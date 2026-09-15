"""Walmart Chile (lider.cl).

WARNING — check robots.txt and your authorisation before using this fetcher.
As of 2026-08-28 lider.cl disallows /supermercado/product* for non-Googlebot agents
and often serves "Robot or human?" interstitials. Radar Retail records those blocks
honestly and does not attempt to bypass them.
"""

from .browser import PlaywrightFetcher
from .curl import CurlFetcher


class WalmartCL:
    URL_TEMPLATE = "https://www.lider.cl/supermercado/product/sku/{sku}"
    NOT_FOUND_MARKERS = ("no encontramos", "página no encontrada")
    CHALLENGE_MARKERS = PlaywrightFetcher.CHALLENGE_MARKERS + (
        "robot or human?",
        "are you a human",
    )
    WAIT_SELECTOR = '[class*="price"], [class*="Price"], [data-testid*="price"]'
    PRICE_SELECTORS = '[data-testid*="price"], [class*="ProductPrice"], [class*="price-sell"]'
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"

    def parse(self, html: str, product_url: str) -> dict:
        result = super().parse(html, product_url)
        result = self.apply_state_prices(
            result,
            selling=(self.embedded_json(html, "currentPrice") or {}).get("price"),
            listed=(self.embedded_json(html, "wasPrice") or {}).get("price"),
        )
        if result.get("new_price") is None and not result.get("error"):
            if self.is_challenge(html):
                result["error"] = "Blocked by an anti-bot challenge"
            else:
                result["error"] = (
                    "No price found on the page. "
                    "Lider/Walmart puede estar bloqueando o cambiando el layout; "
                    "requiere revisión manual."
                )
        return result


class WalmartCurl(WalmartCL, CurlFetcher):
    pass


class WalmartPlaywright(WalmartCL, PlaywrightFetcher):
    pass
