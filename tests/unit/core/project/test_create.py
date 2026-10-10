# SPDX-License-Identifier: GPL-3.0-or-later
"""Crear un proyecto (spec 002, T15; RF-002-01, RF-002-02, RF-002-03, RF-002-08,
RF-002-18, RF-002-23, RF-002-24, RF-002-26; plan 002 §5.3 y §5.4).

Crear deja la carpeta ``<Nombre>.gbproj`` con ``manifest.json``, ``project.gpkg``,
``.lock`` y las subcarpetas ``rasters/``, ``meshes/``, ``snapshots/``, ``scenes/`` y
``exports/``, con el cerrojo de la sesión. Todo se crea en una carpeta temporal junto al
destino y se renombra al final: un fallo en cualquier paso no deja ni el proyecto ni la
temporal. Se valida antes de tocar el disco: nombre válido en Windows, CRS del catálogo
(siempre indicado: el diálogo propone EPSG:25830 y EPSG:5782; o una referencia local con
descripción), ventana no
vacía, con los ejes en su sitio y dentro del ámbito del CRS, paso de rejilla y Z0. La
ventana se amplía a la unidad de alineación del paso y el GeoOrigin sale de su centro; si
la ventana pasa de ±8 km del origen, se crea con aviso.
"""

import json
import os
import re
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from tests.support.core_fixtures import (
    EXPECTED_ORIGIN,
    FakeClock,
    FakePids,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
events = import_geoblender("core.project.events")
model = import_geoblender("core.project.model")
manifest = import_geoblender("core.project.manifest")
schema = import_geoblender("core.project.schema")
lock = import_geoblender("core.project.lock")
errors = import_geoblender("core.errors")
gpkg = import_geoblender("core.gpkg")
georef = import_geoblender("core.georef")
paths = import_geoblender("core.paths")
userdata_mod = import_geoblender("core.userdata")

SESSION = make_session()
EXPECTED_ENTRIES = [
    ".lock",
    "exports",
    "manifest.json",
    "meshes",
    "project.gpkg",
    "rasters",
    "scenes",
    "snapshots",
]
STEPS = ("_make_folders", "_create_database", "_write_header", "_acquire_lock", "_publish")


def _make(tmp: Path, **overrides):
    parent = tmp / "proyectos"
    parent.mkdir(exist_ok=True)
    userdata = userdata_mod.UserData(tmp / "datos_usuario")
    return create.create_project(
        parent, make_settings(**overrides), SESSION, userdata, clock=FakeClock()
    )


def _deep_folder(tmp: Path, length: int) -> Path:
    """Una carpeta (creada) dentro de ``tmp`` cuya ruta mide ``length`` caracteres (±1)."""
    folder = tmp
    while len(str(folder)) < length - 1:
        room = length - len(str(folder)) - 1  # el separador
        folder = folder / ("c" * min(40, room))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _compact(text: str) -> str:
    """``text`` sin espacios (también el fino de miles), para buscar cifras."""
    return "".join(text.split()).replace(" ", "").replace(" ", "")


def _text_cells(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        found: list[str] = []
        for table in tables:
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                found.extend(value for value in row if isinstance(value, str))
        return found
    finally:
        conn.close()


class CreateTest(unittest.TestCase):
    def test_structure_and_open_for_writing(self) -> None:
        """RF-002-01: la carpeta contiene exactamente ``manifest.json``,
        ``project.gpkg``, ``.lock``, ``rasters/``, ``meshes/``, ``snapshots/``,
        ``scenes/`` y ``exports/``; el cerrojo es de la sesión y la cabecera coincide con
        la base de datos."""
        with project_tmp() as tmp:
            result = _make(tmp)
            self.assertEqual(result.root, tmp / "proyectos" / "Cantera Prueba.gbproj")
            self.assertEqual(sorted(p.name for p in result.root.iterdir()), EXPECTED_ENTRIES)
            for folder in ("rasters", "meshes", "snapshots", "scenes", "exports"):
                self.assertTrue((result.root / folder).is_dir())
            self.assertEqual(sorted(p.name for p in result.root.parent.iterdir()),
                             ["Cantera Prueba.gbproj"])
            status = lock.inspect(result.root, SESSION, clock=FakeClock(), pid_alive=FakePids())
            self.assertEqual(status.state, lock.LockState.OURS)
            self.assertEqual(status.holder.mode, lock.LockMode.LOCAL)
            self.assertEqual(result.lock, status.holder)
            header = manifest.read_manifest(result.root)
            with gpkg.GpkgConnection.open_read(result.root / "project.gpkg") as db:
                record = schema.read_project(db.connection)
                self.assertEqual(
                    schema.missing_objects(db.connection, schema.SCHEMA_VERSION), []
                )
                self.assertEqual(
                    db.connection.execute("PRAGMA journal_mode").fetchone()[0], "delete"
                )
            self.assertEqual(record, result.record)
            self.assertEqual(manifest.compare(header, record).status,
                             manifest.ManifestStatus.CONSISTENT)

    def test_georeference_stored(self) -> None:
        """RF-002-23, RF-002-24: se guardan el código, el nombre y la definición del CRS
        horizontal y vertical del catálogo; la ventana ampliada a la unidad de alineación
        y el GeoOrigin de su centro; el paso y Z0."""
        catalog = georef.load_catalog()
        with project_tmp() as tmp:
            record = _make(tmp).record
            self.assertEqual(
                (record.crs_epsg, record.crs_name, record.crs_wkt),
                (25830, catalog.horizontal(25830).name, catalog.horizontal(25830).wkt2),
            )
            vertical = catalog.vertical(5782)
            self.assertEqual(
                (record.vcrs_epsg, record.vcrs_name, record.vcrs_wkt, record.vcrs_note),
                (5782, vertical.name, vertical.wkt2, None),
            )
            self.assertEqual(record.origin.as_tuple(), EXPECTED_ORIGIN)
            self.assertEqual(
                record.window, georef.Window(699_500.0, 4_399_500.0, 700_501.0, 4_400_501.0)
            )
            # El esquema de esta versión (el 2 desde la spec 008).
            self.assertEqual(
                (record.grid_step_m, record.schema_version), (1.0, schema.SCHEMA_VERSION)
            )
            self.assertEqual(record.created_with, "0.1.0")
            self.assertEqual(record.created_at, "2026-10-05T08:12:44.000Z")
        with project_tmp() as tmp:
            record = _make(tmp, grid_step_m=1.5, z0=-180).record
            self.assertEqual(record.window, georef.Window(699_498.0, 4_399_500.0, 700_503.0, 4_400_502.0))
            self.assertEqual(record.origin.as_tuple(), (700_000, 4_400_000, -180))

    def test_origin_from_the_aligned_window(self) -> None:
        """RF-002-24 (hueco de prueba I6 de la verificación; convergencia, T52): el
        GeoOrigin sale del centro de la ventana ya ampliada, no de la tecleada. X de
        700 000,0 a 700 099,6 con paso 1 → ventana 700 000–700 100, centro 700 050 y
        X0 = 700 100 (con la tecleada, centro 700 049,8, saldría 700 000); con paso 1,5
        (unidad de alineación 3 m) → 699 999–700 101 y X0 = 700 100. La cabecera lleva el
        mismo origen."""
        window = (700_000.0, 4_399_500.0, 700_099.6, 4_400_500.0)
        expected = (700_100, 4_400_000, 0)
        for step, aligned_x in ((1.0, (700_000.0, 700_100.0)), (1.5, (699_999.0, 700_101.0))):
            with self.subTest(paso=step), project_tmp() as tmp:
                result = _make(tmp, window=window, grid_step_m=step)
                record = result.record
                self.assertEqual((record.window_xmin, record.window_xmax), aligned_x)
                self.assertEqual(record.origin.as_tuple(), expected)
                header = manifest.read_manifest(result.root)
                self.assertEqual(header.origin.as_tuple(), expected)
                result.project.close()

    def test_crs_never_assumed_and_local_vertical(self) -> None:
        """RF-002-23, RF-002-03: el dominio no supone el CRS (constitución, principio 6):
        unos ajustes sin CRS horizontal o sin CRS vertical no se construyen; quien propone
        EPSG:25830 y EPSG:5782 es el diálogo «Nuevo proyecto», con las constantes del
        catálogo (convergencia, T42). La referencia vertical local se guarda con su
        descripción."""
        window = (699_500.0, 4_399_500.0, 700_500.0, 4_400_500.0)
        for missing in ({}, {"crs_epsg": 25830}, {"vcrs_epsg": 5782}):
            with self.subTest(dados=missing), self.assertRaises(TypeError):
                model.ProjectSettings(name="Sin CRS", window=window, **missing)
        crs = import_geoblender("core.georef.crs")
        self.assertEqual((crs.DEFAULT_HORIZONTAL_EPSG, crs.DEFAULT_VERTICAL_EPSG), (25830, 5782))
        with project_tmp() as tmp:
            record = _make(tmp, vcrs_epsg=None, vcrs_note="NP-0 del plano 3").record
            self.assertEqual(
                (record.vcrs_epsg, record.vcrs_name, record.vcrs_wkt, record.vcrs_note),
                (None, "Referencia local", None, "NP-0 del plano 3"),
            )

    def test_event_and_recent(self) -> None:
        """RF-002-01, RF-002-08: queda el evento ``create`` con la sesión y la lista de
        recientes del equipo (fuera del proyecto) lo incluye."""
        with project_tmp() as tmp:
            result = _make(tmp)
            with gpkg.GpkgConnection.open_read(result.root / "project.gpkg") as db:
                found = events.read_events(db.connection)
            self.assertEqual([item.kind for item in found], ["create"])
            self.assertEqual(found[0].session_uid, SESSION.session_uid)
            self.assertEqual(found[0].user_host, "prueba@PC-PRUEBA-A")
            self.assertIn("Cantera Prueba", found[0].message)
            recent = userdata_mod.UserData(tmp / "datos_usuario").recent_projects()
            self.assertEqual([item.uid for item in recent], [result.record.uid])
            self.assertEqual(recent[0].path, result.root)
            self.assertEqual(list(result.root.rglob("*.json")), [result.root / "manifest.json"])

    def test_no_absolute_paths(self) -> None:
        """RF-002-18: ni la cabecera, ni ninguna celda de texto de la base de datos, ni el
        cerrojo guardan una ruta absoluta."""
        with project_tmp() as tmp:
            result = _make(tmp)
            header = json.loads((result.root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(paths.find_absolute_paths(header), [])
            self.assertEqual(paths.find_absolute_paths(_text_cells(result.root / "project.gpkg")), [])
            self.assertEqual(
                paths.find_absolute_paths((result.root / ".lock").read_text(encoding="utf-8")), []
            )

    def test_network_mode(self) -> None:
        """RF-002-01, RF-002-30: en una carpeta de red el cerrojo nace en modo
        ``network``."""
        with project_tmp() as tmp:
            parent = tmp / "proyectos"
            parent.mkdir()
            result = create.create_project(
                parent, make_settings(), SESSION, userdata_mod.UserData(tmp / "u"),
                clock=FakeClock(), network=True,
            )
            self.assertTrue(result.network)
            self.assertEqual(result.lock.mode, lock.LockMode.NETWORK)

    def test_precision_warning(self) -> None:
        """RF-002-26: una ventana de 20 × 20 km se crea, con aviso de las esquinas que
        quedan a más de 8 km del GeoOrigin y del error estimado en mm."""
        with project_tmp() as tmp:
            result = _make(tmp, window=(690_000.0, 4_390_000.0, 710_000.0, 4_410_000.0))
            self.assertFalse(result.precision.within_limit)
            self.assertEqual(len(result.warnings), 1)
            self.assertIn("esquinas", result.warnings[0])
            self.assertIn("mm", result.warnings[0])
            self.assertTrue(result.root.is_dir())
        with project_tmp() as tmp:
            self.assertEqual(_make(tmp).warnings, ())


class RejectTest(unittest.TestCase):
    def _assert_rejected(self, tmp: Path, field: str, value_text: str, **overrides) -> None:
        with self.assertRaises(errors.ValidationError) as caught:
            _make(tmp, **overrides)
        self.assertEqual(caught.exception.field, field)
        self.assertIn(value_text, str(caught.exception))
        self.assertEqual(list((tmp / "proyectos").iterdir()), [])

    def test_invalid_settings_create_nothing(self) -> None:
        """RF-002-03: ejes invertidos (X e Y intercambiadas), ventana vacía, fuera del
        ámbito del CRS y de su huso extendido (al norte de su ámbito), CRS que falta (``None``: nunca se supone EPSG:25830, principio 6;
        convergencia, T42), que no es un código entero, fuera del catálogo o del tipo
        equivocado, vertical local sin descripción, paso 0,3 o Z0 = 20 000 → rechazo con el
        campo y el valor, y no se crea nada."""
        cases = [
            ("ventana", "4400000", {"window": (4_400_000.0, 700_000.0, 4_401_000.0, 701_000.0)}),
            ("xmin–xmax", "700500", {"window": (700_500.0, 4_399_500.0, 700_500.0, 4_400_500.0)}),
            ("ymin–ymax", "4400500", {"window": (699_500.0, 4_400_500.0, 700_500.0, 4_399_500.0)}),
            # Al norte del ámbito de EPSG:25830 (80,49°), también fuera del huso extendido
            # (D-12: solo se amplía la longitud).
            (
                "ventana",
                "9500000",
                {"window": (699_500.0, 9_500_000.0, 700_500.0, 9_501_000.0)},
            ),
            ("CRS horizontal", "vacío", {"crs_epsg": None}),
            ("CRS horizontal", "25830", {"crs_epsg": "25830"}),
            ("CRS horizontal", "EPSG:4326", {"crs_epsg": 4326}),
            ("CRS horizontal", "EPSG:5782", {"crs_epsg": 5782}),
            ("CRS vertical", "EPSG:25830", {"vcrs_epsg": 25830}),
            ("descripción de la referencia local", "vacío", {"vcrs_epsg": None, "vcrs_note": None}),
            ("descripción de la referencia local", "NP-0", {"vcrs_note": "NP-0"}),
            ("paso de rejilla", "0,3", {"grid_step_m": 0.3}),
            ("Z0", "20000", {"z0": 20_000}),
            ("nombre", "CON", {"name": "CON"}),
            ("nombre", "a:b", {"name": "a:b"}),
        ]
        for field, value_text, overrides in cases:
            with self.subTest(campo=field, cambio=overrides), project_tmp() as tmp:
                self._assert_rejected(tmp, field, value_text, **overrides)

    def test_crs_scope_at_the_east_edge_of_zone_30(self) -> None:
        """RF-002-03 (D-12 de la spec 0.4; convergencia, T47 y T51): una ventana fuera del
        ámbito EPSG del CRS pero dentro de su huso extendido (hasta 3° de longitud fuera
        del huso) se crea con un aviso que dice cuánto se sale y la deformación de escala;
        más allá, se rechaza como antes, sin crear nada. En EPSG:25830 (huso 30, de −6° a
        0°), la cartografía valenciana (ICV) llega a Vinaròs: 794 000–795 000 ×
        4 482 000–4 483 000 → creado con «0,48° al este del huso 30 (0°)» y «+671 ppm
        (0,67 m por km)»; 1 007 000–1 008 000 × 4 500 000–4 501 000 → creado con 2,99° y
        +2 778 ppm; 1 008 000–1 009 000 (3,0056° E) y Mahón (4,26° E) →
        ``core.window_outside_crs`` en «ventana», que nombra el huso extendido; Castellón
        de la Plana (dentro del ámbito) → creado sin aviso."""
        accepted = (
            (
                (794_000.0, 4_482_000.0, 795_000.0, 4_483_000.0),
                (
                    "0,48°",
                    "al este del huso 30 (0°)",
                    "+671 ppm",
                    "(0,67 m por km)",
                    "EPSG:25830",
                ),
            ),
            (
                (1_007_000.0, 4_500_000.0, 1_008_000.0, 4_501_000.0),
                ("2,99°", "al este del huso 30 (0°)", "+2778 ppm", "(2,78 m por km)"),
            ),
        )
        for window, texts in accepted:
            with self.subTest(ventana=window), project_tmp() as tmp:
                result = _make(tmp, window=window)
                (warning,) = result.warnings
                for text in texts:
                    self.assertIn(_compact(text), _compact(warning))
                self.assertIn("huso extendido", warning)
                self.assertTrue(result.project.writable)
                result.project.close()
        for window in (
            (1_008_000.0, 4_500_000.0, 1_009_000.0, 4_501_000.0),
            (1_121_000.0, 4_440_000.0, 1_122_000.0, 4_441_000.0),
        ):
            with self.subTest(ventana=window), project_tmp() as tmp:
                with self.assertRaises(errors.ValidationError) as caught:
                    _make(tmp, window=window)
                self.assertEqual(caught.exception.code, "core.window_outside_crs")
                self.assertEqual(caught.exception.field, "ventana")
                self.assertIn("huso extendido", str(caught.exception))
                self.assertIn("intercambiadas", str(caught.exception))
                self.assertEqual(list((tmp / "proyectos").iterdir()), [])
        with project_tmp() as tmp:
            result = _make(tmp, window=(751_000.0, 4_429_000.0, 752_000.0, 4_430_000.0))
            self.assertEqual(result.record.origin.as_tuple()[:2], (751_500, 4_429_500))
            self.assertEqual(result.warnings, ())
            result.project.close()

    def test_existing_destination(self) -> None:
        """RF-002-02: si la carpeta de destino ya existe, se informa con la ruta y no se
        toca nada."""
        with project_tmp() as tmp:
            target = tmp / "proyectos" / "Cantera Prueba.gbproj"
            target.mkdir(parents=True)
            (target / "nota.txt").write_text("de otro", encoding="utf-8")
            with self.assertRaises(errors.ProjectError) as caught:
                _make(tmp)
            self.assertEqual(caught.exception.code, "core.project_exists")
            self.assertIn("Cantera Prueba.gbproj", str(caught.exception))
            self.assertEqual(sorted(p.name for p in (tmp / "proyectos").iterdir()),
                             ["Cantera Prueba.gbproj"])
            self.assertEqual([p.name for p in target.iterdir()], ["nota.txt"])

    def test_parent_missing_or_not_writable(self) -> None:
        """RF-002-02: si la carpeta elegida no existe o no se puede escribir, se informa
        con la ruta y el motivo y no queda nada."""
        with project_tmp() as tmp:
            with self.assertRaises(errors.ProjectError) as caught:
                create.create_project(
                    tmp / "no_existe", make_settings(), SESSION,
                    userdata_mod.UserData(tmp / "u"), clock=FakeClock(),
                )
            self.assertEqual(caught.exception.code, "core.project_parent_missing")
            self.assertIn("no_existe", str(caught.exception))
            (tmp / "proyectos").mkdir()
            denied = PermissionError(13, "Acceso denegado")
            with mock.patch.object(create, "_make_temporary", side_effect=denied):
                with self.assertRaises(errors.ProjectError) as caught:
                    _make(tmp)
            self.assertEqual(caught.exception.code, "core.project_not_writable")
            self.assertIn("proyectos", str(caught.exception))
            self.assertEqual(list((tmp / "proyectos").iterdir()), [])

    def test_too_long_folder_rejected_before_creating(self) -> None:
        """RF-002-02: con una carpeta de destino de unos 200 caracteres, la ruta más larga
        que necesita crear el proyecto (la cabecera temporal dentro de la carpeta temporal)
        pasaría del límite de Windows (MAX_PATH: 259 caracteres; Blender 5.2.1 no admite
        rutas más largas aunque Windows las tenga activadas): se rechaza antes de crear
        nada, con la ruta, su longitud y el límite (convergencia, T45)."""
        with project_tmp() as tmp:
            parent = _deep_folder(tmp, 200)
            with self.assertRaises(errors.ProjectError) as caught:
                create.create_project(
                    parent, make_settings(), SESSION, userdata_mod.UserData(tmp / "u"),
                    clock=FakeClock(),
                )
            self.assertEqual(caught.exception.code, "core.path_too_long")
            text = str(caught.exception)
            self.assertIn("259", text)
            self.assertIn(str(parent), text)
            self.assertIn("Cantera Prueba.gbproj", text)
            self.assertEqual(list(parent.iterdir()), [])

    def test_paths_used_while_creating_fit(self) -> None:
        """RF-002-02: con una carpeta de 150 caracteres (dentro de Blender, crear fallaba a
        partir de unos 145: hito H2), el proyecto se crea; la carpeta temporal es
        ``<Nombre>.gbproj.creando-`` y la cabecera temporal ``manifest.json.tmp-``, cada una
        con 8 cifras hexadecimales (no un UUID), y ninguna ruta que se usa al crearlo pasa
        de 259 caracteres (convergencia, T45)."""
        with project_tmp() as tmp:
            parent = _deep_folder(tmp, 150)
            used: list[str] = []
            real_replace = os.replace
            real_publish = create._publish

            def replace(src: object, dst: object) -> None:
                used.extend((os.fspath(src), os.fspath(dst)))
                real_replace(src, dst)

            def publish(folder: Path, target: Path) -> None:
                used.extend(os.fspath(path) for path in (folder, *folder.rglob("*")))
                real_publish(folder, target)

            with (
                mock.patch.object(manifest.os, "replace", side_effect=replace),
                mock.patch.object(create, "_publish", side_effect=publish),
            ):
                result = create.create_project(
                    parent, make_settings(), SESSION, userdata_mod.UserData(tmp / "u"),
                    clock=FakeClock(),
                )
            self.assertTrue(result.root.is_dir())
            names = {Path(path).name for path in used}
            self.assertTrue(any(re.fullmatch(r"Cantera Prueba\.gbproj\.creando-[0-9a-f]{8}", n)
                                for n in names), names)
            self.assertTrue(any(re.fullmatch(r"manifest\.json\.tmp-[0-9a-f]{8}", n)
                                for n in names), names)
            self.assertLessEqual(max(len(path) for path in used), 259)
            result.project.close()

    def test_failure_in_each_step_leaves_nothing(self) -> None:
        """RF-002-02: un fallo simulado en cada paso de la creación (carpetas, base de
        datos, cabecera, cerrojo y renombrado final) informa del motivo con la ruta y no
        deja ni ``.gbproj`` ni carpeta temporal."""
        for step in STEPS:
            with self.subTest(paso=step), project_tmp() as tmp:
                failure = OSError(28, "No queda espacio en el disco")
                with mock.patch.object(create, step, side_effect=failure):
                    with self.assertRaises(errors.ProjectError) as caught:
                        _make(tmp)
                self.assertEqual(caught.exception.code, "core.project_create_failed")
                self.assertIn("No queda espacio", str(caught.exception))
                self.assertIn("Cantera Prueba.gbproj", str(caught.exception))
                self.assertEqual(list((tmp / "proyectos").iterdir()), [])

    def test_failure_inside_database_leaves_nothing(self) -> None:
        """RF-002-02: un fallo a mitad de la base de datos (con el ``project.gpkg`` ya
        empezado) tampoco deja nada."""
        with project_tmp() as tmp:
            with mock.patch.object(create, "create_schema", side_effect=sqlite3.OperationalError("disk I/O error")):
                with self.assertRaises(errors.ProjectError):
                    _make(tmp)
            self.assertEqual(list((tmp / "proyectos").iterdir()), [])


class EventsTest(unittest.TestCase):
    def test_event_refuses_absolute_paths(self) -> None:
        """RF-002-18: un evento con una ruta absoluta en el mensaje o en los datos no se
        registra."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            crs = georef.load_catalog().horizontal(25830)
            with gpkg.GpkgConnection.open_write(path, create=True) as db:
                with db.transaction() as conn:
                    import_geoblender("core.gpkg.base").create_base(conn, crs)
                    schema.create_schema(conn)
                for message, data in (
                    ("copiado de " + str(tmp), None),
                    ("bien", {"ruta": str(tmp)}),
                ):
                    with self.subTest(mensaje=message):
                        with self.assertRaises(ValueError), db.transaction() as conn:
                            events.record_event(
                                conn, events.EventKind.OPEN, message, session=SESSION,
                                at="2026-10-05T08:12:44.000Z", data=data,
                            )
                with db.transaction() as conn:
                    events.record_event(
                        conn, events.EventKind.OPEN, "abierto", session=SESSION,
                        at="2026-10-05T08:12:44.000Z", data={"modo": "local"},
                    )
                found = events.read_events(db.connection)
            self.assertEqual([(item.kind, item.data) for item in found], [("open", {"modo": "local"})])


if __name__ == "__main__":
    unittest.main()
