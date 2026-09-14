"""Base class for retailer fetchers.

A retailer is described by a handful of class attributes plus, when the defaults are
not enough, an overridden `parse()`. The transport (HTTP client or browser) lives in
the subclasses under `curl.py` and `playwright.py`, so adding a retailer usually means
writing one small class per transport.
"""

import json
import asyncio
import os
import re
from typing import Any, Iterable, Optional
from urllib.parse import quote, urljoin

Item = dict  # {"sku": str, "url": str | None, "screenshot_to": str | None}


class ProductFetcher:
    """Fetches price data for one product page."""

    # How to build a product URL from a SKU alone, e.g. "https://site.cl/p/{sku}".
    # Empty when the retailer's URLs cannot be derived from the SKU, in which case a
    # link must be supplied per product.
    URL_TEMPLATE: str = ""
    # Substring that only appears on a "product does not exist" page.
    NOT_FOUND_MARKERS: tuple = ()
    # Substrings found in an anti-bot interstitial and not in a product page.
    # Deliberately full phrases: a bare "captcha" or "/cdn-cgi/challenge-platform"
    # also appears on pages Cloudflare served correctly, which would report healthy
    # fetches as blocked.
    CHALLENGE_MARKERS: tuple = (
        "un paso más",                       # Cloudflare interstitial h1, es-CL
        "complete este punto de seguridad",  # its subtitle
        "verifique que es un ser humano",    # Turnstile checkbox label
        "¿por qué tengo que completar este captcha?",
        "just a moment",                     # en-US h1
        "checking your browser before accessing",
        "why do i have to complete a captcha?",
        "cf-browser-verification",
        "attention required! | cloudflare",
        "servicio de seguridad para protegerse de los ataques en línea",
        "this website is using a security service to protect itself",
        "robot or human?",
        "activate and hold the button to confirm",
    )
    SALE_PRICE_SELECTOR: str = ""
    LIST_PRICE_SELECTOR: str = ""
    PRICE_ATTRIBUTE: str = ""
    # CSS selectors used by the HTML fallback when JSON-LD carries no price.
    PRICE_SELECTORS: str = '[class*="price"], [class*="Price"], [id*="price"]'
    # Selector the browser transport waits for after navigation.
    WAIT_SELECTOR: str = '[class*="price"], [class*="Price"]'
    # Browser context locale/timezone.
    LOCALE: str = "en-US"
    TIMEZONE: str = "UTC"

    async def fetch(self, sku: str, url: Optional[str] = None, *,
                    screenshot_to: Optional[str] = None,
                    proxy: Optional[str] = None) -> dict:
        """Fetch a single product. Implemented by each transport."""
        raise NotImplementedError

    async def fetch_many(self, items: Iterable[Item], *, proxy: Optional[str] = None,
                         mode: str = "fifo") -> list:
        """
        Fetch several products, returning [(item, result | Exception), ...] in order.

        The default is a sequential loop; transports that can share a session across
        products (the browser one) override this.
        """
        results = []
        try:
            delay_s = max(0.0, float(os.getenv("PRICEBOT_DELAY_SECONDS", "1.5")))
        except ValueError:
            delay_s = 1.5
        for index, item in enumerate(items):
            if index:
                await asyncio.sleep(delay_s)
            try:
                result = await self.fetch(
                    item["sku"],
                    item.get("url"),
                    screenshot_to=item.get("screenshot_to"),
                    proxy=proxy,
                )
                results.append((item, result))
            except Exception as exc:  # per-product failure; the caller decides
                results.append((item, exc))
        return results

    # ── URL / result helpers ────────────────────────────────────────────────

    def product_url(self, sku: Optional[str], url: Optional[str] = None) -> str:
        """Prefer the given link; otherwise build one from the SKU."""
        if url and url.strip():
            return url.strip()
        if sku and self.URL_TEMPLATE:
            return self.URL_TEMPLATE.format(sku=quote(str(sku).strip(), safe=""))
        raise ValueError(
            "A product url or a sku is required "
            f"({type(self).__name__} cannot build a URL from a SKU alone)"
            if sku else "A product url or a sku is required"
        )

    @staticmethod
    def empty_result(product_url: str) -> dict:
        return {
            "original_price": None,
            "new_price": None,
            "image_url": None,
            "screenshot_path": None,
            "used_link": product_url,
            "ip_used": None,
        }

    # ── Parsing ─────────────────────────────────────────────────────────────

    def parse(self, html: str, product_url: str) -> dict:
        """
        Extract prices and image from a product page.

        JSON-LD first (most reliable), then a CSS fallback. Returns a partial result
        dict; `status` is only present when the page says the product does not exist.
        """
        from bs4 import BeautifulSoup

        result: dict = {"original_price": None, "new_price": None, "image_url": None}
        soup = BeautifulSoup(html, "html.parser")

        ld_data = self.extract_json_ld(soup)
        if ld_data:
            if ld_data.get("high_price") and ld_data.get("price"):
                result["original_price"] = ld_data["high_price"]
                result["new_price"] = ld_data["price"]
            elif ld_data.get("price"):
                result["new_price"] = ld_data["price"]
            if ld_data.get("image"):
                result["image_url"] = urljoin(product_url, ld_data["image"])

        labelled = self.extract_by_selector(soup)
        result["new_price"] = result["new_price"] or labelled["new_price"]
        if labelled["original_price"] and result["new_price"] and labelled["original_price"] > result["new_price"]:
            result["original_price"] = labelled["original_price"]

        if not result["new_price"]:
            fallback = self.extract_from_html(soup, product_url)
            result["original_price"] = result["original_price"] or fallback["original_price"]
            result["new_price"] = result["new_price"] or fallback["new_price"]
            result["image_url"] = result["image_url"] or fallback["image_url"]

        # Nothing was extracted: decide whether the page says the product is gone, or
        # whether the fetch itself never reached a product page. Only trust the
        # not-found marker here, since the phrase also shows up in footers and search
        # widgets on perfectly valid pages.
        if not result["new_price"]:
            # Markers are only consulted once no price was found, so a healthy product
            # page can never be called delisted. Within that, they are trusted as-is:
            # a not-found page often still serves a logo via og:image, so the presence
            # of an image proves nothing. The precision lives in the markers, which
            # must appear ONLY on a genuine not-found page for that retailer.
            if self.is_not_found(html):
                result["status"] = "PRODUCT_NOT_FOUND"
            elif self.is_challenge(html):
                result["error"] = "Blocked by an anti-bot challenge"
            else:
                result["error"] = "No price found on the page"

        return result

    @staticmethod
    def embedded_json(html: str, key: str) -> Optional[dict]:
        decoder = json.JSONDecoder()
        for match in re.finditer(rf'"{re.escape(key)}"\s*:\s*', html):
            try:
                value, _ = decoder.raw_decode(html, match.end())
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def apply_state_prices(result: dict, selling: Any, listed: Any) -> dict:
        if not isinstance(selling, int): selling = None
        if not isinstance(listed, int): listed = None
        result["new_price"] = result["new_price"] or selling
        result["original_price"] = listed if listed and result["new_price"] and listed > result["new_price"] else None
        if result["new_price"]:
            result.pop("error", None); result.pop("status", None)
        return result

    def is_not_found(self, html: str) -> bool:
        return self._contains_any(html, self.NOT_FOUND_MARKERS)

    def is_challenge(self, html: str) -> bool:
        """True when the response is an interstitial (CAPTCHA, bot check) page."""
        return self._contains_any(html, self.CHALLENGE_MARKERS)

    @staticmethod
    def _contains_any(html: str, markers: tuple) -> bool:
        # Interstitial markup frequently inserts line breaks inside a phrase.
        haystack = re.sub(r"\s+", " ", html.lower())
        return any(re.sub(r"\s+", " ", marker.lower()) in haystack for marker in markers)

    @staticmethod
    def parse_price(text: Optional[str]) -> Optional[int]:
        """Turn '$289.990' or '$ 289990' into 289990."""
        if not text:
            return None
        digits = re.sub(r"[^\d]", "", text.strip())
        return int(digits) if digits else None

    @classmethod
    def extract_json_ld(cls, soup) -> Optional[dict]:
        """Read the first schema.org Product block that actually carries an offer."""
        fallback = None
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(script.string)
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue

            for entry in cls._walk_json_ld(payload):
                if entry.get("@type") == "Product":
                    data = cls._product_from_json_ld(entry)
                    if data and data.get("price"):
                        return data
                    if fallback is None and data and (data.get("name") or data.get("image")):
                        fallback = data
        return fallback

    @classmethod
    def _walk_json_ld(cls, payload) -> Iterable[dict]:
        """
        Yield every node of a JSON-LD payload.

        A block is a dict, a list of dicts, or a dict wrapping its nodes in "@graph" —
        all three are common in the wild, and a Product can be at any of those levels.
        """
        if isinstance(payload, list):
            for item in payload:
                yield from cls._walk_json_ld(item)
        elif isinstance(payload, dict):
            yield payload
            if "@graph" in payload:
                yield from cls._walk_json_ld(payload["@graph"])

    @staticmethod
    def _product_from_json_ld(entry: dict) -> dict:
        data: dict[str, Any] = {"name": entry.get("name")}

        image = entry.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        data["image"] = image

        offers = entry.get("offers", [])
        if not isinstance(offers, list):
            offers = [offers]

        prices = []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            try:
                prices.append(int(float(offer["price"])))
            except (KeyError, TypeError, ValueError):
                continue

        if prices:
            data["price"] = min(prices)
            if max(prices) > min(prices):
                data["high_price"] = max(prices)

        return data

    def extract_by_selector(self, soup) -> dict:
        return {"new_price": self._price_at(soup, self.SALE_PRICE_SELECTOR), "original_price": self._price_at(soup, self.LIST_PRICE_SELECTOR)}

    def _price_at(self, soup, selector: str) -> Optional[int]:
        if not selector: return None
        tag = soup.select_one(selector)
        if tag is None: return None
        if self.PRICE_ATTRIBUTE:
            try: return int(float(tag.get(self.PRICE_ATTRIBUTE)))
            except (TypeError, ValueError): return None
        return self.parse_price(tag.get_text(strip=True))

    def extract_from_html(self, soup, product_url: str) -> dict:
        """
        CSS fallback: the lowest price on the page is the selling price, the previous
        lowest is treated as the list price.
        """
        result: dict = {"original_price": None, "new_price": None, "image_url": None}

        for tag in soup.select(self.PRICE_SELECTORS):
            price = self.parse_price(tag.get_text(strip=True))
            if not price:
                continue
            if result["new_price"] is None or price < result["new_price"]:
                if result["new_price"] is not None:
                    result["original_price"] = result["new_price"]
                result["new_price"] = price

        og_image = soup.select_one('meta[property="og:image"]')
        if og_image and og_image.get("content"):
            result["image_url"] = urljoin(product_url, og_image["content"])
        else:
            img = soup.select_one('img[class*="product"], img[class*="Product"]')
            if img:
                src = img.get("src") or img.get("data-src")
                if src:
                    result["image_url"] = urljoin(product_url, src)

        return result
