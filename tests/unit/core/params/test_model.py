# SPDX-License-Identifier: GPL-3.0-or-later
"""Definiciones de parámetros tipados (spec 008, T03; RF-008-01, RF-008-03; plan 008 §5.3.1
y §5.3.4).

Cada módulo declara sus parámetros con :class:`core.params.ParamDef`: clave
``<código>.<nombre>``, tipo de valor, unidad del catálogo, rango, valor y tipo por defecto
(ADOPTADO o HIPÓTESIS, nunca MEDIDO ni CALCULADO) y procedencia. ``check()`` comprueba un
valor del programa y ``parse_value`` uno tecleado, con su unidad (RF-008-03).

La 006 hizo antes un ``ParamDef`` provisional en ``gis/params.py`` (commit ``39b28f1``):
``core.params.ParamDef`` tiene su misma firma, así que una **copia literal de sus 17
llamadas** se ejecuta aquí sin cambiar nada, y da los mismos valores normalizados, los
mismos textos y el mismo ``range_text()``, con códigos ``core.param_*`` en lugar de
``gis.param_*``. Lo esperado de :data:`PROVISIONAL_CHECK` y :data:`PROVISIONAL_RANGES` lo
dio la provisional de ``39b28f1`` con esos mismos valores (copiado aquí, no recalculado),
salvo el separador de miles de T71 en los números de cuatro cifras o más.

Spec 008, T71: los valores, los rangos y los rechazos se leen como las cifras, con el
separador de miles (spec 003, II §2.4: «500 000» en español y «500,000» en inglés);
``format_value(..., grouped=False)``, sin él, como se teclea.
"""

import inspect
import math
import string
import unittest

import numpy

from tests.support.package import import_geoblender

params = import_geoblender("core.params")
store = import_geoblender("core.params.store")
figures = import_geoblender("core.provenance.figures")
core_defs = import_geoblender("core.params.core_defs")
units = import_geoblender("core.units")
errors = import_geoblender("core.errors")

ParamDef = params.ParamDef
THIN = "\u202f"  # separador de miles de las cifras en español (spec 003, II §2.4; T71)
DIMENSIONLESS = units.DIMENSIONLESS

# --- Copia literal de gis/params.py (39b28f1): las 17 llamadas de DEFINITIONS ---------------

_D4 = "Spec 006, D-4 (DP-43): sin dato salvo cobertura total"
_D5 = "Spec 006, D-5 (DP-44): 1 mm en planta y 0,01 m en cota"
_A12 = "Plan 006 §5.2.5 y A12 (TIN desde curvas)"
_CONTOURS = "Spec 006 §11: curvas del terreno (R-61 fija las de los diseños)"

DEFINITIONS: tuple[ParamDef, ...] = (
    ParamDef("gis.resample.min_valid_fraction", "float", DIMENSIONLESS, 1.0, 0.0, 1.0,
             ("RF-006-11",), _D4, min_exclusive=True),
    ParamDef("gis.reproject.supersample", "int", DIMENSIONLESS, 4, 1, 16,
             ("RF-006-05",), "Plan 006 §6, D7: submuestreo de 4 × 4 por celda"),
    ParamDef("gis.points.dup_xy_tol_m", "float", "m", 0.001, 0.0, 1.0,
             ("RF-006-14",), _D5, min_exclusive=True),
    ParamDef("gis.points.dup_z_tol_m", "float", "m", 0.01, 0.0, 1.0,
             ("RF-006-14",), _D5),
    ParamDef("gis.tin.contour_densify_m", "float", "m", 5.0, 0.0, 100.0,
             ("RF-006-16",), _A12, min_exclusive=True),
    ParamDef("gis.tin.flat_max_passes", "int", DIMENSIONLESS, 3, 0, 10,
             ("RF-006-16",), _A12),
    ParamDef("gis.tin.max_flat_pct", "float", "%", 1.0, 0.0, 100.0,
             ("RF-006-16",), "Spec 006, RF-006-16 (D-6)"),
    ParamDef("gis.tin.blender_cdt_max_s", "float", "s", 2.0, 0.0, 2.0,
             ("RF-006-13", "RF-006-28"),
             "Plan 006 §9, D-12 (DP-54): excepción del principio 9, hasta 2 s"),
    ParamDef("gis.contours.interval_m", "float", "m", 1.0, 0.0, 1000.0,
             ("RF-006-18",), _CONTOURS, min_exclusive=True),
    ParamDef("gis.contours.index_every_m", "float", "m", 5.0, 0.0, 10000.0,
             ("RF-006-18",), _CONTOURS, min_exclusive=True),
    ParamDef("gis.contours.index_offset_m", "float", "m", 0.0, -100.0, 100.0,
             ("RF-006-18",), _CONTOURS),
    ParamDef("gis.contours.simplify_m", "float", "m", 0.0, 0.0, 100.0,
             ("RF-006-18",), _CONTOURS),
    ParamDef("gis.contours.min_length_m", "float", "m", 0.0, 0.0, 10000.0,
             ("RF-006-18",), _CONTOURS),
    ParamDef("gis.vertical.ellipsoidal_band_m", "json", "m", (40.0, 60.0), 0.0, 200.0,
             ("RF-006-06",), "Spec 006, D-8 (DP-46): península y Baleares", length=2),
    ParamDef("gis.validate.z_range_m", "json", "m", (-500.0, 5000.0), -11000.0, 9000.0,
             ("RF-006-23",), "Spec 006 §11: rango plausible de cotas", length=2),
    ParamDef("gis.import.max_cells", "int", DIMENSIONLESS, 100_000_000, 1, 100_000_000,
             ("RF-006-09",), "Spec 006 §8 y §11 (memoria: RNF-006-08)"),
    ParamDef("gis.view.lod_steps_m", "json", "m", (2.0, 5.0), 0.5, 100.0,
             ("RF-006-22",), "Spec 006, RF-006-22: versiones de 2 y 5 m", length=2),
)
"""Los parámetros de la tabla del plan 006 §5.2.5, en su orden."""

# --- Lo que dio la provisional de 39b28f1 -----------------------------------------------------
# Con el separador de miles de las cifras en los números de cuatro cifras o más, que la
# provisional no ponía (spec 008, T71: los valores se leen como las cifras).

# (clave, valor, resultado): el valor normalizado (con su tipo) o (código, texto en español),
# con el código gis.param_* ya escrito como core.param_*.
PROVISIONAL_CHECK: tuple[tuple[str, object, object], ...] = (
    ("gis.resample.min_valid_fraction", 0.5, 0.5),
    ("gis.resample.min_valid_fraction", 1.0, 1.0),
    ("gis.resample.min_valid_fraction", 1, 1.0),
    ("gis.resample.min_valid_fraction", 0.0, ("core.param_out_of_range", "Parámetro «gis.resample.min_valid_fraction»: 0 está fuera de su rango (0; 1].")),
    ("gis.resample.min_valid_fraction", 1.5, ("core.param_out_of_range", "Parámetro «gis.resample.min_valid_fraction»: 1,5 está fuera de su rango (0; 1].")),
    ("gis.resample.min_valid_fraction", -0.1, ("core.param_out_of_range", "Parámetro «gis.resample.min_valid_fraction»: -0,1 está fuera de su rango (0; 1].")),
    ("gis.resample.min_valid_fraction", "0,5", ("core.param_not_number", "Parámetro «gis.resample.min_valid_fraction»: «0,5» no es un número.")),
    ("gis.resample.min_valid_fraction", True, ("core.param_not_number", "Parámetro «gis.resample.min_valid_fraction»: «sí» no es un número.")),
    ("gis.resample.min_valid_fraction", math.nan, ("core.param_not_number", "Parámetro «gis.resample.min_valid_fraction»: «nan» no es un número.")),
    ("gis.resample.min_valid_fraction", math.inf, ("core.param_not_number", "Parámetro «gis.resample.min_valid_fraction»: «inf» no es un número.")),
    ("gis.resample.min_valid_fraction", -math.inf, ("core.param_not_number", "Parámetro «gis.resample.min_valid_fraction»: «-inf» no es un número.")),
    ("gis.reproject.supersample", 4, 4),
    ("gis.reproject.supersample", 8.0, 8),
    ("gis.reproject.supersample", 16, 16),
    ("gis.reproject.supersample", 4.5, ("core.param_not_integer", "Parámetro «gis.reproject.supersample»: «4,5» no es un número entero.")),
    ("gis.reproject.supersample", True, ("core.param_not_integer", "Parámetro «gis.reproject.supersample»: «sí» no es un número entero.")),
    ("gis.reproject.supersample", "4", ("core.param_not_integer", "Parámetro «gis.reproject.supersample»: «4» no es un número entero.")),
    ("gis.reproject.supersample", 0, ("core.param_out_of_range", "Parámetro «gis.reproject.supersample»: 0 está fuera de su rango [1; 16].")),
    ("gis.reproject.supersample", 17, ("core.param_out_of_range", "Parámetro «gis.reproject.supersample»: 17 está fuera de su rango [1; 16].")),
    ("gis.reproject.supersample", math.inf, ("core.param_not_integer", "Parámetro «gis.reproject.supersample»: «inf» no es un número entero.")),
    ("gis.points.dup_xy_tol_m", 0.001, 0.001),
    ("gis.points.dup_xy_tol_m", 0.0, ("core.param_out_of_range", "Parámetro «gis.points.dup_xy_tol_m»: 0 está fuera de su rango (0; 1] m.")),
    ("gis.points.dup_xy_tol_m", 1.0000001, ("core.param_out_of_range", "Parámetro «gis.points.dup_xy_tol_m»: 1,0000001 está fuera de su rango (0; 1] m.")),
    ("gis.points.dup_z_tol_m", 0, 0.0),
    ("gis.points.dup_z_tol_m", 1.0, 1.0),
    ("gis.points.dup_z_tol_m", -0.01, ("core.param_out_of_range", "Parámetro «gis.points.dup_z_tol_m»: -0,01 está fuera de su rango [0; 1] m.")),
    ("gis.tin.contour_densify_m", 0.0, ("core.param_out_of_range", "Parámetro «gis.tin.contour_densify_m»: 0 está fuera de su rango (0; 100] m.")),
    ("gis.tin.contour_densify_m", 100, 100.0),
    ("gis.tin.flat_max_passes", 10, 10),
    ("gis.tin.flat_max_passes", 0.0, 0),
    ("gis.tin.flat_max_passes", 11, ("core.param_out_of_range", "Parámetro «gis.tin.flat_max_passes»: 11 está fuera de su rango [0; 10].")),
    ("gis.tin.flat_max_passes", -1, ("core.param_out_of_range", "Parámetro «gis.tin.flat_max_passes»: -1 está fuera de su rango [0; 10].")),
    ("gis.tin.max_flat_pct", 100.0, 100.0),
    ("gis.tin.max_flat_pct", 100.5, ("core.param_out_of_range", "Parámetro «gis.tin.max_flat_pct»: 100,5 está fuera de su rango [0; 100] %.")),
    ("gis.tin.blender_cdt_max_s", 2, 2.0),
    ("gis.tin.blender_cdt_max_s", 2.5, ("core.param_out_of_range", "Parámetro «gis.tin.blender_cdt_max_s»: 2,5 está fuera de su rango [0; 2] s.")),
    ("gis.contours.interval_m", 0.0, ("core.param_out_of_range", f"Parámetro «gis.contours.interval_m»: 0 está fuera de su rango (0; 1{THIN}000] m.")),
    ("gis.contours.interval_m", 1000.0, 1000.0),
    ("gis.contours.index_every_m", 5, 5.0),
    ("gis.contours.index_every_m", 10000.25, ("core.param_out_of_range", f"Parámetro «gis.contours.index_every_m»: 10{THIN}000,25 está fuera de su rango (0; 10{THIN}000] m.")),
    ("gis.contours.index_offset_m", -100.0, -100.0),
    ("gis.contours.index_offset_m", -100.5, ("core.param_out_of_range", "Parámetro «gis.contours.index_offset_m»: -100,5 está fuera de su rango [-100; 100] m.")),
    ("gis.contours.simplify_m", numpy.float64(2.5), 2.5),
    ("gis.contours.min_length_m", 10000.0, 10000.0),
    ("gis.vertical.ellipsoidal_band_m", (40.0, 60.0), (40.0, 60.0)),
    ("gis.vertical.ellipsoidal_band_m", [40, 60], (40.0, 60.0)),
    ("gis.vertical.ellipsoidal_band_m", (60.0, 40.0), ("core.param_not_list", "Parámetro «gis.vertical.ellipsoidal_band_m»: «(60.0, 40.0)» no es una lista de 2 números en orden creciente.")),
    ("gis.vertical.ellipsoidal_band_m", (40.0, 40.0), ("core.param_not_list", "Parámetro «gis.vertical.ellipsoidal_band_m»: «(40.0, 40.0)» no es una lista de 2 números en orden creciente.")),
    ("gis.vertical.ellipsoidal_band_m", (40.0,), ("core.param_not_list", "Parámetro «gis.vertical.ellipsoidal_band_m»: «(40.0,)» no es una lista de 2 números en orden creciente.")),
    ("gis.vertical.ellipsoidal_band_m", (40.0, 50.0, 60.0), ("core.param_not_list", "Parámetro «gis.vertical.ellipsoidal_band_m»: «(40.0, 50.0, 60.0)» no es una lista de 2 números en orden creciente.")),
    ("gis.vertical.ellipsoidal_band_m", "40;60", ("core.param_not_list", "Parámetro «gis.vertical.ellipsoidal_band_m»: «40;60» no es una lista de 2 números en orden creciente.")),
    ("gis.vertical.ellipsoidal_band_m", 40.0, ("core.param_not_list", "Parámetro «gis.vertical.ellipsoidal_band_m»: «40» no es una lista de 2 números en orden creciente.")),
    ("gis.vertical.ellipsoidal_band_m", (math.nan, 60.0), ("core.param_not_list", "Parámetro «gis.vertical.ellipsoidal_band_m»: «(nan, 60.0)» no es una lista de 2 números en orden creciente.")),
    ("gis.vertical.ellipsoidal_band_m", (True, 60.0), ("core.param_not_list", "Parámetro «gis.vertical.ellipsoidal_band_m»: «(True, 60.0)» no es una lista de 2 números en orden creciente.")),
    ("gis.vertical.ellipsoidal_band_m", (40.0, 300.0), ("core.param_out_of_range", "Parámetro «gis.vertical.ellipsoidal_band_m»: [40; 300] está fuera de su rango [0; 200] m.")),
    ("gis.validate.z_range_m", (-11000.0, 9000.0), (-11000.0, 9000.0)),
    ("gis.validate.z_range_m", (-11000.5, 0.0), ("core.param_out_of_range", f"Parámetro «gis.validate.z_range_m»: [-11{THIN}000,5; 0] está fuera de su rango [-11{THIN}000; 9{THIN}000] m.")),
    ("gis.import.max_cells", 100_000_000, 100000000),
    ("gis.import.max_cells", 1e8, 100000000),
    ("gis.import.max_cells", 100_000_001, ("core.param_out_of_range", f"Parámetro «gis.import.max_cells»: 100{THIN}000{THIN}001 está fuera de su rango [1; 100{THIN}000{THIN}000].")),
    ("gis.view.lod_steps_m", (0.5, 100.0), (0.5, 100.0)),
    ("gis.view.lod_steps_m", (0.25, 2.0), ("core.param_out_of_range", "Parámetro «gis.view.lod_steps_m»: [0,25; 2] está fuera de su rango [0,5; 100] m.")),
)

# clave → (range_text() en español, en inglés)
PROVISIONAL_RANGES: dict[str, tuple[str, str]] = {
    "gis.resample.min_valid_fraction": ("(0; 1]", "(0, 1]"),
    "gis.reproject.supersample": ("[1; 16]", "[1, 16]"),
    "gis.points.dup_xy_tol_m": ("(0; 1] m", "(0, 1] m"),
    "gis.points.dup_z_tol_m": ("[0; 1] m", "[0, 1] m"),
    "gis.tin.contour_densify_m": ("(0; 100] m", "(0, 100] m"),
    "gis.tin.flat_max_passes": ("[0; 10]", "[0, 10]"),
    "gis.tin.max_flat_pct": ("[0; 100] %", "[0, 100] %"),
    "gis.tin.blender_cdt_max_s": ("[0; 2] s", "[0, 2] s"),
    "gis.contours.interval_m": (f"(0; 1{THIN}000] m", "(0, 1,000] m"),
    "gis.contours.index_every_m": (f"(0; 10{THIN}000] m", "(0, 10,000] m"),
    "gis.contours.index_offset_m": ("[-100; 100] m", "[-100, 100] m"),
    "gis.contours.simplify_m": ("[0; 100] m", "[0, 100] m"),
    "gis.contours.min_length_m": (f"[0; 10{THIN}000] m", "[0, 10,000] m"),
    "gis.vertical.ellipsoidal_band_m": ("[0; 200] m", "[0, 200] m"),
    "gis.validate.z_range_m": (f"[-11{THIN}000; 9{THIN}000] m", "[-11,000, 9,000] m"),
    "gis.import.max_cells": (f"[1; 100{THIN}000{THIN}000]", "[1, 100,000,000]"),
    "gis.view.lod_steps_m": ("[0,5; 100] m", "[0.5, 100] m"),
}

# Los cuatro mensajes de gis/messages.py (39b28f1): código gis.* → (msgid, español).
PROVISIONAL_MESSAGES: dict[str, tuple[str, str]] = {
    "param_not_number": (
        "Parameter «{key}»: «{value}» is not a number.",
        "Parámetro «{key}»: «{value}» no es un número.",
    ),
    "param_not_integer": (
        "Parameter «{key}»: «{value}» is not a whole number.",
        "Parámetro «{key}»: «{value}» no es un número entero.",
    ),
    "param_not_list": (
        "Parameter «{key}»: «{value}» is not a list of {length} numbers in ascending order.",
        "Parámetro «{key}»: «{value}» no es una lista de {length} números en orden creciente.",
    ),
    "param_out_of_range": (
        "Parameter «{key}»: {value} is outside its range {range}.",
        "Parámetro «{key}»: {value} está fuera de su rango {range}.",
    ),
}

# Campos de la provisional, en su orden: los ocho primeros, también por posición.
PROVISIONAL_FIELDS = (
    "key", "value_type", "unit", "default", "minimum", "maximum", "requirements", "source",
    "min_exclusive", "length", "kind", "source_kind",
)

BY_KEY = {definition.key: definition for definition in DEFINITIONS}


def swell_factor(**changes: object) -> ParamDef:
    """El K de esponjamiento de los ejemplos de la spec §8: HIPÓTESIS adimensional en
    [1; 2]."""
    fields: dict[str, object] = {
        "key": "res.swell_factor", "value_type": "float", "unit": "-", "default": 1.25,
        "minimum": 1.0, "maximum": 2.0, "requirements": ("RF-008-03",),
        "source": "Prueba: K de esponjamiento sin dato", "kind": "HIPÓTESIS",
    }
    fields.update(changes)
    return ParamDef(**fields)


def fraction(**changes: object) -> ParamDef:
    """Un parámetro declarado en fracción (adimensional, [0; 1])."""
    fields: dict[str, object] = {
        "key": "res.recovery", "value_type": "float", "unit": "-", "default": 0.9,
        "minimum": 0.0, "maximum": 1.0, "requirements": ("RF-008-03",),
        "source": "Prueba: recuperación minera",
    }
    fields.update(changes)
    return ParamDef(**fields)


def _placeholders(text: str) -> set[str]:
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}


class GisCompatibilityTest(unittest.TestCase):
    """Plan 008 §5.3.4 (I-1): ``core.params.ParamDef`` sustituye al provisional de
    ``gis/params.py`` (``39b28f1``) sin cambiar sus llamadas (RF-008-01, RF-008-03)."""

    def test_literal_copy_builds(self) -> None:
        """RF-008-01: las 17 llamadas copiadas tal cual se ejecutan; cada definición es del
        módulo ``gis`` (deducido de la clave), ADOPTADO de origen ``algorithm``, con su
        valor por defecto ya normalizado."""
        self.assertEqual(len(DEFINITIONS), 17)
        self.assertEqual(len(BY_KEY), 17)
        for definition in DEFINITIONS:
            with self.subTest(key=definition.key):
                self.assertEqual(definition.module, "gis")
                self.assertEqual(definition.kind, "ADOPTADO")
                self.assertIs(definition.kind, params.ParamKind.ADOPTADO)
                self.assertEqual(definition.source_kind, "algorithm")
                self.assertEqual(definition.scope, "project")
                self.assertFalse(definition.allow_empty)
                default = definition.check(definition.default)
                self.assertEqual(default, definition.default)
                self.assertIs(type(default), type(definition.default))

    def test_signature_of_provisional(self) -> None:
        """Plan 008 §5.3.1: la misma firma que la provisional: los ocho primeros campos
        también por posición y en su orden, y el resto con su nombre."""
        signature = inspect.signature(ParamDef)
        names = list(signature.parameters)
        self.assertEqual(names[:12], list(PROVISIONAL_FIELDS))
        for name in PROVISIONAL_FIELDS[:8]:
            self.assertEqual(
                signature.parameters[name].kind, inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
        for name in PROVISIONAL_FIELDS[8:]:
            self.assertEqual(signature.parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
        for name in ("allow_empty", "choices", "scope", "label_msgid", "description_msgid"):
            self.assertIn(name, signature.parameters)

    def test_check_matches_provisional(self) -> None:
        """RF-008-03: para la tabla de valores (en rango, en el extremo excluido, fuera de
        rango, no numérico, booleano, NaN, infinito, listas desordenadas o de otra
        longitud), ``check()`` da el mismo valor normalizado y del mismo tipo que la
        provisional, o el mismo texto con el código ``core.param_*``."""
        self.assertEqual(len(PROVISIONAL_CHECK), 62)
        for key, value, expected in PROVISIONAL_CHECK:
            with self.subTest(key=key, value=value):
                definition = BY_KEY[key]
                if isinstance(expected, tuple) and isinstance(expected[0], str):
                    code, text = expected
                    with self.assertRaises(params.ParamError) as caught:
                        definition.check(value)
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(caught.exception.text, text)
                    self.assertEqual(str(caught.exception), text)
                else:
                    result = definition.check(value)
                    self.assertEqual(result, expected)
                    self.assertIs(type(result), type(expected))
                    if isinstance(result, tuple):
                        self.assertTrue(all(type(item) is float for item in result))

    def test_range_text_matches_provisional(self) -> None:
        """RF-008-03: ``range_text()`` como la provisional, en español y en inglés
        («[0; 2] s», «(0; 1]», sin unidad si es adimensional)."""
        self.assertEqual(set(PROVISIONAL_RANGES), set(BY_KEY))
        for key, (spanish, english) in PROVISIONAL_RANGES.items():
            with self.subTest(key=key):
                self.assertEqual(BY_KEY[key].range_text(), spanish)
                self.assertEqual(BY_KEY[key].range_text("es"), spanish)
                self.assertEqual(BY_KEY[key].range_text("en"), english)

    def test_messages_match_provisional(self) -> None:
        """Principio 10: los cuatro mensajes de la provisional, con el mismo ``msgid`` y el
        mismo texto en español, ahora con el código ``core.param_*``."""
        for suffix, (msgid, spanish) in PROVISIONAL_MESSAGES.items():
            with self.subTest(code=suffix):
                message = params.MESSAGES[f"core.{suffix}"]
                self.assertEqual(message.msgid, msgid)
                self.assertEqual(message.es, spanish)

    def test_error_is_a_validation_error_with_object_and_field(self) -> None:
        """RF-008-03: el rechazo es un ``ValidationError`` de Geoblender con el objeto
        «Parámetro», el campo (la clave), el valor, la unidad y el rango."""
        definition = BY_KEY["gis.tin.blender_cdt_max_s"]
        with self.assertRaises(errors.ValidationError) as caught:
            definition.check(2.5)
        error = caught.exception
        self.assertIsInstance(error, params.ParamError)
        self.assertEqual(error.obj, "Parámetro")
        self.assertEqual(error.field, "gis.tin.blender_cdt_max_s")
        self.assertEqual(error.value, 2.5)
        self.assertEqual(error.values["key"], "gis.tin.blender_cdt_max_s")
        self.assertEqual(error.values["unit"], "s")
        self.assertEqual(error.values["range"], "[0; 2] s")
        self.assertEqual(error.msgid, PROVISIONAL_MESSAGES["param_out_of_range"][0])
        self.assertEqual(
            params.render(error.code, language="en", **error.values),
            "Parameter «gis.tin.blender_cdt_max_s»: 2.5 is outside its range [0; 2] s.",
        )

    def test_integer_too_large_for_float64(self) -> None:
        """Un entero que no cabe en un float64 no es un número válido (como en la
        provisional)."""
        with self.assertRaises(params.ParamError) as caught:
            BY_KEY["gis.reproject.supersample"].check(2**1100)
        self.assertEqual(caught.exception.code, "core.param_not_integer")
        with self.assertRaises(params.ParamError) as caught:
            BY_KEY["gis.points.dup_z_tol_m"].check(2**1100)
        self.assertEqual(caught.exception.code, "core.param_not_number")


class DefinitionTest(unittest.TestCase):
    """RF-008-01 (spec §6): una definición incoherente es un error del programa
    (``ValueError``) y no se construye."""

    def test_enums(self) -> None:
        """RF-008-01: los cuatro tipos (``HIPÓTESIS`` con tilde, como ADR-0013 y
        ``gb_parameter.kind``), los cinco tipos de valor de ``gb_parameter.value_type`` y
        los cinco orígenes de ``gb_parameter.source_kind``."""
        self.assertEqual(
            [kind.value for kind in params.ParamKind],
            ["MEDIDO", "CALCULADO", "ADOPTADO", "HIPÓTESIS"],
        )
        self.assertEqual(params.ParamKind.HIPOTESIS, "HIPÓTESIS")
        self.assertEqual(
            [value_type.value for value_type in params.ValueType],
            ["float", "int", "bool", "text", "json"],
        )
        self.assertEqual(
            [source.value for source in params.SourceKind],
            ["document", "standard", "person", "operation", "algorithm"],
        )

    def test_default_kind_is_adopted_or_hypothesis(self) -> None:
        """RF-008-01, RF-008-04: el tipo por defecto es ADOPTADO o HIPÓTESIS; MEDIDO lo mide
        alguien y CALCULADO lo produce una operación, así que no son un valor por
        defecto. Un tipo fuera de los cuatro tampoco."""
        self.assertIs(swell_factor().kind, params.ParamKind.HIPOTESIS)
        self.assertIs(fraction().kind, params.ParamKind.ADOPTADO)
        for kind in ("MEDIDO", "CALCULADO", params.ParamKind.CALCULADO):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, f"res.swell_factor.*{kind}"):
                    swell_factor(kind=kind)
        for kind in ("HIPOTESIS", "adoptado", "", None):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "res.swell_factor"):
                    swell_factor(kind=kind)

    def test_malformed_key(self) -> None:
        """La clave es ``<código>.<nombre>[.<más>]``, en minúsculas, con un código de módulo
        de ``docs/sdd/convenciones.md`` §5; el módulo se deduce de ella."""
        self.assertEqual(swell_factor().module, "res")
        self.assertEqual(swell_factor(key="dh.desurvey.min_step_m").module, "dh")
        for key in ("swell_factor", "res.", ".swell", "res..swell", "Res.swell",
                    "res.Swell", "res.swell-factor", "res.2swell", "xyz.swell",
                    "reserves.swell", " res.swell", "res.swell ", ""):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "clave"):
                    swell_factor(key=key)

    def test_unit_from_catalog(self) -> None:
        """RF-008-03: la unidad es un código del catálogo de unidades (``m3``, no «m³»);
        un sí/no o un texto es adimensional."""
        self.assertEqual(fraction(key="res.volume_m3", unit="m3", maximum=1e9).unit, "m3")
        for unit in ("m³", "mm", "metros", "", None, ["m"]):
            with self.subTest(unit=unit):
                with self.assertRaisesRegex(ValueError, "unidad"):
                    fraction(unit=unit)
        with self.assertRaisesRegex(ValueError, "unidad"):
            ParamDef("res.use_bench", "bool", "m", True, requirements=("RF-008-03",),
                     source="prueba")

    def test_inverted_or_misplaced_range(self) -> None:
        """Un rango invertido no se declara; ni un rango en un sí/no o un texto, ni el
        extremo excluido sin mínimo."""
        with self.assertRaisesRegex(ValueError, "rango"):
            swell_factor(minimum=2.0, maximum=1.0)
        with self.assertRaisesRegex(ValueError, "rango"):
            ParamDef("res.use_bench", "bool", "-", True, 0, 1, ("RF-008-03",), "prueba")
        with self.assertRaisesRegex(ValueError, "rango"):
            swell_factor(minimum=None, min_exclusive=True)
        for bound in (math.nan, math.inf, True, "1"):
            with self.subTest(bound=bound):
                with self.assertRaisesRegex(ValueError, "rango"):
                    swell_factor(minimum=bound)

    def test_default_must_be_valid_and_normalized(self) -> None:
        """Como en la provisional: el valor por defecto está en el rango y ya normalizado
        (``1`` no es el ``1.0`` de un ``float``); ``None`` solo si admite «sin valor»."""
        for default in (5.0, 1, None, math.nan):
            with self.subTest(default=default):
                with self.assertRaisesRegex(ValueError, "por defecto"):
                    swell_factor(default=default)
        self.assertIsNone(swell_factor(default=None, allow_empty=True).default)

    def test_requirements_and_source(self) -> None:
        """La procedencia y los requisitos no están vacíos (principio 2)."""
        for changes in ({"source": ""}, {"source": "   "}, {"requirements": ()},
                        {"requirements": "RF-008-03"}, {"requirements": ("",)}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    swell_factor(**changes)
        self.assertEqual(swell_factor(requirements=["RF-008-03"]).requirements, ("RF-008-03",))

    def test_other_fields(self) -> None:
        """Tipo de valor, origen, longitud (solo de un ``json``), opciones (solo de un
        texto), ámbito (proyecto o versión) y ``msgid`` de su etiqueta."""
        for changes in ({"value_type": "number"}, {"source_kind": "persona"},
                        {"length": 2}, {"choices": ("a",)}, {"scope": "sector"},
                        {"label_msgid": ""}, {"description_msgid": 3}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    swell_factor(**changes)
        versioned = swell_factor(scope="version", label_msgid="Swell factor",
                                 source_kind="person")
        self.assertEqual(versioned.scope, "version")
        self.assertIs(versioned.source_kind, params.SourceKind.PERSON)
        self.assertIs(swell_factor().value_type, params.ValueType.FLOAT)
        for length in (None, 0, "1", True):
            with self.subTest(length=length):
                with self.assertRaises(ValueError):
                    ParamDef("gis.view.steps_m", "json", "m", (2.0,), 0.5, 100.0,
                             ("RF-008-03",), "prueba", length=length)

    def test_definitions_are_values(self) -> None:
        """Dos definiciones iguales son iguales (``str`` o ``StrEnum`` da lo mismo) y no se
        pueden cambiar."""
        self.assertEqual(swell_factor(), swell_factor(kind=params.ParamKind.HIPOTESIS,
                                                       value_type=params.ValueType.FLOAT))
        self.assertEqual(hash(swell_factor()), hash(swell_factor()))
        with self.assertRaises(AttributeError):
            swell_factor().default = 1.5  # type: ignore[misc]


class OtherValueTypesTest(unittest.TestCase):
    """RF-008-03: sí/no, texto (con opciones), «sin valor» y rangos abiertos."""

    def test_bool(self) -> None:
        """Un sí/no solo admite ``True`` o ``False`` (ni 1 ni «sí»)."""
        definition = ParamDef("res.use_bench", "bool", "-", True,
                              requirements=("RF-008-03",), source="prueba")
        self.assertIs(definition.check(False), False)
        self.assertEqual(definition.range_text(), "")
        for value in (1, 0, "sí", numpy.bool_(True)):
            with self.subTest(value=value):
                with self.assertRaises(params.ParamError) as caught:
                    definition.check(value)
                self.assertEqual(caught.exception.code, "core.param_not_bool")

    def test_text_and_choices(self) -> None:
        """Un texto es un ``str``; con opciones, una de ellas; vacío, «sin valor»."""
        method = ParamDef("bm.estimation.method", "text", "-", "OK",
                          requirements=("RF-008-03",), source="prueba",
                          choices=("OK", "IDW", "NN"))
        self.assertEqual(method.check("IDW"), "IDW")
        with self.assertRaises(params.ParamError) as caught:
            method.check("kriging")
        self.assertEqual(caught.exception.code, "core.param_not_choice")
        self.assertIn("«OK», «IDW», «NN»", str(caught.exception))
        with self.assertRaises(params.ParamError) as caught:
            method.check(3)
        self.assertEqual(caught.exception.code, "core.param_not_text")
        with self.assertRaisesRegex(ValueError, "por defecto"):
            ParamDef("bm.estimation.method", "text", "-", "SK", requirements=("RF-008-03",),
                     source="prueba", choices=("OK", "IDW"))
        note = ParamDef("res.note", "text", "-", None, requirements=("RF-008-03",),
                        source="prueba", allow_empty=True)
        self.assertEqual(note.check(" a "), " a ")
        self.assertIsNone(note.check("   "))

    def test_missing_value(self) -> None:
        """RF-008-03 (spec §8): vacío sin que la definición admita «sin valor» se rechaza
        con el texto de la spec; si lo admite, es ``None``."""
        with self.assertRaises(params.ParamError) as caught:
            swell_factor().check(None)
        self.assertEqual(caught.exception.code, "core.param_missing")
        self.assertEqual(
            str(caught.exception),
            "res.swell_factor: falta el valor; este parámetro no admite «sin valor».",
        )
        self.assertIsNone(swell_factor(allow_empty=True).check(None))
        for key in BY_KEY:
            with self.subTest(key=key):
                with self.assertRaises(params.ParamError) as caught:
                    BY_KEY[key].check(None)
                self.assertEqual(caught.exception.code, "core.param_missing")

    def test_open_ranges(self) -> None:
        """Un extremo sin declarar es abierto: «(-∞; 2]», «[0; +∞) m»."""
        below = swell_factor(minimum=None)
        self.assertEqual(below.range_text(), "(-∞; 2]")
        self.assertEqual(below.check(-1e300), -1e300)
        above = fraction(key="res.depth_m", unit="m", default=3.0, maximum=None)
        self.assertEqual(above.range_text(), "[0; +∞) m")
        self.assertEqual(above.range_text("en"), "[0, +∞) m")
        self.assertEqual(above.check(1e300), 1e300)
        with self.assertRaises(params.ParamError):
            above.check(-0.5)

    def test_unit_symbol_in_spanish(self) -> None:
        """El rango se escribe con el símbolo en español de la unidad («m³», «t/m³»)."""
        volume = fraction(key="res.volume", unit="m3", default=10.0, maximum=1000.0)
        self.assertEqual(volume.range_text(), f"[0; 1{THIN}000] m³")
        self.assertEqual(volume.range_text("en"), "[0, 1,000] m3")
        with self.assertRaises(ValueError):
            volume.range_text("fr")


class ParseValueTest(unittest.TestCase):
    """RF-008-03 (spec §8): un valor tecleado se comprueba con su unidad; si es convertible
    a la declarada se convierte, y si no, se rechaza con la clave, el valor, la unidad y el
    rango."""

    def test_percent_in_a_fraction(self) -> None:
        """Spec §8: «35 %» en un parámetro declarado en fracción da 0,35 (lo que se guarda
        y se muestra)."""
        self.assertEqual(params.parse_value(fraction(), "35 %"), 0.35)
        self.assertEqual(params.parse_value(fraction(), "35%"), 0.35)
        self.assertEqual(params.parse_value(fraction(), "35", unit="%"), 0.35)
        self.assertEqual(params.parse_value(fraction(), "0,35"), 0.35)
        self.assertEqual(params.parse_value(fraction(), "0.35"), 0.35)
        self.assertEqual(params.parse_value(fraction(), "0.35", decimal="."), 0.35)
        self.assertEqual(params.parse_value(fraction(), " 1 "), 1.0)

    def test_convertible_units(self) -> None:
        """t y kt, m y km, MB y GB: se guarda en la unidad declarada."""
        tonnes = ParamDef("res.min_lot_t", "float", "t", 1000.0, 0.0, None,
                          ("RF-008-03",), "prueba")
        self.assertEqual(params.parse_value(tonnes, "1,5 kt"), 1500.0)
        self.assertEqual(params.parse_value(tonnes, "1 500"), 1500.0)
        cells = ParamDef("gis.import.max_cells", "int", "-", 10, 1, 100,
                         ("RF-008-03",), "prueba")
        self.assertEqual(params.parse_value(cells, "200 %"), 2)
        self.assertIs(type(params.parse_value(cells, "12")), int)
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(cells, "40 %")  # 0,4 no es un entero
        self.assertEqual(caught.exception.code, "core.param_not_integer")
        self.assertEqual(params.parse_value(core_defs.DEFINITIONS[0], "1 GB"), 1000.0)

    def test_out_of_range(self) -> None:
        """Spec §8: fuera del rango declarado, con la clave, el valor y el rango; con
        unidad, el valor ya convertido."""
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(swell_factor(), "3,5")
        error = caught.exception
        self.assertEqual(error.code, "core.param_out_of_range")
        self.assertEqual(
            str(error), "Parámetro «res.swell_factor»: 3,5 está fuera de su rango [1; 2]."
        )
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(fraction(), "135 %")
        self.assertIn("1,35 está fuera de su rango [0; 1]", str(caught.exception))
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(BY_KEY["gis.tin.blender_cdt_max_s"], "1 min")
        self.assertIn("60 está fuera de su rango [0; 2] s", str(caught.exception))

    def test_nan_infinite_and_not_numbers(self) -> None:
        """Spec §8: NaN e infinito tecleados se rechazan, como lo que no es un número."""
        for text in ("NaN", "nan", "inf", "-inf", "Infinity", "abc", "1,2,3", "-"):
            with self.subTest(text=text):
                with self.assertRaises(params.ParamError) as caught:
                    params.parse_value(swell_factor(), text)
                self.assertEqual(caught.exception.code, "core.param_not_number")
                self.assertIn("res.swell_factor", str(caught.exception))
                self.assertIn(text, str(caught.exception))
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(swell_factor(), "1" + "0" * 400)
        self.assertEqual(caught.exception.code, "core.param_not_finite")
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(BY_KEY["gis.reproject.supersample"], "NaN")
        self.assertEqual(caught.exception.code, "core.param_not_integer")

    def test_empty(self) -> None:
        """Spec §8: vacío sin «sin valor», el texto de la spec; con él, ``None``."""
        for text in ("", "   "):
            with self.subTest(text=text):
                with self.assertRaises(params.ParamError) as caught:
                    params.parse_value(swell_factor(), text)
                self.assertEqual(caught.exception.code, "core.param_missing")
                self.assertIn(
                    "res.swell_factor: falta el valor; este parámetro no admite «sin valor»",
                    str(caught.exception),
                )
                self.assertIsNone(params.parse_value(swell_factor(allow_empty=True), text))

    def test_unit_not_convertible(self) -> None:
        """Spec §8: una unidad no convertible a la declarada (t en una fracción) o fuera
        del catálogo se rechaza nombrando la clave, el valor, la unidad y el rango."""
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(fraction(), "35 t")
        error = caught.exception
        self.assertEqual(error.code, "core.param_unit_not_convertible")
        for part in ("res.recovery", "«35 t»", "«t»", "«—»", "[0; 1]"):
            self.assertIn(part, str(error))
        self.assertEqual(error.values["from_unit"], "t")
        self.assertEqual(error.values["unit"], "-")
        self.assertEqual(error.values["range"], "[0; 1]")
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(fraction(), "35", unit="m")
        self.assertEqual(caught.exception.code, "core.param_unit_not_convertible")
        for text, unit in (("35 xx", None), ("35", "xx")):
            with self.subTest(text=text, unit=unit):
                with self.assertRaises(params.ParamError) as caught:
                    params.parse_value(fraction(), text, unit=unit)
                self.assertEqual(caught.exception.code, "core.param_unit_unknown")
                self.assertIn("«xx»", str(caught.exception))

    def test_other_value_types(self) -> None:
        """Sí/no, texto y lista tecleados; cada elemento de una lista, con su unidad."""
        use_bench = ParamDef("res.use_bench", "bool", "-", True, requirements=("RF-008-03",),
                             source="prueba")
        for text, expected in (("sí", True), ("Si", True), ("NO", False), ("1", True),
                               ("false", False)):
            with self.subTest(text=text):
                self.assertIs(params.parse_value(use_bench, text), expected)
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(use_bench, "quizá")
        self.assertEqual(caught.exception.code, "core.param_not_bool")
        method = ParamDef("bm.estimation.method", "text", "-", "OK",
                          requirements=("RF-008-03",), source="prueba", choices=("OK", "IDW"))
        self.assertEqual(params.parse_value(method, " IDW "), "IDW")
        band = BY_KEY["gis.vertical.ellipsoidal_band_m"]
        for text, unit in (("40; 60", None), ("[40; 60]", None), ("(40;60)", None),
                           ("40 m; 0,06 km", None), ("0,04; 0,06", "km"),
                           ("40, 60", "m")):
            with self.subTest(text=text, unit=unit):
                decimal = "." if text == "40, 60" else ","
                self.assertEqual(params.parse_value(band, text, unit=unit, decimal=decimal),
                                 (40.0, 60.0))
        for text in ("60; 40", "40", "40; 60; 80", "40;", "[40; 60", "40; abc"):
            with self.subTest(text=text):
                with self.assertRaises(params.ParamError) as caught:
                    params.parse_value(band, text)
                self.assertEqual(caught.exception.code, "core.param_not_list")
        with self.assertRaises(params.ParamError) as caught:
            params.parse_value(band, "40; 300")
        self.assertEqual(caught.exception.code, "core.param_out_of_range")

    def test_text_must_be_str(self) -> None:
        """Lo tecleado es un texto; otra cosa es un error del programa."""
        with self.assertRaises(TypeError):
            params.parse_value(fraction(), 0.35)  # type: ignore[arg-type]


class RegistryTest(unittest.TestCase):
    """RF-008-01 (plan 008 §5.3.4, «Declarar»): cada módulo registra sus definiciones desde
    ``bl/`` y las quita al desregistrarse; dos definiciones con la misma clave se
    rechazan."""

    def setUp(self) -> None:
        self.assertNotIn("res.swell_factor", params.DEFINITIONS)
        self.addCleanup(params.unregister_definitions, "res")
        self.addCleanup(params.unregister_definitions, "gis")

    def test_register_and_unregister(self) -> None:
        params.register_definitions(DEFINITIONS)
        params.register_definitions((swell_factor(), fraction()))
        self.assertIs(params.DEFINITIONS["gis.tin.blender_cdt_max_s"],
                      BY_KEY["gis.tin.blender_cdt_max_s"])
        self.assertEqual(params.unregister_definitions("res"), 2)
        self.assertEqual(params.unregister_definitions("res"), 0)  # idempotente
        self.assertNotIn("res.swell_factor", params.DEFINITIONS)
        self.assertEqual(len([k for k in params.DEFINITIONS if k.startswith("gis.")]), 17)
        with self.assertRaises(TypeError):
            params.DEFINITIONS["res.x"] = swell_factor()  # type: ignore[index]

    def test_same_key_twice_is_rejected(self) -> None:
        """Una clave repetida en el lote o ya registrada se rechaza y no se registra nada
        del lote."""
        with self.assertRaisesRegex(ValueError, "res.swell_factor"):
            params.register_definitions((swell_factor(), fraction(), swell_factor()))
        self.assertNotIn("res.recovery", params.DEFINITIONS)
        params.register_definitions((swell_factor(),))
        with self.assertRaisesRegex(ValueError, "res.swell_factor"):
            params.register_definitions((fraction(), swell_factor(default=1.5)))
        self.assertNotIn("res.recovery", params.DEFINITIONS)
        self.assertEqual(params.DEFINITIONS["res.swell_factor"].default, 1.25)

    def test_only_definitions(self) -> None:
        with self.assertRaises(TypeError):
            params.register_definitions(({"key": "res.x"},))  # type: ignore[arg-type]


class CoreDefinitionsTest(unittest.TestCase):
    """RF-008-53 (D-18): la definición de ``core``: el límite para guardar el original de
    una entrada."""

    def test_original_copy_limit(self) -> None:
        (limit,) = core_defs.DEFINITIONS
        self.assertEqual(limit.key, "core.original_copy_limit")
        self.assertEqual(limit.module, "core")
        self.assertEqual(limit.unit, "MB")
        self.assertEqual(limit.default, 200.0)
        self.assertIs(limit.kind, params.ParamKind.ADOPTADO)
        self.assertIs(limit.source_kind, params.SourceKind.ALGORITHM)
        self.assertIn("RF-008-53", limit.requirements)
        self.assertIn("D-18", limit.source)
        self.assertEqual(units.convert(limit.default, limit.unit, "B"), 2e8)
        self.addCleanup(params.unregister_definitions, "core")
        params.register_definitions(core_defs.DEFINITIONS)
        self.assertIs(params.DEFINITIONS["core.original_copy_limit"], limit)


class MessagesTest(unittest.TestCase):
    """Principio 10: cada código ``core.param_*`` tiene ``msgid`` en inglés y texto en
    español con los mismos marcadores, que nombran la clave y el valor."""

    def test_catalog(self) -> None:
        self.assertGreaterEqual(len(params.MESSAGES), 10)
        for code, message in params.MESSAGES.items():
            with self.subTest(code=code):
                self.assertTrue(code.startswith("core.param_"))
                self.assertEqual(message.code, code)
                self.assertEqual(_placeholders(message.msgid), _placeholders(message.es))
                self.assertIn("key", _placeholders(message.es))
                self.assertEqual(params.CATALOG_ES[message.msgid], message.es)
        with self.assertRaises(TypeError):
            params.CATALOG_ES["x"] = "y"  # type: ignore[index]

    def test_render(self) -> None:
        self.assertEqual(
            params.render("core.param_not_integer", key="k", value=4.5),
            "Parámetro «k»: «4,5» no es un número entero.",
        )
        self.assertEqual(
            params.render("core.param_not_integer", language="en", key="k", value=4.5),
            "Parameter «k»: «4.5» is not a whole number.",
        )
        self.assertEqual(params.render("core.param_not_list", key="k", value=None),
                         "Parámetro «k»: «?» no es una lista de ? números en orden creciente.")
        with self.assertRaises(ValueError):
            params.render("core.no_such", key="k")


class ThousandsTest(unittest.TestCase):
    """Spec 008, T71 (en la comprobación en pantalla, T58, los parámetros salían sin separador
    de miles, «500000 t/año»): un valor se lee como una cifra (spec 003, II §2.4)."""

    def test_values_with_the_thousands_separator_of_the_figures(self) -> None:
        """RF-008-06, RF-008-29, RF-008-59, RF-008-03 (T71): un valor se lee con el separador
        de miles de las cifras, «500 000» (espacio fino) en español y «500,000» en inglés, con
        todos sus decimales, también un entero; sin separar, como se teclea. Un parámetro de
        500 000 t/año se muestra igual que una cifra de 500 000 t/año en los dos idiomas (el
        ámbito de la cifra, «2026», no se separa), y lo separan el aviso de divergencia, el
        rango y su rechazo. Ningún valor cambia: el texto sin separar y el separado se leen
        como el mismo número."""
        shown = params.format_value
        for value, spanish, english in (
            (500_000.0, f"500{THIN}000", "500,000"),
            (1_234_567.891, f"1{THIN}234{THIN}567,891", "1,234,567.891"),
            (-12_345.5, f"-12{THIN}345,5", "-12,345.5"),
            (1_000.0, f"1{THIN}000", "1,000"),
            (999.5, "999,5", "999.5"),
            (0.35, "0,35", "0.35"),
            (1.2e-05, "1,2e-05", "1.2e-05"),
            (100_000_001, f"100{THIN}000{THIN}001", "100,000,001"),
            (16, "16", "16"),
        ):
            with self.subTest(value=value):
                self.assertEqual(shown(value), spanish)
                self.assertEqual(shown(value, "es"), spanish)
                self.assertEqual(shown(value, "en"), english)
                self.assertEqual(shown(value, "es", grouped=False), spanish.replace(THIN, ""))
                self.assertEqual(shown(value, "en", grouped=False), english.replace(",", ""))
        self.assertEqual((shown(True), shown(False, "en"), shown("B-1")), ("sí", "no", "B-1"))

        production = ParamDef("res.output", "float", "t/yr", 500_000.0, 0.0, 2_000_000.0,
                              ("RF-008-03",), "Prueba: producción del plan", kind="HIPÓTESIS",
                              source_kind="document")
        self.assertEqual(production.range_text(), f"[0; 2{THIN}000{THIN}000] t/año")
        self.assertEqual(production.range_text("en"), "[0, 2,000,000] t/yr")
        with self.assertRaises(params.ParamError) as caught:
            production.check(3_000_000.0)
        self.assertEqual(str(caught.exception),
                         f"Parámetro «res.output»: 3{THIN}000{THIN}000 está fuera de su rango "
                         f"[0; 2{THIN}000{THIN}000] t/año.")
        for language, decimal in (("es", ","), ("en", ".")):
            typed = shown(512_345.25, language, grouped=False)
            self.assertEqual(params.parse_value(production, typed, decimal=decimal), 512_345.25)
        self.assertEqual(params.parse_value(production, f"512{THIN}345,25"), 512_345.25)

        figure = figures.FigureRecord(
            uid="f", key="res.output_calc", label="Producción calculada", value=500_000.0,
            unit="t/yr", kind=params.ParamKind.CALCULADO, operation_uid="o",
            parameter_uid=None, parameter_rev=None, scope={"year": 2026}, scope_key="",
            created_at="2026-09-24T09:31:00Z")
        self.assertEqual(figure.text(), f"Producción calculada · 2026 = 500{THIN}000 t/año")
        self.assertEqual(store.shown_value(500_000.0, "t/yr"), f"500{THIN}000 t/año")
        self.assertEqual(store.shown_value(500_000.0, "t/yr", "en"), "500,000 t/año")
        for language in ("es", "en"):
            with self.subTest(language=language):
                self.assertEqual(figure.text(language=language).rpartition(" = ")[2],
                                 store.shown_value(500_000.0, "t/yr", language))

        warning = figures.Divergence(
            figure_uid="f", figure_key="res.output_calc", label="Producción calculada",
            op_type="res.plan", operation_uid="o", value=512_345.5, unit="t/yr",
            parameter_uid="p", parameter_key="res.output", parameter_value=500_000.0,
            parameter_unit="t/yr", parameter_kind=params.ParamKind.HIPOTESIS,
            unconfirmed=True, decided_by="Geoblender (valor por defecto)",
            decided_at="2026-09-24T09:31:00Z")
        self.assertIn(f"= 512{THIN}345,5 t/año; el valor hipotético sin confirmar es "
                      f"500{THIN}000 t/año (", warning.render("es"))
        self.assertIn("= 512,345.5 t/año; the unconfirmed hypothetical value is 500,000 t/año (",
                      warning.render("en"))


if __name__ == "__main__":
    unittest.main()
