# SPDX-License-Identifier: GPL-3.0-or-later
"""Las vistas regenerables con volumen, dentro de Blender (spec 010, T17; RNF-010-01, RNF-010-02 y
RNF-010-03; plan 010 §2.2 y §7.3, ``tests/rendimiento/blender``).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py --
--carpeta tests/rendimiento/blender --patron "perf_views.py"``). En ``blender -b`` no corren ni
el bucle de eventos ni los temporizadores: la prueba hace de ventana (un evento del temporizador
de la orden cada 0,05 s, esperándolo) y de temporizador (el tic de los indicadores de la
procedencia, ``bl.ui.provenance.indicator_tick``, y los de la marca en vivo,
``bl.scene.live.mark_tick``, con los intervalos que piden sumados sin esperarlos), y mide cada
llamada del hilo de Blender. Los dibujos, con un *layout* nulo
(``perf_ui_draw_cost.NullLayout``): se mide el Python de Geoblender. Cada prueba imprime su cifra
en una línea «RNF-010-nn: …» y la compara con su presupuesto, sin relajarlo; y comprueba que
nada de lo medido escribe en el proyecto (el contador de cambios de la cabecera de
``project.gpkg``).

- **RNF-010-01** (:class:`RefreshTest`): un proyecto de 1 000 × 1 000 m con 200 rejillas cargadas
  con «Cargar en la vista» (una de 1 000 × 1 000 celdas, 1 M de vértices, y 199 de 10 × 10), de
  las que 10 no están al día (la grande y 9 pequeñas: lo que dejaría Ctrl+Z, otro contenido en la
  escena). Refrescar, ``geoblender.core_refresh`` como desde la interfaz (el modal, en pasos), 5
  veces: en total ≤ 5 s (la mediana), ninguna llamada del hilo de Blender de más de 0,2 s (la
  orden y cada evento) y el avance cada ≤ 1 s; y Esc a mitad de la grande: la escena no cambió
  mientras tanto y queda como estaba en ≤ 2 s (el evento en curso y cerrar los pasos).
- **RNF-010-02** (:class:`InventoryTest`): el proyecto de D-13 de la 008
  (``tests/support/provenance_fixtures.py``: 20 000 datos y 100 entradas) con 200 de sus datos en
  la vista y 3 000 objetos del usuario. Abrir N ▸ Proyecto ▸ Inventario sin nada leído (el
  dibujo que pide la lectura y la lectura de su temporizador, con las 500 filas llenas) y cada
  cambio de filtro (el texto tecla a tecla, el tipo, el estado y «En la escena») ≤ 0,5 s; cada
  redibujado (el panel con lo de la fila elegida y 15 filas visibles) ≤ 5 ms. Al día y, otra
  vez, con todo obsoleto (el parámetro común cambiado) y una entrada cambiada (lo que depende de
  ella, 200 datos).
- **RNF-010-03** (:class:`LiveTest`): el mismo proyecto y la misma escena; tras cambiar el
  parámetro común (los 200 obsoletos a la vez), 5 veces: el tic de los indicadores (que lee el
  proyecto cambiado y pide la marca) y las llamadas de la marca, cada una ≤ 20 ms, y todo al día
  ≤ 1 s después del cambio (la espera del tic, lo que tarda, las llamadas y sus intervalos); y,
  antes, sin cambios y con 10 no al día.
- **En la red** (:class:`NetworkTest`; recurso «red» de ``tests.support.network``: con
  ``GEOBLENDER_NET_TEST_DIR``, omitida sin ella): el proyecto de D-13 copiado a una subcarpeta
  temporal de la carpeta de pruebas de ``Z:`` (que se borra al terminar) y abierto allí; las
  lecturas de RNF-010-02 (abrir el inventario y filtrarlo) y de RNF-010-03 (la marca sin cambios y
  con 10 no al día), con los mismos presupuestos.

Los 200 datos de D-13 «en la vista» son un objeto cada uno en la colección de su dato, con su
nombre generado y ``Object.geoblender`` como lo deja la carga, de un cargador de la prueba
(``res_``: los datos de D-13 son filas de tablas, que ningún módulo carga): la marca en vivo y el
inventario solo miran esas marcas.
"""

from __future__ import annotations

import gc
import shutil
import statistics
import time
import unittest
from collections.abc import Callable, Sequence
from types import SimpleNamespace
from typing import Any

import bpy
import numpy as np

from tests.blender.test_views_state import scene_state
from tests.rendimiento.blender.perf_provenance_ui import (
    D13Case,
    _module,
    _ms,
    _report,
    _seconds,
    _timed,
)
from tests.rendimiento.blender.perf_ui_draw_cost import NullLayout
from tests.support import blender_ext, network
from tests.support import provenance_fixtures as d13
from tests.support.core_fixtures import settings_values
from tests.support.resources import requires
from tests.support.trees import temp_folder

LOADED = 200  # datos en la vista (RNF-010-01 y 03)
CHANGED = 10  # de ellos, los que no están al día
USER_OBJECTS = 3000  # objetos del usuario en la escena (plan §2.2)
RUNS = 5  # mediana de 5
DRAWS = 1000  # redibujados para medir lo que cuesta cada uno
VISIBLE_ROWS = 15  # filas de la lista dibujadas en cada redibujado
MAX_CALLS = 400  # llamadas de la marca o eventos de Refrescar: más, no acaba
TIMER_S = 0.05  # el temporizador de la ventana de un modal (``_StepsModal``)
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESC = SimpleNamespace(type="ESC", value="PRESS")

REFRESH_BUDGET_S = 5.0  # RNF-010-01: Refrescar entero
PROGRESS_BUDGET_S = 1.0  # RNF-010-01: el avance, cada
CANCEL_BUDGET_S = 2.0  # RNF-010-01: Esc, la vista como estaba
CALL_BUDGET_S = 0.2  # RNF-010-01: cada llamada del hilo de Blender, en disco local
INVENTORY_BUDGET_S = 0.5  # RNF-010-02: abrir el inventario y filtrarlo
REDRAW_BUDGET_S = 0.005  # RNF-010-02: cada redibujado
MARK_BUDGET_S = 1.0  # RNF-010-03: al día tras el cambio
MARK_CALL_BUDGET_S = 0.020  # RNF-010-03: cada llamada de la marca en el hilo de Blender

LOADER = "res_"  # el comienzo de los nombres de los datos de D-13
OUTDATED_SHA = "0" * 64  # otro contenido en la escena (lo que deja Ctrl+Z)
VIEWED_KIND = "DTM"

# Los cambios de filtro del inventario, en orden: el texto tecla a tecla (el campo filtra a cada
# tecla), «En la escena», el tipo y el estado, y vuelta a lo de por defecto.
FILTERS: tuple[tuple[str, str], ...] = (
    ("inventory_text", "d"),
    ("inventory_text", "d1"),
    ("inventory_text", "d12"),
    ("inventory_presence", "IN"),
    ("inventory_text", ""),
    ("inventory_presence", "ALL"),
    ("inventory_kind", "RASTER"),
    ("inventory_status", "STALE"),
    ("inventory_status", "INPUT_CHANGED"),
    ("inventory_kind", "INPUT"),
    ("inventory_status", "ALL"),
    ("inventory_kind", "ALL"),
    ("inventory_status", "LIVE"),
)

# Las rejillas de RNF-010-01: el proyecto, de 1 000 × 1 000 m con paso de 1 m.
WEST, SOUTH, SIZE = 700_000.0, 4_400_000.0, 1000
SMALL = 10  # celdas de lado de cada rejilla pequeña
RESAMPLE_PARAM = "gis.resample.min_valid_fraction"


def _median_text(values: Sequence[float], unit: Callable[[float], str], suffix: str) -> str:
    """«mediana X, máximo Y» con la unidad de ``unit`` y su ``suffix`` («s» o «ms»)."""
    return (f"mediana {unit(statistics.median(values))} {suffix}, máximo {unit(max(values))} "
            f"{suffix}")


def _calls(count: int) -> str:
    """«1 llamada» o «3 llamadas»."""
    return "1 llamada" if count == 1 else f"{count} llamadas"


def _counter(project: Any) -> int:
    """El contador de cambios de la cabecera de ``project.gpkg`` (lo que sube al escribir)."""
    return _module("core.gpkg.header").read_header(project.database_path).change_counter


def _marks(live: Any) -> tuple[list[float], float]:
    """Hace de temporizador de la marca en vivo hasta que se retira: lo que tardó cada llamada
    y la suma de los intervalos que pidió entre ellas."""
    calls: list[float] = []
    waits = 0.0
    for _ in range(MAX_CALLS):
        took, interval = _timed(live.mark_tick)
        calls.append(took)
        if interval is None:
            return calls, waits
        waits += interval
    raise AssertionError("la marca en vivo no acaba")


class _D13View(D13Case):
    """El proyecto de D-13 (:class:`D13Case`) con el cargador de la prueba de sus datos y, en
    cada prueba, la escena de :meth:`populate`; los textos, en español."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        try:
            cls.views = _module("bl.scene.views")
            cls.live = _module("bl.scene.live")
            cls.panels = _module("bl.ui.view_panels")
            cls.model = _module("core.datasets.model")
            cls.state = _module("core.views.state")
            cls.ROW_LIMIT = _module("core.views.inventory").ROW_LIMIT
            i18n = _module("core.i18n")
            cls.stack.callback(i18n.set_language, i18n.language())
            i18n.set_language("es")

            def load(_request: Any) -> Any:  # pragma: no cover - aquí no se carga nada
                raise AssertionError("la prueba no carga datos de D-13")

            cls.views.register_loader(LOADER, VIEWED_KIND, VIEWED_KIND, load)
            cls.stack.callback(cls.views.unregister_loader, LOADER)
            cls.loader = cls.views.loaders()[LOADER]
        except BaseException:
            cls.stack.close()
            raise

    def populate(self, project: Any) -> list[Any]:
        """3 000 objetos del usuario (en «99 Trabajo») y los 200 primeros datos vigentes de D-13
        «cargados»: un objeto cada uno en la colección de su dato, con su nombre generado y
        ``Object.geoblender`` como lo deja la carga. Devuelve sus registros, en orden."""
        views = self.views
        self.addCleanup(self._clear_scene)
        user = bpy.data.collections.new("99 Trabajo")
        bpy.context.scene.collection.children.link(user)
        for index in range(USER_OBJECTS):
            user.objects.link(bpy.data.objects.new(f"Croquis {index}", None))
        model = self.model
        with project.read() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(model.RECORD_COLUMNS)} FROM gb_dataset "
                "WHERE status = 'current' ORDER BY fid LIMIT ?", (LOADED,)).fetchall()
        records = [model.DatasetRecord.from_row(row) for row in rows]
        self.assertEqual(len(records), LOADED)
        origin = self.state.origin_text(project.origin)
        for record in records:
            mesh = bpy.data.meshes.new("m")
            mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
            name = views.view_name(self.loader, record, stale=False)
            obj = bpy.data.objects.new(name, mesh)
            views.ensure_collection(VIEWED_KIND, record, name=name).objects.link(obj)
            props = obj.geoblender
            props.kind = VIEWED_KIND
            props.dataset_uid = record.uid
            props.project_uid = project.uid
            props.content_sha256 = record.content_sha256
            props.status = "CURRENT"
            props.stale = False
            props.view_state = "CURRENT"
            props.origin = origin
        return records

    @staticmethod
    def _clear_scene() -> None:
        for obj in list(bpy.data.objects):
            data = obj.data
            bpy.data.objects.remove(obj)
            if isinstance(data, bpy.types.Mesh) and data.users == 0:
                bpy.data.meshes.remove(data)
        for collection in list(bpy.data.collections):
            bpy.data.collections.remove(collection)

    def objects(self, records: Sequence[Any]) -> list[Any]:
        """El objeto de cada dato de ``records`` (buscados otra vez: un nombre cambiado no los
        invalida, pero así no se guardan objetos de Blender)."""
        found = self.views.loaded_items()
        return [found[record.uid][0] for record in records]

    @staticmethod
    def view() -> Any:
        """``WindowManager.geoblender_view_panels`` (leída otra vez: ``docs/trampas.md`` §4)."""
        name = _module("bl.props.views").WINDOW_MANAGER_PROPERTY
        return getattr(bpy.context.window_manager, name)

    # RNF-010-02 -----------------------------------------------------------------------------

    def open_inventory(self, project: Any) -> float:
        """Abrir el inventario sin nada leído (como recién abierto el proyecto): el dibujo del
        panel, que pide la lectura, y la lectura (el temporizador de un disparo), hasta las 500
        filas llenas; lo que tardan los dos."""
        panels = self.panels
        panels.on_project_changed(project)  # olvida lo leído, como al abrir el proyecto
        self.assertEqual(len(self.view().inventory), 0)
        gc.collect()
        layout = NullLayout()
        drawn, _ = _timed(lambda: panels.draw_inventory(layout, bpy.context))
        tick = panels.inventory_tick
        self.assertTrue(bpy.app.timers.is_registered(tick), "el dibujo no pidió la lectura")
        bpy.app.timers.unregister(tick)  # en -b no corre: se llama a su función
        read, interval = _timed(tick)
        self.assertIsNone(interval)
        view = self.view()
        self.assertEqual(len(view.inventory), self.ROW_LIMIT)
        self.assertEqual(view.inventory_project, project.uid)
        return drawn + read

    def filter_inventory(self) -> list[float]:
        """Cada cambio de filtro de :data:`FILTERS` (lo que hace su ``update``: filtrar lo leído
        con lo que está en la escena y llenar las filas): lo que tarda cada uno."""
        view = self.view()
        took = []
        for name, value in FILTERS:
            took.append(_timed(lambda name=name, value=value: setattr(view, name, value))[0])
        self.assertEqual(len(view.inventory), self.ROW_LIMIT)  # vuelta a lo de por defecto
        self.assertFalse(bpy.app.timers.is_registered(self.panels.inventory_tick))
        return took

    def redraws(self) -> list[float]:
        """Lo que cuesta cada redibujado del panel (con lo de la fila elegida) y de
        :data:`VISIBLE_ROWS` filas de la lista, :data:`DRAWS` veces; ninguno pide leer."""
        panels = self.panels
        view = self.view()
        view.inventory_index = 0
        rows = [view.inventory[index] for index in range(VISIBLE_ROWS)]
        layout = NullLayout()
        context = bpy.context

        def redraw() -> None:
            panels.draw_inventory(layout, context)
            for row in rows:
                panels.draw_inventory_row(layout, row)

        times = [_timed(redraw)[0] for _ in range(DRAWS)]
        self.assertFalse(bpy.app.timers.is_registered(panels.inventory_tick),
                         "redibujar pidió leer el inventario")
        return times

    # RNF-010-03 -----------------------------------------------------------------------------

    def steady_marks(self, project: Any) -> list[float]:
        """La marca pedida sin que nada haya cambiado, :data:`RUNS` veces: lo que tarda la
        llamada más larga de cada vez."""
        live = self.live
        longest = []
        for _ in range(RUNS):
            live.request(project)
            calls, _ = _marks(live)
            longest.append(max(calls))
            self.assertEqual(live.pending_count(), 0)
        return longest

    def outdated_marks(self, project: Any, records: Sequence[Any]) -> tuple[list[float], float]:
        """10 de los 200 con otro contenido en la escena (lo que deja Ctrl+Z, que pide la
        marca): las llamadas de la marca y cuánto tarda en estar al día (las llamadas y sus
        intervalos); después, otra vez como estaban."""
        live = self.live
        for obj in self.objects(records)[:CHANGED]:
            obj.geoblender.content_sha256 = OUTDATED_SHA
        live.request(project)
        calls, waits = _marks(live)
        names = [obj.name for obj in self.objects(records)[:CHANGED]]
        self.assertTrue(all(name.endswith("[VIGENTE · NO AL DÍA]") for name in names), names)
        self.assertEqual(live.pending_count(), CHANGED)
        for record, obj in zip(records, self.objects(records), strict=True):
            obj.geoblender.content_sha256 = record.content_sha256
        live.request(project)
        _marks(live)
        self.assertEqual(live.pending_count(), 0)
        return calls, sum(calls) + waits

    def change_common_parameter(self, project: Any, step: float) -> float:
        """Cambia el parámetro que leen todas las cadenas de D-13 (todo queda obsoleto); lo que
        tarda en escribirse (no es de la marca)."""
        store = _module("core.params").ParameterStore(project)
        value = store.get(d13.COMMON_KEY).value
        started = time.perf_counter()
        with project.write_transaction() as conn:
            store.change(conn, d13.COMMON_KEY, value=value + step,
                         reason="Prueba de rendimiento de la 010")
        return time.perf_counter() - started


# --- RNF-010-02 --------------------------------------------------------------------------------


class InventoryTest(_D13View):

    def test_inventory_of_d13(self) -> None:
        """RNF-010-02 (plan §7.3; D-7, D-8, D-15): el inventario del proyecto de D-13 (20 000
        datos, 100 entradas) con 200 datos en la vista y 3 000 objetos del usuario: abrirlo sin
        nada leído, hasta sus 500 filas, y cada cambio de filtro ≤ 0,5 s; cada redibujado (el
        panel y 15 filas) ≤ 5 ms. Al día y con todo obsoleto y una entrada cambiada. Nada se
        escribe en el proyecto al leerlo ni al filtrarlo."""
        project, _opened = self.open_d13()
        self.populate(project)
        before = _counter(project)
        opened_current = [self.open_inventory(project) for _ in range(RUNS)]
        filtered_current = self.filter_inventory()
        drawn_current = self.redraws()
        self.assertEqual(_counter(project), before)
        view = self.view()
        self.assertEqual(view.inventory_total, d13.DATASETS + d13.INPUTS)
        self.assertFalse(any(row.stale for row in view.inventory))

        # Todo obsoleto (el parámetro común) y la primera entrada cambiada sin decidir (como la
        # deja la comprobación de las entradas): lo que depende de ella, su cadena.
        self.change_common_parameter(project, 1.0)
        with project.write_transaction() as conn:
            first = conn.execute("SELECT uid FROM gb_input ORDER BY fid LIMIT 1").fetchone()[0]
            conn.execute("UPDATE gb_input SET status = 'changed' WHERE uid = ?", (first,))
        changed = _counter(project)
        # Lo que pasa en la sesión: el tic de los indicadores lee el proyecto cambiado y pide la
        # marca (que deja viejo el inventario); el siguiente dibujo pide leerlo otra vez.
        self.ui.indicator_tick()
        self.assertTrue(self.panels.inventory_is_old(project))
        layout = NullLayout()
        drawn, _ = _timed(lambda: self.panels.draw_inventory(layout, bpy.context))
        bpy.app.timers.unregister(self.panels.inventory_tick)
        reread, _ = _timed(self.panels.inventory_tick)
        reread += drawn
        _marks(self.live)  # la marca que pidió el tic (en -b no corre sola)
        rows = {row.category: [] for row in view.inventory}
        for row in view.inventory:
            rows[row.category].append(row)
        self.assertEqual(sorted(rows), ["DATASET", "INPUT"])  # por nombre: «Entrada_…» antes
        self.assertTrue(all(row.stale for row in rows["DATASET"]))
        self.assertEqual([row.input_changed for row in rows["INPUT"]].count(True), 1)
        opened_changed = [self.open_inventory(project) for _ in range(RUNS)]
        view.inventory_status = "INPUT_CHANGED"
        affected = view.inventory_total
        view.inventory_status = "LIVE"
        filtered_changed = self.filter_inventory()
        drawn_changed = self.redraws()
        self.assertEqual(_counter(project), changed)
        self.assertEqual(affected, 1 + d13.OPERATIONS // d13.CHAINS * d13.OUTPUTS)

        opens = opened_current + opened_changed + [reread]
        filters = filtered_current + filtered_changed
        draws = drawn_current + drawn_changed
        worst = max(opens) + max(filters)
        _report(
            f"RNF-010-02: inventario del proyecto de D-13 ({d13.DATASETS} datos y {d13.INPUTS} "
            f"entradas, {self.ROW_LIMIT} filas) con {LOADED} datos en la vista y "
            f"{USER_OBJECTS} objetos del usuario: abrirlo sin nada leído, {RUNS} veces, al día "
            f"{_median_text(opened_current, _seconds, 's')} y con todo obsoleto y una entrada "
            f"cambiada ({affected} afectados) {_median_text(opened_changed, _seconds, 's')}; "
            f"leerlo otra vez tras el cambio {_seconds(reread)} s; cada cambio de filtro "
            f"({len(FILTERS)}, el texto tecla a tecla), máximo {_seconds(max(filters))} s; abrir "
            f"y filtrar, lo peor, {_seconds(worst)} s (presupuesto "
            f"{_seconds(INVENTORY_BUDGET_S, 1)} s); redibujar el panel y {VISIBLE_ROWS} filas, "
            f"{2 * DRAWS} veces: mediana {_ms(statistics.median(draws))} ms, máximo "
            f"{_ms(max(draws))} ms (presupuesto {_ms(REDRAW_BUDGET_S)} ms)"
        )
        self.assertLessEqual(worst, INVENTORY_BUDGET_S)
        self.assertLessEqual(max(draws), REDRAW_BUDGET_S)


# --- RNF-010-03 --------------------------------------------------------------------------------


class LiveTest(_D13View):

    def reset(self, records: Sequence[Any]) -> None:
        """Los 200 objetos (y sus colecciones) como recién cargados, sin la marca de
        obsoleto."""
        views = self.views
        collections = {item.get(views.KEY_PROPERTY): item for item in bpy.data.collections}
        for record, obj in zip(records, self.objects(records), strict=True):
            name = views.view_name(self.loader, record, stale=False)
            obj.geoblender.stale = False
            obj.name = name
            collections[f"{views.DATASET_KEY}{record.uid}"].name = name

    def test_live_mark_of_d13(self) -> None:
        """RNF-010-03 (plan §7.3; D-12): con el proyecto de D-13, 200 de sus datos en la vista
        y 3 000 objetos del usuario, tras cambiar el parámetro que leen todas las cadenas, los
        200 «[VIGENTE · OBSOLETO]» ≤ 1 s después del cambio (la espera del tic de los
        indicadores, su lectura, las llamadas de la marca y sus intervalos), cada llamada de la
        marca ≤ 20 ms; 5 veces. Antes, la primera marca tras abrir, la marca sin cambios y con
        10 no al día. La marca no escribe en el proyecto."""
        live, ui = self.live, self.ui
        project, _opened = self.open_d13()
        records = self.populate(project)
        first_tick, _ = _timed(ui.indicator_tick)
        first, _ = _marks(live)
        self.assertEqual(live.pending_count(), 0)
        before = _counter(project)
        steady = self.steady_marks(project)
        outdated, outdated_s = self.outdated_marks(project, records)
        self.assertEqual(_counter(project), before)

        runs = []
        for index in range(RUNS):
            self.reset(records)
            gc.collect()
            written = self.change_common_parameter(project, 1.0 + index)
            changed = _counter(project)
            tick, interval = _timed(ui.indicator_tick)
            self.assertEqual(interval, ui.INDICATOR_TICK_S)
            calls, waits = _marks(live)
            objects = self.objects(records)
            names = [obj.name for obj in objects]
            self.assertTrue(all(name.endswith("[VIGENTE · OBSOLETO]") for name in names),
                            names[:3])
            self.assertTrue(all(obj.geoblender.stale for obj in objects))
            self.assertEqual(_counter(project), changed)
            after = ui.INDICATOR_TICK_S + tick + sum(calls) + waits
            runs.append((after, max(calls), len(calls), tick, written))
            _report(f"  · RNF-010-03 vuelta {index + 1}: escribir el parámetro "
                    f"{_seconds(written)} s (no es de la marca); tic de los indicadores "
                    f"{_seconds(tick)} s; la marca, {_calls(len(calls))}, la más larga "
                    f"{_ms(max(calls))} ms; al día {_seconds(after)} s después del cambio")
        afters = [run[0] for run in runs]
        longest = max(max(run[1] for run in runs), max(first), max(steady), max(outdated))
        _report(
            f"RNF-010-03: marca en vivo con el proyecto de D-13, {LOADED} datos en la vista y "
            f"{USER_OBJECTS} objetos del usuario: los {LOADED} obsoletos tras cambiar el "
            f"parámetro común, {RUNS} veces, al día {_median_text(afters, _seconds, 's')} "
            f"después del cambio (tic de {_seconds(ui.INDICATOR_TICK_S, 1)} s, su lectura "
            f"{_median_text([run[3] for run in runs], _seconds, 's')}, la marca en "
            f"{_calls(max(run[2] for run in runs))} como mucho; presupuesto "
            f"{_seconds(MARK_BUDGET_S, 0)} s); {CHANGED} no al día, al día en "
            f"{_seconds(outdated_s)} s; llamada de la marca más larga {_ms(longest)} ms (la "
            f"primera tras abrir {_ms(max(first))} ms con el tic de los indicadores "
            f"{_seconds(first_tick)} s; sin cambios {_median_text(steady, _ms, 'ms')}; con "
            f"{CHANGED} no al día {_ms(max(outdated))} ms; los {LOADED} obsoletos "
            f"{_ms(max(run[1] for run in runs))} ms; presupuesto {_ms(MARK_CALL_BUDGET_S)} ms)"
        )
        self.assertLessEqual(longest, MARK_CALL_BUDGET_S)
        self.assertLessEqual(max(afters), MARK_BUDGET_S)


# --- RNF-010-02 y 03 en la red -----------------------------------------------------------------


@requires(network.NET, network.NET_HINT)
class NetworkTest(_D13View):

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        try:
            folder = cls.stack.enter_context(network.net_tmp("gb-010-"))
            started = time.perf_counter()
            target = folder / cls.root.name
            shutil.copytree(cls.root, target)
            cls.copy_s = time.perf_counter() - started
            cls.root = target
        except BaseException:
            cls.stack.close()
            raise

    def test_reads_on_the_network(self) -> None:
        """RNF-010-02 y RNF-010-03 en la red (plan §2.2 y §7.3): el proyecto de D-13 abierto en
        la carpeta de pruebas de ``Z:``, con 200 datos en la vista y 3 000 objetos del usuario:
        abrir el inventario sin nada leído y cada cambio de filtro ≤ 0,5 s; la marca en vivo sin
        cambios y con 10 no al día, cada llamada ≤ 20 ms y al día ≤ 1 s. Nada se escribe en el
        proyecto."""
        live, ui = self.live, self.ui
        project, opened = self.open_d13()
        self.assertTrue(project.is_network)
        records = self.populate(project)
        before = _counter(project)
        first_tick, _ = _timed(ui.indicator_tick)
        first, _ = _marks(live)
        steady = self.steady_marks(project)
        outdated, outdated_s = self.outdated_marks(project, records)
        opens = [self.open_inventory(project) for _ in range(RUNS)]
        filters = self.filter_inventory()
        self.assertEqual(_counter(project), before)
        worst = max(opens) + max(filters)
        longest = max(max(first), max(steady), max(outdated))
        _report(
            f"RNF-010-02: inventario del proyecto de D-13 en la red (Z:, copiado en "
            f"{_seconds(self.copy_s, 1)} s y abierto en {_seconds(opened)} s) con {LOADED} "
            f"datos en la vista: abrirlo sin nada leído, {RUNS} veces, "
            f"{_median_text(opens, _seconds, 's')}; cada cambio de filtro, máximo "
            f"{_seconds(max(filters))} s; abrir y filtrar, lo peor, {_seconds(worst)} s "
            f"(presupuesto {_seconds(INVENTORY_BUDGET_S, 1)} s)"
        )
        _report(
            f"RNF-010-03: marca en vivo con el proyecto de D-13 en la red (Z:) y {LOADED} datos "
            f"en la vista: la primera tras abrir {_ms(max(first))} ms (el tic de los "
            f"indicadores {_seconds(first_tick)} s), sin cambios "
            f"{_median_text(steady, _ms, 'ms')}, con {CHANGED} no al día {_ms(max(outdated))} "
            f"ms y al día en {_seconds(outdated_s)} s; llamada más larga {_ms(longest)} ms "
            f"(presupuestos {_ms(MARK_CALL_BUDGET_S)} ms y {_seconds(MARK_BUDGET_S, 0)} s)"
        )
        self.assertLessEqual(worst, INVENTORY_BUDGET_S)
        self.assertLessEqual(longest, MARK_CALL_BUDGET_S)
        self.assertLessEqual(outdated_s, MARK_BUDGET_S)


# --- RNF-010-01 --------------------------------------------------------------------------------


class RefreshTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.ps = _module("bl.scene.project_session")
        cls.provenance_ops = _module("bl.ops.core_provenance")
        cls.core = _module("core.project")
        cls.views = _module("bl.scene.views")
        cls.live = _module("bl.scene.live")
        i18n = _module("core.i18n")
        cls.language = i18n.language()
        i18n.set_language("es")

    @classmethod
    def tearDownClass(cls) -> None:
        _module("core.i18n").set_language(cls.language)
        cls.ps.close()
        blender_ext.load_file()
        blender_ext.release()

    def open_project(self) -> Any:
        """Un proyecto nuevo de 1 000 × 1 000 m con paso de 1 m, abierto en la sesión (con su
        comprobación de apertura terminada)."""
        parent = temp_folder(self, "gb-010-f5-") / "proyectos"
        parent.mkdir(parents=True)
        window = (WEST, SOUTH, WEST + SIZE, SOUTH + SIZE)
        settings = self.core.ProjectSettings(**settings_values(window=window, grid_step_m=1.0))
        project = self.core.create_project(parent, settings, self.ps.session(),
                                           self.ps.userdata()).project
        self.ps.attach(project)
        self.addCleanup(self.ps.close)
        for _ in range(500):
            if self.provenance_ops.check_tick() is None:
                break
        self.ps.take_notices()
        return project

    @staticmethod
    def write_grids(project: Any) -> list[str]:
        """La rejilla grande (la ventana entera: 1 000 × 1 000 celdas) y 199 pequeñas de 10 × 10,
        cada una de su operación ``gis.resample``; sus nombres."""
        store = _module("gis.store")
        grid_mod, raster_mod = _module("gis.grid"), _module("gis.raster")
        operations = _module("core.provenance.operations")
        prov = _module("gis.provenance")
        crs, vertical = store.project_references(project)

        def write(name: str, grid: Any, values: Any) -> str:
            handle = operations.begin_operation(project, prov.RESAMPLE, settings={"name": name},
                                                params=[RESAMPLE_PARAM], executor="blender")
            with store.ResultWriter(project, handle) as out:
                out.raster(name, raster_mod.Raster(grid, values, crs, vertical))
                out.commit(software={"pyproj": "3.8.0"}, message="Prueba de rendimiento")
            return prov.dataset_name(prov.PROJECT_GRID, name)

        big = grid_mod.project_grid(project.window, project.grid_step_m)
        x, y = big.centers()
        names = [write("grande", big, 200.0 + 0.01 * (x - WEST) + 0.02 * (y - SOUTH))]
        for index in range(LOADED - 1):
            column, row = index % 90, index // 90
            grid = grid_mod.Grid(WEST + column * SMALL, SOUTH + SIZE - row * SMALL, 1.0, 1.0,
                                 SMALL, SMALL)
            names.append(write(f"p{index:03d}", grid,
                               np.full((SMALL, SMALL), 100.0 + index)))
        return names

    @staticmethod
    def in_scene() -> list[tuple[str, str, str, tuple[str, ...]]]:
        """Lo que se ve: los objetos de la escena (nombre, sus datos, su hash y sus
        colecciones)."""
        return sorted((obj.name, "" if obj.data is None else obj.data.name,
                       obj.geoblender.content_sha256,
                       tuple(sorted(item.name for item in obj.users_collection)))
                      for obj in bpy.context.scene.objects)

    def start(self) -> tuple[Any, float, float]:
        """F5 como desde la interfaz: la orden en pasos (el modal); la orden, cuándo se pidió y
        lo que tardó la llamada."""
        started = time.perf_counter()
        result = bpy.ops.geoblender.core_refresh("EXEC_DEFAULT", in_steps=True)
        took = time.perf_counter() - started
        self.assertEqual(result, {"RUNNING_MODAL"})
        cls = getattr(bpy.types, "GEOBLENDER_OT_core_refresh")
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "Refrescar no está en marcha como modal")
        return found[0], started, took

    def drive(self, operator: Any, started: float) -> tuple[set[str], float, float, float]:
        """Como la ventana: un evento del temporizador cada 0,05 s hasta que acaba. Su final, el
        total, el evento más largo y el mayor hueco del avance (desde que se pidió hasta que
        acabó)."""
        longest = 0.0
        for _ in range(MAX_CALLS):
            time.sleep(TIMER_S)
            took, state = _timed(lambda: operator.modal(bpy.context, TIMER))
            longest = max(longest, took)
            if state != {"RUNNING_MODAL"}:
                break
        else:
            self.fail("Refrescar no acaba")
        ended = time.perf_counter()
        stamps = [started, *(entry[0] for entry in operator.progress_log), ended]
        return state, ended - started, longest, float(np.max(np.diff(stamps)))

    def outdate(self, uids: Sequence[str]) -> None:
        """Otro contenido en la escena de los datos ``uids`` (lo que deja Ctrl+Z)."""
        for obj in bpy.data.objects:
            if obj.geoblender.dataset_uid in uids:
                obj.geoblender.content_sha256 = OUTDATED_SHA

    def test_refresh_two_hundred(self) -> None:
        """RNF-010-01 (plan §7.3; D2): 200 rejillas en la vista (una de 1 M de vértices), 10 no
        al día (la grande y 9 pequeñas): Refrescar en pasos, 5 veces, vuelve a cargar esas 10 en
        ≤ 5 s (la mediana), con el avance cada ≤ 1 s y ninguna llamada del hilo de Blender de
        más de 0,2 s; Esc a mitad de la grande deja la vista como estaba (sin cambiar mientras
        tanto) en ≤ 2 s. Refrescar no escribe en el proyecto."""
        project = self.open_project()
        started = time.perf_counter()
        names = self.write_grids(project)
        written = time.perf_counter() - started
        started = time.perf_counter()
        self.assertEqual(bpy.ops.geoblender.core_load_into_view(
            "EXEC_DEFAULT", datasets=",".join(names)), {"FINISHED"})
        loaded = time.perf_counter() - started
        _marks(self.live)
        self.assertEqual(self.live.pending_count(), 0)
        groups = self.views.loaded_items()
        self.assertEqual(len(groups), LOADED)
        big = next(uid for uid, objs in groups.items()
                   if any(len(getattr(obj.data, "vertices", ())) > SMALL * SMALL for obj in objs))
        vertices = sum(len(obj.data.vertices) for obj in groups[big])
        self.assertGreaterEqual(vertices, SIZE * SIZE)
        wanted = [big, *[uid for uid in groups if uid != big][:CHANGED - 1]]
        before = _counter(project)

        runs = []
        for index in range(RUNS):
            gc.collect()
            self.outdate(wanted)
            operator, started, call = self.start()
            state, total, longest, gap = self.drive(operator, started)
            self.assertEqual(state, {"FINISHED"})
            self.assertEqual(operator.report_log[-1],
                             f"Vista al día: {CHANGED} datos vueltos a cargar, "
                             f"{LOADED - CHANGED} al día")
            runs.append((total, max(call, longest), gap))
            _report(f"  · RNF-010-01 vuelta {index + 1}: total {_seconds(total)} s; llamada "
                    f"más larga {_seconds(max(call, longest))} s; mayor hueco del avance "
                    f"{_seconds(gap)} s")
            _marks(self.live)
            self.assertEqual(self.live.pending_count(), 0)

        # Esc a mitad de la grande: la escena no cambia y queda como estaba.
        self.outdate([big])
        before_cancel = scene_state()
        shown = self.in_scene()
        operator, started, call = self.start()
        done = 0
        longest = call
        for _ in range(MAX_CALLS):
            if done >= self.views.STEPS_TOTAL // 2:
                break
            time.sleep(TIMER_S)
            took, state = _timed(lambda: operator.modal(bpy.context, TIMER))
            longest = max(longest, took)
            self.assertEqual(state, {"RUNNING_MODAL"})
            done = operator.progress_log[-1][2] if operator.progress_log else 0
        middle = self.in_scene() == shown
        cancel, state = _timed(lambda: operator.modal(bpy.context, ESC))
        self.assertEqual(state, {"CANCELLED"})
        self.assertTrue(middle, "la escena cambió a mitad de Refrescar")
        self.assertEqual(scene_state(), before_cancel)
        self.assertEqual(operator.report_log[-1],
                         "Refrescar cancelado: la vista queda como estaba")
        self.assertEqual(_counter(project), before)

        totals = [run[0] for run in runs]
        slowest = max(max(run[1] for run in runs), longest)
        gap = max(run[2] for run in runs)
        stopped = longest + cancel  # el evento en curso y cerrar los pasos
        _report(
            f"RNF-010-01: Refrescar en pasos con {LOADED} rejillas en la vista (escritas en "
            f"{_seconds(written, 1)} s y cargadas en {_seconds(loaded, 1)} s; la grande de "
            f"{vertices} vértices) y {CHANGED} no al día (la grande y {CHANGED - 1} pequeñas), "
            f"{RUNS} veces: total {_median_text(totals, _seconds, 's')} (presupuesto "
            f"{_seconds(REFRESH_BUDGET_S, 0)} s); llamada del hilo de Blender más larga "
            f"{_seconds(slowest)} s (presupuesto {_seconds(CALL_BUDGET_S, 1)} s); mayor hueco "
            f"del avance {_seconds(gap)} s (presupuesto {_seconds(PROGRESS_BUDGET_S, 0)} s); Esc "
            f"a mitad de la grande ({done * 100 // self.views.STEPS_TOTAL} %): la escena igual "
            f"mientras tanto y como estaba en {_seconds(stopped)} s (cerrar los pasos "
            f"{_seconds(cancel)} s; presupuesto {_seconds(CANCEL_BUDGET_S, 0)} s)"
        )
        self.assertLessEqual(statistics.median(totals), REFRESH_BUDGET_S)
        self.assertLessEqual(slowest, CALL_BUDGET_S)
        self.assertLessEqual(gap, PROGRESS_BUDGET_S)
        self.assertLessEqual(stopped, CANCEL_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
