# SPDX-License-Identifier: GPL-3.0-or-later
"""``gis.masks`` reexporta sin importar hasta el primer uso (spec 012, T38; RNF-001-03).

``gis.masks.provenance`` es la declaración ligera que ``bl`` registra al habilitar la extensión, e
importarla importa el paquete ``gis.masks``. Si el paquete cargase ``combine``, ``overlay`` y
``zones`` (con la geometría 2D), habilitar Geoblender pagaría unos 8 ms que no usa hasta la primera
compilación. Los nombres de ``__all__`` se resuelven al pedirlos (PEP 562):

- en un proceso nuevo, importar ``gis.masks.provenance`` no carga ningún otro módulo de
  ``gis.masks`` (ni ``gis.polygons`` ni ``gis.coverage``, que la declaración no usa);
- cada nombre de ``__all__`` es el objeto de su módulo (``from geoblender.gis.masks import Runs``
  sigue valiendo), lo que se pide queda guardado, ``dir()`` los lista y un nombre que no es suyo da
  ``AttributeError``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from tests.support.package import PACKAGE_NAME, import_geoblender
from tests.support.repo import ROOT
from tests.support.trees import child_env, child_temp

CHILD = r"""
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from tests.support.package import PACKAGE_NAME, import_geoblender

import_geoblender("gis.masks.provenance")
prefix = PACKAGE_NAME + "."
print(json.dumps(sorted(name.removeprefix(prefix) for name in sys.modules
                        if name.startswith(prefix + "gis"))))
"""


class LazyExportsTest(unittest.TestCase):
    def test_provenance_loads_no_other_module_of_masks(self) -> None:
        """RNF-001-03: en un proceso nuevo, importar ``gis.masks.provenance`` (lo que registra
        ``bl``) carga el paquete y esa declaración, y ninguno de los módulos de cálculo de
        ``gis.masks`` ni la geometría 2D."""
        flags = ["-B", "-s", "-X", "utf8", *(["-S"] if sys.flags.no_site else [])]
        with child_temp() as temp:
            done = subprocess.run(
                [sys.executable, *flags, "-c", CHILD, str(ROOT)], capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=child_env(None, temp), timeout=120,
                check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        loaded = json.loads(done.stdout)
        masks = [name for name in loaded if name.startswith("gis.masks")]
        self.assertEqual(masks, ["gis.masks", "gis.masks.provenance"])
        self.assertNotIn("gis.polygons", loaded)
        self.assertNotIn("gis.coverage", loaded)

    def test_every_exported_name_is_the_object_of_its_module(self) -> None:
        """RNF-001-03: cada nombre de ``__all__`` se resuelve en su módulo (``combine``, ``overlay``
        o ``zones``) y es el mismo objeto; ``from … import nombre`` y ``getattr`` valen y el nombre
        queda guardado en el paquete."""
        masks = import_geoblender("gis.masks")
        sources = {"combine": import_geoblender("gis.masks.combine"),
                   "overlay": import_geoblender("gis.masks.overlay"),
                   "zones": import_geoblender("gis.masks.zones")}
        self.assertEqual(sorted(masks.__all__), sorted(masks._SOURCES))
        for name in masks.__all__:
            with self.subTest(nombre=name):
                module = sources[masks._SOURCES[name]]
                self.assertIs(getattr(masks, name), getattr(module, name))
                self.assertIs(vars(masks)[name], getattr(module, name))
        namespace: dict[str, object] = {}
        exec(f"from {PACKAGE_NAME}.gis.masks import Runs, prepare, limits_report", namespace)
        self.assertIs(namespace["Runs"], sources["zones"].Runs)
        self.assertIs(namespace["prepare"], sources["combine"].prepare)
        self.assertIs(namespace["limits_report"], sources["overlay"].limits_report)

    def test_unknown_names_and_dir(self) -> None:
        """RNF-001-03: un nombre que no es de ``__all__`` da ``AttributeError`` (también para
        ``hasattr``), un módulo del paquete se sigue importando con ``from … import``, y ``dir()``
        lista los nombres de ``__all__`` aunque no se hayan pedido."""
        masks = import_geoblender("gis.masks")
        with self.assertRaises(AttributeError):
            masks.no_existe
        self.assertFalse(hasattr(masks, "no_existe"))
        namespace: dict[str, object] = {}
        exec(f"from {PACKAGE_NAME}.gis.masks import combine as module", namespace)
        self.assertIs(namespace["module"], import_geoblender("gis.masks.combine"))
        self.assertTrue(set(masks.__all__) <= set(dir(masks)))


if __name__ == "__main__":
    unittest.main()
