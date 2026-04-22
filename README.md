# Gaceta Oficial de Normas

## Flujo estandar (Makefile)

Render de demostración (solo 10 normas):

```bash
make dev-render
```

Preview en desarrollo (render previo de 10 normas):

```bash
make dev-preview
```

Atajo equivalente:

```bash
make dev
```

Este comando genera un perfil temporal de Quarto para limitar el preview a 10 normas.

Compilación completa del sitio:

```bash
make build
```

## Scripts directos

Render dev con límite custom:

```bash
./.venv/bin/python script/render_dev.py --limit 10
```

Preview dev con opciones de red:

```bash
./.venv/bin/python script/preview_dev.py --limit 10 --port 4200 --host 127.0.0.1
```

## Crawler Con Reanudación

El crawler guarda un checkpoint en `data/archivo_gaceta_bolivia.resume.json` y escribe logs en `logs/download_gaceta.log`.

Ejecutar normalmente:

```bash
python script/download_gaceta.py
```

Reanudar desde el último punto guardado:

```bash
python script/download_gaceta.py --resume
```

Ejemplo con fechas y salida personalizadas:

```bash
python script/download_gaceta.py --fecha-inicio 1999-01-01 --fecha-fin 1999-12-31 --output-jsonl data/archivo_gaceta_bolivia.jsonl
```
