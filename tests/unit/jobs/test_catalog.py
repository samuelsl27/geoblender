# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de tipos de trabajo (spec 004, T06; RF-004-03; plan 004 §5.3.1 y §6).

- RF-004-03: cada tipo de trabajo declara su política (``subprocess`` o ``auto``: ninguna
  fuerza el hilo), su entorno (``blender``, ``compute`` o una función de los parámetros), su
  tiempo máximo, su estimador de duración y la función de dominio que lo ejecuta en hilo
  (``run``). Un ``WorkerInfo`` que no cumple no se crea.
- ``register_worker`` / ``unregister_worker``: cada módulo registra los suyos desde ``bl/``
  (``jobs/`` no importa el dominio); registrar dos veces el mismo nombre falla y deja el
  primero; ``WORKERS`` es una vista de solo lectura que sigue los registros.
- Los de la 004: ``selftest``, ``runtime_install``, ``runtime_check`` y ``probe_python``, con
  su estimador, su entorno y su nombre visible traducido al español.
"""

import dataclasses
import datetime as dt
import math
import re
import threading
import unittest
from unittest import mock

from tests.support.package import import_geoblender

catalog = import_geoblender("jobs.catalog")
protocol = import_geoblender("jobs.protocol")
messages = import_geoblender("jobs.messages")
selftest = import_geoblender("jobs.selftest")

WorkerInfo = catalog.WorkerInfo
NOW = dt.datetime(2026, 10, 7, 9, 0, 0, tzinfo=dt.UTC)
BUILTIN_NAMES = {"selftest", "runtime_install", "runtime_check", "probe_python"}
SPANISH_LETTERS = re.compile(r"[áéíóúüñÁÉÍÓÚÜÑ¿¡]")


def _run(ctx):
    return {}


def _info(name="gbtest_job", **changes):
    """Un tipo de trabajo válido que cabría en el hilo, con ``changes`` aplicados."""
    values = {
        "policy": "auto",
        "environment": "blender",
        "default_timeout_s": 60,
        "estimate_s": lambda params: 1.0,
        "run": _run,
    }
    values.update(changes)
    return WorkerInfo(name, "Test job", **values)


def _empty_registry():
    """El registro vacío durante la prueba; al salir, como estaba."""
    return mock.patch.dict(catalog._REGISTRY, clear=True)


class WorkerInfoTest(unittest.TestCase):
    """``WorkerInfo``: lo que declara un tipo de trabajo, comprobado al crearlo."""

    def test_valid_info_keeps_what_it_declares(self):
        """RF-004-03: nombre, nombre visible (``msgid``), política, entorno, tiempo máximo
        (en s, como decimal), estimador y función ``run``."""
        estimate = lambda params: 2.5  # noqa: E731
        info = WorkerInfo("gbtest_job", "Test job", policy="subprocess", environment="compute",
                          default_timeout_s=120, estimate_s=estimate, run=_run)
        self.assertEqual(info.name, "gbtest_job")
        self.assertEqual(info.label_msgid, "Test job")
        self.assertEqual(info.policy, "subprocess")
        self.assertEqual(info.environment, "compute")
        self.assertEqual(info.default_timeout_s, 120.0)
        self.assertIsInstance(info.default_timeout_s, float)
        self.assertIs(info.estimate_s, estimate)
        self.assertIs(info.run, _run)

    def test_defaults_never_choose_the_thread(self):
        """RF-004-03, RF-004-11: sin declarar nada, política ``auto``, entorno ``blender``,
        3600 s de tiempo máximo, sin estimador y sin ``run`` (irá siempre a subproceso)."""
        info = WorkerInfo("gbtest_job", "Test job")
        self.assertEqual(info.policy, "auto")
        self.assertEqual(info.environment, "blender")
        self.assertEqual(info.default_timeout_s, protocol.DEFAULT_TIMEOUT_S)
        self.assertEqual(info.default_timeout_s, 3600.0)
        self.assertIsNone(info.estimate_s)
        self.assertIsNone(info.run)

    def test_policies_are_subprocess_and_auto_only(self):
        """RF-004-03: solo ``subprocess`` y ``auto``; ninguna política fuerza el hilo, así que
        ``inprocess``, ``thread``… no se admiten."""
        self.assertEqual(catalog.POLICIES, ("subprocess", "auto"))
        for policy in ("inprocess", "thread", "hilo", "Auto", "SUBPROCESS", "", None, 1):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                _info(policy=policy)

    def test_name_is_a_worker_module_name(self):
        """Plan 004 §5.2.2: ``<código>_<acción>`` en minúsculas, igual al módulo de
        ``workers/``: nada de mayúsculas, guiones, puntos, barras ni espacios."""
        for name in ("Selftest", "self-test", "jobs.selftest", "a/b", "a b", "1job", "_x",
                     "", "ñu", None, 3):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _info(name=name)

    def test_label_msgid_is_required(self):
        """El nombre visible es un ``msgid`` (texto no vacío)."""
        for label in ("", "   ", None, 3):
            with self.subTest(label=label), self.assertRaises(ValueError):
                WorkerInfo("gbtest_job", label)

    def test_environment_is_blender_compute_or_a_function(self):
        """El entorno es ``blender``, ``compute`` o una función de los parámetros."""
        self.assertEqual(_info(environment="compute").environment, "compute")
        rule = lambda params: "compute"  # noqa: E731
        self.assertIs(_info(environment=rule).environment, rule)
        for environment in ("external", "Blender", "", None, 1):
            with self.subTest(environment=environment), self.assertRaises(ValueError):
                _info(environment=environment)

    def test_default_timeout_within_limits(self):
        """RF-004-11 (spec §8): el tiempo máximo del tipo, en (0, 86 400] s."""
        self.assertEqual(_info(default_timeout_s=86_400).default_timeout_s, 86_400.0)
        self.assertEqual(_info(default_timeout_s=0.5).default_timeout_s, 0.5)
        for seconds in (0, -1, 86_400.5, math.nan, math.inf, True, "60", None):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                _info(default_timeout_s=seconds)

    def test_estimator_and_run_are_callables(self):
        """El estimador y ``run`` son funciones (o nada)."""
        self.assertIsNone(_info(estimate_s=None).estimate_s)
        self.assertIsNone(_info(run=None).run)
        for field in ("estimate_s", "run"):
            for value in (5.0, "selftest.run", object()):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    _info(**{field: value})

    def test_info_is_immutable(self):
        """Lo registrado no se cambia después."""
        info = _info()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            info.policy = "subprocess"

    def test_environment_for_params(self):
        """RF-004-03: el entorno que exige el tipo para unos parámetros; una función que
        devuelve otra cosa es un error del programa."""
        self.assertEqual(_info().environment_for({}), "blender")
        self.assertEqual(_info(environment="compute").environment_for({}), "compute")
        rule = lambda params: "compute" if params.get("n", 0) > 10 else "blender"  # noqa: E731
        info = _info(environment=rule)
        self.assertEqual(info.environment_for({"n": 11}), "compute")
        self.assertEqual(info.environment_for({"n": 10}), "blender")
        with self.assertRaises(ValueError):
            _info(environment=lambda params: "external").environment_for({})


class RegistryTest(unittest.TestCase):
    """``register_worker``, ``unregister_worker`` y ``WORKERS``."""

    def setUp(self):
        patcher = _empty_registry()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_registered_worker_is_in_workers(self):
        """RF-004-03: lo registrado está en ``WORKERS`` con su nombre."""
        info = _info()
        catalog.register_worker(info)
        self.assertIs(catalog.WORKERS["gbtest_job"], info)
        self.assertEqual(list(catalog.WORKERS), ["gbtest_job"])

    def test_registering_the_same_name_twice_fails(self):
        """Registrar dos veces el mismo nombre falla (también con otro ``WorkerInfo``) y
        deja el primero."""
        first = _info()
        catalog.register_worker(first)
        for again in (first, _info(policy="subprocess")):
            with self.subTest(again=again), self.assertRaises(ValueError) as caught:
                catalog.register_worker(again)
            self.assertIn("gbtest_job", str(caught.exception))
        self.assertIs(catalog.WORKERS["gbtest_job"], first)

    def test_only_worker_infos_are_registered(self):
        """Solo se registra un ``WorkerInfo``."""
        for value in ("gbtest_job", {"name": "gbtest_job"}, None):
            with self.subTest(value=value), self.assertRaises(TypeError):
                catalog.register_worker(value)
        self.assertEqual(dict(catalog.WORKERS), {})

    def test_unregister_removes_and_is_idempotent(self):
        """``unregister_worker`` quita el tipo y dice si estaba; quitar uno que no está no
        falla (``unregister()`` simétrico e idempotente)."""
        catalog.register_worker(_info())
        self.assertTrue(catalog.unregister_worker("gbtest_job"))
        self.assertNotIn("gbtest_job", catalog.WORKERS)
        self.assertFalse(catalog.unregister_worker("gbtest_job"))
        self.assertFalse(catalog.unregister_worker("gbtest_never"))
        catalog.register_worker(_info())  # se puede volver a registrar
        self.assertIn("gbtest_job", catalog.WORKERS)

    def test_workers_cannot_be_modified(self):
        """``WORKERS`` es de solo lectura: ni asignar, ni borrar, ni vaciar."""
        catalog.register_worker(_info())
        with self.assertRaises(TypeError):
            catalog.WORKERS["gbtest_other"] = _info("gbtest_other")
        with self.assertRaises(TypeError):
            del catalog.WORKERS["gbtest_job"]
        for method in ("clear", "pop", "popitem", "update", "setdefault"):
            with self.subTest(method=method):
                self.assertFalse(hasattr(catalog.WORKERS, method))
        self.assertEqual(list(catalog.WORKERS), ["gbtest_job"])

    def test_workers_is_a_live_view(self):
        """``WORKERS`` sigue los registros sin volver a importarlo."""
        view = catalog.WORKERS
        catalog.register_worker(_info("gbtest_a"))
        catalog.register_worker(_info("gbtest_b"))
        self.assertEqual(sorted(view), ["gbtest_a", "gbtest_b"])
        catalog.unregister_worker("gbtest_a")
        self.assertEqual(sorted(view), ["gbtest_b"])

    def test_concurrent_registrations_of_one_name_admit_one(self):
        """Desde varios hilos a la vez, el mismo nombre se registra una sola vez."""
        outcomes = []
        barrier = threading.Barrier(8)

        def attempt():
            barrier.wait()
            try:
                catalog.register_worker(_info())
                outcomes.append("ok")
            except ValueError:
                outcomes.append("rechazado")

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(sorted(outcomes), ["ok"] + ["rechazado"] * 7)

    def test_validate_request_uses_the_registry(self):
        """RF-004-02: ``validate_request`` con ``catalog=WORKERS`` acepta un tipo registrado
        y da ``worker_unknown`` si no lo está."""
        request = protocol.new_request("gbtest_job", label="Prueba", owner="jobs",
                                       environment="blender", timeout_s=60, now=NOW)
        with self.assertRaises(messages.JobError) as caught:
            protocol.validate_request(request, catalog=catalog.WORKERS)
        self.assertEqual(caught.exception.code, "worker_unknown")
        catalog.register_worker(_info())
        protocol.validate_request(request, catalog=catalog.WORKERS)


class BuiltinWorkersTest(unittest.TestCase):
    """Los tipos de trabajo de la 004 (plan 004 §5.1 y §5.3.1)."""

    def setUp(self):
        patcher = _empty_registry()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.builtins = {info.name: info for info in catalog.BUILTIN_WORKERS}

    def test_the_four_of_spec_004(self):
        """La 004 trae ``selftest``, ``runtime_install``, ``runtime_check`` y
        ``probe_python``, sin repetir nombre."""
        self.assertEqual(set(self.builtins), BUILTIN_NAMES)
        self.assertEqual(len(catalog.BUILTIN_WORKERS), 4)

    def test_register_and_unregister_builtins(self):
        """``bl/`` los registra al habilitar y los quita al deshabilitar: registrarlos dos
        veces falla sin dejar nada a medias, y quitarlos dos veces no."""
        self.assertEqual(dict(catalog.WORKERS), {})
        catalog.register_builtin_workers()
        self.assertEqual(set(catalog.WORKERS), BUILTIN_NAMES)
        with self.assertRaises(ValueError):
            catalog.register_builtin_workers()
        self.assertEqual(set(catalog.WORKERS), BUILTIN_NAMES)
        catalog.unregister_builtin_workers()
        self.assertEqual(dict(catalog.WORKERS), {})
        catalog.unregister_builtin_workers()
        self.assertEqual(dict(catalog.WORKERS), {})

    def test_builtins_register_all_or_nothing(self):
        """Si uno de ellos ya estaba registrado, no se registra ninguno."""
        other = _info("probe_python")
        catalog.register_worker(other)
        with self.assertRaises(ValueError) as caught:
            catalog.register_builtin_workers()
        self.assertIn("probe_python", str(caught.exception))
        self.assertEqual(dict(catalog.WORKERS), {"probe_python": other})

    def test_selftest_declaration(self):
        """El autodiagnóstico: política ``auto``, su estimador, su entorno según los
        parámetros y la función ``run`` de ``jobs/selftest.py`` (la misma que envolverá
        ``workers/selftest.py``)."""
        info = self.builtins["selftest"]
        self.assertEqual(info.policy, "auto")
        self.assertIs(info.run, selftest.run)
        self.assertIs(info.estimate_s, selftest.estimate_s)
        self.assertIs(info.environment, selftest.environment)
        self.assertEqual(info.default_timeout_s, 600.0)

    def test_engine_workers_always_go_to_a_subprocess(self):
        """Instalar el motor usa el ``pip`` de Blender en un proceso aparte (entorno
        ``blender``); verificarlo, el motor (``compute``). Ninguno tiene ``run``."""
        install = self.builtins["runtime_install"]
        check = self.builtins["runtime_check"]
        self.assertEqual((install.policy, install.environment), ("subprocess", "blender"))
        self.assertEqual((check.policy, check.environment), ("subprocess", "compute"))
        self.assertIsNone(install.run)
        self.assertIsNone(check.run)

    def test_probe_python_fits_in_the_thread(self):
        """El sondeo del intérprete externo se estima en ≤ 5 s (va en hilo cuando tenga su
        ``run``, plan 004 §5.1) con un tiempo máximo corto."""
        info = self.builtins["probe_python"]
        self.assertEqual((info.policy, info.environment), ("auto", "blender"))
        estimate = info.estimate_s({"path": "python.exe"})
        self.assertLessEqual(estimate, 5.0)
        self.assertLessEqual(info.default_timeout_s, 60.0)

    def test_labels_have_spanish(self):
        """Constitución, principio 10: cada nombre visible es un ``msgid`` en inglés con su
        traducción al español en ``CATALOG_ES`` (para ``core.i18n.install``)."""
        for info in catalog.BUILTIN_WORKERS:
            with self.subTest(worker=info.name):
                self.assertIsNone(SPANISH_LETTERS.search(info.label_msgid))
                spanish = catalog.CATALOG_ES.get(info.label_msgid)
                self.assertTrue(spanish and spanish.strip())
                self.assertNotEqual(spanish, info.label_msgid)
        with self.assertRaises(TypeError):
            catalog.CATALOG_ES["x"] = "y"

    def test_catalog_includes_selftest_messages(self):
        """Los mensajes propios del autodiagnóstico van también en ``CATALOG_ES``."""
        for msgid, spanish in selftest.CATALOG_ES.items():
            with self.subTest(msgid=msgid):
                self.assertEqual(catalog.CATALOG_ES[msgid], spanish)


if __name__ == "__main__":
    unittest.main()
