# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera el catálogo de CRS de Geoblender (spec 002, T02; RF-002-23; ADR-0019, D-8).

Uso, con el Python de Blender y desde la raíz del repositorio de código::

    $env:GEOBLENDER_PROJ_BIN = "<carpeta con projinfo y cs2cs>"   # p. ej. el bin de QGIS
    & $PY -B tools/gen_crs_catalog.py [--comprobar]

Escribe ``thirdparty/epsg/crs_catalog.json`` y ``thirdparty/epsg/README.md`` de la
extensión. Con ``--comprobar`` no escribe nada: genera en memoria y compara con lo que
hay (0 si coincide, 1 si no). Solo biblioteca estándar (HER-01).

Qué hace (plan 002 §5.1 y §6; ADR-0019, punto 1):

- Selecciona los CRS de la spec 002 §11 (``HORIZONTAL_CODES`` y ``VERTICAL_CODES``) y
  toma de ``projinfo`` su PROJJSON (tipo, nombre, ejes y unidad, área y ámbito
  geográfico), su WKT2:2019 y su WKT1:GDAL, tal cual: solo cambia el formato.
- Calcula el **ámbito proyectado** de cada CRS horizontal (``bounds``, el único dato
  derivado): el contorno de su ámbito geográfico (la unión de sus usos), densificado,
  se proyecta con ``cs2cs`` desde su propio CRS geográfico base (sin cambio de datum) y
  se toma la envolvente redondeada hacia fuera a metros enteros.
- Escribe en el JSON el origen (EPSG Dataset, propiedad de IOGP), las versiones de EPSG y
  de PROJ (de la tabla ``metadata`` del ``proj.db`` usado, abierto en solo lectura) y la
  atribución; y en el ``README.md`` el sha256 del catálogo.

PROJ se ejecuta aislado del equipo (Silvestre TOP-05: ``PROJ_LIB`` apuntaba al ``proj.db``
de PostGIS): sin ninguna variable ``PROJ_*`` ni ``GDAL_*``, con ``PROJ_DATA`` = la carpeta
``share/proj`` de esa misma instalación y sin red (``PROJ_NETWORK=OFF``).

Códigos de salida: 0 correcto; 1 la generación falló o ``--comprobar`` encontró
diferencias; 2 uso o entorno (sin ``GEOBLENDER_PROJ_BIN``, sin ``projinfo``…).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ (plan 001 §5.3)

import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
from collections.abc import Callable, Iterable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from gbtools import layout  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402

ENV_PROJ_BIN = "GEOBLENDER_PROJ_BIN"
OPTION_CHECK = "--comprobar"
CATALOG_FORMAT = "geoblender-crs-catalog"
CATALOG_SCHEMA = 1
EPSG_FOLDER_RELPATH = f"{layout.THIRDPARTY_RELPATH}/epsg"
CATALOG_NAME = "crs_catalog.json"
README_NAME = "README.md"

# Spec 002 §11 (D-1; códigos y nombres comprobados con projinfo de QGIS 4.2). La spec
# dice «26 CRS», pero enumera estos 25.
HORIZONTAL_CODES: tuple[int, ...] = (
    25828, 25829, 25830, 25831,  # ETRS89 / UTM 28N–31N
    4082, 4083,  # REGCAN95 / UTM 27N y 28N (Canarias)
    32628, 32629, 32630, 32631,  # WGS 84 / UTM 28N–31N
    23029, 23030, 23031,  # ED50 / UTM 29N–31N
)
VERTICAL_CODES: tuple[int, ...] = (
    5782,  # Alicante
    9392, 9393, 9394,  # Mallorca, Menorca, Ibiza
    9395, 9396, 9397, 9398, 9399, 9400, 9401,  # Canarias
    9402,  # Ceuta
)

EDGE_POINTS = 64  # puntos por lado del contorno del ámbito geográfico
OWNER = "IOGP (International Association of Oil and Gas Producers)"
DATASET = "EPSG Geodetic Parameter Dataset"
EPSG_URL = "https://epsg.org"
TERMS_URL = "https://epsg.org/terms-of-use.html"
ATTRIBUTION = (
    "Contiene datos del EPSG Geodetic Parameter Dataset, propiedad de IOGP "
    "(International Association of Oil and Gas Producers), https://epsg.org. Extracto "
    "con los valores sin modificar (solo el formato WKT1/WKT2 que da projinfo); el "
    "ámbito proyectado (bounds) lo calcula Geoblender con PROJ."
)
VERSION_KEYS: tuple[str, ...] = (
    "EPSG.VERSION",
    "EPSG.DATE",
    "PROJ.VERSION",
    "PROJ_DATA.VERSION",
)

USAGE = f"""Uso (con el Python de Blender, desde la raíz del repositorio de código):
  $env:{ENV_PROJ_BIN} = "<carpeta con projinfo y cs2cs>"
  & $PY -B tools/gen_crs_catalog.py [{OPTION_CHECK}]

  {OPTION_CHECK}   genera en memoria y compara con el catálogo guardado, sin escribir
  --ayuda, -h   muestra esta ayuda
Códigos: 0 correcto, 1 fallo o diferencias, 2 uso o entorno."""

# Ejecuta una herramienta de PROJ: argumentos y entrada estándar → salida estándar.
Runner = Callable[[Sequence[str], str | None], str]


class GenerationError(Exception):
    """La generación no puede seguir: el mensaje dice por qué."""


class UsageError(Exception):
    """Opciones no válidas."""


@dataclass(frozen=True)
class ProjTools:
    """``projinfo``, ``cs2cs`` y la carpeta de datos de una instalación de PROJ."""

    projinfo: Path
    cs2cs: Path
    data_dir: Path


def proj_tools(environ: Mapping[str, str]) -> ProjTools:
    """Las herramientas de ``GEOBLENDER_PROJ_BIN`` y su ``share/proj`` (con
    ``proj.db``); :class:`GenerationError` si falta algo."""
    folder = environ.get(ENV_PROJ_BIN, "").strip()
    if not folder:
        raise GenerationError(
            f"defina {ENV_PROJ_BIN} con la carpeta que contiene projinfo y cs2cs (p. ej. "
            "la carpeta bin de QGIS 4.2)"
        )
    bin_dir = Path(folder)
    found: dict[str, Path] = {}
    for name in ("projinfo", "cs2cs"):
        candidates = [bin_dir / f"{name}.exe", bin_dir / name]
        exe = next((path for path in candidates if path.is_file()), None)
        if exe is None:
            raise GenerationError(
                f"no hay {name} en la carpeta de {ENV_PROJ_BIN} ({bin_dir})"
            )
        found[name] = exe
    data_dir = bin_dir.parent / "share" / "proj"
    if not (data_dir / "proj.db").is_file():
        raise GenerationError(
            f"no hay share/proj/proj.db junto a la carpeta de {ENV_PROJ_BIN} ({bin_dir}): "
            "use el bin de una instalación completa de PROJ (p. ej. la de QGIS)"
        )
    return ProjTools(found["projinfo"], found["cs2cs"], data_dir)


def child_env(data_dir: str | Path, environ: Mapping[str, str]) -> dict[str, str]:
    """El entorno de ``projinfo`` y ``cs2cs``: el de ``environ`` sin ``PROJ_*`` ni
    ``GDAL_*``, con ``PROJ_DATA`` = ``data_dir`` y sin red."""
    env = {
        key: value
        for key, value in environ.items()
        if not key.upper().startswith(("PROJ_", "GDAL_"))
    }
    env["PROJ_DATA"] = str(data_dir)
    env["PROJ_NETWORK"] = "OFF"
    return env


def make_runner(exe: Path, env: Mapping[str, str]) -> Runner:
    """Ejecuta ``exe`` con ``env``; :class:`GenerationError` si no termina con 0."""

    def run(args: Sequence[str], stdin: str | None = None) -> str:
        result = subprocess.run(
            [str(exe), *args],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=dict(env),
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise GenerationError(
                f"{exe.name} {' '.join(args)} terminó con {result.returncode}: {detail}"
            )
        return result.stdout

    return run


def read_versions(data_dir: Path) -> dict[str, str]:
    """Versiones de la tabla ``metadata`` del ``proj.db`` (abierto en solo lectura e
    inmutable: no crea ni toca ningún fichero)."""
    uri = (Path(data_dir) / "proj.db").resolve().as_uri() + "?mode=ro&immutable=1"
    try:
        with sqlite3.connect(uri, uri=True) as conn:
            rows = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
    except sqlite3.Error as exc:
        raise GenerationError(f"no se puede leer la versión de proj.db ({exc})") from exc
    missing = [key for key in VERSION_KEYS if key not in rows]
    if missing:
        raise GenerationError(f"a proj.db le faltan las claves {missing} en «metadata»")
    return {key: str(rows[key]) for key in VERSION_KEYS}


def _projjson(projinfo: Runner, code: int) -> dict[str, Any]:
    text = projinfo([f"EPSG:{code}", "-o", "PROJJSON", "-q"], None)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"EPSG:{code}: projinfo no devolvió PROJJSON ({exc})") from exc
    if data.get("id") != {"authority": "EPSG", "code": code}:
        raise GenerationError(f"EPSG:{code}: el PROJJSON tiene otro identificador")
    return data


def _wkt(projinfo: Runner, code: int, fmt: str, suffix: str) -> str:
    text = projinfo([f"EPSG:{code}", "-o", fmt, "--single-line", "-q"], None).strip()
    if "\n" in text or not text.endswith(suffix):
        raise GenerationError(f"EPSG:{code}: su {fmt} no termina con {suffix}")
    return text


def _usages(projjson: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if "usages" in projjson:
        return list(projjson["usages"])
    return [projjson]


def union_bbox(projjson: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """(oeste, sur, este, norte) en grados: la unión de los ámbitos de sus usos."""
    boxes = [usage["bbox"] for usage in _usages(projjson) if "bbox" in usage]
    if not boxes:
        raise GenerationError(f"{projjson.get('name')}: sin ámbito geográfico")
    west = min(box["west_longitude"] for box in boxes)
    south = min(box["south_latitude"] for box in boxes)
    east = max(box["east_longitude"] for box in boxes)
    north = max(box["north_latitude"] for box in boxes)
    if west > east:
        raise GenerationError(f"{projjson.get('name')}: ámbito que cruza el antimeridiano")
    return (west, south, east, north)


def area_text(projjson: Mapping[str, Any]) -> str:
    """La descripción del área del primer uso."""
    for usage in _usages(projjson):
        if usage.get("area"):
            return str(usage["area"])
    raise GenerationError(f"{projjson.get('name')}: sin descripción del área")


def densify(
    bbox: tuple[float, float, float, float], per_edge: int = EDGE_POINTS
) -> list[tuple[float, float]]:
    """El contorno del rectángulo (oeste, sur, este, norte) como ``4·per_edge`` puntos
    (latitud, longitud), con las cuatro esquinas."""
    west, south, east, north = bbox
    points: list[tuple[float, float]] = []
    for index in range(per_edge):
        t = index / per_edge
        points.append((south, west + t * (east - west)))  # sur, hacia el este
        points.append((south + t * (north - south), east))  # este, hacia el norte
        points.append((north, east - t * (east - west)))  # norte, hacia el oeste
        points.append((north - t * (north - south), west))  # oeste, hacia el sur
    return points


def parse_cs2cs(text: str) -> list[tuple[float, float]]:
    """Los pares (x, y) de la salida de ``cs2cs``; un punto no transformado (``*``) es
    un error."""
    points: list[tuple[float, float]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        try:
            points.append((float(fields[0]), float(fields[1])))
        except (IndexError, ValueError) as exc:
            raise GenerationError(f"cs2cs no transformó un punto: «{line}»") from exc
    return points


def bounds_from_points(points: Iterable[tuple[float, float]]) -> list[int]:
    """[xmin, ymin, xmax, ymax] redondeados hacia fuera a metros enteros."""
    xs, ys = zip(*points, strict=True)
    return [math.floor(min(xs)), math.floor(min(ys)), math.ceil(max(xs)), math.ceil(max(ys))]


def _axes(projjson: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(projjson.get("coordinate_system", {}).get("axis", []))


def _common(projinfo: Runner, code: int, kind: str, wkt2_head: str) -> dict[str, Any]:
    data = _projjson(projinfo, code)
    west, south, east, north = union_bbox(data)
    entry: dict[str, Any] = {
        "epsg": code,
        "name": data["name"],
        "type": kind,
        "unit": "metre",
        "area": area_text(data),
        "bbox_lonlat": [west, south, east, north],
    }
    wkt2 = _wkt(projinfo, code, "WKT2_2019", f'ID["EPSG",{code}]]')
    if not wkt2.startswith(wkt2_head):
        raise GenerationError(f"EPSG:{code}: su WKT2 no empieza por {wkt2_head}")
    entry["wkt2"] = wkt2
    entry["wkt1"] = _wkt(projinfo, code, "WKT1_GDAL", f'AUTHORITY["EPSG","{code}"]]')
    return entry | {"_projjson": data}


def horizontal_entry(projinfo: Runner, cs2cs: Runner, code: int) -> dict[str, Any]:
    """La entrada de un CRS horizontal: proyectado, en metros, con ejes Este y Norte."""
    entry = _common(projinfo, code, "projected", "PROJCRS[")
    data = entry.pop("_projjson")
    axes = _axes(data)
    if data.get("type") != "ProjectedCRS":
        raise GenerationError(f"EPSG:{code} no es un CRS proyectado ({data.get('type')})")
    if [axis.get("unit") for axis in axes] != ["metre", "metre"]:
        raise GenerationError(f"EPSG:{code}: sus ejes no están en metros")
    if [axis.get("direction") for axis in axes] != ["east", "north"]:
        raise GenerationError(f"EPSG:{code}: sus ejes no son Este y Norte, en ese orden")
    base = data.get("base_crs", {}).get("id", {})
    if base.get("authority") != "EPSG":
        raise GenerationError(f"EPSG:{code}: su CRS base no tiene código EPSG")
    entry["axes"] = [axis.get("abbreviation") for axis in axes]
    entry["base_epsg"] = base["code"]
    west, south, east, north = entry["bbox_lonlat"]
    lines = "\n".join(f"{lat!r} {lon!r}" for lat, lon in densify((west, south, east, north)))
    output = cs2cs(["-f", "%.6f", f"EPSG:{base['code']}", f"EPSG:{code}"], lines + "\n")
    entry["bounds"] = bounds_from_points(parse_cs2cs(output))
    return _ordered(entry, horizontal=True)


def vertical_entry(projinfo: Runner, code: int) -> dict[str, Any]:
    """La entrada de un CRS vertical en metros."""
    entry = _common(projinfo, code, "vertical", "VERTCRS[")
    data = entry.pop("_projjson")
    axes = _axes(data)
    if data.get("type") != "VerticalCRS":
        raise GenerationError(f"EPSG:{code} no es un CRS vertical ({data.get('type')})")
    if [axis.get("unit") for axis in axes] != ["metre"]:
        raise GenerationError(f"EPSG:{code}: su eje no está en metros")
    return _ordered(entry, horizontal=False)


def _ordered(entry: Mapping[str, Any], *, horizontal: bool) -> dict[str, Any]:
    keys = ["epsg", "name", "type", "unit"]
    if horizontal:
        keys += ["axes", "base_epsg"]
    keys += ["area", "bbox_lonlat"]
    if horizontal:
        keys.append("bounds")
    keys += ["wkt2", "wkt1"]
    return {key: entry[key] for key in keys}


def build_catalog(
    projinfo: Runner,
    cs2cs: Runner,
    versions: Mapping[str, str],
    *,
    horizontal: Sequence[int] = HORIZONTAL_CODES,
    vertical: Sequence[int] = VERTICAL_CODES,
) -> dict[str, Any]:
    """El catálogo completo, con su origen y sus versiones."""
    return {
        "format": CATALOG_FORMAT,
        "schema": CATALOG_SCHEMA,
        "source": {
            "dataset": DATASET,
            "owner": OWNER,
            "url": EPSG_URL,
            "terms_of_use": TERMS_URL,
            "epsg_version": versions["EPSG.VERSION"],
            "epsg_date": versions["EPSG.DATE"],
            "proj_version": versions["PROJ.VERSION"],
            "proj_data_version": versions["PROJ_DATA.VERSION"],
            "generated_with": (
                "tools/gen_crs_catalog.py: projinfo (PROJJSON, WKT2_2019, WKT1_GDAL) y "
                "cs2cs (ámbito proyectado)"
            ),
            "attribution": ATTRIBUTION,
        },
        "horizontal": [horizontal_entry(projinfo, cs2cs, code) for code in horizontal],
        "vertical": [vertical_entry(projinfo, code) for code in vertical],
    }


def render_catalog(catalog: Mapping[str, Any]) -> str:
    """El JSON del catálogo: UTF-8, sangrado de 2, sin escapar acentos, con «\\n» final."""
    return json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"


def sha256_text(text: str) -> str:
    """sha256 del texto en UTF-8 (lo que se escribe en el fichero)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_readme(catalog_text: str, catalog: Mapping[str, Any]) -> str:
    """El ``README.md`` de ``thirdparty/epsg/`` (ADR-0019, punto 2)."""
    source = catalog["source"]
    horizontal = ", ".join(str(entry["epsg"]) for entry in catalog["horizontal"])
    vertical = ", ".join(str(entry["epsg"]) for entry in catalog["vertical"])
    return f"""# Catálogo de CRS (EPSG Dataset)

Datos de terceros sin modificar (ADR-0019) que lee `core.georef.load_catalog()` (spec 002,
RF-002-23). No se edita a mano: lo genera `tools/gen_crs_catalog.py`.

- **Origen:** {source["dataset"]}, propiedad de {source["owner"]}, a través del `proj.db`
  de PROJ {source["proj_version"]} (EPSG {source["epsg_version"]}, {source["epsg_date"]}).
- **URL:** {source["url"]}. Términos de uso: {source["terms_of_use"]}, copiados en `LICENSE`.
- **Contenido:** CRS horizontales {horizontal}; verticales {vertical}. De cada uno, el
  nombre, el tipo, la unidad, el área y el ámbito geográfico (PROJJSON) y sus WKT2:2019 y
  WKT1:GDAL, tal como los da `projinfo`. El único dato calculado es `bounds`, el ámbito en
  coordenadas proyectadas de los horizontales (su contorno, proyectado con `cs2cs` desde su
  CRS geográfico base y redondeado hacia fuera a metros enteros).
- **Atribución:** {source["attribution"]}

| Fichero | sha256 |
| --- | --- |
| `{CATALOG_NAME}` | `{sha256_text(catalog_text)}` |
"""


def parse_args(args: Sequence[str]) -> tuple[bool, bool]:
    """(solo comprobar, mostrar la ayuda); :class:`UsageError` si una opción no existe."""
    check_only = show_help = False
    for arg in args:
        if arg == OPTION_CHECK:
            check_only = True
        elif arg in ("--ayuda", "-h", "--help"):
            show_help = True
        else:
            raise UsageError(f"opción desconocida «{arg}»")
    return check_only, show_help


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    try:
        check_only, show_help = parse_args(sys.argv[1:] if argv is None else argv)
    except UsageError as exc:
        print(f"ERROR: {exc}\n\n{USAGE}", file=sys.stderr)
        return 2
    if show_help:
        print(USAGE)
        return 0
    try:
        tools = proj_tools(environ)
    except GenerationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        env = child_env(tools.data_dir, environ)
        catalog = build_catalog(
            make_runner(tools.projinfo, env),
            make_runner(tools.cs2cs, env),
            read_versions(tools.data_dir),
        )
    except (GenerationError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    text = render_catalog(catalog)
    readme = render_readme(text, catalog)
    folder = repo_root(Path(__file__)) / EPSG_FOLDER_RELPATH
    targets = {folder / CATALOG_NAME: text, folder / README_NAME: readme}
    source = catalog["source"]
    summary = (
        f"{len(catalog['horizontal'])} horizontales y {len(catalog['vertical'])} "
        f"verticales; EPSG {source['epsg_version']} ({source['epsg_date']}), PROJ "
        f"{source['proj_version']}"
    )
    if check_only:
        different = [
            path.name
            for path, content in targets.items()
            if not path.is_file() or path.read_bytes() != content.encode("utf-8")
        ]
        if different:
            print(f"DIFERENTE: {', '.join(different)} ({summary})")
            return 1
        print(f"IGUAL: el catálogo guardado coincide ({summary})")
        return 0
    for path, content in targets.items():
        _write(path, content)
    print(f"ESCRITO: {EPSG_FOLDER_RELPATH}/{CATALOG_NAME} y {README_NAME} ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
