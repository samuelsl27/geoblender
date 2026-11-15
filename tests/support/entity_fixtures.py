# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera de las entidades de diseño paramétricas (spec 015, T01; plan 015 §7.1 y §7.4;
RF-015-19 a 24; CE-015-02, CE-015-03 y CE-015-07).

Todo es sintético (ningún dato de cliente), en coordenadas **absolutas** float64 (EPSG:25830 +
EPSG:5782) desde la esquina :data:`BASE` de ``tests.support.constraints_fixtures``, sobre la cantera
de la 014 (``tests.support.quarry_fixtures``, que no se toca) y las ayudas de la 013 y la 012. Las
coordenadas «locales» son metros desde :data:`BASE` (``x`` al este, ``y`` al norte); en las
rejillas, la fila 0 es el norte. Cada función que da un array da uno **nuevo**. Las cuentas están
hechas a mano; las comprueba ``tests/unit/design/test_entity_fixtures.py``.

- **El terreno inclinado** (:func:`plane_terrain`): la ladera de la cantera sin el escarpe, un plano
  ``180 + 0,25·y + 0,0625·x`` de 400 × 400 celdas de 1 m, exacto en binario; el de los cálculos del
  borde (CE-015-07).
- **La franja** (:func:`strip_case`; CE-015-02): una plataforma de eje de 200 m (de (100, 200) a
  (300, 200)) y 40 m de ancho al 1 % desde 230 m sobre un terreno 6 m por encima de la rasante, con
  un tramo de 40 m (de 80 a 120 m del principio) **5 m por debajo** de ella: 8.000 celdas de huella,
  1.600 del tramo; «en corte» baja 38.400 m³ y no sube nada (el lomo de B7) y «en corte y relleno»
  sube además 8.000 m³. Con ``untouchable=True``, un intocable (una banda de 10 m que cruza la
  huella de lado a lado) deja 400 celdas sin mover: 36.000 m³ de corte y los mismos 8.000 m³ de
  relleno. Con ``hollow="downstream"`` el tramo bajo la rasante va en el extremo de la abscisa 0 (de
  0 a 40 m, ``STRIP_DOWNSTREAM_HOLLOW_BOX``) y no en el medio: la rasante baja hacia él y el perfil
  longitudinal **no vuelve a subir** (ninguna contrapendiente: el caso base de CE-015-02; en el medio
  sí la hay, RF-015-23). Las cuentas (celdas y m³) son las mismas.
- **Las capas de plataformas** (:func:`platform_layers`; plan §5.2.1): una capa de líneas con los
  campos de un corredor (``ancho``, ``cota_inicial`` y ``pendiente``; D-15: sirve también de capa de
  corredores de la cantera) y una de polígonos con ``cota_inicial``, ``pendiente`` y ``eje``, el
  **número de entidad (``fid``) de su eje en la capa de líneas** (vacío si no tiene). Cinco
  plataformas válidas (tres ejes y dos polígonos) en el interior de la cantera, sin tocarse entre sí
  ni lo de la 014 (:data:`VALID_NAMES`), y los defectos de geometría de RF-015-08 en el margen este,
  fuera de la concesión: ver :data:`AXES` y :data:`POLYGONS`.
- **El proyecto** (:func:`project_template`, :class:`EntityProjectCase`): el de la cantera de la 014
  (V01 y V02, ventana de 400 × 400 celdas de 1 m, restricciones, sectores con sus búsquedas
  cerradas, terreno, las cinco capas y las máscaras de V01) más las dos capas de plataformas. Se
  crea **una vez por proceso** y paso de rejilla (en ≤ 2 s de CPU: :data:`BUILD_BUDGET_S`, lo que
  añade a la cantera) y cada clase trabaja en su copia.
- **La restricción declarada** (:class:`DeclaredConstraintsProjectCase`; T16): la variante de
  ``constraints_project`` con una restricción declarada por una entidad en V01.
  :func:`declare_platform_constraint` escribe su tabla (``des_decl_v01``, con
  ``core.constraints.declared.write_declared``) con una operación de prueba
  (``des.declare_constraints``, sin entradas: no hay entidades) y devuelve su uid:
  :data:`DECLARED_CODE` («sin relleno», la huella :data:`DECLARED_BOX_LOCAL`, 300 celdas de 2 m, y
  :data:`DECLARED_GUARD_M`).
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import quarry_fixtures as qfx
from tests.support.core_fixtures import FakeClock, FakePids, project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

gis = import_geoblender("gis")

CRS = qfx.CRS
"""El CRS de la cantera (ETRS89 / UTM 30N)."""
VERTICAL = qfx.VERTICAL
"""La referencia vertical de las superficies (Alicante)."""
BASE: tuple[float, float] = qfx.BASE
"""La esquina suroeste de la cantera (m, absoluta)."""
GRID = qfx.GRID
"""La rejilla de la cantera: 400 × 400 celdas de 1 m de (0, 0) a (400, 400) locales."""

# --- El terreno inclinado (CE-015-07) ----------------------------------------------------------

PLANE_NORTH_TAN = qfx.TERRAIN_NORTH
"""La pendiente del terreno inclinado hacia el norte (m/m, exacta en binario: 0,25)."""
PLANE_EAST_TAN = qfx.TERRAIN_EAST
"""La pendiente del terreno inclinado hacia el este (m/m, exacta en binario: 0,0625)."""


def plane_terrain(grid: Any = GRID) -> np.ndarray:
    """El terreno inclinado en los centros de ``grid`` (por defecto :data:`GRID`; m, float64,
    exacto en binario): ``180 + 0,25·y + 0,0625·x``, la ladera de la cantera **sin** el escarpe
    de 3 m de y = 300."""
    x, y = qfx.local_centers(grid)
    return qfx.TERRAIN_Z0 + PLANE_NORTH_TAN * y + PLANE_EAST_TAN * x


def plane_raster(grid: Any = GRID) -> Any:
    """:func:`plane_terrain` como ``gis.Raster`` de ``grid``."""
    return gis.Raster(grid, plane_terrain(grid), CRS, VERTICAL)


# --- La franja: un tramo 5 m por debajo de la rasante, con y sin intocable (CE-015-02) ---------

STRIP_AXIS_LOCAL = ((100.0, 200.0), (300.0, 200.0))
"""El eje de la franja (local): recto, de oeste a este, **200 m**."""
STRIP_WIDTH_M = 40.0
"""El ancho de la franja (m)."""
STRIP_START_M = 230.0
"""La cota inicial de su rasante (m), en el primer vértice del eje."""
STRIP_GRADIENT_PCT = 1.0
"""La pendiente de su rasante (%): sube 2 m en los 200 m del eje."""
STRIP_ABOVE_M = 6.0
"""Lo que el terreno queda por encima de la rasante fuera del tramo bajo ella (m)."""
STRIP_HOLLOW_M = 5.0
"""Lo que el tramo bajo la rasante queda por debajo de ella (m)."""
STRIP_FOOTPRINT_BOX = (100.0, 180.0, 300.0, 220.0)
"""La huella de la franja (local: izquierda, abajo, derecha, arriba): 200 × 40 m."""
STRIP_HOLLOW_BOX = (180.0, 180.0, 220.0, 220.0)
"""El tramo bajo la rasante (local): de 80 a 120 m del principio del eje, todo el ancho."""
STRIP_DOWNSTREAM_HOLLOW_BOX = (100.0, 180.0, 140.0, 220.0)
"""El tramo bajo la rasante **aguas abajo** (local): de 0 a 40 m del principio del eje, todo el ancho.
La rasante sube con la abscisa (+ 1 %): baja hacia la abscisa 0, que es el extremo del tramo."""
STRIP_HOLLOW_PLACES: tuple[str, ...] = ("middle", "downstream")
"""Dónde va el tramo bajo la rasante: ``middle`` (de 80 a 120 m, el de siempre) o ``downstream``
(de 0 a 40 m, aguas abajo de la rasante)."""
UNTOUCHABLE_BOX = (140.0, 170.0, 150.0, 230.0)
"""La banda del intocable (local): 10 m en x, de 40 a 50 m del principio del eje, que cruza la
huella de lado a lado y sobresale 10 m por cada lado (10 × 60 celdas)."""
UNTOUCHABLE_NAME = "Intocable de la franja"
"""El nombre de la restricción del intocable (para el aviso de lo que no se mueve)."""

STRIP_FOOTPRINT_CELLS = 8_000
"""Las celdas de la huella: 200 columnas de 40 filas."""
STRIP_HOLLOW_CELLS = 1_600
"""Las celdas del tramo bajo la rasante: 40 × 40."""
STRIP_BLOCKED_CELLS = 400
"""Las celdas de la huella que el intocable deja sin mover: 10 × 40."""
STRIP_GRADE_FIRST_M = 230.005
"""La rasante en el centro de la primera columna (abscisa 0,5 m): 230 + 0,5 · 0,01."""
STRIP_GRADE_LAST_M = 231.995
"""La rasante en el centro de la última columna (abscisa 199,5 m): 230 + 199,5 · 0,01."""
STRIP_CUT_M3 = 38_400.0
"""Lo que «en corte» baja: 6 m en las 6.400 celdas por encima de la rasante (8.000 − 1.600)."""
STRIP_FILL_M3 = 8_000.0
"""Lo que «en corte y relleno» sube además: 5 m en las 1.600 celdas del tramo."""
STRIP_CUT_BLOCKED_M3 = 36_000.0
"""El corte con el intocable: 6 m en 6.000 celdas (6.400 − las 400 que no se mueven)."""


@dataclass(frozen=True, slots=True, eq=False)
class StripCase:
    """La franja de :func:`strip_case` sobre :data:`GRID`: el eje (``axis``, absoluto, ``(2, 2)``),
    su ``width_m``, la rasante (``grade_start_m``, ``slope_pct``), el ``terrain`` (en toda la
    rejilla), la huella (``footprint``), la rasante de cada celda de la huella (``grade``; ``nan``
    fuera: ``cota_inicial + σ · pendiente / 100`` con σ la abscisa del centro, a mano), el tramo
    bajo ella (``hollow``) y las máscaras ``cut_allowed`` y ``fill_allowed`` (la rejilla entera
    admitida, salvo la banda del intocable si lo hay), con las celdas de la huella que el intocable
    bloquea (``blocked``, ``blocked_by`` su nombre) y los m³ de corte y de relleno que dan las
    cuentas a mano (``cut_m3`` en cualquier modo; ``fill_m3`` solo en «en corte y relleno»).
    ``hollow_at`` es dónde está el tramo bajo la rasante (:data:`STRIP_HOLLOW_PLACES`)."""

    grid: Any
    axis: np.ndarray
    width_m: float
    grade_start_m: float
    slope_pct: float
    terrain: np.ndarray
    footprint: np.ndarray
    grade: np.ndarray
    hollow: np.ndarray
    cut_allowed: np.ndarray
    fill_allowed: np.ndarray
    blocked: np.ndarray
    blocked_by: str
    cut_m3: float
    fill_m3: float
    hollow_at: str = "middle"


def strip_case(*, untouchable: bool = False, hollow: str = "middle") -> StripCase:
    """La franja de CE-015-02 (véase el módulo), con o sin el intocable que cruza la huella y con el
    tramo bajo la rasante en ``hollow`` (:data:`STRIP_HOLLOW_PLACES`): ``middle`` (de 80 a 120 m del
    principio del eje: el perfil baja en el tramo y **vuelve a subir** aguas abajo de él, una
    contrapendiente de 4,99 m por RF-015-23) o ``downstream`` (de 0 a 40 m: el tramo está en el
    extremo por donde baja la rasante y el perfil solo baja; el caso base de CE-015-02: ninguna
    contrapendiente). El eje, la huella, la rasante, las máscaras y las cuentas a mano (los m³) son
    los mismos en las dos; ``ValueError`` si ``hollow`` no es de la lista."""
    if hollow not in STRIP_HOLLOW_PLACES:
        raise ValueError(f"el tramo bajo la rasante va en {' o '.join(STRIP_HOLLOW_PLACES)}, "
                         f"no en «{hollow}»")
    x, _y = qfx.local_centers(GRID)
    footprint = qfx.in_box(STRIP_FOOTPRINT_BOX, GRID)
    hollow_box = STRIP_HOLLOW_BOX if hollow == "middle" else STRIP_DOWNSTREAM_HOLLOW_BOX
    hollow_cells = qfx.in_box(hollow_box, GRID)
    line = STRIP_START_M + (x - STRIP_AXIS_LOCAL[0][0]) * (STRIP_GRADIENT_PCT / 100.0)
    terrain = np.where(hollow_cells, line - STRIP_HOLLOW_M, line + STRIP_ABOVE_M)
    grade = np.where(footprint, line, np.nan)
    band = qfx.in_box(UNTOUCHABLE_BOX, GRID) if untouchable else np.zeros(GRID.shape, dtype=bool)
    allowed = ~band
    return StripCase(
        GRID, cfx.absolute(STRIP_AXIS_LOCAL), STRIP_WIDTH_M, STRIP_START_M, STRIP_GRADIENT_PCT,
        terrain, footprint, grade, hollow_cells, allowed, allowed.copy(), footprint & band,
        UNTOUCHABLE_NAME if untouchable else "",
        STRIP_CUT_BLOCKED_M3 if untouchable else STRIP_CUT_M3, STRIP_FILL_M3, hollow)


# --- Las capas de plataformas (plan 015 §5.2.1) ----------------------------------------------

AXES_LAYER = "gis_fea_plataformas_ejes"
"""La capa de líneas: los ejes de las plataformas (con los campos de un corredor, D-15)."""
POLYGONS_LAYER = "gis_fea_plataformas_poligonos"
"""La capa de polígonos de las plataformas, con su enlace a la de ejes."""
LAYERS: tuple[str, ...] = (AXES_LAYER, POLYGONS_LAYER)
"""Los nombres de las dos capas, en el orden en que se escriben."""
LINK_FIELD = "eje"
"""El campo del enlace de un polígono con su eje: el ``fid`` del eje en :data:`AXES_LAYER`, vacío
(``None``) si no tiene (lo que la T06 y la T11 pueden cambiar por el nombre si la spec lo pide)."""

SELF_INTERSECTING = "self_intersecting"
"""Defecto: la geometría se corta a sí misma."""
CLOSED = "closed"
"""Defecto: un eje cerrado (acaba donde empieza)."""
ZERO_LENGTH = "zero_length"
"""Defecto: un eje de longitud cero."""
NO_WIDTH = "no_width"
"""Defecto: un eje sin ancho (el campo está vacío)."""
SHORT = "short"
"""Defecto de un eje de enlace: entra en su polígono y acaba dentro (no lo cruza de lado a lado)."""
ZERO_AREA = "zero_area"
"""Defecto: un polígono de área cero."""
NO_CELLS = "no_cells"
"""Defecto: un polígono sin ningún centro de celda dentro."""
AXIS_DOES_NOT_CROSS = "axis_does_not_cross"
"""Defecto: un polígono enlazado con un eje que no lo cruza (:data:`SHORT`)."""


@dataclass(frozen=True, slots=True, eq=False)
class AxisSpec:
    """Un eje de :data:`AXES_LAYER`: su nombre, su camino local, el ancho (m), la cota inicial (m)
    y la pendiente (%) de su rasante (``None`` si el campo va vacío) y su ``defect`` (``None`` si es
    válido)."""

    name: str
    path: tuple[tuple[float, float], ...]
    width_m: float | None
    start_m: float | None
    gradient_pct: float | None
    defect: str | None = None


@dataclass(frozen=True, slots=True, eq=False)
class PolygonSpec:
    """Un polígono de :data:`POLYGONS_LAYER`: su nombre, su anillo local (cerrado), la cota inicial
    (m) y la pendiente (%) de su rasante, el nombre del eje de :data:`AXES` con el que se enlaza
    (``None`` si no tiene) y su ``defect`` (``None`` si es válido)."""

    name: str
    ring: tuple[tuple[float, float], ...]
    start_m: float
    gradient_pct: float
    axis: str | None = None
    defect: str | None = None


def _box(left: float, bottom: float, right: float, top: float
         ) -> tuple[tuple[float, float], ...]:
    return ((left, bottom), (right, bottom), (right, top), (left, top), (left, bottom))


AXES: tuple[AxisSpec, ...] = (
    # Las plataformas válidas, en el interior de la cantera (en el corte admitido de V01). Cada
    # rasante queda por debajo de todo el terreno de su huella (corta del todo).
    AxisSpec("Plataforma de carga", ((110.0, 280.0), (310.0, 280.0)), 20.0, 250.0, 1.0),
    AxisSpec("Plataforma de taller", ((125.0, 90.0), (245.0, 90.0), (245.0, 130.0)), 30.0,
             200.0, 2.0),
    # Su huella (x de 290 a 310, y de 90 a 140) tiene dentro, entera, la zona de la torre de la
    # cantera (224 celdas de 1 m, con 8 m de resguardo): un intocable que cruza la huella.
    AxisSpec("Plataforma de la torre", ((300.0, 90.0), (300.0, 140.0)), 20.0, 215.0, 1.0),
    # El eje de la «Explanada con eje»: solo la geometría, sin ancho ni rasante propios.
    AxisSpec("Eje de la explanada", ((110.0, 235.0), (210.0, 235.0)), None, None, None),
    # Los defectos de RF-015-08, en el margen este (fuera de la concesión, que acaba en x = 360).
    AxisSpec("Eje que se corta", ((365.0, 300.0), (395.0, 330.0), (395.0, 300.0), (365.0, 330.0)),
             10.0, 200.0, 1.0, SELF_INTERSECTING),
    AxisSpec("Eje cerrado", ((365.0, 340.0), (395.0, 340.0), (395.0, 370.0), (365.0, 370.0),
                             (365.0, 340.0)), 10.0, 200.0, 1.0, CLOSED),
    AxisSpec("Eje de longitud cero", ((380.0, 30.0), (380.0, 30.0)), 10.0, 200.0, 1.0,
             ZERO_LENGTH),
    AxisSpec("Eje sin ancho", ((365.0, 50.0), (395.0, 50.0)), None, 200.0, 1.0, NO_WIDTH),
    AxisSpec("Eje corto", ((360.0, 260.0), (380.0, 260.0)), 10.0, 200.0, 1.0, SHORT),
)
"""Los ejes de :data:`AXES_LAYER`, por orden de ``fid`` (1, 2…): cuatro válidos (carga, taller,
torre y el de enlace de la explanada) y los cinco con defecto."""
POLYGONS: tuple[PolygonSpec, ...] = (
    PolygonSpec("Explanada con eje", _box(120.0, 210.0, 200.0, 260.0), 235.0, 1.5,
                "Eje de la explanada"),
    # Sin eje enlazado: el eje principal es el de los 80 m (norte-sur) y su abscisa 0, el extremo
    # más al sur (los dos están a la misma x).
    PolygonSpec("Explanada sin eje", _box(310.0, 180.0, 350.0, 260.0), 240.0, 0.5),
    PolygonSpec("Polígono que se corta",
                ((365.0, 100.0), (395.0, 130.0), (395.0, 100.0), (365.0, 130.0), (365.0, 100.0)),
                200.0, 1.0, defect=SELF_INTERSECTING),
    PolygonSpec("Polígono sin área", ((365.0, 150.0), (395.0, 150.0), (380.0, 150.0),
                                      (365.0, 150.0)), 200.0, 1.0, defect=ZERO_AREA),
    PolygonSpec("Polígono sin celdas", _box(380.1, 200.1, 380.4, 200.4), 200.0, 1.0,
                defect=NO_CELLS),
    PolygonSpec("Explanada con eje que no la cruza", _box(365.0, 240.0, 395.0, 280.0), 200.0, 1.0,
                "Eje corto", AXIS_DOES_NOT_CROSS),
)
"""Los polígonos de :data:`POLYGONS_LAYER`, por orden de ``fid``: dos válidos y cuatro con
defecto."""
VALID_NAMES: tuple[str, ...] = (
    "Plataforma de carga", "Plataforma de taller", "Plataforma de la torre", "Explanada con eje",
    "Explanada sin eje")
"""Las plataformas válidas (sus nombres en la capa de ejes o en la de polígonos): su huella no toca
las demás ni lo de la cantera de la 014 y cae en el corte admitido de V01 (salvo la zona de la torre
en la de la torre)."""


def axis_fid(name: str) -> int:
    """El ``fid`` (1, 2…) del eje ``name`` en :data:`AXES_LAYER`; ``KeyError`` si no está."""
    for index, spec in enumerate(AXES, start=1):
        if spec.name == name:
            return index
    raise KeyError(name)


def platform_layers() -> tuple[qfx.LayerData, ...]:
    """Las dos capas de plataformas (arrays nuevos), en el orden en que se escriben:
    :data:`AXES_LAYER` y :data:`POLYGONS_LAYER`."""
    axes = qfx.LayerData(
        AXES_LAYER, "line", tuple(((cfx.absolute(spec.path),),) for spec in AXES),
        tuple(spec.name for spec in AXES),
        {"ancho": tuple(spec.width_m for spec in AXES),
         "cota_inicial": tuple(spec.start_m for spec in AXES),
         "pendiente": tuple(spec.gradient_pct for spec in AXES)})
    polygons = qfx.LayerData(
        POLYGONS_LAYER, "polygon", tuple(((cfx.absolute(spec.ring),),) for spec in POLYGONS),
        tuple(spec.name for spec in POLYGONS),
        {"cota_inicial": tuple(spec.start_m for spec in POLYGONS),
         "pendiente": tuple(spec.gradient_pct for spec in POLYGONS),
         LINK_FIELD: tuple(None if spec.axis is None else float(axis_fid(spec.axis))
                           for spec in POLYGONS)})
    return axes, polygons


# --- El proyecto de la cantera con las plataformas -------------------------------------------

BUILD_BUDGET_S = 2.0
"""Lo que añade la plantilla a la cantera de la 014 (copiarla y escribir las dos capas) se
construye en ≤ 2 s de CPU (tarea T01)."""
_TEMPLATES: dict[float, dict[str, Any]] = {}


def _open(folder: Path, made: Mapping[str, Any], clock: FakeClock) -> Any:
    open_mod = import_geoblender("core.project.open")
    userdata = import_geoblender("core.userdata")
    return open_mod.open_project(
        folder / "proyectos" / made["name"], cp.SESSION, userdata.UserData(folder / "u"),
        clock=clock, pid_alive=FakePids({cp.SESSION.pid})).project


def _build(folder: Path, base: Mapping[str, Any]) -> dict[str, Any]:
    """Copia la cantera ``base`` en ``folder``, le escribe las capas de plataformas y la cierra."""
    started = time.process_time()
    shutil.copytree(base["folder"] / "proyectos", folder / "proyectos")
    clock = FakeClock(base["now"])
    project = _open(folder, base, clock)
    try:
        for layer in platform_layers():
            qfx.write_feature_layer(project, clock, layer)
        clock.advance(minutes=1)
        return {"folder": folder, "name": base["name"], "now": clock.now(),
                "versions": base["versions"], "build_s": time.process_time() - started}
    finally:
        project.close()


def project_template(step_m: float = qfx.STEP_M) -> Mapping[str, Any]:
    """El proyecto de la cantera con las capas de plataformas (véase el módulo) con la rejilla de
    ``step_m`` m (por defecto la de 1 m; con ``qfx.COARSE_STEP_M``, la gruesa), creado y cerrado la
    primera vez que se pide en el proceso con ese paso, en una carpeta temporal que se borra al
    salir: ``folder``, ``name`` de la carpeta del proyecto, ``now`` del reloj al terminar, los uid
    de ``versions`` (V01 y V02) y ``build_s``, la CPU que gastó **añadir las plataformas** a la
    cantera (s; la de la 014 tiene la suya). No se modifica."""
    found = _TEMPLATES.get(step_m)
    if found is None:
        base = qfx.project_template(step_m)  # antes del registro: construye la suya con el suyo
        folder = Path(tempfile.mkdtemp(prefix="gb-et-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        with cp.constraints_registered():
            found = _TEMPLATES[step_m] = _build(folder, base)
    return found


@contextmanager
def open_entity_project(prefix: str = "gb-ep-", step_m: float = qfx.STEP_M
                        ) -> Iterator[tuple[Any, FakeClock]]:
    """Una copia propia del proyecto de la cantera con las capas de plataformas
    (:func:`project_template`) abierta en escritura: ``(project, clock)``. Al salir se cierra y se
    borra. Hace falta ``constraints_project.constraints_registered()`` activo (lo está en una
    :class:`EntityProjectCase`)."""
    made = project_template(step_m)
    with project_tmp(prefix) as folder:
        shutil.copytree(made["folder"] / "proyectos", folder / "proyectos")
        clock = FakeClock(made["now"])
        project = _open(folder, made, clock)
        try:
            yield project, clock
        finally:
            project.close()


class EntityProjectCase(qfx.QuarryProjectCase):
    """Una copia **por clase** del proyecto de la cantera con las capas de plataformas, abierta en
    escritura: lo de :class:`~tests.support.quarry_fixtures.QuarryProjectCase` (``cls.project``,
    ``cls.root``, ``cls.clock``, ``cls.v1``, ``cls.v2``, ``cls.grid``, ``masks``, ``read_layer``,
    ``stale_causes``, ``recompute_plan``…; una clase con ``STEP_M = qfx.COARSE_STEP_M`` trabaja en
    la gruesa) y, en ella, las capas :data:`AXES_LAYER` y :data:`POLYGONS_LAYER`."""

    @classmethod
    def setUpClass(cls) -> None:
        versions_read = import_geoblender("core.versions.read")
        cls.grid = qfx.grid_of(cls.STEP_M)
        made = project_template(cls.STEP_M)
        cls.enterClassContext(cp.constraints_registered())
        cls.project, cls.clock = cls.enterClassContext(open_entity_project("gb-ec-", cls.STEP_M))
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in made["versions"])


# --- La restricción declarada (T16; RF-012-29, RF-015-10) ---------------------------------------

DECLARED_MODULE = "core.constraints.declared"
"""El módulo del esquema de las declaradas (T16; plan 015 §5.1)."""
DECLARED_ENTITY = "PLT-001"
"""El código de la entidad que declara (``PLT-nnn``, T02)."""
DECLARED_ENTITY_NAME = "P1"
"""El nombre de la entidad que declara (el motivo generado, «declarada por la plataforma P1»)."""
DECLARED_CODE = "dec__plt_001"
"""El código de la restricción declarada: ``dec__<entidad>`` (``declared_code``: un código válido de la
012, único en las tres capas)."""
DECLARED_BOX_LOCAL = (130.0, 140.0, 170.0, 170.0)
"""La huella de la entidad que declara, en el sitio de ``constraints_project`` (local: izquierda,
abajo, derecha, arriba): 40 × 30 m = 300 celdas de 2 m, dentro del perímetro y lejos de su balsa, su
torre y su cuneta."""
DECLARED_CELLS = 300
"""Las celdas de la huella de la declarada de prueba."""
DECLARED_GUARD_M = 4.0
"""El resguardo de la declarada de prueba (m): dos celdas del sitio."""
DECLARED_BY = "Samuel (IMGA)"
DECLARED_ON = date(2026, 11, 14)
"""El decisor y la fecha de la decisión de la declarada de prueba (la de la aprobación del DIFF-012;
nunca ``now``)."""


def declared_footprint() -> np.ndarray:
    """La huella de la declarada de prueba como máscara de ``cfx.SITE_GRID`` (de ``DECLARED_CELLS``
    celdas)."""
    x, y = cfx.site_centers()
    left, bottom, right, top = DECLARED_BOX_LOCAL
    return (x > left) & (x < right) & (y > bottom) & (y < top)


def declared_constraint(version_uid: str) -> Any:
    """La restricción declarada de prueba (``core.constraints.declared.DeclaredConstraint``) de la
    versión de uid ``version_uid``: :data:`DECLARED_CODE`, «sin relleno», con el contorno de
    :func:`declared_footprint` (``design.entities.declared_zone``), :data:`DECLARED_GUARD_M`, el
    motivo generado de la entidad, :data:`DECLARED_BY` y :data:`DECLARED_ON`."""
    declared = import_geoblender(DECLARED_MODULE)
    entities = import_geoblender("design.entities")
    constraint_model = import_geoblender("core.constraints.model")
    zone = entities.declared_zone(declared_footprint(), cfx.SITE_GRID, DECLARED_GUARD_M)
    return declared.DeclaredConstraint(
        uid=declared.declared_uid(version_uid, DECLARED_ENTITY),
        code=declared.declared_code(DECLARED_ENTITY),
        ctype=constraint_model.ConstraintType.NO_FILL, name=DECLARED_ENTITY_NAME,
        reason=entities.declared_reason(entities.EntityKind.PLATFORM, DECLARED_ENTITY_NAME),
        decided_by=DECLARED_BY, decided_on=DECLARED_ON, entity_code=DECLARED_ENTITY,
        entity_name=DECLARED_ENTITY_NAME, parts=zone.parts, buffer_out_m=DECLARED_GUARD_M,
        active=True)


def _never(request: Any) -> Any:
    raise AssertionError("las pruebas de las declaradas no recalculan ni reproducen")


@contextmanager
def declared_registered() -> Iterator[None]:
    """Registra lo que declara ``des`` para las declaradas (lo hará ``bl``): los tres tipos de la 015
    (``des.declare_constraints`` entre ellos, con funciones de recálculo y reproducción que no se
    llaman) y sus cifras, los que falten; al salir, quita lo que registró."""
    contract = import_geoblender("core.provenance.contract")
    provenance = import_geoblender("design.provenance")
    types = provenance.ENTITY_VERSION_TYPES
    definitions = provenance.entity_operation_defs({name: _never for name in types},
                                                   {name: _never for name in types})
    wanted = [item for item in definitions if item.op_type not in contract.OPERATIONS]
    wanted += [item for item in provenance.ENTITY_FIGURES if item.key not in contract.FIGURES]
    with registered(*wanted):
        yield


def declare_rows(project: Any, clock: Any, rows: Any, *, version: Any = None,
                 supersedes: str | None = None) -> str:
    """Escribe en ``project`` la tabla de restricciones declaradas de ``version`` (por defecto V01) con
    ``rows`` (``core.constraints.declared.DeclaredConstraint``; ninguna la deja vacía) con una operación de
    prueba de ``des.declare_constraints`` (como ``constraints_project.edit_constraints``; sin entradas: no
    hay entidades) que usa ``write_declared``, y devuelve el uid de la operación. Con ``supersedes`` (el uid
    de la declaración vigente), la sustituye (como repetirla: ``des.declare_constraints`` es repetible).
    Registra los tipos de ``des`` que falten mientras escribe."""
    declared = import_geoblender(DECLARED_MODULE)
    operations = import_geoblender("core.provenance.operations")
    versions_read = import_geoblender("core.versions.read")
    provenance = import_geoblender("design.provenance")
    if version is None:
        with project.read() as conn:
            version = versions_read.version(conn, "V01")
    rows = tuple(rows)
    srs = project.record.crs_epsg
    table = provenance.dataset_locator(provenance.DECLARED_TABLE, "", version.code)
    with declared_registered():
        clock.advance(minutes=1)
        handle = operations.begin_operation(
            project, provenance.DECLARE_CONSTRAINTS, executor="blender", version=version.uid,
            supersedes=supersedes,
            settings=provenance.declare_settings([(row.entity_code, row.entity_name)
                                                  for row in rows]))
        with project.write_transaction() as conn:
            declared.write_declared(conn, table, rows, srs_id=srs)
            handle.complete(
                conn, outputs=(provenance.dataset_spec(provenance.DECLARED_TABLE, "", version.code,
                                                       crs_epsg=srs),),
                figures=provenance.declare_figures(len(rows)),
                message="Restricción declarada de prueba")
    return str(handle.uid)


def declare_platform_constraint(project: Any, clock: Any, *, version: Any = None) -> str:
    """Escribe en ``project`` la tabla de restricciones declaradas de ``version`` (por defecto V01) con
    una, :data:`DECLARED_CODE` («sin relleno», la huella :data:`DECLARED_BOX_LOCAL` y
    :data:`DECLARED_GUARD_M`), con :func:`declare_rows` (``core.constraints.declared.write_declared``), y
    devuelve el uid de la operación."""
    versions_read = import_geoblender("core.versions.read")
    if version is None:
        with project.read() as conn:
            version = versions_read.version(conn, "V01")
    return declare_rows(project, clock, [declared_constraint(version.uid)], version=version)


class DeclaredConstraintsProjectCase(cp.ConstraintsProjectCase):
    """Una copia por clase del proyecto de ``constraints_project`` (V01 y V02; 160 × 160 celdas de
    2 m) con una restricción declarada por una entidad (:func:`declare_platform_constraint`) en V01 y
    los tipos de ``des`` registrados (:func:`declared_registered`) mientras dura la clase."""

    declared_operation: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(declared_registered())
        cls.declared_operation = declare_platform_constraint(cls.project, cls.clock,
                                                              version=cls.v1)
