# SPDX-License-Identifier: GPL-3.0-or-later
"""Instalación del motor de cálculo en su carpeta parcial (spec 004, T27; HU-004-3,
HU-004-4; RF-004-21, RF-004-24; plan 004 §5.3.1, §5.3.3, §5.4.7 y §6).

- ``runtime.fetch_wheel``: copia la rueda del almacén o la descarga de la URL del lock con
  ``urllib``, calculando su sha256 mientras la lee; si no coincide con la del lock,
  ``wheel_hash_mismatch`` y no queda nada. Una rueda que falta en el almacén es
  ``wheel_not_found`` y una descarga que falla, ``network_error``; la cancelación la para.
- ``runtime.write_requirements``: ``requirements.txt`` con ``--hash`` de cada paquete.
- ``runtime.run_pip_install``: el ``pip`` del Python de Blender con la orden exacta del plan
  §5.4.7 (``--isolated``, ``--no-index``, ``--require-hashes``, ``--target``,
  ``--no-cache-dir``…). Con ``PIP_REQUIRE_VIRTUALENV=1`` y ``PIP_USER=1`` en su entorno
  instala igual: ``--isolated`` hace que ``pip`` no lea sus variables.
- El trabajo ``runtime_install`` (``workers/runtime_install.py``): con la petición de
  ``ComputeEnvironment.install_request`` y las rutas de ``install_paths`` (los datos de
  usuario y el almacén viajan en la línea de órdenes, ``--path``), deja los paquetes en
  ``runtime/<lock_id>.partial/site`` por las dos vías (almacén y «PyPI»), sin adoptar el
  motor (T28) y borrando antes la carpeta parcial de un intento anterior. Con una huella
  alterada, o cancelado mientras instala, no deja nada en ``.partial`` ni ningún motor
  usable, y borra las ruedas que había copiado.

Ruedas sintéticas (``gbtestpkg`` y ``gbtestdos``) en un almacén temporal; la «PyPI» es la
URL ``file://`` de cada rueda: ninguna prueba usa la red. ``pip`` tarda 1–2 s: todos los
trabajos y la instalación directa se lanzan a la vez al empezar (``setUpModule``), con
``TEMP`` y ``TMP`` en una carpeta de la prueba, y cada prueba mira lo que dejó el suyo.
"""

import contextlib
import dataclasses
import json
import os
import re
import socket
import sys
import threading
import time
import unittest
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
worker_api = import_geoblender("jobs.worker_api")

HEADER = {"schema": "geoblender.runtime_lock/1", "python": "3.13", "platform": "win_amd64"}
FILES_URL = "https://files.pythonhosted.org/packages/aa/bb/"
SYNTHETIC = (("gbtestpkg", "1.0.0"), ("gbtestdos", "2.0.0"))
PIP_ENVIRONMENT = {"PIP_REQUIRE_VIRTUALENV": "1", "PIP_USER": "1"}
"""Variables del usuario que harían fallar a ``pip`` sin ``--isolated`` (con
``--target``: «Can not combine '--user' and '--target'»)."""
LABELS = {
    "wheelhouse": "Instalar desde el almacén",
    "pypi": "Instalar desde PyPI",
    "hash": "Huella alterada",
    "cancel": "Instalación cancelada",
}
DEADLINE_S = 60.0
POLL_S = 0.02
ABSOLUTE = re.compile(r"\A(?:[A-Za-z]:[\\/]|[\\/]{2})")

_CASES: dict[str, dict] = {}
_STATE: dict[str, object] = {}


def _lock(wheels: list, *, url_of=None, sha_of=None):
    """El lock de ``wheels`` (ruedas sintéticas): sus URL las da ``url_of(rueda)`` (por
    defecto, una de PyPI) y sus huellas ``sha_of(rueda)`` (por defecto, la suya)."""
    packages = [{
        "name": wheel.name,
        "version": wheel.version,
        "filename": wheel.filename,
        "url": FILES_URL + wheel.filename if url_of is None else url_of(wheel),
        "sha256": wheel.sha256 if sha_of is None else sha_of(wheel),
        "size": wheel.size,
        "installed_size": 2_000_000,
        "license": "MIT",
        "bundled_licenses": [],
        "required_by": ["004"],
    } for wheel in wheels]
    return runtime.parse_lock(dict(HEADER, package=packages))


def _altered(sha256: str) -> str:
    """Otra huella de 64 hexadecimales (la primera cifra cambiada)."""
    return ("1" if sha256[0] == "0" else "0") + sha256[1:]


@contextlib.contextmanager
def _no_sockets() -> Iterator[list[str]]:
    """Cambia los sockets por funciones que anotan la llamada y fallan; da la lista de
    llamadas. ``urlopen`` sigue funcionando con ``file://``, que no abre sockets."""
    calls: list[str] = []

    def refuse(name: str):
        def call(*args: object, **kwargs: object) -> None:
            calls.append(name)
            raise OSError(f"intento de usar la red: {name}")
        return call

    with contextlib.ExitStack() as stack:
        for name in ("socket", "create_connection", "getaddrinfo"):
            stack.enter_context(mock.patch.object(socket, name, side_effect=refuse(name)))
        yield calls


def _stale_partial(env) -> Path:
    """Una carpeta ``<lock_id>.partial`` de una instalación anterior cortada a la mitad, con
    un paquete de otra versión y un fichero de más."""
    stale = env.partial_path / "site" / "gbtestpkg"
    stale.mkdir(parents=True)
    (stale / "__init__.py").write_text('__version__ = "0.9.0"\n', encoding="utf-8")
    (env.partial_path / "site" / "resto.txt").write_text("a medias\n", encoding="utf-8")
    return env.partial_path


def _submit(launcher, name: str, env, source, *, online: bool = False) -> None:
    plan = env.plan_install(source, online_access=online)
    consent = runtime.Consent.given(plan, user="ana", host="PC-PRUEBAS")
    request = env.install_request(plan, consent, label=LABELS[name])
    paths = env.install_paths(plan)
    _CASES[name].update(env=env, plan=plan, request=request, paths=paths)
    _CASES[name]["handle"] = launcher.submit(request, paths=paths)


def _direct_install(folder: Path, wheel) -> None:
    """``run_pip_install`` llamado directamente, con :data:`PIP_ENVIRONMENT` en el entorno
    del proceso (``pip`` lo hereda)."""
    try:
        package = _lock([wheel]).packages[0]
        requirements = runtime.write_requirements([package], folder / "requirements.txt")
        target = folder / "site"
        _STATE["direct_environ"] = {name: os.environ.get(name) for name in PIP_ENVIRONMENT}
        with (folder / "instalador.log").open("wb") as log:
            runtime.run_pip_install(Path(sys.executable), wheel.path.parent, requirements,
                                    target, cancelled=lambda: False, log=log)
        _STATE["direct_target"] = target
    except BaseException as exc:  # noqa: BLE001 - se comprueba en la prueba
        _STATE["direct_error"] = exc


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    _STATE["base"] = base
    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    catalog.register_builtin_workers()

    store = base / "almacen"
    wheels = [_support.make_wheel(store, name=name, version=version)
              for name, version in SYNTHETIC]
    one = _lock(wheels[:1])
    by_file = _lock(wheels[:1], url_of=lambda wheel: wheel.path.as_uri())
    tampered = _lock(wheels, sha_of=lambda wheel: (
        _altered(wheel.sha256) if wheel.name == "gbtestdos" else wheel.sha256))
    _STATE.update(store=store, wheels=wheels)

    temp = base / "temp"
    temp_cancel = base / "temp_cancelada"
    temp.mkdir()
    temp_cancel.mkdir()
    _STATE.update(temp=temp)
    launcher = runner.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                                blender_python=Path(sys.executable), max_subprocess=4)
    _STATE["runner"] = launcher
    for name in LABELS:
        _CASES[name] = {"user_dir": base / f"usuario_{name}"}

    def env_of(name: str, lock) -> object:
        return runtime.ComputeEnvironment(_CASES[name]["user_dir"], lock)

    wheelhouse = runtime.WheelSource.wheelhouse(store)
    environ = dict(PIP_ENVIRONMENT, TEMP=str(temp), TMP=str(temp))
    with mock.patch.dict(os.environ, environ):
        # El cancelado, con su propio TEMP: al matar pip pueden quedar sus temporales.
        with mock.patch.dict(os.environ, {"TEMP": str(temp_cancel), "TMP": str(temp_cancel)}):
            _submit(launcher, "cancel", env_of("cancel", one), wheelhouse)
        env = env_of("wheelhouse", one)
        _CASES["wheelhouse"]["stale"] = _stale_partial(env)
        _submit(launcher, "wheelhouse", env, wheelhouse)
        _submit(launcher, "pypi", env_of("pypi", by_file), runtime.WheelSource.pypi(),
                online=True)
        env = env_of("hash", tampered)
        _CASES["hash"]["stale"] = _stale_partial(env)
        _submit(launcher, "hash", env, wheelhouse)

        direct = base / "directo"
        direct.mkdir()
        thread = threading.Thread(target=_direct_install,
                                  args=(direct, _support.make_wheel(direct / "ruedas")))
        thread.start()
        # El arranque con un --path que no es <nombre>=<ruta>.
        job = _support.prepare_job(base / "jobs")
        bad_path = _support.LaunchedWorker(job.path, args=(
            "--package-dir", str(EXTENSION_DIR), "--job-dir", str(job.path),
            "--kind", "blender", "--path", "runtime"))
        unittest.addModuleCleanup(bad_path.close)
        deadline = time.monotonic() + DEADLINE_S
        handles = {name: case["handle"] for name, case in _CASES.items()}
        cancel = handles["cancel"]
        while thread.is_alive() or any(h.result() is None for h in handles.values()):
            if time.monotonic() > deadline:
                pending = [name for name, h in handles.items() if h.result() is None]
                raise AssertionError(f"no terminaron a tiempo: {pending}")
            launcher.poll()
            if "cancel_message" not in _STATE and cancel.message == runtime.INSTALLING_TEXT:
                _STATE["cancel_message"] = cancel.message
                _STATE["cancel_sent"] = cancel.cancel()
            time.sleep(POLL_S)
        thread.join()
        launcher.poll()
        _STATE["bad_path"] = bad_path.finish()


def _summary(handle) -> dict:
    return json.loads(handle.job_dir.result_file.read_text(encoding="utf-8"))["summary"]


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _strings(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _strings(inner)


class FetchWheelTest(unittest.TestCase):
    def test_fetch_checks_the_hash(self) -> None:
        """RF-004-21, RF-004-24: ``fetch_wheel`` copia la rueda del almacén o la descarga de
        su URL (``file://``) con la huella del lock, avisando de los bytes leídos; con otra
        huella (o más bytes de los del lock), ``wheel_hash_mismatch`` con el fichero, sin
        dejar nada en la carpeta de destino. Sin la rueda en el almacén, o con el almacén
        inalcanzable, ``wheel_not_found`` con el fichero y la carpeta; una URL que falla o
        que no es https ni file, ``network_error`` con el paquete, sin abrir ningún socket.
        Cancelada (``cancelled`` verdadero o que lanza ``JobCancelled``), no deja nada.
        ``write_requirements`` escribe ``nombre==versión --hash=sha256:…`` por paquete y la
        orden de ``pip`` es la del plan §5.4.7."""
        store, wheels = _STATE["store"], _STATE["wheels"]
        good = _lock(wheels).packages
        by_file = _lock(wheels, url_of=lambda wheel: wheel.path.as_uri()).packages
        with _support.jobs_tmp() as base, _no_sockets() as calls:
            sources = {
                "almacén": (runtime.WheelSource.wheelhouse(store), good),
                "PyPI": (runtime.WheelSource.pypi(), by_file),
            }
            for label, (source, packages) in sources.items():
                with self.subTest(label):
                    dest = base / f"ok_{source.kind}"
                    seen: list[int] = []
                    for package, wheel in zip(packages, wheels, strict=True):
                        seen.clear()
                        path = runtime.fetch_wheel(package, source, dest, progress=seen.append,
                                                   cancelled=lambda: False)
                        self.assertEqual(path, dest / wheel.filename)
                        self.assertEqual(_support.sha256_file(path), wheel.sha256)
                        self.assertEqual(seen[-1], wheel.size)
                        self.assertEqual(seen, sorted(seen))
                    self.assertEqual(sorted(p.name for p in dest.iterdir()),
                                     sorted(wheel.filename for wheel in wheels))

                    bad = base / f"huella_{source.kind}"
                    for changed in (
                        dataclasses.replace(packages[1], sha256=_altered(packages[1].sha256)),
                        dataclasses.replace(packages[1], size=10),
                    ):
                        with self.assertRaises(messages.JobError) as caught:
                            runtime.fetch_wheel(changed, source, bad, cancelled=lambda: False)
                        self.assertEqual(caught.exception.code, "wheel_hash_mismatch")
                        self.assertEqual(caught.exception.values,
                                         {"file": wheels[1].filename})
                        self.assertEqual(list(bad.iterdir()), [], "no queda nada")

                    stop = base / f"cancelada_{source.kind}"
                    def raising() -> bool:
                        raise worker_api.JobCancelled("parar")
                    for check in (lambda: True, raising):
                        with self.assertRaises(worker_api.JobCancelled):
                            runtime.fetch_wheel(packages[0], source, stop, cancelled=check)
                        self.assertEqual(list(stop.iterdir()), [], "no queda nada")

            unreachable = base / "nas_caido"
            for folder in (base / "almacen_vacio", unreachable):
                if folder != unreachable:
                    folder.mkdir()
                with self.assertRaises(messages.JobError) as caught:
                    runtime.fetch_wheel(good[0], runtime.WheelSource.wheelhouse(folder),
                                        base / "nada", cancelled=lambda: False)
                self.assertEqual(caught.exception.code, "wheel_not_found")
                self.assertEqual(caught.exception.values,
                                 {"file": wheels[0].filename, "folder": str(folder)})
            for url in ((base / "no_existe.whl").as_uri(), FILES_URL.replace("https", "http")
                        + wheels[0].filename, "ftp://ejemplo/" + wheels[0].filename):
                with self.subTest(url=url):
                    package = dataclasses.replace(good[0], url=url)
                    with self.assertRaises(messages.JobError) as caught:
                        runtime.fetch_wheel(package, runtime.WheelSource.pypi(),
                                            base / "nada", cancelled=lambda: False)
                    self.assertEqual(caught.exception.code, "network_error")
                    self.assertEqual(caught.exception.values["package"], "gbtestpkg")
            self.assertFalse((base / "nada").exists() and any((base / "nada").iterdir()))
            self.assertEqual(calls, [], "ninguna rueda se busca en la red")

            requirements = runtime.write_requirements(good, base / "req" / "requirements.txt")
            self.assertEqual(requirements.read_bytes().decode("utf-8"), "".join(
                f"{p.name}=={p.version} --hash=sha256:{p.sha256}\n" for p in good))

        python, wheels_dir = Path(r"C:\py\python.exe"), Path(r"C:\t\out\wheels")
        requirements, target = Path(r"C:\t\out\requirements.txt"), Path(r"C:\r\x.partial\site")
        self.assertEqual(
            runtime.pip_install_command(python, wheels_dir, requirements, target),
            [str(python), "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index",
             "--find-links", str(wheels_dir), "--require-hashes", "--no-deps",
             "--only-binary=:all:", "--target", str(target), "--no-cache-dir",
             "--disable-pip-version-check", "--no-input", "--progress-bar", "off",
             "-r", str(requirements)],
        )


class InstallJobTest(unittest.TestCase):
    def test_both_sources_install_into_partial(self) -> None:
        """RF-004-21, RF-004-24: el trabajo ``runtime_install`` deja ``gbtestpkg`` 1.0.0 en
        ``runtime/<lock_id>.partial/site`` desde el almacén y desde la URL ``file://`` del
        lock, sin red y con ``PIP_REQUIRE_VIRTUALENV=1`` y ``PIP_USER=1`` en el entorno de
        Blender; borra antes la carpeta parcial de un intento cortado; no adopta el motor
        (sigue ``missing``) ni deja las ruedas copiadas; la salida de ``pip`` queda en
        ``job.log``. La petición no lleva rutas absolutas (van en ``--path``). Llamado
        directamente con esas variables en su entorno, ``run_pip_install`` instala igual
        (``--isolated``). Ninguno deja caché ni temporales de ``pip`` fuera de la carpeta
        del trabajo: ``TEMP`` queda vacío y los datos de usuario solo tienen la carpeta
        parcial."""
        for name, source in (("wheelhouse", "wheelhouse"), ("pypi", "pypi")):
            with self.subTest(name):
                case = _CASES[name]
                env, handle = case["env"], case["handle"]
                result = handle.result()
                self.assertEqual((result.state, result.error_code), ("succeeded", None),
                                 result.error_text)
                site = env.partial_path / "site"
                self.assertEqual(env.partial_path,
                                 case["user_dir"] / "runtime" / f"{env.lock_id}.partial")
                self.assertEqual(case["paths"]["runtime"], case["user_dir"] / "runtime")
                init = site / "gbtestpkg" / "__init__.py"
                self.assertIn('__version__ = "1.0.0"', init.read_text(encoding="utf-8"))
                self.assertTrue((site / "gbtestpkg-1.0.0.dist-info" / "RECORD").is_file())
                self.assertFalse((site / "resto.txt").exists(), "el intento anterior se borra")
                self.assertEqual([p.name for p in env.runtime_dir.iterdir()],
                                 [env.partial_path.name])
                self.assertEqual([p.name for p in case["user_dir"].iterdir()], ["runtime"])
                self.assertEqual(env.status(), "missing", "instalar no adopta el motor")
                self.assertFalse((handle.job_dir.outputs_dir / "wheels").exists())
                summary = _summary(handle)
                self.assertEqual((summary["lock_id"], summary["source"]),
                                 (env.lock_id, source))
                self.assertEqual(summary["packages"], [
                    {"name": "gbtestpkg", "version": "1.0.0",
                     "sha256": env.lock.packages[0].sha256}])
                log = handle.job_dir.log_file.read_text(encoding="utf-8", errors="replace")
                self.assertIn("Successfully installed gbtestpkg-1.0.0", log)
                stored = json.loads(handle.job_dir.path.joinpath("request.json")
                                    .read_text(encoding="utf-8"))
                absolute = [text for text in _strings(stored["params"]) if ABSOLUTE.match(text)]
                self.assertEqual(absolute, [], "las rutas van en la línea de órdenes")
        self.assertEqual(_CASES["wheelhouse"]["paths"]["wheelhouse"], _STATE["store"])
        self.assertNotIn("wheelhouse", _CASES["pypi"]["paths"])
        self.check_command_paths()

        self.assertIsNone(_STATE.get("direct_error"))
        self.assertEqual(_STATE["direct_environ"], PIP_ENVIRONMENT)
        init = _STATE["direct_target"] / "gbtestpkg" / "__init__.py"
        self.assertIn('__version__ = "1.0.0"', init.read_text(encoding="utf-8"))
        self.assertEqual(list(_STATE["temp"].iterdir()), [], "pip no deja nada en TEMP")

    def check_command_paths(self) -> None:
        """Las rutas del trabajo en la orden (``--path``, por nombre), las que no valen al
        lanzarlo y un ``--path`` mal formado en el arranque (salida 5)."""
        interp = interpreter.resolve_interpreter("blender", blender_python=Path(sys.executable),
                                                 runtime=None, external_python=None)
        folder, store = Path(r"C:\datos\runtime"), Path(r"D:\almacen")
        command = interpreter.build_command(interp, package_dir=EXTENSION_DIR,
                                            job_dir=Path(r"C:\cache\jobs\x"),
                                            paths={"wheelhouse": store, "runtime": folder})
        self.assertEqual(command[-4:], ["--path", f"runtime={folder}",
                                        "--path", f"wheelhouse={store}"])
        launcher = _STATE["runner"]
        request = _CASES["wheelhouse"]["request"]
        before = sorted(p.name for p in launcher.jobs_root.iterdir())
        for bad in ({"Runtime": folder}, {"runtime": Path("relativa")}, {"runtime": 3}):
            with self.subTest(paths=bad), self.assertRaises(ValueError):
                launcher.submit(dataclasses.replace(request, job_uid=protocol.new_request(
                    "runtime_install", label="x", owner="jobs").job_uid), paths=bad)
        self.assertEqual(sorted(p.name for p in launcher.jobs_root.iterdir()), before)
        run = _STATE["bad_path"]
        self.assertEqual(run.returncode, 5)
        self.assertIn("--path 'runtime' no es <nombre>=<ruta>", run.log)


class InstallFailureTest(unittest.TestCase):
    def test_hash_mismatch_and_cancel_leave_no_engine(self) -> None:
        """RF-004-21: con la huella de ``gbtestdos`` alterada en el lock, el trabajo queda
        «Fallido» con ``wheel_hash_mismatch`` y el fichero, sin lanzar ``pip``: no queda
        nada en ``.partial`` (tampoco la del intento anterior) ni las ruedas ya copiadas.
        Cancelado mientras ``pip`` instala, queda «Cancelado» sin forzar, sin carpeta
        ``.partial`` ni ``site/`` usable. En los dos, el motor sigue ``missing``."""
        case = _CASES["hash"]
        env, handle = case["env"], case["handle"]
        result = handle.result()
        self.assertEqual((result.state, result.error_code), ("failed", "wheel_hash_mismatch"))
        wheel = next(w for w in _STATE["wheels"] if w.name == "gbtestdos")
        self.assertIn(wheel.filename, result.error_text)
        self.assertFalse(case["stale"].exists(), "no queda nada en .partial")
        self.assertEqual(list(env.runtime_dir.iterdir()) if env.runtime_dir.exists() else [],
                         [])
        self.assertFalse((handle.job_dir.outputs_dir / "wheels").exists(),
                         "las ruedas copiadas se borran")
        self.assertFalse((handle.job_dir.outputs_dir / "requirements.txt").exists(),
                         "pip no llega a lanzarse")
        self.assertEqual(env.status(), "missing")

        case = _CASES["cancel"]
        env, handle = case["env"], case["handle"]
        self.assertEqual(_STATE.get("cancel_message"), runtime.INSTALLING_TEXT)
        self.assertTrue(_STATE.get("cancel_sent"))
        result = handle.result()
        self.assertEqual(result.state, "cancelled", result.error_text)
        record = json.loads(handle.job_dir.path.joinpath("state.json")
                            .read_text(encoding="utf-8"))
        self.assertFalse(record["cancel"]["forced"], "el worker atiende la cancelación")
        self.assertEqual(record["exit_code"], 3)
        self.assertFalse(env.partial_path.exists(), "no queda ningún site/ a medias")
        self.assertFalse(env.path.exists())
        self.assertEqual(env.status(), "missing")
        self.assertFalse((handle.job_dir.outputs_dir / "wheels").exists())


if __name__ == "__main__":
    unittest.main()
