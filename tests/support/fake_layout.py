# SPDX-License-Identifier: GPL-3.0-or-later
"""Un ``UILayout`` simulado para dibujar menús y paneles sin interfaz (spec 002, T26 y
T28; plan 003 §5.1, «layout simulado»).

En ``blender -b`` no hay regiones que dibujar: las pruebas llaman al ``draw`` de un menú o
de un panel con un objeto que tiene ``layout`` (y lo que use el ``draw``) y leen lo que se
pidió dibujar. :class:`FakeLayout` anota cada elemento en una lista común a todo el árbol
(columnas, filas y cajas incluidas) y admite los atributos que se ponen a un *layout*
(``enabled``, ``alert``…). Python puro: no importa ``bpy``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from types import MethodType, SimpleNamespace
from typing import Any


@dataclass
class Item:
    """Un elemento dibujado: su tipo (``label``, ``operator``, ``prop``, ``menu``,
    ``separator``), su texto, su icono y lo demás que se pasó."""

    kind: str
    text: str = ""
    icon: str = "NONE"
    target: str = ""  # bl_idname del operador o del menú, o nombre de la propiedad
    properties: Any = None  # las propiedades del operador, que el draw rellena
    options: dict[str, Any] = field(default_factory=dict)


class FakeLayout:
    """Lo mínimo de ``bpy.types.UILayout`` que usan los menús y paneles de Geoblender."""

    def __init__(self, items: list[Item] | None = None) -> None:
        self.items: list[Item] = [] if items is None else items
        self.enabled = True
        self.active = True
        self.alert = False
        self.use_property_split = False
        self.use_property_decorate = True
        self.scale_y = 1.0
        self.operator_context = "INVOKE_DEFAULT"

    def _add(self, item: Item) -> Item:
        self.items.append(item)
        return item

    def label(self, *, text: str = "", icon: str = "NONE", **options: Any) -> None:
        self._add(Item("label", text, icon, options=options))

    def operator(
        self, operator: str, *, text: str = "", icon: str = "NONE", **options: Any
    ) -> SimpleNamespace:
        properties = SimpleNamespace()
        self._add(Item("operator", text, icon, operator, properties, options))
        return properties

    def prop(self, data: Any, property: str, *, text: str | None = None, icon: str = "NONE",
             **options: Any) -> None:
        shown = "" if text is None else text
        value = getattr(data, property, None)
        self._add(Item("prop", shown, icon, property, value, options))

    def menu(self, menu: str, *, text: str = "", icon: str = "NONE", **options: Any) -> None:
        self._add(Item("menu", text, icon, menu, None, options))

    def separator(self, **options: Any) -> None:
        self._add(Item("separator", options=options))

    def _child(self, **_options: Any) -> FakeLayout:
        return FakeLayout(self.items)

    column = row = box = split = grid_flow = column_flow = _child

    # Lectura ---------------------------------------------------------------------------

    def of_kind(self, kind: str) -> list[Item]:
        """Los elementos de un tipo, en orden."""
        return [item for item in self.items if item.kind == kind]

    def texts(self) -> list[str]:
        """Los textos de etiquetas, operadores y menús, en orden."""
        return [item.text for item in self.items if item.text]


class _Owner:
    """Hace de ``self`` del ``draw``: tiene el *layout* simulado y, para lo demás, los
    atributos y métodos de la clase (las clases de Blender no se pueden instanciar)."""

    def __init__(self, cls: type, layout: FakeLayout, attributes: dict[str, Any]) -> None:
        self.__dict__.update(attributes)
        self.layout = layout
        self._cls = cls

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._cls, name)
        if inspect.isfunction(value):
            return MethodType(value, self)
        return value


def draw(cls: type, context: Any, **attributes: Any) -> FakeLayout:
    """Llama al ``draw`` de la clase de un menú o un panel con un :class:`FakeLayout` y
    devuelve el *layout* con lo dibujado."""
    layout = FakeLayout()
    cls.draw(_Owner(cls, layout, attributes), context)
    return layout
