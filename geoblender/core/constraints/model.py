# SPDX-License-Identifier: GPL-3.0-or-later
"""Los tipos de restricción, sus reglas y los datos de la spec 012 (plan 012 §5.2.1 y §5.3.1;
RF-012-01, RF-012-02, RF-012-04, RF-012-13, RF-012-26; D-16, D-22 y D-23).

- :class:`ConstraintType`: los once tipos (``ctype``), con su ``msgid`` y su español; qué
  parámetros pide cada uno (:attr:`~ConstraintType.requires`, D-23), en qué geometrías cabe
  (un límite, solo en un polígono) y qué prohíbe **dentro de su zona** (RF-012-13):
  :attr:`~ConstraintType.forbids_cut`, :attr:`~ConstraintType.forbids_fill` y
  :attr:`~ConstraintType.removes_from_domain`. Los dos límites (:attr:`~ConstraintType.is_limit`)
  prohíben **fuera**: los combinan las máscaras (``gis.masks``).
- :class:`ConstraintParam`: los cuatro parámetros de una restricción, sufijo de su clave
  (``core.constraint.{c}.<sufijo>``, :mod:`.params`).
- :class:`GeometryKind`: polígono, línea o punto (una capa del proyecto por geometría, D-20).
- :class:`Constraint`, :class:`Intention`, :class:`Sector`, :class:`SearchRecord` y
  :class:`SearchHit` (:class:`HitDecision`): las filas de las tablas del proyecto, con la
  geometría **absoluta en float64** (de solo lectura) tal como se guarda.
- :func:`constraint_code` y :func:`is_code`: el código inmutable de una restricción (D-22), que
  sale de su nombre al crearla o completarla y no cambia al renombrarla.

Python puro (``core``, nivel 0) con numpy; importarlo no registra nada.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

import numpy as np

from ..i18n import translate

__all__ = [
    "CODE_MAX_LENGTH",
    "Constraint",
    "ConstraintParam",
    "ConstraintType",
    "GeometryKind",
    "HitDecision",
    "Intention",
    "IntentionRole",
    "SearchHit",
    "SearchRecord",
    "Sector",
    "constraint_code",
    "is_code",
]

CODE_MAX_LENGTH = 32
"""La longitud máxima del código de una restricción (como el de una unidad de la 011)."""

_CODE = re.compile(r"[a-z][a-z0-9_]*")
_NOT_CODE = re.compile(r"[^a-z0-9]+")
_CODE_PREFIX = "r"
UNNAMED_MSGID = "Unnamed ({layer}, fid {fid})"
"""Lo que nombra una restricción sin nombre ni código (dibujada en QGIS)."""


class ConstraintParam(StrEnum):
    """Los parámetros de una restricción (RF-012-02): el sufijo de su clave."""

    BUFFER_OUT = "buffer_out_m"
    BUFFER_IN = "buffer_in_m"
    WEIGHT = "weight"
    ACTIVE = "active"


class GeometryKind(StrEnum):
    """La geometría de una restricción: una capa del proyecto por cada una (D-20)."""

    POLYGON = "polygon"
    LINE = "line"
    POINT = "point"

    @property
    def label_msgid(self) -> str:
        """Su nombre (``msgid``): «Polygon», «Line», «Point»."""
        return _KIND_LABELS[self][0]

    @property
    def article_msgid(self) -> str:
        """Su nombre con artículo, para una frase (``msgid``): «a polygon»…"""
        return _KIND_LABELS[self][1]

    def label(self, language: str = "es") -> str:
        """Su nombre en ``language``: «Polígono», «Línea», «Punto»."""
        return translate(language, self.label_msgid)


_KIND_LABELS: Mapping[GeometryKind, tuple[str, str]] = {
    GeometryKind.POLYGON: ("Polygon", "a polygon"),
    GeometryKind.LINE: ("Line", "a line"),
    GeometryKind.POINT: ("Point", "a point"),
}

_ALL_KINDS = (GeometryKind.POLYGON, GeometryKind.LINE, GeometryKind.POINT)
_POLYGON_ONLY = (GeometryKind.POLYGON,)
_OUT = (ConstraintParam.BUFFER_OUT, ConstraintParam.ACTIVE)


@dataclass(frozen=True, slots=True)
class _Rule:
    """La fila de un tipo en la tabla del plan §5.2.1."""

    msgid: str
    requires: tuple[ConstraintParam, ...]
    is_limit: bool = False
    forbids_cut: bool = False
    forbids_fill: bool = False
    removes_from_domain: bool = False


class ConstraintType(StrEnum):
    """Los once tipos de restricción (D-16; plan §5.2.1), en el orden de su tabla."""

    LEGAL_LIMIT = "legal_limit"
    ACTION_PERIMETER = "action_perimeter"
    UNTOUCHABLE = "untouchable"
    EXCLUSION = "exclusion"
    NO_CUT = "no_cut"
    FILL_ONLY = "fill_only"
    RESTORATION_ONLY = "restoration_only"
    SETBACK = "setback"
    NO_FILL = "no_fill"
    AVOID = "avoid"
    REQUIRES_ACCESS = "requires_access"

    @property
    def _rule(self) -> _Rule:
        return _RULES[self]

    @property
    def label_msgid(self) -> str:
        """Su nombre en la interfaz (``msgid`` en inglés; su español en ``messages.toml``)."""
        return self._rule.msgid

    def label(self, language: str = "es") -> str:
        """Su nombre en ``language`` («Banda de resguardo» para ``setback``)."""
        return translate(language, self.label_msgid)

    @property
    def requires(self) -> tuple[ConstraintParam, ...]:
        """Los parámetros que pide (D-23), en orden; «activa» siempre, la última."""
        return self._rule.requires

    @property
    def is_limit(self) -> bool:
        """Si es un límite (legal o perímetro de actuación): prohíbe fuera, no dentro."""
        return self._rule.is_limit

    @property
    def geometry_kinds(self) -> tuple[GeometryKind, ...]:
        """Las geometrías en que cabe: un límite, solo un polígono (D-23)."""
        return _POLYGON_ONLY if self.is_limit else _ALL_KINDS

    def accepts(self, kind: GeometryKind | str) -> bool:
        """Si una restricción de este tipo puede tener la geometría ``kind``."""
        return GeometryKind(kind) in self.geometry_kinds

    @property
    def forbids_cut(self) -> bool:
        """Si prohíbe el corte dentro de su zona (RF-012-13)."""
        return self._rule.forbids_cut

    @property
    def forbids_fill(self) -> bool:
        """Si prohíbe el relleno dentro de su zona (RF-012-13)."""
        return self._rule.forbids_fill

    @property
    def removes_from_domain(self) -> bool:
        """Si su zona sale del dominio por defecto (intocable y exclusión; RF-012-13)."""
        return self._rule.removes_from_domain


_FORBIDS_ALL = {"forbids_cut": True, "forbids_fill": True, "removes_from_domain": True}

_RULES: Mapping[ConstraintType, _Rule] = {
    ConstraintType.LEGAL_LIMIT: _Rule(
        "Legal limit", (ConstraintParam.BUFFER_IN, ConstraintParam.ACTIVE), is_limit=True),
    ConstraintType.ACTION_PERIMETER: _Rule(
        "Action perimeter", (ConstraintParam.ACTIVE,), is_limit=True),
    ConstraintType.UNTOUCHABLE: _Rule("Untouchable", _OUT, **_FORBIDS_ALL),
    ConstraintType.EXCLUSION: _Rule("Exclusion", _OUT, **_FORBIDS_ALL),
    ConstraintType.NO_CUT: _Rule("No cut", _OUT, forbids_cut=True),
    ConstraintType.FILL_ONLY: _Rule("Fill only", _OUT, forbids_cut=True),
    ConstraintType.RESTORATION_ONLY: _Rule("Restoration only", _OUT, forbids_cut=True),
    ConstraintType.SETBACK: _Rule("Setback band", _OUT, forbids_cut=True),
    ConstraintType.NO_FILL: _Rule("No fill", _OUT, forbids_fill=True),
    ConstraintType.AVOID: _Rule(
        "Preferably avoid",
        (ConstraintParam.BUFFER_OUT, ConstraintParam.WEIGHT, ConstraintParam.ACTIVE)),
    ConstraintType.REQUIRES_ACCESS: _Rule("Requires access", _OUT),
}


class IntentionRole(StrEnum):
    """Los seis roles de una marca del cliente (RF-012-26; plan §5.2.1)."""

    PROTECT = "protect"
    FILL = "fill"
    MINE_TO_ELEVATION = "mine_to_elevation"
    KEEP_AS_IS = "keep_as_is"
    PLATFORM = "platform"
    SLOPE_TO_TREAT = "slope_to_treat"

    @property
    def label_msgid(self) -> str:
        """Su nombre (``msgid`` en inglés)."""
        return _ROLE_LABELS[self]

    def label(self, language: str = "es") -> str:
        """Su nombre en ``language``."""
        return translate(language, self.label_msgid)

    @property
    def requires_elevation(self) -> bool:
        """Si pide una cota (solo «explotar a una cota»)."""
        return self is IntentionRole.MINE_TO_ELEVATION


_ROLE_LABELS: Mapping[IntentionRole, str] = {
    IntentionRole.PROTECT: "Protect",
    IntentionRole.FILL: "Fill",
    IntentionRole.MINE_TO_ELEVATION: "Mine to an elevation",
    IntentionRole.KEEP_AS_IS: "Keep as it is",
    IntentionRole.PLATFORM: "Platform",
    IntentionRole.SLOPE_TO_TREAT: "Slope to treat",
}


class HitDecision(StrEnum):
    """Lo que se decidió de una entidad hallada en una búsqueda (RF-012-08, RF-012-09)."""

    CONVERTED = "converted"
    DISCARDED = "discarded"


# --- Geometría ------------------------------------------------------------------------------


def _coords(points: object) -> np.ndarray:
    """Una copia de ``points`` como array float64 ``(k, 2)`` de solo lectura (los mismos bits);
    :class:`ValueError` si no tiene esa forma."""
    array = np.array(points, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2 or array.shape[0] == 0:
        raise ValueError(f"unas coordenadas son (k, 2) con k ≥ 1, no {array.shape}")
    array.flags.writeable = False
    return array


def _parts(parts: object) -> tuple[tuple[np.ndarray, ...], ...]:
    """Las partes (cada una, sus anillos o su camino) como tuplas de arrays absolutos."""
    if isinstance(parts, np.ndarray) or not isinstance(parts, Sequence):
        raise ValueError("las partes de una geometría son una secuencia de secuencias de "
                         "coordenadas (k, 2)")
    return tuple(tuple(_coords(item) for item in part) for part in parts)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


# --- Datos ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Constraint:
    """Una restricción del proyecto (RF-012-01, RF-012-02; una fila de ``core_constraint_*``).

    ``parts``: por cada parte, sus anillos (polígono: exterior y huecos), su camino (línea) o su
    punto, en coordenadas **absolutas** float64 ``(k, 2)`` de solo lectura. ``ctype`` es
    ``None`` si no tiene un tipo válido (dibujada en QGIS sin rellenarlo); ``code`` es ``''``
    hasta que se completa (D-22). ``layer`` y ``fid``: la capa del proyecto y la fila."""

    uid: str
    code: str
    name: str
    ctype: ConstraintType | None
    kind: GeometryKind
    parts: tuple[tuple[np.ndarray, ...], ...]
    priority: int
    reason: str | None
    decided_by: str | None
    decided_on: date | None
    decision_uid: str | None
    intention_uid: str | None
    source_input: str | None
    source_fid: int | None
    layer: str
    fid: int

    def __post_init__(self) -> None:
        if self.ctype is not None:
            object.__setattr__(self, "ctype", ConstraintType(self.ctype))
        object.__setattr__(self, "kind", GeometryKind(self.kind))
        object.__setattr__(self, "parts", _parts(self.parts))

    def param_key(self, param: ConstraintParam | str) -> str:
        """La clave de su parámetro ``param`` (``core.constraint.<código>.<sufijo>``), que
        depende de su código, no de su nombre; :class:`ValueError` sin un código válido."""
        if not is_code(self.code):
            raise ValueError(f"la restricción {self.fid} de {self.layer} no tiene un código "
                             f"válido ({self.code!r}): sus parámetros no tienen clave")
        return f"core.constraint.{self.code}.{ConstraintParam(param).value}"

    def shown_name(self, language: str = "es") -> str:
        """Lo que la nombra en una lista: su nombre, su código o su capa y su fid."""
        return shown_name(self.name, self.code, self.layer, self.fid, language)


def shown_name(name: str, code: str, layer: str, fid: int, language: str = "es") -> str:
    """El nombre visible de una restricción: ``name``, o ``code``, o «Sin nombre (capa, fid)»."""
    return _text(name) or _text(code) or translate(language, UNNAMED_MSGID, layer=layer,
                                                     fid=fid)


@dataclass(frozen=True, slots=True)
class Intention:
    """Una marca del cliente (RF-012-26; una fila de ``core_intention``): nunca entra en las
    máscaras. ``elevation_m`` solo (y siempre) en «explotar a una cota»."""

    uid: str
    name: str
    role: IntentionRole
    kind: GeometryKind
    parts: tuple[tuple[np.ndarray, ...], ...]
    elevation_m: float | None
    stated_on: date
    document_input: str
    decision_uid: str | None
    source_input: str
    source_fid: int
    fid: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", IntentionRole(self.role))
        object.__setattr__(self, "kind", GeometryKind(self.kind))
        object.__setattr__(self, "parts", _parts(self.parts))
        if self.role.requires_elevation != (self.elevation_m is not None):
            raise ValueError(f"la intención «{self.name}» ({self.role.value}): la cota va "
                             "solo, y siempre, con «explotar a una cota»")


@dataclass(frozen=True, slots=True)
class Sector:
    """Un sector de búsqueda de intocables (RF-012-07; una fila de ``core_sector``): sus
    anillos absolutos float64."""

    uid: str
    code: str
    name: str
    rings: tuple[np.ndarray, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rings", tuple(_coords(ring) for ring in self.rings))


@dataclass(frozen=True, slots=True)
class SearchRecord:
    """Una búsqueda de intocables cerrada (RF-012-09; ``core_untouchable_search``).
    ``sector_code`` ``''`` = el perímetro como único sector; ``closed_at`` en UTC."""

    uid: str
    operation_uid: str
    sector_code: str
    sector_sha256: str
    distance_m: float
    closed_by: str
    closed_at: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Una entidad hallada en una búsqueda y lo que se decidió (RF-012-08, RF-012-09;
    ``core_untouchable_hit``): convertida, con la restricción creada; o descartada; siempre con
    su motivo."""

    search_uid: str
    layer_dataset: str
    feature_fid: int
    distance_m: float
    attributes: Mapping[str, Any] = field(hash=False)
    decision: HitDecision
    reason: str
    constraint_code: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision", HitDecision(self.decision))
        if not _text(self.reason):
            raise ValueError(f"la entidad {self.feature_fid} de {self.layer_dataset}: falta "
                             "el motivo de la decisión")
        converted = self.decision is HitDecision.CONVERTED
        if converted != (self.constraint_code is not None):
            raise ValueError(f"la entidad {self.feature_fid} de {self.layer_dataset}: la "
                             "restricción creada va solo, y siempre, con «convertida»")


# --- Códigos --------------------------------------------------------------------------------


def is_code(code: object) -> bool:
    """Si ``code`` es un código de restricción bien formado (``[a-z][a-z0-9_]*``, D-22)."""
    return isinstance(code, str) and _CODE.fullmatch(code) is not None


def constraint_code(name: str, taken: Collection[str]) -> str:
    """El código de una restricción nueva o que se completa (D-22): su nombre en ASCII y en
    minúsculas, sin tildes y con «_» en lugar de lo demás (``Torre 132 kV`` → ``torre_132_kv``),
    con ``r_`` delante si no empieza por una letra (``r`` si no queda nada), de como mucho
    :data:`CODE_MAX_LENGTH` caracteres, y ``_2``, ``_3``… si ya está en ``taken`` (los códigos
    de las tres capas)."""
    plain = "".join(char for char in unicodedata.normalize("NFKD", name)
                    if not unicodedata.combining(char))
    base = _NOT_CODE.sub("_", plain.lower().encode("ascii", "ignore").decode("ascii"))
    base = base.strip("_")
    if not base:
        base = _CODE_PREFIX
    elif not base[0].isalpha():
        base = f"{_CODE_PREFIX}_{base}"
    base = base[:CODE_MAX_LENGTH].rstrip("_")
    candidate, number = base, 2
    while candidate in taken:
        suffix = f"_{number}"
        candidate = base[:CODE_MAX_LENGTH - len(suffix)].rstrip("_") + suffix
        number += 1
    return candidate
