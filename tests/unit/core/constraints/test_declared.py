# SPDX-License-Identifier: GPL-3.0-or-later
"""La restricción declarada por una entidad: su tabla de versión (spec 015, T16; HU-015-1;
RF-012-29, RF-012-02, RF-015-10; plan 015 §5.1, §5.2.3 y P-8; D-23).

``core.constraints.declared`` guarda las restricciones que declaran las entidades de diseño en
**una tabla de la versión** (``des_decl_<vNN>``: una capa de polígonos ``MULTIPOLYGON``, **no
editable a mano**, RF-008-56): de cada una, su código ``dec__<código de la entidad>`` (único en las
tres capas del proyecto por su prefijo), su tipo (uno de los once), su nombre, su motivo, su
decisor, la fecha **de la decisión** (nunca ``now``), la entidad de origen, el contorno de las
celdas de la entidad (absoluto, float64, bit a bit), el resguardo hacia fuera y si está activa
—columnas de la tabla, no parámetros del almacén (P-8)— y un ``uid`` **determinista** derivado de
la entidad y de la versión, de modo que escribir lo mismo dos veces da la misma tabla (y el mismo
hash). La prioridad es una constante estable.
"""

from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
model = import_geoblender("core.constraints.model")
checks = import_geoblender("core.constraints.checks")
messages = import_geoblender("core.constraints.messages")
store = import_geoblender("core.constraints.store")
declared = import_geoblender("core.constraints.declared")
builtin = import_geoblender("core.content.builtin")
datasets = import_geoblender("core.datasets")
dataset_model = import_geoblender("core.datasets.model")
encoder = import_geoblender("core.content.encoder")

T = model.ConstraintType
G = model.GeometryKind
SRS = fx.SRS_ID
VERSION_UID = "v" * 32
TABLE = "des_decl_v01"
# Coordenadas con decimales que float32 perdería.
ODD = (0.123456789012, 0.987654321098)


def _ring(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    ring = fx.rectangle(left, bottom, right, top) + np.array(ODD)
    ring[-1] = ring[0]
    return ring


def _parts():
    """Dos partes: un cuadrado con un hueco y otro cuadrado."""
    return ((_ring(0, 0, 40, 40), _ring(10, 10, 20, 20)[::-1].copy()), (_ring(60, 0, 80, 20),))


def _row(entity: str = "PLT-001", name: str = "P1", *, parts=None, **changes):
    fields = dict(
        uid=declared.declared_uid(VERSION_UID, entity), code=declared.declared_code(entity),
        ctype=T.NO_FILL, name=name, reason=f"declarada por la plataforma {name}",
        decided_by="Samuel (IMGA)", decided_on=date(2026, 11, 14), entity_code=entity,
        entity_name=name, parts=_parts() if parts is None else parts, buffer_out_m=4.0,
        active=True)
    fields.update(changes)
    return declared.DeclaredConstraint(**fields)


def _new(path: Path):
    db = gpkg.GpkgConnection.open_write(path, create=True)
    with db.transaction() as conn:
        base.create_base(conn, fx.CRS)
    return db


@contextmanager
def _read(db):
    """La conexión de lectura de ``db`` (ve lo confirmado)."""
    yield db.connection


def _dump(conn: sqlite3.Connection, table: str = TABLE) -> list[tuple]:
    return conn.execute(f'SELECT * FROM "{table}" ORDER BY fid').fetchall()


def _digest(conn: sqlite3.Connection, table: str = TABLE) -> str:
    """El hash de contenido (``core.gpkg_layer@1``) de la capa, como lo calcula el proyecto."""
    request = builtin.GPKG_LAYER.request("vector", dataset_model.DATASET_DECLARATIONS,
                                         {"main": Path("digest")}, {"layer": table},
                                         normalizer=encoder.NORMALIZER)
    for _step in builtin.layer_steps(conn, request):
        pass
    return request.hasher.digest().content_sha256


class CodeTest(unittest.TestCase):
    """RF-012-29, D-22: el código ``dec__<entidad>`` y el ``uid`` determinista."""

    def test_code_is_the_prefix_and_the_entity(self) -> None:
        """RF-012-29: ``dec__<código de la entidad>`` (en minúsculas y con «_»); un código que no es de
        una entidad (``PLT-001``: letras mayúsculas, un guion y al menos tres cifras) es un error; y
        ``declared_entity`` es su inversa."""
        self.assertEqual(declared.DECLARED_PREFIX, "dec__")
        self.assertEqual(declared.declared_code("PLT-001"), "dec__plt_001")
        self.assertEqual(declared.declared_code("BUT-1204"), "dec__but_1204")
        for entity in ("plt-001", "PLT-1", "PLT001", "dec__plt_001", "", " PLT-001", "PLT-001 "):
            with self.subTest(entity=entity), self.assertRaises(ValueError):
                declared.declared_code(entity)
        with self.assertRaises(TypeError):
            declared.declared_code(None)
        self.assertTrue(declared.is_declared_code("dec__plt_001"))
        for code in ("PLT-001", "dec-plt-001", "DEC-PLT-001", "dec__plt_1", "dec_plt_001", "dec__PLT_001",
                     "", "dec__", None, 5):
            with self.subTest(code=code):
                self.assertFalse(declared.is_declared_code(code))
        for entity in ("PLT-001", "BUT-1204"):
            self.assertEqual(declared.declared_entity(declared.declared_code(entity)), entity)
        for code in ("PLT-001", "dec_plt_001", "r_1", ""):
            with self.subTest(code=code), self.assertRaises(ValueError):
                declared.declared_entity(code)
        with self.assertRaises(TypeError):
            declared.declared_entity(None)

    def test_code_is_a_valid_code_of_the_012(self) -> None:
        """RF-012-29, RF-012-02, D-22 (el hallazgo de la T16: ``DEC-PLT-001`` no lo era): ``dec__plt_001``
        es un código de la 012 —``is_code``, ``Constraint.param_key`` y ``params.param_key`` lo aceptan y
        ``checks.incomplete`` no lo trata como inválido—, con lo que la compilación puede inyectar bajo él
        el resguardo y «activa» de la tabla (P-8, T18)."""
        params = import_geoblender("core.constraints.params")
        code = declared.declared_code("PLT-001")
        self.assertTrue(model.is_code(code))
        self.assertEqual(params.param_key(code, model.ConstraintParam.BUFFER_OUT),
                         "core.constraint.dec__plt_001.buffer_out_m")
        found = _row().as_constraint()
        self.assertEqual(found.param_key(model.ConstraintParam.ACTIVE),
                         "core.constraint.dec__plt_001.active")
        problems = checks.incomplete((found,), {})
        self.assertNotIn("core.constraint_code_invalid", {item.problem for item in problems})

    def test_code_never_collides_with_a_project_code(self) -> None:
        """RF-012-29, D-22: el doble guion bajo de ``dec__`` no lo genera ``constraint_code`` desde
        ningún nombre (junta lo que no son letras ni cifras en **un** «_»: ``DEC-PLT-001`` da
        ``dec_plt_001``), así que un código del proyecto nunca es el de una declarada (el precedente
        es ``perimeter__``, ADR-0029); y no la reconoce ``is_declared_code``."""
        code = declared.declared_code("PLT-001")
        for name in ("DEC-PLT-001", "dec-plt-001", "dec__plt_001", "dec  plt  001", "Plataforma P1",
                     "DEC", "PLT-001", ""):
            made = model.constraint_code(name, {code, "dec_plt_001"})
            with self.subTest(name=name):
                self.assertTrue(model.is_code(made))
                self.assertNotEqual(made, code)
                self.assertNotIn("__", made)
                self.assertFalse(declared.is_declared_code(made))

    def test_uid_is_deterministic_from_the_entity_and_the_version(self) -> None:
        """RF-012-29, A8: el ``uid`` depende solo del código de la entidad y de la versión (el
        mismo para los mismos, otro si cambia uno), de 32 cifras hexadecimales como los de
        ``core_constraint_*``: recalcular la entidad no cambia el hash de la tabla."""
        uid = declared.declared_uid(VERSION_UID, "PLT-001")
        self.assertRegex(uid, r"^[0-9a-f]{32}$")
        self.assertEqual(uid, declared.declared_uid(VERSION_UID, "PLT-001"))
        self.assertNotEqual(uid, declared.declared_uid(VERSION_UID, "PLT-002"))
        self.assertNotEqual(uid, declared.declared_uid("w" * 32, "PLT-001"))
        with self.assertRaises(ValueError):
            declared.declared_uid(VERSION_UID, "plt-001")
        with self.assertRaises(ValueError):
            declared.declared_uid("", "PLT-001")


class ModelTest(unittest.TestCase):
    """RF-012-29, RF-012-02: lo que es una restricción declarada y su origen «entidad»."""

    def test_the_row_is_checked(self) -> None:
        """RF-012-02, RF-012-29: una restricción declarada lleva su código ``dec__<entidad>``, uno de
        los once tipos, nombre, motivo, decisor y entidad con algo escrito, una fecha, un resguardo
        finito ≥ 0 (sin valor por defecto: D-19) y una geometría de polígonos."""
        found = _row()
        self.assertEqual((found.code, found.entity_code, found.ctype), ("dec__plt_001", "PLT-001",
                                                                       T.NO_FILL))
        self.assertEqual((found.buffer_out_m, found.active, found.fid, found.layer), (4.0, True,
                                                                                    0, ""))
        for field, value in (
                ("code", "dec__plt_002"), ("code", "plt_001"), ("entity_code", "plt-001"),
                ("ctype", "rareza"), ("name", "  "), ("reason", ""), ("decided_by", " "),
                ("entity_name", ""), ("decided_on", "2026-11-14"), ("buffer_out_m", -1.0),
                ("buffer_out_m", float("nan")), ("buffer_out_m", float("inf")),
                ("buffer_out_m", None), ("buffer_out_m", True), ("active", 1), ("active", None),
                ("parts", ()), ("uid", "")):
            with self.subTest(field=field, value=value), self.assertRaises((ValueError, TypeError)):
                _row(**{field: value})
        with self.assertRaises(TypeError):
            declared.DeclaredConstraint(
                uid="a" * 32, code="dec__plt_001", ctype=T.NO_FILL, name="P1", reason="r",
                decided_by="d", decided_on=date(2026, 11, 14), entity_code="PLT-001",
                entity_name="P1", parts=_parts())  # sin resguardo: no hay valor por defecto

    def test_every_one_of_the_eleven_types_is_accepted(self) -> None:
        """RF-012-29: «con uno de los once tipos»: ninguno se rechaza y se leen por su valor."""
        for ctype in T:
            with self.subTest(ctype=ctype.value):
                self.assertEqual(_row(ctype=ctype.value).ctype, ctype)

    def test_the_priority_is_one_stable_constant(self) -> None:
        """RF-012-29, plan 015 §5.4 A8: la prioridad de una declarada no la da nadie: es la
        constante :data:`~core.constraints.declared.DECLARED_PRIORITY` (solo ordena informes y
        leyenda, D-13 de la 012; una prohibición no la quita ninguna prioridad)."""
        self.assertIsInstance(declared.DECLARED_PRIORITY, int)
        self.assertEqual(_row().priority, declared.DECLARED_PRIORITY)
        self.assertEqual(_row("PLT-007", "otra").priority, declared.DECLARED_PRIORITY)
        self.assertFalse(hasattr(declared.DeclaredConstraint, "__dataclass_fields__")
                         and "priority" in declared.DeclaredConstraint.__dataclass_fields__)

    def test_as_constraint_carries_the_origin_entity(self) -> None:
        """RF-012-29, RF-012-18: la restricción de la 012 que sale de una declarada lleva la
        entidad como origen (``entity_code``, ``entity_name``), su capa de versión, su geometría
        absoluta y la prioridad constante; es un polígono, con el motivo y el decisor de la
        entidad."""
        found = _row(fid=3, layer=TABLE).as_constraint()
        self.assertIsInstance(found, model.Constraint)
        self.assertTrue(found.declared)
        self.assertEqual((found.entity_code, found.entity_name), ("PLT-001", "P1"))
        self.assertEqual((found.code, found.layer, found.fid, found.kind, found.priority),
                         ("dec__plt_001", TABLE, 3, G.POLYGON, declared.DECLARED_PRIORITY))
        self.assertEqual((found.reason, found.decided_by, found.decided_on, found.ctype),
                         ("declarada por la plataforma P1", "Samuel (IMGA)", date(2026, 11, 14),
                          T.NO_FILL))
        self.assertEqual((found.decision_uid, found.intention_uid, found.source_input,
                          found.source_fid), (None, None, None, None))
        for mine, theirs in zip(found.parts, _row().parts, strict=True):
            for got, expected in zip(mine, theirs, strict=True):
                self.assertEqual(got.tobytes(), expected.tobytes())
                self.assertFalse(got.flags.writeable)
        self.assertEqual(found.shown_name(), "P1")

    def test_constraint_keeps_working_without_the_origin(self) -> None:
        """RF-012-01 (compatibilidad): una restricción del proyecto se construye como siempre
        —los catorce campos, ``layer`` y ``fid``— y no es declarada; los campos de la entidad son
        opcionales y van al final."""
        plain = model.Constraint(
            "u" * 32, "balsa", "Balsa", T.NO_FILL, G.POLYGON, ((_ring(0, 0, 10, 10),),), 0, "r",
            "d", date(2026, 10, 28), None, None, None, None, "core_constraint_polygon", 4)
        self.assertFalse(plain.declared)
        self.assertEqual((plain.entity_code, plain.entity_name), (None, None))
        self.assertEqual(plain.param_key("buffer_out_m"), "core.constraint.balsa.buffer_out_m")
        fields = [name for name in model.Constraint.__dataclass_fields__]
        self.assertEqual(fields[-4:], ["layer", "fid", "entity_code", "entity_name"])


class TableTest(unittest.TestCase):
    """RF-012-29, RF-008-56: la tabla de la versión, su escritura y su lectura."""

    def test_the_table_is_a_non_editable_polygon_layer(self) -> None:
        """RF-012-29, RF-008-56: ``des_decl_<vNN>`` es una capa ``MULTIPOLYGON`` (2D, CRS del
        proyecto) registrada en ``gpkg_contents``, con los títulos en español de sus columnas, y
        su dato (``declared_dataset_spec``) es de ``des``, un ``vector`` del GeoPackage leído con
        ``core.gpkg_layer@1``, con el papel ``constraints_declared`` y **no editable en QGIS**."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                declared.create_declared_table(conn, TABLE, SRS)
                declared.create_declared_table(conn, TABLE, SRS)  # otra vez: no hace nada
            with _read(db) as conn:
                self.assertEqual(
                    conn.execute("SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = ?",
                                 (TABLE,)).fetchall(), [("features", SRS)])
                self.assertEqual(
                    conn.execute("SELECT geometry_type_name, z, m, srs_id FROM "
                                 "gpkg_geometry_columns WHERE table_name = ?", (TABLE,)).fetchall(),
                    [("MULTIPOLYGON", 0, 0, SRS)])
                columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{TABLE}")')]
                self.assertEqual(columns, ["fid", "geom", *declared.COLUMN_NAMES])
                titles = dict(conn.execute("SELECT column_name, name FROM gpkg_data_columns WHERE "
                                           "table_name = ?", (TABLE,)).fetchall())
                self.assertEqual(sorted(titles), sorted(declared.COLUMN_NAMES))
                self.assertEqual(titles["code"], "Código")
                self.assertEqual(titles["entity_name"], "Entidad")
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(read := declared.read_declared(conn, TABLE), ())
                self.assertEqual(read, ())
        spec = declared.declared_dataset_spec("V01", crs_epsg=SRS)
        self.assertEqual((spec.name, spec.module, spec.kind, spec.store, spec.locator),
                         ("des_decl", "des", "vector", dataset_model.Store.GPKG, TABLE))
        self.assertEqual((spec.reader, spec.role, spec.crs_epsg, spec.qgis_editable),
                         ("core.gpkg_layer@1", "constraints_declared", SRS, False))
        self.assertEqual(declared.declared_table("V10"), "des_decl_v10")
        self.assertEqual(declared.declared_dataset_spec("V10").locator, "des_decl_v10")
        # Las tres capas de restricciones del proyecto sí son editables; la declarada, no.
        editable = {spec.name for spec in store.dataset_specs(crs_epsg=SRS) if spec.qgis_editable}
        self.assertEqual(editable, set(store.CONSTRAINT_LAYERS.values()))
        self.assertNotIn(spec.name, editable)

    def test_write_and_read_round_trip_bit_by_bit(self) -> None:
        """RF-012-29, RF-012-02: las filas escritas se leen con todos sus campos y su geometría
        **absoluta en float64 bit a bit** (partes con hueco), por orden de código; el resguardo y
        «activa» son columnas de la tabla; ninguna se guarda en las tres capas del proyecto."""
        rows = [_row("PLT-002", "P2", buffer_out_m=0.0, active=False, ctype=T.NO_CUT,
                     decided_on=date(2026, 11, 2)), _row("PLT-001", "P1")]
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                store.create_tables(conn, SRS)
                fids = declared.write_declared(conn, TABLE, rows, srs_id=SRS)
            self.assertEqual(fids, (1, 2))
            with _read(db) as conn:
                found = declared.read_declared(conn, TABLE)
                self.assertEqual(store.read_constraints(conn), ())  # nada en las tres capas
            self.assertEqual([item.code for item in found], ["dec__plt_001", "dec__plt_002"])
            first, second = found
            self.assertEqual((first.fid, first.layer, second.fid), (1, TABLE, 2))
            self.assertEqual((first.name, first.reason, first.decided_by, first.decided_on),
                             ("P1", "declarada por la plataforma P1", "Samuel (IMGA)",
                              date(2026, 11, 14)))
            self.assertEqual((first.ctype, first.buffer_out_m, first.active, first.entity_code,
                              first.entity_name, first.uid),
                             (T.NO_FILL, 4.0, True, "PLT-001", "P1",
                              declared.declared_uid(VERSION_UID, "PLT-001")))
            self.assertEqual((second.ctype, second.buffer_out_m, second.active, second.decided_on),
                             (T.NO_CUT, 0.0, False, date(2026, 11, 2)))
            for item in found:
                self.assertEqual(len(item.parts), 2)
                self.assertEqual([len(part) for part in item.parts], [2, 1])
                for mine, theirs in zip(item.parts, _parts(), strict=True):
                    for got, expected in zip(mine, theirs, strict=True):
                        self.assertEqual(got.dtype, np.float64)
                        self.assertEqual(got.tobytes(), expected.tobytes())

    def test_writing_again_replaces_the_table_with_the_same_bytes(self) -> None:
        """RF-015-10, A8: escribir lo mismo otra vez deja **la misma tabla** (mismas filas, mismos
        ``fid``, el mismo hash de contenido): reescribir la tabla entera desde las entidades no
        cambia el hash si nada cambió, y lo que ya no se declara desaparece."""
        rows = [_row("PLT-001", "P1"), _row("PLT-002", "P2", ctype=T.NO_CUT)]
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                declared.write_declared(conn, TABLE, rows, srs_id=SRS)
            with _read(db) as conn:
                first, digest = _dump(conn), _digest(conn)
            with db.transaction() as conn:
                declared.write_declared(conn, TABLE, list(reversed(rows)), srs_id=SRS)
            with _read(db) as conn:
                self.assertEqual(_dump(conn), first)
                self.assertEqual(_digest(conn), digest)
            with db.transaction() as conn:  # una entidad que ya no protege
                declared.write_declared(conn, TABLE, rows[:1], srs_id=SRS)
            with _read(db) as conn:
                self.assertEqual([item.code for item in declared.read_declared(conn, TABLE)],
                                 ["dec__plt_001"])
                self.assertEqual(_digest(conn) != digest, True)
            with db.transaction() as conn:  # y otra vez las dos: vuelve el mismo contenido
                declared.write_declared(conn, TABLE, rows, srs_id=SRS)
            with _read(db) as conn:
                self.assertEqual(_dump(conn), first)
                self.assertEqual(_digest(conn), digest)
            with db.transaction() as conn:  # ninguna entidad protege: la tabla queda vacía
                self.assertEqual(declared.write_declared(conn, TABLE, [], srs_id=SRS), ())
            with _read(db) as conn:
                self.assertEqual(declared.read_declared(conn, TABLE), ())
                self.assertEqual(conn.execute(f'SELECT count(*) FROM "{TABLE}"').fetchone()[0], 0)

    def test_the_hash_does_not_depend_on_the_name_of_the_table(self) -> None:
        """RF-015-10, RF-009-11 (T17): las mismas filas en tablas con otro nombre (la de V01 del proyecto, la
        «V01» con que la reproducción escribe la suya, la de otra versión) dan el mismo hash de contenido:
        reproducir una declaración congelada compara con el que registró la operación."""
        rows = [_row("PLT-001", "P1"), _row("PLT-002", "P2")]
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                for table in (TABLE, "des_decl_v02", "des_decl_v10"):
                    declared.write_declared(conn, table, rows, srs_id=SRS)
            with _read(db) as conn:
                found = {_digest(conn, table) for table in (TABLE, "des_decl_v02", "des_decl_v10")}
        self.assertEqual(len(found), 1)

    def test_a_rewrite_rolls_back_with_its_transaction(self) -> None:
        """RF-012-29: ``write_declared`` no confirma nada: si la transacción se deshace, queda la
        tabla de antes."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                declared.write_declared(conn, TABLE, [_row()], srs_id=SRS)
            with self.assertRaises(RuntimeError), db.transaction() as conn:
                declared.write_declared(conn, TABLE, [_row("PLT-002", "P2")], srs_id=SRS)
                raise RuntimeError("deshacer")
            with _read(db) as conn:
                self.assertEqual([item.code for item in declared.read_declared(conn, TABLE)],
                                 ["dec__plt_001"])

    def test_rows_that_cannot_be_written_are_rejected(self) -> None:
        """RF-012-29, D-22: dos filas con el mismo código o el mismo ``uid`` se rechazan sin
        escribir nada; un código que ya usa una restricción de las tres capas del proyecto, también
        (``core.constraint_code_taken``); sin la tabla y sin SRS, o con otro SRS que el de la tabla,
        un error del programa."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                store.create_tables(conn, SRS)
                declared.write_declared(conn, TABLE, [_row()], srs_id=SRS)
                with self.assertRaises(ValueError):
                    declared.write_declared(conn, TABLE, [_row(), _row()], srs_id=SRS)
                with self.assertRaises(ValueError):
                    declared.write_declared(conn, "des_decl_v02", [_row()])
                with self.assertRaises(ValueError):
                    declared.write_declared(conn, TABLE, [_row()], srs_id=4326)
                with self.assertRaises(ValueError):
                    declared.write_declared(conn, "no es una tabla", [_row()], srs_id=SRS)
                # Un código con el aspecto de una declarada en una de las tres capas (la escribió
                # alguien a mano): no se pisa.
                clash = cp._constraint("dec__plt_009", "Intrusa", T.NO_FILL, G.POLYGON,
                                       ((_ring(0, 0, 10, 10),),))
                store.write_constraints(conn, [clash], srs_id=SRS)
                with self.assertRaises(messages.ConstraintError) as caught:
                    declared.write_declared(conn, TABLE, [_row("PLT-009", "P9")], srs_id=SRS)
                self.assertEqual(caught.exception.code, "core.constraint_code_taken")
            with _read(db) as conn:  # lo anterior sigue como estaba
                self.assertEqual([item.code for item in declared.read_declared(conn, TABLE)],
                                 ["dec__plt_001"])


class CodesTest(unittest.TestCase):
    """RF-012-29, D-22: el código de una declarada no choca con los de las tres capas."""

    def test_no_clash_with_the_three_layers_in_the_checks_of_the_012(self) -> None:
        """RF-012-29: sumadas a las del proyecto (``tests.support.constraints_project``: las cinco
        en las tres capas), ninguna restricción declarada repite el código de otra
        (``core.constraint_code_repeated`` no sale), y los códigos que usan las tres capas
        (``taken_codes``) no incluyen ninguno ``dec__``."""
        project = cp.constraints()
        resolved = cp.project_values()
        mine = _row().as_constraint()
        problems = checks.incomplete((*project, mine), resolved)
        self.assertNotIn("core.constraint_code_repeated", {item.problem for item in problems})
        self.assertEqual([item.problem for item in problems if item.code != mine.code], [])
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                store.create_tables(conn, SRS)
                store.write_constraints(conn, project, srs_id=SRS)
                declared.write_declared(conn, TABLE, [_row()], srs_id=SRS)
            with _read(db) as conn:
                taken = store.taken_codes(conn)
                self.assertEqual(len(taken), 5)
                self.assertFalse(any(declared.is_declared_code(code) for code in taken))
                self.assertNotIn(mine.code, taken)
                self.assertTrue(taken.isdisjoint({item.code for item in
                                                  declared.read_declared(conn, TABLE)}))


if __name__ == "__main__":
    unittest.main()
