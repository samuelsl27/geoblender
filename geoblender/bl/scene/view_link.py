# SPDX-License-Identifier: GPL-3.0-or-later
"""Ofrecer abrir el proyecto de una vista (spec 010, T12; RF-010-04, RF-002-29; plan 010 §5.3.2,
A5, D-14, R3).

Cuando se carga un ``.blend`` que es vista de un proyecto que no está abierto (sin proyecto, o
tras cerrar el de otro: ``bl.scene.georef.check_loaded_file``, que antes avisa y deja la vista
desfasada, RF-002-29), :func:`offer_after_load` ofrece «Abrir el proyecto de esta vista»: apunta
la oferta (:class:`Offer`: la vista, lo que guarda su escena sobre su proyecto y el aviso) y pone
un temporizador de un disparo (:func:`offer_tick`, :data:`OFFER_DELAY_S` s después, tras el primer
ciclo de eventos: la carga no se puede detener, D6) que lanza en la primera ventana la orden
interna ``geoblender.core_open_view_project`` con su diálogo (:func:`launch`). Nunca abre el
proyecto: lo abre la orden si la persona acepta.

No se ofrece (``core.views.locate.offer_refusal``) con Blender sin interfaz (:func:`background`),
en un fichero de recuperación (``quit.blend``) o de autoguardado (``*_autosave.blend``) de las
carpetas temporales de Blender (:func:`temp_dirs`) ni en una vista dentro de una copia de
respaldo del proyecto (``.anterior``, ``.respaldo-esquema-N``, ``.publicando``). Para reconocer
una recuperación cuenta el fichero que se leyó (el argumento de ``load_post``), no
``bpy.data.filepath``, que al recuperar es el del original (010/T06).

En un fichero con escenas de varios proyectos se ofrece el de la escena de la ventana
(:func:`window_link`; D-14). La oferta dura hasta que se carga otro fichero (:func:`withdraw`, al
principio de ``check_loaded_file``): mientras no haya un proyecto abierto y el fichero siga siendo
de ese proyecto, el panel Proyecto la ofrece también (:func:`current_offer`), por si el diálogo se
cerró sin respuesta o se pulsó «Ahora no» (R3). :func:`unregister` la olvida y retira el
temporizador.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy

from ...core.i18n import tr
from ...core.paths import BLEND_RELATIVE_PREFIX
from ...core.views.locate import ViewLink, offer_refusal
from . import project_session

if TYPE_CHECKING:
    from .georef import SceneGeoref

LOGGER = logging.getLogger("geoblender.bl.scene")

OFFER_DELAY_S = 0.1
"""Cuándo se abre el diálogo tras cargar la vista: tras el primer ciclo de eventos (plan A5)."""
OPEN_VIEW_PROJECT = "geoblender.core_open_view_project"
"""La orden interna del diálogo «Abrir el proyecto de esta vista» (``bl/ops/views.py``)."""


@dataclass(frozen=True)
class Offer:
    """Lo que se ofrece abrir tras cargar una vista: el ``.blend`` que se cargó
    (``blend_file``), lo que guarda la escena sobre su proyecto (``link``: identidad, nombre y
    carpeta relativa al ``.blend``) y el aviso de RF-002-29 que se dio al cargarla."""

    blend_file: str
    link: ViewLink
    notice: str = ""

    def properties(self) -> dict[str, str]:
        """Las propiedades de la orden interna (``geoblender.core_open_view_project``)."""
        return {
            "filepath": self.blend_file,
            "project_uid": self.link.project_uid,
            "project_name": self.link.project_name,
            "relative_path": self.link.relative_path,
            "notice": self.notice,
        }


class _State:
    """Lo de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.offer: Offer | None = None


_STATE = _State()


def background() -> bool:
    """Si Blender no tiene interfaz (``blender -b``, guiones): entonces no se ofrece nada."""
    return bool(bpy.app.background)


def temp_dirs() -> tuple[Path, ...]:
    """Las carpetas temporales de Blender, donde están sus ficheros de recuperación y de
    autoguardado: la de las preferencias (si la hay), la base de ``bpy.app.tempdir`` (que es una
    subcarpeta ``blender_*`` de ella) y la del sistema."""
    found: list[Path] = []
    preferred = bpy.context.preferences.filepaths.temporary_directory
    if preferred:
        found.append(Path(bpy.path.abspath(preferred)))
    session_dir = bpy.app.tempdir
    if session_dir:
        found.append(Path(os.path.normpath(session_dir)).parent)
    found.append(Path(tempfile.gettempdir()))
    return tuple(found)


def _window() -> Any | None:
    """La ventana donde se ofrece: la primera de Blender; ninguna sin interfaz."""
    manager = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(manager, "windows", ()) or ())
    return windows[0] if windows else None


def _scene_link(scene: Any) -> ViewLink:
    props = scene.geoblender
    return ViewLink(props.project_uid, props.project_name, props.project_path)


def window_link(georefs: Sequence[SceneGeoref]) -> ViewLink | None:
    """El proyecto que se ofrece de entre los de ``georefs`` (los de las escenas del fichero,
    ``georef.file_georeferences``): el de la escena de la ventana si es uno de ellos; si no, el
    de la primera escena de uno de ellos (D-14). Su carpeta relativa sale de esa escena
    (``Scene.geoblender.project_path``: ``SceneGeoref`` no la lleva). ``None`` sin ninguno."""
    uids = {georef.uid for georef in georefs}
    if not uids:
        return None
    window = getattr(bpy.context, "window", None) or _window()
    scene = getattr(window, "scene", None)
    if scene is not None and scene.geoblender.project_uid in uids:
        return _scene_link(scene)
    for candidate in bpy.data.scenes:
        if candidate.geoblender.project_uid in uids:
            return _scene_link(candidate)
    return None


def offer_after_load(filepath: str | None, georefs: Sequence[SceneGeoref], *,
                     notice: str = "") -> bool:
    """Tras cargar ``filepath`` (el argumento de ``load_post``: el fichero que se leyó), vista de
    los proyectos ``georefs``, que no están abiertos: apunta la oferta del de la ventana
    (:func:`window_link`) y pone el temporizador de un disparo que abre su diálogo
    (:func:`offer_tick`); verdadero si lo hizo. No lo hace (y olvida la anterior) si no se
    ofrece (``core.views.locate.offer_refusal``) o si no hay ningún proyecto en ``georefs``. No
    lee nada del proyecto ni escribe nada."""
    withdraw()
    loaded = filepath if isinstance(filepath, str) and filepath else None
    refusal = offer_refusal(loaded, background=background(), temp_dirs=temp_dirs())
    if refusal is not None:
        LOGGER.debug("No se ofrece abrir el proyecto de la vista «%s»: %s", loaded, refusal)
        return False
    link = window_link(georefs)
    if link is None:
        return False
    _STATE.offer = Offer(loaded or bpy.data.filepath, link, notice)
    bpy.app.timers.register(offer_tick, first_interval=OFFER_DELAY_S, persistent=True)
    return True


def offer_tick() -> None:
    """El temporizador de un disparo de :func:`offer_after_load`: con la oferta y sin proyecto
    abierto, lanza su diálogo en la primera ventana (:func:`launch`); sin ventana, nada. Un
    fallo va al registro técnico (la oferta sigue en el panel Proyecto)."""
    offer = current_offer()
    window = _window()
    if offer is None or window is None:
        return None
    try:
        launch(window, offer)
    except Exception:  # noqa: BLE001 - un temporizador que falla no tumba la interfaz
        LOGGER.warning("No se pudo ofrecer abrir el proyecto «%s» de la vista",
                       offer.link.project_name, exc_info=True)
    return None


def launch(window: Any, offer: Offer) -> None:
    """La orden interna con el diálogo de ``offer`` (``INVOKE_DEFAULT``) en ``window``."""
    with bpy.context.temp_override(window=window):
        bpy.ops.geoblender.core_open_view_project("INVOKE_DEFAULT", **offer.properties())


def current_offer() -> Offer | None:
    """La oferta del fichero cargado, mientras no haya un proyecto abierto y alguna escena del
    fichero siga siendo de su proyecto (el botón del panel Proyecto, R3); si no, ``None``."""
    offer = _STATE.offer
    if offer is None or project_session.current() is not None:
        return None
    uid = offer.link.project_uid
    if not any(scene.geoblender.project_uid == uid for scene in bpy.data.scenes):
        return None
    return offer


def withdraw() -> None:
    """Olvida la oferta y retira su temporizador (al cargar otro fichero, al desregistrar)."""
    _STATE.offer = None
    if bpy.app.timers.is_registered(offer_tick):
        bpy.app.timers.unregister(offer_tick)


def location_text(link: ViewLink) -> str:
    """La pregunta del diálogo: «¿Abrir el proyecto «Cantera Norte» de esta vista? Está en
    «..\\» (relativa a la vista).» o, si la vista no guarda su carpeta, que se busca entre los
    recientes; en el idioma de Geoblender."""
    relative = link.relative_path
    if relative.startswith(BLEND_RELATIVE_PREFIX):
        shown = relative[len(BLEND_RELATIVE_PREFIX):].replace("/", os.sep) or f".{os.sep}"
        return tr("Open the project «{name}» of this view? It is in «{path}» (relative to the "
                  "view).", name=link.project_name, path=shown)
    return tr("Open the project «{name}» of this view? The view does not say where it is: it "
              "is looked for among the recent projects of this computer.",
              name=link.project_name)


def panel_text(offer: Offer) -> str:
    """Lo que dice el panel Proyecto sobre la oferta: «Esta vista es del proyecto «Cantera
    Norte», que no está abierto»."""
    return tr("This view is of the project «{name}», which is not open",
              name=offer.link.project_name)


def register() -> None:
    """Nada que registrar: la oferta se apunta al cargar un fichero (``georef``)."""
    withdraw()


def unregister() -> None:
    """Olvida la oferta y retira su temporizador."""
    withdraw()
