# SPDX-License-Identifier: GPL-3.0-or-later
"""Quién declara las restricciones de las entidades de una versión (spec 015, T38; RF-015-10, RF-015-29;
CE-015-04, HU-015-1; plan 015 §5.8; ADR-0030 §3; hallazgo E-1 de la verificación única).

El hueco H-1 de ``gis.masks.access`` (una tabla de declaradas viva que la compilación vigente no consumió deja
las máscaras obsoletas) **no cubre la primera declaración de una versión**: mientras no se escribe la tabla
(``des_decl_<vNN>``) no hay nada que la compilación no haya consumido. «Crear» una plataforma que protege hace su
commit y **después** encadena, por pasos, la declaración y la compilación; si Esc o un fallo cortan la cadena antes
de que se escriba la primera tabla, la entidad queda viva, protegiendo, **sin su restricción en ningún sitio** y con
las máscaras de antes «al día»: un operador de diseño rellenaría sobre su huella sin un aviso (el error 51).

Quién sabe qué entidades viven y protegen es ``design`` y ``gis`` no puede importarlo, así que ``design`` (a
través de ``bl``, que registra el gancho al habilitar Geoblender, como registra los tipos de operación) da a
``gis.masks.access`` un :class:`DeclarationHook` con **dos** cosas:

- :attr:`~DeclarationHook.pending`: si una entidad viva y calculada de la versión que protege **no tiene su
  restricción en la declaración vigente** (sin tabla viva, o con una a la que le falta su fila). Solo lee y lo
  llama ``mask_state`` (también al dibujar la interfaz): ha de ser barata. Con ella, las máscaras están
  **obsoletas** con su causa (``MaskCause.DECLARED_NEW``) mientras la restricción esté pendiente: nunca al día sin
  la zona de una entidad que protege.
- :attr:`~DeclarationHook.declare`: los pasos de **declararlas** ahora (``des.declare_constraints``, una
  operación propia y una transacción propia; el último ``Progress`` lleva lo guardado). Lo usa
  ``gis.masks.access.declare_pending_steps`` antes de compilar, para que la compilación (de un operador por el
  contrato, ``ensure_masks_steps``, o la orden «Compilar las máscaras») lea la declaración y no deje las máscaras
  obsoletas para siempre por una tabla que no existe.

Sin gancho registrado (``gis`` solo, las pruebas de la 012, o ``design`` aún sin cargar) todo es como en la 012.

Python puro (nivel 2). Ligero a propósito: ``bl`` lo importa al habilitar y no importa nada de ``gis`` ni de
``design`` (RNF-001-03)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...core.project.model import Progress
    from ..store import StoreProject

__all__ = ["DeclarationHook", "current", "register", "unregister"]


@dataclass(frozen=True, slots=True, eq=False)
class DeclarationHook:
    """Lo que ``design`` da a ``gis.masks.access`` para la primera declaración de una versión (véase el módulo):
    ``pending(project, conn, version_uid)`` (si hay una restricción de una entidad pendiente de declarar; ``conn``
    es la conexión de lectura de quien llama, con su instantánea) y ``declare(project, version_uid, budget_s)``
    (los pasos de declararlas, de ``budget_s`` como mucho)."""

    pending: Callable[[StoreProject, sqlite3.Connection, str], bool]
    declare: Callable[[StoreProject, str, float], Iterator[Progress]]


_HOOK: DeclarationHook | None = None


def register(hook: DeclarationHook) -> None:
    """Registra ``hook`` como el gancho de la declaración (el que había, si lo había, se sustituye); idempotente."""
    global _HOOK
    _HOOK = hook


def unregister(hook: DeclarationHook) -> None:
    """Quita ``hook`` si es el registrado (lo que otro registró después es suyo); idempotente."""
    global _HOOK
    if _HOOK is hook:
        _HOOK = None


def current() -> DeclarationHook | None:
    """El gancho registrado, o ``None`` (sin él, ninguna restricción de entidad queda pendiente)."""
    return _HOOK
