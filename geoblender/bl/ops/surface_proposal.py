# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que proponen los diálogos de superficies con lo seleccionado en la vista (T43, T45 de la 013).

Lo usan «Verificar un diseño por recinto…» y «Entre dos superficies…» (``bl.ops.res``, T43),
«Envolventes y escalonado…» (``bl.ops.des``, T45) y «Límite desde el perímetro…» (spec 014, T20). Cada diálogo tiene su lista de superficies (sus
identificadores) y su forma de saber qué superficie es cada uno (``choice_of``: del identificador
a su :class:`~geoblender.reserves.surfaces.SurfaceChoice`, o ``None``); lo de aquí solo mira los
objetos seleccionados y los nombres de los datos, y lee la ficha de una superficie de diseño. No
calcula ni escribe nada.

De las rejillas de un diseño (``bl.scene.des_views``: la envolvente ``des_env_``, la superficie de
diseño ``des_srf_``, las cotas de berma ``des_brm_`` y, de la 014, el recinto excavable
``des_rcn_`` y las cinco de una cantera, ``des_exp_``, ``des_fin_``, ``des_xen_``, ``des_fen_`` y
``des_cls_``), solo la superficie de diseño es una final; y ninguna es el terreno.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ...core.errors import GeoblenderError
from ...design import provenance as design_provenance
from ..props.core import OBJECT_PROPERTY
from ..scene import des_views

if TYPE_CHECKING:
    from ...reserves.surfaces import SurfaceChoice

__all__ = ["design_start_item", "ground_item", "is_design_grid", "is_design_surface",
           "selected_surfaces"]

LOGGER = logging.getLogger("geoblender.bl.ops")

SURFACE_KINDS = ("DTM", "TIN")  # Object.geoblender.kind de un objeto que muestra una superficie
DESIGN_SURFACE = des_views.prefix(design_provenance.DESIGN_GRID)  # «des_srf_»: la final
DESIGN_GRIDS = tuple(des_views.prefix(family) for family, _label in des_views.LOADERS)
"""El comienzo del nombre de las rejillas de un diseño (``des_env_``, ``des_srf_``, ``des_brm_``,
el recinto ``des_rcn_``, T20 de la 014, y las de una cantera, T22: ``des_exp_``, ``des_fin_``,
``des_xen_``, ``des_fen_`` y ``des_cls_``)."""

type ChoiceOf = Callable[[str], SurfaceChoice | None]


def _name(identifier: str, choice_of: ChoiceOf) -> str:
    """El nombre del dato de ``identifier`` (el identificador, si la lista no lo conoce)."""
    choice = choice_of(identifier)
    return identifier if choice is None else choice.name


def is_design_surface(identifier: str, choice_of: ChoiceOf) -> bool:
    """Si ``identifier`` (un elemento de la lista de superficies de un diálogo) es la superficie
    de diseño de la 013 (``des_srf_…``), la única de las tres rejillas de un diseño que es una
    final: la envolvente (``des_env_``) y las bermas (``des_brm_``) no lo son (T43)."""
    choice = choice_of(identifier)
    return choice is not None and choice.name.startswith(DESIGN_SURFACE)


def is_design_grid(identifier: str, choice_of: ChoiceOf) -> bool:
    """Si ``identifier`` es una de las rejillas de un diseño (``des_env_``, ``des_srf_``,
    ``des_brm_`` o el recinto ``des_rcn_``): ninguna es el terreno (T45)."""
    return _name(identifier, choice_of).startswith(DESIGN_GRIDS)


def selected_surfaces(context: Any, by_uid: Mapping[str, str], choice_of: ChoiceOf) -> list[str]:
    """Las superficies de la lista del diálogo (``by_uid``: uid del dato → identificador) que
    muestran los objetos seleccionados en la vista, en su orden y sin repetir: los de clase MDT o
    TIN y los ``DESIGN`` cuyo dato es una superficie de diseño (T43; una envolvente o unas bermas
    seleccionadas no cuentan)."""
    chosen: list[str] = []
    for obj in getattr(context, "selected_objects", None) or ():
        marks = getattr(obj, OBJECT_PROPERTY, None)
        found = None if marks is None else by_uid.get(str(marks.dataset_uid))
        if found is None or found in chosen:
            continue
        if marks.kind in SURFACE_KINDS or (marks.kind == des_views.KIND
                                           and is_design_surface(found, choice_of)):
            chosen.append(found)
    return chosen


def design_start_item(project: Any, identifier: str, items: Sequence[str],
                      choice_of: ChoiceOf) -> str | None:
    """La partida de la superficie de diseño ``identifier``: la de «Superficie de partida» de su
    ficha (``design.store.design_surface_start``, de los ajustes de la operación que la escribió)
    si es una de ``items`` (los identificadores que ofrece el diálogo). ``None`` si no es un
    diseño, si su ficha no la lleva, si ya no está en la lista o si el proyecto no se pudo leer (se
    deja en el registro): quien lo pide sigue como si no hubiera diseño (T43). Solo lee."""
    choice = choice_of(identifier)
    if choice is None or not is_design_surface(identifier, choice_of):
        return None
    from ...design import store as design_store  # al usarlo: habilitar no lo carga (T38)

    try:
        with project.read() as conn:
            found = design_store.design_surface_start(conn, choice.uid)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.info("No se pudo leer la superficie de partida de «%s»", choice.name,
                    exc_info=True)
        return None
    return found if found in items and found != identifier else None


def ground_item(context: Any, project: Any, items: Sequence[str],
                choice_of: ChoiceOf) -> str | None:
    """El terreno que propone un diálogo de ``items`` (sus identificadores, en su orden) con lo
    seleccionado en la vista (T45): el primer MDT o TIN seleccionado; si no hay, la partida de la
    ficha de la primera superficie de diseño seleccionada que la tenga en la lista
    (:func:`design_start_item`); si no, la primera de ``items`` que no es una rejilla de un diseño
    (:func:`is_design_grid`) y, si todas lo son, la primera. ``None`` si ``items`` está vacía."""
    by_uid = {choice.uid: identifier for identifier in items
              if (choice := choice_of(identifier)) is not None}
    chosen = selected_surfaces(context, by_uid, choice_of)
    terrain = next((item for item in chosen if not is_design_surface(item, choice_of)), None)
    if terrain is not None:
        return terrain
    for item in chosen:
        start = design_start_item(project, item, items, choice_of)
        if start is not None:
            return start
    return next((item for item in items if not is_design_grid(item, choice_of)),
                items[0] if items else None)
