# SPDX-License-Identifier: GPL-3.0-or-later
"""Los avisos pendientes de la barra N ▸ Proyecto: sin «…» y con plazo (spec 019, T42; RF-019-21; UI-28; H3 repetido, H3b-1).

El aviso «No hay ninguna operación registrada del tipo …» (``core.operation_unregistered``) es largo; con ``layout.label`` Blender
lo cortaba con «…» en medio. Ahora ``GEOBLENDER_PT_core_project.draw_notices`` lo parte en las líneas que caben (``labels.wrapped``) y
cada aviso caduca a los 15 s (``core.notices.DEFAULT_TTL``) como los de la barra de estado; ``take_notices`` y «Descartar» siguen
vaciando la lista. Se mide como ``test_ui_labels_cut``: el ancho de ``label_px`` frente al de la barra, a 1,0, 1,25 y 1,5556, en
español y en inglés.
"""

import importlib
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.blender.test_ui_labels_cut import SCALES, cut_labels
from tests.support import blender_ext
from tests.support.fake_layout import draw


def _module(name: str):
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


class ProjectNoticesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.labels = _module("bl.ui.labels")
        cls.panel = _module("bl.ui.core_panel").GEOBLENDER_PT_core_project
        cls.ps = _module("bl.scene.project_session")
        cls.i18n = _module("core.i18n")
        cls.messages = _module("core.provenance.messages")

    def setUp(self) -> None:
        self.ps.take_notices()
        self.addCleanup(self.ps.take_notices)
        self.addCleanup(self.i18n.set_language, self.i18n.language())

    def _drawn(self, scale: float, width: int):
        context = SimpleNamespace(region=SimpleNamespace(width=width))
        with mock.patch.object(self.labels.compat, "ui_scale", return_value=scale):
            layout = draw(self.panel, context)
            return layout, self.labels.sidebar_width(context)

    def test_a_the_long_unregistered_notice_is_not_cut_at_any_scale(self) -> None:
        for language in ("es", "en"):
            self.i18n.set_language(language)
            text = self.messages.render("core.operation_unregistered", language=language, op_type="des.road_carriageway_height")
            for scale in SCALES:
                for width in (300, 339, 420):
                    with self.subTest(language=language, scale=scale, width=width):
                        self.ps.take_notices()
                        self.ps.notify(text)
                        layout, available = self._drawn(scale, width)
                        alerts = [item.text for item in layout.items if item.kind == "label" and item.alert]
                        self.assertGreater(len(alerts), 1, "el aviso largo va en varias líneas")
                        self.assertEqual(cut_labels(layout, available, self.labels.label_px, (scale,)), [])
                        self.assertIn("des.road_carriageway_height", "".join(alerts).replace(" ", ""))

    def test_b_a_notice_expires_like_a_status_bar_notice(self) -> None:
        clock = {"now": 100.0}
        with mock.patch.object(self.ps, "_clock", lambda: clock["now"]):
            self.ps.notify("Aviso de prueba")
            self.assertEqual(self.ps.notices(), ("Aviso de prueba",))
            clock["now"] += 14.0
            self.assertEqual(self.ps.notices(), ("Aviso de prueba",))
            clock["now"] += 2.0  # 16 s > 15 s (DEFAULT_TTL)
            self.assertEqual(self.ps.notices(), ())
            self.ps.notify("Aviso de prueba")  # uno repetido renueva el plazo (UI-09)
            self.assertEqual(self.ps.notices(), ("Aviso de prueba",))

    def test_c_dismiss_and_take_still_empty_the_list(self) -> None:
        self.ps.notify("uno")
        self.ps.notify("dos")
        self.assertEqual(self.ps.take_notices(), ["uno", "dos"])
        self.assertEqual(self.ps.notices(), ())


if __name__ == "__main__":
    unittest.main()
