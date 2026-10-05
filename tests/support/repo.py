# SPDX-License-Identifier: GPL-3.0-or-later
"""Rutas del repositorio para las pruebas.

``ROOT`` se calcula desde este fichero, no desde la carpeta de trabajo: las pruebas dan el
mismo resultado se lancen desde donde se lancen.

Los árboles temporales de las pruebas de ruedas, empaquetado e instalación usan
``EMPTY_WHEELS_TOML`` y :func:`manifest_without_wheels`, no el ``tools/wheels.toml`` ni la
lista ``wheels`` reales: así no dependen de las ruedas que fije cada spec (la primera, la
006), y un incumplimiento de LIC-01 en el real lo señalan solo las pruebas del árbol
real (convergencia de la spec 001, T45).
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT: Path = Path(__file__).resolve().parents[2]
TOOLS_DIR: Path = ROOT / "tools"

EMPTY_WHEELS_TOML = "schema_version = 1\n"


def tools_on_path() -> None:
    """Pone ``tools/`` al principio de ``sys.path`` para importar ``gbtools`` (idempotente)."""
    entry = str(TOOLS_DIR)
    if entry not in sys.path:
        sys.path.insert(0, entry)


tools_on_path()

from gbtools import layout  # noqa: E402

# El nombre de la carpeta de la extensión, de ``gbtools.layout`` (spec 007): los árboles
# temporales escriben ``f"{EXT}/core/__init__.py"``, nunca el nombre a mano.
EXT: str = layout.EXTENSION_DIR
EXTENSION_DIR: Path = ROOT / EXT


def _real_manifest_text() -> str:
    """El texto del manifiesto real, sin BOM si lo tiene: un BOM lo señalan TXT-01, MAN-01,
    las pruebas del manifiesto real y el paso «manifiesto», no las pruebas que solo
    necesitan sus datos (convergencia de la spec 001, T56)."""
    tools_on_path()
    from gbtools import manifest

    return (ROOT / manifest.MANIFEST_RELPATH).read_bytes().decode("utf-8-sig")


def manifest_without_wheels() -> str:
    """El texto del manifiesto real con ``wheels = []`` (lo demás, igual; sin BOM).

    Se llama al usarlo, nunca al importar un módulo de pruebas: con un manifiesto
    ilegible fallan las pruebas que lo usan y no la importación del módulo (T56)."""
    tools_on_path()
    from gbtools import manifest

    return manifest.with_wheels(_real_manifest_text(), [])


def real_manifest() -> dict[str, Any]:
    """Los datos del manifiesto real (sin BOM), para las pruebas que solo los leen; al
    usarlos, nunca al importar el módulo (T56)."""
    return tomllib.loads(_real_manifest_text())
