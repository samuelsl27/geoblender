# SPDX-License-Identifier: GPL-3.0-or-later
"""El objeto de la pista y el de la accesibilidad en la vista: lo que no necesita un proyecto (spec 017, T31; HU-017-1, HU-017-3; RF-015-25, RF-017-23, RF-017-25;
plan 017 §5.1 y §5.5; comprobación manual M4 en la T31b).

Lo de con proyecto (el objeto de una pista con su huella y su eje 3D, el de una accesibilidad con su rejilla, que se regeneran, y el de una pista descartada o de
«apoyo retirado») cuesta ≈ 15 s de mundo y es un hito (``tests/blender/milestone_road_views.py``, P-12); aquí, en el «verde» y sin proyecto:

- RF-015-25, RF-017-23 (a): la **pista** es un objeto ``DESIGN_ENTITY`` (decisión T31-a): su tabla de huella (``des_epr_``) sigue teniendo el cargador de la entidad, que dibuja
  su huella y **su eje 3D**; el eje por estaciones (``des_rdx_``), la capa de ejes (``des_rax_``), la capa propuesta (``des_rpl_``) y las tablas de la accesibilidad no tienen
  cargador propio: el de la pista lleva su eje y las demás las lee la barra N o QGIS. La pista tiene su color y el tipo y su descripción dicen que también es una pista.
- RF-015-25, RF-017-25 (b): lo alcanzable de una accesibilidad (``des_acc_``) tiene su cargador, del tipo ``DESIGN`` (el de las superficies de un diseño: la rejilla «como
  cualquier superficie»), con su nombre traducido y un nombre que no repite el de otro; su cargador dibuja lo alcanzable **sobre su superficie**, no sus 1 y 0 como cotas.
- Principio 8 (z): desactivar Geoblender quita los dos cargadores y la huella de Blender vuelve a la del principio de la sesión.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType

from tests.support import blender_ext

KIND = "DESIGN_ENTITY"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


class RoadViewsRegistrationTest(unittest.TestCase):
    """La extensión habilitada una vez: el registro de la vista de la pista y de la accesibilidad, sin proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.views = _module("bl.scene.views")
        cls.entity_views = _module("bl.scene.entity_views")
        cls.des_views = _module("bl.scene.des_views")
        cls.core_props = _module("bl.props.core")
        cls.i18n = _module("core.i18n")
        cls.dprov = _module("design.provenance")

    def test_a_the_road_is_a_design_entity_with_its_axis_and_the_tables_that_are_not_objects_have_no_loader(self) -> None:
        """RF-015-25, RF-017-23 (plan 017 §5.1; decisión T31-a): la tabla de huella de una pista (``des_epr_``) tiene el cargador de la entidad, del tipo ``DESIGN_ENTITY``
        (la pista es una entidad: lleva la barra N «Entidad» y su menú); el eje por estaciones (``des_rdx_``), su informe (``des_prp_``), la capa de ejes (``des_rax_``), la
        capa propuesta (``des_rpl_``) y lo que la accesibilidad guarda de bermas, plataformas y zonas (``des_acb_``, ``des_acp_``, ``des_acz_``) no se cargan solos; la pista tiene
        su color y el tipo de objeto y su descripción dicen que también es una pista, traducidos."""
        again = self.views.loader_for("des_epr_pista")
        self.assertEqual((again.prefix, again.kind, again.label), ("des_epr_", KIND, "Design entity"))
        self.assertIs(again.load, self.entity_views.load_entity, "la pista la carga el cargador de la entidad, que dibuja además su eje 3D")
        for name in ("des_rdx_pista", "des_prp_pista", "des_psf_pista", "des_rax_v01", "des_rpl_ruta", "des_acb_acceso", "des_acp_acceso", "des_acz_acceso"):
            self.assertIsNone(self.views.loader_for(name), name)
        kinds = {item[0]: item for item in self.core_props.OBJECT_KINDS}
        self.assertEqual(self.views.BRANCHES[KIND], (("design", "Design"),))
        self.assertIn("haul road", kinds[KIND][2])
        self.assertIn("stockpile detection", kinds[KIND][2], "lo de la 015 y la 016 sigue en la descripción")
        self.assertEqual(self.i18n.untranslated([kinds[KIND][1], kinds[KIND][2]]), [])
        self.assertIn("pista", self.i18n.translate("es", kinds[KIND][2]))
        colors = self.entity_views.COLORS
        self.assertEqual(colors.keys(), {"platform", "stockpile", "removal", "buttress", "body", "road", "pit"})
        self.assertEqual(len(set(colors.values())), len(colors), "cada tipo, su color")
        self.assertNotEqual(colors["road"], self.entity_views.OTHER_COLOR)
        self.assertIn("road", {kind.value for kind in _module("design.entities").EntityKind}, "es el tipo que dice la tabla de la pista")

    def test_b_the_reachable_grid_of_an_accessibility_loads_like_a_surface_drawn_on_its_surface(self) -> None:
        """RF-015-25, RF-017-25 (plan 017 §5.1: «como cualquier superficie»): lo alcanzable (``des_acc_``, 1 alcanzable y 0 no) tiene cargador del tipo ``DESIGN`` (el de las
        rejillas de un diseño: una malla con un vértice por celda con dato), con su nombre traducido que no repite el de otro; **no es una cota**: su cargador es el de las zonas,
        que dibuja las celdas alcanzables **a la cota de su superficie** (como el recinto excavable, ``des_rcn_``), y no el de las cotas; las rejillas de las specs anteriores
        siguen con el suyo."""
        loader = self.views.loader_for("des_acc_acceso")
        self.assertEqual((loader.prefix, loader.kind, loader.label), ("des_acc_", "DESIGN", "Reachable by the roads"))
        self.assertIs(loader.load, self.des_views.load_access_grid)
        self.assertIs(self.des_views.loader_of(self.dprov.ACCESS_GRID), self.des_views.load_access_grid)
        self.assertEqual(self.i18n.translate("es", loader.label), "Lo alcanzable por las pistas")
        self.assertEqual(self.i18n.untranslated([loader.label]), [])
        self.assertIn((self.dprov.ACCESS_GRID, "Reachable by the roads"), self.des_views.LOADERS)
        self.assertEqual(len({label for _family, label in self.des_views.LOADERS}), len(self.des_views.LOADERS), "ningún nombre se repite")
        self.assertIs(self.views.loader_for("des_stb_acopios_mineral").load, self.des_views.load_design_grid)
        self.assertIs(self.views.loader_for("des_rcn_recinto").load, self.des_views.load_area_grid)

    def test_c_a_road_without_its_axis_is_drawn_at_the_height_of_its_surface_and_says_so(self) -> None:
        """RF-015-25, RF-017-23: el aviso de una pista cuyo eje por estaciones no se puede leer (``des_rdx_`` sin tabla o vacío) existe y está traducido; con él la vista dibuja
        el eje de la huella a la cota de su superficie en lugar de no dibujarlo."""
        msgid = "The road «{name}» has no usable axis by stations: its axis is drawn at the height of its surface"
        self.assertEqual(self.i18n.untranslated([msgid]), [])
        self.assertIn("«{name}»", self.i18n.translate("es", msgid))

    def test_z_disabling_geoblender_removes_the_loaders_and_leaves_blender_as_it_was(self) -> None:
        """Principio 8 (``geoblender/AGENTS.md``, Registro): deshabilitada la extensión no queda ningún cargador de la vista de la pista ni de lo alcanzable, y la huella
        entera de Blender vuelve a la del principio de la sesión."""
        self.assertIsNotNone(self.views.loader_for("des_acc_acceso"))
        self.assertIsNotNone(self.views.loader_for("des_epr_pista"))
        self.addCleanup(blender_ext.enable)  # las demás pruebas de la clase, habilitada
        blender_ext.disable()
        for name in ("des_acc_acceso", "des_epr_pista"):
            self.assertIsNone(self.views.loader_for(name), name)
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
