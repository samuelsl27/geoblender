# SPDX-License-Identifier: GPL-3.0-or-later
"""La orden del cuerpo apoyado, su almacén: leer los datos, preparar, calcular, crear, recalcular y reproducir (spec 016, T25;
HU-016-4; RF-016-01, RF-016-20 a RF-016-22, RF-015-02, RF-015-03, RF-015-29, RF-009-11, RNF-016-05 y 07; plan 016 §5.2.3, §5.3.2,
§5.4 A11 y §5.7 P-12; CE-016-05 con proyecto). Es el patrón que sigue la T27 (el contrafuerte): ``design.supported_store`` hace, para
el cuerpo, lo que hizo para la retirada (T20).

- **Los datos de espesor** (:class:`ThicknessDataReaderTest`, sin proyecto): el campo de los puntos y de los polígonos de una capa de
  entidades, la Z de las líneas 3D (con las de la cantera, ``lines_z``) y la M declarada de los vértices (``lines_m``, que el
  proyecto no guarda: ``des.body_data_m``), un espesor negativo, que falta o que no es un número rechazado con capa, entidad, campo y
  valor, y el mismo camino sobre una tabla congelada (sqlite) con el WKB real.
- **La orden** (:class:`BodyOperationTest`, con proyecto, **en orden**: cada ``test_x`` parte de lo que dejó la anterior): la
  cantera de 2 m con la ladera y las tres secciones (CE-016-05). «Calcular» no escribe nada ni deja un temporal tras descartarlo;
  los rechazos, sin escribir; «Crear» es **una** transacción (un fallo no deja nada y ninguna entrada se modifica); «bajo un techo» deja
  la base y el espesor dispersos y no cambia la superficie; «sobre una base» deja la superficie con el techo; nadie parte de un cuerpo
  «bajo un techo»; recalcular y reproducir.
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import test_removal_operation as rop
from tests.unit.design import test_stockpile_operation as ops
from tests.unit.design import test_stockpile_prepare as tp

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
freeze = import_geoblender("core.versions.freeze")
geotiff_reader = import_geoblender("gis.geotiff.reader")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
supported_store = import_geoblender("design.supported_store")
thickness = import_geoblender("design.thickness")
vector = import_geoblender("gis.vector")
wkb = import_geoblender("core.gpkg.wkb")

GRID = rop.GRID
USER = rop.USER
SURVEY = rop.SURVEY
HILLSIDE = sdata.HILLSIDE_DATASET
FOOT = "Cuerpo de la ladera"
NO_DATA_FOOT = "Cuerpo sin datos"
ROOF, BASE = "Cuerpo bajo la ladera", "Cuerpo sobre la ladera"
EXACT = 1e-9
MIB = 1024 * 1024
NEGATIVE_LAYER, MISSING_LAYER, LINES_LAYER = "gis_fea_espesor_negativo", "gis_fea_espesor_falta", "gis_fea_espesor_lineas"
BRK_LAYER = "gis_brk_secciones"


def asked(name: str = ROOF, *, sense: str = "under_roof", feature: str = FOOT, surface: str = HILLSIDE,
          data_layer: str = sdata.THICKNESS_POINTS_LAYER, field: str = "espesor", data_from: str = "field",
          distance: float | None = 100.0, **changes: Any) -> Any:
    """La petición de un cuerpo de la huella ``feature`` con los datos de ``data_layer`` sobre la ladera: «bajo un techo» por defecto
    (la ladera es su techo) y, «sobre una base», desde el levantamiento de V01."""
    start = changes.pop("start", SURVEY if sense == "on_base" else None)
    return model.BodyRequest(name=name, layer=sdata.BODIES_LAYER, feature=feature, data_layer=data_layer, data_field=field,
                             data_from=data_from, surface=surface, sense=sense, start=start, max_distance_m=distance, **changes)


def feature_layer(layer: Any) -> Any:
    """La ``FeatureLayer`` de una capa de la cantera tal como la lee el proyecto (``nombre`` y sus campos)."""
    kinds = {field: "TEXT" if any(isinstance(item, str) for item in values) else "DOUBLE" for field, values in layer.fields.items()}
    columns = (vector.FieldColumn("nombre", "nombre", "TEXT"), *(vector.FieldColumn(f, f, k) for f, k in kinds.items()))
    values = {"nombre": layer.names, **{field: tuple(found) for field, found in layer.fields.items()}}
    return vector.FeatureLayer(layer.kind, tuple(range(1, len(layer.entities) + 1)), layer.entities, columns, values)


# --- Los datos de espesor, sin proyecto ----------------------------------------------------------------------------------


class ThicknessDataReaderTest(unittest.TestCase):
    """RF-016-20, RF-015-08: de dónde salen los datos de espesor y qué se rechaza antes de calcular, sin proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sections = sdata.thickness_sections()
        cls.layers = {layer.name: feature_layer(layer) for layer in sdata.layers()}

    def test_the_field_of_the_points_gives_one_datum_per_point_with_its_coordinates(self) -> None:
        """RF-016-20: un punto con el espesor de su campo; los 15 datos de las tres secciones, con X e Y absolutas, bit a bit."""
        found = supported_store.thickness_from_features(self.layers[sdata.THICKNESS_POINTS_LAYER], asked())
        np.testing.assert_array_equal(found.points, self.sections.points)
        self.assertEqual((found.polygons, found.sections), ((), False))

    def test_the_field_of_the_polygons_gives_a_constant_thickness_in_each(self) -> None:
        """RF-016-20: un polígono con el espesor constante de su campo (cada parte con el de su entidad), con sus anillos absolutos."""
        found = supported_store.thickness_from_features(
            self.layers[sdata.THICKNESS_POLYGONS_LAYER], asked(data_layer=sdata.THICKNESS_POLYGONS_LAYER))
        self.assertEqual(len(found.points), 0)
        self.assertEqual([value for _rings, value in found.polygons], [value for _ring, value in self.sections.polygons])
        for (rings, _value), (ring, _expected) in zip(found.polygons, self.sections.polygons, strict=True):
            np.testing.assert_array_equal(rings[0], ring)

    def test_the_z_of_the_vertices_of_the_3d_lines_is_the_thickness_when_it_is_declared(self) -> None:
        """RF-016-20 (decisión 18/11/2026): con ``data_from`` ``z``, la Z de cada vértice de las líneas 3D de la cantera
        (``lines_z``) es el espesor: los mismos 15 datos que los puntos, marcados como **secciones** (el TIN de una huella grande es
        caro con ellas)."""
        found = supported_store.thickness_from_lines(self.sections.lines_z, asked(data_layer=BRK_LAYER, field="Z", data_from="z"))
        np.testing.assert_array_equal(found.points, self.sections.points)
        self.assertTrue(found.sections)

    def test_the_declared_m_of_the_vertices_is_the_thickness_and_a_source_without_it_is_refused(self) -> None:
        """RF-016-20: con ``data_from`` ``m``, la M de los vértices (``lines_m``: X, Y y la Z del terreno, y el espesor en la M) es el
        espesor y **la Z no cuenta**; unas líneas que llegan sin M (lo único que guarda el proyecto: la importación la descarta) se
        rechazan con ``des.body_data_m``, sin suponer que la Z es el espesor."""
        request = asked(data_layer=BRK_LAYER, field="M", data_from="m")
        with_m = [np.column_stack([xyz, m]) for xyz, m in self.sections.lines_m]
        found = supported_store.thickness_from_lines(with_m, request)
        np.testing.assert_array_equal(found.points, self.sections.points)
        without = [xyz for xyz, _m in self.sections.lines_m]
        with self.assertRaises(messages.DesignError) as caught:
            supported_store.thickness_from_lines(without, request)
        self.assertEqual(caught.exception.code, "des.body_data_m")
        self.assertIn(BRK_LAYER, caught.exception.text)
        with self.assertRaises(messages.DesignError) as caught:
            supported_store.thickness_from_features(self.layers[sdata.THICKNESS_POINTS_LAYER], request)
        self.assertEqual(caught.exception.code, "des.body_data_m")

    def test_a_negative_missing_or_non_numeric_thickness_is_refused_with_layer_entity_field_and_value(self) -> None:
        """RF-016-01, RF-015-08: un espesor negativo, que falta o que no es un número (de un campo o de la Z de unas líneas) se rechaza
        **antes** de construir los datos, con la capa de los datos, el cuerpo, el campo y el valor (``des.entity_field_value``)."""
        base = sdata.layers()[3]
        cases = {"negativo": (-0.5, "-0,5"), "falta": (None, "—"), "infinito": (float("inf"), "inf")}
        for label, (value, shown) in cases.items():
            fields = {"espesor": (1.0, value, 2.0)}
            layer = feature_layer(sdata.FieldsLayer(NEGATIVE_LAYER, "point", base.entities[:3], base.names[:3], fields))
            with self.subTest(label=label), self.assertRaises(messages.DesignError) as caught:
                supported_store.thickness_from_features(layer, asked(data_layer=NEGATIVE_LAYER))
            error = caught.exception
            self.assertEqual(error.code, "des.entity_field_value")
            self.assertEqual((error.values["layer"], error.values["entity"], error.values["field"]),
                             (NEGATIVE_LAYER, ROOF, "espesor"))
            self.assertIn(shown, error.text)
            self.assertIn(NEGATIVE_LAYER, error.text)
        deep = [np.array([[1.0, 2.0, 1.0], [3.0, 4.0, -2.0]])]
        with self.assertRaises(messages.DesignError) as caught:
            supported_store.thickness_from_lines(deep, asked(data_layer=BRK_LAYER, field="Z", data_from="z"))
        self.assertEqual((caught.exception.code, caught.exception.values["field"], caught.exception.values["value"]),
                         ("des.entity_field_value", "Z", -2.0))

    def test_a_layer_that_cannot_give_the_thickness_as_declared_is_refused(self) -> None:
        """RF-016-20: una capa de líneas no da el espesor de un campo; una de puntos o de polígonos no tiene Z; líneas sin Z, tampoco
        (``des.body_data_kind``, nombrando la capa y lo que tiene); un campo que no es numérico o no está, ``des.quarry_layer_field``."""
        lines = feature_layer(sdata.FieldsLayer(LINES_LAYER, "line", (((self.sections.lines_z[0][:, :2],),),), ("S1",),
                                                {"espesor": (1.0,)}))
        for layer, name, how in ((lines, LINES_LAYER, "field"), (self.layers[sdata.THICKNESS_POINTS_LAYER],
                                                                   sdata.THICKNESS_POINTS_LAYER, "z")):
            with self.subTest(layer=name, how=how), self.assertRaises(messages.DesignError) as caught:
                if how == "field":
                    supported_store.thickness_from_features(layer, asked(data_layer=name))
                else:
                    supported_store.thickness_from_features(layer, asked(data_layer=name, field="Z", data_from="z"))
            self.assertEqual(caught.exception.code, "des.body_data_kind")
            self.assertIn(name, caught.exception.text)
        with self.assertRaises(messages.DesignError) as caught:
            supported_store.thickness_from_lines([self.sections.lines_z[0][:, :2]], asked(data_layer=BRK_LAYER, field="Z", data_from="z"))
        self.assertEqual(caught.exception.code, "des.body_data_kind")
        with self.assertRaises(messages.DesignError) as caught:
            supported_store.thickness_from_features(self.layers[sdata.THICKNESS_POINTS_LAYER], asked(field="no_existe"))
        self.assertEqual(caught.exception.code, "des.quarry_layer_field")

    def test_a_frozen_table_of_3d_lines_gives_the_z_with_the_real_wkb(self) -> None:
        """RF-009-11, RF-016-20: ``frozen_thickness_data`` lee la tabla congelada de la capa de datos **sin el proyecto**: las líneas 3D
        como las guarda el GeoPackage (WKB con Z) dan los mismos 15 datos que ``lines_z``, y una capa de entidades (la huella de los
        puntos), los puntos; todo bit a bit."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute(f'CREATE TABLE "{BRK_LAYER}" (fid INTEGER PRIMARY KEY, geom BLOB)')
        for number, line in enumerate(self.sections.lines_z, start=1):
            conn.execute(f'INSERT INTO "{BRK_LAYER}" VALUES (?, ?)', (number, wkb.encode_geometry("LINESTRING", line, 25830, True)))
        found = supported_store.frozen_thickness_data(conn, BRK_LAYER, asked(data_layer=BRK_LAYER, field="Z", data_from="z"))
        np.testing.assert_array_equal(found.points, self.sections.points)
        self.assertTrue(found.sections)
        with self.assertRaises(messages.DesignError) as caught:
            supported_store.frozen_thickness_data(conn, BRK_LAYER, asked(data_layer=BRK_LAYER))
        self.assertEqual(caught.exception.code, "des.body_data_kind")


# --- La orden, con proyecto ------------------------------------------------------------------------------------------------


class BodyCase(rop.RemovalCase):
    """La cantera de los acopios (2 m, V01 con su levantamiento) con el tipo del cuerpo registrado con sus funciones reales (recalcular y
    reproducir) y las capas del proyecto de la ladera, más lo de ``RemovalCase`` (``state``, ``refused``, las entradas y las salidas de una
    operación…)."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        body_type = provenance.OPERATION_TYPES_BY_NAME[provenance.BODY].definition(ops.recompute_function, design_reproduce.reproduce_body)
        return (*super().definitions(), body_type, *provenance.BODY_FIGURES)

    @classmethod
    def calculate(cls, request: Any, **options: Any) -> Any:
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        return ops.last(steps.body_run(cls.project, request, **options))

    @classmethod
    def make(cls, request: Any, **options: Any) -> tuple[Any, Any]:
        """«Calcula» y «crea» ``request`` (un minuto después de lo anterior): la ``Calculation`` y lo guardado."""
        cls.clock.advance(minutes=1)
        calculation = cls.calculate(request)
        stored = calculation.create(decided_by=USER, **options)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def locator(self, family: str, name: str) -> str:
        return provenance.dataset_locator(family, name, "V01")

    def raster(self, family: str, name: str) -> np.ndarray:
        """La rejilla de la salida ``family`` del cuerpo ``name`` tal como está en su fichero."""
        return self.grid_of(provenance.dataset_name(family, name))

    def sizes(self, uid: str) -> dict[str, int]:
        """Lo que pesa cada rejilla que escribió la operación ``uid`` en el disco (bytes)."""
        return {name: (self.root / self.record(name, self.v1).locator).stat().st_size for role, name in self.outputs_of(uid)
                if self.record(name, self.v1).locator.endswith(".tif")}


class BodyOperationTest(BodyCase):
    """RF-016-01, RF-016-20 a RF-016-22, RF-015-02, RF-015-03, RF-015-29, RF-009-11, RNF-016-07, **en orden**: la huella de la ladera con
    los 15 datos de espesor, «bajo la ladera» (``BDY-001``) y «sobre la ladera» (``BDY-002``)."""

    first: ClassVar[Any]
    stored: ClassVar[Any]
    second: ClassVar[Any]
    revision: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        base = sdata.layers()[3]
        for name, fields in ((NEGATIVE_LAYER, {"espesor": (1.0, -0.5, 2.0)}), (MISSING_LAYER, {"espesor": (1.0, None, 2.0)})):
            cls.clock.advance(minutes=1)
            sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(name, "point", base.entities[:3], base.names[:3], fields))
        cls.clock.advance(minutes=1)
        section = sdata.thickness_sections().lines_z[0][:, :2]
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(LINES_LAYER, "line", (((section,),),), ("S1",), {"espesor": (1.0,)}))
        cls.clock.advance(minutes=1)

    # --- Calcular ------------------------------------------------------------------------------------------------------

    def test_a_calculating_writes_nothing_and_leaves_the_thickness_under_the_roof_that_reproduces_the_data(self) -> None:
        """RF-015-03, RF-016-01, RF-016-20, CE-016-05 con proyecto: «Calcular» el cuerpo de la ladera «bajo un techo» no escribe **nada**
        (ni la base de datos, ni las operaciones, los datos, los parámetros o las cifras; solo los temporales del espesor y de la base,
        que **descartar** borra): el espesor reproduce los 15 datos en su celda a ≤ 10⁻⁹ m, queda entre el menor y el mayor, no es
        negativo, **el techo es la ladera** en todas las celdas del cuerpo y la base es el techo menos el espesor (nunca sobre el techo)."""
        before = self.state()
        calculation = self.calculate(asked())
        self.assertEqual(self.state(), before, "calcular no escribe")
        self.assertEqual(len(self.temporaries()), 2, "los temporales del espesor y de la base")
        self.assertTrue(calculation.open)
        self.assertEqual((calculation.op_type, calculation.name, calculation.version, calculation.entity.code),
                         (provenance.BODY, ROOF, "V01", "BDY-001"))
        outcome = calculation.outcome
        hand = tp.hand_cells(sdata.BODIES[0].box)
        flat = outcome.body.ravel()  # la ventana de trabajo: la de la huella más una celda
        rows, cols = np.nonzero(outcome.body)
        found = np.sort((rows + outcome.window[0].start) * GRID.ncols + cols + outcome.window[1].start)
        np.testing.assert_array_equal(found, hand)
        self.assertEqual(int(flat.sum()), len(hand))
        hillside = sdata.hillside(GRID)
        window = outcome.window
        np.testing.assert_array_equal(outcome.top[outcome.body], hillside[window][outcome.body])
        self.assertTrue(np.all(outcome.base[outcome.body] <= outcome.top[outcome.body]))
        self.assertLessEqual(float(np.abs(outcome.top - outcome.base - outcome.thickness)[outcome.body].max()), EXACT)
        values = outcome.thickness[outcome.body]
        data = sdata.thickness_sections().points
        self.assertGreaterEqual(float(values.min()), float(data[:, 2].min()) - 0.0)
        self.assertLessEqual(float(values.max()), float(data[:, 2].max()))
        for x, y, wanted in data:
            row, col = int((GRID.north - y) // GRID.dy), int((x - GRID.west) // GRID.dx)
            self.assertLessEqual(abs(outcome.thickness[row - window[0].start, col - window[1].start] - wanted), EXACT, (row, col))
        self.assertEqual((outcome.ignored, outcome.far_m2), (0, 0.0))
        summary = calculation.summary
        self.assertEqual((summary.name, summary.code, summary.version, summary.sense, summary.data_layer),
                         (ROOF, "BDY-001", "V01", "under_roof", sdata.THICKNESS_POINTS_LAYER))
        self.assertEqual(summary.figures, outcome.figures)
        self.assertEqual((summary.volume_m3, summary.thickness_max_m), (outcome.volume_m3, outcome.thickness_max_m))
        calculation.discard()
        self.assertEqual(self.temporaries(), [], "descartar borra los temporales")
        self.assertEqual(self.state(), before)

    def test_a_closing_the_steps_halfway_leaves_nothing(self) -> None:
        """RF-015-29, RNF-016-05: con un presupuesto de 0 s son varios pasos y cerrar el generador a mitad (Esc) o justo antes del último
        no deja nada —ni un temporal—; el último paso es el que lleva el cálculo."""
        before = self.state()
        work = steps.body_run(self.project, asked(), version=self.v1.uid, masks=self.masks_v1, budget_s=0.0)
        shown = [next(work) for _ in range(4)]
        self.assertTrue(all(step.result is None for step in shown))
        work.close()
        self.assertEqual((self.state(), self.temporaries()), (before, []))
        every = list(steps.body_run(self.project, asked(), version=self.v1.uid, masks=self.masks_v1, budget_s=0.0))
        self.assertGreater(len(every), 10, "por pasos")
        self.assertTrue(all(step.result is None for step in every[:-1]))
        self.assertIsInstance(every[-1].result, steps.Calculation)
        every[-1].result.discard()
        work = steps.body_run(self.project, asked(), version=self.v1.uid, masks=self.masks_v1, budget_s=0.0)
        for _step in range(len(every) - 1):
            next(work)
        work.close()
        self.assertEqual((self.state(), self.temporaries()), (before, []), "justo antes del último paso")

    def test_a_the_polygons_of_the_project_give_their_constant_thickness_in_their_cells_without_triangulating_their_interior(self) -> None:
        """RF-016-20, RNF-016-02 (decisión 19/11/2026): con las tres bandas de 200 × 20 m del proyecto (espesor constante en cada una:
        1,7, 2,2 y 1,7 m) las celdas de cada banda toman **su** espesor (a mano, por el centro de la celda), las del interior son
        directas y solo se triangulan las del contorno: muchos menos datos que celdas con dato."""
        calculation = self.calculate(asked(data_layer=sdata.THICKNESS_POLYGONS_LAYER))
        outcome = calculation.outcome
        window = outcome.window
        for (ring, value), box in zip(sdata.thickness_sections().polygons, ((100.0, 130.0, 300.0, 150.0), (100.0, 190.0, 300.0, 210.0),
                                                                          (100.0, 250.0, 300.0, 270.0)), strict=True):
            cells = tp.hand_cells(box)
            rows, cols = np.divmod(cells, GRID.ncols)
            got = outcome.thickness[rows - window[0].start, cols - window[1].start]
            self.assertLessEqual(float(np.abs(got - value).max()), EXACT, box)
        self.assertEqual(outcome.data_cells, 3 * 100 * 10)
        self.assertGreater(outcome.direct_cells, 0)
        self.assertLess(outcome.tin_points, outcome.data_cells // 2)
        self.assertEqual(outcome.tin_points, outcome.data_cells - outcome.direct_cells)
        self.assertEqual(calculation.summary.notices, outcome.notices)
        calculation.discard()

    def test_a_what_is_far_from_the_data_is_warned_with_its_area_volume_and_place_and_can_still_be_created(self) -> None:
        """RF-016-21 (B9, D-9): con una distancia máxima de 20 m **las celdas a más de ella de los datos se avisan** con su área, su
        volumen y su lugar y no impiden calcular; el área sale a mano del bucle de las celdas del cuerpo a más de 20 m de su dato más
        próximo (por fuerza bruta con enteros)."""
        calculation = self.calculate(asked(distance=20.0))
        outcome = calculation.outcome
        rows, cols = np.nonzero(outcome.body)
        cells = [(int(r) + outcome.window[0].start, int(c) + outcome.window[1].start) for r, c in zip(rows, cols, strict=True)]
        data = [(int((GRID.north - y) // GRID.dy), int((x - GRID.west) // GRID.dx)) for x, y, _t in sdata.thickness_sections().points]
        far = [(r, c) for r, c in cells if min((r - dr) ** 2 + (c - dc) ** 2 for dr, dc in data) * 4.0 > 20.0 ** 2]
        self.assertGreater(len(far), 0)
        self.assertEqual(outcome.far_m2, len(far) * 4.0)
        (notice,) = [item for item in calculation.notices if item.code == "des.body_far"]
        self.assertEqual((notice.values["area"], notice.values["distance"]), (round(len(far) * 4.0, 2), 20.0))
        self.assertGreater(float(notice.values["volume"]), 0.0)
        calculation.discard()

    def test_a_a_slow_estimate_is_warned_in_the_summary_with_the_estimated_cost_and_the_cause_and_can_still_be_created(self) -> None:
        """RNF-016-02, RF-016-20 (T44): el aviso de lo lento sale por el **coste estimado de las cajas del TIN**, no por el área: con el
        límite bajado a 0,5 s, el resumen de «Calcular» (que es el del cálculo) lleva el aviso con la estimación (``BODY_BASE_S`` más lo
        que suman las cajas del TIN) y la separación de los datos como causa, en los dos idiomas, y es un aviso (se puede crear); con el
        límite de siempre (8 s) la cantera no avisa."""
        with mock.patch.object(thickness, "SLOW_BODY_S", 0.5):
            calculation = self.calculate(asked(data_layer=sdata.THICKNESS_POINTS_LAYER))
        outcome = calculation.outcome
        self.assertGreater(outcome.tin_cost, 0.0)
        (notice,) = [item for item in calculation.notices if item.code == "des.body_sections_large"]
        self.assertEqual((notice.values["seconds"], notice.values["limit"]), (round(outcome.estimated_s, 1), 0.5))
        self.assertEqual(calculation.summary.notices, outcome.notices)
        self.assertIn(notice.text("es"), calculation.warnings("es"))
        self.assertIn("separación de los datos de espesor", notice.text("es"))
        self.assertIn("separation of its thickness data", notice.text("en"))
        calculation.discard()
        quiet = self.calculate(asked(data_layer=sdata.THICKNESS_POINTS_LAYER))
        self.assertNotIn("des.body_sections_large", [item.code for item in quiet.notices])
        quiet.discard()

    # --- Los rechazos ----------------------------------------------------------------------------------------------------

    def test_b_the_refusals_write_nothing_and_name_what_is_wrong(self) -> None:
        """RF-016-22, RF-016-20, RF-015-08, RF-016-01: cada rechazo sale **al avanzar** (antes de calcular) y no escribe nada ni deja un
        temporal: un espesor negativo o que falta, con la capa, el cuerpo, el campo y el valor; sin distancia máxima (D-9: no se elige
        una por la persona) o con una que no es positiva; leer la Z de una capa de entidades, líneas de un campo, o la M (que el proyecto no
        guarda); una huella que no es de polígonos o que no existe; una huella **sin ningún dato de espesor**, nombrándola con la capa de los
        datos (RF-016-22); «sobre una base» sin partida."""
        error = self.refused(asked(data_layer=NEGATIVE_LAYER), "des.entity_field_value")
        self.assertEqual((error.values["layer"], error.values["field"], error.values["value"]), (NEGATIVE_LAYER, "espesor", -0.5))
        self.assertIn("-0,5", error.text)
        error = self.refused(asked(data_layer=MISSING_LAYER), "des.entity_field_value")
        self.assertEqual(error.values["value"], "—")
        self.refused(asked(field="no_existe"), "des.quarry_layer_field")
        error = self.refused(asked(distance=None), "des.entity_param_missing")
        self.assertEqual(error.values["field"], "des.body.bdy_001.max_distance_m")
        self.refused(asked(distance=0.0), "des.entity_param_range")
        self.refused(asked(data_from="z", field="Z"), "des.body_data_kind")
        self.refused(asked(data_layer=LINES_LAYER), "des.body_data_kind")
        self.refused(asked(data_from="m", field="M"), "des.body_data_m")
        self.refused(asked(data_layer=sdata.CROWN_LAYER, field="cota", data_from="z"), "des.body_data_kind")
        error = self.refused(asked(feature="No hay"), "des.entity_feature_unknown")
        self.assertEqual(error.values["layer"], sdata.BODIES_LAYER)
        self.refused(model.BodyRequest(name=ROOF, layer=sdata.THICKNESS_POINTS_LAYER, feature="A1", data_layer=sdata.THICKNESS_POINTS_LAYER,
                                       data_field="espesor", data_from="field", surface=HILLSIDE, sense="under_roof",
                                       max_distance_m=100.0), "des.layer_not_polygons")
        error = self.refused(asked(feature=NO_DATA_FOOT), "des.body_no_data")
        self.assertEqual((error.values["footprint"], error.values["layer"]), (NO_DATA_FOOT, sdata.THICKNESS_POINTS_LAYER))
        self.assertIn(NO_DATA_FOOT, error.text)
        self.assertIn(sdata.THICKNESS_POINTS_LAYER, error.text)
        self.refused(asked(sense="on_base", start=None), "des.entity_param_missing")
        with self.assertRaises(ValueError):
            self.calculate(asked(protect=True))
        with self.assertRaises(ValueError):
            self.calculate(asked(support=SURVEY))
        before = self.state()
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.state(), before)

    # --- Crear ---------------------------------------------------------------------------------------------------------------

    def test_c_creating_fails_as_a_whole_if_a_table_cannot_be_written(self) -> None:
        """RF-015-02, RF-015-29: «Crear» es **una** transacción: un fallo al escribir la segunda tabla no deja nada —ni la operación, los
        datos, los parámetros de la entidad, las cifras o los ficheros, ni un temporal— y el cálculo queda descartado."""
        calculation = self.calculate(asked())
        before = self.state()
        written: list[str] = []
        real = store.DesignWriter._write_table

        def breaks(writer: Any, conn: Any, table: Any) -> None:
            written.append(table.family)
            if len(written) == 2:
                raise RuntimeError("falla la segunda tabla")
            real(writer, conn, table)

        with mock.patch.object(store.DesignWriter, "_write_table", breaks):
            with self.assertRaises(RuntimeError):
                calculation.create(decided_by=USER)
        self.assertEqual(self.state(), before, "no queda nada")
        self.assertEqual(self.temporaries(), [])
        self.assertFalse(calculation.open, "el cálculo queda descartado")

    def test_d_creating_under_a_roof_registers_the_body_in_one_transaction_and_keeps_the_surface(self) -> None:
        """RF-016-20, RF-016-01, RF-015-02, RF-015-01, RNF-016-07 (P-4): «Crear» el cuerpo «bajo un techo» registra **de una vez** los
        parámetros de la entidad (``des.body.bdy_001.*`` de V01, con su decisor y su origen), la operación ``des.body`` con sus entradas
        (la huella con el papel ``entity_layer``, los datos con ``body_data``, la superficie que es su techo, ``surface``, y las máscaras)
        y sus parámetros, **el espesor y la base dispersos** —ni una superficie entera: no cambia la de nadie—, la huella (``des_epr_``),
        el informe y las cifras ``des.bdy_*`` con el ámbito de la entidad. La base más el espesor es la ladera en las celdas del cuerpo y
        ``NaN`` en el resto; las entradas no cambian de contenido; **pesa ≤ 2 MiB**."""
        hillside_before = self.record(HILLSIDE).content_sha256
        footprint_before = self.record(sdata.BODIES_LAYER).content_sha256
        data_before = self.record(sdata.THICKNESS_POINTS_LAYER).content_sha256
        calculation, stored = self.make(asked())
        type(self).first, type(self).stored = calculation, stored
        uid = str(stored.handle.uid)
        self.assertEqual(self.query("SELECT op_type, scope, status, supersedes_uid FROM gb_operation WHERE uid = ?", uid),
                         [(provenance.BODY, "version", "done", None)])
        self.assertEqual(self.operation_of("BDY-001"), uid)
        rows = {key: (value, decided_by) for key, value, decided_by in self.query(
            "SELECT key, value, decided_by FROM gb_parameter WHERE key LIKE 'des.body.bdy_001.%' AND scope = 'version'")}
        for param, value in (("name", ROOF), ("layer", sdata.BODIES_LAYER), ("data_layer", sdata.THICKNESS_POINTS_LAYER),
                             ("data_field", "espesor"), ("data_from", "field"), ("surface", HILLSIDE), ("sense", "under_roof"),
                             ("max_distance_m", 100.0), ("zero_at_edge", False)):
            found = rows[f"des.body.bdy_001.{param}"]
            self.assertEqual((json.loads(found[0]), found[1]), (value, USER), param)
        self.assertEqual(json.loads(rows["des.body.bdy_001.feature"][0]), "1", "la huella, por su fid")
        self.assertNotIn("des.body.bdy_001.start", rows, "no cambia la superficie: sin partida")
        read = {name for (name,) in self.query("SELECT p.key FROM gb_operation_param AS p WHERE p.operation_uid = ?", uid)}
        self.assertLessEqual({f"des.body.bdy_001.{name}" for name in ("max_distance_m", "zero_at_edge", "sense", "surface")}, read)
        self.assertEqual(self.inputs_of(uid)[:3],
                         [("entity_layer", sdata.BODIES_LAYER), ("body_data", sdata.THICKNESS_POINTS_LAYER), ("surface", HILLSIDE)])
        outputs = self.outputs_of(uid)
        self.assertEqual(outputs, [("body_thickness", provenance.dataset_name(provenance.BODY_THICKNESS_GRID, ROOF)),
                                   ("body_base", provenance.dataset_name(provenance.BODY_BASE_GRID, ROOF)),
                                   ("entity", provenance.dataset_name(provenance.ENTITY_TABLE, ROOF)),
                                   ("entity_report", provenance.dataset_name(provenance.ENTITY_REPORT_TABLE, ROOF))])
        for name, sha in ((HILLSIDE, hillside_before), (sdata.BODIES_LAYER, footprint_before), (sdata.THICKNESS_POINTS_LAYER, data_before)):
            self.assertEqual(self.record(name).content_sha256, sha, f"{name} no cambia")
        thick, base = self.raster(provenance.BODY_THICKNESS_GRID, ROOF), self.raster(provenance.BODY_BASE_GRID, ROOF)
        outcome = calculation.outcome
        expected = np.full(GRID.shape, np.nan)
        expected[outcome.window] = outcome.thickness
        np.testing.assert_array_equal(thick, expected)
        hillside = sdata.hillside(GRID)
        made = np.isfinite(thick)
        self.assertEqual(int(made.sum()), len(tp.hand_cells(sdata.BODIES[0].box)))
        self.assertLessEqual(float(np.abs(base[made] + thick[made] - hillside[made]).max()), EXACT)
        self.assertTrue(np.isnan(base[~made]).all() and np.isnan(thick[~made]).all(), "disperso: NaN fuera del cuerpo")
        self.assertTrue(np.all(thick[made] >= 0.0))
        figures = self.figures_by_key(uid)
        for key, value in (("des.bdy_volume_m3", outcome.volume_m3), ("des.bdy_thickness_max_m", outcome.thickness_max_m),
                           ("des.bdy_far_m2", outcome.far_m2), ("des.bdy_far_m3", outcome.far_m3), ("des.bdy_ignored", 0.0)):
            self.assertEqual(figures[key], value, key)
        self.assertLessEqual(abs(figures["des.bdy_volume_m3"] - float(np.nansum(thick)) * 4.0) / figures["des.bdy_volume_m3"], EXACT)
        scopes = [json.loads(scope) for (scope,) in self.query(
            "SELECT scope FROM gb_figure WHERE operation_uid = ? AND key = 'des.bdy_volume_m3'", uid)]
        self.assertEqual(scopes, [{"name": "cuerpo_bajo_la_ladera", "entity": "BDY-001"}])
        entry = entities.registry(self.project, self.v1.uid).get("BDY-001")
        assert entry is not None
        self.assertEqual((entry.record.kind, entry.record.name, entry.record.start, entry.record.state),
                         (entities.EntityKind.BODY, ROOF, None, entities.EntityState.CURRENT))
        self.assertEqual(entities.chain_tails(entities.registry(self.project, self.v1.uid).records), (),
                         "sin partida no está en ninguna cadena ni deja una superficie de diseño")
        (table,) = self.query(f'SELECT code, name, kind, start_surface, support_surface, layer, source_fid, mode, cells FROM '
                              f'"{self.locator(provenance.ENTITY_TABLE, ROOF)}"')
        self.assertEqual(table, ("BDY-001", ROOF, "body", HILLSIDE, None, sdata.BODIES_LAYER, 1, "body", len(tp.hand_cells(sdata.BODIES[0].box))))
        size = sum(self.sizes(uid).values())
        self.assertLessEqual(size, 2 * MIB, f"un cuerpo bajo un techo pesa {size} B")
        type(self).under_roof_bytes = size
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.stale_causes(uid), set())

    def test_e_the_report_carries_the_figures_the_cells_and_the_warnings(self) -> None:
        """RF-016-20, RF-016-21: el informe (``des_prp_``) lleva las celdas (la huella, el cuerpo, las del TIN, las del más próximo y
        las directas), las cifras con su lugar y los dos valores que lo gobiernan (la distancia máxima y «cero en el borde»); la
        detección de nada más, ni de la huella de otra entidad, cambia por ello."""
        report = {quantity: (value, note) for quantity, value, _unit, note in self.query(
            f'SELECT quantity, value, unit_code, note FROM "{self.locator(provenance.ENTITY_REPORT_TABLE, ROOF)}"')}
        outcome = self.first.outcome
        hand = len(tp.hand_cells(sdata.BODIES[0].box))
        for quantity, value in (("footprint_cells", hand), ("body_cells", hand), ("data_cells", 15), ("zero_cells", 0),
                                ("tin_cells", outcome.tin_cells), ("nearest_cells", outcome.nearest_cells), ("direct_cells", 0),
                                ("tin_points", 15), ("unsupported_cells", 0), ("far_cells", 0), ("volume_m3", outcome.volume_m3),
                                ("thickness_max_m", outcome.thickness_max_m), ("max_distance_m", 100.0), ("zero_at_edge", 0)):
            self.assertEqual(report[quantity][0], value, quantity)
        self.assertEqual(report["tin_cells"][0] + report["nearest_cells"][0], hand)
        place = report["thickness_max_m"][1]
        self.assertEqual(place, f"{outcome.thickness_max_x!r};{outcome.thickness_max_y!r}")

    def test_f_nobody_can_start_from_the_surface_of_a_body_under_a_roof(self) -> None:
        """H-9, RF-016-20 (decisión de la sesión principal, 18/11/2026): el cuerpo «bajo un techo» no cambia la superficie y no la escribe,
        así que **nadie parte de ella** —ni otro cuerpo, ni una retirada, ni una plataforma, ni como superficie conocida— y se rechaza con
        ``des.chainless_start`` nombrando las dos entidades, **antes de calcular y sin escribir nada**; sí se parte de la superficie de un
        cuerpo «sobre una base» (que la deja)."""
        error = self.refused(asked("Otro cuerpo", sense="on_base", start="entity:BDY-001"), "des.chainless_start")
        self.assertEqual((error.values["entity"], error.values["other"], error.values["value"]), ("Otro cuerpo", ROOF, "entity:BDY-001"))
        self.assertIn(ROOF, error.text)
        self.refused(asked("Otro cuerpo", surface="entity:BDY-001"), "des.chainless_start")
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            ops.last(steps.removal_run(self.project, model.RemovalRequest(name="Retirada", stockpile="STK-001#A", start="entity:BDY-001",
                                                                         transition_deg=30.0), version=self.v1.uid, masks=self.masks_v1))
        self.assertEqual(caught.exception.code, "des.chainless_start")
        fields = model.PlatformFields(layer="gis_fea_nada", start_level_field="cota", gradient_field="pendiente")
        with self.assertRaises(messages.DesignError) as caught:
            ops.last(steps.platform_run(self.project, model.PlatformRequest("Sobre el cuerpo", fields, "1", "entity:BDY-001"),
                                        version=self.v1.uid, masks=self.masks_v1))
        self.assertEqual(caught.exception.code, "des.chainless_start")
        self.assertEqual((self.state(), self.temporaries()), (before, []))

    def test_g_a_body_on_a_base_leaves_the_surface_with_its_roof_and_chains(self) -> None:
        """RF-016-20, RF-016-01, RF-015-04, P-12: el cuerpo «sobre una base» (la ladera es su apoyo; parte del levantamiento de V01) deja
        la **superficie entera** con el techo, ``máx(partida, apoyo + espesor)`` donde se admite relleno y la partida, bit a bit, en
        las demás —a mano, del espesor y la ladera de los ficheros—; consume la partida con el papel ``surface`` y la ladera con
        ``supported_on``; **encadena** (``BDY-002`` parte del levantamiento y otra entidad podría partir de su superficie); no escribe la
        base; y pesa ≤ 17 MiB."""
        calculation, stored = self.make(asked(BASE, sense="on_base"))
        type(self).second = calculation
        uid = str(stored.handle.uid)
        self.assertEqual(self.operation_of("BDY-002"), uid)
        outputs = self.outputs_of(uid)
        self.assertEqual([role for role, _name in outputs], ["body_thickness", "entity_surface", "entity", "entity_report"])
        inputs = self.inputs_of(uid)
        self.assertEqual(inputs[:3], [("entity_layer", sdata.BODIES_LAYER), ("body_data", sdata.THICKNESS_POINTS_LAYER), ("surface", SURVEY)])
        self.assertIn(("supported_on", HILLSIDE), inputs)
        self.assertEqual([item for item in inputs if item[0] == "supported_on"][0], ("supported_on", HILLSIDE), "la conocida, la primera")
        thick = self.raster(provenance.BODY_THICKNESS_GRID, BASE)
        surface = self.raster(provenance.ENTITY_SURFACE_GRID, BASE)
        start, hillside = sdata.survey(GRID), sdata.hillside(GRID)
        made = np.isfinite(thick)
        fill = np.asarray(self.masks_v1.fill_allowed() | self.masks_v1.fill_strip())
        expected = start.copy()
        pick = made & fill
        expected[pick] = np.maximum(start[pick], hillside[pick] + thick[pick])
        np.testing.assert_array_equal(surface, expected)
        np.testing.assert_array_equal(np.delete(surface.ravel(), np.flatnonzero(pick)), np.delete(start.ravel(), np.flatnonzero(pick)),
                                      "fuera del relleno admitido, la partida bit a bit")
        self.assertGreater(int((surface != start).sum()), 0)
        entry = entities.registry(self.project, self.v1.uid).get("BDY-002")
        assert entry is not None
        self.assertEqual((entry.record.kind, entry.record.start, entry.record.state),
                         (entities.EntityKind.BODY, SURVEY, entities.EntityState.CURRENT))
        self.assertEqual([item.code for item in entities.chain_tails(entities.registry(self.project, self.v1.uid).records)], ["BDY-002"])
        self.assertEqual(self.query(f'SELECT start_surface, support_surface FROM "{self.locator(provenance.ENTITY_TABLE, BASE)}"'),
                         [(SURVEY, HILLSIDE)])
        size = sum(self.sizes(uid).values())
        self.assertLessEqual(size, 17 * MIB, f"un cuerpo sobre una base pesa {size} B")
        type(self).on_base_bytes = size
        follow = self.calculate(asked("Sigue al cuerpo", sense="on_base", start="entity:BDY-002", surface=SURVEY))
        self.assertEqual(follow.entity.start_surface, provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, BASE))
        follow.discard()
        self.refused(asked("Otro más", sense="on_base", start=SURVEY), "des.entity_start_taken")
        self.refused(asked(ROOF), "des.entity_name_repeated")

    # --- Recalcular y reproducir -------------------------------------------------------------------------------------------

    def test_h_recomputing_repeats_the_body_with_the_parameters_of_its_entity(self) -> None:
        """RF-015-02, RF-016-10, RF-015-16: cambiar la distancia máxima de la entidad (``des.body.bdy_001.max_distance_m``) la deja obsoleta
        con su causa y **«Recalcular lo obsoleto»** la repite como una operación nueva que sustituye a la anterior (los parámetros de su
        entidad), con la misma identidad (``BDY-001``) y **sin reescribir sus parámetros**: con 20 m aparece lo lejano de los datos y el volumen cambia (los triángulos de más de 40 m se descartan)."""
        old = str(self.stored.handle.uid)
        figures = self.figures_by_key(old)
        self.assertEqual(figures["des.bdy_far_m2"], 0.0)
        self.assertEqual(self.stale_causes(old), set())
        self.change(design_params.entity_key("BDY-001", "max_distance_m"), 20.0)
        self.assertNotEqual(self.stale_causes(old), set(), "obsoleta con su causa")
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("BDY-001").record.state, entities.EntityState.STALE)
        rows = self.query("SELECT key, scope, value, rev FROM gb_parameter WHERE key LIKE 'des.body.bdy_001.%' ORDER BY key, scope")
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertTrue(all(result.status == recompute_mod.UnitStatus.DONE for result in outcome.results), outcome.results)
        new = self.operation_of("BDY-001")
        self.assertNotEqual(new, old)
        self.assertEqual(self.query("SELECT supersedes_uid, status FROM gb_operation WHERE uid = ?", new), [(old, "done")])
        after = self.query("SELECT key, scope, value, rev FROM gb_parameter WHERE key LIKE 'des.body.bdy_001.%' ORDER BY key, scope")
        self.assertEqual([row[0] for row in after], [row[0] for row in rows], "sin parámetros nuevos")
        self.assertGreater(self.figures_by_key(new)["des.bdy_far_m2"], 0.0, "con 20 m, lo lejano")
        self.assertNotEqual(self.figures_by_key(new)["des.bdy_volume_m3"], figures["des.bdy_volume_m3"],
                            "con 20 m se descartan los triángulos de lado mayor que 40 m: allí manda el dato más próximo")
        self.assertEqual(self.stale_causes(new), set())
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("BDY-001").record.state, entities.EntityState.CURRENT)

    def test_i_reproducing_the_frozen_revision_gives_the_same_thickness_surface_tables_and_figures(self) -> None:
        """RF-009-11, RF-015-02: congelada ``V01.r1`` con los dos cuerpos, reproducirla —**sin el proyecto**: desde lo congelado, la huella,
        los datos de espesor, la superficie conocida, la partida y las máscaras, y los parámetros— da, de cada cuerpo, el mismo espesor,
        la misma superficie o base, la misma huella y el mismo informe (el hash de cada dato) y las mismas cifras; reproducir no escribe
        nada en el proyecto."""
        self.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        type(self).revision = str(frozen.frozen.uid)
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before,
                         "reproducir no escribe en el proyecto")
        uids = {self.operation_of(code) for code in ("BDY-001", "BDY-002")}
        mine = [check for check in report.outputs if check.operation_uid in uids]
        self.assertEqual(len(mine), 8, "el espesor, la base o la superficie, la huella y el informe de cada cuerpo")
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        self.assertEqual(len([check for check in report.figures if check.operation_uid in uids]), 10, "las cinco cifras de cada uno")
        self.assertTrue(all(check.same for check in report.outputs), [check for check in report.outputs if not check.same])
        self.assertTrue(all(check.same for check in report.figures), [check for check in report.figures if not check.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)

    def test_j_what_a_body_keeps_is_small_when_it_is_under_a_roof_and_a_whole_surface_when_it_is_on_a_base(self) -> None:
        """RNF-016-07 (P-4, P-12): lo que guarda un cuerpo bajo un techo es de unos KiB (disperso) y lo de uno sobre una base, la superficie
        entera (la T37 lo mide con 2,81 M celdas: ≤ 2 MiB y ≤ 17 MiB)."""
        self.assertLess(self.under_roof_bytes, 200 * 1024, "disperso: unos KiB frente a la superficie entera")
        self.assertGreater(self.on_base_bytes, self.under_roof_bytes)


if __name__ == "__main__":
    unittest.main()
