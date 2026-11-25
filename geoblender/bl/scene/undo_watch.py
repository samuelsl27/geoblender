# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl+Z y lo registrado en el proyecto (spec 008, RF-008-32; plan 008 §5.4.11 y decisión D13;
regla provisional de R-10).

Ctrl+Z y Ctrl+Mayús+Z de Blender deshacen y rehacen la **escena**, nunca lo registrado en el
proyecto (un parámetro, una decisión sobre una entrada, una operación hecha): las órdenes que
escriben en el proyecto no entran en la pila de deshacer. La API de Python no expone esa pila,
así que el diario de Ctrl+Z de la sesión (:data:`JOURNAL`, un
``core.provenance.undo.UndoJournal``) numera cada cambio registrado y :func:`record` sella con
su número todas las escenas (``Scene.geoblender.registry_seq``) **sin empujar un paso de
deshacer**: la escena que Blender restaura trae el número que tenía.

Manejadores, todos ``@persistent`` (sin ello se pierden al abrir otro ``.blend``) y retirados en
:func:`unregister`:

- ``undo_post`` y ``redo_post``: pasan al diario el número de la escena restaurada
  (:func:`restored`) y, si deja atrás (deshacer) o recupera (rehacer) algo registrado, lo avisan
  en la barra de estado durante 10 s (``bl.ui.provenance.show_undo_notice``): «Ctrl+Z no
  deshace la operación «gis.resample»: sigue en el proyecto». Nada de lo registrado cambia, ni
  el proyecto ni lo anotado en el diario. Una escena sin ``Scene.geoblender`` no avisa.
- ``load_post``: un ``.blend`` recién abierto empieza su historia de deshacer con el número de
  su escena (``UndoJournal.scene_loaded``): lo registrado antes no sale en sus avisos.

Quien registra un cambio llama a :func:`record` después de confirmarlo (``bl.ops``); el diario es
de la sesión de Blender, no del proyecto: el aviso dice lo que sigue en el proyecto en el que se
registró.
"""

from __future__ import annotations

import logging
from typing import Any

import bpy
from bpy.app.handlers import persistent

from ...core import i18n
from ...core.provenance.undo import UndoJournal, UndoKind

LOGGER = logging.getLogger("geoblender.bl.scene")

JOURNAL = UndoJournal()
"""El diario de Ctrl+Z de esta sesión de Blender (lo usa también ``ProvenanceSession.journal``)."""


def scene_seq(scene: Any) -> int | None:
    """El número de lo registrado que trae ``scene`` (``Scene.geoblender.registry_seq``), o
    ``None`` si no lleva ``Scene.geoblender`` (o no es un número de escena)."""
    group = getattr(scene, "geoblender", None)
    seq = getattr(group, "registry_seq", None)
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        return None
    return seq


def stamp(seq: int) -> None:
    """Sella con ``seq`` todas las escenas del ``.blend`` (sin empujar un paso de deshacer). Si
    una no se puede escribir, lo deja en el registro técnico: lo registrado ya está en el
    proyecto."""
    for scene in bpy.data.scenes:
        group = getattr(scene, "geoblender", None)
        if group is None or group.registry_seq == seq:
            continue
        try:
            group.registry_seq = seq
        except (AttributeError, RuntimeError, TypeError, ValueError):
            LOGGER.warning("No se pudo anotar el cambio registrado %s en la escena «%s»", seq,
                           scene.name, exc_info=True)


def record(kind: UndoKind | str, label: str) -> int:
    """Apunta en :data:`JOURNAL` un cambio ya registrado en el proyecto (su clase y su etiqueta:
    la clave del parámetro, el nombre de la entrada o el tipo de la operación) y sella todas las
    escenas con su número (:func:`stamp`), que devuelve (RF-008-32). Si la escena de la ventana
    trae un número que el diario no tiene por suyo (Geoblender se habilitó con el ``.blend`` ya
    abierto), su historia empieza ahí, como al abrirlo: el número nuevo va después del suyo."""
    shown = scene_seq(getattr(bpy.context, "scene", None))
    if shown is not None and shown != JOURNAL.scene_seq:
        JOURNAL.scene_loaded(shown)
    seq = JOURNAL.record(kind, label)
    stamp(seq)
    return seq


def restored(scene: Any) -> str | None:
    """Lo que hacen ``undo_post`` y ``redo_post``: el diario pasa a la escena restaurada
    ``scene`` (``None``: la de la ventana) y, si deja atrás o recupera algo registrado, el aviso
    va a la barra de estado y se devuelve; si no, ``None``. No cambia nada registrado."""
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    notice = JOURNAL.restored(scene_seq(scene))
    if notice is None:
        return None
    text = notice.text(i18n.language())
    from ..ui import provenance as ui  # al usarlo: bl/scene se registra antes que bl/ui

    ui.show_undo_notice(text)
    return text


def _restored_safely(scene: Any) -> None:
    try:
        restored(scene)
    except Exception:  # noqa: BLE001 - un manejador que falla no tumba Blender
        LOGGER.exception("No se pudo avisar de lo registrado tras deshacer o rehacer")
    try:
        from . import appearance  # al usarlo; R-5 (spec 019, T08): tras deshacer o rehacer, manda la tabla del aspecto

        appearance.reconcile()
    except Exception:  # noqa: BLE001
        LOGGER.exception("No se pudo conciliar el aspecto con el proyecto tras deshacer o rehacer")


@persistent
def on_undo_post(scene: Any = None, *_args: Any) -> None:
    """Tras deshacer (Ctrl+Z): :func:`restored` con la escena restaurada (RF-008-32)."""
    _restored_safely(scene)


@persistent
def on_redo_post(scene: Any = None, *_args: Any) -> None:
    """Tras rehacer (Ctrl+Mayús+Z): :func:`restored` con la escena restaurada (RF-008-32)."""
    _restored_safely(scene)


@persistent
def on_load_post(*_args: Any) -> None:
    """Tras abrir un ``.blend``: su historia de deshacer empieza con el número de su escena (0
    sin él), sin aviso."""
    JOURNAL.scene_loaded(scene_seq(getattr(bpy.context, "scene", None)) or 0)


# (lista de bpy.app.handlers, función), en el orden en que se registran.
HANDLERS: tuple[tuple[str, Any], ...] = (
    ("load_post", on_load_post),
    ("undo_post", on_undo_post),
    ("redo_post", on_redo_post),
)


def register() -> None:
    """Añade los manejadores (sin repetirlos)."""
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function not in handlers:
            handlers.append(function)


def unregister() -> None:
    """Quita los manejadores (todas sus apariciones)."""
    for name, function in reversed(HANDLERS):
        handlers = getattr(bpy.app.handlers, name)
        while function in handlers:
            handlers.remove(function)
