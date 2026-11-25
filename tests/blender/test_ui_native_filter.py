# SPDX-License-Identifier: GPL-3.0-or-later
"""El filtro reversible de los paneles nativos del editor de Propiedades (spec 019, T15;
RF-019-03, RF-019-04, RNF-019-02; ADR-0032 punto 2; plan 019 A3, R-7, R-8, R-12).

- En una ventana en modo Geoblender **ningún panel nativo pasa su ``poll``**; en una de
  «Layout» pasan los de siempre (RF-019-03).
- Tras desactivar la extensión, **cada atributo ``poll`` es el mismo objeto de antes** y el
  árbol del contexto Objeto se registra de nuevo **en el orden original** (RF-019-04).
- Es idempotente, también tras ``script.reload`` (el módulo pierde su estado y el filtro se
  recupera de la marca de cada ``poll``) (ADR-0032).
- Dos ventanas en modos distintos deciden cada una por la suya (R-12) y el filtro vive
  mientras haya una en modo Geoblender (P-5).
- Un árbol con otra forma deja el modo degradado: nada se toca y se dice una vez (R-8).
- Redibujar cuesta menos de 1 ms más (RNF-019-02).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import statistics
import time
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

COST_BUDGET_MS = 1.0
GB_NAME = "gbtest_t15_geoblender"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _natives() -> list[type]:
    return [c for c in bpy.types.Panel.__subclasses__()
            if getattr(c, "bl_space_type", "") == "PROPERTIES"
            and not c.__name__.startswith("GEOBLENDER_") and getattr(c, "is_registered", False)]


def _tree(classes: list[type]) -> list[type]:
    return [c for c in classes if getattr(c, "bl_context", "") == "object"]


def _polls(classes: list[type]) -> dict[type, object]:
    return {c: c.__dict__.get("poll") for c in classes}


def _call(cls: type, context: object) -> bool:
    poll = getattr(cls, "poll", None)
    if poll is None:
        return True
    try:
        return bool(poll(context))
    except Exception:  # noqa: BLE001 - como Blender: si el poll falla, se dibuja
        return True


class NativeFilterTest(unittest.TestCase):
    """RF-019-03, RF-019-04: el filtro, sin pantalla (``poll`` con un contexto con espacio de
    trabajo; el redibujo real, en el H3)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.nf = _module("bl.ui.native_filter")
        # Blender 5.2 no crea espacios de trabajo vacíos desde Python: el de Geoblender es un
        # sustituto con la marca (el filtro solo lee ``geoblender_mode``, como la puerta).
        self.gb = SimpleNamespace(name=GB_NAME, geoblender_mode=True)
        self.blender_ws = bpy.data.workspaces.get("Layout") or bpy.data.workspaces[0]
        self.assertFalse(self.blender_ws.geoblender_mode)
        self.gb_window = SimpleNamespace(workspace=self.gb)
        self.bl_window = SimpleNamespace(workspace=self.blender_ws)

    def tearDown(self) -> None:
        if blender_ext.is_enabled():
            self.nf.remove()

    def test_no_native_panel_passes_in_geoblender(self) -> None:
        """RF-019-03: con una ventana en modo Geoblender, ningún panel nativo pasa su
        ``poll`` en su contexto; en una de «Layout», los de siempre."""
        natives = _natives()
        before = {c: _call(c, bpy.context) for c in natives}
        self.assertTrue(self.nf.sync([self.gb_window]))
        self.assertTrue(self.nf.installed())
        in_gb = SimpleNamespace(workspace=self.gb)
        passing = [c.__name__ for c in natives if c.poll(in_gb)]
        self.assertEqual(passing, [])
        self.assertTrue(all(c.is_registered for c in _tree(natives)))
        after = {c: _call(c, bpy.context) for c in natives}
        self.assertEqual(after, before)

    def test_identity_and_order_after_unregister(self) -> None:
        """RF-019-04: tras desactivar la extensión cada ``poll`` es el mismo objeto de antes
        y el árbol se registra de nuevo en el orden original."""
        natives = _natives()
        tree_before = [c.__name__ for c in _tree(natives)]
        self.assertGreaterEqual(len(tree_before), 19)
        polls_before = _polls(natives)
        registered_before = {c: c.is_registered for c in natives}
        self.assertTrue(self.nf.sync([self.gb_window]))
        self.assertNotEqual(_polls(natives), polls_before)  # de verdad parcheó
        calls: list[str] = []
        real = bpy.utils.register_class

        def spy(cls: type) -> None:
            calls.append(cls.__name__)
            real(cls)

        with mock.patch.object(bpy.utils, "register_class", side_effect=spy):
            blender_ext.release()  # unregister() de la extensión
        self.assertFalse(self.nf.installed())
        self.assertEqual(calls, tree_before)  # el orden original, padres antes que hijos
        after = _natives()
        polls_after = _polls(after)
        self.assertEqual(set(polls_after), set(polls_before))
        for cls, entry in polls_before.items():
            self.assertIs(polls_after[cls], entry, cls.__name__)  # el mismo objeto (o ausente)
        self.assertEqual({c: c.is_registered for c in after}, registered_before)
        self.assertEqual([c.__name__ for c in _tree(after)], tree_before)

    def test_idempotent_and_survives_script_reload(self) -> None:
        """ADR-0032: instalar dos veces no envuelve dos veces; tras recargar el módulo (pierde
        su estado) se recupera de la marca y se retira dejando el original."""
        natives = _natives()
        polls_before = _polls(natives)
        self.assertTrue(self.nf.install())
        wrapped = _polls(natives)
        self.assertTrue(self.nf.install())
        self.assertEqual(_polls(natives), wrapped)
        # script.reload desactiva (quita avisos y manejadores del módulo viejo) y recarga el
        # módulo con el filtro puesto por un caso que no pasó por unregister()
        self.nf.unregister()
        self.assertTrue(self.nf.install())
        reloaded = importlib.reload(self.nf)  # estado nuevo y vacío
        self.assertFalse(reloaded.installed())
        self.assertTrue(reloaded.install())
        self.assertEqual(sum(1 for c in natives if reloaded._marked(c) is not None), len(natives))
        reloaded.remove()
        self.assertFalse(reloaded.installed())
        for cls, entry in polls_before.items():
            self.assertIs(cls.__dict__.get("poll"), entry, cls.__name__)
        self.nf = reloaded

    def test_two_windows_decide_each_by_its_own(self) -> None:
        """R-12, P-5: el ``poll`` mira el espacio de trabajo de su contexto; se pone con una
        ventana en modo Geoblender aunque otra esté en Blender y se retira con la última."""
        transform = bpy.types.OBJECT_PT_transform
        self.assertTrue(self.nf.sync([self.gb_window, self.bl_window]))
        self.assertFalse(transform.poll(SimpleNamespace(workspace=self.gb)))
        self.assertTrue(transform.poll(SimpleNamespace(workspace=self.blender_ws)))
        self.assertTrue(self.nf.sync([self.gb_window]))
        self.assertFalse(self.nf.sync([self.bl_window]))  # la última sale: se retira
        self.assertFalse(self.nf.installed())
        self.assertNotIn("poll", transform.__dict__)
        self.assertFalse(self.nf.sync([]))

    def test_rescan_picks_up_new_panels(self) -> None:
        """R-7: «Reparar la interfaz» vuelve a escanear y un panel nuevo se filtra."""

        class OTHER_PT_t15_extra(bpy.types.Panel):
            bl_label = "Extra"
            bl_space_type = "PROPERTIES"
            bl_region_type = "WINDOW"
            bl_context = "object"

            def draw(self, context: object) -> None:
                pass

        self.assertTrue(self.nf.sync([self.gb_window]))
        bpy.utils.register_class(OTHER_PT_t15_extra)
        try:
            self.assertNotIn("poll", OTHER_PT_t15_extra.__dict__)
            self.assertTrue(self.nf.rescan())
            self.assertFalse(OTHER_PT_t15_extra.poll(SimpleNamespace(workspace=self.gb)))
            self.nf.remove()
            self.assertNotIn("poll", OTHER_PT_t15_extra.__dict__)
        finally:
            bpy.utils.unregister_class(OTHER_PT_t15_extra)

    def test_degraded_mode_touches_nothing_and_says_it_once(self) -> None:
        """R-8: si el árbol del contexto Objeto no tiene la forma esperada, no se filtra, no
        se toca nada y se dice una sola vez."""
        polls_before = _polls(_natives())
        compat = _module("bl.compat")
        shape = compat.NativeFilterShape("object", 999, "x", "x")
        with mock.patch.object(compat, "native_filter_shape", return_value=shape):
            with self.assertLogs("geoblender.bl.ui", level="WARNING") as logs:
                self.assertFalse(self.nf.install())
                self.assertFalse(self.nf.install())
                self.assertFalse(self.nf.sync([self.gb_window]))
        self.assertEqual(len(logs.records), 1)
        self.assertIn("degradado", logs.output[0].lower())
        self.assertIsNotNone(self.nf.degraded_reason())
        self.assertFalse(self.nf.installed())
        self.assertEqual(_polls(_natives()), polls_before)

    def test_redraw_cost_under_one_millisecond(self) -> None:
        """RNF-019-02: consultar el ``poll`` de todos los paneles cuesta menos de 1 ms más con
        el filtro puesto, en una ventana de Blender (la que más trabajo hace)."""
        natives = _natives()
        context = SimpleNamespace(workspace=self.blender_ws, object=None, space_data=None)

        def run() -> float:
            samples = []
            for _ in range(25):
                start = time.perf_counter()
                for cls in natives:
                    _call(cls, context)
                samples.append((time.perf_counter() - start) * 1000)
            return statistics.median(samples)

        base = run()
        self.assertTrue(self.nf.install())
        filtered = run()
        self.nf.remove()
        print(f"[T15] poll de {len(natives)} paneles: sin filtro {base:.3f} ms, "
              f"con filtro {filtered:.3f} ms, diferencia {filtered - base:.3f} ms")
        self.assertLess(filtered - base, COST_BUDGET_MS)


if __name__ == "__main__":
    unittest.main()
