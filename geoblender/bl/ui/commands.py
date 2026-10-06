# SPDX-License-Identifier: GPL-3.0-or-later
"""El catálogo de comandos visto desde Blender (spec 003; RF-003-06, RF-003-07,
RF-003-08; plan 003 §5.3; BS §7).

- :func:`catalog`: el catálogo de ``core.catalog`` (en caché);
- :func:`text`: un texto del catálogo (``msgid`` en inglés) en el idioma activo de
  Geoblender, nunca en el de Blender (ADR-0012 §4). ``core.i18n.tr`` es para los
  ``msgid`` literales de ``messages.toml``; las etiquetas y descripciones de los
  comandos llegan como variable y pasan por aquí;
- :func:`registered_class`: la clase registrada de un operador (por su ``bl_idname``) o
  de un menú o un panel (por su clase);
- :func:`is_available`: si un comando está **disponible** (BS §7.3): un nativo de
  Blender, siempre; uno de Geoblender, si su entrada ya está entregada (``delivered`` en
  ``entries.toml``) y su clase registrada es la real, no la provisional. Así una variante
  de una entrada posterior (``geo_set_clip_mode?mode=FRONT``, R-16) sale no disponible
  aunque el operador sea real. Se calcula una vez por registro (:func:`refresh`).
"""

from __future__ import annotations

from typing import Any

import bpy

from ...core import catalog as core_catalog
from ...core.i18n import language, translate
from .. import ADDON_PACKAGE

TRANSLATION_CONTEXT = "Geoblender"
PROVISIONAL_FLAG = "_gb_provisional"  # atributo de las clases provisionales
NATIVE_KINDS = frozenset({"native", "property"})

_AVAILABLE: dict[str, bool] = {}


def catalog() -> core_catalog.Catalog:
    """El catálogo de comandos de la extensión (leído una vez)."""
    return core_catalog.load()


def text(msgid: str) -> str:
    """Un texto del catálogo en el idioma activo de Geoblender ("" si no hay)."""
    return translate(language(), msgid) if msgid else ""


def operator_class_name(idname: str) -> str:
    """El nombre de la clase de Blender de un operador
    (``geoblender.ui_toggle_mode`` → ``GEOBLENDER_OT_ui_toggle_mode``)."""
    module, _, name = idname.partition(".")
    return f"{module.upper()}_OT_{name}"


def registered_class(idname: str) -> type | None:
    """La clase registrada de un operador (``bl_idname``) o de un menú o un panel (su
    clase); ``None`` si no hay ninguna registrada."""
    name = operator_class_name(idname) if "." in idname else idname
    cls = getattr(bpy.types, name, None)
    if isinstance(cls, type) and getattr(cls, "is_registered", False):
        return cls
    return None


def is_provisional(cls: type | None) -> bool:
    """Verdadero si ``cls`` es un comando provisional (BS §7.2)."""
    return bool(cls is not None and cls.__dict__.get(PROVISIONAL_FLAG, False))


def _delivered(cat: core_catalog.Catalog, entry: str) -> bool:
    if not entry:
        return True
    ref = cat.entries.get(entry)
    return bool(ref is not None and ref.delivered)


def _compute(cat: core_catalog.Catalog, cmd: core_catalog.Command) -> bool:
    if cmd.kind in NATIVE_KINDS or cmd.entry == "Blender":
        return True
    if not _delivered(cat, cmd.entry):
        return False
    cls = registered_class(cmd.idname)
    return cls is not None and not is_provisional(cls)


def refresh() -> None:
    """Vuelve a calcular la disponibilidad de todos los comandos (al registrar)."""
    cat = catalog()
    _AVAILABLE.clear()
    for key, cmd in cat.commands.items():
        _AVAILABLE[key] = _compute(cat, cmd)


def clear() -> None:
    """Olvida la disponibilidad calculada (al desregistrar)."""
    _AVAILABLE.clear()


def is_available(key: str) -> bool:
    """Si el comando de ``key`` está disponible (BS §7.3); una clave desconocida, no."""
    if key in _AVAILABLE:
        return _AVAILABLE[key]
    cat = catalog()
    cmd = cat.commands.get(key)
    if cmd is None:
        return False
    value = _compute(cat, cmd)
    _AVAILABLE[key] = value
    return value


def preferences() -> Any:
    """El grupo ``ui`` de las preferencias de la extensión, o ``None`` si aún no están
    (una habilitación sin ``default_set``, o durante el registro)."""
    addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
    return getattr(getattr(addon, "preferences", None), "ui", None)


def preference(name: str, default: Any) -> Any:
    """Un ajuste del grupo ``ui`` de las preferencias, o ``default`` si no se puede
    leer."""
    value = getattr(preferences(), name, None)
    return default if value is None else value
