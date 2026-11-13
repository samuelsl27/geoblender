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
- :func:`excavation_area_run` (spec 014, T06; RF-014-01): «Calcular» el recinto excavable de la
  versión (``des.excavation_area``) del mismo modo; el último paso lleva su :class:`Calculation`.
- :func:`quarry_run` (spec 014, T19; RF-014-12, RF-014-29, RF-014-30): «Calcular» la cantera con
  dos superficies (``des.quarry``) del mismo modo, con los avisos de su resumen; sin la
  confirmación, se para antes de calcular si las semillas de la 013 de un lado caen fuera de la
  coronación y de las zonas a sostener, con sus grupos (T43; RF-014-03).
- :func:`edge_transition_run` (spec 014, T28; RF-014-19 a RF-014-21, RF-014-29): «Calcular» la
  transición de una superficie de diseño con el terreno no afectado (``des.edge_transition``) del
  mismo modo, con el aviso del salto creado que deja.
- :func:`fill_only_run` (spec 014, T30; RF-014-22 a RF-014-25, RF-014-29): «Calcular» el diseño
  «solo relleno» de una envolvente de la versión (``des.fill_only``) del mismo modo, con los avisos
  del informe de su escalonado.
- :func:`refit_run` (spec 014, T32; RF-014-27 a RF-014-29): «Calcular» el ajuste de unas
  superficies de diseño de la versión a su límite vigente (``des.refit``) del mismo modo, con el
  aviso de las que no hacía falta ajustar.
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
from types import MappingProxyType, TracebackType

from ..core.datasets.model import DatasetSpec
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore, definition
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.masks.access import MaskSet
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.store import StoreProject
from . import edges, fronts, pipeline, preview, provenance, quarry, refit, store
from .messages import DesignError
from .model import DesignRequest, EnvelopeRequest, FillOnlyRequest, QuarryRequest, RefitRequest
from .preview import Notice
from .seeds import SeedPlan, SeedSet, pace_progress

__all__ = [
    "Calculation",
    "design_run",
    "edge_transition_run",
    "envelope_run",
    "excavation_area_run",
    "fill_only_run",
    "preview_steps",
    "quarry_run",
    "refit_run",
    "resolve_values",
]

_PREPARE_PHASE = "prepare"
_DONE_PHASE = "calculated"
_OUTSIDE_PHASE = "seeds_outside"  # la cantera parada por sus semillas fuera (T43; RF-014-03)
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
    (``pipeline.EnvelopeOutcome``, ``pipeline.DesignOutcome`` o, de un recinto,
    ``quarry.AreaOutcome``, de una cantera, ``quarry.QuarryOutcome``, de una transición,
    ``edges.EdgeTransition``, de un diseño «solo relleno», ``fronts.FillOnlyOutcome``, y de un
    ajuste, ``refit.RefitOutcome``), los
    ``notices`` que enseña
    la ventana junto a su resumen —de la envolvente, los de sus semillas; del escalonado, los de su
    informe; de la cantera, los suyos y los del informe de cada lado—, las ``seeds`` (``None``
    salvo en una envolvente), el tipo de operación (``op_type``), su
    ``name`` y la ``version`` (su código). Mientras esté abierta (:attr:`open`), sus rejillas
    esperan en temporales junto a su destino: hay que crearla o descartarla."""

    def __init__(self, *, project: StoreProject, writer: store.DesignWriter,
                 start: store.OperationStart, outcome: pipeline.EnvelopeOutcome
                 | pipeline.DesignOutcome | quarry.AreaOutcome | quarry.QuarryOutcome
                 | edges.EdgeTransition | fronts.FillOnlyOutcome | refit.RefitOutcome,
                 notices: Sequence[Notice],
                 seeds: SeedSet | None,
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

    @property
    def settings(self) -> Mapping[str, object]:
        """Los ajustes que anotará la operación al crearla (los de lo pedido: la superficie de una
        transición, T28…), de solo lectura."""
        return MappingProxyType(dict(self._start.settings))

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


def excavation_area_run(project: StoreProject, name: str, surface: str, *, version: str | None,
                        masks: MaskSet | None = None, budget_s: float = STEP_BUDGET_S
                        ) -> Iterator[Progress]:
    """**«Calcular»** el recinto excavable ``name`` de la versión ``version`` sobre la superficie
    de partida ``surface`` (el nombre de su dato) por pasos de ``budget_s`` como mucho (spec 014,
    T06; RF-014-01, RF-014-29; «Límite desde el perímetro…»): el último ``Progress`` lleva la
    :class:`Calculation` de ``des.excavation_area``, con la rejilla ``des_rcn_`` (1 dentro, sin
    dato fuera) en su temporal y la cifra ``des.rcn_area_m2``, y **nada registrado**. ``masks``,
    como en :func:`envelope_run`.

    Los rechazos salen **al avanzar**, antes de escribir nada: sin versión activa o no editable,
    máscaras (``MaskError``), la superficie (``des.surface_*``), un recinto vacío
    (``des.quarry_area_empty``, con lo que lo vacía) y el nombre repetido. Cerrar el generador a
    mitad borra el temporal."""
    return _area_steps(project, name, surface, version, masks, budget_s)


def quarry_run(project: StoreProject, request: QuarryRequest, *, version: str | None,
               masks: MaskSet | None = None, budget_s: float = STEP_BUDGET_S,
               confirm_outside: bool = False) -> Iterator[Progress]:
    """**«Calcular»** la cantera con dos superficies ``request`` de la versión ``version`` por
    pasos de ``budget_s`` como mucho (spec 014, T19; RF-014-12, RF-014-29, RF-014-30; «Cantera con
    dos superficies…»): el último ``Progress`` lleva la :class:`Calculation` de ``des.quarry``, con
    sus cinco rejillas (las dos superficies, sus envolventes y la clasificación) en temporales, sus
    dos tablas (las bermas de las dos y el informe) preparadas, sus cifras y los avisos del
    resumen (los de sus capas, las semillas de la 013 fuera de la coronación, el desdoblado sobre
    terreno sin explotar, «explotación hasta la final» y los del escalonado de cada lado), y
    **nada registrado**. ``masks``, como en :func:`envelope_run`.

    **Semillas fuera** (T43; RF-014-03, error 10): si las semillas de la 013 de un lado caen fuera
    de la coronación y de las zonas a sostener y no viene la confirmación (``confirm_outside``), se
    para tras armar las piezas, antes de calcular y sin escribir nada (ni un temporal): su último
    ``Progress`` (fase ``seeds_outside``) lleva en ``result``, en lugar de la
    :class:`Calculation`, sus avisos (``preview.Notice``: por lado, ``des.quarry_seeds_outside``
    con su superficie y un ``des.quarry_seed_group`` por grupo, con sus celdas, su área y su
    centro). Con la confirmación, calcula; el resumen sigue diciendo los grupos.

    Los rechazos salen **al avanzar**, antes de escribir nada: el primero, antes de leer nada, un
    lado con la euclídea exacta (``des.quarry_final_exact``, ``des.quarry_exploitation_exact``;
    T45: la cantera solo admite el *chamfer* 5×5); después, sin versión activa o no editable,
    máscaras (``MaskError``), la superficie, un recinto vacío, un sector del recinto con la
    búsqueda de intocables pendiente (``des.sector_pending``, RF-014-30), las capas (fondos,
    corredores, zonas), un perfil o un parámetro de la 014 sin valor (RF-013-19) y el nombre
    repetido. Cerrar el generador a mitad borra los temporales."""
    return _quarry_steps(project, request, version, masks, budget_s, confirm_outside)


def edge_transition_run(project: StoreProject, name: str, surface: str, start: str, *,
                        version: str | None, masks: MaskSet | None = None,
                        budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**«Calcular»** la transición ``name`` de la superficie de diseño ``surface`` de la versión
    ``version`` con el terreno no afectado, sobre la superficie de partida ``start`` (los nombres
    de sus datos), por pasos de ``budget_s`` como mucho (spec 014, T28; RF-014-19 a RF-014-21,
    RF-014-29; «Transiciones con el terreno no afectado»): el último ``Progress`` lleva la
    :class:`Calculation` de ``des.edge_transition``, con la superficie con la transición
    (``des_trn_``) en su temporal, el informe del salto creado (``des_erp_``) preparado, sus cifras
    y el aviso de RF-014-21 si queda dentro del salto admitido menos del porcentaje admitido, y
    **nada registrado**. ``masks``, como en :func:`envelope_run`.

    Los rechazos salen **al avanzar**, antes de escribir nada: sin versión activa o no editable,
    máscaras (``MaskError``), una superficie que no es de diseño de la versión
    (``des.edge_not_design_surface``), las superficies (``des.surface_*``), el ángulo de transición
    sin valor (``des.quarry_param_missing``, D-9) o un parámetro fuera de rango y el nombre
    repetido. Cerrar el generador a mitad borra el temporal."""
    return _transition_steps(project, name, surface, start, version, masks, budget_s)


def fill_only_run(project: StoreProject, request: FillOnlyRequest, *, version: str | None,
                  masks: MaskSet | None = None, budget_s: float = STEP_BUDGET_S
                  ) -> Iterator[Progress]:
    """**«Calcular»** el diseño «solo relleno» ``request`` de la versión ``version`` por pasos de
    ``budget_s`` como mucho (spec 014, T30; RF-014-22 a RF-014-25, RF-014-29; «Solo relleno…»):
    el último ``Progress`` lleva la :class:`Calculation` de ``des.fill_only``, con su superficie
    (``des_srf_``) en un temporal, su informe (``des_rpt_``) preparado, sus cifras (las del
    escalonado de la 013 frente al terreno registrado y ``des.fill_only_cut_m3``) y sus avisos (los
    de las láminas que caen fuera del relleno admitido o en un intocable, T55, y después los del
    informe de su escalonado), y **nada registrado**. ``masks``, como en :func:`envelope_run`.

    Los rechazos salen **al avanzar**, antes de escribir nada: sin versión activa o no editable,
    máscaras (``MaskError``), la envolvente y las superficies (``des.surface_*``), un sector con la
    búsqueda pendiente que toca la envolvente (RF-013-05), las láminas de agua (su capa, su campo,
    una cota que falta, dos que se solapan), un perfil sin valor (RF-013-19), el nombre repetido y
    los de RF-014-25: un movimiento en un intocable (nombrándolo, con su volumen) o un corte de
    1 m³ o más. Cerrar el generador a mitad borra el temporal."""
    return _fill_only_steps(project, request, version, masks, budget_s)


def refit_run(project: StoreProject, request: RefitRequest, *, version: str | None,
              masks: MaskSet | None = None, budget_s: float = STEP_BUDGET_S
              ) -> Iterator[Progress]:
    """**«Calcular»** el ajuste ``request`` de unas superficies de diseño de la versión ``version``
    a su límite vigente por pasos de ``budget_s`` como mucho (spec 014, T32; RF-014-27 a
    RF-014-29; «Ajustar el diseño a un límite nuevo…»): el último ``Progress`` lleva la
    :class:`Calculation` de ``des.refit``, con la superficie ajustada de cada una
    (``des_adj_<nombre>_<superficie>``) en su temporal, la cifra ``des.refit_m3`` de cada una y el
    aviso ``des.refit_not_needed`` de las que el límite nuevo no corta, y **nada registrado**.
    ``masks``, como en :func:`envelope_run` (las del límite nuevo).

    Los rechazos salen **al avanzar**, antes de escribir nada: sin versión activa o no editable,
    máscaras (``MaskError``), una superficie que no es de diseño de la versión
    (``des.edge_not_design_surface``), las superficies (``des.surface_*``), un perfil sin cara o
    sin factor de malla (RF-013-19), el nombre repetido y, si la petición trae un ángulo para una
    superficie que no es la cara de su perfil, ``des.refit_angle`` (RF-014-28). Cerrar el generador
    a mitad borra los temporales."""
    return _refit_steps(project, request, version, masks, budget_s)


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


def _area_steps(project: StoreProject, name: str, surface: str, version: str | None,
                masks: MaskSet | None, budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.EXCAVATION_AREA)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: store.PreparedArea = yield from _prepare_steps(
        store.prepare_area_units(project, name, surface, found, loaded), budget_s)
    writer = store.DesignWriter(project, provenance.EXCAVATION_AREA, name, version=found.uid)
    try:
        outcome: quarry.AreaOutcome = yield from store.compute_area_steps(
            writer, name, prepared, budget_s)
        calculation = Calculation(project=project, writer=writer, start=prepared.start,
                                  outcome=outcome, notices=(), seeds=None, values={})
    except BaseException as error:  # un fallo o cerrar el generador: no queda el temporal
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _quarry_steps(project: StoreProject, request: QuarryRequest, version: str | None,
                  masks: MaskSet | None, budget_s: float, confirm_outside: bool
                  ) -> Generator[Progress, None, None]:
    quarry._check_metric(request)  # T45: la petición sola, antes de leer nada
    found = store.require_version(project, version, provenance.QUARRY)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: store.PreparedQuarry = yield from _prepare_steps(
        store.prepare_quarry_units(project, request, found, loaded), budget_s)
    values = resolve_values(project, found.uid, prepared.start.params)
    if not confirm_outside:  # RF-014-03: antes de calcular, sin escribir nada
        outside: tuple[Notice, ...] = yield from pipeline.forward(pace_progress(
            store._seeds_outside_units(loaded, prepared.parts, values), budget_s,
            phase=_OUTSIDE_PHASE, running="Buscando las semillas fuera de la coronación…",
            finished="Semillas comprobadas"))
        if outside:
            yield Progress(_OUTSIDE_PHASE, 1, 1, "Semillas fuera de la coronación y de las zonas "
                           "a sostener: falta su confirmación para calcular", result=outside)
            return
    writer = store.DesignWriter(project, provenance.QUARRY, request.name, version=found.uid)
    try:
        calculated: store.QuarryCalculated = yield from store.compute_quarry_steps(
            writer, request, loaded, prepared, values, prepared.start.settings, budget_s)
        outcome = calculated.outcome
        sides = tuple(notice for side in (outcome.final, outcome.exploitation)
                      for notice in side.design.report.notices)
        calculation = Calculation(project=project, writer=writer, start=prepared.start,
                                  outcome=outcome, notices=(*calculated.notices, *sides),
                                  seeds=None, values=values)
    except BaseException as error:  # un fallo o cerrar el generador: no quedan los temporales
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _transition_steps(project: StoreProject, name: str, surface: str, start: str,
                      version: str | None, masks: MaskSet | None, budget_s: float
                      ) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.EDGE_TRANSITION)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: store.PreparedTransition = yield from _prepare_steps(
        store.prepare_transition_units(project, name, surface, start, found, loaded), budget_s)
    writer = store.DesignWriter(project, provenance.EDGE_TRANSITION, name, version=found.uid)
    try:
        values = resolve_values(project, found.uid, prepared.start.params)
        outcome: edges.EdgeTransition = yield from store.compute_transition_steps(
            writer, name, prepared, loaded, values, budget_s)
        calculation = Calculation(project=project, writer=writer, start=prepared.start,
                                  outcome=outcome, notices=outcome.notices, seeds=None,
                                  values=values)
    except BaseException as error:  # un fallo o cerrar el generador: no queda el temporal
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _fill_only_steps(project: StoreProject, request: FillOnlyRequest, version: str | None,
                     masks: MaskSet | None, budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.FILL_ONLY)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: store.PreparedFillOnly = yield from _prepare_steps(
        store.prepare_fill_only_units(project, request, found, loaded), budget_s)
    writer = store.DesignWriter(project, provenance.FILL_ONLY, request.name, version=found.uid)
    try:
        values = resolve_values(project, found.uid, prepared.start.params)
        outcome: fronts.FillOnlyOutcome = yield from store.compute_fill_only_steps(
            writer, request, loaded, prepared, values, prepared.start.settings, budget_s)
        calculation = Calculation(project=project, writer=writer, start=prepared.start,
                                  outcome=outcome,
                                  notices=(*outcome.notices, *outcome.design.report.notices),
                                  seeds=None, values=values)
    except BaseException as error:  # un fallo o cerrar el generador: no queda el temporal
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _refit_steps(project: StoreProject, request: RefitRequest, version: str | None,
                 masks: MaskSet | None, budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.REFIT)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: store.PreparedRefit = yield from _prepare_steps(
        store.prepare_refit_units(project, request, found, loaded), budget_s)
    writer = store.DesignWriter(project, provenance.REFIT, request.name, version=found.uid)
    try:
        values = resolve_values(project, found.uid, prepared.start.params)
        outcome: refit.RefitOutcome = yield from store.compute_refit_steps(
            writer, request, loaded, prepared, values, budget_s)
        calculation = Calculation(project=project, writer=writer, start=prepared.start,
                                  outcome=outcome, notices=outcome.notices, seeds=None,
                                  values=values)
    except BaseException as error:  # un fallo o cerrar el generador: no quedan los temporales
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)
