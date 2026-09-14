"""ABC (abc.cl), Chile — Salesforce Commerce Cloud."""
from .browser import PlaywrightFetcher
from .curl import CurlFetcher

class AbcCL:
    URL_TEMPLATE = "https://www.abc.cl/{sku}.html"
    NOT_FOUND_MARKERS = ("la página que buscas no existe",)
    SALE_PRICE_SELECTOR = ".js-internet-price [data-value]"
    LIST_PRICE_SELECTOR = ".js-normal-price [data-value]"
    PRICE_ATTRIBUTE = "data-value"
    WAIT_SELECTOR = ".js-internet-price, [class*='price']"
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"

class AbcCurl(AbcCL, CurlFetcher): pass
class AbcPlaywright(AbcCL, PlaywrightFetcher): pass
