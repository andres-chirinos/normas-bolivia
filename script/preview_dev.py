from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Sequence

from render_dev import BASE_PAGES, ROOT_DIR, construir_objetivos_dev, rutas_relativas


PROFILE_NAME = "dev10"
PROFILE_FILE = ROOT_DIR / f"_quarto-{PROFILE_NAME}.yml"


def escribir_perfil_dev(objetivos: Sequence[Path]) -> None:
    rutas = rutas_relativas(objetivos)
    lineas = ["project:", "  render:"]
    for ruta in rutas:
        lineas.append(f'    - "{ruta}"')
    PROFILE_FILE.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def ejecutar_quarto_preview(
    port: int | None,
    host: str | None,
    no_browser: bool,
    timeout_seconds: int | None,
) -> int:
    cmd = ["quarto", "preview", "--profile", PROFILE_NAME, "--render", "all"]

    if port is not None:
        cmd.extend(["--port", str(port)])
    if host is not None:
        cmd.extend(["--host", host])
    if no_browser:
        cmd.append("--no-browser")
    if timeout_seconds is not None:
        cmd.extend(["--timeout", str(timeout_seconds)])

    result = subprocess.run(cmd, cwd=ROOT_DIR, check=False)
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview Quarto en modo dev con render previo de un subconjunto de normas."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Cantidad de normas a renderizar antes del preview (default: 10).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=4200,
        help="Puerto sugerido para el servidor de preview (default: 4200).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host de bind para preview (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="No abrir navegador automáticamente.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Cerrar preview automáticamente tras N segundos sin clientes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    objetivos = construir_objetivos_dev(args.limit)
    normas_dev = objetivos[len(BASE_PAGES) :]

    escribir_perfil_dev(objetivos)
    print(
        f"Preview dev (perfil {PROFILE_NAME}): {len(normas_dev)} normas + {len(BASE_PAGES)} páginas base."
    )

    try:
        codigo_preview = ejecutar_quarto_preview(
            port=args.port,
            host=args.host,
            no_browser=args.no_browser,
            timeout_seconds=args.timeout,
        )
    except KeyboardInterrupt:
        print("\nPreview detenido por el usuario.")
        return

    if codigo_preview != 0:
        raise SystemExit(codigo_preview)


if __name__ == "__main__":
    main()
