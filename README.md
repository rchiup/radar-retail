# Radar Retail MVP

MVP de monitoreo de precios retail con React + FastAPI + pricebot.

## Funcionalidad

- Campanas de monitoreo.
- Carga de productos desde CSV o XLSX.
- Tabla de precio base, precio nuevo, menor mercado y brecha.
- Matriz historica por fecha.
- Captura real con pricebot.
- Screenshots con fecha/hora, campana, SKU, precio, URL e IP incrustados en la imagen.
- Export CSV de analisis.

## Desarrollo local

```powershell
npm install
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\playwright.exe install chromium
npm run api
npm run dev
```

Front local:

```text
http://127.0.0.1:5173/
```

API local:

```text
http://127.0.0.1:8000/
```

## Observabilidad y bloqueos

Cada corrida escribe eventos estructurados en la consola de Uvicorn y en
`backend/data/radar-retail.log` (en Railway, en el volumen configurado por
`RADAR_DATA_DIR`). Se registran campaña, retail, SKU, URL sin query string,
duración, estado HTTP, IP de salida, precio detectado, evidencia y error.
No se guardan cookies, credenciales ni tokens de URL.

Un CAPTCHA o desafío anti-bot queda registrado como `anti_bot_challenge` para
revisión manual. El sistema no intenta evadirlo ni rota IPs automáticamente:
para operar de forma legítima hay que respetar robots.txt, términos del sitio,
límites de frecuencia y usar una integración/autorización del retail cuando
esté disponible.

Para una integración autorizada se puede definir un proxy por retailer (sin
compartir credenciales entre servicios) y una pausa mínima entre páginas:

```powershell
$env:PRICEBOT_PROXY_RIPLEY_CL = "http://usuario:clave@host:puerto"
$env:PRICEBOT_PROXY_WALMART_CL = "http://usuario:clave@host:puerto"
$env:PRICEBOT_DELAY_SECONDS = "2.5"
```

Usa estos perfiles solo con proveedores y sitios que hayan aprobado la
recolección. Google puede servir para descubrir una URL, pero no reemplaza la
captura de la página oficial: sus snippets pueden estar desactualizados y no
constituyen evidencia de precio.

## Formato de carga

El archivo puede ser `.csv` o `.xlsx`. Columnas soportadas:

```text
sku, descripcion, url, retailer, categoria, precio_base, precio_nuevo
```

Tambien acepta el formato que usa Experto Retail:

```text
SKU, Link, PVP, PVP Descuento
```

En XLSX, el nombre de la hoja (por ejemplo `Falabella`) se usa como retail. Tambien acepta alias como
`sku_retail`, `link`, `cadena`, `nombre`, `producto`, `precio_objetivo`.

## Railway

El proyecto incluye `Dockerfile` y `railway.json`.

```powershell
npx @railway/cli login
npx @railway/cli init --name radar-retail-mvp --json
npx @railway/cli up
```

Railway debe tener un plan activo. Si la cuenta esta en trial expirado, el CLI no permite crear ni desplegar servicios.
