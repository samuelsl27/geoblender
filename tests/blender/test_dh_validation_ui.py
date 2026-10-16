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
- RF-005-18, spec §8 (T56; F-1 de la verificación única): con la rejilla, la diferencia de
  cada boca con el MDT (su cota menos la del MDT en su posición, en m) queda guardada con la
  validación y se ve: una fila DH-W05 por boca en la lista y en el CSV exportado (el aviso, si
  pasa de la tolerancia; si no, «Información»; una boca fuera del MDT, «Sin evaluar») y su
  resumen en el informe de la operación. Sin rejilla, ``dh_validation_issue`` no cambia.
- RF-005-19, RF-008-15, D21: ``geoblender.dh_export_validation_report`` (la operación
  ``dh.export_validation``, que consume ``dh_validation_issue``) escribe exactamente el CSV de
  T11; dentro de ``exports/`` es un dato del proyecto; fuera, ninguno; un destino que ya existe
  no se sustituye sin confirmarlo; una carpeta de solo lectura, otra del proyecto u otra
  extensión se rechazan sin escribir nada. Sin validación, no empieza.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import csv
import io
import json
import math
import os
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

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
OUTSIDE_DTM = "S-30"
OUTSIDE_LINE = f"{OUTSIDE_DTM};700100,500;4400040,500;805,000;50,00;;;DD;C-2025;14/04/2025;" \
               "15/04/2025;no\n"
"""Una boca dentro de la ventana de trabajo y fuera del MDT de ``tests/data/gis`` (E 700 000
a 700 064, N 4 400 000 a 4 400 048), añadida a la copia de las bocas de DH-W05 (T56)."""
DEM_TOLERANCE_M = 2.0  # dh.validation.collar_dem_tolerance_m, por defecto
LISTED_LEVELS = {"Error": "ERROR", "Aviso": "WARNING", "Información": "INFO",
                 "Sin evaluar": "NOT_EVALUATED"}
"""El nivel de una fila de la lista por el de su fila del CSV (en español)."""


def _metres(value: float) -> str:
    """Una diferencia como la dice un mensaje de la validación en español: redondeada al mm,
    con coma y sin decimales si es entera («0», «5», «-2,5»)."""
    shown = round(value, 3) + 0.0
    return str(int(shown)) if shown.is_integer() else repr(shown).replace(".", ",")


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
        with open(self.sources / "dh_w05_bocas.csv", "a", encoding="utf-8", newline="") as out:
            out.write(OUTSIDE_LINE)
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
        """La lista de la pestaña: las filas del informe ``found`` (las de su CSV), en su
        orden, con su nivel."""
        rows = _module("drillholes.report").rows(found)
        self.assertEqual(self.listed(), [(row[0], row[1], LISTED_LEVELS[row[2]], row[11])
                                         for row in rows])

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
        RF-005-18 y spec §8 (T56): la diferencia de cada boca con el MDT se ve en una fila
        DH-W05 por boca de la lista y del CSV exportado (el aviso de S-12; «Información», con
        su diferencia al mm, las demás; «Sin evaluar», la que está fuera del MDT) y en el
        informe de la operación (la boca fuera y el resumen); sin rejilla, la tabla de
        incidencias no cambia. Cerrar el proyecto vacía la lista."""
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
        # Sin rejilla, solo incidencias: la tabla (y su hash) como antes de T56.
        self.assertLessEqual({level for (level,) in self.rows(
            f"SELECT DISTINCT level FROM {ISSUES}")}, {"error", "warning"})

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
        # RF-005-18 (T56): la diferencia de cada boca con el MDT (la bilineal de la 006), a la
        # vista: una fila DH-W05 por boca en la lista, con su diferencia al mm en el mensaje.
        sampler = _module("drillholes.surface").raster_sampler(raster)
        collars = self.rows("SELECT name, x, y, z FROM dh_collar ORDER BY fid")
        dem = sampler.sample(np.array([[x, y] for _name, x, y, _z in collars]))
        dz = {name: z - float(value)
              for (name, _x, _y, z), value in zip(collars, dem, strict=True)}
        self.assertTrue(math.isnan(dz.pop(OUTSIDE_DTM)))
        listed = [(hole, level, text) for hole, code, level, text in self.listed()
                  if code == "DH-W05"]
        self.assertEqual(sorted(hole for hole, _level, _text in listed),
                         sorted([*dz, OUTSIDE_DTM]))
        for hole, level, text in listed:
            with self.subTest(sondeo=hole):
                if hole == OUTSIDE_DTM:
                    self.assertEqual(level, "NOT_EVALUATED")
                    self.assertIn("fuera del MDT", text)
                else:
                    self.assertEqual(level, "WARNING" if abs(dz[hole]) > DEM_TOLERANCE_M
                                     else "INFO")
                    self.assertIn(f"da {_metres(dz[hole])} m", text)
        self.assertEqual([hole for hole, level, _text in listed if level == "WARNING"],
                         ["S-12"])
        found, expected = self.expected(sampler)
        self.assertEqual([(note.code, note.hole_name) for note in found.notes],
                         [("DH-W05", OUTSIDE_DTM)])
        self.assertListed(found)
        # El informe de la operación: la boca fuera del MDT y el resumen de las diferencias.
        i18n = _module("core.i18n")
        self.assertIn(f"{OUTSIDE_DTM}: La boca está fuera del MDT", message)
        self.assertIn(f"Cota de las bocas menos la del MDT: {len(dz)} bocas comparadas, de "
                      f"{i18n.format_number(min(dz.values()), 3)} m a "
                      f"{i18n.format_number(max(dz.values()), 3)} m", message)
        # El CSV exportado (el informe guardado): la misma fila DH-W05 de cada boca.
        self.assertEqual(export("EXEC_DEFAULT", filepath=str(outside), overwrite=True),
                         {"FINISHED"})
        self.assertEqual(outside.read_bytes(), expected)
        exported = csv.reader(io.StringIO(expected.decode("utf-8-sig")), delimiter=";")
        self.assertEqual(sorted((row[0], row[2]) for row in exported if row[1] == "DH-W05"),
                         sorted([*((hole, "Información") for hole in dz if hole != "S-12"),
                                 ("S-12", "Aviso"), (OUTSIDE_DTM, "Sin evaluar")]))

        self.ps.close()
        self.assertEqual(self.listed(), [])


if __name__ == "__main__":
    unittest.main()
