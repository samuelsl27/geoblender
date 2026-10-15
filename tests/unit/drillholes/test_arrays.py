# SPDX-License-Identifier: GPL-3.0-or-later
"""Las tablas de los sondeos a arrays por partes (spec 005, T53; RNF-005-06, RF-005-02; plan
005 §5.6.7).

Con V-ref, convertir de una vez los 500 000 análisis a los arrays que van a un trabajo
(``drillholes.arrays.tables_arrays``) era una llamada de 0,8–1,0 s del hilo de Blender (T32:
la base, su validación y la vista). Ahora una tabla se convierte por partes de
``arrays.PART_ROWS`` filas (``arrays.table_parts``), una por paso, cada una en su entrada de
``in/`` (``drillholes.jobs.packed_parts``), y el trabajo las junta (``arrays.merge_parts``, en
``drillholes.jobs.input_arrays``) en los mismos arrays, bit a bit, que la tabla entera: nada
cambia en lo que calcula ni en lo que escribe. Se cuenta (las filas de cada parte), no se
cronometra.
"""

from __future__ import annotations

import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from tests.support import dh_sets
from tests.support.package import import_geoblender

arrays = import_geoblender("drillholes.arrays")
dh_jobs = import_geoblender("drillholes.jobs")
model = import_geoblender("drillholes.model")

PART = 3
"""Las filas de una parte en estas pruebas: varias partes con unas pocas filas."""


def _collars() -> list[Any]:
    """Siete bocas con todos los tipos de columna: los enteros opcionales (categoría y
    prioridad) solo a partir de la cuarta (las tres primeras, una parte sin ninguno), textos
    vacíos, sin valor solo en una parte, con tildes y emojis, fechas y ``extra``."""
    found = []
    for number in range(7):
        found.append(model.Collar(
            f"S-{number:02d}", 700_000.0 + number / 3, 4_400_000.0 - number * 0.1, 500.25,
            100.0 + number, hole_type="DD" if number % 2 else None, planned=number == 3,
            category=None if number < 3 else number, priority=None if number < 5 else 1,
            campaign=None if number in (4, 5) else ("Campaña ñandú 🪨" if number == 6 else ""),
            start_date=None if number == 1 else dt.date(2026, 1 + number, 3),
            comments="sí" if number == 2 else None,
            extra={"orden": number, "nota": "á"} if number % 3 == 0 else {}))
    return found


def _set() -> Any:
    """Un conjunto pequeño con bocas, estaciones, tramos y análisis (con sus catálogos)."""
    collars = _collars()
    names = [collar.name for collar in collars]
    surveys = [model.SurveyStation(name, depth, 45.0, -60.0 + depth / 100)
               for name in names for depth in (0.0, 50.0)]
    lithology = [model.LithologyInterval(name, start, start + 2.5, "MIN" if start % 5 else "SUE",
                                         description=None if start > 5 else "óxidos")
                 for name in names[:4] for start in (0.0, 2.5, 5.0, 7.5)]
    assays = [model.AssayValue(name, start, start + 1.0, element, value, "g/t",
                               reported_value=None if value is None else f"{value}")
              for name in names[:3] for start in (0.0, 1.0, 2.0)
              for element, value in (("Au", 0.25 + start), ("Cu", None))]
    catalogs = model.Catalogs(lithology=(model.LithologyCode("SUE", color="#8B6B3D"),
                                         model.LithologyCode("MIN")),
                              elements=(model.Element("Au", "g/t"), model.Element("Cu", "%")))
    return model.DrillholeSet.from_records(crs=dh_sets.H25830, vertical=dh_sets.V5782,
                                           collars=collars, surveys=surveys,
                                           lithology=lithology, assays=assays,
                                           catalogs=catalogs)


def _tables(dset: Any) -> dict[str, Any]:
    return {name: getattr(dset, name) for name in model.TABLES}


def _rows(found: dict[str, np.ndarray]) -> int:
    """Las filas de los arrays de una parte (todos tienen las mismas)."""
    sizes = {len(array) for array in found.values()}
    assert len(sizes) == 1, sizes
    return sizes.pop()


class PartsTest(unittest.TestCase):
    def assertSameArrays(self, found: dict[str, np.ndarray],  # noqa: N802 - unittest
                         expected: dict[str, np.ndarray]) -> None:
        """Las mismas claves y, en cada una, el mismo tipo, la misma forma y los mismos
        bytes."""
        self.assertEqual(sorted(found), sorted(expected))
        for key, array in expected.items():
            with self.subTest(clave=key):
                self.assertEqual(found[key].dtype, array.dtype)
                self.assertEqual(found[key].shape, array.shape)
                self.assertEqual(found[key].tobytes(), array.tobytes())

    def test_parts_join_into_the_arrays_of_the_whole_table(self) -> None:
        """RNF-005-06, RF-005-02 (T53): cada tabla, por partes de como mucho ``rows`` filas
        (``table_parts``), da al juntarlas (``merge_parts``) los arrays de ``tables_arrays`` de
        la tabla entera, bit a bit: los números (también NaN), los textos con el ancho mayor y
        su máscara de nulos (también si solo una parte tiene alguno), los enteros opcionales de
        una parte que no tiene ninguno, las fechas y ``extra``. Con una parte o ninguna (una
        tabla vacía), lo mismo; ``arrays.PART_ROWS`` son las filas por defecto."""
        dset = _set()
        for name, columns in _tables(dset).items():
            whole = arrays.tables_arrays({name: columns})
            for rows in (1, PART, 4, 1_000):
                with self.subTest(tabla=name, filas=rows):
                    parts = list(arrays.table_parts(name, columns, rows=rows))
                    self.assertEqual(len(parts), -(-len(columns) // rows))
                    for part in parts:
                        self.assertLessEqual(_rows(part), rows)
                    self.assertSameArrays(arrays.merge_parts(parts), whole)
        self.assertEqual(arrays.PART_ROWS, 50_000)
        self.assertEqual(len(list(arrays.table_parts("collars", dset.collars))), 1)
        self.assertEqual(arrays.merge_parts([]), {})

    def test_mixed_integers_and_texts_fail_like_the_whole_table(self) -> None:
        """RF-005-02 (T53): una columna de enteros opcionales con un texto en otra parte, o con
        un sí/no, es ``TypeError`` como en ``tables_arrays``; una tabla que no es del modelo o
        unas filas por parte que no valen, ``ValueError``."""
        collars = _set().collars
        for bad in ("A", True):
            category = collars.category.copy()
            category[0] = bad
            broken = collars.take(np.arange(len(collars)), category=category)
            with self.subTest(valor=bad):
                with self.assertRaises(TypeError):
                    arrays.tables_arrays({"collars": broken})
                with self.assertRaises(TypeError):
                    list(arrays.table_parts("collars", broken, rows=PART))
        for name, rows in (("bocas", PART), ("collars", 0), ("collars", True)):
            with self.subTest(tabla=name, filas=rows), self.assertRaises((ValueError,
                                                                           TypeError)):
                list(arrays.table_parts(name, collars, rows=rows))

    def test_packed_parts_reach_the_job_as_whole_tables(self) -> None:
        """RNF-005-06 (T53; plan §5.6.7): ``packed_parts`` da, paso a paso, una entrada de
        ``in/`` por parte (``<nombre>_npz-<tabla>-<n>``) de como mucho ``rows`` filas y otra con
        los catálogos; escritas como las escribe ``launch_job(arrays=…)``, el trabajo las lee
        juntas (``input_arrays``) en los arrays de ``tables_arrays`` del conjunto entero, bit a
        bit (también una entrada de una sola parte, de antes, ``<nombre>_npz-<parte>``)."""
        dset = _set()
        steps = list(dh_jobs.packed_parts("base", _tables(dset), dset.catalogs, rows=PART))
        expected = arrays.tables_arrays(_tables(dset), dset.catalogs)
        for step in steps:
            (entry, raw), = step.items()
            self.assertTrue(entry.startswith("base_" + dh_jobs.PACKED_TAG), entry)
            with np.load(io.BytesIO(raw.tobytes()), allow_pickle=False) as data:
                if entry.endswith("catalogs"):
                    self.assertEqual(list(data.files), ["catalogs"])
                else:
                    self.assertLessEqual(_rows({key: data[key] for key in data.files}), PART)
        parts = sum(-(-len(columns) // PART) for columns in _tables(dset).values())
        self.assertEqual(len(steps), parts + 1)
        with tempfile.TemporaryDirectory(prefix="gb-t53-") as folder:
            loose: dict[str, np.ndarray] = {}
            for step in steps:
                loose.update(step)
            loose.update(dh_jobs.packed_arrays("other", "rest", {"x": np.arange(3)}))
            self.assertSameArrays(dh_jobs.input_arrays(_context(Path(folder), loose), "base"),
                                  expected)
            self.assertSameArrays(dh_jobs.input_arrays(_context(Path(folder), loose), "other"),
                                  {"x": np.arange(3)})


def _context(folder: Path, loose: dict[str, np.ndarray]) -> Any:
    """Lo que ``input_arrays`` mira del contexto de un trabajo: sus entradas escritas como
    las deja ``JobDir.write_array``."""
    inputs = {}
    for name, array in loose.items():
        path = folder / f"{name}.npy"
        if not path.exists():
            with path.open("wb") as handle:
                np.save(handle, array, allow_pickle=False)
        inputs[name] = path.name
    return SimpleNamespace(request=SimpleNamespace(inputs=inputs),
                           input_path=lambda name: folder / inputs[name])


if __name__ == "__main__":
    unittest.main()
