# SPDX-License-Identifier: GPL-3.0-or-later
"""Los acopios, el contrafuerte y los cuerpos apoyados dentro de Blender (spec 016, T37; RNF-016-03 y RNF-016-05; plan 016 §7.3 y el
riesgo R4 de la 012, ``tests/rendimiento/blender``), con la forma de ``perf_entities.py`` de la 015, cuyas piezas usa: el proyecto de
escala de las entidades, el registro de cada llamada del hilo de Blender y los eventos del modal.

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py -- --carpeta
tests/rendimiento/blender --patron "perf_stockpiles.py"``). Cada prueba imprime su cifra en una línea «RNF-016-nn: …» con el equipo y
el espacio libre del disco, y la compara con su presupuesto, sin relajarlo.

**Datos** (los puros de ``tests/support/stockpile_scale.py``, que no versionan ninguno; en Blender nunca se importa una ayuda que
cargue ``import_geoblender``, ``docs/trampas.md`` §4): el proyecto de escala de ``perf_entities.py`` (EPSG:25830 + EPSG:5782, V01 y
V02, la rejilla de 1.654 × 1.699 celdas de 1 m —2,81 M—, el límite legal y el perímetro, los 20 sectores, los diez perfiles de banco
y las máscaras de V01 al día) con el levantamiento de escala (el terreno con las **100 marcas y las 2.000 zonas candidatas**) como
rejilla del proyecto, la capa de **20 marcas**, las zonas de coronación (2 y 10 ha), las huellas de los cuerpos, los **10.000 datos
de espesor** sueltos y las secciones (líneas 3D con el espesor en su Z). Todo con la extensión habilitada, como una persona.

- **RNF-016-03** (:class:`CallsTest`, en el orden de sus letras sobre el mismo estado): las órdenes de la 016, las reales, como desde
  la interfaz: Intro (``execute`` por ``bpy.ops``, en pasos), cada evento del temporizador de su modal hasta que termina (con el tic
  de los indicadores de la procedencia cuando le toca) y «Crear» (la misma orden con ``confirm``): **la detección** escribe sus tablas y
  sus cuatro rejillas dispersas **por pasos** (T44: ``Calculation.create_steps``; antes, una sola llamada de ≈ 1 s), con la transacción
  final como último paso, y en la retirada, el contrafuerte y el cuerpo encadena lo que sigue (``after_entity_change``: la
  declaración, las máscaras y la capa de entidades, ``_ChainsEntityLayer``), con sus pasos y sus eventos. Cada llamada del hilo de Blender se mide: lo que hace Geoblender en ella,
  **sin la transacción final** (``DesignWriter.commit`` y ``MaskWriter.commit``: una transacción que no se trocea; el R4 de la 012),
  ≤ 0,2 s; la transacción, medida aparte, se anota con la llamada en que ocurre (si pasa de 0,2 s, con un aviso: la cifra, para
  Samuel). (a) «Detectar acopios…» con las 20 marcas y los candidatos; (b) «Retirar un acopio…» el mayor y «como plataforma»;
  (c) «Contrafuerte…» de 10 ha; (d) «Cuerpo apoyado…» «sobre una base» de 100 ha con los 10.000 datos sueltos y con las secciones.
  **Cada llamada se mide en CPU del proceso** (``time.process_time()``, que no cuenta lo que gastan otros programas:
  ``docs/trampas.md`` §4) **y en pared**; el presupuesto se exige a la CPU y la pared se anota con un aviso si lo pasa (se repite
  con el equipo en reposo). La resolución del reloj de CPU de Windows es de unos 16 ms.
- **RNF-016-05** (:meth:`CallsTest.test_g_esc`): Esc a mitad de cada cálculo —«Calcular» de las cuatro órdenes (a mitad de sus eventos
  y, las que escriben un temporal, en cuanto tienen su superficie en él) y, de la detección, a mitad de «Crear» (T44)—: la llamada más larga del cálculo más lo que tarda Esc ≤ 2
  s y nada a medias en el proyecto (ni operación «en curso», ni temporal; «Calcular» no deja ni operación, ni dato, ni cifra, ni
  fichero). **A esta escala sí hay un «a mitad»**: la T35 no pudo probarlo en la cantera de 2 m, donde el cálculo cabe en un evento.
- **En la red**: lo de RNF-016-03 con el proyecto en ``Z:`` se mide a mano con ``GEOBLENDER_NET_TEST_DIR`` en las pruebas del
  dominio (``test_stockpiles_perf.py``); aquí no hay clase de red.

En ``blender -b`` no corren ni el bucle de eventos ni los temporizadores: la prueba hace de ventana (un evento del temporizador del
modal cada vez) y de temporizador (las colas de pasos); la confirmación de «Calcular» (``_ask_confirmation``, que relanza la orden con
un temporizador) se sustituye.
"""

from __future__ import annotations

import gc
import statistics
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.rendimiento.blender import perf_constraints as pc
from tests.rendimiento.blender import perf_design as pd
from tests.rendimiento.blender import perf_entities as pe
from tests.rendimiento.blender import perf_quarry as pq
from tests.support import blender_ext
from tests.support import design_data as ddata
from tests.support import stockpile_scale as scale
from tests.support.trees import remove_tree

CALL_BUDGET_S = 0.2  # RNF-016-03: lo que hace Geoblender en cada llamada del hilo de Blender
ESC_BUDGET_S = 2.0  # RNF-016-05: Esc a mitad de cualquier cálculo
RUNS = 3  # cada orden se mide 3 veces y el presupuesto se exige a la mediana de su peor llamada
DETECT = "geoblender.des_detect_stockpiles"
REMOVE = "geoblender.des_remove_stockpile"
BUTTRESS = "geoblender.des_add_buttress"
BODY = "geoblender.des_create_body"
SURVEY = "gis_dtm_levantamiento"
"""El levantamiento de escala como rejilla del proyecto (``gis_dtm_<nombre>``)."""
MARKS_LAYER = "gis_fea_marcas_escala_20"
CROWN_LAYER = "gis_fea_coronacion_escala"
BODIES_LAYER = "gis_fea_cuerpos_escala"
POINTS_LAYER = "gis_fea_espesor_escala"
SECTIONS_LAYER = scale.SECTION_NAMES["100"]
MARKS = 20
LAYERS_TYPE = "gis.perf_stockpiles_layers"
"""El tipo de operación con que se escriben las capas de la prueba (como la importación de la 006)."""
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")

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


# --- El proyecto de escala con las capas de la 016 ---------------------------------------------------


def write_survey(project: Any) -> str:
    """El levantamiento de escala como rejilla del proyecto (``gis.resample``, como las deja «Rejilla del proyecto desde un MDT»); el
    nombre de su dato."""
    gis_store = _module("gis.store")
    grid = _module("gis.grid").Grid(scale.SCALE_WEST, scale.SCALE_SOUTH + len(ddata.terrain()) * 1.0, 1.0, 1.0, ddata.COLS, ddata.ROWS)
    raster = _module("gis.raster").Raster
    crs, vertical = gis_store.project_references(project)
    library, library_version = _module("gis.crs").crs_library()
    handle = _module("core.provenance.operations").begin_operation(
        project, _module("gis.provenance").RESAMPLE, settings={"nombre": "Levantamiento de escala de los acopios"}, executor="blender")
    with gis_store.ResultWriter(project, handle) as out:
        out.raster("levantamiento", raster(grid, scale.scale_survey(), crs, vertical))
        records = out.commit(software={library: library_version}, message="Levantamiento de escala de los acopios")
    (found,) = records
    return str(found.name)


def write_features(project: Any, name: str, kind: str, entities: tuple[Any, ...], names: tuple[str, ...],
                   fields: dict[str, tuple[Any, ...]]) -> None:
    """La capa de entidades ``name`` (``kind``: ``polygon`` o ``point``) con ``nombre`` y los ``fields`` numéricos, como la deja la
    importación de la 006."""
    gis_store, vector = _module("gis.store"), _module("gis.vector")
    datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
    srs = int(project.record.crs_epsg)
    columns = (vector.FieldColumn("nombre", "nombre", "TEXT"), *(vector.FieldColumn(field, field, "DOUBLE") for field in fields))
    values = {"nombre": names, **fields}
    layer = vector.FeatureLayer(kind, tuple(range(1, len(names) + 1)), entities, columns, values)
    rows = gis_store.feature_rows(layer, srs)
    columns_sql = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
    marks = ", ".join("?" for _ in range(len(columns) + 2))
    handle = _module("core.provenance.operations").begin_operation(project, LAYERS_TYPE, settings={"name": name}, executor="blender")
    with project.write_transaction() as conn:
        conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, geom {layer.geometry_type}, {columns_sql})')
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES (?, 'features', ?, '', ?)",
                     (name, name, srs))
        conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) "
                     "VALUES (?, 'geom', ?, ?, 0, 0)", (name, layer.geometry_type, srs))
        conn.executemany(f'INSERT INTO "{name}" VALUES ({marks})', rows)
        handle.complete(conn, outputs=(datasets.DatasetSpec(
            name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs,
            input_uid=None, immutable=False),), message="Capa de rendimiento de los acopios")


def write_sections(project: Any, name: str, lines: list[np.ndarray]) -> None:
    """Las líneas 3D ``lines`` (``(n, 3)`` ABSOLUTAS) como la tabla de líneas de rotura ``name`` (``gis_brk_…``), la única capa que
    guarda la Z de las líneas (``docs/trampas.md`` §6)."""
    datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
    wkb = _module("core.gpkg.wkb")
    srs = int(project.record.crs_epsg)
    handle = _module("core.provenance.operations").begin_operation(project, LAYERS_TYPE, settings={"name": name}, executor="blender")
    create = ("CREATE TABLE \"{name}\" (fid INTEGER PRIMARY KEY NOT NULL, geom LINESTRING, line_id TEXT NOT NULL DEFAULT '', "
              "hard BOOLEAN NOT NULL, code TEXT NOT NULL DEFAULT '')")
    with project.write_transaction() as conn:
        conn.execute(create.format(name=name))
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES (?, 'features', ?, '', ?)",
                     (name, name, srs))
        conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) "
                     "VALUES (?, 'geom', 'LINESTRING', ?, 1, 0)", (name, srs))
        conn.executemany(f"INSERT INTO \"{name}\" (geom, line_id, hard, code) VALUES (?, ?, 0, '')",
                         [(wkb.encode_geometry("LINESTRING", line, srs, True), f"S{number_ + 1}") for number_, line in enumerate(lines)])
        handle.complete(conn, outputs=(datasets.DatasetSpec(
            name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs,
            input_uid=None, immutable=False),), message="Secciones de escala del cuerpo")


def write_data(project: Any) -> None:
    """El levantamiento y las capas de la 016 en el proyecto."""
    assert write_survey(project) == SURVEY
    marks, _bumps = scale.scale_mounds()
    chosen = marks[:MARKS]
    write_features(project, MARKS_LAYER, "polygon", tuple(((scale.mark_ring(item),),) for item in chosen),
                   tuple(item.name for item in chosen), {})
    write_features(project, CROWN_LAYER, "polygon", tuple(((scale.rectangle_ring(box),),) for box, _up in scale.BUTTRESS_ZONES.values()),
                   tuple(scale.BUTTRESS_ZONES), {"cota": tuple(0.0 for _ in scale.BUTTRESS_ZONES)})
    write_features(project, BODIES_LAYER, "polygon", tuple(((scale.rectangle_ring(box),),) for box in scale.BODY_BOXES.values()),
                   tuple(scale.BODY_BOXES), {})
    data = scale.scale_thickness()
    write_features(project, POINTS_LAYER, "point", tuple(((point[None, :2].copy(),),) for point in data),
                   tuple(f"D{index + 1:05d}" for index in range(len(data))), {"espesor": tuple(float(value) for value in data[:, 2])})
    box, spacing, lines = scale.SECTION_SPECS["100"]
    write_sections(project, SECTIONS_LAYER, scale.section_lines(box, spacing, lines))


def refresh(project: Any) -> None:
    """Las listas de los diálogos (también las de los acopios, el contrafuerte y los cuerpos), leídas de nuevo (un guion no abre el
    diálogo que las lee)."""
    pe.refresh(project)
    panels = _module("bl.ui.des_panels")
    for refresh_choices in (panels.refresh_removal_choices, panels.refresh_buttress_choices, panels.refresh_body_choices):
        refresh_choices(project)


def build(parent: Path) -> pd.Built:
    """El proyecto de escala de las entidades (:func:`perf_entities.build`) con los datos de la 016, abierto en la sesión con V01
    activa y sus máscaras al día."""
    built = pe.build(parent)
    project = _module("bl.scene.project_session").current()
    write_data(project)
    refresh(project)
    return built


class _Local:
    """El proyecto de escala en disco local, uno para todo el módulo (se construye la primera vez que se pide), en la sesión."""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.made: pd.Built | None = None

    def built(self) -> pd.Built:
        """El proyecto, abierto en la sesión (construido, si aún no lo está)."""
        if self.made is None:
            self.folder = Path(tempfile.mkdtemp(prefix="gb-016-t37-"))
            self.made = build(self.folder / "proyectos")
        elif _module("bl.scene.project_session").current() is None:
            pd.base.reopen(self.made)
            refresh(_module("bl.scene.project_session").current())
        return self.made

    def close(self) -> None:
        if self.folder is not None:
            remove_tree(self.folder)
        self.folder = self.made = None


_LOCAL = _Local()


def setUpModule() -> None:  # noqa: N802
    blender_ext.release()
    blender_ext.load_file()
    blender_ext.enable()
    i18n = _module("core.i18n")
    unittest.addModuleCleanup(i18n.set_language, i18n.language())
    i18n.set_language("es")
    contract = _module("core.provenance.contract")
    for op_type in (LAYERS_TYPE, pe.LAYERS_TYPE):  # el de las capas de esta prueba y el de la de plataformas de ``perf_entities.build``
        contract.register_operation(contract.OperationDef(op_type, "1.0", "gis", "Layers of the performance tests", False))


def tearDownModule() -> None:  # noqa: N802
    try:
        _module("bl.draw.entity").disable()
        _module("bl.draw.design").disable()
        _module("bl.scene.project_session").close()
        _LOCAL.close()
        for op_type in (LAYERS_TYPE, pe.LAYERS_TYPE):
            _module("core.provenance.contract").unregister_operation(op_type)
    finally:
        blender_ext.load_file()
        blender_ext.release()


# --- Lo que se pide en cada diálogo ----------------------------------------------------------------------


def detect_form(name: str, **changes: Any) -> dict[str, Any]:
    """«Detectar acopios…» con las 20 marcas sobre el levantamiento, con los candidatos sin marca y los valores por defecto de D-3."""
    return {"name": name, "surface": SURVEY, "layer": MARKS_LAYER, "name_field": "nombre", "candidates": True, **changes}


def removal_form(name: str, stockpile: str, **changes: Any) -> dict[str, Any]:
    """«Retirar un acopio…» el ``stockpile`` (``STK-001#Marca 004``) desde el levantamiento, con la transición a 30°."""
    return {"name": name, "stockpile": stockpile, "start": SURVEY, "transition_angle": "30", **changes}


def buttress_form(name: str, zone: str, start: str, **changes: Any) -> dict[str, Any]:
    """«Contrafuerte…» de la zona ``zone`` desde ``start``, a la cota de coronación de su ancla y con 10 m de resguardo."""
    return {"name": name, "layer": CROWN_LAYER, "feature": zone, "start": start, "profile": pd.profile_name(ddata.PROFILES[0]),
            "crown": f"{scale.crown_level(zone):g}", "guard": "10", **changes}


def body_form(name: str, footprint: str, start: str, **changes: Any) -> dict[str, Any]:
    """«Cuerpo apoyado…» «sobre una base» de la huella ``footprint`` desde ``start``, con los 10.000 datos sueltos."""
    return {"name": name, "layer": BODIES_LAYER, "feature": footprint, "data_layer": POINTS_LAYER, "data_from": "FIELD",
            "data_field": "espesor", "sense": "ON_BASE", "surface": start, "start": start, "max_distance": "250", **changes}


# --- Las órdenes, como desde la interfaz -----------------------------------------------------------------


def open_dialog(idname: str) -> Callable[[Any], None]:
    """Lo que lee el ``invoke`` de la orden ``idname`` al abrir su diálogo (las listas de superficies, capas y entidades; no las de las
    demás órdenes): lo que mide la llamada «abrir el diálogo»."""
    panels = _module("bl.ui.des_panels")

    def opened(project: Any) -> None:
        if idname == BUTTRESS:
            panels.fill_profiles(project)
        panels.refresh_choices(project)
        if idname != DETECT:
            panels.refresh_platform_choices(project)
        for order, refresh_list in ((REMOVE, panels.refresh_removal_choices), (BUTTRESS, panels.refresh_buttress_choices),
                                    (BODY, panels.refresh_body_choices)):
            if idname == order:
                refresh_list(project)

    return opened


def create(recorder: Recorder, idname: str, what: str) -> None:
    """«Crear» (la misma orden con ``confirm``): empieza el modal de pasos —**la detección** (T44) escribe sus tablas y sus cuatro rejillas
    dispersas por pasos, con la transacción final como último; la retirada, el contrafuerte y el cuerpo, que ya escribían su superficie de
    una vez, solo encadenan lo que sigue (``after_entity_change``: la declaración, las máscaras y la capa de entidades)— y cada evento de
    su modal, hasta que termina, es una llamada del hilo de Blender medida."""
    commands = _module("bl.ui.commands")
    cls = commands.registered_class(idname)
    order = getattr(bpy.ops.geoblender, idname.removeprefix("geoblender."))
    result = recorder.call(f"Crear ({what})", order, "EXEC_DEFAULT", confirm=True, in_steps=True)
    if result != {"RUNNING_MODAL"}:
        raise AssertionError(f"«{what}» no se crea por pasos o no encadena lo que sigue: {result}")
    state = pd.pump(recorder, pc.running(cls), f"{what}: «Crear» y lo que sigue a crearla")
    if state != {"FINISHED"}:
        raise AssertionError(f"«{what}»: «Crear» y lo que sigue a crearla acaban mal: {state}")


def run_order(idname: str, form: dict[str, Any], what: str) -> pd.Run:
    """La orden ``idname`` como desde la interfaz: abrir el diálogo, «Calcular» (Intro y cada evento de su modal) y «Crear» con lo que
    encadena, cada llamada del hilo de Blender medida."""
    project = _module("bl.scene.project_session").current()
    opened = open_dialog(idname)

    def steps(recorder: Recorder) -> None:
        recorder.call(f"abrir el diálogo ({what})", opened, project)
        pq.calculate(recorder, idname, form, what)
        create(recorder, idname, what)

    return measure(what, steps)


def parts(run: pd.Run) -> tuple[tuple[pd.Call, ...], tuple[pd.Call, ...]]:
    """Las llamadas de ``run`` de «Calcular» (abrir el diálogo, Intro y los eventos de su modal hasta «Crear») y las de «Crear» y lo
    que encadena."""
    first = next(index for index, call in enumerate(run.calls) if call.what.startswith("Crear"))
    return run.calls[:first], run.calls[first:]


def calculation_events(run: pd.Run) -> int:
    """Los eventos del modal de «Calcular» (los anteriores a «Crear»)."""
    return sum(call.what.startswith("evento") for call in parts(run)[0])


def worst(calls: tuple[pd.Call, ...]) -> pd.Call:
    """La llamada de ``calls`` que más se acerca al presupuesto en CPU (sin la transacción final)."""
    return max(calls, key=lambda call: call.budgeted_cpu)


# --- RNF-016-03 y RNF-016-05 ----------------------------------------------------------------------------


class Stopped(pe.Stopped):
    """Esc a mitad de un cálculo (véase :class:`perf_entities.Stopped`)."""


class CallsTest(pe._Case):  # noqa: SLF001
    """RNF-016-03 y RNF-016-05 con el proyecto de escala en disco local, en el orden de sus letras sobre el mismo estado: la detección
    de la a la usan la c (retirar) y la g (Esc); las entidades de las demás se descartan al medirlas (de cada superficie parte una
    sola). Cada orden se mide :data:`RUNS` veces y el presupuesto se exige a la **mediana** de la peor llamada de cada ejecución (como
    las demás pruebas de rendimiento: una llamada de ≈ 0,15 s de CPU varía unas decenas de ms con el equipo cargado por otros
    programas). Todo cumple: «Crear» la detección, que era el hueco de la T37 (una sola llamada de ≈ 1 s, fijada con ``assertRaises``),
    corre por pasos desde la T44 y su prueba (la b) es una afirmación normal."""

    built: pd.Built
    runs: dict[str, list[pd.Run]] = {}
    stockpile: str
    counter = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.built = _LOCAL.built()
        cls.core_ops = _module("bl.ops.core_provenance")

    @classmethod
    def fresh(cls, label: str) -> str:
        """Un nombre que no se ha usado: «``label`` n»."""
        cls.counter += 1
        return f"{label} {cls.counter}"

    def report_runs(self, text: str, runs: list[pd.Run], rnf: str = "RNF-016-03") -> None:
        """La línea de cifra de unas ejecuciones (la peor, con sus llamadas más largas) y el presupuesto: lo que hace Geoblender en cada
        llamada, sin la transacción final, en CPU."""
        found = max(runs, key=lambda run: worst(run.calls).budgeted_cpu)
        calculate, created = parts(found)
        each = [(worst(parts(run)[0]).budgeted_cpu, worst(parts(run)[1]).budgeted_cpu) for run in runs]
        report(f"{rnf}: {text} con {count(CELLS)} celdas de 1 m ({len(runs)} ejecuciones; la peor, {count(len(found.calls))} llamadas "
               f"del hilo de Blender, {count(found.events)} eventos del modal, {number(found.seconds, 1)} s; {MACHINE}); la peor llamada "
               f"de «Calcular» de cada ejecución: " + ", ".join(f"{ms(item[0])} ms" for item in each)
               + f" (mediana {ms(statistics.median(item[0] for item in each))} ms) y de «Crear» y lo que encadena: "
               + ", ".join(f"{ms(item[1])} ms" for item in each)
               + f" (mediana {ms(statistics.median(item[1] for item in each))} ms), de CPU; presupuesto "
               f"{number(CALL_BUDGET_S * 1000, 0)} ms; la peor ejecución, "
               f"{pd.calls_line(found, f'«{found.label}», con el proyecto en disco local', network_waits=False)}; "
               f"{free_space(self.built.root)}")
        del calculate, created
        for run in runs:
            over = [call for call in run.calls if call.budgeted > CALL_BUDGET_S]
            if over:
                report(f"Aviso {rnf} ({run.label}): {len(over)} llamadas de más de {number(CALL_BUDGET_S, 1)} s de pared sin la "
                       f"transacción final (con el equipo cargado por otros programas se repite en reposo; el presupuesto se exige a "
                       f"la CPU): " + "; ".join(f"{ms(call.budgeted)} ms de pared y {ms(call.budgeted_cpu)} de CPU ({call.text()})"
                                                for call in over))
            long = [(op, seconds - waited) for call in run.with_commits for op, seconds, _cpu, waited in call.commits
                    if seconds - waited > CALL_BUDGET_S]
            if long:
                report(f"Aviso {rnf} ({run.label}; R4 de la 012, la cifra para Samuel): la transacción final pasa de "
                       f"{number(CALL_BUDGET_S, 1)} s: " + "; ".join(f"{op} {ms(seconds)} ms" for op, seconds in long))

    def check_runs(self, runs: list[pd.Run], *, calculate: bool = True, create: bool = True) -> None:
        """La mediana de la peor llamada de cada ejecución, en «Calcular» y en «Crear» con lo que encadena, no pasa de 0,2 s de CPU
        sin la transacción final."""
        for index, wanted in ((0, calculate), (1, create)):
            if wanted:
                found = statistics.median(worst(parts(run)[index]).budgeted_cpu for run in runs)
                self.assertLessEqual(found, CALL_BUDGET_S, f"{runs[0].label}: {'Calcular' if index == 0 else 'Crear'}: "
                                     f"{worst(parts(runs[0])[index]).text()}")

    def repeat(self, idname: str, form: Callable[[str], dict[str, Any]], what: str, name: str, *, prefix: str | None) -> list[pd.Run]:
        """La orden ``idname`` :data:`RUNS` veces con un nombre nuevo cada una (``form``: lo pedido con ese nombre) y, si ``prefix`` (el
        de los códigos de lo que crea: ``RMV``, ``BTR``…), descartando cada entidad al terminar (de cada superficie parte una sola)."""
        runs = []
        for _turn in range(RUNS):
            runs.append(run_order(idname, form(self.fresh(name)), what))
            if prefix is not None:
                self.drop(self.last_code(prefix))
        return runs

    def drop(self, code: str) -> None:
        """Descarta la entidad ``code`` de V01 (de cada superficie parte una sola) con lo que encadena la orden, para repetir."""
        entity_store = _module("design.entity_store")
        for _step in entity_store.discard_entity_steps(self.project(), self.built.version_uid, code, reason="Medición de rendimiento"):
            pass

    def last_code(self, prefix: str) -> str:
        """El código de la última entidad de V01 con ese prefijo (``RMV``, ``BTR``, ``BDY``…)."""
        registry = _module("design.entities").registry(self.project(), self.built.version_uid)
        return [entry.record.code for entry in registry if entry.record.code.startswith(prefix)][-1]

    def test_a_detect(self) -> None:
        """RNF-016-03 (RF-016-25, RF-015-29): «Detectar acopios…» con 20 marcas y los candidatos sobre 2,81 M celdas, como desde la
        interfaz: en ninguna llamada de «Calcular» (abrir el diálogo, Intro, cada evento de su modal y el tic de los indicadores) lo
        que hace Geoblender pasa de 0,2 s de CPU; «Crear» (que ahora corre por pasos), en la prueba siguiente."""
        runs = self.repeat(DETECT, lambda name: detect_form(name), "Detectar acopios", "Acopios de escala", prefix=None)
        CallsTest.runs[DETECT] = runs
        found = self.rows("SELECT count(*) FROM gb_operation WHERE op_type LIKE 'des.stockpile_detect%' AND status = 'done'")[0][0]
        self.assertEqual(found, RUNS, "las detecciones no están hechas")
        removable = _module("design.supported_store").removable_stockpiles(self.project(), self.built.version_uid)
        self.assertGreater(len(removable), 10, "casi ninguna marca da un acopio: no mide nada")
        first = sorted({item.ref.split("#")[0] for item in removable})[0]
        CallsTest.stockpile = max((item for item in removable if item.ref.startswith(first + "#")), key=lambda item: item.volume_m3).ref
        self.report_runs(f"«Detectar acopios…» con {MARKS} marcas y los candidatos sin marca ({len(removable) // RUNS} acopios "
                         f"formados)", runs)
        self.check_runs(runs, create=False)

    def test_b_detect_creating_runs_by_steps(self) -> None:
        """RNF-016-03 (T44): «Crear» la detección (la orden con ``confirm``) corre **por pasos** (``Calculation.create_steps``): cada
        evento de su modal escribe un trozo de las tablas y de las cuatro rejillas dispersas de 2,81 M celdas (la base, el espesor, el
        terreno sin acopios y la superficie), y la transacción final es el último paso: ninguna llamada pasa de 0,2 s de CPU sin la
        transacción final (antes de la T44 era **una sola llamada de ≈ 1 s**: la orden no usaba ``create_detection_steps``). La transacción,
        aparte (R4 de la 012)."""
        runs = CallsTest.runs[DETECT]
        found = [worst(parts(run)[1]) for run in runs]
        events = [sum(call.what.startswith("evento") for call in parts(run)[1]) for run in runs]
        commits = [seconds - waited for run in runs for call in run.with_commits for _op, seconds, _cpu, waited in call.commits]
        report(f"RNF-016-03: «Crear» la detección con {MARKS} marcas ({count(CELLS)} celdas de 1 m; {MACHINE}) por pasos: {events[0]} "
               f"eventos de su modal; la peor llamada de cada ejecución, "
               + ", ".join(f"{ms(call.budgeted_cpu)} ms" for call in found) + f" de CPU sin la transacción final ({len(runs)} ejecuciones; "
               f"mediana {ms(statistics.median(call.budgeted_cpu for call in found))} ms; presupuesto "
               f"{number(CALL_BUDGET_S * 1000, 0)} ms; la más larga, {found[0].text()}); la transacción final, aparte: "
               + ", ".join(f"{ms(seconds)} ms" for seconds in commits) + " de pared")
        self.assertGreater(min(events), 10, "«Crear» no corre por pasos")
        self.check_runs(runs, calculate=False)

    def test_c_removal(self) -> None:
        """RNF-016-03 (RF-016-11 a 16, RF-016-24): «Retirar un acopio…» el mayor de la detección —con la transición a 30°, lo que se
        le apoyaba y la pared— y, el mismo, «como plataforma» (una sola operación con el borde de la 015), «Calcular» y «Crear» con
        lo que encadena: en ninguna llamada sin la transacción final pasa de 0,2 s de CPU."""
        platform = {"as_platform": True, "edge_angle": "35", "reach": "40"}
        cases = (("Retirar un acopio", "Retirada de escala", {}, "RMV"),
                 ("Retirar un acopio como plataforma", "Retirada de escala como plataforma", platform, "PLT"))
        made = []
        for what, name, changes, prefix in cases:
            runs = self.repeat(REMOVE, lambda label, changes=changes: removal_form(label, self.stockpile, **changes), what, name,
                               prefix=prefix)
            CallsTest.runs[f"{REMOVE}:{what}"] = runs
            made.append(runs)
            self.report_runs(f"«{what}…» el mayor de los acopios ({self.stockpile})", runs)
        CallsTest.runs[REMOVE] = made[0]
        for runs in made:
            self.check_runs(runs)

    def test_d_buttress(self) -> None:
        """RNF-016-03 (RF-016-17, RF-016-18): «Contrafuerte…» de la zona de 10 ha a +20 m sobre el terreno, «Calcular» y «Crear» con lo
        que encadena (la declaración y las máscaras, porque protege): en ninguna llamada sin la transacción final pasa de 0,2 s de
        CPU."""
        runs = self.repeat(BUTTRESS, lambda name: buttress_form(name, "Zona de 10 ha", self.built.start), "Contrafuerte de 10 ha",
                           "Contrafuerte de escala", prefix="BTR")
        CallsTest.runs[BUTTRESS] = runs
        self.report_runs("«Contrafuerte…» de 10 ha a +20 m, con su declaración", runs)
        self.check_runs(runs)

    def test_e_body_with_sections(self) -> None:
        """RNF-016-03 (RF-016-20 a 22): «Cuerpo apoyado…» «sobre una base» de 100 ha con las secciones (7.500 datos en 10 líneas 3D
        diagonales: el peor caso del TIN), «Calcular» y «Crear» con lo que encadena: en ninguna llamada sin la transacción final pasa
        de 0,2 s de CPU."""
        what = "Cuerpo de 100 ha con secciones"
        runs = self.repeat(BODY, lambda name: body_form(name, "Cuerpo de 100 ha", self.built.start, data_layer=SECTIONS_LAYER,
                                                        data_from="Z", data_field="Z"), what, "Cuerpo con secciones", prefix="BDY")
        CallsTest.runs[f"{BODY}:{what}"] = runs
        self.report_runs(f"«Cuerpo apoyado…» «sobre una base» de {what}", runs)
        self.check_runs(runs)

    def test_f_body_with_loose_data(self) -> None:
        """RNF-016-03: «Cuerpo apoyado…» «sobre una base» de 100 ha con los 10.000 datos de espesor sueltos, «Calcular» y «Crear» con
        lo que encadena: en ninguna llamada sin la transacción final pasa de 0,2 s de CPU. **Va justo** (≈ 0,16 s de CPU, y una
        ejecución con el equipo cargado llegó a 0,25 s): la unidad de la preparación que lee los 10.000 puntos de la capa y los
        comprueba (``prepare``) es una sola llamada."""
        what = "Cuerpo de 100 ha con 10.000 datos sueltos"
        runs = self.repeat(BODY, lambda name: body_form(name, "Cuerpo de 100 ha", self.built.start), what, "Cuerpo de escala",
                           prefix="BDY")
        CallsTest.runs[f"{BODY}:{what}"] = runs
        CallsTest.runs[BODY] = runs
        self.report_runs(f"«Cuerpo apoyado…» «sobre una base» de {what}", runs)
        self.check_runs(runs)

    # --- Esc (RNF-016-05) ---------------------------------------------------------------------

    def esc_in_calculation(self, idname: str, form: dict[str, Any], *, after_events: int | None, until_tmp: bool, where: str) -> Stopped:
        """«Calcular» ``form`` hasta ``after_events`` eventos del modal (o, con ``until_tmp``, hasta que su superficie está en un
        temporal) y Esc: lo que tardó la llamada más larga hasta entonces y lo que tardó Esc; el cálculo no deja nada en el proyecto."""
        refresh(self.project())
        before = self.state()
        cls = _module("bl.ui.commands").registered_class(idname)
        order = getattr(bpy.ops.geoblender, idname.removeprefix("geoblender."))
        longest = (0.0, 0.0)
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            result, wall, cpu = pe._timed_call(order, "EXEC_DEFAULT", in_steps=True, **form)  # noqa: SLF001
            self.assertEqual(result, {"RUNNING_MODAL"}, f"{where}: no empieza")
            longest = max(longest, (wall, cpu), key=lambda call: call[1])
            operator = pc.running(cls)
            events = 0
            for events in range(1, pc.MAX_EVENTS):
                if after_events is not None and events > after_events:
                    break
                state, wall, cpu = pe._timed_call(operator.modal, bpy.context, pc.TIMER)  # noqa: SLF001
                self.assertEqual(state, {"RUNNING_MODAL"}, f"{where}: acabó antes de Esc (evento {events})")
                longest = max(longest, (wall, cpu), key=lambda call: call[1])
                if until_tmp and self.tmp_files():
                    break
            else:
                self.fail(f"{where}: no llega al momento de Esc")
            waiting = len(self.tmp_files())
            state, wall, cpu = pe._timed_call(operator.modal, bpy.context, ESCAPE)  # noqa: SLF001
        self.assertEqual(state, {"CANCELLED"}, where)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before, f"{where}: Esc dejó algo en el proyecto")
        return Stopped(where, events, longest, (wall, cpu), waiting)

    def esc_in_creation(self, idname: str, form: dict[str, Any], where: str) -> Stopped:
        """«Calcular» ``form`` hasta el final y «Crear» hasta la mitad de sus eventos (los de la primera ejecución de la ``test_a``, sin la
        transacción final), con ya ficheros temporales en el disco, y Esc (T44): lo que tardó la llamada más larga hasta entonces y lo
        que tardó Esc; el proyecto queda como estaba (sin operación, dato, cifra, fichero ni temporal) y el cálculo, descartado."""
        refresh(self.project())
        total = sum(call.what.startswith("evento") for call in parts(self.runs[idname][0])[1])
        before = self.state()
        cls = _module("bl.ui.commands").registered_class(idname)
        order = getattr(bpy.ops.geoblender, idname.removeprefix("geoblender."))
        measure(where, lambda recorder: pq.calculate(recorder, idname, form, where))  # deja el cálculo abierto
        self.assertEqual(self.state(), before, f"{where}: «Calcular» escribió algo")
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            result, wall, cpu = pe._timed_call(order, "EXEC_DEFAULT", confirm=True, in_steps=True)  # noqa: SLF001
            self.assertEqual(result, {"RUNNING_MODAL"}, f"{where}: «Crear» no empieza por pasos")
            longest = (wall, cpu)
            operator = pc.running(cls)
            events = 0
            for events in range(1, max(2, total // 2) + 1):
                state, wall, cpu = pe._timed_call(operator.modal, bpy.context, pc.TIMER)  # noqa: SLF001
                self.assertEqual(state, {"RUNNING_MODAL"}, f"{where}: acabó antes de Esc (evento {events})")
                longest = max(longest, (wall, cpu), key=lambda call: call[1])
            waiting = len(self.tmp_files())
            state, wall, cpu = pe._timed_call(operator.modal, bpy.context, ESCAPE)  # noqa: SLF001
        self.assertEqual(state, {"CANCELLED"}, where)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before, f"{where}: Esc dejó algo en el proyecto")
        return Stopped(f"{where}, a mitad de sus eventos ({events} de {total})", events, longest, (wall, cpu), waiting)

    def test_g_esc(self) -> None:
        """RNF-016-05 (RF-015-29): Esc a mitad de cada «Calcular» de las cuatro órdenes sobre 2,81 M celdas —a la mitad de sus
        eventos y, las que escriben un temporal (la retirada, el contrafuerte y el cuerpo), en cuanto su superficie ya está en él— y, de
        la detección, a mitad de «Crear» (T44: por pasos, con sus temporales ya escritos): la llamada más larga más lo que tarda Esc ≤ 2 s
        y nada a medias en el proyecto: ni operación, ni dato, ni cifra, ni fichero ni temporal."""
        cases: list[tuple[str, dict[str, Any], str, bool]] = [
            (DETECT, detect_form("Acopios de Esc"), "Detectar acopios", False),
            (REMOVE, removal_form("Retirada de Esc", self.stockpile), "Retirar un acopio", True),
            (BUTTRESS, buttress_form("Contrafuerte de Esc", "Zona de 10 ha", self.built.start), "Contrafuerte de 10 ha", True),
            (BODY, body_form("Cuerpo de Esc", "Cuerpo de 100 ha", self.built.start), "Cuerpo de 100 ha con 10.000 datos sueltos", True)]
        stops = []
        for idname, form, what, writes_tmp in cases:
            total = calculation_events(self.runs[idname][0])
            half = max(1, total // 2)
            stops.append(self.esc_in_calculation(idname, form, after_events=half, until_tmp=False,
                                                 where=f"«{what}», a mitad de sus eventos ({half} de {total})"))
            if writes_tmp:
                stops.append(self.esc_in_calculation(idname, form, after_events=None, until_tmp=True,
                                                     where=f"«{what}», con su superficie ya en el temporal"))
                self.assertGreater(stops[-1].temporaries, 0, f"«{what}» no llegó a escribir su temporal")
        stops.append(self.esc_in_creation(DETECT, detect_form("Acopios de Esc en Crear"), "Detectar acopios: «Crear»"))
        self.assertGreater(stops[-1].temporaries, 0, "«Crear» no llegó a escribir un temporal")
        worst_stop = max(stops, key=lambda stop: stop.wall)
        report(f"RNF-016-05: Esc a mitad de cada cálculo de la 016 sobre {count(CELLS)} celdas (la llamada más larga más lo que tarda "
               f"Esc; nada queda a medias en el proyecto; {MACHINE}): " + "; ".join(stop.text() for stop in stops)
               + f"; presupuesto {number(ESC_BUDGET_S, 0)} s; {free_space(self.built.root)}")
        self.assertLessEqual(worst_stop.wall, ESC_BUDGET_S, worst_stop.text())


if __name__ == "__main__":
    unittest.main()
