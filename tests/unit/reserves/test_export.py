# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar una cubicación (spec 011, T17; RF-011-24, RF-011-05; RNF-011-06; plan 011 D-29).

Sobre el proyecto de ``tests.support.res_fixtures`` (una copia para la clase): la columna
sintética guardada (``res.edit_materials``), sus densidades, K y porcentajes HIPÓTESIS en el
proyecto y la cubicación «Mensual octubre» de V01 con unidades (``res.volume``, con la rejilla
de diferencias, y ``res.tonnage``). Para la guarda de las escrituras de la 008, una entrada
registrada a mano: un documento de una carpeta «entregas» junto al proyecto, con un lector y
una importación de prueba (como ``tests/unit/core/inputs/test_registry.py``).

Exportar no es una operación (D-29): el CSV y la rejilla entregable se escriben desde lo
registrado. El CSV, para Excel en español: BOM de UTF-8, «;», coma decimal sin separador de
miles, una fila por valor con su ámbito, su dato, su unidad, su tipo y sus marcas, y la
cabecera con la procedencia; la rejilla, en el perfil ``deliverable`` de la 006 (Float32,
−9999).
"""

from __future__ import annotations

import codecs
import csv
import dataclasses
import io
import os
import re
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import res_fixtures as fx
from tests.support import timing
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered as contract_registered
from tests.support.provenance_readers import registered as readers_registered

export = import_geoblender("reserves.export")
provenance = import_geoblender("reserves.provenance")
store = import_geoblender("reserves.store")
table = import_geoblender("reserves.table")
volumes = import_geoblender("reserves.volumes")
surfaces = import_geoblender("reserves.surfaces")
res_messages = import_geoblender("reserves.messages")
operations = import_geoblender("core.provenance.operations")
contract = import_geoblender("core.provenance.contract")
readers = import_geoblender("core.content.readers")
content = import_geoblender("core.content")
hashing = import_geoblender("core.hashing")
inputs = import_geoblender("core.inputs")
input_registry = import_geoblender("core.inputs.registry")
i18n = import_geoblender("core.i18n")
paths = import_geoblender("core.paths")
units = import_geoblender("core.units")
timeutil = import_geoblender("core.timeutil")
session_mod = import_geoblender("core.project.session")
gis_reader = import_geoblender("gis.geotiff.reader")
gis_messages = import_geoblender("gis.messages")

NAME = "Mensual octubre"
START = surfaces.SurfaceRef(dataset=fx.START_GRID, label="Partida")
FINAL = surfaces.SurfaceRef(dataset=fx.FINAL_GRID, label="Final")
NOT_APPLICABLE = {"not_applicable": True}
NO_READ_ONLY = paths.ReadOnlyDirs.from_sources(None, [])
UNCONFIRMED = "depende de un valor sin confirmar"
HYPOTHESIS = "depende de una hipótesis"
NUMBER = re.compile(r"-?\d+(,\d+)?")
"""Un número del CSV: coma decimal, sin separador de miles ni exponente."""
TABLE_HEADER = ["Tabla", "Dominio", "Cota inferior de la rodaja (m)",
                "Cota superior de la rodaja (m)", "Unidad", "Componente", "Nombre",
                "Clave del dato", "Dato", "Valor", "Unidad de medida", "Tipo", "Marcas", "Nota"]


def _unread(request: Any) -> Any:
    raise AssertionError("las pruebas de la exportación no leen con el lector de prueba")


SOURCE = readers.ContentReader("test.res_delivery", 1, ("document",), False, False, None,
                               _unread)
IMPORT = contract.OperationDef("res.test_delivery", "1.0", "res", "Test delivery import", False)


def _drain(steps: Any) -> Any:
    last = None
    for last in steps:
        pass
    return last


def _local(moment: str) -> str:
    return timeutil.parse_utc(moment).astimezone().strftime("%d/%m/%Y %H:%M")


def _number(text: str) -> float | None:
    return None if text == "" else float(text.replace(",", "."))


def _read_csv(data: bytes) -> tuple[dict[str, list[list[str]]], list[list[str]]]:
    """La cabecera del CSV (primera celda → el resto de cada fila con ella) y la tabla (con
    sus títulos), separadas por la primera fila vacía."""
    lines = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), delimiter=";"))
    blank = lines.index([])
    head: dict[str, list[list[str]]] = {}
    for line in lines[:blank]:
        head.setdefault(line[0], []).append(line[1:])
    return head, lines[blank + 1:]


class ExportTest(fx.ResProjectCase):
    """El CSV de «Mensual octubre» (V01) y su rejilla de diferencias entregable."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(readers_registered(SOURCE))
        cls.enterClassContext(contract_registered(IMPORT))
        cls.column = fx.project_column()
        cls.declare(fx.column_values())
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(cls.project, provenance.EDIT_MATERIALS,
                                            settings={"units": len(cls.column.units)},
                                            executor="blender")
        store.save_materials(cls.project, handle, cls.column)
        request = volumes.VolumeRequest(NAME, START, FINAL, column=cls.column,
                                        difference_grid=True)
        cls.clock.advance(minutes=1)
        cls.volume = operations.begin_operation(
            cls.project, provenance.VOLUME, executor="blender", version=cls.v1.uid,
            settings=provenance.volume_settings(request),
            inputs=provenance.volume_inputs(request), params=provenance.volume_params(request))
        _drain(store.volume_run(cls.project, cls.volume, request))
        cls.clock.advance(minutes=1)
        cls.tonnage = operations.begin_operation(
            cls.project, provenance.TONNAGE, executor="blender", version=cls.v1.uid,
            settings=provenance.tonnage_settings(NAME), inputs=provenance.tonnage_inputs(NAME),
            params=provenance.tonnage_params(cls.column))
        _drain(store.tonnage_run(cls.project, cls.tonnage))
        cls.deliveries = cls.root.parent.parent / "entregas"
        cls.deliveries.mkdir()
        cls.register_delivery(cls.deliveries / "plano.pdf")
        cls.exports = cls.root / "exports"
        cls.clock.advance(minutes=1)
        cls.export = export.cubication_export(cls.project, NAME, version=cls.v1.code)

    @classmethod
    def register_delivery(cls, path: Path) -> None:
        """Registra ``path`` (un documento nuevo) como la entrada «Entrega» del proyecto, con
        su importación de prueba completada en la misma transacción."""
        path.write_bytes(b"%PDF-1.4 plano de la entrega\n")
        found = path.stat()
        data_sha = hashing.sha256_file(path)
        declarations = inputs.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
        digest = content.ContentDigest(
            data_sha, content.content_sha256("document", declarations, data_sha),
            content.NORMALIZER, SOURCE.id)
        spec = inputs.InputSpec(
            "Entrega", "document", "res", SOURCE.id,
            files=[input_registry.locate_source(path, cls.project, cls.project.userdata)],
            file_prints=[inputs.SourcePrint(data_sha, size=found.st_size,
                                            mtime_ns=found.st_mtime_ns)],
            digest=digest, crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE)
        handle = operations.begin_operation(cls.project, IMPORT.op_type, settings={},
                                            executor="blender")
        with cls.project.write_transaction() as conn:
            input_registry.register_input(conn, cls.project, spec, operation_uid=handle.uid)
            handle.complete(conn)

    def write(self, target: Path, **kw: Any) -> Path:
        return export.write_csv(self.export, target, project=self.project,
                                read_only=kw.pop("read_only", NO_READ_ONLY), **kw)

    def consumed(self, uid: str) -> dict[str, tuple[str, str]]:
        """Papel → (nombre del dato, hash) de lo que consumió la operación ``uid``."""
        return {role: (name, sha) for role, name, sha in self.query(
            "SELECT io.role, d.name, io.content_sha256 FROM gb_operation_io AS io JOIN "
            "gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND "
            "io.direction = 'in'", uid)}

    def stored_rows(self) -> list[tuple[str, Any]]:
        """(tabla, fila) de lo registrado: las de volúmenes y después las de toneladas."""
        found: list[tuple[str, Any]] = []
        with self.project.read() as conn:
            for family, label in ((provenance.VOLUMES, "Cubicación"),
                                  (provenance.TONNES, "Toneladas de la cubicación")):
                record = self.record(provenance.dataset_name(family, NAME), self.v1)
                found += [(label, row) for row in table.read_rows(conn, record.locator)]
        return found

    # --- Pruebas ----------------------------------------------------------------------------

    def test_csv_for_excel_in_spanish(self) -> None:
        """RF-011-24 (D-29): el CSV empieza por el BOM de UTF-8 y se lee de vuelta con
        ``csv`` y «;»: la cabecera con la cubicación, el proyecto, la versión y la revisión,
        las dos operaciones (su revisión, su fecha y su Geoblender), las superficies con el
        hash que consumió la operación, los parámetros con su valor, su unidad, su tipo, «sin
        confirmar» y su ámbito, la fecha de la exportación y la versión de Geoblender; y una
        fila por valor de las tablas registradas (volúmenes y toneladas), en su orden, con su
        ámbito, su clave y su dato en español, su valor exacto con coma decimal y sin separador
        de miles, su unidad, CALCULADO, sus marcas (los m³, «sin confirmar» por el espesor
        mínimo; las toneladas, además, la hipótesis de las densidades) y sus notas."""
        target = self.exports / self.export.default_name
        self.assertEqual(self.export.default_name, "mensual_octubre_V01.r1.csv")
        self.assertEqual(self.write(target), target)
        data = target.read_bytes()
        self.assertTrue(data.startswith(codecs.BOM_UTF8))
        self.assertEqual(data, export.csv_bytes(self.export))
        self.assertNotIn(b"\r\r", data)
        head, lines = _read_csv(data)

        self.assertEqual(head["Cubicación"], [[NAME]])
        self.assertEqual(head["Proyecto"], [[self.project.name]])
        self.assertEqual(head["Versión"], [["V01 · Definitiva", "BORRADOR"]])
        self.assertEqual(head["Revisión"], [["V01.r1", "abierta"]])
        done = {uid: (finished, version) for uid, finished, version in self.query(
            "SELECT uid, finished_at, geoblender_version FROM gb_operation WHERE uid IN (?, ?)",
            self.volume.uid, self.tonnage.uid)}
        self.assertEqual(head["Operación"], [
            [label, "V01.r1", _local(done[uid][0]), done[uid][1]]
            for label, uid in (("Cubicación entre superficies", self.volume.uid),
                               ("Toneladas de una cubicación", self.tonnage.uid))])
        entries = {line[0]: line[1:] for line in head["Entrada"]}
        used = self.consumed(self.volume.uid)
        self.assertEqual(entries["Superficie de partida"], list(used["start"]))
        self.assertEqual(entries["Superficie final"], list(used["final"]))
        self.assertEqual(used["start"][0], fx.START_GRID)
        self.assertEqual(entries["Columna de materiales"], list(used["materials"]))
        self.assertEqual(entries["Base de Capa útil"], list(used["base_capa_util"]))
        self.assertEqual(entries["Tabla de volúmenes"],
                         list(self.consumed(self.tonnage.uid)["volumes"]))
        parameters = {line[1]: line for line in head["Parámetro"]}
        self.assertEqual(parameters["res.min_thickness_m"],
                         ["Espesor mínimo de desmonte y terraplén", "res.min_thickness_m", "0",
                          "m", "ADOPTADO", "sin confirmar", "proyecto"])
        density = "res.unit.capa_util.caliza.density"
        self.assertEqual(parameters[density],
                         ["Densidad in situ · capa_util · caliza", density,
                          str(fx.column_values()[density]).replace(".", ","), "t/m³",
                          "HIPÓTESIS", "", "proyecto"])
        self.assertEqual(set(parameters), {"res.min_thickness_m", "res.anthropic_presence_m",
                                           *provenance.tonnage_params(self.column)})
        self.assertEqual(head["Fecha de la exportación"],
                         [[_local(timeutil.format_utc(self.clock.now()))]])
        self.assertEqual(head["Versión de Geoblender"],
                         [[self.project.session.geoblender_version]])

        self.assertEqual(lines[0], TABLE_HEADER)
        stored = self.stored_rows()
        self.assertEqual(len(lines) - 1, len(stored))
        names = {unit.code: unit.name for unit in self.column.units}
        names.update({item.code: item.name for unit in self.column.units
                      for item in unit.components})
        with_decimals = 0
        for line, (label, row) in zip(lines[1:], stored, strict=True):
            found = dict(zip(TABLE_HEADER, line, strict=True))
            with self.subTest(line=line):
                self.assertEqual(found["Tabla"], label)
                domain = {"*": "Todos los dominios", "": "Fuera de los dominios"}.get(
                    row.domain, row.domain)
                self.assertEqual(found["Dominio"], domain)
                self.assertEqual(_number(found["Cota inferior de la rodaja (m)"]), row.bench_z0)
                self.assertEqual(_number(found["Cota superior de la rodaja (m)"]), row.bench_z1)
                self.assertEqual(found["Unidad"], row.unit or "")
                self.assertEqual(found["Componente"], row.component or "")
                self.assertEqual(found["Nombre"],
                                 names.get(row.component or row.unit or "", ""))
                self.assertEqual(found["Clave del dato"], row.quantity)
                self.assertEqual(found["Dato"],
                                 i18n.translate("es", table.QUANTITIES[row.quantity].label))
                self.assertEqual(_number(found["Valor"]), row.value)  # exacto: repr
                if found["Valor"]:
                    self.assertRegex(found["Valor"], NUMBER)
                    with_decimals += "," in found["Valor"]
                self.assertEqual(found["Unidad de medida"], units.symbol(row.unit_code))
                self.assertEqual(found["Tipo"], "CALCULADO")
                marks = UNCONFIRMED if label == "Cubicación" else f"{HYPOTHESIS} · {UNCONFIRMED}"
                self.assertEqual(found["Marcas"], marks)
                self.assertEqual(found["Nota"], " · ".join(
                    res_messages.render(code) for code in row.notes))
        self.assertGreater(with_decimals, 0)
        for name, quantity in table.QUANTITIES.items():  # cada dato, con su español
            with self.subTest(quantity=name):
                self.assertNotEqual(i18n.translate("es", quantity.label), quantity.label)

    def test_csv_of_a_cubication_by_stages_has_the_stage_column(self) -> None:
        """RF-011-19, RF-011-24 (T38; F-3 de la verificación): la tabla del CSV de una
        cubicación por momentos lleva «Momento» tras «Tabla»: el momento de cada fila y, vacío,
        en las que comparan la suma con la directa (con su nota de la tolerancia); la de una
        cubicación, no. Los papeles de los momentos y de la directa, en español."""
        label = "Cubicación por momentos"
        rows = (export.ExportRow(label, table.row("cut_m3", 6.0), "", (UNCONFIRMED,),
                                 "Explotación"),
                export.ExportRow(label, table.row(
                    "stages_diff_pct", 30.0, notes=("res.note_stages_over_tolerance",)), "",
                    (UNCONFIRMED,)))
        found = dataclasses.replace(self.export, rows=rows, stages=True)
        _head, lines = _read_csv(export.csv_bytes(found))
        self.assertEqual(lines[0], [TABLE_HEADER[0], "Momento", *TABLE_HEADER[1:]])
        self.assertEqual(lines[1][:2] + lines[1][8:11], [label, "Explotación", "cut_m3",
                                                         "Desmonte", "6"])
        self.assertEqual(lines[2][:2] + [lines[2][10], lines[2][-1]],
                         [label, "", "30", "más que la tolerancia"])
        self.assertEqual(_read_csv(export.csv_bytes(self.export))[1][0], TABLE_HEADER)
        self.assertEqual((export._role_label("stage_2", {}), export._role_label("direct", {})),
                         ("Momento 2", "Cubicación directa"))

    def test_rows_of_the_panel_in_the_language_of_geoblender(self) -> None:
        """RF-011-23 (T25; D-16): lo que lee el panel de la cubicación, en el idioma de
        Geoblender (en inglés, las operaciones, las marcas y el ámbito «project» de un
        parámetro), y sus filas: las del CSV sin las de las toneladas que repiten los m³ in situ
        de una unidad entera de la tabla de volúmenes (así no llevan «depende de una
        hipótesis»); lo suelto, con su m³ in situ (V/K), se queda."""
        found = export.cubication_export(self.project, NAME, version=self.v1.code,
                                         language="en")
        self.assertEqual([item.label for item in found.header.operations],
                         ["Volumetrics between surfaces", "Tonnage of a cubication"])
        marks = {mark for item in found.header.operations for mark in item.marks}
        self.assertTrue(marks)
        self.assertFalse(marks & {UNCONFIRMED, HYPOTHESIS})
        self.assertEqual({item.key: item.scope for item in found.header.parameters}[
            "res.min_thickness_m"], "project")
        with self.assertRaises(ValueError):
            export.cubication_export(self.project, NAME, version=self.v1.code, language="fr")

        tonnes = "Toneladas de la cubicación"
        rows = export.shown_rows(self.export)
        kept = {id(item) for item in rows}
        dropped = [item for item in self.export.rows if id(item) not in kept]
        volumes = {(row.domain, row.bench, row.unit): row.value for label, row
                   in self.stored_rows() if label == "Cubicación" and row.quantity == "volume_m3"
                   and row.unit is not None}
        self.assertTrue(dropped)
        for item in dropped:
            with self.subTest(fila=item.row):
                self.assertEqual((item.table, item.row.component), (tonnes, None))
                self.assertIn(item.row.quantity, ("volume_m3", "in_situ_m3"))
                self.assertAlmostEqual(
                    item.row.value, volumes[(item.row.domain, item.row.bench, item.row.unit)],
                    delta=1e-9)
        self.assertFalse([item for item in rows if item.table == tonnes
                          and item.row.quantity == "volume_m3" and item.row.component is None])
        self.assertTrue([item for item in rows if item.table == tonnes
                         and item.row.quantity == "in_situ_m3" and item.row.component is None])

    def test_never_over_an_input_nor_inside_the_project(self) -> None:
        """RF-011-24, RF-008-15 (D-29): la guarda de la 008 rechaza el CSV en la carpeta de la
        fuente de una entrada (fuera del proyecto) y en una carpeta de solo lectura; dentro
        del proyecto solo va a ``exports/``, con la extensión «.csv»; con el proyecto en solo
        lectura, solo fuera de él. Ningún rechazo escribe nada; sobre un fichero que ya existe,
        solo con ``overwrite``."""
        dossiers = self.root.parent.parent / "expedientes"
        dossiers.mkdir()
        read_only = paths.ReadOnlyDirs.from_sources(str(dossiers), [])
        before = sorted(os.listdir(self.deliveries))
        refused = (
            (self.deliveries / "cubicacion.csv", "core.write_target_source_folder"),
            (dossiers / "cubicacion.csv", "core.write_target_read_only"),
            (self.root / "rasters" / "cubicacion.csv", "gis.export_inside_project"),
            (self.exports / "cubicacion.txt", "gis.export_extension_invalid"),
        )
        for target, code in refused:
            with self.subTest(code=code), self.assertRaises(Exception) as caught:
                self.write(target, read_only=read_only)
            self.assertEqual(getattr(caught.exception, "code", None), code)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + ".tmp").exists())
        self.assertIsInstance(caught.exception, gis_messages.GisError)
        self.assertEqual(sorted(os.listdir(self.deliveries)), before)
        self.assertEqual(os.listdir(dossiers), [])

        existing = self.exports / "existente.csv"
        existing.write_bytes(b"anterior")
        with self.assertRaises(gis_messages.GisError) as caught:
            self.write(existing)
        self.assertEqual(caught.exception.code, "gis.export_target_exists")
        self.assertEqual(existing.read_bytes(), b"anterior")
        self.write(existing, overwrite=True)
        self.assertEqual(existing.read_bytes(), export.csv_bytes(self.export))

        outside = self.root.parent.parent / "fuera" / "cubicacion.csv"
        outside.parent.mkdir()
        with mock.patch.object(session_mod.Project, "writable", new_callable=mock.PropertyMock,
                               return_value=False):
            with self.assertRaises(res_messages.ResError) as caught:
                self.write(self.exports / "solo_lectura.csv")
            self.assertEqual(caught.exception.code, "res.export_read_only_project")
            self.assertFalse((self.exports / "solo_lectura.csv").exists())
            self.write(outside)
        self.assertEqual(outside.read_bytes(), export.csv_bytes(self.export))

    def test_locked_target_keeps_the_previous(self) -> None:
        """RF-011-24 (D-29; plan §2.1): si otro programa tiene abierto el destino (Excel) y
        Windows no deja sustituirlo, ``gis.raster_target_locked`` con su nombre; el anterior
        sigue intacto y no queda el temporal."""
        if os.name != "nt":
            self.skipTest("solo en Windows: un fichero abierto no se puede sustituir")
        target = self.exports / "abierto.csv"
        target.write_bytes(b"anterior")
        with target.open("rb"), self.assertRaises(gis_messages.GisError) as caught:
            self.write(target, overwrite=True)
        self.assertEqual(caught.exception.code, "gis.raster_target_locked")
        self.assertEqual(caught.exception.obj, "abierto.csv")
        self.assertEqual(target.read_bytes(), b"anterior")
        self.assertEqual([p.name for p in self.exports.iterdir() if ".tmp" in p.name], [])

    def test_difference_grid_as_deliverable(self) -> None:
        """RF-011-05 (RF-006-24; D-29): la rejilla de diferencias de «Mensual octubre» se
        exporta a GeoTIFF entregable y el lector de la 006 la lee: Float32 con −9999, cada
        celda el float32 de la registrada y sin dato donde no lo tiene, la misma rejilla, CRS y
        referencia vertical. Sobre un fichero que ya existe, solo con ``overwrite``; una
        cubicación o una rejilla que no hay en V01, su rechazo."""
        target = self.exports / "diferencia.tif"
        written = export.export_difference(self.project, NAME, target, version=self.v1.uid,
                                           read_only=NO_READ_ONLY)
        self.assertEqual(written, target)
        record = self.record(provenance.dataset_name(provenance.DIFFERENCE_GRID, NAME), self.v1)
        stored = gis_reader.read_geotiff(self.root.joinpath(*record.locator.split("/")))
        found = gis_reader.read_geotiff(target)
        finite = np.isfinite(stored.values)
        expected = np.where(finite, stored.values.astype(np.float32), np.nan).astype(np.float64)
        same = (found.values == expected) | (np.isnan(found.values) & np.isnan(expected))
        self.assertTrue(same.all())
        self.assertEqual((found.source_dtype, found.nodata_value), ("float32", -9999.0))
        self.assertTrue(found.grid.same_geometry(stored.grid))
        self.assertEqual((found.declared_crs.epsg, found.declared_vertical.epsg), (25830, 5782))
        with self.assertRaises(gis_messages.GisError) as caught:
            export.export_difference(self.project, NAME, target, version=self.v1.uid,
                                     read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "gis.export_target_exists")
        with self.assertRaises(res_messages.ResError) as caught:
            export.export_difference(self.project, "Otra", self.exports / "otra.tif",
                                     version=self.v1.uid, read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "res.difference_unknown")
        with self.assertRaises(res_messages.ResError) as caught:
            export.cubication_export(self.project, NAME, version=self.v2.code)
        self.assertEqual(caught.exception.code, "res.cubication_unknown")
        self.assertIn("V02", caught.exception.message)
        self.assertFalse((self.exports / "otra.tif").exists())

    def test_six_thousand_rows_within_a_second(self) -> None:
        """RNF-011-06: el CSV de una tabla de 6 000 filas (20 dominios × 30 rodajas × 10
        unidades) se escribe en ≤ 1 s, una fila por valor."""
        template = self.export.rows[0]
        rows = tuple(
            dataclasses.replace(template, row=table.row(
                "volume_m3", 1234.5 + index, domain=f"Fase {index // 300}",
                bench=(600.0 + 10 * (index // 10 % 30), 610.0 + 10 * (index // 10 % 30)),
                unit=f"u{index % 10}"))
            for index in range(6000))
        big = dataclasses.replace(self.export, rows=rows)
        target = self.exports / "seis_mil.csv"

        def measure() -> float:
            start = time.perf_counter()
            export.write_csv(big, target, project=self.project, read_only=NO_READ_ONLY,
                             overwrite=True)
            return time.perf_counter() - start

        self.assertLessEqual(timing.least_of(measure, 1.0), 1.0)
        _head, lines = _read_csv(target.read_bytes())
        self.assertEqual(len(lines), 6001)
        self.assertEqual(lines[-1][TABLE_HEADER.index("Valor")], "7233,5")


if __name__ == "__main__":
    unittest.main()
