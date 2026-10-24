# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de la cubicación entre superficies (spec 011, T27; RNF-011-01, RNF-011-02,
RNF-011-03 y RNF-011-06; plan 011 §2.2 y §7.3, ``tests/rendimiento/res``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4) en el PC
de referencia de la spec 001 §5. Cada prueba imprime su cifra en una línea ``RNF-011-nn: …``
con el equipo, el intérprete y el espacio libre del disco en que escribe (trampa §6: un
``fsync`` lento con el disco casi lleno), que ``tools/check.py`` recoge, y la compara con su
presupuesto, sin relajarlo (spec 011 §5: mediana de 5).

**Datos** (plan §2.2; se generan aquí, no se versionan y se borran al terminar:
``tests/support/res_perf.py``): la rejilla de 1 654 × 1 699 celdas de 1 m (2,81 M) con el
terreno de colinas, el ondulado y el ruido de 5 cm, la corta de 120 m, el relleno y el hueco sin
dato; las bases de las unidades (dos de ellas, la base de una antrópica: el terreno menos su
espesor) y los espesores de las dos antrópicas; 20 dominios de bordes ondulados compartidos
(31 920 vértices) importados con el papel «dominios» (``gis_dom_``) y la columna de 8 unidades
de RNF-011-02 (una compuesta y dos antrópicas) con sus parámetros sintéticos (D-8: ninguno es de
un material real). Todo como rejillas y capas de un proyecto nuevo (EPSG:25830 + EPSG:5782) con
V01, en ``%TEMP%``.

**Cómo se mide**: con las funciones del dominio como la orden (``begin_operation`` con lo que
anotan las ayudas de ``reserves.provenance`` y los pasos de ``reserves.store.volume_run`` y
``tonnage_run``, D-16), los pasos llevados uno tras otro como el temporizador del modal
(``tests.support.versions_perf.drive``: el total, cada llamada y el mayor hueco del avance). El
total con el modal añade, como mucho, una espera de su temporizador (``TIMER_INTERVAL_S``) por
cada evento (cada uno avanza pasos hasta pasar de ``MODAL_EVENT_S``; ``bl.ops.core._StepsModal``):
es lo que se compara con el presupuesto. Lo de cada llamada del hilo de Blender con la orden real
(RNF-011-04) y el panel (RNF-011-05) se miden dentro de Blender (T28, ``perf_res.py``).

- RNF-011-01 (:class:`BetweenSurfacesTest`): cubicar entre las dos superficies (desmonte,
  terraplén, neto y áreas, sin repartos; con la rejilla de diferencias, como la orden por
  defecto), desde la orden hasta las cifras registradas: ≤ 3 s.
- RNF-011-02 (:class:`BreakdownTest`): repartir esas celdas en las 8 unidades, los 20 dominios y
  30 rodajas (``res.volume`` y las toneladas encadenadas, ``res.tonnage``): ≤ 20 s; el mayor
  hueco del avance ≤ 1 s; Esc con el avance a la mitad: la llamada más larga más cerrar los
  pasos ≤ 2 s, la operación «cancelada» y nada en el proyecto.
- RNF-011-03 (:class:`BreakdownTest`): el pico de memoria adicional de ese reparto
  (``tracemalloc``, con la de numpy) ≤ 1,5 GB.
- RNF-011-06 (:class:`ExportTest`): exportar a CSV la cubicación de la tabla de RNF-011-05 (20
  dominios × 30 rodajas × 10 unidades: la columna con dos unidades más) con sus toneladas
  (``reserves.export.cubication_export`` y ``write_csv``, en ``exports/``): ≤ 1 s.

**En la red** (:class:`NetworkTest`; recurso «red»: la carpeta de pruebas de
``GEOBLENDER_NET_TEST_DIR``, nunca la de los expedientes ni la del espejo; sin ella, se omite):
el mismo proyecto creado en una subcarpeta temporal propia que se borra al terminar, con los
datos de usuario en disco local (como en un puesto): RNF-011-01 ≤ 10 s y RNF-011-02 ≤ 45 s, con
el avance ≤ 1 s y Esc ≤ 2 s. Escribe unos 200 MB en la red y tarda alrededor de un minuto.
"""

from __future__ import annotations

import gc
import statistics
import unittest
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import gis_perf, network
from tests.support import res_fixtures as fx
from tests.support import res_perf as data
from tests.support import versions_perf as vperf
from tests.support.core_fixtures import FakeClock, make_settings, project_tmp
from tests.support.package import import_geoblender
from tests.support.resources import requires

gis = import_geoblender("gis")
gis_provenance = import_geoblender("gis.provenance")
provenance = import_geoblender("reserves.provenance")
store = import_geoblender("reserves.store")
volumes = import_geoblender("reserves.volumes")
surfaces = import_geoblender("reserves.surfaces")
slices_mod = import_geoblender("reserves.slices")
materials = import_geoblender("reserves.materials")
params = import_geoblender("reserves.params")
table = import_geoblender("reserves.table")
export = import_geoblender("reserves.export")
operations = import_geoblender("core.provenance.operations")
figures_mod = import_geoblender("core.provenance.figures")
core_params = import_geoblender("core.params")
create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
versions_store = import_geoblender("core.versions.store")
paths = import_geoblender("core.paths")

BETWEEN_BUDGET_S = 3.0  # RNF-011-01, en disco local
NET_BETWEEN_BUDGET_S = 10.0  # RNF-011-01, en Z:
BREAKDOWN_BUDGET_S = 20.0  # RNF-011-02, en disco local
NET_BREAKDOWN_BUDGET_S = 45.0  # RNF-011-02, en Z:
PROGRESS_GAP_S = 1.0  # RNF-011-02: progreso cada ≤ 1 s
CANCEL_BUDGET_S = 2.0  # RNF-011-02: cancelación efectiva en ≤ 2 s
MEMORY_BUDGET_BYTES = 1.5e9  # RNF-011-03: 1,5 GB
EXPORT_BUDGET_S = 1.0  # RNF-011-06
RUNS = 5  # spec 011 §5: mediana de 5
CANCEL_AT = 0.5  # Esc con el avance a la mitad
CLOSURE_TOLERANCE = 1e-12  # relativa: los repartos cierran con el total (plan §2.2: ≈ 1e-16)

MODAL_EVENT_S = 0.1
"""Lo que avanza pasos cada evento del modal (``bl.ops.core._StepsModal.STEP_BUDGET_S``)."""
TIMER_INTERVAL_S = 0.05
"""Su temporizador (``bl.ops.core._StepsModal.TIMER_INTERVAL_S``): como mucho, la espera hasta
el evento siguiente."""

START = surfaces.SurfaceRef(dataset=gis_provenance.dataset_name(gis_provenance.PROJECT_GRID,
                                                                data.START), label=data.START)
FINAL = surfaces.SurfaceRef(dataset=gis_provenance.dataset_name(gis_provenance.PROJECT_GRID,
                                                                data.FINAL), label=data.FINAL)
NO_READ_ONLY = paths.ReadOnlyDirs.from_sources(None, [])
DOMAINS_NAME = "Dominios"
DOMAINS_LAYER = "dominios"
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count


# --- El proyecto de §2.2 -----------------------------------------------------------------------


def _grid() -> Any:
    return gis.Grid(data.WEST, data.NORTH, data.STEP, data.STEP, data.COLS, data.ROWS)


def _ref(label: str | None) -> Any:
    if label is None:
        return None
    return surfaces.SurfaceRef(
        dataset=gis_provenance.dataset_name(gis_provenance.PROJECT_GRID, label), label=label)


def _column(units: Sequence[Any]) -> Any:
    """La columna de ``units`` (``res_perf.UnitSpec``) con sus rejillas del proyecto."""
    return materials.MaterialColumn(tuple(
        materials.Unit(spec.code, spec.name, spec.kind, spec.role, spec.state, _ref(spec.base),
                       _ref(spec.thickness),
                       tuple(materials.Component(item.code, item.name, item.role)
                             for item in spec.components))
        for spec in units
    ))


def _key(unit: str, component: str | None, what: str) -> str:
    if what == "density":
        return params.density_key(unit, component)
    if what == "swell":
        return params.swell_key(unit, component)
    assert component is not None
    return params.percent_key(unit, component)


class _Built:
    """Un proyecto nuevo en ``parent/proyectos`` (los datos de usuario y las fuentes, en
    ``local``) con V01, las rejillas ``labels`` de §2.2 como rejillas del proyecto
    (``gis_dtm_``), la capa de los 20 dominios importada con el papel «dominios» y, al usarla,
    una columna con sus parámetros."""

    def __init__(self, stack: ExitStack, parent: Path, local: Path,
                 labels: Sequence[str]) -> None:
        self.clock = FakeClock()
        self.userdata = userdata_mod.UserData(local / "u")
        (parent / "proyectos").mkdir()
        settings = make_settings(window=data.WINDOW, grid_step_m=data.STEP)
        self.project = create.create_project(parent / "proyectos", settings, fx.SESSION,
                                             self.userdata, clock=self.clock).project
        stack.callback(self.project.close)
        self.root = Path(self.project.root)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            self.version, _revision = versions_store.create_version(
                conn, self.project, feature="rnf", title="Rendimiento", reason="Spec 011, T27")
        self.project.refresh_header()
        grid = _grid()
        x, y = grid.centers()
        found = data.surfaces(x, y, labels)
        del x, y
        self.clock.advance(minutes=1)
        fx.write_grids(self.project, [(label, gis.Raster(grid, found[label], fx.CRS, fx.VERTICAL))
                                      for label in labels], message="Rejillas de §2.2")
        self.start, self.final = found[data.START], found[data.FINAL]
        del found
        sources = local / "fuentes"
        sources.mkdir()
        layer = sources / "dominios.gpkg"
        fx.write_layer(layer, DOMAINS_LAYER, data.FIELD,
                       [(n + 1, f"D{n + 1:02d}", [ring])
                        for n, ring in enumerate(data.domain_rings())])
        self.clock.advance(minutes=1)
        record = fx.import_layer(self.project, self.userdata, layer, DOMAINS_LAYER, DOMAINS_NAME,
                                 role="domains")
        self.domains = store.load_domain_layer(self.project, record.name, data.FIELD)
        self.column: Any = None
        self.declared: set[str] = set()

    def use_column(self, units: Sequence[Any]) -> Any:
        """Guarda la columna de ``units`` (``res.edit_materials``) si no es la que hay y da de
        alta los parámetros que aún no están (HIPÓTESIS, sintéticos)."""
        column = _column(units)
        if self.column == column:
            return column
        self.clock.advance(minutes=1)
        handle = operations.begin_operation(self.project, provenance.EDIT_MATERIALS,
                                            settings={"units": len(column.units)},
                                            executor="blender")
        store.save_materials(self.project, handle, column)
        values = {_key(unit, component, what): value
                  for unit, component, what, value in data.parameter_values(units)}
        missing = {key: value for key, value in values.items() if key not in self.declared}
        parameter_store = core_params.ParameterStore(self.project)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            for key, value in missing.items():
                parameter_store.create(conn, key, value, kind="HIPÓTESIS", **fx.PARAMS_BY_HAND,
                                       reason="Rendimiento de la 011 (T27)")
        self.declared.update(missing)
        self.column = column
        return column

    def benches(self) -> Any:
        """Las rodajas de RNF-011-02: la altura (anclada a la cota 0) con la que las cotas de lo
        que se mueve dan :data:`res_perf.BENCHES` rodajas."""
        both = np.isfinite(self.start) & np.isfinite(self.final) & (self.start != self.final)
        low = float(np.min(np.minimum(self.start, self.final)[both]))
        high = float(np.max(np.maximum(self.start, self.final)[both]))
        for tenths in range(100, 9, -1):
            found = slices_mod.Slices(tenths / 10, 0.0, None)
            if slices_mod.bounds(found, low, high).size - 1 == data.BENCHES:
                return found
        raise AssertionError(f"ninguna altura da {data.BENCHES} rodajas de {low} a {high}")

    # --- Los pasos, como la orden --------------------------------------------------------------

    def begin_volume(self, request: Any) -> Any:
        self.clock.advance(minutes=1)
        return operations.begin_operation(
            self.project, provenance.VOLUME, executor="blender", version=self.version.uid,
            settings=provenance.volume_settings(request), inputs=provenance.volume_inputs(request),
            params=provenance.volume_params(request))

    def begin_tonnage(self, name: str, column: Any) -> Any:
        self.clock.advance(minutes=1)
        return operations.begin_operation(
            self.project, provenance.TONNAGE, executor="blender", version=self.version.uid,
            settings=provenance.tonnage_settings(name), inputs=provenance.tonnage_inputs(name),
            params=provenance.tonnage_params(column))

    def query(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def figure(self, uid: str, key: str, **scope: Any) -> float:
        (row,) = self.query("SELECT value FROM gb_figure WHERE operation_uid = ? AND key = ? "
                            "AND scope = ?", uid, key, figures_mod.scope_json(scope))
        return float(row[0])

    def leftovers(self) -> list[str]:
        """Los temporales que quedan en el proyecto (``*.tmp*``)."""
        return sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*")
                      if ".tmp" in path.name)


class _Chain:
    """``res.volume`` y, encadenada, ``res.tonnage`` de una cubicación por unidades (D-16), como
    la orden: los pasos de las dos seguidos; las operaciones y lo guardado, en sus atributos."""

    def __init__(self, built: _Built, request: Any) -> None:
        self.built = built
        self.request = request
        self.volume_handle: Any = None
        self.tonnage_handle: Any = None
        self.volume: Any = None
        self.tonnage: Any = None

    def steps(self) -> Iterator[Any]:
        built, request = self.built, self.request
        self.volume_handle = built.begin_volume(request)
        with closing(store.volume_run(built.project, self.volume_handle, request)) as steps:
            for step in steps:
                if step.result is not None:
                    self.volume = step.result
                yield step
        self.tonnage_handle = built.begin_tonnage(request.name, request.column)
        with closing(store.tonnage_run(built.project, self.tonnage_handle)) as steps:
            for step in steps:
                if step.result is not None:
                    self.tonnage = step.result
                yield step


def _with_timer(driven: Any) -> float:
    """El total de ``driven`` con las esperas del temporizador del modal (como mucho): cada evento
    avanza pasos hasta pasar de :data:`MODAL_EVENT_S` y espera, como mucho,
    :data:`TIMER_INTERVAL_S` al siguiente. La primera llamada (crear los pasos) es la de
    ``execute``."""
    events, spent = 0, None
    for call in driven.calls[1:]:
        if spent is None:
            events += 1
            spent = 0.0
        spent += call
        if spent >= MODAL_EVENT_S:
            spent = None
    return driven.total_s + events * TIMER_INTERVAL_S


def _phase_text(driven: Any) -> str:
    return (f"{driven.steps} pasos, la llamada más larga {number(driven.longest_s * 1000, 0)} ms "
            f"(«{driven.longest_phase}»)")


def _between(test: unittest.TestCase, built: _Built, where: str, budget: float,
             prefix: str) -> None:
    """RNF-011-01: :data:`RUNS` cubicaciones entre las dos superficies de ``built`` con la
    rejilla de diferencias, cada una con su nombre; la mediana con el modal contra ``budget``."""
    totals, timed, runs = [], [], []
    for n in range(RUNS):
        request = volumes.VolumeRequest(f"{prefix} {n + 1}", START, FINAL, difference_grid=True)
        gc.collect()
        handles: list[Any] = []

        def start(request: Any = request, handles: list[Any] = handles) -> Iterator[Any]:
            handles.append(built.begin_volume(request))
            return store.volume_run(built.project, handles[0], request)

        driven = vperf.drive(start)
        totals.append(driven.total_s)
        timed.append(_with_timer(driven))
        runs.append((driven, handles[0]))
    driven, handle = runs[-1]
    stored = driven.result
    test.assertIsInstance(stored, store.StoredVolume)
    expected = gis.volume_between(gis.Raster(_grid(), built.start, fx.CRS, fx.VERTICAL),
                                  gis.Raster(_grid(), built.final, fx.CRS, fx.VERTICAL))
    name = stored.result.name
    for key, value in (("res.cut_m3", expected.cut_m3), ("res.fill_m3", expected.fill_m3),
                       ("res.area_m2", expected.area_m2),
                       ("res.nodata_area_m2", expected.nodata_area_m2)):
        got = built.figure(handle.uid, key, cubication=name)
        test.assertLessEqual(abs(got - value), CLOSURE_TOLERANCE * abs(value), key)
    test.assertEqual({record.name[:8] for record in stored.records}, {"res_dif_", "res_vol_"})
    test.assertEqual(built.leftovers(), [])
    median = statistics.median(timed)
    worst = max(runs, key=lambda item: item[0].longest_s)[0]
    gis_perf.report(
        f"RNF-011-01: cubicar entre dos superficies de {count(data.COLS * data.ROWS)} celdas "
        f"{where} (desmonte {number(expected.cut_m3, 1)} m³, terraplén "
        f"{number(expected.fill_m3, 1)} m³, neto y áreas, sin repartos, con la rejilla de "
        f"diferencias; de begin_operation a las cifras registradas; {MACHINE}): con el modal, "
        f"mediana {number(median)} s de {RUNS} (mín. {number(min(timed))}, máx. "
        f"{number(max(timed))}; los pasos seguidos, {gis_perf.median_line(totals)}); "
        f"{_phase_text(worst)}; presupuesto {number(budget, 0)} s; "
        f"{vperf.free_space(built.root)}")
    test.assertLessEqual(median, budget)


def _breakdown(test: unittest.TestCase, built: _Built, where: str, budget: float,
               prefix: str) -> None:
    """RNF-011-02: :data:`RUNS` cubicaciones por las 8 unidades, los 20 dominios y las 30
    rodajas, con sus toneladas; el avance, y Esc a la mitad sin nada en el proyecto."""
    column = built.use_column(data.column_units(data.UNITS_BREAKDOWN))
    benches = built.benches()
    totals, timed, runs = [], [], []
    for n in range(RUNS):
        request = volumes.VolumeRequest(f"{prefix} {n + 1}", START, FINAL, domains=built.domains,
                                        slices=benches, column=column)
        chain = _Chain(built, request)
        gc.collect()
        driven = vperf.drive(chain.steps)
        totals.append(driven.total_s)
        timed.append(_with_timer(driven))
        runs.append((driven, chain))
    driven, chain = runs[-1]
    kernel = chain.volume.result.kernel
    test.assertIsInstance(chain.tonnage, store.StoredTonnage)
    test.assertEqual(kernel.domains, data.DOMAINS)
    test.assertEqual(kernel.units, data.UNITS_BREAKDOWN)
    test.assertEqual(kernel.bounds.size - 1, data.BENCHES)
    cut = float(kernel.cut_m3[0])
    for part, label in ((float(kernel.unit_volume_m3[0].sum()), "unidades"),
                        (float(kernel.slice_cut_m3[0].sum()), "rodajas"),
                        (float(kernel.cut_m3[1:].sum()), "dominios")):
        test.assertLessEqual(abs(part - cut), CLOSURE_TOLERANCE * cut, label)
    gap = max(item[0].gap_s for item in runs)
    worst = max(runs, key=lambda item: item[0].longest_s)[0]
    rows = (len(chain.volume.result.rows), len(chain.tonnage.outputs.rows))
    figures = len(chain.volume.result.figures) + len(chain.tonnage.outputs.figures)

    request = volumes.VolumeRequest(f"{prefix} cancelada", START, FINAL, domains=built.domains,
                                    slices=benches, column=column)
    cancelled = _Chain(built, request)
    gc.collect()
    stopped = vperf.drive(cancelled.steps, cancel_at=CANCEL_AT)
    effective = stopped.longest_s + stopped.cancelled_s
    (status,) = built.query("SELECT status FROM gb_operation WHERE uid = ?",
                            cancelled.volume_handle.uid)
    left = built.query("SELECT count(*) FROM gb_dataset WHERE name = ?",
                       provenance.dataset_name(provenance.VOLUMES, request.name))[0][0]
    figures_left = built.query("SELECT count(*) FROM gb_figure WHERE operation_uid = ?",
                               cancelled.volume_handle.uid)[0][0]
    test.assertEqual(status[0], "cancelled")
    test.assertIsNone(cancelled.tonnage_handle)
    test.assertEqual((left, figures_left), (0, 0))
    test.assertEqual(built.leftovers(), [])

    median = statistics.median(timed)
    gis_perf.report(
        f"RNF-011-02: repartir {count(data.COLS * data.ROWS)} celdas en "
        f"{data.UNITS_BREAKDOWN} unidades (una compuesta y dos antrópicas), {data.DOMAINS} "
        f"dominios y {data.BENCHES} rodajas de {number(benches.height_m, 1)} m {where} "
        f"(res.volume y res.tonnage encadenadas: {count(rows[0])} + {count(rows[1])} filas, "
        f"{count(figures)} cifras; {MACHINE}): con el modal, mediana {number(median, 2)} s de "
        f"{RUNS} (mín. {number(min(timed), 2)}, máx. {number(max(timed), 2)}; los pasos "
        f"seguidos, {gis_perf.median_line(totals)}); el mayor hueco del avance "
        f"{number(gap * 1000, 0)} ms; {_phase_text(worst)}; Esc con el avance al "
        f"{number(stopped.cancelled_at * 100, 0)} % («{stopped.called[-1]}», a los "
        f"{number(stopped.total_s, 2)} s): cerrar los pasos "
        f"{number(stopped.cancelled_s * 1000, 1)} ms (con la llamada más larga, "
        f"{number(effective * 1000, 0)} ms), operación "
        f"«{status[0]}» sin datos, cifras ni temporales; presupuestos {number(budget, 0)} s, "
        f"avance {number(PROGRESS_GAP_S, 0)} s y Esc {number(CANCEL_BUDGET_S, 0)} s; el "
        f"proyecto, {number(vperf.folder_size(built.root) / 1e6, 0)} MB; "
        f"{vperf.free_space(built.root)}")
    test.assertLessEqual(median, budget)
    test.assertLessEqual(gap, PROGRESS_GAP_S)
    test.assertLessEqual(effective, CANCEL_BUDGET_S)


# --- En disco local ----------------------------------------------------------------------------


class _Local:
    stack: ExitStack | None = None
    built: _Built | None = None


_LOCAL = _Local()


def setUpModule() -> None:
    """El proyecto de §2.2 en disco local (``%TEMP%``), para las pruebas en disco local."""
    stack = ExitStack()
    try:
        stack.enter_context(fx.content_readers())
        stack.enter_context(fx.layers_registered())
        stack.enter_context(fx.res_registered())
        folder = stack.enter_context(project_tmp("gb-011-perf-"))
        _LOCAL.built = _Built(stack, folder, folder, data.labels(data.UNITS_TABLE))
    except BaseException:
        stack.close()
        raise
    _LOCAL.stack = stack


def tearDownModule() -> None:
    if _LOCAL.stack is not None:
        _LOCAL.stack.close()
    _LOCAL.stack = _LOCAL.built = None


def _local() -> _Built:
    assert _LOCAL.built is not None
    return _LOCAL.built


class BetweenSurfacesTest(unittest.TestCase):
    """RNF-011-01 en disco local."""

    def test_between_two_surfaces(self) -> None:
        """RNF-011-01: cubicar entre dos superficies de 2,81 M celdas (desmonte, terraplén, neto
        y áreas, sin repartos; con la rejilla de diferencias), desde la orden hasta las cifras
        registradas, en ≤ 3 s en disco local (mediana de 5, con las esperas del modal); las
        cifras, las de ``gis.volume_between`` (RF-011-01) y nada temporal en el proyecto."""
        _between(self, _local(), "en disco local", BETWEEN_BUDGET_S, "Entre superficies")


class BreakdownTest(unittest.TestCase):
    """RNF-011-02 y RNF-011-03 en disco local."""

    def test_breakdown(self) -> None:
        """RNF-011-02: repartir las 2,81 M celdas en 8 unidades (una compuesta y dos
        antrópicas), 20 dominios y 30 rodajas con sus toneladas en ≤ 20 s en disco local
        (mediana de 5, con las esperas del modal), el avance cada ≤ 1 s y Esc a la mitad
        efectivo en ≤ 2 s sin dejar nada (RF-011-25); unidades, rodajas y dominios cierran con
        el desmonte."""
        _breakdown(self, _local(), "en disco local", BREAKDOWN_BUDGET_S, "Reparto")

    def test_breakdown_memory(self) -> None:
        """RNF-011-03: el pico de memoria adicional (``tracemalloc``, con la de numpy) del
        reparto de RNF-011-02 con sus toneladas ≤ 1,5 GB."""
        built = _local()
        column = built.use_column(data.column_units(data.UNITS_BREAKDOWN))
        request = volumes.VolumeRequest("Reparto con memoria", START, FINAL,
                                        domains=built.domains, slices=built.benches(),
                                        column=column)
        chain = _Chain(built, request)
        peak = gis_perf.peak_bytes(lambda: vperf.drive(chain.steps))
        self.assertIsInstance(chain.tonnage, store.StoredTonnage)
        gis_perf.report(
            f"RNF-011-03: pico de memoria adicional (tracemalloc, con la de numpy) del reparto de "
            f"RNF-011-02 con sus toneladas ({MACHINE}): {number(peak / 2**20, 0)} MiB "
            f"({number(peak / 1e9, 3)} GB), presupuesto {number(MEMORY_BUDGET_BYTES / 1e9, 1)} GB")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


class ExportTest(unittest.TestCase):
    """RNF-011-06 en disco local: la cubicación de la tabla de RNF-011-05, a CSV."""

    NAME = "Tabla de exportación"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        built = _local()
        column = built.use_column(data.column_units(data.UNITS_TABLE))
        request = volumes.VolumeRequest(cls.NAME, START, FINAL, domains=built.domains,
                                        slices=built.benches(), column=column)
        chain = _Chain(built, request)
        vperf.drive(chain.steps)
        assert isinstance(chain.tonnage, store.StoredTonnage)
        cls.rows = (len(chain.volume.result.rows), len(chain.tonnage.outputs.rows))

    def test_export_csv(self) -> None:
        """RNF-011-06: exportar a CSV (``cubication_export`` y ``write_csv``, en ``exports/``)
        la cubicación de 20 dominios × 30 rodajas × 10 unidades (6 000 volúmenes por dominio,
        rodaja y unidad) con sus toneladas en ≤ 1 s (mediana de 5)."""
        built = _local()
        version = built.version.code
        target = built.root / "exports" / "rendimiento.csv"
        written: list[Any] = []

        def run() -> Any:
            found = export.cubication_export(built.project, self.NAME, version=version)
            export.write_csv(found, target, project=built.project, read_only=NO_READ_ONLY,
                             overwrite=True)
            written.append(found)
            return found

        times, found = gis_perf.measure(run)
        combos = {(item.row.domain, item.row.bench_z0, item.row.unit) for item in found.rows
                  if item.row.quantity == "volume_m3" and item.row.unit is not None
                  and item.row.component is None and item.row.bench_z0 is not None
                  and item.row.domain not in (table.ALL_DOMAINS, table.OUTSIDE_DOMAINS)}
        lines = target.read_bytes()
        self.assertEqual(len(combos), data.DOMAINS * data.BENCHES * data.UNITS_TABLE)
        self.assertTrue(lines.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(lines.count(b"\r\n"), len(export.csv_rows(found)))
        self.assertEqual(built.leftovers(), [])
        gis_perf.report(
            f"RNF-011-06: exportar a CSV la cubicación de {data.DOMAINS} dominios × "
            f"{data.BENCHES} rodajas × {data.UNITS_TABLE} unidades ({count(len(combos))} "
            f"volúmenes por dominio, rodaja y unidad; {count(len(found.rows))} filas de valores: "
            f"{count(self.rows[0])} de volúmenes y {count(self.rows[1])} de toneladas; "
            f"{number(len(lines) / 1e6, 1)} MB; cubication_export y write_csv en exports/; "
            f"{MACHINE}): {gis_perf.median_line(times)}, presupuesto "
            f"{number(EXPORT_BUDGET_S, 0)} s; {vperf.free_space(built.root)}")
        self.assertLessEqual(statistics.median(times), EXPORT_BUDGET_S)


# --- En la red ---------------------------------------------------------------------------------


@requires(network.NET, network.NET_HINT)
class NetworkTest(unittest.TestCase):
    """RNF-011-01 y RNF-011-02 con el proyecto en la carpeta de pruebas de la red (una
    subcarpeta temporal propia, borrada al terminar) y los datos de usuario en disco local."""

    built: _Built

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        stack = ExitStack()  # lo registrado, el de setUpModule
        try:
            local = stack.enter_context(project_tmp("gb-011-perf-red-"))
            remote = stack.enter_context(network.net_tmp("gb-011-"))
            cls.built = _Built(stack, remote, local, data.labels(data.UNITS_BREAKDOWN))
        except BaseException:
            stack.close()
            raise
        cls.addClassCleanup(stack.close)

    def test_between_two_surfaces_on_the_network(self) -> None:
        """RNF-011-01 en ``Z:``: cubicar entre las dos superficies con el proyecto en la carpeta
        de pruebas de la red en ≤ 10 s (mediana de 5, con las esperas del modal)."""
        _between(self, self.built, "con el proyecto en la red", NET_BETWEEN_BUDGET_S,
                 "Entre superficies")

    def test_breakdown_on_the_network(self) -> None:
        """RNF-011-02 en ``Z:``: el reparto de 8 unidades, 20 dominios y 30 rodajas con sus
        toneladas con el proyecto en la red en ≤ 45 s (mediana de 5, con las esperas del
        modal), el avance cada ≤ 1 s y Esc a la mitad en ≤ 2 s sin dejar nada."""
        _breakdown(self, self.built, "con el proyecto en la red", NET_BREAKDOWN_BUDGET_S,
                   "Reparto")


if __name__ == "__main__":
    unittest.main()
