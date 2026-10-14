# SPDX-License-Identifier: GPL-3.0-or-later
"""Ida y vuelta absoluta → malla de Blender (float32) → absoluta (spec 002, T29;
RF-002-25; ADR-0005 §6, «Cómo se verifica»).

10⁵ vértices aleatorios (semilla fija) a ±8 km del GeoOrigin (700 000; 4 400 000; 0), con
cotas de 0 a 4 000 m: se restan del origen en float64 con ``core.georef.world_to_local``,
se escriben en una malla con ``foreach_set`` (Blender los guarda en float32), se leen con
``foreach_get`` y se vuelven a absolutas con ``local_to_world``. El error máximo tiene que
ser ≤ 0,5 mm (el teórico es 0,244 mm: 2⁻¹² m a 8 km). Control: las mismas coordenadas
absolutas escritas sin restar el origen pierden mucho más (la trampa de float32 en UTM,
docs/trampas.md §1), así que la medida sí distingue un error.

Se ejecuta con ``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import importlib
import unittest

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name

SEED = 20_261_005
COUNT = 100_000
HALF_SIDE_M = 8_000.0
TOLERANCE_M = 0.0005


class Float32RoundTripTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(blender_ext.fresh())
        blender_ext.import_root()
        self.georef = importlib.import_module(module_name() + ".core.georef")
        self.origin = self.georef.GeoOrigin(700_000, 4_400_000, 0)
        rng = np.random.default_rng(SEED)
        world = np.empty((COUNT, 3), dtype=np.float64)
        world[:, 0] = self.origin.x0 + rng.uniform(-HALF_SIDE_M, HALF_SIDE_M, COUNT)
        world[:, 1] = self.origin.y0 + rng.uniform(-HALF_SIDE_M, HALF_SIDE_M, COUNT)
        world[:, 2] = rng.uniform(0.0, 4_000.0, COUNT)
        self.world = world

    def mesh_round_trip(self, coordinates: np.ndarray) -> np.ndarray:
        """Escribe ``coordinates`` en los vértices de una malla nueva con ``foreach_set``
        y las lee con ``foreach_get`` (float32, como las guarda Blender)."""
        mesh = bpy.data.meshes.new("gbtest_float32")
        try:
            mesh.vertices.add(len(coordinates))
            mesh.vertices.foreach_set("co", np.ascontiguousarray(coordinates).ravel())
            mesh.update()
            read = np.empty(len(coordinates) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", read)
        finally:
            bpy.data.meshes.remove(mesh)
        return read.reshape(-1, 3)

    def test_round_trip_within_half_millimetre(self) -> None:
        """RF-002-25 (ADR-0005 §6): 10⁵ vértices a ±8 km vuelven, por una malla de Blender,
        con un error máximo ≤ 0,5 mm (se registra la cifra)."""
        local = self.georef.world_to_local(self.world, self.origin)
        self.assertEqual(local.dtype, np.float64)
        back = self.georef.local_to_world(self.mesh_round_trip(local), self.origin)
        self.assertEqual(back.dtype, np.float64)
        error = np.abs(back - self.world)
        worst = float(error.max())
        per_axis_mm = [round(float(value) * 1000, 4) for value in error.max(axis=0)]
        print(f"\nida y vuelta por la malla: error máximo {worst * 1000:.4f} mm "
              f"(X, Y, Z: {per_axis_mm} mm) en {COUNT} vértices")
        self.assertLessEqual(worst, TOLERANCE_M)

    def test_absolute_coordinates_lose_precision(self) -> None:
        """Control (docs/trampas.md §1): las mismas coordenadas escritas en absolutas, sin
        restar el GeoOrigin, vuelven con errores de decenas de centímetros en Y: la medida
        detecta un error y la resta del origen es la que lo evita."""
        back = self.mesh_round_trip(self.world).astype(np.float64)
        worst_y = float(np.abs(back[:, 1] - self.world[:, 1]).max())
        self.assertGreater(worst_y, 0.1)


if __name__ == "__main__":
    unittest.main()
