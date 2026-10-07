# SPDX-License-Identifier: GPL-3.0-or-later
"""Comparación de instantáneas de la interfaz (spec 003, T38; RF-003-02, RF-003-23;
CE-003-02).

``tools/inblender/gui_check_003.py`` toma, dentro de Blender con interfaz, instantáneas de
lo que toca la interfaz de Geoblender (``draw_left`` de la barra superior, las funciones de
dibujo de las cabeceras y los menús que amplía, el mapa de complementos, las clases, los
manejadores, los espacios de trabajo…) como diccionarios que se pueden guardar en JSON:
cada valor es un texto, una lista de textos o un diccionario de listas de textos (una
función se escribe ``módulo.nombre@id``, para que otro objeto con el mismo nombre se vea
distinto). Este módulo, puro, las compara (:func:`compare`) y junta el informe
(:func:`report`). Lo prueba ``tests/unit/tools/test_gui_check_003.py``.

Convergencia, T43 (hallazgo D4 de la comprobación en pantalla):

- El espacio de trabajo marcado de Geoblender que anexa el conmutador la primera vez es
  del fichero por diseño (CW §3.3 y §4): :func:`appended_geoblender_workspaces` lo
  nombra (los marcados de después, ``geoblender_workspaces``, que antes no estaban en
  ``workspaces``) y :func:`compare` lo tolera en esas dos claves (``tolerated``). Cualquier
  otro espacio que sobre o falte, uno que pasa a estar marcado y uno marcado que falta
  siguen siendo diferencias.
- RNF-003-06 («el espacio de destino queda activo en el primer ciclo de eventos tras la
  orden») se cuenta desde que se ejecuta el operador (:func:`execution_cycle` y
  :func:`cycles_since_execution`), en pasos del temporizador del guion, que corre una vez
  por ciclo de eventos de Blender. En cada ciclo, Blender atiende los eventos
  (``wm_event_do_handlers``), después corre los temporizadores de Python (al principio de
  ``wm_event_do_notifiers``) y después aplica las notas, entre ellas el cambio de espacio
  (``ND_WORKSPACE_SET``). El botón y F3, que el guion ejecuta con ``bpy.ops`` dentro de su
  temporizador, cambian el espacio en ese mismo ciclo, y el paso siguiente lo ve: 1.
  Ctrl+F10 simulado se ejecuta al entregar el evento, en el ciclo siguiente a la orden y
  antes del paso del temporizador de ese ciclo, que aún no ve el cambio: contados desde la
  orden salían 2; desde la ejecución, 1, como el botón. :func:`report` exige 1 a cada
  paso con ciclos.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

WORKSPACES = "workspaces"  # los espacios de trabajo del fichero
GEOBLENDER_WORKSPACES = "geoblender_workspaces"  # los marcados (WorkSpace.geoblender_mode)
FIRST_CYCLE = 1  # RNF-003-06: activo en el primer ciclo tras ejecutarse el operador


@dataclass(frozen=True)
class Difference:
    """Una diferencia: la clave (``draw_funcs[STATUSBAR_HT_header]``), lo que sobra y lo
    que falta (en una lista) o el valor de antes y el de después."""

    key: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    before: str = ""
    after: str = ""

    def __str__(self) -> str:
        if self.added or self.removed:
            parts = []
            if self.added:
                parts.append(f"sobran {list(self.added)}")
            if self.removed:
                parts.append(f"faltan {list(self.removed)}")
            return f"{self.key}: {', '.join(parts)}"
        return f"{self.key}: «{self.before}» → «{self.after}»"

    def as_dict(self) -> dict[str, object]:
        return {"key": self.key, "added": list(self.added), "removed": list(self.removed),
                "before": self.before, "after": self.after, "text": str(self)}


def _items(value: object) -> list[str] | None:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return None


def _compare_values(key: str, old: object, new: object) -> list[Difference]:
    if old == new:
        return []
    old_items, new_items = _items(old), _items(new)
    if old is None and new_items is not None:
        old_items = []
    if new is None and old_items is not None:
        new_items = []
    if old_items is not None and new_items is not None:
        added = tuple(item for item in new_items if item not in old_items)
        removed = tuple(item for item in old_items if item not in new_items)
        if not added and not removed:  # mismo contenido en otro orden o repetido
            return [Difference(key, before=repr(old_items), after=repr(new_items))]
        return [Difference(key, added=added, removed=removed)]
    if isinstance(old, Mapping) or isinstance(new, Mapping):
        old_map = old if isinstance(old, Mapping) else {}
        new_map = new if isinstance(new, Mapping) else {}
        found: list[Difference] = []
        for sub in sorted(set(old_map) | set(new_map), key=str):
            found += _compare_values(f"{key}[{sub}]", old_map.get(sub), new_map.get(sub))
        return found
    return [Difference(key, before=str(old), after=str(new))]


def _without_tolerated(old: object, new: object, allowed: Collection[str]) -> object:
    """``new`` sin los elementos de ``allowed`` que no estaban en ``old``; si ``old`` no
    tenía la clave y no queda nada, como si ``new`` tampoco la tuviera."""
    new_items = _items(new)
    if new_items is None:
        return new
    old_items = _items(old) or []
    kept = [item for item in new_items if item in old_items or item not in allowed]
    return None if old is None and not kept else kept


def compare(before: Mapping[str, object], after: Mapping[str, object], *,
            ignore: Collection[str] = (),
            tolerated: Mapping[str, Collection[str]] | None = None) -> list[Difference]:
    """Las diferencias entre dos instantáneas, por clave (salvo las de ``ignore``). En
    las claves de ``tolerated`` (listas), los elementos tolerados que aparecen después sin
    estar antes no cuentan; los que faltan, sí."""
    tolerated = tolerated or {}
    found: list[Difference] = []
    for key in sorted(set(before) | set(after)):
        if key in ignore:
            continue
        new = after.get(key)
        if tolerated.get(key):
            new = _without_tolerated(before.get(key), new, tolerated[key])
        found += _compare_values(key, before.get(key), new)
    return found


def appended_geoblender_workspaces(
    before: Mapping[str, object], after: Mapping[str, object]
) -> dict[str, tuple[str, ...]]:
    """Lo que se tolera al comparar ``after`` con ``before``: los espacios marcados de
    Geoblender de después que el fichero no tenía antes (el anexado del conmutador, CW
    §3.3 y §4), en las claves ``workspaces`` y ``geoblender_workspaces``; vacío si no hay
    ninguno."""
    known = set(_items(before.get(WORKSPACES)) or ())
    appended = tuple(name for name in _items(after.get(GEOBLENDER_WORKSPACES)) or ()
                     if name not in known)
    return {WORKSPACES: appended, GEOBLENDER_WORKSPACES: appended} if appended else {}


def execution_cycle(tick: int, *, in_timer: bool) -> int:
    """El paso del temporizador del guion cuyo ciclo de eventos es el de la ejecución del
    operador: ``tick``, el paso en curso, si se ejecutó dentro del temporizador, y el
    siguiente si se ejecutó fuera, al entregar el evento, porque Blender atiende los
    eventos de un ciclo antes que sus temporizadores."""
    return tick if in_timer else tick + 1


def cycles_since_execution(applied_tick: int, executed: int | None) -> int | None:
    """Los ciclos desde el de la ejecución del operador (:func:`execution_cycle`) hasta
    el paso del temporizador que ve activo el espacio de destino (RNF-003-06: 1); ``None``
    si el operador no llegó a ejecutarse."""
    return None if executed is None else applied_tick - executed


def report(before: Mapping[str, object], after: Mapping[str, object],
           steps: Sequence[Mapping[str, object]], *,
           ignore: Collection[str] = (),
           tolerated: Mapping[str, Collection[str]] | None = None) -> dict[str, object]:
    """El informe de una comprobación: los pasos (cada uno con ``applied`` y, si se
    midieron, sus ``ticks``), las diferencias entre la instantánea de antes y la de
    después (con lo tolerado, :func:`compare`) y ``ok``: sin diferencias, con todos los
    pasos aplicados y cada uno activo en el primer ciclo tras ejecutarse el operador
    (RNF-003-06; ``late_steps``, los que no)."""
    tolerated = tolerated or {}
    differences = compare(before, after, ignore=ignore, tolerated=tolerated)
    applied = all(bool(step.get("applied")) for step in steps)
    late = [index for index, step in enumerate(steps)
            if isinstance(ticks := step.get("ticks"), int) and ticks > FIRST_CYCLE]
    return {
        "ok": not differences and applied and not late,
        "steps": [dict(step) for step in steps],
        "differences": [difference.as_dict() for difference in differences],
        "ignored": sorted(ignore),
        "tolerated": {key: sorted(values) for key, values in sorted(tolerated.items())
                      if values},
        "late_steps": late,
    }
