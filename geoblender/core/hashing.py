# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON canónico, flotante canónico y huellas sha256 (spec 008; RF-008-07, RF-008-08;
ADR-0024 §2 y §7; plan 008 §5.3.1).

Son las piezas comunes del hash de contenido (``core.content``) y de lo que se registra de
cada entrada (ajustes de importación en JSON canónico, huella de los bytes de cada
fichero). Su salida no puede depender del proceso, del equipo ni del orden en que se
construyó un valor: un hash de hoy se comprueba con el Geoblender de dentro de cinco años
(ADR-0024 §6). Cambiar lo que escriben es cambiar el normalizador (una versión nueva).

- :func:`canonical_float`: el flotante canónico. Un float32 se amplía a float64 sin
  pérdida; todo NaN es el NaN canónico (:data:`CANONICAL_NAN`, ``0x7FF8000000000000``);
  −0,0 es 0,0. Lo demás no cambia en ningún bit (sin tolerancia, D-8).
- :func:`canonical_json`: el **JSON canónico** de ADR-0024 §2, en bytes: UTF-8 sin BOM,
  claves ordenadas (por punto de código), sin espacios, enteros como enteros, flotantes
  con ``repr`` (el texto más corto que vuelve al mismo binario; 1 y 1,0 son distintos),
  −0,0 → ``0.0``, NaN → ``{"nan":true}``, infinitos → ``{"inf":1}`` o ``{"inf":-1}``,
  binarios → ``{"b64":…}`` (base64 estándar con relleno), fechas en ISO 8601 (UTC con «Z»,
  como ``core.timeutil``; días como ``AAAA-MM-DD``) y el texto tal cual (sin normalizar
  Unicode ni espacios: exacto). Lo que no tiene una forma única (conjuntos, claves que no
  son texto, fracciones, decimales, matrices, fechas sin zona) se rechaza.
- :func:`sha256_bytes` y :func:`sha256_file`: la huella (sha256 en hexadecimal en
  minúsculas) de unos bytes o de un fichero leído por trozos (8 MiB por defecto), con
  progreso tras cada trozo y cancelación entre trozos (:class:`HashCancelled`).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import math
import numbers
import operator
import os
import struct
from collections.abc import Callable, Mapping
from typing import Any

from .timeutil import format_utc

CANONICAL_NAN_BITS = 0x7FF8000000000000
"""Los bits del NaN canónico (float64 silencioso, signo positivo, sin carga)."""
CANONICAL_NAN: float = struct.unpack("<d", CANONICAL_NAN_BITS.to_bytes(8, "little"))[0]
"""El NaN canónico: el que devuelve :func:`canonical_float` para cualquier NaN."""
DEFAULT_CHUNK = 8 << 20
"""Trozo de lectura de :func:`sha256_file` (8 MiB, como la copia por trozos de la 002)."""

type ProgressCallback = Callable[[int, int], object]
"""``progress(hechos, total)`` en bytes, tras cada trozo leído."""
type CancelCheck = Callable[[], bool]
"""``cancelled()``: verdadero si se pidió parar; se consulta antes de leer cada trozo."""


class HashCancelled(Exception):
    """Se pidió parar el cálculo de una huella entre dos trozos. ``name`` es el nombre del
    fichero (sin carpeta), ``done`` los bytes leídos y ``total`` su tamaño."""

    def __init__(self, name: str, done: int, total: int) -> None:
        self.name = name
        self.done = done
        self.total = total
        super().__init__(
            f"Se paró el cálculo de la huella de «{name}» tras leer {done} de {total} bytes"
        )


def canonical_float(x: float) -> float:
    """El flotante canónico de ``x`` (un real: ``float``, ``int`` o un flotante de numpy,
    también float32, que se amplía sin pérdida): NaN → :data:`CANONICAL_NAN`, −0,0 → 0,0 y
    lo demás sin cambiar. ``TypeError`` si ``x`` es un booleano o no es un número real."""
    if isinstance(x, bool) or not isinstance(x, numbers.Real):
        raise TypeError(f"{x!r} ({type(x).__name__}) no es un número real")
    value = float(x)
    if value != value:
        return CANONICAL_NAN
    if value == 0.0:
        return 0.0
    return value


def canonical_json(value: object) -> bytes:
    """El JSON canónico de ``value`` (ADR-0024 §2), en bytes UTF-8 sin BOM.

    Admite ``None``, booleanos, enteros (también de numpy), flotantes (también float32 de
    numpy), textos, listas y tuplas, diccionarios y otros ``Mapping`` con claves de texto,
    binarios (``bytes``, ``bytearray``, ``memoryview``) y fechas (``datetime`` con zona y
    ``date``). ``TypeError`` con lo que no tiene una forma canónica única; ``ValueError``
    con una fecha sin zona (no se supone) o un texto que no es UTF-8 válido (un sustituto
    suelto). ``value`` no se modifica."""
    text = json.dumps(
        _plain(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(
            "un texto con un sustituto suelto (de U+D800 a U+DFFF) no es UTF-8 válido: "
            "no tiene forma canónica"
        ) from error


def sha256_bytes(data: bytes | bytearray | memoryview) -> str:
    """La huella sha256 de ``data``, en 64 cifras hexadecimales en minúsculas.
    ``TypeError`` con un texto: se codifica antes (``canonical_json`` ya da bytes)."""
    if isinstance(data, str):
        raise TypeError("un texto no tiene huella: codifícalo antes (UTF-8)")
    return hashlib.sha256(data).hexdigest()


def sha256_file(
    path: str | os.PathLike[str],
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCheck | None = None,
    chunk: int = DEFAULT_CHUNK,
) -> str:
    """La huella sha256 de los bytes del fichero ``path``, leído por trozos de ``chunk``
    bytes (memoria acotada a un trozo). El fichero solo se lee.

    ``progress(hechos, total)`` se llama tras cada trozo (una vez con ``(0, 0)`` si está
    vacío); ``total`` es el tamaño al abrirlo (o lo leído, si creció). ``cancelled()`` se
    consulta antes de leer cada trozo: si es verdadero, se cierra el fichero y se lanza
    :class:`HashCancelled`. ``chunk`` es un entero positivo (``TypeError`` o
    ``ValueError`` antes de abrir nada); los errores al abrir o leer (``OSError``) pasan
    tal cual."""
    if isinstance(chunk, bool) or not isinstance(chunk, int):
        raise TypeError(f"el trozo de lectura {chunk!r} no es un número entero de bytes")
    if chunk <= 0:
        raise ValueError(f"el trozo de lectura ({chunk} bytes) tiene que ser positivo")
    source = os.fspath(path)
    name = os.path.basename(source)
    digest = hashlib.sha256()
    done = 0
    with open(source, "rb", buffering=0) as stream:
        size = os.fstat(stream.fileno()).st_size
        while True:
            if cancelled is not None and cancelled():
                raise HashCancelled(name, done, max(size, done))
            block = stream.read(chunk)
            if not block:
                break
            digest.update(block)
            done += len(block)
            if progress is not None:
                progress(done, max(size, done))
    if done == 0 and progress is not None:
        progress(0, 0)
    return digest.hexdigest()


# --- Forma canónica ------------------------------------------------------------------------


def _plain(value: object) -> Any:
    """``value`` con solo tipos que ``json`` escribe de una única manera: los flotantes
    canónicos o su marca, enteros y textos exactos, diccionarios con claves de texto y
    listas; un objeto nuevo, sin tocar el original."""
    kind = type(value)
    if value is None or kind is str or kind is int or kind is bool:
        return value
    if kind is float:
        return _plain_float(value)
    if kind is list or kind is tuple:
        return [_plain(item) for item in value]
    if kind is dict or isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"la clave {key!r} ({type(key).__name__}) no es un texto: las claves de "
                    "un objeto JSON canónico son textos"
                )
            result[str.__str__(key)] = _plain(item)
        return result
    if isinstance(value, str):
        return str.__str__(value)
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, numbers.Integral):
        return operator.index(value)
    if isinstance(value, float) or (
        isinstance(value, numbers.Real) and not isinstance(value, numbers.Rational)
    ):
        return _plain_float(float(value))
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"b64": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, dt.datetime):
        return _datetime_text(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(
        f"{type(value).__name__} no tiene forma JSON canónica ({_shown(value)}): "
        "convierte antes el valor (una lista ordenada, un flotante, un texto…)"
    )


def _plain_float(value: float) -> Any:
    """Un ``float`` exacto: su marca si es NaN o infinito; 0,0 si es −0,0; él mismo si no
    (``json`` lo escribe con ``repr``)."""
    if value != value:
        return {"nan": True}
    if value == math.inf:
        return {"inf": 1}
    if value == -math.inf:
        return {"inf": -1}
    if value == 0.0:
        return 0.0
    return value


def _datetime_text(moment: dt.datetime) -> str:
    """``AAAA-MM-DDTHH:MM:SS.mmmZ`` en UTC (``core.timeutil.format_utc``), o con los seis
    decimales si hay microsegundos: no se pierde nada. ``ValueError`` sin zona."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(
            f"la fecha {moment.isoformat()} no tiene zona: no se supone (se guardan en UTC)"
        )
    utc = moment.astimezone(dt.UTC)
    if utc.microsecond % 1000 == 0:
        return format_utc(utc)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond:06d}Z"


def _shown(value: object) -> str:
    """El valor para un mensaje, recortado."""
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "…"
