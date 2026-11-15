# SPDX-License-Identifier: GPL-3.0-or-later
"""Las máscaras de una versión leídas por ventanas (spec 015, T37; RNF-015-03, RNF-015-08, RF-012-17; plan 015
§5.4 A0; ADR-0028).

«Recalcular lo obsoleto» crea la operación de cada plataforma en **una** llamada del hilo de Blender (≤ 0,2 s): no
puede leer la rejilla de clases entera (2,81 M celdas) para tocar de ella unas pocas teselas. ``access.open_masks``
comprueba que las máscaras de la versión están al día (los mismos rechazos que ``load_masks``) y da un
:class:`~geoblender.gis.masks.access.MaskSource` con lo que identifica a las máscaras (la rejilla, la versión, la
compilación y sus ``Use``) **sin celdas**: ``classes_window`` lee solo las teselas de una ventana, y da, bit a bit,
lo mismo que ``load_masks(...).classes[ventana]`` (que también la da, ``MaskSet.classes_window``). Sobre el proyecto
de ``tests.support.constraints_project`` con la rejilla de clases en teselas de 16 × 16.
"""

from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from tests.support import constraints_project as cp
from tests.support.package import import_geoblender

access = import_geoblender("gis.masks.access")
reader = import_geoblender("gis.geotiff.reader")
writer = import_geoblender("gis.geotiff.writer")
compose = import_geoblender("design.compose")
design_model = import_geoblender("design.model")

TILE_M = 16


def windows_of(shape: tuple[int, int]) -> list[tuple[slice, slice]]:
    """Unas cuantas ventanas de una rejilla de ``shape``: entera, una celda, una tesela, a caballo de varias, una
    fila y una columna."""
    rows, cols = shape
    return [(slice(0, rows), slice(0, cols)), (slice(0, 1), slice(0, 1)),
            (slice(rows - 1, rows), slice(cols - 1, cols)),
            (slice(TILE_M, 2 * TILE_M), slice(TILE_M, 2 * TILE_M)),
            (slice(TILE_M - 3, 2 * TILE_M + 5), slice(7, cols // 2)),
            (slice(rows // 3, rows // 3 + 1), slice(0, cols)), (slice(0, rows), slice(cols // 2, cols // 2 + 1))]


class MaskSourceTest(cp.ConstraintsProjectCase):
    """V01 con las máscaras compiladas; V02, sin ellas."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.enterClassContext(mock.patch.object(writer, "TILE_SIZE", TILE_M))
        super().setUpClass()
        steps = access.ensure_masks_steps(cls.project, cls.v1.uid)
        found = None
        for step in steps:
            found = step.result or found
        cls.masks = found

    def test_a_a_window_of_the_classes_is_the_same_cells_as_the_loaded_masks(self) -> None:
        """RF-012-17, RNF-015-03: ``MaskSource.classes_window`` y ``MaskSet.classes_window`` dan, en uint16 y bit a
        bit, lo que ``load_masks(...).classes`` en esa ventana; ``admitted_in`` da lo que ``admitted`` en ella, en
        corte y en relleno."""
        loaded = access.load_masks(self.project, self.v1.uid)
        source = access.open_masks(self.project, self.v1.uid)
        self.assertEqual(loaded.classes.shape, self.masks.grid.shape)
        self.assertGreater(loaded.classes.shape[0], 2 * TILE_M)
        for window in windows_of(loaded.classes.shape):
            for found in (source, loaded):
                with self.subTest(window=window, kind=type(found).__name__):
                    part = found.classes_window(window)
                    self.assertEqual(part.dtype, np.uint16)
                    np.testing.assert_array_equal(part, loaded.classes[window])
                    for sense in (design_model.BenchSense.CUT, design_model.BenchSense.FILL):
                        np.testing.assert_array_equal(compose.admitted_in(found, sense, window),
                                                      compose.admitted(loaded, sense)[window])

    def test_a_it_has_what_identifies_the_masks_and_no_cells(self) -> None:
        """La rejilla, la versión, la compilación, el estado y los ``Use`` son los del ``MaskSet`` cargado."""
        loaded = access.load_masks(self.project, self.v1.uid)
        source = access.open_masks(self.project, self.v1.uid)
        self.assertEqual(source.grid, loaded.grid)
        self.assertEqual((source.version_uid, source.operation_uid, source.state),
                         (loaded.version_uid, loaded.operation_uid, access.MaskState.CURRENT))
        self.assertEqual(source.uses(), loaded.uses())
        self.assertFalse(hasattr(source, "classes"))

    def test_a_only_the_tiles_of_the_window_are_decoded(self) -> None:
        """RNF-015-03: una ventana dentro de una tesela decodifica una sola; abrir las máscaras, ninguna."""
        with mock.patch.object(reader, "decode_block", wraps=reader.decode_block) as decoded:
            source = access.open_masks(self.project, self.v1.uid)
        self.assertEqual(decoded.call_count, 0, "abrir las máscaras no lee celdas")
        with mock.patch.object(reader, "decode_block", wraps=reader.decode_block) as decoded:
            source.classes_window((slice(2, 9), slice(3, 12)))
        self.assertEqual(decoded.call_count, 1)

    def test_a_masks_that_are_not_up_to_date_are_refused_like_load_masks(self) -> None:
        """RF-012-17: sin compilar (V02), ``open_masks`` lanza el mismo ``MaskError`` que ``load_masks``."""
        with self.assertRaises(access.MaskError) as expected:
            access.load_masks(self.project, self.v2.uid)
        with self.assertRaises(access.MaskError) as found:
            access.open_masks(self.project, self.v2.uid)
        self.assertEqual(found.exception.code, expected.exception.code)
        self.assertEqual(found.exception.values, expected.exception.values)

    def test_a_a_window_outside_the_grid_is_a_program_error(self) -> None:
        """Una ventana vacía o fuera de la rejilla es un error del programa."""
        source = access.open_masks(self.project, self.v1.uid)
        rows, cols = source.grid.shape
        for window in ((slice(3, 3), slice(0, 4)), (slice(0, 4), slice(0, cols + 1)),
                       (slice(-1, 4), slice(0, 4)), (slice(0, rows + 1), slice(0, 4))):
            with self.subTest(window=window), self.assertRaises(ValueError):
                source.classes_window(window)


if __name__ == "__main__":
    unittest.main()
