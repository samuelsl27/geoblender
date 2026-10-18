# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobar y conservar las instantáneas (spec 009, T14; RF-009-09, RF-009-23; plan 009 A8,
D-5, D-11, D-31; RNF-008-12).

Sobre el proyecto de la demostración de versiones (``tests/support/versions_fixtures.py``) con
tres revisiones **congeladas de verdad** (``core.versions.freeze.freeze_steps``): V01.r1 (el
hueco y su volumen, con el original del límite guardado), V01.r2 (sin cambios: todo
referenciado a V01.r1) y V02.r1 (vacía: solo su manifiesto); y V03, que parte de V01 y diseña
con la tabla de bancos congelada en V01.r2 (``Use.frozen``). Se crea una vez por proceso y cada
prueba trabaja en su copia.

``core.versions.check`` compara cada instantánea con lo anotado: al abrir el proyecto (el paso
«instantáneas» de la comprobación de apertura, tras «restos»), la huella del manifiesto, la
existencia y el tamaño de cada fichero propio, de cada fichero de otra instantánea que
referencia y de cada original de sus entradas, y el estado de lo importado que referencia; a
petición («Comprobar cambios en las entradas») y antes de reproducir, también la huella de cada
fichero. Lo que no coincide deja **alterada** esa revisión y la que comparte el fichero (D-5),
con un aviso grave, la marca y su evento; si vuelve a coincidir, se quita (D-31). Las fechas no
se miran. En solo lectura, solo el aviso. Sacar una copia local, publicarla y migrar el
esquema no cambian un byte de las instantáneas, y la 002 borra sus copias sin error (D-11).

Datos solo sintéticos.
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Generator, Iterator, Mapping
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import provenance_data as data
from tests.support import schema2_project
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.core_fixtures import FakeClock, project_tmp
from tests.support.package import import_geoblender
from tests.support.timing import MAX_ATTEMPTS

versions_check = import_geoblender("core.versions.check")
checks = import_geoblender("core.provenance.checks")
freeze = import_geoblender("core.versions.freeze")
versions_read = import_geoblender("core.versions.read")
events_mod = import_geoblender("core.project.events")
open_mod = import_geoblender("core.project.open")
project_model = import_geoblender("core.project.model")
checkout = import_geoblender("core.project.checkout")
migrations = import_geoblender("core.project.migrations")
copytree = import_geoblender("core.project.copytree")
stale = import_geoblender("core.provenance.stale")
graph_mod = import_geoblender("core.provenance.graph")
dataset_registry = import_geoblender("core.datasets.registry")
tracking = import_geoblender("core.datasets.tracking")
external = import_geoblender("core.datasets.external")
userdata_mod = import_geoblender("core.userdata")
hashing = import_geoblender("core.hashing")

EVENT = events_mod.EventKind
Problem = versions_check.Problem
Mismatch = versions_check.Mismatch
Cause = graph_mod.Cause
CauseKind = graph_mod.CauseKind
BUDGET_S = 0.020
"""Lo que puede durar un paso de la comprobación de apertura (RNF-008-12)."""
GRID = vdemo.GRID_LOCATOR.replace(vdemo.PIT_GRID, f"{vdemo.PIT_GRID}_v01")
MESH = vdemo.MESH_LOCATOR.replace(vdemo.PIT_MESH, f"{vdemo.PIT_MESH}_v01")
"""La rejilla y la malla de V01 (D-34), copiadas en V01.r1 con su ruta del proyecto."""
LABELS = ("V01.r1", "V01.r2", "V02.r1")
"""Las revisiones congeladas del proyecto de las pruebas, en su orden."""
ALTERED_V02 = ("La revisión V02.r1 está alterada: 1 fichero no coincide con lo congelado "
               "(manifest.json: otra huella). No se usará ni se reproducirá")

_BASE_TEMPLATE = fixtures.template
_FROZEN: dict[str, Any] = {}


def _drain(steps: Generator[Any, None, Any]) -> Any:
    """Lleva ``steps`` hasta el final y devuelve su resultado."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def _last(steps: Iterator[Any]) -> Any:
    """El resultado del último paso de una operación por pasos de ``core``."""
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


def _freeze(project: Any, version: str, reason: str) -> Any:
    outcome = _last(freeze.freeze_steps(project, version, reason=reason))
    if outcome is None or outcome.frozen is None:
        raise AssertionError(f"no se ha congelado {version}")
    return outcome.frozen


def frozen_template() -> Mapping[str, Any]:
    """El proyecto de la demostración de versiones (:func:`fixtures.template`) con V01.r1,
    V01.r2 y V02.r1 congeladas y V03 diseñando desde V01.r2 (véase el módulo), creado (y
    cerrado) la primera vez que se pide en el proceso, con las mismas claves que la plantilla
    más ``revisions`` (etiqueta → uid), ``original`` (la ruta del original guardado del límite)
    y ``design`` (la operación de V03)."""
    if _FROZEN:
        return _FROZEN
    made = _BASE_TEMPLATE()
    folder = Path(tempfile.mkdtemp(prefix="gb-vs-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    for part in ("proyectos", "fuentes"):
        shutil.copytree(made["folder"] / part, folder / part)
    clock = FakeClock(made["now"])
    clock.advance(minutes=1)
    project = open_mod.open_project(folder / "proyectos" / made["name"], fixtures.SESSION,
                                    userdata_mod.UserData(folder / "u"), clock=clock,
                                    pid_alive=fixtures.PIDS).project
    try:
        with vdemo.VersionsDemo().registered() as demo:
            # El original del límite, guardado (RF-008-53; la demostración no lo guarda).
            with project.read() as conn:
                record = dataset_registry.get(conn, made["boundary"])
            original = f"originals/{record.input_uid}/{data.BOUNDARY_V1}"
            target = Path(project.root, *original.split("/"))
            target.parent.mkdir(parents=True)
            shutil.copy2(folder / "fuentes" / data.BOUNDARY_V1, target)
            seen = target.stat()
            with project.write_transaction() as conn:
                conn.execute(
                    "UPDATE gb_input_file SET original_path = ?, original_size = ?, "
                    "original_sha256 = ?, original_mtime_ns = ? WHERE input_uid = ? AND ord = "
                    "(SELECT min(ord) FROM gb_input_file WHERE input_uid = ?)",
                    (original, seen.st_size, hashing.sha256_file(target), seen.st_mtime_ns,
                     record.input_uid, record.input_uid))
            demo.pit(project, "V01")
            clock.advance(minutes=1)
            demo.pit_volume(project, "V01")
            revisions: dict[str, str] = {}
            for version, reason in (("V01", "Entrega"), ("V01", "Sin cambios"),
                                    ("V02", "Primera")):
                clock.advance(minutes=1)
                frozen = _freeze(project, version, reason)
                revisions[frozen.label(version)] = frozen.uid
            clock.advance(minutes=1)
            fixtures.create_version(project, feature="desde_v01", title="Desde V01",
                                    parent="V01")
            clock.advance(minutes=1)
            design = demo.design_from_parent(project, "V03", frozen=revisions["V01.r2"])
    finally:
        project.close()
    _FROZEN.update(made, folder=folder, now=clock.now(), revisions=revisions,
                   original=original, design=design.uid)
    return _FROZEN


def _prints(root: Path) -> dict[str, tuple[int, str]]:
    """Cada fichero de ``snapshots/`` de ``root`` con su tamaño y su huella."""
    found: dict[str, tuple[int, str]] = {}
    base = Path(root) / "snapshots"
    for path in sorted(base.rglob("*")):
        if path.is_file():
            found[path.relative_to(base).as_posix()] = (path.stat().st_size,
                                                        hashing.sha256_file(path))
    return found


class SnapshotCheckCase(fixtures.VersionsProjectCase):
    """Una copia del proyecto con las revisiones congeladas (:func:`frozen_template`)."""

    tmp_prefix = "gb-vs-"

    def setUp(self) -> None:
        with mock.patch.object(fixtures, "template", frozen_template):
            super().setUp()
        made = frozen_template()
        self.revisions: dict[str, str] = dict(made["revisions"])
        self.original: str = made["original"]
        self.design: str = made["design"]

    # --- Ayudas -----------------------------------------------------------------------------

    def folder_of(self, label: str) -> Path:
        return self.root / "snapshots" / label

    def open_check(self, **kw: Any) -> tuple[Any, list[str]]:
        """La comprobación de apertura entera (en escritura, por defecto), un minuto después:
        su resultado y sus fases, en orden."""
        self.tick()
        kw.setdefault("write", True)
        steps = list(checks.open_check_steps(self.project, **kw))
        self.assertEqual([step.result is not None for step in steps].count(True), 1)
        return steps[-1].result, list(dict.fromkeys(step.phase for step in steps))

    def full_check(self) -> tuple[Any, list[str]]:
        """«Comprobar cambios en las entradas», un minuto después: su resultado y sus fases."""
        self.tick()
        steps = list(checks.full_check_steps(self.project))
        return steps[-1].result, list(dict.fromkeys(step.phase for step in steps))

    def altered(self) -> dict[str, tuple[Any, Any]]:
        """La marca de cada revisión congelada: (``altered_at``, ``altered_detail`` leído)."""
        return {label: (at, None if detail is None else json.loads(detail))
                for label, at, detail in (
                    (f"{code}.r{number}", at, detail) for code, number, at, detail in self.query(
                        "SELECT v.code, r.number, r.altered_at, r.altered_detail FROM gb_revision "
                        "AS r JOIN gb_version AS v ON v.uid = r.version_uid "
                        "WHERE r.state = 'frozen' ORDER BY v.code, r.number"))}

    def events(self, kind: Any) -> list[Any]:
        return self.read(lambda conn: events_mod.read_events(conn, kind))

    def by_label(self, findings: Any) -> dict[str, Any]:
        return {finding.label: finding for finding in findings}

    def causes(self, uid: str) -> set[Any]:
        return {Cause(CauseKind(cause), subject) for cause, subject in self.query(
            "SELECT cause_kind, subject_uid FROM gb_stale WHERE item_uid = ?", (uid,))}

    def assertCacheIsWhole(self) -> None:  # noqa: N802 - unittest
        """La caché de la obsolescencia es la completa (lo que deja la comprobación)."""
        with self.project.read() as conn:
            difference = graph_mod.drain(stale.full_difference_steps(
                lambda: contextlib.nullcontext(conn)))
        self.assertTrue(difference.empty, difference)

    def assertUnaltered(self, *labels: str) -> None:  # noqa: N802 - unittest
        marks = self.altered()
        for label in labels:
            self.assertEqual(marks[label], (None, None), label)


class OpeningTest(SnapshotCheckCase):
    def test_unchanged_then_manifest_altered_and_restored(self) -> None:
        """RF-009-09, D-5, D-31 (plan A8): sin cambios, la comprobación de apertura (su paso
        «instantáneas», tras «restos») no encuentra nada ni marca nada. Con el manifiesto de
        V02.r1 cambiado (mismo tamaño y misma fecha), **solo** V02.r1 queda alterada: su marca
        con lo que no coincide, el evento ``revision_altered`` y el aviso grave en los dos
        idiomas; otra apertura no lo repite. Restaurado el manifiesto, vuelve a coincidir: la
        marca se quita, con el evento ``revision_restored`` y su aviso."""
        self.assertEqual(checks.SURVEY_STEPS,
                         ("foto", "interrumpidas", "entradas", "datos", "restos",
                          "instantáneas", "versiones"))
        outcome, phases = self.open_check()
        self.assertEqual(phases, list(checks.OPEN_CHECK_STEPS))
        self.assertTrue(outcome.recorded)
        self.assertEqual((outcome.snapshots, outcome.warnings), ((), ()))
        self.assertUnaltered(*LABELS)
        found = self.by_label(_drain(versions_check.quick_steps(self.project)))
        self.assertEqual(list(found), list(LABELS))
        self.assertFalse(any(item.altered or item.changed for item in found.values()))
        self.assertEqual(found["V01.r1"].imported, (
            (self.record(self.boundary).uid, self.boundary),))

        undo = fixtures.alter_file(self.folder_of("V02.r1") / "manifest.json")
        outcome, _phases = self.open_check()
        (finding,) = outcome.snapshots
        self.assertEqual((finding.label, finding.revision_uid, finding.what),
                         ("V02.r1", self.revisions["V02.r1"],
                          (Mismatch("manifest.json", Problem.SHA256),)))
        self.assertIn(ALTERED_V02, outcome.warnings)
        self.assertIn("Revision V02.r1 is altered: 1 file does not match what was frozen "
                      "(manifest.json: different fingerprint). It will not be used or "
                      "reproduced", outcome.texts("en"))
        marks = self.altered()
        self.assertEqual(marks["V02.r1"],
                         (self.now(), [{"path": "manifest.json", "problem": "sha256"}]))
        self.assertUnaltered("V01.r1", "V01.r2")
        (event,) = self.events(EVENT.REVISION_ALTERED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.message, event.at),
                         ("revision", self.revisions["V02.r1"], ALTERED_V02, self.now()))
        self.assertEqual(event.data["what"], [{"path": "manifest.json", "problem": "sha256"}])
        revision = self.read(lambda conn: versions_read.revision(conn, self.revisions["V02.r1"]))
        self.assertTrue(revision.altered)

        outcome, _phases = self.open_check()  # ya anotada: ni otro evento ni otro aviso
        self.assertEqual(len(self.events(EVENT.REVISION_ALTERED)), 1)
        self.assertNotIn(ALTERED_V02, outcome.warnings)
        self.assertEqual([item.label for item in outcome.snapshots], ["V02.r1"])
        self.assertEqual(self.altered()["V02.r1"], marks["V02.r1"])

        undo()
        outcome, _phases = self.open_check()
        self.assertIn("La revisión V02.r1 vuelve a coincidir con lo congelado", outcome.warnings)
        self.assertUnaltered(*LABELS)
        (event,) = self.events(EVENT.REVISION_RESTORED)
        self.assertEqual((event.entity_uid, event.message),
                         (self.revisions["V02.r1"],
                          "La revisión V02.r1 vuelve a coincidir con lo congelado"))

    def test_missing_and_other_size_alter_every_revision_that_has_the_file(self) -> None:
        """RF-009-09, D-5, D-31, D-27 (plan A8, A4 (3)): sin la malla de V01.r1 y con su
        rejilla de otro tamaño, quedan alteradas V01.r1 (sus ficheros) y V01.r2 (que los
        referencia, D-28), cada una con lo que no coincide, y no V02.r1. El diseño de V03, que
        usa lo congelado en V01.r2, queda obsoleto (``dataset_damaged``) y la caché sigue siendo
        la completa. Restaurados los dos ficheros (con otra fecha), las dos vuelven a coincidir
        (dos eventos) y el diseño deja de estar obsoleto."""
        mesh, grid = self.folder_of("V01.r1") / MESH, self.folder_of("V01.r1") / GRID
        aside = self.folder / "malla_apartada.npz"
        os.replace(mesh, aside)
        kept = grid.read_bytes()
        grid.write_bytes(kept + b"\0")
        outcome, _phases = self.open_check()
        found = self.by_label(outcome.snapshots)
        self.assertEqual(list(found), ["V01.r1", "V01.r2"])
        self.assertEqual(set(found["V01.r1"].what),
                         {Mismatch(GRID, Problem.SIZE), Mismatch(MESH, Problem.MISSING)})
        self.assertEqual(set(found["V01.r2"].what),
                         {Mismatch(f"snapshots/V01.r1/{GRID}", Problem.SIZE),
                          Mismatch(f"snapshots/V01.r1/{MESH}", Problem.MISSING)})
        text = found["V01.r1"].text()
        self.assertIn(text, outcome.warnings)
        self.assertTrue(text.startswith("La revisión V01.r1 está alterada: 2 ficheros no "
                                        "coinciden con lo congelado ("))
        self.assertIn(f"{GRID}: otro tamaño", text)
        self.assertIn(f"{MESH}: falta", text)
        self.assertTrue(text.endswith("). No se usará ni se reproducirá"))
        marks = self.altered()
        self.assertEqual({label for label, (at, _detail) in marks.items() if at},
                         {"V01.r1", "V01.r2"})
        self.assertEqual(len(self.events(EVENT.REVISION_ALTERED)), 2)
        benches = self.record(vdemo.PIT_BENCHES, "V01")
        self.assertEqual(self.causes(self.design),
                         {Cause(CauseKind.DATASET_DAMAGED, benches.uid)})
        self.assertCacheIsWhole()

        os.replace(aside, mesh)
        grid.write_bytes(kept)  # con otra fecha: no importa (D-5)
        outcome, _phases = self.open_check()
        self.assertEqual({item.label for item in outcome.snapshots if item.restored},
                         {"V01.r1", "V01.r2"})
        self.assertUnaltered(*LABELS)
        self.assertEqual(len(self.events(EVENT.REVISION_RESTORED)), 2)
        self.assertEqual(self.causes(self.design), set())
        self.assertCacheIsWhole()

    def test_imported_damaged_and_original_changed(self) -> None:
        """RF-009-09, RF-008-57, D-18 (plan A8): lo importado que referencian V01.r1 y V01.r2
        (el límite), sin su protección (otro programa le quitó un disparador), queda dañado
        (008) y el original guardado de su entrada cambia de tamaño: las dos quedan alteradas
        con «lo importado «…»: dañado» y el original con otro tamaño; V02.r1 (que no los
        referencia), no."""
        record = self.record(self.boundary)
        trigger = tracking.protection_trigger_names(record.locator, record.selector)[0]
        conn = sqlite3.connect(self.root / fixtures.DATABASE, isolation_level=None)
        try:
            conn.execute(f'DROP TRIGGER "{trigger}"')
        finally:
            conn.close()
        original = Path(self.root, *self.original.split("/"))
        with original.open("ab") as stream:
            stream.write(b"otra version")
        outcome, _phases = self.open_check()
        self.assertIn((record.name, external.DatasetVerdict.DAMAGED),
                      {(item.record.name, item.verdict) for item in outcome.datasets})
        found = self.by_label(outcome.snapshots)
        self.assertEqual(list(found), ["V01.r1", "V01.r2"])
        expected = {Mismatch(self.original, Problem.SIZE),
                    Mismatch(record.name, Problem.DAMAGED, record.uid)}
        self.assertEqual(set(found["V01.r1"].what), expected)
        self.assertEqual(set(found["V01.r2"].what), expected)
        self.assertIn(f"lo importado «{record.name}»: dañado", found["V01.r1"].text())
        self.assertIn(f"{self.original}: otro tamaño", found["V01.r1"].text())
        self.assertIn(f"imported «{record.name}»: damaged", found["V01.r1"].text("en"))
        self.assertUnaltered("V02.r1")
        self.assertEqual(self.altered()["V01.r1"][1],
                         [{"path": self.original, "problem": "size"},
                          {"path": record.name, "problem": "damaged",
                           "dataset_uid": record.uid}])


class OnRequestTest(SnapshotCheckCase):
    def test_same_size_other_fingerprint_only_on_request_and_dates_ignored(self) -> None:
        """RF-009-09, D-5 (plan A8): una copia restaurada con otras fechas no avisa, ni al abrir
        ni a petición. El GeoPackage de V01.r1 con otro byte (mismo tamaño y misma fecha) no se
        ve al abrir; «Comprobar cambios en las entradas» (con su paso «instantáneas») lo ve con
        su huella: V01.r1 y V01.r2 (que lo referencia) alteradas, y la apertura siguiente (que no
        mira huellas) no las da por buenas, tampoco con el byte restaurado: solo otra
        comprobación entera (D-31). :func:`full_steps` (antes de reproducir) comprueba solo las
        revisiones que se le piden, con todas sus huellas, por pasos y sin escribir nada."""
        before = _prints(self.root)
        for path in (self.root / "snapshots").rglob("*"):
            if path.is_file():
                os.utime(path, ns=(path.stat().st_atime_ns, 1_600_000_000_000_000_000))
        outcome, _phases = self.open_check()
        self.assertEqual(outcome.snapshots, ())
        outcome, phases = self.full_check()
        self.assertEqual(phases, list(checks.FULL_CHECK_STEPS))
        self.assertEqual(checks.FULL_CHECK_STEPS,
                         ("entradas", "datos", "instantáneas", "contenido", "registro"))
        self.assertEqual((outcome.snapshots, self.events(EVENT.REVISION_ALTERED)), ((), []))
        self.assertEqual(_prints(self.root), before)

        gpkg = self.folder_of("V01.r1") / "V01.r1.gpkg"
        undo = fixtures.alter_file(gpkg)
        outcome, _phases = self.open_check()
        self.assertEqual(outcome.snapshots, ())
        self.assertUnaltered(*LABELS)
        counter = self.change_counter()
        steps = list(versions_check.full_steps(self.project, [self.revisions["V02.r1"]],
                                               budget_s=1e-9))
        self.assertEqual({step.phase for step in steps}, {versions_check.PHASE})
        (only,) = steps[-1].result
        self.assertEqual((only.label, only.altered), ("V02.r1", False))
        steps = list(versions_check.full_steps(self.project, [self.revisions["V01.r1"]],
                                               budget_s=1e-9))
        (whole,) = steps[-1].result
        self.assertEqual(whole.what, (Mismatch("V01.r1.gpkg", Problem.SHA256),))
        self.assertGreater(len(steps), 3)
        done = [step.done for step in steps]
        self.assertEqual((done, done[-1]), (sorted(done), steps[-1].total))
        self.assertEqual(self.change_counter(), counter)
        self.assertUnaltered(*LABELS)

        outcome, _phases = self.full_check()
        found = self.by_label(outcome.snapshots)
        self.assertEqual(found["V01.r1"].what, (Mismatch("V01.r1.gpkg", Problem.SHA256),))
        self.assertEqual(found["V01.r2"].what,
                         (Mismatch("snapshots/V01.r1/V01.r1.gpkg", Problem.SHA256),))
        self.assertIn("La revisión V01.r1 está alterada: 1 fichero no coincide con lo congelado "
                      "(V01.r1.gpkg: otra huella). No se usará ni se reproducirá",
                      outcome.warnings)
        marks = self.altered()
        self.assertEqual({label for label, (at, _detail) in marks.items() if at},
                         {"V01.r1", "V01.r2"})

        for restore in (True, False):  # al abrir no se ve la huella: sigue alterada
            outcome, _phases = self.open_check()
            self.assertEqual([(item.label, item.changed) for item in outcome.snapshots],
                             [("V01.r1", False), ("V01.r2", False)])
            self.assertEqual(self.altered(), marks)
            if restore:
                undo()  # el byte, otra vez el congelado
        self.assertEqual(self.events(EVENT.REVISION_RESTORED), [])
        outcome, _phases = self.full_check()
        self.assertEqual({item.label for item in outcome.snapshots if item.restored},
                         {"V01.r1", "V01.r2"})
        self.assertUnaltered(*LABELS)
        self.assertEqual(len(self.events(EVENT.REVISION_RESTORED)), 2)

    def test_read_only_only_warns_and_records_when_writable(self) -> None:
        """RF-009-09 (plan A8): en solo lectura, la comprobación de apertura avisa de V02.r1 sin
        su manifiesto y no escribe nada (ni la marca, ni eventos: el contador de cambios de la
        base no se mueve); al volver a abrirlo en escritura, se registra."""
        manifest = self.folder_of("V02.r1") / "manifest.json"
        os.replace(manifest, self.folder / "manifiesto_apartado.json")
        self.project.set_read_only(project_model.ReadOnlyCode.REQUESTED, "a petición (prueba)")
        counter = self.change_counter()
        outcome, _phases = self.open_check()
        self.assertFalse(outcome.recorded)
        text = ("La revisión V02.r1 está alterada: 1 fichero no coincide con lo congelado "
                "(manifest.json: falta). No se usará ni se reproducirá")
        self.assertIn(text, outcome.warnings)
        self.assertEqual(self.change_counter(), counter)
        self.assertUnaltered(*LABELS)
        self.assertEqual(self.events(EVENT.REVISION_ALTERED), [])

        self.project.close()
        self.project = open_mod.open_project(self.root, fixtures.SESSION, self.userdata,
                                             clock=self.clock, pid_alive=fixtures.PIDS).project
        self.addCleanup(self.project.close)
        outcome, _phases = self.open_check()
        self.assertTrue(outcome.recorded)
        self.assertIn(text, outcome.warnings)
        self.assertEqual(self.altered()["V02.r1"][1], [{"path": "manifest.json",
                                                        "problem": "missing"}])


class BudgetTest(SnapshotCheckCase):
    def many_revisions(self, versions: int = 20, revisions: int = 10) -> None:
        """Por SQL, ``versions`` versiones (V04…) con ``revisions`` revisiones congeladas cada
        una (200), cada una con su instantánea (su manifiesto, con su huella anotada, y un
        fichero propio) y, desde la segunda, la referencia al fichero de la anterior."""
        now, user = self.now(), fixtures.USER

        def work(conn: sqlite3.Connection) -> None:
            for number in range(4, 4 + versions):
                code = f"V{number:02d}"
                version = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO gb_version (uid, code, feature, title, status, reason_created, "
                    "created_at, created_by, status_changed_at, status_changed_by, modified_at) "
                    "VALUES (?, ?, 'prueba', 'Prueba', 'BORRADOR', 'Prueba', ?, ?, ?, ?, ?)",
                    (version, code, now, user, now, user, now))
                previous: tuple[str, int, str] | None = None
                for revision in range(1, revisions + 1):
                    label = f"{code}.r{revision}"
                    folder = self.root / "snapshots" / label
                    folder.mkdir()
                    payload = label.encode() * 8
                    (folder / f"{label}.gpkg").write_bytes(payload)
                    sha = hashlib.sha256(payload).hexdigest()
                    own = f"snapshots/{label}/{label}.gpkg"
                    body = hashing.canonical_json({
                        "format": "geoblender-snapshot", "schema": 1, "revision": label,
                        "files": [{"path": f"{label}.gpkg", "size": len(payload),
                                   "sha256": sha}],
                        "datasets": [], "inputs": []})
                    (folder / "manifest.json").write_bytes(body)
                    uid = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO gb_revision (uid, version_uid, number, state, reason, "
                        "created_at, created_by) VALUES (?, ?, ?, 'open', 'Prueba', ?, ?)",
                        (uid, version, revision, now, user))
                    conn.execute(
                        "UPDATE gb_revision SET state = 'frozen', closed_at = ?, closed_by = ?, "
                        "snapshot_dir = ?, snapshot_sha256 = ?, snapshot_bytes = ?, "
                        "geoblender_version = '0.1.0' WHERE uid = ?",
                        (now, user, f"snapshots/{label}", hashlib.sha256(body).hexdigest(),
                         len(payload), uid))
                    rows = [(uid, f"d-{label}", 1, own, len(payload), sha)]
                    if previous is not None:
                        rows.append((uid, f"d-{previous[0]}", 0, *previous[1:]))
                    conn.executemany(
                        "INSERT INTO gb_revision_item (revision_uid, item_kind, item_uid, part, "
                        "content_sha256, copied, snapshot_path, snapshot_layer, file_size, "
                        "file_sha256) VALUES (?, 'dataset', ?, 'produced', ?, ?, ?, 't', ?, ?)",
                        [(row[0], row[1], "c" * 64, *row[2:]) for row in rows])
                    previous = (label, own, len(payload), sha)

        self.write(work)

    def test_each_step_within_budget_with_200_revisions(self) -> None:
        """RF-009-09, RNF-008-12 (plan A8; RNF-009-03): con 200 revisiones congeladas más las
        tres del proyecto, ningún paso de la comprobación de apertura (los siete primeros, con
        el de las instantáneas) pasa de 20 ms (con la máquina cargada se repite hasta encontrar
        un momento tranquilo) y ninguna revisión está alterada; cediendo siempre, cada revisión
        es un paso y lo encontrado es lo mismo. Sin el fichero de V23.r9, V23.r9 y V23.r10 (que
        lo referencia) quedan alteradas, y ninguna otra."""
        self.many_revisions()
        found = _drain(versions_check.quick_steps(self.project))
        self.assertEqual(len(found), 203)
        self.assertFalse(any(item.altered for item in found))

        def run() -> tuple[Any, list[float]]:
            durations: list[float] = []
            outcome = None
            steps = checks.survey_steps(self.project, write=True, budget_s=BUDGET_S)
            while True:
                start = time.perf_counter()
                try:
                    step = next(steps)
                except StopIteration:
                    durations.append(time.perf_counter() - start)
                    return outcome, durations
                durations.append(time.perf_counter() - start)
                if step.result is not None:
                    outcome = step.result

        outcome, durations = run()
        worst = max(durations)
        for _attempt in range(MAX_ATTEMPTS // 4):
            if worst <= BUDGET_S:
                break
            worst = min(worst, max(run()[1]))
        self.assertLessEqual(worst, BUDGET_S, f"un paso tardó {worst * 1000:.1f} ms")
        self.assertEqual((outcome.snapshots, outcome.warnings), ((), ()))
        steps = versions_check.quick_steps(self.project, lap=lambda: True)
        fractions = []
        while True:
            try:
                fractions.append(next(steps))
            except StopIteration as stop:
                tiny = stop.value
                break
        self.assertEqual(len(fractions), 203 - 1)  # una revisión por paso (la última, al final)
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(tiny, found)

        # La referencia de V23.r10 al fichero de V23.r9: si falta, las dos.
        (self.root / "snapshots" / "V23.r9" / "V23.r9.gpkg").unlink()
        found = {item.label: item for item in _drain(versions_check.quick_steps(self.project))
                 if item.altered}
        self.assertEqual(found["V23.r9"].what, (Mismatch("V23.r9.gpkg", Problem.MISSING),))
        self.assertEqual(found["V23.r10"].what,
                         (Mismatch("snapshots/V23.r9/V23.r9.gpkg", Problem.MISSING),))
        self.assertEqual(set(found), {"V23.r9", "V23.r10"})

    def test_without_revisions_nothing_to_check(self) -> None:
        """RF-009-09: un proyecto del esquema 2 abierto en solo lectura (sin migrar: no tiene
        ``gb_revision``) pasa por el paso «instantáneas» sin nada que comprobar."""
        with project_tmp("gb-v2-") as tmp:
            root = schema2_project.extract(tmp)
            opened = open_mod.open_project(root, fixtures.SESSION,
                                           userdata_mod.UserData(tmp / "u"), want_write=False)
            self.addCleanup(opened.project.close)
            steps = list(checks.survey_steps(opened.project, write=False))
            self.assertIn("instantáneas", {step.phase for step in steps})
            self.assertEqual(steps[-1].result.snapshots, ())
            self.assertEqual(_drain(versions_check.quick_steps(opened.project)), ())
            opened.project.close()


class KeptTest(SnapshotCheckCase):
    def test_local_copy_publication_and_migration_keep_snapshots(self) -> None:
        """RF-009-23, D-11 (plan A8): sacar una copia local del proyecto con instantáneas, la
        comprobación entera en la copia, publicarla y migrar el esquema (una migración 3 → 4
        de prueba) no cambian un byte de ninguna (las mismas huellas, también en la copia
        previa); la 002 borra la publicación anterior (con sus instantáneas) al publicar otra
        vez, la copia previa de una migración cancelada y la que queda, sin error."""
        self.project.close()
        before = _prints(self.root)
        self.assertLessEqual({"V01.r1/manifest.json", f"V01.r1/{GRID}", f"V01.r1/{MESH}",
                              "V01.r1/V01.r1.gpkg", "V01.r2/manifest.json",
                              "V02.r1/manifest.json"}, set(before))
        parent, name = self.root.parent, self.root.name
        dest = self.folder / "copias"
        dest.mkdir()
        options = {"clock": self.clock, "pid_alive": fixtures.PIDS}

        result = _last(checkout.checkout_steps(self.root, dest, fixtures.SESSION, self.userdata,
                                               **options))
        local = result.opened.project
        self.assertEqual(_prints(local.root), before)
        found = _drain(versions_check.check_steps(local, full=True))
        self.assertEqual([(item.label, item.altered) for item in found],
                         [(label, False) for label in LABELS])
        _last(checkout.publish_steps(local, fixtures.SESSION, self.userdata, **options))
        self.assertEqual(_prints(self.root), before)
        again = _last(checkout.checkout_steps(self.root, dest, fixtures.SESSION, self.userdata,
                                              **options))
        _last(checkout.publish_steps(again.opened.project, fixtures.SESSION, self.userdata,
                                     **options))
        previous = parent / f"{name}{checkout.PREVIOUS_MARK}"
        self.assertEqual(sorted(path.name for path in parent.iterdir()),
                         [name, previous.name])
        self.assertEqual((_prints(self.root), _prints(previous)), (before, before))

        def m3_4(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE IF NOT EXISTS gb_test_m4 (fid INTEGER PRIMARY KEY)")

        chain = (*migrations.REGISTRY, migrations.Migration(3, 4, "tabla de prueba", m3_4))
        steps = migrations.migrate_steps(self.root, fixtures.SESSION, self.userdata, chain,
                                         target=4, **options)
        for step in steps:
            if step.phase == migrations.PHASES[3]:
                break
        steps.close()  # cancelada tras la copia previa: se borra
        self.assertEqual(sorted(path.name for path in parent.iterdir()),
                         [name, previous.name])
        migrated = _last(migrations.migrate_steps(self.root, fixtures.SESSION, self.userdata,
                                                  chain, target=4, **options))
        self.assertEqual(migrated.to_version, 4)
        self.assertEqual((_prints(self.root), _prints(migrated.backup)), (before, before))
        copytree.remove_tree(migrated.backup)
        self.assertFalse(migrated.backup.exists())
