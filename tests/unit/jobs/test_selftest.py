# SPDX-License-Identifier: GPL-3.0-or-later
"""Lógica del autodiagnóstico de los trabajos (spec 004, T06; HU-004-1, HU-004-2, RF-004-03;
plan 004 §5.1, §5.2.2 y §5.4.1).

``jobs/selftest.py`` es la función de dominio ``run(ctx)`` del tipo de trabajo ``selftest``
(la misma en hilo y en proceso aparte, donde la envolverá ``workers/selftest.py``), su
estimador de duración y su entorno. Se prueba aquí con un contexto falso; con el arranque de
verdad, en ``tests/unit/workers/`` (T08).

- ``chunked_sum``: suma exacta n(n−1)/2 por trozos, con avance «Trozo k de N» hasta 1,0 y el
  resultado en ``out/sum.npy`` (``int64``, sin *pickle*) declarado con su huella; fallos
  provocables: ``fail_at`` (``JobFailed``), ``crash_at`` (``os._exit(7)``, solo en proceso
  aparte), ``ignore_cancel`` y ``stdout_noise`` (``print()`` y descriptor 1).
- Cancelación (RF-004-09): comprueba al menos cada 0,5 s, también durante una espera larga.
- ``matmul``: producto float64 n × n, el mejor de varios, con s, GFLOP/s, numpy y BLAS.
- Estimador (plan §5.4.1): ``chunks · sleep_s + n / 1,5·10⁹`` s; ``matmul`` exige ``compute``
  si n > 1000. Parámetros que no valen: ``request_invalid`` antes de calcular.
"""

import contextlib
import hashlib
import io
import math
import re
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender

selftest = import_geoblender("jobs.selftest")
worker_api = import_geoblender("jobs.worker_api")
protocol = import_geoblender("jobs.protocol")
messages = import_geoblender("jobs.messages")
i18n = import_geoblender("core.i18n")

JobCancelled = worker_api.JobCancelled
JobFailed = worker_api.JobFailed
LABEL = "Autodiagnóstico: suma por trozos"
SPANISH_LETTERS = re.compile(r"[áéíóúüñÁÉÍÓÚÜÑ¿¡]")


class _Crash(BaseException):
    """Lo que lanza el ``os._exit`` sustituido en las pruebas."""


class FakeContext:
    """Contexto falso con lo que ``run`` usa del ``WorkerContext`` de T07: ``request``,
    ``output_path``, ``progress`` (que comprueba la cancelación), ``log``,
    ``check_cancelled`` y ``add_output``. ``cancel_after`` pide cancelar tras ese número de
    avances; ``cancelled`` se puede activar desde otro hilo."""

    def __init__(self, request, folder: Path, *, cancel_after: int | None = None):
        self.request = request
        self.folder = folder
        (folder / protocol.OUTPUTS_DIR).mkdir(exist_ok=True)
        self.cancelled = threading.Event()
        self.cancel_after = cancel_after
        self.progress_events: list[tuple[float, str]] = []
        self.logs: list[tuple[str, str]] = []
        self.outputs = []
        self.checks = 0

    def output_path(self, filename: str) -> Path:
        return self.folder / protocol.OUTPUTS_DIR / filename

    def progress(self, frac: float, msg: str = "") -> None:
        self.progress_events.append((frac, msg))
        if self.cancel_after is not None and len(self.progress_events) >= self.cancel_after:
            self.cancelled.set()
        if self.cancelled.is_set():
            raise JobCancelled()

    def log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def check_cancelled(self) -> None:
        self.checks += 1
        if self.cancelled.is_set():
            raise JobCancelled()

    def add_output(self, path: Path, role: str):
        data = Path(path).read_bytes()
        ref = protocol.OutputRef(Path(path).relative_to(self.folder).as_posix(),
                                 hashlib.sha256(data).hexdigest(), len(data), role)
        self.outputs.append(ref)
        return ref


class _SelftestCase(unittest.TestCase):
    """Una carpeta temporal por prueba y un contexto falso con la petición."""

    def setUp(self):
        tmp = _support.jobs_tmp()
        self.folder = tmp.__enter__()
        self.addCleanup(tmp.__exit__, None, None, None)

    def context(self, params, **options) -> FakeContext:
        request = protocol.new_request("selftest", label=LABEL, owner="jobs", params=params,
                                       environment="blender", timeout_s=600)
        return FakeContext(request, self.folder, **options)

    def outputs_on_disk(self) -> list[str]:
        return sorted(p.name for p in (self.folder / protocol.OUTPUTS_DIR).iterdir())


class ChunkedSumTest(_SelftestCase):
    """HU-004-1: la suma por trozos, con avance, resultado y huella."""

    def test_sum_is_exact_and_declared_with_its_hash(self):
        """RF-004-05: suma exacta n(n−1)/2 (n = 20 000 por defecto: 199 990 000), guardada en
        ``out/sum.npy`` como ``int64`` sin *pickle* (136 bytes) y declarada con su sha256."""
        ctx = self.context({"op": "chunked_sum"})
        summary = selftest.run(ctx)
        self.assertEqual(summary, {"op": "chunked_sum", "n": 20_000, "chunks": 20,
                                   "sum": 199_990_000})
        [ref] = ctx.outputs
        self.assertEqual((ref.path, ref.role, ref.size), ("out/sum.npy", "sum", 136))
        path = self.folder / "out" / "sum.npy"
        self.assertEqual(ref.sha256, _support.sha256_file(path))
        value = np.load(path, allow_pickle=False)
        self.assertEqual((value.dtype, value.shape), (np.dtype(np.int64), ()))
        self.assertEqual(int(value), 199_990_000)

    def test_large_sum_is_exact(self):
        """La suma no pierde ni una unidad con n de millones (varios bloques por trozo)."""
        n = 3_000_001
        summary = selftest.run(self.context({"n": n, "chunks": 7}))
        self.assertEqual(summary["sum"], n * (n - 1) // 2)

    def test_more_chunks_than_numbers(self):
        """Con más trozos que números, los trozos vacíos no suman nada."""
        ctx = self.context({"n": 3, "chunks": 10})
        self.assertEqual(selftest.run(ctx)["sum"], 3)
        self.assertEqual(len(ctx.progress_events), 10)

    def test_progress_grows_to_one(self):
        """RF-004-06: un avance por trozo, creciente, «Trozo k de N», y el último 1,0."""
        ctx = self.context({"chunks": 4})
        selftest.run(ctx)
        self.assertEqual(ctx.progress_events, [
            (0.25, "Trozo 1 de 4"), (0.5, "Trozo 2 de 4"), (0.75, "Trozo 3 de 4"),
            (1.0, "Trozo 4 de 4"),
        ])

    def test_sleep_per_chunk(self):
        """``sleep_s`` por trozo: 3 × 0,05 s tardan al menos 0,15 s."""
        start = time.perf_counter()
        selftest.run(self.context({"chunks": 3, "sleep_s": 0.05}))
        self.assertGreaterEqual(time.perf_counter() - start, 0.15)

    def test_logs_what_it_does(self):
        """RF-004-15: deja en el registro qué suma hace."""
        ctx = self.context({"n": 10, "chunks": 2})
        selftest.run(ctx)
        self.assertTrue(any(level == "info" and "n = 10" in msg for level, msg in ctx.logs),
                        ctx.logs)


class ProvokedFailureTest(_SelftestCase):
    """HU-004-2: los fallos que se pueden provocar."""

    def test_fail_at_raises_job_failed(self):
        """RF-004-12: ``fail_at`` = 3 → ``JobFailed`` en el trozo 3 (antes de sumarlo), con
        código, ``msgid`` en inglés, valores y texto en español sin traza; sin resultado."""
        ctx = self.context({"chunks": 5, "fail_at": 3})
        with self.assertRaises(JobFailed) as caught:
            selftest.run(ctx)
        error = caught.exception
        self.assertEqual(error.code, "selftest_failed")
        self.assertEqual(error.values, {"chunk": 3, "chunks": 5})
        self.assertIsNone(SPANISH_LETTERS.search(error.msgid))
        self.assertIn("trozo 3 de 5", error.text)
        self.assertEqual(str(error), error.text)
        self.assertNotIn("Traceback", error.text)
        self.assertEqual(len(ctx.progress_events), 2)
        self.assertEqual(self.outputs_on_disk(), [])

    def test_crash_at_exits_the_process_with_7(self):
        """RF-004-12: ``crash_at`` = 2 → ``os._exit(7)`` en el trozo 2, en el hilo principal
        (el del worker en proceso aparte)."""
        ctx = self.context({"chunks": 4, "crash_at": 2})
        with mock.patch.object(selftest, "_hard_exit", side_effect=_Crash) as hard_exit:
            with self.assertRaises(_Crash):
                selftest.run(ctx)
        hard_exit.assert_called_once_with(7)
        self.assertEqual(len(ctx.progress_events), 1)

    def test_crash_never_happens_in_a_thread(self):
        """RF-004-12: en un hilo (el ejecutor dentro de Blender) la caída no se hace: sería
        tumbar Blender. ``JobFailed`` en su lugar."""
        ctx = self.context({"chunks": 4, "crash_at": 2})
        caught = []

        def target():
            try:
                selftest.run(ctx)
            except BaseException as exc:  # noqa: BLE001 - la prueba mira qué llegó
                caught.append(exc)

        with mock.patch.object(selftest, "_hard_exit", side_effect=_Crash) as hard_exit:
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            thread.join(5)
        hard_exit.assert_not_called()
        self.assertEqual(len(caught), 1)
        self.assertIsInstance(caught[0], JobFailed)
        self.assertEqual(caught[0].code, "selftest_crash_inprocess")

    def test_stdout_noise_goes_through_print_and_descriptor_1(self):
        """RF-004-15: ``stdout_noise`` escribe con ``print()`` (también una línea que parece
        un evento) y directamente en el descriptor 1, como una librería en C."""
        ctx = self.context({"chunks": 2, "stdout_noise": True})
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), mock.patch.object(selftest.os, "write") as write:
            summary = selftest.run(ctx)
        self.assertEqual(summary["sum"], 20_000 * 19_999 // 2)
        self.assertIn('"t": "result"', printed.getvalue())
        self.assertIn("print()", printed.getvalue())
        descriptors = [call.args[0] for call in write.call_args_list]
        self.assertIn(1, descriptors)


class CancellationTest(_SelftestCase):
    """RF-004-09: la suma atiende la cancelación (salvo que se le pida ignorarla)."""

    def test_cancel_during_a_long_sleep_stops_quickly(self):
        """RF-004-09: con un trozo de 30 s, cancelar a los 0,2 s la detiene antes de 0,5 s
        más (comprueba al menos cada 0,5 s), sin resultado."""
        ctx = self.context({"chunks": 1, "sleep_s": 30})
        timer = threading.Timer(0.2, ctx.cancelled.set)
        timer.start()
        self.addCleanup(timer.cancel)
        start = time.monotonic()
        with self.assertRaises(JobCancelled) as caught:
            selftest.run(ctx)
        self.assertLess(time.monotonic() - start, 0.7)
        self.assertIn("trozo 1 de 1", str(caught.exception))
        self.assertEqual(self.outputs_on_disk(), [])

    def test_cancel_between_chunks(self):
        """RF-004-09: cancelada tras el segundo trozo, para ahí («Cancelado en el trozo 2
        de 5») y no escribe el resultado."""
        ctx = self.context({"chunks": 5}, cancel_after=2)
        with self.assertRaises(JobCancelled) as caught:
            selftest.run(ctx)
        self.assertEqual(str(caught.exception), "Cancelado en el trozo 2 de 5")
        self.assertEqual(len(ctx.progress_events), 2)
        self.assertEqual(self.outputs_on_disk(), [])

    def test_ignore_cancel_runs_to_the_end(self):
        """HU-004-2: ``ignore_cancel`` no mira la cancelación (para probar el plazo de
        gracia): termina todos los trozos con la suma exacta."""
        ctx = self.context({"chunks": 4, "ignore_cancel": True})
        ctx.cancelled.set()
        summary = selftest.run(ctx)
        self.assertEqual(summary["sum"], 20_000 * 19_999 // 2)
        self.assertEqual(len(ctx.progress_events), 4)
        self.assertEqual(ctx.checks, 0)


class MatmulTest(_SelftestCase):
    """HU-004-3, HU-004-5: el producto de matrices del autodiagnóstico."""

    def test_matmul_reports_time_speed_numpy_and_blas(self):
        """El mejor de ``repeats`` productos float64 n × n: s, GFLOP/s, versión de numpy y
        BLAS (la de ``numpy.show_config``), con un avance por producto hasta 1,0."""
        ctx = self.context({"op": "matmul", "n": 40, "repeats": 2})
        summary = selftest.run(ctx)
        blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]["name"]
        self.assertEqual(summary["op"], "matmul")
        self.assertEqual((summary["n"], summary["repeats"]), (40, 2))
        self.assertGreater(summary["best_s"], 0)
        self.assertGreater(summary["gflops"], 0)
        self.assertEqual(summary["numpy"], np.__version__)
        self.assertEqual(summary["blas"], blas)
        self.assertEqual([frac for frac, _ in ctx.progress_events], [0.5, 1.0])
        self.assertEqual(ctx.outputs, [])
        protocol.plain_json(summary, "summary")  # JSON

    def test_matmul_cancelled_before_computing(self):
        """RF-004-09: cancelado, no calcula."""
        ctx = self.context({"op": "matmul", "n": 40})
        ctx.cancelled.set()
        with self.assertRaises(JobCancelled):
            selftest.run(ctx)
        self.assertEqual(ctx.progress_events, [])


class ParamsTest(_SelftestCase):
    """Parámetros del autodiagnóstico: los que no valen, ``request_invalid`` sin calcular."""

    def test_defaults(self):
        """Por defecto: suma por trozos de n = 20 000 en 20 trozos sin espera; el producto,
        n = 2000 (el de CE-004-02), el mejor de 3."""
        params = selftest.SelftestParams.from_params({}, job=LABEL)
        self.assertEqual((params.op, params.n, params.chunks, params.sleep_s),
                         ("chunked_sum", 20_000, 20, 0.0))
        self.assertEqual((params.fail_at, params.crash_at), (None, None))
        self.assertFalse(params.ignore_cancel or params.stdout_noise)
        matmul = selftest.SelftestParams.from_params({"op": "matmul"}, job=LABEL)
        self.assertEqual((matmul.n, matmul.repeats), (2000, 3))

    def test_invalid_params_fail_before_calculating(self):
        """Cada parámetro que no vale da ``JobFailed`` con el código, el ``msgid`` y el
        texto de ``request_invalid``, que nombra el trabajo; nada calculado ni escrito."""
        cases = [
            {"op": "nada"}, {"op": 3}, {"n": 0}, {"n": -1}, {"n": True}, {"n": "5"},
            {"n": 2.5}, {"n": 2**31 + 1}, {"chunks": 0}, {"chunks": 10_001},
            {"sleep_s": -1}, {"sleep_s": 61}, {"sleep_s": "1"},
            {"fail_at": 0}, {"fail_at": 21}, {"crash_at": 21}, {"fail_at": 1.0},
            {"ignore_cancel": "sí"}, {"stdout_noise": 1}, {"sleep": 1},
            {"op": "matmul", "fail_at": 1}, {"op": "matmul", "n": 4001},
            {"op": "matmul", "repeats": 0}, {"op": "matmul", "repeats": 11},
            {"op": "chunked_sum", "repeats": 2},
        ]
        request_invalid = messages.MESSAGES["request_invalid"]
        for params in cases:
            with self.subTest(params=params):
                ctx = self.context(params)
                with self.assertRaises(JobFailed) as caught:
                    selftest.run(ctx)
                error = caught.exception
                self.assertEqual(error.code, "request_invalid")
                self.assertEqual(error.msgid, request_invalid.msgid)
                self.assertEqual(error.values["job"], LABEL)
                self.assertIn(LABEL, error.text)
                self.assertEqual(ctx.progress_events, [])
                self.assertEqual(self.outputs_on_disk(), [])

    def test_non_finite_seconds_are_rejected(self):
        """Una espera NaN o infinita (no llega en JSON, pero sí en un diccionario) es
        ``request_invalid``."""
        for seconds in (math.nan, math.inf):
            with self.subTest(seconds=seconds), self.assertRaises(messages.JobError) as caught:
                selftest.SelftestParams.from_params({"sleep_s": seconds}, job=LABEL)
            self.assertEqual(caught.exception.code, "request_invalid")


class EstimateAndEnvironmentTest(unittest.TestCase):
    """RF-004-03: estimador y entorno del autodiagnóstico (plan §5.4.1, calibrado con §2.1)."""

    def test_chunked_sum_estimate(self):
        """``chunks · sleep_s + n / 1,5·10⁹`` s: la del menú (20 × 0,5 s) son 10 s."""
        self.assertAlmostEqual(selftest.estimate_s({"chunks": 20, "sleep_s": 0.5}),
                               10.0 + 20_000 / 1.5e9)
        self.assertAlmostEqual(selftest.estimate_s({"n": 1_500_000_000}), 1.0)
        self.assertAlmostEqual(selftest.estimate_s({}), 20_000 / 1.5e9)

    def test_matmul_estimate(self):
        """Producto con el numpy de Blender hasta n = 1000 (0,52 s a n = 1000, cúbico) y
        con el motor por encima (0,041 s a n = 2000), por el número de repeticiones."""
        self.assertAlmostEqual(selftest.estimate_s({"op": "matmul", "n": 1000}), 3 * 0.52)
        self.assertAlmostEqual(selftest.estimate_s({"op": "matmul", "n": 500, "repeats": 1}),
                               0.52 / 8)
        self.assertAlmostEqual(selftest.estimate_s({"op": "matmul", "n": 2000}), 3 * 0.041)

    def test_unknown_estimates(self):
        """Caída provocada, ruido en el descriptor 1 o parámetros que no valen: duración
        desconocida (``None``), que lleva a proceso aparte."""
        for params in ({"crash_at": 1}, {"stdout_noise": True}, {"op": "nada"}, {"n": 0}):
            with self.subTest(params=params):
                self.assertIsNone(selftest.estimate_s(params))

    def test_environment(self):
        """``matmul`` con n > 1000 exige el motor (``compute``); lo demás, ``blender``."""
        cases = [({"op": "matmul", "n": 1001}, "compute"), ({"op": "matmul"}, "compute"),
                 ({"op": "matmul", "n": 1000}, "blender"), ({}, "blender"),
                 ({"n": 10**9}, "blender"), ({"op": "nada"}, "blender")]
        for params, expected in cases:
            with self.subTest(params=params):
                self.assertEqual(selftest.environment(params), expected)


class SelftestMessagesTest(unittest.TestCase):
    """Constitución, principio 10: los mensajes propios del autodiagnóstico."""

    def test_messages_have_english_msgid_and_spanish_text(self):
        """Cada mensaje: ``msgid`` en inglés, texto en español, los mismos marcadores; y su
        traducción en ``CATALOG_ES`` (para ``core.i18n.install``)."""
        self.assertEqual(set(selftest.MESSAGES),
                         {"selftest_failed", "selftest_crash_inprocess"})
        for code, message in selftest.MESSAGES.items():
            with self.subTest(code=code):
                self.assertEqual(message.code, code)
                self.assertIsNone(SPANISH_LETTERS.search(message.msgid))
                self.assertTrue(message.es.strip())
                self.assertEqual(i18n.placeholders(message.msgid),
                                 i18n.placeholders(message.es))
                self.assertEqual(selftest.CATALOG_ES[message.msgid], message.es)
                self.assertNotIn(code, messages.MESSAGES)  # no pisa los de jobs/messages.py


if __name__ == "__main__":
    unittest.main()
