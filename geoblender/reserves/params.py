# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de la cubicación (spec 011; RF-011-04, RF-011-09, RF-011-14, RF-011-19,
RF-011-21; plan 011 §5.2.2; ADR-0013; RF-008-01 a RF-008-06).

Cada valor que cambia una cifra de ``res`` y no es un dato es un parámetro con **clave, tipo
de valor, unidad, rango, valor por defecto, tipo y procedencia**, declarado con el
:class:`ParamDef` de ``core.params`` (spec 008), como ``gis.params``. Los tres del proyecto
son ADOPTADO de origen ``algorithm``, decididos por Samuel (IMGA) en las dudas de la spec, y
quedan «sin confirmar» en el proyecto hasta que una persona los confirma; los tres son **del
proyecto** (RF-011-21: el espesor mínimo y el umbral de presencia no cambian por versión):

- ``res.min_thickness_m`` (:data:`MIN_THICKNESS`; RF-011-04, D-6): el espesor mínimo, un
  **umbral** (la celda cuya diferencia no pasa de él no cuenta; la que pasa, cuenta entera),
  0 m en [0; 10] m: el volumen exacto.
- ``res.anthropic_presence_m`` (:data:`ANTHROPIC_PRESENCE`; RF-011-14, D-7): el umbral único
  de presencia de las unidades antrópicas (presente donde su espesor pasa de él), 0,30 m en
  [0; 10] m.
- ``res.stages_tolerance_pct`` (:data:`STAGES_TOLERANCE`; RF-011-19, D-14 e): la diferencia
  entre la suma de los momentos de extracción y la cubicación directa por encima de la cual
  se avisa, 1 % en (0; 100] %.

La altura de banco (``res.bench_height_m``, :data:`BENCH_HEIGHT`) **no** es un parámetro del
proyecto: las rodajas, el anclaje y la cota constante son ajustes de cada cubicación
(``gb_operation.settings``). Su :data:`BENCH_HEIGHT_DEF`, sin registrar y sin valor por
defecto, solo comprueba el rango, (0; 100] m (RF-008-03; plan §5.2.2 y A4).

La densidad in situ, el K y los porcentajes son **familias** de parámetros (:data:`FAMILIES`;
ADR-0027, D-17): una clave por unidad y por componente de la columna de materiales, con su
código inmutable (D-18), **sin valor por defecto** (D-8: una densidad supuesta acabaría en un
informe) y HIPÓTESIS hasta que una persona los declara (MEDIDO del ensayo, ADOPTADO o
HIPÓTESIS). La densidad es del proyecto; el K y los porcentajes, de versión (D-11, RF-011-21).

- ``res.unit.{u}.density`` y ``res.unit.{u}.{c}.density``: t/m³ en (0; 10] (una unidad que no
  es compuesta y cada componente; :func:`density_key`).
- ``res.unit.{u}.swell`` y ``res.unit.{u}.{c}.swell``: K (—) en [1; 3] (:func:`swell_key`).
- ``res.unit.{u}.{c}.percent``: el porcentaje de un componente en su unidad compuesta, % en
  [0; 100] (:func:`percent_key`; que sumen 100 lo comprueban las toneladas, RF-011-15).

- :data:`DEFINITIONS`, las del plan §5.2.2 en su orden, cada una con su etiqueta
  (``label_msgid``, con su español en ``core/i18n/messages.toml``) para el panel de parámetros
  (RF-008-06); :data:`PARAMS`, por clave (:func:`index_definitions`).
- :func:`param` y :func:`default`: la definición y el valor por defecto de una clave (también
  de la altura de banco).

``bl`` registra :data:`DEFINITIONS` y :data:`FAMILIES` en ``core.params``
(``register_definitions``, ``register_families``) y las quita con
``unregister_definitions("res")`` y ``unregister_families("res")``. Python puro (nivel 9:
``core`` y ``gis``); importarlo no registra nada.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..core.params import ParamDef, ParamFamily, ParamValue
from ..gis.params import index_definitions

__all__ = [
    "ANTHROPIC_PRESENCE",
    "BENCH_HEIGHT",
    "BENCH_HEIGHT_DEF",
    "DEFINITIONS",
    "FAMILIES",
    "MIN_THICKNESS",
    "PARAMS",
    "ParamDef",
    "ParamValue",
    "STAGES_TOLERANCE",
    "default",
    "density_key",
    "index_definitions",
    "param",
    "percent_key",
    "swell_key",
]

MIN_THICKNESS = "res.min_thickness_m"
"""Espesor mínimo (m): umbral del desmonte y del terraplén (RF-011-04)."""
ANTHROPIC_PRESENCE = "res.anthropic_presence_m"
"""Umbral único de presencia de las unidades antrópicas (m; RF-011-14)."""
STAGES_TOLERANCE = "res.stages_tolerance_pct"
"""Tolerancia de los momentos de extracción frente a la directa (%; RF-011-19)."""
BENCH_HEIGHT = "res.bench_height_m"
"""Altura de banco (m) de una cubicación por rodajas: un ajuste, no un parámetro (RF-011-09)."""

_D6 = "Spec 011, D-6: umbral, no resta; 0 m da el volumen exacto (Samuel, IMGA, 23/10/2026)"
_D7 = ("Spec 011, D-7: 0,30 m, el umbral de la mayoría de los cálculos del proyecto de "
       "referencia (N-12) (Samuel, IMGA, 23/10/2026)")
_D14 = ("Spec 011, D-14 (e): aviso por encima del 1 %, el criterio CA-12 del proyecto de "
        "referencia (Samuel, IMGA, 23/10/2026)")
_A4 = "Plan 011 §5.2.2 y A4: altura de banco en (0; 100] m, sin valor por defecto"

DEFINITIONS: tuple[ParamDef, ...] = (
    ParamDef(MIN_THICKNESS, "float", "m", 0.0, 0.0, 10.0, ("RF-011-04",), _D6,
             label_msgid="Minimum thickness of cut and fill"),
    ParamDef(ANTHROPIC_PRESENCE, "float", "m", 0.30, 0.0, 10.0, ("RF-011-14",), _D7,
             label_msgid="Presence threshold of anthropic units"),
    ParamDef(STAGES_TOLERANCE, "float", "%", 1.0, 0.0, 100.0, ("RF-011-19",), _D14,
             min_exclusive=True, label_msgid="Tolerance of the extraction stages"),
)
"""Los parámetros del proyecto de la tabla del plan 011 §5.2.2, en su orden."""

BENCH_HEIGHT_DEF = ParamDef(BENCH_HEIGHT, "float", "m", None, 0.0, 100.0, ("RF-011-09",), _A4,
                            min_exclusive=True, allow_empty=True, label_msgid="Bench height")
"""La altura de banco: comprueba el ajuste de una cubicación; **no se registra**."""

PARAMS: Mapping[str, ParamDef] = index_definitions(DEFINITIONS)
"""Las definiciones del proyecto por clave (solo lectura)."""

_D8 = ("Spec 011, D-8: sin valor por defecto; lo declara una persona con su tipo (MEDIDO del "
       "ensayo, ADOPTADO o HIPÓTESIS) (Samuel, IMGA, 23/10/2026)")
_DENSITY_LABEL = "In-situ density"
_SWELL_LABEL = "Swell factor"
_PERCENT_LABEL = "Share of the component"
_UNIT_RFS = ("RF-011-11", "RF-011-16", "RF-011-17")
_COMPONENT_RFS = ("RF-011-15", "RF-011-16", "RF-011-17")
_VERSION_RF = ("RF-011-21",)


def _family(pattern: str, unit: str, minimum: float, maximum: float, rfs: tuple[str, ...],
            label: str, *, scope: str, min_exclusive: bool = False) -> ParamFamily:
    """Una familia sin valor por defecto (D-8), HIPÓTESIS, cuya plantilla tiene la clave del
    patrón con cada variable por su nombre (``res.unit.u.density``)."""
    template = ParamDef(pattern.replace("{", "").replace("}", ""), "float", unit, None, minimum,
                        maximum, rfs, _D8, min_exclusive=min_exclusive, allow_empty=True,
                        kind="HIPÓTESIS", source_kind="person", scope=scope,
                        label_msgid=label)
    return ParamFamily(pattern, template)


FAMILIES: tuple[ParamFamily, ...] = (
    _family("res.unit.{u}.density", "t/m3", 0.0, 10.0, _UNIT_RFS, _DENSITY_LABEL,
            scope="project", min_exclusive=True),
    _family("res.unit.{u}.swell", "-", 1.0, 3.0, _UNIT_RFS + _VERSION_RF, _SWELL_LABEL,
            scope="version"),
    _family("res.unit.{u}.{c}.density", "t/m3", 0.0, 10.0, _COMPONENT_RFS, _DENSITY_LABEL,
            scope="project", min_exclusive=True),
    _family("res.unit.{u}.{c}.swell", "-", 1.0, 3.0, _COMPONENT_RFS + _VERSION_RF, _SWELL_LABEL,
            scope="version"),
    _family("res.unit.{u}.{c}.percent", "%", 0.0, 100.0, ("RF-011-15", *_VERSION_RF),
            _PERCENT_LABEL, scope="version"),
)
"""Las familias de la columna de materiales (plan §5.2.2; ADR-0027), sin valor por defecto."""

_CODE = re.compile(r"[a-z][a-z0-9_]*")


def _element(unit: str, component: str | None) -> str:
    """``res.unit.<unidad>[.<componente>]``; :class:`ValueError` si un código no vale."""
    codes = (unit,) if component is None else (unit, component)
    for code in codes:
        if not isinstance(code, str) or _CODE.fullmatch(code) is None:
            raise ValueError(f"el código {code!r} no es [a-z][a-z0-9_]* (D-18)")
    return "res.unit." + ".".join(codes)


def density_key(unit: str, component: str | None = None) -> str:
    """La clave de la densidad in situ de la unidad ``unit`` o de su componente
    ``component`` (por sus códigos): ``res.unit.capa_util.caliza.density``."""
    return _element(unit, component) + ".density"


def swell_key(unit: str, component: str | None = None) -> str:
    """La clave del K de la unidad ``unit`` o de su componente ``component``."""
    return _element(unit, component) + ".swell"


def percent_key(unit: str, component: str) -> str:
    """La clave del porcentaje del componente ``component`` en su unidad compuesta ``unit``."""
    return _element(unit, component) + ".percent"

_ALL: Mapping[str, ParamDef] = index_definitions((*DEFINITIONS, BENCH_HEIGHT_DEF))


def param(key: str) -> ParamDef:
    """La definición de ``key`` (una de :data:`PARAMS` o la altura de banco);
    :class:`KeyError` si no es un parámetro de la cubicación (un error del programa)."""
    try:
        return _ALL[key]
    except KeyError:
        raise KeyError(f"«{key}» no es un parámetro de la cubicación (reserves/params.py)"
                       ) from None


def default(key: str) -> ParamValue | None:
    """El valor por defecto de ``key`` (ADOPTADO; ``None`` en la altura de banco, que no
    tiene)."""
    return param(key).default
