# SPDX-License-Identifier: GPL-3.0-or-later
"""Las declaraciones de la verificación por recinto viven en ``reserves.provenance`` (spec 012,
T38; RNF-001-03; RF-012-16, RF-012-21).

``bl`` registra al habilitar la extensión el tipo de operación ``res.verify_constraints``, su
parámetro del proyecto y sus cinco cifras, y habilitar no puede importar ``reserves.compliance_store``
(arrastra las máscaras, los lectores de GeoTIFF y la cadena de versiones). Por eso se declaran en
``reserves.provenance`` y el almacén las reexporta con los nombres de siempre: estas pruebas fijan
que son los mismos objetos y lo que declaran.
"""

import unittest

from tests.support.package import import_geoblender

provenance = import_geoblender("reserves.provenance")
store = import_geoblender("reserves.compliance_store")
contract = import_geoblender("core.provenance.contract")

SAME = (("VERIFY", "VERIFY"), ("COMMAND", "VERIFY_COMMAND"), ("PHASE", "VERIFY_PHASE"),
        ("MIN_THICKNESS", "VERIFY_MIN_THICKNESS"), ("MIN_THICKNESS_DEF", "VERIFY_MIN_THICKNESS_DEF"),
        ("DEFINITIONS", "VERIFY_DEFINITIONS"), ("FIGURES", "VERIFY_FIGURES"),
        ("operation_def", "verify_operation_def"), ("MODULE", "MODULE"),
        ("FIGURE_TOLERANCE", "FIGURE_TOLERANCE"))


class VerifyDeclarationsTest(unittest.TestCase):
    def test_the_store_reexports_the_declarations(self) -> None:
        """RNF-001-03: cada nombre de la verificación que usan ``bl`` y las pruebas desde
        ``reserves.compliance_store`` es el objeto de ``reserves.provenance``."""
        for name, declared in SAME:
            with self.subTest(nombre=name):
                self.assertIs(getattr(store, name), getattr(provenance, declared))

    def test_what_is_declared(self) -> None:
        """RF-012-16, RF-012-21: la operación es de la versión, se repite sola y se reproduce con
        10⁻⁹ relativo; su parámetro del proyecto es el espesor mínimo (0,02 m); sus cinco cifras
        son las de la verificación; se declaran en ``res``."""
        self.assertEqual((provenance.VERIFY, provenance.VERIFY_COMMAND, provenance.MODULE),
                         ("res.verify_constraints", "geoblender.res_verify_constraints", "res"))
        definition = provenance.verify_operation_def(lambda request: None, lambda request: iter(()))
        self.assertEqual((definition.op_type, definition.module, definition.scope,
                          definition.repeatable, definition.commands, definition.figure_tolerance),
                         (provenance.VERIFY, "res", "version", True, (provenance.VERIFY_COMMAND,),
                          contract.Tolerance(relative=1e-9)))
        bare = provenance.verify_operation_def(lambda request: None)  # se repite sola: pide recálculo
        self.assertIsNone(bare.reproduce)
        self.assertIsNone(bare.figure_tolerance)
        self.assertEqual([(item.key, item.default, item.unit)
                          for item in provenance.VERIFY_DEFINITIONS],
                         [("res.verify.min_thickness_m", 0.02, "m")])
        self.assertEqual([figure.key for figure in provenance.VERIFY_FIGURES],
                         ["res.check_cut_m3", "res.check_fill_m3", "res.check_moved_area_m2",
                          "res.check_nodata_area_m2", "res.check_avoid_weighted_m3"])


if __name__ == "__main__":
    unittest.main()
