# SPDX-License-Identifier: GPL-3.0-or-later
"""Motor de cálculo: estado, plan de instalación y consentimiento (spec 004, T26; HU-004-3,
HU-004-4; RF-004-19, RF-004-20, RF-004-23, RF-004-24, RF-004-25; plan 004 §5.2.6, §5.3.1 y
§5.4.7).

- ``runtime.ComputeEnvironment(user_dir, lock)``: el motor de un lock vive en
  ``<user_dir>/runtime/<lock_id>/``, con sus paquetes en ``site/``. Crearlo, preguntar su
  estado, planear la instalación y pedirla no crea nada en disco (RF-004-19). ``status()``:
  ``missing`` sin la carpeta del lock (una ``<lock_id>.partial`` nunca cuenta), ``broken``
  si existe sin una verificación válida en ``runtime.json`` y ``ready`` si la tiene; el
  lanzador solo usa el motor ``ready`` (RF-004-25). Si falta el del lock vigente y queda el
  de otra versión de Geoblender (``outdated``), el trabajo dice cuál está instalado y cuál
  hace falta (``runtime_mismatch``, T43; RF-004-27).
- ``plan_install(origen, online_access=…)``: lo que el diálogo del RF-004-20 enseña antes de
  hacer nada (origen, paquetes con versión y licencia, MB de descarga y en disco, carpeta de
  destino) y la huella que firma el consentimiento. Nunca usa la red: PyPI con el acceso en
  línea desactivado es ``network_not_allowed``, que explica las dos salidas (RF-004-23); con
  el almacén de ruedas el origen es el almacén aunque no haya acceso en línea, y una rueda
  que falta (o un almacén inaccesible) es ``wheel_not_found`` con la carpeta (RF-004-24).
- ``install_request(plan, consent)``: la petición del trabajo ``runtime_install``, sin rutas
  absolutas; un consentimiento con la huella de otro plan, un plan cambiado después de
  calcular su huella o el plan de otro lock o de otra carpeta se rechazan
  (``request_invalid``).

Lock sintético y almacén temporal con ruedas sintéticas: ninguna prueba usa la red (los
sockets y ``urlopen`` están cambiados por funciones que lo anotan).
"""

import contextlib
import dataclasses
import datetime as dt
import json
import re
import socket
import sys
import unittest
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("jobs.catalog")
interpreter = import_geoblender("jobs.interpreter")
messages = import_geoblender("jobs.messages")
protocol = import_geoblender("jobs.protocol")
runner = import_geoblender("jobs.runner")
runtime = import_geoblender("jobs.runtime")

FILES_URL = "https://files.pythonhosted.org/packages/aa/bb/"
HEADER = {"schema": "geoblender.runtime_lock/1", "python": "3.13", "platform": "win_amd64"}
SYNTHETIC = (
    # nombre, versión, licencia, licencias incluidas, bytes instalados
    ("gbtestpkg", "1.0.0", "MIT", (), 2_500_000),
    ("gbtestdos", "2.0.0", "BSD-3-Clause AND Zlib", ("ZPL-2.1",), 1_500_000),
)
DISK_MB = 4.0
INSTALL_TIMEOUT_S = 1800.0
ABSOLUTE = re.compile(r"\A(?:[A-Za-z]:[\\/]|[\\/]{2})")
"""Una ruta absoluta de Windows (con unidad o de red)."""


def _synthetic_lock(store: Path, *, count: int = len(SYNTHETIC)) -> tuple[object, list]:
    """Las ruedas sintéticas de :data:`SYNTHETIC` en ``store`` y su lock (las ``count``
    primeras)."""
    wheels = []
    packages = []
    for name, version, license_, bundled, installed in SYNTHETIC[:count]:
        wheel = _support.make_wheel(store, name=name, version=version)
        wheels.append(wheel)
        packages.append({
            "name": name,
            "version": version,
            "filename": wheel.filename,
            "url": FILES_URL + wheel.filename,
            "sha256": wheel.sha256,
            "size": wheel.size,
            "installed_size": installed,
            "license": license_,
            "bundled_licenses": list(bundled),
            "required_by": ["004"],
        })
    return runtime.parse_lock(dict(HEADER, package=packages)), wheels


@contextlib.contextmanager
def _no_network() -> Iterator[list[str]]:
    """Cambia los sockets y ``urlopen`` por funciones que anotan la llamada y fallan; da la
    lista de llamadas (vacía si nadie intentó conectarse)."""
    calls: list[str] = []

    def refuse(name: str):
        def call(*args: object, **kwargs: object) -> None:
            calls.append(name)
            raise AssertionError(f"intento de usar la red: {name}")
        return call

    targets = (
        (socket, "socket"), (socket, "create_connection"), (socket, "getaddrinfo"),
        (urllib.request, "urlopen"),
    )
    with contextlib.ExitStack() as stack:
        for module, name in targets:
            stack.enter_context(mock.patch.object(module, name, side_effect=refuse(name)))
        yield calls


def _write_runtime_json(folder: Path, lock_id: str, *, ok: object = True) -> None:
    """``runtime.json`` de un motor con su verificación (``ok``)."""
    folder.mkdir(parents=True, exist_ok=True)
    data = {"schema": runtime.RUNTIME_SCHEMA, "lock_id": lock_id, "verification": {"ok": ok}}
    (folder / runtime.RUNTIME_FILE).write_text(json.dumps(data), encoding="utf-8")


def _strings(value: object) -> Iterator[str]:
    """Todos los textos de un valor JSON (claves y valores, en profundidad)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _strings(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _strings(inner)


# Tres pruebas con varias comprobaciones cada una: hasta 004/T39, tools/check.py repartía
# las unitarias por número de pruebas (gbtools.parts; docs/trampas.md §4).
class EnvironmentStatusTest(unittest.TestCase):
    def test_status_and_interpreter(self) -> None:
        """RF-004-19, RF-004-25: el motor del lock real vive en
        ``<datos de usuario>/runtime/<lock_id>/site``; crearlo y preguntar su estado no crea
        nada. Sin su carpeta está ``missing`` (también si hay una ``<lock_id>.partial``
        completa: nunca se usa); con la carpeta pero sin ``runtime.json`` válido, de otro
        lock, sin verificación correcta o sin ``site/``, ``broken``; con todo, ``ready``.
        El lanzador solo calcula con el motor ``ready``: en los demás estados,
        ``runtime_missing``; listo, ``--site`` con su carpeta y ``--expect-numpy`` con la
        versión de numpy del lock."""
        lock = runtime.read_lock()
        with self.assertRaises(ValueError):
            runtime.ComputeEnvironment(Path("relativa"), lock)
        with self.assertRaises(TypeError):
            runtime.ComputeEnvironment(Path.cwd(), {"schema": runtime.LOCK_SCHEMA})
        with _support.jobs_tmp() as base:
            user_dir = base / "usuario"
            env = runtime.ComputeEnvironment(user_dir, lock)
            self.assertIs(env.lock, lock)
            self.assertEqual(env.lock_id, lock.lock_id)
            self.assertEqual(env.path, user_dir / "runtime" / lock.lock_id)
            self.assertEqual(env.site_dir(), env.path / "site")
            self.assertEqual(env.status(), "missing")
            self.assertFalse(user_dir.exists(), "crear el motor o mirar su estado no crea nada")
            self.check_launch(env, ready=False)

            partial = env.path.with_name(f"{env.lock_id}.partial")
            (partial / "site").mkdir(parents=True)
            _write_runtime_json(partial, env.lock_id)
            self.assertEqual(env.status(), "missing", "una carpeta .partial nunca se usa")

            (env.path / "site").mkdir(parents=True)
            self.assertEqual(env.status(), "broken", "sin runtime.json")
            manifest = env.path / runtime.RUNTIME_FILE
            broken = {
                "no es JSON": "{",
                "no es un objeto": "[]",
                "otro esquema": json.dumps({"schema": "x/1", "lock_id": env.lock_id,
                                            "verification": {"ok": True}}),
            }
            for case, text in broken.items():
                with self.subTest(case):
                    manifest.write_text(text, encoding="utf-8")
                    self.assertEqual(env.status(), "broken")
            for case, (lock_id, ok) in {
                "otro lock": ("0" * 12, True),
                "verificación fallida": (env.lock_id, False),
                "verificación que no es booleana": (env.lock_id, "sí"),
            }.items():
                with self.subTest(case):
                    _write_runtime_json(env.path, lock_id, ok=ok)
                    self.assertEqual(env.status(), "broken")
            self.check_launch(env, ready=False)

            _write_runtime_json(env.path, env.lock_id)
            (env.path / "site").rmdir()
            self.assertEqual(env.status(), "broken", "sin site/")
            (env.path / "site").mkdir()
            self.assertEqual(env.status(), "ready")
            self.check_launch(env, ready=True)

    def check_launch(self, env: object, *, ready: bool) -> None:
        """El intérprete de un trabajo ``compute`` con el motor ``env``."""
        python = Path(sys.executable)
        if not ready:
            with self.assertRaises(messages.JobError) as caught:
                interpreter.resolve_interpreter(
                    "compute", blender_python=python, runtime=env, external_python=None,
                )
            self.assertEqual(caught.exception.code, "runtime_missing")
            return
        interp = interpreter.resolve_interpreter(
            "compute", blender_python=python, runtime=env, external_python=None,
        )
        self.assertEqual(interp.kind, "compute")
        self.assertEqual(interp.site, env.site_dir())
        self.assertEqual(interp.expect_numpy, env.lock.package("numpy").version)
        self.assertEqual(interp.lock_id, env.lock_id)


OTHER_LOCK_ID = "0123456789ab"
"""El ``lock_id`` de un tercer motor, de otra versión anterior de Geoblender."""
MISMATCH_TEXT = ("El motor de cálculo instalado ({instalado}) no es el que necesita esta "
                 "versión de Geoblender ({vigente}): actualícelo.")
"""El mensaje ``runtime_mismatch`` del §8 de la spec, tal cual."""


class OtherVersionEngineTest(unittest.TestCase):
    def test_engine_of_another_version_is_a_mismatch(self) -> None:
        """RF-004-25, RF-004-27: con dos locks en los mismos datos de usuario, el vigente
        (el real) y el de una versión anterior de Geoblender (sintético), un trabajo
        ``compute`` no se lanza (queda «Fallido» sin proceso) y dice por qué: sin ningún
        motor, ``runtime_missing``; si falta el del lock vigente y queda el del otro
        (``outdated``), ``runtime_mismatch`` con los dos ``lock_id`` en el mensaje del §8
        (el instalado y el vigente; si quedan varios anteriores, todos, por orden); con la
        carpeta del vigente dañada, otra vez ``runtime_missing`` (hay que repararlo, no
        actualizarlo)."""
        current = runtime.read_lock()
        with _support.jobs_tmp() as base:
            old_lock, _wheels = _synthetic_lock(base / "almacen")
            user_dir = base / "usuario"
            env = runtime.ComputeEnvironment(user_dir, current)
            old = runtime.ComputeEnvironment(user_dir, old_lock)
            self.assertNotEqual(old.lock_id, env.lock_id)
            self.assertNotIn(OTHER_LOCK_ID, (old.lock_id, env.lock_id))
            missing = ("runtime_missing", {}, messages.render("runtime_missing"))
            with mock.patch.dict(catalog._REGISTRY, clear=True):
                catalog.register_builtin_workers()
                launcher = runner.JobRunner(
                    jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                    blender_python=Path(sys.executable), runtime=env,
                )
                self.addCleanup(launcher.shutdown, timeout_s=2.0)
                with self.subTest("sin ningún motor"):
                    self.assertEqual(env.status(), "missing")
                    self.check_refused(env, launcher, missing)

                old.site_dir().mkdir(parents=True)
                _write_runtime_json(old.path, old.lock_id)
                self.assertEqual((old.status(), env.status()), ("ready", "outdated"))
                with self.subTest("el motor de otra versión"):
                    self.check_refused(env, launcher, (
                        "runtime_mismatch",
                        {"installed": old.lock_id, "required": env.lock_id},
                        MISMATCH_TEXT.format(instalado=old.lock_id, vigente=env.lock_id),
                    ))

                (env.runtime_dir / OTHER_LOCK_ID).mkdir()
                both = ", ".join(sorted([OTHER_LOCK_ID, old.lock_id]))
                with self.subTest("dos motores de otras versiones"):
                    self.check_refused(env, launcher, (
                        "runtime_mismatch", {"installed": both, "required": env.lock_id},
                        MISMATCH_TEXT.format(instalado=both, vigente=env.lock_id),
                    ))

                env.path.mkdir()
                self.assertEqual(env.status(), "broken")
                with self.subTest("el vigente, dañado"):
                    self.check_refused(env, launcher, missing)

    def check_refused(self, env: object, launcher: object, expected: tuple) -> None:
        """``resolve_interpreter`` con el motor ``env`` y un trabajo ``compute`` del
        lanzador ``launcher`` dan el error ``expected`` (código, valores y texto); el
        trabajo queda «Fallido» sin proceso."""
        code, values, text = expected
        with self.assertRaises(messages.JobError) as caught:
            interpreter.resolve_interpreter("compute", blender_python=Path(sys.executable),
                                            runtime=env, external_python=None)
        error = caught.exception
        self.assertEqual((error.code, dict(error.values), error.text), expected)
        handle = launcher.submit(protocol.new_request(
            "selftest", label="Necesita el motor", owner="jobs",
            params={"n": 1000, "chunks": 2}, environment="compute",
        ))
        result = handle.result()
        self.assertIsNotNone(result, "no se lanza: termina al pedirlo")
        self.assertEqual((result.state, result.error_code, result.error_text),
                         ("failed", code, text))
        self.assertIsNone(handle.pid)


class RemoveEngineTest(unittest.TestCase):
    def test_remove_only_when_installed_and_unused(self) -> None:
        """RF-004-19: ``remove(in_use=…)`` borra el motor de este lock (y los restos
        ``<lock_id>.old`` de un intento anterior) solo cuando se pide, que es después de que
        el usuario lo confirme en su diálogo (``geoblender.jobs_setup_runtime``). Sin motor
        no hay nada que borrar ni se crea nada; con un trabajo de esta sesión que lo usa
        (``in_use``) o con un fichero suyo abierto (un worker de otra sesión de Blender) lo
        conserva tal cual; nunca toca el motor de otro lock ni una instalación a medias
        (``.partial``, quizá en marcha en otra sesión). Un texto suelto como ``in_use`` es
        :class:`TypeError`."""
        lock = runtime.read_lock()
        with _support.jobs_tmp() as base:
            user_dir = base / "usuario"
            env = runtime.ComputeEnvironment(user_dir, lock)
            self.assertFalse(env.remove(in_use=()))
            self.assertFalse(user_dir.exists())
            (env.path / "site").mkdir(parents=True)
            _write_runtime_json(env.path, env.lock_id)
            other = env.runtime_dir / ("0" * 12) / "site"
            other.mkdir(parents=True)
            staged = env.staged_site
            staged.mkdir(parents=True)
            leftover = env.path.with_name(env.lock_id + runtime.OLD_SUFFIX)
            leftover.mkdir()
            self.assertEqual(env.status(), "ready")
            with self.assertRaises(TypeError):
                env.remove(in_use=env.lock_id)
            self.assertFalse(env.remove(in_use={env.lock_id}))
            self.assertEqual(env.status(), "ready")
            held = env.site_dir() / "numpy_de_otra_sesion.py"
            held.write_bytes(b"")
            with held.open("rb"):
                self.assertFalse(env.remove(in_use=()))
            self.assertEqual(env.status(), "ready")
            self.assertTrue(env.remove(in_use={"0" * 12}))
            self.assertFalse(env.path.exists())
            self.assertFalse(leftover.exists())
            self.assertTrue(other.is_dir())
            self.assertTrue(staged.is_dir())
            self.assertEqual(env.status(), "outdated")
            self.assertFalse(env.remove(in_use=()))


class InstallPlanTest(unittest.TestCase):
    def test_plan_shows_source_packages_sizes_and_destination(self) -> None:
        """RF-004-19, RF-004-20, RF-004-23, RF-004-24: el plan lista el origen, cada paquete
        con su versión y su licencia (también las incluidas en la rueda), los MB de descarga
        y en disco (del lock) y la carpeta de destino, con una huella de 64 hexadecimales
        que no cambia al repetirlo y sí con otro origen. PyPI con el acceso en línea
        desactivado: ``network_not_allowed``, que explica las dos salidas, sin conectarse.
        Con el almacén, el origen es el almacén aunque no haya acceso en línea (también con
        «automático» y un almacén configurado); una rueda que falta, o un almacén que no se
        alcanza, es ``wheel_not_found`` con el fichero y la carpeta. Nada usa la red ni crea
        la carpeta del motor."""
        with _support.jobs_tmp() as base, _no_network() as calls:
            store = base / "almacen"
            lock, wheels = _synthetic_lock(store)
            user_dir = base / "usuario"
            env = runtime.ComputeEnvironment(user_dir, lock)
            listed = [(name, version, license_, bundled)
                      for name, version, license_, bundled, _ in SYNTHETIC]
            download_mb = sum(wheel.size for wheel in wheels) / 1_000_000

            pypi = env.plan_install(runtime.WheelSource.pypi(), online_access=True)
            self.assertEqual(pypi.lock_id, lock.lock_id)
            self.assertEqual(pypi.source.kind, "pypi")
            self.assertIsNone(pypi.source.folder)
            self.assertEqual(
                [(p.name, p.version, p.license, p.bundled_licenses) for p in pypi.packages],
                listed,
            )
            self.assertEqual([p.origin for p in pypi.packages],
                             [FILES_URL + wheel.filename for wheel in wheels])
            self.assertAlmostEqual(pypi.download_mb, download_mb)
            self.assertAlmostEqual(pypi.disk_mb, DISK_MB)
            self.assertEqual(pypi.destination, user_dir / "runtime" / lock.lock_id)
            self.assertRegex(pypi.digest, r"\A[0-9a-f]{64}\Z")
            self.assertEqual(
                env.plan_install(runtime.WheelSource.pypi(), online_access=True), pypi
            )

            with self.assertRaises(messages.JobError) as caught:
                env.plan_install(runtime.WheelSource.pypi(), online_access=False)
            self.assertEqual(caught.exception.code, "network_not_allowed")
            self.assertIn("Permitir acceso en línea", caught.exception.text)
            self.assertIn("configure el almacén de ruedas", caught.exception.text)

            local = env.plan_install(runtime.WheelSource.wheelhouse(store),
                                     online_access=False)
            self.assertEqual((local.source.kind, local.source.folder), ("wheelhouse", store))
            self.assertEqual(
                [(p.name, p.version, p.license, p.bundled_licenses) for p in local.packages],
                listed,
            )
            self.assertEqual([p.origin for p in local.packages],
                             [str(store / wheel.filename) for wheel in wheels])
            self.assertEqual((local.download_mb, local.disk_mb, local.destination),
                             (pypi.download_mb, pypi.disk_mb, pypi.destination))
            self.assertNotEqual(local.digest, pypi.digest)

            choices = {
                ("AUTO", store): runtime.WheelSource.wheelhouse(store),
                ("auto", None): runtime.WheelSource.pypi(),
                ("WHEELHOUSE", store): runtime.WheelSource.wheelhouse(store),
                ("PYPI", store): runtime.WheelSource.pypi(),
            }
            for (choice, folder), expected in choices.items():
                with self.subTest(choice=choice, folder=folder):
                    self.assertEqual(runtime.choose_source(choice, wheelhouse_dir=folder),
                                     expected)
            with self.assertRaises(ValueError):
                runtime.choose_source("WHEELHOUSE", wheelhouse_dir=None)
            with self.assertRaises(ValueError):
                runtime.WheelSource.wheelhouse(Path("ruedas"))

            (store / wheels[1].filename).unlink()
            unreachable = base / "nas_caido"
            for folder, missing in ((store, wheels[1]), (unreachable, wheels[0])):
                with self.subTest(folder=folder.name):
                    with self.assertRaises(messages.JobError) as caught:
                        env.plan_install(runtime.WheelSource.wheelhouse(folder),
                                         online_access=True)
                    self.assertEqual(caught.exception.code, "wheel_not_found")
                    self.assertEqual(caught.exception.values,
                                     {"file": missing.filename, "folder": str(folder)})
            self.assertEqual(calls, [], "planear la instalación no usa la red")
            self.assertFalse(user_dir.exists(), "planear la instalación no crea nada")


class InstallRequestTest(unittest.TestCase):
    def test_consent_signs_the_plan(self) -> None:
        """RF-004-19, RF-004-20: el consentimiento lleva usuario, equipo, hora UTC y la
        huella del plan. ``install_request`` da la petición del trabajo ``runtime_install``
        (lock, origen, paquetes con su huella, huella del plan y consentimiento) sin rutas
        absolutas: el lanzador la prepara con los datos de usuario y el almacén como rutas
        prohibidas, y toma del tipo de trabajo el entorno ``blender`` y 1800 s. Se rechaza
        (``request_invalid``) un consentimiento con la huella de otro plan, un plan cambiado
        después de calcular su huella y el plan de otro lock o de otra carpeta de destino;
        nada crea la carpeta del motor."""
        with _support.jobs_tmp() as base:
            store = base / "almacen"
            lock, wheels = _synthetic_lock(store)
            user_dir = base / "usuario"
            env = runtime.ComputeEnvironment(user_dir, lock)
            plan = env.plan_install(runtime.WheelSource.wheelhouse(store), online_access=False)
            moment = dt.datetime(2026, 10, 7, 9, 30, tzinfo=dt.UTC)
            consent = runtime.Consent.given(plan, user="ana", host="PC-IMGA-07", now=moment)
            self.assertEqual(
                (consent.user, consent.host, consent.given_at, consent.plan_digest),
                ("ana", "PC-IMGA-07", "2026-10-07T09:30:00.000Z", plan.digest),
            )
            default = runtime.Consent.given(plan)
            self.assertTrue(default.user.strip() and default.host.strip())
            self.assertEqual(default.plan_digest, plan.digest)

            other_plan = env.plan_install(runtime.WheelSource.pypi(), online_access=True)
            other_lock, _ = _synthetic_lock(base / "otro", count=1)
            foreign = runtime.ComputeEnvironment(user_dir, other_lock).plan_install(
                runtime.WheelSource.pypi(), online_access=True)
            elsewhere = runtime.ComputeEnvironment(base / "otro_usuario", lock).plan_install(
                runtime.WheelSource.pypi(), online_access=True)
            rejected = {
                "consentimiento de otro plan": (plan, dataclasses.replace(
                    consent, plan_digest=other_plan.digest)),
                "plan cambiado": (dataclasses.replace(plan, installed_size=1), consent),
                "plan de otro lock": (foreign, runtime.Consent.given(foreign)),
                "plan de otra carpeta": (elsewhere, runtime.Consent.given(elsewhere)),
            }
            for case, (some_plan, some_consent) in rejected.items():
                with self.subTest(case):
                    with self.assertRaises(messages.JobError) as caught:
                        env.install_request(some_plan, some_consent)
                    self.assertEqual(caught.exception.code, "request_invalid")
            with self.assertRaises(messages.JobError) as caught:
                env.install_request(plan, rejected["consentimiento de otro plan"][1])
            self.assertIn("consentimiento", caught.exception.text)

            request = env.install_request(plan, consent)
            self.assertEqual((request.worker, request.owner, request.label),
                             ("runtime_install", "jobs", "Instalar el motor de cálculo"))
            self.assertEqual(request.params["lock_id"], lock.lock_id)
            self.assertEqual(request.params["source"], "wheelhouse")
            self.assertEqual(request.params["plan_digest"], plan.digest)
            self.assertEqual(request.params["consent"], {
                "user": "ana", "host": "PC-IMGA-07",
                "given_at": "2026-10-07T09:30:00.000Z", "plan_digest": plan.digest,
            })
            self.assertEqual(request.params["packages"], [
                {"name": p.name, "version": p.version, "filename": p.filename,
                 "sha256": p.sha256, "size": p.size, "url": p.url}
                for p in lock.packages
            ])
            absolute = [text for text in _strings(request.to_json()) if ABSOLUTE.match(text)]
            self.assertEqual(absolute, [], "la petición no lleva rutas absolutas")

            with mock.patch.dict(catalog._REGISTRY, clear=True):
                catalog.register_builtin_workers()
                launcher = runner.JobRunner(
                    jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                    blender_python=Path(sys.executable), forbidden_roots=(user_dir, store),
                )
                folder = launcher.prepare(request)
            stored = protocol.read_request(folder)
            self.assertEqual((stored.environment, stored.timeout_s),
                             ("blender", INSTALL_TIMEOUT_S))
            self.assertEqual(stored.params, request.params)
            self.assertFalse(user_dir.exists(), "pedir la instalación no crea el motor")


if __name__ == "__main__":
    unittest.main()
