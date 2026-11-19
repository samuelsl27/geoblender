# SPDX-License-Identifier: GPL-3.0-or-later
"""CE-016-05: regresión del error 26 y de B9 con un cuerpo «bajo un techo» sobre una ladera (spec 016, T23; HU-016-4; RF-016-01,
RF-016-20, RF-016-21, RF-016-22; E5 en el dominio; plan 016 §5.4 A11 y §7.1; D-8, D-9).

El escombro existente de los errores 26 y B9 es un cuerpo **bajo** el terreno (su techo): el espesor se conoce en tres secciones
y la cota de su base **no** se interpola. Sobre la ladera de la cantera de pruebas (``tests.support.stockpile_data``: una
parábola con vaguada que baja hasta ``y = 168``, celdas de 1 m, 15 datos de 1 a 3 m en tres secciones de cinco estaciones), el
dominio (:mod:`design.thickness`, sin proyecto) da:

- **el espesor ≥ 0, la base ≤ el techo y el techo reproducido a ≤ 10⁻⁹ m** en todas las celdas, y el espesor de cada estación
  igual a su dato a ≤ 10⁻⁹ m (con una distancia máxima que deja al TIN unir las secciones);
- **las celdas lejanas avisadas con su área, su volumen y su lugar** (una distancia máxima que descarta los triángulos que cruzan
  de una sección a otra: todo toma el dato más próximo), cada cifra contra un cálculo a mano **independiente** (la distancia de
  cada celda a las 15 estaciones por fuerza bruta con ``numpy``, el dato más próximo y su desempate) y no contra el código;
- **lo mismo con los datos en puntos, en líneas con el espesor en su Z, en líneas con él en su M y en polígonos** (los cuatro
  formatos de RF-016-20: el dominio recibe los datos llevados a puntos o polígonos; su lectura de la capa es de la T25);
- el rechazo de RF-016-22 con la huella «sin datos» del banco de pruebas;
- y, **como demostración y no como criterio**, que **interpolar la cota de la base da espesores negativos** en esta ladera: en el
  punto medio entre dos secciones el techo queda por debajo de la cuerda de las bases (la vaguada) y el «espesor» sería de
  −1,27 m en la columna de ``x = 150,5``; a mano, con la fórmula cerrada de la ladera.
"""

from __future__ import annotations

import unittest
from typing import Any

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender

messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
thickness = import_geoblender("design.thickness")

DesignError = messages.DesignError
GRID = sdata.GRID
EXACT = 1e-9
FAR = "des.body_far"
NO_DATA = "des.body_no_data"
LAYER = "gis_fea_espesor_puntos"
BODY, EMPTY = sdata.BODIES
FOOTPRINT = sdata.in_box(BODY.box)
"""La huella de la ladera: las celdas con el centro dentro de la caja de 220 × 140 m (30.800 celdas de 1 m²)."""
WINDOW = thickness.body_window(FOOTPRINT, GRID)
BASE_X, BASE_Y = sdata.BASE
LOCAL_X, LOCAL_Y = sdata.local_centers(GRID)
"""Las coordenadas LOCALES (m desde la esquina de la cantera) de los centros de celda, de la forma de la rejilla."""


def request(name: str, feature: str = BODY.name) -> Any:
    return model.BodyRequest(name=name, layer=sdata.BODIES_LAYER, feature=feature, data_layer=LAYER, data_field="espesor",
                             data_from="field", surface="Terreno (techo)", sense="under_roof")


def job_of(data: Any, distance: float, *, footprint: np.ndarray = FOOTPRINT, name: str = "Escombro existente",
           feature: str = BODY.name) -> Any:
    """El cuerpo de la ladera como un trabajo de su ventana de trabajo: el techo es la ladera (``hillside``)."""
    window = thickness.body_window(footprint, GRID)
    cut = window
    roof = sdata.hillside(GRID)[cut]
    return thickness.BodyJob(request(name, feature), "BDY-001", GRID, sdata.CRS, sdata.VERTICAL, roof, footprint[cut], data,
                             {"max_distance_m": distance, "zero_at_edge": False}, region=window)


def whole(outcome: Any, array: np.ndarray) -> np.ndarray:
    """``array`` (de la ventana de ``outcome``) puesto en una rejilla entera de NaN."""
    found = np.full(GRID.shape, np.nan)
    found[outcome.window] = array
    return found


def stations() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Las 15 estaciones: sus ``x`` e ``y`` LOCALES y su espesor (m), a mano de ``THICKNESS_M``."""
    xs = np.array([x for _y, _row in zip(sdata.SECTIONS_Y, sdata.THICKNESS_M, strict=True) for x in sdata.STATIONS_X])
    ys = np.array([y for y, _row in zip(sdata.SECTIONS_Y, sdata.THICKNESS_M, strict=True) for _x in sdata.STATIONS_X])
    ts = np.array([t for _y, row in zip(sdata.SECTIONS_Y, sdata.THICKNESS_M, strict=True) for t in row])
    return xs, ys, ts


def brute_nearest() -> tuple[np.ndarray, np.ndarray]:
    """Para cada celda de la huella, la distancia (m) a la estación más próxima y el espesor de **esa** (a igual distancia, el
    menor), por fuerza bruta: la matriz celdas × 15 estaciones. Fuera de la huella, NaN."""
    xs, ys, ts = stations()
    cx, cy = LOCAL_X[FOOTPRINT], LOCAL_Y[FOOTPRINT]
    d2 = (cx[:, None] - xs[None, :]) ** 2 + (cy[:, None] - ys[None, :]) ** 2
    least = d2.min(axis=1)
    value = np.array([ts[np.flatnonzero(row == m)].min() for row, m in zip(d2, least, strict=True)])
    distance, thick = np.full(GRID.shape, np.nan), np.full(GRID.shape, np.nan)
    distance[FOOTPRINT], thick[FOOTPRINT] = np.sqrt(least), value
    return distance, thick


class HillsideTest(unittest.TestCase):
    """CE-016-05: el cuerpo bajo el terreno de la ladera, con los datos en tres secciones."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = sdata.thickness_sections()
        cls.points = thickness.ThicknessData(cls.data.points)
        cls.joined = thickness.compute_body(job_of(cls.points, 40.0))
        cls.apart = thickness.compute_body(job_of(cls.points, 25.0))

    def test_the_footprint_is_the_ladera_box(self) -> None:
        """La huella de la prueba son las 220 × 140 celdas de 1 m del cuerpo de la ladera, con los 15 datos dentro, y su
        ventana de trabajo, la caja y una celda más."""
        self.assertEqual(int(FOOTPRINT.sum()), 220 * 140)
        self.assertEqual(WINDOW, (slice(129, 271), slice(89, 311)))
        self.assertEqual(self.data.points.shape, (15, 3))

    def test_the_thickness_is_never_negative_and_the_base_never_above_the_roof(self) -> None:
        """RF-016-01, CE-016-05 (error 26): con una distancia máxima que une las secciones (40 m: nada es lejano) el espesor es ≥ 0
        y ≤ 3 m (el mayor dato) en las 30.800 celdas, la base ≤ el techo en todas, **el techo es la ladera** y la base más el
        espesor lo reproduce a ≤ 10⁻⁹ m."""
        out = self.joined
        body = out.body
        self.assertEqual(int(body.sum()), 220 * 140)
        self.assertGreaterEqual(float(out.thickness[body].min()), 0.0)
        self.assertGreaterEqual(float(out.thickness[body].min()), 1.0)  # el menor dato: queda entre el menor y el mayor
        self.assertLessEqual(float(out.thickness[body].max()), 3.0)
        self.assertTrue(np.all(out.base[body] <= out.top[body]))
        roof = sdata.hillside(GRID)[out.window]
        np.testing.assert_array_equal(out.top[body], roof[body])
        self.assertLessEqual(float(np.abs((out.base + out.thickness)[body] - roof[body]).max()), EXACT)
        self.assertIsNone(out.surface)

    def test_every_station_is_reproduced(self) -> None:
        """RF-016-20: en la celda de cada una de las 15 estaciones el espesor es su dato (a ≤ 10⁻⁹ m): las estaciones están en
        centros de celda de 1 m, así que ni se promedian ni se mueven."""
        out = self.joined
        found = whole(out, out.thickness)
        xs, ys, ts = stations()
        for x, y, t in zip(xs, ys, ts, strict=True):
            row, col = int(GRID.nrows - 1 - np.floor(y)), int(np.floor(x))
            self.assertLessEqual(abs(found[row, col] - t), EXACT, (x, y))
        self.assertEqual(out.data_cells, 15)

    def test_nothing_is_far_when_the_sections_are_joined(self) -> None:
        """RF-016-21: con 40 m, la celda más lejana de una estación (el punto medio entre dos secciones, a √(30² + 25²) m) no lo
        es: sin aviso y con 0 m² y 0 m³ lejanos, que la fuerza bruta confirma."""
        distance, _nearest = brute_nearest()
        self.assertLess(float(np.nanmax(distance)), 40.0)
        self.assertEqual((self.joined.far_m2, self.joined.far_m3), (0.0, 0.0))
        self.assertEqual([n for n in self.joined.notices if n.code == FAR], [])

    def test_the_far_cells_with_their_area_and_volume(self) -> None:
        """CE-016-05, RF-016-21 (B9): con 25 m (los triángulos entre secciones se descartan) todo es el dato más próximo y las
        celdas a más de 25 m de todas las estaciones son lo lejano: su **área**, su **volumen** (su espesor es el del dato más
        próximo, por fuerza bruta) y su **lugar** (el centro de la más lejana) y el aviso las dice, sin impedir crearlo."""
        out = self.apart
        distance, nearest = brute_nearest()
        far = distance > 25.0
        self.assertGreater(int(far.sum()), 1000)
        np.testing.assert_array_equal(whole(out, out.far)[FOOTPRINT] == 1.0, far[FOOTPRINT])
        found = whole(out, out.thickness)
        self.assertLessEqual(float(np.abs(found[FOOTPRINT] - nearest[FOOTPRINT]).max()), EXACT)
        self.assertEqual(out.far_m2, float(far.sum()))
        want = float(nearest[far].sum())
        self.assertLessEqual(abs(out.far_m3 - want) / want, EXACT)
        flat = np.where(far, distance, -1.0)
        row, col = divmod(int(np.argmax(flat)), GRID.ncols)
        self.assertEqual((out.far_x, out.far_y), (BASE_X + LOCAL_X[row, col], BASE_Y + LOCAL_Y[row, col]))
        notice = [n for n in out.notices if n.code == FAR]
        self.assertEqual(len(notice), 1)
        self.assertEqual((notice[0].values["area"], notice[0].values["distance"]), (float(far.sum()), 25.0))
        self.assertEqual(out.tin_cells, 0)  # ningún triángulo: todos cruzan de una sección a otra (≥ 60 m > 2·25)
        # Sigue siendo un cuerpo válido: el espesor no es negativo, la base no pasa del techo y el techo es el mismo.
        self.assertGreaterEqual(float(out.thickness[out.body].min()), 0.0)
        self.assertTrue(np.all(out.base[out.body] <= out.top[out.body]))

    def test_lines_with_the_thickness_in_z_or_m_give_the_same_body(self) -> None:
        """RF-016-20: el espesor de una línea 3D «en su Z o en su M, como se declare» son los mismos datos: llevados a puntos por
        quien lee la capa (la T25), el dominio da el mismo cuerpo, bit a bit, en puntos, en líneas con el espesor en la Z y en
        líneas con él en la M (la Z del terreno aparte)."""
        from_z = np.vstack(list(self.data.lines_z))
        from_m = np.vstack([np.column_stack([xyz[:, 0], xyz[:, 1], m]) for xyz, m in self.data.lines_m])
        np.testing.assert_array_equal(from_z, self.data.points)
        np.testing.assert_array_equal(from_m, self.data.points)
        for name, rows in (("Z", from_z), ("M", from_m)):
            with self.subTest(espesor_en=name):
                other = thickness.compute_body(job_of(thickness.ThicknessData(rows), 40.0))
                np.testing.assert_array_equal(other.thickness, self.joined.thickness)
                self.assertEqual(other.volume_m3, self.joined.volume_m3)

    def test_polygons_give_their_thickness_in_their_cells(self) -> None:
        """RF-016-20 (polígonos, constante en cada uno): las tres bandas de 200 × 20 m dan, en sus celdas (el centro dentro:
        x de 100,5 a 299,5 y las 20 filas de cada banda), su espesor medio (1,7; 2,2 y 1,7 m) a ≤ 10⁻⁹ m; el resto queda entre
        1,7 y 2,2 m; y lo lejano (a más de 15 m de una banda: la distancia a un rectángulo de centros, en forma cerrada) con su
        área."""
        bands = tuple(((ring,), value) for ring, value in self.data.polygons)
        out = thickness.compute_body(job_of(thickness.ThicknessData(polygons=bands), 15.0))
        found = whole(out, out.thickness)
        means = (1.7, 2.2, 1.7)
        far_cells = np.zeros(GRID.shape, dtype=bool)
        for y, mean in zip(sdata.BAND_Y, means, strict=True):
            inside = (LOCAL_X > 100.0) & (LOCAL_X < 300.0) & (LOCAL_Y > y - 10.0) & (LOCAL_Y < y + 10.0)
            self.assertEqual(int(inside.sum()), 200 * 20)
            self.assertLessEqual(float(np.abs(found[inside] - mean).max()), EXACT)
        self.assertEqual(out.data_cells, 3 * 200 * 20)
        self.assertGreaterEqual(float(out.thickness[out.body].min()), 1.7 - EXACT)
        self.assertLessEqual(float(out.thickness[out.body].max()), 2.2 + EXACT)
        edges = [(100.5, 299.5, y - 9.5, y + 9.5) for y in sdata.BAND_Y]  # los centros de celda de cada banda
        distance = np.full(GRID.shape, np.inf)
        for x0, x1, y0, y1 in edges:
            gap_x = np.maximum(np.maximum(x0 - LOCAL_X, LOCAL_X - x1), 0.0)
            gap_y = np.maximum(np.maximum(y0 - LOCAL_Y, LOCAL_Y - y1), 0.0)
            distance = np.minimum(distance, np.hypot(gap_x, gap_y))
        far_cells = FOOTPRINT & (distance > 15.0)
        self.assertGreater(int(far_cells.sum()), 500)
        self.assertEqual(out.far_m2, float(far_cells.sum()))
        self.assertEqual(int(whole(out, out.far.astype(float))[far_cells].sum()), int(far_cells.sum()))

    def test_a_footprint_without_data_is_refused(self) -> None:
        """RF-016-22: la huella «sin datos» del banco de pruebas (a 20–60 m del oeste y 345–380 m del sur: ninguno de los 15 datos
        cae en ella) se rechaza nombrando la huella y la capa de los datos; no se registra nada."""
        empty = sdata.in_box(EMPTY.box)
        with self.assertRaises(DesignError) as caught:
            thickness.compute_body(job_of(self.points, 40.0, footprint=empty, feature=EMPTY.name))
        self.assertEqual(caught.exception.code, NO_DATA)
        self.assertIn(EMPTY.name, str(caught.exception))
        self.assertIn(LAYER, str(caught.exception))


class DemonstrationTest(unittest.TestCase):
    """CE-016-05 **como demostración, no como criterio** (error 26): interpolar la cota de la base da espesores negativos."""

    def test_interpolating_the_base_elevation_gives_a_negative_thickness(self) -> None:
        """En la columna de ``x = 150,5``, entre la sección A (``y = 140,5``, 2,0 m) y la B (``y = 200,5``, 2,5 m), la base de
        cada estación es su techo menos su espesor y la cota de la base **interpolada** a la mitad (``y = 170,5``) es la media de
        las dos: el techo de la ladera (la parábola de la vaguada) queda **por debajo** de esa cuerda y el «espesor»
        techo − base interpolada es **−1,27 m**; con la regla de RF-016-01, que interpola el espesor, el de esa celda está entre
        2,0 y 2,5 m. A mano con ``hillside_at``, en las cinco columnas de estaciones: negativo en todas."""
        roof = sdata.hillside_at
        for column, x in enumerate(sdata.STATIONS_X):
            with self.subTest(x=x):
                t_a, t_b = sdata.THICKNESS_M[0][column], sdata.THICKNESS_M[1][column]
                base_a, base_b = roof(x, 140.5) - t_a, roof(x, 200.5) - t_b
                wrong = roof(x, 170.5) - (base_a + base_b) / 2.0
                self.assertLess(wrong, 0.0)
                if column == 1:
                    self.assertLessEqual(abs(wrong - (-1.2656)), 1e-3)
        # Con la regla del espesor, en esa celda el espesor sale de los datos y es positivo: entre los de las dos secciones.
        data = sdata.thickness_sections()
        out = thickness.compute_body(job_of(thickness.ThicknessData(data.points), 40.0))
        found = np.full(GRID.shape, np.nan)
        found[out.window] = out.thickness
        row, col = int(GRID.nrows - 1 - np.floor(170.5)), int(np.floor(150.5))
        self.assertGreaterEqual(found[row, col], 1.0)
        self.assertLessEqual(found[row, col], 3.0)
        self.assertTrue(np.all(out.base[out.body] <= out.top[out.body]))


if __name__ == "__main__":
    unittest.main()
