# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar la pista y rechazar, sobre el proyecto de las pistas, como prueba de **hito** (spec 017, T19, que lo dejó en el «verde» dentro de ``test_road_prepare``;
T48, que lo pasó al paso «hito» de ``tools/check.py --completo`` para que el «verde» vuelva a costar ≤ +3 s: RNF-017-09; HU-017-1 y HU-017-2; RF-017-01 a RF-017-06; RF-015-06, RF-015-07,
RF-015-08 y RF-015-09; plan 017 §5.1, §5.2.1 a §5.2.3, §5.3.1, §5.7 P-1 y P-5; D-3, D-13 y D-16).

:class:`RoadPrepareTest` es lo que antes estaba en ``test_road_prepare`` y monta el proyecto de las pistas (``tests.support.road_data``: la cantera de la 015 con los terrenos como rejillas, en la gruesa
de 2 m, 200 × 200 celdas; ≈ 1,2 s en las 21 pruebas): ``design.road_store`` **lee y comprueba antes de calcular**, sin escribir nada (la versión editable, la geometría de origen por modo, el perfil de
la versión, las cotas de inicio y de fin, la partida y la cadena, las máscaras de la versión y los parámetros sin valor por defecto), y cada rechazo de RF-017-04 sale **sin escribir nada** y nombrando la
capa, la pista (o el perfil), el campo y el valor. **No cambia ninguna prueba**: solo el fichero. Lo puro de la preparación (los comprobadores de la ruta, el valor por defecto de la cota de partida
y la geometría) sigue en ``test_road_prepare`` del «verde», de donde se importan la ayuda del proyecto (:class:`PrepareCase`), las constantes y ``request``/``drive``, que usan además los hitos
``milestone_road_*`` y las pruebas de las pistas del «verde»; lo que cambia el proyecto (una pista hecha antes, un sector sin búsqueda, una versión cerrada, una plataforma de destino) es de
``milestone_road_prepare``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from tests.support import road_data as rd
from tests.unit.design.test_road_prepare import (
    CODE,
    EMPTY,
    FINE,
    GRID,
    HOLLOW,
    KEY,
    NARROW,
    PROFILE,
    PrepareCase,
    RAMP,
    ROUTE_FIELDS,
    absolute,
    entities,
    entity_store,
    gis,
    provenance,
    request,
    road_model,
    road_section,
    road_store,
    versions_model,
)


class RoadPrepareTest(PrepareCase):
    """RF-017-01 a RF-017-06, RF-015-03, RF-015-06, RF-015-08: preparar y rechazar sobre el proyecto (una sola copia: ninguna prueba de la clase cambia el proyecto), siempre **sin
    escribir nada**."""

    # --- Lo que se lee (RF-017-01, RF-017-02, RF-015-03, RF-015-06) ---

    def test_a_trace_road_is_prepared_without_writing(self) -> None:
        """RF-017-01, RF-017-02, RF-017-06, RF-015-03, RF-015-06: la capa de puntos, la rampa, el código ``RDW-001``, el perfil de V01, la rejilla y las máscaras de V01 dejan un
        ``RoadJob`` con todo lo leído (la superficie bit a bit; el origen y el destino en absolutas float64; el perfil y los nueve parámetros de la ruta; lo intocable, el bit
        ``UNTOUCHABLE`` de las máscaras) y la ``OperationStart`` de ``des.road`` con sus ajustes, entradas (la capa con su papel, la partida y las máscaras) y parámetros; **nada se
        escribe**, ni la capa de origen ni la partida cambian, y la pista no declara nada (no lleva ``protect``)."""
        asked = request()
        before = self.state()
        prepared = self.prepare(asked)
        self.assertEqual(self.state(), before)
        self.assertEqual((prepared.code, prepared.op_type, prepared.existing, prepared.version.uid), (CODE, provenance.ROAD, False, self.v1.uid))
        self.assertEqual((prepared.start_surface, prepared.layer, prepared.supports, prepared.profile.code), (RAMP, rd.POINTS_LAYER, (), PROFILE))
        job = prepared.job
        self.assertIs(job.request.mode, road_model.RoadMode.TRACE)
        self.assertEqual((job.code, job.grid), (CODE, GRID))
        np.testing.assert_array_equal(job.start, rd.ramp_terrain(GRID))
        self.assertEqual((job.geometry.origin, job.geometry.destination), (absolute(rd.RAMP_ORIGIN), absolute(rd.RAMP_DESTINATION)))
        self.assertEqual(job.route, road_model.RouteParams(**{field: getattr(rd.ROUTE, field) for field in ROUTE_FIELDS}))
        self.assertEqual((job.profile.max_gradient_pct, job.profile.vehicle_width_m, job.profile.min_radius_m), (10.0, 3.5, 12.0))
        self.assertTrue(job.cut_allowed.any() and job.fill_allowed.any())
        wall = (self.masks_v1.classes & np.uint16(64)) != 0
        self.assertTrue(wall.any(), "la cantera de la 014 tiene un intocable (la torre)")
        np.testing.assert_array_equal(job.untouchable, wall)
        self.assertIsNone(job.avoid_weight)
        self.assertNotIn("protect", prepared.values)
        self.assertNotIn("guard_m", prepared.values)
        start = prepared.start
        self.assertEqual((start.op_type, start.name, start.version_uid), (provenance.ROAD, "Pista de la rampa", self.v1.uid))
        self.assertEqual(start.settings, {"name": "Pista de la rampa", "code": CODE, "fields": {"name_field": "nombre"}})
        used = {(use.item, str(use.role)) for use in start.inputs}
        self.assertIn((rd.POINTS_LAYER, provenance.ENTITY_LAYER_ROLE), used)
        self.assertIn((RAMP, provenance.SURFACE_ROLE), used)
        self.assertTrue({(use.item, str(use.role)) for use in self.masks_v1.uses()} <= used)
        self.assertIn(f"{KEY}origin", start.params)
        self.assertIn("des.roadprofile.pista_principal.max_gradient_pct", start.params)
        self.assertNotIn(f"{KEY}protect", start.params)

    def test_the_start_surface_and_the_layer_are_inputs_and_unchanged(self) -> None:
        """RF-017-01, RF-017-06: la capa de origen y la superficie de partida son entradas con su hash y la preparación no los toca (los hashes de los datos del proyecto son los de antes)."""
        before = {row[0]: row[2] for row in self.query("SELECT name, status, content_sha256 FROM gb_dataset WHERE name IN (?, ?)", rd.POINTS_LAYER, RAMP)}
        prepared = self.prepare(request())
        after = {row[0]: row[2] for row in self.query("SELECT name, status, content_sha256 FROM gb_dataset WHERE name IN (?, ?)", rd.POINTS_LAYER, RAMP)}
        self.assertEqual(before, after)
        self.assertEqual(len(before), 2)
        self.assertEqual(set(prepared.start.seen.values()) >= set(before.values()), True)

    def test_levels_default_to_the_terrain_with_their_origin(self) -> None:
        """RF-017-02, D-13: sin cotas de inicio y de fin, son las de la superficie de partida en el origen y en el destino (la interpolación bilineal de la 011) y su fila de parámetros
        dice de dónde salen (``algorithm``, la superficie y el punto); las que da el usuario mandan, con su procedencia de persona."""
        terrain = rd.ramp_terrain(GRID)
        prepared = self.prepare(request())
        for rows_key, point, level in (("start_level_m", rd.RAMP_ORIGIN, prepared.job.start_level_m), ("end_level_m", rd.RAMP_DESTINATION, prepared.job.end_level_m)):
            x, y = absolute(point)
            expected = float(road_section.sample_terrain(terrain, GRID, np.array([x]), np.array([y]))[0])
            self.assertAlmostEqual(level, expected, places=9, msg=rows_key)
        rows = {row.param: row for row in prepared.rows}
        for name in ("start_level_m", "end_level_m"):
            self.assertEqual(rows[name].source_kind, "algorithm", name)
            self.assertIn(RAMP, rows[name].source)
        given = self.prepare(request(start_level_m=101.0, end_level_m=109.0))
        self.assertEqual((given.job.start_level_m, given.job.end_level_m), (101.0, 109.0))
        rows = {row.param: row for row in given.rows}
        self.assertEqual((rows["start_level_m"].value, rows["start_level_m"].source_kind, rows["end_level_m"].value), (101.0, "person", 109.0))
        self.assertEqual(rows["name"].value, "Pista de la rampa")
        self.assertTrue(all(row.key.startswith(KEY) for row in given.rows))

    def test_the_rows_carry_every_parameter_of_the_dialog(self) -> None:
        """RF-017-01, RF-015-08: las filas de los parámetros de la entidad son **todas** las que lee la operación (``road_params``), cada una con su valor y su origen; sin ellas,
        ``begin_operation`` crearía la del valor por defecto en el proyecto (trampa de la T04). El presupuesto de estados lleva el valor por defecto de su parámetro."""
        prepared = self.prepare(request())
        keys = {row.key for row in prepared.rows}
        read = {key for key in prepared.start.params if key.startswith(KEY)}
        self.assertEqual(keys & read, read, "falta la fila de algún parámetro que lee la operación")
        values = {row.param: row.value for row in prepared.rows}
        for field in ROUTE_FIELDS:
            self.assertEqual(values[field], getattr(rd.ROUTE, field), field)
        self.assertEqual((values["mode"], values["layer"], values["profile"], values["start"], values["origin"], values["destination"]),
                         ("trace", rd.POINTS_LAYER, PROFILE, RAMP, "Origen rampa", "Destino rampa"))
        default = self.prepare(request(search_budget=None))
        row = next(item for item in default.rows if item.param == "search_budget")
        self.assertEqual((row.value, row.source_kind), (5_000_000, "algorithm"))

    def test_a_point_is_chosen_by_its_fid_or_its_name(self) -> None:
        """RF-017-02: un punto de la capa se elige por su nombre o por su ``fid`` (como texto): los dos dan el mismo origen; el ``fid`` de «Origen rampa» es el 1."""
        by_name = self.prepare(request())
        by_fid = self.prepare(request(origin="1", destination="2"))
        self.assertEqual((by_fid.job.geometry.origin, by_fid.job.geometry.destination), (by_name.job.geometry.origin, by_name.job.geometry.destination))

    def test_a_level_destination_reads_its_zone(self) -> None:
        """RF-017-02, RF-017-04: el destino por cota (la rampa, D-4) toma la cota, la tolerancia y la zona (un polígono de una capa del proyecto, elegido por su nombre o por su
        ``fid`` tras los dos puntos) y el trabajo lleva un ``LevelDestination`` con la zona en absolutas; los parámetros del destino son filas de la entidad."""
        asked = request(destination=None, dest_level_m=rd.PIT_FLOOR_M, dest_tol_m=0.5, dest_zone=f"{rd.ZONES_LAYER}:Zona del fondo", origin="Origen tajo", surface=rd.dataset_of("tajo"))
        prepared = self.prepare(asked)
        destination = prepared.job.geometry.destination
        self.assertIsInstance(destination, road_model.LevelDestination)
        self.assertEqual((destination.level_m, destination.tolerance_m), (rd.PIT_FLOOR_M, 0.5))
        left, bottom, right, top = rd.ZONES[0][1]
        ring = destination.zone[0][0]
        np.testing.assert_allclose(sorted({float(x) for x in ring[:, 0]}), [rd.absolute([(left, 0.0)], GRID)[0][0], rd.absolute([(right, 0.0)], GRID)[0][0]])
        values = {row.param: row.value for row in prepared.rows}
        self.assertEqual((values["dest_level_m"], values["dest_tol_m"], values["dest_zone"]), (rd.PIT_FLOOR_M, 0.5, f"{rd.ZONES_LAYER}:Zona del fondo"))
        self.assertNotIn("destination", values)
        by_fid = self.prepare(request(destination=None, dest_level_m=rd.PIT_FLOOR_M, dest_tol_m=0.5, dest_zone=f"{rd.ZONES_LAYER}:1", origin="Origen tajo", surface=rd.dataset_of("tajo")))
        self.assertEqual(by_fid.job.geometry.destination.zone[0][0].tolist(), ring.tolist())

    def test_a_line_mode_reads_its_line_untouched(self) -> None:
        """RF-017-02, RF-017-01: «sobre un eje» lee la línea de su capa (una parte, X e Y absolutas float64) y **no** lleva origen, destino ni parámetros de la ruta (P-14); la capa
        no cambia."""
        prepared = self.prepare(request(mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("escalon")))
        job = prepared.job
        self.assertIs(job.request.mode, road_model.RoadMode.ON_AXIS)
        np.testing.assert_array_equal(job.geometry.line, rd.absolute(rd.STEP_AXIS, GRID))
        self.assertIsNone(job.route)
        self.assertNotIn("mesh_m", {row.param for row in prepared.rows})
        self.assertIn("feature", {row.param for row in prepared.rows})
        self.assertNotIn(f"{KEY}mesh_m", prepared.start.params)

    # --- Los rechazos de RF-017-04 (sin escribir nada) ---

    def test_an_origin_equal_to_the_destination(self) -> None:
        """RF-017-04: el origen y el destino son el mismo punto: se rechaza nombrando la capa, la pista, el campo y el valor, sin elegir otro por ella."""
        error = self.refused(request(destination="Origen rampa"), "des.road_origin_is_destination")
        self.assertEqual((error.values["layer"], error.values["entity"], error.values["field"], error.values["value"]),
                         (rd.POINTS_LAYER, "Pista de la rampa", f"{KEY}destination", "Origen rampa"))
        self.assertIn("Pista de la rampa", error.text)
        self.assertIn(rd.POINTS_LAYER, error.text)

    def test_a_point_outside_the_grid_or_without_data(self) -> None:
        """RF-017-04, RF-015-09: un punto fuera de la rejilla y uno sin dato en la superficie de partida se rechazan con su lugar; también un origen en el hueco de una superficie."""
        error = self.refused(request(origin="Punto fuera de la rejilla"), "des.road_point_outside_grid")
        self.assertEqual((error.values["layer"], error.values["field"], error.values["value"]), (rd.POINTS_LAYER, f"{KEY}origin", "Punto fuera de la rejilla"))
        self.assertEqual((error.values["x"], error.values["y"]), tuple(round(v, 2) for v in absolute((-20.0, 200.0))))
        error = self.refused(request(surface=HOLLOW), "des.road_point_no_data")
        self.assertEqual((error.values["field"], error.values["value"], error.values["surface"]), (f"{KEY}origin", "Origen rampa", HOLLOW))
        self.assertIn(HOLLOW, error.text)

    def test_a_layer_of_another_kind_or_an_unknown_point(self) -> None:
        """RF-017-04: «trazar» pide una capa de puntos y los modos de línea una de líneas; un punto que la capa no tiene se rechaza con su capa y su valor."""
        error = self.refused(request(layer=rd.AXES_LAYER), "des.road_layer_kind")
        self.assertEqual((error.values["layer"], error.values["entity"]), (rd.AXES_LAYER, "Pista de la rampa"))
        self.refused(request(mode="on_axis", layer=rd.POINTS_LAYER), "des.road_layer_kind")
        error = self.refused(request(origin="No existe"), "des.entity_feature_unknown")
        self.assertEqual((error.values["layer"], error.values["value"]), (rd.POINTS_LAYER, "No existe"))

    def test_a_line_that_is_not_valid(self) -> None:
        """RF-017-04: una línea que se corta a sí misma, sin longitud, de varias partes o con un vértice repetido se rechaza nombrando la capa, la pista, el campo y el valor (y el
        lugar o el vértice); una línea sin Z en el modo «eje 3D», con el texto de «sin Z» (T23-a); la línea no se corrige."""
        escalon = rd.dataset_of("escalon")
        cases = {"Eje que se corta": "des.road_line_self_intersects", "Eje de longitud cero": "des.road_line_no_length", "Eje de dos partes": "des.road_line_multipart",
                 "Eje con vértice repetido": "des.road_line_repeated_vertex"}
        for feature, code in cases.items():
            with self.subTest(feature=feature):
                error = self.refused(request(mode="on_axis", layer=rd.AXES_LAYER, surface=escalon, feature=feature), code)
                self.assertEqual((error.values["layer"], error.values["entity"], error.values["field"], error.values["value"]),
                                 (rd.AXES_LAYER, "Pista de la rampa", f"{KEY}feature", feature))
        error = self.refused(request(mode="axis_3d", layer=rd.AXES_LAYER, surface=escalon), "des.road_line_no_z")
        self.assertEqual(error.values["layer"], rd.AXES_LAYER)

    def test_the_profile(self) -> None:
        """RF-017-04, RF-017-07: un perfil que no existe (con los que sí), uno sin valores y uno con un radio mínimo menor que la semianchura se rechazan nombrando el perfil, el campo y
        el valor; el rechazo es de la pista que lo nombra y no escribe nada."""
        error = self.refused(request(profile="no_existe"), "des.road_profile_unknown")
        self.assertEqual((error.values["layer"], error.values["field"], error.values["value"]), (rd.POINTS_LAYER, f"{KEY}profile", "no_existe"))
        self.assertIn("PISTA_PRINCIPAL", error.text)
        error = self.refused(request(profile=EMPTY), "des.road_profile_value_missing")
        self.assertEqual(error.values["profile"], "VACIO")
        error = self.refused(request(profile=NARROW), "des.road_profile_radius_narrow")
        self.assertEqual((error.values["profile"], error.values["value"]), ("ANGOSTO", 3.0))

    def test_levels_out_of_the_terrain(self) -> None:
        """RF-017-04: una cota de inicio o de fin fuera de las del terreno ± 1.000 m se rechaza nombrando el campo, el valor y las cotas del terreno, sin elegir otra."""
        error = self.refused(request(start_level_m=5000.0), "des.road_level_range")
        self.assertEqual((error.values["layer"], error.values["field"], error.values["value"], error.values["limit"]), (rd.POINTS_LAYER, f"{KEY}start_level_m", 5000.0, 1000.0))
        error = self.refused(request(end_level_m=-2000.0), "des.road_level_range")
        self.assertEqual(error.values["field"], f"{KEY}end_level_m")
        self.prepare(request(start_level_m=900.0, end_level_m=-800.0))  # dentro de ± 1.000 m

    def test_a_destination_level_out_of_its_zone(self) -> None:
        """RF-017-04: un destino por cota que el terreno de su zona no alcanza se rechaza con las cotas de la zona; una zona sin ningún nodo que se pise (sin dato), también."""
        tajo = rd.dataset_of("tajo")
        error = self.refused(request(destination=None, origin="Origen tajo", surface=tajo, dest_level_m=300.0, dest_tol_m=0.5, dest_zone=f"{rd.ZONES_LAYER}:Zona del fondo"),
                             "des.road_dest_level_out_of_zone")
        self.assertEqual((error.values["field"], error.values["value"], error.values["zone"]), (f"{KEY}dest_level_m", 300.0, f"{rd.ZONES_LAYER}:Zona del fondo"))
        error = self.refused(request(destination=None, origin="Origen ladera", surface=HOLLOW, dest_level_m=100.0, dest_tol_m=0.5, dest_zone=f"{rd.ZONES_LAYER}:Zona del fondo"),
                             "des.road_dest_zone_empty")
        self.assertEqual(error.values["layer"], rd.POINTS_LAYER)

    def test_the_mesh_of_the_route_is_a_multiple_of_the_step(self) -> None:
        """RF-017-04, D-10: una malla de la ruta que no es un múltiplo entero del paso del proyecto se rechaza con su paso, antes de leer una celda de la ruta."""
        error = self.refused(request(mesh_m=3.0), "des.road_mesh_not_multiple")
        self.assertEqual((error.values["field"], error.values["value"], error.values["step"]), (f"{KEY}mesh_m", 3.0, 2.0))

    def test_a_parameter_without_a_value_or_out_of_range(self) -> None:
        """RF-015-08: un parámetro de la ruta sin valor, sin valor por defecto, se rechaza (sin elegir uno por la persona) y uno fuera de su rango también, nombrando capa, pista, campo y
        valor; sin partida ni perfil tampoco hay valor."""
        for field in ("mesh_m", "turn_m", "arrival_tol_m"):  # una de cada clase: la malla, el movimiento de tierras y la llegada (la tabla entera es la de ``road_values``)
            with self.subTest(field=field):
                error = self.refused(request(**{field: None}), "des.entity_param_missing")
                self.assertEqual((error.values["layer"], error.values["entity"], error.values["field"]), (rd.POINTS_LAYER, "Pista de la rampa", f"{KEY}{field}"))
        error = self.refused(request(level_step_m=-1.0), "des.entity_param_range")
        self.assertEqual((error.values["field"], error.values["value"]), (f"{KEY}level_step_m", -1.0))
        self.refused(request(origin=None), "des.entity_param_missing")
        self.refused(request(destination=None), "des.entity_param_missing")

    def test_the_start_surface_and_the_version(self) -> None:
        """RF-017-05, RF-009-21, RF-011-02: una partida que no existe, una en otra rejilla y una versión que no se pide se rechazan sin escribir nada."""
        self.refused(request(surface="gis_dtm_no_existe"), "gis.dataset_unknown")
        self.refused(request(surface=FINE), "des.surface_mismatch")
        with self.assertRaises(versions_model.VersionError) as caught:
            road_store.prepare_road(self.project, request(), version=None, masks=self.masks_v1)
        self.assertEqual(caught.exception.code, "core.version_required")

    def test_a_reference_to_a_road_or_an_entity_that_does_not_exist(self) -> None:
        """RF-017-03, RF-015-15: el origen en el eje de una pista (``RDW-009@10``) o el destino en una entidad (``entity:PLT-009``) que la versión no tiene (o no está calculada) se rechaza
        con el texto de las dependencias declaradas, sin escribir nada."""
        error = self.refused(request(origin="RDW-009@10"), "des.entity_supports_unknown")
        self.assertEqual(error.values["target"], "RDW-009")
        error = self.refused(request(destination="entity:PLT-009"), "des.entity_supports_unknown")
        self.assertEqual(error.values["target"], "PLT-009")

    def test_an_origin_on_the_axis_of_another_road_is_a_declared_dependency(self) -> None:
        """RF-017-03, RF-015-15, D-16: el origen en el eje de otra pista (``RDW-001@100``) toma de sus estaciones su lugar y la cota de su rasante a esa abscisa (por defecto, la cota de
        inicio, con su origen anotado) y **registra la dependencia «se apoya en» declarada**: ``supports``, la fila ``supports`` de los parámetros (que la operación lee) y, como
        entradas, la superficie de esa pista (``supported_on``) y la tabla de su huella (``support_footprint``); una abscisa fuera del eje se rechaza con su longitud. La otra pista se
        sustituye aquí por una hecha a mano (la T21 las crea de verdad): el cálculo de la rasante y el lugar es el de ``axis_point_at``."""
        s = np.arange(0.0, 201.0, 10.0)
        local_x = rd.RAMP_ORIGIN[0] + s
        axis = np.column_stack([s, [absolute((x, rd.RAMP_AXIS_Y_M))[0] for x in local_x], [absolute((x, rd.RAMP_AXIS_Y_M))[1] for x in local_x],
                                100.0 + 0.04 * local_x, 104.0 + 0.04 * s])
        entry = SimpleNamespace(record=SimpleNamespace(name="Pista base", code="RDW-001"), operation_uid="op")
        listed = entity_store.EntitySurface("RDW-001", "des_psf_pista_base", "des_epr_pista_base", "des_epr_pista_base_v01", entities.EntityKind.ROAD, "op")
        before = self.state()
        with mock.patch.object(road_store, "_supportable", return_value=(entry, listed)), mock.patch.object(road_store, "_axis_stations", return_value=axis):
            prepared = self.prepare(request(origin="RDW-001@100", destination="Destino del ramal"), code="RDW-002")
            self.assertEqual(self.state(), before)
            self.assertEqual(prepared.supports, ("RDW-001",))
            self.assertEqual(prepared.job.geometry.origin, absolute((200.0, rd.RAMP_AXIS_Y_M)))
            self.assertAlmostEqual(prepared.job.start_level_m, 108.0, places=9)
            rows = {row.param: row for row in prepared.rows}
            self.assertEqual((rows["supports"].value, rows["supports"].source_kind), ("RDW-001", "algorithm"))
            self.assertIn("RDW-001", rows["start_level_m"].source)
            self.assertIn("100", rows["start_level_m"].source)
            used = {(use.item, str(use.role)) for use in prepared.start.inputs}
            self.assertIn(("des_psf_pista_base", provenance.SUPPORTED_ON_ROLE), used)
            self.assertIn(("des_epr_pista_base", provenance.SUPPORT_FOOTPRINT_ROLE), used)
            self.assertIn("des.road.rdw_002.supports", prepared.start.params)
            error = self.refused(request(origin="RDW-001@500", destination="Destino del ramal"), "des.road_origin_abscissa", code="RDW-002")
            self.assertEqual((error.values["field"], error.values["target"], error.values["length"]), ("des.road.rdw_002.origin", "RDW-001", 200.0))

    # --- La partida por defecto y la cadena (RF-017-05, D-3, D-16) ---

    def test_the_default_start(self) -> None:
        """RF-017-05, D-3: sin partida, la de explotación de una cantera de la 014 de la versión y, si no, la última de la cadena de entidades; con **una** sola candidata. V01 de las
        pruebas no tiene ninguna cantera ni entidad: sin candidata, el rechazo de RF-015-08 (no se elige una por la persona)."""
        found = road_store.default_start(self.project, self.v1)
        self.assertIsNone(found)
        error = self.refused(request(surface=""), "des.entity_param_missing")
        self.assertEqual(error.values["field"], f"{KEY}start")

    # --- Lo que no se pisa y el peso de «preferible no afectar» (RF-017-06) ---

    def test_what_the_masks_give_the_job(self) -> None:
        """RF-017-06: el corte y el relleno admitidos son los de la 012 (``compose.admitted_pair``) y el peso de las zonas «preferible no afectar» es el mayor de las que pisan cada
        celda, de 1 o más; ninguna zona, ningún peso."""
        masks = self.masks_v1
        self.assertIsNone(road_store.avoid_weight(masks))
        zone = np.zeros(GRID.shape, dtype=bool)
        zone[10:20, 30:40] = True
        other = np.zeros(GRID.shape, dtype=bool)
        other[15:25, 35:45] = True

        class FakeRuns:
            def __init__(self, mask: np.ndarray) -> None:
                self.found = mask

            def mask(self, shape: tuple[int, int]) -> np.ndarray:
                return self.found

        class FakeMasks:
            grid = GRID

            def avoid_weights(self) -> dict[str, Any]:
                return {"a": (FakeRuns(zone), 3.0), "b": (FakeRuns(other), 5.0), "c": (FakeRuns(zone), 0.5)}

        weight = road_store.avoid_weight(FakeMasks())
        self.assertEqual(weight.shape, GRID.shape)
        self.assertEqual((float(weight[12, 32]), float(weight[17, 37]), float(weight[22, 42]), float(weight[0, 0])), (3.0, 5.0, 5.0, 1.0))
        self.assertTrue(bool((weight >= 1.0).all()))


if __name__ == "__main__":
    unittest.main()
