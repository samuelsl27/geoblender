# SPDX-License-Identifier: GPL-3.0-or-later
"""Informe de validación en CSV (spec 005, T11; HU-005-3; RF-005-19 y RF-005-16; spec §11;
plan 005 §3, §5.3 y §5.6.9).

- **Para Excel en español** (RF-005-19; spec §11): BOM UTF-8 (una sola vez, al principio),
  «;» de separador, coma decimal, una fila por incidencia (y una por cada nota de lo que no se
  evaluó, spec §8) y las tildes legibles al volver a leerlo con ``utf-8-sig``; los textos con
  «;» o comillas vuelven tal cual; también lo lee el lector de CSV de Geoblender
  (``interop.csv_tables``).
- **Las columnas de RF-005-16**: sondeo, código, nivel, alcance, tabla, esquema de logueo o
  elemento, código del catálogo, tramo o profundidad, campo, valor y el mensaje en español
  que dice qué corregir; la cabecera, el nivel y el alcance, en el catálogo de idioma.
- **Con todo ``tests/data/dh/csv_errores``**: las incidencias de sus casos (los 27 códigos de
  la tabla 4.4.1) y la nota sin MDT, una fila cada una, en el orden del informe.
- **Escritura** (plan §5.6.9): por un temporal y ``os.replace`` (el destino anterior se
  sustituye entero, sin restos); con el destino abierto por otro programa,
  ``dh.report_target_locked`` y el anterior intacto; en una carpeta que no existe,
  ``dh.report_write_failed``; una ruta demasiado larga, ``core.path_too_long`` sin escribir.
"""

from __future__ import annotations

import codecs
import csv
import io
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import dh_sets
from tests.support.dh_fakes import FakeSurface
from tests.support.package import import_geoblender

report = import_geoblender("drillholes.report")
validate = import_geoblender("drillholes.validate")
i18n = import_geoblender("core.i18n")
errors = import_geoblender("core.errors")
csv_tables = import_geoblender("interop.csv_tables")

HEADER = ["Sondeo", "Código", "Nivel", "Alcance", "Tabla", "Esquema o elemento",
          "Código del catálogo", "Desde (m)", "Hasta (m)", "Campo", "Valor", "Mensaje"]
"""La cabecera en español (RF-005-16: sondeo, código, nivel, tabla, tramo o profundidad,
campo, valor y mensaje; y lo que excluye un error, el esquema o el elemento y la entrada de un
catálogo)."""
NUMBER_COLUMNS = ("Desde (m)", "Hasta (m)")
SPANISH_NUMBER = re.compile(r"-?\d+(,\d+)?")
MESSAGES = validate.MESSAGES


def _issue(code: str, hole: int, name: str | None, table: str, message: str | None = None,
           args: dict | None = None, **fields):
    return validate.Issue(code, hole, name, table, message_id=MESSAGES[message or code],
                          message_args=args or {}, **fields)


def _sample_report():
    """Un informe pequeño con cada clase de valor: decimales (también uno sin cifras enteras
    y otro negativo), sí/no, vacío y sin valor (un cálculo), textos con tildes, «;» y
    comillas, una incidencia de un catálogo (sin sondeo) y una nota."""
    issues = (
        _issue("DH-E07", 0, "S-01", "dh_survey", "DH-E07.below",
               {"depth": 150.02, "bottom": 150.0, "tolerance": 0.01}, row_ref=3,
               depth_from=150.02, depth_to=150.02, field="depth", value=150.02),
        _issue("DH-E03", 1, "Sondeo-Ñ", "dh_collar", "DH-E03.invalid", {"depth": -5.0},
               row_ref=1, field="depth", value=-5.0),
        _issue("DH-W07", 1, "Sondeo-Ñ", "dh_assay", None,
               {"unit": 'oz;"t"', "element": "Au", "catalog_unit": "g/t"}, row_ref=0,
               element="Au", depth_from=0.5, depth_to=1.25, field="unit", value='oz;"t"'),
        _issue("DH-W08", 1, "Sondeo-Ñ", "dh_assay", None, {"value": -0.00001}, row_ref=1,
               element="Au", depth_from=1.25, depth_to=2.0, field="value", value=-0.00001),
        _issue("DH-W12", 0, "S-01", "dh_collar", row_ref=0, field="planned", value=True),
        _issue("DH-W05", 0, "S-01", "dh_collar", None,
               {"z": 812.5, "dem": 810.0, "dz": 2.5, "tolerance": 2.0}, row_ref=0, field="z"),
        _issue("DH-E11", 1, "Sondeo-Ñ", "dh_lithology", "DH-E11.lithology",
               {"code": "Pizarra", "log_set": "alteración"}, row_ref=4, log_set="alteración",
               depth_from=10.0, depth_to=12.5, field="lithology", value="Pizarra"),
        _issue("DH-W10", -1, None, "dh_lithology_code", None, {"code": "CAL"}, row_ref=0,
               log_set="lithology", catalog_code="CAL", field="density", value=""),
    )
    notes = (validate.Note("DH-W05", 1, "Sondeo-Ñ",
                           message_id=MESSAGES["DH-W05.outside"]),)
    return validate.ValidationReport(issues, 2, notes)


def _csv_errores_report():
    """Las incidencias de todos los casos de ``csv_errores`` (con la ventana de trabajo y la
    superficie de ``esperado.json``) y la nota de ``csv_basico`` sin MDT, en un informe."""
    params, window = dh_sets.params(), dh_sets.work_window()
    issues, holes = [], 0
    for case in dh_sets.error_cases():
        found = validate.validate(case.dset, params, work_window=window,
                                  surface=FakeSurface(dh_sets.H25830, dh_sets.V5782),
                                  stored_geom_xyz=case.stored_geom_xyz)
        issues += found.issues
        holes = max(holes, found.hole_count)
    notes = validate.validate(dh_sets.basico_set(), params).notes
    return validate.ValidationReport(tuple(issues), holes, notes)


def _parse(data: bytes) -> list[list[str]]:
    """Las filas de un CSV escrito por ``report``, leído como lo lee Excel en español."""
    text = data.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))


class _FolderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="gb-dhrep-"))
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def _listing(self) -> list[str]:
        return sorted(os.listdir(self.folder))


class SpanishCsvTest(_FolderTest):
    """RF-005-19: el CSV que abre bien Excel en español."""

    def test_bom_semicolon_decimal_comma_and_accents(self) -> None:
        """RF-005-19, spec §11: BOM UTF-8 al principio (y solo allí), «;», coma decimal, una
        fila por incidencia y por nota, las tildes legibles al volver a leerlo con
        ``utf-8-sig`` y los textos con «;» o comillas, tal cual; filas acabadas en CRLF."""
        found = _sample_report()
        path = self.folder / "Informe de validación.csv"
        self.assertEqual(report.write_csv(found, path), path)
        data = path.read_bytes()
        self.assertTrue(data.startswith(codecs.BOM_UTF8))
        self.assertEqual(data.count(codecs.BOM_UTF8), 1)
        self.assertEqual(data.count(b"\r\n"), 1 + len(found.issues) + len(found.notes))
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        text = data.decode("utf-8-sig")
        for word in ("Código del catálogo", "Sondeo-Ñ", "alteración", "Sin evaluar",
                     "está por debajo del fondo"):
            self.assertIn(word, text)
        rows = _parse(data)
        self.assertEqual(rows[0], HEADER)
        body = rows[1:]
        self.assertEqual(len(body), len(found.issues) + len(found.notes))
        message = [issue.message("es") for issue in found.issues]
        self.assertEqual(body[0], ["S-01", "DH-E07", "Error", "Sondeo", "dh_survey", "", "",
                                   "150,02", "150,02", "depth", "150,02", message[0]])
        self.assertIn("150,02 m", body[0][-1])
        self.assertEqual(body[1], ["Sondeo-Ñ", "DH-E03", "Error", "Sondeo", "dh_collar", "",
                                   "", "", "", "depth", "-5", message[1]])
        self.assertEqual(body[2], ["Sondeo-Ñ", "DH-W07", "Aviso", "", "dh_assay", "Au", "",
                                   "0,5", "1,25", "unit", 'oz;"t"', message[2]])
        self.assertIn(";", body[2][-1])  # el mensaje en español también lleva «;»
        self.assertEqual(body[3][7:11], ["1,25", "2", "value", "-0,00001"])
        self.assertEqual(body[4][9:11], ["planned", "sí"])
        self.assertEqual(body[5], ["S-01", "DH-W05", "Aviso", "", "dh_collar", "", "", "",
                                   "", "z", "", message[5]])
        self.assertIn("2,5 m", body[5][-1])
        self.assertEqual(body[6][:9], ["Sondeo-Ñ", "DH-E11", "Error", "Tabla", "dh_lithology",
                                       "alteración", "", "10", "12,5"])
        self.assertEqual(body[7], ["", "DH-W10", "Aviso", "", "dh_lithology_code",
                                   "lithology", "CAL", "", "", "density", "", message[7]])
        self.assertEqual(body[8], ["Sondeo-Ñ", "DH-W05", "Sin evaluar", "", "", "", "", "",
                                   "", "", "", found.notes[0].message("es")])
        self.assertEqual([tuple(row) for row in body], list(report.rows(found)))
        self.assertEqual(tuple(rows[0]), report.header())
        self.assertEqual(self._listing(), [path.name])

    def test_numbers_with_decimal_comma(self) -> None:
        """RF-005-19: cada número del CSV (tramo o profundidad y valor numérico) con coma
        decimal y sin separador de miles ni exponente, el decimal más corto que vuelve al
        mismo float64; −0 sale «0»."""
        cases = {150.02: "150,02", -5.0: "-5", 1e-05: "0,00001", 4_400_123.456: "4400123,456",
                 0.1 + 0.2: "0,30000000000000004", -0.0: "0", 1e21: "1000000000000000000000"}
        for value, shown in cases.items():
            with self.subTest(value=value):
                issue = _issue("DH-E07", 0, "S-01", "dh_survey", "DH-E07.above", row_ref=0,
                               depth_from=value, depth_to=value, field="depth", value=value)
                row = report.rows(validate.ValidationReport((issue,), 1))[0]
                self.assertEqual(row[7:9] + row[10:11], (shown, shown, shown))
                self.assertEqual(float(shown.replace(",", ".")), value)

    def test_texts_in_the_language_catalog(self) -> None:
        """Principio 10 de la constitución, RF-005-16: la cabecera, los niveles (error,
        aviso, sin evaluar) y los alcances (sondeo, tabla, registro) tienen su ``msgid`` en
        inglés y su español en ``core/i18n/messages.toml``."""
        self.assertEqual(i18n.untranslated(report.MESSAGE_IDS), [])
        self.assertEqual(list(report.header()), HEADER)
        record = _issue("DH-E04", -1, "X-9", "dh_lithology", row_ref=0, depth_from=0.0,
                        depth_to=1.0, field="hole", value="X-9", args={"hole": "X-9"})
        row = report.rows(validate.ValidationReport((record,), 0))[0]
        self.assertEqual(row[:5], ("X-9", "DH-E04", "Error", "Registro", "dh_lithology"))


class CsvErrorsReportTest(_FolderTest):
    """RF-005-16 y RF-005-19 con todo ``csv_errores``."""

    def test_one_row_per_issue_of_every_code(self) -> None:
        """RF-005-16, RF-005-19, CE-005-01: las incidencias de todos los casos de
        ``csv_errores`` (los 27 códigos) y la nota sin MDT dan una fila cada una, en el orden
        del informe, con su código, nivel, sondeo, tabla y mensaje en español; el lector de
        CSV de Geoblender las lee igual que Excel; los tramos, con coma decimal."""
        found = _csv_errores_report()
        self.assertEqual({issue.code for issue in found.issues}, set(validate.CODES))
        self.assertEqual([note.message_id for note in found.notes],
                         [MESSAGES["DH-W05.no_dem"]])
        path = self.folder / "informe.csv"
        report.write_csv(found, path)
        rows = _parse(path.read_bytes())
        table = csv_tables.read_table(path, encoding="utf-8", separator=";")
        self.assertEqual(table.columns, HEADER)
        self.assertEqual(table.rows, rows[1:])
        self.assertEqual(len(rows) - 1, len(found.issues) + len(found.notes))
        levels = {"error": "Error", "warning": "Aviso"}
        scopes = {"hole": "Sondeo", "table": "Tabla", "record": "Registro", None: ""}
        for row, issue in zip(rows[1:], found.issues, strict=False):
            with self.subTest(code=issue.code, hole=issue.hole_name):
                scope = None if issue.scope is None else str(issue.scope)
                self.assertEqual(row[:5], [issue.hole_name or "", issue.code,
                                           levels[str(issue.level)], scopes[scope],
                                           issue.table])
                self.assertEqual(row[-1], issue.message("es"))
                for column in NUMBER_COLUMNS:
                    cell = row[HEADER.index(column)]
                    if cell:
                        self.assertRegex(cell, SPANISH_NUMBER)
        self.assertEqual(rows[-1][:3], ["", "DH-W05", "Sin evaluar"])
        self.assertEqual(rows[-1][-1], found.notes[0].message("es"))


class WriteTest(_FolderTest):
    """Plan §5.6.9: por un temporal y ``os.replace``; los fallos, con su código."""

    def test_replaces_the_previous_file_entirely(self) -> None:
        """RF-005-19: un destino que ya existe se sustituye entero (sin restos ni
        temporales); el mismo informe da los mismos bytes."""
        path = self.folder / "informe.csv"
        path.write_bytes(b"anterior;" * 10_000)
        found = _sample_report()
        report.write_csv(found, path)
        first = path.read_bytes()
        report.write_csv(found, path)
        self.assertEqual(path.read_bytes(), first)
        self.assertEqual(first, report.csv_bytes(found))
        self.assertNotIn(b"anterior", first)
        self.assertEqual(self._listing(), ["informe.csv"])

    def test_target_open_in_another_program(self) -> None:
        """RF-005-19, plan §5.6.9: si otro programa (Excel) tiene abierto el destino,
        ``dh.report_target_locked`` con el nombre del fichero; el anterior sigue intacto y no
        queda el temporal."""
        path = self.folder / "informe.csv"
        path.write_bytes(b"anterior")
        denied = PermissionError(13, "Permission denied")
        with mock.patch.object(report.os, "replace", side_effect=denied):
            with self.assertRaises(errors.GeoblenderError) as caught:
                report.write_csv(_sample_report(), path)
        self.assertEqual(caught.exception.code, "dh.report_target_locked")
        self.assertIn("informe.csv", caught.exception.message)
        self.assertEqual(path.read_bytes(), b"anterior")
        self.assertEqual(self._listing(), ["informe.csv"])

    def test_folder_that_does_not_exist(self) -> None:
        """RF-005-19: en una carpeta que no existe, ``dh.report_write_failed`` con el motivo
        del sistema, sin crear nada; una ruta más larga de lo que admite Blender,
        ``core.path_too_long`` antes de escribir."""
        path = self.folder / "no existe" / "informe.csv"
        with self.assertRaises(errors.GeoblenderError) as caught:
            report.write_csv(_sample_report(), path)
        self.assertEqual(caught.exception.code, "dh.report_write_failed")
        self.assertEqual(self._listing(), [])
        long_path = self.folder / ("x" * 250 + ".csv")
        with self.assertRaises(errors.GeoblenderError) as caught:
            report.write_csv(_sample_report(), long_path)
        self.assertEqual(caught.exception.code, "core.path_too_long")
        self.assertEqual(self._listing(), [])

    def test_only_a_report(self) -> None:
        """Contrato: solo se escribe un ``ValidationReport``; un valor de una incidencia
        que no es texto, número, sí/no ni vacío es un error del programa."""
        with self.assertRaises(TypeError):
            report.write_csv([], self.folder / "informe.csv")
        odd = _issue("DH-W12", 0, "S-01", "dh_collar", row_ref=0, field="planned",
                     value=object())
        with self.assertRaises(TypeError):
            report.rows(validate.ValidationReport((odd,), 1))
        self.assertEqual(self._listing(), [])


if __name__ == "__main__":
    unittest.main()
