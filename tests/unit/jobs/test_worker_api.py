# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que usa la función de un trabajo en los dos ejecutores (spec 004, T07; HU-004-1;
RF-004-05, RF-004-09; plan 004 §5.2.3, §5.3.1 y §5.4.5).

``jobs/worker_api.py``: ``WorkerContext`` (lo que recibe ``run(ctx)`` en el hilo y en el
proceso aparte), ``JobCancelled``, ``JobFailed`` y los sumideros de eventos: el canal (el
stdout original del worker) y la cola del ejecutor en hilo. Todo se prueba aquí sin lanzar
ningún proceso.

- Avance (plan §5.2.3): como mucho 10 eventos por segundo, y siempre se envía el último (el
  más reciente de los retenidos llega en cuanto toca y, al acabar, sin esperar).
- RF-004-09: ``check_cancelled`` ve el centinela ``cancel`` de la carpeta (el del proceso
  aparte; mirado como mucho cada 50 ms) y el aviso del hilo (``threading.Event``, al
  momento); ``progress`` también comprueba la cancelación.
- ``output_path`` siempre dentro de ``out/``: lo que sale de ella se rechaza.
- RF-004-05: ``add_output`` declara el resultado con su sha256 y su tamaño, relativo a la
  carpeta del trabajo; fuera de ``out/``, no.
"""

import hashlib
import io
import json
import os
import platform
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender

worker_api = import_geoblender("jobs.worker_api")
protocol = import_geoblender("jobs.protocol")
paths = import_geoblender("jobs.paths")
messages = import_geoblender("jobs.messages")
selftest = import_geoblender("jobs.selftest")

WorkerContext = worker_api.WorkerContext
StreamSink = worker_api.StreamSink
QueueSink = worker_api.QueueSink
JobCancelled = worker_api.JobCancelled
JobFailed = worker_api.JobFailed
JobEvent = protocol.JobEvent
OutputRef = protocol.OutputRef

LABEL = "Autodiagnóstico: suma por trozos"
INTERVAL = worker_api.PROGRESS_INTERVAL_S
EPSILON = 1e-9


class _Clock:
    """Reloj monótono simulado: solo avanza cuando la prueba lo dice."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _ListSink:
    """Sumidero que guarda los eventos (para mirar qué y cuándo se envía)."""

    def __init__(self) -> None:
        self.events: list = []

    def send(self, event) -> None:
        self.events.append(event)

    def of(self, kind: str) -> list:
        return [event for event in self.events if event.type == kind]


class _FlushCounter(io.BytesIO):
    """Flujo binario que cuenta sus ``flush``."""

    def __init__(self) -> None:
        super().__init__()
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1
        super().flush()


class _ContextCase(unittest.TestCase):
    """Una raíz de trabajos temporal por prueba y la carpeta de un trabajo ya creada."""

    def setUp(self) -> None:
        tmp = _support.temp_jobs_root()
        self.root = tmp.__enter__()
        self.addCleanup(tmp.__exit__, None, None, None)
        self.clock = _Clock()
        self.sink = _ListSink()

    def request(self, **options):
        return protocol.new_request(
            "selftest", label=LABEL, owner="jobs", environment="blender", timeout_s=600,
            **options,
        )

    def job(self, request):
        return paths.job_dir(self.root, request.job_uid).create()

    def context(self, *, request=None, sink=None, real_clock=False, **options):
        request = request or self.request()
        job = self.job(request)
        clock = time.monotonic if real_clock else self.clock
        return WorkerContext(request, job, sink or self.sink, clock=clock, **options)


class ProgressRateTest(_ContextCase):
    """Plan §5.2.3: como mucho 10 avances por segundo, enviando siempre el último."""

    def test_at_most_ten_per_second_and_the_last_one_always(self):
        """1000 avances en 1 s (uno por ms): como mucho 10 enviados en ese segundo, separados
        al menos 0,1 s, y al acabar (``flush``) llega el último, 1,0 «Paso 999»."""
        ctx = self.context()
        sent_at: list[float] = []
        for step in range(1000):
            self.clock.t = step / 1000
            before = len(self.sink.events)
            ctx.progress(step / 999, f"Paso {step}")
            if len(self.sink.events) > before:
                sent_at.append(self.clock.t)
        self.assertLessEqual(len(sent_at), 10)
        self.assertGreaterEqual(len(sent_at), 9)
        for earlier, later in zip(sent_at, sent_at[1:], strict=False):
            self.assertGreaterEqual(later - earlier, INTERVAL - EPSILON)
        self.assertNotEqual(self.sink.events[-1].msg, "Paso 999")
        ctx.flush()
        last = self.sink.events[-1]
        self.assertEqual((last.type, last.frac, last.msg), ("progress", 1.0, "Paso 999"))
        self.assertEqual(len(self.sink.of("progress")), len(sent_at) + 1)

    def test_the_newest_held_value_is_sent(self):
        """Lo retenido no se acumula: cuando toca, se envía el avance más reciente (0,7), no
        el primero que se retuvo (0,3)."""
        ctx = self.context()
        for t, frac in ((0.0, 0.0), (0.03, 0.3), (0.06, 0.6), (0.12, 0.7)):
            self.clock.t = t
            ctx.progress(frac, f"{frac}")
        self.assertEqual([e.frac for e in self.sink.of("progress")], [0.0, 0.7])

    def test_held_progress_goes_out_when_due_on_check_cancelled(self):
        """Un cálculo que solo mira la cancelación (sin más avances) envía lo retenido en
        cuanto pasan 0,1 s: la interfaz no se queda atrás."""
        ctx = self.context()
        ctx.progress(0.1, "uno")
        self.clock.t = 0.05
        ctx.progress(0.2, "dos")
        ctx.check_cancelled()
        self.assertEqual([e.frac for e in self.sink.of("progress")], [0.1])
        self.clock.t = 0.2
        ctx.check_cancelled()
        self.assertEqual([e.frac for e in self.sink.of("progress")], [0.1, 0.2])
        ctx.flush()  # ya no queda nada retenido
        self.assertEqual(len(self.sink.of("progress")), 2)

    def test_log_does_not_bring_held_progress_forward(self):
        """Una nota del registro no adelanta el avance retenido antes de tiempo (los avances
        siguen a ≤ 10/s); si ya toca, el avance va antes que la nota, en orden."""
        ctx = self.context()
        ctx.progress(0.1)
        self.clock.t = 0.02
        ctx.progress(0.2)
        ctx.log("info", "primera nota")
        self.assertEqual([e.type for e in self.sink.events], ["progress", "log"])
        self.clock.t = 0.15
        ctx.log("warning", "segunda nota")
        self.assertEqual([(e.type, e.frac) for e in self.sink.events],
                         [("progress", 0.1), ("log", None), ("progress", 0.2), ("log", None)])
        self.assertEqual(self.sink.events[-1].level, "warning")

    def test_emit_sends_the_held_progress_first(self):
        """Los eventos del ejecutor (``result``…) van después del último avance retenido."""
        ctx = self.context()
        ctx.progress(0.5)
        ctx.progress(1.0, "Hecho")
        ctx.emit(JobEvent.result((), {"sum": 3}))
        self.assertEqual([(e.type, e.frac) for e in self.sink.events],
                         [("progress", 0.5), ("progress", 1.0), ("result", None)])

    def test_flush_with_nothing_held_sends_nothing(self):
        """``flush`` sin avance retenido no envía nada."""
        ctx = self.context()
        ctx.flush()
        ctx.progress(0.3)
        ctx.flush()
        self.assertEqual([e.frac for e in self.sink.events], [0.3])

    def test_sent_events_are_stamped_in_order(self):
        """El avance retenido sale con la hora de su envío: las horas (``ts``) del canal no
        retroceden."""
        ctx = self.context()
        ctx.progress(0.1)
        ctx.progress(0.2)
        time.sleep(0.002)
        ctx.log("info", "nota")
        ctx.flush()
        stamps = [event.ts for event in self.sink.events]
        self.assertEqual(stamps, sorted(stamps))

    def test_real_clock_tight_loop(self):
        """Con el reloj real, 5000 avances seguidos no inundan el canal: como mucho uno por
        cada 0,1 s transcurridos (más el primero y el último)."""
        ctx = self.context(real_clock=True)
        start = time.monotonic()
        for step in range(5000):
            ctx.progress(step / 4999)
        ctx.flush()
        elapsed = time.monotonic() - start
        progress = self.sink.of("progress")
        self.assertLessEqual(len(progress), 2 + int(elapsed / INTERVAL))
        self.assertEqual(progress[-1].frac, 1.0)

    def test_progress_is_validated_and_clamped(self):
        """El avance es una fracción: fuera de 0–1 se acota; NaN o un texto, ``ValueError``
        sin enviar nada."""
        ctx = self.context()
        for bad in (float("nan"), "0,5", None):
            with self.subTest(frac=bad), self.assertRaises(ValueError):
                ctx.progress(bad)
        self.assertEqual(self.sink.events, [])
        ctx.progress(1.5)
        self.assertEqual(self.sink.events[0].frac, 1.0)


class CancellationTest(_ContextCase):
    """RF-004-09: el centinela ``cancel`` y el aviso del hilo."""

    def test_nothing_requested(self):
        """Sin centinela ni aviso, ``check_cancelled`` y ``progress`` no lanzan."""
        ctx = self.context(cancel_event=threading.Event())
        ctx.check_cancelled()
        ctx.progress(0.5)

    def test_sentinel_file(self):
        """RF-004-09: el centinela ``cancel`` en la carpeta del trabajo (el que crea el
        lanzador del proceso aparte) → ``JobCancelled``."""
        ctx = self.context()
        ctx.job_dir.cancel_file.touch()
        with self.assertRaises(JobCancelled):
            ctx.check_cancelled()

    def test_thread_event(self):
        """RF-004-09: el aviso del hilo (``threading.Event``, el ejecutor en hilo) se ve al
        momento, sin centinela y sin esperar a que toque mirar el disco."""
        event = threading.Event()
        ctx = self.context(cancel_event=event)
        ctx.check_cancelled()
        event.set()
        with self.assertRaises(JobCancelled):
            ctx.check_cancelled()
        self.assertFalse(ctx.job_dir.cancel_file.exists())

    def test_sentinel_is_looked_at_most_every_50_ms(self):
        """El disco se mira como mucho cada 50 ms (un bucle que comprueba sin parar no
        castiga el disco); el centinela creado se ve en ≤ 50 ms."""
        ctx = self.context()
        ctx.check_cancelled()
        ctx.job_dir.cancel_file.touch()
        self.clock.t = 0.01
        ctx.check_cancelled()
        self.clock.t = worker_api.CANCEL_POLL_S
        with self.assertRaises(JobCancelled):
            ctx.check_cancelled()

    def test_cancellation_is_not_withdrawn(self):
        """Una cancelación vista no se deshace aunque desaparezca el centinela."""
        ctx = self.context()
        ctx.job_dir.cancel_file.touch()
        with self.assertRaises(JobCancelled):
            ctx.check_cancelled()
        ctx.job_dir.cancel_file.unlink()
        self.clock.t = 1.0
        with self.assertRaises(JobCancelled):
            ctx.check_cancelled()

    def test_progress_checks_cancellation(self):
        """RF-004-09: ``progress`` comprueba la cancelación (después de anotar el avance)."""
        event = threading.Event()
        ctx = self.context(cancel_event=event)
        event.set()
        with self.assertRaises(JobCancelled) as caught:
            ctx.progress(0.4, "Trozo 2 de 5")
        self.assertTrue(str(caught.exception))
        self.assertEqual([e.frac for e in self.sink.of("progress")], [0.4])

    def _loop_until_cancelled(self, ctx) -> list:
        """Un cálculo en otro hilo que mira la cancelación cada ms; devuelve lo que acabó."""
        ended: list = []

        def work():
            try:
                while True:
                    ctx.check_cancelled()
                    time.sleep(0.001)
            except JobCancelled as exc:
                ended.append((time.monotonic(), exc))

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        return ended

    def test_another_thread_stops_quickly_with_the_event(self):
        """RF-004-09: un cálculo en otro hilo para en ≤ 0,2 s tras activar el aviso."""
        event = threading.Event()
        ctx = self.context(cancel_event=event, real_clock=True)
        ended = self._loop_until_cancelled(ctx)
        time.sleep(0.05)
        asked = time.monotonic()
        event.set()
        deadline = asked + 2
        while not ended and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(ended, "el cálculo no paró")
        self.assertLess(ended[0][0] - asked, 0.2)

    def test_another_thread_stops_quickly_with_the_sentinel(self):
        """RF-004-09: un cálculo en otro hilo para en ≤ 0,2 s tras crear el centinela."""
        ctx = self.context(real_clock=True)
        ended = self._loop_until_cancelled(ctx)
        time.sleep(0.05)
        asked = time.monotonic()
        ctx.job_dir.cancel_file.touch()
        deadline = asked + 2
        while not ended and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(ended, "el cálculo no paró")
        self.assertLess(ended[0][0] - asked, 0.2)

    def test_selftest_stops_within_two_seconds(self):
        """RF-004-09: el autodiagnóstico con el contexto de verdad (un trozo de 30 s) para en
        < 1 s tras crear el centinela: «Cancelado en el trozo 1 de 1» y sin resultado."""
        request = self.request(params={"chunks": 1, "sleep_s": 30})
        ctx = self.context(request=request, real_clock=True)
        timer = threading.Timer(0.2, ctx.job_dir.cancel_file.touch)
        timer.start()
        self.addCleanup(timer.cancel)
        start = time.monotonic()
        with self.assertRaises(JobCancelled) as caught:
            selftest.run(ctx)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertEqual(str(caught.exception), "Cancelado en el trozo 1 de 1")
        self.assertEqual(list(ctx.job_dir.outputs_dir.iterdir()), [])
        self.assertEqual(ctx.outputs, ())


class OutputPathTest(_ContextCase):
    """``output_path`` siempre dentro de ``out/`` (plan §5.3.1)."""

    def test_inside_out(self):
        """Un nombre, o una ruta relativa con «/» o «\\», queda dentro de ``out/``; las
        subcarpetas se crean."""
        ctx = self.context()
        out = ctx.job_dir.outputs_dir
        self.assertEqual(ctx.output_path("sum.npy"), out / "sum.npy")
        nested = ctx.output_path("mallas/capa 1.npy")
        self.assertEqual(nested, out / "mallas" / "capa 1.npy")
        self.assertTrue(nested.parent.is_dir())
        self.assertEqual(ctx.output_path("mallas\\b\\c.npz"), out / "mallas" / "b" / "c.npz")
        self.assertEqual(ctx.output_path(Path("vértices.npy")), out / "vértices.npy")

    def test_outside_out_is_rejected(self):
        """Lo que sale de ``out/`` (``..``, absoluto, unidad, red, flujo alternativo) o no es
        un nombre de fichero válido en Windows se rechaza con ``ValueError`` que nombra la
        ruta, sin crear nada fuera de ``out/``."""
        ctx = self.context()
        before = sorted(p.relative_to(self.root.parent) for p in self.root.parent.rglob("*"))
        bad = [
            "", ".", "..", "../x.npy", "..\\x.npy", "a/../../x.npy", "mallas/../x.npy",
            "a/.. /x.npy", "/x.npy", "\\x.npy", "C:\\x.npy", "C:x.npy", "c:/x.npy",
            "\\\\srv\\recurso\\x.npy", "//srv/recurso/x.npy", "\\\\?\\C:\\x.npy",
            "x.npy:flujo", "a//b.npy", "mallas/", "x.npy.", "x.npy ", "a<b.npy", "a|b",
            "tab\t.npy", "nul", "CON.txt", "mallas/aux.npy", "com1",
        ]
        for name in bad:
            with self.subTest(name=name), self.assertRaises(ValueError) as caught:
                ctx.output_path(name)
            self.assertIn("out/", str(caught.exception))
        after = sorted(p.relative_to(self.root.parent) for p in self.root.parent.rglob("*"))
        self.assertEqual(after, before)

    def test_not_a_name(self):
        """Lo que no es un texto ni una ruta es ``ValueError``."""
        ctx = self.context()
        for bad in (None, 3, b"x.npy", Path("C:/x.npy")):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                ctx.output_path(bad)


class AddOutputTest(_ContextCase):
    """RF-004-05: cada resultado se declara con su sha256 y su tamaño."""

    def test_sha256_and_size(self):
        """RF-004-05: 3 MiB + 17 bytes (varios bloques) → la huella sha256 y el tamaño del
        fichero, la ruta ``out/…`` con «/» y su papel; queda en ``outputs``."""
        ctx = self.context()
        data = os.urandom(3 * (1 << 20) + 17)
        path = ctx.output_path("mallas/datos.bin")
        path.write_bytes(data)
        ref = ctx.add_output(path, "mesh")
        self.assertEqual(ref, OutputRef("out/mallas/datos.bin",
                                        hashlib.sha256(data).hexdigest(), len(data), "mesh"))
        self.assertEqual(ref.sha256, _support.sha256_file(path))
        self.assertEqual(ctx.outputs, (ref,))

    def test_relative_to_the_job_folder(self):
        """Una ruta relativa se entiende desde la carpeta del trabajo (con «/» o «\\»)."""
        ctx = self.context()
        ctx.output_path("sum.npy").write_bytes(b"suma")
        first = ctx.add_output("out/sum.npy", "sum")
        second = ctx.add_output(Path("out\\sum.npy"), "sum")
        self.assertEqual(first, second)
        self.assertEqual(first.path, "out/sum.npy")
        self.assertEqual(len(ctx.outputs), 1)

    def test_outside_out_is_rejected(self):
        """Un fichero de la carpeta del trabajo fuera de ``out/`` (``in/``, ``job.log``) o
        de fuera de la carpeta no se declara: ``ValueError`` y nada en ``outputs``."""
        ctx = self.context()
        folder = ctx.job_dir.path
        log = folder / "job.log"
        log.write_text("registro\n", encoding="utf-8")
        entry = ctx.job_dir.inputs_dir / "datos.npy"
        entry.write_bytes(b"entrada")
        elsewhere = self.root.parent / "fuera.npy"
        elsewhere.write_bytes(b"fuera")
        cases = [log, entry, elsewhere, "job.log", "out/../job.log", "in/datos.npy",
                 "../fuera.npy", folder / "out" / ".." / "job.log"]
        for path in cases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                ctx.add_output(path, "x")
        self.assertEqual(ctx.outputs, ())

    def test_missing_file_or_folder(self):
        """Un resultado que no existe o que es una carpeta no se declara."""
        ctx = self.context()
        with self.assertRaises(FileNotFoundError):
            ctx.add_output(ctx.output_path("nada.npy"), "x")
        folder = ctx.output_path("mallas/x.npy").parent
        with self.assertRaises(IsADirectoryError):
            ctx.add_output(folder, "x")
        self.assertEqual(ctx.outputs, ())

    def test_role_is_required(self):
        """Sin papel (``role``), ``ValueError``."""
        ctx = self.context()
        ctx.output_path("a.npy").write_bytes(b"a")
        for role in ("", "  ", None):
            with self.subTest(role=role), self.assertRaises(ValueError):
                ctx.add_output("out/a.npy", role)
        self.assertEqual(ctx.outputs, ())

    def test_declared_again_keeps_the_last_hash(self):
        """Un resultado reescrito y declarado otra vez queda una vez, con la huella nueva y
        en su sitio."""
        ctx = self.context()
        a = ctx.output_path("a.npy")
        a.write_bytes(b"uno")
        ctx.add_output(a, "a")
        ctx.output_path("b.npy").write_bytes(b"b")
        ctx.add_output("out/b.npy", "b")
        a.write_bytes(b"dos")
        ctx.add_output(a, "a")
        self.assertEqual([ref.path for ref in ctx.outputs], ["out/a.npy", "out/b.npy"])
        self.assertEqual(ctx.outputs[0].sha256, hashlib.sha256(b"dos").hexdigest())


class InputPathTest(_ContextCase):
    """Las entradas declaradas en la petición (``in/…``)."""

    def test_declared_input(self):
        """La entrada declarada es su fichero de ``in/``, que se lee bit a bit."""
        array = np.array([4_400_000.456, np.nan, -0.0], dtype=np.float64)
        request = self.request(inputs={"datos": "in/datos.npy"})
        job = self.job(request)
        self.assertEqual(job.write_array("datos", array), "in/datos.npy")
        ctx = WorkerContext(request, job, self.sink)
        path = ctx.input_path("datos")
        self.assertEqual(path, job.inputs_dir / "datos.npy")
        self.assertEqual(np.load(path, allow_pickle=False).tobytes(), array.tobytes())

    def test_undeclared_or_missing_input(self):
        """Una entrada que la petición no declara, o declarada sin fichero, es un fallo
        explicado (``request_invalid``, que nombra el trabajo y la entrada)."""
        request = self.request(inputs={"datos": "in/datos.npy"})
        ctx = WorkerContext(request, self.job(request), self.sink)
        for name in ("collares", "datos"):
            with self.subTest(name=name), self.assertRaises(JobFailed) as caught:
                ctx.input_path(name)
            error = caught.exception
            self.assertEqual(error.code, "request_invalid")
            self.assertIn(LABEL, error.text)
            self.assertIn(name, error.text)


class ContextTest(_ContextCase):
    """El contexto: su petición, su carpeta y las notas del registro."""

    def test_request_and_job_dir(self):
        """El contexto da la petición y la carpeta (``JobDir``), también si se le pasa la
        ruta de la carpeta."""
        request = self.request()
        job = self.job(request)
        ctx = WorkerContext(request, job.path, self.sink)
        self.assertIs(ctx.request, request)
        self.assertEqual(ctx.job_dir, job)
        self.assertEqual(ctx.outputs, ())

    def test_folder_of_another_job_is_rejected(self):
        """La carpeta tiene que ser la del trabajo de la petición."""
        other = self.job(self.request())
        with self.assertRaises(ValueError):
            WorkerContext(self.request(), other, self.sink)

    def test_log(self):
        """``log`` envía una nota con su nivel; un nivel desconocido es ``ValueError`` sin
        enviar nada."""
        ctx = self.context()
        ctx.log("warning", "La serie «Miocena» no tiene orientaciones")
        [event] = self.sink.events
        self.assertEqual((event.type, event.level), ("log", "warning"))
        self.assertIn("Miocena", event.msg)
        with self.assertRaises(ValueError):
            ctx.log("aviso", "x")
        self.assertEqual(len(self.sink.events), 1)


class SinkTest(_ContextCase):
    """Los sumideros de eventos: el canal (stdout original del worker) y la cola."""

    def _events(self, request):
        ref = OutputRef("out/sum.npy", "a" * 64, 136, "sum")
        return [
            JobEvent.start({"pid": 4120, "kind": "blender", "python": "3.13.9"}),
            JobEvent.progress(0.42, "Trozo 9 de 20"),
            JobEvent.log("warning", "Línea con «ñ»\ny un salto"),
            JobEvent.result([ref], {"sum": 199_990_000, "trabajo": request.label}),
            JobEvent.error("selftest_failed", msgid="Self-test failed", msg="Falló",
                           values={"chunk": 3}),
            JobEvent.cancelled("Cancelado en el trozo 11 de 20"),
        ]

    def test_stream_sink_binary(self):
        """Un evento por línea en UTF-8, que el decodificador del lanzador lee igual."""
        stream = _FlushCounter()
        sink = StreamSink(stream)
        events = self._events(self.request())
        for event in events:
            sink.send(event)
        data = stream.getvalue()
        self.assertEqual(data.count(b"\n"), len(events))
        self.assertEqual(data, b"".join(protocol.encode_event(e) for e in events))
        self.assertEqual(protocol.EventDecoder().feed(data), events)
        self.assertGreaterEqual(stream.flushes, len(events))

    def test_stream_sink_text(self):
        """Con un flujo de texto (UTF-8, «\\n») escribe los mismos bytes."""
        raw = io.BytesIO()
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")
        events = self._events(self.request())
        sink = StreamSink(text)
        for event in events:
            sink.send(event)
        self.assertEqual(raw.getvalue(), b"".join(protocol.encode_event(e) for e in events))

    def test_stream_sink_threads_do_not_mix_lines(self):
        """8 hilos × 100 eventos a la vez: todas las líneas son eventos enteros."""
        stream = io.BytesIO()
        sink = StreamSink(stream)
        text = "x" * 5000

        def send(index):
            for step in range(100):
                sink.send(JobEvent.log("info", f"{index}:{step}:{text}"))

        threads = [threading.Thread(target=send, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        decoded = protocol.EventDecoder().feed(stream.getvalue())
        self.assertEqual(len(decoded), 800)
        self.assertTrue(all(isinstance(item, JobEvent) for item in decoded))

    def test_queue_sink(self):
        """La cola recibe los mismos eventos, en orden; ``drain`` los saca sin esperar."""
        sink = QueueSink()
        events = self._events(self.request())
        for event in events:
            sink.send(event)
        self.assertEqual(sink.drain(), events)
        self.assertEqual(sink.drain(), [])
        own = queue.Queue()
        QueueSink(own).send(events[0])
        self.assertIs(own.get_nowait(), events[0])

    def test_both_sinks_reject_an_oversized_event(self):
        """Lo que no cabe en el canal (> 1 MiB) tampoco pasa por la cola: el mismo
        ``ValueError`` en los dos ejecutores, y nada enviado."""
        big = JobEvent.result((), {"texto": "x" * (protocol.MAX_EVENT_BYTES + 1)})
        stream = io.BytesIO()
        sink = QueueSink()
        for target in (StreamSink(stream), sink):
            with self.subTest(sink=type(target).__name__), self.assertRaises(ValueError):
                target.send(big)
        self.assertEqual(stream.getvalue(), b"")
        self.assertEqual(sink.drain(), [])

    def test_selftest_through_both_sinks(self):
        """HU-004-1, RF-004-05: el autodiagnóstico con el contexto de verdad da la misma
        secuencia por el canal y por la cola: nota, avances (el último, 1,0) y el resultado
        con ``out/sum.npy`` y su huella."""
        sequences = []
        for kind in ("canal", "cola"):
            with self.subTest(sink=kind):
                request = self.request(params={"chunks": 4})
                stream = io.BytesIO()
                sink = StreamSink(stream) if kind == "canal" else QueueSink()
                # Reloj simulado y parado: el mismo reparto de avances en los dos casos.
                ctx = self.context(request=request, sink=sink)
                summary = selftest.run(ctx)
                ctx.emit(JobEvent.result(ctx.outputs, summary))
                events = (protocol.EventDecoder().feed(stream.getvalue()) if kind == "canal"
                          else sink.drain())
                kinds = [event.type for event in events]
                self.assertEqual(kinds[0], "log")
                self.assertEqual(kinds[-1], "result")
                progress = [event for event in events if event.type == "progress"]
                self.assertEqual(progress[-1].frac, 1.0)
                self.assertEqual(progress[-1].msg, "Trozo 4 de 4")
                [ref] = events[-1].outputs
                path = ctx.job_dir.path / ref.path
                self.assertEqual((ref.path, ref.role), ("out/sum.npy", "sum"))
                self.assertEqual(ref.sha256, _support.sha256_file(path))
                self.assertEqual(events[-1].summary["sum"], 20_000 * 19_999 // 2)
                sequences.append([(e.type, e.frac) for e in events])
        self.assertEqual(sequences[0], sequences[1])


class JobFailedTest(unittest.TestCase):
    """RF-004-12: el fallo explicado de un cálculo."""

    def test_job_failed(self):
        """Código, ``msgid``, valores (JSON) y texto en español, que es ``str(error)``."""
        error = JobFailed("engine_missing_orientation", msgid="Series {series} has no "
                          "orientations", text="La serie «Miocena» no tiene orientaciones",
                          values={"series": "Miocena"})
        self.assertEqual(error.code, "engine_missing_orientation")
        self.assertEqual(error.values, {"series": "Miocena"})
        self.assertEqual(str(error), "La serie «Miocena» no tiene orientaciones")

    def test_job_failed_needs_its_texts(self):
        """Sin código, ``msgid`` o texto, o con valores que no son JSON, ``ValueError``."""
        good = {"code": "x_y", "msgid": "X", "text": "Equis"}
        for name in ("code", "msgid", "text"):
            with self.subTest(field=name), self.assertRaises(ValueError):
                JobFailed(**{**good, name: " "})
        with self.assertRaises(ValueError):
            JobFailed(**good, values={"n": float("nan")})

    def test_from_error(self):
        """De un ``JobError`` del catálogo: el mismo código, ``msgid``, valores y texto."""
        error = messages.JobError("worker_unknown", worker="nada")
        failed = JobFailed.from_error(error)
        self.assertEqual((failed.code, failed.msgid, failed.text, failed.values),
                         ("worker_unknown", error.msgid, error.text, {"worker": "nada"}))


class FinishTest(_ContextCase):
    """Spec 004, T08 (RF-004-15): el cierre de un trabajo que terminó bien y el orden de las
    horas del canal con los eventos del ejecutor."""

    def test_executor_event_created_before_the_flush_keeps_times_in_order(self):
        """RF-004-15: un evento del ejecutor creado antes del avance retenido sale después
        de él y con una hora que no retrocede; ``emit`` devuelve el evento enviado."""
        ctx = self.context()
        ctx.progress(0.5)
        ctx.progress(1.0, "Hecho")  # retenido: el reloj simulado está parado
        early = JobEvent.cancelled("Cancelado en el trozo 2 de 2", ts=time.time() - 60)
        sent = ctx.emit(early)
        self.assertEqual([e.type for e in self.sink.events], ["progress", "progress",
                                                               "cancelled"])
        self.assertIs(sent, self.sink.events[-1])
        self.assertEqual(sent.msg, early.msg)
        stamps = [event.ts for event in self.sink.events]
        self.assertEqual(stamps, sorted(stamps))

    def test_finish_writes_result_json_and_sends_the_result(self):
        """RF-004-15: ``finish`` envía el último avance, deja el evento ``result`` (resultados
        declarados y resumen) en ``result.json`` (UTF-8 sin BOM) y lo envía el último."""
        ctx = self.context()
        path = ctx.output_path("dato.bin")
        path.write_bytes(b"geoblender")
        ref = ctx.add_output(path, "dato")
        ctx.progress(0.5)
        ctx.progress(1.0, "Hecho")
        event = ctx.finish({"suma": 3, "nota": "año"})
        self.assertEqual([e.type for e in self.sink.events], ["progress", "progress",
                                                               "result"])
        self.assertIs(event, self.sink.events[-1])
        self.assertEqual((event.outputs, dict(event.summary)),
                         ((ref,), {"suma": 3, "nota": "año"}))
        raw = ctx.job_dir.result_file.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(JobEvent.from_json(json.loads(raw.decode("utf-8"))), event)
        self.assertEqual(list(ctx.job_dir.path.glob("*.partial")), [])
        stamps = [e.ts for e in self.sink.events]
        self.assertEqual(stamps, sorted(stamps))

    def test_finish_without_summary(self):
        """Sin resumen (``None``), el resultado lleva un resumen vacío."""
        ctx = self.context()
        self.assertEqual(dict(ctx.finish().summary), {})
        self.assertTrue(ctx.job_dir.result_file.is_file())

    def test_bad_summary_writes_and_sends_nothing(self):
        """Un resumen que no es un objeto JSON es ``ValueError``: ni ``result.json`` ni
        evento, ni siquiera el avance retenido."""
        ctx = self.context()
        ctx.progress(0.5)
        ctx.progress(1.0)
        for summary in (["no", "objeto"], {"x": float("nan")}, {"x": object()}):
            with self.subTest(summary=summary), self.assertRaises(ValueError):
                ctx.finish(summary)
        self.assertEqual([e.frac for e in self.sink.events], [0.5])
        self.assertFalse(ctx.job_dir.result_file.exists())
        self.assertEqual(list(ctx.job_dir.path.glob("*.partial")), [])


class InterpreterInfoTest(unittest.TestCase):
    """Spec 004, T08 (RF-004-15): lo que cuenta el evento ``start`` del intérprete."""

    def test_info_of_this_interpreter(self):
        """RF-004-15: pid, tipo, versión de Python y versiones de numpy y de su BLAS."""
        info = worker_api.interpreter_info("blender")
        blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]["name"]
        self.assertEqual(info, {"pid": os.getpid(), "kind": "blender",
                                "python": platform.python_version(),
                                "numpy": np.__version__, "blas": blas})
        self.assertEqual(JobEvent.start(info).info, info)

    def test_kinds(self):
        """Solo ``blender``, ``compute`` y ``external``."""
        for kind in ("blender", "compute", "external"):
            self.assertEqual(worker_api.interpreter_info(kind)["kind"], kind)
        for kind in ("", "Blender", "python", None):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                worker_api.interpreter_info(kind)

    def test_without_numpy(self):
        """Un intérprete sin numpy: numpy y BLAS vacíos (``None``)."""
        with mock.patch.dict(sys.modules, {"numpy": None}):
            info = worker_api.interpreter_info("external")
        self.assertEqual((info["numpy"], info["blas"]), (None, None))

    def test_blas_name_unknown(self):
        """Un numpy que no dice su BLAS da ``unknown``."""
        self.assertEqual(worker_api.blas_name(object()), worker_api.UNKNOWN_BLAS)
        self.assertEqual(worker_api.UNKNOWN_BLAS, "unknown")


if __name__ == "__main__":
    unittest.main()
