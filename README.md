# thesis-dashboard — crimen urbano sobre la red vial de Lima

**Sitio:** https://cesarpr30.github.io/thesis-dashboard/

Dashboard público de la tesis: hotspots de crimen detectados como **subgrafos de
la red vial** de Lima Metropolitana, caracterizados por su forma (sin usar el
crimen) y comparados entre lugares estructuralmente parecidos.

1 016 306 denuncias PNP · 90 meses (2018-01 .. 2025-06) · 35 subtipos de delito ·
4 299 subgrafos.

> **Datos agregados.** Las ubicaciones de las denuncias se publican llevadas al
> centro de celdas de **200 m** (1 km para las categorías sensibles). Equivale a
> conteos por celda, distrito, categoría y mes: ninguna denuncia aparece con su
> coordenada original. El detalle está en [`CONTRACT.md`](CONTRACT.md).

## Qué hay

- [`public/index.html`](public/index.html): el dashboard. Mapa (puntos y calor),
  subgrafos por mes, ficha descriptiva, espacio de embeddings con UMAP y
  clústeres, línea de tiempo y comparación A vs B. El cajón de información
  técnica trae la procedencia del dato, el barrido de parámetros, la validación
  sintética, la evaluación y los estudios de caso.
- [`public/como-funciona-visual.html`](public/como-funciona-visual.html) y
  [`public/como-funciona.html`](public/como-funciona.html): el método en resumen
  visual y paso a paso.
- `public/data/`: los artefactos publicados. **No se editan a mano**: los
  escribe el script de publicación del pipeline (privado) y cada archivo va
  firmado en `publication.json`.

Es estático: HTML con MapLibre y D3 por CDN, sin build ni npm.

En la versión pública no está la vista «Nodos»: necesita el snapping de cada
denuncia a su intersección, que es la ubicación individual con otro nombre y no
sale del repositorio privado. El «Relieve 3D» sí está, pero se calcula en el
navegador sobre los mismos centros de celda publicados (σ = 200 m, el tamaño de
la celda; las categorías sensibles se reparten sobre su celda de 1 km), no sobre
la carga por intersección que usa la versión privada.

## En local

```bash
python -m http.server 8000 -d public     # http://localhost:8000
```

## Cómo llegan los datos

```text
thesis-data-pipeline (privado)                 thesis-dashboard (público)
  dashboard/public/data/<ciudad>  ──publish.py──►  public/data/<ciudad>
        datos completos             agrega, firma        solo agregados
                                    y valida con
                                    tools/validate_data.py
```

1. En el pipeline: `python scripts/publish.py dashboard` (ensayo) y luego con
   `--yes`. Lee [`tools/contract.json`](tools/contract.json) de este repositorio,
   arma la publicación en una carpeta temporal, la valida con
   [`tools/validate_data.py`](tools/validate_data.py) y solo si pasa la copia aquí.
2. Aquí: revisar el `git diff` y hacer commit. El hook de pre-push vuelve a
   validar (actívalo una vez por clon con `git config core.hooksPath tools/hooks`).
3. GitHub Actions valida otra vez y solo entonces despliega a Pages.

## Crédito

Trabajo de tesis de **Cesar Pajuelo** (UTEC). Datos de denuncias: PNP,
consolidado DGIS 2018-2025. Red vial y POIs: OpenStreetMap (© colaboradores de
OSM, ODbL), vía Geofabrik. Mapa base: OpenFreeMap.
