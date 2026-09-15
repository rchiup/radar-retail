"""ABC (abc.cl), Chile — Salesforce Commerce Cloud."""

from .browser import PlaywrightFetcher
from .curl import CurlFetcher


class AbcCL:
    URL_TEMPLATE = "https://www.abc.cl/{sku}.html"
    NOT_FOUND_MARKERS = ("la página que buscas no existe",)
    SALE_PRICE_SELECTOR = ".js-internet-price [data-value], .js-internet-price"
    LIST_PRICE_SELECTOR = ".js-normal-price [data-value], .js-normal-price"
    PRICE_ATTRIBUTE = "data-value"
    # Avoid the broad [class*=price] scrape that previously picked "31" from unrelated copy.
    PRICE_SELECTORS = ".js-internet-price, .js-normal-price, .price-sales, .product-price"
    WAIT_SELECTOR = ".js-internet-price, .product-price, [itemprop='price']"
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"
    MIN_VALID_PRICE = 500

    def parse(self, html: str, product_url: str) -> dict:
        result = super().parse(html, product_url)
        price = result.get("new_price")
        if isinstance(price, int) and price < self.MIN_VALID_PRICE:
            result["new_price"] = None
            result["original_price"] = None
            result["error"] = (
                f"Precio ABC descartado por valor inválido ({price}). "
                "Revisa selectores o evidencia manual."
            )
        return result


class AbcCurl(AbcCL, CurlFetcher):
    pass


class AbcPlaywright(AbcCL, PlaywrightFetcher):
    pass
