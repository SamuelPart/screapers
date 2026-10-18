# Screapers 🕷

**Scraping web para Linux con interfaz de escritorio** — sin usar la terminal.
Ventana simple y limpia, **bots de IA** que ayudan a extraer y limpiar los
datos, y **seguridad** pensada en dos direcciones: que los sitios no te
bloqueen *y* proteger la información de quien usa la herramienta.

![Linux](https://img.shields.io/badge/Linux-Ubuntu%2FDebian-blue) ![Python](https://img.shields.io/badge/Python-3.10%2B-green)

## Instalar como app (Ubuntu / Debian)

```bash
git clone https://github.com/SamuelPart/screapers.git
cd screapers
./install.sh
```

Después busca **«Screapers»** en el menú de aplicaciones de tu escritorio
(icono propio, sin terminal). El instalador:

- Instala `python3-tk` si falta (único paso con `sudo`).
- Copia la app a `~/.local/share/screapers` y el lanzador a `~/.local/bin/screapers`.
- Crea el acceso directo `~/.local/share/applications/screapers.desktop`.

**Alternativa .deb:** `./packaging/build-deb.sh` genera
`screapers_0.1.0_all.deb` → `sudo apt install ./screapers_0.1.0_all.deb`

**Desinstalar:** `./uninstall.sh`

## Qué hace

1. Pegas una **URL**, ajustas páginas/profundidad/pausa y pulsas **Iniciar**.
2. Extrae enlaces, tablas, encabezados y datos estructurados. Con un
   **selector** simple (`article`, `.producto`, `#lista`, `a`) afinas la extracción.
3. Los **bots de IA** analizan la página, sugieren qué extraer, limpian y
   deduplican los registros, infieren tipos y resumen el contenido.
4. Revisas la tabla de resultados y la **vista previa**, gestionas tus
   **datasets guardados** (cargar/borrar desde la propia ventana) y
   **exportas** a CSV, JSON, JSONL, XLSX o SQLite.

## Bots de IA

| Bot | Trabajo |
|---|---|
| **ScoutBot** | Analiza la página y sugiere la mejor extracción (tablas, JSON-LD, precios…). |
| **CleanerBot** | Limpia espacios, normaliza importes, deduplica y oculta datos personales. |
| **AnalystBot** | Infiere el esquema (url/fecha/precio/texto…) y resume la página. |

Por defecto la IA es **local y offline**: ningún dato sale de tu máquina.
Si defines `SCREAPERS_AI_API_KEY`, se enriquece con una API compatible con
OpenAI — enviando solo texto **redactado** (sin secretos).

## Seguridad

**Para que no te bloqueen (scraping educado, sin evasión abusiva):**
respeta `robots.txt`, pausa con jitter entre peticiones (configurable),
reintentos con backoff honrando `Retry-After`, User-Agent rotado entre
navegadores reales y límite de tamaño por página. Ante 401/403/CAPTCHA se
**detiene y te lo explica**: no burla CAPTCHAs, paywalls ni accesos.

**Para proteger tu información:**
- 🛡 **Anti-SSRF:** bloquea destinos en red privada/local salvo que lo actives.
- 🙈 **PII:** enmascara emails, tarjetas (con validación Luhn), teléfonos, DNI e IPs en resultados y exportaciones.
- 🔑 **Secretos:** redacta tokens/contraseñas en registros; la clave de IA y el proxy **solo** viven en variables de entorno (`SCREAPERS_AI_API_KEY`, `SCREAPERS_PROXY`), nunca se guardan en disco.
- 📜 **Auditoría:** registro local encadenado con SHA-256, verificable desde la propia app.

## Desarrollo

Sin dependencias obligatorias fuera de la biblioteca estándar de Python
(solo `python3-tk` del sistema para la ventana). XLSX usa `openpyxl` si está.

```bash
python3 -m screapers --selftest     # verificación rápida del núcleo
python3 -m unittest discover -s tests -v
python3 -m screapers                # abre la interfaz
```

CI en GitHub Actions (`.github/workflows/ci.yml`): tests, selftest, smoke
test de la ventana real bajo Xvfb y construcción del `.deb` en cada push/PR.

```
screapers/
├── __main__.py     arranque (GUI / --selftest)
├── desktop.py      interfaz Tkinter: URL, opciones, resultados, IA, auditoría
├── scraper.py      motor educado: robots, ritmo, reintentos, BFS mismo dominio
├── parser.py       parser HTML (stdlib) + selectores simples
├── security.py     PII, secretos, anti-SSRF, auditoría SHA-256
├── datasets.py     datasets y exportación CSV/JSON/JSONL/XLSX/SQLite
├── config.py       configuración XDG (sin secretos en disco)
└── ai/             providers (local / API) + bots Scout/Cleaner/Analyst
packaging/          .desktop, icono SVG y constructor .deb
install.sh          instalador como app para el usuario
```

## Uso responsable

Extrae solo datos que tengas derecho a usar, respeta los términos de cada
sitio y la legislación que te aplique. Screapers está diseñado para un
rastreo lento, identificado y respetuoso.
