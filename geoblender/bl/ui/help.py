# SPDX-License-Identifier: GPL-3.0-or-later
"""Ayuda de Geoblender (spec 003; RF-003-21, RF-003-27; BS §8.13; plan 003 DT12;
ADR-0019).

Todo se genera del **estado actual**, nunca a mano (AT §1, regla 8):

- Hojas (:func:`sheet`): la de atajos con los atajos registrados tal como están ahora
  (``keymap.current_shortcuts``: la combinación que tengan, sin los desactivados), la de
  alias de la línea de comandos y el glosario de términos de otros programas, con los
  textos en el idioma de Geoblender (``core.catalog.sheets``). :func:`draw_sheet` las
  dibuja en una ventana emergente, en columnas; :func:`write_sheet` escribe su versión
  imprimible, una página HTML, **solo** en la carpeta de datos de la extensión
  (``extension_path_user(ADDON_PACKAGE, path="help")``; nunca en el ``.blend``, plan 003
  DT12) y :func:`open_page` la abre en el navegador (con interfaz).
- Diagnóstico de la instalación (:func:`diagnostics`): versiones de Blender y de
  Geoblender, modo de la barra superior (normal, compatibilidad o sustituida por otro
  complemento después de Geoblender, spec §8), atajos registrados y en conflicto en el
  ámbito de la Vista 3D (``keymap.conflicts``), iconos cargados, idiomas, el estado del
  motor de cálculo del lanzador de la sesión y, si lo hay, su intérprete externo (spec 004,
  T41; :func:`engine_text`, :func:`external_interpreter`), y lo que aún no hay (PROJ) con
  su «Disponible en …».
- «Acerca de» (:func:`about`): versión, autor, licencias y la atribución de los datos de
  terceros de ``thirdparty/`` (ADR-0019), leída de su ``README.md``.

Los rótulos y valores salen de ``core.i18n.tr``; la atribución de terceros se muestra como
la escribe su origen.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import bpy

from ...core import catalog as core_catalog
from ...core.catalog import sheets
from ...core.i18n import language, tr
from ...core.version import geoblender_version
from ...jobs.runtime import ComputeEnvironment
from .. import ADDON_PACKAGE
from . import commands, icons, keymap, topbar
from . import jobs as job_list

HELP_FOLDER = "help"  # dentro de la carpeta de datos de la extensión
KINDS = ("shortcuts", "aliases", "glossary")
# Columnas que se ven en la ventana emergente (la página imprimible las lleva todas).
POPUP_COLUMNS: dict[str, tuple[int, ...]] = {
    "shortcuts": (0, 1),
    "aliases": (0, 1),
    "glossary": (0, 1, 2),
}
POPUP_ROWS = 25  # filas por columna en la ventana emergente
THIRDPARTY_DIR = Path(__file__).resolve().parents[2] / "thirdparty"
ATTRIBUTION_MARK = "**Atribución:**"


class _State:
    def __init__(self) -> None:
        self.last: Path | None = None  # la última página escrita


_STATE = _State()


# Hojas ---------------------------------------------------------------------------------


def shortcut_rows(lang: str | None = None) -> list[sheets.SheetRow]:
    """La hoja de atajos de los registrados, tal como están ahora."""
    return sheets.shortcut_rows(commands.catalog(), lang or language(),
                                keymap.current_shortcuts())


def sheet(kind: str, lang: str | None = None) -> tuple[str, tuple[str, ...],
                                                       list[sheets.SheetRow]]:
    """(título, cabeceras, filas) de una hoja: ``shortcuts``, ``aliases`` o
    ``glossary``."""
    lang = lang or language()
    cat = commands.catalog()
    if kind == "shortcuts":
        rows = shortcut_rows(lang)
    elif kind == "aliases":
        rows = sheets.alias_rows(cat, lang)
    else:
        rows = sheets.glossary_rows(cat, lang)
    return sheets.sheet_title(kind, lang), sheets.sheet_headers(kind, lang), rows


def help_folder() -> Path:
    """La carpeta de las páginas imprimibles (se crea si no existe)."""
    return Path(bpy.utils.extension_path_user(ADDON_PACKAGE, path=HELP_FOLDER, create=True))


def write_sheet(kind: str, lang: str | None = None) -> Path:
    """Escribe la página imprimible de una hoja y devuelve su ruta
    (``<datos>/help/<hoja>_<idioma>.html``)."""
    lang = lang or language()
    title, headers, rows = sheet(kind, lang)
    path = help_folder() / f"{kind}_{lang}.html"
    page = sheets.render_html(title, rows, headers=headers, language=lang)
    path.write_text(page, encoding="utf-8", newline="\n")
    _STATE.last = path
    return path


def last_written() -> Path | None:
    """La última página escrita en esta sesión."""
    return _STATE.last


def open_page(path: Path) -> bool:
    """Abre ``path`` en el navegador; sin interfaz, no abre nada y devuelve falso."""
    if bpy.app.background:
        return False
    bpy.ops.wm.url_open(url=path.as_uri())
    return True


def draw_sheet(layout: Any, kind: str) -> None:
    """Dibuja una hoja en una ventana emergente: el título y, en columnas de hasta
    :data:`POPUP_ROWS` filas, las columnas de :data:`POPUP_COLUMNS`."""
    title, headers, rows = sheet(kind)
    layout.label(text=title, icon="HELP", translate=False)
    shown = POPUP_COLUMNS[kind]
    chunks = [rows[start:start + POPUP_ROWS] for start in range(0, len(rows), POPUP_ROWS)]
    columns = layout.row()
    for chunk in chunks or [[]]:
        column = columns.column(align=True)
        head = column.row()
        head.active = False
        for index in shown:
            head.label(text=headers[index], translate=False)
        for row in chunk:
            line = column.row()
            for index in shown:
                line.label(text=row.columns[index], translate=False)


# Diagnóstico ---------------------------------------------------------------------------


def topbar_state() -> str:
    """Cómo está la barra superior: normal, compatibilidad, sustituida o sin instalar."""
    mode = topbar.mode()
    if mode == "patched":
        if topbar.is_installed():
            return tr("normal")
        return tr("replaced by another add-on (Help ▸ Repair the interface)")
    if mode == "compat":
        return tr("compatibility mode")
    return tr("not installed")


def conflicts_text() -> str:
    """Los atajos en conflicto («F10 · Object Mode · object.select_all»; …) o
    «ninguno»."""
    lang = language()
    found = keymap.conflicts()
    if not found:
        return tr("none")
    return "; ".join(f"{sheets.combination(shortcut, lang)} · {name} · {idname}"
                     for shortcut, name, idname in found)


def _available_in(entry: str) -> str:
    cat = commands.catalog()
    return tr("Available in {entry}", entry=core_catalog.entry_text(cat, entry, language()))


def _language_name(lang: str) -> str:
    return tr("Spanish") if lang == "es" else tr("English")


def _ops_jobs() -> ModuleType:
    """``bl.ops.jobs``, importado al usarlo: bl/ops importa bl/ui (ARQ-08)."""
    from ..ops import jobs as ops_jobs

    return ops_jobs


def engine_text() -> str:
    """El estado del motor de cálculo (spec 004, T41; RF-004-22), el del lanzador de la
    sesión (``bl.ops.jobs.session_runner``; sin lanzador, el del lock de esta versión,
    ``compute_environment``), como lo dice la lista de trabajos
    (``bl.ui.jobs.engine_state_text``): «No instalado», desactualizado, dañado o «Listo ·
    numpy … · BLAS … · 2000 × 2000 en … s» de su última verificación. Si el lock no se
    puede leer, lo dice. Solo lee: no crea ni comprueba nada."""
    ops = _ops_jobs()
    runner = ops.session_runner()
    env = runner.runtime if runner is not None else ops.compute_environment()
    if not isinstance(env, ComputeEnvironment):
        return tr("The compute engine lock of this version of Geoblender could not be read")
    return job_list.engine_state_text(env)


def external_interpreter() -> Path | None:
    """El intérprete externo con el que corren los trabajos del motor (spec 004, T41;
    RF-004-26): el del lanzador de la sesión o, sin lanzador, el de las preferencias;
    ``None`` si no hay ninguno."""
    ops = _ops_jobs()
    runner = ops.session_runner()
    return runner.external_python if runner is not None else ops.configured_external_python()


def diagnostics() -> list[tuple[str, str]]:
    """(rótulo, valor) del diagnóstico de la instalación, en el idioma de Geoblender."""
    view = bpy.context.preferences.view
    blender_language = view.language if view.use_translate_interface else "en_US"
    registered = len(keymap.current_shortcuts())
    total = len(commands.catalog().shortcuts())
    own_icons = len(commands.catalog().icons)
    loaded = icons.loaded_count()
    icon_text = (tr("{n} of {total} loaded ({size} px)", n=loaded, total=own_icons,
                    size=icons.loaded_size()) if loaded
                 else tr("{n} of {total} loaded", n=0, total=own_icons))
    build = bpy.app.build_hash.decode("ascii", "replace") if bpy.app.build_hash else ""
    external = external_interpreter()
    return [
        ("Blender", f"{bpy.app.version_string} ({build})" if build else bpy.app.version_string),
        (tr("Extension"), f"{geoblender_version()} · {ADDON_PACKAGE}"),
        ("Python", sys.version.split()[0]),
        (tr("Top bar"), topbar_state()),
        (tr("Shortcuts"), tr("{n} of {total} registered", n=registered, total=total)),
        (tr("Conflicting shortcuts"), conflicts_text()),
        (tr("Icons"), icon_text),
        (tr("Geoblender language"), _language_name(language())),
        (tr("Blender language"), blender_language),
        (tr("Compute engine"), engine_text()),
        *([(tr("External interpreter"), str(external))] if external is not None else []),
        ("PROJ", _available_in("006")),
    ]


def diagnostics_text() -> str:
    """El diagnóstico como texto, una línea por rótulo (para copiarlo)."""
    return "\n".join(f"{label}: {value}" for label, value in diagnostics())


# Acerca de -----------------------------------------------------------------------------


def attributions(folder: Path = THIRDPARTY_DIR) -> list[str]:
    """La atribución de cada carpeta de datos de terceros (la línea «Atribución» de su
    ``README.md``), en orden."""
    found: list[str] = []
    for readme in sorted(folder.glob("*/README.md")):
        for line in readme.read_text(encoding="utf-8").splitlines():
            if ATTRIBUTION_MARK in line:
                found.append(line.split(ATTRIBUTION_MARK, 1)[1].strip())
                break
    return found


def about() -> list[tuple[str, str]]:
    """(rótulo, valor) de «Acerca de Geoblender»."""
    rows = [
        ("Geoblender", tr("Version {version}", version=geoblender_version())),
        (tr("Author"), "IMGA"),
        (tr("Licence"), tr("Code GPL-3.0-or-later; icons, images and layouts CC0-1.0")),
        ("Blender", bpy.app.version_string),
    ]
    rows += [(tr("Third-party data"), text) for text in attributions()]
    return rows


def draw_rows(layout: Any, title: str, rows: Sequence[tuple[str, str]]) -> None:
    """Dibuja (rótulo, valor) en dos columnas bajo ``title``."""
    layout.label(text=title, icon="INFO", translate=False)
    column = layout.column(align=True)
    for label, value in rows:
        split = column.split(factor=0.3)
        left = split.row()
        left.active = False
        left.label(text=label, translate=False)
        split.label(text=value, translate=False)


def clear() -> None:
    """Olvida la última página escrita (al desregistrar)."""
    _STATE.last = None
