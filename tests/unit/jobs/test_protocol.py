# SPDX-License-Identifier: GPL-3.0-or-later
"""Petición de los trabajos en segundo plano (spec 004, T03; RF-004-01, RF-004-02; plan 004
§5.2.2 y §5.3.1).

- RF-004-01: la petición (``request.json``, esquema ``geoblender.job/1``) lleva el tipo de
  trabajo, los parámetros, las entradas, el tiempo máximo y la versión de Geoblender, y se
  lee idéntica a como se escribió: los decimales bit a bit y el texto en UTF-8 («ñ»).
- RF-004-02: una entrada absoluta, con ``..``, fuera de ``in/`` o con unidad, y la ruta del
  proyecto escondida en un parámetro anidado (con ``/`` y ``\\``, con otras mayúsculas), se
  rechazan con un ``JobError`` que nombra el trabajo y la ruta.
- Límites (spec §8): ``timeout_s`` ≤ 0 o > 86 400 y ``grace_s`` fuera de 1–60 dan
  ``request_invalid``; un esquema desconocido, ``request_invalid``; un tipo de trabajo
  desconocido, ``worker_unknown``.
- Ningún caso inválido crea ficheros: ni en la raíz de trabajos ni en el proyecto.

Eventos del worker (T04; RF-004-12, RF-004-15; plan 004 §5.2.3): ``JobEvent``, ``OutputRef``,
``encode_event`` y ``EventDecoder``. El decodificador devuelve los eventos en el orden de
llegada aunque las líneas lleguen partidas entre lecturas (también por la mitad de una «ñ»), y
lo que no es un evento (una línea no JSON, un evento de versión desconocida…) como
``InvalidLine``, sin lanzar; el avance (``frac``) fuera de 0–1 se acota.
"""

import dataclasses
import datetime as dt
import json
import os
import random
import struct
import unittest
from pathlib import Path

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender

protocol = import_geoblender("jobs.protocol")
messages = import_geoblender("jobs.messages")
version = import_geoblender("core.version")

JobError = messages.JobError

# El catálogo de tipos de trabajo: ``validate_request`` solo mira si el nombre está.
CATALOG = {"selftest": object(), "runtime_check": object()}
NOW = dt.datetime(2026, 10, 5, 14, 30, 12, 345678, tzinfo=dt.UTC)
LABEL = "Autodiagnóstico: suma por trozos"
PARAMS = {"op": "chunked_sum", "chunks": 20, "sleep_s": 0.5}


def _request(**changes):
    """Una petición válida del autodiagnóstico, con ``changes`` aplicados."""
    request = protocol.new_request(
        "selftest",
        label=LABEL,
        owner="jobs",
        params=PARAMS,
        inputs={"data": "in/data.npy"},
        environment="blender",
        timeout_s=600,
        grace_s=5,
        now=NOW,
    )
    return dataclasses.replace(request, **changes) if changes else request


def _files(root: Path) -> list[str]:
    """Todo lo que hay bajo ``root`` (ficheros y carpetas), relativo y ordenado."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _bits(value: float) -> bytes:
    return struct.pack("<d", value)


class NewRequestTest(unittest.TestCase):
    """``new_request``: una petición nueva con su identificador, versión y hora."""

    def test_new_request_has_what_the_job_needs(self):
        """RF-004-01: tipo de trabajo, parámetros, entradas, tiempo máximo, plazo de gracia,
        entorno, versión de Geoblender, hora de creación y un identificador
        ``AAAAMMDD_HHMMSS_xxxxxx`` de esa hora."""
        request = protocol.new_request(
            "selftest", label=LABEL, owner="jobs", params=PARAMS,
            inputs={"data": "in/data.npy"}, environment="blender", timeout_s=600, grace_s=5,
            project_uid="p-1", operation_uid="o-1", now=NOW,
        )
        self.assertEqual(request.schema, "geoblender.job/1")
        self.assertRegex(request.job_uid, r"\A20261005_143012_[0-9a-f]{6}\Z")
        self.assertEqual(request.worker, "selftest")
        self.assertEqual(request.label, LABEL)
        self.assertEqual(request.owner, "jobs")
        self.assertEqual(request.params, PARAMS)
        self.assertEqual(request.inputs, {"data": "in/data.npy"})
        self.assertEqual(request.timeout_s, 600.0)
        self.assertEqual(request.grace_s, 5.0)
        self.assertEqual(request.environment, "blender")
        self.assertEqual(request.project_uid, "p-1")
        self.assertEqual(request.operation_uid, "o-1")
        self.assertEqual(request.geoblender_version, version.geoblender_version())
        self.assertEqual(request.created_at, "2026-10-05T14:30:12.345Z")
        protocol.validate_request(request, catalog=CATALOG)

    def test_each_request_has_its_own_uid(self):
        """RF-004-01: mil peticiones del mismo segundo tienen identificadores distintos."""
        uids = {protocol.new_request("selftest", label=LABEL, owner="jobs", now=NOW).job_uid
                for _ in range(1000)}
        self.assertEqual(len(uids), 1000)

    def test_params_are_copied_as_json(self):
        """RF-004-01: la petición guarda una copia JSON de los parámetros (las tuplas, como
        listas); cambiar después el diccionario del módulo no la cambia."""
        params = {"lista": (1, 2.5, None, True, "ñ"), "anidado": {"a": [1, {"b": 2}]}}
        request = protocol.new_request("selftest", label=LABEL, owner="jobs", params=params,
                                       now=NOW)
        params["anidado"]["a"].append(3)
        params["nuevo"] = 1
        self.assertEqual(
            request.params, {"lista": [1, 2.5, None, True, "ñ"], "anidado": {"a": [1, {"b": 2}]}}
        )

    def test_params_that_are_not_json_are_rejected(self):
        """RF-004-01: un parámetro que no es JSON (una ruta, un conjunto, NaN, una clave que
        no es texto) se rechaza con ``request_invalid``, nombrando el trabajo."""
        for bad in ({"ruta": Path("in")}, {"conjunto": {1, 2}}, {"x": float("nan")},
                    {"x": [float("inf")]}, {1: "clave numérica"}, ["no", "es", "objeto"]):
            with self.subTest(bad=bad), self.assertRaises(JobError) as caught:
                protocol.new_request("selftest", label=LABEL, owner="jobs", params=bad, now=NOW)
            self.assertEqual(caught.exception.code, "request_invalid")
            self.assertIn(LABEL, caught.exception.text)

    def test_environment_and_timeout_come_from_the_job_type(self):
        """RF-004-01: sin entorno ni tiempo máximo, la petición no es válida hasta que el
        lanzador los toma del tipo de trabajo (3600 s si no declara ninguno, RF-004-11)."""
        draft = protocol.new_request("selftest", label=LABEL, owner="jobs", now=NOW)
        self.assertIsNone(draft.environment)
        self.assertIsNone(draft.timeout_s)
        self.assertEqual(draft.grace_s, 5.0)
        with self.assertRaises(JobError) as caught:
            protocol.validate_request(draft, catalog=CATALOG)
        self.assertEqual(caught.exception.code, "request_invalid")
        self.assertEqual(protocol.DEFAULT_TIMEOUT_S, 3600.0)
        ready = dataclasses.replace(
            draft, environment="blender", timeout_s=protocol.DEFAULT_TIMEOUT_S
        )
        protocol.validate_request(ready, catalog=CATALOG)


class RoundTripTest(unittest.TestCase):
    """``write_request`` y ``read_request``: la petición válida se lee idéntica."""

    def test_valid_request_is_read_back_identical(self):
        """RF-004-01: escrita en ``<raíz>/<job_uid>/request.json`` y leída, la petición es la
        misma; el fichero es UTF-8 sin BOM con «ñ» tal cual y LF, y no deja temporales."""
        request = _request(
            params={**PARAMS, "nota": "señal ñ «á»", "vacío": {}, "lista": [1, [2, [3]]]},
            project_uid="5b0c-proyecto",
        )
        protocol.validate_request(request, catalog=CATALOG)
        with _support.temp_jobs_root() as root:
            folder = root / request.job_uid
            folder.mkdir()
            protocol.write_request(folder, request)
            self.assertEqual(protocol.read_request(folder), request)
            self.assertEqual(_files(root), [request.job_uid, f"{request.job_uid}/request.json"])
            raw = (folder / "request.json").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        self.assertIn("señal ñ «á»".encode(), raw)
        data = json.loads(raw.decode("utf-8"))
        self.assertEqual(data["schema"], "geoblender.job/1")
        self.assertEqual(data["worker"], "selftest")
        self.assertEqual(data["inputs"], {"data": "in/data.npy"})
        self.assertEqual(data["timeout_s"], 600)
        self.assertEqual(data["geoblender_version"], version.geoblender_version())

    def test_decimals_are_read_bit_for_bit(self):
        """RF-004-01: los decimales de los parámetros (coordenadas UTM de 4,4 Mm, el menor
        subnormal, −0,0) vuelven idénticos bit a bit, sin pasar por float32."""
        values = [4400000.456, 700099.123456789, 1 / 3, 5e-324, -0.0, 1e308]
        request = _request(params={"valores": values, "x0": 4400000.456})
        with _support.temp_jobs_root() as root:
            folder = root / request.job_uid
            folder.mkdir()
            protocol.write_request(folder, request)
            back = protocol.read_request(folder)
        self.assertEqual([_bits(v) for v in back.params["valores"]], [_bits(v) for v in values])
        self.assertEqual(_bits(back.params["x0"]), _bits(4400000.456))

    def test_job_folder_object_with_path(self):
        """RF-004-01: ``write_request`` y ``read_request`` aceptan la carpeta del trabajo como
        ruta o como un objeto con ``path`` (el ``JobDir`` de ``jobs/paths.py``)."""
        request = _request()
        with _support.temp_jobs_root() as root:
            folder = root / request.job_uid
            folder.mkdir()
            holder = type("Holder", (), {"path": folder})()
            protocol.write_request(holder, request)
            self.assertEqual(protocol.read_request(holder), request)
            self.assertEqual(protocol.read_request(str(folder)), request)

    def test_request_is_not_written_to_another_folder(self):
        """RF-004-01: la carpeta de un trabajo es la de su identificador; escribir la petición
        en otra se rechaza (``request_invalid``) sin crear nada."""
        request = _request()
        with _support.temp_jobs_root() as root:
            other = root / "20261005_143012_000000"
            other.mkdir()
            with self.assertRaises(JobError) as caught:
                protocol.write_request(other, request)
            self.assertEqual(caught.exception.code, "request_invalid")
            self.assertEqual(_files(root), [other.name])


class InputPathTest(unittest.TestCase):
    """Entradas: relativas, dentro de ``in/``, sin ``..`` ni unidad (plan §5.2.2)."""

    def _rejected(self, path: str) -> JobError:
        with self.assertRaises(JobError) as caught:
            protocol.validate_request(_request(inputs={"data": path}), catalog=CATALOG)
        return caught.exception

    def test_absolute_or_drive_inputs_are_rejected(self):
        """RF-004-02: una entrada absoluta, con unidad, de red o con «:» se rechaza con
        ``request_path_outside_job``, y el mensaje nombra el trabajo y la ruta."""
        for path in ("C:/datos/x.npy", "C:\\datos\\x.npy", "c:in/x.npy", "/in/x.npy",
                     "\\in\\x.npy", "\\\\nas\\cu\\x.npy", "//nas/cu/x.npy",
                     "\\\\?\\C:\\in\\x.npy", "in/x.npy:flujo"):
            with self.subTest(path=path):
                error = self._rejected(path)
                self.assertEqual(error.code, "request_path_outside_job")
                self.assertEqual(error.values["path"], path)
                self.assertEqual(error.values["job"], LABEL)
                self.assertIn(LABEL, error.text)
                self.assertIn(path, error.text)

    def test_parent_references_are_rejected(self):
        """RF-004-02: una entrada con ``..`` (también con «\\» o con espacios detrás) se
        rechaza con ``request_path_outside_job``."""
        for path in ("../x.npy", "in/../out/x.npy", "in\\..\\..\\x.npy",
                     "in/sub/../../x.npy", "in/.. /x.npy", "in/.../x.npy"):
            with self.subTest(path=path):
                error = self._rejected(path)
                self.assertEqual(error.code, "request_path_outside_job")
                self.assertEqual(error.values["path"], path)

    def test_inputs_outside_in_are_rejected(self):
        """RF-004-02: una entrada que no está dentro de ``in/`` (``out/``, la carpeta del
        trabajo, ``in`` sola, un nombre que solo empieza por «in») es ``request_invalid``
        con el trabajo y la ruta en el mensaje."""
        for path in ("out/x.npy", "x.npy", "inside/x.npy", "in", "in/", "./in/x.npy",
                     "in//x.npy", "in/x.npy.", "in/a?b.npy", ""):
            with self.subTest(path=path):
                error = self._rejected(path)
                self.assertEqual(error.code, "request_invalid")
                self.assertIn(LABEL, error.text)
                self.assertIn(path, error.values["detail"])

    def test_inputs_inside_in_are_accepted(self):
        """RF-004-02: las entradas relativas dentro de ``in/`` se aceptan, con «/» o «\\»."""
        inputs = {"a": "in/data.npy", "b": "in\\sub\\data.npz", "c": "in/con espacio/ñ.parquet"}
        protocol.validate_request(_request(inputs=inputs), catalog=CATALOG)


class ProjectPathTest(unittest.TestCase):
    """Ningún texto de la petición contiene la ruta del proyecto (plan §5.2.2)."""

    def setUp(self):
        context = _support.jobs_tmp()
        base = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.jobs_root = base / "jobs"
        self.jobs_root.mkdir()
        self.project = _support.make_fake_project(base)
        self.before = self.project.fingerprints()

    def _assert_rejected(self, request, shown: str) -> None:
        with self.assertRaises(JobError) as caught:
            protocol.validate_request(request, catalog=CATALOG,
                                      forbidden_roots=[self.project.root])
        error = caught.exception
        self.assertEqual(error.code, "request_path_outside_job")
        self.assertEqual(error.values["path"], shown)
        self.assertIn(LABEL, error.text)
        self.assertEqual(_files(self.jobs_root), [])
        self.assertEqual(self.project.fingerprints(), self.before)

    def test_project_path_hidden_in_a_nested_param(self):
        """RF-004-02: la ruta del proyecto en un parámetro anidado se encuentra con «\\» o
        «/», con otras mayúsculas, con separadores dobles o con el prefijo ``\\\\?\\``."""
        root = str(self.project.root)
        variants = (
            root,
            self.project.root.as_posix(),
            root.upper(),
            root.lower().replace("\\", "/"),
            root.replace("\\", "\\\\"),
            "\\\\?\\" + root.swapcase(),
        )
        for variant in variants:
            text = f"--db={variant}\\project.gpkg"
            params = {"op": "x", "nivel": [1, {"más": {"hondo": [text]}}]}
            with self.subTest(variant=variant):
                self._assert_rejected(_request(params=params), text)

    def test_project_path_in_a_key_the_label_or_an_input(self):
        """RF-004-02: también en una clave de un parámetro, en el nombre visible o en el
        nombre de una entrada."""
        root = self.project.root.as_posix().upper()
        self._assert_rejected(_request(params={"a": {root: 1}}), root)
        self._assert_rejected(_request(label=f"{LABEL} {root}"), f"{LABEL} {root}")
        self._assert_rejected(_request(inputs={root: "in/x.npy"}), root)

    def test_other_texts_are_accepted(self):
        """RF-004-02: la carpeta madre del proyecto o un nombre relativo no son la ruta del
        proyecto: la petición se acepta."""
        params = {"madre": str(self.project.root.parent), "nombre": self.project.root.name}
        protocol.validate_request(_request(params=params), catalog=CATALOG,
                                  forbidden_roots=[self.project.root])

    def test_relative_forbidden_root_is_a_program_error(self):
        """RF-004-02: una raíz prohibida relativa no sirve para comparar: ``ValueError``."""
        with self.assertRaises(ValueError):
            protocol.validate_request(_request(), catalog=CATALOG,
                                      forbidden_roots=[Path("proyecto")])


class LimitsTest(unittest.TestCase):
    """Tiempo máximo en (0, 86 400] s y plazo de gracia en [1, 60] s (spec §8)."""

    def _code(self, **changes) -> JobError:
        with self.assertRaises(JobError) as caught:
            protocol.validate_request(_request(**changes), catalog=CATALOG)
        return caught.exception

    def test_timeout_out_of_range_is_rejected(self):
        """RF-004-02: ``timeout_s`` ≤ 0, > 86 400, no finito o que no es un número es
        ``request_invalid`` y el detalle nombra ``timeout_s``."""
        for value in (0, -1, 0.0, 86400.001, 86401, float("nan"), float("inf"),
                      float("-inf"), True, "600", None):
            with self.subTest(value=value):
                error = self._code(timeout_s=value)
                self.assertEqual(error.code, "request_invalid")
                self.assertIn("timeout_s", error.values["detail"])

    def test_timeout_limits_are_accepted(self):
        """RF-004-02: 0,001 s, 1 s y 86 400 s son tiempos máximos válidos."""
        for value in (0.001, 1, 86400, 86400.0):
            with self.subTest(value=value):
                protocol.validate_request(_request(timeout_s=value), catalog=CATALOG)

    def test_grace_out_of_range_is_rejected(self):
        """RF-004-02: ``grace_s`` fuera de 1–60 s, no finito o que no es un número es
        ``request_invalid`` y el detalle nombra ``grace_s``."""
        for value in (0, 0.999, 60.001, 61, -5, float("nan"), False, "5", None):
            with self.subTest(value=value):
                error = self._code(grace_s=value)
                self.assertEqual(error.code, "request_invalid")
                self.assertIn("grace_s", error.values["detail"])

    def test_grace_limits_are_accepted(self):
        """RF-004-02: 1 s, 5,5 s y 60 s son plazos de gracia válidos."""
        for value in (1, 5.5, 60, 60.0):
            with self.subTest(value=value):
                protocol.validate_request(_request(grace_s=value), catalog=CATALOG)


class SchemaAndWorkerTest(unittest.TestCase):
    """Esquema ``geoblender.job/1`` y tipo de trabajo del catálogo."""

    def test_unknown_schema_is_rejected(self):
        """RF-004-02: un esquema que no es ``geoblender.job/1`` es ``request_invalid``."""
        for schema in ("geoblender.job/2", "geoblender.job", ""):
            with self.subTest(schema=schema), self.assertRaises(JobError) as caught:
                protocol.validate_request(_request(schema=schema), catalog=CATALOG)
            self.assertEqual(caught.exception.code, "request_invalid")
            self.assertIn("geoblender.job/1", caught.exception.values["detail"])

    def test_unknown_worker_is_rejected(self):
        """RF-004-02: un tipo de trabajo que no está en el catálogo es ``worker_unknown``,
        con su nombre en el mensaje."""
        with self.assertRaises(JobError) as caught:
            protocol.validate_request(_request(worker="no_existe"), catalog=CATALOG)
        self.assertEqual(caught.exception.code, "worker_unknown")
        self.assertEqual(caught.exception.values["worker"], "no_existe")
        self.assertEqual(caught.exception.text, "No existe el tipo de trabajo «no_existe».")

    def test_malformed_worker_is_rejected_even_without_catalog(self):
        """RF-004-02: un nombre de tipo que no es ``<código>_<acción>`` en minúsculas (un
        módulo de otra carpeta, con punto, mayúsculas o salto de línea) es
        ``worker_unknown`` también al escribir la petición, que no tiene catálogo."""
        for worker in ("../selftest", "os.path", "Selftest", "selftest\n", "", "1selftest"):
            request = _request(worker=worker)
            with self.subTest(worker=worker), _support.temp_jobs_root() as root:
                folder = root / request.job_uid
                folder.mkdir()
                with self.assertRaises(JobError) as caught:
                    protocol.validate_request(request, catalog={worker: object()})
                self.assertEqual(caught.exception.code, "worker_unknown")
                with self.assertRaises(JobError) as caught:
                    protocol.write_request(folder, request)
                self.assertEqual(caught.exception.code, "worker_unknown")
                self.assertEqual(_files(root), [folder.name])

    def test_unknown_environment_is_rejected(self):
        """RF-004-02: el entorno es ``blender`` o ``compute``; otro es ``request_invalid``."""
        for environment in ("gpu", "Blender", "external"):
            with self.subTest(environment=environment), self.assertRaises(JobError) as caught:
                protocol.validate_request(_request(environment=environment), catalog=CATALOG)
            self.assertEqual(caught.exception.code, "request_invalid")


class ReadRequestTest(unittest.TestCase):
    """``read_request`` no acepta un ``request.json`` que no es una petición válida."""

    @classmethod
    def setUpClass(cls):
        # En la preparación y no al importar: crear la petición lee el manifiesto
        # (``BomHermeticTest``: ningún módulo de pruebas lo lee al importarse).
        cls.request = _request()

    def _read(self, content: bytes | None):
        """Lee ``content`` como ``request.json`` de la carpeta de :attr:`request`; comprueba
        que leer no crea ni cambia nada."""
        with _support.temp_jobs_root() as root:
            folder = root / self.request.job_uid
            folder.mkdir()
            if content is not None:
                (folder / "request.json").write_bytes(content)
            listing = _files(root)
            try:
                return protocol.read_request(folder)
            finally:
                self.assertEqual(_files(root), listing)

    def _read_error(self, content: bytes | None) -> JobError:
        with self.assertRaises(JobError) as caught:
            self._read(content)
        return caught.exception

    def _json(self, **changes) -> bytes:
        data = self.request.to_json()
        data.update(changes)
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def test_well_formed_file_is_read(self):
        """RF-004-01: un ``request.json`` bien formado (escrito por otro, sin sangría) se lee
        como la petición que contiene."""
        self.assertEqual(self._read(self._json()), self.request)

    def test_unreadable_files_are_request_invalid(self):
        """RF-004-02: sin ``request.json``, con bytes que no son JSON, con BOM, con ``NaN`` o
        con una lista en vez de un objeto: ``request_invalid``."""
        good = self._json()
        for content in (None, b"{no es json", b"\xef\xbb\xbf" + good,
                        good.replace(b'"chunks": 20', b'"chunks": NaN'), b"[1, 2]",
                        "{\"a\": \"\xf1\"}".encode("latin-1")):
            with self.subTest(content=content):
                self.assertEqual(self._read_error(content).code, "request_invalid")

    def test_other_schema_or_fields_are_request_invalid(self):
        """RF-004-02: otro esquema, un campo de más o de menos, un tipo cambiado o la
        petición de otro trabajo: ``request_invalid``."""
        data = self.request.to_json()
        missing = {key: value for key, value in data.items() if key != "timeout_s"}
        cases = (
            self._json(schema="geoblender.job/2"),
            self._json(extra=1),
            json.dumps(missing).encode(),
            self._json(params=[1, 2]),
            self._json(inputs={"data": 3}),
            self._json(label=7),
            self._json(job_uid="20261005_143012_000000"),
        )
        for content in cases:
            with self.subTest(content=content):
                self.assertEqual(self._read_error(content).code, "request_invalid")

    def test_unknown_schema_message_names_the_schema(self):
        """RF-004-02: el detalle del esquema desconocido nombra el que se esperaba."""
        error = self._read_error(self._json(schema="geoblender.job/2"))
        self.assertIn("geoblender.job/2", error.values["detail"])
        self.assertIn("geoblender.job/1", error.values["detail"])


class NoFilesTest(unittest.TestCase):
    """Ningún caso inválido crea ficheros (``Hecho cuando`` de la T03)."""

    def test_invalid_requests_create_no_files(self):
        """RF-004-02: cada petición inválida lanza ``JobError`` con su código al validarla y
        al escribirla, y no queda nada nuevo en la raíz de trabajos ni cambia el proyecto."""
        with _support.jobs_tmp() as base:
            project = _support.make_fake_project(base)
            before = project.fingerprints()
            root_text = project.root.as_posix().upper()
            # (cambios, código, ¿lo detecta también write_request, que no tiene catálogo?)
            cases = (
                ({"inputs": {"d": "C:/x.npy"}}, "request_path_outside_job", True),
                ({"inputs": {"d": "in/../x.npy"}}, "request_path_outside_job", True),
                ({"inputs": {"d": "out/x.npy"}}, "request_invalid", True),
                ({"inputs": {"d": "c:in/x.npy"}}, "request_path_outside_job", True),
                ({"params": {"a": [{"b": root_text}]}}, "request_path_outside_job", False),
                ({"timeout_s": 0}, "request_invalid", True),
                ({"timeout_s": 86401}, "request_invalid", True),
                ({"grace_s": 0.5}, "request_invalid", True),
                ({"grace_s": 61}, "request_invalid", True),
                ({"schema": "geoblender.job/2"}, "request_invalid", True),
                ({"worker": "no_existe"}, "worker_unknown", False),
                ({"worker": "os.path"}, "worker_unknown", True),
                ({"environment": "gpu"}, "request_invalid", True),
            )
            for changes, code, also_on_write in cases:
                request = _request(**changes)
                with self.subTest(changes=changes), _support.temp_jobs_root() as root:
                    folder = root / request.job_uid
                    folder.mkdir()
                    with self.assertRaises(JobError) as caught:
                        protocol.validate_request(request, catalog=CATALOG,
                                                  forbidden_roots=[project.root])
                    self.assertEqual(caught.exception.code, code)
                    if also_on_write:
                        with self.assertRaises(JobError) as caught:
                            protocol.write_request(folder, request)
                        self.assertEqual(caught.exception.code, code)
                    self.assertEqual(_files(root), [folder.name])
                    self.assertEqual(os.listdir(folder), [])
            self.assertEqual(project.fingerprints(), before)
            self.assertEqual(sorted(p.name for p in project.root.iterdir()),
                             ["blocks.duckdb", "project.gpkg"])


# --- Eventos (T04) ----------------------------------------------------------------------

SHA = "3fa9c2" * 10 + "0b1d"
TS = 1759674612.125


def _sample_events():
    """Un evento de cada tipo, con «ñ» y decimales que deben volver bit a bit."""
    return [
        protocol.JobEvent.start(
            {"pid": 4120, "kind": "blender", "python": "3.13.13", "numpy": "2.3.4",
             "blas": None},
            ts=TS,
        ),
        protocol.JobEvent.progress(0.42, "Trozo 9 de 20 · señal «ñ»", ts=TS + 1),
        protocol.JobEvent.log("warning", "Contacto descartado en el sondeo S-12", ts=TS + 1.5),
        protocol.JobEvent.result(
            [protocol.OutputRef("out/sum.npy", SHA, 136, "sum")],
            {"sum": 199990000, "x0": 4400000.456},
            ts=TS + 8.25,
        ),
        protocol.JobEvent.error(
            "engine_missing_orientation",
            msgid="Series {series} has no orientations",
            msg="La serie «Miocena» no tiene orientaciones",
            values={"series": "Miocena"},
            ts=TS + 8.5,
        ),
        protocol.JobEvent.cancelled("Cancelado en el trozo 11 de 20", ts=TS + 9),
    ]


def _line(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8") + b"\n"


def _decode_in_chunks(data: bytes, size: int, **options) -> list:
    """Decodifica ``data`` entregándolo en trozos de ``size`` bytes y cierra."""
    decoder = protocol.EventDecoder(**options)
    found = []
    for start in range(0, len(data), size):
        found.extend(decoder.feed(data[start:start + size]))
    found.extend(decoder.close())
    return found


def _shape(items: list) -> list:
    """Los eventos tal cual; de cada línea inválida, su texto."""
    return [("invalid", item.text) if isinstance(item, protocol.InvalidLine) else item
            for item in items]


class OutputRefTest(unittest.TestCase):
    """``OutputRef``: un resultado declarado, dentro de ``out/``, con su huella y tamaño."""

    def test_output_ref_round_trip(self):
        """RF-004-15: el resultado declarado (ruta relativa dentro de ``out/``, sha256 en 64
        cifras hexadecimales, tamaño en bytes y papel) se lee idéntico de su forma JSON."""
        ref = protocol.OutputRef("out/sub/señal ñ.npy", SHA, 0, "sum")
        data = ref.to_json()
        self.assertEqual(data, {"path": "out/sub/señal ñ.npy", "sha256": SHA, "size": 0,
                                "role": "sum"})
        self.assertEqual(protocol.OutputRef.from_json(json.loads(json.dumps(data))), ref)

    def test_invalid_output_refs_are_rejected(self):
        """RF-004-15: una ruta absoluta, con unidad, con ``..`` o fuera de ``out/``, una huella
        que no es sha256 en minúsculas, un tamaño negativo o que no es un entero y un papel
        vacío son ``ValueError``."""
        good = {"path": "out/x.npy", "sha256": SHA, "size": 8, "role": "sum"}
        cases = (
            {"path": "C:/datos/x.npy"}, {"path": "\\\\nas\\cu\\x.npy"}, {"path": "/out/x.npy"},
            {"path": "out/../in/x.npy"}, {"path": "in/x.npy"}, {"path": "x.npy"},
            {"path": "out"}, {"path": ""}, {"path": 3},
            {"sha256": SHA.upper()}, {"sha256": SHA[:-1]}, {"sha256": SHA + "0"},
            {"size": -1}, {"size": 1.5}, {"size": True}, {"size": "8"},
            {"role": ""}, {"role": None},
        )
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                protocol.OutputRef.from_json({**good, **change})
        for missing in good:
            data = {key: value for key, value in good.items() if key != missing}
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                protocol.OutputRef.from_json(data)
        with self.assertRaises(ValueError):
            protocol.OutputRef("C:/x.npy", SHA, 1, "sum")


class EncodeEventTest(unittest.TestCase):
    """``encode_event``: una línea JSON en UTF-8 por evento."""

    def test_each_event_is_one_utf8_line(self):
        """RF-004-15: cada evento se codifica en una sola línea UTF-8 (la «ñ» sin escapar)
        terminada en «\\n», que empieza por la versión, el tipo y la hora, y se decodifica
        idéntico (los decimales, bit a bit)."""
        for event in _sample_events():
            with self.subTest(type=event.type):
                line = protocol.encode_event(event)
                self.assertTrue(line.endswith(b"\n"))
                self.assertEqual(line.count(b"\n"), 1)
                self.assertNotIn(b"\r", line)
                data = json.loads(line.decode("utf-8"))
                self.assertEqual(list(data)[:3], ["v", "t", "ts"])
                self.assertEqual(data["v"], 1)
                self.assertEqual(data["t"], event.type)
                self.assertEqual(_bits(data["ts"]), _bits(event.ts))
                decoder = protocol.EventDecoder()
                self.assertEqual(decoder.feed(line), [event])
                self.assertEqual(decoder.close(), [])
        progress = protocol.encode_event(_sample_events()[1])
        self.assertIn("señal «ñ»".encode(), progress)

    def test_line_breaks_in_messages_stay_in_one_line(self):
        """RF-004-15: un mensaje con saltos de línea (o un texto con sustitutos sueltos, como
        un nombre de fichero mal descodificado) sigue siendo una sola línea y vuelve igual."""
        for msg in ("línea 1\nlínea 2\r\nlínea 3", "fichero \udcff.csv", "sep\u2028arador"):
            event = protocol.JobEvent.log("error", msg, ts=TS)
            line = protocol.encode_event(event)
            with self.subTest(msg=msg):
                self.assertEqual(line.count(b"\n"), 1)
                self.assertEqual(protocol.EventDecoder().feed(line), [event])

    def test_progress_outside_0_1_is_clamped(self):
        """RF-004-15 (y el caso límite de RF-004-06: el avance se acota): ``frac`` por debajo
        de 0 o por encima de 1 se guarda como 0 o 1."""
        for frac, expected in ((-0.5, 0.0), (1.2, 1.0), (0, 0.0), (1, 1.0), (0.5, 0.5)):
            with self.subTest(frac=frac):
                event = protocol.JobEvent.progress(frac, ts=TS)
                self.assertEqual(event.frac, expected)
                data = json.loads(protocol.encode_event(event))
                self.assertEqual(data["frac"], expected)

    def test_invalid_events_are_program_errors(self):
        """RF-004-15: un evento que no cumple el protocolo no se codifica: ``ValueError``
        (tipo o nivel desconocidos, avance NaN, información que no es JSON, sin mensaje de
        error, versión distinta de 1, hora no finita)."""
        cases = (
            lambda: protocol.JobEvent(type="finished", ts=TS),
            lambda: protocol.JobEvent.log("fatal", "x", ts=TS),
            lambda: protocol.JobEvent.progress(float("nan"), ts=TS),
            lambda: protocol.JobEvent.progress("0.5", ts=TS),
            lambda: protocol.JobEvent.start({"ruta": Path("in")}, ts=TS),
            lambda: protocol.JobEvent.error("x", msgid="X", msg=None, ts=TS),
            lambda: protocol.JobEvent.error("", msgid="X", msg="x", ts=TS),
            lambda: protocol.JobEvent(type="cancelled", ts=TS, v=2),
            lambda: protocol.JobEvent.cancelled(ts=float("inf")),
            lambda: protocol.JobEvent.result([{"path": "out/x.npy"}], ts=TS),
        )
        for index, build in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                protocol.encode_event(build())

    def test_too_long_event_is_rejected(self):
        """RF-004-15: un evento de más de ``MAX_EVENT_BYTES`` no se codifica (el decodificador
        no lo aceptaría): ``ValueError`` en el worker y no un resultado que se pierde."""
        event = protocol.JobEvent.log("info", "x" * protocol.MAX_EVENT_BYTES, ts=TS)
        with self.assertRaises(ValueError):
            protocol.encode_event(event)


class EventDecoderTest(unittest.TestCase):
    """``EventDecoder``: eventos en orden e ``InvalidLine`` sin lanzar."""

    def _stream(self) -> tuple[bytes, list]:
        """Bytes del canal con eventos, ruido y líneas inválidas, y lo que debe salir."""
        events = _sample_events()
        noise = "Setting Backend To: AUTO — «ñ»"
        future = {"v": 2, "t": "progress", "ts": TS, "frac": 0.5}
        parts = [
            protocol.encode_event(events[0]),
            noise.encode("utf-8") + b"\n",
            protocol.encode_event(events[1]).replace(b"\n", b"\r\n"),
            b"\n   \n",
            _line(future),
            protocol.encode_event(events[2]),
            protocol.encode_event(events[3]),
            b'{"v": 1, "t": "progress", "ts": 1.0, "frac": 0.5\n',
            protocol.encode_event(events[4]),
            protocol.encode_event(events[5]),
        ]
        expected = [
            events[0], ("invalid", noise), events[1], ("invalid", json.dumps(future)),
            events[2], events[3], ("invalid", '{"v": 1, "t": "progress", "ts": 1.0, "frac": 0.5'),
            events[4], events[5],
        ]
        return b"".join(parts), expected

    def test_events_come_out_in_order_whatever_the_reads(self):
        """RF-004-15: los eventos salen en el orden de llegada, y las líneas inválidas en su
        sitio como ``InvalidLine``, tanto si llega todo de una vez como byte a byte o en trozos
        que parten las líneas (y las «ñ») por cualquier sitio."""
        data, expected = self._stream()
        for size in (1, 2, 3, 5, 7, 13, 64, 4096, len(data)):
            with self.subTest(size=size):
                self.assertEqual(_shape(_decode_in_chunks(data, size)), expected)

    def test_utf8_split_between_reads(self):
        """RF-004-15: una «ñ» partida entre dos lecturas (sus dos bytes por separado) llega
        entera en el mensaje."""
        line = protocol.encode_event(protocol.JobEvent.progress(0.5, "año", ts=TS))
        cut = line.index("ñ".encode()) + 1
        decoder = protocol.EventDecoder()
        self.assertEqual(decoder.feed(line[:cut]), [])
        found = decoder.feed(line[cut:])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].msg, "año")

    def test_not_json_lines_are_invalid_lines(self):
        """RF-004-15: lo que no es un evento JSON (texto de una librería, JSON cortado, una
        lista, ``NaN``, bytes que no son UTF-8, BOM) es una ``InvalidLine`` con el texto y el
        motivo, sin lanzar."""
        lines = (
            b"Setting Backend To: AUTO",
            b'{"v": 1, "t": "progress"',
            b"[1, 2]",
            b'{"v": 1, "t": "progress", "ts": 1.0, "frac": NaN}',
            b'"texto"',
            b"\xff\xfe\xc3",
            b"\xef\xbb\xbf" + protocol.encode_event(protocol.JobEvent.cancelled(ts=TS)).strip(),
        )
        for raw in lines:
            with self.subTest(raw=raw):
                found = protocol.EventDecoder().feed(raw + b"\n")
                self.assertEqual(len(found), 1)
                self.assertIsInstance(found[0], protocol.InvalidLine)
                self.assertEqual(found[0].text, raw.decode("utf-8", "replace"))
                self.assertTrue(found[0].reason)

    def test_unknown_version_is_an_invalid_line(self):
        """RF-004-15: un evento de otra versión (``"v": 2``), sin versión o con una versión
        que no es un entero es una ``InvalidLine`` cuyo motivo cita la versión."""
        base = {"t": "progress", "ts": TS, "frac": 0.5}
        for version in (2, 0, "1", True, 1.0, None):
            data = {"v": version, **base}
            with self.subTest(version=version):
                found = protocol.EventDecoder().feed(_line(data))
                self.assertIsInstance(found[0], protocol.InvalidLine)
                self.assertIn("versión", found[0].reason)
        found = protocol.EventDecoder().feed(_line(base))
        self.assertIsInstance(found[0], protocol.InvalidLine)
        self.assertIn("versión", found[0].reason)

    def test_progress_outside_0_1_is_clamped_when_decoded(self):
        """RF-004-15 (y el caso límite de RF-004-06): un avance por debajo de 0 o por encima
        de 1 (también 1e400, que JSON lee como infinito) llega acotado a 0–1; uno que no es un
        número es una ``InvalidLine``."""
        for frac, expected in ((-0.25, 0.0), (1.5, 1.0), (100, 1.0), (-1e400, 0.0),
                               (1e400, 1.0), (0.42, 0.42)):
            raw = b'{"v": 1, "t": "progress", "ts": 1.5, "frac": ' + repr(frac).encode()
            raw = raw.replace(b"inf", b"1e400") + b"}\n"
            with self.subTest(frac=frac):
                found = protocol.EventDecoder().feed(raw)
                self.assertIsInstance(found[0], protocol.JobEvent)
                self.assertEqual(found[0].frac, expected)
        for bad in ('"0.5"', "true", "null", "[0.5]"):
            raw = f'{{"v": 1, "t": "progress", "ts": 1.5, "frac": {bad}}}\n'.encode()
            with self.subTest(frac=bad):
                found = protocol.EventDecoder().feed(raw)
                self.assertIsInstance(found[0], protocol.InvalidLine)

    def test_malformed_events_are_invalid_lines(self):
        """RF-004-12, RF-004-15: un tipo desconocido, sin hora, un error sin código o sin
        mensaje, un nivel desconocido o un resultado con una salida fuera de ``out/`` son
        ``InvalidLine``: el trabajo sigue y el lanzador decide (``protocol_no_result``)."""
        cases = (
            {"v": 1, "t": "finished", "ts": TS},
            {"v": 1, "t": "progress", "frac": 0.5},
            {"v": 1, "t": "progress", "ts": "ayer", "frac": 0.5},
            {"v": 1, "t": "error", "ts": TS, "msgid": "X", "msg": "x"},
            {"v": 1, "t": "error", "ts": TS, "code": "x", "msgid": "X"},
            {"v": 1, "t": "log", "ts": TS, "level": "fatal", "msg": "x"},
            {"v": 1, "t": "start", "ts": TS},
            {"v": 1, "t": "result", "ts": TS,
             "outputs": [{"path": "C:/x.npy", "sha256": SHA, "size": 1, "role": "x"}]},
            {"v": 1, "t": "result", "ts": TS, "outputs": "out/x.npy"},
        )
        for data in cases:
            with self.subTest(data=data):
                found = protocol.EventDecoder().feed(_line(data))
                self.assertEqual(len(found), 1)
                self.assertIsInstance(found[0], protocol.InvalidLine)

    def test_error_event_keeps_code_msgid_values_and_text(self):
        """RF-004-12: el evento de error del worker llega con su código, su ``msgid``, sus
        valores y su texto en español, para el registro y la interfaz."""
        event = protocol.EventDecoder().feed(protocol.encode_event(_sample_events()[4]))[0]
        self.assertEqual(event.code, "engine_missing_orientation")
        self.assertEqual(event.msgid, "Series {series} has no orientations")
        self.assertEqual(event.values, {"series": "Miocena"})
        self.assertEqual(event.msg, "La serie «Miocena» no tiene orientaciones")

    def test_extra_keys_are_ignored(self):
        """RF-004-15: una clave de más en un evento de la versión 1 no lo invalida."""
        data = {"v": 1, "t": "progress", "ts": TS, "frac": 0.5, "msg": "x", "otra": [1]}
        found = protocol.EventDecoder().feed(_line(data))
        self.assertEqual(found, [protocol.JobEvent.progress(0.5, "x", ts=TS)])

    def test_too_long_lines_are_dropped_without_memory_growth(self):
        """RF-004-15: una línea más larga que el máximo (también si llega por partes, sin
        salto de línea todavía) da una sola ``InvalidLine`` y la siguiente se decodifica."""
        good = protocol.encode_event(protocol.JobEvent.cancelled("fin", ts=TS))
        long = b"x" * 500
        for size in (7, 64, 10_000):
            with self.subTest(size=size):
                found = _decode_in_chunks(long + b"\n" + good, size, max_line_bytes=128)
                self.assertEqual(len(found), 2)
                self.assertIsInstance(found[0], protocol.InvalidLine)
                self.assertLessEqual(len(found[0].text), 256)
                self.assertEqual(found[1], protocol.JobEvent.cancelled("fin", ts=TS))

    def test_close_decodes_the_last_line_without_newline(self):
        """RF-004-15: al cerrar, lo que quedó sin «\\n» se decodifica: un evento completo
        sale como evento y uno cortado (el worker murió a medias) como ``InvalidLine``;
        cerrar dos veces no da nada más y alimentar después es un error del programa."""
        line = protocol.encode_event(protocol.JobEvent.cancelled("fin", ts=TS))
        decoder = protocol.EventDecoder()
        self.assertEqual(decoder.feed(line.rstrip(b"\n")), [])
        self.assertEqual(decoder.close(), [protocol.JobEvent.cancelled("fin", ts=TS)])
        self.assertEqual(decoder.close(), [])
        with self.assertRaises(ValueError):
            decoder.feed(b"{}\n")
        decoder = protocol.EventDecoder()
        decoder.feed(line[:10])
        found = decoder.close()
        self.assertEqual(len(found), 1)
        self.assertIsInstance(found[0], protocol.InvalidLine)
        self.assertEqual(protocol.EventDecoder().close(), [])

    def test_random_bytes_never_raise(self):
        """RF-004-15: bytes al azar, en trozos al azar, nunca hacen lanzar al decodificador:
        solo devuelve ``JobEvent`` o ``InvalidLine``."""
        generator = random.Random(4004)
        alphabet = b'{}[]":,.0123456789-eE ntrufals\\\n\r\xc3\xb1\xff' + b"vtfrac"
        for _ in range(50):
            data = bytes(generator.choice(alphabet) for _ in range(generator.randint(0, 400)))
            decoder = protocol.EventDecoder()
            found = []
            position = 0
            while position < len(data):
                step = generator.randint(1, 40)
                found.extend(decoder.feed(data[position:position + step]))
                position += step
            found.extend(decoder.close())
            for item in found:
                self.assertIsInstance(item, protocol.JobEvent | protocol.InvalidLine)


if __name__ == "__main__":
    unittest.main()
