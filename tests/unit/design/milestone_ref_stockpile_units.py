# SPDX-License-Identifier: GPL-3.0-or-later
"""CE-016-07 con proyecto: la cubicación de la 011 con la base y el espesor de una detección **escritos en el proyecto** (spec 016,
T16; HU-016-1; RF-016-09, RF-011-14, RF-011-16, RF-011-20, RF-011-21; D-15, D-17 y D-19 de la 016; ADR-0031 §3; P-13).
Va al paso «hito» de ``check.py --completo`` (la rejilla de 2 m con proyecto y las operaciones de las dos specs); el cálculo
puro, sobre los mismos datos, está en ``tests/referencia/des/test_ref_stockpile_units.py``, en el «verde».

La cantera de los acopios de 2 m con **dos detecciones** hechas por las órdenes de la 016: «Acopios de V01», de V01 sobre su
levantamiento (``des_stp_…``, un dato de versión), y «Acopios del proyecto», del proyecto sobre el levantamiento del proyecto
(D-15; una versión puede consumir un dato del proyecto, RF-009-05). **La 011 no cambia y no importa ``design``**: la columna de
materiales (``res.edit_materials``, del proyecto) lleva, por material de la detección, una unidad antrópica suelta cuya **base y
cuyo espesor son los datos de la detección, por su nombre** (``SurfaceRef(dataset=…)``; ``Detection.materials`` los da), y
``res.volume`` y ``res.tonnage`` (de V01) los leen con ``reserves.store.project_sources`` como cualquier rejilla del proyecto:

- cada cubicación anota **como entradas** los datos de la detección con los papeles ``base_<u>`` y ``thickness_<u>`` (su uid y
  su hash), el umbral de presencia (``res.anthropic_presence_m``) y las densidades como parámetros;
- el volumen de cada unidad es **el de la detección de su material** (la suma de ``des_stk_``) a ≤ 10⁻⁹ relativo y las toneladas,
  ``V·ρ/K`` (suelto);
- **cambiar el umbral** deja obsoletas la detección y la cubicación, con su causa, y «Recalcular lo obsoleto» las repite en orden:
  la cubicación sigue dando **el volumen de la detección nueva** (las huellas cambian), porque los dos leen el mismo umbral.

Los ρ y K de la prueba son **sintéticos** (D-8).
"""

from __future__ import annotations

import json
import math
from typing import Any, ClassVar

import numpy as np

from tests.support import res_fixtures as fx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design import milestone_stockpile_prepare as tp

core_params = import_geoblender("core.params")
geotiff_reader = import_geoblender("gis.geotiff.reader")
design_provenance = import_geoblender("design.provenance")
materials = import_geoblender("reserves.materials")
operations = import_geoblender("core.provenance.operations")
recompute_mod = import_geoblender("core.provenance.recompute")
res_params = import_geoblender("reserves.params")
res_provenance = import_geoblender("reserves.provenance")
res_reproduce = import_geoblender("reserves.reproduce")
res_store = import_geoblender("reserves.store")
stockpile_store = import_geoblender("design.stockpile_store")
surfaces = import_geoblender("reserves.surfaces")
volumes = import_geoblender("reserves.volumes")

TOLERANCE = 1e-9
IN_V01, IN_PROJECT = "Acopios de V01", "Acopios del proyecto"
CODES = {"mineral": "acopio_mineral", "estéril": "acopio_esteril"}
ROLES = {"mineral": materials.Role.USEFUL, "estéril": materials.Role.WASTE}
SYNTHETIC = {"acopio_mineral": (2.60, 1.50), "acopio_esteril": (2.10, 1.30), "terreno": (2.40, 1.20)}
"""La densidad (t/m³) y el K sintéticos de cada unidad (distintos, para que se note cualquier cruce)."""
GROUND = "terreno"
THRESHOLD_KEY = ops.THRESHOLD_KEY
V01_CUBICATION = "Cubicación de los acopios de V01"


def res_recompute(request: Any) -> Any:
    """Lo que registra ``bl`` para repetir una operación de ``res``: ``reserves.store.recompute_run`` llevada hasta el final."""
    handle, work = res_store.recompute_run(request)
    ops.finish(work)
    return handle


def res_definitions() -> tuple[Any, ...]:
    """Las operaciones y las cifras de ``res`` como las registra ``bl`` (el recálculo, el real; la reproducción, la de ``res``)."""
    functions = dict.fromkeys(res_provenance.REPRODUCIBLE, res_recompute)
    again = {op_type: res_reproduce.REPRODUCE[op_type] for op_type in res_provenance.REPRODUCIBLE}
    return (*res_provenance.operation_defs(functions, again), *res_provenance.FIGURES)


def unit_column(detection: Any) -> Any:
    """La columna del proyecto con **una unidad antrópica suelta por material de la detección** (su base y su espesor, por el
    nombre de sus datos) y el terreno in situ al final."""
    units = [materials.Unit(CODES[item.material], f"Acopios de {item.material}", materials.Kind.ANTHROPIC, ROLES[item.material],
                            materials.State.LOOSE, surfaces.SurfaceRef(dataset=item.base.name),
                            surfaces.SurfaceRef(dataset=item.thickness.name)) for item in detection.materials]
    units.append(materials.Unit(GROUND, "Terreno", materials.Kind.NATURAL, materials.Role.WASTE, materials.State.IN_SITU))
    return materials.MaterialColumn(tuple(units))


class UnitsCase(ops.RecomputeCase):
    """Lo de ``RecomputeCase`` (la cantera con las operaciones de la detección) más las de ``res`` y los parámetros sintéticos
    de las tres unidades, y las ayudas de cubicar una detección: la columna guardada, ``res.volume`` y ``res.tonnage`` de V01."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*super().definitions(), *res_definitions())

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(res_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "res")
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for code, (density, swell) in SYNTHETIC.items():
                for key, value in ((res_params.density_key(code), density), (res_params.swell_key(code), swell)):
                    store.create(conn, key, value, kind="HIPÓTESIS", reason="Prueba de la 016 (T16)", **fx.PARAMS_BY_HAND)

    # --- Cubicar ----------------------------------------------------------------------------------

    @classmethod
    def save_column(cls, column: Any) -> Any:
        """Guarda ``column`` como la del proyecto (``res.edit_materials``)."""
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(cls.project, res_provenance.EDIT_MATERIALS, settings={"units": len(column.units)},
                                            executor="blender")
        return res_store.save_materials(cls.project, handle, column)

    def cubicate(self, detection: Any, name: str, start: str) -> tuple[Any, Any, Any, Any]:
        """Cubica en V01 ``start`` contra una cota constante por debajo de todo con la columna de ``detection`` (la guarda como la
        del proyecto): ``(volumen, toneladas, operación de volumen, operación de toneladas)``, lo guardado y las dos operaciones
        (``res.volume`` y ``res.tonnage``)."""
        column = unit_column(detection)
        self.save_column(column)
        floor = math.floor(float(np.nanmin(sdata.survey(self.grid)))) - 20.0
        request = volumes.VolumeRequest(name, surfaces.SurfaceRef(dataset=start), surfaces.SurfaceRef(elevation=floor), column=column)
        self.clock.advance(minutes=1)
        volume = operations.begin_operation(
            self.project, res_provenance.VOLUME, executor="blender", version=self.v1.uid,
            settings=res_provenance.volume_settings(request), inputs=res_provenance.volume_inputs(request),
            params=res_provenance.volume_params(request))
        found = ops.last(res_store.volume_run(self.project, volume, request))
        self.clock.advance(minutes=1)
        tonnage = operations.begin_operation(
            self.project, res_provenance.TONNAGE, executor="blender", version=self.v1.uid,
            settings=res_provenance.tonnage_settings(name), inputs=res_provenance.tonnage_inputs(name),
            params=res_provenance.tonnage_params(column))
        weighed = ops.last(res_store.tonnage_run(self.project, tonnage))
        return found, weighed, volume, tonnage

    # --- Lo que dice el proyecto -------------------------------------------------------------------

    def figures(self, uid: str) -> list[tuple[str, dict[str, Any], float]]:
        """Las cifras de la operación ``uid``: ``(clave, ámbito, valor)``."""
        return [(key, json.loads(scope), value) for key, scope, value in self.query(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ? ORDER BY fid", uid)]

    def figure(self, uid: str, key: str, **scope: Any) -> float:
        """El valor de la cifra ``key`` con ese ámbito de la operación ``uid``."""
        (value,) = [item for found, where, item in self.figures(uid) if found == key and where == scope]
        return float(value)

    def inputs(self, uid: str) -> dict[str, tuple[str, str]]:
        """Lo que anotó la operación ``uid`` al empezar: papel → (uid del dato, hash)."""
        return {role: (item, sha) for item, sha, role in self.query(
            "SELECT item_uid, content_sha256, role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in'", uid)}

    def detected(self, name: str, material: str, *, version: bool) -> float:
        """El volumen de la detección ``name`` de los acopios de ``material``: la suma de su tabla ``des_stk_`` (m³)."""
        rows = stockpile_store.read_detection_table(self.project, design_provenance.STOCKPILES_TABLE, name,
                                                    version_uid=self.v1.uid if version else "")
        return math.fsum(row["volume_m3"] for row in rows if row["material"] == material)

    def footprint_cells(self, name: str, material: str, *, version: bool) -> int:
        """Las celdas de las huellas de los acopios de ``material`` de la detección ``name`` (la suma de ``cells`` de ``des_stk_``)."""
        rows = stockpile_store.read_detection_table(self.project, design_provenance.STOCKPILES_TABLE, name,
                                                    version_uid=self.v1.uid if version else "")
        return sum(int(row["cells"]) for row in rows if row["material"] == material)

    def assertRelative(self, found: float, wanted: float, what: str = "") -> None:  # noqa: N802
        self.assertGreater(wanted, 0.0, what)
        self.assertLessEqual(abs(found - wanted) / wanted, TOLERANCE, f"{what}: {found!r} frente a {wanted!r}")

    def current_detection(self, name: str, surface: str) -> Any:
        """La detección al día ``name`` hecha sobre ``surface`` (la consulta de la T14)."""
        (found,) = [item for item in stockpile_store.detections_on(self.project, self.v1.uid, surface) if item.name == name]
        return found

    def check_cubication(self, detection: Any, name: str, stored: tuple[Any, Any, Any, Any], *, version: bool) -> None:
        """La cubicación ``name`` de ``detection`` es la de la detección: sus entradas, el volumen de cada unidad, las toneladas
        ``V·ρ/K`` y el desmonte."""
        volume, weighed, volume_op, tonnage_op = stored
        inputs = self.inputs(volume_op.uid)
        for item in detection.materials:
            code = CODES[item.material]
            self.assertEqual(inputs[volumes.base_role(code)], (item.base.uid, self.dataset_hash(item.base.uid)), code)
            self.assertEqual(inputs[volumes.thickness_role(code)], (item.thickness.uid, self.dataset_hash(item.thickness.uid)), code)
            expected = self.detected(detection.name, item.material, version=version)
            density, swell = SYNTHETIC[code]
            footprint = self.footprint_cells(detection.name, item.material, version=version)
            for data in (item.base, item.thickness):  # dispersos: dato solo en las huellas de su material
                grid = geotiff_reader.read_geotiff(self.root / data.locator).values
                self.assertEqual(int(np.count_nonzero(np.isfinite(grid))), footprint, data.name)
            self.assertGreaterEqual(float(np.nanmin(geotiff_reader.read_geotiff(self.root / item.thickness.locator).values)), 0.0)
            with self.subTest(detection=detection.name, material=item.material):
                self.assertRelative(self.figure(volume_op.uid, "res.unit_volume_m3", cubication=name, unit=code), expected, "m³")
                self.assertRelative(self.figure(tonnage_op.uid, "res.unit_t", cubication=name, unit=code), expected * density / swell,
                                    "V·ρ/K")
        cut = self.figure(volume_op.uid, "res.cut_m3", cubication=name)
        units = math.fsum(self.figure(volume_op.uid, "res.unit_volume_m3", cubication=name, unit=unit.code)
                          for unit in unit_column(detection).units)
        self.assertRelative(units, cut, "las unidades suman el desmonte")
        self.assertRelative(volume.result.cut_m3, cut)
        self.assertEqual(self.inputs(tonnage_op.uid).keys(), {"volumes", "materials"})
        self.assertEqual(weighed.outputs.result.missing, ())

    def dataset_hash(self, uid: str) -> str:
        ((sha,),) = self.query("SELECT content_sha256 FROM gb_dataset WHERE uid = ?", uid)
        return str(sha)


class ProjectUnitsTest(UnitsCase):
    """RF-016-09, RF-011-14, RF-011-16, RF-011-20, RF-011-21, D-15, D-17, CE-016-07: **en orden** (``test_a`` a ``test_c``)."""

    version_stored: ClassVar[tuple[Any, ...]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create(tp.request(IN_V01, surface=tp.VERSION_SURFACE))
        cls.create(tp.request(IN_PROJECT), version=None, masks=None)

    def test_a_a_version_detection_is_taken_as_one_unit_per_material(self) -> None:
        """CE-016-07, RF-016-09, RF-011-14, RF-011-16, RF-011-20: la detección de V01 sobre su levantamiento da **dos unidades**
        (``mineral`` y ``estéril``, más el terreno): ``res.volume`` anota como entradas la base y el espesor de cada una (los
        datos de la detección, con su hash) y el umbral de la 011, el volumen de cada unidad es el de la detección de su
        material a ≤ 10⁻⁹ y las toneladas, ``V·ρ/K``; los datos de la detección no cambian."""
        detection = self.current_detection(IN_V01, tp.VERSION_SURFACE)
        self.assertEqual([item.material for item in detection.materials], ["mineral", "estéril"])
        hashes = {item.uid: self.dataset_hash(item.uid) for found in detection.materials for item in (found.base, found.thickness)}
        stored = type(self).version_stored = self.cubicate(detection, V01_CUBICATION, tp.VERSION_SURFACE)
        self.assertEqual(self.query("SELECT status, scope FROM gb_operation WHERE uid = ?", stored[2].uid), [("done", "version")])
        self.check_cubication(detection, V01_CUBICATION, stored, version=True)
        self.assertEqual({uid: self.dataset_hash(uid) for uid in hashes}, hashes, "las entradas no cambian")
        self.assertEqual(self.stale_causes(stored[2].uid), set())
        self.assertEqual(self.stale_causes(stored[3].uid), set())

    def test_b_a_project_detection_is_consumed_from_a_version(self) -> None:
        """CE-016-07, RF-016-09, D-15, RF-009-05: lo mismo con la detección **del proyecto** (sobre el levantamiento del
        proyecto, sin versión): la cubicación de V01 la lee como una rejilla del proyecto (sus datos no llevan código de
        versión) y da el volumen de **esa** detección, con sus toneladas."""
        detection = self.current_detection(IN_PROJECT, sdata.SURVEY_DATASET)
        self.assertEqual((detection.scope, detection.version), (stockpile_store.PROJECT, None))
        stored = self.cubicate(detection, "Cubicación de los acopios del proyecto", sdata.SURVEY_DATASET)
        self.check_cubication(detection, "Cubicación de los acopios del proyecto", stored, version=False)

    def test_c_the_threshold_is_the_same_for_the_detection_and_the_cubication(self) -> None:
        """D-17, CE-016-07, RF-011-21, RF-016-10: el umbral de presencia (``res.anthropic_presence_m``) lo leen la detección **y** la
        011, así que cambiarlo (0,3 → 0,6 m) deja obsoletas las dos (con la causa del parámetro) y «Recalcular lo obsoleto» las repite
        en orden: la cubicación sigue dando **el volumen de la detección nueva** (las huellas cambiaron y el volumen también) y sus
        toneladas, ``V·ρ/K``."""
        detection = self.current_detection(IN_V01, tp.VERSION_SURFACE)
        before = {item.material: self.detected(IN_V01, item.material, version=True) for item in detection.materials}
        _found, _weighed, volume_op, tonnage_op = self.version_stored
        self.change_threshold(0.6)
        self.assertEqual(self.stale_causes(self.current()), {("parameter_changed", THRESHOLD_KEY)})
        self.assertIn(("parameter_changed", THRESHOLD_KEY), self.stale_causes(volume_op.uid))
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertTrue(all(result.status is recompute_mod.UnitStatus.DONE for result in outcome.results), outcome.results)
        self.assertEqual(self.recompute_plan(), [])
        again = self.current_detection(IN_V01, tp.VERSION_SURFACE)
        after = {item.material: self.detected(IN_V01, item.material, version=True) for item in again.materials}
        self.assertNotEqual(after, before, "el umbral cambió las huellas")
        ((new_volume,),) = self.query("SELECT uid FROM gb_operation WHERE supersedes_uid = ?", volume_op.uid)
        ((new_tonnage,),) = self.query("SELECT uid FROM gb_operation WHERE supersedes_uid = ?", tonnage_op.uid)
        self.assertEqual(self.stale_causes(new_volume), set())
        for item in again.materials:
            code = CODES[item.material]
            density, swell = SYNTHETIC[code]
            self.assertRelative(self.figure(new_volume, "res.unit_volume_m3", cubication=V01_CUBICATION, unit=code),
                                after[item.material], "m³")
            self.assertRelative(self.figure(new_tonnage, "res.unit_t", cubication=V01_CUBICATION, unit=code),
                                after[item.material] * density / swell, "V·ρ/K")
