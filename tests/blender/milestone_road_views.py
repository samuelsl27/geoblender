# SPDX-License-Identifier: GPL-3.0-or-later
"""El objeto de la pista y el de la accesibilidad en la vista (spec 017, T31; HU-017-1, HU-017-3; RF-015-25, RF-017-23, RF-017-25, RF-017-24; RF-010-01; plan 017 §5.1 y §5.5;
decisión T31-a; ADR-0005), con las órdenes reales, en ``blender -b`` y sin pantalla.

El proyecto de ``milestone_road_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02, el terreno ``Suave`` de ``100 + 0,02·(x + y)``, las capas de la pista y los perfiles de
referencia, **solo de las pruebas**) con el terreno ``Muro`` de ``milestone_road_access_ops`` (una pared de 30 m a partir de y = 36 m que ninguna pendiente transitable pasa) y una capa
con **un punto de entrada en el norte**. Con las órdenes reales, en V01: ``RDW-001`` «Pista de la carga» (trazada de (10, 30) a (50, 30) sobre ``Suave``, con la cota de inicio
que da la persona) y ``ACC-001`` «Alcanzable» (sobre ``Muro``, desde el norte: lo alcanzable es **solo el norte**). Las pruebas, **en el orden de sus letras** sobre el mismo
estado; las cuentas, a mano (las tablas y los ficheros leídos con SQL y bucles de numpy, no el código que se prueba):

- RF-015-25, RF-017-23 (a, b): el mundo; «Cargar en la vista» de la pista da **un objeto ``DESIGN_ENTITY``** con su huella y su **eje 3D**: los vértices del eje son las estaciones
  de ``des_rdx_`` con **la cota de la rasante** en la Z (no la del terreno) y las aristas del eje marcadas con ``gb_axis``; los de la huella, a la cota de su superficie
  (la media de las celdas de la huella que tocan el vértice); relativos al GeoOrigin y con matriz identidad; la vista no escribe nada.
- RF-017-24, RF-017-25 (c): lo alcanzable de la accesibilidad es **un objeto ``DESIGN`` por accesibilidad**: un vértice en el centro de cada celda alcanzable —y solo en
  ellas: el sur, tras la pared, no— **a la cota de su superficie** (no a su 1), con el nombre de su tipo.
- RF-015-25, RF-010-01 (d): cerrar los pasos a mitad no deja nada; borrar el objeto y cargar de nuevo da lo mismo; cargar de nuevo lo sustituye.
- RF-015-25, RF-017-23, RF-010-01 (e): al cambiar la cota de fin de la pista queda **obsoleta** y su objeto lo dice en su nombre sin cambiar; «Recalcular lo obsoleto» deja su
  dato sustituido y «Refrescar» **regenera** el objeto con la rasante nueva en la Z de su eje, al día.
- RF-015-25, RF-015-17, D-12 (f): la pista **descartada** queda en la escena **sin respaldo** (no se borra ni se vuelve a cargar) y el ramal que se apoyaba en ella (su apoyo
  retirado) se ve **obsoleto**, con lo que dice la barra N de su causa.
- RF-015-25 (g): una pista sin su eje por estaciones se dibuja con el de su huella a la cota de su superficie y lo dice.
- Principio 8 (z): desactivar Geoblender quita los cargadores y deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py`` (es un hito: ``check.py --completo``).
"""

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.blender import milestone_road_access_ops as access_ops
from tests.blender import milestone_road_ops as road_ops
from tests.support import blender_ext

KIND = "DESIGN_ENTITY"
GRID_KIND = "DESIGN"
LOAD = "geoblender.core_load_into_view"
EDGE_FLAG = "gb_axis"
ENTRIES = access_ops.ENTRIES
ACCESS_NAME = "Alcanzable"
FIRST, BRANCH = road_ops.FIRST, road_ops.BRANCH
START_LEVEL = "100,5"
END_LEVEL = "101,2"
"""La cota de fin que da la persona al cambiar la pista (la natural, en la ladera de 2 %, ronda los 101,6 m)."""
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
MAX_TICKS = 400
WHY = "El tramo se rehace sobre otra superficie"
LATE_REASON = "La pista llega más baja"


def _module(name: str) -> Any:
    return platform_ops._module(name)


class RoadViewsTest(road_ops.RoadOpsTest):
    """El proyecto de ``RoadOpsTest`` con lo que necesita la accesibilidad (el terreno ``Muro`` y una capa con la entrada en el norte). Las pruebas de la pista y de la plataforma
    no se repiten."""

    wall_surface: str
    uids: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.wall_surface = cls.write_grid("Muro", access_ops.wall())
        cls.write_feature_layer(ENTRIES, "point", access_ops.ENTRY_ROWS)
        cls.refresh()
        cls.views = _module("bl.scene.views")
        cls.entity_views = _module("bl.scene.entity_views")
        cls.scene_refresh = _module("bl.scene.refresh")
        cls.mesh = _module("bl.scene.mesh")
        cls.estore = _module("design.entity_store")
        cls.uids = {}

    @classmethod
    def refresh(cls) -> None:
        super().refresh()
        cls.panels.refresh_access_choices(cls.project)

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def origin(self) -> Any:
        return self.project.origin

    def uid_of(self, family: str, name: str) -> str:
        """El uid del dato vigente de la familia ``family`` de la operación ``name``."""
        return str(self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name(family, name))[0][0])

    def table_of(self, family: str, name: str) -> str:
        return str(self.rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name(family, name))[0][0])

    def stations(self, name: str) -> np.ndarray:
        """El eje por estaciones de la pista ``name`` (x, y, cota de la rasante y cota del terreno), de su ``des_rdx_``, por SQL."""
        rows = self.rows(f'SELECT x, y, level_m, terrain_m FROM "{self.table_of("rdx", name)}" ORDER BY station_m')
        return np.asarray(rows, dtype=np.float64)

    def loaded(self) -> dict[str, Any]:
        """Los objetos de la escena que son de un dato de Geoblender, por el uid del dato."""
        return {obj.geoblender.dataset_uid: obj for obj in bpy.data.objects if obj.geoblender.kind in (KIND, GRID_KIND)}

    def load(self, uid: str) -> None:
        self.assertEqual(getattr(bpy.ops.geoblender, "core_load_into_view")(datasets=uid), {"FINISHED"})

    def load_outcome(self, *uids: str) -> Any:
        """Lo que dicen los pasos de carga de ``uids`` (``LoadOutcome``: lo cargado, los avisos y los errores)."""
        found = None
        for step in self.views.load_steps(bpy.context, self.project, list(uids)):
            found = step.result or found
        return found

    def world(self, obj: Any) -> np.ndarray:
        return self.mesh.mesh_vertices_world(obj.data, self.origin)

    def axis_of(self, obj: Any) -> np.ndarray:
        """Los vértices de las aristas del eje del objeto (marcadas con ``gb_axis``), vueltos a absolutos, en el orden de su malla."""
        edges, flags = self.mesh.mesh_edges(obj.data), self.mesh.edge_flags(obj.data, EDGE_FLAG)
        self.assertIsNotNone(flags, "las aristas del eje van marcadas")
        return self.world(obj)[np.unique(edges[flags])]

    def refresh_view(self) -> Any:
        """«Refrescar» (F5) por sus pasos: lo que hizo (``RefreshOutcome``)."""
        found = None
        for step in self.scene_refresh.refresh_steps(bpy.context, self.project):
            found = step.result or found
        return found

    def tick(self) -> bool:
        """Un paso de cada cola de pasos del recálculo (``des``, las máscaras de ``gis`` y la verificación de ``res``: sus temporizadores no corren en ``blender -b``)."""
        gis_ops, res_ops = _module("bl.ops.gis"), _module("bl.ops.res")
        pending = bool(self.des_ops.pending_runs() or gis_ops.pending_mask_runs() or res_ops.pending_runs())
        self.des_ops.des_tick()
        gis_ops.masks_tick()
        res_ops.res_tick()
        return pending

    def recompute(self) -> None:
        """Lanza «Recalcular lo obsoleto» y lo lleva hasta el final (el modal, con la cola de ``des`` avanzada a mano), sin pedir ninguna confirmación."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask, mock.patch.object(_module("bl.ops.incorporation"), "status_text"):
            self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"), {"RUNNING_MODAL"})
            found = [op for op in bpy.context.window.modal_operators
                     if isinstance(op, self.session.GEOBLENDER_OT_core_recompute_stale) and getattr(op, "_steps", None) is not None]
            self.assertEqual(len(found), 1)
            operator = found[0]
            self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
        for _ in range(MAX_TICKS):
            state = operator.modal(bpy.context, TIMER)
            self.tick()
            if state != {"RUNNING_MODAL"}:
                ask.assert_not_called()
                return
        self.fail("el recálculo no termina")

    def change(self, code: str, param: str, value: str) -> None:
        """«Cambiar parámetro…» de la pista ``code`` y lo que sigue, hasta el final."""
        prefix = f"des.road.{code.lower().replace('-', '_')}"
        self.assertEqual(bpy.ops.geoblender.core_set_parameter("EXEC_DEFAULT", key=f"{prefix}.{param}", value=value, scope="VERSION", decided_by=platform_ops.PERSON,
                                                               reason=LATE_REASON), {"FINISHED"})
        self.finish_refresh()

    def files(self) -> list[str]:
        return self.names()

    def operations(self) -> int:
        return int(self.rows("SELECT count(*) FROM gb_operation")[0][0])

    def touched(self, vertex: np.ndarray, cells: np.ndarray, values: np.ndarray, grid: Any) -> float:
        """A mano: la media de ``values`` en las celdas de ``cells`` (máscara) con dato que tocan el vértice absoluto ``vertex`` (sus cuatro celdas vecinas)."""
        line_row = int(round((grid.north - vertex[1]) / grid.dy))
        line_col = int(round((vertex[0] - grid.west) / grid.dx))
        found = []
        for row in (line_row - 1, line_row):
            for col in (line_col - 1, line_col):
                if 0 <= row < cells.shape[0] and 0 <= col < cells.shape[1] and cells[row, col] and np.isfinite(values[row, col]):
                    found.append(values[row, col])
        return float(np.mean(found)) if found else float("nan")

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_world_is_made_with_the_real_commands(self) -> None:
        """RF-017-23, RF-017-24, RF-017-25, RF-015-25 (el mundo de estas pruebas): una pista trazada sobre ``Suave`` (con la cota de inicio de la persona) y una accesibilidad sobre
        ``Muro`` desde el norte, las dos al día, con su huella, su eje por estaciones y lo alcanzable, que **no es todo**: la pared deja el sur sin alcanzar."""
        self.refresh()
        self.calculate_road(self.form(start_level=START_LEVEL))
        self.assertEqual(self.create_road(), {"FINISHED"})
        access = {"name": ACCESS_NAME, "surface": self.wall_surface, "layer": ENTRIES, **access_ops.THRESHOLDS, "in_steps": False}
        self.assertEqual(bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", **access), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        registry = self.entities.registry(self.project, self.v01.uid)
        self.assertEqual({entry.record.name: (entry.record.code, str(entry.record.kind), str(entry.record.state)) for entry in registry},
                         {FIRST: ("RDW-001", "road", "current"), ACCESS_NAME: ("ACC-001", "access", "current")})
        type(self).uids = {"road": self.uid_of("epr", FIRST), "reach": self.uid_of("acc", ACCESS_NAME)}
        reach = self.surfaces.read_surface(self.project, self.dprov.dataset_name("acc", ACCESS_NAME), version_uid=self.v01.uid).values
        self.assertTrue((reach > 0.5).any() and (reach < 0.5).any(), "alcanza el norte y no el sur")
        stations = self.stations(FIRST)
        self.assertGreater(len(stations), 2)
        self.assertGreater(np.abs(stations[:, 2] - stations[:, 3]).max(), 1e-3, "la rasante no es el terreno: lo que se dibuja en la Z es la rasante")

    def test_b_the_road_is_one_object_with_its_footprint_and_its_3d_axis_at_the_level_of_the_grade_line(self) -> None:
        """RF-015-25, RF-017-23, ADR-0005 (M4): «Cargar en la vista» de la pista da **un objeto ``DESIGN_ENTITY``** con el nombre de la vista («Entidad de diseño … · V01 [VIGENTE]»), en
        la colección de su dato bajo la de su versión, con matriz identidad y en alambre; los vértices de su **eje son las estaciones de ``des_rdx_``** (x, y **y la cota de la
        rasante**: no la del terreno) con sus aristas marcadas con ``gb_axis``, y los de su huella, a la cota de su superficie (la media de las celdas de la huella con dato que
        tocan el vértice, contada a mano); la vista no escribe nada."""
        files, operations = self.files(), self.operations()
        self.load(self.uids["road"])
        self.assertEqual((self.files(), self.operations()), (files, operations))
        obj = self.loaded()[self.uids["road"]]
        self.assertEqual(obj.name, f"Entidad de diseño {self.dprov.dataset_name('epr', FIRST)[8:]} · V01 [VIGENTE]")
        self.assertEqual((obj.geoblender.kind, obj.geoblender.project_uid), (KIND, self.project.uid))
        path = self.views.collection_path(obj.users_collection[0])
        self.assertTrue(path[-1].startswith("Entidad de diseño") and path[-2].startswith("V01"), path)
        self.assertEqual(tuple(obj.location), (0.0, 0.0, 0.0))  # nunca el origen en location
        self.assertTrue(np.array_equal(np.array(obj.matrix_world), np.eye(4)))
        self.assertEqual(obj.display_type, "WIRE")
        np.testing.assert_allclose(tuple(obj.color), self.entity_views.COLORS["road"], atol=1e-6)
        axis = self.axis_of(obj)
        stations = self.stations(FIRST)
        self.assertEqual(axis.shape, (len(stations), 3), "un vértice por estación")
        np.testing.assert_allclose(axis, stations[:, :3], atol=1e-4, rtol=0)  # x, y y la cota de la rasante, absolutas
        # El contorno de la huella: sus vértices, a la cota de la superficie que dejó la pista.
        world, edges, flags = self.world(obj), self.mesh.mesh_edges(obj.data), self.mesh.edge_flags(obj.data, EDGE_FLAG)
        outline = np.unique(edges[~flags])
        self.assertGreaterEqual(len(outline), 4, "al menos el contorno de la sección")
        surface = self.surfaces.read_surface(self.project, self.dprov.dataset_name("psf", FIRST), version_uid=self.v01.uid)
        runs = json.loads(self.rows(f'SELECT footprint FROM "{self.table_of("epr", FIRST)}"')[0][0])
        cells = np.zeros(surface.values.shape, dtype=bool)
        for row, first, last in runs:
            cells[row, first:last] = True
        self.assertGreater(int(cells.sum()), 20)
        for index in outline:
            expected = self.touched(world[index], cells, surface.values, surface.grid)
            self.assertAlmostEqual(world[index, 2], expected, delta=1e-3, msg=f"vértice {index} de la huella")
        # La huella es el contorno de la sección, alrededor del eje: ninguno de sus vértices queda a más de media sección y un par de celdas de él.
        reach = np.hypot(world[outline, 0][:, None] - stations[:, 0][None, :], world[outline, 1][:, None] - stations[:, 1][None, :]).min(axis=1)
        self.assertLess(reach.max(), 8.0)

    def test_c_the_reachable_grid_is_one_object_per_accessibility_drawn_on_its_surface(self) -> None:
        """RF-017-24, RF-017-25, RF-015-25 (M4; «como cualquier superficie»): lo alcanzable de la accesibilidad es **un objeto ``DESIGN`` por accesibilidad**, con el nombre de su
        tipo («Lo alcanzable por las pistas … · V01 [VIGENTE]»): un vértice en el centro de **cada celda alcanzable y de ninguna más** (el sur, tras la pared, no), **a la cota de
        su superficie** (``Muro``) y no a su 1; en la colección de su dato bajo la de su versión y con matriz identidad; la vista no escribe nada."""
        files, operations = self.files(), self.operations()
        self.load(self.uids["reach"])
        self.assertEqual((self.files(), self.operations()), (files, operations))
        obj = self.loaded()[self.uids["reach"]]
        self.assertEqual(obj.name, f"Lo alcanzable por las pistas {self.dprov.dataset_name('acc', ACCESS_NAME)[8:]} · V01 [VIGENTE]")
        self.assertEqual((obj.geoblender.kind, obj.geoblender.project_uid), (GRID_KIND, self.project.uid))
        path = self.views.collection_path(obj.users_collection[0])
        self.assertTrue(path[-1].startswith("Lo alcanzable por las pistas") and path[-2].startswith("V01"), path)
        self.assertEqual(tuple(obj.location), (0.0, 0.0, 0.0))
        self.assertTrue(np.array_equal(np.array(obj.matrix_world), np.eye(4)))
        reach = self.surfaces.read_surface(self.project, self.dprov.dataset_name("acc", ACCESS_NAME), version_uid=self.v01.uid)
        wall = self.surfaces.read_surface(self.project, self.wall_surface, version_uid=self.v01.uid)
        grid = reach.grid
        expected = sorted((round(grid.west + (col + 0.5) * grid.dx, 3), round(grid.north - (row + 0.5) * grid.dy, 3), round(float(wall.values[row, col]), 3))
                          for row, col in zip(*np.nonzero(reach.values > 0.5), strict=True))
        found = sorted((round(float(x), 3), round(float(y), 3), round(float(z), 3)) for x, y, z in self.world(obj))
        self.assertGreater(len(expected), 100)
        self.assertLess(len(expected), int((reach.values >= 0).sum()), "no todas las celdas son alcanzables")
        self.assertEqual(len(found), len(expected), "un vértice por celda alcanzable")
        np.testing.assert_allclose(np.asarray(found), np.asarray(expected), atol=2e-3, rtol=0)
        self.assertGreater(min(z for _x, _y, z in found), 90.0, "a la cota de su superficie, no a 1")
        self.assertGreater(min(y for _x, y, _z in found), platform_ops.SOUTH + access_ops.WALL_M - 2.0, "solo el norte de la pared")

    def test_d_closing_the_steps_leaves_nothing_and_loading_again_gives_the_same(self) -> None:
        """RF-015-25, RF-010-01 (RNF-006-09): cerrar los pasos de la carga a mitad (Esc), de la pista y de lo alcanzable, no deja ni el objeto ni su malla; borrar el objeto y
        cargar de nuevo da **lo mismo** (los mismos vértices, aristas y nombre), y cargar de nuevo sin borrar lo sustituye, sin duplicarlo."""
        files, operations = self.files(), self.operations()
        for key in ("road", "reach"):
            with self.subTest(dato=key):
                meshes, objects = len(bpy.data.meshes), len(bpy.data.objects)
                steps = self.views.load_steps(bpy.context, self.project, [self.uids[key]])
                # La carga ya está en la escena: lo preparado antes de colocarlo se borra al cerrar; el dato cargado antes sigue.
                for _ in range(200):
                    step = next(steps)
                    if len(bpy.data.meshes) > meshes:
                        break
                    self.assertIsNone(step.result, "se cargó sin pasar por la malla")
                self.assertGreater(len(bpy.data.meshes), meshes)
                steps.close()
                self.assertEqual((len(bpy.data.meshes), len(bpy.data.objects)), (meshes, objects), "lo preparado y no colocado se borra")
        obj = self.loaded()[self.uids["road"]]
        before = (self.world(obj).tolist(), self.mesh.mesh_edges(obj.data).tolist(), self.mesh.edge_flags(obj.data, EDGE_FLAG).tolist(), obj.name)
        count = len(self.loaded())
        self.load(self.uids["road"])  # cargar de nuevo lo sustituye: no se duplica
        self.assertEqual(len(self.loaded()), count)
        obj = self.loaded()[self.uids["road"]]
        collection, mesh = obj.users_collection[0], obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
        bpy.data.collections.remove(collection)
        self.assertNotIn(self.uids["road"], self.loaded())
        self.load(self.uids["road"])
        again = self.loaded()[self.uids["road"]]
        self.assertEqual((self.world(again).tolist(), self.mesh.mesh_edges(again.data).tolist(), self.mesh.edge_flags(again.data, EDGE_FLAG).tolist(), again.name), before)
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_e_a_changed_road_makes_its_object_stale_and_loading_it_again_regenerates_it_with_the_new_grade_line(self) -> None:
        """RF-015-25, RF-017-23, RF-010-01 (M4): al cambiar la cota de fin de la pista queda **obsoleta** y su objeto lo dice en su nombre («· OBSOLETO») sin cambiar su malla;
        «Recalcular lo obsoleto» deja su dato con **la rasante nueva** (su ``des_rdx_`` y su ``des_psf_`` cambian; su ``des_epr_``, la huella, no) y «Cargar en la vista» **regenera**
        el objeto de la base: su eje, con la rasante nueva en la Z (la de ``des_rdx_``: acaba en la cota que dio la persona), al día y sin duplicarlo."""
        first = self.code_of(FIRST)
        uid = self.uids["road"]
        old = self.loaded()[uid]
        old_axis = self.axis_of(old).copy()
        hashes = dict(self.rows("SELECT name, content_sha256 FROM gb_dataset WHERE name IN (?, ?, ?)", *(self.dprov.dataset_name(family, FIRST) for family in ("epr", "rdx", "psf"))))
        self.change(first, "end_level_m", END_LEVEL)
        self.assertEqual(str(self.entities.registry(self.project, self.v01.uid).get(first).record.state), "stale")
        outcome = self.refresh_view()
        self.assertFalse(outcome.reloaded, "su dato sigue siendo el mismo: solo cambia lo que dice el nombre")
        stale = self.loaded()[uid]
        self.assertIn("OBSOLETO", stale.name)
        self.assertEqual(self.axis_of(stale).tolist(), old_axis.tolist(), "la malla no cambia hasta que se carga otra vez")
        self.recompute()
        self.assertEqual(str(self.entities.registry(self.project, self.v01.uid).get(first).record.state), "current")
        again = dict(self.rows("SELECT name, content_sha256 FROM gb_dataset WHERE name IN (?, ?, ?)", *(self.dprov.dataset_name(family, FIRST) for family in ("epr", "rdx", "psf"))))
        self.assertEqual(self.uid_of("epr", FIRST), uid, "recalcular repone el mismo dato")
        self.assertNotEqual(again[self.dprov.dataset_name("rdx", FIRST)], hashes[self.dprov.dataset_name("rdx", FIRST)], "la rasante cambió")
        self.assertNotEqual(again[self.dprov.dataset_name("psf", FIRST)], hashes[self.dprov.dataset_name("psf", FIRST)], "y la superficie que deja")
        self.load(uid)  # «Cargar en la vista»: lo regenera de la base
        found = self.loaded()
        self.assertEqual(len([obj for obj in bpy.data.objects if obj.geoblender.dataset_uid == uid]), 1, "sustituido, no duplicado")
        regenerated = found[uid]
        self.assertIsNot(regenerated, old)
        self.assertTrue(regenerated.name.endswith("[VIGENTE]"), regenerated.name)
        axis = self.axis_of(regenerated)
        stations = self.stations(FIRST)
        np.testing.assert_allclose(axis, stations[:, :3], atol=1e-4, rtol=0)
        self.assertAlmostEqual(stations[-1, 2], float(END_LEVEL.replace(",", ".")), delta=0.31, msg="la rasante llega a la cota que dio la persona (con su tolerancia)")
        self.assertGreater(np.abs(axis[:, 2] - old_axis[:, 2]).max(), 0.05, "la rasante cambió y el objeto la enseña")
        self.assertEqual(self.refresh_view().reloaded, (), "lo que hay en la escena ya es lo de hoy")

    def test_f_a_discarded_road_stays_unbacked_and_what_rested_on_it_shows_stale(self) -> None:
        """RF-015-25, RF-015-17, D-12 (M4): un ramal que parte del eje de la pista (``RDW-001@20``: se apoya en ella) tiene su objeto; al **descartar** la pista, la vista deja el
        suyo **sin respaldo** («· SIN RESPALDO»: sigue en la escena, sin borrarse ni cambiar) y el del ramal, que perdió su apoyo, **obsoleto**; el dato descartado no se puede volver a
        cargar (lo dice, sin dejar nada a medias)."""
        first = self.code_of(FIRST)
        self.refresh()
        branch = self.form(name=BRANCH, origin_from="ROAD", origin_road=first, origin_station="20", destination_point="Destino norte", start=f"entity:{first}")
        branch.pop("origin_point")
        self.calculate_road(branch)
        self.assertEqual(self.create_road(), {"FINISHED"})
        branch_code = self.code_of(BRANCH)
        branch_uid = self.uid_of("epr", BRANCH)
        self.load(branch_uid)
        discarded_uid = self.uids["road"]
        kept = self.axis_of(self.loaded()[discarded_uid]).tolist()
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity=first, reason=WHY, in_steps=False), {"FINISHED"})
        registry = self.entities.registry(self.project, self.v01.uid)
        self.assertEqual((str(registry.get(first).record.state), str(registry.get(branch_code).record.state)), ("discarded", "support_removed"))
        self.refresh_view()
        found = self.loaded()
        self.assertIn(discarded_uid, found, "la pista descartada sigue en la escena")
        self.assertTrue(found[discarded_uid].name.endswith("[SIN RESPALDO]"), found[discarded_uid].name)
        self.assertEqual(found[discarded_uid].geoblender.view_state, "UNBACKED")
        self.assertEqual(self.axis_of(found[discarded_uid]).tolist(), kept, "no se borra ni se cambia")
        self.assertIn("OBSOLETO", found[branch_uid].name, "el ramal, sin su apoyo, ya no está al día")
        meshes, objects = len(bpy.data.meshes), len(bpy.data.objects)
        outcome = self.load_outcome(discarded_uid)
        self.assertEqual((outcome.loaded, len(outcome.errors)), ((), 1), "el dato descartado no se carga: lo dice")
        self.assertEqual((len(bpy.data.meshes), len(bpy.data.objects)), (meshes, objects), "y no deja nada a medias")

    def test_g_a_road_without_its_axis_by_stations_is_drawn_on_its_surface_and_says_so(self) -> None:
        """RF-015-25, RF-017-23: si el proyecto ya no tiene el eje por estaciones de la pista (``des_rdx_`` sin tabla utilizable), el objeto se dibuja con el eje de su huella a la
        cota de su superficie —no a la de la rasante— y **lo dice** (en el idioma de la interfaz); con él, el objeto se carga igual."""
        second = self.uid_of("epr", BRANCH)  # el del ramal, que sigue en el proyecto (con el apoyo retirado)
        with mock.patch.object(self.estore, "read_road_axis", return_value=None):
            outcome = self.load_outcome(second)
        self.assertEqual(len(outcome.errors), 0, outcome.errors)
        self.assertEqual(len(outcome.notes), 1, outcome.notes)
        self.assertIn(f"La pista «{BRANCH}» no tiene un eje por estaciones utilizable", outcome.notes[0])
        obj = self.loaded()[second]
        stations = self.stations(BRANCH)
        axis = self.axis_of(obj)
        self.assertEqual(axis.shape, (len(stations), 3), "el eje se dibuja igual: un vértice por punto del eje de la huella")
        np.testing.assert_allclose(axis[:, :2], stations[:, :2], atol=1e-4, rtol=0)
        surface = self.surfaces.read_surface(self.project, self.dprov.dataset_name("psf", BRANCH), version_uid=self.v01.uid)
        runs = json.loads(self.rows(f'SELECT footprint FROM "{self.table_of("epr", BRANCH)}"')[0][0])
        cells = np.zeros(surface.values.shape, dtype=bool)
        for row, first, last in runs:
            cells[row, first:last] = True
        for vertex in axis:  # a la cota de la superficie del vértice de rejilla más próximo (a mano), no a la de la rasante
            self.assertAlmostEqual(vertex[2], self.touched(vertex, cells, surface.values, surface.grid), delta=1e-3)
        self.load(second)  # con su eje, otra vez: la rasante en la Z, sin aviso
        np.testing.assert_allclose(self.axis_of(self.loaded()[second]), stations[:, :3], atol=1e-4, rtol=0)

    def test_z_disable_leaves_nothing_of_the_road_views(self) -> None:
        """Principio 8: con los objetos de la pista y de lo alcanzable en la escena, desactivar Geoblender quita los cargadores y la huella de Blender vuelve a la del principio de
        la sesión."""
        self.assertIsNotNone(self.views.loader_for("des_acc_alcanzable"))
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        for name in ("des_acc_alcanzable", "des_epr_pista_de_la_carga"):
            self.assertIsNone(self.views.loader_for(name), name)
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


for _name in dir(road_ops.RoadOpsTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(RoadViewsTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
