# SPDX-License-Identifier: GPL-3.0-or-later
"""«Sectores de diseño…» en Blender (spec 013, T23; HU-013-2; RF-013-07, RF-013-08, RF-013-09,
RF-013-10, RF-013-21, RF-013-33; plan 013 §5.3.3 y §5.5, D-23; ADR-0029; comprobación manual M3).

La orden ``geoblender.des_edit_design_sectors`` abre la ventana ``GEOBLENDER_PT_des_sectors`` (lo ya
leído del proyecto: nada se calcula ni se lee al dibujar) y la interna ``geoblender.des_set_sector_slope``
guarda el talud general máximo que impone un sector como parámetro de su código (ADR-0029);
«Declarar de nuevo desde una capa…» es la declaración de la 012 (``geoblender.core_declare_sectors``).
Un proyecto por clase (100 × 80 m con celdas de 2 m, V01 y V02, dos capas de polígonos) y las
pruebas, en el orden de sus letras sobre el mismo estado:

- RF-013-33 (a): las dos órdenes, la ventana y la lista son clases reales; sin proyecto, la orden dice
  por qué no está disponible.
- RF-013-07 (b): sin sectores ni perímetro la ventana lo dice; los sectores declarados salen con su
  área (a mano), el estado de su búsqueda (pendiente o vigente, cerrada por quién y cuándo) y la fila
  de la lista los marca; la ventana abierta se pone al día sola al declarar.
- RF-013-08, RF-013-09 (c): un talud de 10,6° en un sector con su origen y su decisor queda como
  parámetro de su código; la ventana lo enseña; cambiarlo en un sector y una versión no cambia los
  demás ni las demás versiones; el dominio lo resuelve igual (versión antes que proyecto).
- RF-013-08 (d): una pendiente fuera de rango, que no es un número, sin decisor o de un sector que no
  existe se rechaza nombrando el sector, el campo y el valor, y no escribe nada.
- RF-013-10 (e): redeclarar los sectores desde otra capa conserva los valores de los sectores que
  mantienen su código y deja, sin borrarlos, los del sector renombrado en una lista aparte.
- RF-013-21 (f): el perfil asignado a cada sector se enseña con su nombre.
- RF-013-07, RF-013-33 (g, h): la ventana y el diálogo en los dos idiomas; con la versión activa
  SUPERADO la ventana dice por qué y desactiva lo que escribe.
- Principio 8 (z): desactivar Geoblender quita las órdenes, la ventana y la lista.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import FakeLayout, draw, operator_self
from tests.support.trees import remove_tree

OPEN = "geoblender.des_edit_design_sectors"
SET_SLOPE = "geoblender.des_set_sector_slope"
DECLARE = "geoblender.core_declare_sectors"
FIND = "geoblender.core_find_untouchables"
PANEL = "GEOBLENDER_PT_des_sectors"
LIST = "GEOBLENDER_UL_des_sectors"
VIEW_PROPERTY = "geoblender_design"
CONSTRAINTS_PROPERTY = "geoblender_constraints"
REASON = "Prueba de los sectores de diseño"
PERSON = "Samuel (IMGA)"
SOURCE = "la propiedad"
WEST = 700_000.0
SOUTH = 4_400_000.0
WIDTH_M = 100.0
HEIGHT_M = 80.0
STEP_M = 2.0
BOXES = {"Sector 1": (10.0, 10.0, 40.0, 70.0), "Sector 2": (50.0, 10.0, 90.0, 70.0)}
RENAMED = {"Sector 1": BOXES["Sector 1"], "Zona Norte": BOXES["Sector 2"]}
AREAS_M2 = {"sector_1": 30.0 * 60.0, "sector_2": 40.0 * 60.0}
"""El área de cada sector a mano: lados alineados con la rejilla de 2 m (base por altura)."""
SLOPE_KEY = "des.sector.{}.max_general_slope_deg"
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
CLOSED_AT = "2026-10-28T10:00:00Z"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def rectangle(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local dado."""
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


class DesignSectorsTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02 y dos capas de polígonos para toda
    la clase (las pruebas, en el orden de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-d23-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.des_ops = _module("bl.ops.des")
        cls.panels = _module("bl.ui.des_panels")
        cls.ui = _module("bl.ui.provenance")
        cls.params = _module("core.params")
        cls.i18n = _module("core.i18n")
        cls.cstore = _module("core.constraints.store")
        cls.cmodel = _module("core.constraints.model")
        cls.sectors = _module("design.sectors")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + WIDTH_M, SOUTH + HEIGHT_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="definitiva",
                                                      title="Definitiva", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        sources = folder / "fuentes"
        sources.mkdir()
        cls.layers = {"Sectores": cls.import_layer(sources, "Sectores", BOXES),
                      "Renombrados": cls.import_layer(sources, "Renombrados", RENAMED)}
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)

    @classmethod
    def import_layer(cls, folder: Path, name: str,
                     boxes: dict[str, tuple[float, float, float, float]]) -> str:
        """«Capas vectoriales…» de la 006 con el papel «Entidades», sin su trabajo: la capa ``name``
        de un GeoPackage fuera del proyecto con un polígono por cada ``(nombre, caja local)``, en el
        campo ``sector``; el nombre de su dato (``gis_fea_``)."""
        crs, vertical = _module("gis.store").project_references(cls.project)
        path = folder / f"{name}.gpkg"
        conn = sqlite3.connect(path)
        try:
            _module("core.gpkg.base").create_base(conn, crs)
            conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT '
                         'NULL, geom GEOMETRY, "sector" TEXT)')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                         (name, name, crs.epsg))
            conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', 'POLYGON', ?, 0, 0)",
                         (name, crs.epsg))
            encode = _module("core.gpkg.wkb").encode_geometry
            features = []
            for fid, (label, box) in enumerate(boxes.items(), start=1):
                ring = rectangle(*box)
                conn.execute(f'INSERT INTO "{name}" VALUES (?, ?, ?)',
                             (fid, encode("POLYGON", [ring], crs.epsg, False), label))
                features.append((fid, ring, {"sector": label}))
            conn.commit()
        finally:
            conn.close()
        inputs, gis_store, vector = (_module("core.inputs"), _module("gis.store"),
                                     _module("gis.vector"))
        reader = _module("gis.content").GPKG_LAYER
        settings = {"layer": name, "role": "features"}
        anchors = [inputs.locate_source(path, cls.project, cls.ps.userdata(), role="main")]
        prints = [_module("core.inputs.model").SourcePrint(
            _module("core.hashing").sha256_file(path), size=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns)]
        request = reader.request(
            reader.kinds[0], gis_store.source_declarations(reader.id, crs, vertical, settings),
            dict(zip(inputs.reader_roles(anchors), [path], strict=True)), settings)
        spec = gis_store.source_input(
            reader.id, name, files=anchors, file_prints=prints,
            digest=_module("core.content.readers").read_content(reader, request), crs=crs,
            vertical=vertical, settings=settings)
        copies = folder / f"copia_{name}"
        copies.mkdir()
        read = vector.read_layer(vector.copy_source(path, copies), name)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").IMPORT_VECTOR, settings={"nombre": name},
            executor="blender")
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.declare_input(spec)
            out.features(name, vector.features_from_layer(read)[0])
            (record,) = out.commit(message=REASON)
        assert len(features) == len(boxes)
        return record.name

    @staticmethod
    def set_active(version: Any) -> None:
        assert bpy.ops.geoblender.core_set_active_version(
            version_uid="" if version is None else version.uid) == {"FINISHED"}

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    @property
    def constraints(self) -> Any:
        return getattr(bpy.context.window_manager, CONSTRAINTS_PROPERTY)

    def number(self, value: float, decimals: int = 0) -> str:
        return self.i18n.format_number(value, decimals)

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def counts(self) -> tuple[int, int, int]:
        """Operaciones, parámetros de sector y entradas de su historial (lo que un rechazo no
        cambia)."""
        return (self.rows("SELECT count(*) FROM gb_operation")[0][0],
                self.rows("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.sector.%'")[0][0],
                sum(len(self.params.ParameterStore(self.project).history(key, version=version))
                    for (key,) in self.rows("SELECT DISTINCT key FROM gb_parameter "
                                            "WHERE key LIKE 'des.sector.%'")
                    for version in (None, self.v01.uid, self.v02.uid)))

    def opened(self) -> Any:
        """«Sectores de diseño…» con su ventana sustituida (en ``blender -b``, ``wm.call_panel``
        cierra Blender): la vista, leída del proyecto."""
        with mock.patch.object(self.des_ops, "_call_panel", return_value={"FINISHED"}) as call:
            self.assertEqual(bpy.ops.geoblender.des_edit_design_sectors(), {"FINISHED"})
        call.assert_called_once_with(PANEL)
        return self.view

    def sector(self, code: str) -> Any:
        found = [item for item in self.opened().sectors if item.code == code]
        self.assertEqual(len(found), 1, f"{code}: {[item.code for item in self.view.sectors]}")
        return found[0]

    def set_slope(self, code: str, slope: str, **values: Any) -> set[str]:
        """La orden interna con una declaración completa (lo que no se da: ADOPTADO, la propiedad,
        la persona, el proyecto)."""
        given = {"kind": "ADOPTADO", "source": SOURCE, "source_kind": "PERSON",
                 "decided_by": PERSON, "reason": REASON, "scope": "PROJECT", **values}
        return bpy.ops.geoblender.des_set_sector_slope(code=code, slope=slope, **given)

    def declare(self, layer: str) -> None:
        """«Declarar de nuevo desde una capa…»: la orden de la 012 con la capa y el campo de la
        ventana, y el tic de los indicadores (que en ``blender -b`` no corre)."""
        view = self.constraints
        view.sector_layer, view.sector_field = self.layers[layer], "sector"
        self.assertEqual(bpy.ops.geoblender.core_declare_sectors(), {"FINISHED"})
        self.ui.refresh(force=True)

    def close_search(self, code: str, clock_minutes: int) -> None:
        """Cierra la búsqueda de intocables de un sector (con su huella), como hará la orden de la
        012: queda sin la marca de pendiente."""
        with self.project.read() as conn:
            (sector,) = [item for item in self.cstore.read_sectors(conn) if item.code == code]
        handle = _module("core.provenance.operations").begin_operation(
            self.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = self.cmodel.SearchRecord(f"search{clock_minutes}{'0' * 25}", handle.uid, code,
                                          self.cstore.sector_sha256(sector), 25.0, PERSON,
                                          CLOSED_AT)
        with self.project.write_transaction() as conn:
            self.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=self.cstore.dataset_specs(
                crs_epsg=self.project.record.crs_epsg), message="Búsqueda de prueba")

    def stored(self, code: str, scope: str = "project") -> tuple[Any, ...] | None:
        """La fila del talud del sector ``code``: (valor, tipo, origen, decisor) o ``None``."""
        found = self.rows("SELECT value, kind, source, decided_by FROM gb_parameter "
                          "WHERE key = ? AND scope = ?", SLOPE_KEY.format(code), scope)
        return None if not found else (json.loads(found[0][0]), *found[0][1:])

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_commands_and_the_window_are_registered(self) -> None:
        """RF-013-33 (plan §5.3.3): «Sectores de diseño…» y la interna que guarda el talud son
        clases reales de ``bl.ops.des`` (con la ventana y su lista) y la interna está en el
        catálogo; sin proyecto, la orden no está disponible y dice por qué."""
        for idname in (OPEN, SET_SLOPE):
            with self.subTest(orden=idname):
                self.assertIn(self.commands.registered_class(idname), self.des_ops.classes)
        for name in (PANEL, LIST):
            self.assertIsNotNone(getattr(bpy.types, name, None), name)
        self.assertEqual(self.commands.catalog().commands[SET_SLOPE].kind, "internal")
        self.assertTrue(bpy.ops.geoblender.des_edit_design_sectors.poll())
        cls = self.commands.registered_class(OPEN)
        with mock.patch.object(cls, "poll_message_set") as said, \
                mock.patch.object(self.session, "write_unavailable", return_value="Abra un proyecto"), \
                mock.patch.object(self.des_ops, "write_unavailable", return_value="Abra un proyecto"):
            self.assertFalse(cls.poll(bpy.context))
        said.assert_called_once_with("Abra un proyecto")

    def test_b_the_sectors_with_their_area_and_the_state_of_their_search(self) -> None:
        """RF-013-07: sin sectores ni perímetro la ventana lo dice; declarados desde una capa (la
        orden de la 012), salen con su nombre, su código, su área (a mano) y la búsqueda
        pendiente, en ámbar; la ventana ya abierta se pone al día sola; cerrada la búsqueda del
        sector 1, sale vigente con quién la cerró y cuándo."""
        view = self.opened()
        self.assertEqual(len(view.sectors), 0)
        self.assertEqual(view.sectors_project, self.project.uid)
        texts = draw(getattr(bpy.types, PANEL), bpy.context).texts()
        self.assertIn("declare primero el límite legal", " ".join(texts))  # el texto se parte
        self.assertIn(self.layers["Sectores"], [item.name for item in self.constraints.sector_sources])
        self.declare("Sectores")
        names = {item.code: item for item in view.sectors}  # la misma vista, sin reabrirla
        self.assertEqual([item.name for item in view.sectors], ["Sector 1", "Sector 2"])
        self.assertEqual(list(names), ["sector_1", "sector_2"])
        for code, item in names.items():
            with self.subTest(sector=code):
                self.assertEqual(item.area, f"{self.number(AREAS_M2[code])} m²")
                self.assertEqual(item.search, "Búsqueda pendiente")
                self.assertTrue(item.pending)
                self.assertEqual((item.slope, item.slope_source, item.problem, item.profile), ("",) * 4)
        self.close_search("sector_1", 1)
        one, two = self.sector("sector_1"), self.sector("sector_2")
        self.assertFalse(one.pending)
        self.assertEqual(one.search, "Búsqueda vigente, cerrada por Samuel (IMGA) el 28/10/2026")
        self.assertTrue(two.pending)
        self.assertEqual(two.search, "Búsqueda pendiente")
        row = FakeLayout()
        ul = getattr(bpy.types, LIST)
        ul.draw_item(None, bpy.context, row, self.view, two, 0, self.view, "sector_index")
        self.assertIn("Sector 2", row.texts())
        pending = [item for item in row.items if "Búsqueda pendiente" in item.text]
        self.assertTrue(pending and all(item.alert for item in pending), row.texts())
        calm = FakeLayout()
        ul.draw_item(None, bpy.context, calm, self.view, one, 0, self.view, "sector_index")
        self.assertFalse(any(item.alert for item in calm.items), calm.texts())
        self.view.sector_index = 1
        self.assertEqual(self.opened().sector_index, 1)  # volver a leer conserva el elegido
        self.i18n.set_language("en")
        self.assertEqual(self.sector("sector_2").search, "Search pending")
        self.assertEqual(self.sector("sector_1").search,
                         "Search in force, closed by Samuel (IMGA) on 28/10/2026")

    def test_c_the_slope_a_sector_imposes_with_its_source_and_decider(self) -> None:
        """RF-013-08, RF-013-09, RF-013-07: 10,6° en el sector 2 con su origen y su decisor queda
        como parámetro de su código (ADOPTADO, del proyecto); la ventana lo enseña; cambiarlo en un
        sector y una versión no cambia los demás ni las otras versiones; cambiar un valor que ya
        existe añade una entrada a su historial; el dominio lo resuelve igual."""
        before = self.counts()
        journal = _module("bl.scene.undo_watch").JOURNAL
        noted = len(journal.entries)
        self.assertEqual(self.set_slope("sector_2", "10,6"), {"FINISHED"})
        self.assertEqual(self.stored("sector_2"), (10.6, "ADOPTADO", SOURCE, PERSON))
        self.assertIsNone(self.stored("sector_1"))
        self.assertEqual(self.counts()[0], before[0])  # un parámetro no es una operación
        self.assertEqual(len(journal.entries), noted + 1)  # Ctrl+Z no lo deshace: queda apuntado
        self.assertEqual(journal.entries[-1].label, SLOPE_KEY.format("sector_2"))
        # la ventana ya abierta se pone al día sola, con el sector elegido y lo que se hizo
        shown = self.view
        self.assertEqual(next(item for item in shown.sectors if item.code == "sector_2").slope,
                         "10,6° [ADO]")
        self.assertEqual([line.name for line in shown.sector_report],
                         ["Talud impuesto por Sector 2 en el proyecto: 10,6° [ADO]"])
        self.assertEqual(shown.sectors[shown.sector_index].code, "sector_2")
        self.assertIn("Talud impuesto por Sector 2 en el proyecto: 10,6° [ADO]",
                      draw(getattr(bpy.types, PANEL), bpy.context).texts())
        item = self.sector("sector_2")
        self.assertEqual(item.slope, "10,6° [ADO]")
        self.assertEqual(item.slope_source, f"{SOURCE} · decidido por {PERSON} · el proyecto")
        self.assertEqual(self.sector("sector_1").slope, "")
        # el sector 1, 8° solo para la versión V01; V02 no lo ve (RF-013-08)
        self.assertEqual(self.set_slope("sector_1", "8", scope="VERSION"), {"FINISHED"})
        self.assertIsNone(self.stored("sector_1"))
        self.assertEqual(self.stored("sector_1", "version")[0], 8.0)
        self.assertEqual(self.sector("sector_1").slope_source,
                         f"{SOURCE} · decidido por {PERSON} · V01")
        self.set_active(self.v02)
        self.assertEqual(self.sector("sector_1").slope, "")
        self.assertEqual(self.sector("sector_2").slope, "10,6° [ADO]")  # el del proyecto
        self.set_active(self.v01)
        # un valor propio de V01 en el sector 2 manda sobre el del proyecto; el del proyecto sigue
        self.assertEqual(self.set_slope("sector_2", "12", scope="VERSION"), {"FINISHED"})
        self.assertEqual(self.stored("sector_2")[0], 10.6)
        self.assertEqual(self.sector("sector_2").slope, "12° [ADO]")
        # cambiar uno que ya existe: otra entrada de su historial, la misma fila
        key = SLOPE_KEY.format("sector_2")
        store = self.params.ParameterStore(self.project)
        self.assertEqual(len(store.history(key)), 1)
        self.assertEqual(self.set_slope("sector_2", "11", kind="HIPOTESIS"), {"FINISHED"})
        self.assertEqual(self.set_slope("sector_2", "10.6", reason="Vuelve al valor de la propiedad"),
                         {"FINISHED"})
        self.assertEqual([entry.value for entry in store.history(key)], [10.6, 11.0, 10.6])
        self.assertEqual(self.stored("sector_2"), (10.6, "ADOPTADO", SOURCE, PERSON))
        # el dominio lo resuelve igual: versión antes que proyecto, y el sector sin fila, nada
        found = self.sectors.design_sectors(self.project, self.v01.uid)
        self.assertEqual(self.sectors.imposed_slopes(found), {"sector_1": 8.0, "sector_2": 12.0})
        found = self.sectors.design_sectors(self.project, self.v02.uid)
        self.assertEqual(self.sectors.imposed_slopes(found), {"sector_2": 10.6})
        self.assertEqual(self.sectors.slope_params(found), (SLOPE_KEY.format("sector_2"),))

    def test_d_rejections_name_the_sector_the_field_and_the_value(self) -> None:
        """RF-013-08: una pendiente fuera de (0; 90) °, que no es un número, ausente, sin decisor o
        de un sector que no existe se rechaza nombrando el sector, el campo y el valor, y no
        escribe nada (ni un parámetro ni una entrada de su historial)."""
        before = self.counts()
        key = SLOPE_KEY.format("sector_2")
        cases = {
            "95°": (("sector_2", "95"), (key, "95", "sector_2")),
            "90°": (("sector_2", "90"), (key, "90")),
            "0°": (("sector_2", "0"), (key, "0")),
            "negativa": (("sector_2", "-3"), (key, "-3")),
            "no es un número": (("sector_2", "diez"), ("diez",)),
            "ausente": (("sector_2", ""), ("talud",)),
            "sin decisor": (("sector_2", "9", {"decided_by": " "}), ("quién decide",)),
            "sector inexistente": (("sector_9", "9"), ("ya no está en el proyecto",)),
        }
        for label, (arguments, expected) in cases.items():
            with self.subTest(caso=label):
                code, slope, *extra = arguments
                with self.assertRaises(RuntimeError) as raised:
                    self.set_slope(code, slope, **(extra[0] if extra else {}))
                for part in expected:
                    self.assertIn(part, str(raised.exception))
                self.assertEqual(self.counts(), before)
        self.i18n.set_language("en")
        with self.assertRaises(RuntimeError) as raised:
            self.set_slope("sector_2", "95")
        self.assertIn("is outside its range", str(raised.exception))
        self.assertIn(key, str(raised.exception))
        self.i18n.set_language("es")
        self.assertEqual(self.counts(), before)

    def test_e_redeclaring_the_sectors_keeps_the_values_and_lists_the_orphans(self) -> None:
        """RF-013-10: redeclarar los sectores desde otra capa (la 012) conserva con su historial el
        valor del sector que mantiene su código y deja, sin borrarlo, el del sector renombrado
        (del proyecto y de V01) en una lista aparte; el sector nuevo no tiene talud."""
        store = self.params.ParameterStore(self.project)
        kept_key, gone_key = SLOPE_KEY.format("sector_1"), SLOPE_KEY.format("sector_2")
        history = [entry.value for entry in store.history(gone_key)]
        self.assertEqual(len(self.view.orphans), 0)
        self.opened()
        self.declare("Renombrados")  # la ventana abierta se pone al día con el tic
        self.assertEqual([(item.code, item.name) for item in self.view.sectors],
                         [("sector_1", "Sector 1"), ("zona_norte", "Zona Norte")])
        self.assertEqual(self.sector("sector_1").slope, "8° [ADO]")  # el de V01, conservado
        self.assertEqual(self.sector("zona_norte").slope, "")
        self.assertEqual(self.stored("sector_1", "version")[0], 8.0)
        self.assertEqual([entry.value for entry in store.history(gone_key)], history)
        self.assertEqual(self.stored("sector_2"), (10.6, "ADOPTADO", SOURCE, PERSON))  # sin borrar
        self.assertEqual(self.stored("sector_2", "version")[0], 12.0)
        lines = [(line.name, line.alert) for line in self.view.orphans]
        self.assertEqual(len(lines), 2)
        for text, alert in lines:
            self.assertTrue(alert)
            self.assertIn("«sector_2»", text)
            self.assertIn(f"{SOURCE} · decidido por {PERSON}", text)
        self.assertEqual(sorted(text.split(": ")[1].split(" · ")[0] for text, _a in lines),
                         ["10,6° [ADO]", "12° [ADO]"])
        self.assertEqual(sorted(text.split(": ")[0] for text, _a in lines),
                         ["Talud de «sector_2» en V01", "Talud de «sector_2» en el proyecto"])
        self.assertTrue(store.get(kept_key, version=self.v01.uid) is not None)
        # el huérfano se pasa al sector nuevo declarando su talud; no se borra por ello
        self.assertEqual(self.set_slope("zona_norte", "10,6"), {"FINISHED"})
        self.assertEqual(self.sector("zona_norte").slope, "10,6° [ADO]")
        self.assertEqual(len(self.view.orphans), 2)
        texts = draw(getattr(bpy.types, PANEL), bpy.context).texts()
        self.assertTrue(any("Parámetros sin sector: 2" in text for text in texts), texts)
        self.assertTrue(any("«sector_2»" in text for text in texts), texts)

    def test_f_the_profile_assigned_to_each_sector_is_shown_by_name(self) -> None:
        """RF-013-21, RF-013-07: el perfil asignado a la superficie en preparación (la ventana de
        las envolventes lo pone con ``assign_profiles``) se enseña con su nombre en su sector y sobrevive
        a volver a leer los sectores; quitarlo lo deja sin perfil."""
        self.assertEqual(bpy.ops.geoblender.des_save_bench_profile(
            name="EXPL_10_60_6", height="10", face="60", berm="6", anchor="125", kind="ADOPTADO",
            source=SOURCE, decided_by=PERSON, reason=REASON, scope="PROJECT"), {"FINISHED"})
        self.opened()
        self.panels.assign_profiles(self.project, {"sector_1": "expl_10_60_6"})
        one = self.sector("sector_1")
        self.assertEqual((one.profile, one.profile_name), ("expl_10_60_6", "EXPL_10_60_6"))
        self.assertEqual(self.sector("zona_norte").profile, "")
        self.view.sector_index = [item.code for item in self.view.sectors].index("sector_1")
        texts = draw(getattr(bpy.types, PANEL), bpy.context).texts()
        self.assertTrue(any(text == "Perfil asignado: EXPL_10_60_6" for text in texts), texts)
        self.view.sector_index = 1
        texts = draw(getattr(bpy.types, PANEL), bpy.context).texts()
        self.assertTrue(any(text == "Perfil asignado: —" for text in texts), texts)
        self.panels.assign_profiles(self.project, {})
        self.assertEqual(self.sector("sector_1").profile, "")

    def test_g_the_window_draws_the_sectors_and_blocks_writing_in_a_superseded_version(self) -> None:
        """RF-013-07, RF-013-33: la ventana dibuja la lista, el sector elegido (su búsqueda en ámbar
        con la orden de la 012, su talud y «Fijar el talud…»), los huérfanos y «Declarar de nuevo
        desde una capa…»; con la versión activa SUPERADO dice por qué y desactiva lo que escribe;
        en inglés, en inglés."""
        shown = self.opened()
        shown.sector_index = [item.code for item in shown.sectors].index("zona_norte")
        panel = getattr(bpy.types, PANEL)
        layout = draw(panel, bpy.context)
        texts = layout.texts()
        self.assertIn("template_list", {item.kind for item in layout.items})
        self.assertTrue(any("Zona Norte" in text for text in texts), texts)
        self.assertIn("Búsqueda pendiente", texts)
        alerts = [item.text for item in layout.items if item.alert and item.kind == "label"]
        self.assertTrue(any("Búsqueda pendiente" in text for text in alerts), alerts)
        self.assertIn("Declarar de nuevo desde una capa…", texts)
        self.assertIn("Capa de los sectores", texts)
        buttons = {item.target: item for item in layout.items if item.kind == "operator"}
        for target in (SET_SLOPE, DECLARE, FIND):
            self.assertIn(target, buttons)
            self.assertTrue(buttons[target].enabled, target)
        self.assertEqual(buttons[SET_SLOPE].properties.code, "zona_norte")
        # sin la búsqueda pendiente, la alerta y la orden desaparecen
        shown.sector_index = [item.code for item in shown.sectors].index("sector_1")
        calm = draw(panel, bpy.context)
        self.assertFalse(any(item.alert and "Búsqueda pendiente" in item.text for item in calm.items))
        self.assertNotIn(FIND, {item.target for item in calm.items if item.kind == "operator"})
        # en inglés
        self.i18n.set_language("en")
        shown = self.opened()
        english = draw(panel, bpy.context).texts()
        self.assertIn("Declare again from a layer…", english)
        self.assertTrue(any(text.startswith("Design sectors: ") for text in english), english)
        self.i18n.set_language("es")
        shown = self.opened()
        # la versión activa SUPERADO
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", (REASON, self.v02.uid))
        self.set_active(self.v02)
        self.assertEqual(_module("bl.scene.versions").not_editable_text(), NOT_EDITABLE)
        shown.sector_index = [item.code for item in shown.sectors].index("zona_norte")
        blocked = draw(panel, bpy.context)
        self.assertIn(NOT_EDITABLE, " ".join(blocked.texts()))
        writes = [item for item in blocked.items
                  if item.kind == "operator" and item.target in (SET_SLOPE, DECLARE)]
        self.assertTrue(writes and not any(item.enabled for item in writes))
        self.assertTrue(any("Zona Norte" in text for text in blocked.texts()))  # se sigue viendo
        self.assertFalse(bpy.ops.geoblender.des_set_sector_slope.poll())
        self.assertFalse(bpy.ops.geoblender.des_edit_design_sectors.poll())
        self.set_active(self.v01)

    def test_h_the_dialog_asks_the_scope_and_fills_what_the_sector_has(self) -> None:
        """RF-013-08, RF-009-29: el diálogo de la orden interna pregunta «¿Para el proyecto o solo
        para V01?», propone el decisor y, de un sector que ya tiene talud en el ámbito, su valor, su
        tipo, su origen y su decisor; no cambia nada hasta que se acepta."""
        cls = self.commands.registered_class(SET_SLOPE)
        asked: list[dict[str, Any]] = []

        def dialog(operator: Any, **options: Any) -> set[str]:
            asked.append(options)
            return {"RUNNING_MODAL"}

        manager = SimpleNamespace(invoke_props_dialog=dialog)
        context = SimpleNamespace(window_manager=manager, window=object())
        unset = SimpleNamespace(is_property_set=lambda name: False)
        before = self.counts()
        # el sector 1 solo tiene talud en V01 (V02 no lo ve): con V02 activa, el diálogo parte vacío
        self.set_active(self.v02)
        fresh = operator_self(cls, code="sector_1", slope="", scope="PROJECT", decided_by="",
                              reason="", kind="ADOPTADO", source="", source_kind="PERSON",
                              properties=unset)
        self.assertEqual(cls.invoke(fresh, context, None), {"RUNNING_MODAL"})
        self.assertEqual(len(asked), 1)
        self.assertEqual((fresh.slope, fresh.scope, fresh.decided_by),
                         ("", "PROJECT", self.project.session.user_host))
        self.set_active(self.v01)
        # con V01 activa tiene valor propio: se propone ese ámbito y ese valor, con su origen
        own = operator_self(cls, code="sector_1", slope="", scope="PROJECT", decided_by="",
                            reason="", kind="HIPOTESIS", source="", source_kind="DOCUMENT",
                            properties=unset)
        self.assertEqual(cls.invoke(own, context, None), {"RUNNING_MODAL"})
        self.assertEqual((own.slope, own.scope, own.kind, own.source, own.source_kind,
                          own.decided_by), ("8", "VERSION", "ADOPTADO", SOURCE, "PERSON", PERSON))
        # sin valor propio en V01, el del proyecto
        existing = operator_self(cls, code="zona_norte", slope="", scope="PROJECT", decided_by="",
                                 reason="", kind="HIPOTESIS", source="", source_kind="DOCUMENT",
                                 properties=unset)
        self.assertEqual(cls.invoke(existing, context, None), {"RUNNING_MODAL"})
        self.assertEqual((existing.slope, existing.scope, existing.kind, existing.source,
                          existing.source_kind, existing.decided_by),
                         ("10,6", "PROJECT", "ADOPTADO", SOURCE, "PERSON", PERSON))
        said = mock.Mock()
        lost = operator_self(cls, code="sector_9", slope="", scope="PROJECT", decided_by="",
                             reason="", report=said, properties=unset)
        self.assertEqual(cls.invoke(lost, context, None), {"CANCELLED"})
        self.assertEqual(said.call_args.args[0], {"ERROR"})
        self.assertIn("ya no está en el proyecto", said.call_args.args[1])
        self.assertEqual(len(asked), 3)
        self.assertEqual(self.counts(), before)
        layout = draw(cls, bpy.context, method="draw", code="zona_norte", slope="10,6",
                      scope="PROJECT", kind="ADOPTADO", source="x", source_kind="PERSON",
                      decided_by=PERSON, reason="", _title="Zona Norte")
        texts = layout.texts()
        self.assertIn("¿Para el proyecto o solo para V01?", texts)
        self.assertIn("Solo V01", texts)
        props = [item.target for item in layout.items if item.kind == "prop"]
        for name in ("slope", "kind", "source", "source_kind", "decided_by", "reason"):
            self.assertIn(name, props)

    def test_z_disabling_leaves_no_trace(self) -> None:
        """Principio 8: desactivar Geoblender quita las dos órdenes, la ventana y la lista (la
        huella entera la mira el lanzador al terminar)."""
        blender_ext.release()
        for name in (PANEL, LIST, "GEOBLENDER_OT_des_edit_design_sectors",
                     "GEOBLENDER_OT_des_set_sector_slope"):
            with self.subTest(clase=name):
                self.assertIsNone(getattr(bpy.types, name, None))
        self.assertFalse(hasattr(bpy.types.WindowManager, VIEW_PROPERTY))


if __name__ == "__main__":
    unittest.main()
