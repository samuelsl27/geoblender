# SPDX-License-Identifier: GPL-3.0-or-later
"""Verificación y adopción del motor de cálculo y limpieza de los motores anteriores
(spec 004, T28 y T29; HU-004-3; RF-004-21, RF-004-22, RF-004-25, RF-004-27; plan 004 §5.2.6,
§5.3.1 y §5.4.7).

- El trabajo ``runtime_check`` (``workers/runtime_check.py``, entorno ``compute``) llama a
  ``runtime.probe_environment`` sobre una carpeta ``site`` que le llega por la línea de
  órdenes: la versión de cada paquete del lock (``importlib.metadata``), que numpy se carga
  desde esa carpeta y no desde Blender, su BLAS (no ``auto``), los s del producto
  2000 × 2000 y la longitud máxima de ruta. Si algo no cumple, queda «Fallido» con el
  mensaje del §8 (``runtime_package_mismatch``, ``runtime_blas_missing``…).
- ``runtime.RuntimeSetup.install``: la cadena instalar → verificar → adoptar en el lanzador.
  Verifica la carpeta ``<lock_id>.partial/site`` (``site_override``) y solo si pasa la
  adopta (``ComputeEnvironment.adopt``: ``runtime.json`` con el origen, el consentimiento y la
  verificación, y ``os.replace(<lock_id>.partial → <lock_id>)``). Si la verificación falla,
  borra la carpeta parcial y el motor sigue sin instalar.
- ``runtime.RuntimeSetup.verify``: verifica el motor instalado; si falla (una versión
  cambiada en ``site/``), lo anota en ``runtime.json`` y el motor queda ``broken``: los
  trabajos que lo necesitan no se lanzan.
- Con otro lock (una versión nueva de Geoblender), el motor del lock vigente falta y queda el
  anterior: estado ``outdated``. ``ComputeEnvironment.remove_stale`` borra los motores de
  otros locks solo cuando el vigente está listo y ningún trabajo los usa (los ``lock_id`` de
  ``JobRunner.locks_in_use`` y, desde cualquier sesión, el numpy del motor que el worker
  ``compute`` tiene abierto); la cadena de instalación la llama al adoptar.

Motor sintético: un «numpy» de pruebas (``numpy/__init__.py`` con ``__version__``,
``show_config`` y un producto de matrices de mentira) y ``gbtestpkg`` en ruedas sintéticas,
instaladas con el ``pip`` del Python de Blender desde un almacén temporal (sin red). Todo se
lanza a la vez al empezar (``setUpModule``) y cada prueba mira lo que dejó lo suyo.
"""

import json
import os
import sys
import time
import unittest
import zipfile
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

HEADER = {"schema": "geoblender.runtime_lock/1", "python": "3.13", "platform": "win_amd64"}
FILES_URL = "https://files.pythonhosted.org/packages/aa/bb/"
NUMPY_VERSION = "9.8.7"
GOOD_BLAS = "scipy-openblas"
FAKE_NUMPY = '''"""numpy sintético de las pruebas: lo justo para verificar un motor."""

__version__ = "{version}"
float64 = float


class _Matrix:
    def __init__(self, n):
        self.shape = (n, n)

    def __matmul__(self, other):
        return _Matrix(self.shape[0])


def ones(shape, dtype=None):
    return _Matrix(shape[0])


def show_config(mode="stdout"):
    return {{"Build Dependencies": {{"blas": {{"name": "{blas}"}}}}}}
'''
CONSENT = {"user": "ana", "host": "PC-PRUEBAS"}
DEADLINE_S = 60.0
POLL_S = 0.02
HOLD_PARAMS = {"op": "chunked_sum", "n": 1, "chunks": 2, "sleep_s": 30.0}
"""Un autodiagnóstico ``compute`` que espera en su primer trozo (sin usar numpy) hasta que se
cancela: un trabajo que usa el motor anterior."""
THIRD_LOCK_ID = "abcdefabcdef"
"""Un lock de otra versión del que solo queda una instalación a medias."""
IDLE_LOCK_ID = "0123456789ab"
"""Un lock de otra versión con su motor, que ningún trabajo tiene abierto."""
LEFTOVER_LOCK_ID = "fedcba987654"
"""Un lock de otra versión del que quedan los restos ``.old`` de una limpieza anterior."""

_CASES: dict[str, dict] = {}
_STATE: dict[str, object] = {}
_TWO: dict[str, object] = {}


def _wheels(store: Path, blas: str) -> list:
    """El «numpy» sintético con la BLAS ``blas`` y ``gbtestpkg`` en ``store``."""
    source = FAKE_NUMPY.format(version=NUMPY_VERSION, blas=blas)
    return [
        _support.make_wheel(store, name="numpy", version=NUMPY_VERSION,
                            extra_files={"numpy/__init__.py": source}),
        _support.make_wheel(store),
    ]


def _lock(wheels: list):
    packages = [{
        "name": wheel.name,
        "version": wheel.version,
        "filename": wheel.filename,
        "url": FILES_URL + wheel.filename,
        "sha256": wheel.sha256,
        "size": wheel.size,
        "installed_size": 1_000_000,
        "license": "MIT",
        "bundled_licenses": [],
        "required_by": ["004"],
    } for wheel in wheels]
    return runtime.parse_lock(dict(HEADER, package=packages))


def _unpack(wheels: list, site: Path) -> Path:
    """Un motor hecho a mano: las ruedas descomprimidas en ``site`` (lo que deja ``pip``)."""
    site.mkdir(parents=True)
    for wheel in wheels:
        with zipfile.ZipFile(wheel.path) as archive:
            archive.extractall(site)
    return site


def _passing_check(lock, **changes) -> dict:
    """El resumen de una verificación que pasó (el de ``runtime_check``), con ``changes``."""
    check = {
        "lock_id": lock.lock_id,
        "ok": True,
        "checked_at": "2026-10-07T10:00:00.000Z",
        "python": "3.13.9",
        "packages": [{"name": p.name, "locked": p.version, "installed": p.version}
                     for p in lock.packages],
        "numpy": NUMPY_VERSION,
        "numpy_in_site": True,
        "blas": GOOD_BLAS,
        "matmul_n": 2000,
        "matmul_repeats": 3,
        "matmul_s": 0.04,
        "longest_relative": 30,
        "max_path_length": 120,
        "problems": [],
    }
    check.update(changes)
    return check


def _plan_and_consent(env, store: Path):
    plan = env.plan_install(runtime.WheelSource.wheelhouse(store), online_access=False)
    return plan, runtime.Consent.given(plan, **CONSENT)


def _launcher(base: Path, env):
    return runner.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                            blender_python=Path(sys.executable), runtime=env)


def _set_version(site: Path, name: str, old: str, new: str) -> None:
    """Cambia en ``site`` la versión que declara el paquete ``name`` (su ``METADATA``)."""
    metadata = site / f"{name}-{old}.dist-info" / "METADATA"
    text = metadata.read_text(encoding="utf-8")
    metadata.write_text(text.replace(f"Version: {old}", f"Version: {new}"), encoding="utf-8")


def _install_by_hand(env, wheels: list, store: Path) -> tuple:
    """Un motor instalado y adoptado sin ``pip`` (las ruedas descomprimidas en la carpeta
    parcial y ``adopt`` con una verificación que pasó). Devuelve su plan y su
    consentimiento."""
    plan, consent = _plan_and_consent(env, store)
    _unpack(wheels, env.staged_site)
    env.adopt(env.staged_site, _passing_check(env.lock), plan, consent)
    return plan, consent


def _names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def _start_two_locks(base: Path, wheels: list, store: Path) -> None:
    """Dos locks en los mismos datos de usuario: el motor de la versión anterior (solo
    numpy), instalado, con un trabajo ``compute`` que lo usa; el de la versión nueva (numpy y
    ``gbtestpkg``), aún sin instalar. Al acabar el trabajo, su ``on_finish`` limpia."""
    user = base / "usuario_dos_locks"
    old = runtime.ComputeEnvironment(user, _lock(wheels[:1]))
    new = runtime.ComputeEnvironment(user, _lock(wheels))
    _install_by_hand(old, wheels[:1], store)
    for name in (f"{THIRD_LOCK_ID}.partial", IDLE_LOCK_ID, f"{LEFTOVER_LOCK_ID}.old", "notas"):
        (old.runtime_dir / name / "site").mkdir(parents=True)
        (old.runtime_dir / name / "site" / "dato.txt").write_text("x\n", encoding="utf-8")
    launcher = _launcher(base, old)
    unittest.addModuleCleanup(launcher.shutdown)
    request = protocol.new_request("selftest", label="Usa el motor anterior", owner="jobs",
                                   params=HOLD_PARAMS, environment="compute")

    def at_end(result) -> None:
        _TWO["result"] = result
        _TWO["in_use_at_end"] = launcher.locks_in_use()
        _TWO["removed_at_end"] = new.remove_stale(in_use=launcher.locks_in_use())

    _TWO.update(old=old, new=new, runner=launcher, wheels=wheels, store=store,
                handle=launcher.submit(request, on_finish=at_end))


def _step_two_locks() -> None:
    """En cuanto el trabajo ya usa el motor anterior (su evento ``start`` llega después de
    cargar numpy): lo que ve el lock nuevo sin instalar, su instalación y las limpiezas con el
    trabajo en marcha; después lo cancela."""
    launcher = _TWO["runner"]
    launcher.poll()
    if "kept_held" in _TWO:
        return
    (snapshot,) = launcher.snapshots()
    if snapshot.interpreter is None or snapshot.interpreter.python is None:
        return
    old, new = _TWO["old"], _TWO["new"]
    _TWO["new_before"] = new.status()
    try:
        _resolve(new)
    except messages.JobError as exc:
        _TWO["resolve_before"] = exc.code
    _TWO["sweep_before"] = new.remove_stale(in_use=set())
    _TWO["in_use"] = launcher.locks_in_use()
    _install_by_hand(new, _TWO["wheels"], _TWO["store"])
    _TWO["kept_in_use"] = new.remove_stale(
        in_use=_TWO["in_use"] | {IDLE_LOCK_ID, LEFTOVER_LOCK_ID})
    _TWO["names_kept"] = _names(new.runtime_dir)
    _TWO["kept_held"] = new.remove_stale(in_use=set())
    _TWO["names_while_running"] = _names(new.runtime_dir)
    _TWO["old_while_running"] = old.status()
    _TWO["handle"].cancel()


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    catalog.register_builtin_workers()
    temp = base / "temp"
    temp.mkdir()
    environ = mock.patch.dict(os.environ, {"TEMP": str(temp), "TMP": str(temp)})
    environ.start()
    unittest.addModuleCleanup(environ.stop)

    good_store, auto_store = base / "almacen", base / "almacen_auto"
    good, auto = _wheels(good_store, GOOD_BLAS), _wheels(auto_store, "auto")
    _STATE.update(base=base, good_store=good_store, good_wheels=good)
    _start_two_locks(base, good, good_store)

    # En los datos de usuario de «ok» queda el motor de un lock anterior, que nadie usa.
    previous = runtime.ComputeEnvironment(base / "usuario_ok", _lock(good[:1]))
    _install_by_hand(previous, good[:1], good_store)
    _STATE["ok_previous"] = previous
    for name, wheels, store in (("ok", good, good_store), ("auto", auto, auto_store)):
        env = runtime.ComputeEnvironment(base / f"usuario_{name}", _lock(wheels))
        _STATE[f"{name}_before"] = env.status()
        plan, consent = _plan_and_consent(env, store)
        done: list = []
        launcher = _launcher(base, env)
        setup = runtime.RuntimeSetup.install(launcher, env, plan, consent, on_done=done.append)
        _CASES[name] = dict(env=env, plan=plan, consent=consent, runner=launcher,
                            setup=setup, done=done, store=store)

    # Un motor ya adoptado al que se le cambia la versión de un paquete en site/.
    env = runtime.ComputeEnvironment(base / "usuario_alterado", _lock(good))
    plan, consent = _install_by_hand(env, good, good_store)
    _STATE["altered_before"] = env.status()
    _set_version(env.site_dir(), "gbtestpkg", "1.0.0", "1.0.1")
    _STATE["altered_untouched"] = env.status()
    launcher = _launcher(base, env)
    done = []
    setup = runtime.RuntimeSetup.verify(launcher, env, on_done=done.append)
    _CASES["altered"] = dict(env=env, plan=plan, consent=consent, runner=launcher,
                             setup=setup, done=done)

    deadline = time.monotonic() + DEADLINE_S
    ok = _CASES["ok"]
    while not (all(case["setup"].done for case in _CASES.values()) and "result" in _TWO):
        if time.monotonic() > deadline:
            pending = [name for name, case in _CASES.items() if not case["setup"].done]
            raise AssertionError(f"no terminaron a tiempo: {pending} (dos locks: "
                                 f"{'result' in _TWO})")
        for case in _CASES.values():
            case["runner"].poll()
        _step_two_locks()
        if ok["setup"].step == runtime.STEP_CHECK and ok["env"].partial_path.exists():
            _STATE.setdefault("status_while_checking", ok["env"].status())
        time.sleep(POLL_S)


def _results(case: dict) -> list:
    return [handle.result() for handle in case["setup"].handles]


def _record(result) -> dict:
    return json.loads(result.job_dir.path.joinpath("state.json").read_text(encoding="utf-8"))


def _runtime_json(env) -> dict:
    return json.loads((env.path / "runtime.json").read_text(encoding="utf-8"))


def _resolve(env):
    return interpreter.resolve_interpreter("compute", blender_python=Path(sys.executable),
                                           runtime=env, external_python=None)


# Cuatro pruebas con varias comprobaciones cada una: hasta 004/T39, tools/check.py repartía
# las unitarias por número de pruebas (gbtools.parts; docs/trampas.md §4).
class AdoptChainTest(unittest.TestCase):
    def test_install_verify_and_adopt(self) -> None:
        """RF-004-21, RF-004-22, RF-004-27: la cadena instala en ``<lock_id>.partial/site``,
        verifica esa carpeta en un trabajo ``compute`` aparte (numpy del lock cargado desde
        ella, BLAS distinta de ``auto``, s del 2000 × 2000, longitud máxima de ruta) y solo
        entonces la adopta con ``os.replace``: el motor queda ``ready`` sin carpeta parcial, y
        mientras se verificaba seguía ``outdated`` (había el motor de un lock anterior; la
        carpeta parcial nunca se usa). Al adoptar borra ese motor anterior, que nadie usaba.
        ``runtime.json`` registra el lock, los paquetes con su versión y su huella, el
        origen, el consentimiento (usuario, equipo, fecha y huella del plan) y la
        verificación. Los trabajos ``compute`` usan ya su ``site``."""
        case = _CASES["ok"]
        env, setup = case["env"], case["setup"]
        self.assertEqual((setup.kind, setup.state, setup.error_code),
                         ("install", "succeeded", None), setup.error_text)
        self.assertEqual(case["done"], [setup], "on_done se llama una vez, al acabar")
        install, check = _results(case)
        self.assertEqual([r.state for r in (install, check)], ["succeeded", "succeeded"])
        self.assertEqual(setup.job_uids, (install.job_uid, check.job_uid))
        self.assertEqual((_STATE["ok_before"], _STATE.get("status_while_checking")),
                         ("outdated", "outdated"))

        self.assertEqual(env.status(), "ready")
        self.assertFalse(env.partial_path.exists(), "no queda carpeta parcial")
        previous = _STATE["ok_previous"]
        self.assertNotEqual(previous.lock_id, env.lock_id)
        self.assertEqual(setup.removed, (previous.path,), "borra el motor anterior")
        self.assertEqual([p.name for p in env.runtime_dir.iterdir()], [env.lock_id])
        self.assertEqual(previous.status(), "outdated", "visto desde la versión anterior")
        site = env.site_dir()
        self.assertIn(f'__version__ = "{NUMPY_VERSION}"',
                      (site / "numpy" / "__init__.py").read_text(encoding="utf-8"))
        self.assertTrue((site / "gbtestpkg-1.0.0.dist-info" / "METADATA").is_file())
        interp = _resolve(env)
        self.assertEqual((interp.kind, interp.site, interp.lock_id),
                         ("compute", site, env.lock_id))

        summary = setup.check
        self.assertEqual(summary, check.summary)
        self.assertEqual((summary["lock_id"], summary["ok"], summary["problems"]),
                         (env.lock_id, True, []))
        self.assertEqual(summary["packages"], [
            {"name": "numpy", "locked": NUMPY_VERSION, "installed": NUMPY_VERSION},
            {"name": "gbtestpkg", "locked": "1.0.0", "installed": "1.0.0"}])
        self.assertEqual((summary["numpy"], summary["numpy_in_site"], summary["blas"]),
                         (NUMPY_VERSION, True, GOOD_BLAS))
        self.assertEqual((summary["matmul_n"], summary["matmul_repeats"]), (2000, 3))
        self.assertGreaterEqual(summary["matmul_s"], 0.0)
        record = _record(check)
        self.assertEqual(record["interpreter"]["kind"], "compute")
        self.assertEqual(record["interpreter"]["lock_id"], env.lock_id)
        log = check.job_dir.log_file.read_text(encoding="utf-8", errors="replace")
        self.assertIn(f"(--site): {env.staged_site}", log, "verifica la carpeta parcial")
        request = json.loads(check.job_dir.path.joinpath("request.json")
                             .read_text(encoding="utf-8"))
        self.assertNotIn(str(case["store"]), json.dumps(request), "rutas por --path")

        info = _runtime_json(env)
        self.assertEqual((info["schema"], info["lock_id"]), ("geoblender.runtime/1",
                                                              env.lock_id))
        self.assertEqual(info["packages"], [
            {"name": p.name, "version": p.version, "sha256": p.sha256}
            for p in env.lock.packages])
        self.assertEqual(info["source"], {"kind": "wheelhouse", "folder": str(case["store"])})
        self.assertEqual(info["consent"], case["consent"].to_json())
        self.assertEqual(info["plan_digest"], case["plan"].digest)
        verification = info["verification"]
        self.assertIs(verification["ok"], True)
        for key in ("checked_at", "python", "numpy", "numpy_in_site", "blas", "matmul_n",
                    "matmul_repeats", "matmul_s"):
            self.assertEqual(verification[key], summary[key], key)
        longest = max(len(str(path)) for path in site.rglob("*"))
        self.assertEqual(verification["max_path_length"], longest, "medida en la final")


class VerificationGateTest(unittest.TestCase):
    def test_only_a_passing_verification_is_adopted(self) -> None:
        """RF-004-21, RF-004-22, RF-004-25: con un numpy cuya BLAS es ``auto``, la
        verificación falla con ``runtime_blas_missing`` y la cadena no adopta nada: borra la
        carpeta parcial y el motor sigue ``missing``. ``adopt`` rechaza, sin tocar nada, una
        verificación que no pasó, de otro lock o con otra versión, un consentimiento de otro
        plan y otra carpeta que la parcial. Una carpeta ``.partial`` completa, con su
        ``runtime.json`` correcto, nunca se usa: el motor sigue ``missing``, los trabajos
        ``compute`` no se lanzan y no se puede verificar (``submit`` tampoco admite una
        carpeta ``site`` relativa). Reparar adopta sobre un motor ``broken`` del mismo lock
        sin dejar restos."""
        case = _CASES["auto"]
        env, setup = case["env"], case["setup"]
        self.assertEqual((setup.state, setup.error_code), ("failed", "runtime_blas_missing"))
        self.assertIn("auto", setup.error_text)
        self.assertEqual(case["done"], [setup])
        install, check = _results(case)
        self.assertEqual((install.state, check.state, check.error_code),
                         ("succeeded", "failed", "runtime_blas_missing"))
        self.assertIsNone(setup.check)
        self.assertEqual(env.status(), "missing")
        self.assertFalse(env.partial_path.exists(), "se borra la carpeta parcial")
        self.assertFalse(env.path.exists())

        base, store, wheels = _STATE["base"], _STATE["good_store"], _STATE["good_wheels"]
        env = runtime.ComputeEnvironment(base / "usuario_puerta", _lock(wheels))
        plan, consent = _plan_and_consent(env, store)
        staged = _unpack(wheels, env.staged_site)
        other_plan = env.plan_install(runtime.WheelSource.pypi(), online_access=True)
        refused = {
            "no pasó": (staged, _passing_check(env.lock, ok=False), consent),
            "otro lock": (staged, _passing_check(env.lock, lock_id="0" * 12), consent),
            "otra versión": (staged, _passing_check(env.lock, packages=[
                {"name": "numpy", "locked": NUMPY_VERSION, "installed": NUMPY_VERSION},
                {"name": "gbtestpkg", "locked": "1.0.0", "installed": "1.0.1"}]), consent),
            "consentimiento de otro plan": (staged, _passing_check(env.lock),
                                            runtime.Consent.given(other_plan, **CONSENT)),
            "otra carpeta": (env.path / "site", _passing_check(env.lock), consent),
        }
        for label, (folder, check_data, given) in refused.items():
            with self.subTest(label), self.assertRaises(ValueError):
                env.adopt(folder, check_data, plan, given)
            self.assertFalse(env.path.exists())
            self.assertTrue((staged / "numpy" / "__init__.py").is_file())

        (env.partial_path / "runtime.json").write_text(json.dumps({
            "schema": runtime.RUNTIME_SCHEMA, "lock_id": env.lock_id,
            "verification": {"ok": True}}), encoding="utf-8")
        self.assertEqual(env.status(), "missing", "una carpeta .partial nunca se usa")
        with self.assertRaises(messages.JobError) as caught:
            _resolve(env)
        self.assertEqual(caught.exception.code, "runtime_missing")
        launcher = _launcher(base, env)
        with self.assertRaises(messages.JobError) as caught:
            runtime.RuntimeSetup.verify(launcher, env)
        self.assertEqual(caught.exception.code, "runtime_missing")
        jobs = sorted(p.name for p in launcher.jobs_root.iterdir())
        with self.assertRaises(ValueError):
            launcher.submit(env.verify_request(staged_site=staged), paths={"site": staged},
                            site_override=Path("relativa"))
        self.assertEqual(sorted(p.name for p in launcher.jobs_root.iterdir()), jobs)
        (env.partial_path / "runtime.json").unlink()

        old = env.site_dir() / "viejo.txt"
        old.parent.mkdir(parents=True)
        old.write_text("motor roto\n", encoding="utf-8")
        (env.path / "runtime.json").write_text(json.dumps({
            "schema": runtime.RUNTIME_SCHEMA, "lock_id": env.lock_id,
            "verification": {"ok": False}}), encoding="utf-8")
        self.assertEqual(env.status(), "broken")
        env.adopt(staged, _passing_check(env.lock), plan, consent)
        self.assertEqual(env.status(), "ready")
        self.assertFalse(old.exists(), "el motor roto se sustituye entero")
        self.assertEqual([p.name for p in env.runtime_dir.iterdir()], [env.lock_id])


class BrokenEngineTest(unittest.TestCase):
    def test_altered_version_leaves_it_broken(self) -> None:
        """RF-004-22, RF-004-25: con la versión de ``gbtestpkg`` cambiada en el ``site/`` de
        un motor ``ready``, la verificación (``RuntimeSetup.verify``, sobre la carpeta del
        motor) falla con ``runtime_package_mismatch`` (paquete, versión real y la del lock);
        se anota en ``runtime.json``, que conserva el origen y el consentimiento, y el motor
        queda ``broken``: los trabajos ``compute`` no se lanzan hasta repararlo."""
        case = _CASES["altered"]
        env, setup = case["env"], case["setup"]
        self.assertEqual((_STATE["altered_before"], _STATE["altered_untouched"]),
                         ("ready", "ready"), "solo la verificación lo detecta")
        self.assertEqual((setup.kind, setup.state, setup.error_code),
                         ("verify", "failed", "runtime_package_mismatch"))
        for text in ("gbtestpkg", "1.0.1", "1.0.0"):
            self.assertIn(text, setup.error_text)
        self.assertEqual(case["done"], [setup])
        (check,) = _results(case)
        self.assertEqual((check.state, check.error_code),
                         ("failed", "runtime_package_mismatch"))
        log = check.job_dir.log_file.read_text(encoding="utf-8", errors="replace")
        self.assertIn(f"(--site): {env.site_dir()}", log, "verifica el motor instalado")

        self.assertEqual(env.status(), "broken")
        with self.assertRaises(messages.JobError) as caught:
            _resolve(env)
        self.assertEqual(caught.exception.code, "runtime_missing")
        info = _runtime_json(env)
        self.assertEqual(info["consent"], case["consent"].to_json())
        self.assertEqual(info["source"]["kind"], "wheelhouse")
        verification = info["verification"]
        self.assertIs(verification["ok"], False)
        self.assertEqual(verification["code"], "runtime_package_mismatch")
        self.assertEqual(verification["text"], setup.error_text)
        self.assertNotEqual(verification["checked_at"], "2026-10-07T10:00:00.000Z")


class StaleEngineTest(unittest.TestCase):
    def test_previous_engine_kept_while_in_use(self) -> None:
        """RF-004-27: con dos locks en los mismos datos de usuario y sin el motor del lock
        vigente, el estado es ``outdated``, los trabajos ``compute`` no se lanzan
        (``runtime_missing``) y la limpieza no borra nada. Instalado el nuevo, la limpieza no
        borra los motores de los ``lock_id`` en uso (``JobRunner.locks_in_use`` y los que se
        le digan); sin ellos, borra el motor que nadie usa y los restos ``.old`` de su lock,
        pero el anterior se conserva mientras un trabajo ``compute`` lo usa, aunque no se
        diga (el worker tiene abierto el numpy del motor y Windows no deja apartar la
        carpeta, como pasaría con un trabajo de otra sesión de Blender). Al terminar el
        trabajo, la limpieza lo borra sin dejar restos. Una instalación a medias de otro
        lock y lo que no es un motor no se tocan."""
        two = _TWO
        old, new = two["old"], two["new"]
        self.assertNotEqual(old.lock_id, new.lock_id)
        self.assertEqual((two["new_before"], two.get("resolve_before")),
                         ("outdated", "runtime_missing"))
        self.assertEqual(two["sweep_before"], [], "sin el motor nuevo no se borra nada")
        self.assertEqual(two["in_use"], {old.lock_id})
        others = [f"{THIRD_LOCK_ID}.partial", "notas"]
        idle = [IDLE_LOCK_ID, f"{LEFTOVER_LOCK_ID}.old"]
        self.assertEqual(two["kept_in_use"], [], "los lock_id en uso no se tocan")
        self.assertEqual(two["names_kept"], sorted([old.lock_id, new.lock_id, *others, *idle]))
        self.assertEqual(two["kept_held"], [new.runtime_dir / name for name in idle])
        self.assertEqual(two["names_while_running"],
                         sorted([old.lock_id, new.lock_id, *others]))
        self.assertEqual(two["old_while_running"], "ready")

        result = two["result"]
        self.assertEqual(result.state, "cancelled", result.error_text)
        interp = _record(result)["interpreter"]
        self.assertEqual((interp["kind"], interp["lock_id"]), ("compute", old.lock_id))
        self.assertEqual(two["in_use_at_end"], set())
        self.assertEqual(two["removed_at_end"], [old.path])
        self.assertEqual(_names(new.runtime_dir), sorted([new.lock_id, *others]))
        self.assertEqual((new.status(), old.status()), ("ready", "outdated"))
        self.assertEqual(new.remove_stale(in_use=set()), [], "ya no queda nada que borrar")
        with self.assertRaises(TypeError):
            new.remove_stale(in_use=old.lock_id)


if __name__ == "__main__":
    unittest.main()
