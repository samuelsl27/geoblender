# SPDX-License-Identifier: GPL-3.0-or-later
"""Las propiedades del diseño de explotación (spec 013, T21; HU-013-1 a HU-013-6; RF-013-03,
RF-013-07, RF-013-18, RF-013-33; plan 013 §5.1 y §5.2.4).

``WindowManager.geoblender_design`` (:class:`GEOBLENDER_PG_des_panels`) guarda lo que dibujan las
ventanas «Perfiles de banco…», «Sectores de diseño…» y «Envolventes y escalonado…» y la barra N
«Diseño»:

- los **perfiles de banco** ya leídos del proyecto (:class:`GEOBLENDER_PG_des_profile`: su nombre y
  código, cómo se leen —«h 10 m · cara 60° · berma 6 m · ancla 125 m»—, sus derivados, lo que la
  rejilla no resuelve y sus cinco valores con su tipo y su ámbito,
  :class:`GEOBLENDER_PG_des_param`), el elegido (``profile_index``);
- los **sectores de diseño** (:class:`GEOBLENDER_PG_des_sector`: su nombre y código, su área, el
  estado de su búsqueda de intocables, su talud impuesto con su origen y decisor y el perfil
  asignado), el elegido (``sector_index``), y los parámetros huérfanos aparte (``orphans``);
- el **resumen** del cálculo en preparación (``summary``, con su título ``summary_title``) y el de
  la **vista previa** de las semillas (``preview``): líneas ya traducidas
  (:class:`GEOBLENDER_PG_des_line`), algunas en alerta (el ámbar de los avisos);
- el **dato del objeto activo** que enseña la barra N «Diseño» (T27: ``item_uid``, ``item_title`` y
  ``item``, las líneas leídas del proyecto con su ``kind``).

:class:`GEOBLENDER_PG_des_refit_surface` es una fila de la ventana de «Ajustar el diseño a un límite
nuevo…» (spec 014, T33): una superficie de diseño de la versión activa, lo que deja fuera del límite
vigente y si se ajusta; la orden la lleva en su propia colección, no en ``WindowManager``.

El nombre del grupo lleva su acción (``panels``, como el de la cubicación) porque NOM-01 la pide;
el plan 013 §5.2.4 lo llamaba ``GEOBLENDER_PG_des``.

Es una **vista** que se regenera desde el proyecto, nunca la fuente (nada se lee al dibujar, como la
008, la 010, la 011 y la 012); vive en ``WindowManager``, que Blender no guarda en el ``.blend``. El
cálculo en preparación en sí (las rejillas sin registrar) no es una propiedad: lo guarda
``bl.ops.des`` en memoria (:func:`~bl.ops.des.hold_calculation`). Las listas de superficies, zonas
y perfiles de los diálogos son enumerados dinámicos con una caché de módulo viva (plan §2.1).

``WindowManager.geoblender_design_preview`` (:data:`PREVIEW_PROPERTY`) es la vista previa de
semillas, dominios y restricciones como propiedad (RF-013-03; T25): apagada al empezar y **no se
guarda** (``SKIP_SAVE``). Su valor es el de ``bl.draw.design.enabled()`` (sin importarlo si no lo
está) y escribirla la activa —sobre la primera rejilla del proyecto, en todo su dominio— o la quita
(la importa al activarla); la orden ``geoblender.des_toggle_preview`` la enciende con lo que pide su
ventana y la apaga.

Ninguna propiedad es una coordenada ni una cota en ``FloatProperty`` (ADR-0005; las alturas, caras,
bermas, anclas, alcances y taludes de los diálogos, en ``StringProperty``: ``docs/trampas.md`` §1;
las coordenadas absolutas, en texto). Las propiedades de las filas no tienen nombre ni descripción:
las dibuja la ventana con sus textos.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

WINDOW_MANAGER_PROPERTY = "geoblender_design"
"""El nombre de la propiedad de ``WindowManager`` (la usan las ventanas del diseño)."""
PREVIEW_PROPERTY = "geoblender_design_preview"
"""El de la propiedad de ``WindowManager`` de la vista previa de semillas, dominios y
restricciones (RF-013-03)."""
_PREVIEW_MODULE = f"{__package__.rpartition('.')[0]}.draw.design"
_STATIC: set[str] = set()  # ni animable ni nada más


def _get_preview(_self: Any) -> bool:
    """Si la vista previa del diseño está activa (sin importarla si no lo está)."""
    module = sys.modules.get(_PREVIEW_MODULE)
    return bool(module is not None and module.enabled())


def _set_preview(_self: Any, value: bool) -> None:
    """Activa o quita la vista previa del diseño (la importa al activarla)."""
    if value:
        importlib.import_module(_PREVIEW_MODULE).enable()
        return
    module = sys.modules.get(_PREVIEW_MODULE)
    if module is not None:
        module.disable()


class GEOBLENDER_PG_des_param(bpy.types.PropertyGroup):
    """Un valor de un perfil de banco, o el talud de un sector, en la versión activa (``name``: el
    nombre del parámetro; ``key``: su clave): cómo se lee en la versión y en el proyecto
    (``text``: «V01: 10 m [HIP] · proyecto: sin valor [HIP] sin confirmar») y si está registrado
    (``registered``: sin registrar no se puede cambiar, se completa)."""

    key: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    text: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    registered: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_des_profile(bpy.types.PropertyGroup):
    """Un perfil de banco de la lista de «Perfiles de banco…» (RF-013-18, RF-013-19), ya leído del
    proyecto: su nombre (``name``) y su código (``code``, inmutable), cómo se lee
    (``summary``: «h 10 m · cara 60° · berma 6 m · ancla 125 m»), sus derivados (``derived``: el
    avance y el talud general), lo que la rejilla no resuelve (``unresolved``: vacío si todo se
    resuelve; se dibuja en ámbar), la insignia de tipo de sus valores (``badge``: [ADO] o [HIP],
    la del menos firme), el ámbito de donde salen (``scope``: «el proyecto», «V01» o «V01 y el
    proyecto»), lo que le falta o no vale en la versión activa (``problem``, en ámbar) y sus
    valores (``parameters``)."""

    code: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    summary: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    derived: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    unresolved: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    badge: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    scope: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    problem: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    parameters: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_param, options=_STATIC,
    )


class GEOBLENDER_PG_des_sector(bpy.types.PropertyGroup):
    """Un sector de diseño de la lista de «Sectores de diseño…» (RF-013-07 a RF-013-10), ya leído
    del proyecto: su nombre (``name``) y su código (``code``; vacío: el perímetro de actuación como
    único sector), su área ya escrita (``area``), el estado de su búsqueda de intocables
    (``search``: «Búsqueda vigente…» o «Búsqueda pendiente», ``pending`` si lo está), su talud
    general máximo impuesto (``slope``, vacío si no lo tiene: «10,6° [ADO]») con su origen, su
    decisor y su ámbito (``slope_source``: «la propiedad · decidido por … · V01»), lo que le pasa
    (``problem``: un talud guardado fuera de rango, en ámbar) y el perfil asignado a la superficie
    en preparación (``profile``: su código; ``profile_name``: su nombre).

    Lo que marca la persona en el diálogo de «Envolventes y escalonado…» (T24): ``use`` (acotar el
    dominio de trabajo a este sector) y ``profile_pick`` (el nombre del perfil que elige para él,
    de la lista de perfiles; vacío: el perfil base); en el de «Cantera con dos superficies…»
    (spec 014, T21), el de cada superficie: ``final_pick`` y ``exploitation_pick``. No son una
    lectura del proyecto: las conserva :func:`~bl.ui.des_panels.fill_sectors` al volver a leer."""

    code: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    area: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    search: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    pending: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]
    slope: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    slope_source: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    problem: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    profile: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    profile_name: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    use: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]
    profile_pick: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    final_pick: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    exploitation_pick: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_des_line(bpy.types.PropertyGroup):
    """Una línea de lo que dice una ventana, ya traducida (``name``: su texto; ``alert``: si va
    en alerta, en ámbar: un aviso, un sector pendiente, un perfil sin resolver). En la barra N
    «Diseño» (T27), ``kind`` dice cómo se dibuja (el título de un apartado, un dato, una cifra, un
    apartado vacío: los ``ROW_*`` de ``bl.ui.view_panels``) y ``uid`` es el de la cifra que
    nombra."""

    alert: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]
    kind: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    uid: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_des_refit_surface(bpy.types.PropertyGroup):
    """Una superficie de diseño de la versión activa que ofrece «Ajustar el diseño a un límite
    nuevo…» (spec 014, T33; RF-014-27; plan 014 §5.3.3): el nombre de su dato (``name``), lo que
    dice de ella la ventana, ya traducido (``label``: lo que deja fuera del límite vigente), si lo
    deja (``outside``: va en alerta) y si se ajusta (``selected``: marcada, de entrada, si queda
    fuera)."""

    label: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    outside: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]
    selected: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_des_panels(bpy.types.PropertyGroup):
    """Lo que dibujan las ventanas del diseño (una vista; véase el módulo)."""

    profiles: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_profile, options=_STATIC,
    )
    profile_index: IntProperty(default=0, min=0, options=_STATIC)  # type: ignore[valid-type]
    profiles_project: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    profile_report: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_line, options=_STATIC,
    )
    sectors: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_sector, options=_STATIC,
    )
    sector_index: IntProperty(default=0, min=0, options=_STATIC)  # type: ignore[valid-type]
    sectors_project: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    sector_report: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_line, options=_STATIC,
    )
    orphans: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_line, options=_STATIC,
    )
    summary_title: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    summary: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_line, options=_STATIC,
    )
    preview: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_line, options=_STATIC,
    )
    # La barra N «Diseño» (T27; RF-013-32): el dato del objeto activo, de qué proyecto es, si el
    # proyecto lo tiene, su título («Superficie de diseño · Hoyo») y sus líneas.
    item_uid: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    item_project: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    item_found: BoolProperty(default=False, options=_STATIC)  # type: ignore[valid-type]
    item_title: StringProperty(default="", options=_STATIC)  # type: ignore[valid-type]
    item: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_line, options=_STATIC,
    )


# En orden de registro: cada grupo, después de los que contiene.
classes: tuple[type, ...] = (GEOBLENDER_PG_des_param, GEOBLENDER_PG_des_profile,
                             GEOBLENDER_PG_des_sector, GEOBLENDER_PG_des_line,
                             GEOBLENDER_PG_des_refit_surface, GEOBLENDER_PG_des_panels)


def register() -> None:
    """Pone ``WindowManager.geoblender_design`` y ``geoblender_design_preview`` (apagada, sin
    guardarse en el ``.blend``); las clases ya están registradas."""
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_des_panels, options=_STATIC))
    setattr(bpy.types.WindowManager, PREVIEW_PROPERTY, BoolProperty(
        name="Preview of seeds, domains and constraints", get=_get_preview, set=_set_preview,
        options={"SKIP_SAVE"},
        description="Show the seeds, domains and constraints before computing"))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_design`` y ``geoblender_design_preview`` (antes de
    desregistrar las clases); sin ellas, nada."""
    for name in (PREVIEW_PROPERTY, WINDOW_MANAGER_PROPERTY):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
