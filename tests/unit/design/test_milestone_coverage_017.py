# SPDX-License-Identifier: GPL-3.0-or-later
"""Qué deja la 017 en el «verde» y qué en el paso «hito» (spec 017, T34b; RNF-017-09; plan 017 §7.4 y §5.7 P-12).

La comprobación de cada tarea (``tools/check.py``) tiene que terminar en ≤ 48 s (RNF-001-01) y la 017 tenía que costar ≤ +3 s
(RNF-017-09): las pruebas de la 017 que montan un proyecto en la rejilla de 2 m, o que pasan de 1 s, son ``milestone_*.py``
(el «verde» no los descubre y los ejecuta el paso «hito» de ``--completo``; la publicación lo pide siempre). Estas pruebas
guardan el trato, como las de la 016 (``test_milestone_coverage_016.py``, que no se toca): **cada requisito de la 017 tiene al
menos una prueba en el «verde» que corre y comprueba algo** (E-6 de la 016: una prueba omitida de forma incondicional o sin
ninguna aserción no cuenta) y lo que lleva cada hito **lo cita** (y cita requisitos que existen).

El requisito RF-017-19 (la rasante de mínimo movimiento por programación lineal, prioridad P3) **no tiene tarea** (S-3 de la
spec): se excluye por su nombre, en :data:`WITHOUT_TASK`, y no se exige prueba; si algún día se implementa, se quita de ahí.
"""

import re
import tempfile
import unittest
from collections.abc import Iterable
from pathlib import Path

from tests.support.repo import ROOT
from tests.unit.design import test_milestone_coverage as green015
from tests.unit.design.test_milestone_coverage_016 import running_tests

ALL_REQUIREMENTS = range(1, 31)
"""Los RF-017-01 a RF-017-30 de la spec."""
WITHOUT_TASK = {19: "S-3 (rasante por programación lineal, P3: sin tarea)"}
"""Los requisitos que la spec deja **sin tarea**, con el porqué: no se les exige prueba (``RF-017-19``, S-3)."""
REQUIREMENTS = [number for number in ALL_REQUIREMENTS if number not in WITHOUT_TASK]
"""Los RF-017-nn a los que se exige una prueba rápida en el «verde»."""
CITATION = re.compile(r"\bRF-017-(\d\d)\b")


def missing_requirements(paths: Iterable[Path]) -> list[str]:
    """Los ``RF-017-nn`` exigidos (:data:`REQUIREMENTS`) que no cita el docstring de ninguna prueba de ``paths`` que corre y
    comprueba algo (:func:`running_tests` de la 016: sin una omisión incondicional y con al menos una aserción)."""
    cited: set[int] = set()
    for path in paths:
        if "RF-017-" not in path.read_text(encoding="utf-8"):
            continue
        for docstring in running_tests(path).values():
            cited.update(int(number) for number in CITATION.findall(docstring))
    return [f"RF-017-{number:02d}" for number in REQUIREMENTS if number not in cited]


EVERY_RF = ", ".join(f"RF-017-{number:02d}" for number in ALL_REQUIREMENTS)


class MilestoneCoverage017Test(unittest.TestCase):
    def test_every_requirement_of_017_has_a_test_in_the_green(self) -> None:
        """RNF-017-09, RF-017-01 a RF-017-30 (salvo el 19, S-3): cada requisito de la 017 lo cita el docstring de al menos una
        prueba que descubre el «verde» (``test*.py`` de ``tests/unit``, ``tests/blender`` y ``tests/referencia``) **y que corre
        y comprueba algo**: lo que pasó a ``milestone_*.py`` no deja un requisito sin prueba rápida."""
        paths = [path for path in green015._files("test*.py")
                 if path != Path(__file__).resolve()]  # este fichero cita los 30 requisitos en sus docstrings: no es una prueba de ninguno
        self.assertEqual(missing_requirements(paths), [], "requisitos de la 017 sin ninguna prueba en el «verde»")

    def test_the_requirement_left_without_a_task_is_the_only_exclusion(self) -> None:
        """RNF-017-09: lo único que se excluye del guardián es lo que la spec deja sin tarea (RF-017-19, S-3), por su nombre:
        los otros 29 requisitos (RF-017-01 a RF-017-30 salvo el 19) se exigen."""
        self.assertEqual(sorted(WITHOUT_TASK), [19])
        self.assertEqual(len(REQUIREMENTS), 29)
        self.assertNotIn(19, REQUIREMENTS)
        self.assertIn(30, REQUIREMENTS)

    def test_the_moved_milestones_cite_their_requirements(self) -> None:
        """RNF-017-09: cada ``milestone_*.py`` que cita la 017 cita solo requisitos que existen (``RF-017-01`` a
        ``RF-017-30``): un número de más es un error de copia y dejaría el hito sin el requisito que de verdad prueba."""
        milestones = [
            path
            for path in green015._files("milestone_*.py")
            if "RF-017-" in path.read_text(encoding="utf-8")
        ]
        self.assertTrue(milestones, "ningún hito cita la 017")
        for path in milestones:
            with self.subTest(hito=path.relative_to(ROOT).as_posix()):
                text = path.read_text(encoding="utf-8")
                cited = {int(number) for number in CITATION.findall(text)}
                unknown = sorted(number for number in cited if number not in ALL_REQUIREMENTS)
                self.assertEqual(unknown, [], "requisitos que la spec no tiene")


class GuardianTest(unittest.TestCase):
    """RNF-017-09, RF-017-01 a RF-017-30 (E-6 de la 016): el guardián no se burla con una prueba que no corre o que no comprueba
    nada: ficheros de mentira con las burlas más a mano."""

    def fake(self, body: str) -> Path:
        """Un ``test_fake.py`` de mentira con ``body`` tras su cabecera, en una carpeta temporal que se borra al acabar."""
        folder = tempfile.TemporaryDirectory(prefix="gb-guardian-")
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "test_fake.py"
        path.write_text("# SPDX-License-Identifier: GPL-3.0-or-later\nimport unittest\n\n\n" + body, encoding="utf-8")
        return path

    def test_an_empty_test_that_cites_every_requirement_does_not_cover_any(self) -> None:
        """RNF-017-09, RF-017-01 a RF-017-30: una prueba **vacía** (sin ninguna aserción) cuyo docstring cita los 30 requisitos
        no cubre ninguno: faltan los 29 exigidos (los 30 menos el 19, que la spec deja sin tarea)."""
        path = self.fake(f'class EmptyTest(unittest.TestCase):\n    def test_empty(self) -> None:\n        """{EVERY_RF}."""\n        pass\n')
        self.assertEqual(missing_requirements([path]), [f"RF-017-{number:02d}" for number in REQUIREMENTS])

    def test_a_test_that_is_always_skipped_does_not_cover_any_even_with_assertions(self) -> None:
        """RNF-017-09, RF-017-01 a RF-017-30: una prueba omitida de forma incondicional (``skip``, ``skipIf(True)``,
        ``skipUnless(False)``, ``expectedFailure``, ella o su clase) no cubre ningún requisito aunque tenga aserciones."""
        body = (f'@unittest.skip("sí")\nclass SkippedClassTest(unittest.TestCase):\n    def test_a(self) -> None:\n        """{EVERY_RF}."""\n'
                f'        self.assertTrue(True)\n\n\n'
                f'class SkippedTest(unittest.TestCase):\n'
                f'    @unittest.skip("sí")\n    def test_a(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(True)\n\n'
                f'    @unittest.skipIf(True, "sí")\n    def test_b(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(True)\n\n'
                f'    @unittest.skipUnless(False, "sí")\n    def test_c(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(True)\n\n'
                f'    @unittest.expectedFailure\n    def test_d(self) -> None:\n        """{EVERY_RF}."""\n        self.assertTrue(False)\n')
        self.assertEqual(missing_requirements([self.fake(body)]), [f"RF-017-{number:02d}" for number in REQUIREMENTS])

    def test_a_test_that_runs_and_asserts_covers_what_it_cites_and_only_that(self) -> None:
        """RNF-017-09, RF-017-01 a RF-017-30: una prueba con una aserción de cualquier forma (``assert``, ``self.assert…``,
        ``with self.assertRaises``, ``np.testing.assert_…``, ``self.fail``) y las omisiones **condicionales** de entorno
        (``skipIf`` y ``skipUnless`` con una condición que se calcula: TST-07) cubren lo que citan, y nada más; un ayudante que
        no es prueba y una prueba sin aserción propia que llama a un ayudante no cuentan."""
        body = ('class RealTest(unittest.TestCase):\n'
                '    def test_a(self) -> None:\n        """RF-017-01."""\n        assert 1 + 1 == 2\n\n'
                '    def test_b(self) -> None:\n        """RF-017-02."""\n        self.assertEqual(1, 1)\n\n'
                '    def test_c(self) -> None:\n        """RF-017-03."""\n        with self.assertRaises(ValueError):\n            int("x")\n\n'
                '    def test_d(self) -> None:\n        """RF-017-04."""\n        np.testing.assert_array_equal(1, 1)\n\n'
                '    def test_e(self) -> None:\n        """RF-017-05."""\n        if False:\n            self.fail("nunca")\n\n'
                '    @unittest.skipUnless(HAS_THE_THING, "[ENTORNO] falta")\n    def test_f(self) -> None:\n        """RF-017-06."""\n'
                '        self.assertTrue(True)\n\n'
                '    @requires(NET, HINT)\n    def test_g(self) -> None:\n        """RF-017-07."""\n        self.assertTrue(True)\n\n'
                '    def test_h(self) -> None:\n        """RF-017-08."""\n        self.helper()\n\n'
                '    def helper(self) -> None:\n        """RF-017-09."""\n        self.assertTrue(True)\n')
        found = missing_requirements([self.fake(body)])
        self.assertEqual(found, [f"RF-017-{number:02d}" for number in REQUIREMENTS if number >= 8],
                         "RF-017-08 solo lo cita una prueba sin aserción propia (llama a un ayudante); RF-017-09, un ayudante que no es prueba")

    def test_the_requirement_without_a_task_is_not_asked_for(self) -> None:
        """RNF-017-09, RF-017-30: citar o no citar el RF-017-19 (S-3, sin tarea) no cambia lo que falta: se excluye por su
        nombre, y el resto se sigue exigiendo (una prueba que solo cita el 19 no cubre el 30)."""
        body = ('class OnlyNineteenTest(unittest.TestCase):\n'
                '    def test_a(self) -> None:\n        """RF-017-19."""\n        self.assertTrue(True)\n')
        found = missing_requirements([self.fake(body)])
        self.assertNotIn("RF-017-19", found)
        self.assertIn("RF-017-30", found)
        self.assertEqual(len(found), 29)

    def test_the_real_tests_of_the_repository_are_found_by_the_same_rule(self) -> None:
        """RNF-017-09, RF-017-21: lo que mira el guardián en el repositorio es lo que corre: ``running_tests`` de una prueba real
        (el ``test_road_engrave`` del dominio) da sus métodos y no cuenta lo que no es de prueba."""
        found = running_tests(ROOT / "tests" / "unit" / "design" / "test_road_engrave.py")
        self.assertTrue(found)
        self.assertTrue(all(name.split(".")[1].startswith("test") for name in found))
        self.assertTrue(any("RF-017-21" in docstring for docstring in found.values()))


if __name__ == "__main__":
    unittest.main()
