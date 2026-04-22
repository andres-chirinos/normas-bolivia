import requests
from bs4 import BeautifulSoup
import argparse
import json
import logging
import time
import re
import os
from pathlib import Path
from urllib.parse import urljoin

try:
    from markdownify import markdownify as md
except ImportError:
    md = None

BASE_URL = "http://www.gacetaoficialdebolivia.gob.bo"
REQUEST_TIMEOUT_SECONDS = 60
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}
MAX_REINTENTOS_HTTP = 3
RETRY_SLEEP_SECONDS = 2
DEFAULT_OUTPUT_JSONL = Path("data/archivo_gaceta_bolivia.jsonl")
DEFAULT_STATE_FILE = Path("data/archivo_gaceta_bolivia.resume.json")
DEFAULT_LOG_FILE = Path("logs/download_gaceta.log")

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False

# Rate limit propio del crawler (ajustable)
RATE_LIMIT_SECONDS = 0.5
REQUESTS_BEFORE_COOLDOWN = 120
COOLDOWN_SECONDS = 20


def _limpiar_espacios(texto):
    return re.sub(r"\s+", " ", texto).strip()


def _html_a_markdown(nodo):
    """Conversor HTML -> Markdown ligero para el contenido de la norma."""
    if nodo is None:
        return ""

    if getattr(nodo, "name", None) is None:
        return str(nodo)

    tag = nodo.name.lower()

    if tag in {"script", "style", "title", "hr", "img"}:
        return ""

    if tag == "br":
        return "\n"

    contenido = "".join(_html_a_markdown(hijo) for hijo in nodo.children)
    contenido = contenido.strip()

    if tag in {"strong", "b"}:
        if not contenido:
            return ""
        return f"**{contenido}**"
    if tag in {"em", "i"}:
        if not contenido:
            return ""
        return f"*{contenido}*"
    if tag == "a":
        href = nodo.get("href", "").strip()
        href = urljoin(BASE_URL, href) if href else ""
        return f"[{contenido}]({href})" if href else contenido
    if tag == "li":
        return f"- {contenido}\n"
    if tag in {"ul", "ol"}:
        return f"{contenido}\n"
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        nivel = int(tag[1])
        return f"{'#' * nivel} {contenido}\n\n"
    if tag in {"p", "div", "center", "fieldset", "legend", "font"}:
        return f"{contenido}\n\n" if contenido else ""

    return contenido


def _html_a_markdown_moderno(nodo):
    """Conversión HTML -> Markdown usando markdownify cuando está disponible."""
    if nodo is None:
        return ""

    # Evita convertir elementos que no aportan al contenido normativo.
    for tag in nodo.find_all(["script", "style", "title", "hr", "img"]):
        tag.decompose()

    if md is None:
        # Fallback: conserva comportamiento previo si markdownify no está instalado.
        return _html_a_markdown(nodo)

    return md(
        str(nodo),
        heading_style="ATX",
        bullets="-",
        strip=["script", "style", "title", "hr", "img"],
    )


def _registrar_error(contexto, exc, nivel="warning"):
    mensaje = f"{contexto}: {exc}"
    if nivel == "error":
        LOGGER.error(mensaje, exc_info=True)
    else:
        LOGGER.warning(mensaje)


def _configurar_logging(log_path):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if LOGGER.handlers:
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)


def _cargar_estado_resumen(state_path):
    state_path = Path(state_path)
    if not state_path.exists():
        return None

    try:
        with state_path.open("r", encoding="utf-8") as fh:
            estado = json.load(fh)
        if not isinstance(estado, dict):
            return None
        return estado
    except (OSError, json.JSONDecodeError) as exc:
        _registrar_error(f"No se pudo leer el estado de reanudación {state_path}", exc)
        return None


def _guardar_estado_resumen(state_path, estado):
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with state_path.open("w", encoding="utf-8") as fh:
            json.dump(estado, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        _registrar_error(f"No se pudo guardar el estado de reanudación {state_path}", exc, nivel="error")
        raise


def _borrar_estado_resumen(state_path):
    state_path = Path(state_path)
    try:
        if state_path.exists():
            state_path.unlink()
    except OSError as exc:
        _registrar_error(f"No se pudo borrar el estado de reanudación {state_path}", exc)


def _firma_norma(norma):
    return "|".join(
        [
            str(norma.get("titulo") or ""),
            str(norma.get("fecha_publicacion") or ""),
            str(norma.get("url_word") or ""),
            str(norma.get("url_pdf") or ""),
        ]
    )


def _normalizar_markdown(texto):
    # Limpia espacios por línea y reduce saltos de línea excesivos.
    # Elimina prólogos XML/DOCTYPE que a veces llegan mezclados con el contenido.
    texto = re.sub(
        r'xml\s+version\s*=\s*"[^"]*"\s*encoding\s*=\s*"[^"]*"\s*\??',
        "",
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(r'html\s+public\s+"[^"]*"\s+"[^"]*"', "", texto, flags=re.IGNORECASE)
    texto = re.sub(r'html\s+public\s+"[^"]*"', "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<!doctype[^>]*>", "", texto, flags=re.IGNORECASE)

    lineas = [linea.rstrip() for linea in texto.splitlines()]
    lineas_limpias = []
    for linea in lineas:
        linea_strip = linea.strip()
        if not linea_strip:
            lineas_limpias.append("")
            continue

        # Quita restos de encabezados basura frecuentes por HTML malformado.
        if re.fullmatch(r"(doctype|html|public)", linea_strip, flags=re.IGNORECASE):
            continue
        if re.fullmatch(
            r'"?http://www\.w3\.org/TR/xhtml1/DTD/xhtml1-transitional\.dtd"?',
            linea_strip,
            flags=re.IGNORECASE,
        ):
            continue
        if re.fullmatch(r"\*{2,}", linea_strip):
            continue

        lineas_limpias.append(linea_strip)

    texto = "\n".join(lineas_limpias)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _obtener_soup(url, timeout=REQUEST_TIMEOUT_SECONDS):
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() in {"iso-8859-1", "latin-1"}:
        response.encoding = response.apparent_encoding or "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def _crear_estado_rate_limit():
    return {"total_requests": 0}


def _aplicar_rate_limit(rate_limit_state):
    if rate_limit_state is None:
        return

    total_requests = rate_limit_state.get("total_requests", 0)

    if total_requests > 0 and RATE_LIMIT_SECONDS > 0:
        time.sleep(RATE_LIMIT_SECONDS)

    if (
        total_requests > 0
        and REQUESTS_BEFORE_COOLDOWN > 0
        and total_requests % REQUESTS_BEFORE_COOLDOWN == 0
    ):
        print(
            f"Enfriamiento activado: {COOLDOWN_SECONDS}s tras {total_requests} consultas."
        )
        time.sleep(COOLDOWN_SECONDS)


def _obtener_soup_con_control(url, timeout=REQUEST_TIMEOUT_SECONDS, rate_limit_state=None):
    ultimo_error = None
    for intento in range(1, MAX_REINTENTOS_HTTP + 1):
        _aplicar_rate_limit(rate_limit_state)
        try:
            return _obtener_soup(url, timeout=timeout)
        except requests.RequestException as exc:
            ultimo_error = exc
            _registrar_error(
                f"Error HTTP al consultar {url} (intento {intento}/{MAX_REINTENTOS_HTTP})",
                exc,
            )
            if intento < MAX_REINTENTOS_HTTP:
                time.sleep(RETRY_SLEEP_SECONDS)
        finally:
            if rate_limit_state is not None:
                rate_limit_state["total_requests"] = rate_limit_state.get("total_requests", 0) + 1

    raise requests.RequestException(str(ultimo_error) if ultimo_error else f"No se pudo consultar {url}")


def _append_jsonl(file_path, item):
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False))
            f.write("\n")
    except OSError as exc:
        _registrar_error(f"No se pudo escribir en {file_path}", exc, nivel="error")
        raise


def _jsonl_a_json(jsonl_path, json_path):
    try:
        with open(jsonl_path, "r", encoding="utf-8") as src, open(
            json_path, "w", encoding="utf-8"
        ) as dst:
            dst.write("[\n")
            first = True
            for line in src:
                row = line.strip()
                if not row:
                    continue
                if not first:
                    dst.write(",\n")
                dst.write(row)
                first = False
            dst.write("\n]\n")
    except OSError as exc:
        _registrar_error(f"No se pudo convertir {jsonl_path} a JSON", exc, nivel="error")
        raise


def _extraer_estadisticas_busqueda(soup):
    """Extrae página actual, total de páginas y total de normas desde #titulos-bloque."""
    bloque = soup.find(id="titulos-bloque") or soup
    texto = _limpiar_espacios(bloque.get_text(" ", strip=True))

    pagina_actual = None
    total_paginas = None
    total_normas = None

    # Ejemplo esperado: "Página 2 de 1636 // mostrando normas 21 - 40 // 32703 en total"
    match_paginas = re.search(r"P[aá]gina\s+(\d+)\s+de\s+(\d+)", texto, re.IGNORECASE)
    if match_paginas:
        pagina_actual = int(match_paginas.group(1))
        total_paginas = int(match_paginas.group(2))

    match_total = re.search(r"(\d+)\s+en\s+total", texto, re.IGNORECASE)
    if match_total:
        total_normas = int(match_total.group(1))

    return {
        "pagina_actual": pagina_actual,
        "total_paginas": total_paginas,
        "total_normas": total_normas,
    }


def descargar_norma_markdown(
    url_detalle, timeout=REQUEST_TIMEOUT_SECONDS, rate_limit_state=None
):
    try:
        soup = _obtener_soup_con_control(
            url_detalle, timeout=timeout, rate_limit_state=rate_limit_state
        )
    except requests.RequestException as exc:
        _registrar_error(f"No se pudo descargar la norma en {url_detalle}", exc)
        return ""

    contenedor = soup.find(id="seleccion")
    if not contenedor:
        # Fallback observado en páginas de detalle verGratis_gob1.
        candidatos = soup.find_all("div", class_="contentpaneopen")
        if candidatos:
            contenedor = max(candidatos, key=lambda n: len(n.get_text(" ", strip=True)))

    if not contenedor:
        return "[NORMA_NO_DISPONIBLE_EN_HTML]"

    # El cuerpo normativo suele venir dentro del primer <font> cuando existe.
    cuerpo = contenedor.find("font") or contenedor

    # Eliminamos bloques no normativos frecuentes.
    try:
        for nodo in cuerpo.find_all(["fieldset", "img", "script", "style", "title", "hr"]):
            nodo.decompose()

        markdown = _html_a_markdown_moderno(cuerpo)
        markdown = _normalizar_markdown(markdown)
        if not markdown:
            return "[NORMA_NO_DISPONIBLE_EN_HTML]"
        return markdown
    except Exception as exc:
        _registrar_error(f"Error al convertir HTML a Markdown para {url_detalle}", exc)
        return "[NORMA_NO_DISPONIBLE_EN_HTML]"


def extraer_normativas(
    fecha_inicio,
    fecha_fin,
    pagina_inicial=1,
    paginas_a_extraer=None,
    output_jsonl_path=None,
    reset_output_jsonl=False,
    resume=False,
    state_file_path=DEFAULT_STATE_FILE,
):
    # La URL base utiliza la convención de CakePHP para la paginación (/page:X)
    base_url = f"http://www.gacetaoficialdebolivia.gob.bo/normas/buscarFecha/{fecha_inicio}/{fecha_fin}/page:{{}}"

    todas_las_normas = []
    rate_limit_state = _crear_estado_rate_limit()
    estado_resumen = {
        "pagina": pagina_inicial,
        "indice_tarjeta": 0,
        "ultima_firma": None,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "output_jsonl_path": str(output_jsonl_path) if output_jsonl_path else None,
    }

    if resume:
        estado_cargado = _cargar_estado_resumen(state_file_path)
        if estado_cargado:
            estado_resumen.update(estado_cargado)
            LOGGER.info(
                "Reanudando desde página %s, tarjeta %s.",
                estado_resumen.get("pagina"),
                estado_resumen.get("indice_tarjeta"),
            )
        else:
            LOGGER.warning(
                "Se pidió --resume pero no hay estado de reanudación válido. Se iniciará desde el comienzo."
            )

    if output_jsonl_path and reset_output_jsonl:
        try:
            with open(output_jsonl_path, "w", encoding="utf-8"):
                pass
        except OSError as exc:
            _registrar_error(f"No se pudo inicializar {output_jsonl_path}", exc, nivel="error")
            raise

    pagina = int(estado_resumen.get("pagina") or pagina_inicial)
    indice_tarjeta_inicio = int(estado_resumen.get("indice_tarjeta") or 0)
    ultima_pagina = None

    while True:
        if paginas_a_extraer is not None and pagina >= pagina_inicial + paginas_a_extraer:
            break
        if ultima_pagina is not None and pagina > ultima_pagina:
            break

        LOGGER.info("Procesando página %s...", pagina)
        url = base_url.format(pagina)

        try:
            # Añadimos un timeout por si el servidor gubernamental tarda en responder
            soup = _obtener_soup_con_control(
                url, timeout=REQUEST_TIMEOUT_SECONDS, rate_limit_state=rate_limit_state
            )
        except requests.RequestException as e:
            _registrar_error(f"Error de conexión en la página {pagina}", e)
            break

        # Identificamos el bloque iterativo principal (las tarjetas de cada ley/decreto)
        tarjetas = soup.find_all("div", class_="fondo-paper")

        # Detecta automáticamente el total de páginas si el usuario no define límite.
        if paginas_a_extraer is None and ultima_pagina is None:
            stats = _extraer_estadisticas_busqueda(soup)
            if stats["total_paginas"]:
                ultima_pagina = stats["total_paginas"]
                msg_total = (
                    f"({stats['total_normas']} normas)" if stats["total_normas"] is not None else ""
                )
                print(f"Total detectado: {ultima_pagina} páginas {msg_total}".strip())

        # Condición de salida si la página ya no tiene resultados
        if not tarjetas:
            LOGGER.info("No se encontraron más normativas. Fin del listado.")
            break

        if resume and indice_tarjeta_inicio:
            LOGGER.info(
                "Reanudando en la tarjeta %s de la página %s.",
                indice_tarjeta_inicio + 1,
                pagina,
            )

        for indice_tarjeta, tarjeta in enumerate(tarjetas):
            if indice_tarjeta < indice_tarjeta_inicio:
                continue
            norma = {}
            try:
                # 1. Título / Tipo y Número de Norma
                h6 = tarjeta.find("h6")
                norma["titulo"] = h6.text.strip() if h6 else "Sin título"

                # 2. Metadatos (Edición y Fecha)
                texto_meta = tarjeta.find("p", class_="card-text")
                if texto_meta:
                    texto_limpio = texto_meta.get_text(" ", strip=True)
                    # Extraemos la fecha con una expresión regular simple
                    match_fecha = re.search(
                        r"Fecha de Publicación:\s*([\d\-]+)", texto_limpio
                    )
                    norma["fecha_publicacion"] = (
                        match_fecha.group(1) if match_fecha else None
                    )

                    match_edicion = re.search(
                        r"Publicado en edici[oó]n:\s*(\d+)", texto_limpio, re.IGNORECASE
                    )
                    norma["edicion"] = match_edicion.group(1) if match_edicion else None

                # 3. Resumen de la norma
                resumen_div = tarjeta.find("div", class_="contentpaneopen")
                norma["resumen"] = resumen_div.text.strip() if resumen_div else ""

                # 4. Enlaces a los documentos originales
                footer = tarjeta.find("div", class_="card-footer")
                if footer:
                    enlaces = footer.find_all("a")
                    for enlace in enlaces:
                        texto_enlace = enlace.text.lower()
                        # Reconstruimos la URL absoluta sumando el dominio base
                        href_raw = enlace.get("href")
                        href = href_raw if isinstance(href_raw, str) else ""
                        href_absoluto = urljoin(BASE_URL, href)

                        if "pdf" in texto_enlace:
                            norma["url_pdf"] = href_absoluto
                        elif "word" in texto_enlace:
                            norma["url_word"] = href_absoluto

                if norma.get("url_word"):
                    norma["norma_markdown"] = descargar_norma_markdown(
                        norma["url_word"], rate_limit_state=rate_limit_state
                    )

                if output_jsonl_path:
                    _append_jsonl(output_jsonl_path, norma)

                todas_las_normas.append(norma)

                estado_resumen.update(
                    {
                        "pagina": pagina,
                        "indice_tarjeta": indice_tarjeta + 1,
                        "ultima_firma": _firma_norma(norma),
                        "titulo": norma.get("titulo"),
                    }
                )
                _guardar_estado_resumen(state_file_path, estado_resumen)
            except Exception as exc:
                estado_resumen.update(
                    {
                        "pagina": pagina,
                        "indice_tarjeta": indice_tarjeta,
                        "titulo": norma.get("titulo"),
                    }
                )
                _guardar_estado_resumen(state_file_path, estado_resumen)
                _registrar_error(
                    f"Error procesando la página {pagina}, norma {indice_tarjeta + 1}",
                    exc,
                )
                continue

        estado_resumen.update(
            {
                "pagina": pagina + 1,
                "indice_tarjeta": 0,
                "ultima_firma": estado_resumen.get("ultima_firma"),
            }
        )
        _guardar_estado_resumen(state_file_path, estado_resumen)
        indice_tarjeta_inicio = 0

        LOGGER.info(
            "Página %s completada. Registros acumulados: %s | Consultas HTTP: %s",
            pagina,
            len(todas_las_normas),
            rate_limit_state["total_requests"],
        )

        pagina += 1

    return todas_las_normas


def _parse_args():
    parser = argparse.ArgumentParser(description="Crawler de normas de la Gaceta Oficial.")
    parser.add_argument(
        "--fecha-inicio",
        default="1800-01-01",
        help="Fecha de inicio en formato YYYY-MM-DD.",
    )
    parser.add_argument(
        "--fecha-fin",
        default="2026-01-01",
        help="Fecha de fin en formato YYYY-MM-DD.",
    )
    parser.add_argument(
        "--output-jsonl",
        default=str(DEFAULT_OUTPUT_JSONL),
        help="Ruta del archivo JSONL de salida.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reanuda desde el último checkpoint guardado.",
    )
    parser.add_argument(
        "--log-file",
        default=str(DEFAULT_LOG_FILE),
        help="Ruta del archivo de log persistente.",
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help="Ruta del checkpoint de reanudación.",
    )
    parser.add_argument(
        "--pagina-inicial",
        type=int,
        default=1,
        help="Página inicial a procesar.",
    )
    parser.add_argument(
        "--paginas-a-extraer",
        type=int,
        default=None,
        help="Cantidad de páginas a extraer. Si se omite, recorre todo el rango.",
    )
    return parser.parse_args()


# Ejecución del crawler
if __name__ == "__main__":
    args = _parse_args()

    _configurar_logging(args.log_file)

    try:
        datos = extraer_normativas(
            args.fecha_inicio,
            args.fecha_fin,
            pagina_inicial=args.pagina_inicial,
            paginas_a_extraer=args.paginas_a_extraer,
            output_jsonl_path=args.output_jsonl,
            reset_output_jsonl=not args.resume,
            resume=args.resume,
            state_file_path=args.state_file,
        )

        _borrar_estado_resumen(args.state_file)

        print(
            f"\nExtracción completada. Se guardaron {len(datos)} registros en {args.output_jsonl}."
        )
    except KeyboardInterrupt:
        _registrar_error("Extracción interrumpida por el usuario", KeyboardInterrupt())
        raise SystemExit(130)
    except Exception as exc:
        _registrar_error("Error fatal durante la ejecución del crawler", exc, nivel="error")
        raise SystemExit(1)
