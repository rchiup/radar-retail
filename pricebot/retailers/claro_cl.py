"""Claro Chile product pages and their explicit missing-product handling."""
from .browser import PlaywrightFetcher
from .curl import CurlFetcher

class ClaroCL:
    URL_TEMPLATE = ""
    NOT_FOUND_MARKERS = ("<title>tienda claro chile</title>", "<title> error genérico </title>")
    SALE_PRICE_SELECTOR = ".price_display .price"
    LIST_PRICE_SELECTOR = ".price_display .old_price"
    WAIT_SELECTOR = ".price_display, [class*='price']"
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"

    def parse(self, html: str, product_url: str) -> dict:
        if self.is_not_found(html):
            return {"original_price": None, "new_price": None, "image_url": None, "status": "PRODUCT_NOT_FOUND"}
        return super().parse(html, product_url)

class ClaroCurl(ClaroCL, CurlFetcher): pass
class ClaroPlaywright(ClaroCL, PlaywrightFetcher): pass
