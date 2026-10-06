# SPDX-License-Identifier: GPL-3.0-or-later
"""La carpeta de la documentación para las pruebas que comprueban el código contra ella
(spec 003: el catálogo de comandos frente a BS §8, al roadmap y al índice de specs).

La documentación no está en el repositorio de código (ADR-0023): es su carpeta madre o
la de ``GEOBLENDER_DOCS_DIR`` (``gbtools.repo.find_docs``, como ``tools/check_docs.py``).
Ninguna ruta se escribe en el código. Sin documentación, las pruebas que la necesitan se
omiten con el recurso ``docs`` (:data:`DOCS`, ``tests.support.resources``) y
``tools/check.py`` lo dice en su resumen.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

from tests.support import resources
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

from gbtools import repo  # noqa: E402

DOCS = "docs"  # el recurso de tests.support.resources
DOCS_HINT = (
    "ponga el repositorio de código dentro de la carpeta de la documentación o defina "
    "GEOBLENDER_DOCS_DIR con ella"
)
BS_RELPATH = "docs/arquitectura/interfaz/barra-superior.md"
ROADMAP_RELPATH = "docs/producto/roadmap.md"
SPECS_INDEX_RELPATH = "specs/README.md"


@functools.cache
def docs_dir() -> Path | None:
    """La carpeta de la documentación, o ``None`` si no hay (o no lo es)."""
    found = repo.find_docs(ROOT, os.environ)
    if found is None:
        return None
    try:
        return repo.docs_root(found)
    except repo.DocsProblem:
        return None


def docs_available() -> bool:
    return docs_dir() is not None


def read(relpath: str) -> str:
    """El texto de un documento de la documentación (``docs/…``, ``specs/…``)."""
    folder = docs_dir()
    if folder is None:
        raise FileNotFoundError("no hay carpeta de documentación: " + DOCS_HINT)
    return (folder / relpath).read_bytes().decode("utf-8")


def requires_docs(obj: object) -> object:
    """Decorador: omite la prueba o la clase si no hay documentación."""
    return resources.requires(DOCS, DOCS_HINT)(obj)


resources.register_resource(DOCS, docs_available)
