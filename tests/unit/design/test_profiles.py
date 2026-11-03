# SPDX-License-Identifier: GPL-3.0-or-later
"""Perfiles de banco: lo derivado y las comprobaciones del modelo (spec 013, T02; HU-013-4;
RF-013-18, RF-013-19, RF-013-20; plan 013 §5.2.2 y §5.3.1, D-7 y D-17).

``design.model.BenchProfile`` es un perfil con un código inmutable (``[a-z][a-z0-9_]*``, D-17),
un nombre libre (``EXPL_10_60_6``) y sus cinco valores (altura de banco ``h`` en m, inclinación
de la cara ``α`` en °, berma mínima ``B`` en m, cota de ancla en m y factor de malla). El avance
``a = h/tan α + B`` (m) y el talud general ``atan(h/a)`` (°) son **valores derivados**, no
parámetros, con error ≤ 10⁻⁹ relativo (RF-013-20), y el perfil se marca «no resuelto por la
rejilla» cuando la huella horizontal de su cara o su berma es menor que el paso de la rejilla
(ADR-0014). Un perfil sin nombre, con el nombre de otro, o con un valor sin valor o fuera de rango
se rechaza nombrándolo, con el campo y el valor, y no se calcula con él (RF-013-19).

Los derivados de la spec están hechos a mano con 70 cifras (``decimal``; ``tan 60°``, ``tan 35°``
y ``atan`` por series): no usan el código de ``design``.

T16 (HU-013-4; RF-013-18, RF-013-19; plan 013 §5.2.1, D-17 y D-24): la tabla del proyecto
``des_bench_profile`` (código ASCII en minúsculas fijado al crear y único, nombre libre y único) y
la operación de proyecto ``des.edit_bench_profiles``, que crea, completa o renombra perfiles. Al
crear o completar, la altura, la cara, la berma y el ancla son filas ``create`` del historial de
``core.params`` en la transacción que escribe la fila; renombrar no cambia el código; un perfil sin
nombre, repetido, o con un valor sin valor o fuera de rango se rechaza nombrando el perfil, el campo
y el valor, **antes** de registrar nada.
"""

from __future__ import annotations

import dataclasses
import json
import math
import sqlite3
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
params = import_geoblender("design.params")
profiles = import_geoblender("design.profiles")
pipeline = import_geoblender("design.pipeline")
design_store = import_geoblender("design.store")
grid_mod = import_geoblender("gis.grid")
core_params = import_geoblender("core.params")
registry = import_geoblender("core.datasets.registry")
versions_read = import_geoblender("core.versions.read")
i18n = import_geoblender("core.i18n")
res_provenance = import_geoblender("reserves.provenance")

# Cálculo a mano (Decimal, 70 cifras): nombre → (altura, cara, berma, huella de la cara, avance,
# talud general).
HAND = {
    "EXPL_10_60_6": (10.0, 60.0, 6.0, 5.773502691896257645, 11.773502691896257645,
                     40.343404702690171789),
    "REST_5_35_6": (5.0, 35.0, 6.0, 7.140740033710572511, 13.140740033710572511,
                    20.831623498965657231),
    "DESD_10_45_6": (10.0, 45.0, 6.0, 10.0, 16.0, 32.005383208083495561),
}
ANCHOR = 125.0


def profile_of(which: str, /, **changes: object) -> object:
    """El perfil de la spec con ese nombre (código = nombre en minúsculas), con los cambios."""
    height, face, berm, *_ = HAND[which]
    values: dict[str, object] = dict(code=which.lower(), name=which, height_m=height,
                                     face_deg=face, berm_m=berm, anchor_m=ANCHOR)
    values.update(changes)
    return model.BenchProfile(**values)


def project_grid(step: float, step_y: float | None = None) -> object:
    """Una rejilla de proyecto de 20 × 20 celdas con ese paso (en Y, ``step_y`` si se da)."""
    return grid_mod.Grid(west=699_700.0, north=4_400_020.0, dx=step,
                         dy=step if step_y is None else step_y, ncols=20, nrows=20)


class DerivedValuesTest(unittest.TestCase):
    def test_advance_and_general_slope_of_the_spec_profiles(self) -> None:
        """RF-013-20 (CE-013-03): ``EXPL_10_60_6`` da 11,77 m y 40,3°, ``REST_5_35_6`` 13,14 m y
        20,83° y ``DESD_10_45_6`` 16,00 m y 32,0°, con error ≤ 10⁻⁹ relativo frente al
        cálculo a mano de 70 cifras."""
        # Como los escribe la spec: avance (2 decimales) y talud general (1 o 2 decimales).
        shown = {"EXPL_10_60_6": (11.77, 40.3, 1), "REST_5_35_6": (13.14, 20.83, 2),
                 "DESD_10_45_6": (16.00, 32.0, 1)}
        for name, (_h, _f, _b, footprint, advance, general) in HAND.items():
            profile = profile_of(name)
            shown_advance, shown_general, decimals = shown[name]
            with self.subTest(name=name):
                self.assertLessEqual(abs(profile.avance_m - advance) / advance, 1e-9)
                self.assertLessEqual(abs(profile.general_deg - general) / general, 1e-9)
                self.assertLessEqual(abs(profile.face_footprint_m - footprint) / footprint, 1e-9)
                self.assertEqual(round(profile.avance_m, 2), shown_advance)
                self.assertEqual(round(profile.general_deg, decimals), shown_general)

    def test_general_tangent_is_height_over_advance(self) -> None:
        """RF-013-20, RF-013-13: la tangente del talud general es ``h / a`` (exacta, no la de un
        ángulo ya redondeado), y ``general_deg`` es su arcotangente en grados."""
        for name in HAND:
            profile = profile_of(name)
            with self.subTest(name=name):
                self.assertEqual(profile.general_tan, profile.height_m / profile.avance_m)
                self.assertAlmostEqual(math.tan(math.radians(profile.general_deg)),
                                       profile.general_tan, places=14)

    def test_without_berm_the_general_slope_is_the_face(self) -> None:
        """RF-013-20: con berma 0 el avance es la huella de la cara y el talud general es la
        cara; una cara casi vertical y una berma grande dan un talud general suave."""
        flat = profile_of("EXPL_10_60_6", berm_m=0.0)
        self.assertAlmostEqual(flat.avance_m, flat.face_footprint_m, places=12)
        self.assertAlmostEqual(flat.general_deg, 60.0, places=9)
        gentle = profile_of("EXPL_10_60_6", face_deg=89.9, berm_m=100.0)
        self.assertLess(gentle.general_deg, 6.0)

    def test_derived_values_are_not_parameters(self) -> None:
        """RF-013-20: el avance y el talud general no son campos ni parámetros del perfil (no
        se guardan ni se pueden fijar: se derivan); el perfil es inmutable y los cinco campos
        de valor son los de las familias ``des.bench.{p}.*``."""
        profile = profile_of("EXPL_10_60_6")
        fields = [field.name for field in dataclasses.fields(profile)]
        self.assertEqual(fields, ["code", "name", "height_m", "face_deg", "berm_m", "anchor_m",
                                  "mesh_factor"])
        self.assertEqual(sorted(fields[2:]), sorted(str(item) for item in params.BenchParam))
        self.assertNotIn("avance_m", dataclasses.asdict(profile))
        self.assertNotIn("general_deg", dataclasses.asdict(profile))
        for name in ("avance_m", "general_deg", "height_m", "code"):
            # Un campo da FrozenInstanceError (AttributeError); un derivado, en Python 3.13 con
            # slots, TypeError: en los dos casos no se puede fijar.
            with self.subTest(name=name), self.assertRaises((AttributeError, TypeError)):
                setattr(profile, name, 1.0)
            self.assertEqual(profile, profile_of("EXPL_10_60_6"))
        self.assertEqual(profile.mesh_factor, 1.0)
        self.assertEqual(profile, profile_of("EXPL_10_60_6"))

    def test_integers_become_floats(self) -> None:
        """RF-013-18 (regla 4: float64): los valores enteros se guardan como ``float``."""
        profile = profile_of("EXPL_10_60_6", height_m=10, face_deg=60, berm_m=6,
                             anchor_m=125, mesh_factor=1)
        for name in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            self.assertIs(type(getattr(profile, name)), float, name)


class UnresolvedByTheGridTest(unittest.TestCase):
    def test_resolved_profile_has_no_mark(self) -> None:
        """RF-013-20 (ADR-0014): con la huella de la cara (5,77 m) y la berma (6 m) mayores o
        iguales que el paso de la rejilla del proyecto, el perfil está resuelto."""
        profile = profile_of("EXPL_10_60_6")
        for step in (0.5, 1.0, 2.0, 5.0, 5.77, 5.7735):
            with self.subTest(step=step):
                self.assertIsNone(profile.unresolved_by(project_grid(step)))

    def test_face_or_berm_narrower_than_a_cell_is_marked(self) -> None:
        """RF-013-20: si la huella de la cara (5,77 m) o la berma (6 m) es menor que el paso, el
        perfil se marca «no resuelto por la rejilla», con el texto en español (y en inglés) y las
        cifras; con paso 5,8 m es la cara; con 7 m, las dos; el paso es el mayor de dx y dy."""
        profile = profile_of("EXPL_10_60_6")
        text = profile.unresolved_by(project_grid(5.8))
        self.assertIsNotNone(text)
        self.assertIn("«EXPL_10_60_6»", text)
        self.assertIn("no está resuelto por la rejilla", text)
        self.assertIn("5,77 m", text)
        self.assertIn("6 m", text)
        self.assertIn("5,8 m", text)
        english = profile.unresolved_by(project_grid(5.8), language="en")
        self.assertIn("is not resolved by the grid", english)
        self.assertIn("5.77 m", english)
        self.assertIsNotNone(profile.unresolved_by(project_grid(7.0)))
        self.assertIsNotNone(profile.unresolved_by(project_grid(1.0, 7.0)))
        self.assertIsNone(profile.unresolved_by(project_grid(1.0, 2.0)))
        thin = profile_of("DESD_10_45_6", berm_m=0.5)
        self.assertIsNotNone(thin.unresolved_by(project_grid(1.0)))
        self.assertIsNone(thin.unresolved_by(project_grid(0.5)))
        steep = profile_of("EXPL_10_60_6", face_deg=89.0, berm_m=6.0)
        self.assertIsNotNone(steep.unresolved_by(project_grid(1.0)))

    def test_no_berm_is_nothing_to_resolve(self) -> None:
        """RF-013-20 (decisión de la T02): una berma de 0 m no tiene huella que resolver; solo
        una berma mayor que 0 y menor que el paso, o la cara, marca el perfil."""
        flat = profile_of("DESD_10_45_6", berm_m=0.0)
        self.assertIsNone(flat.unresolved_by(project_grid(2.0)))
        self.assertIsNotNone(flat.unresolved_by(project_grid(11.0)))

    def test_the_mark_is_the_warning_of_the_catalog(self) -> None:
        """RF-013-20, RF-013-30: la marca es el aviso ``des.profile_unresolved`` del catálogo,
        que se informa y no se lanza."""
        message = messages.MESSAGES["des.profile_unresolved"]
        self.assertEqual(message.severity, "warning")
        with self.assertRaises(ValueError):
            messages.DesignError("des.profile_unresolved", obj="Perfil", field="campo")


class ValidationTest(unittest.TestCase):
    def test_ranges_of_every_value(self) -> None:
        """RF-013-18, RF-013-19: la altura es de 0 (excluido) a 100 m, la cara de 0 a 90 °
        (ambos excluidos), la berma de 0 a 100 m, el ancla de -1 000 a 10 000 m y el factor de
        malla de 0 (excluido) a 1: los extremos incluidos valen y lo de fuera se rechaza
        (``des.profile_value_range``), nombrando el perfil, la clave del campo y el valor."""
        valid = (("height_m", 100.0), ("height_m", 0.5), ("face_deg", 89.999), ("face_deg", 1e-6),
                 ("berm_m", 0.0), ("berm_m", 100.0), ("anchor_m", -1000.0),
                 ("anchor_m", 10000.0), ("mesh_factor", 1.0), ("mesh_factor", 0.5))
        for field, value in valid:
            with self.subTest(field=field, value=value):
                self.assertEqual(getattr(profile_of("EXPL_10_60_6", **{field: value}), field),
                                 value)
        invalid = (("height_m", 0.0), ("height_m", -5.0), ("height_m", 100.5),
                   ("face_deg", 0.0), ("face_deg", 90.0), ("face_deg", 120.0),
                   ("berm_m", -0.001), ("berm_m", 100.001), ("anchor_m", -1000.5),
                   ("anchor_m", 10000.5), ("mesh_factor", 0.0), ("mesh_factor", 1.0001),
                   ("height_m", math.nan), ("berm_m", math.inf), ("anchor_m", -math.inf))
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                with self.assertRaises(messages.DesignError) as caught:
                    profile_of("EXPL_10_60_6", **{field: value})
                error = caught.exception
                self.assertEqual(error.code, "des.profile_value_range")
                self.assertEqual(error.field, f"des.bench.expl_10_60_6.{field}")
                self.assertEqual(error.obj, "Perfil de banco «EXPL_10_60_6»")
                self.assertIn("«EXPL_10_60_6»", error.text)
                self.assertIn(f"des.bench.expl_10_60_6.{field}", error.text)
                if isinstance(value, float) and math.isfinite(value):
                    self.assertEqual(error.value, value)

    def test_a_value_without_value_is_rejected(self) -> None:
        """RF-013-19 (D-7): una altura, una cara, una berma, un ancla o un factor de malla
        «sin valor» (``None``) se rechaza con ``des.profile_value_missing``, nombrando el perfil
        y el campo, y diciendo dónde se declara; nada se calcula con él."""
        for field in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            with self.subTest(field=field):
                with self.assertRaises(messages.DesignError) as caught:
                    profile_of("REST_5_35_6", **{field: None})
                error = caught.exception
                self.assertEqual(error.code, "des.profile_value_missing")
                self.assertEqual(error.field, f"des.bench.rest_5_35_6.{field}")
                self.assertIsNone(error.value)
                self.assertIn("«REST_5_35_6»", error.text)
                self.assertIn("Perfiles de banco", error.text)

    def test_a_profile_without_name_is_rejected(self) -> None:
        """RF-013-19: un perfil con el nombre vacío, de espacios o que no es un texto se
        rechaza con ``des.profile_name_missing`` (nombrándolo por su código)."""
        for name in ("", "   ", "\t"):
            with self.subTest(name=name):
                with self.assertRaises(messages.DesignError) as caught:
                    profile_of("EXPL_10_60_6", name=name)
                error = caught.exception
                self.assertEqual(error.code, "des.profile_name_missing")
                self.assertEqual(error.field, "name")
                self.assertIn("«expl_10_60_6»", error.text)
        with self.assertRaises(TypeError):
            profile_of("EXPL_10_60_6", name=None)

    def test_the_code_is_an_ascii_identifier(self) -> None:
        """RF-013-18 (D-17): el código es ``[a-z][a-z0-9_]*`` (ASCII, en minúsculas); otro es
        un error del programa (``ValueError``), igual que un valor que no es un número real
        (``TypeError``: un booleano, un texto)."""
        for code in ("", "Expl", "1expl", "expl 10", "expl.10", "exploración", "expl-10"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                profile_of("EXPL_10_60_6", code=code)
        for field, value in (("height_m", True), ("height_m", "10"), ("face_deg", [60.0]),
                             ("berm_m", b"6")):
            with self.subTest(field=field, value=value), self.assertRaises(TypeError):
                profile_of("EXPL_10_60_6", **{field: value})
        with self.assertRaises(TypeError):
            profile_of("EXPL_10_60_6", code=None)


class RepeatedNamesTest(unittest.TestCase):
    def test_a_repeated_name_is_rejected(self) -> None:
        """RF-013-19: un perfil que repite el nombre de otro (también en mayúsculas distintas o
        con espacios en los bordes: el código sale del nombre) se rechaza con
        ``des.profile_name_repeated``, nombrando los dos; perfiles con nombres distintos valen."""
        first = profile_of("EXPL_10_60_6")
        second = profile_of("REST_5_35_6")
        third = profile_of("DESD_10_45_6")
        model.check_profiles([first, second, third])
        model.check_profiles([])
        for repeated in (profile_of("EXPL_10_60_6", code="expl_otra"),
                         profile_of("EXPL_10_60_6", code="otra", name="expl_10_60_6"),
                         profile_of("EXPL_10_60_6", code="otra", name=" EXPL_10_60_6 ")):
            with self.subTest(name=repeated.name):
                with self.assertRaises(messages.DesignError) as caught:
                    model.check_profiles([first, second, repeated])
                error = caught.exception
                self.assertEqual(error.code, "des.profile_name_repeated")
                self.assertEqual(error.field, "name")
                self.assertIn(repeated.code, error.text)
                self.assertIn("expl_10_60_6", error.text)

    def test_a_repeated_code_is_a_program_error(self) -> None:
        """RF-013-18 (D-17): dos perfiles con el mismo código no son un error del usuario sino
        del programa (el sistema fija el código al crear el perfil y es único): ``ValueError``."""
        with self.assertRaises(ValueError):
            model.check_profiles([profile_of("EXPL_10_60_6"),
                                  profile_of("EXPL_10_60_6", name="Otro nombre")])


# --- La tabla del proyecto y la operación que edita los perfiles (T16) -----------------------------

NEW_VALUES = {name: {"height_m": h, "face_deg": f, "berm_m": b, "anchor_m": ANCHOR}
              for name, (h, f, b, *_rest) in HAND.items()}
"""Los valores de los tres perfiles de la spec, tal como los declara la persona al crearlos."""
EXPL, REST, DESD = "EXPL_10_60_6", "REST_5_35_6", "DESD_10_45_6"
NOBODY = "Samuel (IMGA)"


def declaration(**changes: Any) -> Any:
    """Lo que declara la persona de los valores que escribe (origen, decisor y motivo)."""
    base: dict[str, Any] = {"source": "Plan de diseño de IMGA", "decided_by": NOBODY,
                            "reason": "Perfil de la spec 013"}
    return profiles.ProfileDeclaration(**{**base, **changes})


def new(name: str, **changes: Any) -> Any:
    """Un perfil nuevo con los valores de ``name`` (uno de la spec) cambiados por ``changes``; con
    ``None`` en un valor, ese valor se quita."""
    values = {**NEW_VALUES.get(name, NEW_VALUES[EXPL]), **changes}
    return profiles.ProfileEdit(name=name, values={k: v for k, v in values.items()
                                                   if v is not None})


class CodeTest(unittest.TestCase):
    def test_the_code_is_the_ascii_name_in_lowercase(self) -> None:
        """RF-013-18 (D-17): el código es el nombre en ASCII y en minúsculas, sin tildes y con «_»
        en lugar de lo demás: ``EXPL_10_60_6`` da ``expl_10_60_6``, ``Exploración 10/60`` da
        ``exploracion_10_60``; sin letra delante lleva una ``p_`` y sin nada, ``p``."""
        cases = {"EXPL_10_60_6": "expl_10_60_6", "REST_5_35_6": "rest_5_35_6",
                 "Exploración 10/60": "exploracion_10_60",
                 "  Banco   de  prueba ": "banco_de_prueba",
                 "10-60-6": "p_10_60_6", "": "p", "¡¿?!": "p", "Año 2026": "ano_2026"}
        for name, code in cases.items():
            with self.subTest(name=name):
                self.assertEqual(profiles.profile_code(name, ()), code)
                self.assertTrue(params.is_code(code))

    def test_a_taken_code_gets_a_number(self) -> None:
        """RF-013-18 (D-17): el código es único; si el del nombre ya es de otro perfil, se le
        pone ``_2``, ``_3``… (y el del otro no cambia nunca); el código dura como mucho 32
        caracteres, con el número incluido."""
        taken = {"expl_10_60_6"}
        self.assertEqual(profiles.profile_code("EXPL_10_60_6", taken), "expl_10_60_6_2")
        taken.add("expl_10_60_6_2")
        self.assertEqual(profiles.profile_code("expl 10 60 6", taken), "expl_10_60_6_3")
        long = "perfil de banco con un nombre larguisimo de explotacion"
        code = profiles.profile_code(long, ())
        self.assertLessEqual(len(code), 32)
        self.assertTrue(params.is_code(code))
        again = profiles.profile_code(long, {code})
        self.assertNotEqual(again, code)
        self.assertLessEqual(len(again), 32)
        self.assertTrue(again.endswith("_2"))


class _ProfilesCase(dfx.DesignProjectCase):
    """El proyecto del diseño (una copia **por prueba**: estas pruebas escriben), con los
    parámetros de ``des`` y la operación de los perfiles registrados (lo hará ``bl``)."""

    @classmethod
    def setUpClass(cls) -> None:
        dfx.project_template()  # la plantilla, antes de registrar lo de la 012 (T05)
        cls.enterClassContext(cp.constraints_registered())
        core_params.register_definitions(params.DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        cls.enterClassContext(registered(*profiles.OPERATIONS))

    def setUp(self) -> None:
        self.project, self.clock = self.enterContext(dfx.open_design_project("gb-pf-"))
        self.root = Path(self.project.root)
        with self.project.read() as conn:
            self.v1, self.v2 = (versions_read.version(conn, uid)
                                for uid in dfx.project_template()["versions"])
        self.store = core_params.ParameterStore(self.project)

    def edit(self, *edits: Any, declared: Any = ...) -> Any:
        """Edita los perfiles un minuto después, con la declaración de ``declaration()``."""
        self.clock.advance(minutes=1)
        return profiles.edit_bench_profiles(
            self.project, edits, declaration() if declared is ... else declared)

    def state(self) -> dict[str, Any]:
        """Lo que hay de los perfiles en el proyecto: operaciones, tabla y sus filas, datos y las
        filas de parámetros (clave, ámbito y revisión)."""
        with self.project.read() as conn:
            made = conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?",
                                (profiles.TABLE,)).fetchone() is not None
            return {
                "operations": conn.execute(
                    "SELECT op_type, status FROM gb_operation WHERE op_type LIKE 'des.%' "
                    "ORDER BY fid").fetchall(),
                "table": made,
                "rows": conn.execute(f"SELECT code, name FROM {profiles.TABLE} "
                                     "ORDER BY fid").fetchall() if made else None,
                "datasets": conn.execute("SELECT name FROM gb_dataset WHERE name LIKE 'des\\_%' "
                                         "ESCAPE '\\'").fetchall(),
                "params": conn.execute(
                    "SELECT key, scope_uid, rev FROM gb_parameter WHERE key LIKE 'des.bench.%' "
                    "ORDER BY key, scope_uid").fetchall(),
            }

    def stored(self) -> tuple[Any, ...]:
        with self.project.read() as conn:
            return profiles.read_profiles(conn)

    def value(self, code: str, field: str, version: Any = None) -> Any:
        """La fila del valor ``field`` del perfil ``code`` en el proyecto o en la versión."""
        return self.store.get(params.bench_key(code, field), version=version)

    def values_of(self, codes: list[str], version: Any = None) -> dict[str, Any]:
        """Clave → valor que resuelven los cálculos para esos perfiles (la versión y, si no, el
        proyecto o el valor por defecto de su definición)."""
        keys = [params.bench_key(code, param) for code in codes for param in params.BenchParam]
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
        """Que no se ha registrado nada desde ``before``: ni operación (ni fallida), ni tabla, ni
        fila, ni dato, ni parámetro."""
        self.assertEqual(self.state(), before)


class TableTest(_ProfilesCase):
    def test_the_first_profile_creates_the_table_and_the_next_reuses_it(self) -> None:
        """RF-013-18, plan §5.2.1: la tabla ``des_bench_profile`` (``fid``, ``uid``, ``code``,
        ``name``, ``created_by``, ``created_at``) se crea en la transacción del primer perfil,
        en ``gpkg_contents`` como tabla de atributos, y se registra como dato del proyecto de
        ``des``, leído con ``core.gpkg_layer@1``, no editable en QGIS y salida de la operación;
        la segunda edición añade filas sin tocar las primeras (ni su ``fid`` ni su ``uid`` ni su
        creación) y se registra en el mismo dato."""
        self.assertFalse(self.state()["table"])
        made = self.edit(new(EXPL))
        with self.project.read() as conn:
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({profiles.TABLE})")]
            contents = conn.execute("SELECT data_type, identifier FROM gpkg_contents "
                                    "WHERE table_name = ?", (profiles.TABLE,)).fetchone()
            record = registry.get(conn, profiles.TABLE)
            roles = conn.execute("SELECT role FROM gb_operation_io WHERE operation_uid = ? "
                                 "AND direction = 'out'", (made.operation_uid,)).fetchall()
            titles = dict(conn.execute("SELECT column_name, title FROM gpkg_data_columns "
                                       "WHERE table_name = ?", (profiles.TABLE,)).fetchall())
        self.assertEqual(columns, ["fid", "uid", "code", "name", "created_by", "created_at"])
        self.assertEqual(titles, {"uid": "Identificador", "code": "Código", "name": "Nombre",
                                  "created_by": "Creado por", "created_at": "Creado el"})
        self.assertEqual(contents[0], "attributes")
        self.assertIsNotNone(record)
        self.assertEqual((record.module, record.kind, record.locator, record.reader,
                          record.qgis_editable, record.status.value),
                         ("des", "table", profiles.TABLE, "core.gpkg_layer@1", False, "current"))
        self.assertEqual(record.operation_uid, made.operation_uid)
        self.assertEqual(roles, [(profiles.PROFILES_ROLE,)])
        self.assertEqual(profiles.dataset_spec().name, profiles.TABLE)
        (first,) = self.stored()
        second = self.edit(new(REST))
        after = self.stored()
        self.assertEqual(after[0], first)
        self.assertEqual([item.code for item in after], ["expl_10_60_6", "rest_5_35_6"])
        self.assertNotEqual(made.operation_uid, second.operation_uid)
        with self.project.read() as conn:
            record = registry.get(conn, profiles.TABLE)
        self.assertEqual(record.operation_uid, second.operation_uid)

    def test_code_and_name_are_unique_in_the_table(self) -> None:
        """RF-013-18, RF-013-19 (D-17): la tabla no admite dos perfiles con el mismo código ni el
        mismo nombre, aunque alguien escriba en ella por fuera."""
        self.edit(new(EXPL))
        with self.project.read() as conn:
            unique = set()
            for _seq, index, is_unique, *_rest in conn.execute(
                    f"PRAGMA index_list({profiles.TABLE})").fetchall():
                if is_unique:
                    columns = [row[2] for row in conn.execute(f"PRAGMA index_info({index})")]
                    unique.add(tuple(columns))
        self.assertEqual(unique, {("uid",), ("code",), ("name",)})
        # Y una escritura por fuera (no pasa por la operación) que los repitiera, no entra. Se
        # prueba en una copia en memoria: en el proyecto, un fallo de escritura lo deja en solo lectura.
        with self.project.read() as conn:
            ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?",
                               (profiles.TABLE,)).fetchone()[0]
        copy = sqlite3.connect(":memory:")
        self.addCleanup(copy.close)
        copy.execute(ddl)
        insert = (f"INSERT INTO {profiles.TABLE} (uid, code, name, created_by, created_at) "
                  "VALUES (?, ?, ?, 'x', '2026-11-02T10:00:00Z')")
        copy.execute(insert, ("u1", "expl_10_60_6", EXPL))
        for uid, code, name in (("u2", "expl_10_60_6", "Otro"), ("u3", "otro", EXPL),
                                ("u1", "otro", "Otro")):
            with self.subTest(code=code, name=name), self.assertRaises(sqlite3.IntegrityError):
                copy.execute(insert, (uid, code, name))


class CreateTest(_ProfilesCase):
    def test_a_profile_is_a_row_and_four_created_parameters(self) -> None:
        """RF-013-18 (D-17, D-24): crear ``EXPL_10_60_6`` escribe su fila (código fijado del
        nombre, quién y cuándo) y su altura, su cara, su berma y su ancla como parámetros con tipo
        HIPÓTESIS, su origen, su decisor y su motivo, con una fila ``create`` en el historial y sin
        «sin confirmar»; el factor de malla no se escribe (vale 1,0 por su definición)."""
        made = self.edit(new(EXPL))
        (row,) = self.stored()
        self.assertEqual((row.code, row.name), ("expl_10_60_6", EXPL))
        self.assertEqual(row.created_by, self.project.session.user_host)
        with self.project.read() as conn:
            started = conn.execute("SELECT started_at FROM gb_operation WHERE uid = ?",
                                   (made.operation_uid,)).fetchone()[0]
        self.assertEqual(row.created_at, started)
        for field, expected in NEW_VALUES[EXPL].items():
            with self.subTest(field=field):
                record = self.value(row.code, field)
                self.assertEqual(record.value, expected)
                self.assertEqual((record.kind, record.source_kind, record.source),
                                 ("HIPÓTESIS", "person", "Plan de diseño de IMGA"))
                self.assertEqual((record.decided_by, record.reason, record.unconfirmed),
                                 (NOBODY, "Perfil de la spec 013", False))
                self.assertEqual((record.scope, record.scope_uid, record.rev),
                                 ("project", "", 1))
                history = self.store.history(params.bench_key(row.code, field))
                self.assertEqual([(entry.rev, entry.action.value) for entry in history],
                                 [(1, "create")])
        self.assertIsNone(self.value(row.code, "mesh_factor"))
        self.assertEqual((made.created, made.renamed, made.completed),
                         (("expl_10_60_6",), (), ()))
        self.assertEqual([item.code for item in made.profiles], ["expl_10_60_6"])

    def test_several_profiles_in_one_call_are_one_operation(self) -> None:
        """RF-013-18, HU-013-4: los tres perfiles de la spec en una llamada son una sola
        operación de proyecto, ``des.edit_bench_profiles``, no repetible, y con ellos los
        cálculos obtienen los mismos perfiles, avances y taludes generales que la spec."""
        made = self.edit(new(EXPL), new(REST), new(DESD))
        self.assertEqual(self.state()["operations"], [(profiles.EDIT_BENCH_PROFILES, "done")])
        self.assertEqual([item.code for item in self.stored()],
                         ["expl_10_60_6", "rest_5_35_6", "desd_10_45_6"])
        self.assertEqual(made.created, ("expl_10_60_6", "rest_5_35_6", "desd_10_45_6"))
        self.assertEqual(self.state()["datasets"], [(profiles.TABLE,)])
        codes = list(made.created)
        found = pipeline.bench_profiles(self.values_of(codes), codes)
        for name in HAND:
            profile = found[name.lower()]
            with self.subTest(name=name):
                self.assertEqual(profile.mesh_factor, 1.0)
                self.assertAlmostEqual(profile.avance_m, HAND[name][4], places=12)
                self.assertAlmostEqual(profile.general_deg, HAND[name][5], places=12)
        self.assertEqual(profiles.OPERATIONS[0].repeatable, False)
        self.assertEqual(profiles.OPERATIONS[0].scope, "project")

    def test_the_kind_the_origin_and_the_mesh_factor_are_the_persons(self) -> None:
        """RF-013-18 (D-7): la persona elige HIPÓTESIS o ADOPTADO y el origen (un documento);
        con un factor de malla lo escribe también (la quinta fila); un tipo que no es ni
        ADOPTADO ni HIPÓTESIS es un error del programa."""
        self.edit(new(EXPL, mesh_factor=0.95),
                  declared=declaration(kind="ADOPTADO", source_kind="document",
                                       source="Estudio geotécnico 2026"))
        for field in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            with self.subTest(field=field):
                record = self.value("expl_10_60_6", field)
                self.assertEqual((record.kind, record.source_kind, record.source),
                                 ("ADOPTADO", "document", "Estudio geotécnico 2026"))
        self.assertEqual(self.value("expl_10_60_6", "mesh_factor").value, 0.95)
        before = self.state()
        for kind in ("MEDIDO", "CALCULADO", "hipótesis", ""):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.edit(new(REST), declared=declaration(kind=kind))
        self.assertNothing(before)

    def test_a_value_for_one_version_is_that_versions_own(self) -> None:
        """RF-013-18, RF-009-24: con ``version`` los valores son los propios de esa versión
        (ámbito de versión), sin escribir los del proyecto; la fila del perfil es del proyecto."""
        self.edit(new(EXPL), declared=declaration(version=self.v2.code))
        for field in NEW_VALUES[EXPL]:
            with self.subTest(field=field):
                self.assertIsNone(self.value("expl_10_60_6", field))
                record = self.value("expl_10_60_6", field, version=self.v2.code)
                self.assertEqual(record.value, NEW_VALUES[EXPL][field])
                self.assertEqual((record.scope, record.scope_uid, record.rev),
                                 ("version", self.v2.uid, 1))
        self.assertEqual([item.code for item in self.stored()], ["expl_10_60_6"])
        found = pipeline.bench_profiles(self.values_of(["expl_10_60_6"], self.v2.code),
                                        ["expl_10_60_6"])
        self.assertEqual(found["expl_10_60_6"].height_m, 10.0)

    def test_a_name_that_looks_like_another_gets_its_own_code(self) -> None:
        """RF-013-18 (D-17): el nombre es libre y el código sale de él: dos nombres que dan el
        mismo código (``Perfil A`` y ``perfil-a``) son nombres distintos con códigos distintos
        (``perfil_a`` y ``perfil_a_2``); el segundo no cambia el primero."""
        made = self.edit(new("Perfil A"), new("perfil-a"))
        self.assertEqual(made.created, ("perfil_a", "perfil_a_2"))
        self.assertEqual([(item.code, item.name) for item in self.stored()],
                         [("perfil_a", "Perfil A"), ("perfil_a_2", "perfil-a")])
        for code in made.created:
            self.assertEqual(self.value(code, "height_m").value, 10.0)

    def test_everything_is_written_in_one_transaction(self) -> None:
        """RF-013-18 (RF-008-01): la fila del perfil y sus parámetros van en la misma
        transacción; si algo falla a mitad, no queda ni la tabla, ni la fila del perfil, ni
        ninguno de los parámetros ya escritos: solo la operación, fallida."""
        before = self.state()
        original = core_params.ParameterStore.create
        calls: list[str] = []

        def flaky(store: Any, conn: Any, key: str, *args: Any, **kwargs: Any) -> Any:
            calls.append(key)
            if len(calls) == 6:
                raise RuntimeError("falla a mitad")
            return original(store, conn, key, *args, **kwargs)

        with mock.patch.object(core_params.ParameterStore, "create", flaky):
            with self.assertRaises(RuntimeError):
                self.edit(new(EXPL), new(REST))
        self.assertEqual(len(calls), 6)
        after = self.state()
        self.assertEqual(after["operations"], [(profiles.EDIT_BENCH_PROFILES, "failed")])
        self.assertEqual({k: v for k, v in after.items() if k != "operations"},
                         {k: v for k, v in before.items() if k != "operations"})
        self.assertFalse(after["table"])

    def test_the_declaration_must_say_who_decides_and_why(self) -> None:
        """RF-013-18 (RF-008-01, D-5): sin origen, decisor o motivo, el parámetro no se escribe
        (``ParamError``) y no queda nada; escribir valores sin declaración es un error del
        programa (``ValueError``)."""
        before = self.state()
        for changes in ({"decided_by": ""}, {"source": ""}, {"reason": " "}):
            with self.subTest(changes=changes), self.assertRaises(core_params.ParamError):
                self.edit(new(EXPL), declared=declaration(**changes))
            after = self.state()
            self.assertEqual(after["rows"], before["rows"])
            self.assertEqual(after["params"], before["params"])
            self.assertFalse(after["table"])
        with self.assertRaises(ValueError):
            self.edit(new(EXPL), declared=None)
        with self.assertRaises(ValueError):
            profiles.edit_bench_profiles(self.project, (), declaration())


class _SeededCase(_ProfilesCase):
    """Una copia del proyecto **por clase** con ``EXPL_10_60_6`` y ``REST_5_35_6`` ya creados, para
    las pruebas que solo rechazan (no escriben nada: ``reject`` lo comprueba)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.project, cls.clock = cls.enterClassContext(dfx.open_design_project("gb-pf-"))
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid)
                              for uid in dfx.project_template()["versions"])
        cls.store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        profiles.edit_bench_profiles(cls.project, (new(EXPL), new(REST)), declaration())

    def setUp(self) -> None:
        pass  # el proyecto es el de la clase

    def reject(self, *edits: Any, **kw: Any) -> Any:
        """La edición se rechaza con un ``DesignError`` y no deja nada, ni una operación fallida."""
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            self.edit(*edits, **kw)
        self.assertNothing(before)
        return caught.exception


class RejectionTest(_SeededCase):
    def test_a_profile_without_a_name_is_rejected(self) -> None:
        """RF-013-19: un perfil sin nombre (vacío, de espacios, ``None``) se rechaza con
        ``des.profile_name_missing`` nombrando el campo y el valor, antes de registrar nada."""
        for name in ("", "   ", "\t"):
            with self.subTest(name=name):
                error = self.reject(new(name))
                self.assertEqual((error.code, error.field), ("des.profile_name_missing", "name"))
                self.assertEqual(error.value, name)
        error = self.reject(profiles.ProfileEdit(name=None, values=NEW_VALUES[EXPL]))
        self.assertEqual(error.code, "des.profile_name_missing")
        error = self.reject(new(DESD), new(" "))
        self.assertEqual(error.code, "des.profile_name_missing")
        self.assertIn("nuevo 2", error.text)
        error = self.reject(profiles.ProfileEdit(code="rest_5_35_6", name="  "), declared=None)
        self.assertEqual(error.code, "des.profile_name_missing")
        self.assertIn("«rest_5_35_6»", error.text)

    def test_a_repeated_name_is_rejected_naming_both(self) -> None:
        """RF-013-19: un nombre que ya es de otro perfil (sin distinguir mayúsculas ni espacios
        en los bordes) se rechaza con ``des.profile_name_repeated`` nombrando los dos; también
        dos nuevos con el mismo nombre en la misma llamada y un renombrado al nombre de otro
        perfil. Nada queda escrito."""
        for name in (EXPL, "expl_10_60_6", " EXPL_10_60_6 "):
            with self.subTest(name=name):
                error = self.reject(new(name))
                self.assertEqual((error.code, error.field), ("des.profile_name_repeated", "name"))
                self.assertIn("expl_10_60_6_2", error.text)
                self.assertIn("«expl_10_60_6»", error.text)
        error = self.reject(new(DESD), new("desd_10_45_6"))
        self.assertEqual(error.code, "des.profile_name_repeated")
        self.assertIn("desd_10_45_6_2", error.text)
        error = self.reject(profiles.ProfileEdit(code="rest_5_35_6", name=" expl_10_60_6"),
                            declared=None)
        self.assertEqual(error.code, "des.profile_name_repeated")
        self.assertIn("«rest_5_35_6»", error.text)
        self.assertIn("«expl_10_60_6»", error.text)

    def test_a_missing_value_is_rejected_naming_the_profile_and_the_field(self) -> None:
        """RF-013-19 (D-7): sin altura, cara, berma o ancla (que falte la clave o sea ``None``)
        se rechaza con ``des.profile_value_missing`` nombrando el perfil por su nombre, la clave
        del campo y el valor; no hay valor por defecto que lo tape. Nada queda escrito."""
        for field in ("height_m", "face_deg", "berm_m", "anchor_m"):
            with self.subTest(field=field, how="absent"):
                error = self.reject(new(DESD, **{field: None}))
                self.assertEqual((error.code, error.field, error.value),
                                 ("des.profile_value_missing",
                                  f"des.bench.desd_10_45_6.{field}", None))
                self.assertIn("«DESD_10_45_6»", error.text)
                self.assertEqual(error.obj, "Perfil de banco «DESD_10_45_6»")
            with self.subTest(field=field, how="none"):
                edit = profiles.ProfileEdit(name=DESD, values={**NEW_VALUES[DESD], field: None})
                self.assertEqual(self.reject(edit).code, "des.profile_value_missing")
        error = self.reject(profiles.ProfileEdit(name=DESD))
        self.assertEqual((error.code, error.field), ("des.profile_value_missing",
                                                     "des.bench.desd_10_45_6.height_m"))

    def test_a_value_out_of_range_is_rejected_naming_the_value(self) -> None:
        """RF-013-19: una altura de 0 o más de 100 m, una cara de 0° o 90°, una berma negativa,
        un ancla fuera de -1 000 a 10 000 m, un factor de malla de 0 o más de 1, y un NaN o un
        infinito se rechazan con ``des.profile_value_range`` nombrando el perfil, la clave del
        campo y el valor; un valor que no es un número, un error del programa."""
        bad = (("height_m", 0.0), ("height_m", 100.5), ("face_deg", 0.0), ("face_deg", 90.0),
               ("berm_m", -1.0), ("anchor_m", 10_000.5), ("anchor_m", -1_000.5),
               ("mesh_factor", 0.0), ("mesh_factor", 1.5), ("height_m", math.nan),
               ("berm_m", math.inf))
        for field, value in bad:
            with self.subTest(field=field, value=value):
                error = self.reject(new(DESD, **{field: value}))
                self.assertEqual((error.code, error.field),
                                 ("des.profile_value_range", f"des.bench.desd_10_45_6.{field}"))
                self.assertIn("«DESD_10_45_6»", error.text)
                if math.isfinite(value):
                    self.assertEqual(error.value, value)
        before = self.state()
        with self.assertRaises(TypeError):
            self.edit(new(DESD, height_m=True))
        with self.assertRaises(ValueError):
            self.edit(profiles.ProfileEdit(name=DESD, values={"altura": 5.0}))
        self.assertNothing(before)

    def test_everything_is_looked_at_before_writing_anything(self) -> None:
        """RF-013-19: se mira todo antes de escribir nada: un perfil válido y otro con un valor
        fuera de rango no dejan ninguno de los dos."""
        error = self.reject(new(DESD), new("Otro", face_deg=95.0))
        self.assertEqual(error.code, "des.profile_value_range")
        self.assertEqual([item.code for item in self.stored()], ["expl_10_60_6", "rest_5_35_6"])

    def test_completed_values_are_checked_by_name(self) -> None:
        """RF-013-19: un valor que se completa fuera de rango o sin valor se rechaza nombrando
        el perfil por su NOMBRE (no su código), la clave del campo y el valor."""
        for values, code in (({"face_deg": 90.0}, "des.profile_value_range"),
                             ({"berm_m": None}, "des.profile_value_missing")):
            with self.subTest(values=values):
                error = self.reject(profiles.ProfileEdit(code="expl_10_60_6", values=values),
                                    declared=declaration(version=self.v2.code))
                self.assertEqual(error.code, code)
                self.assertEqual(error.obj, "Perfil de banco «EXPL_10_60_6»")
                self.assertEqual(error.field, f"des.bench.expl_10_60_6.{next(iter(values))}")

    def test_an_edit_that_changes_nothing_is_a_program_error(self) -> None:
        """RF-013-19: una edición que no cambia nada (el mismo nombre y sin valores), de un perfil
        que no existe, repetida en la misma llamada o con valores sin declaración, es un error del
        programa (``ValueError``) y no deja nada."""
        before = self.state()
        edits = (profiles.ProfileEdit(code="rest_5_35_6", name=REST),
                 profiles.ProfileEdit(code="rest_5_35_6"),
                 profiles.ProfileEdit(code="no_existe", name="Otro"))
        for edit in edits:
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                self.edit(edit, declared=None)
        with self.assertRaises(ValueError):
            self.edit(profiles.ProfileEdit(code="rest_5_35_6", name="Uno"),
                      profiles.ProfileEdit(code="rest_5_35_6", name="Otro"), declared=None)
        self.assertNothing(before)


class RenameTest(_ProfilesCase):
    def setUp(self) -> None:
        super().setUp()
        self.edit(new(EXPL), new(REST))

    def test_renaming_does_not_change_the_code_or_the_values(self) -> None:
        """RF-013-18 (D-17): renombrar ``EXPL_10_60_6`` cambia solo su nombre: el código (la clave
        de sus parámetros), su ``uid``, quién lo creó y cuándo siguen igual, y sus valores y su
        historial no se tocan (sigue en la revisión 1); el renombrado es una operación registrada
        y el código antiguo no se reutiliza para un perfil nuevo. Cambiar solo las mayúsculas
        del nombre es renombrar el mismo perfil, no repetir un nombre."""
        before = self.stored()[0]
        values_before = self.values_of([before.code])
        made = self.edit(profiles.ProfileEdit(code=before.code, name="Explotación 10-60-6"),
                         declared=None)
        after = self.stored()[0]
        self.assertEqual(after.name, "Explotación 10-60-6")
        self.assertEqual((after.fid, after.uid, after.code, after.created_by, after.created_at),
                         (before.fid, before.uid, before.code, before.created_by,
                          before.created_at))
        self.assertEqual(self.values_of([before.code]), values_before)
        self.assertEqual(self.value(before.code, "height_m").rev, 1)
        self.assertEqual((made.created, made.renamed, made.completed), ((), (before.code,), ()))
        self.assertEqual(self.state()["operations"][-1], (profiles.EDIT_BENCH_PROFILES, "done"))
        self.assertEqual([item.code for item in self.stored()], ["expl_10_60_6", "rest_5_35_6"])
        self.edit(profiles.ProfileEdit(code=before.code, name="EXPLOTACIÓN 10-60-6"),
                  declared=None)
        self.assertEqual(self.stored()[0].name, "EXPLOTACIÓN 10-60-6")
        again = self.edit(new(EXPL))
        self.assertEqual(again.created, ("expl_10_60_6_2",))

    def test_a_swap_of_names_is_valid(self) -> None:
        """RF-013-19: los nombres se miden sobre los que quedan: intercambiar los de dos perfiles
        en la misma llamada es válido (cada código conserva sus valores) y no se queda a
        medias."""
        self.edit(profiles.ProfileEdit(code="expl_10_60_6", name=REST),
                  profiles.ProfileEdit(code="rest_5_35_6", name=EXPL), declared=None)
        self.assertEqual([(item.code, item.name) for item in self.stored()],
                         [("expl_10_60_6", REST), ("rest_5_35_6", EXPL)])
        self.assertEqual(self.value("expl_10_60_6", "face_deg").value, 60.0)


class CompleteTest(_ProfilesCase):
    def setUp(self) -> None:
        super().setUp()
        self.edit(new(EXPL))

    def test_a_profile_is_completed_in_a_version(self) -> None:
        """RF-013-18 (RF-009-24, RF-009-29): completar ``EXPL_10_60_6`` en V02 le escribe su valor
        propio de la versión (fila ``create`` del historial de la versión) sin tocar el del
        proyecto ni crear otra fila de perfil."""
        project_row = self.value("expl_10_60_6", "height_m")
        made = self.edit(
            profiles.ProfileEdit(code="expl_10_60_6", values={"height_m": 8.0,
                                                              "anchor_m": 120.0}),
            declared=declaration(version=self.v2.code, kind="ADOPTADO",
                                 reason="Altura del banco en la alternativa"))
        own = self.value("expl_10_60_6", "height_m", version=self.v2.code)
        self.assertEqual((own.value, own.kind, own.scope, own.scope_uid, own.rev),
                         (8.0, "ADOPTADO", "version", self.v2.uid, 1))
        self.assertEqual(self.value("expl_10_60_6", "anchor_m", version=self.v2.code).value,
                         120.0)
        self.assertIsNone(self.value("expl_10_60_6", "face_deg", version=self.v2.code))
        self.assertEqual(self.value("expl_10_60_6", "height_m"), project_row)
        self.assertEqual((made.created, made.renamed, made.completed),
                         ((), (), ("expl_10_60_6",)))
        self.assertEqual(len(self.stored()), 1)
        found = pipeline.bench_profiles(self.values_of(["expl_10_60_6"], self.v2.code),
                                        ["expl_10_60_6"])["expl_10_60_6"]
        self.assertEqual((found.height_m, found.face_deg, found.anchor_m), (8.0, 60.0, 120.0))

    def test_a_value_left_empty_is_filled_not_duplicated(self) -> None:
        """RF-013-18 (RF-008-04): un valor que el proyecto tiene vacío «sin confirmar» (lo deja
        una operación que lo pidió antes de que nadie lo declarara) se completa cambiándolo, no
        con un alta que fallaría: queda con su valor, ya confirmado, en la revisión 2 con una
        fila ``change``."""
        key = params.bench_key("rest_5_35_6", "height_m")
        with self.project.write_transaction() as conn:
            empty = self.store.ensure_default(conn, key, geoblender_version="0.1.0")
        self.assertIsNone(empty.value)
        self.assertTrue(empty.unconfirmed)
        self.edit(new(REST))
        record = self.value("rest_5_35_6", "height_m")
        self.assertEqual((record.value, record.unconfirmed, record.rev, record.kind),
                         (5.0, False, 2, "HIPÓTESIS"))
        self.assertEqual([entry.action.value for entry in self.store.history(key)],
                         ["default", "change"])
        self.assertEqual(self.value("rest_5_35_6", "face_deg").rev, 1)

    def test_an_empty_value_of_the_project_is_not_the_versions(self) -> None:
        """RF-013-18 (RF-009-29): el vacío «sin confirmar» del proyecto no es el valor de una
        versión: tras crear un perfil solo en V02, completar en V02 un valor que ya tiene se
        rechaza (``core.param_exists``) aunque el del proyecto siga vacío, y su valor no cambia."""
        key = params.bench_key("otro", "berm_m")
        with self.project.write_transaction() as conn:
            self.store.ensure_default(conn, key, geoblender_version="0.1.0")
        in_v2 = declaration(version=self.v2.code)
        self.edit(new("Otro"), declared=in_v2)
        before = self.state()
        with self.assertRaises(core_params.ParamError) as caught:
            self.edit(profiles.ProfileEdit(code="otro", values={"berm_m": 3.0}), declared=in_v2)
        self.assertEqual(caught.exception.code, "core.param_exists")
        self.assertEqual(self.value("otro", "berm_m", version=self.v2.code).value, 6.0)
        self.assertEqual(self.value("otro", "berm_m", version=self.v2.code).rev, 1)
        self.assertIsNone(self.value("otro", "berm_m").value)
        after = self.state()
        self.assertEqual({k: v for k, v in after.items() if k != "operations"},
                         {k: v for k, v in before.items() if k != "operations"})

    def test_a_value_already_declared_is_not_overwritten(self) -> None:
        """RF-013-18: completar un valor que ya tiene la versión (o el proyecto) se rechaza con
        el ``ParamError`` ``core.param_exists`` (cambiarlo es de «Parámetros»), y no queda nada
        de lo demás de la llamada, ni siquiera un perfil nuevo."""
        before = self.state()
        with self.assertRaises(core_params.ParamError) as caught:
            self.edit(new(REST), profiles.ProfileEdit(code="expl_10_60_6",
                                                      values={"berm_m": 7.0}))
        self.assertEqual(caught.exception.code, "core.param_exists")
        after = self.state()
        self.assertEqual(after["operations"][-1], (profiles.EDIT_BENCH_PROFILES, "failed"))
        self.assertEqual({k: v for k, v in after.items() if k != "operations"},
                         {k: v for k, v in before.items() if k != "operations"})
        self.assertEqual(self.value("expl_10_60_6", "berm_m").value, 6.0)


class CalculationTest(_ProfilesCase):
    def test_a_calculation_with_an_incomplete_profile_names_it_by_its_name(self) -> None:
        """RF-013-19: calcular con un perfil al que le falta un valor en la versión (aquí, uno
        creado solo en V02 y pedido en V01) se rechaza antes de registrar nada con
        ``des.profile_value_missing``, que nombra el perfil por su NOMBRE de ``des_bench_profile``
        y la clave del campo, y no por su código; un perfil sin fila se nombra por su código."""
        self.edit(new(EXPL), declared=declaration(version=self.v2.code))
        request = model.DesignRequest(name="Escalón", envelope="Env", sense="cut",
                                      base_profile="expl_10_60_6")
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            design_store.prepare_design(self.project, request, dfx.START_DATASET,
                                        version=self.v1.uid)
        error = caught.exception
        self.assertEqual((error.code, error.field),
                         ("des.profile_value_missing", "des.bench.expl_10_60_6.height_m"))
        self.assertEqual(error.obj, "Perfil de banco «EXPL_10_60_6»")
        self.assertIn("«EXPL_10_60_6»", error.text)
        self.assertEqual(self.state(), before)
        request = model.DesignRequest(name="Escalón", envelope="Env", sense="cut",
                                      base_profile="sin_fila")
        with self.assertRaises(messages.DesignError) as caught:
            design_store.prepare_design(self.project, request, dfx.START_DATASET,
                                        version=self.v1.uid)
        self.assertEqual(caught.exception.obj, "Perfil de banco «sin_fila»")
        self.assertEqual(self.state(), before)


class ReadTest(_ProfilesCase):
    def test_a_project_without_profiles_reads_none(self) -> None:
        """RF-013-18: sin la tabla (aún nadie creó un perfil) no hay perfiles ni nombres, sin
        error; con ellos salen en el orden en que se crearon, con su nombre por código."""
        with self.project.read() as conn:
            self.assertEqual(profiles.read_profiles(conn), ())
            self.assertEqual(profiles.profile_names(conn), {})
        self.edit(new(REST), new(EXPL))
        self.assertEqual([item.name for item in self.stored()], [REST, EXPL])
        with self.project.read() as conn:
            self.assertEqual(profiles.profile_names(conn),
                             {"rest_5_35_6": REST, "expl_10_60_6": EXPL})


class DeclarationTest(unittest.TestCase):
    def test_the_operation_is_declared_for_bl(self) -> None:
        """RF-013-18: ``des.edit_bench_profiles`` es una operación de proyecto, de ``des``, no
        repetible, que lanza la orden del catálogo, y su nombre visible está en español en el
        catálogo de mensajes."""
        (operation,) = profiles.OPERATIONS
        self.assertEqual(operation.op_type, "des.edit_bench_profiles")
        self.assertEqual((operation.module, operation.scope, operation.repeatable),
                         ("des", "project", False))
        self.assertEqual(operation.commands, ("geoblender.des_edit_bench_profiles",))
        table = i18n.load_messages()
        self.assertIn(operation.label_msgid, table)
        self.assertNotEqual(table[operation.label_msgid], operation.label_msgid)

    def test_the_dataset_is_not_editable_in_qgis(self) -> None:
        """RF-013-18 (plan §5.2.1): el dato de los perfiles es una tabla de atributos de ``des``
        que se lee con ``core.gpkg_layer@1`` y no se edita en QGIS (los valores están en
        parámetros, con su historial)."""
        spec = profiles.dataset_spec()
        self.assertEqual((spec.name, spec.module, spec.kind, spec.locator, spec.reader,
                          spec.role, spec.qgis_editable),
                         ("des_bench_profile", "des", "table", "des_bench_profile",
                          "core.gpkg_layer@1", "profiles", False))


if __name__ == "__main__":
    unittest.main()
