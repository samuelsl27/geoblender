# SPDX-License-Identifier: GPL-3.0-or-later
"""Patrones de exclusión: subconjunto de la sintaxis de gitignore (plan 001 §5.4.4).

Es el mismo para ``.gitignore`` y para ``[build] paths_exclude_pattern`` del manifiesto:

- las líneas vacías y las que empiezan por ``#`` se ignoran;
- un ``/`` inicial o intermedio ancla el patrón a la raíz (como en git);
- un ``/`` final hace que solo case con carpetas;
- sin ``/`` (salvo el final), el patrón casa con el nombre en cualquier nivel;
- comodines ``*`` y ``?`` (nunca atraviesan «/»), ``[…]`` y ``**`` (``**/x``,
  ``a/**/b``, ``a/**``); ``\\`` hace literal el carácter siguiente.

La negación ``!`` no se admite: mejor un error claro que una exclusión distinta de la
de git o de la de Blender. Las rutas se comparan tal cual, distinguiendo mayúsculas.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


class UnsupportedPattern(ValueError):
    """Patrón que este subconjunto de gitignore no admite (p. ej. la negación «!»)."""


@dataclass(frozen=True)
class _Pattern:
    source: str
    regex: re.Pattern[str]
    dir_only: bool
    anchored: bool


def _translate(pattern: str) -> str:
    """Traduce un patrón (sin «/» inicial ni final) a una expresión regular."""
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            if j - i == 2:
                after_slash = i == 0 or pattern[i - 1] == "/"
                if after_slash and j < n and pattern[j] == "/":
                    out.append("(?:.*/)?")  # cero o más carpetas
                    i = j + 1
                    continue
                if after_slash and j == n:
                    out.append(".*")  # todo lo que hay dentro
                    i = j
                    continue
            out.append("[^/]*")
            i = j
        elif char == "?":
            out.append("[^/]")
            i += 1
        elif char == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(char))
                i += 1
                continue
            body = pattern[i + 1 : j]
            negated = body[:1] in ("!", "^")
            if negated:
                body = body[1:]
            body = body.replace("\\", "\\\\").replace("[", "\\[")
            out.append(f"[^{body}/]" if negated else f"[{body}]")
            i = j + 1
        elif char == "\\" and i + 1 < n:
            out.append(re.escape(pattern[i + 1]))
            i += 2
        else:
            out.append(re.escape(char))
            i += 1
    return "".join(out)


def _compile(line: str) -> _Pattern | None:
    text = line.rstrip("\r\n").rstrip(" ")
    if not text or text.startswith("#"):
        return None
    if text.startswith("!"):
        raise UnsupportedPattern(
            f"Patrón de exclusión no admitido «{text}»: la negación «!» no está "
            "soportada; reescriba las exclusiones sin «!» (plan 001 §5.4.4)"
        )
    dir_only = text.endswith("/")
    body = text.rstrip("/")
    anchored = "/" in body
    body = body.lstrip("/")
    if not body:
        raise UnsupportedPattern(f"Patrón de exclusión vacío «{text}»")
    regex = re.compile(_translate(body), re.DOTALL)
    return _Pattern(source=text, regex=regex, dir_only=dir_only, anchored=anchored)


class IgnoreSpec:
    """Conjunto de patrones de exclusión."""

    def __init__(self, patterns: Sequence[_Pattern] = ()) -> None:
        self._patterns: tuple[_Pattern, ...] = tuple(patterns)

    @classmethod
    def from_lines(cls, lines: Iterable[str]) -> IgnoreSpec:
        """Compila las líneas de un ``.gitignore`` o de ``paths_exclude_pattern``.

        Lanza :class:`UnsupportedPattern` si alguna usa la negación «!».
        """
        compiled = (_compile(line) for line in lines)
        return cls([pattern for pattern in compiled if pattern is not None])

    @property
    def sources(self) -> tuple[str, ...]:
        """Los patrones tal como se escribieron (sin comentarios ni líneas vacías)."""
        return tuple(pattern.source for pattern in self._patterns)

    def matches_entry(self, relpath: str, is_dir: bool) -> bool:
        """Verdadero si algún patrón casa con la ruta, sin mirar sus carpetas."""
        relpath = relpath.strip("/")
        name = relpath.rsplit("/", 1)[-1]
        for pattern in self._patterns:
            if pattern.dir_only and not is_dir:
                continue
            if pattern.regex.fullmatch(relpath if pattern.anchored else name):
                return True
        return False

    def matches(self, relpath: str, is_dir: bool) -> bool:
        """Verdadero si ``relpath`` (relativa, con «/») o una carpeta suya se excluye."""
        parts = relpath.strip("/").split("/")
        for depth in range(1, len(parts)):
            if self.matches_entry("/".join(parts[:depth]), True):
                return True
        return self.matches_entry("/".join(parts), is_dir)
