# SPDX-License-Identifier: GPL-3.0-or-later
"""La columna de materiales y las unidades en el núcleo (spec 011, T09; HU-011-3; RF-011-11,
RF-011-12, RF-011-13, RF-011-14; plan 011 A7, §5.2.1, D-10, D-18, D-23, D-24 y D-39).

``reserves.materials`` guarda la **columna** del proyecto (D-12): unidades de arriba abajo, cada
una con un **código** inmutable (D-18), su nombre, su clase (natural, antrópica o compuesta), su
papel, su estado, su base (un dato del proyecto o una cota constante; la última, sin base: D-24)
y, si es antrópica, su rejilla de espesores (D-23); una compuesta, sus componentes. Sin densidad
ni K: son parámetros sin valor por defecto (familias de ``reserves.params``, D-8). La columna se
valida (``res.materials_invalid`` con la lista de problemas) y va y vuelve por su tabla
``res_materials``.

``reserves.kernel`` reparte el **desmonte** de cada celda entre las unidades (A7): de arriba
abajo, con ``techo = +∞``, cada unidad ocupa ``[min(base, techo), techo)``; **ausente** si su base
(o su espesor) no tiene dato o, en una antrópica, si su espesor no **pasa** del umbral de
presencia (su espesor pasa a la de abajo); si su base sube por encima del techo, **cruce**
(espesor 0). Por unidad, el volumen, el área ausente, la de sin dato y la de cruce; por dominio
y por rodaja con los mismos pesos. Las unidades suman el desmonte; el terraplén no se reparte.

Las referencias son cuentas a mano con números exactos en binario y, en la columna sintética
(``tests/support/res_fixtures.py``), los espesores de cada unidad celda a celda desde sus planos.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import unittest

import numpy as np

from tests.support import res_fixtures as fx
from tests.support.package import import_geoblender

materials = import_geoblender("reserves.materials")
surfaces = import_geoblender("reserves.surfaces")
kernel = import_geoblender("reserves.kernel")
messages = import_geoblender("reserves.messages")
slices_module = import_geoblender("reserves.slices")
polygons = import_geoblender("reserves.polygons")
gis = import_geoblender("gis")
store = import_geoblender("gis.store")

Grid = gis.Grid
Slices = slices_module.Slices
SurfaceRef = surfaces.SurfaceRef
Unit = materials.Unit
Component = materials.Component
MaterialColumn = materials.MaterialColumn

WEST = 735_000.0
SOUTH = 4_434_000.0
CLOSURE = 1e-9
"""Cierre de las unidades con el desmonte (RF-011-12; D-14 b)."""
SAME = 1e-12
"""Por bandas frente a de una vez, y las cuentas a mano en float64: error relativo al total."""
PRESENCE = fx.ANTHROPIC_PRESENCE_M


def _ref(name: str) -> SurfaceRef:
    return SurfaceRef(dataset=name)


def _natural(code: str, name: str, base: SurfaceRef | None, role: str = "waste") -> Unit:
    return Unit(code, name, "natural", role, "in_situ", base)


def _column() -> MaterialColumn:
    """Una columna válida: escombro (antrópico), montera, capa útil compuesta y muro."""
    return MaterialColumn((
        Unit("escombro", "Escombro", "anthropic", "waste", "loose", _ref("mdt_techo_util"),
             _ref("espesor_escombro")),
        _natural("montera", "Montera", _ref("mdt_techo_util")),
        Unit("capa_util", "Capa útil", "compound", None, "in_situ",
             SurfaceRef(elevation=612.3456789012345),
             components=(Component("caliza", "Caliza", "useful"),
                         Component("arcilla", "Arcilla", "waste"))),
        _natural("muro", "Muro", None),
    ))


def _grid(ncols: int, nrows: int, dx: float = 1.0, dy: float = 1.0) -> Grid:
    return Grid(west=WEST, north=SOUTH + nrows * dy, dx=dx, dy=dy, ncols=ncols, nrows=nrows)


def _run(grid: Grid, start, final, bases, thicknesses, *, e: float = 0.0,
         presence: float = PRESENCE, slices=None, domains=(), scope=None,
         band: int | None = None, chunks=None):
    """Cubica con unidades de una vez (``band=None``) o por bandas de ``band`` filas; con
    ``chunks`` (cortes de unidades consecutivos desde 0), cada banda por trozos de unidades."""
    accumulators = kernel.Accumulators(grid, slices=slices, domains=len(domains),
                                       min_thickness_m=e, units=len(bases),
                                       presence_m=presence)
    height = grid.nrows if band is None else band
    for first in range(0, grid.nrows, height):
        rows = slice(first, min(first + height, grid.nrows))
        weights = None
        if len(domains) or scope is not None:
            weights = polygons.weights(domains, scope, grid, rows)

        def cut(values):
            return values if values is None or np.ndim(values) == 0 else values[rows]

        values = kernel.BandValues(first, start[rows], cut(final),
                                   bases=tuple(cut(item) for item in bases),
                                   thicknesses=tuple(cut(item) for item in thicknesses))
        for part in (None,) if chunks is None else chunks:
            kernel.band_step(accumulators, values, weights, units=part)
    return accumulators.result()


def _close(test: unittest.TestCase, found, expected, scale: float, tolerance: float,
           what: str) -> None:
    """Cada valor de ``found`` a ≤ ``tolerance``·``scale`` del de ``expected``."""
    found = np.asarray(found, dtype=np.float64)
    expected = np.asarray(expected, dtype=np.float64)
    test.assertEqual(found.shape, expected.shape, what)
    worst = float(np.max(np.abs(found - expected), initial=0.0))
    test.assertLessEqual(worst, tolerance * scale,
                         f"{what}: {found!r} frente a {expected!r} (error {worst!r})")


def _fractions(grid: Grid, rect: tuple[float, float, float, float]) -> np.ndarray:
    """La fracción exacta de cada celda de ``grid`` dentro de ``rect`` (relativo a la esquina
    suroeste de ``grid``): el producto de los solapes en X y en Y, sin el núcleo."""
    west = np.arange(grid.ncols) * grid.dx
    north = grid.nrows * grid.dy - np.arange(grid.nrows) * grid.dy
    in_x = np.clip(np.minimum(west + grid.dx, rect[2]) - np.maximum(west, rect[0]), 0.0, None)
    in_y = np.clip(np.minimum(north, rect[3]) - np.maximum(north - grid.dy, rect[1]), 0.0,
                   None)
    return in_y[:, None] * in_x[None, :] / grid.cell_area


class ColumnTest(unittest.TestCase):
    """RF-011-11 (D-18, D-23, D-24): la columna, su validación y sus códigos."""

    def test_a_valid_column(self) -> None:
        """RF-011-11: una columna de arriba abajo con su nombre, clase, papel, estado y base
        (la última, sin base), una antrópica con su rejilla de espesores y una compuesta con
        sus componentes es válida; las clases, papeles y estados son los de la tabla."""
        column = _column()
        self.assertEqual(column.problems(), ())
        column.validate()
        self.assertEqual(column.codes, ("escombro", "montera", "capa_util", "muro"))
        self.assertIs(column.unit("capa_util"), column.units[2])
        self.assertEqual(column.units[0].kind, materials.Kind.ANTHROPIC)
        self.assertEqual(column.units[2].kind, "compound")
        self.assertIsNone(column.units[2].role)
        self.assertEqual(column.units[2].components[0].role, materials.Role.USEFUL)
        self.assertEqual(column.units[0].state, materials.State.LOOSE)
        self.assertEqual([kind.value for kind in materials.Kind],
                         ["natural", "anthropic", "compound", "component"])
        self.assertEqual([role.value for role in materials.Role], ["useful", "waste"])
        self.assertEqual([state.value for state in materials.State], ["in_situ", "loose"])
        fixture = fx.domain_column(fx.material_column())
        self.assertEqual(fixture.problems(), ())
        self.assertEqual(fixture.codes, ("acopio", "escombro", "montera", "capa_util", "muro"))

    def test_no_density_nor_swell_in_the_column(self) -> None:
        """RF-011-11 (D-8): ninguna unidad ni componente lleva densidad ni K: son parámetros
        con tipo e historial (``reserves.params``), sin valor por defecto."""
        for kind in (Unit, Component, MaterialColumn):
            names = {field.name for field in dataclasses.fields(kind)}
            with self.subTest(kind=kind.__name__):
                self.assertFalse({name for name in names
                                  if "density" in name or "swell" in name or "percent" in name})

    def test_problems_are_listed(self) -> None:
        """RF-011-11: códigos repetidos (también entre los componentes de una unidad) o no
        válidos, una unidad sin base que no es la última, la última con base, una antrópica sin
        rejilla de espesores o la última antrópica, una compuesta sin componentes, una unidad o
        un componente sin papel, un nombre vacío y la columna vacía se rechazan con
        ``res.materials_invalid`` y la lista (la unidad y el problema)."""
        caliza = Component("caliza", "Caliza", "useful")
        cases = {
            "res.materials_empty": MaterialColumn(()),
            "res.unit_code_repeated": MaterialColumn((
                _natural("montera", "Montera", _ref("a")), _natural("montera", "Otra", None))),
            "res.unit_code_invalid": MaterialColumn((_natural("Capa 1", "Capa 1", None),)),
            "res.unit_base_missing": MaterialColumn((
                _natural("montera", "Montera", None), _natural("muro", "Muro", None))),
            "res.unit_last_with_base": MaterialColumn((_natural("muro", "Muro", _ref("a")),)),
            "res.unit_thickness_missing": MaterialColumn((
                Unit("escombro", "Escombro", "anthropic", "waste", "loose", _ref("a")),
                _natural("muro", "Muro", None))),
            "res.unit_last_anthropic": MaterialColumn((
                Unit("escombro", "Escombro", "anthropic", "waste", "loose", None),)),
            "res.unit_components_missing": MaterialColumn((
                Unit("capa_util", "Capa útil", "compound", None, "in_situ", None),)),
            "res.unit_role_missing": MaterialColumn((
                Unit("capa_util", "Capa útil", "compound", None, "in_situ", None,
                     components=(Component("caliza", "Caliza", None),)),)),
            "res.unit_name_empty": MaterialColumn((_natural("muro", "  ", None),)),
        }
        for code, column in cases.items():
            with self.subTest(code=code):
                found = column.problems()
                self.assertEqual([problem.code for problem in found], [code])
                with self.assertRaises(materials.MaterialsError) as caught:
                    column.validate()
                error = caught.exception
                self.assertIsInstance(error, messages.ResError)
                self.assertEqual(error.code, "res.materials_invalid")
                self.assertEqual(error.problems, found)
                self.assertEqual(error.value, 1)
                self.assertIn(found[0].text(), error.text)
                self.assertNotIn("{", error.text)
                self.assertNotIn("{", found[0].text(language="en"))
        twice = MaterialColumn((
            Unit("capa_util", "Capa útil", "compound", None, "in_situ", None,
                 components=(caliza, Component("caliza", "Caliza 2", "waste"))),))
        self.assertEqual([problem.code for problem in twice.problems()],
                         ["res.unit_code_repeated"])
        self.assertIn("«Capa útil ▸ Caliza 2»", twice.problems()[0].text())
        # Un componente puede repetir el código de una unidad: su clave lleva la de su unidad.
        same = MaterialColumn((Unit("caliza", "Caliza", "compound", None, "in_situ", None,
                                    components=(caliza,)),))
        self.assertEqual(same.problems(), ())
        several = MaterialColumn((_natural("montera", "", None), _natural("montera", "M", None)))
        self.assertEqual([problem.code for problem in several.problems()],
                         ["res.unit_name_empty", "res.unit_base_missing",
                          "res.unit_code_repeated"])
        with self.assertRaises(materials.MaterialsError) as caught:
            several.validate()
        self.assertEqual(caught.exception.value, 3)
        self.assertEqual(
            caught.exception.text,
            "La columna de materiales no es válida: «montera» no tiene nombre; «montera» no "
            "tiene superficie de base: solo la última unidad va sin base; «M» repite el código "
            "«montera» de otro elemento de la columna. Corríjala en Cubicación ▸ Materiales y "
            "densidades….")

    def test_structure_errors_of_the_program(self) -> None:
        """Lo que la interfaz nunca construye es un error del programa (``ValueError``): una
        clase, papel o estado desconocidos, una unidad de clase «componente», una rejilla de
        espesores en una unidad que no es antrópica, componentes en una que no es compuesta,
        papel en una compuesta, una base o un espesor congelados (D-24) o un espesor que no es
        una rejilla (D-23)."""
        base = _ref("a")
        wrong = (
            lambda: Unit("a", "A", "rock", "waste", "in_situ", base),
            lambda: Unit("a", "A", "natural", "ore", "in_situ", base),
            lambda: Unit("a", "A", "natural", "waste", "wet", base),
            lambda: Unit("a", "A", "component", "waste", "in_situ", base),
            lambda: Unit("a", "A", "natural", "waste", "in_situ", base, _ref("e")),
            lambda: Unit("a", "A", "natural", "waste", "in_situ", base,
                         components=(Component("c", "C", "useful"),)),
            lambda: Unit("a", "A", "compound", "useful", "in_situ", base,
                         components=(Component("c", "C", "useful"),)),
            lambda: Unit("a", "A", "natural", "waste", "in_situ", SurfaceRef(frozen="x")),
            lambda: Unit("a", "A", "anthropic", "waste", "loose", base,
                         SurfaceRef(elevation=2.0)),
            lambda: Unit("a", "A", "natural", "waste", "in_situ", "mdt"),
            lambda: Component("c", "C", "ore"),
            lambda: MaterialColumn([_natural("a", "A", None), "b"]),
            lambda: SurfaceRef(),
            lambda: SurfaceRef(dataset="a", elevation=1.0),
            lambda: SurfaceRef(elevation=float("nan")),
            lambda: SurfaceRef(elevation=True),
            lambda: SurfaceRef(dataset=""),
        )
        for number, make in enumerate(wrong):
            with self.subTest(number=number), self.assertRaises((ValueError, TypeError)):
                make()

    def test_codes_are_immutable_and_unique(self) -> None:
        """D-18: el código es el ASCII en minúsculas del nombre al crear la unidad, único en la
        columna, y no cambia al renombrarla (es la clave de sus parámetros)."""
        self.assertEqual(materials.unit_code("Capa útil", ()), "capa_util")
        self.assertEqual(materials.unit_code("Capa útil", {"capa_util"}), "capa_util_2")
        self.assertEqual(materials.unit_code("Capa útil", {"capa_util", "capa_util_2"}),
                         "capa_util_3")
        self.assertEqual(materials.unit_code("  Ñandú — 1ª   capa ", ()), "nandu_1a_capa")
        self.assertEqual(materials.unit_code("1.ª capa", ()), "u_1_a_capa")
        self.assertEqual(materials.unit_code("—", ()), "u")
        self.assertEqual(materials.unit_code("", {"u"}), "u_2")
        long = materials.unit_code("Caliza " * 20, ())
        self.assertLessEqual(len(long), materials.CODE_MAX_LENGTH)
        self.assertFalse(long.endswith("_"))
        taken = {long}
        other = materials.unit_code("Caliza " * 20, taken)
        self.assertLessEqual(len(other), materials.CODE_MAX_LENGTH)
        self.assertNotIn(other, taken)
        for name in ("Capa útil", "1.ª capa", "—", "Caliza " * 20, "Ü", "ß"):
            self.assertRegex(materials.unit_code(name, ()), r"^[a-z][a-z0-9_]*$")
        column = _column()
        unit = column.units[2]
        renamed = unit.renamed("Capa explotable")
        self.assertEqual((renamed.code, renamed.name), ("capa_util", "Capa explotable"))
        self.assertEqual(renamed.components, unit.components)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            unit.code = "otra"  # type: ignore[misc]

    def test_round_trip_through_its_table(self) -> None:
        """RF-011-11 (§5.2.1): la columna va y vuelve por su tabla ``res_materials`` (una fila
        por unidad y por componente, la cota constante como texto exacto); sin la tabla, o sin
        filas, no hay columna."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertIsNone(materials.read_column(conn))
        conn.execute(materials.CREATE_TABLE)
        self.assertIsNone(materials.read_column(conn))
        read = []
        for column in (_column(), fx.domain_column(fx.material_column())):
            with self.subTest(codes=column.codes):
                conn.execute(f"DELETE FROM {materials.TABLE}")
                rows = materials.column_rows(column)
                store.insert_rows(conn, materials.TABLE, materials.COLUMNS, rows)
                back = materials.read_column(conn)
                self.assertEqual(back, column)
                self.assertEqual(back.problems(), ())
                read.append(back)
        self.assertEqual(read[0].units[2].base.elevation, 612.3456789012345)
        rows = materials.column_rows(_column())
        self.assertEqual(len(rows), 6)
        self.assertEqual(materials.COLUMNS, (
            "position", "parent", "code", "name", "kind", "role", "state", "base_dataset",
            "base_elevation", "thickness_dataset"))
        self.assertEqual(rows[0], (1, "", "escombro", "Escombro", "anthropic", "waste", "loose",
                                   "mdt_techo_util", None, "espesor_escombro"))
        self.assertEqual(rows[2], (3, "", "capa_util", "Capa útil", "compound", None,
                                   "in_situ", None, "612.3456789012345", None))
        self.assertEqual(rows[3], (1, "capa_util", "caliza", "Caliza", "component", "useful",
                                   "in_situ", None, None, None))
        self.assertEqual(rows[5][:4], (4, "", "muro", "Muro"))
        with self.assertRaises(sqlite3.IntegrityError):
            store.insert_rows(conn, materials.TABLE, materials.COLUMNS, [rows[0]])


class UnitsTest(unittest.TestCase):
    """RF-011-12, RF-011-13, RF-011-14 (A7, D-10, D-7): las unidades en cada celda."""

    # Siete celdas de 2,5 × 2 m (5 m²), de una fila. Tres unidades: un escombro antrópico (base
    # y espesor), una natural y la última, sin base. Umbral de presencia 0,30 m.
    #   c0: [0, 20], escombro presente sobre 15 → 5 / 5 / 10.
    #   c1: [0, 20], espesor 0,30 (no pasa del umbral: ausente) → 0 / 10 / 10.
    #   c2: [0, 20], espesor y base de la natural sin dato (ausentes, sin dato) → 0 / 0 / 20.
    #   c3: [0, 20], escombro sobre 8; la base de la natural (10) sube por encima: cruce →
    #       12 / 0 / 8.
    #   c4: terraplén [5, 12] (no se reparte); c5: [12, 20] → 0 / 8 / 0; c6: sin dato.
    START = np.array([[20.0, 20.0, 20.0, 20.0, 5.0, 20.0, np.nan]])
    FINAL = np.array([[0.0, 0.0, 0.0, 0.0, 12.0, 12.0, 0.0]])
    BASES = (np.array([[15.0, 15.0, 15.0, 8.0, 15.0, 15.0, 15.0]]),
             np.array([[10.0, 10.0, np.nan, 10.0, 10.0, 10.0, 10.0]]),
             None)
    THICKNESSES = (np.array([[5.0, 0.3, np.nan, 2.0, 1.0, 0.0, 1.0]]), None, None)
    GRID = _grid(7, 1, dx=2.5, dy=2.0)

    def _run(self, **options):
        return _run(self.GRID, self.START, self.FINAL, self.BASES, self.THICKNESSES, **options)

    def test_by_hand(self) -> None:
        """RF-011-12, RF-011-13, RF-011-14: cada unidad recibe el espesor del desmonte entre su
        base efectiva y la de la unidad presente encima: 17, 23 y 48 m de espesor (× 5 m²); una
        antrópica, desde su base hacia arriba y presente solo donde su espesor **pasa** del
        umbral; la base sin dato y el espesor sin dato, ausente (su espesor pasa a la de abajo);
        el cruce, espesor 0 (la de abajo, cortada en la base de encima). Áreas por unidad:
        ausente 15 / 5 / 0 m², sin dato 5 / 5 / 0 y cruce 0 / 5 / 0. Las unidades suman el
        desmonte (440 m³); el terraplén (35 m³) no se reparte. Las entradas no cambian."""
        copies = [item.copy() for item in (self.START, self.FINAL, self.BASES[0],
                                           self.BASES[1], self.THICKNESSES[0])]
        result = self._run()
        all_ = kernel.ALL
        self.assertEqual(result.units, 3)
        self.assertEqual(result.unit_volume_m3.shape, (1, 3))
        np.testing.assert_array_equal(result.unit_volume_m3[all_], [85.0, 115.0, 240.0])
        np.testing.assert_array_equal(result.unit_absent_m2[all_], [15.0, 5.0, 0.0])
        np.testing.assert_array_equal(result.unit_nodata_m2[all_], [5.0, 5.0, 0.0])
        np.testing.assert_array_equal(result.unit_crossed_m2[all_], [0.0, 5.0, 0.0])
        self.assertEqual(result.cut_m3[all_], 440.0)
        self.assertEqual(result.fill_m3[all_], 35.0)
        self.assertEqual(np.sum(result.unit_volume_m3[all_]), result.cut_m3[all_])
        self.assertIsNone(result.unit_slice_m3)
        for found, original in zip((self.START, self.FINAL, self.BASES[0], self.BASES[1],
                                    self.THICKNESSES[0]), copies, strict=True):
            np.testing.assert_array_equal(found, original)

    def test_the_minimum_thickness_and_the_presence_threshold(self) -> None:
        """RF-011-04 y RF-011-14: con e = 8,5 m, la celda de 8 m no es desmonte y no se reparte
        (sus áreas tampoco cuentan); con un umbral de presencia de 0 m, el espesor de 0,30 m
        pasa y el escombro de c1 tiene sus 5 m (de 15 a 20) y el de c5, ausente (espesor 0)."""
        result = self._run(e=8.5)
        np.testing.assert_array_equal(result.unit_volume_m3[kernel.ALL], [85.0, 75.0, 240.0])
        np.testing.assert_array_equal(result.unit_absent_m2[kernel.ALL], [10.0, 5.0, 0.0])
        self.assertEqual(result.cut_m3[kernel.ALL], 400.0)
        result = self._run(presence=0.0)
        np.testing.assert_array_equal(result.unit_volume_m3[kernel.ALL], [110.0, 90.0, 240.0])
        np.testing.assert_array_equal(result.unit_absent_m2[kernel.ALL], [10.0, 5.0, 0.0])

    def test_slices_of_each_unit(self) -> None:
        """RF-011-09 y RF-011-12 (A7 con A3): cada unidad se reparte entre las rodajas sobre su
        propio intervalo. Con 10 m desde 0: 2 + 15, 0 + 23 y 38 + 10 m; con la lista 5; 15, lo de
        abajo y lo de arriba, aparte. Por rodaja, las unidades suman la del desmonte."""
        result = self._run(slices=Slices(10.0, 0.0, None))
        np.testing.assert_array_equal(result.bounds, [0.0, 10.0, 20.0])
        self.assertEqual(result.unit_slice_m3.shape, (1, 3, 2))
        np.testing.assert_array_equal(result.unit_slice_m3[kernel.ALL],
                                      np.array([[2.0, 15.0], [0.0, 23.0], [38.0, 10.0]]) * 5.0)
        np.testing.assert_array_equal(result.unit_slice_m3[kernel.ALL].sum(axis=0),
                                      result.slice_cut_m3[kernel.ALL])
        np.testing.assert_array_equal(result.unit_below_m3[kernel.ALL], [0.0, 0.0, 0.0])
        listed = self._run(slices=Slices(None, None, (5.0, 15.0)))
        np.testing.assert_array_equal(listed.unit_slice_m3[kernel.ALL],
                                      np.array([[7.0], [13.0], [23.0]]) * 5.0)
        np.testing.assert_array_equal(listed.unit_below_m3[kernel.ALL],
                                      np.array([0.0, 0.0, 20.0]) * 5.0)
        np.testing.assert_array_equal(listed.unit_above_m3[kernel.ALL],
                                      np.array([10.0, 10.0, 5.0]) * 5.0)
        np.testing.assert_array_equal(
            listed.unit_slice_m3[kernel.ALL].sum(axis=1) + listed.unit_below_m3[kernel.ALL]
            + listed.unit_above_m3[kernel.ALL], listed.unit_volume_m3[kernel.ALL])

    def test_negative_thickness(self) -> None:
        """RF-011-14 (A7): un espesor negativo (aquí, en una celda de terraplén) rechaza la
        banda sin sumar nada (``NegativeThickness`` con la unidad y el menor);
        ``materials.negative_thickness`` da el error para el usuario
        (``res.thickness_negative``, con la rejilla, la unidad y el valor)."""
        thickness = self.THICKNESSES[0].copy()
        thickness[0, 4] = -0.25
        thickness[0, 6] = -0.125
        accumulators = kernel.Accumulators(self.GRID, units=3, presence_m=PRESENCE)
        band = kernel.BandValues(0, self.START, self.FINAL, bases=self.BASES,
                                 thicknesses=(thickness, None, None))
        with self.assertRaises(kernel.NegativeThickness) as caught:
            kernel.band_step(accumulators, band)
        self.assertEqual((caught.exception.unit, caught.exception.value), (0, -0.25))
        self.assertIsInstance(caught.exception, ValueError)
        kernel.band_step(accumulators, kernel.BandValues(
            0, self.START, self.FINAL, bases=self.BASES, thicknesses=self.THICKNESSES))
        np.testing.assert_array_equal(accumulators.result().unit_volume_m3[kernel.ALL],
                                      [85.0, 115.0, 240.0])
        unit = _column().units[0]
        error = materials.negative_thickness(unit, -0.25)
        self.assertIsInstance(error, messages.ResError)
        self.assertEqual(error.code, "res.thickness_negative")
        self.assertEqual(error.value, -0.25)
        self.assertEqual(error.text,
                         "La rejilla de espesores «espesor_escombro» de la unidad «Escombro» "
                         "tiene espesores negativos (el menor, -0,25 m): un espesor es de 0 m o "
                         "más; corríjala y vuelva a cubicar.")

    def test_by_unit_chunks_as_at_once(self) -> None:
        """RF-011-10: una banda por trozos de unidades (el primero que llega suma también los
        totales; ``slice(0, 0)``, solo los totales), en cualquier orden, da **bit a bit** lo
        mismo que de una vez."""
        options = {"slices": Slices(10.0, 0.0, None)}
        at_once = self._run(**options)
        for chunks in ((slice(0, 1), slice(1, 3)), (slice(0, 0), slice(0, 3)),
                       (slice(2, 3), slice(0, 2))):
            with self.subTest(chunks=chunks):
                by_parts = self._run(chunks=chunks, **options)
                for field in ("cut_m3", "unit_volume_m3", "unit_absent_m2", "unit_crossed_m2",
                              "unit_slice_m3"):
                    np.testing.assert_array_equal(getattr(by_parts, field),
                                                  getattr(at_once, field), field)

    def test_misuse(self) -> None:
        """Errores del programa (``ValueError``, sin sumar nada): bases o espesores que no son
        uno por unidad (o de otra forma), la última unidad con base o otra sin ella, un trozo de
        unidades repetido, fuera de la columna o con paso, la banda entera después de un trozo,
        un umbral negativo y un resultado sin todas las unidades."""
        grid, start, final = self.GRID, self.START, self.FINAL
        for presence in (-0.1, float("nan")):
            with self.subTest(presence=presence), self.assertRaises(ValueError):
                kernel.Accumulators(grid, units=3, presence_m=presence)
        with self.assertRaises(ValueError):
            kernel.Accumulators(grid, units=-1)
        accumulators = kernel.Accumulators(grid, units=3)
        wrong = (
            kernel.BandValues(0, start, final),
            kernel.BandValues(0, start, final, bases=self.BASES[:2],
                              thicknesses=self.THICKNESSES[:2]),
            kernel.BandValues(0, start, final, bases=(*self.BASES[:2], self.BASES[0]),
                              thicknesses=self.THICKNESSES),
            kernel.BandValues(0, start, final, bases=(self.BASES[0], None, None),
                              thicknesses=self.THICKNESSES),
            kernel.BandValues(0, start, final, bases=(self.BASES[0][:, :3], *self.BASES[1:]),
                              thicknesses=self.THICKNESSES),
        )
        for number, band in enumerate(wrong):
            with self.subTest(band=number), self.assertRaises(ValueError):
                kernel.band_step(accumulators, band)
        band = kernel.BandValues(0, start, final, bases=self.BASES,
                                 thicknesses=self.THICKNESSES)
        for units in (slice(0, 4), slice(0, 3, 2), slice(-1, 3), slice(2, 1)):
            with self.subTest(units=units), self.assertRaises(ValueError):
                kernel.band_step(accumulators, band, units=units)
        kernel.band_step(accumulators, band, units=slice(0, 2))
        for units in (slice(1, 3), None):
            with self.subTest(units=units), self.assertRaises(ValueError):
                kernel.band_step(accumulators, band, units=units)
        with self.assertRaises(ValueError):
            accumulators.result()
        kernel.band_step(accumulators, band, units=slice(2, 3))
        self.assertEqual(accumulators.result().unit_volume_m3[kernel.ALL, 2], 240.0)
        without = kernel.Accumulators(grid)
        with self.assertRaises(ValueError):
            kernel.band_step(without, band)
        with self.assertRaises(ValueError):
            kernel.band_step(without, kernel.BandValues(0, start, final), units=slice(0, 1))


class ColumnInTheKernelTest(unittest.TestCase):
    """RF-011-07, RF-011-09, RF-011-10, RF-011-12: la columna sintética por dominios, con ámbito,
    por rodajas y por bandas, en un solo cálculo."""

    CASE = fx.material_column()
    # Rectángulos relativos a la esquina suroeste, con un lado común, que cortan celdas; sus
    # cotas son exactas en binario también en absolutas (la referencia no lleva su redondeo).
    FIRST = (10.25, 5.75, 55.125, 61.875)
    SECOND = (55.125, 5.75, 99.0, 79.25)
    SCOPE = (3.25, 2.25, 97.75, 77.125)

    def _thickness(self) -> np.ndarray:
        """El espesor de cada unidad en cada celda (m), desde los planos de la columna y sin el
        núcleo: el acopio y el escombro, su espesor; la montera, del techo de la capa útil al
        terreno fuera del escombro; la capa útil, entre su base y su techo; el muro, de su techo
        a la final; nada en el terraplén."""
        case = self.CASE
        acopio, escombro, montera, capa, _muro = case.units
        cut = case.start.values > case.final.values
        ground, useful_top = acopio.base.values, montera.base.values
        muro_top = capa.base.values
        layers = (acopio.thickness.values, escombro.thickness.values,
                  np.where(escombro.thickness.values > 0.0, 0.0, ground - useful_top),
                  useful_top - muro_top, muro_top - case.final.values)
        return np.array([np.where(cut, layer, 0.0) for layer in layers])

    def _domains(self, scope):
        grid = self.CASE.grid
        items = [polygons.Polygon(1, "Fase 1", (self._ring(self.FIRST),)),
                 polygons.Polygon(2, "Fase 2", (self._ring(self.SECOND),))]
        return [item.edges for item in polygons.domain_edges(items, grid, scope=scope)]

    @staticmethod
    def _ring(rect):
        west, south = fx.COLUMN_WINDOW.xmin, fx.COLUMN_WINDOW.ymin
        return np.array([[rect[0], rect[1]], [rect[2], rect[1]], [rect[2], rect[3]],
                         [rect[0], rect[3]]]) + np.array([west, south])

    def _run(self, **options):
        bases, thicknesses = fx.column_layers(self.CASE)
        return _run(self.CASE.grid, self.CASE.start.values, self.CASE.final.values, bases,
                    thicknesses, **options)

    def _check_closure(self, result) -> None:
        """Nada se cuenta dos veces: en cada fila, las unidades suman su desmonte y, en cada
        rodaja, la del desmonte; las filas de cada unidad suman su total."""
        total = result.cut_m3[kernel.ALL]
        _close(self, result.unit_volume_m3.sum(axis=1), result.cut_m3, total, SAME, "filas")
        if result.domains:
            _close(self, result.unit_volume_m3[1:].sum(axis=0),
                   result.unit_volume_m3[kernel.ALL], total, SAME, "dominios")
        if result.unit_slice_m3 is not None:
            _close(self, result.unit_slice_m3.sum(axis=1), result.slice_cut_m3, total, SAME,
                   "rodajas")
            _close(self, result.unit_slice_m3.sum(axis=2), result.unit_volume_m3, total, SAME,
                   "rodajas de cada unidad")

    def test_by_domains_with_and_without_scope(self) -> None:
        """RF-011-07 y RF-011-12: cada unidad de cada fase es la suma de la fracción exacta de
        cada celda por el espesor de la unidad en ella (≤ 10⁻¹² del total), con y sin ámbito, y
        la fila «Fuera de los dominios» cierra; las unidades de cada fila suman su desmonte."""
        grid = self.CASE.grid
        thickness = self._thickness()
        scope = polygons.Polygon(9, "", (self._ring(self.SCOPE),))

        def clipped(rect):
            return (max(rect[0], self.SCOPE[0]), max(rect[1], self.SCOPE[1]),
                    min(rect[2], self.SCOPE[2]), min(rect[3], self.SCOPE[3]))

        cases = {
            "sin ámbito": ({}, np.ones(grid.shape), self.FIRST, self.SECOND),
            "con ámbito": ({"scope": polygons.scope_edges(scope, grid)},
                           _fractions(grid, self.SCOPE), clipped(self.FIRST),
                           clipped(self.SECOND)),
        }
        for name, (options, whole, first, second) in cases.items():
            with self.subTest(name):
                domains = self._domains(scope if options else None)
                result = self._run(domains=domains, **options)
                fractions = [_fractions(grid, first), _fractions(grid, second)]
                rows = [whole, *fractions, whole - sum(fractions)]
                expected = np.array([[np.sum(f * layer) for layer in thickness] for f in rows])
                total = result.cut_m3[kernel.ALL]
                _close(self, result.unit_volume_m3, expected * grid.cell_area, total, SAME,
                       "unidades por dominio")
                self._check_closure(result)
                np.testing.assert_array_equal(result.unit_crossed_m2, 0.0)

    def test_by_slices_and_by_bands(self) -> None:
        """RF-011-09 y RF-011-10: con rodajas de 5 m desde 0, dos fases y un ámbito, por bandas
        de 7 filas y por trozos de unidades da lo mismo que de una vez (≤ 10⁻¹² del total), y
        todo cierra: unidades con desmonte, rodajas y filas."""
        grid = self.CASE.grid
        scope = polygons.Polygon(9, "", (self._ring(self.SCOPE),))
        options = {"slices": Slices(5.0, 0.0, None), "domains": self._domains(scope),
                   "scope": polygons.scope_edges(scope, grid)}
        at_once = self._run(**options)
        self._check_closure(at_once)
        total = at_once.cut_m3[kernel.ALL]
        by_bands = self._run(band=7, chunks=(slice(0, 2), slice(2, 5)), **options)
        np.testing.assert_array_equal(by_bands.bounds, at_once.bounds)
        for field in ("unit_volume_m3", "unit_absent_m2", "unit_nodata_m2", "unit_slice_m3",
                      "unit_below_m3", "unit_above_m3"):
            _close(self, getattr(by_bands, field), getattr(at_once, field), total, SAME, field)


if __name__ == "__main__":
    unittest.main()
