# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de las restricciones (spec 012; RF-012-02, RF-012-04, RF-012-08; plan 012
§5.2.2; D-4 y D-5 de la spec; ADR-0027; RF-008-01).

Lo que una restricción pide (D-23) son **familias** de parámetros (:data:`FAMILIES`), una clave
por restricción con su código inmutable (D-22), **sin valor por defecto** (D-5: un resguardo
por defecto sería una distancia de seguridad inventada que acabaría en un plano) y **de
versión** (D-4: la propiedad libera o endurece una zona en una versión sin redibujarla):

- ``core.constraint.{c}.buffer_out_m``: resguardo hacia fuera, m en [0; 1 000], HIPÓTESIS;
- ``core.constraint.{c}.buffer_in_m``: resguardo hacia dentro de un límite, m en [0; 1 000],
  HIPÓTESIS;
- ``core.constraint.{c}.weight``: peso de una «preferible no afectar», — en [1; 1 000],
  HIPÓTESIS;
- ``core.constraint.{c}.active``: si está activa, sí/no, ADOPTADO.

Los declara una persona al crear o completar la restricción (origen ``person``). Además, el
parámetro del proyecto ``core.constraints.search_distance_m`` (:data:`SEARCH_DISTANCE`): 25 m
ADOPTADO «sin confirmar» en (0; 1 000] m (D-5; RF-012-08).

``bl`` registra :data:`DEFINITIONS` y :data:`FAMILIES` en ``core.params`` y las quita con
``unregister_definitions("core")`` y ``unregister_families("core")``. Importarlo no registra
nada.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..params import ParamDef, ParamFamily
from .model import ConstraintParam, is_code

__all__ = [
    "DEFINITIONS",
    "FAMILIES",
    "SEARCH_DISTANCE",
    "active_key",
    "buffer_in_key",
    "buffer_out_key",
    "family",
    "param_key",
    "weight_key",
]

PREFIX = "core.constraint"
"""El principio de la clave de un parámetro de una restricción."""

_D5 = ("Spec 012, D-5: sin valor por defecto; lo declara una persona con su tipo al crear o "
       "completar la restricción (Samuel, IMGA, 28/10/2026)")
_D5_SEARCH = ("Spec 012, D-5: 25 m, unas tres veces los 8 m de resguardo de la torre del "
              "proyecto de referencia; sin confirmar (Samuel, IMGA, 28/10/2026)")

_SPECS: Mapping[ConstraintParam, tuple[str, str, float | None, float | None, str,
                                        tuple[str, ...], str]] = {
    ConstraintParam.BUFFER_OUT: ("float", "m", 0.0, 1000.0, "HIPÓTESIS",
                                 ("RF-012-02", "RF-012-04", "RF-012-12"), "Outward buffer"),
    ConstraintParam.BUFFER_IN: ("float", "m", 0.0, 1000.0, "HIPÓTESIS",
                                ("RF-012-02", "RF-012-04", "RF-012-13"),
                                "Inward buffer of the limit"),
    ConstraintParam.WEIGHT: ("float", "-", 1.0, 1000.0, "HIPÓTESIS",
                             ("RF-012-02", "RF-012-04", "RF-012-22"),
                             "Weight of the area to avoid"),
    ConstraintParam.ACTIVE: ("bool", "-", None, None, "ADOPTADO",
                             ("RF-012-02", "RF-012-04", "RF-012-16"), "Constraint active"),
}


def _family(param: ConstraintParam) -> ParamFamily:
    value_type, unit, minimum, maximum, kind, rfs, label = _SPECS[param]
    template = ParamDef(f"{PREFIX}.c.{param.value}", value_type, unit, None, minimum, maximum,
                        rfs, _D5, allow_empty=True, kind=kind, source_kind="person",
                        scope="version", label_msgid=label)
    return ParamFamily(f"{PREFIX}.{{c}}.{param.value}", template)


_BY_PARAM: Mapping[ConstraintParam, ParamFamily] = {
    param: _family(param) for param in ConstraintParam
}

FAMILIES: tuple[ParamFamily, ...] = tuple(_BY_PARAM.values())
"""Las cuatro familias de una restricción (plan §5.2.2), sin valor por defecto, de versión."""

SEARCH_DISTANCE = ParamDef(
    "core.constraints.search_distance_m", "float", "m", 25.0, 0.0, 1000.0, ("RF-012-08",),
    _D5_SEARCH, min_exclusive=True, label_msgid="Search distance for untouchables")
"""La distancia de búsqueda de intocables (m): 25 m ADOPTADO «sin confirmar», del proyecto."""

DEFINITIONS: tuple[ParamDef, ...] = (SEARCH_DISTANCE,)
"""Los parámetros de las restricciones que no son de una familia."""


def family(param: ConstraintParam | str) -> ParamFamily:
    """La familia del parámetro ``param`` de una restricción."""
    return _BY_PARAM[ConstraintParam(param)]


def param_key(code: str, param: ConstraintParam | str) -> str:
    """La clave del parámetro ``param`` de la restricción ``code``
    (``core.constraint.torre_132.buffer_out_m``); :class:`ValueError` si el código no es
    ``[a-z][a-z0-9_]*`` (D-22; un error del programa)."""
    if not is_code(code):
        raise ValueError(f"el código {code!r} no es [a-z][a-z0-9_]* (D-22)")
    return f"{PREFIX}.{code}.{ConstraintParam(param).value}"


def buffer_out_key(code: str) -> str:
    """La clave del resguardo hacia fuera de la restricción ``code``."""
    return param_key(code, ConstraintParam.BUFFER_OUT)


def buffer_in_key(code: str) -> str:
    """La clave del resguardo hacia dentro del límite ``code``."""
    return param_key(code, ConstraintParam.BUFFER_IN)


def weight_key(code: str) -> str:
    """La clave del peso de la «preferible no afectar» ``code``."""
    return param_key(code, ConstraintParam.WEIGHT)


def active_key(code: str) -> str:
    """La clave de «activa» de la restricción ``code``."""
    return param_key(code, ConstraintParam.ACTIVE)
