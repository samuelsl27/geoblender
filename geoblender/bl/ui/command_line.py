# SPDX-License-Identifier: GPL-3.0-or-later
"""Línea de comandos F10 (spec 003; RF-003-26; HU-003-7; plan 003 §5.4, 10; AR §3.1, n.º
32; AT §2; BS §7.3).

F10 (en la Vista 3D, con la puerta de modo) o Herramientas ▸ Línea de comandos abren una
ventana con un campo de texto ya activo. Al escribir, Blender pide la lista de
:func:`suggestions`: los resultados de ``core.catalog.search.search`` en su orden —por
nombre en español o en inglés, alias (también los de Datamine), términos de otros
programas o entrada (``R-38``, ``r38``)—, cada uno con su etiqueta en el idioma de
Geoblender y, entre paréntesis, dónde está en la barra; los no disponibles llevan a la
derecha su «Disponible en …». Al confirmar, :func:`run` ejecuta el elegido (o, si se
escribió un texto sin elegir, el primer resultado):

- disponible: en la **Vista 3D de destino** (``views.target_view3d``: la que lanzó F10 o,
  desde la barra superior, la última usada o la mayor), como si se hubiera pulsado en su
  menú (``INVOKE_DEFAULT``: si el comando pide datos, abre su diálogo). Un menú se abre
  (``wm.call_menu``, o ``wm.call_menu_pie`` si es circular), un panel se abre bajo el
  cursor (``wm.call_panel``) y una propiedad nativa (Encaje) se conmuta;
- no disponible: informa «Disponible en …» y no cambia nada (RF-003-07);
- sin resultados: lo dice.

El estado (qué texto mostrado corresponde a qué comando) es de la sesión y solo vale para la
última lista. Puro de lógica: el operador ``geoblender.ui_open_command_line`` (``bl/ops/
ui.py``) solo abre la ventana y presenta el resultado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import bpy

from ...core.catalog import unavailable_text
from ...core.catalog.search import SearchHit, path_text, search
from ...core.i18n import language, tr
from . import commands, views
from .drawing import is_menu_id, property_owner

LIMIT = 30  # resultados de la lista (los de search())
SEPARATOR = "  ·  "  # entre la etiqueta y dónde está


class _State:
    def __init__(self) -> None:
        self.shown: dict[str, str] = {}  # texto de la última lista → clave del comando


_STATE = _State()


@dataclass(frozen=True)
class Outcome:
    """Lo que pasó al elegir: el estado del operador (``{"FINISHED"}`` o
    ``{"CANCELLED"}``), el nivel y el texto del informe ("" sin informe), la clave del
    comando elegido (o ``None``) y si estaba disponible."""

    status: set[str]
    level: str = ""
    message: str = ""
    key: str | None = None
    available: bool = False


def hits(query: str) -> list[SearchHit]:
    """Los resultados de ``search()`` para ``query`` en el idioma de Geoblender."""
    return search(commands.catalog(), query, language=language(),
                  is_available=commands.is_available, limit=LIMIT)


def display_text(hit: SearchHit) -> str:
    """El texto de un resultado en la lista: su etiqueta y, si tiene casa, dónde está
    («Cubicar entre dos superficies…  ·  Cubicación ▸ Cubicar»)."""
    where = path_text(commands.catalog(), hit.key, language(), parent=True)
    return f"{hit.label}{SEPARATOR}{where}" if where else hit.label


def suggestions(query: str) -> list[tuple[str, str]]:
    """La lista que muestra el campo al escribir ``query``: (texto, nota) por resultado,
    en el orden de ``search()``; la nota es "" si está disponible y su «Disponible en …»
    si no."""
    shown: dict[str, str] = {}
    items: list[tuple[str, str]] = []
    for hit in hits(query):
        text = display_text(hit)
        if text in shown:
            continue  # dos comandos con la misma etiqueta y la misma casa: el primero
        shown[text] = hit.key
        items.append((text, "" if hit.available else hit.unavailable_text))
    _STATE.shown = shown
    return items


def search_callback(_operator: Any, _context: Any, edit_text: str) -> list[tuple[str, str]]:
    """``search`` de la propiedad ``query`` del operador: la lista al escribir."""
    return suggestions(edit_text)


def resolve(query: str) -> SearchHit | None:
    """El comando de ``query``: el de la última lista si es uno de sus textos; si no, el
    primer resultado de buscarlo (``None`` si no hay ninguno)."""
    key = _STATE.shown.get(query)
    if key is None:
        found = hits(query)
        return found[0] if found else None
    cat = commands.catalog()
    cmd = cat.commands[key]
    available = commands.is_available(key)
    return SearchHit(key=key, label=commands.text(cmd.label),
                     path=path_text(cat, key, language()), score=100.0, field="label",
                     available=available,
                     unavailable_text="" if available else unavailable_text(cat, cmd,
                                                                            language()),
                     entry=cmd.entry, frequency=cmd.frequency)


def choose(query: str) -> Outcome:
    """Qué comando se ejecutaría con ``query`` (sin ejecutarlo)."""
    hit = resolve(query.strip())
    if hit is None:
        return Outcome({"CANCELLED"}, "WARNING",
                       tr("No command matches «{query}»", query=query.strip()))
    return Outcome({"FINISHED"}, key=hit.key, available=hit.available,
                   message="" if hit.available else hit.unavailable_text)


def _override(context: Any) -> dict[str, Any]:
    """El contexto de la Vista 3D de destino (vacío si la ventana no tiene ninguna)."""
    target = views.target_view3d(context)
    if target is None:
        return {}
    return {"window": target.window, "area": target.area, "region": target.region}


def _call_operator(idname: str, props: dict[str, Any]) -> set[str]:
    module, _, name = idname.partition(".")
    operator = getattr(getattr(bpy.ops, module), name)
    return set(operator("INVOKE_DEFAULT", **props))


def _execute(context: Any, key: str) -> set[str]:
    """Ejecuta el comando disponible de ``key`` en la Vista 3D de destino."""
    cat = commands.catalog()
    cmd = cat.commands[key]
    idname = cmd.idname
    with context.temp_override(**_override(context)):
        if cmd.kind == "property":
            data, name = property_owner(bpy.context, idname)
            setattr(data, name, not getattr(data, name))
            return {"FINISHED"}
        if cmd.kind == "panel":
            return set(bpy.ops.wm.call_panel(name=idname, keep_open=False))
        if cmd.kind == "menu" or (cmd.kind == "native" and is_menu_id(idname)):
            if idname in cat.pies:
                return set(bpy.ops.wm.call_menu_pie(name=idname))
            return set(bpy.ops.wm.call_menu(name=idname))
        return _call_operator(idname, dict(cmd.props))


def run(context: Any, query: str) -> Outcome:
    """Elige el comando de ``query`` y, si está disponible, lo ejecuta en la Vista 3D de
    destino; si no, informa «Disponible en …» sin cambiar nada (RF-003-26, RF-003-07)."""
    chosen = choose(query)
    if chosen.key is None:
        return chosen
    if not chosen.available:
        return Outcome({"CANCELLED"}, "INFO", chosen.message, chosen.key, False)
    try:
        status = _execute(context, chosen.key)
    except RuntimeError as exc:  # su poll falló: el motivo es el suyo
        reason = str(exc).split("\n")[-1].strip() or str(exc)
        return Outcome({"CANCELLED"}, "WARNING", reason, chosen.key, True)
    finished = "FINISHED" in status or "RUNNING_MODAL" in status or "PASS_THROUGH" in status
    return Outcome({"FINISHED"} if finished else {"CANCELLED"}, key=chosen.key,
                   available=True)


def clear() -> None:
    """Olvida la última lista (al desregistrar)."""
    _STATE.shown = {}
