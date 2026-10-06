# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogos de comandos sintéticos para las pruebas del catálogo (spec 003, T02).

:data:`VALID` es un catálogo pequeño y válido con lo que tiene el real: dos menús de la
barra, grupos, un submenú definido en su sitio, otro cuyo contenido está en otro fichero,
accesos cruzados, un espejo (Datos ▾), comandos con propiedades, un comando nativo, sus
entradas y un atajo. Las pruebas de validación le añaden un error cada vez
(:func:`with_files`). :func:`big_catalog` genera uno válido del tamaño del real para medir
la carga.
"""

from __future__ import annotations

from collections.abc import Mapping

PROJECT = """\
[[menu]]
id = "GEOBLENDER_MT_ui_project"
label = {en = "Project", es = "Proyecto"}
description = {en = "Create or open the project", es = "Crear o abrir el proyecto"}
stage = {en = "Project", es = "Proyecto"}
step = 1
branch = "common"
icon = "gb_menu_project"
icon_fallback = "FILE_FOLDER"

[[menu.group]]
label = {en = "Project", es = "Proyecto"}

[[menu.group.item]]
key = "geoblender.core_new_project"
label = {en = "New project…", es = "Nuevo proyecto…"}
description = {en = "Create a project", es = "Crea un proyecto"}
entry = "002"
action = "D"
frequency = 1

[[menu.group.item]]
key = "GEOBLENDER_MT_core_network"
label = {en = "Local copy and network", es = "Copia local y red"}
description = {en = "Local working copy and network", es = "Copia local de trabajo y red"}
entry = "002"
action = "S"
frequency = 2

[[menu.group.item.item]]
key = "geoblender.core_checkout_project"
label = {en = "Work on a local copy…", es = "Trabajar en copia local…"}
description = {en = "Take a local copy", es = "Saca una copia local"}
entry = "002"
action = "D"
frequency = 2

[[menu.group]]
label = {en = "Exchange", es = "Intercambio"}

[[menu.group.item]]
key = "GEOBLENDER_MT_io_import"
label = {en = "Import", es = "Importar"}
description = {en = "Import a file into the project", es = "Importa un fichero al proyecto"}
entry = ""
action = "S"
frequency = 3

[[menu.group.item]]
separator = true

[[menu.group.item]]
key = "geoblender.ui_set_view?view=PLAN"
label = {en = "Plan", es = "Planta"}
description = {en = "Look down", es = "Mira hacia abajo"}
entry = "003"
action = "A"

[[menu.group.item]]
key = "geoblender.ui_set_view?view=NORTH"
label = {en = "Looking north", es = "Mirando al norte"}
description = {en = "Look north", es = "Mira al norte"}
entry = "003"
action = "A"

[[menu.group.item]]
key = "geoblender.geo_step_section?direction=-1&scope=SET"
label = {en = "Previous in the named set", es = "Anterior del conjunto con nombre"}
description = {en = "Previous section of the set", es = "Sección anterior del conjunto"}
entry = "R-38"
action = "A"

[[menu.group.item]]
key = "view3d.view_all"
label = {en = "Frame all", es = "Encuadrar todo"}
description = {en = "Show everything", es = "Muestra todo"}
entry = "Blender"
action = "A"
"""

TOPOGRAPHY = """\
[[menu]]
id = "GEOBLENDER_MT_ui_topography"
label = {en = "Topography", es = "Topografía"}
description = {en = "Surfaces", es = "Superficies"}
stage = {en = "Topography and GIS", es = "Topografía y SIG"}
step = 2
branch = "design"
icon = "gb_menu_topography"
icon_fallback = "WORLD"

[[menu.group]]
label = {en = "Analyze", es = "Analizar"}

[[menu.group.item]]
key = "geoblender.res_compute_volume_between_surfaces"
label = {en = "Volume between two surfaces…", es = "Cubicar entre dos superficies…"}
description = {en = "Volume between two surfaces", es = "Volumen entre dos superficies"}
entry = "R-38"
action = "D"
frequency = 3
aliases = ["cubicar", "volume"]
jargon = [["RecMin", "Volumen entre superficies"]]

[[menu.group.item]]
ref = "geoblender.core_new_project"

[[menu.group.item]]
ref = "GEOBLENDER_MT_io_import"
"""

IO_HUBS = """\
[[menu]]
id = "GEOBLENDER_MT_io_import"

[[menu.group]]
label = {en = "Detect", es = "Detectar"}

[[menu.group.item]]
key = "geoblender.gis_import_dtm"
label = {en = "Raster DTM…", es = "MDT ráster…"}
description = {en = "Import a raster DTM", es = "Importa un MDT ráster"}
entry = "006"
action = "D"
background = true

[[menu]]
id = "GEOBLENDER_MT_core_data"
label = {en = "Data", es = "Datos"}
description = {en = "Import, load, unload, export", es = "Importar, cargar, descargar, exportar"}
entry = "002"
action = "S"

[[menu.group]]

[[menu.group.item]]
mirror = "GEOBLENDER_MT_io_import"
"""

ENTRIES = """\
["002"]
title = {en = "Project and georeference", es = "Proyecto y georreferencia"}
delivered = true

["003"]
title = {en = "Geoblender interface", es = "Interfaz Geoblender"}
delivered = true

["006"]
title = {en = "Base topography", es = "Topografía base"}

["R-38"]
title = {en = "Volumetrics between surfaces", es = "Cubicación entre superficies"}

["Blender"]
title = {en = "Blender", es = "Blender"}
delivered = true
"""

SHORTCUTS = """\
[[shortcut]]
key = "geoblender.core_new_project"
keymap = "3D View"
event = "F5"
ctrl = true
"""

VALID: dict[str, str] = {
    "menus/01_project.toml": PROJECT,
    "menus/02_topography.toml": TOPOGRAPHY,
    "io_hubs.toml": IO_HUBS,
    "entries.toml": ENTRIES,
    "shortcuts.toml": SHORTCUTS,
}


def with_files(**changes: str) -> dict[str, str]:
    """:data:`VALID` con los ficheros de ``changes`` añadidos o sustituidos (las claves
    con ``__`` en lugar de ``/`` y sin ``.toml``: ``menus__01_project``)."""
    files = dict(VALID)
    for name, text in changes.items():
        files[name.replace("__", "/") + ".toml"] = text
    return files


def appended(name: str, text: str) -> dict[str, str]:
    """:data:`VALID` con ``text`` añadido al final del fichero ``name``."""
    files = dict(VALID)
    files[name] = files.get(name, "") + "\n" + text
    return files


def big_catalog(commands: int, menus: int = 13) -> Mapping[str, str]:
    """Un catálogo válido con ``commands`` operadores repartidos en ``menus`` menús de la
    barra, con textos del tamaño de los reales."""
    files: dict[str, str] = {"entries.toml": ENTRIES}
    per_menu = -(-commands // menus)
    made = 0
    for number in range(1, menus + 1):
        lines = [
            "[[menu]]",
            f'id = "GEOBLENDER_MT_ui_menu{number:02d}"',
            f'label = {{en = "Menu {number}", es = "Menú {number}"}}',
            f'description = {{en = "Stage {number} of the work", es = "Etapa {number} del trabajo"}}',
            f'stage = {{en = "Stage {number}", es = "Etapa {number}"}}',
            f"step = {number}",
            'branch = "design"',
            f'icon = "gb_menu_m{number}"',
            'icon_fallback = "WORLD"',
        ]
        for group in range(4):
            lines += ["", "[[menu.group]]",
                      f'label = {{en = "Group {number} {group}", es = "Grupo {number} {group}"}}']
            for _ in range(-(-per_menu // 4)):
                if made == commands:
                    break
                made += 1
                lines += [
                    "",
                    "[[menu.group.item]]",
                    f'key = "geoblender.res_compute_thing_{made:03d}"',
                    f'label = {{en = "Compute the thing number {made} between surfaces…", '
                    f'es = "Calcular la cosa número {made} entre superficies…"}}',
                    f'description = {{en = "Volume and tonnage of thing {made}, with its type '
                    f'and provenance", es = "Volumen y tonelaje de la cosa {made}, con su tipo '
                    'y su procedencia"}',
                    'entry = "R-38"',
                    'action = "D"',
                    "frequency = 2",
                    f'aliases = ["cosa{made}", "thing{made}"]',
                ]
        files[f"menus/{number:02d}_menu.toml"] = "\n".join(lines) + "\n"
    return files
