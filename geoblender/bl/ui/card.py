# SPDX-License-Identifier: GPL-3.0-or-later
"""El cuerpo de la ficha del elemento activo (spec 019, T09; HU-019-1; RF-019-06, RF-019-14; plan 019 §5.1).

Dibuja, en dos cajas, las filas ya leídas del proyecto (``WindowManager.geoblender_view_panels.card``, que escribe
``bl.ui.view_panels.read_card``; dibujar **no lee** el proyecto):

- **Ficha** (UI-26): el nombre y el tipo del dato, su versión y su estado, si está al día en la vista, la operación que
  escribió su contenido, sus coordenadas absolutas **como texto validado** (RF-019-14: ninguna propiedad de la ficha es
  ``FloatProperty``), sus cifras con su insignia de tipo (MEDIDO, CALCULADO, ADOPTADO, HIPÓTESIS) y las líneas más de su
  módulo (la corta, la pista…);
- **Procedencia**: sus entradas (↑) y derivados (↓) y el botón de la cadena entera (``geoblender.core_show_lineage``);
  «sin procedencia aún» si no tiene ni operación ni entradas ni derivados.

Antes estaba en la barra N (``view_panels``); allí queda una línea con un botón que lleva aquí (UI-29). Lo dibuja
``bl.ui.element_panel``. Las etiquetas pasan por ``bl.ui.labels`` (partidas al ancho del área).
"""

from __future__ import annotations

from typing import Any

from ...core.i18n import tr
from ..scene import project_session, views
from . import labels, view_panels
from .view_panels import ROW_HEADING, ROW_ITEM, ROW_NONE, ROW_VIEW

BOX_MARGIN_PX = 12.0
"""Lo que quitan a las etiquetas el borde y el relleno de una caja (``layout.box()``)."""

draw_lines = view_panels._draw_lines  # noqa: SLF001 - el mismo ayudante que el resto de paneles de la vista


def view_text(obj: Any) -> tuple[str, bool]:
    """Si ``obj`` está al día en la vista (``Object.geoblender.view_state``): el texto y si va en alerta."""
    state = str(getattr(getattr(obj, view_panels.OBJECT_PROPERTY, None), "view_state", "CURRENT"))
    if state == views.VIEW_OUTDATED:
        return tr("In the view: not up to date: Refresh (F5)"), True
    if state == views.VIEW_UNBACKED:
        return tr("In the view: unbacked in the project"), True
    return tr("In the view: up to date"), False


_PROVENANCE_KINDS = frozenset({view_panels.ROW_ITEM, view_panels.ROW_NONE, view_panels.ROW_FIGURE,
                               view_panels.ROW_MARKS})
"""Las filas que solo hay en los apartados de procedencia (entradas, derivados y cifras): cualquier otra, no."""


def split_rows(rows: Any) -> tuple[list[Any], list[Any]]:
    """Las filas de la ficha partidas en las de la caja «Ficha» (el dato, su estado, su operación, su posición y las
    líneas más de su módulo) y las de «Procedencia» (↑ entradas, ↓ derivados y las cifras de su operación, con sus
    títulos y sus elementos): desde el primer título de apartado, lo que es de un apartado va a «Procedencia»; una
    línea de dato suelta (``ROW_FIELD``…), a la «Ficha»."""
    card: list[Any] = []
    provenance: list[Any] = []
    in_section = False
    for row in rows:
        if row.kind == ROW_HEADING:
            in_section = True
        (provenance if in_section and (row.kind == ROW_HEADING or row.kind in _PROVENANCE_KINDS) else card).append(row)
    return card, provenance


def _draw_rows(layout: Any, rows: Any, obj: Any, width: float) -> None:
    for row in rows:
        if row.kind == ROW_VIEW:
            text, alert = view_text(obj)
            draw_lines(layout, text, width, alert=alert)
            continue
        if row.kind == ROW_HEADING:
            layout.separator()
        sub = layout.column(align=True)
        sub.active = row.kind != ROW_NONE
        draw_lines(sub, row.text, width, icon=row.icon or "NONE", alert=row.alert)


def draw_card(layout: Any, context: Any) -> None:
    """El contenido de «Ficha» y «Procedencia» del objeto activo, ya leído; o por qué no hay. No lee el proyecto."""
    width = labels.sidebar_width(context) - BOX_MARGIN_PX
    view = view_panels._view(context)  # noqa: SLF001
    project = project_session.current()
    obj = view_panels._active_object(context)  # noqa: SLF001
    uid, owner = view_panels.shown_by(obj)
    if view is None or project is None or not uid or owner != project.uid:
        draw_lines(layout, tr("The active object does not show data of this project"), width, icon="INFO")
        return
    if view.card_uid != uid or view.card_project != owner:
        draw_lines(layout, tr("Reading the project data of the active object…"), width, icon="TIME")
        return
    if not view.card_found:
        draw_lines(layout, tr("The project no longer has the data of this object"), width, icon="ERROR", alert=True)
        return
    card, provenance = split_rows(view.card)
    sheet = layout.box()
    sheet.label(text=tr("Element card"), icon="INFO", translate=False)
    _draw_rows(sheet, card, obj, width)
    origin = layout.box()
    origin.label(text=tr("Provenance"), icon="NODETREE", translate=False)
    if not any(row.kind == ROW_ITEM for row in provenance) and any(
            row.text == tr("Operation: {operation}", operation=view_panels.NO_VALUE) for row in card):
        draw_lines(origin, tr("No provenance yet"), width)
    _draw_rows(origin, provenance, obj, width)
    button = origin.operator(view_panels.SHOW_LINEAGE, text=tr("Provenance"), icon="NODETREE", translate=False)
    button.item_uid = uid
