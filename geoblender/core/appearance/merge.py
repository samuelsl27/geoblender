# SPDX-License-Identifier: GPL-3.0-or-later
"""El aspecto de varios elementos a la vez y la regla de la leyenda por campo (spec 019, T04; RF-019-10 y
RF-019-13; plan 019 §5.7 P-10; D-8).

- :func:`common`: con varios elementos del **mismo tipo**, cada propiedad toma el valor común o queda como
  «varios valores» (``None`` en :class:`Mixed`); con **tipos distintos** (P-10) solo se muestran las propiedades
  de visibilidad y transparencia que tienen todos. Si todos son iguales devuelve el
  :class:`~.model.Appearance` común.
- :func:`color_rule`: mientras un elemento esté coloreado por una leyenda por campo, **manda la leyenda**: el
  color del panel no se edita y el panel dice su nombre; al quitarla, vuelve el color guardado
  (:func:`effective_color`).

Dominio puro: ni ``bpy`` ni ``bl``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..errors import GeoblenderError
from ..i18n import tr
from .catalog import PROPERTIES
from .model import Appearance

__all__ = ["ColorRule", "MULTI_KIND_PROPS", "Mixed", "color_rule", "common", "effective_color"]

MULTI_KIND_PROPS: tuple[str, ...] = ("transparency", "visible")
"""Con tipos distintos (P-10) solo se muestran, de entre las comunes, la transparencia y la visibilidad."""


@dataclass(frozen=True)
class Mixed:
    """El aspecto común de una selección que no es toda igual: ``values`` son pares ``(propiedad, valor)`` y el
    valor es ``None`` donde los elementos difieren («varios valores»)."""

    kinds: tuple[str, ...]
    count: int
    values: tuple[tuple[str, str | None], ...]

    @property
    def props(self) -> tuple[str, ...]:
        """Las propiedades comunes a todos los elementos, en el orden del catálogo."""
        return tuple(prop for prop, _value in self.values)

    def get(self, prop: str) -> str | None:
        """El valor común de ``prop``, o ``None`` si difiere. ``KeyError`` si no es una propiedad común."""
        for key, value in self.values:
            if key == prop:
                return value
        raise KeyError(prop)

    def is_various(self, prop: str) -> bool:
        """Si los elementos difieren en ``prop`` (el panel muestra «varios valores»)."""
        return self.get(prop) is None


def common(items: Sequence[Appearance]) -> Appearance | Mixed:
    """El aspecto común de ``items``: un :class:`Appearance` si todos son del mismo tipo y de los mismos
    valores; si no, un :class:`Mixed`. Con tipos distintos, solo las propiedades que tienen todos."""
    if not items:
        raise GeoblenderError("core.appearance_empty_selection", tr("there is no element selected"),
                              obj=tr("Selection"), field=tr("Elements"), value="0")
    first = items[0]
    kinds = tuple(dict.fromkeys(item.kind for item in items))
    if len(items) == 1 or (len(kinds) == 1 and all(item == first for item in items)):
        return first
    candidates = PROPERTIES if len(kinds) == 1 else MULTI_KIND_PROPS
    shared = [prop for prop in candidates if all(prop in item.props for item in items)]
    values = []
    for prop in shared:
        found = {item.get(prop) for item in items}
        values.append((prop, found.pop() if len(found) == 1 else None))
    return Mixed(kinds, len(items), tuple(values))


@dataclass(frozen=True)
class ColorRule:
    """Quién manda en el color: ``editable`` si ninguna leyenda lo pinta; si no, ``legend`` con su nombre
    (varios, ordenados y separados por coma)."""

    editable: bool
    legend: str | None

    @property
    def text(self) -> str:
        """«Coloreado por <leyenda>» en el idioma activo; vacío si el color es editable."""
        return "" if self.legend is None else tr("Colored by {legend}", legend=self.legend)


def color_rule(legends: Sequence[str | None]) -> ColorRule:
    """La regla del color de una selección: ``legends`` es la leyenda por campo activa de cada elemento
    (``None`` si no tiene). Con alguna activa, manda ella (D-8)."""
    names = sorted({name for name in legends if name})
    if not names:
        return ColorRule(True, None)
    return ColorRule(False, ", ".join(names))


def effective_color(stored: Appearance, legend: str | None) -> str | None:
    """El color que manda: ``None`` mientras la leyenda ``legend`` esté activa (el color guardado no se pierde
    y **vuelve al quitarla**); si no, el del aspecto guardado."""
    if legend:
        return None
    return stored.get("color", None)
