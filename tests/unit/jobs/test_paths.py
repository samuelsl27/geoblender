# SPDX-License-Identifier: GPL-3.0-or-later
"""Carpetas de los trabajos (spec 004, T05; RF-004-01, RF-004-18; plan 004 §5.2.1 y §5.3.1).

- RF-004-01: cada trabajo tiene su carpeta con un identificador único
  ``AAAAMMDD_HHMMSS_xxxxxx`` (hora UTC y 6 cifras hexadecimales al azar), sin repetir en
  10 000 llamadas; ``new_request`` usa el mismo generador. Las entradas se guardan tal como
  las entrega el módulo, sin cambiar su tipo ni su precisión: un array float64 con
  coordenadas UTM de 4,4 Mm y NaN (también con carga útil y con signo) se lee bit a bit, en
  ``.npy`` sin *pickle*. Una entrada externa (CSV, XLSX, base de RecMin) se copia a ``in/``
  comprobando la huella sha256 de la fuente antes, de la copia y de la fuente después: si la
  fuente cambia durante la copia, ``JobError`` ``source_changed`` y no queda nada en ``in/``.
  Sin espacio en disco, ``disk_space`` con los MB necesarios y libres, y nada escrito
  (spec §8).
- RF-004-18: la raíz de trabajos es ``<caché del proyecto>/jobs`` (``Project.cache_dir()`` de
  la 002: en los datos de usuario si el proyecto está en red o en solo lectura) o, sin
  proyecto, ``<datos de usuario>/cache/_sin_proyecto/jobs``. ``jobs/`` no decide si una ruta
  es de red: no contiene ninguna detección de red.
"""

import ast
import datetime as dt
import errno
import hashlib
import os
import re
import stat
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.core_fixtures import FakeClock, FakePids, make_session, make_settings
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

paths = import_geoblender("jobs.paths")
protocol = import_geoblender("jobs.protocol")
messages = import_geoblender("jobs.messages")
core_paths = import_geoblender("core.paths")
userdata_mod = import_geoblender("core.userdata")
create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")

JobError = messages.JobError

UID = "20261005_143012_3fa9c2"
NOW = dt.datetime(2026, 10, 5, 14, 30, 12, 345678, tzinfo=dt.UTC)
UID_FORMAT = re.compile(r"[0-9]{8}_[0-9]{6}_[0-9a-f]{6}")
JOBS_SOURCE_DIR = EXTENSION_DIR / "jobs"

# Lo que delataría una detección de red en ``jobs/`` (la decide ``bl`` con la caché del
# proyecto de la 002, plan 004 §5.2.1).
NETWORK_DETECTION = (
    "is_network_path", "is_network", "windows_drive_type", "GetDriveType", "DRIVE_REMOTE",
    "WNetGetConnection", "PathIsNetworkPath", "PathIsUNC",
)


def _bits(array: np.ndarray) -> bytes:
    """Los bytes del array tal como están en memoria (en orden C)."""
    return np.ascontiguousarray(array).tobytes()


def _utm_with_nans() -> np.ndarray:
    """float64 con coordenadas UTM de 4,4 Mm (milímetros), NaN de varias clases (silencioso,
    con signo, con carga útil y señalizador), −0,0, subnormales e infinitos."""
    special = np.array(
        [0x7FF8000000000000, 0xFFF8000000000000, 0x7FF8000000000123, 0x7FF0000000000001,
         0x8000000000000000, 0x0000000000000001, 0x7FF0000000000000, 0xFFF0000000000000],
        dtype=np.uint64,
    ).view(np.float64)
    utm = np.array([
        [715_123.456, 4_400_000.456, 1_234.567],
        [715_123.457, 4_400_000.457, 1_234.568],
        [699_999.999, 4_399_999.999, -12.001],
    ])
    return np.concatenate([utm.ravel(), special]).reshape(-1, 1)


def _tree(root: Path) -> list[str]:
    """Todo lo que hay bajo ``root`` (rutas relativas con «/»), ordenado."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _writable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IWRITE)


def _network_detections(source: str) -> list[str]:
    """Los nombres de :data:`NETWORK_DETECTION` que usa un módulo de Python: nombres,
    atributos, importaciones y textos (``getattr(kernel32, "GetDriveTypeW")``)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            words = [node.id]
        elif isinstance(node, ast.Attribute):
            words = [node.attr]
        elif isinstance(node, ast.alias):
            words = [node.name, node.asname or ""]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            words = re.findall(r"\w+", node.value)
        else:
            continue
        for word in words:
            if any(word == bad or word.startswith(bad) for bad in NETWORK_DETECTION):
                found.append(word)
    return found


class NewJobUidTest(unittest.TestCase):
    def test_format_is_utc_and_six_hex(self) -> None:
        """RF-004-01 (plan §5.2.1): ``AAAAMMDD_HHMMSS_xxxxxx`` con la hora en UTC (una hora
        con otra zona se pasa a UTC) y 6 cifras hexadecimales en minúsculas."""
        uid = paths.new_job_uid(NOW)
        self.assertRegex(uid, r"^20261005_143012_[0-9a-f]{6}$")
        madrid = dt.datetime(2026, 10, 5, 16, 30, 12, tzinfo=dt.timezone(dt.timedelta(hours=2)))
        self.assertTrue(paths.new_job_uid(madrid).startswith("20261005_143012_"))
        before = dt.datetime.now(dt.UTC).replace(microsecond=0)
        current = paths.new_job_uid()
        after = dt.datetime.now(dt.UTC)
        self.assertTrue(UID_FORMAT.fullmatch(current), current)
        stamp = dt.datetime.strptime(current[:15], "%Y%m%d_%H%M%S").replace(tzinfo=dt.UTC)
        self.assertTrue(before <= stamp <= after, (before, stamp, after))
        self.assertTrue(paths.JOB_UID_PATTERN.fullmatch(uid))

    def test_naive_time_is_rejected(self) -> None:
        """RF-004-01: una hora sin zona no se supone UTC ni local: ``ValueError``."""
        with self.assertRaises(ValueError):
            paths.new_job_uid(dt.datetime(2026, 10, 5, 14, 30, 12))

    def test_unique_in_10000_calls(self) -> None:
        """RF-004-01: 10 000 identificadores seguidos son distintos, en el mismo segundo y
        con el reloj real, y todos tienen el formato."""
        same_second = [paths.new_job_uid(NOW) for _ in range(10_000)]
        self.assertEqual(len(set(same_second)), 10_000)
        self.assertTrue(all(uid.startswith("20261005_143012_") for uid in same_second))
        live = [paths.new_job_uid() for _ in range(10_000)]
        self.assertEqual(len(set(live)), 10_000)
        self.assertTrue(all(UID_FORMAT.fullmatch(uid) for uid in live))

    def test_new_request_uses_the_same_generator(self) -> None:
        """RF-004-01: ``new_request`` saca su ``job_uid`` del mismo generador: los de las
        peticiones y los de ``new_job_uid`` del mismo segundo no se repiten entre sí."""
        from_paths = {paths.new_job_uid(NOW) for _ in range(500)}
        from_requests = {
            protocol.new_request("selftest", label="Prueba", owner="jobs", now=NOW).job_uid
            for _ in range(500)
        }
        self.assertEqual(len(from_paths), 500)
        self.assertEqual(len(from_requests), 500)
        self.assertEqual(from_paths & from_requests, set())
        self.assertIs(protocol.JOB_UID_PATTERN, paths.JOB_UID_PATTERN)


class JobDirTest(unittest.TestCase):
    def test_job_dir_is_root_and_uid_without_creating(self) -> None:
        """RF-004-01 (plan §5.2.1): ``job_dir`` es ``<raíz>/<job_uid>`` con ``in/`` y
        ``out/`` y los ficheros del registro; calcularla no crea nada."""
        with _support.temp_jobs_root() as root:
            folder = paths.job_dir(root, UID)
            self.assertIsInstance(folder, paths.JobDir)
            self.assertEqual(folder.path, root / UID)
            self.assertEqual(folder.job_uid, UID)
            self.assertEqual(folder.inputs_dir, root / UID / "in")
            self.assertEqual(folder.outputs_dir, root / UID / "out")
            self.assertEqual(folder.events_file, root / UID / "events.jsonl")
            self.assertEqual(folder.log_file, root / UID / "job.log")
            self.assertEqual(folder.result_file, root / UID / "result.json")
            self.assertEqual(folder.cancel_file, root / UID / "cancel")
            self.assertEqual(_tree(root), [])
            self.assertEqual(paths.job_dir(str(root), UID), folder)

    def test_create_makes_the_folder_once(self) -> None:
        """RF-004-01: ``create`` crea la carpeta del trabajo con ``in/`` y ``out/`` (y la
        raíz si falta); una carpeta que ya existe no se reutiliza (``FileExistsError``)."""
        with _support.jobs_tmp() as tmp:
            root = tmp / "cache" / "jobs"
            folder = paths.job_dir(root, UID)
            self.assertIs(folder.create(), folder)
            self.assertEqual(_tree(root), [UID, f"{UID}/in", f"{UID}/out"])
            with self.assertRaises(FileExistsError):
                folder.create()

    def test_invalid_uid_or_relative_root(self) -> None:
        """RF-004-01: un identificador que no es ``AAAAMMDD_HHMMSS_xxxxxx`` (con ``..``,
        barras, mayúsculas, de otra longitud) o una raíz relativa no dan una carpeta: la
        carpeta de un trabajo nunca sale de su raíz."""
        with _support.temp_jobs_root() as root:
            for bad in ("", "..", "x", f"{UID}/..", f"../{UID}", f"{UID}\\x", UID.upper()[:-1]
                        + "A", UID + "0", UID[:-1], f" {UID}", 20261005):
                with self.subTest(uid=bad), self.assertRaises(ValueError):
                    paths.job_dir(root, bad)
            with self.assertRaises(ValueError):
                paths.job_dir(Path("cache") / "jobs", UID)
            with self.assertRaises(ValueError):
                paths.JobDir(root / "no_es_un_trabajo")
            self.assertEqual(_tree(root), [])

    def test_request_round_trip_through_jobdir(self) -> None:
        """RF-004-01: ``write_request`` y ``read_request`` aceptan el ``JobDir`` y la
        petición se lee idéntica (contrato de T03 con T05)."""
        with _support.temp_jobs_root() as root:
            request = protocol.new_request(
                "selftest", label="Prueba «ñ»", owner="jobs", params={"x": 4_400_000.456},
                inputs={"data": "in/data.npy"}, environment="blender", timeout_s=60, now=NOW,
            )
            folder = paths.job_dir(root, request.job_uid).create()
            protocol.write_request(folder, request)
            self.assertEqual(protocol.read_request(folder), request)
            self.assertTrue((folder.path / protocol.REQUEST_FILE).is_file())


class WriteArrayTest(unittest.TestCase):
    def test_float64_utm_and_nan_bit_for_bit(self) -> None:
        """RF-004-01 (spec §8): un float64 con coordenadas UTM de 4,4 Mm y NaN (silencioso,
        negativo, con carga útil, señalizador), −0,0, subnormales e infinitos se escribe en
        ``in/<nombre>.npy`` y se lee bit a bit, con el mismo tipo y forma, sin *pickle*."""
        array = _utm_with_nans()
        with _support.temp_jobs_root() as root:
            folder = paths.job_dir(root, UID).create()
            rel = folder.write_array("coords", array)
            self.assertEqual(rel, "in/coords.npy")
            loaded = np.load(folder.path / rel, allow_pickle=False)
            self.assertEqual(loaded.dtype, np.dtype("<f8"))
            self.assertEqual(loaded.shape, array.shape)
            self.assertEqual(_bits(loaded), _bits(array))
            self.assertEqual(loaded.view(np.uint64)[-5, 0], 0x7FF0000000000001)
            self.assertEqual(_tree(folder.path), ["in", "in/coords.npy", "out"])
            # La entrada vale en una petición (relativa y dentro de in/).
            request = protocol.new_request(
                "selftest", label="Prueba", owner="jobs", inputs={"coords": rel},
                environment="blender", timeout_s=60, now=NOW,
            )
            protocol.validate_request(request, catalog={"selftest": object()})

    def test_type_and_layout_are_kept(self) -> None:
        """RF-004-01: sin cambiar el tipo ni la precisión: float32, float64 big endian,
        enteros, booleanos, un array Fortran y uno estructurado salen como entraron."""
        cases = {
            "f32": np.array([4_400_000.5, np.nan, -0.0], dtype=np.float32),
            "f64be": np.array([715_123.456, np.nan], dtype=">f8"),
            "i64": np.arange(-5, 5, dtype=np.int64).reshape(2, 5),
            "flags": np.array([True, False, True]),
            "fortran": np.asfortranarray(np.arange(12, dtype=np.float64).reshape(3, 4) + 0.1),
            "rec": np.array([(1, 4_400_000.456), (2, np.nan)],
                            dtype=[("id", "<i4"), ("y", "<f8")]),
            "vacio": np.empty((0, 3)),
        }
        with _support.temp_jobs_root() as root:
            folder = paths.job_dir(root, UID).create()
            for name, array in cases.items():
                with self.subTest(name=name):
                    rel = folder.write_array(name, array)
                    loaded = np.load(folder.path / rel, allow_pickle=False)
                    self.assertEqual(loaded.dtype, array.dtype)
                    self.assertEqual(loaded.shape, array.shape)
                    self.assertEqual(loaded.flags.f_contiguous and not loaded.flags.c_contiguous,
                                     array.flags.f_contiguous and not array.flags.c_contiguous)
                    self.assertEqual(_bits(loaded), _bits(array))

    def test_inputs_are_read_only_and_not_overwritten(self) -> None:
        """RF-004-01: la entrada queda de solo lectura (el worker no la cambia) y no se
        sobrescribe una que ya existe."""
        with _support.temp_jobs_root() as root:
            folder = paths.job_dir(root, UID).create()
            rel = folder.write_array("data", np.arange(3.0))
            target = folder.path / rel
            self.assertFalse(_writable(target))
            with self.assertRaises(PermissionError):
                target.open("r+b").close()
            with self.assertRaises(FileExistsError):
                folder.write_array("data", np.arange(4.0))
            np.testing.assert_array_equal(np.load(target), np.arange(3.0))

    def test_no_pickle_and_no_conversion(self) -> None:
        """RF-004-01 (ARQ-16): un array de objetos (también dentro de un tipo
        estructurado) no se escribe, porque haría falta *pickle*; lo que no es un
        ``ndarray`` tampoco se convierte. No queda ningún fichero."""
        with _support.temp_jobs_root() as root:
            folder = paths.job_dir(root, UID).create()
            objects = np.array([{"a": 1}, None], dtype=object)
            mixed = np.array([(1, "x")], dtype=[("id", "<i4"), ("o", object)])
            for bad in (objects, mixed):
                with self.subTest(dtype=str(bad.dtype)), self.assertRaises(ValueError):
                    folder.write_array("bad", bad)
            for not_array in ([1.0, 2.0], 3.0, np.float64(1.0)):
                with self.subTest(value=not_array), self.assertRaises(TypeError):
                    folder.write_array("bad", not_array)
            self.assertEqual(_tree(folder.inputs_dir), [])

    def test_bad_names(self) -> None:
        """RF-004-01: el nombre de una entrada es un identificador corto: sin barras,
        puntos, unidad, espacios ni nombres reservados de Windows (``CON``, ``NUL``…)."""
        with _support.temp_jobs_root() as root:
            folder = paths.job_dir(root, UID).create()
            for bad in ("", "..", "../x", "a/b", "a\\b", "C:x", "x.npy", "con", "NUL", "lpt1",
                        " x", "x ", "-x", "x" * 65, "ñ", None):
                with self.subTest(name=bad), self.assertRaises(ValueError):
                    folder.write_array(bad, np.zeros(1))
            self.assertEqual(_tree(root), [UID, f"{UID}/in", f"{UID}/out"])

    def test_creates_inputs_folder_if_missing(self) -> None:
        """RF-004-01: escribir una entrada crea ``in/`` si falta (el módulo puede escribir
        sus entradas antes de que el lanzador prepare la carpeta)."""
        with _support.temp_jobs_root() as root:
            folder = paths.job_dir(root, UID)
            self.assertEqual(folder.write_array("data", np.ones(2)), "in/data.npy")
            self.assertEqual(_tree(root), [UID, f"{UID}/in", f"{UID}/in/data.npy"])


class CopyInputTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = _support.jobs_tmp()
        self.tmp = self._tmp.__enter__()
        self.addCleanup(self._tmp.__exit__, None, None, None)
        self.root = self.tmp / "jobs"
        self.folder = paths.job_dir(self.root, UID).create()
        sources = self.tmp / "fuentes"
        sources.mkdir()
        self.source = sources / "collares.csv"
        # Más de un bloque de lectura: la copia se hace por trozos.
        self.content = "x;y;z;ñ\n".encode() + os.urandom(3 * (1 << 20) + 123)
        self.source.write_bytes(self.content)
        self.source_hash = hashlib.sha256(self.content).hexdigest()

    def test_copy_is_identical_and_read_only(self) -> None:
        """RF-004-01: la copia a ``in/<nombre><extensión>`` es idéntica (sha256), de solo
        lectura, y la fuente no cambia (ni su contenido ni su fecha ni sus permisos)."""
        before = self.source.stat()
        rel = self.folder.copy_input(self.source, "collares")
        self.assertEqual(rel, "in/collares.csv")
        copy = self.folder.path / rel
        self.assertEqual(hashlib.sha256(copy.read_bytes()).hexdigest(), self.source_hash)
        self.assertFalse(_writable(copy))
        after = self.source.stat()
        self.assertEqual(_support.sha256_file(self.source), self.source_hash)
        self.assertEqual((after.st_mtime_ns, after.st_size), (before.st_mtime_ns, before.st_size))
        self.assertTrue(_writable(self.source))
        self.assertEqual(_tree(self.folder.inputs_dir), ["collares.csv"])

    def test_three_hashes_are_taken(self) -> None:
        """RF-004-01 (plan §5.3.1): la huella de la fuente se toma antes, la de la copia
        mientras se copia y la de la fuente después: tres lecturas completas."""
        real = paths._digest
        calls: list[tuple[Path, bool]] = []

        def spy(path, sink=None):
            calls.append((Path(path), sink is not None))
            return real(path, sink)

        with mock.patch.object(paths, "_digest", side_effect=spy):
            self.folder.copy_input(self.source, "collares")
        self.assertEqual(calls, [(self.source, False), (self.source, True), (self.source, False)])

    def test_progress_of_the_three_reads(self) -> None:
        """RF-004-01 (spec 006, T33; RF-006-28): con ``progress``, la copia avisa tras cada
        bloque de lo hecho de sus tres lecturas (4 bloques cada una), creciente hasta 1; lo
        que lance ``progress`` (la cancelación del trabajo) para la copia sin dejar nada en
        ``in/``."""
        seen: list[float] = []
        self.folder.copy_input(self.source, "collares", progress=seen.append)
        self.assertEqual(len(seen), 12)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)

        class Stop(Exception):
            pass

        def stop(fraction: float) -> None:
            if fraction > 0.5:  # ya copiando
                raise Stop

        with self.assertRaises(Stop):
            self.folder.copy_input(self.source, "otra", progress=stop)
        self.assertEqual(_tree(self.folder.inputs_dir), ["collares.csv"])

    def _assert_source_changed(self, change_at_call: int, *, mid_copy: bool = False) -> None:
        real = paths._digest
        count = 0

        def change_source() -> None:
            # Mismo tamaño y otro contenido: solo la huella lo descubre.
            with self.source.open("r+b") as stream:
                stream.seek(len(self.content) - 1000)
                stream.write(b"\x00" * 1000 if self.content[-1] else b"\x01" * 1000)

        def tampering(path, sink=None):
            nonlocal count
            count += 1
            if mid_copy and sink is not None:
                blocks = 0

                def sink_then_change(block: bytes) -> None:
                    nonlocal blocks
                    sink(block)
                    blocks += 1
                    if blocks == 1:
                        change_source()

                return real(path, sink_then_change)
            digest = real(path, sink)
            if count == change_at_call:
                change_source()
            return digest

        with mock.patch.object(paths, "_digest", side_effect=tampering):
            with self.assertRaises(JobError) as caught:
                self.folder.copy_input(self.source, "collares", job="Importar sondeos")
        error = caught.exception
        self.assertEqual(error.code, "source_changed")
        self.assertIn(str(self.source), error.text)
        self.assertIn("«Importar sondeos»", error.text)
        self.assertNotIn("Traceback", error.text)
        self.assertEqual(_tree(self.folder.inputs_dir), [])

    def test_source_changed_before_the_copy(self) -> None:
        """RF-004-01 (plan §5.3.1): la fuente cambia entre su primera huella y la copia →
        ``source_changed``, sin dejar nada en ``in/``."""
        self._assert_source_changed(1)

    def test_source_changed_during_the_copy(self) -> None:
        """RF-004-01 (plan §5.3.1): la fuente cambia a mitad de la copia (tras el primer
        bloque, con el mismo tamaño) → ``source_changed``, sin dejar nada en ``in/``."""
        self._assert_source_changed(0, mid_copy=True)

    def test_source_changed_after_the_copy(self) -> None:
        """RF-004-01 (plan §5.3.1): la fuente cambia entre la copia y su última huella →
        ``source_changed``, sin dejar nada en ``in/``."""
        self._assert_source_changed(2)

    def test_source_changed_message(self) -> None:
        """RF-004-01 (principio 10): ``source_changed`` tiene ``msgid`` en inglés y texto
        en español que nombran el fichero y el trabajo."""
        message = messages.MESSAGES["source_changed"]
        self.assertEqual(
            messages.render("source_changed", path="Z:\\x\\collares.csv", job="Importar"),
            message.es.format(path="Z:\\x\\collares.csv", job="Importar"),
        )
        self.assertIn("{path}", message.es)
        self.assertIn("{job}", message.msgid)
        self.assertIsNone(re.search(r"[áéíóúñ]", message.msgid))

    def test_missing_or_unreadable_source(self) -> None:
        """RF-004-01: una fuente que no existe o que no es un fichero da ``JobError``
        ``request_invalid`` con su ruta, sin crear nada en ``in/``."""
        for bad in (self.tmp / "fuentes" / "no_existe.csv", self.tmp / "fuentes"):
            with self.subTest(source=bad.name):
                with self.assertRaises(JobError) as caught:
                    self.folder.copy_input(bad, "collares")
                self.assertEqual(caught.exception.code, "request_invalid")
                self.assertIn(str(bad), caught.exception.text)
        self.assertEqual(_tree(self.folder.inputs_dir), [])

    def test_extension_name_and_existing_copy(self) -> None:
        """RF-004-01: el nombre en ``in/`` es el dado con la extensión de la fuente (o
        ninguna); un nombre no válido es ``ValueError`` y una copia que ya existe no se
        sobrescribe."""
        plain = self.tmp / "fuentes" / "LEEME"
        plain.write_bytes(b"sin extension")
        self.assertEqual(self.folder.copy_input(plain, "leeme"), "in/leeme")
        self.assertEqual(self.folder.copy_input(self.source, "collares"), "in/collares.csv")
        with self.assertRaises(FileExistsError):
            self.folder.copy_input(self.source, "collares")
        for bad in ("", "../x", "collares.csv", "aux"):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                self.folder.copy_input(self.source, bad)
        self.assertEqual(_tree(self.folder.inputs_dir), ["collares.csv", "leeme"])


class DiskSpaceTest(unittest.TestCase):
    def test_write_array_without_space(self) -> None:
        """RF-004-01 (spec §8): sin espacio para un array, ``disk_space`` con la unidad y
        los MB necesarios y libres, y nada escrito."""
        array = np.zeros((1000, 300))  # 2,4 MB
        with _support.temp_jobs_root() as root:
            folder = paths.job_dir(root, UID).create()
            with mock.patch.object(paths, "_free_bytes", return_value=1_000_000):
                with self.assertRaises(JobError) as caught:
                    folder.write_array("big", array)
            error = caught.exception
            self.assertEqual(error.code, "disk_space")
            self.assertGreaterEqual(error.values["needed"], 2.4)
            self.assertEqual(error.values["free"], 1.0)
            self.assertEqual(error.values["drive"], root.drive or root.anchor)
            self.assertIn("hacen falta", error.text)
            self.assertEqual(_tree(folder.inputs_dir), [])

    def test_disk_full_while_writing(self) -> None:
        """RF-004-01 (spec §8): el disco se llena mientras se escribe (``ENOSPC``):
        ``disk_space`` y ningún fichero a medias."""
        with _support.temp_jobs_root() as root:
            folder = paths.job_dir(root, UID).create()
            full = OSError(errno.ENOSPC, "No space left on device")
            with mock.patch.object(np, "save", side_effect=full):
                with self.assertRaises(JobError) as caught:
                    folder.write_array("data", np.arange(10.0))
            self.assertEqual(caught.exception.code, "disk_space")
            self.assertEqual(_tree(folder.inputs_dir), [])

    def test_copy_input_without_space(self) -> None:
        """RF-004-01 (spec §8): sin espacio para la copia, ``disk_space`` antes de leer la
        fuente; ni copia ni fichero a medias, y la fuente intacta."""
        with _support.jobs_tmp() as tmp:
            source = tmp / "fuente.xlsx"
            source.write_bytes(os.urandom(300_000))
            digest = _support.sha256_file(source)
            folder = paths.job_dir(tmp / "jobs", UID).create()
            with mock.patch.object(paths, "_free_bytes", return_value=100_000), \
                    mock.patch.object(paths, "_digest") as digest_spy:
                with self.assertRaises(JobError) as caught:
                    folder.copy_input(source, "fuente")
            self.assertEqual(caught.exception.code, "disk_space")
            self.assertEqual(caught.exception.values["free"], 0.1)
            digest_spy.assert_not_called()
            self.assertEqual(_tree(folder.inputs_dir), [])
            self.assertEqual(_support.sha256_file(source), digest)


class JobsRootTest(unittest.TestCase):
    def test_project_cache_or_no_project(self) -> None:
        """RF-004-18 (plan §5.2.1): con proyecto, ``<caché del proyecto>/jobs``; sin
        proyecto, ``<datos de usuario>/cache/_sin_proyecto/jobs`` (la caché sin proyecto
        de la 002). Calcularla no crea nada."""
        with _support.jobs_tmp() as tmp:
            user = tmp / "datos_usuario"
            cache = tmp / "proyecto" / "cache"
            self.assertEqual(
                paths.resolve_jobs_root(project_cache_dir=cache, user_dir=user), cache / "jobs"
            )
            no_project = paths.resolve_jobs_root(project_cache_dir=None, user_dir=user)
            self.assertEqual(no_project, user / "cache" / "_sin_proyecto" / "jobs")
            self.assertEqual(
                no_project, userdata_mod.UserData(user).no_project_cache_dir() / "jobs"
            )
            self.assertEqual(_tree(tmp), [])

    def test_relative_paths_are_rejected(self) -> None:
        """RF-004-18: la raíz se calcula con rutas completas (las da ``bl``); una
        relativa es un error del programa."""
        with _support.jobs_tmp() as tmp:
            with self.assertRaises(ValueError):
                paths.resolve_jobs_root(project_cache_dir=None, user_dir=Path("datos"))
            with self.assertRaises(ValueError):
                paths.resolve_jobs_root(project_cache_dir=Path("cache"), user_dir=tmp)

    def _project(self, tmp: Path, drive_type):
        """Un proyecto de la 002 en ``tmp/red`` con la detección de unidad simulada."""
        parent = tmp / "red"
        parent.mkdir()
        userdata = userdata_mod.UserData(tmp / "datos_usuario")
        clock = FakeClock()
        session = make_session()
        created = create.create_project(
            parent, make_settings(), session, userdata, clock=clock, drive_type=drive_type
        )
        return created.project, userdata, clock, session

    def test_network_project_jobs_go_to_user_data(self) -> None:
        """RF-004-18: con el proyecto abierto sobre una unidad de red (detección simulada,
        como en la 002), la raíz de trabajos está en los datos de usuario de este equipo,
        y preparar un trabajo con una entrada no crea nada en la carpeta del proyecto."""
        with _support.jobs_tmp() as tmp:
            project, userdata, _clock, _session = self._project(
                tmp, lambda root: core_paths.DRIVE_REMOTE
            )
            try:
                before = _tree(project.root)
                root = paths.resolve_jobs_root(
                    project_cache_dir=project.cache_dir(), user_dir=userdata.root
                )
                self.assertEqual(root, userdata.cache_dir(project.uid) / "jobs")
                folder = paths.job_dir(root, paths.new_job_uid()).create()
                folder.write_array("data", np.arange(4.0))
                self.assertTrue(core_paths.is_within(folder.path, userdata.root))
                self.assertFalse(core_paths.is_within(folder.path, project.root))
                self.assertEqual(_tree(project.root), before)
                self.assertNotIn("cache", before)
            finally:
                project.close()

    def test_read_only_project_jobs_go_to_user_data(self) -> None:
        """RF-004-18: con el proyecto en solo lectura (en disco local, abierto por otra
        sesión), la raíz también está en los datos de usuario; en disco local y en
        escritura, en ``<proyecto>/cache/jobs``."""
        with _support.jobs_tmp() as tmp:
            project, userdata, clock, session = self._project(tmp, lambda root: 3)
            other = make_session(
                session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B",
                user="otra", pid=777,
            )
            reader = open_mod.open_project(
                project.root, other, userdata, clock=clock,
                pid_alive=FakePids({session.pid, other.pid}), drive_type=lambda root: 3,
            ).project
            try:
                local = paths.resolve_jobs_root(
                    project_cache_dir=project.cache_dir(), user_dir=userdata.root
                )
                self.assertEqual(local, project.root / "cache" / "jobs")
                self.assertIsNotNone(reader.read_only_reason)
                read_only = paths.resolve_jobs_root(
                    project_cache_dir=reader.cache_dir(), user_dir=userdata.root
                )
                self.assertEqual(read_only, userdata.cache_dir(project.uid) / "jobs")
                self.assertFalse(core_paths.is_within(read_only, project.root))
            finally:
                reader.close()
                project.close()


class NoNetworkDetectionTest(unittest.TestCase):
    def test_jobs_has_no_network_detection(self) -> None:
        """RF-004-18 (plan §5.2.1, §6): ``jobs/`` no decide si una ruta es de red (lo
        decide la caché del proyecto de la 002, que ``bl`` le pasa): ninguno de sus
        módulos usa ``is_network_path``, ``GetDriveTypeW``, ``DRIVE_REMOTE``…"""
        modules = sorted(JOBS_SOURCE_DIR.rglob("*.py"))
        self.assertIn(JOBS_SOURCE_DIR / "paths.py", modules)
        for module in modules:
            with self.subTest(module=module.name):
                source = module.read_text(encoding="utf-8")
                self.assertEqual(_network_detections(source), [])

    def test_the_check_finds_a_detection(self) -> None:
        """RF-004-18: la comprobación anterior sí ve una detección de red (caso rojo)."""
        samples = (
            "from ..core.paths import is_network_path\n",
            "from ..core import paths\nx = paths.is_network_path(p)\n",
            "import ctypes\nk = ctypes.windll.kernel32\nf = getattr(k, 'GetDriveTypeW')\n",
            "REMOTE = DRIVE_REMOTE\n",
            "net = project.is_network\n",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertNotEqual(_network_detections(sample), [])


if __name__ == "__main__":
    unittest.main()
