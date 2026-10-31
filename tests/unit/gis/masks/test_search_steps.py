# SPDX-License-Identifier: GPL-3.0-or-later
"""Buscar intocables en el proyecto por trozos, con lo mismo de siempre (spec 012, T37;
RF-012-08, RF-012-09, RNF-012-04 y RNF-012-06; plan 012 §5.2.3, A6).

La T37 hace que ``gis.masks.sectors.search_steps`` lea las capas «entidades» del proyecto **por
trozos de entidades y solo las de la caja del sector**, un paso por trozo, en vez de cargar las
diez capas enteras al llamar (la prueba de escala está en
``tests/rendimiento/gis/test_search_perf.py``) **sin cambiar ningún resultado**: aquí, lo que lo
fija de forma rápida, frente al cálculo de antes escrito en la propia prueba (cargar cada capa
con ``gis.store.load_features`` y buscar con ``gis.search.search``).

- **RF-012-08**: lo hallado (capa, número, distancia —bit a bit—, atributos y orden) es lo del
  cálculo de antes, en los dos sectores, en el perímetro como sector y con las capas en otro
  orden; la huella del sector, los hashes de las capas y la distancia, los de siempre.
- **RNF-012-06**: la llamada de la orden no lee ninguna entidad (sí rechaza lo que rechazaba:
  sector desconocido, capas de más o de menos, repetidas, que no son de entidades, que no
  existen o a las que falta su tabla); las entidades fuera de la caja del sector no se
  descodifican.
- **RF-012-09**: la capa de origen queda como estaba, Esc a mitad no deja nada y la búsqueda se
  cierra (``close_search``) como antes con lo hallado por trozos.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender
from tests.unit.core.constraints.test_operations import SECTORS, _last, _LayersCase, sector_layer

cmodel = import_geoblender("core.constraints.model")
cstore = import_geoblender("core.constraints.store")
cmessages = import_geoblender("core.constraints.messages")
sectors_mod = import_geoblender("gis.masks.sectors")
finder = import_geoblender("gis.search")
gstore = import_geoblender("gis.store")
vector = import_geoblender("gis.vector")
registry = import_geoblender("core.datasets.registry")
gmessages = import_geoblender("gis.messages")
gstore_masks = import_geoblender("gis.masks.store")

POINTS, LINES, ZONES = "gis_fea_intr_puntos", "gis_fea_intr_lineas", "gis_fea_intr_zonas"
LAYERS = (POINTS, LINES, ZONES)
COUNT = 120
BUDGET_S = 0.05
DISTANCE = fx.SEARCH_DISTANCE_M
NAME = vector.FieldColumn("nombre", "nombre", "TEXT")


def _random_layer(kind: str, rng: np.random.Generator) -> Any:
    """``COUNT`` entidades de la geometría ``kind`` repartidas al azar en el doble del sitio (la
    mitad, lejos de los sectores), en absolutas."""
    parts = []
    for _ in range(COUNT):
        x, y = rng.uniform(-150.0, 450.0), rng.uniform(-250.0, 370.0)
        if kind == "point":
            parts.append(((fx.absolute([(x, y)]),),))
        elif kind == "line":
            steps = np.cumsum(rng.normal(0.0, 12.0, (int(rng.integers(2, 8)), 2)), axis=0)
            parts.append(((fx.absolute(steps + (x, y)),),))
        else:
            w, h = rng.uniform(3.0, 40.0, 2)
            parts.append(((fx.absolute([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]),),))
    return vector.FeatureLayer(
        kind, tuple(range(1, COUNT + 1)), tuple(parts), (NAME,),
        {"nombre": tuple(f"{kind} {index}" for index in range(COUNT))})


def _key(item: Any) -> tuple[Any, ...]:
    return (item.layer, item.fid, float(item.distance_m).hex(), dict(item.attributes))


class _SearchCase(_LayersCase):
    """El proyecto de las restricciones con tres capas de 300 entidades al azar."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        rng = np.random.default_rng(370)
        for name, kind in zip(LAYERS, ("point", "line", "polygon"), strict=True):
            cls.write_layer(name, _random_layer(kind, rng))

    def search(self, code: str, layers: Any = LAYERS, **options: Any) -> Any:
        self.clock.advance(minutes=1)
        return _last(sectors_mod.search_steps(self.project, code, layers, budget_s=BUDGET_S,
                                              **options))

    def old_way(self, code: str, layers: Any = LAYERS) -> tuple[Any, ...]:
        """Cargar las capas enteras y buscar en memoria: el cálculo de antes de la T37."""
        with self.project.read() as conn:
            sector = next(item for item, _ in gstore_masks.search_sectors(conn, self.project, None)
                          if item.code == code)
        loaded = {name: gstore.load_features(self.project, name) for name in layers}
        return finder.search(sector.rings, loaded, DISTANCE)


class DeclaredSectorsTest(_SearchCase):
    """Los dos sectores declarados de ``gis_fea_sectores``."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_layer(SECTORS, sector_layer(dict(fx.SECTORS_LOCAL)))
        sectors_mod.declare_sectors(cls.project, SECTORS, fx.SECTOR_FIELD)

    def test_the_order_finds_what_loading_the_layers_whole_found(self) -> None:
        """RF-012-08: en cada sector, lo hallado es, bit a bit, lo del cálculo de antes (capas,
        números, distancias, atributos y orden); hay de las tres geometrías, y la huella del
        sector, los hashes de las capas y la distancia son los de siempre."""
        for code in ("sector_1", "sector_2"):
            with self.subTest(sector=code):
                searched = self.search(code)
                wanted = self.old_way(code)
                self.assertGreater(len(wanted), 30)
                self.assertEqual({item.layer for item in searched.found}, set(LAYERS))
                self.assertEqual([_key(item) for item in searched.found],
                                 [_key(item) for item in wanted])
                with self.project.read() as conn:
                    sector = next(item for item, _ in
                                  gstore_masks.search_sectors(conn, self.project, None)
                                  if item.code == code)
                    hashes = tuple(registry.get(conn, name).content_sha256 for name in LAYERS)
                self.assertEqual((searched.sector_code, searched.sector_sha256, searched.layers,
                                  searched.layer_sha256, searched.distance_m),
                                 (code, cstore.sector_sha256(sector), LAYERS, hashes, DISTANCE))

    def test_layers_in_another_order_and_one_layer(self) -> None:
        """Las entidades salen en el orden de las capas pedidas, y una capa sola da lo suyo."""
        reverse = LAYERS[::-1]
        searched = self.search("sector_1", reverse)
        self.assertEqual([_key(item) for item in searched.found],
                         [_key(item) for item in self.old_way("sector_1", reverse)])
        self.assertEqual([item.layer for item in searched.found][0], ZONES)
        only = self.search("sector_2", [LINES])
        self.assertEqual([_key(item) for item in only.found],
                         [_key(item) for item in self.old_way("sector_2", [LINES])])

    def test_the_call_reads_no_entity_and_the_ones_apart_are_not_decoded(self) -> None:
        """RNF-012-06: tras llamar a la orden no se ha descodificado ninguna entidad (todo está
        en los pasos); en el recorrido se descodifican las de la caja del sector, no todas."""
        with mock.patch.object(gstore, "decode_geometry", wraps=gstore.decode_geometry) as spy:
            steps = sectors_mod.search_steps(self.project, "sector_1", LAYERS, budget_s=BUDGET_S)
            self.assertEqual(spy.call_count, 0)
            searched = _last(steps)
            decoded = spy.call_count
        self.assertTrue(searched.found)
        self.assertLess(decoded, 3 * COUNT * 0.8)
        self.assertGreaterEqual(decoded, len(searched.found))

    def test_the_call_rejects_what_it_rejected(self) -> None:
        """Los rechazos salen al llamar, antes del primer paso: sector desconocido, capas de más
        o de menos o repetidas, un dato que no es de entidades y una capa que no existe o a la
        que falta la tabla."""
        def call(code: str = "sector_1", layers: Any = LAYERS) -> Any:
            return sectors_mod.search_steps(self.project, code, layers)

        with self.assertRaises(cmessages.ConstraintError) as caught:
            call("no_existe")
        self.assertEqual(caught.exception.code, "core.constraint_sector_unknown")
        for layers in ((), tuple(f"gis_fea_x{index}" for index in range(11))):
            with self.assertRaises(cmessages.ConstraintError) as caught:
                call(layers=layers)
            self.assertEqual(caught.exception.code, "core.constraint_search_layers")
        with self.assertRaises(ValueError):
            call(layers=[POINTS, POINTS])
        with self.assertRaises(ValueError):
            call(layers=["gis_dtm_otro"])
        with self.assertRaises(gmessages.GisError) as caught:
            call(layers=["gis_fea_no_existe"])
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")
        self.write_layer("gis_fea_intr_sin_tabla", _random_layer("point", np.random.default_rng(1)))
        with self.project.write_transaction() as conn:
            conn.execute('DROP TABLE "gis_fea_intr_sin_tabla"')
        with self.assertRaises(gmessages.GisError) as caught:
            call(layers=[POINTS, "gis_fea_intr_sin_tabla"])
        self.assertEqual(caught.exception.code, "gis.dataset_file_missing")

    def test_the_source_layers_are_not_touched_and_esc_leaves_nothing(self) -> None:
        """RF-012-09 y RF-012-28: las capas consultadas quedan como estaban (filas y hash
        registrado) y cerrar los pasos a mitad no deja ninguna operación ni dato nuevos."""
        def state() -> tuple[Any, ...]:
            with self.project.read() as conn:
                rows = [conn.execute(f'SELECT * FROM "{name}" ORDER BY fid').fetchall()
                        for name in LAYERS]
                hashes = [registry.get(conn, name).content_sha256 for name in LAYERS]
                counts = [conn.execute(f"SELECT count(*) FROM {table}").fetchone()
                          for table in ("gb_operation", "gb_dataset", "core_untouchable_search")]
            return rows, hashes, counts

        before = state()
        steps = sectors_mod.search_steps(self.project, "sector_2", LAYERS, budget_s=1e-9)
        for _ in range(3):  # un paso por trozo
            next(steps)
        steps.close()
        self.assertEqual(state(), before)
        self.search("sector_2")
        self.assertEqual(state(), before)

    def test_a_search_found_by_pieces_closes_as_before(self) -> None:
        """RF-012-09: lo hallado por trozos se cierra con ``close_search`` y queda registrado
        con las mismas entidades que el cálculo de antes."""
        searched = self.search("sector_2", [LINES])
        self.assertTrue(searched.found)
        decisions = [sectors_mod.Decision(item.layer, item.fid, cmodel.HitDecision.DISCARDED,
                                          "Prueba") for item in searched.found]
        self.clock.advance(minutes=1)
        record = sectors_mod.close_search(self.project, searched, decisions, closed_by="Samuel")
        rows = self.query("SELECT layer_dataset, feature_fid, distance_m FROM "
                          "core_untouchable_hit WHERE search_uid = ? ORDER BY rowid", record.uid)
        wanted = self.old_way("sector_2", [LINES])
        self.assertEqual(rows, [(item.layer, item.fid, item.distance_m) for item in wanted])


    def test_the_perimeter_gives_what_loading_the_layers_whole_gave(self) -> None:
        """RF-012-08 (D-26): sin capa de sectores, el perímetro de actuación es el único sector,
        y buscar en él da, bit a bit, lo del cálculo de antes. Al acabar se vuelven a declarar los
        dos sectores."""
        self.clock.advance(minutes=1)
        sectors_mod.declare_sectors(self.project, None, None)
        try:
            searched = self.search("")
            wanted = self.old_way("")
            self.assertGreater(len(wanted), 30)
            self.assertEqual([_key(item) for item in searched.found],
                             [_key(item) for item in wanted])
        finally:
            self.clock.advance(minutes=1)
            sectors_mod.declare_sectors(self.project, SECTORS, fx.SECTOR_FIELD)


class ScaleSearchDataTest(unittest.TestCase):
    """Los datos de escala de buscar de ``plan.md`` §2.2 (``tests/support/constraints_scale.py``)."""

    def test_the_data_of_the_plan_and_the_seed(self) -> None:
        """Diez capas (3 de puntos, 4 de líneas de 10 vértices y 3 de polígonos de 8 vértices) y
        un sector de 400 vértices que ocupa un cuarto de la ventana; las mismas, bit a bit, con
        la misma semilla."""
        from tests.support import constraints_scale as scale

        layers, sector = scale.build_search_layers(count=20)
        self.assertEqual(list(layers), [f"gis_fea_capa_{index}" for index in range(10)])
        self.assertEqual([found.kind for found in layers.values()],
                         ["point"] * 3 + ["line"] * 4 + ["polygon"] * 3)
        self.assertTrue(all(len(found) == 20 for found in layers.values()))
        sizes = {found.kind: {len(path) for feature in found.parts for part in feature
                              for path in part} for found in layers.values()}
        self.assertEqual(sizes, {"point": {1}, "line": {10}, "polygon": {9}})
        self.assertEqual(len(sector), scale.SEARCH_SECTOR_VERTICES + 1)
        self.assertTrue(np.array_equal(sector[0], sector[-1]))
        extent = np.ptp(sector, axis=0)
        self.assertTrue(0.4 * scale.COLS < extent[0] < 0.6 * scale.COLS)
        again, same_sector = scale.build_search_layers(count=20)
        np.testing.assert_array_equal(same_sector, sector)
        for name, found in layers.items():
            self.assertEqual(again[name].fids, found.fids)
            self.assertEqual(dict(again[name].values), dict(found.values))
            for mine, theirs in zip(found.parts, again[name].parts, strict=True):
                for a, b in zip(mine, theirs, strict=True):
                    for ring, other in zip(a, b, strict=True):
                        np.testing.assert_array_equal(ring, other)


if __name__ == "__main__":
    unittest.main()
