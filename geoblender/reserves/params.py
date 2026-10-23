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
defecto, solo comprueba el rango, (0; 100] m (RF-008-03; plan §5.2.2 y A4). La densidad, el K y
los porcentajes de cada unidad son familias de parámetros (ADR-0027; T04 y T09), sin valor por
defecto (D-8).

- :data:`DEFINITIONS`, las del plan §5.2.2 en su orden, cada una con su etiqueta
  (``label_msgid``, con su español en ``core/i18n/messages.toml``) para el panel de parámetros
  (RF-008-06); :data:`PARAMS`, por clave (:func:`index_definitions`).
- :func:`param` y :func:`default`: la definición y el valor por defecto de una clave (también
  de la altura de banco).

``bl`` registra :data:`DEFINITIONS` en ``core.params`` (``register_definitions``) y las quita
con ``unregister_definitions("res")``. Python puro (nivel 9: ``core`` y ``gis``); importarlo no
registra nada.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..core.params import ParamDef, ParamValue
from ..gis.params import index_definitions

__all__ = [
    "ANTHROPIC_PRESENCE",
    "BENCH_HEIGHT",
    "BENCH_HEIGHT_DEF",
    "DEFINITIONS",
    "MIN_THICKNESS",
    "PARAMS",
    "ParamDef",
    "ParamValue",
    "STAGES_TOLERANCE",
    "default",
    "index_definitions",
    "param",
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
