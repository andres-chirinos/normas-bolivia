import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os
from urllib.parse import urljoin

try:
    from markdownify import markdownify as md
except ImportError:
    md = None

BASE_URL = "http://www.gacetaoficialdebolivia.gob.bo"
REQUEST_TIMEOUT_SECONDS = 60
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}

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
    _aplicar_rate_limit(rate_limit_state)
    try:
        return _obtener_soup(url, timeout=timeout)
    finally:
        if rate_limit_state is not None:
            rate_limit_state["total_requests"] = rate_limit_state.get("total_requests", 0) + 1


def _append_jsonl(file_path, item):
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False))
        f.write("\n")


def _jsonl_a_json(jsonl_path, json_path):
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
    except requests.RequestException:
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
    for nodo in cuerpo.find_all(["fieldset", "img", "script", "style", "title", "hr"]):
        nodo.decompose()

    markdown = _html_a_markdown_moderno(cuerpo)
    markdown = _normalizar_markdown(markdown)
    if not markdown:
        return "[NORMA_NO_DISPONIBLE_EN_HTML]"
    return markdown


def extraer_normativas(
    fecha_inicio,
    fecha_fin,
    pagina_inicial=1,
    paginas_a_extraer=None,
    output_jsonl_path=None,
    reset_output_jsonl=False,
):
    # La URL base utiliza la convención de CakePHP para la paginación (/page:X)
    base_url = f"http://www.gacetaoficialdebolivia.gob.bo/normas/buscarFecha/{fecha_inicio}/{fecha_fin}/page:{{}}"

    todas_las_normas = []
    rate_limit_state = _crear_estado_rate_limit()

    if output_jsonl_path and reset_output_jsonl:
        with open(output_jsonl_path, "w", encoding="utf-8"):
            pass

    pagina = pagina_inicial
    ultima_pagina = None

    while True:
        if paginas_a_extraer is not None and pagina >= pagina_inicial + paginas_a_extraer:
            break
        if ultima_pagina is not None and pagina > ultima_pagina:
            break

        print(f"Procesando página {pagina}...")
        url = base_url.format(pagina)

        try:
            # Añadimos un timeout por si el servidor gubernamental tarda en responder
            soup = _obtener_soup_con_control(
                url, timeout=REQUEST_TIMEOUT_SECONDS, rate_limit_state=rate_limit_state
            )
        except requests.RequestException as e:
            print(f"Error de conexión en la página {pagina}: {e}")
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
            print("No se encontraron más normativas. Fin del listado.")
            break

        for tarjeta in tarjetas:
            norma = {}

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

        print(
            f"Página {pagina} completada. Registros acumulados: {len(todas_las_normas)} | Consultas HTTP: {rate_limit_state['total_requests']}"
        )

        pagina += 1

    return todas_las_normas


# Ejecución del crawler
if __name__ == "__main__":
    # Rango de ejemplo según tu URL original
    inicio = "1800-01-01"
    fin = "2026-01-01"

    # Si paginas_a_extraer=None, recorre todo automáticamente según #titulos-bloque.
    # Para pruebas rápidas, usa un entero (ej. 2).
    nombre_archivo_jsonl = "data/archivo_gaceta_bolivia.jsonl"

    datos = extraer_normativas(
        inicio,
        fin,
        pagina_inicial=1,
        paginas_a_extraer=None,
        output_jsonl_path=nombre_archivo_jsonl,
        reset_output_jsonl=True,
    )

    print(
        f"\nExtracción completada. Se guardaron {len(datos)} registros en {nombre_archivo_jsonl}."
    )
