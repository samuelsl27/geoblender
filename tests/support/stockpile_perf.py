# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de rendimiento de los acopios, el contrafuerte y los cuerpos apoyados (spec 016, T37; plan 016 §7.1 y §7.3;
``tests/rendimiento/des/test_stockpiles_perf.py``): los de §2.2 del plan 013 (``design_perf``: la rejilla de 1.654 × 1.699
celdas de 1 m —2,81 M—, con su terreno y las máscaras de V01 al día) con lo que añaden la 014, la 015 y la 016. Solo
sintéticos: se generan al pedirlos, no se versionan y los borra quien los escribe; ningún dato de cliente. Los datos puros
(las 100 marcas, las 2.000 zonas candidatas, los 10.000 datos de espesor, los nueve acopios, las zonas de coronación, las
huellas de los cuerpos y las secciones) son los de ``stockpile_scale`` (que usa también ``perf_stockpiles.py`` dentro de
Blender); aquí se convierten a las clases de la copia del paquete (``import_geoblender``).

- **El proyecto de escala** (:func:`scale_project`): el de la 015 (``entity_perf.scale_project``) con lo que registra ``bl``
  para la 016 (las familias de parámetros de los cuatro tipos, los cinco tipos de operación con las funciones **reales** de
  recalcular y las cifras), el umbral de la 011 y los datos de abajo escritos en el proyecto.
- **Los datos** (:func:`_write`): el levantamiento de escala (el terreno de la 013 con las 100 marcas y las 2.000 zonas
  candidatas) como rejilla del proyecto; las capas de marcas (20 y 100); el levantamiento de **9 acopios de 38.000 m²**
  (RNF-016-07); las zonas de coronación (2 ha y 10 ha); las huellas de los cuerpos (1, 18, 20 y 100 ha); los 10.000 datos de
  espesor sueltos y las secciones (líneas 3D con el espesor en su Z, de 20 y 100 ha).
- **Las peticiones** (:func:`detect_request`, :func:`removal_request`, :func:`buttress_request`, :func:`body_request`) y llevarlas
  como la orden (:func:`calculate`: «Calcular» y «Crear»; :func:`cycle`: y descartarla).

Python de Blender (su numpy 2.3.4) y biblioteca estándar.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import design_perf as dperf
from tests.support import entity_perf as ep
from tests.support import stockpile_data as sdata
from tests.support import stockpile_scale as scale
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.res_fixtures import write_grids

gis = import_geoblender("gis")
core_params = import_geoblender("core.params")
contract = import_geoblender("core.provenance.contract")
datasets = import_geoblender("core.datasets")
builtin = import_geoblender("core.content.builtin")
operations = import_geoblender("core.provenance.operations")
wkb = import_geoblender("core.gpkg.wkb")
design_model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
design_store = import_geoblender("design.store")
entity_store = import_geoblender("design.entity_store")
provenance = import_geoblender("design.provenance")
res_params = import_geoblender("reserves.params")

__all__ = [
    "BODIES", "Calculated", "Calls", "MARKS_100_LAYER", "MARKS_20_LAYER", "MARKS_NINE_LAYER", "POINTS", "SCALE_CROWN",
    "SECTION_NAMES", "SURVEY", "SURVEY_NINE", "body_request", "buttress_request", "calculate", "crown_level", "cycle",
    "detect_request", "removal_request", "scale_project",
]

SURVEY = sdata.SURVEY_DATASET
"""El levantamiento de escala como rejilla del proyecto (``gis_dtm_levantamiento``): el terreno con las marcas y las zonas
candidatas."""
SURVEY_NINE_LABEL = "levantamiento_nueve"
SURVEY_NINE = f"gis_dtm_{SURVEY_NINE_LABEL}"
"""El levantamiento de **9 acopios de 38.000 m²** de huella (RNF-016-07): el terreno con nueve pirámides grandes."""
MARKS_20_LAYER = "gis_fea_marcas_escala_20"
MARKS_100_LAYER = "gis_fea_marcas_escala_100"
MARKS_NINE_LAYER = "gis_fea_marcas_escala_9"
SCALE_CROWN = "gis_fea_coronacion_escala"
"""La capa de las zonas de coronación de escala (campos ``nombre`` y ``cota``)."""
BODIES = "gis_fea_cuerpos_escala"
"""La capa de las huellas de los cuerpos."""
POINTS = "gis_fea_espesor_escala"
"""Los 10.000 datos de espesor sueltos (campo ``espesor``)."""
SECTION_NAMES = scale.SECTION_NAMES
MARKS = 20
"""Las marcas de RNF-016-01 (20 de las 100 de la escala)."""
LAYERS_TYPE = "gis.perf_stockpiles_layers"
"""El tipo de operación con que se escriben las capas de la prueba."""
USER = "Samuel (IMGA)"
GUARD_M = 10.0
"""El resguardo del contrafuerte (m): obligatorio porque protege por defecto (D-19)."""
TRANSITION_DEG = 30.0
"""El ángulo de transición de las retiradas (°): lo da la persona (D-2: sin valor por defecto)."""
MAX_DISTANCE_M = 250.0
"""La distancia máxima a los datos del cuerpo (m): lo da la persona (D-9: sin valor por defecto)."""
crown_level = scale.crown_level


# --- Las capas -------------------------------------------------------------------------------------------------------


def marks_layer(name: str, count: int) -> Any:
    """La capa de las primeras ``count`` marcas de escala (``nombre`` y ``material``: «mineral» y «estéril» alternos), un cuadrado de
    :data:`~stockpile_scale.MARK_HALF_M` m de semilado en el centro de cada acopio."""
    marks, _bumps = scale.scale_mounds()
    chosen = marks[:count]
    return sdata.FieldsLayer(
        name, "polygon", tuple(((scale.mark_ring(item),),) for item in chosen), tuple(item.name for item in chosen),
        {"material": tuple(scale.MATERIALS[index % 2] for index in range(len(chosen)))})


def nine_layer() -> Any:
    """La capa de las nueve marcas (a :data:`~stockpile_scale.NINE_MARGIN_M` m del pie)."""
    mounds = scale.nine_mounds()
    half = scale.NINE_FOOT_M + scale.NINE_MARGIN_M
    return sdata.FieldsLayer(
        MARKS_NINE_LAYER, "polygon", tuple(((scale.mark_ring(item, half),),) for item in mounds), tuple(item.name for item in mounds),
        {"material": tuple(scale.MATERIALS[index % 2] for index in range(len(mounds)))})


def crown_layer() -> Any:
    """La capa de las zonas de coronación de escala: ``nombre`` y ``cota`` (de relleno: la persona la copia al parámetro)."""
    return sdata.FieldsLayer(
        SCALE_CROWN, "polygon", tuple(((scale.rectangle_ring(box),),) for box, _up in scale.BUTTRESS_ZONES.values()),
        tuple(scale.BUTTRESS_ZONES), {"cota": tuple(0.0 for _ in scale.BUTTRESS_ZONES)})


def bodies_layer() -> Any:
    """La capa de las huellas de los cuerpos (:data:`~stockpile_scale.BODY_BOXES`)."""
    return sdata.FieldsLayer(BODIES, "polygon", tuple(((scale.rectangle_ring(box),),) for box in scale.BODY_BOXES.values()),
                             tuple(scale.BODY_BOXES), {})


def thickness_points_layer() -> Any:
    """Los 10.000 datos de espesor sueltos de ``scale_thickness`` en 100 ha, como una capa de puntos con su campo ``espesor`` (a lo
    sumo uno por celda de 1 m)."""
    data = scale.scale_thickness()
    return sdata.FieldsLayer(
        POINTS, "point", tuple(((point[None, :2].copy(),),) for point in data), tuple(f"D{index + 1:05d}" for index in range(len(data))),
        {"espesor": tuple(float(value) for value in data[:, 2])})


def write_sections(project: Any, clock: Any, name: str, lines: Sequence[np.ndarray]) -> None:
    """Escribe ``lines`` (``(n, 3)`` ABSOLUTAS) como la tabla de líneas de rotura ``name`` (``gis_brk_…``) del proyecto, como lo
    deja la importación de la 006: un ``LINESTRING`` con Z por línea, con su ``line_id``, ``hard`` y ``code``; **la única capa
    que guarda la Z de las líneas** (``docs/trampas.md`` §6)."""
    srs = int(project.record.crs_epsg)
    writer = contract.OperationDef(LAYERS_TYPE, "1.0", "gis", "Layers of the performance tests", False)
    create = ("CREATE TABLE \"{name}\" (fid INTEGER PRIMARY KEY NOT NULL, geom LINESTRING, line_id TEXT NOT NULL DEFAULT '', "
              "hard BOOLEAN NOT NULL, code TEXT NOT NULL DEFAULT '')")
    with registered(writer):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, LAYERS_TYPE, settings={"name": name}, executor="blender")
        with project.write_transaction() as conn:
            conn.execute(create.format(name=name))
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) "
                         "VALUES (?, 'features', ?, '', ?)", (name, name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) "
                         "VALUES (?, 'geom', 'LINESTRING', ?, 1, 0)", (name, srs))
            conn.executemany(
                f"INSERT INTO \"{name}\" (geom, line_id, hard, code) VALUES (?, ?, 0, '')",
                [(wkb.encode_geometry("LINESTRING", line, srs, True), f"S{number + 1}") for number, line in enumerate(lines)])
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features",
                crs_epsg=srs, input_uid=None, immutable=False),), message="Secciones de escala del cuerpo")


# --- El proyecto -------------------------------------------------------------------------------------------------------


def _write(data: dperf.DesignScale) -> None:
    """Escribe en el proyecto de escala los dos levantamientos y las capas de arriba."""
    grid = dperf.grid()
    write_grids(data.project, [
        (sdata.SURVEY_LABEL, gis.Raster(grid, scale.scale_survey(), sdata.CRS, sdata.VERTICAL)),
        (SURVEY_NINE_LABEL, gis.Raster(grid, scale.survey_nine(), sdata.CRS, sdata.VERTICAL))],
        message="Levantamientos de escala de los acopios")
    for layer in (marks_layer(MARKS_20_LAYER, MARKS), marks_layer(MARKS_100_LAYER, scale.SCALE_MARKS), nine_layer(),
                  crown_layer(), bodies_layer(), thickness_points_layer()):
        sdata.write_layer(data.project, data.clock, layer)
    for key, (box, spacing, lines) in scale.SECTION_SPECS.items():
        write_sections(data.project, data.clock, SECTION_NAMES[key], scale.section_lines(box, spacing, lines))
    data.clock.advance(minutes=1)


def _never(request: Any) -> Any:
    raise AssertionError("las pruebas de rendimiento de los acopios no reproducen")


def _recompute(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de los tipos de la 016: lleva sus pasos hasta el final."""
    handle, work = design_store.recompute_run(request)
    ep.finish(work)
    return handle


@contextmanager
def scale_project(*, folder: Path | None = None, userdata: Path | None = None) -> Iterator[dperf.DesignScale]:
    """El proyecto de escala de la 015 (``entity_perf.scale_project``: 2,81 M celdas de 1 m, V01 y V02, las máscaras de V01 al
    día, los diez perfiles de banco) con lo que registra ``bl`` para la 016 (las familias de los cuatro tipos y sus cinco tipos
    de operación con las funciones **reales** de recalcular), el umbral de la 011 y los datos de la escala (:func:`_write`).
    ``folder`` y ``userdata``: dónde se crea (el de la red); al salir lo quita todo."""
    with ExitStack() as stack:
        data = stack.enter_context(ep.scale_project(folder=folder, userdata=userdata))
        core_params.register_definitions(res_params.DEFINITIONS)
        stack.callback(core_params.unregister_definitions, "res")
        core_params.register_families(design_params.SUPPORTED_FAMILIES)
        stack.callback(core_params.unregister_families, "des")
        recompute = dict.fromkeys(provenance.SUPPORTED_TYPES, _recompute)
        reproduce = dict.fromkeys(provenance.SUPPORTED_TYPES, _never)
        stack.enter_context(registered(*provenance.supported_operation_defs(recompute, reproduce), *provenance.SUPPORTED_FIGURES))
        _write(data)
        yield data


# --- Las peticiones -----------------------------------------------------------------------------------------------------


def detect_request(name: str, layer: str = MARKS_20_LAYER, *, surface: str = SURVEY, candidates: bool = True, **changes: Any) -> Any:
    """La detección de las marcas de ``layer`` sobre ``surface``, con los valores por defecto de D-3 y, si ``candidates``, los
    candidatos sin marca."""
    fields = design_model.StockpileFields(layer=layer, name_field="nombre", material_field="material")
    return design_model.StockpileRequest(name, fields, surface, candidates=candidates, **changes)


def removal_request(name: str, key: str, *, start: str = SURVEY, detection: str = "STK-001", **changes: Any) -> Any:
    """Retirar el acopio ``key`` de la detección ``detection`` desde ``start`` con la transición de :data:`TRANSITION_DEG`."""
    return design_model.RemovalRequest(name=name, stockpile=f"{detection}#{key}", start=start, transition_deg=TRANSITION_DEG, **changes)


def buttress_request(name: str, zone: str, crown_m: float, *, start: str = dperf.START, profile: str = scale.PROFILE_CODE,
                     **changes: Any) -> Any:
    """El contrafuerte de la zona de coronación ``zone`` a la cota ``crown_m`` con el perfil ``profile``, desde ``start``."""
    return design_model.ButtressRequest(
        name=name, fields=design_model.ButtressFields(layer=SCALE_CROWN, crown_field="cota"), feature=zone, start=start,
        profile=profile, crown_m=crown_m, guard_m=GUARD_M, **changes)


def body_request(name: str, footprint: str, *, sense: str = "under_roof", data_layer: str = POINTS, field: str = "espesor",
                 data_from: str = "field", surface: str = dperf.START, **changes: Any) -> Any:
    """El cuerpo de la huella ``footprint`` con los datos de ``data_layer``: «bajo un techo» (``surface`` es su techo) o «sobre
    una base» (parte de ``surface``)."""
    start = changes.pop("start", surface if sense == "on_base" else None)
    return design_model.BodyRequest(
        name=name, layer=BODIES, feature=footprint, data_layer=data_layer, data_field=field, data_from=data_from, surface=surface,
        sense=sense, start=start, max_distance_m=MAX_DISTANCE_M, **changes)


# --- Llevar las órdenes -------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Calls:
    """Las llamadas del hilo de Blender de unos pasos del dominio (cada ``next`` del generador, con el presupuesto de la interfaz,
    0,05 s): cuántas fueron y la más larga, en pared y en CPU del proceso (``time.process_time``: no cuenta lo que gastan otros
    programas; su resolución en Windows es de unos 16 ms)."""

    count: int
    longest_s: float
    longest_cpu_s: float


def drain(work: Iterator[Any]) -> tuple[Any, Calls]:
    """Lleva unos pasos hasta el final: el último resultado que dieron y sus :class:`Calls`."""
    result, count, longest, longest_cpu = None, 0, 0.0, 0.0
    iterator = iter(work)
    while True:
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            step = next(iterator)
        except StopIteration:
            break
        longest = max(longest, time.perf_counter() - wall)
        longest_cpu = max(longest_cpu, time.process_time() - cpu)
        count += 1
        if step.result is not None:
            result = step.result
    return result, Calls(count, longest, longest_cpu)


@dataclass(frozen=True, slots=True)
class Calculated:
    """Una orden calculada y creada: lo que tardó cada parte (s), lo que creció la base del proyecto (bytes), lo que pesan los
    ficheros nuevos de ``rasters/`` (bytes), las llamadas de «Calcular», la ``Calculation`` (ya creada) y lo guardado
    (``Stored``)."""

    calculate_s: float
    create_s: float
    db_bytes: int
    raster_bytes: int
    calls: Calls
    calculation: Any
    stored: Any
    chain_s: float = 0.0

    @property
    def total_s(self) -> float:
        return self.calculate_s + self.create_s

    @property
    def disk_bytes(self) -> int:
        return self.db_bytes + self.raster_bytes


def rasters_bytes(project: Any) -> dict[str, int]:
    """Los ficheros de ``rasters/`` del proyecto con su tamaño."""
    folder = Path(project.root) / "rasters"
    return {path.name: path.stat().st_size for path in folder.iterdir() if path.is_file()} if folder.is_dir() else {}


def calculate(data: dperf.DesignScale, run: Any, request: Any, *, version: str | None = None, create: dict[str, Any] | None = None,
              confirm: dict[str, Any] | None = None, chain: bool = False, **options: Any) -> Calculated:
    """«Calcular» (``run``: ``steps.stockpile_run``, ``removal_run``, ``buttress_run``, ``body_run`` o ``platform_run``, con el
    presupuesto de la interfaz, 0,05 s) y «Crear» ``request`` en la versión (V01 por defecto) como lo hace la orden: lo que tardó
    cada parte, las llamadas de «Calcular» y lo que dejó en disco. Con ``chain``, además lo que la orden encadena
    (``entity_store.after_entity_change``: la declaración, las máscaras y la capa de entidades), medido aparte (``chain_s``) y
    **sin contar** en ``disk_bytes``."""
    before_db = ep.database_bytes(data.project)
    before_files = rasters_bytes(data.project)
    began = time.perf_counter()
    calculation, calls = drain(run(data.project, request, version=version or data.v1.uid, budget_s=0.05, **options))
    calculated = time.perf_counter()
    with calculation:
        if confirm:
            calculation.confirm_removal(**confirm)
        stored = calculation.create(decided_by=USER, **(create or {}))
    created = time.perf_counter()
    after = rasters_bytes(data.project)
    new = sum(size for name, size in after.items() if before_files.get(name) != size)
    db = ep.database_bytes(data.project) - before_db
    chain_s = 0.0
    if chain:
        began_chain = time.perf_counter()
        ep.finish(entity_store.after_entity_change(data.project, data.v1.uid))
        chain_s = time.perf_counter() - began_chain
    return Calculated(calculated - began, created - calculated, db, new, calls, calculation, stored, chain_s)


def cycle(data: dperf.DesignScale, run: Any, request: Any, *, chain: bool = True, **options: Any) -> Calculated:
    """:func:`calculate` y, si la entidad parte de una superficie (de cada superficie parte una sola), **descartarla** con lo que
    la orden encadena, para repetir la medida con otro nombre: lo que pasa de descartar no cuenta."""
    data.clock.advance(minutes=1)
    made = calculate(data, run, request, chain=chain, **options)
    data.clock.advance(minutes=1)
    if getattr(request, "start", None) is not None:
        ep.finish(entity_store.discard_entity_steps(data.project, data.v1.uid, made.calculation.entity.code,
                                                    reason="Medición de rendimiento"))
    return made
