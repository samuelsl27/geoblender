# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento del proyecto y de la georreferencia (spec 002, T36; RNF-002-01 a
RNF-002-07; plan 002 §7, ``tests/rendimiento/core``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4) en
el PC de referencia de la spec 001 §5, en disco local (``%TEMP%``), con el reloj y la
comprobación de procesos reales. Cada prueba imprime su cifra en una línea
``RNF-002-nn: …`` (``tools/check.py`` las recoge) y la compara con su presupuesto. Lo de
la red (``Z:``: RNF-002-02 ≤ 3 s y RNF-002-05 ≤ 1 s) se mide a mano en la T37 (M5 y M7).

- RNF-002-01: crear un proyecto, 20 veces: máximo ≤ 1 s.
- RNF-002-02: abrir (sin migrar) y cerrar, 20 veces: máximo ≤ 0,5 s cada uno.
- RNF-002-03: ida y vuelta absoluta → local (float32, lo que guarda Blender) → absoluta
  de 10⁶ puntos, 5 veces: máximo ≤ 0,15 s.
- RNF-002-04: cada transacción de escritura de la spec: un evento (20 veces) y cambiar la
  ventana de trabajo con su cabecera (10 veces): máximo ≤ 0,1 s.
- RNF-002-05: renovar el cerrojo, 50 veces: máximo ≤ 0,05 s.
- RNF-002-06: copia previa (migración con una migración de prueba 1 → 2), copia local y
  publicación de un proyecto sintético de 1 GiB: cada una ≤ 30 s, con un paso de progreso
  cada ≤ 1 s (la llamada más larga al generador de pasos) y la cancelación a mitad de la
  copia, antes de sustituir nada, en ≤ 2 s (sin dejar copia ni reserva).
- RNF-002-07: devolver al diario clásico una base de 100 MiB con 50 MiB confirmados que
  solo están en el ``-wal`` (un escritor terminado con ``os._exit``, como un QGIS que se
  cae): ≤ 5 s.
"""

import os
import sqlite3
import statistics
import subprocess
import sys
import time
import unittest
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tests.support.core_fixtures import make_session, make_settings, project_tmp
from tests.support.package import import_geoblender
from tests.support.trees import child_env, child_temp

georef = import_geoblender("core.georef")
create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
model = import_geoblender("core.project.model")
events = import_geoblender("core.project.events")
lock = import_geoblender("core.project.lock")
checkout = import_geoblender("core.project.checkout")
copytree = import_geoblender("core.project.copytree")
migrations = import_geoblender("core.project.migrations")
gpkg = import_geoblender("core.gpkg")
timeutil = import_geoblender("core.timeutil")
userdata_mod = import_geoblender("core.userdata")

SESSION = make_session(pid=os.getpid())
REPETITIONS = 20
MiB = 1024 * 1024
GiB = 1024 * MiB

CREATE_BUDGET_S = 1.0  # RNF-002-01: ≤ 1 s
OPEN_CLOSE_BUDGET_S = 0.5  # RNF-002-02: ≤ 0,5 s cada uno, en disco local
ROUND_TRIP_BUDGET_S = 0.15  # RNF-002-03
ROUND_TRIP_POINTS = 1_000_000
ROUND_TRIP_SEED = 20_261_005
TRANSACTION_BUDGET_S = 0.1  # RNF-002-04
HEARTBEAT_BUDGET_S = 0.05  # RNF-002-05: ≤ 0,05 s en disco local
COPY_BUDGET_S = 30.0  # RNF-002-06
PROGRESS_GAP_S = 1.0  # RNF-002-06: progreso cada ≤ 1 s
CANCEL_BUDGET_S = 2.0  # RNF-002-06: cancelación efectiva en ≤ 2 s
WAL_BUDGET_S = 5.0  # RNF-002-07

# El proyecto sintético de 1 GiB: dos rásteres y una malla grandes y 64 ficheros de 1 MiB
# en una instantánea (el coste por fichero también cuenta).
BIG_FILES: tuple[tuple[str, int], ...] = (
    ("rasters/gis_dtm_uno.tif", 384 * MiB),
    ("rasters/gis_dtm_dos.tif", 384 * MiB),
    ("meshes/des_final.npz", 192 * MiB),
    *((f"snapshots/V1.r1/vector/capa_{n:02d}.parquet", MiB) for n in range(64)),
)

# Escritor de la base en WAL: 50 MiB confirmados en el -wal sin consolidar (sin
# autocheckpoint) y termina sin cerrar. El literal lo arma la prueba (ARQ-17 solo vigila el
# código de la extensión).
WAL_PRAGMA = "PRAGMA journal_mode=" + "WAL"
KILLED_WRITER = f"""
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1], isolation_level=None)
conn.execute("{WAL_PRAGMA}")
conn.execute("PRAGMA wal_autocheckpoint=0")
block = os.urandom(1024 * 1024)
for index in range(50):
    conn.execute("BEGIN")
    conn.execute("INSERT INTO capa_qgis (dato) VALUES (?)", (block,))
    conn.execute("COMMIT")
os._exit(0)
"""


def _seconds(value: float, digits: int = 3) -> str:
    """Segundos con coma decimal (salida en español)."""
    return f"{value:.{digits}f}".replace(".", ",")


def _report(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _write_file(path: Path, size: int, block: bytes) -> None:
    """Un fichero de ``size`` bytes ya escrito en el disco (``fsync``), como el de un
    proyecto que existe desde antes: sin 1 GiB pendiente de escribir en la caché del
    sistema, que la copia tendría que esperar al forzar a disco lo suyo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        left = size
        while left > 0:
            piece = block[: min(left, len(block))]
            handle.write(piece)
            left -= len(piece)
        handle.flush()
        os.fsync(handle.fileno())


@dataclass
class Driven:
    """Lo que tardó una operación por pasos: total, la llamada más larga al generador (el
    mayor hueco sin progreso), cuántos pasos y el resultado del último."""

    total_s: float
    max_gap_s: float
    steps: int
    result: object


def drive(steps: Iterator[object]) -> Driven:
    """Recorre ``steps`` entero midiendo cada paso."""
    gaps: list[float] = []
    result: object = None
    started = time.perf_counter()
    while True:
        before = time.perf_counter()
        try:
            step = next(steps)
        except StopIteration:
            gaps.append(time.perf_counter() - before)
            break
        gaps.append(time.perf_counter() - before)
        if getattr(step, "result", None) is not None:
            result = step.result
    return Driven(time.perf_counter() - started, max(gaps), len(gaps) - 1, result)


def cancel_at_half(steps: Iterator[object], phase: str) -> float:
    """Avanza ``steps`` hasta que la fase ``phase`` pasa de la mitad de su total (en
    bytes) y entonces cancela (``close()``); devuelve lo que tardó la cancelación."""
    for step in steps:
        if step.phase == phase and step.total > GiB // 4 and step.done * 2 >= step.total:
            break
    else:
        raise AssertionError(f"la fase «{phase}» no llegó a la mitad")
    started = time.perf_counter()
    steps.close()  # type: ignore[attr-defined]
    return time.perf_counter() - started


class ProjectSpeedTest(unittest.TestCase):
    """Crear, abrir, cerrar, escribir y renovar el cerrojo en disco local."""

    def test_create_project(self) -> None:
        """RNF-002-01: crear un proyecto en disco local tarda ≤ 1 s (máximo de 20)."""
        times: list[float] = []
        with project_tmp() as tmp:
            userdata = userdata_mod.UserData(tmp / "datos_usuario")
            for index in range(REPETITIONS):
                parent = tmp / f"p{index:02d}"
                parent.mkdir()
                started = time.perf_counter()
                created = create.create_project(parent, make_settings(), SESSION, userdata)
                times.append(time.perf_counter() - started)
                created.project.close()
        _report(
            f"RNF-002-01: crear un proyecto, {REPETITIONS} veces: máximo "
            f"{_seconds(max(times))} s, mediana {_seconds(statistics.median(times))} s "
            f"(presupuesto {_seconds(CREATE_BUDGET_S, 1)} s)"
        )
        self.assertLessEqual(max(times), CREATE_BUDGET_S)

    def test_open_and_close(self) -> None:
        """RNF-002-02: abrir (sin migrar) y cerrar un proyecto en disco local tarda
        ≤ 0,5 s cada uno (máximo de 20)."""
        opens: list[float] = []
        closes: list[float] = []
        with project_tmp() as tmp:
            userdata = userdata_mod.UserData(tmp / "datos_usuario")
            created = create.create_project(tmp, make_settings(), SESSION, userdata)
            created.project.close()
            for _ in range(REPETITIONS):
                started = time.perf_counter()
                opened = open_mod.open_project(created.root, SESSION, userdata)
                opens.append(time.perf_counter() - started)
                self.assertIs(opened.project.mode, model.OpenMode.WRITE_LOCAL)
                started = time.perf_counter()
                warnings = opened.project.close()
                closes.append(time.perf_counter() - started)
                self.assertEqual(warnings, ())
        _report(
            f"RNF-002-02: abrir y cerrar en disco local, {REPETITIONS} veces: abrir máximo "
            f"{_seconds(max(opens))} s (mediana {_seconds(statistics.median(opens))} s), "
            f"cerrar máximo {_seconds(max(closes))} s (mediana "
            f"{_seconds(statistics.median(closes))} s) (presupuesto "
            f"{_seconds(OPEN_CLOSE_BUDGET_S, 1)} s cada uno)"
        )
        self.assertLessEqual(max(opens), OPEN_CLOSE_BUDGET_S)
        self.assertLessEqual(max(closes), OPEN_CLOSE_BUDGET_S)

    def test_write_transactions(self) -> None:
        """RNF-002-04: cada transacción de escritura de la spec en disco local tarda
        ≤ 0,1 s: un evento en ``write_transaction`` (20 veces) y cambiar la ventana de
        trabajo, con su evento y la cabecera (10 veces); máximo."""
        event_times: list[float] = []
        window_times: list[float] = []
        with project_tmp() as tmp:
            userdata = userdata_mod.UserData(tmp / "datos_usuario")
            created = create.create_project(tmp, make_settings(), SESSION, userdata)
            project = created.project
            try:
                for index in range(REPETITIONS):
                    started = time.perf_counter()
                    with project.write_transaction() as conn:
                        events.record_event(
                            conn, events.EventKind.OPEN, f"Evento de rendimiento {index}",
                            session=SESSION, at=timeutil.utc_now_text(),
                        )
                    event_times.append(time.perf_counter() - started)
                for index in range(REPETITIONS // 2):
                    shift = 1_000.0 * (index % 2)
                    window = (699_500.0 + shift, 4_399_500.0, 700_501.0 + shift, 4_400_501.0)
                    started = time.perf_counter()
                    project.set_window(window, 1.0, 0, f"Prueba de rendimiento {index}")
                    window_times.append(time.perf_counter() - started)
            finally:
                project.close()
        _report(
            f"RNF-002-04: transacciones de escritura en disco local: un evento, máximo "
            f"{_seconds(max(event_times))} s (mediana "
            f"{_seconds(statistics.median(event_times))} s, {REPETITIONS} veces); ventana de "
            f"trabajo con su cabecera, máximo {_seconds(max(window_times))} s (mediana "
            f"{_seconds(statistics.median(window_times))} s, {len(window_times)} veces) "
            f"(presupuesto {_seconds(TRANSACTION_BUDGET_S, 1)} s)"
        )
        self.assertLessEqual(max(event_times), TRANSACTION_BUDGET_S)
        self.assertLessEqual(max(window_times), TRANSACTION_BUDGET_S)

    def test_heartbeat(self) -> None:
        """RNF-002-05: renovar la marca de actividad del cerrojo en disco local tarda
        ≤ 0,05 s (máximo de 50)."""
        times: list[float] = []
        with project_tmp() as tmp:
            userdata = userdata_mod.UserData(tmp / "datos_usuario")
            created = create.create_project(tmp, make_settings(), SESSION, userdata)
            project = created.project
            try:
                for _ in range(50):
                    started = time.perf_counter()
                    check = project.heartbeat()
                    times.append(time.perf_counter() - started)
                    self.assertIs(check, lock.LockCheck.OK)
            finally:
                project.close()
        _report(
            f"RNF-002-05: renovar el cerrojo en disco local, 50 veces: máximo "
            f"{_seconds(max(times), 4)} s, mediana {_seconds(statistics.median(times), 4)} s "
            f"(presupuesto {_seconds(HEARTBEAT_BUDGET_S, 2)} s)"
        )
        self.assertLessEqual(max(times), HEARTBEAT_BUDGET_S)


class RoundTripSpeedTest(unittest.TestCase):
    def test_million_points_round_trip(self) -> None:
        """RNF-002-03: la ida y vuelta absoluta → local en float32 → absoluta de 10⁶
        puntos con el numpy de Blender tarda ≤ 0,15 s (máximo de 5)."""
        rng = np.random.default_rng(ROUND_TRIP_SEED)
        n = ROUND_TRIP_POINTS
        world = np.column_stack(
            [
                700_000.0 + rng.uniform(-8_000.0, 8_000.0, n),
                4_400_000.0 + rng.uniform(-8_000.0, 8_000.0, n),
                rng.uniform(0.0, 4_000.0, n),
            ]
        )
        origin = georef.GeoOrigin(700_000, 4_400_000, 0)
        times: list[float] = []
        for _ in range(5):
            started = time.perf_counter()
            local32 = georef.world_to_local(world, origin).astype(np.float32)
            back = georef.local_to_world(local32, origin)
            times.append(time.perf_counter() - started)
        error_mm = float(np.abs(back - world).max()) * 1000.0
        _report(
            f"RNF-002-03: ida y vuelta de {n} puntos (numpy {np.__version__}), 5 veces: "
            f"máximo {_seconds(max(times))} s, mediana {_seconds(statistics.median(times))} s, "
            f"error {_seconds(error_mm, 4)} mm (presupuesto {_seconds(ROUND_TRIP_BUDGET_S, 2)} s)"
        )
        self.assertLessEqual(error_mm, 0.5)
        self.assertLessEqual(max(times), ROUND_TRIP_BUDGET_S)


M1_2 = migrations.Migration(
    1, 2, "tabla de prueba de rendimiento",
    lambda conn: conn.execute("CREATE TABLE IF NOT EXISTS gb_perf_m2 (fid INTEGER PRIMARY KEY)"),
)


class GigabyteCopiesTest(unittest.TestCase):
    """RNF-002-06 con un proyecto sintético de 1 GiB, de disco local a disco local."""

    def _check_driven(self, what: str, driven: Driven, cancel_s: float) -> None:
        _report(
            f"RNF-002-06: {what} de 1 GiB: {_seconds(driven.total_s, 2)} s en "
            f"{driven.steps} pasos, paso más largo {_seconds(driven.max_gap_s)} s; cancelar a "
            f"mitad de la copia: {_seconds(cancel_s)} s (presupuestos "
            f"{_seconds(COPY_BUDGET_S, 0)} s, {_seconds(PROGRESS_GAP_S, 0)} s y "
            f"{_seconds(CANCEL_BUDGET_S, 0)} s)"
        )
        self.assertLessEqual(driven.total_s, COPY_BUDGET_S, what)
        self.assertLessEqual(driven.max_gap_s, PROGRESS_GAP_S, what)
        self.assertLessEqual(cancel_s, CANCEL_BUDGET_S, what)

    def test_backup_checkout_and_publish_of_one_gigabyte(self) -> None:
        """RNF-002-06: copia previa, copia local y publicación de un proyecto de 1 GiB,
        cada una ≤ 30 s, con progreso cada ≤ 1 s; cancelar a mitad de la copia tarda
        ≤ 2 s y no deja copia, ``.publicando`` ni copia previa, ni sustituye nada."""
        with project_tmp("geoblender-002-1gib-") as tmp:
            parent = tmp / "red"
            parent.mkdir()
            dest = tmp / "copias"
            dest.mkdir()
            userdata = userdata_mod.UserData(tmp / "datos_usuario")
            created = create.create_project(parent, make_settings(), SESSION, userdata)
            root = created.root
            block = os.urandom(8 * MiB)
            for rel, size in BIG_FILES:
                _write_file(root / rel, size, block)
            created.project.close()
            total = sum(size for _rel, size in BIG_FILES)
            self.assertEqual(total, GiB)
            before = copytree.fingerprint(root, exclude=checkout.CHECKOUT_EXCLUDE)

            # Copia local: cancelada a mitad y después entera.
            cancel_s = cancel_at_half(
                checkout.checkout_steps(root, dest, SESSION, userdata), "copia"
            )
            self.assertEqual(list(dest.iterdir()), [])
            self.assertFalse((root / ".lock").exists())
            driven = drive(checkout.checkout_steps(root, dest, SESSION, userdata))
            local = driven.result.opened.project
            self._check_driven("copia local", driven, cancel_s)

            # Publicación: cancelada a mitad de la copia a .publicando y después entera.
            cancel_s = cancel_at_half(
                checkout.publish_steps(local, SESSION, userdata), "copia"
            )
            self.assertFalse(checkout.publishing_path(root).exists())
            self.assertEqual(
                copytree.fingerprint(root, exclude=checkout.CHECKOUT_EXCLUDE), before
            )
            driven = drive(checkout.publish_steps(local, SESSION, userdata))
            self.assertTrue(checkout.previous_path(root).is_dir())
            self._check_driven("publicación", driven, cancel_s)

            # Copia previa de una migración (1 → 2, de prueba), sin la publicación anterior
            # ni la copia local para no pasar de 3 GiB en disco.
            copytree.remove_tree(checkout.previous_path(root))
            copytree.remove_tree(driven.result.local)
            backup = migrations.backup_path(root, 1)
            cancel_s = cancel_at_half(
                migrations.migrate_steps(root, SESSION, userdata, (M1_2,), target=2),
                "copia previa",
            )
            self.assertFalse(backup.exists())
            driven = drive(migrations.migrate_steps(root, SESSION, userdata, (M1_2,), target=2))
            self.assertEqual(driven.result.backup, backup)
            self._check_driven("copia previa", driven, cancel_s)


class WalRecoverySpeedTest(unittest.TestCase):
    def test_hundred_megabytes_with_fifty_in_wal(self) -> None:
        """RNF-002-07: devolver al diario clásico la base de un proyecto de 100 MiB con
        50 MiB confirmados que solo están en el ``-wal`` tarda ≤ 5 s, sin perder filas y
        sin dejar ``-wal`` ni ``-shm``."""
        with project_tmp() as tmp:
            userdata = userdata_mod.UserData(tmp / "datos_usuario")
            created = create.create_project(tmp, make_settings(), SESSION, userdata)
            created.project.close()
            database = created.root / "project.gpkg"
            conn = sqlite3.connect(database, isolation_level=None)
            try:  # 100 MiB en diario clásico, en una tabla de «QGIS»
                conn.execute("CREATE TABLE capa_qgis (fid INTEGER PRIMARY KEY, dato BLOB)")
                block = os.urandom(MiB)
                conn.execute("BEGIN")
                while database.stat().st_size < 100 * MiB:
                    for _ in range(10):
                        conn.execute("INSERT INTO capa_qgis (dato) VALUES (?)", (block,))
                    conn.execute("COMMIT")
                    conn.execute("BEGIN")
                conn.execute("COMMIT")
                rows_before = conn.execute("SELECT count(*) FROM capa_qgis").fetchone()[0]
            finally:
                conn.close()
            base_size = database.stat().st_size
            with child_temp() as temp:
                subprocess.run(
                    [sys.executable, "-B", "-s", "-c", KILLED_WRITER, str(database)],
                    env=child_env(None, temp), check=True, timeout=120, capture_output=True,
                )
            wal_file = Path(f"{database}-wal")
            wal_size = wal_file.stat().st_size
            self.assertGreaterEqual(wal_size, 50 * MiB)
            started = time.perf_counter()
            recovery = gpkg.to_classic_journal(database)
            took = time.perf_counter() - started
            self.assertIs(recovery.outcome, gpkg.WalOutcome.CONVERTED)
            self.assertEqual(gpkg.read_header(database).journal, "classic")
            self.assertFalse(wal_file.exists())
            self.assertFalse(Path(f"{database}-shm").exists())
            conn = sqlite3.connect(database)
            try:
                rows_after = conn.execute("SELECT count(*) FROM capa_qgis").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(rows_after, rows_before + 50)
        _report(
            f"RNF-002-07: base de {_seconds(base_size / MiB, 1)} MiB con "
            f"{_seconds(wal_size / MiB, 1)} MiB en el -wal devuelta al diario clásico en "
            f"{_seconds(took)} s (presupuesto {_seconds(WAL_BUDGET_S, 0)} s)"
        )
        self.assertLessEqual(took, WAL_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
