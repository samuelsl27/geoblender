# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación de instantáneas de la comprobación en la GUI (spec 003, T38;
``tools/inblender/gui_check_003.py``; RF-003-02, RF-003-23; CE-003-02).

``gbtools.ui_snapshot`` es puro: compara dos instantáneas (diccionarios que se pueden
guardar en JSON, como las escribe el guion dentro de Blender) y nombra cada diferencia
con su clave, lo que sobra y lo que falta.

Convergencia, T43 (hallazgo D4 de la comprobación en pantalla): el espacio de trabajo
marcado de Geoblender que anexa el conmutador es del fichero por diseño (CW §3.3 y §4) y no
cuenta como diferencia, pero cualquier otro espacio que sobre o falte, sí; y los ciclos
de RNF-003-06 se cuentan desde que se ejecuta el operador, no desde la orden (Ctrl+F10
simulado se ejecuta en el ciclo siguiente, al entregar el evento).
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


MAIN = "GB"  # el espacio principal que anexa el conmutador (el real sale del catálogo)


def _workspaces(names: list[str], marked: list[str]) -> dict[str, object]:
    snapshot = _snapshot()
    snapshot["workspaces"] = sorted(names)
    snapshot["geoblender_workspaces"] = sorted(marked)
    return snapshot


class AppendedWorkspaceTest(unittest.TestCase):
    """Convergencia, T43 (hallazgo D4): el anexado de un espacio marcado de Geoblender."""

    def test_appended_geoblender_tolerated(self) -> None:
        """RF-003-02, CE-003-02 (CW §3.3 y §4): el espacio marcado que no estaba antes se
        tolera en las dos claves y el informe lo dice; sin la tolerancia, es una
        diferencia en las dos."""
        before = _workspaces(["Layout", "Modeling"], [])
        after = _workspaces([MAIN, "Layout", "Modeling"], [MAIN])
        tolerated = ui_snapshot.appended_geoblender_workspaces(before, after)
        self.assertEqual(tolerated, {"workspaces": (MAIN,),
                                     "geoblender_workspaces": (MAIN,)})
        self.assertEqual(ui_snapshot.compare(before, after, tolerated=tolerated), [])
        self.assertEqual(sorted(d.key for d in ui_snapshot.compare(before, after)),
                         ["geoblender_workspaces", "workspaces"])
        report = ui_snapshot.report(before, after, [], tolerated=tolerated)
        self.assertTrue(report["ok"])
        self.assertEqual(report["tolerated"], {"geoblender_workspaces": [MAIN],
                                               "workspaces": [MAIN]})
        self.assertEqual(json.loads(json.dumps(report)), report)
        self.assertEqual(ui_snapshot.appended_geoblender_workspaces(after, after), {})

    def test_other_workspaces_still_count(self) -> None:
        """RF-003-23, CE-003-02: con el anexado tolerado, un espacio sin marcar que sobra,
        uno que falta, uno que pasa a estar marcado y uno marcado que falta siguen siendo
        diferencias, cada uno en su clave."""
        before = _workspaces(["Layout", "Modeling", "Sección", "GB · Datos"],
                             ["GB · Datos"])
        after = _workspaces([MAIN, "Layout", "Layout.001", "Sección"],
                            [MAIN, "Sección"])
        tolerated = ui_snapshot.appended_geoblender_workspaces(before, after)
        self.assertEqual(tolerated["workspaces"], (MAIN,))
        found = {d.key: d for d in ui_snapshot.compare(before, after, tolerated=tolerated)}
        self.assertEqual(sorted(found), ["geoblender_workspaces", "workspaces"])
        self.assertEqual(found["workspaces"].added, ("Layout.001",))
        self.assertEqual(found["workspaces"].removed, ("GB · Datos", "Modeling"))
        self.assertEqual(found["geoblender_workspaces"].added, ("Sección",))
        self.assertEqual(found["geoblender_workspaces"].removed, ("GB · Datos",))
        self.assertFalse(ui_snapshot.report(before, after, [], tolerated=tolerated)["ok"])

    def test_tolerance_only_for_its_keys(self) -> None:
        """La tolerancia solo quita lo tolerado de las claves que nombra, y solo lo que no
        estaba antes; una clave que antes no estaba y que solo tiene lo tolerado no es
        una diferencia."""
        before = _snapshot()
        after = _snapshot()
        after["classes"] = [*after["classes"], MAIN]  # type: ignore[misc]
        after["geoblender_workspaces"] = [MAIN]
        after["workspaces"] = [MAIN, "Layout", "Modeling"]
        tolerated = ui_snapshot.appended_geoblender_workspaces(before, after)
        found = ui_snapshot.compare(before, after, tolerated=tolerated)
        self.assertEqual([(d.key, d.added) for d in found], [("classes", (MAIN,))])


class CyclesTest(unittest.TestCase):
    """Convergencia, T43 (hallazgo D4): RNF-003-06 se mide desde que se ejecuta el
    operador."""

    def test_execution_cycle(self) -> None:
        """RNF-003-06: el operador ejecutado dentro del temporizador del guion (el botón y
        F3) está en el ciclo de ese paso; el ejecutado al entregar el evento (Ctrl+F10),
        en el del paso siguiente, porque Blender atiende los eventos antes que los
        temporizadores."""
        self.assertEqual(ui_snapshot.execution_cycle(0, in_timer=True), 0)
        self.assertEqual(ui_snapshot.execution_cycle(0, in_timer=False), 1)
        self.assertEqual(ui_snapshot.execution_cycle(3, in_timer=False), 4)
        self.assertEqual(ui_snapshot.cycles_since_execution(1, 0), 1)  # botón
        self.assertEqual(ui_snapshot.cycles_since_execution(2, 1), 1)  # Ctrl+F10
        self.assertIsNone(ui_snapshot.cycles_since_execution(40, None))  # no se ejecutó

    def test_report_first_cycle(self) -> None:
        """RNF-003-06: un paso aplicado más tarde del primer ciclo tras ejecutarse el
        operador deja el informe sin ``ok`` y se nombra; los pasos sin ciclos (omitidos o
        el de deshabilitar) no cuentan."""
        steps = [
            {"via": "button", "applied": True, "ticks": 1},
            {"via": "ctrl_f10", "applied": True, "ticks": 1, "order_ticks": 2},
            {"via": "ctrl_f10", "applied": True, "skipped": True},
            {"via": "disable", "applied": True},
        ]
        self.assertTrue(ui_snapshot.report(_snapshot(), _snapshot(), steps)["ok"])
        late = [*steps, {"via": "f3", "applied": True, "ticks": 2}]
        report = ui_snapshot.report(_snapshot(), _snapshot(), late)
        self.assertFalse(report["ok"])
        self.assertEqual(report["late_steps"], [4])


if __name__ == "__main__":
    unittest.main()
