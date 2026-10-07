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

Se ejecuta con ``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import importlib
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
