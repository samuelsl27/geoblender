# SPDX-License-Identifier: GPL-3.0-or-later
"""La marca en vivo (spec 010, T08; RF-010-02; RNF-010-03; plan 010 §5.3.2, A3, D-12).

Con el proyecto sintético de ``tests/support/views_fixtures.py`` (rejillas de 10 × 10 celdas y
las entradas que importa cada prueba), abierto en la sesión y cargado en la escena. En
``blender -b`` no corren los temporizadores (``docs/trampas.md`` §3): cada prueba hace a mano
un tic de los indicadores de la procedencia (``bl.ui.provenance.indicator_tick``, que lee el
proyecto cuando cambia y pide la marca) y los de la marca (``bl.scene.live.mark_tick``, hasta
que acaba):

- **tras cada cambio del proyecto**, sin volver a cargar nada: recalcular una rejilla la deja
  «[VIGENTE · NO AL DÍA]» y las demás, igual; un parámetro, «OBSOLETO» sin «NO AL DÍA»;
  sustituir su entrada, lo importado de ella «NO AL DÍA»; descartarla, «[SIN RESPALDO]», sin
  borrar nada; los objetos del usuario y «99 Trabajo», con su nombre; hasta el tic, como
  estaba;
- **Refrescar (control 7) resaltado** mientras algo no está al día, con cuántos en su
  descripción («1 dato de la vista no está al día»), y no después (volver a cargar o descargar
  lo que no lo estaba también pide la marca); al cerrar el proyecto, nada;
- **Ctrl+Z** (con ``ed.undo_push``, ``docs/trampas.md`` §4) hasta antes de una recarga la deja
  «NO AL DÍA» y rehacer, al día; **abrir un ``.blend``** del proyecto abierto, lo mismo;
- **por tandas**: con presupuesto, un dato por tic y lo que queda en el siguiente; una petición
  a mitad vuelve a leer el proyecto;
- **RNF-010-03**: con 200 datos que cambian a la vez, cada llamada de la marca ≤ 20 ms
  (``tests.support.timing.least_of``) y todos al día en ≤ 1 s tras el cambio;
- **nada escrito en el proyecto** (el contador de cambios de su cabecera);
- **registro y desregistro sin rastro**: los manejadores ``@persistent`` de ``undo_post``,
  ``redo_post`` y ``load_post``, la petición tras cada lectura de los indicadores y el
  proveedor de estado de las órdenes; desactivada, la huella de Blender como al principio.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import time
import unittest
from collections.abc import Callable
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import fingerprint_diff
from tests.support.timing import least_of
from tests.support.trees import temp_folder

MARK_CALL_BUDGET_S = 0.020
"""RNF-010-03: lo que puede tardar cada llamada de la marca en el hilo de Blender."""
MARKED_BUDGET_S = 1.0
"""RNF-010-03: todos al día tras el cambio."""
MAX_TICKS = 400
LIVE_HANDLERS = ("load_post", "undo_post", "redo_post")


def marks(obj: bpy.types.Object) -> tuple[Any, ...]:
    """Lo que dice ``Object.geoblender`` de ``obj`` (sin sus cifras)."""
    props = obj.geoblender
    return (props.dataset_uid, props.content_sha256, props.status, props.stale,
            props.view_state, props.origin)


class ViewsLiveTest(unittest.TestCase):
    """La extensión habilitada una vez; un proyecto de la prueba nuevo en cada una."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.views = vf.extension("bl.scene.views")
        self.live = vf.extension("bl.scene.live")
        self.ui = vf.extension("bl.ui.provenance")
        self.commands = vf.extension("bl.ui.commands")
        self.i18n = vf.extension("core.i18n")
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")
        self.folder = temp_folder(self, "gb-v010l-")
        self.data = vf.ViewsProject(self.folder)
        self.data.attach()
        self.addCleanup(self.data.close)
        self.addCleanup(blender_ext.load_file)

    # --- Ayudas de la prueba ------------------------------------------------------------------

    def only(self, uid: str) -> bpy.types.Object:
        (found,) = vf.objects_of(bpy.data, uid)
        return found

    def short(self, record: Any) -> str:
        """El nombre de ``record`` sin el comienzo de su familia («rejilla_01»)."""
        return record.name[len(self.views.loader_for(record.name).prefix):]

    def collection_of(self, uid: str) -> bpy.types.Collection | None:
        key = f"{self.views.DATASET_KEY}{uid}"
        return next((item for item in bpy.data.collections
                     if item.get(self.views.KEY_PROPERTY) == key), None)

    def shown(self) -> dict[str, tuple[Any, ...]]:
        """Lo que muestra cada dato cargado: el nombre de su objeto y de su colección, «al
        día», su estado y si está obsoleto."""
        found: dict[str, tuple[Any, ...]] = {}
        for uid, (obj,) in vf.loaded(bpy.data).items():
            props = obj.geoblender
            collection = self.collection_of(uid)
            found[uid] = (obj.name, None if collection is None else collection.name,
                          props.view_state, props.status, props.stale)
        return found

    def indicators(self) -> float:
        """Un tic de los indicadores de la procedencia (lee el proyecto si cambió y, tras
        leerlo, pide la marca); lo que tardó."""
        started = time.perf_counter()
        self.assertEqual(self.ui.indicator_tick(), self.ui.INDICATOR_TICK_S)
        return time.perf_counter() - started

    def run_marks(self) -> list[float]:
        """Los tics de la marca hasta que acaba (se retira); lo que tardó cada uno."""
        live = self.live
        took: list[float] = []
        for _ in range(MAX_TICKS):
            started = time.perf_counter()
            interval = live.mark_tick()
            took.append(time.perf_counter() - started)
            if interval is None:
                self.assertFalse(bpy.app.timers.is_registered(live.mark_tick))
                return took
            self.assertEqual(interval, live.MARK_TICK_S)
        self.fail("la marca en vivo no acaba")

    def tick(self) -> list[float]:
        """Un tic de los indicadores y los de la marca, sin escribir en el proyecto."""
        before = self.data.change_counter()
        self.indicators()
        took = self.run_marks()
        self.assertEqual(self.data.change_counter(), before)
        return took

    def refresh_state(self) -> tuple[bool, str]:
        """Si Refrescar (control 7) está resaltado y su descripción añadida, del proveedor de
        estado de las órdenes (``bl.ui.commands.command_state``)."""
        state = self.commands.command_state(bpy.context, self.ui.REFRESH)
        return (False, "") if state is None else (state.highlight, state.note)

    def assertPending(self, count: int, note: str) -> None:
        self.assertEqual(self.live.pending_count(), count)
        self.assertEqual(self.refresh_state(), (count > 0, note))

    # --- Pruebas --------------------------------------------------------------------------------

    def test_marks_follow_the_project(self) -> None:
        """RF-010-02 (T08; plan A3, D-10, D-11): tras cada cambio del proyecto, un tic de los
        indicadores y los de la marca ponen al día, sin volver a cargar nada ni escribir en el
        proyecto, el nombre, el estado y «al día» de los objetos y de la colección de cada
        dato: recalcular una rejilla, «[VIGENTE · NO AL DÍA]» (las demás, igual); el parámetro
        que leyó otra, «OBSOLETO» sin «NO AL DÍA»; sustituir una entrada, lo importado de ella,
        «NO AL DÍA»; descartar otra, lo suyo, «[SIN RESPALDO]», sin borrarlo. Hasta el tic, como
        estaba. Refrescar (control 7), resaltado con cuántos no están al día en su descripción
        mientras haya alguno, y no después: volver a cargar o descargar lo que no lo estaba
        pide también la marca. Los objetos del usuario y «99 Trabajo», con su nombre; los
        mismos objetos y mallas. Al cerrar el proyecto, nada que resaltar."""
        data, views = self.data, self.views
        fuente = data.import_grid("MDT Fuente")
        descarte = data.import_grid("MDT Descarte")
        data.load(bpy.context, *data.names, fuente.uid, descarte.uid)
        work, users = vf.user_objects(bpy.data, bpy.context.scene)
        before_users = [(obj.name, marks(obj)) for obj in users]
        before_work = (work.name, sorted(obj.name for obj in work.objects))
        grids = [data.record(name) for name in data.names]
        objects = {uid: obj.as_pointer() for uid, (obj,) in vf.loaded(bpy.data).items()}
        meshes = sorted(mesh.name for mesh in bpy.data.meshes)

        self.tick()  # la primera lectura: todo al día, nada cambia
        expected = self.shown()
        self.assertEqual(expected[grids[1].uid],
                         ("MDT rejilla_02 [VIGENTE]", "MDT rejilla_02 [VIGENTE]", "CURRENT",
                          "CURRENT", False))
        self.assertPending(0, "")

        def changed(change: Callable[[], Any], uid: str, wanted: tuple[Any, ...],
                    count: int, note: str) -> None:
            change()
            self.assertEqual(self.shown(), expected)  # hasta el tic, como estaba
            self.tick()
            expected[uid] = wanted
            self.assertEqual(self.shown(), expected)
            self.assertPending(count, note)

        with self.subTest(cambio="recalcular"):
            changed(lambda: data.recompute(data.names[1]), grids[1].uid,
                    ("MDT rejilla_02 [VIGENTE · NO AL DÍA]",
                     "MDT rejilla_02 [VIGENTE · NO AL DÍA]", "OUTDATED", "CURRENT", False),
                    1, "1 dato de la vista no está al día")
            self.assertEqual(self.only(grids[1].uid).geoblender.content_sha256,
                             grids[1].content_sha256)  # lo que se cargó
        with self.subTest(cambio="parámetro"):
            changed(lambda: self.assertEqual(data.make_stale(), (data.names[0],)),
                    grids[0].uid,
                    ("MDT rejilla_01 [VIGENTE · OBSOLETO]",
                     "MDT rejilla_01 [VIGENTE · OBSOLETO]", "CURRENT", "CURRENT", True),
                    1, "1 dato de la vista no está al día")
        with self.subTest(cambio="sustituir"):
            name = f"MDT de origen {self.short(fuente)} [VIGENTE · NO AL DÍA]"
            changed(lambda: data.substitute("MDT Fuente"), fuente.uid,
                    (name, name, "OUTDATED", "CURRENT", False),
                    2, "2 datos de la vista no están al día")
        with self.subTest(cambio="descartar"):
            name = f"MDT de origen {self.short(descarte)} [SIN RESPALDO]"
            changed(lambda: data.discard("MDT Descarte"), descarte.uid,
                    (name, name, "UNBACKED", "CURRENT", False),
                    2, "2 datos de la vista no están al día")

        # Nada borrado ni vuelto a cargar; lo del usuario, como estaba.
        self.assertEqual({uid: obj.as_pointer() for uid, (obj,) in vf.loaded(bpy.data).items()},
                         objects)
        self.assertEqual(sorted(mesh.name for mesh in bpy.data.meshes), meshes)
        self.assertEqual([(obj.name, marks(obj)) for obj in users], before_users)
        self.assertEqual((work.name, sorted(obj.name for obj in work.objects)), before_work)
        # Otro tic sin cambios en el proyecto no lo lee ni pide la marca.
        self.indicators()
        self.assertFalse(bpy.app.timers.is_registered(self.live.mark_tick))
        self.assertEqual(self.shown(), expected)

        # En inglés, la descripción de Refrescar en inglés.
        self.i18n.set_language("en")
        self.assertPending(2, "2 data items in the view are not up to date")
        self.i18n.set_language("es")

        # Volver a cargar la rejilla y descargar lo sustituido: nada que no esté al día.
        counter = data.change_counter()
        data.load(bpy.context, grids[1].uid)
        self.assertTrue(bpy.app.timers.is_registered(self.live.mark_tick))
        self.run_marks()
        expected[grids[1].uid] = ("MDT rejilla_02 [VIGENTE]", "MDT rejilla_02 [VIGENTE]",
                                  "CURRENT", "CURRENT", False)
        self.assertEqual(self.shown(), expected)
        self.assertPending(1, "1 dato de la vista no está al día")
        self.assertEqual(views.unload_datasets([fuente.uid]), 1)
        self.assertTrue(bpy.app.timers.is_registered(self.live.mark_tick))
        self.run_marks()
        del expected[fuente.uid]
        self.assertEqual(self.shown(), expected)
        self.assertPending(0, "")
        self.assertEqual(data.change_counter(), counter)

        # Otra vez algo que no está al día, y se cierra el proyecto: nada que resaltar.
        data.recompute(data.names[2])
        self.tick()
        self.assertPending(1, "1 dato de la vista no está al día")
        data.close()
        self.assertPending(0, "")
        self.assertFalse(bpy.app.timers.is_registered(self.live.mark_tick))

    def test_undo_and_redo(self) -> None:
        """RF-010-02 (T08; plan A3): deshacer (Ctrl+Z) hasta antes de volver a cargar una
        rejilla recalculada devuelve sus objetos a la carga anterior, y la marca, pedida tras
        ``undo_post``, la deja «NO AL DÍA» (con Refrescar resaltado); rehacer, al día. Nada se
        escribe en el proyecto."""
        data = self.data
        data.load(bpy.context)
        grid = data.record(data.names[1])
        self.tick()
        bpy.ops.ed.undo_push(message="rejillas cargadas")
        recomputed = data.recompute(grid.uid)
        self.tick()
        self.assertEqual(self.only(grid.uid).name, "MDT rejilla_02 [VIGENTE · NO AL DÍA]")
        data.load(bpy.context, grid.uid)
        self.run_marks()
        bpy.ops.ed.undo_push(message="rejilla vuelta a cargar")
        self.assertEqual(self.only(grid.uid).name, "MDT rejilla_02 [VIGENTE]")
        self.assertPending(0, "")
        counter = data.change_counter()

        bpy.ops.ed.undo()
        obj = self.only(grid.uid)
        self.assertEqual((obj.name, obj.geoblender.content_sha256),
                         ("MDT rejilla_02 [VIGENTE]", grid.content_sha256))
        self.assertTrue(bpy.app.timers.is_registered(self.live.mark_tick))
        self.run_marks()
        obj = self.only(grid.uid)
        self.assertEqual((obj.name, obj.geoblender.view_state, self.collection_of(grid.uid).name),
                         ("MDT rejilla_02 [VIGENTE · NO AL DÍA]", "OUTDATED",
                          "MDT rejilla_02 [VIGENTE · NO AL DÍA]"))
        self.assertPending(1, "1 dato de la vista no está al día")

        bpy.ops.ed.redo()
        self.assertTrue(bpy.app.timers.is_registered(self.live.mark_tick))
        self.run_marks()
        obj = self.only(grid.uid)
        self.assertEqual((obj.name, obj.geoblender.view_state, obj.geoblender.content_sha256),
                         ("MDT rejilla_02 [VIGENTE]", "CURRENT", recomputed.content_sha256))
        self.assertPending(0, "")
        self.assertEqual(data.change_counter(), counter)

    def test_opening_a_view_of_the_open_project(self) -> None:
        """RF-010-02 (T08; plan A3): abrir un ``.blend`` del proyecto abierto pide la marca
        (``load_post``): lo que cambió en el proyecto desde que se guardó queda «NO AL DÍA»,
        sin volver a cargarlo ni escribir en el proyecto."""
        data = self.data
        data.load(bpy.context)
        self.tick()
        view = self.folder / "vista.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(view))
        grid = data.record(data.names[2])
        data.recompute(grid.uid)
        counter = data.change_counter()
        blender_ext.load_file(view)  # sin las suscripciones de los complementos de Blender
        self.assertTrue(bpy.app.timers.is_registered(self.live.mark_tick))
        self.run_marks()
        obj = self.only(grid.uid)
        self.assertEqual((obj.name, obj.geoblender.view_state, obj.geoblender.content_sha256),
                         ("MDT rejilla_03 [VIGENTE · NO AL DÍA]", "OUTDATED",
                          grid.content_sha256))
        self.assertPending(1, "1 dato de la vista no está al día")
        self.assertEqual(data.change_counter(), counter)

    def test_marks_in_batches(self) -> None:
        """RF-010-02 (T08; plan A3, D-12): la marca lee el proyecto una vez por petición y
        aplica por tandas: con presupuesto 0, un dato por tic (el temporizador sigue cada
        ``MARK_TICK_S``) hasta acabar, y se retira; una petición a mitad vuelve a leer y sigue
        con lo que dice el proyecto entonces."""
        data, live = self.data, self.live
        data.load(bpy.context)
        self.tick()
        for name in data.names:
            data.recompute(name)
        reads: list[int] = []
        state = vf.extension("core.views.state")
        original = state.view_states

        def counted(*args: Any, **kwargs: Any) -> Any:
            reads.append(len(args[1]))
            return original(*args, **kwargs)

        outdated = "[VIGENTE · NO AL DÍA]"
        with mock.patch.object(live, "MARK_BUDGET_S", 0.0), \
                mock.patch.object(state, "view_states", side_effect=counted):
            self.indicators()
            done = []
            for _ in data.names:
                interval = live.mark_tick()
                done.append(sum(outdated in obj.name for obj in bpy.data.objects))
                if len(done) < len(data.names):
                    self.assertEqual(interval, live.MARK_TICK_S)
            self.assertIsNone(interval)
            self.assertEqual(done, [1, 2, 3])
            self.assertEqual(reads, [3])

            # Una petición a mitad: vuelve a leer y sigue.
            data.load(bpy.context, *data.names)  # al día: la carga pide la marca
            self.assertEqual(live.mark_tick(), live.MARK_TICK_S)
            self.assertEqual(reads, [3, 3])
            data.recompute(data.names[0])
            self.indicators()
            self.run_marks()
            self.assertEqual(reads, [3, 3, 3])
        self.assertEqual(sum(outdated in obj.name for obj in bpy.data.objects), 1)
        self.assertPending(1, "1 dato de la vista no está al día")

    def test_200_changed_at_once(self) -> None:
        """RNF-010-03, RF-010-02 (T08; plan A3, D-12): con 200 datos cargados que quedan
        obsoletos a la vez (el parámetro que leen todos), cada llamada de la marca tarda
        ≤ 20 ms (la menor de varias, ``least_of``: con la máquina ocupada, en un momento
        tranquilo) y los 200 quedan «[VIGENTE · OBSOLETO]» en ≤ 1 s tras el cambio (el tic de
        los indicadores, lo que tarda la marca y sus intervalos). Nada se escribe en el
        proyecto."""
        # Las 200, de una operación que lee el parámetro (0,9 s en vez de 2,2 s).
        self.data = data = vf.ViewsProject(temp_folder(self, "gb-v010m-"), grids=200,
                                           one_operation=True)
        data.attach()
        self.addCleanup(data.close)
        views, live = self.views, self.live
        state = vf.extension("core.views.state")
        data.load(bpy.context)
        self.tick()
        registry = vf.extension("core.datasets.registry")
        with data.project.read() as conn:
            records = [registry.get(conn, name) for name in data.names]
        groups = views.loaded_items(data.project.uid)
        self.assertEqual(len(groups), 200)
        current = {record.uid: state.ItemView(record.uid, state.ItemState.CURRENT, record,
                                              False, None) for record in records}
        wanted = {record.uid: f"MDT {self.short(record)} [VIGENTE · OBSOLETO]"
                  for record in records}
        self.assertEqual(len(data.make_stale()), 200)
        latencies: list[float] = []
        first = [True]

        def measure() -> float:
            if first[0]:
                first[0] = False
                indicators = self.indicators()  # el cambio, leído por los indicadores
            else:  # la escena como antes del cambio (como la deja Ctrl+Z) y otra petición
                views.show_view_state(groups, current)
                indicators = 0.0
                live.request(data.project)
            took = self.run_marks()
            self.assertEqual({uid: obj.name for uid, (obj,) in groups.items()}, wanted)
            latencies.append(self.ui.INDICATOR_TICK_S + indicators + sum(took)
                             + live.MARK_TICK_S * (len(took) - 1))
            return max(took)

        counter = data.change_counter()
        longest = least_of(measure, MARK_CALL_BUDGET_S, attempts=2)
        print(f"\nRNF-010-03: marca en vivo de 200 datos, la llamada más larga "
              f"{1000 * longest:.1f} ms (≤ {1000 * MARK_CALL_BUDGET_S:.0f} ms); al día "
              f"{min(latencies):.2f} s tras el cambio (≤ {MARKED_BUDGET_S:.0f} s)")
        self.assertLessEqual(longest, MARK_CALL_BUDGET_S)
        self.assertLessEqual(min(latencies), MARKED_BUDGET_S)
        self.assertEqual(data.change_counter(), counter)
        self.assertPending(0, "")


class ViewsLiveRegistrationTest(unittest.TestCase):
    """La extensión deshabilitada al empezar y al terminar (``blender_ext.release``)."""

    def setUp(self) -> None:
        blender_ext.release()
        self.addCleanup(blender_ext.release)

    def test_register_and_unregister_leave_no_trace(self) -> None:
        """RF-010-02 (T08; plan A3, §2.1), principio 8: habilitar apunta los manejadores
        ``@persistent`` de la marca en ``load_post``, ``undo_post`` y ``redo_post``, la
        petición tras cada lectura de los indicadores de la procedencia y el proveedor de
        estado de las órdenes; una petición pone el temporizador de la marca; deshabilitar lo
        quita todo y deja la huella de Blender como al principio de la sesión de pruebas."""
        blender_ext.enable()
        live = vf.extension("bl.scene.live")
        ui = vf.extension("bl.ui.provenance")
        commands = vf.extension("bl.ui.commands")
        for name, function in live.HANDLERS:
            with self.subTest(manejador=name):
                self.assertIn(function, getattr(bpy.app.handlers, name))
                self.assertTrue(hasattr(function, "_bpy_persistent"))  # lo pone @persistent
        self.assertEqual(sorted(name for name, _function in live.HANDLERS),
                         sorted(LIVE_HANDLERS))
        self.assertIn(live.request, ui.change_listeners())
        self.assertIs(commands.state_provider(), ui.command_state)
        self.assertIsNone(commands.command_state(bpy.context, ui.REFRESH))
        self.assertEqual(live.pending_count(), 0)
        live.request(object())  # un proyecto cualquiera: solo se apunta
        self.assertTrue(bpy.app.timers.is_registered(live.mark_tick))

        blender_ext.disable()
        self.assertFalse(bpy.app.timers.is_registered(live.mark_tick))
        for name, function in live.HANDLERS:
            self.assertNotIn(function, getattr(bpy.app.handlers, name))
        self.assertNotIn(live.request, ui.change_listeners())
        after = blender_ext.state_fingerprint()
        baseline = blender_ext.session_baseline()
        if after != baseline:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(baseline, after)))


if __name__ == "__main__":
    unittest.main()
