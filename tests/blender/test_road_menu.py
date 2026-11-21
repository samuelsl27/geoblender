# SPDX-License-Identifier: GPL-3.0-or-later
"""El menú, el catálogo y la activación de las órdenes de pistas y rampas, y las órdenes de entidades con los tipos nuevos (spec 017, T33b; HU-017-1, HU-017-4; RF-017-29, RF-017-28, RF-015-28, RF-015-05; plan 017
§5.3.3, §5.5 y §5.6; D-20; comprobación manual M6), **sin proyecto** (lo que hacen las órdenes de entidades con una pista y una accesibilidad de verdad, con el proyecto, está en ``milestone_road_menu.py``).

- RF-017-29, D-20 (a): las cinco órdenes —«Pista…», «Proponer el trazado…», «Accesibilidad de las pistas…», «Perfil de pista…» y «Exportar pista…»— son reales y de la entrada 017, entregada, con la descripción
  del catálogo; ya no son «interinas de R-40».
- RF-017-29, D-20, M6 (b): Diseño ▸ Pistas y entidades dibuja, **en su orden y antes de «Entidades ▸»**, las cinco órdenes, activas, sin la nota «Disponible en …»; **las tres provisionales de R-40 ya no
  están**: ni en el catálogo, ni en el registro, ni en ningún menú.
- RF-017-29, RF-015-28 (c): las cuatro órdenes de versión se activan con el proyecto en escritura y la versión editable y se desactivan **con su motivo** si no (solo lectura, versión SUPERADO), y la descripción
  de la de una versión no editable dice por qué; «Exportar pista…» (no es una operación: H-9) sigue activa y se desactiva solo sin proyecto.
- RF-015-28, RF-015-05 (d): el menú «Entidad ▾» dibuja las mismas órdenes que antes, activas, para la pista; las siete que escriben se desactivan con su motivo; «Insertar antes o después de…» abre
  **«Plataforma…»** (no «Pista…»: la pista no admite ``insert_before``) y no ofrece una accesibilidad (sin cadena).
- RF-015-28, RF-015-18 (e): «Traer las entidades de…» **no ofrece ni trae una accesibilidad** (no es una entidad con cadena: se vuelve a calcular en la versión): ni en la ventana, ni tecleada, ni al traer todas;
  trae la pista y la plataforma.
- RF-015-28, RF-017-26 (f): la vista previa de una **pista** es la de su eje (``EntityPlan(road=…)``) y la de una accesibilidad no existe, y lo dice.
- Textos (g): los textos nuevos están traducidos.
- Principio 8 (z): desactivar Geoblender quita las cinco órdenes y la interna del perfil; las tres de R-40 siguen sin existir.

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

CREATE = "geoblender.des_create_road"
PROPOSE = "geoblender.des_propose_road"
ACCESS = "geoblender.des_road_access"
PROFILE = "geoblender.des_edit_road_profile"
SAVE_PROFILE = "geoblender.des_save_road_profile"
EXPORT = "geoblender.des_export_road"
VERSION_ORDERS = (CREATE, PROPOSE, ACCESS, PROFILE)
"""Las cuatro de la versión: la puerta de Diseño (``DesignCommand``); «Exportar pista…» tiene la suya."""
MENU_ORDERS = (CREATE, PROPOSE, ACCESS, PROFILE, EXPORT)
LABELS = {CREATE: "Pista…", PROPOSE: "Proponer el trazado…", ACCESS: "Accesibilidad de las pistas…", PROFILE: "Perfil de pista…", EXPORT: "Exportar pista…", SAVE_PROFILE: "Guardar perfil de pista…"}
LABELS_EN = {CREATE: "Road…", PROPOSE: "Propose the route…", ACCESS: "Accessibility of the roads…", PROFILE: "Road profile…", EXPORT: "Export road…"}
GONE = ("des_draw_haul_road", "des_route_haul_road", "des_burn_roads")
"""Las tres provisionales de R-40 que sustituyen (D-20)."""
DESIGN_MENU = "GEOBLENDER_MT_ui_design"
ENTITIES_MENU = "GEOBLENDER_MT_des_entities"
ENTITY_CONTEXT = "GEOBLENDER_MT_des_context_entity"
ENTITY_ORDERS = ("geoblender.des_entity_dependents", "geoblender.des_entity_insert", "geoblender.des_entity_bring", "geoblender.des_entity_calculate", "geoblender.des_entity_discard",
                 "geoblender.des_entity_release_support", "geoblender.des_entity_preview")
"""Las órdenes del menú «Entidad ▾» que dependen de una versión editable (RF-015-28)."""
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
READ_ONLY = "Proyecto en solo lectura: prueba"
NEW_TEXTS = ("«{name}» is an accessibility, not an entity with a chain: it is not brought to another version; calculate it again in the active version",)
"""Los textos que añade esta tarea (``msgid`` en inglés): su español está en ``messages.toml``."""


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class Rows:
    """Una colección de mentira (``CollectionProperty``): lo que usa el diálogo de traer."""

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


class RoadMenuTest(unittest.TestCase):
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

    def test_a_the_five_orders_are_real_delivered_and_of_the_017(self) -> None:
        """RF-017-29, D-20, RF-015-28 (M6): las cinco órdenes del menú son clases reales (no provisionales) de la entrada 017, entregada, con su rótulo en español y la descripción del catálogo (su
        ``__doc__``); ya no son «interinas de R-40»: son órdenes con su casa en Diseño; la interna de la ventana del perfil, de la 017 y sin casa; **ninguna** orden de ``des`` es ya de R-40."""
        self.assertTrue(self.catalog.entries["017"].delivered)
        self.assertFalse(self.catalog.entries["R-40"].delivered)
        for idname in MENU_ORDERS:
            with self.subTest(orden=idname):
                cls = self.registered(idname)
                command = self.catalog.commands[idname]
                self.assertIsNotNone(cls)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertEqual((command.entry, command.module, command.kind, command.home, command.label, command.label_es),
                                 ("017", "des", "operator", DESIGN_MENU, LABELS_EN[idname], LABELS[idname]))
                self.assertEqual(cls.bl_label, LABELS[idname])
                self.assertEqual(cls.__doc__.strip(), command.description)
                self.assertTrue(self.commands.is_available(idname), "entregada: sin la nota «Disponible en …»")
        internal = self.catalog.commands[SAVE_PROFILE]
        self.assertEqual((internal.entry, internal.kind, internal.home), ("017", "internal", ""))
        self.assertEqual(sorted(command.key for command in self.catalog.commands.values() if command.entry == "R-40"), [])
        for idname in VERSION_ORDERS:
            self.assertTrue(issubclass(self.registered(idname), self.des_ops.DesignCommandAware), idname)

    def test_b_the_design_menu_draws_the_five_first_and_the_three_provisionals_are_gone(self) -> None:
        """RF-017-29, D-20, RF-017-28 (M6): Diseño ▸ Pistas y entidades dibuja «Pista…», «Proponer el trazado…» y «Accesibilidad de las pistas…» **como los tres primeros puestos del grupo**, después
        «Perfil de pista…» y «Exportar pista…» y, al final, «Entidades ▸»; todas **activas** y entregadas (sin la nota «Disponible en …»). **«Pista (eje, rasante y sección de la ITC)», «Ruta 3D con pendiente
        máxima…» y «Grabar las pistas en la superficie» ya no están**: ni en ningún menú, ni como clase registrada, ni como operador de ``bpy.ops``."""
        shown = draw(getattr(bpy.types, DESIGN_MENU), bpy.context)
        start = next(index for index, item in enumerate(shown.items) if item.kind == "label" and item.text == "Pistas y entidades")
        end = next(index for index, item in enumerate(shown.items) if index > start and item.kind == "label" and item.text == "Comprobar")
        group = [item for item in shown.items[start + 1:end] if item.kind in ("operator", "menu")]
        self.assertEqual([item.target for item in group], [*MENU_ORDERS, ENTITIES_MENU])
        self.assertEqual([item.text for item in group[:5]], [LABELS[idname] for idname in MENU_ORDERS])
        self.assertTrue(all(item.enabled for item in group), "ninguna se dibuja desactivada ni con la nota «Disponible en …»")
        labels = [item.text for item in shown.items if item.kind in ("operator", "label", "menu")]
        self.assertFalse([text for text in labels if text.startswith("Disponible en")])
        for text in ("Pista (eje, rasante y sección de la ITC)", "Pista", "Ruta 3D con pendiente máxima…", "Grabar las pistas en la superficie"):
            self.assertNotIn(text, labels)
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
        """RF-017-29, RF-015-28 (M6): «Pista…», «Proponer el trazado…», «Accesibilidad de las pistas…» y «Perfil de pista…» se activan con el proyecto en escritura y la versión activa editable y se
        desactivan **con su motivo** con el proyecto en solo lectura o con la versión SUPERADO; la descripción de la de una versión no editable dice por qué. «Exportar pista…» (no es una operación: H-9)
        **no mira la versión**: sigue activa con el proyecto en solo lectura y con la versión superada, y se desactiva con su motivo solo sin proyecto."""
        for idname in VERSION_ORDERS:
            cls = self.registered(idname)
            for reason in (None, READ_ONLY, NOT_EDITABLE):
                with self.subTest(orden=idname, motivo=reason), mock.patch.object(self.des_ops, "design_unavailable", return_value=reason):
                    messages: list[str] = []
                    with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                        self.assertEqual(bool(cls.poll(bpy.context)), reason is None)
                    self.assertEqual(messages, [] if reason is None else [reason])
        with mock.patch.object(self.des_ops.scene_versions, "not_editable_text", return_value=NOT_EDITABLE):
            for idname in (CREATE, PROPOSE, ACCESS):
                self.assertIn(NOT_EDITABLE, self.registered(idname).description(bpy.context, SimpleNamespace()), idname)
        export = self.registered(EXPORT)
        self.assertIn("poll", vars(export), "la de exportar tiene su propio ``poll``")
        for reason, wanted in ((None, True), ("Abra un proyecto", False)):
            with self.subTest(exportar=reason), mock.patch.object(self.des_ops.SESSION, "unavailable", return_value=reason), \
                    mock.patch.object(self.des_ops, "design_unavailable", return_value=READ_ONLY):  # aunque Diseño diga «solo lectura»
                messages = []
                with mock.patch.object(export, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                    self.assertEqual(bool(export.poll(bpy.context)), wanted)
                self.assertEqual(messages, [] if reason is None else [reason])

    # --- (d) «Entidad ▾» ----------------------------------------------------------------------

    def test_d_the_entity_menu_serves_the_road_with_the_same_orders(self) -> None:
        """RF-015-28, RF-015-05 (M6): el menú «Entidad ▾» (``DESIGN_ENTITY``: también el de una pista) dibuja, activas y en su orden, las siete órdenes de entidades de la 015 y la 016 —sin
        «Disponible en …»—; las siete se desactivan con su motivo con el proyecto en solo lectura o la versión no editable (el ``poll`` de ``DesignCommand``, el mismo para cualquier tipo de entidad) y
        «Insertar antes o después de…» abre **«Plataforma…»** (``des_create_platform``): la pista no admite ``insert_before`` (hallazgo H2-4) y no hay una orden de insertar una pista."""
        shown = draw(getattr(bpy.types, ENTITY_CONTEXT), bpy.context)
        operators = {item.target: item.enabled for item in shown.items if item.kind == "operator"}
        for idname in ENTITY_ORDERS:
            self.assertTrue(operators[idname], idname)
        self.assertFalse([item.text for item in shown.items if item.text.startswith("Disponible en")])
        for idname in ENTITY_ORDERS:
            cls = self.registered(idname)
            self.assertTrue(issubclass(cls, self.des_ops.DesignCommand), idname)
            for reason in (READ_ONLY, NOT_EDITABLE):
                with self.subTest(orden=idname, motivo=reason), mock.patch.object(self.des_ops, "design_unavailable", return_value=reason):
                    messages: list[str] = []
                    with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
                        self.assertFalse(cls.poll(bpy.context))
                    self.assertEqual(messages, [reason])
        self.assertEqual(self.des_ops.CREATE_PLATFORM, "geoblender.des_create_platform")
        self.assertNotIn("insert_before", self.registered(CREATE).__annotations__, "«Pista…» no admite insert_before")
        self.assertIn("insert_before", self.registered(self.des_ops.CREATE_PLATFORM).__annotations__)
        records = [self.entities.EntityRecord("PLT-001", "Carga", self.entities.EntityKind.PLATFORM, "terreno", None),
                   self.entities.EntityRecord("RDW-001", "Pista", self.entities.EntityKind.ROAD, "entity:PLT-001", None),
                   self.entities.EntityRecord("ACC-001", "Alcanzable", self.entities.EntityKind.ACCESS, None, None)]
        insert = self.registered(self.des_ops.INSERT_ENTITY)
        for ref, placement, start in (("RDW-001", "AFTER", "entity:RDW-001"), ("PLT-001", "AFTER", "entity:PLT-001")):
            fake = operator_self(insert, reference=ref, placement=placement, report=mock.Mock(), _version_refusal=lambda: None)
            with self.subTest(ref=ref), mock.patch.object(self.des_ops, "write_unavailable", return_value=None), \
                    mock.patch.object(self.des_ops, "SESSION", SimpleNamespace(project=object())), \
                    mock.patch.object(self.entities, "registry", return_value=SimpleNamespace(records=tuple(records))), \
                    mock.patch.object(self.des_ops.des_panels, "refresh_choices"), mock.patch.object(self.des_ops.des_panels, "refresh_platform_choices"), \
                    mock.patch.object(self.des_ops.des_panels, "platform_start_items", return_value=[(start, "x", "")]), \
                    mock.patch.object(self.des_ops, "_invoke_later") as later:
                self.assertEqual(insert.execute(fake, SimpleNamespace(window=object())), {"FINISHED"})
            later.assert_called_once()
            self.assertEqual(later.call_args.args[0], "geoblender.des_create_platform")
            self.assertEqual(later.call_args.kwargs["start"], start)
        refused = operator_self(insert, reference="ACC-001", placement="AFTER", report=mock.Mock(), _version_refusal=lambda: None)
        with mock.patch.object(self.des_ops, "write_unavailable", return_value=None), mock.patch.object(self.des_ops, "SESSION", SimpleNamespace(project=object())), \
                mock.patch.object(self.entities, "registry", return_value=SimpleNamespace(records=tuple(records))), mock.patch.object(self.des_ops, "_invoke_later") as later:
            self.assertEqual(insert.execute(refused, SimpleNamespace(window=object())), {"CANCELLED"}, "una accesibilidad no tiene cadena: no se inserta junto a ella")
        later.assert_not_called()
        self.assertIn("sin cadena", refused.report.call_args.args[1])

    # --- (e) «Traer» y la accesibilidad -------------------------------------------------------

    @staticmethod
    def _entry(code: str, name: str, kind: Any, state: Any = None) -> Any:
        return SimpleNamespace(record=SimpleNamespace(code=code, name=name, kind=kind, state=state or "current"))

    def _listed(self) -> list[Any]:
        kind, state = self.entities.EntityKind, self.entities.EntityState
        return [self._entry("PLT-001", "Carga", kind.PLATFORM), self._entry("RDW-001", "Pista", kind.ROAD), self._entry("ACC-001", "Alcanzable", kind.ACCESS),
                self._entry("RDW-002", "Ramal vieja", kind.ROAD, state.DISCARDED), self._entry("STK-001", "Acopios", kind.STOCKPILE)]

    def _registry(self) -> Any:
        listed = self._listed()

        class Registry(list):
            def get(self_, ref: str) -> Any:
                return next((entry for entry in listed if ref in (entry.record.code, entry.record.name)), None)

        return Registry(listed)

    def test_e_bring_does_not_offer_nor_bring_an_accessibility(self) -> None:
        """RF-015-18, RF-015-28 (M6; decisión tras la T31b): la ventana de «Traer las entidades de…» lista las entidades vivas **menos las descartadas y menos la accesibilidad** (no es una entidad con
        cadena: en otra versión se vuelve a calcular); lo que se trae son siempre **códigos explícitos** (nunca «todas», que incluiría la accesibilidad): las marcadas en la ventana, las tecleadas o, sin
        ventana ni nada tecleado, todas las vivas **menos la accesibilidad**; teclear su código se rechaza con su porqué y no se trae nada."""
        cls = self.registered(self.des_ops.BRING_ENTITIES)
        with mock.patch.object(self.entities, "registry", return_value=self._registry()), mock.patch.object(self.des_ops, "SESSION", SimpleNamespace(project=object())):
            fake = operator_self(cls, source="V01", entities="", rows=Rows())
            self.des_ops._bring_entities_of(fake, None)
            self.assertEqual([(row.name, row.label, row.selected) for row in fake.rows],
                             [("PLT-001", "Carga (PLT-001)", True), ("RDW-001", "Pista (RDW-001)", True), ("STK-001", "Acopios (STK-001)", True)])
            self.assertEqual(cls._wanted(fake), ["PLT-001", "RDW-001", "STK-001"], "todas las de la ventana, por su código y no «todas»")
            fake.rows.items[1].selected = False
            self.assertEqual(cls._wanted(fake), ["PLT-001", "STK-001"])
            for row in fake.rows:
                row.selected = False
            with self.assertRaises(ValueError):
                cls._wanted(fake)
            scripted = operator_self(cls, source="V01", entities="", rows=Rows())  # sin ventana ni nada tecleado: todas las vivas, sin la accesibilidad
            self.assertEqual(cls._wanted(scripted), ["PLT-001", "RDW-001", "STK-001"])
            typed = operator_self(cls, source="V01", entities="RDW-001, Carga", rows=Rows())
            self.assertEqual(cls._wanted(typed), ["RDW-001", "Carga"])
            for ref in ("ACC-001", "Alcanzable"):
                asked = operator_self(cls, source="V01", entities=f"PLT-001, {ref}", rows=Rows())
                with self.subTest(ref=ref), self.assertRaises(ValueError) as caught:
                    cls._wanted(asked)
                self.assertIn("accesibilidad", str(caught.exception))
                self.assertIn("se vuelve a calcular", str(caught.exception))
                self.assertIn("Alcanzable", str(caught.exception))
        with mock.patch.object(self.entities, "registry", side_effect=ValueError("sin versión")), mock.patch.object(self.des_ops, "SESSION", SimpleNamespace(project=object())):
            typed = operator_self(cls, source="V99", entities="RDW-001", rows=Rows())
            self.assertEqual(cls._wanted(typed), ["RDW-001"], "lo que no se puede leer lo rechaza el dominio con sus palabras, no aquí")

    # --- (f) La vista previa ------------------------------------------------------------------

    def test_f_the_preview_of_a_road_is_its_axis_and_an_accessibility_has_none(self) -> None:
        """RF-015-28, RF-017-26 (M6): la vista previa de una **pista** de la versión es la de su eje guardado (``EntityPlan(road=RoadAsk(code=…))``, sin calcular nada); la de una **accesibilidad** no
        existe y lo dice —nombrándola y dando su tipo— antes de dejar «no está calculada»; la de una plataforma, la de siempre."""
        plan = self.des_ops.GEOBLENDER_OT_des_entity_preview._plan
        kind = self.entities.EntityKind

        def entry(each: Any, code: str, operation: str | None = "op") -> Any:
            return SimpleNamespace(record=SimpleNamespace(kind=each, code=code, name=f"N {code}"), operation_uid=operation)

        found = plan(None, None, entry(kind.ROAD, "RDW-001", None))
        self.assertEqual((found.kind, found.road.code), ("road", "RDW-001"))
        found = plan(None, None, entry(kind.PLATFORM, "PLT-001"))
        self.assertEqual((found.kind, found.code), ("entity", "PLT-001"))
        for operation in ("op", None):
            with self.subTest(operación=operation), self.assertRaises(ValueError) as caught:
                plan(None, None, entry(kind.ACCESS, "ACC-001", operation))
            self.assertIn("«N ACC-001»", str(caught.exception))
            self.assertIn("no tiene vista previa", str(caught.exception))
            self.assertIn("una pista (su eje)", str(caught.exception))

    # --- (g) Los textos -----------------------------------------------------------------------

    def test_g_the_new_texts_are_translated(self) -> None:
        """RF-017-29 (principio 10): los textos que añade la tarea tienen su español en ``messages.toml``, y cada orden del menú, su rótulo y su descripción en los dos idiomas (el catálogo)."""
        self.assertEqual(self.i18n.untranslated(list(NEW_TEXTS)), [])
        for idname in (*MENU_ORDERS, SAVE_PROFILE):
            command = self.catalog.commands[idname]
            self.assertTrue(command.label_es and command.description_es, idname)
            self.assertNotEqual((command.label, command.description), (command.label_es, command.description_es), idname)

    # --- (z) Desregistrar ---------------------------------------------------------------------

    def test_z_disabling_geoblender_removes_the_orders_and_leaves_none_of_r40(self) -> None:
        """Principio 8: desactivar Geoblender quita las cinco órdenes del menú, la interna del perfil y el menú de Diseño; **las tres provisionales de R-40 no vuelven** a ningún registro."""
        for idname in (*MENU_ORDERS, SAVE_PROFILE):
            self.assertIsNotNone(self.registered(idname), idname)
        blender_ext.release()
        for idname in (*MENU_ORDERS, SAVE_PROFILE, *(f"geoblender.{name}" for name in GONE)):
            self.assertIsNone(getattr(bpy.types, f"GEOBLENDER_OT_{idname.removeprefix('geoblender.')}", None), idname)
        self.assertIsNone(getattr(bpy.types, DESIGN_MENU, None))
        names = dir(bpy.ops.geoblender)
        self.assertFalse([name for name in names if name.startswith(("des_create_road", "des_propose_road", "des_road_access", "des_export_road", "des_edit_road_profile",
                                                                     "des_save_road_profile", *GONE))])


if __name__ == "__main__":
    unittest.main()
