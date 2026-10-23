# SPDX-License-Identifier: GPL-3.0-or-later
"""Momentos de extracción (spec 011, T16; HU-011-4; RF-011-19, RF-011-20, RF-011-22; plan 011
A13, D-33).

``reserves.stages.stages`` compara la suma de una lista de cubicaciones de la versión (los
momentos: explotación, desdoblado…) con la cubicación directa **desde sus tablas de volúmenes**
(D-33: sin releer las superficies): el desmonte, el terraplén y el desmonte de cada unidad, en
m³ y en %; avisa si la diferencia pasa de la tolerancia (``res.stages_tolerance_pct``) o si las
cubicaciones no usan la misma columna de materiales, y **no ajusta ninguna cifra**. ``res.stages``
es su operación de versión (``reserves.store.stages_run``), con su tabla ``res_stg_`` y sus
cifras, que se recalcula y se reproduce (``reserves.reproduce``).

Datos: (1) cuatro superficies de cotas enteras en 10 × 8 celdas de 2 m (S ≥ M1 ≥ M2 ≥ F donde se
desmonta y al revés donde se rellena), escritas como GeoTIFF en una carpeta temporal y cubicadas
con ``volume_steps`` con una columna de dos unidades (la base de la primera, la cota constante
612): con cotas enteras y celdas de 4 m² toda suma es exacta, así que tres momentos que parten la
directa suman **exactamente** lo mismo; (2) el proyecto de ``tests.support.res_fixtures`` (una
copia por clase) con la columna sintética guardada.
"""

from __future__ import annotations

import json
import math
import shutil
import unittest
from collections.abc import Iterator
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import res_fixtures as fx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

stages = import_geoblender("reserves.stages")
table = import_geoblender("reserves.table")
volumes = import_geoblender("reserves.volumes")
surfaces = import_geoblender("reserves.surfaces")
materials = import_geoblender("reserves.materials")
provenance = import_geoblender("reserves.provenance")
store = import_geoblender("reserves.store")
res_reproduce = import_geoblender("reserves.reproduce")
res_params = import_geoblender("reserves.params")
operations = import_geoblender("core.provenance.operations")
figures_mod = import_geoblender("core.provenance.figures")
graph = import_geoblender("core.provenance.graph")
recompute = import_geoblender("core.provenance.recompute")
registry = import_geoblender("core.datasets.registry")
datasets_model = import_geoblender("core.datasets.model")
readers = import_geoblender("core.content.readers")
versions_reproduce = import_geoblender("core.versions.reproduce")
i18n = import_geoblender("core.i18n")
gis = import_geoblender("gis")
writer = import_geoblender("gis.geotiff.writer")

GRID = gis.project_grid(fx.georef.Window(735_000.0, 4_434_000.0, 735_020.0, 4_434_016.0), 2.0)
"""10 × 8 celdas de 2 m (4 m² cada una)."""
BASE_Z = 612.0
"""La base de la montera: entre M1 y M2."""
COLUMN = materials.MaterialColumn((
    materials.Unit("montera", "Montera", "natural", "waste", "in_situ",
                   surfaces.SurfaceRef(elevation=BASE_Z, label="Cota 612")),
    materials.Unit("capa", "Capa útil", "natural", "useful", "in_situ"),
))
NAMES = {"montera": "Montera", "capa": "Capa útil"}
TOLERANCE = 1.0
"""La tolerancia por defecto de la 011 (%; ``res.stages_tolerance_pct``, D-14 e)."""
CUT, FILL, UNIT = "cut_m3", "fill_m3", "volume_m3"


def _surfaces() -> dict[str, np.ndarray]:
    """Las cotas (enteras) de S, M1, M2 y F: en las columnas 8 y 9 se rellena (S ≤ M1 ≤ M2 ≤ F)
    y en las demás se desmonta (S ≥ M1 ≥ M2 ≥ F), con la base de la montera entre M1 y M2."""
    rows, cols = np.indices(GRID.shape)
    fill = cols >= 8
    return {
        "S": np.where(fill, 600.0, 620.0 + cols % 3),
        "M1": np.where(fill, 601.0, 614.0 + rows % 2),
        "M2": np.where(fill, 602.0 + rows % 2, 609.0 - cols % 2),
        "F": np.where(fill, 604.0, 605.0),
    }


def _last(steps: Iterator[Any]) -> Any:
    """El resultado del último paso de ``steps``."""
    found = None
    for step in steps:
        if step.result is not None:
            found = step.result
    return found


def _figures(items: Any) -> dict[tuple[str, str], float]:
    return {(item.key, figures_mod.scope_json(item.scope)): item.value for item in items}


def _scope(volume: str, **values: Any) -> str:
    return figures_mod.scope_json({"stages": "Fases", "volume": volume, **values})


def _stage_rows(result: Any, stage: str | None) -> dict[tuple[str, str | None], Any]:
    """(dato, unidad) → fila de la tabla de ``result`` del momento ``stage``."""
    return {(item.row.quantity, item.row.unit): item.row for item in result.rows
            if item.stage == stage}


def _totals(source: Any) -> dict[tuple[str, str | None], float]:
    """(dato, unidad) → valor del desmonte, el terraplén y cada unidad de una tabla
    ``res_vol_`` (todos los dominios y todas las rodajas)."""
    return {(item.quantity, item.unit): item.value for item in source.rows
            if item.domain == table.ALL_DOMAINS and item.bench is None and item.component is None
            and (item.quantity in (CUT, FILL) and item.unit is None
                 or item.quantity == UNIT and item.unit is not None)}


class StagesTest(unittest.TestCase):
    """``stages`` sobre las tablas de cubicaciones reales (``volume_steps``) de cotas enteras."""

    tables: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        folder = cls.enterClassContext(project_tmp("gb-st-"))
        sources = {"base": surfaces.constant_source(BASE_Z, name="Cota 612", crs=fx.CRS,
                                                    vertical=fx.VERTICAL)}
        with mock.patch.object(writer, "TILE_SIZE", 16):
            for key, values in _surfaces().items():
                path = folder / f"{key}.tif"
                writer.write_geotiff(gis.Raster(GRID, values, fx.CRS, fx.VERTICAL), path,
                                     profile="project")
                sources[key] = surfaces.grid_source(path, name=key, crs=fx.CRS,
                                                    vertical=fx.VERTICAL)

        def cubicate(name: str, start: str, final: str, *, column: Any = COLUMN,
                     materials_sha: str | None = "h1") -> Any:
            request = volumes.VolumeRequest(
                name, surfaces.SurfaceRef(dataset=f"gis_dtm_{start.lower()}"),
                surfaces.SurfaceRef(dataset=f"gis_dtm_{final.lower()}"), column=column)
            found = {volumes.START: sources[start], volumes.FINAL: sources[final]}
            if column is not None:
                found[volumes.base_role("montera")] = sources["base"]
            result = _last(volumes.volume_steps(request, found))
            return stages.StageTable(name, result.rows, None if column is None
                                     else materials_sha)

        cls.tables = {
            "direct": cubicate("Directa", "S", "F"),
            "first": cubicate("Explotación", "S", "M1"),
            "second": cubicate("Desdoblado", "M1", "M2"),
            "third": cubicate("Stock", "M2", "F"),
            "overlap": cubicate("Desdoblado largo", "M1", "F"),
            "other": cubicate("Desdoblado revisado", "M1", "M2", materials_sha="h2"),
            "plain": cubicate("Stock sin unidades", "M2", "F", column=None),
        }

    def compare(self, *keys: str, tolerance: float = TOLERANCE) -> Any:
        return stages.stages([self.tables[key] for key in keys], self.tables["direct"],
                             name="Fases", tolerance_pct=tolerance, unit_names=NAMES)

    def test_three_stages_that_split_the_direct_add_up_exactly(self) -> None:
        """RF-011-19, RF-011-22: tres momentos que parten la directa suman exactamente lo mismo
        en desmonte, terraplén y cada unidad (diferencia 0 m³ y 0 %, sin aviso); la tabla da
        cada momento por unidad con sus valores tal cual, la suma, la directa y la diferencia,
        y las cifras son la suma y la diferencia (m³ y %) de cada comparación, todas
        finitas."""
        direct = _totals(self.tables["direct"])
        parts = [_totals(self.tables[key]) for key in ("first", "second", "third")]
        cells = _surfaces()
        cut = cells["S"] > cells["F"]
        self.assertEqual(direct[(CUT, None)], 4.0 * float(np.sum((cells["S"] - cells["F"])[cut])))
        for key, value in direct.items():  # de verdad la parten (sumas exactas)
            self.assertEqual(sum(part.get(key, 0.0) for part in parts), value, key)
        self.assertGreater(direct[(FILL, None)], 0.0)

        result = self.compare("first", "second", "third")
        self.assertEqual([(item.quantity, item.unit) for item in result.comparisons],
                         [(CUT, None), (FILL, None), (UNIT, "montera"), (UNIT, "capa")])
        for item in result.comparisons:
            key = (item.quantity, item.unit)
            self.assertEqual((item.sum_m3, item.direct_m3, item.diff_m3, item.diff_pct,
                              item.over), (direct[key], direct[key], 0.0, 0.0, False), key)
            self.assertEqual(item.moments, tuple(part.get(key, 0.0) for part in parts))
        self.assertEqual(result.warnings, ())
        self.assertEqual((result.moments, result.direct, result.tolerance_pct),
                         (("Explotación", "Desdoblado", "Stock"), "Directa", TOLERANCE))

        for key, part in zip(("first", "second", "third"), parts, strict=True):
            rows = _stage_rows(result, self.tables[key].name)
            self.assertEqual({where: item.value for where, item in rows.items()}, part)
        summary = _stage_rows(result, None)
        self.assertEqual(len(summary), 16)
        for prefix, where in (("stages_", (CUT, None)), ("stages_fill_", (FILL, None)),
                              ("stages_", (UNIT, "montera")), ("stages_", (UNIT, "capa"))):
            unit = where[1]
            self.assertEqual(summary[(f"{prefix}sum_m3", unit)].value, direct[where])
            self.assertEqual(summary[(f"{prefix}direct_m3", unit)].value, direct[where])
            self.assertEqual(summary[(f"{prefix}diff_m3", unit)].value, 0.0)
            pct = summary[(f"{prefix}diff_pct", unit)]
            self.assertEqual((pct.value, pct.unit_code, pct.note), (0.0, "%", None))
        self.assertEqual(_figures(result.figures), {
            **{(key, _scope(volume, **extra)): value
               for volume, extra, where in (
                   ("Desmonte", {}, (CUT, None)), ("Terraplén", {}, (FILL, None)),
                   ("Desmonte", {"unit": "montera"}, (UNIT, "montera")),
                   ("Desmonte", {"unit": "capa"}, (UNIT, "capa")))
               for key, value in (("res.stages_sum_m3", direct[where]),
                                  ("res.stages_diff_m3", 0.0), ("res.stages_diff_pct", 0.0))},
        })
        self.assertTrue(all(math.isfinite(item.value) for item in result.figures))
        self.assertEqual({item.unit for item in result.figures}, {"m3", "%"})

    def test_an_overlapping_stage_warns_with_m3_and_percent(self) -> None:
        """RF-011-19: un momento que solapa a otro da el aviso con la diferencia en m³ y en %
        (sobre la directa), por encima de la tolerancia; ninguna cifra se ajusta (cada momento,
        tal cual; la suma, la de los momentos). Con la tolerancia justo en la diferencia, no
        hay aviso (solo si la pasa)."""
        result = self.compare("first", "overlap", "third")
        stock = _totals(self.tables["third"])
        direct = _totals(self.tables["direct"])
        cut = result.comparisons[0]
        parts = [_totals(self.tables[key])[(CUT, None)] for key in ("first", "overlap", "third")]
        self.assertEqual(cut.sum_m3, math.fsum(parts))
        self.assertEqual(cut.diff_m3, stock[(CUT, None)])  # lo que se cuenta dos veces
        self.assertEqual(cut.diff_pct, 100.0 * stock[(CUT, None)] / direct[(CUT, None)])
        self.assertTrue(cut.over)
        for key in ("first", "overlap", "third"):
            rows = _stage_rows(result, self.tables[key].name)
            self.assertEqual({where: item.value for where, item in rows.items()},
                             _totals(self.tables[key]))
        summary = _stage_rows(result, None)
        self.assertEqual(summary[("stages_sum_m3", None)].value, cut.sum_m3)
        self.assertEqual(summary[("stages_diff_pct", None)].note, stages.OVER_TOLERANCE)

        mismatch = [item for item in result.warnings if item.code == "res.stages_mismatch"]
        self.assertEqual([item.values["quantity"] for item in mismatch],
                         ["Desmonte", "Terraplén", "Desmonte de «Capa útil»"])
        number = i18n.format_number
        self.assertEqual(mismatch[0].text(), (
            f"Desmonte: la suma de los momentos ({number(cut.sum_m3, 1)} m³) difiere de la "
            f"cubicación directa «Directa» ({number(cut.direct_m3, 1)} m³) en "
            f"{number(cut.diff_m3, 1)} m³ ({number(cut.diff_pct, 2)} %), más que la tolerancia "
            "de 1 %; no se ha ajustado ninguna cifra."))
        self.assertEqual(_figures(result.figures)[("res.stages_diff_m3", _scope("Desmonte"))],
                         stock[(CUT, None)])

        exact = self.compare("first", "overlap", "third", tolerance=cut.diff_pct)
        self.assertFalse(exact.comparisons[0].over)
        self.assertNotIn("Desmonte", [item.values["quantity"] for item in exact.warnings])

    def test_stages_with_other_columns_warn(self) -> None:
        """RF-011-19 (A13): un momento cubicado con otra columna de materiales, o sin unidades,
        da el aviso que lo nombra con la directa; sin sus unidades, su desmonte cuenta en el
        total pero no en las unidades (nada se reparte por su cuenta)."""
        result = self.compare("first", "other", "plain")
        differ = [item for item in result.warnings if item.code == "res.stages_materials_differ"]
        self.assertEqual([item.text() for item in differ], [
            "«Desdoblado revisado» no usa la misma columna de materiales que «Directa»: sus "
            "unidades no son comparables.",
            "«Stock sin unidades» no usa la misma columna de materiales que «Directa»: sus "
            "unidades no son comparables.",
        ])
        cut, _fill, montera, capa = result.comparisons
        self.assertEqual((cut.diff_m3, cut.over, montera.diff_m3), (0.0, False, 0.0))
        self.assertEqual(capa.diff_m3, -_totals(self.tables["third"])[(UNIT, "capa")])
        self.assertTrue(capa.over)
        self.assertEqual(set(_stage_rows(result, "Stock sin unidades")),
                         {(CUT, None), (FILL, None)})
        self.assertIn("Desmonte de «Capa útil»",
                      [item.values.get("quantity") for item in result.warnings])

    def test_without_direct_volume_no_percent(self) -> None:
        """RF-011-19, RF-011-22: si la directa no tiene ese volumen (el terraplén, aquí) y los
        momentos sí, la diferencia en % no se puede dar: sin valor y con su nota en la tabla,
        sin cifra, y el aviso igualmente."""
        def made(name: str, cut: float, fill: float) -> Any:
            return stages.StageTable(name, (table.row(CUT, cut), table.row(FILL, fill)))

        result = stages.stages([made("A", 60.0, 5.0), made("B", 40.0, 0.0)],
                               made("Directa", 100.0, 0.0), name="Fases",
                               tolerance_pct=TOLERANCE)
        fill = result.comparisons[1]
        self.assertEqual((fill.sum_m3, fill.direct_m3, fill.diff_m3, fill.diff_pct, fill.over),
                         (5.0, 0.0, 5.0, None, True))
        pct = _stage_rows(result, None)[("stages_fill_diff_pct", None)]
        self.assertEqual((pct.value, pct.notes),
                         (None, (stages.NO_DIRECT_VOLUME, stages.OVER_TOLERANCE)))
        found = _figures(result.figures)
        self.assertNotIn(("res.stages_diff_pct", _scope("Terraplén")), found)
        self.assertEqual(found[("res.stages_diff_m3", _scope("Terraplén"))], 5.0)
        (warning,) = result.warnings
        self.assertIn("(? %)", warning.text())

    def test_rejects_malformed_requests(self) -> None:
        """Sin momentos, más de diez, uno repetido, la directa entre los momentos, una
        tolerancia fuera de (0; 100] % o una tabla que no es de volúmenes: errores del
        programa (el diálogo no deja pedirlo)."""
        direct, first = self.tables["direct"], self.tables["first"]
        renamed = [stages.StageTable(f"M{i}", first.rows) for i in range(11)]
        for moments, tolerance in (([], TOLERANCE), (renamed, TOLERANCE),
                                   ([first, first], TOLERANCE), ([first, direct], TOLERANCE),
                                   ([first], 0.0), ([first], math.nan), ([first], 100.5),
                                   ([stages.StageTable("Vacía", ())], TOLERANCE)):
            with self.subTest(moments=len(moments), tolerance=tolerance), \
                    self.assertRaises(ValueError):
                stages.stages(moments, direct, name="Fases", tolerance_pct=tolerance)


def _recompute(request: Any) -> Any:
    """La función de recálculo de prueba de ``res.stages``: la operación nueva de
    ``reserves.store.recompute_run`` con sus pasos avanzados hasta el final."""
    handle, steps = store.recompute_run(request)
    _last(steps)
    return handle


class StagesProjectTest(fx.ResProjectCase):
    """``res.stages`` en V01 del proyecto de la cubicación: tres cubicaciones (la directa y dos
    momentos, uno sin unidades) y su comparación."""

    recompute: ClassVar[Any] = {provenance.STAGES: _recompute}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.column = fx.project_column()
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(cls.project, provenance.EDIT_MATERIALS,
                                            settings={"units": len(cls.column.units)},
                                            executor="blender")
        store.save_materials(cls.project, handle, cls.column)
        cls.base = surfaces.SurfaceRef(dataset=cls.column.unit("capa_util").base.dataset,
                                       label="Techo del muro")
        cls.start = surfaces.SurfaceRef(dataset=fx.START_GRID, label="Partida")
        cls.final = surfaces.SurfaceRef(dataset=fx.FINAL_GRID, label="Final")
        cls.volume("Directa", cls.start, cls.final, column=cls.column)
        cls.volume("Alto", cls.start, cls.base, column=cls.column)
        cls.volume("Bajo", cls.base, cls.final)
        cls.handle, cls.result = cls.compare("Fases", ["Alto", "Bajo"], "Directa")

    @classmethod
    def volume(cls, name: str, start: Any, final: Any, *, column: Any = None,
               supersedes: str | None = None) -> str:
        """``res.volume`` de ``name`` en V01: su uid."""
        request = volumes.VolumeRequest(name, start, final, column=column)
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(
            cls.project, provenance.VOLUME, executor="blender", version=cls.v1.uid,
            supersedes=supersedes, settings=provenance.volume_settings(request),
            inputs=provenance.volume_inputs(request), params=provenance.volume_params(request))
        _last(store.volume_run(cls.project, handle, request))
        return handle.uid

    @classmethod
    def compare(cls, name: str, moments: list[str], direct: str) -> tuple[Any, Any]:
        """``res.stages`` de ``name`` en V01: su operación y su resultado."""
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(
            cls.project, provenance.STAGES, executor="blender", version=cls.v1.uid,
            settings=provenance.stages_settings(name, moments, direct),
            inputs=provenance.stages_inputs(moments, direct),
            params=provenance.stages_params())
        return handle, _last(store.stages_run(cls.project, handle)).result

    def figures(self, uid: str) -> dict[tuple[str, str], float]:
        return {(key, scope): value for key, scope, value in self.query(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def volume_figure(self, name: str, key: str) -> float:
        """La cifra ``key`` del total de la cubicación ``name`` de V01."""
        record = self.record(provenance.dataset_name(provenance.VOLUMES, name), self.v1)
        scope = figures_mod.scope_json({"cubication": name})
        return self.figures(record.operation_uid)[(key, scope)]

    def test_stages_in_v01_and_reproduced(self) -> None:
        """RF-011-19, RF-011-20, RF-011-22: ``res.stages`` es una operación de la revisión
        abierta de V01 que consume las tablas de sus momentos (``stage_1``, ``stage_2``) y de la
        directa (``direct``) con su hash, lee la tolerancia del proyecto y deja su tabla de la
        versión (``res_stg_<n>_v01``, con sus títulos) y sus cifras CALCULADO: la suma es la de
        las cifras de los momentos y la directa, la suya (nada se ajusta). Los dos momentos
        cubican de más donde se rellena (el aviso con m³ y %) y uno no tiene unidades (el aviso
        de la columna). Reproducirla da la misma tabla y las mismas cifras, bit a bit."""
        handle, result = self.handle, self.result
        (revision,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND "
                                 "state = 'open'", self.v1.uid)
        (state,) = self.query("SELECT status, scope, revision_uid FROM gb_operation WHERE "
                              "uid = ?", handle.uid)
        self.assertEqual(state, ("done", "version", revision[0]))
        roles = {"stage_1": "Alto", "stage_2": "Bajo", "direct": "Directa"}
        inputs = {role: self.record(provenance.dataset_name(provenance.VOLUMES, name), self.v1)
                  for role, name in roles.items()}
        self.assertEqual(
            {role: (uid, sha) for uid, sha, role in self.query(
                "SELECT item_uid, content_sha256, role FROM gb_operation_io WHERE "
                "operation_uid = ? AND direction = 'in'", handle.uid)},
            {role: (record.uid, record.content_sha256) for role, record in inputs.items()})
        self.assertEqual([(key, scope, rev, json.loads(value)) for key, scope, rev, value in
                          self.query("SELECT key, scope, rev, value FROM gb_operation_param "
                                     "WHERE operation_uid = ?", handle.uid)],
                         [(res_params.STAGES_TOLERANCE, "project", 1, TOLERANCE)])

        record = self.record(provenance.dataset_name(provenance.STAGE_TABLE, "Fases"), self.v1)
        self.assertEqual((record.locator, record.kind, record.operation_uid),
                         ("res_stg_fases_v01", "table", handle.uid))
        self.assertEqual(dict(self.query("SELECT column_name, name FROM gpkg_data_columns "
                                         "WHERE table_name = ?", record.locator)),
                         dict(table.STAGE_TITLES))
        with self.project.read() as conn:
            self.assertEqual(table.read_stage_rows(conn, record.locator), result.rows)
            self.assertEqual(registry.content_digest(conn, self.project, record).content_sha256,
                             record.content_sha256)
        self.assertEqual(self.figures(handle.uid), _figures(result.figures))
        (kind,) = {row[0] for row in self.query(
            "SELECT kind FROM gb_figure WHERE operation_uid = ?", handle.uid)}
        self.assertEqual(kind, "CALCULADO")

        cut = result.comparison(CUT)
        self.assertEqual(cut.moments, (self.volume_figure("Alto", "res.cut_m3"),
                                       self.volume_figure("Bajo", "res.cut_m3")))
        self.assertEqual(cut.sum_m3, math.fsum(cut.moments))
        self.assertEqual(cut.direct_m3, self.volume_figure("Directa", "res.cut_m3"))
        self.assertGreater(cut.diff_m3, 0.0)
        self.assertEqual(cut.diff_pct, 100.0 * cut.diff_m3 / cut.direct_m3)
        self.assertEqual([(item.code, item.values.get("quantity", item.values.get("name")))
                          for item in result.warnings], [
            ("res.stages_materials_differ", "Bajo"),
            ("res.stages_mismatch", "Desmonte"),
            ("res.stages_mismatch", "Terraplén"),
            ("res.stages_mismatch", "Desmonte de «Montera»"),
            ("res.stages_mismatch", "Desmonte de «Capa útil»"),
            ("res.stages_mismatch", "Desmonte de «Muro»"),
        ])

        folder = self.enterContext(project_tmp("gb-sr-"))
        copy = folder / "proyecto.gpkg"
        shutil.copyfile(self.root / "project.gpkg", copy)
        frozen = tuple(versions_reproduce.FrozenInput(
            role, item.kind, item.reader, item.normalizer, {"main": copy},
            {"layer": item.locator}, item.content_sha256, uid=item.uid, name=item.name)
            for role, item in inputs.items())
        work = folder / "trabajo"
        work.mkdir()
        request = versions_reproduce.ReproduceRequest(
            provenance.STAGES, handle.settings, frozen,
            {res_params.STAGES_TOLERANCE: (1.0, "%")}, work, self.project.record,
            operation_uid=handle.uid)
        again = _last(res_reproduce.REPRODUCE[provenance.STAGES](request))
        (output,) = again.outputs
        self.assertEqual(output.role, "stages")
        reader = readers.reader(record.reader)
        digest = readers.read_content(reader, reader.request(
            record.kind, datasets_model.DATASET_DECLARATIONS, output.files, output.settings,
            normalizer=record.normalizer))
        self.assertEqual(digest.content_sha256, record.content_sha256)
        self.assertEqual(_figures(again.figures), _figures(result.figures))  # bit a bit

    def test_recompute_after_a_stage_changes(self) -> None:
        """RF-011-20 (RF-008-24, RF-008-26): cubicar otra vez un momento con otra superficie
        deja obsoleta la operación de los momentos que usó su tabla; recalcularla registra la
        nueva en la revisión abierta de V01, que sustituye a la anterior, con la suma nueva."""
        low = self.volume("R bajo", self.base, self.final)
        first, before = self.compare("R fases", ["R bajo"], "Directa")
        floor = surfaces.SurfaceRef(elevation=600.0, label="Cota 600")
        self.volume("R bajo", self.base, floor, supersedes=low)
        with self.project.read() as conn:
            stale = dict(graph.deduce(graph.load_graph(conn)).operations)
        self.assertEqual(set(stale), {first.uid})

        self.clock.advance(minutes=1)
        outcome = _last(recompute.recompute_steps(self.project))
        self.assertEqual([item.status for item in outcome.results], [recompute.UnitStatus.DONE])
        (redone,) = outcome.results[0].operations
        (state,) = self.query("SELECT op_type, status, revision_uid, supersedes_uid FROM "
                              "gb_operation WHERE uid = ?", redone)
        (revision,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND "
                                 "state = 'open'", self.v1.uid)
        self.assertEqual(state, (provenance.STAGES, "done", revision[0], first.uid))
        scope = figures_mod.scope_json({"stages": "R fases", "volume": "Desmonte"})
        after = self.figures(redone)[("res.stages_sum_m3", scope)]
        self.assertEqual(self.figures(first.uid)[("res.stages_sum_m3", scope)],
                         before.comparison(CUT).sum_m3)
        self.assertLess(after, before.comparison(CUT).sum_m3)
        self.assertEqual(after, self.volume_figure("R bajo", "res.cut_m3"))


if __name__ == "__main__":
    unittest.main()
