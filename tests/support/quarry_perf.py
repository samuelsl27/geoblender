# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de rendimiento de la cantera con dos superficies (spec 014, T34; plan 014 §7.1 y §7.3;
``tests/rendimiento/des/test_quarry_perf.py``): los de §2.2 del plan 013 (``design_perf``) con lo
que añade la 014. Solo sintéticos: se generan al pedirlos, no se versionan y los borra quien los
escribe; ningún dato de cliente.

- **El proyecto de escala** (:func:`scale_project`): el de la 013 (``design_perf.scale_project``:
  la rejilla de 1.654 × 1.699 celdas de 1 m, V01 y V02, el límite legal y el perímetro, los 20
  sectores con su búsqueda cerrada, los diez perfiles y los dos taludes impuestos, las máscaras de
  V01 al día) con lo que registra ``bl`` para la 014 (sus siete parámetros, sus cinco tipos de
  operación y sus cifras) y el ángulo de transición (:data:`TRANSITION_DEG`; no tiene valor por
  defecto, D-9) declarado en el proyecto.
- **La cantera de escala** (:func:`quarry_request`): las dos superficies con las semillas por
  defecto («coronación y zonas a sostener», RF-014-02), la explotación con los cinco perfiles de
  10 m (:data:`EXPLOITATION_PROFILES`) y la final con los cinco de 5 m (:data:`FINAL_PROFILES`),
  en rotación por los 20 sectores; «final primero».
- **«Solo relleno»** (:func:`fill_envelope`, :func:`fill_only_request`): el escalonado en relleno
  de la envolvente descendente de 35° desde las semillas en anillo de la 013, con los perfiles de
  la final y sin láminas de agua (D-10).
- **El límite nuevo** (:func:`redraw_legal_limit`): el límite legal :data:`CUT_BACK_M` más corto
  por el este (como CE-014-08), o el de la 013 otra vez, con las máscaras de V01 recompiladas.

Python de Blender (su numpy 2.3.4) y biblioteca estándar.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

import numpy as np

from tests.support import constraints_data as cdata
from tests.support import constraints_project as cp
from tests.support import design_perf as dperf
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

core_params = import_geoblender("core.params")
cstore = import_geoblender("core.constraints.store")
access = import_geoblender("gis.masks.access")
design_model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
design_provenance = import_geoblender("design.provenance")
res_provenance = import_geoblender("reserves.provenance")
steps = import_geoblender("design.steps")

__all__ = [
    "CUT_BACK_M", "EXPLOITATION_PROFILES", "FINAL_PROFILES", "MAX_CREATED_STEP_M",
    "MIN_SHARE_PCT", "MIN_THICKNESS_M", "TRANSITION_DEG", "fill_envelope", "fill_only_request",
    "quarry_request", "redraw_legal_limit", "scale_project", "side_profiles",
]

TRANSITION_DEG = 35.0
"""El ángulo de transición con el terreno no afectado (°) que se declara en el proyecto: un dato
sintético de la prueba (``des.edge.transition_deg`` no tiene valor por defecto, D-9; el del
análisis de la spec)."""
CUT_BACK_M = 30.0
"""Lo que el límite legal nuevo queda más corto por el este (m), como CE-014-08."""
MIN_THICKNESS_M = float(res_provenance.VERIFY_MIN_THICKNESS_DEF.default)
"""El espesor mínimo de la 012 (m), el valor por defecto."""
MAX_CREATED_STEP_M = float(design_params.QUARRY_PARAMS[design_params.EDGE_MAX_STEP].default)
"""El salto creado admitido (m), el valor por defecto (D-6)."""
MIN_SHARE_PCT = float(design_params.QUARRY_PARAMS[design_params.EDGE_MIN_SHARE].default)
"""El porcentaje de las parejas del borde que tiene que quedar dentro (%), el valor por defecto
(D-6)."""
EXPLOITATION_PROFILES = tuple(profile for profile in dperf.PROFILES if profile.height_m == 10.0)
"""Los perfiles de la explotación: los cinco de 10 m de §2.2 (taludes generales de 31° a 43°)."""
FINAL_PROFILES = tuple(profile for profile in dperf.PROFILES if profile.height_m == 5.0)
"""Los perfiles de la final: los cinco de 5 m de §2.2 (taludes generales de 19° a 29°)."""
_FILL_ENVELOPE = "Plataforma de escala"


def _never(request: Any) -> Any:
    raise AssertionError("las pruebas de rendimiento no recalculan ni reproducen")


@contextmanager
def scale_project() -> Iterator[dperf.DesignScale]:
    """El proyecto de escala de la 013 (``design_perf.scale_project``) con lo que registra ``bl``
    para la 014 y el ángulo de transición :data:`TRANSITION_DEG` declarado en el proyecto. Al
    salir quita lo registrado, cierra el proyecto y borra su carpeta."""
    with ExitStack() as stack:
        data = stack.enter_context(dperf.scale_project())
        core_params.register_definitions(design_params.QUARRY_DEFINITIONS)
        stack.callback(core_params.unregister_definitions, "des")
        stack.enter_context(registered(
            *design_provenance.quarry_operation_defs(
                {kind: _never for kind in design_provenance.QUARRY_VERSION_TYPES},
                {kind: _never for kind in design_provenance.QUARRY_REPRODUCIBLE}),
            *design_provenance.QUARRY_FIGURES))
        data.clock.advance(minutes=1)
        with data.project.write_transaction() as conn:
            core_params.ParameterStore(data.project).create(
                conn, design_params.EDGE_TRANSITION, TRANSITION_DEG, kind="HIPÓTESIS",
                reason="Ángulo de transición sintético de rendimiento", **dperf.BY_HAND)
        data.clock.advance(minutes=1)
        yield data


def side_profiles(profiles: tuple[dperf.PerfProfile, ...]) -> dict[str, str]:
    """El perfil de cada uno de los 20 sectores (código del sector → código del perfil):
    ``profiles`` en rotación."""
    return {dperf.sector_code(index): profiles[(index - 1) % len(profiles)].code
            for index in range(1, dperf.SECTORS + 1)}


def quarry_request(name: str) -> Any:
    """La cantera de escala ``name``: las dos superficies desde la «coronación y zonas a
    sostener», la final con :data:`FINAL_PROFILES` y la explotación con
    :data:`EXPLOITATION_PROFILES` (el primero, el perfil base), sobre la partida de la 013."""
    return design_model.QuarryRequest(
        name=name, start=dperf.START,
        final=design_model.QuarrySide(FINAL_PROFILES[0].code, side_profiles(FINAL_PROFILES)),
        exploitation=design_model.QuarrySide(EXPLOITATION_PROFILES[0].code,
                                             side_profiles(EXPLOITATION_PROFILES)))


def _drain(work: Iterator[Any]) -> Any:
    result = None
    for step in work:
        if step.result is not None:
            result = step.result
    return result


def fill_envelope(data: dperf.DesignScale) -> str:
    """El nombre de la envolvente de «solo relleno» de V01 —la descendente de 35° desde las
    semillas en anillo de la 013—, que se crea la primera vez que se pide."""
    with data.project.read() as conn:
        found = conn.execute("SELECT count(*) FROM gb_dataset WHERE name = ?", (
            design_provenance.dataset_name(design_provenance.ENVELOPE_GRID,
                                           _FILL_ENVELOPE),)).fetchone()[0]
    if not found:
        data.clock.advance(minutes=1)
        with _drain(steps.envelope_run(data.project, dperf.ring_request(data, _FILL_ENVELOPE),
                                       version=data.v1.uid)) as calculation:
            calculation.create()
        data.clock.advance(minutes=1)
    return _FILL_ENVELOPE


def fill_only_request(name: str, envelope: str) -> Any:
    """El diseño «solo relleno» ``name`` de la envolvente ``envelope`` con los perfiles de la final
    (:data:`FINAL_PROFILES`), el ancla de su perfil y sin láminas de agua."""
    return design_model.FillOnlyRequest(name, envelope, dperf.START, FINAL_PROFILES[0].code,
                                        side_profiles(FINAL_PROFILES))


def _ring(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, de un rectángulo de coordenadas absolutas."""
    return np.array([(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)],
                    dtype=np.float64)


def redraw_legal_limit(data: dperf.DesignScale, *, cut_back: bool) -> None:
    """Redibuja el límite legal del proyecto de escala (la restricción ``concesion``, a la mitad
    de :data:`design_perf.MARGIN_M` de la ventana): con ``cut_back``, :data:`CUT_BACK_M` más corto
    por el este; si no, el de la 013. Después recompila las máscaras de V01."""
    west, south, east, north = cdata.window()
    half = dperf.MARGIN_M / 2.0
    right = east - half - (CUT_BACK_M if cut_back else 0.0)
    with data.project.read() as conn:
        (legal,) = [item for item in cstore.read_constraints(conn) if item.code == "concesion"]
    data.clock.advance(minutes=1)
    cp.edit_constraints(data.project, [dataclasses.replace(
        legal, parts=((_ring(west + half, south + half, right, north - half),),))])
    data.clock.advance(minutes=1)
    for _step in access.ensure_masks_steps(data.project, data.v1.uid):
        pass
    data.clock.advance(minutes=1)
