# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar una rejilla a GeoTIFF en Blender (spec 006, T31; HU-006-6; plan 006 §5.3.5,
§5.6.4 y §5.6.6; D21).

Con el proyecto y las fuentes de ``test_ops_dtm`` (``DtmOperatorsCase``): la orden
``geoblender.gis_export_raster`` (Topografía ▸ Exportar ▸ Superficie o rejilla a GeoTIFF…),
operador de la procedencia de la 008: la operación ``gis.export_raster``, que consume la
rejilla, con su trabajo ``gis_export``. La de capas a GeoPackage, ``test_ops_export_gpkg``.

- RF-006-27, RF-008-51: las dos órdenes de la T31 son las reales y están disponibles;
  habilitar registra sus ``OperationDef`` (no se repiten solas: sin recálculo).
- RF-006-24 (T07): el entregable es el GeoTIFF float32 con −9999 del perfil ``deliverable``
  (los mismos bytes), con el CRS del proyecto. Dentro de ``exports/`` del proyecto es el dato
  ``exports`` ``gis_exp_<ruta>``, sin seguimiento, con su hash; fuera, la operación no tiene
  salida registrada (D21). Ningún ajuste lleva una ruta absoluta: solo el nombre del fichero.
- Spec §8: un destino que ya existe no se sustituye sin confirmarlo (desde un guion,
  ``overwrite``); bloqueado por otro programa, la operación falla con
  ``gis.raster_target_locked`` y el anterior sigue intacto, sin fichero a medias.
- RF-008-15, RF-006-10 (plan §5.6.6): exportar a una carpeta de ``GEOBLENDER_READ_ONLY_DIRS``
  (también por su ruta UNC) o a la carpeta de la fuente de una entrada se rechaza nombrándola,
  sin empezar ninguna operación ni escribir nada; tampoco a otra carpeta del proyecto ni con
  otra extensión.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import os
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import bpy

from tests.blender.gis.test_ops_dtm import DtmOperatorsCase, _folder_state, _module

EXPORT_RASTER = "geoblender.gis_export_raster"
EXPORT_GPKG = "geoblender.gis_export_gpkg"
VARIABLE = "GEOBLENDER_READ_ONLY_DIRS"
UNC = "\\\\nas-imga\\expedientes"


class ExportRasterTest(DtmOperatorsCase):
    def exported(self) -> Path:
        """El MDT del dron importado; devuelve la carpeta de su fuente."""
        path = self.source("geotiff/f64_strip.tif", "mdt/dron_2026.tif")
        self.import_dtm(path, "MDT dron")
        return path.parent

    def expected_bytes(self) -> bytes:
        """El GeoTIFF entregable de ``gis_src_mdt_dron`` escrito con el perfil de T07."""
        reference = self.tmp / "referencia.tif"
        self.geotiff.GeoTiffIO().write(self.stored("gis_src_mdt_dron"), reference,
                                       profile="deliverable")
        return reference.read_bytes()

    def no_paths(self, settings: str) -> None:
        self.assertEqual(_module("core.paths").find_absolute_paths(json.loads(settings)), [])
        self.assertNotIn(str(self.tmp), settings)

    def test_commands_and_declarations(self) -> None:
        """RF-006-27, RF-008-51 (plan §5.6.3): las dos órdenes son las reales y están
        disponibles; habilitar registra ``gis.export_raster`` y ``gis.export_gpkg`` sin
        recálculo, cada uno con su orden; sin proyecto, no están disponibles."""
        commands = _module("bl.ui.commands")
        contract = _module("core.provenance.contract")
        for idname, op_type in ((EXPORT_RASTER, "gis.export_raster"),
                                (EXPORT_GPKG, "gis.export_gpkg")):
            with self.subTest(orden=idname):
                cls = commands.registered_class(idname)
                self.assertIsNotNone(cls)
                self.assertFalse(commands.is_provisional(cls))
                self.assertTrue(commands.is_available(idname))
                definition = contract.OPERATIONS[op_type]
                self.assertIsNone(definition.recompute)
                self.assertEqual(definition.commands, (idname,))
        self.ps.close()
        self.assertFalse(bpy.ops.geoblender.gis_export_raster.poll())
        self.assertFalse(bpy.ops.geoblender.gis_export_gpkg.poll())

    def test_geotiff_inside_and_outside_the_project(self) -> None:
        """RF-006-24, RF-008-51, D21, spec §8: la rejilla importada a ``exports/mdt.tif`` es el
        entregable de T07 (los mismos bytes), dato ``exports`` sin seguimiento con su hash,
        y la operación consume la rejilla; fuera del proyecto, sin salida registrada. Los
        ajustes, sin rutas. Sobre un fichero que ya existe, sin confirmarlo, no se escribe ni
        empieza nada; confirmado, se sustituye; abierto por otro programa, la operación falla
        y el anterior queda intacto, sin temporales."""
        project = self.open()
        root = Path(project.root)
        self.exported()
        expected = self.expected_bytes()
        (source_uid,) = self.dataset("gis_src_mdt_dron")[:1]
        self.ps.take_notices()

        inside = root / "exports" / "mdt.tif"
        uid = self.launch(EXPORT_RASTER, source="gis_src_mdt_dron", filepath=str(inside))
        op_type, status, _reason, message, settings, software, executor, _ = self.operation(uid)
        self.assertEqual((op_type, status, software, executor),
                         ("gis.export_raster", "done", "{}", "job_thread"))
        self.assertEqual(json.loads(settings), {"source": "gis_src_mdt_dron", "file": "mdt.tif",
                                                "in_exports": True})
        self.no_paths(settings)
        self.assertEqual(inside.read_bytes(), expected)
        self.assertEqual(self.rows("SELECT item_uid, role FROM gb_operation_io WHERE "
                                   "operation_uid = ? AND direction = 'in'", uid),
                         [(source_uid, "exported")])
        (row,) = self.rows("SELECT name, kind, store, locator, reader, tracked, content_sha256, "
                           "operation_uid, uid FROM gb_dataset WHERE store = 'exports'")
        self.assertEqual(row[:6], ("gis_exp_mdt_tif", "raster", "exports", "exports/mdt.tif",
                                   "gis.geotiff@1", 0))
        self.assertEqual(row[7], uid)
        registry = _module("core.datasets.registry")
        with project.read() as conn:
            record = registry.get(conn, row[8])
            self.assertEqual(registry.content_digest(conn, project, record).content_sha256,
                             row[6])
        self.assertIn("GeoTIFF «mdt.tif» exportado desde «gis_src_mdt_dron»", message)
        self.assertIn("gis_exp_mdt_tif", message)
        self.assertIn(message, self.ps.take_notices())

        outside = self.tmp / "cliente" / "mdt_cliente.tif"
        outside.parent.mkdir()
        uid = self.launch(EXPORT_RASTER, source="gis_src_mdt_dron", filepath=str(outside))
        _type, status, _reason, message, settings, *_ = self.operation(uid)
        self.assertEqual(status, "done")
        self.assertEqual(json.loads(settings), {"source": "gis_src_mdt_dron",
                                                "file": "mdt_cliente.tif", "in_exports": False})
        self.no_paths(settings)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation_io WHERE "
                                   "operation_uid = ? AND direction = 'out'", uid), [(0,)])
        self.assertEqual(outside.read_bytes(), expected)
        self.assertIn("fuera del proyecto", message)

        # Ya existe: sin confirmar no se escribe ni empieza nada; confirmado, se sustituye.
        outside.write_bytes(b"anterior")
        before = self.counts()
        with self.assertRaises(RuntimeError) as caught:
            self.run_op(EXPORT_RASTER, source="gis_src_mdt_dron", filepath=str(outside))
        self.assertIn("Ya existe «mdt_cliente.tif»: confirme que se sustituye",
                      str(caught.exception))
        self.assertEqual((self.counts(), outside.read_bytes()), (before, b"anterior"))
        self.launch(EXPORT_RASTER, source="gis_src_mdt_dron", filepath=str(outside),
                    overwrite=True)
        self.assertEqual(outside.read_bytes(), expected)

        # Abierto por otro programa: falla sin tocarlo ni dejar temporales.
        outside.write_bytes(b"abierto")
        with outside.open("rb"):
            uid = self.launch(EXPORT_RASTER, source="gis_src_mdt_dron", filepath=str(outside),
                              overwrite=True)
        _type, status, reason, *_ = self.operation(uid)
        self.assertEqual(status, "failed")
        self.assertIn("No se puede sustituir «mdt_cliente.tif»: otro programa lo tiene abierto",
                      reason)
        self.assertEqual(outside.read_bytes(), b"abierto")
        self.assertEqual(sorted(path.name for path in outside.parent.iterdir()),
                         ["mdt_cliente.tif"])
        self.assertEqual(sorted(path.name for path in (root / "exports").iterdir()),
                         ["mdt.tif"])

    def test_refused_targets_write_nothing(self) -> None:
        """RF-008-15, RF-006-10, plan §5.6.6: exportar a una carpeta de
        ``GEOBLENDER_READ_ONLY_DIRS`` (por su unidad o por su ruta UNC), a la carpeta de la
        fuente de una entrada, a otra carpeta del proyecto o con otra extensión se rechaza
        nombrando la carpeta, la entrada o el motivo: no empieza ninguna operación ni se
        escribe nada. Un MDT importado en ED50 tampoco se entrega: los entregables van en el
        CRS del proyecto (RF-006-24)."""
        project = self.open()
        root = Path(project.root)
        source_folder = self.exported()
        dossiers = self.tmp / "expedientes"
        dossiers.mkdir()
        mapped = self.tmp / "unidad"
        mapped.mkdir()
        paths = _module("core.paths")

        def resolve(path: Path) -> Path:  # «unidad» es una unidad de red: su UNC
            text = os.fspath(path)
            if text.lower().startswith(os.fspath(mapped).lower()):
                return Path(UNC + text[len(os.fspath(mapped)):])
            return path

        watched = {folder: _folder_state(folder)
                   for folder in (dossiers, mapped, source_folder, root / "rasters",
                                  root / "exports")}
        before = self.counts()
        cases: list[tuple[Path, str, dict[str, Any]]] = [
            (dossiers / "mdt.tif", str(dossiers), {VARIABLE: str(dossiers)}),
            (mapped / "mdt.tif", UNC, {VARIABLE: UNC}),
            (source_folder / "mdt_entrega.tif", "MDT dron", {}),
            (root / "rasters" / "mdt.tif", "no en su carpeta de entregables", {}),
            (root / "exports" / "mdt.png", "lleva la extensión .tif/.tiff, no «.png»", {}),
        ]
        session = self.session
        for target, named, environ in cases:
            with self.subTest(destino=target.name, carpeta=target.parent.name), \
                    mock.patch.dict(os.environ, environ), \
                    mock.patch.object(session, "read_only_dirs", lambda: paths.ReadOnlyDirs
                                      .from_sources(os.environ.get(VARIABLE), [],
                                                    resolve=resolve)):
                with self.assertRaises(RuntimeError) as caught:
                    self.run_op(EXPORT_RASTER, source="gis_src_mdt_dron", filepath=str(target))
                self.assertIn(named, str(caught.exception))
        self.assertEqual(self.counts(), before)
        for folder, state in watched.items():
            self.assertEqual(_folder_state(folder), state, folder.name)
        # RF-006-24: un MDT importado en ED50 no se entrega en su CRS (el del proyecto, no).
        self.import_dtm(self.source("geotiff/f32_epsg23030.tif"), "MDT ED50")
        before = self.counts()
        with self.assertRaises(RuntimeError) as caught:
            self.run_op(EXPORT_RASTER, source="gis_src_mdt_ed50",
                        filepath=str(root / "exports" / "ed50.tif"))
        self.assertIn("un entregable va en las referencias del proyecto", str(caught.exception))
        self.assertEqual((self.counts(), _folder_state(root / "exports")),
                         (before, watched[root / "exports"]))


if __name__ == "__main__":
    unittest.main()
