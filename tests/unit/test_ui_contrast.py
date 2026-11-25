# SPDX-License-Identifier: GPL-3.0-or-later
"""Contraste y paleta para daltónicos de los colores propios (spec 019, T28; RF-019-22; UI-30, UI-31; plan 019 §5.5).

La fórmula de WCAG es la del dominio (``core.appearance.contrast``, sin dependencias). Se mide el predefinido de cada tipo
de elemento y de cada subtipo (entidades de diseño y restricciones) y los colores de leyenda contra el fondo de la vista
del tema oscuro y del claro de Blender: 3:1 los colores que se pintan, 4,5:1 un texto. Lo existente que no llega, que son
los colores que ya pintan los cargadores (el predefinido **es** el valor actual, T02), está en ``tests/data/ui_baseline.toml``
(``[contrast]``) y solo baja. La paleta de Okabe e Ito se comprueba contra la original y contra tres daltonismos simulados;
el color nunca es la única señal: cada tipo con color tiene un nombre y no hay dos con el mismo color en un grupo.
"""

import re
import unittest
from pathlib import Path

from tests.support import ui_strings as us
from tests.support.package import import_geoblender

catalog = import_geoblender("core.appearance.catalog")
contrast = import_geoblender("core.appearance.contrast")
constraint_model = import_geoblender("core.constraints.model")
entities = import_geoblender("design.entities")

BLENDER_LIGHT_XML = Path("C:/Program Files/Blender Foundation/Blender 5.2/5.2/scripts/presets/interface_theme/Blender_Light.xml")

OKABE_ITO = {"#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7"}


def colors() -> dict[str, str]:
    """Todo color propio con su nombre: predefinido por tipo, por subtipo y los de las leyendas."""
    found: dict[str, str] = {}
    for kind, spec in catalog.KINDS.items():
        if spec.color is not None:
            found[f"kind:{kind}"] = spec.color
    for sub, value in catalog.ENTITY_SUBKINDS.items():
        found[f"entity:{sub}"] = value
    for sub, value in catalog.CONSTRAINT_SUBKINDS.items():
        found[f"constraint:{sub}"] = value
    for loader, values in catalog.CLASS_LEGEND_COLORS.items():
        for index, value in enumerate(values):
            found[f"legend:{loader}:{index}"] = value
    for index, value in enumerate(catalog.DRILLHOLE_RAMP):
        found[f"ramp:{index}"] = value
    return found


def findings() -> list[str]:
    """«nombre color@tema» de cada color que no llega a 3:1 con el fondo de la vista del tema."""
    out = []
    for name, value in colors().items():
        for theme, background in contrast.THEME_BACKGROUNDS.items():
            if contrast.contrast_ratio(value, background) < contrast.GRAPHIC_MIN:
                out.append(f"{name} {value}@{theme}")
    return sorted(out)


class ContrastFormulaTest(unittest.TestCase):
    def test_wcag_reference_values(self) -> None:
        self.assertAlmostEqual(contrast.contrast_ratio("#000000", "#FFFFFF"), 21.0, places=6)
        self.assertAlmostEqual(contrast.contrast_ratio("#FFFFFF", "#FFFFFF"), 1.0, places=6)
        self.assertAlmostEqual(contrast.contrast_ratio("#777777", "#FFFFFF"), 4.48, places=2)
        self.assertEqual(contrast.contrast_ratio("#123456", "#FEDCBA"), contrast.contrast_ratio("#FEDCBA", "#123456"))

    def test_positive_control_two_to_one_fails(self) -> None:
        """Un color con 2:1 sobre el tema no pasa 3:1 ni 4,5:1; uno con 4,5:1 pasa los dos."""
        low = "#B0B0B0"
        self.assertLess(contrast.contrast_ratio(low, "#FFFFFF"), 2.3)
        self.assertFalse(contrast.passes(low, "#FFFFFF", contrast.GRAPHIC_MIN))
        self.assertFalse(contrast.passes(low, "#FFFFFF", contrast.TEXT_MIN))
        self.assertTrue(contrast.passes("#767676", "#FFFFFF", contrast.TEXT_MIN))
        self.assertTrue(contrast.passes("#767676", "#FFFFFF", contrast.GRAPHIC_MIN))

    def test_bad_color_is_an_error(self) -> None:
        for bad in ("red", "#12345", "#GGGGGG", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                contrast.relative_luminance(bad)

    def test_theme_backgrounds_are_the_blender_ones(self) -> None:
        """El claro se lee del tema incluido de Blender si está instalado; el oscuro es el del tema por defecto."""
        self.assertEqual(set(contrast.THEME_BACKGROUNDS), {"dark", "light"})
        if not BLENDER_LIGHT_XML.exists():
            self.skipTest("sin el tema claro de Blender instalado")
        text = BLENDER_LIGHT_XML.read_text(encoding="utf-8")
        view3d = text[text.index("<ThemeView3D"):]
        match = re.search(r'<gradients>.*?gradient="(#[0-9a-fA-F]{6})"', view3d, re.S)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).upper(), contrast.THEME_BACKGROUNDS["light"])


class OwnColorsTest(unittest.TestCase):
    def test_no_new_low_contrast_color_and_baseline_only_goes_down(self) -> None:
        found = set(findings())
        baseline = set(us.load_baseline("contrast"))
        self.assertEqual(sorted(found - baseline), [], "color nuevo sin 3:1 sobre el tema (UI-30)")
        self.assertEqual(sorted(baseline - found), [], "ya cumple: quítelo de [contrast] de la lista base")

    def test_baseline_file_is_well_formed(self) -> None:
        entries = us.load_baseline("contrast")
        self.assertEqual(entries, sorted(set(entries)))

    def test_a_seeded_two_to_one_color_is_found(self) -> None:
        """Control positivo: un predefinido de 2:1 sobre el fondo oscuro no llega y la comparación lo vería nuevo."""
        seeded = "#4A4A4A"
        dark = contrast.THEME_BACKGROUNDS["dark"]
        self.assertLess(contrast.contrast_ratio(seeded, dark), 2.0)
        self.assertFalse(contrast.passes(seeded, dark, contrast.GRAPHIC_MIN))
        self.assertNotIn(f"kind:SEEDED {seeded}@dark", us.load_baseline("contrast"))

    def test_text_over_an_own_color_needs_four_and_a_half(self) -> None:
        """El texto de los controles propios es el de Blender (tema). El texto sobre un color propio (la leyenda, un
        rótulo) es negro o blanco: el que más contraste da pasa 4,5:1 sobre todos los predefinidos."""
        for name, value in colors().items():
            best = max(contrast.contrast_ratio(value, "#000000"), contrast.contrast_ratio(value, "#FFFFFF"))
            with self.subTest(name=name):
                self.assertGreaterEqual(best, contrast.TEXT_MIN, f"{name} {value}: ni negro ni blanco se leen encima")


class ColorblindPaletteTest(unittest.TestCase):
    def test_palette_is_okabe_ito(self) -> None:
        self.assertEqual({value.upper() for value in catalog.PALETTE[:7]}, OKABE_ITO)
        self.assertEqual(len(catalog.PALETTE), 8)

    def test_palette_is_distinguishable_with_three_colour_blindnesses(self) -> None:
        """Los siete colores de Okabe e Ito, entre sí, a 12 de distancia como mínimo; el gris que añade el catálogo (el
        negro no se ve en el tema oscuro), a 7 de los demás: con deuteranopía el púrpura y el gris se acercan (7,05), por
        eso el gris solo es el color de «otro» y de lo sin tipo, que además llevan su nombre en texto (UI-31)."""
        for kind in ("deuteranopia", "protanopia", "tritanopia"):
            simulated = [contrast.simulate(value, kind) for value in catalog.PALETTE]
            for i, first in enumerate(simulated):
                for j in range(i + 1, len(simulated)):
                    distance = contrast.lab_distance(first, simulated[j])
                    minimum = contrast.MIN_CVD_DISTANCE if j < 7 else 7.0
                    with self.subTest(kind=kind, pair=(catalog.PALETTE[i], catalog.PALETTE[j])):
                        self.assertGreaterEqual(distance, minimum)

    def test_positive_control_a_red_green_pair_is_confused(self) -> None:
        """Un rojo y un verde de la misma claridad se confunden con deuteranopía y la prueba lo ve."""
        red, green = "#B35A00", "#6B8E00"
        self.assertLess(contrast.lab_distance(contrast.simulate(red, "deuteranopia"),
                                              contrast.simulate(green, "deuteranopia")), contrast.MIN_CVD_DISTANCE)

    def test_kinds_without_their_own_loader_color_take_the_palette(self) -> None:
        painted = {catalog.KINDS[kind].color for kind in ("DTM", "TIN", "POINTS", "BREAKLINES", "CONTOURS", "BOUNDARY", "DESIGN")}
        self.assertLessEqual({value.upper() for value in painted}, {value.upper() for value in catalog.PALETTE})


class ColorIsNotTheOnlySignalTest(unittest.TestCase):
    def test_every_constraint_type_has_a_name_and_a_distinct_color(self) -> None:
        for sub in catalog.CONSTRAINT_SUBKINDS:
            if sub == "untyped":
                continue
            with self.subTest(sub=sub):
                label = constraint_model.ConstraintType(sub).label("es")
                self.assertTrue(label and label != sub, sub)
        values = list(catalog.CONSTRAINT_SUBKINDS.values())
        self.assertEqual(len(values), len(set(values)), "dos tipos de restricción con el mismo color")

    def test_every_entity_type_has_a_name_and_a_distinct_color(self) -> None:
        for sub in catalog.ENTITY_SUBKINDS:
            if sub == "other":
                continue
            with self.subTest(sub=sub):
                op_type = entities.entity_type(sub).op_type
                self.assertNotEqual(entities.kind_label(op_type, "es"), op_type)
        values = [v for k, v in catalog.ENTITY_SUBKINDS.items() if k != "other"]
        self.assertEqual(len(values), len(set(values)))


if __name__ == "__main__":
    unittest.main()
