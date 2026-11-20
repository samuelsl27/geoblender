# SPDX-License-Identifier: GPL-3.0-or-later
"""RF-015-13 y RF-015-14 con los tipos de la 016, en el dominio (spec 016, T46; HU-016-3, HU-016-4; RF-015-13, RF-015-14, RF-016-17,
RF-016-20; hallazgos C-1 y C-2 de la verificación única): lo que el contrafuerte y el cuerpo «sobre una base» avisan de su borde y de
su orden con la cantera, **como la plataforma** (``design.platform``), sin cambiar ninguna cifra.

- **La huella recortada por la rejilla** (:class:`ClippedByTheGridTest`): las celdas que el polígono de la zona de coronación o de la
  huella tendría fuera de la rejilla, con el lugar de la primera, contra la **fuerza bruta** de la 015 (la misma geometría sobre una
  rejilla mayor, sin recortar: ``ClippedByTheGridTest`` de ``test_platform_footprint``) y contra la medida de la propia plataforma.
- **Lo que llega al borde de la rejilla o a celdas sin dato** (:class:`ButtressEdgeTest`, :class:`BodyEdgeTest`): las celdas que
  suben **fuera de la huella** y están en el borde de la rejilla o junto a una celda sin dato, con su área y el lugar de la primera,
  contra un bucle de Python independiente (las ocho vecinas de cada celda); lo de dentro de la huella no cuenta aquí (RF-015-09: lo
  avisa **la zona sin dato**, T53); sin geometría o en medio de la rejilla, ningún aviso; con una ventana de trabajo, lo mismo que con la
  rejilla entera.
- **Las celdas sin dato de la huella** (:class:`ButtressNoDataTest`, :class:`NoDataNoticeTest`; T53, decisión 8 de «Para Samuel»): la
  excepción de la 016 a RF-015-09 tolera las celdas de la zona de coronación sin dato (no siembran, no cuentan en el volumen) y **las
  avisa con su lugar** (RF-015-13): cuántas, su área y la primera; ninguna cifra cambia.
- **El orden con la otra superficie de la cantera** (:class:`QuarryOrderTest`): ``supported_store.order_notices`` con la otra superficie
  de la 014 como la plataforma (``order_check``: 1 mm; ``final`` no pasa de la explotación y la explotación no baja de la final); el
  aviso lleva lo mismo que el de la plataforma y no impide crear.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import unittest
from typing import Any

import numpy as np

from tests.support import buttress_data as bdata
from tests.support.package import import_geoblender
from tests.unit.design import test_platform_footprint as pfp
from tests.unit.design import test_thickness as tt

buttress = import_geoblender("design.buttress")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
platform = import_geoblender("design.platform")
supported_edge = import_geoblender("design.supported_edge")
supported_store = import_geoblender("design.supported_store")
thickness = import_geoblender("design.thickness")
zones = import_geoblender("design.zones")

OUTSIDE = "des.entity_edge_outside"
BUTTRESS_NO_DATA = "des.buttress_no_data"
BUTTRESS_CLIPPED = "des.buttress_footprint_clipped"
BODY_CLIPPED = "des.body_footprint_clipped"
EDGE_STEP = "des.body_edge_step"
ORDER = "des.entity_quarry_order"
FOOT_CUT = "des.buttress_foot_cut"
PROJECT = {"des.tolerance.face_deg": 1.0, "des.warning.magnitude_ratio": 2.0, "res.verify.min_thickness_m": 0.02,
           "des.edge.max_created_step_m": 1.0, "des.edge.min_share": 99.0}


def of(notices: Any, code: str) -> list[Any]:
    """Los avisos de ``code``."""
    return [item for item in notices if item.code == code]


def with_parts(job: Any, parts: Any) -> Any:
    """El mismo trabajo con la geometría de su huella (``parts``: lo que lee ``as_parts``)."""
    return dataclasses.replace(job, parts=parts)


def hand_clipped(parts: Any, grid: Any, margin: int = 12) -> tuple[int, float, float] | None:
    """Lo que la rejilla recorta de la geometría ``parts``, **por fuerza bruta**: las celdas de su misma geometría sobre una rejilla
    ``margin`` celdas mayor por cada lado (sin recortar) que no están en la de dentro y el lugar de la primera (de norte a sur y de
    oeste a este, en las coordenadas de la rejilla de verdad). ``None`` si no falta ninguna."""
    wide = gis.Grid(grid.west - margin * grid.dx, grid.north + margin * grid.dy, grid.dx, grid.dy, grid.ncols + 2 * margin,
                    grid.nrows + 2 * margin)
    found = zones.polygons_cells(parts, wide)
    found[margin:margin + grid.nrows, margin:margin + grid.ncols] = False
    where = np.argwhere(found)
    if not len(where):
        return None
    row, col = int(where[0][0]) - margin, int(where[0][1]) - margin
    return int(len(where)), float(grid.west + (col + 0.5) * grid.dx), float(grid.north - (row + 0.5) * grid.dy)


def hand_outside(start: np.ndarray, moved: np.ndarray, own: np.ndarray, *, skip: bool = True) -> list[tuple[int, int]]:
    """Las celdas de ``moved`` que están en el borde de la rejilla (la fila o la columna primera o última del array: el trabajo lleva la
    rejilla entera) o tienen **alguna de sus ocho vecinas sin dato** (``NaN`` en ``start``) que no es de la huella ``own``, de norte a
    sur y de oeste a este (un bucle de Python independiente). Con ``skip`` (el contrafuerte: lo que sube **fuera** de su zona) las
    celdas de ``own`` no cuentan; sin él (el cuerpo: lo que sube está dentro de su huella) cuentan todas."""
    rows, cols = start.shape
    found = []
    for row, col in itertools.product(range(rows), range(cols)):
        if not moved[row, col] or (skip and own[row, col]):
            continue
        near = any(0 <= row + dr < rows and 0 <= col + dc < cols and not np.isfinite(start[row + dr, col + dc])
                   and not own[row + dr, col + dc] for dr, dc in itertools.product((-1, 0, 1), repeat=2))
        if row in (0, rows - 1) or col in (0, cols - 1) or near:
            found.append((row, col))
    return found


def place(grid: Any, cell: tuple[int, int]) -> tuple[float, float]:
    """El centro absoluto de la celda ``(fila, columna)``."""
    return float(grid.west + (cell[1] + 0.5) * grid.dx), float(grid.north - (cell[0] + 0.5) * grid.dy)


# --- La huella recortada por la rejilla -------------------------------------------------------------------------------------------


class ClippedByTheGridTest(unittest.TestCase):
    """RF-015-13 (T46 de la 015, hallazgos D-1 y A-7, con los tipos de la 016): si la rejilla recorta la geometría de la huella, las
    celdas de fuera y el lugar de la primera; sin recorte, nada."""

    def test_it_is_what_a_bigger_grid_would_have_measured(self) -> None:
        """Contra la fuerza bruta (la misma geometría sobre una rejilla mayor, sin recortar) con un polígono que sale por el oeste,
        otro por el norte y el este, uno en L, dos partes que se solapan, uno con un hueco y uno de vértices que no caen en el borde de
        una celda."""
        grid = tt.GRID
        cases = {
            "oeste": ((tt.ring(5, 15, -4, 6),),),
            "norte y este": ((tt.ring(-3, 6, 18, 28),),),
            "L": ((np.array([[grid.west - 8, grid.north - 20], [grid.west + 14, grid.north - 20], [grid.west + 14, grid.north - 34],
                             [grid.west + 4, grid.north - 34], [grid.west + 4, grid.north - 46], [grid.west - 8, grid.north - 46]]),),),
            "dos partes": ((tt.ring(2, 10, -5, 5),), (tt.ring(6, 14, -2, 8),)),
            "hueco": ((tt.ring(4, 16, -6, 8), tt.ring(8, 12, -3, 3)),),
            "fraccionario": ((np.array([[grid.west - 6.3, grid.north - 10.7], [grid.west + 9.4, grid.north - 10.2],
                                        [grid.west + 9.1, grid.north - 30.9], [grid.west - 6.6, grid.north - 30.4]]),),),
        }
        for name, parts in cases.items():
            with self.subTest(case=name):
                wanted = hand_clipped(parts, grid)
                self.assertIsNotNone(wanted)
                found = _run(supported_edge.clipped_units(supported_edge.as_parts(parts), grid))
                self.assertEqual(found, wanted)

    def test_it_is_what_the_platform_measures_for_the_same_polygon(self) -> None:
        """Contra la plataforma de la 015 (``platform_footprint``: ``outside_cells``, ``outside_x``, ``outside_y``) con las mismas
        geometrías de su ``ClippedByTheGridTest`` (rejilla de 1 m): lo mismo, a la celda."""
        grid = pfp.GRID
        l_shape = pfp.ring((350.0, 350.0), (450.0, 350.0), (450.0, 450.0), (380.0, 450.0), (380.0, 380.0), (350.0, 380.0))
        two = platform.PlatformGeometry("polygon", (
            (pfp.ring((-30.0, 100.0), (30.0, 100.0), (30.0, 140.0), (-30.0, 140.0)),),
            (pfp.ring((-10.0, 120.0), (50.0, 120.0), (50.0, 160.0), (-10.0, 160.0)),)))
        for name, geometry in (("L", pfp.polygon_path(l_shape)), ("dos partes", two),
                               ("sur", pfp.polygon_path(pfp.ring((180.0, -30.0), (220.0, -30.0), (220.0, 30.0), (180.0, 30.0)))),
                               ("fraccionario", pfp.polygon_path(pfp.ring((-30.3, 100.7), (30.4, 100.2), (30.1, 160.9),
                                                                          (-30.6, 160.4))))):
            with self.subTest(case=name):
                real = platform.platform_footprint(pfp.make_job(geometry, pfp.polygon_request("P", linked=False), pfp.values()))
                found = _run(supported_edge.clipped_units(supported_edge.as_parts(geometry.parts), grid))
                self.assertIsNotNone(found)
                self.assertEqual(found, (real.outside_cells, real.outside_x, real.outside_y))

    def test_a_geometry_inside_the_grid_or_on_its_border_says_nothing(self) -> None:
        """Dentro de la rejilla, pegada a su borde sin pasarlo o con la caja fuera pero ningún centro fuera: ``None`` y ningún aviso."""
        grid = tt.GRID
        for parts in (((tt.ring(5, 15, 5, 15),),), ((tt.ring(0, 8, 0, 8),),), ((tt.ring(16, 24, 16, 24),),)):
            self.assertIsNone(_run(supported_edge.clipped_units(supported_edge.as_parts(parts), grid)))
        sliver = np.array([[grid.west - 0.3, grid.north - 10.0], [grid.west + 8.0, grid.north - 10.0], [grid.west + 8.0, grid.north - 20.0],
                           [grid.west - 0.3, grid.north - 20.0]])
        self.assertIsNone(_run(supported_edge.clipped_units(supported_edge.as_parts(((sliver,),)), grid)))
        self.assertIsNone(supported_edge.clipped_notice(BUTTRESS_CLIPPED, "X", None, grid))

    def test_the_notice_carries_the_cells_the_area_and_the_place(self) -> None:
        """El aviso lleva la entidad, las celdas, su área (m²) y el lugar al cm de la primera."""
        grid = tt.GRID
        parts = ((tt.ring(5, 15, -4, 6),),)
        cells, x, y = hand_clipped(parts, grid)  # type: ignore[misc]
        notice = supported_edge.clipped_notice(BODY_CLIPPED, "Muro", (cells, x, y), grid)
        self.assertEqual(notice.code, BODY_CLIPPED)
        self.assertEqual(dict(notice.values), {"entity": "Muro", "cells": cells, "area": cells * grid.cell_area, "x": round(x, 2),
                                               "y": round(y, 2)})
        self.assertEqual(notice.severity, "warning")
        self.assertIn("Muro", notice.text("es"))
        self.assertIn("rejilla", notice.text("es"))
        self.assertIn("grid", notice.text("en"))

    def test_the_geometry_is_checked(self) -> None:
        """Una geometría con un anillo que no son vértices finitos (k, 2) o (k, 3) de al menos tres es un error del programa."""
        for parts in (((),), (np.zeros((2, 2)),), (((np.array([[0.0, 0.0], [1.0, np.nan], [2.0, 2.0]])),),)):
            with self.subTest(parts=str(parts)[:30]), self.assertRaises((ValueError, TypeError)):
                supported_edge.as_parts(parts)
        self.assertIsNone(supported_edge.as_parts(None))


def _run(work: Any) -> Any:
    """El resultado de unas unidades de trabajo ejecutadas hasta el final."""
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value


# --- El contrafuerte --------------------------------------------------------------------------------------------------------------


class ButtressEdgeTest(unittest.TestCase):
    """RF-015-13, RF-016-17: lo que el contrafuerte sube fuera de su zona de coronación y llega al borde de la rejilla o a celdas sin dato
    de la partida, y lo que la rejilla recorta de su zona; el perfil ``SMALL`` (45°, bancos de 10 m, bermas de 10 m, ancla a 100 m) sobre
    un llano a 101,5 m con celdas de 2 m, la coronación a 110 m (el talud general baja 1 m por celda)."""

    def outcome(self, scene: Any, crown: float = 110.0, **options: Any) -> tuple[Any, Any]:
        job = bdata.job_of(scene, crown, **options)
        return job, buttress.compute_buttress(job)

    def test_a_foot_that_reaches_the_grid_border_says_so(self) -> None:
        """La zona a 4 m del borde oeste (columnas 2 a 7): el pie llega a la columna 0 de la rejilla. El aviso lleva las celdas del
        pie (**fuera de la zona**) que están en el borde, su área y el lugar de la primera, contra el bucle de Python (p9 del
        verificador C: antes, ningún aviso)."""
        scene = bdata.plane_scene(box=(20, 26, 2, 8))
        job, outcome = self.outcome(scene)
        wanted = hand_outside(scene.start, outcome.footprint, scene.zone)
        self.assertGreater(len(wanted), 4)
        self.assertEqual({col for _row, col in wanted} & {0}, {0}, "llega a la columna 0")
        self.assertEqual(int(outcome.outside.sum()), len(wanted))
        np.testing.assert_array_equal(np.argwhere(outcome.outside), np.array(wanted))
        (notice,) = of(outcome.notices, OUTSIDE)
        self.assertEqual(notice.values["entity"], bdata.NAME)
        self.assertEqual((notice.values["cells"], notice.values["area"]), (len(wanted), len(wanted) * 4.0))
        self.assertEqual((notice.values["x"], notice.values["y"]), place(job.grid, wanted[0]))
        self.assertEqual(notice.severity, "warning")
        self.assertEqual([item.code for item in outcome.notices], [OUTSIDE])

    def test_the_cells_of_the_zone_itself_do_not_count(self) -> None:
        """Una zona pegada al borde oeste (columnas 0 a 5): sus celdas de la columna 0 son su huella y no cuentan; sí las del pie
        que están en la columna 0 por encima y por debajo de ella."""
        scene = bdata.plane_scene(box=(20, 26, 0, 6))
        _job, outcome = self.outcome(scene)
        wanted = hand_outside(scene.start, outcome.footprint, scene.zone)
        self.assertTrue(wanted)
        self.assertTrue(all(not scene.zone[cell] for cell in wanted))
        self.assertEqual(sorted(wanted), sorted(tuple(map(int, cell)) for cell in np.argwhere(outcome.outside)))
        self.assertTrue(any(col == 0 for _row, col in wanted))
        self.assertFalse(outcome.outside[20:26, 0].any(), "la columna 0 de la zona no cuenta")

    def test_a_foot_next_to_a_cell_without_data_says_so_with_its_place(self) -> None:
        """Una celda sin dato dos celdas al este de la zona (en el pie): el pie sube hasta ella; el aviso cuenta las celdas que suben
        junto a ella (las ocho vecinas) con el lugar de la primera, a mano."""
        scene = bdata.plane_scene()
        scene.start[22, 28] = np.nan
        job, outcome = self.outcome(scene)
        wanted = hand_outside(scene.start, outcome.footprint, scene.zone)
        self.assertTrue(wanted)
        self.assertFalse(any(row in (0, 43) or col in (0, 43) for row, col in wanted), "no llega al borde de la rejilla")
        (notice,) = of(outcome.notices, OUTSIDE)
        self.assertEqual(notice.values["cells"], len(wanted))
        self.assertEqual((notice.values["x"], notice.values["y"]), place(job.grid, wanted[0]))
        self.assertTrue(all(abs(row - 22) <= 1 and abs(col - 28) <= 1 for row, col in wanted))

    def test_in_the_middle_of_the_grid_it_says_nothing(self) -> None:
        """Un contrafuerte lejos del borde y sin celdas sin dato: ni aviso ni celdas que lleguen; sin geometría, no se mide lo recortado."""
        _job, outcome = self.outcome(bdata.plane_scene())
        self.assertFalse(outcome.outside.any())
        self.assertEqual(outcome.notices, ())
        self.assertIsNone(outcome.clipped)

    def test_a_no_data_cell_of_the_zone_is_not_a_reach(self) -> None:
        """Una celda sin dato **dentro de la zona** (la huella: RF-015-09, excepción de la 016) no hace avisar a los que suben a su
        lado como «llega a celdas sin dato fuera de su huella»: la avisa ella misma, con su aviso propio (T53, antes
        ``outcome.notices == ()``: ningún aviso)."""
        scene = bdata.plane_scene()
        scene.start[21, 21] = np.nan
        _job, outcome = self.outcome(scene)
        self.assertEqual([item.code for item in outcome.notices], [BUTTRESS_NO_DATA])
        self.assertEqual(of(outcome.notices, OUTSIDE), [])

    def test_a_window_gives_the_same_as_the_whole_grid(self) -> None:
        """La ventana de trabajo (A0) da lo mismo que la rejilla entera: la misma máscara en su sitio y el mismo aviso, con el pie en el
        borde de la rejilla (la ventana llega a él) y con una celda sin dato (A0 solo lee lo que alcanza la envolvente)."""
        scene = bdata.plane_scene(box=(20, 26, 2, 8))
        scene.start[30, 14] = np.nan
        _job, whole = self.outcome(scene)
        reach = buttress.buttress_reach_m(scene.profile, 110.0, float(np.nanmin(scene.start)), None, "exact")
        region = buttress.buttress_window(scene.zone, scene.grid, reach)
        found = buttress.compute_buttress(bdata.job_of(scene, 110.0, region=region, lowest_m=float(np.nanmin(scene.start))))
        self.assertEqual(region[1].start, 0, "la ventana llega al borde oeste")
        placed = np.zeros(scene.start.shape, dtype=bool)
        placed[region] = found.outside
        np.testing.assert_array_equal(placed, whole.outside)
        self.assertEqual([(i.code, dict(i.values)) for i in found.notices], [(i.code, dict(i.values)) for i in whole.notices])

    def test_the_zone_cut_by_the_grid_is_measured_and_warned(self) -> None:
        """Con la geometría de la zona (``parts``): una zona que sale por el oeste y el norte da ``des.buttress_footprint_clipped`` con
        las celdas de fuera y su lugar, **contra la fuerza bruta** (rejilla mayor), y va antes que el aviso del borde."""
        grid = bdata.plane_scene().grid
        ring = np.array([[grid.west - 6.0, grid.north + 4.0], [grid.west + 14.0, grid.north + 4.0], [grid.west + 14.0, grid.north - 14.0],
                         [grid.west - 6.0, grid.north - 14.0]])
        parts = ((ring,),)
        scene = bdata.plane_scene()
        scene = dataclasses.replace(scene, zone=zones.polygons_cells(parts, grid))
        job = with_parts(bdata.job_of(scene, 110.0), parts)
        outcome = buttress.compute_buttress(job)
        wanted = hand_clipped(parts, grid)
        self.assertEqual(outcome.clipped, wanted)
        self.assertEqual([item.code for item in outcome.notices][:2], [BUTTRESS_CLIPPED, OUTSIDE])
        notice = outcome.notices[0]
        cells, x, y = wanted  # type: ignore[misc]
        self.assertEqual(dict(notice.values), {"entity": bdata.NAME, "cells": cells, "area": cells * 4.0, "x": round(x, 2), "y": round(y, 2)})
        self.assertGreater(cells, 10)

    def test_a_zone_inside_the_grid_has_no_clipped_notice(self) -> None:
        """Con la geometría dentro de la rejilla (lo normal): ``clipped`` es ``None`` y ningún aviso de recorte."""
        scene = bdata.plane_scene()
        grid = scene.grid
        ring = np.array([[grid.west + 36.0, grid.north - 36.0], [grid.west + 52.0, grid.north - 36.0], [grid.west + 52.0, grid.north - 52.0],
                         [grid.west + 36.0, grid.north - 52.0]])
        outcome = buttress.compute_buttress(with_parts(bdata.job_of(scene, 110.0), ((ring,),)))
        self.assertIsNone(outcome.clipped)
        self.assertEqual(of(outcome.notices, BUTTRESS_CLIPPED), [])

    def test_the_foot_cut_notice_goes_after_them_and_nothing_else_changes(self) -> None:
        """El aviso del pie cortado (T28) sigue donde estaba, detrás de los nuevos; las cifras, la superficie y el pie cortado son los de
        antes de medir lo nuevo (el aviso de más no cambia ningún valor)."""
        scene = bdata.strip_scene()
        scene.allowed[40:, :] = False
        job = bdata.job_of(scene, 120.0)
        outcome = buttress.compute_buttress(job)
        found = buttress.measure_cutoff(job, outcome, PROJECT)
        self.assertEqual([item.code for item in found.notices], [OUTSIDE, FOOT_CUT])
        np.testing.assert_array_equal(found.surface, outcome.surface)
        self.assertEqual((found.volume_m3, found.area_m2, found.height_max_m), (outcome.volume_m3, outcome.area_m2, outcome.height_max_m))
        self.assertGreater(found.cutoff_m2, 0.0)
        np.testing.assert_array_equal(found.outside, outcome.outside)

    def test_the_figures_do_not_include_the_new_notices(self) -> None:
        """Las cifras CALCULADO del contrafuerte (volumen, área y altura máxima) son las mismas con y sin geometría de la zona: lo nuevo
        solo son avisos."""
        scene = bdata.plane_scene(box=(20, 26, 2, 8))
        grid = scene.grid
        ring = np.array([[grid.west + 4.0, grid.north - 40.0], [grid.west + 16.0, grid.north - 40.0], [grid.west + 16.0, grid.north - 52.0],
                         [grid.west + 4.0, grid.north - 52.0]])
        plain = buttress.compute_buttress(bdata.job_of(scene, 110.0))
        parted = buttress.compute_buttress(with_parts(bdata.job_of(scene, 110.0), ((ring,),)))
        self.assertEqual([(figure.key, figure.value) for figure in plain.figures], [(figure.key, figure.value) for figure in parted.figures])
        np.testing.assert_array_equal(plain.surface, parted.surface)


# --- Las celdas sin dato de la huella: el contrafuerte las tolera y las avisa (T53) ----------------------------------------------


class ButtressNoDataTest(unittest.TestCase):
    """RF-015-13, RF-015-09 (excepción de la 016, spec 0.4), RF-016-17, RF-016-18; T53, decisión 8 de «Para Samuel» (20/11/2026): las celdas
    de la **zona de coronación** sin dato en la partida no siembran ni suben (se dejan como están y no cuentan en el volumen: ninguna cifra
    cambia) y el contrafuerte **avisa con su lugar** (``des.buttress_no_data``: cuántas, su área y la primera), sin impedir crear. Lo que
    sube junto a una celda sin dato **fuera de la zona** lo avisa ``des.entity_edge_outside`` (T46), no este. Una zona **entera** sin dato
    sigue rechazándose (``des.buttress_zone_no_data``: no hay contrafuerte). La zona de la escena llana: filas y columnas 18 a 25."""

    HOLES = ((21, 21), (21, 22), (24, 19))
    """Tres celdas de la zona sin dato; la primera de norte a sur y de oeste a este es la (21, 21)."""

    def holed(self) -> Any:
        scene = bdata.plane_scene()
        for cell in self.HOLES:
            scene.start[cell] = np.nan
        return scene

    def outcome(self, scene: Any, crown: float = 110.0, **options: Any) -> tuple[Any, Any]:
        job = bdata.job_of(scene, crown, **options)
        return job, buttress.compute_buttress(job)

    def test_the_cells_without_data_of_the_zone_are_told_with_their_number_their_area_and_their_place(self) -> None:
        """Tres celdas de la zona sin dato dan **un** aviso en ámbar con las celdas (3), su área (12 m²) y el centro de la primera, la
        (21, 21), a mano desde la rejilla; en español y en inglés, con el contrafuerte, lo que se hace con ellas (se dejan como están y no
        siembran ni cuentan en el volumen) y sin ningún marcador sin llenar."""
        scene = self.holed()
        job, outcome = self.outcome(scene)
        (notice,) = of(outcome.notices, BUTTRESS_NO_DATA)
        self.assertEqual(notice.severity, "warning")
        x, y = place(job.grid, (21, 21))
        self.assertEqual(dict(notice.values), {"entity": bdata.NAME, "cells": 3, "area": 12.0, "x": round(x, 2), "y": round(y, 2)})
        spanish, english = notice.text("es"), notice.text("en")
        for words in (f"«{bdata.NAME}»", "3 celdas (12 m²)", "zona de coronación", "se dejan como están", "no cuentan en el volumen"):
            self.assertIn(words, spanish)
        for words in (f"«{bdata.NAME}»", "3 cells (12 m²)", "crown zone", "left as they are", "do not count in the volume"):
            self.assertIn(words, english)
        self.assertNotIn("{", spanish + english)
        self.assertNotIn("?", spanish + english)

    def test_one_cell_is_told_in_the_singular(self) -> None:
        """Con una sola celda sin dato el texto dice «1 celda» (no «1 celdas»), en los dos idiomas."""
        scene = bdata.plane_scene()
        scene.start[22, 22] = np.nan
        _job, outcome = self.outcome(scene)
        (notice,) = of(outcome.notices, BUTTRESS_NO_DATA)
        self.assertEqual((notice.values["cells"], notice.values["area"]), (1, 4.0))
        self.assertIn("1 celda (4 m²)", notice.text("es"))
        self.assertIn("se deja como está", notice.text("es"))
        self.assertIn("1 cell (4 m²)", notice.text("en"))
        self.assertNotIn("1 celdas", notice.text("es"))
        self.assertNotIn("1 cells", notice.text("en"))

    def test_nothing_else_changes_the_cells_do_not_seed_and_the_figures_are_the_independent_calculation(self) -> None:
        """RF-016-17: lo que cambia es solo el aviso. Las tres celdas sin dato no siembran (las semillas son las 64 de la zona menos 3),
        siguen sin dato en la superficie y la superficie, las cifras y el pie son los del cálculo independiente (``hand_buttress``) a ≤ 10⁻⁹:
        el volumen no cambia por avisarlo."""
        scene = self.holed()
        _job, outcome = self.outcome(scene)
        hand = bdata.hand_of(scene, 110.0)
        self.assertEqual(int(outcome.seeds.sum()), 64 - 3)
        for cell in self.HOLES:
            self.assertTrue(np.isnan(outcome.surface[cell]), cell)
        np.testing.assert_allclose(outcome.surface, hand.surface, rtol=0.0, atol=1e-9)
        self.assertAlmostEqual(outcome.volume_m3, hand.volume_m3, delta=1e-9 * max(hand.volume_m3, 1.0))
        self.assertAlmostEqual(outcome.area_m2, hand.area_m2, delta=1e-9 * max(hand.area_m2, 1.0))
        self.assertAlmostEqual(outcome.height_max_m, hand.height_max_m, delta=1e-9)
        clean = buttress.compute_buttress(bdata.job_of(bdata.plane_scene(), 110.0))
        self.assertEqual([item.code for item in clean.notices], [], "sin celdas sin dato, ningún aviso")

    def test_a_no_data_cell_outside_the_zone_is_not_one_of_the_zone(self) -> None:
        """Una celda sin dato **fuera de la zona**, dos celdas al este (en el pie) lo avisa ``des.entity_edge_outside`` y no este aviso:
        el de la zona cuenta solo lo de la zona."""
        scene = bdata.plane_scene()
        scene.start[22, 28] = np.nan
        _job, outcome = self.outcome(scene)
        self.assertEqual(of(outcome.notices, BUTTRESS_NO_DATA), [])
        self.assertEqual(len(of(outcome.notices, OUTSIDE)), 1)

    def test_the_order_of_the_notices_is_the_clipped_zone_the_cells_without_data_and_the_edge(self) -> None:
        """La zona que sale por el oeste y el norte (``des.buttress_footprint_clipped``), con una celda sin dato dentro y el pie en el
        borde de la rejilla (``des.entity_edge_outside``), da los tres avisos en ese orden: lo recortado, lo que no tiene dato y lo que
        llega al borde."""
        grid = bdata.plane_scene().grid
        ring = np.array([[grid.west - 6.0, grid.north + 4.0], [grid.west + 14.0, grid.north + 4.0], [grid.west + 14.0, grid.north - 14.0],
                         [grid.west - 6.0, grid.north - 14.0]])
        parts = ((ring,),)
        scene = bdata.plane_scene()
        scene = dataclasses.replace(scene, zone=zones.polygons_cells(parts, grid))
        scene.start[3, 3] = np.nan
        self.assertTrue(scene.zone[3, 3])
        outcome = buttress.compute_buttress(with_parts(bdata.job_of(scene, 110.0), parts))
        self.assertEqual([item.code for item in outcome.notices], [BUTTRESS_CLIPPED, BUTTRESS_NO_DATA, OUTSIDE])
        self.assertEqual(dict(outcome.notices[1].values)["cells"], 1)

    def test_a_window_gives_the_same_notice_as_the_whole_grid(self) -> None:
        """La ventana de trabajo (A0) da el mismo aviso —las mismas celdas y el mismo lugar, con el desplazamiento de la ventana— que la
        rejilla entera: la zona en el centro de la rejilla con un alcance de 10 m, que deja una ventana más pequeña que ella."""
        scene = self.holed()
        lowest = float(np.nanmin(scene.start))
        _job, whole = self.outcome(scene, reach=10.0)
        reach = buttress.buttress_reach_m(scene.profile, 110.0, lowest, 10.0, "exact")
        region = buttress.buttress_window(scene.zone, scene.grid, reach)
        self.assertGreater(region[0].start, 0, "la ventana no es la rejilla entera")
        self.assertGreater(region[1].start, 0)
        found = buttress.compute_buttress(bdata.job_of(scene, 110.0, reach=10.0, region=region, lowest_m=lowest))
        self.assertEqual([(i.code, dict(i.values)) for i in found.notices], [(i.code, dict(i.values)) for i in whole.notices])
        self.assertEqual(len(of(found.notices, BUTTRESS_NO_DATA)), 1)

    def test_a_zone_wholly_without_data_is_still_refused(self) -> None:
        """RF-016-18: una zona **entera** sin dato sigue rechazándose (``des.buttress_zone_no_data``): no hay contrafuerte que crear,
        como antes de T53; con **una sola celda con dato** ya se calcula y avisa del resto (63 celdas)."""
        scene = bdata.plane_scene()
        scene.start[scene.zone] = np.nan
        with self.assertRaises(messages.DesignError) as caught:
            buttress.compute_buttress(bdata.job_of(scene, 110.0))
        self.assertEqual(caught.exception.code, "des.buttress_zone_no_data")
        scene.start[21, 21] = 101.5
        _job, outcome = self.outcome(scene)
        self.assertEqual(int(outcome.seeds.sum()), 1)
        (notice,) = of(outcome.notices, BUTTRESS_NO_DATA)
        self.assertEqual(notice.values["cells"], 63)

    def test_the_notice_goes_to_the_report(self) -> None:
        """RF-015-13, RF-015-02: el informe (``des_prp_``) lleva el aviso al final con su código y sus valores (lo que repite la
        reproducción: es del resultado); sin celdas sin dato, el informe no lleva ningún aviso."""
        outcome = self.outcome(self.holed())[1]
        rows = supported_store.buttress_report_rows(outcome)
        warned = [row for row in rows if row[0] == "warning"]
        self.assertEqual(len(warned), 1)
        self.assertEqual(rows[-1], warned[0])
        self.assertEqual(json.loads(warned[0][3]), {"code": BUTTRESS_NO_DATA, "values": dict(outcome.notices[0].values)})
        clean = buttress.compute_buttress(bdata.job_of(bdata.plane_scene(), 110.0))
        self.assertEqual([row for row in supported_store.buttress_report_rows(clean) if row[0] == "warning"], [])


class NoDataNoticeTest(unittest.TestCase):
    """RF-015-13 (T53): ``supported_edge.no_data_notice``, el aviso común de las celdas sin dato de la huella: cuántas, su área y el centro
    de la primera (de norte a sur y de oeste a este) en coordenadas absolutas, también con una ventana de trabajo."""

    GRID = gis.Grid(725000.0, 4400100.0, 2.0, 2.0, 30, 40)

    def test_it_counts_the_cells_the_area_and_the_first_with_the_window_offset(self) -> None:
        """Con la ventana que empieza en la fila 5 y la columna 8 de la rejilla, dos celdas sin dato dan 2 celdas, 8 m² y el lugar de la
        primera, a mano; los valores de quien lo pide se conservan."""
        missing = np.zeros((10, 12), dtype=bool)
        missing[4, 7] = missing[2, 9] = True
        window = (slice(5, 15), slice(8, 20))
        notice = supported_edge.no_data_notice("des.removal_no_data", {"stockpile": "Acopio 1"}, missing, self.GRID, window)
        assert notice is not None
        x, y = self.GRID.west + (9 + 8 + 0.5) * 2.0, self.GRID.north - (2 + 5 + 0.5) * 2.0
        self.assertEqual((notice.code, dict(notice.values)),
                         ("des.removal_no_data", {"stockpile": "Acopio 1", "cells": 2, "area": 8.0, "x": x, "y": y}))

    def test_nothing_missing_is_no_notice(self) -> None:
        """Sin ninguna celda sin dato no hay aviso."""
        self.assertIsNone(supported_edge.no_data_notice("des.buttress_no_data", {"entity": "B1"}, np.zeros((6, 6), dtype=bool),
                                                        self.GRID, (slice(0, 6), slice(0, 6))))


# --- El cuerpo ---------------------------------------------------------------------------------------------------------------------


class BodyEdgeTest(unittest.TestCase):
    """RF-015-13, RF-016-20: lo que el cuerpo «sobre una base» sube y llega al borde de la rejilla o a celdas sin dato de la partida fuera de
    su huella, y lo que la rejilla recorta de su huella; «bajo un techo» no cambia la superficie."""

    def body(self, footprint: np.ndarray, **options: Any) -> tuple[Any, Any]:
        cells = np.argwhere(footprint)
        points = tt.points_of({(int(r), int(c)): 3.0 for r, c in cells[:: max(1, len(cells) // 6)]})
        job = tt.job_of(footprint, points=points, sense=options.pop("sense", "on_base"), **options)
        return job, thickness.compute_body(job)

    def test_a_body_on_the_grid_border_says_so(self) -> None:
        """Un cuerpo pegado al borde oeste (columnas 0 a 5, 3 m de espesor): las celdas que sube en la columna 0 no son «de fuera de la
        huella» pero sí lo que llega al borde: se avisa con su área y el lugar de la primera, a mano. Con el cuerpo pegado al borde, el
        resto de lo que sube (dentro de la huella, lejos del borde) no cuenta."""
        footprint = tt.box(8, 16, 0, 6)
        job, outcome = self.body(footprint)
        raised = outcome.surface > job.start
        wanted = hand_outside(job.start, raised, footprint, skip=False)
        self.assertTrue(wanted)
        self.assertTrue(all(col == 0 or row in (0, 23) or col == 23 for row, col in wanted))
        self.assertEqual(int(outcome.outside.sum()), len(wanted))
        (notice,) = of(outcome.notices, OUTSIDE)
        self.assertEqual((notice.values["cells"], notice.values["area"], notice.values["entity"]), (len(wanted), len(wanted) * 4.0, "Cuerpo A"))
        self.assertEqual((notice.values["x"], notice.values["y"]), place(job.grid, wanted[0]))

    def test_a_body_next_to_a_cell_without_data_outside_its_footprint(self) -> None:
        """Una celda sin dato en la partida, justo fuera de la huella: las celdas del cuerpo que la tocan (ocho vecinas) se avisan con el
        lugar de la primera; una celda sin dato **dentro** de la huella no (es ``des.body_unsupported``)."""
        footprint = tt.box(8, 16, 8, 16)
        start = np.full(tt.GRID.shape, 100.0)
        start[11, 16] = np.nan
        support = np.full(tt.GRID.shape, 100.0)
        points = tt.points_of({(10, 10): 3.0, (12, 12): 3.0, (14, 14): 3.0})
        job = tt.job_of(footprint, points=points, sense="on_base", support=support, start=start)
        outcome = thickness.compute_body(job)
        raised = outcome.surface > job.start
        wanted = hand_outside(job.start, raised, footprint, skip=False)
        self.assertEqual(sorted(wanted), [(10, 15), (11, 15), (12, 15)])
        (notice,) = of(outcome.notices, OUTSIDE)
        self.assertEqual((notice.values["cells"], (notice.values["x"], notice.values["y"])), (3, place(job.grid, (10, 15))))
        inside = start.copy()
        inside[11, 16] = 100.0
        inside[11, 12] = np.nan
        found = thickness.compute_body(tt.job_of(footprint, points=points, sense="on_base", support=support, start=inside))
        self.assertEqual(of(found.notices, OUTSIDE), [])
        self.assertEqual([item.code for item in found.notices if item.severity == "warning"], [])  # T46: el renglón del escalón es una nota

    def test_in_the_middle_of_the_grid_it_says_nothing(self) -> None:
        """Un cuerpo lejos del borde y de lo que no tiene dato: ni aviso ni geometría medida (sin ``parts``)."""
        _job, outcome = self.body(tt.box(8, 16, 8, 16))
        self.assertFalse(outcome.outside.any())
        self.assertEqual([item.code for item in outcome.notices if item.severity == "warning"], [])  # T46: el renglón del escalón es una nota
        self.assertIsNone(outcome.clipped)

    def test_under_a_roof_does_not_change_the_surface_and_has_no_edge(self) -> None:
        """«Bajo un techo» no cambia la superficie: sin ``outside`` ni aviso del borde, aunque esté pegado a él; lo recortado por la rejilla sí
        se mide (la huella es lo que es)."""
        footprint = tt.box(8, 16, 0, 6)
        _job, outcome = self.body(footprint, sense="under_roof")
        self.assertIsNone(outcome.outside)
        self.assertEqual(of(outcome.notices, OUTSIDE), [])

    def test_the_footprint_cut_by_the_grid_is_measured_and_warned(self) -> None:
        """Con la geometría de la huella (``parts``): una huella que sale por el oeste da ``des.body_footprint_clipped`` con las celdas de
        fuera y su lugar contra la fuerza bruta, en los dos sentidos, **sin impedir calcular**."""
        parts = ((tt.ring(8, 16, -4, 6),),)
        footprint = zones.polygons_cells(parts, tt.GRID)
        for sense in ("on_base", "under_roof"):
            with self.subTest(sense=sense):
                job, outcome = self.body(footprint, sense=sense)
                outcome = thickness.compute_body(with_parts(job, parts))
                wanted = hand_clipped(parts, tt.GRID)
                self.assertEqual(outcome.clipped, wanted)
                (notice,) = of(outcome.notices, BODY_CLIPPED)
                cells, x, y = wanted  # type: ignore[misc]
                self.assertEqual(dict(notice.values), {"entity": "Cuerpo A", "cells": cells, "area": cells * 4.0, "x": round(x, 2),
                                                       "y": round(y, 2)})
                self.assertEqual(cells, 8 * 4)
                self.assertGreater(outcome.volume_m3, 0.0)

    def test_the_figures_and_the_surface_are_the_same_with_the_geometry(self) -> None:
        """Lo nuevo solo son avisos: las cifras y la superficie son las mismas con y sin la geometría de la huella."""
        parts = ((tt.ring(8, 16, -4, 6),),)
        footprint = zones.polygons_cells(parts, tt.GRID)
        job, plain = self.body(footprint)
        parted = thickness.compute_body(with_parts(job, parts))
        self.assertEqual([(f.key, f.value) for f in plain.figures], [(f.key, f.value) for f in parted.figures])
        np.testing.assert_array_equal(plain.surface, parted.surface)

    def test_the_new_notices_keep_the_order_of_the_old_ones(self) -> None:
        """Los avisos de siempre (lo ignorado, lo lejano, lo que no tiene superficie conocida) siguen en su orden y los nuevos van
        detrás de ellos y delante de lo lento; el renglón informativo del escalón del borde (T46, una nota) cierra los del cálculo."""
        parts = ((tt.ring(8, 16, -4, 6),),)
        footprint = zones.polygons_cells(parts, tt.GRID)
        support = np.full(tt.GRID.shape, 100.0)
        support[10, 3] = np.nan
        points = tt.points_of({(10, 4): 3.0, (12, 4): 3.0, (14, 4): 3.0})
        job = tt.job_of(footprint, points=points, sense="on_base", support=support)
        found = thickness.compute_body(with_parts(job, parts))
        self.assertEqual([item.code for item in found.notices], ["des.body_unsupported", BODY_CLIPPED, OUTSIDE, EDGE_STEP])


# --- El orden con la otra superficie de la cantera --------------------------------------------------------------------------------


class QuarryOrderTest(unittest.TestCase):
    """RF-015-14 con los tipos de la 016: ``order_notices`` da el aviso de la plataforma (``des.entity_quarry_order``) con la otra superficie
    de la cantera y no más: sin cantera, sin superficie (el cuerpo «bajo un techo») o con el orden cumplido (1 mm), nada."""

    GRID = tt.GRID

    def quarry(self, side: str, other: np.ndarray) -> Any:
        return platform.QuarryOrder("Cantera A", side, "des_fin_cantera_a" if side == "final" else "des_exp_cantera_a",
                                    "des_exp_cantera_a" if side == "final" else "des_fin_cantera_a", other)

    def test_a_final_surface_raised_above_the_exploitation_warns(self) -> None:
        """La final subida por encima de la de explotación: el aviso lleva la cantera, las dos superficies, las celdas, el área, lo que
        más pasa (al mm) y el lugar de la primera, a mano; y es el mismo que da la plataforma (``order_check``)."""
        window = (slice(4, 12), slice(6, 14))
        result = np.full((8, 8), 100.0)
        result[2:5, 3:6] = 103.0
        other = np.full(self.GRID.shape, 101.0)
        found = supported_store.order_notices("Muro", result, window, self.GRID, self.quarry("final", other))
        (notice,) = found
        self.assertEqual(notice.code, ORDER)
        self.assertEqual((notice.values["cells"], notice.values["area"], notice.values["above"]), (9, 36.0, 2.0))
        self.assertEqual((notice.values["entity"], notice.values["quarry"], notice.values["surface"], notice.values["other"]),
                         ("Muro", "Cantera A", "des_fin_cantera_a", "des_exp_cantera_a"))
        self.assertEqual((notice.values["x"], notice.values["y"]), place(self.GRID, (4 + 2, 6 + 3)))
        breach = platform.order_check(result, other, "final", self.GRID, window)
        self.assertEqual(notice.values, supported_edge.order_notice("Muro", self.quarry("final", other), breach).values)

    def test_the_exploitation_surface_lowered_below_the_final_warns_and_raised_does_not(self) -> None:
        """Del lado de la explotación el orden es ``final ≤ explotación``: bajarla por debajo de la final avisa y subirla no."""
        window = (slice(0, 8), slice(0, 8))
        other = np.full(self.GRID.shape, 100.0)
        lowered = np.full((8, 8), 99.0)
        raised = np.full((8, 8), 130.0)
        self.assertEqual(len(supported_store.order_notices("R", lowered, window, self.GRID, self.quarry("exploitation", other))), 1)
        self.assertEqual(supported_store.order_notices("C", raised, window, self.GRID, self.quarry("exploitation", other)), ())

    def test_the_tolerance_is_one_millimetre(self) -> None:
        """Hasta 1 mm de más (el de RF-014-14: 0,9 mm cumple) no avisa; con 1,1 mm, sí; una celda sin dato en una de las dos no se compara."""
        window = (slice(0, 4), slice(0, 4))
        other = np.full(self.GRID.shape, 100.0)
        quarry = self.quarry("final", other)
        self.assertEqual(supported_store.order_notices("E", np.full((4, 4), 100.0009), window, self.GRID, quarry), ())
        self.assertEqual(len(supported_store.order_notices("E", np.full((4, 4), 100.0011), window, self.GRID, quarry)), 1)
        self.assertEqual(supported_store.order_notices("E", np.full((4, 4), np.nan), window, self.GRID, quarry), ())

    def test_without_a_quarry_or_a_surface_there_is_nothing_to_compare(self) -> None:
        """Sin cantera (parte del terreno, de otro diseño o de una entidad) o sin superficie (el cuerpo «bajo un techo»): ninguno."""
        window = (slice(0, 4), slice(0, 4))
        high = np.full((4, 4), 500.0)
        self.assertEqual(supported_store.order_notices("E", high, window, self.GRID, None), ())
        self.assertEqual(supported_store.order_notices("E", None, window, self.GRID,
                                                       self.quarry("final", np.full(self.GRID.shape, 100.0))), ())

    def test_the_notice_text_names_the_entity_and_both_surfaces(self) -> None:
        """El texto, en los dos idiomas, nombra la entidad, la superficie que cambia y la otra, con el orden roto."""
        result = np.full((4, 4), 102.0)
        (notice,) = supported_store.order_notices("Muro", result, (slice(0, 4), slice(0, 4)), self.GRID,
                                                  self.quarry("final", np.full(self.GRID.shape, 100.0)))
        for language, words in (("es", ("Muro", "des_fin_cantera_a", "des_exp_cantera_a", "final ≤ explotación")),
                                ("en", ("Muro", "des_fin_cantera_a", "des_exp_cantera_a", "final ≤ exploitation"))):
            for word in words:
                self.assertIn(word, notice.text(language))
        self.assertTrue(messages.MESSAGES[ORDER].severity == "warning")


if __name__ == "__main__":
    unittest.main()
