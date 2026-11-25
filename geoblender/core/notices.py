# SPDX-License-Identifier: GPL-3.0-or-later
"""La cola de avisos de la barra de estado, con caducidad (spec 019, T05; RF-019-18; D-10; plan 019 A5).

Cada aviso lleva su nivel, su ``msgid`` (inglés, se traduce al mostrarlo con :func:`~.i18n.tr`) y sus campos. Vive
:data:`DEFAULT_TTL` (15 s) y se retira al cumplirse el plazo (:meth:`Queue.expire`) o con :meth:`Queue.clear`
por uno de los :data:`REASONS` (cancelar, cambiar de proyecto o de versión, conmutar a Blender, cambiar la
selección o el objeto activo). Un aviso repetido (mismo nivel, texto y campos) se cuenta una vez: renueva su plazo
y sube ``repeats`` (UI-09).

**El tiempo se inyecta (P-6)**: ninguna función lee el reloj; el llamante pasa ``now`` en segundos. Dominio puro:
ni ``bpy`` ni ``bl``; el temporizador que barre la cola y el campo de la barra de estado viven en ``bl/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from .errors import GeoblenderError
from .i18n import tr

__all__ = ["DEFAULT_TTL", "LEVELS", "Notice", "Queue", "REASONS"]

DEFAULT_TTL: float = 15
"""Plazo de un aviso, en segundos (D-10)."""

LEVELS: tuple[str, ...] = ("info", "warning", "error")
"""Niveles de un aviso, de menor a mayor gravedad."""

REASONS: tuple[str, ...] = ("cancel", "project", "version", "switch", "selection")
"""Motivos de :meth:`Queue.clear`: cancelar, cambiar de proyecto, cambiar de versión, conmutar a Blender y cambiar la
selección o el objeto activo (RF-019-18)."""


@dataclass(frozen=True)
class Notice:
    """Un aviso vivo. ``fields`` son pares ``(nombre, valor)`` ordenados; ``expires_at`` es el instante (el mismo
    reloj que ``now``) en que deja de estar."""

    level: str
    msgid: str
    fields: tuple[tuple[str, object], ...]
    created_at: float
    expires_at: float
    repeats: int = 1

    def text(self) -> str:
        """El texto en el idioma activo."""
        return tr(self.msgid, **dict(self.fields))

    def alive(self, now: float) -> bool:
        """Si sigue vivo en ``now`` (a los ``ttl`` segundos ya no lo está)."""
        return now < self.expires_at

    @property
    def key(self) -> tuple[str, str, tuple[tuple[str, object], ...]]:
        """Lo que identifica un aviso repetido."""
        return (self.level, self.msgid, self.fields)


class Queue:
    """La cola: en orden de llegada (el último es el más reciente). No es segura entre hilos: la usa el hilo
    principal."""

    def __init__(self) -> None:
        self._items: list[Notice] = []

    def __len__(self) -> int:
        return len(self._items)

    def add(self, level: str, msgid: str, fields: Mapping[str, object] | None, now: float,
            ttl: float = DEFAULT_TTL) -> Notice:
        """Deja un aviso en la cola. Si ya había uno igual, lo renueva (plazo desde ``now``, ``repeats`` + 1) y pasa a
        ser el último."""
        if level not in LEVELS:
            raise GeoblenderError("core.notice_invalid", tr("the level must be one of: {levels}",
                                                            levels=", ".join(LEVELS)),
                                  obj=tr("Notice"), field=tr("Level"), value=level)
        if not msgid:
            raise GeoblenderError("core.notice_invalid", tr("the message cannot be empty"),
                                  obj=tr("Notice"), field=tr("Message"), value=msgid)
        if not ttl > 0:
            raise GeoblenderError("core.notice_invalid", tr("the time to live must be greater than zero"),
                                  obj=tr("Notice"), field=tr("Time to live"), value=ttl)
        notice = Notice(level, msgid, tuple(sorted((fields or {}).items())), now, now + ttl)
        for index, old in enumerate(self._items):
            if old.key == notice.key:
                del self._items[index]
                notice = replace(notice, repeats=old.repeats + 1)
                break
        self._items.append(notice)
        return notice

    def expire(self, now: float) -> int:
        """Retira los avisos cuyo plazo se cumplió en ``now``; devuelve cuántos."""
        alive = [item for item in self._items if item.alive(now)]
        removed = len(self._items) - len(alive)
        self._items = alive
        return removed

    def clear(self, reason: str) -> int:
        """Retira todos los avisos por ``reason`` (uno de :data:`REASONS`); devuelve cuántos."""
        if reason not in REASONS:
            raise GeoblenderError("core.notice_invalid", tr("the reason must be one of: {reasons}",
                                                            reasons=", ".join(REASONS)),
                                  obj=tr("Notice"), field=tr("Reason"), value=reason)
        removed = len(self._items)
        self._items = []
        return removed

    def alive(self, now: float) -> tuple[Notice, ...]:
        """Los avisos vivos en ``now``, del más antiguo al más reciente (no modifica la cola)."""
        return tuple(item for item in self._items if item.alive(now))

    def latest(self, now: float) -> Notice | None:
        """El aviso vivo más reciente en ``now``, o ``None`` (no modifica la cola)."""
        alive = self.alive(now)
        return alive[-1] if alive else None
