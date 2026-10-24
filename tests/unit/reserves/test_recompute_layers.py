# SPDX-License-Identifier: GPL-3.0-or-later
"""Una cubicación con ámbito y con dominios se recalcula y se reproduce (spec 011, T32;
RF-011-20, RF-011-07, RF-011-10; CE-011-04; plan 011 A12, D-32).

Regresión del HITO H1: ``reserves.provenance.volume_request`` no repetía una cubicación con
ámbito o con capa de dominios (``ValueError``: «sus capas aún no se leen»), así que «Recalcular
lo obsoleto» no la rehacía y reproducir su revisión la daba «no reproducible». RF-011-20 pide
que **toda** cubicación se recalcule y se reproduzca: su capa se lee por su papel (``scope``,
``domains``), la viva al recalcular y la congelada al reproducir.

Sobre el proyecto de ``tests.support.res_fixtures`` (una copia por clase) con dos capas de un
GeoPackage sintético importadas con la 006: «Fases» con el papel «dominios» (tres fases que
pasan del contorno y una parte sin fase) y «Contorno» con el papel «contorno» (un polígono con
un hueco), con bordes que cortan las celdas de 2 m. La referencia es ``volume_steps`` con los
mismos polígonos escritos aquí (no los leídos del proyecto).
"""

from __future__ import annotations

import unittest
from typing import Any

import numpy as np

from tests.support import res_fixtures as fx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.reserves.test_versions import FINAL, START, _last, _VersionsCase

provenance = import_geoblender("reserves.provenance")
store = import_geoblender("reserves.store")
volumes = import_geoblender("reserves.volumes")
polygons = import_geoblender("reserves.polygons")
operations = import_geoblender("core.provenance.operations")
graph = import_geoblender("core.provenance.graph")
figures_mod = import_geoblender("core.provenance.figures")
freeze = import_geoblender("core.versions.freeze")
reproduce = import_geoblender("core.versions.reproduce")
userdata_mod = import_geoblender("core.userdata")
gis_messages = import_geoblender("gis.messages")

NAME = "Por fases"
FIELD = "fase"
"""La columna del campo «Fase» de la capa en el proyecto (T18: su identificador)."""
WEST, SOUTH = fx.COLUMN_WINDOW.xmin, fx.COLUMN_WINDOW.ymin


def _ring(*corners: tuple[float, float]) -> np.ndarray:
    """Un anillo ABSOLUTO cerrado con las esquinas relativas a la esquina suroeste."""
    return np.array([(WEST + x, SOUTH + y) for x, y in (*corners, corners[0])],
                    dtype=np.float64)


PHASES: tuple[tuple[int, str, tuple[np.ndarray, ...]], ...] = (
    (1, "Fase 1", (_ring((0.0, 0.0), (51.0, 0.0), (51.0, 80.0), (0.0, 80.0)),)),
    (2, "Fase 2", (_ring((51.0, 0.0), (100.0, 0.0), (100.0, 41.0), (51.0, 41.0)),)),
    (3, "Fase 3", (_ring((51.0, 41.0), (100.0, 41.0), (100.0, 61.0), (51.0, 61.0)),)),
)
"""Las fases (fid, «Fase», anillos): al norte de la 3 queda una parte sin fase."""
CONTOUR: tuple[tuple[int, str, tuple[np.ndarray, ...]], ...] = (
    (1, "Contorno", (_ring((11.0, 7.0), (89.0, 7.0), (89.0, 73.0), (11.0, 73.0)),
                     _ring((41.0, 31.0), (41.0, 49.0), (59.0, 49.0), (59.0, 31.0)))),
)
"""El contorno con su hueco (que corta las tres fases)."""


def _scope() -> tuple[Any, ...]:
    return tuple(polygons.Polygon(fid, "", rings) for fid, _value, rings in CONTOUR)


def _domains(layer: str) -> Any:
    return volumes.DomainLayer(layer, FIELD, tuple(polygons.Polygon(fid, value, rings)
                                                   for fid, value, rings in PHASES))


def _same_polygons(test: unittest.TestCase, got: Any, expected: Any) -> None:
    """Los mismos polígonos (fid, valor y anillos bit a bit)."""
    test.assertEqual([(item.fid, item.value, len(item.rings)) for item in got],
                     [(item.fid, item.value, len(item.rings)) for item in expected])
    for item, wanted in zip(got, expected, strict=True):
        for ring, ring_wanted in zip(item.rings, wanted.rings, strict=True):
            test.assertEqual(np.asarray(ring).dtype, np.float64)
            test.assertTrue(np.array_equal(np.asarray(ring).view(np.uint64),
                                           np.asarray(ring_wanted).view(np.uint64)))


class LayersRecomputeTest(_VersionsCase):
    """«Por fases» en V01: ``res.volume`` dentro de «Contorno» y repartida por «Fases»."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(fx.layers_registered())
        folder = cls.enterClassContext(project_tmp("gb-rl-"))
        userdata = userdata_mod.UserData(folder / "u")
        fx.write_layer(folder / "fases.gpkg", "fases", "Fase", PHASES)
        fx.write_layer(folder / "contorno.gpkg", "contorno", "nombre", CONTOUR)
        cls.clock.advance(minutes=1)
        cls.phases = fx.import_layer(cls.project, userdata, folder / "fases.gpkg", "fases",
                                     "Fases", role="domains")
        cls.clock.advance(minutes=1)
        cls.contour = fx.import_layer(cls.project, userdata, folder / "contorno.gpkg",
                                      "contorno", "Contorno", role="boundary")
        cls.request = volumes.VolumeRequest(NAME, START, FINAL, scope=_scope(),
                                            domains=_domains(cls.phases.name))
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(
            cls.project, provenance.VOLUME, executor="blender", version=cls.v1.uid,
            settings=provenance.volume_settings(cls.request, scope=cls.contour.name),
            inputs=provenance.volume_inputs(cls.request, scope=cls.contour.name),
            params=provenance.volume_params(cls.request))
        _last(store.volume_run(cls.project, handle, cls.request))
        cls.volume = handle.uid

    def consumed(self, uid: str) -> dict[str, str]:
        """Papel → uid de lo que consumió la operación ``uid``."""
        return {str(role): str(item) for role, item in self.query(
            "SELECT role, item_uid FROM gb_operation_io WHERE operation_uid = ? AND "
            "direction = 'in'", uid)}

    def test_rf_011_20_recomputed_with_the_live_layers_and_reproduced_with_the_frozen(
            self) -> None:
        """RF-011-20, RF-011-07, RF-011-10, CE-011-04 (RF-008-24, RF-008-26, RF-009-07,
        RF-009-11): congelada V01.r1, la superficie final 1 m más alta deja obsoleta la
        cubicación con ámbito y dominios (la superficie, su causa); «Recalcular lo obsoleto» la
        rehace en V01.r2 con las capas vivas, que vuelve a anotar con su papel, y da las cifras
        de ``volume_steps`` con los mismos polígonos (bit a bit), por fase y fuera de ellas, con
        menos desmonte; las de V01.r1 no cambian y reproducirla lee las capas congeladas y da
        su tabla (el mismo hash) y sus cifras por dominio **bit a bit**, sin escribir nada en el
        proyecto."""
        whole = {"cubication": NAME}
        first = self.figures([self.volume])
        phases = [{**whole, "domain": value} for _fid, value, _rings in PHASES]
        shown = [*phases, {**whole, "outside": volumes.OUTSIDE_SCOPE}]
        for scope in shown:
            self.assertGreater(first[(self.volume, "res.cut_m3", figures_mod.scope_json(scope))],
                               0.0, scope)
        layers = {provenance.SCOPE_ROLE: self.contour.uid,
                  provenance.DOMAINS_ROLE: self.phases.uid}
        self.assertLessEqual(layers.items(), self.consumed(self.volume).items())

        self.clock.advance(minutes=1)
        outcome = _last(freeze.freeze_steps(self.project, self.v1.uid, reason=NAME))
        self.assertIsNotNone(outcome.frozen)
        r1, r2 = str(outcome.frozen.uid), self.open_revision(self.v1)
        self.clock.advance(minutes=1)
        fx.write_grids(self.project, [fx.moved_grid("Final", 1.0)], message="Final revisada")
        final = self.dataset_uid(fx.FINAL_GRID)
        self.assertEqual(self.stale(), {self.volume: {graph.Cause(graph.CauseKind.DATASET_CHANGED,
                                                                  final)}})

        (redone,) = self.assertDone(self.recompute_all(), 1)
        state = self.operation(redone)
        self.assertEqual((state["op_type"], state["status"], state["revision_uid"],
                          state["supersedes_uid"]), (provenance.VOLUME, "done", r2, self.volume))
        self.assertLessEqual(layers.items(), self.consumed(redone).items())
        sources = store.project_sources(self.project, self.request, version_uid=self.v1.uid)
        expected = _last(volumes.volume_steps(self.request, sources))
        self.assertEqual(self.figures([redone]),
                         {(redone, item.key, figures_mod.scope_json(item.scope)): item.value
                          for item in expected.figures})
        for scope in phases:
            self.assertLess(self.figure(redone, "res.cut_m3", **scope),
                            self.figure(self.volume, "res.cut_m3", **scope), scope)
        self.assertEqual(self.stale(), {})
        self.assertEqual(self.figures([self.volume]), first)

        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = _last(reproduce.reproduce_steps(self.project, r1))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)
        self.assertEqual(report.not_reproducible, ())
        self.assertEqual([(check.role, check.same) for check in report.outputs
                          if check.operation_uid == self.volume], [("volumes", True)])
        reproduced = {(check.operation_uid, check.key, figures_mod.scope_json(check.scope)):
                      check.reproduced for check in report.figures
                      if check.operation_uid == self.volume}
        self.assertEqual(reproduced, first)  # bit a bit, también por dominio
        self.assertTrue(report.matches)

    def test_the_layers_are_read_by_their_dataset(self) -> None:
        """RF-011-07, RF-011-01 (plan D-32): el ámbito de una capa de contornos son sus
        contornos con sus huecos y el de una capa de dominios, la unión de sus polígonos; la
        capa de dominios, un polígono por parte con el valor de su campo; anillos bit a bit.
        Otro dato, otro campo o un dato que no hay, rechazados."""
        _same_polygons(self, store.load_scope(self.project, self.contour.name), _scope())
        _same_polygons(self, store.load_scope(self.project, self.phases.uid),
                       [polygons.Polygon(fid, "", rings) for fid, _value, rings in PHASES])
        layer = store.load_domain_layer(self.project, self.phases.name, FIELD)
        self.assertEqual((layer.layer, layer.field), (self.phases.name, FIELD))
        _same_polygons(self, layer.polygons, _domains(self.phases.name).polygons)
        with self.assertRaises(ValueError):
            store.load_domain_layer(self.project, self.phases.name, "orden")
        with self.assertRaises(ValueError):
            store.load_domain_layer(self.project, self.contour.name, FIELD)
        with self.assertRaises(ValueError):
            store.load_scope(self.project, fx.FINAL_GRID)
        with self.assertRaises(gis_messages.GisError) as caught:
            store.load_scope(self.project, "gis_bnd_no_esta")
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")


if __name__ == "__main__":
    unittest.main()
