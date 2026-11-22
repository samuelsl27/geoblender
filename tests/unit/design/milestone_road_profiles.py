# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_profiles» (spec 017, T04; plan 017 §8; RNF-017-09): lo que escribe en el proyecto una vez por
prueba y suma más de 1 s. El «verde» deja en ``test_road_profiles`` lo puro (los derivados y las comprobaciones del perfil, y el código del
nombre) y, hasta la T48, dejaba también lo que cubre cada RF sobre un proyecto (la tabla, crear, renombrar, completar, la obsolescencia y
cada rechazo), que desde la T48 es el hito ``milestone_road_profiles_operation`` (de donde se importa el proyecto de prueba); esto y aquello
lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación lo pide siempre).

Es lo que no cabe en el presupuesto de ``check.py`` (≤ +3 s para toda la 017, RNF-017-09): el tipo y el origen que elige la
persona, los nombres que dan el mismo código, la **transacción única** (si falla a mitad no queda nada), la declaración que
debe decir quién decide y por qué, un valor «sin confirmar» que se completa (no se duplica), uno ya declarado que no se
sobrescribe, y **cada uno** de los trece valores sin valor y cada rango rechazados sin escribir nada.
"""

from __future__ import annotations

import math
from typing import Any
from unittest import mock

from tests.support.package import import_geoblender
from tests.unit.design.milestone_road_profiles_operation import (
    MAIN,
    OPTIONAL,
    OTHER,
    REQUIRED,
    _RoadProfilesCase,
    _SharedCase,
    declaration,
    new,
    params,
    road_profiles,
)

core_params = import_geoblender("core.params")
versions_model = import_geoblender("core.versions.model")


class CreateVariantsTest(_RoadProfilesCase):
    def test_the_kind_the_origin_the_mesh_factor_and_the_metric_are_the_persons(self) -> None:
        """RF-017-07 (D-2): la persona elige ADOPTADO o HIPÓTESIS y el origen (un documento); con un factor de malla y una
        métrica los escribe también; un tipo que no es ni ADOPTADO ni HIPÓTESIS es un error del programa y no deja nada."""
        self.edit(new(MAIN, mesh_factor=0.95, metric="chamfer5"),
                  declared=declaration(kind="HIPÓTESIS", source_kind="document", source="Estudio de la mina 2026"))
        for field in (*(param.value for param in REQUIRED), *OPTIONAL):
            with self.subTest(field=field):
                record = self.value("pista_principal", field)
                self.assertEqual((record.kind, record.source_kind, record.source),
                                 ("HIPÓTESIS", "document", "Estudio de la mina 2026"))
        self.assertEqual((self.value("pista_principal", "mesh_factor").value, self.value("pista_principal", "metric").value),
                         (0.95, "chamfer5"))
        self.assertEqual(declaration().kind, "ADOPTADO")  # la fuente de un perfil es la ITC o la propiedad (D-2)
        before = self.state()
        for kind in ("MEDIDO", "CALCULADO", "adoptado", ""):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.edit(new(OTHER), declared=declaration(kind=kind))
        self.assertNothing(before)

    def test_a_name_that_looks_like_another_gets_its_own_code(self) -> None:
        """RF-017-07 (D-17): dos nombres que dan el mismo código (``Pista A`` y ``pista-a``) son nombres distintos con
        códigos distintos (``pista_a`` y ``pista_a_2``); el segundo no cambia el primero."""
        made = self.edit(new("Pista A"), new("pista-a"))
        self.assertEqual(made.created, ("pista_a", "pista_a_2"))
        self.assertEqual([(item.code, item.name) for item in self.stored()], [("pista_a", "Pista A"), ("pista_a_2", "pista-a")])
        for code in made.created:
            self.assertEqual(self.value(code, "vehicle_width_m").value, 3.5)

    def test_everything_is_written_in_one_transaction(self) -> None:
        """RF-017-07 (RF-008-01): la fila del perfil y sus parámetros van en la misma transacción; si algo falla a mitad no
        queda ni la tabla, ni la fila, ni ninguno de los parámetros ya escritos: solo la operación, fallida."""
        before = self.state()
        original = core_params.ParameterStore.create
        calls: list[str] = []

        def flaky(store: Any, conn: Any, key: str, *args: Any, **kwargs: Any) -> Any:
            calls.append(key)
            if len(calls) == 16:  # a mitad del segundo perfil
                raise RuntimeError("falla a mitad")
            return original(store, conn, key, *args, **kwargs)

        with mock.patch.object(core_params.ParameterStore, "create", flaky):
            with self.assertRaises(RuntimeError):
                self.edit(new(MAIN), new(OTHER))
        self.assertEqual(len(calls), 16)
        after = self.state()
        self.assertEqual(after["operations"], [(road_profiles.EDIT_ROAD_PROFILES, "failed")])
        self.assertEqual({k: v for k, v in after.items() if k != "operations"},
                         {k: v for k, v in before.items() if k != "operations"})
        self.assertFalse(after["table"])

    def test_the_declaration_must_say_who_decides_and_why(self) -> None:
        """RF-017-07 (RF-008-01, D-2): sin origen, decisor o motivo el parámetro no se escribe (``ParamError``) y no queda
        nada; escribir valores sin declaración, o editar sin nada, es un error del programa (``ValueError``)."""
        before = self.state()
        for changes in ({"decided_by": ""}, {"source": ""}, {"reason": " "}):
            with self.subTest(changes=changes), self.assertRaises(core_params.ParamError):
                self.edit(new(MAIN), declared=declaration(**changes))
            after = self.state()
            self.assertEqual((after["rows"], after["params"], after["table"]), (before["rows"], before["params"], False))
        with self.assertRaises(ValueError):
            self.edit(new(MAIN), declared=None)
        with self.assertRaises(ValueError):
            road_profiles.edit_road_profiles(self.project, (), declaration())

    def test_a_version_that_does_not_exist_leaves_nothing(self) -> None:
        """RF-017-07 (RF-009-24): un perfil que se **crea** en una versión que no existe falla dentro de la transacción (la
        operación queda fallida y no queda tabla, fila ni parámetro), y uno que se **completa** en ella se rechaza antes de
        registrar nada (al leer los valores efectivos del ámbito: ni siquiera una operación fallida); en los dos, el
        ``VersionError`` de la 009."""
        before = self.state()
        with self.assertRaises(versions_model.VersionError):
            self.edit(new(MAIN), declared=declaration(version="V99"))
        after = self.state()
        self.assertEqual(after["operations"], [(road_profiles.EDIT_ROAD_PROFILES, "failed")])
        self.assertEqual({k: v for k, v in after.items() if k != "operations"},
                         {k: v for k, v in before.items() if k != "operations"})
        self.edit(new(MAIN))
        before = self.state()
        with self.assertRaises(versions_model.VersionError):
            self.edit(road_profiles.ProfileEdit(code="pista_principal", values={"mesh_factor": 0.9}),
                      declared=declaration(version="V99"))
        self.assertNothing(before)

    def test_a_value_left_empty_is_filled_not_duplicated(self) -> None:
        """RF-017-07 (RF-008-04): un valor que el proyecto tiene vacío «sin confirmar» (lo deja una operación que lo pidió
        antes de que nadie lo declarara) se completa cambiándolo, no con un alta que fallaría: queda con su valor, ya
        confirmado, en la revisión 2 con una fila ``change``."""
        key = params.road_profile_key("acceso_tajo", "reach_m")
        with self.project.write_transaction() as conn:
            empty = self.store.ensure_default(conn, key, geoblender_version="0.1.0")
        self.assertIsNone(empty.value)
        self.assertTrue(empty.unconfirmed)
        self.edit(new(OTHER))
        record = self.value("acceso_tajo", "reach_m")
        self.assertEqual((record.value, record.unconfirmed, record.rev, record.kind), (60.0, False, 2, "ADOPTADO"))
        self.assertEqual([entry.action.value for entry in self.store.history(key)], ["default", "change"])
        self.assertEqual(self.value("acceso_tajo", "berm_m").rev, 1)

    def test_a_value_already_declared_is_not_overwritten(self) -> None:
        """RF-017-07: completar un valor que ya tiene el ámbito se rechaza con el ``ParamError`` ``core.param_exists``
        (cambiarlo es de «Parámetros»), y no queda nada de lo demás de la llamada, ni siquiera un perfil nuevo."""
        self.edit(new(MAIN))
        before = self.state()
        with self.assertRaises(core_params.ParamError) as caught:
            self.edit(new(OTHER), road_profiles.ProfileEdit(code="pista_principal", values={"mesh_factor": 0.9, "reach_m": 70.0}))
        self.assertEqual(caught.exception.code, "core.param_exists")
        after = self.state()
        self.assertEqual(after["operations"][-1], (road_profiles.EDIT_ROAD_PROFILES, "failed"))
        self.assertEqual({k: v for k, v in after.items() if k != "operations"},
                         {k: v for k, v in before.items() if k != "operations"})
        self.assertEqual(self.value("pista_principal", "reach_m").value, 60.0)


class EveryFieldRejectedTest(_SharedCase):
    """RF-017-04, RF-017-07: **cada uno** de los trece valores sin valor y cada rango, rechazados con su campo y su valor, sin
    escribir nada (el «verde» prueba una muestra de cada clase y las comprobaciones de ``RoadProfile`` y de ``params`` cubren
    todos sin proyecto)."""

    def test_each_of_the_thirteen_values_is_required(self) -> None:
        """RF-017-04, RF-017-07 (D-2): sin cada uno de los trece valores (que falte o sea ``None``), y con la clase en blanco,
        ``des.road_profile_value_missing`` nombrando el perfil, la clave del campo y el valor."""
        for param in REQUIRED:
            with self.subTest(field=param.value):
                error = self.reject(new("Tercera", **{param.value: None}))
                self.assertEqual((error.code, error.field, error.value),
                                 ("des.road_profile_value_missing", f"des.roadprofile.tercera.{param.value}", None))
                self.assertEqual(error.obj, "Perfil de pista «Tercera»")
                self.assertIn("«Tercera»", error.text)

    def test_each_range_is_checked(self) -> None:
        """RF-017-04, RF-017-07: A, f, pd, w, pm, R y Rmín > 0, arcén y caballón ≥ 0, los ángulos de (0; 90)°, el alcance > 0 y el
        factor de malla de (0; 1], fuera de su rango, un NaN y el infinito: ``des.road_profile_value_range`` nombrando el
        perfil, la clave del campo y el valor."""
        bad = (("vehicle_width_m", 0.0), ("vehicle_width_m", -3.5), ("lane_factor", 0.0), ("shoulder_m", -0.001),
               ("berm_m", -1.0), ("max_gradient_pct", 0.0), ("station_step_m", 0.0), ("max_mean_gradient_pct", -1.0),
               ("curve_radius_m", 0.0), ("min_radius_m", 0.0), ("cut_angle_deg", 0.0), ("cut_angle_deg", 90.0),
               ("fill_angle_deg", 0.0), ("fill_angle_deg", 95.0), ("reach_m", 0.0), ("mesh_factor", 0.0), ("mesh_factor", 1.5),
               ("vehicle_width_m", math.nan), ("reach_m", math.inf), ("metric", "chamfer7"))
        for field, value in bad:
            with self.subTest(field=field, value=value):
                error = self.reject(new("Tercera", **{field: value}))
                self.assertEqual((error.code, error.field), ("des.road_profile_value_range", f"des.roadprofile.tercera.{field}"))
                self.assertIn("«Tercera»", error.text)
                if isinstance(value, float) and math.isfinite(value):
                    self.assertEqual(error.value, value)
