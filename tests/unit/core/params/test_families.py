# SPDX-License-Identifier: GPL-3.0-or-later
"""Familias de parámetros (spec 011, T04; RF-011-11, RF-011-21; ADR-0027; plan 011 §5.3.2 y
D-17; RF-008-01 a RF-008-06, RF-008-60, RF-009-24).

La densidad, el K y los porcentajes de cada unidad de la columna de materiales son parámetros
por **elemento de un dato**: sus claves no se conocen al registrar el módulo. ``core.params``
admite **familias** (``ParamFamily(pattern, template)``, con segmentos variables entre llaves
que casan con ``[a-z][a-z0-9_]*``), que su módulo registra con ``register_families`` y quita con
``unregister_families``; ``definition(key)`` da la registrada con esa clave o la de la familia
que casa, con la clave concreta. Una clave concreta es una definición declarada a todos los
efectos (ADR-0027, punto 3):

- se crea, se cambia, se confirma, anota su historial y su ``def_sha256`` (el de la definición
  concreta), sale en la lista del módulo y se resuelve versión → proyecto si su familia es
  ``scope="version"`` (RF-011-21, RF-009-24);
- la comprobación de apertura (``core.provenance.checks``, con ``Registries.installed()``) no
  la marca «revisar» con su familia registrada, y sí sin ella (RF-008-60);
- una clave que no casa sigue siendo ``core.param_undefined``; registrar dos veces, un patrón
  mal formado o que solapa es un ``ValueError``; quitar las familias de un módulo no deja nada.

Familias de prueba de ``res`` (como las de la 011: ``res.unit.{u}.density`` del proyecto y sin
valor por defecto, D-8; ``res.unit.{u}.swell`` y ``res.unit.{u}.{c}.percent`` de versión, D-11),
con valores sintéticos. Un solo proyecto (esquema 3) con la versión V01 para todas las pruebas
del almacén, cada una con sus propias unidades: crear un proyecto cuesta (presupuesto de
``check.py``).
"""

from __future__ import annotations

import dataclasses
import sqlite3
import unittest
from collections.abc import Callable
from typing import Any

from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
params = import_geoblender("core.params")
store_mod = import_geoblender("core.params.store")
checks = import_geoblender("core.provenance.checks")
versions_store = import_geoblender("core.versions.store")

ParamDef = params.ParamDef
ParamFamily = params.ParamFamily
SESSION = make_session()

DENSITY = ParamFamily("res.unit.{u}.density", ParamDef(
    "res.unit.u.density", "float", "t/m3", None, 0.0, 10.0, ("RF-011-11",),
    "Prueba: sin densidad por defecto (D-8)", min_exclusive=True, allow_empty=True,
    kind="HIPÓTESIS", source_kind="document", label_msgid="In-situ density",
))
"""Del proyecto (D-11), sin valor por defecto."""
SWELL = ParamFamily("res.unit.{u}.swell", ParamDef(
    "res.unit.u.swell", "float", "-", None, 1.0, 3.0, ("RF-011-11", "RF-011-21"),
    "Prueba: sin K por defecto (D-8)", allow_empty=True, kind="HIPÓTESIS",
    source_kind="document", scope="version", label_msgid="Swell factor",
))
"""De versión (D-11, RF-011-21)."""
PERCENT = ParamFamily("res.unit.{u}.{c}.percent", ParamDef(
    "res.unit.u.c.percent", "float", "%", None, 0.0, 100.0, ("RF-011-15", "RF-011-21"),
    "Prueba: sin porcentaje por defecto", allow_empty=True, kind="HIPÓTESIS",
    source_kind="document", scope="version", label_msgid="Share of the component",
))
"""De versión, con dos segmentos variables (unidad y componente)."""
FAMILIES = (DENSITY, SWELL, PERCENT)
RECOVERY = ParamDef("res.recovery", "float", "-", 0.9, 0.0, 1.0, ("RF-008-01",),
                    "Prueba: recuperación minera")
"""Una clave fija de ``res`` (sin familia)."""

BY_HAND: dict[str, Any] = {
    "source": "Ensayo de laboratorio", "source_kind": "document",
    "decided_by": "Samuel (IMGA)",
}


def family(pattern: str, key: str | None = None, *, module_key: str | None = None) -> Any:
    """Una familia con la plantilla de la densidad y la clave ``key`` (o ``module_key``)."""
    template = dataclasses.replace(DENSITY.template, key=module_key or key or "res.x")
    return ParamFamily(pattern, template)


class FamilyModelTest(unittest.TestCase):
    """ADR-0027, puntos 1 a 4: casar una clave, registrar y quitar, patrones mal formados y
    solapados (sin proyecto)."""

    def setUp(self) -> None:
        params.register_families(FAMILIES)
        self.addCleanup(params.unregister_families, "res")
        self.addCleanup(params.unregister_definitions, "res")

    def test_a_concrete_key_is_a_declared_definition(self) -> None:
        """RF-011-11, ADR-0027 (3): ``definition`` da la de la familia con la clave concreta
        (la plantilla con esa clave: su tipo de valor, unidad, rango, «sin valor», tipo y
        ámbito), la registrada antes que ninguna familia y ``None`` si nada casa;
        ``DEFINITIONS`` sigue siendo lo registrado; la etiqueta es la de la plantilla con los
        segmentos variables (punto 4); un valor fuera de rango se rechaza con la clave
        concreta."""
        key = "res.unit.capa_util.density"
        defn = params.definition(key)
        self.assertEqual(defn, dataclasses.replace(DENSITY.template, key=key))
        self.assertEqual((defn.key, defn.module, defn.scope, defn.default, defn.kind),
                         (key, "res", "project", None, "HIPÓTESIS"))
        self.assertIs(params.definition(key), defn)  # memorizada
        self.assertEqual(params.definition("res.unit.capa_util.caliza.percent").scope,
                         "version")
        self.assertEqual(params.definition("res.unit.montera.swell").unit, "-")
        self.assertNotIn(key, params.DEFINITIONS)
        self.assertEqual(dict(params.FAMILIES), {f.pattern: f for f in FAMILIES})
        self.assertEqual(DENSITY.match(key), ("capa_util",))
        self.assertEqual(PERCENT.match("res.unit.capa_util.caliza.percent"),
                         ("capa_util", "caliza"))
        for other in ("res.unit.Capa.density", "res.unit.capa-util.density", "res.unit.density",
                      "res.unit.1capa.density", "res.unit.capa_util.density.extra",
                      "res.unidad.capa_util.density", "gis.unit.capa_util.density", "",
                      "res.unit..density", None, 7):
            with self.subTest(key=other):
                self.assertIsNone(params.definition(other))
        params.register_definitions((RECOVERY,))
        self.assertIs(params.definition("res.recovery"), RECOVERY)
        self.assertEqual(params.parameter_label("res.unit.capa_util.caliza.percent", "en"),
                         "Share of the component · capa_util · caliza")
        self.assertEqual(params.parameter_label(key, "en"), "In-situ density · capa_util")
        self.assertIsNone(params.parameter_label("res.recovery", "en"))  # sin etiqueta
        self.assertIsNone(params.parameter_label("res.unidad.capa_util.density", "en"))
        with self.assertRaises(params.ParamError) as caught:
            defn.check(12.0)
        self.assertEqual((caught.exception.code, caught.exception.key),
                         ("core.param_out_of_range", key))

    def test_register_twice_malformed_or_overlapping_is_a_value_error(self) -> None:
        """ADR-0027 (1, 2): registrar dos veces, un patrón mal formado, de otro módulo o que
        solapa con una clave o una familia registradas es un ``ValueError`` (y no se registra
        nada del lote); una clave fija que casa con una familia registrada, también; lo que no
        es una familia, ``TypeError``."""
        extra = family("res.part.{u}.mass", "res.part.u.mass")
        with self.assertRaisesRegex(ValueError, r"res\.unit\.\{u\}\.density"):
            params.register_families((extra, DENSITY))
        self.assertNotIn(extra.pattern, params.FAMILIES)
        with self.assertRaisesRegex(ValueError, r"res\.part"):
            params.register_families((extra, extra))
        self.assertNotIn(extra.pattern, params.FAMILIES)
        for overlapping in (family("res.unit.{x}.density", "res.unit.x.density"),
                            family("res.unit.{u}.{c}", "res.unit.u.c"),
                            family("res.{a}.capa_util.{b}", "res.a.capa_util.b")):
            with self.subTest(pattern=overlapping.pattern), \
                    self.assertRaisesRegex(ValueError, "solapa"):
                params.register_families((overlapping,))
        params.register_definitions((RECOVERY,))
        with self.assertRaisesRegex(ValueError, "res.recovery"):
            params.register_families((family("res.{name}", "res.name"),))
        with self.assertRaisesRegex(ValueError, r"res\.unit\.\{u\}\.density"):
            params.register_definitions((dataclasses.replace(RECOVERY,
                                                             key="res.unit.acopio.density"),))
        self.assertIsNone(params.definition("res.unit.acopio.density").default)
        for malformed in ("res.unit.density", "res.unit.{U}.density", "res.unit.{u}x.density",
                          "res.unit.{}.density", "res.{u}.{u}.density", "{m}.unit.{u}",
                          "xyz.unit.{u}", "res..{u}", "res.unit.{u}.Density", "res",
                          "res.unit.{u}.density "):
            with self.subTest(pattern=malformed), self.assertRaises(ValueError):
                family(malformed)
        with self.assertRaisesRegex(ValueError, "otro módulo"):
            family("res.unit.{u}.density", module_key="gis.unit.u.density")
        with self.assertRaisesRegex(ValueError, "no casa"):
            ParamFamily("res.unit.{u}.density", SWELL.template)
        with self.assertRaises(TypeError):
            ParamFamily("res.unit.{u}.density", {"key": "res.unit.u.density"})
        with self.assertRaises(TypeError):
            ParamFamily(7, DENSITY.template)
        with self.assertRaises(TypeError):
            params.register_families((DENSITY.template,))

    def test_unregistering_a_module_leaves_nothing(self) -> None:
        """ADR-0027 (2): ``unregister_families(módulo)`` quita todas las suyas y dice cuántas;
        repetirlo no hace nada; ninguna clave concreta sigue declarada."""
        self.assertEqual(params.unregister_families("gis"), 0)
        self.assertEqual(params.unregister_families("res"), 3)
        self.assertEqual(params.unregister_families("res"), 0)
        self.assertEqual(dict(params.FAMILIES), {})
        self.assertIsNone(params.definition("res.unit.capa_util.density"))
        self.assertIsNone(params.parameter_label("res.unit.capa_util.density", "en"))
        with self.assertRaises(TypeError):
            params.FAMILIES["res.unit.{u}.density"] = DENSITY  # type: ignore[index]


class FamilyStoreTest(unittest.TestCase):
    """RF-011-11, RF-011-21, RF-008-60: una clave concreta en ``ParameterStore`` y en la
    comprobación de apertura. Un proyecto para todas (``cls.project``) con la versión V01."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = cls.enterClassContext(project_tmp("gb-011-t04-"))
        parent = tmp / "proyectos"
        parent.mkdir()
        cls.clock = FakeClock()
        cls.project = create.create_project(
            parent, make_settings(), SESSION, userdata_mod.UserData(tmp / "u"), clock=cls.clock
        ).project
        cls.addClassCleanup(cls.project.close)
        cls.store = store_mod.ParameterStore(cls.project)
        with cls.project.write_transaction() as conn:
            cls.v1, _ = versions_store.create_version(
                conn, cls.project, feature="definitiva", title="Definitiva", reason="Prueba")

    def setUp(self) -> None:
        params.register_families(FAMILIES)
        self.addCleanup(params.unregister_families, "res")

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            return work(conn)

    def rejected(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.assertRaises(params.ParamError) as caught:
            self.write(work)
        return caught.exception

    def review_keys(self, registries: Any) -> dict[str, Any]:
        """Lo que la comprobación de apertura (en solo lectura) encuentra para «revisar»."""
        found = list(checks.survey_steps(self.project, registries, write=False))
        return {item.key: item.review for item in found[-1].result.definitions}

    def test_a_concrete_key_is_created_changed_and_confirmed_with_its_history(self) -> None:
        """RF-011-11, RF-008-01, RF-008-02, RF-008-04: ``res.unit.capa_util.density`` se
        registra sin valor y «sin confirmar», se confirma, se cambia (y se rechaza fuera de su
        rango) con su historial, con el ``def_sha256`` de su definición concreta (no el de la
        plantilla ni el de otra unidad); sale en la lista de ``res`` y una clave que no casa
        con ninguna familia sigue siendo ``core.param_undefined``."""
        key, other = "res.unit.capa_util.density", "res.unit.montera.density"
        store = self.store
        record = self.write(lambda conn: store.ensure_default(conn, key,
                                                              geoblender_version="0.3.0"))
        self.assertEqual((record.value, record.kind, record.unconfirmed, record.module),
                         (None, "HIPÓTESIS", True, "res"))
        sha = store_mod.definition_sha256(params.definition(key))
        self.assertEqual(record.def_sha256, sha)
        self.assertNotIn(sha, {store_mod.definition_sha256(DENSITY.template),
                               store_mod.definition_sha256(params.definition(other))})
        self.assertFalse(self.write(lambda conn: store.confirm(conn, key)).unconfirmed)
        changed = self.write(lambda conn: store.change(
            conn, key, value=2.65, kind="MEDIDO", **BY_HAND, reason="Ensayo de densidad"))
        self.assertEqual((changed.value, changed.unit, changed.kind, changed.def_sha256),
                         (2.65, "t/m3", "MEDIDO", sha))
        error = self.rejected(lambda conn: store.change(conn, key, value=12.0, reason="Error"))
        self.assertEqual((error.code, error.key), ("core.param_out_of_range", key))
        self.write(lambda conn: store.create(conn, other, 2.1, kind="ADOPTADO", **BY_HAND,
                                            reason="Bibliografía"))
        self.assertEqual([entry.action for entry in store.history(key)],
                         ["default", "confirm", "change"])
        listed = [row.record.key for row in store.list(params.ParameterFilter(module="res"))]
        self.assertIn(key, listed)
        self.assertIn(other, listed)
        with self.project.read() as conn:
            self.assertEqual(store.resolve(conn, key).value, 2.65)
        error = self.rejected(lambda conn: store.create(
            conn, "res.unidad.capa_util.density", 2.0, kind="ADOPTADO", **BY_HAND,
            reason="Sin familia"))
        self.assertEqual(error.code, "core.param_undefined")

    def test_a_version_family_resolves_version_then_project(self) -> None:
        """RF-011-21, RF-009-24: el K (familia de versión) se resuelve con el de V01 si lo
        tiene y si no con el del proyecto; un porcentaje se registra solo en la versión; la
        densidad (familia del proyecto) no admite valor por versión."""
        key, other = "res.unit.escombro.swell", "res.unit.acopio.swell"
        store = self.store
        for name, value in ((key, 1.3), (other, 1.25)):
            self.write(lambda conn, name=name, value=value: store.create(
                conn, name, value, kind="ADOPTADO", **BY_HAND, reason="Ensayo"))
        self.write(lambda conn: store.change(conn, key, value=1.45, kind="HIPÓTESIS",
                                             reason="Prueba de V01", version=self.v1.code))
        chain = ("version", "project")
        with self.project.read() as conn:
            here = store.resolve(conn, key, chain, version=self.v1.uid)
            there = store.resolve(conn, other, chain, version=self.v1.uid)
        self.assertEqual((here.value, here.scope, here.scope_uid), (1.45, "version", self.v1.uid))
        self.assertEqual((there.value, there.scope), (1.25, "project"))
        percent = "res.unit.escombro.caliza.percent"
        self.write(lambda conn: store.create(conn, percent, 82.5, kind="HIPÓTESIS", **BY_HAND,
                                             reason="Reparto de V01", version=self.v1.code))
        self.assertEqual(store.get(percent, version=self.v1.uid).value, 82.5)
        self.assertIsNone(store.get(percent))
        error = self.rejected(lambda conn: store.create(
            conn, "res.unit.escombro.density", 2.4, kind="ADOPTADO", **BY_HAND,
            reason="Densidad", version=self.v1.code))
        self.assertEqual(error.code, "core.param_project_only")

    def test_review_on_opening_with_and_without_the_family(self) -> None:
        """RF-008-60, ADR-0027 (3): con la familia registrada, la comprobación de apertura no
        marca «revisar» sus claves concretas (``Registries.installed()`` la lleva, copiada);
        sin ella, «ya no se declara»; con su plantilla cambiada, el cambio con la clave
        concreta; marcar con lo instalado no escribe nada."""
        key = "res.unit.muro.density"
        self.write(lambda conn: self.store.create(conn, key, 2.5, kind="ADOPTADO", **BY_HAND,
                                                  reason="Ensayo"))
        installed = checks.Registries.installed()
        self.assertEqual(dict(installed.families), dict(params.FAMILIES))
        self.assertEqual(self.review_keys(installed), {})
        self.assertEqual(self.write(lambda conn: self.store.mark_definition_changes(
            conn, params.DEFINITIONS, families=params.FAMILIES.values())), [])
        params.unregister_families("res")
        self.assertEqual(dict(installed.families), {f.pattern: f for f in FAMILIES})
        found = self.review_keys(checks.Registries.installed())
        self.assertIn(key, found)
        self.assertIsNone(found[key]["declared"])
        narrower = ParamFamily(DENSITY.pattern, dataclasses.replace(DENSITY.template,
                                                                    maximum=2.0))
        params.register_families((narrower, SWELL, PERCENT))
        found = self.review_keys(checks.Registries.installed())
        self.assertIn(key, found)
        self.assertTrue(all(name.endswith(".density") for name in found), list(found))
        self.assertEqual((found[key]["declared"]["key"], found[key]["declared"]["maximum"],
                          found[key]["problem"]["code"]),
                         (key, 2.0, "core.param_out_of_range"))
        self.assertEqual(self.review_keys(installed), {})


if __name__ == "__main__":
    unittest.main()
