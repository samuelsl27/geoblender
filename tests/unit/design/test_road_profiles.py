# SPDX-License-Identifier: GPL-3.0-or-later
"""El perfil de pista (spec 017, T04; HU-017-1; RF-017-04, RF-017-07, RF-017-08; plan 017 §5.1, §5.2.2, §5.3.1 y §5.7 P-2;
ADR-0027; RF-008-01, RF-009-24).

Un perfil de pista son **dos cosas**, como el de banco de la 013 (``test_profiles.py``, de donde se copia la mecánica, no se
generaliza: P-2): su fila en la tabla del proyecto ``des_road_profile`` (``code``, ``name``, quién y cuándo; ni un valor)
y sus quince valores, que son parámetros de ``core.params`` (familias ``des.roadprofile.{p}.…``, :mod:`design.params`)
con su tipo, origen, decisor e historial: el ``code`` (``[a-z][a-z0-9_]*``) sale del nombre al crear el perfil y **no
cambia nunca**; el ``name`` (``PISTA_PRINCIPAL``) es libre y único sin distinguir mayúsculas. La operación de proyecto
``des.edit_road_profiles`` (declarada en ``provenance``; no se repite sola) crea, completa y renombra perfiles en **una**
transacción; todo se mira **antes** de escribir (un perfil sin nombre, con el nombre de otro, incompleto, con un valor
fuera de su rango o con un radio mínimo menor que la semianchura de su sección se rechaza nombrando el perfil, el campo y
el valor, sin registrar nada: RF-017-04, RF-017-07).

Los derivados (RF-017-08) —la calzada f·A, la anchura de la sección, su semianchura y la longitud mínima H/pd— **no son
parámetros** y salen con error ≤ 10⁻⁹ relativo; el cálculo a mano está hecho aquí con ``decimal`` (70 cifras) y no usa el
código de ``design``. Los valores de referencia de IMGA (``road_data.PROFILE``) son **solo de las pruebas**.
"""

from __future__ import annotations

import dataclasses
import json
import math
import sqlite3
import unittest
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

provenance = import_geoblender("design.provenance")
params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
road_profiles = import_geoblender("design.road_profiles")
core_params = import_geoblender("core.params")
registry = import_geoblender("core.datasets.registry")
versions_read = import_geoblender("core.versions.read")
operations = import_geoblender("core.provenance.operations")
i18n = import_geoblender("core.i18n")

Param = params.RoadProfileParam
MAIN, OTHER = "PISTA_PRINCIPAL", "ACCESO_TAJO"
NOBODY = "Samuel (IMGA)"
OPTIONAL = ("mesh_factor", "metric")
"""Los dos valores con valor por defecto (D-2): el resto de los 15 se declara siempre al crear."""


def values_of(data: Any = rd.PROFILE, **changes: object) -> dict[str, object]:
    """Los quince valores de ``data`` (``road_data.ProfileData``) por último segmento de su clave (la clase es ``class``),
    con ``changes`` encima."""
    found: dict[str, object] = {
        param.value: getattr(data, "class_name" if param is Param.CLASS else param.value) for param in Param}
    found.update(changes)
    return found


def profile_of(code: str = "pista_principal", name: str = MAIN, **changes: object) -> Any:
    """El ``RoadProfile`` de referencia con ``changes`` encima."""
    return road_profiles.RoadProfile.from_values(code, name, values_of(**changes))


# --- Los derivados (RF-017-08) y el perfil como dato -----------------------------------------------------------------

# Cálculo a mano (Decimal, 70 cifras): (A, f, arcén, caballón, pd %, H) → (calzada f·A, sección, semianchura, H/pd).
HAND = {
    ("3.5", "3", "0", "1", "10", "30"): ("10.5", "11.5", "5.75", "300"),  # el de la spec: RF-017-08
    ("3.2", "2.5", "0.7", "1.1", "8.25", "17.3"): ("8.0", "9.8", "4.9", "209.696969696969696969696969696969696969"),
    ("4.2", "2", "0.5", "1.5", "12.5", "9.1"): ("8.4", "10.4", "5.2", "72.8"),
    ("2.55", "3.3", "0.35", "0.15", "7", "0"): ("8.415", "8.915", "4.4575", "0"),
}


def relative(found: float, expected: str) -> Decimal:
    """El error relativo de ``found`` frente al valor exacto ``expected`` (a 70 cifras; el error absoluto si es 0)."""
    with localcontext() as context:
        context.prec = 70
        exact = Decimal(expected)
        if exact == 0:
            return abs(Decimal(found))
        return abs(Decimal(found) - exact) / abs(exact)


class DerivedValuesTest(unittest.TestCase):
    def test_the_derived_values_of_the_reference_profile(self) -> None:
        """RF-017-08 (CE de la spec §11): con A = 3,5 m, f = 3, arcén 0 m y caballón 1 m la calzada es 10,5 m, la sección
        11,5 m y su semianchura 5,75 m, y con pd = 10 % y un desnivel de 30 m la longitud mínima es 300 m."""
        found = road_profiles.derived(profile_of())
        self.assertIsInstance(found, road_profiles.RoadDerived)
        self.assertEqual((found.carriageway_m, found.section_m, found.half_width_m), (10.5, 11.5, 5.75))
        self.assertEqual(found.min_length_m(30.0), 300.0)
        self.assertEqual(found.max_gradient_pct, 10.0)

    def test_the_derived_values_against_a_hand_calculation(self) -> None:
        """RF-017-08: la calzada, la sección, la semianchura y H/pd de varios perfiles coinciden con el cálculo a mano de 70
        cifras con error ≤ 10⁻⁹ relativo (también un desnivel nulo)."""
        for (a, f, arc, cab, pd, drop), (carriageway, section, half, length) in HAND.items():
            with self.subTest(vehicle=a, factor=f, gradient=pd):
                profile = profile_of(vehicle_width_m=float(a), lane_factor=float(f), shoulder_m=float(arc),
                                     berm_m=float(cab), max_gradient_pct=float(pd))
                found = road_profiles.derived(profile)
                self.assertLessEqual(relative(found.carriageway_m, carriageway), Decimal("1e-9"))
                self.assertLessEqual(relative(found.section_m, section), Decimal("1e-9"))
                self.assertLessEqual(relative(found.half_width_m, half), Decimal("1e-9"))
                self.assertLessEqual(relative(found.min_length_m(float(drop)), length), Decimal("1e-9"))

    def test_the_semi_width_is_the_one_that_limits_the_minimum_radius(self) -> None:
        """RF-017-04, RF-017-08: la semianchura derivada es la de ``params.road_half_width_m`` (una sola fuente: la que
        limita el radio mínimo) y la sección es la calzada más el arcén y el caballón."""
        profile = profile_of(shoulder_m=0.5, berm_m=1.5)
        found = road_profiles.derived(profile)
        self.assertEqual(found.half_width_m, params.road_half_width_m(3.5, 3.0, 0.5, 1.5))
        self.assertEqual(found.section_m, found.carriageway_m + 0.5 + 1.5)
        self.assertEqual(found.half_width_m, found.section_m / 2.0)

    def test_the_length_needs_a_finite_number_and_uses_the_magnitude(self) -> None:
        """RF-017-08: la longitud mínima para salvar un desnivel es la del desnivel en valor absoluto (subir o bajar
        cuesta lo mismo); un valor que no es un número real finito es un error del programa (``TypeError`` si no es un
        número, ``ValueError`` si es NaN o infinito)."""
        found = road_profiles.derived(profile_of())
        self.assertEqual(found.min_length_m(-30.0), 300.0)
        self.assertEqual(found.min_length_m(0), 0.0)
        self.assertEqual(found.min_length_m(30), 300.0)
        for bad in ("30", None, True, [1.0]):
            with self.subTest(value=bad), self.assertRaises(TypeError):
                found.min_length_m(bad)  # type: ignore[arg-type]
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                found.min_length_m(bad)

    def test_derived_values_are_not_parameters(self) -> None:
        """RF-017-08: la calzada, la sección, la semianchura y H/pd no son campos ni parámetros del perfil (no se guardan
        ni se pueden fijar: se derivan); el perfil y lo derivado son inmutables y los quince campos de valor son los de
        las familias ``des.roadprofile.{p}.*`` (la clase normativa es ``class_name``)."""
        profile = profile_of()
        fields = [field.name for field in dataclasses.fields(profile)]
        self.assertEqual(fields[:2], ["code", "name"])
        self.assertEqual([("class" if name == "class_name" else name) for name in fields[2:]],
                         [str(param) for param in Param])
        for name in ("carriageway_m", "section_m", "half_width_m", "min_length_m", "derived"):
            self.assertNotIn(name, dataclasses.asdict(profile))
        for name in ("code", "vehicle_width_m", "carriageway_m"):
            with self.subTest(name=name), self.assertRaises((AttributeError, TypeError)):
                setattr(profile, name, 1.0)
        found = road_profiles.derived(profile)
        with self.assertRaises((AttributeError, TypeError)):
            found.carriageway_m = 1.0  # type: ignore[misc]
        self.assertEqual(profile, profile_of())

    def test_defaults_and_float64(self) -> None:
        """RF-017-07 (D-2; regla 4: float64): sin factor de malla ni métrica toma 1,0 y la exacta (los únicos valores por
        defecto del perfil); los enteros se guardan como ``float`` y la clase, sin los espacios de los extremos."""
        profile = profile_of(mesh_factor=None, metric=None)
        self.assertEqual((profile.mesh_factor, profile.metric), (1.0, "exact"))
        whole = profile_of(vehicle_width_m=4, lane_factor=2, shoulder_m=0, berm_m=1, max_gradient_pct=10,
                           station_step_m=1, max_mean_gradient_pct=10, curve_radius_m=20, min_radius_m=12,
                           cut_angle_deg=60, fill_angle_deg=35, reach_m=60, mesh_factor=1,
                           **{"class": "  Pista de acceso "})
        for param in Param:
            if param.value not in ("class", "metric"):
                self.assertIs(type(getattr(whole, param.value)), float, param.value)
        self.assertEqual(whole.class_name, "Pista de acceso")


class ProfileChecksTest(unittest.TestCase):
    """Un ``RoadProfile`` no se crea con un valor fuera de su rango, sin valor, con un radio que no cabe o sin nombre: nada se
    calcula con él (RF-017-04, RF-017-07)."""

    def rejected(self, **changes: object) -> Any:
        with self.assertRaises(messages.DesignError) as caught:
            profile_of(**changes)
        return caught.exception

    def test_every_range_names_the_profile_the_field_and_the_value(self) -> None:
        """RF-017-04, RF-017-07: A, f, pd, w, pm, R y Rmín > 0, arcén y caballón ≥ 0, los ángulos de (0; 90)°, el alcance > 0 y
        el factor de malla de (0; 1] se rechazan fuera de su rango con ``des.road_profile_value_range`` nombrando el
        perfil por su nombre, la clave del campo y el valor; la métrica, fuera de sus opciones."""
        bad = (("vehicle_width_m", 0.0), ("vehicle_width_m", -3.5), ("lane_factor", 0.0), ("shoulder_m", -0.001),
               ("berm_m", -1.0), ("max_gradient_pct", 0.0), ("station_step_m", 0.0), ("max_mean_gradient_pct", -1.0),
               ("curve_radius_m", 0.0), ("min_radius_m", 0.0), ("cut_angle_deg", 0.0), ("cut_angle_deg", 90.0),
               ("fill_angle_deg", 95.0), ("reach_m", 0.0), ("mesh_factor", 0.0), ("mesh_factor", 1.5),
               ("vehicle_width_m", math.nan), ("reach_m", math.inf), ("metric", "chamfer7"))
        for field, value in bad:
            with self.subTest(field=field, value=value):
                error = self.rejected(**{field: value})
                self.assertEqual(error.code, "des.road_profile_value_range")
                self.assertEqual(error.field, f"des.roadprofile.pista_principal.{field}")
                self.assertEqual(error.obj, "Perfil de pista «PISTA_PRINCIPAL»")
                self.assertIn("«PISTA_PRINCIPAL»", error.text)
                self.assertIn(error.field, error.text)
                if isinstance(value, float) and math.isfinite(value):
                    self.assertEqual(error.value, value)
        for field, value in (("shoulder_m", 0.0), ("berm_m", 0.0), ("mesh_factor", 1.0), ("cut_angle_deg", 89.999),
                             ("reach_m", 0.001)):
            with self.subTest(field=field, value=value):  # los extremos incluidos valen
                self.assertEqual(getattr(profile_of(**{field: value}), field), value)

    def test_a_value_without_value_is_rejected_and_nothing_is_chosen(self) -> None:
        """RF-017-04 (un perfil incompleto), D-2 (sin valor por defecto): cada uno de los trece valores sin valor (``None``;
        la clase, también en blanco) se rechaza con ``des.road_profile_value_missing`` nombrando el perfil y el campo; solo
        el factor de malla y la métrica toman el valor de siempre."""
        for param in Param:
            if param.value in OPTIONAL:
                continue
            for value in ((None, "  ") if param is Param.CLASS else (None,)):
                with self.subTest(field=param.value, value=value):
                    error = self.rejected(**{param.value: value})
                    self.assertEqual((error.code, error.field, error.value),
                                     ("des.road_profile_value_missing", f"des.roadprofile.pista_principal.{param.value}",
                                      None))
                    self.assertIn("«PISTA_PRINCIPAL»", error.text)
                    self.assertIn("Perfil de pista…", error.text)
        for name in OPTIONAL:
            with self.subTest(default=name):
                self.assertEqual(getattr(profile_of(**{name: None}), name), {"mesh_factor": 1.0, "metric": "exact"}[name])

    def test_the_minimum_radius_must_fit_the_curve_and_the_section(self) -> None:
        """RF-017-04, RF-017-07: ``Rmín`` mayor que ``R`` (``des.road_profile_radius_order``) y ``Rmín`` menor que la
        semianchura de la sección (``des.road_profile_radius_narrow``: el borde interior de una curva se plegaría) se
        rechazan nombrando el perfil, el campo del radio mínimo y su valor; ``Rmín`` igual a la semianchura (5,75 m) vale, y
        con una sección más ancha el mínimo sube con ella."""
        error = self.rejected(min_radius_m=21.0)
        self.assertEqual((error.code, error.field, error.value),
                         ("des.road_profile_radius_order", "des.roadprofile.pista_principal.min_radius_m", 21.0))
        error = self.rejected(min_radius_m=5.0)
        self.assertEqual((error.code, error.field, error.value),
                         ("des.road_profile_radius_narrow", "des.roadprofile.pista_principal.min_radius_m", 5.0))
        self.assertIn("«PISTA_PRINCIPAL»", error.text)
        self.assertEqual(profile_of(min_radius_m=5.75).min_radius_m, 5.75)
        self.assertEqual(self.rejected(min_radius_m=5.75, berm_m=3.0).code, "des.road_profile_radius_narrow")  # semianchura 6,75 m
        self.assertEqual(self.rejected(curve_radius_m=10.0).code, "des.road_profile_radius_order")  # Rmín 12 > R 10
        self.assertEqual(profile_of(min_radius_m=6.75, berm_m=3.0).min_radius_m, 6.75)

    def test_a_profile_without_a_name_or_with_a_wrong_code(self) -> None:
        """RF-017-04, RF-017-07: un nombre vacío o de espacios se rechaza con ``des.road_profile_name_missing`` (nombrando el
        perfil por su código); un nombre que no es un texto, un valor que no es un número real o un código que no es
        ``[a-z][a-z0-9_]*`` son errores del programa."""
        for name in ("", "   ", "\t"):
            with self.subTest(name=name):
                with self.assertRaises(messages.DesignError) as caught:
                    profile_of(name=name)
                self.assertEqual((caught.exception.code, caught.exception.field), ("des.road_profile_name_missing", "name"))
                self.assertIn("«pista_principal»", caught.exception.text)
        with self.assertRaises(TypeError):
            profile_of(name=None)  # type: ignore[arg-type]
        for code in ("", "Pista", "1pista", "pista principal", "pista.1", "pístá"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                profile_of(code=code)
        for field, value in (("vehicle_width_m", True), ("lane_factor", "3"), ("reach_m", [60.0]), ("class", 3)):
            with self.subTest(field=field), self.assertRaises(TypeError):
                profile_of(**{field: value})
        with self.assertRaises(ValueError):
            road_profiles.RoadProfile.from_values("pista", "Pista", {**values_of(), "protect": 1.0})  # no es de un perfil

    def test_the_profiles_built_from_the_resolved_values(self) -> None:
        """RF-017-07, RF-017-04: ``road_profiles_from`` arma los perfiles de unos códigos con los valores que resuelve el
        cálculo (clave ``des.roadprofile.{p}.…`` → valor), con el nombre de la tabla (o el código si no se da) y sin
        repetir; un valor que falta, o fuera de rango, es el rechazo del perfil nombrándolo por su nombre."""
        resolved = {params.road_profile_key(code, last): value
                    for code in ("pista_principal", "acceso_tajo") for last, value in values_of().items()}
        found = road_profiles.road_profiles_from(resolved, ["pista_principal", "acceso_tajo", "pista_principal"],
                                                 {"pista_principal": MAIN})
        self.assertEqual(list(found), ["pista_principal", "acceso_tajo"])
        self.assertEqual((found["pista_principal"].name, found["acceso_tajo"].name), (MAIN, "acceso_tajo"))
        self.assertEqual(found["pista_principal"], profile_of())
        del resolved["des.roadprofile.acceso_tajo.reach_m"]
        with self.assertRaises(messages.DesignError) as caught:
            road_profiles.road_profiles_from(resolved, ["acceso_tajo"], {"acceso_tajo": OTHER})
        self.assertEqual((caught.exception.code, caught.exception.field),
                         ("des.road_profile_value_missing", "des.roadprofile.acceso_tajo.reach_m"))
        self.assertIn("«ACCESO_TAJO»", caught.exception.text)

    def test_the_names_of_the_profiles_must_be_different(self) -> None:
        """RF-017-04: un perfil que repite el nombre de otro (sin distinguir mayúsculas ni espacios en los bordes) se rechaza
        con ``des.road_profile_name_repeated`` nombrando los dos; dos con el mismo código son un error del programa."""
        first, second = profile_of(), profile_of("acceso_tajo", OTHER)
        road_profiles.check_names([first, second])
        road_profiles.check_names([])
        for repeated in (profile_of("otro", MAIN), profile_of("otro", "pista_principal"), profile_of("otro", " pista_PRINCIPAL ")):
            with self.subTest(name=repeated.name), self.assertRaises(messages.DesignError) as caught:
                road_profiles.check_names([first, second, repeated])
            error = caught.exception
            self.assertEqual((error.code, error.field), ("des.road_profile_name_repeated", "name"))
            self.assertIn("«otro»", error.text)
            self.assertIn("«pista_principal»", error.text)
        with self.assertRaises(ValueError):
            road_profiles.check_names([first, profile_of(name="Otro nombre")])


class CodeTest(unittest.TestCase):
    def test_the_code_is_the_ascii_name_in_lowercase(self) -> None:
        """RF-017-07 (D-17 de la 013): el código es el nombre en ASCII y en minúsculas, sin tildes y con «_» en lugar de lo
        demás (``PISTA_PRINCIPAL`` da ``pista_principal``); sin letra delante lleva ``p_`` y sin nada, ``p``; si el del
        nombre ya es de otro perfil se le pone ``_2``, ``_3``… y dura como mucho 32 caracteres."""
        cases = {MAIN: "pista_principal", "Acceso al tajo": "acceso_al_tajo", "Rampa 2 (norte)": "rampa_2_norte", "10-60": "p_10_60",
                 "": "p", "¡¿?!": "p"}
        for name, code in cases.items():
            with self.subTest(name=name):
                self.assertEqual(road_profiles.profile_code(name, ()), code)
                self.assertTrue(params.is_code(code))
        self.assertEqual(road_profiles.profile_code(MAIN, {"pista_principal"}), "pista_principal_2")
        self.assertEqual(road_profiles.profile_code("pista principal", {"pista_principal", "pista_principal_2"}),
                         "pista_principal_3")
        long = "perfil de pista con un nombre larguisimo de acceso al tajo"
        code = road_profiles.profile_code(long, ())
        self.assertLessEqual(len(code), 32)
        again = road_profiles.profile_code(long, {code})
        self.assertNotEqual(again, code)
        self.assertLessEqual(len(again), 32)


# --- La tabla del proyecto y la operación que edita los perfiles ------------------------------------------------------

REQUIRED = tuple(param for param in Param if param.value not in OPTIONAL)


def declaration(**changes: Any) -> Any:
    """Lo que declara la persona de los valores que escribe (origen, decisor y motivo)."""
    base: dict[str, Any] = {"source": "ITC 07.1.03 de la prueba", "decided_by": NOBODY, "reason": "Perfil de la spec 017"}
    return road_profiles.ProfileDeclaration(**{**base, **changes})


def new(name: str, **changes: Any) -> Any:
    """Un perfil nuevo con los trece valores de referencia (sin el factor de malla ni la métrica), con ``changes`` encima;
    con ``None`` en un valor, ese valor se quita."""
    values = {**{key: value for key, value in values_of().items() if key not in OPTIONAL}, **changes}
    return road_profiles.ProfileEdit(name=name, values={key: value for key, value in values.items() if value is not None})


class _RoadProfilesCase(dfx.DesignProjectCase):
    """El proyecto del diseño (una copia **por prueba**: estas pruebas escriben), con la familia del perfil de pista y las
    operaciones registradas (lo hará ``bl``)."""

    @classmethod
    def setUpClass(cls) -> None:
        dfx.project_template()  # la plantilla, antes de registrar lo de la 012 (T05)
        cls.enterClassContext(cp.constraints_registered())
        core_params.register_families(params.ROAD_PROFILE_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        never = provenance.operation_def(provenance.ROAD, lambda request: None)  # la que lee los perfiles al probar la obsolescencia
        cls.enterClassContext(registered(*road_profiles.OPERATIONS, never))

    def setUp(self) -> None:
        self.project, self.clock = self.enterContext(dfx.open_design_project("gb-rp-"))
        self.root = Path(self.project.root)
        with self.project.read() as conn:
            self.v1, self.v2 = (versions_read.version(conn, uid) for uid in dfx.project_template()["versions"])
        self.store = core_params.ParameterStore(self.project)

    def edit(self, *edits: Any, declared: Any = ...) -> Any:
        """Edita los perfiles un minuto después, con la declaración de ``declaration()``."""
        self.clock.advance(minutes=1)
        return road_profiles.edit_road_profiles(self.project, edits, declaration() if declared is ... else declared)

    def state(self) -> dict[str, Any]:
        """Lo que hay de los perfiles en el proyecto: operaciones, tabla y sus filas, datos y las filas de parámetros."""
        with self.project.read() as conn:
            made = conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (road_profiles.TABLE,)).fetchone() is not None
            return {
                "operations": conn.execute("SELECT op_type, status FROM gb_operation WHERE op_type LIKE 'des.%' "
                                           "ORDER BY fid").fetchall(),
                "table": made,
                "rows": conn.execute(f"SELECT code, name FROM {road_profiles.TABLE} ORDER BY fid").fetchall() if made else None,
                "datasets": conn.execute("SELECT name FROM gb_dataset WHERE name LIKE 'des\\_%' ESCAPE '\\'").fetchall(),
                "params": conn.execute("SELECT key, scope_uid, rev FROM gb_parameter WHERE key LIKE 'des.roadprofile.%' "
                                       "ORDER BY key, scope_uid").fetchall(),
            }

    def stored(self) -> tuple[Any, ...]:
        with self.project.read() as conn:
            return road_profiles.read_profiles(conn)

    def value(self, code: str, field: str, version: Any = None) -> Any:
        """La fila del valor ``field`` del perfil ``code`` en el proyecto o en la versión."""
        return self.store.get(params.road_profile_key(code, field), version=version)

    def resolved(self, codes: list[str], version: Any = None) -> dict[str, Any]:
        """Clave → valor que resuelven los cálculos para esos perfiles (la versión y, si no, el proyecto o el valor por
        defecto de su definición)."""
        keys = [params.road_profile_key(code, param) for code in codes for param in Param]
        chain = ("version", "project") if version is not None else ("project",)
        with self.project.read() as conn:
            found = self.store.resolve_many(conn, keys, chain, version=version)
        values: dict[str, Any] = {}
        for key in keys:
            if key in found:
                text = found[key].value_json
                values[key] = None if text is None else json.loads(text)
            else:
                values[key] = core_params.definition(key).default
        return values

    def assertNothing(self, before: dict[str, Any]) -> None:  # noqa: N802
        """Que no se ha registrado nada desde ``before``: ni operación (ni fallida), ni tabla, ni fila, ni dato, ni parámetro."""
        self.assertEqual(self.state(), before)


class _SharedCase(_RoadProfilesCase):
    """Una copia del proyecto **por clase** con ``PISTA_PRINCIPAL`` y ``ACCESO_TAJO`` ya creados (en el proyecto), para las
    pruebas que solo rechazan (no escriben nada: :meth:`reject` lo comprueba) y las que escriben **perfiles propios** con
    nombres que no repite ninguna otra (cada prueba mira lo suyo: el orden no importa)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.project, cls.clock = cls.enterClassContext(dfx.open_design_project("gb-rp-"))
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in dfx.project_template()["versions"])
        cls.store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(cls.project, (new(MAIN), new(OTHER)), declaration())

    def setUp(self) -> None:
        pass  # el proyecto es el de la clase

    def reject(self, *edits: Any, **kw: Any) -> Any:
        """La edición se rechaza con un ``DesignError`` y no deja nada, ni una operación fallida."""
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            self.edit(*edits, **kw)
        self.assertNothing(before)
        return caught.exception


class TableTest(_RoadProfilesCase):
    def test_the_first_profile_creates_the_table_and_the_next_reuses_it(self) -> None:
        """RF-017-07 (plan §5.2.1 y P-2): sin perfiles no hay tabla (ni perfiles ni nombres, sin error); la tabla
        ``des_road_profile`` (``fid``, ``uid``, ``code``, ``name``, ``created_by``, ``created_at``, con su código y su nombre
        **únicos**) se crea en la transacción del primer perfil, en ``gpkg_contents`` como tabla de atributos, y se registra
        como dato del proyecto de ``des``, leído con ``core.gpkg_layer@1``, no editable en QGIS y salida de la operación; la
        segunda edición añade filas sin tocar las primeras y se registra en el mismo dato; los perfiles salen en el orden en
        que se crearon."""
        self.assertFalse(self.state()["table"])
        with self.project.read() as conn:
            self.assertEqual((road_profiles.read_profiles(conn), road_profiles.profile_names(conn)), ((), {}))
        made = self.edit(new(MAIN))
        with self.project.read() as conn:
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({road_profiles.TABLE})")]
            contents = conn.execute("SELECT data_type, identifier FROM gpkg_contents WHERE table_name = ?",
                                    (road_profiles.TABLE,)).fetchone()
            record = registry.get(conn, road_profiles.TABLE)
            roles = conn.execute("SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out'",
                                 (made.operation_uid,)).fetchall()
            titles = dict(conn.execute("SELECT column_name, title FROM gpkg_data_columns WHERE table_name = ?",
                                       (road_profiles.TABLE,)).fetchall())
            unique = set()
            for _seq, index, is_unique, *_rest in conn.execute(f"PRAGMA index_list({road_profiles.TABLE})").fetchall():
                if is_unique:
                    unique.add(tuple(row[2] for row in conn.execute(f"PRAGMA index_info({index})")))
            ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (road_profiles.TABLE,)).fetchone()[0]
        self.assertEqual(columns, ["fid", "uid", "code", "name", "created_by", "created_at"])
        self.assertEqual(titles, {"uid": "Identificador", "code": "Código", "name": "Nombre", "created_by": "Creado por",
                                  "created_at": "Creado el"})
        self.assertEqual(contents, ("attributes", "Perfiles de pista"))
        self.assertEqual((record.module, record.kind, record.locator, record.reader, record.qgis_editable, record.status.value),
                         ("des", "table", road_profiles.TABLE, "core.gpkg_layer@1", False, "current"))
        self.assertEqual(record.operation_uid, made.operation_uid)
        self.assertEqual(roles, [(road_profiles.PROFILES_ROLE,)])
        self.assertEqual(self.state()["datasets"], [(road_profiles.TABLE,)])
        self.assertEqual(unique, {("uid",), ("code",), ("name",)})
        copy = sqlite3.connect(":memory:")  # una copia en memoria: en el proyecto, un fallo de escritura lo deja en solo lectura
        self.addCleanup(copy.close)
        copy.execute(ddl)
        insert = (f"INSERT INTO {road_profiles.TABLE} (uid, code, name, created_by, created_at) "
                  "VALUES (?, ?, ?, 'x', '2026-11-20T10:00:00Z')")
        copy.execute(insert, ("u1", "pista_principal", MAIN))
        for uid, code, name in (("u2", "pista_principal", "Otro"), ("u3", "otro", MAIN), ("u1", "otro", "Otro")):
            with self.subTest(code=code, name=name), self.assertRaises(sqlite3.IntegrityError):
                copy.execute(insert, (uid, code, name))
        (first,) = self.stored()
        second = self.edit(new(OTHER))
        after = self.stored()
        self.assertEqual(after[0], first)
        self.assertEqual([item.code for item in after], ["pista_principal", "acceso_tajo"])
        self.assertNotEqual(made.operation_uid, second.operation_uid)
        with self.project.read() as conn:
            self.assertEqual(registry.get(conn, road_profiles.TABLE).operation_uid, second.operation_uid)
            self.assertEqual(road_profiles.profile_names(conn), {"pista_principal": MAIN, "acceso_tajo": OTHER})


class OperationTest(_SharedCase):
    def test_a_profile_is_a_row_and_thirteen_created_parameters(self) -> None:
        """RF-017-07, RF-017-08 (D-2; RF-008-01; plan §5.2.2): crear un perfil escribe su fila (código fijado del nombre,
        quién y cuándo) y los trece valores que se declaran siempre como parámetros ADOPTADO con su fuente, su decisor y su
        motivo, con una fila ``create`` en el historial, con la unidad de su familia y sin «sin confirmar»; el factor de
        malla y la métrica no se escriben (valen 1,0 y la exacta por su definición); dos perfiles en una llamada son
        **una** operación de proyecto, ``des.edit_road_profiles``, y con lo escrito los cálculos arman los mismos perfiles
        (con el nombre de la tabla) y sus derivados."""
        before = self.state()
        made = self.edit(new("Pista nueva"), new("Acceso nuevo", vehicle_width_m=2.5, lane_factor=2.0, berm_m=0.5,
                                                **{"class": "Acceso al tajo"}))
        self.assertEqual((made.created, made.renamed, made.completed), (("pista_nueva", "acceso_nuevo"), (), ()))
        self.assertEqual(self.state()["operations"], [*before["operations"], (road_profiles.EDIT_ROAD_PROFILES, "done")])
        (operation,) = road_profiles.OPERATIONS
        self.assertEqual((operation.op_type, operation.scope, operation.repeatable), ("des.edit_road_profiles", "project", False))
        row = {item.code: item for item in self.stored()}["pista_nueva"]
        self.assertEqual((row.name, row.created_by), ("Pista nueva", self.project.session.user_host))
        with self.project.read() as conn:
            started = conn.execute("SELECT started_at FROM gb_operation WHERE uid = ?", (made.operation_uid,)).fetchone()[0]
        self.assertEqual(row.created_at, started)
        expected = values_of()
        for param in REQUIRED:
            with self.subTest(field=param.value):
                record = self.value(row.code, param)
                self.assertEqual(record.value, expected[param.value])
                self.assertEqual((record.kind, record.source_kind, record.source),
                                 ("ADOPTADO", "person", "ITC 07.1.03 de la prueba"))
                self.assertEqual((record.decided_by, record.reason, record.unconfirmed), (NOBODY, "Perfil de la spec 017", False))
                self.assertEqual((record.scope, record.scope_uid, record.rev), ("project", "", 1))
                history = self.store.history(params.road_profile_key(row.code, param))
                self.assertEqual([(entry.rev, entry.action.value) for entry in history], [(1, "create")])
        self.assertEqual((self.value(row.code, "vehicle_width_m").unit, self.value(row.code, "max_gradient_pct").unit), ("m", "%"))
        for last in OPTIONAL:
            self.assertIsNone(self.value(row.code, last))
        resolved = self.resolved(list(made.created))
        self.assertEqual((resolved["des.roadprofile.pista_nueva.mesh_factor"], resolved["des.roadprofile.pista_nueva.metric"]),
                         (1.0, "exact"))
        with self.project.read() as conn:
            names = road_profiles.profile_names(conn)
        found = road_profiles.road_profiles_from(resolved, made.created, names)
        self.assertEqual((found["pista_nueva"].name, found["acceso_nuevo"].name), ("Pista nueva", "Acceso nuevo"))
        self.assertEqual(found["pista_nueva"], profile_of("pista_nueva", "Pista nueva"))
        small = road_profiles.derived(found["acceso_nuevo"])
        self.assertEqual((small.carriageway_m, small.section_m, small.half_width_m), (5.0, 5.5, 2.75))
        self.assertEqual(found["acceso_nuevo"].class_name, "Acceso al tajo")

    def test_renaming_does_not_change_the_code_or_the_values_and_a_swap_is_valid(self) -> None:
        """RF-017-07, RF-017-04 (D-17): renombrar un perfil cambia solo su nombre: el código (la clave de sus parámetros),
        su ``uid``, quién lo creó y cuándo siguen igual, y sus valores y su historial no se tocan (sigue en la revisión 1);
        el renombrado es una operación registrada y el código antiguo no se reutiliza para un perfil nuevo; cambiar solo las
        mayúsculas es renombrar el mismo perfil, no repetir un nombre; y los nombres se miden sobre los que quedan:
        intercambiar los de dos perfiles en la misma llamada es válido y no se queda a medias."""
        self.edit(new("Rampa norte"), new("Rampa sur", reach_m=40.0))
        before = {item.code: item for item in self.stored()}["rampa_norte"]
        values_before = self.resolved(["rampa_norte"])
        made = self.edit(road_profiles.ProfileEdit(code="rampa_norte", name="Rampa del norte"), declared=None)
        after = {item.code: item for item in self.stored()}["rampa_norte"]
        self.assertEqual(after.name, "Rampa del norte")
        self.assertEqual((after.fid, after.uid, after.code, after.created_by, after.created_at),
                         (before.fid, before.uid, before.code, before.created_by, before.created_at))
        self.assertEqual(self.resolved(["rampa_norte"]), values_before)
        self.assertEqual(self.value("rampa_norte", "vehicle_width_m").rev, 1)
        self.assertEqual((made.created, made.renamed, made.completed), ((), ("rampa_norte",), ()))
        self.assertEqual(self.state()["operations"][-1], (road_profiles.EDIT_ROAD_PROFILES, "done"))
        self.edit(road_profiles.ProfileEdit(code="rampa_norte", name="RAMPA DEL NORTE"), declared=None)
        self.assertEqual({item.code: item.name for item in self.stored()}["rampa_norte"], "RAMPA DEL NORTE")
        self.assertEqual(self.edit(new("Rampa norte")).created, ("rampa_norte_2",))
        self.edit(road_profiles.ProfileEdit(code="rampa_norte", name="Rampa sur"),
                  road_profiles.ProfileEdit(code="rampa_sur", name="RAMPA DEL NORTE"), declared=None)
        names = {item.code: item.name for item in self.stored()}
        self.assertEqual((names["rampa_norte"], names["rampa_sur"]), ("Rampa sur", "RAMPA DEL NORTE"))
        self.assertEqual((self.value("rampa_norte", "reach_m").value, self.value("rampa_sur", "reach_m").value), (60.0, 40.0))

    def test_a_profile_is_completed_in_a_version_with_its_radii_checked_on_the_effective_values(self) -> None:
        """RF-017-07, RF-017-04 (RF-009-24): completar un perfil en V02 con el factor de malla y la métrica le escribe su valor
        propio de la versión (fila ``create`` del historial de la versión) sin tocar el del proyecto ni crear otra fila de
        perfil, y los cálculos arman el perfil de esa versión; los radios de lo que se completa se comprueban con los valores
        **efectivos** del ámbito (los de la versión y, si no, los del proyecto) más los que se dan: con A = 3,5 m y f = 3, un
        caballón de 5 m hace la semianchura 7,75 m, mayor que el radio mínimo de 7 m que se da, y un radio mínimo de 25 m es
        mayor que el radio de 20 m; los dos se rechazan sin escribir nada y uno que cabe, vale."""
        self.edit(new("Pista a completar"))
        project_row = self.value("pista_a_completar", "reach_m")
        count = len(self.stored())
        made = self.edit(road_profiles.ProfileEdit(code="pista_a_completar", values={"mesh_factor": 0.9, "metric": "chamfer5"}),
                         declared=declaration(version=self.v2.code, reason="Malla de la alternativa"))
        own = self.value("pista_a_completar", "mesh_factor", version=self.v2.code)
        self.assertEqual((own.value, own.kind, own.scope, own.scope_uid, own.rev), (0.9, "ADOPTADO", "version", self.v2.uid, 1))
        self.assertEqual(self.value("pista_a_completar", "metric", version=self.v2.code).value, "chamfer5")
        self.assertIsNone(self.value("pista_a_completar", "reach_m", version=self.v2.code))
        self.assertEqual(self.value("pista_a_completar", "reach_m"), project_row)
        self.assertEqual((made.created, made.renamed, made.completed), ((), (), ("pista_a_completar",)))
        self.assertEqual(len(self.stored()), count)
        found = road_profiles.road_profiles_from(self.resolved(["pista_a_completar"], self.v2.code), ["pista_a_completar"])
        self.assertEqual((found["pista_a_completar"].mesh_factor, found["pista_a_completar"].metric,
                          found["pista_a_completar"].reach_m), (0.9, "chamfer5", 60.0))
        for values, code in (({"berm_m": 5.0, "min_radius_m": 7.0}, "des.road_profile_radius_narrow"),
                             ({"min_radius_m": 25.0}, "des.road_profile_radius_order")):
            with self.subTest(values=values):
                error = self.reject(road_profiles.ProfileEdit(code="pista_a_completar", values=values),
                                    declared=declaration(version=self.v2.code))
                self.assertEqual((error.code, error.field), (code, "des.roadprofile.pista_a_completar.min_radius_m"))
        self.edit(road_profiles.ProfileEdit(code="pista_a_completar", values={"min_radius_m": 15.0, "berm_m": 2.0}),
                  declared=declaration(version=self.v2.code))
        self.assertEqual(self.value("pista_a_completar", "min_radius_m", version=self.v2.code).value, 15.0)

    def read_profile(self, code: str) -> str:
        """Registra una «pista» de prueba en V01 que lee los valores de su perfil ``code`` (lo que lee la real, según
        ``provenance.road_params``) y devuelve su uid."""
        keys = [key for key in provenance.road_params("RDW-001", mode="on_axis", profile=code)
                if key.startswith(f"des.roadprofile.{code}.")]
        self.assertEqual(len(keys), 14)  # los catorce que cambian el resultado (no la clase normativa)
        self.clock.advance(minutes=1)
        handle = operations.begin_operation(self.project, provenance.ROAD, settings={"profile": code}, inputs=[], params=keys,
                                            executor="blender", version=self.v1.uid)
        with self.project.write_transaction() as conn:
            handle.complete(conn, outputs=[])
        return str(handle.uid)

    def causes(self, uid: str) -> set[tuple[str, str]]:
        """Las causas de obsolescencia de la operación (la caché ``gb_stale`` de la 008): su clase y, por su nombre, lo que
        cambió (la clave del parámetro)."""
        with self.project.read() as conn:
            rows = conn.execute("SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?",
                                (uid,)).fetchall()
            return {(kind, (conn.execute("SELECT key FROM gb_parameter WHERE uid = ?", (subject,)).fetchone() or (subject,))[0])
                    for kind, subject in rows}

    def test_changing_a_value_of_a_profile_makes_obsolete_only_the_roads_that_use_it(self) -> None:
        """RF-017-07, RF-009-24 (plan §5.2.2: el perfil es de la versión y cambiar uno de sus valores deja obsoletas las pistas
        que lo usan, con su causa, por el grafo de la 008; una operación **sintética** de tipo ``des.road`` hace de la pista
        que leerán las tareas siguientes): con los valores propios de V01 (y ninguno del proyecto), un valor cambiado de un
        perfil deja obsoleta la pista de prueba que lo lee, con la causa «cambió el parámetro» y su clave; la que usa otro
        perfil sigue al día; y la clase normativa, que no lee la pista ni cambia un cálculo, no deja obsoleta ninguna."""
        self.edit(new("Pista de V01"), new("Acceso de V01"), declared=declaration(version=self.v1.code))
        self.assertIsNone(self.value("pista_de_v01", "max_gradient_pct"))  # nada en el proyecto
        self.assertEqual(self.value("pista_de_v01", "max_gradient_pct", version=self.v1.code).scope, "version")
        uses_main, uses_other = self.read_profile("pista_de_v01"), self.read_profile("acceso_de_v01")
        self.assertEqual((self.causes(uses_main), self.causes(uses_other)), (set(), set()), "al crearlas, están al día")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            self.store.change(conn, params.road_profile_key("pista_de_v01", "class"), value="Acceso al tajo",
                              reason="Cambio de la clase normativa", version=self.v1.code)
        self.assertEqual(self.causes(uses_main), set())
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            self.store.change(conn, params.road_profile_key("pista_de_v01", "max_gradient_pct"), value=8.0,
                              reason="Pendiente máxima de la ITC revisada", version=self.v1.code)
        self.assertEqual(self.causes(uses_main), {("parameter_changed", "des.roadprofile.pista_de_v01.max_gradient_pct")})
        self.assertEqual(self.causes(uses_other), set())
        self.assertEqual(self.value("pista_de_v01", "max_gradient_pct", version=self.v1.code).value, 8.0)


class RejectionTest(_SharedCase):
    def test_a_profile_without_a_name_is_rejected(self) -> None:
        """RF-017-04: un perfil sin nombre (vacío, de espacios, ``None``) se rechaza con ``des.road_profile_name_missing``
        nombrando el campo y el valor, antes de registrar nada; con varios nuevos, se nombra el que falla."""
        for name in ("", "\t"):
            with self.subTest(name=name):
                error = self.reject(new(name))
                self.assertEqual((error.code, error.field, error.value), ("des.road_profile_name_missing", "name", name))
        self.assertEqual(self.reject(road_profiles.ProfileEdit(name=None, values=values_of())).code,
                         "des.road_profile_name_missing")
        self.assertIn("nuevo 2", self.reject(new("Tercera"), new(" ")).text)
        error = self.reject(road_profiles.ProfileEdit(code="acceso_tajo", name="  "), declared=None)
        self.assertEqual(error.code, "des.road_profile_name_missing")
        self.assertIn("«acceso_tajo»", error.text)

    def test_a_repeated_name_is_rejected_naming_both(self) -> None:
        """RF-017-04: un nombre que ya es de otro perfil (sin distinguir mayúsculas ni espacios en los bordes) se rechaza con
        ``des.road_profile_name_repeated`` nombrando los dos; también dos nuevos con el mismo nombre en la misma llamada y
        un renombrado al nombre de otro perfil. Nada queda escrito."""
        for name in (MAIN, " pista_PRINCIPAL "):
            with self.subTest(name=name):
                error = self.reject(new(name))
                self.assertEqual((error.code, error.field), ("des.road_profile_name_repeated", "name"))
                self.assertIn("pista_principal_2", error.text)
                self.assertIn("«pista_principal»", error.text)
        self.assertEqual(self.reject(new("Tercera"), new("tercera")).code, "des.road_profile_name_repeated")
        error = self.reject(road_profiles.ProfileEdit(code="acceso_tajo", name=" pista_principal"), declared=None)
        self.assertEqual(error.code, "des.road_profile_name_repeated")
        self.assertIn("«acceso_tajo»", error.text)
        self.assertIn("«pista_principal»", error.text)

    def test_an_incomplete_profile_is_rejected_naming_the_profile_and_the_field(self) -> None:
        """RF-017-04, RF-017-07 (D-2): sin alguno de los trece valores (que falte la clave o sea ``None``) se rechaza con
        ``des.road_profile_value_missing`` nombrando el perfil por su nombre, la clave del campo y el valor; no hay valor por
        defecto que lo tape. Nada queda escrito."""
        for field in ("vehicle_width_m", "min_radius_m", "reach_m", "class"):
            with self.subTest(field=field):
                error = self.reject(new("Tercera", **{field: None}))
                self.assertEqual((error.code, error.field, error.value),
                                 ("des.road_profile_value_missing", f"des.roadprofile.tercera.{field}", None))
                self.assertEqual(error.obj, "Perfil de pista «Tercera»")
                self.assertIn("«Tercera»", error.text)
        error = self.reject(road_profiles.ProfileEdit(name="Tercera"))
        self.assertEqual((error.code, error.field), ("des.road_profile_value_missing", "des.roadprofile.tercera.vehicle_width_m"))
        error = self.reject(new("Tercera", **{"class": "   "}))
        self.assertEqual((error.code, error.field), ("des.road_profile_value_missing", "des.roadprofile.tercera.class"))

    def test_a_value_out_of_range_or_a_radius_that_does_not_fit_is_rejected(self) -> None:
        """RF-017-04, RF-017-07: un vehículo de 0 m, un arcén negativo, un ángulo de 90°, un factor de malla de más de 1, una
        métrica desconocida y un NaN se rechazan con ``des.road_profile_value_range``; un radio mínimo mayor que el radio, o
        menor que la semianchura de la sección (5,75 m con A = 3,5 m, f = 3, arcén 0 m y caballón 1 m), con
        ``des.road_profile_radius_order`` o ``_narrow``, nombrando el perfil, la clave del campo y el valor; un valor que no
        es un número, o una clave que no es de un perfil, un error del programa."""
        bad = (("vehicle_width_m", 0.0), ("shoulder_m", -1.0), ("cut_angle_deg", 90.0), ("mesh_factor", 1.5),
               ("metric", "manhattan"), ("vehicle_width_m", math.nan))
        for field, value in bad:
            with self.subTest(field=field, value=value):
                error = self.reject(new("Tercera", **{field: value}))
                self.assertEqual((error.code, error.field), ("des.road_profile_value_range", f"des.roadprofile.tercera.{field}"))
                self.assertIn("«Tercera»", error.text)
                if isinstance(value, float) and math.isfinite(value):
                    self.assertEqual(error.value, value)
        error = self.reject(new("Tercera", min_radius_m=25.0))
        self.assertEqual((error.code, error.field, error.value),
                         ("des.road_profile_radius_order", "des.roadprofile.tercera.min_radius_m", 25.0))
        error = self.reject(new("Tercera", min_radius_m=5.7))
        self.assertEqual((error.code, error.field, error.value),
                         ("des.road_profile_radius_narrow", "des.roadprofile.tercera.min_radius_m", 5.7))
        self.assertIn("5,75", error.text)
        self.assertEqual(self.reject(new("Tercera", berm_m=3.0, min_radius_m=6.0)).code, "des.road_profile_radius_narrow")
        before = self.state()
        with self.assertRaises(TypeError):
            self.edit(new("Tercera", vehicle_width_m=True))
        with self.assertRaises(ValueError):
            self.edit(road_profiles.ProfileEdit(name="Tercera", values={"altura": 5.0}))
        self.assertNothing(before)

    def test_everything_is_looked_at_before_writing_anything(self) -> None:
        """RF-017-04: se mira todo antes de escribir nada: un perfil válido y otro con un valor fuera de rango no dejan
        ninguno de los dos; y un valor que se completa fuera de rango o sin valor se rechaza nombrando el perfil por su
        NOMBRE (no su código), la clave del campo y el valor."""
        error = self.reject(new("Tercera"), new("Cuarta", fill_angle_deg=95.0))
        self.assertEqual(error.code, "des.road_profile_value_range")
        self.assertNotIn("tercera", [item.code for item in self.stored()])
        for values, code in (({"mesh_factor": 1.5}, "des.road_profile_value_range"),
                             ({"metric": None}, "des.road_profile_value_missing")):
            with self.subTest(values=values):
                error = self.reject(road_profiles.ProfileEdit(code="pista_principal", values=values),
                                    declared=declaration(version=self.v2.code))
                self.assertEqual((error.code, error.obj), (code, "Perfil de pista «PISTA_PRINCIPAL»"))
                self.assertEqual(error.field, f"des.roadprofile.pista_principal.{next(iter(values))}")

    def test_an_edit_that_changes_nothing_is_a_program_error(self) -> None:
        """RF-017-04: una edición que no cambia nada (el mismo nombre y sin valores), de un perfil que no existe, repetida en
        la misma llamada o con valores sin declaración es un error del programa (``ValueError``) y no deja nada."""
        before = self.state()
        edits = (road_profiles.ProfileEdit(code="acceso_tajo", name=OTHER), road_profiles.ProfileEdit(code="acceso_tajo"),
                 road_profiles.ProfileEdit(code="no_existe", name="Otro"))
        for edit in edits:
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                self.edit(edit, declared=None)
        with self.assertRaises(ValueError):
            self.edit(road_profiles.ProfileEdit(code="acceso_tajo", name="Uno"),
                      road_profiles.ProfileEdit(code="acceso_tajo", name="Otro"), declared=None)
        with self.assertRaises(ValueError):
            self.edit(road_profiles.ProfileEdit(code="acceso_tajo", values={"mesh_factor": 0.9}), declared=None)
        self.assertNothing(before)


class DeclarationTest(unittest.TestCase):
    def test_the_operation_is_declared_for_bl_and_has_its_spanish(self) -> None:
        """RF-017-07: ``des.edit_road_profiles`` es una operación de proyecto, de ``des``, no repetible, que lanza la orden
        del catálogo, y su nombre visible está en español en el catálogo de mensajes."""
        (operation,) = road_profiles.OPERATIONS
        self.assertEqual(operation.op_type, "des.edit_road_profiles")
        self.assertEqual((operation.module, operation.scope, operation.repeatable), ("des", "project", False))
        self.assertEqual(operation.commands, ("geoblender.des_edit_road_profile",))
        table = i18n.load_messages()
        self.assertIn(operation.label_msgid, table)
        self.assertNotEqual(table[operation.label_msgid], operation.label_msgid)

    def test_the_dataset_is_not_editable_in_qgis(self) -> None:
        """RF-017-07 (plan §5.2.1): el dato de los perfiles es una tabla de atributos de ``des`` que se lee con
        ``core.gpkg_layer@1`` y no se edita en QGIS (los valores están en parámetros, con su historial)."""
        spec = road_profiles.dataset_spec()
        self.assertEqual((spec.name, spec.module, spec.kind, spec.locator, spec.reader, spec.role, spec.qgis_editable),
                         ("des_road_profile", "des", "table", "des_road_profile", "core.gpkg_layer@1", "road_profiles", False))


if __name__ == "__main__":
    unittest.main()
