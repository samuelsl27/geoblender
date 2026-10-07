# SPDX-License-Identifier: GPL-3.0-or-later
"""Trabajos en segundo plano dentro de Blender (spec 004; plan 004 §5.1, §5.2.7 y §7).

T18 — el grupo ``jobs`` de las preferencias (``GEOBLENDER_PG_jobs_preferences``,
``bl/props/jobs.py``), enlazado con un ``PointerProperty`` en la **única**
``GeoblenderPreferences`` (``bl/props/preferences.py``; PLT-02):

- RF-004-04: ``max_parallel_jobs``, de 1 a 4 y 2 por defecto (el máximo del lanzador,
  ``jobs.runner.DEFAULT_MAX_SUBPROCESS``);
- RF-004-17: ``retention_days``, de 1 a 90 y 7 por defecto (DP-33);
- RF-004-24: ``runtime_source`` (``AUTO``, ``WHEELHOUSE``, ``PYPI``; ``AUTO``) y
  ``wheelhouse_dir`` (carpeta, vacía);
- RF-004-26: ``use_external_python`` (falso) y ``external_python`` (fichero, vacío), que
  en las preferencias se ve pero no se edita: lo guarda, tras comprobarlo,
  ``geoblender.jobs_set_external_python`` (T33).

Ninguna ruta por defecto (ARQ-15): las dos rutas empiezan vacías. Registrar y desregistrar
dos veces seguidas no deja clases ni propiedades (huella del principio de la sesión).

T19 — el seguimiento en la barra de estado (plan 004 §5.4.4): ``JobMonitor``
(``bl/ops/jobs.py``) sondea el lanzador con un temporizador persistente que se registra al
lanzar el primer trabajo y se retira cuando no queda nada que mostrar, y el campo «jobs»
de la barra de estado de la 003 (``bl/ui/jobs.py``), declarado para los dos modos:

- RF-004-06: mientras hay trabajos activos, su número, y el nombre, el avance (que nunca
  retrocede y se acota a 0–100 %) y el último mensaje del más antiguo en curso, en modo
  Geoblender y en modo Blender;
- RF-004-07: al acabar un trabajo, durante 10 s, su nombre, su estado y su duración en s
  y, si no terminó bien, el mensaje del §8 en una línea, sin traza de Python.

En ``blender -b`` los temporizadores no se ejecutan: las pruebas llaman a ``tick()`` a mano
cada 0,05 s y dibujan el campo con un *layout* simulado. Un trabajo real de unos 2 s (el
autodiagnóstico, en hilo) y otro que falla con una excepción no capturada, en un lanzador
con la raíz en una carpeta temporal; el reloj del monitor lo adelanta la prueba para ver
caducar el aviso sin esperar 10 s.

T20 — los operadores reales ``geoblender.jobs_show_jobs`` y ``geoblender.jobs_cancel``
(``bl/ops/jobs.py``), con el ``bl_idname`` del catálogo de la 003 (que deja de generar sus
provisionales) en Herramientas ▸ Trabajos (``GEOBLENDER_MT_jobs_menu``), y la lista de
trabajos ``GEOBLENDER_PT_jobs_list`` (``bl/ui/jobs.py``):

- RF-004-08: la lista, una fila por trabajo con su nombre, estado, avance, duración,
  intérprete y último mensaje, y los botones Cancelar, Registro (``wm.path_open`` sobre su
  ``job.log``) y Descartar (``geoblender.jobs_clean``, de T21);
- RF-004-09: ``jobs_cancel`` sin ``job_uid`` cancela el más antiguo en curso; con él, ese
  (uno en cola, sin arrancar); otra vez, uno terminado o uno que no existe, nada más que un
  aviso; sin trabajos activos su ``poll`` falla y dice por qué.

Tres trabajos reales en hilo de un tipo de prueba que espera a que lo suelten (uno en curso
y dos en cola) y, para cada estado, un lanzador simulado; ``wm.call_panel`` se sustituye
(en ``blender -b`` no hay dónde abrir una ventana emergente).

T21 — los operadores reales ``geoblender.jobs_run_selftest`` y ``geoblender.jobs_clean``
(``bl/ops/jobs.py``), también del catálogo de la 003:

- RF-004-03: el autodiagnóstico ``SUM_10S`` (unos 10 s) va en proceso aparte;
  ``MATMUL_BLENDER`` (500 × 500 con el numpy de Blender), en hilo; ``MATMUL_COMPUTE``
  necesita el motor de cálculo y, sin él, queda «Fallido» (``runtime_missing``);
- RF-004-17 y RF-004-08: la limpieza ``OLD`` (los terminados hace más días que los de las
  preferencias), ``FINISHED`` (todos los terminados) y ``ONE`` (el «Descartar» de la
  lista) informa de los MB liberados y nunca borra un trabajo activo.

Un lanzador real en una carpeta temporal: el autodiagnóstico de 10 s se cancela en cuanto
da sus tres primeros trozos; la limpieza, sobre carpetas de otra sesión escritas a mano y
dos trabajos del lanzador en hilo (uno terminado, otro en curso).

T22 — el lanzador de la sesión (``bl/ops/jobs.py``), que crea el registro de la extensión y
da al monitor:

- RF-004-18: su raíz de trabajos sale de los datos de usuario de la copia de pruebas
  (``extension_path_user`` de ``bl_ext.gb_tests.…``: ``cache/_sin_proyecto/jobs``) sin
  proyecto y de ``Project.cache_dir()`` de la 002 con uno abierto (en la carpeta del
  proyecto en disco local y escritura; en los datos de usuario en solo lectura); habilitar
  no crea ni la raíz ni ``runtime/`` (RF-004-19);
- RF-004-13: al abrir un proyecto, los trabajos que su registro deja en cola o en curso y
  el lanzador no lleva quedan «Interrumpido», y se borran los terminados hace más de
  ``retention_days`` días (RF-004-17); desactivar Geoblender o cerrar Blender
  (``exit_pre``) con trabajos en curso los deja «Interrumpido» y sin proceso en ≤ 3 s, y
  retira el temporizador, el campo de la barra de estado y los manejadores;
- el ``sys.path`` de Blender no cambia con los trabajos (también uno del motor de cálculo,
  que sin motor queda «Fallido»), y ``max_parallel_jobs`` llega al lanzador al cambiarla.

T37 — el autodiagnóstico ``SUM_10S`` avanza cinco veces por segundo (50 trozos de 0,2 s; en
M1, con 20 trozos de 0,5 s, el % cambiaba 1,9 veces por segundo; M1 y H2 piden al menos dos):

- RF-004-06, RF-004-03: sus parámetros dan un trabajo de 10 ± 0,5 s en proceso aparte, con
  trozos de ≤ 0,25 s y un evento de avance por trozo; en el proceso real, los primeros
  avances llegan cada ≤ 0,25 s, y a ese ritmo el trabajo entero dura 10 ± 0,5 s.

Se ejecuta con ``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import datetime as dt
import importlib
import json
import os
import shutil
import stat
import statistics
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import fingerprint_diff, module_name, state_fingerprint
from tests.support.fake_layout import FakeLayout, draw

GROUP = "jobs"
GROUP_CLASS = "GEOBLENDER_PG_jobs_preferences"
# Valores por defecto del plan 004 §5.2.7, en el orden en que se dibujan.
DEFAULTS: dict[str, object] = {
    "max_parallel_jobs": 2,
    "retention_days": 7,
    "runtime_source": "AUTO",
    "wheelhouse_dir": "",
    "use_external_python": False,
    "external_python": "",
}
# Texto (msgid) con que se dibuja cada una: el nombre de la propiedad.
LABELS: dict[str, str] = {
    "max_parallel_jobs": "Jobs at once (separate process)",
    "retention_days": "Keep finished jobs (days)",
    "runtime_source": "Compute engine source",
    "wheelhouse_dir": "Wheel store folder",
    "use_external_python": "Use an external interpreter",
    "external_python": "External interpreter",
}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _addon_preferences() -> object:
    package = _module("bl").ADDON_PACKAGE
    return bpy.context.preferences.addons[package].preferences


def _extension_classes() -> list[str]:
    """Las clases de la extensión registradas en Blender (también los grupos de
    propiedades, que ``dir(bpy.types)`` no lista)."""
    prefix = module_name() + "."
    names: list[str] = []
    seen: set[type] = set()
    pending: list[type] = [bpy.types.bpy_struct]
    while pending:
        for cls in pending.pop().__subclasses__():
            if cls in seen:
                continue
            seen.add(cls)
            pending.append(cls)
            if (cls.__module__.startswith(prefix) and "bl_rna" in cls.__dict__
                    and getattr(cls, "is_registered", False)):
                names.append(cls.__name__)
    return sorted(names)


class JobsPreferencesTest(unittest.TestCase):
    """Con la extensión habilitada una vez para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.prefs = _addon_preferences()
        cls.i18n = _module("core.i18n")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def jobs(self) -> object:
        return getattr(self.prefs, GROUP)

    def test_group_with_defaults(self) -> None:
        """RF-004-04, RF-004-17, RF-004-24, RF-004-26: con la extensión habilitada desde
        ``gb_tests``, ``preferences.addons[bl.ADDON_PACKAGE].preferences.jobs`` existe con
        2, 7, ``AUTO``, vacío, falso y vacío; el máximo coincide con el del lanzador."""
        jobs = self.jobs()
        self.assertIsNotNone(jobs)
        self.assertEqual(jobs.bl_rna.identifier, GROUP_CLASS)
        self.assertEqual({name: getattr(jobs, name) for name in DEFAULTS}, DEFAULTS)
        runner = _module("jobs.runner")
        self.assertEqual(jobs.max_parallel_jobs, runner.DEFAULT_MAX_SUBPROCESS)

    def test_linked_in_the_single_preferences(self) -> None:
        """RF-004-04, RF-004-26 (PLT-02): el grupo es un ``PointerProperty`` ``jobs`` de la
        única clase de preferencias de la extensión, junto a ``core`` y ``ui``; la 004 no
        registra otra ``AddonPreferences``."""
        mine = [
            cls for cls in bpy.types.AddonPreferences.__subclasses__()
            if cls.__module__.startswith(module_name() + ".")
            and getattr(cls, "is_registered", False)
        ]
        self.assertEqual([cls.__name__ for cls in mine], ["GeoblenderPreferences"])
        rna = mine[0].bl_rna.properties[GROUP]
        self.assertEqual(rna.type, "POINTER")
        self.assertEqual(rna.fixed_type.identifier, GROUP_CLASS)
        inherited = set(bpy.types.AddonPreferences.bl_rna.properties.keys())
        groups = [p.identifier for p in mine[0].bl_rna.properties
                  if p.type == "POINTER" and p.identifier not in inherited]
        self.assertEqual(groups, ["core", "ui", GROUP])

    def test_types_limits_and_no_default_paths(self) -> None:
        """RF-004-04, RF-004-17, RF-004-24, RF-004-26: tipos, límites, subtipos y
        elementos del plan 004 §5.2.7; las rutas empiezan vacías (ninguna ruta por
        defecto, ARQ-15) y nada se anima."""
        props = self.jobs().bl_rna.properties
        inherited = set(bpy.types.PropertyGroup.bl_rna.properties.keys())  # rna_type, name
        self.assertEqual(sorted(p.identifier for p in props if p.identifier not in inherited),
                         sorted(DEFAULTS))
        expected_ints = {"max_parallel_jobs": (1, 4, 2), "retention_days": (1, 90, 7)}
        for name, (low, high, default) in expected_ints.items():
            with self.subTest(propiedad=name):
                self.assertEqual(props[name].type, "INT")
                self.assertEqual((props[name].hard_min, props[name].hard_max), (low, high))
                self.assertEqual(props[name].default, default)
        source = props["runtime_source"]
        self.assertEqual(source.type, "ENUM")
        self.assertEqual([item.identifier for item in source.enum_items],
                         ["AUTO", "WHEELHOUSE", "PYPI"])
        self.assertEqual(source.default, "AUTO")
        for name, subtype in (("wheelhouse_dir", "DIR_PATH"), ("external_python", "FILE_PATH")):
            with self.subTest(propiedad=name):
                self.assertEqual(props[name].type, "STRING")
                self.assertEqual(props[name].subtype, subtype)
                self.assertEqual(props[name].default, "")
        self.assertEqual(props["use_external_python"].type, "BOOLEAN")
        self.assertFalse(props["use_external_python"].default)
        for name in DEFAULTS:
            with self.subTest(propiedad=name):
                self.assertFalse(props[name].is_animatable)
                self.assertTrue(props[name].name)
                self.assertTrue(props[name].description)

    def test_out_of_range_is_clamped(self) -> None:
        """RF-004-04, RF-004-17: un máximo fuera de 1–4 o una retención fuera de 1–90 se
        quedan en el límite; el origen solo admite sus tres valores."""
        jobs = self.jobs()

        def restore() -> None:
            for name, value in DEFAULTS.items():
                setattr(jobs, name, value)

        self.addCleanup(restore)
        for name, value, expected in (
            ("max_parallel_jobs", 9, 4),
            ("max_parallel_jobs", 0, 1),
            ("retention_days", 365, 90),
            ("retention_days", -3, 1),
        ):
            with self.subTest(propiedad=name, valor=value):
                setattr(jobs, name, value)
                self.assertEqual(getattr(jobs, name), expected)
        jobs.runtime_source = "WHEELHOUSE"
        self.assertEqual(jobs.runtime_source, "WHEELHOUSE")
        with self.assertRaises(TypeError):
            jobs.runtime_source = "CONDA"
        self.assertEqual(jobs.runtime_source, "WHEELHOUSE")

    def test_drawn_in_preferences(self) -> None:
        """RF-004-04, RF-004-17, RF-004-24, RF-004-26: el panel de preferencias dibuja el
        grupo con su título y las seis propiedades, en ese orden y con los textos del
        catálogo de idioma; el intérprete externo se ve desactivado (lo guarda
        ``geoblender.jobs_set_external_python`` tras comprobarlo, T33)."""
        prefs = self.prefs
        cls = type(prefs)
        layout = draw(cls, bpy.context, core=prefs.core, ui=prefs.ui, jobs=prefs.jobs)
        tr = self.i18n.tr
        titles = [index for index, item in enumerate(layout.items)
                  if item.kind == "label" and item.text == tr("Background jobs")]
        self.assertEqual(len(titles), 1, layout.texts())
        drawn = [item for item in layout.of_kind("prop") if item.target in DEFAULTS]
        self.assertEqual([item.target for item in drawn], list(DEFAULTS))
        self.assertLess(titles[0], layout.items.index(drawn[0]))
        for item in drawn:
            with self.subTest(propiedad=item.target):
                self.assertEqual(item.text, tr(LABELS[item.target]))
                self.assertIs(item.options.get("translate"), False)
                self.assertEqual(item.enabled, item.target != "external_python")


class JobsPreferencesRegistrationTest(unittest.TestCase):
    """Cada prueba parte de la extensión deshabilitada y fuera de ``sys.modules``."""

    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)

    def assertSessionFingerprint(self) -> None:
        after = state_fingerprint()
        before = blender_ext.session_baseline()
        if after != before:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(before, after)))

    def test_register_and_unregister_twice(self) -> None:
        """RF-004-04, RF-004-17, RF-004-24, RF-004-26: registrar dos veces seguidas deja
        una sola clase del grupo y el grupo enlazado; desregistrar dos veces seguidas no
        deja clases ni propiedades (huella del principio de la sesión), y otra vuelta
        entera habilita el grupo con sus valores por defecto y lo vuelve a quitar."""
        for turn in (1, 2):
            with self.subTest(vuelta=turn):
                blender_ext.enable()
                props = _module("bl.props")
                props.register()  # segundo registro seguido
                self.assertEqual(_extension_classes().count(GROUP_CLASS), 1)
                jobs = getattr(_addon_preferences(), GROUP)
                self.assertEqual({name: getattr(jobs, name) for name in DEFAULTS},
                                 DEFAULTS)
                blender_ext.disable()
                props.unregister()  # segundo desregistro seguido
                sys.modules[module_name()].unregister()
                self.assertEqual(_extension_classes(), [])
                self.assertNotIn(module_name(), bpy.context.preferences.addons)
                self.assertSessionFingerprint()


# --- T19: seguimiento en la barra de estado ---------------------------------------------

FIELD = "jobs"
TIMER_KWARGS = {"first_interval": 0.25, "persistent": True}
SUM_LABEL = "Suma de 2 s"
SUM_PARAMS = {"n": 20_000, "chunks": 20, "sleep_s": 0.1}
BOOM_WORKER = "gbtest_boom"
BOOM_LABEL = "Cálculo que falla"
BOOM_ERROR = "fallo interno del cálculo de prueba"
TICK_SLEEP_S = 0.05
SCENARIO_DEADLINE_S = 30.0
NOTICE_S = 10.0
ACTIVE_ICON = "SORTTIME"
NOTICE_ICONS = {"succeeded": "CHECKMARK", "failed": "ERROR", "timed_out": "ERROR",
                "cancelled": "CANCEL", "interrupted": "CANCEL"}
JOB_OPERATORS = ["geoblender.jobs_show_jobs", "geoblender.jobs_cancel"]


def _boom(_ctx: object) -> dict[str, object]:
    raise RuntimeError(BOOM_ERROR)


class _Clock:
    """El reloj del monitor: el monótono más lo que la prueba lo adelanta."""

    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self) -> float:
        return time.monotonic() + self.offset


def _context(*, geoblender: bool) -> SimpleNamespace:
    """El contexto con que se dibuja la barra de estado (como en ``test_statusbar``)."""
    window = bpy.context.window_manager.windows[0]
    return SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=geoblender),
                           region=SimpleNamespace(width=1920.0), scene=bpy.context.scene,
                           window=window, screen=window.screen, area=None,
                           preferences=bpy.context.preferences)


class _Frame:
    """Lo que dibuja el campo «jobs» en un momento: número de activos, barra, mensaje,
    botones y aviso."""

    def __init__(self, layout: FakeLayout) -> None:
        self.items = layout.items
        labels = layout.of_kind("label")
        counts = [item.text for item in labels if item.icon == ACTIVE_ICON]
        self.count = counts[0] if counts else None
        bars = layout.of_kind("progress")
        self.bar = bars[0].text if bars else None
        self.factor = bars[0].options.get("factor") if bars else None
        notices = [item for item in labels if item.icon in NOTICE_ICONS.values()]
        self.notice = notices[0].text if notices else None
        self.notice_icon = notices[0].icon if notices else None
        plain = [item.text for item in labels if item.icon == "NONE"]
        self.message = plain[0] if plain else None
        self.operators = [item.target for item in layout.of_kind("operator")]
        self.texts = [item.text for item in self.items if item.text]

    @property
    def empty(self) -> bool:
        return not self.items

    @property
    def percent(self) -> int | None:
        if self.bar is None or "%" not in self.bar:
            return None
        return int(self.bar.rsplit("·", 1)[1].replace("%", "").strip())


def _field(ui: ModuleType, *, geoblender: bool = True) -> _Frame:
    """El campo «jobs» dibujado solo."""
    layout = FakeLayout()
    ui.draw(layout, _context(geoblender=geoblender))
    return _Frame(layout)


def _bar_texts(statusbar: ModuleType, *, geoblender: bool) -> list[str]:
    """Los textos de la barra de estado entera."""
    layout = FakeLayout()
    statusbar.draw_statusbar(SimpleNamespace(layout=layout), _context(geoblender=geoblender))
    return layout.texts()


class JobStatusFieldTest(unittest.TestCase):
    """Un trabajo real de 2 s y otro que falla, seguidos con ``tick()`` a mano."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.ops = _module("bl.ops.jobs")
        cls.ui = _module("bl.ui.jobs")
        cls.statusbar = _module("bl.ui.statusbar")
        cls.catalog = _module("jobs.catalog")
        cls.messages = _module("jobs.messages")
        cls.i18n = _module("core.i18n")
        protocol = _module("jobs.protocol")
        runner = _module("jobs.runner")
        cls.tmp = tempfile.TemporaryDirectory(prefix="gb4-")
        package_dir = Path(sys.modules[module_name()].__file__).parent
        cls.runner = runner.JobRunner(jobs_root=Path(cls.tmp.name) / "jobs",
                                      package_dir=package_dir,
                                      blender_python=Path(sys.executable))
        cls.clock = _Clock()
        cls.monitor = cls.ops.JobMonitor(clock=cls.clock)
        cls.patch = mock.patch.object(cls.ops, "MONITOR", cls.monitor)
        cls.patch.start()
        cls.monitor.attach(cls.runner)
        cls.catalog.register_worker(cls.catalog.WorkerInfo(
            BOOM_WORKER, "Failing test job", policy="auto",
            estimate_s=lambda _params: 0.01, run=_boom,
        ))
        cls.before = (bpy.app.timers.is_registered(cls.ops.tick), _field(cls.ui),
                      _field(cls.ui, geoblender=False),
                      cls.ui.width_px(_context(geoblender=True)))
        requests = [
            protocol.new_request("selftest", label=SUM_LABEL, owner="jobs",
                                 params=SUM_PARAMS),
            protocol.new_request(BOOM_WORKER, label=BOOM_LABEL, owner="jobs"),
        ]
        with mock.patch.object(bpy.app.timers, "register",
                               wraps=bpy.app.timers.register) as register:
            cls.handles = [cls.monitor.submit(request) for request in requests]
        cls.timer_calls = [call.kwargs for call in register.call_args_list
                           if call.args and call.args[0] is cls.ops.tick]
        cls.registered_after_submit = bpy.app.timers.is_registered(cls.ops.tick)
        cls._run_scenario()

    @classmethod
    def _run_scenario(cls) -> None:
        """Sondea a mano hasta que acaban los dos; después adelanta el reloj del monitor."""
        cls.running: list[tuple[object, _Frame, _Frame]] = []
        cls.sum_notice: tuple[_Frame, _Frame] | None = None
        total, failing = cls.handles
        deadline = time.monotonic() + SCENARIO_DEADLINE_S
        with mock.patch.object(cls.statusbar, "redraw",
                               wraps=cls.statusbar.redraw) as redraw:
            while failing.result() is None and time.monotonic() < deadline:
                returned = cls.ops.tick()
                frames = (_field(cls.ui), _field(cls.ui, geoblender=False))
                if total.result() is None:
                    cls.running.append((returned, *frames))
                elif cls.sum_notice is None:
                    cls.sum_notice = frames
                time.sleep(TICK_SLEEP_S)
            cls.redraws = redraw.call_count
        cls.boom_notice = (_field(cls.ui), _field(cls.ui, geoblender=False))
        cls.bar_with_notice = (_bar_texts(cls.statusbar, geoblender=True),
                               _bar_texts(cls.statusbar, geoblender=False))
        cls.snapshots = {s.name: s for s in cls.runner.snapshots()}
        cls.clock.offset = NOTICE_S - 0.5
        cls.before_expiry = (cls.ops.tick(), _field(cls.ui),
                             _field(cls.ui, geoblender=False))
        cls.clock.offset = NOTICE_S + 0.5
        cls.after_expiry = (cls.ops.tick(), _field(cls.ui), _field(cls.ui, geoblender=False),
                            cls.ui.width_px(_context(geoblender=True)),
                            bpy.app.timers.is_registered(cls.ops.tick),
                            _bar_texts(cls.statusbar, geoblender=True),
                            _bar_texts(cls.statusbar, geoblender=False))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.runner.shutdown(timeout_s=2.0)
        cls.monitor.stop()
        cls.patch.stop()
        cls.catalog.unregister_worker(BOOM_WORKER)
        blender_ext.unload()
        cls.tmp.cleanup()

    def test_field_registered_for_both_modes(self) -> None:
        """RF-004-06: el campo «jobs» es de la barra de estado de la 003 (prioridad 1, los
        dos modos), sin un ``append`` propio; sin trabajos no ocupa sitio ni dibuja nada y
        no hay temporizador."""
        field = {f.key: f for f in self.statusbar.fields()}[FIELD]
        self.assertEqual(field.priority, 1)
        self.assertEqual(field.modes, frozenset({"GEOBLENDER", "BLENDER"}))
        ours = [f for f in getattr(bpy.types.STATUSBAR_HT_header.draw, "_draw_funcs", ())
                if getattr(f, "__module__", "").startswith(module_name() + ".")]
        self.assertEqual(ours, [self.statusbar.draw_statusbar])
        registered, geoblender, blender, width = self.before
        self.assertFalse(registered)
        self.assertTrue(geoblender.empty)
        self.assertTrue(blender.empty)
        self.assertEqual(width, 0.0)

    def test_timer_from_the_first_job(self) -> None:
        """RF-004-06: lanzar el primer trabajo registra el temporizador (persistente, cada
        0,25 s) una sola vez; mientras hay trabajos, ``tick`` pide seguir cada 0,25 s y
        redibuja la barra de estado."""
        self.assertEqual(self.timer_calls, [TIMER_KWARGS])
        self.assertTrue(self.registered_after_submit)
        self.assertGreaterEqual(len(self.running), 10)
        self.assertEqual({returned for returned, _g, _b in self.running}, {0.25})
        self.assertGreaterEqual(self.redraws, len(self.running))

    def test_number_name_and_rising_percent(self) -> None:
        """RF-004-06: mientras corre el de 2 s, en los dos modos, el número de activos (2:
        el otro espera en la cola), su nombre y su avance con «%», que crece y nunca
        retrocede, su último mensaje y los botones de la lista y de cancelar."""
        percents: list[int] = []
        for _returned, geoblender, blender in self.running:
            self.assertEqual(geoblender.texts, blender.texts)
            self.assertEqual(geoblender.count, "2")
            self.assertTrue(geoblender.bar.startswith(SUM_LABEL + " · "), geoblender.bar)
            self.assertTrue(geoblender.bar.endswith(" %"), geoblender.bar)
            self.assertAlmostEqual(geoblender.factor, geoblender.percent / 100, delta=0.01)
            self.assertEqual(geoblender.operators, JOB_OPERATORS)
            self.assertIsNone(geoblender.notice)
            percents.append(geoblender.percent)
        self.assertEqual(percents, sorted(percents))
        self.assertGreaterEqual(len(set(percents)), 5, percents)
        self.assertLessEqual(percents[-1], 100)
        self.assertGreaterEqual(percents[-1], 50)
        shown = [g.message for _r, g, _b in self.running if g.message]
        self.assertTrue(shown)
        self.assertTrue(all(m.startswith("Trozo ") and m.endswith(" de 20") for m in shown),
                        shown)

    def test_success_notice(self) -> None:
        """RF-004-07: al terminar el de 2 s, su nombre, «Terminado» y su duración en s, con
        el icono de hecho, en los dos modos; el que falla ya corre (1 activo)."""
        self.assertIsNotNone(self.sum_notice)
        geoblender, blender = self.sum_notice
        self.assertEqual(geoblender.texts, blender.texts)
        duration = self.snapshots[SUM_LABEL].duration_s
        self.assertGreater(duration, 1.5)
        seconds = self.i18n.format_number(duration, 1)
        self.assertEqual(geoblender.notice, f"{SUM_LABEL} · Terminado · {seconds} s")
        self.assertEqual(geoblender.notice_icon, "CHECKMARK")
        self.assertEqual(geoblender.count, "1")

    def test_failure_notice_without_traceback(self) -> None:
        """RF-004-07: el que falla con una excepción no capturada muestra su nombre,
        «Fallido», su duración y el mensaje del §8 en una línea, con el icono de error, en
        los dos modos y en la barra entera; la traza solo está en su registro."""
        geoblender, blender = self.boom_notice
        self.assertEqual(geoblender.texts, blender.texts)
        snapshot = self.snapshots[BOOM_LABEL]
        expected = self.messages.render("worker_crashed", job=BOOM_LABEL, exit_code=1)
        seconds = self.i18n.format_number(snapshot.duration_s, 1)
        self.assertEqual(geoblender.notice,
                         f"{BOOM_LABEL} · Fallido · {seconds} s · {expected}")
        self.assertEqual(geoblender.notice_icon, "ERROR")
        self.assertIsNone(geoblender.count)
        for texts in self.bar_with_notice:
            self.assertIn(geoblender.notice, texts)
            self.assertFalse([t for t in texts if "Traceback" in t or BOOM_ERROR in t])
        log = (Path(self.tmp.name) / "jobs" / snapshot.job_uid / "job.log").read_text(
            encoding="utf-8")
        self.assertIn("Traceback", log)
        self.assertIn(BOOM_ERROR, log)

    def test_notice_lasts_ten_seconds(self) -> None:
        """RF-004-07: el aviso sigue a los 9,5 s y a los 10,5 s ha desaparecido: el campo
        no dibuja nada ni ocupa sitio en ningún modo y el temporizador se retira."""
        returned, geoblender, blender = self.before_expiry
        self.assertEqual(returned, 0.25)
        self.assertEqual(geoblender.notice, self.boom_notice[0].notice)
        self.assertEqual(blender.notice, self.boom_notice[0].notice)
        returned, geoblender, blender, width, registered, full, plain = self.after_expiry
        self.assertIsNone(returned)
        self.assertTrue(geoblender.empty)
        self.assertTrue(blender.empty)
        self.assertEqual(width, 0.0)
        self.assertFalse(registered)
        self.assertEqual(plain, [])
        self.assertFalse([t for t in full if BOOM_LABEL in t or SUM_LABEL in t])


class _FakeRunner:
    """Un lanzador simulado: ``poll`` devuelve los finales que se le dan y ``snapshots``,
    las fotos que se le dan."""

    def __init__(self) -> None:
        self.snapshots_now: list[object] = []
        self.finished_now: list[str] = []
        self.jobs_root: Path | None = None

    def poll(self) -> list[object]:
        finished, self.finished_now = self.finished_now, []
        return [SimpleNamespace(job_uid=uid, finished=True) for uid in finished]

    def snapshots(self) -> list[object]:
        return list(self.snapshots_now)


class JobMonitorLogicTest(unittest.TestCase):
    """El monitor con un lanzador simulado: avances fuera de rango o que retroceden,
    trabajos en cola, cada final y el idioma."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.ops = _module("bl.ops.jobs")
        cls.ui = _module("bl.ui.jobs")
        cls.statusbar = _module("bl.ui.statusbar")
        cls.runner_mod = _module("jobs.runner")
        cls.records = _module("jobs.records")
        cls.messages = _module("jobs.messages")
        cls.i18n = _module("core.i18n")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def setUp(self) -> None:
        self.monitor = self.ops.JobMonitor(clock=_Clock())
        patch = mock.patch.object(self.ops, "MONITOR", self.monitor)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.monitor.stop)
        self.fake = _FakeRunner()
        self.monitor.attach(self.fake)

    def snapshot(self, uid: str, name: str, state: str, *, frac: float = 0.0,
                 message: str = "", duration_s: float | None = None,
                 error: object = None) -> object:
        return self.runner_mod.JobSnapshot(
            job_uid=uid, name=name, worker="selftest", state=state, executor="subprocess",
            frac=frac, message=message, duration_s=duration_s, interpreter=None,
            error=error, cancel_requested=False,
        )

    def field(self, *, geoblender: bool = True) -> _Frame:
        return _field(self.ui, geoblender=geoblender)

    def test_progress_never_goes_back(self) -> None:
        """RF-004-06 (spec §8): un avance que retrocede no baja la barra y uno de más del
        100 % se queda en 100 %; otro trabajo empieza con su propio avance."""
        shown = []
        for frac in (0.5, 0.3, 0.42, 1.7):
            self.fake.snapshots_now = [self.snapshot("a", "Uno", "running", frac=frac)]
            self.assertEqual(self.ops.tick(), 0.25)
            frame = self.field()
            shown.append((frame.percent, frame.factor))
        self.assertEqual(shown, [(50, 0.5), (50, 0.5), (50, 0.5), (100, 1.0)])
        self.fake.snapshots_now = [self.snapshot("b", "Dos", "running", frac=0.1)]
        self.ops.tick()
        self.assertEqual((self.field().bar, self.field().percent), ("Dos · 10 %", 10))

    def test_oldest_running_and_queued(self) -> None:
        """RF-004-06: con uno en cola delante, la barra es la del más antiguo en curso; con
        todos en cola, el más antiguo y «En cola», sin avance."""
        self.fake.snapshots_now = [
            self.snapshot("q", "En espera", "queued"),
            self.snapshot("r1", "Primero en curso", "running", frac=0.25, message="Paso 1"),
            self.snapshot("r2", "Segundo en curso", "running", frac=0.75),
        ]
        self.ops.tick()
        frame = self.field()
        self.assertEqual((frame.count, frame.bar, frame.message),
                         ("3", "Primero en curso · 25 %", "Paso 1"))
        self.fake.snapshots_now = [self.snapshot("q", "En espera", "queued"),
                                   self.snapshot("q2", "Otro", "queued")]
        self.ops.tick()
        frame = self.field(geoblender=False)
        self.assertEqual((frame.count, frame.bar, frame.factor, frame.message),
                         ("2", "En espera · En cola", 0.0, None))

    def test_every_final_state(self) -> None:
        """RF-004-07: cada estado final con su icono, su nombre, su estado y su duración;
        el mensaje solo si no terminó bien; sin duración (no llegó a arrancar), 0 s."""
        error = self.records.ErrorInfo(code="job_cancelled",
                                       msgid="Job «{job}» cancelled{forced}.",
                                       values={"job": "J", "forced": True},
                                       text="Trabajo «J» cancelado (forzado).")
        cases = (
            ("succeeded", None, 12.34, "J · Terminado · 12,3 s"),
            ("cancelled", error, None,
             "J · Cancelado · 0,0 s · Trabajo «J» cancelado (forzado)."),
        )
        for state, info, duration, expected in cases:
            with self.subTest(estado=state):
                self.fake.snapshots_now = [self.snapshot(state, "J", state, frac=1.0,
                                                         duration_s=duration, error=info)]
                self.fake.finished_now = [state]
                self.ops.tick()
                frame = self.field()
                self.assertEqual((frame.notice, frame.notice_icon),
                                 (expected, NOTICE_ICONS[state]))
                self.assertIsNone(frame.count)
        for state in ("failed", "timed_out", "interrupted"):
            with self.subTest(estado=state):
                self.fake.snapshots_now = [self.snapshot(state, "K", state, duration_s=1.0,
                                                         error=error)]
                self.fake.finished_now = [state]
                self.ops.tick()
                self.assertEqual(self.field().notice_icon, NOTICE_ICONS[state])

    def test_traceback_and_english(self) -> None:
        """RF-004-07: de un mensaje con una traza solo queda su última línea; en inglés, el
        estado y el mensaje del §8 en inglés."""
        traced = self.records.ErrorInfo(
            code="gbtest_custom", msgid="Custom failure: {detail}", values={"detail": "x"},
            text="Traceback (most recent call last):\n  File \"w.py\", line 1\nValueError: x",
        )
        self.fake.snapshots_now = [self.snapshot("t", "T", "failed", duration_s=0.5,
                                                 error=traced)]
        self.fake.finished_now = ["t"]
        self.ops.tick()
        self.assertEqual(self.field().notice, "T · Fallido · 0,5 s · ValueError: x")
        crashed = self.records.ErrorInfo.from_job_error(
            self.messages.JobError("worker_crashed", job="T", exit_code=1))
        self.fake.snapshots_now = [self.snapshot("t2", "T", "failed", duration_s=0.5,
                                                 error=crashed)]
        self.fake.finished_now = ["t2"]
        self.ops.tick()
        self.i18n.set_language("en")
        self.addCleanup(self.i18n.set_language, "es")
        english = self.messages.render("worker_crashed", language="en", job="T", exit_code=1)
        self.assertEqual(self.field().notice, f"T · Failed · 0.5 s · {english}")

    def test_redraw_skips_modal_windows(self) -> None:
        """RF-004-06: el redibujo fuerza la barra de estado de cada ventana sin operadores
        modales (con uno, su texto es suyo) y cuenta cuántas."""
        modal = SimpleNamespace(modal_operators=[object()],
                                workspace=SimpleNamespace(status_text_set=mock.Mock()))
        window = bpy.context.window_manager.windows[0]
        self.assertEqual(self.statusbar.redraw([modal, window]), 1)
        modal.workspace.status_text_set.assert_not_called()

    def test_submit_needs_a_runner(self) -> None:
        """RF-004-06: sin lanzador no se lanza nada ni se registra el temporizador."""
        self.monitor.attach(None)
        with self.assertRaises(RuntimeError):
            self.monitor.submit(object())
        self.assertFalse(bpy.app.timers.is_registered(self.ops.tick))


class JobMonitorRegistrationTest(unittest.TestCase):
    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)

    def test_disable_retires_timer_and_field(self) -> None:
        """RF-004-06, RF-004-07: desactivar Geoblender retira el temporizador del monitor y
        el campo «jobs», y deja la huella del principio de la sesión."""
        blender_ext.enable()
        ops = _module("bl.ops.jobs")
        statusbar = _module("bl.ui.statusbar")
        ops.MONITOR.start()
        self.assertTrue(bpy.app.timers.is_registered(ops.tick))
        self.assertIn(FIELD, [field.key for field in statusbar.fields()])
        blender_ext.disable()
        self.assertFalse(bpy.app.timers.is_registered(ops.tick))
        self.assertNotIn(FIELD, [field.key for field in statusbar.fields()])
        after = state_fingerprint()
        before = blender_ext.session_baseline()
        if after != before:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(before, after)))


# --- T20: operadores de los trabajos y lista de trabajos --------------------------------

SHOW_JOBS = "geoblender.jobs_show_jobs"
CANCEL_JOB = "geoblender.jobs_cancel"
CLEAN_JOB = "geoblender.jobs_clean"
PATH_OPEN = "wm.path_open"
JOBS_MENU = "GEOBLENDER_MT_jobs_menu"
JOBS_PANEL = "GEOBLENDER_PT_jobs_list"
REAL_OPERATORS = {SHOW_JOBS: "GEOBLENDER_OT_jobs_show_jobs",
                  CANCEL_JOB: "GEOBLENDER_OT_jobs_cancel"}
CATALOG_LABELS = {SHOW_JOBS: "Background jobs", CANCEL_JOB: "Cancel the active job"}
GATED_WORKER = "gbtest_gated"
GATE_POLL_S = 0.02
WAIT_S = 10.0
NO_JOBS = "No hay trabajos en curso"
NO_VALUE = "—"


class _Gates:
    """El cálculo de ``gbtest_gated``: avisa del 30 % y espera a que la prueba suelte su
    trabajo (por su nombre), atendiendo la cancelación."""

    def __init__(self) -> None:
        self.events: dict[str, threading.Event] = {}

    def __getitem__(self, label: str) -> threading.Event:
        return self.events.setdefault(label, threading.Event())

    def release_all(self) -> None:
        for event in list(self.events.values()):
            event.set()

    def run(self, ctx: object) -> dict[str, object]:
        ctx.progress(0.3, "Esperando")
        while not self[ctx.request.label].wait(GATE_POLL_S):
            ctx.check_cancelled()
        return {"ok": True}


class _JobRow:
    """Lo que dibuja la lista para un trabajo: su nombre (con el icono de su estado), su
    estado, la barra de avance, la duración, los botones y la línea de detalle (intérprete
    y último mensaje)."""

    def __init__(self, items: list[object]) -> None:
        head = items[0]
        self.name, self.icon = head.text, head.icon
        labels = [item for item in items[1:] if item.kind == "label"]
        self.state = labels[0].text
        self.duration = labels[1].text
        self.details = labels[2].text if len(labels) > 2 else ""
        self.details_active = labels[2].active if len(labels) > 2 else None
        bar = [item for item in items if item.kind == "progress"][0]
        self.bar, self.factor = bar.text, bar.options.get("factor")
        self.buttons = {item.target: item for item in items if item.kind == "operator"}


def _panel(ui: ModuleType) -> FakeLayout:
    """La lista de trabajos (``GEOBLENDER_PT_jobs_list``) dibujada."""
    return draw(ui.GEOBLENDER_PT_jobs_list, bpy.context)


def _rows(layout: FakeLayout, names: list[str]) -> dict[str, _JobRow]:
    """Las filas de los trabajos ``names``: de la etiqueta con su nombre a la del
    siguiente."""
    starts = [index for index, item in enumerate(layout.items)
              if item.kind == "label" and item.text in names]
    rows: dict[str, _JobRow] = {}
    for number, start in enumerate(starts):
        end = starts[number + 1] if number + 1 < len(starts) else len(layout.items)
        row = _JobRow(layout.items[start:end])
        rows[row.name] = row
    return rows


class JobOperatorsCatalogTest(unittest.TestCase):
    """Con la extensión habilitada una vez para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.commands = _module("bl.ui.commands")
        cls.registry = _module("bl.ui.registry")
        cls.ops = _module("bl.ops.jobs")
        cls.ui = _module("bl.ui.jobs")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def test_real_operators_replace_the_provisionals(self) -> None:
        """RF-004-08, RF-004-09: ``geoblender.jobs_show_jobs`` y ``geoblender.jobs_cancel``
        son los operadores reales de ``bl/ops/jobs.py`` con el ``bl_idname`` del catálogo
        de la 003, que no genera provisionales para ellos: están disponibles, con el nombre
        y la descripción del catálogo en el idioma de Geoblender y el contexto de
        traducción «Geoblender»."""
        provisional = set(self.registry.provisional_classes())
        real = _module("bl.ops").classes
        for idname, name in REAL_OPERATORS.items():
            with self.subTest(idname=idname):
                cls = self.commands.registered_class(idname)
                self.assertIs(cls, getattr(self.ops, name))
                self.assertIn(cls, real)
                self.assertNotIn(cls, provisional)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertTrue(self.commands.is_available(idname))
                cmd = self.cat.commands[idname]
                self.assertEqual(cmd.label, CATALOG_LABELS[idname])
                self.assertEqual(cls.bl_label, self.commands.text(cmd.label))
                self.assertEqual(cls.bl_description, self.commands.text(cmd.description))
                self.assertEqual(cls.bl_translation_context,
                                 self.commands.TRANSLATION_CONTEXT)

    def test_jobs_menu_draws_them_enabled(self) -> None:
        """RF-004-08, RF-004-09: Herramientas ▸ Trabajos (``GEOBLENDER_MT_jobs_menu``) es
        el menú generado del catálogo, sin provisional, y dibuja los dos operadores
        activos, con su nombre del catálogo (la 004 ya entrega sus comandos)."""
        menu = self.commands.registered_class(JOBS_MENU)
        self.assertIsNotNone(menu)
        self.assertFalse(self.commands.is_provisional(menu))
        self.assertIn(menu, self.registry.own_classes())
        self.assertTrue(self.commands.is_available(JOBS_MENU))
        drawn = {item.target: item for item in draw(menu, bpy.context).of_kind("operator")}
        for idname in REAL_OPERATORS:
            with self.subTest(idname=idname):
                self.assertTrue(drawn[idname].enabled)
                self.assertEqual(drawn[idname].text,
                                 self.commands.text(self.cat.commands[idname].label))

    def test_list_panel_registered(self) -> None:
        """RF-004-08: ``GEOBLENDER_PT_jobs_list`` es un panel emergente de ``bl/ui`` (región
        de cabecera: solo se abre con ``wm.call_panel``), fuera del catálogo y sin
        provisional."""
        panel = getattr(bpy.types, JOBS_PANEL, None)
        self.assertIsNotNone(panel)
        self.assertTrue(panel.is_registered)
        self.assertIs(panel, self.ui.GEOBLENDER_PT_jobs_list)
        self.assertIn(panel, _module("bl.ui").classes)
        self.assertEqual(panel.bl_region_type, "HEADER")
        self.assertNotIn(JOBS_PANEL, self.cat.commands)
        self.assertNotIn(panel, self.registry.own_classes())


class JobCancelTest(unittest.TestCase):
    """Tres trabajos en hilo de un tipo de prueba que espera a que lo suelten, con un solo
    hueco de hilo (uno en curso y dos en cola), cancelados con ``geoblender.jobs_cancel``
    como el botón de la barra de estado (sin ``job_uid``) o el de la lista (con él)."""

    NAMES = ("Primero", "Segundo", "Tercero")

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.ops = _module("bl.ops.jobs")
        cls.ui = _module("bl.ui.jobs")
        cls.commands = _module("bl.ui.commands")
        cls.catalog = _module("jobs.catalog")
        cls.i18n = _module("core.i18n")
        protocol = _module("jobs.protocol")
        runner = _module("jobs.runner")
        cls.tmp = tempfile.TemporaryDirectory(prefix="gb4-")
        package_dir = Path(sys.modules[module_name()].__file__).parent
        cls.runner = runner.JobRunner(jobs_root=Path(cls.tmp.name) / "jobs",
                                      package_dir=package_dir,
                                      blender_python=Path(sys.executable), max_inprocess=1)
        cls.monitor = cls.ops.JobMonitor(clock=_Clock())
        cls.patch = mock.patch.object(cls.ops, "MONITOR", cls.monitor)
        cls.patch.start()
        cls.monitor.attach(cls.runner)
        cls.gates = _Gates()
        cls.catalog.register_worker(cls.catalog.WorkerInfo(
            GATED_WORKER, "Gated test job", policy="auto",
            estimate_s=lambda _params: 0.1, run=cls.gates.run,
        ))
        try:
            cls._run_scenario(protocol)
        finally:
            cls.gates.release_all()

    @classmethod
    def _run_scenario(cls, protocol: ModuleType) -> None:
        operator = bpy.ops.geoblender.jobs_cancel
        cls.poll_empty = (operator.poll(), cls._poll())
        cls.handles = {name: cls.monitor.submit(protocol.new_request(
            GATED_WORKER, label=name, owner="jobs")) for name in cls.NAMES}
        first, second, third = (cls.handles[name] for name in cls.NAMES)
        cls._wait(lambda: first.message == "Esperando")
        cls.poll_running = (operator.poll(), cls._poll())
        cls.listed = _rows(_panel(cls.ui), list(cls.NAMES))
        cls.by_default = operator()
        cls.after_default = cls._states()
        cls.twice = cls._execute("")
        cls.queued = operator(job_uid=third.job_uid)
        cls.after_queued = cls._states()
        cls._wait(lambda: first.result() is not None and second.message == "Esperando")
        cls.finished_again = cls._execute(first.job_uid)
        cls.unknown = cls._execute("gbtest-desconocido")
        cls.second_by_default = cls._execute("")
        cls._wait(lambda: second.result() is not None)
        cls.after_all = cls._states()
        cls.poll_after = (operator.poll(), cls._poll())
        cls.final = _rows(_panel(cls.ui), list(cls.NAMES))
        cls.snapshots = {s.name: s for s in cls.runner.snapshots()}

    @classmethod
    def _wait(cls, condition: object) -> None:
        deadline = time.monotonic() + WAIT_S
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError("los trabajos de prueba no avanzaron a tiempo")
            cls.ops.tick()
            time.sleep(GATE_POLL_S)

    @classmethod
    def _poll(cls) -> tuple[bool, list[str]]:
        """El ``poll`` del operador y los mensajes con que explica por qué no."""
        operator = cls.ops.GEOBLENDER_OT_jobs_cancel
        with mock.patch.object(operator, "poll_message_set") as message:
            allowed = operator.poll(bpy.context)
        return allowed, [call.args[0] for call in message.call_args_list]

    @classmethod
    def _execute(cls, job_uid: str) -> tuple[set[str], list[tuple[set[str], str]]]:
        """El operador con ``job_uid``, con sus avisos."""
        reports: list[tuple[set[str], str]] = []
        fake = SimpleNamespace(job_uid=job_uid,
                               report=lambda kind, text: reports.append((set(kind), text)))
        result = cls.ops.GEOBLENDER_OT_jobs_cancel.execute(fake, bpy.context)
        return result, reports

    @classmethod
    def _states(cls) -> dict[str, tuple[str, bool]]:
        return {s.name: (s.state, s.cancel_requested) for s in cls.runner.snapshots()}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.gates.release_all()
        cls.runner.shutdown(timeout_s=2.0)
        cls.monitor.stop()
        cls.patch.stop()
        cls.catalog.unregister_worker(GATED_WORKER)
        blender_ext.unload()
        cls.tmp.cleanup()

    def test_poll_false_explains_why(self) -> None:
        """RF-004-09: sin trabajos activos (antes de lanzar, después de acabar todos y sin
        lanzador) el ``poll`` falla y explica por qué; con uno en curso, se puede."""
        self.assertEqual(self.poll_empty, (False, (False, [NO_JOBS])))
        self.assertEqual(self.poll_after, (False, (False, [NO_JOBS])))
        self.assertEqual(self.poll_running, (True, (True, [])))
        with mock.patch.object(self.ops, "MONITOR", self.ops.JobMonitor()):
            self.assertFalse(bpy.ops.geoblender.jobs_cancel.poll())
            self.assertEqual(self._poll(), (False, [NO_JOBS]))

    def test_without_job_uid_cancels_the_oldest_running(self) -> None:
        """RF-004-09: sin ``job_uid`` se cancela el más antiguo en curso, no los de la cola;
        cuando acaba, el siguiente en curso es el más antiguo y se cancela igual, con su
        aviso."""
        self.assertEqual(self.by_default, {"FINISHED"})
        self.assertEqual(self.after_default, {"Primero": ("running", True),
                                              "Segundo": ("queued", False),
                                              "Tercero": ("queued", False)})
        self.assertEqual(self.second_by_default,
                         ({"FINISHED"}, [({"INFO"}, "Cancelando el trabajo «Segundo»")]))
        self.assertEqual(self.after_all, {"Primero": ("cancelled", True),
                                          "Segundo": ("cancelled", True),
                                          "Tercero": ("cancelled", True)})
        for name in ("Primero", "Segundo"):
            with self.subTest(trabajo=name):
                snapshot = self.snapshots[name]
                self.assertEqual(snapshot.error.code, "job_cancelled")
                self.assertIsNotNone(snapshot.interpreter)

    def test_queued_job_cancelled_without_starting(self) -> None:
        """RF-004-09: uno en cola, con su ``job_uid``, queda «Cancelado» al momento y sin
        arrancar (sin intérprete ni duración); el otro de la cola sigue esperando."""
        self.assertEqual(self.queued, {"FINISHED"})
        self.assertEqual(self.after_queued["Tercero"], ("cancelled", True))
        self.assertEqual(self.after_queued["Segundo"], ("queued", False))
        third = self.snapshots["Tercero"]
        self.assertIsNone(third.interpreter)
        self.assertIsNone(third.duration_s)
        self.assertEqual(third.error.code, "job_cancelled")

    def test_twice_finished_or_unknown_has_no_effect(self) -> None:
        """RF-004-09 (spec §8): cancelar otra vez el que ya se está cancelando, uno que ya
        terminó o uno que no existe no hace nada más y avisa."""
        self.assertEqual(self.twice, ({"CANCELLED"}, [(
            {"WARNING"}, "El trabajo «Primero» ya ha terminado o ya se está cancelando")]))
        self.assertEqual(self.finished_again, ({"CANCELLED"}, [(
            {"WARNING"}, "El trabajo «Primero» ya ha terminado o ya se está cancelando")]))
        self.assertEqual(self.unknown, ({"CANCELLED"}, [(
            {"WARNING"}, "No hay ningún trabajo «gbtest-desconocido»")]))
        self.assertFalse(self.snapshots["Primero"].error.values.get("forced"))

    def test_list_with_real_jobs(self) -> None:
        """RF-004-08: la lista enseña cada trabajo real con su nombre, estado, avance,
        duración, intérprete y último mensaje, y los botones de cancelar (los activos),
        abrir el registro (si ya lo tiene) y descartar (los terminados)."""
        running, queued = self.listed["Primero"], self.listed["Segundo"]
        self.assertEqual((running.state, running.bar, running.factor),
                         ("En curso", "30 %", 0.3))
        self.assertTrue(running.duration.endswith(" s"), running.duration)
        self.assertTrue(running.details.startswith("Blender · Python 3.13"), running.details)
        self.assertTrue(running.details.endswith(" · Esperando"), running.details)
        self.assertEqual((queued.state, queued.bar, queued.duration, queued.details),
                         ("En cola", "0 %", NO_VALUE, ""))
        for row in (running, queued, self.listed["Tercero"]):
            with self.subTest(trabajo=row.name):
                self.assertTrue(row.buttons[CANCEL_JOB].enabled)
                self.assertEqual(row.buttons[CANCEL_JOB].properties.job_uid,
                                 self.handles[row.name].job_uid)
                self.assertFalse(row.buttons[CLEAN_JOB].enabled)
        log = self.handles["Primero"].job_dir.log_file
        self.assertEqual(running.buttons[PATH_OPEN].properties.filepath, str(log))
        self.assertTrue(running.buttons[PATH_OPEN].enabled)
        self.assertFalse(queued.buttons[PATH_OPEN].enabled)
        discard = self.commands.is_available(CLEAN_JOB)
        for name in self.NAMES:
            with self.subTest(trabajo=name):
                row = self.final[name]
                self.assertEqual(row.state, "Cancelado")
                self.assertEqual(row.icon, "CANCEL")
                self.assertIn(f"Trabajo «{name}» cancelado.", row.details)
                self.assertFalse(row.buttons[CANCEL_JOB].enabled)
                self.assertEqual(row.buttons[CLEAN_JOB].enabled, discard)
        self.assertEqual(self.final["Tercero"].duration, NO_VALUE)
        self.assertTrue(self.final["Primero"].buttons[PATH_OPEN].enabled)


class JobsListPanelTest(unittest.TestCase):
    """La lista de trabajos con un lanzador simulado: cada estado con sus columnas y sus
    botones, el título, la carpeta y la lista vacía."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.ops = _module("bl.ops.jobs")
        cls.ui = _module("bl.ui.jobs")
        cls.commands = _module("bl.ui.commands")
        cls.runner_mod = _module("jobs.runner")
        cls.records = _module("jobs.records")
        cls.messages = _module("jobs.messages")
        cls.i18n = _module("core.i18n")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def setUp(self) -> None:
        self.monitor = self.ops.JobMonitor(clock=_Clock())
        patch = mock.patch.object(self.ops, "MONITOR", self.monitor)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.monitor.stop)
        self.fake = _FakeRunner()
        self.monitor.attach(self.fake)
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="gb4-")))
        self.log = self.folder / "job.log"
        self.log.write_bytes(b"registro\n")
        records, messages = self.records, self.messages
        blender = records.InterpreterInfo(kind="blender", python="3.13.9", numpy="2.3.4",
                                          blas="unknown")
        compute = records.InterpreterInfo(kind="compute", python="3.13.9", numpy="2.5.3",
                                          blas="scipy-openblas")
        crashed = records.ErrorInfo.from_job_error(
            messages.JobError("worker_crashed", job="Roto", exit_code=1))
        self.fake.snapshots_now = [
            self.snapshot("r", "En marcha", "running", frac=0.42, message="Trozo 3 de 7",
                          duration_s=2.26, interpreter=blender),
            self.snapshot("c", "Parándose", "running", frac=0.8, message="Trozo 8 de 10",
                          duration_s=4.0, interpreter=blender, cancel_requested=True),
            self.snapshot("q", "Esperando", "queued", log_file=self.folder / "no.log"),
            self.snapshot("s", "Hecho", "succeeded", frac=1.0, duration_s=12.34,
                          interpreter=compute),
            self.snapshot("f", "Roto", "failed", frac=0.5, duration_s=0.5,
                          interpreter=blender, error=crashed, ingested=True,
                          message="Traceback (most recent call last):\nValueError: x"),
        ]
        self.names = [s.name for s in self.fake.snapshots_now]

    def snapshot(self, uid: str, name: str, state: str, *, frac: float = 0.0,
                 message: str = "", duration_s: float | None = None,
                 interpreter: object = None, error: object = None,
                 cancel_requested: bool = False, log_file: Path | None = None,
                 ingested: bool = False) -> object:
        return self.runner_mod.JobSnapshot(
            job_uid=uid, name=name, worker="selftest", state=state, executor="subprocess",
            frac=frac, message=message, duration_s=duration_s, interpreter=interpreter,
            error=error, cancel_requested=cancel_requested,
            log_file=self.log if log_file is None else log_file, ingested=ingested,
        )

    def rows(self) -> dict[str, _JobRow]:
        rows = _rows(_panel(self.ui), self.names)
        self.assertEqual(list(rows), self.names)
        return rows

    def seconds(self, value: float) -> str:
        return self.i18n.format_number(value, 1) + " s"

    def test_each_job_with_its_columns(self) -> None:
        """RF-004-08: una fila por trabajo, por orden de llegada, con su nombre y el icono
        de su estado, su estado («Cancelando» si se pidió pararlo), su avance, su duración
        en s («—» si no arrancó) y, en gris, el intérprete y el último mensaje (el del §8
        si no terminó bien, sin traza)."""
        rows = self.rows()
        crashed = self.messages.render("worker_crashed", job="Roto", exit_code=1)
        expected = {
            "En marcha": ("SORTTIME", "En curso", "42 %", 0.42, self.seconds(2.26),
                          "Blender · Python 3.13.9 · numpy 2.3.4 · Trozo 3 de 7"),
            "Parándose": ("SORTTIME", "Cancelando", "80 %", 0.8, self.seconds(4.0),
                          "Blender · Python 3.13.9 · numpy 2.3.4 · Trozo 8 de 10"),
            "Esperando": ("SORTTIME", "En cola", "0 %", 0.0, NO_VALUE, ""),
            "Hecho": ("CHECKMARK", "Terminado", "100 %", 1.0, self.seconds(12.34),
                      "Motor de cálculo · Python 3.13.9 · numpy 2.5.3 · BLAS scipy-openblas"),
            "Roto": ("ERROR", "Fallido", "50 %", 0.5, self.seconds(0.5),
                        f"Blender · Python 3.13.9 · numpy 2.3.4 · {crashed}"),
        }
        for name, (icon, state, bar, factor, duration, details) in expected.items():
            with self.subTest(trabajo=name):
                row = rows[name]
                self.assertEqual((row.icon, row.state, row.bar, row.duration, row.details),
                                 (icon, state, bar, duration, details))
                self.assertAlmostEqual(row.factor, factor)
                if details:
                    self.assertFalse(row.details_active)
        self.assertNotIn("Traceback", " ".join(r.details for r in rows.values()))

    def test_buttons_by_state(self) -> None:
        """RF-004-08, RF-004-09: «Cancelar» (con su ``job_uid``) solo en los activos a los
        que no se pidió parar; «Registro» abre su ``job.log`` con ``wm.path_open`` si
        existe; «Descartar» (``geoblender.jobs_clean``, ``scope = ONE`` y su ``job_uid``)
        solo en los terminados que ningún módulo incorporó, y desactivado mientras ese
        operador no esté disponible."""
        rows = self.rows()
        cancel = {name: row.buttons[CANCEL_JOB] for name, row in rows.items()}
        self.assertEqual({name: item.enabled for name, item in cancel.items()},
                         {"En marcha": True, "Parándose": False, "Esperando": True,
                          "Hecho": False, "Roto": False})
        self.assertEqual(cancel["En marcha"].properties.job_uid, "r")
        self.assertEqual(cancel["Esperando"].properties.job_uid, "q")
        logs = {name: row.buttons[PATH_OPEN] for name, row in rows.items()}
        self.assertEqual({name: item.enabled for name, item in logs.items()},
                         {"En marcha": True, "Parándose": True, "Esperando": False,
                          "Hecho": True, "Roto": True})
        self.assertEqual(logs["Hecho"].properties.filepath, str(self.log))
        with mock.patch.object(self.commands, "is_available", return_value=False):
            unavailable = self.rows()
        for name, row in unavailable.items():
            with self.subTest(descartar=name, disponible=False):
                self.assertFalse(row.buttons[CLEAN_JOB].enabled)
                self.assertEqual(vars(row.buttons[CLEAN_JOB].properties), {})
        with mock.patch.object(self.commands, "is_available", return_value=True):
            available = self.rows()
        self.assertEqual({name: row.buttons[CLEAN_JOB].enabled
                          for name, row in available.items()},
                         {"En marcha": False, "Parándose": False, "Esperando": False,
                          "Hecho": True, "Roto": False})
        self.assertEqual(vars(available["Hecho"].buttons[CLEAN_JOB].properties),
                         {"scope": "ONE", "job_uid": "s"})

    def test_progress_matches_the_status_bar(self) -> None:
        """RF-004-08 (y RF-004-06, spec §8): el avance de uno en curso es el de la barra de
        estado, que nunca retrocede ni pasa del 100 %."""
        self.fake.snapshots_now = [self.snapshot("r", "En marcha", "running", frac=0.5)]
        self.names = ["En marcha"]
        self.ops.tick()
        self.fake.snapshots_now = [self.snapshot("r", "En marcha", "running", frac=0.3)]
        self.ops.tick()
        self.assertEqual(self.rows()["En marcha"].bar, "50 %")
        self.fake.snapshots_now = [self.snapshot("r", "En marcha", "running", frac=1.7)]
        self.ops.tick()
        self.assertEqual((self.rows()["En marcha"].bar, self.rows()["En marcha"].factor),
                         ("100 %", 1.0))

    def test_title_folder_and_empty_list(self) -> None:
        """RF-004-08: la lista lleva su título y, si se midió al abrirla, lo que ocupa la
        carpeta de los trabajos; sin trabajos (o sin lanzador) lo dice."""
        self.fake.snapshots_now = []
        texts = _panel(self.ui).texts()
        self.assertEqual(texts, ["Trabajos en segundo plano",
                                 "No hay trabajos en segundo plano"])
        self.monitor.attach(None)
        self.assertEqual(_panel(self.ui).texts(), texts)
        self.monitor.attach(self.fake)
        self.fake.jobs_root = self.folder
        self.assertEqual(self.ui.measure_folder(self.folder), 9 / 1e6)
        self.addCleanup(self.ui.measure_folder, None)
        size = self.i18n.format_number(9 / 1e6, 1)
        self.assertEqual(_panel(self.ui).texts(),
                         ["Trabajos en segundo plano", f"Carpeta de los trabajos: {size} MB",
                          "No hay trabajos en segundo plano"])

    def test_english(self) -> None:
        """RF-004-08: en inglés, los estados y los mensajes del §8, en inglés."""
        self.i18n.set_language("en")
        self.addCleanup(self.i18n.set_language, "es")
        rows = self.rows()
        english = self.messages.render("worker_crashed", language="en", job="Roto",
                                       exit_code=1)
        self.assertEqual(rows["Parándose"].state, "Cancelling")
        self.assertEqual(rows["Roto"].state, "Failed")
        self.assertTrue(rows["Roto"].details.endswith(english))
        self.assertTrue(rows["Hecho"].details.startswith("Compute engine · "))


class ShowJobsTest(unittest.TestCase):
    """``geoblender.jobs_show_jobs`` abre la lista de trabajos (``wm.call_panel``)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.ops = _module("bl.ops.jobs")
        cls.ui = _module("bl.ui.jobs")
        cls.cleanup = _module("jobs.cleanup")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def setUp(self) -> None:
        self.monitor = self.ops.JobMonitor(clock=_Clock())
        patch = mock.patch.object(self.ops, "MONITOR", self.monitor)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.ui.measure_folder, None)

    def test_poll_needs_a_window(self) -> None:
        """RF-004-08: sin ventana no se puede abrir la lista y el ``poll`` lo explica; con
        una ventana, sí."""
        operator = self.ops.GEOBLENDER_OT_jobs_show_jobs
        with mock.patch.object(operator, "poll_message_set") as message:
            self.assertFalse(operator.poll(SimpleNamespace(window=None)))
        message.assert_called_once_with("La lista de trabajos necesita una ventana de Blender")
        window = bpy.context.window_manager.windows[0]
        with bpy.context.temp_override(window=window):
            self.assertTrue(bpy.ops.geoblender.jobs_show_jobs.poll())

    def test_opens_the_list_and_measures_the_folder(self) -> None:
        """RF-004-08: abre ``GEOBLENDER_PT_jobs_list`` con ``wm.call_panel`` (que sigue
        abierta) y antes mide lo que ocupa la carpeta de los trabajos del lanzador."""
        folder = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="gb4-")))
        (folder / "uno").mkdir()
        (folder / "uno" / "datos.bin").write_bytes(b"x" * 300_000)
        fake = _FakeRunner()
        fake.jobs_root = folder
        self.monitor.attach(fake)
        window = bpy.context.window_manager.windows[0]
        with mock.patch.object(self.ops, "_call_panel",
                               return_value={"FINISHED"}) as call_panel:
            with bpy.context.temp_override(window=window):
                result = bpy.ops.geoblender.jobs_show_jobs()
        self.assertEqual(result, {"FINISHED"})
        call_panel.assert_called_once_with(JOBS_PANEL)
        self.assertEqual(self.ui.folder_size(folder), self.cleanup.folder_size_mb(folder))
        self.assertEqual(self.ui.folder_size(folder), 0.3)
        self.assertIn("Carpeta de los trabajos: 0,3 MB", _panel(self.ui).texts())
        self.monitor.attach(None)
        with mock.patch.object(self.ops, "_call_panel",
                               return_value={"FINISHED"}) as call_panel:
            with bpy.context.temp_override(window=window):
                self.assertEqual(bpy.ops.geoblender.jobs_show_jobs(), {"FINISHED"})
        call_panel.assert_called_once_with(JOBS_PANEL)
        self.assertIsNone(self.ui.folder_size(folder))


# --- T21: autodiagnóstico y limpieza de los trabajos ------------------------------------

RUN_SELFTEST = "geoblender.jobs_run_selftest"
T21_OPERATORS = {RUN_SELFTEST: "GEOBLENDER_OT_jobs_run_selftest",
                 CLEAN_JOB: "GEOBLENDER_OT_jobs_clean"}
T21_LABELS = {RUN_SELFTEST: "Self-test", CLEAN_JOB: "Clean finished jobs…"}
SELFTEST_NAMES = {
    "SUM_10S": "Autodiagnóstico: suma de 10 s",
    "MATMUL_COMPUTE": "Autodiagnóstico: producto 2000 × 2000 con el motor de cálculo",
    "MATMUL_BLENDER": "Autodiagnóstico: producto 500 × 500 con el numpy de Blender",
}
NO_RUNNER = "Geoblender aún no ha preparado la carpeta de los trabajos"
CLEAN_WORKER = "gbtest_clean"
KB = 1000
# T37: el autodiagnóstico de 10 s se cancela tras sus primeros trozos, que bastan para
# medir cada cuánto avanza; M1 y H2 piden al menos dos avances por segundo.
SAMPLED_CHUNKS = 3
PROGRESS_EVERY_S = 0.25
SUM_10S_S = 10.0
SUM_10S_TOLERANCE_S = 0.5


def _chunk_number(message: str) -> int:
    """El ``k`` del avance «Trozo k de N» del autodiagnóstico; 0 con otro mensaje."""
    words = message.split()
    if len(words) == 4 and words[0] == "Trozo" and words[1].isdigit() and words[2] == "de":
        return int(words[1])
    return 0


def _channel_events(folder: Path) -> list[dict[str, object]]:
    """Los eventos del canal del worker que el lanzador dejó en ``events.jsonl`` de
    ``folder``, en orden, sin sus propias notas."""
    events_file = folder / _module("jobs.paths").EVENTS_FILE
    lines = events_file.read_text(encoding="utf-8").splitlines()
    return [item for item in map(json.loads, lines) if "t" in item]


def _bytes(path: Path) -> int:
    """Bytes de los ficheros bajo ``path`` (lo que libera borrarlo)."""
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _job_folder(root: Path, *, state: str, days: float, label: str, size: int) -> Path:
    """La carpeta de un trabajo de otra sesión (no está en el lanzador): su petición, su
    ``state.json`` (en ``state``; si es final, terminado hace ``days`` días) y ``size``
    bytes de resultados."""
    protocol, paths, records = (_module(f"jobs.{name}")
                                for name in ("protocol", "paths", "records"))
    utc = _module("core.timeutil").format_utc
    request = protocol.new_request("selftest", label=label, owner="jobs",
                                   environment="blender", timeout_s=60)
    folder = paths.job_dir(root, request.job_uid).create()
    protocol.write_request(folder, request)
    ended = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    final = state in records.FINAL_STATES
    records.write_record(folder, records.JobRecord(
        job_uid=request.job_uid, worker="selftest", label=label, owner="jobs", state=state,
        executor="subprocess", queued_at=utc(ended - dt.timedelta(minutes=1)),
        started_at=utc(ended - dt.timedelta(seconds=30)),
        ended_at=utc(ended) if final else None, duration_s=30.0 if final else None,
        exit_code=0 if state == "succeeded" else None,
        error=None if state in ("running", "succeeded") else records.ErrorInfo(
            code="worker_crashed", msgid="Job crashed", text="Falló"),
    ))
    (folder.outputs_dir / "datos.bin").write_bytes(b"\x01" * size)
    return folder.path


type _Reports = list[tuple[set[str], str]]


def _reports(operator: type, **properties: object) -> tuple[set[str], _Reports]:
    """``execute`` del operador con ``properties``, como lo llama Blender, y sus avisos."""
    reports: list[tuple[set[str], str]] = []
    fake = SimpleNamespace(**properties,
                           report=lambda kind, text: reports.append((set(kind), text)))
    return operator.execute(fake, bpy.context), reports


class SelftestCleanCatalogTest(unittest.TestCase):
    """Con la extensión habilitada una vez para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.commands = _module("bl.ui.commands")
        cls.registry = _module("bl.ui.registry")
        cls.ops = _module("bl.ops.jobs")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def test_real_operators_replace_the_provisionals(self) -> None:
        """RF-004-03, RF-004-17: ``geoblender.jobs_run_selftest`` y ``geoblender.jobs_clean``
        son los operadores reales de ``bl/ops/jobs.py`` con el ``bl_idname``, el nombre y
        la descripción del catálogo de la 003, que no genera provisionales para ellos; están
        disponibles y Herramientas ▸ Trabajos los dibuja activos."""
        provisional = set(self.registry.provisional_classes())
        real = _module("bl.ops").classes
        menu = self.commands.registered_class(JOBS_MENU)
        drawn = {item.target: item for item in draw(menu, bpy.context).of_kind("operator")}
        for idname, name in T21_OPERATORS.items():
            with self.subTest(idname=idname):
                cls = self.commands.registered_class(idname)
                self.assertIs(cls, getattr(self.ops, name))
                self.assertIn(cls, real)
                self.assertNotIn(cls, provisional)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertTrue(self.commands.is_available(idname))
                cmd = self.cat.commands[idname]
                self.assertEqual(cmd.label, T21_LABELS[idname])
                self.assertEqual(cls.bl_label, self.commands.text(cmd.label))
                self.assertEqual(cls.bl_description, self.commands.text(cmd.description))
                self.assertEqual(cls.bl_translation_context,
                                 self.commands.TRANSLATION_CONTEXT)
                self.assertTrue(drawn[idname].enabled)

    def test_properties(self) -> None:
        """RF-004-03, RF-004-17: ``mode`` (``SUM_10S`` por defecto, ``MATMUL_COMPUTE``,
        ``MATMUL_BLENDER``) del autodiagnóstico; ``scope`` (``OLD`` por defecto,
        ``FINISHED``, ``ONE``) y ``job_uid`` de la limpieza, los que pone «Descartar» en
        la lista de trabajos; ninguno se guarda para la vez siguiente."""
        mode = bpy.ops.geoblender.jobs_run_selftest.get_rna_type().properties["mode"]
        self.assertEqual([item.identifier for item in mode.enum_items],
                         ["SUM_10S", "MATMUL_COMPUTE", "MATMUL_BLENDER"])
        self.assertEqual(mode.default, "SUM_10S")
        clean = bpy.ops.geoblender.jobs_clean.get_rna_type().properties
        self.assertEqual([item.identifier for item in clean["scope"].enum_items],
                         ["OLD", "FINISHED", "ONE"])
        self.assertEqual(clean["scope"].default, "OLD")
        self.assertEqual(clean["job_uid"].default, "")
        for prop in (mode, clean["scope"], clean["job_uid"]):
            with self.subTest(propiedad=prop.identifier):
                self.assertTrue(prop.is_skip_save)


class RunSelftestTest(unittest.TestCase):
    """Los tres autodiagnósticos con un lanzador real en una carpeta temporal: el de 10 s
    se cancela en cuanto da sus tres primeros trozos; el de 500 × 500 termina en hilo; el
    del motor falla sin él (aún no hay motor de cálculo: fase 4)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.ops = _module("bl.ops.jobs")
        cls.protocol = _module("jobs.protocol")
        cls.records = _module("jobs.records")
        cls.selftest = _module("jobs.selftest")
        cls.worker_api = _module("jobs.worker_api")
        cls.messages = _module("jobs.messages")
        runner = _module("jobs.runner")
        cls.tmp = tempfile.TemporaryDirectory(prefix="gb4-")
        cls.root = Path(cls.tmp.name) / "jobs"
        package_dir = Path(sys.modules[module_name()].__file__).parent
        cls.runner = runner.JobRunner(jobs_root=cls.root, package_dir=package_dir,
                                      blender_python=Path(sys.executable))
        cls.monitor = cls.ops.JobMonitor(clock=_Clock())
        cls.patch = mock.patch.object(cls.ops, "MONITOR", cls.monitor)
        cls.patch.start()
        try:
            cls.poll_without_runner = cls._poll()
            cls.monitor.attach(cls.runner)
            cls.poll_with_runner = cls._poll()
            cls._run_scenario()
        except BaseException:
            cls.tearDownClass()  # unittest no lo llama si setUpClass falla
            raise

    @classmethod
    def _run_scenario(cls) -> None:
        operator = cls.ops.GEOBLENDER_OT_jobs_run_selftest
        started = time.monotonic()
        cls.sum_run = _reports(operator, mode="SUM_10S")
        cls.timer_after_submit = bpy.app.timers.is_registered(cls.ops.tick)
        cls.matmul_run = bpy.ops.geoblender.jobs_run_selftest(mode="MATMUL_BLENDER")
        cls.compute_run = _reports(operator, mode="MATMUL_COMPUTE")
        launched = cls.by_name()
        total = launched[SELFTEST_NAMES["SUM_10S"]]
        matmul = launched[SELFTEST_NAMES["MATMUL_BLENDER"]]
        cls._wait(lambda: _chunk_number(cls.by_name()[total.name].message) >= SAMPLED_CHUNKS
                  and not cls.by_name()[matmul.name].active)
        cls.sampled_s = time.monotonic() - started
        cls.sum_running = cls.by_name()[total.name]
        cls.sum_record = cls.records.read_record(cls.root / total.job_uid)
        cls.runner.cancel(total.job_uid)
        cls._wait(lambda: not cls.by_name()[total.name].active)
        cls.sum_events = _channel_events(cls.root / total.job_uid)

    @classmethod
    def by_name(cls) -> dict[str, object]:
        return {s.name: s for s in cls.runner.snapshots()}

    @classmethod
    def _wait(cls, condition: object) -> None:
        deadline = time.monotonic() + WAIT_S
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError("los autodiagnósticos no avanzaron a tiempo")
            cls.ops.tick()
            time.sleep(GATE_POLL_S)

    @classmethod
    def _poll(cls) -> tuple[bool, list[str]]:
        operator = cls.ops.GEOBLENDER_OT_jobs_run_selftest
        with mock.patch.object(operator, "poll_message_set") as message:
            allowed = operator.poll(bpy.context)
        return allowed, [call.args[0] for call in message.call_args_list]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.runner.shutdown(timeout_s=2.0)
        cls.monitor.stop()
        cls.patch.stop()
        blender_ext.unload()
        cls.tmp.cleanup()

    def request(self, mode: str) -> object:
        job_uid = self.by_name()[SELFTEST_NAMES[mode]].job_uid
        return self.protocol.read_request(self.root / job_uid)

    def test_poll_needs_the_runner(self) -> None:
        """RF-004-03: sin lanzador (Geoblender aún no tiene la carpeta de los trabajos) el
        ``poll`` falla y lo explica; con él, se puede; con el lanzador cerrado, tampoco."""
        self.assertEqual(self.poll_without_runner, (False, [NO_RUNNER]))
        self.assertEqual(self.poll_with_runner, (True, []))
        closed = SimpleNamespace(closed=True)
        with mock.patch.object(self.ops, "MONITOR", self.ops.JobMonitor()):
            self.ops.MONITOR.attach(closed)
            self.assertEqual(self._poll(), (False, [NO_RUNNER]))

    def test_sum_of_ten_seconds_in_a_separate_process(self) -> None:
        """RF-004-03, RF-004-06: ``SUM_10S`` lanza con el monitor un autodiagnóstico de
        10 ± 0,5 s (50 trozos de 0,2 s; el estimador da 10 s, más de 5 s) que va en proceso
        aparte, con un evento de avance cada ≤ 0,25 s (M1 y H2 piden al menos dos por
        segundo): trozos de ≤ 0,25 s, uno por avance, que el límite de 10 avances por
        segundo del worker no retiene. En su proceso, el inicio y los tres primeros avances
        llegan con ≤ 0,25 s entre uno y otro, y a ese ritmo los 50 trozos duran 10 ± 0,5 s;
        se cancela al momento."""
        result, reports = self.sum_run
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(reports, [({"INFO"},
                                    f"Lanzado el trabajo «{SELFTEST_NAMES['SUM_10S']}»")])
        self.assertTrue(self.timer_after_submit)
        request = self.request("SUM_10S")
        self.assertEqual((request.worker, request.owner, request.environment),
                         ("selftest", "jobs", "blender"))
        self.assertEqual(dict(request.params), dict(self.ops.SELFTEST_PARAMS["SUM_10S"]))
        self.assertEqual(dict(request.params),
                         {"op": "chunked_sum", "n": 20_000, "chunks": 50, "sleep_s": 0.2})
        p = self.selftest.SelftestParams.from_params(request.params, job="SUM_10S")
        chunk_s = p.sleep_s + p.n / p.chunks / self.selftest.SUM_RATE_PER_S
        self.assertLessEqual(chunk_s, PROGRESS_EVERY_S)
        self.assertGreater(chunk_s, self.worker_api.PROGRESS_INTERVAL_S)
        self.assertAlmostEqual(self.selftest.estimate_s(request.params), p.chunks * chunk_s)
        self.assertAlmostEqual(p.chunks * chunk_s, SUM_10S_S, delta=SUM_10S_TOLERANCE_S)
        running = self.sum_running
        self.assertEqual((running.state, running.executor), ("running", "subprocess"))
        self.assertIsNotNone(self.sum_record.pid)
        self.assertGreaterEqual(self.sampled_s, SAMPLED_CHUNKS * p.sleep_s)
        start = next(event for event in self.sum_events if event["t"] == "start")
        self.assertEqual(start["info"]["pid"], self.sum_record.pid)
        progress = [event for event in self.sum_events
                    if event["t"] == "progress"][:SAMPLED_CHUNKS]
        self.assertEqual([event["msg"] for event in progress],
                         [f"Trozo {k} de {p.chunks}" for k in range(1, SAMPLED_CHUNKS + 1)])
        times = [start["ts"], *(event["ts"] for event in progress)]
        intervals = [later - earlier for earlier, later in zip(times, times[1:])]
        self.assertLessEqual(max(intervals), PROGRESS_EVERY_S, intervals)
        self.assertAlmostEqual(statistics.median(intervals) * p.chunks, SUM_10S_S,
                               delta=SUM_10S_TOLERANCE_S, msg=intervals)
        cancelled = self.by_name()[SELFTEST_NAMES["SUM_10S"]]
        self.assertEqual(cancelled.state, "cancelled")
        self.assertLess(cancelled.duration_s, 5.0)

    def test_matmul_with_blender_numpy_in_a_thread(self) -> None:
        """RF-004-03: ``MATMUL_BLENDER`` es el producto 500 × 500 con el numpy de Blender,
        estimado en menos de 5 s: va en hilo (sin proceso) y termina con su resultado."""
        self.assertEqual(self.matmul_run, {"FINISHED"})
        request = self.request("MATMUL_BLENDER")
        self.assertEqual(dict(request.params), {"op": "matmul", "n": 500})
        self.assertEqual(request.environment, "blender")
        self.assertLess(self.selftest.estimate_s(request.params), 5.0)
        snapshot = self.by_name()[SELFTEST_NAMES["MATMUL_BLENDER"]]
        self.assertEqual((snapshot.state, snapshot.executor), ("succeeded", "inprocess"))
        self.assertEqual(snapshot.interpreter.kind, "blender")
        record = self.records.read_record(self.root / snapshot.job_uid)
        self.assertIsNone(record.pid)
        summary = json.loads((self.root / snapshot.job_uid / "result.json")
                             .read_text(encoding="utf-8"))["summary"]
        self.assertEqual((summary["op"], summary["n"]), ("matmul", 500))
        self.assertGreater(summary["gflops"], 0.0)

    def test_matmul_with_the_compute_engine_needs_it(self) -> None:
        """RF-004-03: ``MATMUL_COMPUTE`` (2000 × 2000) necesita el motor de cálculo: va a
        proceso aparte y, sin motor, queda «Fallido» (``runtime_missing``) sin arrancar
        ningún proceso; el operador lo dice con el mensaje del §8."""
        result, reports = self.compute_run
        self.assertEqual(result, {"CANCELLED"})
        self.assertEqual(reports, [({"ERROR"}, self.messages.render("runtime_missing"))])
        request = self.request("MATMUL_COMPUTE")
        self.assertEqual(dict(request.params), {"op": "matmul", "n": 2000})
        self.assertEqual(request.environment, "compute")
        snapshot = self.by_name()[SELFTEST_NAMES["MATMUL_COMPUTE"]]
        self.assertEqual((snapshot.state, snapshot.executor), ("failed", "subprocess"))
        self.assertEqual(snapshot.error.code, "runtime_missing")
        self.assertIsNone(self.records.read_record(self.root / snapshot.job_uid).pid)


class CleanJobsTest(unittest.TestCase):
    """``geoblender.jobs_clean`` sobre una raíz con trabajos de otra sesión (8, 10 y 1 días
    terminados, y uno que consta en curso) y dos del lanzador en hilo: uno terminado y otro
    en curso."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.ops = _module("bl.ops.jobs")
        cls.ui = _module("bl.ui.jobs")
        cls.catalog = _module("jobs.catalog")
        cls.protocol = _module("jobs.protocol")
        cls.i18n = _module("core.i18n")
        cls.runner_mod = _module("jobs.runner")
        cls.prefs = _addon_preferences().jobs
        cls.gates = _Gates()
        cls.catalog.register_worker(cls.catalog.WorkerInfo(
            CLEAN_WORKER, "Clean test job", policy="auto",
            estimate_s=lambda _params: 0.1, run=cls.gates.run,
        ))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.gates.release_all()
        cls.catalog.unregister_worker(CLEAN_WORKER)
        blender_ext.unload()

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="gb4-")))
        package_dir = Path(sys.modules[module_name()].__file__).parent
        self.runner = self.runner_mod.JobRunner(jobs_root=self.root, package_dir=package_dir,
                                                blender_python=Path(sys.executable))
        self.monitor = self.ops.JobMonitor(clock=_Clock())
        patch = mock.patch.object(self.ops, "MONITOR", self.monitor)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.monitor.stop)
        self.addCleanup(self.runner.shutdown, timeout_s=2.0)
        self.addCleanup(self.gates.release_all)
        self.monitor.attach(self.runner)
        self.gates.events.clear()  # las de la prueba anterior ya están soltadas
        self.old = _job_folder(self.root, state="succeeded", days=8, label="Viejo",
                               size=300 * KB)
        self.older = _job_folder(self.root, state="failed", days=10, label="Más viejo",
                                 size=200 * KB)
        self.recent = _job_folder(self.root, state="succeeded", days=1, label="Reciente",
                                  size=100 * KB)
        self.orphan = _job_folder(self.root, state="running", days=30, label="Huérfano",
                                  size=50 * KB)
        self.gates["Hecho"].set()
        self.done = self.monitor.submit(self.protocol.new_request(
            CLEAN_WORKER, label="Hecho", owner="jobs"))
        self.busy = self.monitor.submit(self.protocol.new_request(
            CLEAN_WORKER, label="En marcha", owner="jobs"))
        deadline = time.monotonic() + WAIT_S
        while self.done.result() is None or self.busy.message != "Esperando":
            self.assertLess(time.monotonic(), deadline, "los trabajos no avanzaron a tiempo")
            self.ops.tick()
            time.sleep(GATE_POLL_S)
        self.assertEqual((self.done.state, self.busy.state), ("succeeded", "running"))
        self.addCleanup(setattr, self.prefs, "retention_days", self.prefs.retention_days)

    def clean(self, **properties: object) -> tuple[set[str], _Reports]:
        properties.setdefault("scope", "OLD")
        properties.setdefault("job_uid", "")
        return _reports(self.ops.GEOBLENDER_OT_jobs_clean, **properties)

    def freed(self, *folders: Path) -> str:
        return self.i18n.format_number(sum(_bytes(f) for f in folders) / 1e6, 1)

    def remaining(self) -> set[str]:
        return {path.name for path in self.root.iterdir()}

    def listed(self) -> set[str]:
        return {snapshot.name for snapshot in self.runner.snapshots()}

    def test_poll_needs_the_runner(self) -> None:
        """RF-004-17: sin lanzador no hay carpeta de trabajos que limpiar: el ``poll`` falla
        y lo explica."""
        operator = self.ops.GEOBLENDER_OT_jobs_clean
        self.assertTrue(operator.poll(bpy.context))
        self.monitor.attach(None)
        with mock.patch.object(operator, "poll_message_set") as message:
            self.assertFalse(operator.poll(bpy.context))
        message.assert_called_once_with(NO_RUNNER)

    def test_old_uses_the_retention_of_the_preferences(self) -> None:
        """RF-004-17: ``OLD`` borra los terminados hace más días que ``retention_days`` de
        las preferencias (9: solo el de 10 días; 7: también el de 8) e informa de los MB
        liberados; nunca los recientes ni los activos."""
        self.prefs.retention_days = 9
        expected = self.freed(self.older)
        self.assertEqual(self.clean(scope="OLD"), ({"FINISHED"}, [(
            {"INFO"}, f"Carpetas de trabajos borradas: 1 ({expected} MB liberados)")]))
        self.prefs.retention_days = 7
        expected = self.freed(self.old)
        self.assertEqual(self.clean(scope="OLD"), ({"FINISHED"}, [(
            {"INFO"}, f"Carpetas de trabajos borradas: 1 ({expected} MB liberados)")]))
        self.assertEqual(self.remaining(), {self.recent.name, self.orphan.name,
                                            self.done.job_uid, self.busy.job_uid})
        self.assertEqual(self.listed(), {"Hecho", "En marcha"})

    def test_finished_removes_every_finished_job(self) -> None:
        """RF-004-17: ``FINISHED`` borra todos los terminados, recientes y del lanzador
        incluidos (que salen de la lista), informa de los MB liberados y nunca borra los
        activos: ni el que corre en el lanzador ni el que su registro deja en curso; otra
        vez, no hay nada que borrar."""
        expected = self.freed(self.old, self.older, self.recent, self.done.job_dir.path)
        self.assertEqual(self.clean(scope="FINISHED"), ({"FINISHED"}, [(
            {"INFO"}, f"Carpetas de trabajos borradas: 4 ({expected} MB liberados)")]))
        self.assertEqual(self.remaining(), {self.orphan.name, self.busy.job_uid})
        self.assertEqual(self.listed(), {"En marcha"})
        self.assertEqual(self.busy.state, "running")
        self.assertEqual(self.clean(scope="FINISHED"), ({"FINISHED"}, [(
            {"INFO"}, "No había trabajos terminados que borrar")]))

    def test_discard_one_job(self) -> None:
        """RF-004-08, RF-004-17: ``ONE`` (el «Descartar» de la lista, que lo ejecuta sin
        diálogo) borra solo ese trabajo terminado, que sale de la lista, y dice los MB
        liberados; uno en curso, uno que no existe o ninguno solo avisan y no borran
        nada."""
        expected = self.freed(self.done.job_dir.path)
        self.assertEqual(self.clean(scope="ONE", job_uid=self.done.job_uid), (
            {"FINISHED"},
            [({"INFO"}, f"Descartado el trabajo «Hecho» ({expected} MB liberados)")]))
        self.assertEqual(self.listed(), {"En marcha"})
        self.assertEqual(self.clean(scope="ONE", job_uid=self.busy.job_uid), (
            {"CANCELLED"},
            [({"WARNING"}, "El trabajo «En marcha» sigue en marcha: no se puede descartar")]))
        self.assertEqual(self.clean(scope="ONE", job_uid="gbtest-desconocido"),
                         ({"CANCELLED"}, [({"WARNING"},
                                           "No hay ningún trabajo «gbtest-desconocido»")]))
        self.assertEqual(self.clean(scope="ONE"), ({"CANCELLED"}, [(
            {"ERROR"}, "No se ha indicado qué trabajo descartar")]))
        self.assertEqual(self.remaining(), {self.old.name, self.older.name,
                                            self.recent.name, self.orphan.name,
                                            self.busy.job_uid})
        with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
            self.assertEqual(bpy.ops.geoblender.jobs_clean(
                "INVOKE_DEFAULT", scope="ONE", job_uid=self.old.name), {"FINISHED"})
        self.assertNotIn(self.old.name, self.remaining())

    def test_menu_opens_a_dialog(self) -> None:
        """RF-004-17: desde el menú (``OLD`` o ``FINISHED``) pide confirmación en un
        diálogo con los días de las preferencias y que nunca se borran los activos, sin
        borrar nada todavía."""
        self.prefs.retention_days = 12
        operator = self.ops.GEOBLENDER_OT_jobs_clean
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        manager = SimpleNamespace(invoke_props_dialog=dialog)
        context = SimpleNamespace(window_manager=manager)
        for scope in ("OLD", "FINISHED"):
            with self.subTest(scope=scope):
                dialog.reset_mock()
                fake = SimpleNamespace(scope=scope, job_uid="")
                self.assertEqual(operator.invoke(fake, context, None), {"RUNNING_MODAL"})
                self.assertIs(dialog.call_args.args[0], fake)
                self.assertEqual(dialog.call_args.kwargs["title"],
                                 "Limpiar trabajos terminados")
        texts = draw(operator, bpy.context, scope="OLD", job_uid="").texts()
        self.assertEqual(texts, ["Terminados hace más de 12 días", "Todos los terminados",
                                 "Nunca se borran los trabajos en cola ni en curso"])
        self.assertEqual(len(self.remaining()), 6)


# --- T22: el lanzador de la sesión, su raíz de trabajos y el cierre ---------------------

SESSION_WORKER = "gbtest_session"
SHUTDOWN_BUDGET_S = 3.0
PROJECT_WINDOW = (699_500.4, 4_399_500.6, 700_500.2, 4_400_500.9)
NO_PROJECT_JOBS = ("cache", "_sin_proyecto", "jobs")


def _user_dir() -> Path:
    """Los datos de usuario de la copia de pruebas, como los da Blender (no los crea)."""
    return Path(bpy.utils.extension_path_user(module_name()))


def _remove_tree(path: Path) -> None:
    """Borra ``path`` entera, también las entradas de solo lectura de los trabajos."""
    def writable(function: object, name: str, _exc: BaseException) -> None:
        os.chmod(name, stat.S_IWRITE)
        function(name)

    if path.exists():
        shutil.rmtree(path, onexc=writable)


def _wait_jobs(ops: ModuleType, condition: object) -> None:
    """Sondea con ``tick()`` a mano hasta que se cumple ``condition``."""
    deadline = time.monotonic() + WAIT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("los trabajos de prueba no avanzaron a tiempo")
        ops.tick()
        time.sleep(GATE_POLL_S)


class SessionRunnerTest(unittest.TestCase):
    """El lanzador que crea el registro, con la extensión habilitada una vez desde el
    repositorio de pruebas (``bl_ext.gb_tests.…``) y la escena de fábrica."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        cls.user = _user_dir()
        cls.no_project_root = cls.user.joinpath(*NO_PROJECT_JOBS)
        cls.root_existed = cls.no_project_root.exists()
        cls.runtime_existed = (cls.user / "runtime").exists()
        blender_ext.enable()
        cls.ops = _module("bl.ops.jobs")
        cls.ps = _module("bl.scene.project_session")
        cls.catalog = _module("jobs.catalog")
        cls.protocol = _module("jobs.protocol")
        cls.records = _module("jobs.records")
        cls.messages = _module("jobs.messages")
        cls.core = _module("core.project")
        cls.model = _module("core.project.model")
        cls.after_enable = (cls.no_project_root.exists(), (cls.user / "runtime").exists())
        cls.runner = cls.ops.MONITOR.runner
        cls.gates = _Gates()
        cls.catalog.register_worker(cls.catalog.WorkerInfo(
            SESSION_WORKER, "Session test job", policy="auto",
            estimate_s=lambda _params: 0.1, run=cls.gates.run,
        ))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.gates.release_all()
        blender_ext.unload()
        blender_ext.load_file()
        if not cls.root_existed:
            _remove_tree(cls.no_project_root)

    def setUp(self) -> None:
        self.gates.events.clear()
        self.addCleanup(self.gates.release_all)

    def project(self, *, read_only: bool = False) -> object:
        """Un proyecto nuevo en una carpeta temporal, abierto en escritura (o pasado a
        solo lectura) y aún sin dar a la sesión."""
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix="gb4-", ignore_cleanup_errors=True)))
        settings = self.model.ProjectSettings(name="Cantera Trabajos", window=PROJECT_WINDOW,
                                              crs_epsg=25830, vcrs_epsg=5782)
        created = self.core.create_project(tmp, settings, self.ps.session(),
                                           self.ps.userdata())
        project = created.project
        self.addCleanup(self.ps.close)
        if read_only:
            project.set_read_only(self.model.ReadOnlyCode.REQUESTED, "prueba")
        return project

    def test_roots_from_the_test_repository(self) -> None:
        """RF-004-18, RF-004-19: con la extensión habilitada desde ``gb_tests``, el lanzador
        de la sesión existe, abierto, con la raíz sin proyecto de sus datos de usuario
        (``cache/_sin_proyecto/jobs``), sin rutas prohibidas y con el máximo de las
        preferencias; la carpeta del motor (``runtime/``) se resuelve también ahí, y
        habilitar no crea ninguna de las dos."""
        self.assertTrue(module_name().startswith("bl_ext.gb_tests."))
        self.assertEqual(self.ops.user_dir(), self.user)
        self.assertEqual(self.ops.jobs_root(None), self.no_project_root)
        self.assertEqual(self.ops.runtime_dir(), self.user / "runtime")
        runner = self.ops.MONITOR.runner
        self.assertIs(runner, self.ops.session_runner())
        self.assertIsInstance(runner, _module("jobs.runner").JobRunner)
        self.assertFalse(runner.closed)
        self.assertEqual(runner.jobs_root, self.no_project_root)
        self.assertEqual(runner.forbidden_roots, ())
        self.assertEqual(runner.max_subprocess,
                         _addon_preferences().jobs.max_parallel_jobs)
        self.assertEqual(self.after_enable, (self.root_existed, self.runtime_existed))
        self.assertFalse(self.runtime_existed)

    def test_sys_path_unchanged_by_jobs(self) -> None:
        """RF-004-03, RF-004-25: el ``sys.path`` de Blender es idéntico antes y después de
        un trabajo del motor de cálculo (que sin motor queda «Fallido» sin arrancar) y de
        uno en hilo con el numpy de Blender, los dos del lanzador de la sesión."""
        before = list(sys.path)
        operator = self.ops.GEOBLENDER_OT_jobs_run_selftest
        compute, _messages = _reports(operator, mode="MATMUL_COMPUTE")
        threaded = bpy.ops.geoblender.jobs_run_selftest(mode="MATMUL_BLENDER")
        by_name = {s.name: s for s in self.runner.snapshots()}
        matmul = by_name[SELFTEST_NAMES["MATMUL_BLENDER"]]
        _wait_jobs(self.ops, lambda: not {s.job_uid: s for s in self.runner.snapshots()}[
            matmul.job_uid].active)
        self.assertEqual(list(sys.path), before)
        self.assertEqual((compute, threaded), ({"CANCELLED"}, {"FINISHED"}))
        failed = self.records.read_record(
            self.no_project_root / by_name[SELFTEST_NAMES["MATMUL_COMPUTE"]].job_uid)
        self.assertEqual((failed.state, failed.error.code, failed.pid),
                         ("failed", "runtime_missing", None))
        done = self.records.read_record(self.no_project_root / matmul.job_uid)
        self.assertEqual((done.state, done.executor), ("succeeded", "inprocess"))

    def test_max_parallel_preference_reconfigures(self) -> None:
        """RF-004-04: cambiar ``max_parallel_jobs`` en las preferencias cambia al momento el
        máximo de trabajos en proceso aparte del lanzador de la sesión."""
        prefs = _addon_preferences().jobs
        self.addCleanup(setattr, prefs, "max_parallel_jobs", prefs.max_parallel_jobs)
        for value in (3, 1, 4, 2):
            with self.subTest(max_parallel_jobs=value):
                prefs.max_parallel_jobs = value
                self.assertEqual(self.runner.max_subprocess, value)

    def test_opening_a_project_moves_marks_and_purges(self) -> None:
        """RF-004-18, RF-004-13, RF-004-17, RF-004-02: dar a la sesión un proyecto en disco
        local y en escritura lleva la raíz a ``Project.cache_dir()/jobs`` (dentro del
        proyecto) y prohíbe su ruta en las peticiones; de los trabajos que ya estaban ahí,
        el que su registro deja en curso queda «Interrumpido» y se borra el terminado hace
        más de ``retention_days`` días, no el reciente. Volver a abrirlo con un trabajo del
        lanzador en marcha no lo interrumpe; al cerrar el proyecto, la raíz vuelve a la de
        sin proyecto y no queda ninguna ruta prohibida."""
        project = self.project()
        root = project.root / "cache" / "jobs"
        self.assertEqual(project.cache_dir() / "jobs", root)
        orphan = _job_folder(root, state="running", days=0.01, label="Huérfano", size=KB)
        old = _job_folder(root, state="succeeded", days=10, label="Viejo", size=KB)
        recent = _job_folder(root, state="failed", days=1, label="Reciente", size=KB)
        self.ps.attach(project)
        self.assertEqual(self.runner.jobs_root, root)
        self.assertEqual(self.runner.forbidden_roots, (project.root,))
        marked = self.records.read_record(orphan)
        self.assertEqual((marked.state, marked.error.code), ("interrupted", "job_interrupted"))
        self.assertFalse(old.exists())
        self.assertEqual(self.records.read_record(recent).state, "failed")
        with self.assertRaises(self.messages.JobError) as caught:
            self.runner.prepare(self.protocol.new_request(
                "selftest", label="Ruta", owner="jobs",
                params={"nota": str(project.root / "project.gpkg")}))
        self.assertEqual(caught.exception.code, "request_path_outside_job")
        busy = self.ops.MONITOR.submit(self.protocol.new_request(
            SESSION_WORKER, label="En marcha", owner="jobs"))
        _wait_jobs(self.ops, lambda: busy.message == "Esperando")
        self.assertEqual(busy.job_dir.path.parent, root)
        self.ops.on_project_changed(project)  # el mismo proyecto, otra vez
        self.assertEqual(self.records.read_record(busy.job_dir).state, "running")
        self.assertEqual(busy.state, "running")
        self.ps.close()
        self.assertEqual(self.runner.jobs_root, self.no_project_root)
        self.assertEqual(self.runner.forbidden_roots, ())
        self.gates.release_all()
        _wait_jobs(self.ops, lambda: busy.result() is not None)
        self.assertEqual(busy.result().state, "succeeded")

    def test_read_only_project_keeps_jobs_in_user_data(self) -> None:
        """RF-004-18: con el proyecto en solo lectura, la raíz de trabajos es la caché del
        proyecto en los datos de usuario (``cache/<uid>/jobs``), fuera de la carpeta del
        proyecto, en la que no se crea nada."""
        project = self.project(read_only=True)
        self.ps.attach(project)
        expected = self.ps.userdata().cache_dir(project.uid) / "jobs"
        self.assertEqual(self.runner.jobs_root, expected)
        self.assertTrue(expected.is_relative_to(self.user))
        self.assertFalse(expected.is_relative_to(project.root))
        self.assertFalse((project.root / "cache").exists())


class SessionShutdownTest(unittest.TestCase):
    """Cada prueba habilita la extensión, lanza con el lanzador de la sesión el
    autodiagnóstico de 10 s (proceso aparte) y un trabajo en hilo que espera, y cierra."""

    def setUp(self) -> None:
        blender_ext.unload()
        self.folders: list[Path] = []
        self.addCleanup(self.remove_folders)  # lo último: con todo ya cerrado
        self.addCleanup(blender_ext.unload)
        self.sys_path = list(sys.path)
        blender_ext.enable()
        self.ops = _module("bl.ops.jobs")
        self.ps = _module("bl.scene.project_session")
        self.ui = _module("bl.ui.jobs")
        self.statusbar = _module("bl.ui.statusbar")
        self.records = _module("jobs.records")
        self.sysinfo = _module("core.sysinfo")
        catalog = _module("jobs.catalog")
        protocol = _module("jobs.protocol")
        self.gates = _Gates()
        self.addCleanup(self.gates.release_all)
        catalog.register_worker(catalog.WorkerInfo(
            SESSION_WORKER, "Session test job", policy="auto",
            estimate_s=lambda _params: 0.1, run=self.gates.run,
        ))
        self.addCleanup(catalog.unregister_worker, SESSION_WORKER)
        self.runner = self.ops.MONITOR.runner
        self.assertEqual(bpy.ops.geoblender.jobs_run_selftest(mode="SUM_10S"), {"FINISHED"})
        self.waiting = self.ops.MONITOR.submit(protocol.new_request(
            SESSION_WORKER, label="Esperando el cierre", owner="jobs"))
        total = {s.name: s for s in self.runner.snapshots()}[SELFTEST_NAMES["SUM_10S"]]
        self.folders = [self.runner.jobs_root / total.job_uid, self.waiting.job_dir.path]
        _wait_jobs(self.ops, lambda: self.snapshot(total.job_uid).interpreter is not None
                   and self.waiting.message == "Esperando")
        self.pid = self.records.read_record(self.folders[0]).pid
        self.assertTrue(self.sysinfo.pid_alive(self.pid))

    def remove_folders(self) -> None:
        for folder in self.folders:
            _remove_tree(folder)

    def snapshot(self, job_uid: str) -> object:
        return {s.job_uid: s for s in self.runner.snapshots()}[job_uid]

    def assertInterruptedWithoutProcess(self, elapsed_s: float) -> None:
        self.assertLessEqual(elapsed_s, SHUTDOWN_BUDGET_S)
        self.assertFalse(self.sysinfo.pid_alive(self.pid))
        for folder in self.folders:
            record = self.records.read_record(folder)
            with self.subTest(trabajo=record.label):
                self.assertEqual((record.state, record.error.code),
                                 ("interrupted", "job_interrupted"))
        self.assertTrue(self.runner.closed)
        self.assertFalse(bpy.app.timers.is_registered(self.ops.tick))

    def test_disable_interrupts_running_jobs(self) -> None:
        """RF-004-13: desactivar Geoblender con un trabajo en curso en proceso aparte y
        otro en hilo los deja «Interrumpido» en su registro y sin proceso en ≤ 3 s; quedan
        retirados el temporizador, el campo de la barra de estado, el manejador
        ``exit_pre`` y el aviso de cambio de proyecto (huella del principio de la sesión),
        y el ``sys.path`` de Blender sigue igual."""
        started = time.monotonic()
        blender_ext.disable()
        self.assertInterruptedWithoutProcess(time.monotonic() - started)
        self.assertIsNone(self.ops.MONITOR.runner)
        self.assertIsNone(self.ops.session_runner())
        self.assertNotIn(FIELD, [field.key for field in self.statusbar.fields()])
        self.assertNotIn(self.ops.on_exit_pre, bpy.app.handlers.exit_pre)
        self.assertNotIn(self.ops.on_project_changed, self.ps.listeners())
        self.assertEqual(list(sys.path), self.sys_path)
        after = state_fingerprint()
        before = blender_ext.session_baseline()
        if after != before:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(before, after)))

    def test_exit_pre_closes_the_runner(self) -> None:
        """RF-004-13: el manejador ``exit_pre`` (persistente, para que siga tras abrir otro
        ``.blend``) cierra el lanzador al salir de Blender: los trabajos en curso quedan
        «Interrumpido» y sin proceso en ≤ 3 s; desactivar después no hace nada más."""
        handler = self.ops.on_exit_pre
        self.assertIn(handler, bpy.app.handlers.exit_pre)
        self.assertTrue(hasattr(handler, "_bpy_persistent"))  # lo pone @persistent
        started = time.monotonic()
        handler(None)
        self.assertInterruptedWithoutProcess(time.monotonic() - started)
        blender_ext.disable()
        self.assertNotIn(handler, bpy.app.handlers.exit_pre)


if __name__ == "__main__":
    unittest.main()
