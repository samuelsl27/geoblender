# SPDX-License-Identifier: GPL-3.0-or-later
"""Módulo de demostración de la procedencia, «demo» (spec 008, T39; plan 008 §7.1).

Un módulo de Geoblender pequeño y sintético que se enchufa a la procedencia como lo hará
cualquier otro (ADR-0025 §2): declara sus operaciones, su grupo acoplado, sus cifras y sus
parámetros con los tipos de ``core`` y los registra (:meth:`Demo.register`). Lo usan las
regresiones de Silvestre de la 008 (CE-008-01, 02, 03 y 10; T40 y T41), el caso de referencia
de procedencia y, en el perfil de desarrollo, ``tools/inblender/provenance_demo.py`` (operadores
``gbdemo.*``, fuera del catálogo) para las comprobaciones manuales M0 a M5. **No se empaqueta**:
vive en ``tests/support/`` y ``tools/build.py`` solo empaqueta ``geoblender/``.

La cadena (todo en tablas de ``project.gpkg``, sin ficheros):

- importar el límite: :meth:`Demo.import_boundary`, la capa ``limites`` de un GeoPackage como
  entrada con ``core.import_layer`` (lo importado, ``core_imported_<nombre>``); no es un tipo
  ``demo.*``: la importación de una capa es de ``core`` y su importador la reimporta
  («Actualizar», ``core.provenance.importer.reimport_input``);
- ``demo.area``: el área planimétrica del límite → cifra ``demo.boundary_area`` (ha,
  CALCULADO); con ``Limites_v1``, 12,000 0 ha, y con ``Limites_v2``, 13,430 0 ha;
- ``demo.digitize`` (edición a mano, **no** repetible: queda «revisar a mano»): los bancos con
  su tonelaje (``demo_benches``) y la capa **editable** en QGIS de las marcas de acopio
  (``demo_marks``: marca, banco y volumen en banco), con los valores en sus ajustes;
- ``demo.bench_years``: años de cada banco = tonelaje del banco / producción
  ``demo.production`` (t/año, HIPÓTESIS por defecto) → ``demo_bench_years`` y una cifra
  ``demo.bench_years`` (año) por banco. El «volumen por banco» del plan va en toneladas para
  que el cociente entre t/año dé años. También como trabajo de la 004 (T41):
  :meth:`Demo.bench_years_job` la registra «en curso» con el ejecutor del trabajo y
  :meth:`Demo.ingest_bench_years` la incorpora (``ingest_job``) con la producción que leyó;
- el grupo acoplado ``demo.stockpiles``: ``demo.detect_stockpiles`` (las marcas con los años
  de su banco → ``demo_stockpile_candidates``) y ``demo.filter_stockpiles`` (las de bancos con
  al menos :data:`MIN_YEARS` años, con su volumen esponjado = volumen en banco × K
  ``demo.swell_factor`` → ``demo_stockpiles`` y la cifra ``demo.stockpile_volume``, m³);
- ``demo.balance``: calcula K = volumen esponjado / volumen en banco (1 110 / 1 000 = 1,11) y lo
  registra como cifra CALCULADA del parámetro ``demo.swell_factor`` (1,15, HIPÓTESIS por
  defecto), sin tocarlo (RF-008-59; decisión S-1 de Samuel).

Las repetibles se recalculan solas con su función de recálculo (la misma para todas: repite el
cuerpo de su tipo con lo vigente).

**El código ``demo``.** Los tipos, las cifras, los parámetros y los datos de un módulo llevan
un código de ``core.catalog.schema.MODULE_CODES`` y ``demo`` no lo es (ni debe serlo en el
producto). Mientras está registrada, la demostración amplía con ``demo`` la lista que ve cada
módulo de Geoblender que la importó (los que validan esos nombres); al quitarla, devuelve a
cada uno la suya. No toca la de ``core.catalog.schema`` (un módulo importado mientras tanto la
copiaría ampliada para siempre) ni los nombres de los operadores (los de la demostración son
``gbdemo.*``, fuera del catálogo).

**Lo que aún no registra ``bl``.** Hasta que ``bl/ops/core_provenance.py`` registre lo de
``core`` (T44 y T46), :meth:`Demo.register` registra lo que falte de ello (sus operaciones, su
importador y sus lectores de contenido) y :meth:`Demo.unregister` quita solo lo que registró.
También instala las etiquetas en español de la demostración y, al quitarla, deja las
traducciones como estaban.

**Dos paquetes.** En las pruebas sin Blender, ``Demo()`` usa el ``geoblender`` que carga
``tests.support.package``; dentro de Blender, ``Demo("bl_ext.<repo>.geoblender")`` usa la
extensión instalada (sus registros son otros objetos). Este módulo no importa Geoblender al
importarse. Datos solo sintéticos: nada de clientes.
"""

from __future__ import annotations

import importlib
import math
import os
import sqlite3
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from types import ModuleType
from typing import Any

DEMO_CODE = "demo"
"""El código de módulo de la demostración (no es de Geoblender: véase el módulo)."""

AREA = "demo.area"
BENCH_YEARS = "demo.bench_years"
DETECT_STOCKPILES = "demo.detect_stockpiles"
FILTER_STOCKPILES = "demo.filter_stockpiles"
BALANCE = "demo.balance"
DIGITIZE = "demo.digitize"
OPERATION_TYPES: tuple[str, ...] = (DIGITIZE, AREA, BENCH_YEARS, DETECT_STOCKPILES,
                                    FILTER_STOCKPILES, BALANCE)
"""Los tipos de operación de la demostración, en su orden de registro."""
STOCKPILES = "demo.stockpiles"
"""El grupo acoplado de los acopios: detectar y filtrar, en ese orden (RF-008-25)."""

BOUNDARY_AREA = "demo.boundary_area"
YEARS_FIGURE = "demo.bench_years"
STOCKPILE_VOLUME = "demo.stockpile_volume"
SWELL_FIGURE = "demo.swell_factor"
PRODUCTION = "demo.production"
SWELL_FACTOR = "demo.swell_factor"

BENCHES_TABLE = "demo_benches"
MARKS_TABLE = "demo_marks"
YEARS_TABLE = "demo_bench_years"
CANDIDATES_TABLE = "demo_stockpile_candidates"
STOCKPILES_TABLE = "demo_stockpiles"

LAYER = "limites"
"""La capa de los GeoPackage de límites de ``tests/data/core/provenance/``."""
IMPORTED_PREFIX = "core_imported_"
DEFAULT_BENCHES: tuple[tuple[str, float], ...] = (
    ("B-1", 1_250_000.0),
    ("B-2", 980_000.0),
    ("B-3", 1_500_000.0),
)
"""Bancos de la demostración: nombre y tonelaje (t). Con 500 000 t/año: 2,5, 1,96 y 3 años."""
DEFAULT_MARKS: tuple[tuple[str, str, float], ...] = (
    ("A-1", "B-1", 12_000.0),
    ("A-2", "B-2", 8_000.0),
    ("A-3", "B-3", 6_500.0),
)
"""Marcas de acopio: marca, banco y volumen en banco (m³)."""
MIN_YEARS = 2.5
"""Los años mínimos del banco de un acopio que se queda al filtrar (ajuste por defecto): con
500 000 t/año se quedan los de B-1 (justo 2,5) y B-3."""
BALANCE_BANK_M3 = 1_000.0
BALANCE_LOOSE_M3 = 1_110.0
"""Los volúmenes medidos del balance por defecto: K = 1 110 / 1 000 = 1,11."""

LABELS_ES: Mapping[str, str] = {
    "Demo digitize benches and marks": "Digitalizar bancos y marcas (demostración)",
    "Demo compute boundary area": "Calcular el área del límite (demostración)",
    "Demo years per bench": "Años por banco (demostración)",
    "Demo detect stockpiles": "Detectar acopios (demostración)",
    "Demo filter stockpiles": "Filtrar acopios (demostración)",
    "Demo earthwork balance": "Balance de tierras (demostración)",
    "Demo boundary area": "Área del límite (demostración)",
    "Demo bench years": "Años del banco (demostración)",
    "Demo stockpile volume": "Volumen esponjado de los acopios (demostración)",
    "Demo K": "K (demostración)",
    "Demo production": "Producción (demostración)",
    "Demo swell factor K": "Factor de esponjamiento K (demostración)",
}
"""Las etiquetas de la demostración (``msgid`` en inglés → español)."""

_CODE_USERS: tuple[str, ...] = (
    "core.params.model",
    "core.params.store",
    "core.provenance.contract",
    "core.datasets.model",
    "core.datasets.orphans",
    "core.inputs.model",
)
"""Los módulos que validan un código de módulo con ``MODULE_CODES`` (se importan antes de
ampliar la lista, para que cada uno tenga la suya)."""
_TABLE_COLUMNS: Mapping[str, tuple[tuple[str, str], ...]] = {
    BENCHES_TABLE: (("bench", "TEXT"), ("tonnage_t", "DOUBLE")),
    MARKS_TABLE: (("mark", "TEXT"), ("bench", "TEXT"), ("bank_m3", "DOUBLE")),
    YEARS_TABLE: (("bench", "TEXT"), ("tonnage_t", "DOUBLE"), ("years", "DOUBLE")),
    CANDIDATES_TABLE: (("mark", "TEXT"), ("bench", "TEXT"), ("bank_m3", "DOUBLE"),
                       ("years", "DOUBLE")),
    STOCKPILES_TABLE: (("mark", "TEXT"), ("bench", "TEXT"), ("loose_m3", "DOUBLE"),
                       ("years", "DOUBLE")),
}
_TABLE_TITLES: Mapping[str, str] = {
    BENCHES_TABLE: "Bancos (demostración)",
    MARKS_TABLE: "Marcas de acopio (demostración)",
    YEARS_TABLE: "Años por banco (demostración)",
    CANDIDATES_TABLE: "Acopios detectados (demostración)",
    STOCKPILES_TABLE: "Acopios (demostración)",
}


def _positive(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{what} es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{what} es un número finito mayor que cero, no {value!r}")
    return number


def _name(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} es un texto no vacío, no {value!r}")
    return value.strip()


def _ring_area(ring: Sequence[Sequence[float]]) -> float:
    """El área (m², sin signo) de un anillo cerrado, por la fórmula del área de Gauss con las
    coordenadas relativas a su primer vértice (sin perder precisión con las absolutas)."""
    x0, y0 = ring[0][0], ring[0][1]
    xs = [point[0] - x0 for point in ring]
    ys = [point[1] - y0 for point in ring]
    twice = math.fsum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i] for i in range(len(ring) - 1))
    return abs(twice) / 2.0


class Demo:
    """La demostración sobre el paquete ``package`` de Geoblender (``None``: el de las pruebas
    sin Blender): :meth:`register`/:meth:`unregister` (o :meth:`registered`) y las órdenes de la
    cadena, que devuelven la operación hecha (su ``OperationHandle``)."""

    def __init__(self, package: str | None = None) -> None:
        if package is None:  # el de las pruebas sin Blender (tests.support.package)
            from tests.support.package import PACKAGE_NAME, load_geoblender

            load_geoblender()
            package = PACKAGE_NAME
        if not isinstance(package, str) or not package:
            raise TypeError(f"el paquete de Geoblender es su nombre, no {package!r}")
        self.package = package
        self._undo: list[Callable[[], None]] = []
        self._active = False
        self._bodies: Mapping[str, Callable[[Any], None]] = {
            AREA: self._area,
            BENCH_YEARS: self._bench_years,
            DETECT_STOCKPILES: self._detect,
            FILTER_STOCKPILES: self._filter,
            BALANCE: self._balance,
            DIGITIZE: self._digitize,
        }

    def __repr__(self) -> str:
        return f"<Demo {self.package} {'registrada' if self._active else 'sin registrar'}>"

    def module(self, name: str) -> ModuleType:
        """El módulo ``<paquete>.<name>`` (``"core.provenance.contract"``)."""
        return importlib.import_module(f"{self.package}.{name}")

    # --- Registro ---------------------------------------------------------------------------

    @property
    def active(self) -> bool:
        """Si está registrada."""
        return self._active

    def register(self) -> None:
        """Registra la demostración (véase el módulo). :class:`RuntimeError` si ya lo está; si
        algo falla a medias, quita lo registrado y deja pasar el error."""
        if self._active:
            raise RuntimeError("la demostración ya está registrada: quítela antes "
                               "(unregister)")
        self._active = True
        try:
            self._widen_codes()
            self._register_core()
            self._register_own()
            self._install_labels()
        except BaseException:
            self.unregister()
            raise

    def unregister(self) -> None:
        """Quita todo lo que registró, en orden inverso; sin nada registrado, no hace nada."""
        try:
            while self._undo:
                self._undo.pop()()
        finally:
            self._active = False

    @contextmanager
    def registered(self) -> Iterator[Demo]:
        """:meth:`register` al entrar y :meth:`unregister` al salir."""
        self.register()
        try:
            yield self
        finally:
            self.unregister()

    def _widen_codes(self) -> None:
        schema = self.module("core.catalog.schema")
        original = schema.MODULE_CODES
        for name in _CODE_USERS:
            self.module(name)
        widened = (*original, DEMO_CODE)
        prefix = f"{self.package}."
        patched = [module for name, module in list(sys.modules.items())
                   if name.startswith(prefix) and module is not None and module is not schema
                   and getattr(module, "MODULE_CODES", None) is original]
        for module in patched:
            module.MODULE_CODES = widened

        def restore() -> None:
            for module in patched:
                if getattr(module, "MODULE_CODES", None) is widened:
                    module.MODULE_CODES = original

        self._undo.append(restore)

    def _register_core(self) -> None:
        contract = self.module("core.provenance.contract")
        importer = self.module("core.provenance.importer")
        readers = self.module("core.content.readers")
        builtin = self.module("core.content.builtin")
        for operation in contract.CORE_OPERATIONS:
            if operation.op_type not in contract.OPERATIONS:
                contract.register_operation(operation)
                self._undo.append(self._unregister_if(
                    contract.OPERATIONS, operation.op_type, operation,
                    contract.unregister_operation))
        for importer_def in importer.CORE_IMPORTERS:
            if importer_def.reader_id not in contract.IMPORTERS:
                contract.register_importer(importer_def)
                self._undo.append(self._unregister_if(
                    contract.IMPORTERS, importer_def.reader_id, importer_def,
                    contract.unregister_importer))
        for reader in builtin.CONTENT_READERS:
            if reader.id not in readers.READERS:
                readers.register_reader(reader)
                self._undo.append(self._unregister_if(readers.READERS, reader.id, reader,
                                                      readers.unregister_reader))

    @staticmethod
    def _unregister_if(view: Mapping[str, Any], key: str, item: object,
                       remove: Callable[[str], int]) -> Callable[[], None]:
        def undo() -> None:
            if view.get(key) is item:
                remove(key)

        return undo

    def _register_own(self) -> None:
        params = self.module("core.params")
        contract = self.module("core.provenance.contract")
        definitions = self._parameters()
        params.register_definitions(definitions)
        self._undo.append(lambda: params.unregister_definitions(DEMO_CODE))
        for operation in self._operations():
            contract.register_operation(operation)
            self._undo.append(lambda op_type=operation.op_type:
                              contract.unregister_operation(op_type))
        contract.register_group(contract.CoupledGroupDef(
            STOCKPILES, (DETECT_STOCKPILES, FILTER_STOCKPILES)))
        self._undo.append(lambda: contract.unregister_group(STOCKPILES))
        for figure in self._figures():
            contract.register_figure(figure)
            self._undo.append(lambda key=figure.key: contract.unregister_figure(key))

    def _install_labels(self) -> None:
        i18n = self.module("core.i18n")
        installed = i18n._STATE.installed  # sin API para quitar: se deja como estaba
        previous = {msgid: installed.get(msgid) for msgid in LABELS_ES}
        i18n.install(LABELS_ES)

        def restore() -> None:
            for msgid, text in previous.items():
                if text is None:
                    installed.pop(msgid, None)
                else:
                    installed[msgid] = text

        self._undo.append(restore)

    # --- Declaraciones ----------------------------------------------------------------------

    def _parameters(self) -> tuple[Any, ...]:
        params = self.module("core.params")
        return (
            params.ParamDef(
                PRODUCTION, "float", "t/yr", 500_000.0, 0.0, None, ("RF-008-24",),
                "Demostración: producción anual del plan de labores", min_exclusive=True,
                kind="HIPÓTESIS", source_kind="document", label_msgid="Demo production",
            ),
            params.ParamDef(
                SWELL_FACTOR, "float", "-", 1.15, 1.0, 2.0, ("RF-008-59",),
                "Demostración: K de esponjamiento sin ensayo", kind="HIPÓTESIS",
                source_kind="document", label_msgid="Demo swell factor K",
            ),
        )

    def _operations(self) -> tuple[Any, ...]:
        contract = self.module("core.provenance.contract")
        redo = self._recompute
        return (
            contract.OperationDef(DIGITIZE, "1.0", DEMO_CODE,
                                  "Demo digitize benches and marks", False),
            contract.OperationDef(AREA, "1.0", DEMO_CODE, "Demo compute boundary area", True,
                                  recompute=redo),
            contract.OperationDef(BENCH_YEARS, "1.0", DEMO_CODE, "Demo years per bench", True,
                                  recompute=redo),
            contract.OperationDef(DETECT_STOCKPILES, "1.0", DEMO_CODE, "Demo detect stockpiles",
                                  True, group=STOCKPILES, recompute=redo),
            contract.OperationDef(FILTER_STOCKPILES, "1.0", DEMO_CODE, "Demo filter stockpiles",
                                  True, group=STOCKPILES, recompute=redo),
            contract.OperationDef(BALANCE, "1.0", DEMO_CODE, "Demo earthwork balance", True,
                                  recompute=redo),
        )

    def _figures(self) -> tuple[Any, ...]:
        contract = self.module("core.provenance.contract")
        return (
            contract.FigureDef(BOUNDARY_AREA, "ha", "Demo boundary area", allow_zero=False),
            contract.FigureDef(YEARS_FIGURE, "yr", "Demo bench years", allow_zero=False),
            contract.FigureDef(STOCKPILE_VOLUME, "m3", "Demo stockpile volume"),
            contract.FigureDef(SWELL_FIGURE, "-", "Demo K", allow_zero=False),
        )

    # --- Órdenes de la cadena ---------------------------------------------------------------

    def import_boundary(self, project: Any, source: str | os.PathLike[str], *,
                        name: str | None = None, layer: str = LAYER,
                        previous_uid: str | None = None, reason: str | None = None) -> Any:
        """Registra como entrada la capa ``layer`` del GeoPackage ``source`` con
        ``core.import_layer`` (por defecto, con el nombre del fichero) y devuelve su
        ``LayerImport`` (``.dataset``: lo importado)."""
        importer = self.module("core.provenance.importer")
        return importer.import_layer(project, layer, source=source, name=name,
                                     previous_uid=previous_uid, reason=reason)

    def digitize(self, project: Any, *,
                 benches: Sequence[tuple[str, float]] = DEFAULT_BENCHES,
                 marks: Sequence[tuple[str, str, float]] = DEFAULT_MARKS) -> Any:
        """``demo.digitize``: los bancos (nombre y tonelaje, t) y las marcas de acopio (marca,
        banco y volumen en banco, m³) que digitaliza una persona."""
        settings = {
            "benches": [[_name(bench, "el nombre de un banco"),
                         _positive(tonnes, f"el tonelaje del banco «{bench}»")]
                        for bench, tonnes in benches],
            "marks": [[_name(mark, "el nombre de una marca"), _name(bench, "su banco"),
                       _positive(bank, f"el volumen en banco de «{mark}»")]
                      for mark, bench, bank in marks],
        }
        return self._run(project, DIGITIZE, settings=settings)

    def area(self, project: Any, boundary: str) -> Any:
        """``demo.area``: el área del límite ``boundary`` (el nombre o el uid de lo
        importado) → la cifra ``demo.boundary_area`` (ha)."""
        return self._run(project, AREA, inputs=self.uses(AREA, boundary=boundary))

    def bench_years(self, project: Any) -> Any:
        """``demo.bench_years``: años de cada banco con la producción vigente."""
        return self._run(project, BENCH_YEARS, inputs=self.uses(BENCH_YEARS),
                         params=(PRODUCTION,))

    def bench_years_job(self, project: Any, *, executor: str = "job_thread") -> Any:
        """``demo.bench_years`` como trabajo de la 004 (plan 008 §7.1): la registra «en curso»
        con el ejecutor del trabajo (``job_thread`` o ``job_process``) y lo que lee al empezar
        (los bancos y la producción vigentes), y devuelve su ``OperationHandle``. El trabajo se
        lanza con su ``uid`` (el ``operation_uid`` de la petición; en las pruebas, el
        autodiagnóstico de la 004 hace de cálculo) y se incorpora con
        :meth:`ingest_bench_years`."""
        if not self._active:
            raise RuntimeError("la demostración no está registrada (register)")
        operations = self.module("core.provenance.operations")
        return operations.begin_operation(project, BENCH_YEARS, settings={},
                                          inputs=list(self.uses(BENCH_YEARS)),
                                          params=[PRODUCTION], executor=executor)

    def ingest_bench_years(self, project: Any, handle: Any, outcome: Any) -> Any:
        """Incorpora a la operación ``handle`` de :meth:`bench_years_job` su trabajo terminado
        (``outcome``, el ``JobOutcome`` de ``jobs.ingest.job_outcome``) con
        ``core.provenance.operations.ingest_job``: los años de cada banco con la producción que
        leyó la operación al empezar (la del trabajo), en ``demo_bench_years`` y sus cifras.
        Devuelve su ``IngestOutcome``: obsoleta, con la causa, si lo que leyó cambió mientras
        corría."""
        operations = self.module("core.provenance.operations")
        with project.read() as conn:
            rows = self._years_rows(conn, handle)
        outputs, found = self._years_results(rows)

        def write(conn: sqlite3.Connection) -> list[Any]:
            self._replace(conn, YEARS_TABLE, rows)
            return outputs

        return operations.ingest_job(project, handle, outcome, write, figures=found)

    def stockpiles(self, project: Any, *, min_years: float = MIN_YEARS) -> tuple[Any, Any]:
        """El grupo ``demo.stockpiles``: detectar y filtrar los acopios, en la misma
        ejecución del grupo; devuelve las dos operaciones."""
        settings = {"min_years": _positive(min_years, "los años mínimos")}
        detect = self._run(project, DETECT_STOCKPILES, inputs=self.uses(DETECT_STOCKPILES))
        kept = self._run(project, FILTER_STOCKPILES, settings=settings,
                         inputs=self.uses(FILTER_STOCKPILES), params=(SWELL_FACTOR,),
                         group_uid=detect.group_uid)
        return detect, kept

    def balance(self, project: Any, *, bank_m3: float = BALANCE_BANK_M3,
                loose_m3: float = BALANCE_LOOSE_M3) -> Any:
        """``demo.balance``: K = ``loose_m3`` / ``bank_m3`` como cifra CALCULADA del parámetro
        ``demo.swell_factor`` (que no cambia; si difiere, queda el aviso de RF-008-59)."""
        settings = {"bank_m3": _positive(bank_m3, "el volumen en banco"),
                    "loose_m3": _positive(loose_m3, "el volumen esponjado")}
        return self._run(project, BALANCE, settings=settings)

    def uses(self, op_type: str, *, boundary: str | None = None) -> tuple[Any, ...]:
        """Lo que consume una operación de tipo ``op_type`` (``Use``), para empezarla o para
        preguntar a la puerta; ``demo.area`` necesita el límite (``boundary``)."""
        use = self.module("core.provenance.operations").Use
        if op_type == AREA:
            if boundary is None:
                raise ValueError("el área necesita el límite: el nombre o el uid de lo "
                                 "importado")
            return (use(boundary, "boundary"),)
        return {
            BENCH_YEARS: (use(BENCHES_TABLE, "benches"),),
            DETECT_STOCKPILES: (use(YEARS_TABLE, "bench_years"), use(MARKS_TABLE, "marks")),
            FILTER_STOCKPILES: (use(CANDIDATES_TABLE, "candidates"),),
            BALANCE: (),
            DIGITIZE: (),
        }[op_type]

    def gate(self, project: Any, op_type: str, *, boundary: str | None = None) -> Any:
        """La puerta antes de ``op_type`` (``core.provenance.gate.can_run``) sin nada pendiente
        de la comprobación de apertura: ``Ready``, ``Blocked`` o ``Pending``."""
        gate = self.module("core.provenance.gate")
        return gate.can_run(project, op_type, self.uses(op_type, boundary=boundary),
                            pending=gate.CheckState())

    def boundary_name(self, project: Any) -> str | None:
        """El nombre del último límite importado vivo (``core_imported_*``, de entidades), o
        ``None``."""
        live = self.module("core.datasets.model").LIVE_STATUSES
        marks = ", ".join("?" for _ in live)
        with project.read() as conn:
            row = conn.execute(
                f"SELECT name FROM gb_dataset WHERE substr(name, 1, ?) = ? AND kind = 'vector' "
                f"AND status IN ({marks}) ORDER BY fid DESC LIMIT 1",
                (len(IMPORTED_PREFIX), IMPORTED_PREFIX, *(str(status) for status in live)),
            ).fetchone()
        return None if row is None else row[0]

    def current_figure(self, project: Any, key: str,
                       scope: Mapping[str, Any] | None = None) -> Any:
        """La cifra vigente ``key`` (``core.provenance.lineage.current_figure``) o ``None``."""
        return self.module("core.provenance.lineage").current_figure(project, key, scope)

    def figures(self, project: Any, operation_uid: str) -> tuple[list[Any], list[Any]]:
        """Las cifras que registró la operación ``operation_uid`` (``FigureRecord``), en su
        orden, y los avisos de RF-008-59 de las que calculan un parámetro
        (``figures.divergences``), como ``(cifras, avisos)``."""
        figures = self.module("core.provenance.figures")
        with project.read() as conn:
            rows = conn.execute(f"SELECT {figures.RECORD_COLUMNS} FROM gb_figure "
                                "WHERE operation_uid = ? ORDER BY fid",
                                (operation_uid,)).fetchall()
            warnings = figures.divergences(conn, operation_uid)
        return [figures.FigureRecord.from_row(row) for row in rows], warnings

    # --- Ejecución --------------------------------------------------------------------------

    def _run(self, project: Any, op_type: str, *, settings: Mapping[str, Any] | None = None,
             inputs: Sequence[Any] = (), params: Sequence[str] = (),
             group_uid: str | None = None) -> Any:
        if not self._active:
            raise RuntimeError("la demostración no está registrada (register)")
        operations = self.module("core.provenance.operations")
        with operations.operation(project, op_type, settings=dict(settings or {}),
                                  inputs=list(inputs), params=list(params),
                                  group_uid=group_uid) as handle:
            self._bodies[op_type](handle)
        return handle

    def _recompute(self, request: Any) -> Any:
        """La función de recálculo de las repetibles: repite su cuerpo con lo vigente."""
        with request.operation() as handle:
            self._bodies[request.op_type](handle)
        return handle

    def _spec(self, table: str, role: str, *, editable: bool = False) -> Any:
        model = self.module("core.datasets.model")
        reader = self.module("core.content.builtin").GPKG_LAYER.id
        return model.DatasetSpec(table, DEMO_CODE, "table", "gpkg", table, reader=reader,
                                 role=role, qgis_editable=editable)

    def _replace(self, conn: sqlite3.Connection, table: str,
                 rows: Sequence[Sequence[Any]]) -> None:
        """La tabla ``table`` del proyecto con exactamente ``rows``."""
        base = self.module("core.gpkg.base")
        columns = _TABLE_COLUMNS[table]
        exists = conn.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?",
                              (table,)).fetchone()
        if exists is None:
            base.create_attribute_table(
                conn, table, [base.ColumnDef(name, sql_type) for name, sql_type in columns],
                _TABLE_TITLES[table], "Tabla sintética de la demostración de la spec 008")
        else:
            conn.execute(f'DELETE FROM "{table}"')
        names = ", ".join(f'"{name}"' for name, _type in columns)
        marks = ", ".join("?" for _ in columns)
        conn.executemany(f'INSERT INTO "{table}" ({names}) VALUES ({marks})',
                         [tuple(row) for row in rows])

    def _locator(self, conn: sqlite3.Connection, handle: Any, role: str) -> Any:
        """El dato que consume la operación con el papel ``role``."""
        registry = self.module("core.datasets.registry")
        (item,) = [item for item in handle.inputs if item.role == role]
        record = registry.get(conn, item.uid)
        if record is None or str(record.store) != "gpkg" or record.selector is not None:
            raise ValueError(f"«{item.name}» no es una tabla entera de project.gpkg")
        return record

    @staticmethod
    def _param(handle: Any, key: str) -> Any:
        (param,) = [param for param in handle.params if param.key == key]
        return param

    def _digitize(self, handle: Any) -> None:
        settings = handle.settings
        with handle.project.write_transaction() as conn:
            self._replace(conn, BENCHES_TABLE, settings["benches"])
            self._replace(conn, MARKS_TABLE, settings["marks"])
            handle.complete(conn, outputs=[self._spec(BENCHES_TABLE, "benches"),
                                           self._spec(MARKS_TABLE, "marks", editable=True)])

    def _area(self, handle: Any) -> None:
        units = self.module("core.units")
        figures = self.module("core.provenance.figures")
        with handle.project.write_transaction() as conn:
            record = self._locator(conn, handle, "boundary")
            hectares = units.convert(self._area_m2(conn, record), "m2", "ha")
            handle.complete(conn, figures=[figures.FigureSpec(BOUNDARY_AREA, hectares, "ha")])

    def _area_m2(self, conn: sqlite3.Connection, record: Any) -> float:
        """El área planimétrica (m²) de los polígonos de la capa de ``record``, en su CRS, que
        tiene que ser uno proyectado en metros del catálogo (nunca se supone)."""
        if record.crs_epsg is None:
            raise ValueError(f"«{record.name}» no tiene CRS de EPSG: su área no se calcula "
                             "(el CRS no se supone)")
        self.module("core.georef.crs").load_catalog().horizontal(record.crs_epsg)
        wkb = self.module("core.gpkg.wkb")
        row = conn.execute("SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
                           (record.locator,)).fetchone()
        if row is None:
            raise ValueError(f"«{record.name}» no es una capa de entidades")
        parts: list[float] = []
        for (blob,) in conn.execute(f'SELECT "{row[0]}" FROM "{record.locator}" '
                                    f'WHERE "{row[0]}" IS NOT NULL'):
            geometry = wkb.decode_geometry(blob)
            if geometry.geometry_type == "POLYGON":
                polygons = [geometry.coords]
            elif geometry.geometry_type == "MULTIPOLYGON":
                polygons = list(geometry.coords)
            else:
                raise ValueError(f"«{record.name}» tiene una geometría "
                                 f"{geometry.geometry_type}: el área es de polígonos")
            for exterior, *holes in polygons:
                parts.append(_ring_area(exterior.tolist()))
                parts.extend(-_ring_area(hole.tolist()) for hole in holes)
        return math.fsum(parts)

    def _years_rows(self, conn: sqlite3.Connection,
                    handle: Any) -> list[tuple[str, float, float]]:
        """Banco, tonelaje y años de cada banco con la producción que leyó ``handle``."""
        units = self.module("core.units")
        param = self._param(handle, PRODUCTION)
        production = units.convert(param.value, param.unit, "t/yr")
        record = self._locator(conn, handle, "benches")
        return [(bench, tonnes, tonnes / production) for bench, tonnes in conn.execute(
            f'SELECT bench, tonnage_t FROM "{record.locator}" ORDER BY fid')]

    def _years_results(self, rows: Sequence[tuple[str, float, float]]) -> tuple[list[Any],
                                                                               list[Any]]:
        """Las salidas y las cifras de los años por banco ``rows``."""
        figures = self.module("core.provenance.figures")
        return ([self._spec(YEARS_TABLE, "bench_years")],
                [figures.FigureSpec(YEARS_FIGURE, years, "yr", scope={"bench": bench})
                 for bench, _tonnes, years in rows])

    def _bench_years(self, handle: Any) -> None:
        with handle.project.write_transaction() as conn:
            rows = self._years_rows(conn, handle)
            self._replace(conn, YEARS_TABLE, rows)
            outputs, found = self._years_results(rows)
            handle.complete(conn, outputs=outputs, figures=found)

    def _detect(self, handle: Any) -> None:
        with handle.project.write_transaction() as conn:
            years_table = self._locator(conn, handle, "bench_years").locator
            marks_table = self._locator(conn, handle, "marks").locator
            years = dict(conn.execute(f'SELECT bench, years FROM "{years_table}"'))
            rows = [(mark, bench, bank, years[bench]) for mark, bench, bank in conn.execute(
                f'SELECT mark, bench, bank_m3 FROM "{marks_table}" ORDER BY fid')
                if bench in years]
            self._replace(conn, CANDIDATES_TABLE, rows)
            handle.complete(conn, outputs=[self._spec(CANDIDATES_TABLE, "candidates")])

    def _filter(self, handle: Any) -> None:
        figures = self.module("core.provenance.figures")
        swell = float(self._param(handle, SWELL_FACTOR).value)
        minimum = float(handle.settings["min_years"])
        with handle.project.write_transaction() as conn:
            table = self._locator(conn, handle, "candidates").locator
            rows = [(mark, bench, bank * swell, years) for mark, bench, bank, years in
                    conn.execute(f'SELECT mark, bench, bank_m3, years FROM "{table}" '
                                 "ORDER BY fid") if years >= minimum]
            self._replace(conn, STOCKPILES_TABLE, rows)
            total = math.fsum(loose for _mark, _bench, loose, _years in rows)
            handle.complete(conn, outputs=[self._spec(STOCKPILES_TABLE, "stockpiles")],
                            figures=[figures.FigureSpec(STOCKPILE_VOLUME, total, "m3")])

    def _balance(self, handle: Any) -> None:
        figures = self.module("core.provenance.figures")
        swell = float(handle.settings["loose_m3"]) / float(handle.settings["bank_m3"])
        with handle.project.write_transaction() as conn:
            handle.complete(conn, figures=[figures.FigureSpec(
                SWELL_FIGURE, swell, "-", parameter_key=SWELL_FACTOR)])
