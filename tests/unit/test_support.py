# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de los ayudantes de ``tests/support`` (spec 001)."""

import io
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path, PureWindowsPath

from tests.support import network, qgis, resources, runtime, timing, trees
from tests.support.repo import EXTENSION_DIR, ROOT, TOOLS_DIR, tools_on_path

RESOURCE = "recurso-de-prueba"
HINT = "tools/instalar_recurso.py --desde <carpeta>"


class RepoPathsTest(unittest.TestCase):
    def test_root_contains_extension_folder(self) -> None:
        """Spec 001, T01; RF-007-06: ``ROOT`` es la raíz del repositorio de código, con
        la carpeta de la extensión y los dos marcadores de la raíz, sin mirar la
        documentación."""
        tools_on_path()
        from gbtools import layout

        self.assertTrue((ROOT / layout.EXTENSION_DIR).is_dir())
        for marker in layout.ROOT_MARKERS:
            self.assertTrue((ROOT / marker).is_file(), marker)
        self.assertEqual(Path(__file__).resolve().parents[2], ROOT)
        self.assertEqual(EXTENSION_DIR, ROOT / layout.EXTENSION_DIR)
        self.assertEqual(TOOLS_DIR, ROOT / "tools")


def _run(*cases: type[unittest.TestCase]) -> tuple[unittest.TestResult, str]:
    """Ejecuta las clases con el ejecutor detallado; devuelve el resultado y la salida."""
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in cases
    )
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return result, stream.getvalue()


class RequiresTest(unittest.TestCase):
    """``resources.requires``: omisión por recurso opcional (plan 001 §5.2)."""

    def setUp(self) -> None:
        self.available = False
        self.calls: list[str] = []
        resources.register_resource(RESOURCE, lambda: self.available)
        self.addCleanup(resources.unregister_resource, RESOURCE)

    def _cases(self) -> tuple[type[unittest.TestCase], type[unittest.TestCase]]:
        calls = self.calls

        class ConMetodo(unittest.TestCase):
            @resources.requires(RESOURCE, HINT)
            def test_necesita(self) -> None:
                calls.append("metodo")

            def test_no_necesita(self) -> None:
                calls.append("libre")

        @resources.requires(RESOURCE, HINT)
        class ConClase(unittest.TestCase):
            @classmethod
            def setUpClass(cls) -> None:
                calls.append("setUpClass")

            def test_uno(self) -> None:
                calls.append("uno")

        return ConMetodo, ConClase

    def test_requires_skips_with_prefix(self) -> None:
        """RF-001-06: sin el recurso, la prueba (o la clase entera, sin su
        ``setUpClass``) se omite con «[ENTORNO] <recurso>: <orden que lo instala>», y
        la salida detallada lo muestra como ``skipped '[ENTORNO] …'``."""
        result, output = _run(*self._cases())
        reason = f"{resources.SKIP_PREFIX} {RESOURCE}: {HINT}"
        self.assertEqual(resources.SKIP_PREFIX, "[ENTORNO]")
        self.assertEqual(resources.skip_reason(RESOURCE, HINT), reason)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual([why for _test, why in result.skipped], [reason, reason])
        self.assertEqual(self.calls, ["libre"])
        self.assertEqual(output.count(f"skipped {reason!r}"), 2)

    def test_requires_runs_when_available(self) -> None:
        """RF-001-06: con el recurso disponible, las pruebas se ejecutan."""
        self.available = True
        result, _output = _run(*self._cases())
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.skipped, [])
        self.assertEqual(sorted(self.calls), ["libre", "metodo", "setUpClass", "uno"])

    def test_availability_checked_when_running(self) -> None:
        """RF-001-06: la disponibilidad se mira al ejecutar, no al decorar."""
        cases = self._cases()
        self.available = True
        result, _output = _run(*cases)
        self.assertEqual(result.skipped, [])

    def test_unknown_resource_is_an_error(self) -> None:
        """RF-001-06: un recurso sin comprobación registrada no se omite en silencio:
        la prueba da error (un nombre mal escrito no puede quedar siempre omitido)."""

        class Desconocido(unittest.TestCase):
            @resources.requires("recurso-sin-registrar", HINT)
            def test_x(self) -> None:
                pass

        result, output = _run(Desconocido)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.skipped, [])
        self.assertIn("recurso-sin-registrar", output)

    def test_requires_rejects_other_objects(self) -> None:
        """RF-001-06: solo decora clases de prueba o métodos."""
        with self.assertRaises(TypeError):
            resources.requires(RESOURCE, HINT)(object)


class ChildTempTest(unittest.TestCase):
    """``trees.child_temp`` y ``trees.child_env``: la carpeta temporal propia de un
    proceso hijo (hallazgo F7 de la ronda 4; convergencia, T61)."""

    def test_child_temp_is_private_and_removed(self) -> None:
        """RF-001-09: la carpeta del hijo es nueva, está dentro del ``%TEMP%`` de este
        proceso y no es él; al salir se borra entera, con lo que el hijo dejara en ella, y
        solo ella: una carpeta de al lado sigue ahí."""
        shared = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(prefix="geoblender-ajena-") as other:
            with trees.child_temp() as temp:
                self.assertTrue(temp.is_dir())
                self.assertEqual(list(temp.iterdir()), [])
                self.assertEqual(temp.resolve().parent, shared)
                (temp / "geoblender-pruebas-hijo").mkdir()
                (temp / "geoblender-pruebas-hijo" / "x.py").write_text("x", encoding="utf-8")
            self.assertFalse(temp.exists())
            self.assertTrue(Path(other).is_dir())

    def test_child_env_points_temp_variables(self) -> None:
        """RF-001-09: el entorno del hijo es una copia del que se da (o del de este
        proceso) con ``TMPDIR``, ``TEMP`` y ``TMP`` en su carpeta, y lo demás igual."""
        temp = Path(tempfile.gettempdir()) / "geoblender-hijo-x"
        env = trees.child_env({"BLENDER_USER_RESOURCES": "perfil", "TEMP": "otra"}, temp)
        self.assertEqual(trees.TEMP_VARIABLES, ("TMPDIR", "TEMP", "TMP"))
        expected = {"BLENDER_USER_RESOURCES": "perfil"}
        expected.update(dict.fromkeys(trees.TEMP_VARIABLES, str(temp)))
        self.assertEqual(env, expected)
        env = trees.child_env(None, temp)
        self.assertEqual(env["TEMP"], str(temp))
        self.assertEqual(env.get("PATH"), os.environ.get("PATH"))

    def test_child_runner_passes_child_env(self) -> None:
        """RF-001-09: el ejecutor del hijo llama al que se le da con la misma orden, la
        misma carpeta de trabajo y el mismo plazo, y el entorno de :func:`child_env`."""
        calls: list[tuple[object, ...]] = []

        def run(cmd: list[str], *, env=None, cwd=None, timeout=None) -> str:  # noqa: ANN001
            calls.append((cmd, env, cwd, timeout))
            return "hecho"

        temp = Path(tempfile.gettempdir()) / "geoblender-hijo-y"
        runner = trees.child_runner(temp, run)
        result = runner(["blender", "-b"], env={"A": "1"}, cwd=ROOT, timeout=5.0)
        self.assertEqual(result, "hecho")
        self.assertEqual(calls, [(["blender", "-b"], trees.child_env({"A": "1"}, temp), ROOT, 5.0)])


class FakeLayoutTest(unittest.TestCase):
    def test_draw_records_items(self) -> None:
        """Spec 002, T26: ``fake_layout.draw`` llama al ``draw`` de una clase con un
        *layout* simulado que anota etiquetas, operadores (con las propiedades que el
        ``draw`` les pone), propiedades, menús y separadores, también dentro de columnas y
        filas, y deja usar los métodos y atributos de la clase."""
        from tests.support import fake_layout

        class Menu:
            label = "Hola"

            def texto(self) -> str:
                return self.label

            def draw(self, context: object) -> None:
                self.layout.label(text=self.texto(), icon="INFO")
                column = self.layout.column(align=True)
                props = column.operator("geoblender.core_open_project", text="Abrir")
                props.directory = "x"
                column.row().prop(context, "valor", text="Valor")
                self.layout.separator()
                self.layout.menu("GEOBLENDER_MT_core_recent", text="Recientes")

        context = type("Context", (), {"valor": 7})()
        layout = fake_layout.draw(Menu, context)
        self.assertEqual([item.kind for item in layout.items],
                         ["label", "operator", "prop", "separator", "menu"])
        self.assertEqual(layout.texts(), ["Hola", "Abrir", "Valor", "Recientes"])
        (operator,) = layout.of_kind("operator")
        self.assertEqual((operator.target, operator.properties.directory),
                         ("geoblender.core_open_project", "x"))
        self.assertEqual(layout.of_kind("prop")[0].properties, 7)

    def test_items_keep_the_effective_state(self) -> None:
        """Spec 003, T01 (RF-003-07, RF-003-23): cada elemento anota si su *layout* estaba
        activo y habilitado al dibujarlo, también heredado de una fila o columna madre
        (en Blender, una fila desactivada desactiva todo lo de dentro), sin afectar a
        las filas hermanas ni a lo dibujado antes."""
        from tests.support.fake_layout import FakeLayout

        layout = FakeLayout()
        layout.operator("geoblender.ui_toggle_mode", text="Antes")
        row = layout.row()
        row.enabled = False
        row.operator("geoblender.res_compute_volume_between_surfaces", text="Cubicar")
        row.column().label(text="Dentro")
        sibling = layout.row()
        sibling.active = False
        sibling.operator("geoblender.ui_set_view", text="Planta")
        layout.operator("geoblender.ui_frame_work_window", text="Después")
        self.assertEqual(
            [(item.text, item.enabled, item.active) for item in layout.items],
            [
                ("Antes", True, True),
                ("Cubicar", False, True),
                ("Dentro", False, True),
                ("Planta", True, False),
                ("Después", True, True),
            ],
        )

    def test_other_layout_methods_are_recorded(self) -> None:
        """Spec 003, T01: los métodos de ``UILayout`` que no tiene a mano (``popover``,
        ``menu_contents``, ``template_ID_tabs``, ``operator_menu_enum``…) se anotan con
        su nombre como tipo y su primer argumento de texto como destino, para dibujar
        sin error las cabeceras de Blender; los atributos de forma (``ui_units_x``,
        ``scale_x``, ``alignment``) se pueden leer y poner."""
        from tests.support.fake_layout import FakeLayout

        layout = FakeLayout()
        layout.popover("GEOBLENDER_PT_ui_layouts", text="", icon="WORKSPACE")
        layout.row(align=True).menu_contents("TOPBAR_MT_editor_menus")
        layout.template_ID_tabs(object(), "workspace", new="workspace.add")
        props = layout.operator("geoblender.ui_toggle_mode", depress=True, icon_value=7)
        props.target = "BLENDER"
        layout.ui_units_x = 4.5
        layout.scale_x = 0.8
        self.assertEqual(
            [(item.kind, item.target) for item in layout.items],
            [
                ("popover", "GEOBLENDER_PT_ui_layouts"),
                ("menu_contents", "TOPBAR_MT_editor_menus"),
                ("template_ID_tabs", ""),
                ("operator", "geoblender.ui_toggle_mode"),
            ],
        )
        self.assertEqual(layout.items[0].icon, "WORKSPACE")
        self.assertEqual(layout.items[2].options["new"], "workspace.add")
        self.assertEqual(layout.items[3].options, {"depress": True, "icon_value": 7})
        self.assertEqual(layout.items[3].properties.target, "BLENDER")
        self.assertEqual((layout.ui_units_x, layout.scale_x, layout.alignment),
                         (4.5, 0.8, "EXPAND"))
        with self.assertRaises(AttributeError):
            layout._oculto  # noqa: B018 - lo privado no se inventa

    def test_items_keep_the_operator_context(self) -> None:
        """Spec 004, T40 (RF-004-20): cada elemento anota el ``operator_context`` con que se
        dibujó; como en Blender, es uno por *layout* raíz (``uiLayoutRoot``): ponerlo en
        una fila vale para lo que se dibuje después en cualquier fila del mismo *layout*, y
        no cambia lo dibujado antes ni otro *layout*."""
        from tests.support.fake_layout import FakeLayout

        layout = FakeLayout()
        layout.operator("geoblender.jobs_show_jobs", text="Antes")
        row = layout.row()
        row.operator_context = "EXEC_DEFAULT"
        row.label(text="Fila")
        layout.column().template_popup_confirm("geoblender.jobs_setup_runtime",
                                               text="Instalar", cancel_text="Cancelar")
        self.assertEqual([(item.text, item.operator_context) for item in layout.items],
                         [("Antes", "INVOKE_DEFAULT"), ("Fila", "EXEC_DEFAULT"),
                          ("Instalar", "EXEC_DEFAULT")])
        self.assertEqual(layout.operator_context, "EXEC_DEFAULT")
        self.assertEqual(FakeLayout().operator_context, "INVOKE_DEFAULT")


QGIS_TREE: dict[str, str] = {
    "bin/ogrinfo.exe": "",
    "apps/Python312/python.exe": "",
    "apps/Python312/Lib/site-packages/osgeo/__init__.py": "",
    "apps/Python312/Lib/site-packages/osgeo_utils/samples/validate_gpkg.py": "",
}


class QgisSupportTest(unittest.TestCase):
    """``tests.support.qgis``: el GDAL de QGIS de las pruebas de compatibilidad (spec
    002, T35)."""

    def test_resource_is_declared_and_registered(self) -> None:
        """RF-001-06: ``qgis`` está en la lista cerrada de recursos y tiene comprobación
        registrada (sin ella, ``requires`` daría error en lugar de omitir)."""
        self.assertIn(qgis.QGIS, resources.RESOURCES)
        with unittest.mock.patch.dict(os.environ, {qgis.ENV_QGIS_DIR: ""}):
            self.assertFalse(resources.is_available(qgis.QGIS))

    def test_install_found_only_when_complete(self) -> None:
        """RF-002-14: sin la variable, con una carpeta inexistente o sin alguno de
        ``ogrinfo``, el Python, ``osgeo`` o ``validate_gpkg.py``, no hay instalación
        (la prueba con GDAL se omite); completa, sí, con su Python de ``apps``."""
        self.assertIsNone(qgis.find_install({}))
        self.assertIsNone(qgis.find_install({qgis.ENV_QGIS_DIR: "  "}))
        with trees.temp_tree(QGIS_TREE) as root:
            environ = {qgis.ENV_QGIS_DIR: str(root)}
            install = qgis.find_install(environ)
            self.assertIsNotNone(install)
            assert install is not None
            self.assertEqual(install.python_home, root / "apps" / "Python312")
            self.assertEqual(install.tool("ogrinfo"), root / "bin" / "ogrinfo.exe")
            self.assertIsNone(qgis.find_install({qgis.ENV_QGIS_DIR: str(root / "no")}))
        for missing in QGIS_TREE:
            partial = {rel: text for rel, text in QGIS_TREE.items() if rel != missing}
            with self.subTest(falta=missing), trees.temp_tree(partial) as root:
                self.assertIsNone(qgis.find_install({qgis.ENV_QGIS_DIR: str(root)}))

    def test_gdal_env_ignores_the_workstation_proj_and_python(self) -> None:
        """RF-002-14 (Silvestre TOP-05): el entorno de GDAL es el de QGIS: su ``bin``
        primero en ``PATH``, su ``PROJ_DATA`` y su ``GDAL_DATA``, su ``PYTHONHOME``, sin
        ``.aux.xml``, sin ``__pycache__``, y sin el ``PROJ_LIB`` ni las demás variables
        ``PROJ_*``, ``GDAL_*``, ``PYTHON*`` y ``OSGEO4W_*`` del puesto."""
        base = {
            "PROJ_LIB": "postgis",
            "proj_network": "ON",
            "GDAL_DATA": "otra",
            "PYTHONPATH": "otra",
            "PYTHONSTARTUP": "x.py",
            "OSGEO4W_ROOT": "otra",
            "PATH": "otra",
            "SystemRoot": "W",
            "TEMP": "temporal",
        }
        with trees.temp_tree(QGIS_TREE) as root:
            install = qgis.find_install({qgis.ENV_QGIS_DIR: str(root)})
            assert install is not None
            env = qgis.gdal_env(install, base)
        for name in ("PROJ_LIB", "proj_network", "PYTHONPATH", "PYTHONSTARTUP"):
            with self.subTest(variable=name):
                self.assertNotIn(name, env)
        self.assertEqual(env["TEMP"], "temporal")
        self.assertEqual(env["PATH"].split(os.pathsep)[0], str(root / "bin"))
        self.assertNotIn("otra", env["PATH"])
        self.assertEqual(env["PROJ_DATA"], str(root / "share" / "proj"))
        self.assertEqual(env["GDAL_DATA"], str(root / "apps" / "gdal" / "share" / "gdal"))
        self.assertEqual(env["OSGEO4W_ROOT"], str(root))
        self.assertEqual(env["PYTHONHOME"], str(root / "apps" / "Python312"))
        self.assertEqual(env["GDAL_PAM_ENABLED"], "NO")
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")


class RuntimeSupportTest(unittest.TestCase):
    """``tests.support.runtime``: el motor de cálculo de pruebas (spec 004, T30)."""

    def test_resource_is_declared_and_registered(self) -> None:
        """RF-004-28, RF-001-06: ``runtime`` está en la lista cerrada de recursos y tiene
        comprobación registrada; con ``GEOBLENDER_TEST_RUNTIME_SITE`` en una carpeta que
        no existe no hay motor, y en una que existe, esa es su carpeta ``site``; la orden
        que lo crea es ``tools/make_runtime.py``."""
        self.assertIn(runtime.RUNTIME, resources.RESOURCES)
        self.assertIn("tools/make_runtime.py", runtime.RUNTIME_HINT)
        variable = runtime.ENV_TEST_RUNTIME_SITE
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.dict(os.environ, {variable: str(Path(tmp) / "no")}):
                self.assertFalse(resources.is_available(runtime.RUNTIME))
            with unittest.mock.patch.dict(os.environ, {variable: tmp}):
                self.assertTrue(resources.is_available(runtime.RUNTIME))
                self.assertEqual(runtime.runtime_site(), Path(tmp))


class NetworkSupportTest(unittest.TestCase):
    """``tests.support.network``: la carpeta de pruebas de la red (spec 008, T42)."""

    def _environ(self, folder: object, mirror: object = None) -> dict[str, str]:
        found = {network.NET_TEST_DIR_ENV: str(folder)}
        if mirror is not None:
            found[network.NAS_MIRROR_ENV] = str(mirror)
        return found

    def test_resource_is_declared_and_registered(self) -> None:
        """RNF-008-04, RNF-008-10, RF-001-06: ``red`` está en la lista cerrada de recursos y
        tiene comprobación registrada: sin la variable, o con una carpeta que no existe, no
        hay red; con una que existe, esa es la carpeta de pruebas."""
        self.assertIn(network.NET, resources.RESOURCES)
        self.assertIn(network.NET_TEST_DIR_ENV, network.NET_HINT)
        with tempfile.TemporaryDirectory() as tmp:
            empty = {key: value for key, value in os.environ.items()
                     if key != network.NET_TEST_DIR_ENV}
            with unittest.mock.patch.dict(os.environ, empty, clear=True):
                self.assertFalse(resources.is_available(network.NET))
            with unittest.mock.patch.dict(os.environ, self._environ(Path(tmp) / "no")):
                self.assertFalse(resources.is_available(network.NET))
            with unittest.mock.patch.dict(os.environ, self._environ(tmp)):
                self.assertTrue(resources.is_available(network.NET))
                self.assertEqual(network.net_test_dir(), Path(os.path.realpath(tmp)))

    def test_dossiers_and_mirror_are_refused(self) -> None:
        """RNF-008-04, RNF-008-10 (T42): una carpeta de pruebas que es la de los expedientes de
        clientes o está dentro del espejo del repositorio es un error (nunca una omisión ni
        una escritura); otra con un nombre que empieza como el espejo vale."""
        dossiers = PureWindowsPath("Q:/", network.DOSSIERS, "pruebas")
        with self.assertRaisesRegex(ValueError, "expedientes"):
            network.check_net_dir(str(dossiers))
        with tempfile.TemporaryDirectory() as tmp:
            mirror = Path(tmp) / "Geo_espejo"
            (mirror / "pruebas").mkdir(parents=True)
            sibling = Path(tmp) / "Geo_espejo_pruebas"
            sibling.mkdir()
            for inside in (mirror, mirror / "pruebas"):
                with self.assertRaisesRegex(ValueError, "espejo"):
                    network.net_test_dir(self._environ(inside, mirror))
            self.assertEqual(network.net_test_dir(self._environ(sibling, mirror)),
                             Path(os.path.realpath(sibling)))

    def test_net_tmp_removes_only_its_folder(self) -> None:
        """RNF-008-04, RNF-008-10 (T42): cada prueba trabaja en una subcarpeta temporal propia de
        la carpeta de pruebas, que se borra entera al salir; lo demás no se toca."""
        with tempfile.TemporaryDirectory() as tmp:
            kept = Path(tmp) / "LEEME.txt"
            kept.write_text("carpeta de pruebas\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, self._environ(tmp)):
                with network.net_tmp("gb-prueba-") as folder:
                    self.assertEqual(folder.parent, Path(os.path.realpath(tmp)))
                    (folder / "sub").mkdir()
                    (folder / "sub" / "dato.bin").write_bytes(b"x")
            self.assertFalse(folder.exists())
            self.assertEqual(sorted(path.name for path in Path(tmp).iterdir()), ["LEEME.txt"])


class _SlowAction:
    """Una acción que «dura» lo siguiente de ``durations`` (la última se repite) en el
    reloj simulado :meth:`clock`, que da 0 al empezar cada medida y la duración al
    terminarla (sin sumas: valores exactos); cuenta cuántas veces se ejecuta."""

    def __init__(self, durations: list[float]) -> None:
        self.durations = list(durations)
        self.last = 0.0
        self.calls = 0
        self.ticks = 0

    def clock(self) -> float:
        self.ticks += 1
        return 0.0 if self.ticks % 2 else self.last

    def __call__(self) -> None:
        self.last = self.durations[min(self.calls, len(self.durations) - 1)]
        self.calls += 1


class TimingSupportTest(unittest.TestCase):
    """``tests.support.timing``: las pruebas de un presupuesto de tiempo con la máquina
    cargada (spec 006, T38)."""

    def test_best_of_measures_again_while_over_budget(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T38): la mejor de tres medidas y, mientras
        ninguna quepa en el presupuesto (la máquina cargada por las demás partes de
        ``tools/check.py``), otra más, hasta ``MAX_ATTEMPTS``; con una que cabe, para. El
        presupuesto no cambia: si ninguna cabe, devuelve la mejor, que no cabe."""
        budget = 0.050
        cases = {
            "en reposo": ([0.025, 0.026, 0.024, 0.001], 3, 0.024),
            "cargada a ratos": ([0.080, 0.070, 0.060, 0.090, 0.040, 0.001], 5, 0.040),
            "justo en el presupuesto": ([0.060, 0.070, 0.050, 0.001], 3, 0.050),
            "cargada siempre": ([0.060], timing.MAX_ATTEMPTS, 0.060),
        }
        for name, (durations, calls, best) in cases.items():
            with self.subTest(caso=name):
                action = _SlowAction(durations)
                found = timing.best_of(action, budget, clock=action.clock)
                self.assertEqual(action.calls, calls)
                self.assertEqual(found, best)
        self.assertEqual(timing.ATTEMPTS, 3)
        self.assertGreater(timing.MAX_ATTEMPTS, timing.ATTEMPTS)
        action = _SlowAction([0.060])
        found = timing.best_of(action, budget, attempts=1, max_attempts=2, clock=action.clock)
        self.assertEqual((action.calls, found), (2, 0.060))
        for attempts, most in ((0, 5), (3, 2)):
            with self.subTest(intentos=attempts, maximo=most), self.assertRaises(ValueError):
                timing.best_of(_SlowAction([0.0]), budget, attempts=attempts, max_attempts=most)


if __name__ == "__main__":
    unittest.main()
