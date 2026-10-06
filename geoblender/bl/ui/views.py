# SPDX-License-Identifier: GPL-3.0-or-later
"""Vista 3D de destino y vistas mineras (spec 003; RF-003-12; spec §6.1 y §7; BS §8.12;
AR §3.1 y §4).

- **Vista 3D de destino** (:func:`target_view3d`, spec §7): la Vista 3D desde la que se
  lanza el comando; desde la barra superior o un menú (sin área de Vista 3D), la última de
  la ventana en la que se usó un comando de vista de Geoblender (:func:`mark_used`) o, si
  no hay, la mayor. Los operadores ``view3d.*`` no hacen falta: se escribe directamente en
  la ``RegionView3D`` de destino. El estado («última usada», por ventana) es de la sesión
  (plan 003 DT5): no se guarda en el ``.blend`` y se olvida al abrir otro fichero (su
  manejador ``load_post``, que :func:`register` pone y :func:`unregister` quita).
- **Vistas mineras** (:data:`MINING_VIEWS`, :func:`set_view`; RF-003-12): planta, mirando
  al norte, al sur, al este y al oeste, e isométricas desde cada esquina (el observador en
  la esquina), en ortográfica, con la dirección de mirada de spec §6.1 y su «arriba en
  pantalla» (norte en planta, +Z en las laterales, la proyección de +Z en las isométricas;
  plan 003 §5.4, 7): ``back = −d``, ``right = up × back`` y ``view_rotation`` = la matriz
  de columnas (right, up, back). La posición y la distancia de la vista no cambian.
- **Encuadrar la ventana de trabajo** (:func:`frame_work_window`; RF-003-13; plan 003
  §5.4, 9; Silvestre N-07): la ventana de trabajo del proyecto abierto (absoluta, de la
  002) pasa a locales con ``core.georef.world_to_local``; sus cotas son las de los objetos
  visibles con geometría que la cortan en planta (sin ninguno, el cursor 3D ± 50 m). La
  vista se centra en la caja, con la distancia que la deja entera en la región (esfera
  que la contiene, 5 % de margen, en el lado menor de la región, con la proyección de una
  Vista 3D de Blender: ``bl.compat.VIEW_SENSOR_MM`` y ``VIEW_ZOOM``), y los planos de
  recorte del editor se ajustan para que no recorten nada de ella: ``clip_end`` ≥ 2 ·
  (distancia + 2 r) (en ortográfica Blender recorta de −clip_end/2 a clip_end/2 desde el
  ojo) y ``clip_start`` = máx(0,01; clip_end / 10⁵), una relación ≤ 10⁵ que no agota el
  búfer de profundidad (:func:`clip_range`). Sin proyecto o sin ventana, no aplica.
- **Vistas guardadas** (:func:`store_view`, :func:`recall_view`; RF-003-14): la ranura 1–4
  de ``Scene.geoblender_views`` con la orientación, el centro (local), la distancia y la
  proyección. Recuperar una ranura vacía no aplica (:func:`recall_check`, registrada con
  ``commands.register_check``: el menú la dibuja desactivada y su descripción dice cómo
  guardarla).

Coordenadas: ninguna absoluta en Blender; las vistas trabajan en las locales de la escena
(la ventana de trabajo se convierte con la función única del núcleo, en float64).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import bpy
import numpy as np
from bpy.app.handlers import persistent
from mathutils import Matrix, Quaternion, Vector

from ...core.catalog.search import path_text
from ...core.catalog.sheets import combination
from ...core.georef import world_to_local
from ...core.i18n import language, tr
from .. import compat
from ..props.ui import VIEWS_PROPERTY
from ..scene import project_session
from . import commands

_S3 = 1.0 / math.sqrt(3.0)
UP_Z = (0.0, 0.0, 1.0)
FRAME_MARGIN = 1.05  # 5 % de margen al encuadrar
EMPTY_Z_HALF_M = 50.0  # sin nada visible en la ventana: cursor ± 50 m
CLIP_RATIO_MAX = 1e5  # clip_end / clip_start (búfer de profundidad)
CLIP_START_MIN_M = 0.01
GEOMETRY_TYPES = frozenset({"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES",
                            "POINTCLOUD", "VOLUME", "GREASEPENCIL"})
WORK_WINDOW_COMMAND = "geoblender.core_set_work_window"
STORE_VIEW = "geoblender.ui_store_view"
RECALL_VIEW = "geoblender.ui_recall_view"

# Spec §6.1: vista → (dirección de mirada (X = Este, Y = Norte, Z = cota), arriba en
# pantalla; None = la proyección de +Z).
MINING_VIEWS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float] | None]] = {
    "PLAN": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "NORTH": ((0.0, 1.0, 0.0), UP_Z),
    "SOUTH": ((0.0, -1.0, 0.0), UP_Z),
    "EAST": ((1.0, 0.0, 0.0), UP_Z),
    "WEST": ((-1.0, 0.0, 0.0), UP_Z),
    "ISO_NE": ((-_S3, -_S3, -_S3), None),
    "ISO_NW": ((_S3, -_S3, -_S3), None),
    "ISO_SE": ((-_S3, _S3, -_S3), None),
    "ISO_SW": ((_S3, _S3, -_S3), None),
}


@dataclass(frozen=True)
class View3DTarget:
    """Una Vista 3D de destino: su ventana, su área, su región principal, su
    ``RegionView3D`` y su editor (``SpaceView3D``)."""

    window: Any
    area: Any
    region: Any
    rv3d: Any
    space: Any


class _State:
    def __init__(self) -> None:
        self.last: dict[int, int] = {}  # ventana → área de la última Vista 3D usada


_STATE = _State()


def _pointer(value: Any) -> int:
    pointer = getattr(value, "as_pointer", None)
    return int(pointer()) if callable(pointer) else id(value)


def _main_region(area: Any) -> Any:
    return next((region for region in area.regions if region.type == "WINDOW"), None)


def _target(window: Any, area: Any, region: Any = None, rv3d: Any = None) -> View3DTarget | None:
    space = area.spaces.active
    region = region if getattr(region, "type", "") == "WINDOW" else _main_region(area)
    rv3d = rv3d if rv3d is not None else getattr(space, "region_3d", None)
    if region is None or rv3d is None:
        return None
    return View3DTarget(window, area, region, rv3d, space)


def target_view3d(context: Any) -> View3DTarget | None:
    """La Vista 3D de destino de un comando lanzado en ``context`` (spec §7), o ``None``
    si la ventana no tiene ninguna."""
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    if area is not None and getattr(area, "type", "") == "VIEW_3D":
        region_data = getattr(context, "region_data", None)
        rv3d = region_data if isinstance(region_data, bpy.types.RegionView3D) else None
        return _target(window, area, getattr(context, "region", None), rv3d)
    screen = getattr(window, "screen", None) or getattr(context, "screen", None)
    areas = [a for a in getattr(screen, "areas", ()) if a.type == "VIEW_3D"]
    if not areas:
        return None
    last = _STATE.last.get(_pointer(window))
    chosen = next((a for a in areas if _pointer(a) == last), None)
    if chosen is None:
        chosen = max(areas, key=lambda a: a.width * a.height)
    return _target(window, chosen)


def mark_used(target: View3DTarget) -> None:
    """Anota ``target`` como la última Vista 3D usada de su ventana."""
    _STATE.last[_pointer(target.window)] = _pointer(target.area)


def forget() -> None:
    """Olvida las Vistas 3D usadas (al cargar otro fichero o al desregistrar)."""
    _STATE.last.clear()


@persistent
def on_load_post(*_args: Any) -> None:
    """Al abrir otro fichero se pierde el estado de sesión de las vistas."""
    forget()


def register() -> None:
    """Pone el manejador que olvida el estado de sesión al abrir un fichero y la
    comprobación de las ranuras vacías."""
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    commands.register_check(RECALL_VIEW, recall_check)


def unregister() -> None:
    """Quita el manejador y la comprobación y olvida el estado de sesión."""
    commands.unregister_check(RECALL_VIEW)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    forget()


def view_rotation(look: tuple[float, float, float],
                  up: tuple[float, float, float] | None) -> Quaternion:
    """La rotación de la vista que mira hacia ``look`` con ``up`` arriba en pantalla (con
    ``None``, la proyección de +Z sobre el plano de la pantalla)."""
    d = Vector(look).normalized()
    u = Vector(UP_Z if up is None else up)
    u = (u - u.dot(d) * d).normalized()
    back = -d
    right = u.cross(back)
    return Matrix((right, u, back)).transposed().to_quaternion()


def set_view(target: View3DTarget, view: str) -> None:
    """Pone la Vista 3D de destino en la vista minera ``view`` (RF-003-12), en
    ortográfica."""
    look, up = MINING_VIEWS[view]
    rv3d = target.rv3d
    rv3d.view_rotation = view_rotation(look, up)
    rv3d.view_perspective = "ORTHO"
    target.area.tag_redraw()
    mark_used(target)


# Encuadrar la ventana de trabajo (RF-003-13) -------------------------------------------------


def work_window_local() -> tuple[float, float, float, float] | None:
    """La ventana de trabajo del proyecto abierto en coordenadas locales (xmin, ymin, xmax,
    ymax), o ``None`` sin proyecto o sin ventana."""
    project = project_session.current()
    window = getattr(project, "window", None)
    if project is None or window is None:
        return None
    origin = project.origin
    corners = np.array([[window.xmin, window.ymin, origin.z0],
                        [window.xmax, window.ymax, origin.z0]], dtype=np.float64)
    local = world_to_local(corners, origin)
    return (float(local[0, 0]), float(local[0, 1]), float(local[1, 0]), float(local[1, 1]))


def no_work_window_message() -> str:
    """«Primero defina la ventana de trabajo (<su ruta en la barra>)» (spec §8)."""
    path = path_text(commands.catalog(), WORK_WINDOW_COMMAND, language())
    return tr("First {step} ({path})", step=tr("define the work window"), path=path)


def visible_z_range(context: Any, xy: tuple[float, float, float, float]
                    ) -> tuple[float, float] | None:
    """Las cotas (mín., máx.) de los objetos visibles con geometría que cortan en planta
    el rectángulo ``xy`` (locales), o ``None`` si no hay ninguno."""
    x0, y0, x1, y1 = xy
    view_layer = getattr(context, "view_layer", None) or bpy.context.view_layer
    low, high = math.inf, -math.inf
    for obj in view_layer.objects:
        if obj.type not in GEOMETRY_TYPES or not obj.visible_get(view_layer=view_layer):
            continue
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
            continue
        low = min(low, *(c.z for c in corners))
        high = max(high, *(c.z for c in corners))
    return (low, high) if low <= high else None


def frame_distance(radius: float, *, ortho: bool, lens: float, width: float,
                   height: float) -> float:
    """La distancia de la vista que deja entera una esfera de radio ``radius`` (con el
    margen) en una región de ``width`` × ``height`` px: el lado mayor ve
    ``sensor / lens × zoom / 2`` (la tangente del semiángulo o, en ortográfica, el
    semiancho por unidad de distancia), y el menor, eso por la relación de aspecto."""
    factor = compat.VIEW_SENSOR_MM / lens * compat.VIEW_ZOOM / 2.0
    aspect = min(width, height) / max(width, height) if width > 0 and height > 0 else 1.0
    if ortho:
        return FRAME_MARGIN * radius / (factor * aspect)
    return FRAME_MARGIN * radius / math.sin(math.atan(factor * aspect))


def clip_range(current_end: float, distance: float, radius: float) -> tuple[float, float]:
    """(clip_start, clip_end) que no recortan una esfera de radio ``radius`` a
    ``distance`` del ojo, en perspectiva y en ortográfica, con clip_end / clip_start ≤
    10⁵: se conserva un clip_end mayor si no obliga a acercar tanto el cercano que
    recorte la caja."""
    needed = 2.0 * (distance + 2.0 * radius)
    end = max(current_end, needed)
    start = max(CLIP_START_MIN_M, end / CLIP_RATIO_MAX)
    if start > 0.5 * (distance - radius):
        end = needed
        start = max(CLIP_START_MIN_M, end / CLIP_RATIO_MAX)
    return start, end


def frame_work_window(target: View3DTarget, context: Any) -> bool:
    """Encuadra en la Vista 3D de destino la ventana de trabajo con las cotas de lo
    visible en ella y ajusta su recorte (RF-003-13); falso sin ventana de trabajo."""
    xy = work_window_local()
    if xy is None:
        return False
    z = visible_z_range(context, xy)
    if z is None:
        scene = getattr(context, "scene", None) or bpy.context.scene
        cursor_z = float(scene.cursor.location.z)
        z = (cursor_z - EMPTY_Z_HALF_M, cursor_z + EMPTY_Z_HALF_M)
    low = Vector((xy[0], xy[1], z[0]))
    high = Vector((xy[2], xy[3], z[1]))
    centre = (low + high) / 2.0
    radius = (high - low).length / 2.0
    rv3d, space, region = target.rv3d, target.space, target.region
    if rv3d.view_perspective == "CAMERA":
        rv3d.view_perspective = "PERSP"
    distance = frame_distance(radius, ortho=rv3d.view_perspective == "ORTHO",
                              lens=space.lens, width=region.width, height=region.height)
    rv3d.view_location = centre
    rv3d.view_distance = distance
    start, end = clip_range(space.clip_end, distance, radius)
    space.clip_end = end
    space.clip_start = start
    target.area.tag_redraw()
    mark_used(target)
    return True


# Vistas guardadas (RF-003-14) ---------------------------------------------------------------


def saved_view(scene: Any, slot: int) -> Any:
    """La vista guardada en la ranura ``slot`` de la escena, o ``None``."""
    for item in getattr(scene, VIEWS_PROPERTY, ()):
        if item.slot == slot:
            return item
    return None


def store_view(target: View3DTarget, scene: Any, slot: int) -> None:
    """Guarda en la ranura ``slot`` la orientación, el centro (local), la distancia y la
    proyección de la Vista 3D de destino."""
    item = saved_view(scene, slot)
    if item is None:
        item = getattr(scene, VIEWS_PROPERTY).add()
        item.slot = slot
    rv3d = target.rv3d
    item.view_location_local = rv3d.view_location
    item.view_rotation = rv3d.view_rotation
    item.view_distance = rv3d.view_distance
    item.view_perspective = "ORTHO" if rv3d.view_perspective == "ORTHO" else "PERSP"
    mark_used(target)


def recall_view(target: View3DTarget, scene: Any, slot: int) -> bool:
    """Restaura en la Vista 3D de destino la vista de la ranura ``slot``; falso si está
    vacía."""
    item = saved_view(scene, slot)
    if item is None:
        return False
    rv3d = target.rv3d
    rv3d.view_location = item.view_location_local
    rv3d.view_rotation = Quaternion(item.view_rotation).normalized()
    rv3d.view_distance = item.view_distance
    rv3d.view_perspective = item.view_perspective
    target.area.tag_redraw()
    mark_used(target)
    return True


def empty_slot_message(slot: int) -> str:
    """«Guarde antes la vista n (Ctrl+Mayús+F…)» (spec §8), con el atajo de esa ranura."""
    cat = commands.catalog()
    found = cat.shortcuts_for(f"{STORE_VIEW}?slot={slot}")
    shortcut = combination(found[0], language()) if found else ""
    return tr("Save view {n} first ({shortcut})", n=slot, shortcut=shortcut)


def recall_check(context: Any, cmd: Any) -> str:
    """«No aplicable ahora» de Recuperar vista ▸ n: la ranura está vacía."""
    slot = dict(cmd.props).get("slot")
    if not isinstance(slot, int):
        return ""
    scene = getattr(context, "scene", None) or bpy.context.scene
    return "" if saved_view(scene, slot) is not None else empty_slot_message(slot)
