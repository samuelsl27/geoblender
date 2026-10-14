# SPDX-License-Identifier: GPL-3.0-or-later
"""La topografía dentro de Blender sin interfaz (spec 006, T35, T50 y T54; RNF-006-03,
RNF-006-06, RNF-006-09; RNF-008-01; plan 006 §5.3.4, §5.4 A10, A11 y A15, §5.6.4, §7.2 y §9,
D-12).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py
-- --carpeta tests/rendimiento/blender --patron "perf_gis.py"``). Datos generados en la prueba
(en ``%TEMP%``, sin versionar) del tamaño de Silvestre: un proyecto de 1.700 × 1.655 m con su
rejilla de 1 m (:data:`WINDOW`), la superficie de colinas de :func:`surface` y, en él:

- RNF-006-03 (:meth:`GisSpeedTest.test_tin_order`): un levantamiento de 300.000 puntos
  (:func:`survey`: 289.900 sueltos y 100 líneas de rotura de 101 vértices, 10.000 tramos) en
  un CSV importado con la orden de la 006, y la orden «Crear TIN desde puntos» con él, desde que
  se lanza hasta que su operación queda hecha: la cadena entera (``gis_tin_prepare``, la CDT
  de Blender en el hilo principal desde su temporizador, ``gis_tin_finish`` y la incorporación,
  con el registro de la operación y la copia verificada del TIN con su hash), mediana de 5
  ≤ 5 s. Con 300.000 puntos, la estimación de la CDT (6,5 µs por punto, T23) es 1,95 s: dentro
  de la excepción de D-12 (más de 1 s y no más de 2 s), así que se avisa antes y corre en el
  hilo. RNF-008-01 (alineación con la 008): cada escritura en la base del proyecto durante la
  orden (empezar y terminar la operación) ≤ 0,1 s en disco local.
- RNF-006-09 (en esas cinco órdenes): la interfaz no pasa más de 0,5 s sin refrescar el
  progreso, salvo la llamada a la CDT (la excepción de D-12, que se avisa antes en la barra de
  estado y en los avisos, en un paso del temporizador anterior): (a) ninguna llamada del hilo
  principal (la orden, cada sondeo del monitor de trabajos con su incorporación, cada paso del
  temporizador de la triangulación) pasa de 0,5 s sin contar la CDT; (b) desde que se pulsa la
  orden hasta que queda hecha, entre dos refrescos del progreso (el final de la orden, que
  Blender redibuja con su aviso; cada sondeo del monitor, que redibuja la barra de estado; y el
  aviso de la triangulación) no pasan más de 0,5 s sin contar la CDT; y (c) cada trabajo de la
  cadena avisa de su avance al menos cada 0,5 s, desde que empieza hasta que acaba. De cada
  orden, su peor caso; se comprueba la mediana de las cinco (spec 006 §5: 5 repeticiones,
  mediana), y la línea da también el máximo. El peor suele ser el sondeo que incorpora el TIN
  (el intervalo del monitor, 0,25 s, más lo que dura: copiar el TIN de 8 MB al proyecto y
  comprobar sus huellas).
- RNF-006-09 (T50) al importar el levantamiento (una vez, al preparar la orden del TIN): desde
  la orden hasta su operación hecha, ninguna llamada del hilo principal pasa de 0,5 s ni pasa
  más de 0,5 s sin refrescar el progreso (el hash de las tablas lo hace su trabajo y la
  incorporación va por pasos desde su temporizador, ``bl.ops.gis.incorporation_tick``, que
  pone su avance en la barra de estado); el hash de cada tabla, el que calculó el trabajo, es
  el que da leerla en el proyecto (el mismo de antes de la T50).
- RNF-006-09 (T54; :meth:`GisSpeedTest.test_dtm_import`): importar el MDT de RNF-006-01
  (3.399 × 3.309 celdas de 0,5 m, float32 DEFLATE + predictor 3, generado como el de
  ``tests/rendimiento/gis``) con ``geoblender.gis_import_dtm``, la primera vez sin rejilla del
  proyecto y la segunda con la de 1 m (la comparación de cotas de RF-006-06): desde la orden
  hasta su operación hecha, ninguna llamada del hilo principal pasa de 0,5 s ni pasa más de
  0,5 s sin refrescar el progreso. La incorporación va por pasos desde su temporizador (antes
  de la T54, en el sondeo que terminaba el trabajo: 0,49 s y, con la comparación, 0,91 s).
- RNF-006-06 y RNF-006-09 (:meth:`GisSpeedTest.test_view_load`): cargar en la vista la rejilla
  de 1 m del proyecto (1.700 × 1.655 = 2.813.500 celdas, todas con dato) con
  ``geoblender.core_load_into_view`` como desde la interfaz (en pasos: el modal y, haciendo de
  temporizador de su ventana, un evento ``TIMER`` cada ``TIMER_INTERVAL_S``), con la
  comprobación de su malla, mediana de 5 ≤ 6 s; su versión de 5 m (340 × 331) ≤ 1 s; y en
  cada carga, ninguna llamada del hilo principal pasa de 0,5 s ni pasa más de 0,5 s sin
  refrescar el progreso (cada evento lo pone en la barra de estado).

En ``blender -b`` no hay bucle de eventos ni corren los temporizadores: la prueba hace de bucle
(:class:`_EventLoop`): anota cada temporizador que se registra y lo llama cuando le toca (el
``first_interval`` después de registrarlo; luego, lo que devolvió; con ``None`` lo retira,
como Blender), duerme entre medias y mide cada llamada; tras cada sondeo del monitor dibuja el
campo «jobs» de la barra de estado con un *layout* simulado (``FakeLayout``), como
``perf_jobs_monitor``. Los trabajos de la cadena (automáticos, en un hilo por su estimación)
se envuelven para anotar cada aviso de avance.

Hasta la T50, la importación del CSV de 300.000 filas (4,98 s en una llamada: el hash de la
tabla de 289.900 puntos y su escritura) y cargar la rejilla en la vista (4,25 s en una) salían
en dos líneas «Aviso RNF-006-09» sin presupuesto; ahora tienen el de RNF-006-09. Lo que solo
se ve con la interfaz (el primer dibujo de la malla en la Vista 3D, el paso de deshacer con
ventana, la barra de estado con el aviso de la triangulación y con el avance de la carga y de
la incorporación, Esc) queda para la comprobación en pantalla.
"""

import dataclasses
import gc
import os
import platform
import statistics
import sys
import time
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender.gis.test_ops_dtm import JOB_WAIT_S, MAX_TICKS, _module
from tests.blender.gis.test_ops_tin import TIN_POINTS, TinOperatorsCase
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import FakeLayout

IMPORT_POINTS = "geoblender.gis_import_points"
IMPORT_DTM = "geoblender.gis_import_dtm"
REPETITIONS = 5  # mediana de 5 (spec 006 §5)

# El proyecto: 1.700 × 1.655 m, rejilla de 1 m (2.813.500 celdas, la de RNF-006-02 y 05).
WEST = 700_000.0
SOUTH = 4_400_000.0
COLS = 1_700
ROWS = 1_655
WINDOW = (WEST, SOUTH, WEST + COLS, SOUTH + ROWS)
CELLS = COLS * ROWS
LOD_STEP_M = 5.0  # el segundo nivel de detalle (gis.view.lod_steps_m: 2 y 5 m)

# El levantamiento de RNF-006-03: 300.000 puntos, de ellos 100 líneas de rotura de 101 vértices.
POINTS = 300_000
LINES = 100
LINE_VERTICES = 101
SEGMENTS = LINES * (LINE_VERTICES - 1)  # 10.000 tramos de rotura
SCATTERED = POINTS - LINES * LINE_VERTICES  # 289.900 puntos sueltos
LATTICE = (580, 560)  # retícula de los sueltos (columnas, filas), con un desplazamiento al azar
JITTER = 0.3  # fracción del paso de la retícula: dos sueltos a más de 1,1 m
CLEARANCE_M = 0.5  # ningún suelto a menos de 0,5 m de una línea de rotura
NOISE_M = 0.05
SEED = 20_261_010
TIN_WORKERS = ("gis_tin_prepare", "gis_tin_finish")

# El MDT de RNF-006-01 (spec 006 §5; las constantes de tests/support/gis_perf.py, que aquí no se
# importa: cargaría otra copia del paquete): 3.399 × 3.309 celdas de 0,5 m (11,2 M), oeste
# WEST y sur SOUTH (dentro de WINDOW), la superficie de surface con ruido de 5 cm y un hueco
# sin dato de 100 × 80 celdas, en GeoTIFF float32 DEFLATE + predictor 3 (perfil «deliverable»).
MDT_COLS = 3_399
MDT_ROWS = 3_309
MDT_STEP = 0.5
MDT_HOLE = (slice(1500, 1580), slice(2000, 2100))  # filas y columnas (desde el NO) sin dato
MDT_NOISE_M = 0.05
MDT_SEED = 20_261_008
MDT_SHIFT_M = 0.25  # la segunda importación: otros datos (si no, reutilizaría la entrada)
DTM_WORKERS = ("gis_read_raster",)

TIN_BUDGET_S = 5.0  # RNF-006-03
FULL_BUDGET_S = 6.0  # RNF-006-06, la rejilla de 2,81 M celdas
LOD_BUDGET_S = 1.0  # RNF-006-06, su versión de 5 m
REFRESH_BUDGET_S = 0.5  # RNF-006-09
WRITE_BUDGET_S = 0.1  # RNF-008-01, cada escritura en disco local
CDT_RANGE_S = (1.0, 2.0)  # D-12: la excepción, estimada entre 1 y 2 s


def surface(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Cota (m) en (x, y) absolutas: colinas de unos 120 m, una pendiente general y un ondulado
    de metros (la superficie del MDT de RNF-006-01, ``tests/support/gis_perf.py``)."""
    east = x - WEST
    up = y - SOUTH
    return (850.0 + 60.0 * np.sin(east / 150.0) * np.cos(up / 120.0) + 0.02 * east
            + 2.0 * np.sin(east / 7.3) * np.sin(up / 5.1))


def survey() -> tuple[np.ndarray, list[np.ndarray]]:
    """El levantamiento de RNF-006-03, en mm (como un CSV con tres decimales): los
    :data:`SCATTERED` puntos sueltos ``(n, 3)`` y las :data:`LINES` líneas de rotura de
    :data:`LINE_VERTICES` vértices, onduladas y sin cruzarse. Los sueltos salen de una
    retícula con un desplazamiento al azar (dos de ellos nunca coinciden) y quedan a más de
    :data:`CLEARANCE_M` de cualquier línea (ninguno se funde con una ni la parte)."""
    rng = np.random.default_rng(SEED)
    xs = np.linspace(WEST + 10.0, WEST + COLS - 10.0, LINE_VERTICES)
    lines = []
    for k in range(LINES):
        y = SOUTH + (k + 0.5) * ROWS / LINES + 2.0 * np.sin((xs - WEST) / 45.0 + k)
        xyz = np.column_stack([xs, y, surface(xs, y)])
        lines.append(np.round(xyz, 3))
    cols, rows = LATTICE
    step_x, step_y = COLS / cols, ROWS / rows
    gx, gy = np.meshgrid(WEST + (np.arange(cols) + 0.5) * step_x,
                         SOUTH + (np.arange(rows) + 0.5) * step_y)
    x = gx.ravel() + rng.uniform(-JITTER, JITTER, gx.size) * step_x
    y = gy.ravel() + rng.uniform(-JITTER, JITTER, gy.size) * step_y
    near = np.zeros(x.size, dtype=bool)
    for line in lines:
        near |= np.abs(y - np.interp(x, line[:, 0], line[:, 1])) < CLEARANCE_M
    keep = rng.permutation(np.flatnonzero(~near))[:SCATTERED]
    assert keep.size == SCATTERED, keep.size
    x, y = x[keep], y[keep]
    z = surface(x, y) + rng.normal(0.0, NOISE_M, x.size)
    return np.round(np.column_stack([x, y, z]), 3), lines


def survey_csv(points: np.ndarray, lines: list[np.ndarray]) -> bytes:
    """El CSV del levantamiento (``P;X;Y;Z;Código;Línea``, «;» y coma decimal, UTF-8): los
    sueltos con el código TN y cada línea con su identificador."""
    rows = ["P;X;Y;Z;Código;Línea"]
    number = 0
    for x, y, z in points.tolist():
        number += 1
        rows.append(f"{number};{x:.3f};{y:.3f};{z:.3f};TN;")
    for index, line in enumerate(lines):
        for x, y, z in line.tolist():
            number += 1
            rows.append(f"{number};{x:.3f};{y:.3f};{z:.3f};BR;R{index:03d}")
    return ("\n".join(rows) + "\n").replace(".", ",").encode("utf-8")


# --- Equipo y texto de las cifras ----------------------------------------------------------


def _processor() -> str:
    """El nombre del procesador (en Windows, el del registro) y sus hilos."""
    name = ""
    try:
        import winreg

        key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            name = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError):
        name = platform.processor()
    return f"{name or 'procesador desconocido'}, {os.cpu_count()} hilos"


MACHINE = (f"{_processor()}; Blender {bpy.app.version_string} sin interfaz, Python "
           f"{platform.python_version()}, numpy {np.__version__}")
"""El equipo y el intérprete de las cifras."""


def _number(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _median_line(times: list[float]) -> str:
    return (f"mediana {_number(statistics.median(times))} s de {len(times)} "
            f"(mín. {_number(min(times))}, máx. {_number(max(times))})")


def _report(text: str) -> None:
    """Una línea de cifra (``tools/check.py`` recoge las que empiezan por «RNF-NNN-nn: »)."""
    print(text, file=sys.stderr, flush=True)


# --- El bucle de eventos de la prueba ------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Call:
    """Una llamada del hilo principal: qué, cuándo empezó y acabó (``time.perf_counter``) y
    lo que duró en ella la CDT de Blender (la excepción de D-12)."""

    what: str
    start: float
    end: float
    cdt_s: float = 0.0

    @property
    def blocking_s(self) -> float:
        """Lo que bloqueó la interfaz sin contar la CDT."""
        return self.end - self.start - self.cdt_s


class _EventLoop:
    """Hace de bucle de eventos de Blender en ``blender -b`` (ver el módulo): los
    temporizadores que se registran mientras está activo, sus llamadas medidas, los refrescos
    del progreso y las llamadas a la CDT."""

    def __init__(self, case: "GisSpeedTest") -> None:
        self.jobs_ops = case.jobs_ops
        self.gis_ops = case.gis_ops
        self.jobs_ui = case.jobs_ui
        self.triangulator = case.triangulator
        self.due: dict[Callable[[], float | None], float] = {}
        self.calls: list[_Call] = []
        self.refreshes: list[float] = []
        self.cdt: list[tuple[float, float]] = []  # (inicio, fin) de cada llamada a la CDT
        self._register = bpy.app.timers.register
        self._patches: list[Any] = []

    def __enter__(self) -> "_EventLoop":
        self._patches = [
            mock.patch.object(bpy.app.timers, "register", self._on_register),
            mock.patch.object(self.triangulator.BlenderTriangulator, "triangulate",
                              self._timed_triangulate()),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for patch in reversed(self._patches):
            patch.stop()

    def _on_register(self, function: Callable[[], float | None], first_interval: float = 0.0,
                     persistent: bool = False) -> Any:
        self.due[function] = time.perf_counter() + first_interval
        return self._register(function, first_interval=first_interval, persistent=persistent)

    def _timed_triangulate(self) -> Callable[..., np.ndarray]:
        real = self.triangulator.BlenderTriangulator.triangulate
        calls = self.cdt

        def triangulate(triangulator: Any, xy_local: np.ndarray, edges: np.ndarray) -> np.ndarray:
            start = time.perf_counter()
            try:
                return real(triangulator, xy_local, edges)
            finally:
                calls.append((start, time.perf_counter()))

        return triangulate

    def _cdt_since(self, index: int) -> float:
        return sum(stop - start for start, stop in self.cdt[index:])

    def call(self, what: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """``function`` en el hilo principal, medida (una orden)."""
        cdt_before = len(self.cdt)
        start = time.perf_counter()
        result = function(*args, **kwargs)
        end = time.perf_counter()
        self.calls.append(_Call(what, start, end, self._cdt_since(cdt_before)))
        self.refreshes.append(end)  # Blender redibuja la ventana tras la orden
        return result

    def step(self) -> bool:
        """Espera al temporizador al que antes le toca y lo llama; ``False`` si no queda
        ninguno registrado."""
        self.due = {function: when for function, when in self.due.items()
                    if bpy.app.timers.is_registered(function)}
        if not self.due:
            return False
        function = min(self.due, key=self.due.__getitem__)
        wait = self.due[function] - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        cdt_before = len(self.cdt)
        waiting = bool(self.gis_ops.pending_triangulations())
        incorporating = bool(self.gis_ops.pending_incorporations())
        start = time.perf_counter()
        interval = function()
        monitor = function is self.jobs_ops.tick
        if monitor:  # el sondeo redibuja la barra de estado: su campo «jobs»
            self.jobs_ui.draw(FakeLayout(), None)
        end = time.perf_counter()
        cdt_s = self._cdt_since(cdt_before)
        self.calls.append(_Call(getattr(function, "__name__", repr(function)), start, end,
                                cdt_s))
        if monitor or (function is self.gis_ops.triangulation_tick and waiting and not cdt_s):
            self.refreshes.append(end)  # la barra, o el aviso «Triangulando n puntos…»
        elif function is self.gis_ops.incorporation_tick and incorporating:
            self.refreshes.append(end)  # el avance de la incorporación, en la barra (T50)
        if interval is None:
            self.due.pop(function, None)
            if bpy.app.timers.is_registered(function):
                bpy.app.timers.unregister(function)
        else:
            self.due[function] = end + interval
        return True


@dataclasses.dataclass(frozen=True)
class _Order:
    """Una orden medida: su operación, lo que tardó hasta quedar hecha, sus llamadas, los
    intervalos sin refrescar el progreso (sin la CDT), las llamadas a la CDT, el mayor
    intervalo sin aviso de avance de cada ejecución de sus trabajos y las escrituras en la base
    del proyecto."""

    op_uid: str
    seconds: float
    calls: tuple[_Call, ...]
    gaps: tuple[float, ...]
    cdt_s: tuple[float, ...]
    job_gaps: tuple[tuple[str, float], ...]
    writes: tuple[float, ...]

    @property
    def longest_call(self) -> _Call:
        return max(self.calls, key=lambda call: call.blocking_s)

    @property
    def announced_before_cdt(self) -> bool:
        """Si un paso del temporizador de la triangulación sin CDT acabó antes de la CDT."""
        cdt = [call for call in self.calls if call.cdt_s]
        return bool(cdt) and any(call.what == "triangulation_tick" and not call.cdt_s
                                 and call.end <= cdt[0].start for call in self.calls)


class _ProgressMarks:
    """Los avisos de avance de los trabajos de la cadena (``WorkerInfo.run`` envuelto: en un
    hilo de Blender, el mismo reloj): por cada ejecución, su tipo y las horas de su inicio, de
    cada aviso y de su final."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, list[float]]] = []

    def wrap(self, info: Any) -> Any:
        real = info.run
        runs = self.runs

        def run(ctx: Any) -> Any:
            marks = [time.perf_counter()]
            runs.append((info.name, marks))
            try:
                return real(_MarkingContext(ctx, marks))
            finally:
                marks.append(time.perf_counter())

        return dataclasses.replace(info, run=run)

    def gaps(self) -> list[tuple[str, float]]:
        """El mayor intervalo sin aviso de cada ejecución."""
        return [(name, float(np.max(np.diff(marks)))) for name, marks in self.runs]


class _MarkingContext:
    """El ``WorkerContext`` del trabajo, que anota la hora de cada aviso de avance."""

    def __init__(self, ctx: Any, marks: list[float]) -> None:
        self._ctx = ctx
        self._marks = marks

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)

    def progress(self, frac: float, msg: str = "") -> None:
        self._marks.append(time.perf_counter())
        self._ctx.progress(frac, msg)


class GisSpeedTest(TinOperatorsCase):
    """El proyecto de 1.700 × 1.655 m de cada prueba, con la extensión habilitada una vez."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.jobs_ui = _module("bl.ui.jobs")
        cls.job_catalog = _module("jobs.catalog")
        cls.triangulator = _module("bl.scene.triangulator")
        cls.store = _module("gis.store")
        cls.gis_provenance = _module("gis.provenance")

    def open_survey_project(self) -> Any:
        """Un proyecto nuevo con la ventana :data:`WINDOW` y paso de 1 m, abierto en la
        sesión con su comprobación de apertura hecha."""
        parent = self.tmp / "proyectos"
        parent.mkdir(parents=True, exist_ok=True)
        settings = self.core.ProjectSettings(**settings_values(window=WINDOW, grid_step_m=1.0))
        project = self.core.create_project(parent, settings, self.ps.session(),
                                           self.ps.userdata()).project
        self.ps.attach(project)
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                break
        self.ps.take_notices()
        self.project = project
        return project

    def order(self, idname: str, workers: tuple[str, ...] = (), **props: Any) -> _Order:
        """La orden ``idname`` (``EXEC_DEFAULT``) y su cadena hasta que su operación deja de
        estar pendiente, con :class:`_EventLoop`; los trabajos ``workers`` con sus avisos de
        avance anotados y las escrituras en la base del proyecto medidas."""
        marks = _ProgressMarks()
        registry = {name: marks.wrap(self.job_catalog.WORKERS[name]) for name in workers}
        writes: list[float] = []
        real_write = self.project.write_transaction

        class _TimedWrite:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._inner = real_write(*args, **kwargs)

            def __enter__(self) -> Any:
                self._start = time.perf_counter()
                return self._inner.__enter__()

            def __exit__(self, *exc: Any) -> Any:
                try:
                    return self._inner.__exit__(*exc)
                finally:
                    writes.append(time.perf_counter() - self._start)

        group, name = idname.split(".")
        operator = getattr(getattr(bpy.ops, group), name)
        before = set(self.session.pending_ingests())
        with (mock.patch.dict(self.job_catalog._REGISTRY, registry),
              mock.patch.object(self.project, "write_transaction", _TimedWrite),
              _EventLoop(self) as loop):
            result = loop.call("orden", operator, "EXEC_DEFAULT", **props)
            self.assertEqual(result, {"FINISHED"})
            launched = [op for job, op in self.session.pending_ingests().items()
                        if job not in before]
            self.assertEqual(len(launched), 1)
            (op_uid,) = launched
            deadline = time.monotonic() + JOB_WAIT_S
            while (op_uid in self.session.pending_ingests().values()
                   or op_uid in self.gis_ops.pending_triangulations()
                   or op_uid in self.gis_ops.pending_incorporations()):
                self.assertLess(time.monotonic(), deadline, "la orden no termina")
                self.assertTrue(loop.step(), "la orden espera sin ningún temporizador")
            done = loop.calls[-1].end
        # El aviso del final seguiría en la barra NOTICE_S s: la orden siguiente empieza sin él.
        self.jobs_ops.MONITOR.stop()
        start = loop.calls[0].start
        times = sorted({start, *(moment for moment in loop.refreshes if moment <= done)})
        if times[-1] < done:
            times.append(done)
        gaps = []
        for previous, moment in zip(times, times[1:], strict=False):
            cdt = sum(min(stop, moment) - max(begin, previous) for begin, stop in loop.cdt
                      if begin < moment and stop > previous)
            gaps.append(moment - previous - cdt)
        return _Order(op_uid, done - start, tuple(c for c in loop.calls if c.start <= done),
                      tuple(gaps), tuple(stop - begin for begin, stop in loop.cdt),
                      tuple(marks.gaps()), tuple(writes))

    # --- RNF-006-03, RNF-006-09, RNF-008-01 -------------------------------------------------

    def import_survey(self) -> _Order:
        """El levantamiento de :func:`survey` en un CSV de ``entregas/``, importado con
        ``geoblender.gis_import_points`` (``gis_pts_levantamiento`` y
        ``gis_brk_levantamiento``)."""
        points, lines = survey()
        source = self.sources / "levantamiento.csv"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(survey_csv(points, lines))
        imported = self.order(IMPORT_POINTS, workers=("gis_import_points",),
                              filepath=str(source), name="Levantamiento", encoding="UTF8",
                              separator="SEMICOLON", decimal="COMMA", crs="EPSG:25830",
                              vertical="PROJECT")
        self.assertEqual(self.operation(imported.op_uid)[1], "done")
        self.assertEqual(len(self.store.load_points(self.project, "gis_pts_levantamiento")),
                         SCATTERED)
        self.assertEqual(len(self.store.load_lines(self.project, "gis_brk_levantamiento")),
                         LINES)
        self.ps.take_notices()
        # T50: el hash de cada tabla, el que calculó el trabajo, es el que da leerla en el
        # proyecto (el de antes, cuando lo calculaba el hilo de Blender al incorporarla).
        registry = _module("core.datasets.registry")
        for name in ("gis_pts_levantamiento", "gis_brk_levantamiento"):
            with self.project.read() as conn:
                record = registry.get(conn, name)
                again = registry.content_digest(conn, self.project, record)
            self.assertEqual(again.content_sha256, record.content_sha256, name)
        return imported

    def test_tin_order(self) -> None:
        """RNF-006-03, RNF-006-09, RNF-008-01: la orden «Crear TIN desde puntos» con un
        levantamiento de 300.000 puntos y 10.000 tramos de rotura queda hecha, con la CDT de
        Blender en el hilo principal (avisada antes), en ≤ 5 s (mediana de 5); la interfaz no
        pasa más de 0,5 s sin refrescar el progreso salvo la llamada a la CDT (D-12) y cada
        trabajo de la cadena avisa de su avance al menos cada 0,5 s (el peor caso de cada
        orden, mediana de 5), y cada escritura en la base del proyecto tarda ≤ 0,1 s."""
        project = self.open_survey_project()
        imported = self.import_survey()
        shown = _module("core.i18n").format_number(POINTS, 0)
        orders: list[_Order] = []
        for index in range(1, REPETITIONS + 1):
            gc.collect()
            order = self.order(TIN_POINTS, workers=TIN_WORKERS,
                               points="gis_pts_levantamiento",
                               breaklines="gis_brk_levantamiento", name=f"Levantamiento {index}")
            orders.append(order)
            self.assertIn(f"Triangulando {shown} puntos", " ".join(self.ps.take_notices()))
            self.assertTrue(order.announced_before_cdt)
            _type, status, reason, _message, _settings, software, *_ = \
                self.operation(order.op_uid)
            self.assertEqual(status, "done", reason)
            self.assertIn(self.triangulator.NAME, software)
            tin = self.store.load_tin(project, self.gis_provenance.dataset_name(
                self.gis_provenance.TIN, f"Levantamiento {index}"))
            self.assertEqual((len(tin.vertices), len(tin.constraint_edges)), (POINTS, SEGMENTS))
            self.assertEqual(sorted(name for name, _gap in order.job_gaps), sorted(TIN_WORKERS))
        choice = self.triangulator.choose_triangulation(POINTS)
        self.assertTrue(choice.in_process)
        self.assertTrue(CDT_RANGE_S[0] < choice.estimate_s <= CDT_RANGE_S[1])

        seconds = [order.seconds for order in orders]
        cdt = [value for order in orders for value in order.cdt_s]
        self.assertEqual(len(cdt), REPETITIONS)
        _report(f"RNF-006-03: TIN de {_count(POINTS)} puntos ({_count(SCATTERED)} sueltos y "
                f"{LINES} líneas de rotura con {_count(SEGMENTS)} tramos; "
                f"{_count(len(tin.faces))} triángulos) con la orden «Crear TIN desde puntos», "
                f"desde que se lanza hasta su operación hecha con el TIN registrado y su hash "
                f"({MACHINE}): {_median_line(seconds)}, presupuesto "
                f"{_number(TIN_BUDGET_S, 1)} s; de ello, la CDT de Blender en el hilo "
                f"principal {_median_line(cdt)} (estimada {_number(choice.estimate_s)} s: "
                "excepción de D-12)")
        # RNF-006-09, de cada orden su peor caso; la mediana de las 5 (spec 006 §5), y el máximo.
        gaps = [max(order.gaps) for order in orders]
        calls = [order.longest_call for order in orders]
        longest = max(calls, key=lambda call: call.blocking_s)
        jobs = [max(gap for _name, gap in order.job_gaps) for order in orders]
        worst_job = max((gap for order in orders for gap in order.job_gaps),
                        key=lambda item: item[1])
        _report(f"RNF-006-09: la orden del TIN de {_count(POINTS)} puntos, {REPETITIONS} veces "
                f"({MACHINE}), el peor caso de cada una, mediana de {REPETITIONS} (máx.): sin "
                f"refrescar el progreso sin contar la CDT {_number(statistics.median(gaps))} s "
                f"({_number(max(gaps))}); la llamada más larga del hilo principal sin la CDT "
                f"{_number(statistics.median(c.blocking_s for c in calls))} s "
                f"({_number(longest.blocking_s)}, {longest.what}); el mayor intervalo entre "
                f"avisos de avance de sus trabajos {_number(statistics.median(jobs))} s "
                f"({_number(worst_job[1])}, {worst_job[0]}); presupuesto "
                f"{_number(REFRESH_BUDGET_S, 1)} s. La CDT, avisada antes en un paso anterior "
                f"del temporizador: {_number(min(cdt))}–{_number(max(cdt))} s")
        writes = [write for order in orders for write in order.writes]
        _report(f"RNF-008-01: escrituras en la base del proyecto durante la orden del TIN "
                f"({len(writes)} en {REPETITIONS} órdenes, entre ellas empezar y terminar cada "
                f"operación; "
                f"{MACHINE}): máx. {_number(max(writes))} s (mediana "
                f"{_number(statistics.median(writes))} s), presupuesto "
                f"{_number(WRITE_BUDGET_S, 1)} s cada escritura en disco local")
        call = imported.longest_call
        steps = sum(1 for item in imported.calls if item.what == "incorporation_tick")
        _report(f"RNF-006-09: importar el CSV de {_count(POINTS)} filas ({_count(SCATTERED)} "
                f"puntos y {LINES} líneas de rotura; {MACHINE}), desde la orden hasta su "
                f"operación hecha ({_number(imported.seconds)} s; el hash de las tablas, en su "
                f"trabajo, y la incorporación en {steps} pasos del temporizador, T50): la "
                f"llamada más larga del hilo principal {_number(call.blocking_s)} s "
                f"({call.what}), sin refrescar el progreso {_number(max(imported.gaps))} s; "
                f"presupuesto {_number(REFRESH_BUDGET_S, 1)} s")
        self.assertLessEqual(statistics.median(seconds), TIN_BUDGET_S)
        self.assertLessEqual(statistics.median(gaps), REFRESH_BUDGET_S)
        self.assertLessEqual(statistics.median(c.blocking_s for c in calls), REFRESH_BUDGET_S)
        self.assertLessEqual(statistics.median(jobs), REFRESH_BUDGET_S)
        self.assertLessEqual(max(writes), WRITE_BUDGET_S)
        self.assertLessEqual(call.blocking_s, REFRESH_BUDGET_S, call.what)
        self.assertLessEqual(max(imported.gaps), REFRESH_BUDGET_S)

    # --- RNF-006-09: importar un MDT (T54) ---------------------------------------------------

    def dtm_source(self, name: str, shift_m: float = 0.0) -> Any:
        """El MDT de RNF-006-01 (:data:`MDT_COLS` × :data:`MDT_ROWS` celdas de
        :data:`MDT_STEP` m) con sus cotas subidas ``shift_m`` m, en ``entregas/<name>``:
        GeoTIFF float32 DEFLATE + predictor 3 en el CRS y la referencia vertical del
        proyecto."""
        grid_mod, raster_mod = _module("gis.grid"), _module("gis.raster")
        grid = grid_mod.Grid(WEST, SOUTH + MDT_ROWS * MDT_STEP, MDT_STEP, MDT_STEP, MDT_COLS,
                             MDT_ROWS)
        x, y = grid.centers()
        values = (surface(x, y) + shift_m
                  + np.random.default_rng(MDT_SEED).normal(0.0, MDT_NOISE_M, grid.shape))
        values[MDT_HOLE] = np.nan
        crs, vertical = self.store.project_references(self.project)
        path = self.sources / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _module("gis.geotiff").GeoTiffIO().write(raster_mod.Raster(grid, values, crs, vertical),
                                                 path, profile="deliverable")
        return path

    def import_dtm_order(self, name: str, path: Any) -> _Order:
        """``geoblender.gis_import_dtm`` con ``path`` (en el CRS y la referencia vertical del
        proyecto) hasta su operación hecha, medida con :meth:`order`; comprueba que quedó
        hecha con su rejilla de origen."""
        imported = self.order(IMPORT_DTM, workers=DTM_WORKERS, filepath=str(path), name=name,
                              vertical="PROJECT")
        _type, status, reason, *_ = self.operation(imported.op_uid)
        self.assertEqual(status, "done", reason)
        dataset = self.gis_provenance.dataset_name(self.gis_provenance.SOURCE_GRID, name)
        self.assertEqual(self.store.load_raster(self.project, dataset).grid.shape,
                         (MDT_ROWS, MDT_COLS))
        return imported

    def test_dtm_import(self) -> None:
        """RNF-006-09, RF-006-28 (T54): importar el MDT de RNF-006-01 (11,2 M celdas) con
        ``geoblender.gis_import_dtm``, desde la orden hasta su operación hecha, la primera vez
        sin rejilla del proyecto y la segunda con ella (la comparación de cotas de RF-006-06):
        ninguna llamada del hilo principal pasa de 0,5 s ni pasa más de 0,5 s sin refrescar el
        progreso (la incorporación, la copia de la rejilla al proyecto con su huella y su
        registro, va por pasos desde su temporizador)."""
        project = self.open_survey_project()
        orders = [self.import_dtm_order("MDT vuelo", self.dtm_source("mdt/vuelo.tif"))]
        self.grid_dataset(project)
        self.ps.take_notices()
        orders.append(self.import_dtm_order(
            "MDT vuelo B", self.dtm_source("mdt/vuelo_b.tif", MDT_SHIFT_M)))
        compared = " ".join(self.ps.take_notices())
        self.assertIn("gis_dtm_mdt_1_m", compared)  # la comparación con la rejilla (RF-006-06)
        cells = _count(MDT_COLS * MDT_ROWS)
        for label, order in zip(("sin rejilla del proyecto", "con la rejilla del proyecto"),
                                orders, strict=True):
            call = order.longest_call
            steps = sum(1 for item in order.calls if item.what == "incorporation_tick")
            _report(f"RNF-006-09: importar el MDT de {MDT_COLS} × {MDT_ROWS} celdas ({cells}; "
                    f"float32 DEFLATE + predictor 3), {label} ({MACHINE}), desde la orden hasta "
                    f"su operación hecha ({_number(order.seconds)} s; la incorporación en "
                    f"{steps} pasos del temporizador, T54): la llamada más larga del hilo "
                    f"principal {_number(call.blocking_s)} s ({call.what}), sin refrescar el "
                    f"progreso {_number(max(order.gaps))} s; presupuesto "
                    f"{_number(REFRESH_BUDGET_S, 1)} s")
        for order in orders:
            call = order.longest_call
            self.assertLessEqual(call.blocking_s, REFRESH_BUDGET_S, call.what)
            self.assertLessEqual(max(order.gaps), REFRESH_BUDGET_S)

    # --- RNF-006-06 -------------------------------------------------------------------------

    def grid_dataset(self, project: Any) -> str:
        """La rejilla de 1 m del proyecto (``gis_dtm_mdt_1_m``, la superficie de
        :func:`surface` en todas sus celdas), escrita con ``gis.store.ResultWriter`` como la
        deja ``gis.resample``; su nombre."""
        grid_mod, raster_mod = _module("gis.grid"), _module("gis.raster")
        operations = _module("core.provenance.operations")
        crs, vertical = self.store.project_references(project)
        grid = grid_mod.project_grid(project.window, project.grid_step_m)
        self.assertEqual(grid.shape, (ROWS, COLS))
        x, y = grid.centers()
        handle = operations.begin_operation(project, self.gis_provenance.RESAMPLE,
                                            settings={"name": "MDT 1 m"},
                                            params=["gis.resample.min_valid_fraction"],
                                            executor="blender")
        with self.store.ResultWriter(project, handle) as out:
            out.raster("MDT 1 m", raster_mod.Raster(grid, surface(x, y), crs, vertical))
            out.commit(software={"pyproj": "3.8.0"}, message="La rejilla de la prueba")
        return self.gis_provenance.dataset_name(self.gis_provenance.PROJECT_GRID, "MDT 1 m")

    def load_in_steps(self, name: str, lod: str) -> tuple[float, float, float, str]:
        """``geoblender.core_load_into_view`` como desde la interfaz (en pasos, ``in_steps``):
        la orden y, como el temporizador de su ventana, un evento ``TIMER`` cada
        ``TIMER_INTERVAL_S`` al modal hasta que termina. Devuelve lo que tardó, su llamada más
        larga del hilo principal, lo más que pasó sin refrescar el progreso (cada evento lo
        pone en la barra de estado) y cómo terminó."""
        ops = _module("bl.ops.core")
        cls = ops.GEOBLENDER_OT_core_load_into_view
        start = time.perf_counter()
        result = bpy.ops.geoblender.core_load_into_view("EXEC_DEFAULT", datasets=name, lod=lod,
                                                       in_steps=True)
        end = time.perf_counter()
        self.assertEqual(result, {"RUNNING_MODAL"})
        (operator,) = [op for op in bpy.context.window.modal_operators
                       if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        longest, refreshes = end - start, [start, end]
        event = SimpleNamespace(type="TIMER", value="NOTHING")
        state: set[str] = {"RUNNING_MODAL"}
        while state == {"RUNNING_MODAL"}:
            time.sleep(cls.TIMER_INTERVAL_S)
            begin = time.perf_counter()
            state = operator.modal(bpy.context, event)
            end = time.perf_counter()
            longest = max(longest, end - begin)
            refreshes.append(end)
        return (end - start, longest, float(np.max(np.diff(refreshes))),
                next(iter(state)))

    def test_view_load(self) -> None:
        """RNF-006-06, RNF-006-09 (T50): cargar en la vista una rejilla de 2,81 M celdas tarda
        ≤ 6 s y su versión de 5 m ≤ 1 s (mediana de 5), con la malla completa (un vértice por
        celda y dos triángulos por cuadro de cuatro centros) y comprobada; como desde la
        interfaz, por pasos desde el temporizador de la ventana: ninguna llamada del hilo
        principal pasa de 0,5 s ni pasa más de 0,5 s sin refrescar el progreso (el peor caso
        de cada carga, mediana de 5; y el máximo)."""
        name = self.grid_dataset(self.open_survey_project())
        uid = self.dataset(name)[0]
        views = _module("bl.scene.views")

        def load(lod: str, columns: int, rows: int) -> list[tuple[float, float, float, str]]:
            runs = []
            for _ in range(REPETITIONS):
                views.unload_datasets([uid])
                gc.collect()
                runs.append(self.load_in_steps(name, lod))
                self.assertEqual(runs[-1][3], "FINISHED")
                (obj,) = [obj for obj in bpy.data.objects
                          if getattr(obj, views.OBJECT_PROPERTY).dataset_uid == uid]
                self.assertEqual((len(obj.data.vertices), len(obj.data.polygons)),
                                 (columns * rows, 2 * (columns - 1) * (rows - 1)))
            return runs

        full = load("FULL", COLS, ROWS)
        lod_cols, lod_rows = int(COLS // LOD_STEP_M), int(ROWS // LOD_STEP_M)
        coarse = load("LOD2", lod_cols, lod_rows)
        views.unload_datasets([uid])
        _report(f"RNF-006-06: cargar en la vista la rejilla de 1 m de {_count(CELLS)} celdas "
                f"({COLS} × {ROWS}; geoblender.core_load_into_view en pasos con la "
                f"comprobación de la malla; {MACHINE}): {_median_line([r[0] for r in full])}, "
                f"presupuesto {_number(FULL_BUDGET_S, 1)} s; su versión de "
                f"{_number(LOD_STEP_M, 0)} m ({lod_cols} × {lod_rows}): "
                f"{_median_line([r[0] for r in coarse])}, presupuesto "
                f"{_number(LOD_BUDGET_S, 1)} s")
        calls = [run[1] for run in full + coarse]
        gaps = [run[2] for run in full + coarse]
        _report(f"RNF-006-09: cargar en la vista la rejilla de {_count(CELLS)} celdas y su "
                f"versión de {_number(LOD_STEP_M, 0)} m, {REPETITIONS} veces cada una, en "
                f"pasos desde el temporizador de la ventana (T50; {MACHINE}), el peor caso de "
                f"cada carga, mediana (máx.): la llamada más larga del hilo principal "
                f"{_number(statistics.median(calls))} s ({_number(max(calls))}), sin refrescar "
                f"el progreso {_number(statistics.median(gaps))} s ({_number(max(gaps))}); "
                f"presupuesto {_number(REFRESH_BUDGET_S, 1)} s")
        self.assertLessEqual(statistics.median(r[0] for r in full), FULL_BUDGET_S)
        self.assertLessEqual(statistics.median(r[0] for r in coarse), LOD_BUDGET_S)
        self.assertLessEqual(statistics.median(calls), REFRESH_BUDGET_S)
        self.assertLessEqual(statistics.median(gaps), REFRESH_BUDGET_S)
        self.assertLessEqual(max(calls), REFRESH_BUDGET_S)  # ningún tramo, en ninguna carga
        self.assertLessEqual(max(gaps), REFRESH_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
