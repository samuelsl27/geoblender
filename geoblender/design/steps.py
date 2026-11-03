# SPDX-License-Identifier: GPL-3.0-or-later
"""El cálculo de las envolventes y el escalonado por pasos, con presupuesto y cancelación (spec 013,
T17; HU-013-1, HU-013-3; RF-013-03, RF-013-33; RNF-013-01, RNF-013-07; plan 013 §5.3.2, D-14, D-20,
D-27).

Todo lo que la orden de ``bl`` hace en el hilo de Blender mientras calcula es un generador de
:class:`~core.project.model.Progress` que agrupa sus unidades en pasos de ``budget_s`` como mucho
(``gis.masks.compile.pace_units``: 256 filas de un barrido, un bloque de la búsqueda exacta, una
banda de filas, una banda de escritura, una lectura) y cuyo último paso lleva el resultado:

- :func:`preview_steps`: la vista previa de semillas, dominios y restricciones (RF-013-03); solo
  lee (``design.preview.summarize_steps``).
- :func:`envelope_run` y :func:`design_run`: **«Calcular»** (D-14). Compilan antes las máscaras si
  faltan (como operación propia, por pasos), preparan y rechazan (los errores de RF-013-16 salen
  **al avanzar**, antes de calcular), calculan (``design.pipeline``) y dejan cada rejilla en un
  temporal junto a su destino, con su hash por bandas, y cada tabla con el suyo. **No hay operación,
  ni dato, ni tabla, ni cifra todavía.** El último paso lleva la :class:`Calculation`.
- :class:`Calculation`: lo calculado y todavía sin registrar. :meth:`~Calculation.create`
  (**«Crear»**) abre la operación, mueve los temporales, escribe las tablas y las cifras y completa,
  todo en **una** transacción (``DesignWriter.commit``); :meth:`~Calculation.discard`
  (**«Cancelar»**, cerrar la ventana) borra los temporales. Se usa también como gestor de contexto:
  al salir sin haber creado, descarta.

**Cancelar** (RF-013-33): cerrar el generador antes del último paso (Esc, desactivar Geoblender)
borra los temporales y no deja nada registrado; el tiempo de cancelación es el de un paso. Lo que se
compiló antes (las máscaras) es una operación propia y no se deshace. Después del último paso, la
:class:`Calculation` es de quien la recibió: cerrar el generador no la toca.

El cálculo es el mismo que el de ``store.run_envelope`` y ``store.run_design`` (el recálculo de lo
obsoleto, el hito H1): comparten ``store.prepare_*_units`` y ``store.compute_*_steps``. Lo que cambia es
de dónde salen los parámetros (aquí se resuelven hoy, versión → proyecto, sin escribir: no hay
operación que los anote) y que nada se confirma. Si alguno cambia entre «Calcular» y «Crear», el
resultado ya no le corresponde (``des.input_changed``), como una entrada que cambia.

Python puro (nivel 8): no importa ``reserves`` ni ``bl``.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from types import TracebackType

from ..core.datasets.model import DatasetSpec
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore, definition
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.masks.access import MaskSet
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.store import StoreProject
from . import pipeline, preview, provenance, store
from .messages import DesignError
from .model import DesignRequest, EnvelopeRequest
from .preview import Notice
from .seeds import SeedPlan, SeedSet, pace_progress

__all__ = [
    "Calculation",
    "design_run",
    "envelope_run",
    "preview_steps",
    "resolve_values",
]

_PREPARE_PHASE = "prepare"
_DONE_PHASE = "calculated"
_READY, _CREATED, _DISCARDED = "ready", "created", "discarded"


def resolve_values(project: StoreProject, version_uid: str, keys: Iterable[str]
                   ) -> dict[str, object]:
    """El valor de cada parámetro de ``keys`` para la versión ``version_uid`` como lo leería una
    operación que empezara ahora (versión → proyecto, RF-009-24), **sin escribir**: el de su fila o,
    si no la tiene, el valor por defecto de su definición (``None`` si no lo hay). Es lo que hace
    falta para calcular sin haber empezado la operación (``begin_operation`` crearía las filas que
    faltan, y la operación aún no existe: D-14)."""
    wanted = tuple(dict.fromkeys(keys))
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(conn, wanted, (VERSION_SCOPE, PROJECT_SCOPE),
                                                     version=version_uid)
    values: dict[str, object] = {}
    for key in wanted:
        resolved = found.get(key)
        if resolved is not None:
            values[key] = resolved.value
        else:
            declared = definition(key)
            values[key] = None if declared is None else declared.default
    return values


class Calculation:
    """Un cálculo hecho y **sin registrar** (véase el módulo): su ``outcome``
    (``pipeline.EnvelopeOutcome`` o ``pipeline.DesignOutcome``), los ``notices`` que enseña la
    ventana junto a su resumen —de la envolvente, los de sus semillas; del escalonado, los de su
    informe—, las ``seeds`` (``None`` en un escalonado), el tipo de operación (``op_type``), su
    ``name`` y la ``version`` (su código). Mientras esté abierta (:attr:`open`), sus rejillas
    esperan en temporales junto a su destino: hay que crearla o descartarla."""

    def __init__(self, *, project: StoreProject, writer: store.DesignWriter,
                 start: store.OperationStart, outcome: pipeline.EnvelopeOutcome
                 | pipeline.DesignOutcome, notices: Sequence[Notice], seeds: SeedSet | None,
                 values: Mapping[str, object]) -> None:
        self._project = project
        self._writer = writer
        self._start = start
        self._values = dict(values)
        self._state = _READY
        self.op_type = start.op_type
        self.name = start.name
        self.version = start.version_code
        self.outcome = outcome
        self.notices = tuple(notices)
        self.seeds = seeds

    def __repr__(self) -> str:
        return f"<Calculation {self.op_type} «{self.name}» {self.version} {self._state}>"

    @property
    def open(self) -> bool:
        """Si todavía se puede crear o descartar (no se ha hecho ninguna de las dos cosas)."""
        return self._state == _READY

    @property
    def figures(self) -> tuple[FigureSpec, ...]:
        """Las cifras CALCULADO que se registrarán (RF-013-17)."""
        return self.outcome.figures

    @property
    def message(self) -> str:
        """El mensaje de la operación: lo que dice el resumen de lo calculado."""
        return self.outcome.message

    @property
    def specs(self) -> tuple[DatasetSpec, ...]:
        """Las salidas preparadas (con su hash), en el orden de su tipo de operación."""
        return self._writer.specs

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Los avisos y notas del resumen, línea a línea, en ``language`` (``"es"`` o ``"en"``)."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices
                     if notice.severity == "warning")

    def create(self) -> store.Stored:
        """**«Crear»**: registra el cálculo, en una sola transacción de escritura
        (``DesignWriter.commit``: abre la operación, mueve los temporales, escribe las tablas y las
        cifras y completa). Antes comprueba que los parámetros que leyó siguen valiendo lo mismo, y
        ``commit`` que las máscaras están al día y que ninguna entrada cambió. Si algo falla, no queda
        nada (ni operación, ni dato, ni temporal) y el error sigue: ``DesignError``
        ``des.input_changed`` si cambió un parámetro o una entrada, ``MaskError``, los de la 008 y
        los de disco. ``RuntimeError`` si ya se creó o se descartó."""
        if self._state != _READY:
            raise RuntimeError(f"el cálculo «{self.name}» ya no está abierto ({self._state})")
        try:
            self._check_parameters()
            stored = self._writer.commit(self._start, figures=self.outcome.figures,
                                         message=self.outcome.message)
        except BaseException:
            self.discard()
            raise
        self._state = _CREATED
        return stored

    def discard(self) -> None:
        """**«Cancelar»**: borra los temporales y no deja nada. No hace nada si ya se descartó o se
        creó (lo creado no se toca)."""
        if self._state == _READY:
            self._state = _DISCARDED
            self._writer.close()

    def __enter__(self) -> Calculation:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.discard()

    def _check_parameters(self) -> None:
        """RF-013-17, D-14: los parámetros que leyó el cálculo valen lo mismo que ahora."""
        now = resolve_values(self._project, self._start.version_uid, self._values)
        for key, value in self._values.items():
            if now.get(key) != value:
                raise DesignError("des.input_changed", obj=f"Parámetro «{key}»",
                                  field="parámetros", value=key)


def preview_steps(project: StoreProject, plan: SeedPlan, version_uid: str, *,
                  budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """La vista previa de ``plan`` (``plan.seeds`` y ``plan.domain``; una ``EnvelopeRequest`` sirve)
    para la versión activa ``version_uid`` (RF-013-03) por pasos de ``budget_s`` como mucho: el
    último ``Progress`` lleva el ``PreviewSummary``. Solo lee: no compila las máscaras que falten ni
    escribe nada; cerrarla a mitad no deja nada. Los rechazos salen al avanzar
    (``design.preview.summarize_steps``)."""
    return preview.summarize_steps(project, plan, version_uid, budget_s=budget_s)


def envelope_run(project: StoreProject, request: EnvelopeRequest, *, version: str | None,
                 masks: MaskSet | None = None, budget_s: float = STEP_BUDGET_S
                 ) -> Iterator[Progress]:
    """**«Calcular»** la envolvente ``request`` en la versión ``version`` (uid o código) por pasos
    de ``budget_s`` como mucho (véase el módulo): el último ``Progress`` lleva la
    :class:`Calculation`, con la rejilla en su temporal y **nada registrado**. ``masks``: las de la
    versión, al día (``gis.masks.access.MaskSet``); sin ellas se cargan, compilándolas antes por
    pasos si no están al día (RF-013-04).

    Los rechazos salen **al avanzar**, antes de calcular y sin dejar nada: sin versión activa o no
    editable, nombre repetido, máscaras (``MaskError``), semillas o dominio inválidos,
    pendiente fuera de rango, un sector que toca el dominio con la búsqueda pendiente (RF-013-05) y
    un perfil sin valor (RF-013-19). Cerrar el generador a mitad borra el temporal."""
    return _envelope_steps(project, request, version, masks, budget_s)


def design_run(project: StoreProject, request: DesignRequest, surface: str, *,
               version: str | None, masks: MaskSet | None = None,
               budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**«Calcular»** el escalonado ``request`` de la envolvente ``request.envelope`` de la versión
    ``version`` sobre la superficie de partida ``surface`` (el nombre de su dato): lo mismo que
    :func:`envelope_run`, con las dos rejillas (la superficie de diseño y las cotas de las bermas)
    en temporales y las dos tablas (bermas e informe) preparadas con su hash en memoria."""
    return _design_steps(project, request, surface, version, masks, budget_s)


def _prepare_steps[T](units: Generator[None, None, T], budget_s: float
                      ) -> Generator[Progress, None, T]:
    """Las unidades de preparar un cálculo agrupadas en pasos; devuelve lo que preparan."""
    return pipeline.forward(pace_progress(
        units, budget_s, phase=_PREPARE_PHASE, running="Preparando el cálculo…",
        finished="Cálculo preparado", total=6))


def _envelope_steps(project: StoreProject, request: EnvelopeRequest, version: str | None,
                    masks: MaskSet | None, budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.ENVELOPE)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: store.PreparedEnvelope = yield from _prepare_steps(
        store.prepare_envelope_units(project, request, found, loaded), budget_s)
    writer = store.DesignWriter(project, provenance.ENVELOPE, request.name, version=found.uid)
    try:
        values = resolve_values(project, found.uid, prepared.start.params)
        outcome: pipeline.EnvelopeOutcome = yield from store.compute_envelope_steps(
            project, writer, request, loaded, prepared.seeds, values, budget_s)
        calculation = Calculation(
            project=project, writer=writer, start=prepared.start, outcome=outcome,
            notices=preview.seed_notices(request, prepared.seeds), seeds=prepared.seeds,
            values=values)
    except BaseException as error:  # un fallo o cerrar el generador: no queda el temporal
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _design_steps(project: StoreProject, request: DesignRequest, surface: str,
                  version: str | None, masks: MaskSet | None, budget_s: float
                  ) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.STEPPED)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: store.PreparedDesign = yield from _prepare_steps(
        store.prepare_design_units(project, request, surface, found, loaded), budget_s)
    writer = store.DesignWriter(project, provenance.STEPPED, request.name, version=found.uid)
    try:
        values = resolve_values(project, found.uid, prepared.start.params)
        outcome: pipeline.DesignOutcome = yield from store.compute_design_steps(
            project, writer, request, surface, loaded, prepared, values, prepared.start.settings,
            budget_s)
        calculation = Calculation(
            project=project, writer=writer, start=prepared.start, outcome=outcome,
            notices=outcome.report.notices, seeds=None, values=values)
    except BaseException as error:  # un fallo o cerrar el generador: no quedan los temporales
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)
