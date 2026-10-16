# SPDX-License-Identifier: GPL-3.0-or-later
"""Los pasos de los sondeos en el hilo de Blender con V-ref (spec 005 0.5, T32; RNF-005-06; plan
005 §5.6.5, §5.6.7 y §5.6.8, D-13, D25 y los riesgos R13 y R16 del plan).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py
-- --carpeta tests/rendimiento/blender --patron "perf_dh_steps.py"``). Datos generados en la
prueba (en ``%TEMP%``, sin versionar; spec 005 §5): V-ref de ``tests/data/dh/sintetico.py``
(2.000 sondeos, 20.000 estaciones, 50.000 tramos de litología y 25.000 tramos con 20
elementos: 500.000 valores; los seis CSV del formato de ``csv_basico``) en ``entregas/``, y un
proyecto nuevo (EPSG:25830 y EPSG:5782) cuya ventana de trabajo tiene la extensión del MDT de
RNF-006-01 (1.700 × 1.655 m) con las bocas dentro, con su rejilla del proyecto de 0,5 m
(``gis_dtm_terreno``: 3.400 × 3.310 celdas, el tamaño del MDT de RNF-006-01 que pide el riesgo
R16, con la superficie de ``tests/data/gis`` sobre la que están las bocas y 5 cm de ruido;
escrita con la API de la 006 como la deja «Rejilla del proyecto desde un MDT»).

**RNF-005-06** (:class:`DrillholeStepsTest`): con el proyecto en disco local, ninguna operación
de los sondeos deja la interfaz sin responder más de 0,2 s seguidos; con el proyecto en una
unidad de red, lo que hace Geoblender en cada llamada del hilo de Blender no pasa de 0,2 s, y las
esperas de la red (el ``COMMIT`` y el envío al servidor de lo escrito) se miden y se anotan
aparte, sin presupuesto (spec 0.5, D-13 resuelta por Samuel el 16/10/2026); lo que dura más de
1 s enseña su avance. Se recorre, como desde la interfaz, la importación de los seis CSV de
V-ref con ``geoblender.dh_import_drillholes`` (su asistente, con la correspondencia que
propone; cada lectura en proceso aparte), la decisión de la persona en «Importación pendiente»
(dar de alta los códigos nuevos y aplicar), la aplicación (``dh_import_apply``), la escritura
de lo importado por pasos en una transacción (``drillholes.store.SourceWriter``, con su
``COMMIT``) y los originales, la base (``dh.build_base``: lo importado leído por pasos, su
trabajo y su escritura con ``BaseWriter``), su validación con la rejilla del proyecto
(``dh.validate``: la base leída por pasos y la rejilla pasada por ruta a su trabajo, que la
copia a su ``in/``, riesgo R16), las trazas con ``geoblender.dh_desurvey`` y, escritas, la
carga de su vista (tubos de litología y barras del oro; ``bl.scene.dh_view``), desde que se
lanza cada orden hasta que no queda nada por hacer.
Cada llamada del hilo principal se mide: cada orden (la importación, la decisión y las trazas)
y cada paso de cada temporizador (el monitor de los trabajos, con sus finales, y el dibujo de
su campo de la barra de estado; la cola de incorporación de los sondeos; los indicadores de la
procedencia, que ponen la vista al día de lo obsoleto). En disco local, ninguna pasa de
:data:`STEP_BUDGET_S`; en la red, ninguna pasa de él sin sus esperas de la red: el ``COMMIT`` de
cada transacción del proyecto (salir de ``Project.write_transaction``: confirmar y cerrar su
conexión) y cada envío al servidor de lo escrito por un paso de la escritura
(``drillholes.store._sent``, el ``os.fsync`` de la T53), medidos dentro de la llamada en que
ocurren (sin perfilador: un reloj alrededor de cada uno). Entre dos refrescos del avance (el
final de cada orden, cada sondeo del monitor, que redibuja la barra de estado, y cada paso de
la cola, que pone en ella su avance) no pasa más de :data:`PROGRESS_BUDGET_S` (decisión menor
de la T32, revisable: «enseña su avance» medido así). La evaluación del grafo de dependencias
(los tubos de Geometry Nodes) la hace Blender al dibujar, fuera de estos pasos: la mide
``perf_dh_view.py`` (RNF-005-04; plan §5.6.8).

Se mide dos veces: con el proyecto en disco local (``%TEMP%``) y, con la carpeta de pruebas de
la red (``GEOBLENDER_NET_TEST_DIR``, recurso «red» de ``tests.support.network``; nunca la de los
expedientes de clientes), con el proyecto en ``Z:`` (riesgo R13: el ``COMMIT`` de lo importado
y de la base en la red). Cada línea «RNF-005-06: …» da el equipo, la llamada más larga (qué
era), la peor sin las esperas de la red, las cinco más largas (con sus esperas), el mayor
intervalo sin refrescar el avance, la duración de cada ``COMMIT`` de las transacciones del
proyecto, los envíos al servidor (el más largo y su total) y lo que tardó el hilo de Blender en
lanzar cada trabajo, con el tamaño de sus entradas (las que copia el hilo a ``in/`` y las que
van por ruta y copia el trabajo, como la rejilla del proyecto de la validación, R16).

En ``blender -b`` no hay bucle de eventos ni corren los temporizadores: la prueba hace de bucle
(:class:`EventLoop`, como ``perf_gis``): anota cada temporizador que se registra (y los que ya
lo estaban de los que conoce) y lo llama cuando le toca, duerme entre medias y mide cada
llamada; tras cada sondeo del monitor dibuja el campo «jobs» de la barra de estado con un
*layout* simulado (``FakeLayout``). Lo que solo se ve con la interfaz (el dibujo de la vista,
Esc) queda para la comprobación en pantalla (M1 a M3).
"""

from __future__ import annotations

import csv
import dataclasses
import gc
import importlib
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.data.dh import sintetico
from tests.support import blender_ext, network
from tests.support.core_fixtures import settings_values
from tests.support.dh_fakes import gis_surface
from tests.support.fake_layout import FakeLayout
from tests.support.resources import requires
from tests.support.trees import remove_tree

# RNF-005-06: ninguna llamada del hilo de Blender, más (en la red, sin sus esperas de la red)
STEP_BUDGET_S = 0.2
PROGRESS_BUDGET_S = 1.0  # RNF-005-06: lo que dura más de 1 s enseña su avance
WINDOW_MARGIN_M = 50.0  # las bocas, dentro de la ventana de trabajo con este margen
# La rejilla del proyecto con que se valida (gis_dtm_terreno): la del MDT de RNF-006-01 (spec
# 006 §5; riesgo R16 del plan 005), 3.400 × 3.310 celdas de 0,5 m con 5 cm de ruido.
WINDOW_SIZE_M = (1_700, 1_655)
GRID_STEP_M = 0.5
SURFACE_NOISE_M = 0.05
SURFACE_SEED = 20_261_008
PROJECT_SURFACE = "terreno"
ELEMENT = "Au"  # el elemento de las barras de la vista
FILES = ("bocas.csv", "desviaciones.csv", "litologia.csv", "analisis_columnas.csv",
         "litologias.csv", "elementos.csv")
ROLES = {"bocas.csv": "collar", "desviaciones.csv": "survey", "litologia.csv": "lithology",
         "analisis_columnas.csv": "assay_wide", "litologias.csv": "lithology_catalog",
         "elementos.csv": "element_catalog"}
DECLARED = {"crs": "EPSG:25830", "vertical": "PROJECT", "azimuth_ref": "GRID",
            "inclination_convention": "NEGATIVE_DOWN", "all_vertical": False,
            "decimal_mark": "COMMA", "separator": "SEMICOLON", "encoding": "UTF8",
            "date_format": "%d/%m/%Y", "density_kind": "ADOPTADO"}
VREF_HOLES = 2_000
VREF_STATIONS = 20_000
VREF_LITHOLOGY = 50_000
VREF_VALUES = 500_000
WAIT_S = 900.0  # plazo de seguridad de cada recorrido: un trabajo colgado no cuelga la prueba
MAX_TICKS = 300
TOP_CALLS = 5
TRACE = "dh_trace"


def module(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión."""
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


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


def number(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def median_line(times: list[float]) -> str:
    return (f"mediana {number(statistics.median(times))} s de {len(times)} "
            f"(mín. {number(min(times))}, máx. {number(max(times))})")


def report(text: str) -> None:
    """Una línea de cifra (``tools/check.py`` recoge las que empiezan por «RNF-NNN-nn: »)."""
    print(text, file=sys.stderr, flush=True)


# --- V-ref ---------------------------------------------------------------------------------


def _decimal(text: str) -> float:
    return float(text.replace(",", "."))


def vref_facts(folder: Path) -> tuple[str, tuple[float, float, float, float]]:
    """De V-ref escrito en ``folder``: la unidad de cada elemento de su catálogo, como se
    declara en el asistente («Au=g/t; Ag=ppm; …»), y la ventana de trabajo: la extensión del
    MDT de RNF-006-01 (:data:`WINDOW_SIZE_M`) centrada en las bocas, en metros enteros (las
    bocas quedan dentro con más de :data:`WINDOW_MARGIN_M` m de margen)."""
    with (folder / "elementos.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))[1:]
    units = "; ".join(f"{row[0]}={row[2]}" for row in rows)
    with (folder / "bocas.csv").open(encoding="utf-8", newline="") as handle:
        collars = list(csv.reader(handle, delimiter=";"))[1:]
    x = [_decimal(row[1]) for row in collars]
    y = [_decimal(row[2]) for row in collars]
    west = math.floor((min(x) + max(x) - WINDOW_SIZE_M[0]) / 2)
    south = math.floor((min(y) + max(y) - WINDOW_SIZE_M[1]) / 2)
    window = (west, south, west + WINDOW_SIZE_M[0], south + WINDOW_SIZE_M[1])
    if (min(x) - window[0] < WINDOW_MARGIN_M or window[2] - max(x) < WINDOW_MARGIN_M
            or min(y) - window[1] < WINDOW_MARGIN_M or window[3] - max(y) < WINDOW_MARGIN_M):
        raise AssertionError(f"las bocas de V-ref no caben en la ventana {window}")
    return units, window


# --- Memoria del proceso (Windows) -----------------------------------------------------------


def private_bytes() -> int:
    """La memoria privada de este proceso (``GetProcessMemoryInfo``, ``PrivateUsage``), tras
    recoger la basura; fuera de Windows, 0."""
    gc.collect()
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes

    class _Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Counters),
                                                 wintypes.DWORD)
    kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = _Counters()
    counters.cb = ctypes.sizeof(_Counters)
    if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                            ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(counters.PrivateUsage)


# --- El bucle de eventos de la prueba ------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Call:
    """Una llamada del hilo principal: qué era, cuándo empezó y acabó (``time.perf_counter``) y
    lo que esperó en ella a la red (véase el módulo): sus ``COMMIT`` (``commit_s``) y sus
    envíos al servidor de lo escrito (``sent_s``)."""

    what: str
    start: float
    end: float
    commit_s: float = 0.0
    sent_s: float = 0.0

    @property
    def seconds(self) -> float:
        return self.end - self.start

    @property
    def waits(self) -> float:
        """Las esperas de la red de la llamada: sus ``COMMIT`` y sus envíos al servidor."""
        return self.commit_s + self.sent_s

    @property
    def own_seconds(self) -> float:
        """Lo que hace Geoblender en la llamada: su duración sin sus esperas de la red."""
        return self.seconds - self.waits


class EventLoop:
    """Hace de bucle de eventos de Blender en ``blender -b`` (véase el módulo): los
    temporizadores que se registran mientras está activo (y los conocidos que ya lo estaban),
    sus llamadas medidas con lo que hicieron y lo que esperaron a la red, los refrescos del
    avance, cada ``COMMIT`` de las transacciones del proyecto, cada envío al servidor de lo
    escrito y lo que tarda el hilo en lanzar cada trabajo."""

    def __init__(self, case: VrefCase, project: Any) -> None:
        self.case = case
        self.project = project
        self.due: dict[Callable[[], float | None], float] = {}
        self.calls: list[Call] = []
        self.refreshes: list[float] = []
        self.commits: list[tuple[str, float]] = []  # en qué llamada y lo que tardó
        self.sends: list[tuple[str, float]] = []  # los envíos al servidor: ídem
        self.current = ""  # la llamada en curso
        self.waited = {"commit": 0.0, "sent": 0.0}  # las esperas de la red de la llamada en curso
        # trabajo, s, bytes de las entradas que copia el hilo a in/ y de las que van por ruta
        self.launches: list[tuple[str, float, int, int]] = []
        self._register = bpy.app.timers.register
        self._stack = ExitStack()
        self._names: dict[str, str] = {}

    def __enter__(self) -> EventLoop:
        case = self.case
        stack = self._stack
        stack.enter_context(mock.patch.object(bpy.app.timers, "register", self._on_register))
        stack.enter_context(mock.patch.object(self.project, "write_transaction",
                                              self._timed_transaction(
                                                  self.project.write_transaction)))
        provenance = case.session
        stack.enter_context(mock.patch.object(provenance, "launch_job",
                                              self._timed_launch(provenance.launch_job)))
        stack.enter_context(mock.patch.object(provenance, "submit_job",
                                              self._timed_launch(provenance.submit_job)))
        store = module("drillholes.store")
        stack.enter_context(mock.patch.object(store, "_sent", self._timed_sent(store._sent)))
        now = time.perf_counter()
        for function in (case.jobs_ops.tick, case.dh_ops.incorporation_tick,
                         case.ui_provenance.indicator_tick, case.session.check_tick):
            if bpy.app.timers.is_registered(function):
                self.due[function] = now
        return self

    def __exit__(self, *exc: object) -> None:
        self._stack.close()

    def _on_register(self, function: Callable[[], float | None], first_interval: float = 0.0,
                     persistent: bool = False) -> Any:
        self.due[function] = time.perf_counter() + first_interval
        return self._register(function, first_interval=first_interval, persistent=persistent)

    def _waited(self, kind: str, waits: list[tuple[str, float]], seconds: float) -> None:
        """Una espera de la red de ``seconds`` s (``kind``: «commit» o «sent»), anotada en
        ``waits`` con la llamada en curso y sumada a las de esa llamada si es del hilo
        principal, el que se mide."""
        waits.append((self.current, seconds))
        if threading.current_thread() is threading.main_thread():
            self.waited[kind] += seconds

    def _timed_transaction(self, real: Callable[..., Any]) -> Callable[..., Any]:
        """``Project.write_transaction`` con su ``COMMIT`` medido: salir de ella sin error
        (confirmar y cerrar su conexión)."""

        @contextmanager
        def transaction(*args: Any, **kwargs: Any) -> Iterator[Any]:
            manager = real(*args, **kwargs)
            conn = manager.__enter__()
            try:
                yield conn
            except BaseException:
                if not manager.__exit__(*sys.exc_info()):
                    raise
            else:
                start = time.perf_counter()
                manager.__exit__(None, None, None)
                self._waited("commit", self.commits, time.perf_counter() - start)

        return transaction

    def _timed_sent(self, real: Callable[[Any], None]) -> Callable[[Any], None]:
        """``drillholes.store._sent`` medido: con el proyecto en la red, el envío al servidor
        de lo que ya escribió el paso (en disco local no hace nada y no se anota)."""

        def sent(project: Any) -> None:
            start = time.perf_counter()
            try:
                real(project)
            finally:
                if getattr(project, "is_network", False):
                    self._waited("sent", self.sends, time.perf_counter() - start)

        return sent

    def _timed_launch(self, real: Callable[..., Any]) -> Callable[..., Any]:
        launches = self.launches

        def launch(*args: Any, **kwargs: Any) -> Any:
            worker = str(args[1] if len(args) > 1 and not isinstance(args[0], str)
                         else args[0])
            copied = sum(Path(path).stat().st_size
                         for path in dict(kwargs.get("inputs") or {}).values())
            by_path = sum(Path(path).stat().st_size
                          for path in dict(kwargs.get("paths") or {}).values()
                          if Path(path).is_file())
            start = time.perf_counter()
            try:
                return real(*args, **kwargs)
            finally:
                launches.append((worker, time.perf_counter() - start, copied, by_path))

        return launch

    def call(self, what: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """``function`` en el hilo principal, medida (una orden); Blender redibuja tras ella."""
        self._begin(what)
        start = time.perf_counter()
        result = function(*args, **kwargs)
        end = time.perf_counter()
        self.calls.append(self._call(what, start, end))
        self.refreshes.append(end)
        return result

    def _begin(self, what: str) -> None:
        """Empieza la llamada ``what``, sin esperas de la red todavía."""
        self.current = what
        self.waited = {"commit": 0.0, "sent": 0.0}

    def _call(self, what: str, start: float, end: float) -> Call:
        return Call(what, start, end, self.waited["commit"], self.waited["sent"])

    def _label(self, function: Callable[[], float | None]) -> str:
        case = self.case
        if function is case.dh_ops.incorporation_tick:
            pending = case.dh_ops.pending_incorporations()
            return f"cola de los sondeos ({self.name_of(pending[0]) if pending else '—'})"
        if function is case.jobs_ops.tick:
            return "monitor de los trabajos"
        if function is case.ui_provenance.indicator_tick:
            return "indicadores de la procedencia"
        return getattr(function, "__name__", repr(function))

    def name_of(self, uid: str) -> str:
        """Lo que es la incorporación ``uid`` de la cola: el tipo de su operación o su
        nombre en la cola."""
        if uid not in self._names:
            with self.project.read() as conn:
                row = conn.execute("SELECT op_type FROM gb_operation WHERE uid = ?",
                                   (uid,)).fetchone()
            self._names[uid] = uid if row is None else str(row[0])
        return self._names[uid]

    def step(self) -> bool:
        """Espera al temporizador al que antes le toca y lo llama; ``False`` si no queda
        ninguno registrado."""
        case = self.case
        self.due = {function: when for function, when in self.due.items()
                    if bpy.app.timers.is_registered(function)}
        if not self.due:
            return False
        function = min(self.due, key=self.due.__getitem__)
        wait = self.due[function] - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        what = self._label(function)
        runner = case.jobs_ops.MONITOR.runner
        before = {item.job_uid for item in runner.snapshots() if item.active}
        incorporating = bool(case.dh_ops.pending_incorporations())
        self._begin(what)
        start = time.perf_counter()
        interval = function()
        monitor = function is case.jobs_ops.tick
        if monitor:  # el sondeo redibuja la barra de estado: su campo «jobs»
            case.jobs_ui.draw(FakeLayout(), None)
        end = time.perf_counter()
        if monitor:
            ended = sorted({item.worker for item in runner.snapshots()
                            if item.job_uid in before and not item.active})
            if ended:
                what += f" (final de {', '.join(ended)})"
        self.calls.append(self._call(what, start, end))
        if monitor or (function is case.dh_ops.incorporation_tick and incorporating):
            self.refreshes.append(end)
        if interval is None:
            self.due.pop(function, None)
            if bpy.app.timers.is_registered(function):
                bpy.app.timers.unregister(function)
        else:
            self.due[function] = end + interval
        return True

    def until(self, done: Callable[[], bool], what: str) -> None:
        """Llama a los temporizadores hasta que ``done()``."""
        deadline = time.monotonic() + WAIT_S
        while not done():
            self.case.assertLess(time.monotonic(), deadline, f"{what}: no termina")
            self.case.assertTrue(self.step(), f"{what}: espera sin ningún temporizador")

    def gaps(self, start: float, end: float) -> list[float]:
        """Los intervalos sin refrescar el avance entre ``start`` y ``end``."""
        moments = sorted({start, *(moment for moment in self.refreshes
                                   if start <= moment <= end), end})
        return [b - a for a, b in zip(moments, moments[1:], strict=False)]


@dataclasses.dataclass(frozen=True)
class Run:
    """Un recorrido medido (véase el módulo): sus llamadas, sus intervalos sin refrescar el
    avance, los ``COMMIT``, los envíos al servidor y los lanzamientos, lo que tardó de principio
    a fin (sin la decisión de la persona) y si el proyecto estaba en la red."""

    calls: tuple[Call, ...]
    gaps: tuple[float, ...]
    commits: tuple[tuple[str, float], ...]
    sends: tuple[tuple[str, float], ...]
    launches: tuple[tuple[str, float, int, int], ...]
    seconds: float
    network: bool

    @property
    def longest(self) -> Call:
        return max(self.calls, key=lambda call: call.seconds)

    @property
    def longest_own(self) -> Call:
        """La llamada que más hizo sin sus esperas de la red."""
        return max(self.calls, key=lambda call: call.own_seconds)

    def budgeted(self, call: Call) -> float:
        """Lo de ``call`` que cuenta frente a :data:`STEP_BUDGET_S` (véase el módulo): en disco
        local, toda su duración; en la red, la duración sin sus esperas de la red."""
        return call.own_seconds if self.network else call.seconds

    @property
    def worst(self) -> Call:
        """La llamada que más se acerca al presupuesto (:meth:`budgeted`)."""
        return max(self.calls, key=self.budgeted)

    def top(self, n: int = TOP_CALLS) -> list[Call]:
        return sorted(self.calls, key=lambda call: call.seconds, reverse=True)[:n]


# --- El caso: V-ref, el proyecto y el recorrido -----------------------------------------------


class VrefCase(unittest.TestCase):
    """V-ref en ``entregas/`` y la extensión habilitada una vez para todas las pruebas de la
    clase; cada prueba, con su proyecto (:meth:`open_project`)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.ps = module("bl.scene.project_session")
        cls.session = module("bl.ops.core_provenance")
        cls.jobs_ops = module("bl.ops.jobs")
        cls.jobs_ui = module("bl.ui.jobs")
        cls.dh_ops = module("bl.ops.dh")
        cls.props = module("bl.props.dh")
        cls.views = module("bl.scene.views")
        cls.ui_provenance = module("bl.ui.provenance")
        cls.core = module("core.project")
        cls.folder = Path(tempfile.mkdtemp(prefix="gb-t32-"))
        cls.sources = cls.folder / "entregas"
        sintetico.write_vref(cls.sources)
        cls.units, cls.window = vref_facts(cls.sources)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.jobs_ops.MONITOR.stop()
        cls.ps.close()
        blender_ext.load_file()
        blender_ext.release()
        remove_tree(cls.folder)

    def setUp(self) -> None:
        self.addCleanup(self.jobs_ops.MONITOR.stop)
        self.addCleanup(self.ps.close)
        self.ps.take_notices()

    # --- El proyecto ----------------------------------------------------------------------

    def open_project(self, parent: Path) -> Any:
        """Un proyecto nuevo en ``parent`` con la ventana de V-ref y su rejilla del proyecto
        (:meth:`add_surface`), abierto en la sesión con su comprobación de apertura hecha."""
        parent.mkdir(parents=True, exist_ok=True)
        settings = self.core.ProjectSettings(**settings_values(window=self.window,
                                                               grid_step_m=GRID_STEP_M))
        project = self.core.create_project(parent, settings, self.ps.session(),
                                           self.ps.userdata()).project
        self.ps.attach(project)
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                break
        self.ps.take_notices()
        self.project = project
        self.add_surface(project)
        return project

    def add_surface(self, project: Any) -> None:
        """La rejilla del proyecto ``gis_dtm_terreno``: la superficie de ``tests/data/gis``
        en los centros de las celdas de la ventana de trabajo (las del MDT de la 006, véase el
        módulo) con :data:`SURFACE_NOISE_M` m de ruido, escrita con
        ``gis.store.ResultWriter`` como la deja «Rejilla del proyecto desde un MDT»."""
        gis_store = module("gis.store")
        operations = module("core.provenance.operations")
        grid = module("gis.grid").project_grid(project.window, project.grid_step_m)
        x, y = grid.centers()
        values = gis_surface(np.column_stack((np.ravel(x), np.ravel(y)))).reshape(grid.shape)
        del x, y
        values += np.random.default_rng(SURFACE_SEED).normal(0.0, SURFACE_NOISE_M, grid.shape)
        crs, vertical = gis_store.project_references(project)
        raster = module("gis.raster").Raster(grid, values, crs, vertical)
        handle = operations.begin_operation(project, "gis.resample", settings={},
                                            executor="blender")
        library, version = module("gis.crs").crs_library()
        with gis_store.ResultWriter(project, handle) as out:
            out.raster(PROJECT_SURFACE, raster)
            out.commit(software={library: version})

    # --- Lo que pasa en el proyecto -----------------------------------------------------------

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def operations(self, op_type: str) -> list[tuple[str, str]]:
        return [(status, reason or "") for status, reason in self.rows(
            "SELECT status, status_reason FROM gb_operation WHERE op_type = ? ORDER BY fid",
            op_type)]

    def idle(self) -> bool:
        """Si no queda nada por hacer: ni trabajos en marcha, ni por incorporar, ni nada en la
        cola de los sondeos."""
        runner = self.jobs_ops.MONITOR.runner
        return (not self.dh_ops.pending_incorporations()
                and not self.session.pending_ingests()
                and not any(item.active for item in runner.snapshots()))

    # --- El recorrido ---------------------------------------------------------------------

    def import_vref(self, loop: EventLoop) -> tuple[float, float]:
        """La importación de los seis CSV de V-ref (la orden, su lectura, la decisión de la
        persona con los códigos nuevos dados de alta, la aplicación, lo importado, la base y
        su validación), con ``loop``; devuelve lo que tardó (s) sin la decisión y el momento
        en que acabó."""
        mapping = [{"file": name, "role": ROLES[name]} for name in FILES]
        start = time.perf_counter()
        result = loop.call("orden «Importar sondeos»",
                           bpy.ops.geoblender.dh_import_drillholes, "EXEC_DEFAULT",
                           directory=str(self.sources), files=[{"name": name} for name in FILES],
                           mapping_json=json.dumps(mapping), units=self.units, **DECLARED)
        self.assertEqual(result, {"FINISHED"})
        loop.until(lambda: bool(self.dh_ops.waiting_imports()) or self.idle(), "la lectura")
        (uid,) = self.dh_ops.waiting_imports()
        read = time.perf_counter() - start
        pending = getattr(bpy.context.window_manager, self.props.IMPORT_PROPERTY)
        self.assertEqual(len(pending.holes), 0)
        pending.register_codes = True
        decided = time.perf_counter()
        result = loop.call("decisión «Aplicar»", bpy.ops.geoblender.dh_import_drillholes,
                           "EXEC_DEFAULT", stage="APPLY", pending=uid)
        self.assertEqual(result, {"FINISHED"})
        loop.until(lambda: self.idle() and bool(self.operations("dh.validate")),
                   "la importación")
        end = time.perf_counter()
        for op_type, total in (("dh.import_tabular", len(FILES)), ("dh.build_base", 1),
                               ("dh.validate", 1)):
            self.assertEqual(self.operations(op_type), [("done", "")] * total, op_type)
        counted = self.rows("SELECT (SELECT count(*) FROM dh_collar), "
                            "(SELECT count(*) FROM dh_survey), "
                            "(SELECT count(*) FROM dh_lithology), "
                            "(SELECT count(*) FROM dh_assay), "
                            "(SELECT count(*) FROM dh_validation_issue)")
        self.assertEqual(counted, [(VREF_HOLES, VREF_STATIONS, VREF_LITHOLOGY, VREF_VALUES, 0)])
        return read + (end - decided), end

    def traces_and_view(self, loop: EventLoop) -> tuple[float, float]:
        """Las trazas con ``geoblender.dh_desurvey`` y, escritas, la carga de su vista (los
        tubos de litología y las barras de :data:`ELEMENT`), con ``loop``; devuelve lo que
        tardó (s) y el momento en que acabó."""
        display = getattr(bpy.context.scene, self.props.SCENE_PROPERTY)
        display.element = ELEMENT
        start = time.perf_counter()
        result = loop.call("orden «Calcular trazas»", bpy.ops.geoblender.dh_desurvey,
                           "EXEC_DEFAULT")
        self.assertEqual(result, {"FINISHED"})
        loop.until(lambda: self.idle() and bool(self.operations("dh.desurvey"))
                   and bool(self.view_objects()), "las trazas y su vista")
        end = time.perf_counter()
        self.assertEqual(self.operations("dh.desurvey"), [("done", "")])
        self.assertEqual(self.rows("SELECT count(*) FROM dh_trace"), [(VREF_HOLES,)])
        return end - start, end

    def view_objects(self) -> list[Any]:
        return module("bl.scene.dh_view").loaded_objects(self.project)

    def measure_all(self) -> Run:
        """La importación de V-ref y sus trazas con su vista en el proyecto abierto, con el
        bucle de :class:`EventLoop` (véase el módulo)."""
        with EventLoop(self, self.project) as loop:
            imported, imported_end = self.import_vref(loop)
            first = loop.calls[0].start
            decision = next(call for call in loop.calls if call.what.startswith("decisión"))
            reading = [call for call in loop.calls if call.end <= decision.start]
            gaps = loop.gaps(first, reading[-1].end) if reading else []
            gaps += loop.gaps(decision.start, imported_end)
            traced, traced_end = self.traces_and_view(loop)
            order = next(call for call in loop.calls if call.what.startswith("orden «Calcular"))
            gaps += loop.gaps(order.start, traced_end)
        self.jobs_ops.MONITOR.stop()
        objects = self.view_objects()
        self.assertEqual(sorted(obj.type for obj in objects), ["CURVES", "MESH"])
        return Run(tuple(loop.calls), tuple(gaps), tuple(loop.commits), tuple(loop.sends),
                   tuple(loop.launches), imported + traced,
                   bool(getattr(self.project, "is_network", False)))


def _with_waits(call: Call) -> str:
    """«qué era» de ``call``, con lo que tardaron en ella sus ``COMMIT`` y sus envíos al
    servidor, si los tuvo (de más de medio milisegundo)."""
    parts = [f"{label} {number(seconds)} s"
             for label, seconds in (("COMMIT", call.commit_s),
                                    ("envío al servidor", call.sent_s)) if seconds >= 0.0005]
    return call.what + (f"; de ella, {' y '.join(parts)}" if parts else "")


def _waits_text(label: str, waits: tuple[tuple[str, float], ...], listed: bool) -> str:
    """Las esperas ``waits`` (``COMMIT`` o envíos: en qué llamada y cuánto), con la más larga
    y su total, y cada una si ``listed``."""
    if not waits:
        return f"{label}: ninguno"
    what, seconds = max(waits, key=lambda item: item[1])
    text = (f"{label} ({len(waits)}), el más largo {number(seconds)} s ({what}), en total "
            f"{number(sum(seconds for _what, seconds in waits))} s")
    if listed:
        text += ": " + ", ".join(number(seconds) for _what, seconds in waits) + " s"
    return text


def _describe(run: Run, where: str) -> str:
    """La línea de RNF-005-06 de un recorrido ``run`` (véase el módulo)."""
    top = "; ".join(f"{number(call.seconds)} s ({_with_waits(call)})" for call in run.top())
    own = run.longest_own
    if run.network:
        without = "sin las esperas de la red (el COMMIT y el envío al servidor de lo escrito)"
        budget = (f"presupuesto {number(STEP_BUDGET_S, 1)} s de lo que hace Geoblender en cada "
                  "llamada, sin sus esperas de la red (spec 005 0.5); las esperas de la red, "
                  "aparte y sin presupuesto")
    else:
        without = "sin sus COMMIT (en disco local no hay envíos al servidor)"
        budget = f"presupuesto {number(STEP_BUDGET_S, 1)} s de cada llamada entera"
    sends = _waits_text("los envíos al servidor de lo escrito", run.sends, listed=False)
    launches = "; ".join(
        f"{worker} {number(seconds)} s"
        + (f" ({number(copied / 1e6, 1)} MB de entradas copiadas a in/)" if copied else "")
        + (f" ({number(by_path / 1e6, 1)} MB por ruta, copiados por el trabajo)"
           if by_path else "")
        for worker, seconds, copied, by_path in run.launches)
    return (f"RNF-005-06: importar V-ref ({count(VREF_HOLES)} sondeos, "
            f"{count(VREF_STATIONS)} estaciones, {count(VREF_LITHOLOGY)} tramos de litología "
            f"y {count(VREF_VALUES)} valores; seis CSV) con su base y su validación, y calcular "
            f"sus trazas y su vista, {where} ({MACHINE}; {number(run.seconds, 1)} s sin la "
            f"decisión de la persona, {len(run.calls)} llamadas del hilo principal): la llamada "
            f"más larga {number(run.longest.seconds)} s ({_with_waits(run.longest)}); {without}, "
            f"la peor {number(own.own_seconds)} s ({_with_waits(own)}); {budget}; las "
            f"{TOP_CALLS} más largas: {top}; sin refrescar el avance, como mucho "
            f"{number(max(run.gaps))} s (presupuesto {number(PROGRESS_BUDGET_S, 1)} s); "
            f"{_waits_text('los COMMIT del proyecto', run.commits, listed=True)}; {sends}; "
            f"lanzar cada trabajo: {launches}")


class DrillholeStepsTest(VrefCase):
    """RNF-005-06 con V-ref, en disco local y en la red (véase el módulo)."""

    def check(self, run: Run, where: str) -> None:
        """La línea de la cifra, la de las llamadas que pasan del presupuesto (si las hay), la
        de las que pasan de él solo por sus esperas de la red (si las hay) y las
        comprobaciones del recorrido ``run`` (véase el módulo)."""
        report(_describe(run, where))
        slow = [call for call in run.calls if run.budgeted(call) > STEP_BUDGET_S]
        if slow:
            report(f"Aviso RNF-005-06 ({where}): {len(slow)} llamadas de más de "
                   f"{number(STEP_BUDGET_S, 1)} s"
                   + (" sin sus esperas de la red" if run.network else "") + ": "
                   + "; ".join(f"{number(run.budgeted(call))} s ({_with_waits(call)})"
                               for call in slow))
        waiting = [call for call in run.calls
                   if call.seconds > STEP_BUDGET_S >= run.budgeted(call)]
        if waiting:
            report(f"Nota RNF-005-06 ({where}): {len(waiting)} llamadas de más de "
                   f"{number(STEP_BUDGET_S, 1)} s solo por sus esperas de la red (se anotan, "
                   "sin presupuesto): "
                   + "; ".join(f"{number(call.seconds)} s ({_with_waits(call)})"
                               for call in waiting))
        worst = run.worst
        self.assertLessEqual(run.budgeted(worst), STEP_BUDGET_S, _with_waits(worst))
        self.assertLessEqual(max(run.gaps), PROGRESS_BUDGET_S)

    def test_steps_on_local_disk(self) -> None:
        """RNF-005-06 (plan §5.6.7 y §5.6.8, D25): importar V-ref (seis CSV) con su base y su
        validación con la rejilla del proyecto, y calcular sus trazas y cargar su vista, con
        el proyecto en disco local: ninguna llamada del hilo de Blender (las órdenes, cada
        paso de sus temporizadores), entera, pasa de 0,2 s y el avance se refresca al menos
        cada segundo."""
        parent = Path(tempfile.mkdtemp(prefix="gb-t32-pr-"))
        self.addCleanup(remove_tree, parent)
        self.addCleanup(self.ps.close)  # antes de borrar su carpeta
        project = self.open_project(parent)
        self.assertFalse(project.is_network)
        run = self.measure_all()
        self.assertFalse(run.network)
        self.check(run, "con el proyecto en disco local")

    @requires(network.NET, network.NET_HINT)
    def test_steps_on_the_network(self) -> None:
        """RNF-005-06 (spec 0.5; riesgos R13 y R16; D-13 resuelta): lo mismo con el proyecto
        en la carpeta de pruebas de la red (``Z:``): lo que hace Geoblender en cada llamada
        del hilo, su duración sin sus esperas de la red (el ``COMMIT`` de lo importado, de la
        base y de cada transacción, y el envío al servidor de lo que escribe cada paso), no
        pasa de 0,2 s, tampoco al lanzar la validación con la rejilla del proyecto; esas
        esperas se miden dentro de cada llamada y se anotan aparte, sin presupuesto."""
        with ExitStack() as stack:
            remote = stack.enter_context(network.net_tmp("gb-005-t32-"))
            parent = remote / "proyectos"
            stack.callback(remove_tree, parent)
            stack.callback(self.ps.close)
            project = self.open_project(parent)
            self.assertTrue(project.is_network, "el proyecto de la carpeta de la red")
            run = self.measure_all()
            self.assertTrue(run.network)
            self.assertTrue(run.commits, "ningún COMMIT medido")
            self.assertTrue(run.sends, "ningún envío al servidor medido")
            self.check(run, "con el proyecto en la carpeta de pruebas de la red")


if __name__ == "__main__":
    unittest.main()
