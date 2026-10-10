# SPDX-License-Identifier: GPL-3.0-or-later
"""Puertos, parámetros, mensajes e informes de ``gis`` (spec 006, T02; plan 006 §5.1,
§5.2.5 y §5.3.1).

Base de RF-006-01 a RF-006-31: lo que usan todas las tareas siguientes de la 006 y la 005
(el puerto ``CrsService``, con la convergencia de cuadrícula).

- **Parámetros** (``gis.params``; plan §5.2.5 y, desde T39, §5.6.1): las 17 claves de la
  tabla, sin repetir, cada una con su unidad, su valor por defecto, su rango y tipo ADOPTADO
  de origen ``algorithm`` (``source_kind``), y con los RF que la usan: RF-006-05 (submuestreo
  de la reproyección), RF-006-06 (banda de alturas elipsoidales, D-8), RF-006-09 (límite de
  celdas), RF-006-11 (fracción mínima, D-4), RF-006-13 y RF-006-28 (límite de la CDT de
  Blender, 2 s con la excepción de D-12 y nunca más), RF-006-14 (tolerancias de
  duplicados, D-5), RF-006-16 (corrección de triángulos planos), RF-006-18 (curvas),
  RF-006-22 (niveles de detalle) y RF-006-23 (rango plausible de cotas). ``check`` acepta
  los extremos del rango y rechaza lo que sale de él con ``ParamError`` (``core.param_*``).
  Desde T39 (RF-008-01, RF-008-03, RF-008-06), ``ParamDef`` es el de ``core.params``: las 17
  definiciones dan el mismo valor normalizado, el mismo texto y el mismo ``range_text()`` que
  la definición provisional de ``gis`` (:data:`CHECKS` y :data:`RANGES`, copia literal de lo
  que daba antes de T39), cada una lleva su etiqueta (``label_msgid``) con su español en el
  catálogo de idioma y no queda ningún código de parámetro de ``gis`` (los cuatro que daba
  ``gis/messages.py``) en el código ni en las pruebas de la 006.
- **Puertos** (``gis.ports``; plan §5.3.1): los nombres y las firmas del contrato, y que
  ``ports.py`` solo importa la biblioteca estándar, numpy y ``core`` (ARQ-10; RF-006-01 a
  RF-006-31 lo usan a través de él): el detector ve un import prohibido sembrado a
  propósito (control positivo).
- **Mensajes** (``gis.messages``; principio 10): códigos ``gis.*`` únicos, ``msgid`` en
  inglés y español con los mismos marcadores; los ejemplos del plan §5.5 salen tal cual.
- **Informes** (``gis.reports``): inmutables, con sus derivados (sin dato, porcentajes,
  diferencia de cota) y serializables a JSON (los ``report.json`` de los trabajos).
"""

import ast
import dataclasses
import inspect
import json
import math
import re
import string
import sys
import unittest
from typing import is_protocol

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR, ROOT

gis = import_geoblender("gis")
params = import_geoblender("gis.params")
ports = import_geoblender("gis.ports")
messages = import_geoblender("gis.messages")
reports = import_geoblender("gis.reports")
errors = import_geoblender("core.errors")
core_params = import_geoblender("core.params")
i18n = import_geoblender("core.i18n")

PORTS_FILE = EXTENSION_DIR / "gis" / "ports.py"
ParamError = core_params.ParamError

# El código y las pruebas de la 006 en los que no puede quedar ningún código de parámetro de
# gis (T39): los de la 008 en core/params citan la definición provisional como historia.
FOLDERS_OF_006 = (EXTENSION_DIR / "gis", EXTENSION_DIR / "bl", ROOT / "tests" / "unit" / "gis",
                  ROOT / "tests" / "blender" / "gis")
OLD_PARAM_CODE = re.compile(r"gis\.param_")

# Plan 006 §5.2.5: clave → (unidad, valor por defecto, mínimo, máximo, mínimo excluido).
# La unidad «-» es la de gb_parameter para lo adimensional (el «—» de la tabla del plan).
# Los rangos no los fija el plan: son los de gis/params.py (decisión de T02, revisable);
# el de la CDT de Blender sí: nunca más de 2 s (excepción del principio 9, D-12).
EXPECTED: dict[str, tuple[str, object, float, float, bool]] = {
    "gis.resample.min_valid_fraction": ("-", 1.0, 0.0, 1.0, True),
    "gis.reproject.supersample": ("-", 4, 1, 16, False),
    "gis.points.dup_xy_tol_m": ("m", 0.001, 0.0, 1.0, True),
    "gis.points.dup_z_tol_m": ("m", 0.01, 0.0, 1.0, False),
    "gis.tin.contour_densify_m": ("m", 5.0, 0.0, 100.0, True),
    "gis.tin.flat_max_passes": ("-", 3, 0, 10, False),
    "gis.tin.max_flat_pct": ("%", 1.0, 0.0, 100.0, False),
    "gis.tin.blender_cdt_max_s": ("s", 2.0, 0.0, 2.0, False),
    "gis.contours.interval_m": ("m", 1.0, 0.0, 1000.0, True),
    "gis.contours.index_every_m": ("m", 5.0, 0.0, 10000.0, True),
    "gis.contours.index_offset_m": ("m", 0.0, -100.0, 100.0, False),
    "gis.contours.simplify_m": ("m", 0.0, 0.0, 100.0, False),
    "gis.contours.min_length_m": ("m", 0.0, 0.0, 10000.0, False),
    "gis.vertical.ellipsoidal_band_m": ("m", (40.0, 60.0), 0.0, 200.0, False),
    "gis.validate.z_range_m": ("m", (-500.0, 5000.0), -11000.0, 9000.0, False),
    "gis.import.max_cells": ("-", 100_000_000, 1, 100_000_000, False),
    "gis.view.lod_steps_m": ("m", (2.0, 5.0), 0.5, 100.0, False),
}

# Los RF de cada clave (columna RF del plan §5.2.5).
EXPECTED_RF: dict[str, tuple[str, ...]] = {
    "gis.resample.min_valid_fraction": ("RF-006-11",),
    "gis.reproject.supersample": ("RF-006-05",),
    "gis.points.dup_xy_tol_m": ("RF-006-14",),
    "gis.points.dup_z_tol_m": ("RF-006-14",),
    "gis.tin.contour_densify_m": ("RF-006-16",),
    "gis.tin.flat_max_passes": ("RF-006-16",),
    "gis.tin.max_flat_pct": ("RF-006-16",),
    "gis.tin.blender_cdt_max_s": ("RF-006-13", "RF-006-28"),
    "gis.contours.interval_m": ("RF-006-18",),
    "gis.contours.index_every_m": ("RF-006-18",),
    "gis.contours.index_offset_m": ("RF-006-18",),
    "gis.contours.simplify_m": ("RF-006-18",),
    "gis.contours.min_length_m": ("RF-006-18",),
    "gis.vertical.ellipsoidal_band_m": ("RF-006-06",),
    "gis.validate.z_range_m": ("RF-006-23",),
    "gis.import.max_cells": ("RF-006-09",),
    "gis.view.lod_steps_m": ("RF-006-22",),
}

# Lo que daba la definición provisional de gis/params.py antes de T39 (salida de su check(),
# copiada aquí, no recalculada): (clave, valor, resultado), con el valor normalizado (con su
# tipo) o (código, texto en español), el código ya escrito como core.param_*.
CHECKS: tuple[tuple[str, object, object], ...] = (
    ("gis.resample.min_valid_fraction", 1.0, 1.0),
    ("gis.resample.min_valid_fraction", 1, 1.0),
    ("gis.resample.min_valid_fraction", 0.0, ("core.param_out_of_range", "Parámetro «gis.resample.min_valid_fraction»: 0 está fuera de su rango (0; 1].")),
    ("gis.resample.min_valid_fraction", 1.5, ("core.param_out_of_range", "Parámetro «gis.resample.min_valid_fraction»: 1,5 está fuera de su rango (0; 1].")),
    ("gis.resample.min_valid_fraction", True, ("core.param_not_number", "Parámetro «gis.resample.min_valid_fraction»: «sí» no es un número.")),
    ("gis.reproject.supersample", 4, 4),
    ("gis.reproject.supersample", 4.0, 4),
    ("gis.reproject.supersample", 1, 1),
    ("gis.reproject.supersample", 16, 16),
    ("gis.reproject.supersample", 0, ("core.param_out_of_range", "Parámetro «gis.reproject.supersample»: 0 está fuera de su rango [1; 16].")),
    ("gis.reproject.supersample", 17, ("core.param_out_of_range", "Parámetro «gis.reproject.supersample»: 17 está fuera de su rango [1; 16].")),
    ("gis.reproject.supersample", 4.5, ("core.param_not_integer", "Parámetro «gis.reproject.supersample»: «4,5» no es un número entero.")),
    ("gis.points.dup_xy_tol_m", 0.001, 0.001),
    ("gis.points.dup_xy_tol_m", 1.0, 1.0),
    ("gis.points.dup_xy_tol_m", 0.0, ("core.param_out_of_range", "Parámetro «gis.points.dup_xy_tol_m»: 0 está fuera de su rango (0; 1] m.")),
    ("gis.points.dup_xy_tol_m", 1.5, ("core.param_out_of_range", "Parámetro «gis.points.dup_xy_tol_m»: 1,5 está fuera de su rango (0; 1] m.")),
    ("gis.points.dup_xy_tol_m", True, ("core.param_not_number", "Parámetro «gis.points.dup_xy_tol_m»: «sí» no es un número.")),
    ("gis.points.dup_z_tol_m", 0.01, 0.01),
    ("gis.points.dup_z_tol_m", 0.0, 0.0),
    ("gis.points.dup_z_tol_m", 1.0, 1.0),
    ("gis.points.dup_z_tol_m", -0.5, ("core.param_out_of_range", "Parámetro «gis.points.dup_z_tol_m»: -0,5 está fuera de su rango [0; 1] m.")),
    ("gis.points.dup_z_tol_m", 1.5, ("core.param_out_of_range", "Parámetro «gis.points.dup_z_tol_m»: 1,5 está fuera de su rango [0; 1] m.")),
    ("gis.points.dup_z_tol_m", True, ("core.param_not_number", "Parámetro «gis.points.dup_z_tol_m»: «sí» no es un número.")),
    ("gis.tin.contour_densify_m", 5.0, 5.0),
    ("gis.tin.contour_densify_m", 5, 5.0),
    ("gis.tin.contour_densify_m", 100.0, 100.0),
    ("gis.tin.contour_densify_m", 0.0, ("core.param_out_of_range", "Parámetro «gis.tin.contour_densify_m»: 0 está fuera de su rango (0; 100] m.")),
    ("gis.tin.contour_densify_m", 100.5, ("core.param_out_of_range", "Parámetro «gis.tin.contour_densify_m»: 100,5 está fuera de su rango (0; 100] m.")),
    ("gis.tin.contour_densify_m", True, ("core.param_not_number", "Parámetro «gis.tin.contour_densify_m»: «sí» no es un número.")),
    ("gis.tin.flat_max_passes", 3, 3),
    ("gis.tin.flat_max_passes", 3.0, 3),
    ("gis.tin.flat_max_passes", 0, 0),
    ("gis.tin.flat_max_passes", 10, 10),
    ("gis.tin.flat_max_passes", -1, ("core.param_out_of_range", "Parámetro «gis.tin.flat_max_passes»: -1 está fuera de su rango [0; 10].")),
    ("gis.tin.flat_max_passes", 11, ("core.param_out_of_range", "Parámetro «gis.tin.flat_max_passes»: 11 está fuera de su rango [0; 10].")),
    ("gis.tin.flat_max_passes", 3.5, ("core.param_not_integer", "Parámetro «gis.tin.flat_max_passes»: «3,5» no es un número entero.")),
    ("gis.tin.max_flat_pct", 1.0, 1.0),
    ("gis.tin.max_flat_pct", 1, 1.0),
    ("gis.tin.max_flat_pct", 0.0, 0.0),
    ("gis.tin.max_flat_pct", 100.0, 100.0),
    ("gis.tin.max_flat_pct", -0.5, ("core.param_out_of_range", "Parámetro «gis.tin.max_flat_pct»: -0,5 está fuera de su rango [0; 100] %.")),
    ("gis.tin.max_flat_pct", 100.5, ("core.param_out_of_range", "Parámetro «gis.tin.max_flat_pct»: 100,5 está fuera de su rango [0; 100] %.")),
    ("gis.tin.max_flat_pct", True, ("core.param_not_number", "Parámetro «gis.tin.max_flat_pct»: «sí» no es un número.")),
    ("gis.tin.blender_cdt_max_s", 2.0, 2.0),
    ("gis.tin.blender_cdt_max_s", 2, 2.0),
    ("gis.tin.blender_cdt_max_s", 0.0, 0.0),
    ("gis.tin.blender_cdt_max_s", -0.5, ("core.param_out_of_range", "Parámetro «gis.tin.blender_cdt_max_s»: -0,5 está fuera de su rango [0; 2] s.")),
    ("gis.tin.blender_cdt_max_s", 2.5, ("core.param_out_of_range", "Parámetro «gis.tin.blender_cdt_max_s»: 2,5 está fuera de su rango [0; 2] s.")),
    ("gis.tin.blender_cdt_max_s", True, ("core.param_not_number", "Parámetro «gis.tin.blender_cdt_max_s»: «sí» no es un número.")),
    ("gis.contours.interval_m", 1.0, 1.0),
    ("gis.contours.interval_m", 1, 1.0),
    ("gis.contours.interval_m", 1000.0, 1000.0),
    ("gis.contours.interval_m", 0.0, ("core.param_out_of_range", "Parámetro «gis.contours.interval_m»: 0 está fuera de su rango (0; 1000] m.")),
    ("gis.contours.interval_m", 1000.5, ("core.param_out_of_range", "Parámetro «gis.contours.interval_m»: 1000,5 está fuera de su rango (0; 1000] m.")),
    ("gis.contours.interval_m", True, ("core.param_not_number", "Parámetro «gis.contours.interval_m»: «sí» no es un número.")),
    ("gis.contours.index_every_m", 5.0, 5.0),
    ("gis.contours.index_every_m", 5, 5.0),
    ("gis.contours.index_every_m", 10000.0, 10000.0),
    ("gis.contours.index_every_m", 0.0, ("core.param_out_of_range", "Parámetro «gis.contours.index_every_m»: 0 está fuera de su rango (0; 10000] m.")),
    ("gis.contours.index_every_m", 10000.5, ("core.param_out_of_range", "Parámetro «gis.contours.index_every_m»: 10000,5 está fuera de su rango (0; 10000] m.")),
    ("gis.contours.index_every_m", True, ("core.param_not_number", "Parámetro «gis.contours.index_every_m»: «sí» no es un número.")),
    ("gis.contours.index_offset_m", 0.0, 0.0),
    ("gis.contours.index_offset_m", 0, 0.0),
    ("gis.contours.index_offset_m", -100.0, -100.0),
    ("gis.contours.index_offset_m", 100.0, 100.0),
    ("gis.contours.index_offset_m", -100.5, ("core.param_out_of_range", "Parámetro «gis.contours.index_offset_m»: -100,5 está fuera de su rango [-100; 100] m.")),
    ("gis.contours.index_offset_m", 100.5, ("core.param_out_of_range", "Parámetro «gis.contours.index_offset_m»: 100,5 está fuera de su rango [-100; 100] m.")),
    ("gis.contours.index_offset_m", True, ("core.param_not_number", "Parámetro «gis.contours.index_offset_m»: «sí» no es un número.")),
    ("gis.contours.simplify_m", 0.0, 0.0),
    ("gis.contours.simplify_m", 0, 0.0),
    ("gis.contours.simplify_m", 100.0, 100.0),
    ("gis.contours.simplify_m", -0.5, ("core.param_out_of_range", "Parámetro «gis.contours.simplify_m»: -0,5 está fuera de su rango [0; 100] m.")),
    ("gis.contours.simplify_m", 100.5, ("core.param_out_of_range", "Parámetro «gis.contours.simplify_m»: 100,5 está fuera de su rango [0; 100] m.")),
    ("gis.contours.simplify_m", True, ("core.param_not_number", "Parámetro «gis.contours.simplify_m»: «sí» no es un número.")),
    ("gis.contours.min_length_m", 0.0, 0.0),
    ("gis.contours.min_length_m", 0, 0.0),
    ("gis.contours.min_length_m", 10000.0, 10000.0),
    ("gis.contours.min_length_m", -0.5, ("core.param_out_of_range", "Parámetro «gis.contours.min_length_m»: -0,5 está fuera de su rango [0; 10000] m.")),
    ("gis.contours.min_length_m", 10000.5, ("core.param_out_of_range", "Parámetro «gis.contours.min_length_m»: 10000,5 está fuera de su rango [0; 10000] m.")),
    ("gis.contours.min_length_m", True, ("core.param_not_number", "Parámetro «gis.contours.min_length_m»: «sí» no es un número.")),
    ("gis.vertical.ellipsoidal_band_m", (40.0, 60.0), (40.0, 60.0)),
    ("gis.vertical.ellipsoidal_band_m", [40.0, 60.0], (40.0, 60.0)),
    ("gis.vertical.ellipsoidal_band_m", (0.0, 200.0), (0.0, 200.0)),
    ("gis.vertical.ellipsoidal_band_m", (-1.0, 200.0), ("core.param_out_of_range", "Parámetro «gis.vertical.ellipsoidal_band_m»: [-1; 200] está fuera de su rango [0; 200] m.")),
    ("gis.vertical.ellipsoidal_band_m", (0.0, 201.0), ("core.param_out_of_range", "Parámetro «gis.vertical.ellipsoidal_band_m»: [0; 201] está fuera de su rango [0; 200] m.")),
    ("gis.vertical.ellipsoidal_band_m", (60.0, 40.0), ("core.param_not_list", "Parámetro «gis.vertical.ellipsoidal_band_m»: «(60.0, 40.0)» no es una lista de 2 números en orden creciente.")),
    ("gis.validate.z_range_m", (-500.0, 5000.0), (-500.0, 5000.0)),
    ("gis.validate.z_range_m", [-500.0, 5000.0], (-500.0, 5000.0)),
    ("gis.validate.z_range_m", (-11000.0, 9000.0), (-11000.0, 9000.0)),
    ("gis.validate.z_range_m", (-11001.0, 9000.0), ("core.param_out_of_range", "Parámetro «gis.validate.z_range_m»: [-11001; 9000] está fuera de su rango [-11000; 9000] m.")),
    ("gis.validate.z_range_m", (-11000.0, 9001.0), ("core.param_out_of_range", "Parámetro «gis.validate.z_range_m»: [-11000; 9001] está fuera de su rango [-11000; 9000] m.")),
    ("gis.validate.z_range_m", (5000.0, -500.0), ("core.param_not_list", "Parámetro «gis.validate.z_range_m»: «(5000.0, -500.0)» no es una lista de 2 números en orden creciente.")),
    ("gis.import.max_cells", 100000000, 100000000),
    ("gis.import.max_cells", 100000000.0, 100000000),
    ("gis.import.max_cells", 1, 1),
    ("gis.import.max_cells", 0, ("core.param_out_of_range", "Parámetro «gis.import.max_cells»: 0 está fuera de su rango [1; 100000000].")),
    ("gis.import.max_cells", 100000001, ("core.param_out_of_range", "Parámetro «gis.import.max_cells»: 100000001 está fuera de su rango [1; 100000000].")),
    ("gis.import.max_cells", 100000000.5, ("core.param_not_integer", "Parámetro «gis.import.max_cells»: «100000000,5» no es un número entero.")),
    ("gis.view.lod_steps_m", (2.0, 5.0), (2.0, 5.0)),
    ("gis.view.lod_steps_m", [2.0, 5.0], (2.0, 5.0)),
    ("gis.view.lod_steps_m", (0.5, 100.0), (0.5, 100.0)),
    ("gis.view.lod_steps_m", (-0.5, 100.0), ("core.param_out_of_range", "Parámetro «gis.view.lod_steps_m»: [-0,5; 100] está fuera de su rango [0,5; 100] m.")),
    ("gis.view.lod_steps_m", (0.5, 101.0), ("core.param_out_of_range", "Parámetro «gis.view.lod_steps_m»: [0,5; 101] está fuera de su rango [0,5; 100] m.")),
    ("gis.view.lod_steps_m", (5.0, 2.0), ("core.param_not_list", "Parámetro «gis.view.lod_steps_m»: «(5.0, 2.0)» no es una lista de 2 números en orden creciente.")),
)

# clave → range_text() en español y en inglés, como lo daba la provisional antes de T39.
RANGES: dict[str, tuple[str, str]] = {
    "gis.resample.min_valid_fraction": ("(0; 1]", "(0, 1]"),
    "gis.reproject.supersample": ("[1; 16]", "[1, 16]"),
    "gis.points.dup_xy_tol_m": ("(0; 1] m", "(0, 1] m"),
    "gis.points.dup_z_tol_m": ("[0; 1] m", "[0, 1] m"),
    "gis.tin.contour_densify_m": ("(0; 100] m", "(0, 100] m"),
    "gis.tin.flat_max_passes": ("[0; 10]", "[0, 10]"),
    "gis.tin.max_flat_pct": ("[0; 100] %", "[0, 100] %"),
    "gis.tin.blender_cdt_max_s": ("[0; 2] s", "[0, 2] s"),
    "gis.contours.interval_m": ("(0; 1000] m", "(0, 1000] m"),
    "gis.contours.index_every_m": ("(0; 10000] m", "(0, 10000] m"),
    "gis.contours.index_offset_m": ("[-100; 100] m", "[-100, 100] m"),
    "gis.contours.simplify_m": ("[0; 100] m", "[0, 100] m"),
    "gis.contours.min_length_m": ("[0; 10000] m", "[0, 10000] m"),
    "gis.vertical.ellipsoidal_band_m": ("[0; 200] m", "[0, 200] m"),
    "gis.validate.z_range_m": ("[-11000; 9000] m", "[-11000, 9000] m"),
    "gis.import.max_cells": ("[1; 100000000]", "[1, 100000000]"),
    "gis.view.lod_steps_m": ("[0,5; 100] m", "[0.5, 100] m"),
}

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")

# Lo que puede importar un ports.py (ARQ-10; vision-general.md §2.3).
ALLOWED_ABSOLUTE = frozenset(sys.stdlib_module_names) | {"numpy", "__future__"}


def _forbidden_imports(source: str) -> list[str]:
    """Los imports de un ``geoblender/<paquete>/ports.py`` que ARQ-10 no admite: los
    absolutos que no son de la biblioteca estándar ni numpy, los relativos que no van a
    ``core`` (nivel 2: ``from ..core…``) y los dinámicos. También dentro de funciones y
    de ``if TYPE_CHECKING`` (ARQ-10 no los distingue)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name for alias in node.names
                if alias.name.partition(".")[0] not in ALLOWED_ABSOLUTE
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0:
                if module.partition(".")[0] not in ALLOWED_ABSOLUTE:
                    found.append(module)
            elif node.level != 2 or module.partition(".")[0] != "core":
                found.append("." * node.level + module)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("__import__", "import_module"):
                found.append(f"{name}(…)")
    return found


def _fields(text: str) -> set[str]:
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}


class ParamsTest(unittest.TestCase):
    """Plan 006 §5.2.5: las definiciones de ``gis/params.py`` (RF-006-05, RF-006-06,
    RF-006-09, RF-006-11, RF-006-13, RF-006-14, RF-006-16, RF-006-18, RF-006-22,
    RF-006-23, RF-006-28)."""

    def test_keys_are_those_of_the_plan_and_unique(self) -> None:
        """Las 17 claves del plan, cada una una sola vez (también en la tupla de la que
        sale el índice: un duplicado no se pierde en silencio)."""
        keys = [definition.key for definition in params.DEFINITIONS]
        self.assertEqual(len(keys), len(set(keys)), "claves repetidas")
        self.assertEqual(set(keys), set(EXPECTED))
        self.assertEqual(set(params.PARAMS), set(EXPECTED))
        for key in keys:
            self.assertRegex(key, r"^gis\.[a-z]+\.[a-z][a-z0-9_]*$")

    def test_duplicate_key_is_rejected(self) -> None:
        """Control positivo: construir el índice con una clave repetida es un error."""
        first = params.DEFINITIONS[0]
        with self.assertRaisesRegex(ValueError, re.escape(first.key)):
            params.index_definitions((first, first))

    def test_unit_default_range_and_kind(self) -> None:
        """Unidad, valor por defecto (con su tipo), rango y tipo ADOPTADO
        (``source_kind = 'algorithm'``) de cada parámetro."""
        for key, (unit, default, low, high, low_excluded) in EXPECTED.items():
            with self.subTest(key=key):
                definition = params.param(key)
                self.assertEqual(definition.unit, unit)
                self.assertEqual(definition.default, default)
                self.assertIs(type(definition.default), type(default))
                self.assertEqual(definition.minimum, low)
                self.assertEqual(definition.maximum, high)
                self.assertIs(definition.min_exclusive, low_excluded)
                self.assertEqual(definition.kind, "ADOPTADO")
                self.assertEqual(definition.source_kind, "algorithm")
                self.assertTrue(definition.source.strip(), "sin procedencia")
                self.assertEqual(definition.requirements, EXPECTED_RF[key])
                self.assertEqual(params.default(key), default)

    def test_value_types_match_gb_parameter(self) -> None:
        """El tipo de valor es uno de ``gb_parameter.value_type``: ``float``, ``int`` o
        ``json`` (los pares, en orden creciente)."""
        for definition in params.DEFINITIONS:
            with self.subTest(key=definition.key):
                expected = {float: "float", int: "int", tuple: "json"}[type(definition.default)]
                self.assertEqual(definition.value_type, expected)
                if expected == "json":
                    self.assertEqual(definition.length, len(definition.default))
                    self.assertLess(definition.default[0], definition.default[1])

    def test_bounds_accepted_and_outside_rejected(self) -> None:
        """``check`` acepta el valor por defecto y los extremos incluidos del rango, y
        rechaza lo que queda fuera con ``ParamError`` ``core.param_out_of_range``, la clave
        como campo y el valor."""
        for key, (_unit, default, low, high, low_excluded) in EXPECTED.items():
            definition = params.param(key)
            integer = definition.value_type == "int"
            step = 1 if integer else 1e-9
            with self.subTest(key=key):
                self.assertEqual(definition.check(default), default)
                if definition.value_type == "json":
                    self.assertEqual(definition.check([low, high]), (low, high))
                    with self.assertRaises(ParamError) as caught:
                        definition.check([low - 1.0, high])
                    self.assertEqual(caught.exception.code, "core.param_out_of_range")
                    self.assertEqual(caught.exception.field, key)
                    continue
                if not low_excluded:
                    self.assertEqual(definition.check(low), low)
                self.assertEqual(definition.check(high), high)
                for outside in (high + step, low if low_excluded else low - step):
                    with self.assertRaises(ParamError) as caught:
                        definition.check(outside)
                    self.assertEqual(caught.exception.code, "core.param_out_of_range")
                    self.assertEqual(caught.exception.field, key)
                    self.assertIn(key, str(caught.exception))

    def test_blender_cdt_never_above_two_seconds(self) -> None:
        """RF-006-13, RF-006-28: la excepción del principio 9 (plan §9, D-12) acaba en
        2 s; 2,5 s se rechaza y el mensaje da el rango en español."""
        definition = params.param("gis.tin.blender_cdt_max_s")
        with self.assertRaises(ParamError) as caught:
            definition.check(2.5)
        self.assertIn("2,5", str(caught.exception))
        self.assertIn("[0; 2] s", str(caught.exception))

    def test_wrong_types_rejected(self) -> None:
        """Un booleano, un texto o un NaN no son números; 4,5 no es un entero; una lista
        descendente o de otra longitud no es un par válido."""
        cases = (
            ("gis.points.dup_z_tol_m", True, "core.param_not_number"),
            ("gis.points.dup_z_tol_m", "0,01", "core.param_not_number"),
            ("gis.points.dup_z_tol_m", math.nan, "core.param_not_number"),
            ("gis.reproject.supersample", 4.5, "core.param_not_integer"),
            ("gis.reproject.supersample", True, "core.param_not_integer"),
            ("gis.vertical.ellipsoidal_band_m", (60.0, 40.0), "core.param_not_list"),
            ("gis.vertical.ellipsoidal_band_m", (40.0,), "core.param_not_list"),
            ("gis.vertical.ellipsoidal_band_m", "40;60", "core.param_not_list"),
        )
        for key, value, code in cases:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ParamError) as caught:
                    params.param(key).check(value)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.field, key)
        self.assertEqual(params.param("gis.reproject.supersample").check(8.0), 8)
        self.assertIs(type(params.param("gis.reproject.supersample").check(8.0)), int)
        self.assertIs(type(params.param("gis.points.dup_z_tol_m").check(0)), float)

    def test_unknown_key(self) -> None:
        """Una clave que no es de ``gis`` es un error del programa (``KeyError``)."""
        with self.assertRaisesRegex(KeyError, "gis.no_such"):
            params.param("gis.no_such")

    def test_invalid_definition_rejected(self) -> None:
        """Una definición cuyo valor por defecto sale de su rango no se construye."""
        with self.assertRaises(ValueError):
            params.ParamDef(
                key="gis.test.value_m", value_type="float", unit="m", default=5.0,
                minimum=0.0, maximum=1.0, requirements=("RF-006-01",), source="prueba",
            )


class CoreParamsTest(unittest.TestCase):
    """T39 (plan 006 §5.6.1; RF-006-11, RF-006-14, RF-006-16, RF-006-18, RF-006-23;
    RF-008-01, RF-008-03, RF-008-06): ``gis/params.py`` sobre ``core.params``."""

    def test_param_def_is_the_one_of_core(self) -> None:
        """RF-008-01: ``gis`` no define su ``ParamDef``: usa el de ``core.params`` (también
        el que reexporta ``gis``), y sus 17 definiciones son del módulo ``gis``."""
        self.assertIs(params.ParamDef, core_params.ParamDef)
        self.assertIs(gis.ParamDef, core_params.ParamDef)
        self.assertEqual(len(params.DEFINITIONS), 17)
        for definition in params.DEFINITIONS:
            with self.subTest(key=definition.key):
                self.assertIsInstance(definition, core_params.ParamDef)
                self.assertEqual(definition.module, "gis")
                self.assertIs(params.param(definition.key), definition)

    def test_same_normalized_values_and_texts_as_before(self) -> None:
        """RF-006-11, RF-006-14, RF-006-16, RF-006-18, RF-006-23, RF-008-03: cada definición
        da, para la tabla :data:`CHECKS`, el mismo valor normalizado (y del mismo tipo) que la
        provisional, o el mismo texto con el código ``core.param_*``, en un ``ParamError`` con
        la clave como campo."""
        self.assertEqual(len(CHECKS), 104)
        self.assertEqual({key for key, _value, _result in CHECKS}, set(EXPECTED))
        for key, value, expected in CHECKS:
            with self.subTest(key=key, value=value):
                definition = params.param(key)
                if isinstance(expected, tuple) and isinstance(expected[0], str):
                    code, text = expected
                    with self.assertRaises(ParamError) as caught:
                        definition.check(value)
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(str(caught.exception), text)
                    self.assertEqual(caught.exception.field, key)
                    self.assertEqual(caught.exception.obj, "Parámetro")
                else:
                    result = definition.check(value)
                    self.assertEqual(result, expected)
                    self.assertIs(type(result), type(expected))

    def test_same_range_text_as_before(self) -> None:
        """RF-008-03: ``range_text()`` en español y en inglés, como la provisional."""
        self.assertEqual(set(RANGES), set(EXPECTED))
        for key, (spanish, english) in RANGES.items():
            with self.subTest(key=key):
                self.assertEqual(params.param(key).range_text(), spanish)
                self.assertEqual(params.param(key).range_text("en"), english)

    def test_labels_with_their_spanish(self) -> None:
        """RF-008-06 (principio 10): cada definición lleva su etiqueta para el panel de
        parámetros, un ``msgid`` en inglés, distinto en cada una y sin marcadores, con su
        español en ``core/i18n/messages.toml``."""
        table = i18n.load_messages()
        labels = [definition.label_msgid for definition in params.DEFINITIONS]
        self.assertEqual(len(set(labels)), 17, "etiquetas repetidas o sin etiqueta")
        for definition in params.DEFINITIONS:
            label = definition.label_msgid
            with self.subTest(key=definition.key, label=label):
                self.assertIsInstance(label, str)
                self.assertTrue(label.strip())
                self.assertEqual(set(label) & SPANISH_LETTERS, set(), "msgid en inglés")
                self.assertEqual(i18n.placeholders(label), set())
                self.assertIn(label, table)
                self.assertTrue(table[label].strip())
                self.assertNotEqual(table[label], label)
                self.assertEqual(i18n.translate("es", label), table[label])

    def test_registered_and_removed_without_trace(self) -> None:
        """RF-008-01: ``bl`` registra las 17 en ``core.params`` y las quita con
        ``unregister_definitions("gis")`` sin dejar rastro."""
        before = dict(core_params.DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "gis")
        core_params.register_definitions(params.DEFINITIONS)
        for definition in params.DEFINITIONS:
            self.assertIs(core_params.DEFINITIONS[definition.key], definition)
        self.assertEqual(core_params.unregister_definitions("gis"), 17)
        self.assertEqual(dict(core_params.DEFINITIONS), before)

    def test_no_gis_param_codes_left(self) -> None:
        """Plan 006 §5.6.9: los cuatro mensajes de parámetro de ``gis`` salen de
        ``gis/messages.py`` (los da ``core.params``), y ni el código ni las pruebas de la 006
        nombran ya un código de parámetro de ``gis``."""
        self.assertEqual([code for code in messages.MESSAGES if OLD_PARAM_CODE.match(code)], [])
        for suffix in ("not_number", "not_integer", "not_list", "out_of_range"):
            self.assertIn(f"core.param_{suffix}", core_params.MESSAGES)
        found = [
            f"{path.relative_to(ROOT).as_posix()}:{number}"
            for folder in FOLDERS_OF_006
            for path in sorted(folder.rglob("*.py"))
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if OLD_PARAM_CODE.search(line)
        ]
        self.assertEqual(found, [])

    def test_detector_sees_old_codes(self) -> None:
        """Control positivo: el detector ve un código de parámetro de ``gis`` en un texto."""
        self.assertIsNotNone(OLD_PARAM_CODE.search("``GisError`` ``gis" + ".param_*``"))
        self.assertIsNone(OLD_PARAM_CODE.search("``ParamError`` ``core.param_*``"))


class PortsImportsTest(unittest.TestCase):
    """ARQ-10 (plan 006 §5.3.1; vision-general.md §2.3): ``gis/ports.py`` solo importa
    la biblioteca estándar, numpy y ``core``; base de RF-006-01 a RF-006-31."""

    def test_ports_imports_only_stdlib_numpy_and_core(self) -> None:
        self.assertEqual(_forbidden_imports(PORTS_FILE.read_text(encoding="utf-8")), [])

    def test_detector_sees_forbidden_imports(self) -> None:
        """Control positivo: un import de otro paquete, de un hermano de ``gis`` (también
        bajo ``TYPE_CHECKING``), de una librería externa o dinámico se detecta."""
        seeded = (
            "from __future__ import annotations\n"
            "import numpy as np\n"
            "from collections.abc import Callable\n"
            "from ..core.georef import CrsRef\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from .raster import Raster\n"
            "from ..jobs import catalog\n"
            "import pyproj\n"
            "import importlib\n"
            "x = importlib.import_module('pyproj')\n"
        )
        self.assertCountEqual(
            _forbidden_imports(seeded), [".raster", "..jobs", "pyproj", "import_module(…)"]
        )


class PortsContractTest(unittest.TestCase):
    """Plan 006 §5.3.1: nombres y firmas de los puertos (RF-006-05, RF-006-07,
    RF-006-08, RF-006-13, RF-006-24; la 005 usa ``CrsService``)."""

    def _params(self, function: object) -> list[tuple[str, str]]:
        signature = inspect.signature(function)  # type: ignore[arg-type]
        return [(p.name, p.kind.name) for p in signature.parameters.values()]

    def test_protocols(self) -> None:
        """Los cuatro puertos son ``Protocol`` comprobables con ``isinstance`` (sin
        ``runtime_checkable``, ``isinstance`` lanzaría ``TypeError``)."""
        for name in ("RasterIO", "Triangulator", "Transform", "CrsService"):
            with self.subTest(port=name):
                port = getattr(ports, name)
                self.assertTrue(is_protocol(port))
                self.assertNotIsInstance(object(), port)

    def test_signatures(self) -> None:
        positional, keyword = "POSITIONAL_OR_KEYWORD", "KEYWORD_ONLY"
        expected = {
            ports.RasterIO.read: [("self", positional), ("path", positional),
                                  ("progress", keyword), ("cancelled", keyword)],
            ports.RasterIO.write: [("self", positional), ("raster", positional),
                                   ("path", positional), ("profile", keyword)],
            ports.Triangulator.triangulate: [("self", positional), ("xy_local", positional),
                                             ("edges", positional)],
            ports.Transform.apply: [("self", positional), ("xyz", positional)],
            ports.CrsService.identify_wkt: [("self", positional), ("wkt", positional)],
            ports.CrsService.transformer: [("self", positional), ("src", positional),
                                           ("src_v", positional), ("dst", positional),
                                           ("dst_v", positional)],
            ports.CrsService.scale_factor: [("self", positional), ("crs", positional),
                                            ("xy", positional)],
            ports.CrsService.grid_convergence: [("self", positional), ("crs", positional),
                                                ("xy", positional)],
        }
        for function, parameters in expected.items():
            with self.subTest(function=function.__qualname__):
                self.assertEqual(self._params(function), parameters)
        self.assertIn("name", ports.Triangulator.__annotations__)
        self.assertIn("info", ports.Transform.__annotations__)

    def test_runtime_check(self) -> None:
        """Un triangulador con ``name`` y ``triangulate`` cumple el puerto; sin
        ``triangulate``, no (las pruebas de contrato de T17 y T23 lo usan)."""

        class Fake:
            name = "pure@0"

            def triangulate(self, xy_local: object, edges: object) -> object:
                return xy_local

        class Nameless:
            name = "nada@0"

        self.assertIsInstance(Fake(), ports.Triangulator)
        self.assertNotIsInstance(Nameless(), ports.Triangulator)

    def test_write_profile(self) -> None:
        self.assertEqual([p.value for p in ports.WriteProfile], ["project", "deliverable"])
        self.assertEqual(ports.WriteProfile("deliverable"), ports.WriteProfile.DELIVERABLE)

    def test_transform_info(self) -> None:
        """RF-006-05: descripción, precisión en m (``None`` = desconocida) y rejillas;
        inmutable; una precisión negativa o no finita no se construye."""
        info = ports.TransformInfo("ED50 a ETRS89 (IGN)", 0.2, ("es_ign_SPED2ETV2.tif",))
        self.assertEqual(info.accuracy_m, 0.2)
        self.assertEqual(info.grids, ("es_ign_SPED2ETV2.tif",))
        self.assertIsNone(ports.TransformInfo("ballpark", None).accuracy_m)
        self.assertEqual(ports.TransformInfo("identidad", 0.0).grids, ())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            info.accuracy_m = 1.0  # type: ignore[misc]
        for bad in (-0.1, math.inf, math.nan):
            with self.subTest(accuracy=bad), self.assertRaises(ValueError):
                ports.TransformInfo("mala", bad)

    def test_triangulation_error(self) -> None:
        """El error del contrato del triangulador es un error de Geoblender."""
        self.assertTrue(issubclass(ports.TriangulationError, errors.GeoblenderError))

    def test_package_reexports(self) -> None:
        """``gis`` reexporta la API de esta tarea (plan §5.1)."""
        for name in ("RasterIO", "Triangulator", "Transform", "TransformInfo",
                     "CrsService", "WriteProfile", "TriangulationError", "ParamDef",
                     "GisError", "TopoReport", "Conflict", "ResampleReport", "TinReport",
                     "SurfaceReport"):
            with self.subTest(name=name):
                self.assertIn(name, gis.__all__)
                self.assertTrue(hasattr(gis, name))


class MessagesTest(unittest.TestCase):
    """Principio 10: códigos ``gis.*`` con ``msgid`` en inglés y texto en español (base de
    RF-006-01 a RF-006-31; ejemplos del plan 006 §5.5)."""

    def test_catalog(self) -> None:
        codes = [m.code for m in messages.CATALOG]
        self.assertEqual(len(codes), len(set(codes)), "códigos repetidos")
        self.assertEqual(set(messages.MESSAGES), set(codes))
        for message in messages.CATALOG:
            with self.subTest(code=message.code):
                self.assertRegex(message.code, r"^gis\.[a-z][a-z0-9_]*$")
                self.assertIn(message.severity, ("error", "warning"))
                self.assertNotEqual(message.msgid, message.es)
                self.assertEqual(_fields(message.msgid), _fields(message.es))
                for name in _fields(message.es):
                    self.assertRegex(name, r"^[a-z][a-z0-9_]*$")
                self.assertEqual(messages.CATALOG_ES[message.msgid], message.es)

    def test_codes_named_by_the_plan(self) -> None:
        """Los códigos que citan el plan y las tareas están en el catálogo (el de exportar
        sobre una entrada lo da la 008: ``test_inputs_untouched``)."""
        for code in ("gis.step_invalid", "gis.grid_mismatch", "gis.crs_undeclared",
                     "gis.crs_catalog_mismatch", "gis.transform_unknown_accuracy",
                     "gis.xyz_not_grid"):
            with self.subTest(code=code):
                self.assertIn(code, messages.MESSAGES)

    def test_examples_of_the_plan(self) -> None:
        """Los ejemplos del plan §5.5, tal cual."""
        cases = (
            ("gis.tiff_compression_unsupported",
             {"file": "dron_2026_08.tif", "name": "JPEG", "value": 7},
             "MDT «dron_2026_08.tif»: compresión JPEG (código 7) no admitida. Guárdelo en "
             "QGIS con compresión DEFLATE o LZW y vuelva a importarlo."),
            ("gis.value_not_number",
             {"file": "levantamiento.csv", "row": 128, "column": "Z", "header": "cota",
              "value": "12,3,4"},
             "Puntos «levantamiento.csv», fila 128, columna Z («cota»): «12,3,4» no es un "
             "número."),
            ("gis.breaklines_cross",
             {"tin": "topo_2026", "first": "PIE_3", "second": "CAB_2",
              "position": "736 412,318; 4 435 217,904", "first_z": "182,40",
              "second_z": "187,95"},
             "TIN «topo_2026»: las líneas de rotura «PIE_3» y «CAB_2» se cruzan en "
             "(736 412,318; 4 435 217,904) con cotas 182,40 m y 187,95 m."),
            ("gis.ellipsoidal_suspected", {"dtm": "mdt_2025", "median": 51.3},
             "La mediana de la diferencia con el MDT «mdt_2025» es de 51,3 m: las cotas "
             "pueden ser alturas elipsoidales (GNSS o dron sin geoide). ¿Continuar?"),
        )
        for code, values, text in cases:
            with self.subTest(code=code):
                self.assertEqual(messages.render(code, **values), text)

    def test_render_values(self) -> None:
        """Decimales con coma en español y punto en inglés; un marcador sin valor queda
        «?», nunca «{…}»; un código o un idioma desconocidos son un error del programa."""
        self.assertEqual(
            messages.render("gis.step_invalid", value=0.25),
            "El paso de rejilla 0,25 m no es válido: debe ser múltiplo de 0,5 m entre 0,5 "
            "y 5 m.",
        )
        english = messages.render("gis.step_invalid", language="en", value=0.25)
        self.assertIn("0.25", english)
        self.assertIn("?", messages.render("gis.step_invalid"))
        self.assertNotIn("{", messages.render("gis.step_invalid"))
        self.assertEqual(messages.format_value(2.0), "2")
        self.assertEqual(messages.format_value(True), "sí")
        with self.assertRaises(ValueError):
            messages.render("gis.no_such_code")
        with self.assertRaises(ValueError):
            messages.render("gis.step_invalid", language="fr", value=1.0)

    def test_gis_error(self) -> None:
        """``GisError``: un ``GeoblenderError`` con código, ``msgid``, valores (JSON),
        objeto, campo y valor (también el marcador ``{value}``), cuyo texto es el del
        catálogo en español."""
        error = messages.GisError("gis.step_invalid", obj="Rejilla", field="paso",
                                  value=0.75)
        self.assertIsInstance(error, errors.GeoblenderError)
        self.assertEqual(error.code, "gis.step_invalid")
        self.assertEqual(error.msgid, messages.MESSAGES["gis.step_invalid"].msgid)
        self.assertEqual(error.values, {"value": 0.75})
        self.assertEqual((error.obj, error.field, error.value), ("Rejilla", "paso", 0.75))
        self.assertEqual(str(error), messages.render("gis.step_invalid", value=0.75))
        self.assertIn("0,75", str(error))
        self.assertEqual(error.message, str(error))
        json.dumps(error.values)

    def test_warnings_are_not_errors(self) -> None:
        """Un aviso (``severity = "warning"``) no se lanza como error."""
        warning = next(m for m in messages.CATALOG if m.severity == "warning")
        with self.assertRaises(ValueError):
            messages.GisError(warning.code, obj="MDT", field="cota")


class ReportsTest(unittest.TestCase):
    """Informes de la 006 (diagnóstico CALCULADO): RF-006-09, RF-006-11, RF-006-12,
    RF-006-14, RF-006-16 y RF-006-23."""

    def test_topo_report(self) -> None:
        """RF-006-12: leídas, aceptadas, rechazadas (número y motivo) y duplicadas."""
        rejection = reports.Rejection(row=128, code="gis.value_not_number", reason="texto")
        report = reports.TopoReport(source="taludes.csv", read=44, points=20, lines=4,
                                    duplicates=1, rejected=(rejection,))
        self.assertEqual(report.rejected_count, 1)
        self.assertEqual(report.rejected[0].row, 128)

    def test_conflict(self) -> None:
        """RF-006-14: identificadores, posición X, Y y las dos cotas."""
        conflict = reports.Conflict(reports.ConflictKind.CROSSING_LINES, ("PIE_3", "CAB_2"),
                                    736412.318, 4435217.904, (182.40, 187.95))
        self.assertAlmostEqual(conflict.dz, 5.55, places=12)
        self.assertEqual(conflict.kind, "crossing_lines")

    def test_resample_report(self) -> None:
        """RF-006-11: método, fracción mínima, celdas con y sin dato y área."""
        info = ports.TransformInfo("ED50 a ETRS89", 0.2, ("es_ign_SPED2ETV2.tif",))
        report = reports.ResampleReport(method="area_mean", min_valid_fraction=1.0,
                                        cells=12, valid_cells=9, cell_area_m2=0.25,
                                        transform=info, supersample=4)
        self.assertEqual(report.nodata_cells, 3)
        self.assertEqual(report.valid_area_m2, 2.25)

    def test_tin_report(self) -> None:
        """RF-006-16 (planos antes y después, puntos añadidos, cimas sin acotar) y
        RF-006-23 (lado máximo, degenerados)."""
        report = reports.TinReport(triangulator="pure@1", input_points=20, vertices=44,
                                   triangles=70, constraint_edges=20, flat_pct_before=19.0,
                                   flat_pct=0.5, points_added=12)
        self.assertEqual(report.unresolved_flat_regions, 0)
        self.assertEqual(report.degenerate, 0)

    def test_surface_report(self) -> None:
        """RF-006-23: área y porcentaje sin dato, huecos, fuera de ventana y de rango."""
        report = reports.SurfaceReport(surface_type="grid", area_m2=3072.0,
                                       nodata_area_m2=12.0, hole_areas_m2=(12.0,),
                                       cells_outside_window=0, out_of_range=2,
                                       z_range_m=(-500.0, 5000.0))
        self.assertEqual(report.nodata_pct, 12.0 / 3072.0 * 100.0)
        empty = reports.SurfaceReport(surface_type="tin", area_m2=0.0, nodata_area_m2=0.0,
                                      hole_areas_m2=(), cells_outside_window=0,
                                      out_of_range=0, z_range_m=(-500.0, 5000.0))
        self.assertEqual(empty.nodata_pct, 0.0)

    def test_immutable_and_json(self) -> None:
        """Inmutables y serializables a JSON con ``dataclasses.asdict``."""
        info = ports.TransformInfo("identidad", 0.0)
        built = (
            reports.TopoReport(source="a.csv", read=1, points=1),
            reports.Conflict(reports.ConflictKind.DUPLICATE_POINTS, ("1", "2"), 1.0, 2.0,
                             (3.0, 3.5)),
            reports.ResampleReport(method="bilinear", min_valid_fraction=1.0, cells=1,
                                   valid_cells=1, cell_area_m2=1.0, transform=info),
            reports.TinReport(triangulator="pure@1", input_points=3, vertices=3,
                              triangles=1, constraint_edges=0),
            reports.SurfaceReport(surface_type="grid", area_m2=1.0, nodata_area_m2=0.0,
                                  hole_areas_m2=(), cells_outside_window=0,
                                  out_of_range=0, z_range_m=(-500.0, 5000.0)),
        )
        self.assertEqual(reports.KIND, "CALCULADO")
        for report in built:
            with self.subTest(report=type(report).__name__):
                field = dataclasses.fields(report)[0].name
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(report, field, None)
                json.loads(json.dumps(dataclasses.asdict(report)))


if __name__ == "__main__":
    unittest.main()
