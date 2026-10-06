# SPDX-License-Identifier: GPL-3.0-or-later
"""Comandos provisionales con el identificador definitivo (spec 003; RF-003-07; plan 003
§5.4, 2, DT2; BS §7.2).

Para cada ``bl_idname`` del catálogo sin operador real, y para cada menú o panel del
catálogo sin clase, la interfaz registra una clase **provisional** con ese mismo
identificador: los atajos, los favoritos, F3, la documentación y los scripts apuntan desde
el primer día al nombre definitivo, y la spec que entrega el comando registra su clase real
en su lugar (``bl/ops``), sin provisional.

- **Operador** (:func:`operator_class`): ``poll`` = la puerta de modo (``bl.ui.gate``);
  invocado por menú, atajo, F3, favoritos o script, **informa** «Disponible en <entrada ·
  título>» y devuelve ``{'CANCELLED'}`` sin tocar la escena, los datos ni el proyecto. Su
  descripción dinámica (``description``) es la del comando (o de la variante que se pida)
  seguida de ese mismo texto. Admite las propiedades con que lo usan los menús y los atajos
  del catálogo (``geoblender.ui_set_view?view=PLAN``): un enumerado si todos sus valores
  son identificadores en mayúsculas, un entero, un booleano o, si no, un texto.
- **Menú** y **panel** (:func:`menu_class`, :func:`panel_class`): una sola línea
  desactivada con el texto, que también lleva su descripción emergente
  (:func:`class_description`; spec 003, T39). La misma nota, en otra línea, la pone
  :func:`labels` en la descripción de **todo** menú o panel del catálogo que no está
  disponible, sea provisional, generado o real: desactivados, un submenú o una ventana
  emergente no se abren y la nota solo se lee allí.

Los dibujos generados desde el catálogo ya los ponen desactivados (RF-003-07). Las clases
llevan ``bl_translation_context = "Geoblender"`` y los textos en el idioma activo de
Geoblender (``commands.text``); ``bl.ui.registry`` los vuelve a poner al cambiar de idioma.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from ...core.catalog import Catalog, Command, unavailable_text
from ...core.catalog.schema import PropValue, split_key
from ...core.i18n import language
from . import gate
from .commands import (
    PROVISIONAL_FLAG,
    TRANSLATION_CONTEXT,
    is_available,
    operator_class_name,
    text,
    with_note,
)
from .drawing import draw_note

_ENUM_VALUE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


# Lo que dice el catálogo de un bl_idname ------------------------------------------------


def variants(cat: Catalog, idname: str) -> tuple[Command, ...]:
    """Los comandos de un ``bl_idname`` (el comando sin propiedades y sus variantes)."""
    return cat.by_idname(idname)


def property_values(cat: Catalog, idname: str) -> dict[str, list[PropValue]]:
    """Los valores de cada propiedad con que el catálogo usa ``idname``: los de sus
    variantes y los de sus atajos (``geo_step_section?half=True``), en orden."""
    values: dict[str, list[PropValue]] = {}
    keys = [cmd.key for cmd in variants(cat, idname)]
    keys += [shortcut.key for shortcut in cat.shortcuts() if shortcut.idname == idname]
    for key in keys:
        for name, value in split_key(key)[1]:
            found = values.setdefault(name, [])
            if value not in found:
                found.append(value)
    return values


def base_command(cat: Catalog, idname: str) -> Command | None:
    """El comando que da nombre al operador: el de la clave sin propiedades o, si solo hay
    variantes, el menú donde vive la mayoría de ellas («Vistas» para ``ui_set_view``,
    «Recorte» para ``geo_set_clip_mode``)."""
    exact = cat.commands.get(idname)
    if exact is not None:
        return exact
    homes = Counter(cmd.home for cmd in variants(cat, idname) if cmd.home)
    for home, _count in homes.most_common():
        menu = cat.commands.get(home)
        if menu is not None:
            return menu
    found = variants(cat, idname)
    return found[0] if found else None


def variant_for(cat: Catalog, idname: str, properties: Any) -> Command | None:
    """La variante del catálogo cuyas propiedades fijas coinciden con ``properties`` (la
    más específica); sin coincidencia, el comando sin propiedades, si lo hay."""
    best: Command | None = None
    for cmd in variants(cat, idname):
        if not cmd.props:
            continue
        try:
            same = all(getattr(properties, name) == value for name, value in cmd.props)
        except AttributeError:
            continue
        if same and (best is None or len(cmd.props) > len(best.props)):
            best = cmd
    return best or cat.commands.get(idname)


def entry_command(cat: Catalog, idname: str, properties: Any = None) -> Command | None:
    """El comando cuya entrada se cita en «Disponible en …»: la variante pedida, el
    comando sin propiedades o la primera variante."""
    cmd = variant_for(cat, idname, properties) if properties is not None else None
    if cmd is None:
        cmd = cat.commands.get(idname)
    if cmd is None:
        found = variants(cat, idname)
        cmd = found[0] if found else None
    return cmd


def message(cat: Catalog, idname: str, properties: Any = None) -> str:
    """«Disponible en <entrada · título>» de ``idname`` (de la variante pedida), en el
    idioma activo."""
    cmd = entry_command(cat, idname, properties)
    if cmd is None:
        return ""
    return unavailable_text(cat, cmd, language())


def _property(name: str, values: list[PropValue]) -> Any:
    """La propiedad de Blender para los valores que usa el catálogo."""
    if values and all(isinstance(value, bool) for value in values):
        return BoolProperty(name=name, default=False, options={"SKIP_SAVE"})
    if values and all(isinstance(value, int) and not isinstance(value, bool)
                      for value in values):
        return IntProperty(name=name, default=0, options={"SKIP_SAVE"})
    if values and all(isinstance(value, str) and _ENUM_VALUE_RE.match(value)
                      for value in values):
        items = [(str(value), str(value), "") for value in values]
        return EnumProperty(name=name, items=items, options={"SKIP_SAVE"})
    return StringProperty(name=name, default="", options={"SKIP_SAVE"})


# Clases ---------------------------------------------------------------------------------


def operator_class(cat: Catalog, idname: str) -> type:
    """La clase de un operador provisional para ``idname``."""
    base = base_command(cat, idname)
    internal = any(cmd.kind == "internal" for cmd in variants(cat, idname))
    annotations: dict[str, Any] = {
        name: _property(name, values) for name, values in property_values(cat, idname).items()
    }

    def poll(cls: Any, context: Any) -> bool:
        return gate.poll(cls, context)

    def execute(self: Any, context: Any) -> set[str]:
        self.report({"INFO"}, message(cat, idname, self.properties))
        return {"CANCELLED"}

    def invoke(self: Any, context: Any, event: Any) -> set[str]:
        return execute(self, context)

    def description(cls: Any, context: Any, properties: Any) -> str:
        cmd = variant_for(cat, idname, properties) or base
        about = text(cmd.description) if cmd is not None else ""
        return with_note(about, message(cat, idname, properties))

    namespace: dict[str, Any] = {
        "__doc__": base.description if base is not None else "",
        "__annotations__": annotations,
        "bl_idname": idname,
        "bl_label": text(base.label) if base is not None else idname,
        "bl_description": text(base.description) if base is not None else "",
        "bl_translation_context": TRANSLATION_CONTEXT,
        "bl_options": {"INTERNAL"} if internal else {"REGISTER"},
        PROVISIONAL_FLAG: True,
        "poll": classmethod(poll),
        "execute": execute,
        "invoke": invoke,
        "description": classmethod(description),
    }
    return type(operator_class_name(idname), (bpy.types.Operator,), namespace)


def _draw_note(cat: Catalog, cmd: Command) -> Any:
    def draw(self: Any, context: Any) -> None:
        draw_note(self.layout, unavailable_text(cat, cmd, language()))

    return draw


def class_description(cat: Catalog, cmd: Command, *, available: bool) -> str:
    """``bl_description`` de un menú o un panel en el idioma activo: la descripción del
    comando y, si no está disponible, su «Disponible en …» en otra línea, como la de un
    operador provisional (RF-003-07, CE-003-04; spec 003, T39)."""
    about = text(cmd.description)
    return about if available else with_note(about, unavailable_text(cat, cmd, language()))


def menu_class(cat: Catalog, cmd: Command) -> type:
    """La clase de un menú provisional: una línea desactivada con «Disponible en …», que
    también dice su descripción emergente."""
    namespace: dict[str, Any] = {
        "__doc__": cmd.description,
        "bl_idname": cmd.idname,
        "bl_label": text(cmd.label),
        "bl_description": class_description(cat, cmd, available=False),
        "bl_translation_context": TRANSLATION_CONTEXT,
        PROVISIONAL_FLAG: True,
        "draw": _draw_note(cat, cmd),
    }
    return type(cmd.idname, (bpy.types.Menu,), namespace)


def panel_class(cat: Catalog, cmd: Command) -> type:
    """La clase de un panel provisional (ventana emergente de la Vista 3D): una línea
    desactivada con «Disponible en …», que también dice su descripción emergente."""
    namespace: dict[str, Any] = {
        "__doc__": cmd.description,
        "bl_idname": cmd.idname,
        "bl_label": text(cmd.label),
        "bl_description": class_description(cat, cmd, available=False),
        "bl_translation_context": TRANSLATION_CONTEXT,
        "bl_space_type": "VIEW_3D",
        "bl_region_type": "HEADER",
        PROVISIONAL_FLAG: True,
        "draw": _draw_note(cat, cmd),
    }
    return type(cmd.idname, (bpy.types.Panel,), namespace)


def labels(cat: Catalog, idname: str) -> Mapping[str, str]:
    """``bl_label`` y ``bl_description`` de ``idname`` (operador, menú o panel) en el
    idioma activo, según el catálogo. La de un menú o un panel no disponible lleva su
    «Disponible en …» (:func:`class_description`); la de un operador, no: la añade su
    ``description`` dinámica, que conoce la variante pedida."""
    if "." in idname:
        cmd = base_command(cat, idname)
        if cmd is None:
            return {}
        return {"bl_label": text(cmd.label), "bl_description": text(cmd.description)}
    cmd = cat.commands.get(idname)
    if cmd is None:
        return {}
    available = is_available(cmd.key)
    return {"bl_label": text(cmd.label),
            "bl_description": class_description(cat, cmd, available=available)}
