# SPDX-License-Identifier: GPL-3.0-or-later
"""La regla «cada magnitud se escribe siempre igual» (spec 019, T25; RF-019-17; UI-07; plan 019 A6, P-3).

Python puro. Dos piezas:

- :func:`violations`: de un texto que se vería en pantalla, las reglas de formato que incumple: la marca decimal del
  idioma (coma en español, punto en inglés), la unidad separada del número por un espacio y los decimales fijos de
  la magnitud (``core.magnitudes``) cuando el número lleva unidad.
- :func:`source_findings`: de un fichero de la capa de presentación, los números que se formatean a mano
  (``{x:.2f}``, ``{x:,.2f}``) en vez de pasar por ``core.i18n.format_number`` o ``core.magnitudes.format``.

La lista base (``tests/data/ui_baseline.toml``, sección ``[formats]``) es la de lo existente que no cumple: solo baja.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from tests.support.package import import_geoblender
from tests.support.repo import EXT, ROOT

magnitudes = import_geoblender("core.magnitudes")

UNITS = sorted({m.unit for m in magnitudes.MAGNITUDES.values() if m.unit}, key=len, reverse=True)
UNIT = "|".join(re.escape(unit) for unit in UNITS)
DECIMALS = {m.unit: m.decimals for m in magnitudes.MAGNITUDES.values() if m.unit}

_ES_POINT = re.compile(r"(?<![\w.\-])(?<!Python )\d+\.\d+(?![\w.])")
_EN_COMMA = re.compile(r"(?<![\w,])\d{1,3}(?:,\d{3})*,\d{1,2}(?![\w,])")
_GLUED = re.compile(rf"\d(?:{UNIT})(?!\w)")
_WITH_UNIT = {"es": re.compile(rf"(?<![\w.,])\d+,(\d+) ({UNIT})(?!\w)"),
              "en": re.compile(rf"(?<![\w.,])\d+\.(\d+) ({UNIT})(?!\w)")}
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
# Textos que citan a propósito cómo se puede teclear un número (Postel, ``core.magnitudes.parse``): no son un valor.
EXEMPT_PREFIXES = ("it is not a number (for example", "no es un número (por ejemplo")
_BLANK = " "  # el espacio fino de los miles (core.i18n.THIN_SPACE)


def violations(text: str, language: str = "es") -> list[str]:
    """Los nombres de las reglas de formato que incumple ``text`` (vacío: cumple)."""
    if text.startswith(EXEMPT_PREFIXES):
        return []
    text = _PLACEHOLDER.sub("", text).replace(_BLANK, "")
    found: list[str] = []
    if (language == "es" and _ES_POINT.search(text)) or (language == "en" and _EN_COMMA.search(text)):
        found.append("decimal-mark")
    if _GLUED.search(text):
        found.append("unit-glued")
    for match in _WITH_UNIT[language].finditer(text):
        if len(match.group(1)) != DECIMALS[match.group(2)]:
            found.append("fixed-decimals")
            break
    return found


def findings(texts: Iterable[str], language: str = "es") -> list[tuple[str, str]]:
    """(texto, regla) de cada incumplimiento de ``texts``."""
    return [(text, rule) for text in texts for rule in violations(text, language)]


_SPEC = re.compile(r"\.\d+[fFeEgG]|,")
_FORMAT_CALL = re.compile(r"\{[^{}]*:[^{}]*\.\d+[fFeEgG]\}")


def source_findings(source: str, name: str) -> list[str]:
    """Las entradas ``fichero: expresión`` de los números formateados a mano en ``source`` (un f-string con
    ``:.Nf`` o con separador de miles, o un ``"{:.Nf}".format``)."""
    found: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            spec = "".join(part.value for part in node.format_spec.values if isinstance(part, ast.Constant))
            if _SPEC.search(spec):
                found.add(f"{name}: {ast.get_source_segment(source, node)}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _FORMAT_CALL.search(node.value):
            found.add(f"{name}: {node.value[:60]}")
    return sorted(found)


def presentation_findings(root: Path = ROOT / EXT / "bl") -> list[str]:
    """Las de todos los ficheros de la capa de presentación (``bl/``), con la ruta desde ``geoblender/``."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root.parent).as_posix()
        found += source_findings(path.read_text(encoding="utf-8"), name)
    return found
