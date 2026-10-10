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
orden de ``unittest``. Y es por tiempo (spec 004, T39; :func:`assign`): de más a menos,
cada módulo va a la parte que lleva menos; lo que no tiene pruebas (el ``__init__`` de un
paquete), a la 1. El tiempo de un módulo es su duración medida en una comprobación
anterior (:func:`weights`), y el de uno sin medida (nuevo), sus pruebas por la media por
prueba de los medidos; sin ninguna medida, el reparto es por número de pruebas, el de la
spec 003 (T40). Como todas las partes descubren lo mismo, leen el mismo fichero de
tiempos y el reparto solo depende de eso, cada prueba está en una sola parte.

Unas suites que se ejecutan a la vez (las carpetas de dominio del paso «motor»; spec 006,
T47) se reparten también sus partes por tiempo (:func:`share`): cada parte más va a la
que más tarda (:func:`span`, su parte más cargada con el reparto de :func:`assign`).

Antes de ejecutar, cada parte escribe ``PARTE i de n: r de T pruebas`` (:func:`line`).
``tools/check.py`` comprueba con :func:`consistency` que las partes son 1…n, que todas
dicen el mismo total y que sus pruebas suman ese total: si no, el reparto perdió o
repitió pruebas, y el paso falla.

Los tiempos (spec 004, T39; RNF-001-01, RNF-007-01): ``tools/check.py`` guarda la
duración de cada módulo de cada suite con partes en un almacén fuera del repositorio
(:func:`read_store`, :func:`write_store`; lo sitúa ``check.default_times_store``, en la
carpeta temporal del sistema). Antes de un paso, copia en su carpeta temporal los tiempos
de cada suite y se los da a todas sus partes (``--tiempos``, :func:`read_times`); cada
parte mide sus módulos, con sus preparaciones y cierres de módulo y de clase
(:func:`measured`), y al terminar los escribe en su fichero (``--medidas``,
:func:`read_measures`). Tras los pasos, las medidas sustituyen a las guardadas
(:func:`merge`). Un fichero que falta o no se puede leer no tiene medidas: el reparto de
siempre.

Solo biblioteca estándar (HER-01): lo importan ``tools/check.py``,
``tools/unittest_part.py`` y, dentro de Blender, ``tools/run_blender_tests.py``.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import unittest
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

OPTION = "--parte"  # «--parte i/n», en tools/unittest_part.py y en el lanzador
TIMES_OPTION = "--tiempos"  # fichero con la duración de cada módulo (para repartir; T39)
MEASURES_OPTION = "--medidas"  # fichero donde la parte escribe la de los suyos (T39)
LINE_PREFIX = "PARTE"
FORMAT = "i/n (la parte i de n, con 1 ≤ i ≤ n)"
TIMES_SCHEMA = "geoblender.test-times/1"  # un fichero de tiempos o de medidas (T39)
STORE_SCHEMA = "geoblender.test-times-store/1"  # el almacén de check.py (T39)
MIN_SECONDS = 0.001  # el peso mínimo de un módulo: así ninguna parte queda vacía
# Los módulos de pruebas con el mismo valor en esta constante van a la misma parte (spec
# 006, T47; affinity_of).
AFFINITY_ATTRIBUTE = "PART_AFFINITY"
DECIMALS = 3  # los segundos se guardan en milésimas

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


def assign(
    sizes: Sequence[int],
    parts: int,
    weights: Sequence[float] | None = None,
    affinities: Sequence[str | None] | None = None,
) -> list[int]:
    """La parte (1…``parts``) de cada grupo de pruebas, en el orden de ``unittest``,
    con ``sizes`` pruebas cada uno y, si se dan, ``weights`` segundos (:func:`weights`;
    sin ellos, el peso de cada grupo es su número de pruebas). Los que tienen pruebas,
    de más a menos peso (a igualdad, en su orden), van cada uno a la parte que lleva
    menos (a igualdad, la de número menor); los que no tienen, a la 1. Con
    ``affinities`` (spec 006, T47; :func:`affinity_of`), los que tienen la misma van
    juntos, como uno solo con sus pesos sumados (en el lugar del primero). Depende solo
    de lo que recibe: todas las partes calculan lo mismo. Con al menos ``parts`` grupos
    (o afinidades) con pruebas y pesos positivos, ninguna parte queda vacía (los
    ``parts`` mayores van uno a cada parte)."""
    load_of: Sequence[float] = sizes if weights is None else weights
    owners = [1] * len(sizes)
    loads = [0.0] * parts
    units: dict[tuple[int, object], list[int]] = {}
    for index, size in enumerate(sizes):
        if size > 0:
            shared = affinities[index] if affinities is not None else None
            units.setdefault((0, index) if shared is None else (1, shared), []).append(index)
    order = sorted(
        units.values(),
        key=lambda members: (-sum(load_of[index] for index in members), members[0]),
    )
    for members in order:
        lightest = min(range(parts), key=lambda part: (loads[part], part))
        for index in members:
            owners[index] = lightest + 1
        loads[lightest] += sum(load_of[index] for index in members)
    return owners


def affinity_of(name: str | None) -> str | None:
    """La afinidad del módulo de pruebas ``name`` (spec 006, T47): su ``AFFINITY_ATTRIBUTE``
    si ya está importado (``discover`` los importa) y es un texto no vacío; si no,
    ``None``. Los módulos con la misma van a la misma parte: así comparten lo que su
    proceso guarda (los árboles del repositorio que analizan las reglas)."""
    module = sys.modules.get(name) if name is not None else None
    value = getattr(module, AFFINITY_ATTRIBUTE, None)
    return value if isinstance(value, str) and value else None


def span(seconds: Sequence[float], parts: int) -> float:
    """Lo que tarda la parte más cargada si unos módulos que tardan ``seconds`` se
    reparten en ``parts`` partes por tiempo (:func:`assign`); 0 sin módulos."""
    loads = [0.0] * parts
    for owner, value in zip(assign([1] * len(seconds), parts, seconds), seconds):
        loads[owner - 1] += value
    return max(loads)


def share(
    seconds: Mapping[str, Sequence[float]],
    limits: Mapping[str, int],
    budget: int,
    minimum: int = 2,
) -> dict[str, int]:
    """Cuántas partes tiene cada una de unas suites que se ejecutan a la vez (las
    carpetas de dominio del paso «motor»; spec 006, T47): ``seconds`` da la duración de
    cada módulo de cada suite, ``limits`` cuántas partes admite cada una y ``budget``
    cuántas hay entre todas. Cada suite empieza con ``minimum`` partes (o las que admita)
    y, mientras queden, van a la suite que más tarda con las que tiene (:func:`span`; a
    igualdad, la primera), las que le hagan falta para tardar menos (a veces, más de una).
    Si la que más tarda no puede tardar menos con las que quedan, no se dan más: el paso
    no acabaría antes y más procesos a la vez solo cargan el equipo. No pasa del límite
    de ninguna ni de ``budget``, salvo con las partes del principio."""
    counts = {name: max(1, min(minimum, limits[name])) for name in seconds}
    while (left := budget - sum(counts.values())) > 0:
        slowest = max(counts, key=lambda name: span(seconds[name], counts[name]))
        now = span(seconds[slowest], counts[slowest])
        top = min(limits[slowest], counts[slowest] + left)
        better = next(
            (n for n in range(counts[slowest] + 1, top + 1) if span(seconds[slowest], n) < now),
            None,
        )
        if better is None:
            break
        counts[slowest] = better
    return counts


def weights(
    sizes: Sequence[int], names: Sequence[str | None], times: Mapping[str, float]
) -> list[float] | None:
    """El peso, en segundos, de cada grupo de pruebas (``sizes`` pruebas y el módulo
    ``names``) según ``times`` (la duración medida de cada módulo): la suya (al menos
    ``MIN_SECONDS``) o, sin medida, sus pruebas por la media por prueba de los medidos (al
    menos ``MIN_SECONDS``); 0 los que no tienen pruebas. ``None`` si no hay medida de
    ningún grupo con pruebas: entonces se reparte por número de pruebas (spec 004,
    T39)."""
    measured = [
        (size, times[name])
        for size, name in zip(sizes, names)
        if size > 0 and name is not None and name in times
    ]
    if not measured:
        return None
    per_test = sum(seconds for _size, seconds in measured) / sum(
        size for size, _seconds in measured
    )
    found: list[float] = []
    for size, name in zip(sizes, names):
        if size <= 0:
            found.append(0.0)
        elif name is not None and name in times:
            found.append(max(times[name], MIN_SECONDS))
        else:
            found.append(max(size * per_test, MIN_SECONDS))
    return found


def module_of(group: unittest.TestSuite | unittest.TestCase) -> str | None:
    """El módulo de las pruebas de un grupo de ``unittest discover`` (el de su primera
    prueba), o ``None`` si no tiene pruebas."""
    if isinstance(group, unittest.TestSuite):
        for item in group:
            found = module_of(item)
            if found is not None:
                return found
        return None
    return type(group).__module__


def select(
    suite: unittest.TestSuite,
    part: int,
    parts: int,
    times: Mapping[str, float] | None = None,
) -> tuple[unittest.TestSuite, int]:
    """Las pruebas de la parte ``part`` de ``parts`` de ``suite`` (la que devuelve
    ``unittest discover``: un hijo por módulo, o por ``__init__`` de un paquete) y el
    total de pruebas de la suite entera, repartidas por tiempo con ``times`` (la duración
    de cada módulo, :func:`read_times`) o, sin medidas, por número de pruebas. No cambia
    ``suite``."""
    groups = list(suite)
    sizes = [group.countTestCases() for group in groups]
    names = [module_of(group) for group in groups]
    found = weights(sizes, names, times) if times else None
    owners = assign(sizes, parts, found, [affinity_of(name) for name in names])
    chosen = [group for group, owner in zip(groups, owners) if owner == part]
    return unittest.TestSuite(chosen), suite.countTestCases()


@dataclass(frozen=True)
class Measures:
    """Lo que midió una parte (``--medidas``): cuál de cuántas y la duración de cada uno
    de sus módulos, en segundos (spec 004, T39)."""

    part: int
    parts: int
    modules: dict[str, float]


def _seconds_of(value: object) -> float | None:
    """Unos segundos válidos (un número finito y no negativo, no un booleano), o
    ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _modules_of(value: object) -> dict[str, float]:
    """``{módulo: segundos}`` válidos de un objeto JSON (los demás, fuera)."""
    if not isinstance(value, dict):
        return {}
    found: dict[str, float] = {}
    for name, raw in value.items():
        seconds = _seconds_of(raw)
        if isinstance(name, str) and name and seconds is not None:
            found[name] = seconds
    return found


def _read_json(path: Path, schema: str) -> dict[str, object] | None:
    """El objeto JSON de ``path`` con ``schema``, o ``None`` si falta, no se puede leer o
    es de otro esquema."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != schema:
        return None
    return data


def _write_json(path: Path, data: Mapping[str, object]) -> None:
    """Escribe ``data`` en ``path`` (crea su carpeta), entero o nada: se escribe al lado
    y se renombra."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.{os.getpid()}.partial")
    try:
        partial.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1)
                           + "\n", encoding="utf-8")
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


def _rounded(modules: Mapping[str, float]) -> dict[str, float]:
    return {name: round(seconds, DECIMALS) for name, seconds in sorted(modules.items())}


def read_times(path: Path) -> dict[str, float]:
    """La duración de cada módulo de un fichero de tiempos (o de medidas); ``{}`` si falta,
    no se puede leer o es de otro esquema: sin medidas."""
    data = _read_json(path, TIMES_SCHEMA)
    return {} if data is None else _modules_of(data.get("modules"))


def read_measures(path: Path) -> Measures | None:
    """Las medidas que escribió una parte, o ``None`` si falta el fichero, no se puede
    leer o no dice qué parte es."""
    data = _read_json(path, TIMES_SCHEMA)
    if data is None:
        return None
    part, count = data.get("part"), data.get("parts")
    if isinstance(part, bool) or isinstance(count, bool):
        return None
    if not (isinstance(part, int) and isinstance(count, int) and 1 <= part <= count):
        return None
    return Measures(part, count, _modules_of(data.get("modules")))


def write_times(
    path: Path,
    modules: Mapping[str, float],
    *,
    part: int | None = None,
    parts: int | None = None,
) -> None:
    """Escribe un fichero de tiempos con la duración de cada módulo (en milésimas) y, en
    el de las medidas de una parte, cuál de cuántas es."""
    data: dict[str, object] = {"schema": TIMES_SCHEMA, "modules": _rounded(modules)}
    if part is not None and parts is not None:
        data.update(part=part, parts=parts)
    _write_json(path, data)


def merge(stored: Mapping[str, float], measures: Sequence[Measures]) -> dict[str, float]:
    """Los tiempos de una suite tras una comprobación: si llegaron las medidas de todas
    sus partes (1…n), solo ellas (un módulo que ya no está, desaparece); si falta alguna,
    los guardados con las medidas que llegaron encima."""
    numbers = {(m.part, m.parts) for m in measures}
    counts = {m.parts for m in measures}
    complete = len(counts) == 1 and {n for n, _c in numbers} == set(range(1, max(counts) + 1))
    found: dict[str, float] = {} if complete else dict(stored)
    for measure in measures:
        found.update(measure.modules)
    return found


def read_store(path: Path) -> dict[str, dict[str, float]]:
    """``{suite: {módulo: segundos}}`` del almacén de ``tools/check.py``; ``{}`` si falta,
    no se puede leer o es de otro esquema."""
    data = _read_json(path, STORE_SCHEMA)
    suites = data.get("suites") if data is not None else None
    if not isinstance(suites, dict):
        return {}
    found: dict[str, dict[str, float]] = {}
    for key, modules in suites.items():
        valid = _modules_of(modules)
        if isinstance(key, str) and valid:
            found[key] = valid
    return found


def write_store(path: Path, suites: Mapping[str, Mapping[str, float]]) -> None:
    """Escribe el almacén de ``tools/check.py`` con los tiempos de cada suite."""
    data = {
        "schema": STORE_SCHEMA,
        "suites": {key: _rounded(modules) for key, modules in sorted(suites.items())},
    }
    _write_json(path, data)


class _TimedGroup(unittest.TestSuite):
    """Un grupo de ``discover`` (un módulo) que, al ejecutarse, suma su duración a
    ``record[name]``, con las preparaciones de su módulo y de sus clases y también sus
    cierres: al terminar, cierra su última clase y su módulo como haría ``unittest`` al
    empezar el siguiente (los mismos pasos, en el mismo orden), para que no cuenten en
    el siguiente. Usa ``_tearDownPreviousClass`` y ``_handleModuleTearDown`` de
    ``unittest.TestSuite`` (Python 3.13; lo vigila ``tests/unit/tools/test_parts.py``)."""

    def __init__(
        self,
        group: unittest.TestSuite,
        name: str,
        record: dict[str, float],
        clock: Callable[[], float],
    ) -> None:
        super().__init__([group])
        self._name = name
        self._record = record
        self._clock = clock

    def run(self, result: unittest.TestResult, debug: bool = False) -> unittest.TestResult:
        start = self._clock()
        super().run(result, debug)
        if getattr(result, "_testRunEntered", False):
            self._tearDownPreviousClass(None, result)  # type: ignore[attr-defined]
            self._handleModuleTearDown(result)  # type: ignore[attr-defined]
            result._previousTestClass = None  # type: ignore[attr-defined]
        seconds = self._clock() - start
        self._record[self._name] = self._record.get(self._name, 0.0) + seconds
        return result


class _MeasuredSuite(unittest.TestSuite):
    """La suite de una parte que, al terminar de ejecutarse, escribe sus medidas."""

    def __init__(self, groups: Sequence[unittest.TestSuite], write: Callable[[], None]) -> None:
        super().__init__(groups)
        self._write = write

    def run(self, result: unittest.TestResult, debug: bool = False) -> unittest.TestResult:
        super().run(result, debug)
        self._write()
        return result


def measured(
    suite: unittest.TestSuite,
    part: int,
    parts: int,
    path: Path,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> unittest.TestSuite:
    """La suite de la parte ``part`` de ``parts`` (la de :func:`select`) que, al
    ejecutarse entera, escribe en ``path`` la duración de cada uno de sus módulos
    (:class:`Measures`, con :func:`write_times`). Ejecuta lo mismo y en el mismo orden;
    si no puede escribir, lo dice en la salida de errores y las pruebas no cambian."""
    record: dict[str, float] = {}
    groups: list[unittest.TestSuite] = []
    for group in suite:
        name = module_of(group)
        if name is None or not isinstance(group, unittest.TestSuite):
            groups.append(group)  # type: ignore[arg-type]
        else:
            groups.append(_TimedGroup(group, name, record, clock))

    def write() -> None:
        try:
            write_times(path, record, part=part, parts=parts)
        except OSError as exc:
            print(f"AVISO: no se pudieron escribir las medidas de la parte en «{path}»: "
                  f"{exc}", file=sys.stderr, flush=True)

    return _MeasuredSuite(groups, write)


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
