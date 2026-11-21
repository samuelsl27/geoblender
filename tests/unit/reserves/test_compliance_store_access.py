# SPDX-License-Identifier: GPL-3.0-or-later
"""La verificación por recinto con la accesibilidad de las pistas, sin proyecto (spec 017, T18; HU-017-3; RF-012-21, RF-012-22, RF-012-24,
RF-012-25; RF-017-25; plan 017 §5.4 A12, §5.7 P-9, §5.8 H-7; DIFF-012 §2 y §4).

El «verde» lleva lo que no necesita proyecto (P-12); lo que lo necesita —elegir la accesibilidad de cada final, la operación en el proyecto, la
accesibilidad como entrada que la deja obsoleta, recalcular, congelar y reproducir— está en ``milestone_compliance_store_access``. Aquí,
``verify_steps`` sobre una rejilla de 10 × 10 celdas de 1 m con las superficies en GeoTIFF, dos zonas «requiere acceso» (``zona_con_acceso``,
las filas 0 y 1, y ``zona_sin_acceso``, las 2 y 3) y una sin corte (las filas 4 a 9):

- **RF-012-22, RF-012-24**: de cada final, las tres respuestas a mano (comunicada: «cumple»; no comunicada: «no cumple»; sin accesibilidad al
  día para esa final: «sin comprobar»); con dos finales, **cada una la suya** (P-9); la tabla lleva, de cada final con accesibilidad, qué
  accesibilidad usó (``access_used``) y, de las que no, por qué (``access_skipped``); una final con una zona que no se comunica no cumple.
- **Sin accesibilidad**: la tabla, las cifras y los totales de siempre, sin ninguna fila de accesibilidad; los de las demás zonas no cambian
  con ella.
- **RF-012-24**: la selección va en los ajustes (y se lee de ellos, también por JSON), cada accesibilidad tiene su papel (``road_access_<k>``) y
  sus mensajes nombran la accesibilidad, la final y la causa; el resumen da las tres respuestas; congelar nombra la zona sin comunicar.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Iterator
from types import MappingProxyType
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
writer = import_geoblender("gis.geotiff.writer")
model = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")
zones_mod = import_geoblender("gis.masks.zones")
access = import_geoblender("gis.masks.access")
figures_mod = import_geoblender("core.provenance.figures")
surfaces = import_geoblender("reserves.surfaces")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
res_messages = import_geoblender("reserves.messages")
design_provenance = import_geoblender("design.provenance")

GRID = gis.Grid(500000.0, 4400010.0, 1.0, 1.0, 10, 10)
"""10 × 10 celdas de 1 m: la fila 0 es la del norte."""
V = compliance.Verdict
C = compliance.Counts
WITH, WITHOUT, FREE = "zona_con_acceso", "zona_sin_acceso", "r_sin_corte"
NAME = "Verificación de la cantera"


def _last(steps: Iterator[Any]) -> Any:
    found = None
    for step in steps:
        if step.result is not None:
            found = step.result
    return found


def _runs(first: int, last: int) -> Any:
    mask = np.zeros(GRID.shape, dtype=bool)
    mask[first:last + 1] = True
    rows, cols = np.nonzero(mask)
    return zones_mod.Runs(rows, cols, cols + 1)


def _masks(*, requires_access: bool = True) -> Any:
    """Todo dentro del perímetro y del límite; ``zona_con_acceso`` (filas 0 y 1), ``zona_sin_acceso`` (2 y 3) y ``r_sin_corte`` (4 a 9; si
    no ``requires_access``, la zona sin corte son todas las filas y no hay ninguna «requiere acceso»)."""
    classes = np.full(GRID.shape, np.uint16(combine.ClassBit.PERIMETER) | np.uint16(combine.ClassBit.LEGAL), dtype=np.uint16)
    zones = {WITH: _runs(0, 1), WITHOUT: _runs(2, 3), FREE: _runs(4, 9)}
    ctypes = {WITH: model.ConstraintType.REQUIRES_ACCESS, WITHOUT: model.ConstraintType.REQUIRES_ACCESS, FREE: model.ConstraintType.NO_CUT}
    if not requires_access:
        zones, ctypes = {FREE: _runs(0, 9)}, {FREE: model.ConstraintType.NO_CUT}
    return access.MaskSet(GRID, "v" * 32, "o" * 32, access.MaskState.CURRENT, (), classes, (), MappingProxyType(zones), MappingProxyType({}), (),
                          MappingProxyType(ctypes))


def _use(final: int, *, code: str = "ACC-001", name: str = "Accesibilidad de la cantera", dataset: str | None = None, shown: str | None = None) -> Any:
    """Una accesibilidad usada para la final ``final``: su tabla de zonas, ``uid-zonas-<final>``."""
    return cstore.AccessUse(final, code, name, f"gis_dtm_pozo{final}", f"uid-zonas-{final}" if dataset is None else dataset,
                            f"Pozo {final}" if shown is None else shown)


STALE = cstore.SkippedAccess("ACC-002", "Vieja", "stale", "gis_dtm_pozo2", 2, "Pozo 2", "Obsoleto: cambió la capa de entradas (gis_fea_entradas)",
                             "Stale: the entries layer changed (gis_fea_entradas)")
OTHER = cstore.SkippedAccess("ACC-003", "Del banco", "other_surface", "gis_dtm_banco")


class VerifyStepsWithAccessTest(unittest.TestCase):
    """RF-012-22, RF-012-24, P-9: ``verify_steps`` con las zonas comunicadas de cada final, en memoria."""

    @classmethod
    def setUpClass(cls) -> None:
        folder = cls.enterClassContext(project_tmp("gb-csa-"))
        start = np.full(GRID.shape, 100.0)
        final = start.copy()
        final[0, 0:3] = 99.0  # 3 m³ de corte en la zona con acceso
        final[2, 0:2] = 101.0  # 2 m³ de relleno en la zona sin acceso
        final[5, 5] = 98.0  # y 2 m³ de corte en la zona sin corte
        cls.paths = {}
        for key, values in {"inicial": start, "pozo1": final, "pozo2": final, "pozo3": final}.items():
            cls.paths[key] = folder / f"{key}.tif"
            writer.write_geotiff(gis.Raster(GRID, values, fx.CRS, fx.VERTICAL), cls.paths[key], profile="project")
        cls.masks = _masks()

    def source(self, key: str, name: str | None = None) -> Any:
        return surfaces.grid_source(self.paths[key], name=name or key, crs=fx.CRS, vertical=fx.VERTICAL)

    def verify(self, finals: int = 1, communicated: tuple[Any, ...] = (), selection: Any = None) -> Any:
        """``verify_steps`` de ``finals`` finales (``pozo1``…) con ``communicated`` (el conjunto de cada una) y la selección ``selection``."""
        request = compliance.ComplianceRequest(NAME, surfaces.SurfaceRef(dataset="gis_dtm_inicial", label="Levantamiento"),
                                               tuple(surfaces.SurfaceRef(dataset=f"gis_dtm_pozo{k}", label=f"Pozo {k}") for k in range(1, finals + 1)),
                                               self.masks, 0.02, communicated=communicated)
        found = {cstore.START_ROLE: self.source("inicial", "Levantamiento"),
                 **{cstore.final_role(k): self.source(f"pozo{k}", f"Pozo {k}") for k in range(1, finals + 1)}}
        return _last(cstore.verify_steps(request, found, references=(fx.CRS, fx.VERTICAL), access=selection))

    @staticmethod
    def rows(result: Any, *, zone: str = "", final: int | None = None) -> dict[str, Any]:
        """La tabla de ``result`` por cantidad de un recinto (y final): (valor, nota)."""
        return {row[2]: (row[3], row[5]) for row in result.table_rows() if row[0] == zone and (final is None or row[1] == final)}

    def verdicts(self, result: Any, final: int) -> dict[str, str]:
        return {zone: self.rows(result, zone=zone, final=final)["verdict"][1] for zone in (WITH, WITHOUT, FREE)}

    def test_a_the_three_answers_by_final(self) -> None:
        """RF-012-22, P-9: con una final con accesibilidad que comunica solo ``zona_con_acceso``, otra sin accesibilidad al día y otra con
        una que no comunica ninguna, las respuestas son, a mano: comunicada «cumple» y no comunicada «no cumple»; sin accesibilidad, las dos «sin
        comprobar»; con el conjunto vacío, las dos «no cumplen». La final 2 (sin accesibilidad) no tiene fila de accesibilidad."""
        selection = cstore.AccessSelection((_use(1), _use(3)))
        result = self.verify(3, (frozenset({WITH}), None, frozenset()), selection)
        self.assertEqual(self.verdicts(result, 1), {WITH: "complies", WITHOUT: "fails", FREE: "fails"})
        self.assertEqual(self.verdicts(result, 2), {WITH: "unchecked", WITHOUT: "unchecked", FREE: "fails"})
        self.assertEqual(self.verdicts(result, 3), {WITH: "fails", WITHOUT: "fails", FREE: "fails"})
        self.assertEqual(result.fails, (True, True, True))
        used = [(row[1], row[5]) for row in result.table_rows() if row[2] == "access_used"]
        self.assertEqual(used, [(1, "Accesibilidad de «Pozo 1»: ACC-001 «Accesibilidad de la cantera»"),
                                (3, "Accesibilidad de «Pozo 3»: ACC-001 «Accesibilidad de la cantera»")])
        self.assertEqual(result.access, selection)
        # el movimiento de las zonas «requiere acceso» sigue siendo el de siempre: lo da cada final, con o sin accesibilidad
        for final in (1, 2, 3):
            with_access = self.rows(result, zone=WITH, final=final)
            self.assertEqual((with_access["cut_m3"][0], with_access["moved_area_m2"][0], with_access["counted_m3"]), (3.0, 3.0, (0.0, "access")))
            self.assertEqual(self.rows(result, zone=WITHOUT, final=final)["fill_m3"][0], 2.0)

    def test_b_with_two_finals_each_has_its_own_accessibility(self) -> None:
        """P-9: las dos finales con accesibilidad, cada una con su conjunto: lo que comunica la de una no sirve a la otra (la final 1
        comunica la zona con acceso y la 2 la zona sin acceso)."""
        selection = cstore.AccessSelection((_use(1), _use(2, code="ACC-002", name="Otra")))
        result = self.verify(2, (frozenset({WITH}), frozenset({WITHOUT})), selection)
        self.assertEqual((self.verdicts(result, 1)[WITH], self.verdicts(result, 1)[WITHOUT]), ("complies", "fails"))
        self.assertEqual((self.verdicts(result, 2)[WITH], self.verdicts(result, 2)[WITHOUT]), ("fails", "complies"))
        self.assertEqual([row[5] for row in result.table_rows() if row[2] == "access_used"],
                         ["Accesibilidad de «Pozo 1»: ACC-001 «Accesibilidad de la cantera»", "Accesibilidad de «Pozo 2»: ACC-002 «Otra»"])

    def test_c_what_is_not_used_is_noted_with_its_cause(self) -> None:
        """RF-012-24, RF-012-22: una accesibilidad obsoleta (de la final 2) y otra hecha sobre otra superficie (de ninguna final) no se
        usan: la tabla las nombra (``access_skipped``, con la final a la que se refieren y, si hay, la causa) y la final 2 queda «sin
        comprobar»."""
        selection = cstore.AccessSelection((_use(1),), (STALE, OTHER))
        result = self.verify(2, (frozenset({WITH}), None), selection)
        self.assertEqual(self.verdicts(result, 2)[WITH], "unchecked")
        skipped = [(row[1], row[5]) for row in result.table_rows() if row[2] == "access_skipped"]
        self.assertEqual([final for final, _text in skipped], [0, 2])
        by_final = dict(skipped)
        self.assertIn("ACC-003", by_final[0])
        self.assertIn("gis_dtm_banco", by_final[0])
        self.assertIn("ACC-002", by_final[2])
        self.assertIn("«Pozo 2»", by_final[2])
        self.assertIn("gis_fea_entradas", by_final[2])
        self.assertIn("obsoleta", by_final[2])

    def test_d_without_an_accessibility_the_table_and_the_figures_are_the_old_ones(self) -> None:
        """RF-012-24: sin accesibilidad (sin dar nada o con la selección vacía) las dos zonas «requiere acceso» son «sin comprobar» y no hay
        ninguna fila de accesibilidad; los totales y las cifras son los mismos que con ella, salvo el veredicto de esas zonas."""
        plain = self.verify(1)
        empty = self.verify(1, (), cstore.AccessSelection())
        self.assertEqual(plain.table_rows(), empty.table_rows())
        self.assertEqual(self.verdicts(plain, 1), {WITH: "unchecked", WITHOUT: "unchecked", FREE: "fails"})
        quantities = {row[2] for row in plain.table_rows()}
        self.assertFalse(quantities & {"access_used", "access_skipped"})
        self.assertEqual(plain.access, cstore.AccessSelection())
        given = self.verify(1, (frozenset({WITH, WITHOUT}),), cstore.AccessSelection((_use(1),)))

        def stripped(result: Any) -> list[tuple[Any, ...]]:
            return [row for row in result.table_rows() if row[2] not in ("verdict", "access_used")]

        self.assertEqual(stripped(plain), stripped(given))
        self.assertEqual({(spec.key, figures_mod.scope_json(spec.scope)): spec.value for spec in plain.figures},
                         {(spec.key, figures_mod.scope_json(spec.scope)): spec.value for spec in given.figures})
        self.assertTrue(all(np.isfinite(spec.value) for spec in given.figures))

    def test_e_the_request_the_sources_and_the_selection_agree(self) -> None:
        """RF-012-24: una accesibilidad de la selección para una final que no tiene conjunto en la petición (o que no existe) es un error del
        programa (``ValueError``) al llamar, sin dar ningún paso."""
        with self.assertRaises(ValueError):
            self.verify(2, (frozenset(), None), cstore.AccessSelection((_use(2),)))
        with self.assertRaises(ValueError):
            self.verify(1, (), cstore.AccessSelection((_use(1),)))
        with self.assertRaises(ValueError):
            self.verify(1, (frozenset(),), cstore.AccessSelection((_use(3),)))

    def test_f_the_summary_gives_the_three_answers(self) -> None:
        """RF-012-22, RF-012-24: el último aviso del cálculo da las tres respuestas de las zonas «requiere acceso» (a mano, de las tres
        finales de la prueba a: 1 cumple, 3 no cumplen y 2 sin comprobar) y, sin ninguna zona «requiere acceso», el texto de siempre, tal cual."""
        selection = cstore.AccessSelection((_use(1), _use(3)))
        request = compliance.ComplianceRequest(NAME, surfaces.SurfaceRef(dataset="gis_dtm_inicial"),
                                               tuple(surfaces.SurfaceRef(dataset=f"gis_dtm_pozo{k}") for k in (1, 2, 3)), self.masks, 0.02,
                                               communicated=(frozenset({WITH}), None, frozenset()))
        found = {cstore.START_ROLE: self.source("inicial"), **{cstore.final_role(k): self.source(f"pozo{k}") for k in (1, 2, 3)}}
        last = None
        for step in cstore.verify_steps(request, found, references=(fx.CRS, fx.VERTICAL), access=selection):
            last = step
        self.assertIn("no cumplen las finales 1, 2, 3", last.message)
        self.assertIn("«requiere acceso»: cumplen 1, no cumplen 3, sin comprobar 2", last.message)
        plain = self.verify(1)
        self.assertEqual(cstore._summary(plain), f"«{NAME}»: no cumplen las finales 1 · «requiere acceso»: cumplen 0, no cumplen 0, sin comprobar 2")
        flat = compliance.ComplianceRequest(NAME, surfaces.SurfaceRef(dataset="gis_dtm_inicial"), (surfaces.SurfaceRef(dataset="gis_dtm_inicial"),),
                                            _masks(requires_access=False), 0.02)
        steps = cstore.verify_steps(flat, {cstore.START_ROLE: self.source("inicial"), cstore.final_role(1): self.source("inicial")},
                                    references=(fx.CRS, fx.VERTICAL))
        self.assertEqual(_last_message(steps), f"«{NAME}»: todas las finales cumplen")


def _last_message(steps: Iterator[Any]) -> str:
    message = ""
    for step in steps:
        message = step.message
    return message


class AccessSelectionTest(unittest.TestCase):
    """RF-012-24, RF-012-31 (por analogía), P-9: la selección de las accesibilidades de una verificación."""

    def test_the_role_of_an_accessibility(self) -> None:
        """RF-012-24: el papel de cada accesibilidad entre las entradas se cuenta de 1 en 1 y cuelga del papel de la accesibilidad
        (``road_access``) como el de la base de los acopios cuelga del suyo; el de cero o negativo, no."""
        self.assertEqual([cstore.access_role(k) for k in (1, 2, 10)], ["road_access_1", "road_access_2", "road_access_10"])
        self.assertTrue(cstore.access_role(1).startswith(design_provenance.ROAD_ACCESS_ROLE))
        for bad in (0, -1, True, "1"):
            with self.assertRaises(ValueError):
                cstore.access_role(bad)  # type: ignore[arg-type]

    def test_the_uses_of_each_final_and_the_sets_it_gives(self) -> None:
        """P-9: ``uses_of`` da las accesibilidades de una final (desde 1) y ``communicated_by_final`` el conjunto de cada una, que es la unión
        de lo que comunican las de esa final (nada que se pierda) y ``None`` si no tiene ninguna (de 1 a el número de finales)."""
        selection = cstore.AccessSelection((_use(1), _use(1, code="ACC-004", name="Segunda"), _use(3)))
        self.assertEqual([(use.final, use.code) for use in selection.uses_of(1)], [(1, "ACC-001"), (1, "ACC-004")])
        self.assertEqual(selection.uses_of(2), ())
        self.assertEqual(selection.datasets, ("uid-zonas-1", "uid-zonas-1", "uid-zonas-3"))
        found = selection.communicated_by_final([frozenset({WITH}), frozenset({WITHOUT}), frozenset()], 3)
        self.assertEqual(found, (frozenset({WITH, WITHOUT}), None, frozenset()))
        self.assertEqual(cstore.AccessSelection().communicated_by_final([], 2), (None, None))
        with self.assertRaises(ValueError):
            selection.communicated_by_final([frozenset()], 3)
        with self.assertRaises(ValueError):
            selection.communicated_by_final([frozenset()] * 3, 2)  # una accesibilidad de la final 3 con solo dos finales

    def test_the_selection_checks_its_pieces(self) -> None:
        """RF-012-24: la selección son ``AccessUse`` y ``SkippedAccess``; una final de cero o menos o una causa que no es de las dos conocidas es
        un error del programa."""
        for bad in (("x",), (_use(1), "x")):
            with self.assertRaises(ValueError):
                cstore.AccessSelection(bad)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            cstore.AccessSelection((), ("x",))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            cstore.AccessUse(0, "ACC-001", "A", "s", "u", "f")
        with self.assertRaises(ValueError):
            cstore.SkippedAccess("ACC-001", "A", "porque sí", "s")

    def test_the_selection_is_noted_in_the_settings_and_read_back(self) -> None:
        """RF-012-24: ``verify_settings`` anota la accesibilidad que usó y las que no (con su causa, en los dos idiomas) y solo eso: sin
        ellas, los ajustes de siempre; ``AccessSelection.of_settings`` los lee y da la misma selección (también pasando por JSON)."""
        start = surfaces.SurfaceRef(dataset="gis_dtm_inicial", label="Levantamiento")
        finals = (surfaces.SurfaceRef(dataset="gis_dtm_pozo1"), surfaces.SurfaceRef(dataset="gis_dtm_pozo2"))
        plain = cstore.verify_settings(NAME, start, finals, ["s1"], ["Sector 1"])
        self.assertEqual(sorted(plain), ["finals", "name", "pending_names", "pending_sectors", "start"])
        self.assertEqual(cstore.verify_settings(NAME, start, finals, ["s1"], ["Sector 1"], access=cstore.AccessSelection()), plain)
        selection = cstore.AccessSelection((_use(1), _use(2, code="ACC-005", name="Otra")), (STALE, OTHER))
        noted = cstore.verify_settings(NAME, start, finals, ["s1"], ["Sector 1"], access=selection)
        self.assertEqual({key: value for key, value in noted.items() if key not in ("access", "access_skipped")}, plain)
        self.assertEqual([(item["dataset"], item["final"], item["code"], item["name"], item["surface"]) for item in noted["access"]],
                         [("uid-zonas-1", 1, "ACC-001", "Accesibilidad de la cantera", "gis_dtm_pozo1"),
                          ("uid-zonas-2", 2, "ACC-005", "Otra", "gis_dtm_pozo2")])
        self.assertEqual([(item["code"], item["reason"], item["final"], item["cause"] != "", item["cause_en"] != "") for item in noted["access_skipped"]],
                         [("ACC-002", "stale", 2, True, True), ("ACC-003", "other_surface", 0, False, False)])
        for settings in (noted, json.loads(json.dumps(noted))):
            self.assertEqual(cstore.AccessSelection.of_settings(settings), selection)
        self.assertEqual(cstore.AccessSelection.of_settings(plain), cstore.AccessSelection())
        only_skipped = cstore.verify_settings(NAME, start, finals, access=cstore.AccessSelection((), (OTHER,)))
        self.assertEqual(sorted(only_skipped), ["access_skipped", "finals", "name", "pending_names", "pending_sectors", "start"])
        both = cstore.verify_settings(NAME, start, finals, ["s1"], ["Sector 1"], bases=cstore.BaseSelection(), access=selection)
        self.assertEqual(both, noted)
        for broken in ({"access": [{"dataset": "x"}]}, {"access": ["x"]}, {"access_skipped": [{"code": "ACC-001"}]}):
            with self.assertRaises(ValueError):
                cstore.AccessSelection.of_settings(broken)

    def test_the_messages_name_the_accessibility_the_final_and_the_cause(self) -> None:
        """RF-012-24: lo que no se usa se avisa nombrando la accesibilidad, la final y la causa (obsoleta: lo que cambió, en el idioma
        de la interfaz; otra superficie: la superficie de la accesibilidad), en español y en inglés, sin marcadores sin llenar; la que se usa,
        la accesibilidad y la final."""
        for language in ("es", "en"):
            for text in (STALE.text(language), OTHER.text(language), _use(1).text(language)):
                with self.subTest(language=language, text=text[:40]):
                    self.assertNotIn("{", text)
                    self.assertNotIn("?", text)
        text = STALE.text()
        for part in ("ACC-002", "«Vieja»", "«Pozo 2»", "obsoleta", "gis_fea_entradas", "sin comprobar"):
            self.assertIn(part, text)
        self.assertIn("stale", STALE.text("en"))
        self.assertIn("the entries layer changed", STALE.text("en"))
        self.assertNotIn("la capa de entradas", STALE.text("en"))
        bare = cstore.SkippedAccess("ACC-002", "Vieja", "stale", "gis_dtm_pozo2", 2, "Pozo 2", "Obsoleto: x")
        self.assertIn("Obsoleto: x", bare.text("en"))  # sin la inglesa, la de siempre
        other = OTHER.text()
        for part in ("ACC-003", "«Del banco»", "«gis_dtm_banco»"):
            self.assertIn(part, other)
        used = _use(1).text()
        self.assertEqual(used, "Accesibilidad de «Pozo 1»: ACC-001 «Accesibilidad de la cantera»")
        self.assertEqual(_use(1).text("en"), "Accessibility of «Pozo 1»: ACC-001 «Accesibilidad de la cantera»")

    def test_the_stored_selection_is_read_from_the_settings_of_the_operation(self) -> None:
        """RF-012-24: ``_stored_access`` lee de los ajustes (JSON) de una verificación la selección de las accesibilidades (lo que la ventana
        necesita para escribir sus líneas en el idioma de la interfaz); sin ella, la vacía; con unos ajustes que no se entienden, la vacía, sin
        lanzar."""
        start = surfaces.SurfaceRef(dataset="gis_dtm_inicial")
        finals = (surfaces.SurfaceRef(dataset="gis_dtm_pozo1"),)
        selection = cstore.AccessSelection((_use(1),), (OTHER,))
        noted = json.dumps(cstore.verify_settings(NAME, start, finals, access=selection))
        self.assertEqual(cstore._stored_access(noted), selection)
        self.assertEqual(cstore._stored_access(json.dumps(cstore.verify_settings(NAME, start, finals))), cstore.AccessSelection())
        for text in ("", "no es json", "[]", "null", None, '{"access": [{"dataset": "x"}]}'):
            with self.subTest(text=text):
                self.assertEqual(cstore._stored_access(text), cstore.AccessSelection())
        bare = cstore.StoredVerification("op", "Prueba", False, (), (), (), (), (), {})
        self.assertEqual((bare.access, bare.access_skipped, bare.access_selection), ((), (), cstore.AccessSelection()))


class FrozenAndStoredTest(unittest.TestCase):
    """RF-012-25, RF-012-24: lo que guarda la tabla de una zona «requiere acceso» y lo que dice congelar."""

    @classmethod
    def setUpClass(cls) -> None:
        folder = cls.enterClassContext(project_tmp("gb-csa-"))
        start = np.full(GRID.shape, 100.0)
        final = start.copy()
        final[0, 0:3] = 99.0
        cls.rows: dict[str, Any] = {}
        for key, values in {"inicial": start, "pozo1": final}.items():
            path = folder / f"{key}.tif"
            writer.write_geotiff(gis.Raster(GRID, values, fx.CRS, fx.VERTICAL), path, profile="project")
            cls.rows[key] = path

    def table(self, communicated: Any) -> list[Any]:
        request = compliance.ComplianceRequest(NAME, surfaces.SurfaceRef(dataset="gis_dtm_inicial"), (surfaces.SurfaceRef(dataset="gis_dtm_pozo1"),),
                                               _masks(), 0.02, communicated=() if communicated is None else (communicated,))
        found = {cstore.START_ROLE: surfaces.grid_source(self.rows["inicial"], name="inicial", crs=fx.CRS, vertical=fx.VERTICAL),
                 cstore.final_role(1): surfaces.grid_source(self.rows["pozo1"], name="pozo1", crs=fx.CRS, vertical=fx.VERTICAL)}
        return _last(cstore.verify_steps(request, found, references=(fx.CRS, fx.VERTICAL))).table_rows()  # type: ignore[no-any-return]

    def test_a_zone_that_is_not_communicated_is_named_when_freezing(self) -> None:
        """RF-012-22, RF-012-25: congelar con una zona «requiere acceso» que no se comunica nombra la zona y que no la comunica la
        accesibilidad (``res.freeze_access``), no «0 m³ de movimiento»; con las comunicadas o sin accesibilidad, ninguna nota de ella; la nota
        de las demás zonas, la de siempre."""
        notes = cstore._failures(self.table(frozenset({WITH})), NAME)
        self.assertEqual(len(notes), 1)
        self.assertIn(f"«{WITHOUT}»: sin comunicar por la accesibilidad", notes[0])
        self.assertNotIn("m³ de movimiento", notes[0])
        self.assertNotIn(f"«{WITH}»", notes[0])
        self.assertIn("not communicated by the accessibility", res_messages.render("res.freeze_access", language="en", zone="«a»"))
        for communicated in (frozenset({WITH, WITHOUT}), None):
            with self.subTest(communicated=communicated):
                notes = cstore._failures(self.table(communicated), NAME)
                self.assertFalse([note for note in notes if "accesibilidad" in note])

    def test_the_stored_table_gives_the_verdict_and_the_way_of_counting(self) -> None:
        """RF-012-24: de la tabla que se guarda, la zona «requiere acceso» da ``access`` como lo que cuenta y su veredicto (las tres
        respuestas) y su movimiento de siempre."""
        for communicated, wanted in ((frozenset({WITH}), ("complies", "fails")), (frozenset(), ("fails", "fails")), (None, ("unchecked", "unchecked"))):
            with self.subTest(communicated=communicated):
                stored = {item.zone: item for item in cstore._stored_zones(self.table(communicated))}
                self.assertEqual((stored[WITH].counts, stored[WITH].verdict, stored[WITHOUT].verdict), ("access", *wanted))
                self.assertEqual((stored[WITH].cut_m3, stored[WITH].moved_m2), (3.0, 3.0))


if __name__ == "__main__":
    unittest.main()
