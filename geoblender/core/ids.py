# SPDX-License-Identifier: GPL-3.0-or-later
"""Identificadores de Geoblender (formato-proyecto §3.1: ``uid`` = UUID v4 en texto)."""

from __future__ import annotations

import uuid


def new_uid() -> str:
    """Un UUID v4 nuevo, en texto y en minúsculas."""
    return str(uuid.uuid4())
