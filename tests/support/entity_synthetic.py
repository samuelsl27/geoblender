# SPDX-License-Identifier: GPL-3.0-or-later
"""Las entidades sintéticas de las pruebas de rendimiento de las entidades de diseño (spec 015, T33; plan 015 §7.3;
RNF-015-02 y RNF-015-06): sobre una entidad real, las que se apoyan en ella, con su operación y los datos de
juguete de su superficie y su huella, como la ``ScaleTest`` de T24 y lo que lee la vista previa de T29.

No importa el paquete: lo recibe como ``load`` (``tests.support.package.import_geoblender`` en las pruebas con el
Python de Blender, o el importador de la copia de la extensión habilitada dentro de Blender, donde no se puede
cargar otra copia: ``docs/trampas.md`` §4), para que lo usen las dos (``tests/support/entity_perf.py`` y
``tests/rendimiento/blender/perf_entities.py``). Solo escribe en el proyecto que se le da y en una transacción
por entidad.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any

__all__ = ["add_dependents"]

_BY = "Samuel (IMGA)"
BLOCK_CELLS = 6
"""El lado de la huella de juguete de cada entidad sintética (celdas)."""


def footprint(index: int) -> tuple[list[list[int]], list[int]]:
    """La huella de juguete de la entidad sintética número ``index`` (0, 1…): un bloque de :data:`BLOCK_CELLS`
    celdas de lado en un tablero de 15 columnas, como tramos de fila ``[fila, col0, col1]``, y su ventana
    ``[fila0, fila1, col0, col1]`` (de la rejilla entera, las segundas excluidas)."""
    column = 100 + 10 * (index % 15)
    row = 100 + 10 * (index // 15)
    runs = [[row + step, column, column + BLOCK_CELLS] for step in range(BLOCK_CELLS)]
    return runs, [row, row + BLOCK_CELLS, column, column + BLOCK_CELLS]


def add_dependents(project: Any, clock: Any, version: Any, load: Callable[[str], ModuleType], *,
                   base_code: str, first_number: int, last_number: int, start_before: str, layer: str,
                   terrain: str, axis_point: Sequence[float]) -> None:
    """Las entidades ``PLT-<first_number>`` a ``PLT-<last_number>`` de ``version`` (``Version`` editable) sobre la
    entidad real ``base_code`` (calculada): cada una con sus parámetros (``name``, ``E<n>``, y ``start``: la
    superficie de la anterior; la primera, la de ``start_before``, el código de la entidad de la que parte,
    de modo que forman una cadena), su operación ``des.platform`` (que consume la superficie de ``base_code``
    como ``supported_on`` y, la primera, además el dato ``terrain`` del que parte, como ``surface``, que
    consume antes), su cifra de lo apoyado (``des.supported_m3``) y los datos de juguete de su superficie y su
    huella (``des_psf_`` y ``des_epr_``, con una huella de :data:`BLOCK_CELLS` celdas de lado y ``axis_point``
    como único vértice de su eje, absoluto), con la ``layer`` de su geometría de origen. ``load`` importa los
    módulos del paquete (``"core.params"``…)."""
    core_params = load("core.params")
    operations = load("core.provenance.operations")
    datasets = load("core.datasets.model")
    builtin = load("core.content.builtin")
    gpkg_base = load("core.gpkg.base")
    versions_model = load("core.versions.model")
    design_params = load("design.params")
    design_store = load("design.store")
    entities = load("design.entities")
    provenance = load("design.provenance")
    registry = entities.registry(project, version.uid)
    base = registry.get(base_code)
    assert base is not None and base.operation_uid is not None, f"falta la entidad real {base_code}"
    base_surface = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, base.record.name)
    store = core_params.ParameterStore(project)
    keys: dict[int, list[str]] = {}
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        for number in range(first_number, last_number + 1):
            code = f"PLT-{number:03d}"
            before = entities.surface_ref(start_before if number == first_number else f"PLT-{number - 1:03d}")
            keys[number] = []
            for param, value in (("name", f"E{number}"), ("start", before)):
                keys[number].append(design_params.entity_key(code, param))
                store.create(conn, keys[number][-1], value, kind="ADOPTADO", source="Prueba de rendimiento",
                             source_kind="person", decided_by=_BY, reason="Prueba de la T33",
                             version=version.code)
    columns = ", ".join(f'"{column.name}"' for column in design_store.ENTITY_COLUMNS)
    marks = ", ".join("?" for _ in design_store.ENTITY_COLUMNS)
    for number in range(first_number, last_number + 1):
        name, code = f"E{number}", f"PLT-{number:03d}"
        inputs = [operations.Use(base_surface, "supported_on")]
        if number == first_number:
            inputs.insert(0, operations.Use(terrain, "surface"))
        clock.advance(seconds=1)
        handle = operations.begin_operation(
            project, provenance.PLATFORM, settings={"code": code, "name": name}, params=keys[number],
            inputs=inputs, executor="blender", version=version.uid)
        runs, window = footprint(number - first_number)
        surface = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, name)
        table = provenance.dataset_name(provenance.ENTITY_TABLE, name)
        surface_locator = versions_model.version_locator(surface, version.code)
        table_locator = versions_model.version_locator(table, version.code)
        row = (code, name, "platform", terrain, None, layer, number, "0" * 64, "cut", BLOCK_CELLS * BLOCK_CELLS,
               0, json.dumps(window), json.dumps(runs), json.dumps([list(axis_point)]))
        with project.write_transaction() as conn:
            gpkg_base.create_attribute_table(conn, surface_locator, [gpkg_base.ColumnDef("value", "DOUBLE")],
                                             surface, "Superficie de juguete de la prueba de rendimiento")
            conn.execute(f'INSERT INTO "{surface_locator}" (value) VALUES (?)', (float(number),))
            gpkg_base.create_attribute_table(conn, table_locator, list(design_store.ENTITY_COLUMNS), table,
                                             "Huella de juguete de la prueba de rendimiento")
            conn.execute(f'INSERT INTO "{table_locator}" ({columns}) VALUES ({marks})', row)
            handle.complete(
                conn, outputs=[
                    datasets.DatasetSpec(surface, "des", "table", datasets.Store.GPKG, surface_locator,
                                         reader=builtin.GPKG_LAYER.id, role=provenance.ENTITY_SURFACE_ROLE),
                    datasets.DatasetSpec(table, "des", "table", datasets.Store.GPKG, table_locator,
                                         reader=builtin.GPKG_LAYER.id, role=provenance.ENTITY_ROLE)],
                figures=provenance.supported_figures(name, {base_code: float(number)}))
