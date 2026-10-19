# SPDX-License-Identifier: GPL-3.0-or-later
"""Un ``UILayout`` simulado para dibujar menús, paneles y cabeceras sin interfaz (spec 002,
T26 y T28; spec 003, T01; plan 003 §5.1, «layout simulado»).

En ``blender -b`` no hay regiones que dibujar: las pruebas llaman al ``draw`` de un menú,
de un panel o de una cabecera con un objeto que tiene ``layout`` (y lo que use el
``draw``) y leen lo que se pidió dibujar. :class:`FakeLayout` anota cada elemento en una
lista común a todo el árbol (columnas, filas y cajas incluidas) y admite los atributos
que se ponen a un *layout* (``enabled``, ``active``, ``alert``, ``ui_units_x``…).

Spec 003 (T01): cada elemento guarda además el estado **efectivo** de su *layout* al
dibujarlo (``enabled`` y ``active`` de la fila y de todas sus madres, como en Blender: una
fila desactivada desactiva lo de dentro), para comprobar que un comando no disponible se
dibuja desactivado (RF-003-07), y el ``ui_units_x`` de su fila (T18: el ancho explícito de
cada menú de texto de la barra). ``menu_pie`` devuelve, como ``row``, un *layout* hijo (los
menús circulares de la 003). Los métodos de ``UILayout`` que no tiene a mano
(``popover``, ``menu_contents``, ``template_ID_tabs``, ``operator_menu_enum``…) se anotan
con su nombre como tipo, para dibujar sin error las cabeceras de Blender que sustituye o
amplía la 003.

Spec 004 (T40): cada elemento guarda también el ``operator_context`` con que se dibujó; como
en Blender, es uno por *layout* raíz (``uiLayoutRoot``): ponerlo en una fila vale para lo que
se dibuje después en todo el *layout* (p. ej. ``EXEC_DEFAULT`` antes de los botones
``template_popup_confirm`` de un diálogo).

Spec 009 (T36): cada elemento guarda también si su *layout* separaba etiqueta y valor
(``use_property_split``) al dibujarlo. Como en Blender (``ui_litem_init_from_parent``), una
fila, columna o caja nueva hereda la de su madre al crearla; con ella, Blender lleva el texto
de ``prop`` y ``prop_enum`` a una columna de etiqueta a la izquierda y deja el botón sin texto.
Python puro: no importa ``bpy``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from types import MethodType, SimpleNamespace
from typing import Any


@dataclass
class Item:
    """Un elemento dibujado: su tipo (``label``, ``operator``, ``prop``, ``menu``,
    ``separator`` o el nombre del método de ``UILayout``), su texto, su icono y lo demás
    que se pasó."""

    kind: str
    text: str = ""
    icon: str = "NONE"
    target: str = ""  # bl_idname del operador o del menú, o nombre de la propiedad
    properties: Any = None  # las propiedades del operador, que el draw rellena
    options: dict[str, Any] = field(default_factory=dict)
    alert: bool = False  # el layout estaba en alerta (``layout.alert = True``)
    enabled: bool = True  # el layout y todas sus madres estaban habilitados (spec 003)
    active: bool = True  # ídem con ``active`` (gris, pero se puede pulsar)
    units_x: float = 0.0  # ``ui_units_x`` de su *layout* (0: el ancho natural; spec 003)
    operator_context: str = "INVOKE_DEFAULT"  # el del *layout* raíz al dibujarlo (spec 004)
    property_split: bool = False  # su *layout* separaba etiqueta y valor (spec 009, T36)


class FakeLayout:
    """Lo mínimo de ``bpy.types.UILayout`` que usan los menús, paneles y cabeceras."""

    def __init__(self, items: list[Item] | None = None, parent: FakeLayout | None = None) -> None:
        self.items: list[Item] = [] if items is None else items
        self.parent = parent
        self._root: FakeLayout = self if parent is None else parent._root
        self._operator_context = "INVOKE_DEFAULT"  # solo cuenta el de la raíz
        self.enabled = True
        self.active = True
        self.alert = False
        self.use_property_split = False
        self.use_property_decorate = True
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.ui_units_x = 0.0
        self.ui_units_y = 0.0
        self.alignment = "EXPAND"
        self.emboss = "NORMAL"

    @property
    def operator_context(self) -> str:
        """El de la raíz del *layout*, como en Blender (``uiLayoutRoot``)."""
        return self._root._operator_context

    @operator_context.setter
    def operator_context(self, value: str) -> None:
        self._root._operator_context = value

    def _effective(self, name: str) -> bool:
        layout: FakeLayout | None = self
        while layout is not None:
            if not getattr(layout, name):
                return False
            layout = layout.parent
        return True

    def _add(self, item: Item) -> Item:
        item.alert = bool(self.alert)
        item.enabled = self._effective("enabled")
        item.active = self._effective("active")
        item.units_x = float(self.ui_units_x)
        item.operator_context = self.operator_context
        item.property_split = bool(self.use_property_split)
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
        child = FakeLayout(self.items, parent=self)
        # Como en Blender, hereda al crearse la separación de etiqueta y valor de su madre.
        child.use_property_split = self.use_property_split
        child.use_property_decorate = self.use_property_decorate
        return child

    column = row = box = split = grid_flow = column_flow = menu_pie = _child

    def __getattr__(self, name: str) -> Callable[..., Any]:
        """Cualquier otro método público de ``UILayout`` (``popover``, ``menu_contents``,
        ``template_ID_tabs``, ``operator_menu_enum``…): anota un elemento con el nombre
        del método como tipo y su primer argumento de texto como destino."""
        if name.startswith("_"):
            raise AttributeError(name)

        def record(*args: Any, text: str = "", icon: str = "NONE", **options: Any) -> Any:
            target = args[0] if args and isinstance(args[0], str) else ""
            properties = SimpleNamespace()
            self._add(Item(name, text, icon, target, properties, options))
            return properties

        return record

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


def draw(cls: type, context: Any, *, method: str = "draw", **attributes: Any) -> FakeLayout:
    """Llama al ``draw`` (o a ``method``, p. ej. ``"draw_left"`` de una cabecera) de la
    clase de un menú, un panel o una cabecera con un :class:`FakeLayout` y devuelve el
    *layout* con lo dibujado."""
    layout = FakeLayout()
    getattr(cls, method)(_Owner(cls, layout, attributes), context)
    return layout


def operator_self(cls: type, **attributes: Any) -> Any:
    """Un ``self`` simulado de la clase ``cls`` (un operador) con ``attributes``, para llamar
    a mano a su ``invoke`` o a su ``execute`` (``cls.invoke(fake, contexto, None)``; spec 005,
    T49): sus métodos, los de la clase, ligados a él; lo que se le asigna queda en él."""
    return _Owner(cls, FakeLayout(), attributes)
