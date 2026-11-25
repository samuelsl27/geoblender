# SPDX-License-Identifier: GPL-3.0-or-later
"""Las áreas de la interfaz de Geoblender (spec 019, plan §5.1).

Por ahora solo la **revisión de la disposición** (T16; P-9): el entero que
``tools/inblender/make_ui_blend.py`` escribe en cada espacio de trabajo de Geoblender
(``WorkSpace["geoblender_layout_rev"]``) y que la extensión compara con el de un fichero
guardado (T18). Súbalo cuando cambie el reparto de áreas y regenere
``resources/geoblender_ui.blend``. El generador lee la línea ``LAYOUT_REV = n`` de este
fichero sin importarlo (HER-01: las herramientas no importan ``bl``).
"""

from __future__ import annotations

LAYOUT_REV = 2  # 1: la 003 (con línea de tiempo); 2: la 019 T16 (sin barra inferior, pestañas)
