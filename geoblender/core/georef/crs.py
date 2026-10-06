# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo de CRS de Geoblender (spec 002; RF-002-03, RF-002-23; ADR-0005, ADR-0019).

Un proyecto declara siempre su CRS horizontal (proyectado, en metros) y su CRS vertical
(en metros) o una «referencia local» con descripción; nunca se suponen (constitución,
principio 6). Los dos salen de un catálogo cerrado: un extracto del EPSG Dataset (IOGP)
generado una vez con PROJ por ``tools/gen_crs_catalog.py`` y guardado sin modificar en
``thirdparty/epsg/crs_catalog.json`` (ADR-0019). Así el resultado es el mismo en
cualquier equipo y no depende de ``PROJ_LIB``, ``PROJ_DATA`` ni ``GDAL_DATA`` (en el
equipo de IMGA, ``PROJ_LIB`` apuntaba al ``proj.db`` de PostGIS: Silvestre TOP-05). Aquí
nada reproyecta: las transformaciones llegan con la spec 006 (D-1).

Coordenadas: ``CrsRef.bounds`` es el ámbito del CRS en sus coordenadas proyectadas
(absolutas, m), calculado al generar el catálogo; ``CrsRef.bbox_lonlat``, su ámbito
geográfico (grados de su CRS base), y ``CrsRef.projection``, los parámetros de su
transversa de Mercator leídos de su WKT1, con los que se comprueba el huso extendido
(D-12; ``core.georef.tm``).
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..errors import GeoblenderError, ValidationError
from .tm import TransverseMercator

# El catálogo vive en thirdparty/epsg/ del paquete raíz (core/georef/crs.py → raíz).
CATALOG_PATH: Path = (
    Path(__file__).resolve().parents[2] / "thirdparty" / "epsg" / "crs_catalog.json"
)
CATALOG_FORMAT = "geoblender-crs-catalog"
CATALOG_SCHEMA = 1

DEFAULT_HORIZONTAL_EPSG = 25830  # ETRS89 / UTM zone 30N (ADR-0005)
DEFAULT_VERTICAL_EPSG = 5782  # Alicante height (spec 002, D-2)
LOCAL_VERTICAL_NAME = "Referencia local"

VerticalKind = Literal["epsg", "local", "ellipsoidal"]
VERTICAL_KINDS: tuple[str, ...] = ("epsg", "local", "ellipsoidal")

# WKT1 de una proyección UTM: SPHEROID["nombre",a,1/f], PROJECTION["…"], PARAMETER["…",v].
_WKT1_SPHEROID = re.compile(r'SPHEROID\["[^"]*",([-+0-9.eE]+),([-+0-9.eE]+)')
_WKT1_PROJECTION = re.compile(r'PROJECTION\["([^"]+)"')
_WKT1_PARAMETER = re.compile(r'PARAMETER\["([^"]+)",([-+0-9.eE]+)\]')
_TM_PROJECTION = "Transverse_Mercator"
_TM_PARAMETERS = (
    "latitude_of_origin", "central_meridian", "scale_factor", "false_easting", "false_northing",
)

_OBJ = "Catálogo de CRS"
_HORIZONTAL_FIELD = "CRS horizontal"
_VERTICAL_FIELD = "CRS vertical"


@dataclass(frozen=True)
class CrsRef:
    """Un CRS horizontal proyectado en metros (ejes Este y Norte) del catálogo.

    ``bounds`` = (xmin, ymin, xmax, ymax), la envolvente de su ámbito en coordenadas
    absolutas (m); ``bbox_lonlat`` = (oeste, sur, este, norte), su ámbito geográfico en
    grados; ``projection``, su transversa de Mercator (del WKT1); ``area``, la descripción
    del ámbito que da EPSG.
    """

    epsg: int
    name: str
    wkt2: str
    wkt1: str
    bounds: tuple[float, float, float, float]
    bbox_lonlat: tuple[float, float, float, float]
    projection: TransverseMercator
    area: str = ""

    @property
    def utm_zone(self) -> int:
        """El número del huso UTM de su meridiano central (−3° → 30)."""
        return round((self.projection.lon0 + 183.0) / 6.0)

    def contains(self, xmin: float, ymin: float, xmax: float, ymax: float) -> bool:
        """Verdadero si el rectángulo absoluto (m) cae entero dentro de la envolvente
        proyectada del ámbito (``bounds``). El ámbito y el huso extendido de una ventana de
        trabajo se comprueban en geográficas (``core.project.create.check_window_inside``)."""
        left, bottom, right, top = self.bounds
        return left <= xmin <= xmax <= right and bottom <= ymin <= ymax <= top


def transverse_mercator(wkt1: str) -> TransverseMercator:
    """Los parámetros de la transversa de Mercator de un WKT1 (``PROJECTION
    ["Transverse_Mercator"]``, latitud de origen en el ecuador); :class:`ValueError` si
    no lo es o le falta un parámetro."""
    projection = _WKT1_PROJECTION.search(wkt1)
    if projection is None or projection.group(1) != _TM_PROJECTION:
        found = projection.group(1) if projection is not None else "ninguna"
        raise ValueError(f"el WKT1 no es una transversa de Mercator ({found})")
    spheroid = _WKT1_SPHEROID.search(wkt1)
    if spheroid is None:
        raise ValueError("el WKT1 no tiene SPHEROID")
    parameters = {name: float(value) for name, value in _WKT1_PARAMETER.findall(wkt1)}
    missing = [name for name in _TM_PARAMETERS if name not in parameters]
    if missing:
        raise ValueError(f"al WKT1 le faltan los parámetros {', '.join(missing)}")
    if parameters["latitude_of_origin"] != 0.0:
        raise ValueError(
            "la latitud de origen de la transversa de Mercator no es el ecuador "
            f"({parameters['latitude_of_origin']})"
        )
    return TransverseMercator(
        a=float(spheroid.group(1)),
        inv_f=float(spheroid.group(2)),
        lon0=parameters["central_meridian"],
        k0=parameters["scale_factor"],
        fe=parameters["false_easting"],
        fn=parameters["false_northing"],
    )


@dataclass(frozen=True)
class VerticalRef:
    """Referencia de las cotas.

    - ``"epsg"``: un CRS vertical del catálogo (código y WKT2, sin nota);
    - ``"local"``: una referencia local con descripción obligatoria (sin código ni WKT);
    - ``"ellipsoidal"``: altura sobre el elipsoide, solo para declarar fuentes (spec 006);
      un proyecto es siempre ``"epsg"`` o ``"local"`` (RF-002-03, RF-002-23).
    """

    kind: VerticalKind
    epsg: int | None
    name: str
    wkt2: str | None
    note: str | None

    def __post_init__(self) -> None:
        if self.kind not in VERTICAL_KINDS:
            raise ValueError(
                f"tipo de referencia vertical desconocido {self.kind!r}; válidos: "
                f"{', '.join(VERTICAL_KINDS)}"
            )
        if not self.name:
            raise ValueError("una referencia vertical necesita nombre")
        if self.kind == "epsg" and (
            not isinstance(self.epsg, int) or not self.wkt2 or self.note is not None
        ):
            raise ValueError(
                "una referencia vertical EPSG lleva código y WKT2, y no nota"
            )
        if self.kind == "local" and (
            self.epsg is not None
            or self.wkt2 is not None
            or not isinstance(self.note, str)
            or not self.note.strip()
        ):
            raise ValueError(
                "una referencia vertical local lleva descripción, y ni código ni WKT2"
            )


def _check_code(code: object, field: str) -> int:
    if isinstance(code, bool) or not isinstance(code, int):
        raise ValidationError(
            "core.crs_code_invalid",
            "el código EPSG debe ser un número entero (p. ej. 25830)",
            obj=_OBJ,
            field=field,
            value=code,
        )
    return code


class CrsCatalog:
    """Los CRS que admite Geoblender, en el orden del catálogo."""

    def __init__(
        self,
        horizontals: Iterable[CrsRef],
        verticals: Iterable[VerticalRef],
        source: Mapping[str, Any],
    ) -> None:
        self._horizontals = tuple(horizontals)
        self._verticals = tuple(verticals)
        self._by_code: dict[int, CrsRef | VerticalRef] = {}
        for ref in (*self._horizontals, *self._verticals):
            if ref.epsg in self._by_code:
                raise ValueError(f"EPSG:{ref.epsg} está dos veces en el catálogo")
            self._by_code[ref.epsg] = ref  # type: ignore[index]
        self._source = dict(source)

    @property
    def source(self) -> dict[str, Any]:
        """Origen de los datos: EPSG Dataset (IOGP), versiones de EPSG y de PROJ,
        términos de uso y atribución (ADR-0019)."""
        return dict(self._source)

    def horizontals(self) -> tuple[CrsRef, ...]:
        """Los CRS horizontales del catálogo."""
        return self._horizontals

    def verticals(self) -> tuple[VerticalRef, ...]:
        """Los CRS verticales EPSG del catálogo (sin la referencia local)."""
        return self._verticals

    def _missing(self, code: int, field: str, codes: Iterable[int]) -> ValidationError:
        listed = ", ".join(str(item) for item in codes)
        return ValidationError(
            "core.crs_not_in_catalog",
            f"no está en el catálogo de CRS de Geoblender; elija uno de: {listed}",
            obj=_OBJ,
            field=field,
            value=code,
            shown=f"EPSG:{code}",
        )

    def horizontal(self, epsg: object) -> CrsRef:
        """El CRS horizontal ``epsg``; :class:`ValidationError` si no está en el
        catálogo o no es horizontal."""
        code = _check_code(epsg, _HORIZONTAL_FIELD)
        ref = self._by_code.get(code)
        if ref is None:
            codes = [item.epsg for item in self._horizontals]
            raise self._missing(code, _HORIZONTAL_FIELD, codes)
        if not isinstance(ref, CrsRef):
            raise ValidationError(
                "core.crs_not_horizontal",
                f"«{ref.name}» es un CRS vertical; aquí hace falta un CRS horizontal "
                f"proyectado en metros (p. ej. EPSG:{DEFAULT_HORIZONTAL_EPSG})",
                obj=_OBJ,
                field=_HORIZONTAL_FIELD,
                value=code,
                shown=f"EPSG:{code}",
            )
        return ref

    def vertical(self, epsg: object) -> VerticalRef:
        """El CRS vertical ``epsg``; :class:`ValidationError` si no está en el catálogo
        o no es vertical."""
        code = _check_code(epsg, _VERTICAL_FIELD)
        ref = self._by_code.get(code)
        if ref is None:
            codes = [item.epsg for item in self._verticals if item.epsg is not None]
            raise self._missing(code, _VERTICAL_FIELD, codes)
        if not isinstance(ref, VerticalRef):
            raise ValidationError(
                "core.crs_not_vertical",
                f"«{ref.name}» es un CRS horizontal; aquí hace falta un CRS vertical en "
                f"metros (p. ej. EPSG:{DEFAULT_VERTICAL_EPSG}) o una referencia local con "
                "descripción",
                obj=_OBJ,
                field=_VERTICAL_FIELD,
                value=code,
                shown=f"EPSG:{code}",
            )
        return ref

    def local_vertical(self, note: object) -> VerticalRef:
        """Una «referencia local» con su descripción (obligatoria, sin espacios de más)."""
        if not isinstance(note, str) or not note.strip():
            raise ValidationError(
                "core.vcrs_note_required",
                "una referencia local necesita una descripción que diga a qué se refieren "
                "las cotas (p. ej. «NP-0 del plano 3»)",
                obj=_VERTICAL_FIELD,
                field="descripción de la referencia local",
                value=note,
            )
        return VerticalRef(
            kind="local", epsg=None, name=LOCAL_VERTICAL_NAME, wkt2=None, note=note.strip()
        )


def _invalid(path: Path, reason: str) -> GeoblenderError:
    return GeoblenderError(
        "core.crs_catalog_invalid",
        f"{reason}; reinstale Geoblender (el catálogo forma parte de la extensión)",
        obj=_OBJ,
        field="fichero",
        value=path.name,
        context={"path": str(path)},
    )


def _horizontal(entry: Mapping[str, Any]) -> CrsRef:
    code = entry["epsg"]
    projected = entry["type"] == "projected" and entry["unit"] == "metre"
    if not projected or entry["axes"] != ["E", "N"]:
        raise ValueError(f"EPSG:{code} no es proyectado en metros con ejes E, N")
    bounds = tuple(float(value) for value in entry["bounds"])
    if len(bounds) != 4:
        raise ValueError(f"EPSG:{code}: el ámbito proyectado no tiene 4 valores")
    bbox = tuple(float(value) for value in entry["bbox_lonlat"])
    if len(bbox) != 4 or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise ValueError(f"EPSG:{code}: el ámbito geográfico no es (oeste, sur, este, norte)")
    try:
        projection = transverse_mercator(str(entry["wkt1"]))
    except ValueError as exc:
        raise ValueError(f"EPSG:{code}: {exc}") from exc
    return CrsRef(
        epsg=int(entry["epsg"]),
        name=str(entry["name"]),
        wkt2=str(entry["wkt2"]),
        wkt1=str(entry["wkt1"]),
        bounds=bounds,  # type: ignore[arg-type]
        bbox_lonlat=bbox,  # type: ignore[arg-type]
        projection=projection,
        area=str(entry["area"]),
    )


def _vertical(entry: Mapping[str, Any]) -> VerticalRef:
    if entry["type"] != "vertical" or entry["unit"] != "metre":
        raise ValueError(f"EPSG:{entry['epsg']} no es un CRS vertical en metros")
    return VerticalRef(
        kind="epsg",
        epsg=int(entry["epsg"]),
        name=str(entry["name"]),
        wkt2=str(entry["wkt2"]),
        note=None,
    )


def read_catalog(path: Path) -> CrsCatalog:
    """Lee y valida el catálogo de ``path`` (sin caché); :class:`GeoblenderError` si no
    se puede leer o no tiene la forma esperada."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid(Path(path), f"no se puede leer ({exc})") from exc
    if not isinstance(data, dict) or data.get("format") != CATALOG_FORMAT:
        raise _invalid(Path(path), f"no es un catálogo de CRS ({CATALOG_FORMAT})")
    if data.get("schema") != CATALOG_SCHEMA:
        raise _invalid(
            Path(path),
            f"tiene la versión {data.get('schema')!r} y esta versión de Geoblender lee la "
            f"{CATALOG_SCHEMA}",
        )
    try:
        horizontals = [_horizontal(entry) for entry in data["horizontal"]]
        verticals = [_vertical(entry) for entry in data["vertical"]]
        return CrsCatalog(horizontals, verticals, data["source"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid(Path(path), f"tiene una entrada no válida ({exc})") from exc


@functools.cache
def load_catalog() -> CrsCatalog:
    """El catálogo de la extensión (``CATALOG_PATH``), leído una sola vez."""
    return read_catalog(CATALOG_PATH)
