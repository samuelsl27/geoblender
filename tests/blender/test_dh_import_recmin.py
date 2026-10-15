# SPDX-License-Identifier: GPL-3.0-or-later
"""Importar una base de RecMin en Blender (spec 005, T26; HU-005-2; plan 005 §5.3.1, §5.6.4 y
§5.6.5; ADR-0018).

Proyectos sintéticos de esquema 2 (EPSG:25830 + EPSG:5782) abiertos en la sesión, como los de
``test_dh_import_tabular`` (``DrillholeImportCase``), con una base de RecMin en
``entregas/``, fuera de ellos. ``geoblender.dh_import_recmin_mdb`` es un operador de la
procedencia de la 008: la base entera es **una** entrada (D-15), con su operación
``dh.import_recmin`` y su lectura (``dh_import_recmin``); al terminar espera en «Importación
pendiente» si hay algo que decidir (códigos nuevos, sondeos que ya están, una versión de
esquema que no es 11 ni 12) y, aplicada, se incorpora por pasos y le siguen la base y su
validación, como las tablas (T25).

El motor de Access no se usa: la base de ``entregas/`` solo tiene la cabecera de una base ACE
y el extractor es uno falso que da las tablas de ``tests/data/dh/recmin/recmin_v12.sql`` (las
de la extensión habilitada) o el error de un equipo sin motor; la lectura, que en Blender va
siempre en proceso aparte con el ``powershell.exe`` hijo, va aquí en el hilo con la misma
función (el extractor real y el proceso aparte los prueban ``test_mdb_reader_contract`` y
``test_dh_workers``): el presupuesto de ``tools/check.py``.

- RF-005-13, RF-005-03, RF-005-12, RF-005-10: la base se importa con todas sus tablas, su
  informe en ``dh_import_log`` por tabla de RecMin con las cifras del lector, su entrada (el
  CRS y el datum declarados, su hash, su original) y la base de sondeos con sus cuatro
  sondeos y los colores de su catálogo; el extractor solo abre la copia del trabajo y la
  carpeta de la base no cambia.
- RF-005-15, RF-005-11: con otra versión de esquema, la importación espera la confirmación
  antes de leer nada más; confirmada, se lee otra vez y, con los sondeos que ya están, uno se
  conserva y los demás se sustituyen, contados por tabla de RecMin.
- RF-005-15, RF-005-14, RF-005-07: con su fichero de bloqueo junto a la base, nada empieza sin
  confirmarlo (el diálogo lo avisa); sin motor, la operación falla con el formato detectado y
  qué instalar, sin escribir nada; sin el CRS, el datum o la referencia del azimut, nada
  empieza.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import json
import unittest
from pathlib import Path
from typing import Any

import bpy

from tests.blender.test_dh_import_tabular import DrillholeImportCase, _folder_state, _module
from tests.support import recmin
from tests.support.fake_layout import draw

V12 = recmin.RECMIN_DIR / "recmin_v12.sql"
IMPORT_RECMIN = "geoblender.dh_import_recmin_mdb"
BASE = "base_recmin.mdb"
DECLARED = {"crs": "EPSG:25830", "vertical": "PROJECT", "azimuth_ref": "GRID",
            "decimal_mark": "POINT"}
DIALOG = {**DECLARED, "declination_deg": "", "units": "", "sentinels": "",
          "negative_is_below_dl": False, "density_kind": "ADOPTADO", "accept_locked": False,
          "accept_schema": False, "received_at": "", "received_from": "", "reason": "",
          "wizard": True, "stage": "NEW", "pending": ""}
HOLES = ("R-01", "R-02", "R-03", "R-04")
ELEMENT_COLUMNS = ("ELEMENTO ",)


def _ace_base(path: Path) -> Path:
    """Un fichero con la cabecera de una base ACE (byte 0x14 = 2), sin datos: el extractor
    falso no lo abre."""
    data = bytearray(4096)
    data[0:4] = b"\x00\x01\x00\x00"
    data[4:19] = b"Standard ACE DB"
    data[0x14] = 2
    path.write_bytes(bytes(data))
    return path


class _FakeExtractor:
    """Un ``MdbExtractor`` sin motor: anota qué copia abre, deja un crudo en ``out_dir`` y da
    las tablas que se le dan o lanza ``error``."""

    def __init__(self, tables: dict[str, Any], *, error: Exception | None = None) -> None:
        self.tables = tables
        self.error = error
        self.opened: list[Path] = []

    def probe(self, path: Path) -> Any:  # pragma: no cover - el trabajo no lo usa
        raise AssertionError("el trabajo no sondea los motores")

    def extract(self, path: Path, out_dir: Path, on_progress: Any, cancelled: Any) -> list:
        self.opened.append(Path(path))
        out_dir.mkdir(parents=True)
        (out_dir / "schema.json").write_text("{}", encoding="utf-8")
        on_progress(0.5, "Leyendo")
        if self.error is not None:
            raise self.error
        on_progress(1.0, "Leída")
        return list(self.tables.values())


def _hole_records(script: Path) -> dict[str, dict[str, int]]:
    """Los registros de cada sondeo en cada tabla de RecMin del guion ``script`` (por su
    ``IDSONDEO``), contados sin el lector: uno por fila y, en las tablas de muestras, uno por
    valor de elemento."""
    tables = recmin.parse_sql(script)
    names = {row["IDSONDEO"]: row["SONDEO"] for name, table in tables.items()
             if name.casefold() == "sondeos" for row in table.rows}
    found: dict[str, dict[str, int]] = {}
    for name, table in tables.items():
        columns = [column.name for column in table.columns]
        if "IDSONDEO" not in columns:
            continue
        elements = [column for column in columns if column.startswith(ELEMENT_COLUMNS)]
        for row in table.rows:
            hole = names.get(row["IDSONDEO"])
            if hole is None:
                continue
            count = sum(row.get(column) is not None for column in elements) if elements else 1
            per = found.setdefault(name, {})
            per[hole] = per.get(hole, 0) + count
    return found


class RecminImportTest(DrillholeImportCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ports = _module("interop.ports")
        cls.dh_content = _module("interop.dh_content")
        cls.reader = _module("interop.recmin.drillholes")
        cls.model = _module("drillholes.model")
        cls.georef = _module("core.georef")
        cls.tables = recmin.raw_tables(V12, ports=cls.ports)

    def setUp(self) -> None:
        super().setUp()
        self.base = _ace_base(self.sources / BASE)
        self.extractor = self.use(_FakeExtractor(self.tables))

    def read_in_thread(self) -> None:
        """Las dos lecturas en el hilo, con la función de su proceso aparte."""
        super().read_in_thread()
        reading = _module("interop.dh_jobs")
        info = self.catalog.WORKERS[self.dh_jobs.IMPORT_RECMIN]
        fast = dataclasses.replace(info, policy="auto", estimate_s=lambda params: 0.01,
                                   run=reading.run_import_recmin)
        self.catalog.unregister_worker(info.name)
        self.catalog.register_worker(fast)

        def restore() -> None:
            if self.catalog.WORKERS.get(info.name) is fast:
                self.catalog.unregister_worker(info.name)
                self.catalog.register_worker(info)

        self.addCleanup(restore)

    # --- Ayudas -----------------------------------------------------------------------------

    def use(self, extractor: _FakeExtractor) -> _FakeExtractor:
        """El extractor de la lectura de las bases mientras dura la prueba."""
        previous = self.dh_content.use_mdb_extractor(extractor)
        self.addCleanup(self.dh_content.use_mdb_extractor, previous)
        return extractor

    def with_version(self, version: int) -> dict[str, Any]:
        """Las tablas de ``recmin_v12.sql`` con otra versión de esquema."""
        tables = dict(self.tables)
        name = next(key for key in tables if key.casefold() == "actualizacion")
        table = tables[name]
        column = table.position("ULTIMA")
        rows = tuple(tuple(version if i == column else value for i, value in enumerate(row))
                     for row in table.rows)
        tables[name] = self.ports.RawTable(table.name, table.columns, rows)
        return tables

    def run_recmin(self, path: Path | None = None, **props: Any) -> tuple[set[str], list[str]]:
        """La orden con la base ``path`` (la de ``entregas/``) y lo declarado cambiado con
        ``props``; devuelve su final y las operaciones cuyas lecturas lanzó."""
        before = set(self.session.pending_ingests())
        result = bpy.ops.geoblender.dh_import_recmin_mdb(
            "EXEC_DEFAULT", filepath=str(path or self.base), **{**DECLARED, **props})
        launched = [op for job, op in self.session.pending_ingests().items()
                    if job not in before]
        return result, launched

    def decide_recmin(self, stage: str, uid: str) -> set[str]:
        return bpy.ops.geoblender.dh_import_recmin_mdb("EXEC_DEFAULT", stage=stage,
                                                       pending=uid)

    def declaration(self) -> Any:
        catalog = self.georef.load_catalog()
        model = self.model
        return model.SourceDeclaration(
            crs=catalog.horizontal(25830), vertical=catalog.vertical(5782),
            azimuth_ref=model.AzimuthRef.GRID, declination_deg=None,
            inclination_convention=model.InclinationConvention.NEGATIVE_DOWN, units={},
            value_rules=model.ValueRules(decimal_mark="."))

    def log(self, operation: str) -> dict[str, tuple[int, int, int, int]]:
        return {table: tuple(rest) for table, *rest in self.rows(
            "SELECT table_role, n_read, n_imported, n_rejected, n_replaced FROM dh_import_log "
            "WHERE kind = 'summary' AND operation_uid = ?", operation)}

    # --- Pruebas ----------------------------------------------------------------------------

    def test_recmin_base_then_a_new_schema_and_existing_holes(self) -> None:
        """RF-005-13, RF-005-03, RF-005-10, RF-005-12, RF-008-07, RF-008-53 (plan §5.6.5): la
        base es una importación «en curso» que, leída, espera con sus códigos nuevos (el panel
        aplica y descarta con esta orden); aplicada, una entrada (su lector, su hash, el CRS y
        el datum declarados, su original), su informe en ``dh_import_log`` con una línea por
        tabla de RecMin y las cifras del lector, y la base con sus cuatro sondeos, los colores
        de su catálogo y su validación. El extractor abrió la copia del trabajo, nunca la base,
        y su carpeta no cambia.

        RF-005-15, RF-005-11, RF-005-12: otra base con la versión de esquema 13 espera la
        confirmación sin leer nada más (el panel la pide); confirmada, se lee otra vez y espera
        por sus cuatro sondeos, que ya están; aplicada conservando R-02, la base tiene el
        sondeo y el informe cuenta, por tabla de RecMin, los registros sustituidos de R-01,
        R-03 y R-04 y los importados sin los de R-02."""
        before = _folder_state(self.sources)
        result, launched = self.run_recmin()
        self.assertEqual((result, len(launched)), ({"FINISHED"}, 1))
        self.finish()
        uid, pending = self.waiting()
        self.assertEqual(pending.command, IMPORT_RECMIN)
        for code in ("SUE", "MIN", "au", "cu", "Norte"):
            self.assertIn(code, pending.new_codes)
        self.assertEqual((len(pending.holes), pending.confirm), (0, ""))
        self.assertEqual(self.rows("SELECT count(*) FROM gb_input"), [(0,)])
        self.assertEqual(self.statuses(launched), ["running"])
        layout = draw(bpy.types.GEOBLENDER_PT_dh_pending, bpy.context)
        self.assertEqual([(button.target, button.properties.stage, button.properties.pending)
                          for button in layout.of_kind("operator")],
                         [(IMPORT_RECMIN, "APPLY", uid), (IMPORT_RECMIN, "DISCARD", uid)])
        pending.register_codes = True
        self.assertEqual(self.decide_recmin("APPLY", uid), {"FINISHED"})
        self.finish()
        self.assertEqual(self.dh_ops.waiting_imports(), {})
        self.assertEqual(_folder_state(self.sources), before)
        (opened,) = self.extractor.opened
        self.assertNotEqual(opened.parent, self.sources)
        self.assertEqual(opened.parent.name, "in")

        self.assertEqual(self.rows("SELECT name, reader, kind, crs_h, crs_v, original, status "
                                   "FROM gb_input"),
                         [("base_recmin", "io.recmin_mdb@1", "drillholes", '{"epsg":25830}',
                           '{"epsg":5782}', "stored", "current")])
        operations = self.rows("SELECT op_type, status, settings, message FROM gb_operation "
                               "ORDER BY fid")
        self.assertEqual([row[:2] for row in operations],
                         [("dh.import_recmin", "done"), ("dh.build_base", "done"),
                          ("dh.validate", "done")])
        settings = json.loads(operations[0][2])
        self.assertEqual((settings["file"], settings["reader"], settings["decimal"],
                          settings["azimuth_ref"]), (BASE, "io.recmin_mdb@1", ".", "grid"))
        self.assertNotIn("role", settings)
        self.assertIn(BASE, operations[0][3])
        dset, report = self.reader.read_drillholes(list(self.tables.values()),
                                                   self.declaration())
        self.assertEqual(self.log(launched[0]),
                         {table: (counts.read, counts.imported, counts.rejected, 0)
                          for table, counts in report.per_table.items()})
        self.assertEqual(self.rows("SELECT count(*) FROM dh_import_log WHERE kind = 'warning' "
                                   "AND operation_uid = ?", launched[0]),
                         [(len(report.warnings),)])
        self.assertEqual([row[0] for row in self.rows("SELECT name FROM dh_collar "
                                                      "ORDER BY fid")], list(HOLES))
        colors = {(log_set, code): color for log_set, code, color in self.rows(
            "SELECT log_set, code, color FROM dh_lithology_code")}
        self.assertEqual(colors, {(code.log_set, code.code): code.color
                                  for code in dset.catalogs.lithology})
        self.assertTrue(any(BASE in text for text in self.ps.take_notices()))

        # Otra base, de esquema 13, con los mismos sondeos (RF-005-15, RF-005-11).
        newer = self.sources / "base_2026.mdb"
        _ace_base(newer)
        fake = self.use(_FakeExtractor(self.with_version(13)))
        before = _folder_state(self.sources)
        result, (second,) = self.run_recmin(newer)
        self.finish()
        uid, pending = self.waiting()
        self.assertIn("13", pending.confirm)
        self.assertEqual((pending.new_codes, len(pending.holes)), ("", 0))
        layout = draw(bpy.types.GEOBLENDER_PT_dh_pending, bpy.context)
        self.assertIn(pending.confirm.splitlines()[0], layout.texts())
        self.assertEqual(self.statuses([second]), ["running"])
        self.assertEqual(self.decide_recmin("APPLY", uid), {"FINISHED"})
        self.finish()
        self.assertEqual(len(fake.opened), 2)
        uid, pending = self.waiting()
        self.assertEqual(pending.confirm, "")
        self.assertEqual(sorted(hole.name for hole in pending.holes), list(HOLES))
        for hole in pending.holes:
            hole.keep = hole.name == "R-02"
        self.assertEqual(self.decide_recmin("APPLY", uid), {"FINISHED"})
        self.finish()
        self.assertEqual(self.statuses([second]), ["done"])
        self.assertEqual(_folder_state(self.sources), before)
        records = _hole_records(V12)
        replaced = {"R-01", "R-03", "R-04"}
        log = self.log(second)
        self.assertEqual(sorted(log), sorted(report.per_table))
        for table, (read, imported, rejected, substituted) in log.items():
            with self.subTest(tabla=table):
                counts = report.per_table[table]
                per_hole = records.get(table, {})
                self.assertEqual((read, rejected), (counts.read, counts.rejected))
                self.assertEqual(imported, counts.imported - per_hole.get("R-02", 0))
                self.assertEqual(substituted, sum(per_hole.get(hole, 0) for hole in replaced))
        self.assertGreater(log["muestras"][3], 0)
        self.assertEqual([row[0] for row in self.rows("SELECT name FROM dh_collar "
                                                      "ORDER BY fid")], list(HOLES))

    def test_lock_file_missing_engine_and_declarations(self) -> None:
        """RF-005-07: sin el CRS, el datum vertical, la referencia del azimut o la declinación
        de uno magnético, la orden se niega diciendo qué falta y no empieza nada; un fichero
        que no es una base de Access, tampoco.

        RF-005-15: con el fichero de bloqueo de la base junto a ella (otro programa la tiene
        abierta), la orden se niega nombrándolo y no empieza nada; el diálogo enseña el aviso,
        el formato de la base y la confirmación.

        RF-005-14, RF-005-04: confirmado el bloqueo, en un equipo sin motor la lectura falla
        con el formato detectado, qué instalar y la alternativa; la operación queda fallida con
        ese motivo, no se escribe nada y la carpeta de la base no cambia."""
        before = self.counts()
        pending = dict(self.session.pending_ingests())
        cases = (
            ({"crs": ""}, "el CRS de las coordenadas"),
            ({"vertical": "UNDECLARED"}, "el datum vertical de las cotas"),
            ({"azimuth_ref": "NONE"}, "la referencia del azimut"),
            ({"azimuth_ref": "MAGNETIC"}, "la declinación magnética"),
            ({"crs": "EPSG:99999"}, "EPSG:99999"),
        )
        for change, text in cases:
            with self.subTest(cambio=change), self.assertRaises(RuntimeError) as caught:
                self.run_recmin(**change)
            self.assertIn(text, str(caught.exception))
        other = self.sources / "notas.mdb"
        other.write_bytes(b"no es una base" * 8)
        with self.assertRaises(RuntimeError) as caught:
            self.run_recmin(other)
        self.assertIn("notas.mdb", str(caught.exception))
        other.unlink()

        lock = self.base.with_suffix(".laccdb")
        lock.write_bytes(b"")
        folder = _folder_state(self.sources)
        with self.assertRaises(RuntimeError) as caught:
            self.run_recmin()
        self.assertIn("base_recmin.laccdb", str(caught.exception))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.session.pending_ingests(), pending)
        self.assertEqual(self.extractor.opened, [])
        dialog = self.dh_ops.GEOBLENDER_OT_dh_import_recmin_mdb
        texts = draw(dialog, bpy.context, filepath=str(self.base), **DIALOG).texts()
        self.assertTrue(any("base_recmin.laccdb" in text for text in texts), texts)
        self.assertTrue(any(self.ports.MdbFormat.ACE.label in text for text in texts), texts)
        self.assertFalse(any(text.startswith("Falta declarar") for text in texts))
        texts = draw(dialog, bpy.context, filepath=str(self.base),
                     **{**DIALOG, "vertical": "UNDECLARED"}).texts()
        self.assertIn("Falta declarar: el datum vertical de las cotas", texts)

        missing = self.ports.engine_missing(BASE, self.ports.MdbFormat.ACE,
                                            ("ACE.16 (64 bits): no está registrado",))
        self.use(_FakeExtractor({}, error=missing))
        result, (operation,) = self.run_recmin(accept_locked=True)
        self.assertEqual(result, {"FINISHED"})
        self.finish()
        status, reason = self.rows("SELECT status, status_reason FROM gb_operation "
                                   "WHERE uid = ?", operation)[0]
        self.assertEqual(status, "failed")
        for text in (self.ports.MdbFormat.ACE.label, self.ports.ACCESS_ENGINE,
                     self.ports.ENGINE_ALTERNATIVE):
            self.assertIn(text, reason)
        self.assertEqual(self.counts()[1:], before[1:])  # ni datos ni entradas
        self.assertEqual(self.dh_ops.waiting_imports(), {})
        self.assertEqual(_folder_state(self.sources), folder)
        self.assertTrue(any(self.ports.ACCESS_ENGINE in text for text in self.ps.take_notices()))


if __name__ == "__main__":
    unittest.main()
