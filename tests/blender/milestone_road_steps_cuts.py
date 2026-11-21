# SPDX-License-Identifier: GPL-3.0-or-later
"""«Pista…» y «Accesibilidad de las pistas…» por pasos, con su avance y Esc (spec 017, T32; HU-017-1, HU-017-3; RF-017-30, RF-015-29, RNF-017-06; plan 017 §5.3.2 y §7.3; comprobación manual M9).

Lo que hace Geoblender en cada llamada del hilo de Blender mientras una pista o una accesibilidad calcula y se crea, y lo que deja Esc. El proyecto es el de ``milestone_road_ops.py`` (60 × 60 m con celdas
de 2 m, V01 y V02, el límite legal, el perímetro, un sector con la búsqueda cerrada, los terrenos ``Suave`` y ``A15``, las capas de la pista y los perfiles de referencia de IMGA, **solo de pruebas**) con
una capa de puntos de entrada y una línea de rotura con Z (el eje del modo «eje 3D»): se paga una vez por clase (≈ 6 s). **«Crear» ya no es de una vez desde la interfaz** (``_CreatesInSteps``:
``Calculation.create_steps``, la transacción final como último paso; la 016 hizo lo mismo con la detección de acopios, T44): cada evento del modal, una llamada de ≤ 0,2 s, y lo que sigue a crear
(la declaración, las máscaras, la capa de entidades y la de ejes de pistas) va en el **mismo** modal. El recorrido de **todos** los eventos es del hito ``milestone_road_steps.py``, que usa las ayudas de
esta clase (:class:`RoadStepsCase`); aquí, los puntos de corte de cada fase (spec 017, T34b: este módulo pasó del «verde» al hito, P-12 y RNF-017-09; las pruebas de Esc rápidas del «verde» son las de dominio de `test_road_operation.py`). Las pruebas, en el orden de sus letras sobre el mismo estado.

- RF-017-30, RF-015-29, RNF-017-06 (a): Esc a mitad de «Calcular» una pista —en los tres modos: «trazar» (la red 2D y la ruta 3D), «sobre un eje» y «eje 3D»— y la accesibilidad, en cada fase de su
  cálculo, responde en ≤ 2 s y **no deja nada**: ni operación, ni dato, ni parámetro, ni cifra, ni fichero temporal (ninguna ``des_rdx_``, ``des_acc_`` ni ``des_rax_``), ni cálculo abierto.
- RF-017-30, RNF-017-06 (b): Esc **entre los pasos de «Crear»** una pista o una accesibilidad —al empezar, ya con ficheros temporales y justo antes de la transacción final— responde en ≤ 2 s, deja el
  proyecto **como estaba**, descarta el cálculo (hay que volver a calcular) y se puede calcular y crear de nuevo.
- RF-015-29, RF-017-30 (c): Esc en **lo que sigue a «Crear»** (la declaración, las máscaras, la capa de entidades y la de ejes) deja la entidad creada, **ninguna operación a medias, ningún temporal** ni
  una capa a medias, lo dice, y la orden siguiente de entidades lo pone al día.
- RNF-017-06, RF-017-30, RF-015-02 (d): crear por pasos son varios eventos, **no escribe nada en el proyecto antes del último paso** (solo ficheros temporales) y da el mismo resultado que de una vez.
- RNF-017-06, RF-017-30 (e): con el presupuesto de la orden, **ninguna llamada del hilo pasa de 0,2 s** (el máximo, no la media; en CPU del proceso y sin la transacción final, que no se trocea: el R4 de la 012)
  —«Calcular», «Crear» y lo que sigue— y el modal dice el avance.
- Principio 8, RF-017-30 (z): desactivar Geoblender con «Crear» a mitad cancela el modal como Esc y no deja ningún temporal ni cálculo abierto.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import time
import unittest
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.blender import milestone_road_ops as road_ops
from tests.support import blender_ext, step_modals

ROAD = "des_create_road"
ACCESS = "des_road_access"
KINDS = ("TRACE", "ON_AXIS", "AXIS_3D")
"""Los tres modos de la pista."""
ENTRIES = "gis_fea_accesos_pista"
BREAKLINES = "gis_brk_pistas_eje3d_t32"
AXIS_3D_M = ((10.0, 30.0, 100.8), (30.0, 30.0, 101.3), (50.0, 30.0, 101.8))
"""La línea 3D del modo «eje 3D» (local, con la Z de su rasante): el 2,5 % sobre el terreno ``Suave``."""
THRESHOLDS = {"walk_slope": "12", "walk_width": "4", "min_berm_area": "100"}
"""Los umbrales de la accesibilidad tecleados como los teclea una persona (**solo de la prueba**: la orden no propone ninguno)."""
TIMER = step_modals.TIMER
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
CALL_BUDGET_S = 0.2
"""Lo que puede durar cada llamada del hilo de Blender (RNF-017-06), en CPU del proceso."""
ESC_BUDGET_S = 2.0
CANCELLED_CALC = "Cálculo cancelado: no queda nada a medias"
CANCELLED_CREATE = {ROAD: "Creación cancelada: la pista no se ha creado y el cálculo se ha descartado; no queda nada a medias",
                    ACCESS: "Creación cancelada: la accesibilidad no se ha creado y el cálculo se ha descartado; no queda nada a medias"}
CANCELLED_CHAIN = {ROAD: "Cancelado: la pista está creada; las restricciones declaradas y las máscaras se ponen al día antes de la siguiente operación que las use, y la capa de entidades y la de ejes "
                         "con la siguiente orden de entidades o «Recalcular lo obsoleto»",
                   ACCESS: "Cancelado: la accesibilidad está creada; las restricciones declaradas y las máscaras se ponen al día antes de la próxima operación que las use, y la capa de entidades con la "
                           "próxima orden de entidades o «Recalcular lo obsoleto»"}
CREATED = {ROAD: "Pista «{name}» creada en V01", ACCESS: "Accesibilidad «{name}» creada en V01"}


@dataclass
class Run:
    """Lo que pasó al llevar una orden hasta el final con un paso por evento."""

    name: str = ""
    """El nombre de la entidad."""
    modal: Any = None
    state: set[str] = field(default_factory=set)
    events: int = 0
    """Los eventos del temporizador que dio el modal hasta acabar."""
    phases: list[str] = field(default_factory=list)
    """La fase de cada paso, por evento."""
    commit: int | None = None
    """El evento (desde 0) en el que llegó lo guardado: el último de «Crear»; a partir del siguiente, lo que sigue a crearlo."""
    tmp: int | None = None
    """El primer evento (desde 0) tras el que ya hay ficheros temporales en el proyecto."""
    before: tuple[Any, ...] | None = None
    """Lo que había en el proyecto al empezar (con él se anotan los eventos que escribieron antes de que llegara lo guardado)."""
    written: list[int] = field(default_factory=list)
    """Los eventos que escribieron en el proyecto antes de que llegara lo guardado (ninguno)."""
    open_while_creating: bool = False
    """Si el cálculo seguía abierto mientras se creaba."""


class RoadStepsCase(road_ops.RoadOpsTest):
    """El proyecto de la prueba de la pista (que hereda el de la plataforma) con una capa de puntos de entrada y la línea 3D, y las ayudas de los pasos con Esc. Sin pruebas propias: las de la pista
    son de ``milestone_road_ops.py``."""

    probes: dict[str, Run]
    surfaces: int
    named: int

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_feature_layer(ENTRIES, "point", (("Entrada", (10.0, 30.0)),))
        cls.write_axis_3d()
        cls.probes, cls.surfaces, cls.named = {}, 0, 0
        cls.refresh()

    @classmethod
    def refresh(cls) -> None:
        super().refresh()
        cls.panels.refresh_access_choices(cls.project)

    @classmethod
    def write_axis_3d(cls) -> None:
        """La línea de rotura ``BREAKLINES`` con la línea 3D del modo «eje 3D»: **la única capa que guarda la Z de las líneas** (``docs/trampas.md`` §6), como la deja la importación de la 006."""
        operations = platform_ops._module("core.provenance.operations")
        datasets, builtin = platform_ops._module("core.datasets"), platform_ops._module("core.content.builtin")
        gis_store, breaklines = platform_ops._module("gis.store"), platform_ops._module("gis.breaklines")
        srs = int(cls.project.record.crs_epsg)
        line = np.array([(platform_ops.WEST + x, platform_ops.SOUTH + y, z) for x, y, z in AXIS_3D_M], dtype=np.float64)
        rows = gis_store.breakline_rows([breaklines.Breakline("S1", line)], srs)
        handle = operations.begin_operation(cls.project, platform_ops.LAYERS_TYPE, settings={"name": BREAKLINES}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{BREAKLINES}" (fid INTEGER PRIMARY KEY NOT NULL, geom LINESTRING, line_id TEXT NOT NULL DEFAULT \'\', hard BOOLEAN NOT NULL, '
                         f"code TEXT NOT NULL DEFAULT '')")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES (?, 'features', ?, '', ?)", (BREAKLINES, BREAKLINES, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) VALUES (?, 'geom', 'LINESTRING', ?, 1, 0)", (BREAKLINES, srs))
            conn.executemany(f'INSERT INTO "{BREAKLINES}" (geom, line_id, hard, code) VALUES (?, ?, ?, ?)', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(BREAKLINES, "gis", "vector", datasets.Store.GPKG, BREAKLINES, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs,
                                                                input_uid=None, immutable=False),), message="Línea 3D de la prueba de los pasos de la pista")

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(mock.patch.object(self.des_ops, "_ask_confirmation"))  # la ventana de «Crear» no se abre: se cuenta
        self.calls: list[tuple[float, str]] = []  # lo que dura cada llamada del hilo, en CPU del proceso y sin la transacción final, y cuál es
        self.commits: list[float] = []  # la CPU de cada transacción final que hubo (aparte: no se trocea, el R4 de la 012)
        self.budget: float | None = step_modals.ONE_STEP_S  # un paso por evento (``None``: el presupuesto de la orden)
        # T39 (E-2 de la verificación única): un paso de una unidad por evento, **antes de lanzar** la orden (sus generadores leen el presupuesto al crearse) y con el reloj de mentira de los dos
        # módulos que lo miden: los eventos de una corrida y de otra son los mismos vaya como vaya el ordenador, y los puntos de corte que salen de una corrida de referencia siempre caen dentro.
        self.pacing = self.enterContext(ExitStack())
        self.pacing.enter_context(step_modals.one_unit_per_event(
            tuple(self.commands.registered_class(f"geoblender.{command}") for command in (ROAD, ACCESS)),
            (self.core_ops, platform_ops._module("gis.masks.compile"))))
        for module, name in (("design.store", "DesignWriter"), ("gis.masks.store", "MaskWriter")):
            writer = getattr(platform_ops._module(module), name)
            self.enterContext(mock.patch.object(writer, "commit", self.timed_commit(writer.commit)))

    def real_pacing(self) -> None:
        """Los pasos de las órdenes con **su** presupuesto (0,05 s) y el reloj de verdad —lo que ve una persona—, para lo que mide cuánto dura cada llamada. Con él, los eventos de una orden **dependen
        del reloj**: lo que lo usa no corta en un evento que salga de contar los de otra corrida sin tolerar que el número cambie."""
        self.pacing.close()

    def timed_commit(self, real: Any) -> Any:
        """``commit`` de un escritor, con su CPU anotada: la transacción final es lo único que no se trocea (R4 de la 012) y se mide aparte de la llamada que la contiene."""
        case = self

        def commit(writer: Any, *args: Any, **kwargs: Any) -> Any:
            started = time.process_time()
            try:
                return real(writer, *args, **kwargs)
            finally:
                case.commits.append(time.process_time() - started)

        return commit

    def measured(self, what: str, function: Any, *args: Any, **kwargs: Any) -> Any:
        """``function(*args)`` como una llamada del hilo de Blender: su CPU, sin la de la transacción final que hubiera dentro, se anota con ``what``."""
        committed, started = sum(self.commits), time.process_time()
        try:
            return function(*args, **kwargs)
        finally:
            self.calls.append((time.process_time() - started - (sum(self.commits) - committed), what))

    # --- Formularios y superficies ---------------------------------------------------------------

    def fresh_surface(self) -> str:
        """Un terreno nuevo (``Suave`` otra vez): de cada superficie parte una sola entidad, y lo creado en una prueba ocupa la suya."""
        type(self).surfaces += 1
        name = self.write_grid(f"Suave T32 {type(self).surfaces}", road_ops.smooth())
        self.refresh()
        return name

    def road_form(self, kind: str, start: str, name: str) -> dict[str, Any]:
        """Lo pedido para la pista en el modo ``kind``: «trazar» de «Origen» a «Destino» (la ruta de referencia), «sobre un eje» el «Eje A15» y «eje 3D» la línea 3D, con el perfil de referencia."""
        if kind == "TRACE":
            return self.form(name=name, start=start)
        feature = {"ON_AXIS": {"layer": road_ops.AXES, "feature": "Eje A15"}, "AXIS_3D": {"layer": BREAKLINES, "name_field": "line_id", "feature": "S1"}}[kind]
        return {"name": name, "mode": kind, **feature, "profile": "pista_principal", "start": start, "in_steps": False}

    def access_form(self, start: str, name: str) -> dict[str, Any]:
        return {"name": name, "surface": start, "layer": ENTRIES, **THRESHOLDS, "in_steps": False}

    def calc_form(self, which: str, start: str, name: str | None = None) -> dict[str, Any]:
        """El formulario de «Calcular» de ``which`` (uno de :data:`KINDS` o ``"ACCESS"``) con un nombre que no repite el de ninguna entidad de la prueba (``name``: ese)."""
        if name is None:
            type(self).named += 1
            name = f"Entidad T32 {type(self).named}"
        return self.access_form(start, name) if which == "ACCESS" else self.road_form(which, start, name)

    @staticmethod
    def command_of(which: str) -> str:
        return ACCESS if which == "ACCESS" else ROAD

    # --- Los eventos del modal, medidos ----------------------------------------------------------

    def operator(self, command: str) -> Any:
        return getattr(bpy.ops.geoblender, command)

    def modal_of(self, command: str) -> Any:
        cls = self.commands.registered_class(f"geoblender.{command}")
        found = [op for op in bpy.context.window.modal_operators if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"geoblender.{command} no está en marcha")
        modal = found[0]
        if self.budget is not None:
            modal.STEP_BUDGET_S = self.budget  # ``None``: el de la orden
        self.addCleanup(self.close, modal)
        return modal

    @staticmethod
    def close(modal: Any) -> None:
        """Cierra el modal si sigue en marcha (la orden ya puede no estar: se desactivó Geoblender)."""
        try:
            if modal._steps is not None:
                modal.cancel(bpy.context)
        except ReferenceError:
            pass

    def start(self, command: str, **values: Any) -> Any:
        """Lanza ``command`` desde la interfaz (``in_steps``: el modal de pasos) y devuelve el modal en marcha; la llamada se mide."""
        result = self.measured(f"geoblender.{command}", self.operator(command), "EXEC_DEFAULT", **{**values, "in_steps": True})
        self.assertEqual(result, {"RUNNING_MODAL"})
        return self.modal_of(command)

    def drive(self, modal: Any, *, stop_after: int | None = None, run: Run | None = None) -> tuple[set[str], int]:
        """Un evento del temporizador cada vez, cada llamada medida, hasta que el modal acaba o hasta ``stop_after`` eventos (``RUNNING_MODAL``); con ``run``, anota de cada evento su fase, cuándo llegó
        lo guardado y cuándo hubo ficheros temporales y qué escribió. Devuelve cómo acabó y cuántos eventos llevaba."""
        base = 0 if run is None else len(run.phases)
        for index in range(step_modals.MAX_EVENTS):
            if index == stop_after:
                return {"RUNNING_MODAL"}, index
            state = self.measured(f"evento {base + index}", modal.modal, bpy.context, TIMER)
            if run is not None:
                self.annotate(run, modal, base + index)
            if state != {"RUNNING_MODAL"}:
                return state, index + 1
        raise AssertionError(f"el modal no acaba en {step_modals.MAX_EVENTS} eventos")

    def annotate(self, run: Run, modal: Any, event: int) -> None:
        """Lo que pasó en el evento ``event`` de ``run`` (ya dado)."""
        run.phases.append(modal.progress_log[-1][1] if modal.progress_log else "")
        if run.commit is None and modal._chain:
            run.commit = event
        if run.tmp is None and self.temporaries():
            run.tmp = event
        if run.before is not None and run.commit is None and self.state()[:4] != run.before[:4]:
            run.written.append(event)

    def escape(self, modal: Any) -> None:
        """Esc: responde en ≤ 2 s y cancela."""
        started = time.perf_counter()
        state = modal.modal(bpy.context, ESCAPE)
        self.assertLessEqual(time.perf_counter() - started, ESC_BUDGET_S, "Esc responde en ≤ 2 s (RNF-017-06)")
        self.assertEqual(state, {"CANCELLED"})
        self.assertIsNone(modal._steps)
        self.assertEqual(modal.outcome, "CANCELLED")

    def assert_calls_within_budget(self, what: str, *, commits: bool = True) -> None:
        """Ninguna llamada medida pasa de 0,2 s de CPU, sin la transacción final: el máximo, no la media. Con ``commits``, hubo alguna transacción final (la de crear; «Calcular» no la tiene)."""
        self.assertTrue(self.calls, what)
        longest, which = max(self.calls)
        self.assertLessEqual(longest, CALL_BUDGET_S, f"{what}: la llamada más larga, {longest:.3f} s de CPU ({which}), de {len(self.calls)}")
        self.assertEqual(bool(self.commits), commits, f"{what}: la transacción final")

    # --- Qué queda --------------------------------------------------------------------------------

    def unfinished(self) -> list[tuple[Any, ...]]:
        """Las operaciones del proyecto **en curso** (``running``): ninguna a medias. Una operación que Esc cerró a mitad queda **cancelada** y sin salidas (RF-008-19), y no es una a medias."""
        return self.rows("SELECT op_type, status FROM gb_operation WHERE status = 'running'")

    def temporaries(self) -> list[str]:
        return [name for name in self.names() if ".tmp" in name]

    def assert_nothing_left(self, before: tuple[Any, ...], what: str) -> None:
        """Como si nada: el proyecto como estaba (operaciones, datos, parámetros, cifras y ficheros), ninguna operación a medias, ningún temporal, el cálculo descartado y la vista previa quitada."""
        self.assertEqual(self.state(), before, what)
        self.assertEqual(self.unfinished(), [], what)
        self.assertEqual(self.temporaries(), [], what)
        self.assertIsNone(self.des_ops.calculation(), what)
        self.assertFalse(self.des_ops._entity_preview().enabled(), what)

    def escape_and_check(self, which: str, name: str, modal: Any, before: tuple[Any, ...], what: str) -> str:
        """Esc en un modal de «Crear» y lo que deja según **dónde cayó**: entre los pasos de crear (``"create"``: el proyecto como estaba, el cálculo descartado, el resumen y las listas vaciados) o, **ya
        creada** (``"chain"``: la entidad vigente y nada a medias), en lo que sigue. El número de eventos de un paso **no es exacto** de una vez a otra (las unidades casi instantáneas se agrupan según el
        reloj): un punto de corte cerca del límite puede caer a un lado o al otro, y cada lado se comprueba con lo suyo. ``before``: el proyecto antes de «Crear»."""
        self.escape(modal)
        if modal._chain:
            self.assert_chain_escaped(which, name, modal)
            return "chain"
        self.assertIn(CANCELLED_CREATE[self.command_of(which)], modal.report_log)
        self.assert_nothing_left(before, what)
        self.assertEqual(self.view.summary_title, "", "el resumen, vaciado")
        self.assertEqual(self.panels.access_sections(), [])
        return "create"

    def assert_chain_escaped(self, which: str, name: str, modal: Any) -> None:
        """Lo que deja Esc **ya creada** la entidad ``name`` (en lo que sigue a crearla): vigente, ninguna operación en curso (una que Esc cerró queda cancelada y sin salidas), ningún temporal, ninguna capa a
        medias (la de antes o la nueva, entera), lo dice; y la orden siguiente de entidades lo pone todo al día: las dos capas con una fila por pista y las máscaras al día."""
        masks = platform_ops._module("gis.masks.access")
        self.assertIn(CANCELLED_CHAIN[self.command_of(which)], modal.report_log)
        entry = self.entities.registry(self.project, self.v01.uid).get(self.code_of(name))
        self.assertEqual(str(entry.record.state), "current", "la entidad está creada")
        self.assertEqual(self.unfinished(), [], "ninguna operación a medias")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation AS o JOIN gb_operation_io AS io ON io.operation_uid = o.uid WHERE o.status = 'cancelled' AND io.direction = 'out'"),
                         [(0,)], "la operación que cerró Esc queda cancelada y sin salidas")
        self.assertEqual(self.temporaries(), [])
        self.assertIsNone(self.des_ops.calculation())
        roads = [item for item in self.entities.registry(self.project, self.v01.uid) if item.record.kind == self.entities.EntityKind.ROAD]
        for layer in ("des_enl", "des_rax"):
            self.assertIn(self.layer_rows(layer), {None, *range(len(roads) + 1)}, f"{layer}: la de antes o la nueva, entera")
        self.finish_chain()
        self.assertEqual(self.layer_rows("des_enl"), len(roads))
        self.assertEqual(self.layer_rows("des_rax"), len(roads))
        self.assertIs(masks.mask_state(self.project, self.v01.uid)[0], masks.MaskState.CURRENT)

    # --- Calcular y crear -------------------------------------------------------------------------

    def calculate(self, which: str, start: str) -> str:
        """«Calcular» desde un guion: deja abierto el cálculo de la sesión (lo mismo que los pasos, de una vez) con un nombre nuevo, que devuelve."""
        form = self.calc_form(which, start)
        self.assertEqual(self.operator(self.command_of(which))("EXEC_DEFAULT", **form), {"FINISHED"})
        self.assertIsNotNone(self.des_ops.calculation())
        return str(form["name"])

    def calculation_run(self, which: str, start: str) -> Run:
        """«Calcular» desde la interfaz con un paso por evento, hasta el final: sus eventos y la fase de cada uno. Descarta el cálculo y no deja nada."""
        before = self.state()
        run = Run(modal=self.start(self.command_of(which), **self.calc_form(which, start)))
        run.state, run.events = self.drive(run.modal, run=run)
        self.assertEqual(run.state, {"FINISHED"}, which)
        self.assertIsNotNone(self.des_ops.calculation(), which)
        self.des_ops.discard_calculation()
        self.assertEqual(self.state(), before, which)
        return run

    def creation_run(self, which: str, start: str) -> Run:
        """«Calcular» (de una vez) y «Crear» desde la interfaz, un paso por evento, hasta el final (lo guardado y lo que sigue): lo crea. Anota los eventos que escribieron antes de lo guardado."""
        run = Run(name=self.calculate(which, start))
        run.before = self.state()
        run.modal = self.start(self.command_of(which), confirm=True)
        run.open_while_creating = bool(self.des_ops.calculation().open)
        run.state, run.events = self.drive(run.modal, run=run)
        self.assertEqual(run.state, {"FINISHED"}, which)
        self.assertIsNotNone(run.commit, f"{which}: lo guardado no llegó")
        return run

    def probe(self, which: str) -> Run:
        """Lo que da crear ``which`` desde la interfaz con un paso por evento (los eventos y su fase, cuándo hubo temporales y cuándo llegó lo guardado): una vez por clase. La entidad queda creada y al día."""
        if which not in type(self).probes:
            type(self).probes[which] = self.creation_run(which, self.fresh_surface())
            self.finish_chain()
        return type(self).probes[which]

    def outputs(self, name: str, command: str) -> list[tuple[str, str]]:
        """Lo que escribió la operación hecha de la entidad ``name``: ``(papel, hash del contenido)`` de cada salida, en su orden (de las tablas, que llevan el código y el nombre de la entidad, solo el papel)."""
        op_type = {ROAD: "des.road", ACCESS: "des.road_access"}[command]
        ((uid,),) = self.rows("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND json_extract(settings, '$.name') = ?", op_type, name)
        return [(role, sha if dataset.startswith(("des_psf_", "des_acc_")) else "") for role, dataset, sha in self.rows(
            "SELECT io.role, d.name, d.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def figures(self, name: str, command: str) -> list[float]:
        """Las cifras de la operación hecha de la entidad ``name``, ordenadas."""
        op_type = {ROAD: "des.road", ACCESS: "des.road_access"}[command]
        return sorted(value for (value,) in self.rows(
            "SELECT value FROM gb_figure WHERE operation_uid = (SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND json_extract(settings, '$.name') = ?)", op_type, name))

    def layer_rows(self, family: str) -> int | None:
        """Las filas de la capa de la versión ``family`` (``des_enl`` o ``des_rax``) o ``None`` si no hay ninguna viva."""
        found = self.rows("SELECT name FROM gb_dataset WHERE status = 'current' AND name = ?", family)
        if not found:
            return None
        return int(self.rows(f'SELECT count(*) FROM "{family}_v01"')[0][0])

    def finish_chain(self) -> None:
        """Lo que sigue a crear, hasta el final (la orden siguiente de entidades): las restricciones declaradas, las máscaras y las capas, al día."""
        entity_store = platform_ops._module("design.entity_store")
        for _step in entity_store.after_entity_change(self.project, self.v01.uid):
            pass


for _name in dir(road_ops.RoadOpsTest):  # las pruebas de la pista son de ``milestone_road_ops.py``: aquí solo el proyecto y las ayudas
    if _name.startswith("test_"):
        setattr(RoadStepsCase, _name, None)
del _name


def cut_points(run: Run) -> Iterator[int]:
    """Los puntos de corte de Esc de «Calcular»: **antes del primer paso**, justo **antes y después del primer paso de cada fase** y **antes del último**: cuántos eventos corren antes de
    Esc."""
    firsts = {index for index, phase in enumerate(run.phases) if index == 0 or run.phases[index - 1] != phase}
    points = {0, run.events - 1, *firsts, *(index + 1 for index in firsts)}
    yield from sorted(point for point in points if 0 <= point < run.events)


class RoadStepsTest(RoadStepsCase):
    """Las pruebas de los pasos con Esc en sus puntos de corte (el recorrido de todos los eventos es de ``milestone_road_steps.py``)."""

    def test_a_esc_in_each_phase_of_calculating_leaves_nothing(self) -> None:
        """RF-017-30, RF-015-29, RNF-017-06 (M9): Esc a mitad de «Calcular» **una pista en sus tres modos** («trazar»: la red 2D y la ruta 3D; «sobre un eje»; «eje 3D») y **la accesibilidad**, antes
        del primer paso, antes y después del primer paso de cada fase y antes del último, responde en ≤ 2 s y **no deja nada**: ni operación, ni dato, ni parámetro, ni cifra (ninguna ``des_rdx_``,
        ``des_acc_`` ni ``des_rax_``), ni fichero temporal, ni cálculo abierto, ni vista previa; lo dice."""
        start = self.fresh_surface()
        before = self.state()
        for which in (*KINDS, "ACCESS"):
            run = self.calculation_run(which, start)
            self.assertGreaterEqual(run.events, 3, f"{which}: «Calcular» tiene varios pasos: Esc cae a mitad")
            points, escaped = list(cut_points(run)), 0
            self.assertGreaterEqual(len(points), 3, which)
            for point in points:
                with self.subTest(modo=which, eventos_antes_de_Esc=point):
                    modal = self.start(self.command_of(which), **self.calc_form(which, start))
                    state, _events = self.drive(modal, stop_after=point)
                    if state != {"RUNNING_MODAL"}:  # el número de eventos no es exacto de una vez a otra (las unidades casi instantáneas se agrupan según el reloj): el último corte puede ya no caer
                        self.assertGreaterEqual(point, run.events - 2, "solo el último corte cae fuera")
                        self.des_ops.discard_calculation()
                        continue
                    self.escape(modal)
                    escaped += 1
                    self.assertIn(CANCELLED_CALC, modal.report_log)
                    self.assert_nothing_left(before, f"{which} tras {point} eventos")
                    self.assertEqual(self.panels.access_sections(), [], which)
            self.assertGreaterEqual(escaped, len(points) - 1, which)
        self.assertEqual(self.state(), before)

    def test_b_esc_between_the_steps_of_creating_leaves_nothing_half_done_and_discards_the_calculation(self) -> None:
        """RF-017-30, RF-015-29, RNF-017-06 (M9): Esc **entre los pasos de «Crear»** una pista y una accesibilidad —al empezar, ya con ficheros temporales y justo antes de la transacción final—
        responde en ≤ 2 s, deja el proyecto **como estaba** (ni operación, ni dato, ni parámetro, ni cifra, ni temporal: ninguna ``des_rdx_``, ``des_acc_`` ni ``des_rax_``), descarta el cálculo
        (el resumen y las listas se vacían: hay que volver a calcular), lo dice y se puede calcular y crear de nuevo sobre la misma superficie."""
        for which in ("TRACE", "ACCESS"):
            command, probe, start = self.command_of(which), self.probe(which), self.fresh_surface()
            self.assertIsNotNone(probe.tmp, f"{which}: crear escribe ficheros temporales antes de la transacción final")
            created = 0
            for point in sorted({0, probe.tmp + 1, probe.commit}):
                with self.subTest(orden=which, eventos_antes_de_Esc=point):
                    name = self.calculate(which, start)
                    before = self.state()
                    modal = self.start(command, confirm=True)
                    self.assertEqual(self.drive(modal, stop_after=point)[0], {"RUNNING_MODAL"})
                    if point > probe.tmp:
                        self.assertTrue(self.temporaries(), "ya hay ficheros temporales")
                    created += self.escape_and_check(which, name, modal, before, f"{which} tras {point} eventos") == "chain"
            self.assertLessEqual(created, 1, f"{which}: solo el último corte puede caer ya creada")
        again = self.creation_run("TRACE", start)  # sobre la misma superficie: se puede calcular y crear de nuevo
        self.assertEqual(str(self.entities.registry(self.project, self.v01.uid).get(self.code_of(again.name)).record.state), "current")
        self.finish_chain()

    def test_c_esc_in_what_follows_creating_keeps_the_entity_and_leaves_nothing_half_done(self) -> None:
        """RF-015-29, RF-017-30, RNF-017-06 (M9): Esc **ya creada** —en la declaración, las máscaras, la capa de entidades o la de ejes, que van en el mismo modal— responde en ≤ 2 s y deja la pista o
        la accesibilidad **creada** (vigente), **ninguna operación a medias** (la que Esc cerró queda cancelada y sin salidas), ningún temporal y ninguna capa a medias (la de antes o la nueva, entera),
        lo dice, y la orden siguiente de entidades pone todo al día: las dos capas con una fila por pista y las máscaras al día."""
        for which, offsets in (("TRACE", (0, 2)), ("ACCESS", (1,))):
            command, probe = self.command_of(which), self.probe(which)
            self.assertGreaterEqual(probe.events - probe.commit - 1, 3, f"{which}: lo que sigue a crear tiene varios pasos")
            for offset in offsets:  # la cadena de la primera pista es la más larga (compila las máscaras): los cortes, desde el evento de lo guardado
                point = probe.commit + 1 + offset
                with self.subTest(orden=which, eventos_antes_de_Esc=point):
                    name = self.calculate(which, self.fresh_surface())
                    before = self.state()
                    modal = self.start(command, confirm=True)
                    self.assertEqual(self.drive(modal, stop_after=point)[0], {"RUNNING_MODAL"}, "la cadena aún no había acabado")
                    self.escape_and_check(which, name, modal, before, f"{which} tras {point} eventos")  # la cadena, o crear si el número de eventos cambió

    def test_d_creating_runs_by_steps_with_the_result_of_creating_at_once(self) -> None:
        """RNF-017-06, RF-017-30, RF-015-02 (M9): «Crear» la pista y la accesibilidad desde la interfaz **ya no es una sola llamada**: con un paso por evento son **más de 3 eventos**, **no escribe nada
        en el proyecto antes del último paso** (solo ficheros temporales), el cálculo sigue abierto mientras crea, el informe lo dice y deja de estar abierto; **el resultado es el de crear de una vez**
        desde un guion (``in_steps=False``): los mismos papeles, los mismos hashes de contenido de cada rejilla y las mismas cifras."""
        for which in ("TRACE", "ACCESS"):
            command, run = self.command_of(which), self.probe(which)
            self.assertGreater(run.commit, 3, f"{which}: crear por pasos son varios eventos")
            self.assertEqual(run.written, [], f"{which}: ningún evento escribió en el proyecto antes del último paso")
            self.assertTrue(run.open_while_creating, "mientras crea, el cálculo sigue abierto")
            self.assertIsNotNone(run.tmp)
            self.assertIn(CREATED[command].format(name=run.name), list(run.modal.report_log))
            self.assertIsNone(self.des_ops.calculation())
            self.assertEqual(self.temporaries(), [])
        once = self.calculate("TRACE", self.fresh_surface())  # de una vez, desde un guion
        self.assertEqual(self.operator(ROAD)("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.finish_chain()
        steps = self.probe("TRACE").name
        self.assertEqual(self.outputs(steps, ROAD), self.outputs(once, ROAD), "los mismos papeles y rejillas, con los mismos hashes de contenido")
        self.assertGreaterEqual(len(self.outputs(steps, ROAD)), 3, "la rejilla y las tablas")
        self.assertEqual(self.figures(steps, ROAD), self.figures(once, ROAD), "las mismas cifras")
        self.assertTrue(self.figures(once, ROAD))

    def test_e_no_call_of_the_thread_passes_0_2_s_with_the_budget_of_the_command(self) -> None:
        """RNF-017-06, RF-017-30 (M9): con el presupuesto de la orden (0,05 s por llamada) **ninguna llamada del hilo de Blender pasa de 0,2 s** —el máximo, no la media; en CPU del proceso y sin la
        transacción final, que no se trocea (R4 de la 012)— al lanzar «Calcular», en cada evento de su modal (la pista en sus tres modos y la accesibilidad), al lanzar «Crear» y en cada evento de crear
        y de lo que sigue (la declaración, las máscaras y las capas); y el modal dice el avance (un ``Progress`` por paso, hasta completarse)."""
        self.budget = None
        self.real_pacing()  # la de la orden y el reloj de verdad: es lo que se mide
        for which in (*KINDS, "ACCESS"):
            command, start = self.command_of(which), self.fresh_surface()
            self.calls.clear()
            modal = self.start(command, **self.calc_form(which, start))
            self.assertEqual(self.drive(modal)[0], {"FINISHED"}, which)
            self.assertGreaterEqual(len(modal.progress_log), 3, f"{which}: «Calcular» dice su avance")
            self.assertEqual(modal.progress_log[-1][2], modal.progress_log[-1][3], "hasta completarse")
            if which in ("TRACE", "ACCESS"):
                modal = self.start(command, confirm=True)
                self.assertEqual(self.drive(modal)[0], {"FINISHED"}, which)
                self.assertGreaterEqual(len(modal.progress_log), 3, f"{which}: «Crear» dice su avance")
                self.assert_calls_within_budget(which)
                self.finish_chain()
            else:
                self.des_ops.discard_calculation()
                self.assertTrue(self.calls)
                self.assertLessEqual(max(self.calls)[0], CALL_BUDGET_S, f"{which}: la llamada más larga: {max(self.calls)}")

    def test_z_disabling_geoblender_in_the_middle_of_creating_cancels_the_modal_and_leaves_nothing(self) -> None:
        """Principio 8, RF-017-30, RF-015-29, RNF-017-06 (M9): con «Crear» una pista a mitad —ya con ficheros temporales— desactivar Geoblender cancela el modal como Esc (``bl.ops.core.cancel_running``,
        antes de quitar ninguna clase): se cierran sus pasos (``Calculation.create_steps`` borra los temporales y descarta el cálculo), no queda ningún modal en curso ni cálculo abierto ni fichero
        temporal, y la orden ya no está."""
        probe = self.probe("TRACE")
        self.calculate("TRACE", self.fresh_surface())
        modal = self.start(ROAD, confirm=True)
        self.assertEqual(self.drive(modal, stop_after=probe.tmp + 1)[0], {"RUNNING_MODAL"})
        self.assertTrue(self.temporaries(), "ya hay ficheros temporales")
        blender_ext.release()  # la orden se quita con su clase: del modal ya solo queda que no esté en curso
        self.assertEqual(self.core_ops.running_step_modals(), (), "el modal cerró sus pasos")
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.temporaries(), [])
        self.assertIsNone(getattr(bpy.types, "GEOBLENDER_OT_des_create_road", None))


if __name__ == "__main__":
    unittest.main()
