# SPDX-License-Identifier: GPL-3.0-or-later
"""El catálogo de comandos visto desde Blender (spec 003; RF-003-06, RF-003-07,
RF-003-08; plan 003 §5.3; BS §7).

- :func:`catalog`: el catálogo de ``core.catalog`` (en caché);
- :func:`text`: un texto del catálogo (``msgid`` en inglés) en el idioma activo de
  Geoblender, nunca en el de Blender (ADR-0012 §4). ``core.i18n.tr`` es para los
  ``msgid`` literales de ``messages.toml``; las etiquetas y descripciones de los
  comandos llegan como variable y pasan por aquí;
- :func:`unavailable_note` y :func:`with_note`: «Disponible en …» de un comando y su
  descripción emergente con esa nota en otra línea (RF-003-07; spec 003, T39: también la
  de los menús y paneles no disponibles, que no se abren);
- :func:`registered_class`: la clase registrada de un operador (por su ``bl_idname``) o
  de un menú o un panel (por su clase);
- :func:`is_available`: si un comando está **disponible** (BS §7.3): un nativo de
  Blender, siempre; uno de Geoblender, si su entrada ya está entregada (``delivered`` en
  ``entries.toml``) y su clase registrada es la real, no la provisional. Así una variante
  de una entrada posterior (``geo_set_clip_mode?mode=FRONT``, R-16) sale no disponible
  aunque el operador sea real. Un menú generado del catálogo cuya entrada aún no se ha
  entregado está disponible si lo está alguno de sus elementos (Encaje ▾, de R-09, con el
  conmutador nativo; Recorte ▾, de R-16, con «Sin recorte» y «Banda de la vista» de la
  003). Se calcula una vez por registro (:func:`refresh`).
- :func:`register_check` y :func:`not_applicable` (RF-003-09; BS §7.3, «No aplicable
  ahora»): el ``poll`` de un operador no sabe con qué propiedades se va a llamar, así que
  lo que depende de ellas (recuperar una ranura vacía) lo dice una comprobación por
  ``bl_idname``, que recibe el contexto y el comando (con sus propiedades fijas) y
  devuelve "" o el mensaje con el paso previo; ``drawing.draw_command`` dibuja ese
  comando desactivado.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import bpy

from ...core import catalog as core_catalog
from ...core.i18n import language, translate
from .. import ADDON_PACKAGE

TRANSLATION_CONTEXT = "Geoblender"
PROVISIONAL_FLAG = "_gb_provisional"  # atributo de las clases provisionales
NATIVE_KINDS = frozenset({"native", "property"})

_AVAILABLE: dict[str, bool] = {}
# bl_idname → comprobación de «no aplicable ahora»: (contexto, comando) → "" o el mensaje.
Check = Callable[[Any, core_catalog.Command], str]
_CHECKS: dict[str, Check] = {}


def catalog() -> core_catalog.Catalog:
    """El catálogo de comandos de la extensión (leído una vez)."""
    return core_catalog.load()


def text(msgid: str) -> str:
    """Un texto del catálogo en el idioma activo de Geoblender ("" si no hay)."""
    return translate(language(), msgid) if msgid else ""


def unavailable_note(cmd: core_catalog.Command) -> str:
    """«Disponible en <entrada · título>» de ``cmd`` en el idioma activo (RF-003-07)."""
    return core_catalog.unavailable_text(catalog(), cmd, language())


def with_note(about: str, note: str) -> str:
    """La descripción emergente de un comando no disponible: su descripción y, en otra
    línea, su «Disponible en …» (la misma en un operador, un menú y un panel; RF-003-07,
    CE-003-04). Sin una de las dos, la otra."""
    return f"{about}\n{note}" if about and note else (about or note)


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
        spec = cat.menus.get(cmd.key) if cmd.kind == "menu" else None
        if spec is None or is_provisional(registered_class(cmd.idname)):
            return False
        _AVAILABLE[cmd.key] = False  # mientras se mira dentro (un ciclo no lo hace disponible)
        return any(is_available(item.key) for group in spec.groups for item in group.items
                   if item.key is not None)
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


def register_check(idname: str, check: Check) -> None:
    """Pone la comprobación de «no aplicable ahora» de un ``bl_idname``."""
    _CHECKS[idname] = check


def unregister_check(idname: str) -> None:
    """Quita la comprobación de un ``bl_idname`` (sin ella, nada)."""
    _CHECKS.pop(idname, None)


def not_applicable(context: Any, cmd: core_catalog.Command) -> str:
    """"" si el comando se puede ejecutar ahora; si no, el mensaje que nombra el paso
    previo (RF-003-09). Sin comprobación, "" (lo demás lo dice su ``poll``)."""
    check = _CHECKS.get(cmd.idname)
    return check(context, cmd) if check is not None else ""


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
