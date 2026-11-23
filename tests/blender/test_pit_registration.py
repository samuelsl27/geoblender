# SPDX-License-Identifier: GPL-3.0-or-later
"""El menú, el catálogo, el registro simétrico y las órdenes de entidades con la corta (spec 018, T35; HU-018-1; RF-018-34, RF-018-35, RF-015-28, RF-015-18; plan 018 §5.3.3, §5.5 y §2.1;
D-20; comprobación manual M6 y M7), **sin proyecto** (lo que hace «Calcular…» con una corta de verdad, con el proyecto, está en ``milestone_pit_ops.py``).

- RF-018-34, D-20 (a): las seis órdenes —«Nueva corta…», «Expandir banco…», «Rampa…», «Roseta de taludes…», «Línea de cielo…» y «Superficie y sólido…»— son clases reales y de la entrada 018,
  entregada, con la descripción del catálogo; las dos internas de las ventanas, de la 018 y sin casa; **ninguna** orden de ``des`` es ya de R-35.
- RF-018-34, D-20, M6 (b): Diseño ▸ Corta por bancos dibuja las seis, **en su orden y antes de las de R-49**, activas, sin la nota «Disponible en …»; **las cuatro provisionales de R-35 ya no
  están**: ni en el catálogo, ni en el registro, ni en ningún menú, ni como operador de ``bpy.ops``.
- RF-018-34, RF-015-28 (c): las seis se activan con el proyecto en escritura y la versión editable y se desactivan **con su motivo** si no.
- RF-015-28, RF-015-05 (d): el menú «Entidad ▾» dibuja las mismas órdenes, activas, y las siete que escriben se desactivan con su motivo.
- RF-015-18, RF-018-34 (e): «Calcular…» ofrece y calcula **una corta sin calcular**: abre «Nueva corta…» con su ``code``; un tipo que no se calcula así se rehúsa **sin nombrar una corta como
  posible**; las que rechaza el dominio se rechazan antes de abrir nada.
- RF-015-28, RF-018-32 (f): la vista previa de una corta es la de sus polilíneas (``EntityPlan(pit=…)``); lo que no tiene vista previa (una accesibilidad, una retirada) lo dice **nombrando
  también la corta** entre lo que sí la tiene.
- Textos (g): los textos nuevos están traducidos.
- RF-018-35, principio 8, M7 (z): desactivar Geoblender quita las órdenes y sus internas y las cuatro provisionales no vuelven; activar, desactivar y activar de nuevo deja el mismo registro.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw, operator_self

CREATE = "geoblender.des_create_pit"
EXPAND = "geoblender.des_expand_bench"
RAMP = "geoblender.des_edit_pit_ramp"
ROSE = "geoblender.des_edit_pit_rose"
SKYLINE = "geoblender.des_pit_skyline"
SURFACE = "geoblender.des_pit_surface"
SAVE_ROSE = "geoblender.des_save_pit_rose"
SAVE_RAMP = "geoblender.des_save_pit_ramp"
MENU_ORDERS = (CREATE, EXPAND, RAMP, ROSE, SKYLINE, SURFACE)
INTERNALS = (SAVE_ROSE, SAVE_RAMP)
LABELS = {CREATE: "Nueva corta…", EXPAND: "Expandir banco…", RAMP: "Rampa…", ROSE: "Roseta de taludes…", SKYLINE: "Línea de cielo…", SURFACE: "Superficie y sólido…"}
LABELS_EN = {CREATE: "New pit…", EXPAND: "Expand bench…", RAMP: "Ramp…", ROSE: "Slope rose…", SKYLINE: "Skyline…", SURFACE: "Surface and solid…"}
GONE = ("des_new_pit", "des_add_ramp", "des_compute_daylight", "des_create_design_surface")
"""Las cuatro provisionales de R-35 que sustituyen (D-20)."""
FROM_SHELL = ("geoblender.des_design_pit_from_shell", "geoblender.des_compare_with_shell")
DESIGN_MENU = "GEOBLENDER_MT_ui_design"
PIT_MENU = "GEOBLENDER_MT_des_pit"
ENTITY_CONTEXT = "GEOBLENDER_MT_des_context_entity"
ENTITY_ORDERS = ("geoblender.des_entity_dependents", "geoblender.des_entity_insert", "geoblender.des_entity_bring", "geoblender.des_entity_calculate", "geoblender.des_entity_discard",
                 "geoblender.des_entity_release_support", "geoblender.des_entity_preview")
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
READ_ONLY = "Proyecto en solo lectura: prueba"
NEW_TEXTS = ("«{name}» ({kind}) has no preview: only a platform, a detection of stockpiles (its marks), a buttress (its crown zone), a road (its axis) and a pit (its polylines) have one",
             "«{name}» ({kind}) is not calculated from here: it is made again with its own command; only a platform, a road or a pit are calculated with their saved parameters")
"""Los textos que cambia esta tarea (``msgid`` en inglés): su español está en ``messages.toml``."""


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class Rows:
    """Una colección de mentira (``CollectionProperty``)."""

    def __init__(self) -> None:
        self.items: list[Any] = []

    def clear(self) -> None:
        self.items.clear()

    def add(self) -> Any:
        row = SimpleNamespace(name="", label="", selected=True)
        self.items.append(row)
        return row

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Any:
        return iter(self.items)


class PitRegistrationTest(unittest.TestCase):
    """Con la extensión habilitada y sin proyecto: el catálogo, el menú, el ``poll`` y lo que no lee el proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.des_ops = _module("bl.ops.des")
        cls.commands = _module("bl.ui.commands")
        cls.registry = _module("bl.ui.registry")
        cls.i18n = _module("core.i18n")
        cls.entities = _module("design.entities")
        cls.catalog = cls.commands.catalog()

    def registered(self, idname: str) -> Any:
        return self.commands.registered_class(idname)

    # --- (a) Las órdenes ----------------------------------------------------------------------

    def test_a_the_six_orders_are_real_delivered_and_of_the_018(self) -> None:
        """RF-018-34, D-20 (M6): las seis órdenes del menú son clases reales de la entrada 018, entregada, con su rótulo y la descripción del catálogo; las dos internas, de la 018 y sin casa;
        **ninguna** orden de ``des`` es ya de R-35."""
        self.assertTrue(self.catalog.entries["018"].delivered)
        self.assertFalse(self.catalog.entries["R-35"].delivered)
        for idname in MENU_ORDERS:
            with self.subTest(orden=idname):
                cls = self.registered(idname)
                command = self.catalog.commands[idname]
                self.assertIsNotNone(cls)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertEqual((command.entry, command.module, command.kind, command.home, command.label, command.label_es),
                                 ("018", "des", "operator", PIT_MENU, LABELS_EN[idname], LABELS[idname]))
                self.assertEqual(cls.bl_label, LABELS[idname])
                self.assertTrue(cls.__doc__.strip())
                self.assertTrue(self.commands.is_available(idname), "entregada: sin la nota «Disponible en …»")
        for idname in INTERNALS:
            internal = self.catalog.commands[idname]
            self.assertEqual((internal.entry, internal.kind, internal.home), ("018", "internal", ""))
            self.assertIsNotNone(self.registered(idname))
        self.assertEqual(sorted(command.key for command in self.catalog.commands.values() if command.entry == "R-35"), [])

    def test_b_the_pit_menu_draws_the_six_and_the_four_provisionals_are_gone(self) -> None:
        """RF-018-34, D-20 (M6): Diseño ▸ Corta por bancos dibuja las seis órdenes **en su orden** y después las dos de R-49; las seis, **activas** y entregadas. Las cuatro provisionales ya no
        están: ni en ningún menú, ni como clase registrada, ni como operador de ``bpy.ops``."""
        shown = draw(getattr(bpy.types, PIT_MENU), bpy.context)
        group = [item for item in shown.items if item.kind in ("operator", "menu")]
        self.assertEqual([item.target for item in group], [*MENU_ORDERS, *FROM_SHELL])
        self.assertEqual([item.text for item in group[:6]], [LABELS[idname] for idname in MENU_ORDERS])
        self.assertTrue(all(item.enabled for item in group[:6]), "ninguna se dibuja desactivada ni con la nota «Disponible en …»")
        design = draw(getattr(bpy.types, DESIGN_MENU), bpy.context)
        self.assertIn(PIT_MENU, [item.target for item in design.items if item.kind == "menu"])
        labels = [item.text for item in design.items if item.kind in ("operator", "label", "menu")]
        self.assertFalse([text for text in labels if text.startswith("Disponible en") and "R-35" in text])
        menus = [cls for cls in self.registry.own_classes() if issubclass(cls, bpy.types.Menu)]
        drawn = {item.target for cls in menus for item in draw(cls, bpy.context).items if item.kind in ("operator", "menu")}
        for name in GONE:
            with self.subTest(orden=name):
                self.assertIsNone(self.registered(f"geoblender.{name}"))
                self.assertIsNone(getattr(bpy.types, f"GEOBLENDER_OT_{name}", None))
                self.assertNotIn(name, dir(bpy.ops.geoblender))
                self.assertNotIn(f"geoblender.{name}", drawn)
                self.assertNotIn(f"geoblender.{name}", self.catalog.commands)

    # --- (c) La activación --------------------------------------------------------------------

    def test_c_the_orders_are_active_with_a_writable_project_and_disabled_with_their_reason(self) -> None:
        """RF-018-34, RF-015-28 (M6): las seis órdenes se activan con el proyecto en escritura y la versión activa editable y se desactivan **con su motivo** con el proyecto en solo lectura o con
        la versión SUPERADO."""
        for idname in MENU_ORDERS:
            cls = self.registered(idname)
            self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware) or issubclass(cls, self.des_ops.DesignCommand), idname)
            for reason in (None, READ_ONLY, NOT_EDITABLE):
                with self.subTest(orden=idname, motivo=reason), mock.patch.object(self.des_ops, "design_unavailable", return_value=reason):
                    messages: list[str] = []
                    with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                        self.assertEqual(bool(cls.poll(bpy.context)), reason is None)
                    self.assertEqual(messages, [] if reason is None else [reason])

    # --- (d) «Entidad ▾» ----------------------------------------------------------------------

    def test_d_the_entity_menu_serves_the_pit_with_the_same_orders(self) -> None:
        """RF-015-28, RF-015-05 (M6): el menú «Entidad ▾» (también el de una corta) dibuja, activas y en su orden, las siete órdenes de entidades —sin «Disponible en …»— y no nombra ya la
        provisional de la superficie de diseño; las siete se desactivan con su motivo con el proyecto en solo lectura o la versión no editable."""
        shown = draw(getattr(bpy.types, ENTITY_CONTEXT), bpy.context)
        operators = {item.target: item.enabled for item in shown.items if item.kind == "operator"}
        for idname in ENTITY_ORDERS:
            self.assertTrue(operators[idname], idname)
        self.assertNotIn("geoblender.des_create_design_surface", operators)
        self.assertFalse([item.text for item in shown.items if item.text.startswith("Disponible en")])
        for idname in ENTITY_ORDERS:
            cls = self.registered(idname)
            for reason in (READ_ONLY, NOT_EDITABLE):
                with self.subTest(orden=idname, motivo=reason), mock.patch.object(self.des_ops, "design_unavailable", return_value=reason):
                    messages: list[str] = []
                    with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                        self.assertFalse(cls.poll(bpy.context))
                    self.assertEqual(messages, [reason])

    # --- (e) «Calcular…» ----------------------------------------------------------------------

    def _listed(self) -> list[Any]:
        kind, state = self.entities.EntityKind, self.entities.EntityState

        def entry(code: str, name: str, each: Any, status: Any) -> Any:
            return SimpleNamespace(record=SimpleNamespace(code=code, name=name, kind=each, state=status))

        return [entry("PLT-001", "Carga", kind.PLATFORM, state.CURRENT), entry("PIT-001", "Corta traída", kind.PIT, state.UNCALCULATED),
                entry("PIT-002", "Corta hecha", kind.PIT, state.CURRENT), entry("ACC-001", "Alcanzable", kind.ACCESS, state.UNCALCULATED)]

    def _registry(self) -> Any:
        listed = self._listed()

        class Registry(list):
            def get(self_, ref: str) -> Any:
                return next((entry for entry in listed if ref in (entry.record.code, entry.record.name)), None)

        return Registry(listed)

    def test_e_calculate_offers_and_opens_a_brought_pit(self) -> None:
        """RF-015-18, RF-018-34 (M6): la ventana de «Calcular…» ofrece **la corta sin calcular** (no la que ya tiene resultado ni la accesibilidad) y, al aceptar, abre «Nueva corta…» con su
        ``code``; antes de abrir, pide al dominio la petición (lo que rechazaría el cálculo); un tipo que no se calcula así se rehúsa diciendo que lo son la plataforma, la pista y la corta."""
        self.assertIn(self.entities.EntityKind.PIT, self.des_ops._calculable())
        cls = self.registered(self.des_ops.CALCULATE_ENTITY)
        active = SimpleNamespace(uid="uid-v02", code="V02")
        with mock.patch.object(self.entities, "registry", return_value=self._registry()), mock.patch.object(self.des_ops, "SESSION", SimpleNamespace(project=object())), \
                mock.patch.object(self.des_ops.scene_versions, "active_version", return_value="uid-v02"), mock.patch.object(self.des_ops.scene_versions, "active", return_value=active):
            window = SimpleNamespace(invoke_props_dialog=mock.Mock(return_value={"RUNNING_MODAL"}))
            fake = operator_self(cls, entity="", candidates=Rows(), report=mock.Mock(), _version_refusal=lambda: None, provenance_dialog=False)
            self.assertEqual(cls.invoke(fake, SimpleNamespace(window_manager=window), None), {"RUNNING_MODAL"})
            self.assertEqual([row.name for row in fake.candidates], ["Corta traída"])
            self.assertEqual(fake.entity, "Corta traída")
            with mock.patch.object(self.des_ops, "write_unavailable", return_value=None), mock.patch.object(self.des_ops, "_pit_entity_request") as asked, \
                    mock.patch.object(self.des_ops, "_invoke_later") as later:
                chosen = operator_self(cls, entity="PIT-001", report=mock.Mock(), _version_refusal=lambda: None)
                self.assertEqual(cls.execute(chosen, SimpleNamespace(window=object())), {"FINISHED"})
                asked.assert_called_once()
                self.assertEqual(asked.call_args.args[1:], ("uid-v02", "PIT-001"))
                later.assert_called_once()
                self.assertEqual((later.call_args.args[0], later.call_args.kwargs["code"]), (CREATE, "PIT-001"))
            with mock.patch.object(self.des_ops, "write_unavailable", return_value=None), mock.patch.object(self.des_ops, "_pit_entity_request", side_effect=ValueError("sin capa")), \
                    mock.patch.object(self.des_ops, "_invoke_later") as later:
                refused = operator_self(cls, entity="PIT-001", report=mock.Mock(), _version_refusal=lambda: None)
                self.assertEqual(cls.execute(refused, SimpleNamespace(window=object())), {"CANCELLED"})
                later.assert_not_called()
            with mock.patch.object(self.des_ops, "write_unavailable", return_value=None), mock.patch.object(self.des_ops, "_invoke_later") as later:
                other = operator_self(cls, entity="ACC-001", report=mock.Mock(), _version_refusal=lambda: None)
                self.assertEqual(cls.execute(other, SimpleNamespace(window=object())), {"CANCELLED"})
                later.assert_not_called()
                text = other.report.call_args.args[1]
                self.assertIn("una plataforma, una pista o una corta", text)

    # --- (f) La vista previa ------------------------------------------------------------------

    def test_f_the_preview_names_the_pit_among_the_ones_that_have_one(self) -> None:
        """RF-015-28, RF-018-32 (M6): la vista previa de una **corta** es la de sus polilíneas guardadas (``EntityPlan(pit=PitAsk(code=…))``); la de una accesibilidad o la de una retirada no existe y
        lo dice nombrando entre lo que sí la tiene **la corta**."""
        plan = self.des_ops.GEOBLENDER_OT_des_entity_preview._plan
        kind = self.entities.EntityKind

        def entry(each: Any, code: str, operation: str | None = "op") -> Any:
            return SimpleNamespace(record=SimpleNamespace(kind=each, code=code, name=f"N {code}"), operation_uid=operation)

        found = plan(None, None, entry(kind.PIT, "PIT-001", None))
        self.assertEqual((found.kind, found.pit.code), ("pit", "PIT-001"))
        for each in (kind.ACCESS, kind.REMOVAL):
            with self.subTest(tipo=each), self.assertRaises(ValueError) as caught:
                plan(None, None, entry(each, "X-001"))
            self.assertIn("no tiene vista previa", str(caught.exception))
            self.assertIn("una pista (su eje) y una corta (sus polilíneas)", str(caught.exception))

    # --- (g) Los textos -----------------------------------------------------------------------

    def test_g_the_new_texts_are_translated(self) -> None:
        """RF-018-34 (principio 10): los textos que cambia la tarea tienen su español, y cada orden del menú y cada interna, su rótulo y su descripción en los dos idiomas (el catálogo)."""
        self.assertEqual(self.i18n.untranslated(list(NEW_TEXTS)), [])
        for idname in (*MENU_ORDERS, *INTERNALS):
            command = self.catalog.commands[idname]
            self.assertTrue(command.label_es and command.description_es, idname)
            self.assertNotEqual((command.label, command.description), (command.label_es, command.description_es), idname)

    # --- (z) Registrar y desregistrar ---------------------------------------------------------

    def test_z_registering_and_unregistering_are_symmetric(self) -> None:
        """RF-018-35, principio 8, M7: activar, desactivar y activar de nuevo deja **el mismo registro** de las órdenes de la corta; al desactivar no queda ninguna clase, ni operador, ni las
        cuatro provisionales de R-35."""
        everything = (*MENU_ORDERS, *INTERNALS)
        for idname in everything:
            self.assertIsNotNone(self.registered(idname), idname)
        names = lambda: sorted(name for name in dir(bpy.ops.geoblender) if name.startswith(("des_create_pit", "des_expand_bench", "des_edit_pit", "des_pit_", "des_save_pit")))  # noqa: E731
        before = names()
        self.assertEqual(len(before), len(everything))
        blender_ext.release()
        for idname in (*everything, *(f"geoblender.{name}" for name in GONE)):
            self.assertIsNone(getattr(bpy.types, f"GEOBLENDER_OT_{idname.removeprefix('geoblender.')}", None), idname)
        self.assertIsNone(getattr(bpy.types, PIT_MENU, None))
        self.assertEqual(names(), [])
        blender_ext.enable()
        self.assertEqual(names(), before)
        for idname in everything:
            self.assertIsNotNone(getattr(bpy.types, f"GEOBLENDER_OT_{idname.removeprefix('geoblender.')}", None), idname)
        blender_ext.release()
        self.assertEqual(names(), [])


if __name__ == "__main__":
    unittest.main()
