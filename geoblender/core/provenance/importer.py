# SPDX-License-Identifier: GPL-3.0-or-later
"""«Registrar como entrada» una capa de un GeoPackage: la operación ``core.import_layer`` y su
importador (spec 008; RF-008-07, RF-008-11, RF-008-52, RF-008-54, RF-008-62; D14 del plan 008;
ADR-0025 §2; plan 008 §5.1, §5.3.2, §5.4.8 y §5.4.9).

- :func:`import_layer` registra como **entrada** una capa de entidades o una tabla de un
  GeoPackage externo (ancla junto al original o con su ruta en los datos de usuario,
  RF-002-19) o del propio proyecto (una creada desde QGIS: ancla ``project_table``,
  RF-008-62), con su operación ``core.import_layer``, y deja **lo importado** en una copia
  propia, ``core_imported_<slug>`` (D14): una capa del proyecto no puede ser a la vez fuente e
  importado (RF-008-14, RF-008-52). La copia tiene las mismas columnas, tipos, ``fid``,
  geometrías y CRS que la capa, así que su hash de datos es el de la entrada (se comprueba), y
  queda protegida (``core.datasets.protect_immutable``, al registrarla).
- :func:`reimport_input` («Actualizar», RF-008-11) vuelve a importar una entrada activa con el
  importador de su lector (``ImporterDef`` registrado) y sus ajustes registrados, como una
  entrada nueva que la sustituye; el de ``core.gpkg_layer`` es :func:`reimport_layer`
  (:data:`CORE_IMPORTERS`, que registra ``bl/``). Si la capa registrada ya no está en la
  fuente, el importador pide los ajustes (``SettingsNeeded``, con las capas que tiene).

**Ajustes y CRS.** Los ajustes de la entrada son solo la capa (``{"layer": …}``; ninguno es
contenido). El CRS horizontal declarado es, si no se indica, el de EPSG que declara la capa en
su GeoPackage (una tabla: «no aplica»); el vertical, «no aplica» en una capa sin cotas o en
una tabla. Una capa sin CRS de EPSG o con cotas necesita que se declare: nunca se supone
(``core.input_crs_missing``; constitución, principio 6). Un CRS declarado distinto del de la
capa (un límite en ED50 etiquetado en ETRS89) va a las declaraciones de la entrada; la copia
conserva el de la capa.

**Reutilizar y sustituir** (RF-008-54): la misma capa con el mismo contenido y los mismos
ajustes que una entrada activa no se duplica: la importación queda «cancelada» con el aviso de
la spec §8 (``core.inputs.reuse_input``); con otros ajustes, se rechaza
(``core.input_substitution_required``) hasta que se diga a qué entrada sustituye y por qué
(``previous_uid`` y ``reason``), como al actualizarla. Todo lo que se puede comprobar antes de
empezar se comprueba antes (la operación no llega a registrarse): la capa, su tipo, los CRS,
la clasificación y la entrada sustituida; lo demás, en una sola transacción con la entrada, la
copia y la operación completada.

La fuente solo se lee (RF-008-14): un GeoPackage externo en WAL o con un diario pendiente, sobre
una copia privada temporal (``core.gpkg.GpkgConnection.open_read``); una capa del proyecto,
con la conexión del proyecto, sin tocar sus filas, su SQL, sus disparadores ni su fila de
``gpkg_contents``. Se ejecuta en el hilo de Blender (una capa grande, a un trabajo de la 004,
como cualquier importador). Python puro (ADR-0004); lo reexporta ``core.provenance`` al usarlo.
"""

from __future__ import annotations

import dataclasses
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..content.builtin import GPKG_LAYER, LAYER_KINDS, PRIVATE_PREFIX, layer_steps
from ..content.encoder import ContentDigest, content_sha256
from ..datasets.model import DATASET_DECLARATIONS, LIVE_STATUSES, DatasetRecord, DatasetSpec
from ..datasets.orphans import unregistered_tables
from ..datasets.tracking import RESERVED_PREFIXES
from ..errors import ValidationError
from ..gpkg.connection import GpkgConnection
from ..hashing import sha256_file
from ..inputs import registry as input_registry
from ..inputs.model import (
    FileAnchor,
    FileRole,
    InputRecord,
    InputSpec,
    InputStatus,
    SourceFile,
    SourcePrint,
    check_name,
    input_declarations,
)
from ..timeutil import parse_utc
from .contract import IMPORT_LAYER, ImporterDef, ReimportRequest, SettingsNeeded, importer_def
from .messages import ProvenanceError, render
from .operations import _require_writable, operation

IMPORTED_PREFIX = "core_imported_"
"""El prefijo de las tablas de lo importado por ``core.import_layer`` (D14)."""
IMPORTED_ROLE = "imported"
"""El papel de lo importado en su operación (``gb_operation_io.role``)."""
LAYER_SETTING = "layer"
"""El único ajuste de la importación de una capa: su nombre en ``gpkg_contents``."""
MAX_SLUG_CHARS = 40
"""Largo máximo del nombre de la entrada en el de su tabla de lo importado."""
EMPTY_SLUG = "capa"
"""El nombre de la tabla de lo importado si el de la entrada no tiene letras ni cifras."""
ROW_BATCH = 5_000
"""Las filas que se copian de una vez desde un GeoPackage externo."""
NOT_APPLICABLE: Mapping[str, Any] = {"not_applicable": True}
"""El CRS declarado «no aplica» (``core.inputs``)."""

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_GEOMETRY_TYPE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_LIVE = ", ".join(f"'{status}'" for status in LIVE_STATUSES)

__all__ = [
    "CORE_IMPORTERS",
    "IMPORTED_PREFIX",
    "IMPORTED_ROLE",
    "LAYER_SETTING",
    "LayerImport",
    "import_layer",
    "imported_name",
    "reimport_input",
    "reimport_layer",
]


def imported_name(name: str) -> str:
    """El nombre de lo importado de la entrada ``name``: ``core_imported_<slug>``, con el
    nombre en minúsculas, sin tildes y con «_» en lugar de lo que no es una letra o una cifra
    (:data:`MAX_SLUG_CHARS` como mucho; «capa» si no queda nada)."""
    if not isinstance(name, str):
        raise TypeError(f"el nombre de una entrada es un texto, no {name!r}")
    plain = "".join(char for char in unicodedata.normalize("NFKD", name)
                    if not unicodedata.combining(char)).lower()
    slug = _NON_SLUG.sub("_", plain).strip("_")[:MAX_SLUG_CHARS].rstrip("_")
    return IMPORTED_PREFIX + (slug or EMPTY_SLUG)


@dataclass(frozen=True)
class LayerImport:
    """El resultado de :func:`import_layer`: la operación (``uid``, como el de un recálculo),
    la entrada registrada (o la reutilizada) y lo importado (``None`` si se reutilizó)."""

    operation_uid: str
    input: InputRecord
    dataset: DatasetRecord | None = None
    reuse: input_registry.Reuse | None = None

    @property
    def uid(self) -> str:
        """El uid de la operación ``core.import_layer``."""
        return self.operation_uid

    @property
    def reused(self) -> bool:
        """Si la capa ya estaba registrada con el mismo contenido y los mismos ajustes."""
        return self.reuse is not None

    @property
    def table(self) -> str | None:
        """La tabla de lo importado (``None`` si se reutilizó)."""
        return None if self.dataset is None else self.dataset.locator

    def text(self, language: str = "es") -> str:
        """Lo que pasó, en ``language``: el aviso de la spec §8 si se reutilizó."""
        if self.reuse is not None:
            return self.reuse.render(language)
        return render("core.layer_imported", language=language, layer=self.input.layer,
                      name=self.input.name, table=self.table)


# --- La capa en su GeoPackage -------------------------------------------------------------------


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True)
class _Layer:
    """Lo que se copia de una capa o tabla: su nombre exacto, su tipo, su fila de
    ``gpkg_contents``, su clave entera (el ``fid``, si la tiene), su geometría (columna, tipo,
    dimensiones) con su SRS y las demás columnas con su tipo declarado."""

    name: str
    data_type: str
    kind: str
    identifier: str | None
    extent: tuple[Any, Any, Any, Any]
    key: str | None
    geometry: tuple[str, str, int, int] | None
    srs: tuple[Any, ...] | None
    columns: tuple[tuple[str, str], ...]

    @property
    def crs(self) -> dict[str, int] | None:
        """``{"epsg": n}`` si la capa declara un CRS de EPSG."""
        if self.srs is None:
            return None
        organization, code = self.srs[2], self.srs[3]
        if (isinstance(organization, str) and organization.upper() == "EPSG"
                and type(code) is int and code > 0):
            return {"epsg": code}
        return None

    @property
    def has_z(self) -> bool:
        return self.geometry is not None and bool(self.geometry[2])


def _missing(conn: sqlite3.Connection, layer: str, *, source: str, name: str,
             project: bool) -> SettingsNeeded:
    """La capa no está: el importador pide la capa, con las que se pueden registrar."""
    if project:
        layers = [item.name for item in unregistered_tables(conn) if item.registrable]
    else:
        layers = sorted((str(row[0]) for row in conn.execute(
            "SELECT table_name, data_type FROM gpkg_contents")
            if str(row[1]).lower() in LAYER_KINDS), key=str.casefold)
    return SettingsNeeded("core.import_layer_missing", needed=(LAYER_SETTING,),
                          choices={LAYER_SETTING: layers}, layer=layer, source=source,
                          name=name, layers=", ".join(f"«{item}»" for item in layers) or "—")


def _inspect(conn: sqlite3.Connection, layer: str, *, source: str, name: str,
             project: bool) -> _Layer:
    """Comprueba que ``layer`` es una capa de entidades o una tabla del GeoPackage y dice cómo
    se copia (lo demás lo comprueba su hash, con ``core.gpkg_layer``)."""
    known = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = "
                         "'gpkg_contents'").fetchone()
    if known is None:
        raise ProvenanceError("core.import_layer_not_gpkg", source=source)
    row = conn.execute(
        "SELECT table_name, data_type, identifier, min_x, min_y, max_x, max_y "
        "FROM gpkg_contents WHERE table_name = ?", (layer,)).fetchone()
    info = conn.execute("SELECT name, type, pk FROM pragma_table_info(?) ORDER BY cid",
                        (layer,)).fetchall() if row is not None else []
    if row is None or not info:
        raise _missing(conn, layer, source=source, name=name, project=project)
    kind = LAYER_KINDS.get(str(row[1]).lower())
    if kind is None:
        raise ProvenanceError("core.import_layer_kind", layer=layer, source=source,
                              data_type=row[1])
    geometry = srs = None
    if kind == "vector":
        found = conn.execute("SELECT column_name, geometry_type_name, srs_id, z, m FROM "
                             "gpkg_geometry_columns WHERE table_name = ?", (layer,)).fetchone()
        if found is not None:
            column = next((str(item[0]) for item in info
                           if str(item[0]).lower() == str(found[0]).lower()), str(found[0]))
            if not isinstance(found[1], str) or _GEOMETRY_TYPE.fullmatch(found[1]) is None:
                raise ValidationError("core.content_layer_invalid",
                                      "su tipo de geometría no es del estándar GeoPackage",
                                      obj="Capa de GeoPackage", field="capa", value=layer)
            geometry = (column, found[1], found[3], found[4])
            srs = conn.execute(
                "SELECT srs_name, srs_id, organization, organization_coordsys_id, definition, "
                "description FROM gpkg_spatial_ref_sys WHERE srs_id = ?", (found[2],)).fetchone()
    keys = [(str(name_), str(sql_type)) for name_, sql_type, pk in info if pk]
    key = keys[0][0] if len(keys) == 1 and keys[0][1].strip().upper() == "INTEGER" else None
    skip = {key, None if geometry is None else geometry[0]}
    columns = tuple((str(name_), str(sql_type)) for name_, sql_type, _pk in info
                    if name_ not in skip)
    data_type = "features" if kind == "vector" else "attributes"
    return _Layer(str(row[0]), data_type, kind, row[2], tuple(row[3:7]), key, geometry,
                  None if srs is None else tuple(srs), columns)


def _digest(conn: sqlite3.Connection, path: Path, layer: _Layer,
            declarations: Mapping[str, Any]) -> ContentDigest:
    """Sus hashes con el lector de ``core`` (el mismo que la comprueba después)."""
    request = GPKG_LAYER.request(layer.kind, declarations, {"main": path},
                                 {LAYER_SETTING: layer.name})
    for _ in layer_steps(conn, request):
        pass
    return request.hasher.digest()


@contextmanager
def _external(path: Path) -> Iterator[sqlite3.Connection]:
    """Una instantánea de lectura del GeoPackage ``path`` (en una copia privada si está en WAL
    o tiene un diario pendiente): nada se crea ni cambia junto a él."""
    with tempfile.TemporaryDirectory(prefix=PRIVATE_PREFIX) as private:
        with GpkgConnection.open_read(path, Path(private)) as db:
            conn = db.connection
            conn.execute("BEGIN")
            yield conn


# --- Lo importado -------------------------------------------------------------------------------


def _taken(conn: sqlite3.Connection, name: str) -> bool:
    """Si ``name`` ya es de algo de la base: un objeto, una capa o la ubicación de un dato
    (también de uno sustituido: una ubicación no se reutiliza)."""
    lowered = name.lower()
    return any(conn.execute(sql, (lowered,)).fetchone() is not None for sql in (
        "SELECT 1 FROM sqlite_master WHERE lower(name) = ?",
        "SELECT 1 FROM gpkg_contents WHERE lower(table_name) = ?",
        "SELECT 1 FROM gb_dataset WHERE store = 'gpkg' AND lower(locator) = ?",
    ))


def _numbered(base: str, free: Any) -> str:
    number = 1
    while True:
        candidate = base if number == 1 else f"{base}_{number}"
        if free(candidate):
            return candidate
        number += 1


def _dataset_name(conn: sqlite3.Connection, input_name: str) -> str:
    """El nombre de lo importado: el de la entrada (estable al actualizarla: lo importado
    antes ya está sustituido) o, si es el de otro dato vivo, numerado."""
    return _numbered(imported_name(input_name), lambda candidate: conn.execute(
        f"SELECT 1 FROM gb_dataset WHERE name = ? AND status IN ({_LIVE})", (candidate,)
    ).fetchone() is None)


def _project_srs(conn: sqlite3.Connection, srs: tuple[Any, ...] | None) -> int:
    """El SRS del proyecto con el de la capa (el mismo, uno igual o uno nuevo)."""
    if srs is None:
        return -1  # sin SRS registrado: «cartesiano sin definir» del estándar
    name, srs_id, organization, code, definition, description = srs
    same = conn.execute("SELECT organization, organization_coordsys_id FROM "
                        "gpkg_spatial_ref_sys WHERE srs_id = ?", (srs_id,)).fetchone()
    if same is not None and str(same[0]).upper() == str(organization).upper() and same[1] == code:
        return int(srs_id)
    if str(organization).upper() != "NONE":
        other = conn.execute(
            "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE upper(organization) = upper(?) AND "
            "organization_coordsys_id = ? ORDER BY srs_id LIMIT 1", (organization, code)
        ).fetchone()
        if other is not None:
            return int(other[0])
    chosen = srs_id if same is None else conn.execute(
        "SELECT max(srs_id) + 1 FROM gpkg_spatial_ref_sys").fetchone()[0]
    conn.execute("INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, "
                 "organization_coordsys_id, definition, description) VALUES (?, ?, ?, ?, ?, ?)",
                 (name, chosen, organization, code, definition, description))
    return int(chosen)


def _copy(conn: sqlite3.Connection, source: sqlite3.Connection, layer: _Layer, table: str,
          input_name: str) -> int | None:
    """La copia de la capa en ``table`` (registrada en ``gpkg_contents``): mismas columnas,
    tipos y valores (``fid`` incluido); devuelve su SRS."""
    names = {name.lower() for name, _type in layer.columns}
    if layer.geometry is not None:
        names.add(layer.geometry[0].lower())
    key = layer.key or _numbered("fid", lambda candidate: candidate not in names)
    body = [f"{_quote(key)} INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL"]
    copied = [key] if layer.key else []
    srs_id = None
    if layer.geometry is not None:
        column, geometry_type, z, m = layer.geometry
        srs_id = _project_srs(conn, layer.srs)
        body.append(f"{_quote(column)} {geometry_type}")
        copied.append(column)
    body += [f"{_quote(name)} {sql_type}" for name, sql_type in layer.columns]
    copied += [name for name, _type in layer.columns]
    conn.execute(f"CREATE TABLE {_quote(table)} ({', '.join(body)})")
    identifier = _numbered(table, lambda candidate: conn.execute(
        "SELECT 1 FROM gpkg_contents WHERE identifier = ?", (candidate,)).fetchone() is None)
    conn.execute(
        "INSERT INTO gpkg_contents (table_name, data_type, identifier, description, min_x, "
        "min_y, max_x, max_y, srs_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (table, layer.data_type, identifier,
         f"Lo importado de la entrada «{input_name}» ({IMPORT_LAYER})", *layer.extent, srs_id),
    )
    if layer.geometry is not None:
        conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                     "geometry_type_name, srs_id, z, m) VALUES (?, ?, ?, ?, ?, ?)",
                     (table, layer.geometry[0], layer.geometry[1], srs_id, layer.geometry[2],
                      layer.geometry[3]))
    columns = ", ".join(_quote(name) for name in copied)
    if source is conn:
        conn.execute(f"INSERT INTO {_quote(table)} ({columns}) SELECT {columns} FROM "
                     f"{_quote(layer.name)}")
        return srs_id
    marks = ", ".join("?" for _ in copied)
    cursor = source.execute(f"SELECT {columns} FROM {_quote(layer.name)}")
    try:
        while rows := cursor.fetchmany(ROW_BATCH):
            conn.executemany(f"INSERT INTO {_quote(table)} ({columns}) VALUES ({marks})", rows)
    finally:
        cursor.close()
    return srs_id


# --- Importar -----------------------------------------------------------------------------------


def _previous(project: Any, previous_uid: object, reason: object) -> tuple[InputRecord | None,
                                                                            str | None]:
    """La entrada que se sustituye (activa) y el motivo, obligatorio (RF-008-11)."""
    if reason is not None and not isinstance(reason, str):
        raise TypeError(f"el motivo de una sustitución es un texto, no {reason!r}")
    if previous_uid is None:
        if reason is not None:
            raise ValueError("el motivo acompaña a una sustitución: falta la entrada sustituida "
                             "(previous_uid)")
        return None, None
    if not isinstance(previous_uid, str):
        raise TypeError(f"la entrada sustituida se indica por su uid, no {previous_uid!r}")
    with project.read() as conn:
        record = input_registry.get(conn, previous_uid)
    if record is None:
        raise ProvenanceError("core.input_unknown", input=previous_uid, project=project.name)
    if record.status is InputStatus.SUPERSEDED:
        raise ProvenanceError("core.input_superseded", name=record.name)
    if record.status is InputStatus.DISCARDED:
        raise ProvenanceError("core.input_previous_discarded", previous=record.name)
    text = None if reason is None else reason.strip()
    if not text:
        raise ProvenanceError("core.input_supersede_reason_missing", name=record.name)
    return record, text


def _source(project: Any, source: object) -> Path | None:
    """El GeoPackage externo (``None``: el del proyecto, también si ``source`` es él)."""
    if source is None:
        return None
    path = Path(os.fspath(source))  # type: ignore[arg-type]
    try:
        if os.path.samefile(path, project.database_path):
            return None
    except OSError:
        pass  # no está: lo dice al abrirlo
    return path


def _declared(layer: _Layer, crs_h: Mapping[str, Any] | None,
              crs_v: Mapping[str, Any] | None, name: str) -> tuple[Mapping[str, Any],
                                                                   Mapping[str, Any]]:
    """Los CRS declarados (véase el módulo): nunca se suponen."""
    if crs_h is None:
        crs_h = layer.crs if layer.kind == "vector" else NOT_APPLICABLE
    if crs_v is None and not layer.has_z:
        crs_v = NOT_APPLICABLE
    for axis, crs in (("horizontal", crs_h), ("vertical", crs_v)):
        if crs is None:
            raise ProvenanceError("core.input_crs_missing", name=name, kind=layer.kind,
                                  axis=axis)
    return crs_h, crs_v  # type: ignore[return-value]


def _local_date(moment: str) -> str:
    """Una fecha UTC guardada, como día en hora local (``05/10/2026``), como en el aviso de
    reutilizar una entrada."""
    try:
        return parse_utc(moment).astimezone().strftime("%d/%m/%Y")
    except ValueError:
        return moment


def _check_project_table(conn: sqlite3.Connection, layer: str) -> None:
    """Una tabla del proyecto que es interna, del estándar o de un dato no es una capa sin
    registrar."""
    reserved = layer.lower().startswith(RESERVED_PREFIXES)
    if reserved or conn.execute("SELECT 1 FROM gb_dataset WHERE store = 'gpkg' AND "
                                "lower(locator) = lower(?)", (layer,)).fetchone():
        raise ProvenanceError("core.import_layer_dataset", layer=layer)


def import_layer(
    project: Any,
    layer: str,
    *,
    source: str | os.PathLike[str] | None = None,
    name: str | None = None,
    crs_h: Mapping[str, Any] | None = None,
    crs_v: Mapping[str, Any] | None = None,
    received_at: Any = None,
    received_from: str | None = None,
    previous_uid: str | None = None,
    reason: str | None = None,
) -> LayerImport:
    """Registra como entrada la capa o tabla ``layer`` del GeoPackage ``source`` (``None``: una
    del proyecto, creada desde QGIS) con lo importado en ``core_imported_<slug>`` y su
    operación ``core.import_layer`` (RF-008-07, RF-008-62; véase el módulo):

    - ``name``: el nombre lógico (por defecto, el del fichero sin extensión o el de la tabla);
    - ``crs_h``/``crs_v``: los CRS declarados (por defecto, el de EPSG de la capa y «no
      aplica» sin cotas);
    - ``received_at``/``received_from``: la entrega (D-11);
    - ``previous_uid``/``reason``: la entrada activa a la que sustituye y el motivo (al
      actualizarla, RF-008-11, o con otros ajustes, RF-008-54).

    Devuelve :class:`LayerImport` (``reused`` si ya estaba registrada igual). Rechazos, sin
    escribir nada en el proyecto ni junto a la fuente: :class:`SettingsNeeded`
    (``core.import_layer_missing``: la capa no está), ``ProvenanceError``
    (``core.read_only``, ``core.import_layer_not_gpkg``/``_kind``/``_dataset``,
    ``core.input_crs_missing``, ``core.input_reused``, ``core.input_substitution_required``,
    los de la entrada sustituida), los de lectura de la fuente (``core.gpkg_*``,
    ``core.content_*``) y ``TypeError``/``ValueError`` con un argumento mal formado. Lo que
    falle después deja la operación «fallida» con el motivo y nada más escrito."""
    if not isinstance(layer, str):
        raise TypeError(f"la capa es su nombre en texto, no {layer!r}")
    if not layer:
        raise ValueError("la capa que se importa no puede quedar vacía")
    _require_writable(project)
    previous, text = _previous(project, previous_uid, reason)
    path = _source(project, source)
    chosen = check_name(name if name is not None else (layer if path is None else path.stem))
    if path is None:
        with project.read() as conn:
            _check_project_table(conn, layer)
            found = _inspect(conn, layer, source=project.database_path.name, name=chosen,
                             project=True)
            spec = _spec(project, conn, None, found, chosen, crs_h, crs_v, received_at,
                         received_from)
            classified = input_registry.classify_import(conn, spec)
        return _run(project, None, found, spec, classified, previous, text)
    with _external(path) as conn:
        found = _inspect(conn, layer, source=path.name, name=chosen, project=False)
        spec = _spec(project, conn, path, found, chosen, crs_h, crs_v, received_at,
                     received_from)
        with project.read() as read:
            classified = input_registry.classify_import(read, spec)
        return _run(project, conn, found, spec, classified, previous, text)


def _spec(project: Any, conn: sqlite3.Connection, path: Path | None, layer: _Layer, name: str,
          crs_h: Mapping[str, Any] | None, crs_v: Mapping[str, Any] | None, received_at: Any,
          received_from: str | None) -> InputSpec:
    """La entrada de la capa: su fichero (o su tabla), su huella, sus hashes y sus ajustes."""
    declared_h, declared_v = _declared(layer, crs_h, crs_v, name)
    declarations = input_declarations(declared_h, declared_v, {})
    if path is None:
        digest = _digest(conn, project.database_path, layer, declarations)
        files = [SourceFile(layer.name, FileRole.MAIN, FileAnchor.PROJECT_TABLE)]
        prints = [SourcePrint(digest.data_sha256)]
    else:
        found = os.stat(path)
        prints = [SourcePrint(sha256_file(path), size=found.st_size,
                              mtime_ns=found.st_mtime_ns)]
        digest = _digest(conn, path, layer, declarations)
        files = [input_registry.locate_source(path, project, project.userdata)]
    return InputSpec(name, layer.kind, "core", GPKG_LAYER.id, files=files, file_prints=prints,
                     digest=digest, crs_h=declared_h, crs_v=declared_v, layer=layer.name,
                     settings={LAYER_SETTING: layer.name}, received_at=received_at,
                     received_from=received_from)


def _run(project: Any, source: sqlite3.Connection | None, layer: _Layer, spec: InputSpec,
         classified: Any, previous: InputRecord | None, reason: str | None) -> LayerImport:
    """Con todo comprobado: la operación y, en una transacción, la entrada y lo importado."""
    if isinstance(classified, input_registry.Reuse | input_registry.Substitute) and (
            previous is None or classified.input.uid != previous.uid):
        if isinstance(classified, input_registry.Substitute):
            raise ProvenanceError("core.input_substitution_required", name=spec.name,
                                  existing=classified.input.name,
                                  differences=classified.describe())
        if previous is not None:  # el contenido nuevo es el de otra entrada activa
            raise ProvenanceError("core.input_reused", name=classified.input.name,
                                  registered_on=_local_date(classified.input.registered_at))
    (main,) = spec.files
    settings = {LAYER_SETTING: layer.name,
                "source": {"anchor": str(main.anchor), "path": main.path}}
    supersedes = None if previous is None else previous.operation_uid
    with operation(project, IMPORT_LAYER, settings=settings, supersedes=supersedes) as handle:
        if isinstance(classified, input_registry.Reuse) and previous is None:
            input_registry.reuse_input(project, handle, classified)
            return LayerImport(handle.uid, classified.input, reuse=classified)
        with project.write_transaction() as conn:
            record, dataset = _write(conn, project, handle, source, layer, spec, previous,
                                     reason)
    return LayerImport(handle.uid, record, dataset)


def _write(conn: sqlite3.Connection, project: Any, handle: Any,
           source: sqlite3.Connection | None, layer: _Layer, spec: InputSpec,
           previous: InputRecord | None, reason: str | None) -> tuple[InputRecord,
                                                                      DatasetRecord]:
    """La transacción de la importación: la sustitución, la entrada, la copia y la operación
    completada, comprobando que la copia tiene el contenido de la entrada."""
    if previous is not None:
        input_registry.supersede(conn, project, previous.uid, operation_uid=handle.uid,
                                 reason=reason)
    if source is None:  # una capa del proyecto: lo que se copia es lo que se hashea ahora
        layer = _inspect(conn, layer.name, source=project.database_path.name, name=spec.name,
                         project=True)
        digest = _digest(conn, project.database_path, layer, spec.declarations)
        if digest != spec.digest:
            spec = dataclasses.replace(spec, digest=digest,
                                       file_prints=[SourcePrint(digest.data_sha256)])
    record = input_registry.register_input(
        conn, project, spec, operation_uid=handle.uid,
        previous_uid=None if previous is None else previous.uid,
        reason=None if previous is None else reason,
    )
    name = _dataset_name(conn, record.name)
    table = _numbered(name, lambda candidate: not _taken(conn, candidate))
    srs_id = _copy(conn, conn if source is None else source, layer, table, record.name)
    crs = layer.crs if srs_id is not None else None
    (dataset,) = handle.complete(conn, outputs=[DatasetSpec(
        name, "core", layer.kind, "gpkg", table, reader=GPKG_LAYER.id, role=IMPORTED_ROLE,
        crs_epsg=None if crs is None else crs["epsg"], input_uid=record.uid, immutable=True,
    )])
    expected = content_sha256(layer.kind, DATASET_DECLARATIONS, record.data_sha256,
                              normalizer=dataset.normalizer)
    if dataset.content_sha256 != expected:
        raise RuntimeError(f"la copia de «{layer.name}» en «{table}» no tiene el contenido de "
                           f"la entrada «{record.name}»: no se registra")
    return record, dataset


# --- Reimportar (RF-008-11) -----------------------------------------------------------------------


def reimport_input(project: Any, input_uid: str, reason: str, *,
                   settings: Mapping[str, Any] | None = None, received_at: Any = None,
                   received_from: str | None = None) -> Any:
    """«Actualizar» (RF-008-11): vuelve a importar la entrada activa ``input_uid`` (uid o
    nombre lógico) con el importador registrado de su lector y sus ajustes registrados (o los
    que pidió el importador, ``settings``), como una entrada nueva que la sustituye con
    ``reason`` (obligatorio), y devuelve lo que devuelve el importador (con el ``uid`` de la
    operación nueva). ``ProvenanceError`` sin escribir nada: ``core.input_unknown``,
    ``core.input_superseded``, ``core.input_discarded``,
    ``core.input_supersede_reason_missing`` y ``core.importer_unregistered``; y los del
    importador (:class:`SettingsNeeded` si los ajustes ya no sirven)."""
    if not isinstance(input_uid, str):
        raise TypeError(f"una entrada se indica por su uid o su nombre, no {input_uid!r}")
    if not isinstance(reason, str):
        raise TypeError(f"el motivo de una sustitución es un texto, no {reason!r}")
    with project.read() as conn:
        record = input_registry.get(conn, input_uid)
    if record is None:
        raise ProvenanceError("core.input_unknown", input=input_uid, project=project.name)
    if record.status is InputStatus.SUPERSEDED:
        raise ProvenanceError("core.input_superseded", name=record.name)
    if record.status is InputStatus.DISCARDED:
        raise ProvenanceError("core.input_discarded", name=record.name)
    if not reason.strip():
        raise ProvenanceError("core.input_supersede_reason_missing", name=record.name)
    defn = importer_def(record.reader.partition("@")[0])
    return defn.reimport(ReimportRequest(project, record.uid, reason.strip(), settings=settings,
                                         received_at=received_at, received_from=received_from))


def reimport_layer(request: ReimportRequest) -> LayerImport:
    """El importador de ``core.gpkg_layer``: vuelve a importar la entrada con su capa (o la
    que pidió, ``settings={"layer": …}``) y sus CRS declarados desde su fuente (su GeoPackage,
    o la tabla del proyecto), como una entrada nueva que la sustituye
    (:func:`import_layer` con ``previous_uid``). ``ProvenanceError``
    (``core.reimport_source_missing``) si su fuente no se encuentra; :class:`SettingsNeeded` si
    la capa ya no está; ``ValueError`` con un ajuste que no es la capa."""
    if not isinstance(request, ReimportRequest):
        raise TypeError(f"el importador recibe una ReimportRequest, no {request!r}")
    project = request.project
    with project.read() as conn:
        record = input_registry.get(conn, request.input_uid)
    if record is None:
        raise ProvenanceError("core.input_unknown", input=request.input_uid,
                              project=project.name)
    settings = dict(request.settings or {})
    unknown = sorted(str(key) for key in settings if key != LAYER_SETTING)
    if unknown:
        raise ValueError(f"la importación de una capa solo tiene el ajuste «{LAYER_SETTING}», "
                         f"no {unknown}")
    layer = settings.get(LAYER_SETTING, record.settings.get(LAYER_SETTING, record.layer))
    if len(record.files) != 1:
        raise ValueError(f"la entrada «{record.name}» no es la de una capa: tiene "
                         f"{len(record.files)} ficheros")
    (main,) = record.files
    path = None
    if main.anchor is not FileAnchor.PROJECT_TABLE:
        path = input_registry.resolve_source(main, project, project.userdata)
        if path is None or not path.is_file():
            raise ProvenanceError("core.reimport_source_missing", name=record.name,
                                  file=main.path)
    return import_layer(project, layer, source=path, name=record.name,
                        crs_h=dict(record.crs_h), crs_v=dict(record.crs_v),
                        received_at=request.received_at, received_from=request.received_from,
                        previous_uid=record.uid, reason=request.reason)


CORE_IMPORTERS: tuple[ImporterDef, ...] = (ImporterDef(GPKG_LAYER.reader_id, reimport_layer),)
"""El importador de ``core`` (lo registra ``bl/``): reimporta las entradas del lector
``core.gpkg_layer`` (las capas registradas con ``core.import_layer``)."""
