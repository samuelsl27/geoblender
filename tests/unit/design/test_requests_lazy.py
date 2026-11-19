# SPDX-License-Identifier: GPL-3.0-or-later
"""Las peticiones de los cuatro tipos de la 016 no se crean al habilitar (spec 016, T51;
RNF-001-03 de la spec 001; plan 016 §7.4).

Cada ``@dataclass(frozen=True, slots=True)`` se crea en ≈ 0,5–1 ms al importar el módulo, y las seis de
la 016 (:class:`StockpileFields`, :class:`StockpileRequest`, :class:`RemovalRequest`,
:class:`ButtressFields`, :class:`ButtressRequest` y :class:`BodyRequest`) eran 4,2 ms de los 25 ms con
los que la 016 subió el habilitado de Geoblender (0,487 s → 0,512 s). Habilitar solo necesita los
enumerados y las peticiones de la 013 a la 015 de ``design.model``; las seis viven en
``design.supported_requests``, que ``design.model`` ofrece con su nombre de siempre al pedirlas
(``__getattr__``, PEP 562, como ``gis.masks``): ``from geoblender.design.model import
StockpileRequest`` y ``model.StockpileRequest`` siguen valiendo, y son el mismo objeto.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

model = import_geoblender("design.model")
requests = import_geoblender("design.supported_requests")

NAMES = ("BodyRequest", "ButtressFields", "ButtressRequest", "RemovalRequest", "StockpileFields",
         "StockpileRequest")

PROBE = """
import sys
from tests.support.package import import_geoblender
model = import_geoblender("design.model")
assert "geoblender.design.supported_requests" not in sys.modules, "cargado al importar design.model"
assert "geoblender.design.model" in sys.modules
request = model.StockpileRequest
assert "geoblender.design.supported_requests" in sys.modules, "no se cargó al pedirla"
assert request.__name__ == "StockpileRequest"
print("ok")
"""


class LazyRequestsTest(unittest.TestCase):
    def test_a_the_six_requests_are_the_same_objects_under_their_old_name(self) -> None:
        """RF-016-02, RF-016-11, RF-016-17, RF-016-20: cada petición se pide a ``design.model``
        como siempre (atributo, ``from … import``, ``import *`` y ``dir``) y es la de
        ``design.supported_requests``, que la define; un nombre que no es de nadie sigue siendo
        un ``AttributeError`` (y un ``ImportError`` con ``from … import``)."""
        namespace: dict[str, object] = {}
        exec("from geoblender.design.model import *", namespace)  # noqa: S102
        for name in NAMES:
            with self.subTest(name=name):
                self.assertIn(name, model.__all__)
                self.assertIs(getattr(model, name), getattr(requests, name))
                self.assertEqual(getattr(requests, name).__module__, requests.__name__)
                self.assertIn(name, dir(model))
                self.assertIs(namespace[name], getattr(requests, name))
        self.assertEqual(sorted(requests.__all__), sorted(NAMES))
        with self.assertRaises(AttributeError):
            model.NotARequest  # noqa: B018
        with self.assertRaises(ImportError):
            exec("from geoblender.design.model import NotARequest", {})  # noqa: S102

    def test_b_importing_the_model_does_not_create_them(self) -> None:
        """RNF-001-03: importar ``design.model`` (lo que hace habilitar) no importa
        ``design.supported_requests``; sí lo hace pedir una de las seis. Se mira en un proceso
        nuevo: en este ya las pidieron otras pruebas."""
        done = subprocess.run(
            [sys.executable, "-B", "-s", "-X", "utf8", "-c", PROBE], cwd=ROOT, check=False,
            capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "ok"), done.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
