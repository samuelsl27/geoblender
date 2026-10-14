# SPDX-License-Identifier: GPL-3.0-or-later
"""El informe de validación en CSV para Excel en español (spec 005, T11; HU-005-3;
RF-005-19 y RF-005-16; spec §8 y §11; plan 005 §3, §5.3 y §5.6.9).

:func:`write_csv` escribe un :class:`~.validate.ValidationReport` como CSV que Excel en
español abre bien: **UTF-8 con marca de orden de bytes** (sin ella, Excel no muestra bien las
tildes; spec §11 y plan D13; los demás ficheros de Geoblender van sin BOM), **«;»** de
separador, **coma decimal** y filas acabadas en CRLF; los campos con «;», comillas o saltos de
línea, entre comillas dobles al estilo de Excel (``csv`` de Python).

**Las filas** (:func:`rows`), en el orden del informe: una por incidencia (RF-005-16) y,
después, una por cada nota de lo que no se evaluó (spec §8: sin MDT, o una boca fuera de él,
DH-W05 no se evalúa y el informe lo dice), con el nivel «Sin evaluar». **Las columnas**
(:func:`header`): el sondeo (vacío en las de un catálogo), el código, el nivel (error o
aviso), el alcance de un error (sondeo, tabla o registro, spec §4.4.1: lo que excluye; vacío
en un aviso), la tabla y el campo con sus identificadores del modelo de datos (los de las
tablas del proyecto que abre QGIS, RF-005-01), el esquema de logueo o el elemento de un
tramo, la entrada de un catálogo, el tramo o la profundidad (desde y hasta, m), el valor y el
mensaje en español que dice qué corregir (:meth:`~.validate.Issue.message`). La cabecera, el
nivel y el alcance tienen su ``msgid`` en inglés en :data:`MESSAGE_IDS` y su español en
``core/i18n/messages.toml``; el CSV va siempre en español (RF-005-19).

**Los números** (tramos y valores numéricos): el decimal más corto que vuelve al mismo
float64, sin exponente ni separador de miles (Excel los lee como números) y con coma; −0 es
«0», y un valor que no es finito, «inf» o «-inf». **El valor**: el texto tal como está
guardado, «sí» o «no», el número, o vacío (un campo vacío o una comprobación de un cálculo,
sin valor). La primera columna es «Sondeo», no «ID» (Excel tomaría el fichero por SYLK).

**La escritura** (plan §5.6.9): por un temporal (``<destino>.tmp``, en la misma carpeta),
``fsync`` y ``os.replace``: nunca un fichero a medias, y el destino anterior sigue intacto si
algo falla (el temporal se borra). Con el destino abierto por otro programa (Excel lo
bloquea mientras lo tiene abierto), ``dh.report_target_locked``; cualquier otro fallo del
disco, ``dh.report_write_failed``; una ruta más larga de lo que admite Blender en Windows,
``core.path_too_long`` sin escribir nada. Comprobar que el destino se puede escribir
(``check_write_target``, RF-008-15) y confirmar la sustitución de uno que ya existe es de la
operación que exporta (``dh.export_validation``, T27). Nada modifica el informe.
"""

from __future__ import annotations

import codecs
import csv
import io
import math
import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ..core.errors import GeoblenderError
from ..core.i18n import translate
from ..core.paths import check_path_length
from .validate import Issue, Level, Note, Scope, ValidationReport

__all__ = [
    "BOM",
    "ENCODING",
    "LANGUAGE",
    "MESSAGE_IDS",
    "SEPARATOR",
    "TEMPORARY_SUFFIX",
    "csv_bytes",
    "header",
    "rows",
    "write_csv",
]

LANGUAGE = "es"
"""El idioma del CSV (RF-005-19: Excel en español)."""
ENCODING = "utf-8-sig"
"""UTF-8 con marca de orden de bytes (:data:`BOM`)."""
BOM = codecs.BOM_UTF8
"""La marca de orden de bytes con la que empieza el fichero."""
SEPARATOR = ";"
LINE_END = "\r\n"
DECIMAL_MARK = ","
TEMPORARY_SUFFIX = ".tmp"

_COLUMNS = ("Hole", "Code", "Level", "Error scope", "Table", "Logging scheme or element",
            "Catalog code", "From (m)", "To (m)", "Field", "Value", "Message")
_LEVELS = {Level.ERROR: "Error", Level.WARNING: "Warning"}
_NOT_EVALUATED = "Not evaluated"
_SCOPES = {Scope.HOLE: "Hole", Scope.TABLE: "Table", Scope.RECORD: "Record"}
MESSAGE_IDS: tuple[str, ...] = tuple(dict.fromkeys(
    (*_COLUMNS, *_LEVELS.values(), _NOT_EVALUATED, *_SCOPES.values())))
"""Los ``msgid`` (inglés) de la cabecera, los niveles y los alcances; su español está en
``core/i18n/messages.toml``."""

_YES_NO = ("no", "sí")
_FIELD_TARGET = "destino"
_EMPTY = ""

type Row = tuple[str, ...]


def _es(msgid: str) -> str:
    return translate(LANGUAGE, msgid)


def header() -> Row:
    """Los títulos de las columnas, en español."""
    return tuple(_es(msgid) for msgid in _COLUMNS)


def _number(value: float) -> str:
    """Un número con coma decimal: el decimal más corto que vuelve al mismo float64, sin
    exponente ni separador de miles; −0, «0»."""
    if math.isnan(value):
        return _EMPTY
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    text = np.format_float_positional(value, unique=True, trim="-")
    if text == "-0":
        text = "0"
    return text.replace(".", DECIMAL_MARK)


def _depth(value: float | None) -> str:
    return _EMPTY if value is None else _number(float(value))


def _value(value: object) -> str:
    """El valor de una incidencia como celda (véase el módulo)."""
    if value is None:
        return _EMPTY
    if isinstance(value, bool | np.bool_):
        return _YES_NO[bool(value)]
    if isinstance(value, str):
        return value
    if isinstance(value, int | np.integer):
        return str(int(value))
    if isinstance(value, float | np.floating):
        return _number(float(value))
    raise TypeError(f"el valor de una incidencia es texto, número, sí/no o vacío, no {value!r}")


def _text(value: str | None) -> str:
    return _EMPTY if value is None else value


def _issue_row(issue: Issue) -> Row:
    scope = issue.scope
    return (
        _text(issue.hole_name),
        issue.code,
        _es(_LEVELS[issue.level]),
        _EMPTY if scope is None else _es(_SCOPES[scope]),
        issue.table,
        _text(issue.log_set or issue.element),
        _text(issue.catalog_code),
        _depth(issue.depth_from),
        _depth(issue.depth_to),
        _text(issue.field),
        _value(issue.value),
        issue.message(LANGUAGE),
    )


def _note_row(note: Note) -> Row:
    return (_text(note.hole_name), note.code, _es(_NOT_EVALUATED), *([_EMPTY] * 8),
            note.message(LANGUAGE))


def rows(report: ValidationReport) -> list[Row]:
    """Las filas del CSV de ``report`` (sin la cabecera), en español: una por incidencia y,
    después, una por nota (véase el módulo). ``TypeError`` si no es un
    ``ValidationReport`` o si el valor de una incidencia no es texto, número, sí/no ni
    vacío."""
    if not isinstance(report, ValidationReport):
        raise TypeError(f"el informe es un ValidationReport, no {type(report).__name__}")
    return [*(_issue_row(issue) for issue in report.issues),
            *(_note_row(note) for note in report.notes)]


def _csv_text(table: Sequence[Row]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=SEPARATOR, lineterminator=LINE_END)
    writer.writerows(table)
    return stream.getvalue()


def csv_bytes(report: ValidationReport) -> bytes:
    """El CSV de ``report`` tal como lo escribe :func:`write_csv`: BOM UTF-8, cabecera y
    :func:`rows`, separados por «;» y con CRLF."""
    found = rows(report)
    return _csv_text([header(), *found]).encode(ENCODING)


def write_csv(report: ValidationReport, path: str | os.PathLike[str]) -> Path:
    """Escribe el CSV de ``report`` en ``path`` (lo sustituye entero si existe) por un
    temporal y ``os.replace``; devuelve ``path``. :class:`GeoblenderError`
    ``dh.report_target_locked`` si otro programa tiene abierto el destino,
    ``dh.report_write_failed`` si falla el disco y ``core.path_too_long`` si la ruta no
    cabe; en todos, el destino anterior sigue intacto y no queda el temporal."""
    data = csv_bytes(report)
    target = Path(path)
    name = target.name
    temporary = target.with_name(name + TEMPORARY_SUFFIX)
    check_path_length(temporary, obj=name)
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as error:
        _discard(temporary)
        if isinstance(error, OSError):
            raise _write_failed(name, error) from None
        raise
    try:
        os.replace(temporary, target)
    except OSError as error:
        _discard(temporary)
        if isinstance(error, PermissionError):  # Windows: otro programa lo tiene abierto
            raise GeoblenderError(
                "dh.report_target_locked",
                "otro programa (Excel, por ejemplo) tiene abierto el fichero: ciérrelo y "
                "vuelva a exportar el informe. El fichero anterior sigue como estaba",
                obj="Informe de validación", field=_FIELD_TARGET, value=name,
            ) from None
        raise _write_failed(name, error) from None
    return target


def _write_failed(name: str, error: OSError) -> GeoblenderError:
    detail = error.strerror or str(error)
    return GeoblenderError(
        "dh.report_write_failed",
        f"no se ha podido escribir el informe ({detail}): compruebe que la carpeta existe y "
        "que se puede escribir en ella, y vuelva a exportarlo. No se ha cambiado nada",
        obj="Informe de validación", field=_FIELD_TARGET, value=name,
    )


def _discard(temporary: Path) -> None:
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
