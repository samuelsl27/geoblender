# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de buscar intocables (spec 012, T37 y T30; RNF-012-04 y RNF-012-06; plan 012 §2.2
y §5.2.3, A6, ``tests/rendimiento/gis``; el plan §7.3 la nombra en ``test_masks_perf.py``, pero
vive aquí desde la T37 porque lleva sus propios datos).

Se ejecuta con ``python -B -s -X utf8 -m unittest tests.rendimiento.gis.test_search_perf -v`` (o con
``tools/check.py --rendimiento``): el Python de Blender (su numpy 2.3.4), en el PC de referencia de
la spec 001 §5 y en disco local (``%TEMP%``). Cada cifra se imprime en una línea ``RNF-012-nn: …``
con el equipo y el intérprete.

Datos (plan §2.2: se generan y no se versionan, ``tests/support/constraints_scale.py``): un
proyecto nuevo con V01 y V02 y las 500 restricciones de unos 100.000 vértices, **diez capas
«entidades» de 10.000 entidades** (3 de puntos, 4 de líneas de 10 vértices y 3 de polígonos de 8)
escritas en él y un sector de 400 vértices, que ocupa un cuarto de la ventana, ya declarado.

- RNF-012-04 (:class:`SearchTest`): la orden entera (``gis.masks.sectors.search_steps``: leer las
  capas del proyecto, buscar a 25 m y devolver la lista), de la llamada de la orden a la lista,
  con los pasos seguidos, ≤ 2 s (mediana de 5).
- RNF-012-06 (:class:`SearchTest`): cada llamada al generador, la de la orden incluida, ≤ 0,05 s
  (la orden no lee ninguna entidad antes de su primer paso).
- Lo hallado es, bit a bit, lo que da cargar las diez capas enteras y buscar (el cálculo de antes
  de la T37, ``gis.store.load_features`` + ``gis.search.search``): capas, números, distancias,
  atributos y orden.
- La capa de origen queda como estaba (su tabla y su hash) y Esc a mitad no deja nada.
"""

from __future__ import annotations

import gc
import statistics
import time
import unittest
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from tests.support import constraints_scale as scale
from tests.support import gis_perf
from tests.support import versions_perf as vperf
from tests.support.package import import_geoblender

sectors = import_geoblender("gis.masks.sectors")
finder = import_geoblender("gis.search")
gstore = import_geoblender("gis.store")
registry = import_geoblender("core.datasets.registry")

TOTAL_BUDGET_S = 2.0  # RNF-012-04
CALL_BUDGET_S = 0.05  # RNF-012-06 (cada llamada, la de la orden incluida)
RUNS = 5  # mediana de 5
CANCEL_AFTER = 6  # pasos antes de Esc
CANCEL_BUDGET_S = 2.0  # la cancelación efectiva en ≤ 2 s
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count


@dataclass(frozen=True, slots=True)
class Call:
    """Una llamada al generador de los pasos: lo que tardó y qué paso entregó."""

    seconds: float
    phase: str
    done: int
    total: int
    final: bool


@dataclass(frozen=True, slots=True)
class Run:
    """Una orden entera: la llamada de la orden, las llamadas a los pasos y la lista."""

    begin_s: float
    calls: tuple[Call, ...]
    result: Any

    @property
    def total_s(self) -> float:
        return self.begin_s + sum(call.seconds for call in self.calls)

    @property
    def longest(self) -> Call:
        """La llamada más larga a los pasos (la de la orden aparte)."""
        return max(self.calls, key=lambda call: call.seconds)


def _calls(steps: Iterator[Any]) -> tuple[tuple[Call, ...], Any]:
    calls: list[Call] = []
    result = None
    while True:
        before = time.perf_counter()
        try:
            step = next(steps)
        except StopIteration:
            calls.append(Call(time.perf_counter() - before, "end", 0, 0, False))
            break
        final = step.result is not None
        calls.append(Call(time.perf_counter() - before, step.phase, step.done, step.total, final))
        if final:
            result = step.result
    return tuple(calls), result


def _key(found: Any) -> tuple[Any, ...]:
    """Lo que identifica una entidad hallada, la distancia en hexadecimal (bit a bit)."""
    return (found.layer, found.fid, float(found.distance_m).hex(), dict(found.attributes))


def _same(first: Any, second: Any) -> bool:
    """``True`` si las dos listas de ``Found`` son iguales, bit a bit (capa, número, distancia,
    atributos y orden)."""
    return [_key(item) for item in first] == [_key(item) for item in second]


class SearchTest(unittest.TestCase):
    """RNF-012-04 y RNF-012-06 con las capas de §2.2 en disco local."""

    data: ClassVar[scale.ScaleProject]
    search: ClassVar[scale.ScaleSearch]

    @classmethod
    def setUpClass(cls) -> None:
        cls.enterClassContext(scale.search_registered())
        cls.data = cls.enterClassContext(scale.scale_project())
        cls.search = scale.write_search(cls.data)

    def order_once(self) -> Run:
        """``search_steps`` de V01 en el sector con las diez capas, con los pasos seguidos."""
        data, search = self.data, self.search
        data.clock.advance(minutes=1)
        before = time.perf_counter()
        steps = sectors.search_steps(data.project, search.sector_code, search.layers,
                                     version=data.v1.uid, budget_s=CALL_BUDGET_S)
        begin_s = time.perf_counter() - before
        calls, result = _calls(steps)
        self.assertIsInstance(result, sectors.Searched)
        return Run(begin_s, calls, result)

    def test_the_whole_order(self) -> None:
        """RNF-012-04 y RNF-012-06: la orden entera con las diez capas de 10.000 entidades y
        25 m, ≤ 2 s (mediana de 5), y cada llamada, la de la orden incluida, ≤ 0,05 s."""
        self.order_once()  # la primera no cuenta (cachés de SQLite y de numpy)
        found = []
        for _ in range(RUNS):
            gc.collect()
            found.append(self.order_once())
        totals = [run.total_s for run in found]
        begins = [run.begin_s for run in found]
        longest = sorted(found, key=lambda run: run.longest.seconds)[len(found) // 2].longest
        worst = max((run.longest for run in found), key=lambda call: call.seconds)
        data = self.data
        hits = len(found[-1].result.found)
        gis_perf.report(
            f"RNF-012-04: buscar intocables a {number(scale.SEARCH_DISTANCE_M, 0)} m de un sector "
            f"de {count(scale.SEARCH_SECTOR_VERTICES)} vértices en {scale.SEARCH_LAYERS} capas de "
            f"{count(self.search.entities)} entidades del proyecto ({count(hits)} halladas; la "
            f"orden entera: leer las capas, buscar y devolver la lista, con los pasos seguidos; "
            f"{MACHINE}): {gis_perf.median_line(totals)}; {len(found[-1].calls)} llamadas; "
            f"presupuesto {number(TOTAL_BUDGET_S, 0)} s; "
            f"{vperf.free_space(Path(data.project.root))}")
        gis_perf.report(
            f"RNF-012-06: la llamada más larga al buscar, mediana de {len(found)}: "
            f"{number(longest.seconds * 1000, 0)} ms («{longest.phase}» {longest.done}/"
            f"{longest.total}; la peor de todas, {number(worst.seconds * 1000, 0)} ms en "
            f"«{worst.phase}» {worst.done}/{worst.total}); la llamada de la orden, "
            f"{number(statistics.median(begins) * 1000, 0)} ms (la peor, "
            f"{number(max(begins) * 1000, 0)} ms); presupuesto "
            f"{number(CALL_BUDGET_S * 1000, 0)} ms ({MACHINE})")
        self.assertGreater(hits, 0)
        self.assertLessEqual(statistics.median(totals), TOTAL_BUDGET_S)
        self.assertLessEqual(max(begins), CALL_BUDGET_S, "la llamada de la orden")
        self.assertLessEqual(longest.seconds, CALL_BUDGET_S,
                             f"{longest.phase} {longest.done}/{longest.total}")

    def test_the_result_is_the_one_of_loading_the_layers_whole(self) -> None:
        """Lo hallado es, bit a bit, lo de cargar las diez capas enteras y buscar en memoria
        (el cálculo de antes): capas, números, distancias, atributos y orden."""
        data, search = self.data, self.search
        run = self.order_once()
        loaded = {name: gstore.load_features(data.project, name) for name in search.layers}
        wanted = finder.search((search.sector,), loaded, scale.SEARCH_DISTANCE_M)
        self.assertEqual(len(run.result.found), len(wanted))
        self.assertTrue(_same(run.result.found, wanted))

    def test_the_source_layer_is_not_touched(self) -> None:
        """La capa de origen queda como estaba: las filas de su tabla y el hash de su contenido
        registrado."""
        data, search = self.data, self.search
        name = search.layers[7]

        def state() -> tuple[Any, Any]:
            with data.project.read() as conn:
                rows = conn.execute(f'SELECT * FROM "{name}" ORDER BY fid').fetchall()
                record = registry.get(conn, name)
            return rows, record.content_sha256

        before = state()
        self.order_once()
        self.assertEqual(state(), before)

    def test_cancel_leaves_nothing(self) -> None:
        """Esc a mitad de la búsqueda se atiende en ≤ 2 s y no deja nada en el proyecto
        (operaciones y datos como estaban)."""
        data, search = self.data, self.search

        def state() -> tuple[Any, Any]:
            with data.project.read() as conn:
                operations = conn.execute("SELECT count(*) FROM gb_operation").fetchone()
                datasets = conn.execute("SELECT count(*) FROM gb_dataset").fetchone()
            return operations, datasets

        before = state()
        steps = sectors.search_steps(data.project, search.sector_code, search.layers,
                                     version=data.v1.uid, budget_s=CALL_BUDGET_S)
        for _ in range(CANCEL_AFTER):
            next(steps)
        started = time.perf_counter()
        steps.close()
        elapsed = time.perf_counter() - started
        gis_perf.report(
            f"RNF-012-04: Esc tras {CANCEL_AFTER} pasos de buscar: cerrar tarda "
            f"{number(elapsed * 1000, 1)} ms (presupuesto {number(CANCEL_BUDGET_S, 0)} s); las "
            f"operaciones y los datos del proyecto no cambian ({MACHINE})")
        self.assertLessEqual(elapsed, CANCEL_BUDGET_S)
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
