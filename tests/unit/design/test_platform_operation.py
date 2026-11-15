# SPDX-License-Identifier: GPL-3.0-or-later
"""«Calcular» una plataforma y su resumen (spec 015, T12; HU-015-3; RF-015-03, RF-015-13, RF-015-29;
plan 015 §5.3.2 y §5.4; E1 y E2 de la spec), «Crear» (T13; HU-015-1; RF-015-01, RF-015-02, RF-015-04) y
recalcular y reproducir (T14; HU-015-1, HU-015-2; RF-015-02, RF-015-04, RF-015-16): casos (a), (b), (c), (d) y
(e) de ``test_platform_operation``.

Sobre la cantera sintética de la 014 con las capas de plataformas (``tests.support.entity_fixtures``)
y su rejilla gruesa de 2 m:

- **El cálculo compartido** (``entity_store.platform_compute_steps``): huella → aplicar → borde →
  perfil → ``platform_outcome``, por pasos y sin proyecto dentro, es lo que hacen a mano las
  funciones de las T06 a T09; lo comparten «Calcular», el recálculo y la reproducción.
- **«Calcular» no escribe** (RF-015-03, RF-015-29): ``steps.platform_run`` deja la superficie en un
  temporal y el resumen, y **nada en el proyecto** (ni la base de datos, ni operaciones, ni datos, ni
  parámetros); cerrarlo a mitad, descartar la cuenta o un fallo después del temporal no dejan nada;
  los rechazos salen al avanzar.
- **El resumen** (RF-015-03, RF-015-13): las cifras, los avisos (el salto creado, la magnitud, lo que
  llega a celdas sin dato fuera de la huella, el área que no mueve por la restricción de otra entidad
  con esa entidad, o con el nombre de la restricción) y lo que quedará obsoleto al crearla (si
  protege: las máscaras y lo que las usó; si inserta: la sucesora y las que le siguen; si sustituye
  una operación: lo que dependía de ella), con el singular («en 1 grupo»).
- **«Crear»** (T13; RF-015-01, RF-015-02, RF-015-04): registra todo en **una** transacción (la
  superficie ``des_psf_``, la tabla ``des_epr_`` con la huella en tramos de fila, el eje y los
  atributos, el informe ``des_prp_``, las cifras con el ámbito de la entidad, la operación con sus
  entradas y los parámetros de la entidad como filas de la versión con su origen); si algo falla a
  mitad no queda nada; no modifica la capa de origen; una plataforma que parte de otra consume su
  superficie y queda obsoleta, con la causa, si cambia la de la primera; una contrapendiente sin
  confirmar no se crea.
- **Recalcular** (T14, casos (c); RF-015-02, RF-015-16, RF-008-26): ``store.recompute_run`` repite la
  plataforma como una operación **nueva** que sustituye a la anterior (queda como historia) con los
  parámetros vigentes **de la versión** (no los de la capa: la cota, la pendiente y el ancho se copiaron al
  crearla, P-3), y da las mismas cifras y los mismos datos si nada cambió; un cambio que deja la superficie
  como estaba quita la marca de la siguiente sin recalcularla (RF-008-26); un parámetro que cambia entre
  preparar y empezar, o una contrapendiente que ya no está confirmada, no se registran.
- **Reproducir** (T14, casos (d); RF-015-02, RF-009-11): ``design.reproduce.reproduce_platform`` rehace, **sin
  proyecto**, desde lo congelado de V01.r1 (la capa, la partida, el apoyo, las máscaras y los parámetros
  congelados) la superficie, la tabla y el informe de cada plataforma con el **mismo hash** y las mismas
  cifras, sin escribir nada.
- **La cascada** (T14, casos (e); RF-015-16, RF-008-24, RF-009-19): cambiar un parámetro de P1 deja obsoleta
  P1 y, con su causa, P2, que consumió su superficie; «Recalcular lo obsoleto» las repite **en orden de
  dependencia** (P1 antes que P2, aunque la operación de P1 sea posterior a la de P2) y deja la revisión
  congelada como estaba (sus elementos no cambian y se reproduce igual).
"""

from __future__ import annotations

import dataclasses
import json
import math
import unittest
from collections.abc import Iterator
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, freeze_rows
from tests.unit.design import test_edges_operation as edges_test
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
builtin = import_geoblender("core.content.builtin")
datasets = import_geoblender("core.datasets.model")
gpkg_base = import_geoblender("core.gpkg.base")
operations = import_geoblender("core.provenance.operations")
versions_model = import_geoblender("core.versions.model")
core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_report = import_geoblender("design.report")
entities_module = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
design_reproduce = import_geoblender("design.reproduce")
freeze = import_geoblender("core.versions.freeze")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
figures_mod = import_geoblender("core.provenance.figures")
design_store = import_geoblender("design.store")
geotiff_reader = import_geoblender("gis.geotiff.reader")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
platform = import_geoblender("design.platform")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
res_provenance = import_geoblender("reserves.provenance")
steps = import_geoblender("design.steps")
timeutil = import_geoblender("core.timeutil")
zones_mod = import_geoblender("gis.masks.zones")
combine = import_geoblender("gis.masks.combine")

LOADING, TOWER, WORKSHOP = prep.LOADING, prep.TOWER, prep.WORKSHOP
START, GRID = prep.START, prep.GRID
CELL_M2 = 4.0
"""El área de una celda de la rejilla gruesa (2 × 2 m)."""
EDGE_HOLE_DATASET = "gis_dtm_borde"
"""El terreno de la cantera con un hueco sin dato **fuera** de la huella de la «Plataforma de carga»,
al norte de ella: las celdas de centro x de 201 a 209 m e y de 293 a 297 m (locales), donde su borde
corta."""
EDGE_HOLE_BOX = (200.0, 292.0, 210.0, 298.0)
EDGE_HOLE_CELLS = 15


def finish(work: Iterator[Any]) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    last = None
    for last in work:
        pass
    return last.result


def edge_hole_raster() -> Any:
    """El terreno de la cantera con el hueco de :data:`EDGE_HOLE_BOX` sin dato."""
    x, y = qfx.local_centers(GRID)
    left, bottom, right, top = EDGE_HOLE_BOX
    hole = (x > left) & (x < right) & (y > bottom) & (y < top)
    return gis.Raster(GRID, np.where(hole, np.nan, qfx.terrain(GRID)), efx.CRS, efx.VERTICAL)


def codes(found: Any) -> list[str]:
    """Los códigos de los avisos y notas de un resumen, en su orden."""
    return [notice.code for notice in found.notices]


def only(found: Any, code: str) -> Any:
    """El aviso ``code`` del resumen ``found`` (uno solo)."""
    matching = [notice for notice in found.notices if notice.code == code]
    assert len(matching) == 1, f"{code}: {codes(found)}"
    return matching[0]


class OperationCase(prep.PrepareCase):
    """Lo de ``PrepareCase`` más un terreno con un hueco fuera de la huella de la «Plataforma de carga»
    y ``calculate``, que calcula en V01 con sus máscaras y deja la cuenta descartada al acabar."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        res_fixtures.write_grids(cls.project, [("borde", edge_hole_raster())],
                                 message="Terreno de la prueba con un hueco junto a la plataforma")
        cls.clock.advance(minutes=1)

    def run_steps(self, asked: Any, **options: Any) -> Iterator[Any]:
        options.setdefault("masks", self.masks_v1)
        options.setdefault("version", self.v1.uid)
        return steps.platform_run(self.project, asked, **options)

    def calculate(self, asked: Any, **options: Any) -> Any:
        """«Calcular» ``asked`` hasta el final: la ``Calculation``, que se descarta al acabar."""
        calculation = finish(self.run_steps(asked, **options))
        self.addCleanup(calculation.discard)
        return calculation

    def temporaries(self) -> list[str]:
        return sorted(name for name in self.state()["files"] if ".tmp-" in name)


# ---------------------------------------------------------------------------------------------
# El cálculo compartido
# ---------------------------------------------------------------------------------------------


class ComputeStepsTest(OperationCase):
    """RF-015-29, RF-015-03 (el dominio): ``platform_compute_steps`` es la huella, aplicar, el borde, el
    perfil y las cifras de las T06 a T09, por pasos y sin proyecto dentro."""

    def test_a_it_is_what_the_pieces_do_by_hand_and_writes_nothing(self) -> None:
        """RF-015-03, RF-015-29: por pasos (con un presupuesto mínimo: muchos), el resultado es
        el de ``apply_platform``, ``platform_edge`` y ``platform_outcome`` seguidos (superficie,
        cifras y avisos), con o sin la huella ya calculada, y nada se escribe."""
        prepared = self.units(prep.request())
        applied = platform.apply_platform(prepared.job, prepared.footprint)
        edge = platform.platform_edge(prepared.job, prepared.footprint, applied, prepared.common)
        direct = platform.platform_outcome(prepared.job, prepared.footprint, applied, edge,
                                           prepared.common)
        before = self.state()
        work = entity_store.platform_compute_steps(prepared.job, prepared.common,
                                                   footprint=prepared.footprint, budget_s=1e-9)
        shown: list[Any] = []
        while True:
            try:
                shown.append(next(work))
            except StopIteration as done:
                stepped = done.value
                break
        self.assertEqual(self.state(), before)
        self.assertGreater(len(shown), 3, "un presupuesto mínimo da muchos pasos")
        self.assertTrue({"platform_apply", "platform_edge"} <= {step.phase for step in shown})
        np.testing.assert_array_equal(stepped.result, direct.result)
        self.assertEqual(stepped.figures, direct.figures)
        self.assertEqual([n.code for n in stepped.notices], [n.code for n in direct.notices])
        with mock.patch.object(entity_store, "platform_footprint_units",
                               side_effect=AssertionError("la huella ya estaba calculada")):
            _last(entity_store.platform_compute_steps(prepared.job, prepared.common,
                                                      footprint=prepared.footprint))
        again = _last(entity_store.platform_compute_steps(prepared.job, prepared.common))
        np.testing.assert_array_equal(again.result, direct.result)
        np.testing.assert_array_equal(again.footprint.levels, prepared.footprint.levels)

    def test_a_the_outcome_names_itself_for_the_operation(self) -> None:
        """RF-015-02 (el mensaje de la operación): el resultado dice la plataforma, su código y sus
        cifras mayores en español; es lo que ``Calculation.message`` da a ``commit``."""
        prepared = self.units(prep.request())
        outcome = _last(entity_store.platform_compute_steps(
            prepared.job, prepared.common, footprint=prepared.footprint))
        self.assertIn(f"«{LOADING}»", outcome.message)
        self.assertIn("PLT-001", outcome.message)
        self.assertIn("4000 m²", outcome.message)


def _last(work: Iterator[Any]) -> Any:
    """Lo que **devuelve** unos pasos (``yield from``)."""
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value


# ---------------------------------------------------------------------------------------------
# «Calcular» no escribe
# ---------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------
# El resumen
# ---------------------------------------------------------------------------------------------


CLIPPED_LAYER = "gis_fea_plataformas_recortadas"
CLIPPED_NAME = "Eje recortado"
CLIPPED_AXIS = ((-60.0, 200.0), (20.0, 200.0))
"""Un eje de 80 m de oeste a este y 20 m de ancho que sale 60 m por el oeste de la rejilla (locales): con las
celdas de 2 m, 40 columnas × 10 filas = 400 celdas, 100 dentro y 300 (1.200 m²) fuera; la primera de las de fuera, la
más al norte y al oeste, la de centro (−59; 209)."""


class SummaryTest(OperationCase):
    """RF-015-03 y RF-015-13: el resumen lleva las cifras y los avisos de lo que calcula."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        layer = qfx.LayerData(
            CLIPPED_LAYER, "line", (((cfx.absolute(CLIPPED_AXIS),),),), (CLIPPED_NAME,),
            {"ancho": (20.0,), "cota_inicial": (250.0,), "pendiente": (1.0,)})
        qfx.write_feature_layer(cls.project, cls.clock, layer)
        cls.clock.advance(minutes=1)

    def test_a_the_summary_has_the_figures_and_the_notices(self) -> None:
        """RF-015-03: el resumen de la cuenta lleva el nombre, el código y la versión, las cifras (las
        de ``PLATFORM_FIGURES`` que existen, con su unidad y el ámbito de la entidad), los avisos que
        enseña la cuenta (los de la cantera, línea a línea, en los dos idiomas) y, sin proteger ni
        sustituir, nada obsoleto."""
        calculation = self.calculate(prep.request())
        summary = calculation.summary
        self.assertEqual((summary.name, summary.code, summary.version), (LOADING, "PLT-001", "V01"))
        self.assertEqual(summary.figures, calculation.figures)
        declared = {figure.key: figure.unit for figure in provenance.PLATFORM_FIGURES}
        self.assertEqual({figure.key: figure.unit for figure in summary.figures},
                         {key: unit for key, unit in declared.items()
                          if key in {f.key for f in summary.figures}})
        self.assertIn("des.plat_area_m2", {figure.key for figure in summary.figures})
        scope = provenance.entity_figure_scope(LOADING, "PLT-001")
        self.assertTrue(all(figure.scope == scope for figure in summary.figures))
        self.assertEqual(summary.notices, calculation.notices)
        self.assertEqual(summary.obsolete, ())
        self.assertEqual(calculation.lines("es"), summary.lines("es"))
        self.assertEqual(calculation.lines("en"), summary.lines("en"))
        self.assertEqual(calculation.warnings("es"), summary.warnings("es"))
        self.assertTrue(all(isinstance(line, str) and "{" not in line
                            for line in (*summary.lines("es"), *summary.lines("en"))))
        self.assertIn("des.magnitude_no_reference", codes(summary))

    def test_a_the_created_step_and_the_wall_of_a_short_reach(self) -> None:
        """RF-015-13, RF-014-20, RF-014-21: con un alcance corto (4 m) el borde queda empinado en su
        límite y deja un salto creado: el resumen lo avisa con el nombre de la entidad (el aviso del
        salto creado de la 014 y sus tramos, no más de 10) y dice la pared más empinada."""
        summary = self.calculate(prep.request(reach_m=4.0)).summary
        wall = only(summary, "des.platform_edge_steep")
        self.assertEqual(wall.values["entity"], LOADING)
        step = only(summary, "des.edge_surface_step")
        self.assertEqual(step.values["surface"], LOADING)
        self.assertEqual(step.severity, "warning")
        stretches = [n for n in summary.notices if n.code == "des.edge_stretch"]
        self.assertTrue(0 < len(stretches) <= 10)
        self.assertEqual("des.edge_more_stretches" in codes(summary), step.values["stretches"] > 10)

    def test_a_what_reaches_cells_without_data_outside_the_footprint(self) -> None:
        """RF-015-13: lo que el borde mueve junto a celdas sin dato fuera de la huella se avisa con su
        área (15 celdas de hueco, a 8 m de la huella) y su lugar: el terreno de partida con el hueco
        al norte de la «Plataforma de carga» deja ``des.entity_edge_outside``."""
        summary = self.calculate(prep.request(start=EDGE_HOLE_DATASET)).summary
        outside = only(summary, "des.entity_edge_outside")
        self.assertEqual(outside.values["entity"], LOADING)
        self.assertGreater(outside.values["cells"], 0)
        self.assertAlmostEqual(outside.values["area"], outside.values["cells"] * CELL_M2)
        self.assertTrue(290.0 < outside.values["y"] - efx.BASE[1] < 300.0)
        self.assertTrue(195.0 < outside.values["x"] - efx.BASE[0] < 215.0)
        calm = self.calculate(prep.request()).summary
        self.assertNotIn("des.entity_edge_outside", codes(calm))

    def test_a_a_footprint_the_grid_cuts_says_how_much_and_where(self) -> None:
        """RF-015-13, RF-015-08 (T46; D-1/A-7): un eje que sale de la rejilla se calcula **sin rechazo** y el
        resumen avisa del área de huella que queda fuera de ella (300 celdas, 1.200 m²) y su lugar, con el
        nombre de la entidad, en los dos idiomas; la «Plataforma de carga», que cabe, no lo lleva."""
        asked = prep.request(CLIPPED_NAME, fields=prep.line_fields(CLIPPED_LAYER), feature=CLIPPED_NAME)
        calculation = self.calculate(asked)
        summary = calculation.summary
        cut = only(summary, "des.platform_footprint_clipped")
        x, y = (round(float(v), 2) for v in cfx.absolute([(-59.0, 209.0)])[0])
        self.assertEqual(dict(cut.values), {"entity": CLIPPED_NAME, "cells": 300, "area": 1200.0,
                                            "x": x, "y": y})
        self.assertEqual(calculation.outcome.footprint.cell_count, 100)
        self.assertTrue(any("la rejilla del proyecto recorta su huella" in line
                            for line in summary.warnings("es")))
        self.assertTrue(any("the project grid cuts its footprint" in line
                            for line in summary.warnings("en")))
        self.assertNotIn("des.platform_footprint_clipped", codes(self.calculate(prep.request()).summary))
        # La vista previa (RF-015-26, la ficha antes de calcular) lo dice con los mismos datos.
        shown = finish(preview.entity_preview_steps(self.project, asked, self.v1.uid))
        self.assertIsNone(shown.refusal)
        self.assertEqual(only(shown, "des.platform_footprint_clipped").values, cut.values)
        self.assertTrue(any("la rejilla del proyecto recorta su huella" in line
                            for line, alert in shown.lines("es") if alert))

    def test_a_the_magnitude_against_the_last_frozen_revision(self) -> None:
        """RF-015-13, RF-013-30: sin revisión congelada, la nota de que no hay con qué comparar (con
        el nombre de la entidad); con una (la de ``platform_previous``) con un desmonte mucho menor,
        el aviso de magnitud con su revisión."""
        plain = self.calculate(prep.request()).summary
        self.assertEqual(only(plain, "des.magnitude_no_reference").values["operation"], LOADING)
        before = design_report.Previous(LOADING, "V01.r1", cut_m3=1.0, fill_m3=0.0)
        with mock.patch.object(entity_store, "platform_previous", return_value=before):
            compared = self.calculate(prep.request()).summary
        self.assertNotIn("des.magnitude_no_reference", codes(compared))
        cut = only(compared, "des.magnitude_cut")
        self.assertEqual(cut.values["revision"], "V01.r1")
        self.assertTrue(any("V01.r1" in line for line in compared.warnings("es")))

    def test_a_what_a_constraint_does_not_let_move_names_the_constraint(self) -> None:
        """RF-015-13, RF-015-07 (intocable real): la «Plataforma de la torre» cruza la zona del
        intocable «Torre» (entera dentro de su huella): sus celdas no se cortan y el resumen dice su
        área (m²), la restricción (con su nombre y su código) y su lugar; el área es la de la zona
        (a mano: sus celdas por 4 m²) y es toda la que las máscaras no dejan mover."""
        calculation = self.calculate(prep.request(TOWER))
        summary = calculation.summary
        zone = self.masks_v1.zone("torre")
        footprint = np.zeros(GRID.shape, dtype=bool)
        window = calculation.outcome.footprint.window
        footprint[window] = calculation.outcome.footprint.cells
        zone_cells = zone.mask(GRID.shape)
        self.assertFalse((zone_cells & ~footprint).any(), "la zona de la torre cae dentro de la huella")
        held = only(summary, "des.entity_held_constraint")
        self.assertEqual(held.values["entity"], TOWER)
        self.assertEqual(held.values["constraint"], "Torre (torre)")
        self.assertEqual(held.values["area"], zone.cells * CELL_M2)
        self.assertEqual(calculation.outcome.held_area_m2, zone.cells * CELL_M2)
        self.assertNotIn("des.entity_held_masks", codes(summary))
        rows, cols = np.nonzero(zone_cells)  # la primera celda: de norte a sur y de oeste a este
        self.assertEqual(held.values["x"], round(GRID.west + (cols[0] + 0.5) * GRID.dx, 2))
        self.assertEqual(held.values["y"], round(GRID.north - (rows[0] + 0.5) * GRID.dy, 2))
        self.assertEqual(held.severity, "warning")
        self.assertIn("«Torre (torre)»", summary.lines("es")[codes(summary).index(
            "des.entity_held_constraint")])

    def test_a_a_count_of_one_takes_its_singular(self) -> None:
        """RF-015-13, RF-015-24 (spec 014, T60): el grupo de celdas por encima de la rasante de la torre
        es uno (el de la zona del intocable): el resumen dice «en 1 grupo» y «in 1 group», no «1
        grupos», con el número sin escribir (el singular lo elige ``Notice.text``)."""
        summary = self.calculate(prep.request(TOWER)).summary
        above = only(summary, "des.platform_above")
        self.assertEqual(above.values["groups"], 1)
        spanish = summary.lines("es")[codes(summary).index("des.platform_above")]
        english = summary.lines("en")[codes(summary).index("des.platform_above")]
        self.assertIn("en 1 grupo,", spanish)
        self.assertIn("in 1 group,", english)
        for line in (*summary.lines("es"), *summary.lines("en")):
            self.assertNotRegex(line, r"\b1 (grupos|groups|celdas|cells)\b")

    def test_the_group_notes_are_capped_like_the_stretches(self) -> None:
        """RF-015-24, RF-015-03: el resumen enseña los 10 primeros grupos de lo que queda por encima o
        por debajo de la rasante y una nota con los que faltan (con su singular); la lista entera se
        queda en el resultado."""
        notice = preview.Notice
        every = [notice("des.platform_above", {"entity": "P", "area": 1.0, "maximum": 1.0,
                                               "groups": 12}),
                 *(notice("des.platform_above_group", {"group": n, "cells": 2, "area": 8.0,
                                                       "maximum": 1.0, "x": 1.0, "y": 2.0})
                   for n in range(1, 13)),
                 notice("des.platform_below", {"entity": "P", "area": 1.0, "maximum": 1.0,
                                               "groups": 3}),
                 *(notice("des.platform_below_group", {"group": n, "cells": 2, "area": 8.0,
                                                       "maximum": 1.0, "x": 1.0, "y": 2.0})
                   for n in range(1, 4)),
                 notice("des.magnitude_no_reference", {"operation": "P"})]
        shown = platform.summary_notices(every)
        found = [n.code for n in shown]
        self.assertEqual(found.count("des.platform_above_group"), 10)
        self.assertEqual(found.count("des.platform_below_group"), 3)
        self.assertEqual(found.count("des.platform_more_groups"), 1)
        more = shown[found.index("des.platform_more_groups")]
        self.assertEqual(more.values["groups"], 2)
        self.assertIn("y 2 grupos más", more.text("es"))
        self.assertEqual(found.index("des.platform_more_groups") - found.index("des.platform_above"), 11)
        eleven = every[:12] + every[13:]  # 11 grupos por encima: uno de más
        one = platform.summary_notices(eleven, limit=10)
        self.assertEqual(len(one), len(eleven))  # sale el grupo 11 y entra la nota
        self.assertEqual([n.values["groups"] for n in one if n.code == "des.platform_more_groups"],
                         [1])
        singular = platform.summary_notices(every, limit=11)
        self.assertIn("y 1 grupo más", [n for n in singular
                                          if n.code == "des.platform_more_groups"][0].text("es"))


# ---------------------------------------------------------------------------------------------
# Lo que no se mueve por una restricción: las funciones puras
# ---------------------------------------------------------------------------------------------


class HeldNoticesTest(unittest.TestCase):
    """RF-015-13: a partir de lo que no se mueve (la huella que no se corta ni se rellena, y el borde) y
    las zonas de las máscaras, ``preview.held_notices`` dice qué restricción lo impide: con el nombre
    de la entidad si la declara una (código ``dec__…``), con su nombre si es una restricción normal y,
    si no es ninguna zona, que las máscaras no lo admiten."""

    GRID = gis.Grid(725_000.0, 4_400_000.0, 2.0, 2.0, 10, 8)
    WINDOW = (slice(1, 7), slice(2, 8))  # filas 1 a 6 y columnas 2 a 7 de la rejilla

    @classmethod
    def masks(cls, zones: dict[str, tuple[str, Any]]) -> Any:
        """Unas máscaras de doble con las zonas ``zones`` (código → (tipo, máscara de la rejilla))."""
        return access.MaskSet(
            cls.GRID, "version", "operation", access.MaskState.CURRENT, (),
            np.zeros(cls.GRID.shape, dtype=np.uint16),
            zones={code: zones_mod.Runs.from_mask(mask) for code, (_ctype, mask) in zones.items()},
            ctypes={code: ctype for code, (ctype, _mask) in zones.items()})

    @classmethod
    def region(cls, rows: slice, cols: slice) -> np.ndarray:
        """Una máscara de la rejilla entera con las filas y columnas dadas."""
        mask = np.zeros(cls.GRID.shape, dtype=bool)
        mask[rows, cols] = True
        return mask

    def window(self, mask: np.ndarray) -> np.ndarray:
        """La parte de ``mask`` que cae en la ventana de trabajo."""
        return mask[self.WINDOW]

    def notices(self, zones: dict[str, tuple[str, Any]], *, cut: Any = None, fill: Any = None,
                edge: Any = None, names: dict[str, str] | None = None,
                declared: dict[str, str] | None = None) -> tuple[Any, ...]:
        empty = np.zeros((6, 6), dtype=bool)
        return preview.held_notices(
            "P2", self.masks(zones), self.WINDOW,
            cut=empty if cut is None else self.window(cut),
            fill=empty if fill is None else self.window(fill),
            edge=empty if edge is None else self.window(edge),
            names=names or {}, declared=declared or {})

    def test_a_declared_constraint_names_the_entity_that_declares_it(self) -> None:
        """RF-015-13, RF-015-10: la zona ``dec__plt_001`` (sin relleno) impide rellenar 4 celdas de la
        huella: el aviso dice 16 m², la restricción, la entidad del registro y la primera celda (de
        norte a sur y de oeste a este) con sus coordenadas absolutas en float64. El texto nombra la
        restricción como «Ver restricciones y límites» («Plataforma P1 (declarada)», T45, E-8), no por su
        código."""
        zone = self.region(slice(3, 5), slice(4, 6))
        found = self.notices({"dec__plt_001": ("no_fill", zone)}, fill=zone,
                             declared={"dec__plt_001": "P1"})
        (held,) = found
        self.assertEqual(held.code, "des.entity_held")
        self.assertEqual(dict(held.values), {
            "entity": "P2", "area": 16.0, "constraint": "dec__plt_001", "other": "P1",
            "x": 725_000.0 + (4 + 0.5) * 2.0, "y": 4_400_000.0 - (3 + 0.5) * 2.0})
        self.assertIn("«Plataforma P1 (declarada)»", held.text("es"))
        self.assertIn("«Platform P1 (declared)»", held.text("en"))
        self.assertNotIn("dec__plt_001", held.text("es") + held.text("en"))

    def test_a_declared_constraint_of_an_unknown_entity_gives_its_code(self) -> None:
        """RF-015-13: una ``dec__…`` cuya entidad el registro no tiene (la borraron) se nombra con el
        código de la entidad; no se pierde el aviso."""
        zone = self.region(slice(2, 3), slice(3, 6))
        (held,) = self.notices({"dec__plt_009": ("no_cut", zone)}, cut=zone)
        self.assertEqual((held.code, held.values["other"]), ("des.entity_held", "PLT-009"))
        self.assertEqual(held.values["area"], 12.0)

    def test_a_normal_constraint_is_named_with_its_code(self) -> None:
        """RF-015-13: una restricción normal se nombra con su nombre y su código («Torre (torre)») o,
        sin nombre, con el código; el borde también cuenta (en una zona de «sin corte»)."""
        zone = self.region(slice(2, 4), slice(2, 5))
        (held,) = self.notices({"torre": ("untouchable", zone)}, cut=zone,
                               names={"torre": "Torre"})
        self.assertEqual((held.code, held.values["constraint"], held.values["area"]),
                         ("des.entity_held_constraint", "Torre (torre)", 24.0))
        (edge,) = self.notices({"sin_corte": ("no_cut", zone)}, edge=zone)
        self.assertEqual((edge.values["constraint"], edge.values["area"]), ("sin_corte", 24.0))

    def test_a_cell_outside_every_zone_is_what_the_masks_do_not_allow(self) -> None:
        """RF-015-13: lo que ninguna zona explica (fuera del límite, su banda…) se avisa aparte
        (``des.entity_held_masks``) con su área y su lugar; lo explicado y lo no explicado salen
        cada uno en su aviso y el área no se cuenta dos veces."""
        zone = self.region(slice(1, 2), slice(2, 4))
        loose = self.region(slice(5, 7), slice(6, 8))
        found = self.notices({"torre": ("untouchable", zone)}, cut=zone | loose,
                             names={"torre": "Torre"})
        self.assertEqual([n.code for n in found], ["des.entity_held_constraint",
                                                   "des.entity_held_masks"])
        self.assertEqual((found[0].values["area"], found[1].values["area"]), (8.0, 16.0))
        self.assertEqual((found[1].values["x"], found[1].values["y"]),
                         (725_000.0 + 6.5 * 2.0, 4_400_000.0 - 5.5 * 2.0))

    def test_a_zone_that_does_not_forbid_the_movement_does_not_explain_it(self) -> None:
        """RF-015-13: una zona «preferible no afectar» no prohíbe nada, y una de «sin relleno» no
        explica una celda que no se corta: esas celdas quedan para «las máscaras no lo admiten»."""
        zone = self.region(slice(2, 4), slice(3, 5))
        for ctype in ("avoid", "requires_access", "no_fill"):
            with self.subTest(ctype=ctype):
                (held,) = self.notices({"zona": (ctype, zone)}, cut=zone)
                self.assertEqual(held.code, "des.entity_held_masks")
        (filled,) = self.notices({"zona": ("no_fill", zone)}, fill=zone)
        self.assertEqual(filled.code, "des.entity_held_constraint")

    def test_a_legal_limit_band_is_named_by_its_limit(self) -> None:
        """RF-015-13: la banda hacia dentro de un límite legal (zona ``<código>:inner``) impide cortar y
        se nombra con el límite."""
        band = self.region(slice(1, 3), slice(2, 8))
        (held,) = self.notices({"concesion:inner": ("legal_limit", band)}, cut=band,
                               names={"concesion": "Concesión"})
        self.assertEqual((held.code, held.values["constraint"]),
                         ("des.entity_held_constraint", "Concesión (concesion)"))

    def test_a_zone_larger_than_what_is_held_counts_only_what_is_held(self) -> None:
        """RF-015-13: la zona se mira solo donde hay celdas que no se mueven: una zona que cubre toda la
        rejilla y dos grupos separados dan el área de esas celdas (6 + 1, a 4 m²) y el lugar de la
        primera de norte a sur y de oeste a este."""
        everything = self.region(slice(0, 8), slice(0, 10))
        held = self.region(slice(2, 4), slice(3, 6)) | self.region(slice(5, 6), slice(6, 7))
        (found,) = self.notices({"z": ("untouchable", everything)}, cut=held)
        self.assertEqual(found.values["area"], 28.0)
        self.assertEqual((found.values["x"], found.values["y"]),
                         (725_000.0 + 3.5 * 2.0, 4_400_000.0 - 2.5 * 2.0))

    def test_nothing_held_nothing_said(self) -> None:
        """RF-015-13: sin celdas que no se muevan, ningún aviso (y sin zonas, tampoco)."""
        zone = self.region(slice(2, 4), slice(3, 5))
        self.assertEqual(self.notices({"torre": ("untouchable", zone)}), ())
        self.assertEqual(self.notices({}), ())

    def test_a_zone_outside_the_window_is_ignored(self) -> None:
        """RF-015-13: una zona que no toca la ventana de trabajo no cuenta (ni se pinta entera)."""
        outside = self.region(slice(0, 1), slice(0, 2))
        near = self.region(slice(1, 3), slice(2, 4))
        (held,) = self.notices({"lejos": ("untouchable", outside),
                                "cerca": ("untouchable", near)}, cut=near)
        self.assertEqual(held.values["constraint"], "cerca")


class HeldByDeclaredTest(OperationCase):
    """RF-015-13, RF-015-10: con una restricción declarada por otra entidad (``dec__plt_001``, de la
    «Plataforma P1» del registro) que impide cortar, el resumen dice el área que no mueve y esa
    entidad. La declarada es un doble (la tabla de las declaradas es de la T16)."""

    P1 = "Plataforma P1"
    BOX = (150.0, 270.0, 170.0, 290.0)
    """Parte de la huella de la «Plataforma de carga» (local): 10 × 10 celdas de 2 m = 400 m²."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for param, value in (("name", cls.P1), ("start", "des_srf_otra"),
                                 ("start_level_m", 230.0), ("gradient_pct", 1.0)):
                store.create(conn, design_params.entity_key("PLT-001", param), value,
                             kind="ADOPTADO", source="Prueba de la 015", source_kind="person",
                             decided_by="Samuel (IMGA)", reason="Prueba de T12",
                             version=cls.v1.code)
        zone = qfx.in_box(cls.BOX, GRID)
        classes = np.array(cls.masks_v1.classes)
        classes[zone] &= ~np.uint16(int(combine.ClassBit.CUT_ALLOWED))
        cls.declared_zone = zone
        cls.double = dataclasses.replace(
            cls.masks_v1, classes=classes,
            zones={**cls.masks_v1.zones, "dec__plt_001": zones_mod.Runs.from_mask(zone)},
            ctypes={**cls.masks_v1.ctypes, "dec__plt_001": "no_cut"})

    def test_a_the_summary_names_the_entity_that_declares_the_constraint(self) -> None:
        """RF-015-13: la «Plataforma de carga» (PLT-002, tras la P1) no corta las 100 celdas de la
        zona declarada: el resumen dice 400 m², ``dec__plt_001`` y la entidad «Plataforma P1»; y, aparte,
        lo que su borde oeste no mueve por «Sin corte» (una restricción normal, con su nombre): entre
        las dos, todo lo que no mueve (y no hay aviso de máscaras sueltas)."""
        calculation = self.calculate(prep.request(), masks=self.double)
        self.assertEqual(calculation.entity.code, "PLT-002")
        held = only(calculation.summary, "des.entity_held")
        self.assertEqual((held.values["constraint"], held.values["other"], held.values["area"]),
                         ("dec__plt_001", self.P1, 400.0))
        normal = only(calculation.summary, "des.entity_held_constraint")
        self.assertEqual(normal.values["constraint"], "Sin corte (sin_corte)")
        self.assertGreater(normal.values["area"], 0.0)
        self.assertEqual(held.values["area"] + normal.values["area"],
                         calculation.outcome.held_area_m2)
        self.assertNotIn("des.entity_held_masks", codes(calculation.summary))
        text = calculation.summary.lines("es")[codes(calculation.summary).index("des.entity_held")]
        self.assertIn(f"«Plataforma {self.P1} (declarada)»", text)  # como «Ver restricciones y límites» (T45, E-8)
        self.assertEqual(len(self.temporaries()), 1)

    def test_a_without_the_declared_zone_only_the_normal_constraint_is_named(self) -> None:
        """RF-015-13: con las máscaras de V01 (sin la declarada) la misma plataforma corta toda su
        huella y solo avisa de lo que su borde no mueve junto a «Sin corte»."""
        calculation = self.calculate(prep.request())
        summary = calculation.summary
        self.assertNotIn("des.entity_held", codes(summary))
        self.assertNotIn("des.entity_held_masks", codes(summary))
        normal = only(summary, "des.entity_held_constraint")
        self.assertEqual(normal.values["constraint"], "Sin corte (sin_corte)")
        self.assertEqual(normal.values["area"], calculation.outcome.held_area_m2)


# ---------------------------------------------------------------------------------------------
# Lo que quedará obsoleto
# ---------------------------------------------------------------------------------------------


class ObsoleteCase(OperationCase):
    """V01 con una cantera de la 014 y su transición (usan las máscaras: son lo que depende de ellas) y
    cuatro entidades en el registro: P2 (parte del terreno), P3 (de la superficie de P2) y P4 (de la
    de P3), **hechas** (sus operaciones, sintéticas, leen sus parámetros y consumen la superficie de la
    anterior como lo hará la T13), y P5 (de la de P4), sin calcular; más una capa de una plataforma
    a 330 m."""

    QUARRY, TRANSITION = "Cantera E7", "Transición E7"
    HIGH_LAYER = "gis_fea_plataformas_altas"
    quarry: ClassVar[Any]
    transition: ClassVar[Any]
    chain: ClassVar[dict[str, str]]

    @classmethod
    def declare(cls, key: str, value: object) -> None:
        """Declara un parámetro del proyecto."""
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, key, value, kind="ADOPTADO", source="Perfil de prueba", source_kind="person",
                decided_by="Samuel (IMGA)", reason="Prueba de T12")

    @classmethod
    def entity(cls, number: int, name: str, start: str, *, made: bool = True) -> str:
        """Da de alta la entidad ``PLT-00<n>`` en V01 y, si ``made``, registra su operación sintética (la
        del contrato de la T03): lee sus parámetros, consume como ``surface`` la superficie de la
        entidad de la que parte (``entity:PLT-00<m>``) y escribe la suya (``des_psf_p<n>``, una tabla
        de juguete). Devuelve el uid de la operación (``""`` sin ella)."""
        store = core_params.ParameterStore(cls.project)
        code = f"PLT-00{number}"
        cls.clock.advance(minutes=1)
        keys = []
        with cls.project.write_transaction() as conn:
            for param, value in (("name", name), ("start", start)):
                keys.append(design_params.entity_key(code, param))
                store.create(conn, keys[-1], value, kind="ADOPTADO", source="Prueba de la 015",
                             source_kind="person", decided_by="Samuel (IMGA)",
                             reason="Prueba de T12", version=cls.v1.code)
        if not made:
            return ""
        cls.clock.advance(minutes=1)
        before = entities_module.ref_code(start)
        reads = [] if before is None else [operations.Use(
            f"des_psf_p{int(before.rsplit('-', 1)[1])}", "surface")]
        handle = operations.begin_operation(
            cls.project, "des.platform", settings={"code": code, "name": name}, params=keys,
            inputs=reads, executor="blender", version=cls.v1.uid)
        label = f"des_psf_p{number}"
        locator = versions_model.version_locator(label, cls.v1.code)
        with cls.project.write_transaction() as conn:
            gpkg_base.create_attribute_table(
                conn, locator, [gpkg_base.ColumnDef("value", "DOUBLE")], label,
                "Dato sintético de la prueba de T12 (spec 015)")
            conn.execute(f'INSERT INTO "{locator}" (value) VALUES (?)', (float(number),))
            handle.complete(conn, outputs=[datasets.DatasetSpec(
                label, "des", "table", datasets.Store.GPKG, locator, reader=builtin.GPKG_LAYER.id,
                role="entity_surface")])
        return str(handle.uid)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.FAMILIES)
        cls.enterClassContext(registered(*edges_test.definitions()))
        for profile in (qfx.EXPLOITATION_PROFILE, qfx.FINAL_PROFILE):
            for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
                cls.declare(design_params.bench_key(profile.code, param), getattr(profile, param))
        cls.declare(design_params.EDGE_TRANSITION, edges_test.ANGLE_DEG)
        cls.clock.advance(minutes=1)
        asked = model.QuarryRequest(
            name=cls.QUARRY, start=START, final=model.QuarrySide(qfx.FINAL_PROFILE.code),
            exploitation=model.QuarrySide(qfx.EXPLOITATION_PROFILE.code))
        cls.quarry = finish(steps.quarry_run(cls.project, asked, version=cls.v1.uid,
                                             masks=cls.masks_v1)).create()
        cls.clock.advance(minutes=1)
        cls.transition = finish(steps.edge_transition_run(
            cls.project, cls.TRANSITION, provenance.dataset_name("fin", cls.QUARRY), START,
            version=cls.v1.uid, masks=cls.masks_v1)).create()
        cls.chain = {"P2": cls.entity(2, "P2", START),
                     "P3": cls.entity(3, "P3", "entity:PLT-002"),
                     "P4": cls.entity(4, "P4", "entity:PLT-003"),
                     "P5": cls.entity(5, "P5", "entity:PLT-004", made=False)}
        qfx.write_feature_layer(cls.project, cls.clock, qfx.LayerData(
            cls.HIGH_LAYER, "line", (((cfx.absolute(efx.AXES[0].path),),),), ("Alta",),
            {"ancho": (20.0,), "cota_inicial": (330.0,), "pendiente": (0.0,)}))
        cls.clock.advance(minutes=1)
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)


# ---------------------------------------------------------------------------------------------
# Con qué se compara la magnitud
# ---------------------------------------------------------------------------------------------


class PreviousFrozenTest(OperationCase):
    """RF-015-13, RF-013-30 (D-25): la magnitud se compara con la plataforma de la **revisión congelada**
    más reciente de la versión que tiene el mismo código de entidad, con el desmonte y el relleno de su
    huella y de su borde sumados; una operación de ese tipo sin esas cifras, de otra entidad o de una
    revisión sin congelar no cuenta."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.written = cls.operation(LOADING, "PLT-001", cut=100.0, fill=10.0, edge_cut=50.0,
                                    edge_fill=5.0)
        cls.other = cls.operation("Otra", "PLT-002", cut=1.0, fill=1.0, edge_cut=1.0, edge_fill=1.0)
        with cls.project.write_transaction() as conn:
            freeze_rows(conn, cls.v1, now=cls.clock.now().isoformat(timespec="seconds"),
                        reason="Siguiente")
        cls.clock.advance(minutes=1)
        cls.unfrozen = cls.operation(LOADING, "PLT-001", cut=9_999.0, fill=9_999.0,
                                     edge_cut=9_999.0, edge_fill=9_999.0)

    @classmethod
    def operation(cls, name: str, code: str, *, cut: float, fill: float, edge_cut: float,
                  edge_fill: float) -> str:
        """Una operación ``des.platform`` hecha de ``code`` con las cifras dadas."""
        figures = provenance.platform_figures(name, code, {
            "des.plat_area_m2": 1.0, "des.plat_axis_m": 1.0, "des.plat_footprint_m": 1.0,
            "des.plat_start_level_m": 1.0, "des.plat_end_level_m": 1.0, "des.plat_cut_m3": cut,
            "des.plat_fill_m3": fill, "des.edge_cut_m3": edge_cut, "des.edge_fill_m3": edge_fill,
            "des.edge_wall_max_m": None, "des.plat_below_m2": 0.0, "des.plat_below_max_m": None})
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(
            cls.project, "des.platform", settings=provenance.platform_settings(
                prep.request(name), code), executor="blender", version=cls.v1.uid)
        with cls.project.write_transaction() as conn:
            handle.complete(conn, outputs=(), figures=figures)
        return str(handle.uid)

    def test_a_the_previous_is_the_entity_of_the_last_frozen_revision(self) -> None:
        """RF-013-30, D-25: ``platform_previous`` da, de la entidad PLT-001, el desmonte (100 + 50) y el
        relleno (10 + 5) de la revisión V01.r1 con el nombre de su operación; la de otra entidad no se
        mezcla y la de la revisión abierta (con otras cifras) no cuenta; sin revisión congelada, o sin
        operación de esa entidad en ella, ninguna."""
        with self.project.read() as conn:
            found = entity_store.platform_previous(conn, self.v1, "PLT-001")
            other = entity_store.platform_previous(conn, self.v1, "PLT-002")
            nobody = entity_store.platform_previous(conn, self.v1, "PLT-009")
            before_any = entity_store.platform_previous(conn, self.v2, "PLT-001")
        self.assertEqual((found.operation, found.revision, found.cut_m3, found.fill_m3),
                         (LOADING, "V01.r1", 150.0, 15.0))
        self.assertEqual((other.operation, other.cut_m3, other.fill_m3), ("Otra", 2.0, 2.0))
        self.assertIsNone(nobody)
        self.assertIsNone(before_any)

    def test_a_calculating_compares_with_it(self) -> None:
        """RF-015-13: «Calcular» la «Plataforma de carga» (PLT-004: hay tres operaciones antes en la
        versión pero ninguna entidad en el registro, así que parte del código PLT-001) compara su
        desmonte con el de la congelada (150 m³): el aviso de magnitud con V01.r1."""
        calculation = self.calculate(prep.request())
        self.assertEqual(calculation.entity.code, "PLT-001")
        cut = only(calculation.summary, "des.magnitude_cut")
        self.assertEqual((cut.values["revision"], cut.values["previous"]), ("V01.r1", 150))
        self.assertNotIn("des.magnitude_no_reference", codes(calculation.summary))


# ---------------------------------------------------------------------------------------------
# «Crear» (T13): lo que se registra
# ---------------------------------------------------------------------------------------------

PSF, EPR, PRP = (provenance.dataset_name(family, LOADING) for family in ("psf", "epr", "prp"))
"""Los nombres de los tres datos de la «Plataforma de carga»."""
EPR_TABLE = provenance.dataset_locator("epr", LOADING, "V01")
PRP_TABLE = provenance.dataset_locator("prp", LOADING, "V01")
ENTITY_COLUMNS = ("code", "name", "kind", "start_surface", "support_surface", "layer", "source_fid",
                  "geometry_sha256", "mode", "cells", "axis_principal", "bounds", "footprint",
                  "axis")
"""Las columnas de ``des_epr_``, en su orden."""
OUTSIDE_NOTICES = {"des.magnitude_cut", "des.magnitude_fill", "des.magnitude_no_reference",
                   "des.entity_quarry_order"}
"""Los avisos que dependen de algo que la operación no consume (la revisión congelada anterior y la
otra superficie de la cantera): no van al informe, que se reproduce sin el proyecto."""
LOADING_ROWS = list(range(55, 65))
"""Las filas de la huella de la «Plataforma de carga» (a mano: y de 270 a 290 m locales, de 2 m, desde
el norte de 400 m: 400 − 2·(fila + ½) de 271 a 289)."""
LOADING_COLUMNS = (55, 155)
"""Sus columnas (x de 110 a 310 m locales: de 2 m)."""


def written_tables(case: Any) -> list[str]:
    """Las tablas ``des_…`` del proyecto."""
    return [name for (name,) in case.query(
        "SELECT name FROM sqlite_master WHERE name LIKE 'des!_%' ESCAPE '!' ORDER BY name")]


class CreateCase(OperationCase):
    """Lo de ``OperationCase`` más ayudantes **de clase** (las historias de «Crear» se hacen una vez
    en ``setUpClass``) y ``written``: lo que ``des`` y las operaciones han dejado en el proyecto."""

    @classmethod
    def query_of(cls, sql: str, *values: Any) -> list[Any]:
        with cls.project.read() as conn:
            return conn.execute(sql, values).fetchall()

    @classmethod
    def written(cls) -> dict[str, Any]:
        """Todo lo que podría escribir «Crear» (sin el contador de cambios: un deshacer lo deja)."""
        return {
            "operations": cls.query_of(
                "SELECT uid, op_type, status FROM gb_operation ORDER BY fid"),
            "datasets": cls.query_of(
                "SELECT uid, name, status, content_sha256 FROM gb_dataset ORDER BY fid"),
            "parameters": cls.query_of(
                "SELECT key, scope, scope_uid, value, unconfirmed FROM gb_parameter ORDER BY fid"),
            "io": cls.query_of(
                "SELECT operation_uid, direction, item_uid, role FROM gb_operation_io ORDER BY fid"),
            "figures": cls.query_of(
                "SELECT operation_uid, key, scope, value FROM gb_figure ORDER BY fid"),
            "tables": cls.query_of("SELECT name FROM sqlite_master WHERE name LIKE 'des!_%' "
                                   "ESCAPE '!' ORDER BY name"),
            "files": sorted(path.name for path in (cls.root / "rasters").iterdir())}

    @staticmethod
    def settled(state: dict[str, Any]) -> dict[str, Any]:
        """``state`` sin los temporales (``….tmp-…``) de un cálculo abierto: lo que queda en el proyecto
        cuando ese cálculo se descarta o falla al crearse."""
        return {**state, "files": [name for name in state["files"] if ".tmp-" not in name]}

    @classmethod
    def layers(cls) -> dict[str, Any]:
        """Las capas de plataformas como están: su registro y todo el contenido de su tabla."""
        found: dict[str, Any] = {}
        for name in efx.LAYERS:
            (locator,) = cls.query_of("SELECT locator FROM gb_dataset WHERE name = ?", name)[0]
            found[name] = (cls.query_of("SELECT uid, status, content_sha256 FROM gb_dataset "
                                        "WHERE name = ?", name),
                           cls.query_of(f'SELECT * FROM "{locator}" ORDER BY fid'))
        return found

    @classmethod
    def calculate_in(cls, asked: Any, **options: Any) -> Any:
        """«Calcular» ``asked`` hasta el final (la ``Calculation``, que **no** se descarta al acabar)."""
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        return finish(steps.platform_run(cls.project, asked, **options))

    def grid_of(self, name: str) -> np.ndarray:
        """La rejilla del dato ``name`` de V01 tal como está en su fichero."""
        record = self.record(name, self.v1)
        return geotiff_reader.read_geotiff(self.root / record.locator).values

    def figures_of(self, uid: str) -> dict[tuple[str, str], float]:
        return {(key, scope): value for key, scope, value in self.query(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def rows_of(self, table: str) -> dict[str, list[tuple[Any, str | None, str | None]]]:
        """Las filas de un informe largo por su cifra: ``quantity`` → lista de ``(valor, unidad, nota)``."""
        found: dict[str, list[Any]] = {}
        for quantity, value, unit, note in self.query(
                f'SELECT quantity, value, unit_code, note FROM "{table}" ORDER BY fid'):
            found.setdefault(quantity, []).append((value, unit, note))
        return found


class CreateTest(CreateCase):
    """RF-015-01, RF-015-02, RF-015-04: la «Plataforma de carga» (PLT-001, del terreno) calculada y creada
    y la «Plataforma de taller» (PLT-002) de la superficie de la primera, ambas una vez en V01."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    first_stored: ClassVar[Any]
    second_stored: ClassVar[Any]
    clean: ClassVar[dict[str, Any]]
    calculated: ClassVar[dict[str, Any]]
    layers_before: ClassVar[dict[str, Any]]
    layers_after: ClassVar[dict[str, Any]]
    counters: ClassVar[tuple[int, int, int]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.layers_before = cls.layers()
        cls.clean = cls.written()
        before = change_counter(cls.root)
        cls.clock.advance(minutes=1)
        cls.first = cls.calculate_in(prep.request())
        cls.calculated = cls.written()
        calculated = change_counter(cls.root)
        cls.clock.advance(minutes=1)
        cls.first_stored = cls.first.create()
        cls.counters = (before, calculated, change_counter(cls.root))
        cls.clock.advance(minutes=1)
        cls.second = cls.calculate_in(prep.request(WORKSHOP, start="entity:PLT-001"))
        cls.clock.advance(minutes=1)
        cls.second_stored = cls.second.create()
        cls.layers_after = cls.layers()

    # --- Una transacción --------------------------------------------------------------------

    def test_b_creating_is_one_write_transaction(self) -> None:
        """RF-015-02, RF-015-29: «Calcular» no sube el contador de cambios de la base y «Crear» lo sube
        **una** vez: la operación, los tres datos, las tablas, las cifras y los parámetros de la
        entidad entran en una sola transacción de escritura (el fichero de la superficie se pone en
        su sitio dentro de ella)."""
        before, calculated, created = self.counters
        self.assertEqual(calculated, before, "calcular no escribe")
        self.assertEqual(created, calculated + 1, "crear es una sola transacción")
        self.assertTrue(self.first.open is False)
        with self.assertRaises(RuntimeError):
            self.first.create()
        self.first.discard()  # lo creado no se toca
        self.assertEqual(self.written()["operations"][-2:],
                         [(self.first_stored.handle.uid, "des.platform", "done"),
                          (self.second_stored.handle.uid, "des.platform", "done")])

    # --- La operación y sus tres datos ---------------------------------------------------------

    def test_b_the_operation_with_its_inputs_settings_and_message(self) -> None:
        """RF-015-02, RF-015-04, RF-015-06: la operación ``des.platform`` de V01 (revisión abierta), hecha,
        con los ajustes de la entidad, la capa (``entity_layer``), la superficie de partida
        (``surface``) y las máscaras como entradas y los parámetros que lee; el mensaje es el del
        resumen de lo calculado."""
        uid = self.first_stored.handle.uid
        ((op_type, status, settings, message, revision),) = self.query(
            "SELECT op_type, status, settings, message, revision_uid FROM gb_operation "
            "WHERE uid = ?", uid)
        self.assertEqual((op_type, status), ("des.platform", "done"))
        self.assertEqual(json.loads(settings), provenance.platform_settings(prep.request(), "PLT-001"))
        self.assertEqual(message, self.first.outcome.message)
        self.assertEqual(self.query("SELECT version_uid, state FROM gb_revision WHERE uid = ?",
                                    revision), [(self.v1.uid, "open")])
        inputs = [(name, role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "ORDER BY io.fid", uid)]
        self.assertEqual(inputs[:2], [(efx.AXES_LAYER, "entity_layer"), (START, "surface")])
        self.assertTrue(all(role.startswith("masks_") for _name, role in inputs[2:]), inputs)
        self.assertNotIn("supported_on", [role for _name, role in inputs])
        params = [key for (key,) in self.query(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ? ORDER BY fid", uid)]
        self.assertEqual(sorted(params), sorted(provenance.platform_params("PLT-001", prep.request())))
        self.assertEqual([record.name for record in self.first_stored.records], [PSF, EPR, PRP])

    def test_b_the_three_data_with_their_roles_and_hashes(self) -> None:
        """RF-015-01, RF-015-02: ``des_psf_`` (``entity_surface``), ``des_epr_`` (``entity``) y
        ``des_prp_`` (``entity_report``) son datos vivos de V01 escritos por la operación, con el hash
        que se preparó al calcular; la superficie está en su sitio sin temporales y las dos tablas, en el
        proyecto."""
        uid = self.first_stored.handle.uid
        outputs = {name: (role, status, sha) for name, role, status, sha in self.query(
            "SELECT d.name, io.role, d.status, io.content_sha256 FROM gb_operation_io AS io "
            "JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? "
            "AND io.direction = 'out'", uid)}
        prepared = {spec.name: spec.content.content_sha256 for spec in self.first.specs}
        self.assertEqual({name: role for name, (role, _status, _sha) in outputs.items()},
                         {PSF: "entity_surface", EPR: "entity", PRP: "entity_report"})
        self.assertEqual({name: sha for name, (_role, _status, sha) in outputs.items()}, prepared)
        self.assertEqual({status for _role, status, _sha in outputs.values()}, {"current"})
        self.assertEqual(self.record(PSF, self.v1).locator,
                         provenance.dataset_locator("psf", LOADING, "V01"))
        stems = {path for path in self.written()["files"]} - set(self.clean["files"])
        self.assertEqual(stems, {provenance.dataset_locator("psf", LOADING, "V01").rsplit("/", 1)[-1],
                                 provenance.dataset_locator("psf", WORKSHOP, "V01").rsplit("/", 1)[-1]})
        self.assertEqual([name for name in written_tables(self) if name in (EPR_TABLE, PRP_TABLE)],
                         sorted((EPR_TABLE, PRP_TABLE)))
        start = qfx.terrain(GRID)
        expected = start.copy()
        expected[self.first.outcome.footprint.window] = self.first.outcome.result
        np.testing.assert_array_equal(self.grid_of(PSF), expected)

    # --- La tabla de la entidad -----------------------------------------------------------------

    def test_b_the_table_of_the_entity_has_the_footprint_the_axis_and_the_attributes(self) -> None:
        """RF-015-01: ``des_epr_`` lleva **una** fila con el código, el nombre, el tipo, la partida, la capa
        y el ``fid`` de origen, el hash de la geometría de origen, el modo, las celdas, la ventana, la huella
        en tramos de fila ``(fila, col0, col1)`` (a mano: 10 filas de 55 a 155) y los vértices del eje
        (absolutos, float64, exactos, los de la capa)."""
        found = self.query(f'SELECT {", ".join(ENTITY_COLUMNS)} FROM "{EPR_TABLE}"')
        self.assertEqual(len(found), 1)
        row = dict(zip(ENTITY_COLUMNS, found[0], strict=True))
        self.assertEqual((row["code"], row["name"], row["kind"]), ("PLT-001", LOADING, "platform"))
        self.assertEqual((row["start_surface"], row["support_surface"]), (START, None))
        self.assertEqual((row["layer"], row["source_fid"], row["mode"], row["cells"],
                          row["axis_principal"]), (efx.AXES_LAYER, efx.axis_fid(LOADING), "cut", 1000, 0))
        runs = json.loads(row["footprint"])
        self.assertEqual(runs, [[r, *LOADING_COLUMNS] for r in LOADING_ROWS])
        footprint = self.first.outcome.footprint
        window = footprint.window
        self.assertEqual(json.loads(row["bounds"]),
                         [window[0].start, window[0].stop, window[1].start, window[1].stop])
        mask = entity_store.runs_mask(runs, GRID.shape)
        self.assertEqual(int(mask.sum()), 1000)
        np.testing.assert_array_equal(mask[window], footprint.cells)
        axis = np.array(json.loads(row["axis"]))
        layer_axis = self.read_layer(efx.AXES_LAYER).parts[efx.axis_fid(LOADING) - 1][0][0]
        np.testing.assert_array_equal(axis, np.asarray(layer_axis)[:, :2])
        self.assertEqual(axis.dtype, np.float64)
        origin = platform.PlatformGeometry(
            "line", self.read_layer(efx.AXES_LAYER).parts[efx.axis_fid(LOADING) - 1])
        self.assertEqual(row["geometry_sha256"], entity_store.geometry_sha256(origin))
        self.assertRegex(row["geometry_sha256"], r"^[0-9a-f]{64}$")

    def test_b_the_second_platform_table_names_its_start_as_a_surface(self) -> None:
        """RF-015-04: la fila de la «Plataforma de taller» guarda su partida resuelta (el dato de la
        superficie de la primera, no ``entity:PLT-001``) y su código; el hash de su geometría no es el
        de la otra."""
        table = provenance.dataset_locator("epr", WORKSHOP, "V01")
        ((code, start, sha),) = self.query(
            f'SELECT code, start_surface, geometry_sha256 FROM "{table}"')
        (other_sha,) = self.query(f'SELECT geometry_sha256 FROM "{EPR_TABLE}"')[0]
        self.assertEqual((code, start), ("PLT-002", PSF))
        self.assertNotEqual(sha, other_sha)

    # --- El informe -----------------------------------------------------------------------------

    def test_b_the_report_has_the_profile_the_counter_slopes_and_the_edge(self) -> None:
        """RF-015-02, RF-015-13, RF-015-23, RF-015-24: ``des_prp_`` en formato largo lleva las cifras de la
        huella y del borde, una fila por tramo del perfil longitudinal, las contrapendientes (ninguna en
        esta plataforma), las pendientes del salto creado y los avisos con su código y sus valores; no lleva
        los que dependen de lo que la operación no consume (la revisión anterior, la otra superficie de la
        cantera), ni ningún valor que no sea finito."""
        rows = self.rows_of(PRP_TABLE)
        outcome = self.first.outcome
        self.assertEqual(rows["area_m2"], [(4000.0, "m2", None)])
        self.assertEqual(rows["cut_m3"][0][:2], (outcome.applied.cut_m3, "m3"))
        self.assertEqual(rows["edge_cut_m3"][0][:2], (outcome.edge.cut_m3, "m3"))
        self.assertEqual(rows["edge_fill_m3"][0][:2], (outcome.edge.fill_m3, "m3"))
        self.assertEqual(rows["axis_m"][0][:2], (outcome.footprint.axis.length_m, "m"))
        self.assertEqual(rows["start_level_m"][0][0], 250.0)
        self.assertEqual(rows["gradient_pct"][0][:2], (1.0, "%"))
        profile = outcome.profile
        shown = [json.loads(note) for _value, _unit, note in rows["profile"]]
        self.assertEqual(len(shown), profile.section.size)
        self.assertEqual([item["section"] for item in shown], profile.section.tolist())
        self.assertEqual([value for value, _unit, _note in rows["profile"]], profile.level_m.tolist())
        self.assertEqual([item["chainage_m"] for item in shown], profile.chainage_m.tolist())
        self.assertNotIn("counter_slope", rows)
        self.assertEqual(rows["counter_sections"][0][0], 0.0)
        self.assertEqual(rows["counter_tolerance_m"][0][:2], (0.1, "m"))
        found = [json.loads(note)["code"] for quantity in ("warning", "note")
                 for _value, _unit, note in rows.get(quantity, [])]
        expected = [notice.code for notice in outcome.notices if notice.code not in OUTSIDE_NOTICES]
        self.assertEqual(sorted(found), sorted(expected))
        self.assertTrue(set(found).isdisjoint(OUTSIDE_NOTICES))
        self.assertTrue(set(codes(self.first.summary)) & OUTSIDE_NOTICES, "el resumen sí los lleva")
        for values in rows.values():
            for value, _unit, _note in values:
                self.assertTrue(value is None or math.isfinite(value))

    # --- Las cifras ------------------------------------------------------------------------------

    def test_b_the_figures_have_the_scope_of_their_entity(self) -> None:
        """RF-015-02, RF-008-30: las cifras de cada plataforma (CALCULADO, con su unidad) se registran con
        el ámbito de su entidad (el nombre y el código): las de la otra con las mismas claves no las pisan
        (a mano: 4.000 m² la primera)."""
        first = self.figures_of(self.first_stored.handle.uid)
        second = self.figures_of(self.second_stored.handle.uid)
        scope = figures_mod.scope_json(provenance.entity_figure_scope(LOADING, "PLT-001"))
        other = figures_mod.scope_json(provenance.entity_figure_scope(WORKSHOP, "PLT-002"))
        self.assertEqual(first, {(figure.key, scope): figure.value for figure in self.first.figures})
        self.assertEqual(second, {(figure.key, other): figure.value for figure in self.second.figures})
        self.assertEqual(first[("des.plat_area_m2", scope)], 4000.0)
        self.assertGreater(len(first), 9)
        self.assertTrue(set(key for key, _scope in first) & set(key for key, _scope in second))
        both = self.query("SELECT key, count(*), count(DISTINCT scope) FROM gb_figure "
                          "WHERE key = 'des.plat_area_m2' GROUP BY key")
        self.assertEqual(both, [("des.plat_area_m2", 2, 2)])
        kinds = {kind for (kind,) in self.query(
            "SELECT DISTINCT kind FROM gb_figure WHERE operation_uid IN (?, ?)",
            self.first_stored.handle.uid, self.second_stored.handle.uid)}
        self.assertEqual(kinds, {"CALCULADO"})

    # --- Los parámetros de la entidad ------------------------------------------------------------

    def test_b_the_parameters_of_the_entity_are_version_rows_with_their_origin(self) -> None:
        """RF-015-01, RF-008-01, RF-009-29: «Crear» escribe cada parámetro de la entidad como una fila de la
        **versión** (ADOPTADO, de la persona que tiene abierto el proyecto, con su motivo) con su origen:
        «capa X, campo Y, entidad Z» los copiados de la capa; el diálogo, lo que eligió la persona; el valor
        por defecto, la procedencia de su definición. El registro ve la entidad al día con su operación.

        **Limitación conocida** (trampa de la T04, ``docs/trampas.md`` §6): ``begin_operation`` deja en el
        proyecto una fila «sin confirmar» por clave que lee (``ensure_default``; no hacen entidad ni se
        leen: la de la versión manda); solo de las que lee, no las del nombre, lo que declara o la
        pendiente máxima."""
        store = core_params.ParameterStore(self.project)
        decider = self.project.session.user_host
        for row in self.first.entity.rows:
            with self.subTest(key=row.key):
                record = store.get(row.key, version=self.v1.uid)
                self.assertIsNotNone(record)
                self.assertEqual((record.scope, record.scope_uid), ("version", self.v1.uid))
                self.assertEqual((record.value, str(record.kind), record.decided_by),
                                 (row.value, "ADOPTADO", decider))
                self.assertEqual((record.source, str(record.source_kind)),
                                 (row.source, row.source_kind))
                self.assertFalse(record.unconfirmed)
                self.assertIsNotNone(record.decided_at)
        origin = {row.param.value: row.source for row in self.first.entity.rows}
        for param, field in (("width_m", "ancho"), ("start_level_m", "cota_inicial"),
                             ("gradient_pct", "pendiente")):
            self.assertEqual(origin[param],
                             f"capa «{efx.AXES_LAYER}», campo «{field}», entidad «{LOADING}»")
        versioned = {key for (key,) in self.query(
            "SELECT key FROM gb_parameter WHERE key LIKE 'des.platform.plt_001.%' "
            "AND scope = 'version'")}
        self.assertEqual(versioned, {row.key for row in self.first.entity.rows})
        read = {item for item in provenance.platform_params("PLT-001", prep.request())
                if item.startswith("des.platform.")}
        placeholders = {key: unconfirmed for key, unconfirmed in self.query(
            "SELECT key, unconfirmed FROM gb_parameter WHERE key LIKE 'des.platform.plt_001.%' "
            "AND scope = 'project'")}
        self.assertEqual(set(placeholders), read)
        self.assertTrue(all(placeholders.values()), "sin confirmar, no de la entidad")
        self.assertNotIn(design_params.entity_key("PLT-001", "name"), placeholders)
        self.assertNotIn(design_params.entity_key("PLT-001", "protect"), placeholders)
        by_key = {item.key: (item.scope, item.value) for item in self.first_stored.handle.params}
        for row in self.first.entity.rows:
            if row.key in read:
                self.assertEqual(by_key[row.key], ("version", row.value), row.key)
        registry = entities_module.registry(self.project, self.v1.uid)
        entry = registry.get("PLT-001")
        self.assertEqual((entry.record.name, str(entry.record.state)), (LOADING, "current"))
        self.assertEqual(entry.operation_uid, self.first_stored.handle.uid)

    # --- La capa de origen ------------------------------------------------------------------------

    def test_b_the_source_layers_are_not_modified(self) -> None:
        """RF-015-01 (principio 7): tras calcular y crear dos plataformas, las capas de plataformas (ejes y
        polígonos) tienen el mismo registro (uid, estado y hash de contenido) y el mismo contenido que
        antes, y las operaciones las anotan como entradas con ese hash."""
        self.assertEqual(self.layers_after, self.layers_before)
        sha = self.layers_before[efx.AXES_LAYER][0][0][2]
        io = self.query("SELECT content_sha256 FROM gb_operation_io WHERE operation_uid = ? "
                        "AND role = 'entity_layer'", self.first_stored.handle.uid)
        self.assertEqual(io, [(sha,)])

    # --- La cadena ----------------------------------------------------------------------------------

    def test_b_a_chained_platform_consumes_the_surface_of_the_first(self) -> None:
        """RF-015-04, RF-015-01: la «Plataforma de taller», con partida ``entity:PLT-001``, consume la
        superficie de la primera (``des_psf_…``, papel ``surface``) y no el terreno; su resultado es igual a
        esa superficie fuera de las celdas que mueve (y por debajo de ella), y la última de la cadena es la
        suya."""
        uid = self.second_stored.handle.uid
        inputs = {(name, role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid)}
        self.assertIn((PSF, "surface"), inputs)
        self.assertNotIn((START, "surface"), inputs)
        self.assertEqual(self.second.entity.start_surface, PSF)
        value = core_params.ParameterStore(self.project).get(
            design_params.entity_key("PLT-002", "start"), version=self.v1.uid)
        self.assertEqual(value.value, "entity:PLT-001")
        first, second = self.grid_of(PSF), self.grid_of(provenance.dataset_name("psf", WORKSHOP))
        mine = self.second.outcome.footprint.window
        theirs = self.first.outcome.footprint.window
        self.assertFalse(mine[0].start < theirs[0].stop and theirs[0].start < mine[0].stop
                         and mine[1].start < theirs[1].stop and theirs[1].start < mine[1].stop,
                         "las ventanas de trabajo no se cruzan")
        untouched = np.ones(GRID.shape, dtype=bool)
        untouched[mine] = False
        np.testing.assert_array_equal(second[untouched], first[untouched])
        with np.errstate(invalid="ignore"):
            self.assertTrue((second <= first).all())
            self.assertTrue((second < first).any())
        records = entities_module.registry(self.project, self.v1.uid).records
        self.assertEqual([item.code for item in entities_module.chain_tails(records)], ["PLT-002"])
        self.assertEqual([str(entry.record.state) for entry in
                          entities_module.registry(self.project, self.v1.uid)],
                         ["current", "current"])


class ChainStaleTest(CreateCase):
    """RF-015-04, RF-015-16, RF-008-24: cambiar un parámetro de la primera plataforma deja obsoleta la
    primera y, en cascada, la que parte de su superficie, cada una con su causa."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.first = cls.calculate_in(prep.request()).create()
        cls.clock.advance(minutes=1)
        cls.second = cls.calculate_in(prep.request(WORKSHOP, start="entity:PLT-001")).create()

    def test_b_changing_a_parameter_of_the_first_stales_it_and_the_next_with_the_cause(self) -> None:
        """RF-015-04, RF-015-16: antes de cambiar nada ninguna está obsoleta; con el alcance de la primera
        cambiado (parámetro de su fila de la versión), la primera queda obsoleta por ese parámetro y la
        segunda, que consumió su superficie, también (``parameter_changed``, en cascada); el registro de las
        entidades las da como obsoletas, con la causa, y «Recalcular lo obsoleto» tiene dos operaciones."""
        reach = design_params.entity_key("PLT-001", "reach_m")
        first, second = self.first.handle.uid, self.second.handle.uid
        self.assertEqual((self.stale_causes(first), self.stale_causes(second)), (set(), set()))
        self.assertEqual(self.recompute_plan(), [])
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, reach, value=25.0, version=self.v1.uid, reason="Prueba de la T13")
        self.assertEqual(self.stale_causes(first), {("parameter_changed", reach)})
        self.assertIn(("parameter_changed", reach), self.stale_causes(second))
        own = design_params.entity_key("PLT-002", "reach_m")
        self.assertNotIn(("parameter_changed", own), self.stale_causes(second))
        registry = entities_module.registry(self.project, self.v1.uid)
        self.assertEqual([str(entry.record.state) for entry in registry], ["stale", "stale"])
        for entry in registry:
            self.assertEqual({cause.kind for cause in entry.causes}, {"parameter_changed"})
        self.assertEqual(len(self.recompute_plan()), 2)


# ---------------------------------------------------------------------------------------------
# «Crear»: todo o nada
# ---------------------------------------------------------------------------------------------


class CounterSlopeCreateTest(CreateCase):
    """RF-015-23: una plataforma con contrapendiente que pasa de la tolerancia no se crea sin la
    confirmación expresa de quien la pide."""

    def test_b_a_counter_slope_is_not_created_without_confirmation(self) -> None:
        """La «Plataforma de la torre» (con una contrapendiente: la torre de la zona intocable) pide
        confirmación: ``create()`` se rechaza (``des.platform_counter_unconfirmed``) **antes de escribir
        nada** y deja la cuenta abierta; confirmada en la cuenta, se crea, con su contrapendiente en el
        informe y su aviso."""
        calculation = self.calculate_in(prep.request(TOWER))
        self.addCleanup(calculation.discard)
        self.assertTrue(calculation.needs_confirmation)
        before = self.written()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.platform_counter_unconfirmed")
        self.assertEqual(self.written(), before)
        self.assertTrue(calculation.open)
        with self.assertRaises(messages.DesignError) as direct:  # la función pública, por sí sola
            entity_store.create_platform(self.project, calculation._writer, calculation.entity,
                                         calculation.outcome)
        self.assertEqual(direct.exception.code, "des.platform_counter_unconfirmed")
        self.assertEqual(self.written(), before)
        calculation.confirm_counterslope()
        self.clock.advance(minutes=1)
        stored = calculation.create()
        self.assertEqual(stored.handle.op_type, "des.platform")
        table = provenance.dataset_locator("prp", TOWER, "V01")
        rows = self.rows_of(table)
        profile = calculation.outcome.profile
        self.assertEqual(len(rows["counter_slope"]), profile.counter_sections)
        self.assertGreater(len(rows["counter_slope"]), 0)
        worst = max(rows["counter_slope"], key=lambda item: item[0])
        self.assertEqual(worst[0], float(profile.rise_m.max()))
        self.assertEqual(rows["counter_sections"][0][0], float(profile.counter_sections))
        found = [json.loads(note)["code"] for _value, _unit, note in rows["warning"]]
        self.assertIn("des.platform_counter_slope", found)


class CounterSlopeAskedTest(CreateCase):
    """RF-015-23: lo mismo con la confirmación pedida desde el principio."""

    def test_b_a_counter_slope_asked_confirmed_is_created(self) -> None:
        """Pedida ya confirmada (``confirm_counterslope=True``), se crea sin más."""
        calculation = self.calculate_in(prep.request(TOWER), confirm_counterslope=True)
        self.assertFalse(calculation.needs_confirmation)
        self.clock.advance(minutes=1)
        self.assertEqual(calculation.create().handle.op_type, "des.platform")


# ---------------------------------------------------------------------------------------------
# «Crear»: una entidad que ya está en la versión y el gancho de las dependencias
# ---------------------------------------------------------------------------------------------


class ExistingEntityTest(CreateCase):
    """RF-015-01 (RF-015-18): una entidad que ya está en la versión (sus parámetros, sin calcular: lo que
    deja «Traer las entidades de…») se calcula con su código y «Crear» registra su operación **sin escribir
    otra vez sus parámetros**."""

    def test_b_an_entity_already_in_the_version_is_not_written_again(self) -> None:
        asked = prep.request()
        prepared = self.units(asked)
        self.clock.advance(minutes=1)
        entity_store.set_entity_params(self.project, prepared.rows, version=self.v1.uid,
                                       decided_by=prep.USER)
        rows = self.query("SELECT uid, key, value, decided_by, rev FROM gb_parameter "
                          "WHERE scope = 'version' ORDER BY fid")
        self.clock.advance(minutes=1)
        calculation = self.calculate_in(asked, code="PLT-001")
        self.assertTrue(calculation.entity.existing)
        self.assertFalse(self.calculate(prep.request(WORKSHOP, start=prep.HOLE_DATASET))
                         .entity.existing)
        stored = calculation.create()
        self.assertEqual(self.query("SELECT uid, key, value, decided_by, rev FROM gb_parameter "
                                    "WHERE scope = 'version' AND key LIKE 'des.platform.plt_001.%' "
                                    "ORDER BY fid"), rows)
        entry = entities_module.registry(self.project, self.v1.uid).get("PLT-001")
        self.assertEqual((str(entry.record.state), entry.operation_uid),
                         ("current", stored.handle.uid))
        scopes = {item.scope for item in stored.handle.params
                  if item.key.startswith("des.platform.")}
        self.assertEqual(scopes, {"version"})


class RacedEntityTest(CreateCase):
    """RF-015-01: dos sesiones calcularon la misma entidad nueva (el mismo código) y una creó antes."""

    def test_b_a_new_entity_whose_rows_appeared_meanwhile_is_refused(self) -> None:
        """Si entre «Calcular» y «Crear» alguien dio de alta una entidad con el mismo código (sus
        parámetros), «Crear» no pisa ni se queda con las suyas: ``core.param_exists``, nada se escribe y
        la cuenta queda cerrada."""
        calculation = self.calculate_in(prep.request())
        self.assertEqual(calculation.entity.code, "PLT-001")
        other = self.units(prep.request(WORKSHOP, start=prep.HOLE_DATASET), code="PLT-001")
        self.clock.advance(minutes=1)
        entity_store.set_entity_params(self.project, other.rows, version=self.v1.uid,
                                       decided_by=prep.USER)
        expected = self.settled(self.written())
        with self.assertRaises(core_params.ParamError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "core.param_exists")
        self.assertEqual(self.written(), expected)
        self.assertFalse(calculation.open)


class SupportsHookTest(CreateCase):
    """RF-015-15 (T23): el gancho de las dependencias es el genérico de ``DesignWriter.commit``
    (``design.store``; ``test_entity_supports``): la primera plataforma de una versión **sin entidades** no se
    apoya en nada, ``detected_supports`` da ``()`` y crearla ni llama a la medida de lo apoyado."""

    def test_b_the_first_platform_of_a_version_rests_on_nothing_and_pays_nothing_for_the_hook(self) -> None:
        calculation = self.calculate_in(prep.request())
        self.assertEqual(entity_store.detected_supports(
            self.project, calculation.entity, calculation.outcome), ())
        self.clock.advance(minutes=1)
        with mock.patch.object(entity_store, "survey_supports",
                               side_effect=AssertionError("sin entidades en la versión, ni se llama")):
            stored = calculation.create()
        inputs = self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.role IN ('supported_on', "
            "'support_footprint')", stored.handle.uid)
        self.assertEqual(inputs, [])
        self.assertEqual(self.query("SELECT key FROM gb_figure WHERE operation_uid = ? AND key = "
                                    "'des.supported_m3'", stored.handle.uid), [])


# ---------------------------------------------------------------------------------------------
# Las funciones puras de la tabla de la entidad
# ---------------------------------------------------------------------------------------------


class EntityTableTest(unittest.TestCase):
    """RF-015-01: la huella en tramos de fila, su inversa y el hash de la geometría de origen."""

    def test_b_the_footprint_in_runs_and_back(self) -> None:
        """La huella de una ventana (con un hueco, una celda suelta y los bordes de la ventana) son sus
        tramos ``(fila, col0, col1)`` **absolutos** de la rejilla, de norte a sur y de oeste a este, con
        ``col1`` excluida; ``runs_mask`` los devuelve a la máscara de la rejilla entera."""
        mask = np.array([[1, 1, 0, 1, 1],
                         [0, 0, 0, 0, 0],
                         [1, 0, 0, 0, 1],
                         [0, 1, 1, 1, 0]], dtype=bool)
        window = (slice(3, 7), slice(2, 7))
        found = entity_store.footprint_runs(mask, window)
        self.assertEqual(found, [(3, 2, 4), (3, 5, 7), (5, 2, 3), (5, 6, 7), (6, 3, 6)])
        whole = entity_store.runs_mask(found, (10, 10))
        np.testing.assert_array_equal(whole[window], mask)
        self.assertEqual(int(whole.sum()), int(mask.sum()))
        self.assertEqual(entity_store.footprint_runs(np.zeros((2, 2), dtype=bool),
                                                     (slice(0, 2), slice(0, 2))), [])
        self.assertFalse(entity_store.runs_mask([], (3, 3)).any())

    def test_b_a_run_outside_the_grid_is_a_program_error(self) -> None:
        for runs in ([(0, 3, 3)], [(0, 4, 2)], [(3, 0, 1)], [(0, 0, 4)], [(-1, 0, 1)]):
            with self.subTest(runs=runs):
                with self.assertRaises(ValueError):
                    entity_store.runs_mask(runs, (3, 3))

    def test_b_the_geometry_hash_follows_the_geometry_to_the_last_bit(self) -> None:
        """El hash de la geometría de origen es el mismo para la misma geometría y cambia con el tipo, con
        un vértice movido 10⁻⁹ m (la resolución de un float64 a 4,4 Mm de norte), con otra parte y con el
        eje enlazado de un polígono."""
        path = np.array([[725_100.0, 4_400_100.5], [725_200.0, 4_400_100.5]])
        base = platform.PlatformGeometry("line", ((path,),))
        again = platform.PlatformGeometry("line", ((path.copy(),),))
        self.assertEqual(entity_store.geometry_sha256(base), entity_store.geometry_sha256(again))
        self.assertRegex(entity_store.geometry_sha256(base), r"^[0-9a-f]{64}$")
        moved = path.copy()
        moved[1, 1] = np.nextafter(moved[1, 1], np.inf)
        self.assertNotEqual(entity_store.geometry_sha256(platform.PlatformGeometry("line", ((moved,),))),
                            entity_store.geometry_sha256(base))
        ring = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]])
        polygon = platform.PlatformGeometry("polygon", ((ring,),))
        self.assertNotEqual(entity_store.geometry_sha256(polygon),
                            entity_store.geometry_sha256(platform.PlatformGeometry("line", ((ring,),))))
        linked = platform.PlatformGeometry("polygon", ((ring,),), axis_parts=((path,),))
        self.assertNotEqual(entity_store.geometry_sha256(linked), entity_store.geometry_sha256(polygon))
        two = platform.PlatformGeometry("line", ((path,), (path,)))
        self.assertNotEqual(entity_store.geometry_sha256(two), entity_store.geometry_sha256(base))

    def test_b_the_columns_of_the_tables_of_an_entity(self) -> None:
        """RF-015-01: el escritor conoce las tablas de la plataforma: ``des_epr_`` con las columnas de
        la entidad y ``des_prp_`` con las del informe largo."""
        found = design_store.columns_of("des.platform", "epr")
        self.assertEqual(tuple(column.name for column in found), ENTITY_COLUMNS)
        self.assertEqual(found, design_store.ENTITY_COLUMNS)
        self.assertEqual(design_store.columns_of("des.platform", "prp"), design_store.REPORT_COLUMNS)
        with self.assertRaises(KeyError):
            design_store.columns_of("des.platform", "psf")


# ---------------------------------------------------------------------------------------------
# Recalcular y reproducir (T14; casos (c), (d) y (e))
# ---------------------------------------------------------------------------------------------

PSF2 = provenance.dataset_name("psf", WORKSHOP)
"""El nombre de la superficie de la «Plataforma de taller»."""


def recompute_function(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de ``des.platform``: lleva los pasos hasta el
    final."""
    handle, work = design_store.recompute_run(request)
    finish(work)
    return handle


def real_definitions() -> tuple[Any, ...]:
    """Los tipos de las entidades con las funciones **reales** de la plataforma y de la capa de entidades
    (recalcular) y de la plataforma (reproducir), las de la declaración sin llamar y las cifras, como los
    registra ``bl``."""
    types = prep.ENTITY_TYPES
    real = (provenance.PLATFORM, provenance.ENTITY_LAYER)
    return (*provenance.entity_operation_defs(
        {kind: recompute_function if kind in real else prep.never for kind in types},
        {kind: design_reproduce.reproduce_platform if kind == provenance.PLATFORM else prep.never
         for kind in provenance.ENTITY_REPRODUCIBLE}), *provenance.ENTITY_FIGURES)


class RecomputeCase(CreateCase):
    """Lo de ``CreateCase`` con los tipos de las entidades registrados con sus funciones reales y los
    ayudantes de las historias de recalcular y reproducir."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return real_definitions()

    @classmethod
    def made(cls, asked: Any) -> Any:
        """«Calcula» y «crea» ``asked`` en V01 (un minuto después de lo anterior): su ``Stored``."""
        cls.clock.advance(minutes=1)
        return cls.calculate_in(asked).create()

    def current(self, code: str) -> str:
        """El uid de la operación vigente de la entidad ``code`` de V01 (el registro de las entidades)."""
        entry = entities_module.registry(self.project, self.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    def request_for(self, uid: str) -> Any:
        """Lo que recibe ``bl`` para recalcular la operación ``uid``: sus ajustes y su versión."""
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(self.project, uid, provenance.PLATFORM,
                                              json.loads(settings), (), (), version=self.v1.uid)

    @classmethod
    def change(cls, key: str, value: object) -> None:
        """Cambia el parámetro de la versión ``key`` (un minuto después)."""
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).change(
                conn, key, value=value, version=cls.v1.uid, reason="Prueba de la T14")

    def hashes_of(self, uid: str) -> dict[str, str]:
        """El hash que anotó la operación ``uid`` de cada dato que escribió (por su nombre)."""
        return dict(self.query(
            "SELECT d.name, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d "
            "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", uid))

    def version_rows(self) -> list[tuple[Any, ...]]:
        """Los parámetros propios de las versiones, con su historial."""
        return self.query("SELECT key, value, rev, decided_by FROM gb_parameter "
                          "WHERE scope = 'version' ORDER BY fid")

    def plan_units(self) -> list[tuple[str, ...]]:
        """Las operaciones (su uid) de cada unidad del plan de «Recalcular lo obsoleto», en su orden."""
        graph = import_geoblender("core.provenance.graph")
        with self.project.read() as conn:
            return [tuple(unit.operations) for unit in
                    recompute_mod.plan_recompute(graph.load_graph(conn)).units]


class RecomputeCounterSlopeTest(RecomputeCase):
    """RF-015-23: un recálculo no confirma por la persona una contrapendiente mayor que la que ella confirmó
    (T14; con la confirmada de T15, véase ``RecomputeConfirmedCounterSlopeTest``)."""

    def test_c4_a_counter_slope_that_is_not_confirmed_is_not_registered(self) -> None:
        """RF-015-23: la «Plataforma de la torre», creada con la confirmación de su contrapendiente y con su
        cota inicial 3 m más baja (la contrapendiente crece más que la tolerancia sobre la confirmada), al
        recalcularla **no la confirma por la persona**: se rechaza al avanzar
        (``des.platform_counter_unconfirmed``), la operación nueva queda fallida, la anterior sigue
        vigente y no queda ningún dato, cifra ni temporal más."""
        self.clock.advance(minutes=1)
        old = self.calculate_in(prep.request(TOWER), confirm_counterslope=True).create().handle.uid
        self.change(design_params.entity_key("PLT-001", "start_level_m"), 212.0)
        before = self.written()
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(old))
        with self.assertRaises(messages.DesignError) as caught:
            finish(work)
        self.assertEqual(caught.exception.code, "des.platform_counter_unconfirmed")
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("failed", old)])
        self.assertEqual(self.current("PLT-001"), old)
        after = self.written()
        for key in ("datasets", "parameters", "figures", "tables", "files"):
            self.assertEqual(after[key], before[key], key)


class ReproduceFunctionsTest(unittest.TestCase):
    """RF-015-02: las funciones de reproducir de los tipos de las entidades."""

    def test_d2_what_is_not_a_request_or_not_a_platform_is_a_program_error(self) -> None:
        """RF-015-02: lo que no es una petición de reproducir, o es la de otro tipo de operación, es un error
        del programa."""
        with self.assertRaises(TypeError):
            design_reproduce.reproduce_platform("petición")
        other = reproduce_mod.ReproduceRequest("des.quarry", {}, (), {}, ".", None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            design_reproduce.reproduce_platform(other)

    def test_d2_the_layer_of_the_entities_is_not_reproducible(self) -> None:
        """RF-015-27, RF-015-02 (T30): la capa de entidades **no se reproduce** (su contenido incluye el estado de
        cada entidad, que deduce el grafo del proyecto: es una vista regenerable, como ``des.refit``): no tiene función
        de reproducir ni en ``design.reproduce`` ni en la definición de su tipo, que sí se repite sola. La de la
        declaración de restricciones es real desde la T17 (``test_declare_operation``)."""
        self.assertFalse(hasattr(design_reproduce, "reproduce_entity_layer"))
        self.assertNotIn(provenance.ENTITY_LAYER, provenance.ENTITY_REPRODUCIBLE)
        declared = provenance.OPERATION_TYPES_BY_NAME[provenance.ENTITY_LAYER]
        self.assertFalse(declared.reproducible)
        self.assertIn(provenance.ENTITY_LAYER, provenance.ENTITY_VERSION_TYPES)
        defined = declared.definition(recompute_function)
        self.assertEqual((defined.repeatable, defined.drops_discarded, defined.reproduce, defined.figure_tolerance),
                         (True, True, None, None))


if __name__ == "__main__":
    unittest.main()
