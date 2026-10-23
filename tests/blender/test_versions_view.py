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
  tiene el proyecto en solo lectura. El informe de Cargar en la vista… nombra lo de una versión
  con el código de su versión («demo_pit_grid · V01, demo_pit_grid · V02»; T32, del H2).
- **Renombrar desde el Outliner** (RF-009-22, D-36): la colección de V02 y el objeto o la colección
  de un dato del proyecto guardan el texto como su título (``title_changed``; sin el código ni el
  estado si se dejaron) y vuelve el nombre generado con él, sin cambiar su código, su identidad,
  su nombre en el proyecto ni ningún fichero; la marca y volver a cargar lo conservan. En solo
  lectura o con la versión no editable (SUPERADO), vuelve el nombre generado y un aviso dice por
  qué, sin escribir nada. Los objetos y colecciones del usuario, intactos.
- **Registro y desregistro sin rastro**: la suscripción al nombre de ``Object`` y ``Collection``
  (otra vez tras cargar un ``.blend``, ``load_post``); deshabilitada, ninguna.

N ▸ Proyecto ▸ **Inventario** y **Elemento activo** con versiones (spec 009, T25; HU-009-1;
RF-009-20, RF-009-30, RF-009-09; spec §7; plan A11), dibujados con un *layout* simulado:

- **el inventario** enseña una fila por versión («V01 · Definitiva», con el icono y el nombre de
  su estado) y por revisión («V01.r2 · en curso», «V02.r1 · congelada» con la marca «alterada»
  en alerta), cada dato con el código de su versión, y se filtra por versión (un enumerado con
  las versiones ya leídas: «Todas», «Sin versión» y cada una); una versión o una
  revisión no se carga ni tiene procedencia (con el motivo); al cambiar de proyecto, el filtro
  vuelve a «Todas»;
- **la ficha** de un dato de V01 VIGENTE con r2 abierta dice «Versión: V01 · Definitiva — en
  curso (r2) · vigente: r1», sus cifras «en curso (r2)» y las cifras vigentes de V01 (las de
  r1, D-9); la de V02, sin congelar, «en curso (r1)» y que aún no hay ninguna congelada; una
  superada, «cerrada (r2) · congelada: r1» y sus cifras congeladas; un dato del proyecto, como
  en la 010;
- **el estado que tenía al congelarse** (T37; RF-009-19, D-23): lo de una versión superada
  congelado obsoleto y aceptado lo dice en la ficha («Estado: VIGENTE · OBSOLETO AL
  CONGELARSE, ACEPTADO») y en el inventario, y sus cifras congeladas, «obsoleta al congelarse,
  aceptada»; lo «en curso» de una revisión abierta, el estado de hoy.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import hashlib
import shutil
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import assert_fits, at_scales
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import FakeLayout, Item, draw, operator_self
from tests.support.provenance_demo import BENCHES_TABLE
from tests.support.repo import ROOT
from tests.support.trees import temp_folder
from tests.support.versions_demo import (
    BENCH_HEIGHT,
    PIT_BENCHES,
    PIT_GRID,
    PIT_MESH,
    VersionsDemo,
)

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
# Inventario y Elemento activo (T25).
INVENTORY_PANEL = "GEOBLENDER_PT_core_project_inventory"
ACTIVE_ITEM_PANEL = "GEOBLENDER_PT_core_active_item"
LOAD = "geoblender.core_load_into_view"
UNLOAD = "geoblender.core_unload_from_view"
SHOW_LINEAGE = "geoblender.core_show_lineage"
WIDE_PX = 5000.0  # una barra lateral en la que nada se parte (para leer cada línea entera)
VERSION_NOT_LOADED = ("Una versión o una revisión no se carga en la vista: se cargan sus "
                      "datos")
VERSION_NO_LINEAGE = "Una versión o una revisión no tiene procedencia: la tienen sus datos"
NOT_LOADED = "No está cargado en la escena: no hay nada que descargar"
VOLUME_10 = 3_182_000.0
"""``demo.pit_volume`` con los bancos de 10 m por defecto sobre ``Limites_v1`` (T08)."""
PIT_DATA = (PIT_BENCHES, PIT_GRID, PIT_MESH)
"""Lo que escribe ``demo.pit`` en su versión, por nombre."""


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

    def declare_current(self, project: Any, version: Any, *, accept: bool = False) -> None:
        """Congela la revisión abierta de ``version`` (con ``accept``, aceptando lo que haya
        que aceptar) y la declara VIGENTE (la que lo era pasa a SUPERADO), como lo harían sus
        órdenes, sin la sesión."""
        self.freeze(project, version, accept=accept)
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

    # --- Inventario y Elemento activo (T25) ----------------------------------------------------

    def freeze(self, project: Any, version: Any, *, accept: bool = False) -> None:
        """Congela la revisión abierta de ``version`` y abre la siguiente, como Nueva revisión…
        (sin la sesión); con ``accept``, aceptando todo lo que hay que aceptar (lo obsoleto)."""
        freeze = ext("core.versions.freeze")
        accepted = freeze.Acceptance.of(freeze.freeze_plan(project, version.uid)) if accept \
            else None
        outcome = drain(freeze.freeze_steps(project, version.uid, reason="Entrega",
                                            accepted=accepted))
        self.assertFalse(outcome.cancelled)
        project.refresh_header()

    def bench(self, project: Any, value: float, version: Any) -> None:
        """Cambia ``demo.bench_height`` propio de ``version`` (lo de su hueco queda
        obsoleto)."""
        store = ext("core.params").ParameterStore(project)
        self.write(project, lambda conn: store.change(
            conn, BENCH_HEIGHT, value=value, source="Plan de labores (prueba)",
            decided_by="Samuel (IMGA)", reason="Banco de la prueba", version=version.uid))

    def alter(self, project: Any, version: Any) -> str:
        """Un byte de más en el GeoTIFF de la última revisión congelada de ``version`` y la
        comprobación entera de sus huellas, que la marca «alterada»; devuelve su etiqueta
        («V02.r1»)."""
        with project.read() as conn:
            frozen = self.read.last_frozen(conn, version.uid)
        label = frozen.label(version.code)
        (changed,) = (project.root / "snapshots" / label).rglob("*.tif")
        with changed.open("ab") as stream:
            stream.write(b"\0")
        check = ext("core.versions.check")
        findings = drain(check.full_steps(project, [frozen.uid]))
        self.assertTrue(findings)
        now = ext("core.timeutil").format_utc(project.clock.now())
        self.write(project, lambda conn: check.record_findings(conn, project, findings,
                                                               now=now))
        return label

    @staticmethod
    def view() -> Any:
        """``WindowManager.geoblender_view_panels`` (leída otra vez: docs/trampas.md §4)."""
        name = ext("bl.props.views").WINDOW_MANAGER_PROPERTY
        return getattr(bpy.context.window_manager, name)

    @staticmethod
    def drawn(panel: str, *, width_px: float = WIDE_PX) -> FakeLayout:
        """El panel ``panel`` de N ▸ Proyecto dibujado (con ``width_px`` de barra lateral)."""
        with mock.patch.object(ext("bl.ui.labels"), "sidebar_width", return_value=width_px):
            return draw(getattr(bpy.types, panel), bpy.context)

    @staticmethod
    def texts(layout: FakeLayout) -> list[str]:
        return [item.text for item in layout.of_kind("label") if item.text]

    def read_inventory(self) -> None:
        """Dibuja el inventario (que pide su lectura) y hace lo que haría el temporizador de un
        disparo (en ``-b`` no corre): se retira y se llama a su función."""
        tick = ext("bl.ui.view_panels").inventory_tick
        self.drawn(INVENTORY_PANEL)
        self.assertTrue(bpy.app.timers.is_registered(tick), "el dibujo no pidió la lectura")
        bpy.app.timers.unregister(tick)
        self.assertIsNone(tick())

    def inventory(self) -> dict[tuple[str, str], tuple[Any, ...]]:
        """Las filas del inventario por nombre y versión: su categoría, su estado como lo guarda
        el proyecto, si está alterada, si está en curso y si está en la escena."""
        return {(row.name, row.version): (row.category, row.status, row.altered,
                                          row.in_progress, row.in_scene)
                for row in self.view().inventory}

    def choose(self, name: str) -> Any:
        """Elige la fila de ``name`` (como un clic en la lista)."""
        view = self.view()
        view.inventory_index = [row.name for row in view.inventory].index(name)
        return view.inventory[view.inventory_index]

    @staticmethod
    def row_drawn(row: Any) -> FakeLayout:
        """Una fila de la lista (``draw_item`` de su ``UIList``) dibujada."""
        layout = FakeLayout()
        ext("bl.ui.view_panels").draw_inventory_row(layout, row)
        return layout

    @staticmethod
    def icon_of(item: Item) -> object:
        """El icono de un elemento dibujado: el propio (``icon_value``) o el nativo."""
        return item.options.get("icon_value") or item.icon

    @staticmethod
    def state_icon(status: str) -> object:
        """El icono del estado ``status`` como lo dibuja la ventana del control 8."""
        (value,) = ext("bl.ui.version_panels").state_icon(status).values()
        return value

    @staticmethod
    def button(layout: FakeLayout, target: str) -> Item:
        (found,) = [item for item in layout.of_kind("operator") if item.target == target]
        return found

    def card(self, obj: bpy.types.Object) -> list[str]:
        """``obj`` activo y lo que hace ``msgbus`` al cambiarlo (en ``-b`` no avisa): la ficha
        leída y dibujada, una línea por etiqueta."""
        bpy.context.view_layer.objects.active = obj
        ext("bl.ui.view_panels").on_active_changed()
        return self.texts(self.drawn(ACTIVE_ITEM_PANEL))

    def figure_line(self, figure: Any, language: str = "es") -> str:
        """Una cifra como la da la ficha: su insignia de tipo, su nombre y su valor."""
        return f"{ext('bl.ui.provenance').badge(figure.kind)} {figure.text(language=language)}"

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

    def test_load_report_names_the_version(self) -> None:
        """RF-009-30 (plan A11; observación del H2, T32): Cargar en la vista… de la rejilla del
        hueco de V01, la de V02 y un dato del proyecto dice «Cargado en la vista: demo_pit_grid ·
        V01, demo_pit_grid · V02, demo_benches»: lo de una versión, con el código de su versión
        (como su nombre en la vista), y no dos veces el mismo nombre."""
        project = self.project()
        self.demo.digitize(project)
        v01 = self.create(project, "definitiva", "Definitiva")
        v02 = self.create(project, "sur", "Fase sur")
        self.demo.pit(project, "V01")
        self.demo.pit(project, "V02")
        records = (self.record(project, PIT_GRID, v01), self.record(project, PIT_GRID, v02),
                   self.record(project, BENCHES_TABLE))
        self.run_checks()
        cls = ext("bl.ui.commands").registered_class(LOAD)
        reports: list[tuple[set[str], str]] = []
        fake = operator_self(cls, report=lambda kind, text: reports.append((set(kind), text)),
                             datasets=",".join(item.uid for item in records), lod="FULL",
                             in_steps=False)
        self.assertEqual(cls.execute(fake, bpy.context), {"FINISHED"})
        self.assertEqual([text for kind, text in reports if kind == {"INFO"}],
                         [f"Cargado en la vista: {PIT_GRID} · V01, {PIT_GRID} · V02, "
                          f"{BENCHES_TABLE}"])
        self.assertEqual([path[-1] for path in map(self.path, records)],
                         [GRID.format(code="V01"), GRID.format(code="V02"), BENCHES])

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

    def test_inventory_with_versions_and_revisions(self) -> None:
        """RF-009-30, RF-009-20, RF-009-09 (spec §7; plan A11; «Hecho cuando» de la T25): con V01
        VIGENTE (r1 congelada, r2 abierta), V02 BORRADOR (r1 congelada y alterada, r2 abierta)
        y el hueco de cada una, el inventario tiene una fila por versión, con el icono y el
        nombre de su estado («V01 · Definitiva · VIGENTE · V01»), y por revisión, con el suyo
        («V01.r2 · en curso»; «V02.r1 · congelada» con la marca «alterada» en alerta), cada
        versión antes de sus revisiones, y cada dato con el código de su versión. El filtro de
        versión ofrece «Todas», «Sin versión» y las versiones leídas («V01 ·
        Definitiva», «V02 · Ampliación»): una da sus datos, su fila y sus revisiones; «Sin
        versión», lo del proyecto; filtrar no lee el proyecto. Una versión o una revisión no se
        carga en la vista ni tiene procedencia (desactivadas, con el motivo); lo de la fila
        elegida dice su tipo, su estado con sus marcas (en alerta) y su versión, y cabe a escala
        1,0 y 1,25. En inglés, «CURRENT», «in progress», «frozen · ALTERED». Al cambiar de
        proyecto, el filtro vuelve a «Todas». Nada se escribe en el proyecto."""
        project = self.project()
        self.demo.digitize(project)
        v01 = self.create(project, "definitiva", "Definitiva")
        self.demo.pit(project, "V01")
        self.run_checks()
        self.declare_current(project, v01)  # r1 congelada y VIGENTE; r2 abierta
        v02 = self.create(project, "ampliacion", "Ampliación")
        # Otra berma: su rejilla no es la de V01, y V02.r1 la copia (no la referencia).
        self.demo.pit(project, "V02", berm_m=20.0)
        self.freeze(project, v02)  # r1 congelada; r2 abierta
        self.assertEqual(self.alter(project, v02), "V02.r1")
        grid = self.record(project, PIT_GRID, v01)
        self.load(project, grid)
        counter = self.counter(project)
        view = self.view()
        panels = ext("bl.ui.view_panels")

        self.read_inventory()
        rows = self.inventory()
        expected = {
            ("V01 · Definitiva", "V01"): ("VERSION", "VIGENTE", False, False, False),
            ("V01.r1", "V01"): ("REVISION", "frozen", False, False, False),
            ("V01.r2", "V01"): ("REVISION", "open", False, True, False),
            ("V02 · Ampliación", "V02"): ("VERSION", "BORRADOR", False, False, False),
            ("V02.r1", "V02"): ("REVISION", "frozen", True, False, False),
            ("V02.r2", "V02"): ("REVISION", "open", False, True, False),
            **{(name, code): ("DATASET", "current", False, False, (name, code) == (PIT_GRID,
                                                                                   "V01"))
               for code in ("V01", "V02") for name in PIT_DATA},
        }
        self.assertEqual({key: found for key, found in rows.items() if key[1]}, expected)
        self.assertIn((BENCHES_TABLE, ""), rows)  # lo del proyecto, sin versión («—»)
        self.assertEqual([row.name for row in view.inventory
                          if row.category in ("VERSION", "REVISION")],
                         ["V01 · Definitiva", "V01.r1", "V01.r2", "V02 · Ampliación", "V02.r1",
                          "V02.r2"])

        # Cada fila: el icono de su estado, su nombre, su estado, su versión y sus marcas.
        def drawn_row(name: str) -> tuple[list[str], list[Item]]:
            labels = self.row_drawn(self.choose(name)).of_kind("label")
            return [item.text for item in labels if item.text], labels

        for name, status, code in (("V01 · Definitiva", "VIGENTE", "V01"),
                                   ("V02 · Ampliación", "BORRADOR", "V02")):
            texts, labels = drawn_row(name)
            self.assertEqual(texts, [name, status, code])
            self.assertEqual(self.icon_of(labels[0]), self.state_icon(status))
        for name, shown, code, altered in (("V01.r1", "congelada", "V01", False),
                                           ("V01.r2", "en curso", "V01", False),
                                           ("V02.r1", "congelada", "V02", True),
                                           ("V02.r2", "en curso", "V02", False)):
            texts, labels = drawn_row(name)
            self.assertEqual(texts, [name, shown, code])
            marks = [item.alert for item in labels if item.icon == "ERROR"]
            self.assertEqual(marks, [True] if altered else [], name)
        texts, _labels = drawn_row(PIT_GRID)
        self.assertEqual(texts, [PIT_GRID, "VIGENTE", "V01"])

        # El filtro de versión: las versiones leídas; filtrar no lee el proyecto.
        items = panels.version_filter_items(view, bpy.context)
        self.assertEqual([item[:2] for item in items],
                         [("ALL", "Todas"), ("NONE", "Sin versión"),
                          (v01.uid, "V01 · Definitiva"), (v02.uid, "V02 · Ampliación")])
        self.assertEqual(view.inventory_version, "ALL")
        inventory = ext("core.views.inventory")
        with mock.patch.object(inventory, "read_inventory",
                               wraps=inventory.read_inventory) as reads, \
                mock.patch.object(project, "read", wraps=project.read) as opens:
            view.inventory_version = v01.uid
            self.assertEqual([row.name for row in view.inventory],
                             [*PIT_DATA, "V01 · Definitiva", "V01.r1", "V01.r2"])
            view.inventory_version = "NONE"
            self.assertEqual({row.version for row in view.inventory}, {""})
            self.assertIn(BENCHES_TABLE, [row.name for row in view.inventory])
            view.inventory_version = v02.uid
            self.assertEqual([row.name for row in view.inventory],
                             [*PIT_DATA, "V02 · Ampliación", "V02.r1", "V02.r2"])
            self.assertEqual(view.inventory_version, v02.uid)
        self.assertEqual((reads.call_count, opens.call_count), (0, 0))

        # Lo de la fila elegida: una versión o una revisión no se carga ni tiene procedencia.
        self.choose("V02 · Ampliación")
        layout = self.drawn(INVENTORY_PANEL)
        texts = self.texts(layout)
        for line in ("V02 · Ampliación", "Tipo: Versión", "Estado: BORRADOR", "Versión: V02",
                     "No cargado en la escena", VERSION_NOT_LOADED, NOT_LOADED,
                     VERSION_NO_LINEAGE):
            self.assertIn(line, texts)
        for target in (LOAD, UNLOAD, SHOW_LINEAGE):
            self.assertFalse(self.button(layout, target).enabled, target)
        for name, status, alert in (("V02.r1", "Estado: congelada · ALTERADA", True),
                                    ("V02.r2", "Estado: en curso", False)):
            self.choose(name)
            layout = self.drawn(INVENTORY_PANEL)
            (found,) = [item for item in layout.of_kind("label")
                        if item.text.startswith("Estado:")]
            self.assertEqual((found.text, found.alert), (status, alert))
            self.assertIn("Tipo: Revisión", self.texts(layout))
            self.assertFalse(self.button(layout, LOAD).enabled)
            self.assertIn(VERSION_NOT_LOADED, self.texts(layout))

        # Cabe en la barra lateral a escala 1,0 y 1,25; los iconos son de Blender 5.2.
        sidebar = ext("bl.ui.labels").sidebar_width(bpy.context)
        icons = set(bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"]
                    .enum_items.keys())
        for name in ("V02 · Ampliación", "V02.r1"):
            self.choose(name)
            for scale in at_scales():
                layout = self.drawn(INVENTORY_PANEL, width_px=sidebar)
                assert_fits(self, layout, sidebar, scale=scale)
            drawn = [*layout.items, *(item for row in view.inventory
                                      for item in self.row_drawn(row).items)]
            self.assertLessEqual({item.icon for item in drawn}, icons)

        # En inglés.
        self.i18n.set_language("en")
        view.inventory_version = "ALL"
        self.assertEqual(drawn_row("V01 · Definitiva")[0], ["V01 · Definitiva", "CURRENT", "V01"])
        self.assertEqual(drawn_row("V01.r2")[0], ["V01.r2", "in progress", "V01"])
        self.choose("V02.r1")
        self.assertIn("Status: frozen · ALTERED", self.texts(self.drawn(INVENTORY_PANEL)))
        self.assertEqual([item[1] for item in panels.version_filter_items(view, bpy.context)],
                         ["All versions", "Without version", "V01 · Definitiva",
                          "V02 · Ampliación"])
        self.i18n.set_language("es")

        # Al cambiar de proyecto, el filtro vuelve a «Todas».
        view.inventory_version = v01.uid
        panels.on_project_changed(project)
        self.assertEqual((view.inventory_version, len(view.inventory)), ("ALL", 0))
        self.assertEqual(self.counter(project), counter)

    def test_card_of_a_dataset_of_a_version(self) -> None:
        """RF-009-20, D-9, RF-009-30 (plan A11; «Hecho cuando» de la T25): con V01 VIGENTE (r1
        congelada con el hueco y su volumen, 3 182 000 m³; r2 abierta), la ficha de su rejilla
        dice «Versión: V01 · Definitiva — en curso (r2) · vigente: r1», sus cifras «en curso
        (r2)» (las de su operación: ninguna) y las vigentes de V01, las de r1 («Cifras vigentes
        de V01.r1», con su insignia y su valor); la de V02, sin congelar, «en curso (r1)» y
        «Aún no hay ninguna revisión congelada de V02»; la de un dato del proyecto, como en la
        010 («Versión: —», «Cifras»). Cabe a escala 1,0 y 1,25. Declarada VIGENTE V02, tras la
        lectura de los indicadores, la de V01 (SUPERADO, r2 cerrada) dice «cerrada (r2) ·
        congelada: r1» y «Cifras congeladas de V01.r1»; con r1 alterada, «(alterada)» y sus
        cifras en alerta; en inglés, «closed (r2) · frozen: r1 (altered)» y «Frozen figures of
        V01.r1». Leer la ficha no escribe en el proyecto."""
        project = self.project()
        self.demo.digitize(project)
        v01 = self.create(project, "definitiva", "Definitiva")
        self.demo.pit(project, "V01")
        self.demo.pit_volume(project, "V01")
        self.run_checks()
        self.declare_current(project, v01)  # r1 congelada con el volumen; r2 abierta
        v02 = self.create(project, "ampliacion", "Ampliación")
        self.demo.pit(project, "V02")
        grids = [self.record(project, PIT_GRID, version) for version in (v01, v02)]
        benches = self.record(project, BENCHES_TABLE)
        self.load(project, *grids, benches)
        with project.read() as conn:
            (volume,) = self.read.version_figures(conn, v01.uid)
        self.assertAlmostEqual(volume.value, VOLUME_10, delta=1e-9 * VOLUME_10)
        counter = self.counter(project)

        lines = self.card(self.only(grids[0]))
        self.assertEqual(lines[0], PIT_GRID)
        self.assertIn("Versión: V01 · Definitiva — en curso (r2) · vigente: r1", lines)
        start = lines.index("Cifras en curso (r2)")
        self.assertEqual(lines[start:], ["Cifras en curso (r2)", "Sin cifras registradas",
                                         "Cifras vigentes de V01.r1", self.figure_line(volume)])
        self.assertTrue(self.figure_line(volume).startswith(
            "[CAL] Volumen del hueco (demostración) = "))
        self.assertNotIn("Cifras", lines[:start])

        lines = self.card(self.only(grids[1]))
        self.assertIn("Versión: V02 · Ampliación — en curso (r1)", lines)
        start = lines.index("Cifras en curso (r1)")
        self.assertEqual(lines[start:], ["Cifras en curso (r1)", "Sin cifras registradas",
                                         "Cifras vigentes de V02",
                                         "Aún no hay ninguna revisión congelada de V02"])

        lines = self.card(self.only(benches))
        self.assertIn("Versión: —", lines)
        self.assertIn("Cifras", lines)
        self.assertEqual([line for line in lines if line.startswith("Cifras ")], [])

        # Cabe en la barra lateral a escala 1,0 y 1,25.
        self.card(self.only(grids[0]))
        sidebar = ext("bl.ui.labels").sidebar_width(bpy.context)
        for scale in at_scales():
            layout = self.drawn(ACTIVE_ITEM_PANEL, width_px=sidebar)
            assert_fits(self, layout, sidebar, scale=scale)
        self.assertEqual(self.counter(project), counter)

        # V02 VIGENTE: V01 pasa a SUPERADO y su r2 se cierra; la lectura de los indicadores
        # vuelve a leer la ficha.
        self.declare_current(project, v02)
        self.tick(project)
        lines = self.texts(self.drawn(ACTIVE_ITEM_PANEL))
        self.assertIn("Versión: V01 · Definitiva — cerrada (r2) · congelada: r1", lines)
        start = lines.index("Cifras")
        self.assertEqual(lines[start:], ["Cifras", "Sin cifras registradas",
                                         "Cifras congeladas de V01.r1",
                                         self.figure_line(volume)])

        # Con r1 alterada, dicho y sus cifras en alerta; en inglés.
        self.assertEqual(self.alter(project, v01), "V01.r1")
        self.tick(project)
        layout = self.drawn(ACTIVE_ITEM_PANEL)
        self.assertIn("Versión: V01 · Definitiva — cerrada (r2) · congelada: r1 (alterada)",
                      self.texts(layout))
        (heading,) = [item for item in layout.of_kind("label")
                      if item.text == "Cifras congeladas de V01.r1"]
        self.assertTrue(heading.alert)
        self.i18n.set_language("en")
        lines = self.card(self.only(grids[0]))
        self.assertIn("Version: V01 · Definitiva — closed (r2) · frozen: r1 (altered)", lines)
        self.assertEqual(lines[-2:], ["Frozen figures of V01.r1",
                                      self.figure_line(volume, "en")])
        lines = self.card(self.only(grids[1]))
        self.assertIn("Version: V02 · Ampliación — in progress (r2) · current: r1", lines)
        self.assertIn("Figures in progress (r2)", lines)
        self.assertIn("Current figures of V02.r1", lines)

    def test_card_and_inventory_show_the_state_when_frozen(self) -> None:
        """RF-009-19, D-23 (plan A4 (1); F-1 de la verificación): V01 con el hueco y su volumen,
        obsoletos por su banco propio de 12 m, congelada aceptándolos y declarada VIGENTE (r2
        abierta): la ficha de su rejilla da el estado de hoy («Estado: VIGENTE · OBSOLETO»: es
        lo «en curso» de r2, D-23) y, bajo su cifra vigente de V01.r1, el que tenía al
        congelarse («obsoleta al congelarse, aceptada», en alerta). Declarada VIGENTE V02, V01
        pasa a SUPERADO: la ficha dice «Estado: VIGENTE · OBSOLETO AL CONGELARSE, ACEPTADO» (en
        alerta) y lo mismo bajo su cifra congelada; en el inventario, su fila lleva la marca
        (en alerta, un icono de Blender) y lo de la fila elegida, ese estado; la rejilla de V02
        (VIGENTE, al día), ni la marca ni el estado. En inglés, «Status: CURRENT · STALE WHEN
        FROZEN, ACCEPTED» y «stale when frozen, accepted». Cabe a escala 1,0 y 1,25. Leer y
        dibujar no escriben en el proyecto."""
        project = self.project()
        v01 = self.create(project, "definitiva", "Definitiva")
        self.demo.pit(project, "V01")
        self.demo.pit_volume(project, "V01")
        self.run_checks()
        self.bench(project, 12.0, v01)
        self.declare_current(project, v01, accept=True)  # r1: lo obsoleto, aceptado
        grid = self.record(project, PIT_GRID, v01)
        self.load(project, grid)
        with project.read() as conn:
            (volume,) = self.read.version_figures(conn, v01.uid)
        mark = "obsoleta al congelarse, aceptada"

        def alerts(layout: FakeLayout) -> dict[str, bool]:
            return {item.text: item.alert for item in layout.of_kind("label") if item.text}

        # V01 VIGENTE: lo «en curso» de r2, con el estado de hoy; su cifra de r1, con el suyo.
        lines = self.card(self.only(grid))
        self.assertIn("Estado: VIGENTE · OBSOLETO", lines)
        start = lines.index("Cifras vigentes de V01.r1")
        self.assertEqual(lines[start:], ["Cifras vigentes de V01.r1", self.figure_line(volume),
                                         mark])
        self.assertTrue(alerts(self.drawn(ACTIVE_ITEM_PANEL))[mark])

        # V02 VIGENTE: V01, SUPERADO (r2 cerrada); la ficha se lee otra vez con los indicadores.
        v02 = self.create(project, "ampliacion", "Ampliación")
        self.demo.pit(project, "V02", berm_m=20.0)
        self.declare_current(project, v02)
        self.tick(project)
        counter = self.counter(project)
        status = "Estado: VIGENTE · OBSOLETO AL CONGELARSE, ACEPTADO"
        layout = self.drawn(ACTIVE_ITEM_PANEL)
        lines = self.texts(layout)
        self.assertIn("Versión: V01 · Definitiva — cerrada (r2) · congelada: r1", lines)
        self.assertIn(status, lines)
        start = lines.index("Cifras congeladas de V01.r1")
        self.assertEqual(lines[start:], ["Cifras congeladas de V01.r1",
                                         self.figure_line(volume), mark])
        self.assertTrue(alerts(layout)[status])
        self.assertTrue(alerts(layout)[mark])

        # El inventario: la fila de la rejilla de V01, con la marca; la de V02, sin ella.
        panels = ext("bl.ui.view_panels")
        self.read_inventory()
        view = self.view()
        uids = [row.uid for row in view.inventory]
        grid2 = self.record(project, PIT_GRID, v02)

        def marks(uid: str) -> list[bool]:
            drawn = self.row_drawn(view.inventory[uids.index(uid)])
            return [item.alert for item in drawn.of_kind("label")
                    if item.icon == panels.FROZEN_STATE_ICON]

        def chosen(uid: str) -> tuple[str, bool]:
            view.inventory_index = uids.index(uid)
            (found,) = [item for item in self.drawn(INVENTORY_PANEL).of_kind("label")
                        if item.text.startswith("Estado:")]
            return found.text, found.alert

        self.assertEqual(marks(grid.uid), [True])
        self.assertEqual(marks(grid2.uid), [])
        self.assertEqual(chosen(grid.uid), (status, True))
        self.assertEqual(chosen(grid2.uid), ("Estado: VIGENTE", False))
        icons = set(bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"]
                    .enum_items.keys())
        self.assertIn(panels.FROZEN_STATE_ICON, icons)

        # Cabe en la barra lateral a escala 1,0 y 1,25.
        sidebar = ext("bl.ui.labels").sidebar_width(bpy.context)
        view.inventory_index = uids.index(grid.uid)
        for panel in (ACTIVE_ITEM_PANEL, INVENTORY_PANEL):
            for scale in at_scales():
                assert_fits(self, self.drawn(panel, width_px=sidebar), sidebar, scale=scale)

        # En inglés.
        self.i18n.set_language("en")
        lines = self.card(self.only(grid))
        self.assertIn("Status: CURRENT · STALE WHEN FROZEN, ACCEPTED", lines)
        self.assertEqual(lines[-3:], ["Frozen figures of V01.r1",
                                      self.figure_line(volume, "en"),
                                      "stale when frozen, accepted"])
        self.i18n.set_language("es")
        self.assertEqual(self.counter(project), counter)

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
