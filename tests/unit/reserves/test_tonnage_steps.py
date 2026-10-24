# SPDX-License-Identifier: GPL-3.0-or-later
"""El paso del tonelaje, troceado (spec 011, T33; RNF-011-04; RF-011-20, RF-011-25; plan 011
A10, A11, D-16, R4).

En el HITO H1, el paso de ``res.tonnage`` que pesa la tabla de volúmenes
(``reserves.volumes.tonnage_outputs``) y calcula el hash de su tabla ``res_ton_`` tardaba
0,26–0,29 s en **una** llamada con el caso de RNF-011-02 (28 712 filas), frente a los 0,2 s por
llamada de RNF-011-04. ``reserves.store.tonnage_run`` pesa y calcula el hash por pasos de su
presupuesto (``budget_s``, 0,05 s): ninguna llamada pasa de 0,2 s —la confirmación, una
transacción, es lo único que no se trocea (R4)— y la tabla, su hash y sus cifras son los de antes
(los del código anterior, ``36d9460``, escritos aquí). Cerrar los pasos a mitad no deja nada.

Datos: el proyecto de ``tests.support.res_fixtures`` (una copia por clase) con la columna de
RNF-011-02 (8 unidades: una compuesta y dos antrópicas sueltas; las de los datos de §2.2 del plan)
y sus parámetros sintéticos, y la tabla de volúmenes de ese caso (el total, 20 dominios y «Fuera
de los dominios»; 28 rodajas: 6 999 filas, como la de su cubicación de 2,81 M celdas) escrita como
salida de un ``res.volume`` de V01: es lo que lee ``res.tonnage`` (D-16), sin las once superficies,
que no cambian este paso.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from tests.support import res_fixtures as fx
from tests.support.package import import_geoblender
from tests.support.timing import drive_steps, least_of, raised_priority

provenance = import_geoblender("reserves.provenance")
store = import_geoblender("reserves.store")
table = import_geoblender("reserves.table")
volumes = import_geoblender("reserves.volumes")
surfaces = import_geoblender("reserves.surfaces")
materials = import_geoblender("reserves.materials")
params = import_geoblender("reserves.params")
operations = import_geoblender("core.provenance.operations")
figures_mod = import_geoblender("core.provenance.figures")
registry = import_geoblender("core.datasets.registry")

CALL_BUDGET_S = 0.2
"""RNF-011-04: lo que hace Geoblender en cada llamada del hilo de Blender mientras se cubica."""
TINY_S = 1e-9
"""Un presupuesto de paso diminuto: cada paso hace una sola unidad de trabajo."""
NAME = "Reparto RNF"
DOMAINS = 20
BENCHES = 28
BENCH_FLOOR_M, BENCH_HEIGHT_M = 690.0, 8.9
VOLUME_ROWS = 6_999
TONNAGE_ROWS = 28_712
FIGURES = 372
TABLE_SHA256 = "051978fc159be330fae4a9007ad36ca3f5d077117aee1981855c5541b8655fcb"
"""El hash de contenido de la tabla ``res_ton_`` del caso con el código anterior (``36d9460``)."""
FIGURES_SHA256 = "277b20acb72920291edee304acad6a961cee302aeb386c5e80b46da3e140a61d"
"""La huella de sus cifras (:func:`_figures_sha`, con el nombre :data:`NAME`) con el código
anterior (``36d9460``)."""
START = surfaces.SurfaceRef(dataset=fx.START_GRID, label="Partida")
FINAL = surfaces.SurfaceRef(dataset=fx.FINAL_GRID, label="Final")


def rnf_column() -> Any:
    """La columna de RNF-011-02 (plan §2.2): dos antrópicas sueltas (escombro y acopio), una
    compuesta (arena y arcilla) y cinco naturales in situ; sus bases y espesores, rejillas del
    proyecto (no se leen: las toneladas no releen las superficies)."""
    unit, component = materials.Unit, materials.Component
    bases = [name for name in fx.PROJECT_GRIDS if name not in (fx.START_GRID, fx.FINAL_GRID)]

    def ref(position: int) -> Any:
        return surfaces.SurfaceRef(dataset=bases[position % len(bases)], label=f"Capa {position}")

    return materials.MaterialColumn((
        unit("escombro", "Escombro", "anthropic", "waste", "loose", ref(0), ref(1), ()),
        unit("acopio", "Acopio", "anthropic", "useful", "loose", ref(2), ref(3), ()),
        unit("montera", "Montera", "natural", "waste", "in_situ", ref(4), None, ()),
        unit("caliza", "Caliza", "natural", "useful", "in_situ", ref(5), None, ()),
        unit("mixta", "Capa mixta", "compound", None, "in_situ", ref(6), None,
             (component("arena", "Arena", "useful"), component("arcilla", "Arcilla", "waste"))),
        unit("margas", "Margas", "natural", "waste", "in_situ", ref(7), None, ()),
        unit("dolomia", "Dolomía", "natural", "useful", "in_situ", ref(8), None, ()),
        unit("muro", "Muro", "natural", "waste", "in_situ", None, None, ()),
    ))


def rnf_values(column: Any) -> dict[str, float]:
    """Los parámetros sintéticos de la columna (los del H1): densidad, K y porcentajes."""
    found: dict[str, float] = {}
    for position, unit in enumerate(column.units):
        if not unit.components:
            found[params.density_key(unit.code)] = 2.0 + 0.05 * position
            found[params.swell_key(unit.code)] = 1.2 + 0.03 * position
            continue
        for number, (item, share) in enumerate(zip(unit.components, (70.0, 30.0), strict=True)):
            found[params.density_key(unit.code, item.code)] = 2.3 + 0.1 * number
            found[params.swell_key(unit.code, item.code)] = 1.3 + 0.05 * number
            found[params.percent_key(unit.code, item.code)] = share
    return found


def rnf_volume_rows(column: Any) -> tuple[Any, ...]:
    """La tabla de volúmenes del caso, fila a fila como la escribe ``res.volume``
    (``volumes._volume_result``): por el total, cada dominio y lo de fuera, sus seis totales, el
    desmonte y el terraplén de cada rodaja y, de cada unidad, su volumen, sus tres áreas y su
    volumen en cada rodaja; al final la cota media y el factor de escala (sin él). Los valores,
    sintéticos (algunos volúmenes, 0)."""
    found: list[Any] = []
    benches = [(BENCH_FLOOR_M + BENCH_HEIGHT_M * k, BENCH_FLOOR_M + BENCH_HEIGHT_M * (k + 1))
               for k in range(BENCHES)]
    domains = [table.ALL_DOMAINS, *(f"D{n:02d}" for n in range(1, DOMAINS + 1)),
               table.OUTSIDE_DOMAINS]
    for d, domain in enumerate(domains):
        for q, quantity in enumerate(("cut_m3", "fill_m3", "net_m3", "area_m2",
                                      "nodata_area_m2", "still_area_m2")):
            found.append(table.row(quantity, 1000.0 * (q + 1) + 17.25 * d, domain=domain))
        for side, factor in (("cut_m3", 1.0), ("fill_m3", 0.125)):
            for k, bench in enumerate(benches):
                found.append(table.row(side, factor * (50.0 + 3.5 * k + d), domain=domain,
                                       bench=bench))
        for u, unit in enumerate(column.units):
            found.append(table.row("volume_m3", 400.0 + 31.5 * u + 2.25 * d, domain=domain,
                                   unit=unit.code))
            for a, quantity in enumerate(("absent_area_m2", "absent_nodata_area_m2",
                                          "crossed_area_m2")):
                found.append(table.row(quantity, 4.0 * a + u, domain=domain, unit=unit.code))
            for k, bench in enumerate(benches):
                value = 0.0 if (u + k + d) % 11 == 0 else 7.5 + 0.375 * k + u + 0.0625 * d
                found.append(table.row("volume_m3", value, domain=domain, bench=bench,
                                       unit=unit.code))
    found.append(table.row("mean_elevation_m", 812.5))
    notes = ("res.note_no_scale_factor",)
    found.append(table.row("grid_scale_factor", None, notes=notes))
    found.append(table.row("ground_effect_pct", None, notes=notes))
    return tuple(found)


def _figures_sha(figures: Iterable[tuple[str, str, float, str]]) -> str:
    """Una huella de las cifras ``(clave, ámbito JSON, valor, unidad)``, sin importar su orden."""
    lines = sorted(f"{key}\t{scope}\t{float(value).hex()}\t{unit}"
                   for key, scope, value, unit in figures)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _as_named(figures: Iterable[tuple[str, str, float, str]], name: str
              ) -> list[tuple[str, str, float, str]]:
    """Las cifras de la cubicación ``name`` como si fueran de la de :data:`NAME` (su ámbito)."""
    found = []
    for key, scope, value, unit in figures:
        where = json.loads(scope)
        if where.get("cubication") != name:
            raise AssertionError(f"la cifra {key} {scope} no es de «{name}»")
        found.append((key, figures_mod.scope_json({**where, "cubication": NAME}), value, unit))
    return found


def spec_figures(specs: Iterable[Any]) -> list[tuple[str, str, float, str]]:
    """Las cifras ``FigureSpec`` como las guarda ``gb_figure``."""
    return [(spec.key, figures_mod.scope_json(spec.scope), spec.value, spec.unit)
            for spec in specs]


class TonnageStepsTest(fx.ResProjectCase):
    """``res.tonnage`` de la tabla de volúmenes de RNF-011-02 en V01, por pasos."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.column = rnf_column()
        cls.values = rnf_values(cls.column)
        cls.declare(cls.values)
        handle = operations.begin_operation(cls.project, provenance.EDIT_MATERIALS,
                                            settings={"units": len(cls.column.units)},
                                            executor="blender")
        store.save_materials(cls.project, handle, cls.column)
        cls.volume_rows = rnf_volume_rows(cls.column)
        cls.cubication(NAME)

    @classmethod
    def cubication(cls, name: str) -> None:
        """La tabla de volúmenes del caso como salida del ``res.volume`` ``name`` de V01."""
        request = volumes.VolumeRequest(name, START, FINAL)
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(
            cls.project, provenance.VOLUME, executor="blender", version=cls.v1.uid,
            settings=provenance.volume_settings(request),
            inputs=provenance.volume_inputs(request), params=provenance.volume_params(request))
        with store.ResultWriter(cls.project, handle) as out:
            out.table(provenance.VOLUMES, name, cls.volume_rows)
            out.commit(message="La tabla de volúmenes de RNF-011-02")

    def begin(self, name: str = NAME) -> Any:
        """Una operación ``res.tonnage`` de la cubicación ``name`` en V01, «en curso», que
        sustituye a la anterior del mismo nombre si la hay (D-30)."""
        self.clock.advance(minutes=1)
        return operations.begin_operation(
            self.project, provenance.TONNAGE, executor="blender", version=self.v1.uid,
            settings=provenance.tonnage_settings(name), inputs=provenance.tonnage_inputs(name),
            params=provenance.tonnage_params(self.column),
            supersedes=store.previous_operation(self.project, provenance.TONNAGE, name,
                                                version=self.v1.uid))

    def stored_figures(self, uid: str) -> list[tuple[str, str, float, str]]:
        return self.query("SELECT key, scope, value, unit FROM gb_figure WHERE "
                          "operation_uid = ?", uid)

    def test_no_call_over_its_budget_with_the_case_of_rnf_011_02(self) -> None:
        """RNF-011-04 (R4): con la tabla de volúmenes de RNF-011-02 (6 999 filas) y su columna,
        ninguna llamada a los pasos de ``res.tonnage`` pasa de 0,2 s: pesar y calcular el hash
        de su tabla de 28 712 filas van por pasos; la confirmación, una transacción, en la suya.
        Se mide con la prioridad del hilo subida y, con la máquina cargada, hasta tres veces,
        cada una con una cubicación nueva (sin sustituir la tabla de antes). RF-011-20,
        RF-011-22: la tabla ``res_ton_`` (su hash, también el que da el registro al leerla) y sus
        372 cifras son las del código anterior."""
        runs: list[tuple[str, Any, Any]] = []

        def longest() -> float:
            name = NAME if not runs else f"{NAME} {len(runs) + 1}"
            if runs:
                self.cubication(name)
            handle = self.begin(name)
            with raised_priority():
                run = drive_steps(store.tonnage_run(self.project, handle))
            runs.append((name, handle, run))
            return run.longest_s

        worst = least_of(longest, CALL_BUDGET_S, max_attempts=3)
        self.assertLessEqual(worst, CALL_BUDGET_S,
                             f"una llamada tardó {worst * 1000:.0f} ms")
        name, handle, run = runs[-1]
        self.assertEqual(len(self.volume_rows), VOLUME_ROWS)
        outputs = run.result.outputs
        self.assertEqual(len(outputs.rows), TONNAGE_ROWS)
        record = self.record(provenance.dataset_name(provenance.TONNES, name), self.v1)
        self.assertEqual((record.operation_uid, record.content_sha256), (handle.uid, TABLE_SHA256))
        with self.project.read() as conn:  # la tabla escrita da el hash calculado antes
            self.assertEqual(registry.content_digest(conn, self.project, record).content_sha256,
                             TABLE_SHA256)
        stored = self.stored_figures(handle.uid)
        self.assertEqual(len(stored), FIGURES)
        self.assertEqual(_figures_sha(_as_named(stored, name)), FIGURES_SHA256)
        self.assertEqual(_figures_sha(_as_named(spec_figures(outputs.figures), name)),
                         FIGURES_SHA256)

    def test_each_unit_of_work_a_step_and_closing_midway_leaves_nothing(self) -> None:
        """RNF-011-04, RF-011-25: con un presupuesto diminuto, pesar y calcular el hash dan
        muchos pasos (una parte de la tabla, un trozo del hash), con su avance creciente y sin
        pasar de su total; cerrarlos mientras se calcula el hash deja la operación «cancelada»
        sin tabla ni cifras, y la tabla de antes (si la había), intacta."""
        before = self.record(provenance.dataset_name(provenance.TONNES, NAME), self.v1)
        handle = self.begin()
        steps = store.tonnage_run(self.project, handle, budget_s=TINY_S)
        seen: list[Any] = []
        hashing = 0
        for step in steps:
            seen.append(step)
            hashing += step.phase == "hash"
            if hashing == 3:
                break
        steps.close()
        phases = [step.phase for step in seen]
        self.assertEqual(phases[0], "read")
        self.assertGreater(phases.count("weigh"), 1_000)
        self.assertEqual(phases.count("hash"), 3)
        done = [step.done for step in seen]
        self.assertEqual(done, sorted(done))
        self.assertTrue(all(0 < step.done < step.total for step in seen))
        (state,) = self.query("SELECT status, status_reason FROM gb_operation WHERE uid = ?",
                              handle.uid)
        self.assertEqual(state, ("cancelled", store.CANCELLED_REASON))
        self.assertEqual(self.stored_figures(handle.uid), [])
        after = self.record(provenance.dataset_name(provenance.TONNES, NAME), self.v1)
        self.assertEqual(None if after is None else (after.uid, after.content_sha256),
                         None if before is None else (before.uid, before.content_sha256))
        self.assertEqual(operations.claimed_paths(self.project), frozenset())
