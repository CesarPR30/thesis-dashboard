# Contrato de datos — `thesis-dashboard` v1

Este repositorio es **público**. El contrato fija qué datos pueden vivir en
`public/data/` y cómo tienen que venir agregados. Lo define quien recibe (este
repositorio) y lo cumple quien envía (el pipeline privado). La versión que se
lee por máquina es [`tools/contract.json`](tools/contract.json) y la comprueba
[`tools/validate_data.py`](tools/validate_data.py).

## Estructura

```text
public/data/
├── datasets.json            índice de ciudades
└── <ciudad>/
    ├── publication.json     obligatorio: firma SHA-256 de cada archivo + commit del pipeline
    ├── crimes.bin           obligatorio: denuncias agregadas a grilla
    ├── crimes_meta.json     obligatorio: layout del binario + bloque `aggregation`
    └── …                    opcionales de la lista permitida
```

Archivos permitidos por ciudad: `benchmark.json`, `casestudies.json`,
`crimes.bin`, `crimes_meta.json`, `evaluation.json`, `explainer.json`,
`hotspots.geojson`, `param_sweep.json`, `pois.bin`, `pois_meta.json`,
`similarity.json`, `validation_report.json`, `publication.json`.

## Nunca públicos

| Archivo | Motivo |
|---|---|
| `snapping.bin`, `snapping_meta.json` | asignan cada denuncia a su intersección más cercana: es la ubicación individual con otro nombre |
| `metodo.json`, `temporal.json` | eventos individuales para las figuras del paper; se usan solo en local |

## Agregación de `crimes.bin`

Cada registro es (ubicación, distrito, categoría, mes). La ubicación se lleva al
**centro de su celda** de una grilla:

- origen en la esquina SO del bbox de la exportación;
- `dlat = celda / 111 320` y `dlon = celda / (111 320 · cos |lat|máx)`, de modo que
  ninguna celda mida menos que `celda` en ningún punto;
- **200 m** como mínimo en general y **1 km** en las categorías sensibles:
  violación de la libertad sexual, proxenetismo, ofensas al pudor público,
  aborto, violación de la intimidad y exposición a peligro o abandono de personas;
- los registros se reordenan de forma canónica (mes, categoría, distrito, celda).

Con eso el archivo equivale exactamente a la tabla de conteos por (celda,
distrito, categoría, mes). El validador decodifica el binario y comprueba,
registro por registro, que cada uno cae en el centro de una celda de la grilla
que le corresponde, y que la grilla declarada no es más fina que el mínimo.

Los puntos de `explainer.json` (`clip.crimes`, `twins.*.crimes`, en metros
respecto de `meta.center`) se llevan a la misma grilla de 200 m. Cualquier otro
arreglo de pares numéricos bajo una clave que suene a crimen, evento o denuncia
hace fallar la validación.

## Otras reglas

- Ningún archivo de texto contiene rutas absolutas de una máquina.
- Ningún archivo supera 95 MB (GitHub rechaza más de 100 MB).
- `datasets.json` no anuncia en `has` archivos que no están.

## Quién lo comprueba

1. **El pipeline**, antes de copiar (`scripts/publish.py dashboard`).
2. **El hook de pre-push** (`git config core.hooksPath tools/hooks`).
3. **GitHub Actions**: el job `validate` corre antes de `deploy`; si falla, Pages
   no se actualiza.

## Cambiar el contrato

Subir `version` en `tools/contract.json` y aquí, y registrar el motivo como
decisión en `thesis-hub/docs/decisions/`. El pipeline lee el contrato del
destino, así que una celda más gruesa o un archivo nuevo en la lista se aplican
en la siguiente publicación sin tocar su código.
