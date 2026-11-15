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
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files
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


class SupportedOnFillTest(SupportsCase):
    """RF-015-15, D-11, CE-015-01: P2 («en corte y relleno» sobre la huella de P1, de su superficie) se apoya en
    P1 con los 8.000 m³ a mano; P1, que se creó antes, no se apoya en nada."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    shown: ClassVar[tuple[Any, ...]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.clock.advance(minutes=1)
        calculation = cls.calculate_in(over())
        cls.shown = entity_store.detected_supports(cls.project, calculation.entity, calculation.outcome)
        cls.clock.advance(minutes=1)
        cls.second = calculation.create()

    def test_b_the_platform_that_fills_on_another_rests_on_it_with_the_volume_by_hand(self) -> None:
        """RF-015-15, CE-015-01 (D-9): la operación de P2 anota la superficie de P1 como ``supported_on`` y
        la tabla de su huella como ``support_footprint`` (además de la superficie de partida, que es la misma
        con el papel ``surface``) y la cifra ``des.supported_m3`` con el ámbito de P1 —CALCULADO, en m³—:
        **8.000 m³**, a ≤ 10⁻⁹ relativo del cálculo a mano y del que sale de los ficheros (``r − máx(s, e)``
        sobre la huella de P1)."""
        uid = self.second.handle.uid
        self.assertEqual(self.supports_of(uid), [(PSF1, "supported_on"), (EPR1, "support_footprint")])
        inputs = {(name, role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in'", uid)}
        self.assertIn((PSF1, "surface"), inputs)
        self.assertIn((PSF1, "supported_on"), inputs)
        found = self.volumes_of(uid)
        self.assertEqual(list(found), ["PLT-001"])
        self.assertLessEqual(abs(found["PLT-001"] - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        oracle = self.by_hand(provenance.dataset_name("psf", OVER), self.grid_of(PSF1), PSF1, EPR1)
        self.assertLessEqual(abs(found["PLT-001"] - oracle) / oracle, 1e-9)
        scope = figures_mod.scope_json(provenance.entity_figure_scope(OVER, "PLT-001"))
        self.assertEqual(self.figures_of(uid)[("des.supported_m3", scope)], found["PLT-001"])
        self.assertEqual(self.query("SELECT unit, kind FROM gb_figure WHERE operation_uid = ? AND key = "
                                    "'des.supported_m3'", uid), [("m3", "CALCULADO")])

    def test_b_the_first_platform_rests_on_nothing_and_what_rests_on_it_is_a_query(self) -> None:
        """RF-015-15, ADR-0030 §4: P1 se creó antes y no se apoya en nada (ni entradas ni cifras); lo que se le
        apoya a P1 es una consulta de las entradas con el rol ``supported_on`` (la lista de la T24: P2, que
        además parte de su superficie: se ve tanto por partida como por relleno); las dos siguen al día."""
        self.assertEqual(self.supports_of(self.first.handle.uid), [])
        self.assertEqual(self.volumes_of(self.first.handle.uid), {})
        rests = self.query(
            "SELECT o.uid, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "JOIN gb_operation AS o ON o.uid = io.operation_uid WHERE io.direction = 'in' AND d.name = ? "
            "ORDER BY io.role", PSF1)
        self.assertEqual(rests, [(self.second.handle.uid, "supported_on"),
                                 (self.second.handle.uid, "surface")])
        registry = entities.registry(self.project, self.v1.uid)
        self.assertEqual([str(entry.record.state) for entry in registry], ["current", "current"])

    def test_b_what_the_hook_shows_is_what_creating_records(self) -> None:
        """RF-015-15: ``detected_supports`` (lo que apoyaría una plataforma calculada, para enseñarlo antes de
        crearla) dio a P1 con las mismas 1.000 celdas y los mismos 8.000 m³ que registró «Crear»."""
        self.assertEqual([(item.code, item.cells) for item in self.shown], [("PLT-001", 1000)])
        self.assertLessEqual(abs(self.shown[0].volume_m3 - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        self.assertEqual(self.shown[0].volume_m3, self.volumes_of(self.second.handle.uid)["PLT-001"])


class FrozenSupportsTest(SupportsCase):
    """RF-015-15, RF-009-11: congelar V01 con P1 y P2 (que se apoya en ella) y reproducir da las mismas cifras,
    **también** ``des.supported_m3``, desde la superficie y la huella congeladas de P1."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    revision: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.second = cls.made(over())
        cls.clock.advance(minutes=1)
        frozen = finish(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def test_d_reproducing_gives_the_supported_volume_too(self) -> None:
        """RF-015-15, RF-009-11: V01.r1 se reproduce —sin proyecto— con la misma cifra de lo apoyado (la
        reproducción lee la superficie de P1 y la tabla de su huella congeladas, con ``s`` y ``r``) y todo
        igual, sin escribir nada en el proyecto."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)),
                         before, "reproducir no escribe en el proyecto")
        uid = self.second.handle.uid
        found = [check for check in report.figures if check.operation_uid == uid
                 and check.key == "des.supported_m3"]
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].same, found)
        self.assertLessEqual(abs(found[0].reproduced - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        self.assertTrue(all(check.same for check in report.figures))
        self.assertTrue(all(check.same for check in report.outputs))
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)


class RecomputeSupportsTest(SupportsCase):
    """RF-015-15, ADR-0030 §4, RF-015-02 (T14): recalcular P2 lleva lo que apoyaba y lo **vuelve a medir** sobre
    el resultado nuevo (no copia el volumen): una operación hecha es inmutable."""

    first: ClassVar[Any]
    second: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.second = cls.made(over())

    def test_c_recomputing_keeps_what_it_rested_on_and_measures_it_again(self) -> None:
        """RF-015-15, ADR-0030 §4: P2 sube de 252 a 253 m (parámetro de su fila de la versión) y se recalcula:
        la operación **nueva** (la anterior queda como historia con sus 8.000 m³) anota otra vez la superficie
        de P1 y la tabla de su huella y mide **12.000 m³** (3 m sobre 1.000 celdas de 4 m²), no los 8.000 de
        antes."""
        old = self.second.handle.uid
        before = self.volumes_of(old)["PLT-001"]
        self.assertLessEqual(abs(before - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        self.change(design_params.entity_key("PLT-002", "start_level_m"), 253.0)
        self.assertEqual(len(self.recompute_plan()), 1)
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(old))
        finish(work)
        new = handle.uid
        self.assertNotEqual(new, old)
        self.assertEqual(self.supports_of(new), [(PSF1, "supported_on"), (EPR1, "support_footprint")])
        found = self.volumes_of(new)
        self.assertEqual(list(found), ["PLT-001"])
        self.assertLessEqual(abs(found["PLT-001"] - 12_000.0) / 12_000.0, 1e-9)
        self.assertEqual(self.volumes_of(old)["PLT-001"], before, "la historia no cambia")
        self.assertEqual(self.current("PLT-002"), new)
        self.assertEqual(self.recompute_plan(), [])


class DragSupportsTest(SupportsCase):
    """RF-015-15, D-11, P-5: un diseño que solo **arrastra el terreno** sobre la huella de una plataforma
    «cortada» no se apoya en ella."""

    other: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.other = cls.made(asked(DRAG, start=prep.HOLE_DATASET))

    def test_d_a_design_that_only_drags_the_terrain_over_a_cut_platform_is_not_supported(self) -> None:
        """RF-015-15, P-5: «Arrastra el terreno» (que parte de otro terreno, corta a 255 m y cruza la huella de
        P1) deja el terreno —**por encima** de la plataforma cortada— tal como estaba en casi toda ella: sin
        el ``máx(partida, entidad)`` contaría como apoyada en P1 (``r − e`` pasa de 0,02 m en cientos de sus
        celdas); con él, ``a`` es 0 a mano y no se apoya en nada (ni entradas ni cifra)."""
        uid = self.other.handle.uid
        self.assertEqual(self.supports_of(uid), [])
        self.assertEqual(self.volumes_of(uid), {})
        mine, theirs = self.grid_of(provenance.dataset_name("psf", DRAG)), self.grid_of(PSF1)
        rows, cols = self.footprint_of(EPR1)
        with np.errstate(invalid="ignore"):
            naive = (mine[rows, cols] - theirs[rows, cols]) > THICKNESS_M
        self.assertGreater(int(naive.sum()), 500, "sin el máx, la mayor parte de la huella contaría")
        self.assertEqual(self.by_hand(provenance.dataset_name("psf", DRAG), prep.hole_raster().values,
                                      PSF1, EPR1), 0.0)

    def test_d_recomputing_a_design_that_rests_on_nothing_gains_no_dependency(self) -> None:
        """RF-015-15 (C-1, el reverso): recalcular «Arrastra el terreno», que cruza la huella de P1 sin rellenar
        encima, **no** gana ninguna entrada ni cifra (como al crearla: la versión tiene entidades, pero ninguna
        bajo lo que rellena)."""
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(self.other.handle.uid))
        finish(work)
        self.assertNotEqual(handle.uid, self.other.handle.uid)
        self.assertEqual(self.supports_of(handle.uid), [])
        self.assertEqual(self.volumes_of(handle.uid), {})


class DeclaredSupportsTest(SupportsCase):
    """RF-015-15, D-11: lo que la persona **declara** (``des.platform.{e}.supports``) se registra aunque no apoye
    nada; lo que no existe, es ella misma o sería un ciclo se rechaza sin escribir nada. P1 (la de carga),
    P2 (sobre ella: parte de su superficie) y P3 (el taller, de otro terreno y lejos de las demás)."""

    workshop: ClassVar[Any]
    WORKSHOP_KEY: ClassVar[str] = design_params.entity_key("PLT-003", "supports")

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(over())
        cls.workshop = cls.made(prep.request(WORKSHOP, start=prep.HOLE_DATASET))

    @classmethod
    def declare(cls, code: str, text: str) -> None:
        """Declara en la versión que la entidad ``code`` se apoya en ``text`` (códigos separados por comas)."""
        cls.clock.advance(minutes=1)
        key = design_params.entity_key(code, "supports")
        store = core_params.ParameterStore(cls.project)
        with cls.project.write_transaction() as conn:
            if store.get(key, version=cls.v1.uid, conn=conn) is None:
                store.create(conn, key, text, kind="ADOPTADO", source="Prueba de la T23",
                             source_kind="person", decided_by="Samuel (IMGA)",
                             reason="Dependencia declarada", version=cls.v1.uid)
            else:
                store.change(conn, key, value=text, version=cls.v1.uid, reason="Prueba de la T23")

    def refused(self, code: str, text: str, target: str, reason: str) -> None:
        """Declarar ``text`` en ``code`` y recalcularla se rechaza (``des.entity_supports_unknown``, con la
        entidad a la que apunta y el motivo) **sin escribir nada**."""
        self.declare(code, text)
        before = self.written()
        uid = self.current(code)
        with self.assertRaises(DesignError) as caught:
            design_store.recompute_run(self.request_for(uid))
        self.assertEqual(caught.exception.code, "des.entity_supports_unknown")
        self.assertEqual(caught.exception.values["target"], target)
        self.assertIn(reason, caught.exception.values["reason"])
        self.assertIn(target, caught.exception.text)
        self.assertEqual(self.written(), before)

    def test_c_a_declared_dependency_is_registered_with_zero_cubic_metres(self) -> None:
        """RF-015-15, D-11, CE-015-01 («detectada y declarada»): el taller declara que se apoya en P1, con la
        que no comparte ni un metro de huella: al recalcularlo se registra la dependencia (la superficie y
        la huella de P1 como entradas) y la cifra **con 0 m³**; lo que estaba declarado lo lee su parámetro y
        queda anotado en los parámetros de la operación (y, desde entonces, cambiarlo la deja obsoleta)."""
        self.declare("PLT-003", "PLT-001")
        self.assertEqual(entity_store.declared_supports(self.project, self.v1, "PLT-003"), ("PLT-001",))
        old = self.current("PLT-003")
        self.assertEqual(self.supports_of(old), [])
        self.assertEqual(self.stale_causes(old), set(), "no leía lo declarado: una fila nueva no la marca")
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(old))
        finish(work)
        self.assertEqual(self.supports_of(handle.uid),
                         [(PSF1, "supported_on"), (EPR1, "support_footprint")])
        self.assertEqual(self.volumes_of(handle.uid), {"PLT-001": 0.0})
        scope = figures_mod.scope_json(provenance.entity_figure_scope(WORKSHOP, "PLT-001"))
        self.assertEqual(self.figures_of(handle.uid)[("des.supported_m3", scope)], 0.0)
        read = [key for (key,) in self.query("SELECT p.key FROM gb_operation_param AS op JOIN gb_parameter "
                                             "AS p ON p.uid = op.parameter_uid WHERE op.operation_uid = ?",
                                             handle.uid)]
        self.assertIn(self.WORKSHOP_KEY, read)
        self.declare("PLT-003", "PLT-002")  # desde que lo lee, cambiar lo declarado la deja obsoleta
        self.assertIn(("parameter_changed", self.WORKSHOP_KEY), self.stale_causes(handle.uid))

    def test_c_what_does_not_exist_is_the_entity_itself_or_would_be_a_cycle_is_refused(self) -> None:
        """RF-015-15: declarar una entidad que no existe (PLT-009), la propia (PLT-003) o una que parte de la
        superficie de la que declara (P1 en P2: P2 parte de la de P1, sería un ciclo) se rechaza con la
        entidad, el campo, lo declarado y el motivo, sin escribir nada."""
        self.refused("PLT-003", "PLT-009", "PLT-009", "no existe")
        self.refused("PLT-003", "PLT-003", "PLT-003", "propia")
        self.refused("PLT-001", "PLT-002", "PLT-002", "ciclo")


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


class ThicknessRecomputeTest(ThicknessCase):
    """RF-015-15, ADR-0030 §4: al recalcular con otro espesor mínimo se **vuelve a medir** (no se copia lo
    anterior) y la dependencia que ya tenía se queda (una operación hecha es inmutable)."""

    second: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.second = cls.made(over())

    def test_c_recomputing_with_a_thicker_minimum_measures_zero_and_keeps_the_dependency(self) -> None:
        """RF-015-15: P2 se apoya en P1 con 8.000 m³; el espesor mínimo pasa a 2,1 m (la deja obsoleta por ese
        parámetro) y, recalculada, la operación nueva sigue teniendo la superficie y la huella de P1 como
        entradas (lo que apoyaba se arrastra) pero con **0 m³** medidos de nuevo: ni los 8.000 de antes ni
        una dependencia que desaparece."""
        first = self.second.handle.uid
        self.assertLessEqual(abs(self.volumes_of(first)["PLT-001"] - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        self.thickness(2.1)
        self.assertIn(("parameter_changed", self.KEY), self.stale_causes(first))
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(first))
        finish(work)
        self.assertEqual(self.supports_of(handle.uid),
                         [(PSF1, "supported_on"), (EPR1, "support_footprint")])
        self.assertEqual(self.volumes_of(handle.uid), {"PLT-001": 0.0})


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


class FillOnlySupportsTest(FillOnlyCase):
    """RF-015-15, D-11 (y, sin entidades, la 013 y la 014 como antes): sobre la cantera de la 014, con el diseño
    «solo relleno» «Balsa» creado **antes** de que la versión tenga entidades (el gancho ni se llama: la
    versión no tiene ninguna), la «Plataforma de la balsa» (corta a 255 m, en la lámina de agua) y «Balsa 2»,
    que rellena sobre su huella y se apoya en ella."""

    before_stored: ClassVar[Any]
    after_stored: ClassVar[Any]
    twin_request: ClassVar[Any]
    had_entities: ClassVar[tuple[bool, bool]]
    revision: ClassVar[str]
    recomputed: ClassVar[Any] = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()
        first = cls.exists()
        with mock.patch.object(entity_store, "survey_supports",
                               side_effect=AssertionError("sin entidades, el gancho ni se llama")):
            cls.before_stored = cls.fill(fill_test.REQUEST)
        cls.made(asked(BALSA))
        cls.had_entities = (first, cls.exists())
        cls.twin_request = model.FillOnlyRequest("Balsa 2", fill_test.ENVELOPE, fill_test.START,
                                                 fill_test.REST.code, water=fill_test.WATER)
        cls.after_stored = cls.fill(cls.twin_request)

    def test_a_without_entities_nothing_changes_and_the_hook_is_not_even_called(self) -> None:
        """RF-015-15 (coste cero): la versión sin entidades no paga el gancho (una consulta: ``_has_entities``
        es falso antes de crear la plataforma y verdadero después) y «Balsa», creada así, queda como antes: sin
        entradas ``supported_on`` ni ``support_footprint`` y sin la cifra ``des.supported_m3``; sus entradas
        son las de «solo relleno» (``fill_only_inputs``) y sus cifras, las del diseño."""
        self.assertEqual(self.had_entities, (False, True))
        uid = self.before_stored.handle.uid
        self.assertEqual(self.supports_of(uid), [])
        self.assertEqual(self.volumes_of(uid), {})
        roles = {role for (role,) in self.query(
            "SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in'", uid)}
        self.assertIn("surface", roles)
        self.assertIn("envelope", roles)
        self.assertFalse(roles & {"supported_on", "support_footprint"})
        keys = {key for (key,) in self.query("SELECT key FROM gb_figure WHERE operation_uid = ?", uid)}
        self.assertIn("des.fill_m3", keys)
        self.assertNotIn("des.supported_m3", keys)

    def test_b_a_fill_only_that_fills_over_the_footprint_of_a_platform_rests_on_it(self) -> None:
        """RF-015-15, D-11: «Balsa 2» (de la ladera, sin cortar nada, rellena la lámina a 270 m) deja la
        superficie de la plataforma de la balsa (a 255 m, bajo la ladera de 267 a 271 m) con el relleno sobre
        el terreno en ella: se apoya en la plataforma, con la superficie y la huella como entradas y los m³ de
        ``r − máx(s, e)`` sobre su huella (el cálculo a mano de los ficheros, a ≤ 10⁻⁹ relativo)."""
        uid = self.after_stored.handle.uid
        psf, epr = provenance.dataset_name("psf", BALSA), provenance.dataset_name("epr", BALSA)
        self.assertEqual(self.supports_of(uid), [(psf, "supported_on"), (epr, "support_footprint")])
        found = self.volumes_of(uid)
        self.assertEqual(list(found), ["PLT-001"])
        oracle = self.by_hand(provenance.dataset_name("srf", "Balsa 2"), qfx.terrain(self.grid), psf, epr)
        self.assertGreater(oracle, 100.0)
        self.assertLessEqual(abs(found["PLT-001"] - oracle) / oracle, 1e-9)
        scope = figures_mod.scope_json(provenance.entity_figure_scope("Balsa 2", "PLT-001"))
        self.assertEqual(self.figures_of(uid)[("des.supported_m3", scope)], found["PLT-001"])

    @classmethod
    def recompute_older(cls) -> Any:
        """Recalcula «Balsa» —el «solo relleno» creado **antes** de la entidad— con ``recompute_run``, una vez por
        clase (los dos casos que la usan no dependen de su orden): su ``OperationHandle``, ya completa."""
        if cls.recomputed is None:
            older = cls.before_stored.handle.uid
            ((settings,),) = cls.query_of("SELECT settings FROM gb_operation WHERE uid = ?", older)
            cls.clock.advance(minutes=1)
            handle, work = design_store.recompute_run(recompute_mod.RecomputeRequest(
                cls.project, older, provenance.FILL_ONLY, json.loads(settings), (), (), version=cls.v1.uid))
            fill_test.drive(work)
            cls.recomputed = handle
        return cls.recomputed

    def test_c_recomputing_the_fill_only_keeps_what_it_rested_on(self) -> None:
        """RF-015-15, ADR-0030 §4: recalcular «Balsa 2» arrastra la superficie y la huella de la plataforma y
        mide otra vez lo apoyado (el mismo, nada cambió)."""
        old = self.after_stored.handle.uid
        settings = json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?", old)[0][0])
        before = self.volumes_of(old)
        self.clock.advance(minutes=1)
        request = recompute_mod.RecomputeRequest(self.project, old, provenance.FILL_ONLY, settings, (), (),
                                                 version=self.v1.uid)
        handle, work = design_store.recompute_run(request)
        fill_test.drive(work)
        self.assertEqual(self.supports_of(handle.uid), self.supports_of(old))
        self.assertEqual(self.volumes_of(handle.uid), before)

    def test_c_recomputing_a_fill_only_made_before_the_entity_gains_the_dependency(self) -> None:
        """RF-015-15, ADR-0030 §4, CE-015-01 (C-1, error 59): «Balsa», creada **antes** de la plataforma, rellena
        sobre su huella como «Balsa 2» y, **al recalcularse**, gana la dependencia (antes no: la operación ya
        empezada no admitía entradas nuevas): la superficie y la tabla de la huella de P1 como entradas, con
        el hash que tenían y el volumen del cálculo a mano (≤ 10⁻⁹ relativo), y la cifra con el ámbito de P1.
        Lo que se le apoya a P1 y lo que lista descartarla son ya las dos, y la dependencia es la de «Crear»:
        la misma que registraría una operación calculada después."""
        before = self.before_stored.handle.uid
        self.assertEqual(self.supports_of(before), [], "creada sin entidades: sin dependencia")
        handle = self.recompute_older()
        new = handle.uid
        self.assertNotEqual(new, before)
        psf, epr = provenance.dataset_name("psf", BALSA), provenance.dataset_name("epr", BALSA)
        self.assertEqual(self.supports_of(new), [(psf, "supported_on"), (epr, "support_footprint")])
        found = self.volumes_of(new)
        self.assertEqual(list(found), ["PLT-001"])
        oracle = self.by_hand(provenance.dataset_name("srf", "Balsa"), qfx.terrain(self.grid), psf, epr)
        self.assertGreater(oracle, 100.0)
        self.assertLessEqual(abs(found["PLT-001"] - oracle) / oracle, 1e-9)
        scope = figures_mod.scope_json(provenance.entity_figure_scope("Balsa", "PLT-001"))
        self.assertEqual(self.figures_of(new)[("des.supported_m3", scope)], found["PLT-001"])
        marked = self.query(
            "SELECT d.name, io.role, io.content_sha256 = d.content_sha256 FROM gb_operation_io AS io "
            "JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "AND io.role IN ('supported_on', 'support_footprint') ORDER BY io.fid", new)
        self.assertEqual([(name, role) for name, role, _same in marked],
                         [(psf, "supported_on"), (epr, "support_footprint")])
        self.assertTrue(all(same for _name, _role, same in marked), "con el hash que tienen ahora")
        listed = entities.dependents(self.project, self.v1.uid, "PLT-001")
        self.assertEqual(sorted(item.name for item in listed), ["Balsa", "Balsa 2"])
        self.assertEqual({item.name: item.state for item in listed},
                         {"Balsa": entities.EntityState.CURRENT, "Balsa 2": entities.EntityState.CURRENT})
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        self.assertEqual(sorted(item.name for item in plan.dependents), ["Balsa", "Balsa 2"])
        listed_volume = {item.name: item.volume_m3 for item in plan.dependents}
        self.assertEqual(listed_volume["Balsa"], found["PLT-001"])
        self.assertEqual(self.current_fill_of("Balsa"), new, "es la operación vigente de «Balsa»")

    def test_d_reproducing_the_frozen_fill_only_gives_the_supported_volume_too(self) -> None:
        """RF-015-15, RF-009-11: congelada V01, la reproducción de «Balsa 2» da la misma cifra de lo apoyado
        (desde la superficie de partida y la superficie y la huella congeladas de la plataforma) y todo igual;
        también la de «Balsa», recalculada con su dependencia nueva (C-1)."""
        late = self.recompute_older().uid
        self.clock.advance(minutes=1)
        frozen = fill_test.drive(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega")).result
        revision = str(frozen.frozen.uid)
        self.clock.advance(minutes=1)
        report = fill_test.drive(reproduce_mod.reproduce_steps(self.project, revision)).result
        for uid in (self.current_fill_of("Balsa 2"), late):
            with self.subTest(operation=uid):
                found = [check for check in report.figures if check.operation_uid == uid
                         and check.key == "des.supported_m3"]
                self.assertEqual(len(found), 1)
                self.assertTrue(found[0].same, found)
                self.assertTrue(all(check.same for check in report.figures if check.operation_uid == uid))
        self.assertTrue(report.matches, report.not_reproducible)


class LateSupportTest(FillOnlyCase):
    """RF-015-15, RF-015-16, RF-015-17, CE-015-01 (C-1, el patrón del error 59), por el camino de la persona
    («Recalcular lo obsoleto»): «Balsa», un «solo relleno», se creó **antes** de que existiera la plataforma P1
    y «Balsa 2», después; las dos rellenan lo mismo sobre su huella. En el orden de las pruebas: (a) lo que se le
    apoya a P1 antes, (b) tras cambiar la altura de banco y repetir las dos, (c) la cascada desde P1 y (d)
    descartarla."""

    old: ClassVar[Any]
    twin: ClassVar[Any]
    HEIGHT_KEY: ClassVar[str] = design_params.bench_key(fill_test.REST.code, "height_m")
    FILLED_M3: ClassVar[float] = 936.0
    """A mano, con la altura de banco 0,5 m mayor (la sonda de la verificación): lo que rellenan las dos sobre
    la huella de P1."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()
        cls.old = cls.fill(fill_test.REQUEST)  # «Balsa»: antes de que exista ninguna entidad
        cls.made(asked(BALSA))
        cls.twin = cls.fill(model.FillOnlyRequest("Balsa 2", fill_test.ENVELOPE, fill_test.START,
                                                  fill_test.REST.code, water=fill_test.WATER))

    def listed(self) -> dict[str, float | None]:
        """Lo que se le apoya a P1 (``dependents``), por nombre, con su volumen."""
        return {item.name: item.volume_m3 for item in entities.dependents(self.project, self.v1.uid, "PLT-001")}

    def test_a_before_recalculating_only_the_design_made_after_the_entity_rests_on_it(self) -> None:
        """RF-015-15 (la premisa de C-1): «Balsa» no tiene la dependencia (se creó sin entidades) y solo «Balsa 2»
        figura entre lo que se le apoya a P1 y entre lo que lista descartarla."""
        self.assertEqual(list(self.listed()), ["Balsa 2"])
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        self.assertEqual([item.name for item in plan.dependents], ["Balsa 2"])
        self.assertEqual(self.supports_of(self.old.handle.uid), [])

    def test_a_if_the_entity_changes_while_it_is_measured_the_recompute_fails_and_registers_nothing(self) -> None:
        """RF-015-15, RF-013-17 (como ``des.input_changed`` al empezar una operación): si el dato de la entidad cambia
        entre que se mide el resultado y se anota la dependencia, la medida ya no le corresponde: el recálculo
        falla con ``des.input_changed``, nombrando el dato, y no deja ni la dependencia, ni la cifra, ni la
        operación como buena (la anterior sigue vigente)."""
        older = self.old.handle.uid
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", older)
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(recompute_mod.RecomputeRequest(
            self.project, older, provenance.FILL_ONLY, json.loads(settings), (), (), version=self.v1.uid))
        psf = provenance.dataset_name("psf", BALSA)
        genuine = self.record(psf, self.v1).content_sha256
        measure = design_store._seen

        def changed(conn: Any, uses: Any, version: Any) -> Any:
            found = measure(conn, uses, version)
            with self.project.write_transaction() as writing:  # alguien cambia la superficie de P1 justo después
                writing.execute("UPDATE gb_dataset SET content_sha256 = ? WHERE name = ?", ("0" * 64, psf))
            return found

        try:
            with mock.patch.object(design_store, "_seen", changed), self.assertRaises(DesignError) as caught:
                fill_test.drive(work)
        finally:
            with self.project.write_transaction() as writing:
                writing.execute("UPDATE gb_dataset SET content_sha256 = ? WHERE name = ?", (genuine, psf))
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(psf, caught.exception.text)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", handle.uid), [("failed",)])
        self.assertEqual(self.supports_of(handle.uid), [])
        self.assertEqual(self.volumes_of(handle.uid), {})
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", older), [(None,)])

    def test_b_recalculating_the_stale_registers_the_dependency_of_the_older_design_too(self) -> None:
        """RF-015-15, RF-015-17, CE-015-01 (C-1): tras cambiar la altura de banco, «Recalcular lo obsoleto» repite
        las dos (ninguna falla) y lo que se le apoya a P1 y lo que lista descartarla son **las dos**, cada una con
        sus metros cúbicos del cálculo a mano (≤ 10⁻⁹ relativo; 936 m³ las dos, como midió la sonda), no solo
        la que se creó después."""
        self.change(self.HEIGHT_KEY, fill_test.REST.height_m + 0.5)
        self.assertEqual(self.recompute_plan(), [(provenance.FILL_ONLY,), (provenance.FILL_ONLY,)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([(str(result.status), result.unit.op_types) for result in outcome.results],
                         [("done", (provenance.FILL_ONLY,))] * 2)
        psf, epr = provenance.dataset_name("psf", BALSA), provenance.dataset_name("epr", BALSA)
        terrain = qfx.terrain(self.grid)
        found = self.listed()
        self.assertEqual(sorted(found), ["Balsa", "Balsa 2"])
        for name in ("Balsa", "Balsa 2"):
            with self.subTest(design=name):
                oracle = self.by_hand(provenance.dataset_name("srf", name), terrain, psf, epr)
                self.assertLessEqual(abs(oracle - self.FILLED_M3) / self.FILLED_M3, 1e-9)
                self.assertLessEqual(abs(found[name] - oracle) / oracle, 1e-9)
                self.assertEqual(self.supports_of(self.current_fill_of(name)),
                                 [(psf, "supported_on"), (epr, "support_footprint")])
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        self.assertEqual({item.name: item.volume_m3 for item in plan.dependents}, found)

    def test_c_changing_the_entity_leaves_both_designs_stale_with_their_cause(self) -> None:
        """RF-015-16, RF-008-24 (C-1): con la dependencia registrada, cambiar la cota de P1 deja obsoletas las dos
        (en cascada: antes, «Balsa» quedaba al día aunque rellenaba sobre ella)."""
        names = ("Balsa", "Balsa 2")
        self.assertEqual([self.stale_causes(self.current_fill_of(name)) for name in names], [set(), set()])
        self.change(design_params.entity_key("PLT-001", "start_level_m"), 254.0)
        for name in names:
            with self.subTest(design=name):
                self.assertNotEqual(self.stale_causes(self.current_fill_of(name)), set())

    def test_d_discarding_the_entity_leaves_both_designs_in_support_removed(self) -> None:
        """RF-015-17 (C-1, error 59): descartar P1 deja en «apoyo retirado» a las dos, no solo a «Balsa 2»."""
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "PLT-001", reason="La balsa no se hace",
                                    decided_by="Samuel (IMGA)")
        self.assertEqual(sorted((item.name, item.op_type) for item in entities.retired_supports(
            self.project, self.v1.uid)), [("Balsa", provenance.FILL_ONLY), ("Balsa 2", provenance.FILL_ONLY)])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
