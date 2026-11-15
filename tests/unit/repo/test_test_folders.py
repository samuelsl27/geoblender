# SPDX-License-Identifier: GPL-3.0-or-later
"""Reglas de las carpetas y los ficheros de pruebas (RF-001-06; convergencia de la
spec 001).

- TST-01 (T34): toda carpeta de ``tests/`` con ficheros ``.py`` tiene ``__init__.py``.
  Desde Python 3.11, ``unittest discover`` no entra en una carpeta sin él: una prueba
  que falla en ``tests/unit/<sub>/`` no se ejecutaría y la comprobación daría verde.
- TST-02 (T43): todo ``.py`` de una carpeta de pruebas casa con el patrón de su paso;
  si no, ``unittest`` no lo carga nunca y nadie lo ve.
- TST-03 (T44): un método de un ``TestCase`` que cita un requisito empieza por «test».
- TST-04 (T46): ninguna omisión incondicional (``@unittest.skip``, ``skipTest`` suelto).
- TST-07 (T59): ningún ``expectedFailure``: una prueba roja así marcada da «OK».
- TST-08 (T60): ninguna prueba fuera de un ``TestCase`` (funciones ``test_…`` de módulo).
"""

import functools
import unittest
from pathlib import Path

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

import check  # noqa: E402
from gbtools.blender import BlenderInstall  # noqa: E402
from gbtools.findings import Finding, format_findings  # noqa: E402
from gbtools.rules import FAMILIES, suites  # noqa: E402

# Va en la misma parte que las demás pruebas que pasan las reglas por todo el repositorio:
# así lo analizan una sola vez (spec 006, T47; gbtools.parts.affinity_of).
PART_AFFINITY = "reglas-repositorio"

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
FAILING = SPDX + (
    "import unittest\n\n\n"
    "class Falla(unittest.TestCase):\n"
    "    def test_falla(self):\n"
    "        self.fail('sabotaje')\n"
)
PACKAGES = {
    "tests/__init__.py": SPDX,
    "tests/unit/__init__.py": SPDX,
    "tests/blender/__init__.py": SPDX,
}


@functools.cache
def _real_findings_cached() -> tuple[Finding, ...]:
    return tuple(suites.check(ROOT))


def _real_findings() -> list[Finding]:
    """Lo que encuentran las reglas en el árbol real, recorrido una sola vez para todas
    las pruebas del módulo (cada recorrido costaba 0,5 s: RNF-001-01; convergencia de la
    spec 002, T39)."""
    return list(_real_findings_cached())


def _found(files: dict[str, str]) -> list[tuple[str, int, str]]:
    with temp_tree(files) as root:
        return [(f.path, f.line, f.rule) for f in suites.check(root)]


class TestFoldersTest(unittest.TestCase):
    def test_folder_without_init(self) -> None:
        """RF-001-06 / TST-01: una subcarpeta de ``tests/unit/`` o de ``tests/blender/``
        con una prueba y sin ``__init__.py`` falla, con la carpeta en el mensaje."""
        found = _found(
            {
                **PACKAGES,
                "tests/unit/nueva/test_falla.py": FAILING,
                "tests/blender/otra/test_falla.py": FAILING,
            }
        )
        self.assertEqual(
            found,
            [("tests/blender/otra/", 0, "TST-01"), ("tests/unit/nueva/", 0, "TST-01")],
        )

    def test_intermediate_folder_without_init(self) -> None:
        """RF-001-06 / TST-01: discover tampoco baja por una carpeta intermedia sin
        ``__init__.py`` aunque la de abajo lo tenga; y ``tests/`` también lo necesita."""
        found = _found(
            {
                "tests/unit/__init__.py": SPDX,
                "tests/unit/a/b/__init__.py": SPDX,
                "tests/unit/a/b/test_falla.py": FAILING,
            }
        )
        self.assertEqual(found, [("tests/", 0, "TST-01"), ("tests/unit/a/", 0, "TST-01")])

    def test_packages_ok(self) -> None:
        """RF-001-06 / TST-01: con ``__init__.py`` en cada carpeta no hay incumplimientos;
        una carpeta de datos sin ``.py`` no lo necesita, ni las de fuera de ``tests/``."""
        found = _found(
            {
                **PACKAGES,
                "tests/unit/nueva/__init__.py": SPDX,
                "tests/unit/nueva/test_falla.py": FAILING,
                "tests/data/sondeos/collar.csv": "id;x;y\n",
                "tools/inblender/guion.py": SPDX,
                f"{EXT}/core/units.py": SPDX,
            }
        )
        self.assertEqual(found, [])

    def test_in_run_all(self) -> None:
        """RF-001-06 / TST-01: la regla está en ``FAMILIES`` (la ejecuta ``run_all`` y,
        con ella, el paso «unitarias» de la comprobación completa)."""
        self.assertIs(FAMILIES["suites"], suites.check)

    def test_real_tree(self) -> None:
        """RF-001-06 / TST-01: todas las carpetas de ``tests/`` del repositorio con
        ``.py`` tienen ``__init__.py``."""
        findings = _real_findings()
        self.assertEqual(findings, [], "\n" + format_findings(findings))


SUITES = {
    **PACKAGES,
    "tests/unit/tools/__init__.py": SPDX,
    "tests/referencia/__init__.py": SPDX,
    "tests/rendimiento/__init__.py": SPDX,
    "tests/rendimiento/blender/__init__.py": SPDX,
    "tests/banco/__init__.py": SPDX,
    "tests/banco/silvestre/__init__.py": SPDX,
}


class TestFileNamesTest(unittest.TestCase):
    """TST-02: un ``.py`` de una carpeta de pruebas que no casa con el patrón de su paso
    no se carga nunca (hallazgo N6 de la reverificación; convergencia, T43)."""

    def test_names_outside_pattern(self) -> None:
        """RF-001-06 / TST-02: en las carpetas de pruebas, todo ``.py`` salvo
        ``__init__.py`` casa con el patrón de su paso (``test*.py``; ``test_*.py`` en
        ``tests/blender`` y ``tests/rendimiento``; ``perf_*.py`` en
        ``tests/rendimiento/blender``) y es un nombre de módulo; y no hay ``.py`` fuera
        de ellas, de ``tests/support/`` y de ``tests/data/``, que ningún paso carga."""
        bad = [
            "tests/unit/manifest_test.py",  # sufijo de pytest
            "tests/unit/prueba_x.py",
            "tests/unit/tools/ayuda.py",
            "tests/unit/test-guion.py",  # casa con test*.py, pero no es un módulo
            "tests/blender/testx.py",  # test*.py sí; test_*.py no
            "tests/rendimiento/perf_x.py",
            "tests/rendimiento/blender/test_x.py",
            "tests/referencia/milestone_x.py",  # las de hito solo en tests/unit y tests/blender
            "tests/rendimiento/blender/milestone_y.py",
            "tests/unit/milestone-z.py",  # el patrón de hito, pero no es un módulo
            "tests/unit/hito_w.py",
            "tests/referencia/caso/__init__.py",
            "tests/referencia/caso/datos.py",
            "tests/banco/silvestre/comparar.py",
            "tests/test_suelta.py",
            "tests/integracion/__init__.py",
            "tests/integracion/test_y.py",
        ]
        found = _found({**SUITES, **{rel: FAILING for rel in bad}})
        expected = sorted(
            (rel, 0, "TST-02") for rel in bad if not rel.endswith("/__init__.py")
        )
        self.assertEqual(found, expected)
        with temp_tree({**SUITES, "tests/unit/manifest_test.py": FAILING}) as root:
            (finding,) = suites.check(root)
        self.assertIn("«test*.py»", finding.message)
        self.assertIn("tests/support/", finding.message)

    def test_names_in_pattern_ok(self) -> None:
        """RF-001-06 / TST-02: los nombres que carga cada paso, las ayudas de
        ``tests/support/`` y los ``.py`` de ``tests/data/`` no dan incumplimientos."""
        good = [
            "tests/unit/test_a.py",
            "tests/unit/testb.py",
            "tests/unit/tools/test_c.py",
            "tests/blender/test_d.py",
            "tests/unit/tools/milestone_a.py",  # pruebas de hito (spec 015, T48): paso «hito»
            "tests/blender/milestone_b.py",
            "tests/rendimiento/test_e.py",
            "tests/rendimiento/blender/perf_f.py",
            "tests/referencia/test_g.py",
            "tests/banco/silvestre/test_h.py",
            "tests/support/__init__.py",
            "tests/support/ayuda.py",
            "tests/data/__init__.py",
            "tests/data/generar.py",
        ]
        self.assertEqual(_found({**SUITES, **{rel: SPDX for rel in good}}), [])

    def test_patterns_are_the_steps(self) -> None:
        """RF-001-06 / TST-02: los patrones de la regla son la carpeta y el patrón de
        cada orden de pruebas de ``tools/check.py`` (y el del banco). Las del paso «motor»
        (spec 004, RF-004-28; aquí, con un motor simulado) son subcarpetas de
        ``tests/unit`` con su patrón: las cubre el de ``tests/unit``."""
        install = BlenderInstall(Path("blender.exe"), Path("python.exe"), (5, 2, 1))
        ctx = check.Context(
            root=ROOT, install=install, profile=Path("perfil"),
            find_runtime=lambda root, environ: check.TestRuntime(Path("motor")),
        )
        runs = [run for step in check.STEPS for run in step.runs(ctx) if run.folder]
        found = {(f"{run.folder}/", run.pattern) for run in runs}
        self.assertIn(("tests/unit/core/", "test*.py"), found)
        steps = {
            (folder, pattern) for folder, pattern in found
            if not any(folder != other and folder.startswith(other) and pattern == same
                       for other, same in found)
        }
        bank = ("tests/banco/", "test*.py")  # tools/bench_silvestre.py
        self.assertEqual(steps | {bank}, set(suites.SUITE_PATTERNS))


MIXED = SPDX + (
    "import unittest\n"
    "from unittest import TestCase\n\n"
    "from tests.support.otro import WheelsTestCase\n\n\n"
    "class Mezcla(unittest.TestCase):\n"
    "    def test_pasa(self):\n"
    '        """RF-001-06: pasa."""\n\n'
    "    def prueba_falla(self):\n"
    '        """RF-001-06: no se ejecuta nunca."""\n'
    "        self.fail('roja')\n\n\n"
    "class Base(TestCase):\n"
    "    @classmethod\n"
    "    def setUpClass(cls):\n"
    '        """RF-001-06: preparación (se ejecuta)."""\n\n'
    "    def ayuda(self):\n"
    '        """Sin requisito: una ayuda."""\n\n\n'
    "class Hija(Base):\n"
    "    async def comprobar_medida(self):\n"
    '        """RNF-001-02: tampoco se ejecuta."""\n\n\n'
    "class Ruedas(WheelsTestCase):\n"
    "    def caso_rueda(self):\n"
    '        """RF-001-22 / LIC-01: tampoco."""\n\n\n'
    "class Ejecutor:\n"
    "    def __call__(self):\n"
    '        """RF-001-06: no es una prueba."""\n\n\n'
    "def ayuda_de_modulo():\n"
    '    """RF-001-06: no es un método."""\n'
)


class TestMethodNamesTest(unittest.TestCase):
    """TST-03: un método de un ``TestCase`` que cita un requisito pero no empieza por
    «test» no se ejecuta nunca (hallazgo N7 de la reverificación; convergencia, T44)."""

    def test_methods_citing_requirements(self) -> None:
        """RF-001-06 / TST-03: en una subclase de ``unittest.TestCase`` (directa, de una
        clase del mismo fichero o de una base cuyo nombre termina en «TestCase»), un
        método cuyo docstring cita un ``RF-NNN-nn`` o ``RNF-NNN-nn`` y cuyo nombre no
        empieza por «test» se señala en su línea, también si es ``async``; las pruebas,
        las preparaciones (``setUpClass``…), las ayudas sin requisito y lo que no es un
        método de un ``TestCase``, no."""
        found = _found({**SUITES, "tests/unit/test_mezcla.py": MIXED})
        lines = MIXED.splitlines()
        expected = [
            ("tests/unit/test_mezcla.py", number, "TST-03")
            for number, line in enumerate(lines, start=1)
            if line.strip().startswith(
                ("def prueba_falla", "async def comprobar_medida", "def caso_rueda")
            )
        ]
        self.assertEqual(len(expected), 3)
        self.assertEqual(found, expected)
        with temp_tree({**SUITES, "tests/unit/test_mezcla.py": MIXED}) as root:
            messages = [f.message for f in suites.check(root)]
        self.assertIn("«prueba_falla»", messages[0])
        self.assertIn("RF-001-06", messages[0])
        self.assertIn("«test", messages[0])

    def test_unparsable_file_left_to_ast01(self) -> None:
        """RF-001-06 / TST-03: un fichero que no se puede analizar no rompe la regla (lo
        señala AST-01)."""
        found = _found({**SUITES, "tests/unit/test_roto.py": SPDX + "def (:\n"})
        self.assertEqual(found, [])


SKIPS = SPDX + (
    "import unittest\n"
    "from unittest import skip\n\n"
    "from tests.support.resources import skip_reason\n\n\n"
    "@unittest.skip('toda la clase')\n"
    "class Clase(unittest.TestCase):\n"
    "    def test_a(self):\n"
    '        """RF-001-06: a."""\n\n\n'
    "class Metodos(unittest.TestCase):\n"
    "    @unittest.skip(skip_reason('nada', 'nada'))\n"
    "    def test_b(self):\n"
    '        """RF-001-06: b."""\n\n'
    "    @skip\n"
    "    def test_c(self):\n"
    '        """RF-001-06: c."""\n\n'
    "    @unittest.skipIf(True, 'siempre')\n"
    "    def test_d(self):\n"
    '        """RF-001-06: d."""\n\n'
    "    def test_e(self):\n"
    '        """RF-001-06: e."""\n'
    "        self.skipTest('luego')\n"
    "        self.fail('roja')\n\n"
    "    @classmethod\n"
    "    def setUpClass(cls):\n"
    "        raise unittest.SkipTest('nunca')\n"
)
CONDITIONAL = SPDX + (
    "import os\n"
    "import unittest\n\n"
    "from tests.support.resources import skip_reason\n\n\n"
    "class Condicional(unittest.TestCase):\n"
    "    @unittest.skipUnless(os.name == 'nt', skip_reason('windows', 'x'))\n"
    "    def test_a(self):\n"
    '        """RF-001-06: a."""\n\n'
    "    @unittest.skipIf(False, 'nunca')\n"
    "    def test_b(self):\n"
    '        """RF-001-06: b."""\n\n'
    "    def test_c(self):\n"
    '        """RF-001-06: c."""\n'
    "        try:\n"
    "            os.symlink('a', 'b')\n"
    "        except OSError:\n"
    "            self.skipTest(skip_reason('symlink', 'x'))\n\n"
    "    def test_d(self):\n"
    '        """RF-001-06: d."""\n'
    "        if not os.environ.get('X'):\n"
    "            self.skipTest(skip_reason('x', 'y'))\n"
)
SKIPPED_MODULE = SPDX + "import unittest\n\nraise unittest.SkipTest('módulo entero')\n"
# Condiciones que no dependen de nada (hallazgo F1, falsos verdes X1 y X1b; T48).
CONSTANT_SKIPS = SPDX + (
    "import contextlib\n"
    "import unittest\n\n"
    "from tests.support.resources import skip_reason\n\n"
    "SIEMPRE = True\n\n\n"
    "class Constantes(unittest.TestCase):\n"
    "    @unittest.skipIf(1 == 1, skip_reason('qgis', 'instale QGIS'))\n"
    "    def test_a(self):\n"
    '        """RF-001-06: a."""\n\n'
    "    @unittest.skipUnless(1 == 2, skip_reason('symlink', 'x'))\n"
    "    def test_b(self):\n"
    '        """RF-001-06: b."""\n\n'
    "    @unittest.skipIf(not False and (1, 2), 'x')\n"
    "    def test_c(self):\n"
    '        """RF-001-06: c."""\n\n'
    "    @unittest.skipIf(SIEMPRE, 'x')\n"
    "    def test_d(self):\n"
    '        """RF-001-06: d."""\n\n'
    "    def test_e(self):\n"
    '        """RF-001-06: e."""\n'
    "        if True:\n"
    "            self.skipTest(skip_reason('nada', 'nada'))\n"
    "        self.fail('roja')\n\n"
    "    def test_f(self):\n"
    '        """RF-001-06: f."""\n'
    "        if 0:\n"
    "            pass\n"
    "        else:\n"
    "            with contextlib.suppress(OSError):\n"
    "                try:\n"
    "                    self.skipTest('x')\n"
    "                except OSError:\n"
    "                    pass\n\n"
    "    @classmethod\n"
    "    def setUpClass(cls):\n"
    "        if SIEMPRE:\n"
    "            raise unittest.SkipTest('x')\n\n\n"
    "if 1 + 1 == 2:\n"
    "    raise unittest.SkipTest('módulo')\n"
)
DEPENDENT_SKIPS = SPDX + (
    "import os\n"
    "import unittest\n\n"
    "VARIABLE = True\n"
    "VARIABLE = os.name == 'nt'\n\n\n"
    "class Dependientes(unittest.TestCase):\n"
    "    @unittest.skipIf(1 == 2, 'nunca')\n"
    "    def test_a(self):\n"
    '        """RF-001-06: a."""\n\n'
    "    @unittest.skipIf(os.name != 'nt', 'x')\n"
    "    def test_b(self):\n"
    '        """RF-001-06: b."""\n\n'
    "    @unittest.skipIf(VARIABLE, 'x')\n"
    "    def test_c(self):\n"
    '        """RF-001-06: c."""\n\n'
    "    def test_d(self):\n"
    '        """RF-001-06: d."""\n'
    "        if False:\n"
    "            self.skipTest('nunca')\n"
    "        if 1:\n"
    "            pass\n"
    "        else:\n"
    "            self.skipTest('nunca')\n"
    "        while os.environ.get('X'):\n"
    "            self.skipTest('x')\n"
)


class UnconditionalSkipTest(unittest.TestCase):
    """TST-04: una omisión incondicional no se ejecuta nunca; con un motivo
    «[ENTORNO]» inventado, ``tools/check.py`` la contaría como una omisión por un
    recurso y daría código 0 (hallazgo N1 de la reverificación; convergencia, T46)."""

    def test_unconditional_skips(self) -> None:
        """RF-001-06 / TST-04: ``@unittest.skip`` (con o sin motivo, también con
        ``skip_reason`` y sobre una clase), ``skipIf`` con una condición constante
        verdadera, ``self.skipTest`` y ``raise unittest.SkipTest`` directamente en el
        cuerpo de un método o del módulo se señalan en su línea."""
        found = _found(
            {
                **SUITES,
                "tests/unit/test_saltadas.py": SKIPS,
                "tests/unit/test_modulo.py": SKIPPED_MODULE,
            }
        )
        markers = (
            "@unittest.skip(",
            "@skip",
            "@unittest.skipIf(True",
            "self.skipTest(",
            "raise unittest.SkipTest(",
        )
        expected = sorted(
            [
                ("tests/unit/test_saltadas.py", number, "TST-04")
                for number, line in enumerate(SKIPS.splitlines(), start=1)
                if line.strip().startswith(markers)
            ]
            + [("tests/unit/test_modulo.py", 4, "TST-04")]
        )
        self.assertEqual(len(expected), 7)
        self.assertEqual(found, expected)
        with temp_tree({**SUITES, "tests/unit/test_modulo.py": SKIPPED_MODULE}) as root:
            (finding,) = suites.check(root)
        self.assertIn("tests.support.resources.requires", finding.message)

    def test_conditional_skips_ok(self) -> None:
        """RF-001-06 / TST-04: las omisiones que dependen de algo (``skipUnless`` con una
        condición, ``skipIf(False, …)``, ``skipTest`` dentro de un ``except`` o de un
        ``if``) y las de ``requires`` no se señalan; ni el árbol real."""
        found = _found({**SUITES, "tests/unit/test_condicional.py": CONDITIONAL})
        self.assertEqual(found, [])
        real = [f for f in _real_findings() if f.rule == "TST-04"]
        self.assertEqual(real, [], "\n" + format_findings(real))

    def test_constant_conditions(self) -> None:
        """RF-001-06 / TST-04: una condición que no depende de nada (sin nombres,
        atributos ni llamadas, salvo un nombre del módulo asignado una sola vez a una
        constante) se evalúa: ``skipIf(1 == 1, …)``, ``skipUnless(1 == 2, …)``,
        ``skipIf(not False and (1, 2), …)`` y ``skipIf(SIEMPRE, …)`` omiten siempre; y
        una omisión dentro de un ``if`` constante que se cumple (o de su ``else`` si no
        se cumple), de un ``with`` o del cuerpo de un ``try`` también es incondicional,
        en un método, en ``setUpClass`` y en el módulo (hallazgo F1, falsos verdes X1 y
        X1b; convergencia, T48)."""
        found = _found({**SUITES, "tests/unit/test_constantes.py": CONSTANT_SKIPS})
        lines = CONSTANT_SKIPS.splitlines()
        markers = ("@unittest.skip", "self.skipTest(", "raise unittest.SkipTest(")
        expected = [
            ("tests/unit/test_constantes.py", number, "TST-04")
            for number, line in enumerate(lines, start=1)
            if line.strip().startswith(markers)
        ]
        self.assertEqual(len(expected), 8)
        self.assertEqual(found, expected)
        with temp_tree({**SUITES, "tests/unit/test_constantes.py": CONSTANT_SKIPS}) as root:
            messages = [f.message for f in suites.check(root)]
        self.assertIn("1 == 1", messages[0])
        self.assertIn("if True", messages[4])

    def test_conditions_that_depend_ok(self) -> None:
        """RF-001-06 / TST-04: ``skipIf(1 == 2, …)``, una condición con un atributo o con
        un nombre que se asigna más de una vez, un ``if`` constante que no se cumple (o
        su ``else`` si se cumple) y un ``while`` que depende de algo no se señalan."""
        found = _found({**SUITES, "tests/unit/test_dependientes.py": DEPENDENT_SKIPS})
        self.assertEqual(found, [])


DUPLICATES = SPDX + (
    "import unittest\n\n\n"
    "class Doble(unittest.TestCase):\n"
    "    def test_falla(self):\n"
    '        """RF-001-06: roja."""\n'
    "        self.fail('roja')\n\n"
    "    def test_falla(self):  # tapa a la roja\n"
    '        """RF-001-06: pasa."""\n\n'
    "    async def ayuda(self):\n"
    "        pass\n\n"
    "    def ayuda(self):  # también una ayuda repetida\n"
    "        pass\n\n\n"
    "class Otra(unittest.TestCase):\n"
    "    def test_falla(self):\n"
    '        """RF-001-06: otra clase, otro método."""\n\n\n'
    "class Doble(unittest.TestCase):  # tapa a la primera clase entera\n"
    "    def test_b(self):\n"
    '        """RF-001-06: b."""\n'
)
NOT_DUPLICATES = SPDX + (
    "import unittest\n"
    "from typing import overload\n\n\n"
    "class Propiedad(unittest.TestCase):\n"
    "    @property\n"
    "    def valor(self):\n"
    "        return 1\n\n"
    "    @valor.setter\n"
    "    def valor(self, nuevo):\n"
    "        pass\n\n"
    "    @overload\n"
    "    def medir(self, x: int) -> int: ...\n"
    "    @overload\n"
    "    def medir(self, x: str) -> str: ...\n"
    "    def medir(self, x):\n"
    "        return x\n\n"
    "    def test_a(self):\n"
    '        """RF-001-06: a."""\n\n\n'
    "class Ayudante:\n"
    "    def hacer(self):\n"
    "        pass\n\n"
    "    def hacer(self):\n"
    "        pass\n\n\n"
    "def construir():\n"
    "    class Local(unittest.TestCase):\n"
    "        pass\n\n"
    "    class Local(unittest.TestCase):\n"
    "        pass\n"
)


class DuplicateTestsTest(unittest.TestCase):
    """TST-05: dos métodos con el mismo nombre en una clase de pruebas, o dos clases de
    pruebas con el mismo nombre en un módulo: el segundo sustituye al primero en
    silencio y ``unittest`` no lo ejecuta nunca (hallazgo F6 de la ronda 3, falso verde
    X8; convergencia, T53)."""

    def test_duplicates(self) -> None:
        """RF-001-06 / TST-05: el segundo ``test_falla`` de ``Doble`` (que tapa al primero,
        con ``self.fail``), la segunda ``ayuda`` (también ``async``) y la segunda clase
        ``Doble`` se señalan en su línea, con la del primero en el mensaje; el mismo
        método en otra clase, no."""
        found = _found({**SUITES, "tests/unit/test_doble.py": DUPLICATES})
        lines = DUPLICATES.splitlines()
        expected = [
            ("tests/unit/test_doble.py", number, "TST-05")
            for number, line in enumerate(lines, start=1)
            if "tapa a la" in line or "también una ayuda" in line
        ]
        self.assertEqual(len(expected), 3)
        self.assertEqual(found, expected)
        with temp_tree({**SUITES, "tests/unit/test_doble.py": DUPLICATES}) as root:
            messages = [f.message for f in suites.check(root)]
        self.assertIn("«test_falla»", messages[0])
        self.assertIn("línea 6", messages[0])  # la del primer «def test_falla»
        self.assertIn("«Doble»", messages[2])

    def test_not_duplicates(self) -> None:
        """RF-001-06 / TST-05: una propiedad con su ``setter``, las sobrecargas de
        ``typing.overload``, una clase que no es de pruebas y las clases locales de una
        función no se señalan; ni el árbol real."""
        found = _found({**SUITES, "tests/unit/test_no_doble.py": NOT_DUPLICATES})
        self.assertEqual(found, [])
        real = [f for f in _real_findings() if f.rule == "TST-05"]
        self.assertEqual(real, [], "\n" + format_findings(real))


NOT_RUN = SPDX + (
    "import unittest\n\n\n"
    "class Normal(unittest.TestCase):\n"
    "    async def test_falla(self):\n"
    '        """RF-001-06: la corrutina no se espera."""\n'
    "        self.fail('roja')\n\n"
    "    def test_generadora(self):\n"
    '        """RF-001-06: el generador no se recorre."""\n'
    "        self.fail('roja')\n"
    "        yield\n\n"
    "    def test_con_ayuda_generadora(self):\n"
    '        """RF-001-06: el «yield» es de una función de dentro."""\n'
    "        def datos():\n"
    "            yield 1\n\n"
    "        self.assertEqual(list(datos()), [1])\n\n"
    "    async def ayuda(self):\n"
    "        pass\n\n\n"
    "class Hija(Normal):\n"
    "    async def test_hija(self):\n"
    '        """RF-001-06: tampoco se espera."""\n\n\n'
    "class Asincrona(unittest.IsolatedAsyncioTestCase):\n"
    "    async def test_espera(self):\n"
    '        """RF-001-06: esta sí se espera."""\n\n\n'
    "class NietaAsincrona(Asincrona):\n"
    "    async def test_nieta(self):\n"
    '        """RF-001-06: y esta."""\n'
)


class NotRunTestsTest(unittest.TestCase):
    """TST-06: una prueba ``async def`` en un ``TestCase`` que no es
    ``IsolatedAsyncioTestCase``, o una con ``yield``, no ejecuta su cuerpo: ``unittest``
    solo da un ``DeprecationWarning`` (hallazgo F7 de la ronda 3, falso verde X9;
    convergencia, T54)."""

    def test_async_and_generator_tests(self) -> None:
        """RF-001-06 / TST-06: ``async def test_falla`` en un ``TestCase`` y en una hija
        suya, y ``test_generadora`` con ``yield``, se señalan en su línea; una ``async def``
        en una hija (directa o no) de ``IsolatedAsyncioTestCase``, una ayuda ``async`` y un
        ``yield`` de una función de dentro de la prueba, no."""
        found = _found({**SUITES, "tests/unit/test_no_corre.py": NOT_RUN})
        lines = NOT_RUN.splitlines()
        markers = ("async def test_falla", "def test_generadora", "async def test_hija")
        expected = [
            ("tests/unit/test_no_corre.py", number, "TST-06")
            for number, line in enumerate(lines, start=1)
            if line.strip().startswith(markers)
        ]
        self.assertEqual(len(expected), 3)
        self.assertEqual(found, expected)
        with temp_tree({**SUITES, "tests/unit/test_no_corre.py": NOT_RUN}) as root:
            messages = [f.message for f in suites.check(root)]
        self.assertIn("IsolatedAsyncioTestCase", messages[0])
        self.assertIn("yield", messages[1])

    def test_real_tree(self) -> None:
        """RF-001-06 / TST-06: el árbol real no tiene ninguna."""
        real = [f for f in _real_findings() if f.rule == "TST-06"]
        self.assertEqual(real, [], "\n" + format_findings(real))


EXPECTED = SPDX + (
    "import unittest\n"
    "from unittest import expectedFailure\n"
    "from unittest.case import expectedFailure as esperada\n\n\n"
    "@unittest.expectedFailure\n"
    "class Clase(unittest.TestCase):\n"
    "    def test_a(self):\n"
    '        """RF-001-06: a."""\n\n\n'
    "class Metodos(unittest.TestCase):\n"
    "    @unittest.expectedFailure\n"
    "    def test_b(self):\n"
    '        """RF-001-06: roja, marcada como fallo esperado."""\n'
    "        self.fail('roja')\n\n"
    "    @expectedFailure\n"
    "    def test_c(self):\n"
    '        """RF-001-06: c."""\n\n'
    "    @esperada\n"
    "    def test_d(self):\n"
    '        """RF-001-06: d (la línea que se señala es la del import con «as»)."""\n\n'
    "    def test_e(self):\n"
    '        """RF-001-06: e."""\n\n\n'
    "Metodos.test_e = unittest.expectedFailure(Metodos.test_e)\n"
    "Metodos.test_b.__unittest_expecting_failure__ = True\n"
    "setattr(Metodos.test_d, '__unittest_expecting_failure__', True)\n"
)
NOT_EXPECTED = SPDX + (
    "import unittest\n\n\n"
    "class Normal(unittest.TestCase):\n"
    "    def test_expected_failure_text(self):\n"
    '        """RF-001-06: el texto «expectedFailure» en una cadena no cuenta."""\n'
    "        self.assertIn('expectedFailure', 'unittest.expectedFailure')\n\n"
    "    def test_errores(self):\n"
    '        """RF-001-06: un error esperado se prueba con assertRaises."""\n'
    "        with self.assertRaises(ZeroDivisionError):\n"
    "            1 / 0\n"
    "        self.assertEqual(unittest.TestResult().expectedFailures, [])\n"
)


class ExpectedFailureRuleTest(unittest.TestCase):
    """TST-07: una prueba roja marcada con ``expectedFailure`` da «OK (expected
    failures=n)» y código 0 en ``unittest`` (hallazgo F1 de la ronda 4; convergencia,
    T59)."""

    def test_expected_failures(self) -> None:
        """RF-001-06 / TST-07: en ``tests/``, ``expectedFailure`` de unittest como
        decorador (de un método o de una clase, por atributo o por nombre), llamado o
        importado (con o sin ``as``, también de ``unittest.case``), y la marca que pone
        (``__unittest_expecting_failure__``, también con ``setattr``) se señalan en su
        línea."""
        found = _found({**SUITES, "tests/unit/test_esperadas.py": EXPECTED})
        markers = (
            "from unittest import expectedFailure",
            "from unittest.case import expectedFailure",
            "@unittest.expectedFailure",
            "@expectedFailure",
            "Metodos.test_e = unittest.expectedFailure",
            "Metodos.test_b.__unittest_expecting_failure__",
            "setattr(Metodos.test_d, '__unittest_expecting_failure__'",
        )
        expected = [
            ("tests/unit/test_esperadas.py", number, "TST-07")
            for number, line in enumerate(EXPECTED.splitlines(), start=1)
            if line.strip().startswith(markers)
        ]
        self.assertEqual(len(expected), 8)
        self.assertEqual(found, expected)
        with temp_tree({**SUITES, "tests/unit/test_esperadas.py": EXPECTED}) as root:
            messages = [f.message for f in suites.check(root)]
        self.assertIn("expected failures", messages[0])
        self.assertIn("assertRaises", messages[0])

    def test_not_expected_failures(self) -> None:
        """RF-001-06 / TST-07: el texto «expectedFailure» en una cadena, ``assertRaises``,
        el atributo ``expectedFailures`` de un resultado y lo de fuera de ``tests/`` no se
        señalan; ni el árbol real."""
        found = _found(
            {
                **SUITES,
                "tests/unit/test_normal.py": NOT_EXPECTED,
                "tools/guion.py": EXPECTED,
            }
        )
        self.assertEqual(found, [])
        real = [f for f in _real_findings() if f.rule == "TST-07"]
        self.assertEqual(real, [], "\n" + format_findings(real))


OUTSIDE_TESTCASE = SPDX + (
    "import unittest\n\n\n"
    "def test_suelta():\n"
    '    """RF-001-06: estilo pytest."""\n'
    "    assert 1 == 2\n\n\n"
    "async def test_asincrona_suelta():\n"
    '    """RF-001-06: tampoco se ejecuta."""\n\n\n'
    "if True:\n"
    "    def test_en_un_if():\n"
    '        """RF-001-06: también es del módulo."""\n\n\n'
    "class SinBase:\n"
    "    def test_a(self):\n"
    '        """RF-001-06: la clase no hereda de TestCase."""\n'
    "        assert False\n\n\n"
    "class DeObject(object):\n"
    "    async def test_b(self):\n"
    '        """RF-001-06: tampoco."""\n\n\n'
    "class Hija(SinBase):\n"
    "    def test_c(self):\n"
    '        """RF-001-06: hija de una clase que no es de pruebas."""\n\n\n'
    "class Error(Exception):\n"
    "    def test_d(self):\n"
    '        """RF-001-06: una excepción no es un TestCase."""\n'
)
INSIDE_TESTCASE = SPDX + (
    "import unittest\n\n"
    "from tests.support.base import BaseExterna\n\n\n"
    "def ayuda():\n"
    "    pass\n\n\n"
    "def load_tests(loader, tests, pattern):\n"
    "    return tests\n\n\n"
    "class Mezcla:\n"
    "    def test_compartida(self):\n"
    '        """RF-001-06: la ejecuta la clase de pruebas que hereda de esta."""\n\n\n'
    "class Pruebas(Mezcla, unittest.TestCase):\n"
    "    def test_propia(self):\n"
    '        """RF-001-06: propia."""\n\n\n'
    "class Externa(BaseExterna):\n"
    "    def test_x(self):\n"
    '        """RF-001-06: la base llega de otro módulo: no se juzga."""\n\n\n'
    "def fabrica():\n"
    "    def test_local():\n"
    "        pass\n\n"
    "    class Local:\n"
    "        def test_y(self):\n"
    "            pass\n\n"
    "    return test_local, Local\n"
)


class OutsideTestCaseTest(unittest.TestCase):
    """TST-08: ``unittest`` solo ejecuta los métodos «test…» de las clases que heredan
    de ``TestCase``: una función de módulo ``def test_…`` (estilo pytest) o un método
    ``test_…`` de otra clase no se ejecutan nunca (hallazgo F2 de la ronda 4;
    convergencia, T60)."""

    def test_tests_outside_testcase(self) -> None:
        """RF-001-06 / TST-08: en un fichero de una carpeta de pruebas, las funciones de
        módulo ``def test_…`` (también ``async`` y dentro de un ``if`` de módulo) y los
        métodos ``test_…`` de una clase sin bases, de ``object``, de ``Exception`` o de
        otra clase así se señalan en su línea."""
        found = _found({**SUITES, "tests/unit/test_fuera.py": OUTSIDE_TESTCASE})
        lines = OUTSIDE_TESTCASE.splitlines()
        markers = ("def test_", "async def test_")
        expected = [
            ("tests/unit/test_fuera.py", number, "TST-08")
            for number, line in enumerate(lines, start=1)
            if line.strip().startswith(markers)
        ]
        self.assertEqual(len(expected), 7)
        self.assertEqual(found, expected)
        with temp_tree({**SUITES, "tests/unit/test_fuera.py": OUTSIDE_TESTCASE}) as root:
            messages = [f.message for f in suites.check(root)]
        self.assertIn("«test_suelta»", messages[0])
        self.assertIn("pytest", messages[0])
        self.assertIn("«SinBase»", messages[3])

    def test_tests_inside_testcase_ok(self) -> None:
        """RF-001-06 / TST-08: una mezcla de la que hereda una clase de pruebas del
        módulo, una clase cuya base llega de otro módulo (límite declarado), las
        ayudas, ``load_tests``, lo local de una función y lo de ``tests/support/`` no se
        señalan; ni el árbol real."""
        found = _found(
            {
                **SUITES,
                "tests/unit/test_dentro.py": INSIDE_TESTCASE,
                "tests/support/__init__.py": SPDX,
                "tests/support/ayuda.py": OUTSIDE_TESTCASE,
            }
        )
        self.assertEqual(found, [])
        real = [f for f in _real_findings() if f.rule == "TST-08"]
        self.assertEqual(real, [], "\n" + format_findings(real))


if __name__ == "__main__":
    unittest.main()
