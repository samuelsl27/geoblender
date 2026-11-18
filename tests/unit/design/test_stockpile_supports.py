# SPDX-License-Identifier: GPL-3.0-or-later
"""Los acopios apoyables (spec 016, T15; HU-016-2; RF-016-14 —la parte de «se apoya»—, RF-015-15, RF-015-17; plan 016 §5.2.3
«Dependencias» y §5.4 A13, P-1; ADR-0031 §4): el cálculo puro, sin proyecto.

Una detección es **una** entidad (``STK-001``) y cada acopio, una fila suya identificada por la clave de su marca (P-1): lo que
una operación apoya sobre ella se mide **por acopio**, con la misma regla de la 015 (A6) sobre la huella de cada fila y la
superficie con que se detectó (``des_stp_``, la misma para todos los acopios de la detección):

    a(c) = r(c) − máx(s(c), e(c))    en las celdas c de la huella de cada acopio,

y la referencia de un acopio es ``STK-001#m07`` (la detección y su clave). Aquí, ``detect_supports`` y ``strongest`` con esas
referencias (un :class:`~design.entities.Support` por acopio, con su clave), la cifra ``des.supported_m3`` con el código de la
detección y la clave del acopio en su ámbito, y que lo de la 015 (una plataforma) sale **igual** que antes. Lo que lee el
proyecto (el gancho de ``DesignWriter.commit``, la lista de lo que se apoya en un acopio, reproducir) está en
``milestone_stockpile_supports.py`` (rejilla de 2 m con proyecto: paso «hito», P-13).
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

entities = import_geoblender("design.entities")
provenance = import_geoblender("design.provenance")

CELL_M2 = 4.0
THICKNESS_M = 0.02
"""El espesor mínimo de la 012 por defecto (ADOPTADO «sin confirmar»)."""
SHAPE = (6, 8)
CODE = "STK-001"
FIRST, SECOND = "m01", "m02"
"""Las claves de los dos acopios de las pruebas (las de sus marcas)."""


def ref(key: str, code: str = CODE) -> str:
    """La referencia de un acopio (``STK-001#m01``)."""
    return f"{code}#{key}"


def runs(*items: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Los índices de una huella dada en tramos ``(fila, col0, col1)``."""
    return entities.runs_cells(items)


def flat(value: float) -> np.ndarray:
    return np.full(SHAPE, float(value))


def footprints() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Dos acopios de la misma detección: ``m01`` (filas 0 y 1, columnas 0 a 3: 8 celdas) y ``m02`` (filas 4 y 5, columnas 4 a 7:
    8 celdas), disjuntos, en el orden de su tabla."""
    return {ref(FIRST): runs((0, 0, 4), (1, 0, 4)), ref(SECOND): runs((4, 4, 8), (5, 4, 8))}


def detected(top: float = 100.0) -> np.ndarray:
    """``des_stp_``: la superficie con que se detectó, **solo en las huellas** (NaN fuera), igual a la de partida (``top``)."""
    found = np.full(SHAPE, np.nan)
    for rows, cols in footprints().values():
        found[rows, cols] = top
    return found


def raised(base: np.ndarray, by: float, *keys: str) -> np.ndarray:
    """``base`` con ``by`` m más en la huella de cada acopio de ``keys``."""
    found = base.copy()
    for key in keys:
        rows, cols = footprints()[ref(key)]
        found[rows, cols] += by
    return found


def surfaces(top: float = 100.0) -> dict[str, np.ndarray]:
    """La superficie de cada acopio: la misma ``des_stp_`` de la detección, no una copia por acopio."""
    shared = detected(top)
    return {name: shared for name in footprints()}


def detect(result: np.ndarray, start: np.ndarray, **options: object) -> tuple[object, ...]:
    thickness = options.pop("thickness", THICKNESS_M)
    return entities.detect_supports(result, start, surfaces(), footprints(), thickness, CELL_M2, **options)  # type: ignore[arg-type]


class DetectStockpileSupportsTest(unittest.TestCase):
    """RF-016-14, RF-015-15, P-1 (A13): ``detect_supports`` con la superficie de la detección y la huella de cada acopio, un
    ``Support`` por clave."""

    def test_a_a_fill_on_one_stockpile_rests_on_that_one_by_its_key_with_the_volume_by_hand(self) -> None:
        """RF-016-14, RF-015-15, P-1: una operación que parte de la superficie con acopios y sube 2,5 m las 8 celdas de ``m01`` apoya
        ``8 · 2,5 · 4 = 80`` m³ **en ese acopio**, con su clave; ``m02`` (que no toca) no sale: con dos acopios, nombra solo uno."""
        start = flat(100.0)
        found = detect(raised(start, 2.5, FIRST), start.copy())
        self.assertEqual(found, (entities.Support(CODE, 8, 80.0, False, FIRST),))
        self.assertEqual(found[0].ref, ref(FIRST))  # type: ignore[attr-defined]

    def test_a_each_stockpile_has_its_own_support_in_the_order_of_its_table(self) -> None:
        """RF-016-14, P-1: sobre los dos acopios, dos ``Support`` (``m01`` y ``m02``) con su volumen cada uno —un acopio por cada
        clave—, en el orden de la tabla de la detección, no mezclados en uno solo (sin la clave, las cifras de dos acopios se
        confundirían)."""
        start = flat(100.0)
        result = raised(raised(start, 2.5, FIRST), 1.0, SECOND)
        self.assertEqual(detect(result, start.copy()),
                         (entities.Support(CODE, 8, 80.0, False, FIRST), entities.Support(CODE, 8, 32.0, False, SECOND)))

    def test_a_the_ground_of_a_stockpile_is_max_of_the_start_and_its_surface(self) -> None:
        """RF-016-14, P-5 de la 015 (A6): con la superficie de partida **por debajo** de la del acopio (``s = 97``, ``e = 100``), solo
        cuenta lo que sube por encima de ``e``: ``r = 101,5`` es ``a = 1,5`` (``8 · 1,5 · 4 = 48`` m³) y un ``r = 99`` no apoya nada;
        con el terreno **por encima** (``s = 106``), cuenta sobre el terreno (``r = 107,5``, también 48 m³)."""
        below = flat(97.0)
        found = detect(raised(below, 4.5, FIRST), below.copy())  # r = 101,5
        self.assertEqual(found, (entities.Support(CODE, 8, 48.0, False, FIRST),))
        self.assertEqual(detect(raised(below, 2.0, FIRST), below.copy()), ())  # r = 99: bajo la superficie del acopio
        above = flat(106.0)
        found = detect(raised(above, 1.5, FIRST), above.copy())
        self.assertEqual(found, (entities.Support(CODE, 8, 48.0, False, FIRST),))

    def test_a_dragging_the_ground_over_a_stockpile_is_not_support(self) -> None:
        """RF-016-14, RF-015-15: lo que solo **arrastra** la superficie de partida (``r = s``, sin subir nada) no se apoya en ningún
        acopio; lo que no sube más del espesor mínimo (``a`` igual a él, 0,02 m, y justo por debajo) tampoco; justo por encima, sí."""
        start = flat(100.0)
        self.assertEqual(detect(start.copy(), start), ())
        tiny = 2.0 ** -30
        for by, cells in ((THICKNESS_M + tiny, 8), (THICKNESS_M, 0)):
            with self.subTest(by=by):
                found = detect(raised(start, by, FIRST), start.copy())
                self.assertEqual(sum(item.cells for item in found), cells)  # type: ignore[attr-defined]

    def test_a_cells_without_data_do_not_count_or_poison_the_sum(self) -> None:
        """RF-016-14: ``des_stp_`` es **dispersa** (NaN fuera de las huellas) y una celda sin dato en la superficie resultante o en la
        de partida no cuenta (el volumen de las demás sale finito): 8 − 2 = 6 celdas de 2 m de relleno y 4 m² = 48 m³."""
        start = flat(100.0)
        result = raised(start, 2.0, FIRST)
        result[0, 0] = np.nan
        start[1, 3] = np.nan
        found = detect(result, start)
        self.assertEqual(found, (entities.Support(CODE, 6, 48.0, False, FIRST),))
        self.assertTrue(math.isfinite(found[0].volume_m3))  # type: ignore[attr-defined]

    def test_a_what_the_user_declares_comes_out_with_zero_and_what_does_not_rest_does_not(self) -> None:
        """RF-015-15, D-11: un acopio **declarado** sale siempre (con 0 m³ si no se le apoya nada); uno que no se apoya y no se declaró,
        no; un acopio declarado que no está en las huellas es un error del programa (``KeyError``)."""
        start = flat(100.0)
        self.assertEqual(detect(start.copy(), start.copy(), declared=(ref(SECOND),)),
                         (entities.Support(CODE, 0, 0.0, True, SECOND),))
        found = detect(raised(start, 1.0, FIRST), start.copy(), declared=(ref(FIRST), ref(SECOND)))
        self.assertEqual(found, (entities.Support(CODE, 8, 32.0, True, FIRST), entities.Support(CODE, 0, 0.0, True, SECOND)))
        with self.assertRaises(KeyError):
            detect(start.copy(), start.copy(), declared=(ref("m99"),))

    def test_a_the_volume_is_the_hand_sum_to_a_billionth(self) -> None:
        """CE-016-04, RF-015-15 (D-9): con espesores irregulares (de 0 a 3 m) sobre dos acopios de 3.000 celdas de 6,25 m², el volumen de
        cada uno es la suma a mano (``math.fsum`` celda a celda) a ≤ 10⁻⁹ relativo y las celdas, las que pasan del espesor mínimo."""
        generator = np.random.default_rng(16)
        shape = (80, 90)
        start = 200.0 + generator.random(shape) * 5.0
        ground = np.full(shape, np.nan)
        marks: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for key, low in ((FIRST, 0), (SECOND, 40)):
            cells = np.unique(np.stack([generator.integers(low, low + 40, 3000), generator.integers(0, 90, 3000)], axis=1), axis=0)
            marks[ref(key)] = (cells[:, 0], cells[:, 1])
            ground[cells[:, 0], cells[:, 1]] = start[cells[:, 0], cells[:, 1]] - generator.random(len(cells)) * 2.0 \
                + generator.random(len(cells)) * 2.0
        result = start + generator.random(shape) * 3.0 - 0.1
        found = entities.detect_supports(result, start, {name: ground for name in marks}, marks, THICKNESS_M, 6.25)
        self.assertEqual([item.stockpile for item in found], [FIRST, SECOND])
        for item in found:
            rows, cols = marks[item.ref]
            thick = [result[r, c] - max(start[r, c], ground[r, c]) for r, c in zip(rows, cols, strict=True)]
            counted = [value for value in thick if value > THICKNESS_M]
            self.assertEqual(item.cells, len(counted))
            self.assertGreater(len(counted), 1000)
            self.assertLessEqual(abs(item.volume_m3 - math.fsum(counted) * 6.25) / item.volume_m3, 1e-9)

    def test_a_a_platform_and_a_stockpile_sort_by_code_and_the_platform_has_no_key(self) -> None:
        """RF-015-15 (no cambia la 015): una plataforma (``PLT-001``) y un acopio (``STK-001#m01``) en una misma operación salen por orden de
        código, la plataforma **sin** clave de acopio (``stockpile`` ``None``: el ``Support`` de la 015, igual que antes) y el acopio
        con ella; ``PLT-002`` va antes que ``PLT-010``."""
        base = flat(100.0)
        result = base.copy()
        result[0, 0:3] = 103.0  # sobre PLT-010: 3 celdas · 3 m · 4 m² = 36 m³
        result[5, 4:8] = 101.0  # sobre PLT-002: 4 celdas · 1 m · 4 m² = 16 m³
        result[1, 0:4] = 102.0  # sobre el acopio m01: 4 celdas · 2 m · 4 m² = 32 m³
        found = entities.detect_supports(
            result, base,
            {"PLT-010": base, "PLT-002": base, ref(FIRST): base},
            {"PLT-010": runs((0, 0, 3)), "PLT-002": runs((5, 4, 8)), ref(FIRST): runs((1, 0, 4))},
            THICKNESS_M, CELL_M2)
        self.assertEqual(found, (entities.Support("PLT-002", 4, 16.0, False), entities.Support("PLT-010", 3, 36.0, False),
                                 entities.Support(CODE, 4, 32.0, False, FIRST)))
        self.assertIsNone(found[0].stockpile)
        self.assertEqual(found[0].ref, "PLT-002")

    def test_a_the_arguments_are_checked(self) -> None:
        """Errores del programa: un acopio de las huellas sin superficie (``KeyError``) o con una superficie de otra forma
        (``ValueError``)."""
        start = flat(100.0)
        only_one = {ref(FIRST): detected()}
        with self.assertRaises(KeyError):
            entities.detect_supports(raised(start, 1.0, FIRST), start, only_one, footprints(), THICKNESS_M, CELL_M2)
        with self.assertRaises(ValueError):
            entities.detect_supports(raised(start, 1.0, FIRST), start, {name: np.full((3, 3), 100.0) for name in footprints()},
                                     footprints(), THICKNESS_M, CELL_M2)


class StrongestStockpileTest(unittest.TestCase):
    """RF-016-14, RF-015-15 (A13): ``strongest`` agrupa **por clave**: de las superficies de una operación (alternativas) cuenta la
    que más apoya en cada acopio, y dos acopios de una detección no se funden en uno."""

    def test_a_two_stockpiles_of_one_detection_are_two_groups_and_each_keeps_its_strongest(self) -> None:
        """RF-016-14: de las dos superficies de una operación, el de mayor volumen de cada acopio (a igual volumen, el primero) y
        declarado si alguno lo era; los dos acopios de ``STK-001`` y la plataforma ``PLT-001`` son tres grupos, por orden de código y,
        dentro de la detección, en el orden en que vienen (el de su tabla)."""
        found = entities.strongest([
            entities.Support(CODE, 1, 2.0, True, FIRST), entities.Support(CODE, 4, 16.0, False, SECOND),
            entities.Support(CODE, 5, 9.0, False, FIRST), entities.Support(CODE, 2, 8.0, True, SECOND),
            entities.Support("PLT-001", 3, 6.0, False)])
        self.assertEqual(found, (entities.Support("PLT-001", 3, 6.0, False),
                                 entities.Support(CODE, 5, 9.0, True, FIRST), entities.Support(CODE, 4, 16.0, True, SECOND)))

    def test_a_the_same_code_without_key_and_with_key_are_not_the_same_group(self) -> None:
        """RF-015-15: lo de la 015 (sin clave) se agrupa como siempre (por código) y no se junta con un acopio del mismo código: el
        acopio es otra cosa que la entidad entera."""
        found = entities.strongest([entities.Support("PLT-002", 4, 16.0, False), entities.Support("PLT-001", 1, 2.0, True),
                                    entities.Support("PLT-001", 5, 9.0, False), entities.Support("PLT-002", 2, 8.0, True)])
        self.assertEqual(found, (entities.Support("PLT-001", 5, 9.0, True), entities.Support("PLT-002", 4, 16.0, True)))
        self.assertEqual(entities.strongest([]), ())


class SupportReferenceTest(unittest.TestCase):
    """P-1, ADR-0031: un acopio se cita por su detección y su clave (``STK-001#m07``)."""

    def test_a_the_reference_of_a_stockpile_and_its_parts(self) -> None:
        """P-1: ``support_ref`` junta la detección y la clave con ``#`` y ``split_support_ref`` la deshace por el **primer** ``#`` (el código
        de una entidad no lo lleva y la clave de una marca, que es su nombre, sí puede llevarlo); sin ``#``, es una entidad entera."""
        self.assertEqual(provenance.support_ref(CODE, "m07"), "STK-001#m07")
        self.assertEqual(provenance.split_support_ref("STK-001#m07"), (CODE, "m07"))
        self.assertEqual(provenance.split_support_ref(provenance.support_ref(CODE, "Acopio #4")), (CODE, "Acopio #4"))
        self.assertEqual(provenance.split_support_ref("PLT-001"), ("PLT-001", None))

    def test_a_a_blank_key_or_a_wrong_code_is_a_program_error(self) -> None:
        """P-1: una clave en blanco no cita ningún acopio, y un código que no es de una entidad tampoco (``ValueError``)."""
        for bad in ("", "  "):
            with self.subTest(key=bad), self.assertRaises(ValueError):
                provenance.support_ref(CODE, bad)
        with self.assertRaises(ValueError):
            provenance.support_ref("stk-1", "m01")
        with self.assertRaises(ValueError):
            provenance.split_support_ref("STK-001#")


class SupportedFiguresTest(unittest.TestCase):
    """RF-016-14, RF-015-15, RF-009-20: la cifra ``des.supported_m3`` de un acopio lleva en su ámbito la **entidad** (la detección) y la
    **clave del acopio**."""

    def test_a_the_scope_of_a_stockpile_has_the_detection_and_the_key(self) -> None:
        """RF-016-14, P-1 (RF-009-20: la vigente de una clave es la última de cada ámbito): ``supported_figures`` da, por orden, la cifra de
        cada acopio con su ámbito (el nombre de la operación, ``entity`` ``STK-001`` y ``stockpile``) y la de una plataforma, solo con
        ``entity`` (como antes); dos acopios de la misma detección **no** comparten ámbito."""
        found = provenance.supported_figures("Sobre el acopio", {"PLT-001": 8000.0, ref(SECOND): 32.0, ref(FIRST): 80.0})
        scopes = [(figure.key, dict(figure.scope), figure.value, figure.unit) for figure in found]
        self.assertEqual(scopes, [
            ("des.supported_m3", {"name": "sobre_el_acopio", "entity": "PLT-001"}, 8000.0, "m3"),
            ("des.supported_m3", {"name": "sobre_el_acopio", "entity": CODE, "stockpile": FIRST}, 80.0, "m3"),
            ("des.supported_m3", {"name": "sobre_el_acopio", "entity": CODE, "stockpile": SECOND}, 32.0, "m3")])
        self.assertEqual(len({tuple(sorted(figure.scope.items())) for figure in found}), 3)

    def test_a_a_negative_volume_is_a_program_error(self) -> None:
        """RF-015-15: un volumen que no es finito o es negativo no se registra (``ValueError``), también el de un acopio."""
        for bad in (-1.0, math.nan, math.inf):
            with self.subTest(volume=bad), self.assertRaises(ValueError):
                provenance.supported_figures("Op", {ref(FIRST): bad})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
