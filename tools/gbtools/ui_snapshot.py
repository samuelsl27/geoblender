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
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass


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


def compare(before: Mapping[str, object], after: Mapping[str, object], *,
            ignore: Collection[str] = ()) -> list[Difference]:
    """Las diferencias entre dos instantáneas, por clave (salvo las de ``ignore``)."""
    found: list[Difference] = []
    for key in sorted(set(before) | set(after)):
        if key not in ignore:
            found += _compare_values(key, before.get(key), after.get(key))
    return found


def report(before: Mapping[str, object], after: Mapping[str, object],
           steps: Sequence[Mapping[str, object]], *,
           ignore: Collection[str] = ()) -> dict[str, object]:
    """El informe de una comprobación: los pasos (cada uno con ``applied``), las
    diferencias entre la instantánea de antes y la de después y ``ok`` (sin diferencias y
    con todos los pasos aplicados)."""
    differences = compare(before, after, ignore=ignore)
    applied = all(bool(step.get("applied")) for step in steps)
    return {
        "ok": not differences and applied,
        "steps": [dict(step) for step in steps],
        "differences": [difference.as_dict() for difference in differences],
        "ignored": sorted(ignore),
    }
