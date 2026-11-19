# SPDX-License-Identifier: GPL-3.0-or-later
"""Qué deja la 016 en el «verde» y qué en el paso «hito» (spec 016, T43; RNF-016-06; plan 016 §7.4 y §5.7 P-13).

La comprobación de cada tarea (``tools/check.py``) tiene que terminar en ≤ 48 s (RNF-001-01) y la 016, con la 015 ya
sobre ese tiempo, tenía que costar ≤ +3 s: las pruebas de la 016 que montan un proyecto en la rejilla de 2 m (la orden
de detectar, de retirar, del contrafuerte y del cuerpo, y lo que dibuja su vista previa) y las de Blender que ejecutan
esas órdenes pasaron a ``milestone_*.py``, que el «verde» no descubre y ejecuta el paso «hito» de ``--completo`` (la
publicación lo pide siempre). Estas pruebas guardan el trato, como las de la 015 (``test_milestone_coverage.py``, que no
se toca): **cada requisito de la 016 tiene al menos una prueba en el «verde»** y lo que lleva cada hito **lo cita**
(el requisito que prueba, y uno que existe).

Spec 016, T49 (E-6 de la verificación única): una prueba **cuenta** para un requisito solo si **corre y comprueba algo**.
El guardián de la 015 (y el de la T43) contaba citas en docstrings, y una prueba omitida o vacía que citara los 25
requisitos lo dejaba en verde. Ahora (:func:`running_tests`, por el árbol AST de cada método) no cuenta una prueba
omitida de forma incondicional (``skip``, ``skipIf(True, …)``, ``skipUnless(False, …)``, ``expectedFailure``, ella o su clase;
las omisiones **condicionales** de entorno, con su motivo, siguen contando: TST-07) ni una sin ninguna aserción (``assert``,
``self.assert…``, ``np.testing.assert_…``, ``with self.assertRaises``, ``self.fail``).
"""

import ast
import re
import tempfile
import unittest
from collections.abc import Iterable
from pathlib import Path

from tests.support.repo import ROOT
from tests.unit.design import test_milestone_coverage as green015

REQUIREMENTS = range(1, 26)
"""Los RF-016-01 a RF-016-25 de la spec (RF-016-23 y RF-016-25, lo de la vista y las órdenes, tienen pruebas de Blender)."""
CITATION = re.compile(r"\bRF-016-(\d\d)\b")
NEVER_RUN = {"skip", "expectedFailure"}
"""Los decoradores que omiten una prueba (o la dan por fallida) **siempre**."""
CONDITIONAL = {"skipIf": True, "skipUnless": False}
"""Los que omiten según una condición: solo cuentan como omitidos si la condición es la constante que los omite siempre."""


def _decorator_name(node: ast.expr) -> tuple[str, ast.Call | None]:
    """El nombre final de un decorador (``unittest.skip("x")`` → ``skip``) y su llamada, si la lleva."""
    call = node if isinstance(node, ast.Call) else None
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr, call
    if isinstance(target, ast.Name):
        return target.id, call
    return "", call


def _never_runs(decorators: list[ast.expr]) -> bool:
    """Alguno de los ``decorators`` omite la prueba (o la clase) **de forma incondicional**."""
    for node in decorators:
        name, call = _decorator_name(node)
        if name in NEVER_RUN:
            return True
        if name in CONDITIONAL and call is not None and call.args:
            condition = call.args[0]
            if isinstance(condition, ast.Constant) and bool(condition.value) is CONDITIONAL[name]:
                return True
    return False


def _asserts(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """El cuerpo de ``function`` tiene al menos una aserción: una sentencia ``assert``, una llamada a algo que empieza por
    ``assert`` (``self.assertEqual``, ``self.assertRaises`` con o sin ``with``, ``np.testing.assert_array_equal``) o
    ``self.fail``."""
    for node in ast.walk(function):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call):
            target = node.func
            name = target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else ""
            if name.startswith("assert") or name == "fail":
                return True
    return False


def running_tests(path: Path) -> dict[str, str]:
    """``{"Clase.prueba": docstring}`` de los métodos ``test…`` de las clases del fichero que **corren y comprueban algo**: sin una
    omisión incondicional (de la prueba ni de su clase) y con al menos una aserción en su cuerpo."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or _never_runs(node.decorator_list):
            continue
        for item in node.body:
            if (isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name.startswith("test")
                    and not _never_runs(item.decorator_list) and _asserts(item)):
                found[f"{node.name}.{item.name}"] = ast.get_docstring(item) or ""
    return found


def missing_requirements(paths: Iterable[Path]) -> list[str]:
    """Los ``RF-016-nn`` que no cita el docstring de ninguna prueba de ``paths`` que corre y comprueba algo."""
    cited: set[int] = set()
    for path in paths:
        if "RF-016-" not in path.read_text(encoding="utf-8"):
            continue
        for docstring in running_tests(path).values():
            cited.update(int(number) for number in CITATION.findall(docstring))
    return [f"RF-016-{number:02d}" for number in REQUIREMENTS if number not in cited]


EVERY_RF = ", ".join(f"RF-016-{number:02d}" for number in REQUIREMENTS)


class MilestoneCoverage016Test(unittest.TestCase):
    def test_every_requirement_of_016_has_a_test_in_the_green(self) -> None:
        """RNF-016-06, RF-016-01 a RF-016-25: cada requisito de la 016 lo cita el docstring de al menos una prueba que
        descubre el «verde» (``test*.py`` de ``tests/unit``, ``tests/blender`` y ``tests/referencia``) **y que corre y comprueba
        algo** (E-6, T49: sin una omisión incondicional y con una aserción): lo que pasó a ``milestone_*.py`` no deja un
        requisito sin prueba rápida."""
        paths = [path for path in green015._files("test*.py")
                 if path != Path(__file__).resolve()]  # este fichero cita los 25 requisitos en sus docstrings: no es una prueba de ninguno
        self.assertEqual(missing_requirements(paths), [], "requisitos de la 016 sin ninguna prueba en el «verde»")

    def test_the_moved_milestones_cite_their_requirements(self) -> None:
        """RNF-016-06: cada ``milestone_*.py`` que cita la 016 cita solo requisitos que existen (``RF-016-01`` a
        ``RF-016-25``): un número de más es un error de copia y dejaría el hito sin el requisito que de verdad prueba."""
        milestones = [
            path
            for path in green015._files("milestone_*.py")
            if "RF-016-" in path.read_text(encoding="utf-8")
        ]
        self.assertTrue(milestones, "ningún hito cita la 016")
        for path in milestones:
            with self.subTest(hito=path.relative_to(ROOT).as_posix()):
                text = path.read_text(encoding="utf-8")
                cited = {int(number) for number in CITATION.findall(text)}
                unknown = sorted(number for number in cited if number not in REQUIREMENTS)
                self.assertEqual(unknown, [], "requisitos que la spec no tiene")


class GuardianTest(unittest.TestCase):
    """RNF-016-06, RF-016-01 a RF-016-25 (E-6, T49): el guardián no se burla con una prueba que no corre o que no comprueba nada
    (la sonda ``burl_probe`` de la verificación única, convertida en prueba): ficheros de mentira con las burlas más a mano."""

    def fake(self, body: str) -> Path:
        """Un ``test_fake.py`` de mentira con ``body`` tras su cabecera, en una carpeta temporal que se borra al acabar."""
        folder = tempfile.TemporaryDirectory(prefix="gb-guardian-")
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "test_fake.py"
        path.write_text("# SPDX-License-Identifier: GPL-3.0-or-later\nimport unittest\n\n\n" + body, encoding="utf-8")
        return path

    def test_an_empty_test_that_cites_every_requirement_does_not_cover_any(self) -> None:
        """RNF-016-06, RF-016-01 a RF-016-25: una prueba **vacía** (sin ninguna aserción) cuyo docstring cita los 25 requisitos no
        cubre ninguno: faltan los 25 (con el guardián de la T43, que solo contaba citas, **no faltaba ninguno**)."""
        path = self.fake(f'class EmptyTest(unittest.TestCase):\n    def test_empty(self) -> None:\n        """{EVERY_RF}."""\n        pass\n')
        self.assertEqual(missing_requirements([path]), [f"RF-016-{number:02d}" for number in REQUIREMENTS])

    def test_a_test_that_is_always_skipped_does_not_cover_any_even_with_assertions(self) -> None:
        """RNF-016-06, RF-016-01 a RF-016-25: una prueba omitida de forma incondicional (``skip``, ``skipIf(True)``,
        ``skipUnless(False)``, ``expectedFailure``, ella o su clase) no cubre ningún requisito aunque tenga aserciones."""
        body = (f'@unittest.skip("sí")\nclass SkippedClassTest(unittest.TestCase):\n    def test_a(self) -> None:\n        """{EVERY_RF}."""\n'
                f'        self.assertTrue(True)\n\n\n'
                f'class SkippedTest(unittest.TestCase):\n'
                f'    @unittest.skip("sí")\n    def test_a(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(True)\n\n'
                f'    @unittest.skipIf(True, "sí")\n    def test_b(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(True)\n\n'
                f'    @unittest.skipUnless(False, "sí")\n    def test_c(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(True)\n\n'
                f'    @unittest.expectedFailure\n    def test_d(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(False)\n')
        self.assertEqual(missing_requirements([self.fake(body)]), [f"RF-016-{number:02d}" for number in REQUIREMENTS])

    def test_a_test_that_runs_and_asserts_covers_what_it_cites_and_only_that(self) -> None:
        """RNF-016-06, RF-016-01 a RF-016-25: una prueba con una aserción de cualquier forma (``assert``, ``self.assert…``, ``with
        self.assertRaises``, ``np.testing.assert_…``, ``self.fail``) y las omisiones **condicionales** de entorno (``skipIf`` y
        ``skipUnless`` con una condición que se calcula: TST-07) cubren lo que citan, y nada más."""
        body = ('class RealTest(unittest.TestCase):\n'
                '    def test_a(self) -> None:\n        """RF-016-01."""\n        assert 1 + 1 == 2\n\n'
                '    def test_b(self) -> None:\n        """RF-016-02."""\n        self.assertEqual(1, 1)\n\n'
                '    def test_c(self) -> None:\n        """RF-016-03."""\n        with self.assertRaises(ValueError):\n            int("x")\n\n'
                '    def test_d(self) -> None:\n        """RF-016-04."""\n        np.testing.assert_array_equal(1, 1)\n\n'
                '    def test_e(self) -> None:\n        """RF-016-05."""\n        if False:\n            self.fail("nunca")\n\n'
                '    @unittest.skipUnless(HAS_THE_THING, "[ENTORNO] falta")\n    def test_f(self) -> None:\n        """RF-016-06."""\n'
                '        self.assertTrue(True)\n\n'
                '    @requires(NET, HINT)\n    def test_g(self) -> None:\n        """RF-016-07."""\n        self.assertTrue(True)\n\n'
                '    def test_h(self) -> None:\n        """RF-016-08."""\n        self.helper()\n\n'
                '    def helper(self) -> None:\n        """RF-016-09."""\n        self.assertTrue(True)\n')
        found = missing_requirements([self.fake(body)])
        self.assertEqual(found, [f"RF-016-{number:02d}" for number in range(8, 26)],
                         "RF-016-08 solo lo cita una prueba sin aserción propia (llama a un ayudante); RF-016-09, un ayudante que no es prueba")

    def test_the_real_tests_of_the_repository_are_found_by_the_same_rule(self) -> None:
        """RNF-016-06, RF-016-17: lo que mira el guardián en el repositorio es lo que corre: ``running_tests`` de una prueba real
        (el ``test_buttress`` del dominio) da sus métodos y no cuenta lo que no es de prueba."""
        found = running_tests(ROOT / "tests" / "unit" / "design" / "test_buttress.py")
        self.assertTrue(found)
        self.assertTrue(all(name.split(".")[1].startswith("test") for name in found))
        self.assertTrue(any("RF-016-17" in docstring for docstring in found.values()))


if __name__ == "__main__":
    unittest.main()
