# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de rendimiento de las entidades de diseño paramétricas (spec 015, T33; plan 015 §7.1 y
§7.3; ``tests/rendimiento/des/test_entities_perf.py``): los de §2.2 del plan 013 (``design_perf`` y
``quarry_perf``: la rejilla de 1.654 × 1.699 celdas de 1 m —2,81 M—, con su terreno y las máscaras de V01 al
día) con lo que añade la 015. Solo sintéticos: se generan al pedirlos, no se versionan y los borra quien los
escribe; ningún dato de cliente. Las geometrías y las cifras de las plataformas, en ``entity_data`` (datos
puros, que usa también ``perf_entities.py`` dentro de Blender).

- **El proyecto de escala** (:func:`scale_project`): el de la 014 (``quarry_perf.scale_project``) con lo que
  registra ``bl`` para la 015 (las familias de parámetros de la plataforma y los tres tipos de operación con las
  funciones **reales** de recalcular, también la de la compilación de las máscaras) y la capa de plataformas de
  escala (``entity_data.LAYER``).
- **Las peticiones** (:func:`big_request`, :func:`chain_request`) y llevarlas como la orden «Plataforma…»
  (:func:`calculate`: «Calcular» y «Crear»; :func:`create_chain`: con lo que sigue, ``after_entity_change``).
- **Las 200 entidades** (:func:`add_dependents`): sobre una entidad real, 199 que se apoyan en ella, cada una con
  su operación (sus parámetros y su cifra de lo apoyado) y los datos de juguete de su superficie y su huella
  (``des_psf_`` y ``des_epr_``, con una huella de tramos de fila), como la ``ScaleTest`` de T24 (RNF-015-02) y lo
  que lee la vista previa de T29 (RNF-015-06).

Python de Blender (su numpy 2.3.4) y biblioteca estándar.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.support import design_perf as dperf
from tests.support import entity_data as edata
from tests.support import entity_synthetic
from tests.support import quarry_fixtures as qfx
from tests.support import quarry_perf as qperf
from tests.support.entity_data import (
    BIG_NAME, BIG_REACH_M, CHAIN_GUARD_M, CHAIN_LENGTH, CHAIN_REACH_M, EDGE_ANGLE_DEG, LAYER,
    SYNTHETIC_ENTITIES, chain_name)
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

contract = import_geoblender("core.provenance.contract")
core_params = import_geoblender("core.params")
masks_provenance = import_geoblender("gis.masks.provenance")
masks_store = import_geoblender("gis.masks.store")
design_model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
design_store = import_geoblender("design.store")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
provenance = import_geoblender("design.provenance")
steps = import_geoblender("design.steps")

__all__ = [
    "BIG_NAME", "CHAIN_LENGTH", "LAYER", "SYNTHETIC_ENTITIES", "Calculated", "add_dependents",
    "big_request", "calculate", "chain_name", "chain_request", "create_chain", "database_bytes", "drain",
    "finish", "fresh_name", "scale_project",
]


def fields() -> Any:
    """Los campos de la capa de plataformas de escala."""
    return design_model.PlatformFields(layer=LAYER, start_level_field="cota_inicial",
                                       gradient_field="pendiente", width_field="ancho")


def big_request(name: str = BIG_NAME, *, start: str = dperf.START) -> Any:
    """La plataforma grande (``name``; la geometría de la capa es siempre la grande) sobre ``start``: «en corte y
    relleno», con la distancia euclídea exacta (la métrica por defecto del diálogo) y el alcance de
    ``entity_data.BIG_REACH_M``."""
    return design_model.PlatformRequest(
        name=name, fields=fields(), feature=BIG_NAME, start=start, edge_angle_deg=EDGE_ANGLE_DEG,
        reach_m=BIG_REACH_M, mode="cut_fill", metric="exact")


def chain_request(index: int) -> Any:
    """La plataforma ``index`` (0 a 19) de la cadena: «en corte», protegida, con el borde de
    ``entity_data.CHAIN_REACH_M``; la primera parte del terreno y cada una de la superficie de la anterior."""
    start = dperf.START if index == 0 else entities.surface_ref(f"PLT-{index:03d}")
    return design_model.PlatformRequest(
        name=chain_name(index), fields=fields(), feature=chain_name(index), start=start,
        edge_angle_deg=EDGE_ANGLE_DEG, reach_m=CHAIN_REACH_M, mode="cut", metric="exact",
        protect=True, guard_m=CHAIN_GUARD_M)


_NAMES: dict[str, int] = {}


def fresh_name(label: str) -> str:
    """Un nombre que no se ha usado: «``label`` n»."""
    _NAMES[label] = _NAMES.get(label, 0) + 1
    return f"{label} {_NAMES[label]}"


# --- Llevar los pasos -----------------------------------------------------------------------------


def finish(work: Iterator[Any]) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    last = None
    for last in work:
        pass
    return None if last is None else last.result


def drain(work: Iterator[Any]) -> Any:
    """Lleva unos pasos hasta el final y devuelve el último resultado que dieron."""
    result = None
    for step in work:
        if step.result is not None:
            result = step.result
    return result


def database_bytes(project: Any) -> int:
    """Lo que ocupan los ficheros de la base del proyecto (el GeoPackage y su diario)."""
    return sum(path.stat().st_size for path in Path(project.root).glob("*.gpkg*") if path.is_file())


@dataclass(frozen=True, slots=True)
class Calculated:
    """Una plataforma calculada y creada: su resultado, lo que tardó cada parte y lo que creció la base del
    proyecto (sus tablas, sus operaciones, sus parámetros y sus cifras; la superficie va en su propio fichero)."""

    outcome: Any
    calculate_s: float
    create_s: float
    db_bytes: int = 0

    @property
    def total_s(self) -> float:
        return self.calculate_s + self.create_s


def calculate(data: dperf.DesignScale, request: Any, *, version: str | None = None) -> Calculated:
    """«Calcular» y «Crear» ``request`` en la versión (V01 por defecto) como lo hace la orden, sin lo que
    sigue (:func:`entity_store.after_entity_change`: la declaración, las máscaras y la capa de entidades)."""
    before = database_bytes(data.project)
    began = time.perf_counter()
    calculation = drain(steps.platform_run(data.project, request, version=version or data.v1.uid,
                                           budget_s=0.05))
    calculated = time.perf_counter()
    with calculation:
        calculation.create()
        outcome = calculation.outcome
    created = time.perf_counter()
    return Calculated(outcome, calculated - began, created - calculated,
                      database_bytes(data.project) - before)


def create_chain(data: dperf.DesignScale, *, length: int = CHAIN_LENGTH) -> list[Calculated]:
    """Las ``length`` primeras plataformas de la cadena en V01, cada una con lo que sigue a su creación
    (``after_entity_change``), como la orden «Plataforma…»."""
    made = []
    for index in range(length):
        data.clock.advance(minutes=1)
        made.append(calculate(data, chain_request(index)))
        data.clock.advance(minutes=1)
        finish(entity_store.after_entity_change(data.project, data.v1.uid))
    return made


# --- El registro de lo que declara ``des`` para las entidades ------------------------------------


def _never(request: Any) -> Any:
    raise AssertionError("las pruebas de rendimiento de las entidades no reproducen")


def _recompute(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de los tipos de la 015: lleva sus pasos hasta el final."""
    handle, work = design_store.recompute_run(request)
    finish(work)
    return handle


def _compile_recompute(request: Any) -> Any:
    handle, work = masks_store.recompute_run(request)
    finish(work)
    return handle


@contextmanager
def _real_compile_registered() -> Iterator[None]:
    """Registra la compilación de las máscaras con **su recálculo real** (el de las pruebas de la 012 se niega a
    recalcular) mientras dura; al salir, deja la que había."""
    old = contract.OPERATIONS[masks_provenance.COMPILE]
    contract.unregister_operation(masks_provenance.COMPILE)
    contract.register_operation(masks_provenance.operation_def(
        _compile_recompute, masks_store.REPRODUCE[masks_provenance.COMPILE]))
    try:
        yield
    finally:
        contract.unregister_operation(masks_provenance.COMPILE)
        contract.register_operation(old)


def layer_data() -> qfx.LayerData:
    """La capa ``entity_data.LAYER`` (arrays nuevos): la grande y las veinte de la cadena, por orden de ``fid``."""
    arrays = edata.layer_arrays()
    return qfx.LayerData(
        LAYER, "line", tuple(((path,),) for path in arrays.paths), arrays.names,
        {"ancho": arrays.widths, "cota_inicial": arrays.levels, "pendiente": arrays.gradients})


@contextmanager
def scale_project(*, folder: Path | None = None, userdata: Path | None = None
                  ) -> Iterator[dperf.DesignScale]:
    """El proyecto de escala de la 014 (``quarry_perf.scale_project``: 2,81 M celdas de 1 m, V01 y V02, las
    máscaras de V01 al día) con lo que registra ``bl`` para la 015 (las familias de parámetros de la plataforma
    y sus tres tipos de operación, con las funciones **reales** de recalcular, y la compilación de las máscaras
    con la suya) y la capa de plataformas de escala. ``folder`` (y ``userdata``): dónde se crea, para el de la
    red; al salir lo quita todo."""
    with ExitStack() as stack:
        data = stack.enter_context(qperf.scale_project(folder=folder, userdata=userdata))
        core_params.register_families(design_params.ENTITY_FAMILIES)
        stack.callback(core_params.unregister_families, "des")
        recompute = dict.fromkeys(provenance.ENTITY_VERSION_TYPES, _recompute)
        reproduce = dict.fromkeys(provenance.ENTITY_REPRODUCIBLE, _never)
        stack.enter_context(registered(
            *provenance.entity_operation_defs(recompute, reproduce), *provenance.ENTITY_FIGURES))
        stack.enter_context(_real_compile_registered())
        qfx.write_feature_layer(data.project, data.clock, layer_data())
        data.clock.advance(minutes=1)
        yield data


# --- Las 200 entidades de RNF-015-02 y RNF-015-06 ------------------------------------------------


def add_dependents(data: dperf.DesignScale, *, count: int = SYNTHETIC_ENTITIES, version: Any = None) -> None:
    """Sobre la primera entidad real de la versión (``PLT-001``, calculada), las entidades ``PLT-002`` a
    ``PLT-<count>`` que se apoyan en ella, en cadena (``entity_synthetic.add_dependents``)."""
    entity_synthetic.add_dependents(
        data.project, data.clock, version or data.v1, import_geoblender, base_code="PLT-001", first_number=2,
        last_number=count, start_before="PLT-001", layer=LAYER, terrain=dperf.START,
        axis_point=edata.absolute(0.0, 0.0))
