# SPDX-License-Identifier: GPL-3.0-or-later
"""V-ref como base de RecMin (spec 005, T33; RNF-005-05, RF-005-13).

``tests.support.recmin.vref_script`` escribe V-ref (``tests/data/dh/sintetico.py``) como el
guion de una base de RecMin con el esquema de ``recmin_v12.sql``, del que ``build_mdb.ps1``
crea la base ACE de la prueba de rendimiento de la importación de RecMin
(``tests/rendimiento/test_dh_mdb_perf.py``, con el motor). Aquí, sin motor y a escala 1/100
(20 sondeos): el guion tiene las tablas del esquema 12 sin las adicionales, con una columna
``ELEMENTO n`` Single por elemento, y leído como lo daría el extractor
(``tests.support.recmin.raw_tables``: los Single en ``float32``) por el lector de RecMin da los
mismos sondeos, estaciones, tramos, leyes y catálogos que V-ref en CSV con el lector de
tablas: la base mide lo mismo que mide la importación de CSV (RNF-005-01).
"""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from tests.data.dh import sintetico
from tests.support import dh_sets, recmin
from tests.support.package import import_geoblender
from tests.support.trees import remove_tree

csv_tables = import_geoblender("interop.csv_tables")
tabular = import_geoblender("interop.drillholes_tabular")
reader = import_geoblender("interop.recmin.drillholes")
model = import_geoblender("drillholes.model")

SCALE = 0.01  # 20 sondeos
ROLES = {
    "bocas.csv": tabular.TableRole.COLLAR,
    "desviaciones.csv": tabular.TableRole.SURVEY,
    "litologia.csv": tabular.TableRole.LITHOLOGY,
    "analisis_columnas.csv": tabular.TableRole.ASSAY_WIDE,
    "litologias.csv": tabular.TableRole.LITHOLOGY_CATALOG,
    "elementos.csv": tabular.TableRole.ELEMENT_CATALOG,
}


def _declaration(units: dict[str, str], **rules: Any) -> Any:
    return model.SourceDeclaration(
        crs=dh_sets.H25830, vertical=dh_sets.V5782, azimuth_ref=model.AzimuthRef.GRID,
        declination_deg=None, inclination_convention=model.InclinationConvention.NEGATIVE_DOWN,
        units=units, value_rules=model.ValueRules(decimal_mark=",", **rules),
        date_format="%d/%m/%Y")


def _csv_set(tables: dict[str, Any]) -> Any:
    """V-ref en CSV leído con el lector de tablas (lo que lee la importación de CSV)."""
    found = {ROLES[name]: csv_tables.Table(list(table.header), [list(row) for row in table.rows],
                                           list(range(2, len(table.rows) + 2)))
             for name, table in tables.items()}
    units = {row[0]: row[2] for row in tables["elementos.csv"].rows}
    dset, report = tabular.read_drillholes(found, None, _declaration(units))
    assert not report.rejected, report.rejected[:3]
    return dset


def _rows(columns: Any, *fields: str) -> list[tuple[Any, ...]]:
    """Las filas de unas columnas (``fields``), ordenadas; los números, ``float``."""
    values = [getattr(columns, field) for field in fields]
    return sorted(tuple(float(v) if isinstance(v, np.floating) else
                        int(v) if isinstance(v, np.integer) else v for v in row)
                  for row in zip(*values, strict=True))


class VrefScriptTest(unittest.TestCase):
    tables: dict[str, Any]
    parsed: dict[str, Any]
    csv: Any
    read: Any
    report: Any

    @classmethod
    def setUpClass(cls) -> None:
        folder = Path(tempfile.mkdtemp(prefix="gb-vrs-"))
        cls.addClassCleanup(remove_tree, folder)
        cls.tables = sintetico.vref_tables(SCALE)
        script = folder / recmin.VREF_SQL
        script.write_text(recmin.vref_script(cls.tables), encoding="utf-8", newline="\n")
        cls.parsed = recmin.parse_sql(script)
        cls.read, cls.report = reader.read_drillholes(
            recmin.raw_tables(script), _declaration({}, negative_is_below_dl=True))
        cls.csv = _csv_set(cls.tables)

    def test_script_has_the_schema_12_tables_and_vref_rows(self) -> None:
        """RNF-005-05: el guion tiene las tablas del esquema 12 sin las adicionales, las
        muestras con un ``ELEMENTO n`` Single por cada uno de los 20 elementos y las filas de
        V-ref (los sondeos, sus estaciones, sus tramos y sus muestras), con «<LD» como el
        valor negativo y la versión de esquema 12."""
        v12 = recmin.parse_sql(recmin.VREF_SCHEMA)
        self.assertEqual(list(self.parsed), [name for name in v12
                                             if name not in recmin.VREF_EXTRA_TABLES])
        samples = self.parsed[recmin.VREF_SAMPLES]
        elements = [column for column in samples.columns if column.name.startswith("ELEMENTO")]
        self.assertEqual([(column.name, column.type) for column in elements],
                         [(f"ELEMENTO {n}", "SINGLE") for n in range(1, 21)])
        counts = {name: len(table.rows) for name, table in self.parsed.items() if table.rows}
        self.assertEqual(counts, {
            "sondeos": 20, "angulos": 200, "litologia": 500, "idlitologia": 10,
            "muestras": len(self.tables["analisis_columnas.csv"].rows), "elementos": 20,
            "actualizacion": 1})
        self.assertEqual(self.parsed["actualizacion"].rows, ({"ULTIMA": 12},))
        below = [(row[4 + k], samples.rows[i][f"ELEMENTO {k + 1}"])
                 for i, row in enumerate(self.tables["analisis_columnas.csv"].rows)
                 for k in range(20) if row[4 + k].startswith("<")]
        self.assertTrue(below)
        for text, value in below:
            self.assertEqual(-value, Decimal(text[1:].replace(",", ".")))

    def test_read_like_the_csv_vref(self) -> None:
        """RF-005-13, RNF-005-05: leído como lo da el extractor (Single en ``float32``), el
        lector de RecMin da, sin rechazos, los mismos sondeos (X, Y, Z y profundidad, que
        deduce), estaciones, tramos de litología, leyes (con su unidad y «<LD») y catálogos
        (colores y densidades; unidades de los elementos) que V-ref en CSV con el lector de
        tablas."""
        read, csv = self.read, self.csv
        self.assertEqual(self.report.rejected, ())
        self.assertEqual(_rows(read.collars, "name", "x", "y", "z", "depth"),
                         _rows(csv.collars, "name", "x", "y", "z", "depth"))
        self.assertEqual(_rows(read.surveys, "hole_name", "depth", "azimuth", "inclination"),
                         _rows(csv.surveys, "hole_name", "depth", "azimuth", "inclination"))
        self.assertEqual(_rows(read.lithology, "hole_name", "from_m", "to_m", "code"),
                         _rows(csv.lithology, "hole_name", "from_m", "to_m", "code"))
        fields = ("hole_name", "from_m", "to_m", "element", "value", "unit", "detection_flag")
        self.assertEqual(_rows(read.assays, *fields), _rows(csv.assays, *fields))
        self.assertEqual(len(read.assays), 20 * len(self.tables["analisis_columnas.csv"].rows))
        self.assertEqual(
            sorted((code.code, code.color, code.density) for code in read.catalogs.lithology),
            sorted((code.code, code.color, code.density) for code in csv.catalogs.lithology))
        self.assertEqual(sorted((element.code, element.unit)
                                for element in read.catalogs.elements),
                         sorted((element.code, element.unit)
                                for element in csv.catalogs.elements))


if __name__ == "__main__":
    unittest.main()
