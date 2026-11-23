# SPDX-License-Identifier: GPL-3.0-or-later
"""Las capas de cortas de una versión frente a QGIS 4.2 (spec 018, T27; HU-018-4; RF-018-33, RF-012-20, RF-015-27, RF-008-56; plan 018 §5.2.3 y §7.1; D-19; la gemela de
``test_ref_road_layer_qgis`` para ``des_pit_<vNN>`` y ``des_sky_<vNN>``).

Caso de referencia: V01 con **una corta** calculada (la de las pruebas del hito) y sus capas de verdad (``des_pit_v01`` y ``des_sky_v01``, las que escribe ``des.pit_layer`` tras cada orden de cortas, con su
estilo en la misma transacción) y, en una **copia** del GeoPackage del proyecto, una capa de prueba de cada una (``des_pit_v99`` y ``des_sky_v99``) con seis líneas de los tres tipos en todos los estados y
su estilo escrito por ``insert_version_styles``. La referencia externa es QGIS 4.2 (``GEOBLENDER_QGIS_DIR``): PyQGIS sin interfaz, con su GDAL y un perfil temporal, sobre esa copia (QGIS puede pasar a WAL
lo que abre: ``docs/trampas.md`` §6):

- **La geometría** (RF-018-33): líneas **con Z** (``LineStringZ``, no multipartes, válidas) cuyos vértices son los de las polilíneas de la corta (``des_pbl_``) y de su línea de cielo (``des_psk_``), con la
  cota en la Z (bit a bit; el anillo, cerrado).
- **El estilo por tipo** (RF-018-33, RF-012-20): la capa de polilíneas se abre con el estilo por defecto de ``layer_styles``: un renderizador por reglas con **una categoría por tipo** (pie, cresta, rampa y
  «otro tipo») y por estado (normal, atenuada si está descartada y marcada si perdió el apoyo); cada línea cae en **una** sola regla; los símbolos son líneas. La línea de cielo, su único tipo en sus tres
  estados.
- **La marca «no editable»** (RF-008-56, D-19): QGIS da por de solo lectura **todos** los campos (``fid`` y las columnas) y enseña la nota de la capa; la protección de la capa entera es el bloqueo de
  RF-008-56 (``qgis_editable`` falso en el dato).

Sin QGIS (sin la variable, o sin su GDAL) la clase se omite con «[ENTORNO] qgis», que ``tools/check.py`` cuenta como «VERDE CON OMISIONES»; la T27 no se cierra sin una ejecución con QGIS anotada.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.referencia.core.test_ref_road_layer_qgis import INSPECT_SCRIPT, LINE, LINESTRING_Z
from tests.support import qgis
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.resources import requires
from tests.unit.design.milestone_pit_create import BY, NAME
from tests.unit.design.milestone_pit_layer import LayerCase
from tests.unit.design.milestone_pit_prepare_checks import request
from tests.unit.gis.masks.test_declared_blocked import core_operations_registered

cstyles = import_geoblender("core.constraints.styles")
gpkg = import_geoblender("core.gpkg")
pit_layer = import_geoblender("design.pit_layer")

REAL_PIT, REAL_SKY = "des_pit_v01", "des_sky_v01"
TEST_PIT, TEST_SKY = "des_pit_v99", "des_sky_v99"
ROWS = (
    ("PIT-001", "Corta 1", "current", "foot", 100.0),
    ("PIT-001", "Corta 1", "current", "crest", 110.0),
    ("PIT-002", "Corta 2", "stale", "ramp", 120.0),
    ("PIT-003", "Corta 3", "discarded", "foot", 130.0),
    ("PIT-004", "Corta 4", "support_removed", "crest", 140.0),
    ("PIT-005", "Corta 5", "current", "ramp", 150.0),
)
"""Las líneas de la capa de prueba: (código, nombre, estado, tipo, cota de inicio)."""


@requires(qgis.QGIS, qgis.QGIS_HINT)
class QgisPitLayerReferenceTest(LayerCase):
    """V01 con una corta y sus capas de verdad, y unas de prueba en la copia, vistas con QGIS (véase el módulo)."""

    seen: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        started = cls.enterClassContext(qgis.PyqgisProcess(INSPECT_SCRIPT))  # QGIS arranca (≈ 1 s) mientras se prepara el proyecto
        super().setUpClass()
        cls.enterClassContext(core_operations_registered())
        cls.clock.advance(minutes=1)
        cls.uid(cls, cls.calculate(cls, request()).create(decided_by=BY))
        cls.after_chain()
        out = cls.enterClassContext(project_tmp("gb-rp-"))
        copy = out / "copia"
        copy.mkdir()
        target = copy / "project.gpkg"
        shutil.copyfile(cls.project.database_path, target)
        cls.write_test_layers(target)
        result = started.finish(str(target), json.dumps([REAL_PIT, REAL_SKY, TEST_PIT, TEST_SKY]), REAL_PIT)
        if result.returncode != 0:
            raise RuntimeError(f"PyQGIS no abrió las capas: {qgis.output_of(result)}")
        (line,) = [text for text in result.stdout.splitlines() if text.startswith("RESULT")]
        cls.seen = json.loads(line.removeprefix("RESULT"))

    @classmethod
    def write_test_layers(cls, path: Path) -> None:
        """Las capas de prueba (:data:`ROWS`) en ``path`` (la copia), con el formato y la escritura de ``design.pit_layer`` y su estilo por defecto."""
        srs = cls.project.record.crs_epsg
        lines, sky = [], []
        for number, (code, name, state, kind, z0) in enumerate(ROWS):
            west = 725_000.0 + 100.0 * number
            points = np.array([[west, 4_400_000.0, z0], [west + 40.0, 4_400_020.0, z0], [west + 80.0, 4_400_000.0, z0]])
            lines.append(pit_layer.PitLayerRow(code, name, state, number + 1, kind, points, ordinal=number + 1, z_m=z0, length_m=95.0))
            sky.append(pit_layer.SkyLayerRow(code, name, state, number + 1, 95.0, points))
        db = gpkg.GpkgConnection.open_write(path)
        try:
            with db.transaction() as conn:
                pit_layer.write_pit_layer(conn, TEST_PIT, lines, srs_id=srs)
                pit_layer.write_sky_layer(conn, TEST_SKY, sky, srs_id=srs)
                assert cstyles.insert_version_styles(conn, [TEST_PIT, TEST_SKY]) == (TEST_PIT, TEST_SKY)
        finally:
            db.close()

    def layer(self, name: str) -> dict[str, Any]:
        info = self.seen["layers"][name]
        self.assertTrue(info["valid"], name)
        return info

    def test_a_the_real_layers_are_lines_with_z_and_the_z_of_each_vertex_is_the_level(self) -> None:
        """RF-018-33: ``des_pit_v01`` y ``des_sky_v01`` se abren en QGIS como **líneas con Z** (``LineStringZ``, no multiparte, válidas), una por polilínea y por línea de cielo de la corta, cuyos
        vértices y cota son los de su ``des_pbl_`` y su ``des_psk_`` (bit a bit; el anillo, cerrado)."""
        source = self.polylines_of(NAME)
        info = self.layer(REAL_PIT)
        self.assertEqual((info["wkb"], info["features"]), (LINESTRING_Z, len(source)))
        for geometry, line in zip(info["geometry"], source, strict=True):
            self.assertTrue(geometry["valid"] and not geometry["multi"] and geometry["wkb"] == LINESTRING_Z)
            wanted = np.vstack([line.points, line.points[:1]]) if line.closed else line.points
            self.assertEqual(np.array(geometry["points"], dtype=np.float64).tobytes(), np.asarray(wanted, dtype=np.float64).tobytes())
        sky = self.layer(REAL_SKY)
        self.assertEqual((sky["wkb"], sky["features"]), (LINESTRING_Z, len(self.skyline_of(NAME))))
        for geometry, line in zip(sky["geometry"], self.skyline_of(NAME), strict=True):
            self.assertEqual(np.array(geometry["points"], dtype=np.float64).tobytes(), np.asarray(line.points, dtype=np.float64).tobytes())

    def test_b_the_real_layers_open_with_the_style_by_kind_and_every_field_read_only(self) -> None:
        """RF-018-33, RF-012-20, RF-008-56, D-19: ``des_pit_v01`` se abre **con su estilo por defecto**: un renderizador por reglas con una categoría por tipo (pie, cresta, rampa y «otro tipo») en sus tres
        estados (doce reglas) y cada polilínea cae en **una**, la de su tipo; ``des_sky_v01``, una categoría en sus tres estados; los campos (``fid`` y las columnas) son de solo lectura todos, las capas llevan su
        nota y los datos no son editables a mano."""
        info = self.layer(REAL_PIT)
        self.assertEqual((info["renderer"], len(info["rules"])), ("RuleRenderer", 12))
        self.assertEqual(info["fields"], ["fid", *pit_layer.PIT_COLUMN_NAMES])
        self.assertTrue(all(info["read_only"]), dict(zip(info["fields"], info["read_only"], strict=True)))
        self.assertIn("no se edita a mano", info["notes"])
        kinds = {"foot": "Pie", "crest": "Cresta", "ramp": "Rampa"}
        for attributes, matched in info["matches"]:
            by_name = dict(zip(info["fields"], attributes, strict=True))
            self.assertEqual(matched, [kinds[by_name["kind"]]])
        sky = self.layer(REAL_SKY)
        self.assertEqual((sky["renderer"], len(sky["rules"]), sky["fields"]), ("RuleRenderer", 3, ["fid", *pit_layer.SKY_COLUMN_NAMES]))
        self.assertTrue(all(sky["read_only"]))
        for attributes, matched in sky["matches"]:
            self.assertEqual(matched, ["Línea de cielo"])
        self.assertFalse(info["layer_read_only"], "la marca de capa no viaja en el estilo (RF-008-56 la protege)")
        with self.project.read() as conn:
            self.assertEqual(conn.execute("SELECT DISTINCT qgis_editable FROM gb_dataset WHERE name IN ('des_pit', 'des_sky') AND status = 'current'").fetchall(), [(0,)])
        flag = self.seen["layer_flag"]
        self.assertIsNotNone(flag, "la capa no tiene estilo por defecto en layer_styles")
        self.assertTrue(flag["applied"] and not flag["read_only"] and flag["editing"], flag)

    def test_c_each_line_falls_in_one_rule_by_kind_and_state(self) -> None:
        """RF-018-33, RF-012-20: en la capa de prueba cada línea cae en **una** regla: de su tipo, la normal, la **atenuada** si está descartada o la **marcada** si perdió el apoyo; 3 tipos y «otro» ×
        3 estados, sin solaparse; y los símbolos son líneas, el atenuado menos opaco, discontinuo y más fino, y el marcado, de trazo y punto y más grueso."""
        info = self.layer(TEST_PIT)
        self.assertEqual((info["renderer"], info["wkb"], len(info["rules"])), ("RuleRenderer", LINESTRING_Z, 12))
        expected = {"PIT-001": [["Pie"], ["Cresta"]], "PIT-002": [["Rampa"]], "PIT-003": [["Pie descartada"]], "PIT-004": [["Cresta con el apoyo retirado"]], "PIT-005": [["Rampa"]]}
        found: dict[str, list[list[str]]] = {}
        for attributes, matched in info["matches"]:
            found.setdefault(attributes[1], []).append(matched)
        self.assertEqual(found, expected)
        by_label = {label: symbol for label, _condition, symbol in info["rules"]}
        self.assertTrue(all(symbol["type"] == LINE for symbol in by_label.values()))
        normal, faded, marked = (by_label[label] for label in ("Pie", "Pie descartada", "Pie con el apoyo retirado"))
        self.assertEqual(normal["alpha"], 255)
        self.assertLess(faded["alpha"], normal["alpha"])
        self.assertNotEqual(faded["pen_style"], normal["pen_style"])
        self.assertLess(faded["width"], normal["width"])
        self.assertEqual(marked["color"], "#{:02x}{:02x}{:02x}".format(*cstyles.MARK_COLOR))
        self.assertGreater(marked["width"], normal["width"])
        sky = self.layer(TEST_SKY)
        self.assertEqual({tuple(matched) for _attributes, matched in sky["matches"]}, {("Línea de cielo",), ("Línea de cielo descartada",), ("Línea de cielo con el apoyo retirado",)})

    def test_d_the_values_of_the_test_layer_are_the_ones_of_the_table(self) -> None:
        """RF-018-33: lo que lee QGIS de cada línea de la capa de prueba son **los valores de la tabla** que escribió ``design`` (la corta, su estado, el banco, el tipo, la cota y la longitud) y la geometría, la
        línea de tres vértices con la Z de cada uno."""
        info = self.layer(TEST_PIT)
        self.assertEqual(info["features"], len(ROWS))
        by_ordinal = {int(dict(zip(info["fields"], attributes, strict=True))["ordinal"]): dict(zip(info["fields"], attributes, strict=True)) for attributes, _matched in info["matches"]}
        for number, (code, name, state, kind, z0) in enumerate(ROWS, start=1):
            with self.subTest(code=code, kind=kind):
                names = by_ordinal[number]
                self.assertEqual((names["code"], names["name"], names["state"], names["kind"], int(names["bench"])), (code, name, state, kind, number))
                self.assertEqual((float(names["z_m"]), float(names["length_m"])), (z0, 95.0))
        self.assertEqual([[point[2] for point in geometry["points"]] for geometry in info["geometry"]], [[z0] * 3 for *_rest, z0 in ROWS])
        self.assertTrue(all(geometry["valid"] and not geometry["multi"] and geometry["wkb"] == LINESTRING_Z for geometry in info["geometry"]))


if __name__ == "__main__":
    import unittest

    unittest.main()
