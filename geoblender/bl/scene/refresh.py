# SPDX-License-Identifier: GPL-3.0-or-later
"""Refrescar las vistas desde el proyecto, F5 (spec 010, T11; RF-010-01; RNF-010-01; plan 010
§5.3.2, A2, D-9 y D-11; reutiliza los pasos de carga de la 006, plan D2).

:func:`refresh_steps` da los pasos de la orden ``geoblender.core_refresh`` (``bl.ops.views``):

1. agrupa por dato los objetos de la escena y lee, en una instantánea del proyecto, lo que dice
   hoy de cada uno y lo que leen los cargadores con marca en vivo (``bl.scene.live.read_view``,
   la lectura de la marca en vivo); con ello, el plan (``core.views.state.refresh_plan``);
2. vuelve a cargar con su cargador, en los pasos de ``bl.scene.views.load_steps`` (con su avance,
   que lleva el nombre de cada dato, y Esc), lo que no está al día: lo que muestra otro
   contenido o se cargó con otro GeoOrigin (``OUTDATED``) y, en lugar de lo sustituido
   (``REPLACED``), su sucesor (``replaces``: en el último paso, lo sustituido sale y el sucesor
   toma su nombre). Un sucesor que ya está en la vista al día no se vuelve a cargar: lo
   sustituido solo sale (RF-010-01: «no volver a cargar lo que está al día»);
3. en el mismo último paso: marca «sin respaldo en el proyecto», sin borrarlo, lo descartado,
   lo sustituido sin sucesor vivo, lo que el proyecto no tiene y lo de otro proyecto
   (``unbacked``); pone al día, sin volver a cargarlos, el estado y la marca de obsoleto de lo
   demás (``RESTATE``) y «FALTA» en lo que falta, que no se puede volver a cargar (D-11)
   (``bl.scene.views.show_view_state``, con lo leído por los cargadores); pone en lo que
   muestra el contenido de hoy de su dato, sin volver a cargarlo, sus cifras registradas de hoy
   (``Object.geoblender.figures``, ``bl.scene.views.show_figures``; spec 010, T16, RF-010-08:
   lo que se vuelve a cargar ya las trae); y quita la marca de vista desfasada de las escenas
   (RF-002-29; D-9: sin errores, la vista queda al día del proyecto abierto). Después pide la
   marca en vivo, que lo cuenta otra vez (control 7).

Hasta ese último paso la escena no cambia: cerrar los pasos antes (Esc) la deja como estaba
(lo preparado se borra, como al cargar). Lo que no tiene dato del proyecto (lo del usuario, «99
Trabajo», el ancla) no entra; una malla editada a mano no cuenta (se compara el hash con que se
cargó, no la geometría, plan D3). Nada se escribe en el proyecto: los cargadores solo leen.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Generator, Mapping
from dataclasses import dataclass, replace
from typing import Any

import bpy

from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.project.model import Progress
from ...core.views.state import ItemState, ItemView, refresh_plan
from . import live, views

LOGGER = logging.getLogger("geoblender.bl.scene")

_SHOWN = frozenset({ItemState.CURRENT, ItemState.RESTATE})
"""Lo que muestra el contenido de hoy de su dato: no se vuelve a cargar."""


@dataclass(frozen=True)
class RefreshOutcome:
    """Lo que hizo Refrescar, por el uid de cada dato de la escena:

    - ``reloaded``: los datos que se cargaron otra vez (lo que no estaba al día o el sucesor de
      lo sustituido);
    - ``unbacked``: los marcados «sin respaldo en el proyecto», sin borrarlos;
    - ``missing``: los que faltan en el proyecto (su fichero o su tabla), que no se pueden
      volver a cargar;
    - ``current``: cuántos estaban al día (o solo cambiaron su estado o su marca de obsoleto,
      sin volver a cargarlos);
    - ``load``: lo que dijeron los pasos de carga (sus avisos y sus errores), o ``None`` si no
      había nada que volver a cargar;
    - ``replaced``: los sustituidos que salieron de la vista por su sucesor."""

    reloaded: tuple[str, ...]
    unbacked: tuple[str, ...]
    missing: tuple[str, ...]
    current: int
    load: views.LoadOutcome | None
    replaced: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """Si volvió a cargar o quitó algo de la vista (lo que entra en la pila de deshacer)."""
        return bool(self.reloaded or self.replaced)


def _names(states: Mapping[str, ItemView]) -> dict[str, str]:
    """El nombre de cada dato de ``states`` y de su sucesor, por su uid: el avance de los pasos
    de carga dice el nombre, no el uid."""
    found: dict[str, str] = {}
    for view in states.values():
        for record in (view.record, view.successor):
            if record is not None:
                found[record.uid] = record.name
    return found


def _clear_view_stale() -> None:
    for scene in bpy.data.scenes:
        if scene.geoblender.view_stale:
            scene.geoblender.view_stale = False


def refresh_steps(context: Any, project: Any) -> Generator[Progress, None, None]:
    """Los pasos que ponen al día con el proyecto abierto ``project`` la vista de la escena de
    ``context`` (véase el módulo): cada uno da su ``Progress`` (los de
    ``bl.scene.views.load_steps``, con el nombre de cada dato) y el último, el
    :class:`RefreshOutcome` en ``result``. Cerrarlos antes del último deja la escena como
    estaba. No escribe en el proyecto."""
    _groups, states, read = live.read_view(project)
    plan = refresh_plan(states)
    shown = {uid for uid, view in states.items() if view.state in _SHOWN}
    targets = [uid for uid in plan.targets if uid not in shown]
    replaces: dict[str, list[str]] = {}
    dropped: list[str] = []
    for loaded, target in plan.reload:
        if target in shown:
            dropped.append(loaded)  # su sucesor ya está en la vista, al día
        elif loaded != target:
            replaces.setdefault(target, []).append(loaded)
    names = _names(states)
    load: views.LoadOutcome | None = None
    if targets:
        for step in views.load_steps(context, project, targets, replaces=replaces,
                                     unbacked=plan.unbacked, clear_view_stale=True):
            if isinstance(step.result, views.LoadOutcome):
                load = step.result  # el último paso de la carga: ya está en la escena
            else:
                yield replace(step, message=names.get(step.message, step.message))
    # El mismo último paso (sin otro yield antes del final: cancelar no lo deja a medias).
    placed = set() if load is None else set(views.loaded_uids(load.objects))
    replaced = [uid for target in placed for uid in replaces.get(target, ())]
    if dropped:
        views.unload_datasets(dropped)
    rest = {uid: objects for uid, objects in views.loaded_items().items()
            if uid in states and uid not in placed}
    views.show_view_state(rest, states, live=read)
    # Las cifras registradas de hoy en lo que muestra su contenido de hoy (lo vuelto a cargar
    # ya las tiene): RF-010-08, «al cargar y al refrescar». Son solo para mostrarlas: si no se
    # pueden leer, quedan las que había y Refrescar sigue (lo demás ya está en la escena).
    try:
        views.show_figures(project, {uid: objects for uid, objects in rest.items()
                                     if uid in shown})
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("Refrescar no pudo leer las cifras registradas de la vista",
                       exc_info=True)
    if load is None:
        _clear_view_stale()
    live.request(project)
    current = sum(1 for uid in shown if uid not in placed)
    outcome = RefreshOutcome(tuple(uid for uid in targets if uid in placed), plan.unbacked,
                             plan.missing, current, load, tuple(replaced + dropped))
    yield Progress(views.LOAD_PHASE, views.STEPS_TOTAL, views.STEPS_TOTAL, "", outcome)


def outcome_text(outcome: RefreshOutcome) -> str:
    """Lo que dice Refrescar al terminar, en el idioma de Geoblender: «Vista al día: 1 dato
    vuelto a cargar, 2 sin respaldo en el proyecto, 197 al día» (solo lo que no es cero) o, si
    no volvió a cargar nada, «La vista está al día»."""
    if not outcome.changed:
        return tr("The view is up to date")
    parts: list[str] = []
    count = len(outcome.reloaded)
    if count:
        parts.append(tr("1 data item reloaded") if count == 1
                     else tr("{n} data items reloaded", n=count))
    if outcome.unbacked:
        parts.append(tr("{n} unbacked in the project", n=len(outcome.unbacked)))
    count = len(outcome.missing)
    if count:
        parts.append(tr("1 missing from the project") if count == 1
                     else tr("{n} missing from the project", n=count))
    if outcome.current:
        parts.append(tr("{n} up to date", n=outcome.current))
    if not parts:
        return tr("The view is up to date")
    return tr("View up to date: {parts}", parts=", ".join(parts))
