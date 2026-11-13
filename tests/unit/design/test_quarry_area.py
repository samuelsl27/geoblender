# SPDX-License-Identifier: GPL-3.0-or-later
"""El recinto excavable de la cantera (spec 014, T06; HU-014-1; RF-014-01; plan 014 A1, §5.2.3,
§5.3.1, §5.3.2).

- ``design.quarry.excavation_area``: el recinto es el corte admitido de las máscaras de la versión
  con dato de terreno (``R = masks.cut_allowed() ∧ isfinite(z)``); vacío, un error que dice el área
  de lo que lo vacía (``area_parts``: el perímetro fuera del límite, los intocables, el resguardo
  hacia dentro, lo que no admite corte y lo que no tiene terreno).
- ``design.steps.excavation_area_run``: «Calcular» el recinto deja su rejilla (1 dentro, sin dato
  fuera) en un temporal y **nada registrado**; «Crear» registra ``des.excavation_area`` con el dato
  ``des_rcn_`` y la cifra ``des.rcn_area_m2`` (error relativo ≤ 10⁻⁹ frente a las celdas); cerrar a
  mitad no deja nada; un recinto vacío se rechaza al avanzar sin escribir nada.

Sobre la cantera sintética de ``tests.support.quarry_fixtures`` (T01): el recinto tiene
:data:`~tests.support.quarry_fixtures.CUT_ALLOWED_CELLS` celdas de 1 m², contadas a mano.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

quarry = import_geoblender("design.quarry")
steps = import_geoblender("design.steps")
provenance = import_geoblender("design.provenance")
messages = import_geoblender("design.messages")
combine = import_geoblender("gis.masks.combine")
geotiff_reader = import_geoblender("gis.geotiff.reader")

NAME = "Recinto de la cantera"
DATASET = "des_rcn_recinto_de_la_cantera"
CELL_M2 = qfx.STEP_M * qfx.STEP_M
OUTSIDE_LIMIT_CELLS = int(qfx.STRIP_M2)
"""Perímetro ∖ límite: la franja de (20, 60) a (40, 340), 5.600 celdas."""
INNER_BAND_CELLS = int(qfx.INWARD_BAND_M2)
"""El resguardo de 5 m hacia dentro del límite dentro del perímetro: 2.800 celdas."""
PERIMETER_CELLS = int(qfx.PERIMETER_AREA_M2)
"""El perímetro de actuación: 95.200 celdas."""
CUT_BIT = np.uint16(int(combine.ClassBit.CUT_ALLOWED))


def recompute(request: Any) -> Any:  # nunca se llama: solo declara que se repite sola
    raise AssertionError("estas pruebas no recalculan")


def reproduce(request: Any) -> Iterator[Any]:  # idem
    raise AssertionError("estas pruebas no reproducen")


def quarry_definitions() -> tuple[Any, ...]:
    """Los cinco tipos de la 014 con sus funciones y sus cifras, como los registra ``bl``."""
    return (*provenance.quarry_operation_defs(
        {t: recompute for t in provenance.QUARRY_VERSION_TYPES},
        {t: reproduce for t in provenance.QUARRY_REPRODUCIBLE}), *provenance.QUARRY_FIGURES)


def last(found: Iterator[Any]) -> Any:
    """El último ``Progress`` de unos pasos."""
    item = None
    for item in found:
        pass
    return item


def without_cut(masks: Any) -> Any:
    """Las mismas máscaras sin ninguna celda con corte admitido (un recinto vacío)."""
    return dataclasses.replace(masks, classes=masks.classes & ~CUT_BIT)


class ExcavationAreaTest(qfx.QuarryProjectCase):
    """El recinto en el dominio (sin proyecto que escribir) y su operación, sobre una copia del
    proyecto de la cantera por clase. Cada prueba de los pasos compara lo que había antes de
    empezar con lo que queda."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(*quarry_definitions()))
        cls.loaded = cls.masks(cls)  # type: ignore[arg-type]

    # --- Ayudas -------------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Todo lo que el cálculo podría dejar: operaciones, datos, tablas, cifras y ficheros."""
        with self.project.read() as conn:
            return {
                "operations": conn.execute("SELECT uid, status FROM gb_operation "
                                           "ORDER BY fid").fetchall(),
                "datasets": conn.execute("SELECT name, status FROM gb_dataset "
                                         "ORDER BY name").fetchall(),
                "tables": conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall(),
                "figures": conn.execute("SELECT count(*) FROM gb_figure").fetchall(),
                "files": sorted(path.name for path in (self.root / "rasters").iterdir())}

    def area_steps(self, name: str = "Recinto nuevo", **kw: Any) -> Iterator[Any]:
        kw.setdefault("masks", self.loaded)
        return steps.excavation_area_run(self.project, name, qfx.START_DATASET,
                                         version=self.v1.uid, **kw)

    def assertLeavesNothing(self, make: Callable[[], Iterator[Any]],  # noqa: N802
                            check: Callable[[Iterator[Any]], None]) -> None:
        before = self.snapshot()
        check(make())
        self.assertEqual(self.snapshot(), before)

    # --- El recinto (A1) ------------------------------------------------------------------------

    def test_the_area_is_the_cut_allowed_of_the_masks(self) -> None:
        """RF-014-01, A1: el recinto es el corte admitido de las máscaras de la versión con dato
        de terreno, una máscara nueva; sus celdas son las contadas a mano y su área, la de las
        celdas a ≤ 10⁻⁹ relativo. No modifica las entradas."""
        start = qfx.terrain()
        classes = self.loaded.classes.copy()
        area = quarry.excavation_area(self.loaded, start)
        self.assertEqual(area.dtype, np.bool_)
        self.assertEqual(area.shape, qfx.GRID.shape)
        self.assertTrue(np.array_equal(area, self.loaded.cut_allowed()))
        self.assertEqual(int(area.sum()), qfx.CUT_ALLOWED_CELLS)
        self.assertTrue(np.array_equal(start, qfx.terrain()), "el terreno no se toca")
        self.assertTrue(np.array_equal(self.loaded.classes, classes), "las máscaras no se tocan")
        outcome = quarry.area_outcome(NAME, area, qfx.GRID)
        expected = qfx.CUT_ALLOWED_CELLS * CELL_M2
        self.assertEqual(outcome.cells, qfx.CUT_ALLOWED_CELLS)
        self.assertLessEqual(abs(outcome.area_m2 - expected) / expected, 1e-9)
        self.assertTrue(np.array_equal(outcome.grid == 1.0, area))
        self.assertTrue(np.isnan(outcome.grid[~area]).all(), "fuera, sin dato")
        self.assertEqual(outcome.grid.dtype, np.float64)
        (figure,) = outcome.figures
        self.assertEqual((figure.key, figure.unit, dict(figure.scope)),
                         ("des.rcn_area_m2", "m2", {"name": "recinto_de_la_cantera"}))
        self.assertEqual(figure.value, outcome.area_m2)
        self.assertIn(NAME, outcome.message)

    def test_cells_without_terrain_are_outside(self) -> None:
        """RF-014-01, A1: una celda con corte admitido y sin dato de terreno no es del recinto."""
        start = qfx.terrain()
        hole = qfx.in_box((200.0, 200.0, 250.0, 230.0))
        start[hole] = np.nan
        area = quarry.excavation_area(self.loaded, start)
        self.assertEqual(int(area.sum()), qfx.CUT_ALLOWED_CELLS - 50 * 30)
        self.assertFalse(area[hole].any())

    def test_what_empties_the_area_adds_up_to_the_perimeter(self) -> None:
        """RF-014-01, A1: lo que vacía el recinto, por partes y en m² (las celdas contadas a mano),
        y con él suma el perímetro de actuación."""
        parts = quarry.area_parts(self.loaded, qfx.terrain())
        self.assertEqual([part.key for part in parts],
                         ["outside_limit", "untouchable", "inner_band", "no_cut", "no_terrain"])
        self.assertEqual([part.cells for part in parts],
                         [OUTSIDE_LIMIT_CELLS, qfx.TOWER_ZONE_CELLS, INNER_BAND_CELLS,
                          qfx.NO_CUT_CELLS, 0])
        self.assertEqual([part.area_m2 for part in parts],
                         [part.cells * CELL_M2 for part in parts])
        self.assertEqual(sum(part.cells for part in parts) + qfx.CUT_ALLOWED_CELLS,
                         PERIMETER_CELLS)

    def test_an_empty_area_is_an_error_with_what_empties_it(self) -> None:
        """RF-014-01 (spec §7): sin ninguna celda con corte admitido, o sin terreno, el recinto
        está vacío: error ``des.quarry_area_empty`` con la versión y, detrás, una nota con el área
        de cada parte que lo vacía (T51, F-12 (c): también en inglés, sin una palabra en
        español)."""
        empty = without_cut(self.loaded)
        with self.assertRaises(messages.DesignError) as caught:
            quarry.excavation_area(empty, qfx.terrain(), version="V01")
        error = caught.exception
        self.assertEqual(error.code, "des.quarry_area_empty")
        self.assertEqual(error.values["version"], "V01")
        self.assertEqual(error.values["value"], 0)
        no_cut = qfx.DOMAIN_CELLS - INNER_BAND_CELLS
        self.assertEqual(error.notes, (
            ("des.quarry_area_outside_limit", {"area": OUTSIDE_LIMIT_CELLS}),
            ("des.quarry_area_untouchable", {"area": qfx.TOWER_ZONE_CELLS}),
            ("des.quarry_area_inner_band", {"area": INNER_BAND_CELLS}),
            ("des.quarry_area_no_cut", {"area": no_cut})))
        for text in (f"Lo que lo vacía: Perímetro de actuación fuera del límite legal: "
                     f"{OUTSIDE_LIMIT_CELLS} m².",
                     f"Intocables y exclusiones: {qfx.TOWER_ZONE_CELLS} m².",
                     f"Resguardo hacia dentro del límite: {INNER_BAND_CELLS} m².",
                     f"Zonas sin corte, solo relleno o solo restauración: {no_cut} m²."):
            self.assertIn(text, error.text)
        self.assertNotIn("sin dato de terreno", error.text, "solo las partes con celdas")
        english = error.text_in("en")
        for text in (f"What empties it: Action perimeter outside the legal limit: "
                     f"{OUTSIDE_LIMIT_CELLS} m².",
                     f"Untouchables and exclusions: {qfx.TOWER_ZONE_CELLS} m².",
                     f"Buffer inside the limit: {INNER_BAND_CELLS} m².",
                     f"Zones with no cut, fill only or restoration only: {no_cut} m²."):
            self.assertIn(text, english)
        self.assertEqual(set(english) & set("áéíóúñ"), set(), english)
        with self.assertRaises(messages.DesignError) as caught:
            quarry.excavation_area(self.loaded, np.full(qfx.GRID.shape, np.nan))
        self.assertIn(f"Celdas sin dato de terreno: {qfx.CUT_ALLOWED_CELLS} m²",
                      caught.exception.text)
        self.assertIn(f"Cells without terrain data: {qfx.CUT_ALLOWED_CELLS} m²",
                      caught.exception.text_in("en"))
        nothing = dataclasses.replace(self.loaded,
                                      classes=np.zeros_like(self.loaded.classes))
        with self.assertRaises(messages.DesignError) as caught:
            quarry.excavation_area(nothing, qfx.terrain())
        self.assertEqual(caught.exception.notes, (("des.quarry_area_no_perimeter", {}),))
        self.assertIn("Lo que lo vacía: El perímetro de actuación no tiene ninguna celda en la "
                      "rejilla.", caught.exception.text)

    def test_a_terrain_of_another_shape_is_a_programming_error(self) -> None:
        with self.assertRaises(ValueError):
            quarry.excavation_area(self.loaded, np.zeros((3, 3)))

    # --- La operación (calcular, crear, cerrar) -------------------------------------------------

    def test_calculating_writes_nothing_until_create(self) -> None:
        """RF-014-01, RF-014-29 (D-14 de la 013): «Calcular» deja la rejilla del recinto en su
        temporal y nada más; «Cancelar» lo quita; «Crear» registra ``des.excavation_area`` con su
        dato ``des_rcn_`` (1 dentro, sin dato fuera), sus entradas (la superficie de partida y las
        máscaras) y su cifra ``des.rcn_area_m2``; el nombre ya no se puede repetir."""
        before = self.snapshot()
        found = list(self.area_steps(NAME))
        self.assertTrue(all(step.result is None for step in found[:-1]))
        calculation = found[-1].result
        self.assertIsInstance(calculation, steps.Calculation)
        self.assertEqual((calculation.op_type, calculation.name, calculation.version),
                         (provenance.EXCAVATION_AREA, NAME, "V01"))
        after = self.snapshot()
        (temporary,) = set(after["files"]) - set(before["files"])
        self.assertRegex(temporary, r"^des_rcn_recinto_de_la_cantera_v01\.tif\.tmp-[0-9a-f]+$")
        self.assertEqual({key: after[key] for key in after if key != "files"},
                         {key: before[key] for key in before if key != "files"},
                         "calcular no registra nada")
        calculation.discard()
        self.assertEqual(self.snapshot(), before, "descartar quita el temporal")

        calculation = last(self.area_steps(NAME)).result
        stored = calculation.create()
        self.assertFalse(calculation.open)
        uid = stored.handle.uid
        self.assertEqual(self.query("SELECT op_type, status FROM gb_operation WHERE uid = ?", uid),
                         [(provenance.EXCAVATION_AREA, "done")])
        record = self.record(DATASET, self.v1)
        self.assertIsNotNone(record)
        self.assertEqual(record.locator, f"rasters/{DATASET}_v01.tif")
        grid = geotiff_reader.read_geotiff(self.root / record.locator).values
        area = quarry.excavation_area(self.loaded, qfx.terrain())
        self.assertTrue(np.array_equal(grid == 1.0, area))
        self.assertTrue(np.isnan(grid[~area]).all())
        ((key, value, scope),) = self.query(
            "SELECT key, value, scope FROM gb_figure WHERE operation_uid = ?", uid)
        self.assertEqual((key, json.loads(scope)), ("des.rcn_area_m2",
                                                     {"name": "recinto_de_la_cantera"}))
        expected = qfx.CUT_ALLOWED_CELLS * CELL_M2
        self.assertLessEqual(abs(value - expected) / expected, 1e-9)
        roles = dict(self.query("SELECT role, item_kind FROM gb_operation_io WHERE "
                                "operation_uid = ? AND direction = 'in'", uid))
        self.assertIn(provenance.SURFACE_ROLE, roles)
        self.assertTrue(any(role.startswith("masks_") for role in roles), roles)
        settings = json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?",
                                         uid)[0][0])
        self.assertEqual(settings, provenance.excavation_area_settings(NAME, qfx.START_DATASET))
        with self.assertRaises(messages.DesignError) as caught:
            last(self.area_steps(NAME))
        self.assertEqual(caught.exception.code, "des.operation_name_repeated")

    def test_closing_the_steps_midway_leaves_nothing(self) -> None:
        """RF-014-29 (RF-013-33): cerrar los pasos a mitad —al preparar, al escribir, con la
        rejilla ya en su temporal— no deja nada."""
        found = list(self.area_steps(budget_s=1e-9))
        found[-1].result.discard()
        self.assertGreater(len(found), 3)
        for advance in sorted({1, len(found) // 2, len(found) - 1}):
            with self.subTest(advance=advance, phase=found[advance - 1].phase):
                def cut(iterator: Iterator[Any], advance: int = advance) -> None:
                    for _ in range(advance):
                        next(iterator)
                    iterator.close()  # type: ignore[attr-defined]

                self.assertLeavesNothing(lambda: self.area_steps(budget_s=1e-9), cut)

    def test_an_empty_area_is_refused_when_advancing_and_writes_nothing(self) -> None:
        """RF-014-01 (spec §7): un recinto vacío se rechaza al avanzar, antes de escribir nada."""
        def refused(iterator: Iterator[Any]) -> None:
            with self.assertRaises(messages.DesignError) as caught:
                last(iterator)
            self.assertEqual(caught.exception.code, "des.quarry_area_empty")
            self.assertEqual(caught.exception.values["version"], "V01")

        self.assertLeavesNothing(lambda: self.area_steps(masks=without_cut(self.loaded)),
                                 refused)
