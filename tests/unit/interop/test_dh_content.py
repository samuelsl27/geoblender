# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectores de contenido de los sondeos (spec 005, T39; HU-005-1, HU-005-2; RF-005-03,
RF-005-12; RF-008-08, RF-008-09, RF-008-14; ADR-0024; plan 005 §5.6.2).

``interop.dh_content`` declara tres lectores (``ContentReader`` de la 008): ``io.dh_csv@1``,
``io.dh_xlsx@1`` e ``io.recmin_mdb@1``. Con los datos de ``tests/data/dh/``:

- **Tablas** (CSV y XLSX; RF-005-12, RF-008-08): cada tabla de ``csv_basico`` con «;» y coma
  decimal, la misma con «,» y punto, en Windows-1252 o con una línea antes de la cabecera, y la
  hoja equivalente de ``csv_basico.xlsx``, dan el mismo hash de datos (y, con las mismas
  declaraciones, el mismo de contenido); otra correspondencia de columnas, otro CRS, otro
  datum, otra referencia del azimut, otra declinación, otro convenio de inclinación u otra
  unidad, otro hash de contenido; un valor cambiado, otro hash de datos; una columna sin papel,
  el orden de las filas, no; una fila rechazada cuenta con su texto. Las declaraciones y los
  ajustes de la entrada (``drillholes.provenance.input_spec``) dan el mismo hash.
- **RecMin** (RF-005-13): con un extractor de prueba (las tablas de los guiones, sin motor),
  una parte por tabla que lee el importador: otra tabla ``NOTAS``, ``SECCIONES`` o una
  desconocida, el orden de filas y columnas o un Single como float32 o como su float, el mismo
  hash; un Single cambiado, otro. El extractor solo ve una copia privada, que se borra al
  acabar, al fallar y al cancelar. Con el motor de Access (``adapters.registry``), las bases
  sintéticas Jet 4 y ACE con los mismos datos dan el mismo hash, que es el del guion sin motor;
  con otra ``NOTAS``, el mismo; con un Single cambiado, otro.
- Avance y cancelación entre trozos (RNF-008-11); la carpeta de la fuente intacta
  (``assert_source_untouched``; RF-005-03, RF-008-14); el envoltorio del trabajo
  ``core_content_hash`` los tiene en su lista estática (``"interop"``) y da el hash del hilo
  (RF-008-09).
"""

from __future__ import annotations

import concurrent.futures
import csv
import io
import os
import re
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.data.dh import build_xlsx
from tests.support import dh_sets, recmin
from tests.support.package import import_geoblender
from tests.support.provenance_checks import (
    assert_source_untouched,
    source_changes,
    source_state,
)
from tests.support.resources import WINDOWS, WINDOWS_HINT, is_available, requires, skip_reason
from tests.support.trees import age_folders

dh_content = import_geoblender("interop.dh_content")
tabular = import_geoblender("interop.drillholes_tabular")
base = import_geoblender("interop.base")
ports = import_geoblender("interop.ports")
schema = import_geoblender("interop.recmin.schema")
csv_tables = import_geoblender("interop.csv_tables")
model = import_geoblender("drillholes.model")
provenance = import_geoblender("drillholes.provenance")
readers = import_geoblender("core.content.readers")
encoder = import_geoblender("core.content.encoder")
worker = import_geoblender("workers.core_content_hash")
content_hash = import_geoblender("jobs.content_hash")
job_paths = import_geoblender("jobs.paths")
worker_api = import_geoblender("jobs.worker_api")
checks = import_geoblender("core.provenance.checks")

CSV, XLSX, MDB = dh_content.DH_CSV, dh_content.DH_XLSX, dh_content.RECMIN_MDB
BASICO = dh_sets.BASICO
FILES: dict[str, str] = dict(dh_sets.basico_expected()["files"])  # papel → fichero
ROLES = tuple(FILES)
H25830, V5782 = dh_sets.H25830, dh_sets.V5782
CSV_SETTINGS = {"encoding": "utf-8", "separator": ";", "header_row": 0, "decimal": ",",
                "date_format": "%d/%m/%Y"}
SMALL_CHUNK = 256  # bytes entre dos ``yield``: varios trozos con los datos de prueba
V12 = recmin.RECMIN_DIR / "recmin_v12.sql"
NOTES_TABLE = (
    "CREATE TABLE [notas] (\n  [ID] COUNTER CONSTRAINT [pk_notas] PRIMARY KEY,\n"
    "  [TEXTO] TEXT(100)\n);\n"
)
SINGLE_BEFORE = "VALUES (1002, 58.5, 60.5, 101, 1250, 1.85, 'sulfuro');"
SINGLE_AFTER = "VALUES (1002, 58.5, 60.5, 101, 1250, 1.86, 'sulfuro');"
_NUMBER_ES = re.compile(r"[<>]?-?\d+,\d+")


def _mapping(role: str) -> dict[str, str]:
    """La correspondencia que propone ``suggest_mapping`` con las cabeceras del CSV."""
    table = dh_sets.basico_tables()[role]
    return tabular.suggest_mapping(role, table.columns)


def _declaration(**changes: Any) -> Any:
    """La declaración de ``csv_basico`` (EPSG:25830 y EPSG:5782, azimut de cuadrícula,
    inclinación negativa hacia abajo, coma decimal), con ``changes``."""
    found = dh_sets.basico_expected()["declaration"]
    values: dict[str, Any] = dict(
        crs=H25830, vertical=V5782, azimuth_ref=found["azimuth_ref"],
        declination_deg=found["declination_deg"],
        inclination_convention=found["inclination_convention"], units=found["units"],
        value_rules=model.ValueRules(decimal_mark=found["decimal_mark"]),
        all_vertical=found["all_vertical"], density_kind=found["density_kind"],
        date_format=found["date_format"],
    )
    values.update(changes)
    return model.SourceDeclaration(**values)


def _recmin_declaration(**changes: Any) -> Any:
    values: dict[str, Any] = dict(
        crs=H25830, vertical=V5782, azimuth_ref=model.AzimuthRef.GRID, declination_deg=None,
        inclination_convention=model.InclinationConvention.NEGATIVE_DOWN, units={},
        value_rules=model.ValueRules(decimal_mark="."))
    values.update(changes)
    return model.SourceDeclaration(**values)


def _request(reader: Any, path: Path, role: str | None, *, decl: Any = None,
             mapping: dict | None = None, settings: dict | None = None,
             chunk_bytes: int = readers.DEFAULT_CHUNK_BYTES, kind: str | None = None) -> Any:
    """La petición de ``reader`` para la fuente ``path`` con las declaraciones de la
    importación (``source_declarations``) y sus ajustes de lectura."""
    if reader is MDB:
        decl = _recmin_declaration() if decl is None else decl
        declarations = provenance.source_declarations(reader.id, decl)
        settings = {"decimal": "."} if settings is None else settings
    else:
        decl = _declaration() if decl is None else decl
        mapping = _mapping(role) if mapping is None else mapping
        declarations = provenance.source_declarations(reader.id, decl, role=role,
                                                      mapping=mapping)
        if settings is None:
            settings = dict(CSV_SETTINGS) if reader is CSV else {
                "sheet": Path(FILES[role]).stem, "header_row": 0, "decimal": ",",
                "date_format": "%d/%m/%Y"}
    kind = provenance.input_kind(reader.id, role) if kind is None else kind
    return reader.request(kind, declarations, {"main": path}, settings,
                          chunk_bytes=chunk_bytes)


def _digest(reader: Any, path: Path, role: str | None = None, *, progress: Any = None,
            cancelled: Any = None, **options: Any) -> Any:
    """El ``ContentDigest`` de una fuente con un lector (``read_content``)."""
    request = _request(reader, path, role, **options)
    return readers.read_content(reader, request, progress=progress, cancelled=cancelled)


def _steps(reader: Any, path: Path, role: str | None = None, **options: Any) -> list[float]:
    seen: list[float] = []
    _digest(reader, path, role, chunk_bytes=SMALL_CHUNK, progress=seen.append, **options)
    return seen


def _write_comma_variant(folder: Path) -> None:
    """``csv_basico`` con «,» de separador y punto decimal (los mismos textos)."""
    folder.mkdir(parents=True)
    for name in FILES.values():
        with (BASICO / name).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream, delimiter=";"))
        text = io.StringIO()
        writer = csv.writer(text, delimiter=",", lineterminator="\r\n")
        for row in rows:
            writer.writerow([field.replace(",", ".") if _NUMBER_ES.fullmatch(field) else field
                             for field in row])
        (folder / name).write_bytes(text.getvalue().encode("utf-8"))


def _write_lines(path: Path, lines: list[str], encoding: str = "utf-8") -> Path:
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode(encoding))
    return path


def _basico_lines(role: str) -> list[str]:
    return (BASICO / FILES[role]).read_text(encoding="utf-8").splitlines()


class _Temp(unittest.TestCase):
    """Una carpeta temporal por prueba, de ruta corta."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gb-dhc-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def progress_and_cancel(self, reader: Any, path: Path, role: str | None,
                            **options: Any) -> None:
        """Ayuda: avance creciente tras cada trozo hasta 1; cancelar tras el primero para
        entre dos trozos (``ReadCancelled``) y deja el fichero cerrado (se puede borrar)."""
        copy = self.tmp / f"copia{path.suffix}"
        shutil.copyfile(path, copy)
        seen = _steps(reader, copy, role, **options)
        self.assertGreaterEqual(len(seen), 3)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)
        self.assertLess(seen[-2], 1.0)
        stopped: list[float] = []
        with self.assertRaises(readers.ReadCancelled) as caught:
            _digest(reader, copy, role, chunk_bytes=SMALL_CHUNK, progress=stopped.append,
                    cancelled=lambda: bool(stopped), **options)
        self.assertEqual(stopped, seen[:1])
        self.assertLess(caught.exception.progress, 1.0)
        os.remove(copy)  # en Windows falla si sigue abierto


class DeclarationsTest(unittest.TestCase):
    """Los tres lectores y dónde se hashean."""

    def test_the_three_readers(self) -> None:
        """RF-005-12, RF-008-09 (plan §5.6.2): ``CONTENT_READERS`` son los tres lectores de las
        importaciones de la 005 (los de ``drillholes.provenance.READER_IDS``), del módulo
        ``io``; los de tablas dan unas bocas (``drillholes``) o una tabla (``table``); el de
        RecMin, unos sondeos sobre una copia (``needs_copy``); ninguno es SQLite y todos pueden
        ir al trabajo de hash. Una fuente externa de pocos bytes de CSV o XLSX se hashea en el
        hilo y una de 100 MB en el trabajo; una base de RecMin, siempre en el trabajo (su
        motor tarda más de 1 s en arrancar)."""
        found = {reader.id: reader for reader in dh_content.CONTENT_READERS}
        self.assertEqual(tuple(found), provenance.READER_IDS)
        kinds = {CSV.id: ("drillholes", "table"), XLSX.id: ("drillholes", "table"),
                 MDB.id: ("drillholes",)}
        for reader_id, reader in found.items():
            with self.subTest(lector=reader_id):
                self.assertIsInstance(reader, readers.ContentReader)
                self.assertEqual((reader.module, reader.kinds, reader.sqlite, reader.worker),
                                 ("io", kinds[reader_id], False, True))
                self.assertEqual(reader.needs_copy, reader is MDB)
                self.assertEqual(readers.plan_hash(reader, "external", 100 << 20),
                                 readers.JOB)
                small = readers.plan_hash(reader, "external", 4096)
                self.assertEqual(small, readers.JOB if reader is MDB else readers.INLINE)
                self.assertEqual(readers.plan_hash(reader, "project", None), readers.INLINE)

    def test_hashed_columns_are_fixed(self) -> None:
        """ADR-0024 §6: las columnas que hashean los lectores de tablas son las de cada papel,
        con ``raw`` al final, y no cambian (un lector publicado no cambia)."""
        self.assertEqual(sorted(dh_content.COLUMNS),
                         ["assay", "collar", "element_catalog", "lithology",
                          "lithology_catalog", "survey"])
        for name, columns in dh_content.COLUMNS.items():
            with self.subTest(papel=name):
                self.assertEqual(columns[-1], ("raw", "text"))
                self.assertTrue(set(kind for _, kind in columns) <= set(encoder.FIELD_TYPES))
        self.assertEqual([c for c, _ in dh_content.COLUMNS["assay"]],
                         ["hole", "from_m", "to_m", "element", "value", "unit",
                          "detection_flag", "sample_id", "lab", "method", "batch",
                          "external_id", "raw"])


class TabularTest(_Temp):
    """``io.dh_csv@1`` e ``io.dh_xlsx@1`` con ``csv_basico``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.shared = Path(tempfile.mkdtemp(prefix="gb-dhx-"))
        cls.addClassCleanup(shutil.rmtree, cls.shared, True)
        _write_comma_variant(cls.shared / "coma")
        cls.book = cls.shared / "csv_basico.xlsx"
        build_xlsx.basico_book().write(cls.book)
        cls.base = {role: _digest(CSV, BASICO / FILES[role], role) for role in ROLES}

    def test_same_data_whatever_the_reading(self) -> None:
        """RF-005-12, RF-008-08 (plan §5.6.2): cada tabla de ``csv_basico`` con «;» y coma, con
        «,» y punto y en su hoja de ``csv_basico.xlsx`` da el mismo hash de datos y, con las
        mismas declaraciones, el mismo de contenido (el separador, el decimal, la hoja y el
        libro no son contenido); cada papel da otro."""
        comma = dict(CSV_SETTINGS, separator=",", decimal=".")
        for role in ROLES:
            with self.subTest(papel=role):
                first = self.base[role]
                second = _digest(CSV, self.shared / "coma" / FILES[role], role, settings=comma)
                third = _digest(XLSX, self.book, role)
                self.assertEqual({d.data_sha256 for d in (first, second, third)},
                                 {first.data_sha256})
                self.assertEqual({d.content_sha256 for d in (first, second, third)},
                                 {first.content_sha256})
                self.assertEqual((first.reader, third.reader), (CSV.id, XLSX.id))
        self.assertEqual(len({d.data_sha256 for d in self.base.values()}), len(ROLES) - 1)
        self.assertEqual(self.base["assay_wide"].data_sha256,
                         self.base["assay_long"].data_sha256)  # los mismos valores
        self.assertNotEqual(self.base["assay_wide"].content_sha256,
                            self.base["assay_long"].content_sha256)  # otro papel

    def test_what_is_hashed(self) -> None:
        """RF-008-08 (ADR-0024 §1 y §6): el hash de datos de unas desviaciones es el de una
        tabla sin orden con las columnas de su papel (``COLUMNS["survey"]``) y, por fila, el
        sondeo tal como está y los números con su decimal interpretado (``raw`` nulo)."""
        rows = []
        for line in _basico_lines("survey")[1:]:
            hole, depth, azimuth, inclination = line.split(";")
            rows.append([hole, *(float(x.replace(",", ".")) for x in (depth, azimuth,
                                                                     inclination)),
                         None, None, None])
        hasher = encoder.ContentHasher("table", declarations={})
        expected = hasher.rows(dh_content.COLUMNS["survey"], False, rows).digest()
        self.assertEqual(self.base["survey"].data_sha256, expected.data_sha256)

    def test_encoding_and_header_row_are_reading_settings(self) -> None:
        """RF-008-08 (plan §5.6.2): las bocas en Windows-1252, o con una línea de título antes
        de la cabecera (``header_row`` 1), dan el mismo hash."""
        lines = _basico_lines("collar")
        latin = _write_lines(self.tmp / "bocas_1252.csv", lines, "cp1252")
        titled = _write_lines(self.tmp / "bocas_titulo.csv", ["Bocas de la campaña", *lines])
        found = {
            _digest(CSV, latin, "collar", settings=dict(CSV_SETTINGS, encoding="cp1252")),
            _digest(CSV, titled, "collar", settings=dict(CSV_SETTINGS, header_row=1)),
        }
        self.assertEqual(found, {self.base["collar"]})

    def test_declarations_are_content(self) -> None:
        """RF-005-07, RF-008-08 (ADR-0024 §3): otra correspondencia de columnas, otro CRS,
        otro datum vertical, otra referencia del azimut, otra declinación, otro convenio de
        inclinación u otra unidad dan otro hash de contenido; lo que no cambia lo leído (el
        CRS, el datum y los convenios, que no se transforman al leer), el mismo de datos."""
        local = dh_sets.CATALOG.local_vertical("cota de obra")
        magnetic = dict(azimuth_ref=model.AzimuthRef.MAGNETIC, declination_deg=0.25)
        cases = {
            "crs": ("collar", {"decl": _declaration(crs=dh_sets.CATALOG.horizontal(23030))},
                    True),
            "datum": ("collar", {"decl": _declaration(vertical=local)}, True),
            "acimut": ("survey", {"decl": _declaration(**magnetic)}, True),
            "convenio": ("survey", {"decl": _declaration(
                inclination_convention=model.InclinationConvention.POSITIVE_DOWN)}, True),
            "unidad": ("assay_wide", {"decl": _declaration(
                units={"Au": "ppm", "Ag": "ppm", "Cu": "%"})}, False),
            "correspondencia": ("collar", {"mapping": {
                key: value for key, value in _mapping("collar").items()
                if key != "campaign"}}, False),
        }
        declination = _digest(CSV, BASICO / FILES["survey"], "survey",
                              decl=_declaration(**dict(magnetic, declination_deg=0.5)))
        for name, (role, options, same_data) in cases.items():
            with self.subTest(declaración=name):
                found = _digest(CSV, BASICO / FILES[role], role, **options)
                self.assertNotEqual(found.content_sha256, self.base[role].content_sha256)
                self.assertEqual(found.data_sha256 == self.base[role].data_sha256, same_data)
                if name == "acimut":
                    self.assertNotEqual(declination.content_sha256, found.content_sha256)
                    self.assertEqual(declination.data_sha256, found.data_sha256)

    def test_what_is_imported_counts(self) -> None:
        """RF-005-09, RF-008-08: un valor cambiado (también la orientación en boca de un
        sondeo sin desviaciones) da otro hash de datos; una columna que no
        está en la correspondencia (no se importa) o el orden de las filas, no; una fila que
        se rechaza cuenta con su texto (corregirla o cambiarla da otro hash)."""
        lines = _basico_lines("collar")
        header, rows = lines[0], lines[1:]

        def collars(name: str, body: list[str], head: str = header) -> Any:
            return _digest(CSV, _write_lines(self.tmp / name, [head, *body]), "collar")

        changed = [rows[0].replace("700010,500", "700010,600"), *rows[1:]]
        oriented = [row.replace(";300,00;-75,00;", ";300,00;-74,00;") for row in rows]
        self.assertNotEqual(oriented, rows)  # la orientación en boca de S-12
        extra = [f"{row};nota {n}" for n, row in enumerate(rows)]
        bad_x = [rows[0].replace("700010,500", "abc"), *rows[1:]]
        other_bad = [rows[0].replace("700010,500", "abd"), *rows[1:]]
        base_hash = self.base["collar"].data_sha256
        self.assertNotEqual(collars("cambiado.csv", changed).data_sha256, base_hash)
        self.assertNotEqual(collars("orientada.csv", oriented).data_sha256, base_hash)
        self.assertEqual(collars("extra.csv", extra, header + ";Notas").data_sha256, base_hash)
        self.assertEqual(collars("orden.csv", rows[::-1]).data_sha256, base_hash)
        rejected = collars("mal.csv", bad_x).data_sha256
        self.assertNotIn(rejected, (base_hash, collars("otra.csv", other_bad).data_sha256))

    def test_the_input_checks_with_the_same_hash(self) -> None:
        """RF-008-07, RF-008-08: con las declaraciones y los ajustes que guarda la entrada
        (``drillholes.provenance.input_spec``, con el hash del trabajo), el lector da el mismo
        hash al comprobarla: el mismo lector al importar y al comprobar."""
        inputs = import_geoblender("core.inputs")
        role, decl = "survey", _declaration()
        digest = self.base[role]
        spec = provenance.input_spec(
            CSV.id, "desviaciones",
            files=[inputs.SourceFile("fuentes/desviaciones.csv", "main", "original")],
            file_prints=[inputs.SourcePrint("a" * 64, size=1, mtime_ns=1)],
            digest=digest, declaration=decl, role=role, mapping=_mapping(role),
            settings={key: CSV_SETTINGS[key] for key in ("encoding", "separator",
                                                         "header_row")})
        request = CSV.request(spec.kind, spec.declarations,
                              {"main": BASICO / FILES[role]}, dict(spec.settings))
        self.assertEqual(readers.read_content(CSV, request), digest)

    def test_what_is_not_read_is_rejected(self) -> None:
        """RF-005-07 (plan §5.6.2): unas bocas sin CRS ni datum no se leen
        (``dh.declaration_missing``, como al importar); un papel que no es el de la entrada
        (bocas como ``table``), un ajuste de lectura que falta o que no es de este lector, una
        convención de otro papel o un ajuste distinto de su declaración son ``ValueError``; una
        correspondencia con una columna que no está, el ``MappingError`` del importador."""
        collars = BASICO / FILES["collar"]
        with self.assertRaises(base.DeclarationError) as caught:
            _digest(CSV, collars, "collar", decl=_declaration(crs=None, vertical=None))
        self.assertEqual(caught.exception.code, "dh.declaration_missing")
        settings = dict(CSV_SETTINGS)
        settings.pop("encoding")
        bad: dict[str, dict] = {
            "tipo": {"kind": "table"},
            "falta": {"settings": settings},
            "sobra": {"settings": dict(CSV_SETTINGS, sheet="bocas")},
            "distinto": {"settings": dict(CSV_SETTINGS, role="survey")},
        }
        for name, options in bad.items():
            with self.subTest(caso=name), self.assertRaises(ValueError):
                _digest(CSV, collars, "collar", **options)
        request = _request(CSV, collars, "collar")
        decl = dict(request.declarations)
        decl["conventions"] = dict(decl["conventions"], density_kind="MEDIDO")
        other = CSV.request("drillholes", decl, {"main": collars}, dict(CSV_SETTINGS))
        with self.assertRaises(ValueError):
            readers.read_content(CSV, other)
        with self.assertRaises(tabular.MappingError):
            _digest(CSV, collars, "collar", mapping=dict(_mapping("collar"), x="Este"))

    def test_progress_and_cancel(self) -> None:
        """RNF-008-11, RF-005-04: el avance crece tras cada trozo hasta 1 y cancelar tras el
        primero para entre dos trozos, con el fichero cerrado (CSV y XLSX)."""
        self.progress_and_cancel(CSV, BASICO / FILES["lithology"], "lithology")
        self.progress_and_cancel(XLSX, self.book, "assay_long")

    def test_reading_leaves_the_source_untouched(self) -> None:
        """RF-005-03, RF-008-14: leer cada tabla de una copia de ``csv_basico`` y su libro no
        crea, cambia ni borra nada en su carpeta."""
        folder = self.tmp / "fuente"
        shutil.copytree(BASICO, folder)
        shutil.copyfile(self.book, folder / self.book.name)
        age_folders(folder)
        with assert_source_untouched(folder):
            for role, name in FILES.items():
                _digest(CSV, folder / name, role)
                _digest(XLSX, folder / self.book.name, role)


# --- io.recmin_mdb@1 con un extractor de prueba -------------------------------------------------


class _FakeExtractor:
    """Un ``MdbExtractor`` sin motor: da las tablas que se le dan y anota qué abrió. Con
    ``block``, espera a que le pidan cancelar; con ``error``, lo lanza."""

    def __init__(self, tables: dict, *, block: bool = False, error: Exception | None = None
                 ) -> None:
        self.tables = tables
        self.block = block
        self.error = error
        self.opened: list[tuple[Path, bytes, Path]] = []
        self.cancelled_seen = threading.Event()

    def probe(self, path: Path) -> Any:  # pragma: no cover - no lo usa el lector
        return ports.MdbInfo(ports.MdbFormat.ACE, 2)

    def extract(self, path: Path, out_dir: Path, on_progress: Any, cancelled: Any) -> list:
        self.opened.append((Path(path), Path(path).read_bytes(), Path(out_dir)))
        out_dir.mkdir(parents=True)
        (out_dir / "schema.json").write_text("{}", encoding="utf-8")
        on_progress(0.5, "Leyendo")
        if self.error is not None:
            raise self.error
        while self.block:
            if cancelled():
                self.cancelled_seen.set()
                raise ports.MdbCancelled()
            time.sleep(0.005)
        on_progress(1.0, "Leída")
        return list(self.tables.values())


def _v12(**changes: Any) -> dict:
    """Las tablas de ``recmin_v12.sql`` como las da el extractor, con ``changes`` (nombre →
    tabla, o ``None`` para quitarla)."""
    tables = dict(recmin.raw_tables(V12))
    for name, table in changes.items():
        if table is None:
            tables.pop(name)
        else:
            tables[name] = table
    return tables


def _with_rows(table: Any, rows: list) -> Any:
    return ports.RawTable(table.name, table.columns, tuple(tuple(row) for row in rows))


class RecminTest(_Temp):
    """``io.recmin_mdb@1`` con un extractor de prueba (sin motor)."""

    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(dh_content.use_mdb_extractor, dh_content.use_mdb_extractor(None))
        self.source = self.tmp / "fuente"
        self.source.mkdir()
        self.mdb = self.source / "sondeos.mdb"
        self.mdb.write_bytes(os.urandom(3000))

    def read(self, tables: dict, **options: Any) -> Any:
        extractor = _FakeExtractor(tables)
        dh_content.use_mdb_extractor(extractor)
        found = _digest(MDB, self.mdb, **options)
        self.extractor = extractor
        return found

    def test_one_part_per_table_read(self) -> None:
        """RF-005-13, RF-005-02, RF-008-08 (plan §5.6.2): el hash es el de las tablas que lee
        el importador: con otra ``NOTAS``, otras ``secciones`` o una tabla desconocida, el
        orden de las filas y de las columnas cambiado o los Single como su float exacto, el
        mismo; con un Single cambiado, una fila más en una tabla adicional reconocida por su
        forma (``alteracion``) o sin la tabla de giros (vacía), otro."""
        tables = _v12()
        first = self.read(tables)
        samples = tables["muestras"]
        notes = ports.RawTable("NOTAS", (ports.RawColumn("TEXTO", ports.DBTYPE_WSTR, 50),),
                               (("nota",),))
        sections = _with_rows(tables["secciones"], [])
        unknown = ports.RawTable("calculos", (ports.RawColumn("X", ports.DBTYPE_R8),),
                                 ((1.5,),))
        flipped = ports.RawTable(samples.name, samples.columns[::-1],
                                 tuple(row[::-1] for row in samples.rows[::-1]))
        same = {
            "notas": _v12(NOTAS=notes),
            "secciones": _v12(secciones=sections),
            "desconocida": _v12(calculos=unknown),
            "orden": _v12(muestras=flipped),
            "float": dict(recmin.raw_tables(V12, singles_as_float=True)),
        }
        for name, changed in same.items():
            with self.subTest(igual=name):
                self.assertEqual(self.read(changed), first)
        rows = [list(row) for row in samples.rows]
        position = samples.position("ELEMENTO 2")
        rows[1][position] = np.float32(1.86)
        extra = tables["alteracion"]
        more = [*extra.rows, (99, np.float32(80.0), np.float32(81.5), 101, 7)]
        other = {
            "single": _v12(muestras=_with_rows(samples, rows)),
            "adicional": _v12(alteracion=_with_rows(extra, more)),
            "sin giros": _v12(giros=None),
        }
        for name, changed in other.items():
            with self.subTest(distinto=name):
                self.assertNotEqual(self.read(changed).data_sha256, first.data_sha256)

    def test_what_is_hashed(self) -> None:
        """RF-005-02, RF-008-08 (ADR-0024 §4 y §6): el hash de datos es el compuesto de una
        parte ``table`` por tabla que lee el importador (``schema.layout``), con su nombre en
        la base: sus columnas por nombre sin mayúsculas, con el tipo de su ``DBTYPE``, y sus
        filas sin orden, los Single por su decimal más corto (0,1 y no 0,10000000149…), las
        fechas en ISO y los decimales exactos como texto."""
        tables = _v12()
        found = schema.layout({t.name: [c.name for c in t.columns] for t in tables.values()})
        parts = {}
        for name in found.names:
            table = tables[name]
            order = sorted(table.columns, key=lambda c: c.name.casefold())
            kinds = [(c.name, dh_content.DBTYPE_FIELDS.get(c.type, "text")) for c in order]
            rows = []
            for row in table.rows:
                values = []
                for column in order:
                    value = row[table.columns.index(column)]
                    if column.type == ports.DBTYPE_R4 and value is not None:
                        value = float(np.format_float_positional(np.float32(value),
                                                                 unique=True))
                    elif hasattr(value, "isoformat"):
                        value = value.isoformat()
                    elif value is not None and kinds[order.index(column)][1] == "text":
                        value = str(value)
                    values.append(value)
                rows.append(values)
            feed = encoder.RowEncoder(kinds, False)
            feed.update(rows)
            parts[name] = ("table", feed.finish())
        self.assertIn("muestras", parts)
        self.assertNotIn("secciones", parts)
        self.assertEqual(self.read(tables).data_sha256, encoder.composite_sha256(parts))

    def test_declarations_are_content(self) -> None:
        """RF-005-07, RF-008-08: otro CRS, otro datum u otra referencia del azimut, otro hash
        de contenido y el mismo de datos; sin CRS ni datum, ``dh.declaration_missing``; una
        base sin la tabla de sondeos, ``dh.recmin_table_missing`` (como al importar)."""
        first = self.read(_v12())
        for name, decl in {
            "crs": _recmin_declaration(crs=dh_sets.CATALOG.horizontal(23030)),
            "datum": _recmin_declaration(vertical=dh_sets.CATALOG.local_vertical("obra")),
            "acimut": _recmin_declaration(azimuth_ref=model.AzimuthRef.TRUE),
        }.items():
            with self.subTest(declaración=name):
                found = self.read(_v12(), decl=decl)
                self.assertEqual(found.data_sha256, first.data_sha256)
                self.assertNotEqual(found.content_sha256, first.content_sha256)
        with self.assertRaises(base.DeclarationError) as caught:
            self.read(_v12(), decl=_recmin_declaration(crs=None))
        self.assertEqual(caught.exception.code, "dh.declaration_missing")
        with self.assertRaises(schema.RecminSchemaError) as caught:
            self.read(_v12(sondeos=None))
        self.assertEqual(caught.exception.code, "dh.recmin_table_missing")

    def test_the_extractor_only_sees_a_private_copy(self) -> None:
        """RF-005-03, RF-005-15, RF-008-14 (ADR-0018 §4): el extractor abre una copia con los
        mismos bytes en una carpeta temporal privada, nunca la fuente (el motor deja su
        fichero de bloqueo junto a lo que abre); la carpeta privada se borra al acabar y la de
        la fuente no cambia, también en el hilo (sin la copia de un trabajo)."""
        age_folders(self.source)
        with assert_source_untouched(self.source):
            self.read(_v12())
        ((path, data, out_dir),) = self.extractor.opened
        self.assertEqual(data, self.mdb.read_bytes())
        self.assertEqual(path.name, self.mdb.name)
        self.assertNotEqual(path.parent, self.source)
        self.assertTrue(path.parent.name.startswith(dh_content.PRIVATE_PREFIX))
        self.assertEqual(out_dir.parent, path.parent)
        self.assertFalse(path.parent.exists())

    def test_progress_cancel_and_failure(self) -> None:
        """RNF-008-11, RF-005-04, RF-005-14: el avance crece hasta 1; cancelar mientras
        extrae le pide al extractor que pare (cancela en ≤ 2 s) y borra la carpeta privada;
        un error del extractor (sin motor) sale tal cual, también sin dejar nada."""
        dh_content.use_mdb_extractor(_FakeExtractor(_v12()))
        self.progress_and_cancel(MDB, self.mdb, None)
        blocked = _FakeExtractor(_v12(), block=True)
        dh_content.use_mdb_extractor(blocked)
        seen: list[float] = []
        started = time.monotonic()
        with self.assertRaises(readers.ReadCancelled):
            _digest(MDB, self.mdb, progress=seen.append,
                    cancelled=lambda: bool(seen) and seen[-1] > dh_content.COPY_SHARE)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertTrue(blocked.cancelled_seen.is_set())
        self.assertFalse(blocked.opened[0][0].parent.exists())
        missing = ports.engine_missing("sondeos.mdb", ports.MdbFormat.ACE)
        failing = _FakeExtractor(_v12(), error=missing)
        dh_content.use_mdb_extractor(failing)
        with self.assertRaises(ports.MdbError) as caught:
            _digest(MDB, self.mdb)
        self.assertEqual(caught.exception.code, ports.MDB_ENGINE_MISSING)
        self.assertFalse(failing.opened[0][0].parent.exists())

    def test_default_extractor_and_port(self) -> None:
        """ADR-0018, ARQ-07: sin otro, el lector usa el extractor de
        ``adapters.registry.mdb_extractor()``; ``use_mdb_extractor`` da el anterior y solo
        admite un ``MdbExtractor``."""
        registry = import_geoblender("adapters.registry")
        mdb_reader = import_geoblender("adapters.mdb_reader")
        self.assertIsInstance(dh_content.mdb_extractor(), mdb_reader.OleDbProcessMdbExtractor)
        fake = _FakeExtractor({})
        self.assertIsNone(dh_content.use_mdb_extractor(fake))
        self.assertIs(dh_content.mdb_extractor(), fake)
        self.assertIs(dh_content.use_mdb_extractor(None), fake)
        with self.assertRaises(TypeError):
            dh_content.use_mdb_extractor(object())  # type: ignore[arg-type]
        self.assertTrue(callable(registry.mdb_extractor))


# --- io.recmin_mdb@1 con el motor de Access -----------------------------------------------------


def _variant(folder: Path, name: str, notes: str, *, single: bool = False) -> Path:
    """``recmin_v12.sql`` con una tabla ``notas`` (``notes``) y, con ``single``, un Single
    de ``muestras`` cambiado."""
    text = V12.read_text(encoding="utf-8")
    if single:
        assert SINGLE_BEFORE in text
        text = text.replace(SINGLE_BEFORE, SINGLE_AFTER)
    text += f"\n{NOTES_TABLE}\nINSERT INTO [notas] ([ID], [TEXTO]) VALUES (1, '{notes}');\n"
    path = folder / name
    path.write_bytes(text.encode("utf-8"))
    return path


class EngineTest(unittest.TestCase):
    """``io.recmin_mdb@1`` con las bases sintéticas que crea ``build_mdb.ps1`` y el extractor
    de ``adapters.registry`` (Jet 4 de Windows; ACE, si está)."""

    @classmethod
    def setUpClass(cls) -> None:
        if os.name != "nt":
            raise unittest.SkipTest(skip_reason(WINDOWS, WINDOWS_HINT))
        previous = dh_content.use_mdb_extractor(None)
        cls.addClassCleanup(dh_content.use_mdb_extractor, previous)
        cls.tmp = Path(tempfile.mkdtemp(prefix="gb-dhe-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        scripts, cls.source = cls.tmp / "guiones", cls.tmp / "fuente"
        scripts.mkdir()
        cls.source.mkdir()
        cls.ace = is_available(recmin.ACE)
        other = "ace" if cls.ace else "jet4"
        plan = {
            "base": (_variant(scripts, "base.sql", "nota inicial"),
                     ("jet4", "ace") if cls.ace else ("jet4",)),
            "notas": (_variant(scripts, "notas.sql", "otra nota"), (other,)),
            "single": (_variant(scripts, "single.sql", "nota inicial", single=True), (other,)),
        }
        with concurrent.futures.ThreadPoolExecutor(len(plan)) as pool:
            built = list(pool.map(lambda item: recmin.build_bases(cls.source, item[1],
                                                                  sql=item[0]),
                                  plan.values()))
        cls.paths = {(Path(sql).stem, engine): found.path
                     for build in built for (sql, engine), found in build.bases.items()}
        cls.scripts = {name: path for name, (path, _engines) in plan.items()}
        cls.other = other
        age_folders(cls.source)
        before = source_state(cls.source)
        with concurrent.futures.ThreadPoolExecutor(len(cls.paths)) as pool:
            digests = pool.map(lambda path: _digest(MDB, path), cls.paths.values())
            cls.digests = dict(zip(cls.paths, digests, strict=True))
        cls.changes = source_changes(before, source_state(cls.source))

    def test_the_engine_gives_the_script_hash(self) -> None:
        """RF-005-13, RF-005-02, RF-005-03, RF-008-08: la base sintética leída con el motor
        (Jet 4) da el hash del guion sin motor (las tablas que da el extractor son las del
        guion, los Single por su decimal más corto); con otra ``NOTAS`` (no se importa), el
        mismo; con un Single cambiado, otro. La carpeta de las bases no cambia al leerlas."""
        first = self.digests[("base", "jet4")]
        script = _FakeExtractor(dict(recmin.raw_tables(self.scripts["base"])))
        previous = dh_content.use_mdb_extractor(script)
        try:
            from_script = _digest(MDB, self.paths[("base", "jet4")])
        finally:
            dh_content.use_mdb_extractor(previous)
        self.assertEqual(first, from_script)
        self.assertEqual(self.digests[("notas", self.other)], first)
        self.assertNotEqual(self.digests[("single", self.other)].data_sha256,
                            first.data_sha256)
        self.assertEqual(self.changes, [])

    @requires(recmin.ACE, recmin.ACE_HINT)
    def test_jet4_and_ace_give_the_same_hash(self) -> None:
        """RF-005-13, RF-008-08: las bases Jet 4 y ACE con los mismos datos dan el mismo
        hash (el motor no cuenta)."""
        self.assertEqual(self.digests[("base", "ace")], self.digests[("base", "jet4")])


# --- El trabajo de hash -------------------------------------------------------------------------


class WorkerTest(_Temp):
    """El envoltorio en proceso aparte de ``core_content_hash`` (RF-008-09; ADR-0025 §2)."""

    def test_worker_has_the_drillhole_readers(self) -> None:
        """RF-008-09 (plan §5.6.2): ``workers/core_content_hash.py`` tiene ``interop`` en su
        lista estática; ``main`` registra sus lectores (en un proceso nuevo no hay nada
        registrado) y unas bocas en CSV y una base de RecMin (copiada con ``needs_copy``)
        dan el hash del hilo."""
        self.assertEqual(tuple(worker.READER_PACKAGES), ("core", "gis", "interop"))
        self.assertIs(worker.READER_PACKAGES["interop"], dh_content)
        self.addCleanup(dh_content.use_mdb_extractor,
                        dh_content.use_mdb_extractor(_FakeExtractor(_v12())))
        mdb = self.tmp / "fuente" / "sondeos.mdb"
        mdb.parent.mkdir()
        mdb.write_bytes(os.urandom(2000))
        sources = {
            "bocas": (CSV, "collar", BASICO / FILES["collar"]),
            "recmin": (MDB, None, mdb),
        }
        jobs_root = self.tmp / "jobs"
        jobs_root.mkdir()
        for label, (reader, role, path) in sources.items():
            with self.subTest(fuente=label):
                request = _request(reader, path, role)
                expected = readers.read_content(reader, request)
                ticket = checks.HashRequest(f"uid-{label}", label, reader.id, request.kind,
                                            dict(request.declarations),
                                            dict(request.settings), {"main": path}, "gbch/1",
                                            path.stat().st_size)
                job = content_hash.new_job(ticket)
                folder = job_paths.job_dir(jobs_root, job.job_uid).create()
                ctx = worker_api.WorkerContext(job, folder, worker_api.QueueSink(),
                                               cancel_event=threading.Event(),
                                               paths=content_hash.job_paths(ticket))
                with mock.patch.dict(readers._REGISTRY, clear=True):
                    summary = worker.main(ctx)
                    self.assertIs(readers.READERS[reader.id], reader)
                self.assertEqual((summary["data_sha256"], summary["content_sha256"]),
                                 (expected.data_sha256, expected.content_sha256))


if __name__ == "__main__":
    unittest.main()
