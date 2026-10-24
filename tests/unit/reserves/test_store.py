# SPDX-License-Identifier: GPL-3.0-or-later
"""La cubicación en el proyecto (spec 011, T14; RF-011-05, RF-011-20, RF-011-21, RF-011-22,
RF-011-25; plan 011 §5.2.3, A11, D-16, D-30).

Sobre el proyecto de ``tests.support.res_fixtures`` (las superficies de la columna sintética
como rejillas del proyecto, V01 y V02 en BORRADOR; una copia por clase) con las declaraciones
de ``res`` registradas a mano: la columna se guarda con ``res.edit_materials`` (una operación
del proyecto), las densidades, los K y los porcentajes sintéticos se declaran en el proyecto y
el K de la montera, además, solo en V01. Cada prueba usa sus nombres de cubicación.
"""

from __future__ import annotations

import hashlib
import json
import math
import unittest
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import res_fixtures as fx
from tests.support.package import import_geoblender

provenance = import_geoblender("reserves.provenance")
store = import_geoblender("reserves.store")
table = import_geoblender("reserves.table")
volumes = import_geoblender("reserves.volumes")
surfaces = import_geoblender("reserves.surfaces")
materials = import_geoblender("reserves.materials")
params = import_geoblender("reserves.params")
operations = import_geoblender("core.provenance.operations")
figures_mod = import_geoblender("core.provenance.figures")
registry = import_geoblender("core.datasets.registry")
readers = import_geoblender("core.content.readers")
versions_model = import_geoblender("core.versions.model")
gis_content = import_geoblender("gis.content")
gis_messages = import_geoblender("gis.messages")

TINY_S = 1e-9
"""Un presupuesto de paso diminuto: cada paso hace una sola unidad de trabajo."""
START = surfaces.SurfaceRef(dataset=fx.START_GRID, label="Partida")
FINAL = surfaces.SurfaceRef(dataset=fx.FINAL_GRID, label="Final")
FLOOR = surfaces.SurfaceRef(elevation=600.0, label="Cota 600")
K_V01 = 1.30
"""El K de la montera solo en V01 (el del proyecto, el de la columna sintética: 1,25)."""


def _drain(steps: Iterator[Any]) -> Any:
    """El último paso de ``steps`` (el que lleva el resultado)."""
    last = None
    for last in steps:
        pass
    return last


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StoreTest(fx.ResProjectCase):
    """``res.volume``, ``res.tonnage`` y ``res.difference`` en V01 y lo que no dejan."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.column = fx.project_column()
        cls.declare(fx.column_values())
        cls.declare({params.swell_key("montera"): K_V01}, version=cls.v1)
        handle = operations.begin_operation(cls.project, provenance.EDIT_MATERIALS,
                                            settings={"units": len(cls.column.units)},
                                            executor="blender")
        cls.materials = store.save_materials(cls.project, handle, cls.column)

    # --- Ayudas -----------------------------------------------------------------------------

    def begin(self, op_type: str, request: Any = None, *, version: Any,
              supersedes: str | None = None) -> Any:
        """La operación ``op_type`` «en curso» con lo que anotan sus ayudas de
        ``reserves.provenance`` (la cubicación ``request``; en ``res.tonnage``, su nombre)."""
        if op_type == provenance.TONNAGE:
            values = {"settings": provenance.tonnage_settings(request),
                      "inputs": provenance.tonnage_inputs(request),
                      "params": provenance.tonnage_params(self.column)}
        else:
            values = {"settings": provenance.volume_settings(request),
                      "inputs": provenance.volume_inputs(request),
                      "params": provenance.volume_params(request)}
        self.clock.advance(minutes=1)
        return operations.begin_operation(self.project, op_type, executor="blender",
                                          version=version, supersedes=supersedes, **values)

    def operation(self, uid: str) -> dict[str, Any]:
        columns = ("status", "status_reason", "revision_uid", "superseded_by", "scope")
        (row,) = self.query(f"SELECT {', '.join(columns)} FROM gb_operation WHERE uid = ?", uid)
        return dict(zip(columns, row, strict=True))

    def consumed(self, uid: str) -> dict[str, tuple[str, str]]:
        """Papel → (uid, hash) de lo que anotó la operación ``uid`` al empezar."""
        return {role: (item, sha) for item, sha, role in self.query(
            "SELECT item_uid, content_sha256, role FROM gb_operation_io WHERE "
            "operation_uid = ? AND direction = 'in'", uid)}

    def read_params(self, uid: str) -> dict[str, tuple[str, str, int, Any]]:
        """Clave → (ámbito, versión, revisión, valor) de los parámetros que anotó la operación
        ``uid`` (``gb_operation_param`` con su fila de ``gb_parameter``)."""
        return {key: (scope, scope_uid, rev, json.loads(value)) for key, scope, scope_uid, rev,
                value in self.query(
                    "SELECT p.key, p.scope, g.scope_uid, p.rev, p.value FROM gb_operation_param "
                    "AS p JOIN gb_parameter AS g ON g.uid = p.parameter_uid WHERE "
                    "p.operation_uid = ?", uid)}

    def figures(self, uid: str) -> dict[tuple[str, str], tuple[float, str, str]]:
        """(clave, ámbito JSON) → (valor, unidad, tipo) de las cifras de la operación ``uid``."""
        return {(key, scope): (value, unit, kind) for key, scope, value, unit, kind in self.query(
            "SELECT key, scope, value, unit, kind FROM gb_figure WHERE operation_uid = ?", uid)}

    def hashes(self, names: Iterable[str]) -> dict[str, tuple[str, str | None]]:
        """El hash de contenido de cada dato del proyecto ``names`` y la huella de su fichero."""
        found: dict[str, tuple[str, str | None]] = {}
        for name in names:
            record = self.record(name)
            path = self.root.joinpath(*record.locator.split("/"))
            found[name] = (record.content_sha256, _sha(path) if path.is_file() else None)
        return found

    def assertLeftNothing(self, handle: Any, name: str, status: str) -> None:  # noqa: N802
        """RF-011-25: la operación ``handle`` quedó ``status`` con su motivo y de la cubicación
        ``name`` no queda ninguna cifra, tabla, dato, rejilla ni temporal."""
        state = self.operation(handle.uid)
        self.assertEqual(state["status"], status)
        self.assertTrue(state["status_reason"])
        self.assertEqual(self.figures(handle.uid), {})
        names = [provenance.dataset_name(family, name)
                 for family in (provenance.VOLUMES, provenance.DIFFERENCE_GRID)]
        self.assertEqual(self.query(
            f"SELECT name FROM gb_dataset WHERE name IN ({', '.join('?' for _ in names)})",
            *names), [])
        self.assertEqual(self.query("SELECT table_name FROM gpkg_contents WHERE "
                                    "table_name LIKE ?", f"{names[0]}%"), [])
        self.assertEqual(sorted(path.name for path in (self.root / "rasters").iterdir()
                                if path.name.startswith(names[1]) or ".tmp-" in path.name), [])
        self.assertEqual(operations.claimed_paths(self.project), frozenset())

    # --- Pruebas ----------------------------------------------------------------------------

    def test_volume_and_tonnage_in_v01(self) -> None:
        """RF-011-20, RF-011-21, RF-011-22 (D-16): ``res.volume`` y ``res.tonnage`` son dos
        operaciones encadenadas de la revisión abierta de V01, con sus entradas (con su hash y
        su papel), sus parámetros anotados (ámbito y revisión: el K de la montera, de V01; el
        del muro y las densidades, del proyecto), su tabla de la versión con sus títulos y sus
        cifras CALCULADO con su ámbito; las entradas no cambian de hash. RF-011-18, RF-011-19
        (T24, D-35): la cubicación sale entre las de V01 (por nombre, con unidades y sus
        toneladas) y sus filas de relaciones son las de su tabla de toneladas."""
        name = "Mensual octubre"
        inputs = [*fx.PROJECT_GRIDS, provenance.MATERIALS]
        before = self.hashes(inputs)
        request = volumes.VolumeRequest(name, START, FINAL, column=self.column)
        handle = self.begin(provenance.VOLUME, request, version=self.v1.uid)
        stored = _drain(store.volume_run(self.project, handle, request)).result
        result = stored.result
        (revision,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND "
                                 "state = 'open'", self.v1.uid)
        state = self.operation(handle.uid)
        self.assertEqual((state["status"], state["scope"], state["revision_uid"]),
                         ("done", "version", revision[0]))
        roles = {"start": fx.START_GRID, "final": fx.FINAL_GRID,
                 "materials": provenance.MATERIALS}
        for unit in self.column.units:
            for ref, role in ((unit.base, volumes.base_role(unit.code)),
                              (unit.thickness, volumes.thickness_role(unit.code))):
                if ref is not None:
                    roles[role] = ref.dataset
        self.assertEqual(self.consumed(handle.uid), {
            role: (self.record(item).uid, self.record(item).content_sha256)
            for role, item in roles.items()})
        self.assertEqual(sorted(self.read_params(handle.uid).items()),
                         [(params.ANTHROPIC_PRESENCE, ("project", "", 1, 0.3)),
                          (params.MIN_THICKNESS, ("project", "", 1, 0.0))])

        record = self.record(provenance.dataset_name(provenance.VOLUMES, name), self.v1)
        self.assertEqual((record.locator, record.kind, record.operation_uid),
                         ("res_vol_mensual_octubre_v01", "table", handle.uid))
        self.assertIsNone(self.record(record.name))  # de V01, no del proyecto
        self.assertEqual(dict(self.query("SELECT column_name, name FROM gpkg_data_columns "
                                         "WHERE table_name = ?", record.locator)),
                         dict(table.TITLES))
        with self.project.read() as conn:
            self.assertEqual(table.read_rows(conn, record.locator), result.rows)
            self.assertEqual(registry.content_digest(conn, self.project, record).content_sha256,
                             record.content_sha256)
        found = self.figures(handle.uid)
        self.assertEqual(found, {
            (spec.key, figures_mod.scope_json(spec.scope)): (spec.value, spec.unit, "CALCULADO")
            for spec in result.figures})
        whole = json.dumps({"cubication": name}, ensure_ascii=False, separators=(",", ":"))
        case = fx.material_column()
        self.assertTrue(math.isclose(found[("res.cut_m3", whole)][0], case.cut_m3,
                                     rel_tol=1e-12))

        tonnage = self.begin(provenance.TONNAGE, name, version=self.v1.uid)
        weighed = _drain(store.tonnage_run(self.project, tonnage)).result
        materials_record = self.record(provenance.MATERIALS)  # del proyecto (D-12)
        self.assertEqual(materials_record.operation_uid, self.materials[0].operation_uid)
        with self.project.read() as conn:
            self.assertEqual(materials.read_column(conn), self.column)
        self.assertEqual(self.consumed(tonnage.uid), {
            "volumes": (record.uid, record.content_sha256),
            "materials": (materials_record.uid, materials_record.content_sha256)})
        read = self.read_params(tonnage.uid)
        self.assertEqual(set(read), set(provenance.tonnage_params(self.column)))
        self.assertEqual(read[params.swell_key("montera")], ("version", self.v1.uid, 1, K_V01))
        self.assertEqual(read[params.swell_key("muro")], ("project", "", 1, 1.45))
        self.assertEqual(read[params.density_key("montera")], ("project", "", 1, 2.0))
        weighed_record = self.record(provenance.dataset_name(provenance.TONNES, name), self.v1)
        self.assertEqual((weighed_record.locator, weighed_record.operation_uid),
                         ("res_ton_mensual_octubre_v01", tonnage.uid))
        values = {**fx.column_values(), params.swell_key("montera"): K_V01}
        expected = volumes.tonnage_outputs(result.rows, self.column, values, name=name)
        self.assertEqual(weighed.outputs.rows, expected.rows)
        found = self.figures(tonnage.uid)
        self.assertEqual(len(found), len(expected.figures))
        self.assertEqual(found[("res.total_t", whole)][0], expected.result.total.total_t)
        self.assertEqual(self.hashes(inputs), before)

        # T24 (RF-011-18, RF-011-19, D-35): las cubicaciones de la versión (sus tablas de
        # volúmenes vivas, no una diferencia) y las filas de relaciones de su tabla de toneladas
        listed = {item.name: item for item in store.cubications(self.project, version="V01")}
        self.assertEqual((listed[name].record.uid, listed[name].operation_uid,
                          listed[name].units, listed[name].tonnage.uid),
                         (record.uid, handle.uid, True, weighed_record.uid))
        self.assertNotIn("Diferencia octubre", listed)  # res.difference: sin tabla
        self.assertEqual(list(listed), sorted(listed, key=str.casefold))
        ratios = store.cubication_ratios(self.project, name, version=self.v1.uid)
        self.assertEqual(ratios, table.ratio_rows(expected.rows))
        self.assertEqual({item.quantity for item in ratios}, set(table.RATIO_QUANTITIES))
        (total,) = table.filter_rows(ratios, domain="*", bench=None, unit=None,
                                     quantity="waste_ratio_m3")
        self.assertEqual(total.value, expected.result.total.ratio_m3.value)
        with self.assertRaises(import_geoblender("reserves.messages").ResError) as caught:
            store.cubication_ratios(self.project, "Ninguna", version=self.v1.uid)
        self.assertEqual(caught.exception.code, "res.cubication_unknown")

    def test_difference_grid_of_the_version(self) -> None:
        """RF-011-05, RF-011-20, RF-011-22: ``res.difference`` deja la rejilla de V01
        (``rasters/res_dif_<nombre>_v01.tif``, con el hash que da su lector) y sus seis cifras
        de totales con el ámbito de la diferencia; ninguna tabla ni temporal."""
        name = "Diferencia octubre"
        request = volumes.VolumeRequest(name, START, FINAL, difference_grid=True)
        handle = self.begin(provenance.DIFFERENCE, request, version=self.v1.code)
        result = _drain(store.volume_run(self.project, handle, request)).result.result
        record = self.record(provenance.dataset_name(provenance.DIFFERENCE_GRID, name), self.v1)
        self.assertEqual((record.locator, record.kind, record.operation_uid),
                         ("rasters/res_dif_diferencia_octubre_v01.tif", "raster", handle.uid))
        path = self.root.joinpath(*record.locator.split("/"))
        reader = gis_content.GEOTIFF
        digest = readers.read_content(reader, reader.request("raster", {}, {"main": path}))
        self.assertEqual(digest.content_sha256, record.content_sha256)
        scope = json.dumps({"difference": name}, ensure_ascii=False, separators=(",", ":"))
        kernel = result.kernel
        self.assertEqual(self.figures(handle.uid), {
            (key, scope): (float(getattr(kernel, key.removeprefix("res."))[0]),
                           "m2" if key.endswith("m2") else "m3", "CALCULADO")
            for key in provenance.DIFFERENCE_FIGURES})
        self.assertIsNone(self.record(provenance.dataset_name(provenance.VOLUMES, name),
                                      self.v1))
        self.assertEqual([p.name for p in path.parent.iterdir() if ".tmp-" in p.name], [])

    def test_needs_an_editable_version(self) -> None:
        """RF-011-20 (RF-009-05, RF-009-04): sin versión activa, ``core.version_required``; en
        una SUPERADO, su texto; ninguna de las dos registra nada."""
        request = volumes.VolumeRequest("Sin versión", START, FINAL)
        count = self.query("SELECT count(*) FROM gb_operation")
        with self.assertRaises(versions_model.VersionError) as caught:
            self.begin(provenance.VOLUME, request, version=None)
        self.assertEqual(caught.exception.code, "core.version_required")
        with self.project.write_transaction() as conn:  # V02 VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?",
                         (self.v2.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", ("Prueba de la 011", self.v2.uid))
        with self.assertRaises(versions_model.VersionError) as caught:
            self.begin(provenance.VOLUME, request, version=self.v2.uid)
        self.assertEqual(caught.exception.text,
                         "V02 está en estado SUPERADO: cree una versión nueva a partir de ella")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), count)

    def test_cancel_or_fail_leave_nothing(self) -> None:
        """RF-011-25: cerrar los pasos mientras se escribe la rejilla (Esc) deja la operación
        «cancelada» y fallar al confirmar, con la rejilla ya en su sitio, «fallida», con su
        motivo; ninguna de las dos deja cifra, tabla, dato, rejilla ni temporal."""
        rasters = sorted((self.root / "rasters").iterdir())
        name = "Cancelada"
        request = volumes.VolumeRequest(name, START, FINAL, difference_grid=True)
        handle = self.begin(provenance.VOLUME, request, version=self.v1.uid)
        steps = store.volume_run(self.project, handle, request, budget_s=TINY_S)
        for step in steps:
            if step.phase == "grid":
                break
        self.assertTrue(any(".tmp-" in path.name for path in (self.root / "rasters").iterdir()))
        steps.close()
        self.assertLeftNothing(handle, name, "cancelled")

        name = "Fallida"
        request = volumes.VolumeRequest(name, START, FINAL, difference_grid=True)
        handle = self.begin(provenance.VOLUME, request, version=self.v1.uid)
        with mock.patch.object(operations.OperationHandle, "complete",
                               side_effect=RuntimeError("fallo simulado al confirmar")):
            with self.assertRaisesRegex(RuntimeError, "fallo simulado"):
                _drain(store.volume_run(self.project, handle, request))
        self.assertLeftNothing(handle, name, "failed")
        self.assertIn("fallo simulado", self.operation(handle.uid)["status_reason"])
        self.assertEqual(sorted((self.root / "rasters").iterdir()), rasters)

    def test_locked_grid_keeps_the_previous(self) -> None:
        """RF-011-25 (D-30): repetir una diferencia con su rejilla abierta en otro programa da
        ``gis.raster_target_locked``; la nueva queda «fallida» y la anterior, su rejilla, su
        dato y sus cifras siguen como estaban, sin temporales."""
        name = "Bloqueada"
        request = volumes.VolumeRequest(name, START, FINAL, difference_grid=True)
        first = self.begin(provenance.DIFFERENCE, request, version=self.v1.uid)
        _drain(store.volume_run(self.project, first, request))
        record = self.record(provenance.dataset_name(provenance.DIFFERENCE_GRID, name), self.v1)
        path = self.root.joinpath(*record.locator.split("/"))
        sha, figures = _sha(path), self.figures(first.uid)
        previous = store.previous_operation(self.project, provenance.DIFFERENCE, name,
                                            version=self.v1.uid)
        self.assertEqual(previous, first.uid)
        again = volumes.VolumeRequest(name, START, FLOOR, difference_grid=True)
        second = self.begin(provenance.DIFFERENCE, again, version=self.v1.uid,
                            supersedes=previous)
        with path.open("rb"), self.assertRaises(gis_messages.GisError) as caught:
            _drain(store.volume_run(self.project, second, again))
        self.assertEqual(caught.exception.code, "gis.raster_target_locked")
        state = self.operation(second.uid)
        self.assertEqual(state["status"], "failed")
        self.assertIn(path.name, state["status_reason"])
        self.assertEqual(self.figures(second.uid), {})
        self.assertIsNone(self.operation(first.uid)["superseded_by"])
        self.assertEqual(self.record(record.uid), record)
        self.assertEqual((_sha(path), self.figures(first.uid)), (sha, figures))
        self.assertEqual([p.name for p in path.parent.iterdir() if ".tmp-" in p.name], [])

    def test_same_name_replaces_the_previous(self) -> None:
        """D-30 (RF-011-20): repetir el nombre de una cubicación de V01 sustituye a la anterior:
        el mismo dato y la misma tabla con el contenido nuevo, y la anterior, sustituida."""
        name = "Repetida"
        request = volumes.VolumeRequest(name, START, FINAL)
        first = self.begin(provenance.VOLUME, request, version=self.v1.uid)
        _drain(store.volume_run(self.project, first, request))
        before = self.record(provenance.dataset_name(provenance.VOLUMES, name), self.v1)
        previous = store.previous_operation(self.project, provenance.VOLUME, name,
                                            version=self.v1.uid)
        again = volumes.VolumeRequest(name, START, FLOOR)
        second = self.begin(provenance.VOLUME, again, version=self.v1.uid, supersedes=previous)
        result = _drain(store.volume_run(self.project, second, again)).result.result
        after = self.record(before.uid)
        self.assertEqual((after.uid, after.locator, after.operation_uid),
                         (before.uid, before.locator, second.uid))
        self.assertNotEqual(after.content_sha256, before.content_sha256)
        self.assertEqual(self.operation(first.uid)["superseded_by"], second.uid)
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE name = ?",
                                    before.name), [(1,)])
        with self.project.read() as conn:
            self.assertEqual(table.read_rows(conn, after.locator), result.rows)


if __name__ == "__main__":
    unittest.main()
