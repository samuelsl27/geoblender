# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera el ``.blend`` de la interfaz, ``resources/geoblender_ui.blend`` (spec 003, T14;
RF-003-02, RF-003-16; CW §6 y §7; PC §5.5).

Se ejecuta **dentro de Blender**, en segundo plano, de fábrica, con un perfil temporal y
``--python-exit-code 1``, desde la raíz del repositorio::

    $env:BLENDER_USER_RESOURCES = (New-Item -ItemType Directory -Force "$env:TEMP\\gb-perfil").FullName
    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" -b --factory-startup --python-exit-code 1 --python tools/inblender/make_ui_blend.py [-- --salida FICHERO]

Escribe (``bpy.data.libraries.write``) los espacios de trabajo de las disposiciones de la
003 de ``core/catalog/data/layouts.toml`` (entrada ``003``), todos con
``geoblender_mode = True``, y el «Layout» de fábrica de respaldo (sin marcar). Sustituye a
«diseñarlo a mano en la GUI» (adaptación autorizada por Samuel el 06/10/2026): así es
reproducible.

En segundo plano no se pueden unir ni cerrar áreas (``area_join`` divide y ``area_close``
no termina) ni se recalcula su geometría (``area.x``/``width`` de un área nueva valen 0
hasta que la interfaz gráfica la carga): por eso todas parten del espacio de fábrica
«Rendering» (Propiedades a la derecha, a toda altura, 339 px de 1920; un editor de imagen
de 1574 px encima de una línea de tiempo de 74 px) y solo se **dividen** áreas
(``area_split``, que en segundo plano sí cambia los vértices de la pantalla) y se cambia
su tipo:

- **Geoblender** (principal, CW §6.1): el editor de imagen se divide al 18 % (unos 280 px)
  en el Outliner, a la izquierda, y la Vista 3D (unos 1294 px) con la fila 2 y las
  barras T y N; Propiedades a la derecha; abajo, la línea de tiempo de fábrica (decisión
  revisable: sin interfaz no se puede quitar). Outliner como PC §5.5: «Capa de vista», sin
  contenido de objeto ni hijos, columnas «ocultar en la vista» y «seleccionable», orden
  alfabético.
- **Sección y planta**: la Vista 3D se divide por la mitad (dos de unos 650 px, cada una
  con su fila 2): planta ortográfica a la izquierda y sección mirando al norte a la
  derecha.
- **Datos**: la Vista 3D y, debajo (35 %), la Hoja de cálculo.
- **Diseño y perfil**: la Vista 3D con la barra N y, debajo (35 %), una segunda Vista 3D
  ortográfica mirando al norte (el perfil).
- **Fases**: la Vista 3D y, debajo (30 %), la hoja de claves con los marcadores.

El reparto se comprueba en la interfaz gráfica (verificación de la T14 en ``tasks.md``).
Un error sale con código 1 (``--python-exit-code 1``).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en el repositorio

import importlib  # noqa: E402
from pathlib import Path  # noqa: E402

import bpy  # noqa: E402
from bpy.props import BoolProperty  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from gbtools import layout as repo_layout  # noqa: E402
from gbtools.package import load_geoblender  # noqa: E402

WORKSPACE_PROPERTY = "geoblender_mode"  # la marca del modo (bl/props/ui.py)
OUTPUT_NAME = "geoblender_ui.blend"
FALLBACK = "Layout"  # el espacio de fábrica de respaldo, sin marcar (CW §3.2)
BASE = "Rendering"  # el espacio de fábrica del que parten todas
ENTRY = "003"  # las disposiciones de esta spec; las de otras entradas, con la suya
LEFT_FACTOR = 0.18  # Outliner: unos 280 de los 1574 px (CW §6.1)
# Rotaciones de la vista (cuaterniones w, x, y, z): planta (mirando hacia abajo, norte
# arriba) y mirando al norte (+Y, con +Z arriba) (spec §6.1).
PLAN = (1.0, 0.0, 0.0, 0.0)
NORTH = (0.7071067811865476, 0.7071067811865476, 0.0, 0.0)


def _option(argv: list[str], name: str) -> str | None:
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
        raise SystemExit(f"Error: falta el valor de {name}")
    return None


def _window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


def _only(workspace: bpy.types.WorkSpace, kind: str) -> bpy.types.Area:
    found = [area for area in workspace.screens[0].areas if area.type == kind]
    if len(found) != 1:
        raise RuntimeError(f"«{workspace.name}»: se esperaba un área {kind} y hay {len(found)}")
    return found[0]


def split(workspace: bpy.types.WorkSpace, area: bpy.types.Area, direction: str,
          factor: float) -> bpy.types.Area:
    """Divide ``area`` y devuelve el área nueva: con ``factor`` < 0,5, la parte pequeña
    (la izquierda en ``VERTICAL``, la de abajo en ``HORIZONTAL``)."""
    screen = workspace.screens[0]
    before = {item.as_pointer() for item in screen.areas}
    with bpy.context.temp_override(window=_window(), screen=screen, area=area):
        result = bpy.ops.screen.area_split(direction=direction, factor=factor)
    if result != {"FINISHED"}:
        raise RuntimeError(f"«{workspace.name}»: no se pudo dividir el área {area.type}")
    created = [item for item in screen.areas if item.as_pointer() not in before]
    if len(created) != 1:
        raise RuntimeError(f"«{workspace.name}»: la división no dio un área nueva")
    return created[0]


def _space(area: bpy.types.Area, kind: str) -> bpy.types.Space:
    """Cambia el tipo del área a ``kind`` y devuelve ese editor. El cambio se hace con el
    contexto de la ventana, la pantalla y el área: sin él, Blender en segundo plano no crea
    el editor nuevo de un área recién dividida."""
    with bpy.context.temp_override(window=_window(), screen=area.id_data, area=area):
        area.type = kind
    for space in area.spaces:
        if space.type == kind:
            return space
    raise RuntimeError(f"el área no tiene un editor {kind} tras cambiarle el tipo")


def configure_view(area: bpy.types.Area, *, sidebar: bool = False,
                   rotation: tuple[float, float, float, float] | None = None) -> None:
    """Una Vista 3D con la fila 1, la fila 2 (acceso rápido) y la barra T; la barra N si
    ``sidebar``; ortográfica con ``rotation`` si se da."""
    space = _space(area, "VIEW_3D")
    space.show_region_header = True
    space.show_region_tool_header = True
    space.show_region_toolbar = True
    space.show_region_ui = sidebar
    if rotation is not None and space.region_3d is not None:
        space.region_3d.view_perspective = "ORTHO"
        space.region_3d.view_rotation = rotation


def configure_outliner(area: bpy.types.Area) -> None:
    """El Outliner del espacio Geoblender (PC §5.5)."""
    space = _space(area, "OUTLINER")
    space.display_mode = "VIEW_LAYER"
    space.use_filter_object_content = False
    space.use_filter_children = False
    space.show_restrict_column_hide = True
    space.show_restrict_column_select = True
    space.use_sort_alpha = True


def columns(name: str) -> tuple[bpy.types.WorkSpace, bpy.types.Area]:
    """Outliner | Vista 3D | Propiedades, con la línea de tiempo abajo; devuelve el
    espacio y su Vista 3D."""
    workspace = bpy.data.workspaces[BASE].copy()
    workspace.name = name
    view = _only(workspace, "IMAGE_EDITOR")
    configure_outliner(split(workspace, view, "VERTICAL", LEFT_FACTOR))
    configure_view(view, sidebar=True, rotation=PLAN)
    _only(workspace, "DOPESHEET_EDITOR").ui_type = "TIMELINE"
    return workspace, view


def build_main(name: str) -> bpy.types.WorkSpace:
    return columns(name)[0]


def build_section_plan(name: str) -> bpy.types.WorkSpace:
    workspace, view = columns(name)
    configure_view(view, rotation=NORTH)  # la sección, a la derecha
    configure_view(split(workspace, view, "VERTICAL", 0.5), rotation=PLAN)
    return workspace


def build_data(name: str) -> bpy.types.WorkSpace:
    workspace, view = columns(name)
    _space(split(workspace, view, "HORIZONTAL", 0.35), "SPREADSHEET")
    return workspace


def build_design_profile(name: str) -> bpy.types.WorkSpace:
    workspace, view = columns(name)
    configure_view(split(workspace, view, "HORIZONTAL", 0.35), rotation=NORTH)
    return workspace


def build_phases(name: str) -> bpy.types.WorkSpace:
    workspace, view = columns(name)
    sheet = split(workspace, view, "HORIZONTAL", 0.3)
    _space(sheet, "DOPESHEET_EDITOR")
    sheet.ui_type = "DOPESHEET"
    return workspace


BUILDERS = {
    "MAIN": build_main,
    "SECTION_PLAN": build_section_plan,
    "DATA": build_data,
    "DESIGN_PROFILE": build_design_profile,
    "PHASES": build_phases,
}


def mark(workspace: bpy.types.WorkSpace, value: bool) -> None:
    """La marca del modo, sin escena fijada y en modo Objeto (CW §3.3)."""
    setattr(workspace, WORKSPACE_PROPERTY, value)
    workspace.use_pin_scene = False
    workspace.object_mode = "OBJECT"


def main() -> None:
    output = _option(sys.argv, "--salida")
    target = Path(output) if output else ROOT / repo_layout.RESOURCES_RELPATH / OUTPUT_NAME
    package = load_geoblender(ROOT)
    catalog = importlib.import_module(f"{package.__name__}.core.catalog").load()
    layouts = [layout for layout in catalog.layouts if layout.entry == ENTRY]
    missing = [layout.id for layout in layouts if layout.id not in BUILDERS]
    if missing:
        raise RuntimeError(f"disposiciones de la {ENTRY} sin construir: {', '.join(missing)}")
    # La marca, con el nombre de la extensión: el valor se guarda con él y la extensión lo
    # lee al registrar su propiedad.
    setattr(bpy.types.WorkSpace, WORKSPACE_PROPERTY, BoolProperty(default=False))
    try:
        built = []
        for layout in layouts:
            workspace = BUILDERS[layout.id](layout.workspace)
            mark(workspace, True)
            built.append(workspace)
        fallback = bpy.data.workspaces[FALLBACK]
        mark(fallback, False)
        built.append(fallback)
        target.parent.mkdir(parents=True, exist_ok=True)
        bpy.data.libraries.write(str(target), set(built), fake_user=True, compress=True)
    finally:
        delattr(bpy.types.WorkSpace, WORKSPACE_PROPERTY)
    names = ", ".join(workspace.name for workspace in built)
    print(f"Escrito «{target}» ({target.stat().st_size} bytes): {names}", flush=True)


if __name__ == "__main__":
    main()
