# SPDX-License-Identifier: GPL-3.0-or-later
"""Cargar las máscaras por pasos cortos (spec 012, T36; RF-012-17, RNF-012-02, RNF-012-06; plan
012 §5.2.3, A7, A11, D-15, D-43; ADR-0028).

La T36 es de rendimiento puro: al verificar, cargar las máscaras de la versión era una llamada de
0,45 s (2.000 ``ParameterStore.resolve``, 182.000 filas de ``gis_mskz_`` y la rejilla de clases de
2,81 M de celdas de una vez). Sobre el proyecto de ``tests.support.constraints_project`` (una copia
por clase), en V01, con las máscaras compiladas:

- **RNF-012-06**: ``ParameterStore.resolve_many`` da lo mismo que ``resolve`` clave a clave (la
  versión antes que el proyecto, las claves sin valor no salen); ``gis.masks.store._resolved`` da
  lo de antes.
- **RF-012-17**: ``zone_runs_steps`` y ``load_masks_steps`` dan, en varias unidades, lo mismo que
  la lectura de una vez (``read_zone_runs`` y la lectura del GeoTIFF entero con la que se cargaba):
  las zonas en el mismo orden, la rejilla de clases bit a bit, los pesos, los tipos, los ``Use``;
  ``load_masks`` sigue rechazando las máscaras obsoletas; ``ensure_masks_steps`` da la carga en
  pasos de ``budget_s`` y el mismo ``MaskSet``.
- **RF-012-28**: cerrar la carga a mitad no escribe nada (solo lee).
"""

from __future__ import annotations

import sys
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import constraints_project as cp
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files

access = import_geoblender("gis.masks.access")
mask_store = import_geoblender("gis.masks.store")
provenance = import_geoblender("gis.masks.provenance")
cparams = import_geoblender("core.constraints.params")
cmodel = import_geoblender("core.constraints.model")
params = import_geoblender("core.params")
read_tiff = import_geoblender("gis.geotiff.reader")

BUDGET_S = 0.05


def _last(steps: Iterator[Any]) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


def old_resolved(conn: Any, project: Any, constraints: Any, version_uid: str | None) -> dict:
    """``gis.masks.store._resolved`` de antes de la T36: un ``resolve`` por clave."""
    store = params.ParameterStore(project)
    chain = ((params.PROJECT_SCOPE,) if version_uid is None
             else (params.VERSION_SCOPE, params.PROJECT_SCOPE))
    found: dict[str, object] = {}
    for item in constraints:
        if not cmodel.is_code(item.code):
            continue
        for param in cmodel.ConstraintParam:
            key = cparams.param_key(item.code, param)
            try:
                found[key] = store.resolve(conn, key, chain, version=version_uid)
            except params.ParamError:
                continue
    return found


class LoadStepsTest(cp.ConstraintsProjectCase):
    """V01 con las máscaras compiladas: la carga por pasos y lo que usa."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.masks = _last(access.ensure_masks_steps(cls.project, cls.v1.uid, budget_s=BUDGET_S))

    def reference(self) -> Any:
        """La carga de antes: las zonas de una vez y la rejilla de clases entera
        (``read_geotiff``)."""
        found = access._find(self.project, self.v1.uid)
        records = found.records
        with self.project.read() as conn:
            zones = mask_store.read_zone_runs(conn, records[provenance.ZONES].locator)
            report = mask_store.read_report(conn, records[provenance.REPORT].locator)
        raster = records[provenance.CLASSES]
        source = read_tiff.read_geotiff(Path(self.project.root, *raster.locator.split("/")),
                                        max_cells=sys.maxsize)
        values = np.asarray(source.values, dtype=np.float64)
        classes = np.where(np.isfinite(values), values, 0.0).astype(np.uint16)
        return zones, report, classes, found

    def test_resolve_many_equals_resolve(self) -> None:
        """RNF-012-06: ``resolve_many`` da lo que ``resolve`` de cada clave (con la versión, V01
        con su resguardo propio de la torre y V02 con el del proyecto, y solo con el proyecto);
        las claves sin valor no salen; una cadena mala se rechaza como en ``resolve``."""
        store = params.ParameterStore(self.project)
        keys = [cparams.param_key(item.code, param) for item in self.stored_constraints()
                for param in cmodel.ConstraintParam]
        # una clave que no está y otra repetida
        keys += ["core.constraint.no_existe.buffer_out_m", keys[0]]
        with self.project.read() as conn:
            for version, chain in ((self.v1.uid, (params.VERSION_SCOPE, params.PROJECT_SCOPE)),
                                   (self.v2.code, (params.VERSION_SCOPE, params.PROJECT_SCOPE)),
                                   (None, (params.PROJECT_SCOPE,)),
                                   (self.v1.uid, (params.PROJECT_SCOPE, params.VERSION_SCOPE))):
                expected = {}
                for key in dict.fromkeys(keys):
                    try:
                        expected[key] = store.resolve(conn, key, chain, version=version)
                    except params.ParamError:
                        continue
                with self.subTest(version=version, chain=chain):
                    found = store.resolve_many(conn, keys, chain, version=version)
                    self.assertEqual(found, expected)
                    self.assertEqual(list(found), list(expected))
            self.assertNotIn("core.constraint.no_existe.buffer_out_m", found)
            tower = cparams.buffer_out_key("torre")
            by_version = store.resolve_many(conn, [tower], (params.VERSION_SCOPE,
                                                            params.PROJECT_SCOPE),
                                            version=self.v1.uid)[tower]
            by_project = store.resolve_many(conn, [tower], (params.PROJECT_SCOPE,))[tower]
            self.assertEqual((by_version.scope, by_project.scope), ("version", "project"))
            self.assertEqual((by_version.value, by_project.value),
                             (cp.TOWER_V01_M, cp.TOWER_PROJECT_M))
            for bad, version in (((), None), (("project", "project"), None),
                                 (("version", "project"), None), (("project",), self.v1.uid)):
                with self.subTest(chain=bad, version=version), self.assertRaises(ValueError):
                    store.resolve_many(conn, [tower], bad, version=version)
            self.assertEqual(store.resolve_many(conn, [], (params.PROJECT_SCOPE,)), {})

    def test_resolved_of_the_masks_is_what_it_was(self) -> None:
        """RNF-012-06: ``gis.masks.store._resolved`` (ahora con ``resolve_many``) da lo mismo
        que con un ``resolve`` por clave, con y sin versión, y ``{}`` sin restricciones."""
        constraints = self.stored_constraints()
        with self.project.read() as conn:
            for version in (self.v1.uid, self.v2.uid, None):
                with self.subTest(version=version):
                    found = mask_store._resolved(conn, self.project, constraints, version)
                    expected = old_resolved(conn, self.project, constraints, version)
                    self.assertEqual(found, expected)
                    self.assertEqual(list(found), list(expected))
            self.assertEqual(mask_store._resolved(conn, self.project, (), self.v1.uid), {})

    def test_zone_runs_steps_equals_the_whole_read(self) -> None:
        """RF-012-17: ``zone_runs_steps`` da las zonas de ``read_zone_runs``, en su orden, en
        varias unidades (con trozos pequeños), sin sostener una lectura entre unidades."""
        record = self.record(provenance.dataset_name(provenance.ZONES), self.v1)
        with self.project.read() as conn:
            expected = mask_store.read_zone_runs(conn, record.locator)
        with (mock.patch.object(mask_store, "_ZONE_ROWS_PER_UNIT", 11),
              mock.patch.object(mask_store, "_ZONES_PER_UNIT", 1)):
            steps = mask_store.zone_runs_steps(self.project, record.locator)
            units = 0
            while True:
                try:
                    next(steps)
                    units += 1
                except StopIteration as stop:
                    found = stop.value
                    break
        self.assertGreater(units, 20)
        self.assertEqual(list(found), list(expected))
        self.assertTrue(all(found[zone] == expected[zone] for zone in expected))

    def test_load_masks_steps_equals_the_whole_load(self) -> None:
        """RF-012-17: ``load_masks_steps`` da, en varias unidades, el ``MaskSet`` de la lectura de
        una vez: zonas, rejilla de clases (uint16, bit a bit), pesos, tipos, ``Use`` y marca."""
        zones, report, classes, found = self.reference()
        steps = access.load_masks_steps(self.project, self.v1.uid)
        units = 0
        while True:
            try:
                next(steps)
                units += 1
            except StopIteration as stop:
                loaded = stop.value
                break
        self.assertGreaterEqual(units, 4)
        self.assertEqual(loaded.classes.dtype, np.uint16)
        np.testing.assert_array_equal(loaded.classes, classes)
        self.assertEqual(list(loaded.zones), list(zones))
        self.assertTrue(all(loaded.zones[code] == zones[code] for code in zones))
        weights = {code: float(value) for code, quantity, value, _u, _n in report
                   if quantity == "weight" and value is not None}
        ctypes = {code: str(note) for code, quantity, _v, _u, note in report
                  if quantity == "zone_area" and note is not None}
        self.assertEqual(dict(loaded.weights), weights)
        self.assertEqual(dict(loaded.ctypes), ctypes)
        self.assertEqual((loaded.version_uid, loaded.operation_uid, loaded.state),
                         (found.version.uid, found.operation_uid, access.MaskState.CURRENT))
        self.assertEqual((loaded.pending_sectors, loaded.pending_names),
                         (found.pending, found.names))
        again = access.load_masks(self.project, self.v1.uid)
        np.testing.assert_array_equal(again.classes, loaded.classes)
        self.assertEqual(again.uses(), loaded.uses())
        self.assertEqual(loaded.grid, self.masks.grid)

    def test_ensure_masks_steps_loads_in_short_steps(self) -> None:
        """RNF-012-06: con las máscaras al día, ``ensure_masks_steps`` las carga en varios pasos
        (con un presupuesto mínimo, una unidad por paso) y entrega el mismo ``MaskSet``."""
        steps = list(access.ensure_masks_steps(self.project, self.v1.uid, budget_s=0.0001))
        self.assertGreaterEqual(len(steps), 5)
        self.assertEqual({step.phase for step in steps}, {"masks"})
        self.assertEqual([step.result is None for step in steps], [True] * (len(steps) - 1)
                         + [False])
        self.assertEqual([step.done for step in steps], sorted(step.done for step in steps))
        np.testing.assert_array_equal(steps[-1].result.classes, self.masks.classes)

    def test_closing_the_load_writes_nothing(self) -> None:
        """RF-012-28: cerrar la carga a mitad no escribe nada (solo lee)."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        steps = access.load_masks_steps(self.project, self.v1.uid)
        for _ in range(3):
            next(steps)
        steps.close()
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)

    def test_masks_that_are_not_up_to_date_are_still_refused(self) -> None:
        """RF-012-17: las de V02, sin compilar, siguen rechazadas con ``MaskError``, también por
        pasos (al empezar a cargar, antes de leer nada más)."""
        with self.assertRaises(access.MaskError):
            next(access.load_masks_steps(self.project, self.v2.uid))
        with self.assertRaises(access.MaskError):
            access.load_masks(self.project, self.v2.uid)


if __name__ == "__main__":
    unittest.main()
