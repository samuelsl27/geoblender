# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista de los sondeos en Blender (spec 005, T29; HU-005-5; plan 005 §5.4 «Vista» y
§5.6.8; D9 del plan; RF-006-29; ADR-0005).

Con las ayudas de ``test_dh_import_tabular`` (``DrillholeImportCase``), en un proyecto cuya
ventana de trabajo, y con ella su GeoOrigin, está unos 8 km al suroeste de los sondeos de
``tests/data/dh/csv_basico``: importadas las bocas, las desviaciones, la litología y los
análisis en columnas (sus códigos, dados de alta; sin validar la base, que la vista no
necesita: dos trabajos menos, el presupuesto de ``tools/check.py``) y calculadas las trazas.
El oráculo es el dominio: la base del proyecto (``drillholes.store.read_steps``), sus trazas
por mínima curvatura sin los sondeos con errores de alcance S (``validate.hole_exclusions``) y
los arrays de ``drillholes.view_data`` (la litología del esquema ``lithology``; el oro con su
leyenda por defecto o con la de la representación).

- RF-005-23 (plan §5.6.8): calculadas las trazas, la vista de ``dh_trace`` se carga sola: un
  objeto de curvas ``POLY``, una por tramo de litología y por hueco, con ``gb_color`` (de punto,
  el color lineal del catálogo) y ``gb_hole`` (de curva) los del dominio; vueltas a absolutas,
  sus posiciones quedan a ≤ 0,5 mm de las del dominio a ±8 km del GeoOrigin; los tubos son el
  grupo ``GB_DrillTubes`` (con su versión) con el radio de la representación, y su malla
  evaluada lleva ``gb_color`` y el material de la vista.
- RF-005-24: las barras del oro, una malla de cuadriláteros (una cara por parte de tramo) con el
  color de su clase por cara (``gb_color``) y su clase (``gb_class``), a ≤ 0,5 mm; con las
  clases de la representación (editables), las de esa leyenda.
- RF-006-29: matriz identidad, ``Object.geoblender`` (tipo ``DRILLHOLES``, el dato
  ``dh_trace`` de su proyecto) y la colección del dato en «Sondeos»
  (``bl.scene.views.ensure_collection``).
- RF-005-22: la vista toma de la desviación que escribió ``dh_trace`` su método, sus
  parámetros y sus sondeos (``drillholes.store.trace_view``); los de traza obsoleta (los de
  ``drillholes.store.stale_holes``, cuya detección prueba T28) llevan ``gb_stale`` en sus
  curvas y en sus barras, y cargar otra vez sustituye los objetos sin dejar datos huérfanos.
- Plan §5.6.8: cerrar a mitad los pasos de la carga (Esc) deja la vista como estaba.
- T30 (RF-005-25, RF-005-17; plan §5.6.8): la carga deja a la superposición de sus objetos
  las etiquetas «S-12 (160,00 m)» (y las del fondo) en locales, las leyendas y las marcas de
  la boca: los sondeos de traza obsoleta y, con una validación guardada con un error de
  alcance T (la litología de S-01), su código; esa litología no se pinta (el trabajo recibe lo
  que excluye la validación). Lo que dibuja la superposición lo prueba ``test_dh_overlay``.
- T47 (RF-005-22): :func:`check_stale_view`, la vista cargada al día de lo obsoleto sin
  recargarla; la usan ``test_dh_ops_compute`` (tras cambiar la referencia del azimut) y
  ``dh/test_provenance_dh`` (tras añadir y descartar una entrada y tras «Actualizar» otra).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender.test_dh_import_tabular import MAX_TICKS, DrillholeImportCase, _module

FILES = ("bocas.csv", "desviaciones.csv", "litologia.csv", "analisis_columnas.csv")
# La ventana de trabajo y su centro, el GeoOrigin, unos 8 km al suroeste de los sondeos.
FAR_WINDOW = (691_800.0, 4_391_800.0, 692_100.0, 4_392_100.0)
LIMIT_M = 0.0005  # RF-005-23: ≤ 0,5 mm frente a la traza calculada (a ±8 km)
FAR_M = 7_990.0  # los sondeos, a unos 8 km del GeoOrigin en X y en Y
TRACE = "dh_trace"
RADIUS = 0.75
OFFSET_M, WIDTH_M = 1.5, 0.5
STALE = ("S-02", "S-12")
CLASSES = (("", (0.0, 0.0, 1.0)), ("1,0", (1.0, 0.0, 0.0)))  # «desde» y color (sRGB)
IDENTITY = [[float(i == j) for j in range(4)] for i in range(4)]


def _drive(steps: Any) -> Any:
    """Lo que devuelve un generador de pasos, avanzado hasta el final."""
    try:
        while True:
            next(steps)
    except StopIteration as stop:
        return stop.value


def _values(data: Any, name: str) -> np.ndarray:
    """Los valores del atributo ``name`` de ``data`` (una malla o unas curvas), de una vez."""
    found = data.attributes[name]
    count = len(found.data)
    if found.data_type == "FLOAT_COLOR":
        values = np.empty(count * 4, dtype=np.float32)
        found.data.foreach_get("color", values)
        return values.reshape(-1, 4)
    if found.data_type == "FLOAT_VECTOR":
        values = np.empty(count * 3, dtype=np.float32)
        found.data.foreach_get("vector", values)
        return values.reshape(-1, 3)
    listed = [0] * count
    found.data.foreach_get("value", listed)
    return np.array(listed)


def check_stale_view(case: DrillholeImportCase, holes: tuple[str, ...], *,
                     stale: bool) -> None:
    """T47 (RF-005-22; plan §5.6.8): tras un tic del temporizador de los indicadores de la
    procedencia (``bl.ui.provenance.indicator_tick``, que lee el proyecto cuando cambia), la
    vista de las trazas ya cargada en la escena de ``case`` dice lo que dice el proyecto, sin
    recalcular nada (ningún trabajo nuevo) ni escribir en él: los sondeos de traza obsoleta
    ``holes`` (los de ``drillholes.store.stale_holes``, en el orden de la base) llevan
    ``gb_stale`` en sus curvas (y en sus barras, si las hay) y su marca en la superposición, y
    el nombre generado de sus objetos y de la colección de su dato y ``Object.geoblender.stale``
    dicen si ``dh_trace`` está obsoleto (``stale``: «Sondeos [VIGENTE · OBSOLETO]»)."""
    dh_view = _module("bl.scene.dh_view")
    views = _module("bl.scene.views")
    ui = _module("bl.ui.provenance")
    runner = case.jobs_ops.MONITOR.runner
    jobs = {snapshot.job_uid for snapshot in runner.snapshots()}
    before = case.counts()
    case.assertEqual(ui.indicator_tick(), ui.INDICATOR_TICK_S)
    case.assertEqual(case.counts(), before)  # nada escrito en el proyecto
    case.assertEqual({snapshot.job_uid for snapshot in runner.snapshots()}, jobs)
    with case.project.read() as conn:
        case.assertEqual(_module("drillholes.store").stale_holes(conn), holes)
        record = _module("core.datasets.registry").get(conn, TRACE)
    name = views.view_name(views.loader_for(TRACE), record, stale=stale)
    case.assertEqual("OBSOLETO" in name, stale, name)
    objects = dh_view.loaded_objects(case.project)
    case.assertTrue(objects)
    names = [row[0] for row in case.rows("SELECT name FROM dh_collar ORDER BY fid")]
    marked = np.array([item in holes for item in names])
    for obj in objects:
        case.assertTrue(obj.name.startswith(name), obj.name)  # « · Au»
        case.assertEqual((obj.geoblender.dataset_uid, obj.geoblender.stale), (record.uid, stale))
        (collection,) = obj.users_collection
        case.assertEqual(collection.name, name)
        case.assertEqual(_values(obj.data, "gb_stale").tolist(),
                         marked[_values(obj.data, "gb_hole")].tolist(), obj.name)
    overlay = dh_view.overlay_of(objects[0])
    case.assertEqual([mark.hole for mark in overlay.marks if mark.kind == dh_view.MARK_STALE],
                     list(holes))


class DrillholeViewTest(DrillholeImportCase):
    window = FAR_WINDOW

    # --- Ayudas -------------------------------------------------------------------------------

    def record(self) -> Any:
        with self.project.read() as conn:
            return _module("core.datasets.registry").get(conn, TRACE)

    def shown(self, record: Any) -> tuple[Any, Any]:
        """Los dos objetos del dato ``record`` en la escena: los tubos y las barras."""
        found = [obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == record.uid]
        tubes = [obj for obj in found if obj.type == "CURVES"]
        bars = [obj for obj in found if obj.type == "MESH"]
        self.assertEqual((len(tubes), len(bars), len(found)), (1, 1, 2))
        return tubes[0], bars[0]

    def expected(self, legend: Any = None,
                 tables: frozenset = frozenset()) -> tuple[Any, Any, Any, Any]:
        """La base del proyecto, sus curvas de litología, las barras del oro del dominio
        (con ``legend`` o la leyenda por defecto; sin las tablas de alcance T ``tables``) y
        las etiquetas, con las del fondo."""
        store = _module("drillholes.store")
        params = _module("drillholes.params")
        validate = _module("drillholes.validate")
        view_data = _module("drillholes.view_data")
        with self.project.read() as conn:
            dset = _drive(store.read_steps(conn))
        excluded = validate.hole_exclusions(
            dset, depth_tolerance_m=params.default(params.DEPTH_TOLERANCE))
        traces = _module("drillholes.desurvey").desurvey(dset, "minimum_curvature",
                                                         holes=~excluded)
        exclusions = validate.Exclusions(excluded, tables)
        step = params.default(params.TRACE_STEP)
        curves = view_data.lithology_curves(dset, traces, "lithology", step, excluded=exclusions)
        if legend is None:
            legend = view_data.default_grade_legend(
                view_data.grade_values(dset, "Au", "g/t", excluded=exclusions), "g/t")
        bars = view_data.grade_bars(dset, traces, "Au", legend, OFFSET_M, WIDTH_M,
                                    max_step_m=step, excluded=exclusions)
        return dset, curves, bars, view_data.labels(dset, traces, True)

    def check_overlay(self, objects: tuple[Any, Any], dset: Any, labels: Any, legend: Any,
                      marks: list[tuple[str, str, tuple[str, ...]]]) -> None:
        """T30 (RF-005-25, RF-005-17): lo que la carga deja a la superposición de sus dos
        objetos: las etiquetas (con las del fondo, en locales), las leyendas de la litología y
        del oro y las marcas ``marks`` (sondeo, clase, códigos) en la boca."""
        dh_view = _module("bl.scene.dh_view")
        georef = _module("core.georef")
        found = dh_view.overlay_of(objects[0])
        self.assertIsNotNone(found)
        self.assertIs(dh_view.overlay_of(objects[1]), found)
        self.assertEqual([(item.text, item.bottom) for item in found.labels],
                         [(item.text, item.bottom) for item in labels])
        self.assertIn("S-12 (160,00 m)", [item.text for item in found.labels])
        local = georef.world_to_local(np.array([item.xyz for item in labels]),
                                      self.project.origin)
        self.assertEqual([item.xyz for item in found.labels], [tuple(row) for row in
                                                               local.tolist()])
        self.assertEqual(found.lithology,
                         _module("drillholes.view_data").lithology_legend(dset, "lithology"))
        self.assertEqual((found.element, found.grade), ("Au", legend))
        self.assertEqual([(mark.hole, mark.kind, mark.codes) for mark in found.marks], marks)
        names = dset.collars.name.tolist()
        for mark in found.marks:
            k = names.index(mark.hole)
            collar = (dset.collars.x[k], dset.collars.y[k], dset.collars.z[k])
            self.assertEqual(mark.xyz, tuple(georef.world_to_local(
                np.array(collar), self.project.origin).tolist()))

    def world(self, local: np.ndarray) -> np.ndarray:
        return _module("core.georef").local_to_world(local, self.project.origin)

    def assertNear(self, local: np.ndarray, expected: np.ndarray) -> None:
        self.assertEqual(local.shape, expected.shape)
        error = float(np.max(np.abs(self.world(local) - expected)))
        self.assertLessEqual(error, LIMIT_M)
        self.errors.append(error)

    def check_tubes(self, tubes: Any, curves: Any) -> None:
        """Las curvas de ``tubes``: las de ``curves``, a ≤ 0,5 mm y a ±8 km."""
        data = tubes.data
        self.assertIsInstance(data, bpy.types.Curves)
        offsets = [0] * (len(data.curves) + 1)
        data.curve_offset_data.foreach_get("value", offsets)
        self.assertEqual(np.diff(offsets).tolist(), curves.curve_sizes.tolist())
        self.assertTrue((_values(data, "curve_type") == 1).all())  # POLY
        self.assertEqual(_values(data, "gb_hole").tolist(), curves.hole.tolist())
        self.assertTrue(np.array_equal(_values(data, "gb_color"), curves.color_linear))
        local = _values(data, "position")
        self.assertNear(local, curves.points_abs)
        reach = np.max(np.abs(local[:, :2]), axis=0)  # como RF-006-19: llegan a 8 km
        self.assertGreaterEqual(float(reach.min()), FAR_M)

    def check_bars(self, bars: Any, expected: Any) -> None:
        """La malla de ``bars``: las caras de ``expected``, con su color y su clase."""
        mesh_mod = _module("bl.scene.mesh")
        mesh = bars.data
        totals = [0] * len(mesh.polygons)
        mesh.polygons.foreach_get("loop_total", totals)
        self.assertEqual((len(totals), set(totals)), (len(expected.faces), {4}))
        corners = _module("bl.compat").mesh_corner_verts(mesh)
        self.assertEqual(corners.tolist(), expected.faces.ravel().tolist())
        self.assertNear(mesh_mod.mesh_vertices_local(mesh), expected.vertices_abs)
        self.assertTrue(np.array_equal(_values(mesh, "gb_color"), expected.color_linear))
        self.assertEqual(_values(mesh, "gb_class").tolist(), expected.grade_class.tolist())
        self.assertEqual(_values(mesh, "gb_hole").tolist(), expected.hole.tolist())

    def check_object(self, obj: Any, record: Any) -> None:
        """La matriz identidad, ``Object.geoblender`` y la colección del dato de ``obj``."""
        views = _module("bl.scene.views")
        self.assertEqual([list(row) for row in obj.matrix_world], IDENTITY)
        props = obj.geoblender
        self.assertEqual((props.kind, props.dataset_uid, props.project_uid, props.stale),
                         ("DRILLHOLES", record.uid, self.project.uid, False))
        (collection,) = obj.users_collection
        self.assertIs(collection, views.ensure_collection("DRILLHOLES", record,
                                                          name=collection.name))
        self.assertEqual(views.collection_path(collection), ["Sondeos", collection.name])

    # --- La prueba -----------------------------------------------------------------------------

    def test_view_of_the_traces(self) -> None:
        """RF-005-23, RF-005-24, RF-005-22, RF-006-29 (plan §5.4 «Vista» y §5.6.8): calculadas
        las trazas, su vista se carga sola en «Sondeos»: los tubos (curvas ``POLY``, una por
        tramo y por hueco, ``gb_color`` y ``gb_hole`` del dominio, a ≤ 0,5 mm a ±8 km, con
        ``GB_DrillTubes`` y el radio de la representación) y las barras del oro (cuadriláteros
        con el color y la clase de cada cara), con matriz identidad, ``Object.geoblender`` y la
        colección de su dato. La vista toma de la desviación su método, sus parámetros y sus
        sondeos; cargarla otra vez sustituye los objetos y marca con ``gb_stale`` los sondeos
        de traza obsoleta, con las clases de la representación; cerrar sus pasos a mitad deja
        la vista como estaba. T30 (RF-005-25, RF-005-17): cada carga deja a la superposición
        sus etiquetas, sus leyendas y sus marcas, y no pinta lo que excluye la validación
        guardada (alcance T). T47: sin recargarla, la vista vuelve a lo que dice el proyecto
        (ningún sondeo obsoleto) en sus curvas, sus barras y sus marcas."""
        ops = self.dh_ops
        store = _module("drillholes.store")
        drill_tubes = _module("bl.gn.drill_tubes")
        self.errors: list[float] = []
        # Sin validar la base: la vista no la necesita (el presupuesto de tools/check.py).
        self.enterContext(mock.patch.object(ops, "start_validate", lambda project, **_: None))
        self.import_all(FILES)
        display = getattr(bpy.context.scene, self.props.SCENE_PROPERTY)
        display.element, display.tube_radius = "Au", RADIUS
        display.bar_offset, display.bar_width = OFFSET_M, WIDTH_M
        self.assertEqual(bpy.ops.geoblender.dh_desurvey("EXEC_DEFAULT"), {"FINISHED"})
        self.finish()  # las trazas y, después, su vista (plan §5.6.8)

        record = self.record()
        with self.project.read() as conn:
            source = store.trace_view(conn)
        self.assertEqual((source.method, source.holes, source.stale),
                         ("minimum_curvature", tuple(range(6)), ()))
        self.assertEqual(dict(source.params), {"dh.validation.depth_tolerance_m": 0.01,
                                               "dh.desurvey.trace_step_m": 2.0})
        dset, curves, bars, labels = self.expected()
        tubes, bar_object = self.shown(record)
        self.check_tubes(tubes, curves)
        self.check_bars(bar_object, bars)
        for obj in (tubes, bar_object):
            self.check_object(obj, record)
        self.assertFalse(_values(tubes.data, "gb_stale").any())
        view_data = _module("drillholes.view_data")
        self.check_overlay((tubes, bar_object), dset, labels, view_data.default_grade_legend(
            view_data.grade_values(dset, "Au", "g/t"), "g/t"), [])
        (modifier,) = tubes.modifiers
        group = modifier.node_group
        self.assertEqual((modifier.type, group.name), ("NODES", "GB_DrillTubes"))
        self.assertEqual(group[drill_tubes.VERSION_PROPERTY], drill_tubes.VERSION)
        self.assertEqual(drill_tubes.tube_radius(tubes), RADIUS)
        geometry = tubes.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
        evaluated = geometry.mesh  # vive mientras ``geometry``
        self.assertEqual(len(evaluated.vertices),
                         drill_tubes.PROFILE_RESOLUTION * len(tubes.data.points))
        self.assertIn("gb_color", [item.name for item in evaluated.color_attributes])
        materials = [[item.name for item in data.materials] for data in (evaluated,
                                                                          bar_object.data)]
        self.assertEqual(materials, [[drill_tubes.MATERIAL_NAME]] * 2)

        # Otra vez, con dos sondeos de traza obsoleta, la leyenda de la representación y una
        # validación guardada con la litología de S-01 solapada (alcance T, RF-005-17, T30).
        for lower, color in CLASSES:
            item = display.grade_classes.add()
            item.lower, item.color = lower, color
        overlapped = {"hole_id": 2, "hole_name": "S-01", "code": "DH-E10", "level": "error",
                      "scope": "table", "table_name": "dh_lithology", "row_fid": 3,
                      "log_set": "lithology", "element": None}
        stored = store.StoredValidation("validación", (overlapped,))
        with mock.patch.object(store, "stale_holes", lambda conn: STALE), \
                mock.patch.object(store, "stored_validation", lambda conn: stored):
            self.assertEqual(bpy.ops.geoblender.core_load_into_view("EXEC_DEFAULT",
                                                                    datasets=TRACE),
                             {"FINISHED"})
        legend = _module("drillholes.view_data").GradeLegend("g/t", (1.0,),
                                                              ("#0000FF", "#FF0000"))
        _dset, curves, bars, labels = self.expected(
            legend, frozenset({(1, "dh_lithology", "lithology")}))
        tubes, bar_object = self.shown(record)
        self.check_overlay((tubes, bar_object), dset, labels, legend,
                           [("S-01", "partial", ("DH-E10",)), ("S-02", "stale", ()),
                            ("S-12", "stale", ())])
        self.assertEqual(len(bpy.data.hair_curves), 1)  # sin las curvas de antes
        self.assertEqual([item.name for item in bpy.data.node_groups
                          if item.name.startswith(drill_tubes.GROUP_NAME)],
                         [drill_tubes.GROUP_NAME])
        self.check_tubes(tubes, curves)
        self.check_bars(bar_object, bars)
        for obj in (tubes, bar_object):
            self.check_object(obj, record)
        names = dset.collars.name.tolist()
        stale = np.array([name in STALE for name in names])
        self.assertTrue(np.array_equal(_values(tubes.data, "gb_stale"), stale[curves.hole]))
        self.assertTrue(np.array_equal(_values(bar_object.data, "gb_stale"), stale[bars.hole]))
        print(f"\nRF-005-23: error máximo de la ida y vuelta a ±8 km: {max(self.errors) * 1000:.4f}"
              f" mm (≤ {LIMIT_M * 1000:.1f} mm); {len(curves.curve_sizes)} curvas, "
              f"{len(bars.faces)} caras")

        # T47 (RF-005-22): lo que dice ahora el proyecto (ningún sondeo de traza obsoleta), sin
        # recargar: ni en las curvas ni en las barras ni en las marcas; la de la validación sigue.
        self.assertTrue(_module("bl.scene.dh_view").show_stale(self.project))
        check_stale_view(self, (), stale=False)
        self.assertEqual([(mark.hole, mark.kind, mark.codes) for mark in _module(
            "bl.scene.dh_view").overlay_of(bar_object).marks], [("S-01", "partial", ("DH-E10",))])

        # Esc a mitad: la vista queda como estaba.
        before = (sorted(obj.name for obj in bpy.data.objects), len(bpy.data.hair_curves),
                  len(bpy.data.meshes))
        runner = self.jobs_ops.MONITOR.runner
        known = {snapshot.job_uid for snapshot in runner.snapshots()}
        steps = _module("bl.scene.views").load_steps(bpy.context, self.project, [TRACE])
        for _ in range(MAX_TICKS):
            next(steps)
            if {snapshot.job_uid for snapshot in runner.snapshots()} - known:
                break
        else:
            self.fail("la vista no lanza su trabajo")
        steps.close()
        self.finish()
        self.assertEqual((sorted(obj.name for obj in bpy.data.objects),
                          len(bpy.data.hair_curves), len(bpy.data.meshes)), before)


if __name__ == "__main__":
    unittest.main()
