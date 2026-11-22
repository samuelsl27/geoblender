# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-13: GeoOrigin en ``IntProperty`` y ninguna propiedad flotante con nombre de
coordenada absoluta (RF-001-15; ADR-0005).

Las propiedades flotantes de Blender son float32: con nortes UTM de 4,4 Mm la
resolución es de 0,5 m (docs/trampas.md §1).
"""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import props  # noqa: E402

# Va en la misma parte que las demás pruebas que pasan las reglas por la extensión: así
# la analizan una sola vez (spec 006, T47; gbtools.parts.affinity_of).
PART_AFFINITY = "reglas-extension"

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
# Sin imports: la regla mira el árbol sintáctico y no los necesita.
HEAD = '"""Propiedades de prueba."""\n\n'


def _found(files: dict[str, str]) -> list[tuple[str, int, str]]:
    tree = {f"{EXT}/{rel}": SPDX + HEAD + text for rel, text in files.items()}
    with temp_tree(tree) as root:
        findings = props.check(root)
    return [(f.path.removeprefix(f"{EXT}/"), f.line, f.rule) for f in findings]


class GeoOriginTest(unittest.TestCase):
    def test_origin_x_float(self) -> None:
        """RF-001-15 / ARQ-13: ``origin_x: FloatProperty()`` (y cualquier propiedad que
        no sea ``IntProperty`` en ``origin_x``, ``origin_y`` u ``origin_z``) falla."""
        found = _found(
            {
                "bl/props/scene.py": (
                    "class GEOBLENDER_PG_core_scene(bpy.types.PropertyGroup):\n"
                    "    origin_x: FloatProperty()\n"
                    '    origin_y: bpy.props.FloatProperty(name="Y0", unit="LENGTH")\n'
                    "    origin_z: bpy.props.StringProperty()\n"
                ),
            }
        )
        self.assertEqual(
            found,
            [
                ("bl/props/scene.py", 5, "ARQ-13"),
                ("bl/props/scene.py", 6, "ARQ-13"),
                ("bl/props/scene.py", 7, "ARQ-13"),
            ],
        )

    def test_origin_vector(self) -> None:
        """RF-001-15 / ARQ-13: ``origin: FloatVectorProperty()`` falla."""
        found = _found(
            {
                "bl/props/scene.py": (
                    "class P(bpy.types.PropertyGroup):\n"
                    "    origin: FloatVectorProperty(size=3)\n"
                    "    georef_offset = bpy.props.FloatVectorProperty(size=2)\n"
                ),
            }
        )
        rel = "bl/props/scene.py"
        self.assertEqual(found, [(rel, 5, "ARQ-13"), (rel, 6, "ARQ-13")])

    def test_scene_attribute_assignment(self) -> None:
        """RF-001-15 / ARQ-13: ``Scene.utm_x = FloatProperty()`` y asignaciones
        parecidas en cualquier sitio de ``geoblender/`` fallan."""
        found = _found(
            {
                "bl/scene/register.py": (
                    "def register():\n"
                    "    bpy.types.Scene.utm_x = bpy.props.FloatProperty()\n"
                    "    bpy.types.Object.origin_x = FloatProperty()\n"
                    "    bpy.types.Scene.world_northing = FloatProperty(default=0.0)\n"
                ),
                "core/legacy.py": "abs_z = FloatProperty()\nx0: FloatProperty\n",
            }
        )
        self.assertEqual(
            found,
            [
                ("bl/scene/register.py", 5, "ARQ-13"),
                ("bl/scene/register.py", 6, "ARQ-13"),
                ("bl/scene/register.py", 7, "ARQ-13"),
                ("core/legacy.py", 4, "ARQ-13"),
            ],
        )

    def test_aliased_property_names(self) -> None:
        """RF-001-15 / ARQ-13: un tipo de propiedad importado con otro nombre (``from
        bpy.props import FloatVectorProperty as Vec3``) o asignado a otro nombre (``Real =
        bpy.props.FloatProperty``) se reconoce por el original: ``origin: Vec3()``,
        ``origin_y: F()`` y ``utm_e: Real()`` fallan; ``origin_x: Entero()`` (un
        ``IntProperty``) y ``section_step: F()``, no (hallazgo F5 de la ronda 3, sabotaje
        X6; convergencia, T52)."""
        text = (
            "from bpy.props import FloatVectorProperty as Vec3\n"
            "from bpy.props import FloatProperty as F, IntProperty as Entero\n"
            "Real = bpy.props.FloatProperty\n"
            "Otro = construir_vector\n\n"
            "class GEOBLENDER_PG_core_alias(bpy.types.PropertyGroup):\n"
            "    origin: Vec3()\n"
            "    origin_x: Entero()\n"
            "    origin_y: F()\n"
            "    utm_e: Real()\n"
            "    section_step: F()\n"
            "    world: Otro()\n"
        )
        found = _found({"bl/props/alias.py": text})
        offset = (SPDX + HEAD).count("\n")
        expected = [
            ("bl/props/alias.py", offset + number, "ARQ-13")
            for number, line in enumerate(text.splitlines(), start=1)
            if line.strip().startswith(("origin:", "origin_y:", "utm_e:"))
        ]
        self.assertEqual(len(expected), 3)
        self.assertEqual(found, expected)

    def test_collar_and_coordinate_tokens(self) -> None:
        """RF-001-15 / ARQ-13: los nombres de la boca de un sondeo y de las coordenadas de
        un punto (``collar``, ``coord``, ``coords``, ``xyz``) también son de coordenada
        absoluta: ``collar: FloatVectorProperty(size=3)``, ``collar_z``, ``coords``,
        ``coord_x`` y ``head_xyz`` en flotantes fallan; ``collar_id`` en texto,
        ``coordinate_precision`` y ``scale_xy``, no (hallazgo F6 de la ronda 4;
        convergencia, T58)."""
        text = (
            "class GEOBLENDER_PG_dh_collar(bpy.types.PropertyGroup):\n"
            "    collar: FloatVectorProperty(size=3)\n"
            "    collar_z: bpy.props.FloatProperty()\n"
            "    coords: FloatVectorProperty(size=3)\n"
            "    head_xyz: FloatVectorProperty(size=3)\n"
            "    collar_id: StringProperty()\n"
            "    coordinate_precision: FloatProperty()\n"
            "    scale_xy: FloatVectorProperty(size=2)\n"
            "bpy.types.Object.coord_x = bpy.props.FloatProperty()\n"
        )
        found = _found({"bl/props/collar.py": text})
        offset = (SPDX + HEAD).count("\n")
        expected = [
            ("bl/props/collar.py", offset + number, "ARQ-13")
            for number, line in enumerate(text.splitlines(), start=1)
            if line.strip().startswith(
                ("collar:", "collar_z:", "coords:", "head_xyz:", "bpy.types.Object.coord_x")
            )
        ]
        self.assertEqual(len(expected), 5)
        self.assertEqual(found, expected)

    def test_elevation_tokens(self) -> None:
        """RF-001-15 / ARQ-13, E-5 de la verificación única de la spec 017 (T45; mutante M3c: la regla sin términos de cota): la cota también es una coordenada absoluta y ninguna propiedad
        es «una coordenada ni una cota en ``FloatProperty``» (ADR-0005): ``dest_level: FloatProperty()``, ``start_level``, ``cota_min``, ``elev`` y ``Scene.cota_z`` en flotantes fallan; los mismos
        nombres en texto o en entero, ``levels``, ``cotangent`` y ``elevated`` en flotantes, no."""
        text = (
            "class GEOBLENDER_PG_des_road(bpy.types.PropertyGroup):\n"
            "    dest_level: FloatProperty()\n"
            "    start_level: bpy.props.FloatProperty(default=100.0)\n"
            "    cota_min: FloatVectorProperty(size=2)\n"
            "    elev: FloatProperty()\n"
            "    dest_level_text: StringProperty()\n"
            "    level: IntProperty()\n"
            "    levels: FloatProperty()\n"
            "    cotangent: FloatProperty()\n"
            "    elevated: FloatProperty()\n"
            "bpy.types.Scene.cota_z = bpy.props.FloatProperty()\n"
        )
        found = _found({"bl/props/levels.py": text})
        offset = (SPDX + HEAD).count("\n")
        expected = [
            ("bl/props/levels.py", offset + number, "ARQ-13")
            for number, line in enumerate(text.splitlines(), start=1)
            if line.strip().startswith(("dest_level:", "start_level:", "cota_min:", "elev:", "bpy.types.Scene.cota_z"))
        ]
        self.assertEqual(len(expected), 5)
        self.assertEqual(found, expected)

    def test_int_origin_ok(self) -> None:
        """RF-001-15 / ARQ-13: el GeoOrigin en ``IntProperty`` pasa."""
        found = _found(
            {
                "bl/props/scene.py": (
                    "class GEOBLENDER_PG_core_scene(bpy.types.PropertyGroup):\n"
                    '    origin_x: IntProperty(name="X0")\n'
                    "    origin_y: bpy.props.IntProperty()\n"
                    "    origin_z: IntProperty(default=0)\n"
                    "bpy.types.Scene.origin_x = IntProperty()\n"
                ),
            }
        )
        self.assertEqual(found, [])

    def test_unrelated_float_ok(self) -> None:
        """RF-001-15 / ARQ-13: una propiedad flotante con otro nombre pasa
        (``section_step``, ``absorption``, ``worldwide_scale``…)."""
        found = _found(
            {
                "bl/props/design.py": (
                    "class P(bpy.types.PropertyGroup):\n"
                    "    section_step: FloatProperty(default=10.0)\n"
                    "    bench_height: bpy.props.FloatProperty()\n"
                    "    absorption: FloatProperty()\n"
                    "    worldwide_scale: FloatProperty()\n"
                    "    local_offset: FloatVectorProperty(size=3)\n"
                    "    origin_label: bpy.props.StringProperty()\n"
                    "    origin_count = IntProperty()\n"
                ),
            }
        )
        self.assertEqual(found, [])

    def test_tokens(self) -> None:
        """RF-001-15 / ARQ-13: la lista cerrada de términos, por trozos separados por
        «_» y sin distinguir mayúsculas (con ``collar``, ``coord``, ``coords`` y ``xyz``
        desde la convergencia, T58; y ``level``, ``cota`` y ``elev``, de las cotas, desde la
        verificación única de la spec 017, T45)."""
        self.assertEqual(
            props.ABS_COORD_TOKENS,
            frozenset(
                {"origin", "x0", "y0", "z0", "easting", "northing", "utm", "abs",
                 "absolute", "world", "georef", "collar", "coord", "coords", "xyz",
                 "level", "cota", "elev"}
            ),
        )
        for name in (
            "Origin", "UTM_X", "x0_offset", "abs", "Absolute_Z", "georef_y",
            "Collar", "coord_x", "COORDS", "head_xyz",
            "dest_level", "Level", "cota_min", "ELEV",
        ):
            with self.subTest(nombre=name):
                self.assertTrue(props.has_abs_coord_token(name))
        for name in (
            "origins", "x00", "absorption", "worldwide", "section_step",
            "collars", "coordinate", "xyzw",
            "levels", "cotangent", "elevated",
        ):
            with self.subTest(nombre=name):
                self.assertFalse(props.has_abs_coord_token(name))

    def test_real_tree(self) -> None:
        """RF-001-15 / ARQ-13: la extensión real no incumple ARQ-13."""
        findings = props.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()
