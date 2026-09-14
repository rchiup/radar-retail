"""Hites (hites.com), Chile — Salesforce Commerce Cloud."""
from .browser import PlaywrightFetcher
from .curl import CurlFetcher

class HitesCL:
    URL_TEMPLATE = "https://www.hites.com/{sku}.html"
    NOT_FOUND_MARKERS = ("página no disponible",)
    SALE_PRICE_SELECTOR = ".price-item.sales .value[content]"
    LIST_PRICE_SELECTOR = ".price-item.list .value[content]"
    PRICE_ATTRIBUTE = "content"
    WAIT_SELECTOR = ".price-item, [class*='price']"
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"

class HitesCurl(HitesCL, CurlFetcher): pass
class HitesPlaywright(HitesCL, PlaywrightFetcher): pass
