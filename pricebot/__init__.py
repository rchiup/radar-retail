"""Stateless retail price fetching.

The whole module is one call: give it a retailer, a SKU and a product link, get back
the prices found on that page. It opens no database, reads no configuration, keeps
nothing between calls and decides nothing — orchestration belongs to whatever imports
this.

    from pricebot import fetch_price

    fetch_price("ripley_cl", sku="2000387067298", proxy="http://user:pass@host:8000")
    # {'new_price': 95990, 'original_price': 121090, 'image_url': 'https://...',
    #  'used_link': 'https://...', 'ip_used': '164.77.38.168', 'screenshot_path': None}

WHAT THE CALLER MUST PROVIDE
----------------------------
This module only answers "what does this page say the price is?". The application
around it owns: which products to track, when to run, retries, proxy rotation, rate
limiting, and storing the results. There is no queue, no scheduler and no retry logic
in here on purpose.

Two things need a human to set up before this works at any scale:

  1. A PROXY ACCOUNT — optional, strongly recommended. Retailers sit behind bot
     protection; a single office or home IP works for a handful of products and then
     starts getting CAPTCHA pages instead of prices, which surfaces as
     error="Blocked by an anti-bot challenge". Retrying from a blocked IP never helps.
     Any rotating residential/datacentre provider works (DataImpulse, Bright Data,
     Oxylabs, ...); pass its endpoint as `proxy="http://user:pass@host:port"`. Prefer
     Chilean exit IPs — several of these sites treat foreign traffic as suspicious.
     Check `ip_used` in the result to confirm the proxy is really in the path.

  2. CHROMIUM — only if you use method="playwright" (required for paris_cl, optional
     elsewhere):  pip install "pricebot[browser]" && playwright install chromium

THREE OUTCOMES
--------------
Every successful call returns one of these, and a caller must tell them apart:

  * new_price is not None                  -> the page was read; store it.
  * status == "PRODUCT_NOT_FOUND"          -> positive evidence the product is gone
                                              (HTTP 404, or the page says so).
                                              Definitive: do not retry.
  * new_price is None and no status        -> the attempt failed; `error` says why
                                              (anti-bot challenge, layout change).
                                              Retry, ideally from a different IP.

Transport failures (DNS, timeout, dead proxy) raise instead of returning. A page that
loads without a price is never reported as a successful zero.

RETAILERS
---------
known_retailers() lists them. All work with the default method="curl" except paris_cl,
which renders prices client-side and needs method="playwright". jumbo_cl needs a `url`
per product; the rest can build one from the SKU alone.

walmart_cl (lider.cl) is provided but untested: that site's robots.txt disallows the
product paths it targets. Check the current robots.txt and your own authorisation
before using it — and, for every retailer, respect each site's terms of service.

Full documentation: https://github.com/eXperto-retail/standalone-retail-fetcher
It is also bundled with the install; `pip show -v pricebot` prints it.
"""

import asyncio
from typing import Any, Optional

from .retailers import RETAILERS, get_fetcher, known_retailers

__version__ = "0.1.0"

__all__ = [
    "fetch_price",
    "fetch_prices",
    "get_fetcher",
    "known_retailers",
    "RETAILERS",
    "__version__",
]


def fetch_price(
    retail: str,
    sku: Optional[str] = None,
    url: Optional[str] = None,
    *,
    method: str = "curl",
    proxy: Optional[str] = None,
    screenshot_to: Optional[str] = None,
) -> dict:
    """
    Fetch the prices on one product page.

    Args:
        retail:        registered retailer key, e.g. "falabella_cl" (see known_retailers()).
        sku:           the retailer's product code. Optional when `url` is given.
        url:           the product page. Optional when the retailer can build one from `sku`.
        method:        "curl" (HTTP, fast) or "playwright" (headless browser, renders JS).
        proxy:         proxy URL, e.g. "http://user:pass@host:port". Strongly recommended.
        screenshot_to: path to write a screenshot to. Requires method="playwright".

    Returns a dict:
        new_price        int | None   the selling price found on the page
        original_price   int | None   the crossed-out price, when the page shows one
        image_url        str | None
        used_link        str          the URL actually requested
        ip_used          str | None   the outbound IP, to confirm the proxy is in the path
        screenshot_path  str | None
        status           str          "PRODUCT_NOT_FOUND", only when the page confirms it
        error            str          why nothing was extracted, e.g. an anti-bot challenge

    A returned dict with neither `new_price` nor `status` is a failed attempt, and
    `error` says why. Transport failures (network, proxy, timeout) raise instead.

    This is a synchronous wrapper. Inside an existing event loop, await
    `get_fetcher(retail, method).fetch(...)` directly.
    """
    return asyncio.run(
        get_fetcher(retail, method).fetch(sku, url, screenshot_to=screenshot_to, proxy=proxy)
    )


def fetch_prices(
    retail: str,
    items: list,
    *,
    method: str = "curl",
    proxy: Optional[str] = None,
    mode: str = "fifo",
) -> list:
    """
    Fetch several product pages of the same retailer in one session.

    With method="playwright" this reuses a single browser for the whole list, which is
    where the time is saved: launching Chromium costs seconds, navigating does not.

    Args:
        items: dicts with "sku", optionally "url" and "screenshot_to".
        mode:  "fifo" one page at a time (lower memory), or "parallel" all at once.

    Returns [(item, result | Exception), ...] in the order given. A product that fails
    never aborts the rest — its exception is returned in its own slot.
    """
    return asyncio.run(
        get_fetcher(retail, method).fetch_many(items, proxy=proxy, mode=mode)
    )
