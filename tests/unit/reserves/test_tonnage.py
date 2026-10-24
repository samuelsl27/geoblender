# SPDX-License-Identifier: GPL-3.0-or-later
"""Toneladas y relaciones de una cubicación por unidades (spec 011, T10; HU-011-3; RF-011-15,
RF-011-16, RF-011-17, RF-011-18; plan 011 A8, A9, D-8, D-16 y D-28).

``reserves.tonnage`` es la segunda de las dos operaciones encadenadas de una cubicación con
unidades (D-16): de los m³ de cada unidad por dominio y rodaja (lo que da ``res.volume``) y de
los parámetros de la columna (densidad in situ, K y porcentajes, sin valor por defecto: D-8)
saca, por unidad y por componente, el volumen, el esponjado y las toneladas, y las relaciones
estéril/útil. Una compuesta se reparte por sus porcentajes, que han de sumar 100 con dos
decimales; lo in situ pesa V·ρ y se esponja a V·K; lo suelto pesa V·ρ/K (error 67). Sin densidad
(o, en lo suelto, sin K), el volumen sin toneladas, el aviso con la unidad y el parámetro y sin
total de toneladas. Las relaciones, en t/t y en m³/m³ in situ (lo suelto, V/K: D-28).

Las cifras de referencia son cuentas a mano con las fórmulas de la spec; las densidades, los K y
los porcentajes son **valores sintéticos de prueba** (los de ``tests/support/res_fixtures.py``),
de ningún material real.
"""

from __future__ import annotations

import dataclasses
import math
import unittest

from tests.support.package import import_geoblender

tonnage = import_geoblender("reserves.tonnage")
materials = import_geoblender("reserves.materials")
surfaces = import_geoblender("reserves.surfaces")
res_params = import_geoblender("reserves.params")
messages = import_geoblender("reserves.messages")
core_params = import_geoblender("core.params")

Unit = materials.Unit
Component = materials.Component
MaterialColumn = materials.MaterialColumn
SurfaceRef = surfaces.SurfaceRef
UnitVolume = tonnage.UnitVolume
density_key = res_params.density_key
swell_key = res_params.swell_key
percent_key = res_params.percent_key

CLOSURE = 1e-9
"""Cierre de los componentes con su unidad (D-14 b)."""
SAME = 1e-12
"""Las cuentas a mano en float64 frente a las de ``tonnage``: error relativo."""
NO_DENSITY = "res.note_no_density"
NO_SWELL = "res.note_no_swell"
NO_USEFUL = "res.note_no_useful"
BENCH = (600.0, 610.0)

# Densidad in situ (t/m³) y K de cada unidad o componente; porcentajes de la capa útil. Valores
# sintéticos de prueba (los de la columna de ``res_fixtures``).
RHO = {"acopio": 2.60, "montera": 2.00, "caliza": 2.65, "arcilla": 2.10, "muro": 2.45}
K = {"acopio": 1.50, "montera": 1.25, "caliza": 1.60, "arcilla": 1.30, "muro": 1.45}
PERCENT = {"caliza": 82.50, "arcilla": 17.50}

# m³ de desmonte de cada unidad por dominio (la fila «*», su suma; «Fase 3», sin material útil).
VOLUMES = {
    "Fase 1": {"acopio": 300.0, "montera": 1000.0, "capa_util": 2000.0, "muro": 400.0},
    "Fase 2": {"acopio": 0.0, "montera": 500.0, "capa_util": 1500.0, "muro": 0.0},
    "Fase 3": {"acopio": 0.0, "montera": 250.0, "capa_util": 0.0, "muro": 125.0},
}
BENCH_VOLUMES = {"acopio": 0.0, "montera": 0.0, "capa_util": 800.0, "muro": 525.0}


def _column(*, stockpile: str = "loose", clay_role: str = "waste") -> MaterialColumn:
    """Acopio (antrópico, útil, suelto), montera (estéril, in situ), capa útil compuesta (caliza
    útil y arcilla, in situ) y muro (estéril, in situ, sin base)."""
    return MaterialColumn((
        Unit("acopio", "Acopio", "anthropic", "useful", stockpile, SurfaceRef(dataset="mdt"),
             SurfaceRef(dataset="espesor_acopio")),
        Unit("montera", "Montera", "natural", "waste", "in_situ", SurfaceRef(dataset="techo")),
        Unit("capa_util", "Capa útil", "compound", None, "in_situ",
             SurfaceRef(elevation=600.0),
             components=(Component("caliza", "Caliza", "useful"),
                         Component("arcilla", "Arcilla", clay_role))),
        Unit("muro", "Muro", "natural", "waste", "in_situ"),
    ))


def _params(**changes: float | None) -> dict[str, object]:
    """Los parámetros de la columna (``density_<código>``, ``swell_<código>`` y
    ``percent_<componente>`` cambian uno; ``None``, sin declarar)."""
    values: dict[str, object] = {}
    for code in ("acopio", "montera", "muro"):
        values[density_key(code)] = RHO[code]
        values[swell_key(code)] = K[code]
    for code in ("caliza", "arcilla"):
        values[density_key("capa_util", code)] = RHO[code]
        values[swell_key("capa_util", code)] = K[code]
        values[percent_key("capa_util", code)] = PERCENT[code]
    keys = {f"density_{c}": density_key(c) for c in ("acopio", "montera", "muro")}
    keys |= {f"swell_{c}": swell_key(c) for c in ("acopio", "montera", "muro")}
    for code in ("caliza", "arcilla"):
        keys[f"density_{code}"] = density_key("capa_util", code)
        keys[f"swell_{code}"] = swell_key("capa_util", code)
        keys[f"percent_{code}"] = percent_key("capa_util", code)
    for name, value in changes.items():
        if value is None:
            values.pop(keys[name])
        else:
            values[keys[name]] = value
    return values


def _volumes(table: dict[str, dict[str, float]] = VOLUMES) -> list[UnitVolume]:
    """Las filas de ``table`` por dominio, con la de todos (``*``) delante y una rodaja."""
    rows = []
    for code in ("acopio", "montera", "capa_util", "muro"):
        total = math.fsum(volumes[code] for volumes in table.values())
        rows.append(UnitVolume(tonnage.ALL_DOMAINS, None, code, total))
    for domain, volumes in table.items():
        rows += [UnitVolume(domain, None, code, volume) for code, volume in volumes.items()]
    rows += [UnitVolume(tonnage.ALL_DOMAINS, BENCH, code, volume)
             for code, volume in BENCH_VOLUMES.items()]
    return rows


def _total(domain: str, code: str) -> float:
    if domain == tonnage.ALL_DOMAINS:
        return math.fsum(volumes[code] for volumes in VOLUMES.values())
    return VOLUMES[domain][code]


def _leaves(domain: str) -> dict[str, float]:
    """Los m³ de cada elemento sin componentes del dominio (la capa útil, ya repartida)."""
    useful = _total(domain, "capa_util")
    return {"acopio": _total(domain, "acopio"), "montera": _total(domain, "montera"),
            "caliza": useful * PERCENT["caliza"] / 100.0,
            "arcilla": useful * PERCENT["arcilla"] / 100.0, "muro": _total(domain, "muro")}


class TonnageTestCase(unittest.TestCase):

    def assertClose(self, found: float | None, expected: float, *, tolerance: float = SAME,
                    msg: object = None) -> None:
        self.assertIsNotNone(found, msg)
        scale = max(abs(expected), 1.0)
        self.assertLessEqual(abs(found - expected), tolerance * scale,
                             f"{found!r} frente a {expected!r} ({msg})")


class WeightTest(TonnageTestCase):
    """RF-011-16: in situ, t = V·ρ y esponjado V·K; suelto, t = V·ρ/K y sin esponjado."""

    def test_in_situ_and_loose(self) -> None:
        """RF-011-16 (error 67): la montera (in situ) pesa V·ρ y se esponja a V·K; el acopio
        (suelto) pesa V·ρ/K, sin esponjado (ya lo está), y su volumen in situ es V/K; con el
        acopio in situ habría pesado K veces más. Un elemento sin volumen pesa 0 t. Los valores
        de los parámetros pueden ser los ``ResolvedParam`` que anota la operación."""
        values = _params()
        resolved = core_params.ResolvedParam(
            parameter_uid="p1", key=density_key("montera"), scope="project", scope_uid="",
            rev=1, value=RHO["montera"], value_json="2.0", unit="t/m3", kind="HIPÓTESIS",
            unconfirmed=False, value_sha256="0" * 64)
        values[density_key("montera")] = resolved
        result = tonnage.tonnage(_volumes(), _column(), values)
        montera = result.row("montera", domain="Fase 1")
        self.assertEqual((montera.volume_m3, montera.in_situ_m3, montera.notes),
                         (1000.0, 1000.0, ()))
        self.assertClose(montera.mass_t, 1000.0 * RHO["montera"])
        self.assertClose(montera.swell_m3, 1000.0 * K["montera"])
        self.assertIs(montera.state, materials.State.IN_SITU)
        self.assertIs(montera.role, materials.Role.WASTE)
        stockpile = result.row("acopio")
        self.assertEqual(stockpile.volume_m3, 300.0)
        self.assertClose(stockpile.mass_t, 300.0 * RHO["acopio"] / K["acopio"])
        self.assertClose(stockpile.in_situ_m3, 300.0 / K["acopio"])
        self.assertIsNone(stockpile.swell_m3)
        self.assertEqual(stockpile.notes, ())
        empty = result.row("acopio", domain="Fase 2")
        self.assertEqual((empty.volume_m3, empty.mass_t, empty.in_situ_m3), (0.0, 0.0, 0.0))
        in_situ = tonnage.tonnage(_volumes(), _column(stockpile="in_situ"), values)
        heavier = in_situ.row("acopio").mass_t
        self.assertClose(heavier, 300.0 * RHO["acopio"])
        self.assertClose(heavier / stockpile.mass_t, K["acopio"])
        self.assertClose(in_situ.row("acopio").swell_m3, 300.0 * K["acopio"])
        self.assertEqual(result.missing, ())

    def test_compound_unit_by_its_percentages(self) -> None:
        """RF-011-15 y RF-011-16: la capa útil (compuesta) se reparte entre sus componentes por
        sus porcentajes (82,50 % y 17,50 %), cada uno con su papel, su densidad y su K; los
        componentes suman su unidad ≤ 10⁻⁹ (también con porcentajes que suman 100 con dos
        decimales sin ser 100 en binario); la unidad pesa lo que sus componentes."""
        result = tonnage.tonnage(_volumes(), _column(), _params())
        for domain in (tonnage.ALL_DOMAINS, "Fase 1", "Fase 2"):
            with self.subTest(domain=domain):
                unit = result.row("capa_util", domain=domain)
                limestone = result.row("capa_util", "caliza", domain=domain)
                clay = result.row("capa_util", "arcilla", domain=domain)
                volume = _total(domain, "capa_util")
                self.assertEqual(unit.volume_m3, volume)
                self.assertIsNone(unit.role)
                self.assertIs(limestone.role, materials.Role.USEFUL)
                self.assertIs(clay.role, materials.Role.WASTE)
                self.assertClose(limestone.volume_m3, volume * 0.825)
                self.assertClose(clay.volume_m3, volume * 0.175)
                self.assertLessEqual(abs(limestone.volume_m3 + clay.volume_m3 - volume),
                                     CLOSURE * volume)
                self.assertClose(limestone.mass_t, volume * 0.825 * RHO["caliza"])
                self.assertClose(clay.swell_m3, volume * 0.175 * K["arcilla"])
                self.assertClose(unit.mass_t, limestone.mass_t + clay.mass_t)
                self.assertClose(unit.swell_m3, limestone.swell_m3 + clay.swell_m3)
        for percents in ((33.33, 33.33, 33.34), (50.0, 49.996, 0.0), (12.34, 56.78, 30.88)):
            with self.subTest(percents=percents):
                column = MaterialColumn((
                    Unit("techo", "Techo", "natural", "waste", "in_situ", SurfaceRef(dataset="b")),
                    Unit("mezcla", "Mezcla", "compound", None, "in_situ", components=tuple(
                        Component(code, code.capitalize(), "useful")
                        for code in ("a", "b", "c"))),
                ))
                values = {percent_key("mezcla", code): value
                          for code, value in zip("abc", percents, strict=True)}
                volume = 123_456.789
                found = tonnage.tonnage([UnitVolume("*", None, "mezcla", volume),
                                         UnitVolume("*", None, "techo", 0.0)], column, values)
                parts = [found.row("mezcla", code).volume_m3 for code in "abc"]
                self.assertLessEqual(abs(math.fsum(parts) - volume), CLOSURE * volume)
                self.assertEqual(found.row("mezcla", "c").volume_m3 == 0.0, percents[2] == 0.0)

    def test_percentages_that_do_not_add_up(self) -> None:
        """RF-011-15: unos porcentajes que no suman 100 con dos decimales (|Σ − 100| ≥ 0,005;
        uno sin declarar, no suma) se rechazan con ``res.percent_sum``, nombrando la unidad y
        la suma, y no se calcula nada; 99,996 % vale."""
        for clay, shown in ((17.4, 99.9), (17.494, 99.99), (17.506, 100.01), (None, 82.5)):
            with self.subTest(clay=clay):
                with self.assertRaises(messages.ResError) as caught:
                    tonnage.tonnage(_volumes(), _column(), _params(percent_arcilla=clay))
                error = caught.exception
                self.assertEqual(error.code, "res.percent_sum")
                self.assertEqual(error.values["unit"], "Capa útil")
                self.assertEqual(error.values["value"], shown)
                self.assertIn("«Capa útil»", error.text)
                self.assertIn(f"{shown} %".replace(".", ","), error.text)
        result = tonnage.tonnage(_volumes(), _column(), _params(percent_arcilla=17.496))
        self.assertIsNotNone(result.total.total_t)


class MissingParametersTest(TonnageTestCase):
    """RF-011-17 (D-8): ninguna densidad ni ningún K supuestos."""

    def test_without_density(self) -> None:
        """RF-011-17: la montera sin densidad sale con su volumen y su esponjado, sin
        toneladas («sin densidad»); el aviso nombra la unidad y el parámetro; ni el total ni las
        toneladas de lo estéril, ni la relación en t/t (la de m³/m³, sí)."""
        result = tonnage.tonnage(_volumes(), _column(), _params(density_montera=None))
        row = result.row("montera")
        self.assertEqual(row.volume_m3, 1750.0)
        self.assertIsNone(row.mass_t)
        self.assertClose(row.swell_m3, 1750.0 * K["montera"])
        self.assertEqual(row.notes, (NO_DENSITY,))
        self.assertEqual(len(result.missing), 1)
        missing = result.missing[0]
        self.assertEqual((missing.unit, missing.component, missing.key),
                         ("montera", None, density_key("montera")))
        self.assertEqual(missing.text(), messages.render(
            "res.density_missing", unit="Montera", value=density_key("montera")))
        self.assertIn("«Montera»", missing.text("en"))
        total = result.total
        self.assertIsNone(total.total_t)
        self.assertEqual(total.total_notes, (NO_DENSITY,))
        self.assertIsNone(total.waste_t)
        self.assertIsNotNone(total.useful_t)
        self.assertEqual((total.ratio_t.value, total.ratio_t.notes), (None, (NO_DENSITY,)))
        self.assertIsNotNone(total.ratio_m3.value)
        self.assertClose(result.row("muro").mass_t, 525.0 * RHO["muro"])

    def test_loose_without_swell(self) -> None:
        """RF-011-17 y D-28: el acopio (suelto) sin K no pesa (V·ρ/K) ni tiene volumen in
        situ: «sin K», el aviso con su parámetro, sin total de toneladas ni relaciones donde
        tiene volumen; en «Fase 2», donde no lo tiene, sí."""
        result = tonnage.tonnage(_volumes(), _column(), _params(swell_acopio=None))
        row = result.row("acopio")
        self.assertEqual((row.volume_m3, row.mass_t, row.in_situ_m3, row.notes),
                         (300.0, None, None, (NO_SWELL,)))
        self.assertEqual([(m.unit, m.key) for m in result.missing],
                         [("acopio", swell_key("acopio"))])
        for domain in (tonnage.ALL_DOMAINS, "Fase 1"):
            with self.subTest(domain=domain):
                group = result.group(domain)
                self.assertIsNone(group.total_t)
                self.assertIsNone(group.useful_m3)
                self.assertEqual(group.ratio_m3, tonnage.Ratio(None, (NO_SWELL,)))
                self.assertEqual(group.ratio_t, tonnage.Ratio(None, (NO_SWELL,)))
        second = result.group("Fase 2")
        self.assertIsNotNone(second.total_t)
        self.assertIsNotNone(second.ratio_m3.value)
        self.assertIsNotNone(second.ratio_t.value)

    def test_in_situ_without_swell_and_components(self) -> None:
        """RF-011-16 y RF-011-17: sin el K de lo in situ, sin esponjado (nota) pero con
        toneladas y sin aviso; un componente sin densidad, sin toneladas él y su unidad, con el
        aviso nombrando unidad y componente; sin ningún parámetro, ninguna tonelada inventada."""
        result = tonnage.tonnage(_volumes(), _column(), _params(swell_montera=None,
                                                                density_caliza=None))
        montera = result.row("montera")
        self.assertIsNone(montera.swell_m3)
        self.assertClose(montera.mass_t, 1750.0 * RHO["montera"])
        self.assertEqual(montera.notes, (NO_SWELL,))
        self.assertIsNone(result.row("capa_util", "caliza").mass_t)
        unit = result.row("capa_util")
        self.assertIsNone(unit.mass_t)
        self.assertEqual(unit.notes, (NO_DENSITY,))
        self.assertIsNotNone(result.row("capa_util", "arcilla").mass_t)
        self.assertEqual([(m.unit, m.component, m.key) for m in result.missing],
                         [("capa_util", "caliza", density_key("capa_util", "caliza"))])
        self.assertIn("«Capa útil ▸ Caliza»", result.missing[0].text())
        self.assertIsNone(result.total.total_t)
        self.assertIsNone(result.group("Fase 3").ratio_t.value)
        self.assertIsNotNone(result.group("Fase 3").total_t)
        only_percents = {key: value for key, value in _params().items()
                         if key.endswith(".percent")}
        bare = tonnage.tonnage(_volumes(), _column(), only_percents)
        self.assertTrue(all(row.mass_t is None for row in bare.rows if row.volume_m3 != 0.0))
        self.assertTrue(all(row.mass_t == 0.0 for row in bare.rows if row.volume_m3 == 0.0))
        self.assertEqual([m.key for m in bare.missing], [
            density_key("acopio"), swell_key("acopio"), density_key("montera"),
            density_key("capa_util", "caliza"), density_key("capa_util", "arcilla"),
            density_key("muro")])


class RatiosTest(TonnageTestCase):
    """RF-011-18 (D-28): estéril/útil en t/t y en m³/m³ in situ."""

    def test_in_total_and_by_domain(self) -> None:
        """RF-011-18: la relación estéril/útil en t/t (Σ t estéril / Σ t útil) y en m³/m³ in
        situ (el acopio suelto, V/K: D-28), en total, por dominio y por rodaja; útil y estéril
        in situ y en t; el total de toneladas."""
        result = tonnage.tonnage(_volumes(), _column(), _params())
        for domain in (tonnage.ALL_DOMAINS, "Fase 1", "Fase 2"):
            with self.subTest(domain=domain):
                v = _leaves(domain)
                waste_m3 = v["montera"] + v["arcilla"] + v["muro"]
                useful_m3 = v["acopio"] / K["acopio"] + v["caliza"]
                waste_t = sum(v[c] * RHO[c] for c in ("montera", "arcilla", "muro"))
                useful_t = v["acopio"] * RHO["acopio"] / K["acopio"] + v["caliza"] * RHO["caliza"]
                group = result.group(domain)
                self.assertClose(group.waste_m3, waste_m3)
                self.assertClose(group.useful_m3, useful_m3)
                self.assertClose(group.waste_t, waste_t)
                self.assertClose(group.useful_t, useful_t)
                self.assertClose(group.total_t, waste_t + useful_t)
                self.assertEqual(group.total_notes, ())
                self.assertClose(group.ratio_m3.value, waste_m3 / useful_m3)
                self.assertClose(group.ratio_t.value, waste_t / useful_t)
                self.assertEqual((group.ratio_m3.notes, group.ratio_t.notes), ((), ()))
        bench = result.group(tonnage.ALL_DOMAINS, BENCH)
        self.assertClose(bench.ratio_m3.value, (800.0 * 0.175 + 525.0) / (800.0 * 0.825))
        self.assertIs(result.total, result.group())

    def test_intrinsic_ratio_of_a_compound(self) -> None:
        """RF-011-18: la relación intrínseca de la capa útil, sus componentes estériles frente a
        los útiles: 17,5/82,5 en m³/m³ y (17,5·ρ arcilla)/(82,5·ρ caliza) en t/t; suelta, con
        V/K y V·ρ/K (D-28); sin la densidad de un componente, sin la de t/t."""
        result = tonnage.tonnage(_volumes(), _column(), _params())
        self.assertEqual([item.unit for item in result.intrinsic], ["capa_util"])
        intrinsic = result.intrinsic_of("capa_util")
        self.assertClose(intrinsic.ratio_m3.value, 17.5 / 82.5)
        self.assertClose(intrinsic.ratio_t.value,
                         (17.5 * RHO["arcilla"]) / (82.5 * RHO["caliza"]))
        loose_column = _column()
        units = list(loose_column.units)
        units[2] = dataclasses.replace(units[2], state="loose")
        loose = tonnage.tonnage(_volumes(), MaterialColumn(tuple(units)), _params())
        intrinsic = loose.intrinsic_of("capa_util")
        self.assertClose(intrinsic.ratio_m3.value,
                         (17.5 / K["arcilla"]) / (82.5 / K["caliza"]))
        self.assertClose(intrinsic.ratio_t.value,
                         (17.5 * RHO["arcilla"] / K["arcilla"])
                         / (82.5 * RHO["caliza"] / K["caliza"]))
        missing = tonnage.tonnage(_volumes(), _column(), _params(density_arcilla=None))
        intrinsic = missing.intrinsic_of("capa_util")
        self.assertEqual(intrinsic.ratio_t, tonnage.Ratio(None, (NO_DENSITY,)))
        self.assertClose(intrinsic.ratio_m3.value, 17.5 / 82.5)

    def test_without_useful_material(self) -> None:
        """RF-011-18: sin material útil, «sin material útil» en lugar de un número (en un
        dominio sin útil, en una columna sin útil y en una compuesta sin componentes útiles),
        también si falta una densidad."""
        result = tonnage.tonnage(_volumes(), _column(), _params(density_montera=None))
        group = result.group("Fase 3")
        no_useful = tonnage.Ratio(None, (NO_USEFUL,))
        self.assertEqual((group.ratio_m3, group.ratio_t), (no_useful, no_useful))
        self.assertIsNone(group.total_t)
        waste_only = tonnage.tonnage(_volumes(), _column(clay_role="waste"), _params(
            percent_caliza=0.0, percent_arcilla=100.0))
        self.assertEqual(waste_only.intrinsic_of("capa_util").ratio_m3, no_useful)
        self.assertEqual(waste_only.intrinsic_of("capa_util").ratio_t, no_useful)
        self.assertEqual(waste_only.group("Fase 3").ratio_t, no_useful)
        self.assertIsNotNone(waste_only.total.ratio_t.value)  # el acopio es útil
        self.assertTrue(all(math.isfinite(group.ratio_t.value) for group in result.groups
                            if group.ratio_t.value is not None))


class MisuseTest(unittest.TestCase):
    """Lo que la operación nunca pasa es un error del programa."""

    def test_misuse(self) -> None:
        """Una unidad que no es de la columna, una fila repetida, un volumen no finito, un
        parámetro que no es un número positivo o una columna que no vale: errores del programa
        o de la columna, sin resultado."""
        column = _column()
        cases = {
            "unidad desconocida": ([UnitVolume("*", None, "otra", 1.0)], _params()),
            "repetida": ([UnitVolume("*", None, "muro", 1.0)] * 2, _params()),
            "no finito": ([UnitVolume("*", None, "muro", math.nan)], _params()),
            "densidad 0": (_volumes(), _params(density_muro=0.0)),
            "K negativo": (_volumes(), _params(swell_acopio=-1.0)),
            "texto": (_volumes(), {**_params(), density_key("muro"): "2,45"}),
        }
        for name, (volumes, values) in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                tonnage.tonnage(volumes, column, values)
        invalid = MaterialColumn((Unit("muro", "", "natural", "waste", "in_situ"),))
        with self.assertRaises(materials.MaterialsError):
            tonnage.tonnage([], invalid, {})


if __name__ == "__main__":
    unittest.main()
