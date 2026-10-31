# SPDX-License-Identifier: GPL-3.0-or-later
"""El proyecto de las restricciones (spec 012, T10; plan 012 §7.1).

Un proyecto sintético cuya ventana es la del sitio de ``tests.support.constraints_fixtures``
(:data:`~tests.support.constraints_fixtures.SITE_GRID`: celdas de 2 m, 160 × 160), con V01 y
V02 y, en el proyecto, las tres capas de restricciones, los sectores y las búsquedas escritas por
una operación de prueba de ``core`` (:data:`EDIT_TYPE`, que hace lo que hará
``core.edit_constraints`` en la T14: escribir las tablas y registrarlas como datos):

- «Concesión» (``concesion``): el límite legal del sitio, con 10 m hacia dentro;
- «Perímetro» (``perimetro``): el perímetro de actuación con su lóbulo fuera del límite
  (la franja de 0,68 ha, CE-012-03);
- «Torre» (``torre``): un intocable puntual en una esquina de celda, con 6 m en el proyecto y
  **8 m solo en V01** (60 celdas de 2 m, CE-012-01), para ver la resolución versión → proyecto;
- «Balsa» (``balsa``): «sin relleno», un rectángulo de 60 × 50 m sin resguardo;
- «Cuneta» (``cuneta``): «sin corte», una línea de 60 m con 4 m;
- los dos sectores de ``SECTORS_LOCAL`` y ninguna búsqueda.

Se crea una vez por proceso (:func:`project_template`) y cada clase de
:class:`ConstraintsProjectCase` trabaja en su copia, con lo que necesita registrado: los
parámetros de ``core`` de las restricciones, el tipo de prueba, ``gis.compile_constraints`` (con
su función de reproducir) y sus cifras, y los lectores de contenido.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
import unittest
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.core_fixtures import FakeClock, FakePids, make_session, make_settings
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

model = import_geoblender("core.constraints.model")
cparams = import_geoblender("core.constraints.params")
cstore = import_geoblender("core.constraints.store")
cstyles = import_geoblender("core.constraints.styles")

T = model.ConstraintType
G = model.GeometryKind

EDIT_TYPE = "core.test_constraints"
"""La operación de prueba que escribe las tablas de las restricciones (la T14 hará
``core.edit_constraints``)."""
SESSION = make_session()
"""La sesión sintética del proyecto."""
PARAMS_BY_HAND: Mapping[str, str] = {
    "source": "Valores sintéticos de prueba", "source_kind": "document",
    "decided_by": "Samuel (IMGA)",
}
"""El origen y el decisor de los parámetros de prueba (D-5: ningún valor por defecto)."""
LEGAL_INWARD_M = 10.0
TOWER_PROJECT_M = 6.0
TOWER_V01_M = fx.TOWER_OUTWARD_M
DITCH_LOCAL = ((40.0, 150.0), (100.0, 150.0))
DITCH_OUTWARD_M = 4.0
_VERSIONS = (("mascaras", "Máscaras"), ("alternativa", "Alternativa"))
_TEMPLATE: dict[str, Any] = {}


def window() -> tuple[float, float, float, float]:
    """La ventana del proyecto: la extensión de ``SITE_GRID`` (ya alineada a 2 m)."""
    extent = fx.SITE_GRID.extent
    return (extent.xmin, extent.ymin, extent.xmax, extent.ymax)


def _constraint(code: str, name: str, ctype: Any, kind: Any, parts: Any, *,
                priority: int = 0) -> Any:
    return model.Constraint(
        uid=f"{code:0<32}"[:32], code=code, name=name, ctype=ctype, kind=kind, parts=parts,
        priority=priority, reason="Restricción sintética de prueba",
        decided_by="Samuel (IMGA)", decided_on=date(2026, 10, 28), decision_uid=None,
        intention_uid=None, source_input=None, source_fid=None,
        layer=cstore.layer_of(kind), fid=0)


def constraints(*, perimeter: Sequence[Sequence[float]] = fx.PERIMETER_LOCAL
                ) -> tuple[Any, ...]:
    """Las cinco restricciones del proyecto (véase el módulo), con ``fid`` 0 (nuevas); con
    ``perimeter``, el perímetro con esos vértices locales."""
    return (
        _constraint("concesion", "Concesión", T.LEGAL_LIMIT, G.POLYGON,
                    ((fx.absolute(fx.LEGAL_LIMIT_LOCAL),),)),
        _constraint("perimetro", "Perímetro", T.ACTION_PERIMETER, G.POLYGON,
                    ((fx.absolute(perimeter),),)),
        _constraint("torre", "Torre", T.UNTOUCHABLE, G.POINT,
                    ((fx.absolute([fx.TOWER_LOCAL]),),), priority=10),
        _constraint("balsa", "Balsa", T.NO_FILL, G.POLYGON, ((fx.rectangle(*fx.POND_LOCAL),),)),
        _constraint("cuneta", "Cuneta", T.NO_CUT, G.LINE, ((fx.absolute(DITCH_LOCAL),),)),
    )


def project_values() -> dict[str, Any]:
    """Los parámetros del proyecto de las cinco restricciones (clave → valor)."""
    found: dict[str, Any] = {cparams.active_key(item.code): True for item in constraints()}
    found[cparams.buffer_in_key("concesion")] = LEGAL_INWARD_M
    found[cparams.buffer_out_key("torre")] = TOWER_PROJECT_M
    found[cparams.buffer_out_key("balsa")] = 0.0
    found[cparams.buffer_out_key("cuneta")] = DITCH_OUTWARD_M
    return found


def sectors() -> tuple[Any, ...]:
    """Los dos sectores de búsqueda (``SECTORS_LOCAL``)."""
    return tuple(model.Sector(f"sector{index}{'0' * 26}", f"sector_{index}", name,
                              (fx.rectangle(*box),))
                 for index, (name, box) in enumerate(fx.SECTORS_LOCAL.items(), start=1))


def _no_recompute(request: Any) -> Any:
    raise AssertionError("las pruebas de la 012 no recalculan con la función de bl")


@contextmanager
def constraints_registered() -> Iterator[None]:
    """Registra lo que declara la 012 que usan estas pruebas (lo hará ``bl``): los parámetros
    de ``core`` de las restricciones (si faltan), el tipo :data:`EDIT_TYPE`,
    ``gis.compile_constraints`` con su función de reproducir y sus cifras, y los lectores de
    contenido que falten. Al salir, quita lo que registró."""
    params = import_geoblender("core.params")
    contract = import_geoblender("core.provenance.contract")
    readers = import_geoblender("core.content.readers")
    builtin = import_geoblender("core.content.builtin")
    gis_content = import_geoblender("gis.content")
    provenance = import_geoblender("gis.masks.provenance")
    store = import_geoblender("gis.masks.store")
    edit = contract.OperationDef(EDIT_TYPE, "1.0", "core", "Constraints of the tests", False)
    with ExitStack() as stack:
        if cparams.FAMILIES[0].pattern not in params.FAMILIES:
            params.register_families(cparams.FAMILIES)
            stack.callback(params.unregister_families, "core")
        stack.enter_context(registered(
            edit, provenance.operation_def(_no_recompute, store.REPRODUCE[provenance.COMPILE]),
            *provenance.FIGURES))
        for reader in (*builtin.CONTENT_READERS, gis_content.GEOTIFF):
            if reader.id not in readers.READERS:
                readers.register_reader(reader)
                stack.callback(readers.unregister_reader, reader.id)
        yield


def edit_constraints(project: Any, rows: Sequence[Any], *, sector_rows: Sequence[Any] = ()
                     ) -> str:
    """:data:`EDIT_TYPE`: escribe ``rows`` (``fid`` 0, nuevas; > 0, sustituyen) y ``sector_rows``
    en las tablas de las restricciones (las crea si faltan) y las registra como datos del
    proyecto; devuelve el uid de la operación."""
    operations = import_geoblender("core.provenance.operations")
    srs = project.record.crs_epsg
    handle = operations.begin_operation(project, EDIT_TYPE, settings={"count": len(rows)},
                                        executor="blender")
    with project.write_transaction() as conn:
        cstore.create_tables(conn, srs)
        styled = cstyles.write_styles(conn, cstore.CONSTRAINT_LAYERS.values())
        cstore.write_constraints(conn, rows, srs_id=srs)
        cstore.write_sectors(conn, sector_rows, srs_id=srs)
        handle.complete(conn, outputs=(*cstore.dataset_specs(crs_epsg=srs),
                                       *(cstyles.dataset_spec() for _ in styled)),
                        message="Restricciones de prueba")
    return handle.uid


def declare(project: Any, clock: FakeClock, values: Mapping[str, Any], *,
            version: Any = None) -> None:
    """Da de alta cada parámetro de ``values`` en el proyecto o, con ``version``, como valor
    propio de esa versión, con :data:`PARAMS_BY_HAND`, en una transacción."""
    store = import_geoblender("core.params").ParameterStore(project)
    code = None if version is None else version.code
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        for key, value in values.items():
            kind = "ADOPTADO" if isinstance(value, bool) else "HIPÓTESIS"
            store.create(conn, key, value, kind=kind, **PARAMS_BY_HAND,
                         reason="Prueba de las restricciones", version=code)


def _build(folder: Path) -> dict[str, Any]:
    create = import_geoblender("core.project.create")
    userdata = import_geoblender("core.userdata")
    versions_store = import_geoblender("core.versions.store")
    (folder / "proyectos").mkdir()
    clock = FakeClock()
    settings = make_settings(window=window(), grid_step_m=fx.SITE_STEP_M)
    project = create.create_project(folder / "proyectos", settings, SESSION,
                                    userdata.UserData(folder / "u"), clock=clock).project
    try:
        versions = []
        for feature, title in _VERSIONS:
            clock.advance(minutes=1)
            with project.write_transaction() as conn:
                version, _revision = versions_store.create_version(
                    conn, project, feature=feature, title=title, reason="Prueba de la 012")
            project.refresh_header()
            versions.append(version)
        clock.advance(minutes=1)
        edit_constraints(project, constraints(), sector_rows=sectors())
        declare(project, clock, project_values())
        declare(project, clock, {cparams.buffer_out_key("torre"): TOWER_V01_M},
                version=versions[0])
        clock.advance(minutes=1)
        return {"folder": folder, "name": Path(project.root).name, "now": clock.now(),
                "versions": tuple(version.uid for version in versions)}
    finally:
        project.close()


def project_template() -> Mapping[str, Any]:
    """El proyecto de las restricciones (véase el módulo), creado y cerrado la primera vez que
    se pide en el proceso en una carpeta temporal que se borra al salir."""
    if not _TEMPLATE:
        folder = Path(tempfile.mkdtemp(prefix="gb-ct-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        with constraints_registered():
            _TEMPLATE.update(_build(folder))
    return _TEMPLATE


class ConstraintsProjectCase(unittest.TestCase):
    """Una copia por clase del proyecto de :func:`project_template`, abierta en escritura
    (``cls.project``, en ``cls.root``), con lo de :func:`constraints_registered`, su reloj
    (``cls.clock``) y V01 y V02 (``cls.v1``, ``cls.v2``)."""

    project: ClassVar[Any]
    root: ClassVar[Path]
    clock: ClassVar[FakeClock]
    v1: ClassVar[Any]
    v2: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        made = project_template()
        cls.enterClassContext(constraints_registered())
        open_mod = import_geoblender("core.project.open")
        userdata = import_geoblender("core.userdata")
        versions_read = import_geoblender("core.versions.read")
        folder = cls.enterClassContext(project_tmp("gb-cp-"))
        shutil.copytree(made["folder"] / "proyectos", folder / "proyectos")
        cls.clock = FakeClock(made["now"])
        cls.project = open_mod.open_project(
            folder / "proyectos" / made["name"], SESSION, userdata.UserData(folder / "u"),
            clock=cls.clock, pid_alive=FakePids({SESSION.pid})).project
        cls.addClassCleanup(cls.project.close)
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in made["versions"])

    def query(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        """Las filas de ``sql`` en una conexión de lectura."""
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def record(self, name: str, version: Any = None) -> Any:
        """El dato vivo ``name`` del proyecto o de ``version``; ``None``."""
        registry = import_geoblender("core.datasets.registry")
        with self.project.read() as conn:
            return registry.get(conn, name, version_uid="" if version is None else version.uid)

    def stored_constraints(self) -> tuple[Any, ...]:
        """Las restricciones guardadas en el proyecto."""
        with self.project.read() as conn:
            return cstore.read_constraints(conn)


def same_parts(a: Any, b: Any) -> bool:
    """Si dos geometrías (partes de anillos) son iguales bit a bit."""
    return len(a) == len(b) and all(
        len(pa) == len(pb) and all(np.array_equal(ra, rb) for ra, rb in zip(pa, pb, strict=True))
        for pa, pb in zip(a, b, strict=True))
