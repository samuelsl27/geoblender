# SPDX-License-Identifier: GPL-3.0-or-later
"""Curvas de nivel y validación de una superficie en Blender (spec 006, T30; HU-006-3,
HU-006-4; plan 006 §5.3.4, §5.3.5, §5.6.1 a §5.6.4 y §5.6.8).

Con el proyecto y las fuentes de ``test_ops_dtm`` (``DtmOperatorsCase``) y la cadena de
``test_ops_tin``: la orden ``geoblender.gis_create_contours``, operador de la procedencia de
la 008 (la operación ``gis.contours`` con su trabajo ``gis_contours``), y
``geoblender.gis_validate_surface`` (su trabajo ``gis_validate``), que es un informe
diagnóstico (spec §11): no es una operación ni escribe en el proyecto. La validación de una
rejilla y en solo lectura la prueba ``test_ops_contours_validate``.

- RF-006-27, RF-008-26: las dos órdenes de la T30 sustituyen a las provisionales de la 003 y
  están disponibles; habilitar registra el ``OperationDef`` de ``gis.contours`` con su
  recálculo, y la validación no es una operación; sin proyecto, ``poll`` es falso con el
  paso previo.
- RF-006-18, RF-006-26, D18: las curvas de la rejilla importada y las del TIN que sale de
  ella quedan en ``gis_cnt_<nombre>`` (``elevation``, ``is_index``, ``closed`` y
  ``length_m``) iguales bit a bit a las de ``contours_from_raster`` y ``contours_from_tin``,
  como dato con su hash y su operación, que consume la superficie; los campos del diálogo
  salen con los parámetros del proyecto; un valor tecleado distinto es un ajuste y no se
  consume; la cota base, un ajuste.
- RF-008-26: con la equidistancia de las maestras del proyecto cambiada, el recálculo rehace
  las curvas con la nueva.
- RF-006-23, D17: el informe de la validación de ese TIN dice, con su valor y su unidad en
  español, el área y el % sin dato, sus huecos, lo que queda fuera de la ventana, las cotas
  fuera del rango plausible (el de por defecto, que no se registra en el proyecto), el % de
  triángulos planos, el lado máximo y los degenerados: las cifras de ``validate_tin``.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import json
import time
import unittest
from pathlib import Path
from typing import Any

import bpy
import numpy as np

from tests.blender.gis.test_ops_dtm import _module
from tests.blender.gis.test_ops_tin import CONVERT, TinOperatorsCase

CONTOURS = "geoblender.gis_create_contours"
VALIDATE = "geoblender.gis_validate_surface"
Z_RANGE = "gis.validate.z_range_m"
CONSUMED = ["gis.contours.index_every_m", "gis.contours.index_offset_m",
            "gis.contours.min_length_m", "gis.contours.simplify_m"]


class ContoursCase(TinOperatorsCase):
    """Lo de ``TinOperatorsCase`` con la comparación de una tabla de curvas guardada y la
    orden de validar."""

    def assertStoredContours(self, name: str, expected: list[Any]) -> None:
        """La tabla del dato ``name`` tiene una fila por curva de ``expected``, en su orden,
        con su geometría bit a bit (la cerrada, con su primer vértice repetido al final), su
        cota, si es maestra, si es cerrada y su longitud en planta."""
        stored = _module("gis.store").load_features(self.project, name)
        self.assertGreater(len(expected), 0)
        self.assertEqual(len(stored.geometries), len(expected))
        attributes = stored.attributes
        for index, line in enumerate(expected):
            coords = np.vstack([line.xyz, line.xyz[:1]]) if line.closed else line.xyz
            self.assertTrue(np.array_equal(stored.geometries[index], coords), index)
            self.assertEqual((attributes["elevation"][index],
                              bool(attributes["is_index"][index]),
                              bool(attributes["closed"][index]),
                              attributes["length_m"][index]),
                             (line.elevation, line.is_index, line.closed, line.length_m), index)

    def consumed(self, op_uid: str) -> list[str]:
        return sorted(key for (key,) in self.rows(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", op_uid))

    def validate(self, **props: Any) -> str:
        """La orden de validar (``EXEC_DEFAULT``) y su trabajo hasta el final: no deja
        ninguna operación pendiente; devuelve los avisos de la sesión, juntos."""
        self.ps.take_notices()
        result, op_uid = self.run_op(VALIDATE, **props)
        self.assertEqual((result, op_uid), ({"FINISHED"}, None))
        self.finish()
        return "\n".join(self.ps.take_notices())

    def gpkg_sha(self) -> str:
        return hashlib.sha256((Path(self.project.root) / "project.gpkg").read_bytes()).hexdigest()


class ContoursTest(ContoursCase):
    def test_commands_and_declaration(self) -> None:
        """RF-006-27, RF-008-26 (plan §5.6.3 y §5.6.8): las dos órdenes son las reales y
        están disponibles; habilitar registra ``gis.contours`` con su recálculo y la orden de
        las curvas en sus ``commands``; validar no es una operación (ningún ``OperationDef``
        la nombra). Sin proyecto, las dos dicen el paso previo."""
        commands = _module("bl.ui.commands")
        contract = _module("core.provenance.contract")
        for idname in (CONTOURS, VALIDATE):
            with self.subTest(orden=idname):
                cls = commands.registered_class(idname)
                self.assertIsNotNone(cls)
                self.assertFalse(commands.is_provisional(cls))
                self.assertTrue(commands.is_available(idname))
        definition = contract.OPERATIONS["gis.contours"]
        self.assertTrue(callable(definition.recompute))
        self.assertIn(CONTOURS, definition.commands)
        self.assertFalse([op for op, found in contract.OPERATIONS.items()
                          if VALIDATE in found.commands])
        self.ps.close()
        self.assertFalse(bpy.ops.geoblender.gis_create_contours.poll())
        self.assertFalse(bpy.ops.geoblender.gis_validate_surface.poll())
        self.assertTrue(self.gis_ops.open_reason().startswith("Primero abra un proyecto"))

    def test_contours_of_the_dtm_and_of_its_tin(self) -> None:
        """RF-006-18, RF-006-26, D18, RF-008-26, RF-006-23: los campos del diálogo salen con
        los cinco parámetros de las curvas del proyecto («sin confirmar»). Las curvas del MDT
        importado con la equidistancia tecleada (2 m, un ajuste) y la cota base por defecto
        (0 m) son las de ``contours_from_raster`` bit a bit, en ``gis_cnt_dron`` con su hash y
        su operación ``gis.contours`` (consume el MDT y los otros cuatro parámetros); el
        recálculo con las maestras del proyecto cada 4 m las rehace con ellas. Las del TIN que
        sale del MDT, con la equidistancia del proyecto tecleada igual (se consume) y la cota
        base 0,5 m tecleada con coma (un ajuste), son las de ``contours_from_tin``. La
        validación de ese TIN da el informe de ``validate_tin`` sin escribir en el
        proyecto."""
        project = self.open()
        self.assertTrue(bpy.ops.geoblender.gis_create_contours.poll())
        self.assertTrue(bpy.ops.geoblender.gis_validate_surface.poll())
        store = _module("gis.store")
        gis = _module("gis")
        fields = self.gis_ops.contour_fields(project)
        self.assertEqual(fields, {"interval": ("1", "[ADO] sin confirmar"),
                                  "index_every": ("5", "[ADO] sin confirmar"),
                                  "index_offset": ("0", "[ADO] sin confirmar"),
                                  "simplify": ("0", "[ADO] sin confirmar"),
                                  "min_length": ("0", "[ADO] sin confirmar")})
        self.import_dtm(self.source("geotiff/f64_strip.tif"), "MDT dron")
        self.ps.take_notices()
        uid = self.launch(CONTOURS, source="gis_src_mdt_dron", interval="2", name="Dron")
        op_type, status, _reason, message, settings, software, _executor, _ = \
            self.operation(uid)
        self.assertEqual((op_type, status, software), ("gis.contours", "done", "{}"))
        self.assertEqual(json.loads(settings), {"name": "Dron", "source": "gis_src_mdt_dron",
                                                "base_m": 0.0, "interval_m": 2.0})
        self.assertEqual(self.consumed(uid), CONSUMED)
        (source_uid,) = self.dataset("gis_src_mdt_dron")[:1]
        self.assertEqual(self.rows("SELECT item_uid, role FROM gb_operation_io WHERE "
                                   "operation_uid = ? AND direction = 'in'", uid),
                         [(source_uid, "source")])
        _uid, locator, input_uid, content, writer = self.dataset("gis_cnt_dron")
        self.assertEqual((locator, input_uid, writer), ("gis_cnt_dron", None, uid))
        self.assertRegex(content, r"^[0-9a-f]{64}$")
        raster = store.load_raster(project, "gis_src_mdt_dron")
        expected = gis.contours_from_raster(raster, interval_m=2.0, name="Dron")
        self.assertStoredContours("gis_cnt_dron", expected)
        index = sum(1 for line in expected if line.is_index)
        closed = sum(1 for line in expected if line.closed)
        self.assertIn(f"Curvas de nivel gis_cnt_dron de «gis_src_mdt_dron»: {len(expected)} "
                      f"curvas ({index} maestras, {closed} cerradas)", message)
        self.assertIn("equidistancia 2 m, cota base 0 m, maestras cada 5 m", message)
        self.assertIn(message, self.ps.take_notices())

        params = _module("core.params")
        with project.write_transaction() as conn:
            params.ParameterStore(project).change(
                conn, "gis.contours.index_every_m", value=4.0, kind="ADOPTADO",
                source="Criterio de la prueba", source_kind="document",
                decided_by="la prueba", reason="Maestras cada 4 m en el plano")
        steps = _module("core.provenance.recompute").recompute_steps(project)
        for step in steps:
            self.jobs_ops.tick()
            time.sleep(0.002)
        self.assertEqual([str(unit.status) for unit in step.result.results], ["done"])
        (new_uid,) = self.rows("SELECT uid FROM gb_operation WHERE supersedes_uid = ?", uid)[0]
        self.assertEqual(self.operation(new_uid)[1], "done")
        self.assertEqual(json.loads(self.operation(new_uid)[4])["interval_m"], 2.0)
        self.assertEqual(self.rows("SELECT value FROM gb_operation_param WHERE operation_uid = ? "
                                   "AND key = 'gis.contours.index_every_m'", new_uid),
                         [("4.0",)])
        again = gis.contours_from_raster(raster, interval_m=2.0, index_every_m=4.0, name="Dron")
        self.assertNotEqual([line.is_index for line in again],
                            [line.is_index for line in expected])
        self.assertStoredContours("gis_cnt_dron", again)

        self.launch(CONVERT, direction="DTM_TO_TIN", source="gis_src_mdt_dron", name="Dron")
        tin_uid = self.launch(CONTOURS, source="gis_tin_dron", interval="1", base="0,5",
                              name="Dron TIN")
        _type, status, _reason, _message, settings, *_ = self.operation(tin_uid)
        self.assertEqual(status, "done")
        self.assertEqual(json.loads(settings), {"name": "Dron TIN", "source": "gis_tin_dron",
                                                "base_m": 0.5})
        self.assertEqual(self.consumed(tin_uid), sorted([*CONSUMED,
                                                         "gis.contours.interval_m"]))
        tin = self.tin_file("gis_tin_dron")
        expected = gis.contours_from_tin(tin, interval_m=1.0, base_m=0.5, index_every_m=4.0,
                                         name="Dron TIN")
        self.assertStoredContours("gis_cnt_dron_tin", expected)

        # RF-006-23: la validación del TIN, nombrado, sin escribir nada en el proyecto (ni
        # el rango plausible, que se lee con su valor por defecto).
        fmt = _module("core.i18n").format_number
        before = (self.counts(), self.gpkg_sha())
        text = self.validate(source="gis_tin_dron")
        self.assertEqual((self.counts(), self.gpkg_sha()), before)
        self.assertIsNone(params.ParameterStore(project).get(Z_RANGE))
        report = gis.validate_tin(tin, window=project.window)
        holes = "; ".join(f"{fmt(area, 2)} m²" for area in report.hole_areas_m2)
        for line in (
            f"Validación del TIN «gis_tin_dron»: área {fmt(report.area_m2, 2)} m², sin dato "
            f"{fmt(report.nodata_area_m2, 2)} m² ({fmt(report.nodata_pct, 2)} %)",
            f"Huecos interiores: {len(report.hole_areas_m2)} ({holes})",
            f"Triángulos con algún vértice fuera de la ventana de trabajo: "
            f"{fmt(report.cells_outside_window, 0)}",
            f"Vértices con la cota fuera del rango plausible de {fmt(-500, 0)} a "
            f"{fmt(5000, 0)} m: 0",
            f"Triángulos planos: {fmt(report.flat_pct, 2)} %; lado máximo: "
            f"{fmt(report.max_edge_m, 3)} m; triángulos degenerados: "
            f"{fmt(report.degenerate, 0)}",
        ):
            self.assertIn(line, text)
        self.assertNotIn("sin dato no declarado", text)


if __name__ == "__main__":
    unittest.main()
