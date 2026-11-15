# SPDX-License-Identifier: GPL-3.0-or-later
"""El diseño de explotación en Blender: envolventes y escalonado (código ``des``, spec 013; plan 013
§5.1, §5.2.4, §5.3.2, §5.3.3, D-14, D-19, D-30; ADR-0025 §2, ADR-0027).

**El registro** (T21; HU-013-1 a HU-013-6; RF-013-33): lo que la 013 declara en ``core``, en
constantes del módulo construidas una vez:

- sus **definiciones de parámetros** del proyecto (``design.params.DEFINITIONS``: la tolerancia
  de cara y el umbral de aviso de magnitud, 1,0 ° y 2,0 «sin confirmar») y sus **familias**
  (``design.params.FAMILIES``, ADR-0027: la altura, la cara, la berma, el ancla y el factor de
  malla de cada perfil de banco y el talud general máximo impuesto de cada sector, por su código
  inmutable y de versión, sin valor por defecto salvo el factor de malla: D-7);
- sus **tipos de operación** (:data:`OPERATION_DEFS`): ``des.envelope`` y ``des.stepped_design``,
  de la versión, repetibles y reproducibles (D-26), cada uno con su función de recálculo de
  :data:`RECOMPUTE` y la de reproducción de :data:`REPRODUCE`, y ``des.edit_bench_profiles``, del
  proyecto y sin repetición (``design.profiles.OPERATIONS``); y sus quince **cifras**
  (``design.provenance.FIGURES``);
- lo de la **014** (T05; plan 014 §5.2.2 y §5.2.3): sus siete parámetros
  (``design.params.QUARRY_DEFINITIONS``), sus cinco tipos de operación de la versión, repetibles
  (:data:`QUARRY_RECOMPUTE`) y reproducibles salvo el ajuste (:data:`QUARRY_REPRODUCE`), y sus
  cifras (``design.provenance.QUARRY_FIGURES``);
- lo de la **015** (T04; plan 015 §5.2.2 y §5.2.3): las 20 familias de parámetros de una plataforma
  (``design.params.ENTITY_FAMILIES``, ``des.platform.{e}.*``, junto a las de la 013), sus tres tipos de
  operación de la versión, repetibles y reproducibles (``des.platform``, ``des.declare_constraints`` y
  ``des.entity_layer``: :data:`ENTITY_RECOMPUTE`, :data:`ENTITY_REPRODUCE`) y sus cifras
  (``design.provenance.ENTITY_FIGURES``); sin las órdenes (T15 y siguientes);
- sus textos (``design.messages``) en ``core.i18n``.

:func:`register` pone lo que falta y apunta cómo quitarlo; :func:`unregister` quita solo eso, en
orden inverso: lo que otro registró antes con la misma clave, o puso después en su lugar, es suyo y
se queda (también una definición o una familia de ``des``). Los dos son simétricos e idempotentes:
registrar y desregistrar deja los registros de ``core`` como estaban (ADR-0025 §2). Nada pesado: lo
que registra son declaraciones ligeras (``design.params``, ``design.provenance``,
``design.profiles``, ``design.messages``) y el cálculo, el almacén y la reproducción
(``design.store``, ``design.reproduce``, ``design.steps`` y todo lo que arrastran: las máscaras, la
cadena de versiones…) se importan **al usarlos**, dentro de cada función: habilitar Geoblender
tarda ≤ 0,5 s (RNF-001-03).

**Recalcular lo obsoleto** (D-19, plan §5.3.2; RF-013-17, RF-008-26): las funciones de
:data:`RECOMPUTE` (:func:`recompute_envelope` y :func:`recompute_design`) empiezan con
``design.store.recompute_run`` la operación que sustituye a la obsoleta (en la revisión abierta de
**su** versión, con lo que lee hoy), **sin pedir confirmación** (la operación ya existe y se repite
con sus ajustes), dejan sus pasos en la cola de ``des`` (:data:`RUNS`, :func:`queue_steps`) y la
devuelven «en curso»: ``recompute_steps`` de la 008 espera («Esperando a «des.envelope»…») mientras
el temporizador de la cola (:func:`des_tick`, persistente) da un paso de la primera por llamada, de
``design.store.STEP_BUDGET_S`` como mucho, con su avance en la barra de estado («Recalculando
«Ampliación»… 40 %»). Unos pasos que fallan dejan su operación «fallida» con el motivo (si sus pasos
no lo hicieron ya) y sigue la siguiente. Desregistrar cierra lo que espera, como Esc: lo empezado
lo cancelan sus pasos sin dejar nada a medias (RF-013-33) y lo que no empezó queda «cancelado» (no
«en curso»). En ``blender -b`` no corren los temporizadores: las pruebas llaman a :func:`des_tick`
a mano.

**Reproducir** (RF-009-11): las funciones de :data:`REPRODUCE` son las de ``design.reproduce``,
importadas al usarlas (como ``core.versions.reproduce`` en ``bl.ops.versions``).

**El cálculo abierto** (D-14, RF-013-31; plan §5.3.2): «Calcular» deja un cálculo hecho y **sin
registrar** (``design.steps.Calculation``), con sus rejillas en temporales junto a su destino, hasta
que la persona lo crea o lo cancela. Es de la sesión: :func:`hold_calculation` lo guarda en memoria
(el anterior se descarta), :func:`calculation` lo da mientras siga abierto y
:func:`discard_calculation` lo descarta. Cambiar de proyecto (cerrarlo o abrir otro:
:func:`project_changed`) y desactivar Geoblender lo descartan: no quedan ``*.tif.tmp-*``. Un cálculo
cuyo resultado llega con el proyecto ya cerrado (en el último paso: spec 014, T48) no queda abierto:
el modal lo descarta (:func:`_discard_late`) y se para diciéndolo. La confirmación de la orden no
recalcula: llama a ``create()`` de éste.

**La disponibilidad** (RF-013-33): :func:`design_unavailable` dice por qué no se puede lanzar ahora
una orden de Diseño que escribe, en el idioma de Geoblender: sin proyecto, sin la procedencia o en
solo lectura («Proyecto en solo lectura: …»), o con la versión activa SUPERADO o DESCARTADO («V02
está en estado SUPERADO: cree una versión nueva a partir de ella»); ``None`` si se puede, también
sin versión activa (la orden que calcula la pide al lanzarla, RF-009-05). :class:`DesignCommand` es
el ``poll`` común de las cuatro órdenes de «Diseño» de R-33 (Perfiles de banco…, Sectores de
diseño…, Vista previa de semillas, dominios y restricciones y Envolventes y escalonado…) y
:class:`DesignCommandAware`, el de las que son además de :class:`ProvenanceAwareOperator`, con su
descripción con el porqué si la versión activa no es editable (RF-009-21).

**Perfiles de banco…** (T22; RF-013-18, RF-013-19, RF-013-20):
:class:`GEOBLENDER_OT_des_edit_bench_profiles` abre la ventana de ``bl.ui.des_panels`` (lo
leído del proyecto) y la interna :class:`GEOBLENDER_OT_des_save_bench_profile` crea, completa y renombra perfiles con
``design.profiles.edit_bench_profiles`` (una operación de proyecto, en una transacción, con el
ámbito de la 009 «¿Para el proyecto o solo para V01?»); cambiar un valor que ya existe es
``core_set_parameter`` (la 008 y la 009). Ninguna cuenta ni regla de rango es de aquí: las del
dominio (``design.model.BenchProfile``, ``design.params``).

**Sectores de diseño…** (T23; RF-013-07, RF-013-08, RF-013-09, RF-013-10, RF-013-21):
:class:`GEOBLENDER_OT_des_edit_design_sectors` abre la ventana de ``bl.ui.des_panels`` con los
sectores de la 012 (o el perímetro como único sector), el estado de su búsqueda, el talud que
impone cada uno y el perfil asignado, y la interna :class:`GEOBLENDER_OT_des_set_sector_slope`
guarda ese talud como el parámetro de su código (``des.sector.{código}.max_general_slope_deg``,
ADR-0029) con su tipo, su origen, su decisor y su motivo, en el proyecto o solo en la versión
activa (la 009): lo crea la primera vez en el ámbito y lo cambia después (su historial). «Declarar
de nuevo desde una capa…» es la orden de la 012 (``core_declare_sectors``): conserva los valores de
los sectores que mantienen su código y los demás quedan en la lista de huérfanos, sin borrarlos.
Ninguna regla de rango ni cuenta es de aquí: las del dominio (``design.params``,
``design.sectors``).

**Envolventes y escalonado…** (T24; HU-013-1, HU-013-3, HU-013-5, HU-013-6; RF-013-05, RF-013-16,
RF-013-17, RF-013-21, RF-013-31; D-14, D-27, D-30):
:class:`GEOBLENDER_OT_des_compute_envelope` es **una sola orden** con la envolvente y su escalonado
opcional, con el diálogo de la spec (semillas, dirección, métrica, pendiente, alcance, acotar a,
escalonar con su sentido, su superficie de partida, su perfil base, el de cada sector y su ancla, y
el nombre). **Calcular** (el aceptar del diálogo) corre ``design.steps.envelope_run`` en su modal por
pasos (``_StepsModal``: avance «Calculando la envolvente… 40 % · Esc: cancelar» y cancelación con
Esc) y deja el cálculo hecho y **sin registrar** (:func:`hold_calculation`), con su resumen y sus
avisos en la vista (``bl.ui.des_panels.show_summary``); al terminar pide confirmar
(:func:`_ask_confirmation`: la misma orden con ``confirm=True``, que abre el diálogo de **Crear**,
«Crear con N avisos» si los hay). **Crear** llama a ``Calculation.create()`` (una transacción) y
**Cancelar**, cerrar la ventana (``cancel``), un cálculo nuevo, cambiar de proyecto y desactivar
Geoblender descartan el cálculo y borran los temporales. Con «Escalonar», tras crear la envolvente
(``design.steps.design_run`` la lee de la versión) sigue el escalonado en el mismo modal, con su
propio resumen y su propia confirmación; si se rechaza, la envolvente ya está creada y lo dice. El
rechazo de un sector con la búsqueda pendiente es el de ``design`` (``des.sector_pending``,
nombrando el sector y la orden de la 012). Desde un guion (``bpy.ops`` sin ``in_steps``), de una
vez; el perfil de cada sector y los sectores a los que se acota se marcan en
``WindowManager.geoblender_design`` (``sectors[].profile_pick`` y ``.use``). Ninguna cuenta ni regla
es de aquí: el cálculo, los rangos y los avisos son los de ``design``.

**Vista previa de semillas, dominios y restricciones** (T25; HU-013-1; RF-013-01, RF-013-02,
RF-013-03, RF-013-33): :class:`GEOBLENDER_OT_des_toggle_preview` activa o quita la vista previa de la
Vista 3D (``bl.draw.design``) con lo que pide su diálogo —las semillas (de una superficie en una zona,
una cota fija en una zona o una rejilla de cotas) y el acotado del dominio—, sin crear objetos ni
escribir en el proyecto; con ella activa, el control la quita aunque el proyecto esté ya en solo
lectura. Las semillas y el acotado se piden con las mismas funciones que el diálogo de las envolventes
(:func:`seed_source`, :func:`work_domain`). Nada se cuenta ni se resume aquí: lo hace ``design.preview``.

**Exportar una rejilla del diseño** (T28; HU-013-6; RF-013-34; D-29 de la 011):
:class:`GEOBLENDER_OT_des_export_design_grid` (interna; el botón «Exportar rejilla a GeoTIFF…» está
en la barra N «Diseño», con el objeto de la rejilla activo) escribe la envolvente, la superficie de
diseño o la rejilla de cotas de berma registradas como GeoTIFF entregable con
``design.export.export_grid_steps``, por pasos con el avance y Esc (desde un guion, de una vez). No
es una operación: no escribe nada en el proyecto y vale en solo lectura (fuera de él) y desde una
versión que ya no es editable; sobre un fichero que ya existe pregunta antes de sustituirlo
(:func:`_confirm_later`). Qué rejilla es, de qué versión y qué nombre lleva su operación lo dice
``design.export.stored_grid``. **Recalcular lo obsoleto** ya estaba integrado (T21, véase arriba): la
T28 lo prueba de punta a punta sobre un proyecto real. Desde la 014 (T33; RF-014-32) exporta también
las rejillas de la cantera, la transición, la superficie ajustada y el recinto; la clasificación y
el recinto, con un código por celda y su leyenda en los metadatos (``design.export.LEGENDS``).

**Los cargadores de la vista** (T27): el de las rejillas ``des_env_``, ``des_srf_`` y ``des_brm_``
(objetos ``DESIGN``) es de ``bl/scene/des_views.py``, que registra ``bl.scene`` junto al tipo de
objeto que necesita; también el del recinto ``des_rcn_`` de la 014 (T20).

**Límite desde el perímetro…** (spec 014, T20; HU-014-1; RF-014-01; plan 014 §5.3.3):
:class:`GEOBLENDER_OT_des_create_limit_from_perimeter` calcula el **recinto excavable** de la
versión activa (``des.excavation_area``: el corte admitido de sus máscaras con dato en la superficie
de partida) con ``design.steps.excavation_area_run``. Su diálogo pide el nombre y la superficie de
partida (propone «Recinto excavable» y el terreno, como la T45 de la 013); **Calcular**, **Crear**,
**Cancelar** y Esc, como «Envolventes y escalonado…» (el cálculo abierto de la sesión, su resumen
en ``bl.ui.des_panels`` y su confirmación, :func:`_ask_confirmation` con su ``idname``). Ninguna
cuenta es de aquí: el recinto, su área y su rechazo cuando queda vacío (con el área de cada parte
que lo vacía) son de ``design``.

**Cantera con dos superficies…** (spec 014, T21; HU-014-3; RF-014-12, RF-014-13, RF-014-29,
RF-014-30; plan 014 §5.3.3, §5.5): :class:`GEOBLENDER_OT_des_design_quarry` calcula en una sola
orden la superficie final y la de explotación de la versión activa (``des.quarry``) con
``design.steps.quarry_run``. Su diálogo tiene arriba el nombre, la superficie de partida (propone el
terreno, T45 de la 013) y el orden del diseño; una caja por superficie con sus semillas
(«coronación y zonas a sostener» o las de la 013), su perfil base y el de cada sector (por su
nombre: ``final_pick`` y ``exploitation_pick`` de cada sector de la vista), su ancla (la del perfil,
una rejilla o «al fondo de cada muro») y su métrica; y abajo las capas de plan 014 §5.2.1 con sus
campos (fondos, zona a conservar, corredores con cota fija o rasante, zonas de restauración por
relleno, láminas de agua) y «explotación hasta la final» (no, las zonas avisadas o las de una
capa). Lo pedido es una ``design.model.QuarryRequest`` (su ``_request``). Calcular, Crear,
Cancelar y Esc son los de «Límite desde el perímetro…» (:class:`_CalculateAndCreate`, común a las
dos): nada se registra hasta Crear (RF-014-29) y la confirmación dice «Crear con N avisos» si los
hay. Los rechazos (un sector del recinto sin búsqueda vigente, RF-014-30; las capas
y sus campos, los perfiles, el recinto vacío, el nombre repetido) y todas las cuentas son de
``design``. El botón **«Vista previa»** del diálogo (T44; RF-014-04) es la misma orden con la oculta
``preview`` y todo lo pedido: comprueba lo pedido sin calcular ni escribir nada y activa la vista
previa de la 013 con ese diseño (``bl.draw.design.QuarryPlan``), que se quita como siempre.

**Transiciones con el terreno no afectado…** (spec 014, T28; HU-014-5; RF-014-19 a RF-014-21,
RF-014-29; plan 014 §5.3.3, §5.5): :class:`GEOBLENDER_OT_des_create_transitions` (Restauración ▸
Superficie final) calcula ``des.edge_transition`` de la versión activa con
``design.steps.edge_transition_run``: la transición de una superficie de diseño con el terreno no
afectado del borde de lo que mueve y el salto creado que deja. Su diálogo pide el nombre, la
superficie de diseño (``des_panels.design_surface_items``: las de la versión) y la de partida;
propone «Transición», **la superficie de diseño seleccionada** en la vista (sin ella, la primera de
la lista) y, de partida, la de su ficha (``design.store.design_surface_of``) o el terreno. Calcular,
Crear, Cancelar y Esc, los de :class:`_CalculateAndCreate`.

**Solo relleno…** (spec 014, T30; HU-014-6; RF-014-22 a RF-014-25, RF-014-29; plan 014 §5.3.3):
:class:`GEOBLENDER_OT_des_design_fill_only` (Diseño ▸ Cantera) calcula ``des.fill_only`` de la
versión activa con ``design.steps.fill_only_run``: el escalonado en relleno de la 013 de una
envolvente de la versión, que nunca corta, con el pie dentro del relleno admitido de la 012 y las
láminas de agua de una capa como terreno de partida. Su diálogo es el del escalonado en relleno de
la 013 (el nombre, la envolvente —``des_panels.envelope_items``: las de la versión—, la superficie
de partida, el ancla, el perfil base y el de cada sector) más la capa de láminas y su campo;
propone «Solo relleno», la primera envolvente, el terreno y el campo «cota». Lo pedido es una
``design.model.FillOnlyRequest``. Calcular, Crear, Cancelar y Esc, los de
:class:`_CalculateAndCreate`; los rechazos (un intocable movido o un corte, RF-014-25; las
láminas; un perfil sin valor) y las cuentas son de ``design``.

**Ajustar el diseño a un límite nuevo…** (spec 014, T33; HU-014-7; RF-014-27 a RF-014-29; plan 014
§5.3.3, P-3): :class:`GEOBLENDER_OT_des_refit_to_limit` (Diseño ▸ Cantera) calcula ``des.refit`` de
la versión activa con ``design.steps.refit_run``: cada superficie elegida, ajustada al límite
vigente con la cara de su propio perfil (el ángulo no se pide). Su diálogo pide el nombre, la
superficie de partida y las superficies que se ajustan: las de diseño de la versión
(``des_panels.refit_rows``, una fila por superficie en ``surfaces``, con lo que deja fuera del límite
vigente), con **las que quedan fuera marcadas**; propone «Ajuste» y, de partida, la de la ficha de
la primera marcada o el terreno. Lo pedido es una ``design.model.RefitRequest``. Calcular, Crear,
Cancelar y Esc, los de :class:`_CalculateAndCreate`; los rechazos y las cuentas, de ``design``.
Las marcas salen de la caché de la comprobación (spec 014, T35; RNF-014-02:
``des_panels.cached_refit_rows``); sin acierto, la orden comprueba antes **por pasos** en su modal
(``des_panels.refit_rows_steps``, con el texto en la barra de estado y Esc, que no abre nada; cerrar
el proyecto mientras tanto tampoco, ni en el último paso: T54) y después vuelve a abrirse con las
filas ya marcadas.

**Plataforma…** (spec 015, T15; HU-015-3; RF-015-03, RF-015-28, RF-015-29; plan 015 §5.3.3):
:class:`GEOBLENDER_OT_des_create_platform` (``geoblender.des_create_platform``, Diseño ▸ Pistas y
entidades ▸ Entidades; la entrada de R-36 la entrega la T31) calcula ``des.platform`` de la versión activa con
``design.steps.platform_run``: la huella y la rasante de una geometría de una capa de líneas (con su ancho) o de
polígonos (con su eje enlazado o el principal), aplicadas a su superficie de partida, con el borde que la
une con el terreno. Su diálogo pide el nombre; la capa y la geometría (por su nombre o su ``fid``) con sus
campos; **la cota inicial, la pendiente y el ancho que da la capa, que propone y deja corregir**
(:func:`_propose_values`: el ``update`` de la capa y la geometría; ``PlatformRequest.start_level_m``,
``gradient_pct`` y ``width_m``, que se copian a los parámetros de la entidad al crear con su origen:
``design.entity_store.create_platform`` los escribe en la transacción de «Crear», no el cálculo); **la
partida, que propone la última de la cadena** (o el terreno si no hay plataformas), y el apoyo; el modo,
el ángulo, el alcance, el factor de malla y la métrica del borde; la tolerancia de contrapendiente y si
protege, con su resguardo. Calcular, Crear, Cancelar y Esc, los de :class:`_CalculateAndCreate`: nada se
registra hasta Crear (RF-015-03) y cerrarlo a mitad no deja nada (RF-015-29). Con una **contrapendiente**
que pasa de su tolerancia el botón de crear dice «Confirmar la contrapendiente y crear»: pulsarlo es la
confirmación expresa (RF-015-23); desde un guion, ``confirm_counterslope``. Disponible con el proyecto en
escritura y la versión activa editable y, si no, desactivada con su motivo (RF-015-28:
:class:`DesignCommandAware`). Las cuentas y los rechazos son de ``design``.

**Lo que sigue a crear una entidad** (spec 015, T19; RF-015-10, RF-012-06; plan 015 §5.3.2 y P-7): tras el
commit de «Crear», la orden encadena ``design.entity_store.after_entity_change`` por pasos, con el avance y
Esc (como el escalonado tras la envolvente): repite la declaración de las restricciones de las entidades
de la versión y, si las máscaras ya no están al día, las compila de nuevo, y dice qué quedó obsoleto con el
área (m²) ganada y perdida por restricción; cada etapa, su operación y su transacción. La plataforma ya
está creada: si una etapa falla o se cierra con Esc, las máscaras quedan obsoletas con su causa
(``gis.masks.access.MaskCause``) y se compilan de nuevo antes de que un operador las use. «Recalcular lo
obsoleto» no encadena nada: la declaración y las máscaras son operaciones de la 008 que ella recalcula por el
grafo (el recálculo de una plataforma no declara por su cuenta). Descartar (T25) y retirar (T26) encadenan
la misma función.

**Descartar una entidad y soltar el apoyo** (spec 015, T25; HU-015-2; RF-015-17, RF-009-12, RF-015-28, RF-015-29; D-12;
plan 015 §5.3.3 y §5.4 A7, P-6): :class:`GEOBLENDER_OT_des_entity_discard` (``geoblender.des_entity_discard``) **enseña
antes una sola lista** —lo que se apoya en la entidad y lo que parte de ella, con su tipo y sus m³:
``design.entity_store.discard_plan``— y pide confirmar con el motivo; al aceptar descarta la entidad **sin borrar
nada** (``discard_entity``: sus datos pasan a ``DISCARDED``, con un evento y el motivo) y encadena
``after_entity_change`` por pasos con el avance y Esc (su restricción sale de las máscaras). Lo que se le apoyaba queda
en «apoyo retirado» y «Recalcular lo obsoleto» no lo recalcula.
:class:`GEOBLENDER_OT_des_entity_release_support` (``geoblender.des_entity_release_support``) **da por bueno** lo que
perdió su apoyo —una entidad o un diseño de la 013 o la 014— repitiéndolo sin ese apoyo, con el motivo y el decisor
en sus ajustes y un evento (``release_support``, por pasos con el avance y Esc); su salida no cambia y lo que dependía
de ella no se recalcula. Las dos van con el proyecto en escritura y la versión activa editable y, si no, desactivadas
con su motivo (:class:`DesignCommandAware`); la entrada de R-36 las entrega la T31 (menú «Entidad ▾»). Todas las
cuentas y los rechazos son de ``design``.
"""

from __future__ import annotations

import functools
import json
import logging
import math
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty

from ...core import i18n
from ...core import params as core_params
from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.params import ParamKind
from ...core.project.model import Progress
from ...core.provenance import contract
from ...core.provenance.undo import UndoKind
from ...design import messages as design_messages
from ...design import params as design_params
from ...design import profiles as design_profiles
from ...design import model as design_model
from ...design import provenance
from ...design.model import PERIMETER_SEGMENT
from ...gis import provenance as gis_provenance
from ...gis.messages import GisError
from ..props.core import OBJECT_PROPERTY
from ..props.des import PREVIEW_PROPERTY, GEOBLENDER_PG_des_refit_surface
from ..scene import des_views, project_session, undo_watch
from ..scene import versions as scene_versions
from ..ui import constraint_panels, des_panels, labels
from ..ui import provenance as ui_provenance
from ..ui.commands import catalog, command_idname, with_note
from ..ui.commands import text as command_text
from . import incorporation, surface_proposal
from .core import _StepsModal
from .core_provenance import (
    KIND_ITEMS,
    PARAMETER_SCOPE_ITEMS,
    SESSION,
    SOURCE_KIND_ITEMS,
    ProvenanceAwareOperator,
    ensure_ready,
    error_text,
    read_only_dirs,
    scope_choice,
    typed_value,
    write_unavailable,
)
from .incorporation import StepQueue

if TYPE_CHECKING:  # solo para los tipos: habilitar no importa el cálculo (RNF-001-03)
    from ...core.project.session import Project
    from ...core.provenance.operations import OperationHandle
    from ...core.provenance.recompute import RecomputeRequest
    from ...core.versions.reproduce import ReproduceRequest
    from ...design.sectors import DesignSector
    from ...design.steps import Calculation

LOGGER = logging.getLogger("geoblender.bl.ops")
MODULE = provenance.MODULE
"""El módulo de las definiciones, las familias, los tipos y las cifras del diseño (``des``)."""

RECOMPUTING = incorporation.RECOMPUTING
"""Lo que dice la barra de estado de unos pasos de la cola (``msgid`` con ``name`` y
``percent``)."""
DROPPED_REASON = incorporation.DROPPED_REASON
"""El motivo de una operación cuyos pasos esperaban en la cola sin haber empezado al
desactivar Geoblender."""

_UNDO: list[Callable[[], None]] = []


# --- La cola de los pasos del recálculo (D-19) ---------------------------------------------------

RUNS = StepQueue()
"""Los pasos de las operaciones de ``des`` que recalcula «Recalcular lo obsoleto», por orden de
llegada (la cola es suya, aparte de las de la topografía, los sondeos, la cubicación y las
máscaras)."""
des_tick: Callable[[], float | None] = RUNS.timer
"""El temporizador de la cola de ``des``: un paso de la primera por llamada (el mismo objeto
siempre: Blender reconoce un temporizador por su función)."""


def pending_runs() -> list[str]:
    """Las operaciones cuyos pasos esperan en la cola, en orden."""
    return RUNS.pending()


def _shown_name(handle: Any) -> str:
    """El nombre de la envolvente o del escalonado de ``handle`` (sus ajustes) o, sin él, su
    tipo."""
    name = (getattr(handle, "settings", None) or {}).get("name")
    return name.strip() if isinstance(name, str) and name.strip() else str(handle.op_type)


def queue_steps(handle: OperationHandle, steps: Iterator[Progress]) -> None:
    """Pone en la cola de ``des`` los pasos ``steps`` (``Progress``) de la operación ``handle``,
    «en curso», y registra su temporizador si no lo estaba."""
    name = _shown_name(handle)
    RUNS.add(handle.uid, name, incorporation.RecomputeSteps(handle, name, steps),
             status=RECOMPUTING)


def _recompute(request: RecomputeRequest) -> OperationHandle:
    """La operación nueva de ``request`` (``design.store.recompute_run``), «en curso», con sus
    pasos en la cola de ``des``."""
    from ...design import store  # al usarlo: habilitar no carga el cálculo

    handle, steps = store.recompute_run(request)
    queue_steps(handle, steps)
    return handle


def recompute_envelope(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.envelope`` (RF-008-26; RF-013-17; D-19): véase el módulo."""
    return _recompute(request)


def recompute_design(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.stepped_design`` (RF-008-26; RF-013-17; D-19): véase el módulo."""
    return _recompute(request)


def reproduce_envelope(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.envelope``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_envelope(request)


def reproduce_design(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.stepped_design``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_design(request)


# Los cinco tipos de la 014 (T05; plan 014 §5.2.3): el mismo camino que los de la 013. Su recálculo
# lo hace ``design.store.recompute_run`` y su reproducción, ``design.reproduce`` (las tareas que
# crean cada operación, T06, T19, T28, T30 y T32, les dan su cálculo: hasta entonces no hay
# ninguna operación de esos tipos que recalcular ni reproducir).


def recompute_excavation_area(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.excavation_area`` (RF-014-29; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_quarry(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.quarry`` (RF-014-29; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_edge_transition(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.edge_transition`` (RF-014-29; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_fill_only(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.fill_only`` (RF-014-29; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_refit(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.refit`` (RF-014-29; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def reproduce_excavation_area(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.excavation_area``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_excavation_area(request)


def reproduce_quarry(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.quarry``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_quarry(request)


def reproduce_edge_transition(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.edge_transition``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_edge_transition(request)


def reproduce_fill_only(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.fill_only``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_fill_only(request)


# Los tres tipos de la 015 (T04; plan 015 §5.2.3): el mismo camino que los de la 013 y la 014. Su
# recálculo lo hace ``design.store.recompute_run`` y su reproducción, ``design.reproduce``. La plataforma
# ya tiene las dos (T13 y T14: ``design.entity_store.recompute_platform``, que ``recompute_run`` llama, y
# ``design.reproduce.reproduce_platform``) y la declaración de restricciones también (T17:
# ``design.entity_store.recompute_declaration``, que ``recompute_run`` llama, y
# ``design.reproduce.reproduce_declare_constraints``); la capa de entidades (T30) aún no: no hay ninguna
# operación de ese tipo que recalcular ni reproducir, y ``recompute_run`` la rechaza y ``design.reproduce``
# dice la tarea que falta (``NotImplementedError``).


def recompute_platform(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.platform`` (RF-015-02, RF-015-16; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_declare_constraints(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.declare_constraints`` (RF-015-10; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_entity_layer(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.entity_layer`` (RF-015-27; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def reproduce_platform(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.platform``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_platform(request)


def reproduce_declare_constraints(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.declare_constraints``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_declare_constraints(request)


def reproduce_entity_layer(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.entity_layer``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_entity_layer(request)


# --- Declaraciones de la procedencia (ADR-0025 §2; plan §5.2.3) ----------------------------------

RECOMPUTE: Mapping[str, Callable[[RecomputeRequest], OperationHandle]] = MappingProxyType({
    provenance.ENVELOPE: recompute_envelope,
    provenance.STEPPED: recompute_design,
})
"""La función de recálculo de cada tipo de ``des`` que se repite solo (RF-008-26)."""
REPRODUCE: Mapping[str, Callable[[ReproduceRequest], Iterator[Progress]]] = MappingProxyType({
    provenance.ENVELOPE: reproduce_envelope,
    provenance.STEPPED: reproduce_design,
})
"""La función de reproducción de cada tipo de la 013 que se repite solo (RF-009-11)."""
QUARRY_RECOMPUTE: Mapping[str, Callable[[RecomputeRequest], OperationHandle]] = (
    MappingProxyType({
        provenance.EXCAVATION_AREA: recompute_excavation_area,
        provenance.QUARRY: recompute_quarry,
        provenance.EDGE_TRANSITION: recompute_edge_transition,
        provenance.FILL_ONLY: recompute_fill_only,
        provenance.REFIT: recompute_refit,
    }))
"""La función de recálculo de cada tipo de la 014 (todos se repiten solos; RF-014-29)."""
QUARRY_REPRODUCE: Mapping[str, Callable[[ReproduceRequest], Iterator[Progress]]] = (
    MappingProxyType({
        provenance.EXCAVATION_AREA: reproduce_excavation_area,
        provenance.QUARRY: reproduce_quarry,
        provenance.EDGE_TRANSITION: reproduce_edge_transition,
        provenance.FILL_ONLY: reproduce_fill_only,
    }))
"""La función de reproducción de cada tipo de la 014 que se reproduce (todos salvo el ajuste)."""
ENTITY_RECOMPUTE: Mapping[str, Callable[[RecomputeRequest], OperationHandle]] = (
    MappingProxyType({
        provenance.PLATFORM: recompute_platform,
        provenance.DECLARE_CONSTRAINTS: recompute_declare_constraints,
        provenance.ENTITY_LAYER: recompute_entity_layer,
    }))
"""La función de recálculo de cada tipo de la 015 (todos se repiten solos; RF-015-02)."""
ENTITY_REPRODUCE: Mapping[str, Callable[[ReproduceRequest], Iterator[Progress]]] = (
    MappingProxyType({
        provenance.PLATFORM: reproduce_platform,
        provenance.DECLARE_CONSTRAINTS: reproduce_declare_constraints,
        provenance.ENTITY_LAYER: reproduce_entity_layer,
    }))
"""La función de reproducción de cada tipo de la 015 (todos se reproducen; RF-015-02)."""
OPERATION_DEFS: tuple[contract.OperationDef, ...] = (
    *provenance.operation_defs(RECOMPUTE, REPRODUCE), *design_profiles.OPERATIONS,
    *provenance.quarry_operation_defs(QUARRY_RECOMPUTE, QUARRY_REPRODUCE),
    *provenance.entity_operation_defs(ENTITY_RECOMPUTE, ENTITY_REPRODUCE))
"""Los ``OperationDef`` de los once tipos de ``des``: de la 013, la envolvente y el escalonado, de
la versión y repetibles, y la edición de los perfiles de banco, del proyecto; de la 014, el recinto,
la cantera con dos superficies, la transición, «solo relleno» y el ajuste, de la versión y
repetibles (T05); de la 015, la plataforma, la declaración de restricciones y la capa de entidades,
de la versión, repetibles y reproducibles (T04)."""
DEFINITIONS: tuple[core_params.ParamDef, ...] = (
    *design_params.DEFINITIONS, *design_params.QUARRY_DEFINITIONS)
"""Las definiciones de parámetros de ``des``: las dos del proyecto de la 013 y las siete de la 014
(plan 014 §5.2.2)."""
FAMILIES: tuple[core_params.ParamFamily, ...] = (*design_params.FAMILIES,
                                                *design_params.ENTITY_FAMILIES)
"""Las familias de parámetros de ``des`` (ADR-0027): las seis de la 013 y las 20 de una plataforma
(``des.platform.{e}.*``, T04)."""
FIGURES: tuple[contract.FigureDef, ...] = (*provenance.FIGURES, *provenance.QUARRY_FIGURES,
                                           *provenance.ENTITY_FIGURES)
"""Las cifras de ``des``: las de la envolvente y las del escalonado (013), las de la 014 y las de las
entidades (015)."""


# --- Registro ------------------------------------------------------------------------------------


def register() -> None:
    """Instala los textos del diseño en ``core.i18n`` y registra sus definiciones de parámetros
    (:data:`DEFINITIONS`), sus familias, sus tipos de operación (:data:`OPERATION_DEFS`) y sus
    cifras (:data:`FIGURES`) que aún no están, y se apunta a los cambios de proyecto de la sesión
    (:func:`project_changed`); idempotente."""
    i18n.install(design_messages.CATALOG_ES)
    missing = tuple(defn for defn in DEFINITIONS if defn.key not in core_params.DEFINITIONS)
    if missing:
        core_params.register_definitions(missing)
        _UNDO.append(functools.partial(_unregister_definitions, missing))
    families = tuple(family for family in FAMILIES
                     if family.pattern not in core_params.FAMILIES)
    if families:
        core_params.register_families(families)
        _UNDO.append(functools.partial(_unregister_families, families))
    for definition in OPERATION_DEFS:
        if definition.op_type not in contract.OPERATIONS:
            contract.register_operation(definition)
            _UNDO.append(_unregister_if(contract.OPERATIONS, definition.op_type, definition,
                                        contract.unregister_operation))
    for figure in FIGURES:
        if figure.key not in contract.FIGURES:
            contract.register_figure(figure)
            _UNDO.append(_unregister_if(contract.FIGURES, figure.key, figure,
                                        contract.unregister_figure))
    if project_changed not in project_session.listeners():
        project_session.add_listener(project_changed)
        _UNDO.append(functools.partial(project_session.remove_listener, project_changed))


def unregister() -> None:
    """Cierra los pasos que esperan en la cola (como Esc; véase el módulo), descarta el cálculo
    abierto y quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es
    suyo); las traducciones instaladas se quedan; idempotente."""
    RUNS.drop()
    discard_calculation()
    while _UNDO:
        _UNDO.pop()()


def _unregister_if(view: Mapping[str, Any], key: str, item: object,
                   remove: Callable[[str], object]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo


def _unregister_definitions(ours: tuple[core_params.ParamDef, ...]) -> None:
    """Quita las definiciones que puso :func:`register` (``ours``) y deja las demás de ``des``:
    las que otro registró antes con su clave o puso después en su lugar son suyas.
    ``core.params`` solo las quita por módulo: se quitan todas y se vuelven a poner las de otro,
    los mismos objetos."""
    mine = {id(defn) for defn in ours}
    others = [defn for defn in core_params.DEFINITIONS.values()
              if defn.module == MODULE and id(defn) not in mine]
    core_params.unregister_definitions(MODULE)
    if others:
        core_params.register_definitions(others)


def _unregister_families(ours: tuple[core_params.ParamFamily, ...]) -> None:
    """Como :func:`_unregister_definitions`, con las familias (ADR-0027)."""
    mine = {id(family) for family in ours}
    others = [family for family in core_params.FAMILIES.values()
              if family.module == MODULE and id(family) not in mine]
    core_params.unregister_families(MODULE)
    if others:
        core_params.register_families(others)


# --- El cálculo abierto (D-14, RF-013-31) --------------------------------------------------------

_HELD: list[Calculation] = []  # a lo más uno: el cálculo hecho y sin registrar de la sesión


@dataclass(frozen=True)
class _Next:
    """Lo que sigue a la envolvente en la misma orden (D-30): su escalonado, ya pedido, que se
    calcula en cuanto la persona crea la envolvente (lee la envolvente de la versión)."""

    request: design_model.DesignRequest
    surface: str
    version: str


_NEXT: list[_Next] = []  # a lo más uno: el escalonado que espera a que se cree la envolvente


def hold_calculation(opened: Calculation) -> None:
    """Deja ``opened`` (un ``design.steps.Calculation`` hecho y sin registrar) como el cálculo
    abierto de la sesión: el anterior, si lo había y sigue abierto, se descarta (sus temporales
    se borran)."""
    previous = _HELD[:]
    _HELD[:] = [opened]
    for other in previous:
        if other is not opened:
            _discard(other)


def calculation() -> Calculation | None:
    """El cálculo abierto de la sesión, o ``None`` si no hay: uno que ya se creó o se descartó
    (``Calculation.open`` falso) se olvida."""
    if _HELD and not _HELD[0].open:
        _HELD.clear()
    return _HELD[0] if _HELD else None


def discard_calculation() -> None:
    """Descarta el cálculo abierto de la sesión («Cancelar», cerrar la ventana, cambiar de
    proyecto, desactivar Geoblender): borra sus temporales y no deja nada, y con él el escalonado
    que esperaba a la envolvente. Sin él, nada."""
    held = _HELD[:]
    _HELD.clear()
    _NEXT.clear()
    for other in held:
        _discard(other)


def _discard(held: Calculation) -> None:
    try:
        held.discard()
    except Exception:  # noqa: BLE001 - lo que queda son temporales; no impide seguir
        LOGGER.exception("No se pudieron borrar los temporales de un cálculo del diseño")


def _discard_late(result: object) -> None:
    """Lo que trae un paso de un cálculo cuando el proyecto ya se ha cerrado (spec 014, T48;
    RNF-014-05): un cálculo hecho (``design.steps.Calculation``, el del último paso) se descarta
    y sus temporales se borran, en lugar de quedar abierto de un proyecto cerrado; otra cosa (nada,
    o los avisos de la cantera que esperaban su confirmación) no deja nada."""
    from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

    if isinstance(result, design_steps.Calculation):
        _discard(result)


def project_changed(_project: Project | None) -> None:
    """Lo que se hace cuando la sesión pasa a tener otro proyecto o ninguno
    (``project_session.add_listener``): el cálculo abierto era del anterior y se descarta."""
    discard_calculation()


# --- Disponibilidad (RF-013-33) ----------------------------------------------------------------


def design_unavailable() -> str | None:
    """Por qué no están disponibles ahora las órdenes de Diseño que escriben (RF-013-33), en el
    idioma de Geoblender: sin proyecto, sin la procedencia o en solo lectura («Proyecto en solo
    lectura: …»), o con la versión activa SUPERADO o DESCARTADO («V02 está en estado SUPERADO:
    cree una versión nueva a partir de ella»); ``None`` si se puede, también sin versión activa
    (la orden que calcula la pide al lanzarla, RF-009-05). Con lo ya leído de las versiones
    (``bl.scene.versions``): no lee el proyecto."""
    return write_unavailable() or scene_versions.not_editable_text()


def _write_poll(cls: type) -> bool:
    """El ``poll`` de lo que escribe: dice por qué no se puede."""
    reason = design_unavailable()
    if reason is not None:
        cls.poll_message_set(reason)  # type: ignore[attr-defined]
        return False
    return True


class DesignCommand:
    """El ``poll`` común de las órdenes de Diseño de R-33: activas con un proyecto en escritura y la
    versión activa editable (o ninguna), y desactivadas con su motivo en las demás
    (:func:`design_unavailable`; RF-013-33). Se pone **antes** de la base de la orden::

        class GEOBLENDER_OT_des_x(DesignCommand, bpy.types.Operator): ...
    """

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _write_poll(cls)


class DesignCommandAware(DesignCommand):
    """Lo de :class:`DesignCommand` y, en una orden de ``ProvenanceAwareOperator``, su descripción
    con el porqué si la versión activa no es editable (RF-013-33, RF-009-21), una sola vez aunque
    la base ya lo dijera."""

    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        about: str = super().description(context, properties)  # type: ignore[misc]
        note = scene_versions.not_editable_text()
        return about if note is None or note in about else with_note(about, note)


# --- Ventanas ------------------------------------------------------------------------------------

TRANSLATION_CONTEXT = "Geoblender"
DIALOG_WIDTH = 520
_HIDDEN = {"HIDDEN", "SKIP_SAVE"}  # las pone quien la lanza (el botón de la ventana)
_FIELD = {"SKIP_SAVE"}  # las rellena el diálogo: nunca las de la vez anterior
PROFILE_KIND_ITEMS = [item for item in KIND_ITEMS if item[0] in ("ADOPTADO", "HIPOTESIS")]
"""Los tipos con que una persona declara los valores de un perfil (RF-013-18, D-7): ADOPTADO o
HIPÓTESIS (``design.profiles.DECLARED_KINDS``)."""
_EXAMPLE = "p"  # un código cualquiera para preguntar el ámbito de las claves de los perfiles


def _call_panel(name: str) -> set[str]:
    """Abre la ventana emergente ``name`` con ``wm.call_panel``; sigue abierta aunque el ratón
    salga de ella (``keep_open``), hasta pulsar fuera o Esc. Una que no está registrada, nada."""
    if getattr(bpy.types, name, None) is None:
        return {"CANCELLED"}
    return bpy.ops.wm.call_panel(name=name, keep_open=True)


def design_error_text(exc: BaseException) -> str:
    """El texto de un error para la persona en el idioma de Geoblender: el de ``design`` en su
    idioma (``DesignError.text`` es el español) y el de los demás, el de ``core``."""
    if isinstance(exc, design_messages.DesignError):
        return des_panels.design_error_text(exc)
    return error_text(exc)


# --- Perfiles de banco… (T22; HU-013-4; RF-013-18, RF-013-19, RF-013-20, RF-013-33) ---------------

EDIT_BENCH_PROFILES = design_profiles.EDIT_COMMAND
SAVE_BENCH_PROFILE = des_panels.SAVE_PROFILE


class ProfileFormError(ValueError):
    """Lo que impide guardar un perfil con lo escrito en el diálogo (ya en el idioma de
    Geoblender)."""


def typed_number(typed: str, field: str) -> float | None:
    """Un número tecleado (con coma o con punto decimal; sin separador de miles): ``None`` si está
    vacío. :class:`ProfileFormError` si no es un número finito, nombrando el campo y lo tecleado
    (los rangos los mira el dominio, RF-013-19)."""
    text = typed.strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if not text:
        return None
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ProfileFormError(tr("«{value}» is not a number (field «{field}»)",
                                  value=typed.strip(), field=field))
    return number


class GEOBLENDER_OT_des_edit_bench_profiles(DesignCommandAware, ProvenanceAwareOperator,
                                            bpy.types.Operator):
    """Bench profiles such as EXPL_10_60_6 or REST_5_35_6"""

    bl_idname = EDIT_BENCH_PROFILES
    bl_label = "Bench profiles…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = design_profiles.EDIT_BENCH_PROFILES

    def execute(self, context: Any) -> set[str]:
        """Lee los perfiles del proyecto y sus valores en la versión activa en la vista y abre su
        ventana; desde un guion sin ventana, solo la vista (RF-013-18, RF-013-20)."""
        try:
            des_panels.fill_profiles(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(des_panels.PROFILES_PANEL)


class GEOBLENDER_OT_des_save_bench_profile(DesignCommandAware, ProvenanceAwareOperator,
                                           bpy.types.Operator):
    """Create a bench profile, complete the values it lacks or rename it"""

    bl_idname = SAVE_BENCH_PROFILE
    bl_label = "Save profile…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = design_profiles.EDIT_BENCH_PROFILES

    code: StringProperty(  # type: ignore[valid-type]
        name="Profile", description="Code of the profile to complete or rename (empty: a new "
        "profile)", options=_HIDDEN)
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the profile, such as EXPL_10_60_6: it can change, its "
        "code cannot", options=_FIELD)
    height: StringProperty(  # type: ignore[valid-type]
        name="Bench height (m)", description="Height of the bench in metres, more than 0",
        options=_FIELD)
    face: StringProperty(  # type: ignore[valid-type]
        name="Face angle (°)", description="Maximum inclination of the bench face in degrees, "
        "between 0 and 90 (both excluded)", options=_FIELD)
    berm: StringProperty(  # type: ignore[valid-type]
        name="Minimum berm width (m)", description="Minimum berm in metres, 0 or more",
        options=_FIELD)
    anchor: StringProperty(  # type: ignore[valid-type]
        name="Anchor elevation (m)", description="Elevation the benches are anchored to, in "
        "metres", options=_FIELD)
    mesh: StringProperty(  # type: ignore[valid-type]
        name="Mesh factor", description="Factor between 0 (excluded) and 1 that reduces the "
        "slope of the envelope for the grid (empty: 1)", options=_FIELD)
    kind: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="Type of the values: adopted or hypothesis",
        items=PROFILE_KIND_ITEMS, default="HIPOTESIS", options=_FIELD)
    source: StringProperty(  # type: ignore[valid-type]
        name="Source", description="Document, standard, person, operation or algorithm the "
        "values come from (empty: the decider)", options=_FIELD)
    source_kind: EnumProperty(  # type: ignore[valid-type]
        name="Source type", items=SOURCE_KIND_ITEMS, default="PERSON", options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided the values (the owner, a laboratory, a "
        "person)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the profile has these values (recorded in its history)",
        options=_FIELD)
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope",
        description="Whether the change is for the project or only for the active version (a "
                    "parameter that its module admits by version)",
        items=PARAMETER_SCOPE_ITEMS, default="PROJECT", options=_FIELD)

    def _stored(self, project: Any) -> design_profiles.StoredProfile | None:
        """La fila del perfil de :attr:`code` en el proyecto; ``ProfileFormError`` si ya no
        está (sin código, ``None``: un perfil nuevo)."""
        if not self.code:
            return None
        with project.read() as conn:
            found = [row for row in design_profiles.read_profiles(conn) if row.code == self.code]
        if not found:
            raise ProfileFormError(tr("The bench profile is no longer in the project: open the "
                                      "list again"))
        return found[0]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo: de un perfil que existe, con su nombre y lo que ya vale en cada ámbito
        (solo se piden los valores que le faltan); de uno nuevo, vacío. Propone el decisor
        (la persona de la sesión) y, de los parámetros de versión con una versión activa, el
        ámbito (RF-009-29); no cambia nada hasta que se acepta."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            row = self._stored(project)
            self._known = {} if row is None else _known_values(project, row.code)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if row is not None:
            self.name = row.name
        if not self.decided_by:
            self.decided_by = project.session.user_host
        if not self.properties.is_property_set("scope"):
            self.scope = "PROJECT"
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Bench profile"),
            confirm_text=tr("Save"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        choice = scope_choice(design_params.bench_key(_EXAMPLE, design_params.BenchParam.HEIGHT))
        if choice is not None:  # «¿Para el proyecto o solo para V01?» (RF-009-29)
            layout.label(text=tr("For the project or only for {version}?", version=choice.code),
                         translate=False)
            row = layout.row(align=True)
            row.use_property_split = False
            row.prop_enum(self, "scope", "PROJECT", text=tr("The project"), translate=False)
            only = row.row(align=True)
            only.enabled = choice.refusal is None  # «Versión no editable» (RF-009-21)
            only.prop_enum(self, "scope", "VERSION",
                           text=tr("Only {version}", version=choice.code), translate=False)
            if choice.refusal is not None:
                refused = layout.row()
                refused.alert = True
                refused.label(text=choice.refusal, icon="ERROR", translate=False)
        known = getattr(self, "_known", {})
        declared = False
        for param, attribute, label in (
                (design_params.BenchParam.HEIGHT, "height", tr("Bench height (m)")),
                (design_params.BenchParam.FACE, "face", tr("Face angle (°)")),
                (design_params.BenchParam.BERM, "berm", tr("Minimum berm width (m)")),
                (design_params.BenchParam.ANCHOR, "anchor", tr("Anchor elevation (m)")),
                (design_params.BenchParam.MESH_FACTOR, "mesh", tr("Mesh factor"))):
            here = known.get(param, {}).get(self.scope)
            if here is not None:  # ya vale en ese ámbito: se cambia con «Cambiar…»
                layout.label(text=tr("{name}: {value}", name=label, value=here), translate=False)
                declared = True
            else:
                layout.prop(self, attribute, text=label, translate=False)
        if declared:
            layout.label(text=tr("Values already declared are changed with «Change…» in the "
                                 "list"), translate=False)
        layout.prop(self, "kind", text=tr("Type"), translate=False)
        layout.prop(self, "source", text=tr("Source"), translate=False)
        layout.prop(self, "source_kind", text=tr("Source type"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def _request(self, project: Any) -> tuple[design_profiles.ProfileEdit,
                                              design_profiles.ProfileDeclaration | None]:
        """Lo escrito, como lo pide el dominio: la edición (un perfil nuevo con sus valores, o el
        existente con su nombre nuevo y los valores que se completan) y la declaración de los
        valores (tipo, origen, decisor, motivo y ámbito). :class:`ProfileFormError` si lo escrito
        no se puede leer o no cambia nada; los rangos, los nombres y los valores que faltan los
        rechaza el dominio (``DesignError``, RF-013-19)."""
        row = self._stored(project)
        param = design_params.BenchParam
        values: dict[Any, float] = {}
        for item, typed, label in (
                (param.HEIGHT, self.height, tr("Bench height (m)")),
                (param.FACE, self.face, tr("Face angle (°)")),
                (param.BERM, self.berm, tr("Minimum berm width (m)")),
                (param.ANCHOR, self.anchor, tr("Anchor elevation (m)")),
                (param.MESH_FACTOR, self.mesh, tr("Mesh factor"))):
            number = typed_number(typed, label)
            if number is not None:  # un perfil nuevo sin un valor: el dominio dice cuál falta
                values[item] = number
        if row is None:
            edit = design_profiles.ProfileEdit(name=self.name, values=values)
        else:
            typed = self.name.strip()  # vacío: se queda con el suyo
            renamed = self.name if typed and typed != row.name else None
            if renamed is None and not values:
                raise ProfileFormError(tr("Nothing to change in «{name}»", name=row.name))
            edit = design_profiles.ProfileEdit(name=renamed, code=row.code, values=values)
        if not values:
            return edit, None
        decided_by = self.decided_by.strip()
        if not decided_by:
            raise ProfileFormError(tr("Write who decides the values of the profile"))
        source = self.source.strip()
        version = None
        if self.scope == "VERSION":  # solo la versión activa (RF-009-24, RF-009-29)
            active = scene_versions.active()
            if active is None:
                raise ProfileFormError(tr("Choose the active version first: Project ▸ "
                                          "Versions ▸ Active version"))
            version = active.code
        kind = ParamKind.ADOPTADO if self.kind == "ADOPTADO" else ParamKind.HIPOTESIS
        return edit, design_profiles.ProfileDeclaration(
            source=source or decided_by, decided_by=decided_by,
            reason=self.reason.strip() or tr("Declared in the bench profiles window"),
            source_kind=self.source_kind.lower() if source else "person", kind=kind.value,
            version=version)

    def execute(self, context: Any) -> set[str]:
        """Crea, completa o renombra el perfil con ``design.profiles.edit_bench_profiles`` (una
        sola operación de proyecto y una sola transacción; RF-013-18). Todo se mira antes de
        escribir: un perfil sin nombre, con el nombre de otro, sin un valor o con uno fuera de
        rango se rechaza nombrando el perfil, el campo y el valor, y no deja nada (RF-013-19)."""
        project = SESSION.project
        try:
            edit, declaration = self._request(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog,
                             version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        try:
            edited = design_profiles.edit_bench_profiles(project, [edit], declaration)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, design_profiles.EDIT_BENCH_PROFILES)
        code = edited.created[0] if edited.created else edit.code
        shown = next(row.name for row in edited.profiles if row.code == code)
        text = (tr("Bench profile «{name}» created with the code «{code}»", name=shown, code=code)
                if edited.created else
                tr("Bench profile «{name}» saved (code «{code}»)", name=shown, code=code))
        try:
            des_panels.fill_profiles(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.warning("No se pudo volver a leer la lista de perfiles de banco", exc_info=True)
        des_panels.choose(code)
        des_panels.show_report([(text, False)])
        self.report({"INFO"}, text)
        return {"FINISHED"}


def _known_values(project: Any, code: str) -> dict[Any, dict[str, str]]:
    """Lo que el perfil ``code`` ya tiene declarado, por valor y ámbito (``PROJECT`` o
    ``VERSION``, el de la versión activa): su texto («10 m [ADO]»). Con ello el diálogo de
    completar no pide lo que ya vale (se cambia con «Cambiar…»)."""
    store = core_params.ParameterStore(project)
    version = scene_versions.active()
    found: dict[Any, dict[str, str]] = {}
    with project.read() as conn:
        for param in design_params.BenchParam:
            key = design_params.bench_key(code, param)
            records = {"PROJECT": store.get(key, conn=conn),
                       "VERSION": None if version is None
                       else store.get(key, version=version.uid, conn=conn)}
            found[param] = {scope: des_panels.record_text(record)
                            for scope, record in records.items()
                            if record is not None and record.value is not None}
    return found


# --- Sectores de diseño… (T23; HU-013-2; RF-013-07 a RF-013-10, RF-013-21, RF-013-33) -----------

EDIT_DESIGN_SECTORS = "geoblender.des_edit_design_sectors"
SET_SECTOR_SLOPE = des_panels.SET_SECTOR_SLOPE


class SectorFormError(ProfileFormError):
    """Lo que impide guardar el talud de un sector con lo escrito en el diálogo (ya en el idioma de
    Geoblender)."""


def _parameters_written(project: Any) -> None:
    """Tras escribir un parámetro: la lista de Parámetros del proyecto, los indicadores (lo que
    dependía de él puede quedar obsoleto) y las ventanas de los perfiles y de los sectores (la
    escucha de los indicadores las pone al día)."""
    try:
        ui_provenance.fill_parameters()
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo volver a leer la lista de parámetros", exc_info=True)
    if ui_provenance.refresh(force=True):
        ui_provenance.redraw()
    des_panels.on_project_read(project)


class GEOBLENDER_OT_des_edit_design_sectors(DesignCommandAware, ProvenanceAwareOperator,
                                            bpy.types.Operator):
    """Sectors with their own bench profile"""

    bl_idname = EDIT_DESIGN_SECTORS
    bl_label = "Design sectors…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[str]:
        """Lee los sectores del proyecto —los de la 012 o el perímetro de actuación— con el estado
        de su búsqueda, el talud que impone cada uno en la versión activa y los huérfanos, y las
        capas de las que se pueden declarar de nuevo, y abre su ventana; desde un guion sin
        ventana, solo la vista (RF-013-07)."""
        project = SESSION.project
        try:
            des_panels.fill_sectors(project)
            des_panels.fill_sector_sources(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        des_panels.show_sector_report(())
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(des_panels.SECTORS_PANEL)


class GEOBLENDER_OT_des_set_sector_slope(DesignCommandAware, ProvenanceAwareOperator,
                                         bpy.types.Operator):
    """Set the maximum general slope that a sector imposes on the design"""

    bl_idname = SET_SECTOR_SLOPE
    bl_label = "Set the sector slope…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    code: StringProperty(  # type: ignore[valid-type]
        name="Sector", description="Code of the sector whose slope is set (empty: the action "
        "perimeter, when it is the only sector)", options=_HIDDEN)
    slope: StringProperty(  # type: ignore[valid-type]
        name="Maximum general slope (°)", description="Maximum general slope that the sector "
        "imposes on the design in degrees, between 0 and 90 (both excluded)", options=_FIELD)
    kind: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="Type of the value: adopted or hypothesis",
        items=PROFILE_KIND_ITEMS, default="ADOPTADO", options=_FIELD)
    source: StringProperty(  # type: ignore[valid-type]
        name="Source", description="Document, standard, person, operation or algorithm the "
        "value comes from (empty: the decider)", options=_FIELD)
    source_kind: EnumProperty(  # type: ignore[valid-type]
        name="Source type", items=SOURCE_KIND_ITEMS, default="PERSON", options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided the value (the owner, a laboratory, a "
        "person)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the slope has this value (recorded in its history)",
        options=_FIELD)
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope",
        description="Whether the change is for the project or only for the active version (a "
                    "parameter that its module admits by version)",
        items=PARAMETER_SCOPE_ITEMS, default="PROJECT", options=_FIELD)

    def _sector(self, project: Any) -> DesignSector:
        """El sector de :attr:`code` tal como está ahora en el proyecto (en la versión activa);
        :class:`SectorFormError` si ya no está."""
        from ...design import sectors as design_sectors  # al usarlo: habilitar no carga el cálculo

        version = scene_versions.active()
        found = design_sectors.design_sectors(project, None if version is None else version.uid)
        for item in found:
            if item.code == self.code:
                return item
        raise SectorFormError(tr("The sector is no longer in the project: open the list again"))

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo: del sector que se elige, con lo que ya impone en el ámbito (su valor,
        su tipo, su origen y su decisor); propone el decisor (la persona de la sesión) y, con una
        versión activa, el ámbito (RF-009-29: la versión si ya tiene valor propio, y si no, el
        proyecto); no cambia nada hasta que se acepta."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            sector = self._sector(project)
            choice = scope_choice(sector.key)
            store = core_params.ParameterStore(project)
            with project.read() as conn:
                shared = store.get(sector.key, conn=conn)
                own = None if choice is None else store.get(
                    sector.key, version=choice.version_uid, conn=conn)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if choice is None or choice.refusal is not None:
            self.scope = "PROJECT"
        elif not self.properties.is_property_set("scope"):
            self.scope = "PROJECT" if own is None else "VERSION"
        record = own if self.scope == "VERSION" and own is not None else shared
        decided = ""
        if record is not None and record.value is not None:
            self.slope = typed_value(record.value, i18n.language())
            if record.kind.name in ("ADOPTADO", "HIPOTESIS"):
                self.kind = record.kind.name
            self.source = record.source
            self.source_kind = record.source_kind.name
            decided = "" if record.decided_by == core_params.DEFAULT_DECIDER else record.decided_by
        else:
            self.slope = ""
        self.decided_by = decided or project.session.user_host
        self._title = tr("Maximum general slope of {sector}",
                         sector=constraint_panels.sector_name(sector.code, sector.name))
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Sector slope"),
            confirm_text=tr("Save"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.label(text=getattr(self, "_title", self.code), translate=False)
        try:
            choice = scope_choice(design_params.sector_slope_key(self.code or PERIMETER_SEGMENT))
        except ValueError:  # un código que no es de sector: nada que preguntar
            choice = None
        if choice is not None:  # «¿Para el proyecto o solo para V01?» (RF-009-29)
            layout.label(text=tr("For the project or only for {version}?", version=choice.code),
                         translate=False)
            row = layout.row(align=True)
            row.use_property_split = False
            row.prop_enum(self, "scope", "PROJECT", text=tr("The project"), translate=False)
            only = row.row(align=True)
            only.enabled = choice.refusal is None  # «Versión no editable» (RF-009-21)
            only.prop_enum(self, "scope", "VERSION",
                           text=tr("Only {version}", version=choice.code), translate=False)
            if choice.refusal is not None:
                refused = layout.row()
                refused.alert = True
                refused.label(text=choice.refusal, icon="ERROR", translate=False)
        layout.prop(self, "slope", text=tr("Maximum general slope (°)"), translate=False)
        layout.prop(self, "kind", text=tr("Type"), translate=False)
        layout.prop(self, "source", text=tr("Source"), translate=False)
        layout.prop(self, "source_kind", text=tr("Source type"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def _request(self, project: Any) -> tuple[DesignSector, float]:
        """Lo escrito, ya comprobado: el sector y el talud en grados. :class:`SectorFormError` si
        el sector ya no está, falta el talud o quién lo decide, o no es un número; el rango (0 a
        90°, ambos excluidos) lo rechaza el dominio (``DesignError``, nombrando el sector, el
        campo y el valor)."""
        sector = self._sector(project)
        degrees = typed_number(self.slope, tr("Maximum general slope (°)"))
        if degrees is None:
            raise SectorFormError(tr("Write the maximum general slope of the sector"))
        design_params.check_sector_slope(sector.code or PERIMETER_SEGMENT, degrees)
        if not self.decided_by.strip():
            raise SectorFormError(tr("Write who decides the slope of the sector"))
        return sector, degrees

    def execute(self, context: Any) -> set[str]:
        """Guarda el talud del sector como su parámetro (``des.sector.{código}.
        max_general_slope_deg``) en el proyecto o solo en la versión activa: lo da de alta la
        primera vez en el ámbito y lo cambia después, con su tipo, su origen, su decisor y su
        motivo (RF-013-08); el de otro sector o de otra versión no cambia. Todo se mira antes de
        escribir: nada queda si se rechaza. Apunta Ctrl+Z (no deshace la BD) y pone al día las
        ventanas (RF-013-07)."""
        project = SESSION.project
        try:
            sector, degrees = self._request(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        version = None
        if self.scope == "VERSION":  # solo la versión activa (RF-009-24, RF-009-29)
            active = scene_versions.active()
            if active is None:
                self.report({"ERROR"}, tr("Choose the active version first: Project ▸ "
                                          "Versions ▸ Active version"))
                return {"CANCELLED"}
            version = active
        decided_by, source = self.decided_by.strip(), self.source.strip()
        given: dict[str, Any] = {
            "kind": ParamKind.ADOPTADO if self.kind == "ADOPTADO" else ParamKind.HIPOTESIS,
            "source": source or decided_by,
            "source_kind": self.source_kind.lower() if source else "person",
            "decided_by": decided_by,
            "reason": self.reason.strip() or tr("Declared in the design sectors window"),
            "version": None if version is None else version.uid}
        store = core_params.ParameterStore(project)
        try:
            with project.write_transaction() as conn:
                if store.get(sector.key, version=given["version"], conn=conn) is None:
                    saved = store.create(conn, sector.key, degrees, **given)
                else:
                    saved = store.change(conn, sector.key, value=degrees, **given)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.PARAMETER, saved.key)  # Ctrl+Z no lo deshace
        _parameters_written(project)
        des_panels.choose_sector(sector.code)
        message = tr("Slope imposed by {sector} in {scope}: {value}",
                     sector=constraint_panels.sector_name(sector.code, sector.name),
                     scope=version.code if version is not None else tr("the project"),
                     value=des_panels.slope_text(saved))
        des_panels.show_sector_report([(message, False)])
        self.report({"INFO"}, message)
        return {"FINISHED"}


DECLARE_SECTORS_AGAIN = des_panels.DECLARE_SECTORS_AGAIN
_REPORTED_ERROR = "Error: "  # cómo empieza cada línea del error de una orden lanzada con bpy.ops


def _declare_sectors(mode: str) -> set[str]:
    """La orden de la 012 que declara los sectores (``core_declare_sectors``) con la capa y el
    campo de su vista, lanzada como ``mode`` (``INVOKE_DEFAULT`` desde la interfaz: su ``invoke``
    y, si hace falta, el diálogo de la entrada cambiada; ``EXEC_DEFAULT`` desde un guion). Lo que
    rechaza llega como ``RuntimeError`` con su texto."""
    name = des_panels.DECLARE_SECTORS.split(".", 1)[1]
    return set(getattr(bpy.ops.geoblender, name)(mode))


def _error_lines(exc: RuntimeError) -> list[str]:
    """Los errores que dijo una orden lanzada con ``bpy.ops`` (``Error: …`` por línea), sin la
    palabra que Blender les antepone."""
    return [line.removeprefix(_REPORTED_ERROR) for line in str(exc).splitlines() if line.strip()]


class GEOBLENDER_OT_des_declare_sectors(DesignCommandAware, ProvenanceAwareOperator,
                                       bpy.types.Operator):
    """Declare the sectors again from the layer of polygons of the window and read the design
    sectors again"""

    bl_idname = DECLARE_SECTORS_AGAIN
    bl_label = "Declare the sectors again"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context: Any) -> set[str]:
        """«Declarar de nuevo desde una capa…» de la ventana de los sectores (RF-013-07,
        RF-013-10; T44): la declaración es la de la 012 (``core_declare_sectors``, que conserva los
        valores de los sectores que mantienen su código), lanzada como se lanzó esta (desde la
        interfaz, con su ``invoke``); solo si termina, vuelve a leer en la misma ventana los
        sectores, los huérfanos y las capas, y deja en ella y en la barra de estado lo que dice la
        012. Cancelada o rechazada, la ventana queda como estaba y se dice su error."""
        mode = "INVOKE_DEFAULT" if self.provenance_dialog else "EXEC_DEFAULT"
        try:
            done = _declare_sectors(mode)
        except RuntimeError as exc:  # la 012 lo rechazó: su texto (bpy.ops no lo pasa a la barra)
            for line in _error_lines(exc):
                self.report({"ERROR"}, line)
            return {"CANCELLED"}
        if "FINISHED" not in done:
            return {"CANCELLED"}
        other = constraint_panels.view()
        said = [] if other is None else [(line.text, bool(line.alert))
                                         for line in other.search_lines]
        project = SESSION.project
        try:
            des_panels.fill_sectors(project)
            des_panels.fill_sector_sources(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            LOGGER.warning("No se pudo volver a leer los sectores de diseño", exc_info=True)
            said.append((design_error_text(exc), True))
        des_panels.show_sector_report(said)
        for text, alert in said:
            self.report({"WARNING" if alert else "INFO"}, text)
        return {"FINISHED"}


# --- Envolventes y escalonado… (T24; HU-013-1, HU-013-3, HU-013-5, HU-013-6; RF-013-05,
#     RF-013-16, RF-013-17, RF-013-21, RF-013-31, RF-013-33; plan §5.3.3, §5.5, D-14, D-27, D-30) --

COMPUTE_ENVELOPE = "geoblender.des_compute_envelope"
ENVELOPE_STAGE = provenance.ENVELOPE
STEPPED_STAGE = provenance.STEPPED
SEEDS_FROM_ITEMS = [
    ("SURFACE", "A surface in a zone", ""),
    ("FIXED", "A fixed elevation in a zone", ""),
    ("GRID", "A grid of elevations", ""),
]
"""De dónde salen las semillas (``design.model.SeedKind``): la superficie en las celdas de una zona,
una cota fija en las celdas de una zona o una rejilla de cotas."""
DIRECTION_ITEMS = [("DOWN", "Downwards", ""), ("UP", "Upwards", "")]
METRIC_ITEMS = [("CHAMFER5", "Chamfer 5×5", ""), ("EXACT", "Exact Euclidean", "")]
QUARRY_METRIC_ITEMS = [("CHAMFER5", "Chamfer 5×5", "")]
"""La métrica de cada superficie de la cantera (spec 014, T45; RF-014-12): solo el *chamfer* 5×5,
porque cada lado va con la pendiente de sus sectores y la euclídea exacta solo admite una pendiente
constante (la de «Envolventes y escalonado…» de la 013 sigue con :data:`METRIC_ITEMS`)."""
SLOPE_ITEMS = [("CONSTANT", "Constant", ""), ("SECTORS", "By sectors", "")]
BOUND_ITEMS = [("ALL", "The whole domain", ""), ("SECTORS", "Some sectors", ""),
               ("LAYER", "A layer of polygons", "")]
SENSE_ITEMS = [("CUT", "Cut (face first)", ""), ("FILL", "Fill (berm first)", "")]


class ComputeFormError(ProfileFormError):
    """Lo que impide calcular con lo escrito en el diálogo de las envolventes (ya en el idioma de
    Geoblender)."""


@dataclass(frozen=True)
class _Plan:
    """Lo pedido en el diálogo, ya comprobado: la envolvente, su escalonado si se pidió, la
    superficie de la que parte y el perfil de cada sector (código del sector → código del perfil)
    cuando hacen falta."""

    envelope: design_model.EnvelopeRequest
    design: design_model.DesignRequest | None
    start: str
    assigned: dict[str, str]


def _zone_of(identifier: str) -> design_model.Zone | None:
    """La zona de una opción de la lista de zonas (``bl.ui.des_panels.zone_items``): ninguna (toda
    la superficie), el dominio por defecto, o una restricción, un sector o una capa por su código o
    su nombre."""
    if identifier in ("", des_panels.NO_ZONE):
        return None
    kinds = design_model.ZoneKind
    if identifier == des_panels.DOMAIN_ZONE:
        return design_model.Zone(kinds.DOMAIN)
    for prefix, kind in ((des_panels.CONSTRAINT_ZONE, kinds.CONSTRAINT),
                         (des_panels.SECTOR_ZONE, kinds.SECTOR), (des_panels.LAYER_ZONE, kinds.LAYER)):
        if identifier.startswith(prefix) and identifier[len(prefix):]:
            return design_model.Zone(kind, identifier[len(prefix):])
    raise ComputeFormError(tr("Choose the zone of the seeds"))


def seed_source(seeds_from: str, surface: str, zone: str, elevation: str
                ) -> design_model.SeedSource:
    """Las semillas pedidas en un diálogo (el de las envolventes y el de la vista previa): de dónde
    salen (``SURFACE``, ``FIXED`` o ``GRID``), la superficie o rejilla de cotas, la zona (una opción
    de ``bl.ui.des_panels.zone_items``) y la cota fija tecleada. Las que faltan o no valen las
    rechaza el dominio al calcular (``des.seed_missing``, ``des.seed_elevation``…);
    :class:`ComputeFormError` si falta algo del diálogo."""
    kind = design_model.SeedKind(seeds_from.lower())
    if kind is design_model.SeedKind.FIXED:
        value = typed_number(elevation, tr("Elevation (m)"))
        if value is None:
            raise ComputeFormError(tr("Write the fixed elevation of the seeds in metres"))
        return design_model.SeedSource(kind, zone=_zone_of(zone), elevation_m=value)
    if surface in ("", des_panels.NO_ZONE):
        raise ComputeFormError(tr("Choose the surface of the seeds: there are no grids in the "
                                  "project or in the active version"))
    if kind is design_model.SeedKind.GRID:
        return design_model.SeedSource(kind, grid=surface)
    return design_model.SeedSource(kind, surface=surface, zone=_zone_of(zone))


def work_domain(bound: str, bound_layer: str, shown: Any) -> design_model.WorkDomain:
    """El acotado del dominio de trabajo pedido en un diálogo (RF-013-02): todo, los sectores
    marcados en la vista (``shown.sectors[].use``) o una capa de polígonos; nunca se amplía.
    :class:`ComputeFormError` si falta algo del diálogo."""
    if bound == "SECTORS":
        codes = tuple(item.code for item in shown.sectors if item.use and item.code)
        if not codes:
            raise ComputeFormError(tr("Mark the sectors the work domain is bound to"))
        return design_model.WorkDomain(sectors=codes)
    if bound == "LAYER":
        if bound_layer in ("", des_panels.NO_LAYER):
            raise ComputeFormError(tr("Choose the layer of polygons the work domain is bound "
                                      "to"))
        return design_model.WorkDomain(layer=bound_layer)
    return design_model.WorkDomain()


def _draw_seeds(layout: Any, operator: Any) -> None:
    """Las semillas de un diálogo (el de las envolventes y el de la vista previa): su origen, la
    superficie o la rejilla de cotas, la zona y la cota fija, según el origen."""
    seeds = layout.box()
    seeds.label(text=tr("Seeds"), translate=False)
    seeds.prop(operator, "seeds_from", text=tr("Origin of the seeds"), translate=False)
    if operator.seeds_from != "FIXED":
        seeds.prop(operator, "surface", text=tr("Surface") if operator.seeds_from == "SURFACE"
                   else tr("Grid of elevations"), translate=False)
    if operator.seeds_from != "GRID":
        seeds.prop(operator, "zone", text=tr("Zone of the seeds"), translate=False)
    if operator.seeds_from == "FIXED":
        seeds.prop(operator, "elevation", text=tr("Elevation (m)"), translate=False)


def _draw_bound(layout: Any, operator: Any) -> None:
    """El acotado del dominio de un diálogo: a todo, a unos sectores o a una capa de polígonos (la
    casilla de cada sector la dibuja ``bl.ui.des_panels.draw_sector_rows``)."""
    layout.prop(operator, "bound", text=tr("Bound to"), translate=False)
    if operator.bound == "LAYER":
        layout.prop(operator, "bound_layer", text=tr("Layer of polygons"), translate=False)


def _invoke_later(idname: str, window: Any, **values: Any) -> None:
    """Lanza la orden ``idname`` con ``INVOKE_DEFAULT`` y ``values`` en la ventana ``window`` en
    cuanto acaba lo que corre (un diálogo no se abre desde dentro de un modal); sin ventana,
    nada."""
    if window is None:
        return
    group, name = idname.split(".")

    def call() -> None:
        try:
            with bpy.context.temp_override(window=window):
                getattr(getattr(bpy.ops, group), name)("INVOKE_DEFAULT", **values)
        except (RuntimeError, TypeError, AttributeError, ReferenceError):
            LOGGER.warning("No se pudo pedir confirmación en %s", idname, exc_info=True)

    bpy.app.timers.register(call, first_interval=0.0)


def _first_window() -> Any:
    manager = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(manager, "windows", ()) or ())
    return windows[0] if windows else None


def _ask_confirmation(context: Any = None, *, idname: str = COMPUTE_ENVELOPE) -> None:
    """Pide confirmar el cálculo recién hecho (D-14): la misma orden (``idname``, por defecto
    «Envolventes y escalonado…») con ``confirm=True`` en cuanto acaba el modal (un diálogo no se
    abre desde dentro de un modal); sin ventana, nada (lo dice el informe y el cálculo espera a que
    se cree con ``confirm=True``)."""
    _invoke_later(idname, getattr(context, "window", None) or _first_window(), confirm=True)


def _confirm_later(values: Mapping[str, Any], idname: str) -> None:
    """Pide confirmar que se sustituye el fichero que ya existe (D-29 de la 011): la misma orden
    ``idname`` con ``confirm`` (su confirmación) y ``values``, en cuanto acaba ésta; sin ventana,
    nada (lo dice el aviso)."""
    _invoke_later(idname, _first_window(), confirm=True, **values)


def _drain(operator: Any, steps: Iterator[Progress]) -> Any:
    """Los pasos ``steps`` de una orden de una vez (desde un guion): el resultado del último o, si
    fallan, ``None`` (ya dicho con el ``_report`` de ``operator``; sus pasos no dejan nada a
    medias)."""
    found = None
    try:
        for step in steps:
            if step.result is not None:
                found = step.result
    except GeoblenderError as exc:
        operator._report({"ERROR"}, operator._error_text(exc))
        return None
    except (sqlite3.Error, OSError, ValueError) as exc:
        LOGGER.error("«%s» se ha parado", operator.bl_idname, exc_info=exc)
        operator._report({"ERROR"}, error_text(exc))
        return None
    if found is None:  # pragma: no cover - los pasos acaban siempre con su resultado
        operator._report({"ERROR"}, tr("The operation did not finish with its result"))
    return found


class GEOBLENDER_OT_des_compute_envelope(DesignCommandAware, ProvenanceAwareOperator,
                                         _StepsModal, bpy.types.Operator):
    """Envelope of an excavation or a fill and, if you want, its benching and design surface"""

    bl_idname = COMPUTE_ENVELOPE
    bl_label = "Envelopes and benching…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.ENVELOPE

    # Como Compilar las máscaras: cada evento del temporizador avanza pasos durante, como mucho,
    # este tiempo (cada paso, ≤ 0,05 s: ninguna llamada de más de 0,2 s, RNF-013-07).
    STEP_BUDGET_S = 0.05

    name: StringProperty(  # type: ignore[valid-type]
        name="Name",
        description="Name of the envelope, unique in the active version; its benching has the same "
                    "name", options=_FIELD)
    seeds_from: EnumProperty(  # type: ignore[valid-type]
        name="Origin of the seeds",
        description="Where the seeds come from: the cells of a surface inside a zone, a fixed "
                    "elevation in the cells of a zone or a grid of elevations of the project or of "
                    "the active version", items=SEEDS_FROM_ITEMS, default="SURFACE", options=_FIELD)
    surface: EnumProperty(  # type: ignore[valid-type]
        name="Surface",
        description="Surface or grid of elevations of the project or of the active version the "
                    "seeds are read from", items=des_panels.surface_items, options=_FIELD)
    zone: EnumProperty(  # type: ignore[valid-type]
        name="Zone of the seeds",
        description="Cells where the seeds are: the whole surface, the default domain, the zone "
                    "of a constraint, a design sector or a layer of polygons",
        items=des_panels.zone_items, options=_FIELD)
    elevation: StringProperty(  # type: ignore[valid-type]
        name="Elevation (m)", description="Fixed elevation of the seeds in metres", options=_FIELD)
    direction: EnumProperty(  # type: ignore[valid-type]
        name="Envelope direction",
        description="Downwards: the lowest surface that does not go under the seeds; upwards: the "
                    "highest surface that does not go over them",
        items=DIRECTION_ITEMS, default="DOWN", options=_FIELD)
    metric: EnumProperty(  # type: ignore[valid-type]
        name="Metric",
        description="How the distance to the seeds is measured: the 5×5 chamfer (fast, with the "
                    "scale of the grid) or the exact Euclidean distance (constant slope only)",
        items=METRIC_ITEMS, default="CHAMFER5", options=_FIELD)
    slope_mode: EnumProperty(  # type: ignore[valid-type]
        name="Slope",
        description="A constant slope or the general slope of each sector (the maximum it imposes "
                    "or, without one, that of its profile)",
        items=SLOPE_ITEMS, default="CONSTANT", options=_FIELD)
    slope: StringProperty(  # type: ignore[valid-type]
        name="Slope (°)",
        description="Slope of the envelope in degrees, from 0 (included) to 90 (excluded)",
        options=_FIELD)
    mesh: StringProperty(  # type: ignore[valid-type]
        name="Mesh factor",
        description="Factor between 0 (excluded) and 1 that reduces the slope of the envelope for "
                    "the grid (empty: 1)", options=_FIELD)
    reach: StringProperty(  # type: ignore[valid-type]
        name="Reach",
        description="Largest distance from the seeds, in metres, at which the envelope has data "
                    "(empty: no limit)", options=_FIELD)
    bound: EnumProperty(  # type: ignore[valid-type]
        name="Bound to",
        description="Where the work domain is bound: the whole domain of the masks, some sectors "
                    "or a layer of polygons (it is never enlarged)",
        items=BOUND_ITEMS, default="ALL", options=_FIELD)
    bound_layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of polygons",
        description="Layer of polygons of the project the work domain is bound to",
        items=des_panels.layer_items, options=_FIELD)
    stepped: BoolProperty(  # type: ignore[valid-type]
        name="Bench the envelope", default=False,
        description="After creating the envelope, bench it into benches and berms and compose the "
                    "design surface (with its own summary to confirm)", options=_FIELD)
    sense: EnumProperty(  # type: ignore[valid-type]
        name="Sense",
        description="Cut: the face first, the surface stays over the envelope; fill: the berm "
                    "first, the surface stays under it",
        items=SENSE_ITEMS, default="CUT", options=_FIELD)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the benching starts from: the ground the design is composed with",
        items=des_panels.surface_items, options=_FIELD)
    base_profile: StringProperty(  # type: ignore[valid-type]
        name="Base profile",
        description="Bench profile of the cells without a sector (and of the sectors without "
                    "their own)", options=_FIELD)
    anchor: EnumProperty(  # type: ignore[valid-type]
        name="Anchor",
        description="Elevation the benches are anchored to: that of each profile or a grid of "
                    "anchors of the project or of the active version",
        items=des_panels.anchor_items, options=_FIELD)
    # La confirmación de crear (D-14) y los pasos con el temporizador de la ventana, con el avance y
    # Esc: los pone invoke; desde un guion, sin ellos, de una vez.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué.
        Con ``confirm``, el diálogo de crear el cálculo abierto (D-14). Si no, las listas de
        superficies, zonas, capas, perfiles y sectores leídas de nuevo, la propuesta (el nombre, la
        superficie y la de partida: el terreno) y el diálogo del cálculo: Intro calcula."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.fill_profiles(project)
            des_panels.fill_sectors(project)
            des_panels.refresh_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        des_panels.clear_sector_marks()
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.bl_idname)].label),
            confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """El nombre y las superficies que propone el diálogo si quien lo lanza no los dio. De
        «Superficie» y de «Superficie de partida», el terreno (T45): el MDT o el TIN seleccionado
        en la vista; con una superficie de diseño seleccionada, la de partida de su ficha; sin
        selección, la primera de la lista que no es una rejilla de un diseño
        (``surface_proposal.ground_item``). La lista las sigue ofreciendo todas."""
        given = self.properties.is_property_set
        if not self.name.strip():
            self.name = tr("Envelope")
        if des_panels.has_surfaces():
            items = [identifier for identifier, _name, _about
                     in des_panels.surface_items(None, None)]
            ground = surface_proposal.ground_item(context, project, items,
                                                  des_panels.surface_choice)
            if not given("surface"):
                self.surface = ground
            if not given("start"):
                self.start = ground

    def _confirmation(self, context: Any) -> set[str]:
        """El diálogo de crear el cálculo abierto (D-14, RF-013-31): su resumen con los avisos y
        «Crear» (o «Crear con N avisos», que los nombra); «Cancelar» y cerrarlo lo descartan."""
        held = calculation()
        if held is None:
            self.report({"ERROR"}, tr("There is no open calculation: compute first"))
            return {"CANCELLED"}
        count = len(held.warnings())
        if not count:
            confirm_text = tr("Create")
        elif count == 1:
            confirm_text = tr("Create with 1 warning")
        else:
            confirm_text = tr("Create with {count} warnings", count=count)
        shown = des_panels.view()
        title = shown.summary_title if shown is not None and shown.summary_title else (
            command_text(catalog().commands[command_idname(self.bl_idname)].label))
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=title, confirm_text=confirm_text)

    def draw(self, context: Any) -> None:
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        shown = des_panels.view()
        layout.prop(self, "name", text=tr("Name"), translate=False)
        _draw_seeds(layout, self)
        layout.prop(self, "direction", text=tr("Envelope direction"), translate=False)
        layout.prop(self, "metric", text=tr("Metric"), translate=False)
        layout.prop(self, "slope_mode", text=tr("Slope"), translate=False)
        if self.slope_mode == "CONSTANT":
            layout.prop(self, "slope", text=tr("Slope (°)"), translate=False)
        layout.prop(self, "mesh", text=tr("Mesh factor"), translate=False)
        layout.prop(self, "reach", text=tr("Reach"), translate=False)
        _draw_bound(layout, self)
        layout.prop(self, "stepped", text=tr("Bench the envelope"), toggle=True, translate=False)
        if self.stepped:
            layout.prop(self, "sense", text=tr("Sense"), translate=False)
            layout.prop(self, "start", text=tr("Start surface"), translate=False)
            layout.prop(self, "anchor", text=tr("Anchor"), translate=False)
        profiles = self.stepped or self.slope_mode == "SECTORS"
        if profiles and shown is not None:
            layout.prop_search(self, "base_profile", shown, "profiles", text=tr("Base profile"),
                               translate=False)
        bound = self.bound == "SECTORS"
        if (bound or profiles) and shown is not None and len(shown.sectors):
            box = layout.box()
            box.label(text=tr("Sectors"), translate=False)
            des_panels.draw_sector_rows(box, bound=bound, profiles=profiles)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _seeds(self) -> design_model.SeedSource:
        """Las semillas pedidas; las que faltan o no valen las rechaza el dominio al calcular
        (``des.seed_missing``, ``des.seed_elevation``…)."""
        return seed_source(self.seeds_from, self.surface, self.zone, self.elevation)

    def _domain(self, shown: Any) -> design_model.WorkDomain:
        """El acotado del dominio de trabajo pedido (RF-013-02): todo, los sectores marcados o una
        capa; nunca se amplía."""
        return work_domain(self.bound, self.bound_layer, shown)

    @staticmethod
    def _profile_code(picked: str, where: str, codes: Mapping[str, str]) -> str | None:
        """El código del perfil de banco que se eligió por su nombre (``None`` si no se eligió
        ninguno); :class:`ComputeFormError` si ya no existe."""
        wanted = picked.strip()
        if not wanted:
            return None
        found = codes.get(wanted)
        if found is None:
            raise ComputeFormError(tr("The bench profile «{profile}» ({where}) is not in the "
                                      "project", profile=wanted, where=where))
        return found

    def _plan(self, project: Any) -> _Plan:
        """Lo pedido en el diálogo, comprobado sin escribir ni calcular nada: los perfiles y los
        sectores se leen de nuevo (un guion no abre el diálogo) y las peticiones del dominio se
        arman con ellos. Los rangos, las semillas y los perfiles sin valor los rechaza el dominio
        al calcular (RF-013-16, RF-013-19). :class:`ComputeFormError` si falta algo del diálogo."""
        des_panels.fill_profiles(project)
        des_panels.fill_sectors(project)
        shown = des_panels.view()
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the envelope"))
        seeds = self._seeds()
        mode = design_model.SlopeMode(self.slope_mode.lower())
        constant = mode is design_model.SlopeMode.CONSTANT
        slope = typed_number(self.slope, tr("Slope (°)")) if constant else None
        if constant and slope is None:
            raise ComputeFormError(tr("Write the slope of the envelope in degrees"))
        mesh = typed_number(self.mesh, tr("Mesh factor"))
        reach = typed_number(self.reach, tr("Reach"))
        domain = self._domain(shown)
        codes = des_panels.profile_codes()
        base = self._profile_code(self.base_profile, tr("Base profile"), codes)
        assigned: dict[str, str] = {}
        for item in shown.sectors:
            found = self._profile_code(item.profile_pick, item.name, codes)
            if found is not None:
                assigned[item.code] = found
        by_sectors = not constant
        envelope = design_model.EnvelopeRequest(
            name, self.direction.lower(), seeds, slope_mode=mode, slope_deg=slope,
            metric=self.metric.lower(), mesh_factor=1.0 if mesh is None else mesh, reach_m=reach,
            domain=domain, base_profile=base if by_sectors else None,
            sector_profiles=assigned if by_sectors else {})
        if not self.stepped:
            return _Plan(envelope, None, "", assigned if by_sectors else {})
        if base is None:
            raise ComputeFormError(tr("Choose the base profile of the benching"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the benching"))
        design = design_model.DesignRequest(
            name, name, self.sense.lower(), base, assigned,
            None if self.anchor in ("", des_panels.NO_ANCHOR) else self.anchor)
        return _Plan(envelope, design, self.start, assigned)

    # --- Calcular -----------------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido
        (sin escribir nada si no vale), pasa por la puerta de la 008 y calcula la envolvente por
        pasos con ``design.steps.envelope_run`` —compila las máscaras antes si no están al día—,
        sin registrar nada (D-14): desde la interfaz, en el modal con el avance y Esc; desde un guion,
        de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar."""
        if self.confirm:
            return self._create(context)
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        version = scene_versions.active_version() or ""
        try:
            plan = self._plan(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.envelope_run(project, plan.envelope, version=version,
                                          budget_s=self.STEP_BUDGET_S)
        if plan.design is not None:
            _NEXT[:] = [_Next(plan.design, plan.start, version)]
        des_panels.assign_profiles(project, plan.assigned)  # RF-013-21: lo asignado, en la vista
        return self._run(context, project, plan.envelope.name, ENVELOPE_STAGE, steps)

    def _run(self, context: Any, project: Any, name: str, stage: str,
             steps: Iterator[Progress]) -> set[str]:
        """Corre los pasos de una fase (la envolvente o su escalonado): en el modal, con el avance y
        Esc, o de una vez desde un guion."""
        self._project, self._name, self._stage = project, name, stage
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, steps)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        calculated = _drain(self, steps)
        if calculated is None:
            _NEXT.clear()
            return {"CANCELLED"}
        self._finished(context, calculated)
        return {"FINISHED"}

    def _finished(self, context: Any, opened: Calculation) -> None:
        """Lo que hace al terminar un cálculo (RF-013-31): lo deja abierto y sin registrar, enseña su
        resumen con los avisos (en el informe y en la vista) y, desde la interfaz, pide confirmar."""
        hold_calculation(opened)
        des_panels.show_summary(opened)
        shown = des_panels.view()
        for line in () if shown is None else shown.summary:
            self._report({"WARNING" if line.alert else "INFO"}, line.name)
        if self.in_steps and getattr(context, "window", None) is not None:
            _ask_confirmation(context)

    # --- Crear --------------------------------------------------------------------------------

    def _create(self, context: Any) -> set[str]:
        """«Crear» (D-14, RF-013-17, RF-013-31): registra el cálculo abierto en una transacción
        (``Calculation.create``: la operación, su dato, sus tablas y sus cifras); si falla, no queda
        nada. Si se había pedido el escalonado, sigue con él (la envolvente ya está en la versión)."""
        project = SESSION.project
        opened = calculation()
        if opened is None:
            self.report({"ERROR"}, tr("There is no open calculation: compute first"))
            return {"CANCELLED"}
        try:
            opened.create()
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            discard_calculation()
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, opened.op_type)  # Ctrl+Z no lo deshace
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        des_panels.show_summary(None)
        self.report({"INFO"}, tr("Envelope «{name}» created in {version}", name=opened.name,
                                 version=opened.version)
                    if opened.op_type == ENVELOPE_STAGE
                    else tr("Benching «{name}» created in {version}", name=opened.name,
                            version=opened.version))
        following = _NEXT.pop() if _NEXT and opened.op_type == ENVELOPE_STAGE else None
        _NEXT.clear()
        if following is None:
            return {"FINISHED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        try:
            steps = design_steps.design_run(project, following.request, following.surface,
                                            version=following.version,
                                            budget_s=self.STEP_BUDGET_S)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return self._run(context, project, following.request.name, STEPPED_STAGE, steps)

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado (plan §5.5): «Calculando la envolvente… 40 % · Esc:
        cancelar» o, en la segunda fase, «Calculando el escalonado… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if getattr(self, "_stage", ENVELOPE_STAGE) == STEPPED_STAGE:
            return tr("Computing the benching… {percent} % · Esc: cancel", percent=percent)
        return tr("Computing the envelope… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Calculation cancelled: nothing has been left half-done")

    def _error_text(self, exc: GeoblenderError) -> str:
        """El error de los pasos en el idioma de Geoblender; si falló el escalonado, dice que la
        envolvente ya está creada."""
        found = design_error_text(exc)
        if getattr(self, "_stage", ENVELOPE_STAGE) != STEPPED_STAGE:
            return found
        return f"{found} " + tr("The envelope «{name}» is already created: only its benching has "
                                "not been computed", name=getattr(self, "_name", ""))

    def _after_stop(self, context: Any) -> None:
        """Tras cancelar o fallar: el escalonado que esperaba no sigue."""
        _NEXT.clear()

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        """Con el proyecto del cálculo cerrado, en cualquier paso (también el último, que trae el
        cálculo hecho: :func:`_discard_late`; spec 014, T48), se para sin dejar nada y lo dice;
        si no, sigue o, con el resultado, lo deja abierto (:meth:`_finished`)."""
        if project_session.current() is not getattr(self, "_project", None):
            _discard_late(step.result)
            return self._fail(context, tr(
                "The project was closed while the design «{name}» was being computed: nothing "
                "has been left half-done", name=getattr(self, "_name", "")))
        if step.result is None:
            return None
        self._done(context)
        self._finished(context, step.result)
        return {"FINISHED"}

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except Exception as exc:  # noqa: BLE001 - los pasos cerrados no dejan nada a medias
            LOGGER.error("«%s» se ha parado", self.bl_idname, exc_info=exc)
            return self._fail(context, design_error_text(exc))

    def cancel(self, context: Any) -> None:
        """Lo que Blender llama al cancelar: un modal en curso cierra sus pasos (como Esc); la
        ventana de la confirmación cerrada sin crear («Cancelar», Esc, apartar el ratón) descarta el
        cálculo abierto y sus temporales (D-14). El diálogo del cálculo no descarta nada."""
        if getattr(self, "_steps", None) is not None:
            _StepsModal.cancel(self, context)
            _NEXT.clear()
        elif self.confirm:
            discard_calculation()


# --- Lo común de las órdenes de la 014 que calculan y crean (spec 014, T20 y T21; D-14 de la 013) --


class _CalculateAndCreate:
    """Lo común de las órdenes de la 014 que **calculan** por pasos y **crean** al confirmar
    («Límite desde el perímetro…», «Cantera con dos superficies…», «Transiciones con el terreno
    no afectado» y «Solo relleno…»), como «Envolventes y
    escalonado…» sin el escalonado que sigue (D-14 de la 013): :meth:`_run_steps` corre los pasos
    del cálculo en el modal con el avance y Esc (``_StepsModal``) o, desde un guion, de una vez;
    al terminar, :meth:`_finished` deja el cálculo abierto con su resumen (``des_panels``) y pide
    confirmar (:func:`_ask_confirmation` con :attr:`COMMAND`); :meth:`_confirmation` es el diálogo
    de **Crear** («Crear con N avisos» si los hay) y :meth:`_create` registra en una transacción;
    **Cancelar**, cerrar esa ventana (:meth:`cancel`), Esc y cerrar el proyecto mientras calcula
    (también en el último paso: :meth:`_result`) no dejan nada. Se pone **antes** de las
    bases de la orden; cada orden da :attr:`COMMAND`, :meth:`_created_text` y su
    ``_status_text``."""

    COMMAND = ""
    """El ``bl_idname`` de la orden, por su constante: en una instancia registrada, ``bl_idname``
    es el nombre de la clase."""
    # Como «Envolventes y escalonado…»: cada paso, ≤ 0,05 s (ninguna llamada de más de 0,2 s).
    STEP_BUDGET_S = 0.05

    def _created_text(self, opened: Calculation) -> str:  # pragma: no cover - cada orden el suyo
        """Lo que dice el informe al crear ``opened``."""
        raise NotImplementedError

    def _confirmation(self, context: Any) -> set[str]:
        """El diálogo de crear el cálculo abierto: su resumen con los avisos y «Crear» (o «Crear
        con N avisos», que los nombra); «Cancelar» y cerrarlo lo descartan."""
        held = calculation()
        if held is None:
            self.report({"ERROR"}, tr("There is no open calculation: compute first"))
            return {"CANCELLED"}
        confirm_text = self._confirm_text(held)
        shown = des_panels.view()
        title = shown.summary_title if shown is not None and shown.summary_title else (
            command_text(catalog().commands[command_idname(self.COMMAND)].label))
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=title, confirm_text=confirm_text)

    def _confirm_text(self, held: Calculation) -> str:
        """Lo que dice el botón de crear el cálculo abierto ``held``: «Crear» o «Crear con N avisos»."""
        count = len(held.warnings())
        if not count:
            return tr("Create")
        if count == 1:
            return tr("Create with 1 warning")
        return tr("Create with {count} warnings", count=count)

    def _run_steps(self, context: Any, project: Any, name: str,
                   steps: Iterator[Progress]) -> set[str]:
        """Corre los pasos ``steps`` del cálculo ``name`` de ``project``: en el modal, con el avance
        y Esc, o de una vez desde un guion (al terminar, :meth:`_finished`)."""
        self._project, self._name = project, name
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, steps)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        calculated = _drain(self, steps)
        if calculated is None:
            return {"CANCELLED"}
        return self._finished(context, calculated)

    def _finished(self, context: Any, opened: Calculation) -> set[str]:
        """Lo deja abierto y sin registrar, enseña su resumen (en el informe y en la vista) y, desde
        la interfaz, pide confirmar. Devuelve cómo acaba la orden."""
        hold_calculation(opened)
        des_panels.show_summary(opened)
        shown = des_panels.view()
        for line in () if shown is None else shown.summary:
            self._report({"WARNING" if line.alert else "INFO"}, line.name)
        if self.in_steps and getattr(context, "window", None) is not None:
            _ask_confirmation(context, idname=self.COMMAND)
        return {"FINISHED"}

    def _create(self, context: Any) -> set[str]:
        """«Crear»: registra el cálculo abierto en una transacción (``Calculation.create``: la
        operación, sus salidas y sus cifras); si falla, no queda nada."""
        opened = calculation()
        if opened is None:
            self.report({"ERROR"}, tr("There is no open calculation: compute first"))
            return {"CANCELLED"}
        try:
            opened.create()
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            discard_calculation()
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, opened.op_type)  # Ctrl+Z no lo deshace
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        des_panels.show_summary(None)
        self.report({"INFO"}, self._created_text(opened))
        return {"FINISHED"}

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _cancelled_text(self) -> str:
        return tr("Calculation cancelled: nothing has been left half-done")

    def _error_text(self, exc: GeoblenderError) -> str:
        return design_error_text(exc)

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        """Con el proyecto del cálculo cerrado, en cualquier paso (también el último, que trae el
        cálculo hecho o los avisos de la cantera: :func:`_discard_late`; T48), se para sin dejar
        nada ni volver a abrir la orden, y lo dice; si no, sigue o, con el resultado, acaba
        (:meth:`_finished`)."""
        if project_session.current() is not getattr(self, "_project", None):
            _discard_late(step.result)
            return self._fail(context, tr(
                "The project was closed while the design «{name}» was being computed: nothing "
                "has been left half-done", name=getattr(self, "_name", "")))
        if step.result is None:
            return None
        self._done(context)
        return self._finished(context, step.result)

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 - los pasos cerrados no dejan nada a medias
            LOGGER.error("«%s» se ha parado", self.COMMAND, exc_info=exc)
            return self._fail(context, design_error_text(exc))

    def cancel(self, context: Any) -> None:
        """Lo que Blender llama al cancelar: un modal en curso cierra sus pasos (como Esc); la
        ventana de la confirmación cerrada sin crear descarta el cálculo abierto y sus temporales.
        El diálogo del cálculo no descarta nada."""
        if getattr(self, "_steps", None) is not None:
            _StepsModal.cancel(self, context)  # type: ignore[arg-type]
        elif self.confirm:
            discard_calculation()


# --- Límite desde el perímetro… (spec 014, T20; HU-014-1; RF-014-01; plan 014 §5.3.3, §5.5) ------

CREATE_LIMIT = provenance.LIMIT_COMMAND


class GEOBLENDER_OT_des_create_limit_from_perimeter(_CalculateAndCreate, DesignCommandAware,
                                                    ProvenanceAwareOperator, _StepsModal,
                                                    bpy.types.Operator):
    """Excavation boundary of the active version: the cells its masks admit to cut and with data
    in the start surface"""

    bl_idname = CREATE_LIMIT
    bl_label = "Limit from the perimeter…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.EXCAVATION_AREA
    COMMAND = CREATE_LIMIT

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the excavation boundary, unique in the active version",
        options=_FIELD)
    surface: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Ground of the project or of the active version: its cells without data stay "
                    "out of the excavation boundary", items=des_panels.surface_items,
        options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con
    # el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué.
        Con ``confirm``, el diálogo de crear el cálculo abierto. Si no, la lista de superficies
        leída de nuevo, la propuesta (el nombre y, de partida, el terreno: T45 de la 013) y el
        diálogo del cálculo: Intro calcula."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.refresh_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.bl_idname)].label),
            confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """El nombre («Recinto excavable») y la superficie de partida que propone el diálogo si
        quien lo lanza no los dio: el terreno (``surface_proposal.ground_item``: el MDT o el TIN
        seleccionado, la partida de una superficie de diseño seleccionada o la primera de la lista
        que no es una rejilla de un diseño, tampoco un recinto)."""
        if not self.name.strip():
            self.name = tr("Excavation boundary")
        if des_panels.has_surfaces() and not self.properties.is_property_set("surface"):
            items = [identifier for identifier, _name, _about
                     in des_panels.surface_items(None, None)]
            self.surface = surface_proposal.ground_item(context, project, items,
                                                        des_panels.surface_choice)

    def draw(self, context: Any) -> None:
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "surface", text=tr("Start surface"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido
        (sin escribir nada si falta algo), pasa por la puerta de la 008 y calcula el recinto por
        pasos con ``design.steps.excavation_area_run`` —compila las máscaras antes si no están al
        día—, sin registrar nada: desde la interfaz, en el modal con el avance y Esc; desde un guion,
        de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los
        rechazos (un recinto vacío con lo que lo vacía, la superficie, el nombre repetido) son los
        de ``design``."""
        if self.confirm:
            return self._create(context)
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        name = self.name.strip()
        if not name:
            self.report({"ERROR"}, tr("Write the name of the excavation boundary"))
            return {"CANCELLED"}
        if self.surface in ("", des_panels.NO_ZONE):
            self.report({"ERROR"}, tr("Choose the start surface of the excavation boundary"))
            return {"CANCELLED"}
        project = SESSION.project
        version = scene_versions.active_version() or ""
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.excavation_area_run(project, name, self.surface, version=version,
                                                 budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, name, steps)

    def _created_text(self, opened: Calculation) -> str:
        return tr("Excavation boundary «{name}» created in {version}", name=opened.name,
                  version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando el recinto excavable… 40 % · Esc:
        cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Computing the excavation boundary… {percent} % · Esc: cancel", percent=percent)


# --- Cantera con dos superficies… (spec 014, T21; HU-014-3; RF-014-12, RF-014-13, RF-014-29,
#     RF-014-30; plan 014 §5.3.3, §5.5) -------------------------------------------------------------

DESIGN_QUARRY = provenance.QUARRY_COMMAND
CROWN_SEEDS = "CROWN"
QUARRY_SEEDS_ITEMS = [(CROWN_SEEDS, "Crown and zones to hold", ""), *SEEDS_FROM_ITEMS]
"""De dónde salen las semillas de una superficie de la cantera: la coronación del recinto y las
zonas a sostener (RF-014-02) o las de la 013 (``design.model.SeedKind``)."""
ORDER_ITEMS = [("FINAL_FIRST", "Final surface first", ""),
               ("EXPLOITATION_FIRST", "Exploitation surface first", "")]
"""El orden del diseño (``design.model.Order``; RF-014-13, D-4: «final primero» por defecto)."""
QUARRY_ANCHOR_ITEMS = [("FIXED", "The anchor of the profile", ""),
                       ("GRID", "Grid of anchor elevations", ""),
                       ("NEAREST_FLOOR", "Floor nearest to each wall", "")]
"""El ancla de una superficie (``design.model.AnchorMode``; RF-014-11)."""
CORRIDOR_LEVEL_ITEMS = [("FIXED", "Fixed elevation", ""), ("GRADIENT", "Gradient", "")]
"""La cota de los corredores: fija o una rasante (cota inicial y pendiente; RF-014-09). La
pendiente de la rasante es «gradient» en el código y en inglés (glosario §14; T60)."""
TO_FINAL_ITEMS = [("NONE", "No", ""), ("WARNED", "All the warned zones", ""),
                  ("LAYER", "Zones of a layer", "")]
"""Dónde se aplica «explotación hasta la final» (``design.model.ToFinalMode``; P-2)."""
QUARRY_SIDES = (design_model.Surface.FINAL, design_model.Surface.EXPLOITATION)
"""Las dos superficies, en el orden de sus cajas: el prefijo de sus propiedades es su valor."""
FLOOR_FIELD, WIDTH_FIELD, LEVEL_FIELD = "cota", "ancho", "cota"
START_LEVEL_FIELD, GRADIENT_FIELD, WATER_FIELD = "cota_inicial", "pendiente", "cota"
"""Los campos que propone el diálogo (los de plan 014 §5.2.1); la persona escribe los suyos."""


def _side_title(surface: design_model.Surface) -> str:
    """El nombre de una superficie de la cantera, en el idioma de Geoblender."""
    if surface is design_model.Surface.FINAL:
        return tr("Final surface")
    return tr("Exploitation surface")


_QUARRY_HIDDEN = frozenset({"confirm", "in_steps", "confirm_outside", "outside", "preview"})
"""Las propiedades ocultas de «Cantera con dos superficies…»: las pone quien la lanza."""


def _quarry_fields() -> tuple[str, ...]:
    """Los campos del diálogo de «Cantera con dos superficies…»: sus propiedades no ocultas."""
    return tuple(name for name in GEOBLENDER_OT_des_design_quarry.__annotations__
                 if name not in _QUARRY_HIDDEN)


def _draw_preview_button(layout: Any, operator: Any) -> None:
    """El botón «Vista previa» del diálogo de la cantera (T44; RF-014-04): la misma orden con
    ``preview`` y todo lo pedido en el diálogo (cada campo, tal como está), que se ejecuta sin
    abrir otro diálogo. Un valor que su lista ya no ofrece se queda en el de por defecto (y lo
    rechaza la orden si falta)."""
    row = layout.row()
    row.operator_context = "EXEC_DEFAULT"
    shown = row.operator(DESIGN_QUARRY, text=tr("Preview"), icon="HIDE_OFF")
    for name in _quarry_fields():
        try:
            setattr(shown, name, getattr(operator, name))
        except (TypeError, ValueError):
            LOGGER.debug("El campo %s no pasa a la vista previa de la cantera", name,
                         exc_info=True)
    shown.preview = True


def _draw_outside(layout: Any, outside: str) -> None:
    """Los avisos de las semillas fuera de la coronación y de las zonas a sostener (``outside``:
    ``[[código, valores], …]`` en JSON, los de ``design.steps.quarry_run``; RF-014-03) en el
    diálogo que pide confirmarlas: por lado, el nombre de su superficie y su aviso, en ámbar, y
    después cada grupo con sus celdas, su área y su centro; cada texto, partido al ancho."""
    from ...design.preview import Notice  # al usarlo: habilitar no carga el cálculo

    width = labels.dialog_width(DIALOG_WIDTH)
    language = i18n.language()
    for code, values in json.loads(outside):
        notice = Notice(code, values)
        warning = notice.severity == "warning"
        if warning and "surface" in values:
            layout.label(text=_side_title(design_model.Surface(values["surface"])),
                         translate=False)
        column = layout.column(align=True)
        column.alert = warning
        labels.draw_wrapped(column, notice.text(language), width,
                            icon="ERROR" if warning else "NONE")


def _chosen(layer: str) -> bool:
    """Si se eligió una capa en el diálogo de la cantera (no «ninguna»)."""
    return layer not in ("", des_panels.NO_LAYER)


def _field(typed: str, what: str, layer: str) -> str:
    """El nombre de un campo de la capa ``layer`` tal como se escribió (sin espacios a los
    lados); :class:`ComputeFormError` si está vacío. Si la capa no lo tiene, lo dice el dominio al
    calcular (``des.quarry_layer_field``, con los campos que tiene)."""
    found = typed.strip()
    if not found:
        raise ComputeFormError(tr("Write the name of the field «{field}» of the layer «{layer}»",
                                  field=what, layer=constraint_panels.layer_label(layer)))
    return found


class GEOBLENDER_OT_des_design_quarry(_CalculateAndCreate, DesignCommandAware,
                                      ProvenanceAwareOperator, _StepsModal, bpy.types.Operator):
    """Exploitation surface and final surface of the quarry, tied by the order of the design and
    classified"""

    bl_idname = DESIGN_QUARRY
    bl_label = "Quarry with two surfaces…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.QUARRY
    COMMAND = DESIGN_QUARRY

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the quarry, unique in the active version",
        options=_FIELD)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Ground of the project or of the active version the two surfaces start from",
        items=des_panels.surface_items, options=_FIELD)
    order: EnumProperty(  # type: ignore[valid-type]
        name="Order of the design",
        description="Final surface first: the final surface is computed first and the "
                    "exploitation surface is raised where it is under it; exploitation surface "
                    "first: the exploitation surface is computed first and the final surface is "
                    "lowered where it is over it",
        items=ORDER_ITEMS, default="FINAL_FIRST", options=_FIELD)
    # La superficie final (su caja).
    final_seeds: EnumProperty(  # type: ignore[valid-type]
        name="Seeds of the final surface",
        description="Where the seeds of the final surface come from: the crown of the excavation "
                    "boundary and the zones to hold, or the seeds of a surface, a fixed elevation "
                    "or a grid of elevations",
        items=QUARRY_SEEDS_ITEMS, default=CROWN_SEEDS, options=_FIELD)
    final_surface: EnumProperty(  # type: ignore[valid-type]
        name="Surface of the seeds of the final surface",
        description="Surface or grid of elevations of the project or of the active version the "
                    "seeds of the final surface are read from",
        items=des_panels.surface_items, options=_FIELD)
    final_zone: EnumProperty(  # type: ignore[valid-type]
        name="Zone of the seeds of the final surface",
        description="Cells where the seeds of the final surface are: the whole surface, the "
                    "default domain, the zone of a constraint, a design sector or a layer of "
                    "polygons", items=des_panels.zone_items, options=_FIELD)
    final_elevation: StringProperty(  # type: ignore[valid-type]
        name="Elevation of the seeds of the final surface (m)",
        description="Fixed elevation of the seeds of the final surface in metres", options=_FIELD)
    final_profile: StringProperty(  # type: ignore[valid-type]
        name="Base profile of the final surface",
        description="Bench profile of the final surface in the cells without a sector (and in "
                    "the sectors without their own)", options=_FIELD)
    final_anchor: EnumProperty(  # type: ignore[valid-type]
        name="Anchor of the final surface",
        description="Elevation the benches of the final surface are anchored to: that of each "
                    "profile, a grid of anchor elevations or the floor nearest to each wall",
        items=QUARRY_ANCHOR_ITEMS, default="FIXED", options=_FIELD)
    final_anchor_grid: EnumProperty(  # type: ignore[valid-type]
        name="Grid of anchor elevations of the final surface",
        description="Grid of anchor elevations of the project or of the active version of the "
                    "final surface", items=des_panels.surface_items, options=_FIELD)
    final_metric: EnumProperty(  # type: ignore[valid-type]
        name="Distance metric of the final surface",
        description="How the distance to the seeds of the final surface is measured: the 5×5 "
                    "chamfer, the only one with the slope of each sector",
        items=QUARRY_METRIC_ITEMS, default="CHAMFER5", options=_FIELD)
    # La superficie de explotación (su caja).
    exploitation_seeds: EnumProperty(  # type: ignore[valid-type]
        name="Seeds of the exploitation surface",
        description="Where the seeds of the exploitation surface come from: the crown of the "
                    "excavation boundary and the zones to hold, or the seeds of a surface, a fixed "
                    "elevation or a grid of elevations",
        items=QUARRY_SEEDS_ITEMS, default=CROWN_SEEDS, options=_FIELD)
    exploitation_surface: EnumProperty(  # type: ignore[valid-type]
        name="Surface of the seeds of the exploitation surface",
        description="Surface or grid of elevations of the project or of the active version the "
                    "seeds of the exploitation surface are read from",
        items=des_panels.surface_items, options=_FIELD)
    exploitation_zone: EnumProperty(  # type: ignore[valid-type]
        name="Zone of the seeds of the exploitation surface",
        description="Cells where the seeds of the exploitation surface are: the whole surface, "
                    "the default domain, the zone of a constraint, a design sector or a layer of "
                    "polygons", items=des_panels.zone_items, options=_FIELD)
    exploitation_elevation: StringProperty(  # type: ignore[valid-type]
        name="Elevation of the seeds of the exploitation surface (m)",
        description="Fixed elevation of the seeds of the exploitation surface in metres",
        options=_FIELD)
    exploitation_profile: StringProperty(  # type: ignore[valid-type]
        name="Base profile of the exploitation surface",
        description="Bench profile of the exploitation surface in the cells without a sector "
                    "(and in the sectors without their own)", options=_FIELD)
    exploitation_anchor: EnumProperty(  # type: ignore[valid-type]
        name="Anchor of the exploitation surface",
        description="Elevation the benches of the exploitation surface are anchored to: that of "
                    "each profile, a grid of anchor elevations or the floor nearest to each wall",
        items=QUARRY_ANCHOR_ITEMS, default="FIXED", options=_FIELD)
    exploitation_anchor_grid: EnumProperty(  # type: ignore[valid-type]
        name="Grid of anchor elevations of the exploitation surface",
        description="Grid of anchor elevations of the project or of the active version of the "
                    "exploitation surface", items=des_panels.surface_items, options=_FIELD)
    exploitation_metric: EnumProperty(  # type: ignore[valid-type]
        name="Distance metric of the exploitation surface",
        description="How the distance to the seeds of the exploitation surface is measured: the "
                    "5×5 chamfer, the only one with the slope of each sector",
        items=QUARRY_METRIC_ITEMS, default="CHAMFER5", options=_FIELD)
    # Las capas (plan 014 §5.2.1) y «explotación hasta la final».
    floors_layer: EnumProperty(  # type: ignore[valid-type]
        name="Floors",
        description="Layer of polygons of the project with the floor elevation of each polygon "
                    "(none: no floors)", items=des_panels.optional_layer_items, options=_FIELD)
    floors_field: StringProperty(  # type: ignore[valid-type]
        name="Floor elevation field",
        description="Numeric field of the layer of floors with the elevation of each floor in "
                    "metres", default=FLOOR_FIELD, options=_FIELD)
    conserve: EnumProperty(  # type: ignore[valid-type]
        name="Zone to conserve",
        description="Constraint or layer of polygons the design neither excavates nor buries, "
                    "with its conservation ceiling (none: no zone to conserve)",
        items=des_panels.conserve_items, options=_FIELD)
    corridors_layer: EnumProperty(  # type: ignore[valid-type]
        name="Corridors",
        description="Layer of lines of the project with the axis of each corridor, a floor with "
                    "flat ends (none: no corridors)", items=des_panels.line_layer_items,
        options=_FIELD)
    corridors_width_field: StringProperty(  # type: ignore[valid-type]
        name="Width field",
        description="Numeric field of the layer of corridors with the width of each corridor in "
                    "metres", default=WIDTH_FIELD, options=_FIELD)
    corridors_level: EnumProperty(  # type: ignore[valid-type]
        name="Elevation of the corridors",
        description="A fixed elevation or a gradient: the elevation at the start of the axis and "
                    "its slope in %", items=CORRIDOR_LEVEL_ITEMS, default="FIXED", options=_FIELD)
    corridors_level_field: StringProperty(  # type: ignore[valid-type]
        name="Corridor elevation field",
        description="Numeric field of the layer of corridors with the fixed elevation of each "
                    "corridor in metres", default=LEVEL_FIELD, options=_FIELD)
    corridors_start_field: StringProperty(  # type: ignore[valid-type]
        name="Start elevation field",
        description="Numeric field of the layer of corridors with the elevation at the start of "
                    "each axis in metres", default=START_LEVEL_FIELD, options=_FIELD)
    corridors_gradient_field: StringProperty(  # type: ignore[valid-type]
        name="Gradient field",
        description="Numeric field of the layer of corridors with the gradient of each corridor "
                    "in %, positive when it rises along the axis", default=GRADIENT_FIELD,
        options=_FIELD)
    fill_layer: EnumProperty(  # type: ignore[valid-type]
        name="Restoration fill zones",
        description="Layer of polygons where the difference between the two surfaces is covered "
                    "by a fill (none: no fill zones)", items=des_panels.optional_layer_items,
        options=_FIELD)
    water_layer: EnumProperty(  # type: ignore[valid-type]
        name="Water sheets",
        description="Layer of polygons with the elevation of each water sheet (none: no water "
                    "sheets)", items=des_panels.optional_layer_items, options=_FIELD)
    water_field: StringProperty(  # type: ignore[valid-type]
        name="Water elevation field",
        description="Numeric field of the layer of water sheets with the elevation of each sheet "
                    "in metres", default=WATER_FIELD, options=_FIELD)
    to_final: EnumProperty(  # type: ignore[valid-type]
        name="Exploitation down to the final surface",
        description="Where the exploitation surface is lowered down to the final surface with its "
                    "benches: nowhere, in every warned zone or in the zones of a layer of polygons",
        items=TO_FINAL_ITEMS, default="NONE", options=_FIELD)
    to_final_layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of zones",
        description="Layer of polygons with the zones where the exploitation surface is lowered "
                    "down to the final surface", items=des_panels.layer_items, options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con
    # el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    # Las semillas de la 013 fuera de la coronación y de las zonas a sostener (T43; RF-014-03): la
    # confirmación de calcular con ellas (el botón «Calcular con ellas» del diálogo que las enseña
    # o, desde un guion, quien la lanza) y lo que enseña ese diálogo (sus avisos, en JSON).
    confirm_outside: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    outside: StringProperty(default="", options=_HIDDEN)  # type: ignore[valid-type]
    # La vista previa de lo pedido (T44; RF-014-04): la pone el botón «Vista previa» del diálogo.
    preview: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué.
        Con ``confirm``, el diálogo de crear el cálculo abierto; con ``outside``, el que pide
        confirmar las semillas fuera de la coronación antes de calcular con ellas (RF-014-03:
        «Calcular con ellas»; «Cancelar» y cerrarlo no calculan nada). Si no, las listas de
        superficies, zonas, capas, perfiles y sectores leídas de nuevo, la propuesta (el nombre y,
        de partida, el terreno: T45 de la 013) y el diálogo del cálculo: Intro calcula."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        if self.outside:  # lo pedido, tal cual, con la confirmación de las semillas puesta
            return context.window_manager.invoke_props_dialog(
                self, width=DIALOG_WIDTH, translate=False,
                title=tr("Quarry «{name}»: seeds outside the crown and the zones to hold",
                         name=self.name.strip()),
                confirm_text=tr("Calculate with them"))
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.fill_profiles(project)
            des_panels.fill_sectors(project)
            des_panels.refresh_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label),
            confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """El nombre («Cantera») y la superficie de partida que propone el diálogo si quien lo
        lanza no los dio: el terreno (``surface_proposal.ground_item``, como «Límite desde el
        perímetro…»). Los perfiles no se proponen: los elige la persona."""
        if not self.name.strip():
            self.name = tr("Quarry")
        if des_panels.has_surfaces() and not self.properties.is_property_set("start"):
            items = [identifier for identifier, _name, _about
                     in des_panels.surface_items(None, None)]
            self.start = surface_proposal.ground_item(context, project, items,
                                                      des_panels.surface_choice)

    def draw(self, context: Any) -> None:
        """Arriba el nombre, la superficie de partida y el orden; una caja por superficie; abajo
        las capas con sus campos, «explotación hasta la final» (plan 014 §5.5) y el botón «Vista
        previa» (T44; RF-014-04: :func:`_draw_preview_button`). En la confirmación de crear, el
        resumen; en la de las semillas fuera, sus avisos."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        if self.outside:  # las semillas fuera de la coronación, antes de calcular (RF-014-03)
            _draw_outside(layout, self.outside)
            return
        layout.use_property_split = True
        shown = des_panels.view()
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        layout.prop(self, "order", text=tr("Order of the design"), translate=False)
        for surface in QUARRY_SIDES:
            self._draw_side(layout.box(), shown, surface)
        layers = layout.box()
        layers.label(text=tr("Layers"), translate=False)
        layers.prop(self, "floors_layer", text=tr("Floors"), translate=False)
        if self.floors_layer != des_panels.NO_LAYER:
            layers.prop(self, "floors_field", text=tr("Elevation field"), translate=False)
        layers.prop(self, "conserve", text=tr("Zone to conserve"), translate=False)
        layers.prop(self, "corridors_layer", text=tr("Corridors"), translate=False)
        if self.corridors_layer != des_panels.NO_LAYER:
            layers.prop(self, "corridors_width_field", text=tr("Width field"), translate=False)
            layers.prop(self, "corridors_level", text=tr("Elevation of the corridors"),
                        translate=False)
            if self.corridors_level == "GRADIENT":
                layers.prop(self, "corridors_start_field", text=tr("Start elevation field"),
                            translate=False)
                layers.prop(self, "corridors_gradient_field", text=tr("Gradient field"),
                            translate=False)
            else:
                layers.prop(self, "corridors_level_field", text=tr("Elevation field"),
                            translate=False)
        layers.prop(self, "fill_layer", text=tr("Restoration fill zones"), translate=False)
        layers.prop(self, "water_layer", text=tr("Water sheets"), translate=False)
        if self.water_layer != des_panels.NO_LAYER:
            layers.prop(self, "water_field", text=tr("Elevation field"), translate=False)
        layout.prop(self, "to_final", text=tr("Exploitation down to the final surface"),
                    translate=False)
        if self.to_final == "LAYER":
            layout.prop(self, "to_final_layer", text=tr("Layer of zones"), translate=False)
        _draw_preview_button(layout, self)

    def _draw_side(self, box: Any, shown: Any, surface: design_model.Surface) -> None:
        """La caja de una superficie: su título, sus semillas (la superficie o rejilla, la zona y
        la cota fija, según de dónde salen), su perfil base, el de cada sector, su ancla (con su
        rejilla) y su métrica."""
        side = surface.value
        box.label(text=_side_title(surface), translate=False)
        seeds = getattr(self, f"{side}_seeds")
        box.prop(self, f"{side}_seeds", text=tr("Origin of the seeds"), translate=False)
        if seeds in ("SURFACE", "GRID"):
            box.prop(self, f"{side}_surface", text=tr("Surface") if seeds == "SURFACE"
                     else tr("Grid of elevations"), translate=False)
        if seeds in ("SURFACE", "FIXED"):
            box.prop(self, f"{side}_zone", text=tr("Zone of the seeds"), translate=False)
        if seeds == "FIXED":
            box.prop(self, f"{side}_elevation", text=tr("Elevation (m)"), translate=False)
        if shown is not None:
            box.prop_search(self, f"{side}_profile", shown, "profiles", text=tr("Base profile"),
                            translate=False)
        box.prop(self, f"{side}_anchor", text=tr("Anchor"), translate=False)
        if getattr(self, f"{side}_anchor") == "GRID":
            box.prop(self, f"{side}_anchor_grid", text=tr("Grid of anchor elevations"),
                     translate=False)
        box.prop(self, f"{side}_metric", text=tr("Metric"), translate=False)
        if shown is not None and len(shown.sectors):
            des_panels.draw_sector_rows(box, bound=False, profiles=True, pick=f"{side}_pick")

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self, project: Any) -> design_model.QuarryRequest:
        """Lo pedido en el diálogo como la ``design.model.QuarryRequest`` (RF-014-12), comprobado
        sin escribir ni calcular nada: los perfiles y los sectores se leen de nuevo (un guion no
        abre el diálogo que los lee). Las capas, sus campos, las semillas, los perfiles sin valor y
        los sectores pendientes los rechaza el dominio al calcular. :class:`ComputeFormError` si
        falta algo del diálogo."""
        des_panels.fill_profiles(project)
        des_panels.fill_sectors(project)
        shown = des_panels.view()
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the quarry"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the quarry"))
        codes = des_panels.profile_codes()
        final, exploitation = (self._side(surface, shown, codes) for surface in QUARRY_SIDES)
        floors = None
        if _chosen(self.floors_layer):
            floors = design_model.LayerField(self.floors_layer, _field(
                self.floors_field, tr("Elevation field"), self.floors_layer))
        conserve = ()
        if self.conserve not in ("", des_panels.NO_ZONE):
            conserve = (_zone_of(self.conserve),)
        corridors = None
        if _chosen(self.corridors_layer):
            layer = self.corridors_layer
            width = _field(self.corridors_width_field, tr("Width field"), layer)
            if self.corridors_level == "GRADIENT":
                corridors = design_model.CorridorFields(
                    layer, width,
                    start_level_field=_field(self.corridors_start_field,
                                             tr("Start elevation field"), layer),
                    gradient_field=_field(self.corridors_gradient_field, tr("Gradient field"),
                                          layer))
            else:
                corridors = design_model.CorridorFields(layer, width, level_field=_field(
                    self.corridors_level_field, tr("Elevation field"), layer))
        water = None
        if _chosen(self.water_layer):
            water = design_model.LayerField(self.water_layer, _field(
                self.water_field, tr("Elevation field"), self.water_layer))
        to_final = design_model.ToFinalMode(self.to_final.lower())
        to_final_layer = None
        if to_final is design_model.ToFinalMode.LAYER:
            if not _chosen(self.to_final_layer):
                raise ComputeFormError(tr("Choose the layer of «{what}»",
                                          what=tr("Exploitation down to the final surface")))
            to_final_layer = self.to_final_layer
        return design_model.QuarryRequest(
            name, self.start, final, exploitation, order=self.order.lower(), floors=floors,
            conserve=conserve, corridors=corridors,
            fill_zones=self.fill_layer if _chosen(self.fill_layer) else None, water=water,
            to_final=to_final, to_final_layer=to_final_layer)

    def _side(self, surface: design_model.Surface, shown: Any, codes: Mapping[str, str]
              ) -> design_model.QuarrySide:
        """Lo pedido de una superficie (``design.model.QuarrySide``): el perfil base y el de cada
        sector (por su nombre), las semillas («coronación y zonas a sostener» o las de la 013), el
        ancla con su rejilla y la métrica."""
        side, title = surface.value, _side_title(surface)
        pick = GEOBLENDER_OT_des_compute_envelope._profile_code
        base = pick(getattr(self, f"{side}_profile"), tr("Base profile"), codes)
        if base is None:
            raise ComputeFormError(tr("Choose the base profile of «{surface}»", surface=title))
        assigned: dict[str, str] = {}
        for item in () if shown is None else shown.sectors:
            found = pick(getattr(item, f"{side}_pick"), item.name, codes)
            if found is not None:
                assigned[item.code] = found
        seeds_from = getattr(self, f"{side}_seeds")
        seeds = None if seeds_from == CROWN_SEEDS else seed_source(
            seeds_from, getattr(self, f"{side}_surface"), getattr(self, f"{side}_zone"),
            getattr(self, f"{side}_elevation"))
        anchor = design_model.AnchorMode(getattr(self, f"{side}_anchor").lower())
        grid = None
        if anchor is design_model.AnchorMode.GRID:
            grid = getattr(self, f"{side}_anchor_grid")
            if grid in ("", des_panels.NO_ZONE):
                raise ComputeFormError(tr("Choose the grid of anchor elevations of «{surface}»",
                                          surface=title))
        return design_model.QuarrySide(base, assigned, seeds, anchor, grid,
                                       getattr(self, f"{side}_metric").lower())

    # --- Calcular -----------------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido
        (sin escribir nada si falta algo), pasa por la puerta de la 008 y calcula las dos
        superficies por pasos con ``design.steps.quarry_run`` —compila las máscaras antes si no
        están al día—, sin registrar nada (RF-014-29): desde la interfaz, en el modal con el avance
        y Esc; desde un guion, de una vez. Al terminar deja el cálculo abierto con su resumen y
        pide confirmar. Los rechazos (un sector del recinto sin búsqueda vigente, RF-014-30; las
        capas, los perfiles, el recinto vacío, el nombre repetido) son los de ``design``. Si las
        semillas de la 013 de un lado caen fuera de la coronación y de las zonas a sostener, sin
        ``confirm_outside`` no calcula nada (RF-014-03, :meth:`_finished`). Con ``preview``, la
        vista previa de lo pedido (:meth:`_show_preview`)."""
        if self.confirm:
            return self._create(context)
        if self.preview:
            return self._show_preview()
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        version = scene_versions.active_version() or ""
        try:
            request = self._request(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.quarry_run(project, request, version=version,
                                        budget_s=self.STEP_BUDGET_S,
                                        confirm_outside=self.confirm_outside)
        return self._run_steps(context, project, request.name, steps)

    def _show_preview(self) -> set[str]:
        """«Vista previa» (T44; RF-014-04): comprueba lo pedido como al calcular (:meth:`_request`,
        sin escribir ni calcular nada) y activa con ello la vista previa de la 013
        (``bl.draw.design``, un ``QuarryPlan``: el recinto, la coronación, las zonas a sostener, los
        fondos, los techos y los corredores con su leyenda); la que hubiera activa se quita antes
        (pulsarlo otra vez la cambia por la nueva). Lo que falta del diálogo se rechaza sin tocar la
        vista previa. Se quita como la de la 013: su control, conmutar, cerrar el proyecto."""
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            request = self._request(SESSION.project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        preview = _preview()
        preview.disable()
        try:
            preview.enable(preview.QuarryPlan(request))
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr(
                "The preview of seeds, domains and constraints could not be shown: {detail}",
                detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of the quarry «{name}»", name=request.name))
        return {"FINISHED"}

    def _finished(self, context: Any, opened: Calculation | tuple[Any, ...]) -> set[str]:
        """El cálculo abierto, como en las demás órdenes; o, si ``quarry_run`` se paró antes de
        calcular por las semillas de la 013 fuera de la coronación y de las zonas a sostener (sus
        avisos, ``preview.Notice``; RF-014-03, error 10), nada calculado: sus avisos en el informe
        y, desde la interfaz, la misma orden con lo pedido otra vez, la confirmación de las
        semillas puesta y el diálogo que las enseña («Calcular con ellas»); desde un guion, el
        error que lo dice (hace falta ``confirm_outside``)."""
        if not isinstance(opened, tuple):
            return super()._finished(context, opened)
        language = i18n.language()
        for notice in opened:
            self._report({"WARNING" if notice.severity == "warning" else "INFO"},
                         notice.text(language))
        window = getattr(context, "window", None)
        if self.in_steps and window is not None:
            asked = {name: getattr(self, name) for name in type(self).__annotations__
                     if name not in _QUARRY_HIDDEN and self.properties.is_property_set(name)}
            _invoke_later(self.COMMAND, window, **asked, confirm_outside=True,
                          outside=json.dumps([[notice.code, dict(notice.values)]
                                              for notice in opened], ensure_ascii=False))
            return {"FINISHED"}
        self._report({"ERROR"}, tr(
            "Nothing has been computed in «{name}»: confirm the seeds outside the crown and the "
            "zones to hold to compute with them (from a script, with confirm_outside=True)",
            name=getattr(self, "_name", "")))
        return {"CANCELLED"}

    def _created_text(self, opened: Calculation) -> str:
        return tr("Quarry «{name}» created in {version}", name=opened.name,
                  version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando la cantera… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Computing the quarry… {percent} % · Esc: cancel", percent=percent)


# --- Transiciones con el terreno no afectado (spec 014, T28; HU-014-5; RF-014-19 a RF-014-21,
#     RF-014-29; plan 014 §5.3.3, §5.5) ------------------------------------------------------------

CREATE_TRANSITIONS = provenance.TRANSITIONS_COMMAND


def _design_surface_start(project: Any, surface: str) -> str | None:
    """La superficie de partida de la ficha de la superficie de diseño ``surface`` de la versión
    activa (``design.store.design_surface_of``) si el diálogo la ofrece; ``None`` si no la hay, no
    está en la lista o no se pudo leer (queda en el registro técnico). Solo lee."""
    from ...design import store as design_store  # al usarlo: habilitar no lo carga

    version = scene_versions.active_version() or ""
    try:
        with project.read() as conn:
            origin = design_store.design_surface_of(conn, surface, version)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.info("No se pudo leer la superficie de partida de «%s»", surface, exc_info=True)
        return None
    start = None if origin is None else origin.start
    listed = {identifier for identifier, _name, _about in des_panels.surface_items(None, None)}
    return start if start in listed and start != surface else None


class GEOBLENDER_OT_des_create_transitions(_CalculateAndCreate, DesignCommandAware,
                                           ProvenanceAwareOperator, _StepsModal,
                                           bpy.types.Operator):
    """Join a design surface with the untouched terrain at the edge of what it moves, with a slope
    no steeper than the transition angle, and measure the created step"""

    bl_idname = CREATE_TRANSITIONS
    bl_label = "Transitions with the untouched terrain…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.EDGE_TRANSITION
    COMMAND = CREATE_TRANSITIONS

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the transition, unique in the active version",
        options=_FIELD)
    surface: EnumProperty(  # type: ignore[valid-type]
        name="Design surface",
        description="Design surface of the active version that is joined with the untouched "
                    "terrain at the edge of what it moves",
        items=des_panels.design_surface_items, options=_FIELD)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the design starts from: the untouched terrain is the one the design "
                    "does not move", items=des_panels.surface_items, options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con
    # el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué.
        Con ``confirm``, el diálogo de crear el cálculo abierto. Si no, las listas de superficies
        leídas de nuevo, la propuesta (el nombre, la superficie de diseño seleccionada y su
        partida) y el diálogo del cálculo: Intro calcula."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.refresh_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label),
            confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 014 §5.3.3, como la T45 de
        la 013): el nombre («Transición»); **la superficie de diseño seleccionada** en la vista (el
        objeto ``DESIGN`` de una de la lista; sin ninguna, la primera de la lista) y, de partida, la
        de su ficha (``design.store.design_surface_of``) o, si no la tiene, el terreno
        (``surface_proposal.ground_item``)."""
        if not self.name.strip():
            self.name = tr("Transition")
        given = self.properties.is_property_set
        designs = [identifier for identifier, _name, _about
                   in des_panels.design_surface_items(None, None)
                   if identifier != des_panels.NO_ZONE]
        if designs and not given("surface"):
            by_uid = {choice.uid: identifier for identifier in designs
                      if (choice := des_panels.surface_choice(identifier)) is not None}
            chosen = [by_uid[str(marks.dataset_uid)]
                      for obj in getattr(context, "selected_objects", None) or ()
                      if (marks := getattr(obj, OBJECT_PROPERTY, None)) is not None
                      and marks.kind == des_views.KIND and str(marks.dataset_uid) in by_uid]
            self.surface = chosen[0] if chosen else designs[0]
        if des_panels.has_surfaces() and not given("start"):
            start = (_design_surface_start(project, self.surface)
                     if self.surface in designs else None)
            if start is None:
                items = [identifier for identifier, _name, _about
                         in des_panels.surface_items(None, None)]
                start = surface_proposal.ground_item(context, project, items,
                                                     des_panels.surface_choice)
            if start is not None:
                self.start = start

    def draw(self, context: Any) -> None:
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "surface", text=tr("Design surface"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido
        (sin escribir nada si falta algo), pasa por la puerta de la 008 y calcula la transición por
        pasos con ``design.steps.edge_transition_run`` —compila las máscaras antes si no están al
        día—, sin registrar nada (RF-014-29): desde la interfaz, en el modal con el avance y Esc;
        desde un guion, de una vez. Al terminar deja el cálculo abierto con su resumen y pide
        confirmar. Los rechazos (una superficie que no es de diseño, el ángulo de transición sin
        valor, el nombre repetido) y todas las cuentas son de ``design``."""
        if self.confirm:
            return self._create(context)
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        name = self.name.strip()
        if not name:
            self.report({"ERROR"}, tr("Write the name of the transition"))
            return {"CANCELLED"}
        if self.surface in ("", des_panels.NO_ZONE):
            self.report({"ERROR"}, tr("Choose the design surface of the transition"))
            return {"CANCELLED"}
        if self.start in ("", des_panels.NO_ZONE):
            self.report({"ERROR"}, tr("Choose the start surface of the transition"))
            return {"CANCELLED"}
        project = SESSION.project
        version = scene_versions.active_version() or ""
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.edge_transition_run(project, name, self.surface, self.start,
                                                 version=version, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, name, steps)

    def _created_text(self, opened: Calculation) -> str:
        return tr("Transition «{name}» created in {version}", name=opened.name,
                  version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando la transición… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Computing the transition… {percent} % · Esc: cancel", percent=percent)


# --- Solo relleno… (spec 014, T30; HU-014-6; RF-014-22 a RF-014-25, RF-014-29; plan 014 §5.3.3,
#     §5.5) ---------------------------------------------------------------------------------------

DESIGN_FILL_ONLY = provenance.FILL_ONLY_COMMAND


class GEOBLENDER_OT_des_design_fill_only(_CalculateAndCreate, DesignCommandAware,
                                         ProvenanceAwareOperator, _StepsModal,
                                         bpy.types.Operator):
    """Bench an envelope of the active version in fill without cutting: the toe stays in the
    admitted fill and the water sheets are the start surface"""

    bl_idname = DESIGN_FILL_ONLY
    bl_label = "Fill only…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.FILL_ONLY
    COMMAND = DESIGN_FILL_ONLY

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the fill-only design, unique in the active version",
        options=_FIELD)
    envelope: EnumProperty(  # type: ignore[valid-type]
        name="Envelope",
        description="Envelope of the active version that is benched in fill: the design only "
                    "fills", items=des_panels.envelope_items, options=_FIELD)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the benching starts from: the ground the design is composed with",
        items=des_panels.surface_items, options=_FIELD)
    anchor: EnumProperty(  # type: ignore[valid-type]
        name="Anchor",
        description="Elevation the benches are anchored to: that of each profile or a grid of "
                    "anchors of the project or of the active version",
        items=des_panels.anchor_items, options=_FIELD)
    base_profile: StringProperty(  # type: ignore[valid-type]
        name="Base profile",
        description="Bench profile of the cells without a sector (and of the sectors without "
                    "their own)", options=_FIELD)
    water_layer: EnumProperty(  # type: ignore[valid-type]
        name="Water sheets",
        description="Layer of polygons with the elevation of each water sheet (none: no water "
                    "sheets)", items=des_panels.optional_layer_items, options=_FIELD)
    water_field: StringProperty(  # type: ignore[valid-type]
        name="Water elevation field",
        description="Numeric field of the layer of water sheets with the elevation of each sheet "
                    "in metres", default=WATER_FIELD, options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con
    # el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué.
        Con ``confirm``, el diálogo de crear el cálculo abierto. Si no, las listas de envolventes,
        superficies, anclas, capas, perfiles y sectores leídas de nuevo, la propuesta (el nombre,
        la envolvente, el terreno y el campo de la cota) y el diálogo del cálculo: Intro calcula."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.fill_profiles(project)
            des_panels.fill_sectors(project)
            des_panels.refresh_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label),
            confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 014 §5.3.3, como la T45 de
        la 013): el nombre («Solo relleno»), la primera envolvente de la versión, de partida el
        terreno (``surface_proposal.ground_item``: el MDT o el TIN seleccionado, la partida de una
        superficie de diseño seleccionada o la primera de la lista que no es una rejilla de un
        diseño) y el campo de la cota de las láminas («cota», plan 014 §5.2.1). Los perfiles no se
        proponen: los elige la persona."""
        given = self.properties.is_property_set
        if not self.name.strip():
            self.name = tr("Fill only")
        envelopes = [identifier for identifier, _name, _about
                     in des_panels.envelope_items(None, None) if identifier != des_panels.NO_ZONE]
        if envelopes and not given("envelope"):
            self.envelope = envelopes[0]
        if des_panels.has_surfaces() and not given("start"):
            items = [identifier for identifier, _name, _about
                     in des_panels.surface_items(None, None)]
            self.start = surface_proposal.ground_item(context, project, items,
                                                      des_panels.surface_choice)
        if not given("water_field") and not self.water_field.strip():
            self.water_field = WATER_FIELD

    def draw(self, context: Any) -> None:
        """Lo del escalonado en relleno de la 013 (el nombre, la envolvente, la superficie de
        partida, el ancla, el perfil base y el de cada sector) y la capa de láminas con su campo
        (plan 014 §5.3.3)."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        shown = des_panels.view()
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "envelope", text=tr("Envelope"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        layout.prop(self, "anchor", text=tr("Anchor"), translate=False)
        if shown is not None:
            layout.prop_search(self, "base_profile", shown, "profiles", text=tr("Base profile"),
                               translate=False)
            if len(shown.sectors):
                box = layout.box()
                box.label(text=tr("Sectors"), translate=False)
                des_panels.draw_sector_rows(box, bound=False, profiles=True)
        layout.prop(self, "water_layer", text=tr("Water sheets"), translate=False)
        if self.water_layer != des_panels.NO_LAYER:
            layout.prop(self, "water_field", text=tr("Elevation field"), translate=False)

    def _request(self, project: Any) -> design_model.FillOnlyRequest:
        """Lo pedido en el diálogo como la ``design.model.FillOnlyRequest`` (RF-014-22, RF-014-24),
        comprobado sin escribir ni calcular nada: los perfiles y los sectores se leen de nuevo (un
        guion no abre el diálogo que los lee). La envolvente, las superficies, la capa y su campo,
        los perfiles sin valor y los sectores pendientes los rechaza el dominio al calcular.
        :class:`ComputeFormError` si falta algo del diálogo."""
        des_panels.fill_profiles(project)
        des_panels.fill_sectors(project)
        shown = des_panels.view()
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the fill-only design"))
        if self.envelope in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the envelope of the fill-only design"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the fill-only design"))
        codes = des_panels.profile_codes()
        pick = GEOBLENDER_OT_des_compute_envelope._profile_code
        base = pick(self.base_profile, tr("Base profile"), codes)
        if base is None:
            raise ComputeFormError(tr("Choose the base profile of the fill-only design"))
        assigned: dict[str, str] = {}
        for item in () if shown is None else shown.sectors:
            found = pick(item.profile_pick, item.name, codes)
            if found is not None:
                assigned[item.code] = found
        water = None
        if _chosen(self.water_layer):
            water = design_model.LayerField(self.water_layer, _field(
                self.water_field, tr("Elevation field"), self.water_layer))
        anchor = None if self.anchor in ("", des_panels.NO_ANCHOR) else self.anchor
        return design_model.FillOnlyRequest(name, self.envelope, self.start, base, assigned,
                                            anchor, water)

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido
        (sin escribir nada si falta algo), pasa por la puerta de la 008 y calcula el diseño por
        pasos con ``design.steps.fill_only_run`` —compila las máscaras antes si no están al día—,
        sin registrar nada (RF-014-29): desde la interfaz, en el modal con el avance y Esc; desde un
        guion, de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar.
        Los rechazos (un intocable movido o un corte, RF-014-25; las láminas; un sector pendiente;
        un perfil sin valor; el nombre repetido) y todas las cuentas son de ``design``."""
        if self.confirm:
            return self._create(context)
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        version = scene_versions.active_version() or ""
        try:
            request = self._request(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        des_panels.assign_profiles(project, dict(request.sector_profiles))  # RF-013-21, en la vista
        steps = design_steps.fill_only_run(project, request, version=version,
                                           budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _created_text(self, opened: Calculation) -> str:
        return tr("Fill-only design «{name}» created in {version}", name=opened.name,
                  version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando el diseño «solo relleno»… 40 % · Esc:
        cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Computing the fill-only design… {percent} % · Esc: cancel", percent=percent)


# --- Ajustar el diseño a un límite nuevo… (spec 014, T33; HU-014-7; RF-014-27, RF-014-28,
#     RF-014-29; plan 014 §5.3.3, §5.5, P-3) ---------------------------------------------------------

REFIT_TO_LIMIT = provenance.REFIT_COMMAND


def _fill_refit_rows(rows: Any, found: Iterator[tuple[str, str, bool]]) -> None:
    """Pone en la colección ``rows`` de la orden una fila por superficie de ``found`` (el nombre de
    su dato, lo que dice la ventana y si queda fuera del límite vigente): marcada si queda
    fuera."""
    rows.clear()
    for surface, label, outside in found:
        row = rows.add()
        row.name, row.label, row.outside, row.selected = surface, label, outside, outside


class GEOBLENDER_OT_des_refit_to_limit(_CalculateAndCreate, DesignCommandAware,
                                       ProvenanceAwareOperator, _StepsModal, bpy.types.Operator):
    """Refit design surfaces of the active version to its current limit: the untouched terrain
    outside it and, inside, the face of the own profile of each surface, without going above the
    terrain"""

    bl_idname = REFIT_TO_LIMIT
    bl_label = "Refit the design to a new limit…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.REFIT
    COMMAND = REFIT_TO_LIMIT

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the refit, unique in the active version",
        options=_FIELD)
    surfaces: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_des_refit_surface, name="Design surfaces",
        description="Design surfaces of the active version that are refitted (marked: the ones "
                    "the current limit leaves outside)", options=_FIELD)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the design starts from: outside the limit the refitted surfaces go "
                    "back to it", items=des_panels.surface_items, options=_FIELD)
    # Lo que dice la ventana si no se sabe qué queda fuera (las máscaras no están al día).
    note: StringProperty(default="", options=_HIDDEN)  # type: ignore[valid-type]
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con
    # el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué.
        Con ``confirm``, el diálogo de crear el cálculo abierto. Si no, las superficies de diseño
        de la versión leídas de nuevo (las que quedan fuera del límite vigente, marcadas: de la
        caché de la comprobación, ``des_panels.cached_refit_rows``), la propuesta (el nombre y la
        superficie de partida) y el diálogo del cálculo: Intro calcula. Sin acierto en la caché
        (spec 014, T35; RNF-014-02), desde la interfaz comprueba antes por pasos
        (:meth:`_check_first`) y la ventana se abre al terminar; desde un guion, de una vez."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        self._checking = False
        if self.confirm:
            return self._confirmation(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        version = scene_versions.active_version() or ""
        try:
            des_panels.refresh_choices(project)
            rows = None
            if not self.properties.is_property_set("surfaces"):
                rows = des_panels.cached_refit_rows(project, version)
                if rows is None and self.in_steps:
                    return self._check_first(context, project, version)
                if rows is None:  # sin ventana: de una vez
                    rows = des_panels.refit_rows(project, version)
            self._propose(context, project, rows)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label),
            confirm_text=tr("Calculate"))

    def _check_first(self, context: Any, project: Any, version: str) -> set[str]:
        """La comprobación de las superficies de la versión contra el límite vigente antes de abrir
        el diálogo (spec 014, T35; RNF-014-02): por pasos en el modal de la orden
        (``des_panels.refit_rows_steps``, que llena la caché), con el texto en la barra de estado y
        Esc, que no abre nada; al terminar, la orden se vuelve a abrir con las filas ya marcadas
        (:meth:`_result`)."""
        self._checking = True
        self._project, self._name = project, ""
        self._start(context, des_panels.refit_rows_steps(project, version))
        return {"RUNNING_MODAL"}

    def _propose(self, context: Any, project: Any,
                 rows: tuple[list[tuple[str, str, bool]], str] | None = None) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 014 §5.3.3): el nombre
        («Ajuste»); las superficies de diseño de la versión activa con **las que quedan fuera del
        límite vigente marcadas** (``rows``: las filas y la nota de ``des_panels.refit_rows``; y,
        si las máscaras no están al día, la nota que lo dice); y, de partida, la de la ficha de la
        primera marcada (o de la primera, sin ninguna marcada:
        ``design.store.design_surface_of``) o, si no la tiene, el terreno
        (``surface_proposal.ground_item``)."""
        if not self.name.strip():
            self.name = tr("Refit")
        given = self.properties.is_property_set
        if not given("surfaces"):
            found, self.note = rows if rows is not None else des_panels.refit_rows(
                project, scene_versions.active_version() or "")
            _fill_refit_rows(self.surfaces, iter(found))
        if des_panels.has_surfaces() and not given("start"):
            listed = [item.name for item in self.surfaces]
            chosen = [item.name for item in self.surfaces if item.selected] or listed
            start = next((found for surface in chosen
                          if (found := _design_surface_start(project, surface)) is not None), None)
            if start is None:
                items = [identifier for identifier, _name, _about
                         in des_panels.surface_items(None, None)]
                start = surface_proposal.ground_item(context, project, items,
                                                     des_panels.surface_choice)
            if start is not None:
                self.start = start

    def draw(self, context: Any) -> None:
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        box = layout.box()
        box.use_property_split = False
        box.label(text=tr("Design surfaces to refit"), translate=False)
        if not len(self.surfaces):
            box.label(text=tr("There are no design surfaces in the active version"),
                      translate=False)
        for item in self.surfaces:
            row = box.row()
            row.alert = bool(item.outside)
            row.prop(item, "selected", text=item.label, translate=False)
        if self.note:
            box.label(text=self.note, icon="INFO", translate=False)

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido
        (sin escribir nada si falta algo), pasa por la puerta de la 008 y calcula el ajuste de las
        superficies marcadas por pasos con ``design.steps.refit_run`` —compila las máscaras antes
        si no están al día—, sin registrar nada (RF-014-29): desde la interfaz, en el modal con el
        avance y Esc; desde un guion, de una vez. Al terminar deja el cálculo abierto con su
        resumen y pide confirmar. El ángulo de cada superficie no se pide: es la cara de su propio
        perfil (P-3). Desde un guion, cada fila de ``surfaces`` lleva todos sus campos (Blender los
        pide): ``{"name": <dato>, "label": "", "outside": False, "selected": True}``. Los rechazos
        (una superficie que no es de diseño, un perfil sin cara, el nombre repetido) y todas las
        cuentas son de ``design``."""
        if self.confirm:
            return self._create(context)
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        name = self.name.strip()
        if not name:
            self.report({"ERROR"}, tr("Write the name of the refit"))
            return {"CANCELLED"}
        chosen = tuple(dict.fromkeys(item.name for item in self.surfaces if item.selected))
        if not chosen:
            self.report({"ERROR"}, tr("Choose the design surfaces to refit: mark at least one"))
            return {"CANCELLED"}
        if self.start in ("", des_panels.NO_ZONE):
            self.report({"ERROR"}, tr("Choose the start surface of the refit"))
            return {"CANCELLED"}
        project = SESSION.project
        version = scene_versions.active_version() or ""
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        request = design_model.RefitRequest(name, chosen, self.start)
        steps = design_steps.refit_run(project, request, version=version,
                                       budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, name, steps)

    def _created_text(self, opened: Calculation) -> str:
        return tr("Refit «{name}» created in {version}", name=opened.name, version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando el ajuste… 40 % · Esc: cancelar» o, mientras
        comprueba antes de abrir el diálogo, «Comprobando las superficies de diseño contra el límite
        vigente… · Esc: cancelar»."""
        if getattr(self, "_checking", False):
            return tr("Checking the design surfaces against the current limit… · Esc: cancel")
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Computing the refit… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if getattr(self, "_checking", False):
            return tr("Check cancelled: the window has not been opened")
        return super()._cancelled_text()

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        """Mientras comprueba antes de abrir el diálogo (:meth:`_check_first`): si se cierra el
        proyecto, en cualquier paso (también el último, que trae las filas: spec 014, T54, punto 2
        de la T48), lo deja sin volver a abrir la orden y lo dice; al terminar, vuelve a abrir la
        orden con las filas ya marcadas y su nota (y el nombre y la partida si se dieron). Si no,
        el del cálculo."""
        if not getattr(self, "_checking", False):
            return super()._result(context, step)
        if project_session.current() is not getattr(self, "_project", None):
            return self._stop(context)
        if step.result is None:
            return None
        self._done(context)
        rows, note = step.result  # type: ignore[misc]
        values: dict[str, Any] = {
            "surfaces": [{"name": surface, "label": label, "outside": outside,
                          "selected": outside} for surface, label, outside in rows],
            "note": note}
        for given in ("name", "start"):
            if self.properties.is_property_set(given):
                values[given] = getattr(self, given)
        _invoke_later(self.COMMAND, getattr(context, "window", None) or _first_window(),
                      **values)
        return {"FINISHED"}


# --- Plataforma… (spec 015, T15; HU-015-3; RF-015-03, RF-015-28, RF-015-29; plan 015 §5.3.3, §5.5) ----

CREATE_PLATFORM = provenance.PLATFORM_COMMAND
PLATFORM_MODE_ITEMS = [
    ("CUT", "In cut", "The platform lowers the ground to its level and never raises it: it is "
                      "the floor of its footprint, not a minimum elevation"),
    ("CUT_FILL", "In cut and fill", "The platform also raises the ground to its level where "
                                    "fill is admitted")]
"""El modo de la plataforma (``design.model.PlatformMode``; D-5: «en corte» por defecto)."""
AXIS_LINK_FIELD = "eje"
"""El campo que propone el diálogo para el enlace de un polígono con su eje (plan 015 §5.2.1)."""
_PLATFORM_HIDDEN = frozenset({"confirm", "in_steps", "confirm_counterslope"})
"""Las propiedades ocultas de «Plataforma…»: las pone quien la lanza (o su ventana de confirmar)."""


def _typed(value: float | None) -> str:
    """Un valor leído de la capa como se teclea (el más corto que vuelve a dar el mismo número: lo que la
    capa dice, sin redondeos); vacío si no lo tiene."""
    return "" if value is None else repr(float(value))


def _propose_values(self: Any, _context: Any) -> None:
    """El ``update`` de la capa, de la geometría y de los campos de «Plataforma…» (T15; plan 015 §5.2.1:
    «el diálogo deja corregirlos»): **propone** la cota inicial, la pendiente y el ancho que da la capa
    para esa geometría (``design.entity_store.layer_values``), que la persona puede corregir. Lo que la capa
    no da, o no se puede leer, queda vacío: vacío es «el de la capa» y lo rechaza el cálculo si falta (no se
    elige ninguno por ella). Solo lee."""
    project = SESSION.project
    kind = des_panels.platform_layer_kind(self.layer)
    if project is None or kind is None or not self.feature.strip():
        return
    from ...design import entity_store  # al usarlo: habilitar no carga el cálculo
    from ...design.params import PlatformParam

    try:
        fields = design_model.PlatformFields(
            self.layer, self.start_level_field, self.gradient_field,
            self.width_field if kind == "line" else None)
        found = entity_store.layer_values(project, fields, self.feature.strip())
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.debug("No se pudieron leer los valores de «%s» de la capa «%s»", self.feature,
                     self.layer, exc_info=True)
        found = {}
    self.start_level = _typed(found.get(PlatformParam.START_LEVEL))
    self.gradient = _typed(found.get(PlatformParam.GRADIENT))
    self.width = _typed(found.get(PlatformParam.WIDTH))


class GEOBLENDER_OT_des_create_platform(_CalculateAndCreate, DesignCommandAware,
                                        ProvenanceAwareOperator, _StepsModal, bpy.types.Operator):
    """Platform of a layer of the project: its footprint and its level applied to its start surface,
    with the edge that joins it with the ground"""

    bl_idname = CREATE_PLATFORM
    bl_label = "Platform"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PLATFORM
    COMMAND = CREATE_PLATFORM

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the platform, unique in the active version",
        options=_FIELD)
    layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer",
        description="Layer of the project the platform is taken from: a layer of lines (the axis and "
                    "the width of each platform) or of polygons (the shape of each platform)",
        items=des_panels.platform_layer_items, options=_FIELD, update=_propose_values)
    feature: StringProperty(  # type: ignore[valid-type]
        name="Platform of the layer",
        description="Name or number (fid) of the geometry of the layer that is the platform",
        options=_FIELD, update=_propose_values)
    start_level_field: StringProperty(  # type: ignore[valid-type]
        name="Start elevation field",
        description="Numeric field of the layer with the elevation of the platform level at the "
                    "start of the axis in metres", default=START_LEVEL_FIELD, options=_FIELD,
        update=_propose_values)
    gradient_field: StringProperty(  # type: ignore[valid-type]
        name="Gradient field",
        description="Numeric field of the layer with the gradient of the platform level in %, positive "
                    "when it rises along the axis", default=GRADIENT_FIELD, options=_FIELD,
        update=_propose_values)
    width_field: StringProperty(  # type: ignore[valid-type]
        name="Width field",
        description="Numeric field of the layer of lines with the width of each platform in metres",
        default=WIDTH_FIELD, options=_FIELD, update=_propose_values)
    axis_layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of axes",
        description="Layer of lines with the axis of each polygon (none: the main axis of the "
                    "polygon)", items=des_panels.line_layer_items, options=_FIELD)
    axis_field: StringProperty(  # type: ignore[valid-type]
        name="Axis link field",
        description="Numeric field of the layer of polygons with the number (fid) of its axis in the "
                    "layer of axes", default=AXIS_LINK_FIELD, options=_FIELD)
    start_level: StringProperty(  # type: ignore[valid-type]
        name="Start elevation (m)",
        description="Elevation of the platform level at the start of the axis in metres: the one of the "
                    "layer, which you can correct (empty: the one of the layer)", options=_FIELD)
    gradient: StringProperty(  # type: ignore[valid-type]
        name="Gradient (%)",
        description="Gradient of the platform level in %, positive when it rises along the axis: the one "
                    "of the layer, which you can correct (empty: the one of the layer)",
        options=_FIELD)
    width: StringProperty(  # type: ignore[valid-type]
        name="Width (m)",
        description="Width of the platform in metres: the one of the layer, which you can correct "
                    "(empty: the one of the layer)", options=_FIELD)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the platform starts from: the ground, a design surface or the surface "
                    "of another platform (by default, the last of the chain)",
        items=des_panels.platform_start_items, options=_FIELD)
    support: EnumProperty(  # type: ignore[valid-type]
        name="Support surface",
        description="Surface the platform rests on, if it rests on one (none: it rests on no other "
                    "surface)", items=des_panels.platform_support_items, options=_FIELD)
    mode: EnumProperty(  # type: ignore[valid-type]
        name="Mode",
        description="In cut: the platform only lowers the ground to its level; in cut and fill: "
                    "it also raises it where fill is admitted", items=PLATFORM_MODE_ITEMS,
        default="CUT", options=_FIELD)
    edge_angle: StringProperty(  # type: ignore[valid-type]
        name="Edge angle (°)",
        description="Angle of the slope that joins the platform with the ground, in degrees",
        options=_FIELD)
    reach: StringProperty(  # type: ignore[valid-type]
        name="Reach of the edge (m)",
        description="Farthest distance from the footprint the edge can reach, in metres",
        options=_FIELD)
    mesh_factor: StringProperty(  # type: ignore[valid-type]
        name="Mesh factor",
        description="Factor of the mesh of the edge (empty: the default value)", options=_FIELD)
    metric: EnumProperty(  # type: ignore[valid-type]
        name="Metric",
        description="How the distance to the footprint is measured: the 5×5 chamfer (fast, with the "
                    "scale of the grid) or the exact Euclidean distance", items=METRIC_ITEMS,
        default="EXACT", options=_FIELD)
    counter_tolerance: StringProperty(  # type: ignore[valid-type]
        name="Counter-slope tolerance (m)",
        description="How much the longitudinal profile can rise against the sense in which the "
                    "platform level falls before it has to be confirmed, in metres (empty: the "
                    "default value)",
        options=_FIELD)
    protect: BoolProperty(  # type: ignore[valid-type]
        name="Protect",
        description="Declare the footprint a protected zone: the other designs neither cut nor fill "
                    "in it", default=False, options=_FIELD)
    guard: StringProperty(  # type: ignore[valid-type]
        name="Guard (m)",
        description="Distance around the footprint that is also protected, in metres; required to "
                    "protect", options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con
    # el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez. La confirmación expresa de
    # la contrapendiente (RF-015-23): la pone el botón de su ventana, que lo dice; desde un guion, quien
    # la lanza.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    confirm_counterslope: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué.
        Con ``confirm``, el diálogo de crear el cálculo abierto. Si no, las listas de capas y de
        superficies leídas de nuevo, la propuesta (el nombre, la capa y la partida: la última de la
        cadena) y el diálogo del cálculo: Intro calcula."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.refresh_choices(project)
            des_panels.refresh_platform_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label),
            confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 015 §5.3.3): un nombre que no repite
        el de ninguna plataforma de la versión («Plataforma 1»…), la primera capa y la **partida: la última
        de la cadena** (``des_panels.platform_default_start``) o, sin plataformas calculadas, el terreno
        (``surface_proposal.ground_item``, con lo seleccionado en la vista)."""
        given = self.properties.is_property_set
        if not self.name.strip():
            names, number = des_panels.platform_names(), len(des_panels.platform_names()) + 1
            while f"{tr('Platform')} {number}" in names:
                number += 1
            self.name = f"{tr('Platform')} {number}"
        layers = [identifier for identifier, _name, _about in des_panels.platform_layer_items(None, None)]
        if layers and layers[0] != des_panels.NO_LAYER and not given("layer"):
            self.layer = layers[0]
        if not given("start"):
            start = des_panels.platform_default_start()
            if start is None and des_panels.has_surfaces():
                items = [identifier for identifier, _name, _about
                         in des_panels.platform_start_items(None, None)
                         if identifier != des_panels.NO_ZONE and not identifier.startswith("entity:")]
                start = surface_proposal.ground_item(context, project, items,
                                                     des_panels.surface_choice)
            if start is not None:
                self.start = start

    def draw(self, context: Any) -> None:
        """Arriba el nombre; la capa, la geometría y sus campos; los valores que da la capa (la cota
        inicial, la pendiente y el ancho), que se corrigen aquí; la partida, el apoyo y el modo; el borde
        (su ángulo, su alcance, su factor de malla y la métrica); la tolerancia de contrapendiente y si
        protege, con su resguardo. En la confirmación de crear, el resumen."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        kind = des_panels.platform_layer_kind(self.layer)
        layout.prop(self, "name", text=tr("Name"), translate=False)
        box = layout.box()
        box.label(text=tr("Geometry of the platform"), translate=False)
        box.prop(self, "layer", text=tr("Layer"), translate=False)
        box.prop(self, "feature", text=tr("Platform of the layer"), translate=False)
        box.prop(self, "start_level_field", text=tr("Start elevation field"), translate=False)
        box.prop(self, "gradient_field", text=tr("Gradient field"), translate=False)
        if kind == "line":
            box.prop(self, "width_field", text=tr("Width field"), translate=False)
        elif kind == "polygon":
            box.prop(self, "axis_layer", text=tr("Layer of axes"), translate=False)
            if _chosen(self.axis_layer):
                box.prop(self, "axis_field", text=tr("Axis link field"), translate=False)
        values = layout.box()
        values.label(text=tr("Values of the layer (you can correct them)"), translate=False)
        values.prop(self, "start_level", text=tr("Start elevation (m)"), translate=False)
        values.prop(self, "gradient", text=tr("Gradient (%)"), translate=False)
        if kind == "line":
            values.prop(self, "width", text=tr("Width (m)"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        layout.prop(self, "support", text=tr("Support surface"), translate=False)
        layout.prop(self, "mode", text=tr("Mode"), translate=False)
        edge = layout.box()
        edge.label(text=tr("Edge of the platform"), translate=False)
        edge.prop(self, "edge_angle", text=tr("Edge angle (°)"), translate=False)
        edge.prop(self, "reach", text=tr("Reach of the edge (m)"), translate=False)
        edge.prop(self, "mesh_factor", text=tr("Mesh factor"), translate=False)
        edge.prop(self, "metric", text=tr("Metric"), translate=False)
        layout.prop(self, "counter_tolerance", text=tr("Counter-slope tolerance (m)"),
                    translate=False)
        layout.prop(self, "protect", text=tr("Protect"), translate=False)
        if self.protect:
            layout.prop(self, "guard", text=tr("Guard (m)"), translate=False)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self) -> design_model.PlatformRequest:
        """Lo pedido en el diálogo como la ``design.model.PlatformRequest`` (RF-015-01, RF-015-19),
        comprobado sin escribir ni calcular nada. Lo que se deja vacío (el factor de malla, la tolerancia
        de contrapendiente y los valores de la capa) lo resuelve el dominio: el valor por defecto de su
        parámetro o el de la capa; el ángulo, el alcance y el resguardo de quien protege no tienen
        ninguno y los rechaza el dominio si faltan (RF-015-08). :class:`ComputeFormError` si falta algo
        del diálogo."""
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the platform"))
        kind = des_panels.platform_layer_kind(self.layer)
        if kind is None:
            raise ComputeFormError(tr("Choose the layer of the platform"))
        feature = self.feature.strip()
        if not feature:
            raise ComputeFormError(tr("Write the name or the number of the platform in its layer"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the platform"))
        layer = self.layer
        start_field = _field(self.start_level_field, tr("Start elevation field"), layer)
        gradient_field = _field(self.gradient_field, tr("Gradient field"), layer)
        line = kind == "line"
        axis = kind == "polygon" and _chosen(self.axis_layer)
        fields = design_model.PlatformFields(
            layer, start_field, gradient_field,
            width_field=_field(self.width_field, tr("Width field"), layer) if line else None,
            axis_field=_field(self.axis_field, tr("Axis link field"), layer) if axis else None,
            axis_layer=self.axis_layer if axis else None)
        return design_model.PlatformRequest(
            name, fields, feature, self.start,
            support=None if self.support in ("", des_panels.NO_ZONE) else self.support,
            mode=self.mode.lower(),
            edge_angle_deg=typed_number(self.edge_angle, tr("Edge angle (°)")),
            reach_m=typed_number(self.reach, tr("Reach of the edge (m)")),
            mesh_factor=typed_number(self.mesh_factor, tr("Mesh factor")),
            counter_tol_m=typed_number(self.counter_tolerance, tr("Counter-slope tolerance (m)")),
            metric=self.metric.lower(), protect=self.protect,
            guard_m=typed_number(self.guard, tr("Guard (m)")) if self.protect else None,
            start_level_m=typed_number(self.start_level, tr("Start elevation (m)")),
            gradient_pct=typed_number(self.gradient, tr("Gradient (%)")),
            width_m=typed_number(self.width, tr("Width (m)")) if line else None)

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido
        (sin escribir nada si falta algo), pasa por la puerta de la 008 y calcula la plataforma por
        pasos con ``design.steps.platform_run`` —compila las máscaras antes si no están al día—, sin
        registrar nada (RF-015-03): desde la interfaz, en el modal con el avance y Esc (RF-015-29); desde un
        guion, de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los rechazos
        (la geometría, los campos de la capa, los parámetros que faltan, la partida, la falta de dato, un
        sector con la búsqueda pendiente, el nombre repetido) y todas las cuentas son de ``design``."""
        if self.confirm:
            return self._create(context)
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        version = scene_versions.active_version() or ""
        try:
            request = self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.platform_run(project, request, version=version,
                                          budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _confirmation(self, context: Any) -> set[str]:
        """El diálogo de crear el cálculo abierto. Con una contrapendiente que pasa de su tolerancia
        (RF-015-23: no se crea sin la confirmación expresa), su botón la dice («Confirmar la
        contrapendiente y crear»): pulsarlo es la confirmación; «Cancelar» y cerrarlo no crean nada."""
        held = calculation()
        self.confirm_counterslope = held is not None and held.needs_confirmation
        return _CalculateAndCreate._confirmation(self, context)

    def _confirm_text(self, held: Calculation) -> str:
        if held.needs_confirmation:
            return tr("Confirm the counter-slope and create")
        return _CalculateAndCreate._confirm_text(self, held)

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-015-01, RF-015-02): como las demás, y con una contrapendiente sin confirmar
        (RF-015-23) no la crea sin ``confirm_counterslope``: lo dice y el cálculo sigue abierto (se
        confirma, o se calcula otra vez). Con ella, la confirma en el cálculo antes de crearlo."""
        opened = calculation()
        if opened is not None and opened.needs_confirmation:
            if not self.confirm_counterslope:
                try:
                    opened.outcome.ensure_creatable()  # type: ignore[union-attr]
                except design_messages.DesignError as exc:
                    self.report({"ERROR"}, design_error_text(exc))
                return {"CANCELLED"}
            opened.confirm_counterslope()
        created = _CalculateAndCreate._create(self, context)
        if opened is None or "FINISHED" not in created:
            return created
        return self._update_declared(context, opened)

    # --- Lo que sigue a crearla (RF-015-10, RF-012-06; plan 015 §5.3.2, P-7) -------------------

    _chain = False
    """Si los pasos que corren son los de lo que sigue a crear la plataforma (y no los de calcularla)."""

    def _update_declared(self, context: Any, opened: Calculation) -> set[str]:
        """Tras crear la plataforma, **pone al día** las restricciones que declaran las entidades de la
        versión y las máscaras (``design.entity_store.after_entity_change``: declarar, recompilar si ya no
        están al día y decir qué quedó obsoleto, con lo ganado y perdido por restricción), por pasos con el
        avance y Esc, como el escalonado tras la envolvente: la plataforma **ya está creada** (cada etapa es
        una operación y una transacción propias); cerrar o fallar a mitad deja las máscaras obsoletas con su
        causa y se compilan de nuevo antes de que un operador las use."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        project = SESSION.project
        self._chain = True
        steps = entity_store.after_entity_change(project, opened.version,
                                                 budget_s=self.STEP_BUDGET_S)
        started = self._run_steps(context, project, opened.name, steps)
        return {"FINISHED"} if started == {"CANCELLED"} else started  # ya creada: el fallo está dicho

    def _finished(self, context: Any, opened: Any) -> set[str]:
        """Con los pasos de lo que sigue a crearla, dice lo que hizo (:meth:`_report_chain`); si no, como
        las demás órdenes."""
        if self._chain:
            self._chain = False
            self._report_chain(opened)
            return {"FINISHED"}
        return _CalculateAndCreate._finished(self, context, opened)

    def _report_chain(self, chain: Any) -> None:
        """Lo que hizo ``chain`` (``design.entity_store.EntityChain``), en el informe y en el registro: la
        declaración, las máscaras recompiladas, por restricción el polígono y la zona ganados y perdidos (m²),
        lo que quedó obsoleto y, en alerta, lo que no se pudo hacer (RF-012-06)."""
        shown = i18n.language()
        for notice in chain.notices():
            self._report({"WARNING" if notice.severity == "warning" else "INFO"}, notice.text(shown))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()

    def _created_text(self, opened: Calculation) -> str:
        return tr("Platform «{name}» created in {version}", name=opened.name,
                  version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando la plataforma… 40 % · Esc: cancelar» o, tras
        crearla, «Poniendo al día las restricciones declaradas… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._chain:
            return tr("Updating the declared constraints and the masks… {percent} % · Esc: cancel",
                      percent=percent)
        return tr("Computing the platform… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._chain:
            return tr("Cancelled: the platform is created; the declared constraints and the masks "
                      "are brought up to date before the next operation that uses them")
        return _CalculateAndCreate._cancelled_text(self)

    def _error_text(self, exc: GeoblenderError) -> str:
        found = _CalculateAndCreate._error_text(self, exc)
        if self._chain:
            return f"{found} " + tr("The platform is created: only the declared constraints and the "
                                    "masks have not been brought up to date")
        return found


# --- Vista previa de semillas, dominios y restricciones (T25; HU-013-1; RF-013-01, RF-013-02,
#     RF-013-03, RF-013-33; plan §5.3.3, §5.5, D-29) ----------------------------------------------

TOGGLE_PREVIEW = "geoblender.des_toggle_preview"


def _preview() -> Any:
    """El módulo de la vista previa (``bl.draw.design``), importado al usarlo."""
    from ..draw import design as preview  # al usarlo: nada pesado al registrar

    return preview


def _preview_on(context: Any = None) -> bool:
    """Si la vista previa está activa (sin importar su módulo si no lo está)."""
    manager = getattr(context, "window_manager", None) or getattr(bpy.context, "window_manager",
                                                                  None)
    return bool(getattr(manager, PREVIEW_PROPERTY, False))


class GEOBLENDER_OT_des_toggle_preview(DesignCommandAware, ProvenanceAwareOperator,
                                       bpy.types.Operator):
    """Show the seeds, domains and constraints before computing"""

    bl_idname = TOGGLE_PREVIEW
    bl_label = "Preview of seeds, domains and constraints"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = ENVELOPE_STAGE

    seeds_from: EnumProperty(  # type: ignore[valid-type]
        name="Origin of the seeds",
        description="Where the seeds come from: the cells of a surface inside a zone, a fixed "
                    "elevation in the cells of a zone or a grid of elevations of the project or of "
                    "the active version", items=SEEDS_FROM_ITEMS, default="SURFACE", options=_FIELD)
    surface: EnumProperty(  # type: ignore[valid-type]
        name="Surface",
        description="Surface or grid of elevations of the project or of the active version the "
                    "seeds are read from", items=des_panels.surface_items, options=_FIELD)
    zone: EnumProperty(  # type: ignore[valid-type]
        name="Zone of the seeds",
        description="Cells where the seeds are: the whole surface, the default domain, the zone "
                    "of a constraint, a design sector or a layer of polygons",
        items=des_panels.zone_items, options=_FIELD)
    elevation: StringProperty(  # type: ignore[valid-type]
        name="Elevation (m)", description="Fixed elevation of the seeds in metres", options=_FIELD)
    bound: EnumProperty(  # type: ignore[valid-type]
        name="Bound to",
        description="Where the work domain is bound: the whole domain of the masks, some sectors "
                    "or a layer of polygons (it is never enlarged)",
        items=BOUND_ITEMS, default="ALL", options=_FIELD)
    bound_layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of polygons",
        description="Layer of polygons of the project the work domain is bound to",
        items=des_panels.layer_items, options=_FIELD)

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Con la vista previa activa, se puede quitar siempre; si no, lo de las órdenes de Diseño
        (RF-013-33): con un proyecto en escritura y la versión activa editable o ninguna."""
        return True if _preview_on(context) else _write_poll(cls)

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Con la vista previa activa, la quita. Si no, sin versión activa abre la ventana que pide
        una (RF-009-05) y con ella no editable dice por qué; con una, lee de nuevo las listas de
        superficies, zonas, capas y sectores, propone de «Superficie» el terreno, como «Envolventes y
        escalonado…» (T46, ``surface_proposal.ground_item``), si quien la lanza no la dio, y abre el
        diálogo de lo que se previsualiza: Intro la muestra."""
        self.provenance_dialog = True
        if _preview_on(context):
            return self.execute(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.fill_sectors(project)
            des_panels.refresh_choices(project)
            if des_panels.has_surfaces() and not self.properties.is_property_set("surface"):
                items = [identifier for identifier, _name, _about
                         in des_panels.surface_items(None, None)]
                self.surface = surface_proposal.ground_item(context, project, items,
                                                            des_panels.surface_choice)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        des_panels.clear_sector_marks()
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.bl_idname)].label),
            confirm_text=tr("Show"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        _draw_seeds(layout, self)
        _draw_bound(layout, self)
        shown = des_panels.view()
        if self.bound == "SECTORS" and shown is not None and len(shown.sectors):
            box = layout.box()
            box.label(text=tr("Sectors"), translate=False)
            des_panels.draw_sector_rows(box, bound=True, profiles=False)

    def execute(self, context: Any) -> set[str]:
        """Con la vista previa activa, la quita. Si no, comprueba lo pedido (sin escribir ni calcular
        nada) y la activa: se construye por pasos con el temporizador, solo leyendo, y dibuja las
        semillas, el dominio de trabajo, los sectores y las restricciones con su resumen (RF-013-03)."""
        preview = _preview()
        if preview.enabled():
            preview.disable()
            self.report({"INFO"}, tr("Preview of seeds, domains and constraints hidden"))
            return {"FINISHED"}
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            des_panels.fill_sectors(SESSION.project)
            wanted = preview.Plan(
                seed_source(self.seeds_from, self.surface, self.zone, self.elevation),
                work_domain(self.bound, self.bound_layer, des_panels.view()))
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        try:
            preview.enable(wanted)
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr(
                "The preview of seeds, domains and constraints could not be shown: {detail}",
                detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of seeds, domains and constraints"))
        return {"FINISHED"}


# --- Exportar una rejilla del diseño a GeoTIFF (T28; HU-013-6; RF-013-34; plan §5.3.3, D-29) -------

EXPORT_DESIGN_GRID = "geoblender.des_export_design_grid"
EXPORT_TICKS = 1000
"""El total de los pasos de la exportación (``Progress.total``): su avance, en milésimas."""
GEOTIFF_SUFFIX = ".tif"


def _export_progress(steps: Iterator[float], name: str) -> Iterator[Progress]:
    """Los pasos de ``design.export.export_grid_steps`` (su avance, 0–1) como ``Progress`` (fase
    ``export``, en milésimas); el último lleva el fichero escrito. Cerrarlos cierra los de la
    exportación, que no dejan nada a medias."""
    try:
        while True:
            try:
                done = next(steps)
            except StopIteration as stop:
                yield Progress("export", EXPORT_TICKS, EXPORT_TICKS, name, result=stop.value)
                return
            yield Progress("export", int(EXPORT_TICKS * min(max(float(done), 0.0), 1.0)),
                           EXPORT_TICKS, name)
    finally:
        close = getattr(steps, "close", None)
        if callable(close):
            close()


class GEOBLENDER_OT_des_export_design_grid(_StepsModal, bpy.types.Operator):
    """Write a registered grid of the design (an envelope, a design surface, the berm elevations,
    the classification of a quarry or an excavation boundary) as a deliverable GeoTIFF (it is not
    an operation: also from a superseded version and, outside the project, in read-only)"""

    bl_idname = EXPORT_DESIGN_GRID
    bl_label = "Export grid to GeoTIFF…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    STEP_BUDGET_S = 0.05

    source: StringProperty(  # type: ignore[valid-type]
        name="Design grid",
        description="Uid or name of the grid of the design (empty: the active one in the view)",
        options=_FIELD)
    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.tif;*.tiff", options={"HIDDEN"})
    check_existing: BoolProperty(  # type: ignore[valid-type]
        default=True, options={"HIDDEN", "SKIP_SAVE"})
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace", description="Replace the file if it already exists", options=_FIELD)
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Con un proyecto abierto y con procedencia: exportar no es una operación (D-29), así que
        también en solo lectura (fuera del proyecto) y con la versión SUPERADO."""
        reason = SESSION.unavailable()
        if reason is not None:
            cls.poll_message_set(reason)
            return False
        return True

    def _stored(self, context: Any) -> Any:
        """La rejilla que se exporta (``design.export.StoredGrid``): la de :attr:`source` o la del
        objeto de diseño activo de la vista; ``ValueError`` sin ninguna, y ``DesignError`` si no es
        una rejilla viva del diseño."""
        from ...design import export  # al usarlo: habilitar no lo carga

        ref = self.source.strip() or des_panels.wanted(context)
        if not ref:
            raise ValueError(tr("Choose the design grid: select it in the view"))
        return export.stored_grid(SESSION.project, ref,
                                  version=scene_versions.active_version() or "")

    def invoke(self, context: Any, event: Any) -> set[str]:
        """El diálogo de fichero, con el destino que propone (``exports/<dato>_<V01>.tif`` del
        proyecto); con ``confirm``, la confirmación de sustituir el que ya existe."""
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            self.overwrite = True
            return context.window_manager.invoke_confirm(
                self, event, title=tr("Replace the file"),
                message=tr("«{file}» already exists: replace it?",
                           file=Path(self.filepath).name),
                confirm_text=tr("Replace"), translate=False)
        try:
            stored = self._stored(context)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        self.source = stored.record.uid
        if not self.filepath:
            stem = f"{stored.record.name}_{stored.version_code}"
            self.filepath = str(Path(SESSION.project.root, gis_provenance.EXPORTS_FOLDER,
                                     f"{stem}{GEOTIFF_SUFFIX}"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        """Escribe el entregable desde lo registrado (``design.export``): desde la interfaz, por
        pasos con el avance y Esc; desde un guion, de una vez. Sobre un fichero que ya existe, solo
        con ``overwrite`` (desde la interfaz, lo pregunta)."""
        from ...design import export  # al usarlo: habilitar no lo carga

        blocked = SESSION.unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        shown = self.filepath.strip()
        try:
            stored = self._stored(context)
            if not shown:
                raise ValueError(tr("Choose the file to export to"))
            target = Path(bpy.path.abspath(shown))
            steps = export.export_grid_steps(
                SESSION.project, stored.family, stored.name, target, version=stored.version_uid,
                read_only=read_only_dirs(), overwrite=bool(self.overwrite))
        except GisError as exc:
            interactive = self.in_steps and getattr(context, "window", None) is not None
            if exc.code == "gis.export_target_exists" and interactive:
                self.report({"WARNING"}, error_text(exc))
                _confirm_later({"source": stored.record.uid, "filepath": shown},
                               idname=EXPORT_DESIGN_GRID)
            else:
                self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        self._file = target.name
        progress = _export_progress(steps, target.name)
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, progress)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        try:
            for step in progress:
                if step.result is not None:
                    return self._exported()
        except (GeoblenderError, OSError) as exc:
            self._report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return {"CANCELLED"}  # pragma: no cover - los pasos acaban siempre con el fichero

    def _exported(self) -> set[str]:
        self._report({"INFO"}, tr("Design grid exported to «{file}»",
                                  file=getattr(self, "_file", "")))
        return {"FINISHED"}

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Exporting «{file}»… {percent} % · Esc: cancel",
                  file=getattr(self, "_file", ""), percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Export cancelled: nothing has been written")

    def _error_text(self, exc: GeoblenderError) -> str:
        return design_error_text(exc)

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        if step.result is None:
            return None
        self._done(context)
        return self._exported()

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except OSError as exc:  # los pasos cerrados no dejan nada a medias
            LOGGER.error("La exportación de «%s» se ha parado", getattr(self, "_file", ""),
                         exc_info=exc)
            return self._fail(context, error_text(exc))


# --- Descartar una entidad y soltar el apoyo (spec 015, T25; HU-015-2; RF-015-17, RF-015-29; plan 015 §5.3.3) --

DISCARD_ENTITY = "geoblender.des_entity_discard"
RELEASE_SUPPORT = "geoblender.des_entity_release_support"
_ITEMS_SHOWN = 5
"""Cuántos nombres lleva el aviso de lo que quedó en «apoyo retirado» (los demás, «…»)."""


class _EntitySteps:
    """Lo común de las dos órdenes de decisión sobre las entidades (T25): corren por pasos con el avance y Esc
    (``_StepsModal``) o, desde un guion, de una vez; al acabar dicen lo que hicieron (:meth:`_finished`, de cada
    una). Se pone **antes** de las bases de la orden."""

    STEP_BUDGET_S = 0.05
    in_steps = False
    _name = ""

    def _run_steps(self, context: Any, project: Any, name: str, steps: Iterator[Progress]) -> set[str]:
        """Corre los pasos ``steps`` de ``name`` de ``project``: en el modal, o de una vez desde un guion (al acabar,
        :meth:`_finished`; si fallan, ya dicho y ``CANCELLED``)."""
        self._project, self._name = project, name
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, steps)  # type: ignore[attr-defined]
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        found = _drain(self, steps)
        if found is None:
            return {"CANCELLED"}
        return self._finished(context, found)

    def _finished(self, context: Any, result: Any) -> set[str]:  # pragma: no cover - cada orden la suya
        raise NotImplementedError

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        """Con el proyecto cerrado se para sin dejar nada y lo dice; si no, sigue o, con el resultado, acaba."""
        if project_session.current() is not getattr(self, "_project", None):
            return self._fail(context, tr(  # type: ignore[attr-defined]
                "The project was closed while «{name}» was being done: nothing has been left half-done",
                name=self._name))
        if step.result is None:
            return None
        self._done(context)  # type: ignore[attr-defined]
        return self._finished(context, step.result)

    def _error_text(self, exc: GeoblenderError) -> str:
        return design_error_text(exc)

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 - los pasos cerrados no dejan nada a medias
            LOGGER.error("«%s» se ha parado", getattr(self, "bl_idname", ""), exc_info=exc)
            return self._fail(context, design_error_text(exc))  # type: ignore[attr-defined]


def _shown_items(names: list[str]) -> str:
    """Los nombres de ``names`` para un aviso: los primeros (:data:`_ITEMS_SHOWN`) y «…» si hay más."""
    found = [f"«{name}»" for name in names]
    return ", ".join([*found[:_ITEMS_SHOWN], *(["…"] if len(found) > _ITEMS_SHOWN else [])])


class GEOBLENDER_OT_des_entity_discard(_EntitySteps, DesignCommandAware, ProvenanceAwareOperator, _StepsModal,
                                       bpy.types.Operator):
    """Discard a design entity: it stays in the project as a record, nothing is deleted, and what rests on it is left as «support removed»"""

    bl_idname = DISCARD_ENTITY
    bl_label = "Discard…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PLATFORM

    entity: StringProperty(  # type: ignore[valid-type]
        name="Entity", description="Code or name of the design entity to discard", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the entity is discarded; it is recorded with the decision",
        options=_FIELD)
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    _plan = None
    """La lista que se enseña antes de descartar (``design.entity_store.DiscardPlan``)."""
    _discarded = None
    """Lo que hizo ``discard_entity`` (``design.entity_store.Discarded``), mientras corre lo que sigue."""

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Enseña **antes** la lista de lo que se apoya en la entidad y de lo que parte de ella (nombre, tipo y m³) y pide
        confirmar con el motivo; no cambia nada hasta que se acepta. Sin versión editable o sin entidad, lo dice."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            self._plan = self._read_plan()
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=tr("Discard «{name}»", name=self._plan.name), confirm_text=tr("Discard"))

    def _read_plan(self) -> Any:
        """La lista de antes de descartar la entidad pedida de la versión activa (``design.entity_store.discard_plan``)."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        if not self.entity.strip():
            raise ValueError(tr("Choose the entity to discard"))
        return entity_store.discard_plan(SESSION.project, scene_versions.active_version() or "",
                                         self.entity.strip())

    def draw(self, context: Any) -> None:
        """La lista de lo que se apoya en la entidad y de lo que parte de ella, una línea cada uno (el nombre, el tipo y los
        m³ apoyados), lo que le pasará y el motivo."""
        layout = self.layout
        plan = self._plan
        if plan is None:
            layout.prop(self, "reason", text=tr("Reason"), translate=False)
            return
        layout.label(text=tr("«{name}» ({code}) will be discarded: it stays in the project as a record and "
                             "nothing is deleted", name=plan.name, code=plan.code), translate=False)
        if plan.dependents:
            layout.label(text=tr("These rest on the entity or start from it:"), translate=False)
            box = layout.box()
            for line in plan.lines(i18n.language()):
                box.label(text=line, icon="DOT", translate=False)
            layout.label(text=tr("They are left as «support removed»."), translate=False)
            layout.label(text=tr("«Recompute the stale results» does not recompute them until you remake them on "
                                 "another surface, discard them or give them as good with a reason."),
                         translate=False)
        else:
            layout.label(text=tr("Nothing rests on the entity and nothing starts from it."), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Descarta la entidad (``design.entity_store.discard_entity``: nada se borra, un evento con el motivo) y encadena lo
        que sigue (``after_entity_change``: su restricción sale de las máscaras) por pasos con el avance y Esc; desde un
        guion, de una vez. Los rechazos (sin motivo, ya descartada, sin entidad) son de ``design``: nada se escribe."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project, version = SESSION.project, scene_versions.active_version() or ""
        try:
            if not self.entity.strip():
                raise ValueError(tr("Choose the entity to discard"))
            found = entity_store.discard_entity(project, version, self.entity.strip(), reason=self.reason,
                                                decided_by=project.session.user_host)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError, TypeError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, "des.entity_discard")  # Ctrl+Z no lo deshace
        self._discarded = found
        self.report({"INFO"}, tr("Entity «{name}» discarded in {version}: nothing has been deleted",
                                 name=found.name, version=found.version))
        if found.dependents:
            self.report({"WARNING"}, tr("Left as «support removed»: {items}",
                                        items=_shown_items([row.name for row in found.dependents])))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        steps = entity_store.after_entity_change(project, version, budget_s=self.STEP_BUDGET_S)
        started = self._run_steps(context, project, found.name, steps)
        return {"FINISHED"} if started == {"CANCELLED"} else started  # ya descartada: el fallo está dicho

    def _finished(self, context: Any, result: Any) -> set[str]:
        """Lo que hizo lo que sigue (``design.entity_store.EntityChain``): la declaración, las máscaras de nuevo, lo ganado y
        perdido por restricción y lo que quedó obsoleto."""
        shown = i18n.language()
        for notice in result.notices():
            self._report({"WARNING" if notice.severity == "warning" else "INFO"}, notice.text(shown))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        return {"FINISHED"}

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Updating the declared constraints and the masks… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Cancelled: the entity is discarded; the declared constraints and the masks are brought up to "
                  "date before the next operation that uses them")

    def _error_text(self, exc: GeoblenderError) -> str:
        return f"{design_error_text(exc)} " + tr("The entity is discarded: only the declared constraints and the "
                                                 "masks have not been brought up to date")


class GEOBLENDER_OT_des_entity_release_support(_EntitySteps, DesignCommandAware, ProvenanceAwareOperator,
                                               _StepsModal, bpy.types.Operator):
    """Give as good what lost its support because an entity was discarded: it is repeated without that support, with a reason that is recorded"""

    bl_idname = RELEASE_SUPPORT
    bl_label = "Release the support…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PLATFORM

    target: StringProperty(  # type: ignore[valid-type]
        name="Entity or design",
        description="Code or name of the entity, or uid or name of the design, that lost its support",
        options=_FIELD)
    entity: StringProperty(  # type: ignore[valid-type]
        name="Discarded entity",
        description="Code or name of the discarded entity it no longer rests on (empty: every one it lost)",
        options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why it is given as good without that support; it is recorded with the decision",
        options=_FIELD)
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    _lost = None
    """Lo que perdió su apoyo y se da por bueno (``design.entities.RetiredSupport``)."""

    def _read_lost(self) -> Any:
        """Lo que perdió su apoyo en la versión activa y se pide dar por bueno (``design.entities.retired_supports``):
        :class:`ValueError` con su porqué si no hay nada que dar por bueno."""
        from ...design import entities  # al usarlo: habilitar no carga las entidades

        wanted = self.target.strip()
        if not wanted:
            raise ValueError(tr("Choose what to give as good: an entity or a design that lost its support"))
        found = entities.retired_supports(SESSION.project, scene_versions.active_version() or "")
        for item in found:
            if wanted in (item.operation_uid, item.name, item.entity):
                if not item.releasable:
                    raise ValueError(tr(
                        "«{name}» starts from the surface of a discarded entity: remake it on another surface "
                        "or discard it; it cannot be given as good", name=item.name))
                return item
        raise ValueError(tr("«{name}» has not lost its support: nothing it rests on was discarded", name=wanted))

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Enseña lo que perdió su apoyo (la causa) y lo que pasará, y pide confirmar con el motivo; no cambia nada hasta
        que se acepta."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            self._lost = self._read_lost()
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=tr("Release the support of «{name}»", name=self._lost.name), confirm_text=tr("Give as good"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        lost = self._lost
        if lost is not None:
            from ...design import entities  # al usarlo: habilitar no carga las entidades

            layout.label(text=tr("«{name}» ({kind}) lost its support:", name=lost.name,
                                 kind=entities.kind_label(lost.op_type, i18n.language())), translate=False)
            layout.label(text=lost.text(i18n.language()), icon="DOT", translate=False)
            layout.label(text=tr("It is repeated without that support, with the reason you give."), translate=False)
            layout.label(text=tr("What depends on it is not recomputed if its result does not change."),
                         translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Repite la operación sin ese apoyo (``design.entity_store.release_support``) por pasos con el avance y Esc; desde un
        guion, de una vez. Los rechazos (sin motivo, parte de la superficie descartada, sin ese apoyo retirado…) son de
        ``design``: nada se escribe."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project, version = SESSION.project, scene_versions.active_version() or ""
        try:
            if not self.target.strip():
                raise ValueError(tr("Choose what to give as good: an entity or a design that lost its support"))
            handle, steps = entity_store.release_support(
                project, version, self.target.strip(), self.entity.strip() or None, reason=self.reason,
                decided_by=project.session.user_host, budget_s=self.STEP_BUDGET_S)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError, TypeError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        name = _shown_name(handle)
        self._project, self._name = project, name
        return self._run_steps(context, project, name, steps)

    def _finished(self, context: Any, result: Any) -> set[str]:
        """Lo que hizo: la operación repetida sin su apoyo, con su motivo."""
        undo_watch.record(UndoKind.OPERATION, provenance.PLATFORM)  # Ctrl+Z no lo deshace
        self._report({"INFO"}, tr("«{name}» given as good without its support: its result is registered with the "
                                  "reason", name=self._name))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        return {"FINISHED"}

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Repeating «{name}» without its support… {percent} % · Esc: cancel", name=self._name,
                  percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Cancelled: nothing has been left half-done")


classes: tuple[type, ...] = (GEOBLENDER_OT_des_edit_bench_profiles,
                             GEOBLENDER_OT_des_save_bench_profile,
                             GEOBLENDER_OT_des_edit_design_sectors,
                             GEOBLENDER_OT_des_set_sector_slope,
                             GEOBLENDER_OT_des_compute_envelope,
                             GEOBLENDER_OT_des_toggle_preview,
                             GEOBLENDER_OT_des_export_design_grid,
                             GEOBLENDER_OT_des_declare_sectors,
                             GEOBLENDER_OT_des_create_limit_from_perimeter,
                             GEOBLENDER_OT_des_design_quarry,
                             GEOBLENDER_OT_des_create_transitions,
                             GEOBLENDER_OT_des_design_fill_only,
                             GEOBLENDER_OT_des_refit_to_limit,
                             GEOBLENDER_OT_des_create_platform,
                             GEOBLENDER_OT_des_entity_discard,
                             GEOBLENDER_OT_des_entity_release_support)
"""Las órdenes reales del diseño (la T22 pone «Perfiles de banco…» y su orden interna, la T23
«Sectores de diseño…» y la suya, la T24 «Envolventes y escalonado…», la T25 «Vista previa de
semillas, dominios y restricciones», la T28, la interna que exporta una rejilla a GeoTIFF, y la
T44, la que declara de nuevo los sectores desde su ventana; de la 014, la T20 pone «Límite desde el
perímetro…», la T21 «Cantera con dos superficies…», la T28 «Transiciones con el terreno no
afectado», la T30 «Solo relleno…» y la T33 «Ajustar el diseño a un límite nuevo…», de la entrada
«014», que la T58 entrega; de la 015, la T15 pone «Plataforma…», de la entrada «R-36», que entrega la
T31; la T25, «Descartar…» y «Soltar el apoyo…», internas hasta que la T31 las ponga en el menú «Entidad ▾»)."""
