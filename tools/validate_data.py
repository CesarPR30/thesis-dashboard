"""Comprueba que los datos del dashboard público cumplen el contrato.

    python tools/validate_data.py              # public/data + archivos versionados
    python tools/validate_data.py --dir X      # una carpeta con la forma de public/data
                                               # (la usa el pipeline sobre su staging)

Reglas (tools/contract.json, explicadas en CONTRACT.md):

1. En `public/data/` solo hay `datasets.json` y, por ciudad, archivos de la
   lista permitida. `snapping.bin`, `metodo.json` y `temporal.json` nunca.
2. `publication.json` lista el SHA-256 de cada archivo publicado y todos
   coinciden: nada se tocó a mano después de publicar.
3. `crimes.bin` está agregado a una grilla: cada registro cae en el centro de
   una celda de al menos `min_cell_m` metros (`min_sensitive_cell_m` para las
   categorías sensibles). Se decodifica registro por registro.
4. Los arreglos de puntos de `explainer.json` caen en el centro de la misma
   grilla; cualquier otro arreglo de pares numéricos bajo una clave que suene
   a crimen/evento es un error.
5. Ningún archivo de texto contiene rutas absolutas de una máquina y ninguno
   supera `max_file_mb`.

Solo usa la biblioteca estándar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "tools" / "contract.json").read_text(encoding="utf-8"))
AGG = CONTRACT["aggregation"]
MPD = AGG["meters_per_degree"]

RUTA_LOCAL = re.compile(r"[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+[^\\/\s\"'`…]+[\\/]"
                        r"|/(?:Users|home)/[^/\s\"'`…]+/")
TIPOS = {"Uint8": "B", "Uint16": "H", "Uint32": "I"}


class Informe:
    def __init__(self) -> None:
        self.errores: list[str] = []
        self.notas: list[str] = []

    def error(self, msg: str) -> None:
        self.errores.append(msg)

    def nota(self, msg: str) -> None:
        self.notas.append(msg)


# ─── utilidades ──────────────────────────────────────────────────────────

def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_json(ruta: Path, inf: Informe, rel: str):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        inf.error(f"{rel}: JSON ilegible ({e})")
        return None


def es_par(x) -> bool:
    return (isinstance(x, list) and len(x) >= 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in x[:2]))


def arreglos_de_puntos(obj, ruta: str = ""):
    """Rutas (sin índices) de las listas de pares numéricos dentro de `obj`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from arreglos_de_puntos(v, f"{ruta}.{k}" if ruta else k)
    elif isinstance(obj, list):
        if len(obj) >= 2 and all(es_par(x) for x in obj[:5]):
            yield ruta, obj
        else:
            for x in obj:
                yield from arreglos_de_puntos(x, ruta + "[]")


# ─── grilla ──────────────────────────────────────────────────────────────

def revisar_grilla(nombre: str, g: dict, minimo_m: float, lat_max_abs: float, inf: Informe, rel: str) -> bool:
    try:
        dlat, dlon = float(g["dlat"]), float(g["dlon"])
        float(g["origin"][0]), float(g["origin"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        inf.error(f"{rel}: grilla «{nombre}» mal declarada (origin, dlat, dlon)")
        return False
    alto = dlat * MPD
    ancho = dlon * MPD * math.cos(math.radians(lat_max_abs))
    if alto < minimo_m * 0.999 or ancho < minimo_m * 0.999:
        inf.error(f"{rel}: la grilla «{nombre}» mide {alto:.0f}×{ancho:.0f} m; el contrato exige al menos {minimo_m} m")
        return False
    return True


def en_centro(valor: float, origen: float, paso: float, tol: float) -> bool:
    k = round((valor - origen) / paso - 0.5)
    return abs(valor - (origen + (k + 0.5) * paso)) <= tol


# ─── crimes.bin ──────────────────────────────────────────────────────────

def revisar_crimenes(d: Path, rel: str, inf: Informe) -> dict | None:
    meta = leer_json(d / "crimes_meta.json", inf, f"{rel}/crimes_meta.json")
    if meta is None:
        return None
    ag = meta.get("aggregation") or {}
    if ag.get("method") != "grid":
        inf.error(f"{rel}/crimes_meta.json: falta `aggregation.method = \"grid\"`; crimes.bin parece llevar coordenadas individuales")
        return None

    lat0, lon0, lat1, lon1 = meta["bbox"]
    q = meta["quant_max"]
    n = meta["n"]
    lat_max_abs = max(abs(lat0), abs(lat1))
    grillas = ag.get("grids") or {}
    if not (revisar_grilla("base", grillas.get("base", {}), AGG["min_cell_m"], lat_max_abs, inf, rel)
            and revisar_grilla("sensitive", grillas.get("sensitive", {}), AGG["min_sensitive_cell_m"], lat_max_abs, inf, rel)):
        return None

    crudo = (d / "crimes.bin").read_bytes()
    campos = {}
    for c in meta["layout"]:
        a = array(TIPOS[c["type"]])
        ancho = a.itemsize
        a.frombytes(crudo[c["offset"]: c["offset"] + n * ancho])
        if sys.byteorder == "big":
            a.byteswap()
        if len(a) != n:
            inf.error(f"{rel}/crimes.bin: el campo {c['field']} está truncado ({len(a)} de {n})")
            return None
        campos[c["field"]] = a

    categorias = meta["categories"]
    sensibles = set(AGG["sensitive_categories"]) | set(ag.get("sensitive_categories") or [])
    es_sensible = [c in sensibles for c in categorias]

    flat, flon = (lat1 - lat0) / q, (lon1 - lon0) / q
    tol_lat, tol_lon = flat * 1.01, flon * 1.01
    gb, gs = grillas["base"], grillas["sensitive"]
    malos = 0
    distintos = set()
    lat_a, lon_a, cat_a = campos["lat"], campos["lon"], campos["cat"]
    for i in range(n):
        g = gs if es_sensible[cat_a[i]] else gb
        la = lat0 + lat_a[i] * flat
        lo = lon0 + lon_a[i] * flon
        if not (en_centro(la, g["origin"][0], g["dlat"], tol_lat) and en_centro(lo, g["origin"][1], g["dlon"], tol_lon)):
            malos += 1
            if malos <= 3:
                inf.error(f"{rel}/crimes.bin: el registro {i} ({la:.6f}, {lo:.6f}) no cae en el centro de una celda")
        distintos.add((lat_a[i], lon_a[i]))
    if malos:
        inf.error(f"{rel}/crimes.bin: {malos:,} de {n:,} registros fuera de la grilla")
        return None
    inf.nota(f"{rel}/crimes.bin: {n:,} registros en {len(distintos):,} celdas "
             f"(base {gb.get('cell_m')} m, sensibles {gs.get('cell_m')} m)")
    return meta


# ─── explainer.json y barrido de puntos ──────────────────────────────────

def revisar_puntos(ruta: Path, rel: str, meta_crimenes: dict | None, inf: Informe) -> None:
    nombre = ruta.name
    if not nombre.endswith((".json", ".geojson")):
        return
    obj = leer_json(ruta, inf, rel)
    if obj is None:
        return
    permitidas = set(CONTRACT["point_arrays"].get(nombre, []))
    claves = CONTRACT["point_keywords"]
    for camino, pares in arreglos_de_puntos(obj):
        limpio = camino.replace("[]", "")
        sospechoso = any(k in camino.lower() for k in claves)
        if camino in permitidas:
            revisar_puntos_locales(obj, camino, pares, rel, meta_crimenes, inf)
        elif sospechoso:
            inf.error(f"{rel}: «{limpio}» tiene {len(pares):,} puntos y no está entre los arreglos que el contrato permite")


def revisar_puntos_locales(obj: dict, camino: str, pares: list, rel: str, meta_crimenes: dict | None, inf: Informe) -> None:
    """Puntos en metros (x al este, y al sur) respecto de meta.center [lon, lat]."""
    centro = (obj.get("meta") or {}).get("center")
    if not centro or meta_crimenes is None:
        inf.error(f"{rel}: «{camino}» no se puede verificar (falta meta.center o crimes_meta agregado)")
        return
    clon, clat = centro
    g = meta_crimenes["aggregation"]["grids"]["base"]
    kx = MPD * math.cos(math.radians(clat))
    tol = 0.5 / MPD                        # medio metro
    malos = 0
    for x, y, *_ in pares:
        lo = clon + x / kx
        la = clat - y / MPD
        if not (en_centro(la, g["origin"][0], g["dlat"], tol) and en_centro(lo, g["origin"][1], g["dlon"], tol * MPD / kx)):
            malos += 1
    if malos:
        inf.error(f"{rel}: {malos} de {len(pares)} puntos de «{camino}» no caen en la grilla")


# ─── carpeta de datos ────────────────────────────────────────────────────

def revisar_datos(base: Path, prefijo: str, inf: Informe) -> int:
    idx_ruta = base / CONTRACT["index"]
    if not idx_ruta.exists():
        inf.error(f"{prefijo}/{CONTRACT['index']}: no existe")
        return 0
    indice = leer_json(idx_ruta, inf, f"{prefijo}/{CONTRACT['index']}") or {}
    dirs = {e["dir"]: e for e in indice.get("datasets", [])}
    revisados = 1

    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        relp = p.relative_to(base).as_posix()
        if relp == CONTRACT["index"]:
            continue
        partes = relp.split("/")
        if len(partes) != 2 or partes[0] not in dirs:
            inf.error(f"{prefijo}/{relp}: fuera de la carpeta de una ciudad indexada")
        elif partes[1] in CONTRACT["never_public"]:
            inf.error(f"{prefijo}/{relp}: nunca es público — {CONTRACT['never_public'][partes[1]]}")
        elif partes[1] not in CONTRACT["allowed_files"]:
            inf.error(f"{prefijo}/{relp}: no está en la lista de archivos permitidos")

    for nombre_dir, entrada in dirs.items():
        d = base / nombre_dir
        rel = f"{prefijo}/{nombre_dir}"
        faltan = [f for f in CONTRACT["required_files"] if not (d / f).exists()]
        if faltan:
            inf.error(f"{rel}: faltan {', '.join(faltan)}")
            continue
        presentes = {p.name for p in d.iterdir() if p.is_file()}
        sobran = set(entrada.get("has", [])) - presentes
        if sobran:
            inf.error(f"{prefijo}/{CONTRACT['index']}: «{nombre_dir}» anuncia {sorted(sobran)} pero no están")

        pub = leer_json(d / "publication.json", inf, f"{rel}/publication.json") or {}
        if pub.get("contract_version") != CONTRACT["version"]:
            inf.error(f"{rel}/publication.json: contract_version {pub.get('contract_version')!r} ≠ {CONTRACT['version']}")
        firmados = pub.get("files") or {}
        for f in sorted(presentes - {"publication.json"}):
            if f not in firmados:
                inf.error(f"{rel}/{f}: no figura en publication.json (¿copiado a mano?)")
            elif sha256(d / f) != firmados[f]:
                inf.error(f"{rel}/{f}: el SHA-256 no coincide con publication.json (¿editado después de publicar?)")
        for f in sorted(set(firmados) - presentes):
            inf.error(f"{rel}/publication.json: firma {f}, que no está")

        meta = revisar_crimenes(d, rel, inf)
        for f in sorted(presentes):
            revisar_puntos(d / f, f"{rel}/{f}", meta, inf)
        revisados += len(presentes)
    return revisados


def revisar_textos(archivos: list[tuple[Path, str]], inf: Informe) -> None:
    tope = CONTRACT["max_file_mb"] * 1024 * 1024
    textos = tuple(CONTRACT["text_extensions"])
    for ruta, rel in archivos:
        if ruta.stat().st_size > tope:
            inf.error(f"{rel}: pesa más de {CONTRACT['max_file_mb']} MB")
        if ruta.name in CONTRACT["never_public"]:
            inf.error(f"{rel}: nunca es público — {CONTRACT['never_public'][ruta.name]}")
        if rel.lower().endswith(textos):
            m = RUTA_LOCAL.search(ruta.read_text(encoding="utf-8", errors="replace"))
            if m:
                inf.error(f"{rel}: contiene una ruta local ({m.group(0)!r}…)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, help="carpeta con la forma de public/data (staging del pipeline)")
    args = ap.parse_args()
    inf = Informe()

    if args.dir:
        base = args.dir.resolve()
        n = revisar_datos(base, "data", inf)
        revisar_textos([(p, "data/" + p.relative_to(base).as_posix()) for p in base.rglob("*") if p.is_file()], inf)
    else:
        n = revisar_datos(ROOT / CONTRACT["data_root"], CONTRACT["data_root"], inf)
        try:
            salida = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
            rels = [r for r in salida.decode("utf-8").split("\0") if r]
        except (OSError, subprocess.CalledProcessError):
            rels = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
        revisar_textos([(ROOT / r, r) for r in rels if (ROOT / r).is_file()], inf)

    for nota in inf.notas:
        print("  ·", nota)
    inf.errores = list(dict.fromkeys(inf.errores))
    if inf.errores:
        print(f"Contrato {CONTRACT['contract']} v{CONTRACT['version']}: {len(inf.errores)} problema(s)")
        for e in inf.errores:
            print("  ✗", e)
        return 1
    print(f"Contrato {CONTRACT['contract']} v{CONTRACT['version']}: {n} archivos de datos revisados, todo en orden.")
    return 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
