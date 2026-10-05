# SPDX-License-Identifier: GPL-3.0-or-later
"""Reglas comprobables de los repositorios (plan 001 §5.4.1; plan 007 §5.4.2).

Cada módulo es una familia de reglas con ``check(root: Path) -> list[Finding]``: la
lista vacía significa que el árbol bajo ``root`` cumple. Solo biblioteca estándar.

- ``FAMILIES``, las del código (con las del manifiesto, MAN-01 y NOM-04), y
  ``run_all``, que las ejecuta todas: el verde de ``tools/check.py``. Los pasos de
  ``tools/check.py`` que no son reglas sobre ficheros (licencias, validación con
  Blender) tienen su propia orden.
- ``DOCS_FAMILIES``, las de la documentación (ADR-01, AGT-01 y AGT-02, NOM-03 y TXT-01
  a 03, sin ``.git/``, ``Documentacion/``, ``Promts/`` ni la carpeta del código), y
  ``run_docs``: las ejecuta ``tools/check_docs.py`` (spec 007, RF-007-11). ADR-01 y
  NOM-03 dejaron el verde del código en la tarea 007/T05: el repositorio de código no
  tiene ``docs/`` ni ``specs/``.

``layout`` llega con la spec 007: REP-02, la carpeta de la extensión con su nombre exacto
(T04). ``specs`` (NOM-03) sale de ``naming`` en la T05.

``suites`` llega con la convergencia de la spec 001: TST-01, carpetas de ``tests/`` sin
``__init__.py`` (T34); TST-02, ficheros de pruebas que su paso no carga (T43); TST-03,
métodos de un ``TestCase`` que citan un requisito y no empiezan por «test» (T44);
TST-04, omisiones incondicionales (T46, ampliada en T48); TST-05, pruebas repetidas
(T53); TST-06, pruebas ``async`` o con ``yield`` que no se ejecutan (T54); TST-07,
pruebas marcadas con ``expectedFailure`` (T59); y TST-08, pruebas fuera de un
``TestCase`` (T60); el catálogo del plan 001 (§5.4.1) debe recogerlas.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

from .. import manifest
from ..findings import Finding
from ..layout import DOCS_EXCLUDED
from . import adr, agents, headers, imports, layout, naming, platform, props, specs
from . import suites, text

Family = Callable[[Path], list[Finding]]

FAMILIES: Mapping[str, Family] = {
    "imports": imports.check,
    "props": props.check,
    "platform": platform.check,
    "naming": naming.check,
    "headers": headers.check,
    "text": text.check,
    "agents": agents.check,
    "manifest": manifest.check,
    "suites": suites.check,
    "layout": layout.check,
}

DOCS_FAMILIES: Mapping[str, Family] = {
    "adr": adr.check,
    "agents": partial(agents.check, excluded=DOCS_EXCLUDED),
    "specs": specs.check,
    "text": partial(text.check, excluded=DOCS_EXCLUDED),
}


def _run(families: Mapping[str, Family], root: Path) -> list[Finding]:
    findings: set[Finding] = set()
    for check in families.values():
        findings.update(check(root))
    return sorted(findings)


def run_all(root: Path) -> list[Finding]:
    """Todos los incumplimientos de todas las familias del código, sin repetir y
    ordenados."""
    return _run(FAMILIES, root)


def run_docs(root: Path) -> list[Finding]:
    """Todos los incumplimientos de las familias de la documentación en ``root``, sin
    repetir y ordenados."""
    return _run(DOCS_FAMILIES, root)
