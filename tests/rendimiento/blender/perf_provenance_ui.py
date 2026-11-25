# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia en la interfaz con el volumen de D-13, dentro de Blender (spec 008, T60;
RNF-008-06, RNF-008-12 y RNF-008-13; plan 008 §7.3, ``tests/rendimiento/blender``).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con
``tools/run_blender_tests.py -- --carpeta tests/rendimiento/blender --patron
"perf_provenance*.py"``). Cada clase construye en un temporal de disco local el proyecto de
D-13 de ``tests/support/provenance_fixtures.py`` (100 entradas, 300 parámetros con 10
revisiones, 10 000 operaciones y 20 000 datos; lo escribe el ``geoblender`` que carga
``tests.support.package``, por filas), registra sus declaraciones también en la extensión
habilitada (:func:`extension_declarations`) y lo abre con ella, como una persona: abrir el
proyecto y dejarlo en la sesión (``project_session.attach``). En ``blender -b`` los
temporizadores no corren: la prueba hace de temporizador y llama a sus funciones
(``check_tick`` de la sesión de la procedencia cada :data:`TICK_S` s y ``indicator_tick`` de
los indicadores cada :data:`INDICATOR_TICK_S` s), midiendo cada llamada. Los dibujos se
llaman con un *layout* nulo (``perf_ui_draw_cost.NullLayout``): se mide el Python de
Geoblender. Cada prueba imprime su cifra en una línea «RNF-008-nn: …» y la compara con su
presupuesto, sin relajarlo.

- RNF-008-06 (:class:`IndicatorsTest`): «⚠ n entradas», «! n obsoletos» y «Comprobando el
  proyecto…» se ponen al día ≤ 1 s después del cambio (lo que espera el tic de los indicadores
  más lo que tarda) y dibujar los cuatro campos de la barra de estado cuesta ≤ 1 ms.
- RNF-008-12 (:class:`ResponsiveTest`): abrir el proyecto de D-13 hasta que es usable sigue
  en ≤ 0,5 s (RNF-002-02; ninguna comprobación corre en ese tiempo) y, mientras corre la
  comprobación de apertura, cada tic del monitor dura ≤ 20 ms y la interfaz responde en
  ≤ 0,1 s (ninguna llamada del hilo de Blender, tic del monitor, tic de los indicadores o
  dibujo de la barra de estado, la retiene más).
- RNF-008-13 (:class:`PanelsTest`): Parámetros del proyecto (300 parámetros de D-13 con
  3 000 entradas de historial) y el registro de entradas (100): abrir y filtrar ≤ 0,2 s, y
  cada redibujado (el panel y las filas visibles de sus listas) ≤ 5 ms. El registro de
  entradas no tiene filtros propios (el de nombre de la lista es el de Blender, en C): su
  «filtrar» es volver a leer sus filas cuando cambia el proyecto.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
import platform
import statistics
import sys
import time
import unittest
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.rendimiento.blender.perf_ui_draw_cost import NullLayout
from tests.support import blender_ext
from tests.support import provenance_fixtures as d13
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import project_tmp

INTERPRETER = f"Blender {bpy.app.version_string}, Python {platform.python_version()}"

UPDATE_BUDGET_S = 1.0  # RNF-008-06: los indicadores al día tras el cambio
FIELDS_DRAW_BUDGET_S = 0.001  # RNF-008-06: dibujar los cuatro campos
OPEN_BUDGET_S = 0.5  # RNF-008-12 (RNF-002-02): abrir hasta usable, en disco local
TICK_BUDGET_S = 0.020  # RNF-008-12: cada tic del monitor de la comprobación
RESPONSE_BUDGET_S = 0.1  # RNF-008-12: la interfaz responde mientras corre
PANEL_BUDGET_S = 0.2  # RNF-008-13: abrir y filtrar
REDRAW_BUDGET_S = 0.005  # RNF-008-13: cada redibujado
DRAWS = 1000  # dibujos para medir lo que cuesta cada uno
MAX_TICKS = 20_000  # la comprobación de D-13 acaba en unos cientos de tics

FIELD_KEYS = ("provenance_inputs", "provenance_stale", "provenance_checking", "notice")
UNDO_TEXT = "Ctrl+Z no deshace la operación «res.t00»: sigue en el proyecto"
CHANGED_SOURCE = 0  # la fuente de D-13 que cambia en IndicatorsTest


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _seconds(value: float, digits: int = 3) -> str:
    """Segundos con coma decimal (salida en español)."""
    return f"{value:.{digits}f}".replace(".", ",")


def _ms(value: float) -> str:
    return f"{value * 1000:.3f}".replace(".", ",")


def _report(text: str) -> None:
    print(f"{text} [{INTERPRETER}]", file=sys.stderr, flush=True)


def _timed(function: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = function()
    return time.perf_counter() - started, result


def _plain(value: Any) -> Any:
    """Un valor de una declaración del otro ``geoblender`` que valga en la extensión: sus
    enumeraciones, por su valor."""
    return value.value if isinstance(value, enum.Enum) else value


def _same(cls: type, value: Any) -> Any:
    """La declaración ``value`` del ``geoblender`` de ``tests.support.package`` como un objeto
    ``cls`` de la extensión, con los mismos campos."""
    return cls(**{field.name: _plain(getattr(value, field.name))
                  for field in dataclasses.fields(value) if field.init})


@contextmanager
def extension_declarations() -> Iterator[None]:
    """Registra en la extensión habilitada lo que el volumen de D-13 declara (los 300
    parámetros, los 20 tipos de operación y la cifra; lo de ``core`` ya lo registra la
    extensión) y lo quita al salir."""
    params = _module("core.params")
    contract = _module("core.provenance.contract")
    with ExitStack() as stack:
        params.register_definitions(tuple(_same(params.ParamDef, defn)
                                          for defn in d13.DEFINITIONS))
        stack.callback(params.unregister_definitions, d13.MODULE)
        for defn in d13.OPERATION_DEFS:
            contract.register_operation(_same(contract.OperationDef, defn))
            stack.callback(contract.unregister_operation, defn.op_type)
        contract.register_figure(_same(contract.FigureDef, d13.FIGURE_DEF))
        stack.callback(contract.unregister_figure, d13.FIGURE_KEY)
        yield


def _bar_context() -> SimpleNamespace:
    """La barra de estado de una ventana de 1920 px en modo Geoblender."""
    window = bpy.context.window_manager.windows[0]
    return SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True),
                           region=SimpleNamespace(width=1920.0), scene=bpy.context.scene,
                           window=window, screen=window.screen, area=None,
                           preferences=bpy.context.preferences)


class D13Case(unittest.TestCase):
    """La extensión habilitada y el proyecto de D-13, construido para la clase en un temporal
    de disco local y cerrado; :meth:`open_d13` lo abre con la extensión."""

    root: Path
    sources: tuple[Path, ...]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stack = ExitStack()
        try:
            blender_ext.unload()
            blender_ext.enable()
            cls.stack.callback(blender_ext.unload)
            tmp = cls.stack.enter_context(project_tmp("gb-008-ui-"))
            started = time.perf_counter()
            with d13.registered():
                built = d13.build_d13(tmp / "proyectos", tmp / "fuentes")
            built.close()
            cls.build_s = time.perf_counter() - started
            cls.root = built.root
            cls.sources = built.sources
            cls.stack.enter_context(extension_declarations())
            cls.core = _module("core.project")
            cls.ps = _module("bl.scene.project_session")
            cls.ops = _module("bl.ops.core_provenance")
            cls.ui = _module("bl.ui.provenance")
            cls.statusbar = _module("bl.ui.statusbar")
            cls.stale = _module("core.provenance.stale")
            cls.stack.callback(cls.ps.take_notices)
            cls.stack.callback(cls.ps.close)
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()
        super().tearDownClass()

    def setUp(self) -> None:
        self.slow: list[tuple[float, str]] = []  # tics del monitor de más de 20 ms y su paso

    # Ayudas ---------------------------------------------------------------------------------

    def open_d13(self) -> tuple[Any, float]:
        """Abre el proyecto de D-13 con la extensión y lo deja en la sesión; devuelve el
        proyecto y lo que tardó hasta ser usable."""
        started = time.perf_counter()
        opened = self.core.open_project(self.root, self.ps.session(), self.ps.userdata(),
                                        read_only=self.ops.read_only_dirs())
        self.ps.attach(opened.project)
        took = time.perf_counter() - started
        self.addCleanup(self.ps.close)
        return opened.project, took

    def fields(self) -> list[Any]:
        """Los campos de la procedencia en la barra de estado."""
        return [field for field in self.statusbar.fields() if field.key in FIELD_KEYS]

    def draw_fields(self, layout: Any, ctx: Any) -> None:
        for field in self.fields():
            if field.width_px(ctx) > 0:
                field.draw(layout, ctx)

    def shown(self) -> list[str]:
        """Los textos de los campos de la procedencia que se ven ahora."""
        return [text for text in (self.ui.inputs_text(), self.ui.stale_text(),
                                  self.ui.checking_text(),
                                  _module("bl.ui.notices").latest_text()) if text]

    def drive(self) -> dict[str, list[float]]:
        """Hace de temporizador hasta que la sesión no tiene nada que comprobar: cada
        :data:`TICK_S` s simulados, un tic del monitor; cada :data:`INDICATOR_TICK_S` s, uno de
        los indicadores; tras cada tic, el dibujo de los campos de la barra. Devuelve lo que
        duró cada llamada, por clase."""
        times: dict[str, list[float]] = {"check": [], "indicator": [], "bar": []}
        every = max(1, round(self.ui.INDICATOR_TICK_S / self.ops.TICK_S))
        ctx = _bar_context()
        layout = NullLayout()
        for tick in range(MAX_TICKS):
            took, interval = _timed(self.ops.check_tick)
            times["check"].append(took)
            if took > TICK_BUDGET_S:
                step = self.ops.SESSION.progress
                self.slow.append((took, "" if step is None else step.phase))
            if tick % every == every - 1:
                times["indicator"].append(_timed(self.ui.indicator_tick)[0])
            times["bar"].append(_timed(lambda: self.draw_fields(layout, ctx))[0])
            if interval is None:
                return times
        self.fail("la comprobación no termina")


class IndicatorsTest(D13Case):
    def test_indicators_follow_the_changes(self) -> None:
        """RNF-008-06: en el proyecto de D-13, al volver a abrirlo con una fuente cambiada,
        «Comprobando el proyecto… 0 %» se ve en cuanto es usable y avanza en cada tic del
        monitor; al terminar, «⚠ 1 entrada»; y, tras cambiar el parámetro que leen todas las
        cadenas, «! 20000 obsoletos»: cada uno ≤ 1 s después del cambio (lo que espera el tic
        más lo que tarda). Dibujar los cuatro campos cuesta ≤ 1 ms."""
        ui, ops = self.ui, self.ops
        self.open_d13()
        self.drive()
        ui.indicator_tick()
        self.assertEqual(self.shown(), [])  # todo al día

        self.ps.close()
        source = self.sources[CHANGED_SOURCE]
        source.write_bytes(source.read_bytes() + b"S-999;715999,5;4378999,25;699,5\n")
        project, opened = self.open_d13()
        self.assertEqual(self.shown(), ["Comprobando el proyecto… 0 %"])
        checking = self.drive()
        progress_after = ops.TICK_S + max(checking["check"])  # el siguiente porcentaje
        took, interval = _timed(ui.indicator_tick)
        inputs_after = interval + took
        self.assertEqual(self.shown(), ["⚠ 1 entrada"])

        store = _module("core.params").ParameterStore(project)
        before = store.get(d13.COMMON_KEY).value
        started = time.perf_counter()
        with project.write_transaction() as conn:
            store.change(conn, d13.COMMON_KEY, value=before + 1.0,
                         reason="Prueba de rendimiento")
        marks = time.perf_counter() - started
        self.assertEqual(self.shown(), ["⚠ 1 entrada"])  # hasta el siguiente tic
        took, interval = _timed(ui.indicator_tick)
        stale_after = interval + took
        counts = ui.counts()
        self.assertGreaterEqual(counts.obsolete, d13.DATASETS)
        self.assertEqual(self.shown(), ["⚠ 1 entrada", f"! {counts.obsolete} obsoletos"])

        ops.SESSION.check_inputs()  # «Comprobando…» a la vista
        ui.show_undo_notice(UNDO_TEXT)
        ctx = _bar_context()
        layout = NullLayout()
        self.assertEqual(len(self.shown()), 4)
        draws = [_timed(lambda: self.draw_fields(layout, ctx))[0] for _ in range(DRAWS)]
        ops.SESSION.cancel()
        _report(
            f"RNF-008-06: indicadores con el proyecto de D-13: «Comprobando el proyecto… 0 %» "
            f"al quedar usable ({_seconds(opened)} s) y el porcentaje siguiente ≤ "
            f"{_seconds(progress_after)} s después (tic de {_seconds(ops.TICK_S, 2)} s + el más "
            f"largo); «⚠ 1 entrada» {_seconds(inputs_after)} s y «! {counts.obsolete} "
            f"obsoletos» {_seconds(stale_after)} s después del cambio (tic de "
            f"{_seconds(ui.INDICATOR_TICK_S, 1)} s + lectura; presupuesto "
            f"{_seconds(UPDATE_BUDGET_S, 0)} s; escribir las marcas {_seconds(marks)} s); "
            f"dibujar los cuatro campos, mediana de {DRAWS}: {_ms(statistics.median(draws))} ms, "
            f"máximo {_ms(max(draws))} ms (presupuesto {_ms(FIELDS_DRAW_BUDGET_S)} ms)"
        )
        self.assertLessEqual(opened, UPDATE_BUDGET_S)
        self.assertLessEqual(progress_after, UPDATE_BUDGET_S)
        self.assertLessEqual(inputs_after, UPDATE_BUDGET_S)
        self.assertLessEqual(stale_after, UPDATE_BUDGET_S)
        self.assertLessEqual(max(draws), FIELDS_DRAW_BUDGET_S)


class PanelsTest(D13Case):
    def test_parameters_panel(self) -> None:
        """RNF-008-13: Parámetros del proyecto con los 300 parámetros de D-13 y sus 3 000
        entradas de historial: abrirlo, filtrar por módulo, tipo y marca y elegir otro tardan
        ≤ 0,2 s cada uno, y cada redibujado (el panel y las filas visibles de la lista y del
        historial) ≤ 5 ms."""
        self.open_d13()
        view = bpy.context.window_manager.geoblender_provenance
        with mock.patch.object(self.ops, "_call_panel", return_value={"FINISHED"}):
            opened, result = _timed(bpy.ops.geoblender.core_show_parameters)
        self.assertEqual(result, {"FINISHED"})
        self.assertGreaterEqual(len(view.parameters), d13.PARAMETERS)
        times = {"abrir": opened}
        changes = (("módulo", "filter_module", d13.MODULE), ("tipo", "filter_kind", "HIPOTESIS"),
                   ("marca", "filter_mark", "UNCONFIRMED"), ("tipo", "filter_kind", "ALL"),
                   ("marca", "filter_mark", "ALL"))
        for label, name, value in changes:
            took, _ = _timed(lambda name=name, value=value: setattr(view, name, value))
            times[f"filtrar por {label}"] = max(took, times.get(f"filtrar por {label}", 0.0))
        self.assertEqual(len(view.parameters), d13.PARAMETERS)
        times["elegir otro"] = _timed(lambda: setattr(view, "parameter_index", 150))[0]
        self.assertEqual(len(view.parameter_history), d13.REVISIONS)
        ui = self.ui
        layout = NullLayout()
        rows = [view.parameters[index] for index in range(ui.PARAMETER_ROWS)]
        history = [view.parameter_history[index] for index in range(ui.HISTORY_ROWS)]

        def redraw() -> None:
            ui.draw_parameters(layout, bpy.context)
            for row in rows:
                ui.draw_parameter_row(layout, row)
            for row in history:
                ui.draw_history_row(layout, row)

        draws = [_timed(redraw)[0] for _ in range(DRAWS)]
        worst = max(times.values())
        _report(
            f"RNF-008-13: Parámetros del proyecto ({len(view.parameters)} parámetros, "
            f"{d13.PARAMETERS * d13.REVISIONS} entradas de historial): "
            + ", ".join(f"{label} {_seconds(value)} s" for label, value in times.items())
            + f" (presupuesto {_seconds(PANEL_BUDGET_S, 1)} s); redibujar el panel con "
            f"{ui.PARAMETER_ROWS} filas y {ui.HISTORY_ROWS} del historial, {DRAWS} veces: "
            f"mediana {_ms(statistics.median(draws))} ms, máximo {_ms(max(draws))} ms "
            f"(presupuesto {_ms(REDRAW_BUDGET_S)} ms)"
        )
        self.assertLessEqual(worst, PANEL_BUDGET_S)
        self.assertLessEqual(max(draws), REDRAW_BUDGET_S)

    def test_input_register(self) -> None:
        """RNF-008-13: el registro de entradas con las 100 de D-13: abrirlo y volver a leer sus
        filas cuando cambia el proyecto tardan ≤ 0,2 s cada uno, y cada redibujado (el panel y
        las filas visibles) ≤ 5 ms."""
        project, _opened = self.open_d13()
        view = bpy.context.window_manager.geoblender_provenance
        with mock.patch.object(self.ops, "_call_panel", return_value={"FINISHED"}):
            opened, result = _timed(bpy.ops.geoblender.core_show_inputs)
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(view.inputs), d13.INPUTS)
        with project.write_transaction() as conn:  # un cambio cualquiera del proyecto
            conn.execute("UPDATE gb_input SET received_from = 'La propiedad' WHERE uid = ?",
                         (view.inputs[0].uid,))
        reread, count = _timed(self.ui.fill_inputs)
        self.assertEqual(count, d13.INPUTS)
        self.assertEqual(view.inputs[0].received_from, "La propiedad")
        ui = self.ui
        layout = NullLayout()
        rows = [view.inputs[index] for index in range(ui.INPUT_ROWS)]

        def redraw() -> None:
            ui.draw_inputs(layout, bpy.context)
            for row in rows:
                ui.draw_input_row(layout, row)

        draws = [_timed(redraw)[0] for _ in range(DRAWS)]
        _report(
            f"RNF-008-13: registro de entradas ({len(view.inputs)} entradas): abrir "
            f"{_seconds(opened)} s, volver a leerlo tras un cambio del proyecto "
            f"{_seconds(reread)} s (presupuesto {_seconds(PANEL_BUDGET_S, 1)} s); redibujar el "
            f"panel con {ui.INPUT_ROWS} filas, {DRAWS} veces: mediana "
            f"{_ms(statistics.median(draws))} ms, máximo {_ms(max(draws))} ms (presupuesto "
            f"{_ms(REDRAW_BUDGET_S)} ms)"
        )
        self.assertLessEqual(max(opened, reread), PANEL_BUDGET_S)
        self.assertLessEqual(max(draws), REDRAW_BUDGET_S)


class ResponsiveTest(D13Case):
    def test_open_and_check_keep_the_interface_responsive(self) -> None:
        """RNF-008-12: abrir el proyecto de D-13 hasta que es usable tarda ≤ 0,5 s (RNF-002-02)
        sin dar ningún paso de la comprobación; después, mientras corre la comprobación de
        apertura, cada tic del monitor dura ≤ 20 ms y ninguna llamada del hilo de Blender (los
        tics del monitor y de los indicadores y el dibujo de la barra de estado) pasa de
        0,1 s."""
        ops = self.ops
        _project, opened = self.open_d13()
        self.assertTrue(ops.SESSION.running)
        self.assertIsNone(ops.SESSION.progress)  # ningún paso al abrir
        started = time.perf_counter()
        times = self.drive()
        total = time.perf_counter() - started
        report = ops.SESSION.report
        self.assertIsNotNone(report)
        self.assertEqual(report.warnings, ())
        self.assertGreaterEqual(len(report.checked_datasets), d13.DATASETS)
        longest = {kind: max(found) for kind, found in times.items()}
        response = max(longest.values())
        slow = ", ".join(f"{_ms(took)} ms en «{step}»" for took, step in self.slow) or "ninguno"
        _report(
            f"RNF-008-12: abrir el proyecto de D-13 en disco local hasta usable "
            f"{_seconds(opened)} s (presupuesto {_seconds(OPEN_BUDGET_S, 1)} s); comprobación "
            f"de apertura en {len(times['check'])} tics ({_seconds(total, 2)} s sin esperas): "
            f"tic del monitor más largo {_ms(longest['check'])} ms (presupuesto "
            f"{_ms(TICK_BUDGET_S)} ms; los de más: {slow}), de los indicadores "
            f"{_ms(longest['indicator'])} ms, "
            f"dibujo de la barra {_ms(longest['bar'])} ms: la interfaz responde en "
            f"{_seconds(response)} s (presupuesto {_seconds(RESPONSE_BUDGET_S, 1)} s)"
        )
        self.assertLessEqual(opened, OPEN_BUDGET_S)
        self.assertLessEqual(longest["check"], TICK_BUDGET_S)
        self.assertLessEqual(response, RESPONSE_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
