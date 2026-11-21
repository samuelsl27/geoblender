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
- :func:`platform_run` (spec 015, T12; RF-015-03, RF-015-13, RF-015-29): «Calcular» una plataforma
  (``des.platform``) del mismo modo: deja la superficie (``des_psf_``) en un temporal y el **resumen**
  (:class:`~.preview.PlatformSummary`: las cifras, los avisos —el salto creado, la magnitud, lo que llega
  a celdas sin dato, lo que no mueve por la restricción de otra entidad, el orden de la cantera— y lo que
  quedará obsoleto al crearla) y **nada en el proyecto**; crearla (T13; RF-015-01, RF-015-02,
  RF-015-04) es :meth:`Calculation.create`: los parámetros de su entidad, la operación, la superficie, su
  tabla y su informe y las cifras, en **una** transacción.
- :func:`stockpile_run` (spec 016, T12; RF-016-04 a 08, RF-015-03, RF-015-29): «Calcular» una detección de acopios
  (``des.stockpile_detect``, de una versión, o ``des.stockpile_detect_project``, del proyecto, D-15) del mismo modo: deja el
  **resultado** (``design.stockpiles.StockpileOutcome``) y el **resumen** (:class:`~.preview.StockpileSummary`: cada acopio con
  su plano, huella, volumen, espesor máximo y notas, los avisos con su lugar, las marcas rechazadas, los candidatos y lo que
  quedará obsoleto al repetirla) y **nada en el proyecto**: ni la base de datos, ni los ficheros, ni temporales. Crearla
  (T13; RF-016-02, RF-015-02, RNF-016-03) es :meth:`Calculation.create` o, por pasos, :meth:`Calculation.create_steps`: las
  tablas y las rejillas dispersas se preparan en su temporal y **una** transacción registra los parámetros de la entidad, la
  operación, los datos y las cifras (:func:`~.stockpile_store.create_detection_steps`).
- :func:`access_run` (spec 017, T17; RF-017-24, RF-017-25, RF-015-03, RF-015-29): «Calcular» la accesibilidad de las pistas (``des.road_access``, de una versión, sin cadena y
  sin huella) del mismo modo: deja el **resultado** (``design.road_model.AccessOutcome``, con las cifras y los avisos) y el **resumen**
  (:class:`~.access_store.AccessSummary`: las cotas, las listas de bermas, plataformas y zonas «requiere acceso» comunicadas o no, los avisos y lo que quedará obsoleto al
  repetirla) y **nada en el proyecto**. Crearla (T17b; RF-015-02, RNF-017-10) es :meth:`Calculation.create` o, por pasos, :meth:`Calculation.create_steps`: la rejilla de lo
  alcanzable y las tablas se preparan en su temporal y **una** transacción registra los parámetros de la entidad, la operación, los datos y las cifras
  (:func:`~.access_store.create_access_steps`).
- :func:`road_run` (spec 017, T20b; RF-017-17, RF-017-22, RF-017-12, RF-017-23, RF-015-03, RF-015-29): «Calcular» una pista (``des.road``, de una versión, con cadena y huella) del mismo modo: deja el
  **resultado** (``design.road_model.RoadOutcome``: el eje, la rasante, la sección, el grabado y las veintitrés cifras) y el **resumen** (:class:`~.preview.RoadSummary`: las cifras, la holgura del pasillo,
  los avisos con su lugar, la calzada que no queda en su rasante con la restricción o la entidad que lo impide y lo que quedará obsoleto) y **nada en el proyecto**: ni la base de datos, ni los ficheros, ni
  siquiera un temporal (la superficie entera la escribe «Crear», T21). Pide **dos confirmaciones expresas** antes de crearla: la **pendiente media por encima de pm** con un motivo (RF-017-17, que no bloquea)
  y la **calzada que no queda en su rasante** (RF-017-22): :attr:`Calculation.needs_mean_confirmation`, :attr:`~Calculation.needs_carriageway_confirmation` y :meth:`Calculation.confirm_road`.
- :func:`road_propose_run` (spec 017, T33; RF-017-28, RF-015-03, RF-015-29, RF-017-30): «Calcular» una propuesta del trazado (``des.road_propose``, de una versión, **sin cadena, sin superficie y sin huella**: no es una
  entidad) del mismo modo: deja el **resultado** (``design.road_model.ProposalOutcome``: el eje, la rasante y las dos cifras) y el **resumen** (:class:`~.road_store.ProposalSummary`: la longitud, las pendientes, el radio
  mínimo y los avisos con su lugar; la pendiente media por encima de pm **avisa y no pide confirmación**) y **nada en el proyecto**. Crearla es :meth:`Calculation.create` o, por pasos, :meth:`Calculation.create_steps`: la
  capa de líneas con Z ``des_rpl_`` (editable en QGIS) en su temporal y **una** transacción que registra la operación, el dato y las cifras (:func:`~.road_store.create_propose_steps`).
- :func:`removal_run` (spec 016, T20; RF-016-11 a 15, RF-015-03, RF-015-29): «Calcular» la retirada de un acopio
  (``des.stockpile_removal``) del mismo modo: deja la superficie (``des_psf_``) en un temporal, el **resumen**
  (:class:`~.preview.RemovalSummary`: las cifras, **la lista de lo que se le apoyaba**, la pared y lo que pide confirmar) y
  **nada en el proyecto**; crearla es :meth:`Calculation.create` (con :meth:`Calculation.confirm_removal` si pide confirmar):
  los parámetros de su entidad, la operación, la superficie, su huella, su informe y las cifras, en **una** transacción
  (:func:`~.supported_store.create_removal`).
- :func:`body_run` (spec 016, T25; RF-016-20 a 22, RF-015-03, RF-015-29): «Calcular» un cuerpo apoyado (``des.body``) del mismo modo:
  deja el espesor disperso (``des_bdt_``) y la superficie con el techo (``des_psf_``, «sobre una base») o la base dispersa (``des_bds_``,
  «bajo un techo») en temporales, el **resumen** (:class:`~.preview.BodySummary`: las cifras, lo lejano de los datos con su lugar y los
  avisos) y **nada en el proyecto**; crearlo es :meth:`Calculation.create` (:func:`~.supported_store.create_body`: una transacción).
- :func:`buttress_run` (spec 016, T27 y T28; RF-016-17 a RF-016-19, RF-015-03, RF-015-29): «Calcular» un contrafuerte (``des.buttress``) del mismo modo:
  deja la superficie (``des_psf_``) en un temporal, el **resumen** (:class:`~.preview.ButtressSummary`: el volumen, el área y la altura máxima,
  si declara «sin corte» sobre su zona de coronación y, desde la T28 —RF-016-19, RF-015-13—, **el pie cortado** por el borde del relleno
  admitido con su área, su volumen y el salto creado de ese borde, y lo que no rellena por la restricción de otra entidad, con ella: avisos
  que no impiden crearlo) y **nada en el proyecto**; crearlo es :meth:`Calculation.create`
  (:func:`~.supported_store.create_buttress`: una transacción; la restricción que declara la encadena la orden, ``after_entity_change``).
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
from . import (
    access_store,
    buttress,
    edges,
    entity_store,
    fronts,
    pipeline,
    platform,
    preview,
    provenance,
    quarry,
    refit,
    removal,
    road_store,
    stockpile_store,
    stockpiles,
    store,
    supported_store,
    thickness,
)
from .messages import DesignError
from .model import (
    BodyRequest,
    ButtressRequest,
    DesignRequest,
    EnvelopeRequest,
    FillOnlyRequest,
    PlatformRequest,
    QuarryRequest,
    RefitRequest,
    RemovalRequest,
    StockpileRequest,
)
from .params import ANTHROPIC_PRESENCE
from .preview import Notice
from .road_model import AccessOutcome, AccessRequest, ProposalOutcome, RoadOutcome, RoadRequest
from .seeds import SeedPlan, SeedSet, pace_progress

__all__ = [
    "Calculation",
    "access_run",
    "body_run",
    "buttress_run",
    "design_run",
    "edge_transition_run",
    "envelope_run",
    "excavation_area_run",
    "fill_only_run",
    "platform_run",
    "preview_steps",
    "quarry_run",
    "refit_run",
    "removal_run",
    "resolve_values",
    "road_propose_run",
    "road_run",
    "stockpile_run",
]

_PREPARE_PHASE = "prepare"
_DONE_PHASE = "calculated"
_SUMMARY_PHASE = "platform_summary"  # el resumen de una plataforma (T12)
_STOCKPILE_SUMMARY_PHASE = "stockpile_summary"  # el resumen de una detección de acopios (016, T12)
_CREATED_PHASE = "created"  # la detección de acopios guardada (016, T13)
_REMOVAL_SUMMARY_PHASE = "removal_summary"  # el resumen de la retirada de un acopio (016, T20)
_BODY_SUMMARY_PHASE = "body_summary"  # el resumen de un cuerpo apoyado (016, T25)
_BUTTRESS_SUMMARY_PHASE = "buttress_summary"  # el resumen de un contrafuerte (016, T27)
_ACCESS_SUMMARY_PHASE = "access_summary"  # el resumen de una accesibilidad (017, T17)
_ROAD_SUMMARY_PHASE = "road_summary"  # el resumen de una pista (017, T20b)
_PROPOSE_SUMMARY_PHASE = "propose_summary"  # el resumen de una propuesta del trazado (017, T33)
_OUTSIDE_PHASE = "seeds_outside"  # la cantera parada por sus semillas fuera (T43; RF-014-03)
_READY, _CREATED, _DISCARDED = "ready", "created", "discarded"


def resolve_values(project: StoreProject, version_uid: str, keys: Iterable[str]
                   ) -> dict[str, object]:
    """El valor de cada parámetro de ``keys`` para la versión ``version_uid`` como lo leería una
    operación que empezara ahora (versión → proyecto, RF-009-24), **sin escribir**: el de su fila o,
    si no la tiene, el valor por defecto de su definición (``None`` si no lo hay). Es lo que hace
    falta para calcular sin haber empezado la operación (``begin_operation`` crearía las filas que
    faltan, y la operación aún no existe: D-14). Con ``version_uid`` vacío (spec 016, T12: una operación **de proyecto**, la
    detección de acopios sobre una superficie del proyecto) solo cuenta el ámbito del proyecto."""
    wanted = tuple(dict.fromkeys(keys))
    chain = (VERSION_SCOPE, PROJECT_SCOPE) if version_uid else (PROJECT_SCOPE,)
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(conn, wanted, chain, version=version_uid or None)
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
    ``edges.EdgeTransition``, de un diseño «solo relleno», ``fronts.FillOnlyOutcome``, de un
    ajuste, ``refit.RefitOutcome``, de una plataforma, ``platform.PlatformOutcome``, y de una detección
    de acopios, ``stockpiles.StockpileOutcome``), los
    ``notices`` que enseña
    la ventana junto a su resumen —de la envolvente, los de sus semillas; del escalonado, los de su
    informe; de la cantera, los suyos y los del informe de cada lado; de cada aviso del salto
    creado, sus primeros tramos y cuántos faltan, ``edges.summary_notices``, T61: el informe del
    diseño los guarda todos; un ajuste, que no guarda informe, los enseña todos—, las ``seeds``
    (``None``
    salvo en una envolvente), el tipo de operación (``op_type``), su
    ``name`` y la ``version`` (su código). De una plataforma (spec 015, T12) lleva además ``entity``
    (la :class:`~.entity_store.PreparedPlatform`: su código, su geometría, sus parámetros con su origen,
    lo que anotará la operación) y ``summary`` (el :class:`~.preview.PlatformSummary`); **crearla** (T13) es
    :meth:`create`, que escribe además los parámetros de su entidad. De una **detección de acopios** (spec 016, T12) lleva
    en ``entity`` la :class:`~.stockpile_store.PreparedDetection` y en ``summary`` el :class:`~.preview.StockpileSummary`;
    crearla es :meth:`create` o :meth:`create_steps` (T13). **De una pista** (spec 017, T20b) lleva en ``entity`` la :class:`~.road_store.PreparedRoad` y en ``summary`` el :class:`~.preview.RoadSummary`, con
    sus dos confirmaciones (:meth:`confirm_road`): la pendiente media por encima de pm, con un motivo, y la calzada que no queda en su rasante. Mientras esté abierta
    (:attr:`open`), sus rejillas esperan en temporales junto a su destino: hay que crearla o
    descartarla."""

    def __init__(self, *, project: StoreProject, writer: store.DesignWriter,
                 start: store.OperationStart, outcome: pipeline.EnvelopeOutcome
                 | pipeline.DesignOutcome | quarry.AreaOutcome | quarry.QuarryOutcome
                 | edges.EdgeTransition | fronts.FillOnlyOutcome | refit.RefitOutcome
                 | platform.PlatformOutcome | stockpiles.StockpileOutcome | removal.RemovalOutcome
                 | thickness.BodyOutcome | buttress.ButtressOutcome | AccessOutcome | RoadOutcome | ProposalOutcome,
                 notices: Sequence[Notice],
                 seeds: SeedSet | None,
                 values: Mapping[str, object],
                 entity: entity_store.PreparedPlatform | stockpile_store.PreparedDetection
                 | supported_store.PreparedRemoval | supported_store.PreparedBody | supported_store.PreparedButtress
                 | access_store.PreparedAccess | road_store.PreparedRoad | road_store.PreparedProposal | None = None,
                 summary: preview.PlatformSummary | preview.StockpileSummary | preview.RemovalSummary
                 | preview.BodySummary | preview.ButtressSummary | access_store.AccessSummary | preview.RoadSummary | road_store.ProposalSummary | None = None) -> None:
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
        self.entity = entity
        self.summary = summary
        self._removal_confirmed = (False, False)
        self._road_confirmed: tuple[bool, bool, str | None] = (False, False, None)

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

    @property
    def needs_confirmation(self) -> bool:
        """Si es una plataforma con una contrapendiente que pasa de su tolerancia y la persona aún no
        la ha confirmado: no se podrá crear (RF-015-23). Falso en cualquier otra."""
        found = self.outcome
        return isinstance(found, platform.PlatformOutcome) and found.needs_confirmation

    def confirm_counterslope(self) -> None:
        """La confirmación expresa de la contrapendiente de una plataforma (RF-015-23): la deja
        confirmada sin recalcular (``PlatformOutcome.confirm``). ``TypeError`` si no es una
        plataforma."""
        found = self.outcome
        if not isinstance(found, platform.PlatformOutcome):
            raise TypeError(f"solo una plataforma tiene contrapendiente que confirmar, no "
                            f"«{self.op_type}»")
        self.outcome = found.confirm()

    @property
    def needs_resting_confirmation(self) -> bool:
        """Si es una retirada de un acopio —o una plataforma que retira un acopio «como plataforma», T21— con algo apoyado (RF-016-14) y la
        persona aún no lo ha confirmado: no se podrá crear. Falso en cualquier otra."""
        found = self.entity
        return (isinstance(found, supported_store.PreparedRemoval | entity_store.PreparedPlatform) and bool(found.resting)
                and not self._removal_confirmed[0])

    @property
    def needs_wall_confirmation(self) -> bool:
        """Si es una retirada que deja una pared (RF-016-15) y la persona aún no la ha confirmado: no se podrá crear. Falso en cualquier
        otra."""
        found = self.outcome
        return (isinstance(self.entity, supported_store.PreparedRemoval) and isinstance(found, removal.RemovalOutcome)
                and found.wall is not None and found.wall.needs_confirmation and not self._removal_confirmed[1])

    @property
    def needs_wall_reason(self) -> bool:
        """Si la pared de la retirada pasa de 45° y 3 m (CA-9) y pide, además, un motivo que quede registrado."""
        found = self.outcome
        return (isinstance(self.entity, supported_store.PreparedRemoval) and isinstance(found, removal.RemovalOutcome)
                and found.wall is not None and found.wall.needs_reason)

    def confirm_removal(self, *, resting: bool = False, wall: bool = False) -> None:
        """La confirmación expresa de lo que se apoya en el acopio que se retira (``resting``, RF-016-14) y de la pared que deja
        (``wall``, RF-016-15): queda dicha para :meth:`create` (que la registra con su decisor y su fecha) sin recalcular. Sustituye a
        la anterior. ``TypeError`` si no es una retirada. **Una plataforma que retira un acopio «como plataforma»** (T21; RF-016-16) solo tiene
        que confirmar lo apoyado: su pared es la de su borde, un aviso de la plataforma (``wall`` no cuenta)."""
        platform_of_stockpile = isinstance(self.entity, entity_store.PreparedPlatform) and self.entity.removed is not None
        if not isinstance(self.entity, supported_store.PreparedRemoval) and not platform_of_stockpile:
            raise TypeError(f"solo una retirada de un acopio tiene algo que confirmar, no «{self.op_type}»")
        self._removal_confirmed = (bool(resting), bool(wall))

    @property
    def needs_mean_confirmation(self) -> bool:
        """Si es una pista cuya pendiente media pasa de la pendiente media máxima de su perfil (RF-017-17) y la persona aún no la ha confirmado: no se podrá crear sin la confirmación expresa y un motivo
        (que queda registrado y no la bloquea, D-6). Falso en cualquier otra."""
        found = self.outcome
        return isinstance(found, RoadOutcome) and found.mean_exceeded and not self._road_confirmed[0]

    @property
    def needs_carriageway_confirmation(self) -> bool:
        """Si es una pista con alguna celda de la calzada que no queda en su rasante (RF-017-22) y la persona aún no lo ha confirmado: no se podrá crear. Falso en cualquier otra."""
        found = self.outcome
        return isinstance(found, RoadOutcome) and bool(found.off_level) and not self._road_confirmed[1]

    @property
    def road_confirmed(self) -> tuple[bool, bool, str | None]:
        """Lo que la persona ha confirmado de una pista (:meth:`confirm_road`): la pendiente media, la calzada y el motivo de la media."""
        return self._road_confirmed

    def confirm_road(self, *, mean: bool = False, carriageway: bool = False, reason: str | None = None) -> None:
        """La confirmación expresa de una pista (RF-017-17, RF-017-22): la de la **pendiente media por encima de pm** (``mean``, con su motivo ``reason``, que queda registrado con quién y cuándo y no
        bloquea) y la de la **calzada que no queda en su rasante** (``carriageway``); queda dicha para la creación (T21, que la registra con su decisor y su fecha) sin recalcular. Sustituye a la anterior.
        ``TypeError`` si no es una pista."""
        if not isinstance(self.entity, road_store.PreparedRoad):
            raise TypeError(f"solo una pista tiene una pendiente media o una calzada que confirmar, no «{self.op_type}»")
        self._road_confirmed = (bool(mean), bool(carriageway), reason)

    def ensure_road_creatable(self) -> None:
        """**No se crea la pista sin la confirmación expresa** (RF-017-17, RF-017-22; :func:`~.road_store.check_road_confirmed`): con la pendiente media por encima de pm y sin confirmar,
        ``des.road_mean_unconfirmed``; confirmada sin motivo, ``des.road_mean_reason``; con la calzada fuera de su rasante sin confirmar, ``des.road_carriageway_unconfirmed``. **Antes de escribir nada y
        sin cerrar el cálculo**: se confirma y se vuelve a crear. ``TypeError`` si no es una pista."""
        found = self.outcome
        if not isinstance(found, RoadOutcome):
            raise TypeError(f"el cálculo «{self.name}» no es el de una pista, sino «{self.op_type}»")
        mean, carriageway, reason = self._road_confirmed
        road_store.check_road_confirmed(found, mean=mean, carriageway=carriageway, reason=reason)

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Los avisos y notas del resumen, línea a línea, en ``language`` (``"es"`` o ``"en"``)."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices
                     if notice.severity == "warning")

    def create(self, *, decided_by: str | None = None) -> store.Stored:
        """**«Crear»**: registra el cálculo, en una sola transacción de escritura
        (``DesignWriter.commit``: abre la operación, mueve los temporales, escribe las tablas y las
        cifras y completa). Antes comprueba que los parámetros que leyó siguen valiendo lo mismo, y
        ``commit`` que las máscaras están al día y que ninguna entrada cambió. Si algo falla, no queda
        nada (ni operación, ni dato, ni temporal) y el error sigue: ``DesignError``
        ``des.input_changed`` si cambió un parámetro o una entrada, ``MaskError``, los de la 008 y
        los de disco. ``RuntimeError`` si ya se creó o se descartó.

        **Una plataforma** (spec 015, T13; RF-015-01, RF-015-02, RF-015-04) se registra con
        :func:`~.entity_store.create_platform`: además de lo anterior, escribe en esa misma transacción los
        parámetros de su entidad como filas de la versión, con su origen, antes de abrir la operación.
        Si tiene una contrapendiente sin confirmar (``needs_confirmation``, RF-015-23), se rechaza
        (``DesignError`` ``des.platform_counter_unconfirmed``) **antes de escribir nada y sin cerrar el
        cálculo**: se confirma (:meth:`confirm_counterslope`) y se vuelve a crear.

        **Una accesibilidad** (spec 017, T17b; RF-017-24, RF-015-02) se registra del mismo modo con :func:`~.access_store.create_access_steps`: la rejilla de lo alcanzable y las
        cuatro tablas se preparan y se escriben en su temporal, y una sola transacción registra los parámetros de la entidad, la operación con sus entradas, los datos y las cifras.

        **Una pista** (spec 017, T21; RF-017-01, RF-017-03, RF-017-23, RF-015-02) se registra del mismo modo con :func:`~.road_store.create_road_steps`: la superficie entera y las tres tablas
        (la huella de la sección, el eje por estaciones y el informe) se preparan y se escriben en su temporal y una sola transacción registra los parámetros de la entidad, la operación con sus entradas
        y sus ajustes (con lo confirmado, :meth:`confirm_road`), los datos y las cifras; **no declara ninguna restricción**. Sin la confirmación de la pendiente media o de la calzada, se rechaza
        (``des.road_mean_unconfirmed``, ``des.road_mean_reason``, ``des.road_carriageway_unconfirmed``) **antes de escribir nada y sin cerrar el cálculo**.

        **Una propuesta del trazado** (spec 017, T33; RF-017-28, RF-015-02) se registra con :func:`~.road_store.create_propose_steps`: la capa propuesta (``des_rpl_``, editable en QGIS) se escribe en su temporal y una
        sola transacción registra la operación con sus entradas, el dato y las cifras; **ninguna superficie ni parámetro de entidad**, y sin confirmaciones (la pendiente media por encima de pm solo avisa).

        **Una detección de acopios** (spec 016, T13; RF-016-02, RF-015-02) se registra con
        :func:`~.stockpile_store.create_detection_steps`, la misma en el proyecto (``des.stockpile_detect_project``) y en una
        versión (``des.stockpile_detect``): las tablas y las rejillas dispersas se preparan y se escriben en su temporal, y
        una sola transacción registra los parámetros de la entidad, la operación, los datos y las cifras. Es
        :meth:`create_steps` llevado hasta el final. ``decided_by``: el decisor de los parámetros de la entidad (por defecto,
        quien tiene abierto el proyecto)."""
        if isinstance(self.entity, stockpile_store.PreparedDetection | access_store.PreparedAccess | road_store.PreparedRoad | road_store.PreparedProposal):
            stored: store.Stored | None = None
            for step in self.create_steps(decided_by=decided_by):
                if step.result is not None:
                    stored = step.result
            assert stored is not None  # el último paso lo lleva
            return stored
        if self._state != _READY:
            raise RuntimeError(f"el cálculo «{self.name}» ya no está abierto ({self._state})")
        if isinstance(self.entity, supported_store.PreparedRemoval):
            return self._create_removal(self.entity, decided_by)
        if isinstance(self.entity, supported_store.PreparedBody):
            return self._create_body(self.entity, decided_by)
        if isinstance(self.entity, supported_store.PreparedButtress):
            return self._create_buttress(self.entity, decided_by)
        if self.entity is not None:
            self._platform().ensure_creatable()  # sin cerrar el cálculo: se confirma y se crea
            if isinstance(self.entity, entity_store.PreparedPlatform) and self.entity.origin is not None:
                # retirar un acopio «como plataforma» (T21; RF-016-14): sin confirmar lo apoyado, no se crea (y el cálculo sigue abierto)
                removal.check_resting_confirmed(self.entity.origin.item.name, self.entity.resting,
                                                confirmed=self._removal_confirmed[0])
        try:
            self._check_parameters()
            if self.entity is not None:
                stored = entity_store.create_platform(self._project, self._writer, self.entity,
                                                      self._platform(), decided_by=decided_by,
                                                      confirmed_resting=self._removal_confirmed[0])
            else:
                stored = self._writer.commit(self._start, figures=self.outcome.figures,
                                             message=self.outcome.message)
        except BaseException:
            self.discard()
            raise
        self._state = _CREATED
        return stored

    def _create_removal(self, found: supported_store.PreparedRemoval, decided_by: str | None) -> store.Stored:
        """**«Crear» una retirada de un acopio** (spec 016, T20; RF-016-11, RF-016-13 a 15, RF-015-02): lo registra
        :func:`~.supported_store.create_removal` en una sola transacción. Sin la confirmación expresa de lo que se le apoyaba o de la
        pared (:meth:`confirm_removal`), y de más de 45° y 3 m sin su motivo, se rechaza (``des.removal_resting_unconfirmed``,
        ``des.removal_wall_unconfirmed``, ``des.removal_wall_reason``) **antes de escribir nada y sin cerrar el cálculo**: se confirma y se
        vuelve a crear."""
        outcome = self.outcome
        assert isinstance(outcome, removal.RemovalOutcome)
        resting, wall = self._removal_confirmed
        supported_store.check_removal_confirmed(found, outcome, resting=resting, wall=wall)  # sin cerrar el cálculo
        try:
            self._check_parameters()
            stored = supported_store.create_removal(self._project, self._writer, found, outcome, resting=resting, wall=wall,
                                                    decided_by=decided_by)
        except BaseException:
            self.discard()
            raise
        self._state = _CREATED
        return stored

    def _create_body(self, found: supported_store.PreparedBody, decided_by: str | None) -> store.Stored:
        """**«Crear» un cuerpo apoyado** (spec 016, T25; RF-016-20, RF-015-02): lo registra :func:`~.supported_store.create_body` en una
        sola transacción (el espesor, la superficie o la base, la huella, el informe, los parámetros de su entidad y las cifras). No pide
        ninguna confirmación (no retira nada ni deja una pared); si algo falla, o lo que consume cambió, no queda nada y el cálculo
        queda descartado."""
        outcome = self.outcome
        assert isinstance(outcome, thickness.BodyOutcome)
        try:
            self._check_parameters()
            stored = supported_store.create_body(self._project, self._writer, found, outcome, decided_by=decided_by)
        except BaseException:
            self.discard()
            raise
        self._state = _CREATED
        return stored

    def _create_buttress(self, found: supported_store.PreparedButtress, decided_by: str | None) -> store.Stored:
        """**«Crear» un contrafuerte** (spec 016, T27; RF-016-17, RF-015-02): lo registra :func:`~.supported_store.create_buttress` en una sola
        transacción (la superficie, la huella con su zona de coronación, el informe, los parámetros de su entidad y las cifras). No pide
        ninguna confirmación (no retira nada ni deja una pared: el pie cortado, T28, es un aviso que no impide crearlo); si algo falla, o lo
        que consume cambió, no queda nada y el cálculo queda descartado. La restricción «sin corte» que declara la encadena la orden."""
        outcome = self.outcome
        assert isinstance(outcome, buttress.ButtressOutcome)
        try:
            self._check_parameters()
            stored = supported_store.create_buttress(self._project, self._writer, found, outcome, decided_by=decided_by)
        except BaseException:
            self.discard()
            raise
        self._state = _CREATED
        return stored

    def create_steps(self, *, decided_by: str | None = None, budget_s: float = STEP_BUDGET_S
                     ) -> Generator[Progress, None, None]:
        """**«Crear» una detección de acopios, una accesibilidad, una pista o una propuesta del trazado por pasos** (spec 016, T13; RF-016-02, RNF-016-03 y 05; spec 017, T17b, T21 y T33;
        RF-017-24, RF-017-30, RF-017-01, RF-017-28): lo que hace :meth:`create`, con cada llamada del hilo de Blender de ``budget_s`` como mucho (montar y escribir
        cada rejilla y cada tabla en su temporal, por pasos) y la transacción final como último paso; el último ``Progress`` lleva lo
        guardado (:class:`~.store.Stored`) en ``result``. Cerrar el generador antes (Esc), un fallo o lo que consume cambiado
        desde que se calculó (``des.input_changed``) **no dejan nada** y descartan el cálculo. ``RuntimeError`` si ya no está
        abierto; ``TypeError`` si no es una detección de acopios, una accesibilidad, una pista ni una propuesta. **Una propuesta del trazado** (T33) escribe su capa propuesta en su temporal y la registra en una
        sola transacción (:func:`~.road_store.create_propose_steps`: **ninguna superficie, ningún parámetro de entidad**; sin confirmaciones). **Una pista** sin la confirmación expresa de la pendiente media o de la calzada
        (:meth:`ensure_road_creatable`) se rechaza **antes de escribir nada y sin cerrar el cálculo**: se confirma (:meth:`confirm_road`) y se vuelve a crear."""
        found = self.entity
        if not isinstance(found, stockpile_store.PreparedDetection | access_store.PreparedAccess | road_store.PreparedRoad | road_store.PreparedProposal):
            raise TypeError(f"solo una detección de acopios, una accesibilidad, una pista o una propuesta del trazado se crea por pasos, no «{self.op_type}»")
        if self._state != _READY:
            raise RuntimeError(f"el cálculo «{self.name}» ya no está abierto ({self._state})")
        outcome = self.outcome
        if isinstance(found, road_store.PreparedRoad):
            self.ensure_road_creatable()  # sin cerrar el cálculo: se confirma y se vuelve a crear
        try:
            self._check_parameters()
            if isinstance(found, road_store.PreparedRoad):
                assert isinstance(outcome, RoadOutcome)
                mean, carriageway, reason = self._road_confirmed
                stored: store.Stored = yield from road_store.create_road_steps(
                    self._project, self._writer, found, outcome, mean=mean, carriageway=carriageway, reason=reason, decided_by=decided_by, budget_s=budget_s)
                done = f"Pista «{self.name}» guardada"
            elif isinstance(found, road_store.PreparedProposal):
                assert isinstance(outcome, ProposalOutcome)
                stored = yield from road_store.create_propose_steps(self._project, self._writer, found, outcome, budget_s=budget_s)
                done = f"Trazado «{self.name}» guardado"
            elif isinstance(found, access_store.PreparedAccess):
                assert isinstance(outcome, AccessOutcome)
                stored = yield from access_store.create_access_steps(
                    self._project, self._writer, found, outcome, decided_by=decided_by, budget_s=budget_s)
                done = f"Accesibilidad «{self.name}» guardada"
            else:
                assert isinstance(outcome, stockpiles.StockpileOutcome)
                stored = yield from stockpile_store.create_detection_steps(
                    self._project, self._writer, found, outcome, decided_by=decided_by, budget_s=budget_s)
                done = f"Detección «{self.name}» guardada"
        except BaseException:  # un fallo o cerrar el generador: no queda nada
            self.discard()
            raise
        self._state = _CREATED
        yield Progress(_CREATED_PHASE, 1, 1, done, result=stored)

    def _platform(self) -> platform.PlatformOutcome:
        """El resultado de una plataforma (``TypeError`` si el cálculo no lo es: un error del programa)."""
        found = self.outcome
        if not isinstance(found, platform.PlatformOutcome):
            raise TypeError(f"el cálculo «{self.name}» no es el de una plataforma, sino «{self.op_type}»")
        return found

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


def platform_run(project: StoreProject, request: PlatformRequest, *, version: str | None,
                 masks: MaskSet | None = None, code: str | None = None,
                 supersedes: str | None = None, insert_before: str | None = None,
                 confirm_counterslope: bool = False, budget_s: float = STEP_BUDGET_S
                 ) -> Iterator[Progress]:
    """**«Calcular»** la plataforma ``request`` en la versión ``version`` (uid o código) por pasos de
    ``budget_s`` como mucho (spec 015, T12; RF-015-03, RF-015-13, RF-015-29; «Plataforma…»): el último
    ``Progress`` lleva la :class:`Calculation` de ``des.platform``, con su superficie (``des_psf_``) en
    un temporal, su resumen (``Calculation.summary``: las cifras, los avisos y lo que quedará obsoleto
    al crearla) y **nada registrado ni escrito en el proyecto**: ni la base de datos, ni las
    operaciones, los datos o los parámetros. ``masks``, como en :func:`envelope_run`. ``code``,
    ``supersedes`` e ``insert_before``, los de ``entity_store.prepare_platform_units`` (recalcular una
    entidad que ya está en la versión, sustituir una operación e insertar antes de otra entidad);
    ``confirm_counterslope``, la confirmación expresa de una contrapendiente (RF-015-23; también
    ``Calculation.confirm_counterslope``).

    Los rechazos salen **al avanzar**, antes de escribir nada: los de ``prepare_platform_units``
    (sin versión activa o no editable, geometría, campos, parámetros, partida, falta de dato, un
    sector pendiente…, RF-015-06 a RF-015-09) y los del cálculo. Cerrar el generador a mitad (Esc) o un
    fallo después de dejar el temporal lo borra y no deja nada (RF-015-29)."""
    return _platform_steps(project, request, version, masks, code, supersedes, insert_before,
                           confirm_counterslope, budget_s)


def stockpile_run(project: StoreProject, request: StockpileRequest, *, version: str | None,
                  masks: MaskSet | None = None, code: str | None = None,
                  supersedes: str | None = None, budget_s: float = STEP_BUDGET_S
                  ) -> Iterator[Progress]:
    """**«Calcular»** la detección de acopios ``request`` por pasos de ``budget_s`` como mucho (spec 016, T12; RF-016-04
    a 08, RF-015-03, RF-015-29; RNF-016-03 y 05; «Acopio (detectar, retirar)…»): el último ``Progress`` lleva la
    :class:`Calculation` de ``des.stockpile_detect`` (la superficie es de la versión ``version``) o de
    ``des.stockpile_detect_project`` (la superficie es del proyecto, también sin versión activa, D-15), con su resultado
    (``Calculation.outcome``: ``design.stockpiles.StockpileOutcome``), su resumen (``Calculation.summary``: los acopios con su
    plano, huella, volumen, espesor máximo y notas, los avisos con su lugar, las marcas **rechazadas** nombrando marca, caso y
    lugar sin registrarlas, los candidatos y lo que quedará obsoleto al crearla) y **nada registrado ni escrito en el
    proyecto**: ni la base de datos, ni las operaciones, los datos, los parámetros o los ficheros. ``version`` es la versión
    activa (uid o código; ``None`` si no hay: solo vale una superficie del proyecto) y ``masks``, las de esa versión (al día;
    sin ellas se cargan, compilándolas antes si faltan: la preparación). ``code``, ``supersedes``: los de
    ``stockpile_store.prepare_detection_units`` (recalcular o repetir una detección que ya está en su ámbito y sustituir su
    operación; con ``supersedes`` el resumen dice lo que quedará obsoleto).

    Los rechazos salen **al avanzar**, antes de calcular y sin escribir nada: los de ``prepare_detection_units`` (versión,
    capa y campos, marcas solapadas, parámetros, falta de dato…, RF-016-02, 03 y 04). Los acopios que no se pueden formar no
    paran el cálculo: salen en el resumen sin registrarse. Cerrar el generador a mitad (Esc) o un fallo después de calcular no
    dejan nada (RF-015-29). Crear la detección es :meth:`Calculation.create` (T13)."""
    return _stockpile_steps(project, request, version, masks, code, supersedes, budget_s)


def access_run(project: StoreProject, request: AccessRequest, *, version: str | None, masks: MaskSet | None = None, code: str | None = None,
               supersedes: str | None = None, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**«Calcular»** la accesibilidad ``request`` en la versión ``version`` (uid o código) por pasos de ``budget_s`` como mucho (spec 017, T17; RF-017-24, RF-017-25, RF-015-03,
    RF-015-29, RF-017-30; RNF-017-05 y RNF-017-06; «Accesibilidad de las pistas…»): el último ``Progress`` lleva la :class:`Calculation` de ``des.road_access``, con su resultado
    (``Calculation.outcome``: ``design.road_model.AccessOutcome``, con las cifras y los avisos), su resumen (``Calculation.summary``: ``design.access_store.AccessSummary``: las
    cotas y las listas de bermas, plataformas y zonas «requiere acceso» comunicadas o no, los avisos —una entrada que no cae en terreno transitable, lo que no se comunica— y lo que
    quedará obsoleto al repetirla) y **nada registrado ni escrito en el proyecto**: ni la base de datos, ni las operaciones, los datos, los parámetros o los ficheros. ``masks``, como
    en :func:`envelope_run`. ``code`` y ``supersedes``, los de ``access_store.prepare_access_units`` (recalcular una accesibilidad que ya está en la versión y sustituir su operación).

    Los rechazos salen **al avanzar**, antes de calcular y sin escribir nada: los de ``prepare_access_units`` (sin versión activa o no editable, la capa de entradas y su campo, los
    parámetros sin valor, la superficie y su rejilla, las bermas, ningún punto de entrada o uno sin dato: RF-017-04). Cerrar el generador a mitad (Esc) o un fallo después de calcular
    no dejan nada (RF-015-29). **Crear** la accesibilidad es :meth:`Calculation.create` o :meth:`Calculation.create_steps` (T17b)."""
    return _access_steps(project, request, version, masks, code, supersedes, budget_s)


def road_run(project: StoreProject, request: RoadRequest, *, version: str | None, masks: MaskSet | None = None, code: str | None = None, supersedes: str | None = None,
             budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**«Calcular»** la pista ``request`` en la versión ``version`` (uid o código) por pasos de ``budget_s`` como mucho (spec 017, T20b; RF-017-17, RF-017-22, RF-017-12, RF-017-23, RF-015-03, RF-015-29,
    RF-017-30; RNF-017-06 y RNF-017-07; «Pista…»): el último ``Progress`` lleva la :class:`Calculation` de ``des.road``, con su resultado (``Calculation.outcome``: ``design.road_model.RoadOutcome``, con el eje,
    la rasante, la sección, el grabado y las veintitrés cifras), su resumen (``Calculation.summary``: :class:`~.preview.RoadSummary`: las cifras, la holgura del pasillo, los avisos con su lugar, la calzada
    que no queda en su rasante con la restricción o la entidad que lo impide, lo que la pista no mueve por una restricción y lo que quedará obsoleto al crearla) y **nada registrado ni escrito en el
    proyecto**: ni la base de datos, ni las operaciones, los datos, los parámetros o los ficheros (ni un temporal: la superficie entera la escribe «Crear»). ``masks``, como en :func:`envelope_run`. ``code`` y
    ``supersedes``, los de ``road_store.prepare_road_units`` (recalcular una pista que ya está en la versión y sustituir su operación).

    Los rechazos salen **al avanzar**, antes de escribir nada y con la capa, la pista, el campo y el valor: los de la preparación (sin versión activa o no editable, la geometría, el perfil, la partida, la
    falta de dato, los parámetros sin valor, un sector con la búsqueda pendiente: RF-017-04, RF-015-06 a RF-015-09) y los del cálculo (**sin ruta**, por sus tres causas —la red 2D, el pasillo y el presupuesto de
    estados agotado—, RF-017-12; el radio que cabe menor que Rmín, RF-017-14; el desnivel que no cabe en el eje, RF-017-16; la falta de dato bajo la sección, RF-015-09). Cerrar el generador a mitad (Esc) o un fallo
    no dejan nada (RF-015-29). Crearla es :meth:`Calculation.create` (T21), con :meth:`Calculation.confirm_road` si pide confirmar la pendiente media o la calzada (RF-017-17, RF-017-22)."""
    return _road_steps(project, request, version, masks, code, supersedes, budget_s)


def road_propose_run(project: StoreProject, request: RoadRequest, *, version: str | None, masks: MaskSet | None = None, supersedes: str | None = None,
                     budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**«Calcular»** la propuesta del trazado ``request`` en la versión ``version`` (uid o código) por pasos de ``budget_s`` como mucho (spec 017, T33; RF-017-28, RF-017-17, RF-015-03, RF-015-29, RF-017-30;
    RNF-017-06; «Proponer el trazado…»): el último ``Progress`` lleva la :class:`Calculation` de ``des.road_propose``, con su resultado (``Calculation.outcome``: ``design.road_model.ProposalOutcome``, con el eje con curvas,
    la rasante y las dos cifras), su resumen (``Calculation.summary``: :class:`~.road_store.ProposalSummary`: la longitud, las pendientes con su abscisa y su lugar, el radio mínimo y los avisos con su lugar) y **nada
    registrado ni escrito en el proyecto**: ni la base de datos, ni las operaciones, los datos o los ficheros (ni un temporal: la capa propuesta la escribe «Crear»). **Una propuesta no es una entidad**: lo mismo que la pista
    «trazar» hasta la ruta y la rasante (A1 a A5) y **sin** A6 a A9 (P-14): no graba ninguna superficie y, con la pendiente media por encima de pm, **avisa y no pide confirmación**. ``masks``, como en
    :func:`envelope_run`. ``supersedes``, el de ``road_store.prepare_propose_units`` (recalcular una propuesta que ya está en la versión).

    Los rechazos salen **al avanzar**, antes de escribir nada y con la capa, la propuesta, el campo y el valor: los de la preparación (sin versión activa o no editable, la capa de puntos, el perfil, la partida, el origen y
    el destino, la falta de dato, los parámetros de la ruta sin valor, el nombre de la capa propuesta repetido: ``des.operation_name_repeated``, un sector con la búsqueda pendiente: RF-017-04, RF-015-06 a RF-015-09) y los
    del cálculo (**sin ruta**, por sus tres causas, RF-017-12; el radio que cabe menor que Rmín, RF-017-14; el desnivel que no cabe en el eje, RF-017-16). Cerrar el generador a mitad (Esc) o un fallo no dejan nada
    (RF-015-29). Crearla es :meth:`Calculation.create` o :meth:`Calculation.create_steps`."""
    return _propose_steps(project, request, version, masks, supersedes, budget_s)


def removal_run(project: StoreProject, request: RemovalRequest, *, version: str | None,
                masks: MaskSet | None = None, code: str | None = None, supersedes: str | None = None,
                budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**«Calcular»** la retirada de un acopio ``request`` en la versión ``version`` (uid o código) por pasos de ``budget_s`` como mucho
    (spec 016, T20; RF-016-11 a 15, RF-015-03, RF-015-29; RNF-016-05; «Retirar un acopio…»): el último ``Progress`` lleva la
    :class:`Calculation` de ``des.stockpile_removal``, con su superficie (``des_psf_``) en un temporal, su resultado
    (``Calculation.outcome``: ``design.removal.RemovalOutcome``), su resumen (``Calculation.summary``: las cifras, **la lista única de
    lo que se le apoyaba**, la pared y lo que pide confirmar) y **nada registrado ni escrito en el proyecto**: ni la base de datos, ni
    las operaciones, los datos o los parámetros. ``masks``, como en :func:`envelope_run`. ``code`` y ``supersedes``, los de
    ``supported_store.prepare_removal_units`` (recalcular una retirada que ya está en la versión y sustituir su operación).

    Los rechazos salen **al avanzar**, antes de calcular y sin escribir nada: los de ``prepare_removal_units`` (sin versión activa o no
    editable, nombre y partida, el ángulo de transición, el acopio y su detección —**obsoleta: RF-016-12**—, la partida, un sector con la
    búsqueda pendiente: RF-015-07). Cerrar el generador a mitad (Esc) o un fallo después de dejar el temporal lo borra y no deja nada
    (RF-015-29). Crearla es :meth:`Calculation.create`, con :meth:`Calculation.confirm_removal` si pide confirmar lo apoyado o la
    pared (RF-016-14, RF-016-15)."""
    return _removal_steps(project, request, version, masks, code, supersedes, budget_s)


def body_run(project: StoreProject, request: BodyRequest, *, version: str | None,
             masks: MaskSet | None = None, code: str | None = None, supersedes: str | None = None,
             budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**«Calcular»** el cuerpo apoyado ``request`` en la versión ``version`` (uid o código) por pasos de ``budget_s`` como mucho (spec 016,
    T25; RF-016-20 a 22, RF-015-03, RF-015-29; RNF-016-02, RNF-016-05; «Cuerpo apoyado…»): el último ``Progress`` lleva la
    :class:`Calculation` de ``des.body``, con el espesor disperso (``des_bdt_``) y la superficie con el techo (``des_psf_``,
    «sobre una base») o la base dispersa (``des_bds_``, «bajo un techo») en temporales, su resultado (``Calculation.outcome``:
    ``design.thickness.BodyOutcome``), su resumen (``Calculation.summary``: las cifras, lo lejano de los datos con su lugar y los avisos)
    y **nada registrado ni escrito en el proyecto**: ni la base de datos, ni las operaciones, los datos o los parámetros. ``masks``,
    como en :func:`envelope_run`. ``code`` y ``supersedes``, los de ``supported_store.prepare_body_units`` (recalcular un cuerpo que ya
    está en la versión y sustituir su operación).

    Los rechazos salen **al avanzar**, antes de calcular y sin escribir nada: los de ``prepare_body_units`` (sin versión activa o no
    editable, nombre y partida —nadie parte de un cuerpo «bajo un techo»: ``des.chainless_start``—, la huella, los datos de espesor
    —uno negativo o que falta, con capa, cuerpo, campo y valor—, la distancia máxima sin valor, las superficies, un sector con la
    búsqueda pendiente) y los del cálculo (sin datos en la huella o todo lejos de ellos: RF-016-22). Cerrar el generador a mitad (Esc)
    o un fallo después de dejar el temporal lo borra y no deja nada (RF-015-29). Crearlo es :meth:`Calculation.create`."""
    return _body_steps(project, request, version, masks, code, supersedes, budget_s)


def buttress_run(project: StoreProject, request: ButtressRequest, *, version: str | None,
                 masks: MaskSet | None = None, code: str | None = None, supersedes: str | None = None,
                 budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**«Calcular»** el contrafuerte ``request`` en la versión ``version`` (uid o código) por pasos de ``budget_s`` como mucho (spec 016,
    T27; RF-016-17, RF-016-18, RF-015-03, RF-015-29; RNF-016-02, RNF-016-03; «Contrafuerte…»): el último ``Progress`` lleva la
    :class:`Calculation` de ``des.buttress``, con su superficie (``des_psf_``) en un temporal, su resultado (``Calculation.outcome``:
    ``design.buttress.ButtressOutcome``), su resumen (``Calculation.summary``: el volumen, el área y la altura máxima y si declara «sin
    corte») y **nada registrado ni escrito en el proyecto**: ni la base de datos, ni las operaciones, los datos o los parámetros.
    ``masks``, como en :func:`envelope_run`. ``code`` y ``supersedes``, los de ``supported_store.prepare_buttress_units`` (recalcular un
    contrafuerte que ya está en la versión y sustituir su operación).

    Los rechazos salen **al avanzar**, antes de calcular y sin escribir nada: los de ``prepare_buttress_units`` (sin versión activa o no
    editable, nombre y partida, la capa y su geometría, la cota de coronación y el resguardo sin valor, la cota fuera del ancla de su perfil
    —RF-016-18—, las superficies, un sector con la búsqueda pendiente) y los del cálculo (la coronación por debajo del apoyo en toda la
    zona, o ninguna celda que suba). Cerrar el generador a mitad (Esc) o un fallo después de dejar el temporal lo borra y no deja nada
    (RF-015-29). Crearlo es :meth:`Calculation.create`."""
    return _buttress_steps(project, request, version, masks, code, supersedes, budget_s)


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
                                  outcome=outcome,
                                  notices=edges.summary_notices((*calculated.notices, *sides)),
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
                                  outcome=outcome, notices=edges.summary_notices(outcome.notices),
                                  seeds=None, values=values)
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
                                  notices=edges.summary_notices(
                                      (*outcome.notices, *outcome.design.report.notices)),
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


def _stockpile_steps(project: StoreProject, request: StockpileRequest, version: str | None,
                     masks: MaskSet | None, code: str | None, supersedes: str | None, budget_s: float
                     ) -> Generator[Progress, None, None]:
    prepared: stockpile_store.PreparedDetection = yield from _prepare_steps(
        stockpile_store.prepare_detection_units(project, request, version=version, masks=masks, code=code,
                                                supersedes=supersedes), budget_s)
    writer = store.design_writer(project, prepared.op_type, request.name, version=prepared.version_uid,
                                 supersedes=supersedes)
    try:
        outcome: stockpiles.StockpileOutcome = yield from stockpile_store.detection_compute_steps(
            prepared.job, decisions=prepared.decisions, budget_s=budget_s)
        yield Progress(_STOCKPILE_SUMMARY_PHASE, 0, 1, f"Preparando el resumen de «{request.name}»…")
        summary = stockpile_store.detection_summary(project, prepared, outcome, supersedes=supersedes)
        calculation = Calculation(
            project=project, writer=writer, start=prepared.start, outcome=outcome, notices=summary.notices,
            seeds=None, values={ANTHROPIC_PRESENCE: prepared.job.params.threshold_m}, entity=prepared,
            summary=summary)
    except BaseException as error:  # un fallo o cerrar el generador: no queda nada
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _access_steps(project: StoreProject, request: AccessRequest, version: str | None, masks: MaskSet | None, code: str | None,
                  supersedes: str | None, budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.ROAD_ACCESS)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: access_store.PreparedAccess = yield from _prepare_steps(
        access_store.prepare_access_units(project, request, found, loaded, code=code, supersedes=supersedes), budget_s)
    writer = store.DesignWriter(project, provenance.ROAD_ACCESS, request.name, version=found.uid, supersedes=supersedes)
    try:
        outcome: AccessOutcome = yield from access_store.access_compute_steps(prepared.job, budget_s=budget_s)
        yield Progress(_ACCESS_SUMMARY_PHASE, 0, 1, f"Preparando el resumen de «{request.name}»…")
        summary = access_store.prepared_summary(project, prepared, outcome, supersedes=supersedes)
        calculation = Calculation(project=project, writer=writer, start=prepared.start, outcome=outcome, notices=summary.notices, seeds=None, values={},
                                  entity=prepared, summary=summary)
    except BaseException as error:  # un fallo o cerrar el generador: no queda nada
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _road_steps(project: StoreProject, request: RoadRequest, version: str | None, masks: MaskSet | None, code: str | None, supersedes: str | None,
                budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.ROAD)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: road_store.PreparedRoad = yield from _prepare_steps(
        road_store.prepare_road_units(project, request, found, loaded, code=code, supersedes=supersedes), budget_s)
    with project.read() as conn:  # con qué se compara la magnitud (RF-013-30)
        previous = road_store.road_previous(conn, found, prepared.code)
    order = entity_store.quarry_order(project, found, prepared)  # RF-015-14: el orden con la otra superficie de la cantera
    read_other = road_store.other_reader(project, found)  # RF-017-05 (b): la superficie de otro diseño de la versión en la ventana de trabajo de la pista
    writer = store.DesignWriter(project, provenance.ROAD, request.name, version=found.uid, supersedes=supersedes)
    try:
        outcome: RoadOutcome = yield from road_store.road_compute_steps(
            prepared.job, prepared.common, surface=prepared.start_surface, others=prepared.others, read_other=read_other, quarry=order, previous=previous, operation=request.name,
            budget_s=budget_s)
        yield Progress(_ROAD_SUMMARY_PHASE, 0, 1, f"Preparando el resumen de «{request.name}»…")
        summary = road_store.road_summary(project, found, prepared, outcome, loaded, supersedes=supersedes)
        calculation = Calculation(project=project, writer=writer, start=prepared.start, outcome=outcome, notices=summary.notices, seeds=None, values=prepared.common,
                                  entity=prepared, summary=summary)
    except BaseException as error:  # un fallo o cerrar el generador: no queda nada
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _propose_steps(project: StoreProject, request: RoadRequest, version: str | None, masks: MaskSet | None, supersedes: str | None,
                   budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.ROAD_PROPOSE)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: road_store.PreparedProposal = yield from _prepare_steps(
        road_store.prepare_propose_units(project, request, found, loaded, supersedes=supersedes), budget_s)
    writer = store.DesignWriter(project, provenance.ROAD_PROPOSE, request.name, version=found.uid, supersedes=supersedes)
    try:
        outcome: ProposalOutcome = yield from road_store.propose_compute_steps(prepared.job, surface=prepared.start_surface, budget_s=budget_s)
        yield Progress(_PROPOSE_SUMMARY_PHASE, 0, 1, f"Preparando el resumen de «{request.name}»…")
        summary = road_store.propose_summary(outcome, version=found.code, profile=prepared.profile)
        calculation = Calculation(project=project, writer=writer, start=prepared.start, outcome=outcome, notices=summary.notices, seeds=None, values=road_store.propose_values(prepared),
                                  entity=prepared, summary=summary)
    except BaseException as error:  # un fallo o cerrar el generador: no queda nada
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _removal_steps(project: StoreProject, request: RemovalRequest, version: str | None, masks: MaskSet | None,
                   code: str | None, supersedes: str | None, budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.STOCKPILE_REMOVAL)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: supported_store.PreparedRemoval = yield from _prepare_steps(
        supported_store.prepare_removal_units(project, request, found, loaded, code=code, supersedes=supersedes), budget_s)
    writer = store.DesignWriter(project, provenance.STOCKPILE_REMOVAL, request.name, version=found.uid, supersedes=supersedes)
    try:
        outcome: removal.RemovalOutcome = yield from supported_store.compute_removal_steps(writer, prepared, budget_s=budget_s)
        yield Progress(_REMOVAL_SUMMARY_PHASE, 0, 1, f"Preparando el resumen de «{request.name}»…")
        summary = supported_store.removal_summary(project, prepared, outcome, supersedes=supersedes,
                                                  quarry=entity_store.quarry_order(project, found, prepared))
        calculation = Calculation(project=project, writer=writer, start=prepared.start, outcome=outcome, notices=summary.notices,
                                  seeds=None, values=prepared.common, entity=prepared, summary=summary)
    except BaseException as error:  # un fallo o cerrar el generador: no queda el temporal
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _body_steps(project: StoreProject, request: BodyRequest, version: str | None, masks: MaskSet | None,
                code: str | None, supersedes: str | None, budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.BODY)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: supported_store.PreparedBody = yield from _prepare_steps(
        supported_store.prepare_body_units(project, request, found, loaded, code=code, supersedes=supersedes), budget_s)
    writer = store.DesignWriter(project, provenance.BODY, request.name, version=found.uid, supersedes=supersedes)
    try:
        outcome: thickness.BodyOutcome = yield from supported_store.compute_body_steps(writer, prepared, budget_s=budget_s)
        yield Progress(_BODY_SUMMARY_PHASE, 0, 1, f"Preparando el resumen de «{request.name}»…")
        summary = supported_store.body_summary(project, prepared, outcome, supersedes=supersedes,
                                               quarry=entity_store.quarry_order(project, found, prepared))
        calculation = Calculation(project=project, writer=writer, start=prepared.start, outcome=outcome, notices=summary.notices,
                                  seeds=None, values={}, entity=prepared, summary=summary)
    except BaseException as error:  # un fallo o cerrar el generador: no queda el temporal
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _buttress_steps(project: StoreProject, request: ButtressRequest, version: str | None, masks: MaskSet | None,
                    code: str | None, supersedes: str | None, budget_s: float) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.BUTTRESS)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: supported_store.PreparedButtress = yield from _prepare_steps(
        supported_store.prepare_buttress_units(project, request, found, loaded, code=code, supersedes=supersedes), budget_s)
    writer = store.DesignWriter(project, provenance.BUTTRESS, request.name, version=found.uid, supersedes=supersedes)
    try:
        outcome: buttress.ButtressOutcome = yield from supported_store.compute_buttress_steps(writer, prepared, budget_s=budget_s)
        yield Progress(_BUTTRESS_SUMMARY_PHASE, 0, 1, f"Preparando el resumen de «{request.name}»…")
        summary = supported_store.buttress_summary(project, prepared, outcome, loaded, supersedes=supersedes,
                                                   quarry=entity_store.quarry_order(project, found, prepared))
        calculation = Calculation(project=project, writer=writer, start=prepared.start, outcome=outcome, notices=summary.notices,
                                  seeds=None, values=prepared.common, entity=prepared, summary=summary)
    except BaseException as error:  # un fallo o cerrar el generador: no queda el temporal
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)


def _platform_steps(project: StoreProject, request: PlatformRequest, version: str | None,
                    masks: MaskSet | None, code: str | None, supersedes: str | None,
                    insert_before: str | None, confirm_counterslope: bool, budget_s: float
                    ) -> Generator[Progress, None, None]:
    found = store.require_version(project, version, provenance.PLATFORM)
    loaded = yield from store.masks_steps(project, found, masks, budget_s=budget_s)
    prepared: entity_store.PreparedPlatform = yield from _prepare_steps(
        entity_store.prepare_platform_units(project, request, found, loaded, code=code,
                                            supersedes=supersedes, insert_before=insert_before),
        budget_s)
    with project.read() as conn:  # con qué se compara la magnitud y el orden de la cantera
        previous = entity_store.platform_previous(conn, found, prepared.code)
    order = entity_store.quarry_order(project, found, prepared)
    writer = store.DesignWriter(project, provenance.PLATFORM, request.name, version=found.uid,
                                supersedes=supersedes)
    try:
        outcome: platform.PlatformOutcome = yield from entity_store.compute_platform_steps(
            writer, prepared, confirm_counterslope=confirm_counterslope, previous=previous,
            operation=request.name, quarry=order, budget_s=budget_s)
        yield Progress(_SUMMARY_PHASE, 0, 1, f"Preparando el resumen de «{request.name}»…")
        summary = entity_store.platform_summary(project, found, prepared, outcome, loaded,
                                                insert_before=insert_before,
                                                supersedes=supersedes)
        calculation = Calculation(project=project, writer=writer, start=prepared.start,
                                  outcome=outcome, notices=summary.notices, seeds=None,
                                  values=prepared.common, entity=prepared, summary=summary)
    except BaseException as error:  # un fallo o cerrar el generador: no queda el temporal
        writer.close(error)
        raise
    yield Progress(_DONE_PHASE, 1, 1, outcome.message, result=calculation)
