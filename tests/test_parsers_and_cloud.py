import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.cloud_scraper import CloudConfigError, DEMO_SITEMAP_ID, assert_retail_cloud_allowed
from pricebot.retailers.abc_cl import AbcCurl
from pricebot.retailers.base import ProductFetcher
from pricebot.retailers.ripley_cl import RipleyCurl


def test_parse_chilean_price():
    assert ProductFetcher.parse_price("$139.990") == 139990
    assert ProductFetcher.parse_price("$ 54.990") == 54990
    assert ProductFetcher.parse_price("31") == 31


def test_abc_rejects_absurd_low_price():
    html = """
    <html><body>
      <div class="js-internet-price"><span data-value="31">$31</span></div>
      <div>algo 31 en el texto</div>
    </body></html>
    """
    result = AbcCurl().parse(html, "https://www.abc.cl/producto/29133522.html")
    assert result.get("new_price") is None
    assert "inválido" in (result.get("error") or "").lower() or "invalido" in (result.get("error") or "").lower()


def test_ripley_state_price_preferred():
    html = '''
    <html><body>
      <script>window.__X={"parentpricestock":{"price":{"sale":{"valueNumber":95990},"master":{"valueNumber":121090}}}}</script>
      <div class="price">$1.000</div>
    </body></html>
    '''
    # Ensure regex finds parentpricestock even nested loosely
    html = '"parentpricestock": {"price": {"sale": {"valueNumber": 95990}, "master": {"valueNumber": 121090}}}'
    result = RipleyCurl().parse("<html>" + html + "</html>", "https://simple.ripley.cl/x-2000387067298p")
    assert result.get("new_price") == 95990
    assert result.get("original_price") == 121090


def test_demo_sitemap_blocked(monkeypatch):
    monkeypatch.setenv("WEBSCRAPER_SITEMAP_ID", DEMO_SITEMAP_ID)
    monkeypatch.setenv("WEBSCRAPER_TOKEN", "dummy-token")
    try:
        assert_retail_cloud_allowed()
        assert False, "should have blocked demo sitemap"
    except CloudConfigError as exc:
        assert DEMO_SITEMAP_ID in str(exc)
