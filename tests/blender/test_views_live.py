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
  proveedor de estado de las órdenes; desactivada, la huella de Blender como al principio;
- **al abrir el proyecto** (T10; RF-010-03; plan A4, D-13), con dos rejillas y los sondeos de
  ``csv_basico`` (``ViewsOpenTest``, con las ayudas de ``test_dh_import_tabular``): una vista
  guardada y una rejilla cambiada desde otra sesión (otro ``Project`` sobre la misma carpeta),
  abrir el proyecto no lee nada de la vista; tras el primer tic de los indicadores y la marca,
  la rejilla «NO AL DÍA», «1 dato de la vista no está al día: Refrescar (F5)» en el registro de
  Blender y en los avisos del proyecto (ninguno si todo está al día) y la superposición de los
  sondeos rehecha en su cola, sin volver a cargar las rejillas; lo mismo al abrir un ``.blend``
  del proyecto abierto; y abrir tarda lo mismo con y sin la vista (RNF-002-02).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import statistics
import time
import unittest
from collections.abc import Callable
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import DrillholeImportCase, _module
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
DH_FILES = ("bocas.csv", "desviaciones.csv")  # lo que necesitan las trazas y su vista
OPEN_BUDGET_S = 0.5
"""RNF-002-02: abrir el proyecto (sin migrar) en disco local."""
OPEN_SLACK_S = 0.05
"""Lo que puede tardar de más abrir con la vista que sin ella (la mediana de 5): nada que medir
en un PC tranquilo (abrir no lee la vista); con la máquina ocupada, se mide otra vez."""
OPENINGS = 5
ONE_OUTDATED = "1 dato de la vista no está al día: Refrescar (F5)"
NOT_RESTORED = ("La superposición de la vista de los sondeos no se ha rehecho: sus objetos no "
                "son los de la base y la representación de hoy; vuelva a cargarla (Cargar en la "
                "vista…)")


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


class ViewsOpenTest(DrillholeImportCase):
    """Al abrir el proyecto (T10): la extensión habilitada una vez para todas
    (``DrillholeImportCase``); cada prueba, con su proyecto de la vista
    (``views_fixtures.ViewsProject``, dos rejillas) abierto en la sesión, en el que se importan
    los sondeos de ``csv_basico`` (sus bocas están dentro de su ventana)."""

    def open(self) -> Any:
        """El proyecto de la vista con dos rejillas, abierto en la sesión con su comprobación
        de apertura hecha (lo que hace ``DrillholeImportCase.open`` con el suyo)."""
        self.data = vf.ViewsProject(self.tmp, grids=2)
        self.data.attach()
        self.addCleanup(self.data.close)
        self.check_opening()
        self.project = self.data.project
        return self.project

    def setUp(self) -> None:
        super().setUp()
        self.live = _module("bl.scene.live")
        self.ui = _module("bl.ui.provenance")
        self.views = _module("bl.scene.views")
        self.dh_view = _module("bl.scene.dh_view")
        i18n = _module("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")
        self.addCleanup(blender_ext.load_file)

    # --- Ayudas ---------------------------------------------------------------------------------

    def check_opening(self) -> None:
        """La comprobación de apertura de la 008, entera, y sus avisos fuera."""
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                break
        self.ps.take_notices()

    def reopen(self, *, session: Any = None) -> Any:
        """Abre otra vez el proyecto de la vista en la sesión de Blender (con ``session``, el
        de otra sesión, fuera de ella, en escritura); devuelve el ``Project``."""
        opened = self.core.open_project(self.data.root, session or self.ps.session(),
                                        self.ps.userdata()).project
        if session is None:
            self.ps.attach(opened)
            self.check_opening()
            self.project = opened
        self.data.project = opened
        return opened

    def first_tick(self) -> None:
        """El primer tic de los indicadores de la procedencia (lee el proyecto y pide la
        marca) y los de la marca, hasta que acaba (``live.mark_tick``)."""
        self.assertEqual(self.ui.indicator_tick(), self.ui.INDICATOR_TICK_S)
        self.run_marks()

    def run_marks(self) -> None:
        live = self.live
        for _ in range(MAX_TICKS):
            interval = live.mark_tick()
            if interval is None:
                self.assertFalse(bpy.app.timers.is_registered(live.mark_tick))
                return
            self.assertEqual(interval, live.MARK_TICK_S)
        self.fail("la marca en vivo no acaba")

    def shown(self) -> dict[str, tuple[Any, ...]]:
        """Lo que muestra cada objeto de un dato: su nombre, «al día» y el hash de su carga."""
        return {obj.name: (obj.geoblender.view_state, obj.geoblender.content_sha256)
                for obj in bpy.data.objects if obj.geoblender.dataset_uid}

    def grid_objects(self) -> dict[str, int]:
        """Los objetos de las rejillas (no se vuelven a cargar), por el uid de su dato."""
        uids = {self.data.record(name).uid for name in self.data.names}
        return {uid: obj.as_pointer() for uid, (obj,) in vf.loaded(bpy.data).items()
                if uid in uids}

    def tubes(self) -> Any:
        (found,) = self.dh_view.loaded_objects(self.project)
        return found

    def drillholes(self) -> dict[int, str]:
        """Los objetos de la vista de los sondeos (``session_uid`` → nombre): uno nuevo, con
        otro ``session_uid``, es que se volvió a cargar."""
        return {obj.session_uid: obj.name for obj in self.dh_view.loaded_objects(self.project)}

    def overlay(self) -> tuple[Any, ...]:
        """Lo que dibuja la superposición de los sondeos además de las etiquetas: las marcas,
        las leyendas y la representación con que se cargó."""
        found = self.dh_view.overlay_of(self.tubes())
        self.assertIsNotNone(found, "la vista de los sondeos sin superposición")
        return (found.marks, found.lithology, found.element, found.grade, found.display_key)

    def labels(self) -> list[tuple[Any, ...]]:
        """Las etiquetas de la superposición de los sondeos (``None`` si no la tienen)."""
        found = self.dh_view.overlay_of(self.tubes())
        self.assertIsNotNone(found, "la vista de los sondeos sin superposición")
        return [(item.text, item.xyz, item.bottom) for item in found.labels]

    def announced(self, since: int) -> list[str]:
        """Los avisos de lo que no está al día que llevó la marca al registro de Blender
        (``report_later``) desde el informe número ``since``, como aviso."""
        sent = self.jobs_ops.sent_reports()[since:]
        return [text for kind, text in sent
                if kind == "WARNING" and text.endswith(" al día: Refrescar (F5)")]

    def timed_open(self) -> float:
        """Lo que tarda abrir el proyecto en la sesión (abrirlo y dejarlo en ella, sin su
        comprobación de apertura, que va por pasos en su temporizador); después, lo cierra."""
        started = time.perf_counter()
        opened = self.core.open_project(self.data.root, self.ps.session(), self.ps.userdata())
        self.ps.attach(opened.project)
        took = time.perf_counter() - started
        self.ps.close()
        return took

    # --- La prueba ----------------------------------------------------------------------------

    def test_opening_the_project_of_a_saved_view(self) -> None:
        """RF-010-03, RNF-002-02 (T10; plan A4, D-2, D-13; T20, F-1 de la verificación): una
        vista guardada con las dos rejillas y los sondeos y, con el proyecto cerrado, la segunda
        rejilla recalculada desde otra sesión (otro ``Project`` sobre la misma carpeta). Al
        abrir el proyecto con la vista cargada no se lee nada de ella ni se pone nada en la cola
        de los sondeos; tras el primer tic de los indicadores y los de la marca (una lectura):
        la rejilla «[VIGENTE · NO AL DÍA]» con el contenido que se cargó (no se vuelve a cargar:
        los mismos objetos), la otra y los sondeos, al día; «1 dato de la vista no está al día:
        Refrescar (F5)» una vez, en el registro de Blender (``report_later``) y en los avisos
        del proyecto; de los sondeos, que están al día, solo su superposición, que no se guarda
        en el ``.blend``, rehecha en su cola (las mismas etiquetas, marcas y leyendas) **sin
        volver a cargarlos** (los mismos objetos, por su ``session_uid``; ni ``load_steps`` ni
        ``start_view``); nada escrito en el proyecto; las marcas siguientes no avisan ni rehacen
        nada. Ningún aviso si todo está al día. Lo mismo al abrir un ``.blend`` del proyecto
        abierto (``load_post``). Una vista cuyos sondeos muestran otro contenido que el de hoy:
        al abrir, «[VIGENTE · NO AL DÍA]», contados en el aviso, sin volver a cargarlos ni
        rehacer su superposición (nada en su cola: es lo de Refrescar); unos al día cuyos tubos
        no son los que crearía la carga de hoy, sin superposición (no sería la suya), con su
        aviso y sin volver a cargarlos; una recarga pedida mientras la superposición espera en
        su cola no se pierde. Abrir el proyecto con la vista tarda lo mismo que sin ella (la
        mediana de 5) y ≤ 0,5 s (RNF-002-02)."""
        data, ops, ps, live = self.data, self.dh_ops, self.ps, self.live
        state = _module("core.views.state")
        self.enterContext(mock.patch.object(ops, "start_validate", lambda project, **_: None))
        self.import_all(DH_FILES)
        self.assertEqual(bpy.ops.geoblender.dh_desurvey("EXEC_DEFAULT"), {"FINISHED"})
        self.finish()  # las trazas y, después, su vista
        data.load(bpy.context)
        grids = [data.record(name) for name in data.names]
        reports = len(self.jobs_ops.sent_reports())
        self.first_tick()  # la primera lectura tras abrir, todo al día: sin aviso
        current = {"MDT rejilla_01 [VIGENTE]": ("CURRENT", grids[0].content_sha256),
                   "MDT rejilla_02 [VIGENTE]": ("CURRENT", grids[1].content_sha256)}
        drillholes = {name: value for name, value in self.shown().items()
                      if name.startswith("Sondeos")}
        self.assertEqual(list(drillholes), ["Sondeos [VIGENTE]"])
        self.assertEqual(self.shown(), {**drillholes, **current})
        self.assertEqual(self.announced(reports), [])
        before, drawn = self.labels(), self.overlay()
        view = self.tmp / "vista.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(view))

        # Cerrado el proyecto, otra sesión recalcula la segunda rejilla.
        data.close()
        other = self.reopen(session=dataclasses.replace(
            ps.session(), session_uid=_module("core.ids").new_uid()))
        try:
            self.assertTrue(other.writable)
            changed = data.recompute(grids[1].uid)
        finally:
            other.close()
        self.assertNotEqual(changed.content_sha256, grids[1].content_sha256)

        # La vista, sin su proyecto; después, abrir el proyecto: nada se lee de la vista.
        blender_ext.load_file(view)
        self.assertIsNone(ps.current())
        objects = self.grid_objects()
        kept = self.drillholes()
        reads = self.enterContext(mock.patch.object(state, "view_states",
                                                    wraps=state.view_states))
        started = self.enterContext(mock.patch.object(ops, "start_view", wraps=ops.start_view))
        loads = self.enterContext(mock.patch.object(self.views, "load_steps",
                                                    wraps=self.views.load_steps))
        project = self.reopen()
        self.assertEqual((reads.call_count, started.call_count), (0, 0))
        self.assertEqual(ops.pending_incorporations(), [])
        self.assertFalse(bpy.app.timers.is_registered(live.mark_tick))
        self.assertEqual(self.shown(), {**drillholes, **current})

        # El primer tic: la rejilla marcada, el aviso y la superposición en su cola.
        counter = data.change_counter()
        reports = len(self.jobs_ops.sent_reports())
        ps.take_notices()
        self.first_tick()
        self.assertEqual(reads.call_count, 1)
        outdated = {"MDT rejilla_01 [VIGENTE]": current["MDT rejilla_01 [VIGENTE]"],
                    "MDT rejilla_02 [VIGENTE · NO AL DÍA]": ("OUTDATED",
                                                             grids[1].content_sha256)}
        self.assertEqual(self.shown(), {**drillholes, **outdated})
        self.assertEqual(self.grid_objects(), objects)  # no se vuelven a cargar
        self.assertEqual(self.announced(reports), [ONE_OUTDATED])
        self.assertEqual(ps.notices(), (ONE_OUTDATED,))
        self.assertEqual(ops.pending_incorporations(), [ops.OVERLAY_QUEUE])
        self.finish()  # la superposición de los sondeos, por su cola
        # RF-010-03 (T20): los sondeos, al día, no se vuelven a cargar: los mismos objetos.
        self.assertEqual(self.drillholes(), kept)
        self.assertEqual((started.call_count, loads.call_count), (0, 0))
        self.assertEqual((self.labels(), self.overlay()), (before, drawn))
        self.assertEqual(self.shown(), {**drillholes, **outdated})
        self.run_marks()  # ni otro aviso ni otra superposición
        self.assertEqual(self.announced(reports), [ONE_OUTDATED])
        self.assertEqual(ops.pending_incorporations(), [])
        self.assertEqual(data.change_counter(), counter)

        # Lo mismo al abrir un .blend del proyecto abierto.
        again = self.tmp / "vista-2.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(again))
        counter = data.change_counter()
        reports = len(self.jobs_ops.sent_reports())
        ps.take_notices()
        blender_ext.load_file(again)
        kept = self.drillholes()
        self.assertIs(ps.current(), project)
        self.assertTrue(bpy.app.timers.is_registered(live.mark_tick))
        self.run_marks()
        self.assertEqual(self.shown(), {**drillholes, **outdated})
        self.assertEqual(self.announced(reports), [ONE_OUTDATED])
        self.assertEqual(ps.notices(), (ONE_OUTDATED,))
        self.assertEqual(ops.pending_incorporations(), [ops.OVERLAY_QUEUE])
        self.finish()
        self.assertEqual(self.drillholes(), kept)
        self.assertEqual((self.labels(), self.overlay()), (before, drawn))
        self.run_marks()
        self.assertEqual(self.announced(reports), [ONE_OUTDATED])
        self.assertEqual((started.call_count, loads.call_count), (0, 0))
        self.assertEqual(data.change_counter(), counter)

        # Unos sondeos con otro contenido que el de hoy (el hash de otra carga, como si otra
        # sesión hubiera calculado otra vez las trazas): al abrir, marcados y contados, sin
        # volver a cargarlos ni rehacer su superposición (es lo de Refrescar, F5).
        for obj in self.dh_view.loaded_objects(project):
            obj.geoblender.content_sha256 = "0" * 64
        earlier = self.tmp / "vista-3.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(earlier))
        ps.close()
        blender_ext.load_file(earlier)
        kept = self.drillholes()
        reports = len(self.jobs_ops.sent_reports())
        project = self.reopen()
        counter = data.change_counter()
        self.first_tick()
        two = "2 datos de la vista no están al día: Refrescar (F5)"
        self.assertEqual(self.announced(reports), [two])
        self.assertEqual(self.shown(), {"Sondeos [VIGENTE · NO AL DÍA]": ("OUTDATED", "0" * 64),
                                        **outdated})
        self.assertEqual(ops.pending_incorporations(), [])
        self.assertEqual(list(self.drillholes()), list(kept))  # los mismos, ya marcados
        self.assertIsNone(self.dh_view.overlay_of(self.tubes()))
        self.assertEqual(live.pending_count(), 2)
        self.assertEqual((started.call_count, loads.call_count), (0, 0))
        self.assertEqual(data.change_counter(), counter)

        # Unos sondeos al día cuyos tubos no son los que crearía la carga de hoy (otra fila de
        # la base en cada curva): su superposición no se rehace (no sería la suya) y se dice,
        # sin volver a cargarlos.
        ps.close()
        blender_ext.load_file(again)
        mesh = _module("bl.scene.mesh")
        tubes = self.tubes()
        rows = mesh.attribute_values(tubes.data, self.dh_view.ROW)
        mesh.set_attribute(tubes.data, self.dh_view.ROW, "CURVE", "INT", rows + 1)
        kept = self.drillholes()
        self.reopen()
        counter = data.change_counter()
        ps.take_notices()
        self.first_tick()
        self.assertEqual(ops.pending_incorporations(), [ops.OVERLAY_QUEUE])
        self.finish()
        self.assertEqual(self.drillholes(), kept)
        self.assertIsNone(self.dh_view.overlay_of(self.tubes()))
        self.assertEqual(ps.notices(), (ONE_OUTDATED, NOT_RESTORED))
        self.assertEqual((started.call_count, loads.call_count), (0, 0))
        self.assertEqual(data.change_counter(), counter)
        # Una recarga pedida mientras la superposición espera (otra representación) no se
        # pierde; con ella en espera no se pone otra superposición, y la que esperaba, al
        # empezar, no hace nada: la trae la recarga (sin trabajos: la cola se vacía después).
        self.assertTrue(ops.start_overlay(project))
        self.assertTrue(ops.display_changed())
        self.assertFalse(ops.start_overlay(project))
        self.assertEqual(ops.pending_incorporations(), [ops.OVERLAY_QUEUE, ops.VIEW_QUEUE])
        ops.incorporation_tick()
        self.assertEqual(ops.pending_incorporations(), [ops.VIEW_QUEUE])
        ops.INCORPORATIONS.drop()
        self.assertEqual((started.call_count, loads.call_count), (1, 0))

        # RNF-002-02: abrir con la vista tarda lo mismo que sin ella.
        ps.close()
        counted = reads.call_count
        timings: list[tuple[float, float]] = []

        def extra() -> float:
            blender_ext.load_file(again)
            with_view = statistics.median(self.timed_open() for _ in range(OPENINGS))
            blender_ext.load_file()
            without = statistics.median(self.timed_open() for _ in range(OPENINGS))
            timings.append((with_view, without))
            return with_view - without

        added = least_of(extra, OPEN_SLACK_S, max_attempts=3)
        with_view, without = min(timings, key=lambda pair: pair[0] - pair[1])
        print(f"\nRNF-002-02: abrir el proyecto con la vista (dos rejillas y los sondeos), "
              f"mediana de {OPENINGS} {1000 * with_view:.1f} ms; sin ella "
              f"{1000 * without:.1f} ms (≤ {1000 * OPEN_BUDGET_S:.0f} ms)")
        self.assertEqual(reads.call_count, counted)  # ni una lectura al abrir
        self.assertLessEqual(added, OPEN_SLACK_S)
        self.assertLessEqual(with_view, OPEN_BUDGET_S)


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
