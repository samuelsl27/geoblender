# SPDX-License-Identifier: GPL-3.0-or-later
"""La versión de Geoblender (spec 002; RF-002-04; plan 002 §5.1).

La fuente única es ``version`` de ``blender_manifest.toml`` (convenciones §3), que está
junto al paquete raíz también en la extensión instalada: el cerrojo, la cabecera y
``gb_project`` firman con ella cada sesión. Nunca se escribe a mano en otro sitio.
"""

from __future__ import annotations

import functools
import tomllib
from pathlib import Path

from .errors import GeoblenderError

MANIFEST_FILE = "blender_manifest.toml"


def manifest_path() -> Path:
    """``<paquete raíz>/blender_manifest.toml``."""
    return Path(__file__).resolve().parent.parent / MANIFEST_FILE


@functools.cache
def geoblender_version() -> str:
    """La versión de esta Geoblender (SemVer, p. ej. ``"0.1.0"``), leída una vez del
    manifiesto. :class:`GeoblenderError` si no se puede leer."""
    path = manifest_path()
    try:
        value = tomllib.loads(path.read_bytes().decode("utf-8")).get("version")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise GeoblenderError(
            "core.version_unreadable",
            f"no se puede leer ({exc}); reinstale Geoblender",
            obj="Geoblender",
            field=MANIFEST_FILE,
            value=str(path),
        ) from exc
    if not isinstance(value, str) or not value:
        raise GeoblenderError(
            "core.version_missing",
            "el manifiesto no tiene «version»; reinstale Geoblender",
            obj="Geoblender",
            field="version",
            value=value,
        )
    return value
