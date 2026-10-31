# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de escala de la 012 (``plan.md`` §2.2; spec 012, T35; RNF-012-01 a RNF-012-06).

Se generan aquí y no se versionan (semilla :data:`SEED`, ningún dato de cliente): la rejilla de
:data:`COLS` × :data:`ROWS` celdas de 1 m (2,81 M) y, en un proyecto sintético, las
:data:`COUNT` restricciones de §2.2 con unos 100.000 vértices:

- el límite legal y el perímetro, de 2.000 vértices cada uno (estrellas de radio casi constante);
- 30 puntos, 30 líneas de 200 vértices y 40 polígonos de 500 con un resguardo de 5 a 50 m, de los
  tipos que lo piden (intocable, exclusión, resguardo, «preferible no afectar» y «sin relleno»);
- 398 polígonos de 176 vértices sin resguardo (los otros cinco tipos).

:func:`scale_project` los deja escritos en un proyecto en disco local, con V01 y V02, los
parámetros dados de alta y lo que registrará ``bl`` (las pruebas de compilar y de verificar lo
miden de ``begin`` a las cifras). Python de Blender (su numpy 2.3.4) y biblioteca estándar.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import constraints_project as cp
from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

cmodel = import_geoblender("core.constraints.model")
cparams = import_geoblender("core.constraints.params")
cstore = import_geoblender("core.constraints.store")
userdata_mod = import_geoblender("core.userdata")
versions_store = import_geoblender("core.versions.store")
create = import_geoblender("core.project.create")
gis = import_geoblender("gis")

T = cmodel.ConstraintType
G = cmodel.GeometryKind

WEST, SOUTH = 699_000.0, 4_399_000.0
COLS, ROWS = 1654, 1699
STEP_M = 1.0
EAST, NORTH = WEST + COLS * STEP_M, SOUTH + ROWS * STEP_M
SEED = 20_261_031
COUNT = 500
PERSON = "Samuel (IMGA)"
SESSION = make_session()


def window() -> tuple[float, float, float, float]:
    """La ventana del proyecto de escala: (oeste, sur, este, norte)."""
    return (WEST, SOUTH, EAST, NORTH)


def grid() -> Any:
    """La rejilla de 1 m del proyecto de escala."""
    return gis.Grid(WEST, NORTH, STEP_M, STEP_M, COLS, ROWS)


# --- Las restricciones --------------------------------------------------------------------------


def star(rng: np.random.Generator, cx: float, cy: float, radius: float, n: int,
         jitter: float = 0.3) -> np.ndarray:
    """Un anillo cerrado y antihorario de ``n`` vértices (simple: radio positivo a ángulos
    crecientes)."""
    step = 2.0 * math.pi / n
    angles = np.arange(n) * step + (rng.random(n) - 0.5) * 0.6 * step
    radii = radius * (1.0 + jitter * (rng.random(n) - 0.5) * 2.0)
    ring = np.column_stack([cx + radii * np.cos(angles), cy + radii * np.sin(angles)])
    return np.vstack([ring, ring[:1]])


def path(rng: np.random.Generator, x: float, y: float, n: int, length: float) -> np.ndarray:
    """Una línea de ``n`` vértices que empieza en (``x``, ``y``) y gira poco (``length`` m)."""
    heading = rng.uniform(0, 2 * math.pi)
    steps = length / (n - 1)
    turns = np.cumsum((rng.random(n - 1) - 0.5) * 0.4) + heading
    xy = np.column_stack([np.cumsum(np.cos(turns)) * steps, np.cumsum(np.sin(turns)) * steps])
    return np.vstack([[x, y], np.array([x, y]) + xy])


@dataclass(frozen=True, slots=True)
class ScaleConstraints:
    """Las restricciones de §2.2 (``rows``, nuevas, ``fid`` 0), los valores de sus parámetros
    de proyecto (clave → valor) y sus vértices."""

    rows: tuple[Any, ...]
    values: dict[str, Any]
    vertices: int


def build_constraints(rng: np.random.Generator | None = None) -> ScaleConstraints:
    """Las 500 restricciones de §2.2 con ``rng`` (por defecto, la semilla :data:`SEED`): el
    límite legal (10 m hacia dentro) y el perímetro, 30 puntos, 30 líneas y 40 polígonos con
    resguardo de 5 a 50 m y 398 polígonos sin él."""
    rng = np.random.default_rng(SEED) if rng is None else rng
    rows: list[Any] = []
    values: dict[str, Any] = {}
    taken: set[str] = set()
    vertices = 0
    cx, cy = (WEST + EAST) / 2.0, (SOUTH + NORTH) / 2.0

    def add(name: str, ctype: Any, kind: Any, part: np.ndarray, buffer_out: float | None,
            buffer_in: float | None = None, weight: float | None = None) -> None:
        nonlocal vertices
        code = cmodel.constraint_code(name, taken)
        taken.add(code)
        rows.append(cmodel.Constraint(
            uid=f"{len(rows):032x}", code=code, name=name, ctype=ctype, kind=kind,
            parts=((part,),), priority=0, reason="Restricción sintética de rendimiento",
            decided_by=PERSON, decided_on=date(2026, 10, 31), decision_uid=None,
            intention_uid=None, source_input=None, source_fid=None,
            layer=cstore.layer_of(kind), fid=0))
        vertices += len(part)
        values[cparams.active_key(code)] = True
        if buffer_out is not None:
            values[cparams.buffer_out_key(code)] = float(buffer_out)
        if buffer_in is not None:
            values[cparams.buffer_in_key(code)] = float(buffer_in)
        if weight is not None and ctype is T.AVOID:
            values[cparams.weight_key(code)] = float(weight)

    add("Concesión", T.LEGAL_LIMIT, G.POLYGON, star(rng, cx, cy, 760.0, 2000, 0.06), None, 10.0)
    add("Perímetro", T.ACTION_PERIMETER, G.POLYGON,
        star(rng, cx + 40, cy - 30, 640.0, 2000, 0.08), None)
    buffered = (T.UNTOUCHABLE, T.EXCLUSION, T.SETBACK, T.AVOID, T.NO_FILL)
    plain = (T.NO_CUT, T.NO_FILL, T.FILL_ONLY, T.RESTORATION_ONLY, T.REQUIRES_ACCESS)

    def at() -> tuple[float, float]:
        return (float(rng.uniform(WEST + 120, EAST - 120)),
                float(rng.uniform(SOUTH + 120, NORTH - 120)))

    for index in range(30):
        x, y = at()
        add(f"Punto {index:02d}", buffered[index % 5], G.POINT, np.array([[x, y]]),
            float(rng.uniform(5, 50)), weight=2.0)
    for index in range(30):
        x, y = at()
        add(f"Línea {index:02d}", buffered[index % 5], G.LINE, path(rng, x, y, 200, 300.0),
            float(rng.uniform(5, 50)), weight=2.0)
    for index in range(40):
        x, y = at()
        add(f"Zona {index:02d}", buffered[index % 5], G.POLYGON,
            star(rng, x, y, float(rng.uniform(30, 120)), 500), float(rng.uniform(5, 50)),
            weight=2.0)
    for index in range(398):
        x, y = at()
        add(f"Recinto {index:03d}", plain[index % 5], G.POLYGON,
            star(rng, x, y, float(rng.uniform(10, 60)), 176), 0.0)
    return ScaleConstraints(tuple(rows), values, vertices)


# --- El proyecto --------------------------------------------------------------------------------


@dataclass(slots=True)
class ScaleProject:
    """Un proyecto de escala abierto: el proyecto, su reloj, V01 y V02 (``versions``), el
    SRS de sus capas y las restricciones que se le escribieron."""

    project: Any
    clock: FakeClock
    versions: tuple[Any, Any]
    srs_id: int
    constraints: ScaleConstraints

    @property
    def v1(self) -> Any:
        """V01 («Máscaras»)."""
        return self.versions[0]

    @property
    def v2(self) -> Any:
        """V02 («Alternativa»)."""
        return self.versions[1]


@contextmanager
def scale_project(constraints: ScaleConstraints | None = None) -> Iterator[ScaleProject]:
    """Un proyecto nuevo en una carpeta temporal de disco local, con V01 y V02, las
    restricciones de §2.2 escritas (``constraints``; por defecto :func:`build_constraints`) y sus
    parámetros dados de alta en el proyecto, con lo que registrará ``bl`` para compilar. Al salir
    lo cierra y borra la carpeta."""
    made = build_constraints() if constraints is None else constraints
    with ExitStack() as stack:
        stack.enter_context(cp.constraints_registered())
        folder = stack.enter_context(project_tmp("gb-escala-"))
        clock = FakeClock()
        (folder / "proyectos").mkdir()
        settings = make_settings(window=window(), grid_step_m=STEP_M)
        project = create.create_project(folder / "proyectos", settings, SESSION,
                                        userdata_mod.UserData(folder / "u"), clock=clock).project
        stack.callback(project.close)
        versions = []
        for feature, title in (("mascaras", "Máscaras"), ("alternativa", "Alternativa")):
            clock.advance(minutes=1)
            with project.write_transaction() as conn:
                version, _revision = versions_store.create_version(
                    conn, project, feature=feature, title=title, reason="Escala de la 012")
            project.refresh_header()
            versions.append(version)
        clock.advance(minutes=1)
        cp.edit_constraints(project, made.rows)
        cp.declare(project, clock, made.values)
        clock.advance(minutes=1)
        yield ScaleProject(project, clock, (versions[0], versions[1]),
                           int(project.record.crs_epsg), made)
