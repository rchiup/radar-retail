"""Walmart Chile (lider.cl).

WARNING — check this before using it. As of 2026-08-28 lider.cl's robots.txt disallows
the product paths this fetcher targets, for every user agent except Googlebot:

    Disallow: /supermercado/product*
    Disallow: /catalogo/product*

The site also serves an interception page ("Robot or human?") to non-browser traffic,
so results will usually come back as an anti-bot challenge. This class is provided for
completeness and is untested against live pages on purpose. Confirm the current
robots.txt and your own authorisation before pointing it at the site.
"""

from .browser import PlaywrightFetcher
from .curl import CurlFetcher


class WalmartCL:
    URL_TEMPLATE = "https://www.lider.cl/supermercado/product/sku/{sku}"
    NOT_FOUND_MARKERS = ("no encontramos", "página no encontrada")
    WAIT_SELECTOR = '[class*="price"], [class*="Price"]'
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"

    def parse(self, html: str, product_url: str) -> dict:
        result = super().parse(html, product_url)
        return self.apply_state_prices(
            result,
            selling=(self.embedded_json(html, "currentPrice") or {}).get("price"),
            listed=(self.embedded_json(html, "wasPrice") or {}).get("price"),
        )


class WalmartCurl(WalmartCL, CurlFetcher): pass
class WalmartPlaywright(WalmartCL, PlaywrightFetcher): pass
