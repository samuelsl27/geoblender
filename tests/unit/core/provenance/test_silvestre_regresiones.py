# SPDX-License-Identifier: GPL-3.0-or-later
"""Regresiones de Silvestre de la procedencia, primera parte (spec 008, T40; plan 008 §7;
Silvestre 00, §4.5): CE-008-01, CE-008-03 y CE-008-05. La segunda parte (CE-008-02, 09 y 10) es
de T41.

Cada prueba recorre la demostración de la procedencia (``tests.support.provenance_demo``) sobre
un proyecto real en disco (``tests.support.demo_project``) con las fuentes sintéticas de
``tests/data/core/provenance/`` en ``fuentes/``, fuera del proyecto. Nada de clientes:

- **Error 44** (y 46): se trabajó con una copia vieja del límite. El límite redibujado
  (+1,43 ha) hace que la operación siguiente que lo usa se niegue y liste lo que depende de él,
  también con la fuente en WAL y la edición en su ``-wal``; abrir y guardar el GeoPackage en
  QGIS sin cambiar nada no avisa; actualizarlo deja lo importado antes intacto.
- **N-27** (y N-12): un K fijo en un script (1,11) y otro en el balance (1,23). El K es un solo
  parámetro del proyecto que leen todas las operaciones, con su historial entero, y la que lo
  calcula no lo cambia.
- **Error 34**: «medido» aplicado a un valor adoptado. Ni un parámetro ni una cifra sin tipo, y
  una cifra que muestra un parámetro lleva su tipo.
- **PRJ-07**: nada temporal. Borrar la caché del proyecto no pierde ningún resultado ni su
  procedencia.
"""

from __future__ import annotations

import datetime as dt
import shutil
import sqlite3
from typing import Any

from tests.support import provenance_data as data
from tests.support import provenance_demo as demo
from tests.support.demo_project import SESSION, DemoProjectTestCase
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_contract import registered
from tests.support.trees import age_folders

gate = import_geoblender("core.provenance.gate")
importer = import_geoblender("core.provenance.importer")
lineage_mod = import_geoblender("core.provenance.lineage")
stale = import_geoblender("core.provenance.stale")
checks = import_geoblender("core.provenance.checks")
operations = import_geoblender("core.provenance.operations")
figures = import_geoblender("core.provenance.figures")
contract = import_geoblender("core.provenance.contract")
messages = import_geoblender("core.provenance.messages")
provenance_schema = import_geoblender("core.provenance.schema")
params = import_geoblender("core.params")
core_defs = import_geoblender("core.params.core_defs")
inputs = import_geoblender("core.inputs")
input_registry = import_geoblender("core.inputs.registry")
originals = import_geoblender("core.inputs.originals")
datasets = import_geoblender("core.datasets.registry")
builtin = import_geoblender("core.content.builtin")
readers = import_geoblender("core.content.readers")
hashing = import_geoblender("core.hashing")
events = import_geoblender("core.project.events")

UPDATE_REASON = "La propiedad entrega el límite redibujado"
NOT_APPLICABLE = {"not_applicable": True}
CHANGED_TEXT = (
    r"La entrada «Limites_v1» ha cambiado desde su registro \(\d\d/\d\d/\d{4} \d\d:\d\d\)\. "
    r"Dependen de ella: 1 dato, 1 operación y 1 cifra\. "
    r"Fecha de la fuente: \d\d/\d\d/\d{4} \d\d:\d\d\."
)
"""El aviso de la spec §8 con lo que depende del límite: lo importado, el área y su cifra."""
K_DECISIONS: tuple[tuple[float, str, str, dt.date, str], ...] = (
    (1.15, "HIPÓTESIS", "técnico de IMGA", dt.date(2026, 9, 1),
     "Sin ensayo: valor de la bibliografía"),
    (1.18, "HIPÓTESIS", "técnico de IMGA", dt.date(2026, 9, 5), "Primer ensayo de la arenisca"),
    (1.20, "HIPÓTESIS", "técnico de IMGA", dt.date(2026, 9, 10), "Ensayo de la caliza"),
    (1.25, "HIPÓTESIS", "técnico de IMGA", dt.date(2026, 9, 15), "Media ponderada con la marga"),
    (1.22, "HIPÓTESIS", "técnico de IMGA", dt.date(2026, 9, 20), "Proporción 60/40 revisada"),
    (1.23, "ADOPTADO", "la propiedad", dt.date(2026, 9, 24),
     "La propiedad adopta el K del balance"),
)
"""Los seis valores del K (N-27): valor, tipo, quién lo decidió, cuándo y por qué."""
K_WARNING = ("La operación «demo.balance» calcula K (demostración) = 1,11; el valor adoptado es "
             "1,23 (la propiedad, 24/09/2026).")
"""El aviso de RF-008-59 (spec §8) con el K de la demostración."""
REPORT_IMPORT = "demo.import_report"
"""Una importación de documentos de prueba (la demostración no tiene)."""


def _entry(conn: sqlite3.Connection, key: str) -> Any:
    return input_registry.get(conn, key)


class Err44Test(DemoProjectTestCase):
    """El límite importado, su área (12,000 0 ha) y lo que hace la puerta antes de la
    operación siguiente cuando cambia su fuente."""

    def measure(self) -> tuple[Any, Any, Any]:
        """Importa ``fuentes/Limites_v1.gpkg`` y calcula su área: (importación, operación del
        área, cifra)."""
        first = self.run_step(lambda: self.demo.import_boundary(self.project, self.source))
        area = self.run_step(lambda: self.demo.area(self.project, first.dataset.name))
        (figure,) = self.figures_of(area.uid)
        self.assertClose(figure.value, 12.0)
        return first, area, figure

    def next_area(self, boundary: str) -> Any:
        """La puerta antes de volver a calcular el área con el límite ``boundary``, sin tocar
        la carpeta de la fuente: nada se crea, cambia ni borra junto a ella."""
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            return self.run_step(lambda: self.demo.gate(self.project, demo.AREA,
                                                        boundary=boundary))

    def assertRefused(self, verdict: Any, first: Any, area: Any, figure: Any) -> None:  # noqa: N802
        """La operación se niega por la entrada «Limites_v1», cambiada, con sus tres salidas
        (Actualizar, Mantener la copia y Cancelar) y lo que depende de ella."""
        self.assertIsInstance(verdict, gate.Blocked)
        (reason,) = verdict.reasons
        self.assertEqual((reason.kind, reason.item_kind, reason.uid, reason.name, reason.choices),
                         (gate.BlockKind.INPUT_CHANGED, operations.ItemKind.INPUT,
                          first.input.uid, "Limites_v1", gate.CHANGED_INPUT_CHOICES))
        found = reason.finding.dependents
        self.assertEqual([(item.uid, item.name) for item in found.datasets],
                         [(first.dataset.uid, first.dataset.name)])
        self.assertEqual([(item.uid, item.name) for item in found.operations],
                         [(area.uid, demo.AREA)])
        self.assertEqual([(item.uid, item.name) for item in found.figures],
                         [(figure.uid, demo.BOUNDARY_AREA)])
        self.assertRegex(reason.text(), f"^{CHANGED_TEXT}$")
        self.assertEqual([gate.choice_label(choice) for choice in reason.choices],
                         ["Actualizar", "Mantener la copia", "Cancelar"])
        entry = self.read(lambda conn: _entry(conn, first.input.uid))
        self.assertEqual(entry.status, inputs.InputStatus.CHANGED)
        # Nada se calculó: la cifra vigente sigue siendo la de la copia del proyecto.
        self.assertEqual(self.demo.current_figure(self.project, demo.BOUNDARY_AREA).uid,
                         figure.uid)

    def test_err44_entrada_cambiada_bloquea(self) -> None:
        """RF-008-08, RF-008-09, RF-008-10, RF-008-11, RF-008-14, RF-008-52 (CE-008-01;
        Silvestre, errores 44 y 46): con el límite importado y su área (12,000 0 ha), abrir y
        guardar el GeoPackage en QGIS sin cambiar nada (otros bytes, otro orden y otro
        ``last_change``) no avisa: la operación siguiente se puede ejecutar y quedan anotados
        su tamaño y su fecha nuevos, también en la comprobación completa. El límite redibujado
        (+1,43 ha) hace que se niegue con el aviso de la spec §8, que lista lo que depende de
        él (lo importado, el área y su cifra), y así sigue al repetirla. Actualizarlo da el
        área nueva, 13,430 0 ha (+1,430 0), y deja lo importado antes intacto en el proyecto:
        con su contenido, protegido y en la procedencia de la cifra antigua. Nada se escribe
        junto a la fuente."""
        first, area, figure = self.measure()
        registered_print = self.read(lambda conn: _entry(conn, first.input.uid)).files[0]

        resaved = self.deliver(data.BOUNDARY_V1_QGIS)
        seen = resaved.stat()
        self.assertNotEqual(data.file_sha256(resaved), registered_print.sha256)
        verdict = self.next_area(first.dataset.name)
        self.assertIsInstance(verdict, gate.Ready)
        self.assertEqual(verdict.notices, ())
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            full = list(inputs.check_steps(self.project, mode=inputs.CheckMode.FULL))[-1].result
        self.assertEqual([(item.name, item.verdict) for item in full.findings],
                         [("Limites_v1", inputs.Verdict.SAME)])
        self.assertEqual((full.warnings, full.notices), ((), ()))
        entry = self.read(lambda conn: _entry(conn, first.input.uid))
        self.assertEqual((entry.status, entry.content_sha256, entry.seen_sha256),
                         (inputs.InputStatus.CURRENT, first.input.content_sha256, None))
        self.assertEqual((entry.files[0].checked_size, entry.files[0].checked_mtime_ns),
                         (seen.st_size, seen.st_mtime_ns))

        self.deliver(data.BOUNDARY_V2)
        verdict = self.next_area(first.dataset.name)
        self.assertRefused(verdict, first, area, figure)
        self.assertRefused(self.next_area(first.dataset.name), first, area, figure)
        changed = self.read(lambda conn: conn.execute(
            "SELECT entity_uid FROM gb_event WHERE kind = ?",
            (events.EventKind.INPUT_CHANGED.value,)).fetchall())
        self.assertEqual(changed, [(first.input.uid,)])

        imported = self.read(lambda conn: datasets.get(conn, first.dataset.uid))
        rows = self.read(lambda conn: conn.execute(
            f'SELECT * FROM "{imported.locator}" ORDER BY fid').fetchall())
        update = self.run_step(lambda: importer.reimport_input(self.project, "Limites_v1",
                                                               UPDATE_REASON))
        outcome = self.recompute_all()
        self.assertEqual([result.unit.operations for result in outcome.results], [(area.uid,)])
        current = self.demo.current_figure(self.project, demo.BOUNDARY_AREA)
        self.assertClose(current.value, 13.43)
        self.assertClose(current.value - figure.value, 1.43)
        tree = lineage_mod.lineage(self.project, current.uid)
        self.assertEqual(list(tree.inputs), [update.input.uid])

        # Lo importado antes sigue en el proyecto tal cual (RF-008-52).
        old = self.read(lambda conn: datasets.get(conn, first.dataset.uid))
        self.assertEqual((old.status, old.content_sha256, old.immutable),
                         ("superseded", imported.content_sha256, True))
        self.assertEqual(self.read(lambda conn: datasets.content_digest(
            conn, self.project, old).content_sha256), imported.content_sha256)
        self.assertEqual(self.read(lambda conn: conn.execute(
            f'SELECT * FROM "{old.locator}" ORDER BY fid').fetchall()), rows)
        qgis = sqlite3.connect(str(self.project.database_path), timeout=2.0,
                               isolation_level=None)
        self.addCleanup(qgis.close)
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            qgis.execute(f'DELETE FROM "{old.locator}"')
        self.assertIn("es lo importado de la entrada «Limites_v1»", str(caught.exception))
        before = self.read(lambda conn: _entry(conn, first.input.uid))
        self.assertEqual(before.status, inputs.InputStatus.SUPERSEDED)
        old_tree = lineage_mod.lineage(self.project, figure.uid)
        self.assertEqual(list(old_tree.inputs), [first.input.uid])
        self.assertEqual([link.uid for link in old_tree.operations[area.uid].consumed],
                         [first.dataset.uid])

    def test_err44_entrada_cambiada_bloquea_en_wal(self) -> None:
        """RF-008-09, RF-008-10, RF-008-14 (CE-008-01 con la fuente en WAL; plan 008 §5.4.2,
        I-3): el límite está en un GeoPackage en WAL (como lo deja QGIS); registrarlo y medirlo
        no escribe nada junto a él. QGIS guarda el límite redibujado en su ``-wal`` sin volcarlo
        al principal, que conserva su tamaño y su fecha: aun así la operación siguiente se
        niega con el aviso de la spec §8 y lo que depende de él, sin escribir ni volcar nada
        junto a la fuente."""
        data.to_wal(self.source)
        self.assertEqual(sorted(path.name for path in self.sources.iterdir()),
                         [data.BOUNDARY_V1])
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            first, area, figure = self.measure()
        registered_print = self.read(lambda conn: _entry(conn, first.input.uid)).files[0]
        main = self.source.stat()
        self.assertEqual((registered_print.size, registered_print.mtime_ns),
                         (main.st_size, main.st_mtime_ns))

        wal = data.edit_in_wal(self.source)
        edited = self.source.stat()
        self.assertEqual((edited.st_size, edited.st_mtime_ns), (main.st_size, main.st_mtime_ns))
        self.assertGreater(wal.stat().st_size, 0)
        verdict = self.next_area(first.dataset.name)
        self.assertRefused(verdict, first, area, figure)


class ParameterTypeTest(DemoProjectTestCase):
    """El K de esponjamiento de la demostración (``demo.swell_factor``) y sus cifras."""

    def decide_k(self) -> Any:
        """El K pasa por los seis valores de :data:`K_DECISIONS`: el primero se da de alta y
        cada uno de los demás es un cambio con su motivo, un minuto después."""
        store = params.ParameterStore(self.project)
        for index, (value, kind, who, when, why) in enumerate(K_DECISIONS):
            with self.project.write_transaction() as conn:
                if index == 0:
                    store.create(conn, demo.SWELL_FACTOR, value, kind=kind, source="Balance "
                                 "de tierras", source_kind="document", decided_by=who,
                                 decided_at=when, reason=why)
                else:
                    store.change(conn, demo.SWELL_FACTOR, value=value, kind=kind,
                                 decided_by=who, decided_at=when, reason=why)
            self.clock.advance(minutes=1)
        return store.get(demo.SWELL_FACTOR)

    def test_N27_parametro_unico(self) -> None:  # noqa: N802 - nombre de Silvestre
        """RF-008-01, RF-008-02, RF-008-05, RF-008-59 (CE-008-03; Silvestre, N-27 y N-12): el K
        pasa por seis valores y acaba ADOPTADO; su historial conserva los seis, cada uno con su
        valor, su tipo (los anteriores siguen HIPÓTESIS), quién y cuándo lo decidió, quién lo
        escribió y cuándo, y su motivo; cambiarlo sin motivo se rechaza. Todas las operaciones
        leen ese único K: el filtro de acopios usa 1,23 ADOPTADO (revisión 6) y el balance, que
        calcula 1,11, lo registra como cifra CALCULADO con el aviso de la spec §8 y no lo
        cambia: ni su valor, ni su tipo, ni su historial."""
        record = self.decide_k()
        store = params.ParameterStore(self.project)
        history = store.history(demo.SWELL_FACTOR)
        self.assertEqual(
            [(entry.rev, entry.value, str(entry.kind), entry.decided_by, entry.decided_at[:10],
              entry.reason, entry.changed_by) for entry in history],
            [(rev, value, kind, who, when.isoformat(), why, SESSION.user_host)
             for rev, (value, kind, who, when, why) in enumerate(K_DECISIONS, start=1)])
        self.assertEqual(len({entry.changed_at for entry in history}), 6)
        self.assertEqual(sorted(entry.changed_at for entry in history),
                         [entry.changed_at for entry in history])
        self.assertEqual((record.value, str(record.kind), record.rev, record.unconfirmed),
                         (1.23, "ADOPTADO", 6, False))

        with self.assertRaises(params.ParamError) as caught, \
                self.project.write_transaction() as conn:
            store.change(conn, demo.SWELL_FACTOR, value=1.24, reason=" ")
        self.assertEqual(caught.exception.code, "core.param_reason_missing")
        self.assertEqual(str(caught.exception),
                         "Indique el motivo del cambio de «demo.swell_factor» (1,23 → 1,24).")
        self.assertEqual(len(store.history(demo.SWELL_FACTOR)), 6)

        self.run_step(lambda: self.demo.digitize(self.project))
        self.run_step(lambda: self.demo.bench_years(self.project))
        _detect, kept = self.run_step(lambda: self.demo.stockpiles(self.project))
        balance = self.run_step(lambda: self.demo.balance(self.project))
        used = self.read(lambda conn: conn.execute(
            "SELECT key, rev, value, kind FROM gb_operation_param WHERE operation_uid = ?",
            (kept.uid,)).fetchall())
        self.assertEqual(used, [(demo.SWELL_FACTOR, 6, "1.23", "ADOPTADO")])
        (volume,) = self.figures_of(kept.uid)
        self.assertClose(volume.value, (12_000.0 + 6_500.0) * 1.23)
        (k_figure,) = self.figures_of(balance.uid)
        self.assertEqual((k_figure.key, k_figure.value, str(k_figure.kind), k_figure.unit,
                          k_figure.parameter_uid, k_figure.parameter_rev),
                         (demo.SWELL_FIGURE, 1.11, "CALCULADO", "-", record.uid, 6))
        _found, warnings = self.demo.figures(self.project, balance.uid)
        self.assertEqual([warning.text for warning in warnings], [K_WARNING])
        self.assertEqual(store.get(demo.SWELL_FACTOR), record)
        self.assertEqual(store.history(demo.SWELL_FACTOR), history)
        self.assertEqual(stale.counts(self.project).obsolete, 0)

    def test_err34_tipo_obligatorio(self) -> None:
        """RF-008-01, RF-008-30 (CE-008-03; Silvestre, error 34: «medido» aplicado a un valor
        adoptado): un parámetro sin tipo, con un tipo que no es MEDIDO, CALCULADO, ADOPTADO ni
        HIPÓTESIS o CALCULADO tecleado se rechaza con el texto de la spec §8, al darlo de alta y
        al cambiarlo, y no se guarda. Una cifra sin tipo, con un tipo desconocido, MEDIDO sin
        mostrar ningún parámetro o que muestra como MEDIDO el K ADOPTADO (como el 60/40 de
        Silvestre) se rechaza nombrando su clave y su operación, sin escribir nada; la que lo
        muestra lleva su tipo, ADOPTADO, y su revisión."""
        store = params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            k_record = store.create(conn, demo.SWELL_FACTOR, 1.23, kind="ADOPTADO",
                                    source="Balance de tierras", source_kind="document",
                                    decided_by="la propiedad", reason="Adoptado en el balance")
        before = self.saved_rows()
        refused = (
            (None, "core.param_kind_missing", "El parámetro «demo.production» necesita un tipo: "
             "MEDIDO, CALCULADO, ADOPTADO o HIPÓTESIS."),
            ("NORMA", "core.param_kind_unknown", "El parámetro «demo.production» tiene el tipo "
             "«NORMA», que no es MEDIDO, CALCULADO, ADOPTADO ni HIPÓTESIS."),
            ("CALCULADO", "core.param_calculated_by_hand", "demo.production: un parámetro "
             "CALCULADO lo escribe una operación; para fijarlo a mano, elija ADOPTADO o "
             "HIPÓTESIS."),
        )
        for kind, code, text in refused:
            with self.subTest(kind=kind), self.assertRaises(params.ParamError) as caught, \
                    self.project.write_transaction() as conn:
                store.create(conn, demo.PRODUCTION, 450_000.0, kind=kind, source="Plan de "
                             "labores", source_kind="document", decided_by="la propiedad",
                             reason="Plan de labores 2027")
            self.assertEqual((caught.exception.code, str(caught.exception)), (code, text))
        for kind, code in ((None, "core.param_kind_missing"),
                           ("NORMA", "core.param_kind_unknown"),
                           ("CALCULADO", "core.param_calculated_by_hand")):
            with self.subTest(change=kind), self.assertRaises(params.ParamError) as caught, \
                    self.project.write_transaction() as conn:
                store.change(conn, demo.SWELL_FACTOR, kind=kind, reason="Sin tipo")
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.saved_rows(), before)
        self.assertTrue(self.project.writable)

        handle = operations.begin_operation(
            self.project, demo.BALANCE, settings={"bank_m3": 1_000.0, "loose_m3": 1_230.0},
            params=[demo.SWELL_FACTOR], executor="blender")
        before = self.saved_rows()
        wrong = (
            (figures.FigureSpec(demo.SWELL_FIGURE, 1.23, "-", kind=None,
                                parameter_key=demo.SWELL_FACTOR),
             "core.figure_kind_missing",
             "La cifra «demo.swell_factor» de la operación «demo.balance» necesita un tipo: "
             "CALCULADO, o el del parámetro que muestra."),
            (figures.FigureSpec(demo.SWELL_FIGURE, 1.23, "-", kind="NORMA",
                                parameter_key=demo.SWELL_FACTOR),
             "core.figure_kind_unknown",
             "La cifra «demo.swell_factor» de la operación «demo.balance» tiene el tipo «NORMA», "
             "que no es MEDIDO, CALCULADO, ADOPTADO ni HIPÓTESIS."),
            (figures.FigureSpec(demo.STOCKPILE_VOLUME, 1_230.0, "m3", kind="MEDIDO"),
             "core.figure_kind_without_parameter", None),
            (figures.FigureSpec(demo.SWELL_FIGURE, 1.23, "-", kind="MEDIDO",
                                parameter_key=demo.SWELL_FACTOR),
             "core.figure_parameter_kind",
             "La cifra «demo.swell_factor» de la operación «demo.balance» muestra el parámetro "
             "«demo.swell_factor», que es ADOPTADO: lleva su tipo, no MEDIDO."),
        )
        for spec, code, text in wrong:
            with self.subTest(code=code), self.assertRaises(messages.ProvenanceError) as caught, \
                    self.project.write_transaction() as conn:
                figures.record_figure(conn, handle, spec)
            self.assertEqual(caught.exception.code, code, str(caught.exception))
            self.assertIn(f"«{spec.key}»", str(caught.exception))
            self.assertIn("«demo.balance»", str(caught.exception))
            if text is not None:
                self.assertEqual(str(caught.exception), text)
        self.assertEqual(self.saved_rows(), before)
        self.assertTrue(self.project.writable)

        with self.project.write_transaction() as conn:
            handle.complete(conn, figures=[figures.FigureSpec(
                demo.SWELL_FIGURE, 1.23, "-", kind="ADOPTADO", parameter_key=demo.SWELL_FACTOR)])
        (shown,) = self.figures_of(handle.uid)
        self.assertEqual((shown.value, str(shown.kind), shown.parameter_uid, shown.parameter_rev),
                         (1.23, "ADOPTADO", k_record.uid, 1))

    def saved_rows(self) -> dict[str, list[tuple[Any, ...]]]:
        """Los parámetros, su historial, las operaciones y las cifras del proyecto."""
        tables = ("gb_parameter", "gb_parameter_history", "gb_operation", "gb_figure")
        return self.read(lambda conn: {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
            for table in tables})


class CacheTest(DemoProjectTestCase):
    """La cadena entera de la demostración, cerrada, sin su caché y vuelta a abrir."""

    def import_report(self) -> Any:
        """Registra ``fuentes/informe.pdf`` como entrada documental y guarda su original desde
        la copia verificada de su importación (como la de un trabajo de la 004)."""
        if "core.original_copy_limit" not in params.DEFINITIONS:
            params.register_definitions(core_defs.DEFINITIONS)
            self.addCleanup(params.unregister_definitions, "core")
        self.enterContext(registered(contract.OperationDef(
            REPORT_IMPORT, "1.0", demo.DEMO_CODE, "Demo import report", False)))
        path = self.deliver(data.REPORT, data.REPORT)
        declarations = inputs.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
        request = builtin.DOCUMENT.request("document", declarations, {"main": path})
        found = path.stat()
        spec = inputs.InputSpec(
            "informe", "document", demo.DEMO_CODE, builtin.DOCUMENT.id,
            files=[input_registry.locate_source(path, self.project, self.userdata)],
            file_prints=[inputs.SourcePrint(hashing.sha256_file(path), size=found.st_size,
                                            mtime_ns=found.st_mtime_ns)],
            digest=readers.read_content(builtin.DOCUMENT, request),
            crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE)
        with operations.operation(self.project, REPORT_IMPORT, settings={}) as handle, \
                self.project.write_transaction() as conn:
            record = input_registry.register_input(conn, self.project, spec,
                                                   operation_uid=handle.uid)
            handle.complete(conn)
        copy = self.tmp / "trabajo" / data.REPORT
        copy.parent.mkdir()
        shutil.copyfile(path, copy)
        stored = list(originals.store_originals_steps(self.project, record.uid, [copy]))
        self.assertEqual(str(stored[-1].result.state), "stored")
        self.clock.advance(minutes=1)
        return record

    def saved(self) -> dict[str, Any]:
        """Todo lo que es resultado o procedencia en el proyecto: las tablas de la procedencia
        (salvo la caché ``gb_stale``), las causas de lo obsoleto (sin su fecha), las tablas de
        los datos, el contenido de cada dato vivo, la procedencia de cada cifra y los
        originales con su huella."""
        tables = [name for name in provenance_schema.TABLES if name != "gb_stale"]

        def read(conn: sqlite3.Connection) -> dict[str, Any]:
            found: dict[str, Any] = {
                name: conn.execute(f"SELECT * FROM {name} ORDER BY fid").fetchall()
                for name in tables}
            found["gb_stale"] = sorted(conn.execute(
                "SELECT item_kind, item_uid, cause_kind, subject_uid FROM gb_stale").fetchall())
            live = [datasets.get(conn, uid) for (uid,) in conn.execute(
                "SELECT uid FROM gb_dataset WHERE status = 'current' ORDER BY fid")]
            found["data"] = {record.name: conn.execute(
                f'SELECT * FROM "{record.locator}" ORDER BY fid').fetchall() for record in live}
            found["content"] = {record.name: (record.content_sha256, datasets.content_digest(
                conn, self.project, record).content_sha256) for record in live}
            found["originals"] = {
                path: hashing.sha256_file(self.project.root / path)
                for (path,) in conn.execute("SELECT original_path FROM gb_input_file "
                                            "WHERE original_path IS NOT NULL")}
            found["figures"] = [uid for (uid,) in conn.execute(
                "SELECT uid FROM gb_figure ORDER BY fid")]
            return found

        found = self.read(read)
        found["lineage"] = {uid: lineage_mod.lineage(self.project, uid).rows()
                            for uid in found["figures"]}
        found["stale"] = [(item.item_kind, item.uid, item.name, item.review, item.text)
                          for item in stale.stale_items(self.project).items]
        return found

    def test_PRJ07_sin_cache(self) -> None:  # noqa: N802 - nombre de Silvestre
        """RF-008-23, RF-008-52, RF-008-53 (CE-008-05; Silvestre, PRJ-07): con la cadena de la
        demostración (el límite importado y su área, bancos y marcas, años por banco, los
        acopios acoplados y el balance), un informe registrado con su original guardado y lo
        que dejó obsoleto un cambio de la producción, cerrar el proyecto y borrar su caché (la
        carpeta ``cache/`` del proyecto, la de sus datos de usuario y la caché de obsolescencia
        ``gb_stale``) no pierde nada: al volver a abrirlo y comprobarlo, los datos con su
        contenido, las operaciones, los parámetros con su historial, las entradas, el original
        con su huella, las cifras y la procedencia de cada una son los mismos, y lo obsoleto
        sigue obsoleto por las mismas causas."""
        first = self.run_step(lambda: self.demo.import_boundary(self.project, self.source))
        self.run_step(lambda: self.demo.area(self.project, first.dataset.name))
        self.run_step(lambda: self.demo.digitize(self.project))
        years = self.run_step(lambda: self.demo.bench_years(self.project))
        self.run_step(lambda: self.demo.stockpiles(self.project))
        self.run_step(lambda: self.demo.balance(self.project))
        report = self.import_report()
        with self.project.write_transaction() as conn:
            params.ParameterStore(self.project).change(
                conn, demo.PRODUCTION, value=400_000.0, kind="ADOPTADO",
                source="Plan de labores 2027", source_kind="document",
                decided_by="la propiedad", reason="Plan de labores revisado")
        self.clock.advance(minutes=1)
        saved = self.saved()
        self.assertEqual(len(saved["figures"]), 6)
        self.assertEqual(len(saved["originals"]), 1)
        self.assertIn(years.uid, {uid for _kind, uid, *_rest in saved["gb_stale"]})
        self.assertTrue(saved["stale"])
        for name, (registered_sha, now_sha) in saved["content"].items():
            self.assertEqual(now_sha, registered_sha, name)

        cache = self.project.cache_dir()
        user_cache = self.userdata.cache_dir(self.project.uid)
        for folder in (cache, user_cache):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "vista_previa.bin").write_bytes(b"vista previa, sin guardar")
        with self.project.write_transaction() as conn:
            conn.execute("DELETE FROM gb_stale")
        self.project.close()
        shutil.rmtree(cache)
        shutil.rmtree(user_cache)

        project = self.reopen()
        self.assertTrue(project.writable)
        outcome = list(checks.open_check_steps(project, write=True))[-1].result
        self.assertTrue(outcome.recorded)
        self.assertEqual((outcome.interrupted, outcome.datasets, outcome.originals,
                          outcome.warnings), ((), (), (), ()))
        self.assertEqual({item.name: item.verdict for item in outcome.inputs},
                         {"Limites_v1": inputs.Verdict.UNCHANGED,
                          report.name: inputs.Verdict.UNCHANGED})
        self.assertEqual(self.saved(), saved)
        self.assertEqual(inputs.OriginalState.STORED, self.read(
            lambda conn: _entry(conn, report.uid)).original)
        self.assertEqual(sorted(path.name for path in (project.root / "originals").rglob("*")
                                if path.is_file()), [data.REPORT])
