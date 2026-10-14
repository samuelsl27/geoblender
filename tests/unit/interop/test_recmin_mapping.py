# SPDX-License-Identifier: GPL-3.0-or-later
"""Bases de RecMin a sondeos (spec 005, T15; HU-005-2; plan 005 §5.4 «RecMin», §5.6.2 y
§5.6.12; ``interop.ports.RawTable``, ``interop.recmin.schema`` e
``interop.recmin.drillholes``), con las tablas crudas en memoria de los guiones de
``tests/data/dh/recmin/`` (las que dará el extractor de la base, T16).

- **RF-005-13** (incorporar sin pérdida bocas, desviaciones, todas las tablas de litología y de
  muestras, catálogos, intersecciones y cortes, con cada campo sin equivalente y el
  identificador de RecMin de cada registro): las dos bases (esquemas 11 y 12) dan exactamente
  los registros que dicen sus guiones: los análisis, de columnas por elemento a un valor por
  tramo y elemento con el nombre y la unidad de su catálogo (el de texto, como texto); los
  colores BGR de Windows como «#RRGGBB»; las tablas adicionales de litología y de muestras,
  reconocidas por su forma (su esquema de logueo ``recmin_<tabla>``, con su catálogo; sus
  muestras, no primarias); ``extra`` con todos los campos sin columna y ``external_id``
  (``recmin:<TABLA>:<id>``) en cada registro; los sondeos de las tablas hijas, por su nombre;
  la profundidad, deducida (CALCULADO) y avisada con DH-W16; la lista de tablas que lee el
  importador (la que hasheará ``io.recmin_mdb@1``), sin depender del orden ni de las
  mayúsculas.
- **RF-005-02** (precisión simple por su decimal más corto): 0,1 y 4,35 de las columnas Single
  se guardan como 0,1 y 4,35, lleguen como ``float32`` o como su ``float`` exacto; los Double,
  idénticos.
- **RF-005-15** (versión de esquema distinta de 11 y 12): no se lee sin confirmarla; con la
  confirmación, se lee lo reconocible y el informe lo avisa.
- **RF-005-07** (nada se supone): sin CRS, datum vertical, referencia del azimut (con
  desviaciones) o la unidad de un elemento que RecMin no da en una de ley, no se lee.
- **RF-005-09**, **RF-005-10**, **RF-005-12**: negativos tal cual o «<x» si se declara; lo que no
  se puede leer, rechazado con su tabla, fila, campo, valor y motivo (sondeo y tramo); los
  recuentos por tabla, los avisos y los códigos nuevos en el informe.

Las tablas crudas nunca cambian al leerlas.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import unittest
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

import numpy as np

from tests.support import dh_sets, recmin
from tests.support.package import import_geoblender

ports = import_geoblender("interop.ports")
schema = import_geoblender("interop.recmin.schema")
reader = import_geoblender("interop.recmin.drillholes")
base = import_geoblender("interop.base")
model = import_geoblender("drillholes.model")
validate = import_geoblender("drillholes.validate")
errors = import_geoblender("core.errors")
params = import_geoblender("core.params")

Kind = schema.TableKind
V11, V12 = "recmin_v11.sql", "recmin_v12.sql"
CALCULADO = params.ParamKind.CALCULADO
ADOPTADO = params.ParamKind.ADOPTADO
MEDIDO = params.ParamKind.MEDIDO

# Lo que el guion no puede decir: la profundidad deducida de cada sondeo (la mayor de sus
# estaciones y de los hasta de sus tramos, muestras e intersecciones).
DEPTHS = {
    V12: {"R-01": 120.0, "R-02": 80.5, "R-03": 92.5, "R-04": 150.0},
    V11: {"SV-1": 60.3, "SV-2": 100.2, "SV-3": 80.0},
}
# Las tablas adicionales de cada guion: (litología, muestras).
ADDITIONAL = {V12: ("alteracion", "duplicados"), V11: ("LITOLOGIA2", "MUESTRAS2")}
# La lista de tablas que lee el importador, en su orden.
READ = {
    V12: ("actualizacion", "sondeos", "angulos", "litologia", "alteracion", "muestras",
          "duplicados", "intersecciones", "cortes", "idlitologia", "elementos", "formulas",
          "sectores", "grupos", "zonas", "giros"),
    V11: ("ACTUALIZACION", "SONDEOS", "ANGULOS", "LITOLOGIA", "LITOLOGIA2", "MUESTRAS",
          "MUESTRAS2", "INTERSECCIONES", "CORTES", "IDLITOLOGIA", "ELEMENTOS", "SECTORES",
          "ZONAS", "GIROS"),
}


def _sql(script: str) -> dict[str, Any]:
    """Las tablas del guion por su nombre en mayúsculas."""
    return {name.upper(): table
            for name, table in recmin.parse_sql(recmin.RECMIN_DIR / script).items()}


def _raw(script: str, **options: Any) -> dict[str, Any]:
    return recmin.raw_tables(recmin.RECMIN_DIR / script, **options)


def _declaration(**changes: Any) -> Any:
    values: dict[str, Any] = dict(
        crs=dh_sets.H25830, vertical=dh_sets.V5782, azimuth_ref=model.AzimuthRef.GRID,
        declination_deg=None, inclination_convention=model.InclinationConvention.NEGATIVE_DOWN,
        units={}, value_rules=model.ValueRules(decimal_mark="."),
    )
    values.update(changes)
    return model.SourceDeclaration(**values)


def _read(tables: Mapping[str, Any] | str, **options: Any) -> tuple[Any, Any]:
    if isinstance(tables, str):
        tables = _raw(tables)
    decl = options.pop("decl", None) or _declaration()
    return reader.read_drillholes(tables, decl, **options)


def _replace(tables: Mapping[str, Any], name: str, *, rows: Any = None, add: Any = (),
             change: Callable[[dict[str, Any]], None] | None = None,
             columns: tuple[tuple[str, int], ...] = ()) -> dict[str, Any]:
    """``tables`` con la tabla ``name`` cambiada: otras filas (``rows``, como diccionarios
    columna → valor), filas añadidas al final (``add``), ``change`` aplicado a cada fila, o
    columnas nuevas al final."""
    found = dict(tables)
    table = found[name]
    names = [c.name for c in table.columns]
    current = [dict(zip(names, row, strict=True)) for row in table.rows]
    new_columns = table.columns + tuple(ports.RawColumn(c, kind) for c, kind in columns)
    names += [c for c, _ in columns]
    if rows is not None:
        current = list(rows)
    current += list(add)
    if change is not None:
        for row in current:
            change(row)
    found[name] = ports.RawTable(
        table.name, new_columns, tuple(tuple(row.get(c) for c in names) for row in current))
    return found


def _num(value: Any) -> float | None:
    """El float64 del decimal del guion: el de un Double y el decimal más corto de un Single."""
    return None if value is None else float(value)


def _short(value: Any) -> str:
    return np.format_float_positional(float(value), unique=True, trim="-")


def _bgr(color: int) -> str:
    return f"#{color & 0xFF:02X}{(color >> 8) & 0xFF:02X}{(color >> 16) & 0xFF:02X}"


def _day(value: dt.datetime | None) -> dt.date | None:
    return None if value is None else value.date()


def _element_number(column: str) -> int | None:
    words = column.split()
    if len(words) == 2 and words[0].upper() == "ELEMENTO" and words[1].isdigit():
        return int(words[1])
    return None


def _expected(script: str) -> dict[str, Any]:
    """Los registros que debe dar la base del guion ``script``, escritos desde sus filas."""
    t = _sql(script)
    litho_extra, samples_extra = ADDITIONAL[script]
    names = {r["IDSONDEO"]: r["SONDEO"] for r in t["SONDEOS"].rows}
    sectors = {r["IDSECTOR"]: r["SECTOR"] for r in t["SECTORES"].rows}
    groups = {r["IDGRUPO"]: r["GRUPO"] for r in t["GRUPOS"].rows} if "GRUPOS" in t else {}
    zones = {r["IDZONA"]: r["ZONA"] for r in t["ZONAS"].rows}
    codes = {r["IDLITO"]: r["NOMBRE CORTO"] for r in t["IDLITOLOGIA"].rows}
    elements = {r["ELEMENTO"]: r for r in t["ELEMENTOS"].rows}

    collars = [
        model.Collar(
            r["SONDEO"], _num(r["ESTE"]), _num(r["NORTE"]), _num(r["ELEVACION"]),
            DEPTHS[script][r["SONDEO"]], depth_kind=CALCULADO, planned=r["PLAN"],
            grade_control=r["CONTROL"], category=r["CAT"], priority=r["PRIORIDAD"],
            sector=sectors[r["IDSECTOR"]], group=groups.get(r.get("IDGRUPO")),
            start_date=_day(r["FECHA INI"]), end_date=_day(r["FECHA FIN"]),
            external_id=f"recmin:SONDEOS:{r['IDSONDEO']}",
            extra={c: _num(r[c]) for c in ("CL NORTE", "CL ESTE", "CL Z")})
        for r in t["SONDEOS"].rows
    ]
    surveys = [
        model.SurveyStation(
            names[r["IDSONDEO"]], _num(r["DISTANCIA"]),
            0.0 if r["DIRECCION"] == 360 else _num(r["DIRECCION"]), _num(r["INCLINACION"]),
            external_id=f"recmin:ANGULOS:{r['ID']}")
        for r in t["ANGULOS"].rows
    ]
    lithology = [
        model.LithologyInterval(
            names[r["IDSONDEO"]], _num(r["DESDE"]), _num(r["HASTA"]), codes[r["IDLITO"]],
            log_set=log_set, external_id=f"recmin:{table}:{r['ID']}")
        for table, log_set in (("LITOLOGIA", "lithology"),
                               (litho_extra.upper(), f"recmin_{litho_extra.lower()}"))
        for r in t[table].rows
    ]
    assays = []
    for table, primary in (("MUESTRAS", True), (samples_extra.upper(), False)):
        columns = [(c.name, _element_number(c.name)) for c in t[table].columns]
        for r in t[table].rows:
            for column, number in columns:
                if number is None or r[column] is None:
                    continue
                e = elements[number]
                text = e["UNIDAD"] == "txt"
                assays.append(model.AssayValue(
                    names[r["IDSONDEO"]], _num(r["DESDE"]), _num(r["HASTA"]), e["NOMBRE"],
                    None if text else _num(r[column]), "text" if text else e["UNIDAD"],
                    reported_value=r[column] if text else _short(r[column]),
                    reported_unit=e["UNIDAD"], sample_id=f"recmin:{table}:{r['ID']}",
                    is_primary=primary, external_id=f"recmin:{table}:{r['ID']}"))
    zone_intervals = [
        model.ZoneInterval(names[r["IDSONDEO"]], _num(r["DESDE"]), _num(r["HASTA"]),
                           zones[r["IDZONA"]], angle_deg=_num(r["ANGULO"]),
                           external_id=f"recmin:INTERSECCIONES:{r['ID']}")
        for r in t["INTERSECCIONES"].rows
    ]
    structures = [
        model.StructureMeasure(
            names[r["IDSONDEO"]], _num(r["DISTANCIA"]), "zone_plane",
            orientation_source="recmin_cortes", zone=zones[r["IDZONA"]],
            external_id=f"recmin:CORTES:{r['ID']}",
            extra={"AZIMUT": _num(r["AZIMUT"]), "INCLINACION": _num(r["INCLINACION"])})
        for r in t["CORTES"].rows
    ]
    lithology_codes = [
        model.LithologyCode(
            r["NOMBRE CORTO"], log_set=log_set, description=r["DESCRIPCION"],
            color=_bgr(r["COLOR"]), pattern=str(r["ESTILO"]), density=_num(r["DENSIDAD"]),
            density_kind=ADOPTADO, sort_order=r["ORDEN"], show_in_legend=r["VER"],
            external_id=f"recmin:IDLITOLOGIA:{r['IDLITO']}",
            extra={c: r[c] for c in ("COLORPRINT", "ESTILOPRINT", "BMP", "BMPprint")})
        for log_set in ("lithology", f"recmin_{litho_extra.lower()}")
        for r in t["IDLITOLOGIA"].rows
    ]
    element_codes = [
        model.Element(
            r["NOMBRE"], "text" if r["UNIDAD"] == "txt" else r["UNIDAD"],
            decimals=r["DECIMALES"], sort_order=r["ORDEN"], show_in_tables=r["TABLA"],
            use_in_calc=r["CALCULO"], color_legend=r["COLORES"],
            external_id=f"recmin:ELEMENTOS:{r['ELEMENTO']}", extra={"CONTADOR": r["CONTADOR"]})
        for r in t["ELEMENTOS"].rows
    ]
    if "FORMULAS" in t:  # cueq = 1·cu + 0,0008·au, en la unidad de su primer término
        element_codes.append(model.Element(
            "cueq", "%", expression="1*cu + 0.0008*au", use_in_calc=False,
            external_id="recmin:FORMULAS:cueq",
            extra={"FORMULAS": [{"CAMPO": "cu", "FACTOR": 1.0},
                                {"CAMPO": "au", "FACTOR": 0.0008}]}))
    entries = {
        name: [model.CatalogEntry(r[code], description=r["DESCRIPCION"],
                                  external_id=f"recmin:{name}:{r[ident]}")
               for r in t[name].rows]
        for name, code, ident in (("SECTORES", "SECTOR", "IDSECTOR"),
                                  ("GRUPOS", "GRUPO", "IDGRUPO")) if name in t
    }
    zone_codes = [model.CatalogEntry(r["ZONA"], description=r["DESCRIPCION"],
                                     density=_num(r["DENSIDAD"]), density_kind=ADOPTADO,
                                     external_id=f"recmin:ZONAS:{r['IDZONA']}")
                  for r in t["ZONAS"].rows]
    catalogs = model.Catalogs(lithology=tuple(lithology_codes), elements=tuple(element_codes),
                              sectors=tuple(entries["SECTORES"]),
                              groups=tuple(entries.get("GRUPOS", ())), zones=tuple(zone_codes))
    return {"collars": tuple(collars), "surveys": tuple(surveys),
            "lithology": tuple(lithology), "assays": tuple(assays),
            "zones": tuple(zone_intervals), "structures": tuple(structures),
            "catalogs": catalogs}


def _issues(report: Any, code: str) -> list[Any]:
    return [issue for issue in report.issues if issue.code == code]


class _Untouched:
    """Las tablas crudas no cambian al leerlas (son las de la fuente)."""

    def assertReadsUntouched(self, tables: Mapping[str, Any], **options: Any) -> tuple:
        before = {name: (t.name, t.columns, t.rows) for name, t in tables.items()}
        found = _read(tables, **options)
        after = {name: (t.name, t.columns, t.rows) for name, t in tables.items()}
        self.assertEqual(after, before)
        return found


class RawTableTest(unittest.TestCase):
    """El contrato de las tablas crudas del extractor (``interop.ports``)."""

    def test_raw_table(self) -> None:
        """RF-005-13: columnas con su tipo OLE DB, sin repetir (sin distinguir mayúsculas), y
        filas de su mismo ancho, inmutables; la posición de una columna sin distinguir
        mayúsculas."""
        columns = (ports.RawColumn("ID", ports.DBTYPE_I4), ports.RawColumn("Desde", 4))
        table = ports.RawTable("t", columns, [[1, np.float32(0.5)], (2, None)])
        self.assertEqual(table.rows, ((1, np.float32(0.5)), (2, None)))
        self.assertEqual(table.position("DESDE"), 1)
        self.assertIsNone(table.position("HASTA"))
        self.assertEqual(table.values("desde"), [np.float32(0.5), None])
        with self.assertRaises(ValueError):
            ports.RawTable("t", columns, ((1,),))
        with self.assertRaises(ValueError):
            ports.RawTable("t", columns + (ports.RawColumn("id", 3),), ())
        with self.assertRaises(ValueError):
            ports.RawTable(" ", columns, ())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            table.rows = ()  # type: ignore[misc]


class SchemaTest(unittest.TestCase):
    """Qué tablas lee el importador (plan §5.6.2, la lista que hashea ``io.recmin_mdb@1``)."""

    def _columns(self, tables: Mapping[str, Any]) -> dict[str, list[str]]:
        return {t.name: [c.name for c in t.columns] for t in tables.values()}

    def test_tables_read_by_name_and_shape(self) -> None:
        """RF-005-13: las conocidas de los esquemas 11 y 12 por su nombre (sin distinguir
        mayúsculas) y las adicionales de litología y de muestras por su forma, en un orden
        fijo; las de RecMin que no son de sondeos, no; ni las desconocidas."""
        for script in (V12, V11):
            with self.subTest(script=script):
                found = schema.layout(self._columns(_raw(script)))
                self.assertEqual(found.names, READ[script])
                self.assertEqual(found.not_imported, ("secciones",) if script == V12 else ())
                self.assertEqual(found.unknown, ())
                litho, samples = ADDITIONAL[script]
                additional = [(u.name, u.kind, u.log_set, u.primary) for u in found.tables
                              if not u.primary]
                self.assertEqual(additional, [
                    (litho, Kind.LITHOLOGY, f"recmin_{litho.lower()}", False),
                    (samples, Kind.SAMPLES, None, False)])
                main = found.table(Kind.LITHOLOGY)
                self.assertEqual((main.name.upper(), main.log_set), ("LITOLOGIA", "lithology"))
        columns = self._columns(_raw(V12))
        shuffled = {name.upper(): [c.lower() for c in reversed(columns[name])]
                    for name in reversed(list(columns))}
        self.assertEqual(schema.layout(shuffled).names, tuple(n.upper() for n in READ[V12]))
        more = dict(columns, **{
            "Litología estructural": ["Id", "IdSondeo", "Desde", "Hasta", "IdLito"],
            "leyes_2": ["ID", "IDSONDEO", "DESDE", "HASTA", "ELEMENTO 1", "Elemento 12"],
            "NOTAS": ["ID", "TEXTO"],
            "rarezas": ["IDSONDEO", "DESDE", "HASTA"],
        })
        found = schema.layout(more)
        self.assertEqual(found.table(Kind.LITHOLOGY).name, "litologia")
        self.assertEqual([u.log_set for u in found.of_kind(Kind.LITHOLOGY)],
                         ["lithology", "recmin_alteracion", "recmin_litología estructural"])
        self.assertEqual([u.name for u in found.of_kind(Kind.SAMPLES)],
                         ["muestras", "duplicados", "leyes_2"])
        self.assertEqual(found.not_imported, ("NOTAS", "secciones"))
        self.assertEqual(found.unknown, ("rarezas",))
        self.assertEqual(schema.element_number("Elemento 12"), 12)
        self.assertIsNone(schema.element_number("ELEMENTOS"))
        roles = [kind for kinds in reader.OUTPUT_ROLES.values() for kind in kinds]
        self.assertEqual(sorted(roles), sorted(set(Kind) - {Kind.VERSION, Kind.ROTATIONS}))
        self.assertEqual(set(reader.OUTPUT_ROLES), {"collar", "survey", "lithology", "assay",
                                                    "zone_interval", "structure", "catalog"})

    def test_known_table_without_its_columns(self) -> None:
        """RF-005-13: una tabla conocida sin sus columnas, o la base sin SONDEOS, no se lee y
        se dice cuál y qué le falta."""
        columns = self._columns(_raw(V12))
        columns["angulos"] = ["ID", "IDSONDEO", "DISTANCIA", "INCLINACION"]
        with self.assertRaises(schema.RecminSchemaError) as caught:
            schema.layout(columns)
        self.assertEqual(caught.exception.code, "dh.recmin_columns_missing")
        self.assertEqual(caught.exception.obj, "angulos")
        self.assertIn("DIRECCION", str(caught.exception))
        twice = dict(self._columns(_raw(V12)), SONDEOS=["IDSONDEO"])
        with self.assertRaises(ValueError):
            schema.layout(twice)
        tables = _raw(V12)
        del tables["sondeos"]
        with self.assertRaises(schema.RecminSchemaError) as caught:
            _read(tables)
        self.assertEqual(caught.exception.code, "dh.recmin_table_missing")


class MappingTest(_Untouched, unittest.TestCase):
    """De las tablas de RecMin a una tabla por papel (plan §5.4 y §5.6.12)."""

    def test_both_schemas_give_the_script_records(self) -> None:
        """RF-005-13, RF-005-02: cada base da exactamente los registros de su guion: bocas,
        desviaciones (DIRECCION 360 → 0), litología (las tablas adicionales, con su esquema de
        logueo), análisis de ancho a largo con el nombre y la unidad de su catálogo (el de
        texto, como texto), intersecciones, cortes (literales, ángulos en ``extra``) y los
        catálogos (BGR → «#RRGGBB»), con su ``external_id`` y su ``extra``; los sondeos de las
        tablas hijas, enlazados por su nombre."""
        for script in (V12, V11):
            with self.subTest(script=script):
                dset, report = self.assertReadsUntouched(_raw(script))
                expected = _expected(script)
                for name in model.TABLES:
                    self.assertEqual(getattr(dset, name).records(), expected[name], name)
                self.assertEqual(dset.catalogs, expected["catalogs"])
                names = dset.collars.name.tolist()
                for name in model.CHILD_TABLES:
                    columns = getattr(dset, name)
                    self.assertEqual([names[k] for k in columns.hole.tolist()],
                                     columns.hole_name.tolist(), name)
                self.assertEqual((dset.crs, dset.vertical), (dh_sets.H25830, dh_sets.V5782))
                self.assertEqual(report.rejected, ())

    def test_single_precision_by_shortest_decimal(self) -> None:
        """RF-005-02: un Single se guarda por su decimal más corto (0,1 y no
        0,10000000149011612; 4,35 y no 4,349999904632568), llegue como ``float32`` o como su
        ``float`` exacto; un Double, idéntico."""
        as_single, _ = _read(V11)
        as_float, _ = _read(_raw(V11, singles_as_float=True))
        for name in model.TABLES:
            self.assertEqual(getattr(as_float, name).records(),
                             getattr(as_single, name).records(), name)
        self.assertEqual(as_float.catalogs, as_single.catalogs)
        au = as_single.assays.element == "Au"
        self.assertEqual(as_single.assays.value[au][:2].tolist(), [0.1, 4.35])
        self.assertNotEqual(float(np.float32(0.1)), 0.1)
        self.assertNotEqual(float(np.float32(4.35)), 4.35)
        self.assertEqual(as_single.surveys.depth.tolist()[:2], [0.0, 60.3])
        self.assertEqual(as_single.collars.records()[2].extra["CL Z"], 4.35)
        litho = {c.code: c.density for c in as_single.catalogs.lithology}
        self.assertEqual((litho["TV"], litho["ESQ"]), (1.6, 2.75))
        v12, _ = _read(V12)
        self.assertEqual(v12.collars.z.tolist(), [802.525, 809.943, 825.989, 809.933])

    def test_colors_bgr(self) -> None:
        """RF-005-13: COLOR de Windows (BGR) → «#RRGGBB»; sin color, el gris por defecto; uno
        que no es un color, el gris y su valor en ``extra``."""
        dset, _ = _read(V12)
        colors = {c.code: c.color for c in dset.catalogs.lithology if c.log_set == "lithology"}
        self.assertEqual(colors, {"SUE": "#CC6633", "PIZ": "#808080", "CUA": "#E0E0E0",
                                  "MIN": "#FF8000", "POR": "#0000FF", "SIL": "#FFFF00",
                                  "ARG": "#99FF66"})

        def odd(row: dict[str, Any]) -> None:
            row["COLOR"] = {1: None, 2: -2147483643}.get(row["IDLITO"], row["COLOR"])

        dset, _ = _read(_replace(_raw(V12), "idlitologia", change=odd))
        found = {c.code: (c.color, c.extra.get("COLOR")) for c in dset.catalogs.lithology
                 if c.log_set == "lithology"}
        self.assertEqual(found["SUE"], (model.DEFAULT_COLOR, None))
        self.assertEqual(found["PIZ"], (model.DEFAULT_COLOR, -2147483643))
        self.assertEqual(found["MIN"], ("#FF8000", None))

    def test_extra_and_external_id_complete(self) -> None:
        """RF-005-13: cada registro de cada tabla leída lleva su ``external_id`` y, en
        ``extra``, todas las columnas de su tabla que no tienen campo."""
        for script in (V12, V11):
            raw = _raw(script)
            dset, _ = _read(raw)
            records = [*dset.collars.records(), *dset.surveys.records(),
                       *dset.lithology.records(), *dset.assays.records(),
                       *dset.zones.records(), *dset.structures.records(),
                       *dset.catalogs.lithology, *dset.catalogs.elements,
                       *dset.catalogs.sectors, *dset.catalogs.groups, *dset.catalogs.zones]
            layout = schema.layout({t.name: [c.name for c in t.columns] for t in raw.values()})
            for use in layout.tables:
                if use.kind in (Kind.VERSION, Kind.ROTATIONS, Kind.FORMULAS):
                    continue
                with self.subTest(script=script, table=use.name):
                    prefix = f"recmin:{use.name.upper()}:"
                    found = [r for r in records if (r.external_id or "").startswith(prefix)]
                    self.assertTrue(found)
                    columns = {c.name for c in raw[use.name].columns
                               if c.name.upper() not in schema.COLUMNS[use.kind]
                               and schema.element_number(c.name) is None}
                    for record in found:
                        self.assertEqual(set(record.extra), columns)
            self.assertTrue(all(r.external_id for r in records))

    def test_additional_tables_and_samples(self) -> None:
        """RF-005-13, RF-005-09: las muestras de una tabla adicional no son primarias (no
        chocan con las de MUESTRAS: sin DH-E10 ni DH-E12); el elemento de texto, con
        ``value`` vacío y su texto; un negativo, tal cual (DH-W08) o «<x» si se declara."""
        dset, _ = _read(V12)
        report = validate.validate(dset, dh_sets.params())
        self.assertEqual([i.code for i in report.issues if i.level == "error"], [])
        self.assertEqual([(i.hole_name, i.value) for i in _issues(report, "DH-W08")],
                         [("R-01", -5.0)])
        oxid = dset.assays.element == "oxid"
        self.assertTrue(np.isnan(dset.assays.value[oxid]).all())
        self.assertEqual(dset.assays.reported_value[oxid].tolist()[:2], ["sulfuro", "sulfuro"])
        rules = model.ValueRules(decimal_mark=".", negative_is_below_dl=True)
        below, _ = _read(V12, decl=_declaration(value_rules=rules))
        k = below.assays.reported_value.tolist().index("-5")
        flags = model.AssayColumns.code_values("detection_flag")
        self.assertEqual((below.assays.value[k], flags[below.assays.detection_flag[k]]),
                         (5.0, model.DetectionFlag.BELOW_DL))

    def test_depth_deduced_with_dh_w16(self) -> None:
        """RF-005-13 (DH-W16): RecMin no guarda la profundidad total; la deducida (la mayor
        de estaciones y tramos) es CALCULADO y la validación la avisa en cada sondeo."""
        for script in (V12, V11):
            with self.subTest(script=script):
                dset, report = _read(script)
                kinds = model.CollarColumns.code_values("depth_kind")
                self.assertEqual({kinds[k] for k in dset.collars.depth_kind.tolist()},
                                 {CALCULADO})
                issues = _issues(validate.validate(dset, dh_sets.params()), "DH-W16")
                self.assertEqual({i.hole_name: dict(i.message_args)["depth"] for i in issues},
                                 DEPTHS[script])
                self.assertTrue(any("DH-W16" in w for w in report.warnings))


class SchemaVersionTest(_Untouched, unittest.TestCase):
    """RF-005-15: la versión de esquema (ACTUALIZACION.ULTIMA)."""

    def test_unknown_version_needs_confirmation(self) -> None:
        """RF-005-15: 11 y 12 se leen sin aviso; otra versión (13) o ninguna no se lee sin
        confirmarla (``dh.recmin_schema_unknown``); confirmada, se lee lo reconocible y el
        informe lo avisa."""
        for script, version in ((V11, 11), (V12, 12)):
            raw = _raw(script)
            self.assertEqual(schema.schema_version(raw), version)
            self.assertIsNone(schema.version_warning(version))
        self.assertEqual(schema.KNOWN_SCHEMA_VERSIONS, (11, 12))
        self.assertIs(reader.KNOWN_SCHEMA_VERSIONS, schema.KNOWN_SCHEMA_VERSIONS)
        v13 = _replace(_raw(V12), "actualizacion", rows=[{"ULTIMA": 13}])
        none = _replace(_raw(V12), "actualizacion", rows=[{"ULTIMA": None}])
        missing = dict(_raw(V12))
        del missing["actualizacion"]
        for tables, version in ((v13, 13), (none, None), (missing, None)):
            with self.subTest(version=version, tables=len(tables)):
                self.assertEqual(schema.schema_version(tables), version)
                warning = schema.version_warning(version)
                self.assertIn("11 y 12", warning)
                with self.assertRaises(schema.RecminSchemaError) as caught:
                    _read(tables)
                self.assertEqual((caught.exception.code, caught.exception.value),
                                 ("dh.recmin_schema_unknown", version))
                dset, report = self.assertReadsUntouched(tables, accept_schema=True)
                self.assertIn(warning, report.warnings)
                self.assertEqual(len(dset.collars), 4)
        self.assertIn("13", schema.version_warning(13))


class DeclarationsTest(unittest.TestCase):
    """RF-005-07: lo que hay que declarar para leer una base de RecMin."""

    def test_missing_declarations(self) -> None:
        """RF-005-07: sin CRS, datum vertical o referencia del azimut (con desviaciones), no
        se lee y se nombra todo lo que falta; sin desviaciones, el azimut no hace falta; la
        inclinación es la de RecMin (negativa hacia abajo) y no se declara otra."""
        bare = _declaration(crs=None, vertical=None, azimuth_ref=None)
        with self.assertRaises(base.DeclarationError) as caught:
            _read(V12, decl=bare)
        self.assertEqual(caught.exception.missing,
                         [base.MISSING_CRS, base.MISSING_VERTICAL, base.MISSING_AZIMUTH])
        magnetic = _declaration(azimuth_ref=model.AzimuthRef.MAGNETIC)
        with self.assertRaises(base.DeclarationError) as caught:
            _read(V12, decl=magnetic)
        self.assertEqual(caught.exception.missing, [base.MISSING_DECLINATION])
        no_surveys = _replace(_raw(V12), "angulos", rows=[])
        self.assertEqual(reader.needs(no_surveys), base.Needs(crs=True, vertical=True))
        dset, _ = _read(no_surveys, decl=_declaration(azimuth_ref=None))
        self.assertEqual(len(dset.surveys), 0)
        self.assertEqual(reader.needs(_raw(V12)),
                         base.Needs(crs=True, vertical=True, azimuth=True))
        self.assertIs(reader.INCLINATION_CONVENTION, model.InclinationConvention.NEGATIVE_DOWN)
        _read(V12, decl=_declaration(inclination_convention=None))
        for wrong in (dict(inclination_convention="positive_down"), dict(all_vertical=True)):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                _read(V12, decl=_declaration(**wrong))

    def test_unit_that_recmin_does_not_give(self) -> None:
        """RF-005-07: un elemento cuya UNIDAD no es de ley (ni «txt») necesita su unidad
        declarada; declarada, es la de su catálogo y sus análisis, con la de RecMin como la
        unidad original."""
        def ounces(row: dict[str, Any]) -> None:
            if row["NOMBRE"] == "au":
                row["UNIDAD"] = "oz/t"

        tables = _replace(_raw(V12), "elementos", change=ounces)
        self.assertEqual(reader.needs(tables).elements, ("au",))
        with self.assertRaises(base.DeclarationError) as caught:
            _read(tables)
        self.assertEqual(caught.exception.missing, [base.missing_unit("au")])
        with self.assertRaises(base.DeclarationError) as caught:
            _read(tables, decl=_declaration(units={"AU": "oz/t"}))
        self.assertEqual(caught.exception.missing, [base.missing_unit("au", "oz/t")])
        dset, _ = _read(tables, decl=_declaration(units={"AU": "PPB"}))
        au = dset.assays.element == "au"
        self.assertEqual(set(dset.assays.unit[au].tolist()), {"ppb"})
        self.assertEqual(set(dset.assays.reported_unit[au].tolist()), {"oz/t"})
        self.assertEqual([e.unit for e in dset.catalogs.elements if e.code == "au"], ["ppb"])
        self.assertEqual(reader.element_unit("TXT"), reader.TEXT_UNIT)
        self.assertEqual(reader.element_unit(" G/t "), "g/t")
        self.assertIsNone(reader.element_unit("oz/t"))


class RejectionsTest(unittest.TestCase):
    """RF-005-09, RF-005-12: lo que no se puede leer, con su motivo; lo demás entra."""

    def test_rejected_and_kept(self) -> None:
        """RF-005-09, RF-005-12: un código de litología o una zona que no están en su
        catálogo, una fila sin sondeo, un valor que no es un número o de una columna sin
        elemento en ELEMENTOS, y un código repetido en un catálogo se rechazan con su tabla,
        su fila, su campo, su valor y un motivo con el sondeo y el tramo; un sondeo que no
        está en SONDEOS se conserva con su identificador (DH-E04 lo marca); un sector que no
        está, sin sector, con su identificador en ``extra`` y un aviso."""
        tables = _raw(V12)

        def litho(row: dict[str, Any]) -> None:
            if row["ID"] == 3:
                row["IDLITO"] = 99

        def angles(row: dict[str, Any]) -> None:
            row["IDSONDEO"] = {2: None, 3: 999}.get(row["ID"], row["IDSONDEO"])

        def samples(row: dict[str, Any]) -> None:
            row["ELEMENTO 4"] = np.float32(1.5) if row["ID"] == 1001 else None

        def duplicates(row: dict[str, Any]) -> None:
            row["ELEMENTO 1"] = {2001: "<5", 2002: "abc"}[row["ID"]]

        def sectors(row: dict[str, Any]) -> None:
            if row["IDSONDEO"] in (102, 110):
                row["IDSECTOR"] = 9

        tables = _replace(tables, "litologia", change=litho)
        tables = _replace(tables, "angulos", change=angles)
        tables = _replace(tables, "muestras", change=samples, columns=(("ELEMENTO 4", 4),))
        tables = _replace(tables, "duplicados", change=duplicates)
        tables = _replace(tables, "sondeos", change=sectors)
        tables = _replace(tables, "idlitologia", add=[{"IDLITO": 8, "NOMBRE CORTO": "sue"}])
        dset, report = _read(tables)
        self.assertEqual([tuple(r[:4]) for r in report.rejected], [
            ("angulos", 2, "IDSONDEO", None),
            ("litologia", 3, "IDLITO", "99"),
            ("muestras", 1, "ELEMENTO 4", "1.5"),
            ("duplicados", 2, "ELEMENTO 1", "abc"),
            ("idlitologia", 8, "NOMBRE CORTO", "sue"),
        ])
        reasons = [r.reason for r in report.rejected]
        self.assertIn("IDSONDEO", reasons[0])
        self.assertTrue(reasons[1].startswith("sondeo «R-01», de 58,5 a 62,25 m: "))
        self.assertIn("idlitologia", reasons[1])
        self.assertIn("ELEMENTO 4", reasons[2])
        self.assertTrue(reasons[3].startswith("sondeo «R-03», de 70,2 a 72,2 m: "))
        self.assertTrue(reasons[4].startswith("código «sue»: "))
        self.assertEqual(report.per_table["litologia"], base.TableCounts(9, 8, 1))
        self.assertEqual(report.per_table["muestras"], base.TableCounts(7, 19, 1))
        self.assertEqual(report.per_table["duplicados"], base.TableCounts(2, 5, 1))
        self.assertEqual(report.per_table["angulos"], base.TableCounts(11, 10, 1))
        below = dset.assays.reported_value.tolist().index("<5")
        flags = model.AssayColumns.code_values("detection_flag")
        self.assertEqual((dset.assays.value[below], flags[dset.assays.detection_flag[below]]),
                         (5.0, model.DetectionFlag.BELOW_DL))
        orphan = dset.surveys.hole_name.tolist().index("recmin:SONDEOS:999")
        self.assertEqual(dset.surveys.hole[orphan], -1)
        issues = _issues(validate.validate(dset, dh_sets.params()), "DH-E04")
        self.assertEqual([i.hole_name for i in issues], ["recmin:SONDEOS:999"])
        self.assertEqual(dset.collars.sector.tolist(), ["Norte", None, "Sur", None])
        self.assertEqual([c.extra.get("IDSECTOR") for c in dset.collars.records()],
                         [None, 9, None, 9])
        self.assertTrue(any("IDSECTOR 9" in w and "2 " in w for w in report.warnings))

    def test_repeated_names_and_new_codes(self) -> None:
        """RF-005-10, RF-005-12, DH-E01: dos sondeos con el mismo nombre (sin mayúsculas ni
        espacios) se listan en el informe; los códigos de la base que no están en los
        catálogos del proyecto son nuevos; la tabla GIROS con filas y las que no se importan
        se avisan."""
        def rename(row: dict[str, Any]) -> None:
            if row["IDSONDEO"] == 102:
                row["SONDEO"] = " r-01"

        tables = _replace(_raw(V12), "sondeos", change=rename)
        tables = _replace(tables, "giros", rows=[{"NOMBRE": "local", "OLDX": 0.0}])
        dset, report = _read(tables, catalogs=model.Catalogs(
            lithology=(model.LithologyCode("sue"),),
            elements=(model.Element("AU", "ppb"),), sectors=(model.CatalogEntry("norte"),)))
        self.assertEqual(report.duplicate_holes, (("R-01", " r-01"),))
        self.assertEqual(report.per_table["sondeos"].duplicated, 2)
        self.assertEqual(report.unknown_codes["sector"], ("Sur",))
        self.assertEqual(report.unknown_codes["element"], ("cu", "oxid", "cueq"))
        self.assertEqual(report.unknown_codes["group"], ("Campaña 2024", "Control"))
        self.assertEqual(report.unknown_codes["zone"], ("Z1", "Z2"))
        self.assertNotIn("SUE", report.unknown_codes["lithology"][:6])
        self.assertTrue(any("DH-E01" in w for w in report.warnings))
        self.assertTrue(any("GIROS" in w.upper() and "locales" in w for w in report.warnings))
        self.assertTrue(any("secciones" in w for w in report.warnings))
        counts = {name: c.as_dict() for name, c in report.per_table.items()}
        self.assertEqual(set(counts), set(READ[V12]) - {"actualizacion", "giros"})
        self.assertEqual(counts["muestras"], {"read": 7, "imported": 19, "rejected": 0,
                                              "duplicated": 0})
        self.assertEqual(counts["formulas"]["imported"], 1)


if __name__ == "__main__":
    unittest.main()
