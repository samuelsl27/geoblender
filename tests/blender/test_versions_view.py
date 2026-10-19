# SPDX-License-Identifier: GPL-3.0-or-later
"""Las colecciones de las versiones y el renombrado desde el Outliner (spec 009, T22; HU-009-1;
RF-009-30, RF-009-22; plan 009 §5.3.4, A11, D-35 y D-36).

Con un proyecto sintético nuevo (``core.project.create_project`` con los ajustes de
``tests.support.core_fixtures``), en la sesión, el límite de ``tests/data/core/provenance/`` y la
demostración de versiones (``tests.support.versions_demo``): el hueco (``demo.pit``) calculado en
una versión da sus datos de versión (``demo_pit_grid``…) y ``demo.digitize``, los del proyecto
(``demo_benches``…). Un cargador de la prueba («Puntos», un objeto vacío por dato) los lleva a la
vista. En ``blender -b`` no corren los temporizadores ni avisa ``bpy.msgbus`` (``docs/trampas.md``
§3): cada prueba hace a mano un tic de los indicadores de la procedencia y los de la marca en vivo
(como la 010) y llama a la función suscrita al nombre (``bl.scene.versions.on_name_changed``).

- **La colección de su versión** (RF-009-30): cargar un dato de V01 lo pone en «Versiones / V01 ·
  Definitiva [BORRADOR] r1» (``Collection.geoblender``: el uid de V01 y su estado) con el color de
  su estado (``COLOR_03``), con el código de su versión en su nombre («Puntos pit_grid · V01
  [VIGENTE]»: el mismo dato de V02 no choca con él); un dato del proyecto, en su rama («Datos
  base / Topografía»). Declarada
  VIGENTE, tras el tic de la marca, «[VIGENTE] r2» y ``COLOR_04``; superada, «[SUPERADO] r2», sin
  color y sin excluirla (D-35); sin volver a cargar ni mover nada (los mismos objetos y las mismas
  colecciones) ni escribir en el proyecto. También cuando el cambio lo hace otra sesión y Blender
  tiene el proyecto en solo lectura.
- **Renombrar desde el Outliner** (RF-009-22, D-36): la colección de V02 y el objeto o la colección
  de un dato del proyecto guardan el texto como su título (``title_changed``; sin el código ni el
  estado si se dejaron) y vuelve el nombre generado con él, sin cambiar su código, su identidad,
  su nombre en el proyecto ni ningún fichero; la marca y volver a cargar lo conservan. En solo
  lectura o con la versión no editable (SUPERADO), vuelve el nombre generado y un aviso dice por
  qué, sin escribir nada. Los objetos y colecciones del usuario, intactos.
- **Registro y desregistro sin rastro**: la suscripción al nombre de ``Object`` y ``Collection``
  (otra vez tras cargar un ``.blend``, ``load_post``); deshabilitada, ninguna.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import hashlib
import shutil
import unittest
from pathlib import Path
from typing import Any

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.provenance_demo import BENCHES_TABLE
from tests.support.repo import ROOT
from tests.support.trees import temp_folder
from tests.support.versions_demo import PIT_GRID, VersionsDemo

DATA = ROOT / "tests" / "data" / "core" / "provenance"
WRITTEN = ("project.gpkg", "project.gpkg-journal", "manifest.json")
"""Lo único de la carpeta del proyecto que puede cambiar al renombrar: la base, su diario y la
cabecera."""
REASON = "Alternativa de la prueba de la vista"
LOADER_PREFIX = "demo_"  # el cargador de la prueba para los datos de la demostración
LOADER_LABEL = "Points"  # su msgid («Puntos»)
VERSIONS = "Versiones"
TOPOGRAPHY = ["Datos base", "Topografía"]
GRID = "Puntos pit_grid · {code} [VIGENTE]"
"""El nombre generado de ``demo_pit_grid`` de una versión: con el código de su versión."""
BENCHES = "Puntos benches [VIGENTE]"
COLORS = {"BORRADOR": "COLOR_03", "VIGENTE": "COLOR_04", "SUPERADO": "NONE",
          "DESCARTADO": "COLOR_08"}
"""El color de la colección de cada estado (``paneles-contextuales.md`` §5.3; D-35)."""
NOT_KEPT = "No se ha guardado el nombre «{text}»: {reason}"
READ_ONLY = "Proyecto en solo lectura: "
NOT_EDITABLE = "V01 está en estado SUPERADO: cree una versión nueva a partir de ella"
MAX_TICKS = 400


def ext(name: str) -> Any:
    """El módulo ``name`` de la copia de la extensión que importó Blender."""
    return vf.extension(name)


def drain(steps: Any) -> Any:
    """Avanza unos pasos (``Progress``) hasta el final y devuelve el resultado del último."""
    last = None
    for step in steps:
        last = step
    return None if last is None else last.result


def files(root: Path) -> dict[str, object]:
    """Cada carpeta y cada fichero de la carpeta del proyecto, con su tamaño, su huella y su
    fecha (ns), salvo la base, su diario y la cabecera (:data:`WRITTEN`)."""
    found: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel in WRITTEN:
            continue
        if path.is_dir():
            found[rel] = "carpeta"
            continue
        stat = path.stat()
        found[rel] = (stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(),
                      stat.st_mtime_ns)
    return found


def load_empty(request: Any) -> Any:
    """El cargador de la prueba para los datos de la demostración: un objeto vacío."""
    obj = bpy.data.objects.new(request.name, None)
    return ext("bl.scene.views").ViewParts((obj,), None)


class VersionsViewTest(unittest.TestCase):
    """La extensión habilitada una vez; en cada prueba, su proyecto en la sesión."""

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
        if not blender_ext.is_enabled():  # tras la prueba del registro, que la deshabilita
            blender_ext.enable()
        self.sv = ext("bl.scene.versions")
        self.ps = ext("bl.scene.project_session")
        self.views = ext("bl.scene.views")
        self.live = ext("bl.scene.live")
        self.ui = ext("bl.ui.provenance")
        self.jobs_ops = ext("bl.ops.jobs")
        self.core = ext("core.project")
        self.store = ext("core.versions.store")
        self.read = ext("core.versions.read")
        self.i18n = ext("core.i18n")
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")
        self.folder = temp_folder(self, "gb-v9v-")
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(self.ps.close)

    # --- El proyecto ---------------------------------------------------------------------------

    def project(self) -> Any:
        """Un proyecto nuevo en escritura en la sesión, con el límite importado, la
        demostración de versiones registrada y su cargador de la prueba («Puntos»)."""
        parent = self.folder / "proyectos"
        parent.mkdir()
        project = self.core.create_project(
            parent, self.core.ProjectSettings(**settings_values()), self.ps.session(),
            self.ps.userdata()).project
        self.addCleanup(project.close)
        self.ps.attach(project)
        self.root = project.root
        self.demo = self.enterContext(VersionsDemo(module_name()).registered())
        sources = self.folder / "fuentes"
        sources.mkdir()
        source = sources / "Limites.gpkg"
        shutil.copyfile(DATA / "Limites_v1.gpkg", source)
        self.demo.import_boundary(project, source)
        self.views.register_loader(LOADER_PREFIX, "POINTS", LOADER_LABEL, load_empty)
        self.addCleanup(self.views.unregister_loader, LOADER_PREFIX)
        return project

    def write(self, project: Any, work: Any) -> Any:
        with project.write_transaction() as conn:
            return work(conn)

    def create(self, project: Any, feature: str, title: str) -> Any:
        """Una versión hecha como la haría su orden (sin la sesión)."""
        version, _revision = self.write(project, lambda conn: self.store.create_version(
            conn, project, feature=feature, title=title, reason=REASON))
        project.refresh_header()
        return version

    def declare_current(self, project: Any, version: Any) -> None:
        """Congela la revisión abierta de ``version`` y la declara VIGENTE (la que lo era pasa
        a SUPERADO), como lo harían sus órdenes, sin la sesión."""
        outcome = drain(ext("core.versions.freeze").freeze_steps(project, version.uid,
                                                                 reason="Entrega"))
        self.assertFalse(outcome.cancelled)
        self.write(project, lambda conn: self.store.set_status(conn, project, version.uid,
                                                               "VIGENTE", reason=REASON))
        project.refresh_header()

    def run_checks(self) -> None:
        """La comprobación de apertura de la sesión, a mano, hasta que se retira."""
        session = ext("bl.ops.core_provenance")
        for _ in range(MAX_TICKS):
            if session.check_tick() is None:
                self.ps.take_notices()
                return
        self.fail("la comprobación no termina")

    def record(self, project: Any, name: str, version: Any = None) -> Any:
        """El registro del dato vivo ``name`` (de ``version``, si se da)."""
        registry = ext("core.datasets.registry")
        with project.read() as conn:
            found = registry.get(conn, name, version_uid="" if version is None
                                 else version.uid)
        self.assertIsNotNone(found, name)
        return found

    def load(self, project: Any, *records: Any) -> None:
        outcome = self.views.load_datasets(bpy.context, project, [item.uid for item in records])
        self.assertEqual(outcome.errors, ())
        self.assertEqual(len(outcome.loaded), len(records))

    def counter(self, project: Any) -> int:
        return vf.change_counter(project)

    def titles(self, project: Any) -> dict[str, str]:
        """El código y el título de cada versión del proyecto."""
        with project.read() as conn:
            return {item.code: item.title for item in self.read.versions(conn)}

    def dataset_row(self, project: Any, uid: str) -> tuple[Any, ...]:
        """Lo que guarda el proyecto del dato ``uid``: nombre, ubicación, título y versión."""
        with project.read() as conn:
            return conn.execute("SELECT name, locator, title, version_uid FROM gb_dataset "
                                "WHERE uid = ?", (uid,)).fetchone()

    def title_events(self, project: Any) -> list[tuple[Any, ...]]:
        events = ext("core.project.events")
        with project.read() as conn:
            found = events.read_events(conn, events.EventKind.TITLE_CHANGED)
        return [(item.entity_kind, item.entity_uid, item.data["from"], item.data["to"])
                for item in found]

    # --- La vista ------------------------------------------------------------------------------

    def tick(self, project: Any) -> None:
        """Un tic de los indicadores (lee el proyecto si cambió y pide la marca) y los de la
        marca, hasta que acaba, sin escribir en el proyecto."""
        before = self.counter(project)
        self.assertEqual(self.ui.indicator_tick(), self.ui.INDICATOR_TICK_S)
        for _ in range(MAX_TICKS):
            interval = self.live.mark_tick()
            if interval is None:
                break
            self.assertEqual(interval, self.live.MARK_TICK_S)
        else:
            self.fail("la marca en vivo no acaba")
        self.assertEqual(self.counter(project), before)

    def keyed(self, key: str) -> bpy.types.Collection | None:
        return next((item for item in bpy.data.collections
                     if item.get(self.views.KEY_PROPERTY) == key), None)

    def version_collection(self, version: Any) -> bpy.types.Collection:
        found = self.keyed(f"{self.sv.VERSION_KEY}{version.uid}")
        self.assertIsNotNone(found, version.code)
        return found

    def dataset_collection(self, record: Any) -> bpy.types.Collection:
        found = self.keyed(f"{self.views.DATASET_KEY}{record.uid}")
        self.assertIsNotNone(found, record.name)
        return found

    def only(self, record: Any) -> bpy.types.Object:
        (found,) = vf.objects_of(bpy.data, record.uid)
        return found

    def path(self, record: Any) -> list[str]:
        """Las colecciones desde la raíz de la escena hasta la del dato ``record``."""
        return self.views.collection_path(self.dataset_collection(record))

    def shown(self, version: Any) -> tuple[Any, ...]:
        """Lo que enseña la colección de ``version``: su nombre, su color, su versión y su
        estado (``Collection.geoblender``) y si está excluida u oculta en la capa de vista."""
        collection = self.version_collection(version)
        layer = self.layer_of(collection)
        return (collection.name, collection.color_tag, collection.geoblender.version_id,
                collection.geoblender.status, layer.exclude, layer.hide_viewport,
                collection.hide_viewport)

    @staticmethod
    def layer_of(collection: bpy.types.Collection) -> Any:
        pending = [bpy.context.view_layer.layer_collection]
        while pending:
            current = pending.pop()
            if current.collection == collection:
                return current
            pending.extend(current.children)
        raise AssertionError(f"«{collection.name}» no está en la capa de vista")

    def pointers(self) -> dict[str, int]:
        """Cada objeto y cada colección de la escena, por su nombre de sesión (uno nuevo es que
        se volvió a cargar o a crear)."""
        return {**{f"o{obj.session_uid}": obj.as_pointer() for obj in bpy.data.objects},
                **{f"c{item.session_uid}": item.as_pointer() for item in bpy.data.collections}}

    def rename(self, item: bpy.types.ID, name: str) -> None:
        """Lo que hace la persona en el Outliner y lo que avisa ``bpy.msgbus`` (que en
        ``blender -b`` no avisa): el nombre nuevo y la función suscrita."""
        item.name = name
        self.sv.on_name_changed()

    def warnings(self, since: int) -> list[str]:
        """Los avisos que han ido al registro de Blender (``report_later``) desde el número
        ``since``."""
        return [text for kind, text in self.jobs_ops.sent_reports()[since:]
                if kind == "WARNING"]

    # --- Pruebas -------------------------------------------------------------------------------

    def test_collection_of_a_version_follows_its_state(self) -> None:
        """RF-009-30 (plan A11, D-35): cargar ``demo_pit_grid`` de V01 lo pone en «Versiones / V01
        · Definitiva [BORRADOR] r1», con el uid de V01, su estado y ``COLOR_03``; un dato del
        proyecto, en su rama. Declarada V01 VIGENTE (desde fuera de las órdenes, como en la 010),
        hasta el tic nada cambia; tras el de los indicadores y la marca, «V01 · Definitiva
        [VIGENTE] r2» y ``COLOR_04``; con V02 declarada VIGENTE, V01 «[SUPERADO] r2», sin color y
        sin excluirla ni ocultarla. Ni se vuelve a cargar ni se mueve nada (los mismos objetos y
        colecciones, en el mismo sitio), la marca no escribe en el proyecto y lo del usuario
        queda como estaba."""
        project = self.project()
        self.demo.digitize(project)
        v01 = self.create(project, "definitiva", "Definitiva")
        self.demo.pit(project, "V01")
        grid = self.record(project, PIT_GRID, v01)
        benches = self.record(project, BENCHES_TABLE)
        self.run_checks()
        self.load(project, grid, benches)
        work, users = vf.user_objects(bpy.data, bpy.context.scene)
        before_users = [(obj.name, obj.users_collection[0].name) for obj in users]
        self.tick(project)

        name = "V01 · Definitiva [BORRADOR] r1"
        self.assertEqual(self.path(grid), [VERSIONS, name, GRID.format(code="V01")])
        self.assertEqual(list(self.only(grid).users_collection), [self.dataset_collection(grid)])
        self.assertEqual(self.shown(v01), (name, "COLOR_03", v01.uid, "BORRADOR", False, False,
                                           False))
        self.assertEqual(self.path(benches), [*TOPOGRAPHY, BENCHES])
        self.assertEqual(self.dataset_collection(benches).geoblender.version_id, "")
        self.assertEqual(self.keyed(self.sv.VERSIONS_KEY).color_tag, "NONE")
        pointers = self.pointers()

        self.declare_current(project, v01)
        self.assertEqual(self.shown(v01)[:2], (name, "COLOR_03"))  # hasta el tic, como estaba
        self.tick(project)
        name = "V01 · Definitiva [VIGENTE] r2"
        self.assertEqual(self.shown(v01), (name, "COLOR_04", v01.uid, "VIGENTE", False, False,
                                           False))
        self.assertEqual(self.path(grid), [VERSIONS, name, GRID.format(code="V01")])

        v02 = self.create(project, "ampliacion", "Ampliación")
        self.declare_current(project, v02)  # V01 pasa a SUPERADO y su r2 se cierra
        self.tick(project)
        name = "V01 · Definitiva [SUPERADO] r2"
        self.assertEqual(self.shown(v01), (name, "NONE", v01.uid, "SUPERADO", False, False,
                                           False))
        self.assertEqual(self.path(grid), [VERSIONS, name, GRID.format(code="V01")])
        self.assertEqual(self.only(grid).name, GRID.format(code="V01"))
        self.assertEqual(self.pointers(), pointers)  # nada vuelto a cargar ni creado
        self.assertEqual([(obj.name, obj.users_collection[0].name) for obj in users],
                         before_users)
        self.assertEqual(work.name, vf.WORK_COLLECTION)

        # En inglés, tras la marca siguiente, sus nombres en inglés y el mismo color.
        self.i18n.set_language("en")
        self.live.request(project)
        self.tick(project)
        self.assertEqual(self.shown(v01)[:2], ("V01 · Definitiva [SUPERSEDED] r2", "NONE"))

    def test_renaming_in_the_outliner_keeps_the_title(self) -> None:
        """RF-009-22 (plan A11, D-36): renombrar la colección de V02 («V02 · Fase norte
        [BORRADOR] r1», con el código y el estado dejados) guarda «Fase norte» como su título
        (``title_changed``) y vuelve el nombre generado con él; otra vez, solo el título («Fase
        sur»). Renombrar el objeto de un dato del proyecto («Bancos de la corta») y la colección
        de un dato de V02 (dejando el tipo y el estado) guarda su título sin cambiar su nombre
        en el proyecto, su ubicación ni su identidad, y vuelve el nombre generado con él en el
        objeto y en la colección del dato. Ningún fichero cambia salvo la base, su diario y la
        cabecera; la marca siguiente y volver a cargar conservan los nombres con el título; lo
        del usuario se renombra como quiera, sin escribir nada."""
        project = self.project()
        self.demo.digitize(project)
        v01 = self.create(project, "definitiva", "Definitiva")
        v02 = self.create(project, "ampliacion", "Ampliación")
        self.demo.pit(project, "V02")
        grid = self.record(project, PIT_GRID, v02)
        benches = self.record(project, BENCHES_TABLE)
        self.run_checks()
        self.load(project, grid, benches)
        work, users = vf.user_objects(bpy.data, bpy.context.scene)
        self.tick(project)
        collection = self.version_collection(v02)
        self.assertEqual(collection.name, "V02 · Ampliación [BORRADOR] r1")
        before_files = files(self.root)
        grid_row, benches_row = (self.dataset_row(project, grid.uid),
                                 self.dataset_row(project, benches.uid))
        objects = (self.only(grid).as_pointer(), self.only(benches).as_pointer())

        # La colección de V02: el texto, sin el código ni el estado, como su título.
        self.rename(collection, "V02 · Fase norte [BORRADOR] r1")
        self.assertEqual(self.titles(project), {"V01": "Definitiva", "V02": "Fase norte"})
        self.assertEqual(collection.name, "V02 · Fase norte [BORRADOR] r1")
        self.assertEqual(self.version_collection(v02), collection)
        self.assertEqual(collection.geoblender.version_id, v02.uid)
        self.rename(collection, "Fase sur")
        self.assertEqual(self.titles(project), {"V01": "Definitiva", "V02": "Fase sur"})
        self.assertEqual(collection.name, "V02 · Fase sur [BORRADOR] r1")
        self.assertEqual([(item.code, item.title) for item in self.sv.versions()],
                         [("V01", "Definitiva"), ("V02", "Fase sur")])
        self.assertEqual(self.path(grid), [VERSIONS, "V02 · Fase sur [BORRADOR] r1",
                                           GRID.format(code="V02")])

        # El objeto de un dato del proyecto y la colección de un dato de V02.
        self.rename(self.only(benches), "Bancos de la corta")
        titled = "Puntos Bancos de la corta [VIGENTE]"
        self.assertEqual((self.only(benches).name, self.dataset_collection(benches).name),
                         (titled, titled))
        self.rename(self.dataset_collection(grid), "Puntos Rejilla del hueco · V02 [VIGENTE]")
        grid_name = "Puntos Rejilla del hueco · V02 [VIGENTE]"
        self.assertEqual((self.only(grid).name, self.dataset_collection(grid).name),
                         (grid_name, grid_name))
        self.assertEqual(self.dataset_row(project, benches.uid),
                         (*benches_row[:2], "Bancos de la corta", ""))
        self.assertEqual(self.dataset_row(project, grid.uid),
                         (*grid_row[:2], "Rejilla del hueco", v02.uid))
        self.assertEqual(self.title_events(project), [
            ("version", v02.uid, "Ampliación", "Fase norte"),
            ("version", v02.uid, "Fase norte", "Fase sur"),
            ("dataset", benches.uid, None, "Bancos de la corta"),
            ("dataset", grid.uid, None, "Rejilla del hueco"),
        ])
        self.assertEqual((self.only(grid).as_pointer(), self.only(benches).as_pointer()),
                         objects)
        self.assertEqual(self.only(benches).geoblender.dataset_uid, benches.uid)
        self.assertEqual(files(self.root), before_files)  # ningún fichero movido ni renombrado

        # La marca siguiente lee los títulos: los nombres siguen; volver a cargar, también.
        self.tick(project)
        self.assertEqual((self.only(benches).name, self.only(grid).name, collection.name),
                         (titled, grid_name, "V02 · Fase sur [BORRADOR] r1"))
        self.load(project, benches)
        self.assertEqual((self.only(benches).name, self.dataset_collection(benches).name),
                         (titled, titled))
        self.assertEqual(self.path(benches), [*TOPOGRAPHY, titled])

        # Lo del usuario: se renombra como quiera, sin escribir nada.
        counter = self.counter(project)
        self.rename(users[0], "Croquis A")
        self.rename(work, "Mi trabajo")
        self.sv.on_name_changed()  # nada renombrado: nada que hacer
        self.assertEqual((users[0].name, work.name), ("Croquis A", "Mi trabajo"))
        self.assertEqual(self.counter(project), counter)
        self.assertEqual(self.titles(project), {"V01": "Definitiva", "V02": "Fase sur"})

    def test_renaming_refused_read_only_or_not_editable(self) -> None:
        """RF-009-22, RF-009-30 (plan A11, D-36; RF-009-04): con el proyecto en solo lectura en
        Blender (otra sesión tiene el cerrojo), esa otra sesión declara V02 VIGENTE y, tras el
        tic de la marca, la colección de V02 dice «[VIGENTE] r2» con ``COLOR_04`` y la de V01
        «[SUPERADO] r2» sin color. Renombrar la colección de V02 o el objeto de su dato vuelve
        el nombre generado y un aviso dice por qué («No se ha guardado el nombre «Fase norte»:
        Proyecto en solo lectura: …»). En escritura, renombrar la colección de V01 (SUPERADO) o
        su dato, lo mismo con «V01 está en estado SUPERADO: cree una versión nueva a partir de
        ella». Nada se escribe en el proyecto."""
        project = self.project()
        v01 = self.create(project, "definitiva", "Definitiva")
        v02 = self.create(project, "ampliacion", "Ampliación")
        self.demo.pit(project, "V01")
        self.demo.pit(project, "V02")
        grids = [self.record(project, PIT_GRID, version) for version in (v01, v02)]
        self.run_checks()
        self.load(project, *grids)
        self.declare_current(project, v01)
        self.tick(project)
        self.assertEqual(self.shown(v01)[:2], ("V01 · Definitiva [VIGENTE] r2", "COLOR_04"))
        self.assertEqual(self.shown(v02)[:2], ("V02 · Ampliación [BORRADOR] r1", "COLOR_03"))

        # Otra sesión toma el cerrojo; Blender abre el proyecto en solo lectura.
        self.ps.close()
        other_session = dataclasses.replace(self.ps.session(),
                                            session_uid=ext("core.ids").new_uid())
        other = self.core.open_project(self.root, other_session, self.ps.userdata()).project
        self.addCleanup(other.close)
        self.assertTrue(other.writable)
        reader = self.core.open_project(self.root, self.ps.session(), self.ps.userdata()).project
        self.addCleanup(reader.close)
        self.assertFalse(reader.writable)
        self.ps.attach(reader)
        self.run_checks()
        self.tick(reader)
        pointers = self.pointers()
        self.declare_current(other, v02)
        self.tick(reader)
        self.assertEqual(self.shown(v02), ("V02 · Ampliación [VIGENTE] r2", "COLOR_04", v02.uid,
                                           "VIGENTE", False, False, False))
        self.assertEqual(self.shown(v01), ("V01 · Definitiva [SUPERADO] r2", "NONE", v01.uid,
                                           "SUPERADO", False, False, False))
        self.assertEqual(self.pointers(), pointers)

        # En solo lectura, el nombre generado vuelve y se dice por qué.
        counter, before_files = self.counter(reader), files(self.root)
        sent = len(self.jobs_ops.sent_reports())
        self.rename(self.version_collection(v02), "Fase norte")
        self.assertEqual(self.version_collection(v02).name, "V02 · Ampliación [VIGENTE] r2")
        self.rename(self.only(grids[1]), "Rejilla norte")
        self.assertEqual(self.only(grids[1]).name, GRID.format(code="V02"))
        found = self.warnings(sent)
        self.assertEqual(len(found), 2, found)
        for text, typed in zip(found, ("Fase norte", "Rejilla norte"), strict=True):
            self.assertTrue(text.startswith(NOT_KEPT.format(text=typed, reason=READ_ONLY)),
                            text)
        self.assertEqual((self.counter(reader), files(self.root)), (counter, before_files))
        self.assertEqual(self.titles(reader), {"V01": "Definitiva", "V02": "Ampliación"})

        # En escritura, con V01 SUPERADO: no editable.
        other.close()
        self.ps.close()
        writer = self.core.open_project(self.root, self.ps.session(), self.ps.userdata()).project
        self.addCleanup(writer.close)
        self.assertTrue(writer.writable)
        self.ps.attach(writer)
        self.run_checks()
        self.tick(writer)
        counter, before_files = self.counter(writer), files(self.root)
        sent = len(self.jobs_ops.sent_reports())
        self.rename(self.version_collection(v01), "Otra")
        self.assertEqual(self.version_collection(v01).name, "V01 · Definitiva [SUPERADO] r2")
        self.rename(self.only(grids[0]), "Rejilla vieja")
        self.assertEqual(self.only(grids[0]).name, GRID.format(code="V01"))
        self.assertEqual(self.warnings(sent), [
            NOT_KEPT.format(text="Otra", reason=NOT_EDITABLE),
            NOT_KEPT.format(text="Rejilla vieja", reason=NOT_EDITABLE),
        ])
        self.assertEqual((self.counter(writer), files(self.root)), (counter, before_files))
        with writer.read() as conn:
            self.assertEqual(self.read.dataset_titles(conn, [grids[0].uid]),
                             {grids[0].uid: (v01.uid, "")})

    def test_register_and_unregister_leave_no_trace(self) -> None:
        """RF-009-22 (plan §2.1, D-36), principio 8: habilitada, la extensión está suscrita al
        nombre de ``Object`` y ``Collection`` (``bpy.msgbus``), también tras cargar un
        ``.blend`` (``load_post``, que Blender borra las suscripciones); deshabilitada, ninguna
        suscripción ni manejador suyo queda."""
        self.assertTrue(self.sv.is_subscribed())
        blender_ext.load_file()
        self.assertTrue(self.sv.is_subscribed())
        blender_ext.disable()
        self.assertFalse(self.sv.is_subscribed())
        self.assertNotIn(self.sv.on_load_post, bpy.app.handlers.load_post)
        blender_ext.enable()
        self.assertTrue(self.sv.is_subscribed())


if __name__ == "__main__":
    unittest.main()
