# SPDX-License-Identifier: GPL-3.0-or-later
"""Objetos de la escena: creación y actualización de mallas, curvas y colecciones en
coordenadas locales respecto al GeoOrigin (ADR-0005).

- ``project_session``: el proyecto abierto en esta sesión, la marca de actividad de su
  cerrojo (temporizador persistente) y su cierre al desactivar o salir (spec 002);
- ``georef``: la georreferencia del proyecto en las escenas y sus manejadores
  (``load_post``, ``undo_post``, ``redo_post``, ``save_pre``, ``save_post``);
- ``undo_watch``: el diario de Ctrl+Z de lo registrado en el proyecto (spec 008, RF-008-32) y
  sus manejadores (``undo_post``, ``redo_post``, ``load_post``), que avisan de que deshacer no
  deshace lo registrado.
- ``triangulator``: la CDT de Blender como ``gis.ports.Triangulator`` y la elección entre
  ella y el trabajo ``gis_triangulate`` (spec 006; no registra nada);
- ``mesh``: mallas desde arrays absolutos, pasados a locales con ``core.georef`` (spec 006);
- ``views``: los datos del proyecto en la vista: el registro de cargadores por tipo de dato,
  ``Object.geoblender``, las colecciones tipadas, el ancla y el recorte (spec 006, RF-006-29);
- ``gis_views``: los cargadores de la topografía (rejillas, TIN, puntos y líneas; spec 006),
  que :func:`register` registra en ``views``;
- ``dh_view``: el cargador de las trazas de los sondeos (spec 005, T24; T29: sus tubos y sus
  barras de leyes, en pasos, con el trabajo ``dh_view_arrays``), después;
- ``live``: la marca en vivo de la vista (spec 010, T08): lo cargado, al día de lo que dice el
  proyecto sin volver a cargarlo, tras cada lectura de los indicadores de la procedencia y tras
  deshacer, rehacer, abrir un ``.blend``, cargar o descargar (``undo_post``, ``redo_post``,
  ``load_post``), por tandas desde su temporizador; el último;
- ``refresh``: los pasos de Refrescar las vistas desde el proyecto, F5 (spec 010, T11): vuelve
  a cargar lo que no está al día con los pasos de ``views`` (no registra nada);
- ``view_link``: ofrecer abrir el proyecto de una vista cargada sin él (spec 010, T12): la
  oferta que apunta ``georef`` al cargar el fichero y su temporizador de un disparo, que
  ``unregister`` retira.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import dh_view, georef, gis_views, live, project_session, undo_watch, view_link

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2); vacía hasta que una spec añada la primera.
classes: tuple[type, ...] = ()


def register() -> None:
    """Registra ``classes``, la sesión, los manejadores y los cargadores de vista; si ya lo
    están, no hace nada. Si algo falla, deshace lo hecho antes de propagar el error."""
    register_classes(classes)
    try:
        project_session.register()
        view_link.register()
        georef.register()
        undo_watch.register()
        gis_views.register()
        dh_view.register()
        live.register()
    except BaseException:
        live.unregister()
        dh_view.unregister()
        gis_views.unregister()
        undo_watch.unregister()
        georef.unregister()
        view_link.unregister()
        project_session.unregister()
        unregister_classes(classes)
        raise


def unregister() -> None:
    """Quita los cargadores de vista y los manejadores, olvida la oferta de abrir el proyecto
    de la vista, cierra el proyecto de la sesión (libera su cerrojo) y desregistra
    ``classes``, en orden inverso."""
    try:
        live.unregister()
        dh_view.unregister()
        gis_views.unregister()
        undo_watch.unregister()
        georef.unregister()
        view_link.unregister()
        project_session.unregister()
    finally:
        unregister_classes(classes)
