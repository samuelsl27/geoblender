# SPDX-License-Identifier: GPL-3.0-or-later
"""«Calcular…» de una pista traída a otra versión, en Blender (spec 017, T33c; HU-017-1 y HU-017-2; RF-015-18, RF-015-04, RF-017-01, RF-017-03, RF-017-29, RF-015-29, RF-017-30; D-13; E5; la duda T22b (d)).

Una pista traída a otra versión (``des_entity_bring``) o heredada de la versión de la que parte queda **sin calcular** (RF-015-18) y «Calcular…» (``geoblender.des_entity_calculate``, del menú «Entidad ▾»)
solo servía a las plataformas: sin ella, el escenario E5 («todo traído a otra versión») acababa en un callejón sin salida para quien usa la interfaz. Ahora la ventana ofrece **la plataforma y las pistas
sin calcular** de la versión activa (la accesibilidad no es una entidad y no se trae: queda fuera) y, al aceptar, lanza «Pista…» (``des_create_road``) **con su código** (la propiedad oculta ``code``):
sin diálogo, calcula con los parámetros que la pista ya tiene en la versión (``design.road_store.entity_road_request``: ``provenance.road_request`` de sus parámetros, como «Recalcular lo obsoleto»), por
pasos con el avance y Esc, enseña el resumen y pide confirmar; «Crear» la registra **con su código y sin tocar ningún parámetro**, **por pasos y en una sola transacción** (``_CreatesInSteps``), y las
dependencias («se apoya en»: el eje de la pista del origen, la plataforma del destino, otros diseños) se detectan de nuevo (RF-015-04).

El mundo es el de ``milestone_road_steps_cuts.py`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, los terrenos ``Suave`` y ``A15``, las capas de la pista y los perfiles de referencia de IMGA, **solo de
pruebas**) con, en V01 y con las órdenes reales: la plataforma ``PLT-001`` «Carga», la pista ``RDW-001`` «Pista de la carga», su ramal ``RDW-002`` «Ramal al norte» (parte de su eje a 20 m) y la
accesibilidad ``ACC-001`` «Alcanzable». Se trae V01 a V02 (que no tiene el perfil de la pista: **los valores del perfil no viajan con ella**) y se calcula allí. Las pruebas, **en el orden de sus
letras** sobre el mismo estado.

- RF-015-18, RF-017-29 (b): la ventana de «Calcular…» ofrece la plataforma y las dos pistas **sin calcular** (no la accesibilidad, que no se trae), propone la primera y dice con qué se calcula; no
  escribe nada. La orden se rehúsa con una accesibilidad (diciendo que solo una plataforma o una pista se calculan así), con una pista que ya tiene resultado y con una que no es de la versión.
- RF-015-18, RF-017-03, RF-015-04 (c): sin el perfil en V02 el cálculo se rehúsa **con su causa** (``des.road_profile_value_missing``) y el ramal, antes que su pista, también (su partida es la superficie de
  una pista aún sin calcular); ninguno deja nada (0 transacciones).
- RF-015-18, RF-015-29 (d): la plataforma traída se calcula **igual que siempre** (``des_create_platform`` con su código); con el perfil ya en V02, **Esc a mitad de «Calcular»** una pista traída y **Esc entre
  los pasos de «Crear»** responden en ≤ 2 s, no dejan nada (ni operación, ni dato, ni parámetro, ni temporal, ni cálculo abierto) y la pista sigue «sin calcular».
- RF-015-18, RF-017-01, RF-017-03, D-13 (e): «Calcular…» de la pista traída la deja **al día con su eje y su huella, igual que la de V01** (mismas cifras, mismos papeles y rejillas con los mismos
  hashes, mismas filas del eje y de la huella, **con las mismas entradas**); calcular no escribe nada; «Crear» es **una sola transacción** y ningún evento escribe antes de la última; los parámetros de la
  pista **no se tocan** (con su historial «Traído de V01.r1»); la capa de entidades y la de ejes la ponen al día.
- RF-015-18, RF-015-04, RF-017-03 (f): el ramal traído **sigue a su principal**: se calcula tras ella, se apoya de nuevo en su eje y en su superficie con los mismos papeles y las mismas cifras que en V01, y
  lo que se apoya en la pista es el ramal; V01 no cambia.
- Principio 8 (z): desactivar Geoblender quita la orden y las suyas y no deja ningún temporal.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import test_platform_ops as platform_ops
from tests.blender import milestone_road_ops as road_ops
from tests.blender import milestone_road_steps_cuts as steps
from tests.support import blender_ext, step_modals
from tests.support.fake_layout import draw, operator_self

CALCULATE = "geoblender.des_entity_calculate"
BRING = "geoblender.des_entity_bring"
ROAD_ID = "geoblender.des_create_road"
PLATFORM_ID = "geoblender.des_create_platform"
FIRST, BRANCH, LOADING = road_ops.FIRST, road_ops.BRANCH, platform_ops.LOADING
ACCESS_NAME = "Alcanzable"
CODES = {"PLT-001": LOADING, "RDW-001": FIRST, "RDW-002": BRANCH}
"""Lo que se trae a V02: la plataforma y las dos pistas (la accesibilidad, no)."""
TOLERANCE = 1e-9


class Rows:
    """Una colección de mentira (``CollectionProperty``): lo que usa la ventana."""

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


class BroughtRoadCalculateTest(steps.RoadStepsCase):
    """El mundo de ``milestone_road_steps_cuts.py`` con la plataforma, las dos pistas y la accesibilidad de V01, traídas a V02. Las pruebas de la pista y de los pasos son de sus módulos."""

    v01_ops: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.v01_ops = {}

    # --- Ayudas -------------------------------------------------------------------------------

    def make(self, command: str, form: dict[str, Any]) -> None:
        """«Calcular» y «Crear» desde un guion con la orden real ``command``."""
        operator = getattr(bpy.ops.geoblender, command)
        self.assertEqual(operator("EXEC_DEFAULT", **form), {"FINISHED"})
        self.assertIsNotNone(self.des_ops.calculation())
        self.assertEqual(operator("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.refresh()

    def activate(self, version: Any) -> None:
        """La versión activa pasa a ser ``version``, con sus máscaras al día."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=version.uid), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        self.refresh()

    def states(self, version: Any) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in self.entities.registry(self.project, version.uid)}

    def operation(self, version: Any, code: str) -> str:
        """El uid de la operación vigente de la entidad ``code`` de ``version``."""
        entry = self.entities.registry(self.project, version.uid).get(code)
        self.assertIsNotNone(entry.operation_uid, code)
        return str(entry.operation_uid)

    def parameters(self, version: Any) -> list[tuple[Any, ...]]:
        """Los parámetros propios de ``version`` con su historial (valor, revisión, decisor y fecha): lo que calcular **no** puede cambiar."""
        return self.rows("SELECT key, value, rev, decided_by, decided_at FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? ORDER BY key", version.uid)

    def history(self, code: str, param: str, version: Any) -> list[str]:
        return [reason for (reason,) in self.rows("SELECT h.reason FROM gb_parameter_history AS h JOIN gb_parameter AS p ON p.uid = h.parameter_uid WHERE p.key = ? AND p.scope = 'version' "
                                                  "AND p.scope_uid = ? ORDER BY h.rev", f"des.road.{code.lower().replace('-', '_')}.{param}", version.uid)]

    def figures_of(self, uid: str) -> list[tuple[str, str, float]]:
        """Las cifras de la operación ``uid``, en su orden: ``(clave, ámbito, valor)``."""
        return [(key, scope, value) for key, scope, value in self.rows("SELECT key, scope, value FROM gb_figure WHERE operation_uid = ? ORDER BY fid", uid)]

    def inputs_of(self, uid: str) -> list[tuple[str, str]]:
        """Lo que consumió la operación ``uid``: ``(papel, nombre del dato)`` de sus entradas, ordenadas."""
        return sorted((str(role), str(name)) for role, name in self.rows(
            "SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' AND io.item_kind = 'dataset'", uid))

    def outputs_of(self, uid: str) -> list[tuple[str, str]]:
        """Lo que escribió la operación ``uid``: ``(papel, hash del contenido)`` de cada salida en su orden (de las tablas, que llevan el código y el nombre, solo el papel)."""
        return [(str(role), str(sha) if str(name).startswith("des_psf_") else "") for role, name, sha in self.rows(
            "SELECT io.role, d.name, d.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out' "
            "AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def table_of(self, version: Any, family: str, name: str) -> list[tuple[Any, ...]]:
        """Las filas de la tabla ``family`` (``epr``, ``rdx``…) de la entidad ``name`` de ``version``, sin la que identifica su fila."""
        ((locator,),) = self.rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current' AND version_uid = ?", self.dprov.dataset_name(family, name), version.uid)
        return [tuple(row[1:]) for row in self.rows(f'SELECT * FROM "{locator}" ORDER BY fid')]

    def candidates(self, **values: Any) -> tuple[Any, Any, mock.Mock, list[tuple[Any, str]]]:
        """El operador de «Calcular…» de mentira, el contexto con que se abre su ventana, esta y lo que se informó."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        said: list[tuple[Any, str]] = []
        fields: dict[str, Any] = {"entity": "", "candidates": Rows(), "provenance_dialog": False, "report": lambda kind, text: said.append((kind, text)), **values}
        return operator_self(self.commands.registered_class(CALCULATE), **fields), context, dialog, said

    def launch(self, entity: str) -> tuple[str, dict[str, Any]]:
        """«Calcular…» ``entity`` desde un guion: **lo que abre** (la orden y sus valores; el temporizador que la abre no corre en ``blender -b``)."""
        calls: list[tuple[str, dict[str, Any]]] = []
        with mock.patch.object(self.des_ops, "_invoke_later", side_effect=lambda idname, _window, **values: calls.append((idname, values))):
            self.assertEqual(bpy.ops.geoblender.des_entity_calculate("EXEC_DEFAULT", entity=entity), {"FINISHED"})
        self.assertEqual(len(calls), 1)
        return calls[0]

    def open_road(self, entity: str) -> Any:
        """«Calcular…» ``entity`` de punta a punta hasta que corre «Pista…»: la lanza con lo que le pide «Calcular…» (su ``code``) desde la interfaz (``in_steps``: el modal de pasos; el temporizador que
        la abre no corre en ``blender -b``, y ``INVOKE_DEFAULT`` no tiene ventana) y devuelve su modal en marcha, con un paso por evento."""
        idname, values = self.launch(entity)
        self.assertEqual((idname, values), (ROAD_ID, {"code": entity}))
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", in_steps=True, **values), {"RUNNING_MODAL"})
        return self.modal_of("des_create_road")

    def refused(self, text: str, **values: Any) -> None:
        """Lanzar «Calcular…» desde un guion se rechaza con ``text``, no abre ninguna orden y no escribe nada."""
        before = self.state()
        with mock.patch.object(self.des_ops, "_invoke_later") as later, self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_entity_calculate("EXEC_DEFAULT", **values)
        self.assertIn(text, str(caught.exception))
        later.assert_not_called()
        self.assertEqual(self.state(), before)

    def calculated(self, entity: str) -> Any:
        """«Calcular…» ``entity`` hasta el final (un paso por evento): el cálculo abierto, que no ha escrito nada."""
        before = self.state()
        modal = self.open_road(entity)
        self.assertEqual(self.drive(modal)[0], {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        self.assertEqual(self.state()[:4], before[:4], "calcular no registra nada")
        self.assertEqual(self.temporaries(), [], "ni deja un temporal")
        return held

    # --- a: el mundo -------------------------------------------------------------------------------

    def test_a_the_world_is_made_in_v01_with_the_real_commands(self) -> None:
        """RF-017-01, RF-017-03, RF-015-18: la plataforma «Carga», la pista «Pista de la carga» (de (10, 30) a (50, 30) sobre ``Suave``), su ramal (parte de su eje a 20 m) y la accesibilidad
        «Alcanzable», creados con las órdenes reales en V01, al día; V02 está vacía y no tiene el perfil de la pista."""
        self.refresh()
        self.make("des_create_platform", platform_ops.CreatePlatformTest.form(self, start=self.ground))
        self.make("des_create_road", self.road_form("TRACE", self.smooth_surface, FIRST))
        branch = self.road_form("TRACE", self.smooth_surface, BRANCH)
        branch.update(origin_from="ROAD", origin_road=self.code_of(FIRST), origin_station="20", destination_point="Destino norte", start=f"entity:{self.code_of(FIRST)}")
        self.make("des_create_road", branch)
        self.make("des_road_access", self.access_form(self.second_surface, ACCESS_NAME))
        self.finish_chain()
        self.assertEqual(self.states(self.v01), {"PLT-001": "current", "RDW-001": "current", "RDW-002": "current", "ACC-001": "current"})
        self.assertEqual(self.states(self.v02), {})
        self.assertEqual(self.rows("SELECT count(*) FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? AND key LIKE 'des.roadprofile.%'", self.v02.uid), [(0,)])
        type(self).v01_ops = {code: self.operation(self.v01, code) for code in CODES}

    # --- b: la ventana -----------------------------------------------------------------------------

    def test_b_the_window_offers_the_platform_and_the_roads_without_a_result_and_not_the_accessibility(self) -> None:
        """RF-015-18, RF-015-28, RF-017-29: tras traer V01 a V02 con la orden real, «Calcular…» ofrece **por su nombre** la plataforma y las dos pistas sin calcular (una sin calcular no tiene objeto
        en la vista) **y no la accesibilidad, que no se trae**, propone la primera y dice con qué se calcula; lo dado, por su código, se queda; no escribe nada. Con una accesibilidad, con una pista
        que ya tiene resultado y con una que no es de la versión, la orden **lo dice**, no abre nada y no escribe nada."""
        self.activate(self.v02)
        self.addCleanup(self.activate, self.v01)
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01"), {"FINISHED"})
        self.assertEqual(self.states(self.v02), dict.fromkeys(CODES, "uncalculated"), "la accesibilidad no se trae")
        before = self.state()
        cls = self.commands.registered_class(CALCULATE)
        fake, context, dialog, said = self.candidates()
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        self.assertEqual(said, [])
        self.assertEqual(dialog.call_args.kwargs["title"], "Calcular…")
        self.assertEqual([(row.name, row.label) for row in fake.candidates],
                         [(LOADING, "Carga (PLT-001)"), (FIRST, "Pista de la carga (RDW-001)"), (BRANCH, "Ramal al norte (RDW-002)")])
        self.assertEqual(fake.entity, LOADING, "propone la primera")
        given, context, _dialog, _said = self.candidates(entity="RDW-002")
        cls.invoke(given, context, None)
        self.assertEqual(given.entity, BRANCH, "lo dado, por su código, se queda (con su nombre)")
        self.assertEqual(draw(cls, bpy.context, entity=BRANCH, candidates=fake.candidates).texts()[0], "Entidad")
        self.assertEqual(self.state(), before, "la ventana no escribe nada")
        self.refused("«PLT-099» no es una entidad de V02", entity="PLT-099")
        self.refused("Elija la entidad que se calcula")
        self.activate(self.v01)
        self.refused("«Alcanzable» (", entity="ACC-001")  # la accesibilidad es de V01 y no se calcula desde aquí
        self.refused("no se calcula desde aquí", entity="ACC-001")
        self.refused("solo una plataforma o una pista se calculan con sus parámetros guardados", entity="ACC-001")
        self.refused("La entidad «Pista de la carga» (RDW-001) ya tiene resultado en V01", entity="RDW-001")
        self.activate(self.v02)

    # --- c: lo que se rehúsa con su causa ------------------------------------------------------

    def test_c_without_the_profile_or_without_its_road_the_calculation_is_refused_with_its_cause(self) -> None:
        """RF-015-18, RF-017-03, RF-015-04, RF-015-08: **los valores del perfil de la pista no viajan con ella** (son parámetros de V01): en V02 la pista traída se rehúsa **diciéndolo**
        (``des.road_profile_value_missing``: el perfil, el campo y dónde declararlo) y **el ramal antes que su pista** también (su partida es la superficie de una pista sin calcular:
        ``des.entity_start_unknown``); no queda nada: ni operación, ni dato, ni parámetro, ni temporal, ni cálculo abierto."""
        self.activate(self.v02)
        before = self.state()
        for entity, text in (("RDW-001", "Perfil de pista «PISTA_PRINCIPAL»"), ("RDW-002", "no es la superficie de una entidad calculada")):
            with self.subTest(entidad=entity):
                modal = self.open_road(entity)
                state, _events = self.drive(modal)
                self.assertEqual(state, {"CANCELLED"})
                self.assertTrue(any(text in line for line in modal.report_log), modal.report_log)
                self.assert_nothing_left(before, entity)
        self.assertEqual(self.states(self.v02), dict.fromkeys(CODES, "uncalculated"))

    # --- d: la plataforma, y Esc ---------------------------------------------------------------

    def test_d_the_platform_is_calculated_as_always_and_esc_leaves_nothing_of_a_road(self) -> None:
        """RF-015-18, RF-015-29, RF-017-30, RNF-017-06: con «Calcular…» la plataforma traída se calcula **igual que siempre** (``des_create_platform`` con su código: su huella, sus parámetros y su
        historial sin tocar); con el perfil ya en V02, **Esc a mitad de «Calcular»** la pista traída y **Esc entre los pasos de «Crear»** (con ficheros temporales ya escritos) responden en ≤ 2 s, **no
        dejan nada** (el proyecto como estaba, ningún temporal, ninguna operación a medias, ningún cálculo abierto) y la pista sigue **sin calcular**."""
        self.activate(self.v02)
        parameters = self.parameters(self.v02)
        idname, values = self.launch("PLT-001")
        self.assertEqual((idname, values), (PLATFORM_ID, {"code": "PLT-001"}), "la plataforma, por su camino de siempre")
        self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", in_steps=False, **values), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertEqual(self.states(self.v02), {"PLT-001": "current", "RDW-001": "uncalculated", "RDW-002": "uncalculated"})
        self.assertEqual(self.parameters(self.v02), parameters, "calcular la plataforma no reescribe sus parámetros")
        self.refresh()
        self.profile_in_v02()
        parameters = self.parameters(self.v02)
        before = self.state()

        dialog = mock.Mock(return_value={"RUNNING_MODAL"})  # «Pista…» lanzada con el código **no abre su diálogo**: ``invoke`` calcula (sin ventana, de una vez)
        context = SimpleNamespace(window=None, selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fake = self.fake(code="RDW-001", name="", layer="", profile="", start="", _show_calculated=lambda held: None)  # el ``staticmethod`` no se liga a un ``self`` simulado
        self.assertEqual(self.road.invoke(fake, context, None), {"FINISHED"})
        dialog.assert_not_called()
        opened = self.des_ops.calculation()
        self.assertEqual((opened.name, opened.entity.code, opened.version), (FIRST, "RDW-001", "V02"))
        self.des_ops.discard_calculation()
        self.assertEqual(self.state(), before, "calcular no escribe nada")

        run = steps.Run(modal=self.open_road("RDW-001"))
        self.assertEqual(self.drive(run.modal, stop_after=3)[0], {"RUNNING_MODAL"})
        self.escape(run.modal)
        self.assertIn(steps.CANCELLED_CALC, run.modal.report_log)
        self.assert_nothing_left(before, "Esc a mitad de «Calcular»")
        self.assertEqual(self.states(self.v02)["RDW-001"], "uncalculated")

        held = self.calculated("RDW-001")
        self.assertEqual((held.op_type, held.name, held.version, held.entity.code), ("des.road", FIRST, "V02", "RDW-001"))
        before = self.state()
        modal = self.start(steps.ROAD, confirm=True)
        for _event in range(step_modals.MAX_EVENTS):
            self.assertEqual(self.drive(modal, stop_after=1)[0], {"RUNNING_MODAL"})
            if self.temporaries():
                break
        else:
            self.fail("«Crear» no escribió ningún fichero temporal")
        self.assertEqual(self.escape_and_check("TRACE", FIRST, modal, before, "Esc entre los pasos de «Crear»"), "create")
        self.assertEqual(self.states(self.v02)["RDW-001"], "uncalculated", "ni creada ni a medias")
        self.assertEqual(self.parameters(self.v02), parameters)

    def profile_in_v02(self) -> None:
        """El perfil de referencia de IMGA (**solo de las pruebas**) con sus valores en V02: el de V01 no se trae con las entidades."""
        profiles, dparams = platform_ops._module("design.road_profiles"), platform_ops._module("design.params")
        declared = profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", platform_ops.PERSON, road_ops.REASON, version=self.v02.code)
        values = {param: getattr(road_ops.rd.PROFILE, "class_name" if param.value == "class" else param.value) for param in dparams.RoadProfileParam}
        profiles.edit_road_profiles(self.project, (profiles.ProfileEdit(code=road_ops.MAIN.lower(), values=values),), declared)

    # --- e: la pista --------------------------------------------------------------------------------

    def test_e_the_brought_road_is_calculated_up_to_date_like_the_one_of_v01_in_one_transaction(self) -> None:
        """RF-015-18, RF-017-01, RF-017-03, RF-015-04, D-13, RF-017-30: «Calcular…» la pista traída «Pista de la carga» en V02 (la orden real: «Pista…» con su código, sin diálogo) enseña el
        resumen **sin escribir nada** y «Crear» —por pasos, con el avance— la registra **con su código y sin tocar ni un parámetro** (las mismas filas, con su historial «Traído de V01.r1»):
        **una sola transacción**, que es el último paso (ningún evento escribió antes); queda **al día con su eje y su huella, igual que la de V01**: las mismas cifras (≤ 10⁻⁹), los mismos
        papeles y rejillas con los mismos hashes de contenido, las mismas filas del eje y de la huella y **las mismas entradas** (el terreno, la capa de origen, los otros diseños); las dos capas
        (la de entidades y la de ejes) se ponen al día en el mismo modal."""
        self.activate(self.v02)
        parameters = self.parameters(self.v02)
        self.assertEqual(self.history("RDW-001", "name", self.v02), ["Traído de V01.r1"])
        held = self.calculated("RDW-001")
        self.assertEqual((held.op_type, held.name, held.version, held.entity.code), ("des.road", FIRST, "V02", "RDW-001"))
        self.assertTrue(self.view.summary_title.startswith(f"Pista «{FIRST}»"), self.view.summary_title)
        self.assertEqual(self.states(self.v02)["RDW-001"], "uncalculated")

        writer, seen = platform_ops._module("design.store").DesignWriter, []
        real = writer.commit

        def counted(this: Any, *args: Any, **kwargs: Any) -> Any:
            seen.append(getattr(args[0] if args else kwargs.get("start"), "op_type", "(reanudada)"))
            return real(this, *args, **kwargs)

        run = steps.Run(name=FIRST)
        run.before = self.state()
        with mock.patch.object(writer, "commit", counted):
            run.modal = self.start(steps.ROAD, confirm=True)
            run.state, run.events = self.drive(run.modal, run=run)
        self.assertEqual(run.state, {"FINISHED"})
        self.assertGreater(run.commit, 3, "crear por pasos son varios eventos")
        self.assertEqual(run.written, [], "ningún evento escribió en el proyecto antes del último paso")
        self.assertEqual(seen.count("des.road"), 1, f"una sola transacción para crear la pista: {seen}")
        self.assertIn(steps.CREATED[steps.ROAD].format(name=FIRST).replace("V01", "V02"), list(run.modal.report_log))
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.states(self.v02)["RDW-001"], "current")
        self.assertEqual(self.parameters(self.v02), parameters, "crear no cambia ningún parámetro")
        self.assertEqual(self.history("RDW-001", "name", self.v02), ["Traído de V01.r1"])

        there, here = self.v01_ops["RDW-001"], self.operation(self.v02, "RDW-001")
        self.assertNotEqual(there, here)
        original, again = self.figures_of(there), self.figures_of(here)
        self.assertEqual([item[:2] for item in again], [item[:2] for item in original], "las mismas cifras, con su ámbito")
        for (name, _scope, value), (_name, _again_scope, found) in zip(original, again, strict=True):
            self.assertAlmostEqual(found, value, delta=TOLERANCE * max(1.0, abs(value)), msg=name)
        self.assertGreater(len(original), 20, "las cifras de la pista, no un puñado")
        self.assertEqual(self.outputs_of(here), self.outputs_of(there), "los mismos papeles y rejillas, con los mismos hashes de contenido")
        for family in ("epr", "rdx", "prp"):
            self.assertEqual(self.table_of(self.v02, family, FIRST), self.table_of(self.v01, family, FIRST), family)
        self.assertEqual(self.inputs_of(here), self.inputs_of(there), "las mismas entradas")
        self.assertEqual(self.states(self.v01)["RDW-001"], "current", "V01 no cambia")
        self.assertEqual(self.operation(self.v01, "RDW-001"), there)
        self.assertTrue(self.rows("SELECT 1 FROM gb_dataset WHERE version_uid = ? AND name = ? AND status = 'current'", self.v02.uid, "des_enl"), "la capa de entidades, al día")
        self.assertTrue(self.rows("SELECT 1 FROM gb_dataset WHERE version_uid = ? AND name = ? AND status = 'current'", self.v02.uid, "des_rax"), "la capa de ejes, al día")

    # --- f: el ramal ---------------------------------------------------------------------------------

    def test_f_the_brought_branch_follows_its_road_and_rests_on_it_again(self) -> None:
        """RF-015-18, RF-015-04, RF-017-03, D-13: con su pista ya calculada en V02, «Calcular…» el ramal traído lo deja **al día y apoyado de nuevo en ella**: su operación consume otra vez
        el eje de la pista (``des_rdx_``) y su superficie, con los mismos papeles, las mismas entradas y **las mismas cifras que en V01**; lo que se apoya en la pista son el ramal (con los mismos
        papeles y los mismos m³ que en V01); sus parámetros no se tocan y V01, tampoco."""
        self.activate(self.v02)
        parameters = self.parameters(self.v02)
        self.assertEqual(self.states(self.v02), {"PLT-001": "current", "RDW-001": "current", "RDW-002": "uncalculated"})
        self.calculated("RDW-002")
        modal = self.start(steps.ROAD, confirm=True)
        self.assertEqual(self.drive(modal)[0], {"FINISHED"})
        self.assertEqual(self.states(self.v02), {"PLT-001": "current", "RDW-001": "current", "RDW-002": "current"})
        self.assertEqual(self.parameters(self.v02), parameters, "calcular el ramal no reescribe sus parámetros")
        there, here = self.v01_ops["RDW-002"], self.operation(self.v02, "RDW-002")
        self.assertEqual(self.inputs_of(here), self.inputs_of(there), "las mismas entradas: el eje de la pista, su superficie y lo demás")
        roles = {role for role, _name in self.inputs_of(here)}
        self.assertTrue({self.dprov.ROAD_AXIS_ROLE, self.dprov.SUPPORTED_ON_ROLE} <= roles, roles)
        for (name, _scope, value), (_name, _again_scope, found) in zip(self.figures_of(there), self.figures_of(here), strict=True):
            self.assertAlmostEqual(found, value, delta=TOLERANCE * max(1.0, abs(value)), msg=name)
        self.assertEqual(self.outputs_of(here), self.outputs_of(there))
        on_road = {row.entity: row for row in self.entities.dependents(self.project, self.v02.uid, "RDW-001")}
        original = {row.entity: row for row in self.entities.dependents(self.project, self.v01.uid, "RDW-001")}
        self.assertEqual(sorted(on_road), ["RDW-002"], "lo que se apoya en la pista es el ramal")
        self.assertEqual(set(on_road["RDW-002"].roles), set(original["RDW-002"].roles))
        self.assertAlmostEqual(on_road["RDW-002"].volume_m3, original["RDW-002"].volume_m3, delta=TOLERANCE * max(1.0, abs(original["RDW-002"].volume_m3)))
        self.assertEqual(self.states(self.v01), {"PLT-001": "current", "RDW-001": "current", "RDW-002": "current", "ACC-001": "current"})
        self.assertEqual({code: self.operation(self.v01, code) for code in CODES}, self.v01_ops, "V01 sigue con lo suyo")
        self.assertEqual(json.loads(self.rows("SELECT value FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? AND key = 'des.road.rdw_002.origin'", self.v02.uid)[0][0]), "RDW-001@20.0")

    # --- z: desactivar ---------------------------------------------------------------------------------

    def test_z_disabling_geoblender_removes_the_commands_and_leaves_no_temporary(self) -> None:
        """Principio 8: desactivar Geoblender quita «Calcular…» y «Pista…» y no deja ningún temporal ni cálculo abierto."""
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, "GEOBLENDER_OT_des_entity_calculate", None))
        self.assertIsNone(getattr(bpy.types, "GEOBLENDER_OT_des_create_road", None))
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.temporaries(), [])


if __name__ == "__main__":
    unittest.main()
