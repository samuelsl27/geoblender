# SPDX-License-Identifier: GPL-3.0-or-later
"""Claves desconocidas de la cabecera (spec 002, T49; RF-002-05, RF-002-06, RF-002-18;
D-10 y D-13; plan 002 §5.2; formato-proyecto §2).

Geoblender escribe exactamente los campos de ``manifest.json`` (``test_exact_keys``, T43),
pero una persona puede anotar en la cabecera, o la puede haber escrito otra versión. Una
clave que no es del formato, en el primer nivel o dentro de ``crs``, ``crs.vertical``,
``geo_origin``, ``stores`` o ``stores.project``, no impide abrir: se avisa de ella (también
en solo lectura, sin escribir nada) y se conserva, con su valor, en su objeto y después de
las conocidas, cada vez que se regenera la cabecera (D-10). Si la clave o su valor lleva una
ruta absoluta, el aviso lo dice y al regenerar la cabecera se descarta: Geoblender no
escribe rutas absolutas en ella (D-13, RF-002-18).
"""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from tests.support.core_fixtures import FakeClock, FakePids, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
checkout = import_geoblender("core.project.checkout")
model = import_geoblender("core.project.model")
manifest = import_geoblender("core.project.manifest")
schema = import_geoblender("core.project.schema")
gpkg = import_geoblender("core.gpkg")
paths = import_geoblender("core.paths")
userdata_mod = import_geoblender("core.userdata")

SESSION_A = make_session()
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra", pid=777
)
TOP_KEYS = (
    "format", "schema_version", "min_reader_schema", "geoblender_version", "created_with",
    "project_uid", "name", "crs", "geo_origin", "grid_step_m", "created_at", "modified_at",
    "stores", "inventory", "checkout",
)
CRS_KEYS = ("epsg", "name", "wkt", "vertical")
NOTE = "Revisar el límite norte con topografía"
SOURCE = {"fuente": "ICV", "hoja": 571, "datos": ["MDT 2 m", "ortofoto"]}
# Una ruta absoluta sintética: Geoblender no la escribe nunca en la cabecera (D-13).
ABSOLUTE = "ver D:\\datos\\sondeos.csv"
NEW_WINDOW = (700_500.4, 4_399_500.6, 701_500.2, 4_400_500.9)
LOGGER = "geoblender.core.project"


def _set(data: dict, dotted: str, value: object) -> None:
    node = data
    *parents, last = dotted.split(".")
    for part in parents:
        node = node[part]
    node[last] = value


def _edit_header(root: Path, changes: dict[str, object]) -> None:
    """Añade a mano a ``manifest.json`` las claves de ``changes`` (``crs.origen_datos``…)."""
    path = root / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for dotted, value in changes.items():
        _set(data, dotted, value)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _header(root: Path) -> dict:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def _record(root: Path):
    with gpkg.GpkgConnection.open_read(root / "project.gpkg") as db:
        return schema.read_project(db.connection)


def _snapshot(root: Path) -> dict[str, object]:
    found: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            found[rel] = "carpeta"
        else:
            stat = path.stat()
            found[rel] = (stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(),
                          stat.st_mtime_ns)
    return found


def _unknown_warnings(warnings) -> list[str]:
    return [item for item in warnings if "no conoce" in item]


class Env:
    """Un proyecto local de la sesión A, cerrado, con una carpeta de copias locales."""

    def __init__(self, tmp: Path) -> None:
        self.parent = tmp / "proyectos"
        self.parent.mkdir()
        self.dest = tmp / "copias"
        self.dest.mkdir()
        self.userdata = userdata_mod.UserData(tmp / "datos_usuario")
        self.clock = FakeClock()
        self.pids = FakePids({SESSION_A.pid, SESSION_B.pid})
        created = create.create_project(
            self.parent, make_settings(), SESSION_A, self.userdata, clock=self.clock
        )
        self.root = created.root
        created.project.close()

    def open(self, root: Path, session, **kwargs):
        return open_mod.open_project(
            root, session, self.userdata, clock=self.clock, pid_alive=self.pids, **kwargs
        )

    def run(self, steps):
        result = None
        for step in steps:
            if step.result is not None:
                result = step.result
        return result

    def checkout(self):
        return self.run(checkout.checkout_steps(
            self.root, self.dest, SESSION_A, self.userdata, clock=self.clock,
            pid_alive=self.pids,
        ))

    def publish(self, local):
        return self.run(checkout.publish_steps(
            local, SESSION_A, self.userdata, clock=self.clock, pid_alive=self.pids
        ))


class ParseTest(unittest.TestCase):
    def _data(self) -> dict:
        record = _record_values()
        return manifest.manifest_from_record(record).to_dict()

    def test_kept_in_their_object_after_the_known_ones(self) -> None:
        """RF-002-05 (D-10): al leer, cada clave desconocida del primer nivel y de ``crs``,
        ``crs.vertical``, ``geo_origin``, ``stores`` y ``stores.project`` se guarda con su
        ruta y su valor JSON tal cual; al escribir, va en su objeto, después de las
        conocidas y en su orden; la cabecera regenerada desde la base las conserva y
        ``compare`` sigue en CONSISTENT."""
        data = self._data()
        changes = {  # en el orden en que aparecen en el documento
            "crs.vertical.comentario": None,
            "crs.origen_datos": SOURCE,
            "geo_origin.marca": [1, 2.5, True],
            "stores.project.comprobado": True,
            "stores.otro": {"path": "otro.db"},
            "nota": NOTE,
            "z_numero": 7,
        }
        for dotted, value in changes.items():
            _set(data, dotted, value)
        header = manifest.parse_manifest(copy.deepcopy(data))
        self.assertEqual([(item.path, item.value) for item in header.extra], list(changes.items()))
        for written in (header, manifest.manifest_from_record(_record_values(), previous=header)):
            with self.subTest(regenerada=written is not header):
                out = json.loads(manifest.manifest_text(written))
                self.assertEqual(list(out), [*TOP_KEYS, "nota", "z_numero"])
                self.assertEqual(list(out["crs"]), [*CRS_KEYS, "origen_datos"])
                self.assertEqual(list(out["crs"]["vertical"]), ["epsg", "name", "note", "comentario"])
                self.assertEqual(list(out["geo_origin"]), ["x0", "y0", "z0", "marca"])
                self.assertEqual(list(out["stores"]), ["project", "otro"])
                self.assertEqual(list(out["stores"]["project"]),
                                 ["path", "gpkg_version", "comprobado"])
                self.assertEqual(out, data)
        rewritten = manifest.manifest_from_record(_record_values(), previous=header)
        self.assertEqual(rewritten.extra, header.extra)
        self.assertIs(manifest.compare(rewritten, _record_values()).status,
                      manifest.ManifestStatus.CONSISTENT)

    def test_known_header_has_no_extra(self) -> None:
        """RF-002-05: una cabecera con solo los campos del formato no tiene claves
        desconocidas (``stores.blocks`` es del formato: formato-proyecto §2)."""
        data = self._data()
        self.assertEqual(manifest.parse_manifest(data).extra, ())
        data["stores"]["blocks"] = {"path": "blocks.duckdb", "duckdb_version": "1.5.6"}
        header = manifest.parse_manifest(data)
        self.assertEqual(header.extra, ())
        self.assertEqual(json.loads(manifest.manifest_text(header))["stores"], data["stores"])

    def test_absolute_path_is_never_written(self) -> None:
        """RF-002-18 (D-13): una clave desconocida cuyo valor (también dentro de una lista
        o de un objeto) o cuyo nombre lleva una ruta absoluta se lee, se marca como
        descartada con la ruta que lleva y no se escribe ni se regenera; las demás se
        conservan. Una ruta relativa o «m/s» no es una ruta absoluta."""
        data = self._data()
        _set(data, "crs.fuentes", ["relativa/datos.csv", {"en": "\\\\servidor\\datos\\x.tif"}])
        data["geo_origin"]["D:\\clave"] = 1  # la ruta, en el nombre de la clave
        _set(data, "stores.unidades", "m/s")
        _set(data, "nota", NOTE)
        _set(data, "origen", ABSOLUTE)
        header = manifest.parse_manifest(data)
        discarded = [(item.path, item.discarded) for item in header.extra]
        self.assertEqual(discarded, [("crs.fuentes", True), ("geo_origin.D:\\clave", True),
                                     ("stores.unidades", False), ("nota", False),
                                     ("origen", True)])
        origin = next(item for item in header.extra if item.path == "origen")
        self.assertEqual(origin.absolute_paths, ("D:\\datos\\sondeos.csv",))
        for written in (header, manifest.manifest_from_record(_record_values(), previous=header)):
            with self.subTest(regenerada=written is not header):
                out = json.loads(manifest.manifest_text(written))
                self.assertEqual(paths.find_absolute_paths(out), [])
                self.assertEqual(out["nota"], NOTE)
                self.assertEqual(out["stores"]["unidades"], "m/s")
                self.assertNotIn("origen", out)
                self.assertNotIn("fuentes", out["crs"])
                self.assertEqual(list(out["geo_origin"]), ["x0", "y0", "z0"])
        rewritten = manifest.manifest_from_record(_record_values(), previous=header)
        self.assertEqual([item.path for item in rewritten.extra], ["stores.unidades", "nota"])


def _record_values():
    catalog = import_geoblender("core.georef").load_catalog()
    crs, vcrs = catalog.horizontal(25830), catalog.vertical(5782)
    return model.ProjectRecord(
        uid="00000000-0000-4000-8000-0000000000aa", name="Cantera Prueba", schema_version=1,
        min_reader_schema=1, created_with="0.1.0", last_written_with="0.1.0",
        crs_epsg=crs.epsg, crs_name=crs.name, crs_wkt=crs.wkt2, vcrs_epsg=vcrs.epsg,
        vcrs_name=vcrs.name, vcrs_wkt=vcrs.wkt2, vcrs_note=None, origin_x=700_000,
        origin_y=4_400_000, origin_z=0, grid_step_m=1.0, window_xmin=699_500.0,
        window_ymin=4_399_500.0, window_xmax=700_501.0, window_ymax=4_400_501.0,
        created_at="2026-10-05T08:12:44.000Z", modified_at="2026-10-05T17:03:10.000Z",
    )


class ProjectLifecycleTest(unittest.TestCase):
    def _assert_kept(self, root: Path) -> None:
        data = _header(root)
        self.assertEqual(list(data), [*TOP_KEYS, "nota"])
        self.assertEqual(data["nota"], NOTE)
        self.assertEqual(list(data["crs"]), [*CRS_KEYS, "origen_datos"])
        self.assertEqual(data["crs"]["origen_datos"], SOURCE)
        self.assertIs(
            manifest.compare(manifest.read_manifest(root), _record(root)).status,
            manifest.ManifestStatus.CONSISTENT,
        )

    def _assert_named(self, warnings, logged) -> None:
        unknown = _unknown_warnings(warnings)
        self.assertEqual(len(unknown), 2, warnings)
        self.assertTrue(any("«nota»" in item for item in unknown), unknown)
        self.assertTrue(any("«crs.origen_datos»" in item for item in unknown), unknown)
        self.assertTrue(all("se conserva" in item for item in unknown), unknown)
        lines = "\n".join(logged.output)
        self.assertIn("«nota»", lines)
        self.assertIn("«crs.origen_datos»", lines)

    def test_open_warns_and_every_regeneration_keeps_them(self) -> None:
        """RF-002-05, RF-002-06 (D-10): una cabecera con ``"nota"`` en el primer nivel y
        ``"origen_datos"`` dentro de ``crs`` abre en escritura con dos avisos que las
        nombran (y su línea en el registro técnico) sin reescribir la cabecera; tras
        «Ventana de trabajo», tras cerrar y tras sacar copia y publicar, la cabecera las
        conserva con el mismo valor, en su objeto y después de las conocidas, y ``compare``
        sigue en CONSISTENT."""
        with project_tmp() as tmp:
            env = Env(tmp)
            _edit_header(env.root, {"nota": NOTE, "crs.origen_datos": SOURCE})
            before = (env.root / "manifest.json").read_bytes()
            with self.assertLogs(LOGGER, "WARNING") as logged:
                result = env.open(env.root, SESSION_B)
            project = result.project
            self.assertIs(project.mode, model.OpenMode.WRITE_LOCAL)
            self.assertEqual(len(result.warnings), 2, result.warnings)
            self._assert_named(result.warnings, logged)
            self.assertEqual((env.root / "manifest.json").read_bytes(), before)
            project.set_window(NEW_WINDOW, 1.0, 0, "Ampliación hacia el este")
            self._assert_kept(env.root)
            self.assertEqual(_header(env.root)["geo_origin"]["x0"], 701_000)
            project.close()
            self._assert_kept(env.root)
            with self.assertLogs(LOGGER, "WARNING") as logged:
                taken = env.checkout()  # abre la copia local: los mismos avisos
            local = taken.opened.project
            self._assert_kept(local.root)
            self._assert_named(taken.opened.warnings, logged)
            env.publish(local)
            self._assert_kept(env.root)
            self.assertIsNone(_header(env.root)["checkout"])

    def test_read_only_warns_without_writing(self) -> None:
        """RF-002-05, RF-002-13: en solo lectura, los mismos avisos y nada escrito en la
        carpeta del proyecto (nombres, tamaños, sha256 y fechas) al abrir y al cerrar."""
        with project_tmp() as tmp:
            env = Env(tmp)
            _edit_header(env.root, {"nota": NOTE, "crs.origen_datos": SOURCE})
            before = _snapshot(env.root)
            with self.assertLogs(LOGGER, "WARNING") as logged:
                result = env.open(env.root, SESSION_B, want_write=False)
            self.assertIs(result.project.mode, model.OpenMode.READ_ONLY)
            self._assert_named(result.warnings, logged)
            result.project.close()
            self.assertEqual(_snapshot(env.root), before)

    def test_absolute_path_key_is_discarded_with_its_reason(self) -> None:
        """RF-002-05, RF-002-18 (D-13): una clave desconocida cuyo valor lleva una ruta
        absoluta abre con un aviso que la nombra y dice el motivo; al regenerar la cabecera
        (aquí, al abrir: la cabecera difería en ``modified_at``) se descarta, y la otra
        clave desconocida se conserva; al cerrar, igual."""
        with project_tmp() as tmp:
            env = Env(tmp)
            _edit_header(env.root, {
                "nota": NOTE, "origen": ABSOLUTE, "modified_at": "2026-10-05T07:00:00.000Z",
            })
            with self.assertLogs(LOGGER, "WARNING") as logged:
                result = env.open(env.root, SESSION_B)
            unknown = _unknown_warnings(result.warnings)
            self.assertEqual(len(unknown), 2, result.warnings)
            dropped = next(item for item in unknown if "«origen»" in item)
            self.assertIn("ruta absoluta", dropped)
            self.assertIn("se descarta", dropped)
            kept = next(item for item in unknown if "«nota»" in item)
            self.assertIn("se conserva", kept)
            self.assertIn("«origen»", "\n".join(logged.output))
            self._assert_discarded(env.root)
            result.project.close()
            self._assert_discarded(env.root)

    def _assert_discarded(self, root: Path) -> None:
        data = _header(root)
        self.assertEqual(list(data), [*TOP_KEYS, "nota"])
        self.assertEqual(data["nota"], NOTE)
        self.assertEqual(paths.find_absolute_paths(data), [])


if __name__ == "__main__":
    unittest.main()
