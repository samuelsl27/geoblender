# SPDX-License-Identifier: GPL-3.0-or-later
"""Las marcas en los objetos de la vista y en los pasos de carga (spec 010, T07; RF-010-01,
RF-010-02, RF-010-08; RF-006-29; plan 010 §5.2, §5.3.2, A1–A3, D-9 a D-12 y D-17).

Con el proyecto sintético de ``tests/support/views_fixtures.py`` (tres rejillas de 10 × 10
celdas y las entradas que importa cada prueba), abierto en la sesión:

- **los nombres generados**, en español y en inglés: «MDT rejilla_01 [VIGENTE · NO AL DÍA]»,
  «… [VIGENTE · OBSOLETO · NO AL DÍA]», «… [SIN RESPALDO]», «… [FALTA]»
  (``bl.scene.views.view_name``);
- **al cargar**, cada objeto anota el GeoOrigin con que se cargó («X0 Y0 Z0»,
  ``Object.geoblender.origin``), «al día» (``view_state``) y las cifras registradas de su dato
  como texto (``figures``: vacía si no tiene, como las rejillas; con las de su operación, su
  nombre, su valor con su unidad y su tipo);
- **sin volver a cargar** (``show_view_state``): tras recalcular una rejilla, «NO AL DÍA»; tras
  cambiar el parámetro que leyó otra, «OBSOLETO»; la de un fichero borrado, «FALTA»; lo
  importado de una entrada sustituida, «NO AL DÍA»; lo de una descartada, «SIN RESPALDO», sin
  borrar nada; las colecciones de cada dato con el mismo nombre; los objetos del usuario y «99
  Trabajo», como estaban; el ``LiveHook`` del cargador, solo en lo que está al día; con
  presupuesto, una tanda y lo que queda;
- **los pasos de carga** con un sustituido (``replaces``) y un «sin respaldo» (``unbacked``):
  en el último paso, el sucesor en lugar del sustituido (sin «.001»), lo descartado marcado y la
  marca de vista desfasada quitada (``clear_view_stale``); cerrarlos antes del último deja la
  escena igual (nombres, objetos, mallas, colecciones y marcas);
- ningún paso escribe en el proyecto (el contador de cambios de su cabecera);
- **registro y desregistro sin rastro**: ``Object.geoblender`` con ``view_state``, ``origin`` y
  ``figures`` (sin propiedades flotantes) y ``WindowManager.geoblender_view_panels``;
  desactivada, la huella de Blender como al principio de la sesión de pruebas.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import re
import time
import unittest
from collections.abc import Callable, Iterable
from types import MappingProxyType
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import fingerprint_diff
from tests.support.trees import temp_folder

GRID = "gis_dtm_"
SOURCE = "gis_src_"
OBJECT_PROPS_010 = ("view_state", "origin", "figures")
FIGURE_PROPS = ("uid", "key", "label", "value_text", "unit", "kind")
VIEW_STATES = ["CURRENT", "OUTDATED", "UNBACKED"]
ORIGIN_TEXT = re.compile(r"-?\d+ -?\d+ -?\d+")


def _views() -> Any:
    return vf.extension("bl.scene.views")


def marks(obj: bpy.types.Object) -> tuple[Any, ...]:
    """Lo que dice ``Object.geoblender`` de ``obj``, con sus cifras."""
    props = obj.geoblender
    figures = tuple(tuple(getattr(item, key) for key in FIGURE_PROPS) for item in props.figures)
    return (props.kind, props.dataset_uid, props.project_uid, props.content_sha256,
            props.status, props.stale, props.date, props.view_state, props.origin, figures)


def scene_state() -> tuple[Any, ...]:
    """La escena entera: cada objeto (nombre, sus datos, sus colecciones y sus marcas), las
    mallas, las colecciones (nombre y clave) y la marca de vista desfasada de cada escena."""
    objects = sorted((obj.name, "" if obj.data is None else obj.data.name,
                      tuple(sorted(item.name for item in obj.users_collection)), marks(obj))
                     for obj in bpy.data.objects)
    meshes = sorted(mesh.name for mesh in bpy.data.meshes)
    collections = sorted((item.name, str(item.get(_views().KEY_PROPERTY, "")))
                         for item in bpy.data.collections)
    stale = [scene.geoblender.view_stale for scene in bpy.data.scenes]
    return objects, meshes, collections, stale


class ViewsStateCase(unittest.TestCase):
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
        self.views = _views()
        self.state = vf.extension("core.views.state")
        self.i18n = vf.extension("core.i18n")
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")
        self.data = vf.ViewsProject(temp_folder(self, "gb-v010s-"))
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

    def assertKeepsCounter(self, action: Callable[[], Any]) -> Any:
        """``action`` no escribe en el proyecto (el contador de cambios no cambia)."""
        before = self.data.change_counter()
        result = action()
        self.assertEqual(self.data.change_counter(), before)
        return result

    def run_steps(self, steps: Iterable[Any]) -> Any:
        """Todos los pasos de ``steps``; el ``LoadOutcome`` del último."""
        outcome = None
        for step in steps:
            if isinstance(step.result, self.views.LoadOutcome):
                outcome = step.result
        self.assertIsNotNone(outcome)
        return outcome

    def states(self) -> dict[str, Any]:
        """Lo que dice hoy el proyecto de lo cargado (``core.views.state.view_states``)."""
        groups = self.views.loaded_items(self.data.project.uid)
        items = [self.views.loaded_item(uid, objects) for uid, objects in groups.items()]
        return self.state.view_states(
            self.data.project, items, project_uid=self.data.project.uid,
            origin=self.data.project.origin,
            view_stale=bpy.context.scene.geoblender.view_stale)


class ViewsStateTest(ViewsStateCase):

    def test_names_in_spanish_and_english(self) -> None:
        """RF-010-02 (T07; plan §5.5, D-10): el nombre generado de un dato dice su estado,
        si está obsoleto y si no está al día, o que no tiene respaldo en el proyecto, en el
        idioma de la interfaz; nunca una cifra."""
        views = self.views
        name = self.data.names[0]
        record = self.data.record(name)
        loader = views.loader_for(name)
        missing = dataclasses.replace(
            record, status=vf.extension("core.datasets.model").DatasetStatus.MISSING)
        expected = {
            "es": ("MDT rejilla_01 [VIGENTE]", "MDT rejilla_01 [VIGENTE · OBSOLETO]",
                   "MDT rejilla_01 [VIGENTE · NO AL DÍA]",
                   "MDT rejilla_01 [VIGENTE · OBSOLETO · NO AL DÍA]",
                   "MDT rejilla_01 [SIN RESPALDO]", "MDT rejilla_01 [FALTA · NO AL DÍA]"),
            "en": ("DTM rejilla_01 [CURRENT]", "DTM rejilla_01 [CURRENT · STALE]",
                   "DTM rejilla_01 [CURRENT · NOT UP TO DATE]",
                   "DTM rejilla_01 [CURRENT · STALE · NOT UP TO DATE]",
                   "DTM rejilla_01 [UNBACKED]", "DTM rejilla_01 [MISSING · NOT UP TO DATE]"),
        }
        for language, texts in expected.items():
            with self.subTest(idioma=language):
                self.i18n.set_language(language)
                found = (views.view_name(loader, record, stale=False),
                         views.view_name(loader, record, stale=True),
                         views.view_name(loader, record, stale=False, outdated=True),
                         views.view_name(loader, record, stale=True, outdated=True),
                         views.view_name(loader, record, stale=True, outdated=True,
                                         unbacked=True),
                         views.view_name(loader, missing, stale=False, outdated=True))
                self.assertEqual(found, texts)
                self.assertFalse(any(char.isdigit() for text in found
                                     for char in text.replace("rejilla_01", "")))

    def test_origin_and_figures_after_loading(self) -> None:
        """RF-006-29, RF-010-01, RF-010-08 (T07; plan §5.2, D-9, D-17): al cargar, cada objeto
        anota el GeoOrigin con que se cargó («X0 Y0 Z0», en metros enteros), «al día» y las
        cifras registradas de su dato, que las rejillas no tienen (colección vacía); con las de
        su operación, cada una con su uid, su clave, su nombre y su ámbito, su valor con su
        unidad ya escrito en el idioma de la interfaz, su unidad y su tipo. Cargar no escribe
        en el proyecto."""
        data = self.data
        outcome = self.assertKeepsCounter(lambda: data.load(bpy.context))
        self.assertEqual((outcome.loaded, outcome.errors), (data.names, ()))
        origin = self.state.origin_text(data.project.origin)
        self.assertRegex(origin, ORIGIN_TEXT)
        for name in data.names:
            with self.subTest(dato=name):
                props = self.only(data.record(name).uid).geoblender
                self.assertEqual((props.view_state, props.origin, len(props.figures)),
                                 ("CURRENT", origin, 0))

        # Con cifras (las de la operación que escribió su contenido, sin marcas).
        card = vf.extension("core.views.card")
        kind = vf.extension("core.params.model").ParamKind.CALCULADO
        record = data.record(data.names[1])
        figure = vf.extension("core.provenance.figures").FigureRecord(
            "cifra-1", "prueba.volumen", "Volumen de la corta", 1_563_631.0, "m3", kind,
            record.operation_uid, None, None, MappingProxyType({"fase": 2}), "clave",
            "2026-10-17T00:00:00.000Z")
        asked: list[tuple[list[str], bool]] = []

        def figures(project: Any, uids: Iterable[str], *, marks: bool = True,
                    conn: Any = None) -> tuple[Any, ...]:
            wanted = list(uids)
            asked.append((wanted, marks))
            return tuple(card.DatasetFigures(data.record(uid),
                                             (figure,) if uid == record.uid else (),
                                             MappingProxyType({})) for uid in wanted)

        thin = self.i18n.THIN_SPACE
        for language, label, value in (
                ("es", "Volumen de la corta · 2", f"1{thin}563{thin}631 m³"),
                ("en", "Volumen de la corta · 2", "1,563,631 m³")):
            with self.subTest(idioma=language), \
                    mock.patch.object(card, "dataset_figures", side_effect=figures):
                self.i18n.set_language(language)
                asked.clear()
                data.load(bpy.context, record.uid)
                self.assertEqual(asked, [([record.uid], False)])
                props = self.only(record.uid).geoblender
                self.assertEqual([tuple(getattr(item, key) for key in FIGURE_PROPS)
                                  for item in props.figures],
                                 [("cifra-1", "prueba.volumen", label, value, "m3",
                                   "CALCULADO")])
                self.assertEqual(props.origin, origin)

    def test_show_view_state_marks_without_reloading(self) -> None:
        """RF-010-02, RF-010-01 (T07; plan A1, A3, D-10, D-11): con lo que dice hoy el proyecto
        (``core.views.state.view_states``), ``show_view_state`` pone al día, sin volver a
        cargar nada ni escribir en el proyecto, el estado, el obsoleto, «al día» y el nombre de
        cada objeto y de la colección de su dato: la rejilla recalculada, «NO AL DÍA» (con el
        hash con que se cargó); la del parámetro cambiado, «OBSOLETO»; la del fichero borrado,
        «FALTA»; lo importado de la entrada sustituida, «NO AL DÍA»; lo de la descartada, «SIN
        RESPALDO». Los objetos del usuario y «99 Trabajo», como estaban; las mallas y los
        objetos, los mismos. El ``LiveHook`` del cargador se aplica solo a lo que está al día,
        con lo que leyó (``live_reads``). Otra vez, no cambia nada."""
        data, views = self.data, self.views
        fuente = data.import_grid("MDT Fuente")
        descarte = data.import_grid("MDT Descarte")
        data.load(bpy.context, *data.names, fuente.uid, descarte.uid)
        work, users = vf.user_objects(bpy.data, bpy.context.scene)
        before_users = [(obj.name, marks(obj)) for obj in users]
        before_work = (work.name, sorted(obj.name for obj in work.objects))
        loaded = {uid: marks(obj) for uid, (obj,) in vf.loaded(bpy.data).items()}
        meshes = sorted(mesh.name for mesh in bpy.data.meshes)

        grids = [data.record(name) for name in data.names]
        data.recompute(data.names[1])
        self.assertEqual(data.make_stale(), (data.names[0],))
        data.delete_file(data.names[2])
        data.substitute("MDT Fuente")
        data.discard("MDT Descarte")

        applied: list[tuple[list[str], str, Any]] = []

        def apply(objects: Any, view: Any, found: Any) -> bool:
            applied.append(([obj.name for obj in objects], str(view.state), found))
            return False

        hook = views.LiveHook(read=lambda conn: "leído", apply=apply)
        views.extend_loader(GRID, live=hook)
        self.addCleanup(views.extend_loader, GRID)
        self.assertIs(views.loaders()[GRID].live, hook)

        def mark() -> tuple[bool, list[str]]:
            states = self.states()
            with data.project.read() as conn:
                live = views.live_reads(conn)
            self.assertEqual(live, {GRID: "leído"})
            return views.show_view_state(views.loaded_items(data.project.uid), states,
                                         live=live)

        changed, rest = self.assertKeepsCounter(mark)
        self.assertEqual((changed, rest), (True, []))
        expected = {
            grids[0].uid: ("MDT rejilla_01 [VIGENTE · OBSOLETO]", "CURRENT", "CURRENT", True),
            grids[1].uid: ("MDT rejilla_02 [VIGENTE · NO AL DÍA]", "OUTDATED", "CURRENT",
                           False),
            grids[2].uid: ("MDT rejilla_03 [FALTA]", "CURRENT", "MISSING", False),
            fuente.uid: (f"MDT de origen {self.short(fuente)} [VIGENTE · NO AL DÍA]",
                         "OUTDATED", "CURRENT", False),
            descarte.uid: (f"MDT de origen {self.short(descarte)} [SIN RESPALDO]",
                           "UNBACKED", "CURRENT", False),
        }
        for uid, (name, view_state, status, stale) in expected.items():
            with self.subTest(dato=name):
                obj = self.only(uid)
                props = obj.geoblender
                self.assertEqual((obj.name, props.view_state, props.status, props.stale),
                                 (name, view_state, status, stale))
                self.assertEqual(self.collection_of(uid).name, name)
                # Lo que se cargó no cambia: su dato, su hash, su GeoOrigin.
                self.assertEqual(marks(obj)[:4], loaded[uid][:4])
                self.assertEqual(marks(obj)[6:], (loaded[uid][6], view_state)
                                 + loaded[uid][8:])
        self.assertEqual(sorted(vf.loaded(bpy.data)), sorted(loaded))
        self.assertEqual(sorted(mesh.name for mesh in bpy.data.meshes), meshes)
        self.assertEqual([(obj.name, marks(obj)) for obj in users], before_users)
        self.assertEqual((work.name, sorted(obj.name for obj in work.objects)), before_work)
        self.assertEqual(applied, [(["MDT rejilla_01 [VIGENTE · OBSOLETO]"], "RESTATE",
                                    "leído")])

        # Al día: otra vez no cambia nada.
        applied.clear()
        scene = scene_state()
        self.assertEqual(self.assertKeepsCounter(mark), (False, []))
        self.assertEqual(scene_state(), scene)
        self.assertEqual(len(applied), 1)

    def test_show_view_state_within_budget(self) -> None:
        """RF-010-02 (T07; plan A3, D-12): con presupuesto, ``show_view_state`` pone al día
        datos hasta pasarlo (al menos uno) y devuelve los que quedan, que la siguiente llamada
        sigue; sin presupuesto, todos de una vez. ``show_state`` (005, T47) es su envoltorio
        para un dato."""
        data, views = self.data, self.views
        data.load(bpy.context)
        records = [data.record(name) for name in data.names]
        groups = views.loaded_items(data.project.uid)
        state = self.state.ItemState.OUTDATED
        states = {record.uid: self.state.ItemView(record.uid, state, record, False, None)
                  for record in records}
        outdated = {record.uid: f"MDT {self.short(record)} [VIGENTE · NO AL DÍA]"
                    for record in records}

        def marked() -> list[str]:
            return sorted(uid for uid in groups if self.only(uid).name == outdated[uid])

        changed, rest = views.show_view_state(groups, states, budget_s=0.0)
        self.assertTrue(changed)
        self.assertEqual(len(rest), 2)
        self.assertEqual(marked(), sorted(set(groups) - set(rest)))
        while rest:
            left = len(rest)
            changed, rest = views.show_view_state({uid: groups[uid] for uid in rest}, states,
                                                  budget_s=0.0)
            self.assertTrue(changed)
            self.assertEqual(len(rest), left - 1)
        self.assertEqual(marked(), sorted(groups))
        self.assertEqual(views.show_view_state(groups, states), (False, []))

        # Sin presupuesto, todos; y el envoltorio de la 005 con lo que dice el proyecto.
        current = {record.uid: self.state.ItemView(record.uid, self.state.ItemState.CURRENT,
                                                   record, False, None) for record in records}
        started = time.perf_counter()
        self.assertEqual(views.show_view_state(groups, current), (True, []))
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual([self.only(record.uid).name for record in records],
                         [f"MDT {self.short(record)} [VIGENTE]" for record in records])
        shown = vf.extension("core.provenance.view").dataset_view(data.project, records[0].uid)
        stale = type(shown)(shown.record, True, shown.date)
        obj = self.only(records[0].uid)
        loader = views.loader_for(records[0].name)
        self.assertTrue(views.show_state([obj], loader, stale))
        self.assertEqual((obj.name, obj.geoblender.stale, obj.geoblender.view_state),
                         ("MDT rejilla_01 [VIGENTE · OBSOLETO]", True, "CURRENT"))
        self.assertFalse(views.show_state([obj], loader, stale))

    def test_extend_loader(self) -> None:
        """RF-010-02, RF-010-03 (T07; plan §5.3.2, D-13): un cargador declara su marca en vivo
        (``LiveHook``) y lo que no se guarda en el ``.blend`` (``SessionParts``) con
        ``extend_loader``, sin cambiar su función; sin nada, no declara nada; un comienzo sin
        cargador es un error; quitar el cargador quita lo declarado."""
        views = self.views
        before = views.loaders()[GRID]
        hook = views.LiveHook(read=lambda conn: None, apply=lambda objects, view, found: False)
        parts = views.SessionParts(missing=lambda project, objects: True,
                                   rebuild=lambda project: True)
        self.addCleanup(views.extend_loader, GRID)
        views.extend_loader(GRID, live=hook, session_parts=parts)
        found = views.loaders()[GRID]
        self.assertEqual((found.prefix, found.kind, found.label), (before.prefix, before.kind,
                                                                    before.label))
        self.assertIs(found.load, before.load)
        self.assertEqual((found.live, found.session_parts), (hook, parts))
        self.assertIs(views.loader_for(self.data.names[0]), found)
        views.extend_loader(GRID)
        self.assertEqual((views.loaders()[GRID].live, views.loaders()[GRID].session_parts),
                         (None, None))
        with self.assertRaises(ValueError):
            views.extend_loader("gb_sin_cargador_", live=hook)
        with self.assertRaises(TypeError):
            views.extend_loader(GRID, live=apply_nothing)
        with self.assertRaises(TypeError):
            views.extend_loader(GRID, session_parts=hook)
        self.assertEqual(views.loaders()[GRID], before)  # sin cambios


def apply_nothing(*_args: Any) -> bool:
    return False


class LoadStepsTest(ViewsStateCase):

    def setUp(self) -> None:
        super().setUp()
        data = self.data
        self.fuente = data.import_grid("MDT Fuente")
        self.descarte = data.import_grid("MDT Descarte")
        data.load(bpy.context, data.names[0], self.fuente.uid, self.descarte.uid)
        self.work, self.users = vf.user_objects(bpy.data, bpy.context.scene)
        self.old, self.new = data.substitute("MDT Fuente")
        self.gone = data.discard("MDT Descarte")
        for scene in bpy.data.scenes:
            scene.geoblender.view_stale = True

    def steps(self) -> Any:
        return self.views.load_steps(
            bpy.context, self.data.project, [self.new.uid],
            replaces={self.new.uid: self.old.uid}, unbacked=[self.gone.uid],
            clear_view_stale=True)

    def test_replaced_and_unbacked_in_the_last_step(self) -> None:
        """RF-010-01 (T07; plan A2): los pasos de carga con un sustituido y un «sin respaldo»
        cargan en el último el sucesor en lugar de lo sustituido (con su nombre, sin «.001»,
        su GeoOrigin y «al día»; lo sustituido, fuera, con su colección), marcan «SIN
        RESPALDO» lo descartado sin borrarlo y quitan la marca de vista desfasada de las
        escenas; lo demás (la rejilla, los objetos del usuario y «99 Trabajo»), igual. Nada se
        escribe en el proyecto."""
        data = self.data
        grid = self.only(data.record(data.names[0]).uid)
        kept = (grid.name, marks(grid))
        users = [(obj.name, marks(obj)) for obj in self.users]
        outcome = self.assertKeepsCounter(lambda: self.run_steps(self.steps()))
        self.assertEqual((outcome.loaded, outcome.errors), ((self.new.name,), ()))

        name = f"MDT de origen {self.short(self.new)} [VIGENTE]"
        self.assertEqual(vf.objects_of(bpy.data, self.old.uid), [])
        self.assertIsNone(self.collection_of(self.old.uid))
        new = self.only(self.new.uid)
        self.assertEqual((new.name, new.data.name), (name, name))
        self.assertEqual((new.geoblender.content_sha256, new.geoblender.view_state,
                          new.geoblender.origin),
                         (self.new.content_sha256, "CURRENT",
                          self.state.origin_text(data.project.origin)))
        self.assertEqual(self.collection_of(self.new.uid).name, name)

        unbacked = f"MDT de origen {self.short(self.descarte)} [SIN RESPALDO]"
        gone = self.only(self.gone.uid)
        self.assertEqual((gone.name, gone.geoblender.view_state, gone.geoblender.content_sha256),
                         (unbacked, "UNBACKED", self.descarte.content_sha256))
        self.assertEqual(self.collection_of(self.gone.uid).name, unbacked)

        self.assertEqual((grid.name, marks(grid)), kept)
        self.assertEqual([(obj.name, marks(obj)) for obj in self.users], users)
        self.assertEqual([scene.geoblender.view_stale for scene in bpy.data.scenes],
                         [False] * len(bpy.data.scenes))
        self.assertFalse(any(obj.name.endswith(".001") for obj in bpy.data.objects))

    def test_closing_before_the_last_step_leaves_the_scene(self) -> None:
        """RF-010-01 (T07; plan A2): cerrar los pasos (Esc) en cualquiera antes del último deja
        la escena como estaba: los mismos objetos con sus nombres, sus datos, sus colecciones y
        sus marcas, las mismas mallas y colecciones y la marca de vista desfasada; y no escribe
        en el proyecto."""
        before = scene_state()
        counter = self.data.change_counter()
        closed = 0
        for taken in range(1, 50):
            steps = self.steps()
            last = False
            for _ in range(taken):
                last = isinstance(next(steps).result, self.views.LoadOutcome)
            if last:
                break
            steps.close()
            closed += 1
            with self.subTest(pasos=taken):
                self.assertEqual(scene_state(), before)
        else:
            self.fail("los pasos no terminan")
        self.assertGreaterEqual(closed, 1)
        self.assertNotEqual(scene_state(), before)  # el último sí cambia la escena
        self.assertEqual(self.data.change_counter(), counter)


class ViewsRegistrationTest(unittest.TestCase):
    """La extensión deshabilitada al empezar y al terminar (``blender_ext.release``)."""

    def setUp(self) -> None:
        blender_ext.release()
        self.addCleanup(blender_ext.release)

    def test_register_and_unregister_leave_no_trace(self) -> None:
        """RF-010-02, RF-010-08, RF-006-29 (T07; plan §5.2), principio 8: habilitar pone en
        ``Object.geoblender`` ``view_state`` (al día, no al día, sin respaldo; por defecto, al
        día), ``origin`` (texto) y ``figures`` (filas de texto ``GEOBLENDER_PG_core_figure``),
        ninguna flotante, y ``WindowManager.geoblender_view_panels``; deshabilitar lo quita
        todo, también lo que declararon los cargadores, y deja la huella de Blender como al
        principio de la sesión de pruebas."""
        blender_ext.enable()
        object_property = vf.extension("bl.props.core").OBJECT_PROPERTY
        wm_property = vf.extension("bl.props.views").WINDOW_MANAGER_PROPERTY
        rna = bpy.types.Object.bl_rna.properties[object_property].fixed_type.properties
        self.assertLessEqual(set(OBJECT_PROPS_010), set(rna.keys()))
        self.assertEqual([key for key in rna.keys() if rna[key].type == "FLOAT"], [])
        self.assertEqual(([item.identifier for item in rna["view_state"].enum_items],
                          rna["view_state"].default), (VIEW_STATES, "CURRENT"))
        self.assertEqual(rna["origin"].type, "STRING")
        figures = rna["figures"]
        self.assertEqual((figures.type, figures.fixed_type.identifier),
                         ("COLLECTION", "GEOBLENDER_PG_core_figure"))
        own = figures.fixed_type.properties
        self.assertEqual(sorted(key for key in own.keys() if key not in ("rna_type", "name")),
                         sorted(FIGURE_PROPS))
        self.assertEqual({own[key].type for key in FIGURE_PROPS}, {"STRING"})
        for prop in [rna[key] for key in OBJECT_PROPS_010] + [own[key] for key in FIGURE_PROPS]:
            with self.subTest(propiedad=prop.identifier):
                self.assertTrue(prop.name)
                self.assertNotIn("_", prop.name)
        # Se lee otra vez tras habilitarla (docs/trampas.md §4).
        panels = bpy.types.WindowManager.bl_rna.properties[wm_property]
        self.assertEqual((panels.type, panels.fixed_type.identifier),
                         ("POINTER", "GEOBLENDER_PG_core_view_panels"))
        self.assertIsNotNone(bpy.context.window_manager.geoblender_view_panels)
        views = _views()
        views.extend_loader(GRID, live=views.LiveHook(read=lambda conn: None,
                                                      apply=apply_nothing))

        blender_ext.disable()
        self.assertFalse(hasattr(bpy.types.Object, object_property))
        self.assertFalse(hasattr(bpy.types.WindowManager, wm_property))
        self.assertEqual(views.loaders(), {})
        after = blender_ext.state_fingerprint()
        baseline = blender_ext.session_baseline()
        if after != baseline:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(baseline, after)))


if __name__ == "__main__":
    unittest.main()
