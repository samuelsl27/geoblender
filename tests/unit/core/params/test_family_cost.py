# SPDX-License-Identifier: GPL-3.0-or-later
"""El coste de registrar las familias de parámetros (spec 016, T51; RNF-001-03 de la spec 001;
ADR-0027; plan 016 §7.4).

Habilitar Geoblender en Blender 5.2.1 en segundo plano tarda ≤ 0,5 s (RNF-001-03) y las 105
familias de ``des`` (35 con la 015, 70 más con la 016) pasaban de los 0,5 s: registrarlas
comparaba **cada pareja** de patrones (5.460 llamadas a ``overlaps``, crecimiento cuadrático) y
cada clave registrada con cada patrón, y construir cada familia **compilaba** su expresión
regular aunque nadie la usara hasta la primera consulta. Estas pruebas fijan lo que arregló la
T51, sin cambiar lo que dice ``core.params``:

- registrar un lote de familias que no se solapan no compara todas las parejas ni todas las
  claves con todos los patrones (el recuento de comparaciones es lineal);
- construir una familia y casar una clave con ella no compila una expresión regular por patrón;
- el resultado es el mismo que el de la comprobación pareja a pareja de antes: los problemas, su
  texto y su orden (contra una copia independiente de aquel algoritmo, con familias al azar), y
  ``match`` y la admisión de la plantilla en la construcción dan lo mismo que la expresión regular.
"""

from __future__ import annotations

import dataclasses
import random
import re
import unittest
import uuid
from typing import Any
from unittest import mock

from tests.support.package import import_geoblender

params = import_geoblender("core.params")
model = import_geoblender("core.params.model")

ParamDef = params.ParamDef
ParamFamily = params.ParamFamily

MODULE = "res"
VARIABLE = re.compile(r"\{[a-z][a-z0-9_]*\}")
SEGMENT = "[a-z][a-z0-9_]*"
TEMPLATE = ParamDef(
    "res.x.y", "float", "t/m3", None, 0.0, 10.0, ("RNF-001-03",),
    "Prueba: coste del registro de familias", min_exclusive=True, allow_empty=True,
    kind="HIPÓTESIS", source_kind="document", label_msgid="In-situ density",
)


def template(key: str) -> ParamDef:
    return dataclasses.replace(TEMPLATE, key=key)


def concrete_key(pattern: str) -> str:
    """Una clave que casa con ``pattern``: cada variable, ``v``."""
    return ".".join("v" if VARIABLE.fullmatch(part) else part for part in pattern.split("."))


def make(pattern: str) -> Any:
    return ParamFamily(pattern, template(concrete_key(pattern)))


def reference_overlap(one: str, other: str) -> bool:
    """La definición de «solapar» de ``ParamFamily.overlaps`` de antes de la T51 (copia
    independiente, sin la forma memorizada)."""
    mine, theirs = one.split("."), other.split(".")
    return len(mine) == len(theirs) and all(
        a == b or VARIABLE.fullmatch(a) is not None or VARIABLE.fullmatch(b) is not None
        for a, b in zip(mine, theirs, strict=True))


def reference_match(pattern: str, key: object) -> bool:
    """Si ``key`` casa con ``pattern``: una expresión regular por patrón, como antes de la T51."""
    parts = [f"({SEGMENT})" if VARIABLE.fullmatch(part) else re.escape(part)
             for part in pattern.split(".")]
    return isinstance(key, str) and re.compile(r"\.".join(parts)).fullmatch(key) is not None


def reference_message(registered: list[str], batch: list[str], keys: list[str]) -> str | None:
    """El ``ValueError`` de ``register_families`` de antes de la T51 (la comprobación de cada
    pareja y de cada clave con cada patrón), o ``None`` si el lote se registra."""
    problems: list[str] = []
    for position, pattern in enumerate(batch):
        for other in (*registered, *batch[:position]):
            if other == pattern:
                problems.append(f"«{pattern}» ya está registrada o repetida")
            elif reference_overlap(pattern, other):
                problems.append(f"«{pattern}» solapa con «{other}»")
        problems.extend(f"«{pattern}» casa con la clave registrada «{key}»"
                        for key in keys if reference_match(pattern, key))
    if not problems:
        return None
    return (f"familia de parámetros ya registrada, repetida o que solapa: "
            f"{'; '.join(problems)}. Cada clave concreta es de una sola definición "
            "(unregister_families antes de volver a registrarla)")


def random_pattern(rng: random.Random) -> str:
    """Un patrón bien formado de ``res`` de 2 a 5 segmentos, con al menos una variable."""
    while True:
        parts = [rng.choice(("a", "b", "unit", f"{{v{index}}}")) for index in range(rng.randint(1, 4))]
        if any(VARIABLE.fullmatch(part) for part in parts):
            return ".".join((MODULE, *parts))


class FamilyRegistrationCostTest(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(params.unregister_families, MODULE)
        self.addCleanup(params.unregister_definitions, MODULE)

    def test_a_building_and_matching_a_family_compiles_no_regular_expression(self) -> None:
        """RNF-001-03: construir una familia comprueba su patrón y que su plantilla casa con él, y
        ``match`` casa una clave, **sin compilar** una expresión regular por patrón (cada una
        costaba ≈ 50 µs en cada habilitación: 105 familias, ≈ 5 ms)."""
        token = uuid.uuid4().hex[:8]
        patterns = [f"res.cost{token}{index}.{{u}}.value" for index in range(60)]
        with mock.patch.object(model.re, "compile", wraps=re.compile) as compiled:
            families = [make(pattern) for pattern in patterns]
            self.assertEqual(families[0].match(f"res.cost{token}0.capa.value"), ("capa",))
            self.assertEqual(families[0].match(f"res.cost{token}0.otra.value"), ("otra",))
            self.assertIsNone(families[1].match(f"res.cost{token}0.capa.value"))
            self.assertIsNone(families[1].match("res.capa"))
        self.assertEqual(compiled.call_count, 0)

    def test_b_registering_does_not_compare_every_pair_or_every_key(self) -> None:
        """RNF-001-03: registrar 400 familias que no se solapan, con 40 claves registradas, no
        compara cada pareja de patrones (79.800 llamadas a ``overlaps``) ni cada clave con cada
        patrón (16.000 a ``match``): el número de comparaciones es lineal."""
        count = 400
        families = [make(f"res.shape{index}.{{u}}.value") for index in range(count)]
        params.register_definitions(
            tuple(ParamDef(f"res.fixed{index}", "float", "-", 1.0, 0.0, 2.0, ("RNF-001-03",),
                           "Prueba: clave fija") for index in range(40)))
        calls: list[str] = []
        real_overlaps, real_match = ParamFamily.overlaps, ParamFamily.match

        def overlaps(self: Any, other: Any) -> bool:
            calls.append("overlaps")
            return real_overlaps(self, other)

        def match(self: Any, key: object) -> Any:
            calls.append("match")
            return real_match(self, key)

        with mock.patch.object(ParamFamily, "overlaps", overlaps), \
                mock.patch.object(ParamFamily, "match", match):
            params.register_families(families)
        self.assertLessEqual(len(calls), 4 * count, f"{len(calls)} comparaciones")
        self.assertEqual(len(params.FAMILIES), count)

    def test_c_the_problems_are_those_of_the_pairwise_check(self) -> None:
        """ADR-0027 (1, 2): con familias y claves al azar, ``register_families`` registra el lote
        o lanza el mismo ``ValueError`` (los mismos problemas, con el mismo texto y en el mismo
        orden: primero lo registrado y después lo del lote) que daba la comprobación de cada
        pareja y de cada clave con cada patrón; si falla, no registra nada del lote."""
        rng = random.Random(20261119)
        refused = 0
        for case in range(250):
            with self.subTest(case=case):
                params.unregister_families(MODULE)
                params.unregister_definitions(MODULE)
                keys = sorted({".".join((MODULE, *(rng.choice(("a", "b", "unit", "v"))
                                                   for _ in range(rng.randint(1, 4)))))
                               for _ in range(rng.randint(0, 5))})
                params.register_definitions(tuple(
                    ParamDef(key, "float", "-", 1.0, 0.0, 2.0, ("RNF-001-03",), "Prueba: clave")
                    for key in keys))
                registered: list[str] = []
                for _ in range(rng.randint(0, 8)):  # lo registrado antes, una a una
                    pattern = random_pattern(rng)
                    try:
                        params.register_families((make(pattern),))
                    except ValueError:
                        self.assertIsNotNone(
                            reference_message(registered, [pattern], keys), pattern)
                    else:
                        self.assertIsNone(reference_message(registered, [pattern], keys), pattern)
                        registered.append(pattern)
                self.assertEqual(list(params.FAMILIES), registered)
                batch = [random_pattern(rng) for _ in range(rng.randint(1, 7))]
                if registered and rng.random() < 0.3:
                    batch.insert(rng.randrange(len(batch) + 1), rng.choice(registered))
                expected = reference_message(registered, batch, keys)
                if expected is None:
                    params.register_families([make(pattern) for pattern in batch])
                    self.assertEqual(list(params.FAMILIES), [*registered, *batch])
                else:
                    refused += 1
                    with self.assertRaises(ValueError) as caught:
                        params.register_families([make(pattern) for pattern in batch])
                    self.assertEqual(str(caught.exception), expected)
                    self.assertEqual(list(params.FAMILIES), registered)  # nada del lote
        self.assertGreater(refused, 30, "el azar tiene que probar también los rechazos")

    def test_d_match_and_the_template_check_are_those_of_the_regular_expression(self) -> None:
        """ADR-0027 (1): ``ParamFamily.match`` da los segmentos variables que daba la expresión
        regular del patrón (también con claves que no son de ningún parámetro: mayúsculas, un
        segmento vacío o con punto), y la plantilla se admite en la construcción exactamente si
        su clave casa con el patrón; ``overlaps`` es el de antes."""
        rng = random.Random(7)
        words = ("a", "b", "unit", "capa_util", "Capa", "1x", "", "x-y", "v", "a.b")
        valid = ("a", "b", "unit", "capa_util", "v", "x1")
        for case in range(400):
            pattern = random_pattern(rng)
            family = make(pattern)
            expression = re.compile(r"\.".join(
                f"({SEGMENT})" if VARIABLE.fullmatch(part) else re.escape(part)
                for part in pattern.split(".")))
            key = ".".join((MODULE, *(rng.choice(words) for _ in range(rng.randint(1, 5)))))
            if rng.random() < 0.4:  # una clave que casa
                key = ".".join(rng.choice(("capa", "x1", "unit", "a_b", "Capa"))
                               if VARIABLE.fullmatch(part) else part
                               for part in pattern.split("."))
            found = expression.fullmatch(key)
            with self.subTest(case=case, pattern=pattern, key=key):
                self.assertEqual(family.match(key), None if found is None else found.groups())
                other = random_pattern(rng)
                self.assertEqual(family.overlaps(make(other)), reference_overlap(pattern, other))
            key = ".".join((MODULE, *(rng.choice(valid) for _ in range(rng.randint(1, 5)))))
            if rng.random() < 0.4:
                key = ".".join(rng.choice(valid) if VARIABLE.fullmatch(part) else part
                               for part in pattern.split("."))
            with self.subTest(case=case, pattern=pattern, template_key=key):
                if reference_match(pattern, key):
                    self.assertEqual(ParamFamily(pattern, template(key)).pattern, pattern)
                else:
                    with self.assertRaisesRegex(ValueError, "no casa"):
                        ParamFamily(pattern, template(key))
        for not_a_key in (None, 7, b"res.a.b", ("res", "a")):
            self.assertIsNone(make("res.a.{u}").match(not_a_key))


if __name__ == "__main__":
    unittest.main()
