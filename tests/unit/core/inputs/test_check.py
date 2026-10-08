# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobación de las fuentes de las entradas (spec 008, T25; RF-008-09, RF-008-10, RF-008-12,
RF-008-13, RF-008-14; ADR-0024 §6; ADR-0025 §6; plan 008 §5.3.1 y §5.4.2).

``core.inputs.check_steps`` compara la fuente de cada entrada activa con lo registrado, por
pasos medidos por tiempo:

- **rápida** (al abrir y antes de operar): el tamaño y la fecha de todos sus ficheros (con el
  ``-wal`` o el ``-journal`` de una fuente SQLite; el ``last_change`` de una tabla del proyecto)
  frente a la última comprobación o a lo registrado y, solo si algo cambió, el hash de contenido
  con su lector y su normalizador; **completa** (a petición): siempre el hash;
- cambió el contenedor y no el contenido: se anotan el tamaño y la fecha nuevos, sin aviso;
- cambió el contenido: «cambiada», con el aviso de la spec §8 y lo que depende de ella; «se
  mantiene la copia» no vuelve a avisar mientras la fuente siga como se vio; una «cambiada» que
  vuelve a su contenido registrado pasa a «vigente», con su evento;
- una fuente que no se encuentra es «no localizable» y no cuenta como cambio;
- nunca se escribe nada junto a la fuente.

Cada prueba usa el proyecto sintético de ``test_registry`` (esquema 2, reloj simulado) con las
fuentes de ``tests/data/core/provenance/`` copiadas en ``fuentes/``, junto a él.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import provenance_data as data
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_contract import registered
from tests.support.provenance_readers import registered as readers_registered
from tests.support.trees import age_folders
from tests.unit.core.inputs.test_registry import (
    ETRS89,
    GPKG,
    LAYER,
    NOT_APPLICABLE,
    REDNAP,
    SESSION,
    LifecycleCase,
    _write_rows,
)

check = import_geoblender("core.inputs.check")
inputs = import_geoblender("core.inputs")
model = import_geoblender("core.inputs.model")
registry = import_geoblender("core.inputs.registry")
provenance = import_geoblender("core.provenance")
operations = import_geoblender("core.provenance.operations")
figures = import_geoblender("core.provenance.figures")
messages = import_geoblender("core.provenance.messages")
events = import_geoblender("core.project.events")
project_model = import_geoblender("core.project.model")
session = import_geoblender("core.project.session")
content = import_geoblender("core.content")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
datasets = import_geoblender("core.datasets")
base = import_geoblender("core.gpkg.base")
hashing = import_geoblender("core.hashing")
timeutil = import_geoblender("core.timeutil")
i18n = import_geoblender("core.i18n")

ProvenanceError = messages.ProvenanceError
Verdict = check.Verdict
Status = model.InputStatus

MEASURE = provenance.OperationDef("res.measure", "1.0", "res", "Test measure", False)
SCHEDULE = provenance.OperationDef("res.schedule", "1.0", "res", "Test schedule", False)
AREA = provenance.FigureDef("res.boundary_area", "ha", "Test boundary area")
LABELS_ES = {"Test boundary area": "Área del límite"}
ROWS = (("P-01", 6.0), ("P-02", 3.0), ("P-03", 3.0))
SOURCE = data.BOUNDARY_V1  # el fichero registrado, en fuentes/
BASE_NS = 1_791_000_000 * 10**9  # fechas de modificación de prueba, en segundos enteros
MARKS = "res_marcas"


def _local(moment: str) -> str:
    """Una hora UTC guardada como la lee una persona: «DD/MM/AAAA HH:MM», hora local."""
    return timeutil.parse_utc(moment).astimezone().strftime("%d/%m/%Y %H:%M")


def _local_ns(mtime_ns: int) -> str:
    moment = dt.datetime(1970, 1, 1, tzinfo=dt.UTC) + dt.timedelta(microseconds=mtime_ns // 1000)
    return moment.astimezone().strftime("%d/%m/%Y %H:%M")


def _read_asc(request: Any) -> Iterator[float]:
    """Lector de prueba de un ASC con su ``.prj``: las dos partes, por sus bytes."""
    _ASC_ROLES.append(tuple(sorted(request.files)))
    parts = {
        "asc": ("document", hashing.sha256_file(request.files["main"])),
        "prj": ("document", hashing.sha256_file(request.files["prj"])),
    }
    request.hasher.composite(parts)
    yield 1.0


_ASC_ROLES: list[tuple[str, ...]] = []
ASC = readers.ContentReader("test.asc_prj", 1, ("raster",), False, False, None, _read_asc)


class CheckCase(LifecycleCase):
    """El proyecto de ``test_registry`` con el límite «Limites_v1» importado de ``fuentes/``."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(registered(MEASURE, SCHEDULE, AREA))
        i18n.install(LABELS_ES)
        self.target = self.sources / SOURCE
        self.hashed: list[str] = []

    # --- Ayudas -----------------------------------------------------------------------------

    def import_boundary(self, *, shared: bool = False) -> Any:
        """Importa ``fuentes/Limites_v1.gpkg``: lo importado, en ``res_limites`` o, con
        ``shared``, como ``res_limites_v1`` en esa tabla común, con su dato acumulado."""
        record, _handle = self.load(self.boundary(), ROWS, table="res_limites",
                                    dataset="res_limites_v1" if shared else "res_limites",
                                    shared=shared)
        return record

    def run_check(self, mode: str = "quick", selected: Any = None, **kw: Any) -> Any:
        """Todos los pasos de ``check_steps``; anota en ``self.hashed`` lo que se hasheó (el
        nombre del fichero principal de cada lectura) y devuelve el resultado."""
        self.hashed = []
        real = check.read_steps

        def counting(found: Any, request: Any) -> Any:
            self.hashed.append(request.files["main"].name)
            return real(found, request)

        with mock.patch.object(check, "read_steps", counting):
            steps = list(check.check_steps(self.project, selected, mode=mode, **kw))
        for step in steps:
            self.assertIsInstance(step, project_model.Progress)
        outcome = steps[-1].result
        self.assertIsInstance(outcome, check.CheckOutcome)
        return outcome

    def replace(self, name: str, *, mtime_ns: int | None = None, step: int = 1) -> int:
        """Pone en el sitio de la fuente registrada una copia de ``fuentes/<name>`` con la
        fecha ``mtime_ns`` (por defecto, una nueva) y la devuelve."""
        shutil.copyfile(self.sources / name, self.target)
        return self.set_mtime(self.target, mtime_ns, step)

    def set_mtime(self, path: Path, mtime_ns: int | None = None, step: int = 1) -> int:
        chosen = BASE_NS + step * 60 * 10**9 if mtime_ns is None else mtime_ns
        os.utime(path, ns=(path.stat().st_atime_ns, chosen))
        return chosen

    def third_version(self) -> int:
        """Una tercera versión del límite: v2 con otro tipo en la parcela P-01."""
        shutil.copyfile(self.sources / data.BOUNDARY_V2, self.target)
        conn = sqlite3.connect(self.target, isolation_level=None)
        try:
            conn.execute(f'UPDATE "{LAYER}" SET tipo = ? WHERE codigo = ?', ("otro", "P-01"))
        finally:
            conn.close()
        return self.set_mtime(self.target, step=30)

    def content_of(self, path: Path) -> str:
        """El hash de contenido de un límite con las declaraciones del registrado."""
        declarations = model.input_declarations(ETRS89, NOT_APPLICABLE, {})
        request = builtin.GPKG_LAYER.request("vector", declarations, {"main": path},
                                             {"layer": LAYER})
        return readers.read_content(builtin.GPKG_LAYER, request).content_sha256

    def files(self, uid: str) -> list[dict[str, Any]]:
        return self.rows("gb_input_file", "input_uid = ?", (uid,))

    def input_row(self, uid: str) -> dict[str, Any]:
        return self.rows("gb_input", "uid = ?", (uid,))[0]

    def finding(self, outcome: Any, uid: str) -> Any:
        (found,) = [item for item in outcome.findings if item.input_uid == uid]
        return found

    def changed_text(self, record: Any, counts: str, source: str) -> str:
        return (f"La entrada «{record.name}» ha cambiado desde su registro "
                f"({_local(record.registered_at)}). Dependen de ella: {counts}. Fecha de la "
                f"fuente: {source}.")


class QuickCheckTest(CheckCase):
    def test_quick_check_hashes_only_when_size_or_date_change(self) -> None:
        """RF-008-09, RF-008-14: sin cambios en el tamaño ni en la fecha de sus ficheros no se
        hashea nada ni se escribe nada. Con ``Limites_v1_qgis`` (el mismo contenido reescrito
        por QGIS: otros bytes y otra fecha) en lugar de ``v1``, se hashea con su lector, no
        avisa y anota el tamaño y la fecha nuevos como última comprobación sin cambiar la
        entrada; la siguiente comprobación rápida se compara con ellos y no hashea. Nada se
        escribe junto a la fuente."""
        record = self.import_boundary()
        age_folders(self.sources)
        before = self.snapshot()
        with assert_source_untouched(self.sources):
            outcome = self.run_check()
        self.assertEqual(self.hashed, [])
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.before, found.status, found.name),
                         (Verdict.UNCHANGED, Status.CURRENT, Status.CURRENT, "Limites_v1"))
        self.assertIsNone(found.warning)
        self.assertEqual((outcome.warnings, outcome.recorded), ((), True))
        self.assertEqual(self.snapshot(), before)
        # QGIS lo abre y lo guarda: otros bytes, otra fecha, el mismo contenido.
        (registered_file,) = self.files(record.uid)
        moment = self.replace(data.BOUNDARY_V1_QGIS)
        self.assertNotEqual(hashing.sha256_file(self.target), registered_file["sha256"])
        input_before = self.input_row(record.uid)
        now = self.later()
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            outcome = self.run_check()
        self.assertEqual(self.hashed, [SOURCE])
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.status, found.content_sha256),
                         (Verdict.SAME, Status.CURRENT, record.content_sha256))
        self.assertIsNone(found.warning)
        self.assertEqual(outcome.warnings, ())
        self.assertEqual(self.files(record.uid), [{
            **registered_file, "checked_size": self.target.stat().st_size,
            "checked_mtime_ns": moment, "checked_at": now,
        }])
        self.assertEqual(self.input_row(record.uid), input_before)
        self.assertEqual(self.logged(events.EventKind.INPUT_CHANGED), [])
        # La siguiente se compara con lo anotado: no hashea.
        outcome = self.run_check()
        self.assertEqual(self.hashed, [])
        self.assertEqual(self.finding(outcome, record.uid).verdict, Verdict.UNCHANGED)
        # Por pasos: con un presupuesto mínimo, cada trozo de trabajo es un paso.
        steps = list(check.check_steps(self.project, mode="full", budget_s=1e-9))
        self.assertGreaterEqual(len(steps), 4)
        self.assertEqual([step.phase for step in (steps[0], steps[-1])],
                         [check.PHASES[0], check.PHASES[-1]])
        with self.assertRaises(ValueError):
            next(check.check_steps(self.project, mode="lenta"))
        with self.assertRaises(ValueError):
            next(check.check_steps(self.project, budget_s=0))

    def test_same_size_and_date_is_seen_only_by_the_full_check(self) -> None:
        """RF-008-09 (spec §8: un fichero sustituido por otro del mismo tamaño y con la fecha
        conservada): la comprobación rápida no lo ve y no hashea; la completa, que siempre
        calcula el hash, lo encuentra cambiado."""
        record = self.import_boundary()
        (registered_file,) = self.files(record.uid)
        self.replace(data.BOUNDARY_V2, mtime_ns=registered_file["mtime_ns"])
        self.assertEqual(self.target.stat().st_size, registered_file["size"])
        outcome = self.run_check("quick")
        self.assertEqual(self.hashed, [])
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.status), (Verdict.UNCHANGED, Status.CURRENT))
        outcome = self.run_check(check.CheckMode.FULL)
        self.assertEqual(self.hashed, [SOURCE])
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.status, found.content_sha256),
                         (Verdict.CHANGED, Status.CHANGED, self.content_of(self.target)))
        self.assertEqual(self.input_row(record.uid)["status"], "changed")


class ChangedTest(CheckCase):
    def chain(self, record: Any) -> dict[str, Any]:
        """Lo que depende del límite (importado en una tabla común, con su acumulado):
        «res.measure» lo lee como entrada y escribe ``res_medidas``, un borrador (que se
        sustituye) y dos cifras;
        «res.schedule» lee ``res_medidas`` y escribe otra cifra, y la sustituye otra
        «res.schedule» (un recálculo). No dependen: la sustituida, una «res.measure» fallida
        que leía el acumulado y una «res.schedule» que no lee nada."""
        outputs = [datasets.DatasetSpec(name, "res", "table", "gpkg", name, reader=GPKG,
                                        role=role)
                   for name, role in (("res_medidas", "result"), ("res_borrador", "draft"))]
        measure = operations.begin_operation(
            self.project, MEASURE.op_type, settings={}, executor="blender",
            inputs=[operations.Use(record.uid, "source", kind="input")])

        def first(conn: sqlite3.Connection) -> Any:
            for spec in outputs:
                _write_rows(conn, spec.locator, record.uid, ROWS)
            return measure.complete(conn, outputs=outputs, figures=[
                figures.FigureSpec(AREA.key, 12.0, "ha"),
                figures.FigureSpec(AREA.key, 6.0, "ha", scope={"parcel": "P-01"}),
            ])

        (measured, draft) = self.write(first)
        # El borrador ya no está vivo: no cuenta.
        self.write(lambda conn: datasets.supersede(conn, self.project, draft.uid))
        replaced = None
        for _time in range(2):
            schedule = operations.begin_operation(
                self.project, SCHEDULE.op_type, settings={}, executor="blender",
                inputs=[operations.Use("res_medidas", "measures")], supersedes=replaced)
            self.write(lambda conn: schedule.complete(conn, figures=[
                figures.FigureSpec(AREA.key, 4.43, "ha", scope={"parcel": "P-02"})]))
            replaced = schedule.uid
        failed = operations.begin_operation(
            self.project, MEASURE.op_type, settings={}, executor="blender",
            inputs=[operations.Use("res_limites", "boundary")])
        failed.fail("prueba: no termina")
        other = operations.begin_operation(self.project, SCHEDULE.op_type, settings={},
                                           executor="blender")
        self.write(lambda conn: other.complete(conn, figures=[
            figures.FigureSpec(AREA.key, 3.0, "ha", scope={"parcel": "P-03"})]))
        figure_rows = self.rows("gb_figure", "operation_uid IN (?, ?)",
                                (measure.uid, schedule.uid))
        return {
            "datasets": (self.dataset("res_limites_v1").uid, self.dataset("res_limites").uid,
                         measured.uid),
            "operations": (measure.uid, schedule.uid),
            "figures": tuple(row["uid"] for row in figure_rows),
        }

    def test_changed_source_warns_with_what_depends_on_it(self) -> None:
        """RF-008-10, RF-008-14: con ``Limites_v2`` en lugar de ``v1`` (un vértice movido), la
        entrada queda «cambiada» con el contenido visto, quién y cuándo, la última comprobación
        y el evento ``input_changed``, y el aviso de la spec §8 con la fecha de su registro, lo
        que depende de ella (datos, operaciones y cifras, con la lista) y la fecha de la fuente.
        Mientras no se decida, cada comprobación lo sigue avisando sin volver a hashear ni a
        registrar nada. Nada se escribe junto a la fuente."""
        record = self.import_boundary(shared=True)
        chain = self.chain(record)
        moment = self.replace(data.BOUNDARY_V2)
        now = self.later()
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            outcome = self.run_check()
        self.assertEqual(self.hashed, [SOURCE])
        found = self.finding(outcome, record.uid)
        seen = self.content_of(self.sources / data.BOUNDARY_V2)
        self.assertEqual((found.verdict, found.before, found.status, found.content_sha256),
                         (Verdict.CHANGED, Status.CURRENT, Status.CHANGED, seen))
        self.assertEqual(found.dependents, check.Dependents(
            datasets=(check.Dependent(chain["datasets"][0], "res_limites_v1"),
                      check.Dependent(chain["datasets"][1], "res_limites"),
                      check.Dependent(chain["datasets"][2], "res_medidas")),
            operations=(check.Dependent(chain["operations"][0], MEASURE.op_type),
                        check.Dependent(chain["operations"][1], SCHEDULE.op_type)),
            figures=tuple(check.Dependent(uid, AREA.key) for uid in chain["figures"]),
        ))
        text = self.changed_text(record, "3 datos, 2 operaciones y 3 cifras", _local_ns(moment))
        self.assertTrue(text.startswith(
            "La entrada «Limites_v1» ha cambiado desde su registro ("))
        self.assertEqual(found.warning, text)
        self.assertEqual(outcome.warnings, (text,))
        self.assertEqual(found.render("en"), (
            f"Input «Limites_v1» has changed since it was registered "
            f"({_local(record.registered_at)}). Depending on it: 3 datasets, 2 operations and 3 "
            f"figures. Date of the source: {_local_ns(moment)}."
        ))
        row = self.input_row(record.uid)
        self.assertEqual(
            {key: row[key] for key in ("status", "seen_sha256", "status_at", "status_by",
                                       "status_reason", "modified_at", "content_sha256")},
            {"status": "changed", "seen_sha256": seen, "status_at": now,
             "status_by": SESSION.user_host, "status_reason": None, "modified_at": now,
             "content_sha256": record.content_sha256},
        )
        (checked,) = self.files(record.uid)
        self.assertEqual((checked["checked_size"], checked["checked_mtime_ns"],
                          checked["checked_at"]), (self.target.stat().st_size, moment, now))
        (event,) = self.logged(events.EventKind.INPUT_CHANGED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.at, event.message),
                         ("input", record.uid, now, text))
        self.assertEqual(event.data, {
            "name": "Limites_v1",
            "from_status": "current",
            "content_sha256": record.content_sha256,
            "seen_sha256": seen,
            "previous_seen": None,
            "source_date": timeutil.format_utc(
                dt.datetime(1970, 1, 1, tzinfo=dt.UTC) + dt.timedelta(microseconds=moment // 1000)),
            "files": [{"ord": 0, "size": checked["checked_size"], "mtime_ns": moment,
                       "last_change": None}],
            "dependents": {"datasets": 3, "operations": 2, "figures": 3},
        })
        # Sin decidir: se sigue avisando sin volver a hashear ni a registrar.
        before = self.snapshot()
        self.later()
        outcome = self.run_check()
        self.assertEqual(self.hashed, [])
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.status, found.warning),
                         (Verdict.UNCHANGED, Status.CHANGED, text))
        self.assertEqual(self.snapshot(), before)

    def test_wal_variant_jumps_to_the_hash_by_its_wal(self) -> None:
        """RF-008-09, RF-008-10, RF-008-14 (spec §8: GeoPackage de entrada en WAL): con la
        edición de v2 pendiente en su ``-wal`` y el fichero principal con el tamaño y la fecha
        registrados, el prefiltro salta al hash por el ``-wal`` y la entrada queda «cambiada»
        con su aviso; se lee sin escribir nada junto a la fuente (ni ``-wal`` ni ``-shm``)."""
        record = self.import_boundary()
        (registered_file,) = self.files(record.uid)
        wal = data.make_wal_variant(self.sources)
        self.assertEqual((wal.path, self.target.stat().st_size),
                         (self.target, registered_file["size"]))
        self.set_mtime(self.target, registered_file["mtime_ns"])
        self.assertGreater(wal.wal.stat().st_size, 0)
        edited = self.set_mtime(wal.wal, registered_file["mtime_ns"] + 3600 * 10**9)
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            outcome = self.run_check()
        self.assertEqual(self.hashed, [SOURCE])
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.status, found.content_sha256),
                         (Verdict.CHANGED, Status.CHANGED,
                          self.content_of(self.sources / data.BOUNDARY_V2)))
        self.assertEqual(found.warning, self.changed_text(
            record, "1 dato, 0 operaciones y 0 cifras", _local_ns(edited)))

    def test_kept_copy_is_not_warned_until_another_change(self) -> None:
        """RF-008-12, RF-008-10: «se mantiene la copia» no vuelve a avisar ni la rápida (sin
        hash) ni la completa (mismo contenido que el visto, sin evento) hasta que la fuente
        cambia otra vez: entonces vuelve a «cambiada» con su aviso. Una «cambiada» cuya fuente
        vuelve a su contenido registrado (aunque con otros bytes) pasa a «vigente» con el evento
        ``input_restored``."""
        record = self.import_boundary()
        self.replace(data.BOUNDARY_V2)
        self.assertEqual(self.finding(self.run_check(), record.uid).status, Status.CHANGED)
        self.write(lambda conn: registry.keep_copy(conn, self.project, record.uid,
                                                   reason="La propiedad lo revisará"))
        outcome = self.run_check()
        self.assertEqual(self.hashed, [])
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.status, found.warning),
                         (Verdict.UNCHANGED, Status.KEPT, None))
        before = self.snapshot()
        outcome = self.run_check("full")
        self.assertEqual(self.hashed, [SOURCE])
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.status, found.warning, outcome.warnings),
                         (Verdict.SAME, Status.KEPT, None, ()))
        self.assertEqual(len(self.logged(events.EventKind.INPUT_CHANGED)), 1)
        self.assertEqual(self.snapshot()[:1], before[:1])
        # Otro cambio de la fuente: vuelve a avisar.
        moment = self.third_version()
        now = self.later()
        outcome = self.run_check()
        found = self.finding(outcome, record.uid)
        third = self.content_of(self.target)
        self.assertEqual((found.verdict, found.before, found.status, found.content_sha256),
                         (Verdict.CHANGED, Status.KEPT, Status.CHANGED, third))
        self.assertEqual(found.warning, self.changed_text(
            record, "1 dato, 0 operaciones y 0 cifras", _local_ns(moment)))
        row = self.input_row(record.uid)
        self.assertEqual((row["status"], row["seen_sha256"], row["status_at"],
                          row["status_reason"]), ("changed", third, now, None))
        second = self.content_of(self.sources / data.BOUNDARY_V2)
        (_first, again) = self.logged(events.EventKind.INPUT_CHANGED)
        self.assertEqual((again.data["from_status"], again.data["previous_seen"],
                          again.data["seen_sha256"]), ("kept", second, third))
        # Sin decidir, la fuente cambia otra vez: sigue «cambiada» con lo visto nuevo.
        self.replace(data.BOUNDARY_V2, step=35)
        later = self.later()
        found = self.finding(self.run_check(), record.uid)
        self.assertEqual((found.verdict, found.before, found.status),
                         (Verdict.CHANGED, Status.CHANGED, Status.CHANGED))
        row = self.input_row(record.uid)
        self.assertEqual((row["status"], row["seen_sha256"], row["status_at"],
                          row["modified_at"]), ("changed", second, now, later))
        self.assertEqual(self.logged(events.EventKind.INPUT_CHANGED)[-1].data["previous_seen"],
                         third)
        # La fuente vuelve a su contenido registrado (reescrito por QGIS): «vigente».
        self.replace(data.BOUNDARY_V1_QGIS, step=40)
        now = self.later()
        outcome = self.run_check()
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.before, found.status, found.warning),
                         (Verdict.RESTORED, Status.CHANGED, Status.CURRENT, None))
        row = self.input_row(record.uid)
        self.assertEqual((row["status"], row["seen_sha256"], row["status_at"], row["status_by"]),
                         ("current", None, now, SESSION.user_host))
        (event,) = self.logged(events.EventKind.INPUT_RESTORED)
        self.assertEqual((event.entity_uid, event.at), (record.uid, now))
        self.assertEqual(event.message, "Entrada «Limites_v1» vigente otra vez: su fuente vuelve "
                                        "a tener el contenido registrado.")
        self.assertEqual(event.data, {"name": "Limites_v1", "from_status": "changed",
                                      "content_sha256": record.content_sha256,
                                      "previous_seen": second})

    def test_read_only_project_detects_without_writing(self) -> None:
        """RF-008-09, RF-008-10 (spec §8, proyecto en solo lectura): se detecta y se avisa,
        pero no se registra nada."""
        record = self.import_boundary()
        self.replace(data.BOUNDARY_V2)
        before = self.snapshot()
        self.project.set_read_only(project_model.ReadOnlyCode.LOCKED, "otra sesión lo tiene")
        outcome = self.run_check()
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.status, outcome.recorded),
                         (Verdict.CHANGED, Status.CHANGED, False))
        self.assertEqual(len(outcome.warnings), 1)
        self.assertEqual(self.snapshot(), before)

    def test_input_decided_while_checking_is_left_alone(self) -> None:
        """RF-008-10, RF-008-12: si la persona decide sobre la entrada mientras se comprueba
        (mantiene la copia antes de registrar lo encontrado, o la descarta mientras la escritura
        espera a otro programa que lee el proyecto), lo encontrado no se muestra ni se registra
        sobre su decisión: queda para la comprobación siguiente."""
        record = self.import_boundary()
        self.replace(data.BOUNDARY_V2)
        self.run_check()
        steps = check.check_steps(self.project, mode="quick", budget_s=1e-9)
        for step in steps:
            if step.phase == check.PHASES[2]:
                break
        self.write(lambda conn: registry.keep_copy(conn, self.project, record.uid))
        outcome = list(steps)[-1].result
        self.assertEqual((outcome.findings, outcome.stale, outcome.warnings),
                         ((), (record.uid,), ()))
        # Con la base ocupada, la escritura se reintenta en el paso siguiente.
        self.third_version()
        real = self.project.try_write
        attempts: list[str] = []

        def busy(work: Any) -> Any:
            attempts.append("intento")
            if len(attempts) == 1:
                return session.WriteAttempt(session.WriteState.RETRYING, None, "Base ocupada")
            return real(work)

        with mock.patch.object(self.project, "try_write", busy):
            steps = check.check_steps(self.project, mode="quick")
            for step in steps:
                if step.message == "Base ocupada":
                    break
            self.write(lambda conn: registry.discard(conn, self.project, record.uid,
                                                     "Equivocada"))
            outcome = list(steps)[-1].result
        self.assertEqual(len(attempts), 2)
        self.assertEqual((outcome.findings, outcome.stale), ((), (record.uid,)))
        self.assertEqual(self.input_row(record.uid)["status"], "discarded")
        self.assertEqual(len(self.logged(events.EventKind.INPUT_CHANGED)), 1)


class SourcesTest(CheckCase):
    def test_unreachable_source_is_not_a_change(self) -> None:
        """RF-008-13: una fuente borrada y otra de otro volumen sin su ubicación anotada en este
        equipo son «no localizables», con o sin hash pedido: no se leen, no cuentan como cambio,
        no se registra nada y se sigue con lo importado. Se comprueban las entradas activas
        pedidas (por uid, nombre o registro, en su orden y sin repetir: una descartada no se
        comprueba); una desconocida es un error para la persona."""
        record = self.import_boundary()
        pdf = self.sources / data.REPORT
        declarations = model.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
        request = builtin.DOCUMENT.request("document", declarations, {"main": pdf})
        stat = pdf.stat()
        far = self.register(model.InputSpec(
            "informe", "document", "res", builtin.DOCUMENT.id,
            files=[model.SourceFile(data.REPORT, "main", "external", ref_uid="ref-otro-equipo")],
            file_prints=[model.SourcePrint(hashing.sha256_file(pdf), size=stat.st_size,
                                           mtime_ns=stat.st_mtime_ns)],
            digest=readers.read_content(builtin.DOCUMENT, request),
            crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE,
        ))
        old = self.register(self.simple("antiguo", "document", NOT_APPLICABLE, NOT_APPLICABLE))
        self.write(lambda conn: registry.discard(conn, self.project, old.uid, "Equivocada"))
        self.target.unlink()
        before = self.snapshot()
        for mode in ("quick", "full"):
            with self.subTest(mode=mode):
                outcome = self.run_check(mode, [far.uid, old.uid, "Limites_v1", far])
                self.assertEqual(self.hashed, [])
                self.assertEqual([item.input_uid for item in outcome.findings],
                                 [far.uid, record.uid])
                for found, shown in zip(outcome.findings, (data.REPORT, SOURCE), strict=True):
                    self.assertEqual((found.verdict, found.status, found.warning, found.file),
                                     (Verdict.UNREACHABLE, Status.CURRENT, None, shown))
                self.assertEqual(outcome.warnings, ())
                self.assertEqual(outcome.notices[1], (
                    "No se encuentra la fuente de la entrada «Limites_v1» (Limites_v1.gpkg): no "
                    "localizable; se sigue con lo importado."))
                self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ProvenanceError) as caught:
            next(check.check_steps(self.project, ["Limites_v9"]))
        self.assertEqual(caught.exception.code, "core.input_unknown")

    def test_edited_prj_changes_the_input(self) -> None:
        """RF-008-09, RF-008-10 (spec §8: ASC cuyo ``.prj`` se editó): la entrada son todos sus
        ficheros; el prefiltro mira también el ``.prj``, el lector lo recibe con su papel y la
        entrada queda «cambiada»."""
        self.enterContext(readers_registered(ASC))
        asc = self.sources / "mdt.asc"
        prj = self.sources / "mdt.prj"
        asc.write_bytes(b"ncols 2\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n1 2\n")
        prj.write_bytes(b'PROJCS["ETRS89 / UTM zone 30N"]')
        declarations = model.input_declarations(ETRS89, REDNAP, {})
        sources = [registry.locate_source(path, self.project, self.userdata, role=role)
                   for path, role in ((asc, "main"), (prj, "sidecar"))]
        self.assertEqual(inputs.reader_roles(sources), ("main", "prj"))
        prints = [model.SourcePrint(hashing.sha256_file(path), size=path.stat().st_size,
                                    mtime_ns=path.stat().st_mtime_ns) for path in (asc, prj)]
        request = ASC.request("raster", declarations, {"main": asc, "prj": prj})
        record = self.register(model.InputSpec(
            "mdt", "raster", "res", ASC.id, files=sources, file_prints=prints,
            digest=readers.read_content(ASC, request), crs_h=ETRS89, crs_v=REDNAP,
        ))
        _ASC_ROLES.clear()
        self.assertEqual(self.finding(self.run_check(), record.uid).verdict, Verdict.UNCHANGED)
        prj.write_bytes(b'PROJCS["ED50 / UTM zone 30N"]')
        self.set_mtime(prj, step=5)
        outcome = self.run_check()
        self.assertEqual((self.hashed, _ASC_ROLES), (["mdt.asc"], [("main", "prj")]))
        found = self.finding(outcome, record.uid)
        self.assertEqual((found.verdict, found.status), (Verdict.CHANGED, Status.CHANGED))

    def test_project_table_input_is_checked_by_its_last_change(self) -> None:
        """RF-008-09: una entrada anclada a una tabla del proyecto (una capa creada desde QGIS)
        se comprueba por el ``last_change`` de su tabla: sin cambio no se hashea; con otro
        ``last_change`` se hashea y, si el contenido es el mismo, se anota como última
        comprobación; si cambió (una fila nueva), queda «cambiada» con la fecha de la tabla."""

        def create(conn: sqlite3.Connection) -> None:
            base.create_attribute_table(conn, MARKS, [base.ColumnDef("codigo", "TEXT")], MARKS)
            conn.executemany(f'INSERT INTO "{MARKS}" (codigo) VALUES (?)', [("M-1",), ("M-2",)])

        self.write(create)
        declarations = model.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
        request = builtin.GPKG_LAYER.request("table", declarations,
                                             {"main": self.project.database_path},
                                             {"layer": MARKS})
        digest = readers.read_content(builtin.GPKG_LAYER, request)
        record = self.register(model.InputSpec(
            "Marcas", "table", "res", GPKG,
            files=[model.SourceFile(MARKS, "main", "project_table")],
            file_prints=[model.SourcePrint(digest.data_sha256)], digest=digest,
            crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE, layer=MARKS, settings={"layer": MARKS},
        ))
        self.assertEqual(self.finding(self.run_check(), record.uid).verdict, Verdict.UNCHANGED)
        self.assertEqual(self.hashed, [])

        def qgis(sql: str, args: tuple[Any, ...]) -> None:
            conn = sqlite3.connect(self.project.database_path, isolation_level=None)
            try:
                conn.execute(sql, args)
            finally:
                conn.close()

        touched = "2026-10-01T08:00:00.000Z"
        qgis("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?", (touched, MARKS))
        now = self.later()
        outcome = self.run_check()
        self.assertEqual(self.hashed, [self.project.database_path.name])
        self.assertEqual(self.finding(outcome, record.uid).verdict, Verdict.SAME)
        (checked,) = self.files(record.uid)
        self.assertEqual((checked["checked_last_change"], checked["checked_at"],
                          checked["checked_size"]), (touched, now, None))
        qgis(f'INSERT INTO "{MARKS}" (codigo) VALUES (?)', ("M-3",))
        edited = "2026-10-02T09:15:00.000Z"
        qgis("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?", (edited, MARKS))
        found = self.finding(self.run_check(), record.uid)
        self.assertEqual((found.verdict, found.status), (Verdict.CHANGED, Status.CHANGED))
        self.assertTrue(found.warning.endswith(f"Fecha de la fuente: {_local(edited)}."))

    def test_public_api(self) -> None:
        """Plan §5.3.1: ``core.inputs`` reexporta la comprobación; los eventos nuevos son los
        de la lista del plan §5.2.3."""
        for name in ("check_steps", "CheckMode", "CheckOutcome", "InputFinding", "Verdict",
                     "Dependents", "Dependent", "reader_roles", "dependents"):
            with self.subTest(name=name):
                self.assertIn(name, inputs.__all__)
                self.assertIs(getattr(inputs, name), getattr(check, name))
        self.assertEqual((events.EventKind.INPUT_CHANGED.value,
                          events.EventKind.INPUT_RESTORED.value),
                         ("input_changed", "input_restored"))


if __name__ == "__main__":
    unittest.main()
