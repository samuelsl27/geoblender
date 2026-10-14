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
- RF-004-07, RF-006-28 (T57; M3, M7): el TIN de dos líneas de rotura que se cruzan con cotas
  distintas y la importación repetida del mismo CSV terminan su trabajo bien, pero no su
  operación: la línea del trabajo en la barra de estado lo dice («Operación fallida» u
  «Operación cancelada» y el principio del motivo, no «Terminado») y el motivo entero va al
  registro de Blender como error o como aviso.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest

from tests.blender.gis.test_ops_dtm import _module
from tests.blender.gis.test_ops_tin import IMPORT_POINTS, TIN_POINTS, TinOperatorsCase
from tests.support.fake_layout import FakeLayout

ERRORES_COLUMNS = [{"name": name, "index": index, "role": role} for index, (name, role) in
                   enumerate((("P", "POINT_ID"), ("X", "X"), ("Y", "Y"), ("Z", "Z"),
                              ("Código", "CODE"), ("Línea", "LINE")))]
CROSSING_CSV = (
    # El cuadro de M3 (12/10/2026): PIE_3 sube de 800 a 810 m y CAB_2 baja de 820 a 830 m;
    # se cruzan en (700 020; 4 400 020) con 805 y 825 m.
    "P;X;Y;Z;Código;Línea\n"
    "1;700000,000;4400000,000;800,000;TN;\n2;700040,000;4400000,000;800,000;TN;\n"
    "3;700040,000;4400040,000;800,000;TN;\n4;700000,000;4400040,000;800,000;TN;\n"
    "5;700010,000;4400010,000;800,000;PIE;PIE_3\n6;700030,000;4400030,000;810,000;PIE;PIE_3\n"
    "7;700010,000;4400030,000;820,000;CAB;CAB_2\n8;700030,000;4400010,000;830,000;CAB;CAB_2\n"
)
NOTICE_ICONS = ("CHECKMARK", "ERROR", "CANCEL")


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

    def notice(self) -> tuple[str, str, str]:
        """La línea del trabajo que acaba de terminar en la barra de estado (el campo «jobs»
        dibujado con un *layout* simulado): su texto y su icono, y el estado del trabajo."""
        layout = FakeLayout()
        self.jobs_ui.draw(layout, None)
        (label,) = [item for item in layout.of_kind("label") if item.icon in NOTICE_ICONS]
        return label.text, label.icon, self.jobs_ops.MONITOR.view().notice.state

    def test_operation_not_done_said_in_the_status_bar_and_the_reports(self) -> None:
        """RF-004-07, RF-006-28 (T57; M3, M7): el TIN del CSV de M3, con las roturas PIE_3 y
        CAB_2 que se cruzan con cotas distintas, queda fallido y sin TIN; su trabajo terminó
        bien («Terminado» en ``jobs/``), pero su línea en la barra de estado dice «TIN «Cruce»
        · Operación fallida · <s> s · <principio del motivo>» con el icono de error, y el
        motivo entero (las dos roturas, la posición y las dos cotas) va al registro de Blender
        como error. Importar otra vez el mismo CSV queda cancelado («La entrada «Cruce» ya está
        registrada con el mismo contenido…»): «Operación cancelada», con el icono de cancelado,
        y el motivo, como aviso. Ninguna dice «Terminado»."""
        self.jobs_ui = _module("bl.ui.jobs")
        i18n = _module("core.i18n")
        self.open()
        path = self.sources / "cruce" / "cruce.csv"
        path.parent.mkdir(parents=True)
        path.write_text(CROSSING_CSV, encoding="utf-8")
        values = {"filepath": str(path), "name": "Cruce", "encoding": "UTF8",
                  "separator": "SEMICOLON", "decimal": "COMMA", "crs": "EPSG:25830",
                  "vertical": "PROJECT"}
        self.assertEqual(self.operation(self.launch(IMPORT_POINTS, **values))[1], "done")
        sent = len(self.jobs_ops.sent_reports())
        tin = self.chain(TIN_POINTS, points="gis_pts_cruce", breaklines="gis_brk_cruce",
                         name="Cruce")
        _type, status, reason, *_ = self.operation(tin)
        self.assertEqual(status, "failed")
        position = "; ".join(i18n.format_number(v, 3) for v in (700_020.0, 4_400_020.0))
        for text in ("«PIE_3» y «CAB_2» se cruzan", f"({position})", "805,000", "825,000"):
            self.assertIn(text, reason)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name = "
                                   "'gis_tin_cruce'"), [(0,)])
        text, icon, state = self.notice()
        seconds = i18n.format_number(self.jobs_ops.MONITOR.view().notice.duration_s or 0.0, 1)
        self.assertEqual(text, f"TIN «Cruce» · Operación fallida · {seconds} s · "
                               f"{self.jobs_ui.reason_head(reason)}")
        self.assertTrue(reason.startswith(self.jobs_ui.reason_head(reason).rstrip("…")))
        self.assertEqual((icon, state), ("ERROR", "succeeded"))
        self.assertNotIn("Terminado", text)
        self.assertEqual(self.jobs_ops.sent_reports()[sent:], (("ERROR", reason),))

        again = self.launch(IMPORT_POINTS, **values)
        _type, status, reason, *_ = self.operation(again)
        self.assertEqual(status, "cancelled")
        self.assertTrue(reason.startswith("La entrada «Cruce» ya está registrada con el mismo "
                                          "contenido"), reason)
        text, icon, state = self.notice()
        seconds = i18n.format_number(self.jobs_ops.MONITOR.view().notice.duration_s or 0.0, 1)
        self.assertEqual(text, f"Importación de los puntos «Cruce» · Operación cancelada · "
                               f"{seconds} s · {self.jobs_ui.reason_head(reason)}")
        self.assertEqual((icon, state), ("CANCEL", "succeeded"))
        self.assertEqual(self.jobs_ops.sent_reports()[sent + 1:], (("WARNING", reason),))


if __name__ == "__main__":
    unittest.main()
