# SPDX-License-Identifier: GPL-3.0-or-later
"""El árbol del repositorio de código, en un solo sitio (plan 007 §5.2 y §5.4.1).

Nombres de la carpeta de la extensión y de lo que cuelga de ella (manifiesto, ruedas,
recursos, terceros), marcadores de la raíz, entradas permitidas en la raíz, la carpeta
del código dentro de la documentación, las variables de entorno y las exclusiones del
espejo. Las herramientas de ``tools/`` y todas las pruebas toman de aquí las rutas: un
renombrado es una línea, y ``tests/unit/tools/test_layout.py`` vigila que no quede
ningún literal de la carpeta de la extensión fuera de este módulo (RF-007-06,
RF-007-07).

``EXTENSION_DIR`` (la extensión dentro del código) y ``CODE_DIR_IN_DOCS`` (el código
dentro de la documentación) son cosas distintas aunque se escriban igual sin
mayúsculas.
"""

from __future__ import annotations

# La carpeta de la extensión en la raíz del repositorio de código (se llama como el id;
# «Geoblender» hasta la tarea 007/T07, que la renombró).
EXTENSION_DIR = "geoblender"
MANIFEST_RELPATH = f"{EXTENSION_DIR}/blender_manifest.toml"
WHEELS_DIR_RELPATH = f"{EXTENSION_DIR}/wheels"
RESOURCES_RELPATH = f"{EXTENSION_DIR}/resources"
THIRDPARTY_RELPATH = f"{EXTENSION_DIR}/thirdparty"
# Carpetas de activos cuyo LICENSE es una copia de LICENSES/CC0-1.0.txt (plan 001 §5.2).
ASSET_ROOTS: tuple[str, ...] = (
    "assets/",
    f"{RESOURCES_RELPATH}/",
    "packaging/app_template/",
)

# La raíz del repositorio de código es la primera carpeta con los dos (RF-007-06): no
# depende de ningún fichero de la documentación.
CHECK_RELPATH = "tools/check.py"
ROOT_MARKERS: tuple[str, ...] = (MANIFEST_RELPATH, CHECK_RELPATH)

# REP-01: las únicas entradas de la raíz del repositorio de código (con su mayúscula).
CODE_ROOT_ENTRIES: frozenset[str] = frozenset(
    {
        EXTENSION_DIR, "tests", "tools", "assets", "packaging", "LICENSE", "LICENSES",
        "REUSE.toml", "README.md", "CHANGELOG.md", "AGENTS.md", "CLAUDE.md",
        ".gitattributes", ".gitignore", ".editorconfig",
    }
)
CODE_AGENTS_MAX_LINES = 60  # AGT-03: el AGENTS.md mínimo del código

# La documentación: su marcador, el repositorio de código dentro de ella y lo que su
# comprobación no recorre (en su raíz).
DOCS_MARKER = "docs/constitution.md"
CODE_DIR_IN_DOCS = "Geoblender"
DOCS_EXCLUDED: tuple[str, ...] = (".git", "Documentacion", "Promts", CODE_DIR_IN_DOCS)

ENV_DOCS_DIR = "GEOBLENDER_DOCS_DIR"
ENV_NAS_MIRROR = "GEOBLENDER_NAS_ESPEJO"

# Lo que el espejo no copia ni borra (sintaxis de gbtools.ignore); dist y .deps,
# anclados a la raíz de cada repositorio (D-17).
MIRROR_EXCLUDED: tuple[str, ...] = (
    "/dist/",
    "/.deps/",
    f"/{CODE_DIR_IN_DOCS}/dist/",
    f"/{CODE_DIR_IN_DOCS}/.deps/",
    "__pycache__/",
    "*.pyc",
    "*.blend[0-9]",
    "*.blend[0-9][0-9]",
    "~$*",
    ".~lock.*#",
    "Thumbs.db",
    "desktop.ini",
)
MIRROR_TEMP_SUFFIX = ".gb-espejo~"  # temporal de cada copia en el destino (§5.4.8)
MIRROR_STATE_PARTS: tuple[str, ...] = ("Geoblender", "espejo")  # bajo %LOCALAPPDATA%
