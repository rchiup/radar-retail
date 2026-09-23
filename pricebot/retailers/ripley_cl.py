"""Ripley Chile.

Product URLs are slug plus SKU with a trailing "p" — https://simple.ripley.cl/<slug>-<sku>p —
and the slug is optional, so a SKU alone resolves.

Ripley embeds selling/list prices in Next.js state. Reading that state avoids mistaking
warranty upsells or related-product prices for the actual product price.

When Cloudflare/CAPTCHA appears, Radar Retail records the block and keeps the screenshot
of the challenge page. It does not solve or bypass the protection.
"""

import json
import re

from .browser import PlaywrightFetcher
from .curl import CurlFetcher

_PRICE_STATE = re.compile(r'"parentpricestock"\s*:\s*')


class RipleyCL:
    URL_TEMPLATE = "https://simple.ripley.cl/{sku}p"
    NOT_FOUND_MARKERS = ("no encontrado", "no encontramos")
    WAIT_SELECTOR = '[class*="price"], [class*="Price"], [data-testid*="price"]'
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"
    # Ripley serves a different responsive PDP to mobile clients. Use that
    # layout for both parsing and the auditable screenshot; this does not solve
    # or bypass CAPTCHA/Cloudflare challenges.
    VIEWPORT = {"width": 390, "height": 844}
    USER_AGENT = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
        "Mobile/15E148 Safari/604.1"
    )
    MOBILE_CONTEXT = True

    def parse(self, html: str, product_url: str) -> dict:
        result = super().parse(html, product_url)
        prices = self._state_prices(html)
        if prices:
            result["new_price"] = result.get("new_price") or prices.get("sale")
            master = prices.get("master")
            if master and result.get("new_price") and master > result["new_price"]:
                result["original_price"] = master
            if result.get("new_price"):
                result.pop("error", None)
                result.pop("status", None)
                result.pop("block_type", None)
        if result.get("new_price") is None and self.is_challenge(html):
            result["error"] = "Blocked by an anti-bot challenge"
            result["block_type"] = "anti_bot_challenge"
        elif result.get("new_price") is None and not result.get("error"):
            result["error"] = (
                "No price found on the page. "
                "Si hay CAPTCHA/Cloudflare, revisa proxy autorizado o reintento manual."
            )
        return result

    @staticmethod
    def _state_prices(html: str) -> dict:
        match = _PRICE_STATE.search(html)
        if not match:
            return {}
        try:
            state, _ = json.JSONDecoder().raw_decode(html, match.end())
        except ValueError:
            return {}
        block = (state or {}).get("price")
        if not isinstance(block, dict):
            return {}
        return {
            key: value.get("valueNumber")
            for key, value in block.items()
            if isinstance(value, dict) and isinstance(value.get("valueNumber"), int)
        }


class RipleyCurl(RipleyCL, CurlFetcher):
    pass


class RipleyPlaywright(RipleyCL, PlaywrightFetcher):
    async def _prepare_screenshot(self, page, result: dict) -> None:
        """Center the mobile evidence on the product price, not reviews."""
        selectors = (
            '[data-testid*="price"]',
            '[data-test*="price"]',
            '[itemprop="price"]',
            '[class*="product-price" i]',
            '[class*="sale-price" i]',
            '[class*="price" i]',
        )
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible():
                    await locator.scroll_into_view_if_needed(timeout=2_000)
                    await page.wait_for_timeout(250)
                    result["screenshot_focus"] = "price"
                    return
            except Exception:
                continue
        result["screenshot_focus"] = "unavailable"
