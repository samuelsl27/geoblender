# SPDX-License-Identifier: GPL-3.0-or-later
"""El informe de validación en CSV para Excel en español (spec 005, T11; HU-005-3;
RF-005-19 y RF-005-16; spec §8 y §11; plan 005 §3, §5.3 y §5.6.9).

:func:`write_csv` escribe un :class:`~.validate.ValidationReport` como CSV que Excel en
español abre bien: **UTF-8 con marca de orden de bytes** (sin ella, Excel no muestra bien las
tildes; spec §11 y plan D13; los demás ficheros de Geoblender van sin BOM), **«;»** de
separador, **coma decimal** y filas acabadas en CRLF; los campos con «;», comillas o saltos de
línea, entre comillas dobles al estilo de Excel (``csv`` de Python).

**Las filas** (:func:`rows`), en el orden del informe: una por incidencia (RF-005-16);
después (T56; RF-005-18), la diferencia con el MDT de cada boca dentro de la tolerancia, con
el nivel «Información» (las que pasan de ella tienen su aviso DH-W05), y una por cada nota de
lo que no se evaluó (spec §8: una boca fuera del MDT, sobre su boca, y sin MDT, DH-W05 no se
evalúa y el informe lo dice), con el nivel «Sin evaluar». **Las columnas**
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

**El informe guardado** (T27; plan §5.6.4 y §5.6.9): la exportación lee lo que guardó
``dh.validate`` en ``dh_validation_issue`` (una fila por incidencia, con el valor en texto y
el mensaje en español; desde T56, también la diferencia de cada boca con el MDT y las bocas
fuera de él, ``drillholes.jobs.issue_rows``) y las notas generales de su operación (las de
sus ajustes: sin MDT); :func:`stored_rows` da con ellas las mismas filas que :func:`rows` con
el informe que las produjo (el valor de un campo de ``validate.NUMBER_FIELDS``, guardado con
punto, vuelve con coma), :func:`rows_bytes` sus bytes y :func:`write_rows` las escribe como
:func:`write_csv`.
"""

from __future__ import annotations

import codecs
import csv
import io
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..core.errors import GeoblenderError
from ..core.i18n import translate
from ..core.paths import check_path_length
from .validate import (
    NUMBER_FIELDS,
    DemDifference,
    Issue,
    Level,
    Note,
    Scope,
    ValidationReport,
)

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
    "rows_bytes",
    "stored_rows",
    "write_csv",
    "write_rows",
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
_NOT_EVALUATED = "Not evaluated"
_LEVELS = {Level.ERROR: "Error", Level.WARNING: "Warning", Level.INFO: "Information",
           Level.NOT_EVALUATED: _NOT_EVALUATED}
_SCOPES = {Scope.HOLE: "Hole", Scope.TABLE: "Table", Scope.RECORD: "Record"}
MESSAGE_IDS: tuple[str, ...] = tuple(dict.fromkeys(
    (*_COLUMNS, *_LEVELS.values(), *_SCOPES.values())))
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


def _collar_row(found: Note | DemDifference) -> Row:
    """La fila de una nota o de una diferencia con el MDT: su boca, su código, su nivel, su
    tabla y su campo (los de una nota general, vacíos), sin valor (es un cálculo) y su
    mensaje."""
    return (_text(found.hole_name), found.code, _es(_LEVELS[found.level]), _EMPTY,
            _text(found.table), _EMPTY, _EMPTY, _EMPTY, _EMPTY, _text(found.field), _EMPTY,
            found.message(LANGUAGE))


def rows(report: ValidationReport) -> list[Row]:
    """Las filas del CSV de ``report`` (sin la cabecera), en español: una por incidencia, una
    por diferencia con el MDT y una por nota, primero las de una boca y después las generales
    (véase el módulo). ``TypeError`` si no es un ``ValidationReport`` o si el valor de una
    incidencia no es texto, número, sí/no ni vacío."""
    if not isinstance(report, ValidationReport):
        raise TypeError(f"el informe es un ValidationReport, no {type(report).__name__}")
    notes = sorted(report.notes, key=lambda note: note.hole < 0)  # estable
    return [*(_issue_row(issue) for issue in report.issues),
            *(_collar_row(found) for found in (*report.differences, *notes))]


def _csv_text(table: Sequence[Row]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=SEPARATOR, lineterminator=LINE_END)
    writer.writerows(table)
    return stream.getvalue()


def _stored_value(field: str | None, value: Any) -> str:
    """El valor guardado de una incidencia como celda: el de un campo numérico
    (``validate.NUMBER_FIELDS``), guardado como su decimal más corto con punto, vuelve a ser
    el número con coma; los demás, el texto tal cual (como :func:`_value`)."""
    if field in NUMBER_FIELDS and isinstance(value, str) and value:
        return _number(float(value))
    return _value(value)


def _stored_row(record: Mapping[str, Any]) -> Row:
    scope = record["scope"]
    return (
        _text(record["hole_name"]),
        record["code"],
        _es(_LEVELS[Level(record["level"])]),
        _EMPTY if scope is None else _es(_SCOPES[Scope(scope)]),
        record["table_name"],
        _text(record["log_set"] or record["element"]),
        _text(record["catalog_code"]),
        _depth(record["depth_from"]),
        _depth(record["depth_to"]),
        _text(record["field"]),
        _stored_value(record["field"], record["value"]),
        record["message"],
    )


def stored_rows(records: Iterable[Mapping[str, Any]], notes: Iterable[Note] = ()) -> list[Row]:
    """Las filas del CSV del informe guardado (sin la cabecera): una por fila de
    ``dh_validation_issue`` (``records``, cada una por el nombre de sus columnas, en el orden
    de su ``fid``: las incidencias, la diferencia de cada boca con el MDT y las bocas fuera de
    él) y, después, una por nota de ``notes`` (las que no se guardan: las generales, de los
    ajustes de su operación); las mismas que :func:`rows` con el informe que las produjo
    (véase el módulo). ``KeyError`` si a una fila le falta una columna; ``ValueError`` si su
    nivel o su alcance no son de la spec."""
    return [*(_stored_row(record) for record in records),
            *(_collar_row(note) for note in notes)]


def rows_bytes(table: Sequence[Row]) -> bytes:
    """El CSV de unas filas (las de :func:`rows` o :func:`stored_rows`) tal como lo escribe
    :func:`write_rows`: BOM UTF-8, cabecera y las filas, separados por «;» y con CRLF."""
    return _csv_text([header(), *table]).encode(ENCODING)


def csv_bytes(report: ValidationReport) -> bytes:
    """El CSV de ``report`` tal como lo escribe :func:`write_csv`: BOM UTF-8, cabecera y
    :func:`rows`, separados por «;» y con CRLF."""
    return rows_bytes(rows(report))


def write_csv(report: ValidationReport, path: str | os.PathLike[str]) -> Path:
    """Escribe el CSV de ``report`` en ``path`` (lo sustituye entero si existe) por un
    temporal y ``os.replace``; devuelve ``path``. :class:`GeoblenderError`
    ``dh.report_target_locked`` si otro programa tiene abierto el destino,
    ``dh.report_write_failed`` si falla el disco y ``core.path_too_long`` si la ruta no
    cabe; en todos, el destino anterior sigue intacto y no queda el temporal."""
    return write_rows(rows(report), path)


def write_rows(table: Sequence[Row], path: str | os.PathLike[str]) -> Path:
    """Escribe el CSV de unas filas (las de :func:`rows` o :func:`stored_rows`) en ``path``
    como :func:`write_csv` (con sus mismos errores); devuelve ``path``."""
    data = rows_bytes(table)
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
