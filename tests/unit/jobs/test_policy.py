# SPDX-License-Identifier: GPL-3.0-or-later
"""Elección del ejecutor: hilo o proceso aparte (spec 004, T06; RF-004-03; plan 004 §5.4.1).

RF-004-03: va a proceso aparte todo trabajo que necesita el motor de cálculo (``compute``),
que su tipo declara de proceso aparte (``subprocess``) o cuyo tiempo estimado pasa de 5 s o
no se conoce; el resto, en hilo. Ninguna política fuerza el hilo, y sin función ``run`` no
hay hilo posible. El umbral es ``INPROCESS_MAX_ESTIMATED_S = 5.0`` (D-1, DP-31): 4,9 s →
hilo; 5,1 s → proceso aparte.

Con el autodiagnóstico (estimador calibrado con plan §2.1): la suma de 10 s va a proceso
aparte y el producto de matrices con n = 1001 exige el motor (n = 500, en hilo).
"""

import datetime as dt
import math
import unittest

from tests.support.package import import_geoblender

catalog = import_geoblender("jobs.catalog")
policy = import_geoblender("jobs.policy")
protocol = import_geoblender("jobs.protocol")

WorkerInfo = catalog.WorkerInfo
NOW = dt.datetime(2026, 10, 7, 9, 0, 0, tzinfo=dt.UTC)


def _run(ctx):
    return {}


def _info(estimate=1.0, **changes):
    """Un tipo de trabajo ``gbtest_job`` que estima ``estimate`` s, con ``changes``."""
    values = {
        "policy": "auto",
        "environment": "blender",
        "estimate_s": lambda params: estimate,
        "run": _run,
    }
    values.update(changes)
    return WorkerInfo("gbtest_job", "Test job", **values)


def _request(worker="gbtest_job", params=None, environment=None):
    """Una petición nueva (el lanzador aún no ha fijado entorno ni tiempo máximo)."""
    return protocol.new_request(worker, label="Prueba", owner="jobs", params=params or {},
                                environment=environment, now=NOW)


def _selftest():
    return next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")


class ThresholdTest(unittest.TestCase):
    """RF-004-03: el umbral de 5 s estimados (D-1)."""

    def test_threshold_is_five_seconds(self):
        """RF-004-03: ``INPROCESS_MAX_ESTIMATED_S`` = 5,0 s."""
        self.assertEqual(policy.INPROCESS_MAX_ESTIMATED_S, 5.0)

    def test_estimates_around_the_threshold(self):
        """RF-004-03: 4,9 s → hilo; 5 s justos → hilo; 5,1 s → proceso aparte."""
        cases = {0.0: "inprocess", 4.9: "inprocess", 5.0: "inprocess", 5.1: "subprocess",
                 5.000001: "subprocess", 60: "subprocess", math.inf: "subprocess"}
        for estimate, expected in cases.items():
            with self.subTest(estimate=estimate):
                self.assertEqual(policy.choose_executor(_info(estimate), _request()), expected)

    def test_unknown_estimate_goes_to_a_subprocess(self):
        """RF-004-03: sin estimador, o si devuelve nada, falla o da algo que no es una
        duración (NaN, negativa, booleano, texto), la duración no se conoce: proceso
        aparte."""

        def broken(params):
            raise KeyError("n")

        for estimator in (None, lambda params: None):
            with self.subTest(estimator=estimator):
                info = WorkerInfo("gbtest_job", "Test job", estimate_s=estimator, run=_run)
                self.assertEqual(policy.choose_executor(info, _request()), "subprocess")
        # Un estimador que falla o devuelve otra cosa es un error del módulo: queda avisado.
        wrong = {
            "falla": broken,
            "NaN": lambda params: math.nan,
            "negativa": lambda params: -1.0,
            "booleano": lambda params: True,
            "texto": lambda params: "1",
        }
        for name, estimator in wrong.items():
            with self.subTest(estimator=name), self.assertLogs("geoblender.jobs") as logs:
                info = WorkerInfo("gbtest_job", "Test job", estimate_s=estimator, run=_run)
                self.assertEqual(policy.choose_executor(info, _request()), "subprocess")
            self.assertTrue(any("gbtest_job" in line for line in logs.output), logs.output)

    def test_estimator_sees_the_params_read_only(self):
        """El estimador recibe los parámetros de la petición sin poder cambiarlos."""
        seen = []

        def estimator(params):
            seen.append(dict(params))
            params["n"] = 0  # TypeError: se trata como «no se conoce»
            return 1.0

        request = _request(params={"n": 7})
        with self.assertLogs("geoblender.jobs"):
            self.assertEqual(policy.choose_executor(_info(estimate_s=estimator), request),
                             "subprocess")
        self.assertEqual(seen, [{"n": 7}])
        self.assertEqual(request.params, {"n": 7})


class EnvironmentTest(unittest.TestCase):
    """RF-004-03: lo que necesita el motor de cálculo va siempre a proceso aparte."""

    def test_compute_always_goes_to_a_subprocess(self):
        """RF-004-03: entorno ``compute`` → proceso aparte, aunque estime 0,1 s y tenga
        ``run``: lo declare el tipo, lo pida la petición o lo exijan sus parámetros."""
        by_type = _info(0.1, environment="compute")
        self.assertEqual(policy.choose_executor(by_type, _request()), "subprocess")
        by_request = _info(0.1)
        self.assertEqual(
            policy.choose_executor(by_request, _request(environment="compute")), "subprocess"
        )
        by_params = _info(0.1, environment=lambda params: "compute")
        self.assertEqual(policy.choose_executor(by_params, _request()), "subprocess")

    def test_resolve_environment(self):
        """El entorno del trabajo: ``compute`` si lo pide la petición o lo exige el tipo
        (manda lo más exigente); si no, ``blender``."""
        cases = [
            ("blender", None, "blender"),
            ("blender", "blender", "blender"),
            ("blender", "compute", "compute"),
            ("compute", None, "compute"),
            ("compute", "blender", "compute"),
        ]
        for declared, requested, expected in cases:
            with self.subTest(declared=declared, requested=requested):
                info = _info(environment=declared)
                request = _request(environment=requested)
                self.assertEqual(policy.resolve_environment(info, request), expected)

    def test_request_of_another_worker_is_a_program_error(self):
        """Elegir con el ``WorkerInfo`` de otro tipo de trabajo es un error del programa."""
        with self.assertRaises(ValueError):
            policy.choose_executor(_info(), _request(worker="gbtest_other"))
        with self.assertRaises(ValueError):
            policy.resolve_environment(_info(), _request(worker="gbtest_other"))


class PolicyTest(unittest.TestCase):
    """RF-004-03: la política del tipo de trabajo."""

    def test_subprocess_policy_is_respected(self):
        """RF-004-03: un tipo de proceso aparte va a proceso aparte aunque estime 0,1 s y
        tenga ``run``."""
        info = _info(0.1, policy="subprocess")
        self.assertEqual(policy.choose_executor(info, _request()), "subprocess")

    def test_no_policy_forces_the_thread(self):
        """RF-004-03: con cualquier política, un trabajo de más de 5 s o de duración
        desconocida va a proceso aparte; y no existe una política «hilo»."""
        for name in catalog.POLICIES:
            for estimate in (5.1, 3600.0, None):
                with self.subTest(policy=name, estimate=estimate):
                    info = _info(estimate, policy=name)
                    self.assertEqual(policy.choose_executor(info, _request()), "subprocess")
        for name in ("inprocess", "thread"):
            with self.subTest(policy=name), self.assertRaises(ValueError):
                _info(policy=name)

    def test_without_run_goes_to_a_subprocess(self):
        """RF-004-03: sin función ``run`` no hay hilo: proceso aparte aunque estime 0,1 s."""
        self.assertEqual(policy.choose_executor(_info(0.1, run=None), _request()), "subprocess")


class SelftestPolicyTest(unittest.TestCase):
    """RF-004-03 con el autodiagnóstico (plan 004 §5.4.1 y T21)."""

    def setUp(self):
        self.info = _selftest()

    def _choose(self, params, environment=None):
        request = _request("selftest", params, environment)
        return (policy.resolve_environment(self.info, request),
                policy.choose_executor(self.info, request))

    def test_matmul_over_1000_needs_compute(self):
        """RF-004-03: ``matmul`` con n = 1001 exige ``compute`` (proceso aparte); con
        n = 1000 y n = 500 (``MATMUL_BLENDER``), entorno ``blender`` y en hilo."""
        self.assertEqual(self._choose({"op": "matmul", "n": 1001}), ("compute", "subprocess"))
        self.assertEqual(self._choose({"op": "matmul", "n": 2000}), ("compute", "subprocess"))
        self.assertEqual(self._choose({"op": "matmul", "n": 1000}), ("blender", "inprocess"))
        self.assertEqual(self._choose({"op": "matmul", "n": 500}), ("blender", "inprocess"))
        self.assertEqual(self._choose({"op": "matmul", "n": 500}, "blender"),
                         ("blender", "inprocess"))

    def test_matmul_requested_in_compute_goes_to_a_subprocess(self):
        """RF-004-03: pedir el motor para un producto pequeño lo lleva a proceso aparte."""
        self.assertEqual(self._choose({"op": "matmul", "n": 500}, "compute"),
                         ("compute", "subprocess"))

    def test_chunked_sum_around_the_threshold(self):
        """RF-004-03: suma por trozos: 49 × 0,1 s (4,9 s) → hilo; 51 × 0,1 s (5,1 s) →
        proceso aparte; la de 10 s del menú (50 × 0,2 s, ``SUM_10S``) → proceso aparte."""
        self.assertEqual(self._choose({"op": "chunked_sum", "chunks": 49, "sleep_s": 0.1}),
                         ("blender", "inprocess"))
        self.assertEqual(self._choose({"op": "chunked_sum", "chunks": 51, "sleep_s": 0.1}),
                         ("blender", "subprocess"))
        self.assertEqual(self._choose({"op": "chunked_sum", "chunks": 50, "sleep_s": 0.2}),
                         ("blender", "subprocess"))

    def test_provoked_crash_and_noise_only_in_a_subprocess(self):
        """Una caída provocada (``os._exit``) o el ruido por el descriptor 1 tumbarían o
        ensuciarían Blender: duración desconocida → siempre proceso aparte."""
        self.assertEqual(self._choose({"crash_at": 1}), ("blender", "subprocess"))
        self.assertEqual(self._choose({"stdout_noise": True}), ("blender", "subprocess"))
        self.assertEqual(self._choose({"ignore_cancel": True}), ("blender", "inprocess"))
        self.assertEqual(self._choose({"fail_at": 1}), ("blender", "inprocess"))

    def test_invalid_params_go_to_a_subprocess(self):
        """Parámetros que no valen: duración desconocida, proceso aparte (allí el trabajo
        acabará «Fallido» con ``request_invalid``)."""
        self.assertEqual(self._choose({"op": "nada"}), ("blender", "subprocess"))
        self.assertEqual(self._choose({"n": -1}), ("blender", "subprocess"))

    def test_engine_workers(self):
        """``runtime_install`` y ``runtime_check`` van siempre a proceso aparte."""
        for name in ("runtime_install", "runtime_check"):
            info = next(i for i in catalog.BUILTIN_WORKERS if i.name == name)
            with self.subTest(worker=name):
                self.assertEqual(policy.choose_executor(info, _request(name)), "subprocess")


if __name__ == "__main__":
    unittest.main()
