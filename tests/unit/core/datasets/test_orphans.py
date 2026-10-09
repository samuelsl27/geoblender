# SPDX-License-Identifier: GPL-3.0-or-later
"""Restos de operaciones interrumpidas (spec 008, T33; RF-008-22; D-19 de la spec; ADR-0025 §3
y §8; plan 008 §5.2.2, §5.3.1, §5.4.6 y §5.4.9).

``core.datasets.orphans.orphan_steps`` busca, al abrir un proyecto, en ``rasters/``,
``meshes/`` y ``originals/`` los ficheros con nombre de los módulos (``<código>_<nombre>.<ext>``,
``*.tmp-<sesión>``, ``*__<hash8>.<ext>``) y las carpetas ``originals/<uid>`` que no son de
ningún dato registrado, de ninguna entrada ni la fuente de una entrada guardada en el proyecto,
y los aparta a ``orphans/<AAAAMMDDTHHMMSSZ>_<sesión8>/`` con su ruta, avisando con la lista:

- nada se borra; lo que otro programa tiene abierto se salta y se reintenta la vez siguiente;
- no se toca lo que reclama una operación en curso de esta sesión ni lo escrito o cambiado
  después de empezar (tampoco lo registrado entre dos pasos);
- en solo lectura solo se avisa.

Cada prueba crea su proyecto sintético (esquema 2) con un reloj simulado (el de
``test_registry``): la carpeta de restos de la pasada es
``orphans/20261005T081244Z_00000001``. Los restos se escriben con una fecha de hace una hora
(los de una sesión anterior que se cayó).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any
from unittest import mock

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.provenance_readers import registered as readers_registered
from tests.unit.core.inputs.test_registry import (
    ETRS89,
    MTIME_NS,
    NOT_APPLICABLE,
    SOURCE,
    InputsCase,
    _digest,
)

orphans = import_geoblender("core.datasets.orphans")
datasets = import_geoblender("core.datasets")
inputs_model = import_geoblender("core.inputs.model")
provenance = import_geoblender("core.provenance")
operations = import_geoblender("core.provenance.operations")
messages = import_geoblender("core.provenance.messages")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
events = import_geoblender("core.project.events")
project_model = import_geoblender("core.project.model")
session_mod = import_geoblender("core.project.session")
hashing = import_geoblender("core.hashing")

State = orphans.OrphanState


def _read_bytes(request: Any) -> Iterator[float]:
    """Un lector de prueba de rejillas y mallas: los bytes del fichero."""
    yield from builtin.read_document(request)


BYTES = readers.ContentReader("test.orphan_bytes", 1, ("raster", "mesh"), False, False, None,
                              _read_bytes)
WRITE = provenance.OperationDef("res.write_files", "1.0", "res", "Test files", False)
STAMP_DIR = "orphans/20261005T081244Z_00000001"
"""La carpeta de restos de la pasada: la hora del reloj simulado y la sesión de prueba."""
AGE_NS = 3600 * 10**9
UNKNOWN_UID = "6f1c2d3e-4b5a-4c6d-8e7f-0a1b2c3d4e5f"
"""La carpeta de los originales de una entrada que no llegó a registrarse."""
DATA_FOLDERS = ("rasters", "meshes", "originals", "orphans")
MOVED_TEXT = ("Restos de operaciones interrumpidas apartados a «{folder}» (no se borra nada): "
              "{files}.")
LOCKED_TEXT = ("Restos abiertos en otro programa, sin apartar: {files}. Se reintentará al abrir "
               "el proyecto la próxima vez.")
FOUND_TEXT = ("Restos de operaciones interrumpidas en el proyecto: {files}. En solo lectura no "
              "se apartan: se apartarán al abrirlo en escritura.")


def _quoted(*paths: str) -> str:
    return ", ".join(f"«{path}»" for path in paths)


def _file_spec(locator: str) -> Any:
    """El dato de prueba del fichero ``locator`` (``rasters/…`` o ``meshes/…``)."""
    store = locator.split("/", 1)[0]
    stem = PurePosixPath(locator).name.split(".")[0]
    return datasets.DatasetSpec(stem, "res", "raster" if store == "rasters" else "mesh", store,
                                locator, reader=BYTES.id, role=stem)


class OrphansCase(InputsCase):
    """El proyecto de ``test_registry`` con un tipo de operación que escribe ficheros en
    ``rasters/`` y ``meshes/`` y su lector."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(registered(WRITE))
        self.enterContext(readers_registered(BYTES))
        self.root = Path(self.project.root)

    # --- Ayudas -----------------------------------------------------------------------------

    def path(self, rel: str) -> Path:
        return self.root.joinpath(*rel.split("/"))

    def put(self, rel: str, data: bytes | None = None, *, recent: bool = False) -> Path:
        """Escribe ``rel`` (por defecto, con su ruta como contenido) con la fecha de hace una
        hora; con ``recent``, con la de ahora."""
        path = self.path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rel.encode("utf-8") if data is None else data)
        if not recent:
            old = time.time_ns() - AGE_NS
            os.utime(path, ns=(old, old))
        return path

    def start(self) -> Any:
        """Una operación en curso de esta sesión que escribe ficheros."""
        return operations.begin_operation(self.project, WRITE.op_type, settings={},
                                          executor="blender")

    def produce(self, *locators: str) -> Any:
        """Registra como datos de una operación los ficheros ``locators`` (ya escritos)."""
        handle = self.start()
        return self.write(lambda conn: handle.complete(
            conn, outputs=[_file_spec(locator) for locator in locators]))

    def project_source(self, name: str, kind: str, rel: str, crs_h: Any = ETRS89) -> Any:
        """Una entrada cuya fuente es el fichero ``rel``, dentro del proyecto (ancla
        ``project``)."""
        data = self.path(rel).read_bytes()
        declarations = inputs_model.input_declarations(crs_h, NOT_APPLICABLE, {})
        return self.register(inputs_model.InputSpec(
            name, kind, "res", SOURCE.id,
            files=[inputs_model.SourceFile(rel, "main", "project")],
            file_prints=[inputs_model.SourcePrint(hashing.sha256_bytes(data), size=len(data),
                                                  mtime_ns=MTIME_NS)],
            digest=_digest(name, kind, declarations), crs_h=crs_h, crs_v=NOT_APPLICABLE,
        ))

    def stored_original(self, input_uid: str, name: str, data: bytes) -> None:
        """El original guardado de la entrada ``input_uid``, como lo deja
        ``store_originals_steps``."""
        path = self.put(f"originals/{input_uid}/{name}", data)
        found = path.stat()
        self.write(lambda conn: conn.execute(
            "UPDATE gb_input_file SET original_path = ?, original_sha256 = ?, original_size = ?, "
            "original_mtime_ns = ? WHERE input_uid = ?",
            (f"originals/{input_uid}/{name}", hashing.sha256_bytes(data), found.st_size,
             found.st_mtime_ns, input_uid)))

    def steps(self, **kw: Any) -> list[Any]:
        kw.setdefault("write", True)
        found = list(orphans.orphan_steps(self.project, **kw))
        for step in found:
            self.assertIsInstance(step, project_model.Progress)
        self.assertIsInstance(found[-1].result, orphans.OrphanOutcome)
        return found

    def listed(self, steps: Iterator[Any]) -> Any:
        """Avanza los pasos hasta el final del listado, sin apartar aún nada (los pasos de en
        medio del listado no tienen total)."""
        for step in steps:
            if step.phase == orphans.PHASES[0] and step.done == step.total:
                return step
        self.fail("el barrido terminó sin acabar el listado")

    def sweep(self, **kw: Any) -> Any:
        """Todos los pasos del barrido; su resultado."""
        return self.steps(**kw)[-1].result

    def files(self) -> dict[str, str]:
        """El sha256 de cada fichero de las carpetas de datos y de ``orphans/``, por su ruta."""
        found: dict[str, str] = {}
        for folder in DATA_FOLDERS:
            for path in sorted(self.path(folder).rglob("*")):
                if path.is_file():
                    found[path.relative_to(self.root).as_posix()] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
        return found

    def assertNothingDeleted(self, before: dict[str, str], after: dict[str, str]) -> None:
        """Los mismos contenidos antes y después (solo cambian de sitio)."""
        self.assertEqual(sorted(before.values()), sorted(after.values()))

    def by_state(self, outcome: Any, state: Any) -> dict[str, Any]:
        return {item.path: item for item in outcome.orphans if item.state is state}

    def moved(self, outcome: Any) -> dict[str, str]:
        return {path: item.moved_to for path, item in self.by_state(outcome, State.MOVED).items()}

    def logged(self, kind: Any = None) -> list[Any]:
        return super().logged(events.EventKind.ORPHANS_MOVED if kind is None else kind)

    def table_state(self) -> list[Any]:
        with self.project.read() as conn:
            return [conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
                    for table in ("gb_event", "gb_dataset", "gb_input", "gb_input_file",
                                  "gb_operation")]


class MoveTest(OrphansCase):
    def test_geoblender_named_leftovers_go_to_orphans_with_their_path(self) -> None:
        """RF-008-22 (spec §8, «Blender se cierra durante una operación»): los ficheros con
        nombre de los módulos de ``rasters/``, ``meshes/`` y ``originals/`` (también en una
        subcarpeta, un temporal de otra sesión y una carpeta ``originals/<uid>`` sin entrada)
        que no son de ningún dato acaban en ``orphans/<fecha>_<sesión>/`` con su ruta y el aviso
        con la lista, con su evento; de la carpeta de una entrada registrada se aparta solo
        el temporal. Lo registrado (también lo descartado y un original guardado, aunque se
        llame como un dato), lo que acompaña a un dato (``.aux.xml``), el temporal de esta
        sesión y lo que no lleva nombre de los módulos se quedan; nada se borra, y una segunda
        pasada no encuentra nada."""
        self.put("rasters/res_mdt.bin")
        self.put("meshes/res_malla.npz")
        self.produce("rasters/res_mdt.bin", "meshes/res_malla.npz")
        discarded = self.read(lambda conn: datasets.get(conn, "res_malla"))
        self.write(lambda conn: datasets.set_status(conn, self.project, discarded.uid,
                                                    datasets.DatasetStatus.DISCARDED))
        report = self.register(self.simple("informe", "document", NOT_APPLICABLE,
                                           NOT_APPLICABLE))
        self.stored_original(report.uid, "res_informe.pdf", b"%PDF-1.7 informe")
        plans = self.register(self.simple("planos", "document", NOT_APPLICABLE,
                                          NOT_APPLICABLE))
        leftovers = sorted((
            "meshes/geo_superficie.npz.tmp-deadbeef",
            f"originals/{report.uid}/res_informe.pdf.tmp-cafe0001",
            f"originals/{plans.uid}/plano.dxf.tmp-cafe0002",
            f"originals/{UNKNOWN_UID}",
            "rasters/res_resto.tif",
            "rasters/sub/mdt_viejo__0a1b2c3d.tif",
        ), key=str.casefold)
        for rel in leftovers:
            if rel.startswith(f"originals/{UNKNOWN_UID}"):
                self.put(f"{rel}/plano.dxf")
                self.put(f"{rel}/memoria/plano.txt")
            else:
                self.put(rel)
        staying = ("rasters/res_mdt.bin.aux.xml", "rasters/res_nuevo.tif.tmp-00000001",
                   "rasters/Mapa del cliente.tif", "originals/notas/leeme.txt")
        for rel in staying:
            self.put(rel)
        before = self.files()

        outcome = self.sweep()

        self.assertEqual(self.moved(outcome),
                         {rel: f"{STAMP_DIR}/{rel}" for rel in leftovers})
        self.assertEqual(outcome.folder, STAMP_DIR)
        self.assertTrue(outcome.recorded)
        self.assertEqual(outcome.stale, ())
        after = self.files()
        self.assertNothingDeleted(before, after)
        for rel in leftovers:
            self.assertFalse(self.path(rel).exists(), rel)
        self.assertEqual(after[f"{STAMP_DIR}/rasters/sub/mdt_viejo__0a1b2c3d.tif"],
                         before["rasters/sub/mdt_viejo__0a1b2c3d.tif"])
        self.assertEqual(after[f"{STAMP_DIR}/originals/{UNKNOWN_UID}/memoria/plano.txt"],
                         before[f"originals/{UNKNOWN_UID}/memoria/plano.txt"])
        for rel in ("rasters/res_mdt.bin", "meshes/res_malla.npz",
                    f"originals/{report.uid}/res_informe.pdf", *staying):
            self.assertEqual(after[rel], before[rel], rel)
        shown = [f"{rel}/" if rel == f"originals/{UNKNOWN_UID}" else rel for rel in leftovers]
        expected = MOVED_TEXT.format(folder=STAMP_DIR, files=_quoted(*shown))
        self.assertEqual(outcome.warnings, (expected,))
        self.assertIn(STAMP_DIR, outcome.texts("en")[0])
        (event,) = self.logged()
        self.assertEqual(event.message, expected)
        self.assertIsNone(event.entity_kind)
        self.assertEqual(event.data["folder"], STAMP_DIR)
        self.assertEqual(event.data["moved"],
                         [[rel, f"{STAMP_DIR}/{rel}"] for rel in leftovers])
        self.assertEqual(event.data["not_moved"], [])

        again = self.sweep()
        self.assertEqual(again.orphans, ())
        self.assertEqual(again.warnings, ())
        self.assertIsNone(again.folder)
        self.assertFalse(again.recorded)
        self.assertEqual(len(self.logged()), 1)
        self.assertEqual(self.files(), after)

    def test_source_of_an_input_inside_the_project_is_never_moved(self) -> None:
        """RF-008-22, RF-008-14 (spec §8, «Fuente de una entrada guardada dentro de la carpeta
        del proyecto»): la fuente de una entrada que está dentro del proyecto, aunque lleve
        nombre de los módulos o esté en una carpeta ``originals/<uid>`` sin entrada, no se
        aparta ni se toca (tampoco lo que la acompaña); lo demás de esa carpeta, sí."""
        self.put("rasters/res_fuente.tif", b"II*\x00 fuente")
        self.put("rasters/res_fuente.tif.aux.xml")
        self.put(f"originals/{UNKNOWN_UID}/plano.dxf", b"0\nSECTION\n")
        self.project_source("fuente", "raster", "rasters/res_fuente.tif")
        self.project_source("plano", "document", f"originals/{UNKNOWN_UID}/plano.dxf",
                            crs_h=NOT_APPLICABLE)
        leftover = f"originals/{UNKNOWN_UID}/plano.dxf.tmp-deadbeef"
        self.put(leftover)
        before = self.files()

        outcome = self.sweep()

        self.assertEqual(self.moved(outcome), {leftover: f"{STAMP_DIR}/{leftover}"})
        after = self.files()
        self.assertNothingDeleted(before, after)
        for rel in ("rasters/res_fuente.tif", "rasters/res_fuente.tif.aux.xml",
                    f"originals/{UNKNOWN_UID}/plano.dxf"):
            self.assertEqual(after[rel], before[rel], rel)


class LockedTest(OrphansCase):
    def test_locked_leftover_is_skipped_and_retried_at_next_opening(self) -> None:
        """RF-008-22 (spec §8, «Resto de una operación interrumpida abierto en QGIS»): un
        resto abierto en otro programa (un fichero, o uno de una carpeta de originales sin
        entrada) se salta sin fallar y queda en el aviso «se reintentará» y en el evento; los
        demás se apartan. Al abrir otra vez, ya cerrado, se aparta; un resto con la ruta de
        uno ya apartado en la misma carpeta no lo sustituye: nada se borra."""
        self.put("rasters/res_a.tif")
        self.put("rasters/res_b.tif")
        self.put(f"originals/{UNKNOWN_UID}/plano.dxf")
        before = self.files()
        with open(self.path("rasters/res_a.tif"), "rb"), \
                open(self.path(f"originals/{UNKNOWN_UID}/plano.dxf"), "rb"):
            outcome = self.sweep()

        self.assertEqual(self.moved(outcome),
                         {"rasters/res_b.tif": f"{STAMP_DIR}/rasters/res_b.tif"})
        self.assertEqual(set(self.by_state(outcome, State.LOCKED)),
                         {"rasters/res_a.tif", f"originals/{UNKNOWN_UID}"})
        self.assertEqual(outcome.retry, tuple(sorted(self.by_state(outcome, State.LOCKED).values(),
                                                     key=lambda item: item.path)))
        self.assertEqual(outcome.warnings, (
            MOVED_TEXT.format(folder=STAMP_DIR, files=_quoted("rasters/res_b.tif")),
            LOCKED_TEXT.format(files=_quoted(f"originals/{UNKNOWN_UID}/", "rasters/res_a.tif")),
        ))
        self.assertTrue(self.path("rasters/res_a.tif").exists())
        self.assertNothingDeleted(before, self.files())
        (event,) = self.logged()
        self.assertEqual(event.data["not_moved"], [
            [f"originals/{UNKNOWN_UID}", "locked", "abierto en otro programa"],
            ["rasters/res_a.tif", "locked", "abierto en otro programa"],
        ])

        self.put("rasters/res_b.tif", b"otro resto con la misma ruta")
        before = self.files()
        again = self.sweep()
        self.assertEqual(self.moved(again), {
            "rasters/res_a.tif": f"{STAMP_DIR}/rasters/res_a.tif",
            "rasters/res_b.tif": f"{STAMP_DIR}/rasters/res_b~2.tif",
            f"originals/{UNKNOWN_UID}": f"{STAMP_DIR}/originals/{UNKNOWN_UID}",
        })
        self.assertEqual(again.retry, ())
        after = self.files()
        self.assertNothingDeleted(before, after)
        self.assertEqual(after[f"{STAMP_DIR}/rasters/res_b.tif"], hashlib.sha256(
            b"rasters/res_b.tif").hexdigest())
        self.assertEqual(len(self.logged()), 2)


class LaterWritesTest(OrphansCase):
    def test_claimed_paths_and_writes_after_the_start_are_not_moved(self) -> None:
        """RF-008-22 (plan §5.4.6, I-5): entre dos pasos del barrido, esta sesión escribe un
        fichero nuevo, reescribe un resto, registra otro como dato y empieza una operación que
        reclama un cuarto, y otro programa deja en lugar de un quinto otro contenido con la
        fecha de antes: ninguno se aparta (quedan para la próxima), ni lo que reclamaba
        desde el principio una operación en curso de esta sesión; solo el resto que nadie
        tocó. Cuando esas operaciones terminan, sus rutas ya no están reclamadas y se
        apartan."""
        for rel in ("rasters/res_a.tif", "rasters/res_b.tif", "meshes/res_c.npz",
                    "rasters/res_d.tif.tmp", "rasters/res_e.tif", "rasters/res_f.tif"):
            self.put(rel)
        running = self.start()
        running.claim_paths("rasters/res_e.tif")
        steps = orphans.orphan_steps(self.project, write=True)
        self.assertEqual(self.listed(steps).total, 5)

        self.put("rasters/res_tarde.tif", recent=True)
        self.put("rasters/res_b.tif", b"reescrito", recent=True)
        self.put("rasters/res_f.tif", b"otro contenido con la fecha de antes")
        self.produce("meshes/res_c.npz")
        later = self.start()
        later.claim_paths("rasters/res_d.tif.tmp")
        outcome = list(steps)[-1].result

        self.assertEqual(self.moved(outcome),
                         {"rasters/res_a.tif": f"{STAMP_DIR}/rasters/res_a.tif"})
        self.assertEqual(set(outcome.stale), {"rasters/res_b.tif", "meshes/res_c.npz",
                                              "rasters/res_d.tif.tmp", "rasters/res_f.tif"})
        for rel in ("rasters/res_b.tif", "meshes/res_c.npz", "rasters/res_d.tif.tmp",
                    "rasters/res_e.tif", "rasters/res_f.tif", "rasters/res_tarde.tif"):
            self.assertTrue(self.path(rel).exists(), rel)

        running.fail("prueba: la operación termina")
        later.fail("prueba: la operación termina")
        again = self.sweep()
        self.assertEqual(set(self.moved(again)),
                         {"rasters/res_d.tif.tmp", "rasters/res_e.tif", "rasters/res_f.tif"})
        self.assertEqual(set(again.stale), {"rasters/res_b.tif", "rasters/res_tarde.tif"})
        self.assertTrue(self.path("meshes/res_c.npz").exists())

    def test_changes_between_two_moves_are_respected(self) -> None:
        """RF-008-22 (plan §5.4.6, I-5): con un paso por resto, lo que esta sesión registra o
        reclama entre dos pasos de apartar ya no se aparta; una carpeta de originales sin
        entrada con un fichero reciente, o a la que se le añade uno entre dos pasos, tampoco."""
        second = UNKNOWN_UID.replace("6f1c", "7a2b")
        for rel in ("rasters/res_a.tif", "rasters/res_b.tif", "rasters/res_c.tif",
                    f"originals/{UNKNOWN_UID}/plano.dxf", f"originals/{second}/plano.dxf"):
            self.put(rel)
        self.put(f"originals/{UNKNOWN_UID}/memoria.txt", recent=True)
        steps = orphans.orphan_steps(self.project, write=True, budget_s=1e-6)
        for step in steps:
            if step.phase == orphans.PHASES[1]:
                break
        self.assertFalse(self.path(f"originals/{second}").exists())  # el primero, apartado
        self.produce("rasters/res_b.tif")
        self.start().claim_paths("rasters/res_c.tif")
        outcome = list(steps)[-1].result

        self.assertEqual(set(self.moved(outcome)), {f"originals/{second}", "rasters/res_a.tif"})
        self.assertEqual(set(outcome.stale), {f"originals/{UNKNOWN_UID}", "rasters/res_b.tif",
                                              "rasters/res_c.tif"})

        self.put(f"originals/{UNKNOWN_UID}/memoria.txt")
        steps = orphans.orphan_steps(self.project, write=True)
        self.listed(steps)
        self.put(f"originals/{UNKNOWN_UID}/nuevo.txt")
        outcome = list(steps)[-1].result
        self.assertEqual(outcome.stale, (f"originals/{UNKNOWN_UID}",))
        self.assertTrue(self.path(f"originals/{UNKNOWN_UID}/nuevo.txt").exists())


class ReadOnlyTest(OrphansCase):
    def test_read_only_only_warns(self) -> None:
        """RF-008-22, RF-008-58 (spec §8, «Proyecto en solo lectura»): sin escribir (o con el
        proyecto en solo lectura) se avisa con la lista y no se aparta nada, ni se crea
        ``orphans/`` ni se escribe en la base; lo escrito después de empezar no se avisa. Al
        abrir en escritura, se apartan."""
        self.put("rasters/res_a.tif")
        self.put("rasters/res_reciente.tif", recent=True)
        self.put(f"originals/{UNKNOWN_UID}/plano.dxf")
        before = self.files()
        state = self.table_state()
        expected = FOUND_TEXT.format(files=_quoted(f"originals/{UNKNOWN_UID}/",
                                                   "rasters/res_a.tif"))
        with mock.patch.object(type(self.project), "writable", property(lambda _s: False)):
            locked = self.sweep(write=True)
        for outcome in (self.sweep(write=False), locked):
            self.assertEqual(set(self.by_state(outcome, State.FOUND)),
                             {"rasters/res_a.tif", f"originals/{UNKNOWN_UID}"})
            self.assertEqual(outcome.found, tuple(sorted(outcome.orphans,
                                                         key=lambda item: item.path)))
            self.assertEqual(self.moved(outcome), {})
            self.assertFalse(outcome.recorded)
            self.assertIsNone(outcome.folder)
            self.assertEqual(outcome.warnings, (expected,))
        self.assertEqual(self.files(), before)
        self.assertFalse(self.path("orphans").exists())
        self.assertEqual(self.table_state(), state)

        written = self.sweep()
        self.assertEqual(set(self.moved(written)),
                         {"rasters/res_a.tif", f"originals/{UNKNOWN_UID}"})


class StepsTest(OrphansCase):
    def test_steps_are_paced_and_the_record_is_retried(self) -> None:
        """RF-008-22, RF-008-58 (plan §5.4.6): con un presupuesto de paso mínimo, buscar y
        apartar van por pasos (con su progreso) y, si otro programa está leyendo la base, el
        evento se reintenta en el paso siguiente sin perder nada; el aviso lista los
        primeros 20 restos y cuántos más hay."""
        names = [f"rasters/res_resto_{index:02d}.tif" for index in range(25)]
        for rel in names:
            self.put(rel)
        real = self.project.try_write
        attempts: list[int] = []

        def busy_once(work: Callable[[sqlite3.Connection], Any]) -> Any:
            attempts.append(1)
            if len(attempts) == 1:
                return session_mod.WriteAttempt(session_mod.WriteState.RETRYING, None,
                                                session_mod.BUSY_MESSAGE)
            return real(work)

        with mock.patch.object(self.project, "try_write", busy_once):
            found = self.steps(budget_s=1e-6)

        phases = [step.phase for step in found]
        self.assertGreater(phases.count(orphans.PHASES[1]), 10)
        self.assertIn(session_mod.BUSY_MESSAGE, [step.message for step in found
                                                 if step.phase == orphans.PHASES[2]])
        self.assertEqual(len(attempts), 2)
        outcome = found[-1].result
        self.assertEqual(set(self.moved(outcome)), set(names))
        self.assertTrue(outcome.recorded)
        (event,) = self.logged()
        self.assertEqual(len(event.data["moved"]), 25)
        listed = _quoted(*names[:20]) + " y 5 más"
        self.assertEqual(outcome.warnings, (MOVED_TEXT.format(folder=STAMP_DIR, files=listed),))
        self.assertTrue(outcome.texts("en")[0].endswith(" and 5 more."))

    def test_api_and_arguments(self) -> None:
        """RF-008-22 (plan §5.3.1 y §5.2.3): ``core.datasets`` reexporta el barrido de restos;
        su evento es ``orphans_moved``; los argumentos mal dados son errores del programa."""
        for name in ("Orphan", "OrphanOutcome", "OrphanState", "orphan_steps"):
            with self.subTest(name=name):
                self.assertIn(name, datasets.__all__)
                self.assertIs(getattr(datasets, name), getattr(orphans, name))
        self.assertEqual(events.EventKind.ORPHANS_MOVED.value, "orphans_moved")
        self.assertEqual(orphans.DATA_FOLDERS, ("rasters", "meshes", "originals"))
        for kw, error in (({"write": "sí"}, TypeError), ({"started_at": 1.5}, TypeError),
                          ({"started_at": True}, TypeError), ({"budget_s": 0}, ValueError),
                          ({"claimed": "rasters/res_a.tif"}, TypeError)):
            with self.subTest(kw=kw), self.assertRaises(error):
                orphans.orphan_steps(self.project, **{"write": True, **kw})
