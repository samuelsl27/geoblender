# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera el proyecto del esquema 2 de prueba, ``tests/data/core/projects/esquema2.zip`` (spec
009, T03; plan 009 §7.1).

El generador es ``tests/support/schema2_project.py`` (``generate``), que no importa los módulos de
Blender (ARQ-01): este guion se ejecuta dentro de Blender, en segundo plano, con un perfil
temporal y desde la raíz del repositorio de código, y solo le da ``bpy``::

    $env:BLENDER_USER_RESOURCES = (New-Item -ItemType Directory -Force "$env:TEMP\\gb-perfil-s2").FullName
    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" -b --factory-startup `
        --python-exit-code 1 --python tools/inblender/schema2_project.py -- [--salida ZIP]

Con el código de partida de la 009 (el esquema 2); con uno posterior se niega. Sin ``--salida``,
escribe ``tests/data/core/projects/esquema2.zip`` y dice su tamaño y su sha256, que se anotan en
el docstring del generador y en el README de su carpeta.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":  # como guion: sin __pycache__ en el repositorio
    sys.dont_write_bytecode = True

from pathlib import Path  # noqa: E402

import bpy  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(ROOT / "tools"), str(ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from tests.support import schema2_project  # noqa: E402

if __name__ == "__main__":
    sys.exit(schema2_project.generate(bpy, sys.argv))
