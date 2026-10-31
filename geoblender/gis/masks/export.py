# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar la rejilla de clases de las restricciones (spec 012, T20; RF-012-20; plan 012 §5.3.4,
D-25 y D-29 de la 011).

Exportar **no es una operación** (D-29 de la 011): el entregable se escribe desde lo registrado,
también con el proyecto en solo lectura (si el destino está fuera de él) y desde una versión que
ya no es editable; nada se registra. Las máscaras tienen que estar al día
(:func:`~.access.mask_state`): sin compilar u obsoletas se rechazan con lo mismo que los
operadores (``core.constraint_masks_missing``, ``core.constraint_masks_stale``), porque un
entregable con clases viejas llevaría a diseñar sobre lo que ya no es.

**La rejilla de clases** (:func:`export_classes_steps`, :func:`export_classes`; RF-006-24): la
registrada (``rasters/gis_msk_<vNN>.tif``, Float64) como GeoTIFF del perfil ``deliverable`` de la
006 (Float32, sin dato −9999, el CRS y la referencia vertical del proyecto; los códigos, de a lo
sumo 2047, son exactos en float32) **con su leyenda en español**, de dos maneras:

- en los **metadatos del propio GeoTIFF** (``GDAL_METADATA``, :func:`legend_items`): ``LEYENDA``
  (cómo se lee un valor), ``VERSION`` y un ``CLASE_<código>`` por cada código presente con su
  nombre;
- en un **``.qml`` paletado junto al fichero** (:func:`classes_qml`, ``<nombre>.qml``): QGIS lo
  aplica solo al abrir el GeoTIFF, con una entrada (valor, etiqueta, color) por código presente.

Los códigos son la suma de los bits de D-25 (:class:`~.combine.ClassBit`): una celda puede ser a
la vez «corte admitido», «dentro del perímetro» y «dentro del límite legal», así que la leyenda no
lista «clases» sino solo los **códigos que hay**, y el nombre de cada uno junta los de sus bits,
de menor a mayor, con « + » (:func:`class_label`; 0, «Sin clase»). Los nombres están en
``messages.toml`` (los reutiliza la superposición de la vista). Los colores
(:func:`class_color`) salen del bit que manda (conflicto, intocable, solo restauración, preferible
no afectar, franja, banda hacia dentro) y, si no hay ninguno, de corte y relleno admitidos; cada
código lleva además un matiz propio para distinguir los que comparten el bit que manda.

**El destino** (:func:`check_target`, antes de escribir nada): con su extensión
(``gis.export_extension_invalid``); dentro del proyecto, solo en ``exports/``
(``gis.export_inside_project``) y nunca con el proyecto en solo lectura
(``core.constraint_export_read_only``); la guarda de las escrituras de la 008
(``core.inputs.check_write_target``: ni sobre una entrada, ni en la carpeta de su fuente, ni en una
carpeta de solo lectura; RF-008-15); y sobre un fichero que ya existe, o cuyo ``.qml`` ya existe,
solo con ``overwrite`` (``gis.export_target_exists``: quien exporta pregunta). Se escribe en
temporales (``<destino>.tmp``, en la misma carpeta) con ``fsync`` y ``os.replace``: primero el
GeoTIFF y después el ``.qml``; si otro programa tiene abierto el destino (QGIS),
``gis.raster_target_locked`` y el anterior intacto; un fallo del disco, ``gis.raster_write_failed``;
en los dos, sin temporales. Si fallase solo el ``.qml`` después de poner el GeoTIFF, queda el nuevo
GeoTIFF con el ``.qml`` anterior.

**Por pasos** (RNF-012-06): el primero lee la rejilla registrada, los siguientes escriben una
tesela cada uno (``gis.geotiff.writer.write_steps``), uno cierra el GeoTIFF en su temporal y el
último escribe el ``.qml`` y pone los dos en su sitio. Cerrar los pasos antes (Esc) no deja nada.
Python puro (nivel 2).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator, Iterable, Mapping
from contextlib import closing
from pathlib import Path
from types import MappingProxyType
from typing import Protocol
from xml.sax.saxutils import quoteattr

import numpy as np

from ...core.constraints.messages import ConstraintError
from ...core.datasets import registry as dataset_registry
from ...core.i18n import LANGUAGES, translate
from ...core.inputs.guard import GuardProject, check_write_target
from ...core.paths import ReadOnlyDirs, check_path_length
from ...core.versions import read as versions_read
from ...core.versions.model import VersionError
from ..geotiff.reader import read_geotiff
from ..geotiff.writer import target_locked, temporary_path, write_failed, write_steps
from ..messages import GisError
from ..provenance import export_locator, inside_project
from ..raster import Raster
from ..store import StoreProject, project_references
from ..styles import QGIS_VERSION
from . import provenance as declared
from .access import MaskError, MaskState, mask_state
from .combine import ClassBit

__all__ = [
    "ALL_CODES_MAX",
    "CLASS_LABELS",
    "NO_CLASS_LABEL",
    "QML_SUFFIX",
    "SEPARATOR",
    "SUFFIXES",
    "ExportProject",
    "check_target",
    "class_color",
    "class_label",
    "classes_qml",
    "export_classes",
    "export_classes_steps",
    "legend_items",
    "present_codes",
    "qml_path",
]

SUFFIXES: tuple[str, ...] = (".tif", ".tiff")
"""Las extensiones del GeoTIFF entregable."""
QML_SUFFIX = ".qml"
"""La extensión del estilo que QGIS aplica solo (junto al GeoTIFF, con su mismo nombre)."""
SEPARATOR = " + "
"""Lo que junta los nombres de los bits de un código."""
ALL_CODES_MAX = sum(int(bit) for bit in ClassBit)
"""El mayor código posible: todos los bits de D-25 (2047)."""
NO_CLASS_LABEL = "No class"
"""El ``msgid`` del código 0 (ninguna clase)."""
CLASS_LABELS: Mapping[ClassBit, str] = MappingProxyType({
    ClassBit.CUT_ALLOWED: "Cut allowed",
    ClassBit.FILL_ALLOWED: "Fill allowed",
    ClassBit.FILL_STRIP: "Fill-only strip",
    ClassBit.PERIMETER: "Inside the action perimeter",
    ClassBit.LEGAL: "Inside the legal limit",
    ClassBit.INNER_BAND: "Inward buffer band of the legal limit",
    ClassBit.UNTOUCHABLE: "Untouchable or excluded",
    ClassBit.AVOID: "Preferably avoid",
    ClassBit.RESTORATION: "Restoration only",
    ClassBit.ACCESS: "Requires access",
    ClassBit.CONFLICT: "No movement possible",
})
"""El ``msgid`` (inglés; su español está en ``messages.toml``) del nombre de cada bit."""

_FIELD_TARGET = "destino"
_FIELD_EXTENSION = "extensión"
_LEGEND_TEXT = "Cada valor suma los códigos de las clases de la celda: "
_DOMINANT: tuple[tuple[ClassBit, tuple[int, int, int]], ...] = (
    (ClassBit.CONFLICT, (200, 30, 30)),
    (ClassBit.UNTOUCHABLE, (130, 35, 35)),
    (ClassBit.RESTORATION, (120, 85, 165)),
    (ClassBit.AVOID, (235, 170, 40)),
    (ClassBit.FILL_STRIP, (70, 135, 205)),
    (ClassBit.INNER_BAND, (165, 200, 120)),
)
_BOTH = (95, 170, 95)
_CUT_ONLY = (225, 130, 60)
_FILL_ONLY = (90, 150, 210)
_ACCESS = (120, 160, 175)
_PLAIN = (205, 205, 205)


class ExportProject(StoreProject, GuardProject, Protocol):
    """Lo que la exportación usa del proyecto (``core.project.Project``): lo de la guarda de las
    escrituras y de ``gis.store`` (su raíz, su nombre, si se puede escribir, su fila de
    ``gb_project`` con el CRS y la referencia vertical) y una lectura."""


# --- La leyenda ----------------------------------------------------------------------------


def _check_code(code: object) -> int:
    if isinstance(code, bool) or not isinstance(code, int | np.integer):
        raise TypeError(f"un código de clase es un número entero, no {code!r}")
    if not 0 <= int(code) <= ALL_CODES_MAX:
        raise ValueError(f"un código de clase va de 0 a {ALL_CODES_MAX} (la suma de los bits de "
                         f"D-25), no {int(code)}")
    return int(code)


def class_label(code: int, language: str = "es") -> str:
    """El nombre del código ``code`` en ``language`` (``es`` o ``en``): los de sus bits, de menor
    a mayor, unidos con :data:`SEPARATOR`; el 0, «Sin clase». ``ValueError`` si ``code`` no está
    entre 0 y :data:`ALL_CODES_MAX` o el idioma no es de Geoblender; ``TypeError`` si no es un
    entero."""
    number = _check_code(code)
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    if number == 0:
        return translate(language, NO_CLASS_LABEL)
    return SEPARATOR.join(translate(language, CLASS_LABELS[bit]) for bit in ClassBit
                          if number & int(bit))


def present_codes(classes: np.ndarray) -> tuple[int, ...]:
    """Los códigos que hay en la rejilla ``classes`` (enteros), distintos y de menor a mayor.
    ``ValueError`` si alguno pasa de :data:`ALL_CODES_MAX`."""
    codes = tuple(int(code) for code in np.unique(np.asarray(classes)))
    for code in codes:
        _check_code(code)
    return codes


def class_color(code: int) -> tuple[int, int, int, int]:
    """El color ``(r, g, b, a)`` del código ``code``: transparente el 0; los demás, opacos, del bit
    que manda (conflicto, intocable, solo restauración, preferible no afectar, franja, banda hacia
    dentro) o, si no hay ninguno, de corte y relleno admitidos, con un matiz propio de cada
    código (± 24 por canal) para distinguir los que comparten color. Determinista."""
    number = _check_code(code)
    if number == 0:
        return (0, 0, 0, 0)
    base = _PLAIN
    for bit, color in _DOMINANT:
        if number & int(bit):
            base = color
            break
    else:
        cut, fill = bool(number & ClassBit.CUT_ALLOWED), bool(number & ClassBit.FILL_ALLOWED)
        if cut and fill:
            base = _BOTH
        elif cut:
            base = _CUT_ONLY
        elif fill:
            base = _FILL_ONLY
        elif number & ClassBit.ACCESS:
            base = _ACCESS
    shade = ((number * 37) % 9 - 4) * 6
    red, green, blue = (min(255, max(0, part + shade)) for part in base)
    return (red, green, blue, 255)


def legend_items(codes: Iterable[int], version_code: str) -> dict[str, str]:
    """Los metadatos de texto del GeoTIFF (``GDAL_METADATA``) de las clases de la versión
    ``version_code`` con los códigos ``codes`` presentes: ``LEYENDA``, ``VERSION`` y
    ``CLASE_<código>`` de cada uno (de menor a mayor), con su nombre en español. Sin «&» (GDAL
    3.13 lo lee mal)."""
    if not isinstance(version_code, str) or not version_code.strip():
        raise ValueError(f"la versión de la leyenda es un texto no vacío, no {version_code!r}")
    bits = "; ".join(f"{int(bit)} = {translate('es', CLASS_LABELS[bit])}" for bit in ClassBit)
    items = {"LEYENDA": f"{_LEGEND_TEXT}{bits}", "VERSION": version_code}
    for code in sorted({_check_code(code) for code in codes}):
        items[f"CLASE_{code}"] = class_label(code)
    return items


def classes_qml(codes: Iterable[int]) -> str:
    """El QML (``styleCategories="Symbology"``) del GeoTIFF de clases: un renderizador paletado
    de la banda 1 con una entrada por código de ``codes`` (valor, color ``#rrggbb``, etiqueta en
    español y opacidad), de menor a mayor. El mismo texto cada vez. ``ValueError`` sin códigos."""
    chosen = sorted({_check_code(code) for code in codes})
    if not chosen:
        raise ValueError("la leyenda de una rejilla de clases tiene al menos un código")
    entries = []
    for code in chosen:
        red, green, blue, alpha = class_color(code)
        entries.append(f'    <paletteEntry value="{code}" color="#{red:02x}{green:02x}{blue:02x}" '
                       f"label={quoteattr(class_label(code))} alpha=\"{alpha}\"/>")
    palette = "\n".join(entries)
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        f'<qgis version="{QGIS_VERSION}" styleCategories="Symbology">\n'
        " <pipe>\n"
        '  <rasterrenderer type="paletted" band="1" opacity="1" alphaBand="-1" nodataColor="">\n'
        "   <rasterTransparency/>\n"
        "   <colorPalette>\n"
        f"{palette}\n"
        "   </colorPalette>\n"
        '   <colorramp name="[source]" type="randomcolors">\n'
        "    <Option/>\n"
        "   </colorramp>\n"
        "  </rasterrenderer>\n"
        " </pipe>\n"
        "</qgis>\n"
    )


# --- El destino ----------------------------------------------------------------------------


def qml_path(path: str | os.PathLike[str]) -> Path:
    """El ``.qml`` que acompaña al GeoTIFF ``path``: su mismo nombre con :data:`QML_SUFFIX`."""
    return Path(path).with_suffix(QML_SUFFIX)


def check_target(path: str | os.PathLike[str], *, project: ExportProject,
                 read_only: ReadOnlyDirs, overwrite: bool) -> Path:
    """El destino ``path`` del GeoTIFF de clases, comprobado sin escribir nada (véase el
    módulo): ``GisError`` ``gis.export_extension_invalid``, ``gis.export_inside_project`` o
    ``gis.export_target_exists`` (del GeoTIFF o de su ``.qml``); ``ConstraintError``
    ``core.constraint_export_read_only``; ``ProvenanceError`` ``core.write_target_*``
    (RF-008-15); ``core.path_too_long``."""
    if not isinstance(overwrite, bool):
        raise TypeError(f"«overwrite» es verdadero o falso, no {overwrite!r}")
    target = Path(path)
    name = target.name
    if target.suffix.lower() not in SUFFIXES:
        raise GisError("gis.export_extension_invalid", obj=name, field=_FIELD_EXTENSION,
                       value=target.suffix or "—", file=name, format="GeoTIFF",
                       expected="/".join(SUFFIXES))
    root = Path(project.root)
    if inside_project(root, target):
        if not project.writable:
            raise ConstraintError("core.constraint_export_read_only", field=_FIELD_TARGET,
                                  value=name, project=project.name)
        if export_locator(root, target) is None:
            raise GisError("gis.export_inside_project", obj=name, field=_FIELD_TARGET, value=name,
                           file=name, project=project.name)
    check_write_target(target, project=project, read_only=read_only)
    qml = qml_path(target)
    for file in (target, qml):
        check_path_length(temporary_path(file), obj=file.name)
        if not overwrite and file.exists():
            raise GisError("gis.export_target_exists", obj=file.name, field=_FIELD_TARGET,
                           value=file.name, file=file.name)
    return target


# --- Exportar ------------------------------------------------------------------------------


def _discard(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_text(text: str, temporary: Path) -> None:
    """``text`` (UTF-8, sin BOM, LF) en ``temporary``, forzado a disco."""
    with temporary.open("wb") as stream:
        stream.write(text.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _place(temporary: Path, target: Path) -> None:
    try:
        os.replace(temporary, target)
    except OSError as error:
        if isinstance(error, PermissionError):  # Windows: otro programa lo tiene abierto
            raise target_locked(target.name) from None
        raise write_failed(target.name, error) from None


def export_classes_steps(project: ExportProject, version: str, path: str | os.PathLike[str], *,
                         read_only: ReadOnlyDirs, overwrite: bool = False
                         ) -> Generator[float, None, Path]:
    """La rejilla de clases de la versión ``version`` (uid o código) como GeoTIFF entregable en
    ``path`` con su leyenda y su ``.qml``, por pasos (véase el módulo): al llamar, sin escribir
    nada, la versión (``VersionError`` ``core.version_unknown``), que sus máscaras estén al día
    (``MaskError``) y el destino (:func:`check_target`); el primer paso lee la registrada; cada
    uno de los siguientes escribe una tesela, el siguiente cierra el GeoTIFF en su temporal y el
    último escribe el ``.qml`` y pone los dos en su sitio y devuelve ``path``
    (``StopIteration.value``). Cerrar los pasos antes no deja nada."""
    with project.read() as conn:
        found = versions_read.version(conn, version)
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version,
                               version=version)
        record = dataset_registry.get(conn, declared.dataset_name(declared.CLASSES),
                                      version_uid=found.uid)
    state, _pending = mask_state(project, found.uid)
    if state is not MaskState.CURRENT or record is None:
        code = ("core.constraint_masks_stale" if state is MaskState.STALE
                else "core.constraint_masks_missing")
        raise MaskError(code, field="máscaras", value=state.value, version=found.code,
                        command=declared.COMMAND)
    target = check_target(path, project=project, read_only=read_only, overwrite=overwrite)
    source = Path(project.root).joinpath(*record.locator.split("/"))
    return _export_steps(project, found.code, source, target)


def _export_steps(project: ExportProject, version_code: str, source: Path,
                  target: Path) -> Generator[float, None, Path]:
    qml = qml_path(target)
    tif_temporary, qml_temporary = temporary_path(target), temporary_path(qml)
    try:
        found = read_geotiff(source, max_cells=sys.maxsize)
        values = np.asarray(found.values, dtype=np.float64)
        classes = np.where(np.isfinite(values), values, 0.0).astype(np.uint16)
        codes = present_codes(classes)
        crs, vertical = project_references(project)
        raster = Raster(found.grid, classes.astype(np.float64), crs, vertical)
        yield 0.0
        yield from write_steps(raster, target, profile="deliverable", temporary=tif_temporary,
                               replace=False, metadata=legend_items(codes, version_code))
        yield 1.0
        _write_text(classes_qml(codes), qml_temporary)
        _place(tif_temporary, target)
        _place(qml_temporary, qml)
    except BaseException as error:  # también GeneratorExit: cerrar los pasos a mitad
        _discard(tif_temporary, qml_temporary)
        if isinstance(error, OSError):
            raise write_failed(target.name, error) from None
        raise
    return target


def export_classes(project: ExportProject, version: str, path: str | os.PathLike[str], *,
                   read_only: ReadOnlyDirs, overwrite: bool = False) -> Path:
    """:func:`export_classes_steps` de una vez: devuelve ``path``."""
    steps = export_classes_steps(project, version, path, read_only=read_only,
                                 overwrite=overwrite)
    with closing(steps):
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                return stop.value  # type: ignore[no-any-return]
