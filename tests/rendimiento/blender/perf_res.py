# SPDX-License-Identifier: GPL-3.0-or-later
"""La cubicación dentro de Blender (spec 011, T28; RNF-011-04 y RNF-011-05; plan 011 §7.3 y el
riesgo R4, ``tests/rendimiento/blender``).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py --
--carpeta tests/rendimiento/blender --patron "perf_res.py"``). Cada prueba imprime su cifra en
una línea «RNF-011-nn: …» con el equipo y el espacio libre del disco, y la compara con su
presupuesto, sin relajarlo.

**Datos** (plan §2.2; ``tests/support/res_perf.py``: se generan aquí, no se versionan y se borran
al terminar): un proyecto nuevo (EPSG:25830 + EPSG:5782) con V01 en ``%TEMP%``, con la rejilla de
referencia de 1 654 × 1 699 celdas de 1 m (2,81 M) de la partida, la final, las bases y los
espesores de las unidades como rejillas del proyecto (``gis_dtm_``, escritas como las deja
«Rejilla del proyecto desde un MDT») y los 20 dominios (31 920 vértices) importados con el papel
«dominios» (``gis_dom_dominios``, campo «dominio»); la columna de materiales y sus parámetros
sintéticos (HIPÓTESIS; D-8: ningún material real), guardados como los deja «Materiales y
densidades…». Todo con la extensión habilitada, como una persona.

- **RNF-011-04** (:class:`CallsTest`): «Por unidad, fase y banco…»
  (``geoblender.res_compute_volume_breakdown``), la orden real, con la columna de RNF-011-02 (8
  unidades: una compuesta y dos antrópicas), los 20 dominios y 30 rodajas (8,5 m ancladas a la
  cota 0) y sus toneladas encadenadas (D-16), como desde la interfaz: su diálogo con las dos
  superficies seleccionadas en la vista (``invoke``, con lo que propone; antes de cubicar, se
  anota aparte), Intro (``execute`` por ``bpy.ops``, en pasos) y cada evento del temporizador de
  su modal hasta que termina, con el tic de los indicadores de la procedencia cuando le toca (el
  temporizador que corre mientras tanto). Cada llamada del hilo de Blender se mide: lo que hace
  Geoblender en ella, **sin la transacción final** (``reserves.store.ResultWriter.commit`` de
  ``res.volume`` y de ``res.tonnage``: las tablas, las cifras y la operación, en una transacción
  que no se trocea; plan R4), ≤ 0,2 s; la transacción, medida aparte, se anota con la llamada en
  que ocurre (si pasa de 0,2 s, con un aviso: la cifra, para Samuel). Dos veces: con un nombre
  nuevo y repitiéndolo para sustituirla (D-30: la confirmación, con las tablas anteriores).
- **RNF-011-05** (:class:`PanelTest`): la ventana de la cubicación (N ▸ Proyecto ▸
  Cubicaciones) con la tabla de 20 dominios × 30 rodajas × 10 unidades (6 000 volúmenes por
  dominio, rodaja y unidad; la columna con dos unidades más) y sus toneladas: abrirla
  (``geoblender.res_show_volumetrics``; tras cubicar, el temporizador que pide su dibujo,
  ``volumetrics_tick``; pulsarla en la lista) y cada cambio de filtro (dominio, banco, unidad,
  «cualquiera» y las relaciones) ≤ 0,5 s; cada redibujo (el panel con la fila elegida y las filas
  visibles de sus dos listas) ≤ 5 ms. Los dibujos, con un *layout* nulo
  (``perf_ui_draw_cost.NullLayout``): se mide el Python de Geoblender.
- **En la red** (:class:`NetworkTest`; recurso «red» de ``tests.support.network``: con
  ``GEOBLENDER_NET_TEST_DIR``, a mano; sin ella, se omite): lo de RNF-011-04 con el proyecto en una
  subcarpeta temporal propia de la carpeta de pruebas de ``Z:`` (borrada al terminar) y los datos
  de usuario en disco local; las esperas de la red de cada llamada (abrir, leer, escribir,
  forzar y cerrar ficheros del proyecto, sus metadatos y el COMMIT de cada transacción) se miden
  con ``tests.support.netwaits`` y se anotan aparte, sin presupuesto (como RNF-005-06 y
  RNF-009-05): el presupuesto es el de lo que hace Geoblender. Escribe unos 200 MB en la red.

En ``blender -b`` no corren ni el bucle de eventos ni los temporizadores: la prueba hace de
ventana (un evento del temporizador del modal cada vez) y de temporizador; ``wm.call_panel``
(que en ``-b`` cierra Blender) se sustituye: se anota que la orden abriría la ventana.
"""

from __future__ import annotations

import dataclasses
import gc
import importlib
import json
import os
import platform
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.rendimiento.blender.perf_ui_draw_cost import NullLayout
from tests.support import blender_ext, netwaits, network
from tests.support import res_perf as data
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import operator_self
from tests.support.resources import requires
from tests.support.trees import remove_tree

CALL_BUDGET_S = 0.2  # RNF-011-04: lo que hace Geoblender en cada llamada del hilo de Blender
PANEL_BUDGET_S = 0.5  # RNF-011-05: abrir y filtrar
REDRAW_BUDGET_S = 0.005  # RNF-011-05: cada redibujo
OPENINGS = 5  # cada manera de abrir la ventana, medida tantas veces (la peor cuenta)
DRAWS = 1000  # dibujos para medir lo que cuesta cada uno
TOP_CALLS = 5
MAX_EVENTS = 5000
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
TIMER_INTERVAL_S = 0.05
"""El temporizador del modal (``bl.ops.core._StepsModal.TIMER_INTERVAL_S``): lo que pasa, como
mucho, entre dos eventos (para saber cuándo le toca al tic de los indicadores)."""
BREAKDOWN = "geoblender.res_compute_volume_breakdown"
BETWEEN = "geoblender.res_compute_volume_between_surfaces"
REASON = "Rendimiento de la cubicación (spec 011, T28)"
GIVEN = {"kind": "HIPÓTESIS", "source": "Valores sintéticos de prueba",
         "source_kind": "document", "decided_by": "Samuel (IMGA)", "reason": REASON}
"""Cómo se declaran los parámetros sintéticos de la columna (D-8)."""
DOMAINS_NAME = "Dominios"
DOMAINS_LAYER = "dominios"
ANCHOR_M = 0.0
DIALOG = {"name": "", "start": "", "final": "", "start_elevation": "", "final_elevation": "",
          "invert": False, "scope_layer": "NONE", "difference_grid": False,
          "domains_layer": "NONE", "domains_field": "NONE", "bench_height": "",
          "bench_anchor": "", "bench_levels": "", "by_units": False, "replace": False,
          "confirm": False, "in_steps": False}
"""Los valores por defecto del diálogo de «Por unidad, fase y banco…» abierto a mano."""
ORDER_FIELDS = ("name", "start", "final", "domains_layer", "domains_field", "bench_height",
                "bench_anchor", "by_units")
"""Lo del diálogo que la orden recibe al pulsar Intro."""


def _module(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión."""
    return importlib.import_module(f"{module_name()}.{name}")


# --- Equipo y texto de las cifras -------------------------------------------------------------


def _processor() -> str:
    """El nombre del procesador (en Windows, el del registro) y sus hilos."""
    name = ""
    try:
        import winreg

        key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            name = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError):
        name = platform.processor()
    return f"{name or 'procesador desconocido'}, {os.cpu_count()} hilos"


MACHINE = (f"{_processor()}; Blender {bpy.app.version_string} sin interfaz, Python "
           f"{platform.python_version()}, numpy {np.__version__}")
"""El equipo y el intérprete de las cifras."""


def number(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def ms(seconds: float, digits: int = 1) -> str:
    return number(seconds * 1000.0, digits)


def count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def report(text: str) -> None:
    """Una línea de cifra (``tools/check.py`` recoge las que empiezan por «RNF-NNN-nn: »)."""
    print(text, file=sys.stderr, flush=True)


def free_space(path: Path) -> str:
    """El espacio libre del disco de ``path`` (trampa §6: un ``fsync`` lento con el disco casi
    lleno)."""
    usage = shutil.disk_usage(path)
    return (f"{number(usage.free / 1e9, 1)} GB libres de {number(usage.total / 1e9, 0)} GB "
            f"({number(100 * usage.free / usage.total, 0)} %) en el disco del proyecto")


def _timed(function: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = function()
    return time.perf_counter() - started, result


# --- El proyecto de §2.2, con la extensión -----------------------------------------------------


def _grid_name(label: str) -> str:
    gis_provenance = _module("gis.provenance")
    return gis_provenance.dataset_name(gis_provenance.PROJECT_GRID, label)


def _benches(start: np.ndarray, final: np.ndarray) -> float:
    """La altura de las rodajas de RNF-011-02 (ancladas a la cota 0): con la que las cotas de lo
    que se mueve dan :data:`res_perf.BENCHES` rodajas (como ``test_res_perf``)."""
    slices = _module("reserves.slices")
    both = np.isfinite(start) & np.isfinite(final) & (start != final)
    low = float(np.min(np.minimum(start, final)[both]))
    high = float(np.max(np.maximum(start, final)[both]))
    for tenths in range(100, 9, -1):
        found = slices.Slices(tenths / 10, ANCHOR_M, None)
        if slices.bounds(found, low, high).size - 1 == data.BENCHES:
            return tenths / 10
    raise AssertionError(f"ninguna altura da {data.BENCHES} rodajas de {low} a {high}")


def _write_grids(project: Any, labels: Sequence[str]) -> float:
    """Las rejillas ``labels`` de §2.2 como rejillas del proyecto (``gis_dtm_``), en una operación
    ``gis.resample`` como las deja «Rejilla del proyecto desde un MDT»; la altura de las rodajas
    (:func:`_benches`)."""
    gis_store = _module("gis.store")
    grid = _module("gis.grid").Grid(data.WEST, data.NORTH, data.STEP, data.STEP, data.COLS,
                                    data.ROWS)
    raster = _module("gis.raster").Raster
    crs, vertical = gis_store.project_references(project)
    x, y = grid.centers()
    found = data.surfaces(x, y, labels)
    del x, y
    height = _benches(found[data.START], found[data.FINAL])
    handle = _module("core.provenance.operations").begin_operation(
        project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Rejillas de §2.2"},
        executor="blender")
    with gis_store.ResultWriter(project, handle) as out:
        for label in labels:
            out.raster(label, raster(grid, found[label], crs, vertical))
        out.commit(software={"pyproj": "3.8.0"}, message=REASON)
    return height


def _import_domains(project: Any, folder: Path) -> str:
    """«Capas vectoriales…» de la 006 sin su trabajo (como ``test_res_ops.import_layer``): los
    20 dominios de §2.2 (campo «dominio»: D01…D20) en un GeoPackage de ``folder``, fuera del
    proyecto, importados con el papel «dominios»; el nombre de su dato (``gis_dom_``)."""
    ps = _module("bl.scene.project_session")
    gis_store, vector = _module("gis.store"), _module("gis.vector")
    inputs = _module("core.inputs")
    crs, vertical = gis_store.project_references(project)
    path = folder / f"{DOMAINS_LAYER}.gpkg"
    conn = sqlite3.connect(path)
    try:
        _module("core.gpkg.base").create_base(conn, crs)
        conn.execute(f'CREATE TABLE "{DOMAINS_LAYER}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT '
                     f'NULL, geom GEOMETRY, "{data.FIELD}" TEXT)')
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, "
                     "srs_id) VALUES (?, 'features', ?, '', ?)",
                     (DOMAINS_LAYER, DOMAINS_LAYER, crs.epsg))
        conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', 'POLYGON', ?, 0, 0)",
                     (DOMAINS_LAYER, crs.epsg))
        encode = _module("core.gpkg.wkb").encode_geometry
        for index, ring in enumerate(data.domain_rings()):
            conn.execute(f'INSERT INTO "{DOMAINS_LAYER}" VALUES (?, ?, ?)',
                         (index + 1, encode("POLYGON", [ring], crs.epsg, False),
                          f"D{index + 1:02d}"))
        conn.commit()
    finally:
        conn.close()
    reader = _module("gis.content").GPKG_LAYER
    settings = {"layer": DOMAINS_LAYER, "role": "domains"}
    anchors = [inputs.locate_source(path, project, ps.userdata(), role="main")]
    prints = [_module("core.inputs.model").SourcePrint(
        _module("core.hashing").sha256_file(path), size=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns)]
    request = reader.request(
        reader.kinds[0], gis_store.source_declarations(reader.id, crs, vertical, settings),
        dict(zip(inputs.reader_roles(anchors), [path], strict=True)), settings)
    spec = gis_store.source_input(
        reader.id, DOMAINS_NAME, files=anchors, file_prints=prints,
        digest=_module("core.content.readers").read_content(reader, request), crs=crs,
        vertical=vertical, settings=settings)
    copies = folder / "copia"
    copies.mkdir()
    read = vector.read_layer(vector.copy_source(path, copies), DOMAINS_LAYER)
    handle = _module("core.provenance.operations").begin_operation(
        project, _module("gis.provenance").IMPORT_VECTOR, settings={"nombre": DOMAINS_NAME},
        executor="blender")
    with gis_store.ResultWriter(project, handle) as out:
        out.declare_input(spec)
        out.domains(DOMAINS_NAME, vector.domains_from_features(read)[0])
        (record,) = out.commit(message=REASON)
    return record.name


def _key(unit: str, component: str | None, what: str) -> str:
    params = _module("reserves.params")
    if what == "density":
        return params.density_key(unit, component)
    if what == "swell":
        return params.swell_key(unit, component)
    assert component is not None
    return params.percent_key(unit, component)


def use_column(project: Any, units_count: int) -> None:
    """La columna de ``units_count`` unidades de §2.2 (``res_perf.column_units``) guardada en el
    proyecto (``res.edit_materials``) y los parámetros de sus unidades que aún no están
    (HIPÓTESIS, sintéticos)."""
    materials = _module("reserves.materials")
    surface = _module("reserves.surfaces").SurfaceRef

    def ref(label: str | None) -> Any:
        return None if label is None else surface(dataset=_grid_name(label), label=label)

    units = data.column_units(units_count)
    column = materials.MaterialColumn(tuple(
        materials.Unit(spec.code, spec.name, spec.kind, spec.role, spec.state, ref(spec.base),
                       ref(spec.thickness),
                       tuple(materials.Component(item.code, item.name, item.role)
                             for item in spec.components))
        for spec in units))
    handle = _module("core.provenance.operations").begin_operation(
        project, _module("reserves.provenance").EDIT_MATERIALS,
        settings={"units": len(column.units)}, executor="blender")
    _module("reserves.store").save_materials(project, handle, column)
    store = _module("core.params").ParameterStore(project)
    with project.write_transaction() as conn:
        for unit, component, what, value in data.parameter_values(units):
            key = _key(unit, component, what)
            if store.get(key, conn=conn) is None:
                store.create(conn, key, value, **GIVEN)


@dataclasses.dataclass
class Built:
    """Un proyecto de §2.2 (:func:`build`): su carpeta, el uid de V01, la altura de las rodajas,
    la capa de dominios y los uid de la partida y la final."""

    root: Path
    version_uid: str
    bench_m: float
    domains: str
    start_uid: str
    final_uid: str


def build(parent: Path, sources: Path, labels: Sequence[str]) -> Built:
    """Un proyecto nuevo en ``parent`` con V01, las rejillas ``labels`` y la capa de dominios
    (su GeoPackage, en ``sources``), abierto en la sesión con su comprobación de apertura
    hecha y V01 activa (:func:`attach`)."""
    core = _module("core.project")
    ps = _module("bl.scene.project_session")
    parent.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)
    settings = core.ProjectSettings(**settings_values(window=data.WINDOW, grid_step_m=data.STEP))
    project = core.create_project(parent, settings, ps.session(), ps.userdata()).project
    with project.write_transaction() as conn:
        version, _revision = _module("core.versions.store").create_version(
            conn, project, feature="rnf", title="Rendimiento", reason=REASON)
    project.refresh_header()
    height = _write_grids(project, labels)
    domains = _import_domains(project, sources)
    registry = _module("core.datasets.registry")
    with project.read() as conn:
        start, final = (registry.get(conn, _grid_name(label)).uid
                        for label in (data.START, data.FINAL))
    built = Built(Path(project.root), version.uid, height, domains, start, final)
    attach(project, built)
    return built


def attach(project: Any, built: Built) -> Any:
    """Deja ``project`` en la sesión (con su comprobación de apertura, que en ``-b`` no corre
    sola) y V01 activa."""
    ps = _module("bl.scene.project_session")
    session = _module("bl.ops.core_provenance")
    ps.attach(project)
    for _ in range(MAX_EVENTS):
        if session.check_tick() is None:
            break
    ps.take_notices()
    assert bpy.ops.geoblender.core_set_active_version(version_uid=built.version_uid) == {
        "FINISHED"}
    return project


def reopen(built: Built) -> Any:
    """Vuelve a abrir el proyecto de ``built`` en la sesión."""
    core = _module("core.project")
    ps = _module("bl.scene.project_session")
    opened = core.open_project(built.root, ps.session(), ps.userdata(),
                               read_only=_module("bl.ops.core_provenance").read_only_dirs())
    return attach(opened.project, built)


def rows(sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with _module("bl.scene.project_session").current().read() as conn:
        return conn.execute(sql, args).fetchall()


def table_rows(name: str) -> int:
    """Las filas de la tabla viva ``name`` (``res_vol_…`` o ``res_ton_…``)."""
    ((locator,),) = rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current'",
                         name)
    return int(rows(f'SELECT count(*) FROM "{locator}"')[0][0])


# --- Las llamadas del hilo de Blender ------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Call:
    """Una llamada del hilo de Blender: qué era, lo que tardó, las fases de los pasos que dio, si
    fue mientras se cubica, lo que esperó en ella a la red (``waits``, por clase de
    ``tests.support.netwaits``) y las transacciones finales que hubo dentro (``commits``: el tipo
    de su operación, lo que tardó y lo que esperó en ella a la red)."""

    what: str
    seconds: float
    phases: str = ""
    cubicating: bool = True
    waits: tuple[tuple[str, float], ...] = ()
    commits: tuple[tuple[str, float, float], ...] = ()

    @property
    def waited(self) -> float:
        return sum(seconds for _kind, seconds in self.waits)

    @property
    def own(self) -> float:
        """Lo que hace Geoblender en la llamada: su duración sin sus esperas de la red."""
        return self.seconds - self.waited

    @property
    def transaction(self) -> float:
        """Lo que hace Geoblender en sus transacciones finales (sin sus esperas de la red)."""
        return sum(seconds - waited for _op, seconds, waited in self.commits)

    @property
    def budgeted(self) -> float:
        """Lo que cuenta frente a :data:`CALL_BUDGET_S`: lo que hace Geoblender sin la
        transacción final (medida aparte, plan R4)."""
        return self.own - self.transaction

    def text(self) -> str:
        """«qué era (fases)», con sus transacciones finales y sus esperas de la red."""
        parts = [self.what + (f" ({self.phases})" if self.phases else "")]
        parts += [f"transacción final de {op} {ms(seconds)} ms"
                  + (f" ({ms(seconds - waited)} ms sin sus esperas de la red)"
                     if waited >= 0.0005 else "")
                  for op, seconds, waited in self.commits]
        if self.waited >= 0.0005:
            parts.append("esperas de la red " + ", ".join(
                f"{kind} {ms(seconds)} ms" for kind, seconds in self.waits if seconds >= 0.0005))
        return "; ".join(parts)


class Recorder:
    """Mide cada llamada del hilo de Blender (:meth:`call`) con lo que esperó a la red
    (``waits``, un ``netwaits.NetworkWaits`` activo, o ``None`` en disco local) y el
    ``ResultWriter.commit`` de ``reserves.store`` que hubo dentro, mientras está activo
    (``with``)."""

    def __init__(self, waits: netwaits.NetworkWaits | None = None) -> None:
        self.waits = waits
        self.calls: list[Call] = []
        self._commits: list[tuple[str, float, float]] = []
        self._stack = ExitStack()

    def __enter__(self) -> Recorder:
        writer = _module("reserves.store").ResultWriter
        self._stack.enter_context(mock.patch.object(writer, "commit", self._timed(writer.commit)))
        return self

    def __exit__(self, *exc: object) -> None:
        self._stack.close()

    def _waited(self) -> float:
        return 0.0 if self.waits is None else sum(self.waits.totals.values())

    def _timed(self, real: Callable[..., Any]) -> Callable[..., Any]:
        recorder = self

        def commit(writer: Any, *args: Any, **kwargs: Any) -> Any:
            before = recorder._waited()
            started = time.perf_counter()
            try:
                return real(writer, *args, **kwargs)
            finally:
                recorder._commits.append((writer.handle.op_type, time.perf_counter() - started,
                                          recorder._waited() - before))

        return commit

    def call(self, what: str, function: Callable[..., Any], *args: Any,
             phases: Callable[[], str] | None = None, cubicating: bool = True,
             **kwargs: Any) -> Any:
        """``function(*args, **kwargs)`` como una llamada del hilo de Blender, medida."""
        self._commits = []
        if self.waits is not None:
            self.waits.begin()
        started = time.perf_counter()
        result = function(*args, **kwargs)
        seconds = time.perf_counter() - started
        waits = () if self.waits is None else tuple(self.waits.take().items())
        self.calls.append(Call(what, seconds, "" if phases is None else phases(), cubicating,
                               waits, tuple(self._commits)))
        return result


@dataclasses.dataclass(frozen=True)
class Run:
    """Una orden medida: sus llamadas, lo que tardó de Intro al final y la orden terminada."""

    calls: tuple[Call, ...]
    seconds: float
    operator: Any
    proposed: tuple[str, str, str]

    @property
    def cubicating(self) -> list[Call]:
        return [call for call in self.calls if call.cubicating]

    @property
    def worst(self) -> Call:
        """La llamada que más se acerca al presupuesto (:attr:`Call.budgeted`)."""
        return max(self.cubicating, key=lambda call: call.budgeted)

    @property
    def longest(self) -> Call:
        return max(self.cubicating, key=lambda call: call.seconds)

    @property
    def with_commits(self) -> list[Call]:
        return [call for call in self.cubicating if call.commits]

    def top(self, n: int = TOP_CALLS) -> list[Call]:
        return sorted(self.cubicating, key=lambda call: call.seconds, reverse=True)[:n]


def _surface(uid: str) -> SimpleNamespace:
    """Un objeto de la vista que muestra la rejilla ``uid`` (lo que lee ``invoke``)."""
    return SimpleNamespace(geoblender=SimpleNamespace(kind="DTM", dataset_uid=uid))


def run_order(built: Built, name: str, *, replace: bool = False,
              waits: netwaits.NetworkWaits | None = None) -> Run:
    """«Por unidad, fase y banco…» de ``name`` por las 8 unidades de la columna guardada, los 20
    dominios y las rodajas de ``built``, como desde la interfaz (véase el módulo), con cada
    llamada del hilo de Blender medida."""
    commands = _module("bl.ui.commands")
    ui_provenance = _module("bl.ui.provenance")
    cls = commands.registered_class(BREAKDOWN)
    typed = {"domains_layer": built.domains, "domains_field": data.FIELD,
             "bench_height": number(built.bench_m, 1), "bench_anchor": number(ANCHOR_M, 0),
             "by_units": True, "name": name}
    names = frozenset(typed)
    fake = operator_self(cls, report=lambda kind, text: None,
                         properties=SimpleNamespace(is_property_set=names.__contains__),
                         **{**DIALOG, **typed})
    manager = SimpleNamespace(invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"}),
                              invoke_confirm=mock.Mock(return_value={"RUNNING_MODAL"}))
    context = SimpleNamespace(window_manager=manager, window=None, scene=bpy.context.scene,
                              selected_objects=[_surface(built.final_uid),
                                                _surface(built.start_uid)])
    gc.collect()
    with Recorder(waits) as recorder:
        opened = recorder.call("abrir el diálogo", cls.invoke, fake, context, None,
                               cubicating=False)
        assert opened == {"RUNNING_MODAL"}, opened
        recorder.call("dibujar el diálogo", cls.draw, fake, bpy.context, cubicating=False)
        values = {field: getattr(fake, field) for field in ORDER_FIELDS}
        started = time.perf_counter()
        result = recorder.call("Intro: comprobar y empezar",
                               bpy.ops.geoblender.res_compute_volume_breakdown, "EXEC_DEFAULT",
                               in_steps=True, replace=replace, **values)
        assert result == {"RUNNING_MODAL"}, result
        (operator,) = [op for op in bpy.context.window.modal_operators
                       if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        clock, due = 0.0, ui_provenance.INDICATOR_TICK_S
        for event in range(MAX_EVENTS):
            log = operator.progress_log
            before = len(log)

            def phases(log: list[Any] = log, before: int = before) -> str:
                return ",".join(dict.fromkeys(str(entry[1]) for entry in log[before:]))

            state = recorder.call(f"evento {event + 1} del modal", operator.modal, bpy.context,
                                  TIMER, phases=phases)
            clock += recorder.calls[-1].seconds + TIMER_INTERVAL_S
            if clock >= due:
                interval = recorder.call("tic de los indicadores de la procedencia",
                                         ui_provenance.indicator_tick)
                due = clock + (ui_provenance.INDICATOR_TICK_S if interval is None else interval)
            if state != {"RUNNING_MODAL"}:
                break
        else:
            raise AssertionError(f"«{name}» no acaba")
        seconds = time.perf_counter() - started
    assert state == {"FINISHED"}, (state, operator.report_log)
    return Run(tuple(recorder.calls), seconds, operator, (values["name"], values["start"],
                                                          values["final"]))


def _calls_line(run: Run, where: str, *, network_waits: bool) -> str:
    """Lo medido de ``run`` (véase el módulo), para la línea de la cifra."""
    worst = run.worst
    longest = run.longest
    intro = next(call for call in run.calls if call.what.startswith("Intro"))
    events = sum(call.what.startswith("evento") for call in run.calls)
    ticks = sum(call.what.startswith("tic") for call in run.calls)
    commits = "; ".join(f"{call.text()}: la llamada {ms(call.seconds)} ms"
                        + (f" ({ms(call.own)} ms sin sus esperas de la red)" if network_waits
                           else "")
                        for call in run.with_commits)
    dialog = [call for call in run.calls if not call.cubicating]
    top = "; ".join(f"{ms(call.seconds)} ms ({call.text()})" for call in run.top())
    own = "sin sus esperas de la red ni la transacción final" if network_waits else \
        "sin la transacción final"
    return (f"{where} ({MACHINE}): de Intro al final {number(run.seconds, 2)} s en "
            f"{len(run.cubicating)} llamadas del hilo de Blender (Intro, {events} eventos del "
            f"modal y {ticks} tics de los indicadores); Intro {ms(intro.seconds)} ms; la más "
            f"larga {ms(longest.seconds)} ms ({longest.text()}); {own}, la peor "
            f"{ms(worst.budgeted)} ms ({worst.text()}); "
            f"presupuesto {number(CALL_BUDGET_S, 1)} s de lo que hace Geoblender en cada llamada"
            f"{', sin sus esperas de la red (aparte, sin presupuesto)' if network_waits else ''}"
            f"; la transacción final, aparte (plan R4): {commits}; las {TOP_CALLS} más largas: "
            f"{top}; antes de cubicar, "
            + ", ".join(f"{call.what} {ms(call.seconds)} ms" for call in dialog))


def _warn_slow(run: Run, where: str) -> None:
    """Los avisos de lo que pasa de 0,2 s: lo que no es la transacción final (falla) y la
    transacción final (para Samuel, R4)."""
    over = [call for call in run.cubicating if call.budgeted > CALL_BUDGET_S]
    if over:
        report(f"Aviso RNF-011-04 ({where}): {len(over)} llamadas de más de "
               f"{number(CALL_BUDGET_S, 1)} s sin la transacción final: "
               + "; ".join(f"{ms(call.budgeted)} ms ({call.text()})" for call in over))
    held = [call for call in run.with_commits
            if call.own > CALL_BUDGET_S >= call.budgeted]
    if held:
        report(f"Aviso RNF-011-04 ({where}; plan R4, la cifra para Samuel): la transacción final "
               f"deja {len(held)} llamadas de más de {number(CALL_BUDGET_S, 1)} s: "
               + "; ".join(f"{ms(call.own)} ms ({call.text()})" for call in held))


class _ResCase(unittest.TestCase):
    """La extensión habilitada (sin importarla otra vez: ``blender_ext.release``), el idioma en
    español y ``wm.call_panel`` sustituido; el proyecto de §2.2 en disco local, el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.res_ops = _module("bl.ops.res")
        cls.panels = _module("bl.ui.res_panels")
        cls.ps = _module("bl.scene.project_session")
        cls.call_panel = cls.enterClassContext(mock.patch.object(
            cls.res_ops, "_call_panel", return_value={"FINISHED"}))

    def operations(self, name: str, op_type: str) -> list[tuple[str, str, str | None]]:
        """Las ``op_type`` de la cubicación ``name``: uid, estado y a quién sustituye."""
        found = rows("SELECT uid, status, supersedes_uid, settings FROM gb_operation WHERE "
                     "op_type = ? ORDER BY started_at, uid", op_type)
        return [(uid, status, old) for uid, status, old, settings in found
                if json.loads(settings).get("name") == name]

    def check_run(self, run: Run, name: str, *, replaced: int = 0) -> None:
        """Lo que deja la orden: lo que propuso el diálogo (la partida, la de mayor cota media),
        ``res.volume`` y ``res.tonnage`` hechas (la última, sustituyendo a la anterior si
        ``replaced``), las 8 unidades, los 20 dominios y las 30 rodajas, y la ventana pedida."""
        self.assertEqual(run.proposed, (name, _grid_name(data.START), _grid_name(data.FINAL)))
        for op_type in ("res.volume", "res.tonnage"):
            found = self.operations(name, op_type)
            self.assertEqual(len(found), replaced + 1, op_type)
            self.assertEqual(found[-1][1], "done", op_type)
            if replaced:
                self.assertEqual(found[-1][2], found[-2][0], op_type)
        kernel = run.operator._volume.result.kernel
        self.assertEqual((kernel.domains, kernel.units, kernel.bounds.size - 1),
                         (data.DOMAINS, data.UNITS_BREAKDOWN, data.BENCHES))
        self.assertEqual({op for call in run.calls for op, _s, _w in call.commits},
                         {"res.volume", "res.tonnage"})
        self.call_panel.assert_called_with(self.panels.VOLUMETRICS_PANEL)


class _Local:
    """El proyecto de §2.2 en disco local, uno para todo el módulo (se construye la primera vez
    que se pide: unos 10 s), en la sesión."""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.made: Built | None = None

    def built(self) -> Built:
        """El proyecto, abierto en la sesión (construido, si aún no lo está)."""
        if self.made is None:
            self.folder = Path(tempfile.mkdtemp(prefix="gb-011-t28-"))
            self.made = build(self.folder / "proyectos", self.folder / "fuentes",
                              data.labels(data.UNITS_TABLE))
        elif _module("bl.scene.project_session").current() is None:
            reopen(self.made)
        return self.made

    def restore(self) -> None:
        """Vuelve a abrirlo en la sesión, si ya se construyó."""
        if self.made is not None:
            self.built()

    def close(self) -> None:
        if self.folder is not None:
            remove_tree(self.folder)
        self.folder = self.made = None


_LOCAL = _Local()


def setUpModule() -> None:
    blender_ext.release()
    blender_ext.load_file()
    blender_ext.enable()
    i18n = _module("core.i18n")
    unittest.addModuleCleanup(i18n.set_language, i18n.language())
    i18n.set_language("es")


def tearDownModule() -> None:
    try:
        _module("bl.scene.project_session").close()
        _LOCAL.close()
    finally:
        blender_ext.load_file()
        blender_ext.release()


class CallsTest(_ResCase):
    """RNF-011-04 con el proyecto en disco local."""

    def test_breakdown_calls_on_local_disk(self) -> None:
        """RNF-011-04 (plan §7.3, R4; RF-011-07, RF-011-09, RF-011-12, RF-011-20, RF-011-25):
        «Por unidad, fase y banco…» con la columna de RNF-011-02 (8 unidades), los 20 dominios y
        30 rodajas, con sus toneladas encadenadas, como desde la interfaz y con el proyecto en
        disco local: en ninguna llamada del hilo de Blender (Intro, cada evento del modal y el
        tic de los indicadores), lo que hace Geoblender sin la transacción final pasa de 0,2 s;
        la transacción final (la de ``res.volume`` y la de ``res.tonnage``), aparte. Con un
        nombre nuevo y repitiéndolo para sustituirla (D-30)."""
        built = _LOCAL.built()
        project = self.ps.current()
        use_column(project, data.UNITS_BREAKDOWN)
        name = "Reparto local"
        first = run_order(built, name)
        self.check_run(first, name)
        again = run_order(built, name, replace=True)
        self.check_run(again, name, replaced=1)
        volume, tonnage = (f"res_{family}_reparto_local" for family in ("vol", "ton"))
        tables = f"{count(table_rows(volume))} + {count(table_rows(tonnage))} filas"
        for run, how in ((first, "nueva"), (again, "sustituyendo la anterior (D-30)")):
            where = f"con el proyecto en disco local, {how}"
            report(f"RNF-011-04: «Por unidad, fase y banco…» con {data.UNITS_BREAKDOWN} "
                   f"unidades (una compuesta y dos antrópicas), {data.DOMAINS} dominios y "
                   f"{data.BENCHES} rodajas de {number(built.bench_m, 1)} m sobre "
                   f"{count(data.COLS * data.ROWS)} celdas, con sus toneladas ({tables}), "
                   + _calls_line(run, where, network_waits=False)
                   + f"; {free_space(built.root)}")
            _warn_slow(run, where)
        for run in (first, again):
            self.assertLessEqual(run.worst.budgeted, CALL_BUDGET_S, run.worst.text())


@requires(network.NET, network.NET_HINT)
class NetworkTest(_ResCase):
    """RNF-011-04 con el proyecto en la carpeta de pruebas de la red (``Z:``): un proyecto propio
    en una subcarpeta temporal (borrada al terminar) y los datos de usuario en disco local; al
    terminar, vuelve el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ps.close()
        cls.addClassCleanup(_LOCAL.restore)  # lo último: los de la clase, al revés
        remote = cls.enterClassContext(network.net_tmp("gb-011-t28-"))
        local = Path(tempfile.mkdtemp(prefix="gb-011-t28-red-"))
        cls.addClassCleanup(remove_tree, local)
        cls.addClassCleanup(cls.ps.close)  # lo primero: antes de borrar su carpeta
        cls.remote = remote
        cls.built = build(remote / "proyectos", local / "fuentes",
                          data.labels(data.UNITS_BREAKDOWN))

    def test_breakdown_calls_on_the_network(self) -> None:
        """RNF-011-04 en ``Z:`` (como RNF-005-06 y RNF-009-05): lo mismo con el proyecto en la
        red; lo que hace Geoblender en cada llamada del hilo de Blender, sin sus esperas de la
        red (medidas en la llamada y anotadas aparte, sin presupuesto) ni la transacción final
        (aparte), no pasa de 0,2 s."""
        project = self.ps.current()
        self.assertTrue(project.is_network, "el proyecto de la carpeta de la red")
        use_column(project, data.UNITS_BREAKDOWN)
        name = "Reparto en la red"
        found = []
        for replace in (False, True):
            with netwaits.NetworkWaits(self.remote, projects=[project]) as waits:
                found.append((run_order(self.built, name, replace=replace, waits=waits),
                              waits.longest))
            self.check_run(found[-1][0], name, replaced=int(replace))
        for (run, longest), how in zip(found, ("nueva", "sustituyendo la anterior (D-30)"),
                                       strict=True):
            where = f"con el proyecto en la carpeta de pruebas de la red, {how}"
            report(f"RNF-011-04: «Por unidad, fase y banco…» con {data.UNITS_BREAKDOWN} "
                   f"unidades, {data.DOMAINS} dominios y {data.BENCHES} rodajas sobre "
                   f"{count(data.COLS * data.ROWS)} celdas, con sus toneladas, "
                   + _calls_line(run, where, network_waits=True)
                   + f"; la espera de la red más larga, {longest[0]} {ms(longest[1])} ms; "
                   f"{free_space(self.built.root)}")
            _warn_slow(run, where)
            waited = [call for call in run.cubicating
                      if call.seconds > CALL_BUDGET_S >= call.own]
            if waited:
                report(f"Nota RNF-011-04 ({where}): {len(waited)} llamadas de más de "
                       f"{number(CALL_BUDGET_S, 1)} s solo por sus esperas de la red (se "
                       "anotan, sin presupuesto): "
                       + "; ".join(f"{ms(call.seconds)} ms ({call.text()})" for call in waited))
        for run, _longest in found:
            self.assertLessEqual(run.worst.budgeted, CALL_BUDGET_S, run.worst.text())


class PanelTest(_ResCase):
    """RNF-011-05: la ventana de la cubicación con la tabla de 20 dominios × 30 rodajas × 10
    unidades, en disco local."""

    TABLE = "Tabla del panel"
    OTHER = "Sin repartos"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        built = _LOCAL.built()
        project = cls.ps.current()
        use_column(project, data.UNITS_TABLE)
        cls.panels.refresh_choices(project, built.version_uid)
        start, final = _grid_name(data.START), _grid_name(data.FINAL)
        assert bpy.ops.geoblender.res_compute_volume_breakdown(
            name=cls.TABLE, start=start, final=final, domains_layer=built.domains,
            domains_field=data.FIELD, bench_height=number(built.bench_m, 1),
            bench_anchor=number(ANCHOR_M, 0), by_units=True) == {"FINISHED"}
        assert bpy.ops.geoblender.res_compute_volume_between_surfaces(
            name=cls.OTHER, start=start, final=final, difference_grid=False) == {"FINISHED"}
        cls.table_rows = (table_rows("res_vol_tabla_del_panel"),
                          table_rows("res_ton_tabla_del_panel"))

    def choose(self, name: str) -> float:
        """Pulsa ``name`` en la lista de la ventana (``cubication_index``); lo que tardó."""
        view = self.panels.view()
        index = [item.name for item in view.cubications].index(name)
        took, _ = _timed(lambda: setattr(view, "cubication_index", index))
        self.assertEqual(view.rows_of, name)
        return took

    def test_panel_with_six_thousand_rows(self) -> None:
        """RNF-011-05 (RF-011-23; plan §5.5, D-27, D-37): la ventana de la cubicación con la tabla
        de 20 dominios × 30 rodajas × 10 unidades (6 000 volúmenes por dominio, rodaja y
        unidad) y sus toneladas: abrirla (la orden de la ventana, el temporizador que pide su
        dibujo tras cubicar y pulsarla en la lista) y cada cambio de filtro (dominio, banco,
        unidad, «cualquiera», las relaciones y vuelta al total) ≤ 0,5 s; cada redibujo (el panel
        con la fila elegida y las filas visibles de sus dos listas) ≤ 5 ms."""
        panels = self.panels
        view = panels.view()
        table = _module("reserves.table")
        times: dict[str, list[float]] = {}
        for _ in range(OPENINGS):
            gc.collect()
            took, result = _timed(lambda: bpy.ops.geoblender.res_show_volumetrics(
                "EXEC_DEFAULT", cubication=self.TABLE))
            self.assertEqual(result, {"FINISHED"})
            times.setdefault("abrir la ventana (la orden)", []).append(took)
        self.call_panel.assert_called_with(panels.VOLUMETRICS_PANEL)
        self.assertEqual(view.rows_of, self.TABLE)
        shown = panels._VOLUMETRICS.table
        combos = {(row[0], row[1], row[2]) for row in shown.rows
                  if row[3] == "volume_m3" and row[2] is not None and row[1] is not None
                  and row[0] not in (table.ALL_DOMAINS, table.OUTSIDE_DOMAINS)}
        self.assertEqual(len(combos), data.DOMAINS * data.BENCHES * data.UNITS_TABLE)
        for _ in range(OPENINGS):  # tras cubicar: la orden lo deja elegido y la ventana lo lee
            panels.show_later(self.TABLE)
            gc.collect()
            took, interval = _timed(panels.volumetrics_tick)
            self.assertIsNone(interval)
            self.assertEqual(view.rows_of, self.TABLE)
            times.setdefault("abrirla tras cubicar (su temporizador)", []).append(took)
        for _ in range(OPENINGS):  # pulsarla en la lista, viniendo de otra
            self.choose(self.OTHER)
            gc.collect()
            times.setdefault("pulsarla en la lista", []).append(self.choose(self.TABLE))

        filters = (("un dominio", "domain_filter", "D3"), ("un banco", "bench_filter", "B10"),
                   ("una unidad", "unit_filter", "U4"),
                   ("cualquier dominio", "domain_filter", panels.FILTER_ANY),
                   ("cualquier banco", "bench_filter", panels.FILTER_ANY),
                   ("cualquier unidad", "unit_filter", panels.FILTER_ANY),
                   ("las relaciones", "quantities", "RATIOS"),
                   ("todos los datos", "quantities", "ALL"))
        for label, prop, value in filters:
            gc.collect()
            took, _ = _timed(lambda prop=prop, value=value: setattr(view, prop, value))
            times[f"filtrar por {label}"] = [took]
        passed = len(view.rows) + view.rows_more
        self.assertEqual(len(view.rows), panels.ROWS_SHOWN)
        self.assertGreater(view.rows_more, 0)
        self.assertEqual(len(panels.domain_filter_items(view, None)), 2 + data.DOMAINS + 1)
        self.assertEqual(len(panels.bench_filter_items(view, None)), 2 + data.BENCHES)
        self.assertEqual(len(panels.unit_filter_items(view, None)), 2 + data.UNITS_TABLE)

        self.assertFalse(panels.volumetrics_is_old(self.ps.current(), _LOCAL.built().version_uid))
        layout = NullLayout()
        rows_list = panels.GEOBLENDER_UL_res_rows
        cubications_list = panels.GEOBLENDER_UL_res_cubications
        visible = [view.rows[index] for index in range(panels.TABLE_ROWS)]
        listed = [view.cubications[index]
                  for index in range(min(panels.CUBICATION_ROWS, len(view.cubications)))]
        context = bpy.context

        def redraw() -> None:
            panels.draw_volumetrics(layout, context, popover=True)
            for row in visible:
                rows_list.draw_item(None, context, layout, view, row, 0, view, "row_index")
            for item in listed:
                cubications_list.draw_item(None, context, layout, view, item, 0, view,
                                           "cubication_index")

        draws = [_timed(redraw)[0] for _ in range(DRAWS)]
        self.assertFalse(bpy.app.timers.is_registered(panels.volumetrics_tick))
        worst = max(max(found) for found in times.values())
        report(
            f"RNF-011-05: la ventana de la cubicación con la tabla de {data.DOMAINS} dominios × "
            f"{data.BENCHES} rodajas × {data.UNITS_TABLE} unidades ({count(len(combos))} "
            f"volúmenes por dominio, rodaja y unidad; {count(len(shown.rows))} filas presentadas "
            f"de {count(self.table_rows[0])} + {count(self.table_rows[1])} de sus tablas; con "
            f"«cualquiera» en los tres filtros, {count(passed)} filas, de las que se presentan "
            f"{count(panels.ROWS_SHOWN)}; {MACHINE}): "
            + ", ".join(f"{label} {number(max(found))} s"
                        + (f" (mediana {number(statistics.median(found))} de {len(found)})"
                           if len(found) > 1 else "")
                        for label, found in times.items())
            + f" (presupuesto {number(PANEL_BUDGET_S, 1)} s); redibujar el panel con "
            f"{panels.TABLE_ROWS} filas de la tabla y {len(listed)} de la lista, {DRAWS} veces: "
            f"mediana {ms(statistics.median(draws), 3)} ms, máximo {ms(max(draws), 3)} ms "
            f"(presupuesto {ms(REDRAW_BUDGET_S, 0)} ms); {free_space(_LOCAL.built().root)}")
        self.assertLessEqual(worst, PANEL_BUDGET_S)
        self.assertLessEqual(max(draws), REDRAW_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
