# SPDX-License-Identifier: GPL-3.0-or-later
"""Un objeto cuya superficie cambia sin cambiar su huella se ve «no al día» y Refrescar (F5) lo regenera (spec 017, T31c; HU-017-1, HU-017-2; RF-010-01, RF-010-02; RF-015-25;
RF-015-16; E5; plan 010 §5.3.1 A1; ADR-0006), con las órdenes reales, en ``blender -b`` y sin pantalla.

El defecto (el hallazgo de la T31): la marca «no al día» (``core.views.state``, RF-010-02) y Refrescar (RF-010-01) comparan el hash de contenido **del dato que carga el objeto**, y el
de una entidad (``des_epr_``) **no depende de la cota** de lo que se calculó: tras cambiar solo la cota de una plataforma o de una pista y recalcular, su superficie (``des_psf_``; en la
pista, además, su eje por estaciones ``des_rdx_``) cambia de hash y ``des_epr_`` **no**, y el recálculo repone el mismo dato. El objeto, dibujado con la cota de esa superficie, decía
«al día» con la cota de antes y Refrescar no lo regeneraba (había que «Cargar en la vista» otra vez). La corrección (decisión de la sesión principal, la salida (i) de la T31): el cargador
de una entidad declara sus **datos compañeros** (su superficie, su base y su eje), el objeto anota su hash al cargarse y ``core.views.state`` los cuenta para «no al día».

Dos proyectos pequeños (ventana de 60 × 60 m con celdas de 2 m: **es un hito**, ``check.py --completo``), uno con **plataformas** (el de ``test_platform_ops``: «Carga» a 105 m y «Taller»,
cada una de su terreno) y otro con una **pista** (el de ``test_road_ops``: «Pista de la carga» sobre ``Suave``). En cada uno, **en el orden de sus letras sobre el mismo estado** (las
cuentas, a mano, con SQL y las mallas de Blender):

- (a) el mundo, con las órdenes reales; «Cargar en la vista» da el objeto de cada entidad a la cota de su superficie (la rasante de la pista en la Z de su eje).
- (b) RF-010-02: con todo al día **nada se marca** (ni «no al día», ni Refrescar resaltado) y Refrescar no vuelve a cargar nada.
- (c) RF-010-02, RF-010-01: cambiada la cota por «Cambiar parámetro…» y **antes de recalcular**, el objeto dice «OBSOLETO» pero **no** «no al día» (su superficie no ha cambiado) y
  Refrescar no lo recarga.
- (d) RF-010-02, RF-010-01: recalculada, su ``des_psf_`` (y el ``des_rdx_`` de la pista) cambia de hash y su ``des_epr_`` **no**; el objeto queda «no al día» **sin cambiar su malla**
  (el control 7 cuenta uno y lo resalta, la otra entidad sigue al día) y Refrescar **lo regenera con la cota nueva** y solo a él; la marca desaparece y otro Refrescar no recarga nada.
- (z) Principio 8: desactivar Geoblender deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py`` (``--patron milestone_view_companions.py``).
"""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.blender import test_road_ops as road_ops
from tests.support import blender_ext

KIND = "DESIGN_ENTITY"
EDGE_FLAG = "gb_axis"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
MAX_TICKS = 400
LOADING, WORKSHOP = platform_ops.LOADING, platform_ops.WORKSHOP
RAISED_M = "106,5"
"""La cota inicial nueva de «Carga» (de 105 a 106,5 m: sigue bajo el terreno de su huella, que va de 107,75 a 111 m)."""
FIRST = road_ops.FIRST
START_LEVEL = "100,5"
END_LEVEL = "101,2"
"""La cota de fin que da la persona a la pista (la natural, en la ladera de 2 %, ronda los 101,6 m)."""
LATE_REASON = "La cota cambia el proyecto"
NOT_UP_TO_DATE = "NO AL DÍA"


def _module(name: str) -> Any:
    return platform_ops._module(name)


class Companions:
    """Lo que comparten las dos clases: la marca en vivo, Refrescar, el recálculo y lo que se ve de cada objeto."""

    project: Any
    uids: dict[str, str]

    @classmethod
    def modules(cls) -> None:
        cls.views = _module("bl.scene.views")
        cls.live = _module("bl.scene.live")
        cls.scene_refresh = _module("bl.scene.refresh")
        cls.mesh = _module("bl.scene.mesh")
        cls.uids = {}

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def origin(self) -> Any:
        return self.project.origin

    def loaded(self) -> dict[str, Any]:
        """Los objetos ``DESIGN_ENTITY`` de la escena por el uid de su dato."""
        return {obj.geoblender.dataset_uid: obj for obj in bpy.data.objects if obj.geoblender.kind == KIND}

    def load(self, *names: str) -> None:
        for name in names:
            self.assertEqual(getattr(bpy.ops.geoblender, "core_load_into_view")(datasets=self.uids[name]), {"FINISHED"})

    def world(self, obj: Any) -> np.ndarray:
        return self.mesh.mesh_vertices_world(obj.data, self.origin)

    def hashes(self, *families: str, name: str) -> dict[str, str]:
        """El hash de contenido de los datos de las familias ``families`` de la entidad ``name``, por su familia."""
        found = {}
        for family in families:
            data = self.dprov.dataset_name(family, name)
            found[family] = str(self.rows("SELECT content_sha256 FROM gb_dataset WHERE name = ? AND status = 'current'", data)[0][0])
        return found

    def mark(self) -> None:
        """La marca en vivo, hasta que acaba (sin ella el tic de los indicadores no la pide: los temporizadores no corren en ``blender -b``)."""
        self.live.request(self.project)
        for _ in range(MAX_TICKS):
            if self.live.mark_tick() is None:
                return
        self.fail("la marca en vivo no acaba")

    def refresh_view(self) -> Any:
        """«Refrescar» (F5) por sus pasos: lo que hizo (``RefreshOutcome``)."""
        found = None
        for step in self.scene_refresh.refresh_steps(bpy.context, self.project):
            found = step.result or found
        return found

    def tick(self) -> bool:
        """Un paso de cada cola de pasos del recálculo (``des``, las máscaras de ``gis`` y la verificación de ``res``)."""
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

    def change(self, kind: str, code: str, param: str, value: str) -> None:
        """«Cambiar parámetro…» de la entidad ``code`` (``kind``: ``platform`` o ``road``) y lo que sigue, hasta el final."""
        key = f"des.{kind}.{code.lower().replace('-', '_')}.{param}"
        self.assertEqual(bpy.ops.geoblender.core_set_parameter("EXEC_DEFAULT", key=key, value=value, scope="VERSION", decided_by=platform_ops.PERSON, reason=LATE_REASON),
                         {"FINISHED"})
        self.finish_refresh()

    def state_of(self, name: str) -> str:
        return str(self.entities.registry(self.project, self.v01.uid).get(self.code_for(name)).record.state)

    def shown(self, uid: str) -> tuple[str, str]:
        """Lo que dice el objeto del dato ``uid``: su ``view_state`` y su nombre."""
        obj = self.loaded()[uid]
        return obj.geoblender.view_state, obj.name

    def pointers(self) -> dict[str, int]:
        return {uid: obj.as_pointer() for uid, obj in self.loaded().items()}


class PlatformCompanionsTest(Companions, platform_ops.CreatePlatformTest):
    """El proyecto de la prueba de la plataforma con dos plataformas, cada una de su terreno, y sus objetos en la escena."""

    ground2: str

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ground2 = cls.write_grid("Ladera 2", platform_ops.ground())
        cls.refresh()
        cls.modules()

    def made(self, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa."""
        self.refresh()
        self.calculate(**values)
        self.assertEqual(self.create(), {"FINISHED"})

    def code_for(self, name: str) -> str:
        (found,) = [entry.record.code for entry in self.entities.registry(self.project, self.v01.uid) if entry.record.name == name]
        return str(found)

    def level(self, name: str) -> np.ndarray:
        """La Z (absoluta) de los vértices del objeto de la plataforma ``name``."""
        return self.world(self.loaded()[self.uids[name]])[:, 2]

    def test_a_two_platforms_are_made_and_loaded_at_the_level_of_their_surface(self) -> None:
        """RF-015-25, RF-010-01, HU-017-2 (el mundo): «Carga» (de su terreno, a 105 m) y «Taller» (de otro, a 108 m) con las órdenes reales; «Cargar en la vista» da el objeto de cada una
        con todos sus vértices a la cota de su rasante, al día."""
        self.made()
        self.made(name=WORKSHOP, feature=WORKSHOP, start=self.ground2)
        type(self).uids = {name: str(self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name("epr", name))[0][0])
                           for name in (LOADING, WORKSHOP)}
        self.assertEqual({entry.record.name: str(entry.record.state) for entry in self.entities.registry(self.project, self.v01.uid)}, {LOADING: "current", WORKSHOP: "current"})
        self.load(LOADING, WORKSHOP)
        np.testing.assert_allclose(self.level(LOADING), 105.0, atol=1e-3)
        np.testing.assert_allclose(self.level(WORKSHOP), 108.0, atol=1e-3)
        self.assertEqual({uid: self.shown(uid)[0] for uid in self.uids.values()}, {uid: "CURRENT" for uid in self.uids.values()})

    def test_b_with_everything_up_to_date_nothing_is_marked_and_refresh_loads_nothing(self) -> None:
        """RF-010-02, RF-010-01: con las dos plataformas cargadas y el proyecto como estaba, la marca en vivo no pone ninguna «no al día» (el control 7 sin resaltar) y Refrescar
        no vuelve a cargar nada."""
        self.mark()
        self.assertEqual(self.live.pending_count(), 0)
        self.assertEqual({uid: self.shown(uid)[0] for uid in self.uids.values()}, {uid: "CURRENT" for uid in self.uids.values()})
        before = self.pointers()
        self.assertEqual(self.refresh_view().reloaded, ())
        self.assertEqual(self.pointers(), before)

    def test_c_a_changed_level_before_recalculating_is_stale_but_not_out_of_date(self) -> None:
        """RF-010-02, RF-010-01, RF-015-16: cambiada la cota inicial de «Carga» (de 105 a 106,5 m), la plataforma queda **obsoleta** y su objeto lo dice en el nombre, pero su
        superficie no ha cambiado: no está «no al día» y Refrescar no la recarga (la cota sigue siendo la de antes)."""
        self.change("platform", self.code_for(LOADING), "start_level_m", RAISED_M)
        self.assertEqual(self.state_of(LOADING), "stale")
        self.mark()
        state, name = self.shown(self.uids[LOADING])
        self.assertIn("OBSOLETO", name)
        self.assertNotIn(NOT_UP_TO_DATE, name)
        self.assertEqual((state, self.live.pending_count()), ("CURRENT", 0))
        self.assertEqual(self.refresh_view().reloaded, ())
        np.testing.assert_allclose(self.level(LOADING), 105.0, atol=1e-3)

    def test_d_a_recalculated_level_leaves_the_object_out_of_date_and_refresh_regenerates_it_with_the_new_level(self) -> None:
        """RF-010-02, RF-010-01, RF-015-25 (E5): recalculada «Carga», su ``des_psf_`` cambia de hash y su ``des_epr_`` **no** (la huella es la misma): su objeto queda
        **«no al día»** sin cambiar su malla —el control 7 cuenta uno, resaltado, y el de «Taller», que no cambió, sigue al día—, y **Refrescar lo regenera con la cota nueva** y solo a
        él; la marca desaparece y otro Refrescar no recarga nada."""
        uid, other = self.uids[LOADING], self.uids[WORKSHOP]
        before = self.hashes("epr", "psf", name=LOADING)
        self.recompute()
        self.assertEqual(self.state_of(LOADING), "current")
        after = self.hashes("epr", "psf", name=LOADING)
        self.assertEqual(after["epr"], before["epr"], "su huella no depende de la cota: el hash de su tabla no cambia")
        self.assertNotEqual(after["psf"], before["psf"], "la superficie que deja, sí")
        self.assertEqual(str(self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name("epr", LOADING))[0][0]), uid,
                         "recalcular repone el mismo dato")
        pointers = self.pointers()
        self.mark()
        state, name = self.shown(uid)
        self.assertEqual(state, "OUTDATED")
        self.assertIn(NOT_UP_TO_DATE, name)
        self.assertEqual(self.shown(other)[0], "CURRENT")
        self.assertEqual(self.live.pending_count(), 1)
        self.assertEqual(self.pointers(), pointers, "marcar no vuelve a cargar nada")
        np.testing.assert_allclose(self.level(LOADING), 105.0, atol=1e-3)  # la malla es la de antes
        outcome = self.refresh_view()
        self.assertEqual(outcome.reloaded, (uid,), "solo se regenera la que no estaba al día")
        self.assertEqual(self.pointers()[other], pointers[other], "la otra, la misma de antes")
        np.testing.assert_allclose(self.level(LOADING), float(RAISED_M.replace(",", ".")), atol=1e-3)
        self.mark()
        state, name = self.shown(uid)
        self.assertEqual(state, "CURRENT")
        self.assertTrue(name.endswith("[VIGENTE]"), name)
        self.assertEqual(self.live.pending_count(), 0)
        self.assertEqual(self.refresh_view().reloaded, (), "lo que hay en la escena ya es lo de hoy")

    def test_z_disable_leaves_nothing_of_the_companions(self) -> None:
        """Principio 8: con los objetos en la escena, desactivar Geoblender quita los cargadores y la huella de Blender vuelve a la del principio de la sesión."""
        self.assertIsNotNone(self.views.loader_for(self.dprov.dataset_name("epr", LOADING)))
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        self.assertIsNone(self.views.loader_for(self.dprov.dataset_name("epr", LOADING)))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


class RoadCompanionsTest(Companions, road_ops.RoadOpsTest):
    """El proyecto de la prueba de la pista con «Pista de la carga» (trazada sobre ``Suave``) y su objeto en la escena."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.modules()
        cls.estore = _module("design.entity_store")

    def code_for(self, name: str) -> str:
        return self.code_of(name)

    def stations(self, name: str) -> np.ndarray:
        """El eje por estaciones de la pista ``name`` (x, y y la cota de la rasante), de su ``des_rdx_`` vigente, por SQL."""
        table = str(self.rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name("rdx", name))[0][0])
        return np.asarray(self.rows(f'SELECT x, y, level_m FROM "{table}" ORDER BY station_m'), dtype=np.float64)

    def axis_of(self, name: str) -> np.ndarray:
        """Los vértices de las aristas del eje (marcadas con ``gb_axis``) del objeto de la pista ``name``, vueltos a absolutos, en el orden de su malla."""
        obj = self.loaded()[self.uids[name]]
        edges, flags = self.mesh.mesh_edges(obj.data), self.mesh.edge_flags(obj.data, EDGE_FLAG)
        self.assertIsNotNone(flags, "las aristas del eje van marcadas")
        return self.world(obj)[np.unique(edges[flags])]

    def test_a_a_road_is_made_and_loaded_with_the_grade_line_in_the_z_of_its_axis(self) -> None:
        """RF-015-25, RF-017-23, RF-010-01, HU-017-2 (el mundo): «Pista de la carga» trazada sobre ``Suave`` con las órdenes reales; «Cargar en la vista» da su objeto con el eje 3D
        igual a las estaciones de su ``des_rdx_`` (la rasante en la Z), al día."""
        self.refresh()
        self.calculate_road(self.form(start_level=START_LEVEL))
        self.assertEqual(self.create_road(), {"FINISHED"})
        type(self).uids = {FIRST: str(self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name("epr", FIRST))[0][0])}
        self.load(FIRST)
        np.testing.assert_allclose(self.axis_of(FIRST), self.stations(FIRST), atol=1e-4, rtol=0)
        self.assertEqual(self.shown(self.uids[FIRST])[0], "CURRENT")

    def test_b_with_everything_up_to_date_nothing_is_marked_and_refresh_loads_nothing(self) -> None:
        """RF-010-02, RF-010-01: con la pista cargada y el proyecto como estaba, la marca en vivo no la pone «no al día» y Refrescar no la vuelve a cargar."""
        self.mark()
        self.assertEqual((self.shown(self.uids[FIRST])[0], self.live.pending_count()), ("CURRENT", 0))
        before = self.pointers()
        self.assertEqual(self.refresh_view().reloaded, ())
        self.assertEqual(self.pointers(), before)

    def test_c_a_changed_end_level_before_recalculating_is_stale_but_not_out_of_date(self) -> None:
        """RF-010-02, RF-010-01, RF-015-16: cambiada la cota de fin de la pista (de la natural a 101,2 m), queda **obsoleta** y su objeto lo dice en el nombre, pero su eje no ha
        cambiado: no está «no al día» y Refrescar no la recarga."""
        self.change("road", self.code_of(FIRST), "end_level_m", END_LEVEL)
        self.assertEqual(self.state_of(FIRST), "stale")
        old = self.axis_of(FIRST).copy()
        self.mark()
        state, name = self.shown(self.uids[FIRST])
        self.assertIn("OBSOLETO", name)
        self.assertNotIn(NOT_UP_TO_DATE, name)
        self.assertEqual((state, self.live.pending_count()), ("CURRENT", 0))
        self.assertEqual(self.refresh_view().reloaded, ())
        self.assertEqual(self.axis_of(FIRST).tolist(), old.tolist())
        type(self).old_axis = old

    def test_d_a_recalculated_grade_line_leaves_the_object_out_of_date_and_refresh_regenerates_it(self) -> None:
        """RF-010-02, RF-010-01, RF-015-25, RF-017-23 (E5): recalculada la pista, su ``des_rdx_`` y su ``des_psf_`` cambian de hash y su ``des_epr_`` **no**: su objeto queda
        **«no al día»** sin cambiar su malla (el control 7 cuenta uno) y **Refrescar lo regenera con la rasante nueva** en la Z de su eje (acaba en la cota que dio la persona); la
        marca desaparece y otro Refrescar no recarga nada."""
        uid = self.uids[FIRST]
        before = self.hashes("epr", "rdx", "psf", name=FIRST)
        self.recompute()
        self.assertEqual(self.state_of(FIRST), "current")
        after = self.hashes("epr", "rdx", "psf", name=FIRST)
        self.assertEqual(after["epr"], before["epr"], "su huella no depende de la rasante: el hash de su tabla no cambia")
        self.assertNotEqual(after["rdx"], before["rdx"], "la rasante cambió")
        self.assertNotEqual(after["psf"], before["psf"], "y la superficie que deja")
        self.mark()
        state, name = self.shown(uid)
        self.assertEqual(state, "OUTDATED")
        self.assertIn(NOT_UP_TO_DATE, name)
        self.assertEqual(self.live.pending_count(), 1)
        self.assertEqual(self.axis_of(FIRST).tolist(), self.old_axis.tolist(), "la malla es la de antes")
        self.assertEqual(self.refresh_view().reloaded, (uid,))
        stations = self.stations(FIRST)
        axis = self.axis_of(FIRST)
        np.testing.assert_allclose(axis, stations, atol=1e-4, rtol=0)
        self.assertAlmostEqual(stations[-1, 2], float(END_LEVEL.replace(",", ".")), delta=0.31, msg="la rasante llega a la cota que dio la persona (con su tolerancia)")
        self.assertGreater(np.abs(axis[:, 2] - self.old_axis[:, 2]).max(), 0.05, "la rasante cambió y el objeto la enseña")
        self.mark()
        state, name = self.shown(uid)
        self.assertEqual(state, "CURRENT")
        self.assertTrue(name.endswith("[VIGENTE]"), name)
        self.assertEqual(self.live.pending_count(), 0)
        self.assertEqual(self.refresh_view().reloaded, (), "lo que hay en la escena ya es lo de hoy")

    def test_z_disable_leaves_nothing_of_the_companions(self) -> None:
        """Principio 8: con el objeto de la pista en la escena, desactivar Geoblender quita el cargador y la huella de Blender vuelve a la del principio de la sesión."""
        self.assertIsNotNone(self.views.loader_for(self.dprov.dataset_name("epr", FIRST)))
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        self.assertIsNone(self.views.loader_for(self.dprov.dataset_name("epr", FIRST)))
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


for _class, _base in ((PlatformCompanionsTest, platform_ops.CreatePlatformTest), (RoadCompanionsTest, road_ops.RoadOpsTest)):
    for _name in dir(_base):  # sus pruebas son suyas: aquí solo los ayudantes
        if _name.startswith("test_"):
            setattr(_class, _name, None)
del _class, _base, _name


if __name__ == "__main__":
    unittest.main()
