# SPDX-License-Identifier: GPL-3.0-or-later
"""Declaraciones de procedencia de los sondeos (spec 005, T40; RF-005-07, RF-005-12, RF-005-20,
RF-005-22; RF-008-07, RF-008-17, RF-008-25 a RF-008-27; ADR-0025 §2; plan 005 §5.6.1, §5.6.2 y
§5.6.4).

Lo que los sondeos registran en la procedencia de la 008, declarado con tipos de ``core``, como
``gis.provenance`` (006/T41). Importar este módulo no registra nada: lo registra
``bl/ops/dh.py`` en su ``register()`` (y lo quita en ``unregister()``), con las funciones de
recálculo y de reimportación, que son de ``bl`` porque lanzan trabajos.

**Tipos de operación** (:data:`OPERATION_TYPES`, :class:`OperationType`; versión
:data:`OP_VERSION`): ``dh.import_tabular`` (CSV o XLSX) y ``dh.import_recmin`` (una base de
RecMin) no se repiten solas: se reimportan y quedan «revisar a mano» (RF-008-27);
``dh.build_base`` (la base desde lo importado vigente), ``dh.validate`` y ``dh.desurvey`` se
repiten solas con su función de recálculo (RF-008-26); ``dh.export_validation`` no se repite.
Ninguna está acoplada a otra (RF-008-25). Cada tipo dice las órdenes que lo lanzan (los
``bl_idname`` del catálogo de la 003: la suya y, ``dh.build_base``, que no tiene orden propia,
las que la encadenan), los papeles de lo que consume (``Use``) y los parámetros que lee, las
tablas que escribe (sus :class:`~.schema.TableLayout`), las bibliotecas que influyen en sus
resultados (``pyproj``, la versión fijada en ``tools/wheels.toml``) y, una importación, sus
lectores de contenido (los de ``interop/dh_content.py``, T39: ``drillholes`` no importa
``interop``, ARQ-07, así que aquí van sus identificadores). :func:`operation_def` y
:func:`operation_defs` construyen los ``OperationDef`` con lo que les da ``bl`` (su recálculo
y los ajustes de su orden que enseña su procedencia, 006/T58); :func:`importer_def`, el
``ImporterDef`` de un lector de importación (RF-008-11). Ninguna operación registra cifras: no
hay ``FigureDef`` (los informes de la 005 son diagnósticos, spec §11).

**Datos** (plan §5.6.1, D17): una tabla de ``project.gpkg``, un dato, leído con
``core.gpkg_layer@1``: ``vector`` las bocas y las trazas, ``table`` las demás; ninguno editable a
mano en QGIS (RF-008-56). :func:`dataset_spec` da la ``DatasetSpec`` de una tabla de la base o
de lo calculado (su nombre es el de su tabla); :func:`source_spec`, la de lo importado de un
papel de una entrada: el dato ``dh_src_<rol>_<nombre>`` en la tabla
``dh_src_<rol>_<nombre>_<entrada8>`` (``drillholes.schema``), inmutable con su entrada y sin
selector (RF-008-52). Cada tabla tiene su papel de salida (:data:`OUTPUT_ROLES`), distinto en
cada una: por él se busca el sucesor de lo sustituido.

**Entradas** (D-15): una por fichero (por hoja de un XLSX; la base de RecMin, una).
:func:`input_spec` da su ``InputSpec`` (módulo ``dh``): unas bocas y una base de RecMin son
``drillholes``, con el CRS y el datum declarados (sin declarar, ``None``: los rechazan la
clasificación y el registro, ``core.input_crs_missing``; RF-005-07); las demás tablas,
``table`` sin CRS («no aplica»). Sus ajustes son los de lectura de su lector
(:data:`READING_SETTINGS`, el decimal y el formato de las fechas de la declaración) y, como
contenido (las convenciones de sus declaraciones, ADR-0024 §3), el papel y la correspondencia de
columnas de una tabla y las convenciones de la declaración que cambian lo que significan sus
datos (:data:`ROLE_CONVENTIONS`, :data:`RECMIN_CONVENTIONS`): así el mismo CSV con «;» y coma o
con «,» y punto da el mismo hash de contenido, y otra referencia del azimut, otro. Una
convención de otro papel (la densidad en unas desviaciones) ni se guarda ni cuenta.
:func:`source_declarations` da esas declaraciones al trabajo que calcula el hash de la fuente:
son las mismas que comprueba la entrada.

``core.inputs`` carga ``core.project``, y ``gis``, todo su paquete: este módulo los importa solo
al construir una entrada (los lectores y los trabajos pueden importarlo por sus claves). Python
puro (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ..core.content.builtin import GPKG_LAYER
from ..core.content.encoder import ContentDigest
from ..core.datasets.model import DatasetSpec, Store
from ..core.georef import CrsRef, VerticalRef
from ..core.provenance.contract import (
    ImporterDef,
    OperationDef,
    RecomputeFunction,
    ReimportFunction,
    SettingDef,
)
from .model import SourceDeclaration
from .params import DESURVEY_KEYS, VALIDATION_KEYS
from .schema import (
    BASE_TABLES,
    COMPUTED_TABLES,
    LAYOUTS,
    SOURCE_PREFIX,
    SOURCE_ROLES,
    source_layout,
    source_name,
    source_table,
)

if TYPE_CHECKING:
    from ..core.inputs.model import InputSpec, SourceFile, SourcePrint

__all__ = [
    "BUILD_BASE",
    "DESURVEY",
    "DH_CSV",
    "DH_XLSX",
    "ELLIPSOIDAL_EPSG",
    "EXPORTS",
    "EXPORT_VALIDATION",
    "IMPORTS",
    "IMPORT_READERS",
    "IMPORT_RECMIN",
    "IMPORT_TABULAR",
    "MODULE",
    "OPERATION_TYPES",
    "OPERATION_TYPES_BY_NAME",
    "OP_VERSION",
    "OUTPUT_ROLES",
    "PYPROJ",
    "READER_IDS",
    "READING_SETTINGS",
    "RECMIN_CONVENTIONS",
    "RECMIN_MDB",
    "REPEATABLE",
    "ROLE_CONVENTIONS",
    "TABLE_ROLES",
    "VALIDATE",
    "OperationType",
    "dataset_spec",
    "declared_crs",
    "declared_vertical",
    "importer_def",
    "input_kind",
    "input_spec",
    "operation_def",
    "operation_defs",
    "source_declarations",
    "source_role",
    "source_spec",
]

MODULE = "dh"
"""El código de los sondeos (``core.catalog.schema.MODULE_CODES``)."""
OP_VERSION = "1.0"
"""La versión inicial del algoritmo de cada tipo (sube cuando un cambio puede mover un
resultado, RF-008-24)."""

# --- Tipos de operación ------------------------------------------------------------------------

IMPORT_TABULAR = "dh.import_tabular"
IMPORT_RECMIN = "dh.import_recmin"
BUILD_BASE = "dh.build_base"
VALIDATE = "dh.validate"
DESURVEY = "dh.desurvey"
EXPORT_VALIDATION = "dh.export_validation"

PYPROJ = "pyproj"
"""La biblioteca de las transformaciones de CRS (su versión, la fijada en
``tools/wheels.toml``)."""

DH_CSV = "io.dh_csv@1"
"""El lector de una tabla de sondeos en CSV (T39)."""
DH_XLSX = "io.dh_xlsx@1"
"""El lector de una hoja de un libro XLSX con una tabla de sondeos (T39)."""
RECMIN_MDB = "io.recmin_mdb@1"
"""El lector de una base de sondeos de RecMin (MDB o ACCDB, sobre una copia; T39)."""
READER_IDS: tuple[str, ...] = (DH_CSV, DH_XLSX, RECMIN_MDB)
"""Los lectores de las importaciones, con versión."""
IMPORT_READERS: tuple[str, ...] = tuple(reader.partition("@")[0] for reader in READER_IDS)
"""Los mismos, sin versión: un ``ImporterDef`` por cada uno."""

_IMPORT_COMMAND = "geoblender.dh_import_drillholes"
_RECMIN_COMMAND = "geoblender.dh_import_recmin_mdb"
_AZIMUTH_COMMAND = "geoblender.dh_set_azimuth_reference"  # reimporta (plan §5.6.10)

_TABULAR_SOURCES = ("collar", "survey", "lithology", "assay", "catalog")


def _output_role(table: str) -> str:
    """El papel de salida de la tabla ``table`` (sin el ``dh_``; lo importado,
    ``source_<rol>``)."""
    if table.startswith(SOURCE_PREFIX):
        return "source_" + table.removeprefix(SOURCE_PREFIX)
    return table.removeprefix(f"{MODULE}_")


OUTPUT_ROLES: Mapping[str, str] = MappingProxyType(
    {table: _output_role(table) for table in LAYOUTS})
"""El papel de salida (``gb_operation_io.role``) de cada tabla de los sondeos (por el nombre de
su ``TableLayout``; lo importado, por ``dh_src_<rol>``): distinto en cada una."""

_BASE_ROLES = tuple(OUTPUT_ROLES[table] for table in BASE_TABLES)


@dataclass(frozen=True, slots=True)
class OperationType:
    """Un tipo de operación de la 005 sin su función de recálculo (plan §5.6.4): ``op_type``,
    su nombre visible (``label_msgid``, con su español en ``core/i18n/messages.toml``), si se
    repite solo, las órdenes que lo lanzan (``commands``), los papeles de lo que consume
    (``inputs``, los de ``Use``), las tablas que escribe (``outputs``, por el nombre de su
    ``TableLayout``: lo importado, ``dh_src_<rol>``), las bibliotecas que influyen en sus
    resultados (``libraries``), los parámetros que lee (``params``, de :mod:`.params`) y, una
    importación, los lectores de su entrada (``readers``, con versión)."""

    op_type: str
    label_msgid: str
    repeatable: bool
    commands: tuple[str, ...]
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    libraries: tuple[str, ...] = ()
    params: tuple[str, ...] = ()
    readers: tuple[str, ...] = ()

    def definition(self, recompute: RecomputeFunction | None = None,
                   settings: Iterable[SettingDef] = ()) -> OperationDef:
        """Su ``OperationDef`` (versión :data:`OP_VERSION`, del proyecto, sin grupo) con la
        función de recálculo ``recompute``: la de ``bl`` si se repite solo y ``None`` si no
        (si no, ``ValueError`` de ``OperationDef``), y los ajustes de su orden que enseña su
        procedencia (``settings``)."""
        return OperationDef(
            self.op_type,
            OP_VERSION,
            MODULE,
            self.label_msgid,
            self.repeatable,
            commands=self.commands,
            libraries=self.libraries,
            recompute=recompute,
            settings=tuple(settings),
        )


OPERATION_TYPES: tuple[OperationType, ...] = (
    OperationType(IMPORT_TABULAR, "Import of drillhole tables", False,
                  (_IMPORT_COMMAND, _AZIMUTH_COMMAND),
                  outputs=(*(f"{SOURCE_PREFIX}{role}" for role in _TABULAR_SOURCES),
                           "dh_import_log"),
                  libraries=(PYPROJ,), readers=(DH_CSV, DH_XLSX)),
    OperationType(IMPORT_RECMIN, "Import of a RecMin drillhole database", False,
                  (_RECMIN_COMMAND, _AZIMUTH_COMMAND),
                  outputs=(*(f"{SOURCE_PREFIX}{role}" for role in SOURCE_ROLES),
                           "dh_import_log"),
                  libraries=(PYPROJ,), readers=(RECMIN_MDB,)),
    OperationType(BUILD_BASE, "Build of the drillhole database", True,
                  (_IMPORT_COMMAND, _RECMIN_COMMAND, _AZIMUTH_COMMAND),
                  inputs=("source", "imports"), outputs=BASE_TABLES, libraries=(PYPROJ,)),
    OperationType(VALIDATE, "Validation of the drillhole database", True,
                  ("geoblender.dh_validate",), inputs=(*_BASE_ROLES, "terrain"),
                  outputs=("dh_validation_issue",), params=VALIDATION_KEYS),
    OperationType(DESURVEY, "Computation of the drillhole traces", True,
                  ("geoblender.dh_desurvey",), inputs=("collar", "survey"),
                  outputs=("dh_trace",), params=DESURVEY_KEYS),
    OperationType(EXPORT_VALIDATION, "Export of the validation report", False,
                  ("geoblender.dh_export_validation_report",), inputs=("exported",)),
)
"""Los tipos de operación de la 005, en el orden del plan §5.6.4."""
OPERATION_TYPES_BY_NAME: Mapping[str, OperationType] = MappingProxyType(
    {declared.op_type: declared for declared in OPERATION_TYPES})
"""Los tipos de operación por nombre (solo lectura)."""
IMPORTS: tuple[str, ...] = tuple(t.op_type for t in OPERATION_TYPES if t.readers)
"""Las importaciones (registran su entrada; se reimportan)."""
EXPORTS: tuple[str, ...] = (EXPORT_VALIDATION,)
"""Las exportaciones."""
REPEATABLE: tuple[str, ...] = tuple(t.op_type for t in OPERATION_TYPES if t.repeatable)
"""Los tipos que se repiten solos con su función de recálculo (RF-008-26)."""


def _operation_type(op_type: object) -> OperationType:
    found = OPERATION_TYPES_BY_NAME.get(op_type) if isinstance(op_type, str) else None
    if found is None:
        raise ValueError(f"{op_type!r} no es un tipo de operación de los sondeos: es uno de "
                         f"{', '.join(OPERATION_TYPES_BY_NAME)}")
    return found


def operation_def(op_type: str, recompute: RecomputeFunction | None = None, *,
                  settings: Iterable[SettingDef] = ()) -> OperationDef:
    """El ``OperationDef`` del tipo ``op_type`` con la función de recálculo ``recompute``
    que le da ``bl`` (la de un tipo que se repite solo; ``None`` en una importación o en la
    exportación) y los ajustes de su orden que enseña su procedencia (``settings``, de
    ``bl``). ``ValueError`` si el tipo no es de la 005, si se repite solo y no recibe su
    función, o si no se repite y la recibe; ``TypeError`` si ``recompute`` no es una
    función."""
    return _operation_type(op_type).definition(recompute, settings)


def operation_defs(
    recompute: Mapping[str, RecomputeFunction],
    *,
    op_types: Iterable[str] | None = None,
    settings: Mapping[str, Iterable[SettingDef]] | None = None,
) -> tuple[OperationDef, ...]:
    """Los ``OperationDef`` de ``op_types`` (todos, por defecto, en el orden de
    :data:`OPERATION_TYPES`), cada uno con su función de ``recompute`` (por tipo: la de cada
    uno que se repite solo, y ninguna más) y sus ajustes de ``settings`` (por tipo: los de su
    orden que enseña su procedencia; los que no están, ninguno). ``ValueError`` si un tipo no
    es de la 005 o se repite en ``op_types``, si falta la función de uno que se repite solo, o
    si ``recompute`` trae una para un tipo que no se construye o que no se repite, o
    ``settings`` unos ajustes de un tipo que no se construye."""
    chosen = OPERATION_TYPES if op_types is None else tuple(_operation_type(name)
                                                            for name in op_types)
    names = [declared.op_type for declared in chosen]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(f"tipos de operación repetidos: {', '.join(repeated)}")
    extra = sorted(set(recompute) - set(names))
    if extra:
        raise ValueError(f"funciones de recálculo de tipos que no se construyen: "
                         f"{', '.join(map(str, extra))}")
    shown = {} if settings is None else dict(settings)
    extra = sorted(set(shown) - set(names))
    if extra:
        raise ValueError(f"ajustes de tipos que no se construyen: {', '.join(map(str, extra))}")
    return tuple(declared.definition(recompute.get(declared.op_type),
                                     shown.get(declared.op_type, ()))
                 for declared in chosen)


def importer_def(reader_id: str, reimport: ReimportFunction) -> ImporterDef:
    """El ``ImporterDef`` del lector de importación ``reader_id`` (sin versión, de
    :data:`IMPORT_READERS`) con la función de reimportación ``reimport`` que le da ``bl``
    (RF-008-11). ``ValueError`` si el lector no es de una importación de la 005;
    ``TypeError`` si ``reimport`` no es una función."""
    if reader_id not in IMPORT_READERS:
        raise ValueError(f"{reader_id!r} no es el lector de una importación de los sondeos "
                         f"(sin versión): es uno de {', '.join(IMPORT_READERS)}")
    return ImporterDef(reader_id, reimport)


# --- Datos ---------------------------------------------------------------------------------


def dataset_spec(table: str, *, content: ContentDigest | None = None,
                 crs_epsg: int | None = None, detail: Any = None) -> DatasetSpec:
    """La ``DatasetSpec`` de la tabla ``table`` de la base (``drillholes.schema.BASE_TABLES``)
    o de lo calculado (``COMPUTED_TABLES``) (RF-008-17): el dato con el nombre de su tabla, en
    ``project.gpkg``, ``vector`` (bocas y trazas) o ``table``, con ``core.gpkg_layer@1`` y su
    papel de :data:`OUTPUT_ROLES`; sin entrada ni selector y no editable a mano en QGIS
    (RF-008-56). ``content`` (el hash que dio el trabajo con ``core.gpkg_layer@1``),
    ``crs_epsg`` y ``detail`` (los sondeos cambiados, RF-005-22) pasan tal cual; lo que no
    admite ``DatasetSpec`` es su ``ValueError`` o ``TypeError``. ``ValueError`` si ``table`` no
    es una tabla de la base ni de lo calculado (lo importado es :func:`source_spec`)."""
    if table not in BASE_TABLES and table not in COMPUTED_TABLES:
        raise ValueError(f"{table!r} no es una tabla de la base ni de lo calculado de los "
                         f"sondeos: es una de {', '.join(BASE_TABLES + COMPUTED_TABLES)} (lo "
                         "importado, con source_spec)")
    return DatasetSpec(table, MODULE, LAYOUTS[table].kind, Store.GPKG, table,
                       reader=GPKG_LAYER.id, role=OUTPUT_ROLES[table], content=content,
                       crs_epsg=crs_epsg, detail=detail)


def source_spec(role: str, name: str, input_uid: str, *, content: ContentDigest | None = None,
                crs_epsg: int | None = None) -> DatasetSpec:
    """La ``DatasetSpec`` de lo importado del papel ``role`` (``drillholes.schema.SOURCE_ROLES``)
    de la entrada ``input_uid`` con la orden llamada ``name`` (RF-008-17, RF-008-52): el dato
    ``dh_src_<rol>_<nombre>`` (``schema.source_name``) en la tabla
    ``dh_src_<rol>_<nombre>_<entrada8>`` (``schema.source_table``: la 008 no reutiliza una
    ubicación), ``table`` con ``core.gpkg_layer@1``, su papel ``source_<rol>``, inmutable con
    su entrada y sin selector (una tabla por dato). ``content`` y ``crs_epsg`` (el CRS
    declarado de las coordenadas) pasan tal cual. ``ValueError`` si el papel no es de lo
    importado o ``input_uid`` no es el uid de una entrada; el nombre sin letras ni cifras, el
    ``ValidationError`` ``dh.dataset_name_invalid`` de ``schema.slug``."""
    layout = source_layout(role)
    return DatasetSpec(source_name(role, name), MODULE, layout.kind, Store.GPKG,
                       source_table(role, name, input_uid), reader=GPKG_LAYER.id,
                       role=OUTPUT_ROLES[layout.name], content=content, crs_epsg=crs_epsg,
                       input_uid=input_uid, immutable=True)


# --- Entradas ------------------------------------------------------------------------------

TABLE_ROLES: tuple[str, ...] = ("collar", "survey", "lithology", "assay_wide", "assay_long",
                                "lithology_catalog", "element_catalog")
"""Los papeles de una tabla de CSV o XLSX (los de ``interop.drillholes_tabular.TableRole``):
bocas, desviaciones, litología, análisis en columnas y en filas y catálogos de litologías y de
elementos."""
_SOURCE_OF_ROLE: Mapping[str, str] = MappingProxyType({
    "collar": "collar",
    "survey": "survey",
    "lithology": "lithology",
    "assay_wide": "assay",
    "assay_long": "assay",
    "lithology_catalog": "catalog",
    "element_catalog": "catalog",
})
_ORIENTATION = ("all_vertical", "azimuth_ref", "declination_deg", "inclination_convention")
_VALUES = ("negative_is_below_dl", "sentinels", "units")
ROLE_CONVENTIONS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "collar": _ORIENTATION,
    "survey": _ORIENTATION,
    "lithology": (),
    "assay_wide": _VALUES,
    "assay_long": _VALUES,
    "lithology_catalog": ("density_kind",),
    "element_catalog": ("units",),
})
"""Las convenciones de la declaración (``SourceDeclaration.conventions``) que son contenido de
una tabla de cada papel (plan §5.6.2): la orientación de unas bocas (la de la boca) y de unas
desviaciones, con «todos verticales» (los sondeos sin desviaciones: lo lleva el fichero de
bocas si no hay de desviaciones); las unidades, los centinelas y «−x = <x» de unos análisis; el
tipo de la densidad de un catálogo de litologías y las unidades de uno de elementos. Además, el
papel (``role``) y la correspondencia de columnas (``mapping``)."""
RECMIN_CONVENTIONS: tuple[str, ...] = ("azimuth_ref", "declination_deg", "density_kind",
                                       "negative_is_below_dl", "sentinels", "units")
"""Las de una base de RecMin (plan §5.6.2): su inclinación es siempre negativa hacia abajo y
nunca «todos verticales» (``interop.recmin``); las unidades, de los elementos cuya unidad de
RecMin no es de ley, y los centinelas, de los números escritos como texto."""
READING_SETTINGS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    DH_CSV: ("encoding", "separator", "header_row"),
    DH_XLSX: ("sheet", "header_row"),
    RECMIN_MDB: (),
})
"""Los ajustes de lectura de cada lector que da quien importa (todos), además del decimal y el
formato de las fechas de la declaración (``decimal``, ``date_format``; RecMin, solo el
decimal): no son contenido (plan §5.6.2). La hoja de un XLSX es la capa de su entrada."""
ELLIPSOIDAL_EPSG = 4937
"""La altura elipsoidal ETRS89 declarada en una entrada (``{"ellipsoidal": 4937}``, como la
registra la 006)."""
_NOT_APPLICABLE = MappingProxyType({"not_applicable": True})


def _reader(reader: object) -> str:
    if not isinstance(reader, str) or reader not in READER_IDS:
        raise ValueError(f"{reader!r} no es el lector de una importación de los sondeos (con "
                         f"versión): es uno de {', '.join(READER_IDS)}")
    return reader


def _role(reader: str, role: object) -> str | None:
    """El papel de la tabla de ``reader``: uno de :data:`TABLE_ROLES` en CSV y XLSX; ninguno
    en RecMin."""
    if reader == RECMIN_MDB:
        if role is not None:
            raise ValueError(f"una base de RecMin no tiene papel: lleva todas sus tablas, no "
                             f"{role!r}")
        return None
    if not isinstance(role, str) or role not in TABLE_ROLES:
        raise ValueError(f"el papel (role) de una tabla de «{reader}» es uno de "
                         f"{', '.join(TABLE_ROLES)}, no {role!r}")
    return role


def input_kind(reader: str, role: str | None = None) -> str:
    """El tipo de la entrada que lee ``reader`` (con versión) con el papel ``role``: unas bocas
    de CSV o XLSX y una base de RecMin, ``drillholes``; las demás tablas, ``table``.
    ``ValueError`` si no es el lector de una importación de la 005, o el papel no es de los
    suyos."""
    found = _role(_reader(reader), role)
    return "drillholes" if found in (None, "collar") else "table"


def source_role(table_role: str) -> str:
    """El papel de lo importado (``dh_src_<rol>``) de una tabla de CSV o XLSX con el papel
    ``table_role``: los análisis en columnas y en filas, ``assay``; los dos catálogos,
    ``catalog``. ``ValueError`` si no es uno de :data:`TABLE_ROLES`."""
    found = _SOURCE_OF_ROLE.get(table_role) if isinstance(table_role, str) else None
    if found is None:
        raise ValueError(f"{table_role!r} no es el papel de una tabla de sondeos: es uno de "
                         f"{', '.join(TABLE_ROLES)}")
    return found


def declared_crs(crs: CrsRef | None) -> dict[str, Any] | None:
    """El CRS horizontal declarado de una entrada (``core.inputs``): ``{"epsg": n}``, o
    ``None`` si no se declaró (nunca se supone, RF-005-07)."""
    if crs is None:
        return None
    if not isinstance(crs, CrsRef):
        raise TypeError(f"el CRS horizontal declarado es un CrsRef del catálogo, no {crs!r}")
    return {"epsg": crs.epsg}


def declared_vertical(vertical: VerticalRef | None) -> dict[str, Any] | None:
    """El datum vertical declarado de una entrada, como lo registra la 006: ``{"epsg": n}``,
    ``{"local": nota}`` o, la altura elipsoidal ETRS89, ``{"ellipsoidal": 4937}``; ``None`` si
    no se declaró (RF-005-07, D-12)."""
    if vertical is None:
        return None
    if not isinstance(vertical, VerticalRef):
        raise TypeError(f"el datum vertical declarado es un VerticalRef, no {vertical!r}")
    if vertical.kind == "epsg":
        return {"epsg": vertical.epsg}
    if vertical.kind == "local":
        return {"local": vertical.note}
    from ..gis.crs import ELLIPSOIDAL_ETRS89  # carga todo gis: solo con una cota elipsoidal

    if vertical == ELLIPSOIDAL_ETRS89:
        return {"ellipsoidal": ELLIPSOIDAL_EPSG}
    return {"ellipsoidal": vertical.name}


def _mapping(reader: str, mapping: object) -> dict[str, str] | None:
    """La correspondencia de columnas (campo → columna de la fuente) de una tabla."""
    if reader == RECMIN_MDB:
        if mapping is not None:
            raise ValueError("una base de RecMin no tiene correspondencia de columnas (mapping)")
        return None
    if mapping is None:
        raise ValueError(f"falta la correspondencia de columnas (mapping) de una tabla de "
                         f"«{reader}»")
    if not isinstance(mapping, Mapping):
        raise TypeError(f"la correspondencia de columnas (mapping) es {{campo: columna}}, no "
                        f"{mapping!r}")
    found = dict(mapping)
    if not found:
        raise ValueError("la correspondencia de columnas (mapping) de una tabla no puede "
                         "quedar vacía")
    for field, column in found.items():
        if not isinstance(field, str) or not isinstance(column, str):
            raise TypeError(f"la correspondencia de columnas (mapping) es de textos, no "
                            f"{field!r}: {column!r}")
    return found


def _declaration(declaration: object) -> SourceDeclaration:
    if not isinstance(declaration, SourceDeclaration):
        raise TypeError(f"la declaración de una importación (declaration) es un "
                        f"drillholes.model.SourceDeclaration, no {declaration!r}")
    return declaration


@dataclass(frozen=True, slots=True)
class _Entry:
    """Lo que se registra de una entrada salvo sus ficheros, sus hashes y su entrega: su
    tipo, sus CRS declarados, sus convenciones (contenido) y sus ajustes de lectura."""

    kind: str
    crs_h: Mapping[str, Any] | None
    crs_v: Mapping[str, Any] | None
    conventions: dict[str, Any]
    reading: dict[str, Any]


def _entry(reader: object, declaration: object, role: object, mapping: object) -> _Entry:
    found = _reader(reader)
    decl = _declaration(declaration)
    chosen = _role(found, role)
    columns = _mapping(found, mapping)
    keys = RECMIN_CONVENTIONS if chosen is None else ROLE_CONVENTIONS[chosen]
    declared = decl.conventions()
    conventions: dict[str, Any] = {key: declared[key] for key in keys}
    if chosen is not None:
        conventions = {"role": chosen, "mapping": columns, **conventions}
    reading: dict[str, Any] = {"decimal": decl.value_rules.decimal_mark}
    if chosen is not None:
        reading["date_format"] = decl.date_format
    kind = input_kind(found, chosen)
    if kind == "drillholes":
        crs_h, crs_v = declared_crs(decl.crs), declared_vertical(decl.vertical)
    else:  # una tabla sin coordenadas: su CRS «no aplica»
        crs_h = crs_v = _NOT_APPLICABLE
    return _Entry(kind, crs_h, crs_v, conventions, reading)


def source_declarations(reader: str, declaration: SourceDeclaration, *,
                        role: str | None = None,
                        mapping: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Las declaraciones (``DECL``, ADR-0024 §3) con que el trabajo de una importación con
    ``reader`` (con versión) calcula el ``ContentDigest`` de la fuente: sus CRS declarados (los
    de la declaración en unas bocas y en RecMin; «no aplica» en las demás tablas) y sus
    convenciones: el papel ``role`` y la correspondencia de columnas ``mapping`` de una tabla y
    lo de la declaración que es contenido de su papel (:data:`ROLE_CONVENTIONS`,
    :data:`RECMIN_CONVENTIONS`). Las mismas que comprueba :func:`input_spec`. Los errores, los
    suyos."""
    from ..core.inputs.model import input_declarations  # carga core.project: solo al usarlo

    entry = _entry(reader, declaration, role, mapping)
    return input_declarations(entry.crs_h, entry.crs_v, entry.conventions)


def _reading(reader: str, settings: object) -> dict[str, Any]:
    """Los ajustes de lectura de ``reader`` que da quien importa: todos los de
    :data:`READING_SETTINGS`, y ninguno más."""
    if settings is not None and not isinstance(settings, Mapping):
        raise TypeError(f"los ajustes de lectura de una importación son un diccionario, no "
                        f"{settings!r}")
    chosen = dict(settings or {})
    allowed = READING_SETTINGS[reader]
    unknown = sorted(str(key) for key in chosen if key not in allowed)
    missing = [key for key in allowed if key not in chosen]
    if unknown or missing:
        raise ValueError(f"los ajustes de lectura de «{reader}» son {list(allowed)}: faltan "
                         f"{missing} y sobran {unknown}")
    for key in ("encoding", "separator", "sheet"):
        if key in chosen and (not isinstance(chosen[key], str) or not chosen[key]):
            raise ValueError(f"el ajuste de lectura «{key}» de «{reader}» es un texto no vacío, "
                             f"no {chosen[key]!r}")
    if "header_row" in chosen:
        header = chosen["header_row"]
        if isinstance(header, bool) or not isinstance(header, int):
            raise TypeError(f"el ajuste de lectura «header_row» (las filas antes de la "
                            f"cabecera) es un entero, no {header!r}")
        if header < 0:
            raise ValueError(f"el ajuste de lectura «header_row» (las filas antes de la "
                             f"cabecera) no es negativo: {header}")
    return chosen


def input_spec(
    reader: str,
    name: str,
    *,
    files: Sequence[SourceFile],
    file_prints: Sequence[SourcePrint],
    digest: ContentDigest,
    declaration: SourceDeclaration,
    role: str | None = None,
    mapping: Mapping[str, str] | None = None,
    settings: Mapping[str, Any] | None = None,
    received_at: Any = None,
    received_from: str | None = None,
) -> InputSpec:
    """La entrada (``InputSpec`` de la 008, RF-008-07) de un fichero de una importación de
    sondeos con el lector ``reader`` (con versión; D-15: una por fichero, por hoja de un XLSX,
    o la base de RecMin): su nombre lógico ``name``, su tipo (:func:`input_kind`),
    ``module="dh"``, sus ficheros (``files``, con el ancla de ``core.inputs.locate_source``: el
    principal el primero) y sus huellas, el ``digest`` que dio el trabajo con
    :func:`source_declarations`, sus CRS declarados (los de ``declaration`` en unas bocas y en
    RecMin, ``None`` si no se declararon: los rechazan la clasificación y el registro,
    ``core.input_crs_missing``, RF-005-07; «no aplica» en las demás tablas), la hoja de un XLSX
    como su capa, sus ajustes y los que son contenido (véase el módulo), y la entrega (fecha y
    quién, opcionales).

    ``role`` y ``mapping``: el papel (:data:`TABLE_ROLES`) y la correspondencia de columnas
    (campo → columna) de una tabla de CSV o XLSX; ninguno en RecMin. ``settings``: los ajustes
    de lectura de su lector (:data:`READING_SETTINGS`, todos).

    ``ValueError`` (un error del programa: el diálogo solo ofrece lo válido) con un lector que
    no es de una importación de la 005, un papel o una correspondencia que faltan o sobran, un
    ajuste de lectura que falta, sobra o no vale, o un hash que no es el de sus datos con esas
    declaraciones; ``TypeError`` con un argumento de otro tipo."""
    from ..core.inputs.model import InputSpec  # carga core.project: solo al usarlo

    entry = _entry(reader, declaration, role, mapping)
    reading = _reading(reader, settings)
    values = {**entry.conventions, **reading, **entry.reading}
    return InputSpec(
        name,
        entry.kind,
        MODULE,
        reader,
        files=files,
        file_prints=file_prints,
        digest=digest,
        crs_h=entry.crs_h,
        crs_v=entry.crs_v,
        layer=reading.get("sheet"),
        settings=values,
        content_settings_keys=tuple(entry.conventions),
        received_at=received_at,
        received_from=received_from,
    )
