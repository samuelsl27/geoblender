# SPDX-License-Identifier: GPL-3.0-or-later
"""La restricción declarada por una entidad de diseño (spec 015, T16; HU-015-1; RF-012-29,
RF-012-02, RF-015-10; plan 015 §5.1, §5.2.3, §5.4 A8 y P-8; ADR-0030 §3; D-23).

Una entidad de diseño (spec 015) declara lo que prohíbe a los demás operadores —una plataforma
protegida, «sin relleno»—, y esa prohibición entra en las máscaras de la 012 como una restricción
más (ADR-0028). A diferencia de las del proyecto (:mod:`.store`: tres capas que el usuario edita en
QGIS), la **restricción declarada** es **de la versión** de su entidad, la ponen, la cambian y la
quitan las entidades (nunca el usuario desde una capa) y es un dato que su módulo declara **no
editable a mano** (RF-008-56): si se toca en QGIS, se bloquea y no se compila con ella hasta que se
acepte la edición con un motivo o la entidad la vuelva a poner (T20).

- :class:`DeclaredConstraint`: una fila de la tabla de la versión. Su ``code`` es
  ``DEC-<código de la entidad>`` (:func:`declared_code`: ``DEC-PLT-001``), único en las tres capas
  del proyecto **por su prefijo** (un código del proyecto es ``[a-z][a-z0-9_]*``, D-22: nunca lleva
  mayúsculas ni guion); su ``ctype`` es uno de los once tipos; su nombre, motivo y decisor los da la
  entidad; su ``decided_on`` es la fecha **de la decisión**, no la de ahora; su ``uid`` es
  **determinista** (:func:`declared_uid`: del código de la entidad y de la versión, para que repetir
  la declaración no cambie el hash de la tabla); su geometría es el contorno alineado a la rejilla de
  las celdas de la entidad (``design.entities.declared_zone``: absoluto, float64, bit a bit; la regla
  de la celda de RF-012-12 no le añade ninguna con resguardo 0, D-23), y su resguardo hacia fuera
  (``buffer_out_m``, sin valor por defecto: D-19) y si está activa (``active``) son **columnas de la
  tabla**, no parámetros del almacén (P-8: la compilación los inyecta bajo las mismas claves). Su
  ``priority`` es la constante :data:`DECLARED_PRIORITY`: solo ordena informes y leyenda (D-13 de la
  012), y ninguna prioridad quita una prohibición (RF-012-14).
  :meth:`DeclaredConstraint.as_constraint` la da como la :class:`~.model.Constraint` de la 012, con la
  entidad como origen (``entity_code``, ``entity_name``).
- :func:`create_declared_table`, :func:`write_declared` y :func:`read_declared`: la tabla
  ``des_decl_<vNN>`` (:func:`declared_table`), una capa ``MULTIPOLYGON`` (2D, CRS del proyecto) con
  los títulos en español de sus columnas. ``write_declared`` **reescribe la tabla entera** desde las
  filas (la entidad es su única dueña: las filas por código, ``fid`` 1…n, sin dejar el contador del
  autoincremento), de modo que las mismas filas dan siempre los mismos bytes y el mismo hash de
  contenido.
- :func:`declared_dataset_spec`: su dato (``des_decl``, un ``vector`` de ``des`` leído con
  ``core.gpkg_layer@1``, papel :data:`DECLARED_ROLE`) con ``qgis_editable=False``.

Todas reciben la conexión de una transacción de escritura (o una de lectura para leer) y no la
confirman. Python puro (``core``): no importa ``design``.
"""

from __future__ import annotations

import math
import re
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType

import numpy as np

from ..content.builtin import GPKG_LAYER
from ..content.encoder import ContentDigest
from ..datasets import DatasetSpec, Store
from ..gpkg.base import ColumnDef, create_feature_table, set_column_titles
from ..gpkg.wkb import decode_geometry, encode_geometry
from ..versions.model import version_locator
from .messages import ConstraintError
from .model import Constraint, ConstraintType, GeometryKind, _parts
from .store import taken_codes

__all__ = [
    "COLUMN_NAMES",
    "COLUMN_TITLES",
    "DATASET_NAME",
    "DECLARED_PREFIX",
    "DECLARED_PRIORITY",
    "DECLARED_ROLE",
    "DeclaredConstraint",
    "create_declared_table",
    "declared_code",
    "declared_dataset_spec",
    "declared_table",
    "declared_uid",
    "is_declared_code",
    "read_declared",
    "write_declared",
]

MODULE = "des"
"""El módulo dueño del dato: lo escribe ``des.declare_constraints`` (spec 015)."""
DATASET_NAME = "des_decl"
"""El nombre del dato de las declaradas: uno por versión (``des_decl_<vNN>`` es su ubicación)."""
DECLARED_ROLE = "constraints_declared"
"""El papel de la tabla de las declaradas: la salida de ``des.declare_constraints`` y lo que consume
la compilación de la 012 (el mismo texto que ``design.provenance.DECLARED_ROLE``)."""
DECLARED_PREFIX = "DEC-"
"""El principio del código de una declarada (``DEC-PLT-001``): el resto es el código de la entidad
(el mismo que ``design.model.DECLARED_PREFIX``)."""
DECLARED_PRIORITY = 0
"""La prioridad de toda restricción declarada: una constante estable (plan 015 §5.4 A8). No es una
cifra minera: la prioridad solo ordena informes y leyenda (D-13 de la 012) y ninguna le quita una
prohibición a otra restricción (RF-012-14); con la de una restricción del proyecto por defecto, a
igual prioridad ordena el código."""
GEOMETRY_TYPE = "MULTIPOLYGON"
IDENTIFIER = "Restricciones declaradas por las entidades"
"""El principio del identificador de la capa en ``gpkg_contents`` (lleva el código de la versión)."""

_ENTITY = re.compile(r"[A-Z]{2,5}-[0-9]{3,}")
_DECLARED = re.compile(re.escape(DECLARED_PREFIX) + r"[A-Z]{2,5}-[0-9]{3,}")
_TABLE = re.compile(r"[a-z][a-z0-9_]{0,62}")
_VERSION_SUFFIX = re.compile(r"v[0-9]+")
_NAMESPACE = uuid.UUID("0c2f6a50-9d3e-5b7a-8e41-6d1f3b9a7c25")
"""El espacio de los ``uid`` de las declaradas: fijo, para que sean siempre los mismos."""

COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("uid", "TEXT", True), ColumnDef("code", "TEXT", True),
    ColumnDef("name", "TEXT", True), ColumnDef("ctype", "TEXT", True),
    ColumnDef("reason", "TEXT", True), ColumnDef("decided_by", "TEXT", True),
    ColumnDef("decided_on", "DATE", True), ColumnDef("entity_code", "TEXT", True),
    ColumnDef("entity_name", "TEXT", True), ColumnDef("buffer_out_m", "DOUBLE", True),
    ColumnDef("active", "BOOLEAN", True),
)
COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in COLUMNS)
"""Las columnas de la tabla además de ``fid`` y ``geom``, en su orden."""
COLUMN_TITLES: Mapping[str, str] = MappingProxyType({
    "uid": "Identificador", "code": "Código", "name": "Nombre", "ctype": "Tipo",
    "reason": "Motivo", "decided_by": "Decisor", "decided_on": "Fecha de la decisión",
    "entity_code": "Código de la entidad", "entity_name": "Entidad",
    "buffer_out_m": "Resguardo hacia fuera (m)", "active": "Activa",
})
"""Los títulos en español de las columnas, que QGIS muestra como alias."""


# --- Códigos y uid ----------------------------------------------------------------------------


def _entity(code: object) -> str:
    """``code`` si es el código de una entidad (``PLT-001``); ``TypeError`` si no es un texto y
    ``ValueError`` si no es uno (errores del programa)."""
    if not isinstance(code, str):
        raise TypeError(f"el código de una entidad es un texto, no {code!r}")
    if _ENTITY.fullmatch(code) is None:
        raise ValueError(f"el código {code!r} no es de una entidad (PLT-001: letras mayúsculas, un "
                         "guion y al menos tres cifras)")
    return code


def declared_code(entity_code: str) -> str:
    """El código de la restricción que declara la entidad ``entity_code``: ``DEC-PLT-001``
    (RF-012-29). Único en las tres capas del proyecto por su prefijo (:data:`DECLARED_PREFIX`).
    ``TypeError`` si no es un texto y ``ValueError`` si no es el código de una entidad
    (``PLT-001``): errores del programa."""
    return DECLARED_PREFIX + _entity(entity_code)


def is_declared_code(code: object) -> bool:
    """Si ``code`` es el código de una restricción declarada (``DEC-PLT-001``). Un código del
    proyecto (:func:`~.model.is_code`) nunca lo es, y al revés."""
    return isinstance(code, str) and _DECLARED.fullmatch(code) is not None


def declared_uid(version_uid: str, entity_code: str) -> str:
    """El ``uid`` de la restricción que declara la entidad ``entity_code`` en la versión de ``uid``
    ``version_uid``: 32 cifras hexadecimales **derivadas de las dos** (determinista: la misma
    entidad en la misma versión tiene siempre el mismo, así que repetir la declaración no cambia
    el hash de la tabla; en otra versión, otro). ``ValueError`` si ``version_uid`` no es un texto
    con algo o ``entity_code`` no es el código de una entidad."""
    if not isinstance(version_uid, str) or not version_uid.strip():
        raise ValueError(f"el uid de una versión es un texto con algo escrito, no {version_uid!r}")
    return uuid.uuid5(_NAMESPACE, f"{version_uid}\n{_entity(entity_code)}").hex


# --- La fila ------------------------------------------------------------------------------------


def _text(value: object, what: str) -> str:
    """``value`` sin los espacios de los extremos; ``TypeError`` si no es un texto y ``ValueError``
    si queda vacío."""
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    found = value.strip()
    if not found:
        raise ValueError(f"{what} es un texto con algo escrito")
    return found


@dataclass(frozen=True, slots=True, eq=False)
class DeclaredConstraint:
    """Una restricción declarada por una entidad (RF-012-29; una fila de ``des_decl_<vNN>``).

    ``code`` es :func:`declared_code` de ``entity_code``; ``ctype``, uno de los once tipos (de
    ``forbids_*`` depende lo que prohíbe en su zona); ``decided_by`` y ``decided_on``, quien creó
    o cambió la entidad y cuándo se **decidió** (no ``now``); ``parts``, el contorno de las celdas
    de la entidad: por cada parte, sus anillos cerrados (exterior y huecos) en coordenadas
    **absolutas** float64 ``(k, 2)`` de solo lectura; ``buffer_out_m`` (m, finito, ≥ 0) y
    ``active``, columnas de la tabla que ponen la entidad (sin valor por defecto: D-19). ``layer``
    y ``fid``: la tabla y la fila, de una leída. Los errores son del programa (``TypeError`` o
    ``ValueError``): la entidad se comprueba antes (``check_entity_param``)."""

    uid: str
    code: str
    ctype: ConstraintType
    name: str
    reason: str
    decided_by: str
    decided_on: date
    entity_code: str
    entity_name: str
    parts: tuple[tuple[np.ndarray, ...], ...]
    buffer_out_m: float
    active: bool
    layer: str = ""
    fid: int = 0

    def __post_init__(self) -> None:
        entity = _entity(self.entity_code)
        if self.code != declared_code(entity):
            raise ValueError(f"el código de la restricción que declara {entity} es "
                             f"{declared_code(entity)}, no {self.code!r}")
        object.__setattr__(self, "ctype", ConstraintType(self.ctype))
        for field, what in (("name", "el nombre"), ("reason", "el motivo"),
                            ("decided_by", "el decisor"), ("entity_name", "el nombre de la entidad")):
            object.__setattr__(self, field, _text(getattr(self, field), what))
        object.__setattr__(self, "uid", _text(self.uid, "el uid"))
        if not isinstance(self.decided_on, date) or isinstance(self.decided_on, datetime):
            raise TypeError(f"la fecha de la decisión es una fecha, no {self.decided_on!r}")
        outward = self.buffer_out_m
        if isinstance(outward, bool) or not isinstance(outward, int | float | np.floating):
            raise TypeError(f"el resguardo es un número, no {outward!r}")
        if not math.isfinite(outward) or outward < 0.0:
            raise ValueError(f"el resguardo hacia fuera es un número finito ≥ 0, no {outward!r}")
        object.__setattr__(self, "buffer_out_m", float(outward))
        if not isinstance(self.active, bool):
            raise TypeError(f"«activa» es verdadero o falso, no {self.active!r}")
        parts = _parts(self.parts)
        if not parts or any(len(part) == 0 for part in parts):
            raise ValueError("una restricción declarada tiene geometría: al menos una parte con su "
                             "anillo exterior")
        object.__setattr__(self, "parts", parts)
        object.__setattr__(self, "layer", str(self.layer))
        object.__setattr__(self, "fid", int(self.fid))

    @property
    def priority(self) -> int:
        """La prioridad: la constante :data:`DECLARED_PRIORITY`."""
        return DECLARED_PRIORITY

    def as_constraint(self) -> Constraint:
        """La restricción de la 012 de esta declarada: un polígono con su capa de versión (o
        :data:`DATASET_NAME` si no se leyó de una), su ``fid``, la prioridad constante y la entidad
        como origen; sin decisión, intención ni entrada de origen. Lo que la compilación suma como
        cualquier otra (RF-012-14)."""
        return Constraint(
            uid=self.uid, code=self.code, name=self.name, ctype=self.ctype,
            kind=GeometryKind.POLYGON, parts=self.parts, priority=DECLARED_PRIORITY,
            reason=self.reason, decided_by=self.decided_by, decided_on=self.decided_on,
            decision_uid=None, intention_uid=None, source_input=None, source_fid=None,
            layer=self.layer or DATASET_NAME, fid=self.fid, entity_code=self.entity_code,
            entity_name=self.entity_name)


# --- La tabla de la versión ---------------------------------------------------------------------


def declared_table(version_code: str) -> str:
    """La tabla de las declaradas de la versión ``version_code`` («V01»): ``des_decl_v01``
    (``core.versions.model.version_locator``). ``ValueError`` con un código que no es el de una
    versión."""
    return version_locator(DATASET_NAME, version_code)


def declared_dataset_spec(version_code: str, *, crs_epsg: int | None = None,
                          content: ContentDigest | None = None) -> DatasetSpec:
    """El dato de las declaradas de la versión ``version_code`` (RF-008-17, RF-008-56): ``des_decl``
    de ``des``, un ``vector`` del GeoPackage del proyecto en :func:`declared_table`, leído con
    ``core.gpkg_layer@1`` y con el papel :data:`DECLARED_ROLE`, **no editable en QGIS** (RF-012-29:
    si se edita fuera, se bloquea). ``crs_epsg`` es el del proyecto; ``content``, el hash que
    calculó quien escribe, si ya lo tiene."""
    return DatasetSpec(DATASET_NAME, MODULE, "vector", Store.GPKG, declared_table(version_code),
                       reader=GPKG_LAYER.id, role=DECLARED_ROLE, content=content,
                       crs_epsg=crs_epsg, qgis_editable=False)


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (table,)).fetchone() is not None


def _check_table(table: object) -> str:
    if not isinstance(table, str) or _TABLE.fullmatch(table) is None:
        raise ValueError(f"{table!r} no es el nombre de una tabla del GeoPackage (un "
                         "identificador en minúsculas: letras, cifras y «_», empezando por una "
                         "letra)")
    return table


def create_declared_table(conn: sqlite3.Connection, table: str, srs_id: int, *,
                          identifier: str | None = None) -> bool:
    """Crea en la transacción de ``conn`` la capa de polígonos ``table`` de las declaradas
    (:data:`COLUMNS`, ``MULTIPOLYGON`` 2D con el CRS ``srs_id``, el del proyecto) con los títulos en
    español de :data:`COLUMN_TITLES`, y la registra en ``gpkg_contents`` y
    ``gpkg_geometry_columns``; ``True`` si la creó y ``False`` si ya estaba (no hace nada).
    ``identifier``: el de ``gpkg_contents`` (por defecto, :data:`IDENTIFIER` y la versión de su
    nombre). ``ValueError`` si ``table`` no es un nombre de tabla; ``ValidationError`` de
    ``core.gpkg`` si ``srs_id`` no está en ``gpkg_spatial_ref_sys``."""
    _check_table(table)
    if _exists(conn, table):
        return False
    suffix = table.rpartition("_")[2]
    label = f"{IDENTIFIER} {suffix.upper()}" if _VERSION_SUFFIX.fullmatch(suffix) else (
        f"{IDENTIFIER} ({table})")
    create_feature_table(conn, table, GEOMETRY_TYPE, srs_id, False, COLUMNS,
                         label if identifier is None else identifier,
                         f"{IDENTIFIER}, de Geoblender: una por versión, no editable a mano")
    set_column_titles(conn, table, COLUMN_TITLES)
    return True


def _srs_of(conn: sqlite3.Connection, table: str) -> int:
    found = conn.execute("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name = ?",
                         (table,)).fetchone()
    if found is None:
        raise ValueError(f"«{table}» no es una capa registrada en gpkg_geometry_columns")
    return int(found[0])


def _insert(table: str) -> str:
    columns = ", ".join(("geom", *COLUMN_NAMES))
    marks = ", ".join("?" for _ in range(len(COLUMN_NAMES) + 1))
    return f'INSERT INTO "{table}" ({columns}) VALUES ({marks})'


def write_declared(conn: sqlite3.Connection, table: str, rows: Iterable[DeclaredConstraint], *,
                   srs_id: int | None = None) -> tuple[int, ...]:
    """Reescribe la tabla ``table`` de las declaradas con ``rows`` y devuelve sus ``fid`` (RF-012-29,
    RF-015-10): la entidad es la única dueña de la tabla, así que se **sustituye entera** —lo que ya
    no se declara desaparece—, por código y con los ``fid`` desde 1 (también el contador del
    autoincremento), de modo que las mismas filas dan siempre los mismos bytes y el mismo hash de
    contenido, sea cual sea el orden de ``rows``. Con ``rows`` vacío, la tabla queda vacía. Si la
    tabla no existe, la crea con el CRS ``srs_id`` (:func:`create_declared_table`); si existe,
    ``srs_id`` (si se da) es el suyo. Con la geometría **absoluta en float64** (``core.gpkg.wkb``).

    ``ConstraintError`` ``core.constraint_code_taken`` si el código de una fila lo usa una
    restricción de las tres capas del proyecto; ``ValueError`` (errores del programa) si dos filas
    repiten el código o el ``uid``, ``table`` no es una capa registrada, o falta el SRS de una
    tabla que no existe o no es el de la que existe; ``TypeError`` si una fila no es una
    :class:`DeclaredConstraint`. No escribe nada si rechaza alguna; no confirma la transacción."""
    found = tuple(rows)
    _check_table(table)
    for item in found:
        if not isinstance(item, DeclaredConstraint):
            raise TypeError(f"una fila de las declaradas es una DeclaredConstraint, no {item!r}")
    for what in ("code", "uid"):
        values = [getattr(item, what) for item in found]
        if len(set(values)) != len(values):
            raise ValueError(f"dos restricciones declaradas repiten el {what}: "
                             f"{sorted(v for v in set(values) if values.count(v) > 1)}")
    if _exists(conn, table):
        srs = _srs_of(conn, table)
        if srs_id is not None and srs_id != srs:
            raise ValueError(f"«{table}» está en el SRS {srs}, no en el {srs_id}")
    elif srs_id is None:
        raise ValueError(f"«{table}» no existe: crearla pide el SRS del proyecto")
    else:
        srs = srs_id
    project = taken_codes(conn)
    for item in found:
        if item.code in project:
            raise ConstraintError("core.constraint_code_taken", name=item.name, value=item.code)
    create_declared_table(conn, table, srs)
    conn.execute(f'DELETE FROM "{table}"')
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    fids: list[int] = []
    for item in sorted(found, key=lambda row: row.code):
        blob = encode_geometry(GEOMETRY_TYPE, [list(part) for part in item.parts], srs, False)
        cursor = conn.execute(_insert(table), (
            blob, item.uid, item.code, item.name, item.ctype.value, item.reason, item.decided_by,
            item.decided_on.isoformat(), item.entity_code, item.entity_name, item.buffer_out_m,
            1 if item.active else 0))
        fids.append(int(cursor.lastrowid or 0))
    return tuple(fids)


def _polygons(blob: object) -> tuple[tuple[np.ndarray, ...], ...]:
    """Las partes absolutas (anillos ``(k, 2)``) de un blob ``MULTIPOLYGON`` o ``POLYGON``."""
    geometry = decode_geometry(bytes(blob), external=True)  # type: ignore[arg-type]
    name, coords = geometry.geometry_type, geometry.coords
    if name == "POLYGON":
        coords = [coords]
    elif name != "MULTIPOLYGON":
        raise ValueError(f"la geometría de una declarada es un polígono, no {name}")
    return tuple(tuple(np.asarray(ring, dtype=np.float64).reshape(-1, np.shape(ring)[-1])[:, :2]
                       for ring in polygon) for polygon in coords)


def read_declared(conn: sqlite3.Connection, table: str) -> tuple[DeclaredConstraint, ...]:
    """Las restricciones declaradas de la tabla ``table``, por ``fid``; ninguna si la tabla no
    existe. Con su capa (``table``) y su ``fid``. ``ValueError`` si una fila no es una declarada
    (una fila editada fuera: la tabla no es editable a mano, RF-008-56)."""
    _check_table(table)
    if not _exists(conn, table):
        return ()
    columns = ", ".join(COLUMN_NAMES)
    found = []
    for row in conn.execute(f'SELECT fid, geom, {columns} FROM "{table}" ORDER BY fid'):
        fid, blob, uid, code, name, ctype, reason, decided_by, decided_on, entity_code, \
            entity_name, outward, active = row
        if blob is None:
            raise ValueError(f"la fila {fid} de «{table}» no tiene geometría")
        found.append(DeclaredConstraint(
            uid=uid, code=code, ctype=ConstraintType(ctype), name=name, reason=reason,
            decided_by=decided_by, decided_on=date.fromisoformat(str(decided_on)[:10]),
            entity_code=entity_code, entity_name=entity_name, parts=_polygons(blob),
            buffer_out_m=float(outward), active=bool(active), layer=table, fid=int(fid)))
    return tuple(found)
