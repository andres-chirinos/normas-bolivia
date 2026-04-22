from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT_DIR / "data" / "archivo_gaceta_bolivia.jsonl"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "normas"


@dataclass(frozen=True)
class Norma:
    titulo: str
    fecha_publicacion: Optional[str]
    edicion: Optional[str]
    resumen: str
    norma_markdown: str
    url_pdf: Optional[str]
    extra_metadata: Dict[str, Any]


def slugify(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto)
    ascii_text = normalizado.encode("ascii", "ignore").decode("ascii")
    limpio = re.sub(r"[^a-zA-Z0-9\s-]", "", ascii_text).strip().lower()
    slug = re.sub(r"[-\s]+", "-", limpio).strip("-")
    return slug or "sin-titulo"


def yaml_quote(valor: str) -> str:
    escaped = valor.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def parse_fecha(valor: Optional[str]) -> Optional[date]:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


def iter_jsonl(path_jsonl: Path) -> Iterator[Dict[str, Any]]:
    with path_jsonl.open("r", encoding="utf-8") as src:
        for numero_linea, linea in enumerate(src, start=1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                item = json.loads(linea)
            except json.JSONDecodeError as exc:
                print(
                    f"[WARN] Línea {numero_linea} inválida (JSONDecodeError): {exc}. Se omite."
                )
                continue

            if not isinstance(item, dict):
                print(f"[WARN] Línea {numero_linea} no es objeto JSON. Se omite.")
                continue

            yield item


def normalizar_norma(item: Dict[str, Any]) -> Norma:
    titulo = str(item.get("titulo") or "Sin título")
    fecha_publicacion = item.get("fecha_publicacion")
    fecha_publicacion = str(fecha_publicacion) if fecha_publicacion else None
    edicion = item.get("edicion")
    edicion = str(edicion) if edicion else None
    resumen = str(item.get("resumen") or "")
    norma_markdown = str(item.get("norma_markdown") or "")
    url_pdf = item.get("url_pdf")
    url_pdf = str(url_pdf) if url_pdf else None

    extra_metadata = {
        clave: valor
        for clave, valor in item.items()
        if clave not in {"titulo", "fecha_publicacion", "edicion", "resumen", "norma_markdown", "url_pdf"}
    }

    return Norma(
        titulo=titulo,
        fecha_publicacion=fecha_publicacion,
        edicion=edicion,
        resumen=resumen,
        norma_markdown=norma_markdown,
        url_pdf=url_pdf,
        extra_metadata=extra_metadata,
    )


def _yaml_scalar(valor: Any) -> str:
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return str(valor)
    escaped = str(valor).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_block(valor: Any, indent: int = 0) -> str:
    sangria = " " * indent

    if isinstance(valor, dict):
        lineas: list[str] = []
        for clave, item in valor.items():
            if isinstance(item, (dict, list)):
                lineas.append(f"{sangria}{clave}:")
                lineas.append(_yaml_block(item, indent + 2))
            else:
                lineas.append(f"{sangria}{clave}: {_yaml_scalar(item)}")
        return "\n".join(lineas)

    if isinstance(valor, list):
        if not valor:
            return f"{sangria}[]"
        lineas = []
        for item in valor:
            if isinstance(item, (dict, list)):
                lineas.append(f"{sangria}-")
                lineas.append(_yaml_block(item, indent + 2))
            else:
                lineas.append(f"{sangria}- {_yaml_scalar(item)}")
        return "\n".join(lineas)

    return f"{sangria}{_yaml_scalar(valor)}"


def construir_frontmatter(norma: Norma) -> str:
    fecha_str = norma.fecha_publicacion or ""
    edicion_str = norma.edicion or "sin_edicion"

    metadata: Dict[str, Any] = {
        "title": norma.titulo,
        "date": fecha_str,
        "summary": norma.resumen or None,
        "resumen": norma.resumen or None,
        "description": norma.resumen or None,
        "edicion": edicion_str,
        "fecha_publicacion": fecha_str or None,
        "url_pdf": norma.url_pdf,
        "status": "vigente",
        "categories": [f"Edición: {edicion_str}"],
        "format": {"html": {"toc": True}},
    }

    metadata.update(norma.extra_metadata)

    return "\n".join(
        [
            "---",
            _yaml_block(metadata),
            "---",
            "",
        ]
    )


def construir_cuerpo(norma: Norma) -> str:
    partes = [
        norma.norma_markdown or "Contenido no disponible.",
        "",
    ]

    if norma.url_pdf:
        partes.append(f"[Ver PDF original]({norma.url_pdf})")
    else:
        partes.append("PDF original no disponible.")

    partes.append("")
    return "\n".join(partes)


def construir_nombre_archivo(norma: Norma) -> tuple[str, str]:
    fecha = parse_fecha(norma.fecha_publicacion)
    slug = slugify(norma.titulo)

    if fecha:
        carpeta = str(fecha.year)
        base = f"{fecha.isoformat()}-{slug}"
    else:
        carpeta = "sin_fecha"
        base = f"sin-fecha-{slug}"

    return carpeta, base


def garantizar_nombre_unico(destino_dir: Path, base_nombre: str) -> Path:
    return destino_dir / f"{base_nombre}.md"


def convertir_jsonl_a_quarto(path_jsonl: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    escritos = 0
    for item in iter_jsonl(path_jsonl):
        total += 1
        norma = normalizar_norma(item)

        subcarpeta, base_nombre = construir_nombre_archivo(norma)
        destino_dir = out_dir / subcarpeta
        destino_dir.mkdir(parents=True, exist_ok=True)

        destino_archivo = garantizar_nombre_unico(destino_dir, base_nombre)

        contenido = construir_frontmatter(norma) + construir_cuerpo(norma)
        destino_archivo.write_text(contenido, encoding="utf-8")
        escritos += 1

        if escritos % 500 == 0:
            print(f"Progreso: {escritos} archivos generados...")

    print(f"Conversión finalizada. Registros leídos: {total}. Archivos creados: {escritos}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convierte un archivo JSONL de normas a markdown compatible con Quarto."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Ruta al archivo JSONL de entrada.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directorio base de salida para archivos markdown.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"No se encontró el archivo JSONL: {args.input}")
    convertir_jsonl_a_quarto(args.input, args.output_dir)


if __name__ == "__main__":
    main()