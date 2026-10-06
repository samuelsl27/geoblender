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

Coordenadas: ninguna absoluta; las vistas trabajan en las locales de la escena.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Quaternion, Vector

_S3 = 1.0 / math.sqrt(3.0)
UP_Z = (0.0, 0.0, 1.0)

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
    """Pone el manejador que olvida el estado de sesión al abrir un fichero."""
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)


def unregister() -> None:
    """Quita el manejador y olvida el estado de sesión."""
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
