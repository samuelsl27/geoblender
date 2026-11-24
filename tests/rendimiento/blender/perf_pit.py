# SPDX-License-Identifier: GPL-3.0-or-later
"""La corta por bancos dentro de Blender (spec 018, T36b; RNF-018-06, 08, 09 y 11; plan 018 §7.3, ``tests/rendimiento/blender``), con la forma de ``perf_roads.py`` de la 017, cuyas piezas usa:
el proyecto de escala de las entidades, el registro de cada llamada del hilo de Blender y los eventos del modal.

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py -- --carpeta tests/rendimiento/blender --patron "perf_pit.py"``). Cada prueba imprime su cifra
en una línea «RNF-018-nn: …» con el equipo y el espacio libre del disco, y la compara con su presupuesto, sin relajarlo.

**Datos** (puros, sin cargar ``import_geoblender``, ``docs/trampas.md`` §4): el proyecto de escala de ``perf_entities.py`` (EPSG:25830 + EPSG:5782, V01 y V02, la rejilla de 1.654 × 1.699 celdas
de 1 m —2,81 M—, el límite legal y el perímetro, los 20 sectores y los diez perfiles de banco) con **un terreno llano** como rejilla del proyecto y **la capa de fondos** (el fondo rugoso de 2.000
vértices de RNF-018-01, el mismo que ``tests/support/pit_perf.py`` usa fuera de Blender), con la extensión habilitada, como una persona.

- **RNF-018-06** (:class:`CallsTest`): «Nueva corta…» ascendente de 40 bancos sobre 2,81 M celdas, la orden real: abrir el diálogo, Intro, cada evento del modal de «Calcular» y «Crear» con lo que
  encadena (la corta, su capa de entidades y las capas de la corta). Cada llamada del hilo de Blender se mide en CPU del proceso (``time.process_time()``) **sin la transacción final**
  (``DesignWriter.commit``: una transacción que no se trocea; el R4 de la 012), ≤ 0,2 s **en la peor de las** :data:`RUNS` **ejecuciones**, con un tic del reloj de CPU descontado y **con el margen
  del 25 % por la carga ajena que Samuel aceptó (23/11/2026): entre 0,2 y 0,25 s sale una línea «RNF-018-06: AVISO» y por encima de 0,25 s falla**. La transacción, aparte y con aviso si pasa de 0,2 s.
- **RNF-018-11** (:meth:`CallsTest.test_b_disk`): lo que guarda en el proyecto la corta que deja la última ejecución: los bytes de su superficie (la rejilla entera, comprimida) y de las tablas de
  polilíneas, y una revisión con **diez cortas** (las que hay más las que haga falta; mismas entradas, otro nombre), medida en el directorio del proyecto.
- **RNF-018-08** (:class:`PreviewTest`): la vista previa de una corta de **60 bancos de 2 polilíneas de 2.000 vértices**, activarla ≤ 1 s y cada redibujo ≤ 5 ms (con ``gpu`` y ``blf`` sustituidos:
  la GPU de verdad es de la comprobación manual).
- **RNF-018-09** (:class:`ViewsTest`): el TIN y el sólido de una corta de hasta 300.000 triángulos (el límite de aviso de la vista) con los cargadores reales, ≤ 10 s y ≤ 0,5 GB.

En ``blender -b`` no corren ni el bucle de eventos ni los temporizadores: la prueba hace de ventana (un evento del temporizador del modal cada vez) y de temporizador (las colas de pasos); la
confirmación de «Calcular» (``_ask_confirmation``) se sustituye.
"""

from __future__ import annotations

import gc
import math
import statistics
import time
import tracemalloc
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from tests.rendimiento.blender import perf_design as pd
from tests.rendimiento.blender import perf_entities as pe
from tests.rendimiento.blender import perf_quarry as pq
from tests.rendimiento.blender import perf_roads as pr
from tests.rendimiento.blender import perf_stockpiles as ps
from tests.support import road_scale as scale

CALL_BUDGET_S = 0.2  # RNF-018-06: lo que hace Geoblender en cada llamada del hilo de Blender
CALL_MARGIN = 1.25  # el margen del 25 % por la carga ajena (Samuel, 23/11/2026)
CLOCK_TICK_S = ps.CLOCK_TICK_S
ACTIVATE_BUDGET_S = 1.0  # RNF-018-08
REDRAW_BUDGET_S = 0.005  # RNF-018-08
VIEW_BUDGET_S = 10.0  # RNF-018-09
VIEW_MEMORY_BYTES = 500 * 1024**2  # RNF-018-09: 0,5 GB
SURFACE_BUDGET_BYTES = 25 * 1024**2  # RNF-018-11
POLYLINES_BUDGET_BYTES = 10 * 1024**2  # RNF-018-11
REVISION_BUDGET_BYTES = 512 * 1024**2  # RNF-018-11: 0,5 GiB
REVISION_PITS = 10
RUNS = 3  # cada orden se mide 3 veces y el presupuesto se exige al MÁXIMO de la peor llamada de cada ejecución
ACTIVATIONS = 5
REDRAWS = 120
TICK_WAIT_S = 0.005
REGION = (1920.0, 1080.0)
MIB = 1024**2

PIT = "geoblender.des_create_pit"
FLOORS_LAYER = "gis_fea_pit_escala_fondos"
FLAT = "gis_dtm_llano"
SOLID_TERRAIN = "gis_dtm_solido"
SOLID_LAYER = "gis_fea_pit_escala_fondo_solido"
TIN_LAYER = "gis_fea_pit_escala_fondo_tin"
SOLID_BENCHES = 11
SOLID_RADIUS_M = 20.0
TIN_VERTICES = 4_000
TIN_ARC = "0,0005"  # con el arco de 5 cm cada polilínea queda en ≈ 400 vértices; con 0,5 mm, la corta de 40 bancos llega a ≈ 125.000 vértices (≈ 250.000 triángulos)
FLOOR_Z_M = 125.0  # el ancla de los perfiles de la prueba (125 m)
BENCH_HEIGHT_M = 10.0
BENCHES = 40
FLOOR_VERTICES = 2_000
FLOOR_RADIUS_M = 150.0
FLOOR_NOISE_M = 0.15
SEED = 7
PROFILE = "perf_10_60_6"
"""El primero de los diez perfiles de banco de ``design_data.PROFILES`` (h 10 m, cara 60°, berma 6 m: avance de 11,77 m por banco)."""
CENTER = (scale.WEST + scale.COLS * scale.STEP_M / 2.0, scale.SOUTH + scale.ROWS * scale.STEP_M / 2.0)
"""El centro de la rejilla de escala (m, absolutas)."""
PIT_PLAN = "PIT-"
LAYERS_TYPE = pr.LAYERS_TYPE
USER = pr.USER

report = pd.report
number = pd.number
ms = pd.ms
count = pd.count
free_space = pd.free_space
MACHINE = pd.MACHINE
CELLS = pd.CELLS
Recorder = pq.Recorder
measure = pq.measure
_module = pe._module  # noqa: SLF001


def setUpModule() -> None:  # noqa: N802
    pe.setUpModule()
    contract = _module("core.provenance.contract")
    contract.register_operation(contract.OperationDef(LAYERS_TYPE, "1.0", "gis", "Layers of the performance tests", False))


def tearDownModule() -> None:  # noqa: N802
    try:
        _module("core.provenance.contract").unregister_operation(LAYERS_TYPE)
    finally:
        pe.tearDownModule()


# --- Los datos de escala (puros) --------------------------------------------------------------------------------


def rough_ring(seed: int, vertices: int, noise_m: float, radius_m: float, center: tuple[float, float]) -> np.ndarray:
    """Un anillo rugoso, antihorario, absoluto, ``(vertices, 2)``: un radio de ``radius_m`` con tres armónicos suaves y un ruido radial uniforme (el de ``pit_data.rough_ring``: una estrella)."""
    rng = np.random.default_rng(seed)
    angle = 2.0 * math.pi * np.arange(vertices) / vertices
    phase = rng.uniform(0.0, 2.0 * math.pi, 3)
    amplitude = 0.08 * radius_m * rng.uniform(0.3, 1.0, 3)
    wobble = sum(amplitude[j] * np.sin((j + 2) * angle + phase[j]) for j in range(3))
    radius = radius_m + wobble + rng.uniform(-noise_m, noise_m, vertices)
    return np.column_stack([center[0] + radius * np.cos(angle), center[1] + radius * np.sin(angle)])


def close(ring: np.ndarray) -> np.ndarray:
    """El anillo con su primer vértice repetido al final (como lo guarda una capa de polígonos)."""
    return np.vstack([ring, ring[:1]])


def write_terrain(project: Any, label: str, flat_m: float) -> str:
    """Un terreno llano a ``flat_m`` como rejilla del proyecto (``gis_dtm_<label>``); el nombre de su dato."""
    values = np.full((scale.ROWS, scale.COLS), flat_m, dtype=np.float64)
    return pr.write_grid(project, label, values, f"Terreno llano de escala de la corta ({label})")


def write_floor(project: Any, layer: str, radius_m: float, vertices: int) -> None:
    """La capa de fondos ``layer`` con un fondo rugoso de ``vertices`` vértices y ``radius_m`` m de radio (``nombre`` y ``cota_m``)."""
    ring = close(rough_ring(SEED, vertices, FLOOR_NOISE_M, radius_m, CENTER))
    with mock.patch.object(ps, "LAYERS_TYPE", LAYERS_TYPE):
        ps.write_features(project, layer, "polygon", (((ring,),),), ("Fondo de escala",), {"cota_m": (FLOOR_Z_M,)})


def write_data(project: Any) -> None:
    """Lo de RNF-018-06 y 11 (terreno llano a la cota que alcanza el banco 40 y fondo de 2.000 vértices) y lo de RNF-018-09: un fondo para el TIN de ≈ 300.000 triángulos (:data:`TIN_VERTICES`
    vértices por polilínea, sin simplificar) y un terreno y un fondo para el sólido de ≈ 300.000 triángulos (una corta de ≈ 150 m de radio)."""
    assert write_terrain(project, "llano", FLOOR_Z_M + BENCHES * BENCH_HEIGHT_M - 5.0) == FLAT
    write_floor(project, FLOORS_LAYER, FLOOR_RADIUS_M, FLOOR_VERTICES)
    assert write_terrain(project, "solido", FLOOR_Z_M + SOLID_BENCHES * BENCH_HEIGHT_M - 5.0) == SOLID_TERRAIN
    write_floor(project, SOLID_LAYER, SOLID_RADIUS_M, FLOOR_VERTICES)
    write_floor(project, TIN_LAYER, FLOOR_RADIUS_M, TIN_VERTICES)


def warm_up() -> None:
    """Importa los módulos de la corta (``design.pit_*``, ``design.steps``…) antes de medir: la copia de pruebas de la extensión no tiene ``.pyc`` y la primera llamada de la sesión pagaba ≈ 0,6 s de
    compilar y abrir 74 ficheros (medido: ``compile`` 0,34 s y ``open_code`` 0,33 s en la primera Intro). Es un coste de una vez por sesión de Blender, que con la extensión instalada
    (con ``.pyc``) no existe; el primer cálculo de una sesión no se mide con él."""
    root = Path(_module("design").__file__).parent
    for path in sorted(root.glob("pit_*.py")):
        _module(f"design.{path.stem}")
    for name in ("design.steps", "design.preview", "design.entity_store", "bl.ops.des_pit", "bl.scene.pit_views", "bl.draw.pit"):
        _module(name)


def refresh(project: Any) -> None:
    """Las listas de los diálogos (también las de la corta), leídas de nuevo (un guion no abre el diálogo que las lee)."""
    pe.refresh(project)
    _module("bl.ops.des_pit").refresh_pit_choices(project)


def pit_form(name: str, start: str = FLAT, **changes: Any) -> dict[str, Any]:
    """«Nueva corta…» ascendente desde la capa de fondos sobre ``start``, con el perfil de referencia y las tolerancias de la prueba tecleadas como las teclea una persona."""
    return {"name": name, "mode": "UP", "layer": FLOORS_LAYER, "name_field": "nombre", "level_field": "cota_m", "profile": PROFILE, "start": start, "arc_tol": "0,05",
            "simplify": "0,05", **changes}  # ``changes`` puede cambiar la capa, el terreno y la simplificación


# --- Las órdenes, como desde la interfaz ------------------------------------------------------------------------


def open_dialog(project: Any) -> None:
    """Lo que lee el ``invoke`` de «Nueva corta…» al abrir su diálogo (superficies, capas, perfiles, rosetas, rampas y entidades): lo que mide «abrir el diálogo»."""
    panels = _module("bl.ui.des_panels")
    panels.refresh_choices(project)
    panels.refresh_platform_choices(project)
    _module("bl.ops.des_pit").refresh_pit_choices(project)


def run_order(form: dict[str, Any], what: str) -> pd.Run:
    """«Nueva corta…» como desde la interfaz: abrir el diálogo, «Calcular» (Intro y cada evento de su modal) y «Crear» con lo que encadena, cada llamada del hilo de Blender medida."""
    project = _module("bl.scene.project_session").current()

    def steps(recorder: Recorder) -> None:
        recorder.call(f"abrir el diálogo ({what})", open_dialog, project)
        pq.calculate(recorder, PIT, form, what)
        ps.create(recorder, PIT, what)

    return measure(what, steps)


def check_budget(case: unittest.TestCase, runs: list[pd.Run]) -> None:
    """**El máximo** de la peor llamada de cada ejecución, en «Calcular» y en «Crear» con lo que encadena, sin la transacción final y con un tic del reloj descontado: ≤ 0,2 s de CPU; entre
    0,2 y 0,25 s sale un aviso (la carga ajena que Samuel aceptó, RNF-018-06) y por encima de 0,25 s falla."""
    for index, label in ((0, "Calcular"), (1, "Crear")):
        slowest = max((ps.worst(ps.parts(run)[index]) for run in runs), key=lambda call: call.budgeted_cpu)
        found = slowest.budgeted_cpu - CLOCK_TICK_S
        if found > CALL_BUDGET_S:
            report(f"RNF-018-06: AVISO, {runs[0].label}, {label}: la peor llamada de las {len(runs)} ejecuciones, {ms(found)} ms de CPU (un tic del reloj descontado), pasa de "
                   f"{ms(CALL_BUDGET_S)} ms y cabe en el margen del 25 % ({ms(CALL_BUDGET_S * CALL_MARGIN)} ms): {slowest.text()}")
        case.assertLessEqual(found, CALL_BUDGET_S * CALL_MARGIN, f"{runs[0].label}: {label}: la peor llamada de las {len(runs)} ejecuciones, {ms(found)} ms de CPU: {slowest.text()}")


# --- RNF-018-06 y RNF-018-11 -------------------------------------------------------------------------------------


class _PitCase(pe._Case):  # noqa: SLF001
    """El proyecto de escala en disco local con los datos de la corta (se escriben la primera vez), y lo común de las pruebas de este módulo."""

    built: pd.Built
    counter = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.built = pe._LOCAL.built()  # noqa: SLF001
        warm_up()
        project = _module("bl.scene.project_session").current()
        if not any(name == FLOORS_LAYER for (name,) in cls.rows_of(project, "SELECT name FROM gb_dataset")):
            write_data(project)
        refresh(project)

    @staticmethod
    def rows_of(project: Any, sql: str) -> list[tuple[Any, ...]]:
        with project.read() as conn:
            return conn.execute(sql).fetchall()

    @classmethod
    def fresh(cls, label: str) -> str:
        cls.counter += 1
        return f"{label} {cls.counter}"

    def last_code(self) -> str:
        """El código de la última corta de V01 (``PIT-nnn``)."""
        registry = _module("design.entities").registry(self.project(), self.built.version_uid)
        return [entry.record.code for entry in registry if entry.record.code.startswith(PIT_PLAN)][-1]

    def drop(self, code: str) -> None:
        """Descarta la corta ``code`` de V01 con lo que encadena la orden, para repetir."""
        entity_store = _module("design.entity_store")
        for _step in entity_store.discard_entity_steps(self.project(), self.built.version_uid, code, reason="Medición de rendimiento"):
            pass

    def sizes(self) -> dict[str, int]:
        """Los bytes de cada fichero del proyecto (el GeoPackage y las rejillas), por su ruta relativa."""
        root = Path(self.project().root)
        return {str(path.relative_to(root)): path.stat().st_size for path in root.rglob("*") if path.is_file()}


class CallsTest(_PitCase):
    """RNF-018-06 y RNF-018-11 con el proyecto de escala en disco local, en el orden de sus letras sobre el mismo estado."""

    def test_a_ascending_forty_benches(self) -> None:
        """RNF-018-06 (RF-018-34, RF-015-29): «Nueva corta…» ascendente de 40 bancos desde un fondo de 2.000 vértices sobre 2,81 M celdas, «Calcular» (Intro y cada evento de su modal) y «Crear»
        con lo que encadena: en ninguna llamada sin la transacción final pasa de 0,2 s de CPU (con el margen del 25 % y su aviso)."""
        runs = []
        for turn in range(RUNS):
            runs.append(run_order(pit_form(self.fresh("Corta de escala")), "Corta ascendente de 40 bancos"))
            if turn < RUNS - 1:
                self.drop(self.last_code())
        found = max(runs, key=lambda run: ps.worst(run.calls).budgeted_cpu)
        each = [(ps.worst(ps.parts(run)[0]).budgeted_cpu, ps.worst(ps.parts(run)[1]).budgeted_cpu) for run in runs]
        report(f"RNF-018-06: «Nueva corta…» ascendente de {BENCHES} bancos con {count(CELLS)} celdas de 1 m ({len(runs)} ejecuciones; la peor, {count(len(found.calls))} llamadas del hilo de Blender, "
               f"{count(found.events)} eventos del modal, {number(found.seconds, 1)} s; {MACHINE}); la peor llamada de «Calcular» de cada ejecución: " + ", ".join(f"{ms(item[0])} ms" for item in each)
               + f" (máximo {ms(max(item[0] for item in each))} ms) y de «Crear» y lo que encadena: " + ", ".join(f"{ms(item[1])} ms" for item in each)
               + f" (máximo {ms(max(item[1] for item in each))} ms), de CPU; se exige el máximo con un tic del reloj ({ms(CLOCK_TICK_S)} ms) descontado; presupuesto "
               f"{ms(CALL_BUDGET_S)} ms (margen del 25 %: {ms(CALL_BUDGET_S * CALL_MARGIN)} ms); la peor ejecución, {pd.calls_line(found, f'«{found.label}», con el proyecto en disco local', network_waits=False)}; "
               f"{free_space(self.built.root)}")
        for run in runs:
            long = [(op, seconds - waited) for call in run.with_commits for op, seconds, _cpu, waited in call.commits if seconds - waited > CALL_BUDGET_S]
            if long:
                report(f"Aviso RNF-018-06 ({run.label}; R4 de la 012, la cifra para Samuel): la transacción final pasa de {number(CALL_BUDGET_S, 1)} s: "
                       + "; ".join(f"{op} {ms(seconds)} ms" for op, seconds in long))
        check_budget(self, runs)

    def test_b_disk(self) -> None:
        """RNF-018-11 (RF-018-25): lo que guarda una corta de 40 bancos sobre 2,81 M celdas —su superficie (la rejilla entera, comprimida, ``des_psf_``), sus polilíneas y tablas (en el
        GeoPackage del proyecto)— y una revisión con **diez cortas**, medido en la carpeta del proyecto (los ficheros antes y después de crear cada una con la orden real; cada una se descarta al medirla y de cada superficie parte una sola corta, de modo que la suma es la de diez cortas con las mismas entradas): ≤ 25 MiB la superficie, ≤ 10 MiB
        lo que crece el GeoPackage (todas sus tablas y su capa, más de lo que pide la spec para las polilíneas) y ≤ 0,5 GiB las diez."""
        self.drop(self.last_code())  # de cada superficie parte una sola corta: se parte de la superficie sin corta y cada una se descarta al medirla
        before = self.sizes()
        per_pit = []
        for turn in range(REVISION_PITS):
            name = self.fresh("Corta de la revisión")
            was = self.sizes()
            run_order(pit_form(name), f"Corta {turn + 1} de {REVISION_PITS} de la revisión")
            now = self.sizes()
            surface = sum(size for path, size in now.items() if "des_psf_" in path and path not in was)
            tables = sum(size - was.get(path, 0) for path, size in now.items() if path.endswith(".gpkg"))
            per_pit.append((surface, tables))
            self.drop(self.last_code())
        after = self.sizes()
        total = sum(after.values()) - sum(before.values())
        surfaces, tables = [item[0] for item in per_pit], [item[1] for item in per_pit]
        report(f"RNF-018-11: lo que guarda cada corta de {BENCHES} bancos sobre {count(CELLS)} celdas ({MACHINE}), medido en los ficheros del proyecto: la superficie (``des_psf_``, GeoTIFF comprimido) "
               f"{number(max(surfaces) / MIB, 2)} MiB como máximo ({number(statistics.median(surfaces) / MIB, 2)} MiB de mediana; presupuesto {number(SURFACE_BUDGET_BYTES / MIB, 0)} MiB) y lo que crece el "
               f"GeoPackage (polilíneas, línea de cielo, cifras, hallazgos y capa de entidades) {number(max(tables) / MIB, 2)} MiB como máximo ({number(statistics.median(tables) / MIB, 2)} MiB de mediana; "
               f"presupuesto {number(POLYLINES_BUDGET_BYTES / MIB, 0)} MiB); la revisión con {REVISION_PITS} cortas (la suma de lo que crece el proyecto con cada una, sin borrar nada) crece {number(total / MIB, 1)} MiB; "
               f"presupuesto {number(REVISION_BUDGET_BYTES / MIB, 0)} MiB; {free_space(self.built.root)}")
        self.assertGreater(min(surfaces), 0, "la superficie de la corta no está en un fichero des_psf_")
        self.assertLessEqual(max(surfaces), SURFACE_BUDGET_BYTES)
        self.assertLessEqual(max(tables), POLYLINES_BUDGET_BYTES)
        self.assertLessEqual(total, REVISION_BUDGET_BYTES)


# --- RNF-018-08 -------------------------------------------------------------------------------------------------


class PreviewTest(unittest.TestCase):
    """RNF-018-08: la vista previa de una corta de 60 bancos de 2 polilíneas de 2.000 vértices (240.000 tramos), con la corta ya calculada (el cálculo lo mide RNF-018-06)."""

    BENCHES = 60
    VERTICES = 2_000

    @classmethod
    def setUpClass(cls) -> None:
        cls.entity = _module("bl.draw.entity")
        cls.pit = _module("bl.draw.pit")
        cls.constraints = _module("bl.draw.constraints")
        cls.dpreview = _module("design.preview")
        cls.model = _module("core.project.model")
        cls.access = _module("gis.masks.access")
        cls.design_draw = _module("bl.draw.design")

    def found(self) -> Any:
        """La vista previa de 60 bancos de pie y cresta (anillos concéntricos de 2.000 vértices con la cota de cada banco, en absolutas)."""
        angle = 2.0 * math.pi * np.arange(self.VERTICES) / self.VERTICES
        lines = []
        for number_ in range(self.BENCHES):
            for offset, kind in enumerate(("foot", "crest")):
                radius = 60.0 + 11.77 * number_ + 6.0 * offset
                ring = np.column_stack([CENTER[0] + radius * np.cos(angle), CENTER[1] + radius * np.sin(angle)])
                z = np.full(self.VERTICES, FLOOR_Z_M + BENCH_HEIGHT_M * (number_ + offset))
                lines.append(self.dpreview.PitLine(kind, number_ + 1, np.column_stack([ring, z]), True))
        return self.dpreview.PitPreview("Corta grande", "PIT-001", "V01", self.access.MaskState.CURRENT, mode="up", start_surface="terreno", cell_m=1.0, calculated=True, polylines=tuple(lines),
                                        bench_numbers=tuple(range(1, self.BENCHES + 1)))

    def activate(self, found: Any) -> tuple[float, Any]:
        """Activa la vista previa (``bl.draw.entity.build_steps`` hasta que termina, sumando los 5 ms de espera de cada paso del temporizador): su tiempo y lo construido."""

        def steps(*_args: Any, **_kwargs: Any) -> Any:
            return iter([self.model.Progress("preview_pit", 1, 1, "lista", result=found)])

        def no_ground(*_args: Any, **_kwargs: Any) -> Any:
            return None
            yield  # noqa: B901 - lo hace un generador

        origin = SimpleNamespace(x0=int(CENTER[0]) - 1000, y0=int(CENTER[1]) - 1000, z0=100)
        plan = self.entity.EntityPlan(pit=self.dpreview.PitAsk(request=object()))
        request = self.entity.Request(SimpleNamespace(origin=origin), "uid-v01", "V01", plan, "es", ("sello",))
        with mock.patch.object(self.dpreview, "pit_preview_steps", side_effect=steps), mock.patch.object(self.constraints, "ground_steps", side_effect=no_ground):
            gc.collect()
            started, ticks = time.perf_counter(), 0
            work = self.entity.build_steps(request)
            while True:
                try:
                    next(work)
                    ticks += 1
                except StopIteration as done:
                    built = done.value
                    break
        return time.perf_counter() - started + TICK_WAIT_S * ticks, built

    def test_a_sixty_benches(self) -> None:
        """RNF-018-08, RF-018-32: activar la vista previa de 60 bancos × 2 polilíneas × 2.000 vértices (240.000 tramos) ≤ 1 s (mediana de 5; la peor con un aviso) y cada redibujo (los nombres
        colocados sobre la pantalla y los lotes, con ``gpu`` y ``blf`` sustituidos: solo el Python de Geoblender; la GPU de verdad es de la comprobación manual) ≤ 5 ms (mediana y percentil 95)."""
        found = self.found()
        cold = self.activate(found)[0]
        walls, built = [], None
        for _ in range(ACTIVATIONS):
            wall, built = self.activate(found)
            walls.append(wall)
        wall = statistics.median(walls)
        segments = sum(batch.segments for batch in built.lines.batches)
        self.assertEqual(segments, self.BENCHES * 2 * self.VERTICES)
        report(f"RNF-018-08: activar la vista previa de una corta de {self.BENCHES} bancos de 2 polilíneas de {count(self.VERTICES)} vértices ({len(built.lines.batches)} lotes, {count(segments)} segmentos; "
               f"los pasos del temporizador con {number(TICK_WAIT_S * 1000, 0)} ms de espera cada uno; {MACHINE}): mediana de {ACTIVATIONS} {number(wall)} s (la peor {number(max(walls))} s; la primera, en frío, "
               f"{number(cold)} s) frente a {number(ACTIVATE_BUDGET_S, 1)} s")
        if max(walls) > ACTIVATE_BUDGET_S:
            report(f"Aviso RNF-018-08 (vista previa): la peor de {ACTIVATIONS} activaciones, {number(max(walls))} s, pasa de {number(ACTIVATE_BUDGET_S, 1)} s (se exige la mediana); se repite en reposo")
        self.assertLessEqual(wall, ACTIVATE_BUDGET_S)
        half = 900.0  # la vista cubre la corta: el centro de la corta (1.000 m al este y al norte del GeoOrigin de la prueba) en el centro de la región
        sx, sy = 1.0 / half, REGION[0] / (REGION[1] * half)
        matrix = np.array([[sx, 0.0, 0.0, -1000.0 * sx], [0.0, sy, 0.0, -1000.0 * sy], [0.0, 0.0, -0.001, 0.0], [0.0, 0.0, 0.0, 1.0]])
        from mathutils import Matrix

        gpu = mock.MagicMock()
        gpu.state.depth_test_get.return_value = "NONE"
        view = {"view_matrix": Matrix.Identity(4), "projection_matrix": Matrix.Identity(4), "perspective": True, "view_distance": 100.0, "viewport_size": REGION, "pixel_size": 1.0}
        items, redraws = [], []
        with mock.patch.object(self.constraints, "gpu", gpu), mock.patch.object(self.constraints, "batch_for_shader") as lots:
            for index in range(REDRAWS):
                started = time.perf_counter()  # el reloj de CPU de Windows mide de 16 ms en 16 ms: aquí, el de pared
                drawn = self.constraints.draw_lines(built.lines, **view)
                items = self.design_draw.screen_items(built, matrix, REGION, measure=lambda text: 8.0 * len(text), scale=1.0)
                if index >= 20:  # los primeros: los lotes de gpu se crean una vez
                    redraws.append(time.perf_counter() - started)
            self.assertEqual((drawn, lots.call_count), (len(built.lines.batches),) * 2)
        percentile = sorted(redraws)[int(0.95 * len(redraws))]
        report(f"RNF-018-08: cada redibujo de la vista previa de {self.BENCHES} bancos ({len(built.lines.batches)} lotes, {len(items)} elementos en pantalla; región de {number(REGION[0], 0)} × {number(REGION[1], 0)} px; {MACHINE}): "
               f"mediana {ms(statistics.median(redraws), 3)} ms, p95 {ms(percentile, 3)} ms, la peor {ms(max(redraws), 3)} ms; presupuesto {ms(REDRAW_BUDGET_S, 0)} ms por redibujo")
        self.assertGreaterEqual(len(items), 5, "el redibujo no coloca ningún elemento en pantalla: no mide nada")
        self.assertLessEqual(statistics.median(redraws), REDRAW_BUDGET_S)
        self.assertLessEqual(percentile, REDRAW_BUDGET_S)


# --- RNF-018-09 -------------------------------------------------------------------------------------------------


class ViewsTest(_PitCase):
    """RNF-018-09: el TIN y el sólido de cortas de hasta 300.000 triángulos (el límite de aviso de la vista), hechas con la orden real y cargadas con los cargadores reales de la vista (por pasos,
    como los lleva el temporizador)."""

    def make(self, name: str, **changes: Any) -> None:
        run_order(pit_form(name, **changes), name)

    def load(self, loader: Any, family: str, name: str) -> tuple[float, int, Any, float]:
        """Carga la vista de la familia ``family`` de la corta ``name`` por pasos: su tiempo (pared), su pico de memoria adicional (``tracemalloc``, con la de numpy), lo creado y el paso más largo."""
        project, registry, views, dprov = self.project(), _module("core.datasets.registry"), _module("bl.scene.views"), _module("design.provenance")
        dataset = dprov.dataset_name(family, name)
        with project.read() as conn:
            record = registry.get(conn, dataset, version_uid=self.built.version_uid)
        asked = views.ViewRequest(project, record, f"Vista {dataset}", 0)
        gc.collect()
        tracemalloc.start()
        try:
            started, longest, steps = time.perf_counter(), 0.0, loader(asked)
            while True:
                mark = time.perf_counter()
                try:
                    next(steps)
                except StopIteration as done:
                    parts = done.value
                    break
                longest = max(longest, time.perf_counter() - mark)
            wall = time.perf_counter() - started
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        return wall, peak, parts, longest

    def view(self, what: str, loader: Any, family: str, name: str, note: str) -> None:
        import bpy

        wall, peak, parts, longest = self.load(loader, family, name)
        triangles = sum(len(obj.data.polygons) for obj in parts.objects)
        for obj in parts.objects:
            mesh = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
        report(f"RNF-018-09: {what} de «{name}» con {count(triangles)} triángulos (por pasos, con el límite de aviso de {count(_module('bl.scene.pit_views').MAX_TRIANGLES)} triángulos; {note}; "
               f"{MACHINE}): {number(wall)} s (el paso más largo {ms(longest)} ms) frente a {number(VIEW_BUDGET_S, 0)} s; pico de memoria adicional (tracemalloc, con la de numpy) "
               f"{number(peak / MIB, 0)} MiB frente a {number(VIEW_MEMORY_BYTES / MIB, 0)} MiB")
        self.assertGreater(triangles, 100_000, "la corta es demasiado pequeña para medir el caso de hasta 300.000 triángulos")
        self.assertLessEqual(wall, VIEW_BUDGET_S)
        self.assertLessEqual(peak, VIEW_MEMORY_BYTES)

    def test_a_tin(self) -> None:
        """RNF-018-09: el TIN de una corta de 40 bancos con ≈ 125.000 vértices de polilíneas (≈ 250.000 triángulos) ≤ 10 s y ≤ 0,5 GB."""
        name = self.fresh("Corta del TIN")
        self.make(name, layer=TIN_LAYER, arc_tol=TIN_ARC, simplify="0,0000001")
        try:
            self.view("el TIN", _module("bl.scene.pit_views").load_pit_tin, _module("design.provenance").PIT_POLYLINES_TABLE, name,
                      f"{BENCHES} bancos con {count(TIN_VERTICES)} vértices por polilínea, sin simplificar")
        finally:
            self.drop(self.last_code())

    def test_b_solid(self) -> None:
        """RNF-018-09: el sólido de excavación de una corta de ≈ 150 m de radio (≈ 300.000 triángulos entre las dos superficies y las paredes) ≤ 10 s y ≤ 0,5 GB."""
        name = self.fresh("Corta del sólido")
        self.make(name, layer=SOLID_LAYER, start=SOLID_TERRAIN)
        try:
            self.view("el sólido", _module("bl.scene.pit_views").load_pit_solid, _module("design.provenance").PIT_BENCHES_TABLE, name, f"{SOLID_BENCHES} bancos, celdas de 1 m")
        finally:
            self.drop(self.last_code())


if __name__ == "__main__":
    unittest.main()
