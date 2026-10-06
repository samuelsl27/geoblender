# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia local y publicación desde Blender (spec 002, T34; RF-002-31, RF-002-32,
RF-002-33; RNF-002-06; plan 002 §5.3; BS §8.1).

- ``geoblender.core_checkout_project`` («Trabajar en copia local…»): modal que avanza
  ``checkout_steps`` sobre el proyecto de la sesión (que se cierra antes, para reservarlo)
  y deja abierta la copia; Esc cancela sin dejar copia ni reserva y vuelve a abrir el
  original.
- ``geoblender.core_publish_project`` («Publicar en la red…»): modal que avanza
  ``publish_steps`` sobre la copia de la sesión y, si se pide, abre el publicado; Esc
  cancela antes de sustituir nada; si no se puede publicar, la copia sigue abierta.
- ``GEOBLENDER_MT_core_network`` («Copia local y red ▸») y el botón de la pestaña
  «Proyecto».

RNF-002-06 con un proyecto sintético de 200 MB: el progreso se actualiza al menos cada
segundo y Esc cancela en ≤ 2 s. En ``blender -b`` no hay bucle de eventos: las pruebas
toman el modal de ``window.modal_operators`` y le pasan los eventos ``TIMER`` (seguidos,
sin la espera de 0,05 s del temporizador) y ``ESC``, midiendo cuánto tarda cada llamada y
el tiempo entre dos actualizaciones del progreso. Se ejecuta con
``tools/run_blender_tests.py``.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

from gbtools import manifest  # noqa: E402

CONTEXT = manifest.load(ROOT / manifest.MANIFEST_RELPATH)["name"]
WINDOW = (699_500.4, 4_399_500.6, 700_500.2, 4_400_500.9)
BIG = 200 * 1024 * 1024  # el proyecto sintético de RNF-002-06 (spec 002, T34)
PROGRESS_GAP_S = 1.0
ESCAPE_S = 2.0
ORIGINAL = "Cantera Prueba.gbproj"
PREVIOUS = "Cantera Prueba.gbproj.anterior"
STAGING = "Cantera Prueba.gbproj.publicando"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESC = SimpleNamespace(type="ESC", value="PRESS")


def ext(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión (ya importado)."""
    return sys.modules[f"{module_name()}.{name}"]


def write_big(path: Path, size: int) -> None:
    """Un fichero de ``size`` bytes, por trozos de 8 MiB (contenido sin importancia)."""
    block = os.urandom(8 * 1024 * 1024)
    with path.open("wb") as handle:
        left = size
        while left > 0:
            handle.write(block[: min(left, len(block))])
            left -= len(block)


class CheckoutOpsTestCase(unittest.TestCase):
    """La extensión habilitada, la escena de fábrica y una carpeta temporal con un
    proyecto creado y abierto en esta sesión."""

    def setUp(self) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        self.tmp = Path(tempfile.mkdtemp(prefix="gb-t34-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(blender_ext.load_file)
        self.addCleanup(blender_ext.unload)
        blender_ext.enable()
        self.ps = ext("bl.scene.project_session")
        self.ops = ext("bl.ops.core")
        self.core = ext("core.project")
        self.lock = ext("core.project.lock")
        self.ps.take_notices()
        self.parent = self.tmp / "red"
        self.parent.mkdir()
        self.copies = self.tmp / "copias"
        self.copies.mkdir()

    # Ayudas -------------------------------------------------------------------------

    def open_project(self, big: int = 0) -> object:
        """Crea «Cantera Prueba» (con un ráster de ``big`` bytes) y lo deja abierto en
        escritura en la sesión."""
        settings = self.core.ProjectSettings(name="Cantera Prueba", window=WINDOW)
        result = self.core.create_project(
            self.parent, settings, self.ps.session(), self.ps.userdata()
        )
        self.root = result.root
        if big:
            write_big(self.root / "rasters" / "gis_dtm_grande.tif", big)
        self.ps.attach(result.project)
        return result.project

    def running(self, cls: type) -> object:
        found = [
            op for op in bpy.context.window.modal_operators
            if isinstance(op, cls) and getattr(op, "_steps", None) is not None
        ]
        self.assertEqual(len(found), 1, f"{cls.__name__} no está en marcha como modal")
        return found[0]

    def drive(self, operator: object, until=None) -> tuple[set[str], list[float]]:
        """Pasa eventos ``TIMER`` seguidos al modal hasta que termina (o hasta que
        ``until(operator)`` es verdadero); devuelve su estado y cuánto tardó cada
        llamada."""
        calls: list[float] = []
        state = {"RUNNING_MODAL"}
        for _ in range(100_000):
            if until is not None and until(operator):
                break
            started = time.perf_counter()
            state = operator.modal(bpy.context, TIMER)
            calls.append(time.perf_counter() - started)
            if state != {"RUNNING_MODAL"}:
                break
        return state, calls

    def run_operator(self, idname: str, cls_name: str, **props: object) -> object:
        """Lanza el operador y lo lleva hasta el final; devuelve el operador."""
        operator_fn = getattr(bpy.ops.geoblender, idname)
        self.assertEqual(operator_fn("EXEC_DEFAULT", **props), {"RUNNING_MODAL"})
        operator = self.running(getattr(self.ops, cls_name))
        state, _calls = self.drive(operator)
        self.assertIn(state, ({"FINISHED"}, {"CANCELLED"}))
        return operator

    def checkout(self, **props: object) -> object:
        props.setdefault("directory", str(self.copies))
        return self.run_operator(
            "core_checkout_project", "GEOBLENDER_OT_core_checkout_project", **props
        )

    def publish(self, **props: object) -> object:
        return self.run_operator(
            "core_publish_project", "GEOBLENDER_OT_core_publish_project", **props
        )

    def finish_reopen(self) -> None:
        """Lleva hasta el final la reapertura del original que lanza una copia cancelada."""
        operator = self.running(self.ops.GEOBLENDER_OT_core_open_project)
        state, _calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})

    def assert_progress(self, operator: object, calls: list[float]) -> None:
        """Comprueba que ninguna llamada del modal pasa de 1 s y que entre dos
        actualizaciones del progreso no pasa más de 1 s."""
        times = [entry[0] for entry in operator.progress_log]
        self.assertGreater(len(times), 10)
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        self.assertLessEqual(max(gaps), PROGRESS_GAP_S, f"hueco máximo {max(gaps):.3f} s")
        self.assertLessEqual(max(calls), PROGRESS_GAP_S, f"llamada máxima {max(calls):.3f} s")
        print(f"\n    {type(operator).__name__}: {len(times)} actualizaciones del progreso, hueco "
              f"máximo {max(gaps):.3f} s, llamada máxima {max(calls):.3f} s")

    def escape(self, operator: object) -> float:
        started = time.perf_counter()
        state = operator.modal(bpy.context, ESC)
        took = time.perf_counter() - started
        self.assertEqual(state, {"CANCELLED"})
        self.assertLessEqual(took, ESCAPE_S, f"Esc tardó {took:.3f} s")
        print(f"    {type(operator).__name__}: Esc en {took:.3f} s")
        return took

    @staticmethod
    def copy_phase_half(operator: object) -> bool:
        """Verdadero cuando la copia va por más de la mitad."""
        for _time, phase, done, total, _message in reversed(operator.progress_log):
            if phase == "copia":
                return total > 0 and done * 2 > total
        return False


class NamesAndInterfaceTest(CheckoutOpsTestCase):
    def test_names_menu_and_panel(self) -> None:
        """ADR-0011, BS §8.1, RF-002-31, RF-002-32: los dos operadores con
        ``geoblender.core_<acción>``, sin ``UNDO`` y modales; el menú «Copia local y red ▸»
        con «Trabajar en copia local…», «Publicar en la red…» y el cerrojo; y en la pestaña
        «Proyecto», el botón que toca: sacar copia en el original y publicar en la copia."""
        for action in ("checkout_project", "publish_project"):
            with self.subTest(operador=action):
                cls = getattr(self.ops, f"GEOBLENDER_OT_core_{action}")
                self.assertTrue(cls.is_registered)
                self.assertEqual(cls.bl_idname, f"geoblender.core_{action}")
                self.assertNotIn("UNDO", cls.bl_options)
                self.assertIn("REGISTER", cls.bl_options)
                self.assertEqual(cls.bl_translation_context, CONTEXT)
                self.assertTrue(hasattr(cls, "modal"))
        menu = ext("bl.ui.core_menus").GEOBLENDER_MT_core_network
        self.assertTrue(menu.is_registered)
        self.assertEqual(menu.bl_translation_context, CONTEXT)
        layout = draw(menu, bpy.context)
        self.assertEqual(
            [(item.target, item.text) for item in layout.of_kind("operator")],
            [
                ("geoblender.core_checkout_project", "Trabajar en copia local…"),
                ("geoblender.core_publish_project", "Publicar en la red…"),
                ("geoblender.core_show_lock", "Cerrojo del proyecto (quién lo tiene, liberar)…"),
            ],
        )
        self.assertFalse(bpy.ops.geoblender.core_checkout_project.poll())
        self.assertFalse(bpy.ops.geoblender.core_publish_project.poll())
        panel = ext("bl.ui.core_panel").GEOBLENDER_PT_core_project
        self.open_project()
        self.assertTrue(bpy.ops.geoblender.core_checkout_project.poll())
        self.assertFalse(bpy.ops.geoblender.core_publish_project.poll())
        targets = {item.target: item.text for item in draw(panel, bpy.context).of_kind("operator")}
        self.assertEqual(targets.get("geoblender.core_checkout_project"),
                         "Trabajar en copia local…")
        self.assertNotIn("geoblender.core_publish_project", targets)
        self.checkout()
        self.assertFalse(bpy.ops.geoblender.core_checkout_project.poll())
        self.assertTrue(bpy.ops.geoblender.core_publish_project.poll())
        layout = draw(panel, bpy.context)
        targets = {item.target: item.text for item in layout.of_kind("operator")}
        self.assertEqual(targets.get("geoblender.core_publish_project"), "Publicar en la red…")
        self.assertNotIn("geoblender.core_checkout_project", targets)
        self.assertIn("Modo: escritura en una copia local de trabajo", layout.texts())
        self.assertEqual(ext("core.i18n").missing_translations(), [])


class CheckoutPublishFlowTest(CheckoutOpsTestCase):
    def test_checkout_then_publish_and_open(self) -> None:
        """RF-002-31, RF-002-32: con el proyecto abierto, «Trabajar en copia local…» lo
        reserva y deja abierta la copia (en la carpeta de copias de las preferencias o de
        los datos de usuario si no se indica otra); «Publicar en la red…» lo sustituye por
        la copia, guarda el anterior como ``.anterior`` y abre el publicado en escritura."""
        self.open_project()
        operator = self.checkout(directory="")
        self.assertEqual(operator.outcome, "FINISHED")
        copy = self.ps.current()
        self.assertIs(copy.mode, self.core.OpenMode.CHECKOUT)
        self.assertTrue(copy.writable)
        default_dir = self.ps.userdata().checkouts_dir()
        self.addCleanup(shutil.rmtree, default_dir, ignore_errors=True)
        self.assertEqual(copy.root.parent, default_dir)
        self.assertIs(self.lock.read_holder(self.root).mode, self.lock.LockMode.CHECKOUT)
        self.assertEqual(bpy.context.scene.geoblender.project_uid, copy.uid)
        (copy.root / "exports" / "informe.txt").write_text("hecho en local", encoding="utf-8")
        operator = self.publish()
        self.assertEqual(operator.outcome, "FINISHED")
        published = self.ps.current()
        self.assertEqual(published.root, self.root)
        self.assertIs(published.mode, self.core.OpenMode.WRITE_LOCAL)
        self.assertTrue((self.root / "exports" / "informe.txt").is_file())
        self.assertEqual(sorted(p.name for p in self.parent.iterdir()), [ORIGINAL, PREVIOUS])
        self.assertTrue(copy.closed)
        self.assertIsNone(self.ps.userdata().checkout_record(copy.uid))
        self.assertTrue(any(PREVIOUS in text for text in operator.report_log), operator.report_log)

    def test_publish_refused_keeps_the_copy_open(self) -> None:
        """RF-002-33: si no se puede publicar (otra sesión forzó la reserva), el operador lo
        dice con el motivo y la copia sigue abierta en escritura, sin tocar el original."""
        self.open_project()
        self.checkout()
        copy = self.ps.current()
        other = ext("core.sysinfo").SessionInfo(
            "00000000-0000-4000-8000-0000000000c1", "PC-OTRO", "andres", os.getpid(), "0.1.0"
        )
        seen = self.lock.inspect(self.root, other)
        self.lock.force(self.root, other, self.lock.LockMode.LOCAL, seen.holder)
        before = (self.root / ".lock").read_bytes()
        operator = self.publish(open_published=False)
        self.assertEqual(operator.outcome, "CANCELLED")
        self.assertTrue(any("ya no está reservado" in text for text in operator.report_log))
        self.assertIs(self.ps.current(), copy)
        self.assertTrue(copy.writable)
        self.assertEqual((self.root / ".lock").read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.parent.iterdir()), [ORIGINAL])


class ProgressAndEscapeTest(CheckoutOpsTestCase):
    def test_checkout_200mb_progress_and_escape(self) -> None:
        """RNF-002-06, RF-002-31: sacar copia de un proyecto de 200 MB actualiza el
        progreso al menos cada segundo; Esc a mitad de la copia cancela en ≤ 2 s sin dejar
        copia ni reserva y vuelve a abrir el original; y la copia completa también da
        progreso cada segundo."""
        self.open_project(big=BIG)
        self.assertEqual(
            bpy.ops.geoblender.core_checkout_project("EXEC_DEFAULT", directory=str(self.copies)),
            {"RUNNING_MODAL"},
        )
        operator = self.running(self.ops.GEOBLENDER_OT_core_checkout_project)
        state, calls = self.drive(operator, until=self.copy_phase_half)
        self.assertEqual(state, {"RUNNING_MODAL"})
        self.assert_progress(operator, calls)
        self.escape(operator)
        self.assertEqual(list(self.copies.iterdir()), [])
        self.assertEqual(operator.outcome, "CANCELLED")
        self.finish_reopen()
        project = self.ps.current()
        self.assertEqual(project.root, self.root)
        self.assertTrue(project.writable)
        self.assertIs(self.lock.read_holder(self.root).mode, self.lock.LockMode.LOCAL)
        self.assertEqual(bpy.ops.geoblender.core_checkout_project(
            "EXEC_DEFAULT", directory=str(self.copies)), {"RUNNING_MODAL"})
        operator = self.running(self.ops.GEOBLENDER_OT_core_checkout_project)
        state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        self.assert_progress(operator, calls)
        self.assertIs(self.ps.current().mode, self.core.OpenMode.CHECKOUT)

    def test_publish_200mb_progress_and_escape(self) -> None:
        """RNF-002-06, RF-002-32: publicar una copia de 200 MB actualiza el progreso al
        menos cada segundo; Esc a mitad de la copia a ``.publicando`` cancela en ≤ 2 s sin
        sustituir nada (ni ``.publicando``, ni cambios en el original) y la copia sigue
        abierta; la publicación completa también da progreso cada segundo."""
        self.open_project(big=BIG)
        self.checkout()
        copy = self.ps.current()
        reservation = (self.root / ".lock").read_bytes()
        self.assertEqual(bpy.ops.geoblender.core_publish_project(
            "EXEC_DEFAULT", open_published=False), {"RUNNING_MODAL"})
        operator = self.running(self.ops.GEOBLENDER_OT_core_publish_project)
        state, calls = self.drive(operator, until=self.copy_phase_half)
        self.assertEqual(state, {"RUNNING_MODAL"})
        self.assert_progress(operator, calls)
        self.escape(operator)
        self.assertEqual(sorted(p.name for p in self.parent.iterdir()), [ORIGINAL])
        self.assertEqual((self.root / ".lock").read_bytes(), reservation)
        self.assertIs(self.ps.current(), copy)
        self.assertTrue(copy.writable)
        self.assertEqual(bpy.ops.geoblender.core_publish_project(
            "EXEC_DEFAULT", open_published=False), {"RUNNING_MODAL"})
        operator = self.running(self.ops.GEOBLENDER_OT_core_publish_project)
        state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        self.assert_progress(operator, calls)
        self.assertIsNone(self.ps.current())
        self.assertEqual(sorted(p.name for p in self.parent.iterdir()), [ORIGINAL, PREVIOUS])


if __name__ == "__main__":
    unittest.main()
