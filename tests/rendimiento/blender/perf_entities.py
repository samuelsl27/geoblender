# SPDX-License-Identifier: GPL-3.0-or-later
"""Las entidades de diseño dentro de Blender (spec 015, T33; RNF-015-03, RNF-015-05 y RNF-015-06; plan 015 §7.3 y
el riesgo R4 de la 012, ``tests/rendimiento/blender``), con la forma de ``perf_quarry.py`` de la 014, cuyas
piezas usa: el proyecto de escala, el registro de cada llamada del hilo de Blender y los eventos del modal.

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py -- --carpeta
tests/rendimiento/blender --patron "perf_entities.py"``). Cada prueba imprime su cifra en una línea
«RNF-015-nn: …» con el equipo y el espacio libre del disco, y la compara con su presupuesto, sin relajarlo.

**Datos** (plan 013 §2.2 y plan 015 §7.1; se generan aquí con las semillas de ``tests/support/design_data.py`` y
``constraints_data.py`` y las geometrías de ``tests/support/entity_data.py``, no se versionan y se borran al
terminar): el proyecto de escala de ``perf_design.py`` (EPSG:25830 + EPSG:5782, V01 y V02, la rejilla de 1.654 ×
1.699 celdas de 1 m —2,81 M—, el límite legal y el perímetro de las restricciones de la 012 (:data:`CONSTRAINTS`:
sin las otras 498, que cubren casi todo el perímetro con zonas que no se cortan y no dejan sitio a una
plataforma; redibujados sobre todo el dominio con ``core.edit_constraints``), los 20 sectores con
su búsqueda de intocables cerrada, el terreno y las semillas en anillo como rejillas del proyecto, los diez
perfiles de banco, los dos taludes impuestos y las máscaras de V01 al día) con la capa de líneas de plataformas
de escala (:data:`edata.LAYER`: la grande, de 10 ha, y las veinte de ≤ 1 ha de la cadena). Todo con la extensión
habilitada, como una persona.

- **RNF-015-03** (:class:`CallsTest`, en el orden de sus letras sobre el mismo estado): las órdenes de las
  entidades, las reales, como desde la interfaz: Intro (``execute`` por ``bpy.ops``, en pasos), cada evento del
  temporizador de su modal hasta que termina (con el tic de los indicadores de la procedencia cuando le toca) y
  «Crear» (la misma orden con ``confirm``), que encadena lo que sigue a cada entidad (``after_entity_change``: la
  declaración de las restricciones que protegen, las máscaras de la 012 y la capa de entidades), con sus pasos
  y sus eventos. Cada llamada del hilo de Blender se mide: lo que hace Geoblender en ella, **sin la transacción
  final** (``DesignWriter.commit`` y ``MaskWriter.commit``: la operación, los temporales movidos, las tablas y las
  cifras en una transacción que no se trocea; el R4 de la 012), ≤ 0,2 s; la transacción, medida aparte, se anota
  con la llamada en que ocurre (si pasa de 0,2 s, con un aviso: la cifra, para Samuel). (a) «Plataforma…» seis
  veces (las seis primeras de la cadena, «en corte» y protegidas, cada una de la superficie de la anterior, con su
  declaración, la compilación de las máscaras y la capa de entidades al crearlas); (b) «Plataforma…» la grande
  (10 ha, «en corte y relleno», distancia euclídea exacta); (c) «Recalcular lo obsoleto» tras cambiar la cota de la
  primera (las siete plataformas, la declaración y la capa de entidades, con la cola de ``des`` y los pasos de las
  demás colas, que en ``blender -b`` no corren solas). **Cada llamada se mide en CPU del proceso**
  (``time.process_time()``, que no cuenta lo que gastan otros programas: ``docs/trampas.md`` §4) **y en pared**; el
  presupuesto se exige a la CPU y la pared se anota con un aviso si lo pasa (se repite con el equipo en reposo).
  La resolución del reloj de CPU de Windows es de unos 16 ms.
- **RNF-015-05** (:meth:`CallsTest.test_d_esc`): Esc a mitad de cada cálculo —«Calcular» (a mitad de sus eventos
  y en cuanto tiene su superficie en el temporal), lo que encadena crear la entidad y «Recalcular lo obsoleto»—:
  la llamada más larga del cálculo más lo que tarda Esc ≤ 2 s y nada a medias en el proyecto (ni operación «en
  curso», ni temporal; «Calcular» no deja ni operación, ni dato, ni cifra, ni fichero).
- **RNF-015-06** (:meth:`CallsTest.test_e_the_preview_with_200_entities`): con **200 entidades** en la versión
  (las de verdad —la cadena, la grande y la de Esc— y las demás hasta 200, que se apoyan en la primera, con sus
  huellas), activar la vista previa de la primera (``geoblender.des_entity_preview``: la orden y los pasos de su
  temporizador hasta que está construida, con los 5 ms de espera de cada uno) ≤ 1 s y cada redibujo (los lotes, los nombres, la leyenda y el resumen, con ``gpu`` y
  ``blf`` sustituidos: solo el Python de Geoblender, la GPU de verdad es de la comprobación manual M4) ≤ 5 ms.
- **En la red** (:class:`NetworkTest`; recurso «red» de ``tests.support.network``: con
  ``GEOBLENDER_NET_TEST_DIR``, a mano; sin ella, se omite): lo de RNF-015-03 con el proyecto en una subcarpeta
  temporal propia de la carpeta de pruebas de ``Z:`` (borrada al terminar) y los datos de usuario en disco local: «Plataforma…» la grande y una de la cadena con sus esperas de la red de cada
  llamada, medidas con ``tests.support.netwaits`` y anotadas aparte, sin presupuesto (como RNF-014-02). **Ojo**: en
  el PC de referencia la variable está definida en el usuario y este módulo, lanzado tal cual, también corre la de
  la red (``docs/trampas.md`` §7); para medir solo en local, sin ella: ``env -u GEOBLENDER_NET_TEST_DIR …`` (Git
  Bash) o ``Remove-Item Env:GEOBLENDER_NET_TEST_DIR`` (PowerShell).

En ``blender -b`` no corren ni el bucle de eventos ni los temporizadores: la prueba hace de ventana (un evento del
temporizador del modal cada vez) y de temporizador (las colas de pasos); la confirmación de «Calcular»
(``_ask_confirmation``, que relanza la orden con un temporizador) se sustituye.
"""

from __future__ import annotations

import dataclasses
import gc
import importlib
import statistics
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np
from mathutils import Matrix

from tests.rendimiento.blender import perf_constraints as pc
from tests.rendimiento.blender import perf_design as pd
from tests.rendimiento.blender import perf_quarry as pq
from tests.support import blender_ext, netwaits, network
from tests.support import constraints_data as cdata
from tests.support import design_data as ddata
from tests.support import entity_data as edata
from tests.support import entity_synthetic
from tests.support.blender_ext import module_name
from tests.support.resources import requires
from tests.support.trees import remove_tree

CALL_BUDGET_S = 0.2  # RNF-015-03: lo que hace Geoblender en cada llamada del hilo de Blender
ESC_BUDGET_S = 2.0  # RNF-015-05: Esc a mitad de cualquier cálculo
ACTIVATE_BUDGET_S = 1.0  # RNF-015-06: activar la vista previa con 200 entidades
REDRAW_BUDGET_S = 0.005  # RNF-015-06: cada redibujo
ACTIVATIONS = 5  # veces que se activa (la mediana cuenta; la peor se anota)
REDRAWS = 120  # redibujos medidos
ENTITIES = edata.SYNTHETIC_ENTITIES
CONSTRAINTS = 2  # el límite legal y el perímetro de actuación de §2.2
ORDERED = 6  # las plataformas de la cadena que se crean con la orden (las veinte son de la prueba del núcleo)
TICK_WAIT_S = 0.005  # bl.draw.entity.TICK_INTERVAL_S (lo comprueba la prueba)
REGION = (1920.0, 1080.0)
LAYERS_TYPE = "gis.perf_entities_layers"
"""El tipo de operación con que se escribe la capa de la prueba (como la importación de la 006)."""
PLATFORM = "geoblender.des_create_platform"
PREVIEW = "geoblender.des_entity_preview"
RECOMPUTE = "geoblender.core_recompute_stale"
PLATFORM_TYPE = "des.platform"
FIRST_PARAM = "start_level_m"
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")

report = pd.report
number = pd.number
ms = pd.ms
count = pd.count
free_space = pd.free_space
MACHINE = pd.MACHINE
CELLS = pd.CELLS
Built = pd.Built


def _module(name: str) -> ModuleType:
    """El módulo ``name`` de la copia de pruebas de la extensión."""
    return importlib.import_module(f"{module_name()}.{name}")


class _NoClock:
    """El reloj que pide ``entity_synthetic`` (``advance``): el proyecto tiene el suyo, de verdad."""

    def advance(self, **_ignored: float) -> None:
        return None


# --- El proyecto de escala con la capa de plataformas --------------------------------------------


def write_axes_layer(project: Any) -> None:
    """La capa de líneas :data:`edata.LAYER` con la plataforma grande y las veinte de la cadena (``nombre``, ``ancho``,
    ``cota_inicial`` y ``pendiente``), como la deja la importación de la 006."""
    gis_store, vector = _module("gis.store"), _module("gis.vector")
    datasets, builtin = _module("core.datasets"), _module("core.content.builtin")
    arrays = edata.layer_arrays()
    srs = int(project.record.crs_epsg)
    fields = ("ancho", "cota_inicial", "pendiente")
    columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
               *(vector.FieldColumn(field, field, "DOUBLE") for field in fields))
    values = {"nombre": arrays.names, "ancho": arrays.widths, "cota_inicial": arrays.levels,
              "pendiente": arrays.gradients}
    parts = tuple(((path,),) for path in arrays.paths)
    layer = vector.FeatureLayer("line", tuple(range(1, len(arrays.names) + 1)), parts, columns, values)
    rows = gis_store.feature_rows(layer, srs)
    names = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
    marks = ", ".join("?" for _ in range(len(columns) + 2))
    name = edata.LAYER
    handle = _module("core.provenance.operations").begin_operation(
        project, LAYERS_TYPE, settings={"name": name}, executor="blender")
    with project.write_transaction() as conn:
        conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                     f"geom {layer.geometry_type}, {names})")
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) "
                     "VALUES (?, 'features', ?, '', ?)", (name, name, srs))
        conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, "
                     "srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)", (name, layer.geometry_type, srs))
        conn.executemany(f'INSERT INTO "{name}" VALUES ({marks})', rows)
        handle.complete(conn, outputs=(datasets.DatasetSpec(
            name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features",
            crs_epsg=srs, input_uid=None, immutable=False),), message="Capa de rendimiento de las entidades")


def widen_constraints(project: Any) -> None:
    """El límite legal y el perímetro de actuación de las dos restricciones de §2.2 (``constraints_data``), que son
    estrellas de unos 640 y 760 m de radio, redibujados como los de ``design_perf`` (la ventana entera menos 10 m
    el perímetro y 5 m el límite) con ``core.edit_constraints``, como lo haría la persona: las plataformas de escala
    caben en todo el dominio y no en un círculo. Las máscaras de V01 quedan obsoletas."""
    cstore, cprov = _module("core.constraints.store"), _module("core.constraints.provenance")
    west, south, east, north = cdata.window()
    margins = {"Concesión": ddata.MARGIN_M / 2.0, "Perímetro": ddata.MARGIN_M}
    with project.read() as conn:
        found = [item for item in cstore.read_constraints(conn) if item.name in margins]
    assert len(found) == len(margins), [item.name for item in found]
    rows = []
    for item in found:
        margin = margins[item.name]
        rows.append(dataclasses.replace(item, parts=((pd._ring(west + margin, south + margin, east - margin,
                                                              north - margin),),)))
    cprov.edit_constraints(project, rows, srs_id=project.record.crs_epsg)


def refresh(project: Any) -> None:
    """Las listas de los diálogos (perfiles, sectores, superficies, capas y plataformas), leídas de nuevo (un guion
    no abre el diálogo que las lee)."""
    pd.refresh_lists(project)
    _module("bl.ui.des_panels").refresh_platform_choices(project)


def build(parent: Path) -> pd.Built:
    """El proyecto de escala de ``perf_design.build`` con el límite legal y el perímetro de §2.2 (:data:`CONSTRAINTS`:
    sin las otras 498, que cubren casi todo el perímetro con zonas que no se cortan y no dejan sitio a una
    plataforma) redibujados sobre todo el dominio (:func:`widen_constraints`), en ``parent``, con la capa de
    plataformas de escala, abierto en la sesión con V01 activa y sus máscaras al día."""
    built = pd.build(parent, CONSTRAINTS)
    project = _module("bl.scene.project_session").current()
    widen_constraints(project)
    write_axes_layer(project)
    pc.ensure_masks(project, built)
    refresh(project)
    return built


class _Local:
    """El proyecto de escala en disco local, uno para todo el módulo (se construye la primera vez que se pide), en
    la sesión."""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.made: pd.Built | None = None

    def built(self) -> pd.Built:
        """El proyecto, abierto en la sesión (construido, si aún no lo está)."""
        if self.made is None:
            self.folder = Path(tempfile.mkdtemp(prefix="gb-015-t33-"))
            self.made = build(self.folder / "proyectos")
        elif _module("bl.scene.project_session").current() is None:
            pd.base.reopen(self.made)
            refresh(_module("bl.scene.project_session").current())
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
        _module("bl.draw.entity").disable()
        _module("bl.draw.design").disable()
        _module("bl.scene.project_session").close()
        _LOCAL.close()
        _module("core.provenance.contract").unregister_operation(LAYERS_TYPE)
    finally:
        blender_ext.load_file()
        blender_ext.release()


# --- Las llamadas del hilo de Blender ------------------------------------------------------------

Recorder = pq.Recorder
measure = pq.measure


def warn_slow(run: pd.Run, where: str) -> None:
    """Los avisos de lo que pasa de 0,2 s: lo que no es la transacción final en pared (se repite en reposo; el
    presupuesto se exige a la CPU) y la transacción final (para Samuel, R4)."""
    over = [call for call in run.calls if call.budgeted > CALL_BUDGET_S]
    if over:
        report(f"Aviso RNF-015-03 ({where}): {len(over)} llamadas de más de {number(CALL_BUDGET_S, 1)} s de "
               f"pared sin la transacción final (con el equipo cargado por otros programas se repite en "
               f"reposo; el presupuesto se exige a la CPU): "
               + "; ".join(f"{ms(call.budgeted)} ms de pared y {ms(call.budgeted_cpu)} de CPU ({call.text()})"
                           for call in over))
    long = [(op, seconds - waited) for call in run.with_commits
            for op, seconds, _cpu, waited in call.commits if seconds - waited > CALL_BUDGET_S]
    if long:
        report(f"Aviso RNF-015-03 ({where}; R4 de la 012, la cifra para Samuel): la transacción final pasa de "
               f"{number(CALL_BUDGET_S, 1)} s: " + "; ".join(f"{op} {ms(seconds)} ms" for op, seconds in long))


def platform_form(name: str, feature: str, start: str, **changes: Any) -> dict[str, Any]:
    """Lo pedido en el diálogo de «Plataforma…» para la plataforma ``feature`` de la capa de escala sobre ``start``."""
    form: dict[str, Any] = {"name": name, "layer": edata.LAYER, "feature": feature, "start": start,
                            "edge_angle": f"{edata.EDGE_ANGLE_DEG:g}", "metric": "EXACT"}
    form.update(changes)
    return form


def chain_form(index: int, built: pd.Built) -> dict[str, Any]:
    """La plataforma ``index`` (0 a 19) de la cadena: «en corte», protegida, partiendo del terreno o de la superficie
    de la anterior (``PLT-00n``, el código que le toca en una versión que solo tiene las de la cadena)."""
    start = built.start if index == 0 else f"entity:PLT-{index:03d}"
    return platform_form(edata.chain_name(index), edata.chain_name(index), start, mode="CUT", protect=True,
                         guard=f"{edata.CHAIN_GUARD_M:g}", reach=f"{edata.CHAIN_REACH_M:g}")


def big_form(start: str) -> dict[str, Any]:
    """La plataforma grande: «en corte y relleno», sin proteger, sobre ``start``."""
    return platform_form("Plataforma grande", edata.BIG_NAME, start, mode="CUT_FILL",
                         reach=f"{edata.BIG_REACH_M:g}")


def create_platform(recorder: Recorder, what: str) -> None:
    """«Crear» la plataforma del cálculo abierto (la misma orden con ``confirm``: la transacción final) y lo que
    encadena (``after_entity_change``: la declaración, las máscaras y la capa de entidades), con cada evento de su
    modal hasta que termina."""
    cls = _module("bl.ui.commands").registered_class(PLATFORM)
    result = recorder.call(f"Crear ({what})", bpy.ops.geoblender.des_create_platform, "EXEC_DEFAULT",
                           confirm=True, in_steps=True)
    if result != {"RUNNING_MODAL"}:
        raise AssertionError(f"«{what}» no se crea o no encadena lo que sigue: {result}")
    state = pd.pump(recorder, pc.running(cls), f"{what}: lo que sigue a crearla")
    if state != {"FINISHED"}:
        raise AssertionError(f"«{what}»: lo que sigue a crearla acaba mal: {state}")


def platform_run(form: dict[str, Any], what: str, project: Any, waits: netwaits.NetworkWaits | None = None
                 ) -> pd.Run:
    """«Plataforma…»: abrir el diálogo (las listas de capas y de superficies, que ``invoke`` lee), «Calcular» (Intro y
    cada evento de su modal) y «Crear» con lo que encadena, cada llamada del hilo de Blender medida."""
    panels = _module("bl.ui.des_panels")

    def steps(recorder: Recorder) -> None:
        recorder.call(f"abrir el diálogo ({what})", lambda: (panels.refresh_choices(project),
                                                              panels.refresh_platform_choices(project)))
        pq.calculate(recorder, PLATFORM, form, what)
        create_platform(recorder, what)

    return measure(what, steps, waits)


# --- Esc ----------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Stopped:
    """Esc a mitad de un cálculo: dónde (los eventos que llevaba y de qué fases), lo que tardó la llamada más larga
    antes de Esc (pared y CPU) y lo que tardó Esc (pared y CPU, hasta que el modal acabó)."""

    where: str
    events: int
    longest: tuple[float, float]
    esc: tuple[float, float]
    temporaries: int
    calls: int = 1

    @property
    def wall(self) -> float:
        """Lo que tarda Esc en el peor caso: la llamada más larga del cálculo más cerrar los pasos."""
        return self.longest[0] + self.esc[0]

    def text(self) -> str:
        return (f"{self.where} {ms(self.wall)} ms de pared (la llamada más larga {ms(self.longest[0])} ms más "
                f"Esc {ms(self.esc[0])} ms, en {self.calls} llamadas, a los {self.events} eventos, "
                f"temporales: {self.temporaries})")


def _timed_call(function: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, float, float]:
    """``function(*args, **kwargs)`` y lo que tardó, en pared y en CPU del proceso."""
    started, cpu = time.perf_counter(), time.process_time()
    found = function(*args, **kwargs)
    return found, time.perf_counter() - started, time.process_time() - cpu


class _Case(pq._Case):
    """La extensión habilitada, el idioma en español y el proyecto de escala en disco local, el del módulo."""

    def project(self) -> Any:
        return self.ps.current()

    def refresh(self) -> None:
        refresh(self.project())

    def tmp_files(self) -> list[str]:
        """Los ficheros temporales de la carpeta del proyecto (los de las rejillas que esperan a «Crear»)."""
        root = Path(self.project().root)
        return sorted(str(path.relative_to(root)) for path in root.rglob("*")
                      if path.is_file() and ".tmp" in path.name)

    def state(self) -> dict[str, Any]:
        """Todo lo que podría escribir un cálculo: las operaciones, los datos, las cifras, los parámetros y los
        ficheros del proyecto (sin el diario de la base)."""
        root = Path(self.project().root)
        return {
            "operations": self.rows("SELECT uid, op_type, status FROM gb_operation ORDER BY fid"),
            "datasets": self.rows("SELECT name, status, content_sha256 FROM gb_dataset ORDER BY name"),
            "figures": self.rows("SELECT count(*) FROM gb_figure"),
            "parameters": self.rows("SELECT count(*) FROM gb_parameter"),
            "files": sorted(str(path.relative_to(root)) for path in root.rglob("*")
                            if path.is_file() and path.suffix != ".gpkg-journal")}

    def assert_nothing_half_done(self, where: str) -> None:
        """Ninguna operación «en curso» ni temporal en el proyecto (lo que una entidad ya creada y lo que ya se
        recalculó dejan es completo: cada operación es una transacción)."""
        self.assertEqual(self.rows("SELECT uid FROM gb_operation WHERE status = 'running'"), [],
                         f"{where}: una operación en curso")
        self.assertEqual(self.tmp_files(), [], f"{where}: un temporal")


# --- RNF-015-03, RNF-015-05 y RNF-015-06: calcular, crear y recalcular con las órdenes reales ------


class CallsTest(_Case):
    """RNF-015-03 y RNF-015-05 con el proyecto de escala en disco local, en el orden de sus letras sobre el mismo
    estado: las plataformas de la a las usa la b (parte de la última de la cadena), la c (recalcular), la d (Esc) y
    la e (las 200 entidades)."""

    built: pd.Built
    runs: list[pd.Run]
    calc_events: int
    chain_events: int

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.built = _LOCAL.built()
        cls.des_ops = _module("bl.ops.des")
        cls.core_ops = _module("bl.ops.core_provenance")
        cls.gis_ops = _module("bl.ops.gis")
        cls.res_ops = _module("bl.ops.res")

    def report_runs(self, text: str, runs: list[pd.Run], rnf: str = "RNF-015-03") -> pd.Run:
        """La línea de cifra de unas ejecuciones de «Plataforma…» (la peor, con sus llamadas más largas) y el
        presupuesto: lo que hace Geoblender en cada llamada, sin la transacción final, en CPU."""
        built = self.built
        worst = max(runs, key=lambda run: run.worst_cpu.budgeted_cpu)
        calls = sum(len(run.calls) for run in runs)
        seconds = sum(run.seconds for run in runs)
        events = sum(run.events for run in runs)
        report(f"{rnf}: {text} con {built.constraints} restricciones ({count(built.vertices)} vértices), "
               f"{count(CELLS)} celdas de 1 m y {len(runs)} {'ejecución' if len(runs) == 1 else 'ejecuciones'} "
               f"({count(calls)} llamadas del hilo de Blender en total, {count(events)} eventos del modal, "
               f"{number(seconds, 1)} s; {MACHINE}); la peor ejecución, "
               f"{pd.calls_line(worst, f'«{worst.label}», con el proyecto en disco local', network_waits=False)}"
               f"; {free_space(built.root)}")
        for run in runs:
            warn_slow(run, run.label)
        return worst

    def check_runs(self, runs: list[pd.Run]) -> None:
        for run in runs:
            worst = run.worst_cpu
            self.assertLessEqual(worst.budgeted_cpu, CALL_BUDGET_S, f"{run.label}: {worst.text()}")

    def test_a_platforms_of_the_chain(self) -> None:
        """RNF-015-03 (plan 015 §7.3; RF-015-29, RF-015-10, RF-012-06): «Plataforma…» seis veces —las seis primeras de
        la cadena, «en corte», protegidas con 5 m y con 40 m de alcance, cada una de la superficie de la anterior—
        sobre 2,81 M celdas con el límite legal y el perímetro de la 012, como desde la interfaz: en ninguna llamada del hilo
        de Blender (abrir el diálogo, Intro, cada evento del modal de «Calcular», el tic de los indicadores,
        «Crear» y cada evento de lo que encadena —la declaración, la compilación de las máscaras y la capa de
        entidades—) lo que hace Geoblender sin la transacción final pasa de 0,2 s de CPU; la transacción final,
        aparte."""
        project = self.project()
        runs = []
        for index in range(ORDERED):
            self.refresh()
            runs.append(platform_run(chain_form(index, self.built), f"Plataforma {index + 1:02d}", project))
        self.assertEqual(len(self.done(PLATFORM_TYPE, edata.chain_name(ORDERED - 1))), 1)
        entities = _module("design.entities")
        registry = entities.registry(project, self.built.version_uid)
        self.assertEqual([entry.record.code for entry in registry],
                         [f"PLT-{number_:03d}" for number_ in range(1, ORDERED + 1)])
        first = runs[0]
        cut = [call for call in first.calls if call.what.startswith("Crear")]
        self.assertTrue(cut, "sin «Crear»")
        CallsTest.calc_events = first.calls.index(cut[0])
        CallsTest.chain_events = len(first.calls) - first.calls.index(cut[0]) - 1
        self.assertGreater(CallsTest.chain_events, 3, "«Crear» no encadena lo que sigue")
        CallsTest.runs = runs
        self.report_runs(f"«Plataforma…» {ORDERED} veces (las primeras de la cadena: «en corte», protegidas, de "
                         f"la superficie de la anterior; con la declaración, las máscaras y la capa de entidades "
                         f"al crear cada una)", runs)
        self.check_runs(runs)

    def test_b_the_big_platform(self) -> None:
        """RNF-015-03 (plan 015 §7.3; RF-015-29): «Plataforma…» la grande —10 ha, «en corte y relleno», con la
        distancia euclídea exacta y 150 m de alcance, de la superficie de la última de la cadena— «Calcular» y
        «Crear» con lo que encadena: en ninguna llamada sin la transacción final pasa de 0,2 s de CPU."""
        self.refresh()
        run = platform_run(big_form(f"entity:PLT-{ORDERED:03d}"), "Plataforma grande", self.project())
        self.assertEqual(len(self.done(PLATFORM_TYPE, "Plataforma grande")), 1)
        cut = self.total(PLATFORM_TYPE, "Plataforma grande", "des.plat_cut_m3")
        fill = self.total(PLATFORM_TYPE, "Plataforma grande", "des.plat_fill_m3")
        self.assertGreater(cut + fill, 0.0, "la plataforma no mueve nada: no mide nada")
        self.report_runs(f"«Plataforma…» la grande (10 ha, «en corte y relleno», desmonte de la huella "
                         f"{number(cut, 0)} m³ y terraplén {number(fill, 0)} m³)", [run])
        self.check_runs([run])

    def recompute_run(self, label: str) -> tuple[pd.Run, Any]:
        """«Recalcular lo obsoleto» (``geoblender.core_recompute_stale``) como desde la interfaz: Intro, cada evento de
        su modal, con el tic de los indicadores y un paso de cada cola de pasos tras cada uno (las de ``des``, las
        máscaras de ``gis`` y la verificación de ``res``, cuyos temporizadores no corren en ``blender -b``), cada
        llamada medida; con su resultado (``RecomputeOutcome``)."""
        cls = self.core_ops.GEOBLENDER_OT_core_recompute_stale
        queues = (("cola de des", self.des_ops.des_tick), ("cola de las máscaras", self.gis_ops.masks_tick),
                  ("cola de la verificación", self.res_ops.res_tick))
        gc.collect()
        with Recorder() as recorder, mock.patch.object(self.des_ops, "_ask_confirmation") as ask, \
                mock.patch.object(_module("bl.ops.incorporation"), "status_text"):
            started = time.perf_counter()
            result = recorder.call("Intro: comprobar y empezar", bpy.ops.geoblender.core_recompute_stale,
                                   "EXEC_DEFAULT")
            if result != {"RUNNING_MODAL"}:
                raise AssertionError(f"«Recalcular lo obsoleto» no empieza: {result}")
            operator = pc.running(cls)
            state = pc.pump(recorder, operator, label, queues)
            seconds = time.perf_counter() - started
        if state != {"FINISHED"}:
            raise AssertionError(f"«{label}» acaba mal: {state}, {getattr(operator, 'report_log', [])}")
        ask.assert_not_called()
        return pd.Run(label, tuple(recorder.calls), seconds), operator.result

    def recompute_all(self, label: str) -> list[pd.Run]:
        """«Recalcular lo obsoleto» tantas veces como haga falta hasta que no queda nada obsoleto (lo recalculado
        que vuelve a quedar obsoleto espera a la siguiente pasada, RF-008-27: desde que una entidad protege, el
        ciclo entidad → declarada → máscaras → entidad, D-21, deja el eco de la declaración, las máscaras y la capa
        de entidades): cada pasada, medida."""
        runs = []
        for turn in range(1, 11):
            run, outcome = self.recompute_run(f"{label} (pasada {turn})")
            runs.append(run)
            if not outcome.remaining.units:
                return runs
        raise AssertionError(f"«{label}» no deja nada al día en 10 pasadas")

    def change_first(self, delta: float, code: str = "PLT-001") -> None:
        """Cambia la cota inicial de la plataforma ``code`` (por defecto, la primera de la cadena) en V01 en
        ``delta`` m."""
        project = self.project()
        params, dparams = _module("core.params"), _module("design.params")
        key = dparams.entity_key(code, FIRST_PARAM)
        store = params.ParameterStore(project)
        with project.read() as conn:
            current = float(store.get(key, version=self.built.version_uid, conn=conn).value)
        with project.write_transaction() as conn:
            store.change(conn, key, value=current + delta, version=self.built.version_uid,
                         reason="Medición de rendimiento (T33)")

    def test_c_recompute_the_chain(self) -> None:
        """RNF-015-03 (plan 015 §7.3; RF-015-16, RF-008-26): cambiar la cota de la primera plataforma deja obsoletas
        las siete (la superficie de cada una parte de la anterior), la declaración y la capa de entidades;
        «Recalcular lo obsoleto» las rehace en orden de dependencia, por pasos en la cola de ``des`` y con las
        máscaras de ``gis`` si hace falta: en ninguna llamada del hilo de Blender sin la transacción final pasa
        de 0,2 s de CPU."""
        self.change_first(-0.5)
        stale = self.rows("SELECT count(*) FROM gb_stale WHERE item_kind = 'operation'")[0][0]
        self.assertGreaterEqual(stale, ORDERED + 1, "cambiar la primera no dejó obsoleta la cadena")
        runs = self.recompute_all("recalcular la cadena")
        redone = sum(len([call for call in run.calls if call.what == "cola de des"]) for run in runs)
        self.report_runs(f"«Recalcular lo obsoleto» tras cambiar la cota de la primera de {ORDERED + 1} "
                         f"plataformas ({stale} elementos obsoletos; {len(runs)} pasadas hasta que no queda "
                         f"nada, {redone} pasos de la cola de ``des``)", runs)
        self.check_runs(runs)

    # --- Esc (RNF-015-05) ---------------------------------------------------------------------

    def esc_in_calculation(self, form: dict[str, Any], *, after_events: int | None, until_tmp: bool,
                           where: str) -> Stopped:
        """«Calcular» ``form`` hasta ``after_events`` eventos del modal (o, con ``until_tmp``, hasta que su
        superficie está en un temporal) y Esc: lo que tardó la llamada más larga hasta entonces y lo que tardó Esc;
        el cálculo no deja nada en el proyecto."""
        self.refresh()
        before = self.state()
        cls = _module("bl.ui.commands").registered_class(PLATFORM)
        longest = (0.0, 0.0)
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            result, wall, cpu = _timed_call(bpy.ops.geoblender.des_create_platform, "EXEC_DEFAULT",
                                            in_steps=True, **form)
            self.assertEqual(result, {"RUNNING_MODAL"}, f"{where}: no empieza")
            longest = max(longest, (wall, cpu), key=lambda call: call[1])
            operator = pc.running(cls)
            events = 0
            for events in range(1, pc.MAX_EVENTS):
                if after_events is not None and events > after_events:
                    break
                state, wall, cpu = _timed_call(operator.modal, bpy.context, pc.TIMER)
                self.assertEqual(state, {"RUNNING_MODAL"}, f"{where}: acabó antes de Esc (evento {events})")
                longest = max(longest, (wall, cpu), key=lambda call: call[1])
                if until_tmp and self.tmp_files():
                    break
            else:
                self.fail(f"{where}: no llega al momento de Esc")
            waiting = len(self.tmp_files())
            state, wall, cpu = _timed_call(operator.modal, bpy.context, ESCAPE)
        self.assertEqual(state, {"CANCELLED"}, where)
        self.assertIn("Cálculo cancelado: no queda nada a medias", operator.report_log)
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before, f"{where}: Esc dejó algo en el proyecto")
        return Stopped(where, events, longest, (wall, cpu), waiting)

    def esc_in_recompute(self, delta: float, des_ticks: int, code: str = "PLT-001") -> Stopped:
        """Cambia la cota de la plataforma ``code`` (``delta`` m), lanza «Recalcular lo obsoleto» y, tras ``des_ticks`` pasos de la
        cola de ``des`` (con 1 acaba de empezar su primera unidad: lo peor para Esc, que acaba la unidad en curso),
        pulsa Esc: lo que tardó la llamada más larga hasta entonces y lo que tardó el modal en acabar; lo hecho
        queda y lo demás sigue obsoleto, sin nada a medias. Al final lo deja todo al día."""
        self.change_first(delta, code)
        cls = self.core_ops.GEOBLENDER_OT_core_recompute_stale
        queues = (("cola de des", self.des_ops.des_tick), ("cola de las máscaras", self.gis_ops.masks_tick),
                  ("cola de la verificación", self.res_ops.res_tick))
        gc.collect()
        with Recorder() as recorder, mock.patch.object(self.des_ops, "_ask_confirmation"),                 mock.patch.object(_module("bl.ops.incorporation"), "status_text"):
            ticks = 0
            for _turn in range(5):
                # Una pasada puede acabar antes (lo recalculado que vuelve a quedar obsoleto espera a la
                # siguiente, RF-008-27): si pasa, otra pasada, hasta llegar a los pasos de ``des`` que se piden.
                self.assertEqual(recorder.call("Intro", bpy.ops.geoblender.core_recompute_stale, "EXEC_DEFAULT"),
                                 {"RUNNING_MODAL"})
                operator = pc.running(cls)
                finished = False
                while ticks < des_ticks:  # unas cuantas unidades hechas y otra en curso
                    state = recorder.call("evento del modal", operator.modal, bpy.context, pc.TIMER)
                    if state != {"RUNNING_MODAL"}:
                        finished = True
                        break
                    for name, tick in queues:
                        recorder.call(name, tick)
                        ticks += name == "cola de des"
                if not finished:
                    break
            else:
                self.fail(f"«Recalcular lo obsoleto» (cota {delta:+g}) no llega a {des_ticks} pasos de su cola")
            events = len(recorder.calls)
            longest = max(((call.seconds, call.cpu) for call in recorder.calls), key=lambda call: call[1])
            started, cpu = time.perf_counter(), time.process_time()
            state = operator.modal(bpy.context, ESCAPE)
            tail = 0
            while state == {"RUNNING_MODAL"}:  # acaba la unidad en curso, con su cola
                tail += 1
                for _name, tick in queues:
                    tick()
                state = operator.modal(bpy.context, pc.TIMER)
                self.assertLess(tail, pc.MAX_TICKS)
            wall, spent = time.perf_counter() - started, time.process_time() - cpu
        self.assertEqual(state, {"CANCELLED"})
        self.assertTrue(operator.result.cancelled)
        self.assertGreater(len(operator.result.remaining.units), 0, "Esc recalculó todo")
        self.assert_nothing_half_done("Esc a mitad de «Recalcular lo obsoleto»")
        self.recompute_all("terminar de recalcular")  # lo que falta, para dejar el estado al día
        return Stopped(f"«Recalcular lo obsoleto» de {code}, tras {des_ticks} "
                       f"{'paso' if des_ticks == 1 else 'pasos'} de su cola (acaba la unidad en curso)", events,
                       longest, (wall, spent), 0, calls=tail + 1)

    def test_d_esc(self) -> None:
        """RNF-015-05 (plan 015 §7.3; RF-015-29): Esc a mitad de cada cálculo de las entidades —«Calcular» una
        plataforma (a la mitad de sus eventos y, otra vez, en cuanto su superficie está en el temporal), lo que
        encadena crearla (a la mitad de sus eventos) y «Recalcular lo obsoleto» (a la mitad)—: la llamada más
        larga del cálculo más lo que tarda Esc ≤ 2 s y nada a medias en el proyecto: «Calcular» no deja ni
        operación, ni dato, ni cifra, ni fichero, y lo demás, ni operación «en curso» ni temporal."""
        index = ORDERED + 1  # la plataforma 08 de la capa (la grande es PLT-007): cada superficie, una entidad
        form = chain_form(index, self.built)
        form["start"] = f"entity:PLT-{ORDERED + 1:03d}"
        stops = [
            self.esc_in_calculation(form, after_events=max(1, self.calc_events // 2), until_tmp=False,
                                    where="«Calcular», a mitad de sus eventos"),
            self.esc_in_calculation(form, after_events=None, until_tmp=True,
                                    where="«Calcular», con su superficie ya en el temporal")]
        self.assertGreater(stops[1].temporaries, 0, "«Calcular» no llegó a escribir su temporal")

        # Esc a mitad de lo que encadena crear la plataforma: ya está creada (cada etapa, su transacción).
        self.refresh()
        cls = _module("bl.ui.commands").registered_class(PLATFORM)
        with mock.patch.object(self.des_ops, "_ask_confirmation"):
            self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", in_steps=True, **form),
                             {"RUNNING_MODAL"})
            operator = pc.running(cls)
            self.assertEqual(pd.pump(Recorder(), operator, "Calcular para crear"), {"FINISHED"})
        longest = (0.0, 0.0)
        result, wall, cpu = _timed_call(bpy.ops.geoblender.des_create_platform, "EXEC_DEFAULT", confirm=True,
                                        in_steps=True)
        self.assertEqual(result, {"RUNNING_MODAL"})
        longest = max(longest, (wall, cpu), key=lambda call: call[1])
        operator = pc.running(cls)
        events = 0
        for events in range(1, max(2, self.chain_events // 2) + 1):
            state, wall, cpu = _timed_call(operator.modal, bpy.context, pc.TIMER)
            self.assertEqual(state, {"RUNNING_MODAL"}, "lo que encadena acabó antes de Esc")
            longest = max(longest, (wall, cpu), key=lambda call: call[1])
        state, wall, cpu = _timed_call(operator.modal, bpy.context, ESCAPE)
        self.assertIn(state, ({"CANCELLED"}, {"FINISHED"}))
        self.assertEqual(len(self.done(PLATFORM_TYPE, form["name"])), 1, "la plataforma ya estaba creada")
        self.assert_nothing_half_done("Esc a mitad de lo que encadena crear la plataforma")
        stops.append(Stopped("lo que encadena crear la plataforma, a mitad de sus eventos", events, longest,
                             (wall, cpu), 0))

        # Esc a mitad de «Recalcular lo obsoleto»: acaba la unidad en curso (lo hecho queda; lo demás, obsoleto).
        big = f"PLT-{ORDERED + 1:03d}"  # la grande: la unidad más larga del recálculo
        for delta, ticks, code in ((+0.5, 1, "PLT-001"), (-0.5, 12, "PLT-001"), (+0.5, 1, big), (-0.5, 12, big)):
            stops.append(self.esc_in_recompute(delta, ticks, code))

        worst = max(stops, key=lambda stop: stop.wall)
        report(f"RNF-015-05: Esc a mitad de cada cálculo de las entidades sobre {count(CELLS)} celdas con "
               f"{self.built.constraints} restricciones (la llamada más larga más lo que tarda Esc; nada queda a "
               f"medias en el proyecto; {MACHINE}): " + "; ".join(stop.text() for stop in stops)
               + f"; presupuesto {number(ESC_BUDGET_S, 0)} s; {free_space(self.built.root)}")
        self.assertLessEqual(worst.wall, ESC_BUDGET_S, worst.text())

    # --- La vista previa con 200 entidades (RNF-015-06) -----------------------------------------

    def activate(self) -> tuple[float, float, int, Any]:
        """Pulsa «Vista previa» de la primera entidad (``geoblender.des_entity_preview``) y da los pasos del
        temporizador hasta que está construida (en ``blender -b`` no corren): lo que tardó hasta entonces con los
        5 ms de espera de cada paso, su CPU, los pasos y lo construido."""
        entity = self.entity
        self.assertFalse(entity.enabled())
        gc.collect()
        started, cpu = time.perf_counter(), time.process_time()
        result = bpy.ops.geoblender.des_entity_preview("EXEC_DEFAULT", entity="PLT-001")
        self.assertEqual(result, {"FINISHED"})
        ticks = 0
        for _ in range(pc.MAX_TICKS):
            ticks += 1
            if entity.tick() is None:
                break
        else:
            self.fail("la vista previa no acaba de construirse")
        wall = time.perf_counter() - started + TICK_WAIT_S * max(0, ticks - 1)
        built = entity.built()
        self.assertIsNotNone(built, "la vista previa no construyó nada")
        return wall, time.process_time() - cpu, ticks, built

    def test_e_the_preview_with_200_entities(self) -> None:
        """RNF-015-06 (plan 015 §7.3; RF-015-26): con **200 entidades** en la versión —las de verdad (la
        cadena, la grande y la de Esc) y las demás, que se apoyan en la primera, cada una con su operación, su
        cifra de lo apoyado y su huella—, activar la vista previa de la primera (la orden real, el registro de las entidades, sus
        dependencias, las máscaras, la geometría y la huella, y los pasos de su temporizador con los 5 ms de espera
        de cada uno) ≤ 1 s (mediana de 5; la peor con un aviso si lo pasa) y cada redibujo (los lotes, los
        nombres, la leyenda y el resumen, con ``gpu`` y ``blf`` sustituidos: solo el Python de Geoblender; la GPU
        de verdad, M4) ≤ 5 ms."""
        project = self.project()
        self.entity = _module("bl.draw.entity")
        design_draw = _module("bl.draw.design")
        constraints = _module("bl.draw.constraints")
        entities = _module("design.entities")
        versions = _module("core.versions.read")
        self.addCleanup(lambda: self.entity.enabled() and self.entity.disable())
        with project.read() as conn:
            version = versions.version(conn, self.built.version_uid)
        real = len(entities.registry(project, version.uid))  # las de verdad: la cadena, la grande y la de Esc
        self.assertGreaterEqual(real, ORDERED + 1)
        entity_synthetic.add_dependents(
            project, _NoClock(), version, _module, base_code="PLT-001", first_number=real + 1,
            last_number=ENTITIES, start_before=f"PLT-{real:03d}", layer=edata.LAYER, terrain=self.built.start,
            axis_point=edata.absolute(0.0, 0.0))
        self.assertEqual(len(entities.registry(project, version.uid)), ENTITIES)
        self.refresh()
        self.assertEqual(self.entity.TICK_INTERVAL_S, TICK_WAIT_S)

        cold = self.activate()
        self.entity.disable()
        found = []
        for _ in range(ACTIVATIONS):
            found.append(self.activate())
            self.entity.disable()
        wall, built = statistics.median(item[0] for item in found), None
        walls = [item[0] for item in found]
        cpus = [item[1] for item in found]
        built = self.activate()[3]
        self.assertEqual(len([batch for batch in built.lines.batches if batch.key == self.entity.RESTING]), 1)
        resting = next(batch for batch in built.lines.batches if batch.key == self.entity.RESTING)
        self.assertGreaterEqual(resting.segments, 4 * (ENTITIES - real), "las que se le apoyan, con su huella")
        report(f"RNF-015-06: activar la vista previa de la primera entidad con {ENTITIES} entidades en la versión "
               f"(las {real} de verdad, con la grande, y {ENTITIES - real} que se apoyan en la primera, con sus "
               f"huellas; {len(built.lines.batches)} lotes, {len(built.lines.labels)} nombres; la orden, el "
               f"registro, las dependencias, las máscaras, la geometría y la huella, y los pasos de su "
               f"temporizador con {number(TICK_WAIT_S * 1000, 0)} ms de espera cada uno; {count(CELLS)} celdas "
               f"debajo, {self.built.constraints} restricciones; {MACHINE}): mediana de {len(found)} "
               f"{number(wall)} s ({number(statistics.median(cpus))} s de CPU; la peor {number(max(walls))} s; la "
               f"primera, en frío, {number(cold[0])} s en {cold[2]} pasos) frente a {number(ACTIVATE_BUDGET_S, 1)} "
               f"s; {free_space(self.built.root)}")
        if max(walls) > ACTIVATE_BUDGET_S:
            report(f"Aviso RNF-015-06 (vista previa): la peor de {len(found)} activaciones, {number(max(walls))} s, "
                   f"pasa de {number(ACTIVATE_BUDGET_S, 1)} s (se exige la mediana, {number(wall)} s, como en el "
                   f"resto de la 013 y la 014); se repite con el equipo en reposo")
        self.assertLessEqual(wall, ACTIVATE_BUDGET_S)

        center = edata.absolute(170.0, cdata.ROWS - 170.0)  # el tablero de las huellas de las entidades de juguete
        origin = project.origin
        local = (center[0] - origin.x0, center[1] - origin.y0)
        half = 200.0
        sx, sy = 1.0 / half, REGION[0] / (REGION[1] * half)
        matrix = np.array([[sx, 0.0, 0.0, -local[0] * sx], [0.0, sy, 0.0, -local[1] * sy],
                           [0.0, 0.0, -0.001, 0.0], [0.0, 0.0, 0.0, 1.0]])
        gpu = mock.MagicMock()
        gpu.state.depth_test_get.return_value = "NONE"
        view = {"view_matrix": Matrix.Identity(4), "projection_matrix": Matrix.Identity(4), "perspective": True,
                "view_distance": 100.0, "viewport_size": REGION, "pixel_size": 1.0}
        measure_text = lambda text: 7.0 * len(text)  # noqa: E731 - el ancho de una fuente de mentira
        redraws: list[float] = []
        with mock.patch.object(constraints, "gpu", gpu), mock.patch.object(constraints, "batch_for_shader") as lots:
            for index in range(REDRAWS):
                started = time.perf_counter()  # el reloj de CPU de Windows mide de 16 ms en 16 ms: aquí, el de pared
                drawn = constraints.draw_lines(built.lines, **view)
                items = design_draw.screen_items(built, matrix, REGION, measure=measure_text, scale=1.0)
                if index >= 20:  # los primeros: los lotes de gpu se crean una vez
                    redraws.append(time.perf_counter() - started)
            self.assertEqual((drawn, lots.call_count), (len(built.lines.batches),) * 2)
        self.entity.disable()
        percentile = sorted(redraws)[int(0.95 * len(redraws))]
        report(f"RNF-015-06: cada redibujo de la vista previa con {ENTITIES} entidades ({len(built.lines.batches)} "
               f"lotes, {count(sum(batch.segments for batch in built.lines.batches))} segmentos, "
               f"{len(built.lines.labels)} nombres, {len(items)} elementos en pantalla; región de "
               f"{number(REGION[0], 0)} × {number(REGION[1], 0)} px; {MACHINE}): mediana "
               f"{ms(statistics.median(redraws), 3)} ms, p95 {ms(percentile, 3)} ms, la peor {ms(max(redraws), 3)} "
               f"ms; presupuesto {ms(REDRAW_BUDGET_S, 0)} ms por redibujo")
        self.assertGreater(len(items), 20)
        self.assertLessEqual(statistics.median(redraws), REDRAW_BUDGET_S)
        self.assertLessEqual(percentile, REDRAW_BUDGET_S)  # y el percentil 95: la carga ajena no cuenta de más


# --- En la red -----------------------------------------------------------------------------------


@requires(network.NET, network.NET_HINT)
class NetworkTest(_Case):
    """RNF-015-03 con el proyecto en la carpeta de pruebas de la red (``Z:``): un proyecto propio en una subcarpeta
    temporal (borrada al terminar) y los datos de usuario en disco local; al terminar, vuelve el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ps.close()
        cls.addClassCleanup(_LOCAL.restore)  # lo último: los de la clase, al revés
        remote = cls.enterClassContext(network.net_tmp("gb-015-t33-"))
        cls.addClassCleanup(cls.ps.close)  # lo primero: antes de borrar su carpeta
        cls.remote = remote
        cls.built = build(remote / "proyectos")

    def test_platforms_on_the_network(self) -> None:
        """RNF-015-03 en ``Z:`` (como RNF-014-02): «Plataforma…» la primera de la cadena y la grande (con lo que
        encadenan) con el proyecto en la red: lo que hace Geoblender en cada llamada
        del hilo de Blender, sin sus esperas de la red (medidas en la llamada y anotadas aparte, sin presupuesto) ni
        la transacción final (aparte), no pasa de 0,2 s de CPU."""
        built = self.built
        project = self.ps.current()
        self.assertTrue(project.is_network, "el proyecto de la carpeta de la red")
        where = "con el proyecto en la carpeta de pruebas de la red"
        runs = []
        with netwaits.NetworkWaits(self.remote, projects=[project]) as waits:
            self.refresh()
            runs.append(platform_run(chain_form(0, built), "Plataforma 01", project, waits))
            self.refresh()
            runs.append(platform_run(big_form("entity:PLT-001"), "Plataforma grande", project, waits))
            longest = waits.longest
        self.assertEqual(len(self.done(PLATFORM_TYPE, "Plataforma grande")), 1)
        for run in runs:
            report(f"RNF-015-03: «Plataforma…» «{run.label}» sobre {count(CELLS)} celdas de 1 m ({MACHINE}): "
                   f"{number(run.with_modal_waits, 2)} s con los 50 ms del temporizador del modal "
                   f"({number(run.seconds, 2)} s de trabajo); "
                   f"{pd.calls_line(run, where, network_waits=True)}; la espera de la red más larga, "
                   f"{longest[0]} {ms(longest[1])} ms; {free_space(built.root)}")
            warn_slow(run, where)
            waited = [call for call in run.calls if call.seconds > CALL_BUDGET_S >= call.own]
            if waited:
                report(f"Nota RNF-015-03 ({where}): {len(waited)} llamadas de más de {number(CALL_BUDGET_S, 1)} s "
                       f"solo por sus esperas de la red (se anotan, sin presupuesto): "
                       + "; ".join(f"{ms(call.seconds)} ms ({call.text()})" for call in waited))
            self.assertLessEqual(run.worst_cpu.budgeted_cpu, CALL_BUDGET_S, run.worst_cpu.text())


if __name__ == "__main__":
    unittest.main()
