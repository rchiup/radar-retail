"""Offline commercial-demo acceptance test and desktop/mobile visual artifacts."""
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    output = Path("outputs/commercial-qa")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1050}, device_scale_factor=1)
        errors = []
        requests = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url) if "/api/" in request.url else None)
        page.route("**/api/**", lambda route: route.abort())
        page.goto("http://127.0.0.1:5173/?demo=1")
        page.get_by_role("heading", name="Centro de inteligencia", exact=True).wait_for()
        page.get_by_text("SKU monitoreados", exact=True).wait_for()
        page.screenshot(path=str(output / "01-intelligence-desktop.png"), full_page=True)
        page.get_by_role("button", name="Auditoría promocional", exact=True).click()
        page.get_by_role("tab", name="Productos 50").wait_for()
        assert page.locator(".product-table-view tbody tr").count() == 50
        page.get_by_label("Filtrar por estado").select_option("non_compliant")
        assert 0 < page.locator(".product-table-view tbody tr").count() < 50
        page.locator(".product-table-view .evidence-button").first.click()
        page.get_by_text("DEMO · DATOS FICTICIOS", exact=True).wait_for()
        assert page.locator(".preview-modal img").count() == 0
        page.screenshot(path=str(output / "02-audit-demo-proof.png"), full_page=True)
        page.get_by_role("button", name="Cerrar", exact=True).click()
        with page.expect_download() as download:
            page.get_by_role("link", name="Reporte", exact=True).click()
        download.value.save_as(str(output / "demo-report.csv"))
        assert "DATOS FICTICIOS" in (output / "demo-report.csv").read_text(encoding="utf-8-sig")
        page.get_by_role("button", name="Inteligencia competitiva", exact=True).click()
        assert page.locator(".comparison-card").count() == 10
        page.get_by_role("button", name="Ver evolución").first.click()
        assert page.locator(".comparison-history svg").count() == 1
        page.screenshot(path=str(output / "03-competition.png"), full_page=True)
        page.get_by_role("button", name="Riesgo de quiebres", exact=True).click()
        page.get_by_role("button", name="Crítico", exact=False).click()
        assert page.locator(".intel-table-wrap tbody tr").count() > 0
        assert "Reponer" in page.locator(".intel-table-wrap tbody").inner_text()
        page.screenshot(path=str(output / "04-inventory.png"), full_page=True)
        page.get_by_role("button", name="Radar Brief", exact=False).click()
        page.get_by_role("heading", name="Prioridades & recomendaciones").wait_for()
        assert page.locator(".brief-finding").count() >= 3
        page.emulate_media(media="print")
        assert page.locator(".brief-document").is_visible()
        assert not page.locator(".sidebar").is_visible()
        page.pdf(path=str(output / "radar-brief-demo.pdf"), format="A4", print_background=True)
        page.emulate_media(media="screen")
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="Centro de inteligencia", exact=True).click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / "05-mobile.png"), full_page=True)
        page.get_by_role("button", name="Auditoría promocional", exact=True).click()
        assert page.locator(".product-card-list").is_visible()
        assert not page.locator(".product-table-view").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / "06-audit-mobile.png"), full_page=True)
        page.get_by_role("button", name="Inteligencia competitiva", exact=True).click()
        page.locator('input[type="file"]').set_input_files("samples/comparables.csv")
        page.get_by_text("6 filas importadas. Cálculos actualizados.").wait_for()
        assert page.locator(".comparison-card").count() == 2
        assert "Sin dato" not in page.locator(".comparison-grid").inner_text()
        page.get_by_role("button", name="Riesgo de quiebres", exact=True).click()
        page.locator('input[type="file"]').set_input_files("samples/inventario.csv")
        page.get_by_text("5 filas importadas. Cálculos actualizados.").wait_for()
        page.get_by_role("button", name="Datos incompletos", exact=False).click()
        assert page.locator(".intel-table-wrap tbody tr").count() == 1
        assert "Completar" in page.locator(".inventory-action").inner_text()
        assert not requests, f"Demo made API requests: {requests}"
        assert not errors, f"Browser errors: {errors}"
        browser.close()
        print("PASS: offline demo, 50 SKU, compliance filter, demo evidence, CSV, 10 comparable groups, history, stock risk, PDF, responsive. Zero API calls.")


if __name__ == "__main__":
    main()
