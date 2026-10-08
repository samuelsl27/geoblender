# SPDX-License-Identifier: GPL-3.0-or-later
"""Originales de las entradas (spec 008, T22; RF-008-14, RF-008-53; D-3 y D-18 de la spec;
plan 008 §5.2.2 y §5.4.8).

``core.inputs.store_originals_steps`` guarda en ``originals/<uid>/`` una copia inmutable de los
ficheros de una entrada tabular o documental con su huella, desde la copia verificada que hizo
su importación (``JobDir.copy_input`` de la 004), sin volver a leer la fuente: la mueve si está
en el volumen del proyecto o la copia por trozos medidos por tiempo si no. Por encima del límite
``core.original_copy_limit`` (200 MB, ADOPTADO «sin confirmar») no copia nada y avisa; de un
ráster o de una nube de puntos nunca guarda el original.

Cada prueba crea su proyecto sintético (esquema 2) con un reloj simulado, sus fuentes en una
carpeta junto a él y sus copias verificadas en la carpeta de un trabajo de la 004.
"""

from __future__ import annotations

import errno
import os
import stat
import time
import unittest
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support.provenance_checks import assert_source_untouched
from tests.support.timing import MAX_ATTEMPTS
from tests.support.trees import age_folders
from tests.unit.core.inputs.test_registry import (
    ETRS89,
    NOT_APPLICABLE,
    REDNAP,
    SOURCE,
    InputsCase,
)
from tests.support.package import import_geoblender

inputs = import_geoblender("core.inputs")
model = import_geoblender("core.inputs.model")
registry = import_geoblender("core.inputs.registry")
originals = import_geoblender("core.inputs.originals")
content = import_geoblender("core.content")
events = import_geoblender("core.project.events")
project_model = import_geoblender("core.project.model")
session_mod = import_geoblender("core.project.session")
params = import_geoblender("core.params")
core_defs = import_geoblender("core.params.core_defs")
messages = import_geoblender("core.provenance.messages")
hashing = import_geoblender("core.hashing")
paths = import_geoblender("core.paths")
errors = import_geoblender("core.errors")
base = import_geoblender("core.gpkg.base")
jobs_paths = import_geoblender("jobs.paths")

ProvenanceError = messages.ProvenanceError
BUDGET_S = 0.020  # ningún paso pasa de 20 ms (plan §2, «Dónde se ejecuta lo pesado»)
LIMIT_KEY = "core.original_copy_limit"
TOO_LARGE = ("El original de «Sondeos.mdb» (350 MB) pasa del límite de 200 MB: se guarda solo "
             "lo importado.")
DB_TABLES = ("gb_input", "gb_input_file", "gb_parameter", "gb_parameter_history", "gb_event")
ROW = b"S-000001;715000,125;4400000,250;352,40;120,50\n"


def _digest(label: str, kind: str, declarations: Any) -> Any:
    """Los hashes que da el importador de una fuente cuyos datos simula ``label``."""
    data_sha = hashing.sha256_bytes(label.encode("utf-8"))
    return content.ContentDigest(data_sha, content.content_sha256(kind, declarations, data_sha),
                                 content.NORMALIZER, SOURCE.id)


def _csv(size: int, seed: str = "S") -> bytes:
    """Un CSV de ``size`` bytes (filas repetidas, la última cortada)."""
    head = f"sondeo;este;norte;cota;profundidad;{seed}\n".encode()
    return (head + ROW * (size // len(ROW) + 1))[:size]


def _read_only(path: Path) -> bool:
    attributes = getattr(os.stat(path), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_READONLY", 0)) or not os.access(
        path, os.W_OK)


class OriginalsCase(InputsCase):
    """Un proyecto nuevo por prueba, con las definiciones de ``core`` registradas y una
    carpeta de trabajos de la 004 junto a él."""

    def setUp(self) -> None:
        super().setUp()
        if LIMIT_KEY not in params.DEFINITIONS:
            params.register_definitions(core_defs.DEFINITIONS)
            self.addCleanup(params.unregister_definitions, "core")
        self.jobs = self.tmp / "trabajos"
        self.made = 0

    # --- Ayudas -----------------------------------------------------------------------------

    def source(self, name: str, data: bytes, folder: str = "") -> Path:
        """Un fichero de ``fuentes/`` (o de una subcarpeta) con ``data``."""
        path = self.sources / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def job_copy(self, path: Path, stem: str = "fuente") -> Path:
        """La copia verificada (de solo lectura) que hace el trabajo de la importación."""
        self.made += 1
        job = jobs_paths.JobDir(self.jobs / f"20261008_093100_{self.made:06x}")
        return job.path / job.copy_input(path, stem)

    def spec(self, files: Sequence[Path], *, kind: str = "table", name: str | None = None,
             sizes: Sequence[int] | None = None, crs_h: Any = NOT_APPLICABLE,
             crs_v: Any = NOT_APPLICABLE, label: str | None = None) -> Any:
        """La entrada de ``files`` (el primero, el principal) junto al proyecto, con sus
        huellas reales, el tamaño ``sizes`` si se inyecta y hashes simulados."""
        chosen = name or files[0].stem
        located = [registry.locate_source(path, self.project, self.userdata,
                                          role="main" if index == 0 else "sidecar")
                   for index, path in enumerate(files)]
        prints = []
        for index, path in enumerate(files):
            found = path.stat()
            size = found.st_size if sizes is None else sizes[index]
            prints.append(model.SourcePrint(hashing.sha256_file(path), size=size,
                                            mtime_ns=found.st_mtime_ns))
        declarations = model.input_declarations(crs_h, crs_v, {})
        return model.InputSpec(chosen, kind, "res", SOURCE.id, files=located, file_prints=prints,
                               digest=_digest(label or chosen, kind, declarations),
                               crs_h=crs_h, crs_v=crs_v)

    def drive(self, steps: Iterator[Any]) -> tuple[Any, list[float]]:
        """Avanza los pasos hasta el final: su resultado y lo que tardó cada uno (también el
        último ``next``, que termina el generador)."""
        durations: list[float] = []
        outcome = None
        while True:
            start = time.perf_counter()
            try:
                step = next(steps)
            except StopIteration:
                durations.append(time.perf_counter() - start)
                return outcome, durations
            durations.append(time.perf_counter() - start)
            self.assertIsInstance(step, project_model.Progress)
            if step.result is not None:
                self.assertIsNone(outcome, "un solo paso lleva el resultado")
                outcome = step.result

    def store(self, record: Any, copies: Sequence[Path], **kw: Any) -> tuple[Any, list[float]]:
        return self.drive(originals.store_originals_steps(self.project, record, copies, **kw))

    def within_budget(self, durations: list[float], again: Callable[[], list[float]]) -> None:
        """Ningún paso pasa de :data:`BUDGET_S`; con la máquina cargada, se repite con una
        entrada nueva (como ``tests.support.timing.best_of``) hasta encontrar un momento
        tranquilo."""
        worst = max(durations)
        for _attempt in range(MAX_ATTEMPTS // 4):
            if worst <= BUDGET_S:
                break
            worst = min(worst, max(again()))
        self.assertLessEqual(worst, BUDGET_S, f"un paso tardó {worst * 1000:.1f} ms")

    def file_row(self, uid: str, ord_: int = 0) -> dict[str, Any]:
        return self.rows("gb_input_file", "input_uid = ? AND ord = ?", (uid, ord_))[0]

    def input_row(self, uid: str) -> dict[str, Any]:
        return self.rows("gb_input", "uid = ?", (uid,))[0]

    def folder(self, uid: str = "") -> Path:
        return self.project.root / "originals" / uid if uid else self.project.root / "originals"

    def db(self) -> list[Any]:
        with self.project.read() as conn:
            return [conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
                    for table in DB_TABLES]

    def limit(self) -> Any:
        return params.ParameterStore(self.project).get(LIMIT_KEY)


class StoreTest(OriginalsCase):
    def test_csv_original_stored_with_its_print(self) -> None:
        """RF-008-53, RF-008-14: el original de un CSV de 15 MB se guarda en
        ``originals/<uid>/`` con su nombre, su huella, su tamaño y la fecha de la fuente, sin
        atributo de solo lectura, moviendo (mismo volumen) la copia verificada de su
        importación y sin volver a leer la fuente (que ya es otra) ni escribir nada junto a
        ella; el límite queda registrado con su valor por defecto «sin confirmar» (D-18) y
        ningún paso pasa de 20 ms."""
        data = _csv(15_000_000)
        source = self.source("collares.csv", data)
        record = self.register(self.spec([source]))
        copy = self.job_copy(source, "collares")
        self.assertTrue(_read_only(copy))
        self.source("collares.csv", b"X" + data[1:])  # la fuente cambia: no se vuelve a leer
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            outcome, durations = self.store(record, [copy])

        stored = self.folder(record.uid) / "collares.csv"
        self.assertEqual(sorted(os.listdir(self.folder(record.uid))), ["collares.csv"])
        self.assertEqual(stored.read_bytes(), data)
        self.assertFalse(copy.exists(), "la copia verificada se mueve (mismo volumen)")
        self.assertFalse(_read_only(stored), "un original no lleva atributo de solo lectura")
        found = stored.stat()
        registered = record.files[0]
        self.assertEqual(found.st_mtime_ns, registered.mtime_ns)
        relative = f"originals/{record.uid}/collares.csv"
        self.assertEqual(
            {key: value for key, value in self.file_row(record.uid).items()
             if key.startswith("original_")},
            {"original_path": relative, "original_sha256": registered.sha256,
             "original_size": 15_000_000, "original_mtime_ns": found.st_mtime_ns},
        )
        self.assertEqual(self.input_row(record.uid)["original"], "stored")
        self.assertEqual(self.read(lambda conn: registry.get(conn, record.uid)).original,
                         model.OriginalState.STORED)
        self.assertEqual(outcome, originals.OriginalsOutcome(
            record.uid, record.name, model.OriginalState.STORED,
            files=(originals.StoredOriginal(0, "collares.csv", relative, registered.sha256,
                                            15_000_000, found.st_mtime_ns),),
            file="collares.csv", size=15_000_000, limit=200.0,
        ))
        self.assertIsNone(outcome.warning)
        limit = self.limit()
        self.assertEqual((limit.value, limit.unit, str(limit.kind), limit.unconfirmed),
                         (200.0, "MB", "ADOPTADO", True))
        self.assertEqual(self.logged(events.EventKind.ORIGINAL_NOT_STORED), [])
        self.assertGreater(len(durations), 4, "se copia por pasos")

        def again() -> list[float]:
            self.made += 1
            name = f"collares_{self.made}"
            again_record = self.register(self.spec([source], name=name))
            return self.store(again_record, [self.job_copy(source, name)])[1]

        self.within_budget(durations, again)

    def test_copied_by_chunks_from_another_volume(self) -> None:
        """RF-008-53, RF-008-14: si la copia verificada está en otro volumen (la carpeta de los
        trabajos en el disco local y el proyecto en la red), el original se copia por trozos
        medidos por tiempo con su huella, la copia queda donde estaba y no queda ningún
        temporal; si mover falla por ser otro volumen, también se copia; ningún paso pasa de
        20 ms."""
        data = _csv(3_000_000, seed="B")
        source = self.source("ensayos.csv", data)
        record = self.register(self.spec([source]))
        copy = self.job_copy(source, "ensayos")
        before = (copy.read_bytes(), copy.stat().st_mtime_ns)
        outcome, durations = self.store(record, [copy], same_volume=lambda first, second: False)
        stored = self.folder(record.uid) / "ensayos.csv"
        self.assertEqual(sorted(os.listdir(self.folder(record.uid))), ["ensayos.csv"])
        self.assertEqual(stored.read_bytes(), data)
        self.assertEqual((copy.read_bytes(), copy.stat().st_mtime_ns), before)
        self.assertTrue(_read_only(copy))
        self.assertFalse(_read_only(stored))
        self.assertEqual(stored.stat().st_mtime_ns, record.files[0].mtime_ns)
        row = self.file_row(record.uid)
        self.assertEqual((row["original_path"], row["original_sha256"], row["original_size"]),
                         (f"originals/{record.uid}/ensayos.csv", record.files[0].sha256,
                          3_000_000))
        self.assertEqual(outcome.state, model.OriginalState.STORED)

        def again() -> list[float]:
            self.made += 1
            name = f"ensayos_{self.made}"
            again_record = self.register(self.spec([source], name=name))
            return self.store(again_record, [self.job_copy(source, name)],
                              same_volume=lambda first, second: False)[1]

        self.within_budget(durations, again)

        # Mover entre volúmenes falla (EXDEV): se copia por trozos.
        moved = self.register(self.spec([source], name="ensayos_exdev"))
        other = self.job_copy(source, "exdev")
        real = originals._rename_new

        def rename(first: Path, second: Path) -> None:
            if Path(first) == other:
                raise OSError(errno.EXDEV, "no se puede mover a otra unidad", str(first))
            real(first, second)

        with mock.patch.object(originals, "_rename_new", side_effect=rename):
            outcome, _durations = self.store(moved, [other])
        self.assertEqual(outcome.state, model.OriginalState.STORED)
        self.assertTrue(other.exists())
        self.assertEqual((self.folder(moved.uid) / "ensayos.csv").read_bytes(), data)

    def test_too_large_is_not_stored(self) -> None:
        """RF-008-53 (D-18): con el tamaño inyectado, una base de 350 MB no se copia: la
        entrada queda «original no guardado» con el aviso exacto de la spec §8 (MB = 10⁶ B) y
        su evento, sin crear ``originals/`` ni tocar la copia verificada; en el límite se
        guarda y un byte más pasa de él; el límite que fija una persona manda."""
        source = self.source("Sondeos.mdb", b"\x00" * 4096)
        record = self.register(self.spec([source], kind="table", sizes=[350_000_000]))
        copy = self.job_copy(source, "sondeos")
        before = copy.read_bytes()
        outcome, durations = self.store(record, [copy])
        self.assertEqual(outcome.state, model.OriginalState.TOO_LARGE)
        self.assertEqual(outcome.warning, TOO_LARGE)
        self.assertEqual(outcome.render("en"), "The original of «Sondeos.mdb» (350 MB) exceeds "
                         "the limit of 200 MB: only the imported data is kept.")
        self.assertEqual((outcome.size, outcome.limit, outcome.files),
                         (350_000_000, 200.0, ()))
        self.assertIn("(352,4 MB)", originals.OriginalsOutcome(
            record.uid, "Sondeos", model.OriginalState.TOO_LARGE, file="Sondeos.mdb",
            size=352_418_816, limit=200.0).warning)
        self.assertEqual(self.input_row(record.uid)["original"], "too_large")
        self.assertIsNone(self.file_row(record.uid)["original_path"])
        self.assertFalse(self.folder().exists())
        self.assertEqual(copy.read_bytes(), before)
        self.assertLessEqual(len(durations), 2)
        logged = self.logged(events.EventKind.ORIGINAL_NOT_STORED)
        self.assertEqual([(item.entity_kind, item.entity_uid, item.message) for item in logged],
                         [("input", record.uid, TOO_LARGE)])
        self.assertEqual(logged[0].data, {
            "name": "Sondeos", "file": "Sondeos.mdb", "files": ["Sondeos.mdb"],
            "size_bytes": 350_000_000, "limit_bytes": 200_000_000, "limit_value": 200.0,
            "limit_unit": "MB",
        })
        self.assertTrue(self.limit().unconfirmed)

        # La persona fija 1 MB: 1 000 000 B se guarda y 1 000 001 B pasa del límite.
        self.write(lambda conn: params.ParameterStore(self.project).change(
            conn, LIMIT_KEY, value=1.0, unit="MB", source="Dirección facultativa",
            source_kind="person", decided_by="samuel@PC-01", reason="Solo originales pequeños",
        ))
        exact = self.source("limite.csv", _csv(1_000_000))
        over = self.source("pasa.csv", _csv(1_000_001))
        at_limit = self.register(self.spec([exact], label="limite"))
        outcome, _durations = self.store(at_limit, [self.job_copy(exact, "limite")])
        self.assertEqual((outcome.state, outcome.limit), (model.OriginalState.STORED, 1.0))
        past = self.register(self.spec([over], label="pasa"))
        outcome, _durations = self.store(past, [self.job_copy(over, "pasa")])
        self.assertEqual(outcome.warning, "El original de «pasa.csv» (1,000001 MB) pasa del "
                         "límite de 1 MB: se guarda solo lo importado.")
        self.assertEqual(self.input_row(past.uid)["original"], "too_large")

    def test_raster_and_point_cloud_never_stored(self) -> None:
        """RF-008-53 (D-3): de un ráster (un ASC con su ``.prj``) o de una nube de puntos
        nunca se guarda el original, ni aunque se declaren tabulares; un vectorial tampoco,
        salvo que su importador lo declare tabular, ni una tabla del proyecto; nada de ello
        escribe en la base ni crea ``originals/``; unos sondeos de un CSV declarados
        tabulares, sí."""
        grid = self.source("mdt.asc", b"ncols 2\nnrows 2\n")
        prj = self.source("mdt.prj", b"PROJCS[...]\n")
        cloud = self.source("nube.laz", b"LASF" + b"\x00" * 64)
        layer = self.source("limite.csv", _csv(200, seed="L"))
        raster = self.register(self.spec([grid, prj], kind="raster", crs_h=ETRS89))
        points = self.register(self.spec([cloud], kind="point_cloud", crs_h=ETRS89,
                                         crs_v=REDNAP))
        vector = self.register(self.spec([layer], kind="vector", crs_h=ETRS89, label="v"))
        copies = {
            raster.uid: [self.job_copy(grid, "mdt"), self.job_copy(prj, "mdt")],
            points.uid: [self.job_copy(cloud, "nube")],
            vector.uid: [self.job_copy(layer, "limite")],
        }
        before = self.db()
        for record, tabular in ((raster, None), (points, None), (vector, None),
                                (vector, False)):
            with self.subTest(kind=record.kind, tabular=tabular):
                outcome, durations = self.store(record, copies[record.uid], tabular=tabular)
                self.assertEqual((outcome.state, outcome.files, outcome.warning),
                                 (model.OriginalState.NOT_APPLICABLE, (), None))
                self.assertLessEqual(len(durations), 2)
        for record in (raster, points):
            with self.subTest(declared=record.kind), self.assertRaises(ValueError):
                self.store(record, copies[record.uid], tabular=True)
        self.assertEqual(self.db(), before)
        self.assertFalse(self.folder().exists())
        for found in copies.values():
            for copy in found:
                self.assertTrue(copy.exists())
        self.assertIsNone(self.limit())

        # Una tabla del proyecto (creada desde QGIS) no tiene fichero que guardar.
        self.write(lambda conn: base.create_attribute_table(
            conn, "res_qgis", [base.ColumnDef("codigo", "TEXT")], "Capa de QGIS"))
        table = self.register(model.InputSpec(
            "res_qgis", "table", "res", SOURCE.id,
            files=[model.SourceFile("res_qgis", "main", "project_table")],
            file_prints=[model.SourcePrint(hashing.sha256_bytes(b"res_qgis"))],
            digest=_digest("res_qgis", "table", model.input_declarations(
                NOT_APPLICABLE, NOT_APPLICABLE, {})),
            crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE,
        ))
        outcome, _durations = self.store(table, [])
        self.assertEqual(outcome.state, model.OriginalState.NOT_APPLICABLE)

        # Unos sondeos de un CSV, declarados tabulares por su importador.
        holes = self.register(self.spec([layer], kind="drillholes", name="bocas", crs_h=ETRS89,
                                        crs_v=REDNAP, label="bocas"))
        outcome, _durations = self.store(holes, [self.job_copy(layer, "bocas")], tabular=True)
        self.assertEqual(outcome.state, model.OriginalState.STORED)
        self.assertEqual(self.input_row(holes.uid)["original"], "stored")

    def test_names_kept_within_path_limit(self) -> None:
        """RF-008-53 (plan §5.2.2): dos ficheros con el mismo nombre se guardan como
        ``<nombre>`` y ``<ord>_<nombre>``; un nombre que pasaría del límite de rutas de
        Windows se guarda recortado como ``<ord>_<nombre recortado>`` con su extensión, y el
        nombre completo sigue en la base."""
        first = self.source("informe.pdf", b"%PDF-1.7 a\n", folder="a")
        second = self.source("informe.pdf", b"%PDF-1.7 b\n", folder="b")
        order = self.register(self.spec([first, second], kind="document", name="encargo"))
        outcome, _durations = self.store(order, [self.job_copy(first, "a"),
                                                 self.job_copy(second, "b")])
        self.assertEqual([item.path.rsplit("/", 1)[1] for item in outcome.files],
                         ["informe.pdf", "1_informe.pdf"])
        self.assertEqual(sorted(os.listdir(self.folder(order.uid))),
                         ["1_informe.pdf", "informe.pdf"])
        self.assertEqual((self.folder(order.uid) / "1_informe.pdf").read_bytes(),
                         b"%PDF-1.7 b\n")

        folder = self.folder("0" * 36)
        room = paths.MAX_FILE_PATH_CHARS - len(os.path.abspath(folder)) - 1
        long_name = "Campaña de sondeos " + "x" * (room - 20 - len(".csv")) + ".csv"
        self.assertGreater(len(long_name), room - len(".tmp-12345678"))
        self.assertLess(len(os.path.abspath(self.sources / long_name)), paths.MAX_FILE_PATH_CHARS)
        source = self.source(long_name, _csv(500, seed="C"))
        record = self.register(self.spec([source], name="campana"))
        outcome, _durations = self.store(record, [self.job_copy(source, "campana")])
        (item,) = outcome.files
        stored_name = item.path.rsplit("/", 1)[1]
        self.assertTrue(stored_name.startswith("0_Campaña de sondeos xxx"), stored_name)
        self.assertTrue(stored_name.endswith(".csv"))
        full = self.folder(record.uid) / stored_name
        self.assertLessEqual(len(os.path.abspath(full)) + len(".tmp-12345678"),
                             paths.MAX_FILE_PATH_CHARS)
        self.assertEqual(full.read_bytes(), _csv(500, seed="C"))
        self.assertEqual(item.name, long_name)
        self.assertTrue(self.file_row(record.uid)["path"].endswith("/" + long_name))


class RejectTest(OriginalsCase):
    def refused_store(self, error: type[BaseException], code: str | None, record: Any,
                      copies: Sequence[Path], **kw: Any) -> BaseException:
        """Guardar se rechaza sin escribir nada en la base ni en ``originals/`` y sin tocar las
        copias verificadas."""
        before = self.db()
        listing = sorted(str(path) for path in self.folder().rglob("*")) \
            if self.folder().exists() else None
        watched = [] if isinstance(copies, str) else [Path(copy) for copy in copies]
        copied = [(copy, copy.read_bytes()) for copy in watched if copy.exists()]
        with self.assertRaises(error) as caught:
            self.store(record, copies, **kw)
        if code is not None:
            self.assertEqual(getattr(caught.exception, "code", None), code,
                             str(caught.exception))
        self.assertEqual(self.db(), before)
        after = sorted(str(path) for path in self.folder().rglob("*")) \
            if self.folder().exists() else None
        self.assertEqual(after, listing)
        for copy, data in copied:
            self.assertEqual(copy.read_bytes(), data)
            self.assertTrue(_read_only(copy))
        return caught.exception

    def test_checked_before_writing(self) -> None:
        """RF-008-53, RF-008-14: una entrada desconocida, una copia verificada que falta, que
        no tiene el tamaño o la huella registrados, otro número de copias, un fichero que ya
        está en su sitio de ``originals/`` (no se sobrescribe), un original ya guardado o un
        proyecto en solo lectura se rechazan sin escribir nada ni tocar las copias."""
        data = _csv(600_000, seed="R")
        source = self.source("collares.csv", data)
        record = self.register(self.spec([source]))
        copy = self.job_copy(source, "collares")

        unknown = self.refused_store(ProvenanceError, "core.input_unknown",
                                     "00000000-0000-4000-8000-0000000002ff", [copy])
        self.assertIn("00000000-0000-4000-8000-0000000002ff", str(unknown))
        missing = self.refused_store(ProvenanceError, "core.original_copy_missing", record,
                                     [self.jobs / "no_existe.csv"])
        self.assertEqual(str(missing), "Falta la copia verificada de «collares.csv» de la "
                         "entrada «collares»: no se guarda su original; vuelva a importarla.")
        self.refused_store(ValueError, None, record, [copy, copy])
        self.refused_store(ValueError, None, record, [])
        self.refused_store(TypeError, None, record, str(copy))
        self.refused_store(ValueError, None, record, [Path("relativa.csv")])

        shorter = self.job_copy(self.source("corto.csv", data[:-1]), "corto")
        self.refused_store(ProvenanceError, "core.original_copy_mismatch", record, [shorter])
        other = self.job_copy(self.source("otro.csv", b"Y" + data[1:]), "otro")
        for same_volume in (None, lambda first, second: False):
            with self.subTest(same_volume=same_volume):
                mismatch = self.refused_store(ProvenanceError, "core.original_copy_mismatch",
                                              record, [other], same_volume=same_volume)
                self.assertEqual(str(mismatch), "La copia verificada de «collares.csv» de la "
                                 "entrada «collares» no coincide con su huella registrada: no "
                                 "se guarda su original; vuelva a importarla.")
        self.assertFalse(self.folder().exists(), "no queda ninguna carpeta vacía")

        leftover = self.folder(record.uid) / "collares.csv"
        leftover.parent.mkdir(parents=True)
        leftover.write_bytes(b"resto")
        exists = self.refused_store(ProvenanceError, "core.original_exists", record, [copy])
        self.assertEqual(str(exists), f"Ya hay un fichero «originals/{record.uid}/collares.csv» "
                         "en los originales del proyecto: no se sobrescribe.")
        self.assertEqual(leftover.read_bytes(), b"resto")
        leftover.unlink()
        leftover.parent.rmdir()
        self.folder().rmdir()

        outcome, _durations = self.store(record, [copy])
        self.assertEqual(outcome.state, model.OriginalState.STORED)
        self.refused_store(ValueError, None, record, [copy])

        self.project.set_read_only(project_model.ReadOnlyCode.LOCK_LOST, "otra sesión")
        read_only = self.refused_store(ProvenanceError, "core.read_only", record.uid, [copy])
        self.assertIn(self.project.name, str(read_only))

    def test_cancel_and_busy_leave_nothing_half_done(self) -> None:
        """RF-008-53, RF-008-14: parar la copia a medias (por trozos o moviendo) no deja nada
        en ``originals/`` ni en la base y la copia verificada queda donde y como estaba; con
        otro programa leyendo el proyecto, el registro se reintenta en el paso siguiente; y
        después se guarda igual."""
        data = _csv(3_000_000, seed="K")
        source = self.source("collares.csv", data)
        record = self.register(self.spec([source]))
        copy = self.job_copy(source, "collares")
        before = self.db()
        for same_volume in (lambda first, second: False, None):
            with self.subTest(same_volume=same_volume):
                steps = originals.store_originals_steps(self.project, record, [copy],
                                                        same_volume=same_volume,
                                                        budget_s=0.002)
                for _step in range(3):
                    next(steps)
                steps.close()
                self.assertFalse(self.folder().exists())
                self.assertEqual(self.db(), before)
                self.assertEqual(copy.read_bytes(), data)
                self.assertTrue(_read_only(copy))

        busy = session_mod.WriteAttempt(session_mod.WriteState.RETRYING, None,
                                        session_mod.BUSY_MESSAGE)
        real = self.project.try_write
        calls: list[int] = []

        def try_write(work: Callable[[Any], Any]) -> Any:
            calls.append(1)
            return busy if len(calls) == 1 else real(work)

        steps = originals.store_originals_steps(self.project, record, [copy])
        messages_seen: list[str] = []
        with mock.patch.object(self.project, "try_write", side_effect=try_write):
            outcome = None
            for step in steps:
                messages_seen.append(step.message)
                outcome = step.result or outcome
        self.assertIn(session_mod.BUSY_MESSAGE, messages_seen)
        self.assertEqual(len(calls), 2)
        self.assertEqual(outcome.state, model.OriginalState.STORED)
        self.assertEqual((self.folder(record.uid) / "collares.csv").read_bytes(), data)

        # Si el registro falla con los ficheros ya en su sitio, se deshace.
        again = self.register(self.spec([source], name="collares_2", label="collares_2"))
        other = self.job_copy(source, "collares_2")
        failing = mock.patch.object(self.project, "try_write",
                                    side_effect=OSError(errno.EIO, "red caída"))
        with failing, self.assertRaises(OSError):
            self.store(again, [other])
        self.assertFalse(self.folder(again.uid).exists())
        self.assertEqual(other.read_bytes(), data)
        self.assertTrue(_read_only(other))
        self.assertEqual(self.input_row(again.uid)["original"], "not_applicable")


class VocabularyTest(unittest.TestCase):
    def test_messages_events_and_api(self) -> None:
        """RF-008-53 (plan §5.2.3 y §5.3.1): el evento ``original_not_stored``, los mensajes
        ``core.original_*`` en español con su ``msgid`` y la API reexportada en
        ``core.inputs``."""
        self.assertEqual(events.EventKind.ORIGINAL_NOT_STORED.value, "original_not_stored")
        for code in ("core.original_too_large", "core.original_copy_missing",
                     "core.original_copy_mismatch", "core.original_exists",
                     "core.original_copy_failed"):
            with self.subTest(code=code):
                self.assertIn(code, messages.MESSAGES)
        for name in ("store_originals_steps", "OriginalsOutcome", "StoredOriginal",
                     "ORIGINAL_COPY_LIMIT"):
            with self.subTest(name=name):
                self.assertIn(name, inputs.__all__)
                self.assertIs(getattr(inputs, name), getattr(originals, name))
        self.assertEqual(originals.ORIGINAL_COPY_LIMIT, LIMIT_KEY)
        self.assertIn(LIMIT_KEY, {defn.key for defn in core_defs.DEFINITIONS})


if __name__ == "__main__":
    unittest.main()
