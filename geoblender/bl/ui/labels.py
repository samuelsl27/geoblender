# SPDX-License-Identifier: GPL-3.0-or-later
"""Etiquetas que se leen enteras (spec 005, T49; hallazgos M1, M2 y M5 de la 005 en pantalla).

Una etiqueta de Blender (``layout.label``) no parte el texto: lo corta con «…» al ancho de su
diálogo o de su panel («Códigos nuevos: …s); 21, 23 (zonas)»). Aquí, un texto largo se parte en
líneas que caben, medidas con la fuente de la interfaz (``blf`` a 11 pt, como la barra de
estado: ``bl.compat.UI_FONT_POINTS``) más lo que añade la etiqueta con o sin icono
(``bl.compat.statusbar_widths``), en px a escala 1,0 (el ancho de un diálogo y el de la barra
lateral crecen con la escala, y el texto también):

- :func:`label_px`: lo que ocupa una etiqueta con un texto a una escala (medido una vez);
- :func:`wrapped`: las líneas de un texto (sus saltos de línea se respetan) que caben en un
  ancho; una palabra que no cabe sola va en su propia línea;
- :func:`draw_wrapped`: esas líneas como etiquetas de una columna alineada, la primera con su
  icono y las demás con su hueco (``BLANK1``);
- :func:`dialog_width` y :func:`sidebar_width`: lo que deja a sus etiquetas un diálogo de un
  ancho dado y la barra lateral (la de su región o, sin ella, la de por defecto);
- :func:`in_file_browser`: si la orden se dibuja en la barra del explorador de ficheros (las
  importaciones enseñan ahí solo una nota: lo que se declara lo pide su diálogo).
"""

from __future__ import annotations

from typing import Any

import blf

from .. import compat

UI_FONT_ID = 0
SIDEBAR_WIDTH_PX = 220.0
"""El ancho por defecto de la barra lateral de un editor (``UI_SIDEBAR_PANEL_WIDTH``), a escala
1,0."""
SIDEBAR_MARGIN_PX = 50.0
"""Lo que la barra lateral no deja a las etiquetas de un panel: sus pestañas, los márgenes del
panel y la barra de desplazamiento."""
DIALOG_MARGIN_PX = 30.0
"""Lo que un diálogo no deja a sus etiquetas: sus márgenes y los de una caja dentro."""
MIN_WIDTH_PX = 80.0
"""El ancho más pequeño en que se parte un texto (una región casi cerrada)."""
MAX_CACHED_TEXTS = 512
_WIDTHS: dict[tuple[str, float], float] = {}
_PADDING = compat.statusbar_widths()


def text_px(text: str, scale: float = 1.0) -> float:
    """El ancho ``blf`` de ``text`` con la fuente de la interfaz a la escala ``scale``, en px a
    escala 1,0 (el redondeo de la fuente a otra escala lo cambia un poco); medido una vez."""
    key = (text, scale)
    width = _WIDTHS.get(key)
    if width is None:
        if len(_WIDTHS) >= MAX_CACHED_TEXTS:
            _WIDTHS.clear()
        blf.size(UI_FONT_ID, compat.UI_FONT_POINTS * scale)
        width = float(blf.dimensions(UI_FONT_ID, text)[0]) / scale
        _WIDTHS[key] = width
    return width


def label_px(text: str, *, icon: bool = False, scale: float = 1.0) -> float:
    """Lo que ocupa una etiqueta con ``text`` y, si ``icon``, su icono (o su hueco), en px a
    escala 1,0, con la fuente a la escala ``scale``."""
    return text_px(text, scale) + (_PADDING.icon_label if icon else _PADDING.label)


def wrapped(text: str, width_px: float, *, icon: bool = False,
            scale: float | None = None) -> list[str]:
    """``text`` partido en líneas que caben como etiquetas (con icono, si ``icon``) en
    ``width_px`` px a escala 1,0, con la fuente a la escala ``scale`` (por defecto, la de la
    interfaz): por palabras (separadas por espacios normales: el fino sin ruptura de los miles,
    «4 400 040,5», no parte), sus saltos de línea respetados; una palabra que no cabe sola
    («(ACTUALIZACION.ULTIMA)», una ruta), en trozos (:func:`_pieces`). Un texto vacío,
    ninguna."""
    scale = compat.ui_scale() if scale is None else scale
    width = max(float(width_px), MIN_WIDTH_PX)

    def fits(shown: str) -> bool:
        return label_px(shown, icon=icon, scale=scale) <= width

    lines: list[str] = []
    for paragraph in text.splitlines():
        line = ""
        for word in (part for part in paragraph.split(" ") if part):
            longer = f"{line} {word}" if line else word
            if fits(longer):
                line = longer
                continue
            if line:
                lines.append(line)
            *whole, line = _pieces(word, fits)
            lines.extend(whole)
        if line:
            lines.append(line)
    return lines


BREAKS = "._/\\-"
"""Dónde se parte de preferencia una palabra que no cabe sola: tras uno de estos."""


def _pieces(word: str, fits: Any) -> list[str]:
    """``word`` en trozos que caben (``fits``): cada uno, lo más largo que cabe, cortado tras el
    último de :data:`BREAKS` que tenga, si tiene alguno; si no, por un carácter cualquiera (al
    menos uno por trozo)."""
    pieces: list[str] = []
    rest = word
    while rest and not fits(rest):
        cut = 1
        while cut < len(rest) and fits(rest[:cut + 1]):
            cut += 1
        soft = max((index + 1 for index in range(cut) if rest[index] in BREAKS), default=0)
        cut = soft or cut
        pieces.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        pieces.append(rest)
    return pieces


def draw_wrapped(layout: Any, text: str, width_px: float, *, icon: str = "NONE",
                 scale: float | None = None) -> list[str]:
    """``text`` (ya traducido) en etiquetas que caben en ``width_px`` (:func:`wrapped`): una
    columna alineada, la primera con ``icon`` y las demás con su hueco; devuelve las líneas."""
    with_icon = icon != "NONE"
    lines = wrapped(text, width_px, icon=with_icon, scale=scale)
    column = layout.column(align=True)
    for index, line in enumerate(lines):
        shown = icon if index == 0 else ("BLANK1" if with_icon else "NONE")
        column.label(text=line, icon=shown, translate=False)
    return lines


def dialog_width(width_px: float) -> float:
    """Lo que deja a sus etiquetas un diálogo (``invoke_props_dialog``) de ``width_px``."""
    return float(width_px) - DIALOG_MARGIN_PX


def sidebar_width(context: Any) -> float:
    """Lo que deja a las etiquetas de un panel la barra lateral de ``context``: el ancho de su
    región, a escala 1,0; sin región (o sin ancho), el de por defecto
    (:data:`SIDEBAR_WIDTH_PX`)."""
    region = getattr(context, "region", None)
    width = float(getattr(region, "width", 0) or 0)
    if width <= 0:
        return SIDEBAR_WIDTH_PX - SIDEBAR_MARGIN_PX
    return width / compat.ui_scale() - SIDEBAR_MARGIN_PX


def in_file_browser(context: Any) -> bool:
    """Si se dibuja en el explorador de ficheros (su barra de las propiedades de la orden)."""
    return getattr(getattr(context, "space_data", None), "type", "") == "FILE_BROWSER"
