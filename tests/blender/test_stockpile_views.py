# SPDX-License-Identifier: GPL-3.0-or-later
"""El objeto y la barra N «Entidad» con los tipos nuevos de la 016: lo que no necesita un proyecto (spec 016, T33; HU-016-1 a HU-016-4; RF-015-25,
RF-016-14, RF-016-09; plan 016 §5.5; comprobación manual M5).

Lo de con proyecto (los objetos de la detección, la retirada, el contrafuerte y el cuerpo, la barra N de cada uno y sus estados) cuesta ≈ 20 s de
mundo y es un hito (``tests/blender/milestone_stockpile_views.py``, P-13); aquí, en el «verde» y sin proyecto:

- RF-015-25, RF-016-14 (a): la tabla de acopios de una detección (``des_stk_``) tiene su cargador, **del tipo** ``DESIGN_ENTITY`` (la detección es una
  entidad: lleva la barra N «Entidad» y su menú) y con el nombre de su tipo; la de la entidad (``des_epr_``) sigue ahí; la superficie con que se
  detectó, las demás tablas y el informe no tienen cargador; el tipo y su descripción están traducidos.
- RF-016-09 (b): la base, el espesor y el terreno sin acopios de la detección y el espesor y la base de un cuerpo se cargan como cualquier superficie
  (tipo ``DESIGN``), cada una con su nombre.
- RF-015-25 (c): una entidad de la 016 se nombra con su tipo («Retirada de acopio Quitar el 2»), sin repetirlo si el nombre ya lo dice
  («Plataforma de carga», no «Plataforma Plataforma de carga»); las opciones de sus parámetros tienen rótulo en los dos idiomas.
- ADR-0005 (d): el nombre del grupo de vértices de un acopio (su referencia) cabe en lo que admite Blender y no se repite.
- Principio 8 (z): desactivar Geoblender quita los cargadores, y la huella de Blender vuelve a la del principio de la sesión.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType

from tests.support import blender_ext

KIND = "DESIGN_ENTITY"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


class StockpileViewsRegistrationTest(unittest.TestCase):
    """La extensión habilitada una vez: el registro de la vista de los acopios y los textos de la barra N, sin proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.views = _module("bl.scene.views")
        cls.entity_views = _module("bl.scene.entity_views")
        cls.des_views = _module("bl.scene.des_views")
        cls.constraint_views = _module("bl.scene.constraint_views")
        cls.core_props = _module("bl.props.core")
        cls.panels = _module("bl.ui.des_panels")
        cls.i18n = _module("core.i18n")

    def test_a_the_table_of_stockpiles_has_its_loader_of_the_kind_of_an_entity(self) -> None:
        """RF-015-25, RF-016-14 (plan 016 §5.1, §5.5): ``des_stk_`` (la tabla de acopios de una detección, una fila por acopio) tiene su cargador,
        del tipo ``DESIGN_ENTITY`` y con el nombre «Detección de acopios»; ``des_epr_`` (la huella de una entidad) sigue con el suyo; ni la
        superficie con que se detectó (``des_stp_``), ni la de una entidad (``des_psf_``), ni los candidatos (``des_stc_``), ni el informe
        (``des_prp_``) se cargan; el tipo y su descripción son los de las dos specs y están traducidos."""
        loader = self.views.loader_for("des_stk_acopios")
        self.assertEqual((loader.prefix, loader.kind, loader.label), ("des_stk_", KIND, "Stockpile detection"))
        self.assertIs(loader.load, self.entity_views.load_stockpiles)
        self.assertEqual(self.i18n.translate("es", loader.label), "Detección de acopios")
        again = self.views.loader_for("des_epr_carga")
        self.assertEqual((again.prefix, again.kind, again.label), ("des_epr_", KIND, "Design entity"))
        for name in ("des_stp_acopios", "des_psf_carga", "des_stc_acopios", "des_prp_acopios"):
            self.assertIsNone(self.views.loader_for(name), name)
        kinds = {item[0]: item for item in self.core_props.OBJECT_KINDS}
        self.assertIn("stockpile detection", kinds[KIND][2])
        self.assertEqual(self.i18n.untranslated([kinds[KIND][1], kinds[KIND][2]]), [])
        self.assertEqual(self.views.BRANCHES[KIND], (("design", "Design"),))
        self.assertEqual(self.entity_views.detected_name("des_stk_acopios"), "des_stp_acopios")
        self.assertEqual(self.entity_views.base_name("des_epr_cuerpo"), "des_bds_cuerpo")
        with self.assertRaises(ValueError):
            self.entity_views.detected_name("des_epr_acopios")
        self.assertEqual(self.entity_views.COLORS.keys(), {"platform", "stockpile", "removal", "buttress", "body", "road"})  # inventario: el de la pista, de la 017 (T31)

    def test_b_the_grids_of_the_stockpiles_and_the_bodies_load_like_any_surface(self) -> None:
        """RF-016-09, RF-016-24 (plan §5.5): la base, el espesor y el terreno sin acopios de una detección y el espesor y la base de un cuerpo
        tienen cargador del tipo ``DESIGN`` (el de las superficies de un diseño), con un nombre cada uno, traducido, que no repite el de otro."""
        labels = {"stb": "Base de acopios", "stt": "Espesor de acopios", "stg": "Terreno sin acopios", "bdt": "Espesor de un cuerpo",
                  "bds": "Base de un cuerpo"}
        found = set()
        for family, label_es in labels.items():
            with self.subTest(familia=family):
                loader = self.views.loader_for(f"des_{family}_x")
                self.assertEqual((loader.prefix, loader.kind), (f"des_{family}_", "DESIGN"))
                self.assertIs(loader.load, self.des_views.load_design_grid)
                self.assertEqual(self.i18n.translate("es", loader.label), label_es)
                self.assertEqual(self.i18n.untranslated([loader.label]), [])
                found.add(loader.label)
        self.assertEqual(len(found), len(labels))
        self.assertEqual(len({label for _family, label in self.des_views.LOADERS}), len(self.des_views.LOADERS))

    def test_c_an_entity_of_the_new_types_is_named_with_its_type_without_repeating_it(self) -> None:
        """RF-015-25 (T32 y T28 de la 015: el tipo en el nombre): una entidad de cada tipo se nombra con el suyo («Contrafuerte Cima», «Detección de
        acopios Acopios») y, si la primera palabra de su nombre ya es la de su tipo, solo con su nombre («Plataforma de carga», «Retirada del acopio 2»); una declarada se
        lee con él («Contrafuerte Cima (declarada)»), no con su código; las opciones de los parámetros de cerrada tienen rótulo en los dos idiomas."""
        text = self.constraint_views.entity_text
        self.assertEqual(text("BTR-001", "Cima"), "Contrafuerte Cima")
        self.assertEqual(text("STK-001", "Acopios"), "Detección de acopios Acopios")
        self.assertEqual(text("RMV-002", "Quitar el 2"), "Retirada de acopio Quitar el 2")
        self.assertEqual(text("RMV-002", "Retirada del acopio 2"), "Retirada del acopio 2", "su primera palabra ya es el tipo")
        self.assertEqual(text("BDY-001", "Relleno"), "Cuerpo apoyado Relleno")
        self.assertEqual(text("PLT-001", "P1"), "Plataforma P1")
        self.assertEqual(text("PLT-002", "Plataforma de carga"), "Plataforma de carga", "sin «Plataforma Plataforma de carga»")
        self.assertEqual(text("BTR-001", "contrafuerte del norte"), "contrafuerte del norte")
        self.assertEqual(text("XX-001", "Otro"), "Otro", "un tipo que no se conoce: solo el nombre")
        self.assertEqual(self.constraint_views.declared_text("BTR-001", "Cima"), "Contrafuerte Cima (declarada)")
        found = self.panels._CHOICES_TEXT  # noqa: SLF001
        for param, options in found.items():
            for value, msgid in options.items():
                with self.subTest(parametro=param, valor=value):
                    self.assertEqual(self.i18n.untranslated([msgid]), [])
        self.assertEqual(self.panels._choice_label("sense", "under_roof"), "Bajo un techo")  # noqa: SLF001
        self.assertEqual(self.panels._choice_label("mode", "cut"), "En corte")  # noqa: SLF001
        self.assertIsNone(self.panels._choice_label("layer", "x"))  # noqa: SLF001

    def test_d_the_label_of_a_stockpile_fits_a_vertex_group(self) -> None:
        """ADR-0005 (T33): el nombre del grupo de vértices de un acopio es su referencia; una clave larguísima se recorta a los 63 bytes que
        admite Blender sin cortar un carácter, y dos que quedan igual se distinguen con ``~2``, ``~3``; Blender acepta los nombres resultantes."""
        import bpy

        group = self.entity_views.group_name
        taken: set[str] = set()
        self.assertEqual(group("STK-001#m07", taken), "STK-001#m07")
        self.assertEqual(group("STK-001#m07", taken), "STK-001#m07~2", "la misma referencia otra vez")
        long_key = "STK-001#" + "ñ" * 60  # 120 bytes
        first, second = group(long_key, taken), group(long_key + "x", taken)
        self.assertLessEqual(len(first.encode()), 63)
        self.assertLessEqual(len(second.encode()), 63)
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("STK-001#ñ") and second.endswith("~2"), (first, second))
        mesh = bpy.data.meshes.new("gb-prueba-grupos")
        obj = bpy.data.objects.new("gb-prueba-grupos", mesh)
        try:
            for name in (*taken,):
                self.assertEqual(obj.vertex_groups.new(name=name).name, name)
        finally:
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)

    def test_e_the_report_lines_are_the_warnings_of_the_calculation_in_order(self) -> None:
        """RF-015-25 (plan §5.5): las filas ``warning`` y ``note`` del informe de una entidad (su código y sus valores en JSON, no el texto) salen
        como líneas de la barra N en el idioma de la interfaz, el aviso en ámbar; el lugar de una cifra (``x;y``) se lee y el que no lo es, no."""
        report = (("removed_m3", 12.0, "m3", None), ("warning", None, None, '{"code": "des.stockpile_footprint_at_edge", "values": '
                                                                            '{"mark": "Dos", "x": 1.0, "y": 2.0}}'),
                  ("note", None, None, '{"code": "des.stockpile_candidate_item", "values": {"candidate": "c01", "area": 36.0, '
                                       '"volume": 12.0, "level": 100.0, "slope": 2.0, "azimuth": 45.0, "x": 5.0, "y": 6.0}}'))
        lines = self.panels._report_notice_lines(report)  # noqa: SLF001
        self.assertEqual([(line.kind, line.alert) for line in lines], [("field", True), ("field", False)])
        self.assertTrue(lines[0].text.startswith("Acopio «Dos»: su huella llega al borde"), lines[0].text)
        self.assertTrue(lines[1].text.startswith("Candidato c01: huella de 36 m²"), lines[1].text)
        self.assertEqual(self.panels._report_place("700001.5;4400002.25"), (700001.5, 4400002.25))  # noqa: SLF001
        for bad in (None, "", "sin lugar", "a;b"):
            self.assertIsNone(self.panels._report_place(bad))  # noqa: SLF001
        self.assertEqual(self.panels._report_notice_lines(()), [])  # noqa: SLF001

    def test_z_disabling_geoblender_removes_the_loaders_and_leaves_blender_as_it_was(self) -> None:
        """Principio 8 (``geoblender/AGENTS.md``, Registro): deshabilitada la extensión no queda ningún cargador de la vista de los acopios ni de
        las rejillas que dejan, y la huella entera de Blender vuelve a la del principio de la sesión."""
        self.assertIsNotNone(self.views.loader_for("des_stk_acopios"))
        self.assertIsNotNone(self.views.loader_for("des_stb_acopios_mineral"))
        self.addCleanup(blender_ext.enable)  # las demás pruebas de la clase, habilitada
        blender_ext.disable()
        for name in ("des_stk_acopios", "des_epr_carga", "des_stb_acopios_mineral", "des_stt_acopios_mineral", "des_stg_acopios",
                     "des_bdt_cuerpo", "des_bds_cuerpo"):
            self.assertIsNone(self.views.loader_for(name), name)
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
