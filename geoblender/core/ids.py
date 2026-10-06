# SPDX-License-Identifier: GPL-3.0-or-later
"""Identificadores de Geoblender (formato-proyecto §3.1: ``uid`` = UUID v4 en texto)."""

from __future__ import annotations

import uuid


SHORT_UID_CHARS = 8


def new_uid() -> str:
    """Un UUID v4 nuevo, en texto y en minúsculas."""
    return str(uuid.uuid4())


def short_uid() -> str:
    """8 cifras hexadecimales al azar (de un UUID v4), para los nombres de las carpetas y
    los ficheros temporales: cada carácter cuenta con el límite de rutas de Windows (spec
    002, convergencia, T45). Quien lo usa para un nombre nuevo reintenta con otro si ya
    existe."""
    return uuid.uuid4().hex[:SHORT_UID_CHARS]
