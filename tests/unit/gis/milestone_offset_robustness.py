# SPDX-License-Identifier: GPL-3.0-or-later
"""La batería de robustez del desfase de la corta: el criterio del H1 (spec 018, T09; HU-018-1; RF-018-10; CE-018-01, CE-018-02;
plan 018 §5.8 H-1, §7.1, §8 y §11 S-1). Paso «hito» (P-16).

300 polilíneas rugosas de ``tests/support/pit_data.py`` (300 a 1.500 vértices, ruido radial de 0 a 0,8 m, semillas fijas), ascendentes y
descendentes, **con y sin roseta** (la de CE-018-02, con la ventana de azimut de la hipótesis), pasadas por ``design.pit_offset``
(distancia por arista + ``gis.offset``). El anillo se simplifica antes (A1, Douglas–Peucker) con ``simplify_m``; el motor verifica el
resultado contra el anillo simplificado (``simplify_m = 0``) y el **oráculo de fuerza bruta** (``tests/support/offset_oracle.py``, que
no usa el motor) lo comprueba contra el anillo **original**: simple, y cada vértice a ``≥ d − arco − simplify_m`` de él, con ``d`` la
menor distancia de las aristas de origen del vértice y de sus dos vecinas.

Dos regímenes de simplificación: ``noise`` (la simplificación igual al ruido del caso, con 0,05 m de mínimo: las condiciones en que el
plan midió el desfase de distancia constante, H-1) con los 300 casos, y ``fixed`` (0,05 m, la hipótesis de inv. 07 §3.4, **menor que
el ruido** en casi todos) con los 60 primeros.

**Criterio** (S-1): 0 resultados no simples y defecto de distancia ≤ arco + simplificación en lo que el desfase **da por bueno**; lo
que su verificación (A4) rechaza con diagnóstico no cuenta como no simple, pero se anota con su causa. Eso lo cumple la batería. **Lo que
no cumple** es la utilidad de ese desfase con una roseta: la gran mayoría de los casos con roseta los rechaza la verificación (el
escalón de distancia entre rangos deja puntos a menos de ``d``). Esa medición está en
``test_rose_cases_are_not_rejected``, que **falla a propósito** con las cifras (sin marcas: TST-07): **el criterio de robustez no está alcanzado y la T09 no se da por hecha** (S-1: el plan vuelve a
Samuel). El paso «hito» queda en rojo hasta que se mejore el desfase o se decida otra cosa."""

from __future__ import annotations

import dataclasses
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
    for loop, source in zip(loops, result.source_edge_of_vertex, strict=True):
        near = np.minimum(found.distance[source], np.minimum(np.roll(found.distance[source], 1), np.roll(found.distance[source], -1)))
        gap = oracle.distance_to_ring(loop, case.ring)
        shortfall = max(shortfall, float((near - H.arc_m - simplify_m - gap).max()))
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
        """RF-018-10 (S-1): el desfase con roseta de una línea rugosa debería salir verificado. **No se cumple**: medido el 22/11/2026
        (T09, ``gis/offset.py`` y ``design/pit_offset.py`` tal como los dejó la T08), con la simplificación igual al ruido, 135 de los
        150 casos con roseta se rechazan por ``distance`` (la verificación halla vértices a menos de d, con hasta ≈ 3,9 m de falta) y,
        con 0,05 m, 138 de 150 (136 por ``distance`` y 2 por ``crossing``); sin roseta, 0 y 6 de 150. Criterio no alcanzado."""
        rejected = [row.case.index for row in outcomes("noise") if row.case.with_rose and not row.verified]
        self.assertEqual(rejected, [], f"{len(rejected)} de {pd.ROUGH_CASES // 2} casos con roseta rechazados")


if __name__ == "__main__":
    unittest.main()
