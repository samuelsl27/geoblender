# SPDX-License-Identifier: GPL-3.0-or-later
"""Trabajos en segundo plano dentro de Blender (spec 004; plan 004 §5.1, §5.2.7 y §7).

T18 — el grupo ``jobs`` de las preferencias (``GEOBLENDER_PG_jobs_preferences``,
``bl/props/jobs.py``), enlazado con un ``PointerProperty`` en la **única**
``GeoblenderPreferences`` (``bl/props/preferences.py``; PLT-02):

- RF-004-04: ``max_parallel_jobs``, de 1 a 4 y 2 por defecto (el máximo del lanzador,
  ``jobs.runner.DEFAULT_MAX_SUBPROCESS``);
- RF-004-17: ``retention_days``, de 1 a 90 y 7 por defecto (DP-33);
- RF-004-24: ``runtime_source`` (``AUTO``, ``WHEELHOUSE``, ``PYPI``; ``AUTO``) y
  ``wheelhouse_dir`` (carpeta, vacía);
- RF-004-26: ``use_external_python`` (falso) y ``external_python`` (fichero, vacío), que
  en las preferencias se ve pero no se edita: lo guarda, tras comprobarlo,
  ``geoblender.jobs_set_external_python`` (T33).

Ninguna ruta por defecto (ARQ-15): las dos rutas empiezan vacías. Registrar y desregistrar
dos veces seguidas no deja clases ni propiedades (huella del principio de la sesión).

Se ejecuta con ``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import importlib
import sys
import unittest
from types import ModuleType

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import fingerprint_diff, module_name, state_fingerprint
from tests.support.fake_layout import draw

GROUP = "jobs"
GROUP_CLASS = "GEOBLENDER_PG_jobs_preferences"
# Valores por defecto del plan 004 §5.2.7, en el orden en que se dibujan.
DEFAULTS: dict[str, object] = {
    "max_parallel_jobs": 2,
    "retention_days": 7,
    "runtime_source": "AUTO",
    "wheelhouse_dir": "",
    "use_external_python": False,
    "external_python": "",
}
# Texto (msgid) con que se dibuja cada una: el nombre de la propiedad.
LABELS: dict[str, str] = {
    "max_parallel_jobs": "Jobs at once (separate process)",
    "retention_days": "Keep finished jobs (days)",
    "runtime_source": "Compute engine source",
    "wheelhouse_dir": "Wheel store folder",
    "use_external_python": "Use an external interpreter",
    "external_python": "External interpreter",
}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _addon_preferences() -> object:
    package = _module("bl").ADDON_PACKAGE
    return bpy.context.preferences.addons[package].preferences


def _extension_classes() -> list[str]:
    """Las clases de la extensión registradas en Blender (también los grupos de
    propiedades, que ``dir(bpy.types)`` no lista)."""
    prefix = module_name() + "."
    names: list[str] = []
    seen: set[type] = set()
    pending: list[type] = [bpy.types.bpy_struct]
    while pending:
        for cls in pending.pop().__subclasses__():
            if cls in seen:
                continue
            seen.add(cls)
            pending.append(cls)
            if (cls.__module__.startswith(prefix) and "bl_rna" in cls.__dict__
                    and getattr(cls, "is_registered", False)):
                names.append(cls.__name__)
    return sorted(names)


class JobsPreferencesTest(unittest.TestCase):
    """Con la extensión habilitada una vez para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.prefs = _addon_preferences()
        cls.i18n = _module("core.i18n")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def jobs(self) -> object:
        return getattr(self.prefs, GROUP)

    def test_group_with_defaults(self) -> None:
        """RF-004-04, RF-004-17, RF-004-24, RF-004-26: con la extensión habilitada desde
        ``gb_tests``, ``preferences.addons[bl.ADDON_PACKAGE].preferences.jobs`` existe con
        2, 7, ``AUTO``, vacío, falso y vacío; el máximo coincide con el del lanzador."""
        jobs = self.jobs()
        self.assertIsNotNone(jobs)
        self.assertEqual(jobs.bl_rna.identifier, GROUP_CLASS)
        self.assertEqual({name: getattr(jobs, name) for name in DEFAULTS}, DEFAULTS)
        runner = _module("jobs.runner")
        self.assertEqual(jobs.max_parallel_jobs, runner.DEFAULT_MAX_SUBPROCESS)

    def test_linked_in_the_single_preferences(self) -> None:
        """RF-004-04, RF-004-26 (PLT-02): el grupo es un ``PointerProperty`` ``jobs`` de la
        única clase de preferencias de la extensión, junto a ``core`` y ``ui``; la 004 no
        registra otra ``AddonPreferences``."""
        mine = [
            cls for cls in bpy.types.AddonPreferences.__subclasses__()
            if cls.__module__.startswith(module_name() + ".")
            and getattr(cls, "is_registered", False)
        ]
        self.assertEqual([cls.__name__ for cls in mine], ["GeoblenderPreferences"])
        rna = mine[0].bl_rna.properties[GROUP]
        self.assertEqual(rna.type, "POINTER")
        self.assertEqual(rna.fixed_type.identifier, GROUP_CLASS)
        inherited = set(bpy.types.AddonPreferences.bl_rna.properties.keys())
        groups = [p.identifier for p in mine[0].bl_rna.properties
                  if p.type == "POINTER" and p.identifier not in inherited]
        self.assertEqual(groups, ["core", "ui", GROUP])

    def test_types_limits_and_no_default_paths(self) -> None:
        """RF-004-04, RF-004-17, RF-004-24, RF-004-26: tipos, límites, subtipos y
        elementos del plan 004 §5.2.7; las rutas empiezan vacías (ninguna ruta por
        defecto, ARQ-15) y nada se anima."""
        props = self.jobs().bl_rna.properties
        inherited = set(bpy.types.PropertyGroup.bl_rna.properties.keys())  # rna_type, name
        self.assertEqual(sorted(p.identifier for p in props if p.identifier not in inherited),
                         sorted(DEFAULTS))
        expected_ints = {"max_parallel_jobs": (1, 4, 2), "retention_days": (1, 90, 7)}
        for name, (low, high, default) in expected_ints.items():
            with self.subTest(propiedad=name):
                self.assertEqual(props[name].type, "INT")
                self.assertEqual((props[name].hard_min, props[name].hard_max), (low, high))
                self.assertEqual(props[name].default, default)
        source = props["runtime_source"]
        self.assertEqual(source.type, "ENUM")
        self.assertEqual([item.identifier for item in source.enum_items],
                         ["AUTO", "WHEELHOUSE", "PYPI"])
        self.assertEqual(source.default, "AUTO")
        for name, subtype in (("wheelhouse_dir", "DIR_PATH"), ("external_python", "FILE_PATH")):
            with self.subTest(propiedad=name):
                self.assertEqual(props[name].type, "STRING")
                self.assertEqual(props[name].subtype, subtype)
                self.assertEqual(props[name].default, "")
        self.assertEqual(props["use_external_python"].type, "BOOLEAN")
        self.assertFalse(props["use_external_python"].default)
        for name in DEFAULTS:
            with self.subTest(propiedad=name):
                self.assertFalse(props[name].is_animatable)
                self.assertTrue(props[name].name)
                self.assertTrue(props[name].description)

    def test_out_of_range_is_clamped(self) -> None:
        """RF-004-04, RF-004-17: un máximo fuera de 1–4 o una retención fuera de 1–90 se
        quedan en el límite; el origen solo admite sus tres valores."""
        jobs = self.jobs()

        def restore() -> None:
            for name, value in DEFAULTS.items():
                setattr(jobs, name, value)

        self.addCleanup(restore)
        for name, value, expected in (
            ("max_parallel_jobs", 9, 4),
            ("max_parallel_jobs", 0, 1),
            ("retention_days", 365, 90),
            ("retention_days", -3, 1),
        ):
            with self.subTest(propiedad=name, valor=value):
                setattr(jobs, name, value)
                self.assertEqual(getattr(jobs, name), expected)
        jobs.runtime_source = "WHEELHOUSE"
        self.assertEqual(jobs.runtime_source, "WHEELHOUSE")
        with self.assertRaises(TypeError):
            jobs.runtime_source = "CONDA"
        self.assertEqual(jobs.runtime_source, "WHEELHOUSE")

    def test_drawn_in_preferences(self) -> None:
        """RF-004-04, RF-004-17, RF-004-24, RF-004-26: el panel de preferencias dibuja el
        grupo con su título y las seis propiedades, en ese orden y con los textos del
        catálogo de idioma; el intérprete externo se ve desactivado (lo guarda
        ``geoblender.jobs_set_external_python`` tras comprobarlo, T33)."""
        prefs = self.prefs
        cls = type(prefs)
        layout = draw(cls, bpy.context, core=prefs.core, ui=prefs.ui, jobs=prefs.jobs)
        tr = self.i18n.tr
        titles = [index for index, item in enumerate(layout.items)
                  if item.kind == "label" and item.text == tr("Background jobs")]
        self.assertEqual(len(titles), 1, layout.texts())
        drawn = [item for item in layout.of_kind("prop") if item.target in DEFAULTS]
        self.assertEqual([item.target for item in drawn], list(DEFAULTS))
        self.assertLess(titles[0], layout.items.index(drawn[0]))
        for item in drawn:
            with self.subTest(propiedad=item.target):
                self.assertEqual(item.text, tr(LABELS[item.target]))
                self.assertIs(item.options.get("translate"), False)
                self.assertEqual(item.enabled, item.target != "external_python")


class JobsPreferencesRegistrationTest(unittest.TestCase):
    """Cada prueba parte de la extensión deshabilitada y fuera de ``sys.modules``."""

    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)

    def assertSessionFingerprint(self) -> None:
        after = state_fingerprint()
        before = blender_ext.session_baseline()
        if after != before:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(before, after)))

    def test_register_and_unregister_twice(self) -> None:
        """RF-004-04, RF-004-17, RF-004-24, RF-004-26: registrar dos veces seguidas deja
        una sola clase del grupo y el grupo enlazado; desregistrar dos veces seguidas no
        deja clases ni propiedades (huella del principio de la sesión), y otra vuelta
        entera habilita el grupo con sus valores por defecto y lo vuelve a quitar."""
        for turn in (1, 2):
            with self.subTest(vuelta=turn):
                blender_ext.enable()
                props = _module("bl.props")
                props.register()  # segundo registro seguido
                self.assertEqual(_extension_classes().count(GROUP_CLASS), 1)
                jobs = getattr(_addon_preferences(), GROUP)
                self.assertEqual({name: getattr(jobs, name) for name in DEFAULTS},
                                 DEFAULTS)
                blender_ext.disable()
                props.unregister()  # segundo desregistro seguido
                sys.modules[module_name()].unregister()
                self.assertEqual(_extension_classes(), [])
                self.assertNotIn(module_name(), bpy.context.preferences.addons)
                self.assertSessionFingerprint()


if __name__ == "__main__":
    unittest.main()
