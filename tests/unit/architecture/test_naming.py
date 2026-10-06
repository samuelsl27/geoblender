# SPDX-License-Identifier: GPL-3.0-or-later
"""Nombres de ADR-0011 (RF-001-17) y el conjunto de todas las reglas (``run_all``).

- NOM-01: clases de ``bl/`` que heredan de ``Operator``, ``Panel``, ``Menu``,
  ``PropertyGroup`` o ``UIList``: ``GEOBLENDER_<OT|PT|MT|PG|UL>_<código>_<acción>``.
- NOM-02: ``bl_idname`` literal de un operador: ``geoblender.<código>_<acción>``, la
  forma en minúsculas de su clase.
- NOM-03: carpetas de ``specs/``: ``NNN-<código>-<slug>`` con número único
  (``rules.specs``; desde la spec 007, de la documentación: RF-007-11).
- NOM-04: versión SemVer en el manifiesto (``gbtools.manifest``).
"""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools import manifest  # noqa: E402
from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import DOCS_FAMILIES, FAMILIES, naming, run_all, specs  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"


def _found(files: dict[str, str]) -> list[tuple[str, int, str]]:
    """NOM-01 y NOM-02 (``naming``) y NOM-03 (``specs``) sobre un árbol temporal."""
    tree = {
        rel: (SPDX + text if rel.endswith(".py") else text)
        for rel, text in files.items()
    }
    with temp_tree(tree) as root:
        findings = sorted(naming.check(root) + specs.check(root))
    return [(f.path, f.line, f.rule) for f in findings]


class BlClassNamesTest(unittest.TestCase):
    def test_operator_class(self) -> None:
        """RF-001-17 / NOM-01: un operador de ``bl/`` sin el patrón de ADR-0011."""
        found = _found(
            {
                f"{EXT}/bl/ops/dh.py": (
                    "class ImportDrillholes(bpy.types.Operator):\n"
                    '    bl_idname = "geoblender.dh_import_drillholes"\n'
                    "class GEOBLENDER_OT_mineria_x(Operator):\n"
                    "    pass\n"
                    "class GEOBLENDER_OT_dh_Import(Operator):\n"
                    "    pass\n"
                    "class GEOBLENDER_OT_dh_import_drillholes(bpy.types.Operator):\n"
                    '    bl_idname = "geoblender.dh_import_drillholes"\n'
                    "class Helper:\n"
                    "    pass\n"
                ),
                f"{EXT}/core/ops.py": "class Whatever(Operator):\n    pass\n",
            }
        )
        rel = f"{EXT}/bl/ops/dh.py"
        self.assertEqual(
            found,
            [(rel, 2, "NOM-01"), (rel, 3, "NOM-02"), (rel, 4, "NOM-01"),
             (rel, 6, "NOM-01")],
        )

    def test_bl_idname_mismatch(self) -> None:
        """RF-001-17 / NOM-02: ``GEOBLENDER_OT_dh_import`` con
        ``bl_idname = "geoblender.dh_importar"`` falla."""
        found = _found(
            {
                f"{EXT}/bl/ops/dh.py": (
                    "class GEOBLENDER_OT_dh_import(bpy.types.Operator):\n"
                    '    bl_idname = "geoblender.dh_importar"\n'
                    "class GEOBLENDER_OT_dh_export(bpy.types.Operator):\n"
                    '    bl_idname = "Geoblender.dh_export"\n'
                    "class GEOBLENDER_OT_dh_check(bpy.types.Operator):\n"
                    '    bl_idname: str = "geoblender.dh_check"\n'
                    "class GEOBLENDER_OT_dh_list(bpy.types.Operator):\n"
                    "    bl_idname = IDNAME\n"
                ),
            }
        )
        rel = f"{EXT}/bl/ops/dh.py"
        self.assertEqual(found, [(rel, 3, "NOM-02"), (rel, 5, "NOM-02")])

    def test_panel_class(self) -> None:
        """RF-001-17 / NOM-01: paneles, menús, grupos de propiedades y listas de ``bl/``
        también siguen el patrón."""
        found = _found(
            {
                f"{EXT}/bl/ui/panels.py": (
                    "class GEOBLENDER_PT_ui_topbar(bpy.types.Panel):\n    pass\n"
                    "class GEOBLENDER_PT_topbar(bpy.types.Panel):\n    pass\n"
                    "class VIEW3D_PT_geoblender(Panel):\n    pass\n"
                    "class GEOBLENDER_MT_ui_main(bpy.types.Menu):\n    pass\n"
                    "class GEOBLENDER_OT_ui_main(bpy.types.Menu):\n    pass\n"
                ),
                f"{EXT}/bl/props/scene.py": (
                    "class GeoblenderSceneProps(bpy.types.PropertyGroup):\n    pass\n"
                    "class GEOBLENDER_PG_core_scene(bpy.types.PropertyGroup):\n"
                    "    pass\n"
                    "class GEOBLENDER_UL_dh_holes(bpy.types.UIList):\n    pass\n"
                ),
            }
        )
        self.assertEqual(
            found,
            [
                (f"{EXT}/bl/props/scene.py", 2, "NOM-01"),
                (f"{EXT}/bl/ui/panels.py", 4, "NOM-01"),
                (f"{EXT}/bl/ui/panels.py", 6, "NOM-01"),
            ],
        )


class SpecFoldersTest(unittest.TestCase):
    def test_spec_folder(self) -> None:
        """RF-001-17, RF-007-11 / NOM-03: ``007-mineria-x`` (código que no existe) y
        otras formas fallan; ``_plantillas`` y los ficheros sueltos no cuentan; la regla
        es de la documentación (``DOCS_FAMILIES``) y no del verde del código."""
        found = _found(
            {
                "specs/001-core-esqueleto/spec.md": "",
                "specs/007-mineria-x/spec.md": "",
                "specs/8-dh-x/": "",
                "specs/009-dh-Sondeos/": "",
                "specs/010-dh-sondeos-v2/": "",
                "specs/011_dh_sondeos/": "",
                "specs/_plantillas/spec.md": "",
                "specs/README.md": "",
            }
        )
        self.assertEqual(
            found,
            [
                ("specs/007-mineria-x", 0, "NOM-03"),
                ("specs/009-dh-Sondeos", 0, "NOM-03"),
                ("specs/011_dh_sondeos", 0, "NOM-03"),
                ("specs/8-dh-x", 0, "NOM-03"),
            ],
        )
        self.assertIs(DOCS_FAMILIES["specs"], specs.check)
        with temp_tree({"specs/8-dh-x/": ""}) as root:
            self.assertEqual([f for f in naming.check(root) if f.rule == "NOM-03"], [])

    def test_spec_number_repeated(self) -> None:
        """RF-001-17 / NOM-03: dos carpetas con el mismo número fallan las dos."""
        found = _found(
            {
                "specs/005-dh-sondeos/": "",
                "specs/005-gis-topografia/": "",
                "specs/006-gis-otra/": "",
            }
        )
        self.assertEqual(
            found,
            [
                ("specs/005-dh-sondeos", 0, "NOM-03"),
                ("specs/005-gis-topografia", 0, "NOM-03"),
            ],
        )

    def test_manifest_version_semver(self) -> None:
        """RF-001-17 / NOM-04: la versión ``0.1`` del manifiesto falla, también en
        ``run_all``."""
        text = (ROOT / manifest.MANIFEST_RELPATH).read_text(encoding="utf-8")
        version_line = next(
            line for line in text.split("\n") if line.startswith("version = ")
        )
        broken = text.replace(version_line, 'version = "0.1"')
        with temp_tree({manifest.MANIFEST_RELPATH: broken}) as root:
            direct = [(f.path, f.rule) for f in manifest.check(root)]
            combined = [(f.path, f.rule) for f in run_all(root) if f.rule == "NOM-04"]
        expected = [(manifest.MANIFEST_RELPATH, "NOM-04")]
        self.assertEqual(direct, expected)
        self.assertEqual(combined, expected)


class RunAllTest(unittest.TestCase):
    def test_families(self) -> None:
        """RF-001-12 a RF-001-21, RF-001-06 (TST-01), RF-007-08 (REP-02), RF-007-11 y
        RF-002-25 (ARQ-14, ``georef``): ``run_all`` reúne todas las familias de reglas
        del código (ADR-01 y NOM-03 son de la documentación)."""
        self.assertEqual(
            sorted(FAMILIES),
            ["agents", "georef", "headers", "imports", "layout", "manifest", "naming",
             "platform", "props", "suites", "text"],
        )

    def test_real_tree(self) -> None:
        """RF-001-17 / NOM-01 y NOM-02: el repositorio real cumple; y ``run_all`` no da
        ningún incumplimiento (sin mirar la documentación: RF-007-07)."""
        findings = naming.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))
        everything = run_all(ROOT)
        self.assertEqual(everything, [], "\n" + format_findings(everything))


if __name__ == "__main__":
    unittest.main()
