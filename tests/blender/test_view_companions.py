# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos compañeros de un cargador cuentan para «no al día» (spec 017, T31c; HU-017-1, HU-017-2; RF-010-01, RF-010-02; RF-015-25; plan 010 §5.3.1 A1).

Con el proyecto sintético de ``tests/support/views_fixtures.py`` (rejillas de 10 × 10 celdas): al cargador de las rejillas del proyecto (``gis_dtm_``) se le declara que la rejilla 01 se
dibuja también con la 02 (``views.register_loader(…, companions=…)``, dentro de ``mock.patch.dict``: al salir, el cargador de antes). Es lo mismo que el cargador de una entidad de
diseño con su superficie y su eje, sin los minutos de un proyecto de entidades (eso lo hace ``milestone_view_companions.py``, con una plataforma y una pista reales):

- el objeto **anota** al cargarse el uid y el hash de su compañero (``Object.geoblender.companions``) y el de un cargador sin compañeros, nada;
- **solo cambia el compañero** (la rejilla 01 conserva su hash): el objeto de la 01 queda «no al día» como el de la 02, el control 7 cuenta los dos, Refrescar (F5) los vuelve a cargar y
  la 01 anota el hash nuevo; con todo al día, nada se marca y Refrescar no recarga nada; lo cargado sin anotar (como antes de la T31c) no se compara;
- registrar con algo que no es una función es un error y ``extend_loader`` no pierde lo declarado; el cargador de una entidad de diseño los declara (su superficie y su eje) y el de lo
  alcanzable no. Desactivar Geoblender deja Blender como estaba: lo comprueban la huella de ``test_registration`` y el hito, con la propiedad nueva del objeto.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.trees import temp_folder

MAX_TICKS = 400


class ViewCompanionsTest(unittest.TestCase):
    """La extensión habilitada una vez; un proyecto de la prueba nuevo en cada una, con la rejilla 01 «dibujada con» la 02."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.views = vf.extension("bl.scene.views")
        self.live = vf.extension("bl.scene.live")
        self.refresh = vf.extension("bl.scene.refresh")
        self.ui = vf.extension("bl.ui.provenance")
        self.registry = vf.extension("core.datasets.registry")
        self.i18n = vf.extension("core.i18n")
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")
        self.folder = temp_folder(self, "gb-v017c-")
        self.data = vf.ViewsProject(self.folder)
        self.data.attach()
        self.addCleanup(self.data.close)
        self.addCleanup(blender_ext.load_file)
        self.first, self.second, self.third = (self.data.record(name) for name in self.data.names)
        patch = mock.patch.dict(self.views._LOADERS)  # noqa: SLF001 - el registro de cargadores, restaurado al salir
        patch.start()
        self.addCleanup(patch.stop)
        self.prefix = self.views.loader_for(self.first.name).prefix
        original = self.views.loaders()[self.prefix]
        self.views.unregister_loader(self.prefix)
        self.views.register_loader(self.prefix, original.kind, original.label, original.load, companions=self.drawn_with)

    # --- Ayudas de la prueba ------------------------------------------------------------------

    def drawn_with(self, conn: Any, record: Any) -> tuple[Any, ...]:
        """Lo que declara el cargador: la rejilla 01 se dibuja con la 02 (si está viva); las demás, con nada."""
        if record.name != self.first.name:
            return ()
        found = self.registry.get(conn, self.second.name)
        return () if found is None or not found.live else (found,)

    def only(self, uid: str) -> bpy.types.Object:
        (found,) = vf.objects_of(bpy.data, uid)
        return found

    def tick(self) -> None:
        """Un tic de los indicadores de la procedencia (lee el proyecto si cambió y pide la marca) y los de la marca, hasta que acaba."""
        self.assertEqual(self.ui.indicator_tick(), self.ui.INDICATOR_TICK_S)
        for _ in range(MAX_TICKS):
            if self.live.mark_tick() is None:
                return
        self.fail("la marca en vivo no acaba")

    def reload_all(self) -> Any:
        """«Refrescar» (F5) por sus pasos: lo que hizo (``RefreshOutcome``)."""
        found = None
        for step in self.refresh.refresh_steps(bpy.context, self.data.project):
            found = step.result or found
        return found

    def states(self) -> dict[str, str]:
        """``view_state`` de cada dato cargado, por nombre de su dato."""
        return {self.data.record(uid).name: obj.geoblender.view_state for uid, (obj,) in vf.loaded(bpy.data).items()}

    # --- Pruebas --------------------------------------------------------------------------------

    def test_the_object_notes_its_companions_and_a_changed_companion_makes_it_not_up_to_date(self) -> None:
        """RF-010-02, RF-010-01, RF-015-25 (T31c): al cargar, el objeto de la rejilla 01 anota el uid y el hash de la 02 y los demás, nada; con todo al día no se marca nada y
        Refrescar no recarga nada. Recalculada **solo la 02** (la 01 conserva su hash), la marca en vivo deja «no al día» **las dos**, el control 7 cuenta dos, la malla no cambia
        hasta Refrescar, que las vuelve a cargar a las dos, y la 01 anota entonces el hash nuevo de la 02; otro tic y no queda nada."""
        self.data.load(bpy.context, self.first.uid, self.second.uid, self.third.uid)
        notes = {uid: obj.geoblender.companions for uid, (obj,) in vf.loaded(bpy.data).items()}
        self.assertEqual(notes, {self.first.uid: f"{self.second.uid}={self.second.content_sha256}", self.second.uid: "", self.third.uid: ""})
        self.tick()
        self.assertEqual(self.states(), {name: "CURRENT" for name in self.data.names})
        self.assertEqual(self.live.pending_count(), 0)
        before = self.data.change_counter()
        self.assertEqual(self.reload_all().reloaded, ())
        self.assertEqual(self.data.change_counter(), before, "Refrescar no escribe en el proyecto")
        pointers = {uid: obj.as_pointer() for uid, (obj,) in vf.loaded(bpy.data).items()}

        again = self.data.recompute(self.second.name)
        self.assertNotEqual(again.content_sha256, self.second.content_sha256)
        self.assertEqual(self.data.record(self.first.name).content_sha256, self.first.content_sha256, "la 01 no cambia: solo su compañero")
        self.tick()
        self.assertEqual(self.states(), {self.first.name: "OUTDATED", self.second.name: "OUTDATED", self.third.name: "CURRENT"})
        self.assertIn("NO AL DÍA", self.only(self.first.uid).name)
        self.assertEqual(self.live.pending_count(), 2)
        self.assertEqual({uid: obj.as_pointer() for uid, (obj,) in vf.loaded(bpy.data).items()}, pointers, "marcar no vuelve a cargar nada")
        outcome = self.reload_all()
        self.assertEqual(sorted(outcome.reloaded), sorted([self.first.uid, self.second.uid]))
        self.assertEqual(self.only(self.first.uid).geoblender.companions, f"{self.second.uid}={again.content_sha256}", "anota lo de hoy")
        self.tick()
        self.assertEqual(self.states(), {name: "CURRENT" for name in self.data.names})
        self.assertEqual(self.live.pending_count(), 0)
        self.assertEqual(self.reload_all().reloaded, ())

    def test_what_was_loaded_without_the_note_is_not_compared(self) -> None:
        """RF-010-02 (T31c): un objeto cargado antes de la T31c (``companions`` vacío) no se compara: cambiar solo el compañero deja «no al día» a la 02 (cambió ella) y la 01 al día."""
        self.data.load(bpy.context, self.first.uid, self.second.uid)
        self.only(self.first.uid).geoblender.companions = ""
        self.data.recompute(self.second.name)
        self.tick()
        self.assertEqual(self.states(), {self.first.name: "CURRENT", self.second.name: "OUTDATED"})
        self.assertEqual(self.live.pending_count(), 1)

    def test_registering_a_loader_with_companions_and_what_extend_loader_keeps(self) -> None:
        """RF-010-02 (T31c): los datos compañeros se declaran al registrar el cargador con una función (otra cosa, ``TypeError``); los demás cargadores no declaran ninguno y
        ``extend_loader`` conserva lo declarado."""
        loaders = self.views.loaders()
        original = loaders[self.prefix]
        self.assertEqual(original.companions, self.drawn_with)
        entity = self.views.loader_for("des_epr_x")  # el de una entidad de diseño: lo declara con su superficie y su eje
        self.assertIsNotNone(entity)
        self.assertIsNotNone(entity.companions)
        self.assertIsNone(self.views.loader_for("des_acc_x").companions, "lo alcanzable es un dato por sí solo: su objeto sale solo de él")
        self.views.extend_loader(self.prefix, live=None)
        self.assertEqual(self.views.loaders()[self.prefix].companions, self.drawn_with)
        self.views.unregister_loader(self.prefix)
        with self.assertRaises(TypeError):
            self.views.register_loader(self.prefix, original.kind, original.label, original.load, companions="no")
        self.assertIsNone(self.views.loader_for(self.first.name), "el rechazo no deja registrado nada")


if __name__ == "__main__":
    unittest.main()
