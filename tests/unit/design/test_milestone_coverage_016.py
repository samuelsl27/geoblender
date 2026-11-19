# SPDX-License-Identifier: GPL-3.0-or-later
"""Qué deja la 016 en el «verde» y qué en el paso «hito» (spec 016, T43; RNF-016-06; plan 016 §7.4 y §5.7 P-13).

La comprobación de cada tarea (``tools/check.py``) tiene que terminar en ≤ 48 s (RNF-001-01) y la 016, con la 015 ya
sobre ese tiempo, tenía que costar ≤ +3 s: las pruebas de la 016 que montan un proyecto en la rejilla de 2 m (la orden
de detectar, de retirar, del contrafuerte y del cuerpo, y lo que dibuja su vista previa) y las de Blender que ejecutan
esas órdenes pasaron a ``milestone_*.py``, que el «verde» no descubre y ejecuta el paso «hito» de ``--completo`` (la
publicación lo pide siempre). Estas pruebas guardan el trato, como las de la 015 (``test_milestone_coverage.py``, que no
se toca): **cada requisito de la 016 tiene al menos una prueba en el «verde»** y lo que lleva cada hito **lo cita**
(el requisito que prueba, y uno que existe).
"""

import re
import unittest
from pathlib import Path

from tests.support.repo import ROOT
from tests.unit.design import test_milestone_coverage as green015

REQUIREMENTS = range(1, 26)
"""Los RF-016-01 a RF-016-25 de la spec (RF-016-23 y RF-016-25, lo de la vista y las órdenes, tienen pruebas de Blender)."""
CITATION = re.compile(r"\bRF-016-(\d\d)\b")


class MilestoneCoverage016Test(unittest.TestCase):
    def test_every_requirement_of_016_has_a_test_in_the_green(self) -> None:
        """RNF-016-06, RF-016-01 a RF-016-25: cada requisito de la 016 lo cita el docstring de al menos una prueba que
        descubre el «verde» (``test*.py`` de ``tests/unit``, ``tests/blender`` y ``tests/referencia``): lo que pasó a
        ``milestone_*.py`` no deja un requisito sin prueba rápida."""
        cited: set[int] = set()
        for path in green015._files("test*.py"):
            if path == Path(__file__).resolve():
                continue  # este fichero cita los 25 requisitos en sus docstrings: no es una prueba de ninguno
            text = path.read_text(encoding="utf-8")
            if "RF-016-" not in text:
                continue
            for docstring in green015._tests(path).values():
                cited.update(int(number) for number in CITATION.findall(docstring))
        missing = [f"RF-016-{number:02d}" for number in REQUIREMENTS if number not in cited]
        self.assertEqual(missing, [], "requisitos de la 016 sin ninguna prueba en el «verde»")

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


if __name__ == "__main__":
    unittest.main()
