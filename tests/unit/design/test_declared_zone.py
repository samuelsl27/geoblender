# SPDX-License-Identifier: GPL-3.0-or-later
"""La zona que declara una entidad: el contorno de su huella (spec 015, T16; HU-015-1; RF-015-10,
RF-012-29; plan 015 §5.4 A8; D-23).

``design.entities.declared_zone`` da, de las celdas de la huella de una entidad, el polígono que
la restricción declarada lleva como geometría: **un polígono por componente 4-conexa**, con sus
huecos, **válido** para las comprobaciones de la 012 (``gis.masks.combine``: un polígono que se
toca a sí mismo —un hueco que roza el contorno por una esquina— es «no válido» allí, así que lo
que toca por una esquina va en **partes distintas**), con las coordenadas **exactas** de la
rejilla (``grid.west + columna·dx``, ``grid.north − fila·dy``: el principio 6) y de modo que la
regla de la celda de la 012 (RF-012-12; ``gis.masks.zones``) devuelva **exactamente** las celdas
de la huella con resguardo 0 (D-23) y, con resguardo, crezca como con cualquier otra restricción.
Es determinista: la misma huella da los mismos bits.
"""

from __future__ import annotations

import math
import unittest
from datetime import date

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
combine = import_geoblender("gis.masks.combine")
zones = import_geoblender("gis.masks.zones")
polygons = import_geoblender("gis.polygons")
coverage = import_geoblender("gis.coverage")
model = import_geoblender("core.constraints.model")

# Una rejilla de 40 × 40 celdas de 2 m en un UTM (los nortes de 4,4 Mm: el ruido de float64).
GRID = gis.Grid(699_680.0, 4_399_920.0, 2.0, 2.0, 40, 40)
OFFSET = (3, 5)
"""La fila y la columna de la celda ``[0, 0]`` de las máscaras de estas pruebas."""


def art(text: str) -> np.ndarray:
    """La máscara de un dibujo (``#`` es una celda de la huella, ``.`` no)."""
    rows = [line.strip() for line in text.strip().splitlines()]
    return np.array([[char == "#" for char in row] for row in rows], dtype=bool)


def vertex(row: int, col: int, grid=GRID) -> tuple[float, float]:
    """La esquina de celda (línea ``row``, línea ``col``) con las coordenadas exactas de ``grid``."""
    return (grid.west + col * grid.dx, grid.north - row * grid.dy)


def ring_of(*corners: tuple[int, int], offset=OFFSET) -> np.ndarray:
    """El anillo cerrado de las esquinas ``(fila, columna)`` (relativas a ``offset``)."""
    points = [vertex(offset[0] + row, offset[1] + col) for row, col in corners]
    return np.array([*points, points[0]], dtype=np.float64)


def zone_of(mask: np.ndarray, guard_m: float = 0.0, *, offset=OFFSET, grid=GRID):
    return entities.declared_zone(mask, grid, guard_m, offset=offset)


def constraint_of(zone, *, ctype=model.ConstraintType.NO_FILL) -> object:
    """La zona como una restricción de la 012 (para sus comprobaciones y su regla de la celda)."""
    return model.Constraint(
        uid="a" * 32, code="DEC-PLT-001", name="P1", ctype=ctype, kind=model.GeometryKind.POLYGON,
        parts=zone.parts, priority=0, reason="declarada por la plataforma P1", decided_by="Samuel",
        decided_on=date(2026, 11, 14), decision_uid=None, intention_uid=None, source_input=None,
        source_fid=None, layer="des_decl_v01", fid=1)


def problems_of(zone) -> tuple[str, ...]:
    """Lo que dice de su geometría la comprobación de la 012 (``combine._geometry_problems_steps``)."""
    return polygons.drain(combine._geometry_problems_steps(constraint_of(zone)))


def cells_of(zone, guard_m: float = 0.0, grid=GRID) -> np.ndarray:
    """Las celdas que da la regla de la celda de la 012 a la zona con su resguardo."""
    return zones.zone_runs(constraint_of(zone), grid, guard_m).mask(grid.shape)


def placed(mask: np.ndarray, offset=OFFSET, grid=GRID) -> np.ndarray:
    """``mask`` puesta en la rejilla entera, en ``offset``."""
    found = np.zeros(grid.shape, dtype=bool)
    found[offset[0]:offset[0] + mask.shape[0], offset[1]:offset[1] + mask.shape[1]] = mask
    return found


def area(ring: np.ndarray) -> float:
    return float(coverage.signed_area(ring[:-1]))


class ContourTest(unittest.TestCase):
    """RF-012-29, RF-015-10, A8: el contorno de cada componente, con sus huecos."""

    def test_rectangle_is_one_ring_with_exact_coordinates(self) -> None:
        """RF-012-29 (A8): una huella rectangular es un polígono de un anillo cerrado, exterior en
        sentido antihorario desde su esquina noroeste, con las coordenadas exactas de la rejilla."""
        zone = zone_of(art("""
            ####
            ####
            ####
        """))
        self.assertEqual(len(zone.parts), 1)
        (ring,) = zone.parts[0]
        expected = ring_of((0, 0), (3, 0), (3, 4), (0, 4))
        self.assertEqual(ring.dtype, np.float64)
        self.assertEqual(ring.tobytes(), expected.tobytes())
        self.assertGreater(area(ring), 0.0)  # antihorario
        self.assertEqual(zone.cells, 12)
        self.assertEqual(zone.area_m2, 48.0)
        self.assertEqual(area(ring), 48.0)
        self.assertEqual((zone.components, zone.split), (1, 0))
        self.assertFalse(ring.flags.writeable)
        self.assertEqual(problems_of(zone), ())

    def test_l_shape_has_the_six_corners(self) -> None:
        """RF-012-29 (A8): una L son seis esquinas, sin vértices de más en los lados rectos."""
        zone = zone_of(art("""
            #..
            #..
            ###
        """))
        (ring,) = zone.parts[0]
        self.assertEqual(ring.tobytes(),
                         ring_of((0, 0), (3, 0), (3, 3), (2, 3), (2, 1), (0, 1)).tobytes())
        self.assertEqual(problems_of(zone), ())
        self.assertEqual(int(cells_of(zone).sum()), 5)

    def test_hole_is_a_clockwise_ring_of_its_polygon(self) -> None:
        """RF-012-29 (A8): una huella con un hueco es **un** polígono con dos anillos: el exterior
        antihorario y el hueco horario, con la comprobación de la 012 limpia (``hole_outside``)."""
        zone = zone_of(art("""
            ###
            #.#
            ###
        """))
        self.assertEqual(len(zone.parts), 1)
        shell, hole = zone.parts[0]
        self.assertEqual(shell.tobytes(), ring_of((0, 0), (3, 0), (3, 3), (0, 3)).tobytes())
        self.assertEqual(hole.tobytes(), ring_of((1, 1), (1, 2), (2, 2), (2, 1)).tobytes())
        self.assertGreater(area(shell), 0.0)
        self.assertLess(area(hole), 0.0)
        self.assertEqual(area(shell) + area(hole), 32.0)  # 8 celdas de 4 m²
        self.assertEqual(zone.cells, 8)
        self.assertEqual(problems_of(zone), ())
        found = cells_of(zone)
        self.assertEqual(int(found.sum()), 8)  # el hueco no es de la huella
        self.assertFalse(found[OFFSET[0] + 1, OFFSET[1] + 1])

    def test_corner_touching_cells_are_different_parts(self) -> None:
        """RF-012-29 (A8): dos celdas que solo se tocan por una esquina no son 4-conexas: son dos
        partes, que se tocan en un vértice sin que la 012 vea un cruce ni un solape."""
        zone = zone_of(art("""
            #.
            .#
        """))
        self.assertEqual(len(zone.parts), 2)
        self.assertEqual(zone.components, 2)
        self.assertEqual(zone.parts[0][0].tobytes(),
                         ring_of((0, 0), (1, 0), (1, 1), (0, 1)).tobytes())
        self.assertEqual(zone.parts[1][0].tobytes(),
                         ring_of((1, 1), (2, 1), (2, 2), (1, 2)).tobytes())
        self.assertEqual(problems_of(zone), ())
        self.assertEqual(int(cells_of(zone).sum()), 2)

    def test_island_inside_a_hole_is_its_own_part(self) -> None:
        """RF-012-29 (A8): una isla dentro del hueco de otra componente es una parte más (ni cruza
        ni se solapa con el polígono que la rodea)."""
        zone = zone_of(art("""
            #####
            #...#
            #.#.#
            #...#
            #####
        """))
        self.assertEqual(len(zone.parts), 2)
        self.assertEqual([len(part) for part in zone.parts], [2, 1])
        self.assertEqual(problems_of(zone), ())
        self.assertEqual(int(cells_of(zone).sum()), 17)

    def test_hole_touching_the_outside_by_a_corner_is_split_in_rectangles(self) -> None:
        """RF-012-29 (A8; D-23): un anillo de celdas cuyo hueco toca el exterior por una esquina
        (las dos celdas de esa esquina están en la misma componente, unidas por el resto del
        anillo) no cabe en **un** polígono válido para la 012 (se tocaría a sí mismo): la
        componente se parte en rectángulos que se tocan, sin perder ni ganar ninguna celda."""
        mask = art("""
            ###.
            #.#.
            ##..
        """)
        zone = zone_of(mask)
        self.assertEqual((zone.components, zone.split), (1, 1))
        self.assertGreater(len(zone.parts), 1)
        self.assertTrue(all(len(part) == 1 and len(part[0]) == 5 for part in zone.parts))
        self.assertEqual(problems_of(zone), ())
        self.assertTrue(np.array_equal(cells_of(zone), placed(mask)))
        self.assertEqual(math.fsum(area(part[0]) for part in zone.parts), 7 * 4.0)

    def test_every_vertex_is_a_cell_corner_of_the_grid(self) -> None:
        """Principio 6: ninguna coordenada se calcula con aritmética de más: cada vértice es
        ``west + columna·dx`` y ``north − fila·dy`` **bit a bit** (también con otro paso)."""
        for grid in (GRID, gis.Grid(699_680.5, 4_399_920.5, 0.5, 1.5, 200, 90)):
            mask = art("""
                ##.#
                #.##
                ####
            """)
            zone = zone_of(mask, grid=grid)
            cols = {grid.west + col * grid.dx for col in range(grid.ncols + 1)}
            rows = {grid.north - row * grid.dy for row in range(grid.nrows + 1)}
            for part in zone.parts:
                for ring in part:
                    self.assertTrue(all(x in cols and y in rows for x, y in ring))
            self.assertEqual(zone.area_m2, int(mask.sum()) * grid.cell_area)

    def test_the_checks_of_the_012_find_no_geometry_problem(self) -> None:
        """RF-012-04, RF-012-29: pasada por ``combine.check_steps`` (la comprobación que hace la 012
        antes de compilar: esquinas que se tocan, ``self_intersecting``; huecos, ``hole_outside``;
        partes, ``overlap``; ``no_area``), ninguna geometría de las formas de esta prueba da un
        problema de geometría."""
        shapes = ("""
            ####
            #..#
            #..#
            ####
        """, """
            #.#
            .#.
            #.#
        """, """
            ##.
            #.#
            .##
        """, """
            ###.
            #.#.
            ##..
        """)
        for number, text in enumerate(shapes):
            with self.subTest(shape=number):
                found = polygons.drain(combine.check_steps([constraint_of(zone_of(art(text)))], {}))
                self.assertEqual([item.problem for item in found if item.field == "geometry"], [])

    def test_orientation_and_closure_of_every_ring(self) -> None:
        """RF-012-29: cada anillo está cerrado (el último punto es el primero), el exterior es
        antihorario y los huecos son horarios."""
        mask = art("""
            ######
            #....#
            #.##.#
            #.##.#
            #....#
            ######
        """)
        zone = zone_of(mask)
        for part in zone.parts:
            for index, ring in enumerate(part):
                self.assertTrue(np.array_equal(ring[0], ring[-1]))
                self.assertEqual(area(ring) > 0.0, index == 0)


class CellRuleTest(unittest.TestCase):
    """D-23, RF-012-12: la regla de la celda de la 012 sobre el contorno."""

    MASK = art("""
        ..###..
        .#####.
        ###.###
        ..###..
        .#...#.
    """)

    def brute_zone(self, mask: np.ndarray, guard_m: float, grid=GRID) -> np.ndarray:
        """Las celdas de la rejilla con alguna parte de su área a menos de ``guard_m − τ`` de alguna
        celda de la huella (la distancia entre rectángulos de celda, a mano)."""
        tau = zones.distance_tau(grid)
        found = np.zeros(grid.shape, dtype=bool)
        rows, cols = np.nonzero(mask)
        rr, cc = np.indices(grid.shape)
        for row, col in zip(rows, cols, strict=True):
            gap_x = np.maximum(np.abs(cc - col) - 1, 0) * grid.dx
            gap_y = np.maximum(np.abs(rr - row) - 1, 0) * grid.dy
            found |= np.hypot(gap_x, gap_y) < guard_m - tau
            found[row, col] = True
        return found

    def test_zero_guard_gives_exactly_the_footprint(self) -> None:
        """D-23, RF-012-29: con resguardo 0 la regla de la celda devuelve **exactamente** las celdas
        de la huella, ni una más (el anillo de una celda que daría un polígono dibujado) ni una
        menos."""
        mask = self.MASK
        zone = zone_of(mask)
        self.assertTrue(np.array_equal(cells_of(zone), placed(mask)))
        self.assertEqual(zone.cells, int(mask.sum()))
        self.assertEqual(problems_of(zone), ())

    def test_guard_grows_like_any_other_constraint(self) -> None:
        """D-23, RF-012-12: con resguardo (m), la zona crece como la de cualquier otra restricción:
        las celdas con alguna parte a menos del resguardo de la huella (comprobado con la distancia
        exacta entre celdas), incluidas las del hueco; y 0 m vuelve a la huella."""
        mask = placed(self.MASK)
        zone = zone_of(self.MASK, guard_m=4.0)
        self.assertEqual(zone.guard_m, 4.0)
        grown = cells_of(zone, 4.0)
        self.assertTrue(np.array_equal(grown, self.brute_zone(mask, 4.0)))
        self.assertGreater(int(grown.sum()), int(mask.sum()))
        self.assertTrue(grown[mask].all())
        for guard in (1.0, 2.0, 3.0, 5.0):
            with self.subTest(guard_m=guard):
                self.assertTrue(np.array_equal(cells_of(zone, guard),
                                               self.brute_zone(mask, guard)))
        self.assertTrue(np.array_equal(cells_of(zone, 0.0), mask))

    def test_guard_is_carried_not_applied(self) -> None:
        """RF-012-29: el contorno es el de las celdas aunque haya resguardo (lo amplía la
        compilación, como en cualquier restricción): la geometría no depende de ``guard_m``."""
        plain, guarded = zone_of(self.MASK), zone_of(self.MASK, guard_m=7.0)
        self.assertEqual(plain.sha256, guarded.sha256)
        self.assertEqual([[ring.tobytes() for ring in part] for part in plain.parts],
                         [[ring.tobytes() for ring in part] for part in guarded.parts])

    def test_random_footprints_are_valid_and_exact(self) -> None:
        """D-23, RF-012-29: sobre 60 huellas al azar (con huecos, esquinas que se tocan y
        componentes partidas), el contorno es válido para la 012, la regla de la celda devuelve
        exactamente las celdas de la huella y el área es la de sus celdas."""
        generator = np.random.default_rng(20261114)
        split = 0
        for index in range(60):
            density = 0.35 + 0.3 * generator.random()
            mask = generator.random((int(generator.integers(3, 13)),
                                     int(generator.integers(3, 13)))) < density
            if not mask.any():
                continue
            with self.subTest(index=index):
                zone = zone_of(mask)
                split += zone.split
                self.assertEqual(problems_of(zone), ())
                self.assertTrue(np.array_equal(cells_of(zone), placed(mask)))
                self.assertEqual(zone.cells, int(mask.sum()))
                self.assertEqual(math.fsum(area(ring) for part in zone.parts for ring in part),
                                 zone.area_m2)
        self.assertGreater(split, 0)  # el azar también cubre las componentes partidas


class DeterminismTest(unittest.TestCase):
    """RF-015-10 (A8): el mismo contorno y el mismo hash al repetirlo."""

    MASK = CellRuleTest.MASK

    def bits(self, zone) -> list[list[bytes]]:
        return [[ring.tobytes() for ring in part] for part in zone.parts]

    def test_same_footprint_same_bits_and_hash(self) -> None:
        """A8: repetir da los mismos bits, el mismo hash y los mismos números; la huella puesta en
        otra ventana (más grande, con otro origen) o en toda la rejilla da lo mismo."""
        first = zone_of(self.MASK)
        again = zone_of(self.MASK.copy())
        wide = entities.declared_zone(placed(self.MASK), GRID, 0.0)
        shifted = entities.declared_zone(
            np.pad(self.MASK, ((2, 3), (4, 1))), GRID, 0.0, offset=(OFFSET[0] - 2, OFFSET[1] - 4))
        for other in (again, wide, shifted):
            self.assertEqual(self.bits(other), self.bits(first))
            self.assertEqual(other.sha256, first.sha256)
            self.assertEqual((other.cells, other.area_m2, other.components),
                             (first.cells, first.area_m2, first.components))
        self.assertRegex(first.sha256, r"^[0-9a-f]{64}$")

    def test_hash_changes_with_the_footprint(self) -> None:
        """A8: otra huella, otro hash (también si solo se mueve una celda)."""
        other = self.MASK.copy()
        other[0, 2] = False
        self.assertNotEqual(zone_of(other).sha256, zone_of(self.MASK).sha256)
        self.assertNotEqual(entities.declared_zone(self.MASK, GRID, 0.0,
                                                   offset=(OFFSET[0], OFFSET[1] + 1)).sha256,
                            zone_of(self.MASK).sha256)

    def test_from_the_runs_of_des_epr(self) -> None:
        """RF-015-10 (T13): la zona sale de los tramos de fila que guarda ``des_epr_``
        (``footprint_runs``) igual que de la máscara, sin leer la rejilla entera."""
        mask = placed(self.MASK)
        window = (slice(OFFSET[0], OFFSET[0] + self.MASK.shape[0]),
                  slice(OFFSET[1], OFFSET[1] + self.MASK.shape[1]))
        runs = entity_store.footprint_runs(self.MASK, window)
        from_runs = entities.declared_zone_of_runs(runs, GRID, 4.0)
        reference = zone_of(self.MASK, guard_m=4.0)
        self.assertEqual(self.bits(from_runs), self.bits(reference))
        self.assertEqual((from_runs.sha256, from_runs.guard_m), (reference.sha256, 4.0))
        self.assertTrue(np.array_equal(cells_of(from_runs), mask))
        # Los tramos en otro orden dan lo mismo.
        self.assertEqual(self.bits(entities.declared_zone_of_runs(runs[::-1], GRID, 4.0)),
                         self.bits(reference))


class InputsTest(unittest.TestCase):
    """Los errores del programa: lo que no es una huella o un resguardo (la persona los ve antes,
    en ``check_entity_param``)."""

    def test_guard_must_be_a_finite_non_negative_number(self) -> None:
        """RF-015-10, D-19: el resguardo es un número finito ≥ 0 (un valor que no, error)."""
        mask = art("##")
        for guard in (-0.5, math.nan, math.inf, "4", None, True):
            with self.subTest(guard=guard), self.assertRaises((ValueError, TypeError)):
                entities.declared_zone(mask, GRID, guard, offset=OFFSET)

    def test_footprint_must_have_cells_and_fit_the_grid(self) -> None:
        """RF-015-10: una huella sin celdas, que no es una máscara de 2 dimensiones o que se sale
        de la rejilla es un error (una entidad sin huella no declara nada)."""
        with self.assertRaises(ValueError):
            entities.declared_zone(np.zeros((3, 3), dtype=bool), GRID, 0.0, offset=OFFSET)
        with self.assertRaises(ValueError):
            entities.declared_zone(np.ones(3, dtype=bool), GRID, 0.0)
        with self.assertRaises(ValueError):
            entities.declared_zone(np.ones((3, 3), dtype=bool), GRID, 0.0, offset=(38, 0))
        with self.assertRaises(ValueError):
            entities.declared_zone(np.ones((3, 3), dtype=bool), GRID, 0.0, offset=(0, -1))
        with self.assertRaises(ValueError):
            entities.declared_zone_of_runs([], GRID, 0.0)
        with self.assertRaises(ValueError):
            entities.declared_zone_of_runs([(0, 38, 41)], GRID, 0.0)

    def test_input_is_not_modified(self) -> None:
        """Una entrada no se modifica: la máscara sigue igual."""
        mask = art("""
            ##.
            #.#
        """)
        before = mask.copy()
        zone_of(mask)
        self.assertTrue(np.array_equal(mask, before))


class CoreConsistencyTest(unittest.TestCase):
    """El prefijo y el papel de la declarada son los mismos en ``design`` y en ``core``."""

    def test_prefix_and_role_agree_with_core(self) -> None:
        """RF-012-29, RF-015-10: ``design.model.DECLARED_PREFIX`` es el de ``core.constraints.declared``
        y el papel y el dato de ``design.provenance`` son los que ``core`` declara no editable."""
        declared = import_geoblender("core.constraints.declared")
        design_model = import_geoblender("design.model")
        provenance = import_geoblender("design.provenance")
        self.assertEqual(design_model.DECLARED_PREFIX, declared.DECLARED_PREFIX)
        self.assertEqual(provenance.DECLARED_ROLE, declared.DECLARED_ROLE)
        ours = declared.declared_dataset_spec("V01", crs_epsg=25830)
        theirs = provenance.dataset_spec("decl", "", "V01", crs_epsg=25830)
        for name in ("name", "module", "kind", "store", "locator", "reader", "role", "crs_epsg",
                     "qgis_editable"):
            self.assertEqual(getattr(ours, name), getattr(theirs, name), name)
        self.assertFalse(ours.qgis_editable)
        entity = "PLT-014"
        self.assertEqual(declared.declared_code(entity), f"{design_model.DECLARED_PREFIX}{entity}")


if __name__ == "__main__":
    unittest.main()
