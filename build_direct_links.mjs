import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";
const csv = await fs.readFile("outputs/jbl-stress-test/jbl-direct-links.csv", "utf8");
const lines = csv.trim().split(/\r?\n/).slice(1);
const rows = [["retailer","sku","name","category","url","pvp","precio_campana","link_verificado"]];
for (const line of lines) {
  const [retailer, url, status, verified] = line.split(",");
  if (!url || verified !== "candidate") continue;
  const decoded = url.replace(/\?.*$/, "");
  const m = decoded.match(/(\d{7,})/g);
  const sku = m ? m[m.length - 1] : decoded.split("/").pop().replace(/\.html$/, "");
  const slug = decoded.split("/").pop().replace(/\.html$/, "").replace(/[-_]?\d{7,}$/, "").replace(/[-_]?\d{7,}$/, "");
  rows.push([retailer, sku, `JBL ${slug.replace(/[-_]/g, " ").trim() || "producto"}`, "Audio JBL", decoded, null, null, "candidate"]);
}
const wb = Workbook.create();
const sheet = wb.worksheets.add("Carga directa");
sheet.getRangeByIndexes(0,0,rows.length,rows[0].length).values = rows;
sheet.getRange("A1:H1").format = {fill:"#123B2A", font:{bold:true,color:"#FFFFFF"}};
sheet.getRange(`A1:H${rows.length}`).format.font = {name:"Arial",size:10};
sheet.getRange(`A1:H${rows.length}`).format.wrapText = false;
sheet.getRange("E:E").format.columnWidth = 78;
sheet.getRange("A:D").format.autofitColumns();
sheet.getRange("F:G").format.columnWidth = 15;
sheet.getRange("H:H").format.columnWidth = 18;
sheet.freezePanes.freezeRows(1);
sheet.tables.add(`A1:H${rows.length}`, true, "JBLDirectLinks");
const note = wb.worksheets.add("Notas");
note.getRange("A1:B5").values = [
  ["Campo","Detalle"],
  ["URLs","Extraídas de páginas públicas de cada retailer; se eliminaron parámetros de búsqueda."],
  ["SKU","Código final de la URL cuando estuvo disponible."],
  ["pvp / precio_campana","Vacíos para que cargues los valores de tu campaña."],
  ["Verificación","candidate = enlace de producto detectado; revisar disponibilidad antes de captura."],
];
note.getRange("A1:B1").format = {fill:"#123B2A",font:{bold:true,color:"#FFFFFF"}};
note.getRange("A:B").format.autofitColumns(); note.getRange("B:B").format.columnWidth=100;
await fs.mkdir("outputs/jbl-stress-test",{recursive:true});
const out = await SpreadsheetFile.exportXlsx(wb); await out.save("outputs/jbl-stress-test/jbl-links-directos.xlsx");
console.log(`rows=${rows.length-1}`);
