# Radar Retail

Inteligencia comercial con React, FastAPI, SQLite, Pricebot y Playwright. Conserva campañas, carga Excel/CSV, capturas, historial, reportes CSV y ZIP de evidencias.

## Ejecutar y mostrar

```powershell
npm install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

En dos terminales:

```powershell
npm run api
```

```powershell
npm run dev
```

Abrir [Radar Retail local](http://127.0.0.1:5173/). Acceso directo a la [demo comercial](http://127.0.0.1:5173/?demo=1): 50 SKU ficticios, promociones, grupos comparables, inventario e históricos. La demo funciona con solo `npm run dev`, sin API, scraping, credenciales ni servicios externos. Los datos y respaldos de demostración están identificados como DEMO y no son pantallazos oficiales.

Recorrido comercial sugerido: Centro de inteligencia → Auditoría promocional → Competencia → Riesgo de quiebres → Radar Brief. Desde el brief se puede imprimir o guardar como PDF.

Para capturas reales, instalar Chromium una sola vez:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Archivos de entrada

Se aceptan `.csv` y `.xlsx`, hasta 12 MB y 5.000 filas. CSV admite coma o punto y coma. Los ejemplos están en `samples/`.

Auditoría promocional:

```csv
sku,nombre,retailer,url,pvp,precio_campana
SKU-001,Producto A,falabella_cl,https://www.falabella.com/falabella-cl/product/ID/PRODUCTO,49990,39990
```

También acepta `SKU`, `Link`, `PVP`, `PVP Descuento`. En XLSX el nombre de la hoja puede definir el retail. Usar links HTTPS directos a cada producto. El precio observado se obtiene al ejecutar la campaña; un archivo sin precio objetivo permite capturar, pero no determinar cumplimiento.

Comparables:

```csv
grupo_comparable,sku,nombre,retailer,precio,fecha
MODELO-A,SKU-001,Producto A,falabella_cl,39990,2026-11-16
MODELO-A,SKU-002,Producto A,paris_cl,42990,2026-11-16
```

Compartir `grupo_comparable` significa asociar explícitamente productos equivalentes. El sistema no empareja productos por similitud de nombre. Importar solo equivalencias verificadas, incluyendo variante, capacidad y condición de venta.

Inventario:

```csv
sku,nombre,retailer,stock,ventas_30d,lead_time,stock_seguridad
SKU-001,Producto A,falabella_cl,20,90,10,5
```

Velocidad = ventas de 30 días / 30 (o `venta_diaria` importada). Cobertura = stock disponible después del stock de seguridad / velocidad. Riesgo crítico: cobertura ≤ lead time; alto: ≤ 1,5 × lead time; medio: ≤ 2,5 × lead time. Los datos faltantes se muestran como insuficientes. Son reglas operativas basadas en venta promedio, sin forecast avanzado.

## Validación

```powershell
npm run build
.\.venv\Scripts\python.exe -m pip install -r tests\requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tests\e2e_demo.py
.\.venv\Scripts\python.exe tests\e2e_workspace.py
```

## Acceso y persistencia

La API local está en `http://127.0.0.1:8001`. Para acceso remoto, configurar `RADAR_ACCESS_TOKEN` en el servidor y entrar desde la pantalla de acceso. No guardar el secreto en Git ni en el frontend.

Docker y Railway se mantienen. Montar volumen persistente en `/data` y usar `RADAR_DATA_DIR=/data`; ahí se guardan SQLite, capturas y logs. Desplegar explícitamente al servicio existente, evitando crear otro proyecto por accidente.

Los desafíos anti-bot quedan registrados para revisión; la plataforma no los evade. El historial, la fuente y la confianza distinguen capturas oficiales, datos estructurados y referencias indirectas. El brief se genera mediante cálculos y reglas sobre los datos cargados.

Dependencias y licencias: [DEPENDENCIES.md](DEPENDENCIES.md).
