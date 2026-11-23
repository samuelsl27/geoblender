# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que el proyecto dice de una corta para la barra N (spec 018, T34; HU-018-1, HU-018-4; RF-018-26, RF-018-29, RF-018-31; RF-015-25; plan 018 §5.5).

**Solo lee**: nada se calcula ni se escribe. Es el dominio de lectura de la ficha de la barra N «Entidad» y «Elemento activo» (``bl.ui.pit_panels``, que solo escribe los textos
traducidos): de lo **guardado** de la operación vigente de la corta —su informe ``des_prp_`` (las cifras de RF-018-31 y de la línea de cielo, el criterio que la paró y sus avisos),
``des_pbk_`` (las cifras de cada banco, con su volumen), ``des_pfn_`` (los hallazgos de RF-018-26, cada uno con su lugar) y ``des_prl_`` (las rampas por estaciones)—, no de un cálculo
abierto ni de la vista (RF-015-25).

:func:`read_pit_facts` da :class:`PitFacts`; ``None`` si la operación no escribió ningún informe (la barra N no inventa cifras). La longitud y las pendientes de cada rampa **se miden sobre
las estaciones guardadas** (:func:`ramp_rows`), las mismas que dibuja la vista previa.

Python puro (nivel 8). Perezoso: lo importa la barra N al usarlo, no ``bl`` al registrarse (``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from . import entity_store, provenance
from .pit_model import Finding
from .preview import Notice
from .road_card import report_notices

__all__ = ["BenchRow", "PitFacts", "RampRow", "ramp_rows", "read_pit_facts"]

_FIGURE_QUANTITIES = frozenset(figure.key.removeprefix("des.pit_") for figure in provenance.PIT_FIGURES)
_FINDINGS = 'SELECT kind, bench, value, limit_value, unit, x, y, detail FROM "{table}" ORDER BY fid'
_BENCHES = 'SELECT bench, z_foot_m, z_crest_m, len_foot_m, len_crest_m, area_berm_m2, area_floor_m2, cut_m3 FROM "{table}" ORDER BY bench'
_RAMPS = 'SELECT ramp, bench, x, y, level_m FROM "{table}" ORDER BY fid'


@dataclass(frozen=True, slots=True)
class BenchRow:
    """Las cifras de un banco (``des_pbk_``): su número, las cotas de su pie y de su cresta (m), las longitudes de ambos (m), el área de su berma y de su fondo (m²; ``None`` donde no la tiene) y el
    volumen que se corta en él (m³)."""

    bench: int
    z_foot_m: float
    z_crest_m: float
    len_foot_m: float
    len_crest_m: float
    area_berm_m2: float | None
    area_floor_m2: float | None
    cut_m3: float


@dataclass(frozen=True, slots=True)
class RampRow:
    """Una rampa guardada (``des_prl_``): el código de su definición (``code``), el banco de arriba, la longitud de su eje en planta (``length_m``), su pendiente media y la máxima (por cientos) y su
    inicio absoluto (``x`` e ``y``, float64)."""

    code: str
    bench: int
    length_m: float
    gradient_mean_pct: float
    gradient_max_pct: float
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class PitFacts:
    """Lo guardado de la operación vigente de una corta (:func:`read_pit_facts`): sus cifras (``figures``: la clave sin ``des.pit_``, p. ej. ``benches``, ``cut_m3``, ``sky_len_m``), el criterio
    que la paró (``stop``), las cifras de cada banco (``benches``), **todos sus hallazgos** (``findings``, en el orden del cálculo), sus rampas y los avisos del cálculo."""

    figures: Mapping[str, float]
    stop: str | None
    benches: tuple[BenchRow, ...]
    findings: tuple[Finding, ...]
    ramps: tuple[RampRow, ...]
    notices: tuple[Notice, ...]


def _finite(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(float(value)) else None  # type: ignore[arg-type]


def ramp_rows(rows: list[tuple[object, ...]]) -> tuple[RampRow, ...]:
    """Las rampas de las estaciones ``rows`` (``ramp, bench, x, y, level_m`` por orden de estación): una por (definición, banco) seguidos, con su longitud en planta y su pendiente media (la
    diferencia de cota entre el principio y el fin sobre la longitud) y máxima (la mayor entre dos estaciones que se separan en planta). Una con menos de dos estaciones no sale."""
    found: list[RampRow] = []
    group: list[tuple[float, float, float]] = []
    key: tuple[str, int] | None = None

    def close() -> None:
        if key is None or len(group) < 2:
            return
        run = top = 0.0
        for (ax, ay, az), (bx, by, bz) in zip(group, group[1:], strict=False):
            step = math.hypot(bx - ax, by - ay)
            run += step
            if step > 0.0:
                top = max(top, abs(bz - az) / step * 100.0)
        found.append(RampRow(key[0], key[1], run, 0.0 if run <= 0.0 else abs(group[-1][2] - group[0][2]) / run * 100.0, top, group[0][0], group[0][1]))

    for code, bench, x, y, level in rows:
        here = (str(code), int(bench))  # type: ignore[call-overload]
        if here != key:
            close()
            key, group = here, []
        group.append((float(x), float(y), float(level)))  # type: ignore[arg-type]
    close()
    return tuple(found)


def read_pit_facts(conn: sqlite3.Connection, operation_uid: str) -> PitFacts | None:
    """Lo que guardó la operación ``operation_uid`` de una corta, leído con ``conn``; ``None`` si no escribió ningún informe (RF-015-25: sin lo guardado, la barra N no inventa cifras). Un hallazgo
    cuyo tipo ya no es del dominio no sale. Solo lee; ``sqlite3.Error`` sigue."""
    report = entity_store.read_entity_report(conn, operation_uid)
    if not report:
        return None
    figures: dict[str, float] = {}
    stop = None
    for quantity, value, _unit, note in report:
        number = _finite(value)
        if quantity in _FIGURE_QUANTITIES and number is not None and quantity not in figures:
            figures[quantity] = number
        elif quantity == "stop" and stop is None and note:
            stop = str(note)
    benches: tuple[BenchRow, ...] = ()
    table = entity_store.operation_table(conn, operation_uid, provenance.PIT_BENCHES_ROLE)
    if table is not None:
        benches = tuple(BenchRow(int(n), float(zf), float(zc), float(lf), float(lc), _finite(ab), _finite(af), float(cut))
                        for n, zf, zc, lf, lc, ab, af, cut in conn.execute(_BENCHES.format(table=table)).fetchall())
    findings: list[Finding] = []
    table = entity_store.operation_table(conn, operation_uid, provenance.PIT_FINDINGS_ROLE)
    if table is not None:
        for kind, bench, value, limit, unit, x, y, detail in conn.execute(_FINDINGS.format(table=table)).fetchall():
            try:
                findings.append(Finding(str(kind), _finite(value), _finite(limit), (float(x), float(y)), None if bench is None else int(bench), None if unit is None else str(unit),
                                        "" if detail is None else str(detail)))
            except ValueError:  # un tipo que ya no es del dominio: no se inventa
                continue
    ramps: tuple[RampRow, ...] = ()
    table = entity_store.operation_table(conn, operation_uid, provenance.PIT_RAMPS_ROLE)
    if table is not None:
        ramps = ramp_rows(conn.execute(_RAMPS.format(table=table)).fetchall())
    return PitFacts(figures, stop, benches, tuple(findings), ramps, report_notices(report))
