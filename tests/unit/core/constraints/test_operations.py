# SPDX-License-Identifier: GPL-3.0-or-later
"""Las operaciones de las restricciones en el proyecto (spec 012; plan 012 §5.2.3, A12, D-3,
D-26): sectores y búsquedas registradas (T13; HU-012-3; RF-012-07, RF-012-08, RF-012-09,
RF-012-10).

Sobre el proyecto de ``tests.support.constraints_project`` (una copia por clase), con capas
«entidades» del proyecto (``gis_fea_``) escritas por una operación de prueba de ``gis``
(:data:`LAYERS_TYPE`, que hace lo que la importación de la 006 con el papel «entidades»):

- ``gis_fea_sectores``: los dos sectores de ``SECTORS_LOCAL`` con el campo «sector»;
- ``gis_fea_torres``: la torre (6 m del sector 2, 96 m del sector 1);
- ``gis_fea_lineas``: la línea eléctrica (15 m del sector 1, 33,54 m del sector 2).

- **RF-012-07**: declarar los sectores de una capa de polígonos y su campo los guarda
  (``core.declare_sectors``, con la capa como entrada) e informa del área del perímetro que no
  cubre ningún sector (12 000 m²; 12 600 m² con el sector 2 desplazado, que sale 600 m² del
  perímetro); una capa con solapes, polígonos no válidos o nombres vacíos se rechaza con la lista
  de RF-011-08 (entidad, nombre, problema y el área del solape) sin escribir nada; sin capa, el
  perímetro es el único sector.
- **RF-012-08**: la búsqueda da cada entidad a ≤ 25 m con su capa, sus atributos y su distancia.
- **RF-012-09**: cerrar una búsqueda registra el sector y su huella, las capas con su hash (las
  entradas de ``core.find_untouchables``), lo hallado, lo convertido y lo descartado con su
  motivo, quién y cuándo; no se cierra con algo sin decidir. Queda **pendiente** al cambiar una
  capa consultada (otro hash) o el sector (otra huella), y sigue vigente al cerrar otra.
- **RF-012-10**: el estado de cada sector, al vuelo, y la marca de las máscaras de un sector
  pendiente.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

cprov = import_geoblender("core.constraints.provenance")
cstore = import_geoblender("core.constraints.store")
cmodel = import_geoblender("core.constraints.model")
cparams = import_geoblender("core.constraints.params")
cmessages = import_geoblender("core.constraints.messages")
sectors_mod = import_geoblender("gis.masks.sectors")
access = import_geoblender("gis.masks.access")
gstore = import_geoblender("gis.store")
vector = import_geoblender("gis.vector")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
params = import_geoblender("core.params")
registry = import_geoblender("core.datasets.registry")
datasets = import_geoblender("core.datasets")
builtin = import_geoblender("core.content.builtin")
i18n = import_geoblender("core.i18n")

LAYERS_TYPE = "gis.test_layers"
"""La operación de prueba de ``gis`` que escribe las capas «entidades»."""
SECTORS = "gis_fea_sectores"
TOWERS = "gis_fea_torres"
LINES = "gis_fea_lineas"
PERSON = "Samuel (IMGA)"
BUDGET_S = 0.05
SECTOR_NAMES = tuple(fx.SECTORS_LOCAL)
SHIFTED_SECTOR_2 = (120.0, 20.0, 190.0, 180.0)
"""El sector 2 desplazado 10 m al este: 10 × 30 m fuera del perímetro arriba y abajo."""


def _layer(kind: str, items: Sequence[tuple[int, str, Any]], field: str = "nombre") -> Any:
    """Una capa de entidades ``kind`` con un campo de texto ``field``: ``items`` = (número,
    valor, partes absolutas: de cada parte, sus anillos / su camino / su punto (1, 2))."""
    column = vector.FieldColumn(field, field, "TEXT")
    return vector.FeatureLayer(
        kind, tuple(fid for fid, _, _ in items),
        tuple(tuple(tuple(np.asarray(ring, dtype=np.float64) for ring in part)
                    for part in parts) for _, _, parts in items),
        (column,), {field: tuple(value for _, value, _ in items)})


def sector_layer(boxes: dict[str, tuple[float, float, float, float]]) -> Any:
    return _layer("polygon", [(fid, name, ((fx.rectangle(*box),),))
                              for fid, (name, box) in enumerate(boxes.items(), start=1)],
                  fx.SECTOR_FIELD)


def towers_layer() -> Any:
    return _layer("point", [(1, "Torre 14", ((fx.absolute([fx.TOWER_LOCAL]),),))])


def lines_layer(local: Sequence[Sequence[float]] = fx.POWER_LINE_LOCAL) -> Any:
    return _layer("line", [(2, "Línea de 20 kV", ((fx.absolute(local),),))])


def _last(steps: Iterator[Any]) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


class SectorsAndSearchesTest(cp.ConstraintsProjectCase):
    """Sectores, búsquedas y su estado sobre la copia del proyecto de las restricciones."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        layers = contract.OperationDef(LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False)
        cls.enterClassContext(registered(layers, *cprov.OPERATIONS))
        if cparams.SEARCH_DISTANCE.key not in params.DEFINITIONS:
            kept = [item for item in params.DEFINITIONS.values() if item.module == "core"]
            params.register_definitions(cparams.DEFINITIONS)

            def restore() -> None:
                params.unregister_definitions("core")
                params.register_definitions(kept)

            cls.addClassCleanup(restore)
        test = cls("test_sector_and_search_cycle")
        test.write_layer(SECTORS, sector_layer(dict(fx.SECTORS_LOCAL)))
        test.write_layer(TOWERS, towers_layer())
        test.write_layer(LINES, lines_layer())

    # --- Ayudas -----------------------------------------------------------------------------

    def write_layer(self, name: str, layer: Any) -> None:
        """:data:`LAYERS_TYPE`: escribe (o vuelve a escribir) la capa ``name`` y la registra
        como dato del proyecto."""
        srs = self.project.record.crs_epsg
        self.clock.advance(minutes=1)
        handle = operations.begin_operation(self.project, LAYERS_TYPE, settings={"name": name},
                                            executor="blender")
        rows = gstore.feature_rows(layer, srs)
        columns = [column.column for column in layer.columns]
        with self.project.write_transaction() as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone():
                conn.execute(f'DELETE FROM "{name}"')
            else:
                extra = "".join(f', "{column}" TEXT' for column in columns)
                conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                             f'geom {layer.geometry_type}{extra})')
                conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                             "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                             (name, name, srs))
                conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                             "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                             (name, layer.geometry_type, srs))
            marks = ", ".join("?" for _ in range(len(columns) + 2))
            names = "".join(f', "{column}"' for column in columns)
            conn.executemany(f'INSERT INTO "{name}" (fid, geom{names}) VALUES ({marks})', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id,
                role="features", crs_epsg=srs),), message="Capa de prueba")

    def states(self) -> dict[str, bool]:
        return {state.code: state.current for state in access.sector_states(self.project)}

    def search(self, code: str, layers: Sequence[str]) -> Any:
        self.clock.advance(minutes=1)
        return _last(sectors_mod.search_steps(self.project, code, layers, budget_s=BUDGET_S))

    def close(self, searched: Any, decisions: Sequence[Any]) -> Any:
        self.clock.advance(minutes=1)
        return sectors_mod.close_search(self.project, searched, decisions, closed_by=PERSON)

    def io(self, operation_uid: str, direction: str) -> dict[str, tuple[str, str]]:
        """Papel → (nombre del dato, hash anotado) de lo que consume o produce una operación."""
        return {role: (name, sha) for role, name, sha in self.query(
            "SELECT io.role, d.name, io.content_sha256 FROM gb_operation_io AS io JOIN "
            "gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND "
            "io.direction = ?", operation_uid, direction)}

    # --- Pruebas ----------------------------------------------------------------------------

    def test_invalid_sector_layer_is_rejected(self) -> None:
        """RF-012-07 (con la lista de RF-011-08): una capa de sectores con un solape, un
        polígono que se corta a sí mismo y un nombre vacío se rechaza listando cada entidad, su
        nombre, el problema y el área del solape (m²), sin registrar nada."""
        bowtie = fx.absolute([(200.0, 20.0), (240.0, 60.0), (240.0, 20.0), (200.0, 60.0),
                              (200.0, 20.0)])
        bad = _layer("polygon", [
            (1, "Norte", ((fx.rectangle(20.0, 20.0, 90.0, 180.0),),)),
            (2, "Sur", ((fx.rectangle(80.0, 20.0, 150.0, 180.0),),)),
            (3, "Lazo", ((bowtie,),)),
            (4, "  ", ((fx.rectangle(150.0, 60.0, 170.0, 80.0),),)),
        ], fx.SECTOR_FIELD)
        self.write_layer("gis_fea_malos", bad)
        before = self.query("SELECT count(*) FROM gb_operation")
        stored = self.query("SELECT uid FROM core_sector ORDER BY fid")
        with self.assertRaises(sectors_mod.SectorsError) as caught:
            sectors_mod.declare_sectors(self.project, "gis_fea_malos", fx.SECTOR_FIELD)
        error = caught.exception
        self.assertEqual(error.code, "core.constraint_sectors_invalid")
        found = {(item.problem, item.fid, item.name, item.other_fid) for item in error.problems}
        self.assertEqual(found, {
            ("self_intersecting", 3, "Lazo", None), ("name_empty", 4, "  ", None),
            ("overlap", 1, "Norte", 2)})
        (overlap,) = [item for item in error.problems if item.problem == "overlap"]
        self.assertAlmostEqual(overlap.area_m2, 10.0 * 160.0, places=6)
        self.assertIn(f"{i18n.format_number(1600.0, 2)} m²", str(error))
        self.assertIn("«Lazo»", str(error))
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), before)
        self.assertEqual(self.query("SELECT uid FROM core_sector ORDER BY fid"), stored)
        with self.assertRaises(cmessages.ConstraintError) as caught:
            sectors_mod.declare_sectors(self.project, TOWERS, "nombre")
        self.assertEqual(caught.exception.code, "core.constraint_sectors_not_polygons")
        with self.assertRaises(cmessages.ConstraintError) as caught:
            sectors_mod.declare_sectors(self.project, SECTORS, "no_existe")
        self.assertEqual(caught.exception.code, "core.constraint_sectors_field_unknown")

    def test_sector_and_search_cycle(self) -> None:
        """RF-012-07, RF-012-08, RF-012-09, RF-012-10: declarar, buscar, cerrar, quedar
        pendiente por la huella del sector o el hash de una capa, y el perímetro sin capa."""
        # Declarar desde la capa (RF-012-07).
        declared = sectors_mod.declare_sectors(self.project, SECTORS, fx.SECTOR_FIELD)
        self.assertEqual([(s.code, s.name) for s in declared.sectors],
                         [("sector_1", "Sector 1"), ("sector_2", "Sector 2")])
        self.assertAlmostEqual(declared.uncovered_m2, fx.SECTORS_UNCOVERED_M2, places=6)
        with self.project.read() as conn:
            stored = cstore.read_sectors(conn)
        self.assertEqual([(s.code, s.name) for s in stored],
                         [("sector_1", "Sector 1"), ("sector_2", "Sector 2")])
        for sector, box in zip(stored, fx.SECTORS_LOCAL.values(), strict=True):
            self.assertEqual(cstore.sector_sha256(sector),
                             cstore.sector_sha256(cmodel.Sector("", "", "",
                                                                (fx.rectangle(*box),))))
        (op_type, settings), = self.query(
            "SELECT op_type, settings FROM gb_operation WHERE uid = ?", declared.operation_uid)
        self.assertEqual(op_type, cprov.DECLARE_SECTORS)
        self.assertIn('"field":"sector"', settings.replace(" ", ""))
        self.assertEqual(set(self.io(declared.operation_uid, "in")), {cprov.SOURCE_ROLE})
        self.assertEqual(self.io(declared.operation_uid, "in")[cprov.SOURCE_ROLE][0], SECTORS)
        self.assertIn(cstore.SECTOR_TABLE, {name for name, _ in
                                            self.io(declared.operation_uid, "out").values()})
        self.assertEqual(self.states(), {"sector_1": False, "sector_2": False})

        # Buscar en el sector 2 (RF-012-08): la torre a 6 m; la línea, a 33,54 m, no.
        searched = self.search("sector_2", [TOWERS, LINES])
        self.assertEqual(searched.distance_m, fx.SEARCH_DISTANCE_M)
        (tower,) = searched.found
        self.assertEqual((tower.layer, tower.fid), (TOWERS, 1))
        self.assertAlmostEqual(tower.distance_m, fx.TOWER_TO_SECTOR_M["Sector 2"], places=9)
        self.assertEqual(dict(tower.attributes), {"nombre": "Torre 14"})
        record = self.close(searched, [sectors_mod.Decision(
            TOWERS, 1, cmodel.HitDecision.CONVERTED, "Torre de alta tensión", "torre")])

        # Lo registrado (RF-012-09).
        (row,) = self.query("SELECT uid, operation_uid, sector_code, sector_sha256, distance_m, "
                            "closed_by, closed_at FROM core_untouchable_search")
        (started,) = self.query("SELECT started_at FROM gb_operation WHERE uid = ?",
                                record.operation_uid)
        self.assertEqual(row, (record.uid, record.operation_uid, "sector_2",
                               cstore.sector_sha256(stored[1]), fx.SEARCH_DISTANCE_M, PERSON,
                               started[0]))
        self.assertEqual(self.query(
            "SELECT layer_dataset, feature_fid, distance_m, attributes, decision, reason, "
            "constraint_code FROM core_untouchable_hit WHERE search_uid = ?", record.uid),
            [(TOWERS, 1, tower.distance_m, '{"nombre":"Torre 14"}', "converted",
              "Torre de alta tensión", "torre")])
        inputs = self.io(record.operation_uid, "in")
        self.assertEqual({role: name for role, (name, _) in inputs.items()},
                         {cprov.SECTOR_ROLE: cstore.SECTOR_TABLE, "layer_1": TOWERS,
                          "layer_2": LINES})
        with self.project.read() as conn:
            for role, (name, sha) in inputs.items():
                self.assertEqual(sha, registry.get(conn, name).content_sha256, role)
        self.assertEqual(self.query("SELECT key, value FROM gb_operation_param WHERE "
                                    "operation_uid = ?", record.operation_uid),
                         [(cparams.SEARCH_DISTANCE.key, "25.0")])
        self.assertEqual(self.states(), {"sector_1": False, "sector_2": True})

        # Las máscaras con un sector pendiente, marcadas (RF-012-10).
        masks = _last(access.ensure_masks_steps(self.project, self.v1.uid, budget_s=BUDGET_S))
        self.assertEqual((masks.pending_sectors, masks.pending_names),
                         (("sector_1",), SECTOR_NAMES[:1]))

        # El sector 1: la línea a 15 m; no se cierra sin decidir (RF-012-09).
        searched = self.search("sector_1", [TOWERS, LINES])
        (line,) = searched.found
        self.assertEqual((line.layer, line.fid), (LINES, 2))
        self.assertAlmostEqual(line.distance_m, fx.POWER_LINE_TO_SECTOR_M["Sector 1"], places=9)
        count = self.query("SELECT count(*) FROM gb_operation")
        with self.assertRaises(cmessages.ConstraintError) as caught:
            self.close(searched, [])
        self.assertEqual(caught.exception.code, "core.constraint_search_undecided")
        self.assertIn("Línea de 20 kV", str(caught.exception))
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), count)
        self.close(searched, [sectors_mod.Decision(LINES, 2, cmodel.HitDecision.DISCARDED,
                                                   "Línea fuera de servicio")])
        # Cerrar otra no deja pendiente la anterior.
        self.assertEqual(self.states(), {"sector_1": True, "sector_2": True})
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[1], ())

        # Otra huella del sector 2: pendiente; el sector 1 sigue vigente (A12).
        self.write_layer(SECTORS, sector_layer({"Sector 1": fx.SECTORS_LOCAL["Sector 1"],
                                                "Sector 2": SHIFTED_SECTOR_2}))
        declared = sectors_mod.declare_sectors(self.project, SECTORS, fx.SECTOR_FIELD)
        self.assertAlmostEqual(declared.uncovered_m2, fx.SECTORS_UNCOVERED_M2 + 600.0, places=6)
        self.assertEqual(self.query("SELECT count(*) FROM core_sector"), [(2,)])
        self.assertEqual(self.states(), {"sector_1": True, "sector_2": False})

        # Otro hash de una capa consultada: pendiente.
        self.write_layer(LINES, lines_layer(((-40.0, 230.0), (80.0, 230.0))))
        self.assertEqual(self.states(), {"sector_1": False, "sector_2": False})
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[1],
                         ("sector_1", "sector_2"))

        # Sin capa, el perímetro es el único sector (D-26).
        declared = sectors_mod.declare_sectors(self.project, None, None)
        self.assertEqual((declared.sectors, declared.uncovered_m2), ((), None))
        self.assertEqual(self.query("SELECT count(*) FROM core_sector"), [(0,)])
        (state,) = access.sector_states(self.project)
        self.assertEqual((state.code, state.name, state.current),
                         ("", "el perímetro de actuación", False))
        searched = self.search("", [TOWERS])
        (inside,) = searched.found
        self.assertEqual(inside.distance_m, 0.0)
        record = self.close(searched, [sectors_mod.Decision(
            TOWERS, 1, cmodel.HitDecision.DISCARDED, "Ya es una restricción")])
        self.assertEqual(self.io(record.operation_uid, "in")[cprov.SECTOR_ROLE][0],
                         cstore.layer_of(cmodel.GeometryKind.POLYGON))
        self.assertEqual(self.states(), {"": True})
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[1], ())


if __name__ == "__main__":
    import unittest

    unittest.main()
