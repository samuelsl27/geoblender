# SPDX-License-Identifier: GPL-3.0-or-later
"""La operación ``des.quarry`` y el recálculo y la reproducción de la cantera y de su recinto
(spec 014, T19; HU-014-1, HU-014-3; RF-014-29, RF-014-30, RF-014-31; plan 014 §5.2.3, §5.3.2;
RF-008-24, RF-008-26, RF-009-11; como D-14 de la 013).

- **RF-014-29**: «Calcular» (``design.steps.quarry_run``) deja las rejillas de la cantera en
  temporales y **nada registrado**; «Crear» registra ``des.quarry`` de la versión con sus siete
  salidas (las dos superficies, sus envolventes, la clasificación, las bermas de las dos y el
  informe), sus ajustes, sus entradas, sus parámetros y sus cifras, en una transacción; cerrar los
  pasos a mitad (Esc) no deja nada.
- **RF-014-30**: con un sector del recinto sin la búsqueda de intocables vigente, ni se calcula ni
  se recalcula, nombrando el sector, y no se registra nada.
- **RF-014-31**: cambiar una capa de fondos deja obsoleta la cantera que la usa, con su causa, y
  no la que no la usa; «Recalcular lo obsoleto» la repite con sus ajustes, sin confirmar.
- **RF-009-11**: reproducir la revisión congelada da las mismas salidas (el mismo hash) y las
  mismas cifras de las dos canteras y del recinto (``des.excavation_area``, que también se
  recalcula), sin escribir en el proyecto.

Una sola historia, en el orden de las pruebas, sobre una copia del proyecto de la cantera
(``tests.support.quarry_fixtures``, T01) con lo que declara ``des`` registrado con sus funciones
reales de recálculo y de reproducción: el recinto, la cantera de E3 (las dos superficies con
fondos, corredor, zona a conservar y zonas de restauración por relleno) y otra que recorre los
caminos que la primera no (semillas de la 013 en una capa, ancla en rejilla, «explotación
primero» y «explotación hasta la final» en una capa); después se congela V01.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files

store = import_geoblender("design.store")
steps = import_geoblender("design.steps")
provenance = import_geoblender("design.provenance")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
quarry = import_geoblender("design.quarry")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
core_params = import_geoblender("core.params")
res_provenance = import_geoblender("reserves.provenance")
freeze = import_geoblender("core.versions.freeze")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
graph = import_geoblender("core.provenance.graph")
operations = import_geoblender("core.provenance.operations")
contract = import_geoblender("core.provenance.contract")
figures_mod = import_geoblender("core.provenance.figures")
datasets = import_geoblender("core.datasets")
builtin = import_geoblender("core.content.builtin")
access = import_geoblender("gis.masks.access")
geotiff_reader = import_geoblender("gis.geotiff.reader")

START = qfx.START_DATASET
EXPL, REST = qfx.EXPLOITATION_PROFILE, qfx.FINAL_PROFILE
CONSERVE_SLOPE_DEG = 35.0
"""El talud de conservación de la prueba (D-9: lo declara una persona; el del análisis)."""
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}
CORRIDOR = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho", start_level_field="cota_inicial",
                                grade_field="pendiente")
AREA_NAME = "Recinto de la cantera"
QUARRY_NAME = "Cantera E3"
OTHER_NAME = "Cantera B"
QUARRY_FAMILIES = ("exp", "fin", "xen", "fen", "cls", "bmt", "qrp")
"""Las siete salidas de ``des.quarry``, en el orden de su tipo (plan 014 §5.2.3)."""
ROLES = {"exp": "design_surface", "fin": "design_surface", "xen": "exploitation_envelope",
         "fen": "final_envelope", "cls": "classification", "bmt": "berm_table",
         "qrp": "quarry_report"}
NEW_PLATFORM_M = 178.0
"""La cota nueva de la plataforma (el fondo 2, a 175 m): la que sí manda en E1 (T14); 3 m (no un
múltiplo de la altura de banco) mueven también las anclas «al fondo de cada muro»."""


def quarry_request(name: str = QUARRY_NAME) -> Any:
    """La cantera de E3: la final con ``REST_5_35_6`` y la explotación con ``EXPL_10_60_6`` anclada
    «al fondo de cada muro», las dos con las semillas «coronación y zonas a sostener»; los fondos,
    el corredor, la zona a conservar y las zonas de restauración por relleno de la cantera."""
    return model.QuarryRequest(
        name=name, start=START, final=model.QuarrySide(REST.code),
        exploitation=model.QuarrySide(EXPL.code, anchor="nearest_floor"),
        floors=model.LayerField(qfx.FLOORS_LAYER, "cota"),
        conserve=(model.Zone("layer", qfx.CONSERVE_LAYER),), corridors=CORRIDOR,
        fill_zones=qfx.FILL_LAYER)


def other_request() -> Any:
    """Otra cantera, por los caminos que la de E3 no recorre: la final anclada a una rejilla (el
    terreno), la explotación con semillas de la 013 (cota fija de 200 m en la capa de relleno: caen
    fuera de la coronación, RF-014-03), «explotación primero» y «explotación hasta la final» en las
    zonas de una capa; sin fondos, corredores ni zonas a conservar."""
    return model.QuarryRequest(
        name=OTHER_NAME, start=START,
        final=model.QuarrySide(REST.code, anchor="grid", anchor_grid=START),
        exploitation=model.QuarrySide(EXPL.code, seeds=model.SeedSource(
            "fixed", elevation_m=200.0, zone=model.Zone("layer", qfx.FILL_LAYER))),
        order="exploitation_first", to_final="layer", to_final_layer=qfx.FILL_LAYER)


def drive(work: Iterator[Any]) -> Any:
    """Lleva unos pasos hasta el final y devuelve el último ``Progress``."""
    found = None
    for found in work:
        pass
    return found


def recompute_function(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo: lleva los pasos hasta el final."""
    handle, work = store.recompute_run(request)
    drive(work)
    return handle


def never(request: Any) -> Any:  # nunca se llama: solo declara que se repite sola
    raise AssertionError("esta historia no recalcula ni reproduce ese tipo")


def definitions() -> tuple[Any, ...]:
    """Los tipos de la 013 y de la 014 con sus funciones **reales** (las de la cantera y el
    recinto) y las cifras, como los registra ``bl``."""
    real = {provenance.EXCAVATION_AREA: recompute_function, provenance.QUARRY: recompute_function}
    reproduce = {provenance.EXCAVATION_AREA: design_reproduce.reproduce_excavation_area,
                 provenance.QUARRY: design_reproduce.reproduce_quarry}
    return (*provenance.operation_defs({t: never for t in provenance.REPRODUCIBLE},
                                       {t: never for t in provenance.REPRODUCIBLE}),
            *provenance.quarry_operation_defs(
                {t: real.get(t, never) for t in provenance.QUARRY_VERSION_TYPES},
                {t: reproduce.get(t, never) for t in provenance.QUARRY_REPRODUCIBLE}),
            *provenance.FIGURES, *provenance.QUARRY_FIGURES)


def declare(project: Any, clock: Any, key: str, value: object, *, version: Any = None) -> None:
    """Declara el parámetro ``key`` en el proyecto o, con ``version``, en esa versión."""
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        core_params.ParameterStore(project).create(
            conn, key, value, kind="ADOPTADO", reason="Prueba de la 014", version=version,
            **BY_HAND)


def declare_profiles(project: Any, clock: Any) -> None:
    """Los cinco valores de los dos perfiles de la cantera, en el proyecto."""
    for profile in (EXPL, REST):
        for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            declare(project, clock, design_params.bench_key(profile.code, param),
                    getattr(profile, param))


def rewrite_floor(project: Any, clock: Any, fid: int, level_m: float) -> None:
    """Cambia la cota del fondo ``fid`` de la capa de fondos (como al editarla y volver a
    registrarla, con el contenido nuevo del mismo dato)."""
    from tests.support import design_fixtures

    srs = int(project.record.crs_epsg)
    writer = contract.OperationDef(design_fixtures.LAYERS_TYPE, "1.0", "gis",
                                   "Layers of the tests", False)
    with registered(writer):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, design_fixtures.LAYERS_TYPE,
                                            settings={"name": qfx.FLOORS_LAYER},
                                            executor="blender")
        with project.write_transaction() as conn:
            conn.execute(f'UPDATE "{qfx.FLOORS_LAYER}" SET "cota" = ? WHERE fid = ?',
                         (level_m, fid))
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                qfx.FLOORS_LAYER, "gis", "vector", datasets.Store.GPKG, qfx.FLOORS_LAYER,
                reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs, input_uid=None,
                immutable=False),), message="Fondo de prueba cambiado")


class QuarryOperationTest(qfx.QuarryProjectCase):
    """RF-014-29 a RF-014-31 y la reproducción (véase el módulo), en el orden de las pruebas."""

    area: ClassVar[Any]
    calculation: ClassVar[Any]
    stored: ClassVar[Any]
    other: ClassVar[Any]
    other_stored: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions(design_params.DEFINITIONS)
        core_params.register_definitions(design_params.QUARRY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        cls.enterClassContext(registered(*definitions()))
        declare_profiles(cls.project, cls.clock)
        declare(cls.project, cls.clock, design_params.CONSERVE_SLOPE, CONSERVE_SLOPE_DEG)
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        cls.clock.advance(minutes=1)
        area = drive(steps.excavation_area_run(cls.project, AREA_NAME, START,
                                               version=cls.v1.uid, masks=cls.masks_v1)).result
        cls.area = area.create()
        cls.before = cls.des_state()
        cls.clock.advance(minutes=1)
        cls.calculation = drive(steps.quarry_run(cls.project, quarry_request(),
                                                 version=cls.v1.uid,
                                                 masks=cls.masks_v1)).result
        cls.calculated = cls.des_state()
        cls.stored = cls.calculation.create()
        cls.clock.advance(minutes=1)
        cls.other = drive(steps.quarry_run(cls.project, other_request(),
                                           version=cls.v1.uid)).result
        cls.other_stored = cls.other.create()
        cls.figures_before = {stored.handle.uid: cls.figures_of(stored.handle.uid)
                              for stored in (cls.area, cls.stored, cls.other_stored)}
        cls.clock.advance(minutes=1)
        outcome = drive(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega")).result
        cls.r1, cls.r2 = str(outcome.frozen.uid), str(outcome.opened.uid)

    # --- Ayudas -------------------------------------------------------------------------------

    @classmethod
    def query_of(cls, sql: str, *values: Any) -> list[Any]:
        with cls.project.read() as conn:
            return conn.execute(sql, values).fetchall()

    @classmethod
    def des_state(cls) -> dict[str, Any]:
        """Lo que ``des`` ha dejado en el proyecto: operaciones, datos, tablas, cifras y los
        ficheros de ``rasters/`` (con sus temporales)."""
        return {
            "operations": cls.query_of("SELECT uid, op_type, status FROM gb_operation WHERE "
                                       "op_type LIKE 'des.%' ORDER BY fid"),
            "datasets": cls.query_of("SELECT name, status FROM gb_dataset WHERE name LIKE "
                                     "'des!_%' ESCAPE '!' ORDER BY name"),
            "tables": cls.query_of("SELECT name FROM sqlite_master WHERE name LIKE 'des!_%' "
                                   "ESCAPE '!' ORDER BY name"),
            "figures": cls.query_of("SELECT count(*) FROM gb_figure WHERE key LIKE 'des.%'"),
            "files": sorted(path.name for path in (cls.root / "rasters").iterdir())}

    @classmethod
    def figures_of(cls, uid: str) -> dict[tuple[str, str], float]:
        """Las cifras de una operación por clave y ámbito."""
        return {(key, scope): value for key, scope, value in cls.query_of(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def settings_of(self, uid: str) -> dict[str, Any]:
        return dict(json.loads(self.query_of("SELECT settings FROM gb_operation WHERE uid = ?",
                                             uid)[0][0]))

    def outputs_of(self) -> dict[str, str]:
        """El hash de contenido de cada dato vivo de ``des`` de V01."""
        return {name: sha for name, sha in self.query_of(
            "SELECT name, content_sha256 FROM gb_dataset WHERE name LIKE 'des!_%' ESCAPE '!' "
            "AND status IN ('current', 'stale') ORDER BY name")}

    def causes(self) -> dict[tuple[str, str], set[tuple[str, str]]]:
        found: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for kind, uid, cause, subject in self.query_of(
                "SELECT item_kind, item_uid, cause_kind, subject_uid FROM gb_stale"):
            found.setdefault((kind, uid), set()).add((cause, subject))
        return found

    def grid_of(self, family: str, name: str = QUARRY_NAME) -> np.ndarray:
        record = self.record(provenance.dataset_name(family, name), self.v1)
        return geotiff_reader.read_geotiff(self.root / record.locator).values

    def live_quarry(self, name: str = QUARRY_NAME) -> str:
        return next(uid for (uid,) in self.query_of(
            "SELECT uid FROM gb_operation WHERE op_type = ? AND superseded_by IS NULL AND "
            "status = 'done' AND settings LIKE ?", provenance.QUARRY, f'%"name":"{name}"%'))

    # --- Calcular y crear (RF-014-29) --------------------------------------------------------

    def test_a_calculating_writes_nothing_and_creating_writes_everything(self) -> None:
        """RF-014-29 (como D-14 de la 013): «Calcular» deja las rejillas en temporales junto a su
        destino y no registra ni operación, ni dato, ni tabla, ni cifra; «Crear» registra
        ``des.quarry`` de V01 hecha, con sus siete salidas y sus papeles (las dos superficies,
        ``design_surface``), sus cifras CALCULADO (las del cálculo) y su mensaje; lo escrito es lo
        calculado, bit a bit."""
        before, calculated = self.before, self.calculated
        for key in ("operations", "datasets", "tables", "figures"):
            self.assertEqual(calculated[key], before[key], key)
        new_files = sorted(set(calculated["files"]) - set(before["files"]))
        self.assertEqual(len(new_files), 5, new_files)
        self.assertTrue(all(".tmp-" in name for name in new_files), new_files)
        calculation = self.calculation
        self.assertEqual((calculation.op_type, calculation.name, calculation.version),
                         (provenance.QUARRY, QUARRY_NAME, "V01"))
        self.assertFalse(calculation.open)
        self.assertEqual([spec.name for spec in calculation.specs],
                         [provenance.dataset_name(family, QUARRY_NAME)
                          for family in QUARRY_FAMILIES])
        handle = self.stored.handle
        self.assertEqual(self.query_of("SELECT op_type, status FROM gb_operation WHERE uid = ?",
                                       handle.uid), [(provenance.QUARRY, "done")])
        roles = dict(self.query_of(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'",
            handle.uid))
        self.assertEqual(roles, {provenance.dataset_name(family, QUARRY_NAME): role
                                 for family, role in ROLES.items()})
        outcome = calculation.outcome
        self.assertEqual(self.figures_before[handle.uid],
                         {(spec.key, figures_mod.scope_json(spec.scope)): spec.value
                          for spec in calculation.figures})
        self.assertEqual(len(calculation.figures), len(self.figures_before[handle.uid]))
        self.assertIn(QUARRY_NAME, calculation.message)
        np.testing.assert_array_equal(self.grid_of("exp"), outcome.exploitation_grid)
        np.testing.assert_array_equal(self.grid_of("fin"), outcome.final_grid)
        np.testing.assert_array_equal(self.grid_of("xen"), outcome.exploitation.envelope.grid)
        np.testing.assert_array_equal(self.grid_of("fen"), outcome.final.envelope.grid)
        np.testing.assert_array_equal(self.grid_of("cls"), outcome.classes.grid)
        start = qfx.terrain()
        final, exploitation = self.grid_of("fin"), self.grid_of("exp")
        self.assertTrue(np.all(final <= exploitation + 1e-3))
        self.assertTrue(np.all(exploitation <= start + 1e-3))
        self.assertTrue((exploitation < start - 1.0).any(), "la cantera excava")

    def test_a_the_tables_carry_the_berms_of_both_surfaces_and_the_report(self) -> None:
        """RF-014-29, plan 014 §5.2.3: ``des_bmt_`` lleva las bermas de las dos superficies con la
        columna ``surface`` (las del cálculo de cada lado), y ``des_qrp_``, el informe en formato
        largo con las cifras de la clasificación iguales a las registradas y los avisos de cada
        lado con su superficie."""
        outcome = self.calculation.outcome
        rows = self.query_of('SELECT surface, sector, profile, level_m, cells FROM '
                             '"des_bmt_cantera_e3_v01" ORDER BY fid')
        expected = [(surface.value, row[0], row[1], row[2], row[3])
                    for surface in model.Surface
                    for row in store.berm_rows(outcome.side(surface).design.berms)]
        self.assertEqual(rows, expected)
        self.assertEqual({row[0] for row in rows}, {"final", "exploitation"})
        report = {quantity: (value, unit) for quantity, value, unit in self.query_of(
            'SELECT quantity, value, unit_code FROM "des_qrp_cantera_e3_v01" '
            "WHERE quantity NOT IN ('warning', 'note')")}
        total = outcome.classes.total
        self.assertEqual(report["exp_cut_m3"], (total.exp_cut_m3, "m3"))
        self.assertEqual(report["unsplit_m3"], (total.unsplit_m3, "m3"))
        self.assertEqual(report["restoration_fill_m3"], (total.fill_m3, "m3"))
        self.assertEqual(report["order_adjusted_cells"], (float(outcome.adjusted), "-"))
        self.assertEqual(report["final.cut_m3"], (outcome.final.design.report.cut_m3, "m3"))
        self.assertEqual(report["exploitation.cut_m3"],
                         (outcome.exploitation.design.report.cut_m3, "m3"))
        notes = [json.loads(note) for (note,) in self.query_of(
            'SELECT note FROM "des_qrp_cantera_e3_v01" WHERE quantity IN (\'warning\', '
            "'note')")]
        self.assertTrue(notes)
        self.assertTrue({"code", "values"} <= set(notes[0]))
        sided = [note for note in notes if "surface" in note]
        self.assertEqual({note["surface"] for note in sided}, {"final", "exploitation"})

    def test_a_what_is_registered_repeats_the_request(self) -> None:
        """RF-014-29, RF-014-31: los ajustes repiten la petición (también la otra cantera) y los
        sectores que tocó el recinto; las entradas son la superficie de partida, las capas que usa
        cada una con su papel, las máscaras, los sectores y las búsquedas; los parámetros, los de
        los dos perfiles, el anillo de coronación, el aviso de desdoblado, el talud de
        conservación (solo con zonas a conservar), la tolerancia, el umbral y el espesor."""
        for stored, request in ((self.stored, quarry_request()),
                                (self.other_stored, other_request())):
            settings = self.settings_of(stored.handle.uid)
            self.assertEqual(provenance.quarry_request(settings), request)
            self.assertEqual(provenance.settings_touched(settings), ("sector_1", "sector_2"))
            self.assertEqual(provenance.settings_pending(settings), ())
        inputs = {(name, role) for name, role in self.query_of(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'",
            self.stored.handle.uid)}
        for item in ((START, "surface"), (qfx.FLOORS_LAYER, "floors_layer"),
                     (qfx.CORRIDORS_LAYER, "corridors_layer"),
                     (qfx.CONSERVE_LAYER, "conserve_layer"), (qfx.FILL_LAYER, "fill_layer"),
                     ("core_sector", "sectors"), ("core_untouchable_search", "searches")):
            self.assertIn(item, inputs)
        self.assertTrue(any(role.startswith("masks_") for _name, role in inputs), inputs)
        other = {(name, role) for name, role in self.query_of(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'",
            self.other_stored.handle.uid)}
        for item in ((START, "surface"), (START, "final_anchors"),
                     (qfx.FILL_LAYER, "exploitation_zone_layer"),
                     (qfx.FILL_LAYER, "to_final_layer")):
            self.assertIn(item, other)
        self.assertFalse([role for _name, role in other
                          if role in ("floors_layer", "conserve_layer", "fill_layer")])
        params = {key for (key,) in self.query_of(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", self.stored.handle.uid)}
        for profile in (EXPL, REST):
            for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
                self.assertIn(design_params.bench_key(profile.code, param), params)
        for key in (design_params.CROWN_RING, design_params.UNSPLIT_THRESHOLD,
                    design_params.UNSPLIT_MIN_AREA, design_params.CONSERVE_SLOPE,
                    design_params.TOLERANCE_FACE, design_params.WARNING_RATIO,
                    design_params.VERIFY_MIN_THICKNESS):
            self.assertIn(key, params)
        other_params = {key for (key,) in self.query_of(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?",
            self.other_stored.handle.uid)}
        self.assertNotIn(design_params.CONSERVE_SLOPE, other_params)

    def test_a_the_summary_says_the_warnings_of_the_request(self) -> None:
        """RF-014-12, RF-014-03 (en el resumen): la otra cantera siembra la explotación fuera de
        la coronación y de las zonas a sostener, y el resumen lo dice con su grupo; «explotación
        hasta la final» deja su cifra; la de E3 no tiene semillas de la 013 y no lo dice."""
        lines = self.other.lines("es")
        self.assertTrue(any("caen fuera de la coronación" in line for line in lines), lines)
        self.assertTrue(any(line.startswith("Grupo 1: 3") for line in lines), lines)
        self.assertIn("des.to_final_m3", {spec.key for spec in self.other.figures})
        self.assertFalse(any("coronación" in line for line in self.calculation.lines("es")))
        self.assertIs(self.other.outcome.order, model.Order.EXPLOITATION_FIRST)

    # --- Reproducir (RF-009-11) --------------------------------------------------------------

    def test_b_reproducing_v01_r1_gives_the_same(self) -> None:
        """RF-009-11, RF-014-29: reproducir V01.r1 da las salidas del recinto y de las dos canteras
        con el mismo hash y sus cifras iguales, sin escribir nada en el proyecto: lo que se lee de
        lo congelado (capas, rejillas, máscaras, sectores, parámetros) es lo que leyó el cálculo."""
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = drive(reproduce_mod.reproduce_steps(self.project, self.r1)).result
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before)
        self.assertEqual(report.not_reproducible, ())
        for stored, roles in ((self.area, ["excavation_area"]),
                              (self.stored, sorted(ROLES.values())),
                              (self.other_stored, sorted(ROLES.values()))):
            uid = stored.handle.uid
            mine = [check for check in report.outputs if check.operation_uid == uid]
            self.assertEqual(sorted(check.role for check in mine), roles)
            self.assertTrue(all(check.same for check in mine), mine)
            reproduced = {check.key for check in report.figures if check.operation_uid == uid}
            self.assertEqual(reproduced, {key for key, _scope in self.figures_before[uid]})
            self.assertTrue(all(check.same for check in report.figures
                                if check.operation_uid == uid))
        self.assertTrue(report.matches)

    # --- Obsoleto y recálculo (RF-014-31) ----------------------------------------------------

    def test_c_changing_the_floors_stales_the_quarry_that_uses_them(self) -> None:
        """RF-014-31: cambiar la capa de fondos deja obsoleta la cantera de E3 con la causa «cambió
        la capa de fondos», y no la otra cantera ni el recinto, que no la usan."""
        rewrite_floor(self.project, self.clock, 2, NEW_PLATFORM_M)
        floors = self.record(qfx.FLOORS_LAYER)
        causes = self.causes()
        self.assertEqual(causes[("operation", self.stored.handle.uid)],
                         {("dataset_changed", floors.uid)})
        for stored in (self.other_stored, self.area):
            self.assertNotIn(("operation", stored.handle.uid), causes)

    def test_d_recomputing_repeats_the_quarry_with_its_settings(self) -> None:
        """RF-014-31, RF-008-26: «Recalcular lo obsoleto» repite solo la cantera de E3, sin pedir
        confirmación y en la revisión abierta (r2), con sus mismos ajustes y el fondo nuevo: la
        explotación cambia (la plataforma manda) y lo congelado en V01.r1 no cambia."""
        old = self.stored.handle.uid
        before = self.outputs_of()
        with self.project.read() as conn:
            plan = recompute_mod.plan_recompute(graph.load_graph(conn))
        self.assertEqual([unit.operations for unit in plan.units], [(old,)])
        self.clock.advance(minutes=1)
        outcome = drive(recompute_mod.recompute_steps(self.project)).result
        self.assertEqual([item.status for item in outcome.results],
                         [recompute_mod.UnitStatus.DONE])
        (new,) = outcome.results[0].operations
        self.assertEqual(self.query_of("SELECT op_type, status, revision_uid, supersedes_uid FROM "
                                       "gb_operation WHERE uid = ?", new),
                         [(provenance.QUARRY, "done", self.r2, old)])
        self.assertEqual(provenance.quarry_request(self.settings_of(new)), quarry_request())
        now = self.outputs_of()
        exploitation = provenance.dataset_name("exp", QUARRY_NAME)
        self.assertNotEqual(now[exploitation], before[exploitation])
        for name in (provenance.dataset_name("exp", OTHER_NAME),
                     provenance.dataset_name("rcn", AREA_NAME)):
            self.assertEqual(now[name], before[name], name)
        total = ("des.exp_cut_m3",
                 figures_mod.scope_json(provenance.quarry_figure_scope(QUARRY_NAME)))
        self.assertNotEqual(self.figures_of(new)[total], self.figures_before[old][total],
                            "la plataforma y sus anclas mueven la excavación")
        self.assertEqual(self.query_of("SELECT count(*) FROM gb_stale WHERE item_kind = "
                                       "'operation' AND item_uid NOT IN (SELECT uid FROM "
                                       "gb_operation WHERE superseded_by IS NOT NULL)"), [(0,)])

    def test_e_recomputing_the_area_repeats_it(self) -> None:
        """RF-014-01, RF-008-26: el recálculo de ``des.excavation_area`` repite el recinto con sus
        ajustes (sustituye al anterior en la revisión abierta) y da el mismo recinto y la misma
        cifra: ni las máscaras ni el terreno han cambiado."""
        old = self.area.handle.uid
        settings = self.settings_of(old)
        self.assertEqual(provenance.excavation_area_start(settings), (AREA_NAME, START))
        before = self.outputs_of()
        request = recompute_mod.RecomputeRequest(self.project, old, provenance.EXCAVATION_AREA,
                                                 settings, (), (), version=self.v1.uid)
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(request)
        stored = drive(work).result
        self.assertEqual(stored.handle.uid, handle.uid)
        self.assertEqual(self.query_of("SELECT op_type, status, supersedes_uid FROM gb_operation "
                                       "WHERE uid = ?", handle.uid),
                         [(provenance.EXCAVATION_AREA, "done", old)])
        self.assertEqual(self.outputs_of()[provenance.dataset_name("rcn", AREA_NAME)],
                         before[provenance.dataset_name("rcn", AREA_NAME)])
        self.assertEqual(list(self.figures_of(handle.uid).values()),
                         list(self.figures_before[old].values()))

    # --- Esc y los rechazos ------------------------------------------------------------------

    def test_f_closing_the_steps_midway_leaves_nothing(self) -> None:
        """RF-014-29, RNF-014-05: cerrar los pasos de «Calcular» con las rejillas ya en sus
        temporales no deja nada; cerrar los de un recálculo a mitad deja la operación «cancelada»
        y nada más."""
        before = self.des_state()
        work = steps.quarry_run(self.project, quarry_request("Cantera C"), version=self.v1.uid,
                                masks=self.masks_v1, budget_s=1e-9)
        for step in work:
            if step.phase == "store" and len(list((self.root / "rasters").iterdir())) > len(
                    before["files"]):
                break
        self.assertNotEqual(self.des_state()["files"], before["files"], "el temporal existe")
        work.close()
        self.assertEqual(self.des_state(), before)
        handle, work = store.run_quarry(self.project, quarry_request("Cantera D"),
                                        version=self.v1.uid, masks=self.masks_v1)
        next(work)
        work.close()
        self.assertEqual(self.query_of("SELECT status FROM gb_operation WHERE uid = ?",
                                       handle.uid), [("cancelled",)])
        after = self.des_state()
        self.assertEqual(after["datasets"], before["datasets"])
        self.assertEqual(after["files"], before["files"])
        self.assertEqual(after["figures"], before["figures"])

    def test_g_a_pending_sector_refuses_calculating_and_recomputing(self) -> None:
        """RF-014-30 (RF-013-05): con la búsqueda de intocables del sector 1 («Sector oeste»)
        pendiente, que el recinto toca, «Calcular» se niega al avanzar y el recálculo al llamar,
        nombrando el sector, sin registrar nada; una operación que no es de la 013 ni de la
        cantera o su recinto no se recalcula aquí (``ValueError``)."""
        with self.project.write_transaction() as conn:
            conn.execute("DELETE FROM core_untouchable_search WHERE sector_code = 'sector_1'")
        before = self.query_of("SELECT count(*) FROM gb_operation")
        with self.assertRaises(messages.DesignError) as caught:
            drive(steps.quarry_run(self.project, quarry_request("Cantera E"),
                                   version=self.v1.uid))
        self.assertEqual(caught.exception.code, "des.sector_pending")
        self.assertIn("Sector oeste", str(caught.exception))
        uid = self.live_quarry()
        request = recompute_mod.RecomputeRequest(self.project, uid, provenance.QUARRY,
                                                 self.settings_of(uid), (), (),
                                                 version=self.v1.uid)
        with self.assertRaises(messages.DesignError) as caught:
            store.recompute_run(request)
        self.assertEqual(caught.exception.code, "des.sector_pending")
        self.assertEqual(self.query_of("SELECT count(*) FROM gb_operation"), before)
        other = recompute_mod.RecomputeRequest(self.project, uid, provenance.FILL_ONLY,
                                               {}, (), (), version=self.v1.uid)
        with self.assertRaises(ValueError):
            store.recompute_run(other)
