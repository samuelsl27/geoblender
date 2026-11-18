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

Y los siete de la cantera con dos superficies (spec 014, T02; plan 014 §5.2.2;
:data:`QUARRY_DEFINITIONS`, por clave en :data:`QUARRY_PARAMS`; aparte de :data:`DEFINITIONS`),
**de versión**, con sus rangos en :data:`QUARRY_RANGES` y su comprobación en
:func:`check_quarry_param`:

- ``des.quarry.crown_ring_cells`` (:data:`CROWN_RING`; RF-014-02): el anillo de coronación,
  entero en [1; 50] celdas, **3** ADOPTADO «sin confirmar» (D-7 de la 014);
- ``des.quarry.unsplit_threshold_m`` y ``des.quarry.unsplit_min_area_ha`` (RF-014-17): el aviso
  de «explotación hasta la final», m en (0; 100] y ha en (0; 1 000], **1,0 m** y **0,2 ha**
  ADOPTADO «sin confirmar» (D-5);
- ``des.edge.max_created_step_m`` y ``des.edge.min_share`` (RF-014-21): el salto creado
  admitido, m en (0; 100], y el porcentaje de parejas del borde dentro de él, % en (0; 100],
  **1,0 m** y **99 %** ADOPTADO «sin confirmar» (D-6);
- ``des.edge.transition_deg`` (RF-014-19) y ``des.conserve.slope_deg`` (RF-014-07): ° en (0; 90)
  (ambos excluidos), ADOPTADO **sin valor** (D-9: los declara una persona).

El umbral «sin explotar» de RF-014-17 (0,3 m) no es un parámetro: es la definición de la spec.

Y los de una entidad de diseño (spec 015, T02; plan 015 §5.2.2; ADR-0027 y ADR-0030): la
definición de una **plataforma** son sus parámetros de versión, 20 **familias**
``des.platform.{e}.<valor>`` (:data:`ENTITY_FAMILIES`, aparte de :data:`FAMILIES`; sus plantillas por
valor en :data:`PLATFORM_PARAMS`, sus rangos en :data:`ENTITY_RANGES`, su comprobación en
:func:`check_entity_param`). ``{e}`` es el código de la entidad (``PLT-001``) como segmento de clave
(:func:`entity_segment`: ``plt_001``). Sin valor por defecto (lo declara una persona al crear la
entidad, ADOPTADO): el nombre, la capa, la geometría, la partida y el apoyo, el ancho, la cota
inicial y la pendiente de la rasante (``start_level_m`` y ``gradient_pct``, como en el glosario
§14), la pendiente máxima (opcional, D-6), el ángulo de borde (D-7), el alcance (D-20), el
resguardo (D-19), el motivo y las dependencias declaradas. Con valor, ADOPTADO «sin confirmar»: el
modo «en corte» (D-5), el factor de malla 1,0 (D-7), la tolerancia de contrapendiente 0,1 m (D-8),
la métrica exacta (D-22), «no proteger» (D-4) y «no descartada» (``discarded``, T25: RF-015-17, D-12; la
persona lo pone en verdadero para descartar una entidad **sin calcular**, que no tiene datos que
descartar: nada se borra, RF-009-12; una calculada se descarta con sus datos).

**Más de un tipo de entidad** (spec 016, T02; plan 016 §5.1 y §5.7 P-11; ADR-0031 §1): la plataforma es un tipo
entre varios y su familia es la de su tipo. :class:`EntityParams` dice de cada tipo su **valor** (el segmento
``des.<tipo>.{e}.*`` de su clave), el **prefijo de su código** (``PLT``), los **valores** de su familia
(:data:`COMMON_ENTITY_PARAMS`, los comunes a todos los tipos, y los propios) y las familias que ``bl`` registra;
:func:`register_entity_params` y :func:`unregister_entity_params` son su registro (la plataforma es del programa y no se
quita; los demás, de quien los declara), :func:`entity_params` y :func:`entity_params_of` lo consultan por tipo y por
código, :func:`entity_key` da la clave de un valor en la familia **del tipo de su código** y :func:`parse_entity_key` la
lee de vuelta. :func:`entity_family` construye las familias de cualquier tipo (con la misma plantilla que las de la
plataforma). Un tipo **sin** ``start`` es un tipo **sin cadena** (:attr:`EntityParams.chained`): no parte de ninguna
superficie ni nadie parte de la suya (``design.entities``). La plataforma no cambia de claves, de plantillas ni de
rangos.

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
    "COMMON_ENTITY_PARAMS",
    "CONSERVE_SLOPE",
    "CROWN_RING",
    "DEFINITIONS",
    "EDGE_MAX_STEP",
    "EDGE_MIN_SHARE",
    "EDGE_TRANSITION",
    "ENTITY_FAMILIES",
    "ENTITY_RANGES",
    "FAMILIES",
    "PARAMS",
    "PLATFORM_PARAMS",
    "QUARRY_DEFINITIONS",
    "QUARRY_PARAMS",
    "QUARRY_RANGES",
    "RANGES",
    "SECTOR_SLOPE",
    "TOLERANCE_FACE",
    "UNSPLIT_MIN_AREA",
    "UNSPLIT_THRESHOLD",
    "VERIFY_MIN_THICKNESS",
    "WARNING_RATIO",
    "BenchParam",
    "EntityParams",
    "ParamDef",
    "ParamValue",
    "PlatformParam",
    "ValueRange",
    "bench_key",
    "check_bench_value",
    "check_entity_param",
    "check_quarry_param",
    "check_sector_slope",
    "entity_family",
    "entity_key",
    "entity_params",
    "entity_params_of",
    "entity_segment",
    "is_code",
    "parse_entity_key",
    "register_entity_params",
    "registered_entity_params",
    "sector_slope_key",
    "segment_code",
    "unregister_entity_params",
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
    de ``ParamDef``, que no puede excluir el máximo): ``minimum`` a ``maximum`` en ``unit``; un
    extremo infinito (``-inf`` o ``inf``) es un extremo sin tope."""

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
        paréntesis en los extremos excluidos y ``±∞`` en el extremo infinito (``(0; +∞) %``)."""
        shown = format_range("float", self.unit,
                             None if self.minimum == -math.inf else self.minimum,
                             None if self.maximum == math.inf else self.maximum,
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

_014_D7 = ("Spec 014, D-7: 3 celdas, el anillo de la V7 y la V8 del proyecto de referencia; sin "
           "confirmar (Samuel, IMGA, 12/11/2026)")
_014_D5 = ("Spec 014, D-5: 1 m de desdoblado en zonas de 0,2 ha, del error 60 del proyecto de "
           "referencia; sin confirmar (Samuel, IMGA, 12/11/2026)")
_014_D6 = ("Spec 014, D-6: un salto creado de 1 m en al menos el 99 % de las parejas del borde "
           "(CA-11); solo avisa; sin confirmar (Samuel, IMGA, 12/11/2026)")
_014_D9 = ("Spec 014, D-9: sin valor por defecto (como D-7 de la 013); lo declara una persona "
           "con su origen y su decisor; el análisis usó 35° (Samuel, IMGA, 12/11/2026)")

CROWN_RING = "des.quarry.crown_ring_cells"
"""Ancho del anillo de coronación (celdas; RF-014-02)."""
UNSPLIT_THRESHOLD = "des.quarry.unsplit_threshold_m"
"""Desdoblado (m) a partir del cual se avisa de que la explotación no llega a la final
(RF-014-17)."""
UNSPLIT_MIN_AREA = "des.quarry.unsplit_min_area_ha"
"""Área mínima (ha) de una zona de desdoblado que se avisa (RF-014-17)."""
EDGE_MAX_STEP = "des.edge.max_created_step_m"
"""Salto creado admitido (m) en una pareja del borde (RF-014-21)."""
EDGE_MIN_SHARE = "des.edge.min_share"
"""Porcentaje de las parejas del borde que tiene que quedar dentro del salto admitido
(RF-014-21)."""
EDGE_TRANSITION = "des.edge.transition_deg"
"""Ángulo de transición con el terreno no afectado (°; RF-014-19; sin valor por defecto)."""
CONSERVE_SLOPE = "des.conserve.slope_deg"
"""Talud de conservación (°; RF-014-07; sin valor por defecto)."""

QUARRY_RANGES: Mapping[str, ValueRange] = MappingProxyType({
    CROWN_RING: ValueRange(1, 50, "-"),
    UNSPLIT_THRESHOLD: ValueRange(0.0, 100.0, "m", min_exclusive=True),
    UNSPLIT_MIN_AREA: ValueRange(0.0, 1000.0, "ha", min_exclusive=True),
    EDGE_MAX_STEP: ValueRange(0.0, 100.0, "m", min_exclusive=True),
    EDGE_MIN_SHARE: ValueRange(0.0, 100.0, "%", min_exclusive=True),
    EDGE_TRANSITION: ValueRange(0.0, 90.0, "deg", min_exclusive=True, max_exclusive=True),
    CONSERVE_SLOPE: ValueRange(0.0, 90.0, "deg", min_exclusive=True, max_exclusive=True),
})
"""Los rangos de los parámetros de la 014 (plan 014 §5.2.2) por clave, en su orden (solo
lectura): la única fuente de los de :data:`QUARRY_DEFINITIONS` y de lo que
:func:`check_quarry_param` acepta (con el 90° excluido que ``ParamDef`` no puede decir)."""


def _quarry(key: str, value_type: str, default: float | None, requirements: tuple[str, ...],
            source: str, label: str) -> ParamDef:
    """El ``ParamDef`` de versión de ``key`` con el rango de :data:`QUARRY_RANGES`: ADOPTADO
    «sin confirmar» (origen ``algorithm``) con valor por defecto, o ADOPTADO sin valor que
    declara una persona (origen ``person``)."""
    span = QUARRY_RANGES[key]
    return ParamDef(key, value_type, span.unit, default, span.minimum, span.maximum,
                    requirements, source, min_exclusive=span.min_exclusive,
                    allow_empty=default is None, kind="ADOPTADO",
                    source_kind="person" if default is None else "algorithm", scope="version",
                    label_msgid=label)


QUARRY_DEFINITIONS: tuple[ParamDef, ...] = (
    _quarry(CROWN_RING, "int", 3, ("RF-014-02",), _014_D7, "Width of the crown ring"),
    _quarry(UNSPLIT_THRESHOLD, "float", 1.0, ("RF-014-17",), _014_D5,
            "Unsplit depth of the warning"),
    _quarry(UNSPLIT_MIN_AREA, "float", 0.2, ("RF-014-17",), _014_D5,
            "Minimum area of a warned unsplit zone"),
    _quarry(EDGE_MAX_STEP, "float", 1.0, ("RF-014-21",), _014_D6,
            "Admitted created step at the edge"),
    _quarry(EDGE_MIN_SHARE, "float", 99.0, ("RF-014-21",), _014_D6,
            "Share of edge pairs within the admitted step"),
    _quarry(EDGE_TRANSITION, "float", None, ("RF-014-19",), _014_D9,
            "Transition angle with the untouched terrain"),
    _quarry(CONSERVE_SLOPE, "float", None, ("RF-014-07",), _014_D9, "Conservation slope"),
)
"""Los siete parámetros de la 014 (plan 014 §5.2.2), de versión, en su orden. Van aparte de
:data:`DEFINITIONS` (los de la 013, que su documentación describe): ``bl`` los registra junto a
ellos cuando registre las operaciones de la 014."""

QUARRY_PARAMS: Mapping[str, ParamDef] = MappingProxyType(
    {item.key: item for item in QUARRY_DEFINITIONS})
"""Los parámetros de la 014 por clave (solo lectura)."""

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


def check_quarry_param(key: str, value: object) -> float | int:
    """El valor ``value`` del parámetro de la 014 ``key`` (:data:`QUARRY_DEFINITIONS`), ya
    comprobado: ``int`` el anillo de coronación y ``float`` los demás.
    :class:`~design.messages.DesignError` ``des.quarry_param_missing`` si no tiene valor
    (``None``: la transición y la conservación no tienen valor por defecto, D-9) o
    ``des.quarry_param_range`` si está fuera de su rango (:data:`QUARRY_RANGES`, con el 90°
    excluido), nombrando la clave y el valor; :class:`TypeError` si no es un número (o, en el
    anillo, un entero); :class:`ValueError` si ``key`` no es de la 014 (errores del programa)."""
    span = QUARRY_RANGES.get(key)
    if span is None:
        raise ValueError(f"«{key}» no es un parámetro de la 014 (plan 014 §5.2.2)")
    obj = "Parámetros del proyecto"
    if value is None:
        raise DesignError("des.quarry_param_missing", obj=obj, field=key, value=None)
    number: float | int
    if QUARRY_PARAMS[key].value_type == "int":
        if isinstance(value, bool) or not isinstance(value, numbers.Integral):
            raise TypeError(f"el valor {key} es un número entero, no {value!r}")
        number = int(value)
    else:
        number = _real(value, f"el valor {key}")
    if not span.contains(number):
        raise DesignError("des.quarry_param_range", obj=obj, field=key, value=number,
                          range=span.text())
    return number


# --- Las entidades de diseño (spec 015, T02; plan 015 §5.2.2; ADR-0027, ADR-0030) ----------------

PLATFORM_PREFIX = "des.platform"
"""El principio de la clave de un parámetro de una plataforma: ``des.platform.{e}.<valor>``."""
_ENTITY_CODE = re.compile(r"[A-Z]{2,5}-[0-9]{3,}")
_ENTITY_SEGMENT = re.compile(r"[a-z]{2,5}_[0-9]{3,}")


class PlatformParam(StrEnum):
    """Los 20 valores de una plataforma: el último segmento de su clave
    ``des.platform.{e}.<valor>`` (plan 015 §5.2.2), en su orden."""

    NAME = "name"
    LAYER = "layer"
    FEATURE = "feature"
    START = "start"
    SUPPORT = "support"
    WIDTH = "width_m"
    START_LEVEL = "start_level_m"
    GRADIENT = "gradient_pct"
    MAX_SLOPE = "max_slope_pct"
    MODE = "mode"
    EDGE_ANGLE = "edge_angle_deg"
    REACH = "reach_m"
    MESH_FACTOR = "mesh_factor"
    COUNTER_TOL = "counter_tol_m"
    METRIC = "metric"
    PROTECT = "protect"
    GUARD = "guard_m"
    REASON = "reason"
    SUPPORTS = "supports"
    DISCARDED = "discarded"


COMMON_ENTITY_PARAMS: tuple[str, ...] = (
    PlatformParam.NAME.value, PlatformParam.START.value, PlatformParam.SUPPORT.value,
    PlatformParam.SUPPORTS.value, PlatformParam.DISCARDED.value, PlatformParam.PROTECT.value,
    PlatformParam.GUARD.value, PlatformParam.REASON.value)
"""Los valores **comunes a todos los tipos de entidad** (plan 016 §5.2.2): los de la 015 que no son de la geometría de
la plataforma (``name``, ``start``, ``support``, ``supports``, ``discarded``, ``protect``, ``guard_m`` y ``reason``),
bajo el prefijo de cada tipo (P-11). Un tipo sin cadena no tiene ``start``."""

_OPTIONAL = frozenset({PlatformParam.SUPPORT, PlatformParam.MAX_SLOPE, PlatformParam.REASON,
                       PlatformParam.SUPPORTS})
"""Los valores que pueden quedarse sin valor: la superficie de apoyo («si la hay»), la pendiente
máxima (opcional, D-6), el motivo (el generado, editable) y las dependencias declaradas (vacío)."""

_INF = math.inf
ENTITY_RANGES: Mapping[str, ValueRange] = MappingProxyType({
    PlatformParam.WIDTH.value: ValueRange(0.0, 1000.0, "m", min_exclusive=True),
    PlatformParam.START_LEVEL.value: ValueRange(-_INF, _INF, "m"),
    PlatformParam.GRADIENT.value: ValueRange(-_INF, _INF, "%"),
    PlatformParam.MAX_SLOPE.value: ValueRange(0.0, _INF, "%", min_exclusive=True),
    PlatformParam.EDGE_ANGLE.value: ValueRange(0.0, 90.0, "deg", min_exclusive=True,
                                               max_exclusive=True),
    PlatformParam.REACH.value: ValueRange(0.0, 10000.0, "m", min_exclusive=True),
    PlatformParam.MESH_FACTOR.value: ValueRange(0.0, 1.0, "-", min_exclusive=True),
    PlatformParam.COUNTER_TOL.value: ValueRange(0.0, 10.0, "m"),
    PlatformParam.GUARD.value: ValueRange(0.0, 1000.0, "m"),
})
"""Los rangos de los valores numéricos de una plataforma (plan 015 §5.2.2) por último segmento de
la clave (solo lectura): la única fuente de los de :data:`ENTITY_FAMILIES` y de lo que
:func:`check_entity_param` acepta (con el 90° excluido que ``ParamDef`` no puede decir). El factor de malla es
de (0; 1], como el de la 013 (T45, hallazgo D-3: con más de 1 la envolvente sería más empinada que el
ángulo de borde por construcción y toda su pared saldría como «no debería haber»)."""

_015_NAME = ("Spec 015, RF-015-01: sin valor por defecto; lo elige una persona al crear la entidad "
             "(Samuel, IMGA, 14/11/2026)")
_015_START = ("Spec 015, RF-015-04: sin valor por defecto; la superficie de partida (el terreno, "
              "una de diseño o una entidad) la elige una persona al crear la entidad, y la de "
              "apoyo, si la hay (Samuel, IMGA, 14/11/2026)")
_015_D15 = ("Spec 015, D-15 (el ancho de un corredor de la 014): sin valor por defecto; lo copia "
            "una persona al crear la entidad, con su origen (la capa y el campo) (Samuel, IMGA, "
            "14/11/2026)")
_015_D6 = ("Spec 015, D-6: sin valor por defecto, una pendiente constante por plataforma; lo "
           "declara una persona al crear la entidad, con su origen (la capa y el campo, o una "
           "persona) y su decisor (Samuel, IMGA, 14/11/2026)")
_015_D6_MAX = ("Spec 015, D-6: opcional y sin valor por defecto; si se fija y la rasante la pasa, "
               "es una rampa y se rechaza (Samuel, IMGA, 14/11/2026)")
_015_D5 = ("Spec 015, D-5: «en corte» por defecto (la plataforma es el fondo de su corredor, B7); "
           "sin confirmar (Samuel, IMGA, 14/11/2026)")
_015_D7_ANGLE = ("Spec 015, D-7: sin valor por defecto, el ángulo de borde es propio de cada "
                 "plataforma (en el proyecto de referencia, 35°) (Samuel, IMGA, 14/11/2026)")
_015_D20 = ("Spec 015, D-20: obligatorio y sin valor por defecto: sin tope, en una ladera más "
            "empinada que el ángulo de borde la envolvente cortaría toda la ladera (Samuel, "
            "IMGA, 14/11/2026)")
_015_D7_MESH = ("Spec 015, D-7: 1,0, como el factor de malla de la 013 (sin margen); sin "
                "confirmar (Samuel, IMGA, 14/11/2026)")
_015_D8 = ("Spec 015, D-8: 0,1 m, la tolerancia de la solera del canal (error 21, R-37), no la de "
           "una plataforma; sin confirmar (Samuel, IMGA, 14/11/2026)")
_015_D22 = ("Spec 015, D-22: la euclídea exacta (RF-013-12), decidida por la sesión principal; "
            "revisable (14/11/2026)")
_015_D4 = ("Spec 015, D-4: la plataforma no declara nada por defecto; «proteger» (sin relleno) se "
           "elige con motivo; sin confirmar (Samuel, IMGA, 14/11/2026)")
_015_D19 = ("Spec 015, D-19: obligatorio y sin valor por defecto, como todo resguardo de la 012 "
            "(RF-012-02: un resguardo por defecto es una distancia de seguridad inventada) "
            "(Samuel, IMGA, 14/11/2026)")
_015_REASON = ("Spec 015, RF-015-10: el motivo generado («declarada por la plataforma P1»), que "
               "la persona puede editar en la entidad (Samuel, IMGA, 14/11/2026)")
_015_SUPPORTS = ("Spec 015, RF-015-15: las entidades en las que la persona declara que se apoya; "
                 "vacío por defecto (Samuel, IMGA, 14/11/2026)")
_015_DISCARDED = ("Spec 015, RF-015-17 y D-12: falso por defecto; la persona lo pone en verdadero para "
                  "descartar una entidad sin calcular («registro, no usar»: nada se borra, RF-009-12); "
                  "decidido por la sesión principal (15/11/2026), revisable")

_MODE_CHOICES = ("cut", "cut_fill")
_METRIC_CHOICES = ("exact", "chamfer5")

_ENTITY_SPECS: tuple[tuple[PlatformParam, str, ParamValue | None, tuple[str, ...],
                           tuple[str, ...], str, str], ...] = (
    (PlatformParam.NAME, "text", None, (), ("RF-015-01",), _015_NAME, "Name of the entity"),
    (PlatformParam.LAYER, "text", None, (), ("RF-015-01",), _015_NAME,
     "Layer the entity comes from"),
    (PlatformParam.FEATURE, "text", None, (), ("RF-015-01",), _015_NAME,
     "Feature of the layer the entity comes from"),
    (PlatformParam.START, "text", None, (), ("RF-015-04", "RF-015-05"), _015_START,
     "Start surface of the entity"),
    (PlatformParam.SUPPORT, "text", None, (), ("RF-015-04", "RF-015-05"), _015_START,
     "Support surface of the entity"),
    (PlatformParam.WIDTH, "float", None, (), ("RF-015-19",), _015_D15, "Width of the platform"),
    (PlatformParam.START_LEVEL, "float", None, (), ("RF-015-19",), _015_D6,
     "Start level of the platform"),
    (PlatformParam.GRADIENT, "float", None, (), ("RF-015-19",), _015_D6,
     "Gradient of the platform"),
    (PlatformParam.MAX_SLOPE, "float", None, (), ("RF-015-08",), _015_D6_MAX,
     "Maximum gradient of the platform"),
    (PlatformParam.MODE, "text", "cut", _MODE_CHOICES, ("RF-015-20", "RF-015-21"), _015_D5,
     "Mode of the platform"),
    (PlatformParam.EDGE_ANGLE, "float", None, (), ("RF-015-22",), _015_D7_ANGLE,
     "Edge angle of the platform"),
    (PlatformParam.REACH, "float", None, (), ("RF-015-22",), _015_D20,
     "Reach of the platform edge"),
    (PlatformParam.MESH_FACTOR, "float", 1.0, (), ("RF-015-22",), _015_D7_MESH,
     "Mesh factor of the platform edge"),
    (PlatformParam.COUNTER_TOL, "float", 0.1, (), ("RF-015-23",), _015_D8,
     "Counter-gradient tolerance of the platform"),
    (PlatformParam.METRIC, "text", "exact", _METRIC_CHOICES, ("RF-015-22",), _015_D22,
     "Distance metric of the platform edge"),
    (PlatformParam.PROTECT, "bool", False, (), ("RF-015-10", "RF-015-12"), _015_D4,
     "The platform protects its area"),
    (PlatformParam.GUARD, "float", None, (), ("RF-015-10", "RF-015-12"), _015_D19,
     "Buffer of the protected area"),
    (PlatformParam.REASON, "text", None, (), ("RF-015-10", "RF-015-12"), _015_REASON,
     "Reason of the declared constraint"),
    (PlatformParam.SUPPORTS, "text", None, (), ("RF-015-15",), _015_SUPPORTS,
     "Entities the platform is declared to rest on"),
    (PlatformParam.DISCARDED, "bool", False, (), ("RF-015-17",), _015_DISCARDED,
     "The entity is discarded"),
)


def entity_family(prefix: str, param: str, value_type: str, default: ParamValue | None,
                  choices: tuple[str, ...], rfs: tuple[str, ...], source: str, label: str, *,
                  span: ValueRange | None = None, scope: str = "version") -> ParamFamily:
    """La familia ``<prefix>.{e}.<param>`` de un tipo de entidad (``prefix``: ``des.platform``, ``des.stockpile``…;
    spec 016, T02) con la plantilla de clave ``<prefix>.e.<param>``: el rango ``span`` (sin tope en un extremo
    infinito), ADOPTADO «sin confirmar» de origen ``algorithm`` con valor por defecto, o ADOPTADO sin valor que
    declara una persona (origen ``person``), de ``scope`` de versión (por defecto) o de proyecto. Es la
    construcción de las 20 familias de la plataforma, sin cambiar nada de ellas."""
    unit = "-" if span is None else span.unit
    minimum = None if span is None or span.minimum == -math.inf else span.minimum
    maximum = None if span is None or span.maximum == math.inf else span.maximum
    template = ParamDef(
        f"{prefix}.e.{param}", value_type, unit, default, minimum, maximum, rfs,
        source, min_exclusive=span is not None and span.min_exclusive, allow_empty=default is None,
        choices=choices, kind="ADOPTADO", source_kind="person" if default is None else "algorithm",
        scope=scope, label_msgid=label)
    return ParamFamily(f"{prefix}.{{e}}.{param}", template)


def _entity_family(param: PlatformParam, value_type: str, default: ParamValue | None,
                   choices: tuple[str, ...], rfs: tuple[str, ...], source: str,
                   label: str) -> ParamFamily:
    """La familia ``des.platform.{e}.<param>`` (de versión) con el rango de :data:`ENTITY_RANGES`."""
    return entity_family(PLATFORM_PREFIX, param.value, value_type, default, choices, rfs, source, label,
                         span=ENTITY_RANGES.get(param.value))


ENTITY_FAMILIES: tuple[ParamFamily, ...] = tuple(_entity_family(*spec) for spec in _ENTITY_SPECS)
"""Las 20 familias de una plataforma (plan 015 §5.2.2 y T25), de versión, en su orden. Van aparte de
:data:`FAMILIES` (las de la 013): ``bl`` las registra junto a ellas cuando registre las operaciones
de la 015 (T04)."""

PLATFORM_PARAMS: Mapping[str, ParamDef] = MappingProxyType(
    {PlatformParam(family.pattern.rsplit(".", 1)[1]).value: family.template
     for family in ENTITY_FAMILIES})
"""Las plantillas de las 20 familias por último segmento de la clave (solo lectura)."""


def entity_segment(code: str) -> str:
    """El código de una entidad como segmento de clave de un parámetro: ``PLT-001`` →
    ``plt_001`` (un segmento es ``[a-z][a-z0-9_]*``, ADR-0027). :class:`TypeError` si no es un
    texto; :class:`ValueError` si no es un código de entidad (``[A-Z]{2,5}-[0-9]{3,}``): un error
    del programa."""
    if not isinstance(code, str):
        raise TypeError(f"el código de una entidad es un texto, no {code!r}")
    if _ENTITY_CODE.fullmatch(code) is None:
        raise ValueError(f"el código {code!r} no es de una entidad (PLT-001: letras mayúsculas, "
                         "un guion y al menos tres cifras)")
    return code.lower().replace("-", "_")


def segment_code(segment: str) -> str:
    """El código de una entidad desde su segmento de clave: ``plt_001`` → ``PLT-001`` (la inversa
    de :func:`entity_segment`). :class:`TypeError` si no es un texto; :class:`ValueError` si no es
    el segmento de un código de entidad (``[a-z]{2,5}_[0-9]{3,}``)."""
    if not isinstance(segment, str):
        raise TypeError(f"el segmento de una entidad es un texto, no {segment!r}")
    if _ENTITY_SEGMENT.fullmatch(segment) is None:
        raise ValueError(f"el segmento {segment!r} no es el de una entidad (plt_001: letras "
                         "minúsculas, un guion bajo y al menos tres cifras)")
    return segment.upper().replace("_", "-")


_KEY_SEGMENT = re.compile(r"[a-z][a-z0-9_]*")
_CODE_PREFIX = re.compile(r"[A-Z]{2,5}")
_KEY_PARTS = 4  # des.<tipo>.<código>.<valor>


@dataclass(frozen=True, slots=True)
class EntityParams:
    """Los parámetros de un **tipo de entidad** (spec 016, T02; plan 016 §5.2.2 y P-11; ADR-0027): su ``kind`` (el
    segmento de su clave: ``des.<kind>.{e}.<valor>``; ``platform``), el principio de su código (``code_prefix``:
    ``PLT`` de ``PLT-001``), los valores de su familia (``names``, en su orden: el último segmento de cada clave;
    todo tipo tiene ``name``) y las ``families`` que registra ``bl`` (una por valor, con su plantilla).

    Un tipo cuya familia **no** tiene ``start`` es un tipo **sin cadena** (:attr:`chained`): no parte de ninguna
    superficie y nadie parte de la suya (``design.entities``). Un tipo mal formado es un error del programa
    (:class:`ValueError`): el ``kind`` y los valores son segmentos de clave (``[a-z][a-z0-9_]*``), el prefijo son de
    dos a cinco mayúsculas, no hay valores repetidos y cada familia es la ``des.<kind>.{e}.<valor>`` de uno de ellos."""

    kind: str
    code_prefix: str
    names: tuple[str, ...]
    families: tuple[ParamFamily, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "names", tuple(self.names))
        object.__setattr__(self, "families", tuple(self.families))
        if not isinstance(self.kind, str) or _KEY_SEGMENT.fullmatch(self.kind) is None:
            raise ValueError(f"el tipo de una entidad es un segmento de clave ([a-z][a-z0-9_]*), no {self.kind!r}")
        if not isinstance(self.code_prefix, str) or _CODE_PREFIX.fullmatch(self.code_prefix) is None:
            raise ValueError(f"el prefijo del código de una entidad son de dos a cinco mayúsculas, no "
                             f"{self.code_prefix!r}")
        for name in self.names:
            if not isinstance(name, str) or _KEY_SEGMENT.fullmatch(name) is None:
                raise ValueError(f"un valor de {self.kind} es un segmento de clave ([a-z][a-z0-9_]*), no {name!r}")
        if len(set(self.names)) != len(self.names):
            raise ValueError(f"los valores de {self.kind} no se repiten: {', '.join(self.names)}")
        if PlatformParam.NAME.value not in self.names:
            raise ValueError(f"toda entidad tiene nombre: {self.kind} no tiene el valor «name»")
        for family in self.families:
            prefix, _, last = family.pattern.rpartition(".")
            if prefix != f"{self.key_prefix}.{{e}}" or last not in self.names:
                raise ValueError(f"la familia {family.pattern!r} no es de {self.key_prefix}.{{e}}.<valor> de "
                                 f"{self.kind}")

    @property
    def key_prefix(self) -> str:
        """El principio de la clave de un valor de este tipo, sin el código: ``des.platform``."""
        return f"des.{self.kind}"

    @property
    def chained(self) -> bool:
        """Si el tipo encadena: su familia tiene ``start`` (la superficie de la que parte). Sin él, es un tipo
        sin cadena."""
        return PlatformParam.START.value in self.names


_ENTITY_PARAMS: dict[str, EntityParams] = {}
_ENTITY_BY_PREFIX: dict[str, EntityParams] = {}
_PERMANENT: set[str] = set()


def register_entity_params(spec: EntityParams, *, permanent: bool = False) -> None:
    """Registra los parámetros de un tipo de entidad (spec 016, T02). ``permanent``: es del programa y no se quita
    (la plataforma); los demás los quita quien los registró. :class:`TypeError` si ``spec`` no es un
    :class:`EntityParams`; :class:`ValueError` si el tipo o el prefijo de su código ya están registrados (el prefijo es
    el tipo de un código: no se comparte). No deja nada a medias."""
    if not isinstance(spec, EntityParams):
        raise TypeError(f"se registra un EntityParams, no {type(spec).__name__} ({spec!r})")
    if spec.kind in _ENTITY_PARAMS:
        raise ValueError(f"el tipo de entidad «{spec.kind}» ya está registrado")
    if spec.code_prefix in _ENTITY_BY_PREFIX:
        raise ValueError(f"el prefijo de código «{spec.code_prefix}» ya es el del tipo de entidad "
                         f"«{_ENTITY_BY_PREFIX[spec.code_prefix].kind}»")
    _ENTITY_PARAMS[spec.kind] = spec
    _ENTITY_BY_PREFIX[spec.code_prefix] = spec
    if permanent:
        _PERMANENT.add(spec.kind)


def unregister_entity_params(kind: str) -> None:
    """Quita los parámetros del tipo de entidad ``kind`` (spec 016, T02). :class:`ValueError` si es del programa
    (la plataforma) o no está registrado."""
    if kind in _PERMANENT:
        raise ValueError(f"el tipo de entidad «{kind}» es del programa: no se quita")
    spec = _ENTITY_PARAMS.pop(kind, None) if isinstance(kind, str) else None
    if spec is None:
        raise ValueError(f"el tipo de entidad {kind!r} no está registrado")
    del _ENTITY_BY_PREFIX[spec.code_prefix]


def registered_entity_params() -> tuple[EntityParams, ...]:
    """Los parámetros de los tipos de entidad registrados, en el orden en que se registraron (la plataforma,
    primero)."""
    return tuple(_ENTITY_PARAMS.values())


def entity_params(kind: str) -> EntityParams:
    """Los parámetros del tipo de entidad ``kind`` (``platform``). :class:`ValueError` si no está registrado: un
    error del programa."""
    found = _ENTITY_PARAMS.get(kind) if isinstance(kind, str) else None
    if found is None:
        raise ValueError(f"el tipo de entidad {kind!r} no está registrado")
    return found


def _parts(code: str) -> tuple[EntityParams, str]:
    """Los parámetros del tipo de la entidad de código ``code`` (el de su prefijo) y su segmento de clave."""
    segment = entity_segment(code)
    found = _ENTITY_BY_PREFIX.get(code.partition("-")[0])
    if found is None:
        raise ValueError(f"el código {code!r} no es de ningún tipo de entidad registrado "
                         f"({', '.join(sorted(_ENTITY_BY_PREFIX))})")
    return found, segment


def entity_params_of(code: str) -> EntityParams:
    """Los parámetros del tipo de la entidad de código ``code``: el que tiene el prefijo de su código.
    :class:`TypeError` si no es un texto; :class:`ValueError` si no es un código de entidad o ningún tipo
    registrado tiene su prefijo."""
    return _parts(code)[0]


def entity_key(code: str, param: PlatformParam | str) -> str:
    """La clave del valor ``param`` de la entidad de código ``code`` **en la familia de su tipo**
    (``des.platform.plt_001.width_m``, ``des.stockpile.stk_001.margin_m``): el tipo es el del prefijo de su código y
    ``param`` ha de ser un valor de su familia (:attr:`EntityParams.names`). :class:`ValueError` si el código no es
    de una entidad de un tipo registrado o ``param`` no es un valor de ese tipo (un error del programa)."""
    spec, segment = _parts(code)
    name = str(param)
    if name not in spec.names:
        raise ValueError(f"«{name}» no es un valor de {spec.kind} ({spec.key_prefix}.{{e}}.<valor>)")
    return f"{spec.key_prefix}.{segment}.{name}"


def parse_entity_key(key: object) -> tuple[str, str, str] | None:
    """El código, el tipo y el valor de la clave de un valor de una entidad (``des.platform.plt_001.width_m`` →
    ``("PLT-001", "platform", "width_m")``); ``None`` si no es de la forma ``des.<tipo>.<segmento>.<valor>`` de un
    tipo registrado con un código de su prefijo y un valor de su familia."""
    if not isinstance(key, str):
        return None
    parts = key.split(".")
    if len(parts) != _KEY_PARTS or parts[0] != "des":
        return None
    spec = _ENTITY_PARAMS.get(parts[1])
    if spec is None:
        return None
    try:
        code = segment_code(parts[2])
    except ValueError:
        return None
    if not code.startswith(f"{spec.code_prefix}-") or parts[3] not in spec.names:
        return None
    return code, spec.kind, parts[3]


PLATFORM_ENTITY = EntityParams("platform", "PLT", tuple(item.value for item in PlatformParam), ENTITY_FAMILIES)
"""Los parámetros del tipo plataforma: sus 20 valores y sus 20 familias (:data:`ENTITY_FAMILIES`), registrados al
importar y del programa."""
register_entity_params(PLATFORM_ENTITY, permanent=True)


def check_entity_param(entity: str, code: str, param: PlatformParam | str, value: object, *,
                       layer: str, required: bool | None = None) -> float | str | bool | None:
    """El valor ``param`` de la plataforma de nombre ``entity`` y código ``code`` de la capa
    ``layer``, ya comprobado: ``float`` un número, ``str`` un texto (sin los espacios de los
    extremos), ``bool`` el sí/no y ``None`` un opcional sin valor.

    :class:`~design.messages.DesignError` ``des.entity_param_missing`` si no tiene valor
    (``None`` o un texto en blanco: ninguno elige un valor por la persona, RF-015-08),
    ``des.entity_param_range`` si un número está fuera de su rango (:data:`ENTITY_RANGES`; ``nan`` y
    el infinito también) o ``des.entity_param_choice`` si un texto no es de su lista cerrada,
    nombrando la capa, la plataforma, la clave del campo y el valor (RF-015-08: «la capa, la
    entidad, el campo y el valor»; la capa, desde la T11). ``required`` (por defecto, todo salvo lo
    opcional: la superficie de apoyo, la pendiente máxima, el motivo y las dependencias declaradas)
    lo cambia: ``False`` deja pasar un valor que no hace falta (el ancho de un eje que no es de
    línea, el resguardo de quien no protege); ``True`` exige uno opcional. :class:`TypeError` si el
    valor no es del tipo del parámetro (un número que llega como texto o como booleano);
    :class:`ValueError` si el código o el parámetro no existen (errores del programa)."""
    param = PlatformParam(param)
    key = entity_key(code, param)
    definition = PLATFORM_PARAMS[param.value]
    value_type = str(definition.value_type)
    if value is not None:
        if value_type == "bool":
            if not isinstance(value, bool):
                raise TypeError(f"el valor {key} es un sí/no, no {value!r}")
        elif value_type == "text":
            if not isinstance(value, str):
                raise TypeError(f"el valor {key} es un texto, no {value!r}")
            value = value.strip() or None
        else:
            value = _real(value, f"el valor {key}")
    obj = f"Plataforma «{entity}»"
    if value is None:
        if (param not in _OPTIONAL) if required is None else required:
            raise DesignError("des.entity_param_missing", obj=obj, field=key, value=None,
                              entity=entity, layer=layer)
        return None
    if definition.choices and value not in definition.choices:
        listed = ", ".join(f"«{choice}»" for choice in definition.choices)
        raise DesignError("des.entity_param_choice", obj=obj, field=key, value=value,
                          entity=entity, layer=layer, choices=listed)
    span = ENTITY_RANGES.get(param.value)
    if span is not None:
        if not span.contains(value):
            raise DesignError("des.entity_param_range", obj=obj, field=key, value=value,
                              entity=entity, layer=layer, range=span.text())
        return float(value)  # type: ignore[arg-type]
    return value  # type: ignore[return-value]
