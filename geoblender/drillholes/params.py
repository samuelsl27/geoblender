# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de los sondeos (spec 005, T20; RF-005-16, RF-005-26; plan 005 §5.2.4 y §5.6.3,
D-17 y D-18; ADR-0013; RF-008-01 a RF-008-06).

Cada valor que cambia un resultado de ``drillholes`` (los umbrales de la validación, el paso de
las trazas) o que fijará cómo se calcula después con los valores bajo el límite de detección es
un parámetro con **clave, tipo de valor, unidad, rango, valor por defecto, tipo y
procedencia**, declarado con el :class:`ParamDef` de ``core.params`` (spec 008), como
``gis.params``. Todos son ADOPTADO de origen ``algorithm``: los fija el método, no una medida ni
una norma. ``bl/ops/dh.py`` los registra en ``core.params`` (``register_definitions``) y los
quita con ``unregister_definitions("dh")``; en el proyecto quedan «sin confirmar» hasta que una
persona los confirma, y los cambia ``geoblender.core_set_parameter`` con su motivo (D-22).
Ninguna operación de la 005 cambia un parámetro (S-1 de la 008).

- Los cinco umbrales de la validación (:data:`VALIDATION_KEYS`; spec §11, D-6): sus nombres,
  sin el prefijo, son los campos de ``drillholes.validate.ValidationParams``, en su orden. Los
  lee ``dh.validate``; la tolerancia de profundidad, también ``dh.desurvey`` (las exclusiones de
  alcance S), con el paso de las trazas (:data:`DESURVEY_KEYS`). El cambio de dirección, en
  ``deg/30m`` («°/30 m», D-18).
- La regla de los valores bajo el límite de detección (RF-005-26; D-4: la mitad del límite),
  en dos claves porque un ``ParamDef`` no guarda un objeto (D-17; :data:`BELOW_DL_KEYS`):
  ``dh.below_dl.method``, un texto entre :data:`BELOW_DL_METHODS` (``factor``: el límite por el
  factor; ``limit``: el límite; ``zero``: 0; ``absent``: ausente), y ``dh.below_dl.factor``,
  la fracción del límite con ``factor``. No la lee ninguna operación de la 005 (la consumen
  R-14 y R-15): la primera importación la registra con ``ensure_default``, y cambiarla no
  altera ningún valor guardado ni deja obsoleto ningún dato de los sondeos.

Los rangos los decide esta definición (el plan solo fija los valores por defecto): el paso de
las trazas excluye el 0 (una polilínea necesita un paso positivo) y el factor va de 0 a 1.

- :data:`DEFINITIONS`, las del plan §5.6.3 en su orden, cada una con su etiqueta
  (``label_msgid``, con su español en ``core/i18n/messages.toml``) para el panel de parámetros
  (RF-008-06); :data:`PARAMS`, por clave (:func:`index_definitions`).
- :func:`param` y :func:`default`: la definición y el valor por defecto de una clave.

Python puro: solo ``core`` (ADR-0004); importarlo no registra nada.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from ..core.params import ParamDef, ParamValue
from ..core.units import DIMENSIONLESS

__all__ = [
    "BELOW_DL_FACTOR",
    "BELOW_DL_KEYS",
    "BELOW_DL_METHOD",
    "BELOW_DL_METHODS",
    "COLLAR_DEM_TOLERANCE",
    "DEFINITIONS",
    "DEPTH_TOLERANCE",
    "DESURVEY_KEYS",
    "DOGLEG_MAX",
    "GAP_TOLERANCE",
    "MIN_INTERVAL",
    "PARAMS",
    "ParamDef",
    "ParamValue",
    "TRACE_STEP",
    "VALIDATION_KEYS",
    "default",
    "index_definitions",
    "param",
]

DEPTH_TOLERANCE = "dh.validation.depth_tolerance_m"
"""Tolerancia de profundidad (m): DH-E07 y DH-E09."""
GAP_TOLERANCE = "dh.validation.gap_tolerance_m"
"""Hueco admitido entre tramos (m): DH-W01."""
MIN_INTERVAL = "dh.validation.min_interval_m"
"""Longitud mínima de un tramo (m): DH-W09."""
DOGLEG_MAX = "dh.validation.dogleg_max_deg_30m"
"""Cambio de dirección máximo entre estaciones (°/30 m): DH-W04."""
COLLAR_DEM_TOLERANCE = "dh.validation.collar_dem_tolerance_m"
"""Diferencia admitida entre la cota de la boca y el MDT (m): DH-W05."""
TRACE_STEP = "dh.desurvey.trace_step_m"
"""Separación máxima de los vértices de ``dh_trace`` y de la vista (m)."""
BELOW_DL_METHOD = "dh.below_dl.method"
"""Cómo se sustituye un valor bajo el límite en los cálculos posteriores."""
BELOW_DL_FACTOR = "dh.below_dl.factor"
"""La fracción del límite con la regla ``factor``."""

VALIDATION_KEYS: tuple[str, ...] = (DEPTH_TOLERANCE, GAP_TOLERANCE, MIN_INTERVAL, DOGLEG_MAX,
                                    COLLAR_DEM_TOLERANCE)
"""Los umbrales que lee ``dh.validate``, en el orden de los campos de ``ValidationParams``."""
DESURVEY_KEYS: tuple[str, ...] = (DEPTH_TOLERANCE, TRACE_STEP)
"""Los parámetros que lee ``dh.desurvey``."""
BELOW_DL_KEYS: tuple[str, ...] = (BELOW_DL_METHOD, BELOW_DL_FACTOR)
"""La regla de los valores bajo el límite de detección (RF-005-26; D-17)."""
BELOW_DL_METHODS: tuple[str, ...] = ("factor", "limit", "zero", "absent")
"""Las opciones de ``dh.below_dl.method``: el límite por el factor, el límite, 0 o ausente."""


def index_definitions(definitions: Iterable[ParamDef]) -> Mapping[str, ParamDef]:
    """Las definiciones por clave (solo lectura); :class:`ValueError` si una clave se repite
    (un duplicado no se pierde en silencio)."""
    index: dict[str, ParamDef] = {}
    for definition in definitions:
        if definition.key in index:
            raise ValueError(f"la clave de parámetro «{definition.key}» está repetida")
        index[definition.key] = definition
    return MappingProxyType(index)


_S11 = "Spec 005 §11 (D-6, DP-40): umbral por defecto de la validación"
_STEP = "Plan 005 §5.2.4: densificado de dh_trace y de la vista cada 2 m"
_D4 = "Spec 005, D-4 (DP-38): la mitad del límite de detección (LD/2); plan 005, D-17"

DEFINITIONS: tuple[ParamDef, ...] = (
    ParamDef(DEPTH_TOLERANCE, "float", "m", 0.01, 0.0, 1.0, ("RF-005-16", "RF-005-17"), _S11,
             label_msgid="Depth tolerance of the drillhole validation"),
    ParamDef(GAP_TOLERANCE, "float", "m", 0.01, 0.0, 1.0, ("RF-005-16",), _S11,
             label_msgid="Gap tolerance between drillhole intervals"),
    ParamDef(MIN_INTERVAL, "float", "m", 0.05, 0.0, 10.0, ("RF-005-16",), _S11,
             label_msgid="Minimum length of a drillhole interval"),
    ParamDef(DOGLEG_MAX, "float", "deg/30m", 3.0, 0.0, 180.0, ("RF-005-16",), _S11,
             label_msgid="Maximum change of direction between survey stations"),
    ParamDef(COLLAR_DEM_TOLERANCE, "float", "m", 2.0, 0.0, 100.0, ("RF-005-16", "RF-005-18"),
             _S11, label_msgid="Tolerance between collar elevation and terrain model"),
    ParamDef(TRACE_STEP, "float", "m", 2.0, 0.0, 100.0, ("RF-005-20", "RF-005-23"), _STEP,
             min_exclusive=True, label_msgid="Maximum vertex spacing of the drillhole traces"),
    ParamDef(BELOW_DL_METHOD, "text", DIMENSIONLESS, "factor", requirements=("RF-005-26",),
             source=_D4, choices=BELOW_DL_METHODS,
             label_msgid="Rule for values below the detection limit"),
    ParamDef(BELOW_DL_FACTOR, "float", DIMENSIONLESS, 0.5, 0.0, 1.0, ("RF-005-26",), _D4,
             label_msgid="Factor of the detection limit"),
)
"""Los parámetros de la tabla del plan 005 §5.6.3, en su orden."""

PARAMS: Mapping[str, ParamDef] = index_definitions(DEFINITIONS)
"""Las definiciones por clave (solo lectura)."""


def param(key: str) -> ParamDef:
    """La definición de ``key``; :class:`KeyError` si no es un parámetro de los sondeos (un
    error del programa)."""
    try:
        return PARAMS[key]
    except KeyError:
        raise KeyError(f"«{key}» no es un parámetro de los sondeos (drillholes/params.py)"
                       ) from None


def default(key: str) -> ParamValue:
    """El valor por defecto de ``key`` (ADOPTADO; ninguno admite «sin valor»)."""
    return param(key).default  # type: ignore[return-value]
