"""Local browser integration: auth, XLSX/CSV imports, calculations and exports.

Run after npm run build:
    .venv\\Scripts\\python.exe tests\\e2e_workspace.py
Uses a disposable database/server and never scrapes external sites.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from openpyxl import Workbook
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "e2e-workspace"
TEST_TOKEN = "local-e2e-disposable-workspace-key"


def xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Datos"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_server(base: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Disposable API exited before becoming ready")
        try:
            with urlopen(f"{base}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("Disposable API did not become ready")


def run_browser(base: str, fixtures: Path) -> dict:
    xlsx(
        fixtures / "audit.xlsx",
        ["sku", "nombre", "retailer", "url", "pvp", "precio_campana"],
        [
            ["E2E-FALA", "Producto auditado A", "falabella_cl", "https://www.falabella.com/falabella-cl/product/100001/producto-a", 59990, 49990],
            ["E2E-PARIS", "Producto auditado A", "paris_cl", "https://www.paris.cl/producto-a-100002.html", 59990, 49990],
        ],
    )
    xlsx(
        fixtures / "comparables.xlsx",
        ["grupo_comparable", "sku", "nombre", "retailer", "precio", "fecha"],
        [
            ["E2E-MODEL-A", "E2E-FALA", "Modelo equivalente A", "falabella_cl", 45990, "2026-11-01"],
            ["E2E-MODEL-A", "E2E-FALA", "Modelo equivalente A", "falabella_cl", 49990, "2026-11-16"],
            ["E2E-MODEL-A", "E2E-PARIS", "Modelo equivalente A", "paris_cl", 39990, "2026-11-16"],
            ["E2E-UNPAIRED", "E2E-ONE", "Modelo sin par", "paris_cl", 29990, "2026-11-16"],
        ],
    )
    xlsx(
        fixtures / "inventory.xlsx",
        ["sku", "nombre", "retailer", "stock", "ventas_30d", "lead_time", "stock_seguridad"],
        [
            ["E2E-FALA", "Producto riesgo crítico", "falabella_cl", 10, 90, 10, 1],
            ["E2E-PARIS", "Producto saludable", "paris_cl", 200, 30, 5, 10],
            ["E2E-BAD", "Fila incompleta", "paris_cl", "texto inválido", 60, 7, 0],
        ],
    )
    (fixtures / "inventory.csv").write_text(
        "sku;nombre;retailer;stock;ventas_30d;lead_time;stock_seguridad\n"
        "E2E-FALA;Producto riesgo crítico;falabella_cl;10;90;10;1\n"
        "E2E-PARIS;Producto saludable;paris_cl;200;30;5;10\n"
        "E2E-BAD;Fila incompleta;paris_cl;texto inválido;60;7;0\n",
        encoding="utf-8-sig",
    )
    errors: list[str] = []
    external_requests: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)

        def local_only(route) -> None:
            if route.request.url.startswith(base) or route.request.url.startswith(("data:", "blob:")):
                route.continue_()
            else:
                external_requests.append(route.request.url)
                route.abort()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        assert context.request.get(f"{base}/api/campaigns").status == 401
        page.goto(base)
        expect(page.get_by_role("button", name="Entrar al workspace")).to_be_visible()
        page.get_by_label("Clave de acceso").fill("incorrect-key")
        page.get_by_role("button", name="Entrar al workspace").click()
        expect(page.get_by_text("Clave de acceso incorrecta.", exact=True)).to_be_visible()
        page.get_by_label("Clave de acceso").fill(TEST_TOKEN)
        page.get_by_role("button", name="Entrar al workspace").click()
        expect(page.get_by_role("button", name="Nueva campaña", exact=True).first).to_be_visible()
        assert context.request.get(f"{base}/api/campaigns").status == 200

        page.get_by_role("button", name="Nueva campaña", exact=True).first.click()
        dialog = page.get_by_role("dialog", name="Crear campaña")
        dialog.get_by_label("Nombre de campaña").fill("E2E workspace privado")
        dialog.get_by_label("Cliente o marca").fill("Cliente ficticio de prueba")
        with page.expect_response(lambda response: response.url.endswith("/api/campaigns") and response.request.method == "POST") as created_response:
            dialog.get_by_role("button", name="Crear campaña", exact=True).click()
        created = created_response.value.json()
        campaign_id = created["id"]
        expect(page.get_by_role("heading", name="E2E workspace privado", exact=True)).to_be_visible()

        with page.expect_response(lambda response: response.url.endswith(f"/api/campaigns/{campaign_id}/import")) as imported_response:
            page.locator("input[type=file]").set_input_files(str(fixtures / "audit.xlsx"))
        imported = imported_response.value.json()
        assert imported_response.value.status == 200, imported
        assert imported["summary"]["total"] == 2
        assert imported["summary"]["processed"] == 0
        expect(page.get_by_text("E2E-FALA", exact=True).first).to_be_visible()
        # Never execute capture: pending rows verify the original Pricebot workflow is retained.

        page.get_by_role("button", name="Inteligencia competitiva", exact=True).click()
        expect(page.get_by_role("heading", name="Inteligencia competitiva", exact=True)).to_be_visible()
        with page.expect_response(lambda response: response.url.endswith(f"/api/campaigns/{campaign_id}/comparables/import")) as comparable_response:
            page.locator(".intelligence-module input[type=file]").set_input_files(str(fixtures / "comparables.xlsx"))
        comparable = comparable_response.value.json()
        assert comparable_response.value.status == 200, comparable
        assert comparable["imported"] == 4
        model = next(group for group in comparable["groups"] if group["group_id"] == "E2E-MODEL-A")
        assert len(model["items"]) == 2, model
        assert model["gap"] == 10000, model
        assert len(model["history"]) == 3, model
        unpaired = next(group for group in comparable["groups"] if group["group_id"] == "E2E-UNPAIRED")
        assert unpaired["gap"] is None, unpaired
        expect(page.get_by_role("heading", name="Modelo equivalente A", exact=True)).to_be_visible()
        page.get_by_role("button", name="Ver evolución").first.click()
        expect(page.locator(".comparison-history")).to_be_visible()
        expect(page.locator(".comparison-history svg")).to_be_visible()
        page.screenshot(path=str(OUTPUT / "workspace-competition.png"), full_page=True)

        page.get_by_role("button", name="Riesgo de quiebres", exact=True).click()
        expect(page.get_by_role("heading", name="Riesgo de quiebres", exact=True)).to_be_visible()
        for fixture in ["inventory.xlsx", "inventory.csv"]:
            with page.expect_response(lambda response: response.url.endswith(f"/api/campaigns/{campaign_id}/inventory/import")) as inventory_response:
                page.locator(".intelligence-module input[type=file]").set_input_files(str(fixtures / fixture))
            inventory = inventory_response.value.json()
            assert inventory_response.value.status == 200, inventory
            assert inventory["imported"] == 3
            critical = next(item for item in inventory["items"] if item["sku"] == "E2E-FALA")
            malformed = next(item for item in inventory["items"] if item["sku"] == "E2E-BAD")
            assert critical["risk"] == "critical" and critical["coverage_days"] == 3.0, critical
            assert malformed["risk"] == "insufficient" and malformed["stock"] is None, malformed
        expect(page.get_by_text("Fila incompleta", exact=True)).to_be_visible()
        expect(page.get_by_text("Datos incompletos", exact=True).first).to_be_visible()
        page.screenshot(path=str(OUTPUT / "workspace-inventory.png"), full_page=True)

        page.get_by_role("button", name="Radar Brief", exact=False).first.click()
        expect(page.get_by_role("heading", name="Radar Brief", exact=True)).to_be_visible()
        expect(page.get_by_text("Reponer 1 SKU con quiebre inminente", exact=True)).to_be_visible()
        with page.expect_download() as download_event:
            page.get_by_role("button", name="Exportar", exact=True).click()
        download = download_event.value
        assert download.suggested_filename == "radar-brief.json"
        downloaded_path = OUTPUT / "workspace-brief.json"
        download.save_as(str(downloaded_path))
        brief = json.loads(downloaded_path.read_text(encoding="utf-8"))
        assert brief["is_demo"] is False
        assert brief["metrics"]["sku"] == 2
        assert brief["metrics"]["critical_stock"] == 1
        assert brief["metrics"]["compliance_percent"] is None
        page.emulate_media(media="print")
        page.pdf(path=str(OUTPUT / "workspace-brief.pdf"), print_background=True)
        page.emulate_media(media="screen")
        page.screenshot(path=str(OUTPUT / "workspace-brief.png"), full_page=True)

        page.get_by_title("Cerrar sesión", exact=True).click()
        expect(page.get_by_role("button", name="Entrar al workspace", exact=True)).to_be_visible()
        expect(page.get_by_text("Cliente ficticio de prueba", exact=True)).to_have_count(0)
        assert context.request.get(f"{base}/api/campaigns").status == 401
        assert context.request.get(f"{base}/api/campaigns/{campaign_id}/brief").status == 401
        assert context.request.get(f"{base}/screenshots/private.png").status == 401
        assert not errors, errors
        assert not external_requests, external_requests
        browser.close()
    return {"status": "passed", "audit_skus": 2, "comparables_imported": 4, "inventory_rows": 3, "critical_stock": 1, "external_requests": 0, "browser_errors": 0}


def main() -> None:
    if not (ROOT / "dist" / "index.html").exists():
        raise SystemExit("Build missing: run npm run build before this integration test")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="radar-e2e-") as temporary:
        fixtures = Path(temporary)
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        environment = os.environ.copy()
        environment.update({
            "RADAR_DATA_DIR": str(fixtures / "data"),
            "RADAR_REQUIRE_AUTH": "1",
            "RADAR_ACCESS_TOKEN": TEST_TOKEN,
            "PYTHONUNBUFFERED": "1",
        })
        environment.pop("RAILWAY_ENVIRONMENT_ID", None)
        environment.pop("RADAR_SCREENSHOTS_DIR", None)
        environment.pop("RADAR_LOG_PATH", None)
        with (fixtures / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                wait_for_server(base, process)
                result = run_browser(base, fixtures)
                print(json.dumps(result, ensure_ascii=False))
            except BaseException:
                print((fixtures / "server.log").read_text(encoding="utf-8"), file=sys.stderr)
                raise
            finally:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
