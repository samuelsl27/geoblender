# SPDX-License-Identifier: GPL-3.0-or-later
"""Las ventanas del diseño de explotación (spec 013; plan 013 §5.3.3, §5.5, D-17, D-24; ADR-0027).

**Perfiles de banco…** (T22; HU-013-4; RF-013-18, RF-013-19, RF-013-20, RF-013-33): la ventana
``GEOBLENDER_PT_des_profiles`` (la abre ``geoblender.des_edit_bench_profiles``, ``bl.ops.des``)
dibuja los perfiles de ``WindowManager.geoblender_design`` (``bl.props.des``), ya leídos del
proyecto:

- la lista (``GEOBLENDER_UL_des_profiles``): el nombre con la insignia de tipo de sus valores
  (la del menos firme: [HIP] antes que [ADO]) y cómo se lee, «h 10 m · cara 60° · berma 6 m ·
  ancla 125 m», en ámbar si la rejilla no lo resuelve o le falta algo;
- del elegido: su ámbito (de dónde salen los valores que se ven: «el proyecto», «V01» o «V01 y el
  proyecto»), sus **derivados** («avance 11,77 m · talud general 40,3°»), «no resuelto por la
  rejilla» en ámbar (RF-013-20; ADR-0014), lo que le falta o no vale en la versión activa y cada
  uno de sus cinco valores con su tipo y su ámbito («V03: 8 m [ADO] · proyecto: —», RF-009-29) y
  «Cambiar…» (``geoblender.core_set_parameter`` de su clave: la 008 pide el tipo, el origen, el
  decisor y el motivo y la 009 pregunta «¿Para el proyecto o solo para V01?»);
- «Perfil nuevo…» y «Completar o renombrar…» (``geoblender.des_save_bench_profile``).

**Perfil de pista…** (spec 017, T29; HU-017-1; RF-017-07, RF-017-08, RF-017-29): la ventana ``GEOBLENDER_PT_des_road_profiles`` (la abre
``geoblender.des_edit_road_profile``, ``bl.ops.des``) es la de los perfiles de banco **copiada para la pista** (plan 017 P-2: no se generaliza),
con ``WindowManager.geoblender_design.road_profiles``: la lista (``GEOBLENDER_UL_des_road_profiles``: el nombre con la insignia y «A 3,5 m · f 3 ·
pd 10 % · pm 10 % · Rmín 12 m»); del elegido, su ámbito, **su clase normativa**, sus **derivados, que no son parámetros y no se editan** (la calzada
f·A, la anchura de la sección y su semianchura, y la longitud mínima H/pd por metro de desnivel: los de ``design.road_profiles.derived``), lo que
le falta o no vale (en ámbar) y cada uno de sus quince valores **con su tipo, su ámbito y su fuente** («Fuente: … · decidido por …») y «Cambiar…»;
«Perfil nuevo…» y «Completar o renombrar…» son ``geoblender.des_save_road_profile``. ``design.road_profiles`` es perezoso: se importa al leer los
perfiles, no al habilitar (RNF-001-03).

**Accesibilidad de las pistas…** (spec 017, T30; HU-017-3; RF-017-24, RF-017-25, RF-017-29; comprobación manual M3): lo que necesita el diálogo de ``geoblender.des_road_access`` (``bl.ops.des``):
las capas de puntos de entrada y la superficie que propone (:func:`refresh_access_choices`, :func:`access_layer_items`, :func:`access_default_surface`: la última de la cadena y, sin cadena, la
explotación de la cantera) y, tras calcular, **las listas** de tramos de berma, plataformas y zonas «requiere acceso» **comunicados o no**, con su lugar y su «Ir a»
(:func:`show_access` las lee del cálculo abierto con ``show_summary``, :func:`access_sections` las da y :func:`draw_access_lists` las dibuja en la ventana de crear). El resumen que se enseña
(:func:`summary_lines`) lleva la cabecera, las cotas, el área y los avisos y **no repite lo que no se comunica**, que dicen las listas (y, en el informe de la orden,
:func:`access_report_lines`).

Los derivados y la marca de la rejilla **no se calculan aquí**: son los de
``design.model.BenchProfile`` (``avance_m``, ``general_deg``, ``unresolved_by``). **Nada se lee al
dibujar**: :func:`fill_profiles` regenera la vista desde el proyecto (al abrir la ventana y tras
guardar) y :func:`on_project_read` la vuelve a leer cuando la procedencia avisa de que el
proyecto cambió (``bl.ui.provenance.add_change_listener``: un valor cambiado con ``Cambiar…``).
En solo lectura o con la versión activa no editable dice por qué y dibuja desactivado lo que
escribe (RF-013-33). Los textos pasan por ``core.i18n`` y se dibujan con ``translate=False``.

**Sectores de diseño…** (T23; HU-013-2; RF-013-07, RF-013-08, RF-013-10, RF-013-21): la ventana
``GEOBLENDER_PT_des_sectors`` (la abre ``geoblender.des_edit_design_sectors``) dibuja los sectores
de ``WindowManager.geoblender_design``, leídos con :func:`fill_sectors` de ``design.sectors``
(los de la 012, o el perímetro de actuación como único sector):

- la lista (``GEOBLENDER_UL_des_sectors``): el nombre, el área, el talud impuesto y el estado de su
  búsqueda de intocables, «Búsqueda pendiente» en ámbar;
- del elegido: su código (la clave de su talud, ADR-0029), su área, el estado de su búsqueda (con
  quién la cerró y cuándo, o pendiente en ámbar con la orden de la 012 para hacerla), el talud que
  impone («10,6° [ADO]») con su origen, su decisor y su ámbito («la propiedad · decidido por … ·
  V01»), el perfil asignado a la superficie en preparación (:func:`assign_profiles`, que llama la
  ventana de las envolventes) y «Fijar el talud del sector…» (``geoblender.des_set_sector_slope``);
- los taludes de los sectores que ya no existen (renombrados o quitados), en una lista aparte y
  sin borrarlos nunca (RF-013-10);
- «Declarar de nuevo desde una capa…»: la capa y el campo de la 012 y su orden
  ``geoblender.core_declare_sectors``, que conserva los valores de los sectores que mantienen su
  código; la ventana se pone al día sola (:func:`on_project_read`).

Ni el área, ni el estado, ni el talud, ni los huérfanos se calculan aquí: son los del dominio
(``design.sectors``).

**Envolventes y escalonado…** (T24; HU-013-1, HU-013-3, HU-013-5, HU-013-6; RF-013-17, RF-013-21,
RF-013-31): lo que ofrece su diálogo y lo que enseña su resumen, ya leído del proyecto.
:func:`refresh_choices` lee las superficies y rejillas de cotas (las del proyecto y las de la
versión activa), las zonas (el dominio por defecto, las restricciones, los sectores y las capas
de polígonos) y las capas con que se puede acotar el dominio, en listas vivas del módulo que
alimentan los ``EnumProperty`` dinámicos (:func:`surface_items`, :func:`anchor_items`,
:func:`zone_items`, :func:`layer_items`; ``docs/trampas.md`` §3). :func:`draw_sector_rows` dibuja
los sectores con su marca de acotado y su perfil. :func:`show_summary` deja el resumen del cálculo
abierto (``summary_title`` y ``summary``) con :func:`summary_lines`: el desmonte, el terraplén, la
inclinación, las bermas y los avisos (en ámbar), de las cifras y del informe del dominio (aquí solo se
escriben).

**Vista previa de semillas, dominios y restricciones** (T25; HU-013-1; RF-013-03):
:func:`show_preview` deja en ``WindowManager.geoblender_design.preview`` el resumen que dice
``design.preview`` (líneas ya traducidas, los avisos en alerta) cuando ``bl.draw.design`` acaba de
construir la vista previa de la Vista 3D, y lo vacía al quitarla; la barra N «Diseño» lo enseña
mientras lo hay.

**La barra N «Diseño»** (T27; HU-013-6; RF-013-32, RF-013-06, RF-010-06): el panel
``GEOBLENDER_PT_des_design`` (de la Vista 3D) enseña, del objeto ``DESIGN`` activo (una envolvente,
una superficie de diseño o una rejilla de cotas de berma cargada en la vista por
``bl.scene.des_views``), lo que dice de él el proyecto (:func:`item_lines`; todo lo da el proyecto, nada
se calcula aquí): su estado, **al día u obsoleto con su causa** (``core.provenance.stale``); en alerta,
la marca «búsqueda de intocables pendiente» con el sector, si un sector que tocó su dominio de trabajo
ya no tiene la búsqueda vigente (``design.sectors.pending_marks``, RF-013-06; una fila por sector
pendiente, y otra vez como primeras filas del apartado «Cifras», junto a ellas: es del estado de ahora
y no del cálculo, no se escribe en el proyecto y el informe y las cifras guardados no la llevan); los
ajustes de su operación y los **parámetros** que leyó, cada uno con su valor, su insignia de tipo, su
ámbito, su origen y su decisor, y lo que valen hoy si cambiaron (``core.provenance.lineage``); las
**semillas** y el dominio de trabajo (los ajustes de la envolvente: la de un escalonado, la suya); las **restricciones
aplicadas** (las activas en su versión) y sus **cifras** registradas con su insignia. Sin objeto de
diseño activo, enseña el resumen de la vista previa de las semillas mientras lo hay. Las mismas líneas,
sin las cifras (que ya son las de su ficha), las enseñan «Elemento activo» y «Cifras de la selección»
de la 010 (``view_panels.register_object_lines``). **Nada se lee al dibujar**: :func:`read_selected`
regenera las líneas al cambiar el objeto activo, tras cada lectura del proyecto cambiado y tras cargar un
``.blend`` (``view_panels.add_card_listener``). Con un dato leído, al final de la barra N está el botón
«Exportar rejilla a GeoTIFF…» (T28; RF-013-34: ``geoblender.des_export_design_grid`` con la rejilla del
objeto activo), siempre activo: exportar no escribe en el proyecto, así que vale en solo lectura.

**«Límite desde el perímetro…»** (spec 014, T20; HU-014-1; RF-014-01): el resumen de su cálculo
(:func:`show_summary`, :func:`summary_lines`: «Recinto excavable «Límite» en V01», sus celdas y su
área) y la ficha de su recinto en la barra N (:func:`item_lines`: su título «Recinto excavable ·
Límite», su superficie de partida y su cifra, sin semillas ni envolvente: el recinto es el corte
admitido de las máscaras).

**«Cantera con dos superficies…»** (spec 014, T21; HU-014-3; RF-014-12, RF-014-13): las listas de su
diálogo, leídas con las demás en :func:`refresh_choices` (las capas de polígonos que puede no usar,
:func:`optional_layer_items`; las de líneas de los corredores, :func:`line_layer_items` con
:func:`line_layers`; y la zona a conservar, :func:`conserve_items`), el perfil de cada sector por
superficie (:func:`draw_sector_rows` con ``pick``, que :func:`fill_sectors` conserva) y el resumen de
su cálculo (:func:`show_summary`: «Cantera «Corta» en V01», el orden con las celdas que cambió su
regla, las cotas de cada superficie, la excavación de la explotación, el desdoblado y el relleno, y
sus avisos).

**El resumen, la clasificación y la barra N de la cantera** (spec 014, T22; HU-014-3, HU-014-4;
RF-014-15 a RF-014-18; plan 014 §5.5): el resumen dice además la excavación de la explotación en ha,
la clasificación con el área de cada clase en ha y el espesor mínimo que la separa, y «explotación
hasta la final: no» si no se pidió (con el modo, lo que pasó a la explotación es una de sus notas;
el aviso de desdoblado sobre terreno sin explotar, con sus zonas, va en ámbar). La barra N enseña la
ficha de cada rejilla de la cantera cargada en la vista (``bl.scene.des_views``: las dos
superficies, sus envolventes y la clasificación): sus ajustes, los perfiles de cada superficie, la
superficie de partida, las capas que leyó con sus campos, los parámetros, las semillas de cada
superficie con el recinto como dominio, las restricciones, la leyenda de la clasificación (un color
por clase) y las cifras registradas, por sector y en total.

**«Solo relleno…»** (spec 014, T30; HU-014-6; RF-014-22 a RF-014-24): la lista de las envolventes
de la versión activa de su diálogo (:func:`envelope_items`, leída en :func:`refresh_choices`), el
resumen de su cálculo (:func:`show_summary`: «Diseño «solo relleno» «Balsa» en V01», el terraplén,
el corte frente al terreno registrado y el área con movimiento, las celdas en que la lámina de agua
es la partida, la inclinación y las bermas, y los avisos de su escalonado) y, en la ficha de su
superficie (una ``des_srf_``), la capa de láminas con su campo.

**La comprobación contra un límite nuevo** (spec 014, T31; HU-014-7; RF-014-26): al recompilar las
máscaras de una versión, :func:`limit_steps` añade al resumen de la compilación
(``constraint_panels.compile_check_steps``) el aviso de cada superficie de diseño de la 014 que
mueve algo fuera del límite vigente, con su volumen y su área (``design.store.limit_checks``), y la
ficha de la barra N de esa superficie lo dice también, en alerta, tras su estado. Desde la T35
(RNF-014-02), **por pasos y con una caché en memoria** (``design.store.LimitCheckMemo``, la de
:data:`_LIMITS`): los pasos de la compilación comprueban, tras guardarla, todas las superficies de
diseño de la versión que se pueden ajustar y las guardan con su clave barata; la ficha y el diálogo
del ajuste las leen de ella sin leer ninguna rejilla. Sin acierto, la ficha no se bloquea: no dice
nada y lanza la comprobación por pasos en un temporizador (:func:`limit_tick`), que llena la caché y
vuelve a leer la ficha; el diálogo comprueba antes de abrirse (:func:`refit_rows_steps`, en el modal
de su orden). La caché se invalida sola por la clave y se vacía al cerrar el proyecto y al
desactivar Geoblender (:func:`forget_limit_checks`).

**«Ajustar el diseño a un límite nuevo…»** (spec 014, T33; HU-014-7; RF-014-27, RF-014-32): las filas
de su diálogo (:func:`refit_rows`: cada superficie de diseño de la versión que se puede ajustar, con
lo que deja fuera del límite vigente; las que lo dejan, marcadas), el resumen de su cálculo
(:func:`show_summary`: «Ajuste «…» en V01» y, por superficie, su volumen de ajuste con la cara de su
perfil) y la ficha de cada superficie ajustada (la superficie de la que sale y su partida). El botón
«Exportar rejilla a GeoTIFF…» vale ya para todas las rejillas de la 014 (la clasificación y el
recinto, con su leyenda en los metadatos: ``design.export``).

**«Plataforma…»** (spec 015, T15; HU-015-3; RF-015-03, RF-015-28; plan 015 §5.3.3, §5.5): las listas de
su diálogo (:func:`refresh_platform_choices`: las capas de líneas o de polígonos del proyecto con su
geometría, :func:`platform_layer_items` y :func:`platform_layer_kind`; las superficies de partida —el
terreno, las de diseño y la de cada plataforma de la versión activa como ``entity:PLT-001``—,
:func:`platform_start_items` y :func:`platform_default_start`, que propone **la última de la cadena**; y
las de apoyo, :func:`platform_support_items`) y el resumen de su cálculo (:func:`show_summary`,
:func:`_platform_lines`: «Plataforma «Carga» (PLT-001) en V01», su huella, su rasante, el corte y el
relleno de la huella y del borde, el mayor desmonte o relleno del borde y «sin contrapendientes», y sus avisos y lo que
quedará obsoleto: el resumen de ``design.preview.PlatformSummary``).

**«Retirar un acopio…»** (spec 016, T20 (b); HU-016-2; RF-016-11 a RF-016-15; plan 016 §5.3.3, §5.5; comprobación manual M1): las listas de
su diálogo (:func:`refresh_removal_choices`: los acopios de las detecciones de la versión activa y del proyecto con su detección y su
estado, :func:`removal_stockpile_items` y :func:`removal_stockpile`; la partida es la de «Plataforma…», :func:`platform_start_items`, que
ofrece también la superficie de cada retirada de la cadena), **lo que se apoya en el acopio elegido, antes de calcular**
(:func:`show_resting`, :func:`resting_lines` y :func:`draw_resting`: una sola lista, en ámbar, o por qué no se pudo leer) y el resumen de
su cálculo (:func:`_removal_lines`: lo retirado, lo apoyado, la transición, lo no retirado, la pared y su motivo, la lista de lo que se
apoyaba y sus avisos; el resumen de ``design.preview.RemovalSummary``). Retirado **«como plataforma»** (T41; RF-016-16) el cálculo es el de
una plataforma de la 015 con la huella del acopio y su resumen es el de :func:`_platform_lines` con **una línea más con las cifras de la
retirada** (lo retirado, lo apoyado y lo no retirado: la transición es el borde de la plataforma) y la lista de lo que se apoyaba como primer
aviso; su título dice «como plataforma».

**«Contrafuerte…»** (spec 016, T27; HU-016-3; RF-016-17, RF-016-18; plan 016 §5.3.3, §5.5; comprobación manual M3): las listas de su
diálogo (:func:`refresh_buttress_choices`: las capas de polígonos de las zonas de coronación, :func:`buttress_zone_items`, y las
superficies de apoyo, :func:`buttress_support_items`; la partida es la de «Plataforma…», :func:`platform_start_items`, y el perfil se
elige entre los de la vista de los perfiles de banco) y el resumen de su cálculo (:func:`_buttress_lines`: el volumen, el área y la mayor
altura con su lugar, la coronación con su perfil y su zona, lo que declarará y sus avisos; el resumen de ``design.preview.ButtressSummary``).

**La barra N «Entidad»** (spec 015, T28; HU-015-1; RF-015-25, RF-010-06; D-12): el panel
``GEOBLENDER_PT_des_entity`` (de la Vista 3D) enseña, del objeto ``DESIGN_ENTITY`` activo (la huella y el eje de una
entidad cargados en la vista por ``bl.scene.entity_views``), lo que dice de ella el proyecto
(:func:`entity_lines`; **todo lo da el proyecto, nada se calcula aquí**): su **estado** (al día; obsoleta o con el apoyo
retirado, con su causa, ``design.entities.stale_reason``; descartada, un registro que no se usa; o sin calcular), sus
**parámetros** con su insignia de tipo y su origen (los de su familia ``des.platform.{e}.*``: «capa X, campo Y, entidad
Z»), **sus restricciones declaradas** (si protege: su tipo, su resguardo, su motivo, quién la decidió y su estado, activa,
bloqueada o divergente), su **cadena** (de qué superficie parte, qué entidad parte de la suya y cuál es la última),
**en qué se apoya** y **lo que se le apoya** (``design.entities.dependencies_of`` y ``dependents``: una sola lista cada
uno, con sus m³ y el estado de cada fila) y sus **cifras** con su insignia. :func:`entity_card` lo lee por el código de la
entidad (también una **sin calcular**, que no tiene datos y por tanto objeto); :func:`entity_lines`, por el dato del
objeto, en una sola instantánea. Las mismas líneas, sin las cifras, las enseñan «Elemento activo» y «Cifras de la
selección» de la 010 (:func:`entity_object_lines`, ``view_panels.register_object_lines``). La lectura es la de la barra
N «Diseño»: :func:`read_selected` regenera las líneas al cambiar el objeto activo, tras cada lectura del proyecto
cambiado y tras cargar un ``.blend`` (``WindowManager.geoblender_design.item``), y nada se lee al dibujar. Con una
entidad leída, al final de la barra N está el botón «Exportar rejilla a GeoTIFF…» (T30; RF-015-27: la misma
``geoblender.des_export_design_grid``, que con el objeto de una entidad exporta **su superficie**, ``des_psf_``): como el
de la barra N «Diseño», siempre activo, porque exportar no escribe en el proyecto. La ventana de «Lo que se apoya en ella» del
menú «Entidad ▾» (T31; RF-015-28) dibuja esas mismas filas de dependencias (:func:`dependent_texts`).

**La barra N «Entidad» con los tipos de la 016** (spec 016, T33; HU-016-1 a HU-016-4; RF-015-25, RF-016-14; plan 016 §5.5; comprobación manual M5): la
misma ficha (:func:`entity_card`) para una **detección de acopios** (el objeto de ``des_stk_``; también la **del proyecto**, D-15, sin lista de
dependencias: se leen en cada versión), una **retirada**, un **contrafuerte** y un **cuerpo apoyado**, con lo propio de cada tipo tras su estado
(:func:`_type_lines`; sus parámetros, los de su familia ``des.<tipo>.{e}.*``; el tipo sin cadena no la tiene): de la detección, **sus acopios**
(:func:`_stockpile_lines`: la nota del resumen de «Calcular» con lo guardado —plano, huella, volumen, espesor máximo y material—, sus avisos y,
en alerta, **«retirado en su superficie»** por una retirada viva) y **la lista de candidatos con su estado** (:func:`_candidate_lines`: pendiente, convertido
o descartado, con su motivo, quién y cuándo; los botones de convertir y descartar los pone la orden de la lista de candidatos, T35); de la retirada,
**lo retirado, lo apoyado y la pared** (:func:`_removal_card_lines`); del contrafuerte, **la coronación y el pie cortado** (:func:`_buttress_card_lines`);
del cuerpo, **el espesor y lo lejano** (:func:`_body_card_lines`). Los estados son los de la 015 (al día, obsoleta, descartada, «apoyo retirado» y
sin calcular) y, de un acopio, «retirado en su superficie» (D-12). Todo se **lee del proyecto** (las tablas de la operación vigente y su informe,
``design.entity_store.read_entity_report``); los textos de los avisos salen de los códigos guardados, en el idioma de la interfaz.

**La barra N con la pista y la accesibilidad** (spec 017, T31b; HU-017-1 a HU-017-3; RF-015-25, RF-017-23, RF-017-25; plan 017 §5.5; comprobación manual M4): de **una pista** (el objeto
``DESIGN_ENTITY`` de su ``des_epr_``) la ficha de la barra N «Entidad» y «Elemento activo» (:func:`entity_card`) añade, tras su estado, :func:`_road_card_lines`: su **modo y su perfil**, la
longitud y las cotas de la rasante, la pendiente media y la máxima con su abscisa y su lugar, el radio mínimo, la calzada y la sección, el corte y el relleno **de la sección y del borde**, la
pared del borde, lo que la persona confirmó al crearla (RF-017-17, RF-017-22), los avisos del cálculo y, **en alerta**, (1) **la causa y la salida** de una pista obsoleta por **otro diseño que lee**
(H2-2: ese diseño se apoya luego en ella y «Recalcular lo obsoleto» no la asienta; la salida es rehacerla sobre la superficie de ese diseño o descartarla) y (2) que **la capa de ejes de pistas para
QGIS está marcada** (cambiar el valor de un perfil deja la pista obsoleta y no la regenera al instante; T26-b). Lo que se le apoya y en qué se apoya, sus parámetros y su cadena son los de
cualquier entidad. **De una accesibilidad** (el objeto ``DESIGN`` de su ``des_acc_``: la barra N «Diseño», :func:`item_lines`, que no cambia :func:`entity_wanted`) la ficha lleva su estado como
entidad (al día, obsoleta con su causa, descartada, «apoyo retirado»; :func:`_entity_state_line`) y :func:`_access_card_lines`: la superficie, las cotas mínima y máxima alcanzables y **las tres
listas de tramos de berma, plataformas y zonas «requiere acceso» comunicados o no**, las que no, primero y en alerta, cada una con su **«Ir a»** (``ROW_PLACE``: :func:`_draw_item` lo dibuja). El
lugar es el que guardan ``des_acb_`` y ``des_acz_`` (el tramo de berma y la zona que no se comunica) o el centro de la huella de la plataforma; una zona comunicada no tiene lugar guardado y no
tiene «Ir a». Todo se **lee del proyecto** (``design.road_card``): nada se calcula aquí."""

from __future__ import annotations

import json
import logging
import numbers
import sqlite3
import time
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy

from ...core.catalog.search import path_text
from ...core.constraints.declared import is_declared_code
from ...core.errors import GeoblenderError
from ...core.i18n import format_number, language, tr, translate
from ...core.params import ParameterStore, ParamKind, format_value, parameter_label
from ...core.params import definition as param_definition
from ...core.params.store import shown_value
from ...core.project.model import Progress
from ...design import messages as design_messages
from ...design import profiles as design_profiles
from ...design import provenance as design_provenance
from ...design.model import (PERIMETER_SEGMENT, BenchProfile, CellClass, Order, SeedKind, Surface,
                             ToFinalMode, ZoneKind)
from ...design.params import BenchParam, RoadProfileParam, bench_key, road_profile_key
from ...gis import provenance as gis_provenance
from ...gis import store as gis_store
from ...gis.masks import provenance as masks_provenance
from ...reserves import surfaces as res_surfaces
from ..props.des import WINDOW_MANAGER_PROPERTY
from ..scene import constraint_views, des_views, entity_views, project_session
from ..scene import versions as scene_versions
from . import constraint_panels, labels, provenance, view_panels
from .commands import catalog
from .commands import text as command_text
from .context import active_object, object_kind
from .res_panels import NOT_SHOWN, record_text
from .view_panels import ROW_FIELD, ROW_FIGURE, ROW_HEADING, ROW_NONE, CardLine

if TYPE_CHECKING:  # solo para los tipos: habilitar no importa el cálculo (RNF-001-03)
    from ...design.model import EnvelopeRequest, QuarryRequest, SeedSource, WorkDomain, Zone
    from ...design.sectors import DesignSector, OrphanSlope
    from ...design.steps import Calculation
    from ...design.supported_store import StockpileChoice

LOGGER = logging.getLogger("geoblender.bl.ui")
TRANSLATION_CONTEXT = "Geoblender"
PROFILES_PANEL = "GEOBLENDER_PT_des_profiles"
PROFILES_LIST = "GEOBLENDER_UL_des_profiles"
SAVE_PROFILE = "geoblender.des_save_bench_profile"
SET_PARAMETER = "geoblender.core_set_parameter"
SECTORS_PANEL = "GEOBLENDER_PT_des_sectors"
SECTORS_LIST = "GEOBLENDER_UL_des_sectors"
SET_SECTOR_SLOPE = "geoblender.des_set_sector_slope"
DECLARE_SECTORS = constraint_panels.DECLARE_SECTORS
DECLARE_SECTORS_AGAIN = "geoblender.des_declare_sectors"  # la 012 y volver a leer (T44)
FIND_UNTOUCHABLES = "geoblender.core_find_untouchables"
EDIT_LIMITS = constraint_panels.EDIT_LIMITS
ROAD_PROFILES_PANEL = "GEOBLENDER_PT_des_road_profiles"
ROAD_PROFILES_LIST = "GEOBLENDER_UL_des_road_profiles"
SAVE_ROAD_PROFILE = "geoblender.des_save_road_profile"
PROFILES_PANEL_UNITS = 40
PROFILES_WIDTH_PX = PROFILES_PANEL_UNITS * 20
PROFILE_ROWS = 5
SECTORS_PANEL_UNITS = 44
SECTORS_WIDTH_PX = SECTORS_PANEL_UNITS * 20
SECTOR_ROWS = 4
SECTOR_NAME_FACTOR = 0.3
SECTOR_AREA_FACTOR = 0.25
SECTOR_SLOPE_FACTOR = 0.35
"""Cómo reparte la fila de la lista de sectores su ancho: el nombre, el área, el talud impuesto
y, con lo que queda, el estado de su búsqueda."""
DERIVED_DECIMALS = 2
"""Los decimales con que se lee el avance (m) y el talud general (°) de un perfil: «11,77 m» y
«40,34°» (RF-013-20 los escribe a dos decimales y a uno, «40,3°»)."""
NAME_FACTOR = 0.4
FIRMNESS = (ParamKind.HIPOTESIS, ParamKind.ADOPTADO, ParamKind.CALCULADO, ParamKind.MEDIDO)
"""Los tipos de menos a más firme: la insignia de un perfil es la de su valor menos firme."""
REQUIRED = (BenchParam.HEIGHT, BenchParam.FACE, BenchParam.BERM, BenchParam.ANCHOR)
"""Los cuatro valores que se declaran siempre (el factor de malla tiene uno por defecto)."""
LABELS = {
    BenchParam.HEIGHT: "Bench height",
    BenchParam.FACE: "Face angle of the bench",
    BenchParam.BERM: "Minimum berm width",
    BenchParam.ANCHOR: "Anchor elevation",
    BenchParam.MESH_FACTOR: "Mesh factor of the profile",
}
"""El ``msgid`` del nombre de cada valor (el de ``design.params.FAMILIES``)."""
ROAD_REQUIRED = tuple(param for param in RoadProfileParam
                      if param not in (RoadProfileParam.MESH_FACTOR, RoadProfileParam.METRIC))
"""Los trece valores de un perfil de pista que se declaran siempre (el factor de malla y la métrica tienen uno por defecto: D-2)."""


def view() -> Any | None:
    """``WindowManager.geoblender_design`` (``None`` sin la extensión registrada)."""
    manager = getattr(bpy.context, "window_manager", None)
    return getattr(manager, WINDOW_MANAGER_PROPERTY, None)


def _write_unavailable() -> str | None:
    """Por qué no se puede escribir ahora (sin proyecto, solo lectura o la versión activa no
    editable), o ``None``."""
    from ..ops import des as des_ops  # al usarlo: bl/ops importa bl/ui (ARQ-08)

    return des_ops.design_unavailable()


# --- Lo que se enseña de un perfil ---------------------------------------------------------------


def number_text(value: float | None, param: BenchParam) -> str:
    """Un valor de un perfil como se lee: «10 m», «60°»; sin valor, «—»."""
    if value is None:
        return NOT_SHOWN
    shown = format_value(float(value), language())
    return f"{shown}°" if param is BenchParam.FACE else f"{shown} m"


def design_error_text(exc: design_messages.DesignError) -> str:
    """El texto de un error del diseño en el idioma de Geoblender (``DesignError.text`` es el
    español), con las notas que lo acompañan (las partes de RF-014-08, T47)."""
    return exc.text_in(language())


def parameter_text(project_record: Any, own: Any, key: str, version: Any) -> str:
    """Un valor de un perfil con su tipo y su ámbito: el del proyecto y, si hay una versión activa
    (``version``), el propio de ella («V01: 10 m [ADO] · proyecto: —», RF-009-29). Sin ningún
    valor registrado, el de por defecto de su definición («1 [ADO] sin confirmar») o «—»."""
    if project_record is None and own is None:
        found = param_definition(key)
        return NOT_SHOWN if found is None or found.default is None else record_text(None, key)
    project_text = NOT_SHOWN if project_record is None else record_text(project_record)
    if version is None:
        return project_text
    own_text = NOT_SHOWN if own is None else record_text(own)
    return tr("{version}: {value} · project: {project}", version=version.code, value=own_text,
              project=project_text)


def _grid(project: Any) -> Any | None:
    """La rejilla del proyecto (su ventana y su paso), con la que se mira lo que la rejilla no
    resuelve; ``None`` si no se puede leer."""
    from ...gis.grid import project_grid  # al usarlo: habilitar no lo carga

    record = getattr(project, "record", None)
    if record is None:
        return None
    try:
        return project_grid(record.window, float(record.grid_step_m))
    except (GeoblenderError, ValueError):
        LOGGER.warning("No se pudo leer la rejilla del proyecto", exc_info=True)
        return None


def _scope_text(origins: set[str], version: Any) -> str:
    """De dónde salen los valores que se ven: «el proyecto», «V01» o «V01 y el proyecto»."""
    if not origins:
        return NOT_SHOWN
    if origins == {"project"}:
        return tr("the project")
    if origins == {"version"}:
        return str(version.code)
    return tr("{version} and the project", version=version.code)


def put_profile(target: Any, row: Any, store: ParameterStore, conn: sqlite3.Connection,
                version: Any, grid: Any | None) -> None:
    """Un perfil del proyecto (``design.profiles.StoredProfile``) en la fila ``target`` de la
    vista: sus cinco valores con su tipo y su ámbito, de dónde salen, su insignia, cómo se lee y
    sus derivados, que son los del dominio (``BenchProfile``)."""
    shown = language()
    target.name, target.code = row.name, row.code
    target.parameters.clear()
    values: dict[BenchParam, Any] = {}
    kinds: list[ParamKind] = []
    origins: set[str] = set()
    for param in BenchParam:
        key = bench_key(row.code, param)
        project_record = store.get(key, conn=conn)
        own = None if version is None else store.get(key, version=version.uid, conn=conn)
        line = target.parameters.add()
        line.key, line.registered = key, project_record is not None or own is not None
        line.name = translate(shown, LABELS[param])
        line.text = parameter_text(project_record, own, key, version)
        chosen = next((record for record in (own, project_record)
                       if record is not None and record.value is not None), None)
        if chosen is not None:
            values[param] = chosen.value
            if param in REQUIRED:
                kinds.append(chosen.kind)
                origins.add("version" if chosen is own else "project")
        elif param is BenchParam.MESH_FACTOR:
            found = param_definition(key)
            values[param] = None if found is None else found.default
    target.summary = tr(
        "h {height} · face {face} · berm {berm} · anchor {anchor}",
        height=number_text(values.get(BenchParam.HEIGHT), BenchParam.HEIGHT),
        face=number_text(values.get(BenchParam.FACE), BenchParam.FACE),
        berm=number_text(values.get(BenchParam.BERM), BenchParam.BERM),
        anchor=number_text(values.get(BenchParam.ANCHOR), BenchParam.ANCHOR))
    target.badge = provenance.badge(min(kinds, key=FIRMNESS.index)) if kinds else ""
    target.scope = _scope_text(origins, version)
    target.derived = target.unresolved = target.problem = ""
    try:
        profile = BenchProfile(row.code, row.name,
                               **{param.value: values.get(param) for param in BenchParam})
    except design_messages.DesignError as exc:  # le falta algo o no vale en la versión activa
        target.problem = design_error_text(exc)
        return
    target.derived = tr("advance {advance} m · general slope {slope}°",
                        advance=format_number(profile.avance_m, DERIVED_DECIMALS),
                        slope=format_number(profile.general_deg, DERIVED_DECIMALS))
    if grid is not None:
        target.unresolved = profile.unresolved_by(grid, language=shown) or ""


def fill_profiles(project: Any) -> int:
    """Regenera la lista de Perfiles de banco… desde ``project`` (RF-013-18, RF-013-20): los
    perfiles del proyecto (``design.profiles.read_profiles``), cada uno con sus valores en la
    versión activa y en el proyecto y sus derivados; conserva el elegido (por su código).
    Devuelve cuántos hay. Si no se puede leer, el error sigue y la vista queda como estaba."""
    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        raise RuntimeError("la vista de los perfiles de banco no está registrada")
    version = scene_versions.active()
    store = ParameterStore(project)
    grid = _grid(project)
    old = shown.profiles
    chosen = old[shown.profile_index].code if 0 <= shown.profile_index < len(old) else ""
    with project.read() as conn:
        stored = design_profiles.read_profiles(conn)
        shown.profiles.clear()
        for row in stored:
            put_profile(shown.profiles.add(), row, store, conn, version, grid)
    shown.profile_index = next((index for index, item in enumerate(shown.profiles)
                                if item.code == chosen), 0)
    shown.profiles_project = project.uid
    return len(shown.profiles)


def choose(code: str) -> None:
    """Deja elegido en la lista el perfil de código ``code`` (si está)."""
    shown = view()
    if shown is None:
        return
    for index, item in enumerate(shown.profiles):
        if item.code == code:
            shown.profile_index = index
            return


def show_report(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` (texto, si va en alerta) como el último resultado de la ventana."""
    shown = view()
    if shown is None:
        return
    shown.profile_report.clear()
    for text, alert in lines:
        line = shown.profile_report.add()
        line.name, line.alert = text, alert


# --- Lo que se enseña de un perfil de pista (spec 017, T29) ------------------------------------------


def _road_length(value: float) -> str:
    """Una longitud derivada como se lee: «10,5 m», «5,75 m» (a lo sumo :data:`DERIVED_DECIMALS` decimales)."""
    return f"{format_value(round(float(value), DERIVED_DECIMALS), language())} m"


def put_road_profile(target: Any, row: Any, store: ParameterStore, conn: sqlite3.Connection, version: Any) -> None:
    """Un perfil de pista del proyecto (``design.road_profiles.StoredProfile``) en la fila ``target`` de la vista: sus quince valores con su tipo,
    su ámbito y **su fuente**, su clase normativa, cómo se lee, su insignia y sus **derivados**, que son los del dominio (``RoadProfile`` y
    ``derived``: la calzada, la sección, su semianchura y la longitud mínima H/pd; RF-017-08) y **no son parámetros**."""
    from ...design import road_profiles  # al usarlo: habilitar no lo carga (RNF-001-03)

    shown = language()
    target.name, target.code = row.name, row.code
    target.parameters.clear()
    chosen: dict[RoadProfileParam, Any] = {}
    kinds: list[ParamKind] = []
    origins: set[str] = set()
    for param in RoadProfileParam:
        key = road_profile_key(row.code, param)
        project_record = store.get(key, conn=conn)
        own = None if version is None else store.get(key, version=version.uid, conn=conn)
        found = param_definition(key)
        line = target.parameters.add()
        line.key, line.registered = key, project_record is not None or own is not None
        line.name = translate(shown, found.label_msgid) if found is not None and found.label_msgid else param.value
        line.text = parameter_text(project_record, own, key, version)
        record = next((item for item in (own, project_record) if item is not None and item.value is not None), None)
        if record is None:
            continue
        chosen[param] = record
        line.source = tr("Source: {source} · decided by {who}", source=record.source or NOT_SHOWN, who=record.decided_by)
        if param in ROAD_REQUIRED:
            kinds.append(record.kind)
            origins.add("version" if record is own else "project")

    def shown_of(param: RoadProfileParam) -> str:
        record = chosen.get(param)
        return NOT_SHOWN if record is None else shown_value(record.value, record.unit, shown)

    target.road_class = str(chosen[RoadProfileParam.CLASS].value) if RoadProfileParam.CLASS in chosen else ""
    target.summary = tr("A {vehicle} · f {factor} · pd {pd} · pm {pm} · Rmin {rmin}",
                        vehicle=shown_of(RoadProfileParam.VEHICLE_WIDTH), factor=shown_of(RoadProfileParam.LANE_FACTOR),
                        pd=shown_of(RoadProfileParam.MAX_GRADIENT), pm=shown_of(RoadProfileParam.MAX_MEAN_GRADIENT),
                        rmin=shown_of(RoadProfileParam.MIN_RADIUS))
    target.badge = provenance.badge(min(kinds, key=FIRMNESS.index)) if kinds else ""
    target.scope = _scope_text(origins, version)
    target.derived = target.min_length = target.problem = ""
    try:
        profile = road_profiles.RoadProfile.from_values(
            row.code, row.name, {param.value: record.value for param, record in chosen.items()})
    except design_messages.DesignError as exc:  # le falta algo o no vale en la versión activa
        target.problem = design_error_text(exc)
        return
    derived = road_profiles.derived(profile)
    target.derived = tr("carriageway {carriageway} · section {section} · half-width {half_width}",
                        carriageway=_road_length(derived.carriageway_m), section=_road_length(derived.section_m),
                        half_width=_road_length(derived.half_width_m))
    target.min_length = tr("Minimum length H/pd: {length} per metre of height difference",
                           length=_road_length(derived.min_length_m(1.0)))


def fill_road_profiles(project: Any) -> int:
    """Regenera la lista de Perfil de pista… desde ``project`` (RF-017-07, RF-017-08): los perfiles del proyecto
    (``design.road_profiles.read_profiles``), cada uno con sus valores en la versión activa y en el proyecto, su fuente y sus derivados;
    conserva el elegido (por su código). Devuelve cuántos hay. Si no se puede leer, el error sigue y la vista queda como estaba."""
    from ...design import road_profiles  # al usarlo: habilitar no lo carga (RNF-001-03)

    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        raise RuntimeError("la vista de los perfiles de pista no está registrada")
    version = scene_versions.active()
    store = ParameterStore(project)
    old = shown.road_profiles
    chosen = old[shown.road_profile_index].code if 0 <= shown.road_profile_index < len(old) else ""
    with project.read() as conn:
        stored = road_profiles.read_profiles(conn)
        shown.road_profiles.clear()
        for row in stored:
            put_road_profile(shown.road_profiles.add(), row, store, conn, version)
    shown.road_profile_index = next((index for index, item in enumerate(shown.road_profiles) if item.code == chosen), 0)
    shown.road_profiles_project = project.uid
    return len(shown.road_profiles)


def choose_road(code: str) -> None:
    """Deja elegido en la lista de perfiles de pista el de código ``code`` (si está)."""
    shown = view()
    if shown is None:
        return
    for index, item in enumerate(shown.road_profiles):
        if item.code == code:
            shown.road_profile_index = index
            return


def show_road_report(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` (texto, si va en alerta) como el último resultado de la ventana de los perfiles de pista."""
    shown = view()
    if shown is None:
        return
    shown.road_profile_report.clear()
    for text, alert in lines:
        line = shown.road_profile_report.add()
        line.name, line.alert = text, alert


# --- Lo que se enseña de los sectores de diseño (T23) --------------------------------------------


def _label(idname: str) -> str:
    """La etiqueta del catálogo de comandos de la orden ``idname``, en el idioma de Geoblender."""
    return command_text(catalog().commands[idname].label)


def _scope_name(scope: str, version: Any) -> str:
    """De dónde sale un talud: «el proyecto» o el código de la versión activa."""
    return tr("the project") if scope == "project" or version is None else str(version.code)


def slope_text(record: Any) -> str:
    """El talud de un registro (``ParameterRecord``) como se lee: «10,6° [ADO]», y «sin confirmar»
    si lo está (los grados pegados al número, como los derivados de un perfil)."""
    shown = f"{format_value(float(record.value), language())}° {provenance.badge(record.kind)}"
    return f"{shown} {tr('unconfirmed')}" if record.unconfirmed else shown


def slope_texts(sector: DesignSector, version: Any) -> tuple[str, str, str]:
    """El talud general máximo que impone ``sector`` como se lee: ``(talud, origen, problema)``.
    El talud, con su tipo («10,6° [ADO]»); el origen, quién lo decidió y de qué ámbito sale
    («la propiedad · decidido por Samuel (IMGA) · V01»); el problema, un talud guardado fuera de
    (0; 90) ° (el dominio lo rechaza al usarlo: aquí se lista para corregirlo). Un sector sin fila
    o con la fila sin valor no impone ninguno: los tres, vacíos."""
    found = sector.slope
    if found is None or found.value is None:
        return "", "", ""
    problem = ""
    try:
        _ = sector.imposed_deg  # el dominio comprueba el rango y lanza si no vale
    except design_messages.DesignError as exc:
        problem = design_error_text(exc)
    record = found.record
    source = tr("{source} · decided by {who} · {scope}", source=record.source or NOT_SHOWN,
                who=record.decided_by, scope=_scope_name(found.scope, version))
    return slope_text(record), source, problem


def put_sector(target: Any, sector: DesignSector, state: Any | None, version: Any,
               profile: str, names: Mapping[str, str]) -> None:
    """Un sector de diseño (``design.sectors.DesignSector``) en la fila ``target`` de la vista: su
    nombre y su código, su área, el estado de su búsqueda (el de la 012 si se conoce, con quién la
    cerró y cuándo), su talud impuesto con su origen y el perfil asignado ``profile`` (su código;
    ``names`` da el nombre de cada perfil del proyecto). Nada se calcula aquí: es el dominio."""
    target.name = constraint_panels.sector_name(sector.code, sector.name)
    target.code = sector.code
    target.area = f"{format_number(sector.area_m2, 0)} m²"
    target.pending = sector.pending
    if state is not None:
        target.search = constraint_panels.sector_text(state.search)
    else:  # sin el estado de la 012 a mano: lo que dice el dominio
        target.search = tr("Search pending") if sector.pending else tr("Search in force")
    target.slope, target.slope_source, target.problem = slope_texts(sector, version)
    target.profile = profile
    target.profile_name = names.get(profile, profile) if profile else ""


def orphan_text(orphan: OrphanSlope) -> str:
    """Un talud de un sector que ya no existe, como se lee: «Talud de «sector_2» en V01: 12° [ADO]
    · la propiedad · decidido por Samuel (IMGA)». Nunca se borra (RF-013-10)."""
    sector = (tr("the action perimeter") if orphan.segment == PERIMETER_SEGMENT
              else orphan.segment)
    record = orphan.record
    scope = tr("the project") if orphan.scope == "project" else orphan.version
    value = NOT_SHOWN if record.value is None else slope_text(record)
    return tr("Slope of «{sector}» in {scope}: {value} · {source} · decided by {who}",
              sector=sector, scope=scope, value=value,
              source=record.source or NOT_SHOWN, who=record.decided_by)


def fill_sectors(project: Any) -> int:
    """Regenera la lista de Sectores de diseño… desde ``project`` (RF-013-07, RF-013-08,
    RF-013-10): los sectores de la 012 (o el perímetro como único sector) con su área, el estado
    de su búsqueda y el talud que imponen en la versión activa (``design.sectors.design_sectors``),
    y aparte los de los sectores que ya no existen (``orphan_slopes``); conserva el elegido y el
    perfil asignado a cada sector (por su código). Devuelve cuántos sectores hay. Si no se puede
    leer, el error sigue y la vista queda como estaba."""
    from ...design import sectors as design_sectors  # al usarlo: habilitar no carga el cálculo
    from ...gis.masks import access as mask_access  # ídem

    shown = view()
    if shown is None:  # inalcanzable con la extensión registrada
        raise RuntimeError("la vista de los sectores de diseño no está registrada")
    version = scene_versions.active()
    uid = None if version is None else version.uid
    found = design_sectors.design_sectors(project, uid)
    states = {state.code: state for state in mask_access.sector_states(project, uid)}
    orphans = design_sectors.orphan_slopes(project, found)
    with project.read() as conn:
        names = design_profiles.profile_names(conn)
    old = shown.sectors
    chosen = old[shown.sector_index].code if 0 <= shown.sector_index < len(old) else None
    assigned = {item.code: item.profile for item in old if item.profile}
    marks = {item.code: (bool(item.use), item.profile_pick, item.final_pick,
                         item.exploitation_pick) for item in old}
    shown.sectors.clear()
    for sector in found:
        row = shown.sectors.add()
        put_sector(row, sector, states.get(sector.code), version,
                   assigned.get(sector.code, ""), names)
        use, pick, final, exploitation = marks.get(sector.code, (False, "", "", ""))
        row.use, row.profile_pick = use, pick or row.profile_name
        row.final_pick, row.exploitation_pick = final, exploitation  # la cantera (014, T21)
    shown.sector_index = next((index for index, item in enumerate(shown.sectors)
                               if item.code == chosen), 0)
    shown.orphans.clear()
    for orphan in orphans:
        line = shown.orphans.add()
        line.name, line.alert = orphan_text(orphan), True
    shown.sectors_project = project.uid
    return len(shown.sectors)


def fill_sector_sources(project: Any) -> None:
    """Las capas de polígonos del proyecto de las que se pueden declarar de nuevo los sectores, en
    la vista de la 012 (``sector_sources``: la declaración es suya, ``core_declare_sectors``)."""
    other = constraint_panels.view()
    if other is None:
        return
    other.sector_sources.clear()
    for name in constraint_panels.polygon_layers(project):
        other.sector_sources.add().name = name


def choose_sector(code: str) -> None:
    """Deja elegido en la lista el sector de código ``code`` (si está)."""
    shown = view()
    if shown is None:
        return
    for index, item in enumerate(shown.sectors):
        if item.code == code:
            shown.sector_index = index
            return


def assign_profiles(project: Any, assigned: Mapping[str, str]) -> None:
    """Pone a cada sector el perfil de banco de la superficie en preparación (RF-013-21):
    ``assigned`` da el código del perfil de cada código de sector (el perímetro, ``""``); un sector
    que no está, sin perfil. La ventana de las envolventes lo llama al elegir los perfiles; las
    lecturas de los sectores lo conservan."""
    shown = view()
    if shown is None:
        return
    with project.read() as conn:
        names = design_profiles.profile_names(conn)
    for item in shown.sectors:
        code = assigned.get(item.code, "")
        item.profile = code
        item.profile_name = names.get(code, code) if code else ""
        item.profile_pick = item.profile_name


def show_sector_report(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` (texto, si va en alerta) como el último resultado de la ventana de los
    sectores."""
    shown = view()
    if shown is None:
        return
    shown.sector_report.clear()
    for message, alert in lines:
        line = shown.sector_report.add()
        line.name, line.alert = message, alert


# --- Envolventes y escalonado… (T24; HU-013-1, HU-013-3, HU-013-5; RF-013-21, RF-013-31) --------

NO_ZONE = "none"
DOMAIN_ZONE = "domain"
CONSTRAINT_ZONE = "constraint:"
SECTOR_ZONE = "sector:"
LAYER_ZONE = "layer:"
NO_ANCHOR = "none"
NO_LAYER = "none"
"""Los identificadores de las opciones de las listas del diálogo: sin zona (toda la superficie),
el dominio por defecto de las máscaras, y el prefijo de una restricción, un sector o una capa (con
su código o su nombre detrás); sin rejilla de anclas (la del perfil); sin capa."""


@dataclass
class _Choices:
    """Las listas del diálogo ya leídas del proyecto (vivas: ``EnumProperty`` conserva sus textos,
    ``docs/trampas.md`` §3), las superficies por su identificador (su nombre; T45) y la clave de lo
    que se leyó."""

    surfaces: list[tuple[str, str, str]] = field(default_factory=list)
    anchors: list[tuple[str, str, str]] = field(default_factory=list)
    zones: list[tuple[str, str, str]] = field(default_factory=list)
    layers: list[tuple[str, str, str]] = field(default_factory=list)
    optional_layers: list[tuple[str, str, str]] = field(default_factory=list)
    lines: list[tuple[str, str, str]] = field(default_factory=list)
    conserve: list[tuple[str, str, str]] = field(default_factory=list)
    designs: list[tuple[str, str, str]] = field(default_factory=list)
    envelopes: list[tuple[str, str, str]] = field(default_factory=list)
    platform_layers: list[tuple[str, str, str]] = field(default_factory=list)
    platform_kinds: dict[str, str] = field(default_factory=dict)
    platform_starts: list[tuple[str, str, str]] = field(default_factory=list)
    platform_supports: list[tuple[str, str, str]] = field(default_factory=list)
    platform_names: list[str] = field(default_factory=list)
    platform_start: str | None = None
    removal_stockpiles: list[tuple[str, str, str]] = field(default_factory=list)
    removal_by_ref: dict[str, StockpileChoice] = field(default_factory=dict)
    body_footprints: list[tuple[str, str, str]] = field(default_factory=list)
    body_data: list[tuple[str, str, str]] = field(default_factory=list)
    body_kinds: dict[str, str] = field(default_factory=dict)
    buttress_zones: list[tuple[str, str, str]] = field(default_factory=list)
    buttress_supports: list[tuple[str, str, str]] = field(default_factory=list)
    road_points: list[tuple[str, str, str]] = field(default_factory=list)
    road_lines: list[tuple[str, str, str]] = field(default_factory=list)
    road_lines_3d: list[tuple[str, str, str]] = field(default_factory=list)
    road_profiles: list[tuple[str, str, str]] = field(default_factory=list)
    road_roads: list[tuple[str, str, str]] = field(default_factory=list)
    road_platforms: list[tuple[str, str, str]] = field(default_factory=list)
    road_zones: list[tuple[str, str, str]] = field(default_factory=list)
    road_start: str | None = None
    access_layers: list[tuple[str, str, str]] = field(default_factory=list)
    access_surface: str | None = None
    by_id: dict[str, res_surfaces.SurfaceChoice] = field(default_factory=dict)
    key: tuple[str, str, str] | None = None


_CHOICES = _Choices()


@dataclass
class _Resting:
    """Lo que dice el diálogo de «Retirar un acopio…» de **lo que se le apoya** al acopio elegido, leído **antes de calcular** (spec 016,
    T20 (b); RF-016-14): sus líneas ya traducidas, cada una con si va en alerta; vacío, nada que enseñar (sin acopio o sin partida)."""

    lines: list[tuple[str, bool]] = field(default_factory=list)


_RESTING = _Resting()


@dataclass(frozen=True, slots=True)
class AccessRow:
    """Una fila de las listas de «Accesibilidad de las pistas…» (spec 017, T30; RF-017-25): su ``text`` (ya traducido), si va en ``alert`` (no queda comunicado) y el lugar de su «Ir a» (``place``: la ``x`` y
    la ``y`` absolutas y el radio, en metros y en texto que se lee sin pérdida, ADR-0005; ``None`` si no tiene lugar)."""

    text: str
    alert: bool = False
    place: tuple[str, str, str] | None = None


@dataclass(frozen=True, slots=True)
class AccessSection:
    """Una de las tres listas (tramos de berma, plataformas y zonas «requiere acceso»): su ``title``, las ``rows`` que caben en la ventana —**las que no se comunican, antes**— y ``more``, cuántas faltan."""

    title: str
    rows: tuple[AccessRow, ...]
    more: int = 0


@dataclass
class _AccessLists:
    """Las listas del cálculo abierto de una accesibilidad (:func:`show_access`), ya leídas y traducidas: la ventana de crear las dibuja (:func:`draw_access_lists`) sin volver a calcularlas en cada dibujo."""

    sections: list[AccessSection] = field(default_factory=list)


_ACCESS = _AccessLists()


def _fixed_choices() -> None:
    """Las listas sin nada del proyecto: sin superficies, sin rejilla de anclas, sin capa y las
    zonas que no dependen de él; las capas que la cantera puede no usar, solo «ninguna»."""
    _CHOICES.surfaces = [(NO_ZONE, NOT_SHOWN, tr("There are no grids in the project"))]
    _CHOICES.by_id = {}
    _CHOICES.anchors = [(NO_ANCHOR, tr("The anchor of the profile"),
                         tr("Anchor the benches to the elevation of the profile"))]
    _CHOICES.zones = [(NO_ZONE, tr("The whole surface"),
                       tr("Seeds in every cell of the surface with an elevation")),
                      (DOMAIN_ZONE, tr("The default domain"),
                       tr("The cells of the default work domain of the masks"))]
    _CHOICES.layers = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of polygons in the project"))]
    _CHOICES.optional_layers = [(NO_LAYER, tr("No layer"), tr("Without this layer"))]
    _CHOICES.lines = [(NO_LAYER, tr("No layer"), tr("Without this layer"))]
    _CHOICES.conserve = [(NO_ZONE, tr("No zone"), tr("No zone to conserve"))]
    _CHOICES.designs = [(NO_ZONE, NOT_SHOWN,
                         tr("There are no design surfaces in the active version"))]
    _CHOICES.envelopes = [(NO_ZONE, NOT_SHOWN, tr("There are no envelopes in the active version"))]
    _fixed_choices_platform()


DESIGN_SURFACE_PREFIXES: tuple[str, ...] = tuple(
    family.prefix for family in (*design_provenance.FAMILIES, *design_provenance.QUARRY_FAMILIES)
    if family.role == design_provenance.DESIGN_SURFACE_ROLE)
"""El comienzo del nombre de las superficies de diseño (las familias con el papel
``design_surface``: la de un escalonado de la 013, las dos de una cantera, la transición y la
ajustada de la 014)."""


CODE_GRID_PREFIXES: tuple[str, ...] = (
    *(design_provenance.FAMILIES_BY_CODE[code].prefix for code in (
        design_provenance.EXCAVATION_AREA_GRID, design_provenance.CLASSIFICATION_GRID)),
    masks_provenance.dataset_name(masks_provenance.CLASSES))
"""El comienzo del nombre de las rejillas de **códigos**, que no son cotas y no se ofrecen como
superficie ni como rejilla de anclas (spec 014, T61; el H3: la de las semillas proponía la
clasificación la primera): el recinto excavable (1 dentro), la clasificación de una cantera (0, 1
o 2) y la rejilla de clases de las máscaras de la 012 (sus bits)."""


def line_layers(project: Any) -> tuple[str, ...]:
    """Las capas «entidades» de líneas del proyecto (``gis_fea_``), por nombre: los ejes de los
    corredores de la cantera (spec 014, T21; plan 014 §5.2.1). Una cuya tabla falta no se
    ofrece."""
    records = gis_store.list_gis_datasets(project, families=(gis_provenance.FEATURES,))
    found: list[str] = []
    for record in records:
        try:
            source = gis_store.feature_source(project, record)
        except (GeoblenderError, ValueError):
            LOGGER.warning("La capa «%s» no se ofrece a la cantera", record.name, exc_info=True)
            continue
        if source.kind == "line":
            found.append(source.name)
    return tuple(sorted(found))


def refresh_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` las listas del diálogo, con la versión activa: las superficies
    y rejillas de cotas del proyecto y de la versión activa (las que puede leer el cálculo: no las
    congeladas ni las de otra versión, ni las de códigos, :data:`CODE_GRID_PREFIXES`), las zonas
    (el dominio por defecto, las restricciones, los sectores declarados y las capas de polígonos)
    y las capas con que se acota el dominio. Si no se puede leer, el error sigue y las listas
    quedan como estaban."""
    version = scene_versions.active_version() or ""
    found = [choice for choice in res_surfaces.surface_choices(project, version_uid=version)
             if choice.revision is None and not choice.name.startswith(CODE_GRID_PREFIXES)]
    envelope_prefix = design_provenance.FAMILIES_BY_CODE[design_provenance.ENVELOPE_GRID].prefix
    with project.read() as conn:
        # Las restricciones del proyecto y las que declaran las entidades de la versión activa (spec
        # 015, T21; RF-012-18): cada una con su nombre (la declarada, por su entidad, no por su código).
        constraints = constraint_views.shown_names(conn, version)
        envelopes = _envelope_names(conn, [choice for choice in found if choice.version_uid
                                           and choice.name.startswith(envelope_prefix)])
    layers = constraint_panels.polygon_layers(project)
    lines = line_layers(project)
    shown = view()
    sectors = [] if shown is None else [(item.code, item.name) for item in shown.sectors
                                        if item.code]
    _fixed_choices()
    if found:
        of_version, of_project = tr("A grid of the active version"), tr("A grid of the project")
        _CHOICES.surfaces = [(choice.name, choice.name,
                              of_version if choice.version_uid else of_project)
                             for choice in found]
        _CHOICES.by_id = {choice.name: choice for choice in found}
    _CHOICES.anchors = [*_CHOICES.anchors, *_CHOICES.surfaces] if found else _CHOICES.anchors
    _CHOICES.zones = [
        *_CHOICES.zones,
        *((CONSTRAINT_ZONE + code, name or code,
           tr("Zone of a constraint declared by an entity") if is_declared_code(code)
           else tr("Zone of a constraint")) for code, (name, _ctype) in constraints.items()),
        *((SECTOR_ZONE + code, name, tr("Design sector")) for code, name in sectors),
        *((LAYER_ZONE + name, constraint_panels.layer_label(name), tr("Layer of polygons"))
          for name in layers)]
    if layers:
        _CHOICES.layers = [(name, constraint_panels.layer_label(name), tr("Layer of polygons"))
                           for name in layers]
    # La cantera (spec 014, T21): sus capas de polígonos y de líneas, que puede no usar, y sus
    # zonas a conservar (una restricción o una capa de polígonos, RF-014-07).
    _CHOICES.optional_layers = [*_CHOICES.optional_layers, *(
        (name, constraint_panels.layer_label(name), tr("Layer of polygons")) for name in layers)]
    _CHOICES.lines = [*_CHOICES.lines, *(
        (name, constraint_panels.layer_label(name), tr("Layer of lines")) for name in lines)]
    _CHOICES.conserve = [*_CHOICES.conserve, *(
        item for item in _CHOICES.zones
        if item[0].startswith((CONSTRAINT_ZONE, LAYER_ZONE)))]
    # Las transiciones (spec 014, T28): las superficies de diseño de la versión activa.
    designs = [(choice.name, choice.name, tr("A design surface of the active version"))
               for choice in found
               if choice.version_uid and choice.name.startswith(DESIGN_SURFACE_PREFIXES)]
    if designs:
        _CHOICES.designs = designs
    # «Solo relleno…» (spec 014, T30): las envolventes de la versión activa, por el nombre de su
    # operación (el que escalona, como el escalonado de la 013).
    if envelopes:
        _CHOICES.envelopes = [(name, name, tr("An envelope of the active version"))
                              for name in envelopes]
    _CHOICES.key = (project.uid, version, language())


def _envelope_names(conn: sqlite3.Connection, choices: Sequence[res_surfaces.SurfaceChoice]
                    ) -> list[str]:
    """El nombre de la operación de cada envolvente de ``choices`` (los datos ``des_env_`` de la
    versión activa), de los ajustes de la operación que la escribió, sin repetir y en su orden;
    una cuyos ajustes no lo llevan no se ofrece. Solo lee."""
    found: list[str] = []
    for choice in choices:
        row = conn.execute("SELECT o.settings FROM gb_dataset AS d JOIN gb_operation AS o "
                           "ON o.uid = d.operation_uid WHERE d.uid = ?", (choice.uid,)).fetchone()
        try:
            settings = json.loads(str(row[0])) if row is not None and row[0] else None
        except ValueError:
            settings = None
        name = settings.get("name") if isinstance(settings, dict) else None
        if isinstance(name, str) and name.strip() and name not in found:
            found.append(name)
    return found


def _ensure_choices() -> None:
    """Las listas del proyecto de la sesión y su versión activa (las lee si son de otro, una vez:
    ``invoke`` las vuelve a leer siempre); sin proyecto, las que no dependen de él."""
    project = project_session.current()
    if project is None:
        if not _CHOICES.zones:
            _fixed_choices()
        return
    key = (project.uid, scene_versions.active_version() or "", language())
    if key == _CHOICES.key:
        return
    try:
        refresh_choices(project)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.warning("No se pudieron leer las listas de envolventes y escalonado", exc_info=True)
        _fixed_choices()
        _CHOICES.key = key  # sin volver a intentarlo en cada dibujo: invoke las relee


def surface_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las superficies y rejillas de cotas que ofrece el diálogo (``EnumProperty``): una lista viva
    del módulo."""
    _ensure_choices()
    return _CHOICES.surfaces


def anchor_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las opciones del ancla del escalonado: el ancla de cada perfil o una rejilla de anclas del
    proyecto o de la versión activa (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.anchors


def zone_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las zonas de las semillas: toda la superficie, el dominio por defecto, una restricción, un
    sector o una capa de polígonos (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.zones


def layer_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de polígonos con que se acota el dominio de trabajo (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.layers


def optional_layer_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Una capa de polígonos de la cantera que puede no usarse (los fondos, las zonas de relleno,
    las láminas de agua; spec 014, T21): «ninguna capa» y las capas de polígonos del proyecto (una
    lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.optional_layers


def line_layer_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """La capa de líneas de los corredores de la cantera (spec 014, T21): «ninguna capa» y las
    capas de líneas del proyecto (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.lines


def conserve_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """La zona a conservar de la cantera (spec 014, T21; RF-014-07): ninguna, una restricción o
    una capa de polígonos (con los identificadores de :func:`zone_items`; una lista viva del
    módulo)."""
    _ensure_choices()
    return _CHOICES.conserve


def design_surface_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las superficies de diseño de la versión activa que ofrece «Transiciones con el terreno no
    afectado» (spec 014, T28; plan 014 §5.2.3: :data:`DESIGN_SURFACE_PREFIXES`), con el nombre de
    su dato como identificador (el de :func:`surface_items`); sin ninguna, «—» (una lista viva del
    módulo)."""
    _ensure_choices()
    return _CHOICES.designs


def envelope_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las envolventes de la versión activa que ofrece «Solo relleno…» (spec 014, T30; plan 014
    §5.3.3: el escalonado en relleno de una envolvente, como la 013), con el nombre de su
    operación como identificador; sin ninguna, «—» (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.envelopes


def _platform_entities(project: Any, version: str) -> tuple[list[tuple[str, str, str]], list[str],
                                                           str | None]:
    """Las plataformas de la versión ``version`` (uid): las superficies de las calculadas como
    ``entity:<código>`` (con su nombre y si es la última de su cadena), los nombres de todas (la
    propuesta del nombre de la nueva no repite ninguno) y la última de la cadena (:func:`platform_default_start`;
    ``None`` sin ninguna). Una cadena que da la vuelta (un dato roto) no ofrece cola."""
    from ...design import entities  # al usarlo: habilitar no carga las entidades

    if not version:
        return [], [], None
    registry = entities.registry(project, version)
    try:
        tails = [record.code for record in entities.chain_tails(registry.records)]
    except design_messages.DesignError:
        LOGGER.warning("Una cadena de entidades no tiene cola: no se propone partida", exc_info=True)
        tails = []
    items: list[tuple[str, str, str]] = []
    for entry in registry:
        record = entry.record
        if record.state in (entities.EntityState.UNCALCULATED, entities.EntityState.DISCARDED):
            continue  # sin superficie que leer
        spec = entities.entity_type(record.kind)
        if spec.surface_role is None:
            continue  # un tipo que no deja una superficie (la detección de acopios, spec 016): no es una partida
        if record.kind == entities.EntityKind.BODY and record.start is None:
            continue  # un cuerpo «bajo un techo» no cambia la superficie y no la escribe: nadie parte de ella (spec 016, T25)
        last = record.code in tails
        if record.kind == entities.EntityKind.PLATFORM:
            label = tr("Platform «{name}» ({code})", name=record.name, code=record.code)
            about = (tr("Surface of the platform, the last of its chain") if last
                     else tr("Surface of a platform that another one starts from"))
        else:  # el tipo de la 016 (una retirada…): su nombre visible, el de su operación
            label = tr("{kind} «{name}» ({code})", kind=entities.kind_label(spec.op_type, language()), name=record.name,
                       code=record.code)
            about = (tr("Surface of the entity, the last of its chain") if last
                     else tr("Surface of an entity that another one starts from"))
        items.append((entities.surface_ref(record.code), label, about))
    usable = {item[0] for item in items}
    start = next((entities.surface_ref(code) for code in reversed(tails)
                  if entities.surface_ref(code) in usable), None)
    return items, [entry.record.name for entry in registry], start


def _cyclic_supports(project: Any, version: str, insert_before: str | None) -> set[str]:
    """Las superficies (``entity:<código>``) en las que una plataforma **nueva** que se inserta antes de la entidad
    ``insert_before`` no puede apoyarse (spec 015, T39; hallazgo A-1): esa entidad y las que la siguen, que pasarán a
    partir de la nueva (``design.entities.unsupportable``: sería un ciclo). Vacío sin versión ni inserción."""
    from ...design import entities  # al usarlo: habilitar no carga las entidades

    if not version or not insert_before:
        return set()
    records = entities.registry(project, version).records
    new = entities.next_code(entities.EntityKind.PLATFORM, (item.code for item in records))
    try:
        return {entities.surface_ref(code)
                for code in entities.unsupportable(records, new, insert_before=insert_before)}
    except design_messages.DesignError:  # una cadena rota (un dato roto): lo rechaza «Calcular», con su texto
        LOGGER.warning("Una cadena de entidades está rota: no se filtran los apoyos", exc_info=True)
        return set()


def refresh_platform_choices(project: Any, *, insert_before: str | None = None) -> None:
    """Vuelve a leer de ``project`` las listas del diálogo de «Plataforma…» (spec 015, T15; plan 015
    §5.3.3): las capas «entidades» de líneas o de polígonos (:func:`platform_layer_items`, con su
    geometría: :func:`platform_layer_kind`), las superficies de partida (:func:`platform_start_items`:
    las plataformas calculadas de la versión activa como ``entity:<código>`` y, después, las superficies y
    rejillas de cotas de :func:`surface_items` sin las de las plataformas, que se eligen por su
    entidad para que la cadena las conozca), la última de su cadena como la propuesta
    (:func:`platform_default_start`) y las de apoyo (:func:`platform_support_items`: «ninguna» y las
    mismas, **sin las que serían un ciclo**: con ``insert_before`` —la entidad ante la que se inserta la nueva—, esa y
    las que la siguen, T39, hallazgo A-1). Se llama tras :func:`refresh_choices`. Si no se puede leer, el error
    sigue."""
    _ensure_choices()
    version = scene_versions.active_version() or ""
    layers = [(name, kind) for name, kind in constraint_panels.search_layers(project)
              if kind in ("line", "polygon")]
    entities, names, last = _platform_entities(project, version)
    prefix = design_provenance.FAMILIES_BY_CODE[design_provenance.ENTITY_SURFACE_GRID].prefix
    surfaces = [item for item in _CHOICES.surfaces
                if item[0] == NO_ZONE or not item[0].startswith(prefix)]
    starts = [*entities, *(item for item in surfaces if item[0] != NO_ZONE)]
    _fixed_choices_platform()
    if layers:
        _CHOICES.platform_layers = [
            (name, constraint_panels.layer_label(name),
             tr("Layer of lines") if kind == "line" else tr("Layer of polygons"))
            for name, kind in layers]
        _CHOICES.platform_kinds = dict(layers)
    if starts:
        cyclic = _cyclic_supports(project, version, insert_before)
        _CHOICES.platform_starts = starts
        _CHOICES.platform_supports = [*_CHOICES.platform_supports,
                                      *(item for item in starts if item[0] not in cyclic)]
    _CHOICES.platform_names, _CHOICES.platform_start = names, last


def _fixed_choices_platform() -> None:
    """Las listas de «Plataforma…» sin nada del proyecto (:func:`_fixed_choices` la llama; sin capas, sin
    superficies, sin plataformas): «—» y «sin apoyo»."""
    _CHOICES.platform_layers = [(NO_LAYER, NOT_SHOWN,
                                 tr("There are no layers of lines or polygons in the project"))]
    _CHOICES.platform_kinds = {}
    _CHOICES.platform_starts = [(NO_ZONE, NOT_SHOWN, tr("There are no grids in the project"))]
    _CHOICES.platform_supports = [(NO_ZONE, tr("No support surface"),
                                   tr("The platform rests on no other surface"))]
    _CHOICES.platform_names, _CHOICES.platform_start = [], None


def platform_layer_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de líneas o de polígonos que ofrece «Plataforma…» (spec 015, T15; plan 015 §5.2.1; una
    lista viva del módulo); sin ninguna, «—»."""
    _ensure_choices()
    return _CHOICES.platform_layers


def platform_layer_kind(layer: str) -> str | None:
    """La geometría (``"line"`` o ``"polygon"``) de la capa ``layer`` de la lista de :func:`platform_layer_items`;
    ``None`` si no es de la lista."""
    _ensure_choices()
    return _CHOICES.platform_kinds.get(layer)


def platform_start_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las superficies de partida de una plataforma (spec 015, T15; plan 015 §5.3.3): las plataformas de la
    versión activa y las superficies y rejillas de cotas (una lista viva del módulo)."""
    _ensure_choices()
    return _CHOICES.platform_starts


def platform_support_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las superficies de apoyo de una plataforma (spec 015, T15): «ninguna» y las de partida (una lista
    viva del módulo)."""
    _ensure_choices()
    return _CHOICES.platform_supports


def platform_default_start() -> str | None:
    """La superficie de partida que propone el diálogo de «Plataforma…»: **la última de la cadena** de la
    versión activa (la de la plataforma que ninguna otra tiene como partida, ``entity:PLT-001``); ``None`` sin
    plataformas calculadas (parte del terreno o de una superficie de diseño: lo propone el diálogo con la
    selección de la vista)."""
    return _CHOICES.platform_start


def platform_names() -> list[str]:
    """Los nombres de las plataformas de la versión activa (los leyó :func:`refresh_platform_choices`)."""
    return list(_CHOICES.platform_names)


def _fixed_choices_removal() -> None:
    """La lista de «Retirar un acopio…» sin nada del proyecto: «—» (sin ninguna detección de acopios)."""
    _CHOICES.removal_stockpiles = [(NO_ZONE, NOT_SHOWN, tr("There is no detection of stockpiles in the project or in the active "
                                                           "version"))]
    _CHOICES.removal_by_ref = {}


def _stockpile_label(item: StockpileChoice) -> str:
    """Lo que dice la lista del acopio ``item``: su nombre y su detección, y «obsoleta» si lo está."""
    if item.state == "stale":
        return tr("{name} ({detection}) · detection out of date", name=item.name, detection=item.detection)
    return tr("{name} ({detection})", name=item.name, detection=item.detection)


def _stockpile_about(item: StockpileChoice) -> str:
    """La descripción del acopio ``item`` en la lista: su detección y de dónde es, su volumen y su área; la obsoleta, lo que hay que hacer."""
    where = tr("of the project") if item.scope == "project" else tr("of the active version")
    about = tr("Stockpile of the detection «{detection}» ({code}) {where}: {volume} m³ in {area} m²",
               detection=item.detection_name, code=item.detection, where=where, volume=_number(item.volume_m3),
               area=_number(item.area_m2))
    if item.state == "stale":
        return f"{about}. " + tr("The detection is out of date: recompute it before removing the stockpile")
    return about


def refresh_removal_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` los acopios que ofrece «Retirar un acopio…» (spec 016, T20 (b); plan 016 §5.3.3:
    ``design.supported_store.removable_stockpiles``: los de las detecciones de la versión activa y del proyecto, con la obsoleta marcada) y
    los guarda para :func:`removal_stockpile_items` y :func:`removal_stockpile`. Sin versión activa, ninguno. Si no se puede leer, el error
    sigue y la lista queda vacía."""
    from ...design import supported_store  # al usarlo: habilitar no carga el cálculo

    _fixed_choices_removal()
    version = scene_versions.active_version() or ""
    found = supported_store.removable_stockpiles(project, version) if version else ()
    if found:
        _CHOICES.removal_stockpiles = [(item.ref, _stockpile_label(item), _stockpile_about(item)) for item in found]
        _CHOICES.removal_by_ref = {item.ref: item for item in found}


def removal_stockpile_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Los acopios que ofrece «Retirar un acopio…» (spec 016, T20 (b); una lista viva del módulo); sin ninguno, «—»."""
    if not _CHOICES.removal_stockpiles:
        _fixed_choices_removal()
    return _CHOICES.removal_stockpiles


def removal_stockpile(ref: str) -> StockpileChoice | None:
    """El acopio ofrecido de referencia ``ref`` (``STK-001#Acopio 1``) o ``None`` si la lista no lo tiene."""
    return _CHOICES.removal_by_ref.get(ref)


def has_removal_stockpiles() -> bool:
    """Si la lista de «Retirar un acopio…» ofrece algún acopio."""
    return bool(_CHOICES.removal_by_ref)


def show_resting(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` (texto ya traducido y si va en alerta) como lo que dice el diálogo de «Retirar un acopio…» de lo que se apoya en el
    acopio elegido (RF-016-14); sin líneas, lo vacía."""
    _RESTING.lines = list(lines)


def resting_lines() -> list[tuple[str, bool]]:
    """Lo que dice ahora el diálogo de lo que se apoya en el acopio elegido (:func:`show_resting`)."""
    return list(_RESTING.lines)


def draw_resting(layout: Any, width_px: int) -> None:
    """La lista de lo que se apoya en el acopio elegido (spec 016, T20 (b); RF-016-14, A7: **una sola lista, antes de calcular**) en un diálogo
    de ``width_px``: su título y cada línea partida al ancho, en ámbar lo que se apoya y lo que no se pudo leer."""
    if not _RESTING.lines:
        return
    width = labels.dialog_width(width_px)
    box = layout.box()
    box.label(text=tr("What rests on the stockpile"), translate=False)
    for text, alert in _RESTING.lines:
        _draw_text(box, text, width, alert=alert)


def _fixed_choices_body() -> None:
    """Las listas de «Cuerpo apoyado…» sin nada del proyecto: «—» (sin capas de huellas ni de datos)."""
    _CHOICES.body_footprints = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of polygons in the project"))]
    _CHOICES.body_data = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of points, polygons or 3D lines in the project"))]
    _CHOICES.body_kinds = {}


def refresh_body_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` las capas que ofrece «Cuerpo apoyado…» (spec 016, T25; plan 016 §5.2.1 y §5.3.3): para la huella, las
    capas «entidades» de **polígonos** (``gis_fea_``) y, para los datos de espesor, las de **puntos** o de **polígonos** (el espesor de
    un campo) y las de **líneas 3D** (``gis_brk_``: el espesor en la Z de sus vértices), cada una con su geometría
    (:func:`body_data_kind`). Si no se puede leer, el error sigue."""
    _fixed_choices_body()
    found = constraint_panels.search_layers(project)
    polygons = [name for name, kind in found if kind == "polygon"]
    data = [(name, kind) for name, kind in found if kind in ("point", "polygon")]
    lines = [record.name for record in gis_store.list_gis_datasets(project, families=(gis_provenance.BREAKLINES,))]
    if polygons:
        _CHOICES.body_footprints = [(name, constraint_panels.layer_label(name), tr("Layer of polygons")) for name in polygons]
    if data or lines:
        kinds = {"point": tr("Layer of points"), "polygon": tr("Layer of polygons")}
        _CHOICES.body_data = [*((name, constraint_panels.layer_label(name), kinds[kind]) for name, kind in data),
                              *((name, constraint_panels.layer_label(name), tr("Layer of 3D lines")) for name in sorted(lines))]
        _CHOICES.body_kinds = {**dict(data), **{name: "line3d" for name in lines}}


def body_footprint_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de polígonos que ofrece «Cuerpo apoyado…» para la huella (spec 016, T25; una lista viva del módulo); sin ninguna, «—»."""
    if not _CHOICES.body_footprints:
        _fixed_choices_body()
    return _CHOICES.body_footprints


def body_data_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de datos de espesor que ofrece «Cuerpo apoyado…» (spec 016, T25; una lista viva del módulo); sin ninguna, «—»."""
    if not _CHOICES.body_data:
        _fixed_choices_body()
    return _CHOICES.body_data


def body_data_kind(layer: str) -> str | None:
    """La geometría de la capa de datos ``layer`` de la lista de :func:`body_data_items`: ``"point"``, ``"polygon"`` o ``"line3d"``;
    ``None`` si no es de la lista."""
    return _CHOICES.body_kinds.get(layer)


def has_body_footprints() -> bool:
    """Si la lista de «Cuerpo apoyado…» ofrece alguna capa de huellas."""
    return any(item[0] != NO_LAYER for item in _CHOICES.body_footprints)


def _fixed_choices_buttress() -> None:
    """Las listas de «Contrafuerte…» sin nada del proyecto: «—» (sin capas de zonas de coronación) y «sin apoyo»."""
    _CHOICES.buttress_zones = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of polygons in the project"))]
    _CHOICES.buttress_supports = [(NO_ZONE, tr("No support surface"), tr("The buttress rests on no other surface"))]


def refresh_buttress_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` las listas de «Contrafuerte…» (spec 016, T27; plan 016 §5.2.1 y §5.3.3): las capas «entidades» de
    **polígonos** (``gis_fea_``) para la zona de coronación y las superficies de apoyo (**«sin apoyo»** y las mismas de partida de
    :func:`platform_start_items`: la superficie de la cantera de la 014, las de diseño y las de las entidades de la cadena). La partida y
    sus entidades son las de :func:`refresh_platform_choices`, que se llama antes. Si no se puede leer, el error sigue."""
    _fixed_choices_buttress()
    polygons = [name for name, kind in constraint_panels.search_layers(project) if kind == "polygon"]
    if polygons:
        _CHOICES.buttress_zones = [(name, constraint_panels.layer_label(name), tr("Layer of polygons")) for name in polygons]
    starts = [item for item in _CHOICES.platform_starts if item[0] != NO_ZONE]
    _CHOICES.buttress_supports = [*_CHOICES.buttress_supports, *starts]


def buttress_zone_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de polígonos que ofrece «Contrafuerte…» para la zona de coronación (spec 016, T27; una lista viva del módulo); sin
    ninguna, «—»."""
    if not _CHOICES.buttress_zones:
        _fixed_choices_buttress()
    return _CHOICES.buttress_zones


def buttress_support_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las superficies de apoyo de «Contrafuerte…» (spec 016, T27): «sin apoyo» —se apoya en la de partida— y las superficies de partida
    (una lista viva del módulo)."""
    if not _CHOICES.buttress_supports:
        _fixed_choices_buttress()
    return _CHOICES.buttress_supports


def has_buttress_zones() -> bool:
    """Si la lista de «Contrafuerte…» ofrece alguna capa de zonas de coronación."""
    return any(item[0] != NO_LAYER for item in _CHOICES.buttress_zones)


def _fixed_choices_road() -> None:
    """Las listas de «Pista…» sin nada del proyecto: «—» (sin capas, sin perfiles, sin pistas ni plataformas calculadas)."""
    _CHOICES.road_points = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of points in the project"))]
    _CHOICES.road_lines = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of lines in the project"))]
    _CHOICES.road_lines_3d = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of 3D lines in the project, nor proposed routes in the active version"))]
    _CHOICES.road_profiles = [(NO_ZONE, NOT_SHOWN, tr("There are no road profiles in the project: create one with «Road profile…»"))]
    _CHOICES.road_roads = [(NO_ZONE, NOT_SHOWN, tr("There are no calculated roads in the active version"))]
    _CHOICES.road_platforms = [(NO_ZONE, NOT_SHOWN, tr("There are no calculated platforms in the active version"))]
    _CHOICES.road_zones = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of polygons in the project"))]
    _CHOICES.road_start = None


def _road_entities(project: Any, version: Any) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Las pistas y las plataformas **calculadas y vivas** de la versión ``version`` (RF-017-03): el eje de una pista es el origen posible de otra y la
    plataforma, su destino posible. Cada una, por su código (``RDW-001``, ``PLT-001``) con su nombre. Solo lee."""
    from ...design import entities  # al usarlo: habilitar no carga las entidades

    roads: list[tuple[str, str, str]] = []
    platforms: list[tuple[str, str, str]] = []
    for entry in entities.registry(project, version.uid):
        record = entry.record
        if record.state in (entities.EntityState.UNCALCULATED, entities.EntityState.DISCARDED):
            continue
        if record.kind == entities.EntityKind.ROAD:
            roads.append((record.code, tr("Road «{name}» ({code})", name=record.name, code=record.code),
                          tr("Road of the active version whose axis another road can start from")))
        elif record.kind == entities.EntityKind.PLATFORM:
            platforms.append((record.code, tr("Platform «{name}» ({code})", name=record.name, code=record.code),
                              tr("Platform of the active version a road can end at")))
    return roads, platforms


def _proposed_routes(project: Any, version_uid: str) -> list[str]:
    """Los nombres de los datos de las **rutas propuestas** (``des_rpl_``: líneas con Z, spec 017 D-19) vigentes de la versión ``version_uid``: el modo «eje 3D»
    las ofrece junto a las líneas de rotura. Solo lee."""
    from ...core.datasets.model import DatasetStatus  # al usarlo: habilitar no lo carga

    prefix = design_provenance.FAMILIES_BY_CODE[design_provenance.ROUTE_LAYER_TABLE].prefix
    with project.read() as conn:
        rows = conn.execute("SELECT name FROM gb_dataset WHERE version_uid = ? AND status = ? ORDER BY name",
                            (version_uid, DatasetStatus.CURRENT.value)).fetchall()
    return [str(name) for (name,) in rows if str(name).startswith(prefix)]


def refresh_road_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` las listas de «Pista…» (spec 017, T29b; plan 017 §5.2.1 y §5.3.3): las capas «entidades» de **puntos** («trazar»: el origen
    y el destino) y de **líneas** («sobre un eje»), las de **líneas con Z** («eje 3D»: las líneas de rotura del proyecto y las rutas propuestas de la versión
    activa), las de **polígonos** (la zona de una cota de destino), los **perfiles de pista** (su código y su nombre), las **pistas** y las **plataformas**
    calculadas de la versión activa (el eje de otra pista como origen y la plataforma como destino) y **la partida** que propone el diálogo: la superficie de
    explotación de la cantera de la 014 y, si no hay o ya parte de ella otra entidad, la última de la cadena (RF-017-05, D-3). Se llama tras
    :func:`refresh_choices` y :func:`refresh_platform_choices`. Si no se puede leer, el error sigue."""
    from ...design import road_profiles, road_store  # al usarlo: habilitar no carga el cálculo

    _fixed_choices_road()
    found = constraint_panels.search_layers(project)
    points = [name for name, kind in found if kind == "point"]
    lines = [name for name, kind in found if kind == "line"]
    polygons = [name for name, kind in found if kind == "polygon"]
    if points:
        _CHOICES.road_points = [(name, constraint_panels.layer_label(name), tr("Layer of points")) for name in points]
    if lines:
        _CHOICES.road_lines = [(name, constraint_panels.layer_label(name), tr("Layer of lines")) for name in lines]
    if polygons:
        _CHOICES.road_zones = [(name, constraint_panels.layer_label(name), tr("Layer of polygons")) for name in polygons]
    version = scene_versions.active()
    breaklines = sorted(record.name for record in gis_store.list_gis_datasets(project, families=(gis_provenance.BREAKLINES,)))
    proposed = [] if version is None else _proposed_routes(project, version.uid)
    if breaklines or proposed:
        prefix = design_provenance.FAMILIES_BY_CODE[design_provenance.ROUTE_LAYER_TABLE].prefix
        _CHOICES.road_lines_3d = [*((name, constraint_panels.layer_label(name), tr("Layer of 3D lines")) for name in breaklines),
                                  *((name, name.removeprefix(prefix), tr("Proposed route of the active version (3D lines)")) for name in proposed)]
    with project.read() as conn:
        stored = road_profiles.read_profiles(conn)
    if stored:
        _CHOICES.road_profiles = [(item.code, item.name, tr("Road profile")) for item in stored]
    if version is None:
        return
    roads, platforms = _road_entities(project, version)
    if roads:
        _CHOICES.road_roads = roads
    if platforms:
        _CHOICES.road_platforms = platforms
    try:
        default = road_store.default_start(project, version)
    except (GeoblenderError, sqlite3.Error, ValueError):
        LOGGER.warning("No se pudo leer la partida por defecto de la pista", exc_info=True)
        default = None
    if default is not None:
        # La explotación de la cantera; si ya parte de ella otra entidad (de cada superficie parte una sola), la última de la cadena.
        _CHOICES.road_start = _CHOICES.platform_start if default.conflict is not None and _CHOICES.platform_start else default.ref


def road_layers(mode: str) -> list[tuple[str, str, str]]:
    """Las capas que ofrece «Pista…» en el modo ``mode`` (``TRACE``, ``ON_AXIS`` o ``AXIS_3D``; una lista viva del módulo): de **puntos** en «trazar», de **líneas** en
    «sobre un eje» y de **líneas con Z** en «eje 3D»; sin ninguna, «—»."""
    if not _CHOICES.road_points:
        _fixed_choices_road()
    if mode == "ON_AXIS":
        return _CHOICES.road_lines
    if mode == "AXIS_3D":
        return _CHOICES.road_lines_3d
    return _CHOICES.road_points


def road_layer_items(self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas que ofrece «Pista…» según su modo (``self.mode``): :func:`road_layers`."""
    return road_layers(getattr(self, "mode", "TRACE"))


def road_profile_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Los perfiles de pista del proyecto (spec 017, T29b; una lista viva del módulo): su código como identificador y su nombre; sin ninguno, «—»."""
    if not _CHOICES.road_profiles:
        _fixed_choices_road()
    return _CHOICES.road_profiles


def road_road_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las pistas calculadas de la versión activa de las que puede partir otra (spec 017, T29b; RF-017-03: su eje a una abscisa; una lista viva del módulo); sin
    ninguna, «—»."""
    if not _CHOICES.road_roads:
        _fixed_choices_road()
    return _CHOICES.road_roads


def road_platform_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las plataformas calculadas de la versión activa a las que puede llegar una pista (spec 017, T29b; RF-017-03; una lista viva del módulo); sin ninguna, «—»."""
    if not _CHOICES.road_platforms:
        _fixed_choices_road()
    return _CHOICES.road_platforms


def road_zone_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de polígonos con la zona de una cota de destino (spec 017, T29b; RF-017-02: la rampa; una lista viva del módulo); sin ninguna, «—»."""
    if not _CHOICES.road_zones:
        _fixed_choices_road()
    return _CHOICES.road_zones


def road_default_start() -> str | None:
    """La superficie de partida que propone el diálogo de «Pista…»: la de explotación de la cantera de la 014 y, si no hay o ya parte de ella otra entidad, la
    última de la cadena (RF-017-05, D-3); ``None`` si no hay ninguna candidata (la propone el diálogo con lo seleccionado en la vista)."""
    return _CHOICES.road_start


def has_road_profiles() -> bool:
    """Si el proyecto tiene algún perfil de pista que ofrecer."""
    return any(item[0] != NO_ZONE for item in _CHOICES.road_profiles)


def _fixed_choices_access() -> None:
    """Las listas de «Accesibilidad de las pistas…» sin nada del proyecto: sin capas de puntos y sin superficie propuesta."""
    _CHOICES.access_layers = [(NO_LAYER, NOT_SHOWN, tr("There are no layers of points in the project"))]
    _CHOICES.access_surface = None


def refresh_access_choices(project: Any) -> None:
    """Vuelve a leer de ``project`` lo que pide «Accesibilidad de las pistas…» (spec 017, T30; plan 017 §5.3.3): las capas «entidades» de **puntos** (los puntos de entrada) y **la superficie que
    propone el diálogo**: la última de la cadena de entidades de la versión activa y, sin cadena, la explotación de su cantera (``design.access_store.default_surface``, RF-017-24). Las superficies que
    se ofrecen son las de :func:`refresh_choices` (las del proyecto y las de la versión), que se llama antes. Si no se puede leer la propuesta, se deja sin ella."""
    from ...design import access_store  # al usarlo: habilitar no carga el cálculo

    _fixed_choices_access()
    points = [name for name, kind in constraint_panels.search_layers(project) if kind == "point"]
    if points:
        _CHOICES.access_layers = [(name, constraint_panels.layer_label(name), tr("Layer of points")) for name in points]
    version = scene_versions.active()
    if version is None:
        return
    try:
        _CHOICES.access_surface = access_store.default_surface(project, version)
    except (GeoblenderError, sqlite3.Error, ValueError):
        LOGGER.warning("No se pudo leer la superficie por defecto de la accesibilidad", exc_info=True)


def access_layer_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    """Las capas de puntos del proyecto que ofrece «Accesibilidad de las pistas…» como puntos de entrada (spec 017, T30; una lista viva del módulo); sin ninguna, «—»."""
    if not _CHOICES.access_layers:
        _fixed_choices_access()
    return _CHOICES.access_layers


def access_default_surface() -> str | None:
    """La superficie que propone el diálogo de «Accesibilidad de las pistas…» (la última de la cadena y, sin cadena, la explotación de la cantera; RF-017-24); ``None`` si no hay candidata."""
    return _CHOICES.access_surface


def forget_choices() -> None:
    """Olvida las listas leídas (al desregistrar)."""
    _CHOICES.key = None
    _CHOICES.surfaces, _CHOICES.anchors, _CHOICES.zones, _CHOICES.layers = [], [], [], []
    _CHOICES.optional_layers, _CHOICES.lines, _CHOICES.conserve = [], [], []
    _CHOICES.designs, _CHOICES.envelopes = [], []
    _CHOICES.platform_layers, _CHOICES.platform_kinds = [], {}
    _CHOICES.platform_starts, _CHOICES.platform_supports = [], []
    _CHOICES.platform_names, _CHOICES.platform_start = [], None
    _CHOICES.removal_stockpiles, _CHOICES.removal_by_ref = [], {}
    _CHOICES.body_footprints, _CHOICES.body_data, _CHOICES.body_kinds = [], [], {}
    _CHOICES.buttress_zones, _CHOICES.buttress_supports = [], []
    _CHOICES.road_points, _CHOICES.road_lines, _CHOICES.road_lines_3d = [], [], []
    _CHOICES.road_profiles, _CHOICES.road_roads, _CHOICES.road_platforms = [], [], []
    _CHOICES.road_zones, _CHOICES.road_start = [], None
    _CHOICES.access_layers, _CHOICES.access_surface = [], None
    _ACCESS.sections = []
    _RESTING.lines = []
    _CHOICES.by_id = {}


def surface_choice(identifier: str) -> res_surfaces.SurfaceChoice | None:
    """La superficie de identificador ``identifier`` (el nombre de su dato) de la lista leída, o
    ``None``: lo que necesita la propuesta del diálogo con lo seleccionado en la vista (T45)."""
    _ensure_choices()
    return _CHOICES.by_id.get(identifier)


def has_surfaces() -> bool:
    """Si el proyecto ofrece alguna superficie o rejilla de cotas (la primera opción no es la de
    «ninguna»)."""
    _ensure_choices()
    return bool(_CHOICES.surfaces) and _CHOICES.surfaces[0][0] != NO_ZONE


def profile_codes() -> dict[str, str]:
    """El código de cada perfil de banco de la vista por su nombre (lo que se elige en el diálogo)."""
    shown = view()
    return {} if shown is None else {item.name: item.code for item in shown.profiles}


def clear_sector_marks() -> None:
    """Quita la marca de acotar de los sectores (el diálogo parte sin acotar); los perfiles
    elegidos se conservan."""
    shown = view()
    if shown is not None:
        for item in shown.sectors:
            item.use = False


def draw_sector_rows(layout: Any, *, bound: bool, profiles: bool,
                     pick: str = "profile_pick") -> None:
    """Los sectores del diálogo, uno por fila: con ``bound``, su casilla de acotar el dominio de
    trabajo a él; con ``profiles``, el perfil que se le asigna (buscado entre los perfiles del
    proyecto; vacío, el perfil base) en su propiedad ``pick`` (la de las envolventes o, en la
    cantera, la de cada superficie: ``final_pick``, ``exploitation_pick``). Su estado de búsqueda
    va en ámbar si está pendiente."""
    shown = view()
    if shown is None:
        return
    for item in shown.sectors:
        row = layout.row(align=True)
        if bound:
            row.prop(item, "use", text=item.name, translate=False)
        else:
            row.label(text=item.name, translate=False)
        if item.pending:
            alert = row.row(align=True)
            alert.alert = True
            alert.label(text=tr("Search pending"), icon="ERROR", translate=False)
        if profiles:
            row.prop_search(item, pick, shown, "profiles", text="", translate=False)


def _figure(calculation: Calculation, key: str) -> float | None:
    """El valor de la cifra ``key`` de un cálculo (``None`` si no se dio)."""
    return next((figure.value for figure in calculation.figures if figure.key == key), None)


def _number(value: float | None, decimals: int = 0) -> str:
    return NOT_SHOWN if value is None else format_number(value, decimals)


def _one(count: object) -> bool:
    """Si un recuento (celdas, parejas, bermas) es 1 y su línea va en singular (spec 014, T61):
    «la regla de orden cambió 1 celda», no «1 celdas», como los avisos del diseño (T60)."""
    return not isinstance(count, bool) and isinstance(count, numbers.Real) and count == 1


def _quarry_lines(outcome: Any) -> list[tuple[str, bool]]:
    """El resumen de las dos superficies de una cantera calculada (``design.quarry.QuarryOutcome``;
    spec 014, T21 y T22; RF-014-12, RF-014-13, RF-014-15 a RF-014-18): el orden del diseño con las
    celdas que cambió su regla, las cotas de cada superficie en el recinto, la excavación de la
    explotación en m³ y ha, el desdoblado y el relleno de restauración en m³, **la clasificación**
    con el área de cada clase en ha y el espesor mínimo que separa «sin diferencia» (los totales de
    su clasificación, ``classes.total``) y, si no se pidió, «explotación hasta la final: no» (con el
    modo, lo que pasó a la explotación es una nota del cálculo). Los avisos los añade
    :func:`summary_lines`."""
    total = outcome.classes.total
    order = (tr("Final surface first") if Order(outcome.order) is Order.FINAL_FIRST
             else tr("Exploitation surface first"))
    if _one(outcome.adjusted):  # T61: el singular, como los avisos (T60)
        changed = tr("Order of the design: {order} · the order rule changed 1 cell", order=order)
    else:
        changed = tr("Order of the design: {order} · the order rule changed {cells} cells",
                     order=order, cells=_number(outcome.adjusted))
    lines = [(changed, False)]
    final, exploitation = total.levels(Surface.FINAL), total.levels(Surface.EXPLOITATION)
    if final is not None:
        lines.append((tr("Final surface: elevations {low} to {high} m",
                         low=_number(final[0], 1), high=_number(final[1], 1)), False))
    if exploitation is not None:
        lines.append((tr("Exploitation surface: elevations {low} to {high} m · excavation "
                         "{cut} m³ in {area} ha", low=_number(exploitation[0], 1),
                         high=_number(exploitation[1], 1), cut=_number(total.exp_cut_m3),
                         area=_number(total.exp_cut_area_ha, 2)), False))
    lines.append((tr("Unsplit {unsplit} m³ · restoration fill {fill} m³",
                     unsplit=_number(total.unsplit_m3), fill=_number(total.fill_m3)), False))
    lines.append((tr("Classification (minimum thickness {thickness} m): unsplit {unsplit} ha · "
                     "restoration fill {fill} ha · no difference {none} ha",
                     thickness=format_value(float(outcome.classes.min_thickness_m), language()),
                     unsplit=_number(total.area_ha(CellClass.UNSPLIT), 2),
                     fill=_number(total.area_ha(CellClass.FILL), 2),
                     none=_number(total.area_ha(CellClass.NONE), 2)), False))
    if outcome.to_final is None:
        lines.append((tr("Exploitation down to the final surface: no"), False))
    return lines


def _transition_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de una transición calculada (``design.edges.EdgeTransition``; spec 014, T28;
    RF-014-19 a RF-014-21): la superficie de diseño, el ángulo y el volumen, las celdas y el área
    de la transición; y el salto creado del borde de la superficie nueva (las parejas, el
    porcentaje dentro del salto admitido y el mayor salto creado). El aviso de RF-014-21 lo añade
    :func:`summary_lines`."""
    outcome = calculation.outcome
    transition, report = outcome.transition, outcome.report  # type: ignore[union-attr]
    shown = language()
    surface = str(calculation.settings.get("surface") or "")
    angle = format_value(float(transition.angle_deg), shown)
    volume, area = _number(transition.volume_m3), _number(transition.area_m2)
    if _one(transition.cells):  # T61: el singular
        moved = tr("Transition of «{surface}» at {angle}°: {volume} m³ in 1 cell ({area} m²)",
                   surface=surface, angle=angle, volume=volume, area=area)
    else:
        moved = tr("Transition of «{surface}» at {angle}°: {volume} m³ in {cells} cells "
                   "({area} m²)", surface=surface, angle=angle, volume=volume,
                   cells=_number(transition.cells), area=area)
    within = _number(report.within_pct, 2)
    threshold = format_value(float(report.threshold_m), shown)
    maximum = _number(max(0.0, report.maximum_m), 2)
    if _one(report.pairs):
        step = tr("Created step at the edge: 1 pair, {within} % within {threshold} m, the "
                  "largest {maximum} m", within=within, threshold=threshold, maximum=maximum)
    else:
        step = tr("Created step at the edge: {pairs} pairs, {within} % within {threshold} m, the "
                  "largest {maximum} m", pairs=_number(report.pairs), within=within,
                  threshold=threshold, maximum=maximum)
    return [(moved, False), (step, False)]


def _refit_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de un ajuste a un límite nuevo calculado (``design.refit.RefitOutcome``; spec 014,
    T33; RF-014-27): por superficie, en el orden de la petición, su volumen de ajuste con la cara de
    su propio perfil, las celdas que cambian y, de ellas, las que vuelven al terreno fuera del
    límite. El aviso de las que no hacía falta ajustar lo añade :func:`summary_lines`."""
    return [(_refit_line(item), False)
            for item in calculation.outcome.refits]  # type: ignore[union-attr]


def _refit_line(item: Any) -> str:
    """La línea de una superficie ajustada (``design.refit.Refit``) del resumen de un ajuste, con
    el singular de sus dos recuentos (T61)."""
    surface, volume = item.surface, _number(item.volume_m3)
    cells, outside = _number(item.cells), _number(item.outside_cells)
    if _one(item.cells) and _one(item.outside_cells):
        return tr("«{surface}» refitted with the face of its profile: {volume} m³ in 1 cell · 1 cell "
                  "back to the terrain outside the limit", surface=surface, volume=volume)
    if _one(item.cells):
        return tr("«{surface}» refitted with the face of its profile: {volume} m³ in 1 cell · "
                  "{outside} cells back to the terrain outside the limit", surface=surface,
                  volume=volume, outside=outside)
    if _one(item.outside_cells):
        return tr("«{surface}» refitted with the face of its profile: {volume} m³ in {cells} cells "
                  "· 1 cell back to the terrain outside the limit", surface=surface,
                  volume=volume, cells=cells)
    return tr("«{surface}» refitted with the face of its profile: {volume} m³ in {cells} cells · "
              "{outside} cells back to the terrain outside the limit", surface=surface,
              volume=volume, cells=cells, outside=outside)


def _refit_rows_of(project: Any, version_uid: str, origins: Sequence[Any],
                   checks: Sequence[Any], current: bool | None = None
                   ) -> tuple[list[tuple[str, str, bool]], str]:
    """Las filas de :func:`refit_rows` de las superficies ``origins`` (``SurfaceOrigin``) con sus
    comprobaciones ``checks`` (``RefitCheck``) y la nota si no hay ninguna y las máscaras no están
    al día (``current``: ya se sabe si lo están; ``None``, se lee)."""
    from ...core.versions import read as versions_read  # al usarlo: habilitar no lo carga
    from ...gis.masks import access as masks_access

    found = {check.surface: check for check in checks}
    rows: list[tuple[str, str, bool]] = []
    for origin in origins:
        surface = origin.record.name
        check = found.get(surface)
        if check is None:
            rows.append((surface, f"«{surface}»", False))
        elif check.outside:
            rows.append((surface, tr("«{surface}» · {volume} m³ in {area} m² outside the current "
                                     "limit", surface=surface, volume=_number(check.volume_m3),
                                     area=_number(check.area_m2)), True))
        else:
            rows.append((surface, tr("«{surface}» · nothing outside the current limit",
                                     surface=surface), False))
    note = ""
    if origins and not found:
        if current is None:
            state, _pending = masks_access.mask_state(project, version_uid)
            current = state is masks_access.MaskState.CURRENT
        if not current:
            with project.read() as conn:
                version = versions_read.version(conn, version_uid)
            note = tr("The masks of {version} are not up to date: compile them to see which "
                      "surfaces the current limit leaves outside",
                      version=version.code if version is not None else version_uid)
    return rows, note


def _refit_origins(project: Any, version_uid: str) -> tuple[Any, ...]:
    """Las superficies de diseño de la versión que se pueden ajustar (``design.store``)."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo

    with project.read() as conn:
        return design_store.limit_surfaces(conn, version_uid, types=design_store.REFIT_SOURCES)


def cached_refit_rows(project: Any, version_uid: str
                      ) -> tuple[list[tuple[str, str, bool]], str] | None:
    """Las filas de «Ajustar el diseño a un límite nuevo…» (como :func:`refit_rows`) **de la
    caché** de la comprobación (spec 014, T35; RNF-014-02), sin leer ninguna rejilla; ``None`` si
    hay que comprobar antes (alguna superficie sin acierto y las máscaras al día). Sin máscaras al
    día no hay nada que comprobar: las filas sin marcar y la nota. Solo lee."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo
    from ...gis.masks import access as masks_access

    origins = _refit_origins(project, version_uid)
    if not origins:
        return [], ""
    checks = _LIMITS.memo().lookup(project, version_uid, types=design_store.REFIT_SOURCES)
    if checks is not None:
        return _refit_rows_of(project, version_uid, origins, checks)
    state, _pending = masks_access.mask_state(project, version_uid)
    if state is masks_access.MaskState.CURRENT:
        return None
    return _refit_rows_of(project, version_uid, origins, (), current=False)


def refit_rows_steps(project: Any, version_uid: str) -> Iterator[Progress]:
    """La comprobación de las superficies de diseño de la versión que se pueden ajustar, por pasos
    (``design.store.LimitCheckMemo.fill_steps``, que llena la caché; spec 014, T35; RNF-014-02):
    los ``Progress`` de :data:`LIMIT_PHASE`, el último con las filas y la nota de
    :func:`refit_rows`. Cerrarlos a mitad no deja nada."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo

    message = tr("Checking the design surfaces against the current limit…")
    found = yield from _progress(_LIMITS.memo().fill_steps(
        project, version_uid, types=design_store.REFIT_SOURCES), message)
    yield Progress(LIMIT_PHASE, 1, 1, message, result=_refit_rows_of(
        project, version_uid, _refit_origins(project, version_uid),
        [check for _op_type, check in found]))


def refit_rows(project: Any, version_uid: str) -> tuple[list[tuple[str, str, bool]], str]:
    """Las filas de «Ajustar el diseño a un límite nuevo…» (spec 014, T33; plan 014 §5.3.3): cada
    superficie de diseño de la versión ``version_uid`` que se puede ajustar
    (``design.store.REFIT_SOURCES``, por el nombre de su dato) con lo que dice de ella la ventana y
    si queda fuera del límite vigente (``design.store.limit_checks``: la marcada); y una nota si las
    máscaras no están al día (sin ellas no se sabe qué queda fuera). De la caché
    (:func:`cached_refit_rows`) o, sin acierto, de una vez (:func:`refit_rows_steps`: desde un
    guion; la orden, desde la interfaz, comprueba por pasos antes de abrir su ventana). Solo lee;
    los errores del proyecto siguen."""
    found = cached_refit_rows(project, version_uid)
    if found is not None:
        return found
    for step in refit_rows_steps(project, version_uid):
        if step.result is not None:
            return step.result  # type: ignore[return-value]
    raise AssertionError("la comprobación acaba siempre con sus filas")  # pragma: no cover


def _platform_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de una plataforma calculada (``design.platform.PlatformOutcome``; spec 015, T15;
    RF-015-03, RF-015-23, RF-015-24; E1): su huella (celdas, área y la longitud de su eje), su rasante (las
    cotas de sus extremos y su pendiente), el corte y el relleno de la huella y del borde por separado, el
    mayor desmonte o relleno del borde (la «pared» del plan: T45, D-11) y **«sin contrapendientes»** si el perfil no sube más que la tolerancia. Sus
    avisos (la contrapendiente, lo que queda por debajo de la rasante, la restricción que no deja mover…) y lo
    que quedará obsoleto los añade :func:`summary_lines` (son los ``notices`` del cálculo)."""
    outcome = calculation.outcome
    values = calculation.entity.values if calculation.entity is not None else {}
    lines = [(tr("Platform «{name}» ({code}): footprint {area} m² in {cells} cells · axis {axis} m",
                 name=calculation.name, code=outcome.code,  # type: ignore[union-attr]
                 area=_number(_figure(calculation, "des.plat_area_m2")),
                 cells=_number(outcome.footprint.cell_count),  # type: ignore[union-attr]
                 axis=_number(_figure(calculation, "des.plat_axis_m"), 1)), False)]
    gradient = values.get("gradient_pct")
    lines.append((tr("Platform level: elevation {start} m at the start and {end} m at the end of "
                     "the axis · gradient {gradient} %",
                     start=_number(_figure(calculation, "des.plat_start_level_m"), 2),
                     end=_number(_figure(calculation, "des.plat_end_level_m"), 2),
                     gradient=_number(gradient if isinstance(gradient, int | float) else None, 2)),
                  False))
    lines.append((tr("Footprint: cut {cut} m³ · fill {fill} m³ · edge: cut {edge_cut} m³ · fill "
                     "{edge_fill} m³",
                     cut=_number(_figure(calculation, "des.plat_cut_m3")),
                     fill=_number(_figure(calculation, "des.plat_fill_m3")),
                     edge_cut=_number(_figure(calculation, "des.edge_cut_m3")),
                     edge_fill=_number(_figure(calculation, "des.edge_fill_m3"))), False))
    wall = _figure(calculation, "des.edge_wall_max_m")
    if wall is not None:
        lines.append((tr("Largest cut or fill of the edge: {wall} m", wall=_number(wall, 2)), False))
    removed = getattr(calculation.entity, "removed", None)
    if removed is not None:  # retirado «como plataforma» (spec 016, T41; RF-016-13, RF-016-16): las cifras de la retirada (la transición es el borde)
        lines.append((tr("Removal of the stockpile «{stockpile}»: {removed} m³ removed · resting on it: {resting} m³ · not removed: {kept} m³",
                         stockpile=removed.name, removed=_number(_figure(calculation, "des.rmv_removed_m3")),
                         resting=_number(_figure(calculation, "des.rmv_resting_m3")),
                         kept=_number(_figure(calculation, "des.rmv_kept_m3"))), False))
    if not outcome.counter_slope:  # type: ignore[union-attr]
        lines.append((tr("No counter-slopes (tolerance {tolerance} m)",
                         tolerance=_number(outcome.profile.tolerance_m, 2)), False))  # type: ignore[union-attr]
    return lines


def _removal_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de una retirada de un acopio calculada (``design.removal.RemovalOutcome`` y ``design.preview.RemovalSummary``; spec
    016, T20 (b); RF-016-13 a RF-016-15; M1): lo retirado, lo apoyado, la transición con su área y lo no retirado donde las máscaras no lo
    admiten, el ángulo y el factor de malla de la transición, la pared que deja (en ámbar, o que no deja ninguna), **la lista única de lo
    que se le apoyaba** (en ámbar: no se crea sin confirmarlo) y el motivo de la pared (o que lo pide). Los avisos y lo que quedará obsoleto
    los añade :func:`summary_lines`."""
    outcome, summary = calculation.outcome, calculation.summary
    lines = [(tr("Removal «{name}» ({code}) of the stockpile «{stockpile}»: {removed} m³ removed", name=calculation.name,
                 code=outcome.code,  # type: ignore[union-attr]
                 stockpile=summary.stockpile_name,  # type: ignore[union-attr]
                 removed=_number(outcome.removed_m3)), False),  # type: ignore[union-attr]
             (tr("Resting on it: {resting} m³ · transition: {transition} m³ over {area} m² · not removed: {kept} m³",
                 resting=_number(outcome.resting_m3),  # type: ignore[union-attr]
                 transition=_number(outcome.transition_m3),  # type: ignore[union-attr]
                 area=_number(outcome.transition_m2),  # type: ignore[union-attr]
                 kept=_number(outcome.kept_m3)), False),  # type: ignore[union-attr]
             (tr("Transition at {angle}° with mesh factor {factor}", angle=_number(outcome.transition_deg, 1),  # type: ignore[union-attr]
                 factor=_number(outcome.mesh_factor, 2)), False)]  # type: ignore[union-attr]
    height, angle = summary.wall_height_m, summary.wall_angle_deg  # type: ignore[union-attr]
    if height is None or angle is None:
        lines.append((tr("No wall left at the edge of what is removed"), False))
    else:
        lines.append((tr("Wall left at the edge: {height} m at {angle}°", height=_number(height, 1), angle=_number(angle, 1)),
                      True))
    prepared = calculation.entity
    lines.extend((row.text(language()), True) for row in prepared.resting)  # type: ignore[union-attr]
    wall = outcome.wall  # type: ignore[union-attr]
    given = (prepared.job.request.wall_reason or "").strip()  # type: ignore[union-attr]
    if calculation.needs_wall_reason and wall is not None:
        lines.append((tr("The wall passes {angle}° and {height} m: it needs a reason that stays recorded. Write it in the dialog and "
                         "calculate again", angle=_number(wall.reason_min_angle_deg, 0), height=_number(wall.reason_min_height_m, 0))
                      if not given else tr("Reason for the wall: {reason}", reason=given), not given))
    elif given and wall is not None and wall.stretches:
        lines.append((tr("Reason for the wall: {reason}", reason=given), False))
    return lines


def _body_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de un cuerpo apoyado calculado (``design.thickness.BodyOutcome`` y ``design.preview.BodySummary``; spec 016, T25;
    RF-016-20 a RF-016-22; M2): su volumen y su espesor máximo con su lugar, de dónde sale el espesor (las celdas con dato, las del TIN,
    las del dato más próximo y las directas de los polígonos), y la superficie que deja: la del techo «sobre una base» o la base
    «bajo un techo». Los avisos (lo ignorado, lo lejano, lo que no tiene superficie, lo triangulado) y lo que quedará obsoleto los añade
    :func:`summary_lines`."""
    outcome, summary = calculation.outcome, calculation.summary
    on_base = summary.sense == "on_base"  # type: ignore[union-attr]
    lines = [(tr("Supported body «{name}» ({code}) {sense}: {volume} m³ · largest thickness {thickness} m at ({x}, {y})",
                 name=calculation.name, code=outcome.code,  # type: ignore[union-attr]
                 sense=tr("on a base") if on_base else tr("under a roof"),
                 volume=_number(outcome.volume_m3),  # type: ignore[union-attr]
                 thickness=_number(outcome.thickness_max_m, 2),  # type: ignore[union-attr]
                 x=_number(outcome.thickness_max_x, 1), y=_number(outcome.thickness_max_y, 1)), False),  # type: ignore[union-attr]
             (tr("Thickness from «{layer}»: {data} cells with data · {tin} by the TIN · {nearest} by the nearest datum · {direct} "
                 "inside polygons",
                 layer=summary.data_layer,  # type: ignore[union-attr]
                 data=_number(outcome.data_cells),  # type: ignore[union-attr]
                 tin=_number(outcome.tin_cells),  # type: ignore[union-attr]
                 nearest=_number(outcome.nearest_cells),  # type: ignore[union-attr]
                 direct=_number(outcome.direct_cells)), False),  # type: ignore[union-attr]
             (tr("Leaves the surface with its roof: the base is the known surface") if on_base else
              tr("Leaves its base and its thickness: the known surface is its roof and it does not change"), False)]
    return lines


def _profile_label(code: str) -> str:
    """El nombre con que enseña el diálogo el perfil de banco de código ``code`` (el de la vista de los perfiles; el código si no lo
    conoce)."""
    shown = view()
    names = {} if shown is None else {item.code: item.name for item in shown.profiles}
    return names.get(code, code)


def _buttress_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de un contrafuerte calculado (``design.buttress.ButtressOutcome`` y ``design.preview.ButtressSummary``; spec 016, T27;
    RF-016-17, RF-016-18; M3): su volumen, su área y su mayor altura con su lugar, la cota de coronación con el perfil y la zona de
    coronación (su capa y sus celdas) y **lo que declarará**: «sin corte» sobre la zona de coronación con su resguardo, o que no protege.
    Los avisos y lo que quedará obsoleto los añade :func:`summary_lines`."""
    outcome, summary = calculation.outcome, calculation.summary
    lines = [(tr("Buttress «{name}» ({code}): {volume} m³ over {area} m² · largest height {height} m at ({x}, {y})",
                 name=calculation.name, code=outcome.code,  # type: ignore[union-attr]
                 volume=_number(outcome.volume_m3),  # type: ignore[union-attr]
                 area=_number(outcome.area_m2),  # type: ignore[union-attr]
                 height=_number(outcome.height_max_m, 2),  # type: ignore[union-attr]
                 x=_number(outcome.height_max_x, 1), y=_number(outcome.height_max_y, 1)), False),  # type: ignore[union-attr]
             (tr("Crown at {crown} m · profile «{profile}» · crown zone of «{layer}»: {cells} cells",
                 crown=_number(outcome.crown_m, 2),  # type: ignore[union-attr]
                 profile=_profile_label(outcome.profile),  # type: ignore[union-attr]
                 layer=summary.layer,  # type: ignore[union-attr]
                 cells=_number(int(outcome.zone.sum()))), False)]  # type: ignore[union-attr]
    if summary.protect:  # type: ignore[union-attr]
        lines.append((tr("It will declare «no cut» on its crown zone, with a guard of {guard} m",
                         guard=_number(summary.guard_m, 1)), False))  # type: ignore[union-attr]
    else:
        lines.append((tr("It does not protect its crown zone: it declares no constraint"), False))
    return lines


def _road_mode_text(mode: object) -> str:
    """El nombre, en el idioma de Geoblender, del modo de una pista (``trace``, ``on_axis`` o ``axis_3d``): el de su diálogo, «Pista…»; el valor tal cual si no es de ellos."""
    names = {"trace": tr("Trace"), "on_axis": tr("Over an axis"), "axis_3d": tr("3D axis")}
    return names.get(str(mode), str(mode))


def _road_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de una pista calculada (``design.preview.RoadSummary``; spec 017, T29b; RF-017-23, RF-017-17, RF-017-22; M1): su modo, su perfil, su longitud y las
    cotas de inicio y de fin, la pendiente media y la máxima con su abscisa y su lugar, el radio mínimo y las curvas, el corte y el relleno de la sección y del
    borde juntos y, **en ámbar, lo que pide su confirmación expresa**: la pendiente media por encima de la del perfil (con un motivo, que queda registrado: no
    bloquea) y la calzada que no queda en su rasante. Los avisos con su lugar (la holgura del pasillo de la ruta, los del eje, la huella recortada, los otros
    diseños, el salto creado, la calzada y la restricción que impide moverla, lo que no se mueve y lo que quedará obsoleto) los añade :func:`summary_lines`
    (son los ``notices`` del cálculo)."""
    summary = calculation.summary
    prepared = calculation.entity
    mode = _road_mode_text(summary.mode)  # type: ignore[union-attr]
    lines = [(tr("Road «{name}» ({code}) · mode «{mode}» · profile «{profile}»: length {length} m · elevation {start} m at the start and {end} m at the end",
                 name=calculation.name, code=summary.code, mode=mode,  # type: ignore[union-attr]
                 profile=prepared.profile.name,  # type: ignore[union-attr]
                 length=_number(summary.length_m, 1), start=_number(summary.start_level_m, 2),  # type: ignore[union-attr]
                 end=_number(summary.end_level_m, 2)), False),  # type: ignore[union-attr]
             (tr("Gradient: mean {mean} % · maximum {max} % at the abscissa {station} m, at ({x}, {y})",
                 mean=_number(summary.gradient_mean_pct, 2), max=_number(summary.gradient_max_pct, 2),  # type: ignore[union-attr]
                 station=_number(summary.gradient_max_station_m, 1), x=_number(summary.gradient_max_x, 1),  # type: ignore[union-attr]
                 y=_number(summary.gradient_max_y, 1)), False)]  # type: ignore[union-attr]
    if summary.radius_min_m is None:  # type: ignore[union-attr]
        lines.append((tr("No curves: the axis is a straight line"), False))
    elif summary.curves == 1:  # type: ignore[union-attr]
        lines.append((tr("Minimum radius {radius} m in 1 curve", radius=_number(summary.radius_min_m, 1)), False))  # type: ignore[union-attr]
    else:
        lines.append((tr("Minimum radius {radius} m in {curves} curves", radius=_number(summary.radius_min_m, 1),  # type: ignore[union-attr]
                         curves=_number(summary.curves)), False))  # type: ignore[union-attr]
    lines.append((tr("Section and edge: cut {cut} m³ · fill {fill} m³ · net {net} m³", cut=_number(summary.cut_m3), fill=_number(summary.fill_m3),  # type: ignore[union-attr]
                     net=_number(summary.net_m3)), False))  # type: ignore[union-attr]
    if calculation.needs_mean_confirmation:
        lines.append((tr("The mean gradient, {mean} %, passes the {limit} % of the profile: the road is not created without your express confirmation and a "
                         "reason, which stays recorded with who and when; the button that creates it confirms it",
                         mean=_number(summary.gradient_mean_pct, 2), limit=_number(summary.mean_limit_pct, 2)), True))  # type: ignore[union-attr]
    if calculation.needs_carriageway_confirmation:
        lines.append((tr("{area} m² of the carriageway do not end up on the level profile of the road (see the warnings): the road is not created without your "
                         "express confirmation; the button that creates it confirms it", area=_number(summary.carriageway_area_m2)), True))  # type: ignore[union-attr]
    return lines


ACCESS_ROWS = 10
"""Cuántas filas enseña cada lista de la accesibilidad en la ventana de crear (como los ``SUMMARY_ITEMS`` de ``design.preview``): las demás, con una nota; el resultado entero se registra al crear."""
_ACCESS_ITEM_NOTICES = frozenset({"des.access_berm_missing", "des.access_platform_missing", "des.access_zone_missing", "des.access_zone_missing_unplaced", "des.access_more"})
"""Los avisos del resumen de una accesibilidad que dicen **qué no se comunica**: los dicen las listas, con su lugar y su «Ir a»; el resumen que se enseña no los repite."""


def _access_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de una accesibilidad calculada (``design.access_store.AccessSummary``; spec 017, T30; RF-017-24, RF-017-25, M3): la cabecera (cuántos tramos de berma, plataformas y zonas «requiere acceso» quedan
    comunicados), las cotas mínima y máxima alcanzables y el área, la cota mínima sobre la final de una cantera, los avisos del cálculo (un punto de entrada que no está en terreno transitable, nada
    alcanzado) y lo que quedará obsoleto. **Lo que no se comunica** no sale aquí: lo dicen las listas (:func:`access_sections`), cada cosa con su lugar y su «Ir a»."""
    shown = language()
    return [(notice.text(shown), notice.severity == "warning") for notice in calculation.notices if notice.code not in _ACCESS_ITEM_NOTICES]


def _cut_rows(rows: list[AccessRow], limit: int = ACCESS_ROWS) -> tuple[tuple[AccessRow, ...], int]:
    """Las primeras ``limit`` filas de ``rows`` —**las que no se comunican (en alerta) antes**, cada grupo en su orden— y cuántas faltan."""
    ordered = sorted(rows, key=lambda row: not row.alert)
    return tuple(ordered[:limit]), max(0, len(ordered) - limit)


def _berm_rows(berms: Iterable[Any]) -> list[AccessRow]:
    """Las filas de los tramos de berma ``berms`` (``BermReach`` del cálculo o ``BermRow`` de ``des_acb_``: su número, el dato de bermas de que sale, su cota real, su área y si queda comunicado), cada una
    con su lugar (``place_of``: el centro de sus celdas, con su área para el radio)."""
    rows: list[AccessRow] = []
    for item in berms:
        source, level, area = "—" if item.source is None else item.source, _number(item.level_m, 2), _number(item.area_m2)
        text = (tr("Berm stretch {stretch} of «{source}»: elevation {level} m, {area} m² · communicated", stretch=item.number, source=source, level=level, area=area) if item.connected
                else tr("Berm stretch {stretch} of «{source}»: elevation {level} m, {area} m² · not communicated", stretch=item.number, source=source, level=level, area=area))
        rows.append(AccessRow(text, not item.connected, constraint_panels.place_of(item.x, item.y, item.area_m2)))
    return rows


def _platform_rows(platforms: Iterable[Any], names: Mapping[str, str], places: Mapping[str, Any]) -> list[AccessRow]:
    """Las filas de las plataformas ``platforms`` (``PlatformReach`` o ``PlatformRow``: su código, si queda comunicada y a qué cota se llega), con su nombre (``names``, por código) y su lugar
    (``places``, por código: el centro de su huella; la que no lo tiene, sin «Ir a»)."""
    rows: list[AccessRow] = []
    for item in platforms:
        found = places.get(item.code)
        name = names.get(item.code, item.code)
        text = (tr("Platform «{name}» ({code}): communicated, reached at elevation {level} m", name=name, code=item.code, level=_number(item.level_m, 2)) if item.connected
                else tr("Platform «{name}» ({code}): not communicated", name=name, code=item.code))
        rows.append(AccessRow(text, not item.connected, None if found is None else constraint_panels.place_of(found.x, found.y, found.area_m2)))
    return rows


def _zone_rows(zones: Iterable[Any], places: Mapping[str, Any]) -> list[AccessRow]:
    """Las filas de las zonas «requiere acceso» ``zones`` (``ZoneReach`` o ``AccessZone``: su código y si queda comunicada y, de la que no, la distancia y la diferencia de cota a lo alcanzable más
    próximo), cada una con su lugar (``places``, por código; la que no lo tiene, sin «Ir a»)."""
    rows: list[AccessRow] = []
    for item in zones:
        found = places.get(item.code)
        if item.connected:
            text = tr("Zone «{code}» that requires access: communicated", code=item.code)
        elif item.distance_m is not None and item.level_difference_m is not None:
            text = tr("Zone «{code}» that requires access: not communicated; the nearest reachable ground is {distance} m away (level difference {difference} m)", code=item.code,
                      distance=_number(item.distance_m, 2), difference=_number(item.level_difference_m, 2))
        else:
            text = tr("Zone «{code}» that requires access: not communicated", code=item.code)
        rows.append(AccessRow(text, not item.connected, None if found is None else constraint_panels.place_of(found.x, found.y, found.area_m2)))
    return rows


def _access_sections(calculation: Calculation) -> list[AccessSection]:
    """Las tres listas de la accesibilidad calculada ``calculation`` (:class:`AccessSection`; spec 017, T30; RF-017-25): **cada tramo de berma** (su número y el dato de bermas de que sale, su cota real, su área y
    si queda comunicado, con su lugar: el centro de sus celdas), **cada plataforma** de la versión (su nombre y su código, si queda comunicada y a qué cota se llega, con el centro de su huella) y **cada zona
    «requiere acceso»** (su código y si queda comunicada y, de la que no, la distancia y la diferencia de cota a lo alcanzable más próximo, con el lugar que dice el resumen). El lugar de «Ir a» lo da
    ``design.access_store.access_places``; el radio, su área (:func:`constraint_panels.place_of`). Solo lee."""
    from ...design import access_store  # al usarlo: habilitar no carga el cálculo

    outcome, job = calculation.outcome, calculation.entity.job  # type: ignore[union-attr]
    places = access_store.access_places(job, outcome)  # type: ignore[arg-type]
    names = {item.code: item.name for item in job.platforms}  # type: ignore[union-attr]
    return [AccessSection(title, *_cut_rows(rows)) for title, rows in (
        (tr("Berm stretches"), _berm_rows(outcome.berms)),  # type: ignore[union-attr]
        (tr("Platforms"), _platform_rows(outcome.platforms, names, places.platforms)),  # type: ignore[union-attr]
        (tr("Zones that require access"), _zone_rows(outcome.zones, places.zones)))]  # type: ignore[union-attr]


def show_access(calculation: Calculation | None) -> None:
    """Deja las listas del cálculo abierto de una accesibilidad ``calculation`` (:func:`_access_sections`) para la ventana de crear (spec 017, T30); sin cálculo, o con el de otra orden, las vacía.
    :func:`show_summary` lo llama: las listas siguen al resumen (al calcular, al crear y al cancelar)."""
    if calculation is None or calculation.op_type != design_provenance.ROAD_ACCESS:
        _ACCESS.sections = []
        return
    _ACCESS.sections = _access_sections(calculation)


def access_sections() -> list[AccessSection]:
    """Las tres listas del cálculo abierto de una accesibilidad (tramos de berma, plataformas y zonas «requiere acceso»), en el idioma en que se leyeron; ninguna si no hay cálculo abierto de ese tipo."""
    return list(_ACCESS.sections)


def access_report_lines() -> list[tuple[str, bool]]:
    """Lo que no se comunica de las listas (:func:`access_sections`), línea a línea y en alerta: lo que la orden dice en el informe al calcular, donde el resumen que se enseña ya no lo repite."""
    return [(row.text, True) for section in _ACCESS.sections for row in section.rows if row.alert]


def draw_access_lists(layout: Any, width_px: int) -> None:
    """Las listas de la accesibilidad (:func:`access_sections`) en un diálogo de ``width_px`` (spec 017, T30; RF-017-25; M3): cada una en su caja con su título y, por fila, su texto (en alerta si no se
    comunica) y su **«Ir a»** (``geoblender.core_go_to_place`` con el lugar y el radio), y, si faltan, una nota con cuántas."""
    for section in _ACCESS.sections:
        box = layout.box()
        box.label(text=section.title, translate=False)
        if not section.rows:
            box.label(text=tr("Nothing to list"), translate=False)
            continue
        for row in section.rows:
            line = box.row()
            draw_wrapped(line.column(), row.text, width_px - 90, alert=row.alert)
            if row.place is not None:
                button = line.operator(constraint_panels.GO_TO_PLACE, text=tr("Go to"), translate=False)
                button.x, button.y, button.radius = row.place
        if section.more:
            box.label(text=tr("… and {more} more (the whole list is recorded when the accessibility is created)", more=section.more), translate=False)


def summary_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de un cálculo hecho y sin registrar (RF-013-31), línea a línea y en el idioma de
    Geoblender, con los avisos al final y en alerta: de una envolvente, sus celdas, su área, sus
    cotas y el desmonte y el terraplén frente a la superficie de partida (las cifras que se
    registrarían); de un escalonado, el desmonte y el terraplén, la inclinación p99 y máxima con su
    lugar, y las bermas con sus cotas reales (el informe y las bermas del dominio); de un recinto
    excavable (spec 014, T20; RF-014-01), sus celdas y su área; de una cantera con dos superficies
    (spec 014, T21; RF-014-12), lo de :func:`_quarry_lines`; de una transición (T28), lo de
    :func:`_transition_lines`; de un diseño «solo relleno» (T30), lo de :func:`_fill_only_lines`;
    de un ajuste a un límite nuevo (T33), lo de :func:`_refit_lines`. Aquí solo se escriben."""
    lines: list[tuple[str, bool]] = []
    if calculation.op_type == design_provenance.PLATFORM:
        lines.extend(_platform_lines(calculation))
    elif calculation.op_type == design_provenance.STOCKPILE_REMOVAL:
        lines.extend(_removal_lines(calculation))
    elif calculation.op_type == design_provenance.BODY:
        lines.extend(_body_lines(calculation))
    elif calculation.op_type == design_provenance.BUTTRESS:
        lines.extend(_buttress_lines(calculation))
    elif calculation.op_type == design_provenance.ROAD:
        lines.extend(_road_lines(calculation))
    elif calculation.op_type == design_provenance.ROAD_ACCESS:
        return _access_lines(calculation)  # sus avisos ya son su resumen (sin lo que no se comunica, que dicen las listas): no se añaden otra vez
    elif calculation.op_type in design_provenance.STOCKPILE_DETECT_TYPES:
        pass  # la detección lo dice todo en sus avisos (``StockpileSummary.notices``: la cabecera, los acopios, los candidatos): spec 016, T35
    elif calculation.op_type == design_provenance.QUARRY:
        lines.extend(_quarry_lines(calculation.outcome))
    elif calculation.op_type == design_provenance.REFIT:
        lines.extend(_refit_lines(calculation))
    elif calculation.op_type == design_provenance.EDGE_TRANSITION:
        lines.extend(_transition_lines(calculation))
    elif calculation.op_type == design_provenance.EXCAVATION_AREA:
        cells = calculation.outcome.cells  # type: ignore[union-attr]
        area = _number(_figure(calculation, "des.rcn_area_m2"))
        lines.append((tr("Excavation boundary «{name}»: 1 cell ({area} m²)", name=calculation.name,
                         area=area) if _one(cells) else
                      tr("Excavation boundary «{name}»: {cells} cells ({area} m²)",
                         name=calculation.name, cells=_number(cells), area=area), False))
    elif calculation.op_type == design_provenance.ENVELOPE:
        cells = _figure(calculation, "des.env_cells")
        lines.append((tr("Envelope «{name}»: {cells} cells ({area} m²)", name=calculation.name,
                         cells=_number(cells), area=_number(_figure(calculation,
                                                                    "des.env_area_m2"))), False))
        low, high = _figure(calculation, "des.env_min_m"), _figure(calculation, "des.env_max_m")
        if low is not None and high is not None:
            lines.append((tr("Elevations {low} to {high} m", low=_number(low, 1),
                             high=_number(high, 1)), False))
        cut, fill = _figure(calculation, "des.env_cut_m3"), _figure(calculation, "des.env_fill_m3")
        if cut is not None and fill is not None:
            lines.append((tr("Against the start surface: cut {cut} m³ · fill {fill} m³",
                             cut=_number(cut), fill=_number(fill)), False))
    elif calculation.op_type == design_provenance.FILL_ONLY:
        lines.extend(_fill_only_lines(calculation))
    else:
        outcome = calculation.outcome
        report, berms = outcome.report, outcome.berms  # type: ignore[union-attr]
        lines.append((tr("Benching «{name}»: cut {cut} m³ · fill {fill} m³ · moved area {area} m²",
                         name=calculation.name, cut=_number(report.cut_m3),
                         fill=_number(report.fill_m3), area=_number(report.moved_area_m2)),
                      False))
        lines.extend(_bench_lines(report, berms))
    lines.extend((notice.text(language()), notice.severity == "warning")
                 for notice in calculation.notices)
    return lines


def _bench_lines(report: Any, berms: Any, *, without_berms: bool = True
                 ) -> list[tuple[str, bool]]:
    """La inclinación p99 y máxima con su lugar y las bermas con sus cotas reales de un
    escalonado (su informe y sus bermas medidas), como las dice el resumen; sin bermas, «Sin
    bermas: no se mueve nada» si ``without_berms``."""
    lines: list[tuple[str, bool]] = []
    if report.slope_max_deg is not None and report.slope_p99_deg is not None:
        where = report.slope_max_at
        lines.append((tr("Cell slope: p99 {p99}° · maximum {max}° at ({x}, {y})",
                         p99=_number(report.slope_p99_deg, 1),
                         max=_number(report.slope_max_deg, 1),
                         x=_number(None if where is None else where.x, 1),
                         y=_number(None if where is None else where.y, 1)), False))
    if berms.lowest_m is not None and berms.highest_m is not None:
        low, high = _number(berms.lowest_m, 1), _number(berms.highest_m, 1)
        lines.append((tr("1 berm, real elevations {low} to {high} m", low=low, high=high)
                      if _one(berms.count) else
                      tr("{count} berms, real elevations {low} to {high} m",
                         count=_number(berms.count), low=low, high=high), False))
    elif without_berms:
        lines.append((tr("No berms: nothing moves"), False))
    return lines


def _fill_only_lines(calculation: Calculation) -> list[tuple[str, bool]]:
    """El resumen de un diseño «solo relleno» calculado (``design.fronts.FillOnlyOutcome``; spec
    014, T30; RF-014-22 a RF-014-24): el terraplén y el área con movimiento frente al terreno de
    partida con las láminas (el informe de su escalonado), el corte frente al terreno registrado
    (con dos decimales: tiene que ser menor de 1 m³), las celdas en que la lámina de agua es la
    partida, si las hay, y la inclinación y las bermas (un relleno de un solo banco no tiene
    bermas, y no por eso deja de mover: «Sin bermas: no se mueve nada», solo si no mueve nada).
    Los avisos los añade :func:`summary_lines`."""
    outcome = calculation.outcome
    report, berms = outcome.design.report, outcome.design.berms  # type: ignore[union-attr]
    lines = [(tr("Fill-only design «{name}»: fill {fill} m³ · cut {cut} m³ · moved area {area} m²",
                 name=calculation.name, fill=_number(report.fill_m3),
                 cut=_number(outcome.cut_m3, 2),  # type: ignore[union-attr]
                 area=_number(report.moved_area_m2)), False)]
    water = outcome.water_cells  # type: ignore[union-attr]
    if water:
        lines.append((tr("Water sheets as the start surface in 1 cell") if _one(water) else
                      tr("Water sheets as the start surface in {cells} cells",
                         cells=_number(water)), False))
    return [*lines, *_bench_lines(report, berms, without_berms=not report.moved_area_m2)]


def show_preview(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja ``lines`` (texto ya traducido, si va en alerta) como el resumen de la vista previa de
    semillas, dominios y restricciones (T25; RF-013-03; ``bl.draw.design``: lo que dice
    ``design.preview``, aquí solo se guarda para que lo dibuje la barra N); sin líneas, lo vacía."""
    shown = view()
    if shown is None:
        return
    shown.preview.clear()
    for text, alert in lines:
        line = shown.preview.add()
        line.name, line.alert = text, alert
    _redraw()  # la barra N «Diseño» enseña este resumen mientras lo hay


def show_summary(calculation: Calculation | None) -> None:
    """Deja el resumen del cálculo abierto ``calculation`` (:func:`summary_lines`) en la vista, con
    su título («Envolvente «Hoyo» en V01»); sin cálculo, lo vacía. Con el de una accesibilidad deja también
    sus listas (:func:`show_access`; spec 017, T30), que siguen al resumen."""
    show_access(calculation)
    shown = view()
    if shown is None:
        return
    shown.summary.clear()
    if calculation is None:
        shown.summary_title = ""
        return
    if calculation.op_type == design_provenance.ENVELOPE:
        title = tr("Envelope «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.EXCAVATION_AREA:
        title = tr("Excavation boundary «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.QUARRY:
        title = tr("Quarry «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.EDGE_TRANSITION:
        title = tr("Transition «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.FILL_ONLY:
        title = tr("Fill-only design «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.REFIT:
        title = tr("Refit «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.PLATFORM and getattr(calculation.entity, "removed", None) is not None:
        title = tr("Removal of a stockpile «{name}» as a platform in {version}", name=calculation.name,  # T41: «como plataforma»
                   version=calculation.version)
    elif calculation.op_type == design_provenance.PLATFORM:
        title = tr("Platform «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.STOCKPILE_REMOVAL:
        title = tr("Removal of a stockpile «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    elif calculation.op_type == design_provenance.BODY:
        title = tr("Supported body «{name}» in {version}", name=calculation.name, version=calculation.version)
    elif calculation.op_type == design_provenance.BUTTRESS:
        title = tr("Buttress «{name}» in {version}", name=calculation.name, version=calculation.version)
    elif calculation.op_type == design_provenance.ROAD:
        title = tr("Road «{name}» in {version}", name=calculation.name, version=calculation.version)
    elif calculation.op_type == design_provenance.ROAD_ACCESS:
        title = tr("Accessibility «{name}» in {version}", name=calculation.name, version=calculation.version)
    elif calculation.op_type == design_provenance.STOCKPILE_DETECT:
        title = tr("Detection of stockpiles «{name}» in {version}", name=calculation.name, version=calculation.version)
    elif calculation.op_type == design_provenance.STOCKPILE_DETECT_PROJECT:  # D-15: del proyecto, sin versión (spec 016, T35)
        title = tr("Detection of stockpiles «{name}» in the project", name=calculation.name)
    else:
        title = tr("Benching «{name}» in {version}", name=calculation.name,
                   version=calculation.version)
    shown.summary_title = title
    for text, alert in summary_lines(calculation):
        line = shown.summary.add()
        line.name, line.alert = text, alert


def draw_summary(layout: Any, width_px: int) -> None:
    """El resumen del cálculo abierto de la vista (:func:`show_summary`) en un diálogo de
    ``width_px``: su título y cada línea partida al ancho, los avisos en ámbar."""
    shown = view()
    if shown is None:
        return
    width = labels.dialog_width(width_px)
    if shown.summary_title:
        _draw_text(layout, shown.summary_title, width)
    for line in shown.summary:
        _draw_text(layout, line.name, width, alert=bool(line.alert))


def on_project_read(project: Any) -> None:
    """Lo que hace la escucha de los indicadores de la procedencia cada vez que el proyecto
    cambió (``bl.ui.provenance.add_change_listener``): los valores de las ventanas de los perfiles
    y de los sectores, al día si son de ``project`` (un valor cambiado con ``Cambiar…``, sectores
    declarados de nuevo con la 012). Si no se puede leer, lo deja en el registro técnico."""
    shown = view()
    if shown is None:
        return
    if shown.profiles_project and shown.profiles_project == project.uid:
        try:
            fill_profiles(project)
        except (GeoblenderError, sqlite3.Error, OSError):
            LOGGER.warning("No se pudieron leer los perfiles de banco", exc_info=True)
    if shown.road_profiles_project and shown.road_profiles_project == project.uid:
        try:
            fill_road_profiles(project)
        except (GeoblenderError, sqlite3.Error, OSError):
            LOGGER.warning("No se pudieron leer los perfiles de pista", exc_info=True)
    if shown.sectors_project and shown.sectors_project == project.uid:
        try:
            fill_sectors(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.warning("No se pudieron leer los sectores de diseño", exc_info=True)


# --- Dibujo --------------------------------------------------------------------------------------


def _draw_text(layout: Any, shown_text: str, width: float, *, alert: bool = False) -> None:
    """``shown_text`` partido al ancho de la zona (``width``), en alerta si ``alert``: una etiqueta
    de Blender no parte el texto, lo corta con «…»."""
    column = layout.column(align=True)
    column.alert = alert
    for index, part in enumerate(labels.wrapped(shown_text, width, icon=alert)):
        icon = ("ERROR" if index == 0 else "BLANK1") if alert else "NONE"
        column.label(text=part, icon=icon, translate=False)


def draw_wrapped(layout: Any, shown_text: str, width_px: int, *, alert: bool = False) -> None:
    """``shown_text`` partido al ancho de un diálogo de ``width_px`` (:func:`_draw_text`), en alerta si ``alert``: una línea de la lista de
    candidatos de «Candidatos de los acopios…» (spec 016, T35)."""
    _draw_text(layout, shown_text, labels.dialog_width(width_px), alert=alert)


def _draw_blocked(layout: Any, blocked: str | None, width: float) -> None:
    """Por qué la ventana se ve y no se cambia (RF-013-33), en alerta y con el candado."""
    if blocked is None:
        return
    note = layout.column(align=True)
    note.alert = True
    for index, part in enumerate(labels.wrapped(blocked, width, icon=True)):
        note.label(text=part, icon="LOCKED" if index == 0 else "BLANK1", translate=False)


class GEOBLENDER_UL_des_profiles(bpy.types.UIList):
    """Bench profiles of the project with their values and their type"""

    bl_idname = PROFILES_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        split = layout.split(factor=NAME_FACTOR, align=True)
        title = f"{item.name} {item.badge}" if item.badge else item.name
        split.label(text=title, translate=False)
        cell = split.row(align=True)
        bad = bool(item.unresolved or item.problem)
        cell.alert = bad
        cell.label(text=item.summary, icon="ERROR" if bad else "NONE", translate=False)


def _draw_chosen(layout: Any, item: Any, width: float, writable: bool) -> None:
    """El perfil elegido: su nombre, su ámbito y su insignia, sus derivados, lo que la rejilla no
    resuelve o lo que le falta (en alerta), cada uno de sus cinco valores (con «Cambiar…» si está
    registrado) y «Completar o renombrar…» (RF-013-18, RF-013-20). Los textos largos, partidos al
    ancho de la zona y el botón de un valor, debajo de él."""
    box = layout.box()
    title = f"{item.name} {item.badge}" if item.badge else item.name
    box.label(text=title, translate=False)
    _draw_text(box, tr("Scope: {scope}", scope=item.scope), width)
    _draw_text(box, item.summary, width)
    if item.derived:
        _draw_text(box, item.derived, width)
    if item.unresolved:
        _draw_text(box, item.unresolved, width, alert=True)
    if item.problem:
        _draw_text(box, item.problem, width, alert=True)
    box.label(text=tr("Parameters"), translate=False)
    for line in item.parameters:
        block = box.column(align=True)
        block.enabled = writable
        _draw_text(block, f"{line.name}:", width)
        _draw_text(block, line.text, width)
        if line.registered:
            button = block.operator(SET_PARAMETER, text=tr("Change…"), translate=False)
            button.key = line.key
    edit = box.row()
    edit.enabled = writable
    button = edit.operator(SAVE_PROFILE, text=tr("Complete or rename…"), icon="GREASEPENCIL",
                           translate=False)
    button.code = item.code


def draw_profiles(layout: Any, context: Any) -> None:
    """La ventana de Perfiles de banco… (véase el módulo), de lo ya leído."""
    shown = view()
    if shown is None:
        return
    blocked = _write_unavailable()
    writable = blocked is None
    width = labels.dialog_width(PROFILES_WIDTH_PX)
    _draw_blocked(layout, blocked, width)
    create = layout.row()
    create.enabled = writable
    button = create.operator(SAVE_PROFILE, text=tr("New profile…"), icon="ADD", translate=False)
    button.code = ""
    if not len(shown.profiles):
        labels.draw_wrapped(layout, tr(
            "There are no bench profiles yet: create one with its height, face angle, berm and "
            "anchor elevation"), width, icon="INFO")
    else:
        layout.label(text=tr("Bench profiles: {count}", count=len(shown.profiles)),
                     translate=False)
        layout.template_list(PROFILES_LIST, "", shown, "profiles", shown, "profile_index",
                             rows=PROFILE_ROWS)
        index = min(max(shown.profile_index, 0), len(shown.profiles) - 1)
        _draw_chosen(layout, shown.profiles[index], width, writable)
    if len(shown.profile_report):
        box = layout.box()
        box.label(text=tr("Last result"), translate=False)
        for line in shown.profile_report:
            _draw_text(box, line.name, width, alert=bool(line.alert))


class GEOBLENDER_PT_des_profiles(bpy.types.Panel):
    """Bench profiles of the project: their values, their type and their scope, and the orders to
    create, complete, rename and change them"""

    bl_idname = PROFILES_PANEL
    bl_label = "Bench profiles"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = PROFILES_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_profiles(self.layout, context)


# --- Perfil de pista… (spec 017, T29; HU-017-1; RF-017-07, RF-017-08, RF-017-29) -------------------


class GEOBLENDER_UL_des_road_profiles(bpy.types.UIList):
    """Road profiles of the project with their values and their type"""

    bl_idname = ROAD_PROFILES_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        split = layout.split(factor=NAME_FACTOR, align=True)
        title = f"{item.name} {item.badge}" if item.badge else item.name
        split.label(text=title, translate=False)
        cell = split.row(align=True)
        cell.alert = bool(item.problem)
        cell.label(text=item.summary, icon="ERROR" if item.problem else "NONE", translate=False)


def _draw_road_chosen(layout: Any, item: Any, width: float, writable: bool) -> None:
    """El perfil de pista elegido: su nombre, su ámbito y su insignia, su clase normativa, cómo se lee, **sus derivados** (la calzada, la sección,
    su semianchura y la longitud mínima H/pd: texto, sin botón, porque no son parámetros), lo que le falta o no vale (en alerta), cada uno de
    sus quince valores con su tipo, su ámbito y su fuente (con «Cambiar…» si está registrado) y «Completar o renombrar…» (RF-017-07,
    RF-017-08). Los textos largos, partidos al ancho de la zona."""
    box = layout.box()
    title = f"{item.name} {item.badge}" if item.badge else item.name
    box.label(text=title, translate=False)
    _draw_text(box, tr("Scope: {scope}", scope=item.scope), width)
    if item.road_class:
        _draw_text(box, tr("Normative class: {road_class}", road_class=item.road_class), width)
    _draw_text(box, item.summary, width)
    if item.problem:
        _draw_text(box, item.problem, width, alert=True)
    else:
        box.label(text=tr("Derived values (not parameters)"), translate=False)
        _draw_text(box, item.derived, width)
        _draw_text(box, item.min_length, width)
    box.label(text=tr("Parameters"), translate=False)
    for line in item.parameters:
        block = box.column(align=True)
        block.enabled = writable
        _draw_text(block, f"{line.name}:", width)
        _draw_text(block, line.text, width)
        if line.source:
            _draw_text(block, line.source, width)
        if line.registered:
            button = block.operator(SET_PARAMETER, text=tr("Change…"), translate=False)
            button.key = line.key
    edit = box.row()
    edit.enabled = writable
    button = edit.operator(SAVE_ROAD_PROFILE, text=tr("Complete or rename…"), icon="GREASEPENCIL", translate=False)
    button.code = item.code


def draw_road_profiles(layout: Any, context: Any) -> None:
    """La ventana de Perfil de pista… (véase el módulo), de lo ya leído: la lista, el elegido, «Perfil nuevo…» y el último resultado; con la
    escritura no disponible (sin proyecto, en solo lectura o con la versión activa no editable: RF-017-29) lo que escribe sale desactivado y el
    motivo dicho en ámbar."""
    shown = view()
    if shown is None:
        return
    blocked = _write_unavailable()
    writable = blocked is None
    width = labels.dialog_width(PROFILES_WIDTH_PX)
    _draw_blocked(layout, blocked, width)
    create = layout.row()
    create.enabled = writable
    button = create.operator(SAVE_ROAD_PROFILE, text=tr("New profile…"), icon="ADD", translate=False)
    button.code = ""
    if not len(shown.road_profiles):
        labels.draw_wrapped(layout, tr(
            "There are no road profiles yet: create one with its vehicle width, carriageway factor, gradients, radii, slope angles "
            "and normative class"), width, icon="INFO")
    else:
        layout.label(text=tr("Road profiles: {count}", count=len(shown.road_profiles)), translate=False)
        layout.template_list(ROAD_PROFILES_LIST, "", shown, "road_profiles", shown, "road_profile_index", rows=PROFILE_ROWS)
        index = min(max(shown.road_profile_index, 0), len(shown.road_profiles) - 1)
        _draw_road_chosen(layout, shown.road_profiles[index], width, writable)
    if len(shown.road_profile_report):
        box = layout.box()
        box.label(text=tr("Last result"), translate=False)
        for line in shown.road_profile_report:
            _draw_text(box, line.name, width, alert=bool(line.alert))


class GEOBLENDER_PT_des_road_profiles(bpy.types.Panel):
    """Road profiles of the project: their values, their source and type and their derived widths, and the orders to create, complete,
    rename and change them"""

    bl_idname = ROAD_PROFILES_PANEL
    bl_label = "Road profiles"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = PROFILES_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_road_profiles(self.layout, context)


# --- Sectores de diseño… (T23; HU-013-2; RF-013-07, RF-013-08, RF-013-10, RF-013-21) ----------


class GEOBLENDER_UL_des_sectors(bpy.types.UIList):
    """Design sectors with their area, the slope they impose and the state of their search"""

    bl_idname = SECTORS_LIST

    def draw_item(self, context: Any, layout: Any, data: Any, item: Any, icon: int,
                  active_data: Any, active_propname: str, index: int = 0,
                  flt_flag: int = 0) -> None:
        split = layout.split(factor=SECTOR_NAME_FACTOR, align=True)
        split.label(text=item.name, translate=False)
        rest = split.split(factor=SECTOR_AREA_FACTOR, align=True)
        rest.label(text=item.area, translate=False)
        more = rest.split(factor=SECTOR_SLOPE_FACTOR, align=True)
        slope = more.row(align=True)
        slope.alert = bool(item.problem)
        slope.label(text=item.slope or NOT_SHOWN, translate=False)
        state = more.row(align=True)
        state.alert = bool(item.pending)
        state.label(text=tr("Search pending") if item.pending else tr("Search in force"),
                    icon="ERROR" if item.pending else "CHECKMARK", translate=False)


def _draw_sector(layout: Any, item: Any, width: float, writable: bool) -> None:
    """El sector elegido: su nombre y su código, su área, el estado de su búsqueda (en ámbar si
    está pendiente, con la orden de la 012 para hacerla), el talud que impone con su origen, su
    decisor y su ámbito, el perfil asignado y «Fijar el talud del sector…» (RF-013-07)."""
    box = layout.box()
    box.label(text=item.name, translate=False)
    if item.code:
        _draw_text(box, tr("Code: {code}", code=item.code), width)
    _draw_text(box, tr("Area: {area}", area=item.area), width)
    _draw_text(box, item.search, width, alert=bool(item.pending))
    if item.pending:
        _draw_text(box, tr("The search of untouchable elements is mandatory before designing: "
                           "{path}", path=path_text(catalog(), FIND_UNTOUCHABLES, language())),
                   width)
        search = box.row()
        search.enabled = writable
        search.operator(FIND_UNTOUCHABLES, text=_label(FIND_UNTOUCHABLES), icon="VIEWZOOM",
                        translate=False)
    if item.slope:
        _draw_text(box, tr("Maximum general slope imposed: {slope}", slope=item.slope), width)
        _draw_text(box, item.slope_source, width)
    else:
        _draw_text(box, tr("No maximum general slope imposed"), width)
    if item.problem:
        _draw_text(box, item.problem, width, alert=True)
    _draw_text(box, tr("Profile assigned: {profile}", profile=item.profile_name or NOT_SHOWN),
               width)
    edit = box.row()
    edit.enabled = writable
    button = edit.operator(SET_SECTOR_SLOPE, text=_label(SET_SECTOR_SLOPE), icon="GREASEPENCIL",
                           translate=False)
    button.code = item.code


def _draw_orphans(layout: Any, shown: Any, width: float) -> None:
    """Los taludes de los sectores que ya no existen, en una lista aparte y en ámbar (RF-013-10):
    no se borran nunca; la persona declara el valor en el sector que los sustituye."""
    if not len(shown.orphans):
        return
    box = layout.box()
    box.label(text=tr("Parameters without a sector: {count}", count=len(shown.orphans)),
              translate=False)
    _draw_text(box, tr("These values belong to sectors that no longer exist (renamed or "
                       "removed). They are never deleted: set the value again in the sector "
                       "that replaces them"), width)
    for line in shown.orphans:
        _draw_text(box, line.name, width, alert=bool(line.alert))


def _draw_declare(layout: Any, writable: bool) -> None:
    """«Declarar de nuevo desde una capa…» (RF-013-07, RF-013-10): la capa de polígonos y el
    campo del nombre de la 012 y la orden de la 013 que lanza la suya de declarar los sectores
    (``core_declare_sectors``, que conserva los valores de los sectores que mantienen su código) y
    vuelve a leer esta ventana sin cerrarla (T44)."""
    other = constraint_panels.view()
    box = layout.box()
    box.label(text=tr("Declare the sectors from a layer of polygons"), translate=False)
    form = box.column()
    form.enabled = writable
    if other is not None:
        form.prop_search(other, "sector_layer", other, "sector_sources",
                         text=tr("Layer of the sectors"), translate=False)
        form.prop(other, "sector_field", text=tr("Field of the name"), translate=False)
    form.operator(DECLARE_SECTORS_AGAIN, text=tr("Declare again from a layer…"), icon="CHECKMARK",
                  translate=False)


def draw_sectors(layout: Any, context: Any) -> None:
    """La ventana de Sectores de diseño… (véase el módulo), de lo ya leído."""
    shown = view()
    if shown is None:
        return
    blocked = _write_unavailable()
    writable = blocked is None
    width = labels.dialog_width(SECTORS_WIDTH_PX)
    _draw_blocked(layout, blocked, width)
    if not len(shown.sectors):
        labels.draw_wrapped(layout, tr(
            "There is no action perimeter or legal limit and no sectors are declared: declare "
            "the legal limit first with {path}",
            path=path_text(catalog(), EDIT_LIMITS, language())), width, icon="INFO")
    else:
        layout.label(text=tr("Design sectors: {count}", count=len(shown.sectors)),
                     translate=False)
        layout.template_list(SECTORS_LIST, "", shown, "sectors", shown, "sector_index",
                             rows=SECTOR_ROWS)
        index = min(max(shown.sector_index, 0), len(shown.sectors) - 1)
        _draw_sector(layout, shown.sectors[index], width, writable)
    _draw_orphans(layout, shown, width)
    _draw_declare(layout, writable)
    if len(shown.sector_report):
        box = layout.box()
        box.label(text=tr("Last result"), translate=False)
        for line in shown.sector_report:
            _draw_text(box, line.name, width, alert=bool(line.alert))


class GEOBLENDER_PT_des_sectors(bpy.types.Panel):
    """Design sectors: their area, the state of their search, the maximum general slope they
    impose with its source and decider, and the profile assigned to each"""

    bl_idname = SECTORS_PANEL
    bl_label = "Design sectors"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = SECTORS_PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_sectors(self.layout, context)


# --- La barra N «Diseño»: el dato del objeto activo (T27; RF-013-32, RF-013-06) -------------------

SELECTED_PANEL = "GEOBLENDER_PT_des_design"
SELECTED_TAB = "Design"  # msgid de la pestaña y del título de la barra N
EXPORT_GRID = "geoblender.des_export_design_grid"  # su botón: «Exportar rejilla a GeoTIFF…» (T28)
MAX_CONSTRAINT_LINES = 10
"""Cuántas restricciones aplicadas enseña la barra N; de las demás, cuántas más hay."""
_LIMIT_CHECKED = frozenset({design_provenance.QUARRY, design_provenance.EDGE_TRANSITION,
                            design_provenance.FILL_ONLY, design_provenance.REFIT})
"""Los tipos de operación cuyas superficies se comprueban contra el límite vigente en la barra N
(los de ``design.store.LIMIT_CHECKED_TYPES``, sin importar el cálculo al habilitar)."""


@dataclass(frozen=True)
class ItemLines:
    """Lo que dice el proyecto del dato de un objeto de diseño (:func:`item_lines`): su título
    («Superficie de diseño · Hoyo»), las líneas de su ficha (estado, marcas, ajustes, parámetros,
    semillas y dominio, restricciones) y, aparte, sus cifras registradas, que empiezan por la marca de
    la búsqueda pendiente si la hay (sin ``uid``: no es una cifra)."""

    title: str
    lines: tuple[CardLine, ...]
    figures: tuple[CardLine, ...]
    exports: tuple[CardLine, ...] = ()


ROW_EXPORT = "export"
"""Una fila de ``ItemLines.exports`` que es **un botón de exportar** una rejilla a GeoTIFF (spec 016, T34; RF-016-24): su ``uid`` es el
del dato de la rejilla (``source`` de la orden) y su texto, lo que dice el botón. No se dibuja como texto."""
ROW_EXPORT_THICKNESS = "export_thickness"
"""La fila que pide **el botón del espesor** de la entidad activa (``part`` ``thickness``, sin ``source``: la toma la orden de la entidad)."""
_EXPORT_ROWS = (ROW_EXPORT, ROW_EXPORT_THICKNESS)
ROW_CANDIDATES = "candidates"
"""La fila de ``ItemLines.exports`` que es **el botón «Candidatos…»** de una detección con la lista de candidatos (spec 016, T35): abre
``geoblender.des_stockpile_candidates`` con la detección del objeto activo. No se dibuja como texto."""
ROW_DECIDE = "decide"
"""La fila que es **los botones de un candidato pendiente** (convertir, descartar, «Ir a»; T35): su ``uid`` es la clave del candidato (``c01``)
y los botones llaman a ``geoblender.des_stockpile_candidates`` con ella. No se dibuja como texto."""
_BUTTON_ROWS = (*_EXPORT_ROWS, ROW_CANDIDATES, ROW_DECIDE)
ROW_PLACE = "place"
"""Una fila de las listas de la accesibilidad en la barra N (spec 017, T31b; RF-017-25) **con su «Ir a»**: su texto se dibuja como el de cualquier línea y, tras él, un botón (``geoblender.core_go_to_place``) con el
lugar que lleva en su ``uid`` (``x;y;radio``, texto que se lee sin pérdida: ADR-0005). Una fila sin lugar es una ``ROW_FIELD``. En «Elemento activo», donde solo hay texto, se lee como cualquier línea."""
GO_TO_BUTTON_PX = 80
"""Lo que se le quita al ancho de una fila con «Ir a» para el botón (px a escala 1,0)."""
STOCKPILE_CANDIDATES = "geoblender.des_stockpile_candidates"
"""La orden de la lista de candidatos de una detección (T35)."""
EXPORT_PART_THICKNESS = "thickness"
"""El valor de ``part`` de la orden de exportar para el espesor (``design.export.PART_THICKNESS``; ``bl.ui`` no importa el dominio al habilitar)."""


def wanted(context: Any = None) -> str:
    """El ``uid`` del dato que enseña la barra N: el del objeto ``DESIGN`` activo si es de un dato
    del proyecto abierto; si no, ``""``. No lee el proyecto."""
    context = bpy.context if context is None else context
    project = project_session.current()
    if project is None:
        return ""
    obj = active_object(context)
    if object_kind(obj) != des_views.KIND:
        return ""
    props = obj.geoblender
    return str(props.dataset_uid) if str(props.project_uid) == project.uid else ""


def has_preview() -> bool:
    """Si la vista previa de las semillas ha dejado su resumen (:func:`show_preview`)."""
    shown = view()
    return shown is not None and len(shown.preview) > 0


def _family_label(name: str) -> str:
    """El nombre, en el idioma de Geoblender, del tipo de rejilla del dato ``name`` (la envolvente,
    la superficie de diseño, las cotas de berma o el recinto excavable de la 014); vacío si no es
    de ellas."""
    for family, msgid in des_views.LOADERS:
        if name.startswith(des_views.prefix(family)):
            return translate(language(), msgid)
    return ""


def _stored_settings(conn: sqlite3.Connection, version_uid: str, family: str,
                     name: object) -> Mapping[str, Any] | None:
    """Los ajustes de la operación que escribió el dato de la familia ``family`` y la operación
    ``name`` en la versión ``version_uid``; ``None`` si la versión ya no lo tiene."""
    from ...core.datasets import registry as dataset_registry  # al usarlo: habilitar no lo carga

    if not isinstance(name, str) or not name:
        return None
    dataset = design_provenance.dataset_name(family, name)
    record = dataset_registry.get(conn, dataset, version_uid=version_uid)
    if record is None or record.name != dataset:
        return None
    row = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?",
                       (record.operation_uid,)).fetchone()
    found = json.loads(str(row[0])) if row is not None and row[0] else None
    return found if isinstance(found, dict) else None


def parameter_line(used: Any, version_code: str) -> CardLine:
    """Un parámetro que leyó la operación (``core.provenance.lineage.ParameterLink``): su nombre, su
    valor con su unidad y su insignia de tipo («Altura de banco · expl_10_60_6: 10 m [ADO]»), su
    ámbito («el proyecto» o la versión), su origen y quién lo decidió; si hoy vale otra cosa, lo de
    hoy, y en alerta. Aquí solo se escribe."""
    shown = language()
    value = f"{used.value_text(language=shown)} {provenance.badge(used.kind)}"
    if used.unconfirmed:
        value = f"{value} {tr('unconfirmed')}"
    scope = tr("the project") if used.scope == "project" else (version_code or str(used.scope))
    origin = [str(used.source or ""),
              tr("decided by {person}", person=used.decided_by) if used.decided_by else ""]
    parts = [f"{parameter_label(used.key, shown) or used.key}: {value}", scope,
             *(part for part in origin if part)]
    if used.changed:
        today = f"{used.current_value_text(language=shown)} {provenance.badge(used.current_kind)}"
        parts.append(tr("today: {value}", value=today))
    return CardLine(ROW_FIELD, " · ".join(parts), alert=bool(used.changed or used.source_stale))


def _zone_text(zone: Zone, constraints: Mapping[str, str], sectors: Mapping[str, str]) -> str:
    """La zona de las semillas como se lee: el dominio por defecto, «zona de «Hoyo»» (su
    restricción), «sector «Sector 1»» o «capa «x»»."""
    if zone.kind is ZoneKind.DOMAIN:
        return tr("default domain")
    name = str(zone.name or "")
    if zone.kind is ZoneKind.CONSTRAINT:
        return tr("zone of «{name}»", name=constraints.get(name) or name)
    if zone.kind is ZoneKind.SECTOR:
        return tr("sector «{name}»", name=sectors.get(name) or name)
    return tr("layer «{name}»", name=name)


def _domain_text(domain: WorkDomain, sectors: Mapping[str, str]) -> str:
    """El acotado del dominio de trabajo como se lee: todo el de las máscaras, unos sectores, una
    capa o los dos."""
    names = ", ".join(f"«{sectors.get(code) or code}»" for code in domain.sectors)
    if domain.sectors and domain.layer:
        return tr("Work domain: bound to the sectors {sectors} and to the layer «{layer}»",
                  sectors=names, layer=domain.layer)
    if domain.sectors:
        return tr("Work domain: bound to the sectors {sectors}", sectors=names)
    if domain.layer:
        return tr("Work domain: bound to the layer «{layer}»", layer=domain.layer)
    return tr("Work domain: the whole domain of the masks")


def seed_lines(request: EnvelopeRequest, constraints: Mapping[str, str],
               sectors: Mapping[str, str]) -> list[CardLine]:
    """Las semillas y el dominio de trabajo de una envolvente (RF-013-01, RF-013-02; los ajustes que
    guardó, ``design.provenance.envelope_request``): de dónde salen las semillas y su zona, y el
    acotado del dominio. ``constraints`` y ``sectors`` dan el nombre de cada código."""
    seeds = request.seeds
    origin = _seed_origin(seeds)
    text = (tr("Seeds: {origin} · {zone}", origin=origin,
               zone=_zone_text(seeds.zone, constraints, sectors))
            if seeds.zone is not None else tr("Seeds: {origin}", origin=origin))
    return [CardLine(ROW_FIELD, text), CardLine(ROW_FIELD, _domain_text(request.domain, sectors))]


def _seed_origin(seeds: SeedSource) -> str:
    """De dónde salen unas semillas de la 013 como se lee: «celdas de «Ladera»», «cota fija 90 m» o
    «rejilla de cotas «x»»."""
    if seeds.kind is SeedKind.SURFACE:
        return tr("cells of «{surface}»", surface=seeds.surface)
    if seeds.kind is SeedKind.FIXED:
        return tr("fixed elevation {elevation} m",
                  elevation=format_value(float(seeds.elevation_m or 0.0), language()))
    return tr("grid of elevations «{grid}»", grid=seeds.grid)


# --- La ficha de una cantera con dos superficies (spec 014, T22; RF-014-15, RF-014-16) ------------


def _quarry_profile_lines(settings: Mapping[str, Any], profile_names: Mapping[str, str],
                          sectors: Mapping[str, str]) -> list[CardLine]:
    """Los perfiles de banco de cada superficie de una cantera (sus ajustes ``final`` y
    ``exploitation``), por su nombre: «Perfiles de la superficie final: base REST_5_35_6»."""
    def assigned(side: Surface) -> str:
        found = settings.get(side.value)
        return profiles_text(found, profile_names, sectors) if isinstance(found, Mapping) else ""

    lines: list[CardLine] = []
    final, exploitation = assigned(Surface.FINAL), assigned(Surface.EXPLOITATION)
    if final:
        lines.append(CardLine(ROW_FIELD, tr("Profiles of the final surface: {profiles}",
                                            profiles=final)))
    if exploitation:
        lines.append(CardLine(ROW_FIELD, tr("Profiles of the exploitation surface: {profiles}",
                                            profiles=exploitation)))
    return lines


def _quarry_layer_lines(request: QuarryRequest, constraints: Mapping[str, str],
                        sectors: Mapping[str, str]) -> list[CardLine]:
    """Las capas que leyó una cantera, cada una con sus campos (plan 014 §5.2.1): los fondos, las
    zonas a conservar, los corredores, las zonas de restauración por relleno, las láminas de agua y
    las zonas de «explotación hasta la final»; con su encabezado, o ninguna línea si no usó
    ninguna."""
    label = constraint_panels.layer_label
    lines: list[CardLine] = []
    if request.floors is not None:
        lines.append(CardLine(ROW_FIELD, tr("{what}: layer «{layer}» · field «{field}»",
                                            what=tr("Floors"), layer=label(request.floors.layer),
                                            field=request.floors.field)))
    lines += [CardLine(ROW_FIELD, tr("{name}: {value}", name=tr("Zone to conserve"),
                                     value=_zone_text(zone, constraints, sectors)))
              for zone in request.conserve]
    corridors = request.corridors
    if corridors is not None and corridors.has_gradient:
        lines.append(CardLine(ROW_FIELD, tr(
            "Corridors: layer «{layer}» · width «{width}» · start elevation «{start}» · "
            "gradient «{gradient}»", layer=label(corridors.layer), width=corridors.width_field,
            start=corridors.start_level_field, gradient=corridors.gradient_field)))
    elif corridors is not None:
        lines.append(CardLine(ROW_FIELD, tr(
            "Corridors: layer «{layer}» · width «{width}» · elevation «{level}»",
            layer=label(corridors.layer), width=corridors.width_field,
            level=corridors.level_field)))
    if request.fill_zones:
        lines.append(CardLine(ROW_FIELD, tr("{what}: layer «{layer}»",
                                            what=tr("Restoration fill zones"),
                                            layer=label(request.fill_zones))))
    if request.water is not None:
        lines.append(CardLine(ROW_FIELD, tr("{what}: layer «{layer}» · field «{field}»",
                                            what=tr("Water sheets"),
                                            layer=label(request.water.layer),
                                            field=request.water.field)))
    if ToFinalMode(request.to_final) is ToFinalMode.LAYER and request.to_final_layer:
        lines.append(CardLine(ROW_FIELD, tr("{what}: layer «{layer}»",
                                            what=tr("Exploitation down to the final surface"),
                                            layer=label(request.to_final_layer))))
    return [CardLine(ROW_HEADING, tr("Layers")), *lines] if lines else []


def _water_lines(settings: Mapping[str, Any]) -> list[CardLine]:
    """La capa de láminas de agua de un diseño «solo relleno» con su campo de cota (sus ajustes
    ``water``; spec 014, T30; RF-014-24): «Láminas de agua: capa «laminas» · campo «cota»»; ninguna
    línea sin láminas."""
    water = settings.get("water")
    if not isinstance(water, Mapping) or not water.get("layer"):
        return []
    return [CardLine(ROW_FIELD, tr("{what}: layer «{layer}» · field «{field}»",
                                   what=tr("Water sheets"),
                                   layer=constraint_panels.layer_label(str(water["layer"])),
                                   field=str(water.get("field") or "")))]


def _quarry_seed_lines(request: QuarryRequest | None, constraints: Mapping[str, str],
                       sectors: Mapping[str, str]) -> list[CardLine]:
    """Las semillas de cada superficie de una cantera («Coronación y zonas a sostener» o las de la
    013 con su zona) y su dominio de trabajo, el recinto excavable de las máscaras (RF-014-01,
    RF-014-02); si sus ajustes no se pueden leer, lo dice."""
    if request is None:
        return [CardLine(ROW_NONE, tr("The seeds and the domain are not recorded"))]
    lines: list[CardLine] = []
    for side, name in ((request.final, tr("Seeds of the final surface")),
                       (request.exploitation, tr("Seeds of the exploitation surface"))):
        seeds = side.seeds
        if seeds is None:
            value = tr("Crown and zones to hold")
        elif seeds.zone is None:
            value = _seed_origin(seeds)
        else:
            value = f"{_seed_origin(seeds)} · {_zone_text(seeds.zone, constraints, sectors)}"
        lines.append(CardLine(ROW_FIELD, tr("{name}: {value}", name=name, value=value)))
    lines.append(CardLine(ROW_FIELD, tr("Work domain: the excavation boundary of the masks")))
    return lines


def _legend_lines() -> list[CardLine]:
    """La leyenda de la clasificación de una cantera (``des_views.CLASS_LEGEND``): su encabezado y
    una línea por clase, con su código y su color en la vista (RF-014-15)."""
    shown = language()
    return [CardLine(ROW_HEADING, tr("Legend")),
            *(CardLine(ROW_FIELD, translate(shown, msgid))
              for _code, _color, msgid in des_views.CLASS_LEGEND)]


def _quarry_request(settings: Mapping[str, Any], name: str) -> QuarryRequest | None:
    """La cantera que guardan los ajustes ``settings`` (``design.provenance.quarry_request``), o
    ``None`` si no se pueden leer (lo deja en el registro técnico con el nombre del dato
    ``name``)."""
    try:
        return design_provenance.quarry_request(settings)
    except ValueError:
        LOGGER.info("Los ajustes de la cantera de «%s» no se pueden leer", name, exc_info=True)
        return None


def profiles_text(settings: Mapping[str, Any], profile_names: Mapping[str, str],
                  sectors: Mapping[str, str]) -> str:
    """Los perfiles de banco asignados que guardó la operación (RF-013-21): el base y el de cada
    sector, por su nombre («base EXPL_10_60_6 · Sector 2: REST_5_35_6»); vacío si no asignó ninguno.
    ``profile_names`` da el nombre de cada código de perfil y ``sectors``, el de cada sector."""
    parts: list[str] = []
    base = settings.get("base_profile")
    if isinstance(base, str) and base:
        parts.append(tr("base {profile}", profile=profile_names.get(base) or base))
    assigned = settings.get("sector_profiles")
    for code, profile in (assigned.items() if isinstance(assigned, Mapping) else ()):
        parts.append(f"{sectors.get(code) or code}: {profile_names.get(profile) or profile}")
    return " · ".join(parts)


LIMIT_PHASE = "limit_check"
"""La fase de los pasos de la comprobación de las superficies contra el límite vigente."""
LIMIT_TICK_S = 0.05
"""Cada cuánto vuelve el temporizador de la comprobación de fondo (:func:`limit_tick`)."""
LIMIT_BUDGET_S = 0.05
"""Lo que avanza la comprobación de fondo en cada llamada, como mucho (más su última unidad, de
≈ 0,1 s como mucho: RNF-014-02)."""


@dataclass
class _LimitChecks:
    """La caché en memoria de la comprobación contra el límite vigente
    (``design.store.LimitCheckMemo``, creada al usarla: habilitar no carga el cálculo) y la
    comprobación de fondo en marcha (sus unidades, el proyecto y la versión)."""

    held: Any = None
    work: Iterator[None] | None = None
    target: tuple[str, str] | None = None
    project: Any = None

    def memo(self) -> Any:
        """La caché (``design.store.LimitCheckMemo``)."""
        if self.held is None:
            from ...design import store as design_store  # al usarlo

            self.held = design_store.LimitCheckMemo()
        return self.held

    def stop(self) -> None:
        """Deja la comprobación de fondo (sus unidades se cierran sin guardar nada)."""
        work, self.work, self.target, self.project = self.work, None, None, None
        if work is not None:
            work.close()  # type: ignore[attr-defined]


_LIMITS = _LimitChecks()


def _progress[T](work: Generator[None, None, T], message: str) -> Generator[Progress, None, T]:
    """Las unidades de ``work`` como ``Progress`` de :data:`LIMIT_PHASE` con ``message``; devuelve
    lo que devuelve ``work``. Cerrarlo cierra ``work``."""
    try:
        while True:
            try:
                next(work)
            except StopIteration as stop:
                return stop.value  # type: ignore[no-any-return]
            yield Progress(LIMIT_PHASE, 0, 0, message)
    finally:
        work.close()


def limit_steps(project: Any, version_uid: str) -> Iterator[Progress]:
    """Lo que añade la 014 al resumen de una compilación de las máscaras de la versión
    ``version_uid`` (spec 014, T31; RF-014-26; ``constraint_panels.add_compile_check``), **por
    pasos** (T35; RNF-014-02): la comprobación de las superficies de diseño de la versión que se
    pueden ajustar (``design.store.REFIT_SOURCES``) contra el límite vigente, que llena la caché
    (:data:`_LIMITS`), un ``Progress`` por unidad; el último lleva, en alerta, el aviso de cada
    superficie de la 014 (``design.store.LIMIT_CHECKED_TYPES``) que mueve algo fuera de él, con su
    volumen y su área; ninguna línea si no queda nada fuera. Solo lee."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo

    message = tr("Checking the design surfaces against the current limit…")
    found = yield from _progress(_LIMITS.memo().fill_steps(
        project, version_uid, types=design_store.REFIT_SOURCES), message)
    shown = language()
    yield Progress(LIMIT_PHASE, 1, 1, message, result=[
        constraint_panels.Line(check.notice.text(shown), alert=True) for op_type, check in found
        if op_type in design_store.LIMIT_CHECKED_TYPES and check.notice is not None])


def _check_later(project: Any, version_uid: str) -> None:
    """Lanza la comprobación de las superficies de la versión ``version_uid`` en el temporizador
    :func:`limit_tick` (por pasos; llena la caché y vuelve a leer la ficha), si no está ya en marcha
    para ella; una de otra versión o de otro proyecto se deja."""
    from ...design import store as design_store  # al usarlo: habilitar no carga el cálculo

    target = (str(project.uid), version_uid)
    if _LIMITS.work is not None and _LIMITS.target == target:
        return
    _LIMITS.stop()
    _LIMITS.work = _LIMITS.memo().fill_steps(project, version_uid,
                                             types=design_store.REFIT_SOURCES)
    _LIMITS.target, _LIMITS.project = target, project
    if not bpy.app.timers.is_registered(limit_tick):
        bpy.app.timers.register(limit_tick, first_interval=LIMIT_TICK_S, persistent=True)


def _reread_cards() -> None:
    """Vuelve a leer la ficha del objeto activo («Elemento activo») y la de la barra N «Diseño»."""
    try:
        view_panels.read_card()
    except Exception:  # noqa: BLE001 - lo que llama Blender no lo tumba
        LOGGER.exception("Falló la lectura de la ficha del objeto activo")
    read_selected_safely()


def limit_tick() -> float | None:
    """El temporizador de la comprobación de fondo (spec 014, T35; RNF-014-02): avanza sus unidades
    durante :data:`LIMIT_BUDGET_S` como mucho y vuelve en :data:`LIMIT_TICK_S`; al terminar, con la
    caché ya llena, vuelve a leer la ficha. Sin comprobación, o con otro proyecto en la sesión, se
    quita. Un fallo va al registro técnico (la ficha sigue sin la línea)."""
    work = _LIMITS.work
    if work is None:
        return None
    if project_session.current() is not _LIMITS.project:
        _LIMITS.stop()
        return None
    started = time.perf_counter()
    try:
        while True:
            next(work)
            if time.perf_counter() - started >= LIMIT_BUDGET_S:
                return LIMIT_TICK_S
    except StopIteration:
        _LIMITS.work = _LIMITS.target = _LIMITS.project = None
    except Exception:  # noqa: BLE001 - lo que llama Blender no lo tumba
        LOGGER.exception("Falló la comprobación de las superficies contra el límite vigente")
        _LIMITS.stop()
        return None
    _reread_cards()
    return None


def forget_limit_checks() -> None:
    """Vacía la caché de la comprobación y deja la de fondo (al cerrar el proyecto o abrir otro, y
    al desactivar Geoblender)."""
    _LIMITS.stop()
    if _LIMITS.held is not None:
        _LIMITS.held.clear()


def _outside_lines(project: Any, version_uid: str, uid: str) -> list[CardLine]:
    """La ficha de una superficie de diseño de la 014 (el dato ``uid`` de la versión
    ``version_uid``) que mueve algo fuera del límite vigente de su versión: su aviso, en alerta
    (spec 014, T31; RF-014-26); ninguna línea si no deja nada fuera, si no es una superficie de la
    014 o si las máscaras no están al día. **De la caché** (T35; RNF-014-02): sin acierto, ninguna
    línea y la comprobación por pasos en el temporizador (:func:`limit_tick`), que vuelve a leer la
    ficha al terminar. Si no se puede comprobar, lo deja en el registro técnico."""
    try:
        checks = _LIMITS.memo().lookup(project, version_uid, names=(uid,))
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.info("No se pudo comprobar «%s» contra el límite vigente", uid, exc_info=True)
        return []
    if checks is None:  # sin acierto: la ficha no se bloquea
        _check_later(project, version_uid)
        return []
    shown = language()
    return [CardLine(ROW_FIELD, check.notice.text(shown), alert=True) for check in checks
            if check.notice is not None]


def _constraint_lines(listed: Sequence[Any], version_code: str) -> list[CardLine]:
    """Las restricciones activas en la versión (``gis.masks.store.ListedConstraint``), cada una con su
    tipo y su nombre; las que pasan de :data:`MAX_CONSTRAINT_LINES`, contadas."""
    shown = language()
    active = [item.constraint for item in listed if item.state == "active"]
    if not active:
        return [CardLine(ROW_NONE, tr("No constraint is active in {version}",
                                      version=version_code or tr("the project")))]
    lines: list[CardLine] = []
    for item in active[:MAX_CONSTRAINT_LINES]:
        kind = constraint_panels.type_label("" if item.ctype is None else item.ctype.value)
        name = constraint_views.constraint_text(item, shown)  # la declarada, por su entidad
        lines.append(CardLine(ROW_FIELD, f"{kind} · {name}"))
    if len(active) > MAX_CONSTRAINT_LINES:
        lines.append(CardLine(ROW_NONE, tr("… and {count} more",
                                           count=len(active) - MAX_CONSTRAINT_LINES)))
    return lines


def _seed_card(settings: Mapping[str, Any], envelope_settings: Mapping[str, Any] | None,
               constraints: Mapping[str, str], sectors: Mapping[str, str],
               name: str) -> list[CardLine]:
    """Las semillas y el dominio de la ficha de una envolvente o de un escalonado (los de su
    envolvente, ``envelope_settings``; ``None`` si la versión ya no la tiene); si sus ajustes no
    se pueden leer, lo dice (y lo deja en el registro técnico con el nombre del dato ``name``)."""
    try:
        if envelope_settings is None:
            return [CardLine(ROW_NONE, tr("The envelope «{name}» is no longer in this version",
                                          name=str(settings.get("envelope") or "")))]
        return seed_lines(design_provenance.envelope_request(envelope_settings), constraints,
                          sectors)
    except ValueError:
        LOGGER.info("Los ajustes de la envolvente de «%s» no se pueden leer", name, exc_info=True)
        return [CardLine(ROW_NONE, tr("The seeds and the domain are not recorded"))]


def item_lines(project: Any, uid: str) -> ItemLines | None:
    """Lo que dice el proyecto del dato ``uid`` de un diseño (véase el módulo), en una instantánea y
    sin escribir nada; ``None`` si el proyecto ya no lo tiene. Su estado es el de
    ``core.provenance.stale`` (con su causa); los ajustes, los parámetros y la operación, los de
    ``core.provenance.lineage``; la marca de la búsqueda pendiente, la de ``design.sectors`` (en las
    líneas y otra vez como primeras filas de las cifras, ámbar y una por sector pendiente); las
    semillas y el dominio, los de los ajustes de la envolvente (la de un escalonado, la que
    escaló; un recinto excavable de la 014, T20, no tiene: su ficha dice su superficie de
    partida; una rejilla de una cantera, T22, las de cada superficie, con sus perfiles, su
    superficie de partida y las capas que leyó, y la clasificación, además, su leyenda; una
    transición, T28, su superficie de diseño y su superficie de partida, sin semillas; una
    superficie ajustada a un límite nuevo, T33, la superficie de la que sale y su partida, sin
    semillas); las restricciones, las activas en su versión (``gis.masks.store``) y las cifras, las de su
    operación. Los errores del proyecto (``GeoblenderError``, ``sqlite3.Error``) siguen."""
    from ...core.provenance import lineage as prov_lineage  # al usarlo: habilitar no lo carga
    from ...core.provenance import stale as prov_stale
    from ...core.versions import read as versions_read
    from ...core.views import card
    from ...design.sectors import design_sectors, pending_marks
    from ...gis.masks import store as masks_store
    from ...gis.polygons import drain

    shown = language()
    with project.read() as conn:
        found = card.item_card(project, uid, conn=conn)
        if found is None:
            return None
        tree = prov_lineage.lineage(project, uid, conn=conn, language=shown)
        link = tree.operations[tree.root]
        cause = (prov_stale.item_text(conn, prov_stale.DATASET, uid, language=shown)
                 if found.stale else None)
        owner = versions_read.dataset_versions(conn, [uid]).get(uid, "")
        constraints = {code: name for code, (name, _kind) in
                       constraint_views.shown_names(conn, owner or None).items()}
        profile_names = design_profiles.profile_names(conn)
        settings = link.settings
        area = link.op_type == design_provenance.EXCAVATION_AREA  # un recinto: sin semillas
        quarry = link.op_type == design_provenance.QUARRY  # una cantera: las de sus dos lados
        # Una transición (T28): sin semillas ni envolvente; su superficie de diseño y su partida.
        transition = link.op_type == design_provenance.EDGE_TRANSITION
        # Un ajuste a un límite nuevo (T33): tampoco; la superficie que ajusta y su partida.
        refit = link.op_type == design_provenance.REFIT
        # Lo que dejan los acopios y los cuerpos apoyados (T33; la base, el espesor, el terreno sin acopios): sin envolvente, sin semillas ni
        # partida de un diseño; la entidad que lo hizo.
        # Y la accesibilidad de las pistas (spec 017, T31b): lo alcanzable es lo que dejó una entidad, sin semillas ni partida de un diseño.
        made = link.op_type in (*design_provenance.STOCKPILE_DETECT_TYPES, design_provenance.BODY, design_provenance.ROAD_ACCESS)
        access_lines = (_access_object_lines(project, conn, owner, found) if link.op_type == design_provenance.ROAD_ACCESS else [])
        envelope_settings: Mapping[str, Any] | None = settings
        if (link.op_type != design_provenance.ENVELOPE and not area and not quarry
                and not transition and not refit and not made):
            envelope_settings =_stored_settings(conn, owner, design_provenance.ENVELOPE_GRID,
                                                 settings.get("envelope"))  # la que escaló
    version_code = found.revision.code if found.revision is not None else ""
    sectors = design_sectors(project, owner or None)
    names = {sector.code: sector.name for sector in sectors}
    listed = drain(masks_store.shown_constraints_steps(project, version=owner or None))

    # El estado de lo alcanzable es el de **su entidad** (al día, obsoleta con su causa, descartada, «apoyo retirado»: RF-015-25), no solo el del dato.
    lines: list[CardLine] = [access_lines[0] if access_lines else CardLine(ROW_FIELD, cause or tr("Up to date"), alert=bool(found.stale))]
    if owner and link.op_type in _LIMIT_CHECKED:  # una superficie de la 014 fuera del límite (T31)
        lines += _outside_lines(project, owner, uid)
    try:
        touched = design_provenance.settings_touched(settings)
    except ValueError:
        touched = ()
        LOGGER.info("Los sectores que tocó «%s» no se pueden leer", found.record.name)
    marks = [CardLine(ROW_FIELD, mark.text(shown), alert=True)
             for mark in pending_marks(touched, sectors)]
    lines += marks
    if link.settings_text:
        lines.append(CardLine(ROW_FIELD, link.settings_text))
    request = _quarry_request(settings, found.record.name) if quarry else None
    if quarry:  # los perfiles de cada superficie (RF-014-12)
        lines += _quarry_profile_lines(settings, profile_names, names)
    elif assigned := profiles_text(settings, profile_names, names):
        lines.append(CardLine(ROW_FIELD, tr("Profiles: {profiles}", profiles=assigned)))
    if (link.op_type != design_provenance.ENVELOPE and not area and not quarry and not transition
            and not refit and not made):
        lines.append(CardLine(ROW_FIELD, tr("Envelope: «{name}»",
                                            name=str(settings.get("envelope") or ""))))
    if transition:
        lines.append(CardLine(ROW_FIELD, tr("Design surface: «{surface}»",
                                            surface=str(settings.get("surface") or ""))))
    if refit:  # la superficie de diseño de la que sale este dato ajustado (T33)
        lines.append(CardLine(ROW_FIELD, tr("Refitted surface: «{surface}»", surface=str(
            design_provenance.refit_source(settings, found.record.name) or ""))))
    if made:  # la entidad que dejó este dato (su nombre y su código; la barra «Entidad» dice el resto)
        lines.append(CardLine(ROW_FIELD, tr("Made by the entity «{name}» ({code})", name=str(settings.get("name") or found.record.name),
                                            code=str(settings.get("code") or ""))))
        lines += access_lines[1:]  # de una accesibilidad: su resultado leído del proyecto (cotas y listas con su «Ir a»)
    if link.op_type != design_provenance.ENVELOPE and not made:
        start = settings.get("start" if quarry or transition or refit else "surface")
        lines.append(CardLine(ROW_FIELD, tr("Start surface: «{surface}»",
                                            surface=str(start or ""))))
    if request is not None:
        lines += _quarry_layer_lines(request, constraints, names)
    if link.op_type == design_provenance.FILL_ONLY:  # «solo relleno» (T30): su capa de láminas
        lines += _water_lines(settings)
    lines.append(CardLine(ROW_HEADING, tr("Parameters")))
    lines += [parameter_line(used, version_code) for used in link.params] or [
        CardLine(ROW_NONE, tr("No parameters recorded"))]
    # El recinto, la transición, el ajuste y lo que dejan los acopios y los cuerpos no tienen semillas ni acotado.
    if not area and not transition and not refit and not made:
        lines.append(CardLine(ROW_HEADING, tr("Seeds and domains")))
        lines += (_quarry_seed_lines(request, constraints, names) if quarry else
                  _seed_card(settings, envelope_settings, constraints, names, found.record.name))
    lines.append(CardLine(ROW_HEADING, tr("Applied constraints")))
    lines += _constraint_lines(listed, version_code)
    if found.record.name.startswith(des_views.prefix(design_provenance.CLASSIFICATION_GRID)):
        lines += _legend_lines()  # la clasificación de una cantera: un color por clase
    # La marca también junto a las cifras (RF-013-06): una fila por sector pendiente, antes de ellas;
    # es del estado de ahora y no una cifra (sin ``uid``): las registradas no la llevan.
    figures = [CardLine(ROW_HEADING, tr("Figures")), *marks]
    figures += [CardLine(ROW_FIGURE, f"{provenance.badge(figure.kind)} "
                                     f"{design_provenance.figure_text(figure, language=shown)}",
                         uid=figure.uid)
                for figure in found.figures] or [CardLine(ROW_NONE, tr("No figures recorded"))]
    name = str(settings.get("name") or found.record.name)
    return ItemLines(f"{_family_label(found.record.name)} · {name}", tuple(lines), tuple(figures))


# --- La barra N «Entidad»: la entidad de diseño del objeto activo (T28; RF-015-25) ----------------

ENTITY_PANEL = "GEOBLENDER_PT_des_entity"
ENTITY_TAB = "Entity"  # msgid de la pestaña y del título de la barra N «Entidad»
_NOT_CURRENT_TEXT = {
    "stale": "out of date",
    "support_removed": "support removed",
    "discarded": "discarded",
}
"""El estado (``design.entities.EntityState``) de una entidad que no está al día, como se lee junto a su nombre en la
lista de lo que se apoya en otra: el ``msgid`` de su texto."""
_SKIPPED_PARAMS = frozenset({"name", "discarded"})
"""Los parámetros de una entidad que su ficha no repite entre los demás: el nombre es su título y si está descartada lo
dice su estado."""
LIST_LIMIT = 30
"""Cuántos acopios y cuántos candidatos enseña como mucho la barra N de una detección (spec 016, T33): el resto, en una línea («… y 70 acopios
más»). Una lista de cientos de filas no cabe en una barra; todos están en la tabla del proyecto y en la capa de entidades (T34)."""
_CHOICES_TEXT = {
    "mode": {"cut": "In cut", "cut_fill": "In cut and fill", "trace": "Trace", "on_axis": "Over an axis", "axis_3d": "3D axis"},
    "metric": {"exact": "Exact Euclidean", "chamfer5": "Chamfer 5×5"},
    "sense": {"on_base": "On a base", "under_roof": "Under a roof"},
    "data_from": {"field": "A field", "z": "The Z of the vertices", "m": "The M of the vertices"},
}
"""El ``msgid`` del rótulo de cada opción de un parámetro de lista cerrada de una entidad (``valor`` → ``msgid``): el modo y la métrica del
borde de la plataforma y de la retirada y el contrafuerte (T45, E-6), del cuerpo apoyado (T33) su sentido y de dónde se lee el espesor y, de la pista (spec 017, T31b), su modo
(«trazar», «sobre un eje» y «eje 3D»: los del diálogo de «Pista…»)."""


def entity_wanted(context: Any = None) -> str:
    """El ``uid`` del dato que enseña la barra N «Entidad»: el del objeto ``DESIGN_ENTITY`` activo si es de un dato del
    proyecto abierto; si no, ``""``. No lee el proyecto."""
    context = bpy.context if context is None else context
    project = project_session.current()
    if project is None:
        return ""
    obj = active_object(context)
    if object_kind(obj) != entity_views.KIND:
        return ""
    props = obj.geoblender
    return str(props.dataset_uid) if str(props.project_uid) == project.uid else ""


def _entity_name(record: Any) -> str:
    """Una entidad como se nombra en una línea: su nombre y su código, «Carga (PLT-002)»."""
    return f"{record.name} ({record.code})"


def _entity_state_line(project: Any, conn: sqlite3.Connection, version: Any, entry: Any) -> CardLine:
    """El estado de la entidad (RF-015-25, D-12): al día; obsoleta o con el apoyo retirado, con su causa
    (``design.entities.stale_reason``), en alerta; descartada (un registro: no se usa), en alerta; o sin calcular."""
    from ...design import entities  # al usarlo: habilitar no lo carga

    state = str(entry.record.state)
    if state == "discarded":
        return CardLine(ROW_FIELD, tr("Discarded: it stays in the project as a record and is not used"), alert=True)
    if state == "uncalculated":
        return CardLine(ROW_FIELD, tr("Not calculated: it has its parameters in this version and no result"))
    if state in ("stale", "support_removed"):
        cause = entities.stale_reason(project, "" if version is None else version.uid, entry.record.code, language=language(),
                                      conn=conn)
        return CardLine(ROW_FIELD, cause or tr("Out of date"), alert=True)
    return CardLine(ROW_FIELD, tr("Up to date"))


def _badged(text: str, stored: Any) -> str:
    """``text`` con la insignia de tipo de ``stored`` y, si lo está, «sin confirmar»."""
    shown = f"{text} {provenance.badge(stored.kind)}"
    return f"{shown} {tr('unconfirmed')}" if stored.unconfirmed else shown


def _choice_label(param: Any, value: object) -> str | None:
    """El rótulo de la opción de un parámetro de lista cerrada (el modo y la métrica del borde de la plataforma, la retirada y el
    contrafuerte; el sentido y el origen del espesor de un cuerpo, T33), el que lleva en su diálogo: «En corte», no ``cut`` (T45, E-6);
    ``None`` si no es uno de ellos."""
    found = _CHOICES_TEXT.get(str(param), {}).get(str(value))
    return None if found is None else translate(language(), found)


def _entity_value_text(param: Any, stored: Any, listed: Any) -> str:
    """El valor de un parámetro de la entidad con su insignia de tipo (y «sin confirmar»): como los de una operación
    (:func:`~.res_panels.record_text`); de la superficie de partida o de apoyo que es la de otra entidad
    (``entity:PLT-001``), la entidad con su código; y del modo y la métrica, el rótulo de su opción (T45, E-6)."""
    from ...design import entities

    if param in ("start", "support") and isinstance(stored.value, str):
        code = entities.ref_code(stored.value)
        other = None if code is None else listed.get(code)
        if other is not None:
            return _badged(_entity_name(other.record), stored)
    label = _choice_label(param, stored.value)
    return record_text(stored) if label is None else _badged(label, stored)


def _entity_parameter_lines(project: Any, conn: sqlite3.Connection, version: Any, entry: Any, listed: Any
                            ) -> tuple[list[CardLine], dict[Any, Any]]:
    """Los parámetros de la entidad con su insignia de tipo y su origen (RF-015-25; ADR-0013): cada valor de su familia
    ``des.<tipo>.{e}.*`` que tiene el valor propio de la versión o, si no, el del proyecto, como una línea de una
    operación (:func:`parameter_line`): «Pendiente de la rasante de la plataforma: 0 % [ADO] · V01 · capa «x», campo
    «pendiente», entidad «Carga» · decidido por …». Sin valor, solo la superficie de partida (sin elegir, «—»). También
    devuelve los valores almacenados por parámetro (``None``: sin fila), para lo que declara la entidad."""
    from ...design import entities
    from ...design.params import entity_key

    shown = language()
    store = ParameterStore(project)
    found: dict[Any, Any] = {}
    lines: list[CardLine] = []
    for param in entities.entity_type(entry.record.kind).params.names:  # los valores de la familia de su tipo (T33)
        key = entity_key(entry.record.code, param)
        stored = (store.get(key, version=version.uid, conn=conn) if version is not None else None) or store.get(key, conn=conn)
        found[param] = stored
        if param in _SKIPPED_PARAMS or stored is None:
            continue
        if stored.value is None and param != "start":
            continue
        defn = param_definition(key)
        label = translate(shown, defn.label_msgid) if defn is not None and defn.label_msgid else key
        scope = version.code if stored.scope == "version" and version is not None else tr("the project")
        origin = [str(stored.source or ""), tr("decided by {person}", person=stored.decided_by)
                  if stored.decided_by else ""]
        parts = [f"{label}: {_entity_value_text(param, stored, listed)}", scope, *(part for part in origin if part)]
        lines.append(CardLine(ROW_FIELD, " · ".join(parts)))
    return lines, found


def _entity_declared_lines(project: Any, version: Any, entry: Any, stored: Mapping[Any, Any]
                           ) -> list[CardLine]:
    """Las restricciones que declara la entidad (RF-015-25, RF-015-10, RF-015-11): si protege su zona, la restricción de la
    tabla de las declaradas de la versión con su tipo, su nombre como se lee, su **estado** (activa; bloqueada por una edición
    fuera de Geoblender, con qué hacer; «divergente» si lo vigente no es lo que declararían las entidades), su resguardo, su
    motivo y quién la decidió; si protege y su restricción aún no está declarada, lo dice; si no protege, que no declara
    ninguna. Una descartada o sin calcular no declara."""
    from ...design import entities
    from ...design.params import PlatformParam
    from ...gis.masks import store as masks_store  # al usarlo: habilitar no lo carga

    shown = language()
    protect = stored.get(PlatformParam.PROTECT)
    if (version is None or not entities.entity_type(entry.record.kind).has_footprint  # la detección no tiene huella que declarar
            or str(entry.record.state) in ("discarded", "uncalculated") or protect is None or protect.value is not True):
        return [CardLine(ROW_NONE, tr("It declares no constraint"))]
    code = entry.record.code
    guard = stored.get(PlatformParam.GUARD)
    wanted = [item for item in masks_store.listed_constraints(project, version=version.uid)
              if item.declared and item.entity_code == code]
    if not wanted:
        return [CardLine(ROW_FIELD, tr("It protects its zone with {guard} m of guard: its constraint is not declared yet",
                                       guard=NOT_SHOWN if guard is None or guard.value is None
                                       else format_value(guard.value, shown)), alert=True)]
    lines: list[CardLine] = []
    for item in wanted:
        row = item.constraint
        bad = item.state in constraint_panels.BAD_STATES
        kind = constraint_panels.type_label("" if row.ctype is None else row.ctype.value)
        lines.append(CardLine(ROW_FIELD, f"{kind} · {constraint_views.declared_text(code, item.entity_name or code)}",
                              alert=bad))
        lines.append(CardLine(ROW_FIELD, constraint_panels.state_text(item.state, version.code), alert=bad))
        if item.state == "blocked":
            lines.append(CardLine(ROW_FIELD, tr("Accept the edit with a reason or recalculate the declaration: the "
                                                "entity puts it back"), alert=True))
        elif constraint_panels._diverges(project, version):  # noqa: SLF001 - la misma comparación que la ventana
            lines.append(CardLine(ROW_FIELD, tr("The declaration differs from the one of the entities"), alert=True))
        lines.append(CardLine(ROW_FIELD, tr("Guard: {value} m", value=NOT_SHOWN if item.buffer_out_m is None
                                            else format_value(float(item.buffer_out_m), shown))))
        lines.append(CardLine(ROW_FIELD, tr("Reason: {value}", value=row.reason or NOT_SHOWN)))
        lines.append(CardLine(ROW_FIELD, tr("Decided by: {value}", value=row.decided_by or NOT_SHOWN)))
    return lines


def _entity_chain_lines(listed: Any, entry: Any) -> list[CardLine]:
    """La cadena de la entidad (RF-015-25, RF-015-04): de qué superficie parte (el terreno, una de diseño o la de otra
    entidad), qué entidad parte de la suya y cuál es la última de su cadena; si los datos de la cadena no son válidos
    (un ciclo, dos entidades desde la misma superficie), lo dice."""
    from ...design import entities

    record = entry.record
    if record.start is None:
        start = CardLine(ROW_FIELD, tr("Starts from: {surface}", surface=NOT_SHOWN))
    elif (code := entities.ref_code(record.start)) is not None and (before := listed.get(code)) is not None:
        start = CardLine(ROW_FIELD, tr("Starts from the surface of {entity}", entity=_entity_name(before.record)),
                         alert=str(before.record.state) == "discarded")
    else:
        start = CardLine(ROW_FIELD, tr("Starts from: {surface}", surface=record.start))
    lines = [start]
    try:
        following = entities.successor_of(listed.records, record.code)
        tail = entities.chain_of(listed.records, record.code)[-1]
    except design_messages.DesignError as exc:
        return [*lines, CardLine(ROW_FIELD, tr("The chain cannot be read: {error}", error=design_error_text(exc)),
                                 alert=True)]
    lines.append(CardLine(ROW_FIELD, tr("The entity that starts from its surface: {entity}", entity=_entity_name(following))
                          if following is not None else tr("No entity starts from its surface")))
    lines.append(CardLine(ROW_FIELD, tr("It is the last of its chain") if tail.code == record.code
                          else tr("Last of its chain: {entity}", entity=_entity_name(tail))))
    return lines


def _entity_dependent_line(item: Any) -> CardLine:
    """Una fila de la lista de lo que se apoya en la entidad (o de en qué se apoya; ``design.entities.Dependent``): su
    texto —el nombre, el tipo y los m³ apoyados, o «superficie de partida»— y, si no está al día, su estado, en alerta."""
    shown = language()
    if item.op_type.startswith("des."):
        text = item.text(shown)
    else:  # una superficie que no es de una entidad ni de un diseño: el terreno de partida
        text = tr("{name}: start surface", name=item.name)
    if getattr(item, "stockpile", None):  # de un acopio de una detección (T33): en cuál de ellos
        text = f"{text} · {tr('on the stockpile «{stockpile}»', stockpile=item.stockpile)}"
    msgid = _NOT_CURRENT_TEXT.get(str(item.state))
    if msgid is None:
        return CardLine(ROW_FIELD, text)
    return CardLine(ROW_FIELD, f"{text} · {translate(shown, msgid)}", alert=True)


def dependent_texts(items: Sequence[Any]) -> list[tuple[str, bool]]:
    """Las filas de una lista de dependencias de una entidad (``design.entities.Dependent``: lo que se apoya en ella o en
    qué se apoya) como las enseña la barra N «Entidad» (:func:`_entity_dependent_line`): ``(texto, alerta)``, el texto con el
    nombre, el tipo y los m³ apoyados (o «superficie de partida») y, si no está al día, su estado; la alerta, para lo que no lo
    está. La ventana de «Lo que se apoya en ella» del menú «Entidad ▾» (T31; RF-015-28) la dibuja con ellas."""
    return [(line.text, line.alert) for line in map(_entity_dependent_line, items)]


def _entity_figures(conn: sqlite3.Connection, entry: Any) -> list[CardLine]:
    """Las cifras registradas de la operación de la entidad con su insignia de tipo (CALCULADO, con su unidad), menos el
    volumen apoyado de cada entidad (``des.supported_m3``: va en la lista de en qué se apoya). Sin operación, ninguna."""
    from ...core.provenance import figures as prov_figures  # al usarlo: habilitar no lo carga

    shown = language()
    found: list[Any] = []
    if entry.operation_uid is not None:
        found = [prov_figures.FigureRecord.from_row(row) for row in conn.execute(
            f"SELECT {prov_figures.RECORD_COLUMNS} FROM gb_figure AS f WHERE f.operation_uid = ? ORDER BY f.fid",
            (entry.operation_uid,))]
    lines = [CardLine(ROW_FIGURE, f"{provenance.badge(figure.kind)} {design_provenance.figure_text(figure, language=shown)}",
                      uid=figure.uid)
             for figure in found if figure.key != design_provenance.SUPPORTED_M3]
    return lines or [CardLine(ROW_NONE, tr("No figures recorded"))]


def _removals_of(project: Any, conn: sqlite3.Connection, version: Any, code: str) -> dict[str, list[tuple[Any, str]]]:
    """Las retiradas vivas de cada acopio de la detección ``code`` (clave del acopio → ``(retirada, código de la versión)``; spec 016, T33; D-12:
    «retirado en su superficie»): las de la versión de la detección o, si es **del proyecto** (``version`` ``None``), las de la versión activa;
    sin versión, ninguna. Cuenta también la que retira un acopio de una detección del proyecto (``consumed`` falso). Solo lee."""
    from ...core.versions import read as versions_read
    from ...design import entities

    active = scene_versions.active_version()
    scope = version if version is not None else (versions_read.version(conn, active) if active else None)
    if scope is None:
        return {}
    found: dict[str, list[tuple[Any, str]]] = {}
    for item in entities.live_removals(project, scope.uid, conn=conn, consumed=False):
        if item.detection == code:
            found.setdefault(item.key, []).append((item, scope.code))
    return found


def _stockpile_lines(project: Any, conn: sqlite3.Connection, version: Any, entry: Any) -> list[CardLine]:
    """Los acopios de la detección ``entry`` (spec 016, T33; RF-015-25, RF-016-14; plan 016 §5.5), **leídos de la tabla de su operación vigente**:
    por acopio, su referencia (``STK-001#m07``), su plano, su huella, su volumen, su espesor máximo y su material (la nota del resumen de
    «Calcular», ``stockpile_store.stockpile_row_notice``), sus avisos y notas y, si una retirada viva lo retira, «retirado en su superficie»
    (D-12), en alerta; los :data:`LIST_LIMIT` primeros. Una detección sin calcular o sin acopios, lo dice."""
    from ...design import entity_store, stockpile_store

    shown = language()
    table = None if entry.operation_uid is None else entity_store.operation_table(
        conn, entry.operation_uid, design_provenance.STOCKPILES_ROLE)
    if table is None:
        return []
    rows = stockpile_store.read_stored_rows(conn, design_provenance.STOCKPILES_TABLE, table)
    removed = _removals_of(project, conn, version, entry.record.code)
    lines = [CardLine(ROW_HEADING, tr("Stockpiles ({count})", count=len(rows)))]
    if not rows:
        return [*lines, CardLine(ROW_NONE, tr("The detection has no stockpiles"))]
    for row in rows[:LIST_LIMIT]:
        ref = design_provenance.support_ref(entry.record.code, str(row["key"]))
        origin = f" · {tr('from a candidate')}" if row["origin"] == "candidate" else ""
        lines.append(CardLine(ROW_FIELD, f"{ref}{origin}: {stockpile_store.stockpile_row_notice(row).text(shown)}"))
        for note in stockpile_store.stored_notes(row):
            lines.append(CardLine(ROW_FIELD, note.text(shown), alert=note.severity == "warning"))
        for gone, version_code in removed.get(str(row["key"]), ()):
            lines.append(CardLine(ROW_FIELD, tr("Removed on its surface by «{removal}» ({code}) in {version}", removal=gone.removal,
                                                code=gone.code, version=version_code), alert=True))
    if len(rows) > LIST_LIMIT:
        lines.append(CardLine(ROW_NONE, tr("… and {count} more stockpiles", count=len(rows) - LIST_LIMIT)))
    return lines


def _candidate_lines(conn: sqlite3.Connection, entry: Any, stored: Mapping[Any, Any]) -> list[CardLine]:
    """Los candidatos de la detección ``entry`` (spec 016, T33; RF-016-08, RF-016-10): por candidato, su clave, su huella, su volumen y su plano
    y **su estado** —pendiente (en alerta: pide una decisión), convertido en acopio o descartado, con su motivo, quién y cuándo (D-23)—, leídos de la
    tabla de su operación vigente; los :data:`LIST_LIMIT` primeros. Sin candidatos pedidos ni listados, nada. Los botones de convertir y descartar
    son de la orden de la lista de candidatos (T35): aquí, la lista y el estado."""
    from ...design import entity_store, stockpile_store

    shown = language()
    table = None if entry.operation_uid is None else entity_store.operation_table(
        conn, entry.operation_uid, design_provenance.STOCKPILE_CANDIDATES_ROLE)
    rows = () if table is None else stockpile_store.read_stored_rows(conn, design_provenance.STOCKPILE_CANDIDATES_TABLE, table)
    asked = stored.get("candidates")
    if not rows and not (asked is not None and asked.value is True):
        return []
    lines = [CardLine(ROW_HEADING, tr("Candidates ({count})", count=len(rows)))]
    if not rows:
        return [*lines, CardLine(ROW_NONE, tr("The detection has no candidates"))]
    for row in rows[:LIST_LIMIT]:
        text = stockpile_store.candidate_row_notice(row).text(shown)
        reason, person, date = row["reason"] or NOT_SHOWN, row["decided_by"] or NOT_SHOWN, row["decided_on"] or NOT_SHOWN
        if row["state"] == "converted":
            lines.append(CardLine(ROW_FIELD, f"{text} · " + tr("Converted into a stockpile: {reason} ({person}, {date})",
                                                               reason=reason, person=person, date=date)))
        elif row["state"] == "discarded":
            lines.append(CardLine(ROW_FIELD, f"{text} · " + tr("Discarded: {reason} ({person}, {date})",
                                                               reason=reason, person=person, date=date)))
        else:
            lines.append(CardLine(ROW_FIELD, f"{text} · {tr('Pending: convert it into a stockpile or discard it with a reason')}",
                                  alert=True))
    if len(rows) > LIST_LIMIT:
        lines.append(CardLine(ROW_NONE, tr("… and {count} more candidates", count=len(rows) - LIST_LIMIT)))
    return lines


def _report_notice_lines(report: Sequence[tuple[str, float | None, str | None, str | None]]) -> list[CardLine]:
    """Los avisos y notas del informe de una operación (``des_prp_``: las filas ``warning`` y ``note``, con su código y sus valores en JSON, no el
    texto) como líneas, en su orden y en el idioma de la interfaz; el aviso, en alerta. Sin ninguno, ninguna."""
    from ...design.preview import Notice

    shown = language()
    lines: list[CardLine] = []
    for quantity, _value, _unit, note in report:
        if quantity not in ("warning", "note") or not note:
            continue
        found = json.loads(note)
        lines.append(CardLine(ROW_FIELD, Notice(str(found["code"]), found.get("values", {})).text(shown), alert=quantity == "warning"))
    return lines


def _report_place(note: str | None) -> tuple[float, float] | None:
    """El lugar (``x;y`` absolutos) que anota una fila del informe, o ``None`` si no lo lleva."""
    if not note or ";" not in note:
        return None
    try:
        x, _, y = note.partition(";")
        return float(x), float(y)
    except ValueError:
        return None


def _removal_card_lines(project: Any, conn: sqlite3.Connection, version: Any, entry: Any, stored: Mapping[Any, Any],
                        report: Sequence[tuple[str, float | None, str | None, str | None]]) -> list[CardLine]:
    """Lo que dice la barra N de una **retirada** (spec 016, T33; RF-016-11 a RF-016-15, RF-015-25): **lo retirado** (el acopio), **lo apoyado**
    (los m³ que se le apoyaban y quién lo confirmó, y lo que por eso perdió su apoyo, en alerta) y **la pared** del borde (su altura y su lugar y,
    si se confirmó, quién y su motivo), más los avisos del cálculo. Leído de la operación vigente y de su informe; nada se calcula."""
    from ...design import entities, supported_store

    shown = language()
    first = {quantity: (value, note) for quantity, value, _unit, note in reversed(report)}
    row = stored.get("stockpile")
    lines = [CardLine(ROW_HEADING, tr("Removal")),
             CardLine(ROW_FIELD, tr("Removes the stockpile {stockpile}", stockpile=NOT_SHOWN if row is None or row.value is None
                                    else str(row.value)))]
    settings = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?", (entry.operation_uid,)).fetchone()
    try:
        confirmed = supported_store.confirmed_of(json.loads(str(settings[0]) if settings and settings[0] else "{}"))
    except ValueError:
        confirmed = None
    resting = first.get("resting_m3", (0.0, None))[0] or 0.0
    if resting > 0:
        text = tr("{volume} m³ rested on the stockpile", volume=format_number(resting, 0))
        if confirmed is not None and confirmed.resting_m3 is not None:
            text = f"{text} · {tr('confirmed by {person} on {date}', person=confirmed.decided_by, date=confirmed.decided_on[:10])}"
        lines.append(CardLine(ROW_FIELD, text, alert=True))
    else:
        lines.append(CardLine(ROW_NONE, tr("Nothing rested on the stockpile")))
    if version is not None:
        for lost in entities.retired_supports(project, version.uid, conn=conn):
            if any(item.removal == entry.record.name for item in lost.retired):
                lines.append(CardLine(ROW_FIELD, tr("Lost its support: {name} ({kind})", name=lost.name,
                                                    kind=entities.kind_label(lost.op_type, shown)), alert=True))
    wall = first.get("wall_max_m")
    place = None if wall is None else _report_place(wall[1])
    if wall is None or not wall[0]:
        lines.append(CardLine(ROW_NONE, tr("No wall at the edge")))
    else:
        where = "" if place is None else tr(", around x = {x} m, y = {y} m", x=format_number(place[0], 0), y=format_number(place[1], 0))
        lines.append(CardLine(ROW_FIELD, tr("Wall of up to {height} m at the edge", height=format_number(wall[0], 1)) + where,
                              alert=True))
        if confirmed is not None and confirmed.wall_height_m is not None:
            text = tr("Wall confirmed by {person} on {date}: {height} m at {angle}°", person=confirmed.decided_by,
                      date=confirmed.decided_on[:10], height=format_number(confirmed.wall_height_m, 1),
                      angle=format_number(confirmed.wall_angle_deg or 0.0, 0))
            if confirmed.wall_reason:
                text = f"{text} · {tr('Reason: {value}', value=confirmed.wall_reason)}"
            lines.append(CardLine(ROW_FIELD, text))
    return [*lines, *_report_notice_lines(report)]


def _buttress_card_lines(project: Any, conn: sqlite3.Connection, entry: Any, stored: Mapping[Any, Any],
                         report: Sequence[tuple[str, float | None, str | None, str | None]]) -> list[CardLine]:
    """Lo que dice la barra N de un **contrafuerte** (spec 016, T33; RF-016-17 a RF-016-19, RF-015-25): **la coronación** (la cota y la zona de
    coronación, sus celdas y su área: la que declara «sin corte») y **el pie cortado** (los m² y los m³ que se cortan y el mayor salto creado en
    el borde, con su lugar, en alerta; o que no se corta), más los avisos del cálculo. Leído de su informe; nada se calcula."""
    first = {quantity: (value, note) for quantity, value, _unit, note in reversed(report)}
    crown = stored.get("crown_m")
    cells = first.get("zone_cells", (None, None))[0]
    step = float(project.record.grid_step_m)
    lines = [CardLine(ROW_HEADING, tr("Buttress"))]
    if cells is not None:
        lines.append(CardLine(ROW_FIELD, tr("Crown zone: {cells} cells ({area} m²) at {crown} m", cells=format_number(cells, 0),
                                            area=format_number(cells * step * step, 0),
                                            crown=NOT_SHOWN if crown is None or crown.value is None else format_number(crown.value, 2))))
    cut = first.get("cutoff_m2")
    if cut is None:
        pass  # el pie no se midió
    elif not cut[0]:
        lines.append(CardLine(ROW_NONE, tr("The foot is not cut")))
    else:
        volume = first.get("cutoff_m3", (0.0, None))[0] or 0.0
        jump = first.get("cutoff_step_m")
        place = None if jump is None else _report_place(jump[1])
        text = tr("Cut foot: {area} m² and {volume} m³ are cut off", area=format_number(cut[0], 0), volume=format_number(volume, 0))
        if jump is not None and jump[0] is not None:
            text += tr("; the largest step created at the edge is {step} m", step=format_number(jump[0], 1))
            if place is not None:
                text += tr(", around x = {x} m, y = {y} m", x=format_number(place[0], 0), y=format_number(place[1], 0))
        lines.append(CardLine(ROW_FIELD, text, alert=True))
    return [*lines, *_report_notice_lines(report)]


def _metres(value: float) -> str:
    """Una distancia (m) con **sus decimales** y sin ceros de más (spec 016, T48; hallazgo D-9): 12 → «12», 12,5 → «12,5» y 12,25 →
    «12,25» (hasta dos decimales; con 0 decimales, 12,5 m se leía «13 m»)."""
    decimals = next((places for places in (0, 1) if abs(round(value, places) - value) < 1e-9), 2)
    return format_number(value, decimals)


def _body_card_lines(entry: Any, stored: Mapping[Any, Any], report: Sequence[tuple[str, float | None, str | None, str | None]]
                     ) -> list[CardLine]:
    """Lo que dice la barra N de un **cuerpo apoyado** (spec 016, T33; RF-016-20 a RF-016-22, RF-015-25): **el espesor** (el mayor y su lugar) y
    **lo lejano** (lo que está a más de la distancia máxima de un dato: su área, su volumen y la mayor distancia, en alerta; o que nada lo está) y
    los datos ignorados, más los avisos del cálculo. Leído de su informe; nada se calcula."""
    first = {quantity: (value, note) for quantity, value, _unit, note in reversed(report)}
    lines = [CardLine(ROW_HEADING, tr("Supported body"))]
    thickest = first.get("thickness_max_m")
    if thickest is not None and thickest[0] is not None:
        place = _report_place(thickest[1])
        where = "" if place is None else tr(", around x = {x} m, y = {y} m", x=format_number(place[0], 0), y=format_number(place[1], 0))
        lines.append(CardLine(ROW_FIELD, tr("Thickness: up to {thickness} m", thickness=format_number(thickest[0], 2)) + where))
    distance = first.get("max_distance_m", (None, None))[0]
    far_area = first.get("far_m2", (None, None))[0]
    if distance is not None and far_area is not None:
        if far_area > 0:
            lines.append(CardLine(ROW_FIELD, tr("Far from the data: {area} m² ({volume} m³) are farther than {distance} m from a datum, "
                                                "the farthest at {farthest} m", area=format_number(far_area, 0),
                                                volume=format_number(first.get("far_m3", (0.0, None))[0] or 0.0, 0),
                                                distance=_metres(distance),
                                                farthest=format_number(first.get("farthest_m", (0.0, None))[0] or 0.0, 0)), alert=True))
        else:
            lines.append(CardLine(ROW_NONE, tr("Nothing is farther than {distance} m from a datum", distance=_metres(distance))))
    ignored = first.get("ignored", (0.0, None))[0] or 0.0
    if ignored > 0:
        lines.append(CardLine(ROW_FIELD, tr("Data ignored: {count}", count=format_number(ignored, 0)), alert=True))
    return [*lines, *_report_notice_lines(report)]


def _type_lines(project: Any, conn: sqlite3.Connection, version: Any, entry: Any, stored: Mapping[Any, Any]) -> list[CardLine]:
    """Lo propio de cada tipo de entidad en la barra N (spec 016, T33; plan 016 §5.5): de una **detección**, sus acopios y su lista de candidatos;
    de una **retirada**, lo retirado, lo apoyado y la pared; de un **contrafuerte**, la coronación y el pie cortado; de un **cuerpo**, el espesor y
    lo lejano; de una **pista**, lo de :func:`_road_card_lines` y de una **accesibilidad**, lo de :func:`_access_card_lines` (spec 017, T31b). Nada de la plataforma. Una
    entidad sin calcular no tiene nada de esto."""
    from ...design import entities, entity_store

    if entry.operation_uid is None:
        return []
    kind = str(entry.record.kind)
    if kind == entities.EntityKind.STOCKPILE:
        return [*_stockpile_lines(project, conn, version, entry), *_candidate_lines(conn, entry, stored)]
    if kind == entities.EntityKind.ROAD:  # la pista y la accesibilidad (spec 017, T31b)
        return _road_card_lines(project, conn, version, entry, stored)
    if kind == entities.EntityKind.ACCESS:
        return _access_card_lines(project, conn, version, entry)
    report = entity_store.read_entity_report(conn, entry.operation_uid)
    if kind == entities.EntityKind.REMOVAL:
        return _removal_card_lines(project, conn, version, entry, stored, report)
    if kind == entities.EntityKind.BUTTRESS:
        return _buttress_card_lines(project, conn, entry, stored, report)
    if kind == entities.EntityKind.BODY:
        return _body_card_lines(entry, stored, report)
    return []


_ROAD_PROMPT_NOTICES = frozenset({"des.road_mean_gradient"})
"""Los avisos de una pista que la barra N **no repite** junto a lo que se confirmó: el de la pendiente media por encima de pm pide la confirmación expresa y su motivo antes de crear («no se crea sin…»); ya
confirmada, lo dice la línea de lo confirmado (RF-017-17)."""


def _road_card_lines(project: Any, conn: sqlite3.Connection, version: Any, entry: Any, stored: Mapping[Any, Any]) -> list[CardLine]:
    """Lo que dice la barra N de una **pista** (spec 017, T31b; RF-015-25, RF-017-23, RF-017-17, RF-017-22; H2-2; M4), **leído de lo guardado** de su operación vigente (``design.road_card``; nada
    se calcula): su **modo y su perfil**, la longitud y las cotas de inicio y de fin de la rasante, la pendiente media y la máxima con su abscisa y su lugar, el radio mínimo (o que no tiene curvas),
    la calzada y la sección, el corte y el relleno **de la sección y del borde** y el neto, la pared del borde (en alerta), lo que la persona confirmó al crearla —la pendiente media con su
    motivo y la calzada fuera de su rasante— y los avisos del cálculo; y, **en alerta**, (1) si está obsoleta por **otro diseño que lee** (H2-2), **la causa y la salida** (rehacerla sobre la
    superficie de ese diseño o descartarla: «Recalcular lo obsoleto» no la asienta si ese diseño se apoya ya en ella) y (2) si **la capa de ejes de pistas para QGIS está marcada** para ella
    (T26-b: cambiar el valor de un perfil la deja obsoleta por el grafo y no regenera la capa al instante), que lo está y por qué. Lo que se le apoya y en qué se apoya son los de cualquier entidad
    (:func:`entity_card`)."""
    from ...design import road_card

    shown = language()
    mode, profile = stored.get("mode"), stored.get("profile")
    code = None if profile is None or profile.value is None else str(profile.value)
    lines = [CardLine(ROW_HEADING, tr("Road")),
             CardLine(ROW_FIELD, tr("Mode «{mode}» · profile «{profile}»", mode=NOT_SHOWN if mode is None or mode.value is None else _road_mode_text(mode.value),
                                    profile=NOT_SHOWN if code is None else road_card.profile_name(conn, code) or code))]
    facts = road_card.read_road_facts(conn, str(entry.operation_uid))
    if facts is None:
        return [*lines, CardLine(ROW_NONE, tr("The project has no report of this road"))]
    where = facts.gradient_max_place
    lines += [CardLine(ROW_FIELD, tr("Length {length} m · elevation {start} m at the start and {end} m at the end", length=_number(facts.length_m, 1), start=_number(facts.z_start_m, 2),
                                     end=_number(facts.z_end_m, 2))),
              CardLine(ROW_FIELD, tr("Gradient: mean {mean} % · maximum {max} % at the abscissa {station} m, at ({x}, {y})", mean=_number(facts.gradient_mean_pct, 2),
                                     max=_number(facts.gradient_max_pct, 2), station=_number(facts.gradient_max_station_m, 1), x=_number(None if where is None else where[0], 1),
                                     y=_number(None if where is None else where[1], 1)))]
    if facts.radius_min_m is None:
        lines.append(CardLine(ROW_FIELD, tr("No curves: the axis is a straight line")))
    elif facts.curves == 1:
        lines.append(CardLine(ROW_FIELD, tr("Minimum radius {radius} m in 1 curve", radius=_number(facts.radius_min_m, 1))))
    else:
        lines.append(CardLine(ROW_FIELD, tr("Minimum radius {radius} m in {curves} curves", radius=_number(facts.radius_min_m, 1), curves=_number(facts.curves))))
    lines += [CardLine(ROW_FIELD, tr("Carriageway {width} m · section {section} m", width=_number(facts.width_m, 2), section=_number(facts.section_m, 2))),
              CardLine(ROW_FIELD, tr("Section: cut {cut} m³ · fill {fill} m³; edge: cut {edge_cut} m³ · fill {edge_fill} m³; net {net} m³", cut=_number(facts.section_cut_m3),
                                     fill=_number(facts.section_fill_m3), edge_cut=_number(facts.edge_cut_m3), edge_fill=_number(facts.edge_fill_m3), net=_number(facts.net_m3)))]
    if facts.wall_max_m:
        place = facts.wall_place
        text = tr("Wall of up to {height} m at the edge", height=format_number(facts.wall_max_m, 1))
        if place is not None:
            text += tr(", around x = {x} m, y = {y} m", x=format_number(place[0], 0), y=format_number(place[1], 0))
        lines.append(CardLine(ROW_FIELD, text, alert=True))
    done = facts.confirmed
    if done is not None and done.mean_pct is not None:  # la pendiente media por encima de la del perfil, que la persona confirmó con su motivo (RF-017-17)
        text = tr("The mean gradient, {mean} %, passed the {limit} % of the profile: confirmed by {person} on {date}", mean=_number(done.mean_pct, 2),
                  limit=_number(done.mean_limit_pct, 2), person=done.decided_by, date=done.decided_on[:10])
        lines.append(CardLine(ROW_FIELD, f"{text} · {tr('Reason: {value}', value=done.reason)}" if done.reason else text, alert=True))
    if done is not None and done.carriageway_m2 is not None:  # la calzada que no quedaba en su rasante (RF-017-22)
        lines.append(CardLine(ROW_FIELD, tr("{area} m² of the carriageway did not end up on the level profile: confirmed by {person} on {date} (largest difference {difference} m)",
                                            area=_number(done.carriageway_m2), person=done.decided_by, date=done.decided_on[:10], difference=_number(done.carriageway_difference_m, 3)),
                              alert=True))
    lines += [CardLine(ROW_FIELD, notice.text(shown), alert=notice.severity == "warning") for notice in facts.notices if notice.code not in _ROAD_PROMPT_NOTICES]
    if str(entry.record.state) == "stale":  # H2-2: obsoleta por otro diseño que lee, con su causa y su salida
        others = road_card.stale_other_designs(conn, str(entry.operation_uid))
        if others:
            lines.append(CardLine(ROW_FIELD, tr("It reads another design of the version that changed, {designs}: recalculating the road does not settle it if that design now rests on it. "
                                                "Redo the road on the surface of that design, or discard it", designs=", ".join(f"«{name}»" for name in others)), alert=True))
    if version is not None and road_card.marked_layer(project, conn, version.uid, entry.record.code):  # T26-b: la capa de ejes todavía dice otro estado
        lines.append(CardLine(ROW_FIELD, tr("The layer of the axes of the roads for QGIS is marked: it still says what this road was before (its state, its profile or its class), because a change such as the value of a "
                                            "profile does not bring it up to date at once; the next order on roads or «Recompute the stale results» does"), alert=True))
    return lines


def _access_list_lines(title: str, rows: list[AccessRow]) -> list[CardLine]:
    """Una de las tres listas de la accesibilidad en la barra N (spec 017, T31b; RF-017-25): su título con cuántas filas tiene y, por fila, su texto —**las que no se comunican, antes y en
    alerta**— con su «Ir a» (:data:`ROW_PLACE`) si tiene lugar; las :data:`LIST_LIMIT` primeras y una nota con cuántas faltan."""
    lines = [CardLine(ROW_HEADING, f"{title} ({len(rows)})")]
    if not rows:
        return [*lines, CardLine(ROW_NONE, tr("Nothing to list"))]
    shown, more = _cut_rows(rows, LIST_LIMIT)
    lines += [CardLine(ROW_PLACE, row.text, alert=row.alert, uid=";".join(row.place)) if row.place is not None else CardLine(ROW_FIELD, row.text, alert=row.alert) for row in shown]
    if more:
        lines.append(CardLine(ROW_NONE, tr("… and {more} more (the whole list is in the tables of the accessibility)", more=more)))
    return lines


def _access_card_lines(project: Any, conn: sqlite3.Connection, version: Any, entry: Any) -> list[CardLine]:
    """Lo que dice la barra N de una **accesibilidad** (spec 017, T31b; RF-015-25, RF-017-24, RF-017-25; M4), **leído de lo guardado** de su operación vigente (``design.road_card``; nada se
    calcula): la superficie sobre la que se hizo (y la final de su cantera), las cotas mínima y máxima alcanzables y el área (o que no se alcanzó nada, en alerta) y la cota mínima sobre la final,
    cuántos tramos de berma, plataformas y zonas «requiere acceso» quedan comunicados, los avisos del cálculo y **las tres listas, comunicados o no** (:func:`_access_list_lines`: las que no, antes
    y en alerta, con su «Ir a»). El lugar es el que guardan ``des_acb_`` (tramo de berma) y ``des_acz_`` (la zona que no se comunica) o el centro de la huella de la plataforma; una zona comunicada
    no guarda ninguno y no lleva «Ir a»."""
    from ...design import road_card

    if version is None:
        return []
    shown = language()
    lines = [CardLine(ROW_HEADING, tr("Accessibility"))]
    facts = road_card.read_access_facts(project, conn, version, entry)
    if facts is None:
        return [*lines, CardLine(ROW_NONE, tr("The project has no result of this accessibility"))]
    lines.append(CardLine(ROW_FIELD, tr("Surface: «{surface}»", surface=NOT_SHOWN if facts.surface is None else facts.surface)))
    if facts.z_min_m is None or facts.z_max_m is None:
        lines.append(CardLine(ROW_FIELD, tr("Nothing is reachable from the entry points"), alert=True))
    else:
        lines.append(CardLine(ROW_FIELD, tr("Reachable elevations: from {low} to {high} m · {area} m²", low=_number(facts.z_min_m, 2), high=_number(facts.z_max_m, 2),
                                            area=_number(facts.area_m2))))
    if facts.z_min_final_m is not None:
        lines.append(CardLine(ROW_FIELD, tr("Lowest elevation reachable over the final surface «{final}» of the quarry: {level} m", final=NOT_SHOWN if facts.final is None else facts.final,
                                            level=_number(facts.z_min_final_m, 2))))
    lines.append(CardLine(ROW_FIELD, tr("Communicated · berm stretches: {berms} of {berms_total} · platforms: {platforms} of {platforms_total} · zones that require access: {zones} of {zones_total}",
                                        berms=sum(1 for item in facts.berms if item.connected), berms_total=len(facts.berms),
                                        platforms=sum(1 for item in facts.platforms if item.connected), platforms_total=len(facts.platforms),
                                        zones=sum(1 for item in facts.zones if item.connected), zones_total=len(facts.zones))))
    lines += [CardLine(ROW_FIELD, notice.text(shown), alert=notice.severity == "warning") for notice in facts.notices]
    platform_places = {item.code: item.place for item in facts.platforms if item.place is not None}
    zone_places = {item.code: road_card.AccessSpot(item.x, item.y) for item in facts.zones if not item.connected and item.x is not None and item.y is not None}
    names = {item.code: item.name for item in facts.platforms}
    for title, rows in ((tr("Berm stretches"), _berm_rows(facts.berms)), (tr("Platforms"), _platform_rows(facts.platforms, names, platform_places)),
                        (tr("Zones that require access"), _zone_rows(facts.zones, zone_places))):
        lines += _access_list_lines(title, rows)
    return lines


def _access_object_lines(project: Any, conn: sqlite3.Connection, owner: str, found: Any) -> list[CardLine]:
    """Las líneas que la barra N «Diseño» añade al objeto ``DESIGN`` de una accesibilidad (``des_acc_``; spec 017, T31b; decisión T31-b): **el estado de su entidad** (al día, obsoleta con su causa,
    descartada o «apoyo retirado»: :func:`_entity_state_line`) y su resultado (:func:`_access_card_lines`). La entidad es la del registro de la versión cuya operación escribió el dato
    ``found`` (la accesibilidad no está en la capa de entidades). Sin versión o sin entidad, ninguna (queda el estado del dato)."""
    from ...core.versions import read as versions_read
    from ...design import entities

    version = versions_read.version(conn, owner) if owner else None
    if version is None:
        return []
    entry = next((item for item in entities.registry(project, version.uid, conn=conn) if item.operation_uid == found.record.operation_uid), None)
    if entry is None:
        return []
    return [_entity_state_line(project, conn, version, entry), *_access_card_lines(project, conn, version, entry)]


_DETECTION_GRIDS = {
    design_provenance.STOCKPILE_BASE_ROLE: design_provenance.STOCKPILE_BASE_GRID,
    design_provenance.STOCKPILE_THICKNESS_ROLE: design_provenance.STOCKPILE_THICKNESS_GRID,
    design_provenance.STOCKPILE_GROUND_ROLE: design_provenance.STOCKPILE_GROUND_GRID}
"""Las rejillas que deja una detección y se exportan a GeoTIFF (spec 016, T34): su papel y su familia."""
_OUTPUTS_BY_ROLE = (
    "SELECT d.uid, d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' AND d.status IN ({live}) "
    "AND io.role IN ({roles}) ORDER BY io.fid")


def _candidate_buttons(conn: sqlite3.Connection, entry: Any) -> list[CardLine]:
    """Los botones de los candidatos de la detección ``entry`` (spec 016, T35; RF-016-08, RF-016-10), leídos de la tabla de su operación vigente:
    **«Candidatos…»** (la lista) y, de cada candidato **pendiente** (los :data:`LIST_LIMIT` primeros), una fila de botones (convertir, descartar
    e «Ir a») con su clave. Sin candidatos, ninguno."""
    from ...design import entity_store, stockpile_store

    table = entity_store.operation_table(conn, entry.operation_uid, design_provenance.STOCKPILE_CANDIDATES_ROLE)
    rows = () if table is None else stockpile_store.read_stored_rows(conn, design_provenance.STOCKPILE_CANDIDATES_TABLE, table)
    if not rows:
        return []
    pending = [str(row["key"]) for row in rows if row["state"] not in ("converted", "discarded")]
    return [CardLine(ROW_CANDIDATES, tr("Candidates…")), *(CardLine(ROW_DECIDE, key, uid=key) for key in pending[:LIST_LIMIT])]


def _entity_exports(conn: sqlite3.Connection, entry: Any) -> list[CardLine]:
    """Los botones de exportar a GeoTIFF de la entidad ``entry`` además del de su superficie (spec 016, T34; RF-016-24), leídos del proyecto:
    de una **detección**, uno por rejilla que dejó —la base y el espesor de los acopios de cada material y el terreno sin acopios—, con
    el uid de su dato; de una **retirada**, un **contrafuerte** o un **cuerpo apoyado**, el de su espesor (la orden toma la entidad del
    objeto activo). Una plataforma o una entidad sin calcular, ninguno."""
    from ...core.datasets import LIVE_STATUSES
    from ...design import entities

    kind = entities.EntityKind(entry.record.kind)
    if kind is entities.EntityKind.STOCKPILE:
        if entry.operation_uid is None:
            return []
        live = [str(status) for status in LIVE_STATUSES]
        sql = _OUTPUTS_BY_ROLE.format(live=", ".join("?" for _ in live), roles=", ".join("?" for _ in _DETECTION_GRIDS))
        found = []
        for uid, name, role in conn.execute(sql, (entry.operation_uid, *live, *_DETECTION_GRIDS)).fetchall():
            stem = design_provenance.dataset_name(_DETECTION_GRIDS[str(role)], entry.record.name) + "_"  # el material, tras la detección
            material = str(name).removeprefix(stem)
            if role == design_provenance.STOCKPILE_BASE_ROLE:
                text = tr("Export the base of the stockpiles of «{material}» to GeoTIFF…", material=material)
            elif role == design_provenance.STOCKPILE_THICKNESS_ROLE:
                text = tr("Export the thickness of the stockpiles of «{material}» to GeoTIFF…", material=material)
            else:
                text = tr("Export the ground without stockpiles to GeoTIFF…")
            found.append(CardLine(ROW_EXPORT, text, uid=str(uid)))
        return [*found, *_candidate_buttons(conn, entry)]
    if entry.operation_uid is not None and kind in (entities.EntityKind.REMOVAL, entities.EntityKind.BUTTRESS, entities.EntityKind.BODY):
        return [CardLine(ROW_EXPORT_THICKNESS, tr("Export the thickness to GeoTIFF…"))]
    return []


def entity_card(project: Any, version_uid: str, code: str, *, conn: sqlite3.Connection) -> ItemLines | None:
    """Lo que dice el proyecto de la entidad ``code`` (código o nombre) de la versión ``version_uid`` (véase el módulo),
    leído con ``conn`` (una instantánea de lectura de quien llama) y sin escribir nada: su título («Plataforma Carga
    (PLT-002)»), su **estado** (al día; obsoleta o con el apoyo retirado, con su causa; descartada; sin calcular), **lo propio de su
    tipo** (:func:`_type_lines`: los acopios y los candidatos de una detección, lo retirado, lo apoyado y la pared de una retirada, la
    coronación y el pie cortado de un contrafuerte, el espesor y lo lejano de un cuerpo; spec 016, T33), sus **parámetros** con su insignia de
    tipo y su origen, sus **restricciones declaradas**, su **cadena** (un tipo sin cadena no la tiene), **en qué se apoya** y **lo que se le
    apoya** (una sola lista cada uno, con sus m³; con el acopio, si es de una detección) y, aparte, sus **cifras**. ``None`` si la versión o la
    entidad no existen. Funciona también con una entidad sin calcular (que no tiene objeto en la vista). Con ``version_uid`` vacío, la de una
    detección **del proyecto** (D-15): no tiene lista de dependencias, que son de cada versión."""
    from ...core.versions import read as versions_read
    from ...design import entities

    version = versions_read.version(conn, version_uid) if version_uid else None
    if version_uid and version is None:
        return None
    listed = entities.registry(project, version.uid, conn=conn) if version is not None else entities.project_registry(project, conn=conn)
    entry = listed.get(code)
    if entry is None:
        return None
    record = entry.record
    params, stored = _entity_parameter_lines(project, conn, version, entry, listed)
    lines: list[CardLine] = [_entity_state_line(project, conn, version, entry),
                             *_type_lines(project, conn, version, entry, stored),
                             CardLine(ROW_HEADING, tr("Parameters")),
                             *(params or [CardLine(ROW_NONE, tr("No parameters recorded"))]),
                             CardLine(ROW_HEADING, tr("Declared constraints")),
                             *_entity_declared_lines(project, version, entry, stored)]
    # Un tipo sin cadena (la detección) no la tiene, ni el cuerpo «bajo un techo» (sin partida: no cambia la superficie).
    if entities.entity_type(record.kind).chained and not (record.kind == entities.EntityKind.BODY and record.start is None):
        lines += [CardLine(ROW_HEADING, tr("Chain")), *_entity_chain_lines(listed, entry)]
    if version is not None:
        rests_on = entities.dependencies_of(project, version.uid, record.code, conn=conn)
        on_it = entities.dependents(project, version.uid, record.code, conn=conn)
        lines += [CardLine(ROW_HEADING, tr("Rests on")),
                  *([_entity_dependent_line(item) for item in rests_on] or [CardLine(ROW_NONE, tr("It rests on nothing"))]),
                  CardLine(ROW_HEADING, tr("What rests on it")),
                  *([_entity_dependent_line(item) for item in on_it] or [CardLine(ROW_NONE, tr("Nothing rests on it"))])]
    else:  # la detección de una superficie del proyecto: lo que se apoya en sus acopios se lee en cada versión
        lines += [CardLine(ROW_HEADING, tr("What rests on it")),
                  CardLine(ROW_NONE, tr("It belongs to the project: what rests on its stockpiles is read in each version"))]
    figures = [CardLine(ROW_HEADING, tr("Figures")), *_entity_figures(conn, entry)]
    return ItemLines(f"{constraint_views.entity_text(record.code, record.name)} ({record.code})", tuple(lines),
                     tuple(figures), tuple(_entity_exports(conn, entry)))


def entity_of(project: Any, conn: sqlite3.Connection, uid: str) -> tuple[str, str]:
    """El código y la versión (uid; ``""``: el proyecto) de la entidad del dato ``uid`` de un objeto ``DESIGN_ENTITY``, leídos con ``conn``:
    el de la tabla de su huella (``des_epr_``) o, de una **detección de acopios** (``des_stk_``, spec 016, T33), el de su tabla de acopios o,
    si no tiene acopios, el de la entidad cuya operación escribió el dato; ``("", "")`` si el proyecto ya no tiene el dato, o si es de una
    entidad de una versión y ya no se sabe de cuál. Solo lee. ``sqlite3.Error`` y ``ValueError`` siguen."""
    from ...core.versions import read as versions_read
    from ...core.views import card
    from ...design import entities, entity_store

    found = card.item_card(project, uid, conn=conn)
    if found is None:
        return "", ""
    owner = versions_read.dataset_versions(conn, [uid]).get(uid, "")
    if not found.record.name.startswith(entity_views.STOCKPILES_PREFIX):
        if not owner:
            return "", ""
        return entity_store.read_entity_footprint(conn, found.record.locator).code, owner
    code, _footprints = entity_store.read_stockpile_footprints(conn, found.record.locator)
    if not code:  # una detección sin acopios: la entidad cuya operación escribió el dato
        listed = entities.registry(project, owner, conn=conn) if owner else entities.project_registry(project, conn=conn)
        code = next((entry.record.code for entry in listed if entry.operation_uid == found.record.operation_uid), "")
    return code, owner


def entity_lines(project: Any, uid: str) -> ItemLines | None:
    """Lo que dice el proyecto de la entidad del dato ``uid`` (la tabla ``des_epr_`` de una entidad o la ``des_stk_`` de una detección que muestra
    un objeto ``DESIGN_ENTITY``): :func:`entity_card` de su entidad en su versión (o en el proyecto), en **una** instantánea; ``None`` si el
    proyecto ya no tiene el dato o no es de una versión (el de una entidad). Los errores del proyecto (``GeoblenderError``, ``sqlite3.Error``)
    siguen."""
    with project.read() as conn:
        conn.execute("BEGIN")
        try:
            code, owner = entity_of(project, conn, uid)
            return entity_card(project, owner, code, conn=conn) if code else None
        finally:
            conn.execute("ROLLBACK")


def entity_object_lines(project: Any, obj: Any) -> list[CardLine]:
    """Las líneas más que enseñan «Elemento activo» y «Cifras de la selección» de un objeto ``DESIGN_ENTITY``
    (``view_panels.register_object_lines``): las de :func:`entity_lines`, sin las cifras (las de su ficha). Ninguna si el
    proyecto ya no tiene su dato."""
    uid = str(getattr(getattr(obj, "geoblender", None), "dataset_uid", "") or "")
    try:
        found = entity_lines(project, uid) if uid else None
    except ValueError:  # un dato que ya no es el de una entidad
        LOGGER.info("No se pudieron leer las líneas de la entidad de «%s»", getattr(obj, "name", ""), exc_info=True)
        return []
    return [] if found is None else list(found.lines)


def object_lines(project: Any, obj: Any) -> list[CardLine]:
    """Las líneas más que enseñan «Elemento activo» y «Cifras de la selección» de un objeto
    ``DESIGN`` (``view_panels.register_object_lines``): las de :func:`item_lines`, sin las cifras
    (las de su ficha). Ninguna si el proyecto ya no tiene su dato."""
    uid = str(getattr(getattr(obj, "geoblender", None), "dataset_uid", "") or "")
    try:
        found = item_lines(project, uid) if uid else None
    except ValueError:  # el proyecto se abrió solo con su cabecera: sin rejilla, sin sectores
        LOGGER.info("No se pudieron leer las líneas del diseño de «%s»", getattr(obj, "name", ""),
                    exc_info=True)
        return []
    return [] if found is None else list(found.lines)


def _redraw() -> None:
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _clear_item(shown: Any) -> bool:
    """Olvida el dato de la barra N; dice si había uno."""
    had = bool(shown.item_uid) or len(shown.item) > 0
    if had:
        shown.item_uid = shown.item_project = shown.item_title = ""
        shown.item_found = False
        shown.item.clear()
    return had


def _put_item(shown: Any, uid: str, project_uid: str, found: ItemLines | None) -> None:
    """Deja en la vista lo leído del dato ``uid`` (``None``: el proyecto ya no lo tiene)."""
    shown.item_uid, shown.item_project = uid, project_uid
    shown.item_found = found is not None
    shown.item_title = "" if found is None else found.title
    shown.item.clear()
    for line in () if found is None else (*found.lines, *found.figures, *found.exports):
        row = shown.item.add()
        row.kind, row.name, row.alert, row.uid = line.kind, line.text, line.alert, line.uid


def read_selected(context: Any = None) -> bool:
    """Lee del proyecto de la sesión el dato del objeto de diseño activo (:func:`wanted`: una rejilla, con
    :func:`item_lines`) o de entidad (:func:`entity_wanted`, T28: su ficha, con :func:`entity_lines`) y lo deja en
    ``WindowManager.geoblender_design`` (``item_title`` e ``item``); sin ninguno, o si el proyecto ya
    no lo tiene, lo olvida. No escribe en el proyecto; mientras esta sesión escribe en él o está en
    WAL, no lo lee (lo hará la siguiente lectura de los indicadores). Devuelve si hay un dato. Si no se
    puede leer, lo olvida y lo anota en el registro técnico."""
    shown = view()
    if shown is None:
        return False
    uid, reader = wanted(context), item_lines  # un objeto DESIGN…
    if not uid:  # …o uno DESIGN_ENTITY (T28; RF-015-25): la barra N «Entidad»
        uid, reader = entity_wanted(context), entity_lines
    project = project_session.current()
    if not uid or project is None:
        changed, found = _clear_item(shown), False
    elif not view_panels.readable(project):
        return bool(shown.item_uid)
    else:
        try:
            read = reader(project, uid)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.info("No se pudo leer del proyecto el dato del diseño seleccionado",
                        exc_info=True)
            changed, found = _clear_item(shown), False
        else:
            _put_item(shown, uid, project.uid, read)
            changed, found = True, read is not None
    if changed:
        _redraw()
    return found


def read_selected_safely() -> None:
    """:func:`read_selected` para lo que llama Blender: un fallo va al registro técnico."""
    try:
        read_selected()
    except Exception:  # noqa: BLE001 - lo que llama Blender no lo tumba
        LOGGER.exception("Falló la lectura del dato del diseño seleccionado")


def on_card_read() -> None:
    """Lo que se apunta en ``view_panels.add_card_listener``: se volvió a leer la ficha del objeto
    activo (cambió el objeto, el proyecto o el fichero), así que también este dato."""
    read_selected_safely()


def on_project_changed(_project: Any) -> None:
    """Lo que se apunta en ``project_session``: con otro proyecto (o ninguno), olvida el dato y la
    caché de la comprobación contra el límite vigente (:func:`forget_limit_checks`); con uno nuevo,
    la barra N no lee nada hasta que se selecciona algo."""
    forget_limit_checks()
    shown = view()
    if shown is not None and _clear_item(shown):
        _redraw()


def _draw_item(layout: Any, shown: Any, uid: str, width: float) -> bool:
    """El dato ya leído del objeto activo (``uid``; vacío: ninguno) como lo enseñan la barra N «Diseño» y la «Entidad»: su
    título y sus líneas, con un apartado por título; «leyendo…» mientras no se leyó el suyo y, si el proyecto ya no lo
    tiene, lo dice. Devuelve si dibujó la ficha de un dato."""
    if uid and shown.item_uid != uid:
        _draw_text(layout, tr("Reading the project data of the active object…"), width)
    elif uid and not shown.item_found:
        _draw_text(layout, tr("The project no longer has the data of this object"), width,
                   alert=True)
    elif uid:
        _draw_text(layout, shown.item_title, width)
        for row in shown.item:
            if row.kind in _BUTTON_ROWS:
                continue  # un botón de exportar (T34) o de los candidatos (T35): lo dibuja la barra de la entidad
            if row.kind == ROW_PLACE:  # una fila de las listas de la accesibilidad con su «Ir a» (T31b)
                _draw_place(layout, row, width)
                continue
            if row.kind == ROW_HEADING:
                layout.separator()
            sub = layout.column(align=True)
            sub.active = row.kind != ROW_NONE
            _draw_text(sub, row.name, width, alert=bool(row.alert))
        return True
    return False


def _draw_place(layout: Any, row: Any, width: float) -> None:
    """Una fila de las listas de la accesibilidad con su **«Ir a»** (spec 017, T31b; RF-017-25): su texto, partido al ancho que deja el botón, y ``geoblender.core_go_to_place`` con el lugar de su
    ``uid`` (``x;y;radio``); en alerta si no se comunica. Un lugar que no se lee no dibuja el botón."""
    parts = str(row.uid).split(";")
    line = layout.row()
    _draw_text(line.column(), row.name, width - GO_TO_BUTTON_PX, alert=bool(row.alert))
    if len(parts) == 3:
        button = line.operator(constraint_panels.GO_TO_PLACE, text=tr("Go to"), translate=False)
        button.x, button.y, button.radius = parts


def _is_detection(obj: Any) -> bool:
    """Si el objeto ``DESIGN_ENTITY`` ``obj`` es el de una detección de acopios (spec 016, T33): lo dice su malla, que lleva el atributo de
    arista de sus acopios (:data:`~..scene.entity_views.STOCKPILE_ATTRIBUTE`); no lee el proyecto."""
    data = getattr(obj, "data", None)
    attributes = getattr(data, "attributes", None)
    return attributes is not None and attributes.get(entity_views.STOCKPILE_ATTRIBUTE) is not None


def draw_entity(layout: Any, context: Any) -> None:
    """La barra N «Entidad» (véase el módulo), de lo ya leído: la entidad del objeto ``DESIGN_ENTITY`` activo."""
    shown = view()
    if shown is not None and _draw_item(layout, shown, entity_wanted(context), labels.sidebar_width(context)):
        layout.separator()
        buttons = [(row.kind, str(row.name), str(row.uid)) for row in shown.item if row.kind in _BUTTON_ROWS]
        if _is_detection(active_object(context)):  # la detección no deja una superficie: un botón por rejilla que dejó (T34, RF-016-24)
            for kind, text, uid in buttons:
                if kind == ROW_EXPORT:
                    button = layout.row().operator(EXPORT_GRID, text=text, icon="EXPORT", translate=False)
                    button.source, button.part = uid, ""
                elif kind == ROW_CANDIDATES:  # la lista de candidatos (T35): la orden toma la detección del objeto activo
                    layout.row().operator(STOCKPILE_CANDIDATES, text=text, icon="VIEWZOOM", translate=False)
                elif kind == ROW_DECIDE:  # los botones de un candidato pendiente (T35): convertir y descartar abren la lista con su motivo
                    row = layout.row(align=True)
                    row.label(text=uid, translate=False)
                    for action, label in (("CONVERT", tr("Convert")), ("DISCARD", tr("Discard"))):
                        button = row.operator(STOCKPILE_CANDIDATES, text=label, translate=False)
                        button.candidate, button.action = uid, action
                    row.operator_context = "EXEC_DEFAULT"  # «Ir a» no abre nada: encuadra la vista
                    button = row.operator(STOCKPILE_CANDIDATES, text=tr("Go to"), translate=False)
                    button.candidate, button.action = uid, "GO_TO"
                    row.operator_context = "INVOKE_DEFAULT"  # el contexto es del layout raíz: no se lo deja a los botones que siguen
            return
        export = layout.row()  # exportar no escribe en el proyecto: vale también en solo lectura (T30, RF-015-27)
        export.operator(EXPORT_GRID, text=_label(EXPORT_GRID), icon="EXPORT", translate=False)
        for kind, text, _uid in buttons:
            if kind == ROW_EXPORT_THICKNESS:  # el espesor de una retirada, un contrafuerte o un cuerpo apoyado (T34)
                button = layout.row().operator(EXPORT_GRID, text=text, icon="EXPORT", translate=False)
                button.part = EXPORT_PART_THICKNESS


def draw_selected(layout: Any, context: Any) -> None:
    """La barra N «Diseño» (véase el módulo), de lo ya leído: el dato del objeto activo y, mientras
    lo hay, el resumen de la vista previa de las semillas."""
    shown = view()
    if shown is None:
        return
    width = labels.sidebar_width(context)
    uid = wanted(context)
    if _draw_item(layout, shown, uid, width):
        layout.separator()
        export = layout.row()  # exportar no escribe en el proyecto: vale también en solo lectura
        export.operator(EXPORT_GRID, text=_label(EXPORT_GRID), icon="EXPORT", translate=False)
    if len(shown.preview):
        if uid:
            layout.separator()
        _draw_text(layout, tr("Preview of the seeds"), width)
        for row in shown.preview:
            _draw_text(layout, row.name, width, alert=bool(row.alert))


class GEOBLENDER_PT_des_design(bpy.types.Panel):
    """The design shown by the active object: state, parameters, seeds, domain, constraints and
    figures, or the summary of the preview of the seeds"""

    bl_idname = SELECTED_PANEL
    bl_label = SELECTED_TAB
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = SELECTED_TAB

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(wanted(context)) or has_preview()

    def draw(self, context: Any) -> None:
        draw_selected(self.layout, context)


class GEOBLENDER_PT_des_entity(bpy.types.Panel):
    """The design entity shown by the active object: state, parameters, declared constraints, chain, what it rests
    on, what rests on it and figures"""

    bl_idname = ENTITY_PANEL
    bl_label = ENTITY_TAB
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = ENTITY_TAB

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(entity_wanted(context))

    def draw(self, context: Any) -> None:
        draw_entity(self.layout, context)


def localize() -> None:
    """La pestaña y el título de las barras N «Diseño» y «Entidad» en el idioma de la interfaz (antes de
    registrar, y otra vez al cambiar el idioma)."""
    GEOBLENDER_PT_des_design.bl_category = tr("Design")
    GEOBLENDER_PT_des_design.bl_label = tr("Design")
    GEOBLENDER_PT_des_entity.bl_category = tr("Entity")
    GEOBLENDER_PT_des_entity.bl_label = tr("Entity")


# En orden de registro (las listas, antes de la ventana que las dibuja).
classes: tuple[type, ...] = (GEOBLENDER_UL_des_profiles, GEOBLENDER_PT_des_profiles,
                             GEOBLENDER_UL_des_road_profiles, GEOBLENDER_PT_des_road_profiles,
                             GEOBLENDER_UL_des_sectors, GEOBLENDER_PT_des_sectors,
                             GEOBLENDER_PT_des_design, GEOBLENDER_PT_des_entity)


def install() -> None:
    """Pone la escucha de los indicadores (:func:`on_project_read`) y las de la barra N «Diseño»: la
    ficha del objeto activo, el proyecto de la sesión y las líneas más de «Elemento activo» y
    «Cifras de la selección» de los objetos ``DESIGN``; y la comprobación de las superficies de la
    014 en el resumen de cada compilación de las máscaras, por pasos (:func:`limit_steps`);
    idempotente."""
    provenance.add_change_listener(on_project_read)
    view_panels.add_card_listener(on_card_read)
    view_panels.register_object_lines(des_views.KIND, object_lines)
    view_panels.register_object_lines(entity_views.KIND, entity_object_lines)
    project_session.add_listener(on_project_changed)
    constraint_panels.add_compile_check(limit_steps)


def uninstall() -> None:
    """Quita lo que puso :func:`install`, olvida el dato de la barra N, las listas del diálogo de
    las envolventes y la caché de la comprobación contra el límite vigente, y quita su
    temporizador; idempotente."""
    constraint_panels.remove_compile_check(limit_steps)
    forget_limit_checks()
    if bpy.app.timers.is_registered(limit_tick):
        bpy.app.timers.unregister(limit_tick)
    project_session.remove_listener(on_project_changed)
    view_panels.unregister_object_lines(entity_views.KIND, entity_object_lines)
    view_panels.unregister_object_lines(des_views.KIND, object_lines)
    view_panels.remove_card_listener(on_card_read)
    provenance.remove_change_listener(on_project_read)
    shown = view()
    if shown is not None:
        _clear_item(shown)
    forget_choices()
