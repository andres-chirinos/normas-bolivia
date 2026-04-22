# Sobre el Proyecto

Metodología, fuentes y criterios editoriales del portal Gaceta Oficial de Normas.

Este portal organiza y publica normas legales en formato web estático para facilitar la consulta pública, la trazabilidad de cambios y la colaboración comunitaria.

## Metodología

1.  Recolección automatizada: se extraen registros desde el portal oficial de la Gaceta con control de rate limit y manejo de errores de red.
2.  Estandarización de campos: cada registro se normaliza en un esquema común con título, fecha, edición, resumen, contenido y enlace al PDF oficial.
3.  Transformación a Markdown: el dataset en JSONL se convierte en documentos Quarto, uno por norma, con metadatos estructurados para búsqueda y filtrado.
4.  Publicación reproducible: el sitio se compila como web estática para asegurar despliegues trazables y revisables.
5.  Colaboración abierta: se habilitan acciones de edición y reporte de issues en GitHub para correcciones y mejoras comunitarias.

## Fuentes

- Gaceta Oficial del Estado Plurinacional de Bolivia: portal oficial de normas y publicaciones legales.
- Archivos oficiales enlazados desde cada registro (PDF original por norma).
- Repositorio del proyecto para versionado y auditoría de cambios: <https://github.com/datosbolivia/normas-bolivia>.

## Alcance y Limitaciones

- Este portal prioriza acceso y navegabilidad; no reemplaza el valor jurídico del documento oficial.
- Puede haber registros con campos incompletos en origen (por ejemplo, sin contenido HTML o sin fecha estructurada).
- Ante discrepancias, prevalece siempre el documento oficial enlazado en cada norma.
