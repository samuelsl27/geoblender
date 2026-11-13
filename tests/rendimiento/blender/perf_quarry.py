# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera con dos superficies dentro de Blender (spec 014, T35; RNF-014-02 y, en ``Z:``,
RNF-014-01; plan 014 §7.3, ``tests/rendimiento/blender``), con la forma de ``perf_design.py`` de la
013, cuyas piezas usa: el proyecto de escala, el registro de cada llamada del hilo de Blender y los
eventos del modal.

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py --
--carpeta tests/rendimiento/blender --patron "perf_quarry.py"``). Cada prueba imprime su cifra en
una línea «RNF-014-nn: …» con el equipo y el espacio libre del disco, y la compara con su
presupuesto, sin relajarlo.

**Datos** (plan 013 §2.2 y plan 014 §7.3; se generan aquí con las semillas de
``tests/support/design_data.py`` y ``constraints_data.py``, no se versionan y se borran al
terminar): el proyecto de escala de ``perf_design.py`` (EPSG:25830 + EPSG:5782, V01 y V02, la
rejilla de 1.654 × 1.699 celdas de 1 m —2,81 M—, las 500 restricciones de la 012 con
``core.edit_constraints``, los 20 sectores con su búsqueda de intocables cerrada, el terreno y las
semillas en anillo como rejillas del proyecto, los diez perfiles de banco con
``geoblender.des_save_bench_profile``, los dos taludes impuestos y las máscaras de V01 al día)
con lo de la 014: el ángulo de transición y el talud de conservación declarados en el proyecto
(:data:`TRANSITION_DEG` y :data:`CONSERVE_DEG`, datos sintéticos: no tienen valor por defecto, D-9)
y tres capas de polígonos del proyecto (:data:`FLOORS_LAYER`, doce fondos de 150 a 172 m;
:data:`FILL_LAYER`, cuatro zonas de restauración por relleno; :data:`CONSERVE_LAYER`, una zona a
conservar). Todo con la extensión habilitada, como una persona.

- **RNF-014-02** (:class:`CallsTest`, en el orden de sus letras sobre el mismo estado): las cinco
  órdenes de la 014, las reales, como desde la interfaz: Intro (``execute`` por ``bpy.ops``, en
  pasos), cada evento del temporizador de su modal hasta que termina (con el tic de los
  indicadores de la procedencia cuando le toca, el temporizador que corre mientras tanto) y
  «Crear» (la misma orden con ``confirm``). Cada llamada del hilo de Blender se mide: lo que hace
  Geoblender en ella, **sin la transacción final** (``DesignWriter.commit``: la operación, los
  temporales movidos, las tablas y las cifras en una transacción que no se trocea; el R4 de la
  012), ≤ 0,2 s; la transacción, medida aparte, se anota con la llamada en que ocurre (si pasa de
  0,2 s, con un aviso: la cifra, para Samuel). (a) «Límite desde el perímetro…»; (b) «Cantera con
  dos superficies…» con las semillas «coronación y zonas a sostener» en los dos lados, la final con
  los cinco perfiles de 5 m y la explotación con los cinco de 10 m en rotación por los 20 sectores
  y anclada «al fondo de cada muro», «final primero», las tres capas y «explotación hasta la final»
  en las zonas avisadas; (c) «Transiciones con el terreno no afectado» de su superficie final; (d)
  «Solo relleno…» de la envolvente descendente de 35° desde una plataforma a :data:`PLATFORM_M` en
  las zonas de relleno (creada antes, sin medir) con los perfiles de 5 m; y (e) con el límite legal
  redibujado (:data:`SHIFT_M` m al oeste, que deja
  fuera las dos superficies de la cantera por el este), «Compilar las máscaras»
  (``geoblender.gis_compile_constraints``: tras guardar la compilación, sus pasos siguen con los de
  la comprobación de la 014 contra el límite nuevo, RF-014-26, que llenan la caché de
  ``des_panels``) y «Ajustar el diseño a un límite nuevo…» de las dos superficies. Con la caché
  llena, abrir la ventana del ajuste (``des_panels.cached_refit_rows``) y leer la ficha de la barra
  N de una superficie fuera del límite (``des_panels.item_lines``) no leen ninguna rejilla; sin
  acierto (la caché vaciada), la ficha no se bloquea y comprueba por pasos en su temporizador
  (``des_panels.limit_tick``, cada tic medido como una llamada) y la orden del ajuste comprueba por
  pasos en su modal antes de abrir la ventana (en ``blender -b`` Blender no llama a ``invoke``: se
  llama con un ``self`` y un contexto de mentira, como en ``tests/blender/test_quarry_limit.py``).
  **Cada llamada se mide en CPU del proceso**
  (``time.process_time()``, que no cuenta lo que gastan otros programas: ``docs/trampas.md`` §4)
  **y en pared**; el presupuesto se exige a la CPU y la pared se anota con un aviso si lo pasa (se
  repite con el equipo en reposo). La resolución del reloj de CPU de Windows es de unos 16 ms.
- **En la red** (:class:`NetworkTest`; recurso «red» de ``tests.support.network``: con
  ``GEOBLENDER_NET_TEST_DIR``, a mano, en el H3; sin ella, se omite): «Cantera con dos
  superficies…» (Calcular y Crear) con el proyecto (el límite legal, el perímetro, los sectores, las
  rejillas y las capas: sin las 500 restricciones) en una subcarpeta temporal propia de la carpeta
  de pruebas de ``Z:`` (borrada al terminar) y los datos de usuario en disco local: RNF-014-01 en
  ``Z:`` (≤ 40 s, de «Calcular» a las cifras registradas, con los 50 ms del temporizador del
  modal) y RNF-014-02 sin las esperas de la red de cada llamada (medidas con
  ``tests.support.netwaits`` y anotadas aparte, sin presupuesto, como RNF-013-07). Escribe en la
  red las rejillas del proyecto y las cinco de la cantera. **Ojo**: en el
  PC de referencia la variable está definida en el usuario y este módulo, lanzado tal cual, también
  corre la de la red (``docs/trampas.md`` §7); para medir solo en local, sin ella:
  ``env -u GEOBLENDER_NET_TEST_DIR …`` (Git Bash) o ``Remove-Item Env:GEOBLENDER_NET_TEST_DIR``
  (PowerShell).

En ``blender -b`` no corren ni el bucle de eventos ni los temporizadores: la prueba hace de ventana
(un evento del temporizador del modal cada vez) y de temporizador; la confirmación de «Calcular»
(``_ask_confirmation``, que relanza la orden con un temporizador) se sustituye.
"""

from __future__ import annotations

import dataclasses
import gc
import importlib
import json
import tempfile
import time
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.rendimiento.blender import perf_constraints as pc
from tests.rendimiento.blender import perf_design as pd
from tests.support import blender_ext, netwaits, network
from tests.support import constraints_data as cdata
from tests.support import design_data as ddata
from tests.support.blender_ext import module_name
from tests.support.fake_layout import operator_self
from tests.support.resources import requires
from tests.support.trees import remove_tree

CALL_BUDGET_S = 0.2  # RNF-014-02: lo que hace Geoblender en cada llamada del hilo de Blender
QUARRY_NETWORK_BUDGET_S = 40.0  # RNF-014-01 en Z:: las dos superficies, de Calcular a Crear
TOP_CALLS = 5
KEY_BUDGET_S = 0.02  # la clave de la caché de la comprobación (T35; la mejor de 5, en pared)
REASON = "Rendimiento de la cantera con dos superficies (spec 014, T35)"
PERSON = ddata.PERSON
SOURCE = "Valores sintéticos de prueba"
LAYERS_TYPE = "gis.perf_quarry_layers"
"""El tipo de operación con que se escriben las capas de la prueba (como la importación de la
006)."""
TRANSITION_DEG = 35.0
"""El ángulo de transición con el terreno no afectado (°) declarado en el proyecto: un dato
sintético de la prueba (``des.edge.transition_deg`` no tiene valor por defecto, D-9)."""
CONSERVE_DEG = 35.0
"""El talud de conservación (°) declarado en el proyecto: un dato sintético de la prueba
(``des.conserve.slope_deg`` no tiene valor por defecto, D-9)."""
SHIFT_M = 60.0
"""Lo que se desplaza al oeste el límite legal redibujado (m): su borde este queda dentro del
perímetro de actuación y deja fuera parte de las dos superficies de la cantera."""
FLOORS_LAYER = "gis_fea_fondos_escala"
FILL_LAYER = "gis_fea_relleno_escala"
CONSERVE_LAYER = "gis_fea_conservar_escala"
LEVEL_FIELD = "cota"
ENVELOPE_NAME = "Plataforma de escala"
"""La envolvente de «Solo relleno…»: la descendente de 35° desde una plataforma a
:data:`PLATFORM_M` en las zonas de :data:`FILL_LAYER`."""
PLATFORM_M = 200.0
"""La cota de la plataforma de «Solo relleno…» (m): por encima del terreno en casi toda la
rejilla (de 145 a 215 m), así que el escalonado en relleno rellena alrededor de las zonas."""

LIMIT = "geoblender.des_create_limit_from_perimeter"
QUARRY = "geoblender.des_design_quarry"
TRANSITIONS = "geoblender.des_create_transitions"
FILL_ONLY = "geoblender.des_design_fill_only"
REFIT = "geoblender.des_refit_to_limit"
COMPILE = "geoblender.gis_compile_constraints"
COMPUTE = pd.COMPUTE

AREA_TYPE = "des.excavation_area"
QUARRY_TYPE = "des.quarry"
TRANSITION_TYPE = "des.edge_transition"
FILL_ONLY_TYPE = "des.fill_only"
REFIT_TYPE = "des.refit"
COMPILE_TYPE = "gis.compile_constraints"

EXPLOITATION_PROFILES = tuple(profile for profile in ddata.PROFILES if profile.height_m == 10.0)
"""Los perfiles de la explotación: los cinco de 10 m de §2.2 (taludes generales de 31° a 43°)."""
FINAL_PROFILES = tuple(profile for profile in ddata.PROFILES if profile.height_m == 5.0)
"""Los perfiles de la final y de «Solo relleno…»: los cinco de 5 m (taludes generales de 19° a
29°)."""

CENTER = ((cdata.WEST + cdata.EAST) / 2.0 + 40.0, (cdata.SOUTH + cdata.NORTH) / 2.0 - 30.0)
"""El centro del perímetro de actuación de §2.2 (``constraints_data.build_specs``), absoluto."""
FLOORS = tuple(((dx, dy, 40.0, 25.0), 150.0 + 2.0 * index) for index, (dx, dy) in enumerate(
    (dx, dy) for dy in (-200.0, 0.0, 200.0) for dx in (-300.0, -100.0, 100.0, 300.0)))
"""Los doce fondos: (desplazamiento al este y al norte desde :data:`CENTER` y semiancho y semialto,
m) y su cota (m), de 150 a 172 m, sin solaparse."""
FILL_ZONES = tuple((dx, dy, 60.0, 40.0) for dx in (-200.0, 200.0) for dy in (-330.0, 330.0))
"""Las cuatro zonas de restauración por relleno (como :data:`FLOORS`, sin cota)."""
CONSERVE_ZONE = (0.0, 400.0, 30.0, 30.0)
"""La zona a conservar (como :data:`FLOORS`, sin cota)."""

report = pd.report
number = pd.number
ms = pd.ms
count = pd.count
free_space = pd.free_space
MACHINE = pd.MACHINE
CELLS = ddata.CELLS


def _module(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión."""
    return importlib.import_module(f"{module_name()}.{name}")


def view() -> Any:
    """La vista de las ventanas del diseño (``WindowManager.geoblender_design``)."""
    return pd.view()


def profile_name(profile: ddata.PerfProfile) -> str:
    """El nombre con que ``perf_design.build`` guarda un perfil (su código en mayúsculas)."""
    return pd.profile_name(profile)


def in_rotation(profiles: Sequence[ddata.PerfProfile], code: str) -> str:
    """El nombre del perfil de ``profiles`` que se asigna al sector ``code`` (``sector_NN``): en
    rotación."""
    index = int(code.rsplit("_", 1)[1])
    return profile_name(profiles[(index - 1) % len(profiles)])


# --- El proyecto de escala de la 013 con lo de la 014 -------------------------------------------


def _box_ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo ``box`` (desplazamiento al este y
    al norte desde :data:`CENTER`, semiancho y semialto)."""
    dx, dy, half_w, half_h = box
    left, right = CENTER[0] + dx - half_w, CENTER[0] + dx + half_w
    bottom, top = CENTER[1] + dy - half_h, CENTER[1] + dy + half_h
    return np.array([(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)],
                    dtype=np.float64)


def write_layer(project: Any, name: str, boxes: Sequence[tuple[float, float, float, float]],
                numbers: dict[str, tuple[float, ...]]) -> None:
    """Una capa de polígonos ``gis_fea_…`` con un rectángulo por entidad (``boxes``), el campo
    ``nombre`` y los campos numéricos ``numbers`` (``DOUBLE``, un valor por entidad), como la deja
    la importación de la 006."""
    gis_store, vector = _module("gis.store"), _module("gis.vector")
    datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
    srs = int(project.record.crs_epsg)
    columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
               *(vector.FieldColumn(field, field, "DOUBLE") for field in numbers))
    fids = tuple(range(1, len(boxes) + 1))
    values = {"nombre": tuple(f"Entidad {fid}" for fid in fids),
              **{field: tuple(found) for field, found in numbers.items()}}
    entities = tuple(((_box_ring(box),),) for box in boxes)
    layer = vector.FeatureLayer("polygon", fids, entities, columns, values)
    rows = gis_store.feature_rows(layer, srs)
    names = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
    marks = ", ".join("?" for _ in range(len(columns) + 2))
    handle = _module("core.provenance.operations").begin_operation(
        project, LAYERS_TYPE, settings={"name": name}, executor="blender")
    with project.write_transaction() as conn:
        conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                     f"geom {layer.geometry_type}, {names})")
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                     "description, srs_id) VALUES (?, 'features', ?, '', ?)", (name, name, srs))
        conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                     "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                     (name, layer.geometry_type, srs))
        conn.executemany(f'INSERT INTO "{name}" VALUES ({marks})', rows)
        handle.complete(conn, outputs=(datasets.DatasetSpec(
            name, "gis", "vector", datasets.Store.GPKG, name,
            reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs, input_uid=None,
            immutable=False),), message="Capa de rendimiento de la cantera")


def declare_quarry(project: Any) -> None:
    """El ángulo de transición y el talud de conservación (sin valor por defecto, D-9), declarados
    en el proyecto con su procedencia, y las tres capas de la cantera."""
    params, dparams = _module("core.params"), _module("design.params")
    store = params.ParameterStore(project)
    with project.write_transaction() as conn:
        for key, value in ((dparams.EDGE_TRANSITION, TRANSITION_DEG),
                           (dparams.CONSERVE_SLOPE, CONSERVE_DEG)):
            store.create(conn, key, value, kind="HIPÓTESIS", source=SOURCE,
                         source_kind="document", decided_by=PERSON, reason=REASON)
    write_layer(project, FLOORS_LAYER, [box for box, _level in FLOORS],
                {LEVEL_FIELD: tuple(level for _box, level in FLOORS)})
    write_layer(project, FILL_LAYER, FILL_ZONES, {})
    write_layer(project, CONSERVE_LAYER, (CONSERVE_ZONE,), {})


def build(parent: Path, constraints: int) -> pd.Built:
    """El proyecto de escala de ``perf_design.build`` (con las primeras ``constraints``
    restricciones de §2.2) en ``parent``, con lo de la 014 (:func:`declare_quarry`), abierto en la
    sesión con V01 activa y sus máscaras al día."""
    built = pd.build(parent, constraints)
    project = _module("bl.scene.project_session").current()
    declare_quarry(project)
    pc.ensure_masks(project, built)
    pd.refresh_lists(project)
    return built


class _Local:
    """El proyecto de escala en disco local, uno para todo el módulo (se construye la primera vez
    que se pide), en la sesión."""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.made: pd.Built | None = None

    def built(self) -> pd.Built:
        """El proyecto, abierto en la sesión (construido, si aún no lo está)."""
        if self.made is None:
            self.folder = Path(tempfile.mkdtemp(prefix="gb-014-t35-"))
            self.made = build(self.folder / "proyectos", cdata.COUNT)
        elif _module("bl.scene.project_session").current() is None:
            pd.base.reopen(self.made)
            pd.refresh_lists(_module("bl.scene.project_session").current())
        return self.made

    def restore(self) -> None:
        """Vuelve a abrirlo en la sesión, si ya se construyó."""
        if self.made is not None:
            self.built()

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
    contract.register_operation(contract.OperationDef(LAYERS_TYPE, "1.0", "gis",
                                                      "Layers of the performance tests", False))


def tearDownModule() -> None:  # noqa: N802
    try:
        _module("bl.draw.design").disable()
        _module("bl.scene.project_session").close()
        _LOCAL.close()
        _module("core.provenance.contract").unregister_operation(LAYERS_TYPE)
    finally:
        blender_ext.load_file()
        blender_ext.release()


# --- Las llamadas del hilo de Blender -----------------------------------------------------------


class Recorder(pd.Recorder):
    """El de ``perf_design.py`` (cada llamada en pared y en CPU, con sus esperas de la red y la
    transacción final de ``DesignWriter.commit``) y, además, la transacción final de compilar las
    máscaras (``MaskWriter.commit`` de ``gis.masks.store``)."""

    def __enter__(self) -> Recorder:
        super().__enter__()
        writer = _module("gis.masks.store").MaskWriter
        self._stack.enter_context(mock.patch.object(writer, "commit", self._timed(writer.commit)))
        return self

    def _timed(self, real: Callable[..., Any]) -> Callable[..., Any]:
        recorder = self

        def commit(writer: Any, *args: Any, **kwargs: Any) -> Any:
            before = recorder._waited()
            started, cpu = time.perf_counter(), time.process_time()
            try:
                return real(writer, *args, **kwargs)
            finally:
                op_type = getattr(writer, "op_type", None) or writer.handle.op_type
                recorder._commits.append((str(op_type), time.perf_counter() - started,
                                          time.process_time() - cpu, recorder._waited() - before))

        return commit


def warn_slow(run: pd.Run, where: str) -> None:
    """Los avisos de lo que pasa de 0,2 s: lo que no es la transacción final en pared (se repite en
    reposo; el presupuesto se exige a la CPU) y la transacción final (para Samuel, R4)."""
    over = [call for call in run.calls if call.budgeted > CALL_BUDGET_S]
    if over:
        report(f"Aviso RNF-014-02 ({where}): {len(over)} llamadas de más de "
               f"{number(CALL_BUDGET_S, 1)} s de pared sin la transacción final (con el equipo "
               f"cargado por otros programas se repite en reposo; el presupuesto se exige a la "
               f"CPU): " + "; ".join(f"{ms(call.budgeted)} ms de pared y {ms(call.budgeted_cpu)} "
                                     f"de CPU ({call.text()})" for call in over))
    long = [(op, seconds - waited) for call in run.with_commits
            for op, seconds, _cpu, waited in call.commits if seconds - waited > CALL_BUDGET_S]
    if long:
        report(f"Aviso RNF-014-02 ({where}; R4 de la 012, la cifra para Samuel): la transacción "
               f"final pasa de {number(CALL_BUDGET_S, 1)} s: "
               + "; ".join(f"{op} {ms(seconds)} ms" for op, seconds in long))


def measure(label: str, steps: Callable[[Recorder], None],
            waits: netwaits.NetworkWaits | None = None) -> pd.Run:
    """Lo que hacen ``steps`` con el hilo de Blender, llamada a llamada."""
    recorder = Recorder(waits)
    gc.collect()
    with recorder:
        started = time.perf_counter()
        steps(recorder)
        seconds = time.perf_counter() - started
    return pd.Run(label, tuple(recorder.calls), seconds)


def calculate(recorder: Recorder, idname: str, form: dict[str, Any], what: str) -> None:
    """«Calcular» de la orden ``idname``: Intro (la orden en pasos) y cada evento de su modal hasta
    que termina, con la confirmación sustituida (sin ventana no corre su temporizador); deja el
    cálculo abierto."""
    commands = _module("bl.ui.commands")
    des_ops = _module("bl.ops.des")
    cls = commands.registered_class(idname)
    order = getattr(bpy.ops.geoblender, idname.removeprefix("geoblender."))
    with mock.patch.object(des_ops, "_ask_confirmation") as ask:
        result = recorder.call(f"Intro: comprobar y empezar ({what})", order, "EXEC_DEFAULT",
                               in_steps=True, **form)
        if result != {"RUNNING_MODAL"}:
            raise AssertionError(f"«{what}» no empieza: {result}")
        operator = pc.running(cls)
        state = pd.pump(recorder, operator, what)
    if state != {"FINISHED"} or ask.call_count != 1:
        raise AssertionError(f"«{what}» acaba mal: {state}, {getattr(operator, 'report_log', [])}")
    if des_ops.calculation() is None:
        raise AssertionError(f"«{what}» no deja el cálculo abierto")


def create(recorder: Recorder, idname: str, what: str) -> None:
    """«Crear»: la misma orden con ``confirm`` (la transacción final)."""
    order = getattr(bpy.ops.geoblender, idname.removeprefix("geoblender."))
    result = recorder.call(f"Crear ({what})", order, "EXEC_DEFAULT", confirm=True, in_steps=True)
    if result != {"FINISHED"}:
        raise AssertionError(f"«{what}» no se crea: {result}")


def chain(idname: str, form: dict[str, Any], what: str) -> Callable[[Recorder], None]:
    """«Calcular» y «Crear» de la orden ``idname`` con lo pedido ``form``."""

    def steps(recorder: Recorder) -> None:
        calculate(recorder, idname, form, what)
        create(recorder, idname, what)

    return steps


def pick_profiles() -> None:
    """El perfil de cada sector en las tres columnas de la ventana de los sectores, como lo haría la
    persona: los de 5 m en la de la superficie final y en la del escalonado («Solo relleno…»), y los
    de 10 m en la de explotación, en rotación."""
    for row in view().sectors:
        row.final_pick = in_rotation(FINAL_PROFILES, row.code)
        row.exploitation_pick = in_rotation(EXPLOITATION_PROFILES, row.code)
        row.profile_pick = in_rotation(FINAL_PROFILES, row.code)


def quarry_form(built: pd.Built, name: str) -> dict[str, Any]:
    """Lo pedido en el diálogo de «Cantera con dos superficies…» (véase el módulo)."""
    return {
        "name": name, "start": built.start, "order": "FINAL_FIRST",
        "final_seeds": "CROWN", "final_profile": profile_name(FINAL_PROFILES[0]),
        "final_anchor": "FIXED", "final_metric": "CHAMFER5",
        "exploitation_seeds": "CROWN",
        "exploitation_profile": profile_name(EXPLOITATION_PROFILES[0]),
        "exploitation_anchor": "NEAREST_FLOOR", "exploitation_metric": "CHAMFER5",
        "floors_layer": FLOORS_LAYER, "floors_field": LEVEL_FIELD,
        "conserve": f"layer:{CONSERVE_LAYER}", "fill_layer": FILL_LAYER, "to_final": "WARNED"}


def surface_row(name: str) -> dict[str, Any]:
    """Una fila de las superficies de «Ajustar el diseño a un límite nuevo…» desde un guion (Blender
    pide todos sus campos), marcada."""
    return {"name": name, "label": "", "outside": False, "selected": True}


def redraw_legal_limit(project: Any, shift_m: float) -> None:
    """Redibuja el límite legal (la restricción «Concesión») desplazado ``shift_m`` m al oeste, con
    ``core.edit_constraints``, como lo haría la persona; las máscaras de V01 quedan obsoletas."""
    cstore, cprov = _module("core.constraints.store"), _module("core.constraints.provenance")
    with project.read() as conn:
        (legal,) = [item for item in cstore.read_constraints(conn) if item.name == "Concesión"]
    parts = tuple(tuple(ring - np.array([shift_m, 0.0]) for ring in part) for part in legal.parts)
    cprov.edit_constraints(project, [dataclasses.replace(legal, parts=parts)],
                           srs_id=project.record.crs_epsg)


@dataclasses.dataclass(frozen=True)
class Timed:
    """Una lectura medida fuera de un cálculo: lo que tardó en pared y en CPU y lo que dio."""

    seconds: float
    cpu: float
    found: Any


def timed(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Timed:
    """``function(*args, **kwargs)`` medida en pared y en CPU del proceso, con la basura recogida
    antes."""
    gc.collect()
    started, cpu = time.perf_counter(), time.process_time()
    found = function(*args, **kwargs)
    return Timed(time.perf_counter() - started, time.process_time() - cpu, found)


class _Case(unittest.TestCase):
    """La extensión habilitada (sin importarla otra vez: ``blender_ext.release``), el idioma en
    español y el proyecto de escala en disco local, el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ps = _module("bl.scene.project_session")
        cls.des_ops = _module("bl.ops.des")
        cls.panels = _module("bl.ui.des_panels")
        cls.dprov = _module("design.provenance")
        cls.dstore = _module("design.store")

    def tearDown(self) -> None:
        self.des_ops.discard_calculation()  # lo que deja una que falla no pasa a la siguiente

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.ps.current().read() as conn:
            return conn.execute(sql, args).fetchall()

    def done(self, op_type: str, name: str) -> list[str]:
        """El uid de las operaciones ``op_type`` hechas con el nombre ``name``."""
        return [uid for uid, settings in self.rows(
            "SELECT uid, settings FROM gb_operation WHERE op_type = ? AND status = 'done'", op_type)
            if json.loads(settings).get("name") == name]

    def figures_of(self, op_type: str, name: str) -> dict[str, float]:
        """Las cifras de la operación ``op_type`` de nombre ``name`` (una sola hecha), por su clave
        y su ámbito."""
        (uid,) = self.done(op_type, name)
        return {f"{key} {scope}": float(value) for key, scope, value in self.rows(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def total(self, op_type: str, name: str, key: str) -> float:
        """La cifra ``key`` de la operación ``name`` en su ámbito más corto (el total)."""
        found = {label: value for label, value in self.figures_of(op_type, name).items()
                 if label.split(" ", 1)[0] == key}
        self.assertTrue(found, f"«{name}» sin la cifra {key}")
        return found[min(found, key=len)]


# --- RNF-014-02: calcular y crear con las órdenes reales -----------------------------------------


class CallsTest(_Case):
    """RNF-014-02 con el proyecto de escala en disco local, en el orden de sus letras sobre el
    mismo estado: la cantera de la b la usan la c y la e."""

    QUARRY_NAME = "Cantera de escala"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.built = _LOCAL.built()

    def check_run(self, run: pd.Run, where: str) -> None:
        warn_slow(run, where)
        worst = run.worst_cpu
        self.assertLessEqual(worst.budgeted_cpu, CALL_BUDGET_S, f"{run.label}: {worst.text()}")

    def report_run(self, text: str, run: pd.Run) -> None:
        built = self.built
        report(f"RNF-014-02: {text} con {built.constraints} restricciones "
               f"({count(built.vertices)} vértices), {ddata.SECTORS} sectores y {count(CELLS)} "
               f"celdas de 1 m ({MACHINE}), "
               f"{pd.calls_line(run, 'con el proyecto en disco local', network_waits=False)}; "
               f"{free_space(built.root)}")

    def test_a_limit_from_the_perimeter(self) -> None:
        """RNF-014-02 (plan 014 §7.3; RF-014-01, RF-014-29): «Límite desde el perímetro…» sobre
        2,81 M celdas con las 500 restricciones de la 012, como desde la interfaz: en ninguna
        llamada del hilo de Blender (Intro, cada evento del modal, el tic de los indicadores y
        «Crear») lo que hace Geoblender sin la transacción final pasa de 0,2 s de CPU; la
        transacción final, aparte."""
        name = "Recinto de escala"
        form = {"name": name, "surface": self.built.start}
        run = measure("recinto", chain(LIMIT, form, "recinto"))
        self.assertEqual(len(self.done(AREA_TYPE, name)), 1)
        area = self.total(AREA_TYPE, name, "des.rcn_area_m2")
        self.assertGreater(area, 0.0)
        self.report_run(f"«Límite desde el perímetro…» (recinto de {count(int(area))} m²)", run)
        self.check_run(run, "recinto")

    def test_b_quarry_with_two_surfaces(self) -> None:
        """RNF-014-02 (plan 014 §7.3; RF-014-02, RF-014-05, RF-014-07, RF-014-11 a RF-014-18,
        RF-014-29): «Cantera con dos superficies…» —las dos envolventes por los 20 sectores desde la
        coronación y las zonas a sostener de las 500 restricciones, los doce fondos con la
        explotación anclada al fondo de cada muro, el techo de la zona a conservar, los dos
        escalonados, la regla de orden, la clasificación con las zonas de relleno y el aviso y el
        modo de «explotación hasta la final»—, «Calcular» y «Crear»: en ninguna llamada sin la
        transacción final pasa de 0,2 s de CPU."""
        name = self.QUARRY_NAME
        pick_profiles()
        run = measure("cantera", chain(QUARRY, quarry_form(self.built, name), "cantera"))
        self.assertEqual(len(self.done(QUARRY_TYPE, name)), 1)
        cut = self.total(QUARRY_TYPE, name, "des.exp_cut_m3")
        unsplit = self.total(QUARRY_TYPE, name, "des.unsplit_m3")
        self.assertGreater(cut, 0.0, "la cantera no excava: no mide nada")
        self.report_run(f"«Cantera con dos superficies…» (excavación de la explotación "
                        f"{number(cut / 1e6, 1)} hm³, desdoblado {number(unsplit / 1e6, 2)} hm³)",
                        run)
        self.check_run(run, "cantera")

    def test_c_transitions(self) -> None:
        """RNF-014-02 (plan 014 §7.3; RF-014-19 a RF-014-21, RF-014-29): «Transiciones con el
        terreno no afectado» de la superficie final de la cantera de la b (la transición y el salto
        creado), «Calcular» y «Crear»: en ninguna llamada sin la transacción final pasa de 0,2 s de
        CPU."""
        name = "Transición de escala"
        surface = self.dprov.dataset_name("fin", self.QUARRY_NAME)
        self.panels.refresh_choices(self.ps.current())  # la lista del diálogo, con la cantera
        form = {"name": name, "surface": surface, "start": self.built.start}
        run = measure("transición", chain(TRANSITIONS, form, "transición"))
        self.assertEqual(len(self.done(TRANSITION_TYPE, name)), 1)
        volume = self.total(TRANSITION_TYPE, name, "des.transition_m3")
        self.report_run(f"«Transiciones con el terreno no afectado» de «{surface}» con "
                        f"{number(TRANSITION_DEG, 0)}° ({number(volume, 0)} m³)", run)
        self.check_run(run, "transición")

    def test_d_fill_only(self) -> None:
        """RNF-014-02 (plan 014 §7.3; RF-014-22 a RF-014-25, RF-014-29): «Solo relleno…» de la
        envolvente descendente de 35° desde una plataforma a 200 m en las zonas de relleno (creada
        antes, sin medir) con los perfiles de 5 m por sector, «Calcular» y «Crear»: en ninguna
        llamada sin la transacción final pasa de 0,2 s de CPU."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            form = pd.envelope_form(self.built, ENVELOPE_NAME, seeds_from="FIXED",
                                    zone=f"layer:{FILL_LAYER}", elevation=f"{PLATFORM_M:g}",
                                    in_steps=False)
            self.assertEqual(bpy.ops.geoblender.des_compute_envelope("EXEC_DEFAULT", **form),
                             {"FINISHED"})
            self.assertEqual(bpy.ops.geoblender.des_compute_envelope(
                "EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.panels.refresh_choices(self.ps.current())
        name = "Relleno de escala"
        pick_profiles()
        form = {"name": name, "envelope": ENVELOPE_NAME, "start": self.built.start,
                "base_profile": profile_name(FINAL_PROFILES[0])}
        run = measure("solo relleno", chain(FILL_ONLY, form, "solo relleno"))
        self.assertEqual(len(self.done(FILL_ONLY_TYPE, name)), 1)
        fill = self.total(FILL_ONLY_TYPE, name, "des.fill_m3")
        self.report_run(f"«Solo relleno…» de «{ENVELOPE_NAME}» ({number(fill, 0)} m³ de "
                        f"relleno)", run)
        self.check_run(run, "solo relleno")

    def test_e_refit_to_a_new_limit(self) -> None:
        """RNF-014-02 (plan 014 §7.3; RF-014-26 a RF-014-29; T35): con el límite legal redibujado,
        que deja fuera parte de las dos superficies de la cantera de la b, «Compilar las máscaras»
        (sus pasos y, tras guardar la compilación, los de la comprobación de la 014 contra el límite
        nuevo, RF-014-26, que llenan la caché), abrir la ventana del ajuste y leer la ficha de la
        barra N de una superficie fuera del límite con la caché llena (sin leer ninguna rejilla),
        sin acierto la ficha (y su comprobación de fondo, tic a tic) y la comprobación de la orden
        antes de abrir su ventana (Intro y cada evento de su modal), y «Ajustar el diseño a un
        límite nuevo…» de las dos superficies («Calcular» y «Crear»): en ninguna llamada sin la
        transacción final pasa de 0,2 s de CPU. La clave de la caché, ≤ 20 ms."""
        project = self.ps.current()
        version = self.built.version_uid
        redraw_legal_limit(project, SHIFT_M)
        panels = self.panels
        check_phase = _module("bl.ui.constraint_panels").CHECK_PHASE
        compiler: list[Any] = []

        def compile_steps(recorder: Recorder) -> None:
            order = bpy.ops.geoblender.gis_compile_constraints
            result = recorder.call("Intro: comprobar y empezar (compilar)", order,
                                   "EXEC_DEFAULT", in_steps=True)
            if result != {"RUNNING_MODAL"}:
                raise AssertionError(f"«Compilar las máscaras» no empieza: {result}")
            cls = _module("bl.ui.commands").registered_class(COMPILE)
            compiler.append(pc.running(cls))
            state = pd.pump(recorder, compiler[0], "compilar")
            if state != {"FINISHED"}:
                raise AssertionError(f"«Compilar las máscaras» acaba mal: {state}")

        compiled = measure("compilar con la comprobación de la 014", compile_steps)
        exploitation = self.dprov.dataset_name("exp", self.QUARRY_NAME)
        final = self.dprov.dataset_name("fin", self.QUARRY_NAME)
        outside = [text for text in compiler[0].report_log if "fuera del límite vigente" in text]
        self.assertTrue(any(exploitation in text for text in outside), outside)
        self.assertTrue(any(final in text for text in outside), outside)
        checking = [call for call in compiled.calls if check_phase in call.phases.split(",")]
        self.assertTrue(checking, "la compilación no comprobó las superficies de la 014")
        self.assertFalse([call for call in checking if call.commits],
                         "la llamada de la transacción de la compilación también comprueba")
        worst_check = max(checking, key=lambda call: call.budgeted_cpu)
        report(f"RNF-014-02: «Compilar las máscaras» de V01 con {self.built.constraints} "
               f"restricciones tras redibujar el límite legal {number(SHIFT_M, 0)} m al oeste, con "
               f"las superficies de la 014 de la versión ({len(outside)} fuera del límite "
               f"nuevo) ({MACHINE}), "
               f"{pd.calls_line(compiled, 'con el proyecto en disco local', network_waits=False)}"
               f"; la comprobación de la 014 contra el límite nuevo (RF-014-26), por pasos tras "
               f"guardar la compilación: {len(checking)} llamadas, "
               f"{number(sum(call.seconds for call in checking), 2)} s de pared, la peor "
               f"{ms(worst_check.budgeted)} ms de pared y {ms(worst_check.budgeted_cpu)} de CPU "
               f"({worst_check.text()}); {free_space(self.built.root)}")

        keys = min((timed(self.dstore.limit_check_keys, project, version,
                          types=self.dstore.REFIT_SOURCES) for _ in range(5)),
                   key=lambda found: found.seconds)
        self.assertGreaterEqual(len(keys.found.surfaces), 4)
        no_read = mock.patch.object(self.dstore, "read_surface",
                                    side_effect=AssertionError("lee una rejilla"))
        with no_read:
            opened = timed(panels.cached_refit_rows, project, version)
            rows, _note = opened.found
            uid = self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status IN "
                            "('current', 'stale')", exploitation)[0][0]
            card = timed(panels.item_lines, project, str(uid))
        marked = [surface for surface, _label, out in rows if out]
        self.assertIn(exploitation, marked)
        self.assertIn(final, marked)
        self.assertTrue(any(line.alert and "fuera del límite vigente" in line.text
                            for line in card.found.lines))
        report(f"RNF-014-02 (T35, de la caché): la clave de la comprobación de "
               f"{len(keys.found.surfaces)} superficies {ms(keys.seconds)} ms de pared y "
               f"{ms(keys.cpu)} de CPU (la mejor de 5; presupuesto "
               f"{ms(KEY_BUDGET_S)} ms); abrir «Ajustar el diseño a un límite nuevo…» ("
               f"{len(rows)} superficies de diseño, {len(marked)} fuera del límite vigente) "
               f"{ms(opened.seconds)} ms de pared y {ms(opened.cpu)} de CPU; la ficha de la barra "
               f"N de «{exploitation}» {ms(card.seconds)} ms de pared y {ms(card.cpu)} de CPU "
               f"({MACHINE})")

        panels.forget_limit_checks()  # sin acierto: la ficha, sin bloquearse, y su temporizador
        self.addCleanup(lambda: bpy.app.timers.is_registered(panels.limit_tick)
                        and bpy.app.timers.unregister(panels.limit_tick))

        def card_steps(recorder: Recorder) -> None:
            found = recorder.call("la ficha de la barra N sin acierto", panels.item_lines,
                                  project, str(uid))
            if any("fuera del límite vigente" in line.text for line in found.lines):
                raise AssertionError("la ficha sin acierto dice el aviso")
            for tick in range(pc.MAX_EVENTS):
                if recorder.call(f"paso {tick + 1} de la comprobación de fondo",
                                 panels.limit_tick) is None:
                    return
            raise AssertionError("la comprobación de fondo no acaba")

        background = measure("la ficha sin acierto y su comprobación de fondo", card_steps)
        with no_read:
            self.assertTrue(any(line.alert and "fuera del límite vigente" in line.text
                                for line in panels.item_lines(project, str(uid)).lines))
        where = "con el proyecto en disco local"
        report(f"RNF-014-02 (T35, sin acierto): la ficha de la barra N de «{exploitation}» y su "
               f"comprobación de fondo ({MACHINE}), "
               f"{pd.calls_line(background, where, network_waits=False)}")

        panels.forget_limit_checks()  # sin acierto: la orden comprueba antes de abrir su ventana
        refit_cls = _module("bl.ui.commands").registered_class(REFIT)
        steps_modal = _module("bl.ops.core")._StepsModal
        manager = SimpleNamespace(**{name: mock.Mock() for name in (
            "event_timer_add", "event_timer_remove", "modal_handler_add", "progress_begin",
            "progress_update", "progress_end", "invoke_props_dialog")})
        context = SimpleNamespace(window=bpy.context.window_manager.windows[0],
                                  window_manager=manager, workspace=None, selected_objects=())
        fake = operator_self(refit_cls, name="", surfaces=[], start="", note="", confirm=False,
                             in_steps=False, report=lambda kind, text: None,
                             properties=SimpleNamespace(is_property_set=lambda name: False))
        reopened = mock.Mock()

        def dialog_steps(recorder: Recorder) -> None:
            with mock.patch.object(self.des_ops, "_invoke_later", reopened):
                if recorder.call("Intro: abrir el ajuste sin acierto", refit_cls.invoke, fake,
                                 context, None) != {"RUNNING_MODAL"}:
                    raise AssertionError("el ajuste sin acierto no comprueba antes")
                for event in range(pc.MAX_EVENTS):
                    state = recorder.call(f"evento {event + 1} del modal", steps_modal.modal,
                                          fake, context, pd.TIMER)
                    if state != {"RUNNING_MODAL"}:
                        return
            raise AssertionError("la comprobación antes de abrir el ajuste no acaba")

        precheck = measure("abrir el ajuste sin acierto", dialog_steps)
        manager.invoke_props_dialog.assert_not_called()
        reopened.assert_called_once()
        reopened_rows = {row["name"]: row["outside"]
                         for row in reopened.call_args.kwargs["surfaces"]}
        self.assertTrue(reopened_rows[exploitation] and reopened_rows[final])
        report(f"RNF-014-02 (T35, sin acierto): abrir «Ajustar el diseño a un límite nuevo…» "
               f"comprueba antes por pasos ({MACHINE}), "
               f"{pd.calls_line(precheck, where, network_waits=False)}")

        name = "Ajuste de escala"
        form = {"name": name, "start": self.built.start,
                "surfaces": [surface_row(exploitation), surface_row(final)]}
        run = measure("ajuste", chain(REFIT, form, "ajuste"))
        self.assertEqual(len(self.done(REFIT_TYPE, name)), 1)
        volumes = {label: value for label, value in self.figures_of(REFIT_TYPE, name).items()
                   if label.startswith("des.refit_m3")}
        self.assertEqual(len(volumes), 2, volumes)
        self.report_run(f"«Ajustar el diseño a un límite nuevo…» de las dos superficies de la "
                        f"cantera ({number(sum(volumes.values()), 0)} m³ de ajuste)", run)
        warn_slow(compiled, "compilar")
        warn_slow(background, "la ficha sin acierto")
        warn_slow(precheck, "abrir el ajuste sin acierto")
        slow = [(what, found) for what, found in (("abrir el ajuste", opened),
                                                  ("la ficha de la barra N", card))
                if found.seconds > CALL_BUDGET_S]
        if slow:
            report("Aviso RNF-014-02 (con acierto; con el equipo cargado se repite en reposo): "
                   + "; ".join(f"{what} {ms(found.seconds)} ms de pared y {ms(found.cpu)} de CPU"
                               for what, found in slow))
        self.check_run(run, "ajuste")
        for where, measured in (("compilar", compiled), ("la ficha sin acierto", background),
                                ("abrir el ajuste sin acierto", precheck)):
            self.assertLessEqual(measured.worst_cpu.budgeted_cpu, CALL_BUDGET_S,
                                 f"{where}: {measured.worst_cpu.text()}")
        for what, found in (("abrir el ajuste", opened), ("la ficha de la barra N", card)):
            self.assertLessEqual(found.cpu, CALL_BUDGET_S, what)
        self.assertLessEqual(keys.seconds, KEY_BUDGET_S, "la clave de la caché")


# --- En la red -----------------------------------------------------------------------------------


@requires(network.NET, network.NET_HINT)
class NetworkTest(_Case):
    """RNF-014-01 y RNF-014-02 con el proyecto en la carpeta de pruebas de la red (``Z:``): un
    proyecto propio en una subcarpeta temporal (borrada al terminar) y los datos de usuario en disco
    local; al terminar, vuelve el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ps.close()
        cls.addClassCleanup(_LOCAL.restore)  # lo último: los de la clase, al revés
        remote = cls.enterClassContext(network.net_tmp("gb-014-t35-"))
        cls.addClassCleanup(cls.ps.close)  # lo primero: antes de borrar su carpeta
        cls.remote = remote
        cls.built = build(remote / "proyectos", 2)

    def test_quarry_on_the_network(self) -> None:
        """RNF-014-01 y RNF-014-02 en ``Z:`` (como RNF-013-03 y RNF-013-07): «Cantera con dos
        superficies…» (como la b de :class:`CallsTest`, sin las 500 restricciones) con el proyecto
        en la red, de «Calcular» a las cifras registradas por «Crear», con la escritura de las cinco
        rejillas con su hash, las dos tablas y la transacción final, en ≤ 40 s (con los 50 ms del
        temporizador del modal); lo que hace Geoblender en cada llamada del hilo de Blender, sin sus
        esperas de la red (medidas en la llamada y anotadas aparte, sin presupuesto) ni la
        transacción final (aparte), no pasa de 0,2 s de CPU."""
        built = self.built
        project = self.ps.current()
        self.assertTrue(project.is_network, "el proyecto de la carpeta de la red")
        name = "Cantera en la red"
        pick_profiles()
        with netwaits.NetworkWaits(self.remote, projects=[project]) as waits:
            run = measure("cantera en la red", chain(QUARRY, quarry_form(built, name), "cantera"),
                          waits)
            longest = waits.longest
        self.assertEqual(len(self.done(QUARRY_TYPE, name)), 1)
        where = "con el proyecto en la carpeta de pruebas de la red"
        report(f"RNF-014-01 y RNF-014-02: «Cantera con dos superficies…» sobre {count(CELLS)} "
               f"celdas de 1 m y {ddata.SECTORS} sectores ({MACHINE}): "
               f"{number(run.with_modal_waits, 2)} s con los 50 ms del temporizador del modal "
               f"({number(run.seconds, 2)} s de trabajo) frente a "
               f"{number(QUARRY_NETWORK_BUDGET_S, 0)} s; "
               f"{pd.calls_line(run, where, network_waits=True)}; la espera de la red más larga, "
               f"{longest[0]} {ms(longest[1])} ms; {free_space(built.root)}")
        warn_slow(run, where)
        waited = [call for call in run.calls if call.seconds > CALL_BUDGET_S >= call.own]
        if waited:
            report(f"Nota RNF-014-02 ({where}): {len(waited)} llamadas de más de "
                   f"{number(CALL_BUDGET_S, 1)} s solo por sus esperas de la red (se anotan, sin "
                   "presupuesto): " + "; ".join(f"{ms(call.seconds)} ms ({call.text()})"
                                                for call in waited))
        self.assertLessEqual(run.worst_cpu.budgeted_cpu, CALL_BUDGET_S, run.worst_cpu.text())
        self.assertLessEqual(run.with_modal_waits, QUARRY_NETWORK_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
