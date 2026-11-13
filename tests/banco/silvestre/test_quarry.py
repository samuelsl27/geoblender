# SPDX-License-Identifier: GPL-3.0-or-later
"""Banco del proyecto de referencia: las dos superficies de su versión vigente, su clasificación
y «explotación hasta la final» frente a las suyas (spec 014, T37; CE-014-09; HU-014-3, HU-014-4;
RF-014-12 a RF-014-18; plan 014 §7.1, «Banco»; constitución, principio 2).

CE-014-09: con el banco privado del proyecto de referencia, las dos superficies de su versión
vigente con los mismos perfiles, fondos y orden: la explotación, el desdoblado y «explotación hasta
la final» dentro de la tolerancia que fija esta comparación (el plan no fija otra: son las de la
013 y la 011, abajo) y con cada diferencia en su clase. Cada diferencia la explica la persona que
lo ejecuta (hito H3).

Lo ejecuta el arnés de los bancos de la 001 (``tools/bench_silvestre.py``) solo con
``tools/check.py --banco`` y con ``GEOBLENDER_SILVESTRE_DIR`` apuntando a la carpeta del banco;
sin la variable (o si no es una carpeta), se omite con la orden que la activa. **Solo lectura**:
los ficheros del banco solo se abren para leer, y el arnés comprueba que la carpeta queda igual
(RNF-001-05). Lo que se escribe (el MDT llevado a la rejilla de las referencias) va a una carpeta
temporal de ``%TEMP%`` que se borra. Ni la ruta ni el nombre de ningún fichero, ni los nombres de
la ficha, se escriben aquí ni en la salida: solo la parte de la comparación y sus cifras.

**La forma del banco** (sin nombres de ficheros del banco: patrones y los nombres de la ficha; todo
se busca en la versión vigente y, si no está allí, en el resto de la carpeta, sin seguir enlaces,
en un orden fijo; las copias iguales, mismo sha256, cuentan como una). Es la de las dos superficies
de la versión vigente del proyecto de referencia que describe su análisis
(``Documentacion/analisis_proyecto_silvestre``, 03 §3.4 y §6.1): la final se diseña primero y la
explotación se apoya en ella; la cuña entre las dos es el desdoblado. Si el banco real no la
tiene, la comparación dice **todo** lo que no encuentra, se ve en el H3 y se adapta esta
comparación (nunca el banco):

1. **La versión vigente** y **la superficie de partida**: como en ``test_design`` (la carpeta
   ``V<nn>_<rasgo>_VIGENTE`` de número mayor; el GeoTIFF con «MDT», «DEM», «DTM» o «terreno» en
   el nombre, que se lleva a la rejilla de las referencias con el remuestreo de Geoblender si tiene
   otra).
2. **La ficha de la cantera**: un JSON (UTF-8) con «ficha_cantera» en el nombre (no «ficha_diseno»,
   que es la de ``test_design``: las dos conviven). Los perfiles, el orden y el ancla del proyecto
   de referencia no están en sus rásteres sino en sus programas, y Geoblender no tiene ninguna cifra
   por defecto para ellos (D-7 de la 013): los declara esta ficha, que la persona del H3 prepara con
   ellos junto al banco (a una copia, nunca a él) o adapta aquí; también las cifras de la
   referencia que se comparan, tal como las dio (con su celda nominal). Cada fichero que nombra es
   un GeoTIFF o un ``.npy`` de números (sin ``pickle``) con la **misma rejilla y CRS** que la
   superficie final de la referencia, que es un GeoTIFF y da la rejilla; se nombra sin extensión.
   Sin dato (``NaN``) donde no hay valor; una máscara son sus celdas con dato distinto de 0::

       {"orden": "final primero" | "explotación primero",
        "recinto": "<máscara del recinto excavable>",
        "relleno": "<máscara de las zonas de restauración por relleno>",   // opcional (D-11)
        "fondos": "<cotas de los fondos, sin dato fuera>",                 // opcional
        "anillo_celdas": 3,       // opcional: la coronación (D-7) de un lado sin semillas
        "final": {"referencia": "<su superficie final>",
                  "semillas": "<cotas de las semillas>",   // opcional: sin ellas, la coronación
                  "perfil": {"altura_m": 5, "cara_deg": 35, "berma_m": 6, "ancla_m": 125},
                  "factor_malla": 0.97,                    // opcional, 1 por defecto
                  "ancla": "fija" | "al fondo de cada muro"},   // opcional, fija
        "explotacion": {"referencia": "<su superficie de explotación, la vigente>",
                        "previa": "<la de antes de «explotación hasta la final»>",
                        ... (lo mismo que la final)},
        "hasta_la_final": {"zonas": "<máscara de las celdas en que la bajó>",
                           "umbral_m": 1, "area_minima_ha": 0.2},   // opcionales (D-5)
        "cifras": {"explotacion_m3": ..., "desdoblado_m3": ..., "relleno_m3": ...,
                   "hasta_la_final_m3": ...}}    // las que dé la referencia

   ``previa`` va con ``hasta_la_final`` y solo con él; «al fondo de cada muro», con ``fondos``.

**Lo calculado** (con ``design.quarry``, que es el cálculo de «Calcular» y de reproducir una
cantera; el dominio de trabajo, las celdas del recinto con terreno; sin sectores; el espesor
mínimo, el de la 012): sobre las superficies de la referencia, la regla de orden, la clasificación,
el aviso de desdoblado sobre terreno sin explotar y «explotación hasta la final» en las zonas de la
referencia; y **la cadena**: las dos superficies de Geoblender (``quarry_steps``) con los perfiles,
las semillas, los fondos, las anclas y el orden de la ficha, y «explotación hasta la final» en las
zonas de la referencia (el modo «capa», P-2).

**La comparación** y qué justifica cada diferencia (las cifras se imprimen en líneas
``CE-014-09: …``, para anotarlas en la verificación del H3):

(a) *El orden* (RF-014-13, RF-014-14). Las superficies de la referencia (la explotación vigente y
    la previa, cada una con la final) pasan por la regla de orden de la ficha y ``≤ z``; cada celda
    del dominio queda **igual** (a ≤ 1 mm, ``EQUAL_M``: la tolerancia de RF-014-14), o con **la
    final por encima de la explotación**, o con alguna **por encima del terreno**. Lo que la regla
    mueve, en m³, no pasa de ``10⁻⁴`` de la excavación de la explotación (``VOLUME_TOL``: D-14 d de
    la 011, la tolerancia de las cifras de volumen del banco); si pasa, la regla de Geoblender no es
    la de la referencia, o la final de la ficha no es su superficie final (es la restaurada).
(b) *Las cifras* (RF-014-15, RF-014-16, RF-014-18). La clasificación de Geoblender de las
    superficies de la referencia ya ordenadas da la excavación de la explotación, el desdoblado y el
    relleno de restauración, y lo que pasa a la explotación con «explotación hasta la final» es
    ``Σ (previa − vigente) · área de celda``; cada una frente a la de la ficha corregida por el
    área de celda (la referencia contaba la celda nominal, los pasos redondeados al centímetro;
    Geoblender, la real: como CE-011-05) es **igual** (a ≤ 10⁻⁴), **explicada por el espesor
    mínimo** (Geoblender da menos, como mucho lo que suman las celdas de su clase de más de 0 y
    hasta el espesor mínimo, que la 011 no cuenta y la referencia quizá sí) o **sin explicar**.
(c) *«Explotación hasta la final»* (RF-014-17, RF-014-18). En las zonas en que la referencia bajó
    la explotación, Geoblender la baja desde la previa con su perfil y su ancla: cada celda es
    **igual** (≤ 1 mm), **explicada por la cota de ancla** (la referencia llega a la final, a ≤ 1
    mm, y Geoblender se queda, como pide RF-014-18, en la cota de ancla inmediatamente por encima,
    a menos de un banco) o **sin explicar**, y falla si queda alguna. Fuera de las zonas, la
    transición con el resto de la explotación (Geoblender, a la cara del perfil; la referencia, a su
    manera) y el aviso de Geoblender sobre la previa frente a las zonas de la referencia se
    informan, sin fallar.
(d) *La cadena* (RF-014-12 a RF-014-14, con RF-014-02, 05 y 11). Se informa, sin fallar: cuántas
    celdas de cada superficie difieren (> 1 mm) y cuánto, y sus cifras frente a las de la ficha;
    la persona del H3 lo explica con (a), (b) y (c) y con CE-013-10 (las envolventes y los
    escalonados de cada lado), o con lo que la referencia hizo además (su análisis, 03 §3.4).
"""

from __future__ import annotations

import json
import math
import re
import tempfile
import unittest
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import numpy as np

from tests.support import bank_folder as shape
from tests.support.bank_folder import ENV, BankShapeError  # ENV: lo lee test_quarry_bank
from tests.support.package import import_geoblender

geotiff = import_geoblender("gis.geotiff")
gis_messages = import_geoblender("gis.messages")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
envelopes = import_geoblender("design.envelopes")
quarry = import_geoblender("design.quarry")
seeds_mod = import_geoblender("design.seeds")

NAME = "CE-014-09"  # el nombre de las líneas de la comparación
EQUAL_M = 1e-3
"""Lo que se cuenta como igual (m): la tolerancia del invariante de RF-014-14 (1 mm), más de diez
veces la cuantización de float32 a 1.000 m de cota."""
VOLUME_TOL = 1e-4
"""Lo que pueden diferir las cifras de volumen, relativo (D-14 d de la 011)."""
MIN_THICKNESS_M = 0.02
"""El espesor mínimo de la clasificación (D-6 de la 012)."""
BUDGET_S = 60.0
"""Lo que dura un paso como mucho: todo de una vez, no hay interfaz que atender."""
OPERATION = "Comparación del banco"
SHEET_PATTERN = re.compile(r"(?i)ficha[_ ]?cantera")
JSON_SUFFIX = ".json"
RASTER_SUFFIXES = (*shape.TIFF_SUFFIXES, shape.NPY_SUFFIX)
Surface = model.Surface
ORDERS = MappingProxyType({"final primero": model.Order.FINAL_FIRST,
                           "explotación primero": model.Order.EXPLOITATION_FIRST,
                           "explotacion primero": model.Order.EXPLOITATION_FIRST})
ANCHORS = MappingProxyType({"fija": model.AnchorMode.FIXED,
                            "al fondo de cada muro": model.AnchorMode.NEAREST_FLOOR})
SIDES = MappingProxyType({Surface.FINAL: "final", Surface.EXPLOITATION: "explotacion"})
"""La clave de cada lado en la ficha, que es también el código de su perfil (D-17)."""
SIDE_LABELS = MappingProxyType({Surface.FINAL: "la final",
                                Surface.EXPLOITATION: "la explotación"})
EXP_CUT, UNSPLIT, FILL, TO_FINAL = ("explotacion_m3", "desdoblado_m3", "relleno_m3",
                                    "hasta_la_final_m3")
FIGURES = MappingProxyType({
    EXP_CUT: "excavación de la explotación", UNSPLIT: "desdoblado",
    FILL: "relleno de restauración", TO_FINAL: "explotación hasta la final"})
"""Las cifras de la referencia que se comparan, en su orden, con su nombre."""
EQUAL, THIN, UNEXPLAINED = "igual", "explicada por el espesor mínimo", "sin explicar"
FLOORS_LAYER, FLOORS_FIELD = "fondos de la ficha", "cota"
TOP_KEYS = frozenset({"orden", "recinto", "relleno", "fondos", "anillo_celdas", "final",
                      "explotacion", "hasta_la_final", "cifras"})
SIDE_KEYS = frozenset({"referencia", "previa", "semillas", "perfil", "factor_malla", "ancla"})
TO_FINAL_KEYS = frozenset({"zonas", "umbral_m", "area_minima_ha"})


# --- La ficha -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SideSpec:
    """Un lado de la ficha: su ``surface``, los nombres de los ficheros de su ``reference``, de la
    explotación ``previous`` (antes de «explotación hasta la final»; solo la explotación) y de sus
    ``seeds`` (``None``: la coronación del recinto), su ``profile`` (``model.BenchProfile`` de
    código el de :data:`SIDES`) y su ``anchor`` (``model.AnchorMode``)."""

    surface: object
    reference: str
    previous: str | None
    seeds: str | None
    profile: object
    anchor: object


@dataclass(frozen=True, slots=True)
class ToFinalSpec:
    """«Explotación hasta la final» de la referencia: el fichero de sus ``zones``, el umbral de
    desdoblado (m) y el área mínima (ha) del aviso."""

    zones: str
    threshold_m: float
    min_area_ha: float


@dataclass(frozen=True, slots=True)
class Sheet:
    """La ficha de la cantera (véase el módulo): el ``order``, los ficheros del recinto (``area``),
    de las zonas de relleno (``fill``) y de los fondos (``floors``), el anillo de coronación, los
    dos lados, «explotación hasta la final» de la referencia y sus cifras (clave → m³)."""

    order: object
    area: str
    fill: str | None
    floors: str | None
    ring_cells: int
    final: SideSpec
    exploitation: SideSpec
    to_final: ToFinalSpec | None
    figures: Mapping[str, float]

    def side(self, surface: object) -> SideSpec:
        return self.final if Surface(surface) is Surface.FINAL else self.exploitation


def _show(value: object) -> str:
    return str(value) if isinstance(value, Decimal) else repr(value)


def _number(item: Mapping[str, object], key: str, where: str, problems: list[str], *,
            default: Decimal | None = None) -> Decimal | None:
    """El número ``item[key]`` (finito) o ``default`` si falta; si no es un número, se anota."""
    if key not in item:
        if default is None:
            problems.append(f"{where}: falta «{key}»")
        return default
    value = item[key]
    if isinstance(value, Decimal) and value.is_finite():
        return value
    problems.append(f"{where}: «{key}» debe ser un número, no {_show(value)}")
    return None


def _text(item: Mapping[str, object], key: str, where: str, problems: list[str], *,
          optional: bool = False) -> str | None:
    """El texto no vacío ``item[key]``; si falta (y no es ``optional``) o no lo es, se anota."""
    if optional and key not in item:
        return None
    value = item.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    problems.append(f"{where}: falta «{key}» (un texto)" if key not in item
                    else f"{where}: «{key}» debe ser un texto no vacío, no {_show(value)}")
    return None


def _unknown(item: Mapping[str, object], known: frozenset[str], where: str,
             problems: list[str]) -> None:
    """Anota las claves de ``item`` que la ficha no tiene (una errata no se ignora en silencio)."""
    for key in sorted(set(item) - known):
        problems.append(f"{where}: «{key}» no es un campo de la ficha de la cantera")


def _parameter(item: Mapping[str, object], field: str, key: str, where: str,
               problems: list[str]) -> float | int | None:
    """``item[field]`` comprobado como el parámetro de la 014 ``key`` (``check_quarry_param``);
    si falta, su valor por defecto declarado (D-5, D-7)."""
    if field not in item:
        found = params.QUARRY_PARAMS[key].default
        return found if isinstance(found, int | float) else None
    value = _number(item, field, where, problems)
    if value is None:
        return None
    number: float | int = float(value)
    if params.QUARRY_PARAMS[key].value_type == "int":
        if value != value.to_integral_value():
            problems.append(f"{where}: «{field}» debe ser un número entero, no {value}")
            return None
        number = int(value)
    try:
        return params.check_quarry_param(key, number)
    except (messages.DesignError, TypeError) as error:
        problems.append(f"{where}: «{field}»: {error}")
        return None


def _profile(item: Mapping[str, object], code: str, where: str, problems: list[str]
             ) -> object | None:
    """El perfil de banco de ``item["perfil"]`` (``altura_m``, ``cara_deg``, ``berma_m``,
    ``ancla_m``) con el ``factor_malla`` del lado, comprobado por el dominio."""
    raw = item.get("perfil")
    keys = ("altura_m", "cara_deg", "berma_m", "ancla_m")
    if not isinstance(raw, dict):
        problems.append(f"{where}: falta «perfil» ({', '.join(keys)})")
        return None
    numbers = [_number(raw, key, f"{where}, perfil", problems) for key in keys]
    mesh = _number(item, "factor_malla", where, problems, default=Decimal(1))
    if any(number is None for number in numbers) or mesh is None:
        return None
    height, face, berm, anchor = (float(number) for number in numbers if number is not None)
    try:
        return model.BenchProfile(code, code, height, face, berm, anchor, float(mesh))
    except (messages.DesignError, ValueError, TypeError) as error:
        problems.append(f"{where}: el perfil no es válido ({error})")
        return None


def _side_spec(data: Mapping[str, object], surface: object, floors: bool,
               problems: list[str]) -> SideSpec | None:
    key = SIDES[surface]
    where = f"el lado «{key}»"
    item = data.get(key)
    if not isinstance(item, dict):
        problems.append(f"la ficha de la cantera: falta «{key}» (un objeto con su referencia y "
                        "su perfil)")
        return None
    before = len(problems)
    _unknown(item, SIDE_KEYS, where, problems)
    reference = _text(item, "referencia", where, problems)
    previous = _text(item, "previa", where, problems, optional=True)
    if previous is not None and surface is Surface.FINAL:
        problems.append(f"{where}: «previa» es de la explotación, no de la final")
    seeds = _text(item, "semillas", where, problems, optional=True)
    profile = _profile(item, key, where, problems)
    anchor = ANCHORS.get(str(item.get("ancla", "fija")).strip().casefold())
    if anchor is None:
        problems.append(f"{where}: «ancla» es fija o al fondo de cada muro, no "
                        f"{_show(item.get('ancla'))}")
    elif anchor is model.AnchorMode.NEAREST_FLOOR and not floors:
        problems.append(f"{where}: el ancla «al fondo de cada muro» necesita «fondos»")
    if len(problems) > before or reference is None or profile is None or anchor is None:
        return None
    return SideSpec(surface, reference, previous, seeds, profile, anchor)


def _to_final_spec(data: Mapping[str, object], problems: list[str]) -> ToFinalSpec | None:
    item = data.get("hasta_la_final")
    where = "«hasta_la_final»"
    if not isinstance(item, dict):
        problems.append(f"{where}: debe ser un objeto con «zonas»")
        return None
    before = len(problems)
    _unknown(item, TO_FINAL_KEYS, where, problems)
    zones = _text(item, "zonas", where, problems)
    threshold = _parameter(item, "umbral_m", params.UNSPLIT_THRESHOLD, where, problems)
    area = _parameter(item, "area_minima_ha", params.UNSPLIT_MIN_AREA, where, problems)
    if len(problems) > before or zones is None or threshold is None or area is None:
        return None
    return ToFinalSpec(zones, float(threshold), float(area))


def _figures(data: Mapping[str, object], problems: list[str]) -> dict[str, float]:
    raw = data.get("cifras", {})
    if not isinstance(raw, dict):
        problems.append("«cifras»: debe ser un objeto con las cifras de la referencia (m³)")
        return {}
    _unknown(raw, frozenset(FIGURES), "«cifras»", problems)
    found: dict[str, float] = {}
    for key in FIGURES:
        if key in raw:
            value = _number(raw, key, "«cifras»", problems)
            if value is not None and value < 0:
                problems.append(f"«cifras»: «{key}» es un volumen ≥ 0, no {value}")
            elif value is not None:
                found[key] = float(value)
    return found


def _parse_sheet(data: object, problems: list[str]) -> Sheet | None:
    if not isinstance(data, dict):
        problems.append("la ficha de la cantera debe ser un objeto con sus campos")
        return None
    before = len(problems)
    _unknown(data, TOP_KEYS, "la ficha de la cantera", problems)
    order = ORDERS.get(str(data.get("orden")).strip().casefold())
    if order is None:
        problems.append("la ficha de la cantera: «orden» es final primero o explotación primero, "
                        f"no {_show(data.get('orden'))}")
    where = "la ficha de la cantera"
    area = _text(data, "recinto", where, problems)
    fill = _text(data, "relleno", where, problems, optional=True)
    floors = _text(data, "fondos", where, problems, optional=True)
    ring = _parameter(data, "anillo_celdas", params.CROWN_RING, where, problems)
    final = _side_spec(data, Surface.FINAL, floors is not None, problems)
    exploitation = _side_spec(data, Surface.EXPLOITATION, floors is not None, problems)
    wanted = "hasta_la_final" in data
    to_final = _to_final_spec(data, problems) if wanted else None
    if exploitation is not None and (wanted != (exploitation.previous is not None)):
        problems.append("el lado «explotacion»: «previa» va con «hasta_la_final», y solo con él")
    figures = _figures(data, problems)
    if (len(problems) > before or order is None or area is None or ring is None
            or final is None or exploitation is None):
        return None
    return Sheet(order, area, fill, floors, int(ring), final, exploitation, to_final,
                 MappingProxyType(figures))


def _read_sheet(version: list[Path], everything: list[Path], problems: list[str]) -> Sheet | None:
    def pick(paths: list[Path]) -> list[Path]:
        return [path for path in paths
                if path.suffix.lower() == JSON_SUFFIX and SHEET_PATTERN.search(path.stem)]

    found = shape.distinct(pick(version) or pick(everything))
    if len(found) != 1:
        problems.append("la ficha de la cantera (un JSON con «ficha_cantera» en el nombre, véase "
                        f"la forma del banco): se esperaba una y hay {_count(found)}")
        return None
    try:
        data = json.loads(found[0].read_text(encoding="utf-8-sig"), parse_float=Decimal,
                          parse_int=Decimal)
    except (OSError, ValueError) as error:
        where = f" (línea {error.lineno})" if isinstance(error, json.JSONDecodeError) else ""
        problems.append(f"la ficha de la cantera no es un JSON legible en UTF-8{where}")
        return None
    return _parse_sheet(data, problems)


# --- Buscar en el banco ---------------------------------------------------------------------


def _count(found: Sequence[object]) -> str:
    return "ninguna" if not found else f"{len(found)} distintas"


def _key(stem: str) -> str:
    return stem.casefold()


def _wanted(sheet: Sheet) -> list[tuple[str, str]]:
    """Los ficheros que nombra la ficha, en un orden fijo (la superficie final primero: da la
    rejilla): su descripción y su nombre sin extensión."""
    wanted = [("la superficie final de la referencia", sheet.final.reference),
              ("la superficie de explotación de la referencia", sheet.exploitation.reference)]
    if sheet.exploitation.previous is not None:
        wanted.append(("la explotación previa de la referencia", sheet.exploitation.previous))
    wanted.append(("el recinto", sheet.area))
    if sheet.fill is not None:
        wanted.append(("las zonas de restauración por relleno", sheet.fill))
    if sheet.floors is not None:
        wanted.append(("los fondos", sheet.floors))
    for surface in (Surface.FINAL, Surface.EXPLOITATION):
        seeds = sheet.side(surface).seeds
        if seeds is not None:
            wanted.append((f"las semillas de {SIDE_LABELS[surface]}", seeds))
    if sheet.to_final is not None:
        wanted.append(("las zonas de «explotación hasta la final»", sheet.to_final.zones))
    return wanted


def _resolve(sheet: Sheet, version: list[Path], everything: list[Path], problems: list[str]
             ) -> dict[str, Path]:
    """El fichero de cada nombre de la ficha (``_key`` → ruta): uno solo salvo copias iguales,
    el de la versión vigente o, si no está allí, el del banco."""
    def pick(paths: list[Path], stem: str) -> list[Path]:
        return [path for path in paths if path.suffix.lower() in RASTER_SUFFIXES
                and _key(path.stem) == _key(stem)]

    paths: dict[str, Path] = {}
    for what, stem in _wanted(sheet):
        if _key(stem) in paths:
            continue
        found = shape.distinct(pick(version, stem) or pick(everything, stem))
        if len(found) != 1:
            problems.append(f"{what} (un GeoTIFF o .npy de la ficha): se esperaba uno y hay "
                            f"{_count(found).replace('ninguna', 'ninguno')}")
        else:
            paths[_key(stem)] = found[0]
    return paths


def _read(path: Path, grid: object, crs: object, what: str, problems: list[str]
          ) -> np.ndarray | None:
    """Los valores de ``path`` (float64, ``NaN`` sin dato) en la rejilla ``grid``, sin remuestrear:
    otra rejilla o CRS se anota en ``problems``."""
    if path.suffix.lower() == shape.NPY_SUFFIX:
        try:
            values = np.load(path, allow_pickle=False)
        except (OSError, ValueError):
            problems.append(f"{what}: el .npy no se puede leer como números")
            return None
        if values.shape != grid.shape or values.dtype.kind not in "fiu":
            problems.append(f"{what}: el .npy no tiene la forma de la rejilla de la superficie "
                            "final ni es de números")
            return None
        return np.asarray(values, dtype=np.float64)
    try:
        source = geotiff.read_geotiff(path)
    except gis_messages.GisError as error:
        problems.append(f"{what}: no se puede leer el GeoTIFF ({error.code})")
        return None
    if source.declared_crs is None or source.declared_crs != crs:
        problems.append(f"{what}: no declara el CRS de la superficie final")
    elif not source.grid.same_geometry(grid):
        problems.append(f"{what}: tiene otra rejilla que la superficie final")
    else:
        return np.asarray(source.values, dtype=np.float64)
    return None


def compare(folder: Path) -> Comparison:
    """CE-014-09 sobre el banco ``folder`` (véase el módulo)."""
    version = shape.files(shape.find_version(folder))
    everything = shape.files(folder)
    problems: list[str] = []
    sheet = _read_sheet(version, everything, problems)
    starts = shape.distinct(shape.tiffs(version, shape.START_PATTERN)
                            or shape.tiffs(everything, shape.START_PATTERN))
    if len(starts) != 1:
        problems.append("la superficie de partida (GeoTIFF con MDT, DEM, DTM o terreno en el "
                        f"nombre): se esperaba una y hay {_count(starts)}")
    paths = {} if sheet is None else _resolve(sheet, version, everything, problems)
    first = None if sheet is None else paths.get(_key(sheet.final.reference))
    if first is not None and first.suffix.lower() not in shape.TIFF_SUFFIXES:
        problems.append("la superficie final de la referencia es un .npy: tiene que ser un "
                        "GeoTIFF, que da la rejilla y el CRS")
    if problems or sheet is None or first is None:
        raise BankShapeError(_shape_message(problems))
    try:
        final = geotiff.read_geotiff(first)
    except gis_messages.GisError as error:
        raise BankShapeError(_shape_message(
            [f"la superficie final de la referencia no se puede leer ({error.code})"])) from None
    crs, vertical = shape.declared(final, "la superficie final de la referencia")
    grid = final.grid
    arrays: dict[str, np.ndarray | None] = {_key(first.stem): np.asarray(final.values,
                                                                         dtype=np.float64)}
    for what, stem in _wanted(sheet):
        if _key(stem) not in arrays:
            arrays[_key(stem)] = _read(paths[_key(stem)], grid, crs, what, problems)
    if problems:
        raise BankShapeError(_shape_message(problems))

    def values(stem: str) -> np.ndarray:
        found = arrays[_key(stem)]
        assert found is not None  # sin problemas
        return found

    with tempfile.TemporaryDirectory(prefix="gb-banco-014-") as name:
        ready = shape.on_grid(starts[0], grid, crs, vertical, Path(name), "partida",
                              "la superficie de partida")
        start = np.asarray(geotiff.read_geotiff(ready).values, dtype=np.float64)
    return compare_values(sheet, grid, start, values)


def _shape_message(problems: Sequence[str]) -> str:
    return ("el banco no tiene la forma que espera la comparación (véase el docstring de la "
            "comparación); no se encuentra:\n  - " + "\n  - ".join(problems))


# --- La comparación -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class OrderResult:
    """(a) Una pareja de superficies de la referencia frente a la regla de orden: las celdas del
    dominio con dato en las tres (``cells``) y, de ellas, las que quedan iguales, las de la final
    por encima de la explotación y las de alguna por encima del terreno (a más de 1 mm); las del
    dominio sin dato en alguna (``nodata``); lo que mueve la regla (``changed_m3``) y la excavación
    de la explotación (``moved_m3``, la base de la tolerancia)."""

    label: str
    cells: int
    equal: int
    final_above: int
    above_terrain: int
    nodata: int
    changed_m3: float
    moved_m3: float

    @property
    def relative(self) -> float:
        if self.changed_m3 == 0.0:
            return 0.0
        return self.changed_m3 / self.moved_m3 if self.moved_m3 > 0.0 else math.inf


@dataclass(frozen=True, slots=True, eq=False)
class FigureResult:
    """(b) Una cifra (``key``, de :data:`FIGURES`): la de Geoblender (``found_m3``), la de la ficha
    corregida por el área de celda (``reference_m3``), lo que suma su clase entre 0 y el espesor
    mínimo (``thin_m3``) y su clase (:data:`EQUAL`, :data:`THIN` o :data:`UNEXPLAINED`)."""

    key: str
    found_m3: float
    reference_m3: float
    thin_m3: float
    verdict: str

    @property
    def label(self) -> str:
        return FIGURES[self.key]

    @property
    def relative(self) -> float:
        difference = self.found_m3 - self.reference_m3
        if self.reference_m3 == 0.0:
            return 0.0 if difference == 0.0 else math.inf
        return difference / self.reference_m3


@dataclass(frozen=True, slots=True, eq=False)
class ToFinalResult:
    """(c) «Explotación hasta la final» de Geoblender en las zonas de la referencia: las celdas de
    las zonas (``zone_cells``) iguales, explicadas por la cota de ancla (``by_anchor``) y sin
    explicar (con la diferencia máxima de estas); las celdas de fuera que difieren (la transición)
    y su máxima; lo que pasa a la explotación con Geoblender y en la referencia (m³); y el aviso de
    Geoblender sobre la explotación previa: sus zonas, su área (ha), su volumen y sus celdas, y
    cuántas de ellas están en las zonas de la referencia."""

    zone_cells: int
    equal: int
    by_anchor: int
    unexplained: int
    unexplained_max_m: float
    transition_cells: int
    transition_max_m: float
    found_m3: float
    reference_m3: float
    warned_zones: int
    warned_ha: float
    warned_m3: float
    warned_cells: int
    warned_in_reference: int


@dataclass(frozen=True, slots=True, eq=False)
class SurfaceFit:
    """(d) Una superficie de la cadena frente a la de la referencia, en el dominio: sus celdas con
    dato en la referencia, las que difieren (> 1 mm), la diferencia máxima y la media."""

    cells: int
    differing: int
    max_abs_m: float
    mean_m: float


@dataclass(frozen=True, slots=True, eq=False)
class ChainResult:
    """(d) La cadena: el ``error`` si Geoblender no la pudo calcular (el texto del rechazo) o cada
    superficie frente a la de la referencia, las celdas que cambió la regla de orden y sus cifras
    frente a las de la ficha."""

    error: str | None
    final: SurfaceFit | None
    exploitation: SurfaceFit | None
    adjusted: int
    figures: tuple[FigureResult, ...]


@dataclass(frozen=True, slots=True, eq=False)
class Comparison:
    """Las cifras de la versión vigente del banco: el dominio (celdas), el área real y la nominal
    de la celda, y las partes (a) a (d)."""

    cells: int
    cell_area_m2: float
    nominal_m2: float
    order: tuple[OrderResult, ...]
    figures: tuple[FigureResult, ...]
    to_final: ToFinalResult | None
    chain: ChainResult


def nominal_area(grid: object) -> float:
    """El área nominal de la celda: el producto de los pasos redondeados al centímetro (como
    CE-011-05)."""
    return round(grid.dx, 2) * round(grid.dy, 2)


def _last(steps: object) -> object:
    found = None
    for found in steps:
        pass
    return found.result


def _default(key: str) -> float:
    return float(params.PARAMS[key].default)


def _mask(values: np.ndarray) -> np.ndarray:
    """Las celdas de una máscara de la ficha: con dato distinto de 0."""
    with np.errstate(invalid="ignore"):
        return np.isfinite(values) & (values != 0.0)


def _order(sheet: Sheet, label: str, final: np.ndarray, exploitation: np.ndarray,
           start: np.ndarray, domain: np.ndarray, area: float) -> tuple[OrderResult, object]:
    """(a) La pareja ``final``, ``exploitation`` de la referencia por la regla de orden de la
    ficha: su :class:`OrderResult` y las superficies ordenadas (``quarry.OrderedSurfaces``)."""
    ordered = quarry.order_surfaces(sheet.order, final, exploitation, start)
    known = domain & np.isfinite(final) & np.isfinite(exploitation) & np.isfinite(start)
    with np.errstate(invalid="ignore"):
        above = known & (final > exploitation + EQUAL_M)
        high = known & ((exploitation > start + EQUAL_M) | (final > start + EQUAL_M))
        moved = np.abs(ordered.final - final) + np.abs(ordered.exploitation - exploitation)
        changed = known & (moved > EQUAL_M)
        dug = start - exploitation
        cut = known & (dug > MIN_THICKNESS_M)
    return OrderResult(
        label, int(known.sum()), int((known & ~changed).sum()), int(above.sum()),
        int(high.sum()), int((domain & ~known).sum()),
        math.fsum(moved[known].tolist()) * area,
        math.fsum(dug[cut].tolist()) * area), ordered


def _verdict(found: float, reference: float, thin: float) -> str:
    """La clase de la diferencia de una cifra (véase el módulo, (b))."""
    tolerance = VOLUME_TOL * abs(reference)
    difference = found - reference
    if abs(difference) <= tolerance:
        return EQUAL
    if -thin - tolerance <= difference < 0.0:
        return THIN
    return UNEXPLAINED


def _thin(values: np.ndarray, where: np.ndarray, area: float) -> float:
    """Lo que suman ``values`` (m) en las celdas ``where`` de más de 0 y hasta el espesor mínimo."""
    with np.errstate(invalid="ignore"):
        chosen = where & np.isfinite(values) & (values > 0.0) & (values <= MIN_THICKNESS_M)
    return math.fsum(values[chosen].tolist()) * area


def _class_figures(sheet: Sheet, classes: object, final: np.ndarray, exploitation: np.ndarray,
                   start: np.ndarray, domain: np.ndarray, fill: np.ndarray | None,
                   factor: float, area: float, previous: np.ndarray | None = None
                   ) -> tuple[FigureResult, ...]:
    """(b) Las cifras de la clasificación ``classes`` de ``final`` y ``exploitation`` (y, con la
    explotación ``previous``, lo que pasó a la explotación) frente a las de la ficha que haya."""
    zone = np.zeros(domain.shape, dtype=bool) if fill is None else fill
    with np.errstate(invalid="ignore"):
        delta = exploitation - final
        dug = start - exploitation
    total = classes.total
    found = {EXP_CUT: (total.exp_cut_m3, _thin(dug, domain, area)),
             UNSPLIT: (total.unsplit_m3, _thin(delta, domain & ~zone, area)),
             FILL: (total.fill_m3, _thin(delta, domain & zone, area))}
    if previous is not None:
        with np.errstate(invalid="ignore"):
            passed = previous - exploitation
            chosen = domain & np.isfinite(passed) & (passed > 0.0)
        found[TO_FINAL] = (math.fsum(passed[chosen].tolist()) * area, 0.0)
    results = []
    for key in FIGURES:
        if key in sheet.figures and key in found:
            value, thin = found[key]
            reference = sheet.figures[key] * factor
            results.append(FigureResult(key, value, reference, thin,
                                        _verdict(value, reference, thin)))
    return tuple(results)


def _floor_map(levels: np.ndarray, grid: object) -> object:
    """Los fondos de la ficha como un mapa de fondos de la 014: sus celdas con cota, como un solo
    polígono (el mapa no se dibuja: solo siembra y ancla)."""
    found = np.isfinite(levels)
    low = float(levels[found].min()) if found.any() else math.nan
    return quarry.FloorMap(FLOORS_LAYER, FLOORS_FIELD, np.where(found, levels, np.nan),
                           found.astype(np.int32), (1,), (low,), (int(found.sum()),),
                           grid.cell_area)


def _anchor(sheet: Sheet, floors: object | None, grid: object) -> float | np.ndarray:
    """La cota de ancla de la explotación: la de su perfil o, «al fondo de cada muro», la rejilla
    de anclas de los fondos (RF-014-11)."""
    side = sheet.exploitation
    if side.anchor is model.AnchorMode.NEAREST_FLOOR and floors is not None:
        return _last(quarry.floor_anchor_steps(floors, grid, budget_s=BUDGET_S)).grid
    return float(side.profile.anchor_m)


def _to_final(sheet: Sheet, final: np.ndarray, previous: np.ndarray, current: np.ndarray,
              start: np.ndarray, domain_set: object, grid: object, floors: object | None,
              zones: np.ndarray) -> ToFinalResult:
    """(c) «Explotación hasta la final» de Geoblender en las zonas ``zones`` de la referencia,
    desde su explotación ``previous``, frente a la suya (``current``); y el aviso sobre la
    previa."""
    assert sheet.to_final is not None
    domain = domain_set.mask
    profile = sheet.exploitation.profile
    area = grid.cell_area
    classes = _last(quarry.classify_steps(final, previous, start, domain_set, grid,
                                          MIN_THICKNESS_M, budget_s=BUDGET_S))
    warned = _last(quarry.unsplit_zones_steps(final, previous, start, classes, grid,
                                              sheet.to_final.threshold_m,
                                              sheet.to_final.min_area_ha, budget_s=BUDGET_S))
    target = zones & domain
    slope = envelopes.sector_slope(domain_set.labels, [], envelopes.SlopeRule(
        math.tan(math.radians(profile.face_deg)), profile.mesh_factor))
    lowered = _last(quarry.to_final_steps(
        final, previous, start, domain_set, grid, target, anchor=_anchor(sheet, floors, grid),
        height_m=profile.height_m, slope=slope, name=OPERATION, budget_s=BUDGET_S))
    mine = lowered.exploitation
    known = domain & np.isfinite(mine) & np.isfinite(current) & np.isfinite(final)
    with np.errstate(invalid="ignore"):
        size = np.abs(mine - current)
        same = known & (size <= EQUAL_M)
        anchored = (known & ~same & (np.abs(current - final) <= EQUAL_M)
                    & (mine > current) & (mine - final < profile.height_m + EQUAL_M))
        passed = previous - current
        chosen = domain & np.isfinite(passed) & (passed > 0.0)
    inside, outside = known & target, known & ~target
    loose = inside & ~same & ~anchored
    moved = outside & ~same
    return ToFinalResult(
        int(inside.sum()), int((inside & same).sum()), int((inside & anchored).sum()),
        int(loose.sum()), float(size[loose].max()) if loose.any() else 0.0,
        int(moved.sum()), float(size[moved].max()) if moved.any() else 0.0,
        lowered.volume_m3, math.fsum(passed[chosen].tolist()) * area,
        len(warned.zones), warned.area_ha, warned.volume_m3, int(warned.warned.sum()),
        int((warned.warned & zones).sum()))


class _Masks:
    """Las máscaras de la cadena: la rejilla, el corte admitido en el recinto de la ficha, nada de
    relleno ni zonas a sostener (la ficha no las tiene: si el proyecto de referencia sostenía
    algo, va en las semillas)."""

    def __init__(self, grid: object, cut: np.ndarray) -> None:
        self.grid = grid
        self._cut = cut
        self.zones: dict[str, object] = {}
        self.ctypes: Mapping[str, str] = MappingProxyType({})
        self.classes = np.zeros(cut.shape, dtype=np.uint16)
        self.version_uid = "V00"

    def zone(self, code: str) -> object:
        return self.zones[code]

    def cut_allowed(self) -> np.ndarray:
        return self._cut.copy()

    def fill_allowed(self) -> np.ndarray:
        return np.zeros(self._cut.shape, dtype=bool)

    def fill_strip(self) -> np.ndarray:
        return np.zeros(self._cut.shape, dtype=bool)


def quarry_job(sheet: Sheet, grid: object, start: np.ndarray, area: np.ndarray,
               values: Callable[[str], np.ndarray], domain_set: object,
               floors: object | None, fill: np.ndarray | None,
               zones: np.ndarray | None) -> object:
    """(d) El ``quarry.QuarryJob`` de la cadena con lo de la ficha (véase el módulo)."""
    parameters: dict[str, object] = {}
    sides: dict[object, object] = {}
    seeds: dict[object, object] = {}
    for surface in (Surface.FINAL, Surface.EXPLOITATION):
        spec = sheet.side(surface)
        profile = spec.profile
        for param in params.BenchParam:
            parameters[params.bench_key(profile.code, param)] = getattr(profile, param.value)
        source = None
        if spec.seeds is not None:
            source = model.SeedSource("grid", grid=f"semillas de {SIDE_LABELS[surface]}")
            seeds[surface] = seeds_mod.collect_seeds(values(spec.seeds), None, domain_set, grid)
        sides[surface] = model.QuarrySide(base_profile=profile.code, seeds=source,
                                          anchor=spec.anchor)
    mode = model.ToFinalMode.NONE if zones is None else model.ToFinalMode.LAYER
    request = model.QuarryRequest(
        name=OPERATION, start="partida", final=sides[Surface.FINAL],
        exploitation=sides[Surface.EXPLOITATION], order=sheet.order,
        fill_zones=None if fill is None else "relleno de la ficha", to_final=mode,
        to_final_layer=None if zones is None else "zonas de la ficha")
    threshold = (_default(params.UNSPLIT_THRESHOLD) if sheet.to_final is None
                 else sheet.to_final.threshold_m)
    min_area = (_default(params.UNSPLIT_MIN_AREA) if sheet.to_final is None
                else sheet.to_final.min_area_ha)
    return quarry.QuarryJob(
        request=request, start=start, masks=_Masks(grid, area), domain=domain_set,
        values=parameters, ring_cells=sheet.ring_cells, min_thickness_m=MIN_THICKNESS_M,
        face_tolerance_deg=_default(params.TOLERANCE_FACE),
        warning_ratio=_default(params.WARNING_RATIO), seeds=seeds, floors=floors,
        fill_zones=fill, unsplit_threshold_m=threshold, unsplit_min_area_ha=min_area,
        to_final_zones=zones)


def _fit(mine: np.ndarray, reference: np.ndarray, domain: np.ndarray) -> SurfaceFit:
    known = domain & np.isfinite(reference)
    both = known & np.isfinite(mine)
    delta = np.where(both, mine - reference, 0.0)
    size = np.abs(delta)
    differing = int((both & (size > EQUAL_M)).sum()) + int((known & ~both).sum())
    return SurfaceFit(int(known.sum()), differing, float(size[both].max()) if both.any() else 0.0,
                      float(delta[both].mean()) if both.any() else 0.0)


def _chain(sheet: Sheet, grid: object, start: np.ndarray, area: np.ndarray,
           values: Callable[[str], np.ndarray], domain_set: object, floors: object | None,
           fill: np.ndarray | None, zones: np.ndarray | None, reference: Mapping[str, object],
           factor: float) -> ChainResult:
    """(d) La cadena: las dos superficies de Geoblender con lo de la ficha frente a las de la
    referencia (``reference``: ``final`` y ``exploitation``)."""
    job = quarry_job(sheet, grid, start, area, values, domain_set, floors, fill, zones)
    try:
        outcome = _last(quarry.quarry_steps(job, budget_s=BUDGET_S))
    except messages.DesignError as error:
        return ChainResult(str(error), None, None, 0, ())
    domain = domain_set.mask
    previous = None if outcome.to_final is None else outcome.ordered.exploitation
    figures = _class_figures(sheet, outcome.classes, outcome.final_grid,
                             outcome.exploitation_grid, start, domain, fill, factor,
                             grid.cell_area, previous)
    return ChainResult(None, _fit(outcome.final_grid, reference["final"], domain),
                       _fit(outcome.exploitation_grid, reference["exploitation"], domain),
                       outcome.adjusted, figures)


def compare_values(sheet: Sheet, grid: object, start: np.ndarray,
                   values: Callable[[str], np.ndarray]) -> Comparison:
    """La comparación sobre las superficies ya leídas (``values``: nombre sin extensión → su
    rejilla; ``start``, la de partida en la misma rejilla)."""
    problems: list[str] = []
    area = _mask(values(sheet.area))
    domain = area & np.isfinite(start)
    if not domain.any():
        problems.append("el recinto no tiene ninguna celda con terreno")
    final = values(sheet.final.reference)
    exploitation = values(sheet.exploitation.reference)
    for what, grid_values in (("la superficie final", final),
                              ("la superficie de explotación", exploitation)):
        if not np.isfinite(grid_values[domain]).any():
            problems.append(f"{what} de la referencia no tiene ninguna celda con dato en el "
                            "recinto")
    floors = None
    if sheet.floors is not None:
        floors = _floor_map(values(sheet.floors), grid)
        if not sum(floors.cells):
            problems.append("los fondos no tienen ninguna cota")
    fill = None if sheet.fill is None else _mask(values(sheet.fill))
    zones = None if sheet.to_final is None else _mask(values(sheet.to_final.zones))
    if zones is not None and not (zones & domain).any():
        problems.append("las zonas de «explotación hasta la final» no tienen ninguna celda en el "
                        "recinto")
    if problems:
        raise BankShapeError(_shape_message(problems))
    labels = np.zeros(grid.shape, dtype=np.int16)
    domain_set = seeds_mod.domain_of(domain, labels, (), grid.cell_area)
    cell_area = grid.cell_area
    factor = cell_area / nominal_area(grid)
    orders = []
    current, ordered = _order(sheet, "la explotación vigente", final, exploitation, start,
                              domain, cell_area)
    orders.append(current)
    previous = None
    if sheet.exploitation.previous is not None:
        before, earlier = _order(sheet, "la explotación previa", final,
                                 values(sheet.exploitation.previous), start, domain, cell_area)
        orders.append(before)
        previous = earlier.exploitation
    classes = _last(quarry.classify_steps(ordered.final, ordered.exploitation, start, domain_set,
                                          grid, MIN_THICKNESS_M, fill_zones=fill,
                                          budget_s=BUDGET_S))
    figures = _class_figures(sheet, classes, ordered.final, ordered.exploitation, start, domain,
                             fill, factor, cell_area, previous)
    to_final = None
    if zones is not None and previous is not None:
        to_final = _to_final(sheet, ordered.final, previous, ordered.exploitation, start,
                             domain_set, grid, floors, zones)
    chain = _chain(sheet, grid, start, area, values, domain_set, floors, fill, zones,
                   {"final": final, "exploitation": exploitation}, factor)
    return Comparison(int(domain.sum()), cell_area, nominal_area(grid), tuple(orders), figures,
                      to_final, chain)


# --- Salida en español ----------------------------------------------------------------------


def _where(part: str) -> str:
    return f"{NAME} (banco del proyecto de referencia, versión vigente, {part})"


def _whole(count: int) -> str:
    return shape.number(float(count), 0)


def order_line(result: Comparison, item: OrderResult) -> str:
    relative = ("—" if math.isinf(item.relative)
                else shape.percent(item.relative, 4).lstrip("+"))
    return (
        f"{_where('orden')}: {item.label} con la final, {_whole(item.cells)} celdas del recinto "
        f"con dato (de {_whole(result.cells)}; sin dato en alguna {_whole(item.nodata)}); iguales "
        f"tras la regla de orden (≤ {shape.number(EQUAL_M * 1000.0, 0)} mm) {_whole(item.equal)}; "
        f"la final por encima de la explotación {_whole(item.final_above)}; por encima del "
        f"terreno {_whole(item.above_terrain)}; la regla mueve {shape.number(item.changed_m3)} m³ "
        f"({relative} de la excavación de la explotación, {shape.number(item.moved_m3)} m³; "
        f"tolerancia {shape.percent(VOLUME_TOL, 2).lstrip('+')})"
    )


def _figure_text(item: FigureResult) -> str:
    relative = "—" if math.isinf(item.relative) else shape.percent(item.relative, 4)
    return (f"{item.label} {shape.number(item.found_m3)} m³ frente a "
            f"{shape.number(item.reference_m3)} m³ ({relative}; hasta el espesor mínimo "
            f"{shape.number(item.thin_m3)} m³): {item.verdict}")


def figures_line(result: Comparison) -> str:
    parts = "; ".join(_figure_text(item) for item in result.figures) or "la ficha no da cifras"
    return (f"{_where('cifras')}: la referencia corregida ×"
            f"{shape.number(result.cell_area_m2 / result.nominal_m2, 9)} (celda de "
            f"{shape.number(result.cell_area_m2, 10)} m² frente a "
            f"{shape.number(result.nominal_m2, 4)} m²); {parts}")


def to_final_line(item: ToFinalResult) -> str:
    return (
        f"{_where('explotación hasta la final')}: en las zonas de la referencia, "
        f"{_whole(item.zone_cells)} celdas; iguales {_whole(item.equal)}; explicadas por la cota "
        f"de ancla {_whole(item.by_anchor)}; sin explicar {_whole(item.unexplained)} (máxima "
        f"{shape.number(item.unexplained_max_m, 4)} m); fuera de ellas, en la transición, "
        f"difieren {_whole(item.transition_cells)} celdas (máxima "
        f"{shape.number(item.transition_max_m, 4)} m); pasan a la explotación "
        f"{shape.number(item.found_m3)} m³ con Geoblender y {shape.number(item.reference_m3)} m³ "
        f"en la referencia; el aviso de Geoblender sobre la previa, {item.warned_zones} zonas, "
        f"{shape.number(item.warned_ha, 2)} ha y {shape.number(item.warned_m3)} m³, "
        f"{_whole(item.warned_cells)} celdas, {_whole(item.warned_in_reference)} de ellas en las "
        "zonas de la referencia"
    )


def _fit_text(label: str, fit: SurfaceFit) -> str:
    return (f"{label}: {_whole(fit.differing)} de {_whole(fit.cells)} celdas difieren "
            f"(> {shape.number(EQUAL_M * 1000.0, 0)} mm), máxima {shape.number(fit.max_abs_m, 4)} "
            f"m, media {shape.number(fit.mean_m, 4)} m")


def chain_line(item: ChainResult) -> str:
    if item.error is not None:
        return f"{_where('la cadena')}: Geoblender no la puede calcular: {item.error}"
    assert item.final is not None and item.exploitation is not None
    figures = "; ".join(_figure_text(figure) for figure in item.figures)
    return (f"{_where('la cadena')}: {_fit_text('la final', item.final)}; "
            f"{_fit_text('la explotación', item.exploitation)}; la regla de orden cambió "
            f"{_whole(item.adjusted)} celdas" + (f"; {figures}" if figures else ""))


def lines(result: Comparison) -> list[str]:
    """Las líneas de la comparación, en su orden: (a), (b), (c) y (d)."""
    found = [order_line(result, item) for item in result.order]
    found.append(figures_line(result))
    if result.to_final is not None:
        found.append(to_final_line(result.to_final))
    found.append(chain_line(result.chain))
    return found


class ReferenceQuarryTest(unittest.TestCase):
    """CE-014-09 con el banco del proyecto de referencia (RF-014-13 a RF-014-18)."""

    result: Comparison | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = None
        result = compare(shape.bank_folder())
        for line in lines(result):
            shape.report(line)
        cls.result = result

    def test_the_reference_keeps_the_order_rule(self) -> None:
        """CE-014-09, RF-014-13, RF-014-14: la regla de orden de la ficha y ``≤ z`` no mueven las
        superficies de la referencia (la explotación vigente y la previa, cada una con la final)
        más de 10⁻⁴ de la excavación de la explotación."""
        assert self.result is not None
        for item in self.result.order:
            with self.subTest(pair=item.label):
                self.assertLessEqual(
                    item.relative, VOLUME_TOL,
                    f"{item.label}: la regla de orden mueve {shape.number(item.changed_m3)} m³ "
                    f"(la final por encima de la explotación en {_whole(item.final_above)} "
                    f"celdas; por encima del terreno en {_whole(item.above_terrain)})")

    def test_the_figures_of_the_reference_are_reproduced(self) -> None:
        """CE-014-09, RF-014-15, RF-014-16, RF-014-18: la excavación de la explotación, el
        desdoblado, el relleno de restauración y lo que pasa a la explotación con «explotación
        hasta la final», medidos por Geoblender en las superficies de la referencia, son los de la
        ficha (corregidos por el área de celda) a ≤ 10⁻⁴ o los explica el espesor mínimo."""
        assert self.result is not None
        if not self.result.figures:
            self.skipTest("la ficha no da ninguna cifra de la referencia")
        for item in self.result.figures:
            with self.subTest(figure=item.label):
                self.assertNotEqual(item.verdict, UNEXPLAINED, _figure_text(item))

    def test_to_final_in_the_reference_zones_is_explained(self) -> None:
        """CE-014-09, RF-014-17, RF-014-18: en las zonas en que la referencia bajó la explotación
        hasta la final, la de Geoblender desde la misma previa, con el perfil y el ancla de la
        ficha, es la suya (≤ 1 mm) o se queda en la cota de ancla inmediatamente por encima de una
        final a la que la referencia llegó; ninguna celda queda sin explicar."""
        assert self.result is not None
        item = self.result.to_final
        if item is None:
            self.skipTest("la ficha no dice que la referencia bajara la explotación hasta la "
                          "final («hasta_la_final»)")
        self.assertGreater(item.zone_cells, 0)
        self.assertEqual(item.unexplained, 0,
                         f"{_whole(item.unexplained)} celdas de las zonas sin explicar, "
                         f"máxima {shape.number(item.unexplained_max_m, 4)} m")


if __name__ == "__main__":
    unittest.main()
