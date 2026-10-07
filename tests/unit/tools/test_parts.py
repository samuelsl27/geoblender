# SPDX-License-Identifier: GPL-3.0-or-later
"""El reparto de unas pruebas en partes que se ejecutan a la vez
(``tools/gbtools/parts.py``; spec 003, T40).

``tools/check.py`` ejecuta las pruebas unitarias en varios procesos de Python
(``tools/unittest_part.py``) y las de Blender en varios Blender
(``tools/run_blender_tests.py --parte``) para terminar en ≤ 40 s (RNF-007-01) sin quitar
ni acortar ninguna prueba: cada proceso descubre todas y ejecuta solo las de su parte.

- RNF-007-01, RF-001-06: cada módulo de pruebas va entero a una sola parte: de más a
  menos pruebas, a la parte que lleva menos; dentro de cada parte, en el orden de
  ``unittest``; lo que no tiene pruebas, a la 1; con tantos módulos con pruebas como
  partes, ninguna queda vacía.
- RF-001-06: cada parte dice, en una línea, cuántas pruebas tiene de cuántas hay; las
  partes de un paso cuadran solo si son 1…n, todas dicen el mismo total y suman ese
  total: si no, el reparto perdió o repitió pruebas.
"""

import unittest

from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import parts  # noqa: E402


def _case(module: str, name: str) -> type[unittest.TestCase]:
    """Una clase de pruebas de ``module`` con las pruebas ``name_0``… (sin importar
    nada: como las que carga ``unittest discover``)."""

    def passing(self: unittest.TestCase) -> None:
        """Pasa."""

    cls = type(name, (unittest.TestCase,), {"test_0": passing, "test_1": passing})
    cls.__module__ = module
    return cls


def _discovered(*sizes: int) -> unittest.TestSuite:
    """Una suite como la de ``discover``: un hijo por módulo (o por ``__init__`` de un
    paquete, vacío), con sus clases dentro; ``sizes`` dice cuántas pruebas tiene cada
    módulo (0, el de un paquete)."""
    loader = unittest.TestLoader()
    children: list[unittest.TestSuite] = []
    for index, size in enumerate(sizes):
        module = f"pruebas.test_m{index}"
        cases: list[unittest.TestCase] = []
        for number in range(size):
            cls = _case(module, f"C{number}")
            cases.append(cls("test_0"))
        inner = loader.suiteClass([loader.suiteClass(cases)]) if cases else loader.suiteClass()
        children.append(inner)
    return loader.suiteClass(children)


def _ids(suite: unittest.TestSuite) -> list[str]:
    found: list[str] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            found.extend(_ids(item))
        else:
            found.append(item.id())
    return found


class ParseTest(unittest.TestCase):
    def test_valid_and_label(self) -> None:
        """RNF-007-01: «i/n» con 1 ≤ i ≤ n es la parte i de n, y ``label`` lo escribe
        igual; la opción es «--parte»."""
        self.assertEqual(parts.OPTION, "--parte")
        for text, expected in (("1/1", (1, 1)), ("2/4", (2, 4)), ("4/4", (4, 4))):
            with self.subTest(valor=text):
                self.assertEqual(parts.parse(text), expected)
                self.assertEqual(parts.label(*expected), text)

    def test_invalid(self) -> None:
        """RNF-007-01: cualquier otra cosa es un error que dice el formato y el valor."""
        for text in ("", "2", "0/4", "5/4", "a/b", "2/0", "-1/2", "2/4/1", " 2/4", "2 /4",
                     "²/4", "1/"):
            with self.subTest(valor=text):
                with self.assertRaises(ValueError) as caught:
                    parts.parse(text)
                self.assertIn("i/n", str(caught.exception))
                self.assertIn(f"«{text}»", str(caught.exception))


class AssignTest(unittest.TestCase):
    def test_largest_first_to_the_lightest_part(self) -> None:
        """RNF-007-01: los módulos con pruebas, de más a menos pruebas (a igualdad, en el
        orden de ``unittest``), van cada uno a la parte que lleva menos pruebas (a
        igualdad, la de número menor); los que no tienen (el ``__init__`` de un paquete),
        a la 1; con una sola parte, todo a la 1. Siempre igual con los mismos tamaños."""
        self.assertEqual(parts.assign([3, 0, 5, 1, 2], 2), [2, 1, 1, 1, 2])
        self.assertEqual(parts.assign([0, 4, 4, 0, 4, 4], 3), [1, 1, 2, 1, 3, 1])
        self.assertEqual(parts.assign([3, 0, 5], 1), [1, 1, 1])
        self.assertEqual(parts.assign([], 4), [])
        sizes = [3, 0, 5, 1, 2, 8, 8, 1]
        self.assertEqual(parts.assign(sizes, 3), parts.assign(list(sizes), 3))

    def test_balanced_by_tests(self) -> None:
        """RNF-007-01: un módulo grande y muchos pequeños se reparten por número de
        pruebas, no por número de módulos (por turno, 15 frente a 5)."""
        sizes = [1, 1, 1, 10, 1, 1, 1, 1, 1, 1, 1]
        owners = parts.assign(sizes, 2)
        loads = [sum(s for s, o in zip(sizes, owners) if o == part) for part in (1, 2)]
        self.assertEqual(loads, [10, 10])

    def test_no_empty_part(self) -> None:
        """RNF-007-01: con al menos tantos módulos con pruebas como partes, ninguna parte
        queda sin pruebas (``tools/check.py`` nunca pide más partes que módulos)."""
        for count in range(1, 7):
            sizes = [0, 2, 0, 1, 7, 3, 0, 1, 1]
            owners = parts.assign(sizes, count)
            with self.subTest(partes=count):
                for part in range(1, count + 1):
                    total = sum(s for s, o in zip(sizes, owners) if o == part)
                    self.assertGreater(total, 0)
                self.assertEqual(set(owners), set(range(1, count + 1)))


class SelectTest(unittest.TestCase):
    def test_every_test_in_exactly_one_part(self) -> None:
        """RF-001-06, RNF-007-01: con cualquier número de partes, la unión de las partes
        es la suite entera, en su orden, sin repetir ninguna prueba; cada módulo va entero
        a una parte, y cada parte sabe el total."""
        suite = _discovered(2, 0, 1, 3, 0, 4, 1)
        every = _ids(suite)
        for count in range(1, 6):
            with self.subTest(partes=count):
                seen: list[str] = []
                for part in range(1, count + 1):
                    selected, total = parts.select(suite, part, count)
                    self.assertIsInstance(selected, unittest.TestSuite)
                    self.assertEqual(total, len(every))
                    ids = _ids(selected)
                    self.assertEqual(ids, [i for i in every if i in ids], "en su orden")
                    modules = {i.rsplit(".", 2)[0] for i in ids}
                    for module in modules:
                        whole = [i for i in every if i.rsplit(".", 2)[0] == module]
                        self.assertEqual([i for i in ids if i in whole], whole)
                    seen.extend(ids)
                self.assertEqual(sorted(seen), sorted(every))
                self.assertEqual(len(seen), len(set(seen)))

    def test_suite_is_not_consumed(self) -> None:
        """RNF-007-01: elegir una parte no cambia la suite descubierta (se puede elegir
        otra después)."""
        suite = _discovered(1, 2, 3)
        before = _ids(suite)
        parts.select(suite, 1, 2)
        self.assertEqual(_ids(suite), before)


class LineTest(unittest.TestCase):
    def test_line_and_parse(self) -> None:
        """RF-001-06: «PARTE i de n: r de T pruebas», con singular, y se lee de una
        salida con más texto (la última de cada salida)."""
        self.assertEqual(parts.line(2, 4, 241, 966), "PARTE 2 de 4: 241 de 966 pruebas")
        self.assertEqual(parts.line(1, 1, 1, 1), "PARTE 1 de 1: 1 de 1 prueba")
        text = "otra cosa\nPARTE 1 de 2: 0 de 0 pruebas\nRan 3 tests\n" + parts.line(
            2, 3, 5, 9
        )
        self.assertEqual(parts.last_line(text), (2, 3, 5, 9))
        self.assertIsNone(parts.last_line("  PARTE 2 de 3: 5 de 9 pruebas\n"))
        self.assertIsNone(parts.last_line("Ran 3 tests\nOK\n"))


class ConsistencyTest(unittest.TestCase):
    def test_consistent(self) -> None:
        """RF-001-06: las partes 1…n con el mismo total y que suman ese total cuadran."""
        found = [(1, 3, 4, 9), (2, 3, 3, 9), (3, 3, 2, 9)]
        self.assertIsNone(parts.consistency(found, 3))

    def test_inconsistent(self) -> None:
        """RF-001-06: una parte sin su línea, una que no es la que se pidió, totales
        distintos o partes que no suman el total son un problema, y el texto lo dice."""
        cases = {
            "sin línea": ([(1, 2, 4, 9), None], 2, "parte 2"),
            "otra parte": ([(1, 2, 4, 9), (1, 2, 5, 9)], 2, "parte 2"),
            "otro número de partes": ([(1, 2, 4, 9), (2, 3, 5, 9)], 2, "parte 2"),
            "totales distintos": ([(1, 2, 4, 9), (2, 2, 5, 10)], 2, "total"),
            "no suman": ([(1, 2, 4, 9), (2, 2, 4, 9)], 2, "8 de 9"),
            "repiten": ([(1, 2, 5, 9), (2, 2, 5, 9)], 2, "10 de 9"),
            "faltan partes": ([(1, 2, 9, 9)], 2, "1 de 2"),
        }
        for name, (found, count, text) in cases.items():
            with self.subTest(caso=name):
                problem = parts.consistency(found, count)
                self.assertIsNotNone(problem)
                self.assertIn(text, str(problem))


if __name__ == "__main__":
    unittest.main()
