# SPDX-License-Identifier: GPL-3.0-or-later
"""Errores de Geoblender para el usuario (constitución, principio 10; spec 002).

Todo error que llega a una persona nombra el **objeto**, el **campo** y el **valor**
concretos y dice el motivo y qué hacer, en español. Lleva además un ``code`` estable en
inglés (``"core.crs_not_in_catalog"``) para las pruebas, el registro y la interfaz, y un
``context`` con datos para el registro técnico. La traza nunca se muestra al usuario: va
al registro.

- :class:`GeoblenderError`: la base.
- :class:`ValidationError`: una entrada que no es válida (un CRS fuera del catálogo, una
  ventana con los ejes invertidos, un Z0 fuera de rango).
- :class:`ProjectError` y :class:`LockError`: el proyecto y su cerrojo (spec 002).
- :class:`GeometryError`, :class:`DatabaseError` y :class:`DatabaseBusyError`: la
  geometría y la base de datos del proyecto (``core.gpkg``).

Las specs añaden los suyos derivando de la base.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def display_value(value: object) -> str:
    """El valor como lo lee una persona: los textos entre comillas latinas, los
    decimales con coma (``700099.6`` → ``700099,6``) y ``None`` como «vacío»."""
    if value is None:
        return "vacío"
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, float):
        return repr(value).replace(".", ",")
    if isinstance(value, str):
        return f"«{value}»"
    return str(value)


class GeoblenderError(Exception):
    """Error para el usuario: objeto, campo, valor y motivo, con un código estable.

    El mensaje (``str(error)``) es ``«<objeto>: <campo> = <valor>: <motivo>»``; ``shown``
    sustituye a la forma por defecto de mostrar el valor (p. ej. ``"EPSG:4326"``).
    """

    def __init__(
        self,
        code: str,
        reason: str,
        *,
        obj: str,
        field: str,
        value: object = None,
        shown: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.reason = reason
        self.obj = obj
        self.field = field
        self.value = value
        self.shown = display_value(value) if shown is None else shown
        self.context: dict[str, Any] = dict(context or {})
        super().__init__(f"{obj}: {field} = {self.shown}: {reason}")

    @property
    def message(self) -> str:
        """El mensaje completo, en español."""
        return str(self)


class ValidationError(GeoblenderError):
    """Una entrada no válida (campo de un diálogo, dato del catálogo, ajuste)."""


class GeometryError(GeoblenderError):
    """Una geometría que Geoblender no escribe ni lee: vacía, de un tipo no admitido o
    mal formada (``core.gpkg.wkb``)."""


class ProjectError(GeoblenderError):
    """Un problema del proyecto como conjunto: crearlo, abrirlo, su cabecera, su esquema
    o su carpeta (spec 002)."""


class LockError(ProjectError):
    """El cerrojo de un solo escritor no deja hacer lo que se pide: lo tiene otra sesión,
    se perdió o no se puede leer (spec 002)."""


class DatabaseError(GeoblenderError):
    """La base de datos del proyecto no se puede abrir, leer o escribir como hace falta
    (no existe, no es SQLite, está en WAL, la conexión es de solo lectura…)."""


class DatabaseBusyError(DatabaseError):
    """Otro programa (QGIS, otra sesión) tiene la base de datos ocupada: la escritura no
    esperó más de 0,2 s y no cambió nada; se puede reintentar."""
