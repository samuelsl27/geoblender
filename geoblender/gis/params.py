# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de topografía (spec 006; plan 006 §5.2.5 y §5.6.1; ADR-0013;
formato-proyecto.md §3.3).

Cada valor que cambia un resultado de ``gis`` (tolerancias, fracción mínima, umbrales) es un
parámetro con **clave, tipo de valor, unidad, rango, valor por defecto, tipo y procedencia**:
el código lo lee de aquí con su clave y nunca lo escribe a mano (principio 2). Todos son
ADOPTADO de origen ``algorithm`` (``gb_parameter.source_kind``): los fija el método, no una
medida ni una norma.

- :class:`ParamDef` es el de ``core.params`` (spec 008; plan 006 §5.6.1): ``gis`` declara
  aquí sus definiciones y no define la clase. :meth:`ParamDef.check` comprueba un valor
  (tipo y rango) y lo devuelve normalizado, o lanza ``core.params.ParamError``
  (``core.param_not_number``, ``core.param_not_integer``, ``core.param_not_list`` o
  ``core.param_out_of_range``, con la clave como campo): un código por problema, sin
  envoltorio en ``gis``.
- :data:`DEFINITIONS`, las de la tabla del plan §5.2.5, cada una con su etiqueta
  (``label_msgid``, con su español en ``core/i18n/messages.toml``) para el panel de
  parámetros (RF-008-06); y :data:`PARAMS`, por clave (:func:`index_definitions`, que no
  admite claves repetidas).
- :func:`param` y :func:`default`: la definición y el valor por defecto de una clave.

Tipos de valor, los de ``gb_parameter.value_type``: ``float``, ``int`` y ``json`` (aquí,
siempre una lista de ``length`` números en orden creciente, cada uno dentro del rango). La
unidad ``-`` es la de lo adimensional. Los rangos los decide esta definición (el plan solo
fija los valores por defecto), salvo el de ``gis.tin.blender_cdt_max_s``: nunca más de 2 s,
el final de la excepción del principio 9 (plan §9, D-12).

``bl`` registra estas definiciones en ``core.params`` (``register_definitions``) y las quita
con ``unregister_definitions("gis")``; el valor de cada operación sale del proyecto
(``ParameterStore``), y :func:`default` es el valor inicial (plan §5.6.1).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from ..core.params import ParamDef, ParamValue
from ..core.units import DIMENSIONLESS

__all__ = [
    "DEFINITIONS",
    "PARAMS",
    "ParamDef",
    "ParamValue",
    "default",
    "index_definitions",
    "param",
]


def index_definitions(definitions: Iterable[ParamDef]) -> Mapping[str, ParamDef]:
    """Las definiciones por clave (solo lectura); :class:`ValueError` si una clave se
    repite (un duplicado no se pierde en silencio)."""
    index: dict[str, ParamDef] = {}
    for definition in definitions:
        if definition.key in index:
            raise ValueError(f"la clave de parámetro «{definition.key}» está repetida")
        index[definition.key] = definition
    return MappingProxyType(index)


_D4 = "Spec 006, D-4 (DP-43): sin dato salvo cobertura total"
_D5 = "Spec 006, D-5 (DP-44): 1 mm en planta y 0,01 m en cota"
_A12 = "Plan 006 §5.2.5 y A12 (TIN desde curvas)"
_CONTOURS = "Spec 006 §11: curvas del terreno (R-61 fija las de los diseños)"

DEFINITIONS: tuple[ParamDef, ...] = (
    ParamDef("gis.resample.min_valid_fraction", "float", DIMENSIONLESS, 1.0, 0.0, 1.0,
             ("RF-006-11",), _D4, min_exclusive=True,
             label_msgid="Minimum valid fraction of a cell"),
    ParamDef("gis.reproject.supersample", "int", DIMENSIONLESS, 4, 1, 16,
             ("RF-006-05",), "Plan 006 §6, D7: submuestreo de 4 × 4 por celda",
             label_msgid="Subsamples per cell side when reprojecting"),
    ParamDef("gis.points.dup_xy_tol_m", "float", "m", 0.001, 0.0, 1.0,
             ("RF-006-14",), _D5, min_exclusive=True,
             label_msgid="Horizontal tolerance for duplicate points"),
    ParamDef("gis.points.dup_z_tol_m", "float", "m", 0.01, 0.0, 1.0,
             ("RF-006-14",), _D5,
             label_msgid="Elevation tolerance for duplicate points"),
    ParamDef("gis.tin.contour_densify_m", "float", "m", 5.0, 0.0, 100.0,
             ("RF-006-16",), _A12, min_exclusive=True,
             label_msgid="Spacing when densifying contours"),
    ParamDef("gis.tin.flat_max_passes", "int", DIMENSIONLESS, 3, 0, 10,
             ("RF-006-16",), _A12,
             label_msgid="Flat triangle correction passes"),
    ParamDef("gis.tin.max_flat_pct", "float", "%", 1.0, 0.0, 100.0,
             ("RF-006-16",), "Spec 006, RF-006-16 (D-6)",
             label_msgid="Maximum share of flat triangles"),
    ParamDef("gis.tin.blender_cdt_max_s", "float", "s", 2.0, 0.0, 2.0,
             ("RF-006-13", "RF-006-28"),
             "Plan 006 §9, D-12 (DP-54): excepción del principio 9, hasta 2 s",
             label_msgid="Time limit of the Blender triangulation in the interface"),
    ParamDef("gis.contours.interval_m", "float", "m", 1.0, 0.0, 1000.0,
             ("RF-006-18",), _CONTOURS, min_exclusive=True,
             label_msgid="Contour interval"),
    ParamDef("gis.contours.index_every_m", "float", "m", 5.0, 0.0, 10000.0,
             ("RF-006-18",), _CONTOURS, min_exclusive=True,
             label_msgid="Index contour interval"),
    ParamDef("gis.contours.index_offset_m", "float", "m", 0.0, -100.0, 100.0,
             ("RF-006-18",), _CONTOURS,
             label_msgid="Index contour offset"),
    ParamDef("gis.contours.simplify_m", "float", "m", 0.0, 0.0, 100.0,
             ("RF-006-18",), _CONTOURS,
             label_msgid="Contour simplification tolerance"),
    ParamDef("gis.contours.min_length_m", "float", "m", 0.0, 0.0, 10000.0,
             ("RF-006-18",), _CONTOURS,
             label_msgid="Minimum contour length"),
    ParamDef("gis.vertical.ellipsoidal_band_m", "json", "m", (40.0, 60.0), 0.0, 200.0,
             ("RF-006-06",), "Spec 006, D-8 (DP-46): península y Baleares", length=2,
             label_msgid="Band of suspected ellipsoidal heights"),
    ParamDef("gis.validate.z_range_m", "json", "m", (-500.0, 5000.0), -11000.0, 9000.0,
             ("RF-006-23",), "Spec 006 §11: rango plausible de cotas", length=2,
             label_msgid="Plausible elevation range"),
    ParamDef("gis.import.max_cells", "int", DIMENSIONLESS, 100_000_000, 1, 100_000_000,
             ("RF-006-09",), "Spec 006 §8 y §11 (memoria: RNF-006-08)",
             label_msgid="Maximum cells of an imported grid"),
    ParamDef("gis.view.lod_steps_m", "json", "m", (2.0, 5.0), 0.5, 100.0,
             ("RF-006-22",), "Spec 006, RF-006-22: versiones de 2 y 5 m", length=2,
             label_msgid="Grid steps of the levels of detail"),
)
"""Los parámetros de la tabla del plan 006 §5.2.5, en su orden."""

PARAMS: Mapping[str, ParamDef] = index_definitions(DEFINITIONS)
"""Las definiciones por clave (solo lectura)."""


def param(key: str) -> ParamDef:
    """La definición de ``key``; :class:`KeyError` si no es un parámetro de ``gis`` (un
    error del programa)."""
    try:
        return PARAMS[key]
    except KeyError:
        raise KeyError(f"«{key}» no es un parámetro de gis (gis/params.py)") from None


def default(key: str) -> ParamValue:
    """El valor por defecto de ``key`` (ADOPTADO; ningún parámetro de ``gis`` admite «sin
    valor»)."""
    return param(key).default  # type: ignore[return-value]
