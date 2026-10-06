# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-14: la conversión absoluta ↔ local (restar o sumar el GeoOrigin) solo existe en
``core.georef.transform`` (spec 002, T04; RF-002-25; ADR-0005; vision-general §10).

Un único sitio, con pruebas de ida y vuelta (≤ 0,5 mm a ±8 km): cualquier otra resta del
origen puede hacerse sobre float32 o con el origen equivocado y perder hasta 0,5 m en
nortes UTM (docs/trampas.md §1).
"""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import FAMILIES, georef  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
HEAD = '"""Módulo de prueba."""\n\n'
OFFSET = (SPDX + HEAD).count("\n")


def _found(files: dict[str, str]) -> list[tuple[str, int, str]]:
    tree = {f"{EXT}/{rel}": SPDX + HEAD + text for rel, text in files.items()}
    with temp_tree(tree) as root:
        findings = georef.check(root)
    return [(f.path.removeprefix(f"{EXT}/"), f.line - OFFSET, f.rule) for f in findings]


class GeoreferenceSingleSiteTest(unittest.TestCase):
    def test_subtraction_outside_transform(self) -> None:
        """RF-002-25 / ARQ-14: restar el GeoOrigin fuera de ``core.georef.transform`` —
        sus atributos (``origin.x0``, ``scene.geoblender.origin_y``), sus nombres
        (``z0``) o dentro de la expresión restada— falla."""
        text = (
            "local_x = xyz[:, 0] - origin.x0\n"
            "local_y = y - scene.geoblender.origin_y\n"
            "local_z = z - z0\n"
            "local = xyz - np.array([origin.x0, origin.y0, origin.z0])\n"
            "x -= self.origin.x0\n"
        )
        found = _found({"core/otro.py": text, "bl/scene/vista.py": "v = w - origin_x\n"})
        self.assertEqual(
            found,
            [
                ("bl/scene/vista.py", 1, "ARQ-14"),
                ("core/otro.py", 1, "ARQ-14"),
                ("core/otro.py", 2, "ARQ-14"),
                ("core/otro.py", 3, "ARQ-14"),
                ("core/otro.py", 4, "ARQ-14"),
                ("core/otro.py", 5, "ARQ-14"),
            ],
        )

    def test_addition_outside_transform(self) -> None:
        """RF-002-25 / ARQ-14: sumar el GeoOrigin (la vuelta a absolutas) fuera de
        ``core.georef.transform`` también falla."""
        text = "world_x = local_x + origin.x0\nworld = origin.y0 + local[:, 1]\nz += z0\n"
        found = _found({"gis/importador.py": text})
        self.assertEqual(
            found,
            [
                ("gis/importador.py", 1, "ARQ-14"),
                ("gis/importador.py", 2, "ARQ-14"),
                ("gis/importador.py", 3, "ARQ-14"),
            ],
        )

    def test_allowed(self) -> None:
        """RF-002-25 / ARQ-14: en ``core/georef/transform.py`` está permitido; fuera, lo
        que no es el origen (``x1``, ``origin_count``, ``x00``), otras operaciones
        (``origin.x0 * 2``, comparaciones) o el origen sin operar, no fallan."""
        allowed = "local = xyz - np.array([origin.x0, origin.y0, origin.z0])\n"
        other = (
            "a = x - x1\n"
            "b = n - self.origin_count\n"
            "c = v - p.x00\n"
            "d = origin.x0 * 2\n"
            "e = origin.x0 == 700_000\n"
            "f = GeoOrigin(origin.x0, origin.y0, origin.z0)\n"
            "g = -origin.x0\n"
        )
        self.assertEqual(
            _found({"core/georef/transform.py": allowed, "core/otro.py": other}), []
        )

    def test_real_tree_and_family(self) -> None:
        """RF-002-25 / ARQ-14: el repositorio real cumple y la regla está en
        ``FAMILIES`` (la ejecuta ``tools/check.py``)."""
        findings = georef.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))
        self.assertIs(FAMILIES["georef"], georef.check)
        self.assertEqual(georef.ALLOWED_MODULE, "core/georef/transform.py")


if __name__ == "__main__":
    unittest.main()
