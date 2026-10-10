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
- RNF-001-01, RNF-007-01 (spec 004, T39): con la duración medida de cada módulo (un
  fichero de tiempos), el reparto es por tiempo y no por número de pruebas; sin medidas,
  el de siempre. Cada parte mide la duración de sus módulos (con sus preparaciones de
  módulo y de clase) y la escribe en un fichero, y las medidas de todas las partes
  sustituyen a las guardadas.
"""

import json
import math
import sys
import tempfile
import types
import unittest
from pathlib import Path

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


class FilesTest(unittest.TestCase):
    """Spec 006, T48 (RNF-001-01, RNF-007-01): con los tiempos medidos, cada parte reparte
    los ficheros de prueba en disco sin importarlos y solo importa los suyos; dice cuántos
    módulos tiene de cuántos hay."""

    def test_module_line_and_parse(self) -> None:
        """RF-001-06: «PARTE i de n: m de M módulos», con singular, y se lee de una salida
        con más texto (la última); la de pruebas no es la de módulos ni al revés."""
        self.assertEqual(parts.module_line(2, 16, 12, 192), "PARTE 2 de 16: 12 de 192 módulos")
        self.assertEqual(parts.module_line(1, 1, 1, 1), "PARTE 1 de 1: 1 de 1 módulo")
        text = "x\n" + parts.module_line(1, 3, 2, 9) + "\nRan 3 tests\n" + parts.module_line(
            2, 3, 4, 9)
        self.assertEqual(parts.last_module_line(text), (2, 3, 4, 9))
        self.assertIsNone(parts.last_line(text))
        self.assertIsNone(parts.last_module_line(parts.line(2, 3, 5, 9)))
        self.assertIsNone(parts.last_module_line("  " + parts.module_line(2, 3, 4, 9)))

    def test_part_lines_and_consistency_in_modules(self) -> None:
        """RF-001-06: si alguna parte dice la línea de módulos, se leen todas así y cuadran
        si son 1…n, dicen el mismo total de módulos y suman ese total; si no, el texto
        habla de módulos. Sin ninguna, las de pruebas, como siempre (``describe`` escribe
        cada una con su unidad)."""
        texts = [parts.module_line(1, 2, 3, 5) + "\n", "Ran 1 test\n" + parts.module_line(
            2, 2, 2, 5) + "\n"]
        found, unit = parts.part_lines(texts)
        self.assertEqual((found, unit), ([(1, 2, 3, 5), (2, 2, 2, 5)], parts.MODULES_UNIT))
        self.assertIsNone(parts.consistency(found, 2, unit=unit))
        self.assertEqual(parts.describe(found[0], unit), "PARTE 1 de 2: 3 de 5 módulos")
        classic = [parts.line(1, 2, 3, 5), parts.line(2, 2, 2, 5)]
        self.assertEqual(parts.part_lines(classic),
                         ([(1, 2, 3, 5), (2, 2, 2, 5)], parts.TESTS_UNIT))
        self.assertEqual(parts.describe((1, 2, 3, 5), parts.TESTS_UNIT),
                         "PARTE 1 de 2: 3 de 5 pruebas")
        mixed, unit = parts.part_lines([classic[0], texts[1]])
        self.assertEqual((mixed, unit), ([None, (2, 2, 2, 5)], parts.MODULES_UNIT))
        cases = {
            "una sin la de módulos": (mixed, "cuántos módulos"),
            "totales distintos": ([(1, 2, 3, 5), (2, 2, 2, 6)], "total de módulos"),
            "no suman": ([(1, 2, 3, 5), (2, 2, 1, 5)], "4 de 5 módulos"),
        }
        for name, (lines, text) in cases.items():
            with self.subTest(caso=name):
                problem = parts.consistency(lines, 2, unit=parts.MODULES_UNIT)
                self.assertIsNotNone(problem)
                self.assertIn(text, str(problem))
        self.assertIn("8 de 9 pruebas", str(parts.consistency([(1, 2, 4, 9), (2, 2, 4, 9)], 2)))

    def test_source_affinity(self) -> None:
        """RNF-001-01 (spec 006, T47 y T48): la afinidad de un módulo leída de su fuente,
        sin importarlo: un texto no vacío asignado a ``PART_AFFINITY`` al nivel del
        módulo (también con anotación); si no, o si el fichero no se puede leer o no es
        Python, ``None``."""
        sources = {
            "a.py": 'import os\n\nPART_AFFINITY = "reglas-repositorio"\n',
            "b.py": 'PART_AFFINITY: str = "reglas-extension"\n',
            "c.py": "import unittest\n",
            "d.py": 'PART_AFFINITY = ""\n',
            "e.py": "PART_AFFINITY = 7\n",
            "f.py": 'def f():\n    PART_AFFINITY = "dentro"\n',
            "g.py": "esto no es Python (\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, text in sources.items():
                (folder / name).write_text(text, encoding="utf-8")
            found = {name: parts.source_affinity(folder / name) for name in sources}
            missing = parts.source_affinity(folder / "no_existe.py")
        self.assertEqual(found, {"a.py": "reglas-repositorio", "b.py": "reglas-extension",
                                 "c.py": None, "d.py": None, "e.py": None, "f.py": None,
                                 "g.py": None})
        self.assertIsNone(missing)

    def test_select_files(self) -> None:
        """RNF-001-01, RNF-007-01: los ficheros de ``{módulo: ruta}`` repartidos por su
        tiempo medido (uno nuevo, sin medida, cuenta la media de los medidos) y con su
        afinidad leída de la fuente: cada módulo en una sola parte, la misma en todas, y
        el total es el número de ficheros."""
        sources = {"t/test_a.py": 'PART_AFFINITY = "x"\n', "t/test_b.py": "",
                   "t/test_c.py": 'PART_AFFINITY = "x"\n', "t/test_d.py": "",
                   "t/test_e.py": ""}
        modules = {rel[:-3].replace("/", "."): rel for rel in sources}
        times = {"t.test_a": 1.0, "t.test_b": 4.0, "t.test_c": 1.0, "t.test_d": 2.0}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "t").mkdir()
            for rel, text in sources.items():
                (root / rel).write_text(text, encoding="utf-8")
            chosen = [parts.select_files(modules, root, part, 3, times) for part in (1, 2, 3)]
        # b 4 s; x (a + c) 2 s; d 2 s; e sin medida, la media (2 s): b → 1, x → 2, d → 3,
        # e → 2 (la que lleva menos de las empatadas a 2 s es la 2).
        self.assertEqual(chosen, [(["t.test_b"], 5), (["t.test_a", "t.test_c", "t.test_e"], 5),
                                  (["t.test_d"], 5)])


class _Clock:
    """Un reloj que solo avanza cuando se le pide: las duraciones medidas son exactas."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _fixture_module(
    test: unittest.TestCase,
    name: str,
    log: list[str],
    clock: _Clock,
    seconds: tuple[float, float, float],
) -> unittest.TestSuite:
    """La suite de un módulo ``name`` (registrado en ``sys.modules`` mientras dura la
    prueba) con ``setUpModule``, ``tearDownModule``, una clase con ``setUpClass`` y
    ``tearDownClass`` y una prueba; cada paso se anota en ``log``, y la preparación del
    módulo, la prueba y el cierre del módulo avanzan ``clock`` lo que diga ``seconds``."""
    setup_s, test_s, teardown_s = seconds
    module = types.ModuleType(name)

    def set_up_module() -> None:
        log.append(f"{name}.setUpModule")
        clock.advance(setup_s)

    def tear_down_module() -> None:
        log.append(f"{name}.tearDownModule")
        clock.advance(teardown_s)

    def set_up_class(cls: type) -> None:
        log.append(f"{name}.setUpClass")

    def tear_down_class(cls: type) -> None:
        log.append(f"{name}.tearDownClass")

    def test_it(self: unittest.TestCase) -> None:
        log.append(f"{name}.test")
        clock.advance(test_s)

    module.setUpModule = set_up_module  # type: ignore[attr-defined]
    module.tearDownModule = tear_down_module  # type: ignore[attr-defined]
    cls = type(
        "Caso",
        (unittest.TestCase,),
        {
            "setUpClass": classmethod(set_up_class),
            "tearDownClass": classmethod(tear_down_class),
            "test_it": test_it,
        },
    )
    cls.__module__ = name
    sys.modules[name] = module
    test.addCleanup(sys.modules.pop, name, None)
    loader = unittest.TestLoader()
    return loader.suiteClass([loader.loadTestsFromTestCase(cls)])


class ShareTest(unittest.TestCase):
    """Spec 006, T47 (RNF-001-01, RNF-007-01): las partes de unas suites que van a la vez
    (las carpetas de «motor»), repartidas entre ellas por su tiempo."""

    def test_span(self) -> None:
        """RNF-001-01: lo que tarda la parte más cargada de unas pruebas con ``n``
        partes, con el reparto por tiempo (``assign``)."""
        seconds = [4.0, 3.0, 2.0, 1.0]
        self.assertEqual([parts.span(seconds, n) for n in (1, 2, 3, 4, 5)],
                         [10.0, 5.0, 4.0, 4.0, 4.0])
        self.assertEqual(parts.span([], 3), 0.0)

    def test_share_by_time(self) -> None:
        """RNF-001-01, RNF-007-01: cada suite empieza con dos partes (o las que admita su
        límite) y cada parte más va a la suite que más tarda (a igualdad, la primera),
        aunque haga falta más de una para que tarde menos; si la que más tarda no puede
        tardar menos con las partes que quedan, no se dan más (el paso no acabaría antes
        y solo se cargaría el equipo). Nunca pasa del límite de cada una, ni del total
        salvo con las partes del principio."""
        seconds = {"a": [6.0] * 12, "b": [4.0] * 10, "c": [1.0] * 8}
        limits = {"a": 24, "b": 24, "c": 24}
        # a: 2 → 3 → 4 → 6 (con 5 tardaría lo mismo que con 4); b: 2 → 3 → 4; con a en
        # 12 s, la que más tarda (empatada con b, y antes), ninguna parte más la baja.
        self.assertEqual(parts.share(seconds, limits, 15), {"a": 6, "b": 4, "c": 2})
        self.assertEqual(parts.share(seconds, limits, 9), {"a": 4, "b": 3, "c": 2})
        self.assertEqual(parts.share(seconds, limits, 6), {"a": 2, "b": 2, "c": 2})
        # b, con una sola parte, tarda 40 s: dar más partes a «a» no acabaría antes.
        self.assertEqual(parts.share(seconds, {"a": 3, "b": 1, "c": 24}, 15),
                         {"a": 2, "b": 1, "c": 2})
        self.assertEqual(parts.share({"x": [1.0], "y": [2.0, 1.0]}, {"x": 1, "y": 2}, 2),
                         {"x": 1, "y": 2})
        self.assertEqual(list(parts.share(seconds, limits, 15)), ["a", "b", "c"])

    def test_affinity_goes_together(self) -> None:
        """RNF-001-01, RNF-007-01: los módulos con la misma afinidad (``PART_AFFINITY``,
        las pruebas que pasan las reglas por el repositorio) van a la misma parte, como
        uno solo con sus pesos sumados, en el lugar del primero: así su proceso analiza el
        repositorio una sola vez. Sin afinidad (o con una que no es un texto), como
        siempre; cada parte, en el orden de ``unittest``."""
        sizes, weights = [1, 1, 1, 1, 1, 0], [5.0, 1.0, 1.0, 4.0, 1.0, 0.0]
        alone = parts.assign(sizes, 2, weights)
        self.assertEqual(parts.assign(sizes, 2, weights, [None] * 6), alone)
        self.assertEqual(parts.assign(sizes, 2, weights, ["x", "x", None, None, "x", "x"]),
                         [1, 1, 2, 2, 1, 1])
        self.assertEqual(parts.assign([1, 1, 1], 2, None, ["x", None, "x"]), [1, 2, 1])
        self.assertEqual(parts.AFFINITY_ATTRIBUTE, "PART_AFFINITY")
        values = {0: "reglas", 1: None, 2: "reglas", 3: "", 4: 7}
        for index, value in values.items():
            module = types.ModuleType(f"pruebas.test_m{index}")
            if value is not None:
                setattr(module, parts.AFFINITY_ATTRIBUTE, value)
            sys.modules[module.__name__] = module
            self.addCleanup(sys.modules.pop, module.__name__, None)
        self.assertEqual([parts.affinity_of(f"pruebas.test_m{i}") for i in range(6)],
                         ["reglas", None, "reglas", None, None, None])
        self.assertIsNone(parts.affinity_of(None))
        # Sin afinidad, m0 y m2 (3 s cada uno) irían a partes distintas.
        times = {f"pruebas.test_m{i}": seconds for i, seconds in enumerate([3.0, 1.0, 3.0, 1.0])}
        chosen = [_ids(parts.select(_discovered(1, 1, 1, 1), part, 2, times)[0])
                  for part in (1, 2)]
        self.assertEqual(chosen, [["pruebas.test_m0.C0.test_0", "pruebas.test_m2.C0.test_0"],
                                  ["pruebas.test_m1.C0.test_0", "pruebas.test_m3.C0.test_0"]])


class TimesTest(unittest.TestCase):
    """Spec 004, T39: el reparto por tiempo (RNF-001-01, RNF-007-01)."""

    def test_by_measured_time(self) -> None:
        """RF-004-28, RNF-001-01, RNF-007-01: con pesos (la duración medida de cada
        módulo), de más a menos segundos (a igualdad, en su orden), cada módulo va a la
        parte que lleva menos segundos (a igualdad, la de número menor); sin pesos, por
        número de pruebas, como siempre; lo que no tiene pruebas, a la 1."""
        sizes = [10, 1, 1, 1, 0]
        self.assertEqual(parts.assign(sizes, 2), [1, 2, 2, 2, 1])
        self.assertEqual(parts.assign(sizes, 2, None), [1, 2, 2, 2, 1])
        weights = [1.0, 5.0, 4.0, 0.5, 0.0]
        self.assertEqual(parts.assign(sizes, 2, weights), [2, 1, 2, 1, 1])
        self.assertEqual(parts.assign([1, 1, 1], 3, [0.001] * 3), [1, 2, 3])

    def test_weights_from_measured_modules(self) -> None:
        """RNF-001-01: el peso de un módulo es su duración medida (al menos
        ``MIN_SECONDS``); uno sin medida (nuevo) cuenta sus pruebas por la media por
        prueba de los medidos; sin ninguna medida de los módulos con pruebas, no hay
        pesos (``None``: el reparto por número de pruebas)."""
        sizes = [4, 2, 1, 0]
        names = ["m0", "m1", "m2", None]
        found = parts.weights(sizes, names, {"m0": 2.0, "m1": 3.0, "otro": 9.0})
        assert found is not None
        self.assertEqual(found[:2], [2.0, 3.0])
        self.assertAlmostEqual(found[2], 5.0 / 6.0)
        self.assertEqual(found[3], 0.0)
        self.assertEqual(parts.weights(sizes, names, {"m0": 0.0})[0], parts.MIN_SECONDS)
        for times in ({}, {"otro": 9.0}, {"m3": 1.0}):
            with self.subTest(tiempos=times):
                self.assertIsNone(parts.weights(sizes, names, times))

    def test_select_by_time(self) -> None:
        """RNF-001-01, RNF-007-01, RF-001-06: ``select`` con los tiempos de los módulos
        (por su nombre) reparte por tiempo, cada módulo entero y en el orden de
        ``unittest``; con tiempos de ningún módulo descubierto, igual que sin tiempos."""
        times = {"pruebas.test_m0": 0.1, "pruebas.test_m2": 5.0, "pruebas.test_m3": 0.2}
        by_count = [_ids(parts.select(_discovered(3, 0, 1, 1), part, 2)[0]) for part in (1, 2)]
        self.assertEqual(by_count[0], ["pruebas.test_m0.C0.test_0", "pruebas.test_m0.C1.test_0",
                                       "pruebas.test_m0.C2.test_0"])
        by_time = [
            _ids(parts.select(_discovered(3, 0, 1, 1), part, 2, times)[0]) for part in (1, 2)
        ]
        self.assertEqual(by_time[0], ["pruebas.test_m2.C0.test_0"])
        self.assertEqual(by_time[1], ["pruebas.test_m0.C0.test_0", "pruebas.test_m0.C1.test_0",
                                      "pruebas.test_m0.C2.test_0", "pruebas.test_m3.C0.test_0"])
        unknown = [_ids(parts.select(_discovered(3, 0, 1, 1), part, 2, {"otro": 1.0})[0])
                   for part in (1, 2)]
        self.assertEqual(unknown, by_count)
        self.assertEqual(parts.module_of(_discovered(2)), "pruebas.test_m0")
        self.assertIsNone(parts.module_of(_discovered(0)))

    def test_parts_measure_their_modules(self) -> None:
        """RNF-001-01, RF-001-06: la suite medida de una parte ejecuta lo mismo y en el
        mismo orden que sin medir (cada preparación una vez) y, al terminar, escribe la
        duración de cada módulo con su preparación y su cierre de módulo y de clase (el
        cierre cuenta en su módulo, no en el siguiente), con la parte y las partes."""

        def build(log: list[str], clock: _Clock) -> unittest.TestSuite:
            return unittest.TestSuite([
                _fixture_module(self, "medida_a", log, clock, (1.0, 0.5, 2.0)),
                _fixture_module(self, "medida_b", log, clock, (0.0, 0.25, 0.0)),
            ])

        plain_log: list[str] = []
        unittest.TextTestRunner(stream=_Sink()).run(build(plain_log, _Clock()))
        log: list[str] = []
        clock = _Clock()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "medidas.json"
            suite = parts.measured(build(log, clock), 2, 3, path, clock=clock)
            result = unittest.TextTestRunner(stream=_Sink()).run(suite)
            found = parts.read_measures(path)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 2)
        self.assertEqual(log, plain_log)
        self.assertEqual(log.count("medida_a.tearDownModule"), 1)
        self.assertEqual(found, parts.Measures(2, 3, {"medida_a": 3.5, "medida_b": 0.25}))

    def test_times_files(self) -> None:
        """RNF-001-01: un fichero de tiempos que no existe, que no es JSON, de otro
        esquema o sin módulos no da medidas; de uno válido, solo los segundos finitos y no
        negativos. Lo escrito se lee igual (con la parte en el de medidas)."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(parts.read_times(folder / "no_esta.json"), {})
            self.assertIsNone(parts.read_measures(folder / "no_esta.json"))
            bad = {
                "no es JSON": "{",
                "otro esquema": json.dumps({"schema": "otro/1", "modules": {"a": 1.0}}),
                "sin módulos": json.dumps({"schema": parts.TIMES_SCHEMA}),
                "una lista": json.dumps([1, 2]),
            }
            for name, text in bad.items():
                with self.subTest(caso=name):
                    path = folder / "malo.json"
                    path.write_text(text, encoding="utf-8")
                    self.assertEqual(parts.read_times(path), {})
            path = folder / "mezcla.json"
            modules = {"a": 1.5, "b": -1, "c": "x", "d": True, "e": math.inf, "f": 0}
            path.write_text(
                json.dumps({"schema": parts.TIMES_SCHEMA, "modules": modules}), encoding="utf-8"
            )
            self.assertEqual(parts.read_times(path), {"a": 1.5, "f": 0.0})
            written = folder / "otra" / "tiempos.json"
            parts.write_times(written, {"x": 1.23456, "y": 2.0})
            self.assertEqual(parts.read_times(written), {"x": 1.235, "y": 2.0})
            self.assertIsNone(parts.read_measures(written))  # sin la parte
            parts.write_times(written, {"x": 1.0}, part=1, parts=2)
            self.assertEqual(parts.read_measures(written), parts.Measures(1, 2, {"x": 1.0}))

    def test_merge_and_store(self) -> None:
        """RNF-001-01: las medidas de todas las partes (1…n) de unas pruebas sustituyen a
        las guardadas (un módulo que ya no está desaparece); si falta alguna parte, se
        actualizan las medidas y se conservan las demás. El almacén guarda los tiempos de
        cada suite; uno ilegible es un almacén vacío."""
        stored = {"a": 1.0, "b": 2.0, "viejo": 3.0}
        complete = [parts.Measures(1, 2, {"a": 1.5}), parts.Measures(2, 2, {"b": 2.5, "c": 0.5})]
        self.assertEqual(parts.merge(stored, complete), {"a": 1.5, "b": 2.5, "c": 0.5})
        partial = [parts.Measures(2, 2, {"b": 2.5})]
        self.assertEqual(parts.merge(stored, partial), {"a": 1.0, "b": 2.5, "viejo": 3.0})
        self.assertEqual(parts.merge(stored, []), stored)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "almacen" / "tiempos.json"
            self.assertEqual(parts.read_store(path), {})
            suites = {"python:tests/unit:test*.py": {"a": 1.5}, "blender:x:y": {"b": 0.5}}
            parts.write_store(path, suites)
            self.assertEqual(parts.read_store(path), suites)
            path.write_text("{", encoding="utf-8")
            self.assertEqual(parts.read_store(path), {})


class _Sink:
    """Una salida que descarta lo que se escribe (para ``TextTestRunner``)."""

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
