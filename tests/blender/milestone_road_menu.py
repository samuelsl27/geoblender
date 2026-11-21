# SPDX-License-Identifier: GPL-3.0-or-later
"""El menú «Entidad ▾» con una pista y una accesibilidad de verdad, con proyecto y con las órdenes reales (spec 017, T33b; HU-017-1 a HU-017-3; RF-015-28, RF-015-05, RF-015-17, RF-015-18, RF-015-26, RF-017-29;
plan 017 §5.3.3; decisión tras la T31b; comprobación manual M6), en ``blender -b`` y sin pantalla.

El mundo de ``milestone_road_sidebar.py`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, el terreno ``Suave`` y el ``Muro``, las bermas y la cantera, la plataforma «Carga» —PLT-001—, dos zonas «requiere
acceso», y, con las órdenes reales, ``RDW-001`` «Pista de la carga», ``RDW-002`` «Ramal al norte» —parte de su eje— y ``ACC-001`` «Alcanzable»; capas, perfiles y valores **solo de las pruebas**). Las pruebas,
**en el orden de sus letras** sobre el mismo estado; las que escriben, al final.

- RF-015-28, RF-015-15 (b): las órdenes del menú toman **la pista seleccionada** en la vista: «Lo que se apoya en ella» da el ramal (y en qué se apoya la pista) y, del ramal, nada; de la accesibilidad (que no es
  una entidad con cadena y cuyo objeto es ``DESIGN``), por su código: no se apoya nada en ella.
- RF-015-28, RF-015-26, RF-017-26 (c): la vista previa de la pista se enciende y se apaga y la de la accesibilidad **se rechaza diciéndolo**; no escriben nada.
- RF-015-05, RF-015-28 (d): «Insertar antes o después de…» **ofrece las pistas y la plataforma y no la accesibilidad** (sin cadena); detrás de una pista, abre «Plataforma…» con su superficie y, si la hay, el ramal
  que parte de ella como sucesor; la accesibilidad se rechaza diciéndolo.
- RF-015-18, RF-015-28 (e): «Traer las entidades de…» ofrece la plataforma y las dos pistas **y no la accesibilidad**; trae todas las que ofrece sin error (también sin teclear nada) y **no deja ninguna accesibilidad en
  la otra versión**; teclear su código se rechaza con su porqué y no escribe nada.
- RF-015-28 (f): con el proyecto en solo lectura o V02 SUPERADO, las siete órdenes salen desactivadas **con su motivo** aunque la pista esté seleccionada; con V01, activas.
- RF-015-05, RF-015-16 (fa): crear la plataforma que abre «Insertar antes o después de…» detrás de la pista, con el ramal como sucesor (``insert_before``), **funciona con una pista de sucesora**: la partida del ramal
  pasa a la superficie de la plataforma nueva y el ramal queda obsoleto con su causa; la pista y la plataforma, al día (lo que la pista no admite es **ser** la insertada: «Pista…» no tiene ``insert_before``).
- RF-015-17, RF-015-28 (g): «Descartar…» toma la pista seleccionada (el ramal queda con el apoyo retirado) y «Soltar el apoyo…» dice que el ramal debe rehacerse o descartarse; descartar la accesibilidad, por su código.
- Principio 8 (z): desactivar Geoblender deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py`` (es un hito: ``check.py --completo``).
"""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import milestone_road_sidebar as sidebar
from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext
from tests.support.fake_layout import operator_self

DEPENDENTS = "geoblender.des_entity_dependents"
INSERT = "geoblender.des_entity_insert"
BRING = "geoblender.des_entity_bring"
CALCULATE = "geoblender.des_entity_calculate"
DISCARD = "geoblender.des_entity_discard"
RELEASE = "geoblender.des_entity_release_support"
PREVIEW = "geoblender.des_entity_preview"
ORDERS = (DEPENDENTS, INSERT, BRING, CALCULATE, DISCARD, RELEASE, PREVIEW)
FIRST, BRANCH = sidebar.FIRST, sidebar.BRANCH
NOT_EDITABLE = "V02 está en estado SUPERADO: cree una versión nueva a partir de ella"
_WORLD = sidebar.RoadSidebarTest.test_a_the_world_is_made_with_the_real_commands


class RoadEntityMenuTest(sidebar.RoadSidebarTest):
    """El mundo de la barra N de la pista y de la accesibilidad (sus pruebas no se repiten: solo los ayudantes)."""

    # --- Ayudas -------------------------------------------------------------------------------

    def command(self, idname: str) -> Any:
        return self.commands.registered_class(idname)

    def fake(self, idname: str, **values: Any) -> tuple[Any, Any, mock.Mock, list[tuple[Any, str]]]:
        """El operador de mentira, el contexto con la capa de vista de verdad (la selección real) y su diálogo, y lo que se informó."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(view_layer=bpy.context.view_layer, window=platform_ops.window(), selected_objects=(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog, invoke_popup=dialog))
        said: list[tuple[Any, str]] = []
        fields: dict[str, Any] = {"entity": "", "reference": "", "placement": "AFTER", "provenance_dialog": False, "in_steps": False,
                                  "report": lambda kind, text: said.append((kind, text)), **values}
        return operator_self(self.command(idname), **fields), context, dialog, said

    def poll(self, idname: str) -> tuple[bool, list[str]]:
        cls = self.command(idname)
        messages: list[str] = []
        with mock.patch.object(cls, "poll_message_set", classmethod(lambda _cls, text: messages.append(text)), create=True):
            return bool(cls.poll(bpy.context)), messages

    def selected(self, uid: str) -> None:
        self.choose(uid)

    # --- a: el mundo -------------------------------------------------------------------------------

    def test_a_the_world_is_made_with_the_real_commands(self) -> None:
        """RF-017-23, RF-017-24, RF-017-25: la pista, el ramal que parte de su eje y la accesibilidad sobre ``Muro``, al día (es el mundo de la barra N: ``milestone_road_sidebar.py``)."""
        _WORLD(self)

    # --- b: lo que se apoya en ella -----------------------------------------------------------------

    def test_b_what_rests_on_it_takes_the_selected_road_and_the_accessibility_by_its_code(self) -> None:
        """RF-015-28, RF-015-15 (M6): con el objeto de la pista seleccionado, «Lo que se apoya en ella» toma **su entidad** sin teclearla y da el ramal; con el del ramal, nada se apoya en él; de la
        accesibilidad (cuyo objeto es ``DESIGN``: no es una entidad con cadena), por su código: nada se apoya en ella. No escribe nada."""
        cls = self.command(DEPENDENTS)
        before = (self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0]))
        self.selected(self.uids["road"])
        self.assertEqual(self.des_ops._selected_entity(bpy.context), ("RDW-001", self.v01.uid))
        fake, context, popup, said = self.fake(DEPENDENTS)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        popup.assert_called_once()
        self.assertEqual((fake._listed.code, fake._listed.name), ("RDW-001", FIRST))
        rests = [text for text, _alert in self.panels.dependent_texts(fake._listed.on_it)]
        self.assertTrue(any(BRANCH in text for text in rests), rests)
        self.assertTrue(self.panels.dependent_texts(fake._listed.rests_on), "se apoya en lo que parte: el terreno")
        self.selected(self.uids["branch"])
        fake, context, popup, said = self.fake(DEPENDENTS)
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual((fake._listed.code, fake._listed.on_it), ("RDW-002", ()))
        for code, name in (("ACC-001", "Alcanzable"), ("RDW-001", FIRST)):
            by_code, context, popup, said = self.fake(DEPENDENTS, entity=code)
            self.assertEqual(cls.invoke(by_code, context, None), {"RUNNING_MODAL"}, code)
            self.assertEqual((by_code._listed.code, by_code._listed.name), (code, name))
        self.assertEqual((self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0])), before, "enseñar la lista no escribe nada")

    # --- c: la vista previa -------------------------------------------------------------------------

    def test_c_the_preview_of_the_road_is_shown_and_hidden_and_the_accessibility_says_it_has_none(self) -> None:
        """RF-015-28, RF-015-26, RF-017-26 (M6): la vista previa de la pista seleccionada se enciende (su eje con lo que se le apoya: ``EntityPlan(road=…)``) y se apaga con la misma orden; la de la
        accesibilidad **se rechaza** nombrándola y no deja nada encendido; ninguna escribe en el proyecto."""
        before = (self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0]))
        self.selected(self.uids["road"])
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT"), {"FINISHED"})  # sin teclear la entidad: la del objeto seleccionado
        self.assertTrue(self.des_ops._entity_preview_on())
        self.assertEqual(bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT"), {"FINISHED"})  # la misma orden la apaga
        self.assertFalse(self.des_ops._entity_preview_on())
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", entity="ACC-001")
        self.assertIn("«Alcanzable»", str(caught.exception))
        self.assertIn("no tiene vista previa", str(caught.exception))
        self.assertFalse(self.des_ops._entity_preview_on())
        self.assertEqual((self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0])), before)

    # --- d: insertar --------------------------------------------------------------------------------

    def test_d_insert_offers_the_roads_and_the_platform_and_not_the_accessibility(self) -> None:
        """RF-015-05, RF-015-28 (M6): el diálogo de «Insertar antes o después de…» ofrece la plataforma y las dos pistas (por su nombre) y **no la accesibilidad** (sin cadena); con la pista seleccionada la propone;
        detrás de ella abre **«Plataforma…»** (no «Pista…») con la superficie de la pista como partida y, como sucesor, el ramal que parte de ella; delante de ella, con la partida de la pista; la accesibilidad se
        rechaza diciéndolo; no escribe nada."""
        cls = self.command(INSERT)
        before = (self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0]))
        self.selected(self.uids["road"])
        fake, context, dialog, said = self.fake(INSERT, references=_Rows())
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual([row.name for row in fake.references], [platform_ops.LOADING, FIRST, BRANCH])
        self.assertEqual(fake.reference, FIRST)
        for ref, placement, start, successor in (("RDW-001", "AFTER", "entity:RDW-001", "RDW-002"), ("RDW-002", "AFTER", "entity:RDW-002", None),
                                                 ("RDW-001", "BEFORE", self.smooth_surface, "RDW-001")):
            with self.subTest(referencia=ref, colocación=placement), mock.patch.object(self.des_ops, "_invoke_later") as later:
                asked, _context, _dialog, said = self.fake(INSERT, reference=ref, placement=placement)
                self.assertEqual(cls.execute(asked, bpy.context), {"FINISHED"})
                self.assertEqual(said, [])
                values: dict[str, Any] = {"start": start}
                if successor:
                    values["insert_before"] = successor
                later.assert_called_once_with(self.des_ops.CREATE_PLATFORM, mock.ANY, **values)
        with mock.patch.object(self.des_ops, "_invoke_later") as later:
            refused, _context, _dialog, said = self.fake(INSERT, reference="ACC-001")
            self.assertEqual(cls.execute(refused, bpy.context), {"CANCELLED"})
        later.assert_not_called()
        self.assertIn("sin cadena", said[0][1])
        self.assertEqual((self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0])), before)

    # --- e: traer -----------------------------------------------------------------------------------

    def test_e_bring_offers_and_brings_everything_but_the_accessibility(self) -> None:
        """RF-015-18, RF-015-28 (M6; decisión tras la T31b): con V02 activa, «Traer las entidades de…» V01 ofrece la plataforma y las dos pistas (**no la accesibilidad**, que no se trae: se vuelve a calcular);
        sin teclear nada trae todas las que ofrece, **sin el error que daba con una accesibilidad en la versión de origen**, y V02 no tiene ninguna; teclear el código de la accesibilidad se rechaza con su
        porqué y no escribe nada."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        cls = self.command(BRING)
        offered, context, _dialog, said = self.fake(BRING, source="V01", entities="", rows=_Rows(), versions=_Rows())
        self.assertEqual(cls.invoke(offered, context, None), {"RUNNING_MODAL"})
        self.assertEqual([(row.name, row.selected) for row in offered.rows], [("PLT-001", True), ("RDW-001", True), ("RDW-002", True)])
        before = (self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0]), self.states(self.v02))
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities="PLT-001, ACC-001")
        self.assertIn("accesibilidad", str(caught.exception))
        self.assertIn("se vuelve a calcular", str(caught.exception))
        self.assertEqual((self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0]), self.states(self.v02)), before, "lo rechazado no escribe nada")
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities=""), {"FINISHED"})
        brought = self.states(self.v02)
        self.assertEqual(brought, {"PLT-001": "uncalculated", "RDW-001": "uncalculated", "RDW-002": "uncalculated"})
        self.assertNotIn("ACC-001", brought)
        self.assertEqual(self.states()["ACC-001"], "current", "la de V01, intacta")

    # --- f: la activación ---------------------------------------------------------------------------

    def test_f_the_seven_orders_are_disabled_with_their_reason_with_the_road_selected(self) -> None:
        """RF-015-28 (M6): con la pista seleccionada, las siete órdenes del menú «Entidad ▾» salen activas con V01 en escritura y **desactivadas con su motivo** con el proyecto en solo lectura o con V02 SUPERADO
        (y su descripción dice por qué); sin lanzar ninguna."""
        self.selected(self.uids["road"])
        for idname in ORDERS:
            self.assertEqual(self.poll(idname), (True, []), idname)
        with mock.patch.object(self.project, "_status", self.project.status):
            self.project.set_read_only(platform_ops._module("core.project").ReadOnlyCode.REQUESTED, "prueba")
            for idname in ORDERS:
                with self.subTest(orden=idname, caso="solo lectura"):
                    found, messages = self.poll(idname)
                    self.assertFalse(found)
                    (reason,) = messages
                    self.assertTrue(reason.startswith("Proyecto en solo lectura: "), reason)
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v02.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?", (platform_ops.REASON, self.v02.uid))
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        for idname in ORDERS:
            with self.subTest(orden=idname, caso="versión no editable"):
                found, messages = self.poll(idname)
                self.assertFalse(found)
                self.assertEqual(messages, [NOT_EDITABLE])
                self.assertIn(NOT_EDITABLE, self.command(idname).description(bpy.context, SimpleNamespace()))
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        for idname in ORDERS:
            self.assertEqual(self.poll(idname), (True, []), idname)

    # --- fa: insertar de verdad ---------------------------------------------------------------------

    def test_fa_a_platform_inserted_after_the_road_makes_the_branch_start_from_it_and_leaves_it_stale(self) -> None:
        """RF-015-05, RF-015-16 (M6): crear «Taller» (la plataforma que abre «Insertar antes o después de…» detrás de la pista, con ``insert_before`` el ramal) deja **la partida del ramal en la superficie
        de la plataforma nueva**, con su motivo, y al ramal **obsoleto con su causa**; la pista y la plataforma, al día."""
        self.refresh()
        form = platform_ops.CreatePlatformTest.form(self, name=platform_ops.WORKSHOP, feature=platform_ops.WORKSHOP, start="entity:RDW-001", start_level="107,5", gradient="0", width="5", reach="6",
                                                    insert_before="RDW-002")
        self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **form), {"FINISHED"})
        self.assertIsNotNone(self.des_ops.calculation())
        self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, confirm_counterslope=True, in_steps=False), {"FINISHED"})
        records = {item.code: item for item in self.entities.registry(self.project, self.v01.uid).records}
        self.assertEqual(records["RDW-002"].start, "entity:PLT-002")
        self.assertEqual(records["PLT-002"].start, "entity:RDW-001")
        states = self.states()
        self.assertEqual((states["RDW-001"], states["PLT-002"], states["RDW-002"]), ("current", "current", "stale"))
        self.assertEqual(self.entities.stale_reason(self.project, self.v01.uid, "RDW-002"), "Obsoleto: cambió Superficie de partida de la entidad · Ramal al norte")

    # --- g: descartar -------------------------------------------------------------------------------

    def test_g_discard_takes_the_selected_road_and_release_says_the_branch_must_be_remade(self) -> None:
        """RF-015-17, RF-015-28 (M6): «Descartar…» con el objeto de la pista seleccionado la toma, enseña antes lo que se le apoya (el ramal) y, al aceptar, la deja descartada y al ramal con el apoyo retirado;
        «Soltar el apoyo…» del ramal dice que parte de la superficie de una entidad descartada (hay que rehacerlo o descartarlo) y no escribe; la accesibilidad se descarta por su código."""
        self.selected(self.uids["road"])
        discard = self.command(DISCARD)
        fake, context, dialog, said = self.fake(DISCARD, reason="", _plan=None)
        self.assertEqual(discard.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual((fake.entity, dialog.call_args.kwargs["title"]), ("RDW-001", f"Descartar «{FIRST}»"))
        self.assertTrue(any(BRANCH in line for line in fake._plan.lines("es")), "antes de descartar, lo que se le apoya")
        self.assertEqual(self.states()["RDW-001"], "current", "enseñar la lista no descarta nada")
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity=fake.entity, reason="La pista se rehace", in_steps=False), {"FINISHED"})  # lo que el diálogo propuso (la seleccionada)
        self.assertEqual((self.states()["RDW-001"], self.states()["RDW-002"]), ("discarded", "support_removed"))
        before = (self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0]))
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_entity_release_support("EXEC_DEFAULT", target="RDW-002", reason="Prueba", in_steps=False)
        self.assertIn(f"parte de la superficie de «{FIRST}», que se descartó", str(caught.exception))
        self.assertIn("rehágala sobre otra superficie", str(caught.exception))
        self.assertEqual((self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0])), before)
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="ACC-001", reason="Otra accesibilidad", in_steps=False), {"FINISHED"})
        self.assertEqual(self.states()["ACC-001"], "discarded")

    # --- z: el registro -----------------------------------------------------------------------------

    def test_z_disable_leaves_blender_as_it_was(self) -> None:
        """Principio 8: con el menú «Entidad ▾» y las órdenes usadas con una pista y una accesibilidad, desactivar Geoblender deja Blender como estaba."""
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


class _Rows:
    """Una colección de mentira (``CollectionProperty``): lo que llena el diálogo."""

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


for _name in dir(sidebar.RoadSidebarTest):  # sus pruebas son suyas (la barra N): aquí solo el mundo y los ayudantes
    if _name.startswith("test_") and _name not in vars(RoadEntityMenuTest):
        setattr(RoadEntityMenuTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
