# SPDX-License-Identifier: GPL-3.0-or-later
"""Las envolventes y el escalonado dentro de Blender (spec 013, T31; RNF-013-05 y RNF-013-07; plan 013
§7.3 y el riesgo R4, ``tests/rendimiento/blender``).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py --
--carpeta tests/rendimiento/blender --patron "perf_design.py"``). Cada prueba imprime su cifra en
una línea «RNF-013-nn: …» con el equipo y el espacio libre del disco, y la compara con su
presupuesto, sin relajarlo.

**Datos** (plan §2.2; ``tests/support/design_data.py``: se generan aquí con la misma semilla que las
pruebas de ``tests/rendimiento/des``, no se versionan y se borran al terminar): un proyecto nuevo
(EPSG:25830 + EPSG:5782) con V01 y V02, la rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M), las 500
restricciones de unos 100.000 vértices de la 012 declaradas con ``core.edit_constraints``, los 20
sectores (franjas del perímetro) con su búsqueda de intocables cerrada, el terreno, las semillas en
anillo (5,3 mil celdas) y un disco de unas 100.000 semillas como rejillas del proyecto, los diez
perfiles de banco (``geoblender.des_save_bench_profile``) y los dos taludes impuestos
(``geoblender.des_set_sector_slope``) y las máscaras de V01 al día. Todo con la extensión habilitada,
como una persona.

- **RNF-013-05** (:class:`PreviewTest`): activar la vista previa (``geoblender.des_toggle_preview``)
  con las 100.000 semillas, los 20 sectores y las 500 restricciones: la orden y los pasos de su
  temporizador hasta que está construida (con los 5 ms de espera de cada uno) ≤ 1 s (mediana de 5,
  como el resto de la 013; la peor se anota con un aviso si lo pasa), y cada redibujo
  (los lotes de las restricciones y de los sectores, los puntos de las semillas, los nombres, la
  leyenda y el resumen) ≤ 5 ms, con ``gpu`` y ``blf`` sustituidos (solo el Python de Geoblender, como
  hace la 012: la GPU de verdad y el color son de la comprobación manual M1).
- **RNF-013-07** (:class:`CallsTest`): «Envolventes y escalonado…» (``geoblender.des_compute_envelope``),
  la orden real, como desde la interfaz: Intro (``execute`` por ``bpy.ops``, en pasos) y cada evento del
  temporizador de su modal hasta que termina, con el tic de los indicadores de la procedencia cuando le
  toca (el temporizador que corre mientras tanto); y «Crear» (la misma orden con ``confirm``), que es la
  transacción final. Cada llamada del hilo de Blender se mide: lo que hace Geoblender en ella, **sin la
  transacción final** (``DesignWriter.commit``: la operación, los temporales movidos, las tablas y las
  cifras en una transacción que no se trocea; plan R4), ≤ 0,2 s; la transacción, medida aparte, se anota
  con la llamada en que ocurre (si pasa de 0,2 s, con un aviso: la cifra, para Samuel). Cuatro
  cálculos: la envolvente *chamfer* de pendiente constante desde las semillas en anillo; la envolvente
  por los 20 sectores (diez perfiles y dos taludes impuestos) con su escalonado en corte, las dos
  órdenes con su «Calcular» y su «Crear»; la euclídea exacta; y toda la superficie como semillas (la
  preparación con más semillas posible), solo «Calcular». **Cada llamada se mide en CPU del proceso
  (``time.process_time()``, que no cuenta lo que gastan otros programas: ``docs/trampas.md`` §4) y en
  pared**; el presupuesto se exige a la CPU y la pared se anota con un aviso si lo pasa (se repite con
  el equipo en reposo). La resolución del reloj de CPU de Windows es de unos 16 ms.
- **En la red** (:class:`NetworkTest`; recurso «red» de ``tests.support.network``: con
  ``GEOBLENDER_NET_TEST_DIR``, a mano; sin ella, se omite): lo de RNF-013-07 y el cálculo completo de
  RNF-013-03 (≤ 25 s: de «Calcular» de la envolvente a las cifras registradas del escalonado, con la
  escritura de las tres rejillas con su hash y las dos transacciones finales) con el proyecto (el
  límite legal, el perímetro, los sectores y las rejillas: sin las 500 restricciones) en una subcarpeta
  temporal propia de la carpeta de pruebas de ``Z:`` (borrada al terminar) y los datos de usuario en
  disco local; las esperas de la red de cada llamada (abrir, leer, escribir, forzar y cerrar ficheros
  del proyecto, sus metadatos y el COMMIT de cada transacción) se miden con ``tests.support.netwaits``
  y se anotan aparte, sin presupuesto (como RNF-011-04, RNF-012-06 y RNF-009-05): el presupuesto de cada
  llamada es el de lo que hace Geoblender. Escribe unos 150 MB en la red. **Ojo**: en el PC de
  referencia la variable está definida en el usuario y este módulo, lanzado tal cual, también corre la
  de la red (``docs/trampas.md`` §7); para medir solo en local, sin ella:
  ``env -u GEOBLENDER_NET_TEST_DIR …`` (Git Bash) o ``Remove-Item Env:GEOBLENDER_NET_TEST_DIR``
  (PowerShell).

En ``blender -b`` no corren ni el bucle de eventos ni los temporizadores: la prueba hace de ventana (un
evento del temporizador del modal cada vez) y de temporizador; la confirmación de «Calcular»
(``_ask_confirmation``, que relanza la orden con un temporizador) se sustituye.
"""

from __future__ import annotations

import dataclasses
import gc
import importlib
import json
import statistics
import tempfile
import time
import unittest
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import bpy
import numpy as np
from mathutils import Matrix

from tests.rendimiento.blender import perf_constraints as pc
from tests.rendimiento.blender import perf_res as base
from tests.support import blender_ext, netwaits, network
from tests.support import constraints_data as cdata
from tests.support import design_data as ddata
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.resources import requires
from tests.support.trees import remove_tree

CALL_BUDGET_S = 0.2  # RNF-013-07: lo que hace Geoblender en cada llamada del hilo de Blender
ACTIVATE_BUDGET_S = 1.0  # RNF-013-05: activar la vista previa
REDRAW_BUDGET_S = 0.005  # RNF-013-05: cada redibujo
DESIGN_NETWORK_BUDGET_S = 25.0  # RNF-013-03 en Z:: el cálculo completo
ACTIVATIONS = 5  # veces que se activa (la peor cuenta)
REDRAWS = 300  # redibujos medidos
TOP_CALLS = 5
TICK_WAIT_S = 0.005  # bl.draw.design.TICK_INTERVAL_S (lo comprueba la prueba)
TIMER = pc.TIMER
TIMER_INTERVAL_S = pc.TIMER_INTERVAL_S
MAX_TICKS = 20_000
REGION = (1920, 1080)
"""La región de la Vista 3D del redibujo: la de la barra a 1920 px de las comprobaciones manuales."""

COMPUTE = "geoblender.des_compute_envelope"
TOGGLE = "geoblender.des_toggle_preview"
VIEW_PROPERTY = "geoblender_design"
REASON = "Rendimiento de las envolventes y el escalonado (spec 013, T31)"
PERSON = ddata.PERSON
SOURCE = "Valores sintéticos de prueba"
CLOSED_AT = "2026-11-04T10:00:00Z"
SEARCH_DISTANCE_M = 25.0
NO_ZONE = "none"
LABELS = ("partida", "anillo", "disco")
"""Las rejillas del proyecto de escala: el terreno, las semillas en anillo y el disco de la vista previa."""

report = base.report
number = base.number
ms = base.ms
count = base.count
free_space = base.free_space
MACHINE = base.MACHINE
CELLS = ddata.CELLS


def _module(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión."""
    return importlib.import_module(f"{module_name()}.{name}")


def view() -> Any:
    """La vista de las ventanas del diseño (``WindowManager.geoblender_design``)."""
    return getattr(bpy.context.window_manager, VIEW_PROPERTY)


def profile_name(profile: ddata.PerfProfile) -> str:
    """El nombre con que se guarda un perfil de :data:`ddata.PROFILES` (su código en mayúsculas)."""
    return profile.code.upper()


# --- El proyecto de §2.2, con la extensión ------------------------------------------------------


@dataclasses.dataclass
class Built:
    """Un proyecto de escala (:func:`build`): su carpeta, el uid y el código de V01, el nombre del dato de
    cada rejilla (:data:`LABELS`) y los vértices de las restricciones."""

    root: Path
    version_uid: str
    version_code: str
    start: str
    ring: str
    disc: str
    constraints: int
    vertices: int


def _ring(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, de un rectángulo de coordenadas absolutas."""
    return np.array([(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)],
                    dtype=np.float64)


def declare_constraints(project: Any, wanted: int) -> int:
    """Las primeras ``wanted`` restricciones de §2.2 (``constraints_data.build_specs``: el límite legal, el
    perímetro y, luego, las de la 012) escritas con ``core.edit_constraints`` y sus parámetros dados de alta
    en el proyecto, en una transacción; los vértices que suman."""
    params, cparams = _module("core.params"), _module("core.constraints.params")
    specs = cdata.build_specs()[:wanted]
    rows = pc.constraint_rows()[:wanted]
    edited = _module("core.constraints.provenance").edit_constraints(
        project, rows, srs_id=project.record.crs_epsg)
    codes = {str(item.name): str(item.code) for item in edited.constraints}
    store = params.ParameterStore(project)
    with project.write_transaction() as conn:
        for spec in specs:
            for param, value in spec.params:
                store.create(conn, cparams.param_key(codes[spec.name], param), value,
                             kind="ADOPTADO" if isinstance(value, bool) else "HIPÓTESIS",
                             source=SOURCE, source_kind="document", decided_by=PERSON,
                             reason=REASON)
    return sum(len(spec.part) for spec in specs)


def declare_sectors(project: Any) -> None:
    """Los 20 sectores de §2.2 (``core_sector``, franjas del perímetro) y, de cada uno, su búsqueda de
    intocables cerrada con su huella: ningún sector queda pendiente."""
    cmodel, cstore = _module("core.constraints.model"), _module("core.constraints.store")
    begin = _module("core.provenance.operations").begin_operation
    srs = project.record.crs_epsg
    sectors = tuple(
        cmodel.Sector(f"sector{index:02d}".ljust(32, "0"), code, name,
                      (_ring(left, bottom, right, top),))
        for index, code, name, left, bottom, right, top in ddata.sector_boxes())
    handle = begin(project, "core.edit_constraints", settings={"count": 0}, executor="blender")
    with project.write_transaction() as conn:
        cstore.write_sectors(conn, sectors, srs_id=srs)
        handle.complete(conn, outputs=cstore.dataset_specs(crs_epsg=srs),
                        message="Sectores de rendimiento")
    with project.read() as conn:
        stored = cstore.read_sectors(conn)
    assert len(stored) == ddata.SECTORS, len(stored)
    for index, sector in enumerate(stored, start=1):
        handle = begin(project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = cmodel.SearchRecord(f"search{index:02d}".ljust(32, "0"), handle.uid, sector.code,
                                     cstore.sector_sha256(sector), SEARCH_DISTANCE_M, PERSON,
                                     CLOSED_AT)
        with project.write_transaction() as conn:
            cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cstore.dataset_specs(crs_epsg=srs),
                            message="Búsqueda de rendimiento")


def write_grids(project: Any) -> dict[str, str]:
    """Las rejillas de :data:`LABELS` como rejillas del proyecto (``gis.resample``, como las deja
    «Rejilla del proyecto desde un MDT»), en una operación; el nombre del dato de cada una."""
    gis_store = _module("gis.store")
    grid = _module("gis.grid").Grid(cdata.WEST, cdata.NORTH, cdata.STEP_M, cdata.STEP_M, cdata.COLS,
                                    cdata.ROWS)
    raster = _module("gis.raster").Raster
    crs, vertical = gis_store.project_references(project)
    library, library_version = _module("gis.crs").crs_library()
    handle = _module("core.provenance.operations").begin_operation(
        project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Rejillas de escala"},
        executor="blender")
    values = {"partida": ddata.terrain(), "anillo": ddata.ring_seeds(ddata.RING_HALF_WIDTH_M),
              "disco": ddata.preview_seeds()}
    with gis_store.ResultWriter(project, handle) as out:
        for label in LABELS:
            out.raster(label, raster(grid, values[label], crs, vertical))
        records = out.commit(software={library: library_version}, message=REASON)
    names = [str(record.name) for record in records]
    assert len(names) == len(LABELS), names
    return dict(zip(LABELS, names, strict=True))


def refresh_lists(project: Any) -> None:
    """Las listas de los diálogos (perfiles, sectores, superficies, zonas y capas), leídas de nuevo (un
    guion no abre el diálogo que las lee)."""
    panels = _module("bl.ui.des_panels")
    panels.fill_profiles(project)
    panels.fill_sectors(project)
    panels.refresh_choices(project)


def save_profiles_and_slopes(project: Any) -> None:
    """Los diez perfiles de banco (del proyecto) y los dos taludes impuestos (solo en V01) con las
    órdenes reales."""
    for profile in ddata.PROFILES:
        found = bpy.ops.geoblender.des_save_bench_profile(
            name=profile_name(profile), kind="ADOPTADO", source=SOURCE, decided_by=PERSON,
            reason=REASON, scope="PROJECT", height=f"{profile.height_m:g}",
            face=f"{profile.face_deg:g}", berm=f"{profile.berm_m:g}",
            anchor=f"{profile.anchor_m:g}")
        assert found == {"FINISHED"}, (profile.code, found)
    refresh_lists(project)
    for index, degrees in ddata.IMPOSED.items():
        found = bpy.ops.geoblender.des_set_sector_slope(
            code=ddata.sector_code(index), slope=f"{degrees:g}", kind="ADOPTADO", source=SOURCE,
            source_kind="PERSON", decided_by=PERSON, reason=REASON, scope="VERSION")
        assert found == {"FINISHED"}, (index, found)
    refresh_lists(project)


def build(parent: Path, constraints: int) -> Built:
    """Un proyecto nuevo en ``parent`` con V01 y V02, las primeras ``constraints`` restricciones de §2.2,
    los 20 sectores, las rejillas de :data:`LABELS`, los perfiles y los taludes impuestos, y las máscaras
    de V01 al día, abierto en la sesión con su comprobación de apertura hecha y V01 activa."""
    core = _module("core.project")
    ps = _module("bl.scene.project_session")
    parent.mkdir(parents=True, exist_ok=True)
    settings = core.ProjectSettings(**settings_values(window=cdata.window(),
                                                      grid_step_m=cdata.STEP_M))
    project = core.create_project(parent, settings, ps.session(), ps.userdata()).project
    versions = _module("core.versions.store")
    with project.write_transaction() as conn:
        first, _revision = versions.create_version(conn, project, feature="diseno",
                                                   title="Diseño", reason=REASON)
        versions.create_version(conn, project, feature="alternativa", title="Alternativa",
                                reason=REASON)
    project.refresh_header()
    vertices = declare_constraints(project, constraints)
    declare_sectors(project)
    names = write_grids(project)
    built = Built(Path(project.root), first.uid, first.code, names["partida"], names["anillo"],
                  names["disco"], constraints, vertices)
    base.attach(project, built)
    save_profiles_and_slopes(project)
    pc.ensure_masks(project, built)
    refresh_lists(project)
    return built


class _Local:
    """El proyecto de §2.2 en disco local, uno para todo el módulo (se construye la primera vez que se
    pide), en la sesión."""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.made: Built | None = None

    def built(self) -> Built:
        """El proyecto, abierto en la sesión (construido, si aún no lo está)."""
        if self.made is None:
            self.folder = Path(tempfile.mkdtemp(prefix="gb-013-t31-"))
            self.made = build(self.folder / "proyectos", cdata.COUNT)
        elif _module("bl.scene.project_session").current() is None:
            base.reopen(self.made)
            refresh_lists(_module("bl.scene.project_session").current())
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


def setUpModule() -> None:  # noqa: N802
    blender_ext.release()
    blender_ext.load_file()
    blender_ext.enable()
    i18n = _module("core.i18n")
    unittest.addModuleCleanup(i18n.set_language, i18n.language())
    i18n.set_language("es")


def tearDownModule() -> None:  # noqa: N802
    try:
        _module("bl.draw.design").disable()
        _module("bl.scene.project_session").close()
        _LOCAL.close()
    finally:
        blender_ext.load_file()
        blender_ext.release()


# --- Las llamadas del hilo de Blender -----------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Call:
    """Una llamada del hilo de Blender: qué era, lo que tardó en pared (``seconds``) y en CPU del proceso
    (``cpu``), las fases de los pasos que dio, lo que esperó en ella a la red (``waits``, por clase de
    ``tests.support.netwaits``) y las transacciones finales que hubo dentro (``commits``: el tipo de su
    operación, lo que tardó en pared y en CPU y lo que esperó en ella a la red)."""

    what: str
    seconds: float
    cpu: float
    phases: str = ""
    waits: tuple[tuple[str, float], ...] = ()
    commits: tuple[tuple[str, float, float, float], ...] = ()

    @property
    def waited(self) -> float:
        return sum(seconds for _kind, seconds in self.waits)

    @property
    def own(self) -> float:
        """Lo que hace Geoblender en la llamada: su duración sin sus esperas de la red."""
        return self.seconds - self.waited

    @property
    def transaction(self) -> float:
        """Lo que hace Geoblender en sus transacciones finales, en pared (sin sus esperas de la red)."""
        return sum(seconds - waited for _op, seconds, _cpu, waited in self.commits)

    @property
    def transaction_cpu(self) -> float:
        return sum(cpu for _op, _seconds, cpu, _waited in self.commits)

    @property
    def budgeted(self) -> float:
        """Lo que cuenta frente a :data:`CALL_BUDGET_S` en pared: lo que hace Geoblender sin la
        transacción final (medida aparte, plan R4) ni las esperas de la red."""
        return self.own - self.transaction

    @property
    def budgeted_cpu(self) -> float:
        """Lo mismo en CPU del proceso (las esperas de la red no gastan CPU)."""
        return self.cpu - self.transaction_cpu

    def text(self) -> str:
        """«qué era (fases)», con sus transacciones finales y sus esperas de la red."""
        parts = [self.what + (f" ({self.phases})" if self.phases else "")]
        parts += [f"transacción final de {op} {ms(seconds)} ms de pared y {ms(cpu)} ms de CPU"
                  + (f" ({ms(seconds - waited)} ms sin sus esperas de la red)"
                     if waited >= 0.0005 else "")
                  for op, seconds, cpu, waited in self.commits]
        if self.waited >= 0.0005:
            parts.append("esperas de la red " + ", ".join(
                f"{kind} {ms(seconds)} ms" for kind, seconds in self.waits if seconds >= 0.0005))
        return "; ".join(parts)


class Recorder:
    """Mide cada llamada del hilo de Blender (:meth:`call`) en pared y en CPU del proceso, con lo que
    esperó a la red (``waits``, un ``netwaits.NetworkWaits`` activo, o ``None`` en disco local) y el
    ``DesignWriter.commit`` que hubo dentro, mientras está activo (``with``)."""

    def __init__(self, waits: netwaits.NetworkWaits | None = None) -> None:
        self.waits = waits
        self.calls: list[Call] = []
        self._commits: list[tuple[str, float, float, float]] = []
        self._stack = ExitStack()

    def __enter__(self) -> Recorder:
        writer = _module("design.store").DesignWriter
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
            started, cpu = time.perf_counter(), time.process_time()
            try:
                return real(writer, *args, **kwargs)
            finally:
                recorder._commits.append((writer.op_type, time.perf_counter() - started,
                                          time.process_time() - cpu, recorder._waited() - before))

        return commit

    def call(self, what: str, function: Callable[..., Any], *args: Any,
             phases: Callable[[], str] | None = None, **kwargs: Any) -> Any:
        """``function(*args, **kwargs)`` como una llamada del hilo de Blender, medida."""
        self._commits = []
        if self.waits is not None:
            self.waits.begin()
        started, cpu = time.perf_counter(), time.process_time()
        result = function(*args, **kwargs)
        seconds, spent = time.perf_counter() - started, time.process_time() - cpu
        waits = () if self.waits is None else tuple(self.waits.take().items())
        self.calls.append(Call(what, seconds, spent, "" if phases is None else phases(), waits,
                               tuple(self._commits)))
        return result


@dataclasses.dataclass(frozen=True)
class Run:
    """Un cálculo medido (una o las dos órdenes): sus llamadas, lo que tardó de Intro al final y los
    eventos del modal."""

    label: str
    calls: tuple[Call, ...]
    seconds: float

    @property
    def events(self) -> int:
        return sum(call.what.startswith("evento") for call in self.calls)

    @property
    def with_modal_waits(self) -> float:
        """Lo que tardaría con el temporizador del modal de Blender (50 ms entre dos eventos, o menos si el
        evento ya dura más): cada evento ocupa lo que dura o 50 ms, el que sea mayor."""
        return sum(max(call.seconds, TIMER_INTERVAL_S) if call.what.startswith("evento")
                   else call.seconds for call in self.calls)

    @property
    def worst_cpu(self) -> Call:
        """La llamada que más se acerca al presupuesto en CPU (sin la transacción final)."""
        return max(self.calls, key=lambda call: call.budgeted_cpu)

    @property
    def worst_wall(self) -> Call:
        """La llamada que más se acerca al presupuesto en pared (sin sus esperas de la red ni la
        transacción final)."""
        return max(self.calls, key=lambda call: call.budgeted)

    @property
    def longest(self) -> Call:
        return max(self.calls, key=lambda call: call.seconds)

    @property
    def with_commits(self) -> list[Call]:
        return [call for call in self.calls if call.commits]

    def top(self, n: int = TOP_CALLS) -> list[Call]:
        return sorted(self.calls, key=lambda call: call.seconds, reverse=True)[:n]


def calls_line(run: Run, where: str, *, network_waits: bool) -> str:
    """Lo medido de ``run`` (véase el módulo), para la línea de la cifra."""
    cpu, wall = run.worst_cpu, run.worst_wall
    intro = run.calls[0]
    ticks = sum(call.what.startswith("tic") for call in run.calls)
    commits = "; ".join(f"{call.text()}: la llamada {ms(call.seconds)} ms"
                        + (f" ({ms(call.own)} ms sin sus esperas de la red)" if network_waits
                           else "")
                        for call in run.with_commits) or "ninguna"
    top = "; ".join(f"{ms(call.seconds)} ms de pared y {ms(call.cpu)} de CPU ({call.text()})"
                    for call in run.top())
    own = ("sin sus esperas de la red ni la transacción final" if network_waits
           else "sin la transacción final")
    return (f"{where}: de Intro al final {number(run.seconds, 2)} s en {len(run.calls)} llamadas del "
            f"hilo de Blender (Intro, {run.events} eventos del modal y {ticks} tics de los "
            f"indicadores; con los 50 ms del temporizador del modal, {number(run.with_modal_waits, 2)} "
            f"s); Intro {ms(intro.seconds)} ms de pared y {ms(intro.cpu)} de CPU; {own}, la peor en "
            f"CPU {ms(cpu.budgeted_cpu)} ms ({cpu.text()}) y la peor en pared {ms(wall.budgeted)} ms "
            f"({wall.text()}); presupuesto {number(CALL_BUDGET_S, 1)} s de lo que hace Geoblender en "
            f"cada llamada{', sin sus esperas de la red (aparte, sin presupuesto)' if network_waits else ''}"
            f"; la transacción final, aparte (plan R4): {commits}; las {TOP_CALLS} más largas: {top}")


def warn_slow(run: Run, where: str) -> None:
    """Los avisos de lo que pasa de 0,2 s: lo que no es la transacción final en pared (se repite en
    reposo; el presupuesto se exige a la CPU) y la transacción final (para Samuel, R4)."""
    over = [call for call in run.calls if call.budgeted > CALL_BUDGET_S]
    if over:
        report(f"Aviso RNF-013-07 ({where}): {len(over)} llamadas de más de {number(CALL_BUDGET_S, 1)} "
               f"s de pared sin la transacción final (con el equipo cargado por otros programas se "
               f"repite en reposo; el presupuesto se exige a la CPU): "
               + "; ".join(f"{ms(call.budgeted)} ms de pared y {ms(call.budgeted_cpu)} de CPU "
                           f"({call.text()})" for call in over))
    held = [call for call in run.with_commits if call.own > CALL_BUDGET_S >= call.budgeted]
    if held:
        report(f"Aviso RNF-013-07 ({where}; plan R4, la cifra para Samuel): la transacción final deja "
               f"{len(held)} llamadas de más de {number(CALL_BUDGET_S, 1)} s: "
               + "; ".join(f"{ms(call.own)} ms ({call.text()})" for call in held))


def commit_warnings(run: Run, where: str) -> None:
    """Si la transacción final (``DesignWriter.commit``) pasa de 0,2 s por sí sola: la cifra, para Samuel
    (plan R4)."""
    long = [(call, op, seconds, waited) for call in run.with_commits
            for op, seconds, _cpu, waited in call.commits if seconds - waited > CALL_BUDGET_S]
    if long:
        report(f"Aviso RNF-013-07 ({where}; plan R4, la cifra para Samuel): la transacción final pasa "
               f"de {number(CALL_BUDGET_S, 1)} s: "
               + "; ".join(f"{op} {ms(seconds - waited)} ms" for _call, op, seconds, waited in long))


def phases_of(operator: Any) -> Callable[[], str]:
    """Las fases de los pasos que da ``operator`` desde que se llama a esto."""
    log = getattr(operator, "progress_log", [])
    before = len(log)

    def phases() -> str:
        return ",".join(dict.fromkeys(str(entry[1]) for entry in log[before:]
                                      if isinstance(entry, tuple)))

    return phases


def pump(recorder: Recorder, operator: Any, label: str) -> set[str]:
    """Los eventos del temporizador del modal de ``operator``, uno por llamada, hasta que termina, con el
    tic de los indicadores de la procedencia cuando le toca (el temporizador que corre mientras
    tanto)."""
    ui_provenance = _module("bl.ui.provenance")
    clock, due = 0.0, ui_provenance.INDICATOR_TICK_S
    for event in range(pc.MAX_EVENTS):
        state = recorder.call(f"evento {event + 1} del modal", operator.modal, bpy.context, TIMER,
                              phases=phases_of(operator))
        clock += recorder.calls[-1].seconds + TIMER_INTERVAL_S
        if clock >= due:
            interval = recorder.call("tic de los indicadores de la procedencia",
                                     ui_provenance.indicator_tick)
            due = clock + (ui_provenance.INDICATOR_TICK_S if interval is None else interval)
        if state != {"RUNNING_MODAL"}:
            return state
    raise AssertionError(f"«{label}» no acaba")


# --- Las órdenes de Diseño, como desde la interfaz ------------------------------------------------


def envelope_form(built: Built, name: str, **changes: Any) -> dict[str, Any]:
    """Lo pedido en el diálogo de las envolventes: por defecto, una envolvente descendente *chamfer* de
    35° desde las semillas en anillo (la rejilla de cotas), en todo el dominio."""
    form: dict[str, Any] = {
        "name": name, "seeds_from": "GRID", "surface": built.ring, "zone": NO_ZONE,
        "direction": "DOWN", "metric": "CHAMFER5", "slope_mode": "CONSTANT",
        "slope": f"{ddata.GENERAL_DEG:g}", "bound": "ALL", "stepped": False, "in_steps": True}
    form.update(changes)
    return form


def pick_profiles() -> None:
    """Un perfil para cada sector (los diez en rotación), como lo haría la persona en la ventana de los
    sectores."""
    for row in view().sectors:
        row.profile_pick = profile_name(ddata.profile_of(int(row.code.rsplit("_", 1)[1])))


def calculate(recorder: Recorder, form: dict[str, Any], what: str) -> None:
    """«Calcular»: Intro (la orden en pasos) y cada evento de su modal hasta que termina, con la
    confirmación sustituida (sin ventana no corre su temporizador); deja el cálculo abierto."""
    commands = _module("bl.ui.commands")
    des_ops = _module("bl.ops.des")
    cls = commands.registered_class(COMPUTE)
    with mock.patch.object(des_ops, "_ask_confirmation") as ask:
        result = recorder.call(f"Intro: comprobar y empezar ({what})",
                               getattr(bpy.ops.geoblender, COMPUTE.split(".")[1]), "EXEC_DEFAULT",
                               **form)
        if result != {"RUNNING_MODAL"}:
            raise AssertionError(f"«{what}» no empieza: {result}")
        state = pump(recorder, pc.running(cls), what)
    if state != {"FINISHED"} or ask.call_count != 1:
        raise AssertionError(f"«{what}» acaba mal: {state}")
    if des_ops.calculation() is None:
        raise AssertionError(f"«{what}» no deja el cálculo abierto")


def create(recorder: Recorder, what: str, *, then_modal: bool = False) -> set[str]:
    """«Crear»: la misma orden con ``confirm`` (la transacción final); con el escalonado pedido, deja en
    marcha su modal (``then_modal``) y sigue con sus eventos hasta que termina."""
    commands = _module("bl.ui.commands")
    des_ops = _module("bl.ops.des")
    cls = commands.registered_class(COMPUTE)
    with mock.patch.object(des_ops, "_ask_confirmation"):
        result = recorder.call(f"Crear ({what})", getattr(bpy.ops.geoblender, COMPUTE.split(".")[1]),
                               "EXEC_DEFAULT", confirm=True, in_steps=True)
        if then_modal:
            if result != {"RUNNING_MODAL"}:
                raise AssertionError(f"«{what}» no sigue con el escalonado: {result}")
            return pump(recorder, pc.running(cls), what)
    if result != {"FINISHED"}:
        raise AssertionError(f"«{what}» no se crea: {result}")
    return result


class _Case(unittest.TestCase):
    """La extensión habilitada (sin importarla otra vez: ``blender_ext.release``), el idioma en español y
    el proyecto de §2.2 en disco local, el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ps = _module("bl.scene.project_session")
        cls.des_ops = _module("bl.ops.des")
        cls.design = _module("bl.draw.design")
        cls.cons = _module("bl.draw.constraints")
        cls.dh = _module("bl.draw.dh_overlay")

    def tearDown(self) -> None:
        self.des_ops.discard_calculation()  # lo que deja una prueba que falla no pasa a la siguiente
        if self.design.enabled():
            self.design.disable()

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.ps.current().read() as conn:
            return conn.execute(sql, args).fetchall()

    def done(self, op_type: str, name: str) -> list[str]:
        """El uid de las operaciones ``op_type`` hechas del cálculo ``name``."""
        return [uid for uid, settings in self.rows(
            "SELECT uid, settings FROM gb_operation WHERE op_type = ? AND status = 'done'", op_type)
            if json.loads(settings).get("name") == name]

    def figures_of(self, op_type: str, name: str) -> dict[str, float]:
        """Las cifras de la operación ``op_type`` de nombre ``name`` (una sola hecha)."""
        (uid,) = self.done(op_type, name)
        return {key: float(value) for key, value in self.rows(
            "SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid)}


# --- RNF-013-07: calcular y crear con las órdenes reales -----------------------------------------

ENVELOPE_TYPE = "des.envelope"
STEPPED_TYPE = "des.stepped_design"


def full_chain(recorder: Recorder, built: Built, name: str) -> None:
    """El cálculo completo de las dos órdenes (RNF-013-03): la envolvente por los 20 sectores
    (diez perfiles y dos taludes impuestos) y su escalonado en corte, cada una con su «Calcular» y su
    «Crear» (el escalonado se encadena a la envolvente)."""
    pick_profiles()
    form = envelope_form(built, name, slope_mode="SECTORS", slope="", stepped=True, sense="CUT",
                         start=built.start, base_profile=profile_name(ddata.PROFILES[0]))
    calculate(recorder, form, "envolvente por sectores")
    state = create(recorder, "envolvente por sectores", then_modal=True)
    if state != {"FINISHED"}:
        raise AssertionError(f"el escalonado de «{name}» acaba mal: {state}")
    create(recorder, "escalonado en corte")


class CallsTest(_Case):
    """RNF-013-07 con el proyecto de §2.2 en disco local, en el orden de sus letras sobre el mismo estado."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.built = _LOCAL.built()

    def check_run(self, run: Run, where: str) -> None:
        warn_slow(run, where)
        commit_warnings(run, where)
        worst = run.worst_cpu
        self.assertLessEqual(worst.budgeted_cpu, CALL_BUDGET_S, f"{run.label}: {worst.text()}")

    def report_run(self, text: str, run: Run) -> None:
        built = self.built
        report(f"RNF-013-07: {text} con {built.constraints} restricciones ({count(built.vertices)} "
               f"vértices), {ddata.SECTORS} sectores y {count(CELLS)} celdas de 1 m ({MACHINE}), "
               f"{calls_line(run, 'con el proyecto en disco local', network_waits=False)}; "
               f"{free_space(built.root)}")

    def measure(self, label: str, steps: Callable[[Recorder], None]) -> Run:
        """Lo que hacen ``steps`` con el hilo de Blender, llamada a llamada."""
        recorder = Recorder()
        gc.collect()
        with recorder:
            started = time.perf_counter()
            steps(recorder)
            seconds = time.perf_counter() - started
        return Run(label, tuple(recorder.calls), seconds)

    def test_a_envelope_chamfer_constant_slope(self) -> None:
        """RNF-013-07 (plan §7.3, R4; RF-013-03, RF-013-17, RF-013-31, RF-013-33): «Envolventes y
        escalonado…» con la envolvente *chamfer* de 35° desde las semillas en anillo (5,3 mil celdas)
        sobre 2,81 M celdas, 20 sectores y las 500 restricciones, como desde la interfaz: en ninguna
        llamada del hilo de Blender (Intro, cada evento del modal y el tic de los indicadores) lo que hace
        Geoblender sin la transacción final pasa de 0,2 s; «Crear» (la transacción final), aparte."""
        name = "Anillo chamfer"

        def steps(recorder: Recorder) -> None:
            calculate(recorder, envelope_form(self.built, name), "envolvente chamfer")
            create(recorder, "envolvente chamfer")

        run = self.measure("envolvente chamfer", steps)
        self.assertEqual(len(self.done(ENVELOPE_TYPE, name)), 1)
        self.assertGreater(self.figures_of(ENVELOPE_TYPE, name)["des.env_cells"], 0)
        self.report_run("«Envolventes y escalonado…», envolvente chamfer de 35° desde las semillas en "
                        "anillo", run)
        self.check_run(run, "envolvente chamfer")

    def test_b_envelope_by_sectors_and_its_benching(self) -> None:
        """RNF-013-07 (plan §7.3, R4; RF-013-09, RF-013-21, RF-013-22, RF-013-26, RF-013-31): el
        cálculo completo de las dos órdenes, la envolvente *chamfer* por los 20 sectores (diez perfiles
        y dos taludes impuestos) desde las semillas en anillo y su escalonado en corte sobre el terreno,
        cada una con su «Calcular» y su «Crear»: en ninguna llamada sin la transacción final pasa de
        0,2 s."""
        name = "Sectores y bancos"
        run = self.measure("envolvente por sectores y escalonado",
                           lambda recorder: full_chain(recorder, self.built, name))
        self.assertEqual(len(self.done(ENVELOPE_TYPE, name)), 1)
        self.assertEqual(len(self.done(STEPPED_TYPE, name)), 1)
        stepped = self.figures_of(STEPPED_TYPE, name)
        self.assertGreater(stepped["des.cut_m3"], 0.0)
        self.assertGreater(stepped["des.berm_count"], 0)
        self.report_run("«Envolventes y escalonado…», envolvente por sectores y escalonado en corte "
                        f"({count(int(stepped['des.berm_count']))} filas de bermas)", run)
        self.check_run(run, "envolvente por sectores y escalonado")

    def test_c_exact_envelope(self) -> None:
        """RNF-013-07 (plan §7.3, R4; RF-013-12, RF-013-33): la envolvente euclídea exacta de 35° desde
        las semillas en anillo, cuya búsqueda por bloques es la que más pasos da: en ninguna llamada sin
        la transacción final pasa de 0,2 s."""
        name = "Anillo exacta"

        def steps(recorder: Recorder) -> None:
            calculate(recorder, envelope_form(self.built, name, metric="EXACT"), "envolvente exacta")
            create(recorder, "envolvente exacta")

        run = self.measure("envolvente exacta", steps)
        self.assertEqual(len(self.done(ENVELOPE_TYPE, name)), 1)
        self.report_run("«Envolventes y escalonado…», envolvente euclídea exacta de 35° desde las "
                        "semillas en anillo", run)
        self.check_run(run, "envolvente exacta")

    def test_d_the_whole_surface_as_seeds(self) -> None:
        """RNF-013-07 (plan §7.3; RF-013-01, RF-013-03): «Calcular» con todo el dominio de trabajo del
        terreno como semillas (la preparación con más semillas posible), sin crear: en ninguna llamada
        pasa de 0,2 s. Descarta el cálculo y no deja nada."""
        name = "Terreno entero"
        operations = self.rows("SELECT count(*) FROM gb_operation")

        def steps(recorder: Recorder) -> None:
            form = envelope_form(self.built, name, seeds_from="SURFACE", surface=self.built.start,
                                 zone="domain")
            calculate(recorder, form, "todo el dominio como semillas")

        run = self.measure("todo el dominio como semillas", steps)
        opened = self.des_ops.calculation()
        self.assertIsNotNone(opened)
        self.assertGreater(opened.seeds.cells, 100_000)
        cells = opened.seeds.cells
        self.des_ops.discard_calculation()
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation"), operations)
        self.report_run(f"«Envolventes y escalonado…», «Calcular» con {count(cells)} semillas (todo el "
                        "dominio de trabajo del terreno), sin crear", run)
        self.check_run(run, "todo el dominio como semillas")


# --- RNF-013-05: la vista previa ------------------------------------------------------------------


class _Null:
    """Un objeto que acepta cualquier uso y no hace nada: ``gpu`` y ``blf`` sustituidos, para medir solo el
    Python de Geoblender."""

    def __getattr__(self, name: str) -> _Null:
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> _Null:
        return self

    def __enter__(self) -> _Null:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


@dataclasses.dataclass(frozen=True)
class Activation:
    """Una activación de la vista previa: lo que tardó la orden (pared y CPU), cada paso del temporizador
    y lo construido."""

    order: tuple[float, float]
    ticks: tuple[tuple[float, float], ...]
    built: Any

    @property
    def work_s(self) -> float:
        return self.order[0] + sum(wall for wall, _cpu in self.ticks)

    @property
    def wall_s(self) -> float:
        """Hasta que está construida: la orden, los pasos y los 5 ms de espera de cada uno
        (``bl.draw.design.TICK_INTERVAL_S``) menos el último."""
        return self.work_s + TICK_WAIT_S * max(0, len(self.ticks) - 1)

    @property
    def longest(self) -> tuple[float, float]:
        """La llamada más larga (pared y CPU de la que más tarda en CPU): la orden o un paso."""
        return max([self.order, *self.ticks], key=lambda call: call[1])


class PreviewTest(_Case):
    """RNF-013-05: la vista previa con las 100.000 semillas del disco, los 20 sectores y las 500
    restricciones, las máscaras de V01 al día y una rejilla de 2,81 M celdas, en disco local."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.built = _LOCAL.built()
        cls.addClassCleanup(cls.design.disable)

    def toggle(self, **values: Any) -> Any:
        return bpy.ops.geoblender.des_toggle_preview("EXEC_DEFAULT", **values)

    def activate(self) -> Activation:
        """Pulsa el control de la vista previa (semillas del disco en toda el dominio) y da los pasos del
        temporizador hasta que está construida (en ``blender -b`` no corren)."""
        design = self.design
        self.assertFalse(design.enabled())
        gc.collect()
        started, cpu = time.perf_counter(), time.process_time()
        result = self.toggle(seeds_from="GRID", surface=self.built.disc, bound="ALL")
        order = (time.perf_counter() - started, time.process_time() - cpu)
        self.assertEqual(result, {"FINISHED"})
        self.assertTrue(design.enabled() and design.building())
        ticks = []
        for _ in range(MAX_TICKS):
            started, cpu = time.perf_counter(), time.process_time()
            interval = design.tick()
            ticks.append((time.perf_counter() - started, time.process_time() - cpu))
            if interval is None:
                break
        else:
            self.fail("la vista previa no acaba de construirse")
        built = design.built()
        self.assertIsNotNone(built)
        return Activation(order, tuple(ticks), built)

    def deactivate(self) -> None:
        self.assertEqual(self.toggle(), {"FINISHED"})
        self.assertFalse(self.design.enabled() or self.design.building())

    def test_a_activating_the_preview_with_100000_seeds(self) -> None:
        """RNF-013-05, RNF-013-07 (RF-013-03; HU-013-1): activar la vista previa con las 100.000
        semillas de un disco, los 20 sectores y las 500 restricciones (las máscaras de V01 al día y la
        rejilla de 2,81 M celdas debajo), hasta que está construida: la orden y los pasos de su
        temporizador ≤ 1 s (con los 5 ms de espera de cada paso; mediana de 5, la peor con un aviso si lo
        pasa) y ninguna llamada del hilo de Blender de más de 0,2 s de CPU. La primera, en frío (las
        cachés de SQLite, el primer uso de los módulos…), no cuenta para el primero, pero sí para la
        llamada más larga."""
        self.assertEqual(self.design.TICK_INTERVAL_S, TICK_WAIT_S)
        cold = self.activate()
        self.deactivate()
        found = []
        for _ in range(ACTIVATIONS):
            found.append(self.activate())
            self.deactivate()
        last = found[-1].built
        walls = [item.wall_s for item in found]
        worst = max(found, key=lambda item: item.wall_s)
        calls = [*found, cold]
        slowest = max(calls, key=lambda item: item.longest[1])
        seeds = last.seeds
        self.assertIsNotNone(seeds)
        self.assertTrue(99_000 <= seeds.total <= 101_000, seeds.total)
        self.assertEqual((seeds.count, seeds.stride), (seeds.total, 1))
        self.assertEqual(len(last.sectors), ddata.SECTORS)
        self.assertEqual(last.lines.masks, "current")
        self.assertGreater(len(last.lines.labels), self.built.constraints // 2)
        segments = sum(batch.segments for batch in last.lines.batches)
        report(
            f"RNF-013-05: activar la vista previa con {count(seeds.total)} semillas, {ddata.SECTORS} "
            f"sectores y {self.built.constraints} restricciones ({count(self.built.vertices)} vértices), "
            f"las máscaras de V01 al día y {count(CELLS)} celdas debajo, hasta que está construida "
            f"({count(len(last.lines.batches))} lotes, {count(segments)} segmentos, "
            f"{count(len(last.lines.labels))} nombres; {MACHINE}): mediana de {len(found)} "
            f"{number(statistics.median(walls))} s (la peor {number(max(walls))} s; {len(worst.ticks)} "
            f"pasos del temporizador con {number(TICK_WAIT_S * 1000, 0)} ms de espera cada uno, "
            f"{number(worst.work_s)} s de trabajo; la primera, en frío, {number(cold.wall_s)} s) "
            f"frente a {number(ACTIVATE_BUDGET_S, 1)} s; la llamada más larga {ms(slowest.longest[0])} "
            f"ms de pared y {ms(slowest.longest[1])} de CPU (la orden {ms(slowest.order[0])} ms de "
            f"pared y {ms(slowest.order[1])} de CPU; presupuesto {number(CALL_BUDGET_S, 1)} s por "
            f"llamada); {free_space(self.built.root)}")
        slow = [item for item in calls if item.longest[0] > CALL_BUDGET_S]
        if slow:
            report(f"Aviso RNF-013-07 (vista previa): {len(slow)} activaciones con una llamada de más de "
                   f"{number(CALL_BUDGET_S, 1)} s de pared (con el equipo cargado por otros programas se "
                   f"repite en reposo; el presupuesto se exige a la CPU): "
                   + ", ".join(f"{ms(item.longest[0])} ms de pared y {ms(item.longest[1])} de CPU"
                               for item in slow))
        if max(walls) > ACTIVATE_BUDGET_S:
            report(f"Aviso RNF-013-05 (vista previa): la peor de {len(found)} activaciones, "
                   f"{number(max(walls))} s, pasa de {number(ACTIVATE_BUDGET_S, 1)} s (se exige la "
                   f"mediana, {number(statistics.median(walls))} s, como en el resto de la 013); se "
                   f"repite con el equipo en reposo")
        self.assertLessEqual(statistics.median(walls), ACTIVATE_BUDGET_S)
        self.assertLessEqual(slowest.longest[1], CALL_BUDGET_S)

    def view_matrices(self, zoom: float) -> tuple[Matrix, Matrix, float]:
        """La vista desde arriba (ortográfica) de la ventana entera (``zoom`` 1) o de 1/``zoom`` de su alto,
        centrada, en coordenadas locales: (vista, proyección, distancia)."""
        origin = self.ps.current().origin
        cx = cdata.WEST + cdata.COLS * cdata.STEP_M / 2.0 - origin.x0
        cy = cdata.SOUTH + cdata.ROWS * cdata.STEP_M / 2.0 - origin.y0
        half_h = cdata.ROWS * cdata.STEP_M / 2.0 / zoom
        half_w = half_h * REGION[0] / REGION[1]
        eye, near, far = 2000.0, 1.0, 4000.0
        view = Matrix.Translation((-cx, -cy, -eye))
        projection = Matrix(((1 / half_w, 0, 0, 0), (0, 1 / half_h, 0, 0),
                             (0, 0, -2 / (far - near), -(far + near) / (far - near)),
                             (0, 0, 0, 1)))
        return view, projection, eye

    def redraw(self, built: Any, view: Matrix, projection: Matrix, eye: float
               ) -> tuple[float, float, int]:
        """Un redibujo como el de los manejadores de la Vista 3D (``POST_VIEW``: los lotes y los puntos;
        ``POST_PIXEL``: los nombres, la leyenda y el resumen): lo que tardó cada parte y cuántos
        elementos de píxeles dibujó."""
        design, cons, dh = self.design, self.cons, self.dh
        size = (float(REGION[0]), float(REGION[1]))
        started = time.perf_counter()
        if built.lines.batches:
            cons.draw_lines(built.lines, view_matrix=view, projection_matrix=projection,
                            perspective=False, view_distance=eye, viewport_size=size,
                            pixel_size=1.0)
        design.draw_points(built, view_matrix=view, projection_matrix=projection,
                           perspective=False, view_distance=eye, pixel_size=1.0)
        middle = time.perf_counter()
        design.blf.size(dh.FONT_ID, dh.FONT_PX)
        items = design.screen_items(built, np.array(projection @ view), size,
                                    measure=design._measure, scale=1.0)
        if items:
            dh.paint(items, size, scale=1.0)
        finished = time.perf_counter()
        return middle - started, finished - middle, len(items)

    def measure_redraws(self, built: Any, view: Matrix, projection: Matrix, eye: float
                        ) -> dict[str, Any]:
        """El primer dibujo (crea los lotes de ``gpu``) y :data:`REDRAWS` más."""
        first = self.redraw(built, view, projection, eye)
        drawn = [self.redraw(built, view, projection, eye) for _ in range(REDRAWS)]
        totals = [lines + pixels for lines, pixels, _items in drawn]
        return {"first": sum(first[:2]), "totals": totals,
                "lines": statistics.median(item[0] for item in drawn),
                "pixels": statistics.median(item[1] for item in drawn), "items": drawn[-1][2]}

    def test_b_the_python_of_each_redraw(self) -> None:
        """RNF-013-05 (RF-013-03; M1): cada redibujo de la vista previa activa, con ``gpu`` y ``blf``
        sustituidos (solo el Python de Geoblender: los lotes de las restricciones y los sectores, los
        puntos de las 100.000 semillas, las matrices, la proyección de los nombres, la leyenda y el
        resumen) a 1.920 × 1.080 px, con la ventana entera y acercada 6 veces, ≤ 5 ms."""
        design, cons, dh = self.design, self.cons, self.dh
        self.activate()
        built = design.built()
        null = _Null()
        lines = []
        worst = 0.0
        try:
            with ExitStack() as stack:
                for target, name in ((design, "gpu"), (design, "batch_for_shader"), (cons, "gpu"),
                                     (cons, "batch_for_shader"), (dh, "gpu"), (dh, "blf"),
                                     (dh, "batch_for_shader")):
                    stack.enter_context(mock.patch.object(target, name, null))
                for zoom, text in ((1.0, "la ventana entera"), (6.0, "acercada 6 veces")):
                    for batch in built.lines.batches:
                        batch._gpu.clear()
                    built.seeds._gpu.clear()
                    view, projection, eye = self.view_matrices(zoom)
                    found = self.measure_redraws(built, view, projection, eye)
                    totals = found["totals"]
                    lines.append(
                        f"{text}: el primer dibujo {ms(found['first'])} ms (crea los lotes); mediana de "
                        f"{len(totals)} {ms(statistics.median(totals), 3)} ms (lotes y puntos "
                        f"{ms(found['lines'], 3)} ms y {count(found['items'])} elementos de píxeles "
                        f"{ms(found['pixels'], 3)} ms), máximo {ms(max(totals), 3)} ms")
                    worst = max(worst, statistics.median(totals))
                    self.assertGreater(found["items"], 0)
        finally:
            for batch in built.lines.batches:
                batch._gpu.clear()
            built.seeds._gpu.clear()
            self.deactivate()
        report(f"RNF-013-05: redibujar la vista previa con {count(built.seeds.total)} semillas, "
               f"{ddata.SECTORS} sectores y {self.built.constraints} restricciones "
               f"({count(sum(b.segments for b in built.lines.batches))} segmentos en "
               f"{len(built.lines.batches)} lotes, {count(len(built.lines.labels))} nombres; región de "
               f"{REGION[0]} × {REGION[1]} px; {MACHINE}): " + "; ".join(lines)
               + f"; presupuesto {ms(REDRAW_BUDGET_S, 0)} ms por redibujo")
        self.assertLessEqual(worst, REDRAW_BUDGET_S)


# --- En la red --------------------------------------------------------------------------------------


@requires(network.NET, network.NET_HINT)
class NetworkTest(_Case):
    """RNF-013-03 y RNF-013-07 con el proyecto en la carpeta de pruebas de la red (``Z:``): un proyecto
    propio en una subcarpeta temporal (borrada al terminar) y los datos de usuario en disco local; al
    terminar, vuelve el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ps.close()
        cls.addClassCleanup(_LOCAL.restore)  # lo último: los de la clase, al revés
        remote = cls.enterClassContext(network.net_tmp("gb-013-t31-"))
        cls.addClassCleanup(cls.ps.close)  # lo primero: antes de borrar su carpeta
        cls.remote = remote
        cls.built = build(remote / "proyectos", 2)

    def test_full_calculation_on_the_network(self) -> None:
        """RNF-013-03 y RNF-013-07 en ``Z:`` (como RNF-011-04 y RNF-012-06): el cálculo completo de las dos
        órdenes (la envolvente por los 20 sectores y su escalonado en corte, cada una con su «Calcular» y
        su «Crear») con el proyecto en la red, de «Calcular» de la envolvente a las cifras registradas del
        escalonado, con la escritura de las tres rejillas con su hash y las dos transacciones finales, en
        ≤ 25 s (con los 50 ms del temporizador del modal); lo que hace Geoblender en cada llamada del hilo
        de Blender, sin sus esperas de la red (medidas en la llamada y anotadas aparte, sin presupuesto)
        ni la transacción final (aparte), no pasa de 0,2 s de CPU."""
        built = self.built
        project = self.ps.current()
        self.assertTrue(project.is_network, "el proyecto de la carpeta de la red")
        name = "Sectores y bancos en la red"
        recorder_runs = []
        with netwaits.NetworkWaits(self.remote, projects=[project]) as waits:
            recorder = Recorder(waits)
            gc.collect()
            with recorder:
                started = time.perf_counter()
                full_chain(recorder, built, name)
                seconds = time.perf_counter() - started
            recorder_runs.append(Run("cálculo completo en la red", tuple(recorder.calls), seconds))
            longest = waits.longest
        run = recorder_runs[0]
        self.assertEqual(len(self.done(ENVELOPE_TYPE, name)), 1)
        self.assertEqual(len(self.done(STEPPED_TYPE, name)), 1)
        where = "con el proyecto en la carpeta de pruebas de la red"
        report(f"RNF-013-03 y RNF-013-07: «Envolventes y escalonado…», el cálculo completo "
               f"(envolvente por {ddata.SECTORS} sectores y escalonado en corte) sobre {count(CELLS)} "
               f"celdas de 1 m ({MACHINE}): {number(run.with_modal_waits, 2)} s con los 50 ms del "
               f"temporizador del modal ({number(run.seconds, 2)} s de trabajo) frente a "
               f"{number(DESIGN_NETWORK_BUDGET_S, 0)} s; {calls_line(run, where, network_waits=True)}"
               f"; la espera de la red más larga, {longest[0]} {ms(longest[1])} ms; "
               f"{free_space(built.root)}")
        warn_slow(run, where)
        commit_warnings(run, where)
        waited = [call for call in run.calls if call.seconds > CALL_BUDGET_S >= call.own]
        if waited:
            report(f"Nota RNF-013-07 ({where}): {len(waited)} llamadas de más de "
                   f"{number(CALL_BUDGET_S, 1)} s solo por sus esperas de la red (se anotan, sin "
                   "presupuesto): " + "; ".join(f"{ms(call.seconds)} ms ({call.text()})"
                                                for call in waited))
        self.assertLessEqual(run.worst_cpu.budgeted_cpu, CALL_BUDGET_S, run.worst_cpu.text())
        self.assertLessEqual(run.with_modal_waits, DESIGN_NETWORK_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
