# SPDX-License-Identifier: GPL-3.0-or-later
"""Detectar «se apoya en» (spec 015, T23; HU-015-2; RF-015-15; D-11; plan 015 §5.2.3, §5.4 A6 y P-5;
ADR-0030 §4; CE-015-01): el marco del error 59 (un relleno seguía apoyado en un acopio que se retiraba).

- **El cálculo puro** (``design.entities.detect_supports``, A6; sin proyecto): ``a = r − máx(partida,
  entidad)`` en las celdas de la huella de cada entidad; las celdas con ``a`` **mayor** que el espesor mínimo
  de la 012 y el volumen apoyado ``Σ a·área``, a ≤ 10⁻⁹ relativo del cálculo a mano; lo que solo **arrastra el
  terreno** sobre una plataforma «cortada» **no** cuenta (P-5); lo declarado por la persona sale **siempre**,
  con cero si no apoya nada. Es vectorizado (sin bucle por celda).
- **El gancho** (``DesignWriter.commit``, ``design.store``): toda operación que deja una superficie de diseño
  o de entidad —la plataforma de la 015, «solo relleno» de la 014— añade, al crear, la superficie de cada
  entidad en la que se apoya (``supported_on``) y la tabla de su huella (``support_footprint``) a sus
  entradas, y la cifra ``des.supported_m3`` con su ámbito. Una operación **hecha** es inmutable (ADR-0030 §4):
  al recalcular se arrastra lo que apoyaba y se vuelve a medir, no se copia el volumen, y **también se
  detectan las entidades que antes no estaban** (T42, C-1: «Balsa», creada antes que P1, gana la dependencia
  al recalcularse, con ``OperationHandle.add_inputs``); con la versión **sin entidades** nada cambia (ni se
  lee una superficie).
- **Lo que declara la persona** (``des.platform.{e}.supports``) se registra aunque el volumen sea cero; se
  rechaza lo que no existe, no está calculado, es ella misma o parte de ella (un ciclo).
- **Reproducir** (RF-009-11): una revisión congelada con lo apoyado se reproduce **con las mismas cifras**
  (``des.supported_m3``), desde la superficie y la huella congeladas de cada entidad.

La historia con proyecto, sobre la cantera de la 014 con las capas de plataformas (rejilla gruesa de 2 m):
P1, la «Plataforma de carga» (200 × 20 m, 250 m al 1 %, 1.000 celdas, de las que la ladera queda por encima:
corta del todo), y P2, «Sobre la carga» (la misma huella a 252 m, «en corte y relleno», **de la superficie de
P1**): rellena 2 m sobre 1.000 celdas de 4 m², **8.000 m³ a mano**.
"""

from __future__ import annotations

import functools
import json
import math
import time
import unittest
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import test_fill_only_operation as fill_test
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
design_store = import_geoblender("design.store")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
figures_mod = import_geoblender("core.provenance.figures")
freeze = import_geoblender("core.versions.freeze")
geotiff_reader = import_geoblender("gis.geotiff.reader")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
res_provenance = import_geoblender("reserves.provenance")
steps = import_geoblender("design.steps")

DesignError = messages.DesignError
SUPPORT_LAYER = "gis_fea_plataformas_apoyo"
OVER, DRAG, BALSA = "Sobre la carga", "Arrastra el terreno", "Plataforma de la balsa"
LOADING, WORKSHOP = prep.LOADING, prep.WORKSHOP
PSF1 = provenance.dataset_name("psf", LOADING)
EPR1 = provenance.dataset_name("epr", LOADING)
CELL_M2 = 4.0
OVER_VOLUME_M3 = 8_000.0
"""A mano: P2 sube 2 m (252 − 250 m) sobre las 1.000 celdas de 4 m² de la huella de P1."""
THICKNESS_M = 0.02
"""El espesor mínimo de la 012 por defecto (D-9 de la 012; ADOPTADO «sin confirmar»)."""
SHAPE = (6, 8)


def finish(work: Any) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    return ops_test.finish(work)


# ---------------------------------------------------------------------------------------------
# El cálculo puro (A6)
# ---------------------------------------------------------------------------------------------


def runs(*items: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Los índices de una huella dada en tramos ``(fila, col0, col1)``."""
    return entities.runs_cells(items)


@functools.cache
def box() -> tuple[np.ndarray, np.ndarray]:
    """Una huella de 4 × 4 = 16 celdas (filas 1 a 4, columnas 2 a 5) de una rejilla de 6 × 8."""
    return runs(*[(row, 2, 6) for row in range(1, 5)])


def flat(value: float, shape: tuple[int, int] = SHAPE) -> np.ndarray:
    return np.full(shape, float(value))


def raised(base: np.ndarray, by: float) -> np.ndarray:
    """``base`` con ``by`` m más en las celdas de :func:`box`."""
    found = base.copy()
    found[box()] += by
    return found


def detect(result: np.ndarray, start: np.ndarray, entity: np.ndarray, **options: Any
           ) -> tuple[Any, ...]:
    """``detect_supports`` de la superficie ``result`` desde ``start`` sobre una entidad ``PLT-001`` de
    superficie ``entity`` y huella :func:`box`."""
    thickness = options.pop("thickness", THICKNESS_M)
    return entities.detect_supports(result, start, {"PLT-001": entity}, {"PLT-001": box()}, thickness,
                                    CELL_M2, **options)


class DetectSupportsTest(unittest.TestCase):
    """RF-015-15, D-11 (A6, P-5), sin proyecto: ``a = r − máx(partida, entidad)`` en la huella, las celdas que
    pasan del espesor mínimo y ``Σ a·área``."""

    def test_a_a_fill_on_the_entity_is_its_volume_by_hand(self) -> None:
        """RF-015-15, D-11: una operación que parte de la superficie de la entidad (``s = e``) y la sube 2,5 m
        sobre sus 16 celdas de 4 m² apoya ``16 · 2,5 · 4 = 160`` m³ en ella (el relleno sobre la entidad)."""
        entity = flat(100.0)
        found = detect(raised(entity, 2.5), entity.copy(), entity)
        self.assertEqual(found, (entities.Support("PLT-001", 16, 160.0, False),))

    def test_a_dragging_the_terrain_over_a_cut_platform_is_not_support(self) -> None:
        """RF-015-15, D-11, P-5: la plataforma «cortada» está 6 m **por debajo** del terreno (``e < s``) y el
        diseño solo arrastra el terreno (``r = s``): sin el ``máx`` contaría como apoyado (``r − e = 6`` en las
        16 celdas); con él, ``a = 0`` y no se apoya en nada."""
        terrain, entity = flat(106.0), flat(100.0)
        self.assertTrue(((terrain - entity)[box()] > THICKNESS_M).all(), "sin el máx, todo contaría")
        self.assertEqual(detect(terrain.copy(), terrain, entity), ())

    def test_a_a_fill_above_the_terrain_that_was_above_the_entity_counts_from_the_terrain(self) -> None:
        """A6: con ``s`` por encima de ``e`` (el terreno que quedaba por encima de la plataforma cortada), el
        relleno cuenta **sobre el terreno**: ``r = 107,5`` sobre ``s = 106`` es ``a = 1,5``, ``16 · 1,5 · 4 =
        96`` m³ (no los 7,5 m sobre la plataforma)."""
        entity, terrain = flat(100.0), flat(106.0)
        found = detect(raised(terrain, 1.5), terrain, entity)
        self.assertEqual(found, (entities.Support("PLT-001", 16, 96.0, False),))

    def test_a_a_start_below_the_entity_counts_only_the_part_above_it(self) -> None:
        """A6: con ``s`` por debajo de ``e``, cuenta la parte por encima de la entidad: ``e = 100``, ``s = 97``,
        ``r = 101,5`` es ``a = 1,5`` (96 m³); un ``r = 99`` entre las dos no apoya nada."""
        entity, below = flat(100.0), flat(97.0)
        result = below.copy()
        result[box()] = 101.5
        self.assertEqual(detect(result, below, entity),
                         (entities.Support("PLT-001", 16, 96.0, False),))
        result[box()] = 99.0
        self.assertEqual(detect(result, below, entity), ())

    def test_a_the_minimum_thickness_is_exclusive_to_the_last_bit(self) -> None:
        """RF-015-15: se cuentan las celdas con ``a`` **mayor** que el espesor mínimo: justo por encima
        (``+ 2⁻³⁰``) cuenta, igual (0,5) y justo por debajo no (todas las cifras son exactas en binario); con
        el valor por defecto, 0,021 m cuenta y 0,019 m no."""
        entity, tiny = flat(100.0), 2.0 ** -30
        for by, cells in ((0.5 + tiny, 16), (0.5, 0), (0.5 - tiny, 0)):
            with self.subTest(by=by):
                found = detect(raised(entity, by), entity.copy(), entity, thickness=0.5)
                self.assertEqual(sum(item.cells for item in found), cells)
        self.assertEqual(len(detect(raised(entity, 0.021), entity.copy(), entity)), 1)
        self.assertEqual(detect(raised(entity, 0.019), entity.copy(), entity), ())

    def test_a_cells_without_data_do_not_count_and_do_not_poison_the_sum(self) -> None:
        """A6: una celda con ``NaN`` en la superficie resultante, la de partida o la de la entidad no cuenta
        (y el volumen de las demás sale finito): 16 − 3 = 13 celdas de 2 m · 4 m² = 104 m³."""
        entity, start = flat(100.0), flat(100.0)
        result = raised(start, 2.0)
        result[1, 2] = np.nan
        start[2, 3] = np.nan
        entity[3, 4] = np.nan
        found = entities.detect_supports(result, start, {"PLT-001": entity}, {"PLT-001": box()},
                                         THICKNESS_M, CELL_M2)
        self.assertEqual(found, (entities.Support("PLT-001", 13, 104.0, False),))

    def test_a_what_the_user_declares_is_always_there_with_the_volume_it_gives(self) -> None:
        """RF-015-15, D-11: una dependencia declarada se registra **aunque no apoye nada** (cero celdas, 0 m³);
        la que apoya algo lleva su volumen; una entidad que no apoya nada y no se declaró no sale."""
        entity = flat(100.0)
        self.assertEqual(detect(entity.copy(), entity.copy(), entity, declared=("PLT-001",)),
                         (entities.Support("PLT-001", 0, 0.0, True),))
        self.assertEqual(detect(entity.copy(), entity.copy(), entity), ())
        self.assertEqual(detect(raised(entity, 1.0), entity.copy(), entity, declared=("PLT-001",)),
                         (entities.Support("PLT-001", 16, 64.0, True),))
        with self.assertRaises(KeyError):
            detect(entity.copy(), entity.copy(), entity, declared=("PLT-002",))

    def test_a_several_entities_each_with_its_own_surface_by_code_order(self) -> None:
        """A6: cada entidad con su huella y su superficie; salen por orden de código (PLT-002 antes que
        PLT-010) y una que no apoya nada no sale."""
        base = flat(100.0)
        result = base.copy()
        result[0, 0:3] = 103.0  # sobre la de PLT-010: 3 celdas · 3 m · 4 m² = 36 m³
        result[5, 4:8] = 101.0  # sobre la de PLT-002: 4 celdas · 1 m · 4 m² = 16 m³
        found = entities.detect_supports(
            result, base, {"PLT-010": base, "PLT-002": base, "PLT-003": base},
            {"PLT-010": runs((0, 0, 3)), "PLT-002": runs((5, 4, 8)), "PLT-003": runs((2, 0, 8))},
            THICKNESS_M, CELL_M2)
        self.assertEqual(found, (entities.Support("PLT-002", 4, 16.0, False),
                                 entities.Support("PLT-010", 3, 36.0, False)))

    def test_a_the_volume_is_the_hand_sum_to_a_billionth(self) -> None:
        """CE-015-01 (D-9): con espesores irregulares (de 0 a 3 m) sobre 5.000 celdas de 6,25 m², el volumen
        es la suma a mano (``math.fsum`` celda a celda) a ≤ 10⁻⁹ relativo y las celdas, las que pasan del
        espesor mínimo."""
        generator = np.random.default_rng(15)
        shape = (80, 90)
        start = 200.0 + generator.random(shape) * 5.0
        entity = start - generator.random(shape) * 2.0 + generator.random(shape) * 2.0
        result = start + generator.random(shape) * 3.0 - 0.1
        rows = generator.integers(0, shape[0], 5000)
        cols = generator.integers(0, shape[1], 5000)
        unique = np.unique(np.stack([rows, cols], axis=1), axis=0)
        footprint = (unique[:, 0], unique[:, 1])
        found = entities.detect_supports(result, start, {"PLT-001": entity}, {"PLT-001": footprint},
                                         THICKNESS_M, 6.25)
        thick = [result[r, c] - max(start[r, c], entity[r, c]) for r, c in unique]
        counted = [value for value in thick if value > THICKNESS_M]
        (item,) = found
        self.assertEqual(item.cells, len(counted))
        self.assertGreater(len(counted), 1000)
        self.assertLessEqual(abs(item.volume_m3 - math.fsum(counted) * 6.25) / item.volume_m3, 1e-9)

    def test_a_it_is_vectorized_one_million_cells_in_well_under_a_second(self) -> None:
        """RNF-015-04 (A6: sin bucle por celda): una huella de 1.000 × 1.000 celdas de una rejilla de 1654 ×
        1699 (la de la cantera a 1 m) da el volumen a mano (3 m sobre cada una: 3 · 10⁶ m³ de 1 m²) en < 1 s."""
        shape = (1654, 1699)
        entity = np.full(shape, 250.0)
        result = entity.copy()
        footprint = entities.runs_cells([(row, 100, 1100) for row in range(300, 1300)])
        result[footprint] += 3.0
        began = time.perf_counter()
        found = entities.detect_supports(result, entity, {"PLT-001": entity}, {"PLT-001": footprint},
                                         THICKNESS_M, 1.0)
        elapsed = time.perf_counter() - began
        self.assertEqual(found, (entities.Support("PLT-001", 1_000_000, 3_000_000.0, False),))
        self.assertLess(elapsed, 1.0)

    def test_a_the_strongest_of_the_surfaces_of_an_operation(self) -> None:
        """RF-015-15: de las superficies de una misma operación (las dos de una cantera, las de un ajuste), que
        son alternativas, cuenta la que más apoya en cada entidad; declarada si alguna lo era."""
        found = entities.strongest([
            entities.Support("PLT-002", 4, 16.0, False), entities.Support("PLT-001", 1, 2.0, True),
            entities.Support("PLT-001", 5, 9.0, False), entities.Support("PLT-002", 2, 8.0, True)])
        self.assertEqual(found, (entities.Support("PLT-001", 5, 9.0, True),
                                 entities.Support("PLT-002", 4, 16.0, True)))
        self.assertEqual(entities.strongest([]), ())

    def test_a_the_arguments_are_checked(self) -> None:
        """Errores del programa: rejillas de formas distintas, un espesor o un área que no valen, una entidad
        sin superficie."""
        entity = flat(100.0)
        with self.assertRaises(ValueError):
            detect(flat(101.0, (6, 9)), entity, entity)
        with self.assertRaises(ValueError):
            detect(raised(entity, 1.0), flat(100.0, (5, 8)), entity)
        with self.assertRaises(ValueError):
            detect(raised(entity, 1.0), entity, flat(1.0, (3, 3)))
        for thickness in (-0.1, math.nan, math.inf):
            with self.subTest(thickness=thickness), self.assertRaises(ValueError):
                detect(raised(entity, 1.0), entity, entity, thickness=thickness)
        for area in (0.0, -1.0, math.nan):
            with self.subTest(area=area), self.assertRaises(ValueError):
                entities.detect_supports(raised(entity, 1.0), entity, {"PLT-001": entity},
                                         {"PLT-001": box()}, THICKNESS_M, area)
        with self.assertRaises(KeyError):
            entities.detect_supports(raised(entity, 1.0), entity, {}, {"PLT-001": box()}, THICKNESS_M,
                                     CELL_M2)
        with self.assertRaises(TypeError):
            entities.detect_supports(raised(entity, 1.0), entity, {"PLT-001": entity},
                                     {"PLT-001": box()}, "0,02", CELL_M2)  # type: ignore[arg-type]


class UnsupportableTest(unittest.TestCase):
    """RF-015-15 (A6): una operación no se apoya en sí misma ni en lo que parte de lo que ella deja (sería un
    ciclo en el grafo), con un registro sintético."""

    @staticmethod
    def registry() -> Any:
        def entry(code: str, start: str) -> Any:
            return entities.EntityEntry(
                entities.EntityRecord(code, f"E{code[-1]}", "platform", start, None, "current"), "uid")

        return entities.EntityRegistry("V01", (
            entry("PLT-001", "terreno"), entry("PLT-002", "entity:PLT-001"),
            entry("PLT-003", "des_srf_diseno"), entry("PLT-004", "entity:PLT-003"),
            entry("PLT-005", "otro")))

    def test_a_an_entity_does_not_rest_on_itself_or_on_what_starts_from_it(self) -> None:
        """RF-015-15: PLT-001 no se apoya en PLT-001 ni en PLT-002 (parte de su superficie: aguas abajo de la
        cadena); sí en las demás. Una entidad nueva (aún no está en el registro) solo se excluye a sí misma."""
        found = entity_store._unsupportable(self.registry(), "PLT-001", ())
        self.assertEqual(found, {"PLT-001", "PLT-002"})
        self.assertEqual(entity_store._unsupportable(self.registry(), "PLT-009", ()), {"PLT-009"})

    def test_a_a_design_does_not_rest_on_what_starts_from_the_surface_it_writes(self) -> None:
        """RF-015-15: un diseño de la 013 o la 014 que deja ``des_srf_diseno`` no se apoya en las entidades que
        parten de ella (PLT-003) ni en las que les siguen (PLT-004): al recalcularlo sería un ciclo."""
        found = entity_store._unsupportable(self.registry(), None, {"des_srf_diseno"})
        self.assertEqual(found, {"PLT-003", "PLT-004"})
        self.assertEqual(entity_store._unsupportable(self.registry(), None, ()), set())


class RunsCellsTest(unittest.TestCase):
    """La huella en tramos de ``des_epr_`` como índices de celda (vectorizado)."""

    def test_a_runs_to_cells_by_hand_and_back(self) -> None:
        """RF-015-15: ``(0, 1, 4)`` y ``(2, 0, 2)`` son las celdas (0,1), (0,2), (0,3), (2,0), (2,1) de
        norte a sur y de oeste a este; sin tramos, ninguna; y es la inversa de ``runs_mask``."""
        rows, cols = entities.runs_cells([(0, 1, 4), (2, 0, 2)])
        self.assertEqual((rows.tolist(), cols.tolist()), ([0, 0, 0, 2, 2], [1, 2, 3, 0, 1]))
        empty_rows, empty_cols = entities.runs_cells([])
        self.assertEqual((empty_rows.size, empty_cols.size), (0, 0))
        mask = np.zeros((4, 6), dtype=bool)
        mask[rows, cols] = True
        np.testing.assert_array_equal(mask, entity_store.runs_mask([(0, 1, 4), (2, 0, 2)], (4, 6)))

    def test_a_a_run_without_cells_is_a_program_error(self) -> None:
        for bad in ((1, 3, 3), (1, 4, 2)):
            with self.subTest(run=bad), self.assertRaises(ValueError):
                entities.runs_cells([bad])


# ---------------------------------------------------------------------------------------------
# Con proyecto: la plataforma que se apoya en otra
# ---------------------------------------------------------------------------------------------


def support_layer() -> Any:
    """La capa de ejes de las plataformas de esta prueba (arrays nuevos): «Sobre la carga» (el eje y el ancho de
    la «Plataforma de carga» a 252 m, 2 m más arriba), «Arrastra el terreno» (un eje norte-sur de 50 m y 10 m de
    ancho que **cruza** la huella de la de carga, a 255 m: corta, no rellena) y «Plataforma de la balsa» (de
    30 × 6 m en la lámina de agua de la 014, a 255 m, que corta)."""
    specs = ((OVER, ((110.0, 280.0), (310.0, 280.0)), 20.0, 252.0, 1.0),
             (DRAG, ((200.0, 255.0), (200.0, 305.0)), 10.0, 255.0, 0.0),
             (BALSA, ((135.0, 305.0), (165.0, 305.0)), 6.0, 255.0, 0.0))
    return qfx.LayerData(
        SUPPORT_LAYER, "line", tuple(((cfx.absolute(path),),) for _name, path, *_rest in specs),
        tuple(item[0] for item in specs),
        {"ancho": tuple(item[2] for item in specs), "cota_inicial": tuple(item[3] for item in specs),
         "pendiente": tuple(item[4] for item in specs)})


def asked(name: str, **changes: Any) -> Any:
    """Una plataforma de la capa de apoyo (por el nombre de su geometría)."""
    return prep.request(name, fields=prep.line_fields(SUPPORT_LAYER), **changes)


def over(**changes: Any) -> Any:
    """P2, «Sobre la carga»: de la superficie de P1, «en corte y relleno»."""
    return asked(OVER, start="entity:PLT-001", mode=model.PlatformMode.CUT_FILL, **changes)


class SupportsCase(ops_test.RecomputeCase):
    """Lo de ``RecomputeCase`` (las plataformas con sus funciones reales) más la capa de apoyo y los ayudantes
    de lo que queda registrado: sus entradas ``supported_on`` y ``support_footprint`` y sus cifras."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        qfx.write_feature_layer(cls.project, cls.clock, support_layer())
        cls.clock.advance(minutes=1)

    def supports_of(self, uid: str) -> list[tuple[str, str]]:
        """Los pares ``(dato, papel)`` de lo que apoya la operación ``uid`` (``supported_on`` y
        ``support_footprint``), en el orden en que los anotó."""
        return self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.role IN ('supported_on', "
            "'support_footprint') ORDER BY io.fid", uid)

    def volumes_of(self, uid: str) -> dict[str, float]:
        """El volumen apoyado (``des.supported_m3``) por entidad que registró la operación ``uid``."""
        return {json.loads(scope)["entity"]: value
                for (key, scope), value in self.figures_of(uid).items() if key == "des.supported_m3"}

    def footprint_of(self, table: str) -> tuple[np.ndarray, np.ndarray]:
        """Las celdas de la huella de la tabla ``des_epr_`` ``table`` de V01 (de su fila)."""
        (found,) = self.query(f'SELECT footprint FROM "{self.record(table, self.v1).locator}"')
        return entities.runs_cells(json.loads(found[0]))

    def by_hand(self, result: str, start: np.ndarray, entity: str, table: str) -> float:
        """Lo apoyado por la superficie ``result`` (V01) desde ``start`` sobre la entidad de superficie
        ``entity`` y huella ``table``: ``a = r − máx(partida, entidad)`` leído de los ficheros, celda a celda,
        y el volumen de las que pasan del espesor mínimo (4 m² cada una)."""
        rows, cols = self.footprint_of(table)
        with np.errstate(invalid="ignore"):
            found = self.grid_of(result)[rows, cols] - np.maximum(start[rows, cols],
                                                                  self.grid_of(entity)[rows, cols])
            return float(found[found > THICKNESS_M].sum()) * CELL_M2


class ThicknessCase(SupportsCase):
    """Lo de ``SupportsCase`` más cambiar el espesor mínimo de la 012 (``res.verify.min_thickness_m``, del
    proyecto) un minuto después."""

    KEY: ClassVar[str] = design_params.VERIFY_MIN_THICKNESS

    @classmethod
    def thickness(cls, value: float) -> None:
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).change(
                conn, cls.KEY, value=value, source="Prueba de la T23", source_kind="person",
                decided_by="Samuel (IMGA)", reason="Espesor mínimo de la prueba")


class ThicknessAtCreationTest(ThicknessCase):
    """RF-015-15, D-11: con un espesor mínimo de 2,1 m, los 2 m que P2 sube sobre P1 no cuentan: no se apoya."""

    second: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.thickness(2.1)
        cls.second = cls.made(over())

    def test_c_what_rises_less_than_the_minimum_thickness_is_not_supported(self) -> None:
        """RF-015-15 (``res.verify.min_thickness_m``): con 2,1 m, P2 (que sube 2,0 m, 8.000 m³ si contara) no
        se apoya en P1: sin entradas ``supported_on`` ni cifra; el parámetro está entre los que leyó."""
        uid = self.second.handle.uid
        self.assertEqual(self.supports_of(uid), [])
        self.assertEqual(self.volumes_of(uid), {})
        read = {key for (key,) in self.query(
            "SELECT p.key FROM gb_operation_param AS op JOIN gb_parameter AS p ON p.uid = op.parameter_uid "
            "WHERE op.operation_uid = ?", uid)}
        self.assertIn(self.KEY, read)


# ---------------------------------------------------------------------------------------------
# Con proyecto: un «solo relleno» de la 014 y una versión sin entidades
# ---------------------------------------------------------------------------------------------


class FillOnlyCase(SupportsCase):
    """Lo de ``SupportsCase`` más lo de la cantera de la 014 con el diseño «solo relleno»: los tipos de la 013 y
    la 014 registrados, el perfil y la envolvente de la prueba en V01 (:meth:`build`) y :meth:`fill`, que
    «calcula» y «crea» un «solo relleno» con la orden real."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*ops_test.real_definitions(), *fill_test.definitions())

    @classmethod
    def fill(cls, request: Any) -> Any:
        """«Calcula» y «crea» el diseño «solo relleno» ``request`` en V01."""
        cls.clock.advance(minutes=1)
        return fill_test.drive(steps.fill_only_run(cls.project, request, version=cls.v1.uid,
                                                   masks=cls.masks_v1)).result.create()

    @classmethod
    def exists(cls) -> bool:
        with cls.project.read() as conn:
            return bool(design_store._has_entities(conn, cls.v1.uid))

    @classmethod
    def build(cls) -> None:
        """Los parámetros del perfil de la prueba y su envolvente en V01 (sin ninguna entidad todavía)."""
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            fill_test.declare(cls.project, cls.clock, design_params.bench_key(fill_test.REST.code, param),
                              getattr(fill_test.REST, param))
        envelope = model.EnvelopeRequest(
            fill_test.ENVELOPE, "down",
            model.SeedSource("fixed", zone=model.Zone("layer", qfx.WATER_LAYER),
                             elevation_m=fill_test.ENVELOPE_LEVEL_M),
            slope_deg=fill_test.ENVELOPE_SLOPE_DEG)
        cls.clock.advance(minutes=1)
        fill_test.drive(steps.envelope_run(cls.project, envelope, version=cls.v1.uid,
                                           masks=cls.masks_v1)).result.create()

    def current_fill_of(self, name: str) -> str:
        """El uid de la operación vigente del «solo relleno» ``name``."""
        rows = self.query("SELECT uid, settings FROM gb_operation WHERE op_type = 'des.fill_only' AND "
                          "status = 'done' AND superseded_by IS NULL ORDER BY fid")
        (found,) = [uid for uid, settings in rows if json.loads(settings).get("name") == name]
        return str(found)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
