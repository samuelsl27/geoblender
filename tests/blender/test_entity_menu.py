# SPDX-License-Identifier: GPL-3.0-or-later
"""El menú «Entidad ▾» y «Insertar antes o después de…» en Blender (spec 015, T31; HU-015-2, HU-015-3; RF-015-28,
RF-015-05, RF-015-04, RF-015-17, RF-015-18, RF-015-26; D-14; plan 015 §5.3.3 y §5.5; comprobación manual M5).

- **El menú** (``GEOBLENDER_MT_des_context_entity``, ``contexts.toml``): con las órdenes reales en lugar de los
  marcadores —«Lo que se apoya en ella» (``des_entity_dependents``, nueva), «Insertar antes o después de…»
  (``des_entity_insert``, nueva), «Traer las entidades de…», «Descartar…», «Soltar el apoyo…», «Vista previa» y
  «Exportar la superficie» (la orden de exportar de la T30)—; «Plataforma…» y las internas pasan a la entrada
  ``015``, entregada; lo de la 016 (Acopio…, Contrafuerte…) sigue marcado en R-36 hasta ella.
- **La activación** (RF-015-28): cada orden, con el proyecto en escritura y la versión activa editable, activa; con el
  proyecto en solo lectura o la versión SUPERADO, desactivada con su motivo. Excepción documentada: «Exportar la
  superficie» es la orden de exportar de la 013 (RF-013-34, D-29 de la 011: no es una operación), que vale también en
  solo lectura y desde una versión superada.
- **Lo que se apoya en ella**: una ventana con **la lista única** (``entities.dependents``: nombre, tipo y m³) y, aparte,
  en qué se apoya (``entities.dependencies_of``), sin escribir nada.
- **Insertar antes o después de…**: elige la entidad de referencia (por defecto, la seleccionada en la vista) y antes o
  después, dice lo que pasará y abre la creación de la plataforma con esa partida y la entidad que pasará a partir de
  ella (``insert_before``); al crear, la sucesora pasa a partir de la nueva (el parámetro ``start``, con su motivo) y ella
  y las que la siguen quedan obsoletas con su causa; sin ``insert_before``, dos entidades desde la misma superficie se
  rechazan (RF-015-04).

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02) con dos capas más de líneas:
«Sobre Carga» (el eje y el ancho de «Carga», a 112 m) y «Entre» (a 108 m, entre «Carga» y «Taller»). P1 es «Carga» (del
terreno), P2 «Taller» (de la superficie de P1), P3 «Rampa» (de la de P2) y P4 «Sobre Carga» (de otro terreno, «en
corte y relleno»: rellena sobre P1, así que se apoya en ella sin partir de su superficie). Las pruebas, en el orden de
sus letras sobre el mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext
from tests.support.fake_layout import draw, operator_self

DEPENDENTS = "geoblender.des_entity_dependents"
INSERT = "geoblender.des_entity_insert"
DEPENDENTS_CLASS = "GEOBLENDER_OT_des_entity_dependents"
INSERT_CLASS = "GEOBLENDER_OT_des_entity_insert"
PLATFORM = platform_ops.PLATFORM
DISCARD = "geoblender.des_entity_discard"
RELEASE = "geoblender.des_entity_release_support"
BRING = "geoblender.des_entity_bring"
PREVIEW = "geoblender.des_entity_preview"
EXPORT = "geoblender.des_export_design_grid"
MENU = "GEOBLENDER_MT_des_context_entity"
ENTRY = "015"
OVER, BETWEEN, RAMP = "Sobre Carga", "Entre", platform_ops.RAMP
LOADING, WORKSHOP = platform_ops.LOADING, platform_ops.WORKSHOP
EXTRA = ((OVER, ((20.0, 30.0), (40.0, 30.0)), 8.0, 112.0, 0.0),
         (BETWEEN, ((20.0, 38.0), (40.0, 38.0)), 4.0, 108.0, 0.0))
DESCRIPTIONS = {
    DEPENDENTS: "Show the single list of what rests on the entity or starts from its surface, with the volume that "
                "rests on it, and what the entity rests on",
    INSERT: "Insert a new platform before or after another entity of its chain: the one that follows starts from the "
            "new one and is left out of date with what follows it",
}
PROPERTIES = {
    DEPENDENTS: {
        "entity": ("Entity", "Code or name of the design entity (empty: the one of the object selected in the 3D "
                             "view)"),
    },
    INSERT: {
        "reference": ("Entity", "Name or code of the entity the new platform is inserted next to (empty: the one of "
                                "the object selected in the 3D view)"),
        "placement": ("Position", "Insert the new platform after or before that entity"),
    },
}
"""Las propiedades de cada orden con el ``msgid`` de su nombre y de su descripción (las colecciones de filas, que llena el
diálogo, no los llevan)."""
HIDDEN = ("references",)
WRITING = (DEPENDENTS, INSERT, BRING, DISCARD, RELEASE, PREVIEW)
"""Las órdenes del menú que se desactivan con el proyecto en solo lectura o la versión no editable (RF-015-28)."""
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"


class Rows:
    """Una colección de mentira (``CollectionProperty``): lo que usa el diálogo."""

    def __init__(self, *items: Any) -> None:
        self.items = list(items)

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


class EntityMenuTest(platform_ops.CreatePlatformTest):
    """Lo de ``CreatePlatformTest`` (el proyecto y sus ayudantes; sus pruebas no se repiten) con dos capas más y otro
    terreno."""

    ground2: str

    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, *EXTRA)):
            super().setUpClass()
        cls.ground2 = cls.write_grid("Ladera 2", platform_ops.ground())
        cls.refresh()

    # --- Ayudas -------------------------------------------------------------------------------

    def command(self, idname: str) -> Any:
        return self.commands.registered_class(idname)

    def made(self, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa."""
        self.refresh()
        self.calculate(**values)
        self.assertEqual(self.create(), {"FINISHED"})

    def states(self) -> dict[str, str]:
        registry = self.entities.registry(self.project, self.v01.uid)
        return {entry.record.code: str(entry.record.state) for entry in registry}

    def starts(self) -> dict[str, str | None]:
        return {item.code: item.start for item in self.entities.registry(self.project, self.v01.uid).records}

    def fake(self, idname: str, **values: Any) -> tuple[Any, Any, mock.Mock, list[tuple[Any, str]]]:
        """El operador de mentira, el contexto con que se abre el diálogo (sin ventana propia) y su ventana
        emergente o su diálogo, y lo que se informó."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog, invoke_popup=dialog))
        said: list[tuple[Any, str]] = []
        fields: dict[str, Any] = {
            "entity": "", "reference": "", "placement": "AFTER", "references": Rows(), "provenance_dialog": False,
            "in_steps": False, "report": lambda kind, text: said.append((kind, text)), **values}
        return operator_self(self.command(idname), **fields), context, dialog, said

    def selected(self, code: str) -> Any:
        """Con el objeto de la entidad ``code`` seleccionado en la vista (``_selected_entity``)."""
        return mock.patch.object(self.des_ops, "_selected_entity",
                                 return_value=(code, self.v01.uid if code else ""))

    def poll(self, idname: str) -> tuple[bool, list[str]]:
        """El ``poll`` de la orden y lo que dice (``poll_message_set``)."""
        cls = self.command(idname)
        messages: list[str] = []
        with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)),
                               create=True):
            return bool(cls.poll(bpy.context)), messages

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_two_new_commands_are_real_internal_commands_of_the_delivered_entry(self) -> None:
        """RF-015-28, RF-015-05 (plan §5.3.3): «Lo que se apoya en ella» e «Insertar antes o después de…» son órdenes
        reales de ``des``, internas, de la entrada 015 (entregada); con la puerta de la procedencia, el ``poll`` común
        de Diseño y propiedades con nombre y descripción (registradas ya en español); su descripción es la del catálogo;
        la desactivación y el registro simétrico los miran ``test_i`` y la prueba de registro."""
        catalog = self.commands.catalog()
        for idname, class_name, label, label_es in ((DEPENDENTS, DEPENDENTS_CLASS, "What rests on it",
                                                     "Lo que se apoya en ella"),
                                                    (INSERT, INSERT_CLASS, "Insert before or after…",
                                                     "Insertar antes o después de…")):
            with self.subTest(orden=idname):
                cls = self.command(idname)
                self.assertIsNotNone(cls)
                self.assertEqual(cls.__name__, class_name)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertIn(cls, self.des_ops.classes)
                self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
                self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
                self.assertEqual((cls.bl_idname, cls.bl_label, cls.bl_options),
                                 (idname, label_es, {"REGISTER"}))  # registrada ya en español
                command = catalog.commands[idname]
                self.assertEqual((command.kind, command.entry, command.module, command.label, command.label_es),
                                 ("internal", ENTRY, "des", label, label_es))
                self.assertEqual(command.description, DESCRIPTIONS[idname])
                self.assertEqual(cls.__doc__.strip(), DESCRIPTIONS[idname])
                self.assertNotIn(idname, {name for defn in self.dprov.ENTITY_OPERATION_TYPES for name in defn.commands})
                annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
                self.assertEqual(annotated, set(PROPERTIES[idname]))
                for prop, (name, about) in PROPERTIES[idname].items():
                    keywords = cls.__annotations__[prop].keywords
                    self.assertEqual((keywords["name"], keywords["description"]),
                                     (self.i18n.translate("es", name), self.i18n.translate("es", about)))
                    self.assertEqual(self.i18n.untranslated([name, about]), [])
                self.assertTrue(cls.poll(bpy.context))
        props = platform_ops._module("bl.props.des")
        self.assertTrue(props.GEOBLENDER_PG_des_bring_row.is_registered)

    def test_b_the_platform_and_the_internals_are_delivered_and_what_is_of_the_016_is_not(self) -> None:
        """RF-015-28 (D-14): «Plataforma…» (con la elipsis de lo que abre un diálogo) y las internas de la 015 son de la
        entrada 015, entregada, y están disponibles; las de la 016 (Acopio…, Contrafuerte…) siguen en R-36, sin entregar,
        y no están disponibles."""
        catalog = self.commands.catalog()
        entry = catalog.entries[ENTRY]
        self.assertEqual((entry.title, entry.title_es, entry.delivered),
                         ("Parametric design entities", "Entidades de diseño paramétricas", True))
        self.assertFalse(catalog.entries["R-36"].delivered)
        platform = catalog.commands[PLATFORM]
        self.assertEqual((platform.entry, platform.module, platform.label, platform.label_es),
                         (ENTRY, "des", "Platform…", "Plataforma…"))
        for idname in (PLATFORM, DEPENDENTS, INSERT, BRING, DISCARD, RELEASE, PREVIEW):
            with self.subTest(orden=idname):
                self.assertEqual(catalog.commands[idname].entry, ENTRY)
                self.assertTrue(self.commands.is_available(idname))
        for idname in ("geoblender.des_edit_stockpile", "geoblender.des_add_buttress"):
            with self.subTest(orden=idname):
                self.assertEqual(catalog.commands[idname].entry, "R-36")
                self.assertFalse(self.commands.is_available(idname))
        self.assertTrue(self.commands.is_available(MENU), "el menú «Entidad ▾» es de la entrada 015")

    def test_c_the_entity_menu_has_the_real_commands_and_what_is_not_there_yet_is_marked(self) -> None:
        """RF-015-28 (D-14; plan §5.5): el menú «Entidad ▾» dibuja, en su orden, las órdenes reales —sus ítems activos— y,
        marcado y desactivado, lo que aún no es una orden (editar el eje, las restricciones que declara) y lo de la
        016 (Acopio…, con su «Disponible en R-36»); sin la nota de menú no disponible."""
        menu = getattr(bpy.types, MENU)
        shown = draw(menu, bpy.context)
        operators = [(item.target, item.enabled) for item in shown.items if item.kind == "operator"]
        self.assertEqual([target for target, _enabled in operators], [
            "geoblender.ui_show_context_panel", "geoblender.core_recompute_stale", DEPENDENTS,
            "geoblender.core_show_lineage", INSERT, BRING, DISCARD, RELEASE, PREVIEW, EXPORT,
            "geoblender.des_edit_stockpile"])
        enabled = dict(operators)
        for idname in (DEPENDENTS, INSERT, BRING, DISCARD, RELEASE, PREVIEW, EXPORT):
            self.assertTrue(enabled[idname], idname)
        self.assertFalse(enabled["geoblender.des_edit_stockpile"])
        labels = [item.text for item in shown.items if item.kind in ("operator", "label")]
        self.assertIn("Lo que se apoya en ella", labels)
        self.assertIn("Insertar antes o después de…", labels)
        self.assertIn("Traer las entidades de…", labels)
        self.assertIn("Descartar…", labels)
        self.assertIn("Soltar el apoyo…", labels)
        self.assertIn("Editar el eje o el contorno", labels)
        self.assertIn("Restricciones que declara…", labels)
        self.assertFalse([text for text in labels if text.startswith("Disponible en")], "el menú está entregado")
        placeholders = [item for item in shown.items if item.kind == "label" and item.text in (
            "Editar el eje o el contorno", "Restricciones que declara…")]
        self.assertEqual([item.enabled for item in placeholders], [False, False])

    def test_d_a_chain_of_three_platforms_and_one_that_rests_on_the_first_are_made(self) -> None:
        """RF-015-15, RF-015-04 (el mundo de estas pruebas): P1 «Carga», P2 «Taller» (de la superficie de P1), P3 «Rampa»
        (de la de P2) y P4 «Sobre Carga» (de otro terreno, en corte y relleno sobre la huella de P1), todas al día."""
        self.made()
        self.made(name=WORKSHOP, feature=WORKSHOP, start="entity:PLT-001", start_level="107,5", gradient="0",
                  width="5", reach="6")
        self.made(name=RAMP, feature=RAMP, start="entity:PLT-002", reach="6")
        self.made(name=OVER, feature=OVER, start=self.ground2, mode="CUT_FILL")
        self.assertEqual(self.states(), {"PLT-001": "current", "PLT-002": "current", "PLT-003": "current",
                                         "PLT-004": "current"})
        self.assertEqual(self.starts(), {"PLT-001": self.ground, "PLT-002": "entity:PLT-001",
                                         "PLT-003": "entity:PLT-002", "PLT-004": self.ground2})

    def test_e_what_rests_on_it_shows_the_single_list_with_the_volume_and_writes_nothing(self) -> None:
        """RF-015-15, RF-015-28 (D-11, D-14): «Lo que se apoya en ella» abre una ventana con **la lista única** de lo que se
        apoya en la entidad o parte de su superficie —P2 (parte de la de P1) y P4 (rellena sobre ella), con su tipo y sus
        m³— y, aparte, en qué se apoya ella; la misma lista de ``entities.dependents`` y ``dependencies_of``, que enseña
        también la barra N; con la entidad seleccionada en la vista si no se da; no escribe nada."""
        cls = self.command(DEPENDENTS)
        before = self.state()
        fake, context, popup, said = self.fake(DEPENDENTS, entity="PLT-001")
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        popup.assert_called_once()
        listed = self.entities.dependents(self.project, self.v01.uid, "PLT-001")
        self.assertEqual([(row.name, row.roles) for row in listed],
                         [(WORKSHOP, ("surface",)), (OVER, ("supported_on",))])
        shown = draw(cls, bpy.context, entity="PLT-001", _listed=fake._listed).texts()
        self.assertEqual(shown[:3], ["Entidad de diseño «Carga» (PLT-001)", "Lo que se apoya en ella",
                                     f"{WORKSHOP} (Plataforma): superficie de partida"])
        self.assertRegex(shown[3], rf"^{OVER} \(Plataforma\): .+ m³ apoyados$")
        self.assertGreater(round(listed[1].volume_m3), 100)
        self.assertEqual(shown[4], "Se apoya en")
        self.assertEqual(len(shown), 6, "la partida de P1 (el terreno) es lo único en que se apoya")
        self.assertEqual(self.state(), before, "enseñar la lista no escribe nada")
        with self.selected("PLT-002"):  # sin dar la entidad: la del objeto seleccionado
            chosen, context, popup, said = self.fake(DEPENDENTS)
            self.assertEqual(cls.invoke(chosen, context, None), {"RUNNING_MODAL"})
        texts = draw(cls, bpy.context, entity="", _listed=chosen._listed).texts()
        self.assertEqual(texts[0], "Entidad de diseño «Taller» (PLT-002)")
        self.assertEqual(texts[1:3], ["Lo que se apoya en ella", f"{RAMP} (Plataforma): superficie de partida"])
        lone, context, popup, said = self.fake(DEPENDENTS, entity="PLT-004")  # nada se apoya en ella
        cls.invoke(lone, context, None)
        self.assertIn("Nada se apoya en ella", draw(cls, bpy.context, entity="PLT-004", _listed=lone._listed).texts())

    def test_f_what_rests_on_it_without_a_chosen_entity_or_with_a_wrong_one_says_so(self) -> None:
        """RF-015-28: sin entidad (ni objeto seleccionado), con una que no es de la versión o de otra versión, lo dice sin
        abrir la ventana; desde un guion (``execute``) informa la lista, línea a línea."""
        cls = self.command(DEPENDENTS)
        for values, text in (({}, "Elija la entidad: seleccione su objeto en la Vista 3D o dé su código"),
                             ({"entity": "PLT-009"}, "«PLT-009» no es una entidad de V01")):
            with self.subTest(values=values):
                with self.selected(""):
                    fake, context, popup, said = self.fake(DEPENDENTS, **values)
                    self.assertEqual(cls.invoke(fake, context, None), {"CANCELLED"})
                self.assertEqual(said, [({"ERROR"}, text)])
                popup.assert_not_called()
        elsewhere = mock.patch.object(self.des_ops, "_selected_entity", return_value=("PLT-001", self.v02.uid))
        with elsewhere:
            fake, context, popup, said = self.fake(DEPENDENTS)
            self.assertEqual(cls.invoke(fake, context, None), {"CANCELLED"})
        self.assertEqual(said, [({"ERROR"}, "La entidad seleccionada no es de la versión activa: active antes su "
                                            "versión")])
        scripted, _context, _popup, said = self.fake(DEPENDENTS, entity="PLT-001")
        self.assertEqual(cls.execute(scripted, bpy.context), {"FINISHED"})
        texts = [text for _kind, text in said]
        self.assertEqual(texts[0], "Entidad de diseño «Carga» (PLT-001)")
        self.assertIn(f"{WORKSHOP} (Plataforma): superficie de partida", texts)
        self.assertTrue(all(kind == {"INFO"} for kind, _text in said), said)

    def test_g_the_insert_dialog_offers_the_live_entities_and_says_what_will_happen(self) -> None:
        """RF-015-05, RF-015-28: «Insertar antes o después de…» ofrece las entidades vivas de la versión (por su nombre),
        propone la del objeto seleccionado (o la primera) y dice, según lo elegido, de qué superficie parte la nueva y qué
        pasará con la sucesora (que pasa a partir de la nueva, y con lo que la sigue queda obsoleta) o que se añade al
        final de su cadena; no escribe nada."""
        cls = self.command(INSERT)
        before = self.state()
        with self.selected("PLT-001"):
            fake, context, dialog, said = self.fake(INSERT)
            self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Insertar antes o después de…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Continuar")
        self.assertEqual([(row.name, row.label) for row in fake.references],
                         [(LOADING, "Carga (PLT-001)"), (WORKSHOP, "Taller (PLT-002)"), (RAMP, "Rampa (PLT-003)"),
                          (OVER, "Sobre Carga (PLT-004)")])
        self.assertEqual((fake.reference, fake.placement), (LOADING, "AFTER"))
        first, context, dialog, said = self.fake(INSERT)  # sin objeto seleccionado: la primera
        with self.selected(""):
            cls.invoke(first, context, None)
        self.assertEqual(first.reference, LOADING)

        def shown(reference: str, placement: str) -> list[str]:
            return draw(cls, bpy.context, reference=reference, placement=placement, references=fake.references,
                        _records=fake._records).texts()

        after = shown(LOADING, "AFTER")
        self.assertEqual(after[0], "Entidad")
        self.assertEqual(after[1:], ["La nueva plataforma parte de la superficie de «Carga»",
                                     "«Taller» pasará a partir de la nueva plataforma y, con lo que la sigue, quedará "
                                     "obsoleta hasta que se recalcule"])
        self.assertEqual(shown(LOADING, "BEFORE")[1:], [
            "La nueva plataforma parte de la misma superficie que «Carga»",
            "«Carga» pasará a partir de la nueva plataforma y, con lo que la sigue, quedará obsoleta hasta que se "
            "recalcule"])
        self.assertEqual(shown(RAMP, "AFTER")[1:], [
            "La nueva plataforma parte de la superficie de «Rampa»",
            "Nada parte de la superficie de «Rampa»: la nueva plataforma se añade al final de su cadena"])
        self.assertEqual(shown(WORKSHOP, "BEFORE")[2:], [
            "«Taller» pasará a partir de la nueva plataforma y, con lo que la sigue, quedará obsoleta hasta que se "
            "recalcule"])
        self.assertTrue(shown("Inexistente", "AFTER")[1].startswith("No se puede insertar:"))
        self.assertEqual(self.state(), before, "el diálogo no escribe nada")

    def test_h_accepting_opens_the_platform_dialog_with_its_start_and_the_entity_that_follows(self) -> None:
        """RF-015-05, RF-015-04: aceptar abre «Plataforma…» con la partida de la nueva (``insertion_start``) y, si la
        hay, la entidad que pasará a partir de ella (``insert_before``): después de P1 (partida: su superficie; sucesora:
        P2), antes de P1 (la del terreno; sucesora: P1), antes de P2 (lo mismo que después de P1) y después de la última
        (partida: su superficie y sin sucesora); no escribe nada."""
        cls = self.command(INSERT)
        before = self.state()
        asked = (("PLT-001", "AFTER", "entity:PLT-001", "PLT-002"), (LOADING, "BEFORE", self.ground, "PLT-001"),
                 (WORKSHOP, "BEFORE", "entity:PLT-001", "PLT-002"), ("PLT-003", "AFTER", "entity:PLT-003", None),
                 (OVER, "BEFORE", self.ground2, "PLT-004"))
        for reference, placement, start, successor in asked:
            with self.subTest(reference=reference, placement=placement), \
                    mock.patch.object(self.des_ops, "_invoke_later") as later:
                fake, _context, _dialog, said = self.fake(INSERT, reference=reference, placement=placement)
                self.assertEqual(cls.execute(fake, bpy.context), {"FINISHED"})
                self.assertEqual(said, [])
                values: dict[str, Any] = {"start": start}
                if successor is not None:
                    values["insert_before"] = successor
                later.assert_called_once_with(PLATFORM, mock.ANY, **values)
        self.assertEqual(self.state(), before, "abrir el diálogo no escribe nada")

    def test_i_what_the_insert_refuses_writes_nothing_and_opens_nothing(self) -> None:
        """RF-015-05, RF-015-17: sin entidad, con una que no es de la versión o antes de una sin partida, lo dice con su
        texto y no abre nada ni escribe nada."""
        cls = self.command(INSERT)
        before = self.state()
        for values, text in (({}, "Elija la entidad junto a la que se inserta la nueva plataforma"),
                             ({"reference": "Inexistente"}, "la versión no tiene ninguna entidad")):
            with self.subTest(values=values), mock.patch.object(self.des_ops, "_invoke_later") as later, \
                    self.selected(""):
                fake, _context, _dialog, said = self.fake(INSERT, **values)
                self.assertEqual(cls.execute(fake, bpy.context), {"CANCELLED"})
                (found,) = said
                self.assertEqual(found[0], {"ERROR"})
                self.assertIn(text, found[1])
                later.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_j_creating_the_inserted_one_makes_the_successor_and_what_follows_obsolete(self) -> None:
        """RF-015-05, RF-015-16, RF-008-24: crear «Entre» después de P1 (``start`` de la superficie de P1 e
        ``insert_before`` P2) deja P1 → «Entre» → P2 → P3: la partida de P2 pasa a ser la de la nueva con su motivo; P2 y
        P3 quedan obsoletas con su causa; P1 y la nueva, al día (y P4, que se apoya en P1 sin partir de ella, solo si se
        apoya además en P2 o P3: la cascada es la del grafo); el resumen de «Calcular» lo dice. Sin ``insert_before``, la
        misma plataforma se rechaza (RF-015-04)."""
        with self.assertRaises(RuntimeError) as caught:
            self.calculate(name=BETWEEN, feature=BETWEEN, start="entity:PLT-001", reach="6")
        self.assertIn("ya parte la entidad «Taller»", str(caught.exception))
        self.assertIn("inserte la nueva antes o después de «Taller»", str(caught.exception))
        self.assertIsNone(self.des_ops.calculation())
        starts = self.starts()
        held = self.calculate(name=BETWEEN, feature=BETWEEN, start="entity:PLT-001", reach="6",
                              insert_before="PLT-002")
        self.assertEqual([(item.kind, item.name) for item in held.summary.obsolete],
                         [(self.dprov_preview().ObsoleteKind.SUCCESSOR, WORKSHOP),
                          (self.dprov_preview().ObsoleteKind.SUCCESSOR, RAMP)])
        self.assertEqual(self.starts(), starts, "calcular no escribe")
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(self.starts(), {"PLT-001": self.ground, "PLT-002": "entity:PLT-005",
                                         "PLT-003": "entity:PLT-002", "PLT-004": self.ground2,
                                         "PLT-005": "entity:PLT-001"})
        rests = {row.name for code in ("PLT-002", "PLT-003")
                 for row in self.entities.dependents(self.project, self.v01.uid, code)}
        self.assertEqual(self.states(), {"PLT-001": "current", "PLT-002": "stale", "PLT-003": "stale",
                                         "PLT-004": "stale" if OVER in rests else "current", "PLT-005": "current"})
        self.assertEqual(self.parameter("PLT-002", "start")[0], "entity:PLT-005")
        self.assertIn("Se inserta la entidad Entre antes de Taller",
                      self.rows("SELECT h.reason FROM gb_parameter_history AS h JOIN gb_parameter AS p ON "
                                "p.uid = h.parameter_uid WHERE p.key = 'des.platform.plt_002.start' AND "
                                "p.scope_uid = ? ORDER BY h.rev DESC LIMIT 1", self.v01.uid)[0][0])
        self.assertIn(WORKSHOP, self.entities.stale_reason(self.project, self.v01.uid, "PLT-002"))
        self.assertEqual(self.layer_state(), self.layer_before, "la capa de origen no se toca")

    def test_k_inserting_before_the_first_of_the_chain_re_points_it(self) -> None:
        """RF-015-05 (el caso «antes» que dejó la T13): crear «Entre 2» antes de P1 (``start`` el terreno de P1 e
        ``insert_before`` P1) deja «Entre 2» → P1 → …: P1 parte de la superficie de la nueva y queda obsoleta con lo que la
        sigue (P2 y P3, la insertada antes y P4, que se apoya en ella); la nueva, al día."""
        self.made(name="Entre 2", feature=BETWEEN, start=self.ground, reach="6", insert_before="PLT-001")
        self.assertEqual(self.parameter("PLT-001", "start")[0], "entity:PLT-006")
        self.assertEqual(self.starts()["PLT-006"], self.ground)
        self.assertEqual(self.states(), {"PLT-001": "stale", "PLT-002": "stale", "PLT-003": "stale",
                                         "PLT-004": "stale", "PLT-005": "stale", "PLT-006": "current"})
        chain = self.entities.chain_of(self.entities.registry(self.project, self.v01.uid).records, "PLT-006")
        self.assertEqual([item.code for item in chain], ["PLT-006", "PLT-001", "PLT-005", "PLT-002", "PLT-003"])

    def test_l_the_platform_dialog_says_it_is_an_insertion(self) -> None:
        """RF-015-05: el diálogo de «Plataforma…» lanzado por «Insertar…» dice que se inserta antes de la entidad (por su
        nombre) y lo que pasará con ella; la propiedad que lo lleva es oculta; en un diálogo de siempre, no dice nada."""
        cls = self.command(PLATFORM)
        self.assertNotIn("name", cls.__annotations__["insert_before"].keywords)
        note = "Se inserta antes de «Taller»: «Taller» pasará a partir de su superficie y, con lo que la sigue, " \
               "quedará obsoleta hasta que se recalcule"
        self.assertIn(note, self.drawn(insert_before="PLT-002", _insert_name=WORKSHOP))
        self.assertEqual([text for text in self.drawn(insert_before="", _insert_name="")
                          if text.startswith("Se inserta")], [])

    def test_m_the_menu_commands_work_on_the_selected_entity_when_none_is_given(self) -> None:
        """RF-015-28 (D-14): «Descartar…» y «Soltar el apoyo…», lanzados desde el menú sin entidad, toman la del objeto
        seleccionado en la vista: el diálogo de descartar se abre para ella, y el de soltar el apoyo la toma como lo que
        perdió su apoyo (P4 no lo ha perdido: lo dice con su código)."""
        discard, release = self.command(DISCARD), self.command(RELEASE)
        with self.selected("PLT-004"):
            fake, context, dialog, said = self.fake(DISCARD, reason="", _plan=None)
            self.assertEqual(discard.invoke(fake, context, None), {"RUNNING_MODAL"})
            self.assertEqual(dialog.call_args.kwargs["title"], "Descartar «Sobre Carga»")
            self.assertEqual(fake.entity, "PLT-004")
            lost, context, dialog, said = self.fake(RELEASE, target="", reason="", _lost=None)
            self.assertEqual(release.invoke(lost, context, None), {"CANCELLED"})
        (found,) = said
        self.assertEqual(found[0], {"ERROR"})
        self.assertIn("«PLT-004» no ha perdido su apoyo", found[1])
        dialog.assert_not_called()

    def test_n_the_commands_are_disabled_with_their_reason(self) -> None:
        """RF-015-28 (M5): con el proyecto en solo lectura («Proyecto en solo lectura: …») o la versión activa no editable
        (V02 SUPERADO), las seis órdenes que escriben o dependen de una versión editable salen desactivadas con su motivo
        y no se pueden lanzar; con V01 en escritura, activas. «Exportar la superficie» (la de la 013: no es una operación)
        sigue activa en las dos."""
        for idname in (*WRITING, EXPORT):
            self.assertEqual(self.poll(idname), (True, []), idname)
        before = self.state()
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            for idname in WRITING:
                with self.subTest(orden=idname, caso="solo lectura"):
                    found, messages = self.poll(idname)
                    self.assertFalse(found)
                    (reason,) = messages
                    self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
                    self.assertFalse(getattr(bpy.ops.geoblender, idname.split(".")[1]).poll())
            self.assertEqual(self.poll(EXPORT), (True, []))
            for idname, values in ((DEPENDENTS, {"entity": "PLT-001"}), (INSERT, {"reference": "PLT-001"})):
                with self.assertRaises(RuntimeError):
                    getattr(bpy.ops.geoblender, idname.split(".")[1])("EXEC_DEFAULT", **values)
            self.assertEqual(self.state(), before)
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?",
                         (platform_ops.REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        for idname in WRITING:
            with self.subTest(orden=idname, caso="versión no editable"):
                found, messages = self.poll(idname)
                self.assertFalse(found)
                self.assertEqual(messages, [NOT_EDITABLE])
                self.assertIn(NOT_EDITABLE, self.command(idname).description(bpy.context, SimpleNamespace()))
        self.assertEqual(self.poll(EXPORT), (True, []))
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        for idname in WRITING:
            self.assertEqual(self.poll(idname), (True, []), idname)

    def test_z_disabling_geoblender_removes_the_commands(self) -> None:
        """Principio 8: desactivar Geoblender quita las dos órdenes y no deja ningún temporal."""
        blender_ext.release()
        for name in (DEPENDENTS_CLASS, INSERT_CLASS):
            self.assertIsNone(getattr(bpy.types, name, None))
        self.assertFalse(any(".tmp" in name for name in self.names()))

    # --- Más ayudas (se usan en las pruebas de arriba) ----------------------------------------

    def dprov_preview(self) -> Any:
        return platform_ops._module("design.preview")


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(EntityMenuTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
