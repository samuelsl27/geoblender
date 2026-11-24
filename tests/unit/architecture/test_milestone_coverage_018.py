# SPDX-License-Identifier: GPL-3.0-or-later
"""Qué deja la 018 en el «verde» y qué en el paso «hito» (spec 018, T36; RNF-018-10; plan 018 §7.4).

La comprobación de cada tarea (``tools/check.py``) tiene que costar poco (RNF-001-01) y la 018 tenía que costar ≤ +3 s (RNF-018-10): las pruebas de la 018 que montan un proyecto en la rejilla de 2 m,
o que pasan de 1 s, son ``milestone_*.py`` (el «verde» no los descubre y los ejecuta el paso «hito» de ``--completo``; la publicación lo pide siempre). Estas pruebas guardan el trato, como las de la
017 (``test_milestone_coverage_017.py``, que no se toca): **cada requisito de la 018 tiene al menos una prueba en el «verde» que corre y comprueba algo** (E-6 de la 016: una prueba omitida de forma
incondicional o sin ninguna aserción no cuenta) y lo que lleva cada hito **lo cita** (y cita requisitos que existen).

El requisito RF-018-32 (la vista previa en pantalla) **solo se puede comprobar con una pantalla y un ratón**: lo cierra el H3 (T40, manual; plan 018 §7.2) y se excluye por su nombre, en
:data:`WITHOUT_GREEN_TEST`, sin exigirle una prueba; si algún día tiene una automática, se quita de ahí.
"""

import re
import tempfile
import unittest
from collections.abc import Iterable
from pathlib import Path

from tests.support.repo import ROOT
from tests.unit.design import test_milestone_coverage as green015
from tests.unit.design.test_milestone_coverage_016 import running_tests

ALL_REQUIREMENTS = range(1, 36)
"""Los RF-018-01 a RF-018-35 de la spec."""
WITHOUT_GREEN_TEST = {32: "RF-018-32 (la vista previa en pantalla: manual en el H3, T40)"}
"""Los requisitos que cierra el H3 en pantalla, con el porqué: no se les exige prueba en el «verde» (``RF-018-32``)."""
REQUIREMENTS = [number for number in ALL_REQUIREMENTS if number not in WITHOUT_GREEN_TEST]
"""Los RF-018-nn a los que se exige una prueba rápida en el «verde»."""
CITATION = re.compile(r"\bRF-018-(\d\d)\b")


def missing_requirements(paths: Iterable[Path]) -> list[str]:
    """Los ``RF-018-nn`` exigidos (:data:`REQUIREMENTS`) que no cita el docstring de ninguna prueba de ``paths`` que corre y comprueba algo
    (:func:`running_tests` de la 016: sin una omisión incondicional y con al menos una aserción)."""
    cited: set[int] = set()
    for path in paths:
        if "RF-018-" not in path.read_text(encoding="utf-8"):
            continue
        for docstring in running_tests(path).values():
            cited.update(int(number) for number in CITATION.findall(docstring))
    return [f"RF-018-{number:02d}" for number in REQUIREMENTS if number not in cited]


EVERY_RF = ", ".join(f"RF-018-{number:02d}" for number in ALL_REQUIREMENTS)


class MilestoneCoverage018Test(unittest.TestCase):
    def test_every_requirement_of_018_has_a_test_in_the_green(self) -> None:
        """RNF-018-10, RF-018-01 a RF-018-35 (salvo el 32): cada requisito de la 018 lo cita el docstring de al menos una prueba que descubre el «verde» (``test*.py`` de ``tests/unit``,
        ``tests/blender`` y ``tests/referencia``) **y que corre y comprueba algo**: lo que pasó a ``milestone_*.py`` no deja un requisito sin prueba rápida."""
        paths = [path for path in green015._files("test*.py")
                 if path != Path(__file__).resolve()]  # este fichero cita los 35 requisitos en sus docstrings: no es una prueba de ninguno
        self.assertEqual(missing_requirements(paths), [], "requisitos de la 018 sin ninguna prueba en el «verde»")

    def test_the_requirement_left_to_the_h3_is_the_only_exclusion(self) -> None:
        """RNF-018-10: lo único que se excluye del guardián es lo que cierra el H3 en pantalla (RF-018-32), por su nombre: los otros 34 requisitos (RF-018-01 a RF-018-35 salvo el 32) se exigen."""
        self.assertEqual(sorted(WITHOUT_GREEN_TEST), [32])
        self.assertEqual(len(REQUIREMENTS), 34)
        self.assertNotIn(32, REQUIREMENTS)
        self.assertIn(35, REQUIREMENTS)

    def test_the_moved_milestones_cite_their_requirements(self) -> None:
        """RNF-018-10: cada ``milestone_*.py`` que cita la 018 cita solo requisitos que existen (``RF-018-01`` a ``RF-018-35``): un número de más es un error de copia y dejaría el hito sin el
        requisito que de verdad prueba."""
        milestones = [path for path in green015._files("milestone_*.py") if "RF-018-" in path.read_text(encoding="utf-8")]
        self.assertTrue(milestones, "ningún hito cita la 018")
        for path in milestones:
            with self.subTest(hito=path.relative_to(ROOT).as_posix()):
                text = path.read_text(encoding="utf-8")
                cited = {int(number) for number in CITATION.findall(text)}
                unknown = sorted(number for number in cited if number not in ALL_REQUIREMENTS)
                self.assertEqual(unknown, [], "requisitos que la spec no tiene")


class GuardianTest(unittest.TestCase):
    """RNF-018-10, RF-018-01 a RF-018-35 (E-6 de la 016): el guardián no se burla con una prueba que no corre o que no comprueba nada: ficheros de mentira con las burlas más a mano."""

    def fake(self, body: str) -> Path:
        """Un ``test_fake.py`` de mentira con ``body`` tras su cabecera, en una carpeta temporal que se borra al acabar."""
        folder = tempfile.TemporaryDirectory(prefix="gb-guardian-")
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "test_fake.py"
        path.write_text("# SPDX-License-Identifier: GPL-3.0-or-later\nimport unittest\n\n\n" + body, encoding="utf-8")
        return path

    def test_an_empty_test_that_cites_every_requirement_does_not_cover_any(self) -> None:
        """RNF-018-10, RF-018-01 a RF-018-35: una prueba **vacía** (sin ninguna aserción) cuyo docstring cita los 35 requisitos no cubre ninguno: faltan los 34 exigidos."""
        path = self.fake(f'class EmptyTest(unittest.TestCase):\n    def test_empty(self) -> None:\n        """{EVERY_RF}."""\n        pass\n')
        self.assertEqual(missing_requirements([path]), [f"RF-018-{number:02d}" for number in REQUIREMENTS])

    def test_a_test_that_is_always_skipped_does_not_cover_any_even_with_assertions(self) -> None:
        """RNF-018-10, RF-018-01 a RF-018-35: una prueba omitida de forma incondicional (``skip``, ``skipIf(True)``, ``skipUnless(False)``, ``expectedFailure``, ella o su clase) no cubre ningún
        requisito aunque tenga aserciones."""
        body = (f'@unittest.skip("sí")\nclass SkippedClassTest(unittest.TestCase):\n    def test_a(self) -> None:\n        """{EVERY_RF}."""\n'
                f'        self.assertTrue(True)\n\n\n'
                f'class SkippedTest(unittest.TestCase):\n'
                f'    @unittest.skip("sí")\n    def test_a(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(True)\n\n'
                f'    @unittest.skipIf(True, "sí")\n    def test_b(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(True)\n\n'
                f'    @unittest.skipUnless(False, "sí")\n    def test_c(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(True)\n\n'
                f'    @unittest.expectedFailure\n    def test_d(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(False)\n')
        self.assertEqual(missing_requirements([self.fake(body)]), [f"RF-018-{number:02d}" for number in REQUIREMENTS])

    def test_a_test_that_runs_and_asserts_covers_what_it_cites_and_only_that(self) -> None:
        """RNF-018-10, RF-018-01 a RF-018-35: una prueba con una aserción de cualquier forma (``assert``, ``self.assert…``, ``with self.assertRaises``, ``np.testing.assert_…``, ``self.fail``) y las
        omisiones **condicionales** de entorno (``skipIf`` y ``skipUnless`` con una condición que se calcula: TST-07) cubren lo que citan, y nada más; un ayudante que no es prueba y una prueba sin
        aserción propia que llama a un ayudante no cuentan."""
        body = ('class RealTest(unittest.TestCase):\n'
                '    def test_a(self) -> None:\n        """RF-018-01."""\n        assert 1 + 1 == 2\n\n'
                '    def test_b(self) -> None:\n        """RF-018-02."""\n        self.assertEqual(1, 1)\n\n'
                '    def test_c(self) -> None:\n        """RF-018-03."""\n        with self.assertRaises(ValueError):\n            int("x")\n\n'
                '    def test_d(self) -> None:\n        """RF-018-04."""\n        np.testing.assert_array_equal(1, 1)\n\n'
                '    def test_e(self) -> None:\n        """RF-018-05."""\n        if False:\n            self.fail("nunca")\n\n'
                '    @unittest.skipUnless(HAS_THE_THING, "[ENTORNO] falta")\n    def test_f(self) -> None:\n        """RF-018-06."""\n'
                '        self.assertTrue(True)\n\n'
                '    @requires(NET, HINT)\n    def test_g(self) -> None:\n        """RF-018-07."""\n        self.assertTrue(True)\n\n'
                '    def test_h(self) -> None:\n        """RF-018-08."""\n        self.helper()\n\n'
                '    def helper(self) -> None:\n        """RF-018-09."""\n        self.assertTrue(True)\n')
        found = missing_requirements([self.fake(body)])
        self.assertEqual(found, [f"RF-018-{number:02d}" for number in REQUIREMENTS if number >= 8],
                         "RF-018-08 solo lo cita una prueba sin aserción propia (llama a un ayudante); RF-018-09, un ayudante que no es prueba")

    def test_the_requirement_left_to_the_h3_is_not_asked_for(self) -> None:
        """RNF-018-10, RF-018-35: citar o no citar el RF-018-32 (H3, manual) no cambia lo que falta: se excluye por su nombre, y el resto se sigue exigiendo (una prueba que solo cita el 32 no cubre el 35)."""
        body = ('class OnlyThirtyTwoTest(unittest.TestCase):\n'
                '    def test_a(self) -> None:\n        """RF-018-32."""\n        self.assertTrue(True)\n')
        found = missing_requirements([self.fake(body)])
        self.assertNotIn("RF-018-32", found)
        self.assertIn("RF-018-35", found)
        self.assertEqual(len(found), 34)

    def test_the_real_tests_of_the_repository_are_found_by_the_same_rule(self) -> None:
        """RNF-018-10, RF-018-13: lo que mira el guardián en el repositorio es lo que corre: ``running_tests`` de una prueba real (``test_pit_scale_fixes``) da sus métodos y no cuenta lo que no es de
        prueba."""
        found = running_tests(ROOT / "tests" / "unit" / "design" / "test_pit_scale_fixes.py")
        self.assertTrue(found)
        self.assertTrue(all(name.split(".")[1].startswith("test") for name in found))
        self.assertTrue(any("RF-018-13" in docstring for docstring in found.values()))


if __name__ == "__main__":
    unittest.main()
