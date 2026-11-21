# SPDX-License-Identifier: GPL-3.0-or-later
"""Recalcular y reproducir la pista, **sin proyecto** (spec 017, T22 (a); HU-017-1 y HU-017-2; RF-017-01, RF-017-02 y RF-017-03; RF-015-01, RF-015-02, RF-015-04 y RF-015-16; plan 017 §5.2.3, §5.3.2
y §5.7 P-5): lo que repiten el recálculo y la reproducción son funciones **puras** de lo guardado —la petición que salen de los ajustes y de los parámetros de la entidad, la geometría de origen que se
lee de la capa **congelada**, lo confirmado que se arrastra y los parámetros que anotó la operación—, y se prueban aquí sin abrir un proyecto. Con el proyecto (recalcular en orden, la obsolescencia
con su causa, reproducir un V01.r1 congelado bit a bit) es de ``milestone_road_recompute``.
"""

from __future__ import annotations

import contextlib
import sqlite3
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.test_road_prepare import CODE, GRID, KEY, PROFILE, RAMP, request

core_recompute = import_geoblender("core.provenance.recompute")
design_params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
reproduce_mod = import_geoblender("design.reproduce")
road_model = import_geoblender("design.road_model")
road_store = import_geoblender("design.road_store")
store = import_geoblender("design.store")
vector = import_geoblender("gis.vector")
versions_reproduce = import_geoblender("core.versions.reproduce")

DesignError = messages.DesignError


def values_of(asked: Any, **levels: Any) -> dict[str, Any]:
    """Los valores de la entidad de ``asked`` por su último segmento, como los resuelve la 008 y los lee ``entity_parameters``: los de ``road_values`` (la petición con lo que se resolvió)."""
    return road_store.road_values(asked, CODE, start_ref=asked.start, **levels)


def roundtrip(asked: Any, **levels: Any) -> Any:
    """La petición que repiten los ajustes de la operación y los valores de la entidad de ``asked`` (el recálculo y la reproducción)."""
    return provenance.road_request(provenance.road_settings(asked, CODE), values_of(asked, **levels))


class RoadRequestTest(unittest.TestCase):
    """RF-017-01, RF-017-02, RF-015-01, RF-015-02: ``provenance.road_request``, la inversa de ``road_settings`` junto con los valores de la entidad."""

    def test_a_the_three_modes_and_the_level_destination_come_back_as_they_were_asked(self) -> None:
        """RF-017-02, RF-015-01: la petición que se rehace de los ajustes y de los valores de la entidad es **la misma** que se pidió, en los tres modos de la pista y con el destino por cota
        (la rampa): la capa y su campo de nombres, el perfil, la partida, el origen y el destino, las cotas, el apoyo y los nueve parámetros de la ruta; lo que el modo no usa queda en ``None``."""
        cases = {
            "trazar": (request(), {"start_level_m": 104.0, "end_level_m": 112.0}),
            "sobre un eje": (request("Pista sobre un eje", mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("escalon"), support=RAMP), {"start_level_m": 0.0, "end_level_m": 6.0}),
            "a una cota": (request("Pista a una cota", destination=None, dest_level_m=rd.PIT_FLOOR_M, dest_tol_m=0.5, dest_zone=f"{rd.ZONES_LAYER}:Zona del fondo", origin="Origen tajo",
                                   surface=rd.dataset_of("tajo")), {"start_level_m": 141.0}),
            "con el eje de otra pista": (request("Ramal", origin="RDW-001@100", destination="Destino del ramal", surface="entity:RDW-001"), {"start_level_m": 108.0, "end_level_m": 108.0}),
        }
        for label, (asked, levels) in cases.items():
            with self.subTest(mode=label):
                found = roundtrip(asked, **levels)
                self.assertEqual(found, road_model.RoadRequest(**{**{name: getattr(asked, name) for name in asked.__slots__}, **levels}))
                self.assertIsInstance(found, road_model.RoadRequest)
        trace = roundtrip(cases["trazar"][0], **cases["trazar"][1])
        self.assertEqual((trace.layer, trace.fields.name_field, trace.origin, trace.destination, trace.mesh_m, trace.search_budget), (rd.POINTS_LAYER, "nombre", "Origen rampa", "Destino rampa", rd.ROUTE.mesh_m, 5_000_000))
        axis = roundtrip(*cases["sobre un eje"][:1], **cases["sobre un eje"][1])
        self.assertEqual((axis.feature, axis.support, axis.origin, axis.destination, axis.mesh_m), ("Eje de 200 m", RAMP, None, None, None))

    def test_b_the_name_and_the_fields_are_those_of_the_settings_and_the_rest_those_of_the_entity(self) -> None:
        """RF-015-01, RF-015-02: renombrar la entidad cambia su parámetro ``name``, no el de la operación (como la detección de acopios): el nombre y el campo de los nombres salen de los
        **ajustes**; la capa, la geometría, la partida y lo demás, de los **parámetros** (cambiar uno repite la operación con el nuevo)."""
        asked = request()
        settings = provenance.road_settings(asked, CODE)
        values = {**values_of(asked, start_level_m=104.0), "name": "Otro nombre", "layer": "gis_fea_otra", "start": "gis_dtm_otra", "mesh_m": 8.0}
        found = provenance.road_request(settings, values)
        self.assertEqual((found.name, found.fields.name_field, found.layer, found.start, found.mesh_m), (asked.name, "nombre", "gis_fea_otra", "gis_dtm_otra", 8.0))
        no_field = provenance.road_request({**settings, "fields": {"name_field": None}}, values_of(asked))
        self.assertIsNone(no_field.fields.name_field)

    def test_c_what_is_not_a_road_is_refused_naming_the_field(self) -> None:
        """RF-015-01: unos ajustes o unos valores que no son los de una pista se rechazan (``ValueError``, un error del programa) nombrando el campo: sin nombre, sin ``fields``, un valor que no
        es de una pista, sin capa, sin modo, sin perfil o sin partida, un texto que no es texto y un número que no es finito."""
        asked = request()
        settings, values = provenance.road_settings(asked, CODE), values_of(asked)
        refused = [
            ("«name»", {**settings, "name": ""}, values), ("«fields»", {k: v for k, v in settings.items() if k != "fields"}, values), ("«bogus»", settings, {**values, "bogus": 1}),
            ("«layer»", settings, {k: v for k, v in values.items() if k != "layer"}), ("«mode»", settings, {k: v for k, v in values.items() if k != "mode"}),
            ("«profile»", settings, {k: v for k, v in values.items() if k != "profile"}), ("«start»", settings, {k: v for k, v in values.items() if k != "start"}),
            ("«origin»", settings, {**values, "origin": 7}), ("«mesh_m»", settings, {**values, "mesh_m": float("nan")}), ("«search_budget»", settings, {**values, "search_budget": 1.5}),
            ("diccionario", ["no", "es", "un", "diccionario"], values)]
        for field, bad_settings, bad_values in refused:
            with self.subTest(field=field), self.assertRaises(ValueError) as caught:
                provenance.road_request(bad_settings, bad_values)
            self.assertIn(field.strip("«»"), str(caught.exception))
        with self.assertRaises(ValueError):
            provenance.road_request(settings, ["no", "un", "diccionario"])  # type: ignore[arg-type]


class ConfirmedTest(unittest.TestCase):
    """RF-017-17, RF-017-22, RF-015-02: lo que la persona confirmó al crear, y hasta dónde lo reutiliza un recálculo (que **no confirma por ella**)."""

    MEAN = road_store.RoadConfirmed("Samuel (IMGA)", "2026-11-21T09:00:00Z", mean_pct=10.5, mean_limit_pct=10.0, reason="Opción A15 de la propiedad (N-15)")
    CARRIAGEWAY = road_store.RoadConfirmed("Samuel (IMGA)", "2026-11-21T09:00:00Z", carriageway_m2=40.0, carriageway_difference_m=0.6)

    def test_a_a_mean_up_to_the_confirmed_one_is_covered(self) -> None:
        """RF-017-17: una pendiente media que no pasa de la confirmada (con el redondeo de la última cifra) entra en lo confirmado; una mayor, no; sin nada confirmado de la media, nada entra."""
        self.assertTrue(self.MEAN.covers_mean(10.5))
        self.assertTrue(self.MEAN.covers_mean(10.2))
        self.assertTrue(self.MEAN.covers_mean(10.5 * (1.0 + 1e-12)))
        self.assertFalse(self.MEAN.covers_mean(10.51))
        self.assertFalse(self.CARRIAGEWAY.covers_mean(9.0))

    def test_b_a_carriageway_covers_its_area_and_its_difference(self) -> None:
        """RF-017-22: la calzada fuera de su rasante entra en lo confirmado si **ni su área ni su diferencia máxima** pasan de lo que se confirmó; con una sola de las dos que pase, no."""
        self.assertTrue(self.CARRIAGEWAY.covers_carriageway(40.0, 0.6))
        self.assertTrue(self.CARRIAGEWAY.covers_carriageway(12.0, 0.2))
        self.assertFalse(self.CARRIAGEWAY.covers_carriageway(40.5, 0.6))
        self.assertFalse(self.CARRIAGEWAY.covers_carriageway(12.0, 0.61))
        self.assertTrue(self.CARRIAGEWAY.covers_carriageway(40.0, 0.6004), "la diferencia se anota redondeada al milímetro: lo mismo sin cambiar nada se cubre")
        self.assertFalse(self.MEAN.covers_carriageway(1.0, 0.1))

    def test_c_what_the_settings_keep_comes_back(self) -> None:
        """RF-015-02: ``confirmed_of`` lee de vuelta lo que anotan ``RoadConfirmed.settings`` (quién, cuándo, el motivo, la media y la calzada), que es lo que un recálculo arrastra tal cual
        a la operación nueva."""
        both = road_store.RoadConfirmed("Samuel (IMGA)", "2026-11-21T09:00:00Z", 10.5, 10.0, "Motivo", 40.0, 0.6)
        found = road_store.confirmed_of({road_store.CONFIRMED: both.settings()})
        self.assertEqual(found, both)
        self.assertEqual(found.settings(), both.settings())


class LevelFollowTest(unittest.TestCase):
    """RF-017-03, D-13, RF-015-01 (T24b): al **recalcular**, las cotas de inicio y de fin cuyo origen anotado en su fila es el del algoritmo se vuelven a tomar de lo que dijo su origen (la superficie de
    partida en el punto, el eje de otra pista en esa abscisa o la superficie de la entidad de destino en ese punto), y las que no, no se tocan: **sin proyecto**, la decisión es una función pura de lo
    que dice la fila, de lo pedido y de lo que da hoy el origen. Con el proyecto (la plataforma de destino cambiada, el eje de otra pista, el resumen y reproducir lo congelado) es de ``milestone_road_chain``."""

    END = design_params.RoadParam.END_LEVEL
    START = design_params.RoadParam.START_LEVEL
    TARGET = "«P1» (PLT-001)"
    TEXT = "cota de la superficie de la entidad «P1» (PLT-001) en el destino (x = 320.00 m, y = 200.00 m)"
    DERIVED = road_store.DerivedLevel(112.4, TEXT, TARGET)

    def test_a_a_level_derived_from_its_origin_is_taken_again_when_the_origin_changes(self) -> None:
        """RF-017-03, D-13: con el origen anotado «algoritmo» (la cota salió de la superficie de la entidad de destino) y una cota nueva en ese origen, la pista **toma la nueva** con su origen y su lugar, y
        lo dice (:class:`~design.road_store.LevelFollow`: la cota, la de antes, la de ahora y de dónde)."""
        found = road_store.resolve_level(self.END, 112.0, "algorithm", self.DERIVED)
        self.assertEqual(found.value_m, 112.4)
        self.assertEqual(found.origin, (self.TEXT, "algorithm"))
        self.assertEqual(found.follow, road_store.LevelFollow(self.END, 112.0, 112.4, self.TEXT, self.TARGET))
        start = road_store.resolve_level(self.START, 104.0, "algorithm", road_store.DerivedLevel(104.5, "texto", "«RDW-001»"))
        self.assertEqual((start.value_m, start.follow.param, start.follow.old_m, start.follow.new_m), (104.5, self.START, 104.0, 104.5))

    def test_b_the_same_level_changes_nothing_and_says_nothing(self) -> None:
        """RF-015-01 (un recálculo sin cambios no escribe ningún parámetro): si el origen da la misma cota (hasta el ruido de la última cifra), el valor sigue siendo el de la fila, con su origen,
        y no hay nada que decir ni que escribir."""
        for same in (112.0, 112.0 + 1e-12):
            with self.subTest(same=same):
                found = road_store.resolve_level(self.END, 112.0, "algorithm", road_store.DerivedLevel(same, self.TEXT, self.TARGET))
                self.assertIsNone(found.follow)
                self.assertEqual((found.value_m, found.origin), (112.0, (self.TEXT, "algorithm")))

    def test_c_a_level_that_is_not_of_the_algorithm_is_kept(self) -> None:
        """RF-017-03, D-13: la cota **que dio la persona** (origen «person») no se cambia por mucho que cambie el origen; tampoco la que anotó un documento, una norma o una cifra adoptada (no son del
        algoritmo: solo se vuelve a derivar lo que el código derivó)."""
        for kind in ("person", "document", "standard", "operation"):
            with self.subTest(kind=kind):
                found = road_store.resolve_level(self.END, 111.0, kind, self.DERIVED)
                self.assertEqual((found.value_m, found.origin, found.follow), (111.0, None, None))

    def test_d_without_an_origin_to_take_it_from_the_stored_level_stays(self) -> None:
        """RF-017-02, D-4, RF-017-18: sin origen que dé la cota hoy (el destino por cota de la rampa, la cota de «eje 3D») la de la fila se conserva aunque sea «algoritmo»; y sin cota en la fila, **al
        crear**, sale del origen con su procedencia (como siempre) sin nada que decir."""
        kept = road_store.resolve_level(self.END, 112.0, "algorithm", None)
        self.assertEqual((kept.value_m, kept.origin, kept.follow), (112.0, None, None))
        first = road_store.resolve_level(self.END, None, None, self.DERIVED)
        self.assertEqual((first.value_m, first.origin, first.follow), (112.4, (self.TEXT, "algorithm"), None))
        none = road_store.resolve_level(self.END, None, None, None)
        self.assertEqual((none.value_m, none.origin, none.follow), (None, None, None))

    def test_e_the_notice_says_the_change_in_both_languages_to_the_centimetre(self) -> None:
        """RF-017-03, D-13: el aviso del resumen dice qué cota (inicio o fin), de cuánto a cuánto (a la centésima: un cambio de 0,04 m no se lee «112,0 m a 112,0 m») y de dónde se vuelve a tomar, en español
        y en inglés, sin marcadores sin sustituir."""
        notice = road_store.resolve_level(self.END, 112.0, "algorithm", self.DERIVED).follow.notice("Pista a P1")
        self.assertEqual((notice.code, notice.severity), ("des.road_end_level_followed", "note"))
        self.assertEqual(dict(notice.values), {"entity": "Pista a P1", "old": 112.0, "new": 112.4, "source": self.TARGET})
        self.assertIn("su cota de fin pasa de 112,00 m a 112,40 m", notice.text("es"))
        self.assertIn(self.TARGET, notice.text("es"))
        self.assertIn("its end level changes from 112.00 m to 112.40 m", notice.text("en"))
        close = road_store.LevelFollow(self.START, 104.0, 104.04, "texto", "«RDW-001»").notice("Ramal")
        self.assertEqual(close.code, "des.road_start_level_followed")
        self.assertIn("su cota de inicio pasa de 104,00 m a 104,04 m", close.text("es"))
        self.assertIn("its start level changes from 104.00 m to 104.04 m", close.text("en"))
        for language in ("es", "en"):
            self.assertNotIn("{", notice.text(language))


class HandEditedLevelTest(unittest.TestCase):
    """RF-017-03, D-13, RF-015-01, RF-015-08 (T29c): quien **cambia a mano** la cota de inicio o de fin de una pista con «Cambiar parámetro…» la deja **suya** (``source_kind = person``, con su origen
    anotado), de modo que recalcular no la vuelve a derivar (T24b: solo se vuelve a derivar lo que anotó el algoritmo). **Sin proyecto**: lo que cambia es una función pura de la clave, de la fila y de
    lo que cambió la persona (:func:`~design.road_store.person_level_changes`); con el proyecto, la orden y recalcular son de ``milestone_road_chain.HandEditedLevelTest`` y de ``test_road_ops``."""

    END = "des.road.rdw_001.end_level_m"
    START = "des.road.rdw_001.start_level_m"
    ALGORITHM = SimpleNamespace(source_kind="algorithm")
    ASKED = {"reason": "Se da la cota", "value": 111.9}

    def test_a_a_derived_level_the_person_edits_becomes_the_persons_with_its_origin(self) -> None:
        """RF-017-03, D-13: la cota de inicio o de fin anotada por el algoritmo (la que derivó el código de la plataforma de destino o del eje de otra pista) cuyo **valor** cambia la persona pasa a
        ``person`` y a un origen que lo dice (la orden y la pista, no el texto del algoritmo); el valor y el motivo son los suyos y no se añade nada más."""
        for key in (self.END, self.START):
            with self.subTest(key=key):
                changes = road_store.person_level_changes(key, self.ALGORITHM, dict(self.ASKED), entity="Pista a P1")
                self.assertEqual(changes["source_kind"], "person")
                self.assertEqual(changes["source"], "orden «Cambiar parámetro…», pista «Pista a P1»")
                self.assertEqual((changes["value"], changes["reason"]), (111.9, "Se da la cota"))
                self.assertEqual(set(changes), {"value", "reason", "source_kind", "source"})
        self.assertEqual(self.ASKED, {"reason": "Se da la cota", "value": 111.9}, "no cambia lo que se le da")
        anonymous = road_store.person_level_changes(self.END, self.ALGORITHM, dict(self.ASKED))
        self.assertEqual((anonymous["source_kind"], anonymous["source"]), ("person", "orden «Cambiar parámetro…»"), "sin el nombre de la pista, solo la orden")

    def test_b_what_the_person_says_or_what_is_not_the_algorithms_is_kept(self) -> None:
        """RF-017-03, D-13: lo que **no** es del algoritmo se conserva —la cota que ya dio la persona, la que anotó un documento, una norma o una cifra adoptada: no las derivó el código— y lo que la persona
        dice **ella** (otra clase de origen, otro texto de origen) manda; también se conserva la adopción de una cifra calculada."""
        for kind in ("person", "document", "standard", "operation"):
            with self.subTest(kind=kind):
                changes = road_store.person_level_changes(self.END, SimpleNamespace(source_kind=kind), dict(self.ASKED), entity="Pista a P1")
                self.assertEqual(changes, self.ASKED, "ni la clase ni el origen cambian")
        said = {**self.ASKED, "source_kind": "document", "source": "Proyecto de la pista, plano 7"}
        self.assertEqual(road_store.person_level_changes(self.END, self.ALGORITHM, dict(said), entity="Pista a P1"), said, "lo que dice la persona manda")
        own = road_store.person_level_changes(self.END, self.ALGORITHM, {**self.ASKED, "source": "Cota del proyecto"}, entity="Pista a P1")
        self.assertEqual((own["source_kind"], own["source"]), ("person", "Cota del proyecto"), "el origen que escribió se respeta")
        figure = {"reason": "Se adopta", "from_figure": "uid-de-una-cifra"}
        self.assertEqual(road_store.person_level_changes(self.END, self.ALGORITHM, dict(figure)), figure)

    def test_c_only_the_two_levels_of_a_road_and_only_when_the_value_changes(self) -> None:
        """RF-015-01, RF-015-08 (el marco de 015 y 016 no cambia): ningún otro parámetro de la pista (el nombre, el perfil, la partida, las cotas de destino, los de la ruta), ni de otro tipo de entidad
        (la plataforma tiene su ``start_level_m``), ni una clave que no es de una entidad se toca; y un cambio **sin valor nuevo** (el decisor, el origen) tampoco: no es dar una cota."""
        for key in ("des.road.rdw_001.name", "des.road.rdw_001.profile", "des.road.rdw_001.start", "des.road.rdw_001.dest_level_m", "des.road.rdw_001.mesh_m",
                    "des.platform.plt_001.start_level_m", "des.stockpile.stk_001.margin_m", "des.road.rdw_001", "des.roadprofile.pista_principal.pd", "res.thickness"):
            with self.subTest(key=key):
                changes = road_store.person_level_changes(key, self.ALGORITHM, dict(self.ASKED), entity="Pista a P1")
                self.assertEqual(changes, self.ASKED)
        without = {"reason": "Se cambia el decisor", "decided_by": "Otra persona"}
        self.assertEqual(road_store.person_level_changes(self.END, self.ALGORITHM, dict(without)), without)


class CheckRecordedTest(unittest.TestCase):
    """RF-013-17, RF-015-02, D-14: lo que anotó la operación al empezar es lo que leyó el cálculo al prepararse."""

    @staticmethod
    def prepared() -> Any:
        profile = rd.road_profile()
        return SimpleNamespace(code=CODE, values={"mode": "trace", "mesh_m": 4.0, "start_level_m": 104.0}, common={"des.tolerance.face_deg": 1.0}, profile=profile)

    @staticmethod
    def handle(**changes: Any) -> Any:
        profile = rd.road_profile()
        params = {f"{KEY}mode": "trace", f"{KEY}mesh_m": 4.0, f"{KEY}start_level_m": 104.0, "des.tolerance.face_deg": 1.0,
                  f"des.roadprofile.{profile.code}.max_gradient_pct": profile.max_gradient_pct, f"des.roadprofile.{profile.code}.cut_angle_deg": profile.cut_angle_deg,
                  f"des.roadprofile.{profile.code}.metric": profile.metric, "des.other": 7}
        params.update(changes)
        return SimpleNamespace(params=tuple(SimpleNamespace(key=key, value=value) for key, value in params.items()))

    def test_a_the_same_values_pass(self) -> None:
        """RF-013-17: lo que lee el cálculo (los parámetros de la entidad, los del proyecto y los del perfil) es lo que anotó la operación: no pasa nada; lo que el cálculo no lee no cuenta."""
        road_store._check_recorded(self.handle(), self.prepared())

    def test_b_a_parameter_that_changed_is_refused_with_its_key(self) -> None:
        """RF-013-17, RF-015-02: si un parámetro de la entidad, uno del proyecto o **uno del perfil** cambió entre prepararla y empezarla (``des.input_changed``, con su clave), el resultado ya no
        le corresponde."""
        profile = rd.road_profile()
        for key, value in ((f"{KEY}mesh_m", 6.0), ("des.tolerance.face_deg", 2.0), (f"des.roadprofile.{profile.code}.cut_angle_deg", profile.cut_angle_deg + 5.0)):
            with self.subTest(key=key), self.assertRaises(DesignError) as caught:
                road_store._check_recorded(self.handle(**{key: value}), self.prepared())
            self.assertEqual((caught.exception.code, caught.exception.values["value"]), ("des.input_changed", key))


def points_layer(*points: tuple[str, tuple[float, float]], first_fid: int = 1) -> Any:
    """Una capa de puntos (absolutos en la rejilla de 2 m) con el campo ``nombre``: lo que lee la reproducción del dato congelado."""
    parts = tuple(((rd.absolute([point], GRID),),) for _name, point in points)
    return vector.FeatureLayer("point", tuple(range(first_fid, first_fid + len(points))), parts, (vector.FieldColumn("nombre", "nombre", "TEXT"),), {"nombre": tuple(name for name, _p in points)})


def cell_of(point: tuple[float, float]) -> int:
    """La celda (fila · columnas + columna) de la rejilla que contiene el punto local ``point``."""
    x, y = rd.absolute([point], GRID)[0]
    found = road_store._cell_of(GRID, float(x), float(y))
    assert found is not None
    return found[0] * GRID.ncols + found[1]


class FrozenGeometryTest(unittest.TestCase):
    """RF-017-02, RF-017-03, RF-015-02: la geometría de origen y el ``fid`` que escribe ``des_epr_`` se repiten **de lo congelado**: la capa, el eje de la otra pista y la huella de la entidad de
    destino que anotó la operación, sin proyecto."""

    POINTS = (("Entrada", (100.0, 200.0)), ("En P1", (320.0, 200.0)), ("Fuera de P1", (200.0, 100.0)))
    LAYER = points_layer(*POINTS)

    @staticmethod
    def absolute(point: tuple[float, float]) -> tuple[float, float]:
        x, y = rd.absolute([point], GRID)[0]
        return float(x), float(y)

    def axis(self) -> np.ndarray:
        """El eje de otra pista por estaciones (abscisa, x, y, terreno, rasante): una recta de 100 m hacia el este cada 10 m, en absolutas."""
        stations = np.arange(0.0, 101.0, 10.0)
        xs, ys = (np.array([self.absolute((100.0 + s, 150.0))[i] for s in stations]) for i in (0, 1))
        return np.column_stack([stations, xs, ys, 100.0 + 0.04 * stations, 101.0 + 0.04 * stations])

    def test_a_a_point_to_point_road_takes_both_points_and_the_fid_of_the_origin(self) -> None:
        """RF-017-02: el origen y el destino se eligen en la capa congelada por su nombre o por su ``fid`` (como texto), con sus coordenadas absolutas tal cual; el ``fid`` de ``des_epr_`` es
        el del **origen**."""
        asked = request("Pista", layer="capa", origin="Entrada", destination="3")
        geometry, fid = road_store.frozen_geometry(asked, CODE, GRID, self.LAYER)
        self.assertEqual((geometry.origin, geometry.destination, fid), (self.absolute(self.POINTS[0][1]), self.absolute(self.POINTS[2][1]), 1))
        self.assertIsNone(geometry.line)
        by_name = request("Pista", layer="capa", origin="Entrada", destination="Fuera de P1")
        shifted, fid = road_store.frozen_geometry(by_name, CODE, GRID, points_layer(*self.POINTS, first_fid=10))
        self.assertEqual((shifted.origin, shifted.destination, fid), (geometry.origin, geometry.destination, 10))

    def test_b_the_origin_on_the_axis_of_another_road_is_read_from_its_frozen_stations(self) -> None:
        """RF-017-03: el origen ``RDW-001@s`` es el punto de la rasante de esa pista a la abscisa ``s`` (``axis_point_at`` de las estaciones congeladas, interpolado entre dos); el ``fid`` es el
        del destino, que es de la capa."""
        asked = request("Ramal", layer="capa", origin="RDW-001@35", destination="Fuera de P1")
        geometry, fid = road_store.frozen_geometry(asked, CODE, GRID, self.LAYER, axis=self.axis())
        at = road_store.axis_point_at(self.axis(), 35.0)
        self.assertEqual((geometry.origin, geometry.destination, fid), ((at[0], at[1]), self.absolute(self.POINTS[2][1]), 3))
        with self.assertRaises(ValueError) as caught:
            road_store.frozen_geometry(asked, CODE, GRID, self.LAYER)
        self.assertIn("eje", str(caught.exception))

    def test_c_the_destination_in_an_entity_is_the_point_inside_its_footprint_and_not_the_origin(self) -> None:
        """RF-017-03, T19-c: el destino ``entity:PLT-001`` es **el** punto de la capa que cae en la huella congelada de la entidad (sin contar el origen, aunque cayera dentro); con el origen en
        el eje de otra pista, el ``fid`` es el de ese punto; y ninguno o varios es un error del programa (la preparación lo rechazó al crearla)."""
        footprint = np.array([cell_of(self.POINTS[0][1]), cell_of(self.POINTS[1][1]), cell_of((322.0, 200.0))], dtype=np.int64)
        asked = request("Pista a P1", layer="capa", origin="Entrada", destination="entity:PLT-001")
        geometry, fid = road_store.frozen_geometry(asked, CODE, GRID, self.LAYER, footprint=footprint)
        self.assertEqual((geometry.origin, geometry.destination, fid), (self.absolute(self.POINTS[0][1]), self.absolute(self.POINTS[1][1]), 1))
        branch = request("Ramal a P1", layer="capa", origin="RDW-001@35", destination="entity:PLT-001")
        inside = np.array([cell_of(self.POINTS[1][1]), cell_of((322.0, 200.0))], dtype=np.int64)  # el origen está en el eje de otra pista: no hay punto de la capa que excluir
        geometry, fid = road_store.frozen_geometry(branch, CODE, GRID, self.LAYER, axis=self.axis(), footprint=inside)
        self.assertEqual((geometry.destination, fid), (self.absolute(self.POINTS[1][1]), 2))
        for wrong in (np.array([cell_of((60.0, 60.0))], dtype=np.int64), np.array([cell_of(self.POINTS[1][1]), cell_of(self.POINTS[2][1])], dtype=np.int64)):
            with self.subTest(cells=len(wrong)), self.assertRaises(ValueError):
                road_store.frozen_geometry(asked, CODE, GRID, self.LAYER, footprint=wrong)
        with self.assertRaises(ValueError):
            road_store.frozen_geometry(asked, CODE, GRID, self.LAYER)

    def test_d_a_level_destination_carries_its_zone_and_no_fid_when_the_origin_is_not_of_the_layer(self) -> None:
        """RF-017-02, D-4: el destino por cota lleva su cota, su tolerancia y **los anillos de la zona** de su capa congelada (por su nombre o su ``fid``); el ``fid`` es el del origen y, con el
        origen en el eje de otra pista, 0."""
        ring = rd.absolute([(80.0, 140.0), (120.0, 140.0), (120.0, 180.0), (80.0, 180.0), (80.0, 140.0)], GRID)
        zones = vector.FeatureLayer("polygon", (4,), ((((ring,)),),), (vector.FieldColumn("nombre", "nombre", "TEXT"),), {"nombre": ("Zona del fondo",)})
        for zone in ("capa_zonas:Zona del fondo", "capa_zonas:4", "capa_zonas"):
            asked = request("Rampa", layer="capa", origin="Entrada", destination=None, dest_level_m=125.0, dest_tol_m=0.5, dest_zone=zone)
            geometry, fid = road_store.frozen_geometry(asked, CODE, GRID, self.LAYER, zone_layer=zones)
            destination = geometry.destination
            self.assertIsInstance(destination, road_model.LevelDestination)
            self.assertEqual((destination.level_m, destination.tolerance_m, fid, len(destination.zone)), (125.0, 0.5, 1, 1))
            np.testing.assert_array_equal(destination.zone[0][0], ring)
        branch = request("Rampa del ramal", layer="capa", origin="RDW-001@35", destination=None, dest_level_m=125.0, dest_tol_m=0.5, dest_zone="capa_zonas")
        geometry, fid = road_store.frozen_geometry(branch, CODE, GRID, self.LAYER, zone_layer=zones, axis=self.axis())
        self.assertEqual(fid, 0)
        with self.assertRaises(ValueError):
            road_store.frozen_geometry(branch, CODE, GRID, self.LAYER, axis=self.axis())

    def test_e_a_line_road_takes_its_line_without_changing_it(self) -> None:
        """RF-017-02, RF-017-18: «sobre un eje» toma la línea de la capa congelada (absolutas, float64) **sin corregirla** y el ``fid`` de su geometría; un «eje 3D» toma la línea con su Z de la capa de líneas congelada
        (T23: ``test_road_modes.FrozenGeometryTest``) y, sin ella, es un error del programa."""
        line = rd.absolute([(100.0, 300.0), (160.0, 300.0), (220.0, 340.0)], GRID)
        lines = vector.FeatureLayer("line", (7, 8), (((line,),), ((line + 10.0,),)), (vector.FieldColumn("nombre", "nombre", "TEXT"),), {"nombre": ("Eje A", "Eje B")})
        asked = request("Sobre un eje", mode="on_axis", layer="ejes", feature="Eje B")
        geometry, fid = road_store.frozen_geometry(asked, CODE, GRID, lines)
        np.testing.assert_array_equal(geometry.line, line + 10.0)
        self.assertEqual((fid, geometry.origin, geometry.destination), (8, None, None))
        with self.assertRaises(ValueError) as caught:  # «eje 3D» sin la capa de líneas con Z congelada
            road_store.frozen_geometry(request("Eje 3D", mode="axis_3d", layer="ejes", feature="Eje B"), CODE, GRID, lines)
        self.assertIn("Z", str(caught.exception))


class FrozenWeightsTest(unittest.TestCase):
    """RF-017-06, RF-015-02: los pesos de «preferible no afectar» que repite la reproducción salen del informe **congelado** de las máscaras, como los carga el proyecto."""

    def test_a_the_weights_are_read_from_the_frozen_report_of_the_masks(self) -> None:
        """RF-017-06: ``_Frozen.weights`` da el peso de cada zona (código → peso) de las filas ``weight`` del informe de las máscaras congelado (como ``gis.masks.access.load_masks``) y sin el
        informe, ninguno: la afección de la pista y su ruta cuentan con ellos."""
        masks_declared = import_geoblender("gis.masks.provenance")
        role = reproduce_mod._MASKS_PREFIX + masks_declared.FAMILIES_BY_CODE[masks_declared.REPORT].role
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE gis_mskr_x (fid INTEGER PRIMARY KEY, constraint_code TEXT, quantity TEXT, value REAL, unit_code TEXT, note TEXT)")
        connection.executemany("INSERT INTO gis_mskr_x (constraint_code, quantity, value, unit_code, note) VALUES (?, ?, ?, ?, ?)",
                               [("encinar", "weight", 3.0, "-", None), ("encinar", "zone_area", 120.0, "m2", "avoid"), ("arbol", "weight", 1.5, "-", None), ("otra", "weight", None, "-", None)])
        item = versions_reproduce.FrozenInput(role, "table", "gpkg", "n", {"main": "x.gpkg"}, {"layer": "gis_mskr_x"}, "0" * 64)
        frozen = reproduce_mod._Frozen.__new__(reproduce_mod._Frozen)
        frozen.request = SimpleNamespace(inputs=(item,))
        with mock.patch.object(reproduce_mod, "_open", lambda _path: contextlib.nullcontext(connection)):
            self.assertEqual(frozen.weights(), {"encinar": 3.0, "arbol": 1.5})
        frozen.request = SimpleNamespace(inputs=())
        self.assertEqual(frozen.weights(), {})


class FunctionsTest(unittest.TestCase):
    """RF-008-26, RF-009-11: las dos funciones de la pista que registra ``bl``."""

    def test_a_recompute_refuses_what_is_not_a_road_recompute(self) -> None:
        """RF-008-26: ``recompute_road`` solo repite una ``RecomputeRequest`` de ``des.road`` con sus ajustes (``TypeError``, ``ValueError``); dar por bueno un apoyo sin su entidad (soltarlo, RF-015-17; T24)
        ya no se rechaza como «no hecho»: se pasa a la operación, y unos ajustes sin código dan el mismo ``ValueError`` que sin soltar nada."""
        with self.assertRaises(TypeError):
            road_store.recompute_road("petición")  # type: ignore[arg-type]
        other = core_recompute.RecomputeRequest(object(), "uid", "des.platform", {}, (), ())
        with self.assertRaises(ValueError):
            road_store.recompute_road(other)
        road = core_recompute.RecomputeRequest(object(), "uid", provenance.ROAD, {}, (), ())
        with self.assertRaises(ValueError) as caught:
            road_store.recompute_road(road)
        self.assertIn("code", str(caught.exception))
        released = (provenance.ReleasedSupport("PLT-001", "motivo", "Samuel", "2026-11-21"),)
        with self.assertRaises(ValueError) as caught:
            road_store.recompute_road(road, released=released)
        self.assertIn("code", str(caught.exception))

    def test_b_the_store_runs_the_road_by_its_own_branch(self) -> None:
        """RF-008-26: ``recompute_run`` repite la pista por **su** rama (no la de un escalonado, ni un ``NotImplementedError``): con unos ajustes que no son los suyos, el ``ValueError`` de la
        petición."""
        request_ = core_recompute.RecomputeRequest(object(), "uid", provenance.ROAD, {}, (), ())
        with self.assertRaises(ValueError) as caught:
            store.recompute_run(request_)
        self.assertNotIn("aún no", str(caught.exception))

    def test_c_reproduce_refuses_what_is_not_a_road(self) -> None:
        """RF-009-11: ``reproduce_road`` solo reproduce una ``ReproduceRequest`` de ``des.road`` (``TypeError``, ``ValueError``): ya no dice «aún no»."""
        with self.assertRaises(TypeError):
            reproduce_mod.reproduce_road("petición")  # type: ignore[arg-type]
        with self.assertRaises(ValueError) as caught:
            reproduce_mod.reproduce_road(versions_reproduce.ReproduceRequest("des.quarry", {}, (), {}, ".", None))
        self.assertNotIn("aún no", str(caught.exception))


class ProfileOfTheRequestTest(unittest.TestCase):
    """RF-017-07: el perfil que se rehace de lo congelado."""

    def test_a_the_profile_is_the_frozen_values_without_its_class(self) -> None:
        """RF-017-07, RF-015-02: el perfil se rehace de los **parámetros congelados** (``des.roadprofile.{p}.*``, los 14 que cambian el resultado; su clase normativa no se lee y no cambia ninguna
        cifra) y da los mismos valores que el del proyecto; sin uno de ellos, el rechazo de siempre (``des.road_profile_value_missing``)."""
        profile = rd.road_profile()
        frozen = {f"des.roadprofile.{profile.code}.{param.value}": getattr(profile, "class_name" if param.value == "class" else param.value)
                  for param in design_params.RoadProfileParam if param.value != "class"}
        found = road_store.frozen_profile(frozen, profile.code)
        self.assertEqual(found.code, PROFILE)
        for param in design_params.RoadProfileParam:
            if param.value != "class":
                self.assertEqual(getattr(found, param.value), getattr(profile, param.value), param.value)
        del frozen[f"des.roadprofile.{profile.code}.max_gradient_pct"]
        with self.assertRaises(DesignError) as caught:
            road_store.frozen_profile(frozen, profile.code)
        self.assertEqual(caught.exception.code, "des.road_profile_value_missing")


if __name__ == "__main__":
    unittest.main()
