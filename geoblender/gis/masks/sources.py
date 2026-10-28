# SPDX-License-Identifier: GPL-3.0-or-later
"""Crear restricciones desde una capa del proyecto (spec 012, T14; HU-012-1, HU-012-2;
RF-012-01, RF-012-02; plan 012 §5.2.2, D-5, D-22, D-27).

Lo que ``core`` no puede leer (nivel 0): las entidades de una capa «entidades» (``gis_fea_``:
puntos, líneas o polígonos con sus atributos) o «dominios» (``gis_dom_``: polígonos) del
proyecto. :func:`create_constraints` las lee (solo lee: la capa de origen no cambia, D-17),
resuelve los campos que elige la persona (por su columna o su título) y pide a
``core.constraints.provenance.create_constraints`` que las cree con ``core.edit_constraints``
(con la capa como entrada ``source``), con su origen (la entrada de la capa y la entidad) y los
parámetros que declara la persona; las entidades que no sirven quedan rechazadas con su motivo.
Python puro con numpy (nivel 2).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ...core.constraints import provenance as cprov
from ...core.constraints.messages import ConstraintError
from ...core.constraints.model import GeometryKind
from ...core.datasets import registry as dataset_registry
from .. import store as gstore
from ..provenance import DOMAINS, FAMILIES_BY_CODE, FEATURES
from ..store import StoreProject
from ..vector import FeatureLayer

__all__ = ["create_constraints", "source_entities"]


def _family(name: str) -> str | None:
    for code in (FEATURES, DOMAINS):
        if name.startswith(FAMILIES_BY_CODE[code].prefix):
            return code
    return None


def source_entities(project: StoreProject, source: str
                    ) -> tuple[tuple[cprov.SourceEntity, ...], tuple[tuple[str, str], ...]]:
    """Las entidades de la capa ``source`` (un dato ``gis_fea_`` o ``gis_dom_`` del proyecto)
    con sus atributos por columna, y sus campos (columna, título). ``ValueError`` si es de otra
    familia; los errores de ``gis.store`` si no está."""
    family = _family(source)
    if family is None:
        raise ValueError(f"las restricciones se crean desde una capa «entidades» o «dominios» "
                         f"del proyecto, no desde «{source}»")
    if family == FEATURES:
        layer = gstore.load_features(project, source)
        assert isinstance(layer, FeatureLayer)
        fields = tuple((column.column, column.field) for column in layer.columns)
        kind = GeometryKind(layer.kind)
        entities = tuple(
            cprov.SourceEntity(int(fid), kind, parts,
                               {name: layer.values[name][index] for name, _ in fields})
            for index, (fid, parts) in enumerate(zip(layer.fids, layer.parts, strict=True)))
        return entities, fields
    fields = tuple(gstore.domain_fields(project, source))
    entities = tuple(cprov.SourceEntity(int(item.fid), GeometryKind.POLYGON, item.polygons,
                                        dict(item.attributes))
                     for item in gstore.load_domains(project, source))
    return entities, fields


def _columns(mapping: cprov.LayerMapping, fields: Sequence[tuple[str, str]],
             layer: str) -> dict[str, str]:
    """Campo elegido → su columna (por la columna o por su título)."""
    found: dict[str, str] = {}
    for wanted in mapping.fields():
        column = next((name for name, title in fields if wanted in (name, title)), None)
        if column is None:
            raise ConstraintError("core.constraint_source_field_unknown", field="campo",
                                  value=wanted, layer=layer,
                                  fields=", ".join(f"«{title}»" for _, title in fields) or "—")
        found[wanted] = column
    return found


def create_constraints(project: StoreProject, source: str, mapping: cprov.LayerMapping, *,
                       params: cprov.ParamDeclaration | None = None) -> Any:
    """Crea las restricciones de la capa ``source`` (RF-012-01) según ``mapping`` y con los
    parámetros ``params`` (RF-012-02), y devuelve lo que dejó ``core.edit_constraints``
    (``EditedConstraints``: su operación, las creadas y las rechazadas con su motivo).
    ``ConstraintError`` ``core.constraint_source_field_unknown`` si un campo elegido no está en
    la capa y ``core.constraint_source_nothing`` si no sirve ninguna entidad; los dos, antes de
    registrar nada."""
    entities, fields = source_entities(project, source)
    columns = _columns(mapping, fields, source)
    with project.read() as conn:
        record = dataset_registry.get(conn, source)
    source_input = None if record is None else record.input_uid
    return cprov.create_constraints(
        project, entities, mapping.with_fields(columns), layer=source, source=source,
        source_input=source_input, params=params, srs_id=int(project.record.crs_epsg))
