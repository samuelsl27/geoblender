# SPDX-License-Identifier: GPL-3.0-or-later
"""Reparto de unas pruebas en partes que se ejecutan a la vez (spec 003, T40;
RNF-007-01).

``tools/check.py`` ejecuta las pruebas unitarias en varios procesos de Python
(``tools/unittest_part.py``) y las de Blender en varios Blender
(``tools/run_blender_tests.py --parte``), para terminar en ≤ 40 s sin quitar ni acortar
ninguna prueba. Los pasos siguen ejecutándose uno tras otro y en su orden (RF-001-06):
solo van a la vez las partes de un mismo paso.

Cada parte descubre todas las pruebas, como ``unittest discover``, y ejecuta solo las
suyas (:func:`select`). El reparto es por módulo de pruebas: un fichero entero, con sus
clases y sus preparaciones, va siempre a la misma parte, y cada parte los ejecuta en el
orden de ``unittest``. Y es por número de pruebas (:func:`assign`): de más a menos, cada
módulo va a la parte que lleva menos; lo que no tiene pruebas (el ``__init__`` de un
paquete), a la 1. Como todas las partes descubren lo mismo y el reparto solo depende de
eso, cada prueba está en una sola parte, y siempre en la misma.

Antes de ejecutar, cada parte escribe ``PARTE i de n: r de T pruebas`` (:func:`line`).
``tools/check.py`` comprueba con :func:`consistency` que las partes son 1…n, que todas
dicen el mismo total y que sus pruebas suman ese total: si no, el reparto perdió o
repitió pruebas, y el paso falla.

Solo biblioteca estándar (HER-01): lo importan ``tools/check.py``,
``tools/unittest_part.py`` y, dentro de Blender, ``tools/run_blender_tests.py``.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Sequence

OPTION = "--parte"  # «--parte i/n», en tools/unittest_part.py y en el lanzador
LINE_PREFIX = "PARTE"
FORMAT = "i/n (la parte i de n, con 1 ≤ i ≤ n)"

_VALUE = re.compile(r"([0-9]+)/([0-9]+)")
_LINE = re.compile(
    rf"^{LINE_PREFIX} ([0-9]+) de ([0-9]+): ([0-9]+) de ([0-9]+) pruebas?\s*$", re.MULTILINE
)

PartLine = tuple[int, int, int, int]  # (parte, partes, pruebas de la parte, total)


def parse(value: str) -> tuple[int, int]:
    """«i/n» → ``(i, n)``; lanza ``ValueError`` con el formato y el valor si no es
    ``i/n`` con 1 ≤ i ≤ n."""
    match = _VALUE.fullmatch(value)
    if match is not None:
        part, parts = int(match.group(1)), int(match.group(2))
        if 1 <= part <= parts:
            return part, parts
    raise ValueError(f"{OPTION} debe ser {FORMAT}, no «{value}»")


def label(part: int, parts: int) -> str:
    """``(2, 4)`` → «2/4», el valor de ``--parte``."""
    return f"{part}/{parts}"


def assign(sizes: Sequence[int], parts: int) -> list[int]:
    """La parte (1…``parts``) de cada grupo de pruebas, en el orden de ``unittest``,
    con ``sizes`` pruebas cada uno. Los que tienen pruebas, de más a menos (a igualdad,
    en su orden), van cada uno a la parte que lleva menos pruebas (a igualdad, la de
    número menor); los que no tienen, a la 1. Depende solo de ``sizes``: todas las
    partes calculan lo mismo. Con al menos ``parts`` grupos con pruebas, ninguna parte
    queda vacía (los ``parts`` mayores van uno a cada parte)."""
    owners = [1] * len(sizes)
    loads = [0] * parts
    order = sorted(
        (index for index, size in enumerate(sizes) if size > 0),
        key=lambda index: (-sizes[index], index),
    )
    for index in order:
        lightest = min(range(parts), key=lambda part: (loads[part], part))
        owners[index] = lightest + 1
        loads[lightest] += sizes[index]
    return owners


def select(suite: unittest.TestSuite, part: int, parts: int) -> tuple[unittest.TestSuite, int]:
    """Las pruebas de la parte ``part`` de ``parts`` de ``suite`` (la que devuelve
    ``unittest discover``: un hijo por módulo, o por ``__init__`` de un paquete) y el
    total de pruebas de la suite entera. No cambia ``suite``."""
    groups = list(suite)
    owners = assign([group.countTestCases() for group in groups], parts)
    chosen = [group for group, owner in zip(groups, owners) if owner == part]
    return unittest.TestSuite(chosen), suite.countTestCases()


def line(part: int, parts: int, selected: int, total: int) -> str:
    """«PARTE 2 de 4: 241 de 966 pruebas»: lo que escribe cada parte antes de
    ejecutar."""
    noun = "prueba" if total == 1 else "pruebas"
    return f"{LINE_PREFIX} {part} de {parts}: {selected} de {total} {noun}"


def last_line(text: str) -> PartLine | None:
    """La última línea de :func:`line` de una salida (al principio de una línea), o
    ``None`` si no hay ninguna."""
    found = _LINE.findall(text)
    if not found:
        return None
    part, parts, selected, total = (int(value) for value in found[-1])
    return part, parts, selected, total


def consistency(found: Sequence[PartLine | None], parts: int) -> str | None:
    """Qué no cuadra entre las líneas de las partes de un paso (``found[k]``, la de la
    parte k + 1, o ``None`` si no la dijo), o ``None`` si cuadran: las partes son
    1…``parts``, todas dicen el mismo total y suman ese total."""
    if len(found) != parts:
        return f"llegaron {len(found)} de {parts} partes"
    for number, info in enumerate(found, start=1):
        if info is None:
            return (
                f"la parte {number} de {parts} no dice cuántas pruebas tiene (falta su "
                f"línea «{LINE_PREFIX} {number} de {parts}: …»)"
            )
        if (info[0], info[1]) != (number, parts):
            return f"la parte {number} de {parts} dice «{line(*info)}»"
    lines = [info for info in found if info is not None]
    totals = sorted({info[3] for info in lines})
    if len(totals) > 1:
        listed = ", ".join(str(total) for total in totals)
        return f"las partes no dicen el mismo total de pruebas ({listed})"
    total = totals[0]
    added = sum(info[2] for info in lines)
    if added != total:
        what = "perdió" if added < total else "repitió"
        return f"las partes suman {added} de {total} pruebas: el reparto {what} pruebas"
    return None
