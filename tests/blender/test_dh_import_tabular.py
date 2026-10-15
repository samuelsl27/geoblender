# SPDX-License-Identifier: GPL-3.0-or-later
"""Importar tablas de sondeos en Blender (spec 005, T25; HU-005-1; plan 005 §5.3.1, §5.5, §5.6.4
y §5.6.5; riesgo R9 del plan).

Proyectos sintéticos de esquema 2 (EPSG:25830 + EPSG:5782, la ventana de trabajo de
``csv_basico``) abiertos en la sesión, con los ficheros de ``tests/data/dh/csv_basico`` en
``entregas/``, fuera de ellos. ``geoblender.dh_import_drillholes`` es un operador de la
procedencia de la 008: una entrada por fichero, cada una con su operación ``dh.import_tabular``
y su lectura (``dh_import_tabular``); al terminar todas, la importación espera en
«Importación pendiente» si hay algo que decidir (códigos nuevos, sondeos que ya están, el
motivo de una sustitución) y, aplicada (``dh_import_apply``), se incorpora por pasos en una
transacción y le siguen la base (``dh.build_base``) y su validación (``dh.validate``). En
``blender -b`` los temporizadores no corren: las pruebas avanzan a mano el monitor de los
trabajos y la cola de incorporación de los sondeos. La lectura, que en Blender va siempre en
proceso aparte, va aquí en el hilo con la misma función (la de proceso aparte la prueban
``tests/unit/workers/test_dh_workers.py``): el presupuesto de ``tools/check.py``.

- RF-005-05, RF-005-10, RF-005-12, RF-005-03 (``mapping_json`` sobre ``csv_basico``): los seis
  ficheros con su papel y la correspondencia propuesta esperan la decisión con sus códigos
  nuevos; aplicados, una entrada por fichero con su hash, su CRS (las bocas) y su original, lo
  importado y su informe en ``dh_import_log`` con las cifras de ``esperado.json``, la base con
  los seis sondeos y los colores de su catálogo, y su validación sin incidencias; la carpeta
  de la fuente no cambia.
- RF-005-07: sin el CRS, el datum vertical, la referencia del azimut (o la declinación de uno
  magnético), el convenio de la inclinación o la unidad de un elemento, nada empieza y el
  mensaje dice qué falta; unas tablas que no lo necesitan sí empiezan.
- RF-005-11, RF-005-04, RF-008-54: el mismo fichero otra vez se reutiliza; otro con los mismos
  sondeos espera y, descartado, no deja nada; aplicado conservando uno, los demás se sustituyen
  en la base y el informe los cuenta. T46: también una orden solo de tablas hijas (desviaciones,
  litología, análisis) de sondeos con registros en ellas.
- RF-005-05 (riesgo R9): el asistente propone el papel y el campo de cada columna (también por
  hoja de un XLSX); los elementos de la enumeración dinámica del campo viven en una caché del
  módulo.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import gc
import hashlib
import importlib
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import bpy
from bpy.props import CollectionProperty

from tests.data.dh import build_xlsx
from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import draw
from tests.support.repo import ROOT

DATA = ROOT / "tests" / "data" / "dh" / "csv_basico"
EXPECTED = json.loads((DATA / "esperado.json").read_text(encoding="utf-8"))
ROLE_OF = {name: role for role, name in EXPECTED["files"].items()}
FILES = ("bocas.csv", "desviaciones.csv", "litologia.csv", "analisis_columnas.csv",
         "litologias.csv", "elementos.csv")
WINDOW = tuple(EXPECTED["work_window"])
HOLES = ("C-01", "S-01", "S-02", "S-03", "S-04", "S-12")
IMPORT = "geoblender.dh_import_drillholes"
DECLARED = {"crs": "EPSG:25830", "vertical": "PROJECT", "azimuth_ref": "GRID",
            "inclination_convention": "NEGATIVE_DOWN", "all_vertical": True,
            "decimal_mark": "COMMA", "separator": "SEMICOLON", "encoding": "UTF8",
            "date_format": "%d/%m/%Y", "units": "Au=g/t; Ag=ppm; Cu=%",
            "density_kind": "ADOPTADO"}
JOB_WAIT_S = 60.0
MAX_TICKS = 300
TEST_TABLES = "gb_t25_tables"  # una colección de tablas del asistente, solo en la prueba


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _folder_state(folder: Path) -> dict[str, tuple[int, int, str]]:
    return {path.relative_to(folder).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns,
                                                  _sha(path))
            for path in sorted(folder.rglob("*")) if path.is_file()}


class DrillholeImportCase(unittest.TestCase):
    """La extensión habilitada una vez para todas; cada prueba, con su proyecto (su ventana
    de trabajo, :attr:`window`: por defecto, la de ``csv_basico``)."""

    window: tuple[float, float, float, float] = WINDOW

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.jobs_ops = _module("bl.ops.jobs")
        cls.dh_ops = _module("bl.ops.dh")
        cls.props = _module("bl.props.dh")
        cls.core = _module("core.project")
        cls.catalog = _module("jobs.catalog")
        cls.dh_jobs = _module("drillholes.jobs")
        cls.tabular = _module("interop.drillholes_tabular")
        cls.options = cls.dh_ops.ReadOptions(encoding="utf-8", separator=";", header_row=0,
                                             decimal=",", date_format="%d/%m/%Y")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ps.close()
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gb-t25-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self.jobs_ops.MONITOR.stop)
        self.addCleanup(self.ps.close)
        self.addCleanup(self.discard_waiting)
        self.ps.take_notices()
        self.read_in_thread()
        self.sources = self.tmp / "entregas"
        self.sources.mkdir()
        for name in (*FILES, "analisis_filas.csv"):
            shutil.copyfile(DATA / name, self.sources / name)
        self.open()

    def read_in_thread(self) -> None:
        """La lectura de una tabla en el hilo, con la función de su proceso aparte."""
        reading = _module("interop.dh_jobs")
        info = self.catalog.WORKERS[self.dh_jobs.IMPORT_TABULAR]
        fast = dataclasses.replace(info, policy="auto", estimate_s=lambda params: 0.01,
                                   run=reading.run_import_tabular)
        self.catalog.unregister_worker(info.name)
        self.catalog.register_worker(fast)

        def restore() -> None:
            if self.catalog.WORKERS.get(info.name) is fast:
                self.catalog.unregister_worker(info.name)
                self.catalog.register_worker(info)

        self.addCleanup(restore)

    def discard_waiting(self) -> None:
        """Descarta lo que una prueba que falló dejó esperando una decisión."""
        for uid in list(self.dh_ops.waiting_imports()):
            bpy.ops.geoblender.dh_import_drillholes("EXEC_DEFAULT", stage="DISCARD",
                                                    pending=uid)

    # --- Ayudas -----------------------------------------------------------------------------

    def open(self) -> Any:
        """Un proyecto nuevo con la ventana :attr:`window` abierto en la sesión, con su
        comprobación de apertura hecha."""
        parent = self.tmp / "proyectos"
        parent.mkdir(parents=True, exist_ok=True)
        settings = self.core.ProjectSettings(**settings_values(window=self.window))
        project = self.core.create_project(parent, settings, self.ps.session(),
                                           self.ps.userdata()).project
        self.ps.attach(project)
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                break
        self.ps.take_notices()
        self.project = project
        return project

    def run_import(self, files: tuple[str, ...], roles: dict[str, str] | None = None,
                   **props: Any) -> tuple[set[str], list[str]]:
        """La orden con ``files`` de ``entregas/`` (su papel, el de ``csv_basico`` o el de
        ``roles``; la correspondencia, la propuesta) y las declaraciones de ``csv_basico``
        cambiadas con ``props``; devuelve su final y las operaciones cuyas lecturas lanzó."""
        chosen = {**ROLE_OF, **(roles or {})}
        mapping = [{"file": name, "role": chosen[name]} for name in files]
        before = set(self.session.pending_ingests())
        result = bpy.ops.geoblender.dh_import_drillholes(
            "EXEC_DEFAULT", directory=str(self.sources),
            files=[{"name": name} for name in files], mapping_json=json.dumps(mapping),
            **{**DECLARED, **props})
        launched = [op for job, op in self.session.pending_ingests().items()
                    if job not in before]
        return result, launched

    def finish(self) -> None:
        """Avanza a mano el monitor de los trabajos y la cola de incorporación de los sondeos
        hasta que no queda ningún trabajo activo ni nada por incorporar: los pasos de una
        incorporación, seguidos; solo se espera (2 ms) a los trabajos."""
        runner = self.jobs_ops.MONITOR.runner
        deadline = time.monotonic() + JOB_WAIT_S
        while time.monotonic() < deadline:
            self.jobs_ops.tick()
            self.dh_ops.incorporation_tick()
            if self.dh_ops.pending_incorporations():
                continue  # el paso siguiente enseguida, como el temporizador (T28)
            if not any(snapshot.active for snapshot in runner.snapshots()):
                self.jobs_ops.tick()
                if (not any(snapshot.active for snapshot in runner.snapshots())
                        and not self.dh_ops.pending_incorporations()):
                    return
            time.sleep(0.002)
        self.fail("los trabajos no terminan")

    def decide(self, stage: str, uid: str) -> set[str]:
        return bpy.ops.geoblender.dh_import_drillholes("EXEC_DEFAULT", stage=stage, pending=uid)

    def waiting(self) -> tuple[str, Any]:
        """La importación que espera la decisión y lo que enseña su panel."""
        (uid,) = self.dh_ops.waiting_imports()
        pending = getattr(bpy.context.window_manager, self.props.IMPORT_PROPERTY)
        self.assertEqual(pending.operation_uid, uid)
        return uid, pending

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def statuses(self, uids: list[str]) -> list[str]:
        return [self.rows("SELECT status FROM gb_operation WHERE uid = ?", uid)[0][0]
                for uid in uids]

    def counts(self) -> tuple[int, int, int]:
        (row,) = self.rows("SELECT (SELECT count(*) FROM gb_operation), "
                           "(SELECT count(*) FROM gb_dataset), (SELECT count(*) FROM gb_input)")
        return row

    def import_all(self, files: tuple[str, ...], **props: Any) -> list[str]:
        """La orden con ``files``, sus códigos nuevos dados de alta y aplicada, hasta el
        final de su validación; devuelve sus operaciones."""
        result, launched = self.run_import(files, **props)
        self.assertEqual(result, {"FINISHED"})
        self.finish()
        if self.dh_ops.waiting_imports():
            uid, pending = self.waiting()
            pending.register_codes = True
            self.assertEqual(self.decide("APPLY", uid), {"FINISHED"})
            self.finish()
        return launched


class ImportTabularTest(DrillholeImportCase):
    def test_csv_basico_then_the_base_and_its_validation(self) -> None:
        """RF-005-05, RF-005-10, RF-005-12, RF-005-03, RF-008-07, RF-008-53 (plan §5.6.5): los
        seis ficheros de ``csv_basico`` con su papel (``mapping_json``) y la correspondencia
        propuesta son seis importaciones «en curso» que, leídas, esperan la decisión: el panel
        lista los códigos nuevos y nada está escrito. Aplicadas, una entrada por fichero (su
        lector, su hash, el CRS y el datum de las bocas y «no aplica» en las demás, su
        original), su informe en ``dh_import_log`` con las filas de ``esperado.json``, la base
        con los seis sondeos y los colores del catálogo de la fuente, y su validación, sin
        incidencias, en la lista de la pestaña. La carpeta de la fuente no cambia."""
        before = _folder_state(self.sources)
        result, launched = self.run_import(FILES)
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(launched), len(FILES))
        self.finish()
        uid, pending = self.waiting()
        for code in ("SUE", "MIN", "Au", "Cu"):
            self.assertIn(code, pending.new_codes)
        self.assertEqual(len(pending.holes), 0)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_input"), [(0,)])
        self.assertEqual(self.statuses(launched), ["running"] * len(FILES))
        pending.register_codes = True
        self.assertEqual(self.decide("APPLY", uid), {"FINISHED"})
        self.finish()
        self.assertEqual(self.dh_ops.waiting_imports(), {})
        self.assertEqual(pending.operation_uid, "")
        self.assertEqual(_folder_state(self.sources), before)

        entries = {name: rest for name, *rest in self.rows(
            "SELECT name, reader, kind, crs_h, crs_v, original, status, content_sha256 "
            "FROM gb_input")}
        self.assertEqual(sorted(entries), sorted(name.removesuffix(".csv") for name in FILES))
        for name, (reader, kind, crs_h, crs_v, original, status, digest) in entries.items():
            with self.subTest(entrada=name):
                self.assertEqual((reader, original, status), ("io.dh_csv@1", "stored",
                                                              "current"))
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
                if name == "bocas":
                    self.assertEqual((kind, crs_h, crs_v),
                                     ("drillholes", '{"epsg":25830}', '{"epsg":5782}'))
                else:
                    self.assertEqual((kind, crs_h), ("table", '{"not_applicable":true}'))
        operations = self.rows("SELECT op_type, status, software, message FROM gb_operation "
                               "ORDER BY fid")
        self.assertEqual([row[:2] for row in operations],
                         [("dh.import_tabular", "done")] * len(FILES)
                         + [("dh.build_base", "done"), ("dh.validate", "done")])
        self.assertTrue(all(row[2].startswith('{"pyproj":"') for row in operations[:-1]))
        self.assertIn("bocas.csv", operations[0][3])
        log = {role: rest for role, *rest in self.rows(
            "SELECT table_role, n_read, n_imported, n_rejected, n_replaced FROM dh_import_log "
            "WHERE kind = 'summary'")}
        self.assertEqual(sorted(log), sorted(ROLE_OF[name] for name in FILES))
        for role, (read, imported, rejected, replaced) in log.items():
            with self.subTest(tabla=role):
                self.assertEqual((read, rejected, replaced), (EXPECTED["rows"][role], 0, 0))
        self.assertEqual(log["assay_wide"][1], EXPECTED["values"]["read"])
        self.assertEqual([row[0] for row in self.rows("SELECT name FROM dh_collar ORDER BY fid")],
                         list(HOLES))
        colors = dict(self.rows("SELECT code, color FROM dh_lithology_code"))
        self.assertEqual((colors["SUE"], colors["MIN"]), ("#8B6B3D", "#C0392B"))
        self.assertEqual(self.rows("SELECT count(*) FROM dh_validation_issue"), [(0,)])
        validation = getattr(bpy.context.window_manager, self.props.VALIDATION_PROPERTY)
        # Sin incidencias; sin MDT, la nota de que DH-W05 no se evaluó (T27, D-19).
        self.assertEqual([(item.code, item.level) for item in validation.issues],
                         [("DH-W05", self.props.NOT_EVALUATED)])
        self.assertIn("0 incidencias", operations[-1][3])
        self.assertTrue(any("bocas.csv" in text for text in self.ps.take_notices()))

    def test_incomplete_declarations_start_nothing(self) -> None:
        """RF-005-07 (spec 0.4): sin el CRS de las coordenadas, el datum vertical («Sin
        declarar»), la referencia del azimut, la declinación de un azimut magnético, el
        convenio de la inclinación o la unidad de un elemento, la orden se niega diciendo qué
        falta (sin suponer nada) y no empieza ninguna operación; un CRS que no es del catálogo,
        tampoco. Control positivo: la litología y su catálogo, que no necesitan ninguno,
        empiezan desde el asistente (``INVOKE_DEFAULT`` con los ficheros: sin interfaz, se
        ejecuta con el papel y la correspondencia que propone, RF-005-05); esperando su
        decisión, descartarlos no deja nada (RF-005-04)."""
        before = self.counts()
        pending = dict(self.session.pending_ingests())
        cases = (
            ({"crs": ""}, "el CRS de las coordenadas"),
            ({"vertical": "UNDECLARED"}, "el datum vertical de las cotas"),
            ({"azimuth_ref": "NONE"}, "la referencia del azimut"),
            ({"azimuth_ref": "MAGNETIC"}, "la declinación magnética"),
            ({"inclination_convention": "NONE"}, "el convenio de la inclinación"),
            ({"units": "Au=g/t; Ag=ppm"}, "la unidad de «Cu»"),
            ({"crs": "EPSG:99999"}, "EPSG:99999"),
        )
        for change, text in cases:
            with self.subTest(cambio=change), self.assertRaises(RuntimeError) as caught:
                self.run_import(FILES, **change)
            self.assertIn(text, str(caught.exception))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.session.pending_ingests(), pending)
        self.assertEqual(self.dh_ops.waiting_imports(), {})

        result = bpy.ops.geoblender.dh_import_drillholes(
            "INVOKE_DEFAULT", directory=str(self.sources),
            files=[{"name": "litologia.csv"}, {"name": "litologias.csv"}],
            **{**DECLARED, "crs": "", "vertical": "UNDECLARED", "azimuth_ref": "NONE",
               "inclination_convention": "NONE", "units": ""})
        launched = [op for job, op in self.session.pending_ingests().items()
                    if job not in pending]
        self.assertEqual((result, len(launched)), ({"FINISHED"}, 2))
        settings = [json.loads(self.rows("SELECT settings FROM gb_operation WHERE uid = ?",
                                         uid)[0][0]) for uid in launched]
        suggested = [(name, ROLE_OF[name], self.tabular.suggest_mapping(
            ROLE_OF[name], self.dh_ops.preview(self.dh_ops.TableChoice(
                self.sources / name, "io.dh_csv@1", "", {}), self.options).columns))
                     for name in ("litologia.csv", "litologias.csv")]
        self.assertEqual([(item["file"], item["role"], item["mapping"])
                          for item in sorted(settings, key=lambda item: item["file"])],
                         suggested)
        self.finish()
        uid, pending_panel = self.waiting()
        self.assertIn("SUE", pending_panel.new_codes)
        self.assertEqual(self.decide("DISCARD", uid), {"FINISHED"})
        self.assertEqual(self.statuses(launched), ["cancelled"] * 2)
        self.assertEqual(self.counts()[1:], before[1:])  # ni datos ni entradas
        self.assertEqual(self.dh_ops.waiting_imports(), {})
        self.assertEqual(pending_panel.operation_uid, "")
        self.assertEqual(self.session.pending_ingests(), pending)

    def test_existing_holes_kept_or_replaced(self) -> None:
        """RF-005-11, RF-005-04, RF-005-12, RF-008-54: el mismo fichero de bocas otra vez
        reutiliza su entrada (cancelada con el aviso, nada nuevo); otro fichero con los mismos
        sondeos (S-01 con otra cota) y uno nuevo espera con los seis que ya están; descartado,
        no deja nada; aplicado conservando S-02, la base tiene la cota nueva de S-01, la de
        antes de S-02 y el sondeo nuevo, y el informe cuenta los cinco sustituidos."""
        self.import_all(("bocas.csv",))  # sin nada que decidir: se aplica sola
        z_before = dict(self.rows("SELECT name, z FROM dh_collar"))
        before = self.counts()

        result, (again,) = self.run_import(("bocas.csv",))
        self.finish()
        status, reason = self.rows("SELECT status, status_reason FROM gb_operation "
                                   "WHERE uid = ?", again)[0]
        self.assertEqual(status, "cancelled")
        self.assertIn("bocas", reason)
        self.assertEqual(self.counts()[1:], before[1:])
        self.assertEqual(self.dh_ops.waiting_imports(), {})

        text = (DATA / "bocas.csv").read_text(encoding="utf-8")
        text = text.replace("S-01;700010,500;4400040,500;798,117",
                            "S-01;700010,500;4400040,500;799,250")
        text += "S-20;700100,000;4400100,000;805,000;50,00;;;DD;C-2026;;;no\n"
        (self.sources / "bocas_2026.csv").write_text(text, encoding="utf-8")
        files = ("bocas_2026.csv",)
        roles = {"bocas_2026.csv": "collar"}
        result, (first,) = self.run_import(files, roles)
        self.finish()
        uid, pending = self.waiting()
        self.assertEqual(sorted(hole.name for hole in pending.holes), sorted(HOLES))
        self.assertEqual(pending.new_codes, "")
        layout = draw(bpy.types.GEOBLENDER_PT_dh_pending, bpy.context)
        self.assertEqual([(button.target, button.properties.stage, button.properties.pending)
                          for button in layout.of_kind("operator")],
                         [(IMPORT, "APPLY", uid), (IMPORT, "DISCARD", uid)])
        self.assertEqual(len(layout.of_kind("prop")), len(HOLES))  # conservar cada uno
        self.assertEqual(self.decide("DISCARD", uid), {"FINISHED"})
        self.assertEqual(self.statuses([first]), ["cancelled"])
        self.assertEqual(self.counts()[1:], before[1:])

        result, (second,) = self.run_import(files, roles)
        self.finish()
        uid, pending = self.waiting()
        for hole in pending.holes:
            hole.keep = hole.name == "S-02"
        self.assertEqual(self.decide("APPLY", uid), {"FINISHED"})
        self.finish()
        self.assertEqual(self.statuses([second]), ["done"])
        z_after = dict(self.rows("SELECT name, z FROM dh_collar"))
        self.assertEqual(sorted(z_after), sorted((*HOLES, "S-20")))
        self.assertEqual(z_after["S-01"], 799.25)
        self.assertEqual(z_after["S-02"], z_before["S-02"])
        self.assertEqual(self.rows("SELECT n_read, n_imported, n_replaced FROM dh_import_log "
                                   "WHERE kind = 'summary' AND operation_uid = ?", second),
                         [(7, 6, 5)])

    def test_child_tables_of_existing_holes_kept_or_replaced(self) -> None:
        """RF-005-11, RF-005-12 (regresión de M1 y M5 en pantalla, 15/10/2026): con
        ``csv_basico`` importado, otra orden solo con desviaciones, litología y análisis de
        sondeos que ya tienen registros en esas tablas espera la decisión como la de las bocas,
        con esos sondeos (S-01, S-02, S-03 y S-04; no S-12, que solo tenía la orientación en
        boca, ni C-01, que no tenía análisis). Aplicada conservando S-03, la base sigue con sus
        estaciones de antes y toma las nuevas de los demás, y el informe de cada tabla
        (``dh_import_log`` y el mensaje de su operación) cuenta los registros sustituidos. Sin
        catálogos ni validación, que no mira (el presupuesto de ``tools/check.py``)."""
        self.enterContext(mock.patch.object(self.dh_ops, "start_validate",
                                            lambda project, **_: None))
        self.import_all(("bocas.csv", "desviaciones.csv", "litologia.csv",
                         "analisis_columnas.csv"))
        survey_sql = ("SELECT s.depth, s.azimuth, s.inclination, s.source FROM dh_survey s "
                      "JOIN dh_collar c ON c.fid = s.hole_id WHERE c.name = ? ORDER BY s.depth")
        s03_before = self.rows(survey_sql, "S-03")
        self.assertEqual([row[3] for row in self.rows(survey_sql, "S-12")], ["collar"])
        revised = {
            "desviaciones_revisadas.csv": (
                "Sondeo;Profundidad;Azimut;Inclinación",
                *(f"S-01;{depth},00;46,00;-60,00" for depth in range(0, 151, 30)),
                *(f"S-03;{depth},00;359,50;-79,50" for depth in range(0, 241, 30)),
                *(f"S-04;{depth},00;0,00;-89,50" for depth in (0, 50, 100)),
                "S-12;0,00;300,00;-75,00", "S-12;160,00;300,00;-74,00"),
            "litologia_revisada.csv": (
                "Sondeo;Desde;Hasta;Litología", "S-02;0,00;2,40;SUE", "S-02;2,40;85,00;ARE",
                "S-02;85,00;190,00;PIZ", "S-02;190,00;206,00;MIN", "S-02;206,00;300,00;PIZ"),
            "analisis_revisados.csv": (
                "Sondeo;Desde;Hasta;Muestra;Au;Ag;Cu", "S-01;60,50;62,50;M-0102;4,90;28,0;0,380",
                "S-01;62,50;64,50;M-0103;5,90;25,0;0,240", "C-01;0,00;0,60;M-C01;0,02;1,0;0,010"),
        }
        for name, lines in revised.items():
            (self.sources / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        roles = dict(zip(revised, ("survey", "lithology", "assay_wide"), strict=True))
        result, launched = self.run_import(tuple(revised), roles)
        self.assertEqual(result, {"FINISHED"})
        self.finish()
        uid, pending = self.waiting()
        self.assertEqual(sorted(hole.name for hole in pending.holes),
                         ["S-01", "S-02", "S-03", "S-04"])
        self.assertEqual(self.statuses(launched), ["running"] * 3)
        for hole in pending.holes:
            hole.keep = hole.name == "S-03"
        self.assertEqual(self.decide("APPLY", uid), {"FINISHED"})
        self.finish()
        self.assertEqual(self.statuses(launched), ["done"] * 3)
        self.assertEqual(self.rows(survey_sql, "S-03"), s03_before)
        self.assertEqual({row[1] for row in self.rows(survey_sql, "S-01")}, {46.0})
        self.assertEqual({row[2] for row in self.rows(survey_sql, "S-04")}, {-89.5})
        self.assertEqual([row[3] for row in self.rows(survey_sql, "S-12")], ["measured"] * 2)
        self.assertIn((190.0, 206.0, "MIN"), self.rows(
            "SELECT l.from_m, l.to_m, k.code FROM dh_lithology l JOIN dh_collar c ON "
            "c.fid = l.hole_id JOIN dh_lithology_code k ON k.fid = l.lithology_id "
            "WHERE c.name = 'S-02'"))
        self.assertEqual(self.rows(
            "SELECT c.name, count(*) FROM dh_assay a JOIN dh_collar c ON c.fid = a.hole_id "
            "GROUP BY c.name ORDER BY c.name"), [("C-01", 3), ("S-01", 6), ("S-02", 30),
                                                 ("S-03", 30)])
        log = {role: (rest, message) for role, *rest, message in self.rows(
            "SELECT l.table_role, l.n_read, l.n_imported, l.n_rejected, l.n_replaced, "
            "o.message FROM dh_import_log l JOIN gb_operation o ON o.uid = l.operation_uid "
            f"WHERE l.kind = 'summary' AND l.operation_uid IN ({', '.join('?' * 3)})",
            *launched)}
        expected = {"survey": [20, 11, 0, 9], "lithology": [5, 5, 0, 5],
                    "assay_wide": [3, 9, 0, 6]}
        self.assertEqual({role: counts for role, (counts, _) in log.items()}, expected)
        for role, (counts, message) in log.items():
            with self.subTest(tabla=role):
                self.assertIn(f"{counts[3]} sustituidos", message)


class WizardTest(DrillholeImportCase):
    def test_tables_fields_and_the_items_cache(self) -> None:
        """RF-005-05 y riesgo R9 del plan (los elementos de una ``EnumProperty`` dinámica que
        Python libera): el asistente propone el papel de cada fichero de ``csv_basico`` (y de
        cada hoja de su libro XLSX, una tabla por hoja) y el campo de cada columna (la
        correspondencia de ``suggest_mapping``, sin tocarla); de su tabla vuelve esa
        correspondencia. Los elementos del campo de una columna salen de una caché del módulo
        (la misma lista cada vez, con un número fijo por campo en todos los papeles) y se
        leen bien tras recoger la basura; cambiar el papel de una tabla propone otra vez los
        campos."""
        props = self.props
        items = props.field_items("collar", "es")
        self.assertIs(props.field_items("collar", "es"), items)
        self.assertEqual(items[0][0], props.FIELD_NONE)
        self.assertEqual([item[0] for item in items[1:]],
                         list(self.tabular.aliases("collar")))
        wide = props.field_items("assay_wide", "es")
        self.assertEqual(wide[-1][0], props.FIELD_ELEMENT)
        numbers = {}
        for role in self.tabular.TableRole:
            for identifier, _name, _description, number in props.field_items(str(role), "es"):
                self.assertEqual(numbers.setdefault(identifier, number), number)
        i18n = _module("core.i18n")
        self.assertEqual(i18n.untranslated([*props.FIELD_MSGIDS.values(),
                                            *props.ROLE_FIELD_MSGIDS.values(),
                                            props.NONE_MSGID, props.ELEMENT_MSGID]), [])
        self.assertEqual(i18n.untranslated(self.dh_ops.SHOWN_MSGIDS), [])

        setattr(bpy.types.WindowManager, TEST_TABLES,
                CollectionProperty(type=props.GEOBLENDER_PG_dh_table))
        self.addCleanup(delattr, bpy.types.WindowManager, TEST_TABLES)
        tables = getattr(bpy.context.window_manager, TEST_TABLES)
        options = self.options
        names = (*FILES, "analisis_filas.csv")
        choices = self.dh_ops.suggested_tables([self.sources / name for name in names],
                                               options)
        self.assertEqual([(choice.path.name, choice.role) for choice in choices],
                         [(name, ROLE_OF[name]) for name in names])
        props.fill_tables(tables, choices)
        gc.collect()
        for table, choice in zip(tables, choices, strict=True):
            with self.subTest(fichero=choice.path.name):
                header = self.dh_ops.preview(choice, options).columns
                self.assertEqual([column.name for column in table.columns], header)
                expected = self.tabular.suggest_mapping(choice.role, header)
                self.assertEqual(dict(choice.mapping), expected)
                self.assertEqual(props.table_mapping(table), expected)
                self.assertEqual(table.role, choice.role.upper())
        # El asistente enseña las primeras filas tal como se van a leer (la coma decimal ya
        # interpretada, «<0,01» con su marca); sin el datum, qué falta y ninguna.
        wizard = self.dh_ops.GEOBLENDER_OT_dh_import_drillholes
        values = {**DECLARED, "declination_deg": "", "sentinels": "",
                  "negative_is_below_dl": False, "header_row": 0, "received_at": "",
                  "received_from": "", "reason": "", "wizard": True, "tables": tables}
        texts = draw(wizard, bpy.context, **values).texts()
        fmt = i18n.format_number
        self.assertIn(f"S-01 · {fmt(700010.5, 1)} · {fmt(4400040.5, 1)} · {fmt(798.117, 3)} · "
                      f"{fmt(150, 0)}", texts)
        self.assertIn(f"S-01 · {fmt(58.5, 1)} · {fmt(60.5, 1)} · Au · <{fmt(0.01, 2)} · g/t",
                      texts)
        self.assertFalse(any(text.startswith("Falta declarar") for text in texts))
        texts = draw(wizard, bpy.context, **{**values, "vertical": "UNDECLARED"}).texts()
        self.assertIn("Falta declarar: el datum vertical de las cotas", texts)
        self.assertNotIn("S-01 · 700", " ".join(texts))
        lithology = tables[FILES.index("litologia.csv")]
        lithology.role = "ASSAY_LONG"
        self.assertEqual(props.table_mapping(lithology), self.tabular.suggest_mapping(
            "assay_long", [column.name for column in lithology.columns]))
        lithology.role = props.NOT_IMPORTED
        self.assertEqual(props.table_mapping(lithology), {})

        book = self.sources / "csv_basico.xlsx"
        build_xlsx.basico_book().write(book)
        sheets = self.dh_ops.suggested_tables([book], options)
        self.assertEqual([(choice.sheet, choice.role, choice.name) for choice in sheets],
                         [(sheet, ROLE_OF[f"{sheet}.csv"], f"csv_basico · {sheet}")
                          for sheet in build_xlsx.BASICO_SHEETS])
        self.assertEqual(sheets[0].mapping, choices[0].mapping)


if __name__ == "__main__":
    unittest.main()
