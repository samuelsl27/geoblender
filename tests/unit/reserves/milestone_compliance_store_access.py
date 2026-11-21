# SPDX-License-Identifier: GPL-3.0-or-later
"""La verificación por recinto con la accesibilidad de las pistas, en el proyecto: la prueba de hito de ``test_compliance_store_access`` (spec 017, T18; HU-017-3; RF-012-21,
RF-012-22, RF-012-24, RF-012-25; RF-017-24 y RF-017-25; plan 017 §5.4 A12, §5.7 P-9, §8; DIFF-012 §2 y §4; P-12: con proyecto en la rejilla de 2 m, al paso «hito» de
``tools/check.py --completo``; el «verde» lleva las que no necesitan proyecto).

Sobre el proyecto de las pistas (``tests.support.road_data``: la cantera con bancos y rampas, rejilla de 2 m, V01 y V02) con las dos restricciones «requiere acceso» **de verdad**
(``zona_con_acceso``, de 400 m² en la berma de 135 m, al este de las rampas, y ``zona_sin_acceso``, de 720 m² en la de 105 m; ``rd.bank_zone_constraints``, declaradas y compiladas
en las máscaras de V01) y dos accesibilidades hechas con ellas: ``ACC-001``, sobre la cantera con bancos del proyecto (``gis_dtm_banco``), y ``ACC-002``, sobre la explotación de la
cantera de V01 (``des_exp_cantera``, de otro dato con el mismo terreno). A mano, de la 017 (T16 y T17b): se comunica la zona con acceso y no la zona sin acceso (a 18 m de lo alcanzable,
con 10 m de diferencia de cota). Se verifica contra el terreno de la rampa con tres finales: la cantera con bancos (con ``ACC-001``), la explotación (con ``ACC-002``) y el tajo (sin
accesibilidad):

- **Sin accesibilidad** (:class:`NoAccessibilityTest`): lo de siempre —las mismas entradas, ajustes, tabla y cifras— con las dos zonas «sin comprobar».
- **Elegir la accesibilidad** (:class:`SelectionTest`, ``select_access``; P-9): de cada final, la suya al día; la hecha sobre otra superficie no se usa y se avisa; las entradas de la
  operación por su papel ``road_access_<k>`` y la lectura de las zonas comunicadas.
- **RF-012-22, RF-012-24, RF-012-25** (:class:`VerifyWithAccessTest`, en orden sobre el mismo estado): las tres respuestas por final; la operación consume la tabla de zonas de cada
  accesibilidad (una **entrada**), sus ajustes y su tabla las nombran; congelar nombra la zona sin comunicar; **cambiar una entrada de la accesibilidad deja obsoleta la verificación**
  (y obsoletas las accesibilidades: no se usan y se avisa con la causa), «Recalcular lo obsoleto» las repite en orden (si lo que comunican no cambia, la verificación deja de estar
  obsoleta sin repetirse; si cambia, se repite después, con lo nuevo); cambiar un umbral solo de una de ellas cambia el veredicto de su final.
- **RF-012-24** (:class:`ReproduceTest`): congelada V01.r1, reproducir la verificación con la accesibilidad (sus tablas de zonas congeladas) da las mismas salidas y cifras, sin escribir.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Iterator
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_project as cproject
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design.milestone_access_operation import (
    BERMS_DATASET,
    EXPLOITATION,
    QUARRY,
    LifecycleCase,
    finish,
    rewrite_layer,
)
from tests.unit.design.test_access_operation import KEY
from tests.unit.design.test_access_operation import request as bank_request

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
cparams = import_geoblender("core.constraints.params")
registry = import_geoblender("core.datasets.registry")
recompute_mod = import_geoblender("core.provenance.recompute")
figures_mod = import_geoblender("core.provenance.figures")
freeze = import_geoblender("core.versions.freeze")
reproduce = import_geoblender("core.versions.reproduce")
access_store = import_geoblender("design.access_store")
provenance = import_geoblender("design.provenance")
surfaces = import_geoblender("reserves.surfaces")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
gis_store = import_geoblender("gis.store")
versions_model = import_geoblender("core.versions.model")

NAME = "Verificación de la cantera"
START = surfaces.SurfaceRef(dataset=rd.dataset_of("rampa"), label="Terreno de la rampa")
BANK = rd.dataset_of("banco")
PIT = rd.dataset_of("tajo")
FINALS = tuple(surfaces.SurfaceRef(dataset=name) for name in (BANK, EXPLOITATION, PIT))
"""La cantera con bancos (con ``ACC-001``), la explotación de la cantera de V01 (con ``ACC-002``) y el tajo (sin accesibilidad)."""
WITH, WITHOUT = "zona_con_acceso", "zona_sin_acceso"
FIRST, SECOND = "Accesibilidad del banco", "Accesibilidad de la explotación"
V = compliance.Verdict


def _verify_recompute(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de ``res.verify_constraints``: lleva los pasos hasta el final."""
    handle, work = cstore.recompute_run(request)
    finish(work)
    return handle


def _last(steps: Iterator[Any]) -> Any:
    found = None
    for step in steps:
        if step.result is not None:
            found = step.result
    return found


class _Case(LifecycleCase):
    """Lo de ``LifecycleCase`` (la cantera de V01 con la accesibilidad registrada) con la verificación registrada con su función real de recalcular y reproducir, las dos restricciones
    «requiere acceso» declaradas y compiladas en las máscaras de V01, y las ayudas de las historias de verificar."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(cstore.operation_def(_verify_recompute, cstore.REPRODUCE[cstore.VERIFY]), *cstore.FIGURES))
        core_params.register_definitions(cstore.DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        rows = rd.bank_zone_constraints()
        cls.clock.advance(minutes=1)
        cproject.edit_constraints(cls.project, rows)
        cproject.declare(cls.project, cls.clock, {**{cparams.active_key(row.code): True for row in rows}, **{cparams.buffer_out_key(row.code): 0.0 for row in rows}})
        cls.clock.advance(minutes=1)
        for _step in access.ensure_masks_steps(cls.project, cls.v1.uid):
            pass
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)

    def verify(self, finals: tuple[Any, ...] = FINALS, *, name: str = NAME, **options: Any) -> Any:
        """Verifica ``finals`` en V01 (de ``START``) y da lo guardado (``StoredCheck``)."""
        self.clock.advance(minutes=1)
        return _last(cstore.verify_project_steps(self.project, version=self.v1.uid, name=name, start=START, finals=finals, **options))

    def read(self, name: str = NAME) -> Any:
        with self.project.read() as conn:
            return cstore.read_verification(conn, self.v1.uid, name)

    def op_named(self, name: str = NAME) -> str:
        """La verificación vigente (sin sustituir) llamada ``name``."""
        for uid, text in self.query("SELECT uid, settings FROM gb_operation WHERE op_type = ? AND status = 'done' AND superseded_by IS NULL ORDER BY rowid DESC", cstore.VERIFY):
            if json.loads(text)["name"] == name:
                return str(uid)
        raise AssertionError(f"no hay una verificación «{name}»")

    def stale(self, uid: str) -> bool:
        return bool(self.query("SELECT 1 FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", uid))

    def inputs(self, uid: str) -> dict[str, str]:
        """Lo que consumió la operación ``uid``: papel → nombre del dato."""
        return dict(self.query("SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid))

    def settings_of(self, uid: str) -> dict[str, Any]:
        (text,) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)[0]
        return json.loads(text)  # type: ignore[no-any-return]

    def figures_of(self, uid: str) -> dict[tuple[str, str], float]:
        return {(key, scope): value for key, scope, value in self.query("SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def table_rows(self, name: str = NAME) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            record = registry.get(conn, cstore.dataset_name(cstore.TABLE, name), version_uid=self.v1.uid)
            return cstore.read_table(conn, record.locator)

    def verdicts(self, stored: Any) -> dict[tuple[int, str], str]:
        """El veredicto de las dos zonas «requiere acceso» de cada final de lo guardado (``read_verification``)."""
        return {(item.final, item.zone): item.verdict for item in stored.zones if item.zone in (WITH, WITHOUT)}

    def zones_table(self, code: str) -> str:
        """El nombre del dato de la tabla de zonas de la accesibilidad ``code`` al día de V01."""
        for surface in (BANK, EXPLOITATION):
            for found in access_store.accessibilities_on(self.project, self.v1.uid, surface):
                if found.code == code:
                    return found.zones.name
        raise AssertionError(code)


class _WithAccessibilities(_Case):
    """Además, ``ACC-001`` (sobre ``gis_dtm_banco``, del proyecto) y ``ACC-002`` (sobre ``des_exp_cantera``, de V01), con las máscaras de V01 y sus dos zonas «requiere acceso»."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create(bank_request(FIRST, surface=BANK))
        cls.create(bank_request(SECOND, surface=EXPLOITATION))


# ---------------------------------------------------------------------------------------------
# Sin accesibilidad: lo mismo que antes
# ---------------------------------------------------------------------------------------------


class NoAccessibilityTest(_Case):
    """RF-012-22, RF-012-24 (DIFF-017: «una versión sin accesibilidad al día sigue dando «sin comprobar»»): sin ninguna accesibilidad, la verificación no lee ninguna ni deja nada de más."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stored = cls("test_a_nothing_is_selected").verify()

    def test_a_nothing_is_selected(self) -> None:
        """RF-012-22: ninguna accesibilidad, ninguna entrada y nada que avisar, con cualquier final (también una cota constante o sin versión)."""
        for finals in (FINALS, (surfaces.SurfaceRef(elevation=100.0),), ()):
            with self.subTest(finals=len(finals)):
                found = cstore.select_access(self.project, self.v1.uid, finals)
                self.assertEqual((found.uses, found.skipped, found.datasets), ((), (), ()))
        self.assertEqual(cstore.select_access(self.project, None, FINALS), cstore.AccessSelection())
        self.assertEqual(cstore.read_communicated(self.project, cstore.AccessSelection(), 3), (None, None, None))
        with self.assertRaises(versions_model.VersionError) as caught:
            cstore.select_access(self.project, "V99", FINALS)
        self.assertEqual(caught.exception.code, "core.version_unknown")

    def test_b_the_two_zones_are_not_checked_and_the_operation_is_the_old_one(self) -> None:
        """RF-012-22, RF-012-24: las dos zonas «requiere acceso» salen «sin comprobar» en las tres finales; las entradas son las máscaras, la partida y las finales (ningún
        ``road_access_<k>``); los ajustes, los de siempre; la tabla, sin filas de accesibilidad."""
        stored = self.read()
        self.assertEqual(self.verdicts(stored), {(final, zone): "unchecked" for final in (1, 2, 3) for zone in (WITH, WITHOUT)})
        self.assertEqual({item.counts for item in stored.zones if item.zone in (WITH, WITHOUT)}, {"access"})
        uid = self.op_named()
        self.assertFalse([role for role in self.inputs(uid) if role.startswith("road_access")])
        self.assertEqual(sorted(self.settings_of(uid)), ["finals", "name", "pending_names", "pending_sectors", "start"])
        self.assertEqual({row[2] for row in self.table_rows()} & {"access_used", "access_skipped"}, set())
        self.assertEqual((stored.access, stored.access_skipped, stored.access_selection), ((), (), cstore.AccessSelection()))
        plain = cstore.verify_inputs(self.project, self.v1.uid, START, FINALS)
        self.assertEqual([use.role for use in plain if use.role.startswith("road_access")], [])
        self.assertEqual(cstore.verify_inputs(self.project, self.v1.uid, START, FINALS, access=cstore.AccessSelection()), plain)
        settings = self.settings_of(uid)
        self.assertEqual(cstore.verify_settings(NAME, START, FINALS, settings["pending_sectors"], settings["pending_names"]), settings)


# ---------------------------------------------------------------------------------------------
# Elegir la accesibilidad de cada final
# ---------------------------------------------------------------------------------------------


class SelectionTest(_WithAccessibilities):
    """RF-012-22, RF-012-24, P-9: elegir la accesibilidad de cada final."""

    def test_a_each_final_gets_its_own_current_accessibility(self) -> None:
        """P-9: la cantera con bancos usa ``ACC-001`` y la explotación, ``ACC-002``; el tajo, ninguna; las dos están usadas y no queda nada que avisar. Cada una es la tabla de zonas de su
        accesibilidad (su uid), con el nombre de la final para el texto."""
        found = cstore.select_access(self.project, self.v1.uid, FINALS)
        self.assertEqual([(use.final, use.code, use.name, use.surface, use.shown) for use in found.uses],
                         [(1, "ACC-001", FIRST, BANK, BANK), (2, "ACC-002", SECOND, EXPLOITATION, EXPLOITATION)])
        self.assertEqual(found.skipped, ())
        (first,) = access_store.accessibilities_on(self.project, self.v1.uid, BANK)
        (second,) = access_store.accessibilities_on(self.project, self.v1.uid, EXPLOITATION)
        self.assertEqual(found.datasets, (first.zones.uid, second.zones.uid))
        self.assertEqual(cstore.select_access(self.project, self.v1.code, FINALS), found)  # el código de la versión también vale
        with self.project.read() as conn:
            self.assertEqual(cstore.select_access(self.project, self.v1.uid, FINALS, conn=conn), found)

    def test_b_what_is_made_on_another_surface_is_not_used_and_is_warned(self) -> None:
        """P-9, RF-012-24: con solo la cantera con bancos como final, ``ACC-002`` (de la explotación) no se usa y se avisa con la superficie en que se hizo; con solo el tajo o una cota
        constante, ninguna se usa y se avisa de las dos."""
        found = cstore.select_access(self.project, self.v1.uid, FINALS[:1])
        self.assertEqual([use.code for use in found.uses], ["ACC-001"])
        self.assertEqual([(item.code, item.reason, item.surface, item.final) for item in found.skipped], [("ACC-002", access_store.EXCLUDED_OTHER_SURFACE, EXPLOITATION, 0)])
        for finals in (FINALS[2:], (surfaces.SurfaceRef(elevation=100.0),)):
            with self.subTest(finals=finals[0].shown):
                found = cstore.select_access(self.project, self.v1.uid, finals)
                self.assertEqual(found.uses, ())
                self.assertEqual([(item.code, item.reason, item.surface) for item in found.skipped],
                                 [("ACC-001", access_store.EXCLUDED_OTHER_SURFACE, BANK), ("ACC-002", access_store.EXCLUDED_OTHER_SURFACE, EXPLOITATION)])
        text = found.skipped[0].text()
        for part in ("ACC-001", f"«{FIRST}»", f"«{BANK}»", "no se usa"):
            self.assertIn(part, text)
        self.assertNotIn("?", text)

    def test_c_the_design_reading_of_what_is_not_given(self) -> None:
        """RF-012-22 (``accessibilities_excluded`` de ``design``, como ``detections_excluded``): de una superficie, las que no da ``accessibilities_on`` con su causa: todas las de otra
        superficie (con la que tienen) y, sin superficie, todas; una versión que no existe, ``core.version_unknown``."""
        found = access_store.accessibilities_excluded(self.project, self.v1.uid, BANK)
        self.assertEqual([(item.code, item.name, item.surface, item.reason) for item in found], [("ACC-002", SECOND, EXPLOITATION, access_store.EXCLUDED_OTHER_SURFACE)])
        found = access_store.accessibilities_excluded(self.project, self.v1.code, None)
        self.assertEqual([(item.code, item.reason) for item in found], [("ACC-001", "other_surface"), ("ACC-002", "other_surface")])
        self.assertEqual(access_store.accessibilities_excluded(self.project, self.v1.uid, "des_exp_no_existe")[0].surface, BANK)
        with self.project.read() as conn:
            self.assertEqual(access_store.accessibilities_excluded(self.project, self.v1.uid, BANK, conn=conn), access_store.accessibilities_excluded(self.project, self.v1.uid, BANK))
        with self.assertRaises(versions_model.VersionError) as caught:
            access_store.accessibilities_excluded(self.project, "V99", BANK)
        self.assertEqual(caught.exception.code, "core.version_unknown")

    def test_d_the_zones_each_final_communicates(self) -> None:
        """RF-012-22, RF-017-25: de cada final, las zonas que comunica su accesibilidad, leídas de su tabla: la zona con acceso (400 m² en la berma de 135 m, al este de las rampas) y
        no la otra (a 18 m de lo alcanzable); el tajo, ninguna accesibilidad (``None``)."""
        found = cstore.select_access(self.project, self.v1.uid, FINALS)
        self.assertEqual(cstore.read_communicated(self.project, found, 3), (frozenset({WITH}), frozenset({WITH}), None))
        with self.project.read() as conn:
            self.assertEqual(cstore.read_communicated(self.project, found, 3, conn=conn), (frozenset({WITH}), frozenset({WITH}), None))
        missing = cstore.AccessSelection((cstore.AccessUse(1, "ACC-009", "Fantasma", BANK, "no-es-un-dato", BANK),))
        with self.assertRaises(ValueError):
            cstore.read_communicated(self.project, missing, 1)

    def test_e_the_inputs_of_the_operation_are_the_zone_tables_by_role(self) -> None:
        """RF-012-24: ``verify_inputs`` da, además de la partida y las finales, la tabla de zonas de cada accesibilidad como entrada con su papel ``road_access_<k>`` (de 1 en 1), por el
        uid de su dato; con la selección dada, esa (y vacía, ninguna)."""
        found = cstore.select_access(self.project, self.v1.uid, FINALS)
        uses = cstore.verify_inputs(self.project, self.v1.uid, START, FINALS)
        self.assertEqual([(use.item, use.role) for use in uses][:5], [(rd.dataset_of("rampa"), "start"), (BANK, "final_1"), (EXPLOITATION, "final_2"), (PIT, "final_3"),
                                                                       (found.datasets[0], "road_access_1")])
        self.assertEqual([(use.item, use.role) for use in uses][-2:], [(found.datasets[0], "road_access_1"), (found.datasets[1], "road_access_2")])
        self.assertEqual(cstore.verify_inputs(self.project, self.v1.uid, START, FINALS, access=found), uses)
        empty = cstore.verify_inputs(self.project, self.v1.uid, START, FINALS, access=cstore.AccessSelection())
        self.assertEqual([use.role for use in empty], ["start", "final_1", "final_2", "final_3"])


# ---------------------------------------------------------------------------------------------
# Verificar con la accesibilidad, quedar obsoleta, recalcular
# ---------------------------------------------------------------------------------------------


class VerifyWithAccessTest(_WithAccessibilities):
    """RF-012-22, RF-012-24, RF-012-25: verificar con la accesibilidad automática, congelar, quedar obsoleta y recalcular. En orden: cada prueba parte de lo que dejó la anterior."""

    def test_a_the_three_answers_by_final(self) -> None:
        """RF-012-22, P-9, CE-017-09: la cantera con bancos y la explotación comunican la zona con acceso («cumple») y no la otra («no cumple»); el tajo, sin accesibilidad, deja las dos
        «sin comprobar»; las tres finales no cumplen (la zona sin comunicar y, en el tajo, lo demás), y lo que se mueve en las zonas es lo de siempre."""
        stored = self.verify()
        result = stored.result
        wanted = {(1, WITH): "complies", (1, WITHOUT): "fails", (2, WITH): "complies", (2, WITHOUT): "fails", (3, WITH): "unchecked", (3, WITHOUT): "unchecked"}
        self.assertEqual({(position, zone): result.finals[position - 1].zone(zone).verdict.value for position, zone in wanted}, wanted)
        self.assertTrue(result.fails[0] and result.fails[1])
        self.assertEqual(self.verdicts(self.read()), wanted)
        plain = _last(cstore.verify_steps(
            compliance.ComplianceRequest(NAME, START, FINALS, self.masks_v1, 0.02),
            cstore.project_sources(self.project, START, FINALS, version_uid=self.v1.uid), references=gis_store.project_references(self.project)))
        for position in (1, 2, 3):  # lo de siempre: totales y grupos de cada recinto, salvo el veredicto de las zonas «requiere acceso»
            for item, old in zip(result.finals[position - 1].totals, plain.finals[position - 1].totals, strict=True):
                self.assertEqual((item.code, item.cut_m3, item.fill_m3, item.moved_m2, item.counted_m3), (old.code, old.cut_m3, old.fill_m3, old.moved_m2, old.counted_m3))
                if item.code not in (WITH, WITHOUT):
                    self.assertEqual(item.verdict, old.verdict)
            self.assertEqual([(g.zone, g.cells) for g in result.finals[position - 1].groups], [(g.zone, g.cells) for g in plain.finals[position - 1].groups])

    def test_b_the_operation_consumes_the_zone_tables_and_records_them(self) -> None:
        """RF-012-24: la operación consume la tabla de zonas de cada accesibilidad como ``road_access_1`` y ``_2`` (los datos ``des_acz_`` vigentes), sus ajustes dicen cuáles
        (accesibilidad, final y dato) y la tabla las nombra, por final; las cifras son las de siempre (finitas) y está al día."""
        uid = self.op_named()
        inputs = self.inputs(uid)
        self.assertEqual((inputs["road_access_1"], inputs["road_access_2"]), (self.zones_table("ACC-001"), self.zones_table("ACC-002")))
        for name in (inputs["road_access_1"], inputs["road_access_2"]):
            self.assertTrue(name.startswith("des_acz_"), name)
        settings = self.settings_of(uid)
        self.assertEqual([(item["final"], item["code"], item["name"], item["surface"]) for item in settings["access"]], [(1, "ACC-001", FIRST, BANK), (2, "ACC-002", SECOND, EXPLOITATION)])
        self.assertNotIn("access_skipped", settings)
        stored = self.read()
        self.assertEqual([final for final, _text in stored.access], [1, 2])
        self.assertTrue(all("ACC-00" in text for _final, text in stored.access))
        self.assertEqual(tuple(item.text("es") for item in stored.access_selection.uses), tuple(text for _final, text in stored.access))
        self.assertEqual(stored.access_selection, cstore.AccessSelection.of_settings(settings))
        self.assertTrue(all(np.isfinite(value) for value in self.figures_of(uid).values()))
        self.assertFalse(self.stale(uid))

    def test_c_freezing_names_the_zone_that_is_not_communicated(self) -> None:
        """RF-012-25, RF-012-22: congelar con esta verificación lista, de las finales que no cumplen, la zona sin comunicar «zona_sin_acceso» (no la que sí se comunica) y la nota no habla de
        m³ para ella."""
        with self.project.read() as conn:
            found = cstore.freeze_findings(conn, self.v1.uid)
        texts = [finding.text for finding in found if finding.name == NAME]
        self.assertTrue(texts)
        joined = " ".join(texts)
        self.assertIn(f"«{WITHOUT}»: sin comunicar por la accesibilidad", joined)
        self.assertNotIn(f"«{WITH}»", joined)
        self.assertNotIn(f"«{WITHOUT}»: 0", joined)

    def test_d_changing_an_entry_makes_the_check_stale_and_the_stale_accessibility_is_not_used(self) -> None:
        """RF-012-24, RF-012-22, P-9: mover un punto de la capa de entradas deja obsoletas las dos accesibilidades y, con ellas, la verificación (su tabla de zonas es una de sus
        entradas); ya no se usan —la selección lo dice con su causa— y una verificación nueva da las zonas «sin comprobar» de esas finales y lo avisa nombrando la accesibilidad y lo
        que cambió."""
        old = self.op_named()
        self.assertFalse(self.stale(old))
        rewrite_layer(self.project, self.clock, rd.ENTRIES_LAYER, move=2.0)
        for code in ("ACC-001", "ACC-002"):
            self.assertTrue(self.stale(self.current(code)), code)
        self.assertTrue(self.stale(old), "la verificación, por la tabla de zonas de su accesibilidad")
        found = cstore.select_access(self.project, self.v1.uid, FINALS)
        self.assertEqual(found.uses, ())
        self.assertEqual([(item.code, item.reason, item.final) for item in found.skipped], [("ACC-001", access_store.EXCLUDED_STALE, 1), ("ACC-002", access_store.EXCLUDED_STALE, 2)])
        self.assertTrue(all(item.cause and item.cause_en for item in found.skipped))
        self.assertIn(rd.ENTRIES_LAYER, found.skipped[0].cause)
        self.assertIn("obsoleta", found.skipped[0].text())
        self.assertIn("stale", found.skipped[0].text("en"))
        stored = self.verify(name="Con la accesibilidad obsoleta")
        self.assertEqual(self.verdicts(self.read("Con la accesibilidad obsoleta")), {(final, zone): "unchecked" for final in (1, 2, 3) for zone in (WITH, WITHOUT)})
        read = self.read("Con la accesibilidad obsoleta")
        self.assertEqual(read.access, ())
        self.assertEqual(len(read.access_skipped), 2)
        self.assertTrue(all("obsoleta" in text and rd.ENTRIES_LAYER in text for _final, text in read.access_skipped))
        self.assertFalse([role for role in self.inputs(self.op_named("Con la accesibilidad obsoleta")) if role.startswith("road_access")])
        self.assertEqual(stored.result.finals[0].zone(WITH).verdict, V.UNCHECKED)

    def test_e_recomputing_repeats_the_accessibilities_and_the_check_stays_if_the_zones_did_not_change(self) -> None:
        """RF-012-24, RF-008-26: «Recalcular lo obsoleto» planea las dos accesibilidades y, después, la verificación obsoleta; repetidas las accesibilidades, la tabla de zonas de cada una sale
        **igual** (mover la entrada 2 m no cambia qué zonas comunica: el dato de cada tabla es el mismo) y la verificación, que consume esa tabla, deja de estar obsoleta sin repetirse (la
        008 compara lo que consume): sigue siendo la misma operación con las mismas respuestas, y una nueva usa las accesibilidades de ahora."""
        old = self.op_named()
        used_before = {item["code"]: item["dataset"] for item in self.settings_of(old)["access"]}
        self.assertEqual(self.recompute_plan(), [("des.road_access",), ("des.road_access",), (cstore.VERIFY,)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * 2)
        self.assertEqual({self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0] for result in outcome.results for uid in result.operations}, {"des.road_access"})
        self.assertFalse(self.stale(old))
        self.assertEqual(self.op_named(), old)
        self.assertEqual(self.recompute_plan(), [])
        now = cstore.select_access(self.project, self.v1.uid, FINALS)
        self.assertEqual([use.code for use in now.uses], ["ACC-001", "ACC-002"])
        self.assertEqual(now.skipped, ())
        self.assertEqual({use.code: use.dataset for use in now.uses}, used_before, "el contenido de las tablas de zonas no cambió: el dato es el mismo")
        self.assertEqual(cstore.read_communicated(self.project, now, 3), (frozenset({WITH}), frozenset({WITH}), None))
        stored = self.verify(name="Con la accesibilidad recalculada")
        self.assertEqual(self.verdicts(self.read("Con la accesibilidad recalculada")), {(1, WITH): "complies", (1, WITHOUT): "fails", (2, WITH): "complies", (2, WITHOUT): "fails",
                                                                                         (3, WITH): "unchecked", (3, WITHOUT): "unchecked"})
        self.assertEqual({item["code"]: item["dataset"] for item in self.settings_of(self.op_named("Con la accesibilidad recalculada"))["access"]}, {use.code: use.dataset for use in now.uses})
        self.assertEqual(stored.result.fails[:2], (True, True))

    def test_f_a_threshold_of_one_accessibility_changes_the_answer_of_its_final_only(self) -> None:
        """RF-012-24, RF-015-16: cambiar la pendiente transitable de ``ACC-001`` (3 %: las rampas del 12,5 % ya no se andan) deja obsoleta solo esa accesibilidad y la verificación;
        recalcular las repite en orden (la accesibilidad y, después, cada verificación que la consumía) y la zona con acceso de **su** final ya no se comunica («no cumple»), mientras la
        otra final conserva «cumple»."""
        old = self.op_named()
        other = self.current("ACC-002")
        self.clock.advance(minutes=1)
        self.change(f"{KEY}walk_slope_pct", 3.0)
        self.assertTrue(self.stale(old))
        self.assertFalse(self.stale(other), "la otra accesibilidad no cambió")
        self.assertEqual({cause for cause, _name in self.stale_causes(self.current("ACC-001"))}, {"parameter_changed"})
        self.assertEqual(self.recompute_plan(), [("des.road_access",), (cstore.VERIFY,), (cstore.VERIFY,)])  # la accesibilidad y las dos verificaciones que la consumen
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * 3)
        self.assertEqual([self.query("SELECT op_type FROM gb_operation WHERE uid = ?", result.operations[0])[0][0] for result in outcome.results],
                         ["des.road_access", cstore.VERIFY, cstore.VERIFY])  # en orden: la accesibilidad primero
        verdicts = self.verdicts(self.read())
        self.assertEqual((verdicts[(1, WITH)], verdicts[(1, WITHOUT)]), ("fails", "fails"))
        self.assertEqual((verdicts[(2, WITH)], verdicts[(2, WITHOUT)]), ("complies", "fails"))
        again = self.verdicts(self.read("Con la accesibilidad recalculada"))
        self.assertEqual((again[(1, WITH)], again[(2, WITH)]), ("fails", "complies"))
        self.assertEqual(self.current("ACC-002"), other)
        self.assertFalse(self.stale(self.op_named()))
        self.assertEqual(self.recompute_plan(), [])

    def test_g_a_berm_that_changed_also_makes_the_check_stale(self) -> None:
        """RF-012-24: sustituir los datos de la cantera (las bermas, sin la de 135 m) deja obsoletas las accesibilidades que las leen y, con ellas, la verificación; recalcular la deja al día
        otra vez."""
        old = self.op_named()
        levels = rd.bank_berms(self.grid).copy()
        levels[levels == 135.0] = np.nan
        type(self).quarry_uid = self.write_quarry(QUARRY, shift=1.0, supersedes=self.quarry_uid, berms=levels)
        self.assertIn(BERMS_DATASET, {name for _kind, name in self.stale_causes(self.current("ACC-001"))})
        self.assertTrue(self.stale(old))
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertTrue(all(result.status == recompute_mod.UnitStatus.DONE for result in outcome.results))
        self.assertFalse(self.stale(self.op_named()))
        self.assertEqual(self.recompute_plan(), [])


# ---------------------------------------------------------------------------------------------
# Congelar y reproducir
# ---------------------------------------------------------------------------------------------


class ReproduceTest(_WithAccessibilities):
    """RF-012-24: la verificación con la accesibilidad, congelada y reproducida."""

    def test_a_a_frozen_check_with_the_accessibility_reproduces_the_same(self) -> None:
        """RF-012-24: congelada V01.r1, reproducir la verificación con la accesibilidad (la tabla de zonas de cada una como entrada congelada) da las mismas salidas (con su hash: la tabla con
        las filas de la accesibilidad y los veredictos) y las mismas cifras bit a bit, sin escribir nada en el proyecto."""
        self.verify(name="Reproducida")
        uid = self.op_named("Reproducida")
        figures = self.figures_of(uid)
        self.assertTrue({"road_access_1", "road_access_2"} <= set(self.inputs(uid)))
        with self.project.write_transaction() as conn:  # congelar no admite lo obsoleto sin aceptarlo: los datos de la segunda cantera, que nada lee, dejan de estarlo
            conn.execute("DELETE FROM gb_stale")
        self.clock.advance(minutes=1)
        outcome = _last(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = _last(reproduce.reproduce_steps(self.project, str(outcome.frozen.uid)))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        mine = [check for check in report.outputs if check.operation_uid == uid]
        grids = self.read("Reproducida").grids
        self.assertEqual(sorted(check.role for check in mine), sorted(["groups", "table", *(f"violations_{k}" for k in grids)]))
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        reproduced = {(check.key, figures_mod.scope_json(check.scope)): check.reproduced for check in report.figures if check.operation_uid == uid}
        self.assertEqual(reproduced, figures)
        self.assertNotIn(uid, [note.operation_uid for note in report.not_reproducible])


if __name__ == "__main__":
    unittest.main()
