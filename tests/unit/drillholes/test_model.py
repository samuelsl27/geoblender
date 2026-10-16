# SPDX-License-Identifier: GPL-3.0-or-later
"""Modelo de los sondeos: registros, ``DrillholeSet`` columnar, declaración de la fuente y DTO
de una importación (spec 005, T03; HU-005-1, HU-005-4; plan 005 §5.2 y §5.3.2; D15).

- **RF-005-02** (el valor decimal de la fuente): registros → columnas → registros y columnas
  → registros → columnas dan los mismos bits en float64 (0,1, −0,0, subnormales, el mayor
  float, coordenadas UTM de 4,4 Mm); las columnas de números son float64 y un número en
  precisión simple (``float32``) se rechaza, en un registro y en una columna: el de RecMin
  llega por su decimal más corto (``drillholes.values``), nunca como float32.
- **RF-005-07** (no suponer nada): la declaración de una fuente obliga a decir el CRS, la
  referencia vertical, la referencia del azimut, la declinación, el convenio de la
  inclinación, las unidades y las reglas de los valores (``TypeError`` si falta uno: ningún
  valor por defecto); lo no declarado queda ``None`` y así sale en sus convenciones; la
  declinación se lee del texto tecleado, exacta, y solo con azimut magnético. Un
  ``DrillholeSet`` lleva siempre su CRS y su referencia vertical del catálogo.

Además: los sondeos se enlazan por su nombre sin mayúsculas ni espacios exteriores (DH-E01:
el primero; DH-E04: sin boca, −1 y su nombre tal cual), ``hole_index`` y ``select`` (los
hijos con el índice nuevo, sin los huérfanos, los catálogos enteros), y el paquete se importa
sin Blender.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import struct
import subprocess
import sys
import unittest
from dataclasses import fields

import numpy as np

from tests.support.package import PACKAGE_NAME, import_geoblender
from tests.support.repo import ROOT
from tests.support.trees import child_env, child_temp

# El hijo importa el modelo y escribe los módulos que no debe haber cargado: los de Blender
# (gbtools.rules.imports.is_blender_module), geoblender.bl, core.project y core.inputs.
CHILD = r"""
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from tests.support.package import import_geoblender
from tests.support.repo import tools_on_path
tools_on_path()
from gbtools.rules.imports import is_blender_module
import_geoblender("drillholes.model")
forbidden = ("geoblender.bl", "geoblender.core.project", "geoblender.core.inputs")
inside = tuple(name + "." for name in forbidden)
found = sorted(name for name in sys.modules if is_blender_module(name)
               or name in forbidden or name.startswith(inside))
print("drillholes.model")
print(json.dumps(found))
"""

drillholes = import_geoblender("drillholes")
model = import_geoblender("drillholes.model")
georef = import_geoblender("core.georef")
content = import_geoblender("core.content")
inputs = import_geoblender("core.inputs")
params = import_geoblender("core.params")
errors = import_geoblender("core.errors")
hashing = import_geoblender("core.hashing")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
H23030 = CATALOG.horizontal(23030)
V5782 = CATALOG.vertical(5782)
KIND = params.ParamKind

Collar = model.Collar
SurveyStation = model.SurveyStation
LithologyInterval = model.LithologyInterval
AssayValue = model.AssayValue
ZoneInterval = model.ZoneInterval
StructureMeasure = model.StructureMeasure
LithologyCode = model.LithologyCode
Element = model.Element
CatalogEntry = model.CatalogEntry
Catalogs = model.Catalogs
DrillholeSet = model.DrillholeSet

# Números que un redondeo cambiaría: el decimal más corto que no es binario, el cero negativo,
# subnormales, el mayor float, 2⁵³, el siguiente a 1 y coordenadas absolutas de 4,4 Mm.
TRICKY = (
    0.1,
    -0.0,
    0.30000000000000004,
    4400040.5,
    4400040.123456789,
    700010.123456789,
    5e-324,
    2.2250738585072014e-308,
    1.7976931348623157e308,
    float(2**53),
    math.nextafter(1.0, 2.0),
    -1e-300,
)

COLLARS = (
    Collar(
        "S-01", 700010.5, 4400040.5, 798.117, 150.0,
        hole_type=model.HoleType.DD, campaign="C-2025", start_date=dt.date(2025, 3, 3),
        end_date=dt.date(2025, 3, 7), extra={"fuente": "bocas.csv", "fila": 2},
    ),
    Collar(
        "S-02", TRICKY[4], TRICKY[5], -0.0, 300.0,
        depth_kind=KIND.CALCULADO, hole_type="RC", planned=True, grade_control=True,
        category=2, priority=1, sector="NORTE", group="G-1", survey_method="giroscopio",
        external_id="recmin:SONDEOS:1234", comments="tildes: áéíóú ñ «»",
    ),
    # Sin Z ni profundidad (DH-E02, DH-E03): ausentes, no un centinela.
    Collar("S-04", TRICKY[6], TRICKY[8], None, None, hole_type=None),
    # El mismo nombre que S-01 sin mayúsculas ni espacios exteriores (DH-E01).
    Collar(" s-01 ", 0.1, 0.30000000000000004, 1.0, 10.0, hole_type=model.HoleType.CA),
)

SURVEYS = (
    SurveyStation("S-01", 0.0, 45.0, -60.0),
    SurveyStation("S-01", 30.0, 45.0, -60.0, method="giroscopio", external_id="e-1"),
    # Convertida: azimut de cuadrícula, el medido, su referencia, δ y γ (D5 del plan).
    SurveyStation(
        "s-02", 60.0, TRICKY[10], TRICKY[0],
        azimuth_measured=359.75, azimuth_ref=model.AzimuthRef.MAGNETIC, declination_deg=0.25,
        convergence_deg=1.5, extra={"nota": "δ y γ"},
    ),
    SurveyStation("S-04", 0.0, 0.0, -90.0, source=model.StationSource.DECLARED_VERTICAL,
                  azimuth_ref="grid"),
    SurveyStation("S-02", 0.0, 300.0, -75.0, source="collar"),
    # Sin boca (DH-E04): se guarda con su nombre.
    SurveyStation("S-99", 5.0, TRICKY[11], -45.0),
)

LITHOLOGY = (
    LithologyInterval("S-01", 0.0, 3.0, "SUE"),
    LithologyInterval("S-01", 3.0, 45.0, "CAL", description="caliza", logged_by="JG"),
    LithologyInterval("S-02", TRICKY[0], TRICKY[2], "MAR", log_set="recmin_alteracion",
                      external_id="recmin:alteracion:7", extra={"COLORPRINT": 255}),
    LithologyInterval("S-99", 0.0, 1.0, "ARC"),
)

ASSAYS = (
    AssayValue("S-01", 58.5, 60.5, "Au", 0.01, "g/t",
               detection_flag=model.DetectionFlag.BELOW_DL, reported_value="<0,01",
               reported_unit="g/t", sample_id="M-0101", lab="ALS", method="FA-AA",
               batch="L-7"),
    AssayValue("S-01", 58.5, 60.5, "Ag", None, "ppm", reported_value="",
               sample_id="M-0101"),
    AssayValue("S-02", TRICKY[3], TRICKY[3] + 2.0, "Au", 10.0, "g/t",
               detection_flag="above_ul", reported_value=">10,00", is_primary=False,
               qaqc_type=model.QaqcType.FIELD_DUP, parent_sample_id="M-0205"),
    AssayValue("S-02", 1.0, 2.0, "Cu", TRICKY[7], "%", detection_flag="not_analysed"),
    # Un material de referencia sin sondeo ni tramo.
    AssayValue(None, None, None, "Au", 1.234, "g/t", qaqc_type="crm", crm_code="OREAS-45",
               extra={"lote": 3}),
)

ZONES = (
    ZoneInterval("S-01", 10.0, 12.5, "Z1", angle_deg=35.0, external_id="recmin:INT:1"),
    ZoneInterval("S-02", 0.1, 0.2, "Z2"),
)

STRUCTURES = (
    StructureMeasure("S-01", 20.0, model.StructureType.FAULT, dip=60.0, dip_direction=120.0,
                     zone="Z1", confidence="alta", comments="estriada"),
    StructureMeasure("S-02", 33.3, "joint", alpha=40.0, beta=210.0,
                     orientation_source=model.OrientationSource.ALPHA_BETA),
)

CATALOGS = Catalogs(
    lithology=(
        LithologyCode("SUE", description="Suelo vegetal", color="#8B6B3D", density=1.8,
                      density_kind=KIND.ADOPTADO, sort_order=1),
        LithologyCode("CAL", color="#CC6633", density=2.65, density_kind="MEDIDO"),
        LithologyCode("MAR", log_set="recmin_alteracion", pattern="rayado",
                      show_in_legend=False),
        LithologyCode("ARC"),
    ),
    elements=(
        Element("Au", "g/t", name="Oro", decimals=2, detection_limit=0.01),
        Element("Ag", "ppm", decimals=1, detection_limit=0.5, use_in_calc=False),
        Element("Cu", "%", sort_order=3, show_in_tables=False, expression="Cu*1",
                color_legend="rojo"),
        Element("Oxid", "text"),
    ),
    sectors=(CatalogEntry("NORTE", description="Sector norte"),),
    groups=(CatalogEntry("G-1"),),
    zones=(CatalogEntry("Z1", density=2.7, density_kind="HIPÓTESIS"), CatalogEntry("Z2")),
)

TABLES = {
    "collars": COLLARS,
    "surveys": SURVEYS,
    "lithology": LITHOLOGY,
    "assays": ASSAYS,
    "zones": ZONES,
    "structures": STRUCTURES,
}
CHILDREN = ("surveys", "lithology", "assays", "zones", "structures")


def build(**tables: object) -> object:
    """El ``DrillholeSet`` de los registros de :data:`TABLES` (o de los que se den)."""
    chosen = {**TABLES, **tables}
    return DrillholeSet.from_records(crs=H25830, vertical=V5782, catalogs=CATALOGS, **chosen)


def bits(value: float) -> bytes:
    return struct.pack("<d", value)


class _Asserts(unittest.TestCase):
    def assertSameRecord(self, got: object, expected: object) -> None:
        """Los mismos campos, con los mismos bits en cada número y el mismo tipo."""
        self.assertIs(type(got), type(expected))
        for item in fields(expected):
            value, wanted = getattr(got, item.name), getattr(expected, item.name)
            with self.subTest(registro=type(expected).__name__, campo=item.name):
                self.assertIs(type(value), type(wanted))
                if isinstance(wanted, float):
                    self.assertEqual(bits(value), bits(wanted))
                else:
                    self.assertEqual(value, wanted)

    def assertSameRecords(self, got: object, expected: object) -> None:
        self.assertIsInstance(got, tuple)
        self.assertEqual(len(got), len(expected))
        for one, other in zip(got, expected, strict=True):
            self.assertSameRecord(one, other)

    def assertSameColumns(self, got: object, expected: object) -> None:
        """Las mismas columnas, con el mismo tipo y los mismos bits."""
        self.assertIs(type(got), type(expected))
        for item in fields(expected):
            value, wanted = getattr(got, item.name), getattr(expected, item.name)
            with self.subTest(columnas=type(expected).__name__, campo=item.name):
                self.assertEqual(value.dtype, wanted.dtype)
                if wanted.dtype == np.float64:
                    np.testing.assert_array_equal(value.view(np.uint64), wanted.view(np.uint64))
                else:
                    self.assertEqual(value.tolist(), wanted.tolist())


class ImportTest(unittest.TestCase):
    def test_package_without_blender(self) -> None:
        """RF-005-02: ``geoblender.drillholes`` y su modelo se importan sin Blender: en un
        proceso nuevo, después de importarlos, no hay ningún módulo de Blender en
        ``sys.modules``, ni ``geoblender.bl``, ni ``core.project`` ni ``core.inputs`` (el modelo
        lo importan los workers, que no cargan el proyecto: ARQ-11)."""
        self.assertTrue(drillholes.__doc__)
        self.assertEqual(model.__name__, f"{PACKAGE_NAME}.drillholes.model")
        flags = ["-B", "-s", *(["-S"] if sys.flags.no_site else [])]
        with child_temp() as temp:
            done = subprocess.run(
                [sys.executable, *flags, "-c", CHILD, str(ROOT)], capture_output=True,
                text=True, env=child_env(None, temp), timeout=60, check=False,
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        loaded, found = done.stdout.split("\n", 1)
        self.assertEqual(loaded, "drillholes.model")
        self.assertEqual(json.loads(found), [])

    def test_enumerations(self) -> None:
        """RF-005-02: los valores de las enumeraciones son los del modelo de datos (plan §5.2)."""
        self.assertEqual([str(v) for v in model.AzimuthRef], ["grid", "true", "magnetic"])
        self.assertEqual([str(v) for v in model.DetectionFlag],
                         ["ok", "below_dl", "above_ul", "not_analysed"])
        self.assertEqual([str(v) for v in model.InclinationConvention],
                         ["negative_down", "positive_down", "from_vertical"])
        self.assertEqual([str(v) for v in model.StationSource],
                         ["measured", "collar", "declared_vertical"])
        self.assertEqual([str(v) for v in model.HoleType],
                         ["DD", "RC", "RP", "AC", "TR", "CA", "OT"])
        self.assertEqual([str(v) for v in model.QaqcType],
                         ["sample", "crm", "blank", "field_dup", "prep_dup", "pulp_dup",
                          "umpire"])
        self.assertEqual([str(v) for v in model.StructureType],
                         ["bedding", "fault", "joint", "contact", "vein", "foliation",
                          "zone_plane"])
        self.assertEqual([str(v) for v in model.OrientationSource],
                         ["measured", "alpha_beta", "recmin_cortes"])


class RoundTripTest(_Asserts):
    def test_records_columns_records(self) -> None:
        """RF-005-02: registros → columnas → registros, con los mismos bits en cada número
        (también −0,0, subnormales y el mayor float) y los mismos textos, fechas, marcas y
        ``extra``; los ausentes siguen ausentes (``None``)."""
        dset = build()
        for table, records in TABLES.items():
            with self.subTest(tabla=table):
                self.assertSameRecords(getattr(dset, table).records(), records)
        self.assertIs(dset.catalogs, CATALOGS)
        self.assertIs(dset.crs, H25830)
        self.assertIs(dset.vertical, V5782)

    def test_columns_records_columns(self) -> None:
        """RF-005-02: columnas → registros → columnas, bit a bit, también con un NaN en una
        columna obligatoria (se conserva) y en una opcional (ausente)."""
        dset = build()
        again = DrillholeSet.from_records(
            crs=dset.crs, vertical=dset.vertical, catalogs=dset.catalogs,
            **{table: getattr(dset, table).records() for table in TABLES},
        )
        for table in TABLES:
            with self.subTest(tabla=table):
                self.assertSameColumns(getattr(again, table), getattr(dset, table))
        surveys = dset.surveys
        holed = model.SurveyColumns(**{
            item.name: getattr(surveys, item.name) for item in fields(surveys)
        } | {"depth": np.array([math.nan, *TRICKY[:5]]),
             "convergence_deg": np.array([math.nan, 0.5, math.nan, -0.0, 1.0, 5e-324])})
        back = model.SurveyColumns.from_records(holed.records(), dset.collars)
        self.assertSameColumns(back, holed)
        self.assertTrue(math.isnan(holed.records()[0].depth))
        self.assertIsNone(holed.records()[0].convergence_deg)

    def test_column_types(self) -> None:
        """RF-005-02: números en float64, el sondeo en int64 (−1 sin boca), marcas en int8
        (posición en ``code_values``), sí/no en bool y textos como objetos."""
        dset = build()
        self.assertEqual(dset.collars.x.dtype, np.float64)
        self.assertEqual(dset.collars.planned.dtype, np.bool_)
        self.assertEqual(dset.collars.name.dtype, object)
        self.assertEqual(dset.surveys.hole.dtype, np.int64)
        self.assertEqual(dset.surveys.hole_name.dtype, object)
        self.assertEqual(dset.assays.detection_flag.dtype, np.int8)
        flags = model.AssayColumns.code_values("detection_flag")
        self.assertEqual(flags, tuple(model.DetectionFlag))
        self.assertEqual([flags[c] for c in dset.assays.detection_flag],
                         ["below_dl", "ok", "above_ul", "not_analysed", "ok"])
        self.assertEqual(dset.surveys.azimuth_ref.tolist(), [-1, -1, 2, 0, -1, -1])
        self.assertEqual(model.CollarColumns.code_values("hole_type")[
            dset.collars.hole_type[1]], model.HoleType.RC)
        self.assertEqual(dset.collars.hole_type[2], -1)
        self.assertEqual(len(dset.assays), 5)
        self.assertEqual(len(DrillholeSet(crs=H25830, vertical=V5782).collars), 0)
        with self.assertRaises(ValueError):
            model.AssayColumns.code_values("value")

    def test_records_normalize(self) -> None:
        """RF-005-02: un entero o un ``numpy.float64`` pasan a ``float`` sin cambiar su valor;
        un NaN opcional es ausente; textos de las enumeraciones, sus miembros."""
        collar = Collar("S", np.float64(0.1), 4400040, 7, None)
        self.assertIs(type(collar.x), float)
        self.assertEqual(bits(collar.x), bits(0.1))
        self.assertIs(type(collar.y), float)
        self.assertEqual(collar.y, 4400040.0)
        self.assertIs(SurveyStation("S", 0, 0, -90, convergence_deg=math.nan).convergence_deg,
                      None)
        self.assertIs(SurveyStation("S", 0, 0, -90, azimuth_ref="true").azimuth_ref,
                      model.AzimuthRef.TRUE)
        self.assertIs(LithologyCode("A", density=2, density_kind="ADOPTADO").density_kind,
                      KIND.ADOPTADO)
        with self.assertRaises(AttributeError):
            collar.x = 1.0  # inmutable

    def test_single_precision_rejected(self) -> None:
        """RF-005-02: un float32 (el Single de RecMin sin pasar por su decimal más corto) no
        entra en el modelo, ni en un registro ni en una columna."""
        with self.assertRaisesRegex(TypeError, "RF-005-02"):
            Collar("S-01", np.float32(0.1), 1.0, 1.0, 1.0)
        with self.assertRaisesRegex(TypeError, "RF-005-02"):
            AssayValue("S-01", 0.0, 1.0, "Au", np.float32(4.35), "g/t")
        collars = build().collars
        values = {item.name: getattr(collars, item.name) for item in fields(collars)}
        with self.assertRaisesRegex(TypeError, "RF-005-02"):
            model.CollarColumns(**values | {"z": collars.z.astype(np.float32)})
        with self.assertRaises(TypeError):
            Collar("S-01", "700010,5", 1.0, 1.0, 1.0)
        with self.assertRaises(TypeError):
            Collar("S-01", True, 1.0, 1.0, 1.0)

    def test_invalid_records(self) -> None:
        """Lo que nunca es un dato válido (claves, enumeraciones y nombres; plan §5.2): un
        nombre vacío, una enumeración desconocida, un color que no es «#RRGGBB», una
        densidad sin su tipo o con tipo CALCULADO, una fecha con hora; el resto (rangos,
        desde ≥ hasta…) lo marca la validación."""
        with self.assertRaises(ValueError):
            Collar("  ", 1.0, 1.0, 1.0, 1.0)
        with self.assertRaises(ValueError):
            Collar("S", 1.0, 1.0, 1.0, 1.0, hole_type="XX")
        with self.assertRaises(ValueError):
            Collar("S", 1.0, 1.0, 1.0, 1.0, depth_kind=KIND.ADOPTADO)
        with self.assertRaises(TypeError):
            Collar("S", 1.0, 1.0, 1.0, 1.0, start_date=dt.datetime(2025, 1, 1, 12))
        with self.assertRaises(ValueError):
            SurveyStation("S", 0.0, 0.0, -90.0, azimuth_ref="north")
        with self.assertRaises(ValueError):
            LithologyCode("A", color="#cc6633")
        with self.assertRaises(ValueError):
            LithologyCode("A", density=2.5)
        with self.assertRaises(ValueError):
            CatalogEntry("Z", density=2.5, density_kind="CALCULADO")
        with self.assertRaises(TypeError):
            AssayValue("S", 0.0, 1.0, "Au", 1.0, "g/t", extra=[("a", 1)])
        # Rangos y tramos al revés sí entran: los marca la validación (DH-E08, DH-E09).
        self.assertEqual(SurveyStation("S", -2.0, 361.0, -90.5).azimuth, 361.0)
        self.assertEqual(LithologyInterval("S", 5.0, 1.0, "A").to_m, 1.0)

    def test_catalogs(self) -> None:
        """Un código de catálogo es único sin distinguir mayúsculas (la litología, dentro de
        su esquema de logueo)."""
        with self.assertRaises(ValueError):
            Catalogs(elements=(Element("Au", "g/t"), Element("AU", "ppb")))
        with self.assertRaises(ValueError):
            Catalogs(zones=(CatalogEntry("Z1"), CatalogEntry(" z1")))
        same_code = Catalogs(lithology=(LithologyCode("MAR"),
                                        LithologyCode("MAR", log_set="recmin_alteracion")))
        self.assertEqual(len(same_code.lithology), 2)
        with self.assertRaises(ValueError):
            Catalogs(lithology=(LithologyCode("MAR"), LithologyCode("mar")))
        with self.assertRaises(TypeError):
            Catalogs(elements=(CatalogEntry("Au"),))
        self.assertIsInstance(Catalogs(elements=[Element("Au", "g/t")]).elements, tuple)


class HolesTest(_Asserts):
    def test_link_by_name(self) -> None:
        """Cada registro hijo apunta a su boca por el nombre sin mayúsculas ni espacios
        exteriores; con dos bocas del mismo nombre (DH-E01), a la primera; sin boca (DH-E04),
        −1 y su nombre tal como venía; un análisis sin sondeo (un CRM), −1 y ``None``."""
        dset = build()
        self.assertEqual(dset.surveys.hole.tolist(), [0, 0, 1, 2, 1, -1])
        self.assertEqual(dset.surveys.hole_name.tolist(),
                         ["S-01", "S-01", "s-02", "S-04", "S-02", "S-99"])
        self.assertEqual(dset.lithology.hole.tolist(), [0, 0, 1, -1])
        self.assertEqual(dset.assays.hole.tolist(), [0, 0, 1, 1, -1])
        self.assertIsNone(dset.assays.hole_name[4])
        self.assertEqual(model.name_key(" S-01 "), model.name_key("s-01"))
        self.assertEqual(dset.collars.lookup([" S-02", "x", None, "s-01"]).tolist(),
                         [1, -1, -1, 0])

    def test_hole_index(self) -> None:
        """``hole_index``: la posición de cada sondeo por su nombre (sin mayúsculas ni espacios
        exteriores), en int64; uno que no está, ``KeyError`` con su nombre."""
        dset = build()
        index = dset.hole_index(["s-04", "S-02 "])
        self.assertEqual(index.dtype, np.int64)
        self.assertEqual(index.tolist(), [2, 1])
        self.assertEqual(dset.hole_index([]).tolist(), [])
        with self.assertRaisesRegex(KeyError, "S-77"):
            dset.hole_index(["S-01", "S-77"])
        with self.assertRaises(TypeError):
            dset.hole_index("S-01")

    def test_select(self) -> None:
        """``select``: las bocas pedidas en su orden, sus registros hijos (en el orden de
        antes) con el índice nuevo, sin los huérfanos; los catálogos, el CRS y la referencia
        vertical, los mismos; la fuente no cambia."""
        dset = build()
        before = {table: getattr(dset, table).records() for table in TABLES}
        part = dset.select(dset.hole_index(["S-02", "S-01"]))
        self.assertEqual(part.collars.name.tolist(), ["S-02", "S-01"])
        self.assertEqual(part.surveys.hole.tolist(), [1, 1, 0, 0])
        self.assertEqual(part.surveys.depth.tolist(), [0.0, 30.0, 60.0, 0.0])
        self.assertEqual(part.lithology.hole_name.tolist(), ["S-01", "S-01", "S-02"])
        self.assertEqual(part.assays.hole.tolist(), [1, 1, 0, 0])
        self.assertEqual(part.zones.hole.tolist(), [1, 0])
        self.assertEqual(part.structures.hole.tolist(), [1, 0])
        self.assertIs(part.catalogs, dset.catalogs)
        self.assertIs(part.crs, dset.crs)
        self.assertIs(part.vertical, dset.vertical)
        self.assertSameRecords(part.collars.records(), (COLLARS[1], COLLARS[0]))
        mask = dset.select(np.array([False, False, True, False]))
        self.assertEqual(mask.collars.name.tolist(), ["S-04"])
        self.assertEqual(mask.surveys.hole.tolist(), [0])
        self.assertEqual(len(dset.select(np.array([], dtype=np.int64)).assays), 0)
        for table, records in before.items():
            self.assertSameRecords(getattr(dset, table).records(), records)
        with self.assertRaises(IndexError):
            dset.select(np.array([4]))
        with self.assertRaises(IndexError):
            dset.select(np.array([-1]))
        with self.assertRaises(ValueError):
            dset.select(np.array([1, 1]))
        with self.assertRaises(ValueError):
            dset.select(np.array([True, False]))
        with self.assertRaises(TypeError):
            dset.select(np.array([0.0]))

    def test_set_invariants(self) -> None:
        """RF-005-07: un ``DrillholeSet`` lleva su CRS y su referencia vertical del catálogo
        (nunca un código suelto ni nada supuesto); un índice de sondeo fuera de rango, o
        columnas de longitudes distintas, se rechazan."""
        with self.assertRaises(TypeError):
            DrillholeSet(crs=25830, vertical=V5782)
        with self.assertRaises(TypeError):
            DrillholeSet(crs=H25830, vertical=None)
        with self.assertRaises(TypeError):
            DrillholeSet(vertical=V5782)  # sin CRS: ninguno por defecto
        dset = build()
        surveys = dset.surveys
        values = {item.name: getattr(surveys, item.name) for item in fields(surveys)}
        with self.assertRaises(ValueError):
            DrillholeSet(crs=H25830, vertical=V5782, collars=dset.collars,
                         surveys=model.SurveyColumns(**values | {"hole": surveys.hole + 4}))
        with self.assertRaises(ValueError):
            model.SurveyColumns(**values | {"depth": surveys.depth[:2]})
        with self.assertRaises(TypeError):
            model.SurveyColumns(**values | {"depth": surveys.depth.reshape(2, 3)})


def declaration(**changes: object) -> object:
    """La declaración de ``csv_basico`` (``esperado.json``), con cambios."""
    values = dict(
        crs=H25830, vertical=V5782, azimuth_ref=model.AzimuthRef.GRID, declination_deg=None,
        inclination_convention=model.InclinationConvention.NEGATIVE_DOWN,
        units={"Au": "g/t", "Ag": "ppm", "Cu": "%"},
        value_rules=model.ValueRules(","), all_vertical=True,
        density_kind=KIND.ADOPTADO, date_format="%d/%m/%Y",
    )
    values.update(changes)
    return model.SourceDeclaration(**values)


class DeclarationTest(unittest.TestCase):
    def test_nothing_is_assumed(self) -> None:
        """RF-005-07: CRS, referencia vertical, referencia del azimut, declinación, convenio
        de la inclinación, unidades y reglas de los valores se declaran siempre (sin ninguno
        por defecto); lo no declarado queda ``None`` y así sale en sus convenciones."""
        required = ("crs", "vertical", "azimuth_ref", "declination_deg",
                    "inclination_convention", "units", "value_rules")
        full = dict(crs=None, vertical=None, azimuth_ref=None, declination_deg=None,
                    inclination_convention=None, units={}, value_rules=model.ValueRules("."))
        for name in required:
            with self.subTest(falta=name), self.assertRaises(TypeError):
                model.SourceDeclaration(**{k: v for k, v in full.items() if k != name})
        empty = model.SourceDeclaration(**full)
        self.assertIsNone(empty.crs)
        self.assertIsNone(empty.vertical)
        self.assertFalse(empty.all_vertical)
        self.assertIs(empty.density_kind, KIND.ADOPTADO)  # spec §11: ADOPTADO salvo MEDIDO
        self.assertIsNone(empty.date_format)
        self.assertEqual(empty.conventions(), {
            "all_vertical": False, "azimuth_ref": None, "declination_deg": None,
            "density_kind": "ADOPTADO", "inclination_convention": None,
            "negative_is_below_dl": False, "sentinels": [], "units": {},
        })
        self.assertEqual(tuple(sorted(empty.conventions())), model.CONVENTION_KEYS)

    def test_types(self) -> None:
        """RF-005-07: el CRS y la referencia vertical son los del catálogo (``CrsRef``,
        ``VerticalRef``), no un código; las enumeraciones admiten su texto."""
        with self.assertRaises(TypeError):
            declaration(crs=25830)
        with self.assertRaises(TypeError):
            declaration(vertical=5782)
        decl = declaration(azimuth_ref="true", inclination_convention="from_vertical")
        self.assertIs(decl.azimuth_ref, model.AzimuthRef.TRUE)
        self.assertIs(decl.inclination_convention, model.InclinationConvention.FROM_VERTICAL)
        with self.assertRaises(ValueError):
            declaration(azimuth_ref="north")
        with self.assertRaises(ValueError):
            declaration(density_kind="CALCULADO")
        with self.assertRaises(TypeError):
            declaration(value_rules=None)
        with self.assertRaises(ValueError):
            declaration(date_format="dd/mm/aaaa")
        with self.assertRaises(TypeError):
            declaration(all_vertical="sí")

    def test_declination(self) -> None:
        """RF-005-07, RF-005-27: la declinación se lee del texto tecleado (coma o punto) en
        float64 exacto (0,25 → 0.25, nunca el float32 de un ``FloatProperty``), solo con azimut
        magnético; magnético sin declinación queda sin declarar (lo nombra la importación);
        fuera de [−180, 180], ``ValidationError``."""
        self.assertEqual(bits(model.parse_declination("0,25")), bits(0.25))
        self.assertEqual(bits(model.parse_declination(" -1.10 ")), bits(-1.1))
        self.assertEqual(bits(model.parse_declination("0,1")), bits(0.1))
        for text, code in (("200", "dh.declination_out_of_range"),
                           ("-180,5", "dh.declination_out_of_range"),
                           ("abc", "core.number_invalid"), ("", "core.number_missing")):
            with self.subTest(texto=text), self.assertRaises(errors.ValidationError) as caught:
                model.parse_declination(text)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.value, text)
        magnetic = declaration(azimuth_ref="magnetic",
                               declination_deg=model.parse_declination("0,25"))
        self.assertEqual(magnetic.conventions()["declination_deg"], 0.25)
        self.assertIn(b'"declination_deg":0.25', hashing.canonical_json(magnetic.conventions()))
        undeclared = declaration(azimuth_ref="magnetic", declination_deg=None)
        self.assertIsNone(undeclared.declination_deg)
        with self.assertRaises(ValueError):
            declaration(azimuth_ref="grid", declination_deg=0.25)
        with self.assertRaises(ValueError):
            declaration(azimuth_ref=None, declination_deg=0.25)
        with self.assertRaises(ValueError):
            declaration(azimuth_ref="magnetic", declination_deg=181.0)
        with self.assertRaisesRegex(TypeError, "RF-005-02"):
            declaration(azimuth_ref="magnetic", declination_deg=np.float32(0.25))

    def test_conventions_are_content(self) -> None:
        """RF-005-07: las convenciones son lo que cambia el significado de los datos
        (referencia del azimut, declinación, inclinación, «todos verticales», unidades,
        centinelas, «−x = <x» y tipo de la densidad) y entran en las declaraciones de la
        entrada (``core.inputs.input_declarations``); el decimal, el formato de fecha y los CRS
        no (los CRS van aparte, en ``crs_h`` y ``crs_v``)."""
        decl = declaration(value_rules=model.ValueRules(",", frozenset({"ND", "-99"}), True))
        self.assertEqual(decl.conventions(), {
            "all_vertical": True, "azimuth_ref": "grid", "declination_deg": None,
            "density_kind": "ADOPTADO", "inclination_convention": "negative_down",
            "negative_is_below_dl": True, "sentinels": ["-99", "ND"],
            "units": {"Ag": "ppm", "Au": "g/t", "Cu": "%"},
        })
        other = declaration(value_rules=model.ValueRules(".", frozenset({"-99", "ND"}), True),
                            date_format="%Y-%m-%d")
        self.assertEqual(other.conventions(), decl.conventions())
        for change in (dict(units={"Au": "ppb", "Ag": "ppm", "Cu": "%"}),
                       dict(all_vertical=False), dict(density_kind="MEDIDO"),
                       dict(inclination_convention="positive_down")):
            with self.subTest(cambio=change):
                self.assertNotEqual(declaration(**change).conventions(),
                                    declaration().conventions())
        result = inputs.input_declarations({"epsg": 25830}, {"epsg": 5782}, decl.conventions())
        self.assertEqual(result["conventions"]["sentinels"], ["-99", "ND"])

    def test_units(self) -> None:
        """RF-005-07: una unidad por elemento, sin distinguir mayúsculas en el código; dos
        códigos iguales sin mayúsculas, o una unidad vacía, se rechazan."""
        decl = declaration()
        self.assertEqual(decl.unit_of("AU"), "g/t")
        self.assertIsNone(decl.unit_of("Zn"))
        with self.assertRaises(ValueError):
            declaration(units={"Au": "g/t", "AU": "ppb"})
        with self.assertRaises(ValueError):
            declaration(units={"Au": ""})
        with self.assertRaises(TypeError):
            declaration(units=[("Au", "g/t")])
        mutable = {"Au": "g/t"}
        decl = declaration(units=mutable)
        mutable["Au"] = "ppb"
        self.assertEqual(decl.unit_of("Au"), "g/t")

    def test_value_rules(self) -> None:
        """RF-005-07: el decimal es coma o punto; los centinelas, textos no vacíos."""
        rules = model.ValueRules(",", {"ND"})
        self.assertEqual(rules.sentinels, frozenset({"ND"}))
        self.assertFalse(rules.negative_is_below_dl)
        for bad in (dict(decimal_mark=";"), dict(decimal_mark=",", sentinels={""}),
                    dict(decimal_mark=",", sentinels="ND")):
            with self.subTest(reglas=bad), self.assertRaises((TypeError, ValueError)):
                model.ValueRules(**bad)


def digest(fill: str) -> object:
    return content.ContentDigest(fill * 64, fill * 64, content.NORMALIZER, "io.dh_csv@1")


class ImportDtoTest(unittest.TestCase):
    def test_dto(self) -> None:
        """RF-005-02, RF-005-07: el DTO de una importación lleva el ``DrillholeSet`` en el CRS
        y la referencia vertical que declara la fuente, una entrada por fichero con su
        ``ContentDigest`` y sus huellas (008; los campos de ``core.inputs.SourcePrint``), los
        códigos nuevos, los sondeos que ya existen, los recuentos y los rechazos (tabla, fila,
        campo, valor, motivo)."""
        sources = (
            model.ImportSource(name="bocas.csv", roles=("collar",), digest=digest("a"),
                               prints=(model.FilePrint("b" * 64, size=10, mtime_ns=1),)),
            model.ImportSource(name="libro.xlsx", layer="Análisis", roles=["assay_wide"],
                               digest=digest("c"), prints=[model.FilePrint("d" * 64)]),
        )
        found = sources[0].prints[0]
        same = inputs.SourcePrint(found.sha256, size=found.size, mtime_ns=found.mtime_ns)
        self.assertEqual((same.sha256, same.size, same.mtime_ns), ("b" * 64, 10, 1))
        dto = model.ImportDto(
            dset=build(), declaration=declaration(), sources=sources,
            new_codes={"lithology": ["GRA"], "element": ()}, existing_holes=["S-01"],
            counts={"collar": {"read": 6, "imported": 5, "rejected": 1}},
            rejected=[("collar", 7, "X", "abc", "no es un número")],
        )
        self.assertEqual(dto.sources[1].roles, ("assay_wide",))
        self.assertEqual(dto.sources[1].prints[0].sha256, "d" * 64)
        self.assertEqual(dto.new_codes["lithology"], ("GRA",))
        self.assertEqual(dto.existing_holes, ("S-01",))
        self.assertEqual(dto.counts["collar"]["imported"], 5)
        self.assertIsInstance(dto.rejected[0], model.Rejection)
        self.assertEqual(dto.rejected[0].field, "X")
        self.assertEqual(dto.rejected[0], ("collar", 7, "X", "abc", "no es un número"))

    def test_dto_rejects(self) -> None:
        """RF-005-07: el ``DrillholeSet`` del DTO está en el CRS y la referencia vertical
        declarados; fuentes con nombre repetido, sin huellas o con un nombre con ruta, un
        catálogo desconocido o un recuento negativo son errores del programa."""
        source = model.ImportSource(name="bocas.csv", roles=("collar",), digest=digest("a"),
                                    prints=(model.FilePrint("b" * 64),))
        good = dict(dset=build(), declaration=declaration(), sources=(source,))
        model.ImportDto(**good)
        bad_cases = (
            dict(declaration=declaration(crs=H23030)),
            dict(declaration=declaration(crs=None)),
            dict(declaration=declaration(vertical=CATALOG.local_vertical("NP-0"))),
            dict(sources=()),
            dict(sources=(source, source)),
            dict(new_codes={"rock": ("GRA",)}),
            dict(counts={"collar": {"read": -1}}),
            dict(rejected=[("collar", 0, "X", "abc", "motivo")]),
            dict(rejected=[("collar", 7, "X")]),
        )
        for change in bad_cases:
            with self.subTest(cambio=change), self.assertRaises((TypeError, ValueError)):
                model.ImportDto(**good | change)
        for change in (dict(prints=()), dict(name="datos/bocas.csv"), dict(name=" bocas.csv"),
                       dict(roles=()), dict(digest="a" * 64), dict(layer=""),
                       dict(prints=(inputs.SourcePrint("b" * 64),))):
            values = dict(name="bocas.csv", roles=("collar",), digest=digest("a"),
                          prints=(model.FilePrint("b" * 64),)) | change
            with self.subTest(fuente=change), self.assertRaises((TypeError, ValueError)):
                model.ImportSource(**values)
        for bad in (dict(sha256="B" * 64), dict(sha256="b" * 63), dict(size=-1),
                    dict(mtime_ns=1.5)):
            values = dict(sha256="b" * 64) | bad
            with self.subTest(huella=bad), self.assertRaises((TypeError, ValueError)):
                model.FilePrint(**values)


if __name__ == "__main__":
    unittest.main()
