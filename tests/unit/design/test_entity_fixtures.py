# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera de las entidades de diseño (spec 015, T01; plan 015 §7.1 y §7.4; RF-015-19 como
contexto: la plataforma que define un eje con su ancho, o un polígono con su eje).

Recorre ``tests.support.entity_fixtures`` antes de que la usen las pruebas de la 015 (que aún no
existen), con cuentas a mano: la cantera de la 014 con sus capas de plataformas (cinco válidas,
tres de eje y dos de polígono, y los defectos de geometría que rechaza RF-015-08), el terreno
inclinado de 400 × 400 celdas de 1 m, la franja de 40 m con un tramo 5 m por debajo de la rasante
(CE-015-02) y su variante con un intocable que cruza la huella, la restricción declarada de prueba
(``DEC-PLT-001`` en la tabla de V01, que escribe la T16) y que la plantilla se construye en ≤ 2 s de
CPU. Y que los nombres de la 013, la
012 y la 014 en los que se apoya el plan 015 (§5) siguen ahí, y que ``reserves`` puede importar
``design`` (ARQ-07; T32).

Ningún dato de cliente: todo es sintético.
"""

from __future__ import annotations

import ast
import time
import unittest

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.repo import EXT, EXTENSION_DIR, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import imports  # noqa: E402

gis = import_geoblender("gis")
access = import_geoblender("gis.masks.access")

COPY_BUDGET_S = 1.0
"""Una copia del proyecto por clase, en menos de 1 s de CPU."""
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"

# Lo que ocupa lo de la cantera de la 014 (cajas locales conservadoras, a mano): los dos fondos, la
# zona a conservar, el relleno, la lámina de agua, «sin corte» y los dos tramos del corredor con su
# ancho (el eje, 10 m a cada lado).
QUARRY_BOXES: dict[str, tuple[float, float, float, float]] = {
    "Fondo 125": (120.0, 120.0, 200.0, 200.0),
    "Plataforma 175": (220.0, 200.0, 300.0, 260.0),
    "Conservar": (60.0, 180.0, 100.0, 240.0),
    "Relleno": (60.0, 80.0, 110.0, 140.0),
    "Lámina": (130.0, 300.0, 170.0, 330.0),
    "Sin corte": (60.0, 280.0, 100.0, 320.0),
    "Corredor, tramo 1": (200.0, 150.0, 330.0, 170.0),
    "Corredor, tramo 2": (310.0, 70.0, 330.0, 170.0),
}
# Lo que cubre la huella de cada plataforma válida (cajas locales; la de «taller» es la unión de
# tres: sus dos tramos y el cuarto de círculo de su codo, por la caja que lo contiene).
FOOTPRINTS: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "Plataforma de carga": ((110.0, 270.0, 310.0, 290.0),),
    "Plataforma de taller": ((125.0, 75.0, 245.0, 105.0), (230.0, 90.0, 260.0, 130.0),
                             (245.0, 75.0, 260.0, 105.0)),
    "Plataforma de la torre": ((290.0, 90.0, 310.0, 140.0),),
    "Explanada con eje": ((120.0, 210.0, 200.0, 260.0),),
    "Explanada sin eje": ((310.0, 180.0, 350.0, 260.0),),
}
# La cota más alta de la rasante de cada una (m, a mano: la inicial más la pendiente por lo más
# largo de su eje).
HAND_MAX_GRADE: dict[str, float] = {
    "Plataforma de carga": 252.0,  # 250 + 200 · 0,01
    "Plataforma de taller": 203.2,  # 200 + 160 · 0,02
    "Plataforma de la torre": 215.5,  # 215 + 50 · 0,01
    "Explanada con eje": 236.5,  # 235 + 100 · 0,015
    "Explanada sin eje": 240.4,  # 240 + 80 · 0,005
}


def _cells(box: tuple[float, float, float, float]) -> np.ndarray:
    return qfx.in_box(box)


def _footprint(name: str) -> np.ndarray:
    found = np.zeros(qfx.GRID.shape, dtype=bool)
    for box in FOOTPRINTS[name]:
        found |= _cells(box)
    return found


def _local(entity: tuple[tuple[np.ndarray, ...], ...]) -> list[np.ndarray]:
    """Los anillos o caminos de una entidad (partes) en coordenadas locales."""
    return [ring - np.asarray(cfx.BASE) for part in entity for ring in part]


def _orientation(o: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


def _cross(p: np.ndarray, q: np.ndarray, r: np.ndarray, s: np.ndarray) -> bool:
    """Si los segmentos ``pq`` y ``rs`` se cruzan en un punto interior de los dos."""
    return (_orientation(p, q, r) * _orientation(p, q, s) < 0
            and _orientation(r, s, p) * _orientation(r, s, q) < 0)


def _self_crossing(path: np.ndarray) -> bool:
    """Si dos segmentos no consecutivos de un camino (o un anillo) se cruzan."""
    count = len(path) - 1
    return any(_cross(path[i], path[i + 1], path[j], path[j + 1])
               for i in range(count) for j in range(i + 2, count)
               if not (i == 0 and j == count - 1 and np.array_equal(path[0], path[-1])))


def _length(path: np.ndarray) -> float:
    return float(np.hypot(*np.diff(path, axis=0).T).sum())


class PlaneTerrainTest(unittest.TestCase):
    """El terreno inclinado de 400 × 400 celdas de 1 m, sin proyecto."""

    def test_plane_by_hand(self) -> None:
        """Es un plano ``180 + 0,25·y + 0,0625·x``, exacto en binario: pasos constantes de −0,25 m
        por fila y +0,0625 m por columna, y los centros de las esquinas a mano."""
        z = efx.plane_terrain()
        self.assertEqual((z.shape, z.dtype), ((400, 400), np.float64))
        self.assertEqual(float(z[-1, 0]), 180.15625)  # el centro (0,5; 0,5): 180 + 0,125 + 0,03125
        self.assertEqual(float(z[0, -1]), 304.84375)  # el (399,5; 399,5): 180 + 99,875 + 24,96875
        self.assertTrue(np.all(np.diff(z, axis=0) == -efx.PLANE_NORTH_TAN))
        self.assertTrue(np.all(np.diff(z, axis=1) == efx.PLANE_EAST_TAN))
        self.assertEqual((efx.PLANE_NORTH_TAN, efx.PLANE_EAST_TAN), (0.25, 0.0625))

    def test_plane_is_the_quarry_hillside_without_the_scarp(self) -> None:
        """Es la ladera de la cantera sin el escarpe de 3 m: igual al sur de y = 300 y 3 m más baja
        al norte."""
        _x, y = qfx.local_centers()
        np.testing.assert_array_equal(efx.plane_terrain() + np.where(y > qfx.SCARP_Y, 3.0, 0.0),
                                      qfx.terrain())

    def test_a_new_array_every_time(self) -> None:
        z = efx.plane_terrain()
        z[0, 0] = 0.0
        self.assertNotEqual(float(efx.plane_terrain()[0, 0]), 0.0)

    def test_raster(self) -> None:
        raster = efx.plane_raster()
        self.assertEqual(raster.grid, qfx.GRID)
        self.assertEqual((raster.crs.epsg, raster.vertical.epsg), (25830, 5782))
        np.testing.assert_array_equal(raster.values, efx.plane_terrain())


class StripCaseTest(unittest.TestCase):
    """La franja de 40 m al 1 % con un tramo 5 m por debajo de la rasante (CE-015-02), sin
    proyecto y con las cuentas a mano."""

    def setUp(self) -> None:
        self.case = efx.strip_case()

    def test_footprint_and_axis(self) -> None:
        """El eje de 200 m (de (100, 200) a (300, 200)) con 40 m de ancho: 200 columnas de 40
        filas, 8.000 celdas; el tramo bajo la rasante, de 80 a 120 m del principio: 1.600."""
        case = self.case
        self.assertEqual(case.grid, qfx.GRID)
        self.assertEqual(case.axis.shape, (2, 2))
        np.testing.assert_array_equal(case.axis, cfx.absolute(efx.STRIP_AXIS_LOCAL))
        self.assertEqual(_length(case.axis), 200.0)
        self.assertEqual((case.width_m, case.grade_start_m, case.slope_pct), (40.0, 230.0, 1.0))
        self.assertEqual(int(case.footprint.sum()), efx.STRIP_FOOTPRINT_CELLS)
        self.assertEqual(efx.STRIP_FOOTPRINT_CELLS, 200 * 40)
        self.assertEqual(int(case.hollow.sum()), efx.STRIP_HOLLOW_CELLS)
        self.assertEqual(efx.STRIP_HOLLOW_CELLS, 40 * 40)
        self.assertTrue((case.hollow <= case.footprint).all())
        x, y = qfx.local_centers()
        self.assertEqual((float(x[case.footprint].min()), float(x[case.footprint].max())),
                         (100.5, 299.5))
        self.assertEqual((float(y[case.footprint].min()), float(y[case.footprint].max())),
                         (180.5, 219.5))
        self.assertEqual((float(x[case.hollow].min()), float(x[case.hollow].max())),
                         (180.5, 219.5))

    def test_grade_by_hand(self) -> None:
        """La rasante de cada celda de la huella es ``230 + σ · 0,01`` con σ la abscisa de su
        centro (``x − 100``): 230,005 en la primera columna y 231,995 en la última (≤ 10⁻⁹ m);
        fuera de la huella no hay."""
        case = self.case
        x, _y = qfx.local_centers()
        np.testing.assert_allclose(case.grade[case.footprint],
                                   (230.0 + (x - 100.0) * 0.01)[case.footprint],
                                   rtol=0.0, atol=1e-9)
        self.assertAlmostEqual(float(case.grade[case.footprint].min()), 230.005, places=9)
        self.assertAlmostEqual(float(case.grade[case.footprint].max()), 231.995, places=9)
        self.assertEqual((efx.STRIP_GRADE_FIRST_M, efx.STRIP_GRADE_LAST_M), (230.005, 231.995))
        self.assertTrue(np.isnan(case.grade[~case.footprint]).all())

    def test_terrain_is_6_m_above_and_5_m_below_in_the_stretch(self) -> None:
        """El terreno es un plano al 1 % 6 m por encima de la rasante y, en el tramo, 5 m por
        debajo (el resto de la rejilla sigue el mismo plano)."""
        case = self.case
        gap = (case.terrain - case.grade)[case.footprint & ~case.hollow]
        np.testing.assert_allclose(gap, efx.STRIP_ABOVE_M, rtol=0.0, atol=1e-9)
        np.testing.assert_allclose((case.terrain - case.grade)[case.hollow], -efx.STRIP_HOLLOW_M,
                                   rtol=0.0, atol=1e-9)
        self.assertEqual((efx.STRIP_ABOVE_M, efx.STRIP_HOLLOW_M), (6.0, 5.0))
        x, _y = qfx.local_centers()
        outside = ~case.hollow
        np.testing.assert_allclose(case.terrain[outside], (236.0 + (x - 100.0) * 0.01)[outside],
                                   rtol=0.0, atol=1e-9)
        self.assertFalse(np.isnan(case.terrain).any())

    def test_masks_and_volumes_by_hand(self) -> None:
        """Sin restricciones se admite todo: «en corte» baja 6 m en las 6.400 celdas por encima
        (38.400 m³ y nada de relleno, el lomo de B7); «en corte y relleno» sube además las 1.600
        del tramo, 5 m (8.000 m³)."""
        case = self.case
        self.assertTrue(case.cut_allowed.all() and case.fill_allowed.all())
        self.assertFalse(case.blocked.any())
        above = np.where(case.terrain > case.grade, case.terrain - case.grade, 0.0)
        below = np.where(case.terrain < case.grade, case.grade - case.terrain, 0.0)
        self.assertAlmostEqual(float(above[case.footprint & case.cut_allowed].sum()),
                               efx.STRIP_CUT_M3, places=6)
        self.assertAlmostEqual(float(below[case.footprint & case.fill_allowed].sum()),
                               efx.STRIP_FILL_M3, places=6)
        self.assertEqual((efx.STRIP_CUT_M3, efx.STRIP_FILL_M3), (6.0 * 6_400.0, 5.0 * 1_600.0))
        self.assertEqual(int((below > 0.0)[case.footprint].sum()), efx.STRIP_HOLLOW_CELLS)
        self.assertEqual(case.cut_m3, efx.STRIP_CUT_M3)
        self.assertEqual(case.fill_m3, efx.STRIP_FILL_M3)

    def test_untouchable_across_the_footprint(self) -> None:
        """Con el intocable, una banda de 10 m (de 140 a 150 en x) que cruza la huella de lado a
        lado y sobresale 10 m por cada lado: 400 celdas de la huella (10 · 40) que ni se cortan ni
        se rellenan, fuera del tramo bajo la rasante; el corte baja a 6 · 6.000 = 36.000 m³ y el
        relleno sigue en 8.000 m³."""
        case = efx.strip_case(untouchable=True)
        band = _cells(efx.UNTOUCHABLE_BOX)
        self.assertEqual(int(band.sum()), 10 * 60)
        self.assertEqual(int(case.blocked.sum()), efx.STRIP_BLOCKED_CELLS)
        self.assertEqual(efx.STRIP_BLOCKED_CELLS, 10 * 40)
        np.testing.assert_array_equal(case.blocked, band & case.footprint)
        self.assertFalse((case.blocked & case.hollow).any())
        np.testing.assert_array_equal(case.cut_allowed, ~band)
        np.testing.assert_array_equal(case.fill_allowed, ~band)
        rows = np.flatnonzero(case.blocked.any(axis=1))
        self.assertEqual(rows.size, 40)  # cruza la huella entera: de borde a borde
        plain = efx.strip_case()
        np.testing.assert_array_equal(case.terrain, plain.terrain)
        np.testing.assert_array_equal(case.footprint, plain.footprint)
        above = np.where(case.terrain > case.grade, case.terrain - case.grade, 0.0)
        below = np.where(case.terrain < case.grade, case.grade - case.terrain, 0.0)
        self.assertAlmostEqual(float(above[case.footprint & case.cut_allowed].sum()),
                               efx.STRIP_CUT_BLOCKED_M3, places=6)
        self.assertAlmostEqual(float(below[case.footprint & case.fill_allowed].sum()),
                               efx.STRIP_FILL_M3, places=6)
        self.assertEqual((case.cut_m3, case.fill_m3), (efx.STRIP_CUT_BLOCKED_M3,
                                                       efx.STRIP_FILL_M3))
        self.assertEqual(efx.STRIP_CUT_BLOCKED_M3, 6.0 * 6_000.0)
        self.assertEqual(case.blocked_by, efx.UNTOUCHABLE_NAME)

    def test_a_new_array_every_time(self) -> None:
        case = efx.strip_case()
        for name in ("terrain", "footprint", "grade", "hollow", "cut_allowed", "fill_allowed",
                     "blocked", "axis"):
            getattr(case, name)[...] = 0
        again = efx.strip_case()
        self.assertEqual(int(again.footprint.sum()), efx.STRIP_FOOTPRINT_CELLS)
        self.assertTrue(again.cut_allowed.all())
        self.assertFalse(np.isnan(again.terrain).any())


class DownstreamStripCaseTest(unittest.TestCase):
    """La variante de la franja con el tramo bajo la rasante **aguas abajo** (T10, el caso base de
    CE-015-02): la rasante sube con la abscisa (+ 1 %), así que baja hacia su abscisa 0, el extremo
    de menor ``x``; el tramo (los 40 m del principio del eje) está en ese extremo y el perfil
    longitudinal solo baja. Con la del medio (``strip_case()``), el perfil vuelve a subir aguas
    abajo del tramo: es una contrapendiente (RF-015-23). Cuentas a mano."""

    def setUp(self) -> None:
        self.case = efx.strip_case(hollow="downstream")
        self.middle = efx.strip_case()

    def test_the_stretch_is_the_first_40_m_of_the_axis(self) -> None:
        """El tramo bajo la rasante es la caja de x de 100 a 140 (la abscisa 0 a 40 m) y de y de 180
        a 220: 40 columnas de 40 filas = 1.600 celdas, las mismas que la del medio, dentro de la
        huella; el centro de la primera columna es x = 100,5 y el de la última, 139,5."""
        case = self.case
        x, y = qfx.local_centers()
        self.assertEqual(efx.STRIP_DOWNSTREAM_HOLLOW_BOX, (100.0, 180.0, 140.0, 220.0))
        self.assertEqual(int(case.hollow.sum()), 40 * 40)
        self.assertEqual(int(case.hollow.sum()), efx.STRIP_HOLLOW_CELLS)
        self.assertTrue((case.hollow <= case.footprint).all())
        self.assertEqual((float(x[case.hollow].min()), float(x[case.hollow].max())), (100.5, 139.5))
        self.assertEqual((float(y[case.hollow].min()), float(y[case.hollow].max())), (180.5, 219.5))
        self.assertEqual(case.hollow_at, "downstream")
        self.assertEqual(self.middle.hollow_at, "middle")

    def test_it_is_the_downstream_end_of_the_grade(self) -> None:
        """Con la rasante ``230 + (x − 100) · 0,01`` (+ 1 %), la menor cota está en x = 100: el tramo
        queda en las abscisas más bajas de la rasante (230,005 a 230,395 m), y el resto de la huella,
        más arriba (230,405 a 231,995 m)."""
        case = self.case
        x, _y = qfx.local_centers()
        self.assertGreater(case.slope_pct, 0.0)
        self.assertLess(float(case.grade[case.hollow].max()), float(case.grade[
            case.footprint & ~case.hollow].min()))
        self.assertAlmostEqual(float(case.grade[case.hollow].min()), 230.005, places=9)
        self.assertAlmostEqual(float(case.grade[case.hollow].max()), 230.395, places=9)
        self.assertAlmostEqual(float(case.grade[case.footprint & ~case.hollow].min()), 230.405,
                               places=9)
        self.assertTrue((x[case.hollow] < 140.0).all())

    def test_the_terrain_is_6_m_above_and_5_m_below_in_the_stretch(self) -> None:
        """El terreno sigue el mismo plano al 1 %: 5 m por debajo de la rasante en el tramo y 6 m
        por encima en el resto de la huella; fuera del tramo, igual que el de la del medio."""
        case = self.case
        gap = case.terrain - case.grade
        np.testing.assert_allclose(gap[case.hollow], -efx.STRIP_HOLLOW_M, rtol=0.0, atol=1e-9)
        np.testing.assert_allclose(gap[case.footprint & ~case.hollow], efx.STRIP_ABOVE_M, rtol=0.0,
                                   atol=1e-9)
        outside = ~(case.hollow | self.middle.hollow)
        np.testing.assert_array_equal(case.terrain[outside], self.middle.terrain[outside])
        self.assertFalse(np.isnan(case.terrain).any())

    def test_same_figures_as_the_middle_one(self) -> None:
        """El mismo eje, la misma huella, la misma rasante y las mismas cuentas a mano: 38.400 m³ de
        corte y 8.000 de relleno, 6.400 celdas por encima y 1.600 por debajo."""
        case, middle = self.case, self.middle
        np.testing.assert_array_equal(case.axis, middle.axis)
        np.testing.assert_array_equal(case.footprint, middle.footprint)
        np.testing.assert_array_equal(case.grade[case.footprint], middle.grade[middle.footprint])
        above = np.where(case.terrain > case.grade, case.terrain - case.grade, 0.0)
        below = np.where(case.terrain < case.grade, case.grade - case.terrain, 0.0)
        self.assertAlmostEqual(float(above[case.footprint].sum()), efx.STRIP_CUT_M3, places=6)
        self.assertAlmostEqual(float(below[case.footprint].sum()), efx.STRIP_FILL_M3, places=6)
        self.assertEqual((case.cut_m3, case.fill_m3), (efx.STRIP_CUT_M3, efx.STRIP_FILL_M3))
        self.assertEqual(int((above > 0.0)[case.footprint].sum()), 6_400)
        self.assertEqual(int((below > 0.0)[case.footprint].sum()), 1_600)

    def test_with_the_untouchable_it_does_not_touch_the_stretch(self) -> None:
        """El intocable (x de 140 a 150) queda aguas arriba del tramo, pegado a él: las mismas 400
        celdas bloqueadas fuera del tramo, 36.000 m³ de corte y los mismos 8.000 de relleno."""
        case = efx.strip_case(untouchable=True, hollow="downstream")
        self.assertEqual(int(case.blocked.sum()), efx.STRIP_BLOCKED_CELLS)
        self.assertFalse((case.blocked & case.hollow).any())
        self.assertEqual((case.cut_m3, case.fill_m3), (efx.STRIP_CUT_BLOCKED_M3,
                                                       efx.STRIP_FILL_M3))
        self.assertEqual(case.blocked_by, efx.UNTOUCHABLE_NAME)
        self.assertEqual(case.hollow_at, "downstream")

    def test_an_unknown_place_is_an_error(self) -> None:
        """Un lugar que no es «middle» ni «downstream» es un error del programa."""
        with self.assertRaises(ValueError):
            efx.strip_case(hollow="upstream")


class LayersTest(unittest.TestCase):
    """La capa de ejes y la de polígonos de las plataformas, sin proyecto."""

    def setUp(self) -> None:
        self.axes, self.polygons = efx.platform_layers()

    def test_the_two_layers(self) -> None:
        """Una capa de líneas con los campos de un corredor (``ancho``, ``cota_inicial`` y
        ``pendiente``: D-15, sirve de capa de corredores de la cantera) y una de polígonos con
        la cota, la pendiente y ``eje``, el enlace con su eje por el número de entidad (``fid``)
        de la capa de ejes; no chocan con las cinco de la cantera."""
        self.assertEqual((self.axes.name, self.axes.kind), (efx.AXES_LAYER, "line"))
        self.assertEqual((self.polygons.name, self.polygons.kind), (efx.POLYGONS_LAYER, "polygon"))
        self.assertEqual(tuple(self.axes.fields), ("ancho", "cota_inicial", "pendiente"))
        self.assertEqual(tuple(self.polygons.fields), ("cota_inicial", "pendiente", "eje"))
        self.assertEqual(efx.LINK_FIELD, "eje")
        self.assertEqual(efx.LAYERS, (efx.AXES_LAYER, efx.POLYGONS_LAYER))
        self.assertTrue(set(efx.LAYERS).isdisjoint(qfx.LAYERS))
        for layer in (self.axes, self.polygons):
            self.assertEqual(len(set(layer.names)), len(layer.names), layer.name)
            self.assertEqual(len(layer.entities), len(layer.names))
            self.assertTrue(layer.name.startswith("gis_fea_"))
        self.assertEqual(self.axes.names, tuple(spec.name for spec in efx.AXES))
        self.assertEqual(self.polygons.names, tuple(spec.name for spec in efx.POLYGONS))

    def test_valid_axes_by_hand(self) -> None:
        """Los ejes de las plataformas válidas: «carga» (200 m, 20 m de ancho, de 250 m al 1 %),
        «taller» (120 + 40 m con un codo, 30 m de ancho, de 200 m al 2 %), «torre» (50 m, 20 m, de
        215 m al 1 %) y el eje de enlace de la explanada (100 m, sin los campos)."""
        hand = (("Plataforma de carga", 200.0, 20.0, 250.0, 1.0, 2),
                ("Plataforma de taller", 160.0, 30.0, 200.0, 2.0, 3),
                ("Plataforma de la torre", 50.0, 20.0, 215.0, 1.0, 2),
                ("Eje de la explanada", 100.0, None, None, None, 2))
        for index, (name, length, width, start, gradient, vertices) in enumerate(hand):
            self.assertEqual(self.axes.names[index], name)
            (path,) = _local(self.axes.entities[index])
            self.assertEqual((len(path), _length(path)), (vertices, length), name)
            self.assertEqual(self.axes.fields["ancho"][index], width, name)
            self.assertEqual(self.axes.fields["cota_inicial"][index], start, name)
            self.assertEqual(self.axes.fields["pendiente"][index], gradient, name)
            self.assertFalse(_self_crossing(path), name)
            self.assertFalse(np.array_equal(path[0], path[-1]), name)
            self.assertTrue(all(isinstance(part, tuple) and len(part) == 1
                                for part in self.axes.entities[index]))
        taller = _local(self.axes.entities[1])[0]
        np.testing.assert_array_equal(taller, [(125.0, 90.0), (245.0, 90.0), (245.0, 130.0)])

    def test_axis_defects_by_hand(self) -> None:
        """Los ejes con defecto (RF-015-08), en el margen este, fuera del perímetro: el que se
        corta a sí mismo (sus tramos 1 y 3 se cruzan), el cerrado (acaba donde empieza), el de
        longitud cero, el que no tiene ancho y el corto (que no cruza su polígono)."""
        defects = {spec.name: spec.defect for spec in efx.AXES if spec.defect}
        self.assertEqual(defects, {
            "Eje que se corta": efx.SELF_INTERSECTING, "Eje cerrado": efx.CLOSED,
            "Eje de longitud cero": efx.ZERO_LENGTH, "Eje sin ancho": efx.NO_WIDTH,
            "Eje corto": efx.SHORT})
        paths = {name: _local(self.axes.entities[index])[0]
                 for index, name in enumerate(self.axes.names)}
        self.assertTrue(_self_crossing(paths["Eje que se corta"]))
        closed = paths["Eje cerrado"]
        self.assertTrue(np.array_equal(closed[0], closed[-1]))
        self.assertFalse(_self_crossing(closed))
        self.assertEqual(_length(paths["Eje de longitud cero"]), 0.0)
        self.assertEqual(_length(paths["Eje corto"]), 20.0)
        index = self.axes.names.index("Eje sin ancho")
        self.assertIsNone(self.axes.fields["ancho"][index])
        self.assertEqual(self.axes.fields["cota_inicial"][index], 200.0)
        for name, path in paths.items():  # fuera de la concesión (que acaba en x = 360)
            if name in defects:
                self.assertGreaterEqual(float(path[:, 0].min()), 360.0, name)

    def test_valid_polygons_by_hand(self) -> None:
        """Los polígonos válidos: «Explanada con eje» (80 × 50 m, 4.000 celdas, de 235 m al 1,5 %,
        enlazada con el eje de la explanada, que la cruza de lado a lado) y «Explanada sin eje» (40
        × 80 m, 3.200 celdas, de 240 m al 0,5 %, sin enlace: su eje principal es el de los 80 m,
        el norte-sur, con su extremo más al sur como abscisa 0)."""
        link = self.polygons.fields[efx.LINK_FIELD]
        self.assertEqual(self.polygons.names[:2], ("Explanada con eje", "Explanada sin eje"))
        self.assertEqual(self.polygons.fields["cota_inicial"][:2], (235.0, 240.0))
        self.assertEqual(self.polygons.fields["pendiente"][:2], (1.5, 0.5))
        self.assertEqual(int(_footprint("Explanada con eje").sum()), 4_000)
        self.assertEqual(int(_footprint("Explanada sin eje").sum()), 3_200)
        self.assertEqual(efx.axis_fid("Eje de la explanada"), 4)
        self.assertEqual(link[0], 4.0)
        self.assertIsNone(link[1])
        left, bottom, right, top = FOOTPRINTS["Explanada con eje"][0]
        (axis,) = _local(self.axes.entities[efx.axis_fid("Eje de la explanada") - 1])
        self.assertLess(axis[0, 0], left)  # entra por el oeste y sale por el este
        self.assertGreater(axis[1, 0], right)
        self.assertTrue(bottom < axis[0, 1] == axis[1, 1] < top)
        left, bottom, right, top = FOOTPRINTS["Explanada sin eje"][0]
        self.assertGreater(top - bottom, right - left)  # más larga de norte a sur
        for name in ("Explanada con eje", "Explanada sin eje"):
            self.assertIsNone(next(s for s in efx.POLYGONS if s.name == name).defect)

    def test_polygon_defects_by_hand(self) -> None:
        """Los polígonos con defecto (RF-015-08), en el margen este: el que se corta a sí mismo
        (un lazo), el de área cero (sus tres vértices alineados), el sin celdas (0,3 × 0,3 m entre
        dos centros) y el enlazado con un eje que no lo cruza (entra por un lado y acaba dentro)."""
        defects = {spec.name: spec.defect for spec in efx.POLYGONS if spec.defect}
        self.assertEqual(defects, {
            "Polígono que se corta": efx.SELF_INTERSECTING, "Polígono sin área": efx.ZERO_AREA,
            "Polígono sin celdas": efx.NO_CELLS,
            "Explanada con eje que no la cruza": efx.AXIS_DOES_NOT_CROSS})
        rings = {name: _local(self.polygons.entities[index])[0]
                 for index, name in enumerate(self.polygons.names)}
        self.assertTrue(_self_crossing(rings["Polígono que se corta"]))
        self.assertEqual(cfx.ring_area(self.polygons.entities[3][0][0]), 0.0)
        tiny = rings["Polígono sin celdas"]
        self.assertAlmostEqual(cfx.ring_area(self.polygons.entities[4][0][0]), 0.09, places=8)
        box = (float(tiny[:, 0].min()), float(tiny[:, 1].min()), float(tiny[:, 0].max()),
               float(tiny[:, 1].max()))
        self.assertEqual(int(_cells(box).sum()), 0)
        index = self.polygons.names.index("Explanada con eje que no la cruza")
        link = self.polygons.fields[efx.LINK_FIELD][index]
        self.assertEqual(link, float(efx.axis_fid("Eje corto")))
        (short,) = _local(self.axes.entities[int(link) - 1])
        ring = rings["Explanada con eje que no la cruza"]
        left, bottom, right, top = (float(ring[:, 0].min()), float(ring[:, 1].min()),
                                    float(ring[:, 0].max()), float(ring[:, 1].max()))
        inside = [bool(left < px < right and bottom < py < top) for px, py in short]
        self.assertEqual(inside, [False, True])  # entra, y no sale
        for name, ring in rings.items():
            if name in defects:
                self.assertGreaterEqual(float(ring[:, 0].min()), 365.0, name)

    def test_linking_by_fid(self) -> None:
        """El enlace es el ``fid`` de la capa de ejes (1, 2… en el orden de las entidades)."""
        self.assertEqual([efx.axis_fid(name) for name in self.axes.names],
                         list(range(1, len(self.axes.names) + 1)))
        with self.assertRaises(KeyError):
            efx.axis_fid("Eje que no existe")
        for index, spec in enumerate(efx.POLYGONS):
            want = None if spec.axis is None else float(efx.axis_fid(spec.axis))
            self.assertEqual(self.polygons.fields[efx.LINK_FIELD][index], want, spec.name)

    def test_valid_platforms_are_apart_and_inside_the_quarry(self) -> None:
        """Las huellas de las plataformas válidas no se tocan entre sí ni tocan lo de la cantera
        de la 014 (fondos, conservar, relleno, lámina, «sin corte» y corredor)."""
        names = list(FOOTPRINTS)
        for first in range(len(names)):
            for second in range(first + 1, len(names)):
                self.assertFalse((_footprint(names[first]) & _footprint(names[second])).any(),
                                 (names[first], names[second]))
        quarry = {name: _cells(box) for name, box in QUARRY_BOXES.items()}
        for name in names:
            for other, cells in quarry.items():
                self.assertFalse((_footprint(name) & cells).any(), (name, other))
        self.assertEqual(sorted(FOOTPRINTS), sorted(efx.VALID_NAMES))

    def test_the_hillside_is_above_the_grade_of_every_valid_platform(self) -> None:
        """Sobre la ladera de la cantera, la rasante de cada plataforma válida queda por debajo de
        todo el terreno de su huella (corta del todo: es el caso normal de «en corte»)."""
        z = qfx.terrain()
        for name, top in HAND_MAX_GRADE.items():
            self.assertGreater(float(z[_footprint(name)].min()), top, name)

    def test_a_new_array_every_time(self) -> None:
        self.axes.entities[0][0][0][...] = 0.0
        self.assertNotEqual(float(efx.platform_layers()[0].entities[0][0][0][0, 0]), 0.0)


class EntityProjectTest(efx.EntityProjectCase):
    """El proyecto de la cantera con la capa de plataformas."""

    def test_built_once_within_budget(self) -> None:
        """La plantilla se crea una vez por proceso en ≤ 2 s de CPU (lo que añade a la cantera de
        la 014) y cada clase la copia en menos de 1 s."""
        template = efx.project_template()
        self.assertIs(template, efx.project_template())
        self.assertLessEqual(template["build_s"], efx.BUILD_BUDGET_S)
        started = time.process_time()
        with efx.open_entity_project() as (_project, _clock):
            elapsed = time.process_time() - started
        self.assertLess(elapsed, COPY_BUDGET_S)

    def test_the_quarry_is_still_there(self) -> None:
        """Lo de la cantera sigue igual: V01 y V02, las cuatro restricciones, las cinco capas, el
        terreno de partida y las máscaras de V01 al día con sus cuentas a mano."""
        self.assertEqual((self.v1.code, self.v2.code), ("V01", "V02"))
        self.assertEqual(self.grid, qfx.GRID)
        self.assertEqual(tuple(sorted(item.code for item in self.stored_constraints())),
                         qfx.CONSTRAINT_CODES)
        for layer in qfx.layers():
            found = self.read_layer(layer.name)
            self.assertTrue(qfx.same_entities(found.parts, layer.entities), layer.name)
        raster = import_geoblender("gis.store").load_raster(self.project, qfx.START_DATASET)
        np.testing.assert_array_equal(raster.values, qfx.terrain())
        state, pending = access.mask_state(self.project, self.v1.uid)
        self.assertIs(state, access.MaskState.CURRENT)
        self.assertEqual(pending, ())
        self.assertEqual(int(self.masks().cut_allowed().sum()), qfx.CUT_ALLOWED_CELLS)
        self.assertIs(access.mask_state(self.project, self.v2.uid)[0], access.MaskState.MISSING)

    def test_layers_read_back(self) -> None:
        """Las dos capas están en el proyecto como capas de entidades y se leen con su geometría
        bit a bit, sus nombres, sus ``fid`` (1, 2…) y sus campos, también los vacíos."""
        for layer in efx.platform_layers():
            record = self.record(layer.name)
            self.assertIsNotNone(record, layer.name)
            found = self.read_layer(layer.name)
            self.assertEqual(found.kind, layer.kind, layer.name)
            self.assertEqual(found.fids, tuple(range(1, len(layer.names) + 1)))
            self.assertTrue(qfx.same_entities(found.parts, layer.entities), layer.name)
            self.assertEqual(tuple(found.values["nombre"]), layer.names)
            for field, values in layer.fields.items():
                self.assertEqual(tuple(found.values[field]), values, (layer.name, field))

    def test_link_survives_the_project(self) -> None:
        """Leído del proyecto, el ``eje`` de «Explanada con eje» es el ``fid`` de la línea que se
        llama «Eje de la explanada»."""
        axes = self.read_layer(efx.AXES_LAYER)
        polygons = self.read_layer(efx.POLYGONS_LAYER)
        link = polygons.values[efx.LINK_FIELD][polygons.values["nombre"].index("Explanada con eje")]
        fid = axes.fids[axes.values["nombre"].index("Eje de la explanada")]
        self.assertEqual(link, float(fid))

    def test_footprints_against_the_masks(self) -> None:
        """Las plataformas válidas caen en el corte admitido de V01, salvo lo que pisa la torre
        (su zona de 224 celdas, dentro de la huella de la plataforma de la torre: ni se corta ni se
        rellena en ella)."""
        masks = self.masks()
        cut, fill = masks.cut_allowed(), masks.fill_allowed()
        zone = masks.zone("torre")
        crossing = np.zeros(self.grid.shape, dtype=bool)
        for row, col0, col1 in zip(zone.row, zone.col0, zone.col1, strict=True):
            crossing[row, col0:col1] = True
        self.assertEqual((zone.cells, int(crossing.sum())), (qfx.TOWER_ZONE_CELLS,) * 2)
        for name in FOOTPRINTS:
            footprint = _footprint(name)
            if name == "Plataforma de la torre":
                self.assertEqual(int((footprint & cut).sum()),
                                 int(footprint.sum()) - qfx.TOWER_ZONE_CELLS)
                self.assertEqual(int(footprint.sum()), 1_000)
            else:
                self.assertTrue(cut[footprint].all(), name)
        self.assertFalse((crossing & cut).any())
        self.assertFalse((crossing & fill).any())
        self.assertTrue((crossing <= _footprint("Plataforma de la torre")).all())


class DeclaredConstraintFixtureTest(efx.DeclaredConstraintsProjectCase):
    """La restricción declarada de prueba (T16; RF-012-29, RF-015-10): la variante de
    ``constraints_project`` con ``DEC-PLT-001`` en la tabla de V01 (``des_decl_v01``), que ya no es
    un hueco: la escribe ``core.constraints.declared.write_declared`` con una operación de prueba."""

    def declared_rows(self, version: object) -> tuple[object, ...]:
        declared = import_geoblender("core.constraints.declared")
        with self.project.read() as conn:
            return declared.read_declared(conn, declared.declared_table(version.code))

    def test_the_declared_constraint_is_in_the_table_of_v01(self) -> None:
        """RF-012-29, RF-015-10: V01 tiene su tabla ``des_decl_v01`` viva y **no editable en QGIS**,
        escrita por una operación de ``des.declare_constraints`` de esa versión con una restricción,
        ``DEC-PLT-001`` («sin relleno», entidad «P1», su motivo generado, el decisor y la fecha de la
        decisión, el resguardo de 4 m y activa); V02 no tiene ninguna ni la del proyecto cambia."""
        declared = import_geoblender("core.constraints.declared")
        record = self.record("des_decl", self.v1)
        self.assertIsNotNone(record)
        self.assertEqual((record.locator, record.module, record.kind, record.live,
                          record.qgis_editable, record.operation_uid),
                         ("des_decl_v01", "des", "vector", True, False, self.declared_operation))
        self.assertIsNone(self.record("des_decl", self.v2))
        self.assertEqual(self.declared_rows(self.v2), ())
        (row,) = self.declared_rows(self.v1)
        self.assertEqual((row.code, row.entity_code, row.entity_name, row.name, row.ctype.value),
                         (efx.DECLARED_CODE, efx.DECLARED_ENTITY, "P1", "P1", "no_fill"))
        self.assertEqual((row.reason, row.decided_by, row.decided_on, row.buffer_out_m, row.active),
                         ("declarada por la plataforma P1", efx.DECLARED_BY, efx.DECLARED_ON,
                          efx.DECLARED_GUARD_M, True))
        self.assertEqual(row.uid, declared.declared_uid(self.v1.uid, efx.DECLARED_ENTITY))
        self.assertEqual(len(self.stored_constraints()), 5)  # nada en las tres capas del proyecto
        self.assertFalse(any(item.code == efx.DECLARED_CODE for item in self.stored_constraints()))

    def test_the_cell_rule_gives_the_footprint_and_grows_with_the_guard(self) -> None:
        """RF-012-29, D-23: con la regla de la celda de la 012 la restricción guardada da las 300 celdas
        de la huella con resguardo 0 y, con su resguardo de 4 m (dos celdas), el bloque de 24 × 19
        celdas; ninguna toca la balsa, la torre ni la cuneta."""
        zones = import_geoblender("gis.masks.zones")
        (row,) = self.declared_rows(self.v1)
        item = row.as_constraint()
        footprint = efx.declared_footprint()
        self.assertEqual(int(footprint.sum()), efx.DECLARED_CELLS)
        self.assertTrue(np.array_equal(zones.zone_runs(item, cfx.SITE_GRID, 0.0).mask(
            cfx.SITE_GRID.shape), footprint))
        grown = zones.zone_runs(item, cfx.SITE_GRID, row.buffer_out_m).mask(cfx.SITE_GRID.shape)
        self.assertEqual(int(grown.sum()), 24 * 19)
        self.assertTrue(grown[footprint].all())
        self.assertTrue(item.declared)
        self.assertEqual(item.entity_code, efx.DECLARED_ENTITY)

    def test_the_code_and_zone_are_free(self) -> None:
        """El código ``DEC-<entidad>`` (``DEC-PLT-001``) no choca con las restricciones de
        ``constraints_project`` ni con las de la cantera, y su caja cabe en el sitio de
        ``constraints_project`` (300 celdas de 2 m) sin tocar su balsa, su torre ni su cuneta."""
        self.assertEqual(efx.DECLARED_CODE, f"DEC-{efx.DECLARED_ENTITY}")
        self.assertRegex(efx.DECLARED_ENTITY, r"^PLT-\d{3}$")
        taken = {item.code for item in cp.constraints()} | {item.code for item in qfx.constraints()}
        self.assertNotIn(efx.DECLARED_CODE, taken)
        x, y = cfx.site_centers()
        left, bottom, right, top = efx.DECLARED_BOX_LOCAL
        box = (x > left) & (x < right) & (y > bottom) & (y < top)
        self.assertEqual(int(box.sum()), 300)  # 40 · 30 m = 1.200 m² / 4 m²
        pond = (x > cfx.POND_LOCAL[0]) & (x < cfx.POND_LOCAL[2]) & (y > cfx.POND_LOCAL[1]) & (
            y < cfx.POND_LOCAL[3])
        self.assertFalse((box & pond).any())
        tower_x, tower_y = cfx.TOWER_LOCAL
        self.assertFalse(((np.abs(x - tower_x) < cfx.TOWER_OUTWARD_M + 2.0)
                          & (np.abs(y - tower_y) < cfx.TOWER_OUTWARD_M + 2.0) & box).any())
        for point in cp.DITCH_LOCAL:
            self.assertFalse(left - cp.DITCH_OUTWARD_M < point[0] < right + cp.DITCH_OUTWARD_M
                             and bottom - cp.DITCH_OUTWARD_M < point[1] < top + cp.DITCH_OUTWARD_M)
        self.assertGreater(efx.DECLARED_GUARD_M, 0.0)


class DeclaredInOtherVersionTest(efx.DeclaredConstraintsProjectCase):
    """RF-012-29: una declarada es de **su versión**: declarar en V02 escribe ``des_decl_v02`` (con
    otro ``uid``, que sale de la versión) y deja la de V01 como estaba."""

    def test_declaring_in_v02_does_not_touch_v01(self) -> None:
        declared = import_geoblender("core.constraints.declared")
        with self.project.read() as conn:
            before = declared.read_declared(conn, "des_decl_v01")
            digest = self.record("des_decl", self.v1).content_sha256
        operation = efx.declare_platform_constraint(self.project, self.clock, version=self.v2)
        self.assertNotEqual(operation, self.declared_operation)
        self.assertEqual(self.record("des_decl", self.v2).locator, "des_decl_v02")
        with self.project.read() as conn:
            (first,) = declared.read_declared(conn, "des_decl_v01")
            (second,) = declared.read_declared(conn, "des_decl_v02")
        self.assertEqual(before[0].uid, first.uid)
        self.assertEqual(self.record("des_decl", self.v1).content_sha256, digest)
        self.assertEqual((first.code, second.code), (efx.DECLARED_CODE, efx.DECLARED_CODE))
        self.assertNotEqual(first.uid, second.uid)
        self.assertEqual(second.uid, declared.declared_uid(self.v2.uid, efx.DECLARED_ENTITY))


class PlanNamesTest(unittest.TestCase):
    """Los nombres de ``main`` en los que se apoya el plan 015 (§5) existen con la forma que dice,
    y ``reserves`` puede importar ``design`` (T32)."""

    def test_domain_names(self) -> None:
        store = import_geoblender("design.store")
        provenance = import_geoblender("design.provenance")
        steps = import_geoblender("design.steps")
        zones_mod = import_geoblender("design.zones")
        quarry = import_geoblender("design.quarry")
        sectors = import_geoblender("design.sectors")
        cstore = import_geoblender("core.constraints.store")
        compliance = import_geoblender("reserves.compliance_store")
        self.assertTrue(isinstance(store.DesignWriter, type))
        for name in ("require_version", "masks_steps"):
            self.assertTrue(callable(getattr(store, name)), name)
        self.assertIsInstance(store.RECOMPUTED, tuple)
        self.assertTrue(isinstance(provenance.OperationType, type))
        for op_type in (provenance.ENVELOPE, provenance.STEPPED, provenance.QUARRY):
            self.assertIn(op_type, provenance.OPERATION_TYPES_BY_NAME)
        self.assertEqual(provenance.DESIGN_SURFACE_ROLE, "design_surface")
        self.assertIsInstance(provenance.CREATED_STEP_PARAMS, tuple)
        self.assertTrue(isinstance(steps.Calculation, type))
        self.assertTrue(callable(zones_mod.layer_cells))
        self.assertTrue(callable(quarry.corridor_cells))
        self.assertTrue(callable(sectors.refuse_pending))
        for name in ("read_constraints", "write_constraints", "layer_of", "dataset_specs"):
            self.assertTrue(callable(getattr(cstore, name)), name)
        self.assertTrue(callable(access.load_masks))
        self.assertTrue(callable(compliance.freeze_findings))

    def test_blender_names(self) -> None:
        """``bl/scene/views.BRANCHES`` y ``bl/props/core.OBJECT_KINDS`` (que ``bl`` no deja
        importar aquí) se leen del código: hoy llevan el ``DESIGN`` de la 013 y todavía no el
        ``DESIGN_ENTITY`` de la 015 (T28)."""
        for module, name in (("scene/views.py", "BRANCHES"), ("props/core.py", "OBJECT_KINDS")):
            source = (EXTENSION_DIR / "bl" / module).read_text(encoding="utf-8")
            texts = None
            for node in ast.parse(source).body:
                target = node.targets[0] if isinstance(node, ast.Assign) else getattr(
                    node, "target", None)
                if isinstance(target, ast.Name) and target.id == name:
                    texts = {part.value for part in ast.walk(node.value)
                             if isinstance(part, ast.Constant) and isinstance(part.value, str)}
            self.assertIsNotNone(texts, f"{module} no declara {name}")
            self.assertIn("DESIGN", texts)

    def test_reserves_may_import_design(self) -> None:
        """T32: ARQ-07 (nivel 8 de ``design``, nivel 9 de ``reserves``) deja a ``reserves``
        importar ``design`` —el test AST de ``design`` solo lo prohíbe al revés—, y ya lo hace:
        ``reserves/compliance_store.py`` importa ``design.provenance``. Lo prohibido es el
        sentido contrario (control positivo)."""
        levels = imports.LEVELS
        self.assertLess(levels["design"], levels["reserves"])
        source = (EXTENSION_DIR / "reserves" / "compliance_store.py").read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(node, ast.ImportFrom) and node.level == 2
                            and (node.module or "").partition(".")[0] == "design"
                            for node in ast.parse(source).body))
        allowed = {
            f"{EXT}/design/entities.py": SPDX + "from ..core import units\n",
            f"{EXT}/reserves/compliance_store.py": (
                SPDX + "from ..design.entities import chain_tails\nfrom ..design import entities\n"
                "def freeze_findings():\n    from ..design import entities\n"),
        }
        with temp_tree(allowed) as root:
            found = imports.check_dependency_direction(root)
        self.assertEqual(found, [], "\n" + format_findings(found))
        reverse = {
            f"{EXT}/design/entities.py": SPDX + "from ..reserves import compliance_store\n",
            f"{EXT}/reserves/compliance_store.py": SPDX + "from ..core import units\n",
        }
        with temp_tree(reverse) as root:
            found = imports.check_dependency_direction(root)
        self.assertEqual([(item.path.removeprefix(f"{EXT}/"), item.line, item.rule)
                          for item in found], [("design/entities.py", 2, "ARQ-07")])


if __name__ == "__main__":
    unittest.main()
