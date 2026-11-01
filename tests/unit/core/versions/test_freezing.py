# SPDX-License-Identifier: GPL-3.0-or-later
"""Las congelaciones en curso de este proceso, en un módulo ligero (spec 009, T39; RNF-008-12,
RF-009-07, RF-008-22; plan 009 A6).

``core.versions.freeze.freeze_steps`` anota en ``core.versions.freezing`` la carpeta temporal de
la congelación que copia (``snapshots/V01.r1.congelando-<8 hex>``) con la raíz de su proyecto y
su sesión, y el barrido de restos de la comprobación de apertura (``core.datasets.orphans``) no
aparta las de su sesión. El paso de «restos» corre en un tic de ≤ 20 ms (RNF-008-12): leer ese
registro no puede importar ``core.versions.freeze``, que arrastra ``provenance.lineage`` y
``recompute`` (42–54 ms en frío; F-4 de la verificación de la 009):

- en un proceso nuevo, importar ``core.versions.freezing`` no carga ningún otro módulo de
  Geoblender, y el barrido entero (con un resto en ``snapshots/``, que aparta) no importa
  ninguno que la comprobación de apertura (``core.provenance.checks``) no tenga ya cargado
  (``sys.modules`` antes y después);
- el registro: lo de una sesión, solo para ella y en su proyecto (la raíz, normalizada), y
  quitarlo dos veces no falla;
- el registro de las comprobaciones de los módulos al congelar (spec 012, T38; RNF-001-03), que
  vive aquí para que habilitar la extensión no cargue ``core.versions.freeze``: su API sigue
  siendo la de ``core.versions.freeze`` (las mismas funciones), registrar dos veces lo mismo no
  repite, se llaman en el orden en que se registraron, se quitan por módulo y un argumento mal
  dado se rechaza.

Datos solo sintéticos.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from tests.support.package import PACKAGE_NAME, import_geoblender
from tests.support.repo import ROOT
from tests.support.trees import child_env, child_temp

LEFTOVER = "snapshots/V01.r1.congelando-0a1b2c3d"
"""La temporal de una congelación que no terminó, que el barrido aparta."""

# El hijo, en un proceso nuevo: (1) lo que carga importar el registro, con su paquete ya
# cargado; (2) con la comprobación de apertura importada y un proyecto nuevo con un resto en
# snapshots/, lo que carga el barrido de restos entero y lo que aparta.
CHILD = r"""
import json, os, sys, tempfile, time
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from tests.support.package import PACKAGE_NAME, import_geoblender

def loaded():
    return {name for name in sys.modules
            if name == PACKAGE_NAME or name.startswith(PACKAGE_NAME + ".")}

found = {}
import_geoblender("core.versions")
before = loaded()
try:
    import_geoblender("core.versions.freezing")
except ImportError as exc:
    found["light"] = f"{type(exc).__name__}: {exc}"
else:
    found["light"] = sorted(loaded() - before)

import_geoblender("core.provenance.checks")
orphans = import_geoblender("core.datasets.orphans")
create = import_geoblender("core.project.create")
userdata = import_geoblender("core.userdata")
from tests.support.core_fixtures import make_session, make_settings

tmp = Path(tempfile.mkdtemp(prefix="gb-t39-"))
(tmp / "p").mkdir()
project = create.create_project(tmp / "p", make_settings(), make_session(),
                                userdata.UserData(tmp / "u")).project
leftover = Path(project.root, *sys.argv[2].split("/"), "manifest.json")
leftover.parent.mkdir(parents=True)
leftover.write_bytes(b"{}")
old = time.time_ns() - 3600 * 10**9
os.utime(leftover, ns=(old, old))
before = loaded()
*_, last = orphans.orphan_steps(project, write=True)
found["tic"] = sorted(loaded() - before)
found["moved"] = [item.path for item in last.result.moved]
project.close()
print(json.dumps(found))
"""


def _freezing() -> ModuleType:
    return import_geoblender("core.versions.freezing")


class SweepImportsTest(unittest.TestCase):
    """El hijo (:data:`CHILD`), una vez para las dos pruebas."""

    found: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        flags = ["-B", "-s", "-X", "utf8", *(["-S"] if sys.flags.no_site else [])]
        with child_temp() as temp:
            done = subprocess.run(
                [sys.executable, *flags, "-c", CHILD, str(ROOT), LEFTOVER],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=child_env(None, temp), timeout=120, check=False,
            )
        if done.returncode != 0:
            raise AssertionError(f"el proceso hijo falló ({done.returncode}): {done.stderr}")
        cls.found = json.loads(done.stdout)

    def test_registry_is_light(self) -> None:
        """RNF-008-12, RF-009-07: en un proceso nuevo, importar ``core.versions.freezing``
        (el registro de las congelaciones en curso) no carga ningún otro módulo de
        Geoblender."""
        self.assertEqual(self.found["light"], [f"{PACKAGE_NAME}.core.versions.freezing"])

    def test_sweep_imports_nothing_in_its_tic(self) -> None:
        """RNF-008-12, RF-008-22 (F-4 de la verificación de la 009): en un proceso nuevo, con
        la comprobación de apertura importada, el barrido de restos entero —que aparta la
        temporal de una congelación que no terminó— no importa ningún módulo de Geoblender:
        tampoco ``core.versions.freeze`` (ni ``provenance.lineage`` ni ``recompute``), que en
        frío retenía su tic 42–54 ms (≤ 20 ms)."""
        self.assertEqual(self.found["moved"], [LEFTOVER])
        self.assertEqual(self.found["tic"], [])


class RegistryTest(unittest.TestCase):
    def project(self, root: str | Path, session: str = "s1") -> Any:
        return SimpleNamespace(root=root, session=SimpleNamespace(session_uid=session))

    def test_paths_of_this_session_and_project(self) -> None:
        """RF-009-07, RF-008-22 (plan A6): lo anotado es de la sesión y del proyecto que lo
        anotan (la raíz, normalizada como la compara Windows); otra sesión u otro proyecto no
        lo ven; quitarlo lo quita y quitarlo otra vez no falla."""
        freezing = _freezing()
        root = Path(os.path.abspath("proyectos")) / "Cantera.gbproj"
        mine = self.project(root)
        temporary = root / "snapshots" / "V01.r1.congelando-0a1b2c3d"
        self.assertEqual(freezing.freezing_paths(mine), frozenset())
        freezing.register(mine, temporary)
        try:
            same = self.project(os.path.normcase(f"{root}{os.sep}.{os.sep}"))
            self.assertEqual(freezing.freezing_paths(mine), frozenset({temporary}))
            self.assertEqual(freezing.freezing_paths(same), frozenset({temporary}))
            self.assertEqual(freezing.freezing_paths(self.project(root, "s2")), frozenset())
            self.assertEqual(freezing.freezing_paths(self.project(root.with_name("Otra.gbproj"))),
                             frozenset())
        finally:
            freezing.unregister(temporary)
        self.assertEqual(freezing.freezing_paths(mine), frozenset())
        freezing.unregister(temporary)
        self.assertEqual(freezing.freezing_paths(mine), frozenset())


def _no_findings(conn: Any, version_uid: str) -> tuple[()]:
    return ()


class FreezeChecksRegistryTest(unittest.TestCase):
    """El registro de las comprobaciones de congelar (RF-012-25) en ``core.versions.freezing``."""

    MODULE = "tst38"
    OTHER = "tst38b"

    def setUp(self) -> None:
        self.freezing = _freezing()
        self.freeze = import_geoblender("core.versions.freeze")
        self.addCleanup(self.freezing.unregister_freeze_checks, self.MODULE)
        self.addCleanup(self.freezing.unregister_freeze_checks, self.OTHER)

    def ours(self) -> list[tuple[str, Any]]:
        return [entry for entry in self.freezing.freeze_checks()
                if entry[0] in (self.MODULE, self.OTHER)]

    def test_the_api_of_freeze_is_the_same(self) -> None:
        """RNF-001-03, RF-012-25: ``core.versions.freeze`` reexporta las tres funciones del
        registro (los mismos objetos): quien registra por ahí y quien lo hace por el módulo ligero
        ven un solo registro."""
        for name in ("register_freeze_check", "unregister_freeze_checks", "freeze_checks"):
            with self.subTest(función=name):
                self.assertIs(getattr(self.freeze, name), getattr(self.freezing, name))
        self.freeze.register_freeze_check(self.MODULE, _no_findings)
        self.assertEqual(self.ours(), [(self.MODULE, _no_findings)])
        self.assertEqual(self.freeze.freeze_checks(), self.freezing.freeze_checks())

    def test_order_idempotence_and_removal_by_module(self) -> None:
        """RF-012-25: registrar otra vez la misma función del mismo módulo no repite; un módulo
        puede tener varias y se llaman en el orden en que se registraron; se quitan por módulo
        (cuántas quitó) y quitar un módulo sin ninguna da 0."""

        def second(conn: Any, version_uid: str) -> tuple[()]:
            return ()

        def other(conn: Any, version_uid: str) -> tuple[()]:
            return ()

        self.freezing.register_freeze_check(self.MODULE, _no_findings)
        self.freezing.register_freeze_check(self.OTHER, other)
        self.freezing.register_freeze_check(self.MODULE, second)
        self.freezing.register_freeze_check(self.MODULE, _no_findings)
        self.assertEqual(self.ours(), [(self.MODULE, _no_findings), (self.OTHER, other),
                                       (self.MODULE, second)])
        self.assertEqual(self.freezing.unregister_freeze_checks(self.MODULE), 2)
        self.assertEqual(self.ours(), [(self.OTHER, other)])
        self.assertEqual(self.freezing.unregister_freeze_checks(self.MODULE), 0)

    def test_bad_arguments(self) -> None:
        """RF-012-25: el módulo es un texto no vacío y la comprobación, algo que se llama."""
        for module, error in ((None, TypeError), (3, TypeError), ("", ValueError),
                              ("  ", ValueError)):
            with self.subTest(módulo=module):
                with self.assertRaises(error):
                    self.freezing.register_freeze_check(module, _no_findings)
                with self.assertRaises(error):
                    self.freezing.unregister_freeze_checks(module)
        with self.assertRaises(TypeError):
            self.freezing.register_freeze_check(self.MODULE, "no se llama")
        self.assertEqual(self.ours(), [])


if __name__ == "__main__":
    unittest.main()
