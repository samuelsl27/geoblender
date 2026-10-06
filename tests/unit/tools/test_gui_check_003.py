# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación de instantáneas de la comprobación en la GUI (spec 003, T38;
``tools/inblender/gui_check_003.py``; RF-003-02, RF-003-23; CE-003-02).

``gbtools.ui_snapshot`` es puro: compara dos instantáneas (diccionarios que se pueden
guardar en JSON, como las escribe el guion dentro de Blender) y nombra cada diferencia
con su clave, lo que sobra y lo que falta.
"""

import json
import unittest

from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import ui_snapshot  # noqa: E402


def _snapshot() -> dict[str, object]:
    return {
        "draw_left": "bl_ui.space_topbar.TOPBAR_HT_upper_bar.draw_left@1a2b",
        "draw_funcs": {
            "STATUSBAR_HT_header": ["bl_ui.space_statusbar.STATUSBAR_HT_header.draw@01"],
            "VIEW3D_HT_tool_header": ["bl_ui.space_view3d.VIEW3D_HT_tool_header.draw@02"],
        },
        "addon_keymaps": {"Window": ["('wm.x', 'F11', True)"]},
        "classes": ["GEOBLENDER_OT_ui_toggle_mode"],
        "workspaces": ["Layout", "Modeling"],
        "window_workspaces": ["Layout"],
        "blender": "5.2.1",
    }


class CompareTest(unittest.TestCase):
    def test_identical(self) -> None:
        """RF-003-23, CE-003-02: dos instantáneas iguales no tienen diferencias, también
        después de pasar por JSON."""
        first = _snapshot()
        second = json.loads(json.dumps(_snapshot()))
        self.assertEqual(ui_snapshot.compare(first, second), [])

    def test_extra_append_named(self) -> None:
        """RF-003-23: un ``append`` de más a una cabecera es una diferencia, con la
        cabecera y la función añadida."""
        after = _snapshot()
        funcs = after["draw_funcs"]
        assert isinstance(funcs, dict)
        funcs["STATUSBAR_HT_header"] = [*funcs["STATUSBAR_HT_header"], "geoblender.fn@99"]
        found = ui_snapshot.compare(_snapshot(), after)
        self.assertEqual(len(found), 1)
        (difference,) = found
        self.assertEqual(difference.key, "draw_funcs[STATUSBAR_HT_header]")
        self.assertEqual(difference.added, ("geoblender.fn@99",))
        self.assertEqual(difference.removed, ())
        self.assertIn("STATUSBAR_HT_header", str(difference))
        self.assertIn("geoblender.fn@99", str(difference))

    def test_values_and_keys(self) -> None:
        """RF-003-23: un valor distinto, una clave que aparece y un elemento que falta, cada
        uno con su clave; ``ignore`` deja fuera las claves pedidas."""
        after = _snapshot()
        after["draw_left"] = "geoblender.gb_draw_left@77"
        after["workspaces"] = ["Layout"]
        after["nuevo"] = ["x"]
        found = {d.key: d for d in ui_snapshot.compare(_snapshot(), after)}
        self.assertEqual(sorted(found), ["draw_left", "nuevo", "workspaces"])
        self.assertIn("geoblender.gb_draw_left@77", str(found["draw_left"]))
        self.assertEqual(found["workspaces"].removed, ("Modeling",))
        self.assertEqual(found["nuevo"].added, ("x",))
        kept = ui_snapshot.compare(_snapshot(), after, ignore=("workspaces", "nuevo"))
        self.assertEqual([d.key for d in kept], ["draw_left"])

    def test_report(self) -> None:
        """RF-003-02: el informe junta los pasos del conmutado y las diferencias, y se
        puede guardar en JSON; sin diferencias ni pasos fallidos, ``ok``."""
        steps = [{"via": "button", "from": "Layout", "to": "GB", "applied": True}]
        report = ui_snapshot.report(_snapshot(), _snapshot(), steps)
        self.assertTrue(report["ok"])
        self.assertEqual(report["differences"], [])
        self.assertEqual(json.loads(json.dumps(report)), report)
        failed = ui_snapshot.report(_snapshot(), _snapshot(), [{**steps[0], "applied": False}])
        self.assertFalse(failed["ok"])


if __name__ == "__main__":
    unittest.main()
