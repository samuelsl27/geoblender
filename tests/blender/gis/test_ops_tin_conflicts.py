# SPDX-License-Identifier: GPL-3.0-or-later
"""Conflictos de un TIN y sus políticas en Blender (spec 006, T29; HU-006-2; plan 006 §5.3.5
y §5.6.4).

Con la cadena de ``test_ops_tin`` (``TinOperatorsCase``): ``errores.csv`` importado con las
columnas elegidas en el asistente (``GEOBLENDER_PG_gis_column``) y el TIN desde sus puntos.

- RF-006-12: el informe de la importación dice las filas leídas, las rechazadas (con su número
  y su motivo) y los duplicados.
- RF-006-14, RF-008-19: con «preguntar», el conflicto de P 8 y P 9 queda en los avisos con su
  posición y sus dos cotas y la operación, fallida con el motivo y sin TIN; con «cancelar»,
  cancelada; con la media, el TIN.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest

from tests.blender.gis.test_ops_tin import TIN_POINTS, TinOperatorsCase

ERRORES_COLUMNS = [{"name": name, "index": index, "role": role} for index, (name, role) in
                   enumerate((("P", "POINT_ID"), ("X", "X"), ("Y", "Y"), ("Z", "Z"),
                              ("Código", "CODE"), ("Línea", "LINE")))]


class TinConflictsTest(TinOperatorsCase):
    def test_conflicts_are_listed_and_a_policy_resolves_them(self) -> None:
        """RF-006-12, RF-006-14, RF-008-19: el CSV con errores (columnas elegidas en el
        asistente) dice sus filas rechazadas con número y motivo y sus 2 duplicados; el TIN con
        «preguntar» lista el conflicto de P 8 y P 9 con su posición y sus dos cotas, queda
        fallido con el motivo y sin TIN; con «cancelar», cancelado; con la media, se crea."""
        self.open()
        op_uid = self.import_csv("points/errores.csv", "Errores", columns=ERRORES_COLUMNS)
        message = self.operation(op_uid)[3]
        self.assertIn("filas leídas 16, puntos 6, líneas de rotura 1, rechazadas 7, "
                      "duplicados 2", message)
        self.assertIn("fila 4", message)
        self.assertIn("«7OO030,000» no es un número", message)
        self.ps.take_notices()
        meshes = self.project.root / "meshes"
        for policy, status in (("ASK", "failed"), ("CANCEL", "cancelled")):
            with self.subTest(politica=policy):
                uid = self.chain(TIN_POINTS, points="gis_pts_errores",
                                 breaklines="gis_brk_errores", name="Errores",
                                 duplicate_policy=policy)
                _type, found, reason, *_ = self.operation(uid)
                self.assertEqual(found, status)
                self.assertIn("Errores", reason)
                notices = " ".join(self.ps.take_notices())
                self.assertIn("los puntos «8» y «9» coinciden en planta en", notices)
                self.assertIn("811,000", notices)
                self.assertIn("811,250", notices)
                self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name = "
                                           "'gis_tin_errores'"), [(0,)])
                self.assertFalse(meshes.exists() and any(meshes.iterdir()))
        uid = self.chain(TIN_POINTS, points="gis_pts_errores", breaklines="gis_brk_errores",
                         name="Errores", duplicate_policy="MEAN")
        self.assertEqual(self.operation(uid)[1], "done")
        self.assertEqual(json.loads(self.operation(uid)[4])["duplicate_policy"], "mean")
        self.dataset("gis_tin_errores")


if __name__ == "__main__":
    unittest.main()
