# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo importado y la base de los sondeos en el proyecto, sobre la 008 (spec 005, T38;
HU-005-1 a HU-005-4; RF-005-01, RF-005-04, RF-005-11, RF-005-12, RF-005-22; RF-008-07,
RF-008-17 a RF-008-19, RF-008-52 a RF-008-54; plan 005 §5.6.1 y §5.6.5).

``drillholes.store`` escribe en un proyecto real de esquema 2 (``create_project`` con un reloj
simulado), con los tipos de ``drillholes.provenance``, los lectores de la T39 y el de las tablas
del proyecto registrados:

- **lo importado** (``SourceWriter``): ``csv_basico`` (fuera del proyecto, en ``fuentes/``)
  leído fichero a fichero con el lector real deja una entrada por fichero con su hash, su CRS
  y su datum, sus tablas ``dh_src_*`` con las filas leídas (bit a bit), inmutables y protegidas,
  su informe en ``dh_import_log`` y su original; el mismo fichero otra vez se reutiliza; otra
  declinación es una sustitución con motivo que conserva lo anterior; un fallo, una
  cancelación o cerrar los pasos no dejan nada (RF-005-04); cada orden, una transacción;
- **la base** (``BaseWriter``): la de ``build_base`` reescrita por pasos, con el hash que da
  ``schema.table_digest`` y el mismo hash con el mismo contenido; ``read_steps`` la devuelve
  bit a bit; ``stale_holes`` da los sondeos cuya huella de la desviación cambió.

Cada prueba crea su proyecto y deja los registros de ``core`` como los encontró.
"""

from __future__ import annotations

import shutil
import sqlite3
import unittest
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import dh_sets
from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.dh_fakes import FakeCrsService
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_contract import registered, snapshot
from tests.support.trees import age_folders

store = import_geoblender("drillholes.store")
provenance = import_geoblender("drillholes.provenance")
schema = import_geoblender("drillholes.schema")
model = import_geoblender("drillholes.model")
build = import_geoblender("drillholes.build_base")
desurvey = import_geoblender("drillholes.desurvey")
tabular = import_geoblender("interop.drillholes_tabular")
csv_tables = import_geoblender("interop.csv_tables")
dh_content = import_geoblender("interop.dh_content")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
inputs = import_geoblender("core.inputs")
input_registry = import_geoblender("core.inputs.registry")
operations = import_geoblender("core.provenance.operations")
dataset_registry = import_geoblender("core.datasets.registry")
prov_messages = import_geoblender("core.provenance.messages")
create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
hashing = import_geoblender("core.hashing")
core_params = import_geoblender("core.params")
core_defs = import_geoblender("core.params.core_defs")
paths_mod = import_geoblender("core.paths")
errors = import_geoblender("core.errors")
wkb = import_geoblender("core.gpkg.wkb")
worker_api = import_geoblender("jobs.worker_api")

CRS, VERTICAL = dh_sets.H25830, dh_sets.V5782
CSV = provenance.DH_CSV
FILES: dict[str, str] = dict(dh_sets.basico_expected()["files"])  # papel → fichero
EXPECTED_ROWS: dict[str, int] = dict(dh_sets.basico_expected()["rows"])
CSV_SETTINGS = {"encoding": "utf-8", "separator": ";", "header_row": 0}
PYPROJ = {"pyproj": "3.7.2"}
ORIGINAL_LIMIT = "core.original_copy_limit"
CAMPAIGN = "Campaña 2026"
HOLES = ("C-01", "S-01", "S-02", "S-03", "S-04", "S-12")
# Lo importado de cada fichero de csv_basico: la boca y su orientación en boca (S-12), las
# desviaciones, la litología, los análisis y los catálogos.
SOURCE_ROLES = {"collar": ("collar", "survey"), "survey": ("survey",),
                "lithology": ("lithology",), "assay_wide": ("assay",),
                "lithology_catalog": ("catalog",), "element_catalog": ("catalog",)}
STATE_TABLES = ("gb_input", "gb_input_file", "gb_dataset", "gb_dataset_change")
ProvenanceError = prov_messages.ProvenanceError


def _recompute(request: Any) -> Any:  # pragma: no cover - ninguna prueba recalcula
    raise AssertionError("no se recalcula en estas pruebas")


def _declaration(**changes: Any) -> Any:
    """La declaración de ``csv_basico/esperado.json`` con ``changes``."""
    found = dh_sets.basico_expected()["declaration"]
    values: dict[str, Any] = dict(
        crs=CRS, vertical=VERTICAL, azimuth_ref=found["azimuth_ref"],
        declination_deg=found["declination_deg"],
        inclination_convention=found["inclination_convention"], units=found["units"],
        value_rules=model.ValueRules(decimal_mark=found["decimal_mark"]),
        all_vertical=found["all_vertical"], density_kind=found["density_kind"],
        date_format=found["date_format"])
    values.update(changes)
    return model.SourceDeclaration(**values)


def _drive(steps: Any) -> tuple[list[float], Any]:
    """Los avances de unos pasos y lo que devuelven."""
    seen: list[float] = []
    while True:
        try:
            seen.append(next(steps))
        except StopIteration as stop:
            return seen, stop.value


class _Ticks:
    """Un reloj simulado que avanza un segundo en cada lectura (cada paso cede tras una
    sentencia)."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


@contextmanager
def _readers_registered() -> Iterator[None]:
    done: list[str] = []
    try:
        for reader in (builtin.GPKG_LAYER, *dh_content.CONTENT_READERS):
            if reader.id not in readers.READERS:
                readers.register_reader(reader)
                done.append(reader.id)
        yield
    finally:
        for reader_id in reversed(done):
            readers.unregister_reader(reader_id)


def _bits(values: np.ndarray) -> list[Any]:
    """Los valores de una columna para comparar: los números por sus bits (sin −0,0 y con un
    solo NaN), ``extra`` como diccionario."""
    if values.dtype == np.float64:
        found = values + 0.0
        found[np.isnan(found)] = np.nan
        return found.view(np.int64).tolist()
    return [dict(value) if isinstance(value, Mapping) else value for value in values.tolist()]


class _StoreCase(unittest.TestCase):
    """Un proyecto de esquema 2 con los tipos de la 005, los lectores de la T39 y el de las
    tablas del proyecto, y ``csv_basico`` copiado en ``fuentes/``, fuera del proyecto."""

    def setUp(self) -> None:
        before = (snapshot(), dict(readers.READERS), dict(core_params.DEFINITIONS))
        self.addCleanup(lambda: self.assertEqual(
            (snapshot(), dict(readers.READERS), dict(core_params.DEFINITIONS)), before,
            "la prueba dejó algo registrado"))
        recompute = {name: _recompute for name in provenance.REPEATABLE}
        self.enterContext(registered(*provenance.operation_defs(recompute)))
        self.enterContext(_readers_registered())
        if ORIGINAL_LIMIT not in core_params.DEFINITIONS:
            core_params.register_definitions(core_defs.DEFINITIONS)
            self.addCleanup(core_params.unregister_definitions, "core")
        self.tmp = self.enterContext(project_tmp("gb-t38-"))
        (self.tmp / "proyectos").mkdir()
        self.sources = self.tmp / "fuentes"
        self.sources.mkdir()
        for name in FILES.values():
            shutil.copyfile(dh_sets.BASICO / name, self.sources / name)
        age_folders(self.sources)
        self.userdata = userdata_mod.UserData(self.tmp / "u")
        self.project = create.create_project(self.tmp / "proyectos", make_settings(),
                                             make_session(), self.userdata,
                                             clock=FakeClock()).project
        self.addCleanup(self.project.close)

    # --- Ayudas ---------------------------------------------------------------------------

    def begin(self, op_type: str = provenance.IMPORT_TABULAR) -> Any:
        return operations.begin_operation(self.project, op_type, settings={},
                                          executor="blender")

    def read(self, role: str, declaration: Any = None) -> Any:
        """Las filas de ``csv_basico`` del papel ``role`` leídas con el lector real."""
        table = csv_tables.read_table(self.sources / FILES[role], encoding="utf-8",
                                      separator=";")
        mapping = tabular.suggest_mapping(role, table.columns)
        decl = _declaration() if declaration is None else declaration
        return mapping, tabular.read_role(role, table, mapping, decl)

    def file_input(self, role: str, *, declaration: Any = None) -> dict[str, Any]:
        """Lo de un fichero de ``csv_basico`` que da su trabajo: su entrada (con el hash de
        contenido del lector de la T39 y el ancla del fichero), sus filas de lo importado y su
        informe."""
        decl = _declaration() if declaration is None else declaration
        mapping, rows = self.read(role, decl)
        path = self.sources / FILES[role]
        reader = readers.reader(CSV)
        request = reader.request(
            provenance.input_kind(CSV, role),
            provenance.source_declarations(CSV, decl, role=role, mapping=mapping),
            {"main": path}, {**CSV_SETTINGS, "decimal": ",", "date_format": "%d/%m/%Y"})
        stat = path.stat()
        spec = provenance.input_spec(
            CSV, f"{CAMPAIGN} · {FILES[role]}",
            files=[input_registry.locate_source(path, self.project, self.userdata)],
            file_prints=[inputs.SourcePrint(hashing.sha256_file(path), size=stat.st_size,
                                            mtime_ns=stat.st_mtime_ns)],
            digest=readers.read_content(reader, request), declaration=decl, role=role,
            mapping=mapping, settings=CSV_SETTINGS)
        tables = store.source_tables(collars=rows.collars, surveys=rows.surveys,
                                     lithology=rows.lithology, assays=rows.assays,
                                     catalogs=rows.catalogs)
        log = [store.LogLine.summary(role, rows.read, rows.imported, rows.rejected_records),
               *(store.LogLine.rejection(item) for item in rows.rejected)]
        return {"spec": spec, "tables": tables, "log": log, "rows": rows,
                "declaration": decl}

    def order(self, roles: tuple[str, ...], **options: Any) -> Any:
        """Una orden con un fichero de ``csv_basico`` por papel (``options``: los de
        ``SourceWriter.add`` comunes)."""
        writer = store.SourceWriter(self.project)
        for role in roles:
            found = self.file_input(role)
            writer.add(self.begin(), found["spec"], found["tables"], log=found["log"],
                       **options)
        return writer

    def query(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def tables(self) -> list[str]:
        return [row[0] for row in self.query(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'dh%' "
            "ORDER BY name")]

    def state(self) -> list[Any]:
        """Las entradas, los datos, sus cambios y las tablas de los sondeos."""
        found: list[Any] = [self.query(f"SELECT * FROM {table} ORDER BY 1")
                            for table in STATE_TABLES]
        return [*found, self.tables()]

    def status(self, handle: Any) -> tuple[str, str | None]:
        (row,) = self.query("SELECT status, status_reason FROM gb_operation WHERE uid = ?",
                            handle.uid)
        return row

    def assert_protected(self, table: str, input_name: str) -> None:
        """Lo importado no se cambia desde otra conexión (QGIS): el rechazo lo dice."""
        conn = sqlite3.connect(str(self.project.database_path), timeout=2.0,
                               isolation_level=None)
        self.addCleanup(conn.close)
        for sql in (f'UPDATE "{table}" SET extra = extra', f'DELETE FROM "{table}"'):
            with self.subTest(tabla=table, sql=sql), \
                    self.assertRaises(sqlite3.IntegrityError) as caught:
                conn.execute(sql)
            self.assertIn(f"{table}: es lo importado de la entrada «{input_name}»: no se "
                          "modifica", str(caught.exception))

    def assert_no_absolute_paths(self) -> None:
        stored = [self.query(f"SELECT * FROM {table}") for table in (
            "gb_input", "gb_input_file", "gb_operation", "gb_dataset", "gb_event",
            "gpkg_contents")]
        self.assertEqual(paths_mod.find_absolute_paths(stored), [])

    def stored_rows(self, table: str) -> list[tuple[Any, ...]]:
        """Las filas de una tabla de los sondeos sin el ``fid``, por su ``fid``."""
        columns = ", ".join(f'"{name}"' for name in schema.layout_of(table).insert_columns)
        return self.query(f'SELECT {columns} FROM "{table}" ORDER BY fid')


# --- Lo importado ------------------------------------------------------------------------------


class SourceWriterTest(_StoreCase):
    def test_csv_basico_one_input_per_file(self) -> None:
        """RF-005-01, RF-005-12, RF-008-07, RF-008-17, RF-008-52, RF-008-53 (plan §5.6.1, D-15):
        ``csv_basico`` en una orden deja una entrada por fichero (su lector, su tipo, su hash
        de contenido, el CRS y el datum de las bocas y «no aplica» en las demás tablas, la
        huella de su fichero y su ancla relativa), de importaciones «hechas» con ``pyproj``; lo
        importado de cada una en sus tablas ``dh_src_<rol>_<nombre>_<entrada8>`` con las filas
        leídas, bit a bit (y de vuelta, las columnas del lector), inmutable con su entrada y
        protegido (cambiarlo desde otra conexión aborta con el nombre de la entrada), con el hash
        de ``schema.table_digest``; su informe en ``dh_import_log`` con lo leído, importado y
        rechazado de cada tabla; y su original desde la copia del trabajo. La carpeta de la
        fuente no cambia y nada guarda una ruta absoluta."""
        roles = tuple(SOURCE_ROLES)
        with assert_source_untouched(self.sources):
            found = {role: self.file_input(role) for role in roles}
            writer = store.SourceWriter(self.project)
            items = {}
            for role in roles:
                contents = {} if role != "lithology" else {  # el hash que da el trabajo
                    "lithology": schema.table_digest(schema.source_layout("lithology"),
                                                     found[role]["tables"]["lithology"], CRS)}
                items[role] = writer.add(self.begin(), found[role]["spec"],
                                         found[role]["tables"], log=found[role]["log"],
                                         contents=contents, message=f"{role} importado")
            hashed: list[str] = []  # las tablas que hashea el registro (sin hash del trabajo)
            real = dataset_registry._computed

            def computed(conn: Any, project: Any, spec: Any, *args: Any, **kw: Any) -> Any:
                hashed.append(spec.locator)
                return real(conn, project, spec, *args, **kw)

            with mock.patch.object(dataset_registry, "_computed", side_effect=computed):
                progress, result = _drive(writer.steps(software=PYPROJ))
            self.assertNotIn(items["lithology"].datasets[0].locator, hashed)
            self.assertIn(items["survey"].datasets[0].locator, hashed)
            self.assertEqual(result, tuple(items.values()))
            self.assertTrue(writer.committed)
            self.assertEqual(progress, sorted(progress))
            work = self.tmp / "trabajo"
            for role, item in items.items():
                copy = work / role / FILES[role]
                copy.parent.mkdir(parents=True)
                shutil.copyfile(self.sources / FILES[role], copy)
                _drive(writer.originals(item, [copy]))
        for role, item in items.items():
            spec = found[role]["spec"]
            with self.subTest(fichero=FILES[role]):
                record = item.record
                self.assertEqual((record.name, record.kind, record.module, record.reader),
                                 (spec.name, "collar" == role and "drillholes" or "table",
                                  "dh", CSV))
                self.assertEqual(record.content_sha256, spec.digest.content_sha256)
                crs = ({"epsg": 25830}, {"epsg": 5782}) if role == "collar" else (
                    {"not_applicable": True}, {"not_applicable": True})
                self.assertEqual((dict(record.crs_h), dict(record.crs_v)), crs)
                (stored,) = self.query("SELECT status, original FROM gb_input WHERE uid = ?",
                                       record.uid)
                self.assertEqual(stored, ("current", "stored"))
                (file,) = self.query("SELECT anchor, path, sha256 FROM gb_input_file WHERE "
                                     "input_uid = ?", record.uid)
                self.assertEqual(file[2], hashing.sha256_file(self.sources / FILES[role]))
                self.assertFalse(Path(file[1]).is_absolute())
                self.assertEqual(self.status(item.handle), ("done", None))
                (software,) = self.query("SELECT software, message FROM gb_operation "
                                         "WHERE uid = ?", item.handle.uid)
                self.assertEqual(software, ('{"pyproj":"3.7.2"}', f"{role} importado"))
                originals = self.project.root / "originals" / record.uid
                self.assertEqual([path.name for path in originals.iterdir()], [FILES[role]])
                names = {item.name: item for item in item.datasets}
                self.assertEqual(sorted(names), sorted(
                    [schema.source_name(part, spec.name) for part in SOURCE_ROLES[role]]
                    + ["dh_import_log"]))
                tag = record.uid.partition("-")[0]
                for part in SOURCE_ROLES[role]:
                    dataset = names[schema.source_name(part, spec.name)]
                    rows = found[role]["tables"][part]
                    self.assertEqual(
                        (dataset.locator, dataset.kind, dataset.input_uid, dataset.immutable,
                         dataset.status),
                        (f"{dataset.name}_{tag}", "table", record.uid, True, "current"))
                    self.assertEqual(dataset.crs_epsg, 25830 if part == "collar" else None)
                    self.assertEqual(self.stored_rows(dataset.locator), rows)
                    self.assertEqual(dataset.content_sha256, schema.table_digest(
                        schema.source_layout(part), rows, CRS).content_sha256)
                read = found[role]["rows"]  # los análisis en columnas: 28 filas, 84 valores
                self.assertEqual(read.read, EXPECTED_ROWS[role])
                self.assertEqual(self.query(
                    "SELECT table_role, kind, n_read, n_imported, n_rejected, n_replaced "
                    "FROM dh_import_log WHERE operation_uid = ? AND input_uid = ?",
                    item.handle.uid, record.uid),
                    [(role, "summary", read.read, read.imported, 0, 0)])
        bocas = items["collar"].record
        self.assert_protected(f"dh_src_collar_campana_2026_bocas_csv_{bocas.uid[:8]}",
                              bocas.name)
        (changes,) = self.query("SELECT count(*) FROM gb_dataset_change c JOIN gb_dataset d "
                                "ON d.uid = c.dataset_uid WHERE d.name = 'dh_import_log'")
        self.assertEqual(changes, (len(roles),))
        self.assert_no_absolute_paths()

    def test_source_rows_back_to_the_columns(self) -> None:
        """RF-005-01, RF-005-02 (plan §5.6.1): las filas de lo importado (``source_tables``)
        vuelven a ser las columnas leídas (``source_entry``), bit a bit, también con los
        textos, las fechas, ``extra``, los catálogos y la orientación en boca; las verticales
        declaradas no se guardan (las crea ``dh.build_base``) y unas estaciones ya
        convertidas no se aceptan."""
        uid = "00000001-0000-4000-8000-000000000001"
        for role in SOURCE_ROLES:
            _, rows = self.read(role)
            tables = store.source_tables(collars=rows.collars, surveys=rows.surveys,
                                         lithology=rows.lithology, assays=rows.assays,
                                         catalogs=rows.catalogs)
            self.assertEqual(tuple(tables), SOURCE_ROLES[role])
            entry = store.source_entry(uid, _declaration(), tables, label=role)
            with self.subTest(papel=role):
                for name in ("collars", "surveys", "lithology", "assays"):
                    given, back = getattr(rows, name), getattr(entry, name)
                    for item in fields(given):
                        self.assertEqual(_bits(getattr(back, item.name)),
                                         _bits(getattr(given, item.name)), (name, item.name))
                self.assertEqual(entry.catalogs, rows.catalogs)
        dset = dh_sets.basico_set()  # con la vertical declarada de C-01
        declared = dset.surveys.source == list(model.StationSource).index(
            model.StationSource.DECLARED_VERTICAL)
        self.assertEqual(int(declared.sum()), 1)
        kept = store.source_tables(surveys=dset.surveys)["survey"]
        self.assertEqual(len(kept), len(dset.surveys) - 1)
        converted = dset.surveys.take(np.arange(len(dset.surveys)),
                                      azimuth_measured=dset.surveys.azimuth)
        with self.assertRaises(ValueError):
            store.source_tables(surveys=converted)

    def test_same_file_again_is_reused(self) -> None:
        """RF-008-54 (spec §8): el mismo fichero con los mismos ajustes otra vez reutiliza su
        entrada: la importación queda «cancelada» con el aviso y no se escribe nada (ninguna
        entrada, dato, cambio ni tabla nuevos)."""
        _drive(self.order(("collar",)).steps(software=PYPROJ))
        before = self.state()
        writer = self.order(("collar",))
        (item,) = writer.inputs
        self.assertTrue(item.reused)
        self.assertIsInstance(item.classification, inputs.Reuse)
        with mock.patch.object(self.project, "write_transaction",
                               side_effect=AssertionError("no escribe")):
            progress, result = _drive(writer.steps(software=PYPROJ))
        self.assertEqual((progress, result), ([], (item,)))
        self.assertIsNone(item.record)
        status, reason = self.status(item.handle)
        self.assertEqual(status, "cancelled")
        self.assertIn("ya está registrada con el mismo contenido", reason)
        self.assertEqual(self.state(), before)

    def test_other_declination_is_a_substitution(self) -> None:
        """RF-008-11, RF-008-54, RF-008-52, RF-005-11: las mismas desviaciones con otra
        referencia del azimut y otra declinación son los mismos datos con otros ajustes: sin la
        entrada a la que sustituye ni motivo, ``core.input_substitution_required`` sin escribir
        nada; con ellos, la anterior queda «sustituida» con el motivo y lo importado de ella se
        conserva (su tabla, sus filas y su protección), y la nueva ocupa su nombre en otra
        tabla."""
        writer = self.order(("survey",))
        _drive(writer.steps(software=PYPROJ))
        (old,) = writer.inputs
        old_table = schema.source_table("survey", old.name, old.record.uid)
        old_rows = self.stored_rows(old_table)
        before = self.state()
        magnetic = _declaration(azimuth_ref=model.AzimuthRef.MAGNETIC,
                                declination_deg=model.parse_declination("1,5"))
        found = self.file_input("survey", declaration=magnetic)
        self.assertEqual(found["spec"].digest.data_sha256, old.spec.digest.data_sha256)
        self.assertNotEqual(found["spec"].digest.content_sha256,
                            old.spec.digest.content_sha256)
        handle = self.begin()
        with self.assertRaises(ProvenanceError) as caught:
            store.SourceWriter(self.project).add(handle, found["spec"], found["tables"])
        self.assertEqual(caught.exception.code, "core.input_substitution_required")
        self.assertEqual(self.state(), before)
        reason = "El geólogo da la declinación de la campaña"
        writer = store.SourceWriter(self.project)
        item = writer.add(handle, found["spec"], found["tables"], log=found["log"],
                            previous_uid=old.record.uid, reason=reason)
        self.assertIsInstance(item.classification, inputs.Substitute)
        _drive(writer.steps(software=PYPROJ))
        (previous,) = self.query("SELECT status, status_reason FROM gb_input WHERE uid = ?",
                                 old.record.uid)
        self.assertEqual(previous, ("superseded", reason))
        self.assertEqual(item.record.previous_uid, old.record.uid)
        datasets = dict(self.query("SELECT locator, status FROM gb_dataset WHERE name = ?",
                                   schema.source_name("survey", old.name)))
        new_table = schema.source_table("survey", item.name, item.record.uid)
        self.assertEqual(datasets, {old_table: "superseded", new_table: "current"})
        self.assertEqual(self.stored_rows(old_table), old_rows)
        self.assertEqual(self.stored_rows(new_table), old_rows)
        self.assert_protected(old_table, old.name)

    def test_live_sources_back_as_entries(self) -> None:
        """RF-005-01, RF-005-02, RF-005-11 (spec 005, T25; plan §5.6.1 y §5.6.10): lo importado
        vigente vuelve, para ``dh.build_base``, como una entrada por fichero en el orden en que
        se registraron (``live_sources``), cada una con sus datos de lo importado por papel y
        lo que declaró su fichero; leída por pasos (``source_entry_steps``, un paso por trozo
        con el reloj de prueba), sus columnas son las de ``source_entry``, bit a bit, con su
        nombre lógico. Una entrada sustituida deja de estar: manda la que la sustituye; sin
        nada importado, ninguna. Sin la base, ``read_catalogs`` da los catálogos vacíos."""
        with self.project.read() as conn:
            self.assertEqual(store.live_sources(conn), ())
            self.assertEqual(store.read_catalogs(conn), model.Catalogs())
        roles = ("lithology_catalog", "collar", "survey", "lithology")
        found = {role: self.file_input(role) for role in roles}
        writer = store.SourceWriter(self.project)
        items = [writer.add(self.begin(), found[role]["spec"], found[role]["tables"])
                 for role in roles]
        _drive(writer.steps(software=PYPROJ))
        with self.project.read() as conn:
            sources = store.live_sources(conn)
            self.assertEqual([source.record.uid for source in sources],
                             [item.record.uid for item in items])
            for role, source in zip(roles, sources, strict=True):
                with self.subTest(papel=role):
                    self.assertEqual(tuple(source.datasets), SOURCE_ROLES[role])
                    for part, dataset in source.datasets.items():
                        self.assertEqual(dataset.name, schema.source_name(
                            part, found[role]["spec"].name))
                    decl = source.declaration
                    self.assertEqual((decl.crs, decl.vertical),
                                     (CRS, VERTICAL) if role == "collar" else (None, None))
                    expected = store.source_entry(source.record.uid, decl,
                                                  found[role]["tables"])
                    steps, entry = _drive(store.source_entry_steps(conn, source,
                                                                   clock=_Ticks()))
                    self.assertGreaterEqual(len(steps), len(SOURCE_ROLES[role]))
                    self.assertEqual(entry.label, found[role]["spec"].name)
                    self.assertIs(entry.declaration.crs, decl.crs)
                    for name in ("collars", "surveys", "lithology", "assays"):
                        given, back = getattr(expected, name), getattr(entry, name)
                        for item in fields(given):
                            self.assertEqual(_bits(getattr(back, item.name)),
                                             _bits(getattr(given, item.name)),
                                             (name, item.name))
                    self.assertEqual(entry.catalogs, expected.catalogs)
        magnetic = _declaration(azimuth_ref=model.AzimuthRef.MAGNETIC,
                                declination_deg=model.parse_declination("1,5"))
        other = self.file_input("survey", declaration=magnetic)
        writer = store.SourceWriter(self.project)
        item = writer.add(self.begin(), other["spec"], other["tables"],
                          previous_uid=items[2].record.uid, reason="Otra declinación")
        _drive(writer.steps(software=PYPROJ))
        with self.project.read() as conn:
            uids = [source.record.uid for source in store.live_sources(conn)]
            self.assertEqual(uids, [items[0].record.uid, items[1].record.uid,
                                    items[3].record.uid, item.record.uid])
            (survey,) = [source for source in store.live_sources(conn)
                         if source.record.uid == item.record.uid]
            self.assertEqual(survey.declaration.declination_deg, 1.5)

    def test_failure_or_cancellation_between_steps_leaves_nothing(self) -> None:
        """RF-005-04, RF-008-19: un fallo inyectado o una cancelación entre pasos dejan cada
        importación de la orden «fallida» o «cancelada» con su motivo y ninguna entrada, dato,
        cambio ni tabla nuevos, con el proyecto en escritura; cerrar los pasos sin terminarlos
        (al desregistrar) tampoco deja nada, y las importaciones siguen «en curso» (quedarán
        «interrumpidas» al abrir el proyecto)."""
        roles = ("collar", "survey", "lithology")
        before = self.state()
        calls = {"n": 0}
        real = store.insert_rows

        def failing(*args: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("fallo inyectado en la tercera sentencia")
            real(*args)

        writer = self.order(roles)
        with mock.patch.object(store, "insert_rows", side_effect=failing), \
                self.assertRaises(RuntimeError):
            _drive(writer.steps(software=PYPROJ, clock=_Ticks(), budget_s=0.5))
        for item in writer.inputs:
            status, reason = self.status(item.handle)
            self.assertEqual(status, "failed")
            self.assertIn("fallo inyectado", reason)
            self.assertIsNone(item.record)
        self.assertEqual(self.state(), before)
        self.assertTrue(self.project.writable)

        asked = {"n": 0}

        def cancelled() -> bool:
            asked["n"] += 1
            return asked["n"] >= 2

        writer = self.order(roles)
        steps = writer.steps(software=PYPROJ, clock=_Ticks(), budget_s=0.5,
                             cancelled=cancelled)
        with self.assertRaises(worker_api.JobCancelled):
            _drive(steps)
        for item in writer.inputs:
            status, reason = self.status(item.handle)
            self.assertEqual(status, "cancelled")
            self.assertIn("cancelada", reason)
        self.assertEqual(self.state(), before)

        writer = self.order(roles)
        steps = writer.steps(software=PYPROJ, clock=_Ticks(), budget_s=0.5)
        next(steps)
        next(steps)
        steps.close()
        self.assertEqual([self.status(item.handle)[0] for item in writer.inputs],
                         ["running"] * len(roles))
        self.assertEqual(self.state(), before)
        self.assertTrue(self.project.writable)

    def test_each_order_in_one_transaction(self) -> None:
        """RF-005-04 (plan §5.6.4, D-15): dos órdenes de varios ficheros se confirman cada una
        en una sola transacción (una por orden, sostenida entre sus pasos); un fallo en el
        último fichero de la segunda no deja nada de ella y la primera sigue intacta."""
        opened: list[int] = []
        real = self.project.write_transaction

        def counted() -> Any:
            opened.append(1)
            return real()

        first = self.order(("collar", "survey", "lithology"))
        with mock.patch.object(self.project, "write_transaction", side_effect=counted):
            progress, _ = _drive(first.steps(software=PYPROJ, clock=_Ticks(), budget_s=0.5))
        self.assertEqual(len(opened), 1)
        self.assertGreaterEqual(len(progress), 3)
        after_first = self.state()
        second = self.order(("assay_wide", "lithology_catalog", "element_catalog"))
        with mock.patch.object(store.SourceWriter, "_complete", autospec=True,
                               side_effect=_fail_on_third()), \
                self.assertRaises(RuntimeError):
            _drive(second.steps(software=PYPROJ))
        self.assertEqual(self.state(), after_first)
        third = self.order(("assay_wide", "lithology_catalog", "element_catalog"))
        opened.clear()
        with mock.patch.object(self.project, "write_transaction", side_effect=counted):
            _drive(third.steps(software=PYPROJ, clock=_Ticks(), budget_s=0.5))
        self.assertEqual(len(opened), 1)
        (count,) = self.query("SELECT count(*) FROM gb_input WHERE status = 'current'")
        self.assertEqual(count, (6,))

    def test_steps_keep_to_their_budget(self) -> None:
        """Plan §5.6.5 (RNF-005-06): cada paso termina en cuanto gasta su presupuesto, tras
        una sentencia de ``schema.INSERT_ROWS`` filas como mucho; con un presupuesto amplio,
        toda la orden en menos pasos."""
        found = self.file_input("assay_wide")
        rows = found["tables"]["assay"]
        many = [rows[index % len(rows)] for index in range(3 * schema.INSERT_ROWS + 7)]
        events: list[str] = []
        real = store.insert_rows

        def spy(*args: Any) -> None:
            events.append("sentencia")
            real(*args)

        writer = store.SourceWriter(self.project)
        writer.add(self.begin(), found["spec"], {"assay": many})
        steps = writer.steps(software=PYPROJ, clock=_Ticks(), budget_s=0.5)
        with mock.patch.object(store, "insert_rows", side_effect=spy):
            for _ in steps:
                events.append("paso")
        compact = "".join("s" if event == "sentencia" else "|" for event in events)
        self.assertNotIn("ss", compact)  # nunca dos sentencias en un paso
        self.assertGreaterEqual(compact.count("|"), 4)  # 1 507 filas: 4 sentencias
        (stored,) = self.query(f'SELECT count(*) FROM "{writer.inputs[0].datasets[0].locator}"')
        self.assertEqual(stored, (len(many),))

    def test_wrong_arguments(self) -> None:
        """RF-005-04, RF-008-17: errores del programa, sin escribir nada: una operación que no
        es una importación, un papel que no produce, unas filas de otro ancho, dos datos con
        el mismo nombre en una orden, una línea del informe de otra clase o una orden ya
        escrita."""
        found = self.file_input("collar")
        writer = store.SourceWriter(self.project)
        with self.assertRaises(ValueError):
            writer.add(self.begin(provenance.BUILD_BASE), found["spec"], found["tables"])
        with self.assertRaises(ValueError):
            writer.add(self.begin(), found["spec"], {"zone_interval": []})
        with self.assertRaises(ValueError):
            writer.add(self.begin(), found["spec"], {"collar": [(1, 2, 3)]})
        writer.add(self.begin(), found["spec"], found["tables"])
        other = self.file_input("survey")
        with self.assertRaises(errors.ValidationError) as caught:
            writer.add(self.begin(), other["spec"], other["tables"], name=found["spec"].name)
        self.assertEqual(caught.exception.code, "dh.dataset_name_taken")
        with self.assertRaises(ValueError):
            store.LogLine("collar", "otra")
        _drive(writer.steps(software=PYPROJ))
        with self.assertRaises(RuntimeError):
            writer.add(self.begin(), other["spec"], other["tables"])
        with self.assertRaises(RuntimeError):
            _drive(writer.steps(software=PYPROJ))


def _fail_on_third() -> Callable[..., Any]:
    """Un ``_complete`` que falla en la tercera entrada de la orden."""
    real = store.SourceWriter._complete
    calls = {"n": 0}

    def complete(self: Any, conn: Any, item: Any, software: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("fallo inyectado al completar la tercera entrada")
        return real(self, conn, item, software)

    return complete


# --- La base -------------------------------------------------------------------------------


def _entries(*, s01_azimuth: float = 0.0) -> list[Any]:
    """Las seis entradas de ``csv_basico`` leídas con el lector real (con ``s01_azimuth``
    grados más en las estaciones de S-01)."""
    tables = dh_sets.basico_tables()
    found = []
    for number, role in enumerate(SOURCE_ROLES, start=1):
        table = tables[role]
        rows = tabular.read_role(role, table, tabular.suggest_mapping(role, table.columns),
                                 _declaration())
        surveys = rows.surveys
        if role == "survey" and s01_azimuth:
            moved = surveys.azimuth.copy()
            moved[surveys.hole_name == "S-01"] += s01_azimuth
            surveys = surveys.take(np.arange(len(surveys)), azimuth=moved)
        found.append(build.SourceEntry(
            f"{number:08x}-0000-4000-8000-{number:012x}", _declaration(),
            collars=rows.collars, surveys=surveys, lithology=rows.lithology,
            assays=rows.assays, catalogs=rows.catalogs, label=role))
    return found


def _trace_rows(base: Any) -> list[tuple[Any, ...]]:
    """Las filas de ``dh_trace`` de la base (trazas por mínima curvatura cada 2 m) con la
    huella de la desviación de cada boca."""
    traces = desurvey.desurvey(base.dset)
    offsets, xyz = desurvey.polylines(traces, None, 2.0)
    hashes = base.columns["dh_collar"]["survey_sha256"]
    rows = []
    for hole in np.flatnonzero(traces.computed).tolist():
        last = traces.hole_start[hole + 1] - 1
        end = traces.xyz[last]
        rows.append((wkb.encode_geometry("LINESTRING", xyz[offsets[hole]:offsets[hole + 1]],
                                         25830, True),
                     hole + 1, str(traces.method), float(traces.md[last]), float(end[0]),
                     float(end[1]), float(end[2]), hashes[hole]))
    return rows


class BaseWriterTest(_StoreCase):
    def write_base(self, base: Any, **options: Any) -> tuple[Any, Any]:
        handle = self.begin(provenance.BUILD_BASE)
        writer = store.BaseWriter(self.project, handle)
        writer.base(base, **options)
        _, records = _drive(writer.steps(software=PYPROJ))
        return handle, {record.name: record for record in records}

    def test_base_rewritten_with_the_same_content_same_hash(self) -> None:
        """RF-005-01, RF-008-17, RF-008-26 (plan §5.6.1): las once tablas de la base de
        ``csv_basico`` (``build_base``) se escriben por pasos con su ``DatasetSpec`` y el hash
        de ``schema.table_digest`` (el que da el trabajo o, sin él, el registro): las bocas,
        capa ``POINT`` con Z en el CRS del proyecto, con los ``fid`` desde 1 y, de detalle,
        los sondeos nuevos; ``read_steps`` devuelve la base bit a bit. Reescrita con el mismo
        contenido (otra operación), los mismos ``fid``, el mismo hash y ningún cambio."""
        base = build.build_base(_entries(), FakeCrsService(), CRS, VERTICAL,
                                project_uid=self.project.uid)
        digests = {name: schema.table_digest(schema.LAYOUTS[name], base.rows(name), CRS)
                   for name in ("dh_collar", "dh_assay")}
        _, first = self.write_base(base, contents=digests)
        self.assertEqual(sorted(first), sorted(schema.BASE_TABLES))
        for name, record in first.items():
            with self.subTest(tabla=name):
                rows = base.rows(name)
                self.assertEqual(record.content_sha256, schema.table_digest(
                    schema.LAYOUTS[name], rows, CRS).content_sha256)
                self.assertEqual(self.stored_rows(name), rows)
                self.assertEqual(self.query(f'SELECT min(fid), max(fid) FROM "{name}"'),
                                 [(1 if rows else None, len(rows) if rows else None)])
                self.assertEqual(record.crs_epsg, 25830 if name == "dh_collar" else None)
        self.assertEqual(self.query(
            "SELECT geometry_type_name, srs_id, z FROM gpkg_geometry_columns WHERE "
            "table_name = 'dh_collar'"), [("POINT", 25830, 1)])
        (detail,) = self.query("SELECT c.detail FROM gb_dataset_change c JOIN gb_dataset d "
                               "ON d.uid = c.dataset_uid WHERE d.name = 'dh_collar'")
        self.assertEqual(detail, ('{"holes":["C-01","S-01","S-02","S-03","S-04","S-12"]}',))
        with self.project.read() as conn:
            _, dset = _drive(store.read_steps(conn, clock=_Ticks(), budget_s=0.5))
            self.assertEqual(store.existing_holes(conn), HOLES)
        for name in ("collars", "surveys", "lithology", "assays", "zones", "structures"):
            back, given = getattr(dset, name), getattr(base.dset, name)
            for item in fields(given):
                with self.subTest(tabla=name, columna=item.name):
                    self.assertEqual(_bits(getattr(back, item.name)),
                                     _bits(getattr(given, item.name)))
        self.assertEqual(dset.catalogs, base.dset.catalogs)
        with self.project.read() as conn:  # RF-005-10 (T25): los de una importación
            self.assertEqual(store.read_catalogs(conn), base.dset.catalogs)
        self.assertEqual((dset.crs, dset.vertical), (CRS, VERTICAL))
        changes = self.query("SELECT count(*) FROM gb_dataset_change")
        again = build.build_base(_entries(), FakeCrsService(), CRS, VERTICAL,
                                 project_uid=self.project.uid)
        _, second = self.write_base(again)
        for name, record in second.items():
            self.assertEqual(record.content_sha256, first[name].content_sha256, name)
            self.assertEqual(self.stored_rows(name), base.rows(name))
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset_change"), changes)
        self.assertEqual(self.query("SELECT seq FROM sqlite_sequence WHERE name = 'dh_collar'"),
                         [(len(HOLES),)])

    def test_stale_holes_by_survey_hash(self) -> None:
        """RF-005-22 (plan §5.6.6, D-21): con las trazas hechas, ningún sondeo obsoleto; la base
        reconstruida con otras estaciones de S-01 deja obsoleta solo su traza
        (``stale_holes``) y lo anota en el detalle de ``dh_collar``."""
        base = build.build_base(_entries(), FakeCrsService(), CRS, VERTICAL,
                                project_uid=self.project.uid)
        self.write_base(base)
        writer = store.BaseWriter(self.project, self.begin(provenance.DESURVEY))
        writer.table("dh_trace", _trace_rows(base))
        _, (trace,) = _drive(writer.steps())
        self.assertEqual((trace.name, trace.kind, trace.crs_epsg), ("dh_trace", "vector", 25830))
        with self.project.read() as conn:
            self.assertEqual(store.stale_holes(conn), ())
        moved = build.build_base(_entries(s01_azimuth=1.0), FakeCrsService(), CRS, VERTICAL,
                                 project_uid=self.project.uid)
        self.write_base(moved)
        with self.project.read() as conn:
            self.assertEqual(store.stale_holes(conn), ("S-01",))
        details = self.query("SELECT c.detail FROM gb_dataset_change c JOIN gb_dataset d ON "
                             "d.uid = c.dataset_uid WHERE d.name = 'dh_collar' ORDER BY c.fid")
        self.assertEqual(details[-1], ('{"holes":["S-01"]}',))

    def test_failure_leaves_the_previous_base(self) -> None:
        """RF-005-04, RF-008-19 (plan §5.6.5, D-14): un fallo al reescribir la base la deja
        como estaba y la operación «fallida» con su motivo; una tabla con el nombre de una de
        la base que no es la de su dato no se toca (``dh.table_exists``); y la operación
        escribe todas sus tablas."""
        base = build.build_base(_entries(), FakeCrsService(), CRS, VERTICAL,
                                project_uid=self.project.uid)
        self.write_base(base)
        before = self.state()
        rows = {name: self.stored_rows(name) for name in schema.BASE_TABLES}
        handle = self.begin(provenance.BUILD_BASE)
        writer = store.BaseWriter(self.project, handle)
        writer.base(build.build_base(_entries(s01_azimuth=2.0), FakeCrsService(), CRS,
                                     VERTICAL, project_uid=self.project.uid))
        real = store.insert_rows
        calls = {"n": 0}

        def failing(*args: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 5:
                raise RuntimeError("fallo inyectado en la base")
            real(*args)

        with mock.patch.object(store, "insert_rows", side_effect=failing), \
                self.assertRaises(RuntimeError):
            _drive(writer.steps(software=PYPROJ, clock=_Ticks(), budget_s=0.5))
        self.assertEqual(self.status(handle)[0], "failed")
        self.assertEqual(self.state(), before)
        self.assertEqual({name: self.stored_rows(name) for name in schema.BASE_TABLES}, rows)
        self.assertTrue(self.project.writable)
        with self.project.write_transaction() as conn:
            schema.create_table(conn, schema.LAYOUTS["dh_validation_issue"],
                                "dh_validation_issue", None)
        writer = store.BaseWriter(self.project, self.begin(provenance.VALIDATE))
        writer.table("dh_validation_issue", [])
        with self.assertRaises(errors.ValidationError) as caught:
            _drive(writer.steps())
        self.assertEqual(caught.exception.code, "dh.table_exists")
        writer = store.BaseWriter(self.project, self.begin(provenance.BUILD_BASE))
        writer.table("dh_collar", base.rows("dh_collar"))
        with self.assertRaises(ValueError):
            _drive(writer.steps(software=PYPROJ))


if __name__ == "__main__":
    unittest.main()
