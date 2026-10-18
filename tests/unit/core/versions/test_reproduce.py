# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproducir una revisión congelada (spec 009, T15; RF-009-11, RF-009-09; CE-009-02; plan 009
A9, §5.3.3, D-4, D-32 y T9).

Sobre el proyecto de la demostración de versiones (``tests/support/versions_fixtures.py``) con
tres revisiones **congeladas de verdad** (``core.versions.freeze.freeze_steps``): V01.r1 (el
hueco, su volumen, las rampas dibujadas a mano y los acopios en el hueco, con la cadena de la
008 aguas arriba), V03.r1 (V03 parte de V01.r1 y diseña con su tabla de bancos congelada,
``Use.frozen``) y V02.r1 (su volumen se calculó con un hueco de dos bancos que después se
rehízo con tres: lo que consumió no quedó congelado en ninguna parte y se aceptó así al
congelar). Se crea una vez por proceso y cada prueba trabaja en su copia.

``core.versions.reproduce.reproduce_steps`` comprueba antes, sin escribir nada, que la
revisión está congelada y no alterada, **todas sus huellas** (la comprobación entera de A8) y
el espacio en la caché; después vuelve a ejecutar en ``<caché>/reproducir/<revisión>-<8
hex>/``, en orden y cada una **con sus entradas y sus parámetros congelados** (no con lo
reproducido aguas arriba: D-32), las operaciones de los tipos que su módulo declara
reproducibles; de las demás (importaciones, ediciones a mano, tipos sin función de reproducir
o de un módulo que no está) toma lo congelado, y la que consumió algo que no se congeló es «no
reproducible». El informe dice qué salidas (hash de contenido, con el lector y el normalizador
de su dato) y qué cifras (exactas, salvo la tolerancia que declara su tipo) coinciden y, si no,
la causa probable (otra versión del algoritmo, de Geoblender o de una biblioteca; si no, «sin
causa conocida»), y se guarda en JSON en esa carpeta. **El proyecto no cambia**: ni un fichero
fuera de ``cache/``, ni la base (su contador de cambios), ni un evento.

Datos solo sintéticos.
"""

from __future__ import annotations

import atexit
import dataclasses
import json
import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from tests.support import provenance_data as data
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.core_fixtures import FakeClock
from tests.support.package import import_geoblender

reproduce = import_geoblender("core.versions.reproduce")
freeze = import_geoblender("core.versions.freeze")
model = import_geoblender("core.versions.model")
contract = import_geoblender("core.provenance.contract")
figures_mod = import_geoblender("core.provenance.figures")
open_mod = import_geoblender("core.project.open")
userdata_mod = import_geoblender("core.userdata")
paths = import_geoblender("core.paths")
version_mod = import_geoblender("core.version")

Why = reproduce.Why
TAKEN_V01 = (("core.import_layer", Why.IMPORT), ("demo.digitize", Why.MANUAL),
             ("demo.bench_years", Why.TYPE), ("demo.detect_stockpiles", Why.TYPE),
             ("demo.filter_stockpiles", Why.TYPE), ("demo.sketch", Why.MANUAL))
"""Lo que V01.r1 toma de lo congelado, en orden: la importación del límite, la cadena de la
008 aguas arriba de los acopios (lo dibujado a mano y los tipos que no se reproducen) y las
rampas dibujadas a mano."""
TAKEN_V01_TEXT = (
    "6 operaciones tomadas de lo congelado (core.import_layer, importación; demo.digitize, "
    "edición a mano; demo.bench_years, su tipo no se reproduce; demo.detect_stockpiles, su "
    "tipo no se reproduce; demo.filter_stockpiles, su tipo no se reproduce; demo.sketch, "
    "edición a mano)"
)
VOLUME_10_M = 3_182_000.0
"""El volumen del hueco sobre ``Limites_v1`` con bancos de 10 m (``versions_demo``)."""

_BASE_TEMPLATE = fixtures.template
_MADE: dict[str, Any] = {}


def _last(steps: Iterator[Any]) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


def _freeze(project: Any, version: str, reason: str, *, accept: bool = False) -> str:
    accepted = freeze.Acceptance.of(freeze.freeze_plan(project, version)) if accept else None
    outcome = _last(freeze.freeze_steps(project, version, reason=reason, accepted=accepted))
    if outcome is None or outcome.frozen is None:
        raise AssertionError(f"no se ha congelado {version}")
    return str(outcome.frozen.uid)


def reproduce_template() -> Mapping[str, Any]:
    """El proyecto de la demostración de versiones (:func:`fixtures.template`) con V01.r1,
    V03.r1 y V02.r1 congeladas (véase el módulo), creado (y cerrado) la primera vez que se pide
    en el proceso, con las claves de la plantilla más ``revisions`` (etiqueta → uid)."""
    if _MADE:
        return _MADE
    made = _BASE_TEMPLATE()
    folder = Path(tempfile.mkdtemp(prefix="gb-vr-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    for part in ("proyectos", "fuentes"):
        shutil.copytree(made["folder"] / part, folder / part)
    clock = FakeClock(made["now"])
    project = open_mod.open_project(folder / "proyectos" / made["name"], fixtures.SESSION,
                                    userdata_mod.UserData(folder / "u"), clock=clock,
                                    pid_alive=fixtures.PIDS).project
    revisions: dict[str, str] = {}
    try:
        with vdemo.VersionsDemo().registered() as demo:
            for work in (lambda: demo.pit(project, "V01"),
                         lambda: demo.pit_volume(project, "V01"),
                         lambda: demo.sketch(project, "V01"),
                         lambda: demo.pit_stockpiles(project, "V01")):
                clock.advance(minutes=1)
                work()
            clock.advance(minutes=1)
            revisions["V01.r1"] = _freeze(project, "V01", "Entrega")
            clock.advance(minutes=1)
            fixtures.create_version(project, feature="desde_v01", title="Desde V01",
                                    parent="V01")
            clock.advance(minutes=1)
            demo.design_from_parent(project, "V03", frozen=revisions["V01.r1"])
            clock.advance(minutes=1)
            revisions["V03.r1"] = _freeze(project, "V03", "Diseño")
            for work in (lambda: demo.pit(project, "V02", benches=2),
                         lambda: demo.pit_volume(project, "V02"),
                         lambda: demo.pit(project, "V02")):
                clock.advance(minutes=1)
                work()
            clock.advance(minutes=1)
            revisions["V02.r1"] = _freeze(project, "V02", "Ampliación", accept=True)
    finally:
        project.close()
    _MADE.update(made, folder=folder, now=clock.now(), revisions=revisions)
    return _MADE


class ReproduceCase(fixtures.VersionsProjectCase):
    """Una copia del proyecto con las revisiones congeladas (:func:`reproduce_template`)."""

    tmp_prefix = "gb-vr-"

    def setUp(self) -> None:
        with mock.patch.object(fixtures, "template", reproduce_template):
            super().setUp()
        self.revisions: dict[str, str] = dict(reproduce_template()["revisions"])

    # --- Ayudas -----------------------------------------------------------------------------

    def state(self) -> tuple[Any, ...]:
        """Lo que no puede cambiar al reproducir: cada fichero del proyecto fuera de
        ``cache/`` (también la base, su diario y la cabecera) con su tamaño, su huella y su
        fecha, y el contador de cambios de la base."""
        return (self.files(skip=(), skip_dirs=("cache",)), self.change_counter())

    def cache_listing(self) -> list[str]:
        cache = Path(self.project.cache_dir())
        return sorted(path.relative_to(cache).as_posix() for path in cache.rglob("*")) \
            if cache.exists() else []

    def run_steps(self, revision: str, **kw: Any) -> tuple[Any, list[Any]]:
        """Reproduce ``revision`` (uid o etiqueta) hasta el final: su informe y sus pasos."""
        self.tick()
        steps = list(reproduce.reproduce_steps(self.project, revision, **kw))
        self.assertEqual([step.result is not None for step in steps].count(True), 1)
        self.assertIsNotNone(steps[-1].result)
        return steps[-1].result, steps

    def bench(self, value: float, version: str) -> None:
        """La altura de banco propia de ``version`` (``value`` m), un minuto después."""
        self.tick()
        self.write(lambda conn: self.store.change(
            conn, vdemo.BENCH_HEIGHT, value=value, source="Plan de labores (prueba)",
            decided_by="Dirección facultativa (prueba)", reason=f"Bancos de {value:g} m",
            version=version))

    def op_uids(self, op_type: str, version: str) -> list[str]:
        """Las operaciones de ``op_type`` de ``version``, en su orden."""
        return [str(row[0]) for row in self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "JOIN gb_version AS v ON v.uid = r.version_uid WHERE o.op_type = ? AND v.code = ? "
            "ORDER BY o.fid", (op_type, version))]

    def written(self, op_uid: str) -> dict[str, str]:
        """Lo que escribió la operación ``op_uid``: papel → hash de contenido."""
        return {str(role): str(sha) for role, sha in self.query(
            "SELECT role, content_sha256 FROM gb_operation_io WHERE operation_uid = ? "
            "AND direction = 'out'", (op_uid,))}

    def outputs(self, report: Any) -> dict[tuple[str, str], Any]:
        return {(check.op_type, check.role): check for check in report.outputs}

    def replace_operation(self, op_type: str, **changes: Any) -> None:
        """El tipo ``op_type`` registrado con ``changes`` (otra versión del algoritmo, otra
        función de reproducir) hasta el final de la prueba."""
        original = contract.OPERATIONS[op_type]
        contract.unregister_operation(op_type)
        contract.register_operation(dataclasses.replace(original, **changes))

        def restore() -> None:
            contract.unregister_operation(op_type)
            contract.register_operation(original)

        self.addCleanup(restore)

    def reproduce_with(self, change: Callable[[Any], Any]) -> Callable[[Any], Iterator[Any]]:
        """Una función de reproducir que es la de la demostración con ``change`` aplicado a su
        resultado (``ReproducedResult``)."""

        def again(request: Any) -> Iterator[Any]:
            for step in self.demo._reproduce(request):
                if isinstance(step.result, reproduce.ReproducedResult):
                    step = dataclasses.replace(step, result=change(step.result))
                yield step

        return again


class ReproduceTest(ReproduceCase):
    def test_same_contents_and_figures_after_changing_inputs_and_parameters(self) -> None:
        """CE-009-02, RF-009-11 (plan A9, D-32, T9): congelada V01.r1, se actualiza la entrada
        del límite (``Limites_v2``), la altura de banco de V01 pasa a 12 m y el hueco y su
        volumen se rehacen. Reproducir V01.r1 con el mismo Geoblender da **los mismos hashes de
        contenido** que lo congelado (la rejilla, la malla y la tabla de bancos del hueco y los
        acopios en el hueco) y **la misma cifra** (3 182 000 m³, exacta), cada operación con sus
        entradas y sus parámetros congelados (el límite de v1 y 10 m: lo vivo ya es otro); la
        importación, lo dibujado a mano y los tipos que no se reproducen, tomados de lo
        congelado. Los pasos dicen qué operación se reproduce; el informe, en los dos idiomas,
        se guarda en JSON (sin rutas absolutas) en ``<caché>/reproducir/V01.r1-<8 hex>/`` con lo
        reproducido. El proyecto no cambia: ni un fichero fuera de ``cache/`` ni la base."""
        pit, volume, piles = (self.op_uids(op_type, "V01")[0] for op_type in (
            vdemo.PIT, vdemo.PIT_VOLUME, vdemo.PIT_STOCKPILES))
        frozen = {**{(vdemo.PIT, role): sha for role, sha in self.written(pit).items()},
                  **{(vdemo.PIT_STOCKPILES, role): sha
                     for role, sha in self.written(piles).items()}}
        source = self.folder / "fuentes" / data.BOUNDARY_V2
        shutil.copyfile(data.DATA_DIR / data.BOUNDARY_V2, source)
        self.tick()
        self.demo.import_boundary(self.project, source, previous_uid=self.record(
            self.boundary).input_uid, reason="Límites nuevos")
        self.bench(12.0, "V01")
        for work in (lambda: self.demo.pit(self.project, "V01"),
                     lambda: self.demo.pit_volume(self.project, "V01")):
            self.tick()
            work()
        live = {name: self.record(name, "V01").content_sha256
                for name in (vdemo.PIT_GRID, vdemo.PIT_MESH, vdemo.PIT_BENCHES)}
        before = self.state()

        report, steps = self.run_steps("V01.r1")

        self.assertEqual(self.state(), before)
        self.assertIsInstance(report, reproduce.ReproduceReport)
        self.assertEqual((report.revision, report.revision_uid, report.cancelled),
                         ("V01.r1", self.revisions["V01.r1"], False))
        checks = self.outputs(report)
        self.assertEqual(set(checks), set(frozen))
        for key, check in checks.items():
            with self.subTest(output=key):
                self.assertEqual((check.frozen_sha256, check.reproduced_sha256, check.same,
                                  check.cause), (frozen[key], frozen[key], True, None))
        self.assertEqual([check.name for check in report.outputs],
                         [vdemo.PIT_GRID, vdemo.PIT_MESH, vdemo.PIT_BENCHES,
                          vdemo.PIT_STOCKPILES_TABLE])
        for name in live:  # lo vivo es otro: se reprodujo con lo congelado
            check = next(item for item in report.outputs if item.name == name)
            self.assertNotEqual(check.reproduced_sha256, live[name])
        (figure,) = report.figures
        self.assertEqual((figure.key, dict(figure.scope), figure.frozen, figure.reproduced,
                          figure.unit, figure.same, figure.cause, figure.operation_uid),
                         (vdemo.PIT_VOLUME_FIGURE, {}, VOLUME_10_M, VOLUME_10_M, "m3", True,
                          None, volume))
        self.assertEqual(figure.tolerance, contract.Tolerance(relative=vdemo.FIGURE_TOLERANCE))
        self.assertEqual([(note.op_type, note.why) for note in report.taken_frozen],
                         list(TAKEN_V01))
        self.assertEqual(report.not_reproducible, ())
        self.assertTrue(report.matches)
        text = ("V01.r1 reproducida: coinciden 4 de 4 salidas y 1 de 1 cifras; "
                + TAKEN_V01_TEXT)
        self.assertEqual(report.text("es"), text)
        self.assertTrue(report.text("en").startswith(
            "V01.r1 reproduced: 4 of 4 outputs and 1 of 1 figures match; 6 operations taken "
            "from what was frozen (core.import_layer, import; demo.digitize, manual edit;"))
        self.assertEqual(steps[-1].message, text)
        self.assertLessEqual(report.started_at, report.finished_at)

        self.assertTrue({step.phase for step in steps} <= set(reproduce.PHASES))
        self.assertEqual(steps[0].phase, reproduce.PHASES[0])
        shown = [step.message for step in steps if step.message.startswith("Reproduciendo")]
        self.assertEqual(shown, [f"Reproduciendo V01.r1: «{op_type}» ({index} de 3)…"
                                 for index, op_type in enumerate(
                                     (vdemo.PIT, vdemo.PIT_VOLUME, vdemo.PIT_STOCKPILES), 1)])
        self.assertTrue(all(step.total == steps[0].total and 0 <= step.done <= step.total
                            for step in steps))

        folder = Path(report.folder)
        cache = Path(self.project.cache_dir())
        self.assertEqual(folder.parent, cache / reproduce.REPRODUCE_DIR)
        self.assertRegex(folder.name, r"^V01\.r1-[0-9a-f]{8}$")
        stored = json.loads((folder / reproduce.REPORT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(stored, json.loads(json.dumps(report.as_json())))
        self.assertEqual(paths.find_absolute_paths(stored), [])
        self.assertEqual(stored["revision"], "V01.r1")
        self.assertEqual(stored["text"], text)
        self.assertGreaterEqual(sum(1 for item in folder.rglob("*") if item.is_file()), 5)

    def test_newer_algorithm_says_what_does_not_match_and_why(self) -> None:
        """RF-009-11 (plan A9 (3), D-32): con la versión del algoritmo de ``demo.pit`` subida a
        1.1 (simulada: el borde un metro más alto), el informe dice que no coinciden su
        rejilla, su malla y su tabla de bancos, con su causa en los dos idiomas («demo.pit 1.1
        instalada, congelada con 1.0»); el volumen y los acopios, que se reproducen con la
        rejilla y la tabla **congeladas** y no con lo reproducido (D-32), coinciden. Con
        ``demo.pit_volume`` 1.1 que da un volumen un 10⁻⁹ mayor, la cifra no coincide (su
        tolerancia relativa es 10⁻¹²) y lo dice con su causa; un 10⁻¹³ mayor, coincide dentro
        de la tolerancia; otra salida sin subir la versión, «sin causa conocida». La causa
        nombra también otra versión de Geoblender o de una biblioteca."""
        def higher(request: Any) -> Iterator[Any]:
            settings = {**request.settings, "top_z": request.settings["top_z"] + 1.0}
            return self.demo._reproduce(dataclasses.replace(request, settings=settings))

        self.replace_operation(vdemo.PIT, version="1.1", reproduce=higher)
        report, _steps = self.run_steps("V01.r1")
        checks = self.outputs(report)
        for role in ("pit_grid", "pit_mesh", "pit"):
            check = checks[(vdemo.PIT, role)]
            with self.subTest(role=role):
                self.assertFalse(check.same)
                self.assertNotEqual(check.reproduced_sha256, check.frozen_sha256)
                self.assertEqual(check.cause.text("es"), "demo.pit 1.1 instalada, congelada con 1.0")
                self.assertEqual(check.cause.text("en"), "demo.pit 1.1 installed, frozen with 1.0")
        self.assertTrue(checks[(vdemo.PIT_STOCKPILES, "pit_stockpiles")].same)
        (figure,) = report.figures
        self.assertTrue(figure.same)
        self.assertFalse(report.matches)
        self.assertIn("V01.r1 reproducida: coinciden 1 de 4 salidas y 1 de 1 cifras; "
                      "«demo_pit_grid» no coincide: demo.pit 1.1 instalada, congelada con 1.0; "
                      "«demo_pit_mesh» no coincide: demo.pit 1.1 instalada, congelada con 1.0; "
                      "«demo_pit_benches» no coincide: demo.pit 1.1 instalada, congelada con "
                      "1.0; 6 operaciones tomadas", report.text("es"))

        def scaled(factor: float) -> Callable[[Any], Any]:
            def change(result: Any) -> Any:
                return dataclasses.replace(result, figures=tuple(
                    dataclasses.replace(spec, value=spec.value * factor)
                    for spec in result.figures))
            return change

        self.replace_operation(vdemo.PIT_VOLUME, version="1.1",
                               reproduce=self.reproduce_with(scaled(1 + 1e-9)))
        (figure,) = self.run_steps("V01.r1")[0].figures
        self.assertFalse(figure.same)
        self.assertEqual(figure.reproduced, VOLUME_10_M * (1 + 1e-9))
        self.assertEqual(figure.cause.text("es"),
                         "demo.pit_volume 1.1 instalada, congelada con 1.0")
        self.replace_operation(vdemo.PIT_VOLUME, reproduce=self.reproduce_with(
            scaled(1 + 1e-13)))
        (figure,) = self.run_steps("V01.r1")[0].figures
        self.assertTrue(figure.same)
        self.assertNotEqual(figure.reproduced, figure.frozen)
        self.assertIsNone(figure.cause)

        self.replace_operation(vdemo.PIT, version="1.0")
        report = self.run_steps("V01.r1")[0]
        self.assertEqual(self.outputs(report)[(vdemo.PIT, "pit_grid")].cause.text("es"),
                         "sin causa conocida")
        self.assertEqual(self.outputs(report)[(vdemo.PIT, "pit_grid")].cause.text("en"),
                         "no known cause")

        installed = version_mod.geoblender_version()
        cause = reproduce.probable_cause(
            "demo.pit", frozen_version="1.0", installed_version="1.0",
            frozen_geoblender="0.0.9", frozen_software={"numpy": "2.3.4", "highspy": "1.7"},
            software={"numpy": "2.5.3", "highspy": "1.7"})
        self.assertEqual(cause.text("es"), f"Geoblender {installed} instalado, congelada con "
                                           "0.0.9; numpy 2.5.3 instalada, congelada con 2.3.4")
        self.assertEqual(reproduce.probable_cause(
            "demo.pit", frozen_version="1.0", installed_version="1.0",
            frozen_geoblender=installed, frozen_software={}).text("es"), "sin causa conocida")

    def test_taken_frozen_not_reproducible_inherited_and_failed(self) -> None:
        """RF-009-11 (plan A9 (1) y (2), D-27, D-32): en V02.r1, el volumen consumió la
        rejilla de un hueco de dos bancos que no quedó congelada en ninguna parte: «no
        reproducible» («demo.pit_volume: consumió un contenido que no se congeló»), y los dos
        huecos se reproducen y coinciden. V03.r1 diseña con la tabla de bancos congelada en
        V01.r1 (de otra instantánea): coincide aunque lo vivo de V01 ya sea otro. Con
        ``demo.pit_stockpiles`` sin registrar (su módulo no está), se toma lo congelado y el
        informe lo dice; una función de reproducir que falla deja su operación «no
        reproducible» con lo que dijo, y las demás se reproducen."""
        report, _steps = self.run_steps(self.revisions["V02.r1"])
        (note,) = report.not_reproducible
        self.assertEqual((note.op_type, note.why, note.operation_uid),
                         (vdemo.PIT_VOLUME, Why.UNFROZEN, self.op_uids(vdemo.PIT_VOLUME, "V02")[0]))
        self.assertEqual(note.text("es"), "demo.pit_volume: consumió un contenido que no se congeló")
        first, second = self.op_uids(vdemo.PIT, "V02")
        self.assertEqual([(check.operation_uid, check.role, check.reproduced_sha256, check.same)
                          for check in report.outputs],
                         [(op, role, sha, True) for op in (first, second)
                          for role, sha in sorted(self.written(op).items(),
                                                  key=lambda item: ("pit_grid", "pit_mesh",
                                                                    "pit").index(item[0]))])
        self.assertEqual(report.figures, ())
        self.assertFalse(report.matches)
        self.assertEqual(report.text("es"),
                         "V02.r1 reproducida: coinciden 6 de 6 salidas y 0 de 0 cifras; 1 "
                         "operación tomada de lo congelado (core.import_layer, importación); 1 "
                         "operación no reproducible (demo.pit_volume: consumió un contenido que "
                         "no se congeló)")

        self.bench(12.0, "V01")
        self.tick()
        self.demo.pit(self.project, "V01")
        report = self.run_steps("V03.r1")[0]
        (check,) = report.outputs
        (design,) = self.op_uids(vdemo.DESIGN_FROM_PARENT, "V03")
        self.assertEqual((check.role, check.same, check.reproduced_sha256),
                         ("design", True, self.written(design)["design"]))
        self.assertEqual((report.taken_frozen, report.not_reproducible), ((), ()))
        self.assertEqual(report.text("es"),
                         "V03.r1 reproducida: coinciden 1 de 1 salidas y 0 de 0 cifras")

        def fail(result: Any) -> Any:
            raise ValueError("sin rejilla")

        self.replace_operation(vdemo.PIT_VOLUME, reproduce=self.reproduce_with(fail))
        original = contract.OPERATIONS[vdemo.PIT_STOCKPILES]
        contract.unregister_operation(vdemo.PIT_STOCKPILES)
        self.addCleanup(contract.register_operation, original)
        report = self.run_steps("V01.r1")[0]
        self.assertEqual([(note.op_type, note.why) for note in report.taken_frozen],
                         [*TAKEN_V01[:5], ("demo.sketch", Why.MANUAL),
                          (vdemo.PIT_STOCKPILES, Why.MODULE)])
        self.assertEqual(report.taken_frozen[-1].text("es"),
                         "demo.pit_stockpiles, su módulo no está instalado")
        (failed,) = report.not_reproducible
        self.assertEqual((failed.op_type, failed.why, failed.text("es")),
                         (vdemo.PIT_VOLUME, Why.FAILED, "demo.pit_volume ha fallado: sin rejilla"))
        self.assertEqual([check.name for check in report.outputs],
                         [vdemo.PIT_GRID, vdemo.PIT_MESH, vdemo.PIT_BENCHES])
        self.assertTrue(all(check.same for check in report.outputs))
        self.assertEqual(report.figures, ())

    def test_rejected_before_starting(self) -> None:
        """RF-009-09, RF-009-11 (plan A9): antes de reproducir nada, sin escribir nada en el
        proyecto ni en la caché. Un fichero de V01.r1 con otra huella (mismo tamaño y fecha,
        lo que solo ve la comprobación entera): rechazo con la revisión y lo que no coincide,
        y la marca no se registra (reproducir solo lee). Una revisión ya marcada alterada, una
        abierta, una que no existe y sin espacio en la caché, rechazo al pedirlo."""
        before, listing = self.state(), self.cache_listing()
        undo = fixtures.alter_file(self.root / "snapshots" / "V01.r1" / Path(
            vdemo.MESH_LOCATOR.replace(vdemo.PIT_MESH, f"{vdemo.PIT_MESH}_v01")))
        steps = reproduce.reproduce_steps(self.project, "V01.r1")
        with self.assertRaises(model.VersionError) as caught:
            for step in steps:
                self.assertEqual(step.phase, reproduce.PHASES[0])
        self.assertEqual(caught.exception.code, "core.version_reproduce_altered")
        self.assertEqual(str(caught.exception),
                         "La revisión V01.r1 está alterada (meshes/demo_pit_mesh_v01.npz: otra "
                         "huella): no se reproduce")
        self.assertEqual(self.query("SELECT count(*) FROM gb_revision WHERE altered_at IS NOT "
                                    "NULL"), [(0,)])
        undo()
        self.assertEqual((self.state(), self.cache_listing()), (before, listing))

        self.write(lambda conn: conn.execute(
            "UPDATE gb_revision SET altered_at = ?, altered_detail = ? WHERE uid = ?",
            (self.now(), '[{"path":"V01.r1.gpkg","problem":"size"}]', self.revisions["V01.r1"])))
        before = self.state()
        free = SimpleNamespace(free=10)
        for revision, code, text, kw in (
                ("V01.r1", "core.version_reproduce_altered",
                 "La revisión V01.r1 está alterada (V01.r1.gpkg: otro tamaño): no se reproduce",
                 {}),
                ("V01.r2", "core.version_reproduce_not_frozen",
                 "V01.r2 no está congelada: solo se reproduce una revisión congelada", {}),
                ("V09.r1", "core.version_reproduce_unknown",
                 "No hay ninguna revisión V09.r1 en el proyecto", {}),
                ("V03.r1", "core.version_reproduce_no_space",
                 "No hay espacio para reproducir V03.r1: hacen falta ",
                 {"disk_usage": lambda path: free})):
            with self.subTest(revision=revision), self.assertRaises(model.VersionError) as caught:
                reproduce.reproduce_steps(self.project, revision, **kw)
            self.assertEqual(caught.exception.code, code)
            self.assertTrue(str(caught.exception).startswith(text), str(caught.exception))
        self.assertIn(" y quedan 10 B", str(caught.exception))
        self.assertEqual((self.state(), self.cache_listing()), (before, listing))

    def test_escape_and_cancel_leave_nothing(self) -> None:
        """RF-009-11 (plan A9): Esc a mitad (cerrar los pasos con la primera operación ya
        reproducida) y cancelar (``cancelled``) no dejan nada en la caché ni cambian el
        proyecto; cancelar termina con un informe cancelado y su texto."""
        before, listing = self.state(), self.cache_listing()
        steps = reproduce.reproduce_steps(self.project, "V01.r1")
        for step in steps:
            if step.message.startswith("Reproduciendo V01.r1: «demo.pit_volume»"):
                break
        else:
            self.fail("no ha llegado a la segunda operación")
        self.assertTrue((Path(self.project.cache_dir()) / reproduce.REPRODUCE_DIR).is_dir())
        steps.close()
        self.assertEqual((self.state(), self.cache_listing()), (before, listing))

        steps = []
        for step in reproduce.reproduce_steps(
                self.project, "V01.r1", cancelled=lambda: any(
                    step.message.startswith("Reproduciendo") for step in steps)):
            steps.append(step)
        self.assertEqual([step.result is not None for step in steps].count(True), 1)
        report = steps[-1].result
        self.assertIsInstance(report, reproduce.ReproduceReport)
        self.assertTrue(report.cancelled)
        self.assertEqual(steps[-1].message, "Reproducción cancelada: no ha quedado nada a medias")
        self.assertEqual(report.text("es"), steps[-1].message)
        self.assertEqual((self.state(), self.cache_listing()), (before, listing))
