# SPDX-License-Identifier: GPL-3.0-or-later
"""El nombre legible de un dato en la ficha (spec 019, T31; UI-07, UI-08): sin el prefijo del nombre estable y con espacios."""

import unittest

from tests.support.package import import_geoblender

card = import_geoblender("core.views.card")


class ReadableNameTest(unittest.TestCase):
    def test_a_stable_name_loses_its_prefix_and_reads_as_text(self) -> None:
        self.assertEqual(card.readable_name("gis_dtm_rejilla_01"), "Rejilla 01")
        self.assertEqual(card.readable_name("gis_src_mdt_norte"), "Mdt norte")
        self.assertEqual(card.readable_name("des_psf_corta_de_la_orden"), "Corta de la orden")

    def test_what_is_not_a_stable_name_stays_as_it_is(self) -> None:
        for text in ("Corta Norte 2", "Rejilla", "demo_pit_grid", "gis_dtm", ""):
            self.assertEqual(card.readable_name(text), text)


if __name__ == "__main__":
    unittest.main()
