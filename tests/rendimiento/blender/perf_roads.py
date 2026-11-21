# SPDX-License-Identifier: GPL-3.0-or-later
"""Las pistas y su accesibilidad dentro de Blender (spec 017, T34; RNF-017-06 y RNF-017-08; plan 017 §7.3 y el riesgo R4 de la 012, ``tests/rendimiento/blender``), con la
forma de ``perf_stockpiles.py`` de la 016, cuyas piezas usa: el proyecto de escala de las entidades, el registro de cada llamada del hilo de Blender y los eventos del modal.

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py -- --carpeta tests/rendimiento/blender --patron "perf_roads.py"``). Cada prueba imprime su
cifra en una línea «RNF-017-nn: …» con el equipo y el espacio libre del disco, y la compara con su presupuesto, sin relajarlo.

**Datos** (los puros de ``tests/support/road_scale.py``, que no versionan ninguno; en Blender nunca se importa una ayuda que cargue ``import_geoblender``, ``docs/trampas.md`` §4): el
proyecto de escala de ``perf_entities.py`` (EPSG:25830 + EPSG:5782, V01 y V02, la rejilla de 1.654 × 1.699 celdas de 1 m —2,81 M—, el límite legal y el perímetro, los 20 sectores, los diez
perfiles de banco y las máscaras de V01 al día) con el terreno del barranco como rejilla del proyecto, la capa de ejes (el de 2 km en diagonal y los **veinte** de la revisión), la de
puntos de origen y destino de la ruta de 1,5 km, la de entradas de la accesibilidad y el **perfil de pista de referencia** (**solo de las pruebas**, D-2). Todo con la extensión
habilitada, como una persona.

- **RNF-017-06** (:class:`CallsTest`, en el orden de sus letras sobre el mismo estado): las órdenes de la 017, las reales, como desde la interfaz: Intro (``execute`` por ``bpy.ops``, en
  pasos), cada evento del temporizador de su modal hasta que termina (con el tic de los indicadores de la procedencia cuando le toca) y «Crear» (la misma orden con ``confirm``, por pasos:
  ``Calculation.create_steps``, con la transacción final como último paso y, en el mismo modal, lo que sigue: ``after_entity_change``, la declaración, las máscaras, la capa de entidades y
  la de ejes de pistas). Cada llamada del hilo de Blender se mide: lo que hace Geoblender en ella, **sin la transacción final** (``DesignWriter.commit`` y ``MaskWriter.commit``: una
  transacción que no se trocea; el R4 de la 012), ≤ 0,2 s **en la peor de las** :data:`RUNS` **ejecuciones** con un tic del reloj de CPU descontado (``perf_stockpiles.check_budget``); la
  transacción, medida aparte, se anota con la llamada en que ocurre (si pasa de 0,2 s, con un aviso: la cifra, para Samuel). (a) «Pista…» «sobre un eje» el eje de 2 km con 61 curvas
  (2,42 M celdas de ventana: la mayor); (b) «Pista…» «trazar» sobre el barranco (la red 2D, la ruta 3D, el eje, la rasante y el grabado); (c) «Accesibilidad de las pistas…»; (d) **veinte
  pistas en cadena** (cada una parte de la anterior): **lo que sigue a «Crear» crece con las pistas de la versión** (la T32 midió, con unas 40 en una versión de 60 × 60 m, una llamada de
  172 ms de CPU y una transacción final de 203 ms) y aquí se mide a escala, pista a pista. **Cada llamada se mide en CPU del proceso** (``time.process_time()``, que no cuenta lo que gastan
  otros programas: ``docs/trampas.md`` §4) **y en pared**; el presupuesto se exige a la CPU y la pared se anota con un aviso si lo pasa (se repite con el equipo en reposo). La resolución
  del reloj de CPU de Windows es de unos 16 ms.
- **RNF-017-06, Esc** (:meth:`CallsTest.test_f_esc`): Esc a mitad de cada cálculo —«Calcular» de las tres órdenes (a mitad de sus eventos y, las que escriben un temporal, en cuanto lo
  tienen) y «Crear» de la pista (a mitad de sus eventos, con temporales ya escritos)—: la llamada más larga más lo que tarda Esc ≤ 2 s y nada a medias en el proyecto (ni operación «en
  curso», ni temporal; «Calcular» no deja ni operación, ni dato, ni cifra, ni fichero).
- **RNF-017-08** (:meth:`CallsTest.test_e_the_preview_with_20_roads`): con **20 pistas** en la versión (las de la revisión, hechas con la orden real), activar la vista previa de la primera
  (``entity.enable`` con ``RoadAsk(code=…)``: **entera**, con la lectura del proyecto —el registro, el eje guardado, el perfil, lo que se le apoya y la superficie sobre la que se dibuja— y los
  pasos de su temporizador con los 5 ms de espera de cada uno) ≤ 1 s y cada redibujo (los lotes, los nombres, la leyenda y el resumen, con ``gpu`` y ``blf`` sustituidos: solo el Python de
  Geoblender; la GPU de verdad es de la comprobación manual M5) ≤ 5 ms. La 013 y la 016 midieron igual (``perf_design.py``, ``perf_entities.py``); la T28 midió lo mismo con la lectura del
  proyecto sustituida (``milestone_road_preview.py``).
- **En la red** (:class:`NetworkTest`; recurso «red» de ``tests.support.network``: con ``GEOBLENDER_NET_TEST_DIR``, a mano; sin ella, se omite): lo de RNF-017-06 con el proyecto en una
  subcarpeta temporal propia de la carpeta de pruebas de ``Z:`` (borrada al terminar) y los datos de usuario en disco local: la pista «sobre un eje» y «trazar», con sus esperas de la red de
  cada llamada, medidas con ``tests.support.netwaits`` y anotadas aparte, sin presupuesto (como RNF-014-02). **Ojo**: en el PC de referencia la variable está definida en el usuario y este
  módulo, lanzado tal cual, también corre la de la red (``docs/trampas.md`` §7); para medir solo en local, sin ella: ``env -u GEOBLENDER_NET_TEST_DIR …`` (Git Bash) o
  ``Remove-Item Env:GEOBLENDER_NET_TEST_DIR`` (PowerShell).

En ``blender -b`` no corren ni el bucle de eventos ni los temporizadores: la prueba hace de ventana (un evento del temporizador del modal cada vez) y de temporizador (las colas de pasos); la
confirmación de «Calcular» (``_ask_confirmation``, que relanza la orden con un temporizador) se sustituye.
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
from mathutils import Matrix

from tests.rendimiento.blender import perf_constraints as pc
from tests.rendimiento.blender import perf_design as pd
from tests.rendimiento.blender import perf_entities as pe
from tests.rendimiento.blender import perf_quarry as pq
from tests.rendimiento.blender import perf_stockpiles as ps
from tests.support import blender_ext, netwaits, network
from tests.support import road_scale as scale
from tests.support.resources import requires
from tests.support.trees import remove_tree

CALL_BUDGET_S = 0.2  # RNF-017-06: lo que hace Geoblender en cada llamada del hilo de Blender
CLOCK_TICK_S = ps.CLOCK_TICK_S
ESC_BUDGET_S = 2.0  # RNF-017-06: Esc a mitad de cualquier cálculo
ACTIVATE_BUDGET_S = 1.0  # RNF-017-08: activar la vista previa con 20 pistas
REDRAW_BUDGET_S = 0.005  # RNF-017-08: cada redibujo
ACTIVATIONS = 5  # veces que se activa (la mediana cuenta; la peor se anota)
REDRAWS = 120  # redibujos medidos
TICK_WAIT_S = 0.005  # bl.draw.entity.TICK_INTERVAL_S (lo comprueba la prueba)
REGION = (1920.0, 1080.0)
RUNS = 3  # cada orden se mide 3 veces y el presupuesto se exige al MÁXIMO de la peor llamada de cada ejecución
ROAD = "geoblender.des_create_road"
ACCESS = "geoblender.des_road_access"
PREVIEW_PLAN = "RDW-"
LAYERS_TYPE = "gis.perf_roads_layers"
"""El tipo de operación con que se escriben las capas de la prueba (como la importación de la 006)."""
RAVINE = "gis_dtm_barranco"
"""El terreno del barranco como rejilla del proyecto (``gis_dtm_<nombre>``)."""
AXES_LAYER = "gis_fea_pistas_escala_ejes"
POINTS_LAYER = "gis_fea_pistas_escala_puntos"
ENTRIES_LAYER = "gis_fea_pistas_escala_entradas"
PROFILE_CODE = "pista_principal"
ROUTE = {"mesh": "4", "level_step": "0,28", "max_cut_fill": "14", "lambda_weight": "2", "turn": "4", "margin": "2", "simplify": "4", "arrival_tol": "0,28"}
"""Los parámetros de la ruta de la referencia de IMGA tecleados como los teclea una persona (``tests.support.road_data.ROUTE``: solo pruebas) con 2 m de holgura."""
THRESHOLDS = {"walk_slope": "12", "walk_width": "10", "min_berm_area": "300"}
"""Los umbrales de la accesibilidad tecleados como los teclea una persona (**solo de la prueba**: la orden no propone ninguno)."""
CHAIN = scale.SCALE_ROADS
USER = "Samuel (IMGA)"
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


# --- El proyecto de escala con las capas de la 017 ----------------------------------------------------------------


def write_grid(project: Any, label: str, values: np.ndarray, message: str) -> str:
    """``values`` (la rejilla de escala, m) como rejilla del proyecto (``gis.resample``, como las deja «Rejilla del proyecto desde un MDT»); el nombre de su dato."""
    gis_store = _module("gis.store")
    grid = _module("gis.grid").Grid(scale.WEST, scale.SOUTH + scale.ROWS * scale.STEP_M, scale.STEP_M, scale.STEP_M, scale.COLS, scale.ROWS)
    raster = _module("gis.raster").Raster
    crs, vertical = gis_store.project_references(project)
    library, library_version = _module("gis.crs").crs_library()
    handle = _module("core.provenance.operations").begin_operation(project, _module("gis.provenance").RESAMPLE, settings={"nombre": message}, executor="blender")
    with gis_store.ResultWriter(project, handle) as out:
        out.raster(label, raster(grid, values, crs, vertical))
        (found,) = out.commit(software={library: library_version}, message=message)
    return str(found.name)


def write_layer(project: Any, name: str, kind: str, entities: tuple[Any, ...], names: tuple[str, ...]) -> None:
    """La capa de entidades ``name`` (``kind``: ``line`` o ``point``) con su campo ``nombre``, como la deja la importación de la 006."""
    with mock.patch.object(ps, "LAYERS_TYPE", LAYERS_TYPE):  # el tipo con que ``perf_stockpiles.write_features`` anota la operación de la capa: el de este módulo
        ps.write_features(project, name, kind, entities, names, {})


def write_profile(project: Any) -> None:
    """El perfil de pista de referencia (``road_scale.PROFILE``, solo de las pruebas) en el proyecto, como la persona con «Perfil de pista…»."""
    road_profiles, design_params = _module("design.road_profiles"), _module("design.params")
    declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", USER, "Perfil de la prueba de rendimiento")
    values = {param: scale.PROFILE[param.value] for param in design_params.RoadProfileParam}
    road_profiles.edit_road_profiles(project, (road_profiles.ProfileEdit(name=PROFILE_CODE.upper(), values=values),), declared)


def write_data(project: Any) -> None:
    """El barranco, las capas de ejes, de puntos y de entradas y el perfil de pista de la 017 en el proyecto."""
    assert write_grid(project, "barranco", scale.ravine_terrain(), "Terreno de escala del barranco") == RAVINE
    axes = (scale.axis_2km(), scale.compact_axis_2km(), *scale.chain_axes())
    write_layer(project, AXES_LAYER, "line", tuple(((line,),) for line in axes), ("Eje de 2 km", "Eje compacto", *(f"Eje {number_:02d}" for number_ in range(1, CHAIN + 1))))
    ends = scale.absolute(np.array([scale.RAVINE_ORIGIN, scale.RAVINE_DESTINATION]))
    write_layer(project, POINTS_LAYER, "point", tuple(((end[None, :].copy(),),) for end in ends), ("Origen del barranco", "Destino del barranco"))
    entry = scale.absolute(np.array([[10.5, 10.5]]))
    write_layer(project, ENTRIES_LAYER, "point", (((entry.copy(),),),), ("Entrada",))
    write_profile(project)


def refresh(project: Any) -> None:
    """Las listas de los diálogos (también las de las pistas y la accesibilidad), leídas de nuevo (un guion no abre el diálogo que las lee)."""
    pe.refresh(project)
    panels = _module("bl.ui.des_panels")
    panels.refresh_road_choices(project)
    panels.refresh_access_choices(project)


def build(parent: Path) -> pd.Built:
    """El proyecto de escala de las entidades (:func:`perf_entities.build`) con los datos de la 017, abierto en la sesión con V01 activa y sus máscaras al día."""
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
            self.folder = Path(tempfile.mkdtemp(prefix="gb-017-t34-"))
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


# --- Lo que se pide en cada diálogo ----------------------------------------------------------------------------------


def axis_form(name: str, feature: str, start: str, **changes: Any) -> dict[str, Any]:
    """«Pista…» «sobre un eje» de la línea ``feature`` de la capa de ejes de escala desde ``start``, con el perfil de referencia."""
    return {"name": name, "mode": "ON_AXIS", "layer": AXES_LAYER, "feature": feature, "profile": PROFILE_CODE, "start": start, **changes}


def trace_form(name: str, start: str, **changes: Any) -> dict[str, Any]:
    """«Pista…» «trazar» la ruta de 1,5 km sobre el barranco, del origen al destino de la capa de puntos, con la ruta de la referencia (2 m de holgura)."""
    return {"name": name, "mode": "TRACE", "layer": POINTS_LAYER, "origin_point": "Origen del barranco", "destination_point": "Destino del barranco", "profile": PROFILE_CODE,
            "start": start, **ROUTE, **changes}


def access_form(name: str, start: str, **changes: Any) -> dict[str, Any]:
    """«Accesibilidad de las pistas…» de la capa de entradas sobre ``start`` con los umbrales de la prueba."""
    return {"name": name, "surface": start, "layer": ENTRIES_LAYER, **THRESHOLDS, **changes}


# --- Las órdenes, como desde la interfaz ---------------------------------------------------------------------------------


def open_dialog(idname: str) -> Callable[[Any], None]:
    """Lo que lee el ``invoke`` de la orden ``idname`` al abrir su diálogo (las listas de superficies, capas, perfiles y entidades): lo que mide la llamada «abrir el diálogo»."""
    panels = _module("bl.ui.des_panels")

    def opened(project: Any) -> None:
        panels.refresh_choices(project)
        panels.refresh_platform_choices(project)
        (panels.refresh_road_choices if idname == ROAD else panels.refresh_access_choices)(project)

    return opened


def run_order(idname: str, form: dict[str, Any], what: str, waits: netwaits.NetworkWaits | None = None) -> pd.Run:
    """La orden ``idname`` como desde la interfaz: abrir el diálogo, «Calcular» (Intro y cada evento de su modal) y «Crear» con lo que encadena, cada llamada del hilo de Blender medida."""
    project = _module("bl.scene.project_session").current()
    opened = open_dialog(idname)

    def steps(recorder: Recorder) -> None:
        recorder.call(f"abrir el diálogo ({what})", opened, project)
        pq.calculate(recorder, idname, form, what)
        ps.create(recorder, idname, what)

    return measure(what, steps, waits)


# --- RNF-017-06 y RNF-017-08 ---------------------------------------------------------------------------------------------


class Stopped(pe.Stopped):
    """Esc a mitad de un cálculo (véase :class:`perf_entities.Stopped`)."""


class CallsTest(pe._Case):  # noqa: SLF001
    """RNF-017-06 y RNF-017-08 con el proyecto de escala en disco local, en el orden de sus letras sobre el mismo estado: las pistas de la a y la b y la accesibilidad de la c se descartan o
    se repiten con otro nombre (de cada superficie parte una sola); la d deja **veinte pistas en cadena**, que usan la e (la vista previa) y la f (Esc). Cada orden se mide :data:`RUNS`
    veces y el presupuesto se exige al **máximo** de la peor llamada de cada ejecución, con un tic del reloj descontado (``perf_stockpiles.check_budget``)."""

    built: pd.Built
    runs: dict[str, list[pd.Run]] = {}
    counter = 0
    first_road = ""
    last_road = ""

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

    def report_runs(self, rnf: str, text: str, runs: list[pd.Run]) -> None:
        """La línea de cifra de unas ejecuciones (la peor, con sus llamadas más largas) y el presupuesto: lo que hace Geoblender en cada llamada, sin la transacción final, en CPU."""
        found = max(runs, key=lambda run: ps.worst(run.calls).budgeted_cpu)
        each = [(ps.worst(ps.parts(run)[0]).budgeted_cpu, ps.worst(ps.parts(run)[1]).budgeted_cpu) for run in runs]
        report(f"{rnf}: {text} con {count(CELLS)} celdas de 1 m ({len(runs)} ejecuciones; la peor, {count(len(found.calls))} llamadas del hilo de Blender, {count(found.events)} eventos del "
               f"modal, {number(found.seconds, 1)} s; {MACHINE}); la peor llamada de «Calcular» de cada ejecución: " + ", ".join(f"{ms(item[0])} ms" for item in each)
               + f" (máximo {ms(max(item[0] for item in each))} ms) y de «Crear» y lo que encadena: " + ", ".join(f"{ms(item[1])} ms" for item in each)
               + f" (máximo {ms(max(item[1] for item in each))} ms), de CPU; se exige el máximo con un tic del reloj ({ms(CLOCK_TICK_S)} ms) descontado; presupuesto "
               f"{number(CALL_BUDGET_S * 1000, 0)} ms; la peor ejecución, {pd.calls_line(found, f'«{found.label}», con el proyecto en disco local', network_waits=False)}; "
               f"{free_space(self.built.root)}")
        for run in runs:
            over = [call for call in run.calls if call.budgeted > CALL_BUDGET_S]
            if over:
                report(f"Aviso {rnf} ({run.label}): {len(over)} llamadas de más de {number(CALL_BUDGET_S, 1)} s de pared sin la transacción final (con el equipo cargado por otros "
                       f"programas se repite en reposo; el presupuesto se exige a la CPU): "
                       + "; ".join(f"{ms(call.budgeted)} ms de pared y {ms(call.budgeted_cpu)} de CPU ({call.text()})" for call in over))
            long = [(op, seconds - waited) for call in run.with_commits for op, seconds, _cpu, waited in call.commits if seconds - waited > CALL_BUDGET_S]
            if long:
                report(f"Aviso {rnf} ({run.label}; R4 de la 012, la cifra para Samuel): la transacción final pasa de {number(CALL_BUDGET_S, 1)} s: "
                       + "; ".join(f"{op} {ms(seconds)} ms" for op, seconds in long))

    def repeat(self, idname: str, form: Callable[[str], dict[str, Any]], what: str, name: str, *, drop: bool) -> list[pd.Run]:
        """La orden ``idname`` :data:`RUNS` veces con un nombre nuevo cada una (``form``: lo pedido con ese nombre) y, con ``drop``, descartando cada pista al terminar (de cada
        superficie parte una sola)."""
        runs = []
        for _turn in range(RUNS):
            runs.append(run_order(idname, form(self.fresh(name)), what))
            if drop:
                self.drop(self.last_code())
        return runs

    def drop(self, code: str) -> None:
        """Descarta la pista ``code`` de V01 con lo que encadena la orden, para repetir."""
        entity_store = _module("design.entity_store")
        for _step in entity_store.discard_entity_steps(self.project(), self.built.version_uid, code, reason="Medición de rendimiento"):
            pass

    def last_code(self) -> str:
        """El código de la última pista de V01 (``RDW-nnn``)."""
        registry = _module("design.entities").registry(self.project(), self.built.version_uid)
        return [entry.record.code for entry in registry if entry.record.code.startswith(PREVIEW_PLAN)][-1]

    def test_a_axis_of_2_km(self) -> None:
        """RNF-017-06 (RF-017-30, RF-015-29): «Pista…» «sobre un eje» el eje de 2 km con 61 curvas (en diagonal: la ventana de grabado de 2,42 M celdas, la mayor) sobre 2,81 M celdas,
        «Calcular» (Intro, cada evento de su modal y el tic de los indicadores) y «Crear» con lo que encadena: en ninguna llamada sin la transacción final pasa de 0,2 s de CPU."""
        runs = self.repeat(ROAD, lambda name: axis_form(name, "Eje de 2 km", self.built.start), "Pista sobre un eje de 2 km", "Pista de escala", drop=True)
        CallsTest.runs["axis"] = runs
        self.report_runs("RNF-017-06", "«Pista…» «sobre un eje» de 2 km con 61 curvas", runs)
        ps.check_budget(self, runs)

    def test_b_trace_over_the_ravine(self) -> None:
        """RNF-017-06 (RF-017-30): «Pista…» «trazar» la ruta de 1,5 km sobre el barranco con 2 m de holgura (la red 2D desde los dos extremos, la ruta 3D, el eje, la rasante, la sección y el
        grabado), «Calcular» y «Crear» con lo que encadena: en ninguna llamada sin la transacción final pasa de 0,2 s de CPU."""
        runs = self.repeat(ROAD, lambda name: trace_form(name, RAVINE), "Pista trazada sobre el barranco", "Pista trazada", drop=True)
        CallsTest.runs["trace"] = runs
        self.report_runs("RNF-017-06", "«Pista…» «trazar» la ruta de 1,5 km sobre el barranco", runs)
        ps.check_budget(self, runs)

    def test_c_access(self) -> None:
        """RNF-017-06 (RF-017-30): «Accesibilidad de las pistas…» de la superficie de escala (2,81 M celdas, con la entrada de la capa del proyecto), «Calcular» y «Crear» (por pasos: las
        rejillas y las tablas, con la transacción final como último paso) con lo que encadena: en ninguna llamada sin la transacción final pasa de 0,2 s de CPU. No se descarta (no es una
        entidad): se repite con otro nombre."""
        runs = self.repeat(ACCESS, lambda name: access_form(name, self.built.start), "Accesibilidad de la superficie de escala", "Accesibilidad de escala", drop=False)
        CallsTest.runs["access"] = runs
        found = self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.road_access' AND status = 'done'")[0][0]
        self.assertEqual(found, RUNS, "las accesibilidades no están hechas")
        self.report_runs("RNF-017-06", "«Accesibilidad de las pistas…»", runs)
        ps.check_budget(self, runs)

    def test_d_twenty_roads(self) -> None:
        """RNF-017-06 (RF-017-30; la T32 de la 017: lo que sigue a «Crear» **crece con las pistas de la versión**), RNF-017-10: **veinte pistas en cadena** (cada una de 1,5 km, de la superficie
        de la anterior), «Calcular» y «Crear» con lo que encadena, **pista a pista**: en ninguna llamada de ninguna pasa de 0,2 s de CPU sin la transacción final; la transacción final de lo que
        sigue (la declaración, las máscaras y la capa de entidades y de ejes), medida aparte (R4 de la 012), con su cifra para Samuel si pasa de 0,2 s."""
        start, runs, codes = self.built.start, [], []
        for index in range(1, CHAIN + 1):
            runs.append(run_order(ROAD, axis_form(f"Pista {index:02d}", f"Eje {index:02d}", start), f"Pista {index:02d} de {CHAIN}"))
            codes.append(self.last_code())
            start = f"entity:{codes[-1]}"
        CallsTest.runs["chain"] = runs
        CallsTest.first_road, CallsTest.last_road = codes[0], codes[-1]
        per_road = [(ps.worst(ps.parts(run)[1]).budgeted_cpu, sum(call.transaction for call in ps.parts(run)[1]), len(ps.parts(run)[1])) for run in runs]
        report(f"RNF-017-06: lo que sigue a «Crear» una pista crece con las pistas de la versión; las {CHAIN} pistas en cadena con la orden real sobre {count(CELLS)} celdas de 1 m ({MACHINE}), "
               f"por pista (la peor llamada de «Crear» y lo que encadena en CPU sin la transacción final, la transacción final y las llamadas): "
               + "; ".join(f"{index + 1}: {ms(cpu)} ms, {ms(transaction)} ms, {calls}" for index, (cpu, transaction, calls) in enumerate(per_road)))
        self.report_runs("RNF-017-06", f"las {CHAIN} pistas en cadena, la última «{runs[-1].label}»", runs[-3:])
        self.assertEqual(len(set(codes)), CHAIN, "las veinte pistas no son veinte")
        ps.check_budget(self, runs)

    # --- La vista previa con 20 pistas (RNF-017-08) -----------------------------------------------

    def activate(self) -> tuple[float, float, int, Any]:
        """Activa la vista previa de la primera pista (``entity.enable`` con su código) y da los pasos del temporizador hasta que está construida (en ``blender -b`` no corren): lo que tardó
        hasta entonces con los 5 ms de espera de cada paso, su CPU, los pasos y lo construido."""
        entity = self.entity
        self.assertFalse(entity.enabled())
        gc.collect()
        started, cpu = time.perf_counter(), time.process_time()
        entity.enable(entity.EntityPlan(road=_module("design.preview").RoadAsk(code=self.first_road)))
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

    def test_e_the_preview_with_20_roads(self) -> None:
        """RNF-017-08 (plan 017 §7.3; RF-017-26): con **20 pistas** en la versión (las de la revisión, hechas con la orden real), activar la vista previa de la primera (la lectura del
        proyecto: el registro de las entidades, el eje guardado, el perfil, lo que se le apoya y la superficie sobre la que se dibuja, y los pasos de su temporizador con los 5 ms de espera de
        cada uno) ≤ 1 s (mediana de 5; la peor con un aviso si lo pasa) y cada redibujo (los lotes, los nombres, la leyenda y el resumen, con ``gpu`` y ``blf`` sustituidos: solo el Python de
        Geoblender; la GPU de verdad, M5) ≤ 5 ms."""
        project = self.project()
        self.entity = _module("bl.draw.entity")
        design_draw = _module("bl.draw.design")
        constraints = _module("bl.draw.constraints")
        entities = _module("design.entities")
        self.addCleanup(lambda: self.entity.enabled() and self.entity.disable())
        registered = [entry for entry in entities.registry(project, self.built.version_uid) if entry.record.code.startswith(PREVIEW_PLAN)]
        roads = [entry for entry in registered if entry.record.state != "discarded"]  # las descartadas de la a, la b y la c siguen en el registro y no se dibujan
        self.assertEqual(len(roads), CHAIN, "las veinte pistas de la d")
        self.assertEqual(self.entity.TICK_INTERVAL_S, TICK_WAIT_S)
        cold = self.activate()
        self.entity.disable()
        found = []
        for _ in range(ACTIVATIONS):
            found.append(self.activate())
            self.entity.disable()
        walls = [item[0] for item in found]
        cpus = [item[1] for item in found]
        wall = statistics.median(walls)
        built = self.activate()[3]
        segments = sum(batch.segments for batch in built.lines.batches)
        self.assertGreater(segments, 100, "la vista previa de la pista no dibuja nada: no mide nada")
        report(f"RNF-017-08: activar la vista previa de la primera pista con {len(roads)} pistas en la versión (las de la orden real, más {len(registered) - len(roads)} descartadas; "
               f"{len(built.lines.batches)} lotes, {count(segments)} segmentos, "
               f"{len(built.lines.labels)} nombres; la lectura del proyecto —el registro, el eje guardado, el perfil, lo que se le apoya y la superficie— y los pasos de su temporizador con "
               f"{number(TICK_WAIT_S * 1000, 0)} ms de espera cada uno; {count(CELLS)} celdas debajo; {MACHINE}): mediana de {len(found)} {number(wall)} s ({number(statistics.median(cpus))} s de "
               f"CPU; la peor {number(max(walls))} s; la primera, en frío, {number(cold[0])} s en {cold[2]} pasos) frente a {number(ACTIVATE_BUDGET_S, 1)} s; {free_space(self.built.root)}")
        if max(walls) > ACTIVATE_BUDGET_S:
            report(f"Aviso RNF-017-08 (vista previa): la peor de {len(found)} activaciones, {number(max(walls))} s, pasa de {number(ACTIVATE_BUDGET_S, 1)} s (se exige la mediana, "
                   f"{number(wall)} s, como en el resto de la 013 a la 016); se repite con el equipo en reposo")
        self.assertLessEqual(wall, ACTIVATE_BUDGET_S)

        origin = project.origin
        local = (scale.WEST + 850.0 - origin.x0, scale.SOUTH + 100.0 - origin.y0)  # el centro de la primera pista (de la rejilla de escala), respecto al GeoOrigin del proyecto
        half = 800.0
        sx, sy = 1.0 / half, REGION[0] / (REGION[1] * half)
        matrix = np.array([[sx, 0.0, 0.0, -local[0] * sx], [0.0, sy, 0.0, -local[1] * sy], [0.0, 0.0, -0.001, 0.0], [0.0, 0.0, 0.0, 1.0]])
        gpu = mock.MagicMock()
        gpu.state.depth_test_get.return_value = "NONE"
        view = {"view_matrix": Matrix.Identity(4), "projection_matrix": Matrix.Identity(4), "perspective": True, "view_distance": 100.0, "viewport_size": REGION, "pixel_size": 1.0}
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
        report(f"RNF-017-08: cada redibujo de la vista previa con {len(roads)} pistas ({len(built.lines.batches)} lotes, {count(segments)} segmentos, {len(built.lines.labels)} nombres, "
               f"{len(items)} elementos en pantalla; región de {number(REGION[0], 0)} × {number(REGION[1], 0)} px; {MACHINE}): mediana {ms(statistics.median(redraws), 3)} ms, p95 "
               f"{ms(percentile, 3)} ms, la peor {ms(max(redraws), 3)} ms; presupuesto {ms(REDRAW_BUDGET_S, 0)} ms por redibujo")
        self.assertGreater(len(items), 5)
        self.assertLessEqual(statistics.median(redraws), REDRAW_BUDGET_S)
        self.assertLessEqual(percentile, REDRAW_BUDGET_S)  # y el percentil 95: la carga ajena no cuenta de más

    # --- Esc (RNF-017-06) ---------------------------------------------------------------------

    def esc_in_calculation(self, idname: str, form: dict[str, Any], *, after_events: int | None, until_tmp: bool, where: str) -> Stopped:
        """«Calcular» ``form`` hasta ``after_events`` eventos del modal (o, con ``until_tmp``, hasta que su superficie está en un temporal) y Esc: lo que tardó la llamada más larga hasta
        entonces y lo que tardó Esc; el cálculo no deja nada en el proyecto."""
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

    @staticmethod
    def events_before_the_final_transaction(run: pd.Run) -> int:
        """Los eventos del modal de «Crear» de ``run`` **antes** de la transacción final de la pista (``des.road``: el evento en que llega lo guardado; los que le siguen son lo que se
        encadena, con la pista ya creada, y Esc ya no la deshace)."""
        events = 0
        for call in ps.parts(run)[1]:
            if call.what.startswith("evento"):
                events += 1
            if any(op == "des.road" for op, _seconds, _cpu, _waited in call.commits):
                return events - 1
        raise AssertionError("«Crear» no tiene la transacción final de la pista")

    def esc_in_creation(self, idname: str, form: dict[str, Any], where: str) -> Stopped:
        """«Calcular» ``form`` hasta el final y «Crear» hasta la mitad de sus eventos **antes de la transacción final** (los de la primera ejecución de la ``test_a``), con ya ficheros
        temporales en el disco, y Esc: lo que tardó la llamada más larga hasta entonces y lo que tardó Esc; el proyecto queda como estaba (sin operación, dato, cifra, fichero ni temporal) y
        el cálculo, descartado. (Esc **después** de la transacción final deja la pista creada y lo que sigue se pone al día con la orden siguiente: es de ``test_road_steps.py``.)"""
        refresh(self.project())
        total = self.events_before_the_final_transaction(self.runs["axis"][0])
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

    def test_f_esc(self) -> None:
        """RNF-017-06 (RF-017-30, RF-015-29): Esc a mitad de cada «Calcular» de las tres órdenes sobre 2,81 M celdas —a la mitad de sus eventos y, las que escriben un temporal, en cuanto su
        superficie ya está en él— y, de la pista, a mitad de «Crear» (por pasos, con sus temporales ya escritos): la llamada más larga más lo que tarda Esc ≤ 2 s y nada a medias en el
        proyecto: ni operación, ni dato, ni cifra, ni fichero ni temporal."""
        last = f"entity:{self.last_road}"
        cases: list[tuple[str, dict[str, Any], str, str]] = [
            (ROAD, axis_form("Pista de Esc", "Eje de 2 km", last), "Pista sobre un eje de 2 km", "axis"),
            (ROAD, trace_form("Pista trazada de Esc", RAVINE), "Pista trazada sobre el barranco", "trace"),
            (ACCESS, access_form("Accesibilidad de Esc", self.built.start), "Accesibilidad de la superficie de escala", "access")]
        stops = []
        for idname, form, what, key in cases:  # «Calcular» no escribe ni un temporal (la superficie entera la escribe «Crear»): solo a mitad de sus eventos
            total = ps.calculation_events(self.runs[key][0])
            half = max(1, total // 2)
            stops.append(self.esc_in_calculation(idname, form, after_events=half, until_tmp=False, where=f"«{what}», a mitad de sus eventos ({half} de {total})"))
        stops.append(self.esc_in_creation(ROAD, axis_form("Pista de Esc en Crear", "Eje de 2 km", last), "Pista sobre un eje de 2 km: «Crear»"))
        self.assertGreater(stops[-1].temporaries, 0, "«Crear» no llegó a escribir un temporal")
        worst_stop = max(stops, key=lambda stop: stop.wall)
        report(f"RNF-017-06: Esc a mitad de cada cálculo de la 017 sobre {count(CELLS)} celdas (la llamada más larga más lo que tarda Esc; nada queda a medias en el proyecto; {MACHINE}): "
               + "; ".join(stop.text() for stop in stops) + f"; presupuesto {number(ESC_BUDGET_S, 0)} s; {free_space(self.built.root)}")
        self.assertLessEqual(worst_stop.wall, ESC_BUDGET_S, worst_stop.text())


# --- En la red -------------------------------------------------------------------------------------------------------------


@requires(network.NET, network.NET_HINT)
class NetworkTest(pe._Case):  # noqa: SLF001
    """RNF-017-06 con el proyecto en la carpeta de pruebas de la red (``Z:``): un proyecto propio en una subcarpeta temporal (borrada al terminar) y los datos de usuario en disco local; al
    terminar, vuelve el del módulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ps.close()
        cls.addClassCleanup(_LOCAL.restore)  # lo último: los de la clase, al revés
        remote = cls.enterClassContext(network.net_tmp("gb-017-t34-"))
        cls.addClassCleanup(cls.ps.close)  # lo primero: antes de borrar su carpeta
        cls.remote = remote
        cls.built = build(remote / "proyectos")

    def test_roads_on_the_network(self) -> None:
        """RNF-017-06 en ``Z:`` (como RNF-014-02): «Pista…» «sobre un eje» de 2 km, «trazar» sobre el barranco y «Accesibilidad de las pistas…» (con lo que encadenan) con el proyecto en la
        red: lo que hace Geoblender en cada llamada del hilo de Blender, sin sus esperas de la red (medidas en la llamada y anotadas aparte, sin presupuesto) ni la transacción final (aparte),
        no pasa de 0,2 s de CPU."""
        built = self.built
        project = self.ps.current()
        self.assertTrue(project.is_network, "el proyecto de la carpeta de la red")
        where = "con el proyecto en la carpeta de pruebas de la red"
        runs = []
        drop = _module("design.entity_store").discard_entity_steps
        with netwaits.NetworkWaits(self.remote, projects=[project]) as waits:
            for idname, form, what in ((ROAD, axis_form("Pista de 2 km", "Eje de 2 km", built.start), "Pista sobre un eje de 2 km"),
                                       (ROAD, trace_form("Pista trazada", RAVINE), "Pista trazada sobre el barranco"),
                                       (ACCESS, access_form("Accesibilidad de escala", built.start), "Accesibilidad de la superficie de escala")):
                refresh(project)
                runs.append(run_order(idname, form, what, waits))
                if idname == ROAD:
                    code = [entry.record.code for entry in _module("design.entities").registry(project, built.version_uid) if entry.record.code.startswith(PREVIEW_PLAN)][-1]
                    for _step in drop(project, built.version_uid, code, reason="Medición de rendimiento"):
                        pass
            longest = waits.longest
        for run in runs:
            report(f"RNF-017-06: «{run.label}» sobre {count(CELLS)} celdas de 1 m ({MACHINE}): {number(run.with_modal_waits, 2)} s con los 50 ms del temporizador del modal "
                   f"({number(run.seconds, 2)} s de trabajo); {pd.calls_line(run, where, network_waits=True)}; la espera de la red más larga, {longest[0]} {ms(longest[1])} ms; "
                   f"{free_space(built.root)}")
            pe.warn_slow(run, where)
            waited = [call for call in run.calls if call.seconds > CALL_BUDGET_S >= call.own]
            if waited:
                report(f"Nota RNF-017-06 ({where}): {len(waited)} llamadas de más de {number(CALL_BUDGET_S, 1)} s solo por sus esperas de la red (se anotan, sin presupuesto): "
                       + "; ".join(f"{ms(call.seconds)} ms ({call.text()})" for call in waited))
            self.assertLessEqual(run.worst_cpu.budgeted_cpu, CALL_BUDGET_S, run.worst_cpu.text())


if __name__ == "__main__":
    unittest.main()
