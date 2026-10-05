# SPDX-License-Identifier: GPL-3.0-or-later
"""Reglas de la plataforma de extensiones y de rutas (RF-001-16).

PLT-01 (``bl_info``), PLT-02 (una sola ``AddonPreferences``), PLT-03 (módulo y paquete
con el mismo nombre), ARQ-03 (raíz sin imports a nivel de módulo), ARQ-09 (imports
internos relativos), ARQ-15 (rutas absolutas o de red en literales), ARQ-16 (pickle),
ARQ-18 (``sys.path`` y ``pip``), ARQ-19 (hilos en ``bl/``) y EXP-01 (rutas a los
expedientes de clientes o al NAS). Las rutas de EXP-01 se construyen por concatenación:
el texto del repositorio nunca contiene el patrón.
"""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import platform  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
BS = "\\"
# «<unidad>:\an\» y «\\<IP>\», construidos en ejecución (plan 001 §5.4.1).
DOSSIER = "Z" + ":" + BS + "an" + BS + "Silvestre"
DOSSIER_SLASH = "y" + ":/" + "an" + "/x"
NAS_IP = ".".join(("192", "168", "10", "10"))
NAS = BS * 2 + NAS_IP + BS + "IMG2"
# Las mismas rutas al NAS con barras normales o mezcladas (convergencia, T39).
NAS_SLASH = "/" * 2 + NAS_IP + "/" + "IMG2"
NAS_MIXED = "/" + BS + NAS_IP + "/" + "cu"


def _found(files: dict[str, str]) -> list[tuple[str, int, str]]:
    tree = {
        rel: (SPDX + text if rel.endswith(".py") else text)
        for rel, text in files.items()
    }
    with temp_tree(tree) as root:
        findings = platform.check(root)
    return [(f.path, f.line, f.rule) for f in findings]


class PlatformTest(unittest.TestCase):
    def test_bl_info(self) -> None:
        """RF-001-16 / PLT-01: ``bl_info`` a nivel de módulo falla (también dentro de un
        ``if``); dentro de una función, no."""
        found = _found(
            {
                f"{EXT}/core/meta.py": (
                    'bl_info = {"name": "Geoblender"}\n'
                    "if True:\n    bl_info: dict = {}\n"
                    "def f():\n    bl_info = 1\n    return bl_info\n"
                ),
            }
        )
        rel = f"{EXT}/core/meta.py"
        self.assertEqual(found, [(rel, 2, "PLT-01"), (rel, 4, "PLT-01")])

    def test_root_module_level_import(self) -> None:
        """RF-001-16 / ARQ-03: el ``__init__.py`` raíz no importa nada a nivel de módulo
        (salvo ``from __future__ import annotations``) y define ``register`` y
        ``unregister``."""
        found = _found(
            {
                f"{EXT}/__init__.py": (
                    "from __future__ import annotations\n"
                    "import os\n"
                    "try:\n    from . import core\nexcept ImportError:\n    pass\n"
                    "def register():\n    from . import bl\n    bl.register()\n"
                    "def unregister():\n    from . import bl\n    bl.unregister()\n"
                ),
            }
        )
        rel = f"{EXT}/__init__.py"
        self.assertEqual(found, [(rel, 3, "ARQ-03"), (rel, 5, "ARQ-03")])
        missing = _found({f"{EXT}/__init__.py": "def register():\n    pass\n"})
        self.assertEqual(missing, [(f"{EXT}/__init__.py", 0, "ARQ-03")])
        good = _found(
            {
                f"{EXT}/__init__.py": (
                    '"""Raíz."""\n'
                    "def register():\n    from . import bl\n    bl.register()\n"
                    "def unregister():\n    from . import bl\n    bl.unregister()\n"
                ),
            }
        )
        self.assertEqual(good, [])

    def test_absolute_internal_import(self) -> None:
        """RF-001-16 / ARQ-09: imports internos absolutos (``geoblender``,
        ``Geoblender``, ``bl_ext``, un paquete propio) o relativos que se salen del
        paquete fallan."""
        found = _found(
            {
                f"{EXT}/gis/grid.py": (
                    "import geoblender.core\n"
                    "from Geoblender.core import units\n"
                    "import bl_ext.user_default.geoblender\n"
                    "from core import units\n"
                    "import importlib\n"
                    'importlib.import_module("geoblender.drillholes")\n'
                    "from ..core import units\n"
                ),
                f"{EXT}/core/a.py": "from ... import outside\n",
            }
        )
        grid = f"{EXT}/gis/grid.py"
        self.assertEqual(
            found,
            [
                (f"{EXT}/core/a.py", 2, "ARQ-09"),
                (grid, 2, "ARQ-09"),
                (grid, 3, "ARQ-09"),
                (grid, 4, "ARQ-09"),
                (grid, 5, "ARQ-09"),
                (grid, 7, "ARQ-09"),
            ],
        )

    def test_bootstrap_absolute_import_only_there(self) -> None:
        """RF-001-16 / ARQ-09: la excepción vale solo para ``workers/_bootstrap.py``."""
        self.assertEqual(platform.ARQ09_ALLOWED, ("workers/_bootstrap.py",))
        found = _found(
            {
                f"{EXT}/workers/_bootstrap.py": "import geoblender\n",
                f"{EXT}/workers/run.py": "import geoblender\n",
                f"{EXT}/jobs/_bootstrap.py": "import geoblender\n",
            }
        )
        self.assertEqual(
            found,
            [(f"{EXT}/jobs/_bootstrap.py", 2, "ARQ-09"),
             (f"{EXT}/workers/run.py", 2, "ARQ-09")],
        )

    def test_absolute_path_literal(self) -> None:
        """RF-001-16 / ARQ-15: literales que empiezan por una unidad, ``file://`` o una
        carpeta absoluta de Linux o macOS fallan."""
        literals = [
            "C:\\\\Datos\\\\x.csv",
            "d:/proyectos",
            "file:///c:/x",
            "/home/ana/x",
            "/mnt/datos",
            "/media/usb",
            "/Users/ana",
            "/tmp/x",
            "/usr/share/proj",
            "/var/lib",
            "/opt/qgis",
        ]
        body = "".join(f'P{i} = "{text}"\n' for i, text in enumerate(literals))
        allowed = (
            'A = "relative/path"\nB = "/"\nC = "https://example.com"\n'
            'D = "a:b"\nE = "/etc/x"\nF = b"C:/bytes"\n'
        )
        found = _found({f"{EXT}/core/paths.py": body + allowed})
        self.assertEqual(
            found,
            [(f"{EXT}/core/paths.py", line, "ARQ-15") for line in range(2, 13)],
        )
        fstrings = 'x = 1\np = f"C:/{x}"\nq = f"{x}/tmp/"\n'
        prefixed = _found({f"{EXT}/core/f.py": fstrings})
        self.assertEqual(prefixed, [(f"{EXT}/core/f.py", 3, "ARQ-15")])

    def test_unc_literal(self) -> None:
        """RF-001-16 / ARQ-15: un literal que empieza por dos barras invertidas (ruta
        de red) falla; con una sola (``"\\n"``), no."""
        found = _found(
            {f"{EXT}/core/net.py": 'NET = r"\\\\servidor\\recurso"\nOK = "\\\\n"\n'}
        )
        self.assertEqual(found, [(f"{EXT}/core/net.py", 2, "ARQ-15")])

    def test_docstring_ignored(self) -> None:
        """RF-001-16 / ARQ-15: los docstrings no cuentan; otro literal suelto, sí."""
        found = _found(
            {
                f"{EXT}/core/doc.py": (
                    '"""C:/Datos es un ejemplo de ruta."""\n'
                    "class K:\n"
                    '    """/home/x en la documentación."""\n'
                    "def f():\n"
                    '    """file:///c:/x tampoco."""\n'
                    "    x = 1\n"
                    '    "/tmp/x"\n'
                    "    return x\n"
                ),
            }
        )
        self.assertEqual(found, [(f"{EXT}/core/doc.py", 8, "ARQ-15")])

    def test_pickle(self) -> None:
        """RF-001-16 / ARQ-16: ``pickle``, ``_pickle``, ``cPickle``, ``shelve``,
        ``dill`` y ``cloudpickle`` fallan."""
        found = _found(
            {
                f"{EXT}/core/store.py": (
                    "import pickle\n"
                    "from shelve import open as shelf\n"
                    "import cloudpickle as cp\n"
                    "import _pickle, cPickle\n"
                    "import importlib\n"
                    'importlib.import_module("dill")\n'
                    "import json\n"
                ),
            }
        )
        rel = f"{EXT}/core/store.py"
        self.assertEqual(
            found,
            [(rel, 2, "ARQ-16"), (rel, 3, "ARQ-16"), (rel, 4, "ARQ-16"),
             (rel, 5, "ARQ-16"), (rel, 5, "ARQ-16"), (rel, 7, "ARQ-16")],
        )

    def test_allow_pickle_true(self) -> None:
        """RF-001-16 / ARQ-16: ``allow_pickle=True`` en cualquier llamada falla."""
        found = _found(
            {
                f"{EXT}/core/npz.py": (
                    "def read(np, path):\n"
                    "    a = np.load(path, allow_pickle=True)\n"
                    "    b = np.load(path, allow_pickle=False)\n"
                    "    return a, b\n"
                ),
            }
        )
        self.assertEqual(found, [(f"{EXT}/core/npz.py", 3, "ARQ-16")])

    def test_sys_path(self) -> None:
        """RF-001-16 / ARQ-18: modificar ``sys.path`` o llamar a ``site.addsitedir``."""
        found = _found(
            {
                f"{EXT}/core/boot.py": (
                    "import sys, site\n"
                    "sys.path.append('x')\n"
                    "sys.path.insert(0, 'x')\n"
                    "sys.path = []\n"
                    "sys.path[0] = 'x'\n"
                    "del sys.path[0]\n"
                    "sys.path += ['x']\n"
                    "site.addsitedir('x')\n"
                    "sys.path.extend(['x'])\n"
                    "print(sys.path, len(sys.path))\n"
                ),
            }
        )
        rel = f"{EXT}/core/boot.py"
        self.assertEqual(found, [(rel, line, "ARQ-18") for line in range(3, 11)])

    def test_sys_path_aliases(self) -> None:
        """RF-001-16 / ARQ-18: también con ``sys`` importado con otro nombre (``import
        sys as s``, también dentro de una función) o con ``path`` importado de ``sys``
        (``from sys import path``), y ``site.addsitedir`` con ``site`` renombrado;
        ``os.path`` y un ``path`` propio no cuentan (convergencia, T39)."""
        found = _found(
            {
                f"{EXT}/core/alias.py": (
                    "import os\n"
                    "import sys as s\n"
                    "s.path.append('x')\n"
                    "s.path = []\n"
                    "from sys import path\n"
                    "from sys import path as rutas, argv\n"
                    "import site as st\n"
                    "st.addsitedir('x')\n"
                    "def f():\n"
                    "    import sys as interno\n"
                    "    del interno.path[0]\n"
                    "os.path.join('a', 'b')\n"
                    "class K:\n"
                    "    path = []\n"
                    "K.path.append('x')\n"
                    "from sys import argv\n"
                ),
            }
        )
        rel = f"{EXT}/core/alias.py"
        self.assertEqual(
            found, [(rel, line, "ARQ-18") for line in (4, 5, 6, 7, 9, 12)]
        )
        allowed = _found(
            {f"{EXT}/jobs/runtime.py": "import sys as s\nfrom sys import path\n"
             "s.path.insert(0, 'x')\n"}
        )
        self.assertEqual(allowed, [])

    def test_pip_literal(self) -> None:
        """RF-001-16 / ARQ-18: ``pip`` en una lista, una tupla o un argumento, o
        importado (también ``ensurepip``), falla."""
        found = _found(
            {
                f"{EXT}/jobs/install.py": (
                    "import subprocess, sys\n"
                    'subprocess.run([sys.executable, "-m", "pip", "install", "x"])\n'
                    'subprocess.run(("pip", "list"))\n'
                    'subprocess.call("pip")\n'
                    'subprocess.call(args="pip")\n'
                    "import pip\n"
                    "import ensurepip\n"
                    'name = "pip"\n'
                    'other = ["pipeline"]\n'
                ),
            }
        )
        rel = f"{EXT}/jobs/install.py"
        self.assertEqual(found, [(rel, line, "ARQ-18") for line in range(3, 9)])

    def test_bootstrap_allowed(self) -> None:
        """RF-001-16 / ARQ-18: ``workers/_bootstrap.py`` y ``jobs/runtime.py`` sí tocan
        ``sys.path`` e invocan ``pip``."""
        self.assertEqual(
            platform.PIP_SYS_PATH_ALLOWED, ("workers/_bootstrap.py", "jobs/runtime.py")
        )
        code = (
            "import sys, subprocess\n"
            "sys.path.insert(0, 'x')\n"
            'subprocess.run([sys.executable, "-m", "pip", "install", "x"])\n'
        )
        found = _found(
            {
                f"{EXT}/workers/_bootstrap.py": "import geoblender\n" + code,
                f"{EXT}/jobs/runtime.py": code,
                f"{EXT}/jobs/other.py": code,
            }
        )
        rel = f"{EXT}/jobs/other.py"
        self.assertEqual(found, [(rel, 3, "ARQ-18"), (rel, 4, "ARQ-18")])

    def test_threading_in_bl(self) -> None:
        """RF-001-16 / ARQ-19: ``bl/`` no usa hilos ni procesos; ``jobs/``, sí."""
        found = _found(
            {
                f"{EXT}/bl/ops/run.py": (
                    "import threading\n"
                    "from concurrent.futures import ThreadPoolExecutor\n"
                    "import multiprocessing\n"
                    "import _thread\n"
                    "from concurrent import futures\n"
                    "import concurrent\n"
                    "def f():\n    import threading\n"
                ),
                f"{EXT}/jobs/runner.py": (
                    "import threading\nfrom concurrent.futures import Future\n"
                ),
            }
        )
        rel = f"{EXT}/bl/ops/run.py"
        self.assertEqual(
            found,
            [(rel, line, "ARQ-19") for line in (2, 3, 4, 5, 6, 9)],
        )

    def test_dossier_path_in_tools(self) -> None:
        """RF-001-16 / EXP-01: una ruta a los expedientes de clientes o al NAS en
        ``geoblender/``, ``tools/`` o ``tests/`` falla; en ``docs/``, no aplica."""
        found = _found(
            {
                "tools/bench.py": f'DIR = r"{DOSSIER}"\n',
                "tests/banco/silvestre/nota.txt": f"datos en {NAS}\\cu\n",
                f"{EXT}/core/x.py": f"# antes en {DOSSIER_SLASH}\n",
                "tools/ok.py": 'A = r"Z:' + BS + 'analisis"\n',
                "docs/nota.md": f"Expedientes en {DOSSIER}\n",
            }
        )
        self.assertEqual(
            found,
            [
                (f"{EXT}/core/x.py", 2, "EXP-01"),
                ("tests/banco/silvestre/nota.txt", 1, "EXP-01"),
                ("tools/bench.py", 2, "EXP-01"),
            ],
        )

    def test_nas_path_with_slashes(self) -> None:
        """RF-001-16 / EXP-01: la ruta al NAS por IP con barras normales o mezcladas
        también falla; la IP sola o tras una sola barra, no (convergencia, T39)."""
        found = _found(
            {
                "tools/nas.py": f'DIR = "{NAS_SLASH}"\n',
                "tests/unit/nota.txt": f"montado en {NAS_MIXED}\n",
                f"{EXT}/core/ip.py": f'# servidor {NAS_IP} y /{NAS_IP}/x\n',
            }
        )
        self.assertEqual(
            found, [("tests/unit/nota.txt", 1, "EXP-01"), ("tools/nas.py", 2, "EXP-01")]
        )

    def test_two_addon_preferences(self) -> None:
        """RF-001-16 / PLT-02: una sola ``AddonPreferences``, en
        ``bl/props/preferences.py`` y con ``bl_idname`` = ``ADDON_PACKAGE``."""
        good = (
            "class GeoblenderPreferences(bpy.types.AddonPreferences):\n"
            "    bl_idname = ADDON_PACKAGE\n"
        )
        self.assertEqual(_found({f"{EXT}/bl/props/preferences.py": good}), [])
        qualified = good.replace("= ADDON_PACKAGE", "= bl.ADDON_PACKAGE")
        self.assertEqual(_found({f"{EXT}/bl/props/preferences.py": qualified}), [])
        two = _found(
            {
                f"{EXT}/bl/props/preferences.py": good,
                f"{EXT}/bl/ui/prefs.py": (
                    "class Other(AddonPreferences):\n    bl_idname = ADDON_PACKAGE\n"
                ),
            }
        )
        self.assertEqual(
            two,
            [(f"{EXT}/bl/props/preferences.py", 2, "PLT-02"),
             (f"{EXT}/bl/ui/prefs.py", 2, "PLT-02")],
        )
        wrong_id = good.replace("ADDON_PACKAGE", "__package__")
        self.assertEqual(
            _found({f"{EXT}/bl/props/preferences.py": wrong_id}),
            [(f"{EXT}/bl/props/preferences.py", 2, "PLT-02")],
        )
        no_id = "class P(bpy.types.AddonPreferences):\n    pass\n"
        self.assertEqual(
            _found({f"{EXT}/bl/props/preferences.py": no_id}),
            [(f"{EXT}/bl/props/preferences.py", 2, "PLT-02")],
        )
        elsewhere = _found({f"{EXT}/bl/props/other.py": good})
        self.assertEqual(elsewhere, [(f"{EXT}/bl/props/other.py", 2, "PLT-02")])

    def test_module_and_package_same_name(self) -> None:
        """RF-001-16 / PLT-03: un ``x.py`` junto a un paquete ``x/`` falla en
        ``geoblender/``, ``tools/`` y ``tests/``."""
        found = _found(
            {
                f"{EXT}/core/i18n.py": "",
                f"{EXT}/core/i18n/__init__.py": "",
                "tools/gbtools.py": "",
                "tools/gbtools/__init__.py": "",
                "tests/support.py": "",
                "tests/support/__init__.py": "",
                f"{EXT}/resources.py": "",
                f"{EXT}/resources/icons/a.png": "",
                "docs/x.py": "",
                "docs/x/__init__.py": "",
            }
        )
        self.assertEqual(
            found,
            [
                (f"{EXT}/core/i18n.py", 0, "PLT-03"),
                ("tests/support.py", 0, "PLT-03"),
                ("tools/gbtools.py", 0, "PLT-03"),
            ],
        )

    def test_real_tree(self) -> None:
        """RF-001-16 / PLT-01 a 03, ARQ-03, 09, 15, 16, 18, 19 y EXP-01: el repositorio
        real cumple (y ningún fichero de ``tools/`` ni de ``tests/`` contiene una ruta a
        los expedientes)."""
        findings = platform.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()
