# SPDX-License-Identifier: GPL-3.0-or-later
"""El hash de contenido y la protección de los datos frente al GDAL de QGIS 4.2 (spec 008, T41;
RF-008-08, RF-008-09, RF-008-21, RF-008-52, RF-008-56; plan 008 §7, ``tests/referencia/core``;
ADR-0024 y ADR-0025; I-3 y riesgos de GDAL del plan 008 §8).

Caso de referencia: un proyecto en disco con la demostración de la procedencia
(``tests.support.provenance_demo``) y dos entradas, los límites sintéticos ``Limites_v1.gpkg`` y
``Limites_v2.gpkg`` de ``fuentes/`` (fuera del proyecto) importados con ``core.import_layer``,
más los bancos (``demo_benches``, que no se editan a mano) y las marcas de acopio
(``demo_marks``, editables en QGIS) de ``demo.digitize``. La referencia externa es el GDAL de
QGIS 4.2 (``GEOBLENDER_QGIS_DIR``, con su PROJ y sin el ``PROJ_LIB`` del puesto), que edita como
QGIS (``tests.support.qgis.edit_gpkg``):

- **abrir y guardar** ``Limites_v1.gpkg`` (todas sus entidades reescritas sin cambios): otra
  huella del fichero y el mismo hash de contenido (y de datos); la comprobación completa da
  «mismo contenido» y no avisa;
- **un vértice** de P-02 en ``Limites_v2.gpkg`` movido 1 mm al norte: otro hash de contenido; la
  entrada queda «cambiada» con el aviso de la spec §8;
- **editar una capa seguida** del proyecto (el volumen en banco de la marca A-1): GDAL no da
  ningún error, su ``last_change`` cambia y conserva sus disparadores; la comprobación de los
  datos lo registra como edición externa y, por ser editable, no lo bloquea;
- **rehacer una tabla** (el tonelaje de ``demo_benches`` pasa de real a entero): GDAL la rehace;
  la comprobación la ve editada, la bloquea (no se edita a mano) y la deja con sus disparadores;
- **editar lo importado** (``core_imported_limites_v1``): GDAL falla con el mensaje de Geoblender,
  «… es lo importado de la entrada «Limites_v1»: no se modifica», y nada cambia.

Sin QGIS (sin la variable, o sin su GDAL) la clase se omite con «[ENTORNO] qgis», que
``tools/check.py`` cuenta como «VERDE CON OMISIONES»; el HITO H1 de la 008 no la admite.
"""

from __future__ import annotations

import shutil
import sqlite3
import unittest
from typing import Any

from tests.support import provenance_data as data
from tests.support import qgis
from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.demo_project import process_state
from tests.support.package import import_geoblender
from tests.support.provenance_demo import Demo
from tests.support.resources import requires

create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
builtin = import_geoblender("core.content.builtin")
readers = import_geoblender("core.content.readers")
tracking = import_geoblender("core.datasets.tracking")
external = import_geoblender("core.datasets.external")
datasets = import_geoblender("core.datasets.registry")
inputs = import_geoblender("core.inputs")
input_registry = import_geoblender("core.inputs.registry")
hashing = import_geoblender("core.hashing")

LAYER = "limites"
MARKS = "demo_marks"
BENCHES = "demo_benches"
EDITED_BANK_M3 = 12_500.0
MOVED_DY_M = 0.001
"""El vértice movido: 1 mm al norte."""
IMPORTED_REFUSAL = "es lo importado de la entrada «Limites_v1»: no se modifica"
EDITED_TEXT = ("El dato «{name}» se editó fuera de Geoblender: se registra la edición externa y "
               "lo que depende de él queda obsoleto.")
BLOCKED_TEXT = (" La capa «demo_benches» se editó fuera de Geoblender y no se edita a mano: "
                "acepte la edición con un motivo, recalcule o reimporte")


@requires(qgis.QGIS, qgis.QGIS_HINT)
class QgisContentReferenceTest(unittest.TestCase):
    """El proyecto de la demostración, editado una vez con el GDAL de QGIS (véase el módulo)."""

    @classmethod
    def setUpClass(cls) -> None:
        before = process_state()
        cls.addClassCleanup(cls._same_process_state, before)
        demo = cls.enterClassContext(Demo().registered())
        tmp = cls.enterClassContext(project_tmp("gb-qg-"))
        sources = tmp / "fuentes"
        sources.mkdir()
        (tmp / "proyectos").mkdir()
        cls.saved = sources / data.BOUNDARY_V1
        cls.moved = sources / data.BOUNDARY_V2
        for path in (cls.saved, cls.moved):
            shutil.copyfile(data.DATA_DIR / path.name, path)
        clock = FakeClock()
        project = create.create_project(tmp / "proyectos", make_settings(), make_session(),
                                        userdata_mod.UserData(tmp / "u"), clock=clock).project
        cls.addClassCleanup(project.close)
        cls.project = project
        cls.first = demo.import_boundary(project, cls.saved)
        cls.second = demo.import_boundary(project, cls.moved)
        clock.advance(minutes=1)
        demo.digitize(project)
        clock.advance(minutes=1)
        cls.imported = cls.first.dataset.locator
        tables = [MARKS, BENCHES, cls.imported]
        cls.prints = {path.name: hashing.sha256_file(path) for path in (cls.saved, cls.moved)}
        cls.states = cls.read(lambda conn: tracking.table_states(conn, tables))
        cls.rows = cls.read(lambda conn: {table: _rows(conn, table) for table in tables})

        cls.edits = qgis.edit_gpkg(
            qgis.resave_layer(cls.saved, LAYER),
            qgis.move_vertex(cls.moved, LAYER, ("codigo", data.MOVED_PARCEL), data.MOVED_VERTEX,
                             dy=MOVED_DY_M),
            qgis.set_field(project.database_path, MARKS, ("mark", "A-1"), "bank_m3",
                           EDITED_BANK_M3),
            qgis.change_field_type(project.database_path, BENCHES, "tonnage_t", "Integer64"),
            qgis.set_field(project.database_path, cls.imported, ("codigo", "P-01"), "tipo",
                           "otro"),
        )
        cls.edited = cls.read(lambda conn: tracking.table_states(conn, tables))
        cls.edited_rows = cls.read(lambda conn: {table: _rows(conn, table) for table in tables})
        cls.digests = {path.name: _digest(project, path, record) for path, record in (
            (cls.saved, cls.first.input), (cls.moved, cls.second.input))}
        cls.check = list(inputs.check_steps(project, mode=inputs.CheckMode.FULL))[-1].result
        cls.external = list(external.external_check_steps(project))[-1].result
        cls.checked = cls.read(lambda conn: tracking.table_states(conn, tables))

    @classmethod
    def _same_process_state(cls, before: Any) -> None:
        after = process_state()
        if after != before:
            raise AssertionError("la demostración no dejó el proceso como estaba")

    @classmethod
    def read(cls, work: Any) -> Any:
        with cls.project.read() as conn:
            return work(conn)

    def finding(self, name: str) -> Any:
        """Lo que dijo la comprobación de los datos de ``name`` (``None``: nada que decir)."""
        found = [item for item in self.external.findings if item.record.name == name]
        self.assertLessEqual(len(found), 1)
        return found[0] if found else None

    def verdict(self, name: str) -> Any:
        """Lo que dijo la comprobación completa de las entradas de la entrada ``name``."""
        (found,) = [item for item in self.check.findings if item.name == name]
        return found

    def test_abrir_y_guardar_no_cambia_el_hash(self) -> None:
        """RF-008-08, RF-008-09 (CE-008-01 con el GDAL de QGIS 4.2): abrir y guardar
        ``Limites_v1.gpkg`` reescribiendo sus tres entidades sin cambios da otra huella del
        fichero y el mismo hash de datos y de contenido que su entrada; la comprobación completa
        da «mismo contenido», sin avisos, y la entrada sigue vigente."""
        self.assertEqual(self.edits.results[0], qgis.EditResult(True, None), self.edits.version)
        self.assertNotEqual(hashing.sha256_file(self.saved), self.prints[self.saved.name])
        self.assertEqual(self.digests[self.saved.name],
                         (self.first.input.data_sha256, self.first.input.content_sha256))
        self.assertEqual(self.verdict("Limites_v1").verdict, inputs.Verdict.SAME)
        self.assertEqual(self.read(lambda conn: input_registry.get(
            conn, self.first.input.uid).status), inputs.InputStatus.CURRENT)

    def test_vertice_movido_cambia_el_hash(self) -> None:
        """RF-008-08, RF-008-09, RF-008-10 (CE-008-01 con el GDAL de QGIS 4.2): un vértice de
        P-02 en ``Limites_v2.gpkg`` movido 1 mm al norte da otro hash de datos y de contenido;
        la comprobación completa marca la entrada «cambiada» con el aviso de la spec §8, el
        único de la comprobación."""
        self.assertEqual(self.edits.results[1], qgis.EditResult(True, None), self.edits.version)
        data_sha, content_sha = self.digests[self.moved.name]
        self.assertNotEqual(data_sha, self.second.input.data_sha256)
        self.assertNotEqual(content_sha, self.second.input.content_sha256)
        finding = self.verdict("Limites_v2")
        self.assertEqual((finding.verdict, finding.content_sha256),
                         (inputs.Verdict.CHANGED, content_sha))
        (warning,) = self.check.warnings
        self.assertTrue(warning.startswith("La entrada «Limites_v2» ha cambiado desde su "
                                           "registro"), warning)

    def test_editar_capa_seguida_cambia_last_change(self) -> None:
        """RF-008-21, RF-008-56 (plan 008 D5; ADR-0025): editar con GDAL el volumen en banco de
        la marca A-1 en ``demo_marks``, una tabla seguida del proyecto, no da ningún error,
        cambia su ``last_change`` y la deja con sus disparadores; la comprobación de los datos
        lo registra como edición externa y, por ser editable en QGIS, no la bloquea."""
        self.assertEqual(self.edits.results[2], qgis.EditResult(True, None), self.edits.version)
        before, after = self.states[MARKS], self.edited[MARKS]
        self.assertTrue(before.tracked)
        self.assertNotEqual(after.last_change, before.last_change)
        self.assertEqual((after.tracked, after.triggers, after.schema_sha256),
                         (True, before.triggers, before.schema_sha256))
        self.assertEqual([row[1:] for row in self.edited_rows[MARKS]],
                         [(mark, bench, EDITED_BANK_M3 if mark == "A-1" else bank)
                          for mark, bench, bank in [row[1:] for row in self.rows[MARKS]]])
        finding = self.finding(MARKS)
        self.assertEqual((finding.verdict, finding.status, finding.text()),
                         (external.DatasetVerdict.EDITED, "current",
                          EDITED_TEXT.format(name=MARKS)))
        self.assertTrue(self.checked[MARKS].tracked)

    def test_rehacer_la_tabla(self) -> None:
        """RF-008-21, RF-008-56 (plan 008 §8, «GDAL rehace una tabla al cambiar sus campos»):
        cambiar con GDAL el tipo de un campo de ``demo_benches`` (el tonelaje, de real a
        entero) rehace la tabla; la comprobación de los datos la ve editada, la bloquea porque
        no se edita a mano (con el texto de la spec §8) y la deja con sus disparadores de
        seguimiento."""
        self.assertEqual(self.edits.results[3], qgis.EditResult(True, None), self.edits.version)
        self.assertNotEqual(self.edited[BENCHES].schema_sha256,
                            self.states[BENCHES].schema_sha256)
        self.assertEqual([row[1:] for row in self.edited_rows[BENCHES]],
                         [(bench, int(tonnes)) for bench, tonnes in
                          [row[1:] for row in self.rows[BENCHES]]])
        finding = self.finding(BENCHES)
        self.assertEqual((finding.verdict, finding.status, finding.text()),
                         (external.DatasetVerdict.EDITED, "blocked",
                          EDITED_TEXT.format(name=BENCHES) + BLOCKED_TEXT))
        self.assertTrue(self.checked[BENCHES].tracked)
        self.assertEqual(self.checked[BENCHES].triggers, self.states[BENCHES].triggers)

    def test_editar_lo_importado_falla(self) -> None:
        """RF-008-52 (plan 008 D5; ADR-0025): editar con GDAL lo importado de «Limites_v1»
        falla con el mensaje de Geoblender y no cambia nada: ni sus filas, ni su
        ``last_change``, ni sus disparadores; la comprobación de los datos no tiene nada que
        decir de él y sigue vigente, con su contenido."""
        result = self.edits.results[4]
        self.assertFalse(result.ok)
        self.assertIn(f"{self.imported}: {IMPORTED_REFUSAL}", result.error)
        self.assertEqual(self.edited_rows[self.imported], self.rows[self.imported])
        self.assertEqual(self.edited[self.imported], self.states[self.imported])
        self.assertIn(self.first.dataset.uid, self.external.checked)
        self.assertIsNone(self.finding(self.imported))
        record =self.read(lambda conn: datasets.get(conn, self.first.dataset.uid))
        self.assertEqual((record.status, record.content_sha256),
                         ("current", self.first.dataset.content_sha256))


def _rows(conn: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
    return conn.execute(f'SELECT * FROM "{table}" ORDER BY fid').fetchall()


def _digest(project: Any, path: Any, record: Any) -> tuple[str, str]:
    """Los hashes de datos y de contenido de la capa ``limites`` de ``path`` con las
    declaraciones de su entrada ``record``."""
    request = builtin.GPKG_LAYER.request("vector", record.declarations, {"main": path},
                                         {"layer": LAYER})
    digest = readers.read_content(builtin.GPKG_LAYER, request)
    return digest.data_sha256, digest.content_sha256


if __name__ == "__main__":
    unittest.main()
