# SPDX-License-Identifier: GPL-3.0-or-later
"""Vista previa de semillas, dominios y restricciones (spec 013, T25; HU-013-1; RF-013-01,
RF-013-02, RF-013-03, RF-013-33; RNF-013-05; plan 013 §5.5, D-29; comprobación manual M1; principio 8).

La vista previa de la Vista 3D (``bl.draw.design``, ``geoblender.des_toggle_preview``) es un manejador
de dibujo sin objetos ni escritura: lo que dibuja se prueba en sus lotes (los puntos de las
semillas con su color por cota, las rayas del dominio, el borde de los sectores, los contornos de las
restricciones) y en sus textos en píxeles (el resumen, la leyenda y los nombres), no en píxeles de
pantalla (``docs/trampas.md`` §3: sin GPU en ``blender -b``). Un proyecto por clase (ventana de
60 × 60 m con celdas de 2 m, V01 y V02, un límite legal, un perímetro y una torre, dos sectores con la
búsqueda de intocables cerrada solo en el primero, y una ladera que sube 0,1 m por metro al este desde
100 m) y las pruebas, en el orden de sus letras sobre el mismo estado:

- RF-013-33 (a): la orden es la real (no la provisional), con el ``poll`` de las órdenes de Diseño
  (dice por qué no está disponible), salvo para quitar la vista previa; la propiedad de la ventana la
  activa y la quita; su diálogo propone la primera superficie y dibuja lo que se previsualiza.
- RF-013-03 (b): sin las máscaras compiladas solo se ven los contornos de las restricciones y el
  resumen lo dice; no escribe nada en el proyecto (sus ficheros, bit a bit, y sus operaciones no
  cambian) y quitarla lo quita todo.
- RF-013-01, RF-013-02, RF-013-03 (c): con las máscaras compiladas, las semillas del sector 1 (una por
  celda, en su cota y coloreadas por ella), el dominio de trabajo en trama sobre la ladera, el borde de
  los dos sectores (el segundo, en ámbar, con su búsqueda pendiente) y el resumen son los de
  ``design`` en el idioma de Geoblender, con los avisos en alerta.
- RF-013-03, RNF-013-05 (d): «semillas en toda la ladera»: el aviso de las semillas fuera del dominio y
  su aclarado cuando pasan del tope de puntos.
- RF-013-03, RNF-013-05 (e): en píxeles, el resumen arriba a la izquierda (partido al ancho, los
  avisos en ámbar), la leyenda y los nombres; el dibujo de los puntos y de las líneas con ``gpu`` (un
  lote cada uno, creado una vez) deja su estado como estaba.
- RF-013-03 (f): cambiar de versión activa la rehace; conmutar a la interfaz de Blender o cerrar el
  proyecto la quita.
- RF-013-33 (g): el diálogo y la orden rechazan lo que falta (la cota fija, los sectores marcados) sin
  activarla y quitarla informa; una vista previa que el cálculo rechaza avisa con el motivo y se quita.
- Principio 8 (z): desactivar Geoblender con la vista previa activa quita el manejador, los avisos y
  el temporizador y deja la huella de Blender como al principio de la sesión.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import importlib
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np
from mathutils import Matrix

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import remove_tree

TOGGLE = "geoblender.des_toggle_preview"
WM_PROPERTY = "geoblender_design_preview"
VIEW_PROPERTY = "geoblender_design"
REASON = "Prueba de la vista previa del diseño"
PERSON = "Samuel (IMGA)"
CLOSED_AT = "2026-11-03T10:00:00Z"
WEST = 700_000.0
SOUTH = 4_400_000.0
SIZE_M = 60.0
STEP_M = 2.0
LEGAL = (4.0, 4.0, 52.0, 52.0)
PERIMETER = (2.0, 2.0, 56.0, 56.0)
TOWER = (20.0, 20.0, 26.0, 26.0)
SECTORS = {"Sector 1": (2.0, 2.0, 30.0, 56.0), "Sector 2": (30.0, 2.0, 56.0, 56.0)}
SEEDS_IN_SECTOR_1 = 14 * 27  # centros de celda (x = 3, 5 … 29; y = 3, 5 … 55) dentro del sector 1
SIZE = (600, 400)  # la región, en píxeles
HALF = 60.0  # la vista desde arriba: 120 m de ancho
MAX_PUMPS = 20_000


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


class DesignPreviewTest(unittest.TestCase):
    """La extensión habilitada una vez y un proyecto con V01 y V02, tres restricciones, dos sectores
    (el segundo con la búsqueda pendiente) y una ladera para toda la clase (las pruebas, en el orden
    de sus letras: cada una parte de lo que dejó la anterior)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-d25-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.commands = _module("bl.ui.commands")
        cls.switcher = _module("bl.ui.switcher")
        cls.des_ops = _module("bl.ops.des")
        cls.panels = _module("bl.ui.des_panels")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.masks_store = _module("gis.masks.store")
        cls.dmodel = _module("design.model")
        cls.dsteps = _module("design.steps")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + SIZE_M, SOUTH + SIZE_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = store.create_version(conn, cls.project, feature="diseno",
                                                      title="Diseño", reason=REASON)
            cls.v02, _revision = store.create_version(conn, cls.project, feature="alternativa",
                                                      title="Alternativa", reason=REASON)
        cls.project.refresh_header()
        cls.declare()
        cls.declare_sectors()
        cls.close_search("sector_1", 1)
        cls.ground = cls.write_slope("Ladera")
        cls.flat = cls.write_slope("Plana", base=50.0, rise=0.0)  # la más reciente, no la de las semillas
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        cls.set_active(cls.v01)
        cls.panels.fill_sectors(cls.project)  # las zonas «sector:…» del diálogo salen de aquí
        cls.panels.refresh_choices(cls.project)
        cls.design = _module("bl.draw.design")
        cls.constraints = _module("bl.draw.constraints")

    @classmethod
    def declare(cls) -> None:
        """El límite legal, el perímetro de actuación y una torre intocable (como las dejará la
        orden de la 012)."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 3), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        rows = [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                row(types.ACTION_PERIMETER, "Perímetro", PERIMETER),
                row(types.UNTOUCHABLE, "Torre", TOWER)]
        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: 2.0, m.ConstraintParam.BUFFER_OUT: 2.0,
                    m.ConstraintParam.WEIGHT: 2.0, m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, rows, params=declaration,
                                   srs_id=cls.project.record.crs_epsg)

    @classmethod
    def declare_sectors(cls) -> None:
        """Los dos sectores de búsqueda (``core_sector``), como los dejará «Declarar de nuevo desde
        una capa…»."""
        sectors = tuple(
            cls.cmodel.Sector(f"sector{index}{'0' * 26}", f"sector_{index}", name, (ring(box),))
            for index, (name, box) in enumerate(SECTORS.items(), start=1))
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        with cls.project.write_transaction() as conn:
            cls.cstore.write_sectors(conn, sectors, srs_id=cls.project.record.crs_epsg)
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Sectores de prueba")

    @classmethod
    def close_search(cls, code: str, minutes: int) -> None:
        """Cierra la búsqueda de intocables de un sector (con su huella): queda sin la marca de
        pendiente."""
        with cls.project.read() as conn:
            (sector,) = [item for item in cls.cstore.read_sectors(conn) if item.code == code]
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, "core.edit_constraints", settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(f"search{minutes}{'0' * 25}", handle.uid, code,
                                         cls.cstore.sector_sha256(sector), 25.0, PERSON, CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

    @classmethod
    def write_slope(cls, name: str, *, base: float = 100.0, rise: float = 0.1) -> str:
        """Una rejilla del proyecto de la ventana que sube ``rise`` m por metro al este desde
        ``base`` m (como la deja «Rejilla del proyecto desde un MDT»); el nombre de su dato."""
        gis_store = _module("gis.store")
        record = cls.project.record
        grid = _module("gis.grid").project_grid(record.window, float(record.grid_step_m))
        crs, vertical = gis_store.project_references(cls.project)
        x, _y = grid.centers()
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": name},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.raster(name, _module("gis.raster").Raster(grid, base + rise * (x - WEST), crs,
                                                          vertical))
            records = out.commit(software={library: library_version}, message=REASON)
        return str(records[0].name)

    @staticmethod
    def set_active(version: Any) -> None:
        assert bpy.ops.geoblender.core_set_active_version(
            version_uid="" if version is None else version.uid) == {"FINISHED"}

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def tearDown(self) -> None:
        if self.design.enabled():  # lo que deja una prueba que falla no pasa a la siguiente
            self.design.disable()

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def origin(self) -> Any:
        return self.project.origin

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    def local(self, x: float, y: float) -> tuple[float, float]:
        """Unas coordenadas de la prueba (desde el SO de la ventana) respecto al GeoOrigin."""
        return (WEST + x - self.origin.x0, SOUTH + y - self.origin.y0)

    def files(self) -> dict[str, str]:
        """Los ficheros del proyecto con su hash (lo que la vista previa no cambia)."""
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
            if self.design.tick() is None:
                built = self.design.built()
                self.assertIsNotNone(built, "la vista previa no construyó nada")
                return built
        self.fail("la vista previa no acaba de construirse")

    def show(self, **values: Any) -> set[str]:
        """Lanza la orden (sin diálogo) sobre la ladera con lo pedido en ``values``."""
        form = {"seeds_from": "SURFACE", "surface": self.ground, "zone": "none", **values}
        return bpy.ops.geoblender.des_toggle_preview("EXEC_DEFAULT", **form)

    def compile_masks(self, version: Any) -> None:
        """La compilación de ``version`` como la lanzará la orden (``begin_compile`` y sus pasos
        hasta el final)."""
        handle = self.masks_store.begin_compile(self.project, version=version.uid)
        for _step in self.masks_store.compile_run(self.project, handle):
            pass
        self.project.refresh_header()

    def truth(self, plan: Any, version: Any | None = None) -> Any:
        """Lo que dice ``design`` de ``plan`` (``design.steps.preview_steps``), sin pasar por el
        dibujo."""
        found = None
        for step in self.dsteps.preview_steps(self.project, plan, (version or self.v01).uid):
            found = step.result if step.result is not None else found
        return found

    def sector_1_plan(self) -> Any:
        return self.design.Plan(self.dmodel.SeedSource(self.dmodel.SeedKind.SURFACE,
                                                       surface=self.ground,
                                                       zone=self.dmodel.Zone(
                                                           self.dmodel.ZoneKind.SECTOR,
                                                           "sector_1")))

    def legend_texts(self, built: Any) -> list[str]:
        return [row.text for row in built.lines.legend]

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_command_is_real_and_available_as_the_design_commands(self) -> None:
        """RF-013-33, D-29: «Vista previa de semillas, dominios y restricciones» es una orden real (no
        la provisional) con el ``poll`` de las de Diseño: dice por qué no está disponible (sin
        proyecto, en solo lectura o con la versión activa no editable), pero con la vista previa
        activa siempre se puede quitar; la propiedad de la ventana la activa (sobre la primera
        rejilla) y la quita; su diálogo propone la primera superficie y dibuja lo que se
        previsualiza."""
        cls = self.commands.registered_class(TOGGLE)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_ops.classes)
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.provenance_op_type, cls.bl_options), ("des.envelope", {"REGISTER"}))
        command = self.commands.catalog().commands[TOGGLE]
        self.assertEqual((command.entry, command.action), ("R-33", "T"))  # la T26 la pasa a «013»
        self.assertEqual(command.label_es, "Vista previa de semillas, dominios y restricciones")
        self.assertTrue(cls.poll(bpy.context))
        for reason in ("Abra un proyecto", "Proyecto en solo lectura: prueba",
                       "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"):
            with mock.patch.object(self.des_ops, "design_unavailable", return_value=reason):
                self.assertFalse(cls.poll(bpy.context), reason)
        self.assertFalse(self.design.enabled())
        self.assertIs(getattr(bpy.context.window_manager, WM_PROPERTY), False)

        setattr(bpy.context.window_manager, WM_PROPERTY, True)  # la primera rejilla, entera
        self.assertTrue(self.design.enabled() and self.design.drawing())
        first = self.panels.surface_items(None, None)[0][0]
        self.assertIn(first, (self.ground, self.flat))
        self.assertEqual((self.design.plan().seeds.surface, self.design.plan().seeds.zone,
                          self.design.plan().domain), (first, None, self.dmodel.WorkDomain()))
        with mock.patch.object(self.des_ops, "design_unavailable", return_value="solo lectura"):
            self.assertTrue(cls.poll(bpy.context))  # quitarla, siempre
        setattr(bpy.context.window_manager, WM_PROPERTY, False)
        self.assertFalse(self.design.enabled() or self.design.drawing() or self.design.building())
        self.assertFalse(bpy.app.timers.is_registered(self.design.tick))

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        values = {"seeds_from": "SURFACE", "surface": "", "zone": "none", "elevation": "",
                  "bound": "ALL", "bound_layer": "none",
                  "properties": SimpleNamespace(is_property_set=lambda name: False)}
        fake = operator_self(cls, report=lambda kind, text: None, **values)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"],
                         "Vista previa de semillas, dominios y restricciones")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Mostrar")
        self.assertEqual(fake.surface, self.ground)
        self.assertFalse(any(item.use for item in self.view.sectors))
        shown = draw(cls, bpy.context, **values).texts()
        for heading in ("Semillas", "Origen de las semillas", "Zona de las semillas", "Acotar a"):
            self.assertIn(heading, shown)
        marked = draw(cls, bpy.context, **{**values, "bound": "SECTORS"})
        self.assertEqual(len([item for item in marked.of_kind("prop") if item.target == "use"]), 2)

    def test_b_without_masks_only_the_constraints_are_shown_and_nothing_is_written(self) -> None:
        """RF-013-03 (M1): con las máscaras de V01 sin compilar la vista previa construye, por pasos,
        los contornos de las restricciones con su leyenda y el resumen dice que no puede mostrar el
        dominio ni las semillas; no escribe nada en el proyecto (los mismos ficheros bit a bit, ninguna
        operación) y deja el resumen en la vista; volver a pulsar el control lo quita todo."""
        design = self.design
        files, operations = self.files(), self.operations()
        self.assertEqual(self.show(), {"FINISHED"})
        self.assertTrue(design.enabled() and design.drawing() and design.building())
        self.assertIs(getattr(bpy.context.window_manager, WM_PROPERTY), True)
        built = self.pump()
        self.assertFalse(design.building())
        self.assertEqual((built.lines.version_code, built.lines.masks), ("V01", "missing"))
        self.assertIsNone(built.seeds)
        self.assertEqual(built.sectors, ())
        self.assertEqual([batch.role for batch in built.lines.batches],
                         [self.constraints.OUTLINE] * 3)
        legend = self.legend_texts(built)
        self.assertEqual(legend[0], "Vista previa · V01")
        self.assertIn("Máscaras sin compilar: solo contornos", legend)
        (text, alert), = built.summary
        self.assertTrue(alert)
        self.assertTrue(text.startswith("Las máscaras de V01 no se han compilado"), text)
        self.assertEqual([(line.name, line.alert) for line in self.view.preview],
                         [(text, True)])
        self.assertEqual(self.files(), files)
        self.assertEqual(self.operations(), operations)
        self.assertEqual(self.show(), {"FINISHED"})  # el mismo control la quita
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        self.assertIsNone(design.built())
        self.assertEqual(len(self.view.preview), 0)
        self.assertFalse(bpy.app.timers.is_registered(design.tick))
        self.assertEqual(self.files(), files)

    def test_c_seeds_domain_sectors_and_summary_come_from_design(self) -> None:
        """RF-013-01, RF-013-02, RF-013-03 (M1): con las máscaras de V01 compiladas y las semillas
        de la ladera en el sector 1: un punto por celda de semilla en su cota (la de la ladera) y
        coloreado por ella (azul la más baja, rojo la más alta), el dominio de trabajo en trama
        sobre la ladera y solo en sus celdas, el borde de cada sector (azul con la búsqueda vigente,
        ámbar el 2, pendiente) con su nombre y su estado, las restricciones y la leyenda; y el resumen
        es el de ``design.preview`` en español y en inglés, con la torre y el sector 2 como avisos. Compilar con la vista
        previa activa la rehace, y no escribe nada por ella."""
        design, constraints = self.design, self.constraints
        self.assertEqual(self.show(zone="sector:sector_1"), {"FINISHED"})
        self.assertEqual(self.pump().lines.masks, "missing")
        self.compile_masks(self.v01)
        files, operations = self.files(), self.operations()
        design.on_project_read(self.project)
        self.assertTrue(design.building())
        built = self.pump()
        self.assertEqual(built.lines.masks, "current")
        self.assertEqual(built.lines.surface, self.ground)

        seeds = built.seeds
        self.assertEqual((seeds.count, seeds.total, seeds.stride), (SEEDS_IN_SECTOR_1,) * 2 + (1,))
        self.assertEqual((seeds.positions.shape, seeds.positions.dtype, seeds.colors.dtype),
                         ((SEEDS_IN_SECTOR_1, 3), np.float32, np.float32))
        east = np.arange(1, 15) * STEP_M + 1.0
        north = np.arange(1, 28) * STEP_M + 1.0
        expected = np.array([(self.local(x, y)[0], self.local(x, y)[1],
                              100.0 + 0.1 * x - self.origin.z0) for x in east for y in north])
        order = np.lexsort((seeds.positions[:, 1], seeds.positions[:, 0]))
        self.assertTrue(np.allclose(seeds.positions[order], expected, atol=1e-4))
        low, high = np.argmin(seeds.positions[:, 2]), np.argmax(seeds.positions[:, 2])
        self.assertTrue(np.allclose(seeds.colors[low], (*design.RAMP[0][1], 1.0), atol=1e-6))
        self.assertTrue(np.allclose(seeds.colors[high], (*design.RAMP[-1][1], 1.0), atol=1e-6))
        self.assertEqual(seeds.size_px, design.SEED_PX)
        self.assertEqual((round(seeds.low, 6), round(seeds.high, 6)), (100.3, 102.9))

        found = self.truth(self.sector_1_plan())  # lo que dice design, sin pasar por el dibujo
        mask = found.domain.mask
        domain = built.lines.batch(constraints.DOMAIN, constraints.DOMAIN)
        self.assertGreater(domain.segments, 0)
        grid = found.seeds.geometry
        xyz = domain.positions.astype(np.float64)
        self.assertTrue(np.all(xyz[0::2, 1] == xyz[1::2, 1]))  # rayas horizontales
        for start, end in zip(xyz[0::2], xyz[1::2], strict=True):  # cada raya cae en el dominio
            row = int(round((grid.north - (start[1] + self.origin.y0)) / grid.dy - 0.5))
            first = int(round((start[0] + self.origin.x0 - grid.west) / grid.dx))
            last = int(round((end[0] + self.origin.x0 - grid.west) / grid.dx))
            self.assertTrue(mask[row, first:last].all(), (row, first, last))
        self.assertTrue(np.allclose(
            xyz[:, 2], 100.0 + 0.1 * (xyz[:, 0] + self.origin.x0 - WEST) - self.origin.z0,
            atol=2e-3))  # sobre la ladera
        self.assertIsNone(built.lines.batch(constraints.STRIP, constraints.STRIP))
        self.assertEqual(sorted(built.sectors), [("Sector 1", False), ("Sector 2", True)])
        plain = built.lines.batch(design.SECTOR, design.SECTOR)
        late = built.lines.batch(design.SECTOR_PENDING, design.SECTOR_PENDING)
        for batch, name in ((plain, "Sector 1"), (late, "Sector 2")):  # su borde, sobre la ladera
            left, bottom, right, top = SECTORS[name]
            xy = batch.positions[:, :2]
            self.assertEqual((xy.min(axis=0).tolist(), xy.max(axis=0).tolist()),
                             ([self.local(left, bottom)[0], self.local(left, bottom)[1]],
                              [self.local(right, top)[0], self.local(right, top)[1]]), name)
            self.assertTrue(np.allclose(
                batch.positions[:, 2],
                100.0 + 0.1 * (batch.positions[:, 0].astype(np.float64) + self.origin.x0 - WEST)
                - self.origin.z0, atol=2e-3))
        self.assertEqual((plain.color, late.color), (design.SECTOR_COLOR, design.PENDING_COLOR))
        self.assertGreater(late.width_px, plain.width_px)
        self.assertEqual(sorted(label.text for label in built.lines.labels
                                if label.text.startswith("Sector")),
                         ["Sector 1 · Búsqueda vigente", "Sector 2 · Búsqueda pendiente"])
        for ctype in ("legal_limit", "action_perimeter", "untouchable"):
            self.assertIsNotNone(built.lines.batch(ctype, constraints.OUTLINE), ctype)
        self.assertIsNotNone(built.lines.batch("untouchable", constraints.ZONE))
        legend = self.legend_texts(built)
        self.assertEqual(legend[:3], ["Vista previa · V01", "Semillas a 100,3 m", "Semillas a 102,9 m"])
        for row in ("Dominio de trabajo", "Sector con la búsqueda vigente",
                    "Sector con la búsqueda pendiente"):
            self.assertIn(row, legend)
        self.assertNotIn("Dominio por defecto", legend)
        self.assertNotIn("Franja de solo relleno", legend)

        self.assertEqual(built.summary, tuple(
            (notice.text("es"), notice.severity == "warning") for notice in found.notices))
        thin = self.i18n.THIN_SPACE
        text = " ".join(line for line, _alert in built.summary)
        self.assertIn(f"Semillas: 378 celdas (1{thin}512 m²), cotas 100,3 a 102,9 m", text)
        self.assertIn("Sector «Sector 2»: búsqueda de intocables pendiente", text)
        self.assertEqual([line.name for line in self.view.preview],
                         [line for line, _alert in built.summary])
        self.assertTrue(any(alert for _line, alert in built.summary))
        self.i18n.set_language("en")
        design.rebuild()
        english = self.pump().summary
        self.assertEqual(english, tuple((notice.text("en"), notice.severity == "warning")
                                        for notice in found.notices))
        self.assertTrue(english[0][0].startswith("Seeds: 378 cells (1,512 m²), elevations 100.3 to "
                                                 "102.9 m"), english[0][0])
        self.assertIn("Seeds at 100.3 m", self.legend_texts(self.design.built()))
        self.assertEqual(self.files(), files)
        self.assertEqual(self.operations(), operations)

    def test_d_seeds_on_the_whole_slope_warn_and_are_thinned(self) -> None:
        """RF-013-03, RNF-013-05 (M1: «semillas en toda la ladera»): con las semillas en toda la
        superficie, el resumen avisa en alerta de las semillas fuera del dominio de trabajo (se
        conservan, con su número y su área) y, con más puntos que el tope, se dibuja uno de cada
        ``stride`` (el primero de cada grupo, en el orden de la rejilla) y la leyenda lo dice."""
        design = self.design
        self.assertEqual(self.show(), {"FINISHED"})
        full = self.pump()
        found = self.truth(design.plan())
        self.assertEqual(full.seeds.count, 900)  # 30 × 30 celdas con cota
        outside = found.seeds.outside_domain
        self.assertGreater(outside, 0)
        warned = [line for line, alert in full.summary if alert and "fuera del dominio" in line]
        (warning,) = warned
        self.assertTrue(warning.startswith(f"{outside} celdas de semilla ("), warning)
        self.assertIn(f"{outside} celdas de semilla fuera del dominio.", full.summary[0][0])
        self.assertNotIn("Semillas aclaradas", " ".join(self.legend_texts(full)))
        design.disable()
        with mock.patch.object(design, "MAX_SEED_POINTS", 128), mock.patch.object(
                design, "SEED_ROWS_PER_STEP", 7):  # 900 / 128 = 7,03: de 8 en 8, en 5 trozos
            self.assertEqual(self.show(), {"FINISHED"})
            thin = self.pump()
        self.assertEqual((thin.seeds.count, thin.seeds.total, thin.seeds.stride), (113, 900, 8))
        self.assertEqual(thin.seeds.positions.shape, (113, 3))
        self.assertIn("Semillas aclaradas: se dibuja 1 de cada 8", self.legend_texts(thin))
        first = thin.seeds.positions[0]  # la primera celda de la rejilla: fila 0, columna 0
        self.assertTrue(np.allclose(first[:2], self.local(1.0, SIZE_M - 1.0), atol=1e-4))
        again = [(line, alert) for line, alert in thin.summary]
        self.assertEqual(again, list(full.summary))  # el resumen cuenta todas, no las dibujadas

    def test_e_what_is_drawn_in_pixels_and_with_gpu(self) -> None:
        """RF-013-03, RNF-013-05: en píxeles de la región, el resumen arriba a la izquierda (cada línea
        partida al ancho, los avisos en ámbar y las demás en blanco), los nombres que caben y la
        leyenda abajo a la derecha; con ``gpu``, los puntos de las semillas en un solo lote con su
        color por vértice (creado una vez, con el tamaño de su punto y el de la pantalla) y los
        lotes de líneas de la 012 (uno por lote), sin que cambie el estado de ``gpu``."""
        design, constraints = self.design, self.constraints
        self.assertEqual(self.show(zone="sector:sector_1"), {"FINISHED"})
        built = self.pump()
        pixels = _module("bl.draw.dh_overlay")
        matrix = top_view(self.local(30.0, 30.0))
        measure = lambda text: 7.0 * len(text)  # noqa: E731 - el ancho de una fuente de mentira
        items = design.screen_items(built, matrix, SIZE, measure=measure, scale=1.0)
        texts = [item for item in items if isinstance(item, pixels.Text)]
        summary = design.summary_items(built.summary, measure, 1.0, SIZE)
        self.assertEqual(items[-len(summary):], summary)  # el resumen, lo último que se pinta
        box, *lines = summary
        limit = SIZE[0] * design.SUMMARY_WIDTH_FRACTION - 2 * pixels.MARGIN_PX
        self.assertTrue(all(isinstance(item, pixels.Text) and item.x == pixels.MARGIN_PX
                            for item in lines))
        self.assertTrue(all(measure(item.text) <= limit for item in lines))
        self.assertEqual(" ".join(item.text for item in lines).split(),
                         " ".join(line for line, _alert in built.summary).split())
        amber = sum(len(design.wrap_text(line, measure, limit))
                    for line, alert in built.summary if alert)
        self.assertGreater(amber, 0)
        self.assertEqual([item.color for item in lines].count(pixels.STALE_COLOR), amber)
        tops = [item.y for item in lines]
        self.assertEqual(tops, sorted(tops, reverse=True))  # de arriba abajo
        self.assertGreater(box.y1, SIZE[1] / 2)  # arriba a la izquierda
        self.assertTrue(box.x0 < pixels.MARGIN_PX and box.y1 < SIZE[1] and box.y1 > tops[0])
        self.assertEqual(design.wrap_text("una dos tres", len, 6), ["una", "dos", "tres"])
        self.assertEqual(design.wrap_text("una dos tres", len, 7), ["una dos", "tres"])
        self.assertEqual(design.wrap_text("una dos tres", len, 12), ["una dos tres"])
        self.assertEqual(design.wrap_text("anticonstitucionalmente", len, 5),
                         ["anticonstitucionalmente"])
        names = {item.text for item in texts}
        self.assertIn("Sector 2 · Búsqueda pendiente", names)
        self.assertIn("Torre", names)
        panel = next(item for item in items if isinstance(item, pixels.Box)
                     and item.x1 == SIZE[0] - pixels.MARGIN_PX + pixels.PAD_PX)  # la leyenda
        self.assertEqual(panel.y0, pixels.MARGIN_PX - pixels.PAD_PX)
        self.assertEqual(design.summary_items((), len, 1.0, SIZE), [])

        gpu = mock.MagicMock()
        gpu.state.depth_test_get.return_value = "NONE"
        gpu.state.depth_mask_get.return_value = True
        gpu.state.blend_get.return_value = "NONE"
        with mock.patch.object(design, "gpu", gpu), mock.patch.object(
                design, "batch_for_shader") as make:
            view = dict(view_matrix=Matrix.Identity(4), projection_matrix=Matrix.Identity(4),
                        perspective=True, view_distance=100.0)
            self.assertEqual(design.draw_points(built, pixel_size=1.0, **view), built.seeds.count)
            gpu.shader.from_builtin.assert_called_with("POINT_FLAT_COLOR")
            self.assertEqual(make.call_count, 1)
            self.assertEqual(make.call_args.args[1], "POINTS")
            data = make.call_args.args[2]
            self.assertEqual(sorted(data), ["color", "pos"])
            self.assertEqual((data["pos"].shape, data["color"].shape),
                             ((built.seeds.count, 3), (built.seeds.count, 4)))
            self.assertEqual(design.draw_points(built, pixel_size=2.0, **view), built.seeds.count)
            self.assertEqual(make.call_count, 1)  # el lote de gpu ya estaba
        sizes = [call.args[0] for call in gpu.state.point_size_set.call_args_list]
        self.assertEqual(sizes, [design.SEED_PX, 1.0, 2 * design.SEED_PX, 1.0])
        gpu.state.depth_test_set.assert_called_with("NONE")
        gpu.state.depth_mask_set.assert_called_with(True)
        gpu.state.blend_set.assert_called_with("NONE")
        nothing = design.Built(built.lines, None, (), ())
        self.assertEqual(design.draw_points(nothing, pixel_size=1.0, **view), 0)

        lines_gpu = mock.MagicMock()
        lines_gpu.state.depth_test_get.return_value = "NONE"
        with mock.patch.object(constraints, "gpu", lines_gpu), mock.patch.object(
                constraints, "batch_for_shader") as lots:
            drawn = constraints.draw_lines(built.lines, viewport_size=(400.0, 300.0),
                                           pixel_size=1.0, **view)
        self.assertEqual((drawn, lots.call_count), (len(built.lines.batches),) * 2)
        self.assertGreater(len(built.lines.batches), 6)  # dominio, tres contornos, la torre y 2 sectores

    def test_f_changing_the_version_or_leaving_removes_or_rebuilds_it(self) -> None:
        """RF-013-03: cambiar de versión activa rehace la vista previa con la de la nueva (V02 no
        tiene máscaras: solo contornos y el aviso); volver a V01 devuelve las semillas; un aviso del
        proyecto sin nada nuevo no rehace nada; conmutar a la interfaz de Blender la quita (y
        volver a Geoblender no la pone sola); cerrar el proyecto también."""
        design, switcher = self.design, self.switcher
        self.assertEqual(self.show(zone="sector:sector_1"), {"FINISHED"})
        self.assertEqual(self.pump().seeds.count, SEEDS_IN_SECTOR_1)
        design.on_project_read(self.project)  # sin nada nuevo
        self.assertFalse(design.building())
        self.set_active(self.v02)
        self.assertTrue(design.building())
        other = self.pump()
        self.assertEqual((other.lines.version_code, other.lines.masks), ("V02", "missing"))
        self.assertIsNone(other.seeds)
        self.assertEqual(self.legend_texts(other)[0], "Vista previa · V02")
        self.assertTrue(other.summary[0][0].startswith("Las máscaras de V02 no se han compilado"))
        self.set_active(self.v01)
        self.assertEqual(self.pump().seeds.count, SEEDS_IN_SECTOR_1)

        self.assertIn(design.disable, switcher.blender_hooks())
        window = bpy.context.window_manager.windows[0]
        self.addCleanup(switcher.forget)
        with mock.patch.object(switcher, "_marked", return_value={window.workspace.name}):
            self.assertTrue(switcher.toggle(window, "BLENDER").workspace)
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        self.assertIsNone(design.built())
        self.assertIs(getattr(bpy.context.window_manager, WM_PROPERTY), False)
        self.assertEqual(switcher.blender_hooks(), ())
        other_space = next(space.name for space in bpy.data.workspaces
                           if space.name != window.workspace.name)
        with mock.patch.object(switcher, "_marked", return_value={other_space}):
            self.assertEqual(switcher.toggle(window, "GEOBLENDER").workspace, other_space)
        self.assertFalse(design.enabled())

        self.assertEqual(self.show(), {"FINISHED"})
        self.pump()
        self.assertIn(design.on_project_changed, self.ps.listeners())
        self.ps.listeners()[self.ps.listeners().index(design.on_project_changed)](None)
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        self.assertNotIn(design.on_project_changed, self.ps.listeners())
        self.assertEqual(len(self.view.preview), 0)

    def test_g_the_dialog_refuses_what_is_missing_and_a_rejected_preview_warns(self) -> None:
        """RF-013-33, RF-013-03: una cota fija sin escribir, unos sectores sin marcar y una cota que no
        es un número se rechazan sin activar nada y diciéndolo; una vista previa que el cálculo
        rechaza (aquí, una superficie que ya no existe) avisa con el motivo y se quita sola; con
        la versión activa no editable la orden se niega con su motivo y con la vista previa activa
        la quita."""
        design = self.design
        for values, wanted in (
                ({"seeds_from": "FIXED", "elevation": ""}, "Escriba la cota fija de las semillas"),
                ({"seeds_from": "FIXED", "elevation": "alta"}, "«alta» no es un número"),
                ({"bound": "SECTORS"}, "Marque los sectores a los que se acota el dominio")):
            with self.subTest(pedido=wanted), self.assertRaises(RuntimeError) as caught:
                self.show(**values)
            self.assertIn(wanted, str(caught.exception))
            self.assertFalse(design.enabled())
        self.assertEqual(self.show(seeds_from="FIXED", elevation="101,5",
                                   zone="sector:sector_1"), {"FINISHED"})
        fixed = self.pump()
        self.assertEqual(fixed.seeds.count, SEEDS_IN_SECTOR_1)
        self.assertTrue(np.all(fixed.seeds.positions[:, 2] == np.float32(101.5 - self.origin.z0)))
        self.assertEqual({tuple(color) for color in fixed.seeds.colors.tolist()},
                         {tuple(np.float32(value) for value in (*self.design.RAMP[2][1], 1.0))})
        design.disable()

        self.view.sectors[1].use = True
        self.assertEqual(self.show(bound="SECTORS"), {"FINISHED"})
        self.assertEqual(design.plan().domain, self.dmodel.WorkDomain(sectors=("sector_2",)))
        design.disable()
        self.panels.clear_sector_marks()

        self.ps.take_notices()
        missing = design.Plan(self.dmodel.SeedSource(self.dmodel.SeedKind.SURFACE,
                                                     surface="Ladera inexistente"))
        design.enable(missing)
        self.assertIsNone(self.run_to_end())
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        (notice,) = self.ps.take_notices()
        self.assertTrue(notice.startswith("No se pudo preparar la vista previa de semillas, "
                                          "dominios y restricciones: "), notice)
        self.assertIn("Ladera inexistente", notice)

        self.assertEqual(self.show(), {"FINISHED"})
        self.pump()
        with mock.patch.object(self.des_ops, "design_unavailable",
                               return_value="V02 está en estado SUPERADO"):
            self.assertEqual(bpy.ops.geoblender.des_toggle_preview(), {"FINISHED"})
        self.assertFalse(design.enabled())
        with mock.patch.object(self.des_ops, "design_unavailable",
                               return_value="V02 está en estado SUPERADO"):
            self.assertFalse(bpy.ops.geoblender.des_toggle_preview.poll())

    def run_to_end(self) -> Any:
        """Los pasos hasta que acaban o fallan (``None`` si la vista previa se quitó)."""
        for _ in range(MAX_PUMPS):
            if self.design.tick() is None:
                return self.design.built()
        self.fail("la vista previa no acaba")

    def test_z_disabling_geoblender_with_the_preview_on_leaves_nothing(self) -> None:
        """Principio 8: con la vista previa activa, desactivar Geoblender quita los manejadores de
        dibujo, los avisos, el temporizador y los lotes, y la huella de Blender vuelve a la del
        principio de la sesión."""
        design = self.design
        self.assertEqual(self.show(zone="sector:sector_1"), {"FINISHED"})
        self.assertTrue(design.drawing())
        self.assertTrue(bpy.app.timers.is_registered(design.tick))  # la construcción, sin acabar
        blender_ext.release()
        self.assertFalse(design.enabled() or design.drawing() or design.building())
        self.assertIsNone(design.built())
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(),
                                                      blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
