# SPDX-License-Identifier: GPL-3.0-or-later
"""«Línea de cielo…» y «Superficie y sólido…» en Blender (spec 018, T33; HU-018-4; RF-018-29, RF-018-30, RF-018-33, RF-018-34, RF-015-28; plan 018 §5.3.3; comprobación manual M4).

:class:`GEOBLENDER_OT_des_pit_skyline` (``geoblender.des_pit_skyline``, de ``bl/ops/des_pit.py``) **muestra** las cifras registradas de la línea de cielo de una corta (RF-018-29: número de partes,
longitud, área, cota mínima y máxima y distancia mínima al límite legal y al perímetro de actuación, con su lugar) y pone al día su capa (``des.pit_layer``) si está atrasada.
:class:`GEOBLENDER_OT_des_pit_surface` (``geoblender.des_pit_surface``) carga a petición el **TIN** y el **sólido** de la corta como vistas regenerables, con el aviso de triángulos **antes de crearlos**
(RNF-018-09), y exporta la **superficie a GeoTIFF** y los **hallazgos a CSV**; **no escribe nada en el proyecto**. Sobre el proyecto del hito H2 (como ``milestone_pit_ops.py``), con la corta circular
ascendente creada en V01. Las pruebas, en el orden de sus letras sobre el mismo estado.

- RF-018-34, RF-015-28 (a): las dos órdenes son reales, del catálogo (con su casa en Diseño ▸ Corta por bancos), con sus propiedades nombradas y descritas; la de la línea de cielo es de ``des.pit_layer``.
- RF-018-29 (b): la orden de la línea de cielo enseña **las siete cifras** (con su unidad y su tipo) tal como las registró la corta y no escribe nada con la capa al día.
- RF-018-33 (c): con la capa atrasada, la orden la pone al día (``des.pit_layer``) con las mismas filas; una corta que no existe se rechaza con el campo y sin dejar nada.
- RF-018-30 (d): el TIN y el sólido se cargan como vistas, sin escribir nada en el proyecto.
- RF-018-30, RNF-018-09 (e): por encima del límite de triángulos el aviso sale antes de crear nada; con la confirmación se crea.
- RF-018-30, RF-018-33 (f): la superficie a GeoTIFF y los hallazgos a CSV, sin escribir en el proyecto; sobre un fichero que existe, solo con ``overwrite``.
- RF-018-34, RF-015-28 (g): las dos órdenes salen desactivadas con su motivo con el proyecto en solo lectura.
- Principio 8 (z): desactivar Geoblender quita las dos órdenes.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import milestone_pit_h2 as h2
from tests.blender import milestone_pit_ops as pit_ops
from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self
from tests.support.trees import remove_tree

SKYLINE = "geoblender.des_pit_skyline"
SURFACE = "geoblender.des_pit_surface"
LAYER_TYPE = "des.pit_layer"
PIT_NAME = "Corta de la vista"
SKY_KEYS = ("des.pit_sky_parts", "des.pit_sky_len_m", "des.pit_sky_area_m2", "des.pit_sky_z_min_m", "des.pit_sky_z_max_m")
HIDDEN = ("in_steps", "confirm_large", "confirm")
SKYLINE_PROPERTIES = frozenset({"pit", "update_layer"})
SURFACE_PROPERTIES = frozenset({"pit", "what", "filepath", "overwrite"})


class PitViewOpsTest(pit_ops.PitOpsTest):
    """El proyecto del hito H2 con la extensión habilitada (el de ``milestone_pit_ops``) y la corta de la vista creada; las pruebas de aquella clase no se repiten aquí."""

    names = platform_ops.CreatePlatformTest.names
    state = platform_ops.CreatePlatformTest.state

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.dprov = h2._module("design.provenance")
        cls.pit_layer = h2._module("design.pit_layer")
        cls.pit_views = h2._module("bl.scene.pit_views")
        cls.views = h2._module("bl.scene.views")
        cls.registry = h2._module("core.datasets.registry")
        cls.refresh()
        assert bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", **cls.form(cls, name=PIT_NAME)) == {"FINISHED"}  # type: ignore[arg-type]
        assert cls.create_pit(cls) == {"FINISHED"}  # type: ignore[arg-type]
        cls.refresh()
        folder = Path(tempfile.mkdtemp(prefix="gb-p33-"))
        cls.addClassCleanup(remove_tree, folder)
        cls.out = folder

    @property
    def skyline(self) -> Any:
        return self.commands.registered_class(SKYLINE)

    @property
    def surface(self) -> Any:
        return self.commands.registered_class(SURFACE)

    # --- Ayudas -------------------------------------------------------------------------------

    def pit_operation(self) -> str:
        ((uid,),) = self.rows("SELECT uid FROM gb_operation WHERE op_type = 'des.pit' AND status = 'done' ORDER BY rowid DESC LIMIT 1")
        return str(uid)

    def sky_run(self, **values: Any) -> tuple[set[str], list[str]]:
        """«Línea de cielo…» llamada a mano: el resultado y los informes que dio."""
        reports: list[str] = []
        shown: dict[str, Any] = {"pit": PIT_NAME, "update_layer": False, "in_steps": False}
        fake = operator_self(self.skyline, report=lambda kind, text: reports.append(text), **{**shown, **values})
        return self.skyline.execute(fake, bpy.context), reports

    def surface_run(self, **values: Any) -> tuple[set[str], list[str]]:
        """«Superficie y sólido…» llamada a mano: el resultado y los informes que dio."""
        reports: list[str] = []
        shown: dict[str, Any] = {"pit": PIT_NAME, "what": "TIN", "filepath": "", "overwrite": False, "confirm_large": False, "in_steps": False}
        fake = operator_self(self.surface, report=lambda kind, text: reports.append(text), **{**shown, **values})
        return self.surface.execute(fake, bpy.context), reports

    def record(self, family: str) -> Any:
        dataset = self.dprov.dataset_name(family, PIT_NAME)
        with self.project.read() as conn:
            found = self.registry.get(conn, dataset, version_uid=self.v01.uid)
        self.assertIsNotNone(found, dataset)
        return found

    def unload(self) -> None:
        self.views.unload_datasets([item.uid for item in (self.record(self.dprov.PIT_POLYLINES_TABLE), self.record(self.dprov.PIT_BENCHES_TABLE))])

    # --- a: las órdenes ------------------------------------------------------------------------

    def test_va_the_commands_are_real_and_in_the_catalog(self) -> None:
        """RF-018-34, RF-015-28 (plan §5.3.3): las dos órdenes son reales, del catálogo (casa en Diseño ▸ Corta por bancos), con sus propiedades nombradas y descritas; la de la línea de cielo es
        la de la operación ``des.pit_layer``."""
        for idname, cls, properties in ((SKYLINE, self.skyline, SKYLINE_PROPERTIES), (SURFACE, self.surface, SURFACE_PROPERTIES)):
            with self.subTest(orden=idname):
                self.assertIsNotNone(cls)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertIn(cls, self.des_pit.classes)
                self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
                self.assertTrue(issubclass(cls, self.des_ops.DesignCommand))
                annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
                self.assertEqual(annotated, properties)
                for prop in sorted(properties):
                    keywords = cls.__annotations__[prop].keywords
                    self.assertTrue(keywords["name"] and keywords["description"], prop)
        catalog = self.commands.catalog().commands
        self.assertEqual((catalog[SKYLINE].label_es, catalog[SKYLINE].module), ("Línea de cielo…", "des"))
        self.assertEqual((catalog[SURFACE].label_es, catalog[SURFACE].module), ("Superficie y sólido…", "des"))
        self.assertTrue(issubclass(self.skyline, self.session.ProvenanceAwareOperator))
        self.assertEqual(self.skyline.provenance_op_type, LAYER_TYPE)
        self.assertEqual(self.dprov.PIT_LAYER_COMMAND, SKYLINE)
        self.assertIn(SKYLINE, self.dprov.OPERATION_TYPES_BY_NAME[LAYER_TYPE].commands)
        self.assertNotIn("geoblender.des_compute_daylight", self.commands.catalog().commands)
        self.assertEqual(self.surface.bl_options, {"REGISTER"})
        shown = draw(self.surface, bpy.context, **{"pit": PIT_NAME, "what": "TIN", "filepath": "", "overwrite": False})
        self.assertLessEqual(len([item for item in shown.items if item.kind in ("prop", "label", "operator", "prop_search")]), 32)

    # --- b: las cifras de la línea de cielo --------------------------------------------------------

    def test_vb_the_skyline_shows_its_figures_and_writes_nothing(self) -> None:
        """RF-018-29, RF-008-30 (M4): la orden enseña las cifras de la línea de cielo tal como las registró la corta (con su unidad y su tipo) y no escribe nada con la capa al día."""
        before = self.state()
        counts = self.counts()
        result, reports = self.sky_run(update_layer=True)
        self.assertEqual(result, {"FINISHED"})
        shown = "\n".join(reports)
        self.assertIn(f"«{PIT_NAME}»", reports[0])
        figures = self.figures_of(self.pit_operation())
        for key in SKY_KEYS:
            self.assertIn(key, figures, key)
        with self.project.read() as conn:
            figures_module = h2._module("core.provenance.figures")
            records = [figures_module.FigureRecord.from_row(row) for row in conn.execute(
                f"SELECT {figures_module.RECORD_COLUMNS} FROM gb_figure AS f WHERE f.operation_uid = ? AND f.key LIKE 'des.pit_sky_%' ORDER BY f.fid", (self.pit_operation(),))]
        self.assertGreaterEqual(len(records), len(SKY_KEYS))
        for record in records:
            self.assertIn(self.dprov.figure_text(record, language="es"), shown, record.key)
        self.assertTrue(any("al día" in text for text in reports), reports)
        report = h2._module("design.pit_view").skyline_report(self.project, self.v01.uid, PIT_NAME)
        self.assertEqual(("des.pit_sky_dist_legal_m" in figures, "des.pit_sky_dist_perimeter_m" in figures), (report.legal is not None, report.perimeter is not None),
                         "el lugar de la distancia existe justo cuando existe su cifra")
        for found, key in ((report.legal, "des.pit_sky_dist_legal_m"), (report.perimeter, "des.pit_sky_dist_perimeter_m")):
            if found is not None:
                self.assertAlmostEqual(found.distance_m, figures[key], delta=1e-6, msg=key)
        self.assertFalse(report.layer_pending)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.counts(), counts, "mostrar las cifras no escribe nada")
        self.i18n.set_language("en")
        in_english = "\n".join(self.sky_run()[1])
        self.assertIn("Skyline of pit", in_english)
        self.i18n.set_language("es")

    # --- c: la capa y los rechazos -------------------------------------------------------------

    def test_vc_a_stale_layer_is_brought_up_to_date_and_what_is_refused_leaves_nothing(self) -> None:
        """RF-018-33, RF-015-29 (M4): con la capa atrasada, la orden la pone al día (una operación ``des.pit_layer`` con las mismas filas); una corta que no existe se rechaza con el campo y sin dejar
        nada; sin versión activa, también."""
        layer = self.pit_layer.pit_layer_table("V01")
        rows = self.rows(f'SELECT * FROM "{layer}" ORDER BY fid')
        operations = self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?", LAYER_TYPE)[0][0]
        with mock.patch.object(self.pit_layer, "pit_layer_pending", return_value=True):
            result, reports = self.sky_run(update_layer=True)
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?", LAYER_TYPE)[0][0], operations + 1)
        self.assertEqual(self.rows(f'SELECT * FROM "{layer}" ORDER BY fid'), rows, "las mismas filas")
        self.assertTrue(any("capa" in text and "puesta al día" in text for text in reports), reports)
        with mock.patch.object(self.pit_layer, "pit_layer_pending", return_value=True):
            self.sky_run(update_layer=False)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = ?", LAYER_TYPE)[0][0], operations + 1, "sin update_layer no se escribe")
        before = self.state()
        counts = self.counts()
        result, reports = self.sky_run(pit="No existe")
        self.assertEqual(result, {"CANCELLED"})
        self.assertIn("No existe", reports[-1])
        result, reports = self.sky_run(pit="")
        self.assertEqual(result, {"CANCELLED"})
        self.assertIn("Elija la corta", reports[-1])
        self.assertEqual((self.state(), self.counts()), (before, counts))

    # --- d: el TIN y el sólido -----------------------------------------------------------------

    def test_vd_the_tin_and_the_solid_are_loaded_as_views_and_write_nothing(self) -> None:
        """RF-018-30, RF-010-01 (M4): el TIN y el sólido de la corta se cargan como vistas regenerables (objetos en la escena con su dato) sin escribir nada en el proyecto."""
        counts = self.counts()
        for what, family in (("TIN", self.dprov.PIT_POLYLINES_TABLE), ("SOLID", self.dprov.PIT_BENCHES_TABLE)):
            with self.subTest(vista=what):
                result, reports = self.surface_run(what=what)
                self.assertEqual(result, {"FINISHED"}, reports)
                uid = self.record(family).uid
                shown = [obj for obj in bpy.data.objects if uid in self.views.loaded_uids([obj])]
                self.assertEqual(len(shown), 1, "un objeto en la escena")
                self.assertGreater(len(shown[0].data.polygons), 10)
                self.assertTrue(any("Cargado" in text or "vista" in text.lower() for text in reports), reports)
        self.assertEqual(self.counts(), counts, "las vistas no escriben nada")
        self.unload()

    # --- e: el aviso de triángulos --------------------------------------------------------------

    def test_ve_over_the_limit_the_warning_comes_before_anything_is_created(self) -> None:
        """RF-018-30, RNF-018-09 (M4): por encima del límite de triángulos la orden avisa **antes de crear nada** (y desde un guion no sigue); con ``confirm_large`` se crea."""
        objects = len(bpy.data.objects)
        counts = self.counts()
        with mock.patch.object(self.pit_views, "MAX_TRIANGLES", 10):
            result, reports = self.surface_run(what="TIN")
            self.assertEqual(result, {"CANCELLED"})
            self.assertIn("no se crea nada hasta que lo confirme", reports[-1])
            self.assertEqual(len(bpy.data.objects), objects, "ni un objeto antes de confirmar")
            result, reports = self.surface_run(what="SOLID")
            self.assertEqual(result, {"CANCELLED"})
            self.assertEqual(len(bpy.data.objects), objects)
            result, reports = self.surface_run(what="TIN", confirm_large=True)
            self.assertEqual(result, {"FINISHED"}, reports)
            self.assertEqual(len(bpy.data.objects), objects + 1, "confirmado, se crea")
            self.assertFalse(self.pit_views.confirmed(), "la confirmación no se queda")
        self.assertEqual(self.counts(), counts)
        self.unload()

    # --- e2: por pasos desde la interfaz ----------------------------------------------------------

    def running(self) -> Any:
        found = [op for op in bpy.context.window.modal_operators if isinstance(op, self.surface) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{SURFACE} no está en marcha")
        return found[0]

    def test_vf2_from_the_interface_it_goes_by_steps_with_esc_and_asks_before_a_large_view(self) -> None:
        """RF-018-30, RF-018-35, RNF-018-09 (M4): desde la interfaz la vista se crea **por pasos** con Esc (cerrar a mitad no deja ningún objeto) y, por encima del límite, avisa y **pregunta** si se
        crea de todos modos (``confirm_large``) sin haber creado nada."""
        objects = len(bpy.data.objects)
        counts = self.counts()
        self.assertEqual(bpy.ops.geoblender.des_pit_surface("EXEC_DEFAULT", pit=PIT_NAME, what="SOLID", in_steps=True), {"RUNNING_MODAL"})
        modal = self.running()
        self.assertEqual(step_modals.drive(modal, bpy.context, stop_after=0)[0], {"RUNNING_MODAL"})
        self.assertEqual(modal.modal(bpy.context, SimpleNamespace(type="ESC", value="PRESS")), {"CANCELLED"})  # Esc a mitad: el cargador de la vista no deja nada
        self.assertEqual(len(bpy.data.objects), objects)
        self.assertEqual(bpy.ops.geoblender.des_pit_surface("EXEC_DEFAULT", pit=PIT_NAME, what="TIN", in_steps=True), {"RUNNING_MODAL"})
        self.assertEqual(step_modals.drive(self.running(), bpy.context)[0], {"FINISHED"})
        self.assertEqual(len(bpy.data.objects), objects + 1)
        self.unload()
        asked: list[tuple[dict[str, Any], str]] = []
        with mock.patch.object(self.pit_views, "MAX_TRIANGLES", 10), mock.patch.object(self.des_pit, "_confirm_later", lambda values, idname: asked.append((dict(values), idname))):
            self.assertEqual(bpy.ops.geoblender.des_pit_surface("EXEC_DEFAULT", pit=PIT_NAME, what="TIN", in_steps=True), {"RUNNING_MODAL"})
            self.assertEqual(step_modals.drive(self.running(), bpy.context)[0], {"FINISHED"})
        self.assertEqual(len(bpy.data.objects), objects, "ni un objeto antes de confirmar")
        ((values, idname),) = asked
        self.assertEqual((idname, values["confirm_large"], values["what"], values["pit"]), (SURFACE, True, "TIN", PIT_NAME))
        self.assertEqual(self.counts(), counts)

    # --- f: los entregables ------------------------------------------------------------------------

    def test_vf_the_surface_to_geotiff_and_the_findings_to_csv(self) -> None:
        """RF-018-30, RF-018-33, RF-015-27 (M4): la superficie de la corta sale a GeoTIFF y los hallazgos a CSV, sin escribir nada en el proyecto; sobre un fichero que existe, solo con ``overwrite``."""
        counts = self.counts()
        tif, csv = self.out / "corta.tif", self.out / "hallazgos.csv"
        result, reports = self.surface_run(what="SURFACE", filepath=str(tif))
        self.assertEqual(result, {"FINISHED"}, reports)
        self.assertEqual(tif.read_bytes()[:2], b"II")
        self.assertTrue(any("corta.tif" in text for text in reports), reports)
        result, reports = self.surface_run(what="FINDINGS", filepath=str(csv))
        self.assertEqual(result, {"FINISHED"}, reports)
        self.assertTrue(csv.read_bytes().startswith(b"\xef\xbb\xbf"), "BOM de UTF-8")
        before = tif.read_bytes()
        result, reports = self.surface_run(what="SURFACE", filepath=str(tif))
        self.assertEqual(result, {"CANCELLED"}, "ya existe")
        self.assertEqual(tif.read_bytes(), before)
        result, reports = self.surface_run(what="SURFACE", filepath=str(tif), overwrite=True)
        self.assertEqual(result, {"FINISHED"}, reports)
        result, reports = self.surface_run(what="SURFACE", filepath=str(self.out / "otra.csv"))
        self.assertEqual(result, {"CANCELLED"}, "la extensión no es la de un GeoTIFF")
        self.assertEqual(self.counts(), counts, "exportar no escribe nada en el proyecto")

    # --- g: desactivadas ---------------------------------------------------------------------------

    def test_vg_the_commands_are_disabled_with_their_reason(self) -> None:
        """RF-018-34, RF-015-28, RF-009-21 (M4): con el proyecto en solo lectura las dos salen desactivadas con su motivo y no se pueden lanzar; ni dejan nada."""
        before = self.state()
        for idname, cls in ((SKYLINE, self.skyline), (SURFACE, self.surface)):
            messages: list[str] = []
            self.assertTrue(cls.poll(bpy.context), idname)
            with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True), \
                    mock.patch.object(self.project, "_status", self.project.status):
                self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
                self.assertFalse(cls.poll(bpy.context), idname)
                (reason,) = messages
                self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
            self.assertTrue(cls.poll(bpy.context), idname)
        self.assertEqual(self.state(), before)

    # --- z: desactivar -------------------------------------------------------------------------------

    def test_vz_disabling_geoblender_removes_the_commands(self) -> None:
        """Principio 8: desactivar Geoblender quita las dos órdenes."""
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, "GEOBLENDER_OT_des_pit_skyline", None))
        self.assertIsNone(getattr(bpy.types, "GEOBLENDER_OT_des_pit_surface", None))


for _name in [name for name in dir(pit_ops.PitOpsTest) if name.startswith("test_") and name not in PitViewOpsTest.__dict__]:
    setattr(PitViewOpsTest, _name, None)  # las pruebas de «Nueva corta…» no se repiten aquí


if __name__ == "__main__":
    unittest.main()
