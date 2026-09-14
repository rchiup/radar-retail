from pathlib import Path

from openpyxl import Workbook


rows = [
    ["sku", "descripcion", "url", "retailer", "categoria", "precio_base", "precio_nuevo"],
    [
        "145731903",
        "Ray-Ban Zuri RB4455",
        "https://www.falabella.com/falabella-cl/product/145731903",
        "falabella_cl",
        "Lentes de sol",
        118915,
        107990,
    ],
    ["17214752", "Headset Trust GXT 489 Fayzo Negro", "", "falabella_cl", "Gaming", 23911, 19990],
    ["17214755", "Teclado Gamer GXT 836 Evocx RGB", "", "paris_cl", "Gaming", 18304, 19990],
]

workbook = Workbook()
sheet = workbook.active
sheet.title = "Campana"
for row in rows:
    sheet.append(row)

for width, column in zip([14, 42, 70, 16, 18, 16, 16], sheet.columns):
    sheet.column_dimensions[column[0].column_letter].width = width

output = Path("samples/campana-demo.xlsx")
output.parent.mkdir(exist_ok=True)
workbook.save(output)
