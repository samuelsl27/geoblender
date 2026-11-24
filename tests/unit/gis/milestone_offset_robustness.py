# SPDX-License-Identifier: GPL-3.0-or-later
"""La batería de robustez del desfase de la corta: el criterio del H1 (spec 018, T09; HU-018-1; RF-018-10; CE-018-01, CE-018-02;
plan 018 §5.8 H-1, §7.1, §8 y §11 S-1). Paso «hito» (P-16).

300 polilíneas rugosas de ``tests/support/pit_data.py`` (300 a 1.500 vértices, ruido radial de 0 a 0,8 m, semillas fijas), ascendentes y
descendentes, **con y sin roseta** (la de CE-018-02, con la ventana de azimut de la hipótesis), pasadas por ``design.pit_offset``
(distancia por arista + ``gis.offset``). El anillo se simplifica antes (A1, Douglas–Peucker) con ``simplify_m``; el motor verifica el
resultado contra el anillo simplificado (``simplify_m = 0``) y el **oráculo de fuerza bruta** (``tests/support/offset_oracle.py``, que
no usa el motor) lo comprueba contra el anillo **original**: simple, y cada vértice a ``≥ d_e − arco − simplify_m`` de **cada** arista ``e``
de él, con ``d_e`` la distancia que le toca a la arista (la menor de las aristas del anillo de trabajo a ``simplify_m`` de ella). Esa es la
definición del desfase con distancia por arista (T09b): el borde de la unión de las cápsulas de las aristas, donde la tapa de la de
mayor distancia pasa más cerca de una vecina de menor distancia (hasta ``d_mayor − d_menor``); la de la T09 (``d`` la menor de las del
vértice y sus dos vecinas) no la cumple ningún desfase correcto en un escalón de la roseta.

Dos regímenes de simplificación: ``noise`` (la simplificación igual al ruido del caso, con 0,05 m de mínimo: las condiciones en que el
plan midió el desfase de distancia constante, H-1) con los 300 casos, y ``fixed`` (0,05 m, la hipótesis de inv. 07 §3.4, **menor que
el ruido** en casi todos) con los 60 primeros.

**Criterio** (S-1): 0 resultados no simples y defecto de distancia ≤ arco + simplificación en lo que el desfase **da por bueno**; lo
que su verificación (A4) rechaza con diagnóstico no cuenta como no simple, pero se anota con su causa; y, con roseta, ningún rechazo
(``test_rose_cases_are_not_rejected``). La T09 midió 135 y 138 de 150 casos con roseta rechazados con el desfase de una sola curva; la
T09b (unión de losas, plan §5.4 A4) los acepta todos."""

from __future__ import annotations

import dataclasses
import math
import unittest
from collections import Counter
from typing import Any

import numpy as np

from tests.support import offset_oracle as oracle
from tests.support import pit_data as pd
from tests.support.package import import_geoblender

pit_offset = import_geoblender("design.pit_offset")
pit_rose = import_geoblender("design.pit_rose")
offset = import_geoblender("gis.offset")

H = pd.HYPOTHESES
ROSE = tuple(pit_rose.RoseRange(r.from_deg, r.to_deg, r.face_deg, r.berm_m) for r in pd.ROSE_TWO_RANGES)
MIN_SIMPLIFY_M = 0.05
FIXED_CASES = 60
SLACK_M = 1e-9
CAUSES = ("crossing", "distance")


@dataclasses.dataclass(frozen=True)
class Outcome:
    """Qué dio un caso: su verificación, el oráculo y, si el motor lo rechazó, la causa."""

    case: Any
    verified: bool
    cause: str
    located: bool
    crossings: int
    shortfall_m: float
    engine_defect_m: float


def simplify_for(regime: str, case: Any) -> float:
    return max(case.noise_m, MIN_SIMPLIFY_M) if regime == "noise" else H.simplify_m


def run_case(regime: str, case: Any) -> Outcome:
    """El desfase de un caso y su comprobación con el oráculo (contra el anillo original)."""
    simplify_m = simplify_for(regime, case)
    ring = offset.simplify_ring(case.ring, simplify_m)
    kwargs: dict[str, Any] = {"step": "face", "side": -1 if case.descending else 1, "profile": pd.EXPL,
                              "az_window_m": H.az_window_m}
    if case.with_rose:
        kwargs["rose"] = ROSE
    found = pit_offset.edge_distances(ring, **kwargs)
    last = None
    for step in pit_offset.offset_polyline_steps(ring, tol=H.arc_m, simplify_m=0.0, **kwargs):
        last = step.result
    assert last is not None
    result = last.result
    loops = list(result.rings) + list(result.holes)
    shortfall = 0.0
    limit = oracle.edge_limits(case.ring, found.ring, found.distance, simplify_m)
    limit = limit - H.arc_m - simplify_m
    for loop in loops:
        shortfall = max(shortfall, oracle.capsule_shortfall(loop, case.ring, limit, -1 if case.descending else 1))
    return Outcome(case, result.verified, result.defect, result.defect_at is not None,
                   oracle.crossing_count(loops), shortfall, result.max_defect_m)


_CACHE: dict[str, list[Outcome]] = {}


def outcomes(regime: str) -> list[Outcome]:
    if regime not in _CACHE:
        count = pd.ROUGH_CASES if regime == "noise" else FIXED_CASES
        _CACHE[regime] = [run_case(regime, pd.rough_case(index)) for index in range(count)]
    return _CACHE[regime]


def report(regime: str) -> str:
    """El informe: cuántos casos, cuántos rechazos y de qué causa, con y sin roseta, y el peor defecto."""
    rows = outcomes(regime)
    lines = [f"régimen {regime}: {len(rows)} casos"]
    for rose in (False, True):
        subset = [row for row in rows if row.case.with_rose == rose]
        rejected = [row for row in subset if not row.verified]
        causes = Counter(row.cause for row in rejected)
        worst = max((row.shortfall_m for row in rejected), default=0.0)
        lines.append(f"  {'con' if rose else 'sin'} roseta: {len(subset)} casos, {len(rejected)} rechazados {dict(causes)}, "
                     f"peor falta de distancia {worst:.3f} m")
    return "\n".join(lines)


class RobustnessTest(unittest.TestCase):
    def check_regime(self, regime: str) -> None:
        rows = outcomes(regime)
        for row in rows:
            label = (regime, row.case.index, row.case.vertices, round(row.case.noise_m, 2), row.case.descending, row.case.with_rose)
            if row.verified:
                self.assertEqual(row.crossings, 0, ("resultado dado por bueno y no simple", label))
                self.assertLessEqual(row.shortfall_m, SLACK_M, ("resultado dado por bueno y más cerca que d − arco − simplificación", label))
            else:
                self.assertIn(row.cause, CAUSES, ("rechazo sin causa", label))
                self.assertTrue(row.located, ("rechazo sin lugar", label))
        print("\n" + report(regime))

    def test_accepted_results_are_simple_and_within_tolerance_noise(self) -> None:
        """RF-018-10, CE-018-01, CE-018-02 (S-1): 300 casos con la simplificación igual al ruido: ninguno de los que el desfase da por
        buenos es no simple o queda a menos de d − arco − simplificación (oráculo de fuerza bruta contra el anillo original); cada
        rechazo lleva su causa (``crossing`` o ``distance``) y su lugar."""
        self.assertEqual(len(outcomes("noise")), pd.ROUGH_CASES)
        self.check_regime("noise")

    def test_accepted_results_are_simple_and_within_tolerance_fixed(self) -> None:
        """RF-018-10 (S-1): los 60 primeros casos con la simplificación de 0,05 m, menor que el ruido: lo mismo."""
        self.check_regime("fixed")

    def test_cases_without_rose_are_never_rejected_when_simplified_to_the_noise(self) -> None:
        """RF-018-10 (H-1): con distancia constante (sin roseta) y la simplificación igual al ruido, ningún caso de los 150 se rechaza."""
        rejected = [row.case.index for row in outcomes("noise") if not row.case.with_rose and not row.verified]
        self.assertEqual(rejected, [])

    def test_rose_cases_are_not_rejected(self) -> None:
        """RF-018-10 (S-1): el desfase con roseta de una línea rugosa sale verificado. Medido el 22/11/2026 con el desfase de una sola
        curva (T09): 135 de los 150 casos con roseta rechazados por ``distance`` con la simplificación igual al ruido y 138 con 0,05 m;
        con la unión de losas (T09b), ninguno."""
        rejected = [row.case.index for row in outcomes("noise") if row.case.with_rose and not row.verified]
        self.assertEqual(rejected, [], f"{len(rejected)} de {pd.ROUGH_CASES // 2} casos con roseta rechazados")


def sampled(ring: np.ndarray, step: float) -> np.ndarray:
    """El anillo con un vértice cada ≤ ``step`` m a lo largo de cada arista (vértices alineados)."""
    out = []
    for a, b in zip(ring, np.roll(ring, -1, axis=0), strict=True):
        n = max(1, round(float(np.hypot(*(b - a))) / step))
        out.extend(a + (b - a) * k / n for k in range(n))
    return np.array(out)


def rotated(ring: np.ndarray, angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return ring @ np.array([[c, s], [-s, c]])


L_SHAPE = np.array([(0, 0), (40, 0), (40, 20), (20, 20), (20, 40), (0, 40)], dtype=np.float64)
DUMBBELL = np.array([(0, 0), (30, 0), (30, 13), (50, 13), (50, 0), (80, 0), (80, 30), (50, 30), (50, 17), (30, 17), (30, 30), (0, 30)],
                    dtype=np.float64)
C_SHAPE = np.array([(0, 0), (40, 0), (40, 18), (30, 18), (30, 10), (10, 10), (10, 30), (30, 30), (30, 22), (40, 22), (40, 40), (0, 40)],
                   dtype=np.float64)


class AlignedVerticesRobustnessTest(unittest.TestCase):
    """T09c: anillos con **vértices alineados** (el contorno muestreado cada ≤ la distancia, que es lo que deja la densificación del primer
    banco, RF-018-12) y esquinas cóncavas, que la batería rugosa no cubre: un trozo del borde de una losa que va por la fuente lo
    clasificaba mal el rayo desde un punto sobre el borde. Con distancia constante, ningún caso se rechaza; con el escalón de la roseta,
    lo que se da por bueno es correcto."""

    @staticmethod
    def cases() -> list[tuple[str, np.ndarray]]:
        out = []
        for name, shape in (("L", L_SHAPE), ("dumbbell", DUMBBELL), ("C", C_SHAPE)):
            for degrees in (0.0, 7.0, 30.0, 45.0, 70.0):
                for step in (0.5, 1.0, 1.7, 3.0):
                    out.append((f"{name} {degrees:g}° cada {step:g} m", sampled(rotated(shape, math.radians(degrees)), step)))
        return out

    def run_ring(self, ring: np.ndarray, dist: np.ndarray, side: int, label: str) -> bool:
        result = offset.offset_ring(ring, dist, side, tol=H.arc_m)
        loops = list(result.rings) + list(result.holes)
        if result.verified:
            self.assertEqual(oracle.crossing_count(loops), 0, (label, side, "no simple"))
            for loop in loops:
                self.assertLessEqual(oracle.capsule_shortfall(loop, ring, dist - H.arc_m, side), SLACK_M, (label, side, "distancia"))
        return result.verified

    def test_constant_distance_is_never_rejected(self) -> None:
        rejected = []
        for label, ring in self.cases():
            for d in (3.0, 10.0):
                for side in (1, -1):
                    if not self.run_ring(ring, np.full(len(ring), d), side, label):
                        rejected.append((label, d, side))
        self.assertEqual(rejected, [])

    def test_stepped_distance_accepted_results_are_correct(self) -> None:
        """La roseta de dos rangos (5,77 y 10 m) en la mitad de cada anillo: lo dado por bueno es simple y está a la distancia."""
        done = 0
        for label, ring in self.cases():
            dist = np.where(np.arange(len(ring)) < len(ring) // 2, 5.77, 10.0)
            for side in (1, -1):
                done += int(self.run_ring(ring, dist, side, label))
        print(f"\ndistancia con escalón y vértices alineados: {done} de {2 * len(self.cases())} verificados")
        self.assertEqual(done, 2 * len(self.cases()), "T09d (DIFF-018k): el criterio cuenta solo el lado del desfase, ningún caso se rechaza")


class OneSidedCriterionRobustnessTest(unittest.TestCase):
    """T09d (DIFF-018k): semillas **nuevas** (no las de la T09, T09b ni T09c) con distancias distintas por arista y cuellos estrechos:
    ningún rechazo y ningún defecto con el oráculo de un solo lado. (1) Anillos rugosos de ``pit_data`` desde el índice 300 (semillas
    1300 a 1359), con y sin roseta, ascendentes y descendentes; (2) L, C y mancuerna giradas, con vértices alineados y distancias
    aleatorias (de 0,5 a 12 m, por tramos), semillas 7000 a 7039."""

    NEW_ROUGH = range(pd.ROUGH_CASES, pd.ROUGH_CASES + 60)
    NEW_SEEDS = range(7000, 7040)

    def test_new_rough_cases_are_verified_and_correct(self) -> None:
        rejected = []
        for index in self.NEW_ROUGH:
            case = pd.rough_case(index)
            row = run_case("noise", case)
            label = (index, case.vertices, round(case.noise_m, 2), case.descending, case.with_rose)
            if not row.verified:
                rejected.append((label, row.cause))
                continue
            self.assertEqual(row.crossings, 0, ("no simple", label))
            self.assertLessEqual(row.shortfall_m, SLACK_M, ("más cerca que d − arco − simplificación", label))
        self.assertEqual(rejected, [])

    @staticmethod
    def random_ring(seed: int, low: float, high: float) -> tuple[np.ndarray, np.ndarray]:
        rng = np.random.default_rng(seed)
        shapes = (L_SHAPE, DUMBBELL, C_SHAPE)
        ring = sampled(rotated(shapes[seed % 3], math.radians(float(rng.uniform(0.0, 90.0)))), float(rng.uniform(0.5, 3.0)))
        runs = int(rng.integers(2, 6))
        cut = np.sort(rng.integers(1, len(ring), runs))
        levels = rng.uniform(low, high, runs + 1)
        return ring, levels[np.searchsorted(cut, np.arange(len(ring)), side="right")]

    def run_ring(self, ring: np.ndarray, dist: np.ndarray, side: int, label: object) -> tuple[bool, Any]:
        """Verificado (con el oráculo de un solo lado: simple y a la distancia) o el resultado rechazado con su lugar y su causa."""
        result = offset.offset_ring(ring, dist, side, tol=H.arc_m)
        loops = list(result.rings) + list(result.holes)
        if not result.verified:
            self.assertIn(result.defect, CAUSES, (label, "rechazo sin causa"))
            self.assertIsNotNone(result.defect_at, (label, "rechazo sin lugar"))
            return False, result
        self.assertEqual(oracle.crossing_count(loops), 0, (label, "no simple"))
        for loop in loops:
            self.assertLessEqual(oracle.capsule_shortfall(loop, ring, dist - H.arc_m, side), SLACK_M, (label, "distancia"))
        return True, result

    def test_random_distances_within_the_rose_span_are_verified_and_correct(self) -> None:
        """Distancias aleatorias por tramos entre 5 y 10 m (la amplitud de una roseta: la de CE-018-02 va de 5,77 a 10 m) y cuellos de 4 m:
        80 desfases (40 semillas, fuera y dentro), ninguno rechazado y todos correctos."""
        rejected = []
        for seed in self.NEW_SEEDS:
            ring, dist = self.random_ring(seed, 5.0, 10.0)
            for side in (1, -1):
                if not self.run_ring(ring, dist, side, (seed, side))[0]:
                    rejected.append((seed, side))
        self.assertEqual(rejected, [])

    def test_extreme_random_distances_are_never_wrong_in_silence(self) -> None:
        """Distancias de 0,5 a 12 m (cocientes de hasta 24) con cuellos más estrechos que la mayor: lo que se da por bueno es correcto y lo
        que no, se rechaza con causa y lugar. Medido el 24/11/2026: 8 de 80 rechazados por ``distance`` (la unión de losas deja un hueco
        de ≈ 0,3 m² en un cuello cuando el cociente de distancias pasa de ≈ 2; ver el hallazgo de la T09d)."""
        rejected = 0
        for seed in self.NEW_SEEDS:
            ring, dist = self.random_ring(seed, 0.5, 12.0)
            for side in (1, -1):
                rejected += int(not self.run_ring(ring, dist, side, (seed, side))[0])
        print(f"\ndistancias extremas con cuellos: {rejected} de {2 * len(self.NEW_SEEDS)} rechazados con aviso")
        self.assertLess(rejected, len(self.NEW_SEEDS))


if __name__ == "__main__":
    unittest.main()
