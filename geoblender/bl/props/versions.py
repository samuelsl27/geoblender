# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades de las versiones en Blender (spec 009; RF-009-10, RF-009-30; plan 009 §5.2.7).

- :class:`GEOBLENDER_PG_core_collection`, en ``Collection.geoblender``: la colección de una
  versión (RF-009-30, la T22 la crea y la pone al día): el uid de su versión (``version_id``, que
  ya lee ``bl.ui.context.collection_kind``: el menú «Versión ▾» de su clic derecho) y el estado de
  esa versión al nombrarla (``status``, uno de los cuatro de ADR-0013; ``NONE`` en una colección
  que no es de una versión). Lo demás de una colección de Geoblender sigue en su propiedad
  ``geoblender_key`` (``bl.scene.views``).
- :class:`GEOBLENDER_PG_core_version_panels`, en ``WindowManager.geoblender_version_panels``: las
  filas ya leídas que dibujan la ventana del control 8 (``GEOBLENDER_PT_core_version``) y el menú
  Proyecto ▸ Versiones ▸ Versión activa (``GEOBLENDER_MT_core_versions``): las versiones del
  proyecto (:class:`GEOBLENDER_PG_core_version_row`) y las revisiones de la activa
  (:class:`GEOBLENDER_PG_core_revision_row`), con los valores del proyecto, que los paneles
  presentan en el idioma de Geoblender al dibujarlas; nada se lee del proyecto al dibujar (como
  las de la 008 y la 010). Las ponen al día ``bl.scene.versions`` al abrir el proyecto, al cambiar
  la versión activa, al cargar la vista y tras cada lectura de los indicadores. Es una **vista**
  que se regenera; vive en ``WindowManager``, que no se guarda en el ``.blend`` de ``scenes/``.
  Tiene también las líneas de la ventana del informe de reproducir
  (:class:`GEOBLENDER_PG_core_report_row`, T23; ``GEOBLENDER_PT_core_reproduce_report``), ya
  presentadas al terminar la reproducción, y (T24; RF-009-13) las decisiones de la propiedad
  (:class:`GEOBLENDER_PG_core_decision_row`), los documentos que pueden citar
  (:class:`GEOBLENDER_PG_core_document_row`) y los encargos de las versiones
  (:class:`GEOBLENDER_PG_core_request_row`), de qué proyecto son (``decisions_project``): las
  dibujan la ventana Encargos y decisiones de la propiedad (``GEOBLENDER_PT_core_decisions``) y
  la del control 8 (las de la versión activa), y el diálogo «Registrar decisión…» ofrece los
  documentos; las pone al día ``bl.ui.version_panels.fill_decisions``.

Redibujar el control 8 y la barra de estado cuando cambia la versión activa lo pide
``bl.scene.versions.request_redraw`` con ``bl.ui.bars.redraw`` (T35, T41), que cambia
``WindowManager.geoblender_redraw`` (``bl.props.ui``).

La versión activa de la sesión, que sí se guarda con la vista, es
``Scene.geoblender.active_version_uid`` (``bl.props.core``). Las propiedades de las filas no tienen
nombre ni descripción: no se dibujan con los suyos. Ninguna se anima.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, PointerProperty, StringProperty

# Nombres de las propiedades (API pública de los guiones).
COLLECTION_PROPERTY = "geoblender"  # Collection.geoblender
WINDOW_MANAGER_PROPERTY = "geoblender_version_panels"  # WindowManager.geoblender_version_panels
NO_STATUS = "NONE"
"""El estado de una colección que no es la de una versión."""
# Los estados como los escribe ADR-0013 (core.versions.model.VersionStatus), con su etiqueta
# inglesa (su msgid), y el de una colección que no es de una versión.
COLLECTION_STATUSES: list[tuple[str, str, str]] = [
    (NO_STATUS, "Not a version", "A collection that is not the one of a version"),
    ("BORRADOR", "DRAFT", "A version being worked on, not yet delivered"),
    ("VIGENTE", "CURRENT", "The version in force"),
    ("SUPERADO", "SUPERSEDED", "A version replaced by another one: kept as a record"),
    ("DESCARTADO", "DISCARDED", "A discarded version: kept as a record"),
]
_STATIC: set[str] = set()  # ni animable ni nada más


class GEOBLENDER_PG_core_collection(bpy.types.PropertyGroup):
    """La colección de una versión (RF-009-30): su versión y el estado con que se nombró."""

    version_id: StringProperty(  # type: ignore[valid-type]
        name="Version",
        description="Identity of the version whose collection this is (empty: not a version)",
        default="",
        options=_STATIC,
    )
    status: EnumProperty(  # type: ignore[valid-type]
        name="Status",
        description="Status of its version when the collection was named",
        items=COLLECTION_STATUSES,
        default=NO_STATUS,
        options=_STATIC,
    )


class GEOBLENDER_PG_core_version_row(bpy.types.PropertyGroup):
    """Una versión del proyecto, como la lee ``core.versions.read``: su uid, su código, su
    título, su estado como lo guarda el proyecto («VIGENTE»…), la revisión que se enseña con ella
    («V10.r2»: la abierta o la última), el estado de esa revisión («open»…) y si está alterada."""

    uid: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    code: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    title: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    status: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    revision: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    revision_state: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    altered: BoolProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_revision_row(bpy.types.PropertyGroup):
    """Una revisión de la versión activa: su uid, su etiqueta («V10.r2»), su estado («open»,
    «frozen», «closed») y si está alterada."""

    uid: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    label: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    state: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    altered: BoolProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_report_row(bpy.types.PropertyGroup):
    """Una línea de la ventana del informe de reproducir (T23; RF-009-11), con su texto ya
    presentado en el idioma de Geoblender: de qué clase es (el resumen, un título, una salida o
    una cifra, una nota), su texto, su icono nativo y si va en alerta (lo que no coincide)."""

    kind: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    text: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    icon: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    alert: BoolProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_decision_row(bpy.types.PropertyGroup):
    """Una decisión de la propiedad (T24; RF-009-13; ``core.versions.model.Decision``): su uid,
    quién decide, el día de la decisión como se muestra («03/10/2026»), qué se decide, el nombre
    de su documento y su referencia en texto ("" si no tiene), las claves de parámetro, los uid
    de las versiones y sus códigos a los que afecta (separados por comas, en su orden)."""

    uid: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    decided_by: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    day: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    what: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    source_name: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    source_text: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    parameters: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    versions: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    version_codes: StringProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_document_row(bpy.types.PropertyGroup):
    """Una entrada de tipo documento que puede citar una decisión (T24): su uid y su nombre."""

    uid: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    label: StringProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_request_row(bpy.types.PropertyGroup):
    """El encargo de la propiedad que dio origen a una versión (T24): su código, su título y el
    texto del encargo."""

    code: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    title: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    request: StringProperty(options=_STATIC)  # type: ignore[valid-type]


class GEOBLENDER_PG_core_version_panels(bpy.types.PropertyGroup):
    """Lo que dibujan la ventana del control 8 y el menú de la versión activa (spec 009), la
    ventana del informe de reproducir (T23: de qué proyecto, de qué revisión y sus líneas) y la
    de los encargos y las decisiones de la propiedad (T24: de qué proyecto, sus decisiones, los
    documentos y los encargos): una vista del proyecto, regenerada desde él."""

    project: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    versions: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_version_row, options=_STATIC)
    revisions: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_revision_row, options=_STATIC)
    revisions_of: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    report_project: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    report_revision: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    report: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_report_row, options=_STATIC)
    decisions_project: StringProperty(options=_STATIC)  # type: ignore[valid-type]
    decisions: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_decision_row, options=_STATIC)
    documents: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_document_row, options=_STATIC)
    requests: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_request_row, options=_STATIC)


# En orden de registro (las filas, antes del grupo que las usa).
classes: tuple[type, ...] = (GEOBLENDER_PG_core_collection, GEOBLENDER_PG_core_version_row,
                             GEOBLENDER_PG_core_revision_row, GEOBLENDER_PG_core_report_row,
                             GEOBLENDER_PG_core_decision_row, GEOBLENDER_PG_core_document_row,
                             GEOBLENDER_PG_core_request_row, GEOBLENDER_PG_core_version_panels)


def register() -> None:
    """Pone ``Collection.geoblender`` y ``WindowManager.geoblender_version_panels`` (las clases
    ya están registradas)."""
    setattr(bpy.types.Collection, COLLECTION_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_collection, options=_STATIC))
    setattr(bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY,
            PointerProperty(type=GEOBLENDER_PG_core_version_panels, options=_STATIC))


def unregister() -> None:
    """Quita ``WindowManager.geoblender_version_panels`` y ``Collection.geoblender`` (antes de
    desregistrar las clases); sin ellas, nada."""
    for owner, name in ((bpy.types.WindowManager, WINDOW_MANAGER_PROPERTY),
                        (bpy.types.Collection, COLLECTION_PROPERTY)):
        if hasattr(owner, name):
            delattr(owner, name)
