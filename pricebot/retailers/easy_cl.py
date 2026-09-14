"""Easy Chile (VTEX). A SKU alone resolves: https://www.easy.cl/<sku>/p."""

from .browser import PlaywrightFetcher
from .curl import CurlFetcher


class EasyCL:
    URL_TEMPLATE = "https://www.easy.cl/{sku}/p"
    NOT_FOUND_MARKERS = ("página no encontrada", "not found")
    WAIT_SELECTOR = '[class*="price"], [class*="Price"]'
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"


class EasyCurl(EasyCL, CurlFetcher): pass
class EasyPlaywright(EasyCL, PlaywrightFetcher): pass
