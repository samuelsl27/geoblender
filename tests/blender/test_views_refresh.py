# SPDX-License-Identifier: GPL-3.0-or-later
"""Refrescar las vistas desde el proyecto, F5 (spec 010, T11; RF-010-01; plan 010 §5.3.2,
§5.3.3, A2, D-9, D-11 y D-18).

Con el proyecto sintético de ``tests/support/views_fixtures.py`` (rejillas de 10 × 10 celdas y
las entradas que importa cada prueba), abierto en la sesión y cargado en la escena; en
``blender -b`` no corren los temporizadores (``docs/trampas.md`` §3): la marca en vivo se hace a
mano (un tic de los indicadores de la procedencia y los de la marca), y la orden, como desde la
interfaz (``in_steps``: el modal, con un evento del temporizador cada vez) o de una vez (desde un
guion):

- **solo lo que no está al día**: la rejilla recalculada se vuelve a cargar; la del parámetro
  cambiado solo cambia su marca de obsoleto, en el mismo último paso; la de la malla editada a
  mano, no (cuenta el hash, no la geometría); lo importado de una entrada sustituida, por su
  sucesor (sin «.001»); lo de una descartada, «[SIN RESPALDO]», sin borrarlo; los objetos del
  usuario y «99 Trabajo», intactos; el avance con el nombre de cada dato y, al terminar, cuántos
  se cargaron, cuántos están sin respaldo y cuántos al día; otra vez, «La vista está al día»;
- **otro GeoOrigin** (``core_set_work_window``): todo otra vez, y la marca de vista desfasada,
  quitada;
- **una vista abierta sin su proyecto** y después el proyecto (D-9): solo lo que cambió;
- **Esc a mitad**: la escena como estaba;
- **en solo lectura**, igual;
- **Ctrl+Z** (con ``ed.undo_push``, ``docs/trampas.md`` §4) hasta antes de la recarga: «NO AL
  DÍA» otra vez, y F5 la vuelve a hacer;
- **la orden real** (D-18): de la entrada «010», entregada, disponible y sin «Disponible en
  R-07»; resaltada en el control 7 mientras algo no está al día; sin proyecto, no;
- **con el MDT y los sondeos** (``RefreshDrillholesTest``, con las ayudas de
  ``test_dh_import_tabular``): recalcular el MDT y F5 vuelve a cargar solo el MDT; los objetos
  de los sondeos, los mismos (``session_uid``), con su superposición;
- **nada escrito en el proyecto** (el contador de cambios de su cabecera).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import DrillholeImportCase, _module
from tests.blender.test_views_state import marks, scene_state
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.fake_layout import FakeLayout
from tests.support.trees import temp_folder

REFRESH = "geoblender.core_refresh"
MAX_TICKS = 400
MAX_EVENTS = 500
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESC = SimpleNamespace(type="ESC", value="PRESS")
UP_TO_DATE = "La vista está al día"
CANCELLED = "Refrescar cancelado: la vista queda como estaba"
DH_FILES = ("bocas.csv", "desviaciones.csv")  # lo que necesitan las trazas y su vista


def ops() -> Any:
    return bpy.ops.geoblender


class RefreshCase(unittest.TestCase):
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
        self.ps = vf.extension("bl.scene.project_session")
        i18n = vf.extension("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")
        self.folder = temp_folder(self, "gb-v010r-")
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

    def sessions(self) -> dict[str, int]:
        """El ``session_uid`` del objeto de cada dato cargado (otro, si se volvió a cargar)."""
        return {uid: obj.session_uid for uid, (obj,) in vf.loaded(bpy.data).items()}

    def run_marks(self) -> None:
        """Los tics de la marca en vivo hasta que acaba."""
        for _ in range(MAX_TICKS):
            if self.live.mark_tick() is None:
                return
        self.fail("la marca en vivo no acaba")

    def tick(self) -> None:
        """Un tic de los indicadores de la procedencia y los de la marca."""
        self.assertEqual(self.ui.indicator_tick(), self.ui.INDICATOR_TICK_S)
        self.run_marks()

    def running(self) -> Any:
        """La orden Refrescar que está en marcha como modal (sin bucle de eventos, Blender no
        se entera de las que ya terminaron: la que aún tiene pasos)."""
        cls = getattr(bpy.types, "GEOBLENDER_OT_core_refresh")
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, "Refrescar no está en marcha como modal")
        return found[0]

    def refresh(self) -> tuple[set[str], Any]:
        """F5 como desde la interfaz: el modal, con un evento del temporizador cada vez hasta
        que acaba; su final y la orden (con su avance y lo que informó)."""
        self.assertEqual(ops().core_refresh("EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
        operator = self.running()
        for _ in range(MAX_EVENTS):
            state = operator.modal(bpy.context, TIMER)
            if state != {"RUNNING_MODAL"}:
                return state, operator
        self.fail("Refrescar no acaba")

    def assertUpToDate(self) -> None:
        """La marca en vivo, tras Refrescar: nada que no esté al día (control 7 apagado)."""
        self.run_marks()
        self.assertEqual(self.live.pending_count(), 0)


class ViewsRefreshTest(RefreshCase):

    def test_reloads_only_what_is_not_up_to_date(self) -> None:
        """RF-010-01 (T11; plan A2, D-11): F5, sin escribir en el proyecto, vuelve a cargar la
        rejilla recalculada (con su contenido de hoy, «al día»); pone al día sin volver a
        cargarla, en el mismo último paso, la del parámetro cambiado («OBSOLETO»); no toca la
        de la malla editada a mano (cuenta el hash, no la geometría); cambia lo importado de
        la entrada sustituida por su sucesor, con su nombre sin «.001» (lo sustituido, fuera
        con su colección); deja «[SIN RESPALDO]» lo de la descartada, sin borrarlo; y no toca
        los objetos del usuario ni «99 Trabajo». Avanza con el nombre de cada dato (nunca su
        uid), en milésimas que no bajan, y dice «Vista al día: 2 datos vueltos a cargar, 1 sin
        respaldo en el proyecto, 2 al día»; la marca en vivo, después, nada que no esté al
        día. Otra vez, de una vez (desde un guion), «La vista está al día» sin tocar nada."""
        data = self.data
        fuente = data.import_grid("MDT Fuente")
        descarte = data.import_grid("MDT Descarte")
        data.load(bpy.context, *data.names, fuente.uid, descarte.uid)
        work, users = vf.user_objects(bpy.data, bpy.context.scene)
        before_users = [(obj.name, marks(obj)) for obj in users]
        before_work = (work.name, sorted(obj.name for obj in work.objects))
        grids = [data.record(name) for name in data.names]
        self.tick()
        sessions = self.sessions()
        edited = self.only(grids[2].uid)
        edited.data.vertices[0].co.z += 5.0
        edited_z = edited.data.vertices[0].co.z

        recomputed = data.recompute(data.names[1])
        self.assertEqual(data.make_stale(), (data.names[0],))
        old, new = data.substitute("MDT Fuente")
        gone = data.discard("MDT Descarte")
        counter = data.change_counter()
        state, operator = self.refresh()
        self.assertEqual(state, {"FINISHED"})
        self.assertEqual(data.change_counter(), counter)
        self.assertEqual(operator.report_log[-1], "Vista al día: 2 datos vueltos a cargar, 1 sin "
                                                  "respaldo en el proyecto, 2 al día")
        progress = operator.progress_log
        uids = {grids[1].uid, new.uid, old.uid}
        self.assertFalse([entry for entry in progress if entry[4] in uids])
        self.assertIn(grids[1].name, [entry[4] for entry in progress])
        self.assertEqual([entry[2] for entry in progress], sorted(entry[2] for entry in progress))
        self.assertEqual(progress[-1][2:4], (1000, 1000))

        now = self.sessions()
        reloaded = self.only(grids[1].uid)
        self.assertNotEqual(now[grids[1].uid], sessions[grids[1].uid])
        self.assertEqual((reloaded.name, reloaded.geoblender.content_sha256,
                          reloaded.geoblender.view_state),
                         ("MDT rejilla_02 [VIGENTE]", recomputed.content_sha256, "CURRENT"))
        restated = self.only(grids[0].uid)
        self.assertEqual((now[grids[0].uid], restated.name, restated.geoblender.stale,
                          self.collection_of(grids[0].uid).name),
                         (sessions[grids[0].uid], "MDT rejilla_01 [VIGENTE · OBSOLETO]", True,
                          "MDT rejilla_01 [VIGENTE · OBSOLETO]"))
        kept = self.only(grids[2].uid)
        self.assertEqual((now[grids[2].uid], kept.name, kept.data.vertices[0].co.z),
                         (sessions[grids[2].uid], "MDT rejilla_03 [VIGENTE]", edited_z))
        self.assertEqual(vf.objects_of(bpy.data, old.uid), [])
        self.assertIsNone(self.collection_of(old.uid))
        name = f"MDT de origen {self.short(new)} [VIGENTE]"
        successor = self.only(new.uid)
        self.assertEqual((successor.name, successor.data.name, self.collection_of(new.uid).name,
                          successor.geoblender.content_sha256),
                         (name, name, name, new.content_sha256))
        unbacked = self.only(gone.uid)
        name = f"MDT de origen {self.short(descarte)} [SIN RESPALDO]"
        self.assertEqual((now[gone.uid], unbacked.name, unbacked.geoblender.view_state,
                          unbacked.geoblender.content_sha256),
                         (sessions[gone.uid], name, "UNBACKED", descarte.content_sha256))
        self.assertEqual([(obj.name, marks(obj)) for obj in users], before_users)
        self.assertEqual((work.name, sorted(obj.name for obj in work.objects)), before_work)
        self.assertFalse([obj.name for obj in bpy.data.objects if obj.name.endswith(".001")])
        self.assertUpToDate()

        # Otra vez, desde un guion (de una vez): nada que volver a cargar.
        scene = scene_state()
        self.assertEqual(ops().core_refresh("EXEC_DEFAULT"), {"CANCELLED"})
        self.assertEqual(scene_state(), scene)
        state, operator = self.refresh()
        self.assertEqual((state, operator.report_log[-1]), ({"CANCELLED"}, UP_TO_DATE))
        self.assertEqual(scene_state(), scene)
        self.assertEqual(data.change_counter(), counter)

    def test_another_geoorigin_reloads_everything(self) -> None:
        """RF-010-01, RF-002-27 (T11; plan A1, D-9): con otro GeoOrigin (la ventana de
        trabajo con otra Z0, ``core_set_work_window``) la vista queda desfasada y todo lo
        cargado «NO AL DÍA»; F5 lo vuelve a cargar todo con el GeoOrigin nuevo y quita la
        marca de vista desfasada de las escenas. F5 no escribe en el proyecto."""
        data = self.data
        data.load(bpy.context)
        self.tick()
        sessions = self.sessions()
        self.assertEqual(ops().core_set_work_window(
            "EXEC_DEFAULT", xmin=str(vf.WEST), ymin=str(vf.SOUTH), xmax=str(vf.WINDOW[2]),
            ymax=str(vf.WINDOW[3]), grid_step="1.0", z0=10, reason=vf.REASON), {"FINISHED"})
        origin = vf.extension("core.views.state").origin_text(data.project.origin)
        self.assertTrue(origin.endswith(" 10"))
        self.assertTrue(all(scene.geoblender.view_stale for scene in bpy.data.scenes))
        self.tick()
        self.assertEqual(self.live.pending_count(), len(data.names))
        counter = data.change_counter()
        self.assertEqual(ops().core_refresh("EXEC_DEFAULT"), {"FINISHED"})
        self.assertEqual(data.change_counter(), counter)
        now = self.sessions()
        for name in data.names:
            with self.subTest(dato=name):
                uid = data.record(name).uid
                obj = self.only(uid)
                self.assertNotEqual(now[uid], sessions[uid])
                self.assertEqual((obj.geoblender.origin, obj.geoblender.view_state),
                                 (origin, "CURRENT"))
        self.assertEqual([scene.geoblender.view_stale for scene in bpy.data.scenes],
                         [False] * len(bpy.data.scenes))
        self.assertUpToDate()

    def test_a_view_opened_before_its_project(self) -> None:
        """RF-010-01, RF-002-29 (T11; plan D-9): una vista guardada, abierta sin su proyecto
        (queda desfasada) y, después, el proyecto, con una rejilla recalculada entre medias: F5
        vuelve a cargar solo esa (las demás se cargaron con el GeoOrigin de hoy y su contenido
        es el de hoy: los mismos objetos) y quita la marca de vista desfasada. No escribe en el
        proyecto."""
        data, ps = self.data, self.ps
        data.load(bpy.context)
        self.tick()
        view = self.folder / "vista.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(view))
        grid = data.record(data.names[1])
        recomputed = data.recompute(grid.uid)
        data.close()
        blender_ext.load_file(view)
        self.assertIsNone(ps.current())
        self.assertTrue(all(scene.geoblender.view_stale for scene in bpy.data.scenes))
        sessions = self.sessions()
        opened = vf.extension("core.project").open_project(data.root, ps.session(),
                                                           ps.userdata()).project
        ps.attach(opened)
        ps.take_notices()
        data.project = opened
        counter = data.change_counter()
        self.assertEqual(ops().core_refresh("EXEC_DEFAULT"), {"FINISHED"})
        self.assertEqual(data.change_counter(), counter)
        now = self.sessions()
        self.assertEqual({uid for uid in now if now[uid] != sessions[uid]}, {grid.uid})
        self.assertEqual(self.only(grid.uid).geoblender.content_sha256, recomputed.content_sha256)
        self.assertEqual([scene.geoblender.view_stale for scene in bpy.data.scenes],
                         [False] * len(bpy.data.scenes))
        self.assertUpToDate()

    def test_esc_leaves_the_view_as_it_was(self) -> None:
        """RF-010-01 (T11; plan A2): Esc a mitad de Refrescar (dos rejillas recalculadas y
        una entrada sustituida, un paso por evento) cancela con «Refrescar cancelado: la vista
        queda como estaba»: la escena, igual que antes (objetos, nombres, marcas, mallas,
        colecciones y la marca de vista desfasada), también a mitad; nada escrito en el
        proyecto."""
        data = self.data
        fuente = data.import_grid("MDT Fuente")
        data.load(bpy.context, *data.names, fuente.uid)
        data.recompute(data.names[0])
        data.recompute(data.names[2])
        data.substitute("MDT Fuente")
        self.tick()
        before = scene_state()
        counter = data.change_counter()
        self.assertEqual(ops().core_refresh("EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
        operator = self.running()
        with mock.patch.object(type(operator), "STEP_BUDGET_S", 0.0):  # un paso por evento
            for _ in range(2):
                self.assertEqual(operator.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
        self.assertEqual(scene_state(), before)
        self.assertEqual(operator.modal(bpy.context, ESC), {"CANCELLED"})
        self.assertEqual(operator.report_log[-1], CANCELLED)
        self.assertEqual(scene_state(), before)
        self.assertEqual(data.change_counter(), counter)
        self.assertEqual(self.live.pending_count(), 3)

    def test_read_only(self) -> None:
        """RF-010-01 (T11; plan §5.3.3): con el proyecto abierto en solo lectura, F5 vuelve a
        cargar la rejilla recalculada antes (solo lee el proyecto)."""
        data, ps = self.data, self.ps
        data.load(bpy.context)
        grid = data.record(data.names[0])
        recomputed = data.recompute(grid.uid)
        data.close()
        opened = vf.extension("core.project").open_project(
            data.root, ps.session(), ps.userdata(), want_write=False).project
        ps.attach(opened)
        ps.take_notices()
        data.project = opened
        self.assertFalse(opened.writable)
        counter = data.change_counter()
        self.assertTrue(ops().core_refresh.poll())
        self.assertEqual(ops().core_refresh("EXEC_DEFAULT"), {"FINISHED"})
        obj = self.only(grid.uid)
        self.assertEqual((obj.name, obj.geoblender.content_sha256),
                         ("MDT rejilla_01 [VIGENTE]", recomputed.content_sha256))
        self.assertEqual(data.change_counter(), counter)

    def test_undo_and_refresh_again(self) -> None:
        """RF-010-01, RF-010-02 (T11; plan A2, A3): tras F5, deshacer (Ctrl+Z) hasta antes de
        la recarga devuelve la rejilla a su contenido anterior y la marca la deja «NO AL DÍA»;
        F5 la vuelve a cargar. Nada escrito en el proyecto."""
        data = self.data
        data.load(bpy.context)
        grid = data.record(data.names[1])
        self.tick()
        bpy.ops.ed.undo_push(message="rejillas cargadas")
        recomputed = data.recompute(grid.uid)
        self.tick()
        counter = data.change_counter()
        self.assertEqual(ops().core_refresh("EXEC_DEFAULT"), {"FINISHED"})
        bpy.ops.ed.undo_push(message="vista refrescada")
        self.run_marks()
        self.assertEqual(self.only(grid.uid).geoblender.content_sha256,
                         recomputed.content_sha256)

        bpy.ops.ed.undo()
        self.run_marks()
        obj = self.only(grid.uid)
        self.assertEqual((obj.name, obj.geoblender.content_sha256),
                         ("MDT rejilla_02 [VIGENTE · NO AL DÍA]", grid.content_sha256))
        self.assertEqual(self.live.pending_count(), 1)
        self.assertEqual(ops().core_refresh("EXEC_DEFAULT"), {"FINISHED"})
        obj = self.only(grid.uid)
        self.assertEqual((obj.name, obj.geoblender.content_sha256),
                         ("MDT rejilla_02 [VIGENTE]", recomputed.content_sha256))
        self.assertUpToDate()
        self.assertEqual(data.change_counter(), counter)

    def test_the_real_command(self) -> None:
        """RF-010-01, RF-010-02 (T11; plan §5.3.3, D-18): Refrescar es la orden real de la
        entrada «010», entregada: disponible, no provisional y sin «Disponible en R-07» en su
        descripción, con ``UNDO``; mientras algo no está al día, el control 7 la dibuja
        resaltada y activa; sin proyecto, no se puede (y dice por qué)."""
        commands = vf.extension("bl.ui.commands")
        cat = commands.catalog()
        self.assertEqual(cat.commands[REFRESH].entry, "010")
        self.assertTrue(cat.entries["010"].delivered)
        cls = commands.registered_class(REFRESH)
        self.assertFalse(commands.is_provisional(cls))
        self.assertTrue(commands.is_available(REFRESH))
        self.assertNotIn("R-07", cls.bl_description)
        self.assertIn("UNDO", cls.bl_options)

        data = self.data
        data.load(bpy.context)
        data.recompute(data.names[0])
        self.tick()
        level = vf.extension("core.catalog.width").Level
        layout = FakeLayout()
        bar = SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True),
                              screen=SimpleNamespace(show_fullscreen=False),
                              region=SimpleNamespace(width=1920), scene=bpy.context.scene)
        vf.extension("bl.ui.quick_access").draw_project(layout, bar, level.C)
        (refresh,) = [item for item in layout.items if item.target == REFRESH]
        self.assertEqual((refresh.enabled, refresh.alert), (True, True))

        self.assertTrue(ops().core_refresh.poll())
        data.close()
        self.assertFalse(ops().core_refresh.poll())


class RefreshDrillholesTest(DrillholeImportCase):
    """Con el MDT y los sondeos (E1): la extensión habilitada una vez para todas
    (``DrillholeImportCase``); el proyecto de la vista (``views_fixtures.ViewsProject``, una
    rejilla) abierto en la sesión, en el que se importan los sondeos de ``csv_basico`` (sus
    bocas están dentro de su ventana)."""

    def open(self) -> Any:
        self.data = vf.ViewsProject(self.tmp, grids=1)
        self.data.attach()
        self.addCleanup(self.data.close)
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                break
        self.ps.take_notices()
        self.project = self.data.project
        return self.project

    def setUp(self) -> None:
        super().setUp()
        self.live = _module("bl.scene.live")
        self.ui = _module("bl.ui.provenance")
        self.dh_view = _module("bl.scene.dh_view")
        i18n = _module("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")
        self.addCleanup(blender_ext.load_file)

    def tick(self) -> None:
        self.assertEqual(self.ui.indicator_tick(), self.ui.INDICATOR_TICK_S)
        for _ in range(MAX_TICKS):
            if self.live.mark_tick() is None:
                return
        self.fail("la marca en vivo no acaba")

    def test_refresh_reloads_the_dtm_and_not_the_drillholes(self) -> None:
        """RF-010-01 (T11; E1; plan A2): con el MDT y los sondeos cargados, recalcular el MDT
        lo deja «NO AL DÍA» y F5 vuelve a cargar solo el MDT, con su contenido de hoy: los
        objetos de los sondeos son los mismos (``session_uid``), con su nombre y su
        superposición, y no se pone nada en la cola de los sondeos. Nada escrito en el
        proyecto; después, nada que no esté al día."""
        data, ops_dh = self.data, self.dh_ops
        self.enterContext(mock.patch.object(ops_dh, "start_validate", lambda project, **_: None))
        self.import_all(DH_FILES)
        self.assertEqual(ops().dh_desurvey("EXEC_DEFAULT"), {"FINISHED"})
        self.finish()  # las trazas y, después, su vista
        data.load(bpy.context)
        self.tick()
        tubes = self.dh_view.loaded_objects(self.project)
        self.assertTrue(tubes)
        drillholes = {obj.session_uid: obj.name for obj in tubes}
        overlay = self.dh_view.overlay_of(tubes[0])
        self.assertIsNotNone(overlay)
        grid = data.record(data.names[0])
        recomputed = data.recompute(grid.uid)
        self.tick()
        (dtm,) = vf.objects_of(bpy.data, grid.uid)
        self.assertEqual(dtm.name, "MDT rejilla_01 [VIGENTE · NO AL DÍA]")
        before = dtm.session_uid
        self.assertEqual(self.live.pending_count(), 1)

        counter = data.change_counter()
        started = self.enterContext(mock.patch.object(ops_dh, "start_view",
                                                      wraps=ops_dh.start_view))
        self.assertEqual(ops().core_refresh("EXEC_DEFAULT"), {"FINISHED"})
        (dtm,) = vf.objects_of(bpy.data, grid.uid)
        self.assertNotEqual(dtm.session_uid, before)
        self.assertEqual((dtm.name, dtm.geoblender.content_sha256),
                         ("MDT rejilla_01 [VIGENTE]", recomputed.content_sha256))
        tubes = self.dh_view.loaded_objects(self.project)
        self.assertEqual({obj.session_uid: obj.name for obj in tubes}, drillholes)
        self.assertIs(self.dh_view.overlay_of(tubes[0]), overlay)
        self.assertEqual((started.call_count, ops_dh.pending_incorporations()), (0, []))
        self.tick()
        self.assertEqual(self.live.pending_count(), 0)
        self.assertEqual(data.change_counter(), counter)


if __name__ == "__main__":
    unittest.main()
