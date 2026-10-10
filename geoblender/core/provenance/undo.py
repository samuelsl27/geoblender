# SPDX-License-Identifier: GPL-3.0-or-later
"""Diario de Ctrl+Z de lo registrado en la sesión (spec 008, RF-008-32; plan 008 §5.3.1 y
§5.4.11; decisión D13 del plan).

Ctrl+Z y Ctrl+Mayús+Z de Blender deshacen y rehacen la escena, nunca lo registrado en el
proyecto (regla provisional de R-10). La API de Python no expone la pila de deshacer, así que
cada cambio registrado —un parámetro, una decisión sobre una entrada, una operación
completada— recibe un **número** del diario (:meth:`UndoJournal.record`) y ``bl`` lo copia en
la escena (``Scene.geoblender.registry_seq``) sin empujar un paso de deshacer: la escena que
Blender restaura trae el número que tenía. Los manejadores ``undo_post`` y ``redo_post`` (T57)
pasan ese número a :meth:`UndoJournal.restored`, que dice qué deja atrás la escena (deshacer) o
qué recupera (rehacer), con el texto de la barra de estado («Ctrl+Z no deshace la operación
«gis.resample»: sigue en el proyecto»).

- :class:`UndoJournal`: el diario de la sesión. Lo anotado no cambia nunca (nada de lo
  registrado se deshace); solo se mueve la escena que se ve (:attr:`UndoJournal.scene_seq`).
- :class:`UndoEntry`: un cambio registrado, con su número, su clase (:class:`UndoKind`), su
  etiqueta (el tipo de la operación, la clave del parámetro o el nombre de la entrada) y la
  escena sobre la que se registró (``parent``), y su texto (:meth:`UndoEntry.text`).
- :class:`UndoNotice`: lo que avisa un paso de deshacer o rehacer (:class:`UndoDirection`).

Cada cambio cuelga de la escena sobre la que se registró, así que los números forman la
historia de deshacer de la escena: lo registrado con la escena deshecha cuelga de ella (la rama
deshecha ya no sale en los avisos), y un ``.blend`` recién abierto empieza su historia
(:meth:`UndoJournal.scene_loaded`): lo registrado antes no es de ella. Python puro, sin
proyecto ni base de datos (ADR-0004).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .messages import render

__all__ = [
    "MESSAGE_CODES",
    "UndoDirection",
    "UndoEntry",
    "UndoJournal",
    "UndoKind",
    "UndoNotice",
]


class UndoKind(StrEnum):
    """Clase de un cambio registrado (RF-008-32)."""

    PARAMETER = "parameter"
    """El cambio de un parámetro (su clave)."""
    INPUT = "input"
    """Una decisión sobre una entrada: registrar, actualizar, mantener la copia, descartar o
    editar (su nombre)."""
    OPERATION = "operation"
    """Una operación completada (su tipo, ``gis.resample``)."""


class UndoDirection(StrEnum):
    """Hacia dónde va la escena restaurada."""

    UNDO = "undo"
    """Ctrl+Z: la escena deja atrás lo registrado después de ella."""
    REDO = "redo"
    """Ctrl+Mayús+Z: la escena recupera lo registrado hasta ella."""


_ITEM_CODES = {
    UndoKind.PARAMETER: "core.undo_item_parameter",
    UndoKind.INPUT: "core.undo_item_input",
    UndoKind.OPERATION: "core.undo_item_operation",
}

# Por sentido: uno, uno más y varios más.
_SENTENCE_CODES = {
    UndoDirection.UNDO: ("core.undo_kept", "core.undo_kept_one_more", "core.undo_kept_more"),
    UndoDirection.REDO: ("core.redo_kept", "core.redo_kept_one_more", "core.redo_kept_more"),
}

MESSAGE_CODES: tuple[str, ...] = (
    *_ITEM_CODES.values(),
    *(code for codes in _SENTENCE_CODES.values() for code in codes),
)
"""Los códigos de :mod:`.messages` que usa el diario."""


@dataclass(frozen=True, slots=True)
class UndoEntry:
    """Un cambio registrado en la sesión: su número ``seq`` (desde 1), su clase, su etiqueta y
    ``parent``, el número de la escena sobre la que se registró (0: una escena sin nada
    registrado)."""

    seq: int
    kind: UndoKind
    label: str
    parent: int

    def item(self, language: str = "es") -> str:
        """Cómo se nombra: «la operación «gis.resample»», «el cambio de «res.swell_factor»»,
        «la decisión sobre la entrada «Limites_v1»»."""
        return render(_ITEM_CODES[self.kind], language=language, label=self.label)

    def text(self, direction: UndoDirection | str = UndoDirection.UNDO, *,
             language: str = "es") -> str:
        """El aviso de la barra de estado si un paso de ``direction`` deja atrás o recupera
        solo este cambio: «Ctrl+Z no deshace la operación «gis.resample»: sigue en el
        proyecto». :class:`ValueError` con otro sentido o idioma."""
        return _sentence(UndoDirection(direction), self, 0, language)


@dataclass(frozen=True, slots=True)
class UndoNotice:
    """Lo que avisa un paso de deshacer o rehacer: ``entries`` (en el orden en que se
    registraron) es lo que la escena deja atrás (``UNDO``) o recupera (``REDO``)."""

    direction: UndoDirection
    entries: tuple[UndoEntry, ...]

    def text(self, language: str = "es") -> str:
        """El aviso de la barra de estado: nombra el cambio más reciente y cuenta los demás
        («Ctrl+Z no deshace la operación «gis.resample» ni otros 2 cambios registrados:
        siguen en el proyecto»)."""
        return _sentence(self.direction, self.entries[-1], len(self.entries) - 1, language)


class UndoJournal:
    """El diario de Ctrl+Z de la sesión (lo tiene ``bl``, en ``ProvenanceSession``).

    ``scene_seq`` es el número de la escena que se ve: lo pone :meth:`record` (``bl`` sella la
    escena con el número que devuelve), :meth:`restored` (la escena que restaura Blender) y
    :meth:`scene_loaded` (la de un ``.blend`` recién abierto; también al crear el diario).
    """

    def __init__(self, scene_seq: int = 0) -> None:
        self._entries: dict[int, UndoEntry] = {}
        self._last = 0
        self._floor = 0
        self._scene = _seq(scene_seq)

    @property
    def last(self) -> int:
        """El número del último cambio registrado (0 si no hay ninguno)."""
        return self._last

    @property
    def scene_seq(self) -> int:
        """El número de la escena que se ve, según el diario."""
        return self._scene

    @property
    def entries(self) -> tuple[UndoEntry, ...]:
        """Todo lo registrado en la sesión, por número (nunca cambia ni se quita nada)."""
        return tuple(self._entries.values())

    def record(self, kind: UndoKind | str, label: str) -> int:
        """Anota un cambio registrado (clase y etiqueta) sobre la escena que se ve y devuelve
        su número, mayor que todo lo anotado y que la escena; ``bl`` sella con él la escena.
        :class:`ValueError` con una clase desconocida o una etiqueta vacía; :class:`TypeError`
        si la etiqueta no es texto."""
        kind = UndoKind(kind)
        if not isinstance(label, str):
            raise TypeError(f"la etiqueta de un cambio registrado es un texto, no {label!r}")
        if not label.strip():
            raise ValueError("la etiqueta de un cambio registrado no puede estar vacía")
        seq = max(self._last, self._scene) + 1
        self._entries[seq] = UndoEntry(seq, kind, label, self._scene)
        self._last = self._scene = seq
        return seq

    def since(self, seq: int) -> list[UndoEntry]:
        """Lo que la escena con el número ``seq`` deja atrás respecto a la que se ve, en el
        orden en que se registró: lo que avisaría Ctrl+Z al restaurarla. Vacía si es la misma
        escena o si no es una escena anterior de su historia (otra rama u otro ``.blend``)."""
        return _ordered(self._path(self._scene, _seq(seq)))

    def restored(self, scene_seq: int | None) -> UndoNotice | None:
        """Blender restauró una escena con el número ``scene_seq`` (``None``: una escena sin
        número, que no avisa ni cambia nada). Devuelve lo que deja atrás (deshacer) o recupera
        (rehacer) respecto a la que se veía, o ``None`` si no hay nada (la misma escena, o una
        que no es de su historia); desde ahí, es la escena que se ve. Lo anotado no cambia."""
        if scene_seq is None:
            return None
        restored = _seq(scene_seq)
        shown, self._scene = self._scene, restored
        if (left := self._path(shown, restored)) is not None:
            direction, entries = UndoDirection.UNDO, left
        elif (recovered := self._path(restored, shown)) is not None:
            direction, entries = UndoDirection.REDO, recovered
        else:
            return None
        if not entries:
            return None
        return UndoNotice(direction, tuple(_ordered(entries)))

    def scene_loaded(self, scene_seq: int) -> None:
        """Se abrió un ``.blend`` cuya escena tiene el número ``scene_seq`` (0 sin número): su
        historia de deshacer empieza ahí, sin aviso, y lo registrado antes no sale en sus
        avisos; lo siguiente se numera después de todo."""
        self._scene = _seq(scene_seq)
        self._floor = self._last

    def _path(self, top: int, bottom: int) -> list[UndoEntry] | None:
        """Los cambios de la escena ``top`` por encima de la escena ``bottom``, del más
        reciente al más antiguo, o ``None`` si ``bottom`` no está debajo de ``top`` en su
        historia. Lo registrado antes de abrir el ``.blend`` (``_floor``) no es de ella."""
        path: list[UndoEntry] = []
        seq = top
        while seq > bottom:  # cada cambio cuelga de una escena de número menor
            entry = self._entries.get(seq) if seq > self._floor else None
            if entry is None:
                return None
            path.append(entry)
            seq = entry.parent
        return path if seq == bottom else None


def _seq(value: object) -> int:
    """Un número de escena: entero (no booleano) mayor o igual que 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"el número de una escena es un entero, no {value!r}")
    if value < 0:
        raise ValueError(f"el número de una escena no puede ser negativo: {value}")
    return value


def _ordered(path: list[UndoEntry] | None) -> list[UndoEntry]:
    """Los cambios de un camino en el orden en que se registraron."""
    return sorted(path or (), key=lambda entry: entry.seq)


def _sentence(direction: UndoDirection, named: UndoEntry, more: int, language: str) -> str:
    """El aviso de ``direction`` que nombra ``named`` y cuenta ``more`` cambios más."""
    code = _SENTENCE_CODES[direction][min(more, 2)]
    return render(code, language=language, item=named.item(language), more=more)
