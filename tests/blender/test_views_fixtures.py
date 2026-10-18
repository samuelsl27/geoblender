# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de prueba de la vista (spec 010, T02; plan 010 §5.1 y §7.1):
``tests/support/views_fixtures.py``, con que las pruebas de la 010 preparan los casos de su §8
(RF-010-01, RF-010-02).

Un proyecto sintético pequeño (ventana de 200 × 200 m, paso 1 m) con tres rejillas de
10 × 10 celdas escritas con ``gis.store.ResultWriter`` y la procedencia de la 008, abierto en la
sesión. Cada ayuda se comprueba en el proyecto (el estado del dato en ``gb_dataset``, su hash,
su obsolescencia en ``gb_stale``, su sucesor y su entrada) y en la escena:

- cargar con ``views.load_datasets`` deja un objeto por rejilla con su dato, su hash y su
  estado;
- recalcular una rejilla con otros valores: el mismo dato con otro hash (lo cargado sigue
  mostrando el anterior);
- cambiar el parámetro de resultado de la 006 que lee su operación
  (``gis.resample.min_valid_fraction``): esa rejilla, obsoleta y con el mismo hash; las demás,
  no;
- importar un MDT y sustituir su entrada: lo importado de la anterior, «sustituido» con su
  hash, y su sucesor, lo importado de la nueva; descartar otra entrada: lo suyo, «descartado»
  y sin sucesor; nada se borra de la escena;
- borrar el fichero de una rejilla: «falta» tras la comprobación de los datos de la 008;
- los objetos del usuario, sueltos y en «99 Trabajo», sin dato del proyecto;
- el contador de cambios de la cabecera de ``project.gpkg``: lo sube cada ayuda que escribe y
  no lo cambia ninguna lectura (las de las ayudas, cargar en la vista y leerlo).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

import bpy

from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.trees import temp_folder

CURRENT = "current"


class ViewsFixturesTest(unittest.TestCase):
    """La extensión habilitada una vez; un proyecto de la prueba nuevo en cada una."""

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
        self.data = vf.ViewsProject(temp_folder(self, "gb-v010-"))
        self.data.attach()
        self.addCleanup(self.data.close)
        self.addCleanup(blender_ext.load_file)

    # --- Ayudas de la prueba ------------------------------------------------------------------

    def assertReadsKeepCounter(self, *reads: Callable[[], Any]) -> None:
        """Ninguna de las lecturas ``reads`` cambia el contador de cambios del proyecto."""
        before = self.data.change_counter()
        for read in reads:
            read()
        self.assertEqual(self.data.change_counter(), before)

    def assertWrites(self, change: Callable[[], Any]) -> Any:
        """``change`` escribe en el proyecto (sube el contador de cambios); su resultado."""
        before = self.data.change_counter()
        result = change()
        self.assertGreater(self.data.change_counter(), before)
        return result

    def only(self, uid: str) -> bpy.types.Object:
        (found,) = vf.objects_of(bpy.data, uid)
        return found

    def assertShows(self, obj: bpy.types.Object, record: Any) -> None:
        """``obj`` muestra el contenido de ``record`` tal como se cargó."""
        props = obj.geoblender
        self.assertEqual((props.dataset_uid, props.project_uid, props.content_sha256),
                         (record.uid, self.data.project.uid, record.content_sha256))

    def loaded_state(self) -> list[tuple[str, str, str, str]]:
        """Lo cargado en la escena: nombre, dato, hash y estado de cada objeto."""
        return sorted((obj.name, obj.geoblender.dataset_uid, obj.geoblender.content_sha256,
                       obj.geoblender.status) for obj in bpy.data.objects
                      if obj.geoblender.dataset_uid)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_project_grids_and_loading(self) -> None:
        """RF-010-01, RF-010-02 (T02): el proyecto tiene la ventana de 200 × 200 m con paso
        1 m y las tres rejillas vigentes (``gis_dtm_``, cada una con su fichero y otro hash);
        cargarlas con ``views.load_datasets`` deja un objeto por rejilla con su dato, su
        proyecto, su hash y «vigente», sin obsoleto. Ni leer las ayudas, ni cargar, ni leer
        el contador lo cambian."""
        data = self.data
        project = data.project
        window = project.window
        self.assertEqual((window.xmax - window.xmin, window.ymax - window.ymin),
                         (vf.SIZE_M, vf.SIZE_M))
        self.assertEqual(project.grid_step_m, vf.STEP_M)
        self.assertEqual(len(data.names), vf.GRIDS)
        records = [data.record(name) for name in data.names]
        for name, record in zip(data.names, records, strict=True):
            with self.subTest(dato=name):
                self.assertTrue(name.startswith("gis_dtm_"))
                self.assertEqual((record.name, str(record.status)), (name, CURRENT))
                self.assertTrue(Path(data.root, *record.locator.split("/")).is_file())
                self.assertFalse(data.stale(name))
                self.assertEqual(data.successor(record.uid).uid, record.uid)
        self.assertEqual(len({record.content_sha256 for record in records}), vf.GRIDS)

        outcome = None

        def load() -> None:
            nonlocal outcome
            outcome = data.load(bpy.context)

        self.assertReadsKeepCounter(
            lambda: [data.record(name) for name in data.names],
            lambda: [data.stale(name) for name in data.names],
            lambda: [data.successor(name) for name in data.names],
            load, lambda: vf.loaded(bpy.data), data.change_counter)
        self.assertEqual((outcome.loaded, outcome.errors), (data.names, ()))
        for record in records:
            with self.subTest(dato=record.name):
                obj = self.only(record.uid)
                self.assertShows(obj, record)
                self.assertEqual((obj.geoblender.status, obj.geoblender.stale),
                                 ("CURRENT", False))
        self.assertEqual(sorted(vf.loaded(bpy.data)), sorted(r.uid for r in records))

    def test_recompute_keeps_the_dataset_with_another_hash(self) -> None:
        """RF-010-01, RF-010-02 (T02; spec §8, «se recalcula el MDT con su vista cargada»):
        recalcular una rejilla con otros valores la deja con el mismo dato, vigente, con otro
        hash y otra operación, sin obsoleto; las demás, igual; lo cargado sigue mostrando el
        contenido anterior."""
        data = self.data
        name, other = data.names[1], data.names[2]
        before, kept = data.record(name), data.record(other)
        data.load(bpy.context)
        scene = self.loaded_state()
        after = self.assertWrites(lambda: data.recompute(name))
        self.assertEqual((after.uid, after.name, str(after.status)), (before.uid, name, CURRENT))
        self.assertNotEqual(after.content_sha256, before.content_sha256)
        self.assertNotEqual(after.operation_uid, before.operation_uid)
        self.assertEqual(data.record(name), after)
        self.assertFalse(data.stale(name))
        self.assertEqual(data.record(other), kept)
        self.assertEqual(self.loaded_state(), scene)
        self.assertShows(self.only(before.uid), before)
        self.assertReadsKeepCounter(lambda: data.record(name), lambda: data.stale(name))

    def test_parameter_leaves_only_its_grid_stale(self) -> None:
        """RF-010-02 (T02; spec §8, «un dato cargado queda obsoleto»): cambiar el parámetro de
        resultado de la 006 que leyó la operación de la primera rejilla
        (``gis.resample.min_valid_fraction``) la deja obsoleta, vigente y con el mismo hash;
        las demás no lo leyeron y no lo están; la escena no cambia."""
        data = self.data
        first = data.names[0]
        records = {name: data.record(name) for name in data.names}
        data.load(bpy.context)
        scene = self.loaded_state()
        stale = self.assertWrites(data.make_stale)
        self.assertEqual(stale, (first,))
        self.assertTrue(data.stale(first))
        for name in data.names[1:]:
            self.assertFalse(data.stale(name))
        self.assertEqual({name: data.record(name) for name in data.names}, records)
        self.assertEqual(self.loaded_state(), scene)
        self.assertReadsKeepCounter(lambda: data.stale(first))

    def test_substituted_and_discarded_inputs(self) -> None:
        """RF-010-01, RF-010-02 (T02; spec §8, «lo importado de una entrada actualizada» y «un
        dato que se descartó»): importar un MDT deja lo importado vigente con su entrada;
        sustituir esa entrada por otra con otros valores deja lo de la anterior «sustituido»,
        con su nombre y su hash, y lo de la nueva vigente, con otro hash, como su sucesor; y
        descartar otra entrada deja lo suyo «descartado», sin sucesor. Las entradas, con su
        estado; los objetos cargados siguen en la escena."""
        data = self.data
        imported = self.assertWrites(lambda: data.import_grid("MDT Fuente"))
        self.assertTrue(imported.name.startswith("gis_src_"))
        self.assertEqual(str(imported.status), CURRENT)
        self.assertEqual(data.input_status(imported.input_uid), CURRENT)
        dropped = data.import_grid("MDT Descarte")
        self.assertEqual(data.load(bpy.context, imported.uid, dropped.uid).errors, ())
        scene = self.loaded_state()

        old, new = self.assertWrites(lambda: data.substitute("MDT Fuente"))
        self.assertEqual((old.uid, old.name, old.content_sha256),
                         (imported.uid, imported.name, imported.content_sha256))
        self.assertEqual(str(old.status), "superseded")
        self.assertEqual((new.name, str(new.status)), (imported.name, CURRENT))
        self.assertNotEqual(new.uid, old.uid)
        self.assertNotEqual(new.content_sha256, old.content_sha256)
        self.assertNotEqual(new.input_uid, old.input_uid)
        self.assertEqual(data.successor(old.uid), new)
        self.assertEqual(data.input_status(old.input_uid), "superseded")
        self.assertEqual(data.input_status(new.input_uid), CURRENT)

        gone = self.assertWrites(lambda: data.discard("MDT Descarte"))
        self.assertEqual((gone.uid, str(gone.status)), (dropped.uid, "discarded"))
        self.assertIsNone(data.successor(gone.uid))
        self.assertEqual(data.input_status(gone.input_uid), "discarded")
        self.assertEqual(self.loaded_state(), scene)
        self.assertShows(self.only(old.uid), imported)
        self.assertShows(self.only(gone.uid), dropped)
        self.assertReadsKeepCounter(lambda: data.successor(old.uid),
                                    lambda: data.input_status(old.input_uid))

    def test_deleted_file_is_missing(self) -> None:
        """RF-010-01 (T02; D-11 del plan): borrar el fichero de una rejilla la deja «falta»
        (la comprobación de los datos de la 008) con su hash; las demás, vigentes; su objeto
        sigue en la escena."""
        data = self.data
        name = data.names[2]
        before = data.record(name)
        data.load(bpy.context)
        scene = self.loaded_state()
        path = Path(data.root, *before.locator.split("/"))
        missing = self.assertWrites(lambda: data.delete_file(name))
        self.assertFalse(path.exists())
        self.assertEqual((missing.uid, missing.content_sha256, str(missing.status)),
                         (before.uid, before.content_sha256, "missing"))
        self.assertEqual([str(data.record(other).status) for other in data.names[:2]],
                         [CURRENT, CURRENT])
        self.assertEqual(self.loaded_state(), scene)

    def test_user_objects_and_work_collection(self) -> None:
        """RF-010-01 (T02; spec §8, «objetos del usuario y 99 Trabajo»): los objetos del
        usuario, sueltos en la escena y en la colección «99 Trabajo», no son de ningún dato
        del proyecto; lo cargado, sí; crearlos no escribe en el proyecto."""
        data = self.data
        scene = bpy.context.scene

        def create() -> None:
            data.load(bpy.context, data.names[0])
            self.created = vf.user_objects(bpy.data, scene)

        self.assertReadsKeepCounter(create)
        work, objects = self.created
        self.assertEqual(work.name, vf.WORK_COLLECTION)
        self.assertIn(work, scene.collection.children.values())
        self.assertGreater(len(work.objects), 0)
        loose = [obj for obj in objects if obj.name not in work.objects]
        self.assertGreater(len(loose), 0)
        self.assertTrue(all(obj.name in scene.collection.objects for obj in loose))
        self.assertTrue(all(obj.geoblender.dataset_uid == "" for obj in objects))
        self.assertTrue(any(obj.type == "MESH" for obj in objects))
        self.assertEqual(list(vf.loaded(bpy.data)), [data.record(data.names[0]).uid])


if __name__ == "__main__":
    unittest.main()
