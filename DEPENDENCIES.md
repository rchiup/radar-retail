# Dependencias y licencias revisadas

Revisión del 16 de noviembre de 2026, usando `package.json`, `package-lock.json`, `backend/requirements.txt` y los metadatos de paquetes instalados. No se añadió una nueva arquitectura ni proveedor externo.

| Dependencia directa | Versión instalada revisada | Licencia declarada |
| --- | --- | --- |
| React / React DOM | 19.2.8 | MIT |
| Vite | 7.3.6 | MIT |
| TypeScript | 5.9.3 | Apache-2.0 |
| Lucide React | 0.562.0 | ISC |
| Vite React plugin | 5.2.0 | MIT |
| React types | 19.2.18 | MIT |
| React DOM types | 19.2.5 | MIT |
| FastAPI | 0.141.1 | MIT |
| Uvicorn | 0.52.4 | BSD-3-Clause |
| openpyxl | 3.1.5 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| Pillow | 12.3.0 | MIT-CMU |
| Beautiful Soup | 4.15.0 | MIT |
| curl_cffi | 0.16.2 | MIT |
| Playwright Python | 1.62.0 | Apache-2.0 |

Las licencias declaradas de estas dependencias directas permiten uso comercial sujeto a sus condiciones y a conservar sus avisos. Los archivos de licencia originales están dentro de los paquetes instalados. Una distribución debe conservar también los avisos de componentes transitivos y navegadores incluidos.

`package-lock.json` fija las versiones npm reproducibles. Los requisitos Python existentes usan rangos o nombres sin versión exacta; una instalación nueva puede resolver versiones diferentes de las revisadas aquí. Docker conserva el runtime de Playwright definido en su imagen base.

No hay un archivo `LICENSE` del proyecto versionado actualmente. Esta revisión no asigna una licencia al código propio ni modifica derechos del código Pricebot existente. Antes de redistribuir el repositorio a terceros, definir los permisos del código propio y conservar la atribución de dependencias.
