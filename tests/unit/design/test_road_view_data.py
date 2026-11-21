# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que el dominio da a la vista de la pista y de la accesibilidad, sin Blender (spec 017, T31; HU-017-1, HU-017-3; RF-015-25, RF-017-23,
RF-017-25; plan 017 §5.1 y §5.5).

El objeto de la vista (``bl.scene.entity_views``, ``bl.scene.des_views``) se prueba en ``tests/blender/test_road_views.py`` (el registro) y en
``tests/blender/milestone_road_views.py`` (con proyecto); aquí, lo que no necesita Blender, que el cargador pide por el **papel** de la salida de
la operación y no por el nombre del dato (el cargador conoce el dato, no la pista ni la accesibilidad):

- **El eje por estaciones de una pista** (:class:`RoadAxisTest`): ``entity_store.read_road_axis`` da el ``des_rdx_`` que escribió la operación como
  ``(n, 3)`` en float64 —la x, la y y **la cota de la rasante**, no la del terreno—, por orden de abscisa, y ``None`` si la operación no lo escribió
  o su tabla no tiene dato utilizable.
- **La superficie de una accesibilidad** (:class:`AccessSurfaceTest`): ``access_store.read_access_surface`` da el nombre de la superficie sobre
  la que se hizo (su entrada con el papel de superficie, no la final de una cantera), y ``None`` si la operación no la consumió.
"""

from __future__ import annotations

import sqlite3
import unittest

import numpy as np

from tests.support.package import import_geoblender

access_store = import_geoblender("design.access_store")
entity_store = import_geoblender("design.entity_store")
provenance = import_geoblender("design.provenance")
store = import_geoblender("design.store")


def _project() -> sqlite3.Connection:
    """Una base en memoria con el registro mínimo de datos y de entradas y salidas de una operación (lo que leen los dos lectores)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE gb_dataset (uid TEXT, name TEXT, locator TEXT)")
    conn.execute("CREATE TABLE gb_operation_io (fid INTEGER PRIMARY KEY, operation_uid TEXT, direction TEXT, item_kind TEXT, item_uid TEXT, role TEXT)")
    return conn


def _data(conn: sqlite3.Connection, uid: str, name: str, locator: str, operation: str, direction: str, role: str) -> None:
    conn.execute("INSERT INTO gb_dataset VALUES (?, ?, ?)", (uid, name, locator))
    conn.execute("INSERT INTO gb_operation_io (operation_uid, direction, item_kind, item_uid, role) VALUES (?, ?, 'dataset', ?, ?)",
                 (operation, direction, uid, role))


def _axis(conn: sqlite3.Connection, table: str, rows: list[tuple[float, float, float, float, float]]) -> None:
    """La tabla ``des_rdx_`` con sus columnas y ``rows`` (abscisa, x, y, cota del terreno y cota de la rasante: el resto, sin dato)."""
    names = ", ".join(f'"{column.name}"' for column in store.ROAD_AXIS_COLUMNS)
    conn.execute(f'CREATE TABLE "{table}" (fid INTEGER PRIMARY KEY, {names})')
    for station, x, y, terrain, level in rows:
        values = {"station_m": station, "x": x, "y": y, "terrain_m": terrain, "level_m": level, "gradient_pct": 0.0, "radius_m": None, "curve": 0}
        conn.execute(f'INSERT INTO "{table}" ({names}) VALUES ({", ".join("?" for _ in store.ROAD_AXIS_COLUMNS)})',
                     tuple(values[column.name] for column in store.ROAD_AXIS_COLUMNS))


class RoadAxisTest(unittest.TestCase):
    """RF-015-25, RF-017-23 (plan 017 §5.1): el eje por estaciones de la pista que escribió una operación, para dibujarlo con su rasante."""

    def test_the_axis_comes_with_the_level_of_the_grade_line_in_the_order_of_the_abscissa(self) -> None:
        """Las filas de ``des_rdx_`` de la operación que lo escribió salen como ``(n, 3)`` float64 con la x, la y **absolutas** y la cota **de la
        rasante** (la tercera columna es ``level_m``, no ``terrain_m``), por orden de abscisa aunque la tabla esté guardada en otro orden; la x y la
        y de un UTM de 4,4 Mm conservan el último bit (float64, regla 4)."""
        conn = _project()
        _axis(conn, "des_rdx_pista", [(20.0, 700020.125, 4400000.25, 101.0, 101.5), (0.0, 700000.125, 4400000.25, 100.0, 100.0),
                                      (10.0, 700010.125, 4400000.25, 100.5, 100.75)])
        _data(conn, "d1", "des_rdx_pista", "des_rdx_pista", "op1", "out", provenance.ROAD_AXIS_ROLE)
        found = entity_store.read_road_axis(conn, "op1")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual((found.shape, found.dtype), ((3, 3), np.float64))
        self.assertEqual(found.tolist(), [[700000.125, 4400000.25, 100.0], [700010.125, 4400000.25, 100.75], [700020.125, 4400000.25, 101.5]])

    def test_an_operation_without_its_axis_has_none(self) -> None:
        """La operación que solo lo consume, la que no escribió ninguno y la que no existe no tienen eje (``None``: la vista dibuja entonces el de
        la huella, a la cota de su superficie, y lo dice)."""
        conn = _project()
        _axis(conn, "des_rdx_pista", [(0.0, 1.0, 2.0, 3.0, 4.0)])
        _data(conn, "d1", "des_rdx_pista", "des_rdx_pista", "op1", "in", provenance.ROAD_AXIS_ROLE)
        _data(conn, "d2", "des_epr_pista", "des_epr_pista", "op2", "out", provenance.ENTITY_ROLE)
        for operation in ("op1", "op2", "otra"):
            with self.subTest(operation=operation):
                self.assertIsNone(entity_store.read_road_axis(conn, operation))

    def test_a_table_without_a_usable_axis_has_none(self) -> None:
        """Una tabla sin filas (se vaciaron fuera de Geoblender), con una sola estación (no hay eje) o con una cota que no es un número finito no
        da un eje a medias: ``None``."""
        for rows in ([], [(0.0, 1.0, 2.0, 3.0, 4.0)], [(0.0, 1.0, 2.0, 3.0, 4.0), (5.0, 2.0, 2.0, 3.0, float("nan"))]):
            with self.subTest(rows=len(rows)):
                conn = _project()
                _axis(conn, "des_rdx_pista", rows)
                _data(conn, "d1", "des_rdx_pista", "des_rdx_pista", "op1", "out", provenance.ROAD_AXIS_ROLE)
                self.assertIsNone(entity_store.read_road_axis(conn, "op1"))


class AccessSurfaceTest(unittest.TestCase):
    """RF-015-25, RF-017-24, RF-017-25 (plan 017 §5.1): la superficie sobre la que se hizo una accesibilidad, para dibujar lo alcanzable sobre ella."""

    def test_the_surface_is_the_input_with_the_role_of_a_surface_not_the_final_one(self) -> None:
        """La superficie de la accesibilidad es **su entrada con el papel de superficie** (``SURFACE_ROLE``); la final de una cantera, la capa de
        entradas y lo que escribió no lo son."""
        conn = _project()
        _data(conn, "d1", "des_exp_cantera", "rasters/des_exp_cantera.tif", "op1", "in", provenance.SURFACE_ROLE)
        _data(conn, "d2", "des_fin_cantera", "rasters/des_fin_cantera.tif", "op1", "in", provenance.ACCESS_FINAL_ROLE)
        _data(conn, "d3", "gis_fea_accesos", "gis_fea_accesos", "op1", "in", provenance.ACCESS_ENTRIES_ROLE)
        _data(conn, "d4", "des_acc_alcanzable", "rasters/des_acc_alcanzable.tif", "op1", "out", provenance.ROAD_ACCESS_ROLE)
        self.assertEqual(access_store.read_access_surface(conn, "op1"), "des_exp_cantera")

    def test_an_operation_that_did_not_consume_a_surface_has_none(self) -> None:
        """La operación que no consumió ninguna superficie (o que no existe) no tiene: ``None``, no un nombre inventado."""
        conn = _project()
        _data(conn, "d3", "gis_fea_accesos", "gis_fea_accesos", "op1", "in", provenance.ACCESS_ENTRIES_ROLE)
        _data(conn, "d4", "des_prp_alcanzable", "des_prp_alcanzable", "op1", "out", provenance.SURFACE_ROLE)  # una salida con ese papel no cuenta
        self.assertIsNone(access_store.read_access_surface(conn, "op1"))
        self.assertIsNone(access_store.read_access_surface(conn, "otra"))


if __name__ == "__main__":
    unittest.main()
