# SPDX-License-Identifier: GPL-3.0-or-later
"""La versión de Geoblender que firma cada sesión (spec 002, T23; RF-002-04; plan 002
§5.1: ``core/version.py``).

La fuente única de la versión es ``blender_manifest.toml`` (convenciones §3): el cerrojo,
la cabecera y ``gb_project`` la leen de ahí, nunca de un texto escrito a mano.
"""

import re
import unittest

from tests.support.package import import_geoblender
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

from gbtools import manifest  # noqa: E402

version = import_geoblender("core.version")

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


class VersionTest(unittest.TestCase):
    def test_version_from_manifest(self) -> None:
        """RF-002-04: ``geoblender_version()`` es la ``version`` del manifiesto real, en
        SemVer."""
        expected = manifest.load(ROOT / manifest.MANIFEST_RELPATH)["version"]
        found = version.geoblender_version()
        self.assertEqual(found, expected)
        self.assertRegex(found, SEMVER)


if __name__ == "__main__":
    unittest.main()
