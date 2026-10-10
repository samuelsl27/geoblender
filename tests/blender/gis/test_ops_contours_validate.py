# SPDX-License-Identifier: GPL-3.0-or-later
"""Validar una rejilla en Blender (spec 006, T30; HU-006-4; plan 006 §5.3.4, §5.3.5 y §5.6.1).

Con el proyecto y las fuentes de ``test_ops_dtm`` (``DtmOperatorsCase``) y las ayudas de
``test_ops_contours``: la orden ``geoblender.gis_validate_surface`` sobre la superficie activa
en la vista, con su trabajo ``gis_validate``. Es un informe diagnóstico (spec §11): no es una
operación ni escribe en el proyecto; el rango plausible (``gis.validate.z_range_m``) es de
control y se lee del proyecto (D17). La de un TIN la prueba ``test_ops_contours``.

- RF-006-23: el informe de la rejilla dice, con su valor y su unidad en español, el área y el
  porcentaje sin dato, cada hueco interior con su área, las celdas fuera de la ventana de
  trabajo y las cotas fuera del rango plausible del proyecto (posible sin dato no
  declarado), con las cifras de ``validate_raster``.
- RF-006-27: sin escribir en el proyecto (ni operación, ni dato: el fichero del proyecto no
  cambia), también con el proyecto en solo lectura, donde las curvas no están disponibles.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from pathlib import Path
from typing import Any

import bpy

from tests.blender.gis.test_ops_contours import Z_RANGE, ContoursCase
from tests.blender.gis.test_ops_dtm import _module

NARROW = (699_980.0, 4_399_980.0, 700_040.0, 4_400_060.0)  # el MDT sale 24 columnas al este


class ValidateTest(ContoursCase):
    def active_surface(self, name: str, kind: str) -> Any:
        """Un objeto de la vista que muestra el dato ``name`` (``kind``), activo."""
        (uid,) = self.dataset(name)[:1]
        obj = bpy.data.objects.new("Superficie", None)
        bpy.context.scene.collection.objects.link(obj)
        self.addCleanup(bpy.data.objects.remove, obj)
        marks = getattr(obj, _module("bl.props.core").OBJECT_PROPERTY)
        marks.kind = kind
        marks.dataset_uid = uid
        bpy.context.view_layer.objects.active = obj
        return obj

    def test_grid_report_and_read_only_project(self) -> None:
        """RF-006-23, RF-006-27, D17: el MDT activo en la vista, con la ventana de trabajo que
        deja fuera sus 24 columnas del este y el rango plausible del proyecto cambiado a
        [−500, 820] m: el informe dice su área y su sin dato en m² y %, su hueco interior
        (12 m²), sus 1.152 celdas fuera de la ventana y las cotas por encima de 820 m (posible
        sin dato no declarado), con las cifras de ``validate_raster``; el fichero del proyecto
        no cambia y no queda ninguna operación. Con el proyecto en solo lectura, las curvas no
        están disponibles y validar sí, y valida."""
        project = self.open(window=NARROW)
        gis = _module("gis")
        fmt = _module("core.i18n").format_number
        self.import_dtm(self.source("geotiff/f64_strip.tif"), "MDT dron")
        params = _module("core.params")
        store = params.ParameterStore(project)
        with project.write_transaction() as conn:
            store.ensure_default(conn, Z_RANGE,
                                 geoblender_version=project.session.geoblender_version)
            store.change(
                conn, Z_RANGE, value=[-500.0, 820.0], kind="ADOPTADO",
                source="Criterio de la prueba", source_kind="document",
                decided_by="la prueba", reason="Cotas plausibles de la zona")
        self.active_surface("gis_src_mdt_dron", "DTM")
        before = (self.counts(), self.gpkg_sha())
        text = self.validate()
        self.assertEqual((self.counts(), self.gpkg_sha()), before)
        report = gis.validate_raster(self.stored("gis_src_mdt_dron"), window=project.window,
                                     z_range=(-500.0, 820.0))
        self.assertEqual((report.hole_areas_m2, report.cells_outside_window), ((12.0,), 1152))
        self.assertGreater(report.out_of_range, 0)
        for line in (
            f"Validación de la rejilla «gis_src_mdt_dron»: área {fmt(report.area_m2, 2)} m², "
            f"sin dato {fmt(report.nodata_area_m2, 2)} m² ({fmt(report.nodata_pct, 2)} %)",
            f"Huecos interiores: 1 ({fmt(12.0, 2)} m²)",
            f"Celdas con dato fuera de la ventana de trabajo: {fmt(1152, 0)}",
            f"Celdas con la cota fuera del rango plausible de {fmt(-500, 0)} a {fmt(820, 0)} "
            f"m: {fmt(report.out_of_range, 0)}",
            "Las cotas fuera del rango plausible pueden ser un sin dato no declarado",
        ):
            self.assertIn(line, text)
        self.assertNotIn("Triángulos planos", text)

        root = Path(project.root)
        self.ps.close()
        read_only = _module("core.paths").ReadOnlyDirs.from_sources(
            str(self.tmp / "proyectos"), [])
        opened = self.core.open_project(root, self.ps.session(), self.ps.userdata(),
                                        read_only=read_only).project
        self.ps.attach(opened)
        self.project = opened
        self.assertFalse(opened.writable)
        self.assertFalse(bpy.ops.geoblender.gis_create_contours.poll())
        self.assertTrue(bpy.ops.geoblender.gis_validate_surface.poll())
        self.assertIn(f"Celdas con dato fuera de la ventana de trabajo: {fmt(1152, 0)}",
                      self.validate(source="gis_src_mdt_dron"))


if __name__ == "__main__":
    unittest.main()
