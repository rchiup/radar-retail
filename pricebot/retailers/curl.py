"""HTTP transport: curl_cffi with a Chrome TLS/JA3 fingerprint.

Fast and cheap, but it only sees server-rendered HTML and cannot take screenshots.
Use the Playwright transport when the page needs JavaScript or a screenshot.
"""

import logging
import time
from typing import Optional

from .base import ProductFetcher

logger = logging.getLogger("pricebot.curl")

IP_ECHO_URL = "https://api.ipify.org?format=json"
REQUEST_TIMEOUT = 25


class CurlFetcher(ProductFetcher):
    """Fetches the product page over HTTP, impersonating Chrome."""

    async def fetch(self, sku: str, url: Optional[str] = None, *,
                    screenshot_to: Optional[str] = None,
                    proxy: Optional[str] = None) -> dict:
        try:
            from curl_cffi import requests as curl_requests
        except ImportError as exc:
            raise RuntimeError("curl_cffi is required for the curl fetch method") from exc

        product_url = self.product_url(sku, url)
        started = time.perf_counter()
        retailer_name = self.__class__.__name__
        result = self.empty_result(product_url)
        result["ip_used"] = self._public_ip(curl_requests, proxy)

        try:
            response = curl_requests.get(
                product_url, impersonate="chrome", timeout=REQUEST_TIMEOUT, proxy=proxy
            )
        except Exception as exc:
            logger.warning("event=request_exception retailer=%s sku=%s url=%s error=%s duration_ms=%s", retailer_name, sku, product_url.split("?", 1)[0], str(exc)[:180], round((time.perf_counter() - started) * 1000))
            raise RuntimeError(f"Failed to fetch {product_url}: {exc}") from exc

        result["http_status"] = response.status_code
        logger.info("event=response retailer=%s sku=%s url=%s http_status=%s ip=%s", retailer_name, sku, product_url.split("?", 1)[0], response.status_code, result.get("ip_used") or "-")

        # A 404 means the product is gone, not that the attempt failed: report it as
        # such so the job settles instead of burning its retries.
        if response.status_code == 404:
            result["status"] = "PRODUCT_NOT_FOUND"
            return result
        if response.status_code >= 400:
            # Some retailers return a marker-gated missing-product page with 400
            # instead of 404 (notably Claro). Keep curl/browser semantics aligned.
            if self.is_not_found(response.text):
                result["status"] = "PRODUCT_NOT_FOUND"
                return result
            raise RuntimeError(f"Failed to fetch {product_url}: HTTP {response.status_code}")

        result.update(self.parse(response.text, product_url))
        if result.get("new_price") is None and response.status_code in {401, 403, 429}:
            result["error"] = f"Blocked by retailer (HTTP {response.status_code})"
            result["block_type"] = "retailer_http_block"
        if result.get("error") == "Blocked by an anti-bot challenge":
            result["block_type"] = "anti_bot_challenge"
            logger.warning("event=anti_bot_challenge retailer=%s sku=%s url=%s", retailer_name, sku, product_url.split("?", 1)[0])
        logger.info("event=parsed retailer=%s sku=%s price=%s status=%s error=%s duration_ms=%s", retailer_name, sku, result.get("new_price"), result.get("status", ""), str(result.get("error", ""))[:120], round((time.perf_counter() - started) * 1000))

        if screenshot_to:
            result["screenshot_error"] = "screenshots require the playwright fetch method"
        return result

    @staticmethod
    def _public_ip(curl_requests, proxy: Optional[str]) -> Optional[str]:
        """Best-effort outbound IP, useful to confirm a proxy is actually in use."""
        try:
            response = curl_requests.get(
                IP_ECHO_URL, impersonate="chrome", timeout=5, proxy=proxy
            )
            response.raise_for_status()
            return response.json().get("ip")
        except Exception:
            return None
