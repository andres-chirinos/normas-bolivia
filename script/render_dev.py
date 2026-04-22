from __future__ import annotations

import argparse
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
NORMAS_DIR = ROOT_DIR / "normas"
BASE_PAGES = [ROOT_DIR / "index.qmd", ROOT_DIR / "about.qmd"]


def extraer_fecha_desde_nombre(path_md: Path) -> Optional[date]:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})-", path_md.name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def obtener_normas_ordenadas(normas_dir: Path) -> List[Path]:
    archivos = [p for p in normas_dir.rglob("*.md") if p.is_file()]

    def clave_orden(path_md: Path) -> Tuple[date, str]:
        fecha = extraer_fecha_desde_nombre(path_md) or date.min
        return (fecha, path_md.name)

    archivos.sort(key=clave_orden, reverse=True)
    return archivos


def seleccionar_normas_para_dev(normas_dir: Path, limite: int) -> List[Path]:
    if limite <= 0:
        return []
    return obtener_normas_ordenadas(normas_dir)[:limite]


def rutas_relativas(paths: Iterable[Path]) -> List[str]:
    return [str(p.relative_to(ROOT_DIR)) for p in paths]


def ejecutar_quarto_render(archivos: Sequence[Path]) -> int:
    cmd = ["quarto", "render", *rutas_relativas(archivos)]
    resultado = subprocess.run(cmd, cwd=ROOT_DIR, check=False)
    return resultado.returncode


def construir_objetivos_dev(limite: int) -> List[Path]:
    if not NORMAS_DIR.exists():
        raise FileNotFoundError(f"No existe el directorio de normas: {NORMAS_DIR}")
    normas_dev = seleccionar_normas_para_dev(NORMAS_DIR, limite)
    return [*BASE_PAGES, *normas_dev]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Renderiza Quarto en modo dev con un subconjunto de normas."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Cantidad de normas a renderizar en modo dev (default: 10).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    objetivos = construir_objetivos_dev(args.limit)
    normas_dev = objetivos[len(BASE_PAGES) :]

    print(f"Render dev: {len(normas_dev)} normas + {len(BASE_PAGES)} páginas base.")
    for md in rutas_relativas(normas_dev):
        print(f" - {md}")

    codigo = ejecutar_quarto_render(objetivos)
    if codigo != 0:
        raise SystemExit(codigo)


if __name__ == "__main__":
    main()
