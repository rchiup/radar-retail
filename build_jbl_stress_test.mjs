import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "outputs/jbl-stress-test";
await fs.mkdir(outputDir, { recursive: true });
const wb = Workbook.create();
const data = wb.worksheets.add("Carga completa");
const summary = wb.worksheets.add("Resumen");
const sources = wb.worksheets.add("Fuentes");
const retailers = [
  ["abc", "https://www.abcdin.cl/search?q=jbl"],
  ["jumbo_cl", "https://www.jumbo.cl/search?query=jbl"],
  ["hites", "https://www.hites.com/search?q=jbl"],
  ["tottus_cl", "https://tottus.falabella.com/tottus-cl/search?Ntt=jbl"],
  ["movistar", "https://tienda.movistar.cl/catalogsearch/result/?q=jbl"],
  ["entel", "https://store.entel.cl/search?q=jbl"],
  ["claro", "https://catalogo.clarochile.cl/search?q=jbl"],
  ["falabella_cl", "https://www.falabella.com/falabella-cl/search?Ntt=jbl"],
  ["mercado_libre", "https://listado.mercadolibre.cl/jbl"],
  ["walmart_cl", "https://www.lider.cl/catalogo/searchresult?Ntt=jbl"],
  ["ripley_cl", "https://simple.ripley.cl/search/jbl"],
  ["sodimac_cl", "https://www.sodimac.cl/sodimac-cl/search?Ntt=jbl"],
  ["easy_cl", "https://www.easy.cl/easy-cl/search?text=jbl"],
  ["paris_cl", "https://www.paris.cl/search?q=jbl"],
];
const models = [
  ["JBL Go 4", "JBL-GO4", 49990, 39990],
  ["JBL Clip 5", "JBL-CLIP5", 69990, 54990],
  ["JBL Flip 6", "JBL-FLIP6", 139990, 99990],
  ["JBL Flip 7", "JBL-FLIP7", 179990, 149990],
  ["JBL Charge 5", "JBL-CHARGE5", 189990, 149990],
  ["JBL Charge 6", "JBL-CHARGE6", 229990, 189990],
  ["JBL Xtreme 3", "JBL-XTREME3", 299990, 239990],
  ["JBL Xtreme 4", "JBL-XTREME4", 349990, 279990],
  ["JBL PartyBox Encore", "JBL-ENCORE", 399990, 319990],
  ["JBL PartyBox Club 120", "JBL-CLUB120", 549990, 449990],
  ["JBL PartyBox 320", "JBL-PARTY320", 699990, 579990],
  ["JBL Tune 770NC", "JBL-TUNE770", 129990, 99990],
];

const rows = [["retailer", "sku", "name", "category", "url", "pvp", "precio_campana"]];
for (const [retailer, baseUrl] of retailers) {
  for (const [name, code, pvp, promo] of models) {
    const sku = `${retailer.toUpperCase()}-${code}`;
    const url = `${baseUrl}${baseUrl.includes("?") ? "&" : "?"}sku=${encodeURIComponent(code)}`;
    rows.push([retailer, sku, name, "Audio JBL", url, pvp, promo]);
  }
}
data.getRangeByIndexes(0, 0, rows.length, rows[0].length).values = rows;
data.getRange("A1:G1").format = { fill: "#123B2A", font: { bold: true, color: "#FFFFFF" } };
data.getRange(`A1:G${rows.length}`).format.font = { name: "Arial", size: 10 };
data.getRange(`F2:G${rows.length}`).format.numberFormat = "$#,##0";
data.getRange(`A1:G${rows.length}`).format.wrapText = false;
data.getRange("A:G").format.autofitColumns();
data.getRange("A:A").format.columnWidth = 18;
data.getRange("B:B").format.columnWidth = 24;
data.getRange("C:C").format.columnWidth = 24;
data.getRange("D:D").format.columnWidth = 16;
data.getRange("E:E").format.columnWidth = 64;
data.getRange("F:G").format.columnWidth = 15;
data.freezePanes.freezeRows(1);
data.tables.add(`A1:G${rows.length}`, true, "JBLStressInput");

summary.getRange("A1:D4").values = [
  ["Prueba JBL multiretail", "", "", ""],
  ["Filas totales", rows.length - 1, "Retails", retailers.length],
  ["Modelos por retail", models.length, "Fecha de carga", new Date()],
  ["Nota", "URLs de búsqueda/prueba; validar disponibilidad antes de usar como evidencia", "", ""],
];
summary.mergeCells("A1:D1");
summary.mergeCells("B4:D4");
summary.getRange("A1:D1").format = { fill: "#123B2A", font: { bold: true, color: "#FFFFFF", size: 14 } };
summary.getRange("A2:A4").format.font = { bold: true, color: "#123B2A" };
summary.getRange("C2:C3").format.font = { bold: true, color: "#123B2A" };
summary.getRange("D3").format.numberFormat = "yyyy-mm-dd";
summary.getRange("A6:D6").values = [["Retailer", "Filas", "URL base", "Integración actual"]];
const sumRows = retailers.map(([retailer, baseUrl], i) => [retailer, null, baseUrl, ["easy_cl", "falabella_cl", "jumbo_cl", "paris_cl", "ripley_cl", "sodimac_cl", "tottus_cl", "walmart_cl"].includes(retailer) ? "Soportado" : "Pendiente"]);
summary.getRangeByIndexes(6, 0, sumRows.length, 4).values = sumRows;
for (let i = 0; i < retailers.length; i++) summary.getRange(`B${7 + i}`).formulas = [[`=COUNTIF('Carga completa'!$A$2:$A$${rows.length},A${7 + i})`]];
summary.getRange("A6:D6").format = { fill: "#123B2A", font: { bold: true, color: "#FFFFFF" } };
summary.getRange(`A6:D${6 + retailers.length}`).format.font = { name: "Arial", size: 10 };
summary.getRange("A:D").format.autofitColumns();
summary.getRange("C:C").format.columnWidth = 58;
summary.freezePanes.freezeRows(6);
summary.tables.add(`A6:D${6 + retailers.length}`, true, "JBLRetailSummary");

sources.getRange("A1:C3").values = [
  ["Fuente / uso", "Valor", "Observación"],
  ["Datos", "Catálogo JBL de prueba", "SKUs internos de prueba, no códigos EAN oficiales"],
  ["URLs", "Búsqueda pública de cada retailer", "Confirmar URL de producto antes de una corrida auditable"],
];
sources.getRange("A1:C1").format = { fill: "#123B2A", font: { bold: true, color: "#FFFFFF" } };
sources.getRange("A:C").format.autofitColumns();
sources.getRange("C:C").format.columnWidth = 62;

const check = await wb.inspect({ kind: "table", range: `Resumen!A1:D${6 + retailers.length}`, include: "values,formulas", tableMaxRows: 24, tableMaxCols: 5 });
console.log(check.ndjson);
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(`${outputDir}/jbl-todos-los-retails.xlsx`);
const preview = await wb.render({ sheetName: "Resumen", range: `A1:D${6 + retailers.length}`, scale: 1.5, format: "png" });
await fs.writeFile(`${outputDir}/resumen.png`, new Uint8Array(await preview.arrayBuffer()));
console.log(`${outputDir}/jbl-todos-los-retails.xlsx`);
