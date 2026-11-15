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
  ``dec__<código de la entidad>`` (:func:`declared_code`: ``dec__plt_001``), un código **válido de
  la 012** (``[a-z][a-z0-9_]*``, D-22: lo aceptan ``is_code`` y ``param_key``, que la compilación
  usa para sus resguardos y su «activa») y único en las tres capas del proyecto **por su doble guion
  bajo** (``constraint_code`` junta lo que no son letras ni cifras en **un** «_»: ningún nombre da un
  ``dec__…``; el precedente es ``perimeter__``, ADR-0029); su ``ctype`` es uno de los once tipos; su nombre, motivo y decisor los da la
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
- :func:`unusable_record` y :func:`require_usable` (T20; RF-015-11, RF-008-56): si la tabla viva de la versión
  está **bloqueada** por una edición hecha fuera de Geoblender (o falta o está dañada), la compilación de las
  máscaras no se ejecuta con ella (``core.constraint_declared_blocked``: un error de dominio que nombra las
  entidades, nunca el ``ValueError`` de :func:`read_declared`); la persona acepta la edición con un motivo o
  recalcula la declaración (las entidades la vuelven a poner).
- :func:`content_sha256_of` (T20): el hash de contenido que tendría la tabla con unas filas, **sin escribir en el
  proyecto** (en un GeoPackage en memoria, con el lector y el normalizador del dato): con él se sabe si lo que hay
  en el proyecto —tras aceptar una edición— difiere de lo que declararían las entidades.
- :func:`live_table`, :func:`read_in_version` y :func:`names_in_version` (T18): lo que lee la
  compilación de la 012 y quien necesita sus nombres. La tabla de las declaradas **vivas** de una
  versión se busca en el registro de datos por el nombre :data:`DATASET_NAME` y el uid de la versión
  (no hay ninguna si ninguna entidad declaró nunca: entonces la compilación consume lo mismo que
  siempre).

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
from pathlib import Path
from types import MappingProxyType

import numpy as np

from ..content.builtin import GPKG_LAYER, layer_steps
from ..content.encoder import NORMALIZER, ContentDigest
from ..datasets import DatasetSpec, Store
from ..datasets import registry as dataset_registry
from ..datasets.external import UNUSABLE_STATUSES
from ..datasets.model import DATASET_DECLARATIONS, DatasetRecord, DatasetStatus
from ..georef import CrsRef
from ..gpkg.base import ColumnDef, create_base, create_feature_table, set_column_titles
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
    "content_sha256_of",
    "create_declared_table",
    "declared_code",
    "declared_dataset_spec",
    "declared_entity",
    "declared_table",
    "declared_uid",
    "is_declared_code",
    "live_table",
    "names_in_version",
    "read_declared",
    "read_in_version",
    "require_usable",
    "unusable_record",
    "write_declared",
]

MODULE = "des"
"""El módulo dueño del dato: lo escribe ``des.declare_constraints`` (spec 015)."""
DATASET_NAME = "des_decl"
"""El nombre del dato de las declaradas: uno por versión (``des_decl_<vNN>`` es su ubicación)."""
DECLARED_ROLE = "constraints_declared"
"""El papel de la tabla de las declaradas: la salida de ``des.declare_constraints`` y lo que consume
la compilación de la 012 (el mismo texto que ``design.provenance.DECLARED_ROLE``)."""
DECLARED_PREFIX = "dec__"
"""El principio del código de una declarada (``dec__plt_001``): el resto es el código de la entidad en
minúsculas y con «_» (como el segmento de la clave de sus parámetros, ``plt_001``); el mismo que
``design.model.DECLARED_PREFIX``. Es un código válido de la 012 (``is_code``) que ningún nombre genera
(``constraint_code`` no deja dos «_» seguidos), así que no choca con los de las tres capas."""
DECLARED_PRIORITY = 0
"""La prioridad de toda restricción declarada: una constante estable (plan 015 §5.4 A8). No es una
cifra minera: la prioridad solo ordena informes y leyenda (D-13 de la 012) y ninguna le quita una
prohibición a otra restricción (RF-012-14); con la de una restricción del proyecto por defecto, a
igual prioridad ordena el código."""
GEOMETRY_TYPE = "MULTIPOLYGON"
IDENTIFIER = "Restricciones declaradas por las entidades"
"""El principio del identificador de la capa en ``gpkg_contents`` (lleva el código de la versión)."""

_ENTITY = re.compile(r"[A-Z]{2,5}-[0-9]{3,}")
_DECLARED = re.compile(re.escape(DECLARED_PREFIX) + r"(?P<entity>[a-z]{2,5}_[0-9]{3,})")
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
    """El código de la restricción que declara la entidad ``entity_code``: ``dec__plt_001``
    (RF-012-29): :data:`DECLARED_PREFIX` y el código de la entidad en minúsculas y con «_». Es un
    código válido de la 012 (``is_code``, ``param_key``: la compilación inyecta bajo él el resguardo
    y «activa» de la tabla, P-8) y es único en las tres capas del proyecto por su doble guion bajo.
    ``TypeError`` si no es un texto y ``ValueError`` si no es el código de una entidad
    (``PLT-001``): errores del programa."""
    return DECLARED_PREFIX + _entity(entity_code).lower().replace("-", "_")


def is_declared_code(code: object) -> bool:
    """Si ``code`` es el código de una restricción declarada (``dec__plt_001``). Un código que genera
    ``constraint_code`` desde un nombre (:func:`~.model.constraint_code`) nunca lo es."""
    return isinstance(code, str) and _DECLARED.fullmatch(code) is not None


def declared_entity(code: str) -> str:
    """El código de la entidad que declara la restricción de código ``code`` (``dec__plt_001`` →
    ``PLT-001``; la inversa de :func:`declared_code`). ``TypeError`` si no es un texto y
    ``ValueError`` si no es el código de una declarada: errores del programa."""
    if not isinstance(code, str):
        raise TypeError(f"el código de una restricción es un texto, no {code!r}")
    found = _DECLARED.fullmatch(code)
    if found is None:
        raise ValueError(f"el código {code!r} no es el de una restricción declarada "
                         f"({DECLARED_PREFIX}plt_001)")
    return found["entity"].upper().replace("_", "-")


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

    ``code`` es :func:`declared_code` de ``entity_code`` (``dec__plt_001``); ``ctype``, uno de los once tipos (de
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


def content_sha256_of(rows: Iterable[DeclaredConstraint], table: str, crs: CrsRef, *,
                      normalizer: str = NORMALIZER) -> str:
    """El hash de contenido que tendría la tabla ``table`` de las declaradas con ``rows`` (T20; RF-015-11),
    **sin escribir en el proyecto**: la escribe con :func:`write_declared` en un GeoPackage en memoria con el CRS
    ``crs`` (el del proyecto) y la lee con el lector de las capas (``core.gpkg_layer@1``) y el ``normalizer`` del
    dato, como lo hace el registro de datos. Las mismas filas dan el mismo hash que dejó la declaración al
    escribirlas. Los errores de :func:`write_declared`."""
    found = tuple(rows)
    conn = sqlite3.connect(":memory:")
    try:
        create_base(conn, crs)
        write_declared(conn, table, found, srs_id=crs.epsg)  # type: ignore[arg-type]
        request = GPKG_LAYER.request("vector", DATASET_DECLARATIONS, {"main": Path(":memory:")},
                                     {"layer": table, "selector": None}, normalizer=normalizer)
        for _progress in layer_steps(conn, request):
            pass
        return request.hasher.digest().content_sha256
    finally:
        conn.close()


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


# --- Las de una versión (T18) -------------------------------------------------------------------


def live_table(conn: sqlite3.Connection, version_uid: str | None) -> str | None:
    """La tabla de las declaradas **vivas** de la versión de uid ``version_uid`` (``des_decl_v01``: la
    ubicación del dato :data:`DATASET_NAME` en el registro de datos de esa versión) o ``None`` si
    ninguna operación la escribió o ya no está viva. Sin versión (``None`` o ``""``: el proyecto)
    tampoco hay ninguna: son de una versión (RF-012-29). Solo lee."""
    if not version_uid:
        return None
    record = dataset_registry.get(conn, DATASET_NAME, version_uid=version_uid)
    return None if record is None else str(record.locator)


def unusable_record(conn: sqlite3.Connection, version_uid: str | None) -> DatasetRecord | None:
    """El dato de las declaradas **vivo** de la versión ``version_uid`` si **no se puede usar**: lo editó una
    persona fuera de Geoblender y el módulo lo declara no editable a mano (``blocked``: RF-015-11, RF-008-56), o
    falta o está dañado (RF-008-57); ``None`` sin versión, sin tabla viva o con una que se puede usar. Solo
    lee."""
    if not version_uid:
        return None
    record = dataset_registry.get(conn, DATASET_NAME, version_uid=version_uid)
    return record if record is not None and record.status in UNUSABLE_STATUSES else None


def _entity_names(conn: sqlite3.Connection, table: str) -> str:
    """Los nombres de las entidades de la tabla ``table`` entre «», por ``fid``, sin leer su geometría; el
    nombre de la tabla si no se pueden leer (la tabla falta o ya no tiene la columna: se editó fuera)."""
    try:
        found = [str(name) for (name,) in conn.execute(
            f'SELECT DISTINCT entity_name FROM "{_check_table(table)}" ORDER BY entity_code, fid')]
    except sqlite3.Error:
        found = []
    return ", ".join(f"«{name}»" for name in found if name) or f"«{table}»"


def require_usable(conn: sqlite3.Connection, version_uid: str | None, version_code: str) -> None:
    """``ConstraintError`` si la tabla de las declaradas de la versión ``version_uid`` (``version_code``, para el
    mensaje) no se puede usar (:func:`unusable_record`): ``core.constraint_declared_blocked`` si la editó una
    persona fuera de Geoblender (con las entidades que declaran y la tabla), o
    ``core.constraint_declared_unusable`` si falta o está dañada. Es lo que la compilación de las máscaras
    comprueba **antes de leer** la tabla (RF-015-11: no se compila con ella mientras tanto, y una fila editada no
    llega a ``read_declared``). Solo lee."""
    record = unusable_record(conn, version_uid)
    if record is None:
        return
    table = str(record.locator)
    if record.status is DatasetStatus.BLOCKED:
        raise ConstraintError("core.constraint_declared_blocked", version=version_code, table=table,
                              names=_entity_names(conn, table), field="restricciones declaradas",
                              value=table)
    raise ConstraintError("core.constraint_declared_unusable", version=version_code, table=table,
                          field="restricciones declaradas", value=table)


def read_in_version(conn: sqlite3.Connection, version_uid: str | None, *,
                    uid: str | None = None) -> tuple[DeclaredConstraint, ...]:
    """Las restricciones declaradas vivas de la versión de uid ``version_uid`` (:func:`live_table`), por
    ``fid``; ninguna sin versión, sin tabla viva o con la tabla sin filas. Con ``uid``, solo la de ese
    ``uid`` (la barra N de una restricción). Es lo que **suma** la compilación de la 012 (RF-012-16) a
    las restricciones del proyecto: las declaradas no están en sus tres capas. Solo lee."""
    table = live_table(conn, version_uid)
    if table is None:
        return ()
    found = read_declared(conn, table)
    return found if uid is None else tuple(item for item in found if item.uid == uid)


def names_in_version(conn: sqlite3.Connection, version_uid: str | None
                     ) -> dict[str, tuple[str, ConstraintType]]:
    """Código → (nombre, tipo) de las declaradas vivas de la versión ``version_uid``, **sin leer su
    geometría** (como ``core.constraints.store.constraint_names``); ninguna sin versión o sin tabla
    viva. El nombre es el de su entidad. Solo lee."""
    table = live_table(conn, version_uid)
    if table is None or not _exists(conn, _check_table(table)):
        return {}
    return {str(code): (str(name), ConstraintType(ctype)) for code, name, ctype in conn.execute(
        f'SELECT code, name, ctype FROM "{table}" ORDER BY fid')}
