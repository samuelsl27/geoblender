# SPDX-License-Identifier: GPL-3.0-or-later
"""CRS y datum vertical de lo que se importa (spec 006, T11; plan 006 §5.1 y §5.3.3; D-2).

Dominio puro: las transformaciones las da el puerto ``gis.ports.CrsService`` (pyproj, en
``adapters.pyproj_crs``), que se recibe por argumento o se resuelve con
``adapters.registry`` dentro de una función (ARQ-07).

- :class:`Declaration`: el CRS horizontal y la referencia vertical que declara una fuente
  (el fichero o, si este no los trae, el usuario). :meth:`Declaration.require` los exige
  (RF-006-04): nunca se suponen los del proyecto.
- Reglas de comparación (RF-006-05): misma referencia (mismo código EPSG horizontal y la
  misma referencia vertical) → sin transformación (:func:`needs_transform`); si no, la del
  servicio, y solo si su precisión es conocida (:func:`transformation_for`; si no,
  ``gis.transform_unknown_accuracy`` con los dos CRS). Una referencia local solo se compara
  por identidad: con otra referencia no hay transformación posible.
- Informe de transformación (RF-006-05): :func:`transform_summary`, la descripción, la
  precisión en m y las rejillas, para el informe de la importación.
- Coordenadas tecleadas (RF-006-07): :func:`transform_coordinates`, con el factor de escala
  y la convergencia de cuadrícula en el destino.
- Disponibilidad del servicio (RF-006-31): :func:`crs_service_status` y
  :func:`require_crs_service`. Si pyproj no es la versión fijada, no carga o su ``proj.db``
  no coincide con el catálogo, las transformaciones quedan desactivadas con su mensaje y lo
  demás sigue: lo que no transforma no necesita el servicio.

Coordenadas: ABSOLUTAS en float64.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy import ndarray

from ..core.georef import CrsRef, VerticalRef
from .messages import GisError, format_value
from .ports import CrsService, CrsServiceUnavailable, Transform, TransformInfo

__all__ = [
    "ELLIPSOIDAL_ETRS89",
    "CoordinateTransform",
    "CrsServiceStatus",
    "Declaration",
    "crs_service_status",
    "needs_transform",
    "reference_label",
    "require_crs_service",
    "service_error",
    "transform_coordinates",
    "transform_summary",
    "transformation_for",
]

type Resolver = Callable[[], CrsService]
"""Lo que da el servicio de CRS (por defecto, ``adapters.registry.crs_service``)."""

ELLIPSOIDAL_ETRS89 = VerticalRef(
    kind="ellipsoidal", epsg=None, name="Altura elipsoidal ETRS89", wkt2=None, note=None
)
"""Alturas sobre el elipsoide (GNSS o dron sin geoide): solo para declarar fuentes, nunca la
referencia de un proyecto (plan 006 §5.3.3: EPSG:4937 en geográficas)."""

CRS_FIELD = "CRS horizontal"
VERTICAL_FIELD = "datum vertical"
TRANSFORM_FIELD = "transformación"
SERVICE_OBJ = "Transformaciones de coordenadas"
SAME_REFERENCE = "Sin transformación: el mismo CRS y la misma referencia vertical"

_ELLIPSOIDAL_LABEL = "altura elipsoidal ETRS89"
_SERVICE_FIELDS = {
    "gis.crs_service_version": ("pyproj", "found"),
    "gis.crs_catalog_mismatch": ("catálogo de CRS", "crs"),
    "gis.crs_service_broken": ("pyproj", None),
}


def _vertical_label(vertical: VerticalRef) -> str:
    if vertical.kind == "epsg":
        return f"EPSG:{vertical.epsg}"
    if vertical.kind == "ellipsoidal":
        return _ELLIPSOIDAL_LABEL
    return f"{vertical.name} ({vertical.note})"


def reference_label(crs: CrsRef, vertical: VerticalRef) -> str:
    """El CRS con su referencia vertical, como se nombra en los mensajes y los informes:
    «EPSG:25830 + EPSG:5782», «EPSG:25830 + altura elipsoidal ETRS89» o «EPSG:23030 +
    Referencia local (NP-0 del plano 3)»."""
    return f"EPSG:{crs.epsg} + {_vertical_label(vertical)}"


@dataclass(frozen=True, slots=True)
class Declaration:
    """Lo que declara una fuente: ``source`` (su nombre, para los mensajes), su CRS
    horizontal y su referencia vertical (``None`` = no declarado)."""

    source: str
    crs: CrsRef | None
    vertical: VerticalRef | None

    def require(self) -> tuple[CrsRef, VerticalRef]:
        """El CRS y la referencia vertical declarados; si falta alguno, ``GisError``
        ``gis.crs_undeclared`` (primero) o ``gis.vertical_undeclared`` (RF-006-04)."""
        if self.crs is None:
            raise GisError(
                "gis.crs_undeclared", obj=self.source, field=CRS_FIELD, source=self.source
            )
        if self.vertical is None:
            raise GisError(
                "gis.vertical_undeclared",
                obj=self.source,
                field=VERTICAL_FIELD,
                source=self.source,
            )
        return self.crs, self.vertical


def needs_transform(
    src: CrsRef, src_v: VerticalRef, dst: CrsRef, dst_v: VerticalRef
) -> bool:
    """Verdadero si el CRS horizontal (código EPSG) o la referencia vertical difieren."""
    return src.epsg != dst.epsg or src_v != dst_v


def _local_mismatch(src_v: VerticalRef, dst_v: VerticalRef) -> bool:
    return "local" in (src_v.kind, dst_v.kind) and src_v != dst_v


def _unknown_accuracy(
    source: str, src: CrsRef, src_v: VerticalRef, dst: CrsRef, dst_v: VerticalRef
) -> GisError:
    return GisError(
        "gis.transform_unknown_accuracy",
        obj=source,
        field=TRANSFORM_FIELD,
        source_crs=reference_label(src, src_v),
        target_crs=reference_label(dst, dst_v),
        source=source,
    )


@dataclass(frozen=True, slots=True)
class CrsServiceStatus:
    """El servicio de CRS o, si no se puede usar, el error que lo explica (RF-006-31)."""

    service: CrsService | None
    error: GisError | None

    @property
    def available(self) -> bool:
        """Verdadero si hay servicio (las transformaciones están activas)."""
        return self.service is not None


def service_error(exc: CrsServiceUnavailable) -> GisError:
    """El ``GisError`` para el usuario de un servicio de CRS no disponible (RF-006-31)."""
    field, value_key = _SERVICE_FIELDS.get(exc.code, ("pyproj", None))
    value = exc.values.get(value_key) if value_key is not None else None
    return GisError(exc.code, obj=SERVICE_OBJ, field=field, value=value, **exc.values)


def require_crs_service(resolver: Resolver | None = None) -> CrsService:
    """El servicio de CRS (por defecto, el de ``adapters.registry``); si no se puede usar,
    ``GisError`` ``gis.crs_service_version``, ``gis.crs_catalog_mismatch`` o
    ``gis.crs_service_broken`` (RF-006-31)."""
    if resolver is None:
        from ..adapters import registry

        resolver = registry.crs_service
    try:
        return resolver()
    except CrsServiceUnavailable as exc:
        raise service_error(exc) from exc


def crs_service_status(resolver: Resolver | None = None) -> CrsServiceStatus:
    """Como :func:`require_crs_service`, pero sin lanzar: el estado que se comprueba al
    registrar la extensión y al arrancar un trabajo que transforma (RF-006-31)."""
    try:
        return CrsServiceStatus(require_crs_service(resolver), None)
    except GisError as exc:
        if exc.code not in _SERVICE_FIELDS:
            raise
        return CrsServiceStatus(None, exc)


def transformation_for(
    declaration: Declaration,
    target_crs: CrsRef,
    target_vertical: VerticalRef,
    *,
    service: CrsService | None = None,
    resolver: Resolver | None = None,
) -> Transform | None:
    """La transformación de lo declarado al CRS y la referencia vertical del proyecto, o
    ``None`` si son los mismos (sin pedir el servicio: RF-006-31, lo demás sigue).

    Exige la declaración (RF-006-04). Una referencia local distinta de la de destino, o una
    transformación sin precisión conocida, se rechaza con ``gis.transform_unknown_accuracy``
    nombrando los dos CRS (RF-006-05). Sin ``service``, lo da ``resolver`` o el registro."""
    src, src_v = declaration.require()
    if not needs_transform(src, src_v, target_crs, target_vertical):
        return None
    if _local_mismatch(src_v, target_vertical):
        raise _unknown_accuracy(declaration.source, src, src_v, target_crs, target_vertical)
    if service is None:
        service = require_crs_service(resolver)
    transform = service.transformer(src, src_v, target_crs, target_vertical)
    if transform.info.accuracy_m is None:
        raise _unknown_accuracy(declaration.source, src, src_v, target_crs, target_vertical)
    return transform


def transform_summary(info: TransformInfo) -> str:
    """El informe de una transformación (RF-006-05): «descripción; precisión 0,2 m;
    rejilla es_ign_SPED2ETV2.tif» (sin rejillas, sin la última parte; sin precisión
    conocida, «precisión desconocida»)."""
    parts = [info.description]
    if info.accuracy_m is None:
        parts.append("precisión desconocida")
    else:
        parts.append(f"precisión {format_value(float(info.accuracy_m))} m")
    if info.grids:
        label = "rejilla" if len(info.grids) == 1 else "rejillas"
        parts.append(f"{label} {', '.join(info.grids)}")
    return "; ".join(parts)


@dataclass(frozen=True, slots=True, eq=False)
class CoordinateTransform:
    """Coordenadas transformadas (RF-006-07): ``xyz`` float64 (n, 3) ABSOLUTAS en el
    destino, la transformación usada (``info``) y, en cada punto de destino, el factor de
    escala y la convergencia de cuadrícula en grados (positiva al este del meridiano
    central)."""

    xyz: ndarray
    info: TransformInfo
    scale_factor: ndarray
    convergence_deg: ndarray


def transform_coordinates(
    xyz: ndarray,
    src: CrsRef,
    src_v: VerticalRef,
    dst: CrsRef,
    dst_v: VerticalRef,
    *,
    service: CrsService | None = None,
    resolver: Resolver | None = None,
) -> CoordinateTransform:
    """Transforma coordenadas tecleadas (float64 (n, 3) ABSOLUTAS) de ``src`` + ``src_v`` a
    ``dst`` + ``dst_v`` y da el factor de escala y la convergencia en el destino
    (RF-006-07). La entrada no cambia. Sin precisión conocida (o con una referencia local
    distinta), ``gis.coordinates_unknown_accuracy``: no se muestra un resultado de precisión
    desconocida (principio 6). :class:`ValueError` si ``xyz`` no es (n, 3)."""
    values = np.array(xyz, dtype=np.float64, copy=True)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"las coordenadas deben ser (n, 3), no {values.shape}")
    if service is None:
        service = require_crs_service(resolver)
    if not needs_transform(src, src_v, dst, dst_v):
        info = TransformInfo(SAME_REFERENCE, 0.0)
        result = values
    else:
        info = None
        if not _local_mismatch(src_v, dst_v):
            transform = service.transformer(src, src_v, dst, dst_v)
            info = transform.info
        if info is None or info.accuracy_m is None:
            raise GisError(
                "gis.coordinates_unknown_accuracy",
                obj=SERVICE_OBJ,
                field=TRANSFORM_FIELD,
                source_crs=reference_label(src, src_v),
                target_crs=reference_label(dst, dst_v),
            )
        result = np.asarray(transform.apply(values), dtype=np.float64)
    xy = np.ascontiguousarray(result[:, :2])
    scale = np.asarray(service.scale_factor(dst, xy), dtype=np.float64)
    convergence = np.asarray(service.grid_convergence(dst, xy), dtype=np.float64)
    return CoordinateTransform(result, info, scale, convergence)
