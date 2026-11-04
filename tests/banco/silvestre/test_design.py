# SPDX-License-Identifier: GPL-3.0-or-later
"""Banco del proyecto de referencia: las envolventes y los escalonados de su versión vigente
frente a los suyos (spec 013, T33; CE-013-10; HU-013-6; RF-013-11, RF-013-22, RF-013-25; plan 013
§7.1, «Banco privado»; constitución, principio 2).

CE-013-10: con el banco privado del proyecto de referencia, las envolventes y los escalonados de
una de sus versiones, con los mismos perfiles y semillas, difieren de los suyos dentro de la
tolerancia que fija esta comparación y con cada diferencia explicada (la métrica, el factor de
malla, la regularización). Cada diferencia la explica la persona que lo ejecuta (hito H3).

Lo ejecuta el arnés de los bancos de la 001 (``tools/bench_silvestre.py``) solo con
``tools/check.py --banco`` y con ``GEOBLENDER_SILVESTRE_DIR`` apuntando a la carpeta del banco;
sin la variable (o si no es una carpeta), se omite con la orden que la activa. **Solo lectura**:
los ficheros del banco solo se abren para leer, y el arnés comprueba que la carpeta queda igual
(RNF-001-05). Lo que se escribe (el MDT llevado a la rejilla de las referencias) va a una carpeta
temporal de ``%TEMP%`` que se borra. Ni la ruta ni el nombre de ningún fichero, ni los nombres de
la ficha, se escriben aquí ni en la salida: solo «envolvente i de n», «escalonado j de m» y las
cifras de la comparación.

**La forma del banco** (sin nombres de ficheros del banco: patrones y los nombres de la ficha;
todo se busca en la versión vigente y, si no está allí, en el resto de la carpeta, sin seguir
enlaces, en un orden fijo; las copias iguales, mismo sha256, cuentan como una). Es la de las
salidas por versión del proyecto de referencia que describe su análisis
(``Documentacion/analisis_proyecto_silvestre``, 01 §2.5 y §4, y 03 §3.1 y §3.2); si el banco real
no la tiene, la comparación dice **todo** lo que no encuentra, se ve en el H3 y se adapta esta
comparación (nunca el banco):

1. **La versión vigente** y **la superficie de partida**: como en ``test_res_volumes`` (la
   carpeta ``V<nn>_<rasgo>_VIGENTE`` de número mayor; el GeoTIFF con «MDT», «DEM», «DTM» o
   «terreno» en el nombre, que se lleva a la rejilla de las referencias con el remuestreo de
   Geoblender si tiene otra).
2. **La ficha del diseño**: un JSON (UTF-8) con «ficha_diseno» en el nombre. Los perfiles de banco,
   las pendientes y los factores de malla del proyecto de referencia no están en sus rásteres sino
   en sus programas, y Geoblender no tiene ninguna cifra por defecto (D-7): los declara esta
   ficha, que la persona del H3 prepara con ellos junto al banco (a una copia, nunca a él) o
   adapta aquí. Cada fichero que nombra es un GeoTIFF o un ``.npy`` de números (sin ``pickle``)
   con la **misma rejilla y CRS** que la primera referencia, que es un GeoTIFF y da la rejilla;
   se nombra sin extensión. Sin dato (``NaN``) donde no hay valor::

       {"envolventes": [{"nombre": "...", "sentido": "baja" | "sube",
                         "semillas": "<cotas de las semillas>", "referencia": "<su envolvente>",
                         "pendiente_deg": 40.3,    // o "perfil": {altura_m, cara_deg, berma_m}
                         "factor_malla": 0.97}],  // opcional, 1 por defecto (D-7)
        "escalonados": [{"nombre": "...", "sentido": "corte" | "relleno",
                         "envolvente": "<nombre de una envolvente>",
                         "referencia": "<su superficie>",
                         "perfil": {"altura_m": 10, "cara_deg": 60, "berma_m": 6, "ancla_m": 125},
                         "factor_malla": 0.98,   // opcional, el del recorte final
                         "sector": {"mascara": "<celdas del sector: distinto de 0>",
                                    "talud_deg": 10.6,       // talud general máximo (RF-013-25)
                                    "berma_m": 19.6}}]}     // opcional: la de la referencia

**Lo calculado** (con ``design.pipeline``, que es el cálculo de «Calcular» y de reproducir una
revisión; el dominio de trabajo, las celdas con dato de la referencia; las máscaras de la 012, sin
vedar nada: aquí se compara la geometría): por envolvente, el *chamfer* 5×5 (la métrica de la
referencia, ``cono5``) y también la euclídea exacta, solo para decir cuánto se aparta de la
referencia; por escalonado, dos cálculos: **sobre la envolvente de la referencia** y con la berma
del literal del sector (solo la fórmula de RF-013-22 y el recorte, con las mismas entradas) y **la
cadena**, sobre la envolvente de Geoblender y con la berma de la regla (RF-013-25).

**La comparación** y qué justifica cada diferencia (las cifras se imprimen en líneas
``CE-013-10: …``, para anotarlas en la verificación del H3):

(a) *Envolventes* (RF-013-11, RF-013-12). Celda a celda, ``Δ = Geoblender − referencia``, en estas
    clases, en este orden: **iguales**, ``|Δ| ≤ 1 mm`` (``EQUAL_M``: más de diez veces la
    cuantización de float32 a 1.000 m de cota, 6·10⁻⁵ m); **explicadas por la métrica**,
    ``|Δ| ≤ 1,4 %`` de la caída desde la semilla más alta (en la ascendente, más baja), que es lo
    que el *chamfer* 5×5 puede apartarse de la euclídea (RF-013-12, D-8: una referencia hecha con
    otra métrica, o con otra escala, queda ahí); **explicadas por la convergencia**, más allá de lo
    anterior pero del lado en que el barrido de Geoblender, hasta el punto fijo, es más
    conservador que el de dos pasadas de ``cono5`` (en la descendente Geoblender queda por encima
    de la referencia; en la ascendente, por debajo); y **sin explicar**, el resto: la envolvente de
    Geoblender del lado contrario al de la convergencia, o ausente donde la referencia tiene dato.
    La comparación falla si queda alguna sin explicar. El factor de malla de la ficha entra en la
    pendiente (``tan · factor``, RF-013-11): si el de la referencia era otro, aparece aquí.
(b) *Escalonados sobre la envolvente de la referencia* (RF-013-22, RF-013-27). Con la misma
    envolvente, el mismo perfil y la misma berma, la fórmula ``z₀ + n·h + mín(f·a·tan α, h)`` es la
    misma y solo puede diferir el recorte final: se comparan celdas (``> 1 mm``, máxima) y el
    desmonte y el terraplén frente al terreno de partida, que no difieren más de ``10⁻⁴`` del
    movimiento de tierras de la referencia (``VOLUME_TOL``: D-14 d de la 011, la tolerancia de las
    cifras de volumen del banco); y ninguna celda queda por debajo de la envolvente en corte (ni
    por encima en relleno): RF-013-22 y RF-013-27 sin mirar la referencia.
(c) *La berma del sector* (RF-013-25, D-11). ``B_s = máx(B, h/tan β − h/tan α)`` frente al literal
    de la referencia: no puede diferir más de **medio decimal del literal** (19,6 m admite
    ±0,05 m; la regla da 19,5765 m): es el redondeo del número que se escribió en el programa de la
    referencia.
(d) *La cadena* (RF-013-11 con RF-013-22 y RF-013-25). Se informa, sin fallar: lo que sale de las
    envolventes (a), y de la berma de la regla frente a la del literal (c), más el recorte y la
    regularización entre sectores (RF-013-26), que la persona del H3 explica con (a), (b) y (c).
"""

from __future__ import annotations

import json
import math
import re
import tempfile
import types
import unittest
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

import numpy as np

from tests.support import bank_folder as shape
from tests.support.bank_folder import ENV, BankShapeError  # ENV: lo lee test_design_bank
from tests.support.package import import_geoblender

geotiff = import_geoblender("gis.geotiff")
gis_messages = import_geoblender("gis.messages")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
benching = import_geoblender("design.benching")
envelopes = import_geoblender("design.envelopes")
pipeline = import_geoblender("design.pipeline")
report = import_geoblender("design.report")
seeds_mod = import_geoblender("design.seeds")

NAME = "CE-013-10"  # el nombre de las líneas de la comparación
EQUAL_M = 1e-3
"""Lo que se cuenta como igual (m): más de diez veces la cuantización de float32 a 1.000 m."""
METRIC_RATIO = 0.014
"""Lo que el *chamfer* 5×5 se aparta de la euclídea, relativo a la caída (RF-013-12, D-8)."""
VOLUME_TOL = 1e-4
"""Lo que pueden diferir el desmonte y el terraplén, relativo al movimiento de la referencia
(D-14 d de la 011)."""
MIN_THICKNESS_M = 0.02
"""El espesor mínimo de los volúmenes y del informe (D-6 de la 012)."""
BUDGET_S = 60.0
"""Lo que dura un paso como mucho: todo de una vez, no hay interfaz que atender."""
STRICT_M = 1e-9
"""La tolerancia de RF-013-22 y RF-013-27 sobre su propia envolvente (m)."""
OPERATION = "Comparación del banco"
SHEET_PATTERN = re.compile(r"(?i)ficha[_ ]?dise[nñ]o")
JSON_SUFFIX = ".json"
RASTER_SUFFIXES = (*shape.TIFF_SUFFIXES, shape.NPY_SUFFIX)
DIRECTIONS = {"baja": "down", "sube": "up"}
SENSES = {"corte": "cut", "relleno": "fill"}
SECTOR = "s"  # el código del sector único de la comparación
BASE = "base"
BASE_SECTOR = "sector"


# --- La ficha -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnvelopeSpec:
    """Una envolvente de la ficha: su ``name``, la ``direction`` (``down`` o ``up``), los nombres
    de los ficheros de las ``seeds`` y de la ``reference``, la pendiente en grados y el factor de
    malla."""

    name: str
    direction: str
    seeds: str
    reference: str
    slope_deg: float
    mesh: float


@dataclass(frozen=True, slots=True)
class SectorSpec:
    """El sector de un escalonado: el fichero de su ``mask``, su talud general máximo ``slope_deg``
    (RF-013-25) y la berma del literal de la referencia, si la ficha la da."""

    mask: str
    slope_deg: float
    berm: Decimal | None


@dataclass(frozen=True, slots=True)
class StepSpec:
    """Un escalonado de la ficha: su ``name``, el ``sense`` (``cut`` o ``fill``), el nombre de su
    ``envelope``, el fichero de la ``reference``, el ``profile`` (con su factor de malla) y el
    ``sector``, si lo tiene."""

    name: str
    sense: str
    envelope: str
    reference: str
    profile: object
    sector: SectorSpec | None


@dataclass(frozen=True, slots=True)
class Sheet:
    """La ficha del diseño: sus envolventes y sus escalonados."""

    envelopes: tuple[EnvelopeSpec, ...]
    steps: tuple[StepSpec, ...]


def _show(value: object) -> str:
    return str(value) if isinstance(value, Decimal) else repr(value)


def _number(item: dict[str, object], key: str, where: str, problems: list[str], *,
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


def _text(item: dict[str, object], key: str, where: str, problems: list[str]) -> str | None:
    value = item.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    problems.append(f"{where}: falta «{key}» (un texto)" if key not in item
                    else f"{where}: «{key}» debe ser un texto no vacío, no {_show(value)}")
    return None


def _profile(item: dict[str, object], where: str, problems: list[str], *, anchor: bool,
             mesh: float) -> object | None:
    """El perfil de banco de ``item["perfil"]`` (``altura_m``, ``cara_deg``, ``berma_m`` y, si
    ``anchor``, ``ancla_m``), comprobado por el dominio; el factor de malla, ``mesh``."""
    raw = item.get("perfil")
    keys = ("altura_m", "cara_deg", "berma_m", *(("ancla_m",) if anchor else ()))
    if not isinstance(raw, dict):
        problems.append(f"{where}: falta «perfil» ({', '.join(keys)})")
        return None
    numbers = [_number(raw, key, f"{where}, perfil", problems) for key in keys]
    if any(number is None for number in numbers):
        return None
    height, face, berm, *rest = (float(number) for number in numbers if number is not None)
    try:
        return model.BenchProfile(BASE, BASE, height, face, berm, rest[0] if rest else 0.0, mesh)
    except (messages.DesignError, ValueError, TypeError) as error:
        problems.append(f"{where}: el perfil no es válido ({error})")
        return None


def _mesh(item: dict[str, object], where: str, problems: list[str]) -> float:
    found = _number(item, "factor_malla", where, problems, default=Decimal(1))
    return 1.0 if found is None else float(found)


def _envelope_spec(item: object, where: str, problems: list[str]) -> EnvelopeSpec | None:
    if not isinstance(item, dict):
        problems.append(f"{where}: debe ser un objeto con sus campos")
        return None
    before = len(problems)
    name = _text(item, "nombre", where, problems)
    seeds = _text(item, "semillas", where, problems)
    reference = _text(item, "referencia", where, problems)
    direction = DIRECTIONS.get(str(item.get("sentido")))
    if direction is None:
        problems.append(f"{where}: «sentido» es baja o sube, no {_show(item.get('sentido'))}")
    mesh = _mesh(item, where, problems)
    slope: float | None = None
    if "pendiente_deg" in item and "perfil" in item:
        problems.append(f"{where}: «pendiente_deg» y «perfil» a la vez: solo uno")
    elif "pendiente_deg" in item:
        found = _number(item, "pendiente_deg", where, problems)
        slope = None if found is None else float(found)
    elif "perfil" in item:
        profile = _profile(item, where, problems, anchor=False, mesh=mesh)
        slope = None if profile is None else profile.general_deg
    else:
        problems.append(f"{where}: falta «pendiente_deg» o «perfil» (su talud general)")
    if len(problems) > before or slope is None or direction is None:
        return None
    request = model.EnvelopeRequest(OPERATION, direction, model.SeedSource("grid", grid=seeds),
                                    slope_deg=slope, mesh_factor=mesh)
    try:
        envelopes.check_request(request)
    except messages.DesignError as error:
        problems.append(f"{where}: {error}")
        return None
    assert name is not None and seeds is not None and reference is not None  # sin problemas
    return EnvelopeSpec(name, direction, seeds, reference, slope, mesh)


def _sector_spec(item: object, profile: object, where: str, problems: list[str]
                 ) -> SectorSpec | None:
    if not isinstance(item, dict):
        problems.append(f"{where}, sector: debe ser un objeto con «mascara» y «talud_deg»")
        return None
    before = len(problems)
    mask = _text(item, "mascara", f"{where}, sector", problems)
    slope = _number(item, "talud_deg", f"{where}, sector", problems)
    berm = _number(item, "berma_m", f"{where}, sector", problems, default=Decimal(-1))
    if len(problems) > before or mask is None or slope is None or berm is None:
        return None
    try:
        params.check_sector_slope(SECTOR, float(slope))
        if berm >= 0:
            replace(profile, berm_m=float(berm))
    except (messages.DesignError, ValueError, TypeError) as error:
        problems.append(f"{where}, sector: {error}")
        return None
    return SectorSpec(mask, float(slope), berm if berm >= 0 else None)


def _step_spec(item: object, where: str, known: Sequence[str], problems: list[str]
               ) -> StepSpec | None:
    if not isinstance(item, dict):
        problems.append(f"{where}: debe ser un objeto con sus campos")
        return None
    before = len(problems)
    name = _text(item, "nombre", where, problems)
    reference = _text(item, "referencia", where, problems)
    link = _text(item, "envolvente", where, problems)
    sense = SENSES.get(str(item.get("sentido")))
    if sense is None:
        problems.append(f"{where}: «sentido» es corte o relleno, no {_show(item.get('sentido'))}")
    if link is not None and link not in known:
        problems.append(f"{where}: la envolvente «{link}» no existe en la ficha")
    profile = _profile(item, where, problems, anchor=True, mesh=_mesh(item, where, problems))
    sector = None
    if profile is not None and "sector" in item:
        sector = _sector_spec(item["sector"], profile, where, problems)
    if (len(problems) > before or name is None or reference is None or link is None
            or sense is None or profile is None):
        return None
    return StepSpec(name, sense, link, reference, profile, sector)


def _parse_sheet(data: object, problems: list[str]) -> Sheet | None:
    if not isinstance(data, dict):
        problems.append("la ficha del diseño debe ser un objeto con «envolventes» y «escalonados»")
        return None
    raw_envelopes, raw_steps = data.get("envolventes"), data.get("escalonados")
    before = len(problems)
    if not isinstance(raw_envelopes, list) or not raw_envelopes:
        problems.append("la ficha del diseño: «envolventes» debe ser una lista con alguna")
    if not isinstance(raw_steps, list) or not raw_steps:
        problems.append("la ficha del diseño: «escalonados» debe ser una lista con alguno")
    if len(problems) > before:
        return None
    assert isinstance(raw_envelopes, list) and isinstance(raw_steps, list)
    found = [_envelope_spec(item, f"envolvente {number} de {len(raw_envelopes)}", problems)
             for number, item in enumerate(raw_envelopes, start=1)]
    names = [item.name for item in found if item is not None]
    if len(set(names)) != len(names):
        problems.append("la ficha del diseño: dos envolventes con el mismo nombre")
    steps = [_step_spec(item, f"escalonado {number} de {len(raw_steps)}", names, problems)
             for number, item in enumerate(raw_steps, start=1)]
    if len(problems) > before or None in found or None in steps:
        return None
    return Sheet(tuple(item for item in found if item is not None),
                 tuple(item for item in steps if item is not None))


def _read_sheet(version: list[Path], everything: list[Path], problems: list[str]) -> Sheet | None:
    def pick(paths: list[Path]) -> list[Path]:
        return [path for path in paths
                if path.suffix.lower() == JSON_SUFFIX and SHEET_PATTERN.search(path.stem)]

    found = shape.distinct(pick(version) or pick(everything))
    if len(found) != 1:
        problems.append("la ficha del diseño (un JSON con «ficha_diseno» en el nombre, véase la "
                        f"forma del banco): se esperaba una y hay {_count(found)}")
        return None
    try:
        data = json.loads(found[0].read_text(encoding="utf-8-sig"), parse_float=Decimal,
                          parse_int=Decimal)
    except (OSError, ValueError) as error:
        where = f" (línea {error.lineno})" if isinstance(error, json.JSONDecodeError) else ""
        problems.append(f"la ficha del diseño no es un JSON legible en UTF-8{where}")
        return None
    return _parse_sheet(data, problems)


# --- Buscar en el banco ---------------------------------------------------------------------


def _count(found: Sequence[object]) -> str:
    return "ninguna" if not found else f"{len(found)} distintas"


def _key(stem: str) -> str:
    return stem.casefold()


def _wanted(sheet: Sheet) -> list[tuple[str, str]]:
    """Los ficheros que nombra la ficha, en un orden fijo (las referencias primero): su
    descripción (con «i de n») y su nombre sin extensión."""
    wanted: list[tuple[str, str]] = []
    count = len(sheet.envelopes)
    for number, item in enumerate(sheet.envelopes, start=1):
        wanted.append((f"la referencia de la envolvente {number} de {count}", item.reference))
    total = len(sheet.steps)
    for number, step in enumerate(sheet.steps, start=1):
        wanted.append((f"la referencia del escalonado {number} de {total}", step.reference))
    for number, item in enumerate(sheet.envelopes, start=1):
        wanted.append((f"las semillas de la envolvente {number} de {count}", item.seeds))
    for number, step in enumerate(sheet.steps, start=1):
        if step.sector is not None:
            wanted.append((f"la máscara del sector del escalonado {number} de {total}",
                           step.sector.mask))
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
            problems.append(f"{what}: el .npy no tiene la forma de la rejilla de la primera "
                            "referencia ni es de números")
            return None
        return np.asarray(values, dtype=np.float64)
    try:
        source = geotiff.read_geotiff(path)
    except gis_messages.GisError as error:
        problems.append(f"{what}: no se puede leer el GeoTIFF ({error.code})")
        return None
    if source.declared_crs is None or source.declared_crs != crs:
        problems.append(f"{what}: no declara el CRS de la primera referencia")
    elif not source.grid.same_geometry(grid):
        problems.append(f"{what}: tiene otra rejilla que la primera referencia")
    else:
        return source.values
    return None


# --- Lo calculado ---------------------------------------------------------------------------


def _last(steps: object) -> object:
    found = None
    for found in steps:
        pass
    return found.result


def _run_envelope(spec: EnvelopeSpec, seeds: np.ndarray, domain: np.ndarray, grid: object,
                  metric: str) -> np.ndarray:
    """La envolvente de ``spec`` (``metric``: ``chamfer5`` o ``exact``) de las ``seeds`` en el
    ``domain``, con ``design.pipeline``: ``NaN`` fuera del dominio."""
    labels = np.zeros(grid.shape, dtype=np.int16)
    domain_set = seeds_mod.domain_of(domain, labels, (), grid.cell_area)
    seed_set = seeds_mod.collect_seeds(seeds, None, domain_set, grid)
    request = model.EnvelopeRequest(
        OPERATION, spec.direction, model.SeedSource("grid", grid=spec.seeds),
        slope_deg=spec.slope_deg, metric=metric, mesh_factor=spec.mesh)
    job = pipeline.EnvelopeJob(request, seed_set, pipeline.envelope_slope(request, (), labels, {}),
                               None, MIN_THICKNESS_M)
    outcome = _last(pipeline.envelope_compute_steps(job, budget_s=BUDGET_S))
    return outcome.grid


def _default(key: str) -> float:
    return float(next(item for item in params.DEFINITIONS if item.key == key).default)


def _run_design(spec: StepSpec, grid: object, start: np.ndarray, surface: np.ndarray,
                sector: np.ndarray | None, *, literal: bool) -> np.ndarray:
    """El escalonado de ``spec`` sobre la envolvente ``surface`` con ``design.pipeline``, con las
    máscaras sin vedar nada. El sector, si lo hay: con la berma del literal de la referencia
    (``literal``, si la ficha la da) o con su talud general máximo, que da la berma de la regla."""
    base: model.BenchProfile = spec.profile
    profiles = {BASE: base}
    labels = np.zeros(grid.shape, dtype=np.int16)
    sectors: tuple[seeds_mod.SectorRef, ...] = ()
    assigned: dict[str, str] = {}
    imposed: dict[str, float] = {}
    if spec.sector is not None and sector is not None:
        sectors = (seeds_mod.SectorRef(SECTOR, "Sector"),)
        labels[sector] = 1
        assigned = {SECTOR: BASE}
        if literal and spec.sector.berm is not None:
            profiles[BASE_SECTOR] = replace(base, code=BASE_SECTOR, name=BASE_SECTOR,
                                            berm_m=float(spec.sector.berm))
            assigned = {SECTOR: BASE_SECTOR}
        else:
            imposed = {SECTOR: spec.sector.slope_deg}
    everything = np.ones(grid.shape, dtype=bool)
    masks = types.SimpleNamespace(cut_allowed=lambda: everything.copy(),
                                  fill_allowed=lambda: everything.copy(),
                                  fill_strip=lambda: np.zeros(grid.shape, dtype=bool))
    job = pipeline.DesignJob(
        request=model.DesignRequest(OPERATION, spec.envelope, spec.sense, BASE, assigned),
        geometry=grid, start=start, envelope=surface, masks=masks, sectors=sectors, labels=labels,
        imposed=imposed, profiles=profiles, anchors=None, min_thickness_m=MIN_THICKNESS_M,
        face_tolerance_deg=_default(params.TOLERANCE_FACE),
        warning_ratio=_default(params.WARNING_RATIO))
    return _last(pipeline.design_compute_steps(job, budget_s=BUDGET_S)).design


# --- La comparación -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class EnvelopeResult:
    """Una envolvente frente a su referencia (clase de cada celda de la referencia con dato)."""

    label: str
    direction: str
    cells: int
    equal: int
    by_metric: int
    by_convergence: int
    unexplained: int
    max_abs_m: float
    mean_m: float
    exact_max_abs_m: float


@dataclass(frozen=True, slots=True, eq=False)
class Fit:
    """Una superficie escalonada de Geoblender frente a la de la referencia: las celdas que
    difieren (``> EQUAL_M``), la diferencia máxima, el desmonte y el terraplén y su diferencia con
    la referencia, relativa a su movimiento de tierras."""

    differing: int
    max_abs_m: float
    cut_m3: float
    fill_m3: float
    relative_cut: float
    relative_fill: float


@dataclass(frozen=True, slots=True, eq=False)
class BermCheck:
    """La berma del sector: la de la regla, la del literal de la referencia, medio decimal de su
    última cifra (el redondeo) y si la diferencia cabe en él (``None`` sin literal)."""

    rule_m: float
    literal_m: float | None
    half_unit_m: float | None
    within: bool | None


@dataclass(frozen=True, slots=True, eq=False)
class StepResult:
    """Un escalonado frente a su referencia: los volúmenes de la referencia, sobre su envolvente
    (``on_reference``) y la cadena (``chain``), las celdas del lado equivocado de la envolvente y
    la berma del sector."""

    label: str
    sense: str
    cells: int
    reference: object
    on_reference: Fit
    chain: Fit
    below_envelope: int
    berm: BermCheck | None


@dataclass(frozen=True, slots=True, eq=False)
class Comparison:
    """Las cifras de la versión vigente del banco."""

    envelopes: tuple[EnvelopeResult, ...]
    steps: tuple[StepResult, ...]


def _explain(label: str, spec: EnvelopeSpec, seeds: np.ndarray, reference: np.ndarray,
             mine: np.ndarray, exact: np.ndarray) -> EnvelopeResult:
    """Las clases de diferencia de la envolvente ``mine`` frente a ``reference`` (véase el
    módulo, (a))."""
    given = seeds[np.isfinite(seeds)]
    down = spec.direction == "down"
    domain = np.isfinite(reference)
    with np.errstate(invalid="ignore"):
        found = domain & np.isfinite(mine)
        delta = np.where(found, mine - reference, 0.0)
        depth = (given.max() - reference) if down else (reference - given.min())
        drop = np.where(domain, np.maximum(depth, 0.0), 0.0)
        size = np.abs(delta)
        equal = found & (size <= EQUAL_M)
        metric = found & ~equal & (size <= METRIC_RATIO * drop)
        safe = (delta >= 0.0) if down else (delta <= 0.0)
        convergence = found & ~equal & ~metric & safe
        unexplained = (domain & ~found) | (found & ~equal & ~metric & ~safe)
        near = domain & np.isfinite(exact)
        apart = float(np.abs(exact[near] - reference[near]).max()) if near.any() else math.nan
    return EnvelopeResult(
        label, spec.direction, int(domain.sum()), int(equal.sum()), int(metric.sum()),
        int(convergence.sum()), int(unexplained.sum()),
        float(size[found].max()) if found.any() else 0.0,
        float(delta[found].mean()) if found.any() else 0.0, apart)


def _fit(start: np.ndarray, design: np.ndarray, reference: np.ndarray, grid: object,
         true: object) -> Fit:
    """``design`` (en las celdas con dato de la referencia) frente a ``reference``; ``true`` son los
    volúmenes de la referencia."""
    finite = np.isfinite(reference)
    mine = np.where(finite, design, np.nan)
    both = finite & np.isfinite(mine)
    delta = np.abs(mine[both] - reference[both])
    seen = report.volumes(start, mine, grid, MIN_THICKNESS_M)
    moved = true.cut_m3 + true.fill_m3
    return Fit(
        int(np.count_nonzero(delta > EQUAL_M)), float(delta.max()) if delta.size else 0.0,
        seen.cut_m3, seen.fill_m3,
        abs(seen.cut_m3 - true.cut_m3) / moved,
        abs(seen.fill_m3 - true.fill_m3) / moved)


def _berm(spec: StepSpec) -> BermCheck | None:
    if spec.sector is None:
        return None
    rule = benching.sector_berm(spec.profile, spec.sector.slope_deg)
    literal = spec.sector.berm
    if literal is None:
        return BermCheck(rule, None, None, None)
    half = float(Decimal("0.5") * Decimal(10) ** literal.as_tuple().exponent)
    return BermCheck(rule, float(literal), half, abs(rule - float(literal)) <= half)


def compare(folder: Path) -> Comparison:
    """CE-013-10 sobre el banco ``folder`` (véase el módulo)."""
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
    anchor = next((path for path in paths.values()
                   if path.suffix.lower() in shape.TIFF_SUFFIXES), None)
    if sheet is not None and not problems and anchor is None:
        problems.append("ninguno de los ficheros de la ficha es un GeoTIFF: el primero da la "
                        "rejilla y el CRS (los .npy no los tienen)")
    if problems or sheet is None or anchor is None:
        raise BankShapeError(_shape_message(problems))
    try:
        first = geotiff.read_geotiff(anchor)
    except gis_messages.GisError as error:
        raise BankShapeError(_shape_message(
            [f"la primera referencia no se puede leer como GeoTIFF ({error.code})"])) from None
    crs, vertical = shape.declared(first, "la primera referencia de la ficha")
    grid = first.grid
    arrays: dict[str, np.ndarray | None] = {_key(anchor.stem): first.values}
    for what, stem in _wanted(sheet):
        if _key(stem) not in arrays:
            arrays[_key(stem)] = _read(paths[_key(stem)], grid, crs, what, problems)
    if problems:
        raise BankShapeError(_shape_message(problems))

    def values(stem: str) -> np.ndarray:
        found = arrays[_key(stem)]
        assert found is not None  # sin problemas
        return found

    with tempfile.TemporaryDirectory(prefix="gb-banco-013-") as name:
        ready = shape.on_grid(starts[0], grid, crs, vertical, Path(name), "partida",
                              "la superficie de partida")
        start = geotiff.read_geotiff(ready).values
    return _compare_values(sheet, grid, start, values)


def _compare_values(sheet: Sheet, grid: object, start: np.ndarray,
                    values: Callable[[str], np.ndarray]) -> Comparison:
    """La comparación sobre las superficies ya leídas (``values``: nombre sin extensión → su
    rejilla)."""
    problems: list[str] = []
    found: list[EnvelopeResult] = []
    chamfer: dict[str, np.ndarray] = {}
    count = len(sheet.envelopes)
    for number, spec in enumerate(sheet.envelopes, start=1):
        label = f"envolvente {number} de {count}"
        seeds, reference = values(spec.seeds), values(spec.reference)
        if not np.isfinite(seeds).any():
            problems.append(f"las semillas de la {label} no tienen ninguna cota")
        if not np.isfinite(reference).any():
            problems.append(f"la referencia de la {label} no tiene ninguna celda con dato")
        if problems:
            continue
        domain = np.isfinite(reference)
        chamfer[spec.name] = _run_envelope(spec, seeds, domain, grid, "chamfer5")
        exact = _run_envelope(spec, seeds, domain, grid, "exact")
        found.append(_explain(label, spec, seeds, reference, chamfer[spec.name], exact))
    steps: list[StepResult] = []
    total = len(sheet.steps)
    for number, spec in enumerate(sheet.steps, start=1):
        label = f"escalonado {number} de {total}"
        owner = next(item for item in sheet.envelopes if item.name == spec.envelope)
        reference = values(spec.reference)
        surface = values(owner.reference)
        sector = None
        if spec.sector is not None:
            marks = values(spec.sector.mask)
            sector = np.isfinite(marks) & (marks != 0.0)  # las celdas con dato distinto de 0
        truth = report.volumes(start, reference, grid, MIN_THICKNESS_M)
        if truth.cut_m3 + truth.fill_m3 <= 0.0:
            problems.append(f"la referencia del {label} no mueve tierras frente a la superficie "
                            "de partida")
        if problems:
            continue
        mine = _run_design(spec, grid, start, surface, sector, literal=True)
        chain = _run_design(spec, grid, start, chamfer[owner.name], sector, literal=False)
        cut = spec.sense == "cut"
        with np.errstate(invalid="ignore"):
            limit = np.minimum(surface, start) if cut else np.maximum(surface, start)
            wrong = (mine < limit - STRICT_M) if cut else (mine > limit + STRICT_M)
            wrong &= np.isfinite(surface) & np.isfinite(start)
        steps.append(StepResult(
            label, spec.sense, int(np.isfinite(reference).sum()), truth,
            _fit(start, mine, reference, grid, truth), _fit(start, chain, reference, grid, truth),
            int(wrong.sum()), _berm(spec)))
    if problems:
        raise BankShapeError(_shape_message(problems))
    return Comparison(tuple(found), tuple(steps))


def _shape_message(problems: Sequence[str]) -> str:
    return ("el banco no tiene la forma que espera la comparación (véase el docstring de la "
            "comparación); no se encuentra:\n  - " + "\n  - ".join(problems))


# --- Salida en español ----------------------------------------------------------------------


def _where() -> str:
    return f"{NAME} (banco del proyecto de referencia, versión vigente"


def _whole(count: int) -> str:
    return shape.number(float(count), 0)


def envelope_line(item: EnvelopeResult) -> str:
    way = "descendente" if item.direction == "down" else "ascendente"
    seed = "alta" if item.direction == "down" else "baja"
    return (
        f"{_where()}, {item.label}, {way}): {_whole(item.cells)} celdas con dato en la "
        f"referencia; iguales (≤ {shape.number(EQUAL_M * 1000.0, 0)} mm) {_whole(item.equal)}; "
        f"explicadas por la métrica (≤ {shape.number(METRIC_RATIO * 100.0, 1)} % de la caída "
        f"desde la semilla más {seed}) {_whole(item.by_metric)}; explicadas por la convergencia "
        f"{_whole(item.by_convergence)}; sin explicar {_whole(item.unexplained)}; diferencia "
        f"máxima {shape.number(item.max_abs_m, 4)} m, media {shape.number(item.mean_m, 4)} m; la "
        f"euclídea exacta se aparta de la referencia como mucho "
        f"{shape.number(item.exact_max_abs_m, 4)} m"
    )


def _volumes(fit: Fit, true: object) -> str:
    moved = true.cut_m3 + true.fill_m3
    cut = shape.percent((fit.cut_m3 - true.cut_m3) / moved, 4)
    fill = shape.percent((fit.fill_m3 - true.fill_m3) / moved, 4)
    return (f"desmonte {shape.number(fit.cut_m3)} m³ frente a "
            f"{shape.number(true.cut_m3)} m³ ({cut}), terraplén {shape.number(fit.fill_m3)} m³ "
            f"frente a {shape.number(true.fill_m3)} m³ ({fill})")


def step_line(item: StepResult) -> str:
    sense = "corte" if item.sense == "cut" else "relleno"
    side = "por debajo" if item.sense == "cut" else "por encima"
    text = (
        f"{_where()}, {item.label}, {sense}): sobre la envolvente de la referencia "
        f"{_whole(item.on_reference.differing)} de {_whole(item.cells)} celdas difieren "
        f"(> {shape.number(EQUAL_M * 1000.0, 0)} mm), máxima "
        f"{shape.number(item.on_reference.max_abs_m, 4)} m; "
        f"{_volumes(item.on_reference, item.reference)}; celdas {side} de la envolvente "
        f"{_whole(item.below_envelope)}; con la envolvente de Geoblender "
        f"{_whole(item.chain.differing)} celdas difieren, máxima "
        f"{shape.number(item.chain.max_abs_m, 4)} m; {_volumes(item.chain, item.reference)}"
    )
    berm = item.berm
    if berm is not None:
        literal = ("sin literal de la referencia" if berm.literal_m is None else
                   f"referencia {shape.number(berm.literal_m, 4)} m (±"
                   f"{shape.number(berm.half_unit_m or 0.0, 4)} m de redondeo)")
        text += f"; berma del sector: regla {shape.number(berm.rule_m, 4)} m, {literal}"
    return text


class ReferenceDesignTest(unittest.TestCase):
    """CE-013-10 con el banco del proyecto de referencia (RF-013-11, RF-013-22, RF-013-25)."""

    result: Comparison | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = None
        result = compare(shape.bank_folder())
        for item in result.envelopes:
            shape.report(envelope_line(item))
        for step in result.steps:
            shape.report(step_line(step))
        cls.result = result

    def test_envelopes_are_explained(self) -> None:
        """CE-013-10, RF-013-11, RF-013-12: en cada envolvente, toda celda de la referencia es
        igual, o está dentro de lo que explica la métrica (1,4 % de la caída), o del lado de la
        convergencia del barrido hasta el punto fijo; ninguna queda sin explicar."""
        assert self.result is not None
        self.assertTrue(self.result.envelopes)
        for item in self.result.envelopes:
            with self.subTest(envelope=item.label):
                self.assertEqual(
                    item.unexplained, 0,
                    f"{item.label}: {item.unexplained} celdas sin explicar (del lado contrario "
                    f"al de la convergencia, o sin envolvente), diferencia máxima "
                    f"{shape.number(item.max_abs_m, 4)} m")

    def test_steps_on_the_reference_envelope_reproduce(self) -> None:
        """CE-013-10, RF-013-22, RF-013-27: sobre la envolvente de la referencia, con su perfil y
        su berma, el desmonte y el terraplén de cada escalonado difieren de los de la referencia
        a lo sumo 10⁻⁴ de su movimiento de tierras, y ninguna celda queda por debajo de la
        envolvente en corte (ni por encima en relleno)."""
        assert self.result is not None
        self.assertTrue(self.result.steps)
        for item in self.result.steps:
            with self.subTest(step=item.label):
                self.assertEqual(item.below_envelope, 0,
                                 f"{item.label}: {item.below_envelope} celdas del lado "
                                 "equivocado de la envolvente (RF-013-22, RF-013-27)")
                fit = item.on_reference
                worst = max(fit.relative_cut, fit.relative_fill)
                self.assertLessEqual(
                    worst, VOLUME_TOL,
                    f"{item.label}: el desmonte o el terraplén difieren "
                    f"{shape.percent(worst, 4)} del movimiento de tierras de la referencia "
                    f"({_whole(fit.differing)} celdas difieren, máxima "
                    f"{shape.number(fit.max_abs_m, 4)} m)")

    def test_sector_berm_is_the_rule_within_the_rounding(self) -> None:
        """CE-013-10, RF-013-25, D-11: la berma que da la regla ``máx(B, h/tan β − h/tan α)`` en
        cada sector con talud general máximo no difiere del literal de la referencia más de medio
        decimal de su última cifra."""
        assert self.result is not None
        checked = [item for item in self.result.steps
                   if item.berm is not None and item.berm.literal_m is not None]
        if not checked:
            self.skipTest("la ficha no da la berma de la referencia de ningún sector")
        for item in checked:
            berm = item.berm
            assert berm is not None and berm.literal_m is not None
            with self.subTest(step=item.label):
                self.assertTrue(
                    berm.within,
                    f"{item.label}: la regla da {shape.number(berm.rule_m, 4)} m y la referencia "
                    f"{shape.number(berm.literal_m, 4)} m (el redondeo admite ±"
                    f"{shape.number(berm.half_unit_m or 0.0, 4)} m)")


if __name__ == "__main__":
    unittest.main()
