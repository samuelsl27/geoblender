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

Crear, completar y editar en QGIS (T14; HU-012-1, HU-012-2; plan 012 §5.2.2, D-4, D-5, D-22):

- **RF-012-01**: desde la capa sintética de polígonos (``gis_fea_restricciones_poligonos``, con
  los once tipos por su campo «tipo» y tres entidades malas) se crean once restricciones
  (``core.edit_constraints``, con la capa como entrada) con su geometría bit a bit, su origen
  (la entrada y la entidad) y su tipo, y se rechazan las tres malas con su entidad y su motivo
  (geometría vacía, tipo desconocido, campo vacío); la capa de origen queda igual (su hash y sus
  filas). Con un tipo para todas, las tres de puntos; un límite en líneas no se crea.
- **RF-012-02**: cada una con su código (único en las tres capas: «concesion_2»), nombre, tipo,
  motivo, decisor y fecha, y los parámetros que pide su tipo como filas ``create`` de la persona
  (su valor, su tipo, su decisor y su historial), en la misma transacción; los que no pide, no.
- **RF-012-03**: una fila escrita en las capas desde una conexión sin ``gb_writer()`` (QGIS) es
  una edición externa (``core.external_edit``: aviso, registro, nada bloqueado) que deja
  obsoletas las máscaras de V01 con su causa (el dato cambiado); completarla le da código y
  parámetros; cambiar un atributo no toca el código ni los parámetros, y el código no cambia.
- **RF-012-06 (CE-012-04)**: el perímetro redibujado en QGIS (+1,43 ha) deja obsoletas las
  máscaras con la causa y, al compilar, el área ganada de su polígono es 1,43 ha (≤ 10⁻⁹ ha).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import date
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
sources = import_geoblender("gis.masks.sources")
gstore_masks = import_geoblender("gis.masks.store")
external = import_geoblender("core.datasets.external")
stale = import_geoblender("core.provenance.stale")
graph = import_geoblender("core.provenance.graph")
wkb = import_geoblender("core.gpkg.wkb")

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
POLYGONS = "gis_fea_restricciones_poligonos"
POINTS = "gis_fea_restricciones_puntos"
CONSTRAINT_LINES = "gis_fea_restricciones_lineas"
DECLARED = cprov.ParamDeclaration(
    values={cmodel.ConstraintParam.BUFFER_OUT: 5.0, cmodel.ConstraintParam.BUFFER_IN: 10.0,
            cmodel.ConstraintParam.WEIGHT: 2.0, cmodel.ConstraintParam.ACTIVE: True},
    source="Informe de restricciones sintético", decided_by=PERSON,
    reason="Resguardos declarados al crear")
"""Lo que declara la persona en el diálogo al crear o completar (D-5: ningún valor por
defecto)."""
QGIS_AT = "2026-10-29T10:00:00.000Z"
"""El ``last_change`` que deja la edición en QGIS."""


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


class _LayersCase(cp.ConstraintsProjectCase):
    """La copia del proyecto de las restricciones con las operaciones de ``core`` de las
    restricciones, la de prueba de las capas (:data:`LAYERS_TYPE`), ``core.external_edit`` y la
    distancia de búsqueda registradas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        layers = contract.OperationDef(LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False)
        core_ops = [item for item in contract.CORE_OPERATIONS
                    if item.op_type not in contract.OPERATIONS]
        cls.enterClassContext(registered(layers, *cprov.OPERATIONS, *core_ops))
        if cparams.SEARCH_DISTANCE.key not in params.DEFINITIONS:
            kept = [item for item in params.DEFINITIONS.values() if item.module == "core"]
            params.register_definitions(cparams.DEFINITIONS)

            def restore() -> None:
                params.unregister_definitions("core")
                params.register_definitions(kept)

            cls.addClassCleanup(restore)

    # --- Ayudas -----------------------------------------------------------------------------

    @classmethod
    def write_layer(cls, name: str, layer: Any) -> None:
        """:data:`LAYERS_TYPE`: escribe (o vuelve a escribir) la capa ``name`` y la registra
        como dato del proyecto."""
        srs = cls.project.record.crs_epsg
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(cls.project, LAYERS_TYPE, settings={"name": name},
                                            executor="blender")
        rows = gstore.feature_rows(layer, srs)
        columns = [column.column for column in layer.columns]
        with cls.project.write_transaction() as conn:
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

    def io(self, operation_uid: str, direction: str) -> dict[str, tuple[str, str]]:
        """Papel → (nombre del dato, hash anotado) de lo que consume o produce una operación."""
        return {role: (name, sha) for role, name, sha in self.query(
            "SELECT io.role, d.name, io.content_sha256 FROM gb_operation_io AS io JOIN "
            "gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND "
            "io.direction = ?", operation_uid, direction)}


class SectorsAndSearchesTest(_LayersCase):
    """Sectores, búsquedas y su estado sobre la copia del proyecto de las restricciones."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_layer(SECTORS, sector_layer(dict(fx.SECTORS_LOCAL)))
        cls.write_layer(TOWERS, towers_layer())
        cls.write_layer(LINES, lines_layer())

    # --- Ayudas -----------------------------------------------------------------------------

    def states(self) -> dict[str, bool]:
        return {state.code: state.current for state in access.sector_states(self.project)}

    def search(self, code: str, layers: Sequence[str]) -> Any:
        self.clock.advance(minutes=1)
        return _last(sectors_mod.search_steps(self.project, code, layers, budget_s=BUDGET_S))

    def close(self, searched: Any, decisions: Sequence[Any]) -> Any:
        self.clock.advance(minutes=1)
        return sectors_mod.close_search(self.project, searched, decisions, closed_by=PERSON)

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


# --- Crear, completar y editar en QGIS (T14) ---------------------------------------------------


def constraints_layer(name: str, extra: Sequence[Any] = ()) -> Any:
    """La capa ``name`` de las fuentes sintéticas como capa de entidades (campos de
    ``CONSTRAINT_FIELDS``, como texto), con las entidades ``extra`` (``SourceFeature``)."""
    features = (*fx.source_features()[name], *extra)
    kind = {"POLYGON": "polygon", "LINESTRING": "line", "POINT": "point"}[
        fx.LAYER_SPECS[name][0]]
    parts: list[Any] = []
    for feature in features:
        coords = feature.coords
        if feature.geometry_type == "POLYGON":
            parts.append((tuple(coords),))
        elif feature.geometry_type == "LINESTRING":
            parts.append(((coords,),))
        else:
            parts.append(((np.asarray(coords, dtype=np.float64).reshape(1, 2),),))
    fields = [field for field, _ in fx.CONSTRAINT_FIELDS]
    return vector.FeatureLayer(
        kind, tuple(feature.fid for feature in features),
        tuple(tuple(tuple(np.asarray(ring, dtype=np.float64) for ring in part)
                    for part in item) for item in parts),
        tuple(vector.FieldColumn(field, field, "TEXT") for field in fields),
        {field: tuple(feature.attributes.get(field) for feature in features)
         for field in fields})


EMPTY = cprov.SourceEntity(12, cmodel.GeometryKind.POLYGON, (), {
    "tipo": "Intocable", "nombre": "Vacía", "motivo": "Sin geometría", "decisor": PERSON,
    "fecha": "2025-07-01"})
"""Una entidad sin geometría (``gis.store`` no guarda geometrías vacías: llega así de una
capa leída)."""
BAD_POLYGONS = (
    fx.SourceFeature(13, "POLYGON", (fx.rectangle(230.0, 160.0, 250.0, 180.0),),
                     {"tipo": "Cantera vieja", "nombre": "Hueco", "motivo": "?",
                      "decisor": PERSON, "fecha": "2025-07-01"}),
    fx.SourceFeature(14, "POLYGON", (fx.rectangle(250.0, 160.0, 270.0, 180.0),),
                     {"tipo": "  ", "nombre": "Sin tipo", "motivo": "?", "decisor": PERSON,
                      "fecha": "2025-07-01"}),
)
"""Las dos entidades malas de la capa de polígonos: tipo desconocido y campo del tipo vacío."""
BY_FIELDS = cprov.LayerMapping(type_field="tipo", name_field="nombre", reason_field="motivo",
                               decider_field="decisor", date_field="fecha")


class CreateFromLayerTest(_LayersCase):
    """RF-012-01, RF-012-02: crear restricciones desde las capas sintéticas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_layer(POLYGONS, constraints_layer(fx.LAYER_POLYGONS, BAD_POLYGONS))
        cls.write_layer(POINTS, constraints_layer(fx.LAYER_POINTS))
        cls.write_layer(CONSTRAINT_LINES, constraints_layer(fx.LAYER_LINES))

    def assertParams(self, row: Any) -> None:  # noqa: N802
        """Los parámetros de ``row``: los que pide su tipo, como fila ``create`` de la persona
        con el valor declarado; los demás, ninguno."""
        store = params.ParameterStore(self.project)
        for param in cmodel.ConstraintParam:
            key = cparams.param_key(row.code, param)
            if param not in row.ctype.requires:
                self.assertIsNone(store.get(key), key)
                continue
            self.assertEqual(store.get(key).value, DECLARED.values[param], key)
            (entry,) = store.history(key)
            self.assertEqual((str(entry.action), str(entry.kind), entry.decided_by,
                              entry.source, entry.reason, entry.unconfirmed),
                             ("create", cparams.family(param).template.kind, PERSON,
                              DECLARED.source, DECLARED.reason, False), key)

    def test_create_from_a_layer_by_its_type_field(self) -> None:
        """RF-012-01, RF-012-02: once creadas con su geometría bit a bit, su origen, su tipo,
        su código y sus parámetros; tres rechazadas con su entidad y su motivo; la capa de
        origen, igual."""
        before = self.record(POLYGONS)
        rows_before = self.query(f'SELECT * FROM "{POLYGONS}" ORDER BY fid')
        existing = {item.uid for item in self.stored_constraints()}
        self.clock.advance(minutes=1)
        edited = sources.create_constraints(self.project, POLYGONS, BY_FIELDS, params=DECLARED)

        # Las rechazadas, con su entidad y su motivo; una sin geometría, también.
        self.assertEqual([(item.fid, item.problem, item.field) for item in edited.rejected],
                         [(13, "type_unknown", "tipo"), (14, "field_empty", "tipo")])
        texts = [item.text() for item in edited.rejected]
        self.assertIn(f"entidad 13 de «{POLYGONS}»", texts[0])
        self.assertIn("«Cantera vieja»", texts[0])
        self.assertIn("«tipo» está vacío", texts[1])
        rows, (empty,) = cprov.constraints_from_entities(
            [EMPTY], BY_FIELDS, layer=POLYGONS, source_input=None)
        self.assertEqual((rows, empty.fid, empty.problem), ((), 12, "no_geometry"))
        self.assertIn("su geometría está vacía", empty.text())

        # Las creadas (RF-012-01, RF-012-02).
        created = [item for item in self.stored_constraints() if item.uid not in existing]
        self.assertEqual([item.uid for item in edited.constraints],
                         [item.uid for item in created])
        source = {feature.fid: feature for feature in fx.source_features()[fx.LAYER_POLYGONS]}
        layer = gstore.load_features(self.project, POLYGONS)
        parts = dict(zip(layer.fids, layer.parts, strict=True))
        self.assertEqual([item.source_fid for item in created], list(range(1, 12)))
        types = {label: ctype for ctype, label in fx.CONSTRAINT_TYPES.items()}
        for row in created:
            attributes = source[row.source_fid].attributes
            self.assertEqual((row.name, row.ctype.value, row.reason, row.decided_by,
                              row.decided_on.isoformat(), row.kind.value, row.source_input,
                              row.layer),
                             (attributes["nombre"], types[attributes["tipo"]],
                              attributes["motivo"], attributes["decisor"], attributes["fecha"],
                              "polygon", before.input_uid, cstore.layer_of("polygon")))
            self.assertTrue(cp.same_parts(row.parts, parts[row.source_fid]), row.name)
            self.assertTrue(cmodel.is_code(row.code))
            self.assertParams(row)
        codes = {row.name: row.code for row in created}
        self.assertEqual((codes["Concesión"], codes["Perímetro"], codes["Balsa"],
                          codes["Cementerio"], codes["Borde de camino"]),
                         ("concesion_2", "perimetro_2", "balsa_2", "cementerio",
                          "borde_de_camino"))
        everything = [row.code for row in self.stored_constraints()]
        self.assertEqual(len(everything), len(set(everything)))

        # La operación: la capa como entrada con su hash; la capa de polígonos, su salida.
        (op_type, settings), = self.query(
            "SELECT op_type, settings FROM gb_operation WHERE uid = ?", edited.operation_uid)
        self.assertEqual(op_type, cprov.EDIT_CONSTRAINTS)
        self.assertEqual(self.io(edited.operation_uid, "in"),
                         {cprov.SOURCE_ROLE: (POLYGONS, before.content_sha256)})
        self.assertEqual({name for name, _ in self.io(edited.operation_uid, "out").values()},
                         {cstore.layer_of("polygon")})
        self.assertIn('"created":11', settings.replace(" ", ""))
        self.assertIn("type_unknown", settings)

        # La capa de origen no cambia (RF-012-01, D-17).
        after = self.record(POLYGONS)
        self.assertEqual((after.uid, after.content_sha256), (before.uid, before.content_sha256))
        self.assertEqual(self.query(f'SELECT * FROM "{POLYGONS}" ORDER BY fid'), rows_before)

    def test_one_type_for_all_and_layers_that_give_nothing(self) -> None:
        """RF-012-01: con un tipo para todas y el motivo y el decisor fijos, las tres de
        puntos; un límite en líneas, ninguna (rechazadas por su geometría, sin registrar nada);
        un campo que no existe, rechazado al llamar."""
        self.clock.advance(minutes=1)
        mapping = cprov.LayerMapping(ctype=cmodel.ConstraintType.UNTOUCHABLE, name_field="nombre",
                                     reason="Inventario de pozos y vértices",
                                     decided_by=PERSON)
        edited = sources.create_constraints(self.project, POINTS, mapping, params=DECLARED)
        self.assertEqual(edited.rejected, ())
        rows = edited.constraints
        self.assertEqual([(row.name, row.ctype, row.kind.value, row.reason, row.decided_by,
                           row.decided_on, row.source_fid) for row in rows],
                         [(name, cmodel.ConstraintType.UNTOUCHABLE, "point",
                           "Inventario de pozos y vértices", PERSON, None, fid)
                          for fid, name in ((1, "Pozo"), (2, "Árbol singular"),
                                            (3, "Vértice geodésico"))])
        for row in rows:
            self.assertParams(row)
        count = self.query("SELECT count(*) FROM gb_operation")
        limit = cprov.LayerMapping(ctype=cmodel.ConstraintType.LEGAL_LIMIT, name_field="nombre",
                                   reason="Concesión", decided_by=PERSON)
        with self.assertRaises(cmessages.ConstraintError) as caught:
            sources.create_constraints(self.project, CONSTRAINT_LINES, limit, params=DECLARED)
        self.assertEqual(caught.exception.code, "core.constraint_source_nothing")
        self.assertIn("Límite legal", str(caught.exception))
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), count)
        with self.assertRaises(cmessages.ConstraintError) as caught:
            sources.create_constraints(self.project, POINTS, cprov.LayerMapping(
                type_field="no_existe", reason="x", decided_by=PERSON))
        self.assertEqual(caught.exception.code, "core.constraint_source_field_unknown")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), count)


class EditOutsideTest(_LayersCase):
    """RF-012-03, RF-012-06 (CE-012-04): editar las capas en QGIS, completar y compilar."""

    def qgis(self, sql: str, args: tuple[Any, ...], table: str) -> None:
        """QGIS escribe en ``table`` desde su propia conexión (sin ``gb_writer()``)."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(sql, args)
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         (QGIS_AT, table))
        finally:
            conn.close()

    def test_edited_in_qgis_completed_and_compiled(self) -> None:
        """RF-012-03, RF-012-06, CE-012-04 (véase el módulo)."""
        polygons = cstore.layer_of("polygon")
        srs = self.project.record.crs_epsg
        masks = _last(access.ensure_masks_steps(self.project, self.v1.uid, budget_s=BUDGET_S))
        self.assertEqual(masks.state, access.MaskState.CURRENT)
        before = self.record(polygons)

        # QGIS redibuja el perímetro (+1,43 ha) y dibuja una charca sin rellenar nada más.
        redrawn = wkb.encode_geometry("MULTIPOLYGON", [[fx.absolute(
            fx.REDRAWN_PERIMETER_LOCAL)]], srs, False)
        self.qgis(f"UPDATE {polygons} SET geom = ? WHERE code = 'perimetro'", (redrawn,),
                  polygons)
        pond = wkb.encode_geometry("MULTIPOLYGON", [[fx.rectangle(200.0, 160.0, 230.0, 190.0)]],
                                   srs, False)
        self.qgis(f"INSERT INTO {polygons} (geom, name) VALUES (?, 'Charca')", (pond,),
                  polygons)

        # Una edición externa: aviso, registro y nada bloqueado (RF-012-03, RF-008-21).
        self.clock.advance(minutes=1)
        outcome = _last(external.external_check_steps(self.project))
        (finding,) = [item for item in outcome.findings if item.record.name == polygons]
        self.assertEqual((finding.verdict, finding.status),
                         (external.DatasetVerdict.EDITED, datasets.DatasetStatus.CURRENT))
        self.assertTrue(outcome.texts())
        (edit_type,), = self.query("SELECT op_type FROM gb_operation WHERE uid = ?",
                                   finding.operation_uid)
        self.assertEqual(edit_type, contract.EXTERNAL_EDIT)
        after = self.record(polygons)
        self.assertNotEqual(after.content_sha256, before.content_sha256)
        self.assertEqual(after.status, datasets.DatasetStatus.CURRENT)

        # Las máscaras de V01, obsoletas con su causa: el dato cambiado (CE-012-04).
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0],
                         access.MaskState.STALE)
        with self.project.read() as conn:
            causes = stale.item_causes(conn, "operation", masks.operation_uid)
        self.assertIn(graph.Cause(graph.CauseKind.DATASET_CHANGED, before.uid), causes)

        # La charca, incompleta: completarla le da código y parámetros (RF-012-03, D-22).
        (charca,) = [item for item in self.stored_constraints() if item.name == "Charca"]
        self.assertEqual((charca.code, charca.ctype, charca.source_input), ("", None, None))
        self.clock.advance(minutes=1)
        completed = cprov.edit_constraints(self.project, [replace(
            charca, ctype=cmodel.ConstraintType.NO_FILL, reason="Charca temporal",
            decided_by=PERSON, decided_on=date(2026, 10, 29))], params=DECLARED, srs_id=srs)
        (row,) = completed.constraints
        self.assertEqual((row.uid, row.fid, row.code), (charca.uid, charca.fid, "charca"))
        (stored,) = [item for item in self.stored_constraints() if item.uid == charca.uid]
        self.assertEqual((stored.code, stored.ctype, stored.reason),
                         ("charca", cmodel.ConstraintType.NO_FILL, "Charca temporal"))
        store = params.ParameterStore(self.project)
        self.assertEqual(store.get(cparams.buffer_out_key("charca")).value, 5.0)
        self.assertIs(store.get(cparams.active_key("charca")).value, True)
        self.assertIsNone(store.get(cparams.weight_key("charca")))

        # Cambiar un atributo no toca el código ni los parámetros; el código no cambia.
        (pond_row,) = [item for item in self.stored_constraints() if item.code == "balsa"]
        history = store.history(cparams.buffer_out_key("balsa"))
        self.clock.advance(minutes=1)
        cprov.edit_constraints(self.project, [replace(pond_row, reason="Balsa en desuso")],
                               params=DECLARED, srs_id=srs)
        (pond_now,) = [item for item in self.stored_constraints() if item.uid == pond_row.uid]
        self.assertEqual((pond_now.code, pond_now.reason), ("balsa", "Balsa en desuso"))
        self.assertEqual(store.history(cparams.buffer_out_key("balsa")), history)
        with self.assertRaises(cmessages.ConstraintError) as caught:
            cprov.edit_constraints(self.project, [replace(pond_now, code="otra")],
                                   srs_id=srs)
        self.assertEqual(caught.exception.code, "core.constraint_code_immutable")

        # Al compilar, el polígono del perímetro ganó 1,43 ha (CE-012-04, A5).
        self.clock.advance(minutes=1)
        masks = _last(access.ensure_masks_steps(self.project, self.v1.uid, budget_s=BUDGET_S))
        self.assertEqual(masks.state, access.MaskState.CURRENT)
        record = self.record("gis_mskr", self.v1)
        with self.project.read() as conn:
            report = gstore_masks.read_report(conn, record.locator)
        values = {(item[0], item[1]): item[2] for item in report}
        gained_ha = values[("perimetro", "polygon_gained")] / 10_000.0
        self.assertLessEqual(abs(gained_ha - 1.43), 1e-9)
        self.assertEqual(values[("perimetro", "polygon_lost")], 0.0)


if __name__ == "__main__":
    import unittest

    unittest.main()
