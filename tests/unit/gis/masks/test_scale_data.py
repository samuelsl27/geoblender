# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de escala de la 012 sin el paquete (spec 012, T31; plan 012 §2.2; RNF-012-05 y
RNF-012-06).

``tests/support/constraints_data.py`` genera, solo con numpy, las 500 restricciones de §2.2 y las
superficies de verificar: lo usan a la vez las pruebas de rendimiento con el Python de Blender
(``tests/support/constraints_scale.py``, que lo convierte a las clases de su copia del paquete) y
las de dentro de Blender (``tests/rendimiento/blender/perf_constraints.py``, que lo convierte a las
de la extensión habilitada: allí no se puede cargar otra copia). Lo que se fija aquí es lo que
tienen en común las dos: el recuento por tipo y geometría, los 100.518 vértices de §2.2, que son
anillos cerrados y antihorarios dentro de la ventana, que los parámetros salen del tipo y que los
mismos datos salen siempre (semilla fija).
"""

import unittest

import numpy as np

from tests.support import constraints_data as data
from tests.support import constraints_scale as scale

POLYGONS_WITH_BUFFER = 40
PLAIN = 398
POINTS = LINES = 30
VERTICES = 100_518


def signed_area(ring: np.ndarray) -> float:
    """El área con signo de un anillo (positiva si es antihorario)."""
    x, y = ring[:, 0], ring[:, 1]
    return float(0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


class ScaleSpecsTest(unittest.TestCase):
    """Las 500 restricciones de §2.2 como datos puros."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.specs = data.build_specs()

    def test_the_counts_of_the_reference_case(self) -> None:
        """RNF-012-06 (plan §2.2): 500 restricciones de 100.518 vértices: el límite legal y el
        perímetro de 2.000 vértices cada uno, 30 puntos, 30 líneas de 200 vértices, 40 polígonos
        de 500 con resguardo y 398 de 176 sin él."""
        specs = self.specs
        self.assertEqual(len(specs), data.COUNT)
        self.assertEqual(sum(len(spec.part) for spec in specs), VERTICES)
        kinds = [spec.kind for spec in specs]
        self.assertEqual((kinds.count("point"), kinds.count("line"), kinds.count("polygon")),
                         (POINTS, LINES, 2 + POLYGONS_WITH_BUFFER + PLAIN))
        self.assertEqual([(spec.name, spec.ctype) for spec in specs[:2]],
                         [("Concesión", "legal_limit"), ("Perímetro", "action_perimeter")])
        self.assertEqual([len(spec.part) for spec in specs[:2]], [2001, 2001])
        self.assertEqual({len(spec.part) for spec in specs if spec.kind == "line"}, {200})
        self.assertEqual(len({spec.name for spec in specs}), data.COUNT)

    def test_the_rings_are_closed_counterclockwise_and_around_the_window(self) -> None:
        """RNF-012-06: cada anillo es cerrado y antihorario, y cada restricción está en la
        ventana del proyecto (su centro; los puntos y los límites, enteros: una línea o una zona
        pueden asomar por el borde, como las de un sitio real)."""
        west, south, east, north = data.window()
        for spec in self.specs:
            part = spec.part
            self.assertEqual(part.dtype, np.float64)
            if spec.kind == "polygon":
                self.assertTrue(np.array_equal(part[0], part[-1]), spec.name)
                self.assertGreater(signed_area(part), 0.0, spec.name)
            centre = part.mean(axis=0)
            self.assertTrue(west < centre[0] < east and south < centre[1] < north, spec.name)
            if spec.kind == "point" or spec.ctype in ("legal_limit", "action_perimeter"):
                self.assertTrue((part[:, 0] > west).all() and (part[:, 0] < east).all(), spec.name)
                self.assertTrue((part[:, 1] > south).all() and (part[:, 1] < north).all(),
                                spec.name)

    def test_the_parameters_come_from_the_type(self) -> None:
        """Cada una está activa; el límite legal tiene 10 m hacia dentro y ningún resguardo hacia
        fuera; solo la «preferible no afectar» lleva peso; las demás de polígono sin resguardo
        llevan 0 m."""
        for spec in self.specs:
            params = dict(spec.params)
            self.assertIs(params["active"], True, spec.name)
            self.assertEqual("weight" in params, spec.ctype == "avoid", spec.name)
        limit = dict(self.specs[0].params)
        self.assertEqual((limit["buffer_in_m"], "buffer_out_m" in limit), (10.0, False))
        self.assertEqual(set(dict(self.specs[1].params)), {"active"})
        plain = [spec for spec in self.specs if spec.name.startswith("Recinto")]
        self.assertEqual(len(plain), PLAIN)
        self.assertEqual({dict(spec.params)["buffer_out_m"] for spec in plain}, {0.0})
        buffered = [spec for spec in self.specs
                    if spec.name.split()[0] in ("Punto", "Línea", "Zona")]
        outward = [dict(spec.params)["buffer_out_m"] for spec in buffered]
        self.assertEqual(len(buffered), POINTS + LINES + POLYGONS_WITH_BUFFER)
        self.assertTrue(5.0 <= min(outward) and max(outward) <= 50.0)

    def test_the_same_data_come_out_every_time(self) -> None:
        """La semilla fija da los mismos vértices y parámetros; otra semilla, otros."""
        again = data.build_specs()
        for first, second in zip(self.specs, again, strict=True):
            self.assertEqual((first.name, first.ctype, first.kind, first.params),
                             (second.name, second.ctype, second.kind, second.params))
            self.assertTrue(np.array_equal(first.part, second.part))
        other = data.build_specs(np.random.default_rng(data.SEED + 1))
        self.assertFalse(np.array_equal(self.specs[3].part, other[3].part))

    def test_build_constraints_is_made_from_them(self) -> None:
        """RNF-012-06: ``constraints_scale.build_constraints`` (T35 a T37) sigue dando las mismas
        filas, con los códigos de sus nombres y las claves de sus parámetros, a partir de los
        datos puros."""
        made = scale.build_constraints()
        self.assertEqual((len(made.rows), made.vertices), (data.COUNT, VERTICES))
        for row, spec in zip(made.rows, self.specs, strict=True):
            self.assertEqual((row.name, str(row.ctype), str(row.kind)),
                             (spec.name, spec.ctype, spec.kind))
            self.assertTrue(np.array_equal(row.parts[0][0], spec.part))
            for param, value in spec.params:
                self.assertEqual(made.values[f"core.constraint.{row.code}.{param}"], value)
        self.assertEqual(len(made.values), sum(len(spec.params) for spec in self.specs))


if __name__ == "__main__":
    unittest.main()
