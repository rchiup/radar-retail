"""Ripley Chile.

Product URLs are slug plus SKU with a trailing "p" — https://simple.ripley.cl/<slug>-<sku>p —
and the slug is optional, so a SKU alone resolves.

Ripley embeds the selling/list prices in its Next.js state. Reading that state avoids
mistaking warranty upsells or related-product prices for the actual product price.
"""

import json
import re

from .browser import PlaywrightFetcher
from .curl import CurlFetcher

_PRICE_STATE = re.compile(r'"parentpricestock"\s*:\s*')


class RipleyCL:
    URL_TEMPLATE = "https://simple.ripley.cl/{sku}p"
    NOT_FOUND_MARKERS = ("no encontrado", "no encontramos")
    WAIT_SELECTOR = '[class*="price"], [class*="Price"]'
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"

    def parse(self, html: str, product_url: str) -> dict:
        result = super().parse(html, product_url)
        prices = self._state_prices(html)
        if not prices:
            return result
        result["new_price"] = result.get("new_price") or prices.get("sale")
        master = prices.get("master")
        if master and result.get("new_price") and master > result["new_price"]:
            result["original_price"] = master
        if result.get("new_price"):
            result.pop("error", None)
            result.pop("status", None)
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


class RipleyCurl(RipleyCL, CurlFetcher): pass
class RipleyPlaywright(RipleyCL, PlaywrightFetcher): pass
