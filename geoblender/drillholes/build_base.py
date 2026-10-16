# SPDX-License-Identifier: GPL-3.0-or-later
"""La base de los sondeos desde lo importado (spec 005, T41; RF-005-02, RF-005-08, RF-005-11,
RF-005-22, RF-005-27 a RF-005-29; plan 005 §5.6.1, D17, D21 y D22).

La operación ``dh.build_base`` ensambla las once tablas de la base
(``drillholes.schema.BASE_TABLES``) desde lo importado vigente de cada entrada (D-15: una por
fichero, por hoja de un XLSX; la base de RecMin, una). :func:`build_base` recibe sus
:class:`SourceEntry` **en el orden en que se registraron** (la última, la más reciente): las
filas de sus ``dh_src_*`` ya interpretadas, en el CRS, el datum y los convenios que declara su
entrada (``declaration``), sin transformar y con el sondeo por su nombre. Da las
:class:`BaseTables`: la base en columnas (un ``DrillholeSet`` en el CRS y el datum del
proyecto), las filas de cada tabla, las transformaciones usadas y lo que no pasa. Dominio
puro: la llama el trabajo ``dh_build_base``, que no abre el proyecto.

**Precedencia** (RF-005-11): por sondeo y tabla, la entrada **registrada más tarde que trae
filas** de ese sondeo en esa tabla (lo que el usuario «conserva» no se importa: no está en lo
importado); por código de catálogo, la más reciente que lo trae. Las estaciones de un sondeo
son las medidas de la entrada más reciente que las trae; si ninguna las trae, la orientación
en boca de la entrada de su boca; si tampoco, con «todos verticales» declarado en esa entrada,
una vertical a 0 m (spec §8: lo que hace ``interop.drillholes_tabular.read_drillholes`` en una
importación entera). Los sondeos y los códigos se comparan sin los espacios exteriores ni las
mayúsculas (``model.name_key``).

**Conversiones** (D21), con la declaración de la entrada de cada fila:

- las bocas, del CRS y el datum de su entrada a los del proyecto con
  ``gis.crs.transformation_for`` y el ``CrsService`` (RF-005-08: X, Y y Z; una cota
  elipsoidal llega al datum del proyecto con la rejilla del geoide); cada transformación, con
  su precisión, en :attr:`BaseTables.transforms`; una boca que la transformación no da queda
  sin coordenadas, y se dice;
- las estaciones (``conventions.convert_surveys``): inclinación negativa hacia abajo
  (RF-005-28) y azimut de la cuadrícula del proyecto (RF-005-27) con la convergencia γ de cada
  boca en el CRS del proyecto (una llamada al servicio para todas); un azimut de cuadrícula de
  unas bocas declaradas en otro CRS pasa a la del proyecto con A_g + γ_origen − γ_proyecto, y
  guarda esa γ neta;
- las leyes, a la unidad de su elemento en el catálogo de la base (RF-005-29,
  ``conventions.convert_assays``), con el valor y la unidad originales;
- la profundidad que falta, deducida de las filas de la base (``validate.deduce_depths``,
  DH-W16).

**Lo que no pasa** (:class:`BuildNote`): un sondeo repetido en las bocas de su entrada
(DH-E01), con sus filas; las filas de un sondeo sin boca en la base (DH-E04); las de un código
que no está en los catálogos de la base (DH-E11; una referencia opcional, el sector o el grupo
de una boca y la zona de una estructura, queda vacía y la fila pasa). La base no admite nada
de eso (claves sin ``NULL``, nombres únicos): lo dicen el informe y estas notas.

**Identificadores deterministas** (RF-008-26): las filas de cada tabla van en el orden de su
``fid`` (desde 1, la tabla se escribe de nuevo): las bocas por su nombre sin mayúsculas, con el
``uid`` de ``schema.hole_uid``; los catálogos por su código; lo demás por sondeo y profundidad
y, si empatan, por el resto de sus columnas. ``hole_id``, ``lithology_id``… son esas
posiciones. El mismo contenido da las mismas filas, byte a byte, en cualquier orden, y el
mismo hash (``schema.table_digest``).

**Huella de la desviación** (RF-005-22, D22): ``survey_sha256`` de cada boca es el sha256 de su
X, Y, Z y profundidad y de sus estaciones ya convertidas (profundidad, azimut, inclinación y
origen, en orden): cambia solo si cambia lo que da su traza. :func:`changed_holes` da los
sondeos cuya huella cambia (el ``detail`` de ``dh_collar``).

**Sin bucles por fila** (plan §5.4): la precedencia, los enlaces, las conversiones y el orden
son de numpy; los nombres y los códigos se comparan por sus textos distintos; por sondeo solo
se calculan la huella, el ``uid`` y la geometría, y por fila solo se escribe el JSON de
``extra``. Las entradas no cambian. Python puro y numpy (ADR-0004); ``gis`` se importa al
transformar.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.georef import CrsRef, VerticalRef
from ..core.gpkg.base import ColumnDef
from ..core.gpkg.wkb import encode_geometry
from ..core.hashing import canonical_json
from .conventions import collar_convergence, convert_assays, convert_surveys
from .model import (
    TABLES,
    AssayColumns,
    AzimuthRef,
    Catalogs,
    CollarColumns,
    DrillholeSet,
    IntervalColumns,
    SourceDeclaration,
    StationSource,
    StructureColumns,
    SurveyColumns,
    ZoneColumns,
    name_key,
)
from .schema import BASE_TABLES, LAYOUTS, hole_uid
from .validate import deduce_depths

if TYPE_CHECKING:
    from ..gis.ports import CrsService, Transform, TransformInfo

__all__ = [
    "NOTE_DUPLICATE",
    "NOTE_NOT_TRANSFORMED",
    "NOTE_UNKNOWN_CODE",
    "NOTE_WITHOUT_COLLAR",
    "SET_TABLES",
    "SURVEY_HASH_TAG",
    "BaseTables",
    "BuildNote",
    "SourceEntry",
    "SourceTransform",
    "build_base",
    "changed_holes",
]

SET_TABLES: Mapping[str, str] = MappingProxyType({
    "collars": "dh_collar",
    "surveys": "dh_survey",
    "lithology": "dh_lithology",
    "assays": "dh_assay",
    "zones": "dh_zone_interval",
    "structures": "dh_structure",
})
"""La tabla de la base de cada tabla de un ``DrillholeSet``."""
NOTE_DUPLICATE = "dh.base_duplicate_hole"
"""Un sondeo repetido en las bocas de su entrada (DH-E01): ni su boca ni sus filas pasan."""
NOTE_WITHOUT_COLLAR = "dh.base_without_collar"
"""Filas de un sondeo sin boca en la base (DH-E04): no pasan."""
NOTE_UNKNOWN_CODE = "dh.base_unknown_code"
"""Filas con un código que no está en los catálogos de la base (DH-E11)."""
NOTE_NOT_TRANSFORMED = "dh.base_not_transformed"
"""Una boca que la transformación de su entrada no da (fuera de su ámbito): sin X, Y ni Z."""
SURVEY_HASH_TAG = b"geoblender:dh_collar.survey_sha256@1\n"
"""El comienzo de lo que se hashea en ``survey_sha256`` (su versión)."""

_EMPTY_EXTRA = "{}"
_NO_EXTRA: Mapping[str, Any] = MappingProxyType({})
_CATALOGS: Mapping[str, str] = MappingProxyType({
    "lithology": "dh_lithology_code",
    "elements": "dh_element",
    "sectors": "dh_sector",
    "groups": "dh_group",
    "zones": "dh_zone",
})
_SOURCES = SurveyColumns.code_values("source")
_MEASURED = _SOURCES.index(StationSource.MEASURED)
_DECLARED = _SOURCES.index(StationSource.DECLARED_VERTICAL)
_GRID = SurveyColumns.code_values("azimuth_ref").index(AzimuthRef.GRID)
_DATES = ("start_date", "end_date")
_PRIMARY: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "dh_survey": ("depth",),
    "dh_lithology": ("from_m", "to_m"),
    "dh_assay": ("from_m", "to_m", "element_id"),
    "dh_zone_interval": ("from_m", "to_m"),
    "dh_structure": ("depth",),
})
"""El orden de las filas de una tabla hija tras su sondeo (plan §5.6.1: por sondeo y
profundidad); si empatan, el resto de sus columnas."""


# --- Lo que entra ----------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class SourceEntry:
    """Lo importado vigente de una entrada (plan §5.6.1): su uid (``gb_input``), lo que declara
    (``declaration``: CRS y datum de sus bocas, convenios de sus estaciones y de sus leyes) y
    sus filas ya interpretadas, en lo declarado y sin transformar, con el sondeo de cada fila
    hija por su nombre (``hole_name``; su ``hole`` no se usa), y sus catálogos. ``label`` es su
    nombre en los mensajes (por defecto, el uid). No se modifica."""

    input_uid: str
    declaration: SourceDeclaration
    collars: CollarColumns = field(default_factory=CollarColumns.empty)
    surveys: SurveyColumns = field(default_factory=SurveyColumns.empty)
    lithology: IntervalColumns = field(default_factory=IntervalColumns.empty)
    assays: AssayColumns = field(default_factory=AssayColumns.empty)
    zones: ZoneColumns = field(default_factory=ZoneColumns.empty)
    structures: StructureColumns = field(default_factory=StructureColumns.empty)
    catalogs: Catalogs = field(default_factory=Catalogs)
    label: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.input_uid, str):
            raise TypeError(f"el uid de una entrada es un texto, no {self.input_uid!r}")
        uuid.UUID(self.input_uid)  # ValueError si no es un UUID
        if not isinstance(self.declaration, SourceDeclaration):
            raise TypeError(f"lo que declara una entrada es un SourceDeclaration, no "
                            f"{self.declaration!r}")
        for name, columns in TABLES.items():
            if type(getattr(self, name)) is not columns:
                raise TypeError(f"«{name}» de una entrada es un {columns.__name__}, no "
                                f"{getattr(self, name)!r}")
        if not isinstance(self.catalogs, Catalogs):
            raise TypeError(f"los catálogos de una entrada son un Catalogs, no {self.catalogs!r}")
        if self.label is not None and (not isinstance(self.label, str) or not self.label.strip()):
            raise ValueError(f"el nombre de una entrada es un texto no vacío, no {self.label!r}")

    @property
    def name(self) -> str:
        """Su nombre en los mensajes: ``label`` o, sin él, su uid."""
        return self.label or self.input_uid

    @classmethod
    def from_set(cls, input_uid: str, declaration: SourceDeclaration, dset: DrillholeSet, *,
                 label: str | None = None) -> SourceEntry:
        """La entrada ``input_uid`` con las tablas y los catálogos de ``dset`` (lo de una
        lectura en lo declarado; los enlaces de ``dset`` no se usan)."""
        if not isinstance(dset, DrillholeSet):
            raise TypeError(f"las filas de una entrada son un DrillholeSet, no {dset!r}")
        return cls(input_uid, declaration, catalogs=dset.catalogs, label=label,
                   **{name: getattr(dset, name) for name in TABLES})


# --- Lo que sale -----------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceTransform:
    """La transformación de las bocas de una entrada al CRS y al datum del proyecto
    (RF-005-08): la entrada, lo declarado y lo del proyecto («EPSG:23030 + EPSG:5782»), la
    transformación de la 006 (``info``: descripción, precisión en m y rejillas), su informe
    (``summary``, el de ``gis.crs.transform_summary``) y las bocas que lleva."""

    input_uid: str
    source: str
    target: str
    info: TransformInfo
    summary: str
    holes: int


@dataclass(frozen=True)
class BuildNote:
    """Algo de lo importado que no pasa a la base (véase el módulo): su código
    (``NOTE_*``), la tabla de la base, el sondeo (``None``: filas sin sondeo), el código de
    catálogo que no está (``value``), las filas y si pasan sin esa referencia (``kept``: el
    sector o el grupo de una boca, la zona de una estructura)."""

    code: str
    table: str
    hole: str | None
    value: str | None
    rows: int
    kept: bool = False

    @property
    def message(self) -> str:
        """El texto para el informe, en español."""
        where = f"«{self.table}»"
        if self.code == NOTE_DUPLICATE:
            return (f"El sondeo «{self.hole}» está repetido en las bocas de su entrada "
                    f"(DH-E01): no pasa a la base ({self.rows} filas de {where}).")
        if self.code == NOTE_WITHOUT_COLLAR:
            return (f"El sondeo «{self.hole}» no tiene boca en la base (DH-E04): sus "
                    f"{self.rows} filas de {where} no pasan.")
        if self.code == NOTE_UNKNOWN_CODE:
            hole = "" if self.hole is None else f" del sondeo «{self.hole}»"
            rest = "pasan sin él" if self.kept else "no pasan"
            return (f"El código «{self.value}» no está en los catálogos de la base (DH-E11): "
                    f"{self.rows} filas de {where}{hole} {rest}.")
        return (f"La transformación de su entrada no da las coordenadas de la boca "
                f"«{self.hole}» (fuera de su ámbito): queda sin X, Y ni Z.")


@dataclass(frozen=True, eq=False)
class BaseTables:
    """La base de los sondeos (véase el módulo).

    - ``dset``: la base en columnas, en el CRS y el datum del proyecto, con las filas de cada
      tabla en el orden de su ``fid`` (``hole`` = ``hole_id`` − 1) y los catálogos de la base;
    - ``columns``: cada tabla de :data:`~drillholes.schema.BASE_TABLES` → sus columnas (las de
      su ``TableLayout``, sin ``fid`` ni ``geom``, en su orden) con los valores que se
      escriben: números en float64 (NaN = ``NULL``), claves en int64, textos, enumeraciones
      por su texto, fechas «AAAA-MM-DD», sí/no 0 o 1 y ``extra`` en JSON;
    - ``transforms``: las transformaciones de las bocas (RF-005-08); ``notes``, lo que no pasa.
    """

    dset: DrillholeSet
    columns: Mapping[str, Mapping[str, np.ndarray]]
    transforms: tuple[SourceTransform, ...] = ()
    notes: tuple[BuildNote, ...] = ()

    @property
    def survey_hashes(self) -> dict[str, str]:
        """La huella de la desviación (``survey_sha256``) de cada sondeo, por su nombre, en el
        orden de las bocas."""
        collars = self.columns["dh_collar"]
        return dict(zip(collars["name"].tolist(), collars["survey_sha256"].tolist(),
                        strict=True))

    def rows(self, table: str) -> list[tuple[Any, ...]]:
        """Las filas de la tabla ``table`` de la base, en el orden de su ``fid`` y con sus
        valores en el de ``TableLayout.insert_columns`` (las de ``schema.insert_rows`` y
        ``schema.table_digest``): la geometría de una boca (un ``POINT`` con Z en el SRS del
        proyecto, o ``None`` sin X, Y o Z) y sus columnas, con ``None`` por ``NULL``.
        ``ValueError`` si no es una tabla de la base."""
        if table not in BASE_TABLES:
            raise ValueError(f"{table!r} no es una tabla de la base de los sondeos: es una de "
                             f"{', '.join(BASE_TABLES)}")
        layout = LAYOUTS[table]
        found = self.columns[table]
        values = [_sql_values(found[name]) for name in layout.column_names]
        if layout.geometry_type is not None:
            values.insert(0, _points(found["x"], found["y"], found["z"], self.dset.crs.epsg))
        return list(zip(*values, strict=True))


# --- Utilidades vectorizadas -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Keys:
    """Los nombres (o códigos) de unas filas por su clave (``name_key``): ``codes``, la clave
    de cada fila (−1 sin nombre), ``keys``, las claves en orden, y ``spellings``, la primera
    grafía de cada una en ese orden."""

    codes: np.ndarray
    keys: tuple[str, ...]
    spellings: tuple[str, ...]

    def lookup(self, index: Mapping[str, int], missing: int = -1) -> np.ndarray:
        """El valor de ``index`` de la clave de cada fila (``missing`` sin clave o si no
        está)."""
        per_key = np.array([index.get(key, missing) for key in self.keys], dtype=np.int64)
        found = np.full(len(self.codes), missing, dtype=np.int64)
        present = self.codes >= 0
        found[present] = per_key[self.codes[present]]
        return found


def _keys(texts: np.ndarray) -> _Keys:
    """Las claves de ``texts`` (textos o ``None``): ``name_key`` una vez por texto distinto."""
    codes = np.full(len(texts), -1, dtype=np.int64)
    present = texts != None  # noqa: E711 (elemento a elemento)
    if not present.any():
        return _Keys(codes, (), ())
    distinct, inverse = np.unique(texts[present], return_inverse=True)
    found = [name_key(text) for text in distinct.tolist()]
    keys, key_of = np.unique(np.array(found, dtype=object), return_inverse=True)
    spellings: dict[int, str] = {}
    for text, key in zip(distinct.tolist(), key_of.tolist(), strict=True):
        spellings.setdefault(key, text)
    codes[present] = key_of[inverse]
    return _Keys(codes, tuple(keys.tolist()), tuple(spellings[k] for k in range(len(keys))))


def _latest(codes: np.ndarray, entry: np.ndarray, count: int,
            among: np.ndarray | None = None) -> np.ndarray:
    """Las filas (de ``among``) de la entrada más reciente que trae filas de su clave; las
    filas sin clave (−1) cuentan como una clave más."""
    slot = np.where(codes >= 0, codes, count)
    winner = np.full(count + 1, -1, dtype=np.int64)
    if among is None:
        np.maximum.at(winner, slot, entry)
        return entry == winner[slot]
    np.maximum.at(winner, slot[among], entry[among])
    return among & (entry == winner[slot])


def _concat(columns: type, parts: Sequence[Any]) -> Any:
    """Las filas de ``parts`` (columnas de la clase ``columns``) una tras otra."""
    chosen = [columns.empty(), *parts]
    return columns(**{item.name: np.concatenate([getattr(part, item.name) for part in chosen])
                      for item in fields(columns)})


def _stack(entries: Sequence[SourceEntry], name: str) -> tuple[Any, np.ndarray]:
    """La tabla ``name`` de todas las entradas, una tras otra, y la entrada de cada fila."""
    parts = [getattr(entry, name) for entry in entries]
    sizes = [len(part) for part in parts]
    entry = np.repeat(np.arange(len(parts), dtype=np.int64), sizes)
    return _concat(TABLES[name], parts), entry


def _canonical(values: np.ndarray) -> np.ndarray:
    """Una copia en float64 sin −0,0 y con un solo NaN (los mismos bits para el mismo valor)."""
    found = np.asarray(values, dtype=np.float64) + 0.0
    found[np.isnan(found)] = math.nan
    return found


def _ranks(values: np.ndarray) -> np.ndarray:
    """El rango (int64) de cada valor de una columna de objetos: 0 ``None``; los demás, por su
    orden."""
    found = np.zeros(len(values), dtype=np.int64)
    present = values != None  # noqa: E711 (elemento a elemento)
    if present.any():
        chosen = values[present]
        try:
            _, inverse = np.unique(chosen, return_inverse=True)
        except TypeError:  # tipos que no se comparan entre sí: por su tipo y su repr
            texts = np.array([f"{type(v).__name__}:{v!r}" for v in chosen.tolist()],
                             dtype=object)
            _, inverse = np.unique(texts, return_inverse=True)
        found[present] = inverse + 1
    return found


def _sort_key(values: np.ndarray) -> np.ndarray:
    """Una clave numérica de una columna para ordenar y comparar."""
    if values.dtype == np.float64:
        return _canonical(values)
    if values.dtype.kind in "biu":
        return values.astype(np.int64)
    return _ranks(values)


def _bits(key: np.ndarray) -> np.ndarray:
    return key.view(np.int64) if key.dtype == np.float64 else key


def _order(primary: Sequence[np.ndarray], columns: Mapping[str, np.ndarray]) -> np.ndarray:
    """El orden de unas filas por ``primary`` (de más a menos significativa) y, las que
    empatan, por todas sus ``columns``: el mismo contenido da el mismo orden."""
    count = len(primary[0])
    if count < 2:
        return np.arange(count)
    keys = [_sort_key(values) for values in primary]
    order = np.lexsort(keys[::-1])
    same = np.ones(count - 1, dtype=bool)
    for key in keys:
        bits = _bits(key)[order]
        same &= bits[1:] == bits[:-1]
    if not same.any():
        return order
    tied = np.zeros(count, dtype=bool)
    tied[1:] |= same
    tied[:-1] |= same
    group = np.concatenate(([0], np.cumsum(~same)))
    positions = np.flatnonzero(tied)
    rows = order[positions]
    breakers = [_sort_key(values[rows]) for values in columns.values()]
    inner = np.lexsort([*breakers[::-1], group[positions]])
    order[positions] = rows[inner]
    return order


def _json_texts(extra: np.ndarray) -> np.ndarray:
    """El JSON canónico de cada ``extra`` («{}» los vacíos)."""
    found = np.full(len(extra), _EMPTY_EXTRA, dtype=object)
    filled = np.flatnonzero(np.frompyfunc(len, 1, 1)(extra).astype(bool)) if len(extra) else []
    for row in np.asarray(filled).tolist():
        found[row] = canonical_json(extra[row]).decode("utf-8")
    return found


def _set_columns(columns: Any) -> dict[str, np.ndarray]:
    """Las columnas de una tabla del modelo con los valores que se escriben (sin ``hole`` ni
    ``hole_name``)."""
    found: dict[str, np.ndarray] = {}
    for item in fields(columns):
        name = item.name
        if name in ("hole", "hole_name"):
            continue
        values = getattr(columns, name)
        if values.dtype == np.float64:
            found[name] = _canonical(values)
        elif values.dtype == np.bool_:
            found[name] = values.astype(np.int64)
        elif values.dtype == np.int8:
            texts = [str(member) for member in type(columns).code_values(name)]
            found[name] = np.array([*texts, None], dtype=object)[values]
        elif values.dtype.kind in "iu":
            found[name] = values.astype(np.int64)
        elif name == "extra":
            found[name] = _json_texts(values)
        elif name in _DATES:
            found[name] = np.array([None if day is None else day.isoformat()
                                    for day in values.tolist()], dtype=object)
        else:
            found[name] = values
    return found


def _sql_column(column: ColumnDef, values: list[Any]) -> np.ndarray:
    """Una columna de un catálogo (sus registros) con los valores que se escriben."""
    if column.sql_type == "DOUBLE":
        return _canonical(np.array([math.nan if v is None else v for v in values],
                                   dtype=np.float64))
    if column.sql_type in ("INTEGER", "BOOLEAN"):
        if column.not_null:
            return np.array([int(v) for v in values], dtype=np.int64)
        return np.array([None if v is None else int(v) for v in values], dtype=object)
    texts: list[str | None] = []
    for value in values:
        if value is None:
            texts.append(None)
        elif isinstance(value, Mapping):
            texts.append(canonical_json(value).decode("utf-8") if value else _EMPTY_EXTRA)
        elif isinstance(value, dt.date):
            texts.append(value.isoformat())
        else:
            texts.append(str(value))
    return np.array(texts, dtype=object)


def _sql_values(values: np.ndarray) -> list[Any]:
    """Los valores de una columna para SQLite: ``None`` por un NaN."""
    if values.dtype == np.float64:
        found = values.astype(object)
        found[np.isnan(values)] = None
        return found.tolist()
    return values.tolist()


def _points(x: np.ndarray, y: np.ndarray, z: np.ndarray, srs: int) -> list[bytes | None]:
    """La geometría de cada boca: un ``POINT`` con Z, o ``None`` sin X, Y o Z (DH-E02)."""
    xyz = np.column_stack([x, y, z])
    finite = np.isfinite(xyz).all(axis=1)
    return [encode_geometry("POINT", point, srs, True) if ok else None
            for point, ok in zip(xyz, finite.tolist(), strict=True)]


def _ids(keys: _Keys, index: Mapping[str, int]) -> np.ndarray:
    """La posición (desde 1) de la clave de cada fila en un catálogo (0 si no está o no hay)."""
    return keys.lookup(index, 0)


def _optional_ids(ids: np.ndarray) -> np.ndarray:
    """Unas posiciones con ``None`` por las que no hay (0)."""
    found = ids.astype(object)
    found[ids <= 0] = None
    return found


def _apply(transform: Transform, xyz: np.ndarray, *,
           same_vertical: bool) -> tuple[np.ndarray, np.ndarray]:
    """``xyz`` (las bocas de una entrada, absolutas) transformadas y las que la transformación
    no da. Sin X o Y, sin X ni Y (y sin Z si cambia el datum); sin Z, la X y la Y se
    transforman con Z = 0 y la Z sigue ausente."""
    found = np.full(xyz.shape, math.nan)
    planar = np.isfinite(xyz[:, :2]).all(axis=1)
    known = np.isfinite(xyz[:, 2])
    rows = np.flatnonzero(planar)
    if rows.size:
        points = xyz[rows].copy()
        points[~known[rows], 2] = 0.0
        moved = np.array(transform.apply(points), dtype=np.float64)
        moved[~known[rows], 2] = math.nan
        found[rows] = moved
    if same_vertical:
        found[~planar, 2] = xyz[~planar, 2]
    given = np.isfinite(found[:, :2]).all(axis=1) & (np.isfinite(found[:, 2]) | ~known)
    lost = planar & ~given
    found[lost] = math.nan
    return found, lost


def _survey_hashes(collars: CollarColumns, surveys: SurveyColumns) -> np.ndarray:
    """``survey_sha256`` de cada boca (véase el módulo): una por sondeo."""
    count = len(collars)
    head = np.ascontiguousarray(_canonical(np.column_stack(
        [collars.x, collars.y, collars.z, collars.depth])), dtype="<f8")
    stations = _canonical(np.column_stack([
        surveys.depth, surveys.azimuth, surveys.inclination,
        surveys.source.astype(np.float64)]))
    order = np.lexsort((stations[:, 3], stations[:, 2], stations[:, 1], stations[:, 0],
                        surveys.hole))
    body = np.ascontiguousarray(stations[order], dtype="<f8").tobytes()
    starts = np.searchsorted(surveys.hole[order], np.arange(count + 1)).tolist()
    head_bytes = head.tobytes()
    width = 4 * 8
    found = np.empty(count, dtype=object)
    for hole in range(count):
        digest = hashlib.sha256(SURVEY_HASH_TAG)
        digest.update(head_bytes[hole * width:(hole + 1) * width])
        digest.update(body[starts[hole] * width:starts[hole + 1] * width])
        found[hole] = digest.hexdigest()
    return found


def _merge_catalogs(entries: Sequence[SourceEntry]) -> tuple[Catalogs, dict[str, dict]]:
    """Los catálogos de la base (de cada código, el de la entrada más reciente que lo trae),
    por su clave, y la posición (desde 1) de cada clave en cada uno."""
    chosen: dict[str, dict[Any, Any]] = {kind: {} for kind in _CATALOGS}
    for entry in entries:
        for item in entry.catalogs.lithology:
            chosen["lithology"][(name_key(item.log_set), name_key(item.code))] = item
        for kind in ("elements", "sectors", "groups", "zones"):
            for item in getattr(entry.catalogs, kind):
                chosen[kind][name_key(item.code)] = item
    index = {kind: {key: k + 1 for k, key in enumerate(sorted(found))}
             for kind, found in chosen.items()}
    catalogs = Catalogs(**{kind: tuple(found[key] for key in sorted(found))
                           for kind, found in chosen.items()})
    return catalogs, index


def _catalog_columns(catalogs: Catalogs) -> dict[str, dict[str, np.ndarray]]:
    found = {}
    for kind, table in _CATALOGS.items():
        records = getattr(catalogs, kind)
        found[table] = {column.name: _sql_column(column, [getattr(r, column.name)
                                                          for r in records])
                        for column in LAYOUTS[table].columns}
    return found


def _check_entries(sources: object) -> tuple[SourceEntry, ...]:
    if isinstance(sources, str | bytes | Mapping) or not isinstance(sources, Sequence):
        raise TypeError(f"lo importado es una lista de SourceEntry en el orden en que se "
                        f"registraron, no {sources!r}")
    entries = tuple(sources)
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, SourceEntry):
            raise TypeError(f"lo importado de una entrada es un SourceEntry, no {entry!r}")
        key = entry.input_uid.lower()
        if key in seen:
            raise ValueError(f"la entrada «{entry.input_uid}» está dos veces en lo importado")
        seen.add(key)
    return entries


# --- La construcción --------------------------------------------------------------------------


class _Builder:
    """La construcción de una base (véase :func:`build_base`)."""

    def __init__(self, entries: tuple[SourceEntry, ...], service: CrsService | None,
                 crs: CrsRef, vertical: VerticalRef, project_uid: str) -> None:
        self.entries = entries
        self.crs = crs
        self.vertical = vertical
        self.project_uid = project_uid
        self._service = service
        self._gamma: np.ndarray | None = None
        self._source_gamma: np.ndarray | None = None
        self.notes: list[BuildNote] = []
        self.transforms: list[SourceTransform] = []
        self.uids = np.array([entry.input_uid for entry in entries], dtype=object)
        self.vertical_flags = np.array([entry.declaration.all_vertical for entry in entries],
                                       dtype=bool)

    def service(self) -> CrsService:
        """El servicio de CRS: el que se dio o, si no, el de ``adapters.registry``."""
        if self._service is None:
            from ..gis.crs import require_crs_service

            self._service = require_crs_service()
        return self._service

    # Bocas

    def collars(self) -> None:
        stacked, entry = _stack(self.entries, "collars")
        keys = _keys(stacked.name)
        count = len(keys.keys)
        latest = _latest(keys.codes, entry, count)
        per_key = np.bincount(keys.codes[latest], minlength=count)
        repeated = per_key > 1
        for key in np.flatnonzero(repeated).tolist():
            self.notes.append(BuildNote(NOTE_DUPLICATE, "dh_collar", keys.spellings[key], None,
                                        int(per_key[key])))
        self.duplicates = frozenset(keys.keys[k] for k in np.flatnonzero(repeated).tolist())
        chosen = np.flatnonzero(latest & ~repeated[keys.codes])
        chosen = chosen[np.argsort(keys.codes[chosen], kind="stable")]
        self.index = {keys.keys[code]: hole for hole, code in
                      enumerate(keys.codes[chosen].tolist())}
        self.hole_entry = entry[chosen]
        found = stacked.take(chosen)
        self.source_xy = np.column_stack([found.x, found.y])
        epsg = np.array([-1 if e.declaration.crs is None else e.declaration.crs.epsg
                         for e in self.entries], dtype=np.int64)
        self.source_epsg = epsg[self.hole_entry]
        self.base_collars = self._transform(found)

    def _transform(self, collars: CollarColumns) -> CollarColumns:
        if not len(collars):
            return collars
        from ..gis.crs import Declaration, reference_label, transform_summary, transformation_for

        x, y, z = collars.x.copy(), collars.y.copy(), collars.z.copy()
        target = reference_label(self.crs, self.vertical)
        for number in np.unique(self.hole_entry).tolist():
            entry = self.entries[number]
            declared = entry.declaration
            transform = transformation_for(
                Declaration(entry.name, declared.crs, declared.vertical), self.crs,
                self.vertical, resolver=self.service)
            if transform is None:
                continue
            rows = np.flatnonzero(self.hole_entry == number)
            found, lost = _apply(transform, np.column_stack([x[rows], y[rows], z[rows]]),
                                 same_vertical=declared.vertical == self.vertical)
            x[rows], y[rows], z[rows] = found[:, 0], found[:, 1], found[:, 2]
            for row in rows[lost].tolist():
                self.notes.append(BuildNote(NOTE_NOT_TRANSFORMED, "dh_collar",
                                            collars.name[row], None, 1))
            self.transforms.append(SourceTransform(
                entry.input_uid, reference_label(declared.crs, declared.vertical), target,
                transform.info, transform_summary(transform.info), int(rows.size)))
        return collars.take(np.arange(len(collars)), x=x, y=y, z=z)

    def gamma(self) -> np.ndarray:
        """La convergencia de cuadrícula del proyecto en cada boca (una llamada)."""
        if self._gamma is None:
            xy = np.column_stack([self.base_collars.x, self.base_collars.y])
            self._gamma = collar_convergence(xy, self.service(), self.crs)
        return self._gamma

    def source_gamma(self) -> np.ndarray:
        """La convergencia de cuadrícula del CRS declarado de cada boca en otro CRS, en su
        posición declarada (una llamada por CRS); NaN en las demás."""
        if self._source_gamma is None:
            gamma = np.full(len(self.base_collars), math.nan)
            other = self.source_epsg != self.crs.epsg
            for epsg in np.unique(self.source_epsg[other]).tolist():
                rows = np.flatnonzero(self.source_epsg == epsg)
                crs = self.entries[int(self.hole_entry[rows[0]])].declaration.crs
                gamma[rows] = collar_convergence(self.source_xy[rows], self.service(), crs)
            self._source_gamma = gamma
        return self._source_gamma

    # Filas hijas

    def _orphans(self, table: str, keys: _Keys, mask: np.ndarray) -> None:
        """Las notas de las filas ``mask`` de sondeos sin boca en la base."""
        if not mask.any():
            return
        counts = np.bincount(keys.codes[mask], minlength=len(keys.keys))
        for key in np.flatnonzero(counts).tolist():
            code = NOTE_DUPLICATE if keys.keys[key] in self.duplicates else NOTE_WITHOUT_COLLAR
            self.notes.append(BuildNote(code, table, keys.spellings[key], None,
                                        int(counts[key])))

    def _unknown(self, table: str, hole: np.ndarray, keys: _Keys, mask: np.ndarray, *,
                 kept: bool = False) -> None:
        """Las notas de las filas ``mask`` con un código que no está en su catálogo."""
        if not mask.any():
            return
        pairs, counts = np.unique(np.column_stack([hole[mask], keys.codes[mask]]), axis=0,
                                  return_counts=True)
        names = self.base_collars.name
        for (row, key), rows in zip(pairs.tolist(), counts.tolist(), strict=True):
            self.notes.append(BuildNote(NOTE_UNKNOWN_CODE, table,
                                        None if row < 0 else names[row],
                                        keys.spellings[key], int(rows), kept=kept))

    def children(self, name: str) -> tuple[Any, np.ndarray]:
        """Las filas de la tabla ``name`` que pasan (de la entrada más reciente de su sondeo,
        con boca en la base) enlazadas a su boca, y su entrada."""
        stacked, entry = _stack(self.entries, name)
        keys = _keys(stacked.hole_name)
        hole = keys.lookup(self.index)
        latest = _latest(keys.codes, entry, len(keys.keys))
        orphan = latest & (keys.codes >= 0) & (hole < 0)
        self._orphans(SET_TABLES[name], keys, orphan)
        chosen = np.flatnonzero(latest & ~orphan)
        return stacked.take(chosen, hole=hole[chosen]), entry[chosen]

    def surveys(self) -> tuple[SurveyColumns, np.ndarray]:
        """Las estaciones de cada sondeo (véase el módulo), enlazadas, y su entrada."""
        stacked, entry = _stack(self.entries, "surveys")
        keys = _keys(stacked.hole_name)
        count = len(keys.keys)
        hole = keys.lookup(self.index)
        linked = hole >= 0
        measured = _latest(keys.codes, entry, count, stacked.source == _MEASURED)
        has_measured = np.zeros(count, dtype=bool)
        has_measured[keys.codes[measured]] = True
        collar_entry = np.full(len(hole), -1, dtype=np.int64)
        collar_entry[linked] = self.hole_entry[hole[linked]]
        oriented = (stacked.source != _MEASURED) & linked & (entry == collar_entry)
        if count:
            oriented &= ~has_measured[keys.codes]
        self._orphans("dh_survey", keys, measured & ~linked)
        chosen = np.flatnonzero((measured & linked) | oriented)
        found = stacked.take(chosen, hole=hole[chosen])
        found_entry = entry[chosen]
        with_station = np.zeros(len(self.base_collars), dtype=bool)
        with_station[found.hole] = True
        vertical = np.flatnonzero(~with_station & self.vertical_flags[self.hole_entry])
        if vertical.size:
            found = _concat(SurveyColumns, [found, self._vertical(vertical)])
            found_entry = np.concatenate([found_entry, self.hole_entry[vertical]])
        return found, found_entry

    def _vertical(self, holes: np.ndarray) -> SurveyColumns:
        """Una estación vertical declarada (0°, −90°, a 0 m) en cada boca ``holes``."""
        count = len(holes)
        return SurveyColumns(
            hole=holes.astype(np.int64), hole_name=self.base_collars.name[holes],
            depth=np.zeros(count), azimuth=np.zeros(count), inclination=np.full(count, -90.0),
            azimuth_measured=np.full(count, math.nan),
            azimuth_ref=np.full(count, -1, dtype=np.int8),
            declination_deg=np.full(count, math.nan), convergence_deg=np.full(count, math.nan),
            source=np.full(count, _DECLARED, dtype=np.int8),
            method=np.full(count, None, dtype=object),
            external_id=np.full(count, None, dtype=object),
            extra=np.full(count, _NO_EXTRA, dtype=object))

    def convert(self, surveys: SurveyColumns, entry: np.ndarray) -> SurveyColumns:
        """Las estaciones en los convenios internos, cada una con la declaración de su
        entrada (una conversión por entrada)."""
        parts, positions = [], []
        for number in np.unique(entry).tolist():
            rows = np.flatnonzero(entry == number)
            parts.append(self._convert(surveys.take(rows), self.entries[number].declaration))
            positions.append(rows)
        if not parts:
            return surveys
        joined = _concat(SurveyColumns, parts)
        return joined.take(np.argsort(np.concatenate(positions), kind="stable"))

    def _convert(self, part: SurveyColumns, declared: SourceDeclaration) -> SurveyColumns:
        measured = part.source != _DECLARED
        ref = declared.azimuth_ref
        if not measured.any():
            return convert_surveys(part, declared)
        if ref in (AzimuthRef.TRUE, AzimuthRef.MAGNETIC):
            return convert_surveys(part, declared, self.gamma())
        if ref is not AzimuthRef.GRID:  # sin declarar: su ValueError (RF-005-07)
            return convert_surveys(part, declared)
        other = measured & (self.source_epsg[part.hole] != self.crs.epsg)
        if not other.any():
            return convert_surveys(part, declared)
        net = self.gamma() - self.source_gamma()
        geographic = dataclasses.replace(declared, azimuth_ref=AzimuthRef.TRUE,
                                         declination_deg=None)
        moved = convert_surveys(part.take(other), geographic, net)
        moved = moved.take(np.arange(len(moved)),
                           azimuth_ref=np.full(len(moved), _GRID, dtype=np.int8))
        kept = convert_surveys(part.take(~other), declared)
        positions = np.concatenate([np.flatnonzero(other), np.flatnonzero(~other)])
        return _concat(SurveyColumns, [moved, kept]).take(np.argsort(positions, kind="stable"))

    # La base

    def run(self) -> BaseTables:
        catalogs, index = _merge_catalogs(self.entries)
        self.collars()
        surveys, surveys_entry = self.surveys()
        surveys = self.convert(surveys, surveys_entry)

        lithology, lithology_entry = self.children("lithology")
        log_sets, codes = _keys(lithology.log_set), _keys(lithology.code)
        width = max(len(codes.keys), 1)
        pairs, inverse = np.unique(log_sets.codes * width + codes.codes, return_inverse=True)
        per_pair = np.array([index["lithology"].get((log_sets.keys[p // width],
                                                     codes.keys[p % width]), 0)
                             for p in pairs.tolist()], dtype=np.int64)
        lithology, lithology_entry, lithology_id = self._known(
            "dh_lithology", lithology, lithology_entry, per_pair[inverse], codes)

        assays, assays_entry = self.children("assays")
        elements = _keys(assays.element)
        assays, assays_entry, element_id = self._known(
            "dh_assay", assays, assays_entry, _ids(elements, index["elements"]), elements)
        assays = convert_assays(assays, {item.code: item.unit for item in catalogs.elements})

        zones, zones_entry = self.children("zones")
        zone_keys = _keys(zones.zone)
        zones, zones_entry, zone_id = self._known(
            "dh_zone_interval", zones, zones_entry, _ids(zone_keys, index["zones"]), zone_keys)

        structures, structures_entry = self.children("structures")
        structure_zone = self._optional("dh_structure", structures.hole, structures.zone,
                                        index["zones"])

        dset = deduce_depths(DrillholeSet(
            crs=self.crs, vertical=self.vertical, collars=self.base_collars, surveys=surveys,
            lithology=lithology, assays=assays, zones=zones, structures=structures,
            catalogs=catalogs))
        collars = dset.collars
        columns: dict[str, dict[str, np.ndarray]] = {}
        children = {
            "surveys": (surveys_entry, {}),
            "lithology": (lithology_entry, {"lithology_id": lithology_id}),
            "assays": (assays_entry, {"element_id": element_id}),
            "zones": (zones_entry, {"zone_id": zone_id}),
            "structures": (structures_entry, {"zone_id": structure_zone}),
        }
        ordered: dict[str, Any] = {}
        for name, (entry, ids) in children.items():
            table = SET_TABLES[name]
            values = getattr(dset, name)
            hole_id = values.hole + 1
            found = {**_set_columns(values), **ids, "input_uid": self.uids[entry],
                     "hole_id": _optional_ids(hole_id) if name == "assays" else hole_id}
            found = {column: found[column] for column in LAYOUTS[table].column_names}
            order = _order([values.hole, *(found[key] for key in _PRIMARY[table])], found)
            columns[table] = {column: array[order] for column, array in found.items()}
            ordered[name] = values.take(order)

        sector = self._optional("dh_collar", np.arange(len(collars)), collars.sector,
                                index["sectors"])
        group = self._optional("dh_collar", np.arange(len(collars)), collars.group,
                               index["groups"])
        found = {**_set_columns(collars), "sector_id": sector, "group_id": group,
                 "uid": np.array([hole_uid(self.project_uid, name)
                                  for name in collars.name.tolist()], dtype=object),
                 "input_uid": self.uids[self.hole_entry],
                 "survey_sha256": _survey_hashes(collars, ordered["surveys"])}
        columns["dh_collar"] = {column: found[column]
                                for column in LAYOUTS["dh_collar"].column_names}
        columns.update(_catalog_columns(catalogs))
        base = dataclasses.replace(dset, **ordered)
        notes = sorted(self.notes, key=lambda note: (note.code, note.table,
                                                     name_key(note.hole or ""),
                                                     note.value or ""))
        return BaseTables(
            base,
            MappingProxyType({table: MappingProxyType(columns[table]) for table in BASE_TABLES}),
            tuple(self.transforms), tuple(notes))

    def _known(self, table: str, columns: Any, entry: np.ndarray, ids: np.ndarray,
               keys: _Keys) -> tuple[Any, np.ndarray, np.ndarray]:
        """Las filas cuyo código está en su catálogo (las demás, a las notas)."""
        unknown = ids <= 0
        self._unknown(table, columns.hole, keys, unknown)
        keep = np.flatnonzero(~unknown)
        return columns.take(keep), entry[keep], ids[keep]

    def _optional(self, table: str, hole: np.ndarray, texts: np.ndarray,
                  index: Mapping[str, int]) -> np.ndarray:
        """La posición en su catálogo de una referencia opcional (``None`` sin ella o si no
        está; esta, a las notas)."""
        keys = _keys(texts)
        ids = _ids(keys, index)
        self._unknown(table, hole, keys, (keys.codes >= 0) & (ids <= 0), kept=True)
        return _optional_ids(ids)


def build_base(
    sources: Sequence[SourceEntry],
    service: CrsService | None,
    project_crs: CrsRef,
    project_vertical: VerticalRef,
    *,
    project_uid: str,
) -> BaseTables:
    """La base de los sondeos del proyecto ``project_uid`` (en ``project_crs`` y
    ``project_vertical``) desde lo importado vigente ``sources`` (sus entradas, en el orden en
    que se registraron), con el servicio de CRS ``service`` de la 006 (``None``: el de
    ``adapters.registry``, solo si hace falta transformar o la convergencia). Véase el módulo.

    Sin el CRS o el datum declarados en unas bocas, ``GisError`` ``gis.crs_undeclared`` o
    ``gis.vertical_undeclared``; una transformación sin precisión conocida,
    ``gis.transform_unknown_accuracy`` (RF-005-07, RF-006-05); unas estaciones sin la
    referencia del azimut o el convenio de la inclinación declarados, ``ValueError``; nada se
    supone. ``ValueError`` con una entrada repetida o un ``project_uid`` que no es un UUID;
    ``TypeError`` con un argumento de otro tipo. Las entradas no cambian."""
    entries = _check_entries(sources)
    if not isinstance(project_crs, CrsRef):
        raise TypeError(f"el CRS del proyecto es un CrsRef del catálogo, no {project_crs!r}")
    if not isinstance(project_vertical, VerticalRef):
        raise TypeError(f"la referencia vertical del proyecto es un VerticalRef, no "
                        f"{project_vertical!r}")
    if not isinstance(project_uid, str):
        raise TypeError(f"el uid del proyecto es un texto, no {project_uid!r}")
    uuid.UUID(project_uid)  # ValueError si no es un UUID
    return _Builder(entries, service, project_crs, project_vertical, project_uid).run()


def _hashes(value: object, what: str) -> dict[str, str]:
    if isinstance(value, BaseTables):
        return value.survey_hashes
    if not isinstance(value, Mapping):
        raise TypeError(f"{what} son unas BaseTables o {{sondeo: survey_sha256}}, no {value!r}")
    found = dict(value)
    for name, digest in found.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise TypeError(f"{what} son {{sondeo: survey_sha256}} de textos, no "
                            f"{name!r}: {digest!r}")
    return found


def changed_holes(previous: BaseTables | Mapping[str, str],
                  new: BaseTables | Mapping[str, str]) -> tuple[str, ...]:
    """Los sondeos cuya huella de la desviación (``survey_sha256``) cambia de ``previous`` a
    ``new`` (RF-005-22, D22; las de unas ``BaseTables`` o ``{sondeo: survey_sha256}``, la de
    la base anterior): los de huella distinta, los nuevos y los que ya no están, comparados
    sin mayúsculas ni espacios exteriores, con su nombre en ``new`` (o en ``previous`` si ya
    no está) y en el orden de su nombre sin mayúsculas."""
    before = {name_key(name): (name, digest)
              for name, digest in _hashes(previous, "las huellas anteriores").items()}
    after = {name_key(name): (name, digest)
             for name, digest in _hashes(new, "las huellas nuevas").items()}
    changed = []
    for key in sorted(before.keys() | after.keys()):
        old, current = before.get(key), after.get(key)
        if old is None or current is None or old[1] != current[1]:
            changed.append((current or old)[0])
    return tuple(changed)
