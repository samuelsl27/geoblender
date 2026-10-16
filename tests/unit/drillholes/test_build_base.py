# SPDX-License-Identifier: GPL-3.0-or-later
"""La base de los sondeos desde lo importado (spec 005, T41; HU-005-1, HU-005-2, HU-005-4;
plan 005 §5.6.1, D17, D21 y D22; ``drillholes.build_base``).

Lo importado de ``tests/data/dh/csv_basico`` y de ``csv_convenios`` se lee **fichero a
fichero** con el lector real (``interop.drillholes_tabular.read_role``: una entrada por
fichero, D-15), y la base se construye con el ``CrsService`` falso de las pruebas (γ = 1,50°
en todas las bocas; la reproyección y la convergencia reales, en
``tests/referencia/dh/test_build_base_reference.py``):

- **RF-005-02** (el valor de la fuente): ``csv_basico`` fichero a fichero da la base que da su
  importación entera (``dh_sets.basico_set``, el lector de T14) con las estaciones convertidas,
  bit a bit: la orientación en boca de S-12, la vertical declarada de C-01, las profundidades
  y las leyes; cada fila con su entrada.
- **RF-005-27 a RF-005-29** (convenios): las tres variantes de ``csv_convenios`` (inclinación
  positiva hacia abajo o desde la vertical, azimut magnético con δ = +0,25°, leyes en ppb, g/t
  y ppm) dan, columna a columna, la base de ``csv_basico`` salvo lo que se guarda como venía
  (azimut medido, su referencia, δ y γ, texto y unidad del laboratorio), que se conserva.
- **RF-005-11** (sustituir o conservar): una entrada registrada más tarde gana en las tablas
  de los sondeos que trae y en los códigos de catálogo que trae, y en nada más; sin ella, la
  base anterior, bit a bit; registrada antes, no gana.
- **RF-005-22** (trazas obsoletas por sondeo): otra declinación cambia ``survey_sha256`` solo
  de los sondeos de esa entrada (``changed_holes``).
- Identificadores deterministas (RF-008-26): bocas por nombre sin mayúsculas, catálogos por
  código, lo demás por sondeo y profundidad; las filas en otro orden, los mismos bytes; las
  filas caben en cada tabla (``drillholes.schema.table_digest``); lo que no pasa a la base
  (DH-E01, DH-E04, DH-E11) se dice; sin declarar el CRS o el azimut, nada se supone
  (RF-005-07); sin bucles por fila; las entradas no cambian.
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from unittest import mock

import numpy as np

from tests.support import dh_sets
from tests.support.dh_fakes import FakeCrsService
from tests.support.package import import_geoblender

build = import_geoblender("drillholes.build_base")
model = import_geoblender("drillholes.model")
schema = import_geoblender("drillholes.schema")
conventions = import_geoblender("drillholes.conventions")
tabular = import_geoblender("interop.drillholes_tabular")
csv_tables = import_geoblender("interop.csv_tables")
wkb = import_geoblender("core.gpkg.wkb")
gis_messages = import_geoblender("gis.messages")

H25830, V5782 = dh_sets.H25830, dh_sets.V5782
PROJECT_UID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
CONVENIOS = dh_sets.DATA / "csv_convenios"
BASICO_ROLES = ("collar", "survey", "lithology", "assay_wide", "lithology_catalog",
                "element_catalog")
CONVENIOS_FILES = {"collar": "collars_{variant}.csv", "survey": "surveys_{variant}.csv",
                   "lithology": "lithology.csv", "assay_long": "assays.csv",
                   "lithology_catalog": "lithology_codes.csv", "element_catalog": "elements.csv"}
HOLES = ("C-01", "S-01", "S-02", "S-03", "S-04", "S-12")  # por su nombre sin mayúsculas
SURVEYED = ("S-01", "S-02", "S-03", "S-04")
AS_REPORTED = {"dh_survey": ("azimuth_measured", "azimuth_ref", "declination_deg",
                             "convergence_deg"),
               "dh_assay": ("reported_value", "reported_unit")}
SET_TABLES = {"collars": "dh_collar", "surveys": "dh_survey", "lithology": "dh_lithology",
              "assays": "dh_assay", "zones": "dh_zone_interval", "structures": "dh_structure"}

BASICO: list = []
BASICO_BASE = None


def _uid(number: int) -> str:
    """El uid (un UUID en texto) de la entrada ``number`` de las pruebas."""
    return f"{number:08x}-0000-4000-8000-{number:012x}"


def _basico_declaration(**changes: object) -> object:
    """La declaración de ``csv_basico/esperado.json`` con ``changes``."""
    found = dh_sets.basico_expected()["declaration"]
    values = dict(
        crs=H25830, vertical=V5782, azimuth_ref=found["azimuth_ref"],
        declination_deg=found["declination_deg"],
        inclination_convention=found["inclination_convention"], units=found["units"],
        value_rules=model.ValueRules(decimal_mark=found["decimal_mark"]),
        all_vertical=found["all_vertical"], density_kind=found["density_kind"],
        date_format=found["date_format"])
    values.update(changes)
    return model.SourceDeclaration(**values)


def _convenios_declaration(variant: str, **changes: object) -> object:
    """La declaración de la variante ``variant`` de ``csv_convenios`` con ``changes``."""
    import json

    expected = json.loads((CONVENIOS / "esperado.json").read_text(encoding="utf-8"))
    common, chosen = expected["declaration"], expected["variants"][variant]
    values = dict(
        crs=H25830, vertical=V5782, azimuth_ref=chosen["azimuth_ref"],
        declination_deg=chosen["declination_deg"],
        inclination_convention=chosen["inclination_convention"], units={},
        value_rules=model.ValueRules(decimal_mark=common["decimal_mark"]),
        all_vertical=common["all_vertical"], density_kind=common["density_kind"],
        date_format=common["date_format"])
    values.update(changes)
    return model.SourceDeclaration(**values)


def _entry(number: int, role: str, table: object, declaration: object) -> object:
    """La entrada ``number`` de un fichero con el papel ``role``: sus filas, leídas con el
    lector real y la correspondencia que propone."""
    rows = tabular.read_role(role, table, tabular.suggest_mapping(role, table.columns),
                             declaration)
    return build.SourceEntry(_uid(number), declaration, collars=rows.collars,
                             surveys=rows.surveys, lithology=rows.lithology,
                             assays=rows.assays, catalogs=rows.catalogs, label=role)


def _basico_entries(**declarations: object) -> list:
    """Las seis entradas de ``csv_basico`` (análisis en columnas), con la declaración de
    ``esperado.json`` o, por papel, la de ``declarations``."""
    tables = dh_sets.basico_tables()
    return [_entry(n, role, tables[role], declarations.get(role, _basico_declaration()))
            for n, role in enumerate(BASICO_ROLES, start=1)]


def _convenios_entries(variant: str, **declarations: object) -> list:
    """Las seis entradas de la variante ``variant`` de ``csv_convenios``, con los mismos uids
    que las de ``csv_basico`` (por papel)."""
    found = []
    for n, (role, name) in enumerate(CONVENIOS_FILES.items(), start=1):
        table = csv_tables.read_table(CONVENIOS / name.format(variant=variant),
                                      encoding="utf-8", separator=",")
        declaration = declarations.get(role, _convenios_declaration(variant))
        found.append(_entry(n, role, table, declaration))
    return found


def _build(entries: list, service: object | None = None) -> object:
    return build.build_base(entries, FakeCrsService() if service is None else service,
                            H25830, V5782, project_uid=PROJECT_UID)


def setUpModule() -> None:  # noqa: N802 (nombre de unittest)
    global BASICO_BASE
    BASICO[:] = _basico_entries()
    BASICO_BASE = _build(BASICO)


def _bits(column: np.ndarray) -> list:
    """Una columna comparable bit a bit (NaN, el mismo)."""
    if column.dtype == np.float64:
        array = column + 0.0
        array[np.isnan(array)] = math.nan
        return array.view(np.int64).tolist()
    return column.tolist()


def _table(base: object, table: str, skip: tuple[str, ...] = ()) -> dict:
    return {name: _bits(values) for name, values in base.columns[table].items()
            if name not in skip}


def _records(columns: object) -> list[str]:
    """Las filas de unas columnas del modelo sin su orden (``repr`` distingue los bits)."""
    return sorted(repr(record) for record in columns.records())


def _expected_basico() -> object:
    """El ``DrillholeSet`` de ``csv_basico`` de una importación entera (el lector de T14,
    ``dh_sets.basico_set``) con las estaciones y las leyes convertidas (``conventions``)."""
    dset = dh_sets.basico_set()
    declaration = _basico_declaration()
    gamma = np.full(len(dset.collars), 1.5)
    units = {element.code: element.unit for element in dset.catalogs.elements}
    return dataclasses.replace(
        dset, surveys=conventions.convert_surveys(dset.surveys, declaration, gamma),
        assays=conventions.convert_assays(dset.assays, units))


def _snapshot(entries: list) -> list:
    """Cada columna de cada entrada (para ver que no cambian)."""
    found = []
    for entry in entries:
        for name in model.TABLES:
            columns = getattr(entry, name)
            found.append([_bits(getattr(columns, item.name))
                          for item in dataclasses.fields(columns)])
        found.append(repr(entry.catalogs))
    return found


def _hole_rows(base: object, table: str, hole: str) -> np.ndarray:
    names = base.columns["dh_collar"]["name"].tolist()
    return np.flatnonzero(base.columns[table]["hole_id"] == names.index(hole) + 1)


def _lithology_table(rows: list[list[str]]) -> object:
    """Una tabla de litología con las columnas de ``csv_basico`` (líneas desde la 2)."""
    columns = dh_sets.basico_tables()["lithology"].columns
    return csv_tables.Table(list(columns), rows, list(range(2, len(rows) + 2)))


class BasicoTest(unittest.TestCase):
    """RF-005-02: lo importado fichero a fichero, la base de una importación entera."""

    def test_basico_file_by_file(self) -> None:
        """RF-005-02, HU-005-1: las seis entradas de ``csv_basico`` dan, tabla a tabla, las
        filas de su importación entera con las estaciones convertidas (bit a bit): la
        orientación en boca de S-12 (de la entrada de bocas), la vertical declarada de C-01 y
        las desviaciones medidas de los demás; en el CRS y el datum del proyecto, sin
        transformación ni filas que no pasen."""
        base = BASICO_BASE
        expected = _expected_basico()
        for name in model.TABLES:
            with self.subTest(tabla=name):
                self.assertEqual(_records(getattr(base.dset, name)),
                                 _records(getattr(expected, name)))
        self.assertEqual(sorted(map(repr, base.dset.catalogs.lithology)),
                         sorted(map(repr, expected.catalogs.lithology)))
        self.assertEqual(sorted(map(repr, base.dset.catalogs.elements)),
                         sorted(map(repr, expected.catalogs.elements)))
        self.assertEqual((base.dset.crs, base.dset.vertical), (H25830, V5782))
        self.assertEqual((base.transforms, base.notes), ((), ()))
        self.assertEqual(base.columns["dh_collar"]["name"].tolist(), list(HOLES))
        surveys = base.columns["dh_survey"]
        sources = dict(zip(SURVEYED, [_uid(2)] * 4, strict=True))
        sources.update({"S-12": _uid(1), "C-01": _uid(1)})
        for hole, uid in sources.items():
            rows = _hole_rows(base, "dh_survey", hole)
            with self.subTest(sondeo=hole):
                self.assertTrue(rows.size)
                self.assertEqual(set(surveys["input_uid"][rows].tolist()), {uid})
        self.assertEqual(surveys["source"][_hole_rows(base, "dh_survey", "S-12")].tolist(),
                         ["collar"])
        self.assertEqual(surveys["source"][_hole_rows(base, "dh_survey", "C-01")].tolist(),
                         ["declared_vertical"])
        self.assertEqual(set(base.columns["dh_collar"]["input_uid"].tolist()), {_uid(1)})
        self.assertEqual(set(base.columns["dh_lithology"]["input_uid"].tolist()), {_uid(3)})
        self.assertEqual(set(base.columns["dh_assay"]["input_uid"].tolist()), {_uid(4)})
        whole = _build([build.SourceEntry.from_set(_uid(9), _basico_declaration(),
                                                   dh_sets.basico_set())])
        for table in schema.BASE_TABLES:
            with self.subTest(una_sola_entrada=table):
                self.assertEqual(_table(whole, table, ("input_uid",)),
                                 _table(base, table, ("input_uid",)))

    def test_convenios_give_the_basico_base(self) -> None:
        """RF-005-27, RF-005-28, RF-005-29: cada variante de ``csv_convenios`` (fichero a
        fichero) da, columna a columna y bit a bit, la base de ``csv_basico`` salvo lo que se
        guarda como venía; con azimut magnético, cada estación conserva A_m, «magnetic»,
        δ = 0,25° y γ = 1,50° (A = A_m + δ − γ), y las leyes, su texto y su unidad del
        laboratorio."""
        for variant in ("positive_dip", "from_vertical", "magnetic"):
            base = _build(_convenios_entries(variant))
            for table in schema.BASE_TABLES:
                with self.subTest(variante=variant, tabla=table):
                    skip = AS_REPORTED.get(table, ())
                    self.assertEqual(_table(base, table, skip), _table(BASICO_BASE, table, skip))
        surveys = base.columns["dh_survey"]
        converted = np.flatnonzero(surveys["source"] != "declared_vertical")
        self.assertEqual(set(surveys["azimuth_ref"][converted].tolist()), {"magnetic"})
        np.testing.assert_array_equal(surveys["declination_deg"][converted], 0.25)
        np.testing.assert_array_equal(surveys["convergence_deg"][converted], 1.5)
        np.testing.assert_array_equal(
            surveys["azimuth"][converted],
            np.mod(surveys["azimuth_measured"][converted] + 0.25 - 1.5, 360.0))
        s03 = _hole_rows(base, "dh_survey", "S-03")
        self.assertEqual(surveys["azimuth_measured"][s03][0], 0.75)  # 359,5 + 1,25 − 360
        assays = base.columns["dh_assay"]
        self.assertEqual(set(assays["reported_unit"].tolist()), {"ppb", "g/t", "ppm"})
        self.assertIn("<10", assays["reported_value"].tolist())
        self.assertEqual(set(assays["unit"].tolist()), {"g/t", "ppm", "%"})


class PrecedenceTest(unittest.TestCase):
    """RF-005-11: la entrada registrada más tarde que trae filas gana en esas tablas."""

    def _s03_entry(self, number: int) -> object:
        """Una entrada de litología con los tramos de S-03 (escrito «s-03 » en la primera
        fila), todos «ARC»."""
        lithology = dh_sets.basico_tables()["lithology"]
        rows = [[" s-03 " if k == 0 else row[0], row[1], row[2], "ARC"]
                for k, row in enumerate(r for r in lithology.rows if r[0] == "S-03")]
        return _entry(number, "lithology", _lithology_table(rows), _basico_declaration())

    def test_later_entry_replaces_its_holes_and_tables(self) -> None:
        """RF-005-11: una segunda entrada que «sustituye» S-03 en la litología gana en esa
        tabla de S-03 y no en las demás (ni en sus desviaciones ni en la litología de los
        demás sondeos); sin ella, la base anterior bit a bit; registrada antes que la de
        litología de ``csv_basico``, no gana."""
        replaced = self._s03_entry(7)
        base = _build([*BASICO, replaced])
        before = _table(BASICO_BASE, "dh_lithology")
        after = _table(base, "dh_lithology")
        s03_after = _hole_rows(base, "dh_lithology", "S-03")
        s03_before = _hole_rows(BASICO_BASE, "dh_lithology", "S-03")
        self.assertEqual(s03_after.size, s03_before.size)
        lithology = base.columns["dh_lithology"]
        self.assertEqual(set(lithology["input_uid"][s03_after].tolist()), {_uid(7)})
        codes = {code.code: k + 1 for k, code in enumerate(base.dset.catalogs.lithology)}
        self.assertEqual(set(lithology["lithology_id"][s03_after].tolist()), {codes["ARC"]})
        others_after = np.setdiff1d(np.arange(len(lithology["hole_id"])), s03_after)
        others_before = np.setdiff1d(np.arange(len(before["hole_id"])), s03_before)
        for column in before:
            with self.subTest(columna=column):
                self.assertEqual(np.array(after[column], dtype=object)[others_after].tolist(),
                                 np.array(before[column], dtype=object)[others_before].tolist())
        for table in schema.BASE_TABLES:
            if table != "dh_lithology":
                with self.subTest(tabla=table):
                    self.assertEqual(_table(base, table), _table(BASICO_BASE, table))
        again = _build(list(BASICO))
        for table in schema.BASE_TABLES:
            with self.subTest(sin_la_segunda=table):
                self.assertEqual(repr(again.rows(table)), repr(BASICO_BASE.rows(table)))
        earlier = _build([*BASICO[:2], self._s03_entry(7), *BASICO[2:]])
        self.assertEqual(_table(earlier, "dh_lithology"), before)

    def test_stations_follow_their_tables(self) -> None:
        """RF-005-11, RF-005-22 (spec §8): unas bocas registradas más tarde con orientación en
        boca de S-01 (que tiene desviaciones medidas) y sin la de S-12: S-01 sigue con sus
        estaciones medidas (la orientación en boca no cuenta si las hay) y S-12 pierde la
        suya (es de la tabla de bocas, que ganó la entrada nueva) y queda vertical declarada
        por «todos verticales» de esa entrada (sin él, sin estaciones); solo cambia la huella
        de S-12."""
        collars = dh_sets.basico_tables()["collar"]
        rows = [list(row) for row in collars.rows if row[0] in ("S-01", "S-12")]
        rows[0][5:7] = ["10,00", "-45,00"]
        rows[1][5:7] = ["", ""]
        table = csv_tables.Table(list(collars.columns), rows, [2, 3])
        base = _build([*BASICO, _entry(11, "collar", table, _basico_declaration())])
        surveys = base.columns["dh_survey"]
        s01 = _hole_rows(base, "dh_survey", "S-01")
        before = _hole_rows(BASICO_BASE, "dh_survey", "S-01")
        self.assertEqual(surveys["source"][s01].tolist(), ["measured"] * before.size)
        self.assertEqual(set(surveys["input_uid"][s01].tolist()), {_uid(2)})
        s12 = _hole_rows(base, "dh_survey", "S-12")
        self.assertEqual(surveys["source"][s12].tolist(), ["declared_vertical"])
        self.assertEqual(surveys["input_uid"][s12].tolist(), [_uid(11)])
        self.assertEqual(build.changed_holes(BASICO_BASE, base), ("S-12",))
        upright = _build([*BASICO, _entry(11, "collar", table,
                                          _basico_declaration(all_vertical=False))])
        self.assertEqual(_hole_rows(upright, "dh_survey", "S-12").size, 0)

    def test_catalog_codes_by_precedence(self) -> None:
        """RF-005-11: un catálogo registrado más tarde gana en los códigos que trae («min»,
        con otro color, sin distinguir mayúsculas) y en ninguno más; los identificadores no
        cambian."""
        catalog = dh_sets.basico_tables()["lithology_catalog"]
        rows = [["min", "Mineralización", "#102030", "3,10", "8"]]
        table = csv_tables.Table(list(catalog.columns), rows, [2])
        base = _build([*BASICO, _entry(8, "lithology_catalog", table, _basico_declaration())])
        codes = base.columns["dh_lithology_code"]
        before = BASICO_BASE.columns["dh_lithology_code"]
        changed = codes["code"].tolist().index("min")
        self.assertEqual(before["code"].tolist()[changed], "MIN")
        self.assertEqual(codes["color"][changed], "#102030")
        others = [k for k in range(len(codes["code"])) if k != changed]
        self.assertEqual(codes["color"][others].tolist(), before["color"][others].tolist())
        self.assertEqual(_table(base, "dh_lithology"), _table(BASICO_BASE, "dh_lithology"))


class IdentifiersTest(unittest.TestCase):
    """RF-008-26: identificadores deterministas y los mismos bytes en otro orden."""

    def test_rows_in_another_order_same_bytes(self) -> None:
        """RF-008-26 (plan §5.6.1): las filas de cada entrada y los catálogos en otro orden
        dan las mismas filas de las once tablas, byte a byte, también con tramos que empatan
        en sondeo y profundidad (los ordena el resto de sus columnas); las entradas no
        cambian."""
        tied = list(BASICO)
        for position, name, changes in ((2, "lithology", {"description": "bis"}),
                                        (3, "assays", {"lab": "LAB-2", "is_primary": False})):
            columns = getattr(tied[position], name)
            count = len(columns)
            twin = columns.take(np.arange(count), **{
                key: np.full(count, value, dtype=getattr(columns, key).dtype)
                for key, value in changes.items()})
            joined = type(columns)(**{item.name: np.concatenate(
                [getattr(columns, item.name), getattr(twin, item.name)])
                for item in dataclasses.fields(columns)})
            tied[position] = dataclasses.replace(tied[position], **{name: joined})
        expected = _build(tied)
        self.assertEqual(len(expected.columns["dh_lithology"]["hole_id"]),
                         2 * len(BASICO_BASE.columns["dh_lithology"]["hole_id"]))
        rng = np.random.default_rng(41)
        shuffled = []
        for entry in tied:
            tables = {}
            for name in model.TABLES:
                columns = getattr(entry, name)
                tables[name] = columns.take(rng.permutation(len(columns)))
            catalogs = model.Catalogs(lithology=tuple(reversed(entry.catalogs.lithology)),
                                      elements=tuple(reversed(entry.catalogs.elements)))
            shuffled.append(dataclasses.replace(entry, catalogs=catalogs, **tables))
        before = _snapshot(shuffled)
        base = _build(shuffled)
        self.assertEqual(_snapshot(shuffled), before)
        for table in schema.BASE_TABLES:
            with self.subTest(tabla=table):
                self.assertEqual(repr(base.rows(table)), repr(expected.rows(table)))

    def test_identifiers_and_rows_fit_the_tables(self) -> None:
        """RF-005-01, RF-008-26: bocas por nombre sin mayúsculas (su ``fid`` es su posición
        desde 1) con el ``uid`` determinista del proyecto; cada fila hija apunta a su boca y
        a su código de catálogo por esa posición; la geometría de una boca es su X, Y, Z en
        el SRS del proyecto; las filas de las once tablas caben en ellas
        (``schema.table_digest``, el GeoPackage en memoria con su DDL)."""
        base = BASICO_BASE
        collars = base.columns["dh_collar"]
        self.assertEqual(collars["uid"].tolist(),
                         [schema.hole_uid(PROJECT_UID, name) for name in HOLES])
        names = collars["name"].tolist()
        for set_name in model.CHILD_TABLES:
            table = SET_TABLES[set_name]
            hole = getattr(base.dset, set_name).hole
            if len(hole):
                with self.subTest(tabla=table):
                    self.assertEqual(base.columns[table]["hole_id"].tolist(),
                                     (hole + 1).tolist())
                    self.assertEqual(
                        [names[k] for k in hole.tolist()],
                        [model.name_key(n).upper() for n in
                         getattr(base.dset, set_name).hole_name.tolist()])
        lithology = base.columns["dh_lithology"]
        catalog = [entry.code for entry in base.dset.catalogs.lithology]
        self.assertEqual([catalog[k - 1] for k in lithology["lithology_id"].tolist()],
                         base.dset.lithology.code.tolist())
        assays = base.columns["dh_assay"]
        elements = [entry.code for entry in base.dset.catalogs.elements]
        self.assertEqual([elements[k - 1] for k in assays["element_id"].tolist()],
                         base.dset.assays.element.tolist())
        self.assertEqual(elements, sorted(elements, key=model.name_key))
        surveys = base.columns["dh_survey"]
        order = np.lexsort((surveys["depth"], surveys["hole_id"]))
        np.testing.assert_array_equal(order, np.arange(len(order)))
        for row, x, y, z in zip(base.rows("dh_collar"), collars["x"], collars["y"],
                                collars["z"], strict=True):
            geometry = wkb.decode_geometry(row[0])
            self.assertEqual((geometry.geometry_type, geometry.srs_id), ("POINT", 25830))
            self.assertEqual(np.asarray(geometry.coords).tolist(), [x, y, z])
        filled = set()
        for table in schema.BASE_TABLES:
            layout = schema.LAYOUTS[table]
            rows = base.rows(table)
            with self.subTest(tabla=table):
                self.assertEqual(list(base.columns[table]), list(layout.column_names))
                self.assertLessEqual({len(row) for row in rows}, {len(layout.insert_columns)})
                schema.table_digest(layout, rows, H25830)
            if rows:
                filled.add(table)
        self.assertEqual(filled, {"dh_collar", "dh_survey", "dh_lithology", "dh_assay",
                                  "dh_lithology_code", "dh_element"})

    def test_survey_sha256_by_declination(self) -> None:
        """RF-005-22: otra declinación en la entrada de desviaciones cambia ``survey_sha256``
        solo de sus sondeos (S-01 a S-04); en la de bocas, solo de S-12 (su orientación en
        boca); C-01 (vertical declarada), nunca. ``changed_holes`` también da los sondeos
        nuevos y los que ya no están."""
        magnetic = _build(_convenios_entries("magnetic"))
        hashes = magnetic.survey_hashes
        self.assertEqual(list(hashes), list(HOLES))
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))
        other = _convenios_declaration("magnetic", declination_deg=0.5)
        surveys = _build(_convenios_entries("magnetic", survey=other))
        self.assertEqual(build.changed_holes(hashes, surveys), SURVEYED)
        collar = _build(_convenios_entries("magnetic", collar=other))
        self.assertEqual(build.changed_holes(magnetic, collar), ("S-12",))
        self.assertEqual(build.changed_holes(magnetic, magnetic), ())
        previous = {**hashes, "X-9": "0" * 64}
        del previous["S-04"]
        self.assertEqual(build.changed_holes(previous, magnetic.survey_hashes),
                         ("S-04", "X-9"))


class NotesTest(unittest.TestCase):
    """Lo que no pasa a la base se dice; nada se supone (RF-005-07)."""

    def test_left_out_and_deduced(self) -> None:
        """DH-E01, DH-E04, DH-E11, DH-W16: un sondeo repetido en su entrada no pasa (ni sus
        tramos), unos tramos sin boca tampoco, ni los de un código que no está en los
        catálogos (S-12 se queda sin litología: la entrada ganó en esa tabla); una boca sin
        profundidad la toma de su tramo más hondo (CALCULADO) y, con «todos verticales», es
        vertical."""
        collars = dh_sets.basico_tables()["collar"]
        blank = ["", "", "RC", "C-2026", "", "", "no"]
        rows = [[" s-90 ", "700001", "4400001", "800", "10", *blank],
                ["S-90", "700002", "4400002", "800", "10", *blank],
                ["S-91", "700003", "4400003", "801", "", *blank]]
        new_collars = csv_tables.Table(list(collars.columns), rows, [2, 3, 4])
        lithology = _lithology_table([["S-90", "0", "2", "ARC"], ["X-1", "0", "1", "ARC"],
                                      ["S-91", "0", "12,5", "ARC"], ["S-12", "0", "160", "ZZZ"]])
        base = _build([*BASICO, _entry(9, "collar", new_collars, _basico_declaration()),
                       _entry(10, "lithology", lithology, _basico_declaration())])
        names = base.columns["dh_collar"]["name"].tolist()
        self.assertEqual(names, [*HOLES, "S-91"])
        notes = {(n.code, n.table, model.name_key(n.hole), n.value, n.rows) for n in base.notes}
        self.assertEqual(notes, {
            (build.NOTE_DUPLICATE, "dh_collar", "s-90", None, 2),
            (build.NOTE_DUPLICATE, "dh_lithology", "s-90", None, 1),
            (build.NOTE_WITHOUT_COLLAR, "dh_lithology", "x-1", None, 1),
            (build.NOTE_UNKNOWN_CODE, "dh_lithology", "s-12", "ZZZ", 1),
        })
        for note in base.notes:
            self.assertTrue(note.message)
        self.assertEqual(_hole_rows(base, "dh_lithology", "S-12").size, 0)
        s91 = names.index("S-91")
        self.assertEqual(base.columns["dh_collar"]["depth"][s91], 12.5)
        self.assertEqual(base.columns["dh_collar"]["depth_kind"][s91], "CALCULADO")
        surveys = base.columns["dh_survey"]
        rows91 = _hole_rows(base, "dh_survey", "S-91")
        self.assertEqual(surveys["source"][rows91].tolist(), ["declared_vertical"])
        self.assertEqual(surveys["input_uid"][rows91].tolist(), [_uid(9)])

    def test_nothing_is_assumed(self) -> None:
        """RF-005-07: unas bocas sin CRS o sin datum declarados no pasan
        (``gis.crs_undeclared``, ``gis.vertical_undeclared``); unas desviaciones sin la
        referencia del azimut, tampoco; nada se supone."""
        collars = BASICO[0]
        for changes, code in (({"crs": None}, "gis.crs_undeclared"),
                              ({"vertical": None}, "gis.vertical_undeclared")):
            entry = dataclasses.replace(collars, declaration=_basico_declaration(**changes))
            with self.subTest(code=code), self.assertRaises(gis_messages.GisError) as caught:
                _build([entry, *BASICO[1:]])
            self.assertEqual(caught.exception.code, code)
        undeclared = dataclasses.replace(BASICO[1], declaration=_basico_declaration(
            azimuth_ref=None))
        with self.assertRaises(ValueError):
            _build([BASICO[0], undeclared, *BASICO[2:]])
        with self.assertRaises(ValueError):
            _build([*BASICO, BASICO[2]])  # una entrada dos veces
        with self.assertRaises(ValueError):
            build.build_base(BASICO, FakeCrsService(), H25830, V5782, project_uid="no")


class NoRowLoopsTest(unittest.TestCase):
    """Sin bucles por fila: lo que se hace por nombre, por código o por entrada no crece con
    las filas."""

    def test_calls_do_not_grow_with_rows(self) -> None:
        """Plan §5.4 y §5.6.1: con los tramos y los análisis repetidos 20 veces, las mismas
        llamadas a ``name_key`` (una por texto distinto), a ``convert_surveys`` (una por
        entrada con estaciones) y al servicio de CRS (una convergencia para todas las
        bocas)."""
        small = _convenios_entries("magnetic")
        big = []
        for entry in small:
            tables = {name: getattr(entry, name).take(np.tile(np.arange(len(getattr(
                entry, name))), 20)) for name in ("lithology", "assays")}
            big.append(dataclasses.replace(entry, **tables))
        counts = []
        for entries in (small, big):
            service = FakeCrsService()
            with mock.patch.object(build, "name_key", wraps=model.name_key) as keys, \
                    mock.patch.object(build, "convert_surveys",
                                      wraps=conventions.convert_surveys) as surveys:
                base = _build(entries, service)
            counts.append((keys.call_count, surveys.call_count,
                           [call[0] for call in service.calls]))
        self.assertEqual(counts[0], counts[1])
        self.assertEqual(counts[0][2], ["grid_convergence"])
        self.assertEqual(counts[0][1], 2)  # la entrada de bocas y la de desviaciones
        self.assertEqual(len(base.columns["dh_assay"]["hole_id"]),
                         20 * len(BASICO_BASE.columns["dh_assay"]["hole_id"]))


if __name__ == "__main__":
    unittest.main()
