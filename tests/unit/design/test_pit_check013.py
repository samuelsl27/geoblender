# SPDX-License-Identifier: GPL-3.0-or-later
"""El contraste de la corta con el escalonado de la 013 (spec 018, T20; HU-018-2; RF-018-27; CE-018-12; plan 018 §5.4 A13).

La corta circular de CE-018-03 (ascendente) y el límite cuadrado de CE-018-04 (descendente) contra el escalonado de la 013 con el mismo perfil,
ancla y semillas: la diferencia de cota y de volumen, la inclinación de celda, el aviso de la envolvente y que **ninguna superficie cambia**.
El contraste con celdas de ≤ 2 m a ≤ 1 % (CE-018-12) está en ``tests/referencia/des/test_ref_pit_check013.py``. Sin proyecto y sin Blender."""

from __future__ import annotations

import dataclasses
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1

pit_bench = import_geoblender("design.pit_bench")
pit_surface = import_geoblender("design.pit_surface")
pit_check013 = import_geoblender("design.pit_check013")
messages = import_geoblender("design.messages")


def up_case(step_m: float = 4.0) -> tuple[object, object]:
    job = h1.up_job(pd.grid_of(step_m))
    return job, pit_surface.rasterize(job, pit_bench.ascend(job), crs=pd.CRS, vertical=pd.VERTICAL)


class AscendingContrastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.job, cls.surface = up_case()
        cls.start, cls.design = cls.job.start.copy(), cls.surface.surface.copy()
        cls.found = pit_check013.contrast(cls.job, cls.surface)

    def test_no_surface_changes(self) -> None:
        """RF-018-27: el contraste no cambia ninguna superficie (la partida y la de la corta, bit a bit; la de la 013 es de solo lectura)."""
        self.assertTrue(np.array_equal(self.start, self.job.start) and np.array_equal(self.design, self.surface.surface))
        self.assertFalse(self.found.design013.flags.writeable)

    def test_the_013_design_is_a_cut_inside_the_enclosure(self) -> None:
        """RF-018-27: la superficie de la 013 corta sobre el fondo circular y no cambia la partida fuera del recinto (bit a bit)."""
        outside = ~self.surface.enclosure
        self.assertTrue(np.array_equal(self.found.design013[outside], self.job.start[outside]))
        self.assertLess(float(np.nanmin(self.found.design013)), pd.TOP_Z_M)
        self.assertEqual(float(np.nanmin(self.found.design013[self.surface.enclosure])), pd.FLOOR_Z_M)

    def test_figures_are_consistent(self) -> None:
        """RF-018-27: la diferencia de volumen es corta − 013 en m³ y en % de la 013; la de cota, el máximo de ``|corta − 013|`` con su lugar."""
        found = self.found
        self.assertEqual(found.volume_pit_m3, self.surface.cut_m3)
        self.assertAlmostEqual(found.volume_diff_m3, found.volume_pit_m3 - found.volume_013_m3, delta=1e-6)
        self.assertAlmostEqual(found.volume_diff_pct, found.volume_diff_m3 / found.volume_013_m3 * 100.0, delta=1e-9)
        moved = self.surface.cut_cells | (found.design013 < self.job.start)
        both = moved & np.isfinite(found.design013)
        self.assertAlmostEqual(found.max_diff_m, float(np.abs(self.surface.surface - found.design013)[both].max()), delta=1e-12)
        self.assertIsNotNone(found.max_diff_place)

    def test_inclination_percentiles(self) -> None:
        """RF-018-27: la inclinación de celda p90 ≤ p99 ≤ máxima, con la máxima junto a 60° (la cara del perfil) y su lugar."""
        found = self.found
        self.assertLessEqual(found.p90_deg, found.p99_deg)
        self.assertLessEqual(found.p99_deg, found.max_deg)
        self.assertAlmostEqual(found.max_deg, 60.0, delta=0.5)
        self.assertIsNotNone(found.max_place)

    def test_reference_profile_does_not_warn(self) -> None:
        """RF-018-27 (DIFF-018d): frente al escalonado recortado de la 013 (mismo perfil, ancla y semillas) la corta de referencia no lo supera en más de
        una altura de banco: el exceso máximo medido es positivo (el escalonado de cara primero y el chamfer no coinciden) pero menor que ``h``, y no
        hay aviso."""
        found = self.found
        self.assertGreater(found.above_max_m, 0.0)
        self.assertLess(found.above_max_m, pd.EXPL.height_m)
        self.assertIsNotNone(found.above_place)
        self.assertEqual((found.above_cells, found.notices), (0, ()))

    def test_warns_when_the_pit_goes_above_by_more_than_one_bench_height(self) -> None:
        """RF-018-27 (DIFF-018d): si el escalonado de la corta supera al de la 013 en más de una altura de banco, el aviso dice el banco (su cota), el
        exceso medido y el lugar; con un exceso de ``h`` o menos no avisa."""
        height = pd.EXPL.height_m
        for lift, warns in ((height - 0.1, False), (height + 0.5, True)):
            with self.subTest(lift=lift):
                raised = dataclasses.replace(self.surface, stepped=self.surface.stepped + lift)
                found = pit_check013.contrast(self.job, raised)
                self.assertEqual(bool(found.notices), warns)
                if warns:
                    (notice,) = found.notices
                    self.assertEqual((notice.code, notice.severity), ("des.pit_above_envelope", "warning"))
                    self.assertIn("Corta 1", notice.text("es"))
                    self.assertIn("una altura de banco", notice.text("es"))
                    self.assertEqual(notice.values["count"], found.above_cells)
                    self.assertGreater(found.above_cells, 0)
                    self.assertGreater(found.above_max_m, height)
                    self.assertAlmostEqual(notice.values["excess"], found.above_max_m, delta=1e-12)
                    self.assertIn("level", notice.values)

    def test_steps_end_with_the_same_result(self) -> None:
        """RF-018-27: por pasos da el mismo resultado que de una vez, y cerrar el generador a mitad no deja nada ni cambia nada."""
        steps = list(pit_check013.contrast_steps(self.job, self.surface))
        self.assertGreater(len(steps), 1)
        self.assertEqual(steps[-1].phase, "pit_check013")
        self.assertTrue(np.array_equal(steps[-1].result.design013, self.found.design013, equal_nan=True))
        half = pit_check013.contrast_steps(self.job, self.surface)
        next(half)
        half.close()
        self.assertTrue(np.array_equal(self.start, self.job.start))


class DescendingContrastTest(unittest.TestCase):
    def test_square_limit(self) -> None:
        """RF-018-27: la descendente del límite cuadrado de CE-018-04 (semillas: su borde al terreno) se contrasta: la 013 corta dentro del recinto, no
        hay aviso de envolvente (es solo de la ascendente) y las cifras son finitas."""
        grid = pd.grid_of(4.0)
        job = h1.down_job(grid)
        surface = pit_surface.rasterize(job, pit_bench.descend(job), crs=pd.CRS, vertical=pd.VERTICAL)
        found = pit_check013.contrast(job, surface)
        self.assertEqual((found.above_cells, found.notices), (0, ()))
        self.assertGreater(found.volume_013_m3, 0.0)
        self.assertTrue(np.isfinite(found.max_diff_m) and found.volume_diff_pct is not None)
        self.assertTrue(np.array_equal(found.design013[~surface.enclosure], job.start[~surface.enclosure]))


class MessageTest(unittest.TestCase):
    def test_message_is_in_the_catalogue_in_both_languages(self) -> None:
        """RF-018-27: el aviso está en el catálogo, en español y en inglés, y es un aviso (no un error)."""
        message = messages.lookup("des.pit_above_envelope")
        self.assertEqual(message.severity, "warning")
        self.assertIn("{count}", message.es)
        self.assertIn("{count}", message.msgid)
        self.assertIn("{excess}", message.es)
        self.assertIn("{level}", message.es)


if __name__ == "__main__":
    unittest.main()
