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

**Los cuatro tipos de la 016** (spec 016, T03; plan 016 §5.2.2; D-1, D-2, D-3, D-9, D-19, D-21 y D-22): el acopio
(``stockpile``, la detección, ``STK-001``: **sin cadena**, sin ``start``), la retirada (``removal``, ``RMV``), el
contrafuerte (``buttress``, ``BTR``) y el cuerpo apoyado (``body``, ``BDY``) son cuatro tipos del programa
(:data:`STOCKPILE_ENTITY`, :data:`REMOVAL_ENTITY`, :data:`BUTTRESS_ENTITY` y :data:`BODY_ENTITY`, registrados al importar
como la plataforma) con sus valores en :class:`StockpileParam`, :class:`RemovalParam`, :class:`ButtressParam` y
:class:`BodyParam` y sus familias de versión (:data:`SUPPORTED_FAMILIES`; admiten también el valor del proyecto: la
detección sobre una superficie del proyecto, D-15). **Valor por defecto solo donde lo dice el plan**: ADOPTADO «sin
confirmar» los de D-3 (margen 10 m, corona de 1 a 3 m, pendiente de corona 12°, área llana mínima 10 m², residuo
máximo 1 m, 4 vueltas del ajuste y 6 de plano y huella, altura mínima 2 m y áreas de 150 a 20.000 m²), el factor de malla
1,0 y la métrica exacta; HIPÓTESIS la inclinación máxima (4°), el cuantil de apoyo (0,6) y, desde la T48 (hallazgo D-4: el banco,
CE-016-08, no lo confirmó), la apertura de 31 m —P-6: el diámetro en metros—; «proteger» solo en el contrafuerte (D-1) y «cero en el borde» falso. **Sin valor** (lo declara
una persona): la transición (D-2), la cota de coronación (D-21), la distancia máxima (D-9) y el resguardo (D-19 de la
015). Los rangos (:data:`STOCKPILE_RANGES`…) son los límites de validez que fija la T03 (no una cifra minera), y
:func:`check_entity_param` rechaza un valor sin valor o fuera de ellos, para cualquier tipo.

El espesor mínimo del informe es el de la 012, ``res.verify.min_thickness_m``
(:data:`VERIFY_MIN_THICKNESS`), y el umbral de la huella de un acopio es el de la 011, ``res.anthropic_presence_m``
(:data:`ANTHROPIC_PRESENCE`, D-17): ``design`` los lee **por su clave** con ``core.params`` sin
importar ``reserves`` (D-24), sin copiarlos; una prueba de arquitectura comprueba que siguen declarados.

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
    "ANTHROPIC_PRESENCE",
    "BODY_ENTITY",
    "BODY_FAMILIES",
    "BODY_RANGES",
    "BUTTRESS_ENTITY",
    "BUTTRESS_FAMILIES",
    "BUTTRESS_RANGES",
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
    "REMOVAL_ENTITY",
    "REMOVAL_FAMILIES",
    "REMOVAL_RANGES",
    "SECTOR_SLOPE",
    "STOCKPILE_ENTITY",
    "STOCKPILE_FAMILIES",
    "STOCKPILE_RANGES",
    "SUPPORTED_FAMILIES",
    "TOLERANCE_FACE",
    "UNSPLIT_MIN_AREA",
    "UNSPLIT_THRESHOLD",
    "VERIFY_MIN_THICKNESS",
    "WARNING_RATIO",
    "BenchParam",
    "BodyParam",
    "ButtressParam",
    "EntityParams",
    "ParamDef",
    "ParamValue",
    "PlatformParam",
    "RemovalParam",
    "StockpileParam",
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
    """Los 21 valores de una plataforma: el último segmento de su clave
    ``des.platform.{e}.<valor>`` (plan 015 §5.2.2), en su orden. El último, ``stockpile``, es de la 016 (T21; RF-016-16, A9): el
    acopio que la plataforma retira **«como plataforma»**; una plataforma de una capa no lo tiene (sin valor)."""

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
    STOCKPILE = "stockpile"


COMMON_ENTITY_PARAMS: tuple[str, ...] = (
    PlatformParam.NAME.value, PlatformParam.START.value, PlatformParam.SUPPORT.value,
    PlatformParam.SUPPORTS.value, PlatformParam.DISCARDED.value, PlatformParam.PROTECT.value,
    PlatformParam.GUARD.value, PlatformParam.REASON.value)
"""Los valores **comunes a todos los tipos de entidad** (plan 016 §5.2.2): los de la 015 que no son de la geometría de
la plataforma (``name``, ``start``, ``support``, ``supports``, ``discarded``, ``protect``, ``guard_m`` y ``reason``),
bajo el prefijo de cada tipo (P-11). Un tipo sin cadena no tiene ``start``."""

_PLATFORM_OPTIONAL = (PlatformParam.SUPPORT.value, PlatformParam.MAX_SLOPE.value, PlatformParam.REASON.value,
                      PlatformParam.SUPPORTS.value, PlatformParam.STOCKPILE.value)
"""Los valores de la plataforma que pueden quedarse sin valor: la superficie de apoyo («si la hay»), la pendiente
máxima (opcional, D-6), el motivo (el generado, editable), las dependencias declaradas (vacío) y el acopio que retira «como
plataforma» (T21: solo lo tiene la plataforma que sale de retirar un acopio)."""

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

_016_PLATFORM_STOCKPILE = ("Spec 016, RF-016-16 y A9: el acopio que la plataforma retira «como plataforma» (su detección y su clave, "
                           "STK-001#m07); sin valor por defecto ni en la plataforma de una capa; lo elige una persona al retirar "
                           "el acopio (Samuel, IMGA, 18/11/2026)")

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
    (PlatformParam.STOCKPILE, "text", None, (), ("RF-016-16",), _016_PLATFORM_STOCKPILE,
     "Stockpile the platform removes"),
)


def entity_family(prefix: str, param: str, value_type: str, default: ParamValue | None,
                  choices: tuple[str, ...], rfs: tuple[str, ...], source: str, label: str, *,
                  span: ValueRange | None = None, scope: str = "version",
                  kind: str = "ADOPTADO") -> ParamFamily:
    """La familia ``<prefix>.{e}.<param>`` de un tipo de entidad (``prefix``: ``des.platform``, ``des.stockpile``…;
    spec 016, T02) con la plantilla de clave ``<prefix>.e.<param>``: el rango ``span`` (sin tope en un extremo
    infinito), ADOPTADO «sin confirmar» de origen ``algorithm`` con valor por defecto, o ADOPTADO sin valor que
    declara una persona (origen ``person``), de ``scope`` de versión (por defecto) o de proyecto. ``kind`` (T03): el
    tipo del valor por defecto, ``ADOPTADO`` (el de siempre) o ``HIPÓTESIS`` (la inclinación máxima y el cuantil de
    apoyo de la detección, D-3). Es la construcción de las 20 familias de la plataforma, sin cambiar nada de ellas."""
    unit = "-" if span is None else span.unit
    minimum = None if span is None or span.minimum == -math.inf else span.minimum
    maximum = None if span is None or span.maximum == math.inf else span.maximum
    template = ParamDef(
        f"{prefix}.e.{param}", value_type, unit, default, minimum, maximum, rfs,
        source, min_exclusive=span is not None and span.min_exclusive, allow_empty=default is None,
        choices=choices, kind=kind, source_kind="person" if default is None else "algorithm",
        scope=scope, label_msgid=label)
    return ParamFamily(f"{prefix}.{{e}}.{param}", template)


def _entity_family(param: PlatformParam, value_type: str, default: ParamValue | None,
                   choices: tuple[str, ...], rfs: tuple[str, ...], source: str,
                   label: str) -> ParamFamily:
    """La familia ``des.platform.{e}.<param>`` (de versión) con el rango de :data:`ENTITY_RANGES`."""
    return entity_family(PLATFORM_PREFIX, param.value, value_type, default, choices, rfs, source, label,
                         span=ENTITY_RANGES.get(param.value))


ENTITY_FAMILIES: tuple[ParamFamily, ...] = tuple(_entity_family(*spec) for spec in _ENTITY_SPECS)
"""Las 21 familias de una plataforma (plan 015 §5.2.2 y T25; la 21.ª, ``stockpile``, de la 016: T21), de versión, en su orden. Van aparte de
:data:`FAMILIES` (las de la 013): ``bl`` las registra junto a ellas cuando registre las operaciones
de la 015 (T04)."""

PLATFORM_PARAMS: Mapping[str, ParamDef] = MappingProxyType(
    {PlatformParam(family.pattern.rsplit(".", 1)[1]).value: family.template
     for family in ENTITY_FAMILIES})
"""Las plantillas de las 21 familias por último segmento de la clave (solo lectura)."""


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
    optional: tuple[str, ...] = ()
    label: str = ""
    ranges: tuple[tuple[str, ValueRange], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "names", tuple(self.names))
        object.__setattr__(self, "families", tuple(self.families))
        object.__setattr__(self, "optional", tuple(self.optional))
        object.__setattr__(self, "ranges", tuple(self.ranges))
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
        for name in self.optional:
            if name not in self.names:
                raise ValueError(f"el valor opcional {name!r} no es de {self.kind}")
        for name, span in self.ranges:
            if name not in self.names or not isinstance(span, ValueRange):
                raise ValueError(f"el rango de {name!r} no es el de un valor numérico de {self.kind}")
        if not isinstance(self.label, str):
            raise ValueError(f"el nombre de {self.kind} para las personas es un texto, no {self.label!r}")

    @property
    def key_prefix(self) -> str:
        """El principio de la clave de un valor de este tipo, sin el código: ``des.platform``."""
        return f"des.{self.kind}"

    @property
    def chained(self) -> bool:
        """Si el tipo encadena: su familia tiene ``start`` (la superficie de la que parte). Sin él, es un tipo
        sin cadena."""
        return PlatformParam.START.value in self.names

    def template(self, name: str) -> ParamDef:
        """La plantilla del valor ``name`` de este tipo (la de su familia ``des.<tipo>.{e}.<valor>``).
        :class:`ValueError` si no es un valor suyo o su familia no está declarada: un error del programa."""
        for family in self.families:
            if family.pattern.rpartition(".")[2] == name:
                return family.template
        raise ValueError(f"«{name}» no es un valor de {self.kind} con su familia declarada")

    def range(self, name: str) -> ValueRange | None:
        """El rango del valor numérico ``name`` de este tipo (:class:`ValueRange`, con los extremos abiertos o
        cerrados que ``ParamDef`` no puede decir); ``None`` si no lo tiene (un texto, un sí/no)."""
        for found, span in self.ranges:
            if found == name:
                return span
        return None


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


PLATFORM_ENTITY = EntityParams(
    "platform", "PLT", tuple(item.value for item in PlatformParam), ENTITY_FAMILIES,
    optional=_PLATFORM_OPTIONAL, label="Plataforma", ranges=tuple(ENTITY_RANGES.items()))
"""Los parámetros del tipo plataforma: sus 21 valores y sus 21 familias (:data:`ENTITY_FAMILIES`), sus opcionales y
sus rangos, registrados al importar y del programa."""
register_entity_params(PLATFORM_ENTITY, permanent=True)


# --- Los cuatro tipos de entidad de la 016 (spec 016, T03; plan 016 §5.2.2; D-1, D-2, D-3, D-9, D-21, D-22) -------

ANTHROPIC_PRESENCE = "res.anthropic_presence_m"
"""El umbral único de presencia de antrópicas de la 011 (RF-011-14, D-7 de la 011; 0,30 m): **el umbral de la huella de
un acopio** (D-17 de la 016). ``design`` lo lee **por su clave** con ``core.params`` sin importar ``reserves`` (como
:data:`VERIFY_MIN_THICKNESS`, D-24): no se copia a la familia del acopio, para que la unidad antrópica de la 011 y la
huella tengan las mismas celdas; una prueba comprueba que la clave sigue declarada en ``reserves.params``."""


class StockpileParam(StrEnum):
    """Los valores de una detección de acopios (``des.stockpile.{e}.<valor>``; plan 016 §5.2.2), en su orden: los
    propios (la capa de marcas, la superficie, los candidatos, los umbrales de D-3 y las decisiones) y los comunes a
    todos los tipos, menos ``start``: la detección es un tipo **sin cadena** (T02)."""

    NAME = "name"
    LAYER = "layer"
    SURFACE = "surface"
    CANDIDATES = "candidates"
    MARGIN = "margin_m"
    CROWN_INNER = "crown_inner_m"
    CROWN_OUTER = "crown_outer_m"
    CROWN_SLOPE = "crown_slope_deg"
    CROWN_FLAT_MIN = "crown_flat_min_m2"
    MAX_RESIDUAL = "max_residual_m"
    FIT_ROUNDS = "fit_rounds"
    TURNS = "turns"
    TILT_MAX = "tilt_max_deg"
    SUPPORT_QUANTILE = "support_quantile"
    OPEN_DIAMETER = "open_diameter_m"
    MIN_HEIGHT = "min_height_m"
    MIN_AREA = "min_area_m2"
    MAX_AREA = "max_area_m2"
    DECISIONS = "decisions"
    SUPPORT = "support"
    SUPPORTS = "supports"
    DISCARDED = "discarded"
    PROTECT = "protect"
    GUARD = "guard_m"
    REASON = "reason"


class RemovalParam(StrEnum):
    """Los valores de la retirada de un acopio (``des.removal.{e}.<valor>``; plan 016 §5.2.2), en su orden."""

    NAME = "name"
    STOCKPILE = "stockpile"
    START = "start"
    SUPPORT = "support"
    SUPPORTS = "supports"
    TRANSITION = "transition_deg"
    MESH_FACTOR = "mesh_factor"
    METRIC = "metric"
    WALL_REASON = "wall_reason"
    DISCARDED = "discarded"
    PROTECT = "protect"
    GUARD = "guard_m"
    REASON = "reason"


class ButtressParam(StrEnum):
    """Los valores de un contrafuerte (``des.buttress.{e}.<valor>``; plan 016 §5.2.2), en su orden."""

    NAME = "name"
    LAYER = "layer"
    FEATURE = "feature"
    START = "start"
    SUPPORT = "support"
    PROFILE = "profile"
    REACH = "reach_m"
    CROWN = "crown_m"
    METRIC = "metric"
    PROTECT = "protect"
    GUARD = "guard_m"
    REASON = "reason"
    SUPPORTS = "supports"
    DISCARDED = "discarded"


class BodyParam(StrEnum):
    """Los valores de un cuerpo apoyado (``des.body.{e}.<valor>``; plan 016 §5.2.2), en su orden."""

    NAME = "name"
    LAYER = "layer"
    FEATURE = "feature"
    DATA_LAYER = "data_layer"
    DATA_FIELD = "data_field"
    DATA_FROM = "data_from"
    SURFACE = "surface"
    SENSE = "sense"
    START = "start"
    MAX_DISTANCE = "max_distance_m"
    ZERO_AT_EDGE = "zero_at_edge"
    SUPPORT = "support"
    SUPPORTS = "supports"
    DISCARDED = "discarded"
    PROTECT = "protect"
    GUARD = "guard_m"
    REASON = "reason"


STOCKPILE_RANGES: Mapping[str, ValueRange] = MappingProxyType({
    StockpileParam.MARGIN.value: ValueRange(0.0, 1000.0, "m"),
    StockpileParam.CROWN_INNER.value: ValueRange(0.0, 1000.0, "m"),
    StockpileParam.CROWN_OUTER.value: ValueRange(0.0, 1000.0, "m", min_exclusive=True),
    StockpileParam.CROWN_SLOPE.value: ValueRange(0.0, 90.0, "deg", min_exclusive=True, max_exclusive=True),
    StockpileParam.CROWN_FLAT_MIN.value: ValueRange(0.0, 1.0e6, "m2"),
    StockpileParam.MAX_RESIDUAL.value: ValueRange(0.0, 1000.0, "m", min_exclusive=True),
    StockpileParam.FIT_ROUNDS.value: ValueRange(1, 100, "-"),
    StockpileParam.TURNS.value: ValueRange(1, 100, "-"),
    StockpileParam.TILT_MAX.value: ValueRange(0.0, 90.0, "deg", max_exclusive=True),
    StockpileParam.SUPPORT_QUANTILE.value: ValueRange(0.0, 1.0, "-"),
    StockpileParam.OPEN_DIAMETER.value: ValueRange(0.0, 1000.0, "m", min_exclusive=True),
    StockpileParam.MIN_HEIGHT.value: ValueRange(0.0, 1000.0, "m"),
    StockpileParam.MIN_AREA.value: ValueRange(0.0, 1.0e7, "m2", min_exclusive=True),
    StockpileParam.MAX_AREA.value: ValueRange(0.0, 1.0e9, "m2", min_exclusive=True),
    StockpileParam.GUARD.value: ENTITY_RANGES[PlatformParam.GUARD.value],
})
REMOVAL_RANGES: Mapping[str, ValueRange] = MappingProxyType({
    RemovalParam.TRANSITION.value: ValueRange(0.0, 90.0, "deg", min_exclusive=True, max_exclusive=True),
    RemovalParam.MESH_FACTOR.value: ENTITY_RANGES[PlatformParam.MESH_FACTOR.value],
    RemovalParam.GUARD.value: ENTITY_RANGES[PlatformParam.GUARD.value],
})
BUTTRESS_RANGES: Mapping[str, ValueRange] = MappingProxyType({
    ButtressParam.REACH.value: ENTITY_RANGES[PlatformParam.REACH.value],
    ButtressParam.CROWN.value: ValueRange(-_INF, _INF, "m"),
    ButtressParam.GUARD.value: ENTITY_RANGES[PlatformParam.GUARD.value],
})
BODY_RANGES: Mapping[str, ValueRange] = MappingProxyType({
    BodyParam.MAX_DISTANCE.value: ValueRange(0.0, 100000.0, "m", min_exclusive=True),
    BodyParam.GUARD.value: ENTITY_RANGES[PlatformParam.GUARD.value],
})
"""Los rangos de los valores numéricos de cada tipo por último segmento de la clave (solo lectura): la única fuente
de los de sus familias y de lo que :func:`check_entity_param` acepta. **El plan 016 §5.2.2 no los da**: son los
límites de validez que esta tarea fija (revisables), ninguno una cifra minera; ninguno excluye un valor por defecto
de la tabla. Los del resguardo, el factor de malla y el alcance son los de la plataforma."""

_016_NAME = _015_NAME
_016_D3 = ("Spec 016, D-3: el valor del proyecto de referencia (00 §3.10; s99 y s99b); ADOPTADO «sin confirmar» "
           "(Samuel, IMGA, 14/11/2026)")
_016_D3_OPEN = ("Spec 016, D-3 y P-6: apertura de 31 m = diámetro en metros (radio 15,5 m sobre la rejilla del "
                "proyecto), la lectura de s99b que cabe en las demás; HIPÓTESIS: el banco (CE-016-08) no lo confirmó "
                "(74, 20 o 135 candidatos según la lectura, frente a 60) y queda sin contrastar hasta tener el expediente "
                "de la V10; el valor no cambia (Samuel, IMGA, 14/11/2026; T48)")
_016_D3_HYPOTHESIS = ("Spec 016, D-3: HIPÓTESIS, como en el origen (TILT_MAX y el cuantil de apoyo de s99); la cifra "
                      "que sale con ella lleva su marca y su sensibilidad (R-41) (Samuel, IMGA, 14/11/2026)")
_016_D3_NONE = ("Spec 016, RF-016-02 y RF-016-08: sin valor por defecto; lo elige una persona al crear la detección "
                "(Samuel, IMGA, 14/11/2026)")
_016_D3_DECISIONS = ("Spec 016, RF-016-08, RF-016-10 y P-14: las decisiones sobre los candidatos (convertido o "
                     "descartado, con motivo, decisor y fecha); vacío por defecto (decidida por la sesión principal, "
                     "14/11/2026, revisable)")
_016_D2_NONE = ("Spec 016, D-2: sin valor por defecto, propio de la retirada (no el de la 014: cambiar la transición "
                "de una cantera no debe dejar obsoletas las retiradas); lo declara una persona con su origen (en el "
                "proyecto de referencia, 35°) (Samuel, IMGA, 14/11/2026)")
_016_D2_MESH = ("Spec 016, D-2: 1,0, como el factor de malla de la 013 (D-7 de la 013); en el proyecto de referencia "
                "×0,93 con el chamfer; sin confirmar (Samuel, IMGA, 14/11/2026)")
_016_REMOVAL = ("Spec 016, RF-016-11 y RF-016-12: sin valor por defecto; lo elige una persona al crear la retirada "
                "(Samuel, IMGA, 14/11/2026)")
_016_WALL = ("Spec 016, RF-016-15 y D-6: el motivo que queda registrado con una pared de más de 45° y 3 m o más; "
             "vacío por defecto (Samuel, IMGA, 14/11/2026)")
_016_BUTTRESS = ("Spec 016, RF-016-17 y D-7: sin valor por defecto; lo elige una persona al crear el contrafuerte "
                 "(Samuel, IMGA, 14/11/2026)")
_016_BUTTRESS_REACH = ("Spec 016, RF-016-17: el alcance es opcional y sin valor por defecto; si se fija, la "
                       "envolvente no pasa de él (Samuel, IMGA, 14/11/2026)")
_016_D21 = ("Spec 016, D-21: sin valor por defecto; la cota de coronación es del ancla de su perfil (z₀ + n·h) o se "
            "rechaza con la del ancla más próxima (Samuel, IMGA, 14/11/2026)")
_016_D1_BUTTRESS = ("Spec 016, D-1: el contrafuerte declara «sin corte» en su zona de coronación por defecto; se "
                    "puede cambiar con motivo y decisor; sin confirmar (Samuel, IMGA, 14/11/2026)")
_016_D1_NONE = ("Spec 016, D-1: este tipo no declara nada por defecto; «proteger» se elige con motivo; sin confirmar "
                "(Samuel, IMGA, 14/11/2026)")
_016_BODY = ("Spec 016, RF-016-20 y D-8: sin valor por defecto; lo elige una persona al crear el cuerpo apoyado "
             "(Samuel, IMGA, 14/11/2026)")
_016_BODY_START = ("Spec 016, RF-016-20: solo un cuerpo «sobre una base» parte de una superficie (el apoyo); «bajo un "
                   "techo» no cambia la superficie y no tiene partida (Samuel, IMGA, 14/11/2026)")
_016_D9 = ("Spec 016, D-9 (B9): obligatoria y sin valor por defecto, el análisis no da cifra; lo declara una "
           "persona con su origen (Samuel, IMGA, 14/11/2026)")
_016_ZERO = ("Spec 016, RF-016-20: falso por defecto; si es verdadero el espesor vale 0 en el borde de la huella "
             "(Samuel, IMGA, 14/11/2026)")
_016_REASON = ("Spec 015, RF-015-10: el motivo generado («declarada por …»), que la persona puede editar en la "
               "entidad (Samuel, IMGA, 14/11/2026)")
_016_SUPPORTS = ("Spec 015, RF-015-15: las entidades en las que la persona declara que se apoya; vacío por defecto "
                 "(Samuel, IMGA, 14/11/2026)")

_SupportedSpec = tuple[str, str, "ParamValue | None", tuple[str, ...], tuple[str, ...], str, str, str]
"""Un valor de un tipo de la 016: su nombre, su tipo de valor, su valor por defecto, sus opciones, sus RF, su
procedencia, su etiqueta y el tipo de su valor por defecto (``ADOPTADO`` o ``HIPÓTESIS``)."""

_COMMON_LABELS = {
    "name": "Name of the entity", "start": "Start surface of the entity", "support": "Support surface of the entity",
    "supports": "Entities the entity is declared to rest on", "discarded": "The entity is discarded",
    "protect": "The entity protects its area", "guard_m": "Buffer of the protected area",
    "reason": "Reason of the declared constraint"}
"""Las etiquetas de los valores comunes a todos los tipos (plan 016 §5.2.2): las mismas en los cuatro."""


def _item(name: str, value_type: str, default: ParamValue | None, rfs: tuple[str, ...], source: str,
          label: str | None = None, *, choices: tuple[str, ...] = (), kind: str = "ADOPTADO") -> _SupportedSpec:
    return (name, value_type, default, choices, rfs, source, label or _COMMON_LABELS[name], kind)


def _common(name: str, *, protect: bool = False) -> _SupportedSpec:
    """Un valor común a todos los tipos (los de la 015 bajo el prefijo de cada tipo, P-11)."""
    rfs, source = {
        "name": (("RF-015-01",), _016_NAME),
        "start": (("RF-015-04", "RF-015-05"), _015_START),
        "support": (("RF-015-04", "RF-015-05"), _015_START),
        "supports": (("RF-015-15",), _016_SUPPORTS),
        "discarded": (("RF-015-17",), _015_DISCARDED),
        "guard_m": (("RF-015-10", "RF-015-12"), _015_D19),
        "reason": (("RF-015-10", "RF-015-12"), _016_REASON),
    }.get(name, (("RF-015-10", "RF-015-12"), _016_D1_BUTTRESS if protect else _016_D1_NONE))
    default: ParamValue | None = (protect if name == "protect" else False if name == "discarded" else None)
    return _item(name, "bool" if name in ("protect", "discarded") else "float" if name == "guard_m" else "text",
                 default, rfs, source)


def _supported_entity(kind: str, prefix: str, label: str, members: type[StrEnum],
                      specs: tuple[_SupportedSpec, ...], ranges: Mapping[str, ValueRange],
                      optional: tuple[str, ...]) -> EntityParams:
    """Los parámetros de un tipo de la 016: una familia ``des.<kind>.{e}.<valor>`` por cada valor de ``members``, en
    su orden, con la procedencia, el rango y las opciones de ``specs``; registrado como del programa (ADOPTADO sin
    valor lo que decide una persona, ADOPTADO «sin confirmar» o HIPÓTESIS lo que lleva valor por defecto)."""
    found = {item[0]: item for item in specs}
    order = tuple(item.value for item in members)
    if tuple(found) != order or len(found) != len(specs):
        raise RuntimeError(f"los valores de {kind} no son los de su enumeración: {', '.join(found)}")
    families = tuple(
        entity_family(f"des.{kind}", name, value_type, default, choices, rfs, source, family_label,
                      span=ranges.get(name), kind=family_kind)
        for name, value_type, default, choices, rfs, source, family_label, family_kind in specs)
    entity = EntityParams(kind, prefix, order, families, optional=optional, label=label,
                          ranges=tuple(ranges.items()))
    register_entity_params(entity, permanent=True)
    return entity


STOCKPILE_ENTITY = _supported_entity(
    "stockpile", "STK", "Detección de acopios", StockpileParam, (
        _common("name"),
        _item("layer", "text", None, ("RF-016-02",), _016_D3_NONE, "Layer of the stockpile marks"),
        _item("surface", "text", None, ("RF-016-02",), _016_D3_NONE, "Surface the stockpiles are detected on"),
        _item("candidates", "bool", None, ("RF-016-08",), _016_D3_NONE, "Look for candidates without a mark"),
        _item("margin_m", "float", 10.0, ("RF-016-02",), _016_D3, "Margin around the mark of a stockpile"),
        _item("crown_inner_m", "float", 1.0, ("RF-016-02",), _016_D3, "Inner distance of the crown ring"),
        _item("crown_outer_m", "float", 3.0, ("RF-016-02",), _016_D3, "Outer distance of the crown ring"),
        _item("crown_slope_deg", "float", 12.0, ("RF-016-02",), _016_D3, "Slope of the flat terrain of the crown"),
        _item("crown_flat_min_m2", "float", 10.0, ("RF-016-02", "RF-016-05"), _016_D3,
              "Minimum flat area of the crown"),
        _item("max_residual_m", "float", 1.0, ("RF-016-02",), _016_D3, "Maximum residual of the base plane"),
        _item("fit_rounds", "int", 4, ("RF-016-02",), _016_D3, "Rounds of the robust fit of the plane"),
        _item("turns", "int", 6, ("RF-016-02", "RF-016-05"), _016_D3, "Rounds of plane and footprint"),
        _item("tilt_max_deg", "float", 4.0, ("RF-016-07",), _016_D3_HYPOTHESIS, "Maximum tilt of the base plane",
              kind="HIPÓTESIS"),
        _item("support_quantile", "float", 0.6, ("RF-016-07",), _016_D3_HYPOTHESIS,
              "Support quantile of the base plane", kind="HIPÓTESIS"),
        _item("open_diameter_m", "float", 31.0, ("RF-016-08",), _016_D3_OPEN,
              "Diameter of the opening of the candidates", kind="HIPÓTESIS"),
        _item("min_height_m", "float", 2.0, ("RF-016-08",), _016_D3, "Minimum height of a candidate"),
        _item("min_area_m2", "float", 150.0, ("RF-016-08",), _016_D3, "Minimum area of a candidate"),
        _item("max_area_m2", "float", 20000.0, ("RF-016-08",), _016_D3, "Maximum area of a candidate"),
        _item("decisions", "text", None, ("RF-016-08", "RF-016-10"), _016_D3_DECISIONS,
              "Decisions on the candidates"),
        _common("support"), _common("supports"), _common("discarded"), _common("protect"), _common("guard_m"),
        _common("reason"),
    ), STOCKPILE_RANGES, ("decisions", "support", "supports", "reason"))
"""Los parámetros de la detección de acopios (``stockpile``, ``STK-001``): sin cadena (sin ``start``)."""

REMOVAL_ENTITY = _supported_entity(
    "removal", "RMV", "Retirada de acopio", RemovalParam, (
        _common("name"),
        _item("stockpile", "text", None, ("RF-016-11", "RF-016-12"), _016_REMOVAL, "Stockpile that is removed"),
        _common("start"), _common("support"), _common("supports"),
        _item("transition_deg", "float", None, ("RF-016-11",), _016_D2_NONE, "Transition angle of the removal"),
        _item("mesh_factor", "float", 1.0, ("RF-016-11",), _016_D2_MESH, "Mesh factor of the transition of the removal"),
        _item("metric", "text", "exact", ("RF-016-11",), _015_D22, "Distance metric of the transition of the removal",
              choices=_METRIC_CHOICES),
        _item("wall_reason", "text", None, ("RF-016-15",), _016_WALL, "Reason for the wall left by the removal"),
        _common("discarded"), _common("protect"), _common("guard_m"), _common("reason"),
    ), REMOVAL_RANGES, ("support", "supports", "wall_reason", "reason"))
"""Los parámetros de la retirada de un acopio (``removal``, ``RMV-001``): encadena."""

BUTTRESS_ENTITY = _supported_entity(
    "buttress", "BTR", "Contrafuerte", ButtressParam, (
        _common("name"),
        _item("layer", "text", None, ("RF-016-17",), _016_BUTTRESS, "Layer of the crown zones"),
        _item("feature", "text", None, ("RF-016-17",), _016_BUTTRESS, "Feature of the layer the entity comes from"),
        _common("start"), _common("support"),
        _item("profile", "text", None, ("RF-016-17",), _016_BUTTRESS, "Bench profile of the buttress"),
        _item("reach_m", "float", None, ("RF-016-17",), _016_BUTTRESS_REACH, "Reach of the buttress"),
        _item("crown_m", "float", None, ("RF-016-17", "RF-016-18"), _016_D21, "Crown level of the buttress"),
        _item("metric", "text", "exact", ("RF-016-17",), _015_D22, "Distance metric of the buttress slopes",
              choices=_METRIC_CHOICES),
        _common("protect", protect=True), _common("guard_m"), _common("reason"), _common("supports"),
        _common("discarded"),
    ), BUTTRESS_RANGES, ("support", "reason", "reach_m", "supports"))
"""Los parámetros de un contrafuerte (``buttress``, ``BTR-001``): encadena y protege por defecto (D-1)."""

BODY_ENTITY = _supported_entity(
    "body", "BDY", "Cuerpo apoyado", BodyParam, (
        _common("name"),
        _item("layer", "text", None, ("RF-016-20",), _016_BODY, "Layer of the footprints of the bodies"),
        _item("feature", "text", None, ("RF-016-20",), _016_BODY, "Feature of the layer the entity comes from"),
        _item("data_layer", "text", None, ("RF-016-20",), _016_BODY, "Layer of the thickness data"),
        _item("data_field", "text", None, ("RF-016-20",), _016_BODY, "Field of the thickness data"),
        _item("data_from", "text", None, ("RF-016-20",), _016_BODY, "Where the thickness is read from",
              choices=("field", "z", "m")),
        _item("surface", "text", None, ("RF-016-20",), _016_BODY, "Known surface of the body"),
        _item("sense", "text", None, ("RF-016-20",), _016_BODY, "Sense of the supported body",
              choices=("on_base", "under_roof")),
        _item("start", "text", None, ("RF-016-20", "RF-015-04"), _016_BODY_START, "Start surface of the entity"),
        _item("max_distance_m", "float", None, ("RF-016-21", "RF-016-22"), _016_D9,
              "Maximum distance to the thickness data"),
        _item("zero_at_edge", "bool", False, ("RF-016-20",), _016_ZERO,
              "Thickness zero at the edge of the footprint"),
        _common("support"), _common("supports"), _common("discarded"), _common("protect"), _common("guard_m"),
        _common("reason"),
    ), BODY_RANGES, ("start", "support", "supports", "reason"))
"""Los parámetros de un cuerpo apoyado (``body``, ``BDY-001``): encadena su instancia «sobre una base»; la de
«bajo un techo» no tiene partida (``start`` es opcional)."""

STOCKPILE_FAMILIES: tuple[ParamFamily, ...] = STOCKPILE_ENTITY.families
REMOVAL_FAMILIES: tuple[ParamFamily, ...] = REMOVAL_ENTITY.families
BUTTRESS_FAMILIES: tuple[ParamFamily, ...] = BUTTRESS_ENTITY.families
BODY_FAMILIES: tuple[ParamFamily, ...] = BODY_ENTITY.families
SUPPORTED_FAMILIES: tuple[ParamFamily, ...] = (*STOCKPILE_FAMILIES, *REMOVAL_FAMILIES, *BUTTRESS_FAMILIES,
                                               *BODY_FAMILIES)
"""Las familias de los cuatro tipos de la 016 (plan 016 §5.2.2), de versión (que admiten también el valor del
proyecto: la detección sobre una superficie del proyecto, D-15), en su orden. Van aparte de :data:`FAMILIES` (las de la
013) y de :data:`ENTITY_FAMILIES` (las de la plataforma): ``bl`` las registra junto a ellas."""


def check_entity_param(entity: str, code: str, param: str, value: object, *,
                       layer: str, required: bool | None = None) -> float | int | str | bool | None:
    """El valor ``param`` de la entidad de nombre ``entity`` y código ``code`` (de cualquier tipo registrado: la
    plataforma, el acopio, la retirada, el contrafuerte o el cuerpo apoyado) de la capa ``layer``, ya comprobado:
    ``float`` un número, ``int`` un entero (las vueltas del ajuste), ``str`` un texto (sin los espacios de los
    extremos), ``bool`` el sí/no y ``None`` un opcional sin valor.

    :class:`~design.messages.DesignError` ``des.entity_param_missing`` si no tiene valor
    (``None`` o un texto en blanco: ninguno elige un valor por la persona, RF-015-08),
    ``des.entity_param_range`` si un número está fuera de su rango (el de su tipo, :meth:`EntityParams.range`;
    ``nan`` y el infinito también) o ``des.entity_param_choice`` si un texto no es de su lista cerrada,
    nombrando la capa, la entidad, la clave del campo y el valor (RF-015-08: «la capa, la
    entidad, el campo y el valor»; la capa, desde la T11). ``required`` (por defecto, todo salvo lo
    opcional de su tipo: :attr:`EntityParams.optional`) lo cambia: ``False`` deja pasar un valor que no hace falta
    (el ancho de un eje que no es de línea, el resguardo de quien no protege); ``True`` exige uno opcional.
    :class:`TypeError` si el valor no es del tipo del parámetro (un número que llega como texto o como booleano, un
    decimal donde va un entero); :class:`ValueError` si el código o el parámetro no existen (errores del programa)."""
    spec = entity_params_of(code)
    name = str(param)
    key = entity_key(code, name)
    definition = spec.template(name)
    value_type = str(definition.value_type)
    if value is not None:
        if value_type == "bool":
            if not isinstance(value, bool):
                raise TypeError(f"el valor {key} es un sí/no, no {value!r}")
        elif value_type == "text":
            if not isinstance(value, str):
                raise TypeError(f"el valor {key} es un texto, no {value!r}")
            value = value.strip() or None
        elif value_type == "int":
            if isinstance(value, bool) or not isinstance(value, numbers.Integral):
                raise TypeError(f"el valor {key} es un número entero, no {value!r}")
            value = int(value)
        else:
            value = _real(value, f"el valor {key}")
    obj = f"{spec.label or 'Entidad'} «{entity}»"
    if value is None:
        if (name not in spec.optional) if required is None else required:
            raise DesignError("des.entity_param_missing", obj=obj, field=key, value=None,
                              entity=entity, layer=layer)
        return None
    if definition.choices and value not in definition.choices:
        listed = ", ".join(f"«{choice}»" for choice in definition.choices)
        raise DesignError("des.entity_param_choice", obj=obj, field=key, value=value,
                          entity=entity, layer=layer, choices=listed)
    span = spec.range(name)
    if span is not None:
        if not span.contains(value):
            raise DesignError("des.entity_param_range", obj=obj, field=key, value=value,
                              entity=entity, layer=layer, range=span.text())
        return int(value) if value_type == "int" else float(value)  # type: ignore[arg-type]
    return value  # type: ignore[return-value]
