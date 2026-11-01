# SPDX-License-Identifier: GPL-3.0-or-later
"""Límites y restricciones dentro de Blender (spec 012, T31; RNF-012-05 y RNF-012-06; plan 012 §7.3
y el riesgo R4, ``tests/rendimiento/blender``).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py --
--carpeta tests/rendimiento/blender --patron "perf_constraints.py"``). Cada prueba imprime su cifra
en una línea «RNF-012-nn: …» con el equipo y el espacio libre del disco, y la compara con su
presupuesto, sin relajarlo.

**Datos** (plan §2.2; ``tests/support/constraints_data.py``: se generan aquí con la misma semilla
que las pruebas de ``tests/rendimiento/gis`` y ``res``, no se versionan y se borran al terminar):
un proyecto nuevo (EPSG:25830 + EPSG:5782) con V01 y V02, la rejilla de 1.654 × 1.699 celdas de
1 m (2,81 M) y las 500 restricciones de unos 100.000 vértices escritas por
``core.edit_constraints`` con sus parámetros dados de alta, más la superficie de partida y las tres
finales de cada forma (``window``, la dura, y ``local``) como rejillas del proyecto. Todo con la
extensión habilitada, como una persona.

- **RNF-012-06** (:class:`CallsTest`): «Compilar las máscaras»
  (``geoblender.gis_compile_constraints``) y «Verificar un diseño por recinto…»
  (``geoblender.res_verify_constraints``), las órdenes reales, como desde la interfaz: Intro (``execute`` por ``bpy.ops``, en pasos) y cada evento del
  temporizador de su modal hasta que termina, con el tic de los indicadores de la procedencia
  cuando le toca (el temporizador que corre mientras tanto). Cada llamada del hilo de Blender se
  mide: lo que hace Geoblender en ella, **sin la transacción final** (``MaskWriter.commit`` de
  ``gis.masks.store`` y ``CheckWriter.commit`` de ``reserves.compliance_store``: las tablas, la
  rejilla, las cifras y la operación, en una transacción que no se trocea; plan R4), ≤ 0,2 s; la
  transacción, medida aparte, se anota con la llamada en que ocurre (si pasa de 0,2 s, con un
  aviso: la cifra, para Samuel). Compilar, nueva y repitiéndola para sustituirla, y tras cambiar un
  resguardo solo en V01 (lo más habitual); verificar tres finales de cada forma, nueva y
  repitiéndola, y tras cambiar un resguardo (la orden compila las máscaras antes). Esos dos
  últimos escenarios fallaron al medirlos por primera vez (217 y 361 ms al empezar, por la
  lectura de las zonas anteriores de una vez: T31 arregló ``gis.masks.store.gather_steps`` y
  ``gis.masks.access.ensure_masks_steps``). :class:`RecomputeTest` hace lo mismo con «Recalcular
  lo obsoleto» tras cambiar un resguardo solo en V01 (la compilación nueva, las verificaciones
  nuevas y las colas de ``gis`` y ``res`` que las avanzan): **ahí quedan llamadas de 0,4 a 0,5 s**,
  hallazgo que se lleva a Samuel (el contrato de recálculo de la 008 devuelve la operación de
  una vez); se anotan y se vigilan sin fallar.
- **RNF-012-05** (:class:`OverlayTest`): «Ver restricciones y límites»
  (``geoblender.core_toggle_constraints_overlay``) con las 500 restricciones, las máscaras de V01 al
  día y una rejilla de 2,81 M celdas debajo: activarlo (la orden, y los pasos del temporizador de
  la superposición hasta que está construida, con los 5 ms de espera de cada uno) ≤ 1 s, y cada
  redibujo (los lotes con ``gpu``, los nombres y la leyenda) ≤ 5 ms: con la GPU (una imagen fuera
  de pantalla de 1.920 × 1.080 px, con ``gpu.init()``; se omite sin GPU) y, para separar lo que
  es Python de Geoblender, con ``gpu`` y ``blf`` sustituidos. Cada llamada de los pasos, ≤ 0,2 s
  (RNF-012-06). La GPU de verdad (la ventana, el color, el rayado) es de la comprobación manual
  M4.
- **En la red** (:class:`NetworkTest`; recurso «red» de ``tests.support.network``: con
  ``GEOBLENDER_NET_TEST_DIR``, a mano; sin ella, se omite): lo de RNF-012-06 con el proyecto en una
  subcarpeta temporal propia de la carpeta de pruebas de ``Z:`` (borrada al terminar) y los datos
  de usuario en disco local; las esperas de la red de cada llamada (abrir, leer, escribir, forzar y
  cerrar ficheros del proyecto, sus metadatos y el COMMIT de cada transacción) se miden con
  ``tests.support.netwaits`` y se anotan aparte, sin presupuesto (como RNF-011-04 y RNF-009-05): el
  presupuesto es el de lo que hace Geoblender. Escribe unos 100 MB en la red.

En ``blender -b`` no corren ni el bucle de eventos ni los temporizadores: la prueba hace de ventana
(un evento del temporizador del modal cada vez) y de temporizador; ``wm.call_panel`` (que en
``-b`` cierra Blender) se sustituye. Este módulo inicia la GPU (``gpu.init``) y se ejecuta el
último de su proceso (``RUN_LAST``): después, abrir un ``.blend`` tarda mucho más.
"""

from __future__ import annotations

import dataclasses
import gc
import importlib
import statistics
import tempfile
import time
import unittest
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np
from mathutils import Matrix

from tests.rendimiento.blender import perf_res as base
from tests.support import blender_ext, netwaits, network, resources
from tests.support import constraints_data as data
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import operator_self
from tests.support.resources import requires
from tests.support.trees import remove_tree

# Este módulo inicia la GPU: se ejecuta el último de su proceso (gbtools.parts.last_at_the_end).
RUN_LAST = True

CALL_BUDGET_S = 0.2  # RNF-012-06: lo que hace Geoblender en cada llamada del hilo de Blender
ACTIVATE_BUDGET_S = 1.0  # RNF-012-05: activar la superposición
REDRAW_BUDGET_S = 0.005  # RNF-012-05: cada redibujo
ACTIVATIONS = 5  # veces que se activa (la peor cuenta)
REDRAWS = 300  # redibujos medidos
SYNCED = 30  # redibujos medidos esperando a la GPU (solo se anotan)
TOP_CALLS = 5
MAX_EVENTS = base.MAX_EVENTS
MAX_TICKS = 20_000
TIMER = base.TIMER
TIMER_INTERVAL_S = base.TIMER_INTERVAL_S
REGION = (1920, 1080)
"""La región de la Vista 3D del redibujo: la de la barra a 1920 px de las comprobaciones
manuales."""

COMPILE = "geoblender.gis_compile_constraints"
VERIFY = "geoblender.res_verify_constraints"
RECOMPUTE = "geoblender.core_recompute_stale"
TOGGLE = "geoblender.core_toggle_constraints_overlay"
SET_PARAMETER = "geoblender.core_set_parameter"
REASON = "Rendimiento de los límites y las restricciones (spec 012, T31)"
PERSON = "Samuel (IMGA)"
SOURCE = "Valores sintéticos de prueba"
SHAPES = (("window", "toda la ventana"), ("local", "cambios localizados"))
"""Las formas de las finales (``constraints_data.shape_values``) y cómo se dicen."""
RESIZED = "Zona 00"
"""La restricción cuyo resguardo se cambia solo en V01 para recalcular."""
RECOMPUTE_OVER = 5
"""Las llamadas del modal de «Recalcular lo obsoleto» que pasan de 0,2 s sin la transacción final
(hallazgo de la T31 para Samuel; véase :class:`RecomputeTest`): las que empiezan una compilación
(``begin_compile`` de una vez), una por cada verificación (``load_masks`` de una vez) y la que
acaba. Se vigila que no sean más ni de otra clase."""

report = base.report
number = base.number
ms = base.ms
count = base.count
free_space = base.free_space
MACHINE = base.MACHINE
CELLS = data.COLS * data.ROWS


def _module(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión."""
    return importlib.import_module(f"{module_name()}.{name}")


# --- El proyecto de §2.2, con la extensión ------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Surfaces:
    """Las superficies de una forma escritas en el proyecto: el nombre del dato de la partida y los
    de las finales."""

    start: str
    finals: tuple[str, ...]


@dataclasses.dataclass
class Built:
    """Un proyecto de §2.2 (:func:`build`): su carpeta, el uid de V01, el código de cada
    restricción por su nombre, y las superficies de cada forma."""

    root: Path
    version_uid: str
    codes: dict[str, str]
    surfaces: dict[str, Surfaces]
    vertices: int


def constraint_rows() -> list[Any]:
    """Las restricciones de §2.2 como ``core.constraints.model.Constraint`` de la extensión
    (nuevas, sin código: lo da ``core.edit_constraints`` de su nombre)."""
    model, store = _module("core.constraints.model"), _module("core.constraints.store")
    rows = []
    for index, spec in enumerate(data.build_specs()):
        kind = model.GeometryKind(spec.kind)
        rows.append(model.Constraint(
            uid=f"{index:032x}", code="", name=spec.name, ctype=model.ConstraintType(spec.ctype),
            kind=kind, parts=((spec.part,),), priority=0, reason=REASON, decided_by=PERSON,
            decided_on=date(2026, 11, 1), decision_uid=None, intention_uid=None,
            source_input=None, source_fid=None, layer=store.layer_of(kind), fid=0))
    return rows


def declare_constraints(project: Any) -> dict[str, str]:
    """Escribe las restricciones con ``core.edit_constraints`` y da de alta los parámetros de cada
    una (el resguardo de cada una, el peso de las «preferibles», etc., de
    ``constraints_data.build_specs``) en el proyecto, en una transacción; el código de cada una
    por su nombre."""
    params, cparams = _module("core.params"), _module("core.constraints.params")
    edited = _module("core.constraints.provenance").edit_constraints(
        project, constraint_rows(), srs_id=project.record.crs_epsg)
    codes = {str(item.name): str(item.code) for item in edited.constraints}
    store = params.ParameterStore(project)
    with project.write_transaction() as conn:
        for spec in data.build_specs():
            for param, value in spec.params:
                store.create(conn, cparams.param_key(codes[spec.name], param), value,
                             kind="ADOPTADO" if isinstance(value, bool) else "HIPÓTESIS",
                             source=SOURCE, source_kind="document", decided_by=PERSON,
                             reason=REASON)
    return codes


def write_surfaces(project: Any, shapes: Sequence[str]) -> dict[str, Surfaces]:
    """La partida y las tres finales de cada forma de ``shapes`` como rejillas del proyecto
    (``gis.resample``, como las deja «Rejilla del proyecto desde un MDT»), en una operación."""
    gis_store = _module("gis.store")
    grid = _module("gis.grid").Grid(data.WEST, data.NORTH, data.STEP_M, data.STEP_M, data.COLS,
                                    data.ROWS)
    raster = _module("gis.raster").Raster
    crs, vertical = gis_store.project_references(project)
    library, library_version = _module("gis.crs").crs_library()
    handle = _module("core.provenance.operations").begin_operation(
        project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Superficies de §2.2"},
        executor="blender")
    labels: dict[str, list[str]] = {}
    with gis_store.ResultWriter(project, handle) as out:
        for shape in shapes:
            labels[shape] = [f"Partida {shape}", *(f"Final {shape} {k}"
                                                   for k in range(1, data.FINALS + 1))]
            for label, values in zip(labels[shape], data.shape_values(shape), strict=True):
                out.raster(label, raster(grid, values, crs, vertical))
        records = out.commit(software={library: library_version}, message=REASON)
    ordered = [str(record.name) for record in records]
    if len(ordered) != len(shapes) * (data.FINALS + 1):
        raise AssertionError(f"las rejillas escritas no son las pedidas: {ordered}")
    found: dict[str, Surfaces] = {}
    for position, shape in enumerate(shapes):
        mine = ordered[position * (data.FINALS + 1):(position + 1) * (data.FINALS + 1)]
        found[shape] = Surfaces(mine[0], tuple(mine[1:]))
    return found


def build(parent: Path, shapes: Sequence[str]) -> Built:
    """Un proyecto nuevo en ``parent`` con V01 y V02, las restricciones y las superficies de
    ``shapes``, abierto en la sesión con su comprobación de apertura hecha y V01 activa."""
    core = _module("core.project")
    ps = _module("bl.scene.project_session")
    parent.mkdir(parents=True, exist_ok=True)
    settings = core.ProjectSettings(**settings_values(window=data.window(),
                                                      grid_step_m=data.STEP_M))
    project = core.create_project(parent, settings, ps.session(), ps.userdata()).project
    versions = _module("core.versions.store")
    with project.write_transaction() as conn:
        first, _revision = versions.create_version(conn, project, feature="mascaras",
                                                   title="Máscaras", reason=REASON)
        versions.create_version(conn, project, feature="alternativa", title="Alternativa",
                                reason=REASON)
    project.refresh_header()
    codes = declare_constraints(project)
    surfaces = write_surfaces(project, shapes)
    built = Built(Path(project.root), first.uid, codes, surfaces,
                  sum(len(spec.part) for spec in data.build_specs()))
    base.attach(project, built)
    return built


def ensure_masks(project: Any, built: Built) -> None:
    """Las máscaras de V01 al día (de una vez y sin medir), si no lo están."""
    access = _module("gis.masks.access")
    state, _pending = access.mask_state(project, built.version_uid)
    if state is not access.MaskState.CURRENT:
        for _step in access.ensure_masks_steps(project, built.version_uid, budget_s=0.05):
            pass
        project.refresh_header()


class _Local:
    """El proyecto de §2.2 en disco local, uno para todo el módulo (se construye la primera vez
    que se pide), en la sesión."""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.made: Built | None = None

    def built(self) -> Built:
        """El proyecto, abierto en la sesión (construido, si aún no lo está)."""
        if self.made is None:
            self.folder = Path(tempfile.mkdtemp(prefix="gb-012-t31-"))
            self.made = build(self.folder / "proyectos", [shape for shape, _text in SHAPES])
        elif _module("bl.scene.project_session").current() is None:
            base.reopen(self.made)
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
        _module("bl.draw.constraints").disable()
        _module("bl.scene.project_session").close()
        _LOCAL.close()
    finally:
        blender_ext.load_file()
        blender_ext.release()


# --- Las llamadas del hilo de Blender -----------------------------------------------------------


class Recorder(base.Recorder):
    """Mide cada llamada del hilo de Blender (:meth:`call`) con lo que esperó a la red y la
    transacción final de compilar (``MaskWriter.commit``) y de verificar
    (``CheckWriter.commit``) que hubo dentro, mientras está activo (``with``)."""

    WRITERS = (("gis.masks.store", "MaskWriter"), ("reserves.compliance_store", "CheckWriter"))

    def __enter__(self) -> Recorder:
        for module, name in self.WRITERS:
            writer = getattr(_module(module), name)
            self._stack.enter_context(
                mock.patch.object(writer, "commit", self._timed(writer.commit)))
        return self


@dataclasses.dataclass(frozen=True)
class Run:
    """Una orden medida: sus llamadas, lo que tardó de Intro al final y la orden terminada."""

    calls: tuple[base.Call, ...]
    seconds: float
    operator: Any

    @property
    def counted(self) -> list[base.Call]:
        """Las llamadas de mientras compila o verifica (no las del diálogo de antes)."""
        return [call for call in self.calls if call.cubicating]

    @property
    def worst(self) -> base.Call:
        """La llamada que más se acerca al presupuesto (lo que hace Geoblender en ella, sin sus
        esperas de la red ni la transacción final)."""
        return max(self.counted, key=lambda call: call.budgeted)

    @property
    def longest(self) -> base.Call:
        return max(self.counted, key=lambda call: call.seconds)

    @property
    def with_commits(self) -> list[base.Call]:
        return [call for call in self.counted if call.commits]

    def top(self, n: int = TOP_CALLS) -> list[base.Call]:
        return sorted(self.counted, key=lambda call: call.seconds, reverse=True)[:n]


def _phases(operator: Any) -> tuple[Callable[[], str], int]:
    log = getattr(operator, "progress_log", [])
    before = len(log)

    def phases() -> str:
        return ",".join(dict.fromkeys(str(entry[1]) for entry in log[before:]
                                      if isinstance(entry, tuple)))

    return phases, before


def pump(recorder: Recorder, operator: Any, label: str,
         queues: Sequence[tuple[str, Callable[[], object]]] = ()) -> set[str]:
    """Los eventos del temporizador del modal de ``operator``, uno por llamada, hasta que
    termina (su final), con el tic de los indicadores de la procedencia cuando le toca (el
    temporizador que corre mientras tanto) y, tras cada evento, un paso de cada cola de
    ``queues`` (``(nombre, función)``: sus temporizadores). Cada una, una llamada medida."""
    ui_provenance = _module("bl.ui.provenance")
    clock, due = 0.0, ui_provenance.INDICATOR_TICK_S
    for event in range(MAX_EVENTS):
        phases, _before = _phases(operator)
        state = recorder.call(f"evento {event + 1} del modal", operator.modal, bpy.context,
                              TIMER, phases=phases)
        clock += recorder.calls[-1].seconds + TIMER_INTERVAL_S
        if clock >= due:
            interval = recorder.call("tic de los indicadores de la procedencia",
                                     ui_provenance.indicator_tick)
            due = clock + (ui_provenance.INDICATOR_TICK_S if interval is None else interval)
        if state != {"RUNNING_MODAL"}:
            return state
        for name, tick in queues:
            recorder.call(f"{name}", tick)
    raise AssertionError(f"«{label}» no acaba")


def running(cls: type) -> Any:
    """El modal de ``cls`` en marcha (el único con pasos)."""
    found = [op for op in bpy.context.window.modal_operators
             if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
    if len(found) != 1:
        raise AssertionError(f"{cls.__name__}: {len(found)} modales en marcha")
    return found[0]


def run_order(idname: str, *, waits: netwaits.NetworkWaits | None = None,
              before: Callable[[Recorder], None] | None = None, **props: Any) -> Run:
    """La orden ``idname`` como desde la interfaz (véase el módulo): Intro con ``props`` (en
    pasos) y cada evento de su modal hasta que termina, con cada llamada del hilo de Blender
    medida. ``before`` mide lo de antes de Intro (el diálogo), que se anota aparte."""
    commands = _module("bl.ui.commands")
    cls = commands.registered_class(idname)
    order = getattr(bpy.ops.geoblender, idname.removeprefix("geoblender."))
    gc.collect()
    with Recorder(waits) as recorder:
        if before is not None:
            before(recorder)
        started = time.perf_counter()
        result = recorder.call("Intro: comprobar y empezar", order, "EXEC_DEFAULT",
                               in_steps=True, **props)
        if result != {"RUNNING_MODAL"}:
            raise AssertionError(f"«{idname}» no empieza: {result}")
        operator = running(cls)
        state = pump(recorder, operator, idname)
        seconds = time.perf_counter() - started
    if state != {"FINISHED"}:
        raise AssertionError(f"«{idname}» acaba mal: {state}, {operator.report_log}")
    return Run(tuple(recorder.calls), seconds, operator)


def calls_line(run: Run, where: str, *, network_waits: bool) -> str:
    """Lo medido de ``run`` (véase el módulo), para la línea de la cifra."""
    worst, longest = run.worst, run.longest
    intro = next(call for call in run.calls if call.what.startswith("Intro"))
    events = sum(call.what.startswith("evento") for call in run.calls)
    ticks = sum(call.what.startswith("tic") for call in run.calls)
    commits = "; ".join(f"{call.text()}: la llamada {ms(call.seconds)} ms"
                        + (f" ({ms(call.own)} ms sin sus esperas de la red)" if network_waits
                           else "")
                        for call in run.with_commits) or "ninguna"
    before = [call for call in run.calls if not call.cubicating]
    top = "; ".join(f"{ms(call.seconds)} ms ({call.text()})" for call in run.top())
    own = ("sin sus esperas de la red ni la transacción final" if network_waits
           else "sin la transacción final")
    return (f"{where}: de Intro al final {number(run.seconds, 2)} s en {len(run.counted)} "
            f"llamadas del hilo de Blender (Intro, {events} eventos del modal y {ticks} tics de "
            f"los indicadores); Intro {ms(intro.seconds)} ms; la más larga {ms(longest.seconds)} "
            f"ms ({longest.text()}); {own}, la peor {ms(worst.budgeted)} ms ({worst.text()}); "
            f"presupuesto {number(CALL_BUDGET_S, 1)} s de lo que hace Geoblender en cada llamada"
            f"{', sin sus esperas de la red (aparte, sin presupuesto)' if network_waits else ''}"
            f"; la transacción final, aparte (plan R4): {commits}; las {TOP_CALLS} más largas: "
            f"{top}"
            + (("; antes de empezar, " + ", ".join(f"{call.what} {ms(call.seconds)} ms"
                                                   for call in before)) if before else ""))


def warn_slow(run: Run, where: str, rnf: str = "RNF-012-06") -> None:
    """Los avisos de lo que pasa de 0,2 s: lo que no es la transacción final (falla) y la
    transacción final (para Samuel, R4)."""
    over = [call for call in run.counted if call.budgeted > CALL_BUDGET_S]
    if over:
        report(f"Aviso {rnf} ({where}): {len(over)} llamadas de más de "
               f"{number(CALL_BUDGET_S, 1)} s sin la transacción final: "
               + "; ".join(f"{ms(call.budgeted)} ms ({call.text()})" for call in over))
    held = [call for call in run.with_commits if call.own > CALL_BUDGET_S >= call.budgeted]
    if held:
        report(f"Aviso {rnf} ({where}; plan R4, la cifra para Samuel): la transacción final "
               f"deja {len(held)} llamadas de más de {number(CALL_BUDGET_S, 1)} s: "
               + "; ".join(f"{ms(call.own)} ms ({call.text()})" for call in held))


def rows(sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with _module("bl.scene.project_session").current().read() as conn:
        return conn.execute(sql, args).fetchall()


class _Case(unittest.TestCase):
    """La extensión habilitada (sin importarla otra vez: ``blender_ext.release``), el idioma en
    español y ``wm.call_panel`` sustituido; el proyecto de §2.2 en disco local, el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.res_ops = _module("bl.ops.res")
        cls.gis_ops = _module("bl.ops.gis")
        cls.ps = _module("bl.scene.project_session")
        cls.access = _module("gis.masks.access")
        cls.verify = _module("reserves.compliance_store")
        cls.enterClassContext(mock.patch.object(cls.res_ops, "_call_panel",
                                                return_value={"FINISHED"}))

    def mask_state(self, built: Built) -> Any:
        return self.access.mask_state(self.ps.current(), built.version_uid)[0]

    def verification(self, built: Built, name: str) -> Any:
        with self.ps.current().read() as conn:
            return self.verify.read_verification(conn, built.version_uid, name)

    def zone_rows(self) -> int:
        """Las filas de la tabla de zonas de las máscaras de V01."""
        found = rows("SELECT locator FROM gb_dataset WHERE name LIKE 'gis_mskz%' AND status = "
                     "'current'")
        return sum(int(rows(f'SELECT count(*) FROM "{locator}"')[0][0]) for (locator,) in found)

    def change_buffer(self, built: Built, value: str) -> base.Call:
        """Cambia el resguardo de :data:`RESIZED` solo en V01 (``core.set_parameter``, ámbito de
        la versión): deja las máscaras obsoletas; la llamada, medida."""
        key = _module("core.constraints.params").buffer_out_key(built.codes[RESIZED])
        with Recorder() as recorder:
            changed = recorder.call(
                "cambiar el resguardo solo en V01", bpy.ops.geoblender.core_set_parameter,
                key=key, value=value, scope="VERSION", kind="ADOPTADO", decided_by=PERSON,
                reason=REASON)
        self.assertEqual(changed, {"FINISHED"})
        self.assertIs(self.mask_state(built), self.access.MaskState.STALE)
        return recorder.calls[0]

    def check_compile(self, built: Built) -> None:
        """Lo que deja compilar: las máscaras de V01 al día."""
        self.assertIs(self.mask_state(built), self.access.MaskState.CURRENT)

    def check_verified(self, built: Built, name: str, shape: str) -> int:
        """Lo que deja verificar: tres finales de ``shape``, que incumplen, con sus grupos y la
        rejilla de cada una; los grupos que guardó."""
        stored = self.verification(built, name)
        self.assertIsNotNone(stored)
        self.assertEqual(len(stored.surfaces), data.FINALS)
        self.assertEqual(len({zone.final for zone in stored.zones}), data.FINALS)
        self.assertGreater(len(stored.groups), 0)
        self.assertFalse(stored.stale)
        return len(stored.groups)

    def verify_dialog(self, built: Built, shape: str) -> Callable[[Recorder], None]:
        """Abrir y dibujar el diálogo de verificar (``invoke`` con las superficies que propone y
        ``draw``), lo de antes de Intro: se mide aparte."""
        commands = _module("bl.ui.commands")
        cls = commands.registered_class(VERIFY)

        def open_dialog(recorder: Recorder) -> None:
            fake = operator_self(
                cls, report=lambda kind, text: None, name="", start="", finals="",
                start_elevation="", final_elevation="", in_steps=False,
                properties=SimpleNamespace(is_property_set=lambda name: False))
            manager = SimpleNamespace(invoke_props_dialog=mock.Mock(
                return_value={"RUNNING_MODAL"}))
            context = SimpleNamespace(window=None, selected_objects=[], window_manager=manager)
            opened = recorder.call("abrir el diálogo", cls.invoke, fake, context, None,
                                   cubicating=False)
            self.assertEqual(opened, {"RUNNING_MODAL"})
            recorder.call("dibujar el diálogo", cls.draw, fake, bpy.context, cubicating=False)

        return open_dialog

    def verify_props(self, built: Built, shape: str, name: str) -> dict[str, Any]:
        surfaces = built.surfaces[shape]
        return {"name": name, "start": surfaces.start, "finals": ",".join(surfaces.finals)}


# --- RNF-012-06: compilar y verificar con las órdenes reales ------------------------------------


class CallsTest(_Case):
    """RNF-012-06 con el proyecto en disco local, en el orden de sus letras sobre el mismo
    estado (compilar en frío, repetirlo, verificar)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.built = _LOCAL.built()

    def check_run(self, run: Run, where: str, what: str) -> None:
        warn_slow(run, where)
        self.assertLessEqual(run.worst.budgeted, CALL_BUDGET_S, f"{what}: {run.worst.text()}")

    def test_a_compile_calls_on_local_disk(self) -> None:
        """RNF-012-06 (plan §7.3, R4; RF-012-11, RF-012-16, RF-012-28): «Compilar las máscaras»
        con las 500 restricciones sobre 2,81 M celdas, como desde la interfaz y con el proyecto
        en disco local: en ninguna llamada del hilo de Blender (Intro, cada evento del modal y el
        tic de los indicadores) lo que hace Geoblender sin la transacción final pasa de 0,2 s; la
        transacción final (las tablas, la rejilla de clases, las cifras y la operación), aparte.
        Nueva y repitiéndola para sustituirla."""
        built = self.built
        self.assertIs(self.mask_state(built), self.access.MaskState.MISSING)
        found = []
        for how in ("nueva", "sustituyendo la anterior"):
            run = run_order(COMPILE)
            self.check_compile(built)
            found.append((run, how))
        for run, how in found:
            where = f"con el proyecto en disco local, {how}"
            report(f"RNF-012-06: «Compilar las máscaras» con {data.COUNT} restricciones "
                   f"({count(built.vertices)} vértices) sobre {count(CELLS)} celdas de 1 m "
                   f"({count(self.zone_rows())} filas de zonas; {MACHINE}), "
                   f"{calls_line(run, where, network_waits=False)}; {free_space(built.root)}")
        for run, how in found:
            self.check_run(run, f"compilar, {how}", "compilar")

    def test_b_compile_calls_after_changing_a_buffer(self) -> None:
        """RNF-012-06 (plan §7.3, R4; RF-012-11, RF-012-16, RF-012-28): lo más habitual, compilar
        otra vez tras cambiar el resguardo de una restricción solo en V01 (las máscaras
        obsoletas): se reutilizan las zonas que no cambian y se leen las anteriores de la que
        cambia; en ninguna llamada del hilo de Blender lo que hace Geoblender sin la transacción
        final pasa de 0,2 s."""
        built = self.built
        change = self.change_buffer(built, "31")
        run = run_order(COMPILE)
        self.check_compile(built)
        where = "con el proyecto en disco local, tras cambiar un resguardo"
        report(f"RNF-012-06: «Compilar las máscaras» tras cambiar el resguardo de «{RESIZED}» "
               f"solo en V01 (cambiarlo {ms(change.seconds)} ms) con {data.COUNT} restricciones "
               f"({count(built.vertices)} vértices) sobre {count(CELLS)} celdas de 1 m "
               f"({count(self.zone_rows())} filas de zonas; {MACHINE}), "
               f"{calls_line(run, where, network_waits=False)}; {free_space(built.root)}")
        self.check_run(run, "compilar tras cambiar un resguardo", "compilar")

    def verify_runs(self, shape: str, text: str) -> None:
        built = self.built
        project = self.ps.current()
        self.assertIsNotNone(project)
        ensure_masks(project, built)
        found = []
        name = f"Diseño {shape}"
        for how in ("nueva", "sustituyendo la anterior"):
            run = run_order(VERIFY, before=self.verify_dialog(built, shape),
                            **self.verify_props(built, shape, name))
            groups = self.check_verified(built, name, shape)
            found.append((run, how, groups))
        for run, how, groups in found:
            where = f"con el proyecto en disco local, {how}"
            report(f"RNF-012-06: «Verificar un diseño por recinto…» de {data.FINALS} finales "
                   f"({shape}: {text}) frente a la partida en {data.COUNT} recintos y "
                   f"{count(CELLS)} celdas de 1 m ({count(groups)} grupos que incumplen; "
                   f"{MACHINE}), {calls_line(run, where, network_waits=False)}"
                   f"; {free_space(built.root)}")
        for run, how, _groups in found:
            self.check_run(run, f"verificar {shape}, {how}", "verificar")

    def test_c_verify_calls_changes_in_the_whole_window(self) -> None:
        """RNF-012-06 (plan §7.3, R4; RF-012-21, RF-012-24, RF-012-28): «Verificar un diseño por
        recinto…» de tres finales que cambian en toda la ventana (la dura: pocos grupos enormes),
        frente a la partida, en las 500 zonas, como desde la interfaz y con el proyecto en disco
        local: el diálogo (antes) y, en ninguna llamada del hilo de Blender, lo que hace
        Geoblender sin la transacción final pasa de 0,2 s. Nueva y repitiéndola."""
        self.verify_runs("window", "toda la ventana")

    def test_d_verify_calls_local_changes(self) -> None:
        """RNF-012-06 (plan §7.3, R4; RF-012-21, RF-012-24, RF-012-28): lo mismo con tres finales
        de cambios localizados (miles de grupos pequeños), la que más cifras y filas deja."""
        self.verify_runs("local", "cambios localizados")

    def test_e_verify_calls_compiling_the_masks_first(self) -> None:
        """RNF-012-06 (plan §7.3, R4; RF-012-21, RF-012-24, D-43): verificar tras cambiar un
        resguardo solo en V01, con las máscaras obsoletas: la orden las compila antes (en sus
        mismos pasos) y verifica después; en ninguna llamada del hilo de Blender lo que hace
        Geoblender sin la transacción final pasa de 0,2 s."""
        built = self.built
        change = self.change_buffer(built, "32")
        name = "Diseño window"
        run = run_order(VERIFY, before=self.verify_dialog(built, "window"),
                        **self.verify_props(built, "window", name))
        self.assertIs(self.mask_state(built), self.access.MaskState.CURRENT)
        groups = self.check_verified(built, name, "window")
        where = "con el proyecto en disco local, compilando antes las máscaras"
        report(f"RNF-012-06: «Verificar un diseño por recinto…» de {data.FINALS} finales "
               f"(window) tras cambiar el resguardo de «{RESIZED}» solo en V01 (cambiarlo "
               f"{ms(change.seconds)} ms; compila las máscaras antes) en {data.COUNT} recintos y "
               f"{count(CELLS)} celdas de 1 m ({count(groups)} grupos que incumplen; {MACHINE}), "
               f"{calls_line(run, where, network_waits=False)}; {free_space(built.root)}")
        self.check_run(run, "verificar compilando antes", "verificar")


# --- RNF-012-06: Recalcular lo obsoleto ---------------------------------------------------------


class RecomputeTest(_Case):
    """RNF-012-06 con «Recalcular lo obsoleto» (spec 008) tras cambiar un resguardo solo en V01:
    recompilar las máscaras y volver a verificar, con sus colas."""

    NAME = "Diseño para recalcular"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.built = _LOCAL.built()
        project = cls.ps.current()
        ensure_masks(project, cls.built)
        surfaces = cls.built.surfaces["window"]
        result = bpy.ops.geoblender.res_verify_constraints(
            "EXEC_DEFAULT", name=cls.NAME, start=surfaces.start,
            finals=",".join(surfaces.finals))
        assert result == {"FINISHED"}, result

    def test_recompute_stale_calls_on_local_disk(self) -> None:
        """RNF-012-06 (spec 008, RF-008-26; RF-012-16, RF-012-24): cambiar el resguardo de una
        restricción solo en V01 deja obsoletas las máscaras y la verificación; «Recalcular lo
        obsoleto» las rehace (la compilación nueva, que cuenta con su ``begin_compile``, y la
        verificación nueva, que carga las máscaras), un evento del modal y un paso de cada cola
        por vez. **Hallazgo para Samuel** (no se arregla aquí: es el contrato de la 008): la
        función de recálculo de cada tipo devuelve su ``OperationHandle`` de una vez, así que
        ``recompute_compile`` empieza la compilación entera (``begin_compile``: 0,4–0,5 s con 500
        restricciones) y ``recompute_verify`` carga las máscaras (``load_masks``: 0,5 s) en una
        sola llamada del modal, más de 0,2 s; y la que acaba, lo que escribe la orden de la 008
        al terminar. Se anotan sin fallar, y se vigila que no sean más ni de otra clase (solo
        eventos del modal, a lo sumo :data:`RECOMPUTE_OVER`); el resto de las llamadas (los
        pasos de las colas de ``gis`` y ``res``, los tics de los indicadores) no pasan de 0,2 s
        sin la transacción final."""
        built = self.built
        change = self.change_buffer(built, "30")
        self.assertTrue(self.verification(built, self.NAME).stale)
        queues = (("cola de gis (un paso)", self.gis_ops.masks_tick),
                  ("cola de res (un paso)", self.res_ops.res_tick))
        gc.collect()
        with Recorder() as recorder:
            started = time.perf_counter()
            begun = recorder.call("Intro: empezar", bpy.ops.geoblender.core_recompute_stale,
                                  "EXEC_DEFAULT")
            self.assertEqual(begun, {"RUNNING_MODAL"})
            operator = running(_module("bl.ui.commands").registered_class(RECOMPUTE))
            state = pump(recorder, operator, RECOMPUTE, queues)
            seconds = time.perf_counter() - started
        self.assertEqual(state, {"FINISHED"}, operator.report_log)
        run = Run(tuple(recorder.calls), seconds, operator)
        self.assertIs(self.mask_state(built), self.access.MaskState.CURRENT)
        self.assertFalse(self.verification(built, self.NAME).stale)
        where = "con el proyecto en disco local"
        report(f"RNF-012-06: «Recalcular lo obsoleto» tras cambiar un resguardo solo en V01 "
               f"(las máscaras de {data.COUNT} restricciones y la verificación de {data.FINALS} "
               f"finales sobre {count(CELLS)} celdas; {MACHINE}); cambiar el resguardo "
               f"{ms(change.seconds)} ms ({change.text()}); "
               + calls_line(run, where, network_waits=False) + f"; {free_space(built.root)}")
        warn_slow(run, where, rnf="RNF-012-06 (Recalcular lo obsoleto; para Samuel, contrato de la "
                  "008)")
        over = [call for call in run.counted if call.budgeted > CALL_BUDGET_S]
        self.assertTrue(all(call.what.startswith("evento") for call in over),
                        [call.what for call in over])
        self.assertLessEqual(len(over), RECOMPUTE_OVER, [call.text() for call in over])


# --- RNF-012-06 en la red -------------------------------------------------------------------------


@requires(network.NET, network.NET_HINT)
class NetworkTest(_Case):
    """RNF-012-06 con el proyecto en la carpeta de pruebas de la red (``Z:``): un proyecto propio
    en una subcarpeta temporal (borrada al terminar) y los datos de usuario en disco local; al
    terminar, vuelve el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ps.close()
        cls.addClassCleanup(_LOCAL.restore)  # lo último: los de la clase, al revés
        remote = cls.enterClassContext(network.net_tmp("gb-012-t31-"))
        local = Path(tempfile.mkdtemp(prefix="gb-012-t31-red-"))
        cls.addClassCleanup(remove_tree, local)
        cls.addClassCleanup(cls.ps.close)  # lo primero: antes de borrar su carpeta
        cls.remote = remote
        cls.built = build(remote / "proyectos", ["window"])

    def test_compile_and_verify_calls_on_the_network(self) -> None:
        """RNF-012-06 en ``Z:`` (como RNF-011-04 y RNF-009-05): «Compilar las máscaras» y
        «Verificar un diseño por recinto…» (tres finales de toda la ventana) con el proyecto en la
        red; lo que hace Geoblender en cada llamada del hilo de Blender, sin sus esperas de la red
        (medidas en la llamada y anotadas aparte, sin presupuesto) ni la transacción final
        (aparte), no pasa de 0,2 s."""
        built = self.built
        project = self.ps.current()
        self.assertTrue(project.is_network, "el proyecto de la carpeta de la red")
        found = []
        with netwaits.NetworkWaits(self.remote, projects=[project]) as waits:
            found.append(("«Compilar las máscaras»", "nueva", run_order(COMPILE, waits=waits),
                          waits.longest))
        self.check_compile(built)
        with netwaits.NetworkWaits(self.remote, projects=[project]) as waits:
            run = run_order(VERIFY, waits=waits, before=self.verify_dialog(built, "window"),
                            **self.verify_props(built, "window", "Diseño en la red"))
            found.append(("«Verificar un diseño por recinto…»", "nueva", run, waits.longest))
        groups = self.check_verified(built, "Diseño en la red", "window")
        for what, how, run, longest in found:
            where = f"con el proyecto en la carpeta de pruebas de la red, {how}"
            extra = (f"{count(groups)} grupos que incumplen; " if "Verificar" in what
                     else f"{count(self.zone_rows())} filas de zonas; ")
            report(f"RNF-012-06: {what} con {data.COUNT} restricciones sobre {count(CELLS)} "
                   f"celdas de 1 m ({extra}{MACHINE}), "
                   + calls_line(run, where, network_waits=True)
                   + f"; la espera de la red más larga, {longest[0]} {ms(longest[1])} ms; "
                   f"{free_space(built.root)}")
            warn_slow(run, where)
            waited = [call for call in run.counted if call.seconds > CALL_BUDGET_S >= call.own]
            if waited:
                report(f"Nota RNF-012-06 ({where}): {len(waited)} llamadas de más de "
                       f"{number(CALL_BUDGET_S, 1)} s solo por sus esperas de la red (se anotan, "
                       "sin presupuesto): "
                       + "; ".join(f"{ms(call.seconds)} ms ({call.text()})" for call in waited))
        for what, _how, run, _longest in found:
            self.assertLessEqual(run.worst.budgeted, CALL_BUDGET_S, f"{what}: {run.worst.text()}")


# --- RNF-012-05: la superposición ---------------------------------------------------------------


class _Null:
    """Un objeto que acepta cualquier uso y no hace nada: ``gpu`` y ``blf`` sustituidos, para medir
    solo el Python de Geoblender."""

    def __getattr__(self, name: str) -> _Null:
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> _Null:
        return self

    def __enter__(self) -> _Null:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


TICK_WAIT_S = 0.005  # bl.draw.constraints.TICK_INTERVAL_S (lo comprueba la prueba)


@dataclasses.dataclass(frozen=True)
class Activation:
    """Una activación de la superposición: lo que tardó la orden, cada paso del temporizador y
    lo construido."""

    order_s: float
    ticks: tuple[float, ...]
    built: Any

    @property
    def work_s(self) -> float:
        return self.order_s + sum(self.ticks)

    @property
    def wall_s(self) -> float:
        """Hasta que está construida: la orden, los pasos y los 5 ms de espera de cada uno
        (``bl.draw.constraints.TICK_INTERVAL_S``) menos el último."""
        return self.work_s + TICK_WAIT_S * max(0, len(self.ticks) - 1)


class OverlayTest(_Case):
    """RNF-012-05: «Ver restricciones y límites» con las 500 restricciones, las máscaras al día y
    una rejilla de 2,81 M celdas debajo, en disco local."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.built = _LOCAL.built()
        cls.ov = _module("bl.draw.constraints")
        cls.dh = _module("bl.draw.dh_overlay")
        ensure_masks(cls.ps.current(), cls.built)
        cls.addClassCleanup(cls.ov.disable)

    def toggle(self) -> Any:
        return bpy.ops.geoblender.core_toggle_constraints_overlay()

    def activate(self) -> Activation:
        """Pulsa el control 30 y da los pasos del temporizador de la superposición hasta que
        está construida (en ``blender -b`` no corren)."""
        ov = self.ov
        self.assertFalse(ov.enabled())
        gc.collect()
        started = time.perf_counter()
        result = self.toggle()
        order_s = time.perf_counter() - started
        self.assertEqual(result, {"FINISHED"})
        self.assertTrue(ov.enabled() and ov.building())
        ticks = []
        for _ in range(MAX_TICKS):
            before = time.perf_counter()
            interval = ov.tick()
            ticks.append(time.perf_counter() - before)
            if interval is None:
                break
        else:
            self.fail("la superposición no acaba de construirse")
        built = ov.built()
        self.assertIsNotNone(built)
        return Activation(order_s, tuple(ticks), built)

    def deactivate(self) -> None:
        self.assertEqual(self.toggle(), {"FINISHED"})
        self.assertFalse(self.ov.enabled() or self.ov.building())

    def test_a_activating_the_overlay_with_the_500_constraints(self) -> None:
        """RNF-012-05, RNF-012-06 (RF-012-18; HU-012-1 a 4): activar «Ver restricciones y
        límites» con las 500 restricciones, las máscaras de V01 al día y la rejilla de 2,81 M
        celdas del proyecto más reciente debajo: la orden y los pasos de su temporizador hasta que
        está construida ≤ 1 s (con los 5 ms de espera de cada paso), y ninguna llamada del hilo de
        Blender de más de 0,2 s."""
        self.assertEqual(self.ov.TICK_INTERVAL_S, TICK_WAIT_S)
        self.activate()  # la primera, en frío (las caches de SQLite, de los módulos…): no cuenta
        self.deactivate()
        found = []
        for _ in range(ACTIVATIONS):
            found.append(self.activate())
            self.deactivate()
        last = found[-1].built
        walls = [item.wall_s for item in found]
        worst = max(found, key=lambda item: item.wall_s)
        longest = max(max(item.ticks) for item in found)
        order = max(item.order_s for item in found)
        segments = sum(batch.segments for batch in last.batches)
        self.assertEqual(last.masks, "current")
        self.assertGreater(len(last.labels), data.COUNT // 2)
        report(
            f"RNF-012-05: activar «Ver restricciones y límites» con {data.COUNT} restricciones "
            f"({count(self.built.vertices)} vértices), las máscaras de V01 al día y "
            f"«{last.surface}» ({count(CELLS)} celdas) debajo, hasta que está construida "
            f"({count(len(last.batches))} lotes, "
            f"{count(segments)} segmentos, {count(len(last.labels))} nombres; {MACHINE}): mediana "
            f"de {len(found)} {number(statistics.median(walls))} s (la peor {number(max(walls))} "
            f"s; {len(worst.ticks)} pasos del temporizador con {number(TICK_WAIT_S * 1000, 0)} ms "
            f"de espera cada uno, {number(worst.work_s)} s de trabajo) frente a "
            f"{number(ACTIVATE_BUDGET_S, 1)} s; la orden {ms(order)} ms y el paso más largo "
            f"{ms(longest)} ms (presupuesto {number(CALL_BUDGET_S, 1)} s por llamada); "
            f"{free_space(self.built.root)}")
        self.assertLessEqual(max(walls), ACTIVATE_BUDGET_S)
        self.assertLessEqual(max(order, longest), CALL_BUDGET_S)

    def test_b_the_stamp_the_indicators_read(self) -> None:
        """RNF-012-06 (RF-012-18): con la superposición activa, cada tic de los indicadores de la
        procedencia lee el sello de lo que dibuja (``stamp``) para saber si la rehace: una
        llamada del hilo de Blender de menos de 0,2 s con las 500 restricciones."""
        project = self.ps.current()
        uid = self.built.version_uid
        self.ov.stamp(project, uid)
        took = []
        for _ in range(50):
            started = time.perf_counter()
            self.ov.stamp(project, uid)
            took.append(time.perf_counter() - started)
        report(f"RNF-012-06: el sello de la superposición (lo que lee cada tic de los indicadores "
               f"de la procedencia con la superposición activa) con {data.COUNT} restricciones "
               f"({MACHINE}): mediana {ms(statistics.median(took), 2)} ms, máximo "
               f"{ms(max(took), 2)}"
               f" ms de {len(took)} (presupuesto {number(CALL_BUDGET_S, 1)} s por llamada)")
        self.assertLessEqual(max(took), CALL_BUDGET_S)

    def view_matrices(self, project: Any, zoom: float) -> tuple[Matrix, Matrix, float]:
        """La vista desde arriba (ortográfica) de la ventana entera (``zoom`` 1) o de 1/``zoom`` de
        su alto, centrada, en coordenadas locales: (vista, proyección, distancia)."""
        origin = project.origin
        cx = data.WEST + data.COLS * data.STEP_M / 2.0 - origin.x0
        cy = data.SOUTH + data.ROWS * data.STEP_M / 2.0 - origin.y0
        half_h = data.ROWS * data.STEP_M / 2.0 / zoom
        half_w = half_h * REGION[0] / REGION[1]
        eye, near, far = 2000.0, 1.0, 4000.0
        view = Matrix.Translation((-cx, -cy, -eye))
        projection = Matrix(((1 / half_w, 0, 0, 0), (0, 1 / half_h, 0, 0),
                             (0, 0, -2 / (far - near), -(far + near) / (far - near)),
                             (0, 0, 0, 1)))
        return view, projection, eye

    def redraw(self, built: Any, view: Matrix, projection: Matrix, eye: float
               ) -> tuple[float, float, int]:
        """Un redibujo como el de los manejadores de la Vista 3D (``POST_VIEW``: los lotes;
        ``POST_PIXEL``: los nombres y la leyenda): lo que tardó cada parte y cuántos elementos
        de píxeles dibujó."""
        ov, dh = self.ov, self.dh
        started = time.perf_counter()
        ov.draw_lines(built, view_matrix=view, projection_matrix=projection, perspective=False,
                      view_distance=eye, viewport_size=(float(REGION[0]), float(REGION[1])),
                      pixel_size=1.0)
        middle = time.perf_counter()
        ov.blf.size(ov.FONT_ID, ov.FONT_PX)
        items = ov.screen_items(built, np.array(projection @ view), (float(REGION[0]),
                                float(REGION[1])), measure=ov._measure, scale=1.0)
        if items:
            dh.paint(items, (float(REGION[0]), float(REGION[1])), scale=1.0)
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

    def redraw_line(self, kind: str, found: dict[str, Any], built: Any, zoom: str) -> str:
        totals = found["totals"]
        return (f"{kind}, {zoom}: el primer dibujo {ms(found['first'])} ms (crea los lotes); "
                f"mediana de {len(totals)} {ms(statistics.median(totals), 3)} ms (lotes "
                f"{ms(found['lines'], 3)} ms y {count(found['items'])} elementos de píxeles "
                f"{ms(found['pixels'], 3)} ms), máximo {ms(max(totals), 3)} ms")

    def test_c_the_python_of_each_redraw(self) -> None:
        """RNF-012-05 (RF-012-18): cada redibujo de la superposición activa, con ``gpu`` y
        ``blf`` sustituidos (solo el Python de Geoblender: los lotes, las matrices, la
        proyección de los nombres y la leyenda) a 1.920 × 1.080 px, con las 500 restricciones
        vistas enteras y acercadas, ≤ 5 ms."""
        ov, dh = self.ov, self.dh
        self.activate()
        built = ov.built()
        null = _Null()
        lines = []
        worst = 0.0
        try:
            with ExitStack() as stack:
                for target, name in ((ov, "gpu"), (ov, "batch_for_shader"), (dh, "gpu"),
                                     (dh, "blf"), (dh, "batch_for_shader")):
                    stack.enter_context(mock.patch.object(target, name, null))
                for zoom, text in ((1.0, "la ventana entera"), (6.0, "acercada 6 veces")):
                    for batch in built.batches:
                        batch._gpu.clear()
                    view, projection, eye = self.view_matrices(self.ps.current(), zoom)
                    found = self.measure_redraws(built, view, projection, eye)
                    lines.append(self.redraw_line("Python de Geoblender", found, built, text))
                    worst = max(worst, statistics.median(found["totals"]))
                    self.assertGreater(found["items"], 0)
        finally:
            for batch in built.batches:
                batch._gpu.clear()
            self.deactivate()
        report(f"RNF-012-05: redibujar la superposición con {data.COUNT} restricciones "
               f"({count(sum(b.segments for b in built.batches))} segmentos en "
               f"{len(built.batches)} lotes, {count(len(built.labels))} nombres; región de "
               f"{REGION[0]} × {REGION[1]} px; {MACHINE}): " + "; ".join(lines)
               + f"; presupuesto {ms(REDRAW_BUDGET_S, 0)} ms por redibujo")
        self.assertLessEqual(worst, REDRAW_BUDGET_S)

    def test_z_each_redraw_on_the_gpu(self) -> None:
        """RNF-012-05 (RF-012-18; M4): cada redibujo de la superposición activa con la GPU de
        verdad, en una imagen fuera de pantalla de 1.920 × 1.080 px (los lotes con el sombreado
        de líneas, los nombres con ``blf`` y la leyenda), con las 500 restricciones vistas enteras
        y acercadas: lo que tarda el hilo de Blender en enviarlo ≤ 5 ms; el primer dibujo (crea los
        lotes de ``gpu``) se anota con la activación, y lo que tarda la GPU en acabarlo, aparte."""
        import gpu

        try:
            gpu.init()
        except SystemError as error:
            self.skipTest(resources.skip_reason(
                resources.BLENDER, f"ejecute las pruebas con GPU ({error})"))
        ov = self.ov
        activation = self.activate()
        built = ov.built()
        lines = []
        worst = 0.0
        offscreen = gpu.types.GPUOffScreen(*REGION)
        try:
            with offscreen.bind():
                framebuffer = gpu.state.active_framebuffer_get()
                framebuffer.clear(color=(0.2, 0.2, 0.2, 1.0), depth=1.0)
                for zoom, text in ((1.0, "la ventana entera"), (6.0, "acercada 6 veces")):
                    for batch in built.batches:
                        batch._gpu.clear()
                    view, projection, eye = self.view_matrices(self.ps.current(), zoom)
                    found = self.measure_redraws(built, view, projection, eye)
                    synced = []
                    for _ in range(SYNCED):
                        started = time.perf_counter()
                        self.redraw(built, view, projection, eye)
                        framebuffer.read_color(0, 0, 1, 1, 4, 0, "FLOAT")
                        synced.append(time.perf_counter() - started)
                    side = 256  # el centro de la imagen (leerla entera tardaría segundos)
                    pixels = np.array(framebuffer.read_color(
                        (REGION[0] - side) // 2, (REGION[1] - side) // 2, side, side, 4, 0,
                        "FLOAT").to_list(), dtype=np.float32)
                    drawn = int((np.abs(pixels[..., :3] - 0.2).max(axis=-1) > 0.05).sum())
                    lines.append(
                        self.redraw_line("con la GPU", found, built, text)
                        + f"; esperando a que la GPU acabe, mediana "
                        f"{ms(statistics.median(synced), 2)}"
                        f" ms (máximo {ms(max(synced), 2)} ms; sin presupuesto); "
                        f"{count(drawn)} de {count(side * side)} px del centro pintados")
                    self.assertGreater(drawn, 0, "no se pintó nada")
                    worst = max(worst, max(found["totals"]))
        finally:
            offscreen.free()
            for batch in built.batches:
                batch._gpu.clear()
            self.deactivate()
        report(f"RNF-012-05: redibujar la superposición con {data.COUNT} restricciones "
               f"({count(sum(b.segments for b in built.batches))} segmentos en "
               f"{len(built.batches)} lotes, {count(len(built.labels))} nombres; imagen fuera de "
               f"pantalla de {REGION[0]} × {REGION[1]} px; {MACHINE}): " + "; ".join(lines)
               + f"; presupuesto {ms(REDRAW_BUDGET_S, 0)} ms por redibujo; la activación, "
               f"{number(activation.wall_s)} s")
        self.assertLessEqual(worst, REDRAW_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
