"""Browser transport: headless Chromium via Playwright.

Slower than the HTTP transport but it renders JavaScript and takes screenshots.
`fetch_many()` reuses one browser for the whole batch, which is where most of the
time is saved: launching Chromium costs a few seconds per invocation.

Requires the optional extra:  pip install "pricebot[browser]" && playwright install chromium
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

from .. import proxy as proxy_utils
from .base import Item, ProductFetcher

logger = logging.getLogger("pricebot.browser")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Kept deliberately small: only flags that help headless Chromium behave in
# containers and hide the most obvious automation signals.
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-background-networking",
    "--no-first-run",
    "--mute-audio",
    "--window-size=1920,1080",
]

NAVIGATION_TIMEOUT_MS = 25_000
WAIT_SELECTOR_TIMEOUT_MS = 5_000
DEFAULT_TIMEOUT_MS = 25_000
MAX_BROWSER_ATTEMPTS = 2
CLOSE_TIMEOUT_S = 10

BROWSER_CRASH_SIGNALS = (
    "target page, context or browser has been closed",
    "browser has been closed",
    "target closed",
    "connection closed",
    "browser disconnected",
)


def _is_browser_crash(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(signal in message for signal in BROWSER_CRASH_SIGNALS)


async def _apply_stealth(page) -> None:
    """Intentionally a no-op.

    Radar Retail records blocks honestly. We do not spoof browser fingerprints,
    rotate free proxies, or attempt to bypass CAPTCHA / Cloudflare challenges.
    """
    return


async def _close(*resources) -> None:
    """
    Close pages, contexts and browsers without letting one of them stall the batch.

    A hung close() would otherwise block every remaining product behind it. On timeout
    the resource is left to the process teardown and the batch carries on.
    """
    for resource in resources:
        if resource is None:
            continue
        try:
            await asyncio.wait_for(resource.close(), timeout=CLOSE_TIMEOUT_S)
        except Exception:
            pass


class PlaywrightFetcher(ProductFetcher):
    """Fetches product pages with headless Chromium."""

    async def fetch(self, sku: str, url: Optional[str] = None, *,
                    screenshot_to: Optional[str] = None,
                    proxy: Optional[str] = None) -> dict:
        item: Item = {"sku": sku, "url": url, "screenshot_to": screenshot_to}
        (_, outcome), = await self.fetch_many([item], proxy=proxy)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def fetch_many(self, items: Iterable[Item], *, proxy: Optional[str] = None,
                         mode: str = "fifo") -> List[Tuple[Item, Any]]:
        """
        Run every item through a single browser session.

        mode="fifo"     one tab at a time; lowest memory, the safe default.
        mode="parallel" one tab per item via asyncio.gather; faster, more memory.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                'playwright is required. Install with: pip install "pricebot[browser]" '
                "&& playwright install chromium"
            ) from exc

        items = list(items)
        if not items:
            return []

        playwright_proxy = proxy_utils.for_playwright(proxy)
        async with async_playwright() as pw:
            return await self._session(pw, items, playwright_proxy, mode)

    # ── Browser session ─────────────────────────────────────────────────────

    async def _session(self, pw, items, playwright_proxy, mode) -> List[Tuple[Item, Any]]:
        """Launch the browser and process every item, relaunching once if it crashes."""
        for attempt in range(1, MAX_BROWSER_ATTEMPTS + 1):
            browser = None
            context = None
            try:
                browser = await pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
                context = await self._new_context(browser, playwright_proxy)
                ip_used = await self._detect_ip(context)

                if mode == "parallel":
                    tasks = [self._fetch_item(context, item, ip_used) for item in items]
                    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
                    return list(zip(items, outcomes))

                results = []
                try:
                    delay_s = max(0.0, float(os.getenv("PRICEBOT_DELAY_SECONDS", "1.5")))
                except ValueError:
                    delay_s = 1.5
                for index, item in enumerate(items):
                    if index:
                        await asyncio.sleep(delay_s)
                    try:
                        results.append((item, await self._fetch_item(context, item, ip_used)))
                    except Exception as exc:
                        results.append((item, exc))
                return results

            except Exception as exc:
                if attempt < MAX_BROWSER_ATTEMPTS and _is_browser_crash(exc):
                    continue
                raise
            finally:
                await _close(context, browser)

        raise RuntimeError("Browser session failed without raising")

    async def _new_context(self, browser, playwright_proxy):
        kwargs = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": USER_AGENT,
            "locale": self.LOCALE,
            "timezone_id": self.TIMEZONE,
            "ignore_https_errors": True,
            "extra_http_headers": {"Accept-Language": f"{self.LOCALE},en;q=0.8"},
        }
        if playwright_proxy:
            kwargs["proxy"] = playwright_proxy
        context = await browser.new_context(**kwargs)
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        return context

    async def _fetch_item(self, context, item: Item, ip_used: Optional[str]) -> dict:
        product_url = self.product_url(item["sku"], item.get("url"))
        started = time.perf_counter()
        result = self.empty_result(product_url)
        result["ip_used"] = ip_used
        html = ""

        page = await context.new_page()
        await _apply_stealth(page)  # no-op: we do not spoof fingerprints
        retailer_name = self.__class__.__name__
        try:
            response = await page.goto(product_url, wait_until="domcontentloaded",
                                       timeout=NAVIGATION_TIMEOUT_MS)
            result["http_status"] = response.status if response is not None else None
            logger.info(
                "event=page_request retailer=%s sku=%s url=%s http_status=%s ip=%s",
                retailer_name, item.get("sku", ""), product_url.split("?", 1)[0],
                result["http_status"], ip_used or "-",
            )
            if response is not None and response.status == 404:
                result["status"] = "PRODUCT_NOT_FOUND"
                if item.get("screenshot_to"):
                    await self._screenshot(page, item["screenshot_to"], result)
                return result

            # Give JS-heavy PDPs a bit more time; still no challenge solving.
            try:
                await page.wait_for_selector(self.WAIT_SELECTOR, timeout=WAIT_SELECTOR_TIMEOUT_MS)
            except Exception:
                pass
            try:
                await page.wait_for_load_state("networkidle", timeout=4_000)
            except Exception:
                pass

            html = await page.content()
            # Always capture visual evidence of whatever loaded (PDP or block page).
            if item.get("screenshot_to"):
                await self._screenshot(page, item["screenshot_to"], result)
        finally:
            await _close(page)

        result.update(self.parse(html, product_url))
        if result.get("new_price") is None and result.get("http_status") in {401, 403, 429}:
            result["error"] = f"Blocked by retailer (HTTP {result['http_status']})"
            result["block_type"] = "retailer_http_block"
        if result.get("error") == "Blocked by an anti-bot challenge":
            result["block_type"] = "anti_bot_challenge"
            logger.warning(
                "event=page_blocked retailer=%s sku=%s url=%s reason=anti_bot_challenge",
                retailer_name, item.get("sku", ""), product_url.split("?", 1)[0],
            )
            # Respectful pause after a challenge so we do not hammer the site.
            try:
                pause_s = max(0.0, float(os.getenv("PRICEBOT_BLOCK_PAUSE_SECONDS", "8")))
            except ValueError:
                pause_s = 8.0
            if pause_s:
                await asyncio.sleep(pause_s)
        if result.get("screenshot_path"):
            logger.info(
                "event=screenshot_saved retailer=%s sku=%s path=%s blocked=%s",
                retailer_name, item.get("sku", ""), result.get("screenshot_path"),
                bool(result.get("block_type")),
            )
        logger.info(
            "event=price_parsed retailer=%s sku=%s price=%s status=%s error=%s duration_ms=%s",
            retailer_name, item.get("sku", ""), result.get("new_price"),
            result.get("status", ""), str(result.get("error", ""))[:120],
            round((time.perf_counter() - started) * 1000),
        )
        return result

    @staticmethod
    async def _screenshot(page, path: str, result: dict) -> None:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            # Aporte evidence must include the product price even when it sits below
            # the first viewport. The UI presents the full image in a scrollable viewer.
            await page.screenshot(path=path, full_page=True)
            result["screenshot_path"] = str(path)
        except Exception as exc:
            result["screenshot_error"] = str(exc)

    @staticmethod
    async def _detect_ip(context) -> Optional[str]:
        """Best-effort outbound IP, resolved once per batch. Never fatal."""
        page = None
        try:
            page = await context.new_page()
            await page.goto("https://api.ipify.org?format=json", timeout=8_000)
            data = await page.evaluate(
                "() => { try { return JSON.parse(document.body.innerText); }"
                " catch (e) { return null; } }"
            )
            return data.get("ip") if data else None
        except Exception:
            return None
        finally:
            await _close(page)
