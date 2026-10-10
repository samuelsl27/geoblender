# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de la procedencia (spec 008, T42; RNF-008-01 a 05, RNF-008-10 y RNF-008-11;
plan 008 §7.3, ``tests/rendimiento/core``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4) en el PC
de referencia de la spec 001 §5, en disco local (``%TEMP%``), con el volumen de D-13 que
construye ``tests/support/provenance_fixtures.py`` (100 entradas, 300 parámetros con 10
revisiones, 10 000 operaciones y 20 000 datos: 4 000 ficheros de ``rasters/`` y 16 000 en 160
tablas comunes del proyecto). Cada prueba imprime su cifra en una línea ``RNF-008-nn: …`` con
el intérprete (``tools/check.py`` las recoge) y la compara con su presupuesto, sin relajarlo.

- RNF-008-01 (:class:`OperationWriteTest`): registrar una operación con 10 datos de entrada,
  10 de salida y 30 parámetros en el proyecto de D-13: empezar y terminar (cada escritura, con
  su transacción) ≤ 0,1 s; máximo de 10 operaciones.
- RNF-008-02 (:class:`GraphCascadeTest`): en ese grafo, cambiar el parámetro que leen todas las
  cadenas: la cascada (la obsolescencia deducida del grafo leído de la base) y la lista de lo
  afectado (``stale_items``, con sus textos) ≤ 0,5 s; escribir las marcas (la transacción del
  cambio, que reescribe la caché ``gb_stale`` por región, ida y vuelta) ≤ 1 s cada una.
- RNF-008-03 (:class:`LineageTest`): la procedencia de una cifra al final de una cadena de
  10 000 operaciones (con 20 000 datos), hasta su entrada, con sus filas ≤ 0,5 s; máximo de 3.
- RNF-008-04 (:class:`InputCheckTest`): comprobar las 100 entradas sin cambios por tamaño y
  fecha de sus ficheros (por pasos, en segundo plano) ≤ 0,5 s con las fuentes en disco local.
- RNF-008-05 (:class:`ContentHashTest`): el hash de contenido de una rejilla de 11,2 M celdas
  (3 399 × 3 309, ``test.npy_grid@1``), de una capa de 100 000 polígonos y de una tabla de
  500 000 filas de un GeoPackage (``core.gpkg_layer@1``) ≤ 5 s cada uno, con progreso cada
  ≤ 1 s.
- RNF-008-10 (:class:`OpenDetectTest`): la comprobación de apertura entera (ediciones externas,
  datos que faltan, restos, entradas, originales, versiones y su registro) del proyecto de D-13
  sin cambios ≤ 1 s, por pasos.
- RNF-008-11 (:class:`BigHashTest`): el arnés por lector de ``provenance_fixtures`` con
  ``test.npy_grid@1`` y un MDT de 100 M celdas (10 000 × 10 000, float32): ≤ 45 s, progreso
  cada ≤ 1 s y cancelación en ≤ 2 s (mirada cada ≤ 2 s, al empezar y a mitad). Con
  ``core.gpkg_layer@1`` (:class:`BigLayerHashTest`, T67): una capa de 2 M polígonos (unos
  0,9 GB) en disco local, ≤ 60 s, con lo mismo también mientras cuenta y cierra el hash.
- RNF-008-12 (:class:`OpenStepsTest`, T65): la comprobación de apertura del proyecto de D-13
  sin cambios, con la obsolescencia completa por pasos: ningún paso de más de 20 ms (el más
  largo, mediana de 5); y, con la caché sin saber de un cambio de todas las cadenas y otro
  cambio entre el cálculo y la escritura, la caché y los estados al terminar son, fila a
  fila, los de la transacción final de antes (con ``refresh_all``) sobre la misma base.

En la red (recurso «red»: la carpeta de pruebas de ``GEOBLENDER_NET_TEST_DIR``, nunca la de
los expedientes ni la del espejo; sin ella, se omiten): RNF-008-04 con las 100 fuentes en la
red (≤ 3 s) y RNF-008-10 con el proyecto de D-13 en la red (≤ 5 s). Quedan para la
comprobación manual M7 (T59): RNF-008-01 y 02 en la red y el GeoPackage de 1 GB de RNF-008-11
(medido de nuevo en T67); el GeoTIFF de 100 M celdas y la base de RecMin de 100 MB, para la 006
y la 005 con este arnés (S-4).
"""

from __future__ import annotations

import platform
import shutil
import statistics
import sys
import time
import unittest
from collections.abc import Iterator
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import network, open_check
from tests.support import provenance_fixtures as d13
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_readers import NPY_GRID
from tests.support.resources import requires

builtin = import_geoblender("core.content.builtin")
readers = import_geoblender("core.content.readers")
graph = import_geoblender("core.provenance.graph")
stale = import_geoblender("core.provenance.stale")
lineage_mod = import_geoblender("core.provenance.lineage")
checks = import_geoblender("core.provenance.checks")
operations = import_geoblender("core.provenance.operations")
inputs_check = import_geoblender("core.inputs.check")
params = import_geoblender("core.params")

INTERPRETER = f"Python {platform.python_version()}, numpy {np.__version__}"

WRITE_BUDGET_S = 0.1  # RNF-008-01: empezar y terminar, cada escritura, en disco local
WRITES = 10
CASCADE_BUDGET_S = 0.5  # RNF-008-02: cascada y lista
MARKS_BUDGET_S = 1.0  # RNF-008-02: escribir las marcas, en disco local
LINEAGE_BUDGET_S = 0.5  # RNF-008-03
LINEAGE_RUNS = 3
INPUT_CHECK_BUDGET_S = 0.5  # RNF-008-04, en disco local
NET_INPUT_CHECK_BUDGET_S = 3.0  # RNF-008-04, en la red
CONTENT_HASH_BUDGET_S = 5.0  # RNF-008-05
PROGRESS_GAP_S = 1.0  # RNF-008-05 y 11: progreso cada ≤ 1 s
OPEN_DETECT_BUDGET_S = 1.0  # RNF-008-10, en disco local
NET_OPEN_DETECT_BUDGET_S = 5.0  # RNF-008-10, en la red
OPEN_STEP_BUDGET_S = 0.020  # RNF-008-12: cada paso de la comprobación de apertura (plan §5.4.6)
OPEN_STEP_RUNS = 5

# RNF-008-05: un MDT de 3 399 × 3 309 (11,2 M celdas), 100 000 polígonos de 20 vértices y una
# tabla de ensayos de 500 000 filas.
MDT_SHAPE = (3_399, 3_309)
LAYER_FEATURES = 100_000
TABLE_ROWS = 500_000


def _seconds(value: float, digits: int = 3) -> str:
    """Segundos con coma decimal (salida en español)."""
    return f"{value:.{digits}f}".replace(".", ",")


def _report(text: str) -> None:
    print(f"{text} [{INTERPRETER}]", file=sys.stderr, flush=True)


@dataclass
class Driven:
    """Lo que tardó una operación por pasos: total, el paso más largo, cuántos pasos y el
    resultado del último."""

    total_s: float
    max_step_s: float
    steps: int
    result: Any


def drive(steps: Iterator[Any]) -> Driven:
    """Recorre ``steps`` entero midiendo cada llamada al generador."""
    durations: list[float] = []
    result: Any = None
    started = time.perf_counter()
    while True:
        before = time.perf_counter()
        try:
            step = next(steps)
        except StopIteration:
            durations.append(time.perf_counter() - before)
            break
        durations.append(time.perf_counter() - before)
        if getattr(step, "result", None) is not None:
            result = step.result
    return Driven(time.perf_counter() - started, max(durations), len(durations) - 1, result)


# --- El proyecto de D-13, compartido por las pruebas que lo dejan como estaba ---------------

_SHARED: dict[str, d13.D13Project] = {}
_STACK = ExitStack()


def _d13() -> d13.D13Project:
    """El proyecto de D-13 en disco local (se construye la primera vez: unos segundos)."""
    if "local" not in _SHARED:
        tmp = _STACK.enter_context(project_tmp("gb-008-d13-"))
        _STACK.enter_context(d13.registered())
        built = d13.build_d13(tmp / "proyectos", tmp / "fuentes")
        _STACK.callback(built.close)
        _SHARED["local"] = built
    return _SHARED["local"]


def tearDownModule() -> None:
    _SHARED.clear()
    _STACK.close()


class OperationWriteTest(unittest.TestCase):
    def test_begin_and_complete(self) -> None:
        """RNF-008-01: registrar una operación con 10 datos de entrada, 10 de salida y 30
        parámetros en el proyecto de D-13 en disco local tarda ≤ 0,1 s al empezar y ≤ 0,1 s
        al terminar, cada escritura con su transacción (máximo de 10 operaciones)."""
        built = _d13()
        project = built.project
        begins: list[float] = []
        completes: list[float] = []
        keys = [d13.parameter_key(index) for index in range(101, 131)]
        for number in range(WRITES):
            consumed = [operations.Use(built.leaf(chain), "source")
                        for chain in range(10 * number, 10 * number + 10)]
            started = time.perf_counter()
            handle = operations.begin_operation(
                project, d13.op_type(number), settings={"prueba": number}, inputs=consumed,
                params=keys, executor="blender",
            )
            begins.append(time.perf_counter() - started)
            outputs = d13.write_output_tables(project, f"res_salida_{number:02d}", 10)
            started = time.perf_counter()
            with project.write_transaction() as conn:
                records = handle.complete(conn, outputs=outputs, software={})
            completes.append(time.perf_counter() - started)
            self.assertEqual(len(records), 10)
            self.assertEqual(len(handle.inputs), 10)
            self.assertEqual(len(handle.params), 30)
        _report(
            f"RNF-008-01: registrar una operación con 10 entradas, 10 salidas y 30 parámetros "
            f"en el proyecto de D-13 en disco local, {WRITES} veces: empezar máximo "
            f"{_seconds(max(begins))} s (mediana {_seconds(statistics.median(begins))} s), "
            f"terminar máximo {_seconds(max(completes))} s (mediana "
            f"{_seconds(statistics.median(completes))} s) (presupuesto "
            f"{_seconds(WRITE_BUDGET_S, 1)} s cada escritura)"
        )
        self.assertLessEqual(max(begins), WRITE_BUDGET_S)
        self.assertLessEqual(max(completes), WRITE_BUDGET_S)


class GraphCascadeTest(unittest.TestCase):
    def test_cascade_list_and_marks(self) -> None:
        """RNF-008-02: en el grafo de D-13 (10 000 operaciones y 20 000 datos), cambiar el
        parámetro que leen todas las cadenas: la cascada (la obsolescencia deducida del grafo
        leído de la base) y la lista de lo afectado tardan ≤ 0,5 s, y escribir las marcas (la
        transacción del cambio con la caché por región) ≤ 1 s en disco local, ida y vuelta."""
        built = _d13()
        project = built.project
        store = params.ParameterStore(project)
        key = d13.COMMON_KEY
        before = store.get(key).value
        marks: list[float] = []
        started = time.perf_counter()
        with project.write_transaction() as conn:
            store.change(conn, key, value=before + 1.0, reason="Prueba de rendimiento")
        marks.append(time.perf_counter() - started)
        with project.read() as conn:
            started = time.perf_counter()
            state = graph.deduce(graph.load_graph(conn))
            cascade = time.perf_counter() - started
        started = time.perf_counter()
        report = stale.stale_items(project)
        listing = time.perf_counter() - started
        counted = stale.counts(project)
        self.assertGreaterEqual(len(state.operations), d13.OPERATIONS)
        self.assertGreaterEqual(len(state.datasets), d13.DATASETS)
        self.assertGreaterEqual(len(report.items), d13.DATASETS)
        self.assertGreaterEqual(counted.stale, d13.DATASETS)
        started = time.perf_counter()
        with project.write_transaction() as conn:
            store.change(conn, key, value=before, reason="Vuelve el valor de la prueba")
        marks.append(time.perf_counter() - started)
        self.assertEqual(stale.counts(project).obsolete, 0)
        _report(
            f"RNF-008-02: grafo de D-13 en disco local, el parámetro de todas las cadenas: "
            f"cascada {_seconds(cascade)} s ({len(state.operations)} operaciones y "
            f"{len(state.datasets)} datos obsoletos) + lista {_seconds(listing)} s "
            f"({len(report.items)} elementos) = {_seconds(cascade + listing)} s (presupuesto "
            f"{_seconds(CASCADE_BUDGET_S, 1)} s); escribir las marcas {_seconds(marks[0])} s y "
            f"quitarlas {_seconds(marks[1])} s (presupuesto {_seconds(MARKS_BUDGET_S, 0)} s)"
        )
        self.assertLessEqual(cascade + listing, CASCADE_BUDGET_S)
        self.assertLessEqual(max(marks), MARKS_BUDGET_S)


class LineageTest(unittest.TestCase):
    """La cifra al final de una cadena de 10 000 operaciones, en su propio proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stack = ExitStack()
        try:
            tmp = cls.stack.enter_context(project_tmp("gb-008-chain-"))
            cls.stack.enter_context(d13.registered())
            cls.built = d13.build_d13(tmp / "proyectos", tmp / "fuentes", chains=1)
            cls.stack.callback(cls.built.close)
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()
        super().tearDownClass()

    def test_figure_at_the_end_of_ten_thousand_operations(self) -> None:
        """RNF-008-03: la procedencia de la cifra de la última operación de una cadena de
        10 000 operaciones (20 000 datos), hasta su entrada y con sus filas, tarda ≤ 0,5 s
        (máximo de 3)."""
        built = self.built
        figure = built.figures[0]
        times: list[float] = []
        for _ in range(LINEAGE_RUNS):
            started = time.perf_counter()
            tree = lineage_mod.lineage(built.project, figure)
            rows = tree.rows()
            times.append(time.perf_counter() - started)
            self.assertEqual(len(tree.operations), d13.OPERATIONS)
            self.assertIn(built.inputs[0], tree.inputs)
        _report(
            f"RNF-008-03: procedencia de la cifra al final de una cadena de "
            f"{len(tree.operations)} operaciones ({len(rows)} filas), {LINEAGE_RUNS} veces: "
            f"máximo {_seconds(max(times))} s, mediana {_seconds(statistics.median(times))} s "
            f"(presupuesto {_seconds(LINEAGE_BUDGET_S, 1)} s)"
        )
        self.assertLessEqual(max(times), LINEAGE_BUDGET_S)


class InputCheckTest(unittest.TestCase):
    def _check(self, project: Any, where: str, budget: float) -> None:
        driven = drive(inputs_check.check_steps(project, mode="quick"))
        outcome = driven.result
        verdicts = {finding.verdict for finding in outcome.findings}
        self.assertEqual(len(outcome.findings), d13.INPUTS)
        self.assertEqual(verdicts, {inputs_check.Verdict.UNCHANGED})
        _report(
            f"RNF-008-04: comprobar {len(outcome.findings)} entradas sin cambios por tamaño y "
            f"fecha {where}: {_seconds(driven.total_s)} s en {driven.steps} pasos, paso más "
            f"largo {_seconds(driven.max_step_s)} s (presupuesto {_seconds(budget, 1)} s)"
        )
        self.assertLessEqual(driven.total_s, budget)

    def test_hundred_inputs_local(self) -> None:
        """RNF-008-04: comprobar por tamaño y fecha las 100 entradas sin cambios del
        proyecto de D-13, con las fuentes en disco local, tarda ≤ 0,5 s."""
        self._check(_d13().project, "con las fuentes en disco local", INPUT_CHECK_BUDGET_S)

    @requires(network.NET, network.NET_HINT)
    def test_hundred_inputs_on_the_network(self) -> None:
        """RNF-008-04: comprobar por tamaño y fecha 100 entradas sin cambios con las fuentes
        en la carpeta de pruebas de la red tarda ≤ 3 s."""
        with ExitStack() as stack:
            tmp = stack.enter_context(project_tmp("gb-008-red-"))
            remote = stack.enter_context(network.net_tmp("gb-008-fuentes-"))
            stack.enter_context(d13.registered())
            built = d13.build_inputs(tmp / "proyectos", remote)
            stack.callback(built.close)
            self._check(built.project, "con las fuentes en la red", NET_INPUT_CHECK_BUDGET_S)


class OpenDetectTest(unittest.TestCase):
    def _check(self, built: d13.D13Project, where: str, budget: float) -> None:
        driven = drive(checks.open_check_steps(built.project, write=True))
        outcome = driven.result
        self.assertEqual(outcome.warnings, ())
        self.assertTrue(outcome.recorded)
        self.assertGreaterEqual(len(outcome.checked_datasets), d13.DATASETS)
        self.assertEqual(len(outcome.checked_inputs), d13.INPUTS)
        self.assertEqual(outcome.orphans.orphans, ())
        self.assertEqual((outcome.cache.added, outcome.cache.removed), (frozenset(), frozenset()))
        _report(
            f"RNF-008-10: comprobación de apertura del proyecto de D-13 sin cambios {where} "
            f"({len(outcome.checked_datasets)} datos, {len(outcome.checked_inputs)} entradas): "
            f"{_seconds(driven.total_s)} s en {driven.steps} pasos, paso más largo "
            f"{_seconds(driven.max_step_s)} s (presupuesto {_seconds(budget, 0)} s)"
        )
        self.assertLessEqual(driven.total_s, budget)

    def test_unchanged_project_local(self) -> None:
        """RNF-008-10: detectar al abrir las ediciones externas, los datos que faltan y los
        restos del proyecto de D-13 sin cambios (20 000 datos) en disco local tarda ≤ 1 s."""
        self._check(_d13(), "en disco local", OPEN_DETECT_BUDGET_S)

    @requires(network.NET, network.NET_HINT)
    def test_unchanged_project_on_the_network(self) -> None:
        """RNF-008-10: detectar al abrir las ediciones externas, los datos que faltan y los
        restos del proyecto de D-13 sin cambios en la carpeta de pruebas de la red tarda
        ≤ 5 s."""
        with ExitStack() as stack:
            remote = stack.enter_context(network.net_tmp("gb-008-d13-"))
            stack.enter_context(d13.registered())
            built = d13.build_d13(remote / "proyectos", remote / "fuentes")
            stack.callback(built.close)
            self._check(built, "en la red", NET_OPEN_DETECT_BUDGET_S)


def _ms(value: float) -> str:
    return f"{value * 1000:.1f}".replace(".", ",")


class OpenStepsTest(unittest.TestCase):
    def test_no_step_takes_longer_than_its_budget(self) -> None:
        """RNF-008-12 (plan §5.4.6; T65): la comprobación de apertura del proyecto de D-13 sin
        cambios en disco local, con la obsolescencia completa por pasos, no tiene ningún paso de
        más de 20 ms (el más largo, mediana de 5 comprobaciones) y su transacción final no toca
        la caché."""
        built = _d13()
        longest: list[float] = []
        totals: list[float] = []
        counts: list[int] = []
        for _ in range(OPEN_STEP_RUNS):
            driven = drive(checks.open_check_steps(built.project, write=True))
            outcome = driven.result
            self.assertTrue(outcome.recorded)
            self.assertEqual((outcome.cache.added, outcome.cache.removed),
                             (frozenset(), frozenset()))
            longest.append(driven.max_step_s)
            totals.append(driven.total_s)
            counts.append(driven.steps)
        median = statistics.median(longest)
        _report(
            f"RNF-008-12: comprobación de apertura del proyecto de D-13 sin cambios en disco "
            f"local, {OPEN_STEP_RUNS} veces: paso más largo, mediana {_ms(median)} ms (máximo "
            f"{_ms(max(longest))} ms; presupuesto {_ms(OPEN_STEP_BUDGET_S)} ms), "
            f"{statistics.median(counts):.0f} pasos y {_seconds(statistics.median(totals))} s"
        )
        self.assertLessEqual(median, OPEN_STEP_BUDGET_S)

    def test_cache_identical_to_the_full_refresh(self) -> None:
        """RF-008-58, RF-008-24, RNF-008-12 (plan §5.4.6, paso 8; T65): en el proyecto de D-13
        con la caché sin saber del cambio del parámetro de todas las cadenas (sus 10 000
        operaciones y 20 000 datos, obsoletos) y otro cambio del proyecto entre el cálculo y la
        escritura (un parámetro de dentro de las cadenas, justo antes de la transacción final),
        la comprobación de apertura vuelve a calcular y deja la caché y los estados idénticos,
        fila a fila, a los de la transacción final de antes (con ``refresh_all``) sobre la
        misma base. El proyecto queda como estaba."""
        built = _d13()
        project = built.project
        database = Path(project.database_path)
        clock = project.clock
        store = params.ParameterStore(project)
        inner = d13.parameter_key(d13.FIRST_INNER_PARAMETER + 49)
        with ExitStack() as stack:
            tmp = stack.enter_context(project_tmp("gb-008-t65-"))
            shutil.copyfile(database, tmp / "d13.gpkg")
            stack.callback(shutil.copyfile, tmp / "d13.gpkg", database)
            moment = (clock._now, clock._monotonic)
            with project.write_transaction() as conn:  # la caché no lo sabe
                conn.execute("UPDATE gb_parameter SET value_sha256 = ? WHERE key = ?",
                             (d13.SHA, d13.COMMON_KEY))
            shutil.copyfile(database, tmp / "base.gpkg")
            found = []
            for before in (False, True):
                shutil.copyfile(tmp / "base.gpkg", database)
                clock._now, clock._monotonic = moment
                real = project.try_write
                pending = [inner]

                def writing(work: Any, real: Any = real, pending: list[str] = pending) -> Any:
                    while pending:
                        key = pending.pop()
                        with project.write_transaction() as conn:
                            store.change(conn, key, value=store.get(key).value + 1.0,
                                         reason="Cambio entre el cálculo y la escritura")
                    return real(work)

                with open_check.same_uids(), \
                        (open_check.as_before() if before else nullcontext()), \
                        mock.patch.object(project, "try_write", writing), \
                        mock.patch.object(checks, "full_difference_steps",
                                          wraps=stale.full_difference_steps) as computed:
                    driven = drive(checks.open_check_steps(project, write=True))
                found.append((driven, open_check.project_rows(project), computed.call_count))
            (driven, rows, computed), (expected, reference, _computed) = found
            clock._now, clock._monotonic = moment
        self.assertEqual(computed, 2)
        outcome = driven.result
        self.assertGreaterEqual(len(outcome.cache.added), d13.OPERATIONS + d13.DATASETS)
        self.assertEqual(outcome.texts("es"), expected.result.texts("es"))
        self.assertEqual(rows.keys(), reference.keys())
        for table in sorted(reference):
            self.assertTrue(rows[table] == reference[table], table)
        _report(
            f"RNF-008-12: comprobación de apertura del proyecto de D-13 con la caché sin saber "
            f"de un cambio de todas las cadenas ({len(outcome.cache.added)} filas que añadir) y "
            f"un cambio entre el cálculo y la escritura: caché y estados idénticos a los de la "
            f"transacción final de antes ({len(rows[open_check.CACHE_TABLE])} filas de la "
            f"caché); calculada 2 veces, {_seconds(driven.total_s)} s en {driven.steps} pasos, "
            f"paso más largo {_ms(driven.max_step_s)} ms (la transacción final con todas esas "
            f"filas; antes, {_seconds(expected.total_s)} s y {_ms(expected.max_step_s)} ms)"
        )


class ContentHashTest(unittest.TestCase):
    """Las tres fuentes de RNF-008-05, escritas una vez en un temporal."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stack = ExitStack()
        try:
            tmp = cls.stack.enter_context(project_tmp("gb-008-hash-"))
            cls.mdt = d13.write_mdt(tmp / "mdt.npy", MDT_SHAPE)
            cls.layer = d13.write_layer(tmp / "parcelas.gpkg", LAYER_FEATURES)
            cls.table = d13.write_assays(tmp / "ensayos.gpkg", TABLE_ROWS)
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()
        super().tearDownClass()

    def _hash(self, what: str, reader: Any, request: Any) -> None:
        clock = d13.ProgressClock()
        digest = readers.read_content(reader, request, progress=clock.tick)
        total, gap = clock.finish()
        self.assertEqual(digest.reader, reader.id)
        _report(
            f"RNF-008-05: hash de contenido de {what}: {_seconds(total, 2)} s, "
            f"{clock.ticks} avisos de progreso, el mayor hueco {_seconds(gap)} s "
            f"(presupuestos {_seconds(CONTENT_HASH_BUDGET_S, 0)} s y "
            f"{_seconds(PROGRESS_GAP_S, 0)} s)"
        )
        self.assertLessEqual(total, CONTENT_HASH_BUDGET_S)
        self.assertLessEqual(gap, PROGRESS_GAP_S)

    def test_grid_of_eleven_million_cells(self) -> None:
        """RNF-008-05: el hash de contenido de una rejilla de 3 399 × 3 309 celdas (un MDT de
        11,2 M celdas en float32) tarda ≤ 5 s, con progreso cada ≤ 1 s."""
        request = NPY_GRID.request("raster", d13.GRID_DECLARATIONS, {"main": self.mdt},
                                   d13.grid_settings())
        self._hash(f"un MDT de {MDT_SHAPE[0]} × {MDT_SHAPE[1]} celdas", NPY_GRID, request)

    def test_layer_of_hundred_thousand_features(self) -> None:
        """RNF-008-05: el hash de contenido de una capa de un GeoPackage con 100 000
        polígonos de 20 vértices tarda ≤ 5 s, con progreso cada ≤ 1 s."""
        request = builtin.GPKG_LAYER.request("vector", d13.LAYER_DECLARATIONS,
                                             {"main": self.layer}, {"layer": d13.LAYER_NAME})
        self._hash(f"una capa de {LAYER_FEATURES} polígonos", builtin.GPKG_LAYER, request)

    def test_table_of_half_a_million_rows(self) -> None:
        """RNF-008-05: el hash de contenido de una tabla de un GeoPackage con 500 000 filas
        (ensayos: sondeo, desde, hasta, ley y litología) tarda ≤ 5 s, con progreso cada
        ≤ 1 s."""
        request = builtin.GPKG_LAYER.request("table", d13.TABLE_DECLARATIONS,
                                             {"main": self.table}, {"layer": d13.ASSAYS_NAME})
        self._hash(f"una tabla de {TABLE_ROWS} filas", builtin.GPKG_LAYER, request)


class BigHashTest(d13.BigHashHarness, unittest.TestCase):
    """RNF-008-11 con el lector de prueba ``test.npy_grid@1``: un MDT de 100 M celdas
    (10 000 × 10 000, float32, 400 MB). La 006 y la 005 heredan el mismo arnés con sus
    lectores (S-4)."""

    reader = NPY_GRID
    budget_s = d13.BIG_HASH_BUDGET_S

    @classmethod
    def make_source(cls, folder: Path) -> d13.BigSource:
        path = d13.write_mdt(folder / "mdt_100m.npy", d13.BIG_MDT_SHAPE)
        rows, columns = d13.BIG_MDT_SHAPE
        return d13.BigSource(
            {"main": path}, "raster", d13.GRID_DECLARATIONS, d13.grid_settings(),
            f"un MDT de {rows * columns // 1_000_000} M celdas ({rows} × {columns}, float32)",
        )

    @classmethod
    def report(cls, text: str) -> None:
        _report(text)


class BigLayerHashTest(d13.BigHashHarness, unittest.TestCase):
    """RNF-008-11 con ``core.gpkg_layer@1`` (T67): una capa de un GeoPackage con 2 M polígonos
    de 20 vértices (unos 0,9 GB) en disco local, ≤ 60 s (el presupuesto del GeoPackage de 1 GB
    en ``Z:``), con progreso cada ≤ 1 s también mientras cuenta sus filas y mientras cierra el
    hash, y la cancelación en ≤ 2 s en cualquier momento. En ``Z:``, a mano (M7)."""

    reader = builtin.GPKG_LAYER
    budget_s = d13.BIG_LAYER_BUDGET_S

    @classmethod
    def make_source(cls, folder: Path) -> d13.BigSource:
        path = d13.write_layer(folder / "parcelas_2m.gpkg", d13.BIG_LAYER_FEATURES)
        return d13.BigSource(
            {"main": path}, "vector", d13.LAYER_DECLARATIONS, {"layer": d13.LAYER_NAME},
            f"una capa de {d13.BIG_LAYER_FEATURES // 1_000_000} M polígonos de "
            f"{d13.LAYER_VERTICES} vértices",
        )

    @classmethod
    def report(cls, text: str) -> None:
        _report(text)


if __name__ == "__main__":
    unittest.main()
