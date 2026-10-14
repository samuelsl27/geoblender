# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que la vista dice de un dato del proyecto (spec 006, T27; RF-006-29; plan 006 §5.6.7).

``core.provenance.view`` lee, sin escribir nada, lo que ``Object.geoblender`` lleva de un dato
vivo al cargarlo en la vista: su registro de ``gb_dataset`` (uid, nombre, estado y hash de
contenido), si está obsoleto según la caché ``gb_stale`` de la 008 y la fecha en que terminó la
operación que escribió su contenido. Sobre el proyecto sintético de las pruebas de las
operaciones (``res``), con un reloj simulado.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from tests.support.package import import_geoblender
from tests.unit.core.provenance.test_operations import (
    SOFTWARE,
    OperationsCase,
    _table_spec,
    _write_table,
)

view = import_geoblender("core.provenance.view")
datasets = import_geoblender("core.datasets")

RESULT = "res_resultado"
REASON = "Nuevo plan de labores"


class DatasetViewTest(OperationsCase):
    def balance(self) -> tuple[Any, Any]:
        """Una operación ``res.balance`` hecha, que leyó ``res.recovery`` y escribió la tabla
        :data:`RESULT`, un minuto después de empezar."""
        handle = self.begin(params=["res.recovery"])
        self.tick()

        def work(conn: sqlite3.Connection) -> Any:
            _write_table(conn, RESULT, (3.5, 4.25))
            return handle.complete(conn, outputs=[_table_spec(RESULT, "summary")],
                                   software=SOFTWARE)

        (record,) = self.write(work)
        return handle, record

    def test_current_dataset_with_its_hash_and_date(self) -> None:
        """RF-006-29 (plan 006 §5.6.7): de un dato vigente, su registro (por su uid o por su
        nombre), sin marca de obsoleto, y la fecha (UTC) en que terminó la operación que
        escribió su contenido; un dato que el proyecto no tiene, ``None``; la lista de los datos
        vivos, por nombre. Leerlo no escribe nada en el proyecto."""
        handle, record = self.balance()
        before = self.snapshot()
        found = view.dataset_view(self.project, record.uid)
        self.assertEqual(
            (found.record.uid, found.record.name, found.record.content_sha256,
             str(found.record.status), found.stale, found.date),
            (record.uid, RESULT, record.content_sha256, "current", False,
             self.row(handle.uid)["finished_at"]),
        )
        self.assertEqual(found.date, "2026-10-05T08:13:44.000Z")
        self.assertEqual(view.dataset_view(self.project, RESULT).record.uid, record.uid)
        self.assertIsNone(view.dataset_view(self.project, "res_nada"))
        self.assertEqual([item.name for item in view.live_datasets(self.project)], [RESULT])
        self.assertEqual(self.snapshot(), before)

    def test_stale_blocked_and_discarded(self) -> None:
        """RF-006-29 (plan 006 §5.6.7): cambiar el parámetro que leyó su operación deja el dato
        obsoleto según la caché de la 008; bloqueado, sigue vivo con su estado y su marca; un
        dato descartado ya no es vivo: ni se ve ni está en la lista."""
        _handle, record = self.balance()
        self.tick()
        self.write(lambda conn: self.store.change(
            conn, "res.recovery", value=0.8, kind="ADOPTADO", source="Plan de labores 2027",
            source_kind="document", decided_by="la propiedad", reason=REASON))
        found = view.dataset_view(self.project, RESULT)
        self.assertEqual((str(found.record.status), found.stale), ("current", True))
        self.write(lambda conn: datasets.set_status(conn, self.project, record.uid, "blocked"))
        found = view.dataset_view(self.project, record.uid)
        self.assertEqual((str(found.record.status), found.stale), ("blocked", True))
        self.write(lambda conn: datasets.set_status(conn, self.project, record.uid,
                                                    "discarded"))
        self.assertIsNone(view.dataset_view(self.project, record.uid))
        self.assertIsNone(view.dataset_view(self.project, RESULT))
        self.assertEqual(view.live_datasets(self.project), [])
