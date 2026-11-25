# SPDX-License-Identifier: GPL-3.0-or-later
"""Las áreas de la interfaz de Geoblender (spec 019, plan §5.1).

Dos cosas, ambas datos sin ``bpy`` (se pueden leer sin Blender):

- La **revisión de la disposición** (T16; P-9): el entero que
  ``tools/inblender/make_ui_blend.py`` escribe en cada espacio de trabajo de Geoblender
  (``WorkSpace["geoblender_layout_rev"]``) y que la extensión compara con el de un fichero
  guardado (T18). Súbalo cuando cambie el reparto de áreas y regenere
  ``resources/geoblender_ui.blend``. El generador lee la línea ``LAYOUT_REV = n`` de este
  fichero sin importarlo (HER-01: las herramientas no importan ``bl``).
- La **lista de áreas decididas** (T17; RF-019-01): cada área, región o cabecera que se ve
  en modo Geoblender, con su decisión («de Geoblender», «sustituida», «oculta» o «de
  Blender», esta última siempre con su motivo). La revisa Samuel en
  ``docs/arquitectura/interfaz/areas-decididas.md``, que repite esta lista; una prueba
  comprueba que coinciden. Cambiar una decisión es cambiar una fila de aquí y del
  documento, y pasa por la spec.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

REV_KEY = "geoblender_layout_rev"  # la propiedad del espacio de trabajo (la escribe el generador)
FIRST_REV = 1  # un espacio de Geoblender sin la clave es de la 003 (revisión 1)
LAYOUT_REV = 3  # 1: la 003 (con línea de tiempo); 2: la 019 T16 (sin barra inferior, pestañas); 3: T38 (Outliner más alto)

#: Las cuatro decisiones posibles (clave → texto que lleva el documento).
DECISIONS: dict[str, str] = {
    "GEOBLENDER": "de Geoblender",
    "REPLACED": "sustituida",
    "HIDDEN": "oculta",
    "BLENDER": "de Blender",
}


def base_name(name: str) -> str:
    """El nombre de un espacio sin el sufijo ``.001`` que Blender añade a una copia."""
    return re.sub(r"\.\d{3}$", "", name)


def outdated_names(revisions: Mapping[str, int | None], known: Collection[str]) -> list[str]:
    """Las disposiciones de ``known`` (nombres del catálogo, en su orden) que el fichero tiene
    con una revisión anterior a :data:`LAYOUT_REV` (T18; P-9; R-4). ``revisions`` es
    «espacio de Geoblender → su ``geoblender_layout_rev``» (``None``: sin la clave). Una copia
    renovada («<nombre>.001») con la revisión actual cuenta: esa disposición ya está al día."""
    best: dict[str, int] = {}
    for name, rev in revisions.items():
        base = base_name(name)
        best[base] = max(best.get(base, FIRST_REV), FIRST_REV if rev is None else rev)
    return [name for name in known if name in best and best[name] < LAYOUT_REV]


@dataclass(frozen=True)
class AreaDecision:
    """Qué se hace con un área, región o cabecera en modo Geoblender.

    ``area``/``region`` son los tipos de Blender (``VIEW_3D``, ``HEADER``…) o, cuando no
    es una región de Blender (un gizmo, un campo de la barra superior), un nombre propio.
    ``reason`` es obligatorio para ``BLENDER``: por qué se deja tal cual.
    """

    area: str
    region: str
    label: str
    decision: str
    what: str
    reason: str = ""

    @property
    def key(self) -> str:
        return f"{self.area}/{self.region}"


def _d(area: str, region: str, label: str, decision: str, what: str,
       reason: str = "") -> AreaDecision:
    return AreaDecision(area, region, label, decision, what, reason)


AREAS: tuple[AreaDecision, ...] = (
    # Ventana: barra superior y barra de estado
    _d("TOPBAR", "HEADER_LEFT", "Barra superior (menús)", "REPLACED",
       "Conmutador, disposición, ≡ con los menús de Blender, los 13 menús del flujo y el "
       "acceso rápido del proyecto (parche de TOPBAR_HT_upper_bar.draw_left)"),
    _d("TOPBAR", "HEADER_RIGHT", "Barra superior: escena y capa de vista", "BLENDER",
       "Los selectores de escena y de capa de vista, a la derecha",
       "Sin ellos no se cambia de escena ni de capa; Geoblender trabaja sobre la escena "
       "activa y no tiene equivalente propio"),
    _d("STATUSBAR", "MINING", "Barra de estado minera", "GEOBLENDER",
       "Proyecto, versión, EPSG, cursor en coordenadas reales, encaje, sección, avisos y "
       "trabajos"),
    _d("STATUSBAR", "REPORT", "Barra de estado: informe de Blender", "BLENDER",
       "La línea del último informe de una orden",
       "Es el canal con el que Blender cuenta lo que ha pasado; con ratón real se retira "
       "sola en 10 a 14 s (ADR-0032, punto 6)"),
    _d("STATUSBAR", "BLENDER_INFO", "Barra de estado: versión y estadísticas", "BLENDER",
       "La versión de Blender y, si se activan, las estadísticas de escena",
       "Es información de la propia aplicación que quien da soporte necesita ver"),
    # Outliner
    _d("OUTLINER", "WINDOW", "Outliner", "GEOBLENDER",
       "Árbol del proyecto: colecciones numeradas y estado de la versión como color; sin "
       "cámaras ni luces (filtros por espacio)"),
    _d("OUTLINER", "HEADER", "Outliner: cabecera", "BLENDER",
       "Modo de visualización, buscador y filtros",
       "El buscador y los filtros son la forma de encontrar un elemento entre muchos; no "
       "hay razón para reescribirlos"),
    # Propiedades
    _d("PROPERTIES", "WINDOW", "Propiedades: contenido", "GEOBLENDER",
       "Las fichas «Geoblender · <Tipo>» y «Procedencia» y el aspecto del elemento; los "
       "paneles nativos quedan filtrados mientras haya una ventana en modo Geoblender"),
    _d("PROPERTIES", "NAVIGATION_BAR", "Propiedades: pestañas", "HIDDEN",
       "Todas las pestañas de Blender salvo «Objeto», que es la actual (render, salida, "
       "mundo, modificadores, partículas, física, restricciones, materiales…)"),
    _d("PROPERTIES", "HEADER", "Propiedades: cabecera", "BLENDER",
       "El buscador de ajustes del editor",
       "Es la cabecera del editor, sin ajustes de Blender dentro; no estorba y quitarla "
       "no aporta nada"),
    # Vista 3D
    _d("VIEW_3D", "HEADER", "Vista 3D: cabecera (fila 1)", "REPLACED",
       "Los menús nativos (View, Select, Add, Object) se pliegan en «Blender ▾» en modo "
       "Objeto (T20, hecha); delante, «Herramientas ▾» y «<Tipo> ▾»; en edición, los "
       "nativos"),
    _d("VIEW_3D", "TOOL_HEADER", "Vista 3D: fila 2", "GEOBLENDER",
       "El acceso rápido de la vista (24 controles) delante de los ajustes de la "
       "herramienta activa"),
    _d("VIEW_3D", "TOOLS", "Vista 3D: barra T", "BLENDER",
       "Las herramientas de Blender (seleccionar, cursor, mover, girar, escalar, anotar, "
       "medir, añadir cubo) y, tras ellas, las 7 de Geoblender",
       "Mover o escalar un objeto de proyecto lo saca de su coordenada: se deja tal cual "
       "(P-8) y la ficha avisa si el objeto se ha movido"),
    _d("VIEW_3D", "UI", "Vista 3D: barra N (Proyecto, Sección y <Tipo>)", "GEOBLENDER",
       "Pestañas Proyecto y Sección, siempre, y la del tipo del objeto activo"),
    _d("VIEW_3D", "UI_NATIVE_TABS", "Vista 3D: barra N (Elemento, Herramienta, Vista)",
       "BLENDER",
       "Las pestañas nativas de la barra N",
       "Vista (recorte, cámara) y Herramienta se usan a diario; Elemento muestra la "
       "posición local y la UTM está en «Coordenadas reales» del Proyecto"),
    _d("VIEW_3D", "WINDOW", "Vista 3D: la vista", "BLENDER",
       "El visor, con la selección y los dibujos de Geoblender encima",
       "Es el visor que Geoblender reutiliza (P10 de la interfaz): no se mantiene lo que "
       "Blender ya hace"),
    _d("VIEW_3D", "HUD", "Vista 3D: ajustar última operación", "BLENDER",
       "El panel flotante con los parámetros de la última operación",
       "Es la forma de Blender de reajustar una operación; las órdenes de Geoblender con "
       "ajuste posterior (F9) lo necesitan"),
    _d("VIEW_3D", "ASSET_SHELF", "Vista 3D: estantería de recursos", "BLENDER",
       "La estantería de recursos de Blender, que viene cerrada de fábrica",
       "Viene cerrada y Geoblender no usa recursos de Blender; solo se abre si la persona "
       "la pide con su botón"),
    _d("VIEW_3D", "ASSET_SHELF_HEADER", "Vista 3D: cabecera de la estantería", "BLENDER",
       "La cabecera de la estantería de recursos, cerrada junto con ella",
       "Va con la estantería de recursos, que viene cerrada de fábrica y no se toca"),
    _d("VIEW_3D", "GIZMO_NAVIGATE", "Vista 3D: gizmos de navegación", "BLENDER",
       "El gizmo de ejes, la mano y la lupa de arriba a la derecha",
       "Es la navegación de Blender y su memoria muscular debe seguir sirviendo al "
       "conmutar (P9 de la interfaz)"),
    _d("VIEW_3D", "GIZMO_TOOL", "Vista 3D: gizmos de la herramienta", "BLENDER",
       "Las flechas, los anillos y los cubos de mover, girar y escalar",
       "Dependen de la herramienta de la barra T, que se deja (P-8); si se ocultan sin "
       "ocultar la herramienta, esta queda sin guía"),
    # Otros editores de las disposiciones
    _d("SPREADSHEET", "WINDOW", "Hoja de cálculo", "BLENDER",
       "La hoja de cálculo de Blender en la disposición «Datos»",
       "Se reutiliza tal cual (P10 de la interfaz): enseña los datos del objeto activo"),
    _d("SPREADSHEET", "HEADER", "Hoja de cálculo: cabecera", "BLENDER",
       "Modo, objeto evaluado y filtros de filas",
       "Forman parte de la hoja de cálculo reutilizada"),
    _d("SPREADSHEET", "TOOLS", "Hoja de cálculo: barra lateral izquierda", "BLENDER",
       "Los filtros de filas y los conjuntos de datos",
       "Forman parte de la hoja de cálculo reutilizada"),
    _d("SPREADSHEET", "UI", "Hoja de cálculo: barra lateral derecha", "BLENDER",
       "Los ajustes de filas de la hoja",
       "Forman parte de la hoja de cálculo reutilizada"),
    _d("SPREADSHEET", "FOOTER", "Hoja de cálculo: pie", "BLENDER",
       "El recuento de filas",
       "Forman parte de la hoja de cálculo reutilizada"),
    _d("DOPESHEET_EDITOR", "WINDOW", "Fases: hoja de claves", "BLENDER",
       "La hoja de claves con los marcadores, solo en la disposición «Fases» (R-54)",
       "Es el editor de tiempo que las fases usan; en las demás disposiciones no se dibuja "
       "(RF-019-02)"),
    _d("DOPESHEET_EDITOR", "HEADER", "Fases: cabecera", "BLENDER",
       "Modo, marcadores y controles de la hoja",
       "Forman parte de la hoja de claves de las fases"),
    _d("DOPESHEET_EDITOR", "CHANNELS", "Fases: canales", "BLENDER",
       "La lista de canales a la izquierda de la hoja",
       "Forman parte de la hoja de claves de las fases"),
    _d("DOPESHEET_EDITOR", "UI", "Fases: barra lateral", "BLENDER",
       "Los ajustes de la hoja de claves",
       "Forman parte de la hoja de claves de las fases"),
    _d("DOPESHEET_EDITOR", "FOOTER", "Fases: pie", "BLENDER",
       "El pie de la hoja de claves",
       "Forman parte de la hoja de claves de las fases"),
)

_BY_KEY: dict[str, AreaDecision] = {item.key: item for item in AREAS}


def decision_for(key: str) -> AreaDecision:
    """La decisión de ``"<área>/<región>"``; ``KeyError`` si no está decidida."""
    return _BY_KEY[key]
