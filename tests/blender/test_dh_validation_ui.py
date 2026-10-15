# SPDX-License-Identifier: GPL-3.0-or-later
"""Validar los sondeos y exportar su informe en Blender (spec 005, T27; HU-005-3; plan 005
§5.3.1, §5.5, §5.6.4, §5.6.6 y §5.6.9; D-19).

Con el proyecto y las ayudas de ``test_dh_import_tabular`` (``DrillholeImportCase``): las bocas,
las desviaciones y la litología de tres casos de ``tests/data/dh/csv_errores`` (DH-W05, DH-W04
y DH-E09), importadas con sus códigos dados de alta; su base y su validación. El oráculo es el
dominio: la base leída del proyecto (``drillholes.store.read_steps``) validada con
``drillholes.validate`` y los parámetros de ``drillholes.params``, y su CSV de T11
(``drillholes.report.csv_bytes``).

- RF-005-16, RF-005-17: la lista de la pestaña «Sondeos» (``GEOBLENDER_UL_dh_issues``) tiene una
  fila por incidencia y una por lo que no se evaluó, en el orden del informe, y se filtra por
  nivel y por código; cerrar el proyecto la vacía.
- D-19, RF-005-18: ``geoblender.dh_validate`` usa la rejilla del proyecto (``gis_dtm_*``)
  vigente más reciente (consumida como ``terrain``) o la que se nombra; sin ninguna, DH-W05 no
  se evalúa y el informe lo dice; una que no está se rechaza nombrándola. Sin base, no empieza.
- RF-005-19, RF-008-15, D21: ``geoblender.dh_export_validation_report`` (la operación
  ``dh.export_validation``, que consume ``dh_validation_issue``) escribe exactamente el CSV de
  T11; dentro de ``exports/`` es un dato del proyecto; fuera, ninguno; un destino que ya existe
  no se sustituye sin confirmarlo; una carpeta de solo lectura, otra del proyecto u otra
  extensión se rechazan sin escribir nada. Sin validación, no empieza.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import os
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import DrillholeImportCase, _module
from tests.support.fake_layout import draw
from tests.support.repo import ROOT

ERRORS = ROOT / "tests" / "data" / "dh" / "csv_errores"
DTM = ROOT / "tests" / "data" / "gis" / "geotiff" / "f64_strip.tif"
ROLES = {"dh_w05_bocas.csv": "collar", "dh_w04_desviaciones.csv": "survey",
         "dh_e09_litologia.csv": "lithology"}
VALIDATE = "geoblender.dh_validate"
EXPORT = "geoblender.dh_export_validation_report"
DESURVEY = "geoblender.dh_desurvey"
ISSUES = "dh_validation_issue"
FILTER_ITEM = 1 << 30


def _drive(steps: Any) -> Any:
    """Lo que devuelve un generador de pasos, avanzado hasta el final."""
    try:
        while True:
            next(steps)
    except StopIteration as stop:
        return stop.value


class ValidationUiTest(DrillholeImportCase):
    def setUp(self) -> None:
        super().setUp()
        for name in ROLES:
            shutil.copyfile(ERRORS / name, self.sources / name)
        validation = getattr(bpy.context.window_manager, self.props.VALIDATION_PROPERTY)
        self.addCleanup(setattr, validation, "code_filter", "")
        self.addCleanup(setattr, validation, "level_filter", "ALL")
        self.validation = validation

    # --- Ayudas -------------------------------------------------------------------------------

    def import_errors(self) -> None:
        """Las tres tablas de ``csv_errores``, sus códigos nuevos dados de alta, aplicadas
        hasta el final de su validación."""
        result, _launched = self.run_import(tuple(ROLES), ROLES)
        self.assertEqual(result, {"FINISHED"})
        self.finish()
        uid, pending = self.waiting()
        pending.register_codes = True
        self.assertEqual(self.decide("APPLY", uid), {"FINISHED"})
        self.finish()

    def expected(self, surface: Any = None) -> tuple[Any, bytes]:
        """El informe del dominio sobre la base del proyecto (sus parámetros por defecto, la
        ventana de trabajo y, si se da, el MDT) y su CSV de T11."""
        store = _module("drillholes.store")
        validate = _module("drillholes.validate")
        params = _module("drillholes.params")
        with self.project.read() as conn:
            dset = _drive(store.read_steps(conn))
        thresholds = validate.ValidationParams(**{
            key.rpartition(".")[2]: params.default(key) for key in params.VALIDATION_KEYS})
        found = validate.validate(dset, thresholds, surface=surface,
                                  work_window=self.project.window)
        return found, _module("drillholes.report").csv_bytes(found)

    def add_dtm(self) -> Any:
        """La rejilla del proyecto ``gis_dtm_terreno`` (el MDT de ``tests/data/gis``, en las
        referencias del proyecto), escrita con la API de la 006 como la deja «Rejilla del
        proyecto desde un MDT»; devuelve su ``Raster``."""
        gis_store = _module("gis.store")
        operations = _module("core.provenance.operations")
        source = _module("gis.geotiff.reader").read_geotiff(DTM)
        crs, vertical = gis_store.project_references(self.project)
        raster = _module("gis.raster").Raster(source.grid, source.values, crs, vertical)
        handle = operations.begin_operation(self.project, "gis.resample", settings={},
                                            executor="blender")
        library, version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(self.project, handle) as out:
            out.raster("terreno", raster)
            out.commit(software={library: version})
        return raster

    def listed(self) -> list[tuple[str, str, str, str]]:
        return [(item.hole, item.code, item.level, item.message)
                for item in self.validation.issues]

    def assertListed(self, found: Any) -> None:  # noqa: N802 - unittest
        """La lista de la pestaña: las filas del informe ``found``, en su orden, con su
        nivel."""
        rows = _module("drillholes.report").rows(found)
        levels = [str(issue.level).upper() for issue in found.issues]
        levels += ["NOT_EVALUATED"] * len(found.notes)
        self.assertEqual(self.listed(), [(row[0], row[1], level, row[11])
                                         for row, level in zip(rows, levels, strict=True)])

    def shown(self) -> list[str]:
        """Los códigos de las filas que deja ver el filtro de la lista."""
        panels = _module("bl.ui.dh_panels")
        # El de una lista de Blender (UILST_FLT_ITEM): solo existe en una lista dibujada.
        fake = SimpleNamespace(bitflag_filter_item=FILTER_ITEM)
        flags, order = panels.GEOBLENDER_UL_dh_issues.filter_items(
            fake, bpy.context, self.validation, "issues")
        self.assertEqual(order, [])
        return [item.code for item, flag in zip(self.validation.issues, flags, strict=True)
                if flag]

    def operation(self, op_type: str) -> tuple[str, str, dict[str, Any], str]:
        """La última operación de ``op_type``: su uid, su estado, sus ajustes y su informe."""
        uid, status, settings, message = self.rows(
            "SELECT uid, status, settings, message FROM gb_operation WHERE op_type = ? "
            "ORDER BY fid DESC LIMIT 1", op_type)[0]
        return uid, status, json.loads(settings), message or ""

    def io(self, uid: str, direction: str) -> list[tuple[str, str]]:
        return self.rows("SELECT item_uid, role FROM gb_operation_io WHERE operation_uid = ? "
                         "AND direction = ? ORDER BY rowid", uid, direction)

    def dataset_uid(self, name: str) -> str:
        return self.rows("SELECT uid FROM gb_dataset WHERE name = ?", name)[0][0]

    # --- La prueba -----------------------------------------------------------------------------

    def test_validate_filter_and_export_the_report(self) -> None:
        """RF-005-16, RF-005-17, RF-005-18, RF-005-19, RF-008-15 (D-19, D21; plan §5.6.6 y
        §5.6.9): sin base no se valida y sin validación no se exporta; importadas las tres
        tablas, la lista tiene el informe del dominio (sin MDT, la nota de DH-W05) y se filtra
        por nivel y por código; el panel dibuja la lista y sus tres órdenes. ``dh_validate``
        sin MDT lo anota en sus ajustes y su informe; el CSV exportado es el de T11, fuera del
        proyecto sin dato y en ``exports/`` como dato ``exports``; un destino que ya existe
        espera la confirmación; una carpeta de solo lectura, otra del proyecto u otra
        extensión no escriben nada. Con la rejilla del proyecto, la validación la consume
        (``terrain``) y compara las cotas (DH-W05 en S-12); otra que no está se rechaza.
        Cerrar el proyecto vacía la lista."""
        commands = _module("bl.ui.commands")
        for idname in (VALIDATE, EXPORT):
            self.assertTrue(commands.is_available(idname), idname)
        root = Path(self.project.root)
        outside = self.tmp / "cliente" / "validacion.csv"
        outside.parent.mkdir()
        before = self.counts()
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.dh_validate("EXEC_DEFAULT")
        self.assertIn("importe sondeos", str(caught.exception))
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.dh_export_validation_report("EXEC_DEFAULT", filepath=str(outside))
        self.assertIn("valide la base de los sondeos", str(caught.exception))
        self.assertEqual((self.counts(), outside.exists()), (before, False))

        # La validación que sigue a la importación, en la lista; filtrada.
        self.import_errors()
        found, expected = self.expected()
        codes = {issue.code for issue in found.issues}
        self.assertTrue({"DH-E09", "DH-W04"} <= codes, codes)
        self.assertEqual([note.code for note in found.notes], ["DH-W05"])
        self.assertListed(found)
        self.validation.level_filter = "ERROR"
        self.assertEqual(self.shown(), [issue.code for issue in found.issues
                                        if str(issue.level) == "error"])
        self.assertTrue(self.shown())
        self.validation.level_filter = "NOT_EVALUATED"
        self.assertEqual(self.shown(), ["DH-W05"])
        self.validation.level_filter = "ALL"
        self.validation.code_filter = " w04"
        self.assertEqual(self.shown(), ["DH-W04"])
        self.validation.code_filter = ""
        layout = draw(bpy.types.GEOBLENDER_PT_dh_validation, bpy.context)
        self.assertEqual([button.target for button in layout.of_kind("operator")],
                         [VALIDATE, EXPORT, DESURVEY])
        self.assertEqual(len(layout.of_kind("template_list")), 1)

        # Validar sin MDT: su ajuste y su informe lo dicen (D-19).
        self.assertEqual(bpy.ops.geoblender.dh_validate("EXEC_DEFAULT"), {"FINISHED"})
        self.finish()
        uid, status, settings, message = self.operation("dh.validate")
        self.assertEqual((status, settings), ("done", {"surface": None}))
        self.assertIn("DH-W05 sin evaluar", message)
        self.assertEqual(len(self.io(uid, "in")), 11)  # las once tablas de la base
        self.assertListed(found)

        # Exportar: fuera del proyecto, sin dato; en exports/, un dato del proyecto (D21).
        export = bpy.ops.geoblender.dh_export_validation_report
        issues_uid = self.dataset_uid(ISSUES)
        self.assertEqual(export("EXEC_DEFAULT", filepath=str(outside)), {"FINISHED"})
        self.assertEqual(outside.read_bytes(), expected)
        uid, status, settings, message = self.operation("dh.export_validation")
        self.assertEqual((status, settings), ("done", {"file": "validacion.csv",
                                                       "in_exports": False}))
        self.assertEqual(self.io(uid, "in"), [(issues_uid, "exported")])
        self.assertEqual(self.io(uid, "out"), [])
        self.assertIn("fuera del proyecto", message)
        inside = root / "exports" / "validacion_sondeos.csv"
        self.assertEqual(export("EXEC_DEFAULT", filepath=str(inside)), {"FINISHED"})
        self.assertEqual(inside.read_bytes(), expected)
        uid, status, settings, message = self.operation("dh.export_validation")
        self.assertEqual(settings, {"file": "validacion_sondeos.csv", "in_exports": True})
        (row,) = self.rows("SELECT name, kind, store, locator, reader, tracked, content_sha256, "
                           "operation_uid, uid FROM gb_dataset WHERE store = 'exports'")
        self.assertEqual(row[:6], ("dh_exp_validacion_sondeos_csv", "report", "exports",
                                   "exports/validacion_sondeos.csv", "core.document@1", 0))
        self.assertEqual(row[7], uid)
        self.assertIn("dh_exp_validacion_sondeos_csv", message)
        registry = _module("core.datasets.registry")
        with self.project.read() as conn:
            record = registry.get(conn, row[8])
            self.assertEqual(registry.content_digest(conn, self.project, record).content_sha256,
                             row[6])

        # Un destino que ya existe espera la confirmación; los rechazados no escriben nada.
        outside.write_bytes(b"anterior")
        before = self.counts()
        with self.assertRaises(RuntimeError) as caught:
            export("EXEC_DEFAULT", filepath=str(outside))
        self.assertIn("Ya existe «validacion.csv»", str(caught.exception))
        self.assertEqual((self.counts(), outside.read_bytes()), (before, b"anterior"))
        self.assertEqual(export("EXEC_DEFAULT", filepath=str(outside), overwrite=True),
                         {"FINISHED"})
        self.assertEqual(outside.read_bytes(), expected)
        dossiers = self.tmp / "expedientes"
        dossiers.mkdir()
        paths = _module("core.paths")
        before = self.counts()
        cases = ((dossiers / "validacion.csv", str(dossiers), {"GEOBLENDER_READ_ONLY_DIRS":
                                                                str(dossiers)}),
                 (root / "rasters" / "validacion.csv", "no en su carpeta de entregables", {}),
                 (root / "exports" / "validacion.txt", "lleva la extensión .csv", {}))
        for target, named, environ in cases:
            with self.subTest(destino=target.name, carpeta=target.parent.name), \
                    mock.patch.dict(os.environ, environ), \
                    mock.patch.object(self.session, "read_only_dirs", lambda: paths
                                      .ReadOnlyDirs.from_sources(
                                          os.environ.get("GEOBLENDER_READ_ONLY_DIRS"), [])):
                with self.assertRaises(RuntimeError) as caught:
                    export("EXEC_DEFAULT", filepath=str(target))
                self.assertIn(named, str(caught.exception))
                self.assertFalse(target.exists())
        self.assertEqual(self.counts(), before)

        # Con la rejilla del proyecto (D-19): la consume y compara las cotas de las bocas.
        raster = self.add_dtm()
        dtm_uid = self.dataset_uid("gis_dtm_terreno")
        ops = _module("bl.ops.dh")
        self.assertEqual([record.name for record in ops.project_surfaces(self.project)],
                         ["gis_dtm_terreno"])
        dialog = draw(ops.GEOBLENDER_OT_dh_validate, bpy.context, surface="gis_dtm_terreno",
                      surfaces=[])
        self.assertEqual(len(dialog.of_kind("prop_search")), 1)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.dh_validate("EXEC_DEFAULT", surface="gis_dtm_otro")
        self.assertIn("gis_dtm_otro", str(caught.exception))
        self.assertEqual(bpy.ops.geoblender.dh_validate("EXEC_DEFAULT"), {"FINISHED"})
        self.finish()
        uid, status, settings, message = self.operation("dh.validate")
        self.assertEqual((status, settings), ("done", {"surface": "gis_dtm_terreno"}))
        self.assertIn((dtm_uid, "terrain"), self.io(uid, "in"))
        self.assertNotIn("sin evaluar", message)
        found, expected = self.expected(_module("drillholes.surface").raster_sampler(raster))
        self.assertEqual(found.notes, ())
        self.assertIn(("DH-W05", "S-12"), [(issue.code, issue.hole_name)
                                           for issue in found.issues])
        self.assertListed(found)
        self.assertEqual(export("EXEC_DEFAULT", filepath=str(outside), overwrite=True),
                         {"FINISHED"})
        self.assertEqual(outside.read_bytes(), expected)

        self.ps.close()
        self.assertEqual(self.listed(), [])


if __name__ == "__main__":
    unittest.main()
