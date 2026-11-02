# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de las envolventes y el escalonado (spec 013; RF-013-08, RF-013-18, RF-013-27,
RF-013-30; plan 013 §5.2.2; D-4, D-7, D-17 y D-24; ADR-0027 y ADR-0029; RF-008-01 a RF-008-06).

Cada valor que cambia una cifra de ``design`` y no es un dato es un parámetro con **clave, tipo de
valor, unidad, rango, valor por defecto, tipo y procedencia**, declarado con el :class:`ParamDef`
de ``core.params`` (spec 008), como ``reserves.params``. Los de un perfil de banco y el del talud
de un sector son **familias** (:data:`FAMILIES`; ADR-0027) **de versión** (RF-009-24: la propiedad
cambia el talud de un sector, o un perfil, en una versión sin tocar las demás):

- ``des.bench.{p}.height_m``: la altura de banco *h*, m en (0; 100];
- ``des.bench.{p}.face_deg``: la inclinación máxima de la cara *α*, ° en (0; 90) (ambos extremos
  excluidos);
- ``des.bench.{p}.berm_m``: la berma mínima *B*, m en [0; 100];
- ``des.bench.{p}.anchor_m``: la cota de ancla *z₀*, m en [-1 000; 10 000];
- ``des.bench.{p}.mesh_factor``: el factor de malla, — en (0; 1], **1,0 ADOPTADO «sin confirmar»**
  (D-7: sin margen);
- ``des.sector.{s}.max_general_slope_deg``: el talud general máximo impuesto de un sector
  (RF-013-08; ADR-0029), ° en (0; 90).

La altura, la cara, la berma, el ancla y el talud impuesto **no tienen valor por defecto** (D-7:
un perfil por defecto es una cifra inventada, y ni los de ``EXPL_10_60_6`` son de Geoblender): los
declara una persona al crear o completar el perfil, o en «Sectores de diseño…», con su tipo
(HIPÓTESIS o ADOPTADO), su origen y su decisor. ``{p}`` es el código del perfil
(``des_bench_profile.code``, D-17) y ``{s}``, el código del sector o
:data:`~design.model.PERIMETER_SEGMENT` (``perimeter__``) para el perímetro como sector único
(D-23; el código es la clave, no el uid, que cambia en cada declaración).

Y los dos parámetros **del proyecto** (:data:`DEFINITIONS`), ADOPTADO «sin confirmar» de origen
``algorithm`` (D-7):

- ``des.tolerance.face_deg`` (:data:`TOLERANCE_FACE`; RF-013-27, RF-013-30): lo que puede pasar la
  inclinación de una celda de la cara del perfil antes de avisar, ° en (0; 10], 1,0 °;
- ``des.warning.magnitude_ratio`` (:data:`WARNING_RATIO`; RF-013-30): las veces que el desmonte o
  el terraplén pueden superar los de la revisión anterior antes de avisar, — en (1; 1 000], 2,0.

El espesor mínimo del informe es el de la 012, ``res.verify.min_thickness_m``
(:data:`VERIFY_MIN_THICKNESS`), que ``design`` lee **por su clave** con ``core.params`` sin
importar ``reserves`` (D-24); una prueba de arquitectura comprueba que sigue declarada.

**El 90 °.** ``ParamDef`` solo sabe excluir el mínimo de un rango; el máximo, no. Un ángulo de 0 a
90 ° ambos excluidos se declara con ``(0; 90]`` y :data:`RANGES` (:class:`ValueRange`) lleva el
rango completo, con el 90 excluido: es el que usan :func:`check_bench_value` y
:func:`check_sector_slope` (y el perfil, :class:`~design.model.BenchProfile`) antes de usar un
valor.

``bl`` registra :data:`DEFINITIONS` y :data:`FAMILIES` en ``core.params`` (``register_definitions``,
``register_families``) y las quita con ``unregister_definitions("des")`` y
``unregister_families("des")``. Python puro (nivel 8: ``core``); importarlo no registra nada.
"""

from __future__ import annotations

import math
import numbers
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ..core.params import ParamDef, ParamFamily, ParamValue, format_range
from .messages import DesignError

__all__ = [
    "DEFINITIONS",
    "FAMILIES",
    "PARAMS",
    "RANGES",
    "SECTOR_SLOPE",
    "TOLERANCE_FACE",
    "VERIFY_MIN_THICKNESS",
    "WARNING_RATIO",
    "BenchParam",
    "ParamDef",
    "ParamValue",
    "ValueRange",
    "bench_key",
    "check_bench_value",
    "check_sector_slope",
    "is_code",
    "sector_slope_key",
]

TOLERANCE_FACE = "des.tolerance.face_deg"
"""Tolerancia de cara (°): lo que la inclinación de una celda puede pasar de la cara del perfil."""
WARNING_RATIO = "des.warning.magnitude_ratio"
"""Umbral de aviso de magnitud (veces) frente a la revisión congelada anterior."""
VERIFY_MIN_THICKNESS = "res.verify.min_thickness_m"
"""El espesor mínimo del informe, de la 012: se lee por su clave, sin ``reserves`` (D-24)."""

SECTOR_SLOPE = "max_general_slope_deg"
"""El último segmento de la clave del talud general máximo impuesto de un sector."""


class BenchParam(StrEnum):
    """Los cinco valores de un perfil de banco: el último segmento de su clave
    ``des.bench.{p}.<valor>`` (RF-013-18)."""

    HEIGHT = "height_m"
    FACE = "face_deg"
    BERM = "berm_m"
    ANCHOR = "anchor_m"
    MESH_FACTOR = "mesh_factor"


@dataclass(frozen=True, slots=True)
class ValueRange:
    """El rango de un valor de ``design`` con sus dos extremos abiertos o cerrados (a diferencia
    de ``ParamDef``, que no puede excluir el máximo): ``minimum`` a ``maximum`` en ``unit``."""

    minimum: float
    maximum: float
    unit: str
    min_exclusive: bool = False
    max_exclusive: bool = False

    def contains(self, value: object) -> bool:
        """Si ``value`` es un número real finito dentro del rango (un booleano, un texto, NaN y
        el infinito no lo están)."""
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            return False
        number = float(value)
        if not math.isfinite(number):
            return False
        above = number > self.minimum if self.min_exclusive else number >= self.minimum
        below = number < self.maximum if self.max_exclusive else number <= self.maximum
        return above and below

    def text(self, language: str = "es") -> str:
        """El rango como se lee: ``(0; 90) °`` en español (``(0, 90) deg`` en inglés), con
        paréntesis en los extremos excluidos."""
        shown = format_range("float", self.unit, self.minimum, self.maximum,
                             min_exclusive=self.min_exclusive, language=language)
        return shown.replace("]", ")", 1) if self.max_exclusive else shown


RANGES: Mapping[str, ValueRange] = MappingProxyType({
    BenchParam.HEIGHT.value: ValueRange(0.0, 100.0, "m", min_exclusive=True),
    BenchParam.FACE.value: ValueRange(0.0, 90.0, "deg", min_exclusive=True, max_exclusive=True),
    BenchParam.BERM.value: ValueRange(0.0, 100.0, "m"),
    BenchParam.ANCHOR.value: ValueRange(-1000.0, 10000.0, "m"),
    BenchParam.MESH_FACTOR.value: ValueRange(0.0, 1.0, "-", min_exclusive=True),
    SECTOR_SLOPE: ValueRange(0.0, 90.0, "deg", min_exclusive=True, max_exclusive=True),
})
"""Los rangos de plan §5.2.2 por último segmento de la clave (solo lectura): la única fuente de
los de las familias y de lo que :func:`check_bench_value` y :func:`check_sector_slope` aceptan."""

_D4 = ("Spec 013, D-4 y ADR-0029: sin valor por defecto; lo declara una persona en «Sectores de "
       "diseño…» con su origen (la propiedad, un documento) y su decisor (Samuel, IMGA, "
       "02/11/2026)")
_D7 = ("Spec 013, D-7: sin valor por defecto; lo declara una persona con su tipo al crear o "
       "completar el perfil (Samuel, IMGA, 02/11/2026)")
_D7_MESH = ("Spec 013, D-7: 1,0, sin margen; el del proyecto de referencia (×0,93 a ×0,985) "
            "dependía del perfil y no se repite sin que alguien lo decida; sin confirmar "
            "(Samuel, IMGA, 02/11/2026)")
_D7_FACE = ("Spec 013, D-7: 1,0 °, el tolerancia_cara_malla_deg del proyecto de referencia; sin "
            "confirmar (Samuel, IMGA, 02/11/2026)")
_D7_RATIO = ("Spec 013, D-7: aviso con el doble de la revisión anterior; sin confirmar (Samuel, "
             "IMGA, 02/11/2026)")

_CODE = re.compile(r"[a-z][a-z0-9_]*")


def is_code(code: object) -> bool:
    """Si ``code`` es un código válido de perfil o de sector: ``[a-z][a-z0-9_]*`` (ASCII, en
    minúsculas; D-17, ADR-0027)."""
    return isinstance(code, str) and _CODE.fullmatch(code) is not None


def _definition(key: str, last: str, default: float | None, requirements: tuple[str, ...],
                source: str, label: str, *, kind: str, source_kind: str,
                scope: str) -> ParamDef:
    """El ``ParamDef`` de ``key`` con el rango de ``RANGES[last]`` (sin valor por defecto si
    ``default`` es ``None``)."""
    span = RANGES[last]
    return ParamDef(key, "float", span.unit, default, span.minimum, span.maximum, requirements,
                    source, min_exclusive=span.min_exclusive, allow_empty=default is None,
                    kind=kind, source_kind=source_kind, scope=scope, label_msgid=label)


def _bench_family(param: BenchParam, rfs: tuple[str, ...], label: str, *,
                  default: float | None = None) -> ParamFamily:
    """La familia ``des.bench.{p}.<param>`` (de versión), con la plantilla de clave
    ``des.bench.p.<param>``."""
    template = _definition(
        f"des.bench.p.{param.value}", param.value, default, rfs,
        _D7 if default is None else _D7_MESH, label,
        kind="HIPÓTESIS" if default is None else "ADOPTADO",
        source_kind="person" if default is None else "algorithm", scope="version")
    return ParamFamily(f"des.bench.{{p}}.{param.value}", template)


FAMILIES: tuple[ParamFamily, ...] = (
    _bench_family(BenchParam.HEIGHT, ("RF-013-18", "RF-013-22"), "Bench height"),
    _bench_family(BenchParam.FACE, ("RF-013-18", "RF-013-22"), "Face angle of the bench"),
    _bench_family(BenchParam.BERM, ("RF-013-18", "RF-013-25"), "Minimum berm width"),
    _bench_family(BenchParam.ANCHOR, ("RF-013-18", "RF-013-24"), "Anchor elevation"),
    _bench_family(BenchParam.MESH_FACTOR, ("RF-013-18", "RF-013-11"),
                  "Mesh factor of the profile", default=1.0),
    ParamFamily(f"des.sector.{{s}}.{SECTOR_SLOPE}", _definition(
        f"des.sector.s.{SECTOR_SLOPE}", SECTOR_SLOPE, None,
        ("RF-013-08", "RF-013-09", "RF-013-13", "RF-013-25"), _D4,
        "Maximum general slope imposed", kind="ADOPTADO", source_kind="person",
        scope="version")),
)
"""Las familias de plan §5.2.2: los cinco valores de un perfil y el talud impuesto de un sector,
todas de versión; sin valor por defecto salvo el factor de malla."""

DEFINITIONS: tuple[ParamDef, ...] = (
    ParamDef(TOLERANCE_FACE, "float", "deg", 1.0, 0.0, 10.0, ("RF-013-27", "RF-013-30"),
             _D7_FACE, min_exclusive=True, label_msgid="Tolerance on the face angle"),
    ParamDef(WARNING_RATIO, "float", "-", 2.0, 1.0, 1000.0, ("RF-013-30",), _D7_RATIO,
             min_exclusive=True,
             label_msgid="Warning threshold for cut and fill against the previous revision"),
)
"""Los parámetros del proyecto de plan §5.2.2, en su orden."""

PARAMS: Mapping[str, ParamDef] = MappingProxyType({item.key: item for item in DEFINITIONS})
"""Las definiciones del proyecto por clave (solo lectura)."""


def bench_key(code: str, param: BenchParam | str) -> str:
    """La clave del valor ``param`` del perfil ``code`` (``des.bench.expl_10_60_6.height_m``);
    :class:`ValueError` si el código no es ``[a-z][a-z0-9_]*`` (D-17) o ``param`` no es un valor de
    un perfil (un error del programa)."""
    if not is_code(code):
        raise ValueError(f"el código {code!r} no es [a-z][a-z0-9_]* (D-17)")
    return f"des.bench.{code}.{BenchParam(param).value}"


def sector_slope_key(segment: str) -> str:
    """La clave del talud general máximo impuesto del sector de código ``segment`` o, con
    :data:`~design.model.PERIMETER_SEGMENT`, del perímetro como sector único
    (``des.sector.sector_2.max_general_slope_deg``); :class:`ValueError` si no es
    ``[a-z][a-z0-9_]*`` (ADR-0029; un error del programa)."""
    if not is_code(segment):
        raise ValueError(f"el código de sector {segment!r} no es [a-z][a-z0-9_]* (ADR-0029)")
    return f"des.sector.{segment}.{SECTOR_SLOPE}"


def _real(value: object, what: str) -> float:
    """``value`` como ``float``; :class:`TypeError` si no es un número real (un booleano o un
    texto son un error del programa, no de la persona)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número real, no {value!r}")
    return float(value)


def check_bench_value(profile: str, code: str, param: BenchParam | str, value: object) -> float:
    """El valor ``param`` del perfil ``profile`` (su nombre, o su código si no lo tiene) de código
    ``code``, ya comprobado y como ``float``. :class:`~design.messages.DesignError`
    ``des.profile_value_missing`` si no tiene valor (``None``: no hay valor por defecto, D-7) o
    ``des.profile_value_range`` si está fuera de su rango (:data:`RANGES`), nombrando el perfil, la
    clave del campo y el valor; :class:`TypeError` si no es un número real."""
    param = BenchParam(param)
    key = bench_key(code, param)
    obj = f"Perfil de banco «{profile}»"
    if value is None:
        raise DesignError("des.profile_value_missing", obj=obj, field=key, value=None,
                          profile=profile)
    number = _real(value, f"el valor {key}")
    span = RANGES[param.value]
    if not span.contains(number):
        raise DesignError("des.profile_value_range", obj=obj, field=key, value=number,
                          profile=profile, range=span.text())
    return number


def check_sector_slope(sector: str, value: object) -> float:
    """El talud general máximo impuesto ``value`` (°) del sector de código ``sector``, ya
    comprobado y como ``float``. :class:`~design.messages.DesignError` ``des.sector_slope_range``
    si no está en (0; 90) °, nombrando el sector, la clave del campo y el valor;
    :class:`TypeError` si no es un número real; :class:`ValueError` si el código no es válido."""
    key = sector_slope_key(sector)
    number = _real(value, f"el talud de {key}")
    span = RANGES[SECTOR_SLOPE]
    if not span.contains(number):
        raise DesignError("des.sector_slope_range", obj=f"Sector «{sector}»", field=key,
                          value=number, sector=sector, range=span.text())
    return number
