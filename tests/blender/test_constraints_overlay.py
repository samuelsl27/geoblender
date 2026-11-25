# SPDX-License-Identifier: GPL-3.0-or-later
"""Ver restricciones y límites (spec 012, T26; HU-012-1 a HU-012-4; RF-012-18; RNF-012-05; plan
012 §5.3.3, §5.5, D-30; comprobación manual M4; principio 8).

La superposición de la Vista 3D (``bl.draw.constraints``, control 30
``geoblender.core_toggle_constraints_overlay``) es un manejador de dibujo sin objetos ni
escritura: lo que dibuja se prueba en sus lotes (sus segmentos en coordenadas locales, por tipo) y
en sus textos en píxeles, no en píxeles de pantalla (``docs/trampas.md`` §3: sin GPU en
``blender -b``). Un proyecto por clase (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, seis
restricciones de seis tipos) y las pruebas, en el orden de sus letras sobre el mismo estado:

- RF-012-18 (a, b): el control 30 es una orden real de la entrada «012»; activarla pone el
  manejador y construye, por pasos, un lote de contornos por tipo (el color del tipo, el mismo de
  QGIS: ``core.constraints.styles``), los nombres y la leyenda con un color por tipo, a la cota
  del GeoOrigin y sin escribir en el proyecto (los mismos ficheros bit a bit, ninguna operación
  nueva); sin máscaras compiladas lo dice; desactivarla lo quita todo.
- RF-012-18 (c, d): con las máscaras compiladas se rayan las zonas de cada tipo (no las de los
  límites: su interior es el dominio), el dominio por defecto y la franja de solo relleno; cambiar
  de versión activa o compilar la rehace.
- RF-012-18 (e, f): sobre una superficie del proyecto (la elegida o, por defecto, la rejilla más
  reciente) los contornos siguen su cota; los segmentos largos se parten.
- RF-012-18, RNF-012-05 (g, h): lo que se dibuja en píxeles (los nombres que caben y la leyenda en
  una esquina) y el dibujo de los lotes con ``gpu`` (uno por lote), sin que cambie el estado de
  ``gpu``.
- RF-012-18 (i): conmutar a la interfaz de Blender la quita y volver no la pone sola; cerrar el
  proyecto también.
- Principio 8 (z): desactivar Geoblender con la superposición activa quita el manejador, los
  avisos y el temporizador y deja la huella de Blender como al principio de la sesión.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import importlib
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import bpy
import numpy as np
from mathutils import Matrix

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw
from tests.support.trees import remove_tree

ENTRY = "012"
TOGGLE = "geoblender.core_toggle_constraints_overlay"
WM_PROPERTY = "geoblender_constraints_overlay"
VIEW_PROPERTY = "geoblender_constraints"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
REASON = "Prueba de la superposición de las restricciones"
PERSON = "Samuel (IMGA)"
# (nombre, tipo, geometría, partes locales). La concesión es el límite legal (2 m hacia dentro);
# el perímetro de actuación es mayor, así que sobra una franja de solo relleno.
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 2.0, 56.0, 56.0)
TOWER = (20.0, 20.0, 26.0, 26.0)
POND = (34.0, 10.0, 44.0, 18.0)
TRACK = ((6.0, 40.0), (52.0, 40.0))
TREE = (12.0, 12.0)
BUFFER_M = 4.0
TYPES = ("legal_limit", "action_perimeter", "untouchable", "no_cut", "requires_access", "avoid")
NAMES = {"legal_limit": "Concesión", "action_perimeter": "Perímetro", "untouchable": "Torre 132 kV",
         "no_cut": "Balsa", "requires_access": "Camino", "avoid": "Árbol"}
# Segmentos del contorno de cada tipo: un rectángulo, 4; el camino, 1; el punto, su cruz de 2.
OUTLINE_SEGMENTS = {"legal_limit": 4, "action_perimeter": 4, "untouchable": 4, "no_cut": 4,
                    "requires_access": 1, "avoid": 2}
VIOLET = (0.7, 0.25, 0.9)  # el de las intenciones del cliente: ningún tipo lo repite
MAX_PUMPS = 20_000
SIZE = (600, 400)  # la región, en píxeles
HALF = 60.0  # la vista desde arriba: 120 m de ancho


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def top_view(centre: tuple[float, float]) -> np.ndarray:
    """La matriz de una vista desde arriba (ortográfica) de 2·:data:`HALF` m de ancho y el alto
    de la región, centrada en ``centre`` (locales)."""
    width, height = SIZE
    sx, sy = 1.0 / HALF, width / (height * HALF)
    return np.array([[sx, 0.0, 0.0, -centre[0] * sx],
                     [0.0, sy, 0.0, -centre[1] * sy],
                     [0.0, 0.0, -0.001, 0.0],
                     [0.0, 0.0, 0.0, 1.0]])


class ConstraintsOverlayTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02 y seis restricciones, para
    toda la clase (las pruebas, en el orden de sus letras: cada una parte de lo que dejó la
    anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-r26-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.switcher = _module("bl.ui.switcher")
        cls.versions = _module("bl.scene.versions")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.styles = _module("core.constraints.styles")
        cls.masks_store = _module("gis.masks.store")
        cls.gis_store = _module("gis.store")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="mascaras",
                                                      title="Máscaras", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.codes = cls.declare()
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)
        cls.ov = _module("bl.draw.constraints")

    @classmethod
    def declare(cls) -> dict[str, str]:
        """Las seis restricciones como las dejará la orden (``core.edit_constraints`` con los
        parámetros que pide cada tipo); el código de cada una por su tipo."""
        m, kinds = cls.cmodel, cls.cmodel.GeometryKind

        def row(ctype: Any, kind: Any, parts: Any) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=NAMES[ctype.value], ctype=ctype, kind=kind,
                parts=parts, priority=0, reason=REASON, decided_by=PERSON,
                decided_on=date(2026, 11, 1), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kind), fid=0)

        T = m.ConstraintType
        rows = [
            row(T.LEGAL_LIMIT, kinds.POLYGON, ((ring(LEGAL),),)),
            row(T.ACTION_PERIMETER, kinds.POLYGON, ((ring(PERIMETER),),)),
            row(T.UNTOUCHABLE, kinds.POLYGON, ((ring(TOWER),),)),
            row(T.NO_CUT, kinds.POLYGON, ((ring(POND),),)),
            row(T.REQUIRES_ACCESS, kinds.LINE,
                ((np.array([(WEST + x, SOUTH + y) for x, y in TRACK]),),)),
            row(T.AVOID, kinds.POINT, ((np.array([[WEST + TREE[0], SOUTH + TREE[1]]]),),)),
        ]
        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: BUFFER_M,
                    m.ConstraintParam.WEIGHT: 2.0, m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        edited = cls.cprov.edit_constraints(cls.project, rows, params=declaration,
                                            srs_id=cls.project.record.crs_epsg)
        return {item.ctype.value: str(item.code) for item in edited.constraints}

    @staticmethod
    def set_active(version: Any) -> None:
        assert bpy.ops.geoblender.core_set_active_version(
            version_uid="" if version is None else version.uid) == {"FINISHED"}

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        i18n = _module("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def origin(self) -> Any:
        return self.project.origin

    def local(self, x: float, y: float) -> tuple[float, float]:
        """Unas coordenadas locales de la prueba (desde el SO de la ventana) respecto al
        GeoOrigin del proyecto."""
        return (WEST + x - self.origin.x0, SOUTH + y - self.origin.y0)

    def files(self) -> dict[str, str]:
        """Los ficheros del proyecto con su hash (lo que activar la superposición no cambia)."""
        root = Path(self.project.root)
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix != ".gpkg-journal"}

    def operations(self) -> int:
        with self.project.read() as conn:
            return int(conn.execute("SELECT count(*) FROM gb_operation").fetchone()[0])

    def pump(self) -> Any:
        """Los pasos de la construcción, uno por llamada del temporizador (en ``blender -b`` no
        corren) hasta que acaba: lo construido."""
        for _ in range(MAX_PUMPS):
            if self.ov.tick() is None:
                built = self.ov.built()
                self.assertIsNotNone(built, "la superposición no construyó nada")
                return built
        self.fail("la superposición no acaba de construirse")

    def toggle(self) -> set[str]:
        return bpy.ops.geoblender.core_toggle_constraints_overlay()

    def compile_masks(self, version: Any) -> None:
        """La compilación de ``version`` como la lanzará la orden (``begin_compile`` y sus pasos
        hasta el final)."""
        handle = self.masks_store.begin_compile(self.project, version=version.uid)
        for _step in self.masks_store.compile_run(self.project, handle):
            pass
        self.project.refresh_header()

    def outline(self, built: Any, ctype: str) -> Any:
        batch = built.batch(ctype, self.ov.OUTLINE)
        self.assertIsNotNone(batch, f"sin contorno de {ctype}")
        return batch

    def legend_texts(self, built: Any) -> list[str]:
        return [row.text for row in built.legend]

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_is_real_and_in_the_012_entry(self) -> None:
        """RF-012-18, D-38: el control 30 es una orden real (no la provisional) de la entrada
        «012», de tipo «T», en Diseño ▸ Límites y restricciones y en el menú del contexto de las
        restricciones; sin proyecto, no está disponible y dice por qué."""
        cat = self.commands.catalog()
        command = cat.commands[TOGGLE]
        self.assertEqual((command.entry, command.action), (ENTRY, "T"))
        cls = self.commands.registered_class(TOGGLE)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls.bl_label, (command.label, command.label_es))
        design = cat.menus["GEOBLENDER_MT_ui_design"]
        self.assertIn(TOGGLE, [item.key for item in design.groups[0].items])
        with mock.patch.object(self.ps, "current", return_value=None):
            self.assertFalse(cls.poll(bpy.context))
        self.assertTrue(cls.poll(bpy.context))

    def test_b_activating_builds_the_outlines_without_writing(self) -> None:
        """RF-012-18, RNF-012-06 (HU-012-1 a 4; D-30): activar el control 30 pone el manejador y
        construye por pasos un lote de contornos por tipo, con el color del tipo, a la cota del
        GeoOrigin (sin superficie), con los nombres y una leyenda con una fila por tipo; sin
        máscaras compiladas dice que solo se ven los contornos. No escribe en el proyecto (sus
        ficheros, bit a bit, y sus operaciones no cambian). Volver a pulsarlo lo quita todo."""
        ov = self.ov
        files, operations = self.files(), self.operations()
        self.assertFalse(ov.enabled())
        self.assertEqual(self.toggle(), {"FINISHED"})
        self.assertTrue(ov.enabled() and ov.drawing() and ov.building())
        self.assertTrue(getattr(bpy.context.window_manager, WM_PROPERTY))
        built = self.pump()
        self.assertFalse(ov.building())
        self.assertEqual((built.version_code, built.masks), ("V01", "missing"))
        for ctype in TYPES:
            with self.subTest(tipo=ctype):
                batch = self.outline(built, ctype)
                self.assertEqual(batch.segments, OUTLINE_SEGMENTS[ctype])
                self.assertEqual(batch.positions.shape, (2 * OUTLINE_SEGMENTS[ctype], 3))
                self.assertEqual(batch.positions.dtype, np.float32)
                red, green, blue = self.styles.COLORS[self.cmodel.ConstraintType(ctype)]
                self.assertEqual(tuple(round(c * 255) for c in batch.color[:3]),
                                 (red, green, blue))
                self.assertTrue(np.all(batch.positions[:, 2] == 0.0))  # la cota del GeoOrigin (Z0 = 0)
        tower = self.outline(built, "untouchable").positions[:, :2]
        left, bottom = self.local(TOWER[0], TOWER[1])
        right, top = self.local(TOWER[2], TOWER[3])
        self.assertEqual((tower.min(axis=0).tolist(), tower.max(axis=0).tolist()),
                         ([left, bottom], [right, top]))
        point = self.outline(built, "avoid").positions[:, :2]
        x, y = self.local(*TREE)
        self.assertEqual(point.min(axis=0).tolist(), [x - self.ov.POINT_ARM_M, y - self.ov.POINT_ARM_M])
        self.assertEqual({label.text for label in built.labels}, set(NAMES.values()))
        legend = self.legend_texts(built)
        self.assertEqual(legend[0], "Restricciones y límites · V01")
        for ctype in TYPES:
            label = self.cmodel.ConstraintType(ctype).label("es")
            self.assertIn(f"{label} (1)", legend)
        self.assertIn("Máscaras sin compilar: solo contornos", legend)
        self.assertIn("A la cota del GeoOrigin", legend)
        self.assertEqual({row.color for row in built.legend[1:7]},
                         {"#%02x%02x%02x" % self.styles.COLORS[self.cmodel.ConstraintType(t)]
                          for t in TYPES})
        self.assertEqual([batch for batch in built.batches if batch.role != ov.OUTLINE], [])
        self.assertEqual(self.files(), files)
        self.assertEqual(self.operations(), operations)
        self.assertEqual(self.toggle(), {"FINISHED"})
        self.assertFalse(ov.enabled() or ov.drawing() or ov.building())
        self.assertIsNone(ov.built())
        self.assertFalse(getattr(bpy.context.window_manager, WM_PROPERTY))
        self.assertFalse(bpy.app.timers.is_registered(ov.tick))

    def test_c_compiled_masks_show_the_zones_the_domain_and_the_strip(self) -> None:
        """RF-012-18: con las máscaras de V01 compiladas, la superposición rehace sus lotes (al
        avisar de que el proyecto cambió): las zonas de los tipos con resguardo rayadas con su
        color (y la banda hacia dentro del límite legal con el suyo; no el interior de los
        límites), el dominio por defecto y la franja de solo relleno, con su leyenda. Cada raya
        cae dentro de la zona (la caja ampliada con su resguardo). Compilar con la superposición
        activa la rehace, y sigue sin escribir nada por ella."""
        ov = self.ov
        self.assertEqual(self.toggle(), {"FINISHED"})
        self.assertEqual(self.pump().masks, "missing")
        self.compile_masks(self.v01)
        files, operations = self.files(), self.operations()
        ov.on_project_read(self.project)
        self.assertTrue(ov.building())
        built = self.pump()
        self.assertEqual(built.masks, "current")
        for ctype, box in (("untouchable", TOWER), ("no_cut", POND)):
            with self.subTest(zona=ctype):
                zone = built.batch(ctype, ov.ZONE)
                self.assertIsNotNone(zone)
                self.assertGreater(zone.segments, 0)
                reach = BUFFER_M + STEP_M  # la celda que lo toca entera, hasta una celda más
                x0, y0 = self.local(box[0] - reach, box[1] - reach)
                x1, y1 = self.local(box[2] + reach, box[3] + reach)
                xy = zone.positions[:, :2]
                self.assertTrue(np.all((xy[:, 0] >= x0 - 1e-3) & (xy[:, 0] <= x1 + 1e-3)))
                self.assertTrue(np.all((xy[:, 1] >= y0 - 1e-3) & (xy[:, 1] <= y1 + 1e-3)))
                self.assertTrue(np.all(xy[0::2, 1] == xy[1::2, 1]))  # rayas horizontales
        self.assertIsNotNone(built.batch("requires_access", ov.ZONE))
        self.assertIsNotNone(built.batch("avoid", ov.ZONE))
        inner = built.batch("legal_limit", ov.ZONE)
        self.assertIsNotNone(inner, "la banda hacia dentro del límite legal")
        self.assertIsNone(built.batch("action_perimeter", ov.ZONE))
        domain, strip = built.batch(ov.DOMAIN, ov.DOMAIN), built.batch(ov.STRIP, ov.STRIP)
        self.assertGreater(domain.segments, 0)
        self.assertGreater(strip.segments, 0)
        legend = self.legend_texts(built)
        self.assertIn("Dominio por defecto", legend)
        self.assertIn("Franja de solo relleno", legend)
        self.assertNotIn("Máscaras sin compilar: solo contornos", legend)
        self.assertEqual(self.files(), files)
        self.assertEqual(self.operations(), operations)

    def test_d_changing_the_active_version_rebuilds_it(self) -> None:
        """RF-012-18: cambiar de versión activa rehace la superposición con la de la nueva (V02
        no tiene máscaras compiladas: solo contornos); volver a V01 devuelve las zonas."""
        ov = self.ov
        self.assertTrue(ov.enabled())
        self.set_active(self.v02)
        self.assertTrue(ov.building())
        built = self.pump()
        self.assertEqual((built.version_code, built.masks), ("V02", "missing"))
        self.assertEqual([batch.role for batch in built.batches if batch.role != ov.OUTLINE], [])
        self.assertIn("Restricciones y límites · V02", self.legend_texts(built))
        self.set_active(self.v01)
        built = self.pump()
        self.assertEqual((built.version_code, built.masks), ("V01", "current"))
        self.assertIsNotNone(built.batch("untouchable", ov.ZONE))
        # Un aviso del proyecto sin nada nuevo no rehace nada.
        ov.on_project_read(self.project)
        self.assertFalse(ov.building())

    def test_e_the_stamp_follows_what_the_overlay_shows(self) -> None:
        """RF-012-18: lo que decide rehacer cambia con la versión, con el estado de las máscaras
        (obsoletas al cambiar un resguardo: solo contornos y lo dice) y con las operaciones nuevas, y
        no con leer."""
        ov = self.ov
        first = ov.stamp(self.project, self.v01.uid)
        self.assertEqual(ov.stamp(self.project, self.v01.uid), first)
        self.assertNotEqual(ov.stamp(self.project, self.v02.uid), first)
        store = _module("core.params").ParameterStore(self.project)
        key = _module("core.constraints.params").buffer_out_key(self.codes["untouchable"])
        with self.project.write_transaction() as conn:
            store.change(conn, key, value=BUFFER_M + 2.0, kind="HIPÓTESIS",
                         source="Criterio de la prueba", source_kind="person",
                         decided_by=PERSON, reason=REASON)
        self.project.refresh_header()
        self.assertNotEqual(ov.stamp(self.project, self.v01.uid), first)
        ov.on_project_read(self.project)
        built = self.pump()
        self.assertEqual(built.masks, "stale")
        self.assertIn("Máscaras obsoletas: compílelas para ver las zonas",
                      self.legend_texts(built))
        self.assertEqual([batch.role for batch in built.batches if batch.role != ov.OUTLINE], [])
        self.compile_masks(self.v01)  # compilar las rehace
        ov.on_project_read(self.project)
        self.assertEqual(self.pump().masks, "current")

    def test_f_drapes_on_the_chosen_surface_or_the_latest_grid(self) -> None:
        """RF-012-18 (plan §5.5): sobre la superficie elegida en la ventana Restricciones…, o
        por defecto la rejilla del proyecto más reciente, los contornos siguen su cota (una
        pendiente de 0,1 al este desde 100 m) y los segmentos largos se parten para que la
        sigan; el nombre de una superficie que ya no está se olvida (la más reciente); sin
        ninguna, a la cota del GeoOrigin."""
        ov = self.ov
        name = type(self).terrain = self.write_terrain()
        self.assertTrue(ov.enabled())
        self.assertEqual(self.pump().surface, "")  # el dato nuevo no lo rehizo solo...
        ov.on_project_read(self.project)  # ...pero sí su operación nueva
        built = self.pump()
        self.assertEqual(built.surface, name)
        self.assert_draped(built)
        self.assertIn(f"Sobre la superficie «{name}»", self.legend_texts(built))
        self.assertNotIn("A la cota del GeoOrigin", self.legend_texts(built))
        track = self.outline(built, "requires_access")
        self.assertGreater(track.segments, 1)  # el camino de 46 m, partido
        view = getattr(bpy.context.window_manager, VIEW_PROPERTY)
        view.overlay_surface = "no existe"
        self.assertEqual(self.pump().surface, name)
        view.overlay_surface = name
        self.assertEqual(self.pump().surface, name)
        self.assert_draped(self.ov.built())

    def write_terrain(self) -> str:
        """Una rejilla del proyecto de 30 × 30 celdas de 2 m con una pendiente de 0,1 hacia el
        este desde 100 m en su borde oeste, como la deja «Rejilla del proyecto desde un MDT»; el
        nombre de su dato."""
        grid_mod, raster_mod = _module("gis.grid"), _module("gis.raster")
        crs, vertical = self.gis_store.project_references(self.project)
        cells = int(SIZE_M / STEP_M)
        grid = grid_mod.Grid(WEST, SOUTH + SIZE_M, STEP_M, STEP_M, cells, cells)
        x, _y = grid.centers()
        values = 100.0 + 0.1 * (x - WEST)
        handle = _module("core.provenance.operations").begin_operation(
            self.project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Terreno"},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with self.gis_store.ResultWriter(self.project, handle) as out:
            out.raster("Terreno", raster_mod.Raster(grid, values, crs, vertical))
            (record,) = out.commit(software={library: library_version}, message=REASON)
        self.project.refresh_header()
        return str(record.name)

    def assert_draped(self, built: Any) -> None:
        """Cada vértice de los contornos está en la cota de la pendiente (float32, 1 mm)."""
        batches = [batch for batch in built.batches if batch.role == self.ov.OUTLINE]
        self.assertEqual(len(batches), len(TYPES))
        for batch in batches:
            east = batch.positions[:, 0].astype(np.float64) + self.origin.x0
            expected = 100.0 + 0.1 * (east - WEST) - self.origin.z0
            self.assertTrue(np.allclose(batch.positions[:, 2], expected, atol=2e-3),
                            f"{batch.key}: {batch.positions[:, 2]} frente a {expected}")

    def test_g_what_is_drawn_in_pixels(self) -> None:
        """RF-012-18, RNF-012-05: en píxeles de la región, los nombres que caben (cada uno junto a
        su sitio, con el color de su tipo y no los que quedan fuera de la vista) y la leyenda en
        la esquina de abajo a la derecha (su fondo, un cuadro de color y un texto por tipo y los
        títulos sin cuadro), sin pasar de :data:`MAX_LABELS` nombres."""
        ov, pixels = self.ov, _module("bl.draw.dh_overlay")
        built = ov.built()
        centre = self.local(30.0, 30.0)
        matrix = top_view(centre)
        items = ov.screen_items(built, matrix, SIZE, measure=lambda text: 7.0 * len(text),
                                scale=1.0)
        texts = [item for item in items if isinstance(item, pixels.Text)]
        shown = {item.text: item for item in texts}
        for name in NAMES.values():
            self.assertIn(name, shown)
        tower = shown[NAMES["untouchable"]]
        sx, sy = pixels.to_screen([(*self.local(23.0, 23.0), 0.0)], matrix, SIZE)[0]
        self.assertAlmostEqual(tower.x, sx, delta=ov.LABEL_OFFSET[0] + 1.0)
        self.assertAlmostEqual(tower.y, sy, delta=ov.LABEL_OFFSET[1] + 1.0)
        red, green, blue = self.styles.COLORS[self.cmodel.ConstraintType.UNTOUCHABLE]
        self.assertEqual(tuple(round(c * 255) for c in tower.color[:3]), (red, green, blue))
        boxes = [item for item in items if isinstance(item, pixels.Box)]
        self.assertGreaterEqual(len(boxes), 1 + len(TYPES))
        panel = boxes[0]
        self.assertEqual(panel.x1, SIZE[0] - pixels.MARGIN_PX + pixels.PAD_PX)  # a la derecha
        self.assertEqual(panel.y0, pixels.MARGIN_PX - pixels.PAD_PX)  # abajo
        self.assertGreater(panel.x0, 0.0)
        self.assertLess(panel.y1, SIZE[1])
        legend = [item for item in texts if item.x >= panel.x0]
        self.assertIn("Restricciones y límites · V01", [item.text for item in legend])
        far = ov.screen_items(built, top_view((900.0, 900.0)), SIZE,
                              measure=lambda text: 7.0 * len(text), scale=1.0)
        self.assertEqual([item.text for item in far if isinstance(item, pixels.Text)
                          and item.text in NAMES.values()], [])  # ninguno cabe
        many = ov.Built(version_uid=None, version_code="", masks="", surface="", batches=(),
                        labels=tuple(ov.Label(f"R{n}", (float(n % 10), float(n // 10), 0.0),
                                              (1.0, 1.0, 1.0, 1.0)) for n in range(500)),
                        legend=(), stamp=())
        placed = ov.screen_items(many, top_view((5.0, 25.0)), SIZE, measure=len, scale=1.0)
        self.assertEqual(len(placed), ov.MAX_LABELS)

    def test_h_the_batches_are_drawn_one_by_one_and_gpu_is_left_as_it_was(self) -> None:
        """RF-012-18, RNF-012-05: dibujar crea un lote de ``gpu`` por lote de segmentos (una sola
        vez: el redibujo reutiliza los lotes), con el grosor de su papel y la vista acercada a la
        cámara, y deja el estado de ``gpu`` como estaba."""
        ov = self.ov
        built = ov.built()
        gpu = mock.MagicMock()
        gpu.state.depth_test_get.return_value = "NONE"
        gpu.state.depth_mask_get.return_value = True
        gpu.state.blend_get.return_value = "NONE"
        with mock.patch.object(ov, "gpu", gpu), mock.patch.object(ov, "batch_for_shader") as make:
            drawn = ov.draw_lines(built, view_matrix=Matrix.Identity(4),
                                  projection_matrix=Matrix.Identity(4), perspective=True,
                                  view_distance=100.0, viewport_size=(400.0, 300.0),
                                  pixel_size=1.0)
            self.assertEqual(drawn, len(built.batches))
            self.assertEqual(make.call_count, len(built.batches))
            make.reset_mock()
            self.assertEqual(ov.draw_lines(built, view_matrix=Matrix.Identity(4),
                                           projection_matrix=Matrix.Identity(4),
                                           perspective=False, view_distance=100.0,
                                           viewport_size=(400.0, 300.0), pixel_size=2.0), drawn)
            make.assert_not_called()  # los lotes de gpu ya estaban
        gpu.state.depth_test_set.assert_called_with("NONE")
        gpu.state.depth_mask_set.assert_called_with(True)
        gpu.state.blend_set.assert_called_with("NONE")
        widths = {call.args[1] for call in gpu.shader.from_builtin.return_value.uniform_float
                  .call_args_list if call.args[0] == "lineWidth"}
        self.assertTrue(widths <= {ov.OUTLINE_PX, ov.LIMIT_PX, ov.HATCH_PX,
                                   2 * ov.OUTLINE_PX, 2 * ov.LIMIT_PX, 2 * ov.HATCH_PX})

    def test_i_switching_to_blender_or_closing_the_project_removes_it(self) -> None:
        """RF-012-18: conmutar a la interfaz de Blender quita la superposición (el manejador, los
        lotes y los avisos) y volver a Geoblender no la pone sola; cerrar el proyecto también la
        quita; la propiedad de la ventana la activa y la desactiva."""
        ov, switcher = self.ov, self.switcher
        self.assertTrue(ov.enabled())
        self.assertIn(ov.disable, switcher.blender_hooks())
        window = bpy.context.window_manager.windows[0]
        self.addCleanup(switcher.forget)
        # La ventana está «en Geoblender» (su espacio de trabajo, marcado) y se conmuta a Blender.
        with mock.patch.object(switcher, "_marked", return_value={window.workspace.name}):
            self.assertTrue(switcher.toggle(window, "BLENDER").workspace)
        self.assertFalse(ov.enabled() or ov.drawing() or ov.building())
        self.assertIsNone(ov.built())
        self.assertFalse(getattr(bpy.context.window_manager, WM_PROPERTY))
        # Lo que queda apuntado es lo de la cola de avisos (spec 019, T22), que no se quita al conmutar.
        self.assertEqual([hook for hook in switcher.blender_hooks()
                          if not hook.__module__.endswith("bl.ui.notices")], [])
        # Y se vuelve a Geoblender (a otro espacio marcado): no la pone sola.
        other = next(space.name for space in bpy.data.workspaces
                     if space.name != window.workspace.name)
        with mock.patch.object(switcher, "_marked", return_value={other}):
            self.assertEqual(switcher.toggle(window, "GEOBLENDER").workspace, other)
        self.assertFalse(ov.enabled())
        # La propiedad de la ventana la activa; cerrar el proyecto de la sesión la quita.
        setattr(bpy.context.window_manager, WM_PROPERTY, True)
        self.assertTrue(ov.enabled() and ov.drawing())
        self.pump()
        self.assertIn(ov.on_project_changed, self.ps.listeners())
        self.ps.listeners()[self.ps.listeners().index(ov.on_project_changed)](None)
        self.assertFalse(ov.enabled() or ov.drawing() or ov.building())
        self.assertFalse(getattr(bpy.context.window_manager, WM_PROPERTY))
        self.assertNotIn(ov.on_project_changed, self.ps.listeners())

    def test_j_the_hatch_of_a_zone_and_the_colors_of_the_types(self) -> None:
        """RF-012-18: las rayas de una zona (``hatch_segments``) van por el centro de las celdas
        de las filas elegidas, con a lo sumo las pedidas y por tramo de fila; una zona vacía no da
        ninguna. Los once tipos de restricción tienen un color cada uno, todos distintos entre sí
        y del violeta de las intenciones del cliente, y la superposición dibuja con ellos."""
        ov = self.ov
        grid = _module("gis.grid").Grid(1000.0, 2000.0, 2.0, 2.0, 40, 30)
        runs_mod = _module("gis.masks.zones")
        mask = np.zeros(grid.shape, dtype=bool)
        mask[2:22, 5:15] = True
        mask[2:22, 20:25] = True
        found = ov.hatch_segments(runs_mod.Runs.from_mask(mask), grid, 4)
        self.assertEqual(found.shape[1:], (2, 2))
        rows = np.unique((2000.0 - found[:, 0, 1]) / 2.0 - 0.5).astype(int)
        self.assertLessEqual(len(rows), 4)
        self.assertEqual(rows[0], 2)
        self.assertTrue(set(rows) <= set(range(2, 22)))
        first = found[found[:, 0, 1] == found[0, 0, 1]]
        self.assertEqual(first[:, :, 0].tolist(), [[1010.0, 1030.0], [1040.0, 1050.0]])
        self.assertEqual(ov.hatch_segments(runs_mod.Runs.empty(), grid, 4).shape, (0, 2, 2))
        every = ov.hatch_segments(runs_mod.Runs.from_mask(mask[:, :6] & mask[:, :6]), grid, 100)
        self.assertEqual(len(every), 20)  # menos filas que rayas: una por fila
        colors = {ctype: ov.color_of(ctype.value) for ctype in self.cmodel.ConstraintType}
        self.assertEqual(len(set(colors.values())), 11)
        palette = list(colors.values()) + [ov.color_of(ov.DOMAIN), ov.color_of(ov.STRIP)]
        for index, first_color in enumerate(palette):
            for other in palette[index + 1:]:
                gap = float(np.linalg.norm(np.array(first_color[:3]) - np.array(other[:3])))
                self.assertGreater(gap, 0.15, f"{first_color} y {other} se confunden")
            self.assertGreater(float(np.linalg.norm(np.array(first_color[:3])
                                                    - np.array(VIOLET))), 0.25)

    def test_k_the_window_offers_the_surface_and_the_switch(self) -> None:
        """RF-012-18 (plan §5.5): la ventana Restricciones… ofrece el control (el botón de la
        orden, pulsado mientras está activa) y la superficie sobre la que dibujar, con las
        rejillas del proyecto, sin que leer cambie nada."""
        ov, panels = self.ov, _module("bl.ui.constraint_panels")
        self.assertFalse(ov.enabled())
        panels.fill_constraints(self.project)
        view = getattr(bpy.context.window_manager, VIEW_PROPERTY)
        self.assertEqual([item.name for item in view.overlay_surfaces], [self.terrain])

        def window() -> Any:
            layout = draw(getattr(bpy.types, panels.CONSTRAINTS_PANEL), bpy.context)
            (button,) = [item for item in layout.of_kind("operator") if item.target == TOGGLE]
            searches = [item.text for item in layout.of_kind("prop_search")]
            return button, searches

        button, searches = window()
        self.assertEqual(button.text, "Ver restricciones y límites")
        self.assertFalse(button.options["depress"])
        self.assertIn("Dibujar sobre la superficie", searches)
        ov.enable()
        self.addCleanup(ov.disable)
        self.assertTrue(window()[0].options["depress"])
        ov.disable()
        self.assertFalse(window()[0].options["depress"])

    def test_z_disabling_geoblender_with_the_overlay_on_leaves_nothing(self) -> None:
        """Principio 8: con la superposición activa, desactivar Geoblender quita el manejador
        de dibujo, los avisos, el temporizador y los lotes, y la huella de Blender vuelve a la
        del principio de la sesión."""
        ov = self.ov
        self.assertEqual(self.toggle(), {"FINISHED"})
        self.assertTrue(ov.drawing())
        self.assertTrue(bpy.app.timers.is_registered(ov.tick))  # la construcción, sin acabar
        blender_ext.release()
        self.assertFalse(ov.enabled() or ov.drawing() or ov.building())
        self.assertIsNone(ov.built())
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(),
                                                      blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
