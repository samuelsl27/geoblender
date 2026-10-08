# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de ``core`` (spec 008; plan 008 §5.1).

- ``core.original_copy_limit`` (RF-008-53; D-18 de la spec): el original de una entrada
  tabular o documental se guarda en el proyecto si sus ficheros no pasan juntos de este
  límite; por encima, aviso y «original no guardado». 200 MB (2·10⁸ B, MB decimales) por
  entrada; ADOPTADO de origen ``algorithm``, como todo parámetro técnico. El rango lo decide
  esta definición (la spec solo fija el valor por defecto): de 0 (no guardar ningún original)
  a 10 000 MB, que acota lo que crece el proyecto en la red.

Las registra ``bl/`` con ``core.params.register_definitions(DEFINITIONS)``.
"""

from __future__ import annotations

from .model import ParamDef

DEFINITIONS: tuple[ParamDef, ...] = (
    ParamDef("core.original_copy_limit", "float", "MB", 200.0, 0.0, 10_000.0,
             ("RF-008-53",), "Spec 008, D-18: 200 MB por entrada (todos sus ficheros)"),
)
"""Las definiciones de ``core``, en su orden."""
