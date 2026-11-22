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
  operación de la versión, repetibles (``des.platform``, ``des.declare_constraints`` y
  ``des.entity_layer``: :data:`ENTITY_RECOMPUTE`) y reproducibles salvo la capa de entidades, que es una vista
  regenerable (:data:`ENTITY_REPRODUCE`) y sus cifras
  (``design.provenance.ENTITY_FIGURES``); sin las órdenes (T15 y siguientes);
- lo de la **016** (T03; plan 016 §5.2.2 y §5.2.3): las familias de parámetros de sus cuatro tipos
  (``design.params.SUPPORTED_FAMILIES``: ``des.stockpile.{e}.*``, ``des.removal.{e}.*``, ``des.buttress.{e}.*`` y
  ``des.body.{e}.*``), sus cuatro tipos de operación de la versión y, desde la T04, el **de proyecto** de la detección
  de acopios (``des.stockpile_detect_project``: D-15, el mismo algoritmo con otro ámbito), repetibles
  (:data:`SUPPORTED_RECOMPUTE`) y reproducibles (:data:`SUPPORTED_REPRODUCE`) y sus cifras
  (``design.provenance.SUPPORTED_FIGURES``); **sin comportamiento ni órdenes todavía** (las tareas siguientes);
- lo de la **017** (T03; plan 017 §5.2.2 y §5.2.3): las familias de parámetros de la pista, la accesibilidad y el perfil de pista
  (``design.params.ROAD_FAMILIES``, ``ACCESS_FAMILIES`` y ``ROAD_PROFILE_FAMILIES``: ``des.road.{e}.*``, ``des.access.{e}.*`` y
  ``des.roadprofile.{p}.*``), sus tres tipos de operación de la versión, repetibles (:data:`ROAD_RECOMPUTE`) y reproducibles
  (:data:`ROAD_REPRODUCE`), la edición de los perfiles de pista, **de proyecto** y sin repetición
  (``design.provenance.ROAD_PROFILE_OPERATIONS``: la declara el módulo ligero porque ``design.road_profiles`` es perezoso) y sus cifras
  (``design.provenance.ROAD_FIGURES`` y ``ACCESS_FIGURES``); **sin comportamiento ni órdenes todavía** (las tareas siguientes);
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

**Perfil de pista…** (spec 017, T29; RF-017-07, RF-017-08, RF-017-29, RF-015-28): :class:`GEOBLENDER_OT_des_edit_road_profile` y la interna
:class:`GEOBLENDER_OT_des_save_road_profile` son las de los perfiles de banco **copiadas para la pista** (plan 017 P-2): la ventana de
``bl.ui.des_panels`` (lo leído del proyecto, con la fuente de cada valor y los derivados, que no son parámetros) y el diálogo que crea,
completa y renombra perfiles con ``design.road_profiles.edit_road_profiles`` (``des.edit_road_profiles``: una operación de proyecto, en una
transacción, con el ámbito de la 009 «¿Para el proyecto o solo para V01?»); los quince valores llevan su tipo, su fuente, su decisor y su
motivo, y ninguno tiene valor por defecto salvo el factor de malla y la métrica (D-2). ``design.road_profiles`` es perezoso: se importa al
usarlo. Ninguna cuenta ni regla de rango es de aquí: las del dominio.

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
el recinto, con un código por celda y su leyenda en los metadatos (``design.export.LEGENDS``). Desde
la 015 (T30; RF-015-27) exporta también **la superficie de una entidad** (``des_psf_``): con el objeto de una
entidad activo (o su tabla ``des_epr_`` como ``source``) toma su superficie, y el botón está también en la barra
N «Entidad». Desde la 016 (T34; RF-016-24) exporta también **la base, el espesor y el terreno sin acopios de una detección**
(``design.export.SUPPORTED_GRIDS``: por el uid o el nombre de su dato, que la barra N «Entidad» de la detección pone en un botón por
rejilla; el terreno, **compuesto entero** con la superficie de la que parte la detección) y, con ``part`` ``thickness``, **el espesor** de
una retirada, un contrafuerte o un cuerpo apoyado (el de los dos primeros, la resta de sus dos superficies). **La capa de entidades**
(T30; RF-015-27): la regeneran, como operación aparte y tras la entidad,
las órdenes que encadenan ``design.entity_store.after_entity_change`` (crear, descartar…) y «Recalcular lo
obsoleto» (:func:`recompute_entity_layer`); no tiene orden propia. **La capa de ejes de pistas** (spec 017, T26; RF-017-27, D-19):
``des.road_layer`` (``design.road_layer``), de la versión, repetible (:func:`recompute_road_layer`) y no reproducible, la regeneran las mismas
órdenes que la de entidades (``after_entity_change`` y «Recalcular lo obsoleto»), solo si la versión tiene pistas.

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
entidades ▸ Entidades; la entrada «015» la entrega la T31) calcula ``des.platform`` de la versión activa con
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

**Lo que sigue a cambiar un parámetro de una entidad y a «Recalcular lo obsoleto»** (spec 015, T43; RF-015-10,
RF-015-27, RF-015-29; hallazgos E-2, B-2 y E-4; spec 016, T47, hallazgos D-1 y D-2: de **cada tipo** de entidad, no solo de la
plataforma): «Cambiar parámetro…» de un parámetro ``des.<tipo>.<e>.<p>`` de la versión activa (``PARAMETER_PREFIXES``: la plataforma,
la detección de acopios, la retirada, el contrafuerte y el cuerpo apoyado) pasa antes por las reglas de crear la entidad
(:func:`_check_entity_parameter`) y lanza, con el cambio ya escrito (:func:`_after_entity_parameter`, registrado en
``core_provenance.register_parameter_after``), :class:`GEOBLENDER_OT_des_entity_refresh` (interna, sin menú): lo que
sigue a crear o descartar una entidad (``design.entity_store.after_entity_change``) por pasos con el avance y Esc;
así una sola pasada de «Recalcular lo obsoleto» deja al día la entidad, las máscaras y la capa. Al terminar
«Recalcular lo obsoleto» (:func:`_layers_after_recompute`, ``core_provenance.register_recompute_after``) se pone al día la
capa de entidades de las versiones en que no dice lo que el registro (``design.entity_store.layers_sync_steps``: la
008 no rehace lo que depende de una salida que no cambió), con una entidad viva de cualquier tipo, también sin plataformas; y, de la 017
(T26), la capa de ejes de pistas de la versión que tenga una pista (``layers_sync_steps`` la incluye: hallazgo D-1 de la 016 con la pista).

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
con su motivo (:class:`DesignCommandAware`); la T31 las pone en el menú «Entidad ▾» (entrada «015»), donde toman la entidad
seleccionada en la vista si no se les da otra. Todas las
cuentas y los rechazos son de ``design``.

**Traer las entidades de otra versión** (spec 015, T26; HU-015-2; RF-015-18, RF-009-01; D-18; plan 015 §5.3.3):
:class:`GEOBLENDER_OT_des_entity_bring` (``geoblender.des_entity_bring``) abre un diálogo con la versión de origen
—cualquiera de las del proyecto menos la activa— y sus entidades vivas (las descartadas no se traen), una casilla cada
una, todas marcadas de entrada; al aceptar copia sus definiciones a la versión activa
(``design.entity_store.bring_entities``: sus parámetros con su historial «Traído de V09.r2», **sin resultados ni
cifras**, «sin calcular», en una sola transacción) y dice lo que hizo: cuántas, los códigos y los nombres que cambiaron
y lo que quedó sin valor (una partida que era un resultado de la otra versión). No encadena nada: lo traído no está
calculado y no declara restricciones; sus dependencias se detectan de nuevo al calcularlo. Con el proyecto en escritura
y la versión activa editable y, si no, desactivada con su motivo (:class:`DesignCommandAware`); la T31 la pone
en el menú «Entidad ▾» (entrada «015»).

**La vista previa de una entidad** (spec 015, T29; HU-015-3; RF-015-26; RNF-015-06; plan 015 §5.3.3 y §5.5; comprobación
manual M4): el botón «Vista previa» del diálogo de «Plataforma…» (:func:`_draw_platform_preview_button`: la misma orden con
la propiedad oculta ``preview`` y todo lo pedido en el diálogo, como el de la cantera) y
:class:`GEOBLENDER_OT_des_entity_preview` (``geoblender.des_entity_preview``: activa o quita la de la entidad
seleccionada, o de la que dice ``entity``) activan ``bl.draw.entity``: dibuja antes de calcular y **sin escribir nada
en el proyecto ni crear objetos** la huella, el eje con la flecha de su sentido y las cotas de la rasante en sus
extremos, lo que se le apoya y las restricciones que declarará, con su leyenda. Al cambiar los campos del diálogo se
redibuja (:func:`_refresh_preview`: el ``update`` de cada uno); se quita al **cancelar** la orden (su diálogo, su
ventana de confirmar o Esc a mitad), al crear la plataforma, con su mismo control y al conmutar a la interfaz de
Blender. Lo que rechazaría «Calcular» sale como aviso de la vista previa, no como un error.

**La vista previa de las marcas y de la zona de coronación** (spec 016, T32; HU-016-1, HU-016-3; RF-016-23; comprobación manual M4):
el mismo ``bl.draw.entity`` dibuja, antes de calcular y sin escribir nada, las **marcas de una detección de acopios con su margen**
(``bl.draw.entity.EntityPlan(stockpile=<StockpileRequest>)``: la orden de detectar de la T35 la activa con su botón «Vista previa», como
«Plataforma…», con :func:`_draw_entity_preview_button`, y la quita con :class:`_ClearsEntityPreview`) y **la zona de coronación de un
contrafuerte** (``EntityPlan(buttress=<ButtressRequest>)``: el botón «Vista previa» de :class:`GEOBLENDER_OT_des_add_buttress`, que se
redibuja al cambiar sus campos, :func:`_refresh_buttress_preview`). Se quitan al cancelar, al Esc a mitad, al crear y al conmutar.

**La vista previa de una pista** (spec 017, T28; HU-017-1; RF-017-26, RF-015-26; RNF-017-08; comprobación manual M5): el mismo ``bl.draw.entity`` dibuja, sin escribir nada, **antes de calcular** el
origen, el destino y el pasillo de la ruta de una pista que se prepara (``EntityPlan(road=<design.preview.RoadAsk>)``: **el diálogo de «Pista…» (T29) lo activa** con su botón «Vista previa», con
:func:`_draw_entity_preview_button`, y la quita con :class:`_ClearsEntityPreview`; tras «Calcular» le da el resultado, ``RoadAsk(request, prepared, outcome)``, y dibuja el eje con su flecha, las pendientes
por tramos según pd y pm y la anchura de la sección) y, con :class:`GEOBLENDER_OT_des_entity_preview`, **una pista de la versión** por su código o seleccionada (``RoadAsk(code=…)``: su eje
guardado y lo que se le apoya). Se quita al cancelar, al Esc a mitad, al crearla y al conmutar a la interfaz de Blender.

**Pista…** (spec 017, T29b; HU-017-1, HU-017-2, HU-017-4; RF-017-02, RF-017-17, RF-017-22, RF-017-29, RF-015-28; plan 017 §5.3.3 y §5.5; comprobación manual M1):
:class:`GEOBLENDER_OT_des_create_road` (``geoblender.des_create_road``, «Pista…», de la entrada «017»: el primer puesto de Diseño ▸ Pistas y entidades, T33b) calcula ``des.road`` de la versión activa con
``design.steps.road_run``: el eje, la rasante y la sección grabada en la superficie de partida. **Es el patrón de la orden de pista**: :class:`_ChainsEntityLayer` +
:class:`_CalculateAndCreate` + :class:`DesignCommandAware` + :class:`~.core._StepsModal`, con :class:`_ClearsEntityPreview` delante. Su diálogo pide el nombre y el **modo**
(«trazar», «sobre un eje» o «eje 3D»); la capa (de puntos, de líneas o de líneas con Z, según el modo: ``des_panels.road_layers``) y, en «trazar», **el origen** (un punto de la
capa o el eje de otra pista a una abscisa, ``RDW-001@100``) y **el destino** (un punto, una plataforma, ``entity:PLT-001``, o una cota con su zona y su tolerancia: la rampa) o,
en los otros dos, la línea; **el perfil de pista** (``des_panels.road_profile_items``); **la partida** (la superficie de explotación de la cantera de la 014 y, si no hay o ya
parte de ella otra entidad, la última de la cadena: ``des_panels.road_default_start``) y el apoyo; las **cotas de inicio y de fin** (vacías, son las de la superficie de partida en
esos puntos con su origen; lo que se escribe queda con ``source_kind="person"``: lo hace ``design.road_store.resolve_level``) y, en «trazar», **los nueve parámetros de la
ruta, cada uno con su tipo** (HIPÓTESIS sin valor por defecto, y el presupuesto de estados, ADOPTADO con el suyo: :func:`_route_text`). Lo pedido es una
``design.road_model.RoadRequest`` (su :meth:`~GEOBLENDER_OT_des_create_road._request`). **Vista previa** (T28): el botón del diálogo y el ``update`` de cada campo
(:func:`_refresh_road_preview`) activan y redibujan ``bl.draw.entity`` con ``EntityPlan(road=RoadAsk(request=…))`` —el origen, el destino y el pasillo— y, **tras calcular**, con lo
calculado (``RoadAsk(request, prepared, outcome)``); se quita al cancelar, al Esc, al crear y al conmutar. Calcular, Crear, Cancelar y Esc son los de
:class:`_CalculateAndCreate`: nada se registra hasta Crear (RF-015-03) y cerrarlo a mitad no deja nada (RF-015-29). **No se crea sin la confirmación expresa** de la
**pendiente media por encima de la del perfil** (RF-017-17: con **un motivo**, que queda en los ajustes de la operación con quién y cuándo y no bloquea, D-6) ni de **la calzada
que no queda en su rasante** (RF-017-22): el botón de la ventana dice «Confirmar y crear» y pulsarlo es la confirmación (``confirm_mean`` y ``confirm_carriageway``; desde un
guion, quien la lanza, con ``mean_reason``). El resumen del cálculo (``des_panels._road_lines``) lleva la longitud, las pendientes, el radio mínimo, el corte y el relleno y **todos
los avisos de la pista con su lugar** (los de la partida, la holgura del pasillo, el eje, la huella recortada, los otros diseños, el salto creado, la calzada con la restricción
que impide moverla, lo que no se mueve y lo que quedará obsoleto). **Tras crear, encadena** ``entity_store.after_entity_change`` (:class:`_ChainsEntityLayer`): la pista no
declara restricciones (D-15), pero la capa de entidades y la de ejes se ponen al día, por pasos con el avance y Esc. Disponible con el proyecto en escritura y la versión activa
editable y, si no, desactivada con su motivo (RF-017-29, RF-015-28: :class:`DesignCommandAware`). «Proponer el trazado…» (``des_propose_road``) es de la T33 (abajo).

**Accesibilidad de las pistas…** (spec 017, T30; HU-017-3; RF-017-29, RF-017-24, RF-017-25, RF-017-30, RF-015-28; plan 017 §5.3.3 y §5.5; comprobación manual M3):
:class:`GEOBLENDER_OT_des_road_access` (``geoblender.des_road_access``, «Accesibilidad de las pistas…», de la entrada «017»: el tercer puesto de Diseño ▸ Pistas y entidades, T33b) calcula ``des.road_access`` de la versión activa con
``design.steps.access_run``: qué celdas se alcanzan a pie desde los puntos de entrada (la pendiente y el ancho transitables), las cotas mínima y máxima alcanzables —también sobre la final de una
cantera de dos superficies— y qué tramos de berma, plataformas y zonas «requiere acceso» quedan comunicados. Sigue el patrón de «Pista…» (:class:`_ChainsEntityLayer` + :class:`_CalculateAndCreate` +
:class:`DesignCommandAware` + :class:`~.core._StepsModal`), sin vista previa ni confirmaciones: no mueve ninguna celda. **La operación es de la versión** (D-18, decisión T30-a): hace falta una versión
activa editable; **la superficie sí puede ser del proyecto**. Su diálogo pide el nombre; **la superficie** (las del proyecto y las de la versión; **por defecto, la última de la cadena** de entidades y,
sin cadena, la explotación de su cantera: ``des_panels.access_default_surface``, ``design.access_store.default_surface``); la capa de **puntos de entrada** (``des_panels.access_layer_items``) con el campo
de su nombre y **los tres umbrales —la pendiente y el ancho transitables y el área mínima de un tramo de berma—, cada uno con su tipo** (HIPÓTESIS sin valor por defecto, D-17: :func:`_access_text`).
Lo pedido es una ``design.road_model.AccessRequest`` (su :meth:`~GEOBLENDER_OT_des_road_access._request`). Tras **Calcular**, la ventana de crear enseña el resumen (la cabecera, las cotas y el área, los
avisos y lo que quedará obsoleto) y **las listas** de tramos de berma, plataformas y zonas «requiere acceso», **comunicados o no** (los que no, primero y en alerta), cada fila con su cota o su distancia, su
lugar y su **«Ir a»** (``geoblender.core_go_to_place``; ``des_panels.access_sections`` y ``draw_access_lists``; el lugar, de ``design.access_store.access_places``); lo que no se comunica va también al
informe de la orden. **Tras crear, encadena** ``entity_store.after_entity_change``: la accesibilidad no declara restricciones, pero la capa de entidades se pone al día con su fila. Calcular, Crear,
Cancelar y Esc son los de :class:`_CalculateAndCreate`. Disponible con el proyecto en escritura y la versión activa editable y, si no, desactivada con su motivo (RF-017-29, RF-015-28:
:class:`DesignCommandAware`).

**El avance, Esc y «Crear» por pasos de la pista y la accesibilidad** (spec 017, T32; HU-017-1, HU-017-3; RF-017-30, RF-015-29, RNF-017-06; comprobación manual M9): desde la interfaz, «Calcular» y **«Crear»
son del modal de pasos** (:class:`_CreatesInSteps`, el patrón de la detección de acopios de la 016, T44): cada evento del temporizador, una llamada de ≤ 0,2 s —las de ``design.steps.road_run`` y
``access_run``, las de ``Calculation.create_steps`` (cada tabla y cada rejilla, montada y escrita en su temporal) y, **en el mismo modal**, las de lo que sigue a crear (``entity_store.after_entity_change``: la
declaración, las máscaras, la capa de entidades y la de ejes de pistas)—, con la transacción final como único paso que no se trocea (el R4 de la 012). **Esc en cualquier evento responde en ≤ 2 s**: entre los
pasos de calcular o de crear **no deja nada** (ni operación, ni dato, ni parámetro, ni cifra, ni temporal; el cálculo se descarta y su resumen y sus listas se vacían: hay que volver a calcular) y, **ya creada**, deja la
entidad creada y lo que sigue sin hacer (cada etapa es una operación y una transacción propias: la que Esc cierra queda cancelada y sin salidas; las máscaras, con su causa, y las capas se ponen al día con la orden de
entidades siguiente o «Recalcular lo obsoleto»). Desde un guion (sin ventana), «Crear» es de una vez, con el mismo resultado bit a bit; desactivar Geoblender cancela el modal como Esc
(:func:`bl.ops.core.cancel_running`) y ``register()`` y ``unregister()`` quitan todo lo de la 017, también lo de las ventanas, las listas y los ajustes de «Cambiar parámetro…».

**Proponer el trazado… y Exportar pista…** (spec 017, T33 (a); HU-017-1, HU-017-4; RF-017-28, RF-017-27, RF-017-29, RF-017-30, RF-015-28; H-9; plan 017 §5.3.3 y §5.5; comprobación manual M6):
:class:`GEOBLENDER_OT_des_propose_road` (``geoblender.des_propose_road``, «Proponer el trazado…», de la entrada «017»: el segundo puesto de Diseño ▸ Pistas y entidades, T33b) calcula ``des.road_propose`` de la versión activa con
``design.steps.road_propose_run``: **lo mismo que la pista «trazar» hasta la ruta y la rasante** (A1 a A5, sin A6 a A9) y deja **una capa de líneas con Z, editable en QGIS** (``des_rpl_<nombre>``), **sin tocar
ninguna superficie** y sin ser una entidad (no hay código, ni cadena, ni capa de entidades o de ejes, ni declaración). Su diálogo es el de «Pista…» en el modo «trazar» (la capa de puntos, el origen y el
destino, el perfil, la partida, las cotas y los nueve parámetros de la ruta con su tipo: :func:`_road_points`, :func:`_route_changes`, :func:`_draw_trace_points` y :func:`_draw_route_params`) y su
**vista previa** es la de **una propuesta** (``RoadAsk(propose=True)``: el origen, el destino y el pasillo de la ruta y, tras calcular, el eje con su rasante, sin sección; no la rechaza una partida que ya
ocupa otra entidad: T44, D-1; :func:`_redraw_road_preview`). El resumen de «Calcular» (``des_panels._propose_lines``) lleva la longitud, las pendientes con su
abscisa y su lugar, el radio mínimo y todos los avisos con su lugar; **la pendiente media por encima de pm solo avisa, sin pedir confirmación** (no graba ninguna superficie). **«Crear» es por pasos** desde la
interfaz, con el avance y Esc (:class:`_CreatesInSteps`, con su propio :meth:`~GEOBLENDER_OT_des_propose_road._creation_steps`: la capa en su temporal y la transacción final, y **nada de lo que sigue a crear una
entidad**), y de una vez desde un guion. Con el proyecto en escritura y la versión activa editable, y si no, desactivada con su motivo (:class:`DesignCommandAware`).
:class:`GEOBLENDER_OT_des_export_road` (``geoblender.des_export_road``, «Exportar pista…», de la entrada «017»: detrás de «Perfil de pista…», T33b) escribe, desde lo registrado y **sin escribir nada en el proyecto** (exportar no es una operación, H-9),
**la superficie de una pista** o **lo que alcanza una accesibilidad** como GeoTIFF y **la rasante de una pista a CSV** (``design.export.stored_road_export``, ``export_grid_steps`` y ``export_road_csv``): el
diálogo es el selector de ficheros de Blender (qué exportar y de qué pista o accesibilidad, en su panel; ``exports/<dato>_<V01>.tif`` o ``.csv`` propuesto), por pasos con el avance y Esc (la rasante, de
una vez) y sobre un fichero que ya existe pregunta antes de sustituirlo; vale con el proyecto en solo lectura (fuera de él) y con la versión superada. Dice en el informe qué escribió y dónde.

**El menú «Entidad ▾» e insertar antes o después** (spec 015, T31; HU-015-2, HU-015-3; RF-015-28, RF-015-05, RF-015-15; D-11,
D-14; plan 015 §5.3.3 y §5.5; comprobación manual M5): el menú contextual de las entidades
(``GEOBLENDER_MT_des_context_entity``, ``contexts.toml``, entrada «015») lleva las órdenes reales:
:class:`GEOBLENDER_OT_des_entity_dependents` («Lo que se apoya en ella») abre una ventana con **la lista única** de lo que se
apoya en la entidad o parte de su superficie (``design.entities.dependents``: nombre, tipo y m³) y en qué se apoya ella
(``dependencies_of``), las mismas filas de la barra N, sin escribir nada; :class:`GEOBLENDER_OT_des_entity_insert`
(«Insertar antes o después de…») elige la entidad de referencia (por defecto, la seleccionada) y antes o después, dice lo que
pasará (``design.entities.insertion_point``: la partida de la nueva y la sucesora) y abre **«Plataforma…»** con esa partida y
``insert_before`` (la entidad que pasará a partir de la nueva); al crear, la sucesora pasa a partir de la nueva con su motivo
y ella y las que la siguen quedan obsoletas con su causa (``design.entity_store.apply_insertion``, RF-015-05); sin
``insert_before``, dos entidades desde la misma superficie se rechazan (RF-015-04). Con «Traer las entidades de…»,
«Descartar…», «Soltar el apoyo…» y «Vista previa» —que toman la entidad seleccionada en la vista si no se les da otra:
:func:`_entity_or_selected`— y «Exportar rejilla a GeoTIFF…» (la de la T30), son las del menú. Todas, salvo la última,
**activas con el proyecto en escritura y la versión activa editable y, si no, desactivadas con su motivo**
(:class:`DesignCommandAware`, RF-015-28); exportar no es una operación (RF-013-34, D-29 de la 011) y vale también en solo
lectura y con la versión superada.
**Con los tipos nuevos de la 017** (T33b; RF-015-28, RF-015-05): el menú «Entidad ▾» es el mismo y sirve a **la pista** con las mismas órdenes (descartar, soltar el apoyo, lo que se apoya en ella, la vista previa de su
eje, traer e insertar junto a ella; «Insertar antes o después de…» abre siempre «Plataforma…»: la pista no admite ``insert_before``). **La accesibilidad no es una entidad con cadena** (sin ``start`` ni ``supports``):
«Traer las entidades de…» **no la ofrece ni la trae** (:func:`_is_bringable`: se vuelve a calcular en la versión), no se inserta junto a ella y no tiene vista previa; el menú contextual de su objeto (``DESIGN``) es «Diseño ▾».

**Calcular una entidad traída o heredada** (spec 015, T41; HU-015-2; RF-015-18; CE-015-01; hallazgo C-12): «Traer las
entidades de…» y la versión que parte de otra dejan la entidad con sus parámetros y **sin resultado**, y «Plataforma…» no podía
calcularla (``des.entity_name_repeated``, ``des.entity_start_taken``: «sin calcular» ocupa su nombre y su partida).
:class:`GEOBLENDER_OT_des_entity_calculate` («Calcular…» del menú «Entidad ▾») abre una ventana con las entidades **sin calcular**
de la versión activa (por su nombre: sin resultado no tiene objeto en la vista) y lanza **«Plataforma…» con su** ``code`` (la
propiedad oculta): sin diálogo, calcula con los parámetros que la entidad ya tiene en la versión
(``design.entity_store.entity_request``) y con su código, enseña el resumen y pide confirmar; «Crear» la registra **sin
escribir ningún parámetro** (conserva su código y su historial) y la dependencia «se apoya en» se detecta de nuevo. Se calculan
por el orden de la cadena (la partida de una es la superficie de la anterior). **Con la pista** (spec 017, T33c; RF-015-18, RF-015-04,
RF-017-01, RF-017-03; la duda T22b (d)): la ventana ofrece también **las pistas sin calcular** y «Calcular…» lanza **«Pista…»
(:class:`GEOBLENDER_OT_des_create_road`) con su** ``code`` (su propiedad oculta): sin diálogo, calcula por pasos con los parámetros
que la pista ya tiene en la versión (``design.road_store.entity_road_request``: la misma petición que repite el recálculo), y
«Crear» —por pasos y en una sola transacción, como «Pista…»— la registra con su código y sin tocar ningún parámetro; las
dependencias (el eje de la pista del origen, la plataforma del destino) se detectan de nuevo, así que **un ramal se calcula tras su
pista**. **La accesibilidad no es una entidad: no se trae ni se calcula desde aquí** (se vuelve a calcular con su orden).

**Retirar un acopio…** (spec 016, T20 (b); HU-016-2; RF-016-11 a RF-016-15, RF-015-03, RF-015-28, RF-015-29; RNF-016-05; plan 016 §5.3.3 y
§5.5; comprobación manual M1): :class:`GEOBLENDER_OT_des_remove_stockpile` (``geoblender.des_remove_stockpile``, interna, de la entrada
«016») calcula ``des.stockpile_removal`` de la versión activa con ``design.steps.removal_run``: la huella de un acopio de una detección
(``STK-001#Acopio 1``) en su base, unida al terreno por una transición, desde la superficie de partida. **Es el patrón de la orden que
calcula y crea de la 016** (el cuerpo apoyado, T25, y el contrafuerte, T27, lo siguen): :class:`_CalculateAndCreate` +
:class:`DesignCommandAware` + :class:`~.core._StepsModal`, con las listas de su diálogo en ``bl.ui.des_panels`` y el resumen en
``des_panels._removal_lines``. Su diálogo pide el nombre, el acopio (:func:`des_panels.removal_stockpile_items`: los de las detecciones
de la versión y del proyecto), la partida (la última de la cadena), **la lista de lo que se apoya en el acopio** —una sola lista, leída
**antes de calcular** por el ``update`` del acopio y de la partida con ``design.supported_store.resting_preview``: :func:`_refresh_resting`—,
el ángulo de transición (sin valor por defecto: D-2), el factor de malla, la métrica y el motivo de la pared. Calcular, Crear, Cancelar y
Esc son los de :class:`_CalculateAndCreate`: nada se registra hasta Crear (RF-015-03) y cerrarlo a mitad no deja nada (RF-015-29). **No se
crea sin la confirmación expresa** de lo que se le apoyaba ni de la pared (RF-016-14, RF-016-15): el botón de su ventana lo dice y pulsarlo
es la confirmación (``confirm_resting`` y ``confirm_wall``; desde un guion, quien la lanza); una pared de más de 45° y 3 m pide además el
motivo del diálogo, que **va en la petición** (se escribe al calcular). Quedan en los ajustes de la operación con su decisor y su fecha
(``design.supported_store.CONFIRMED``). **Tras crear, encadena** ``entity_store.after_entity_change`` (T41; :class:`_ChainsEntityLayer`): la
retirada no declara restricciones (D-1), pero la capa de entidades (``des_enl_<vNN>``, como operación aparte: T34) se pone al día con su fila,
por pasos con el avance y Esc. **«Como plataforma»** (T41; RF-016-16, A9; escenario E3): con ``as_platform`` el diálogo pide, en lugar de la
transición y la pared, **el borde de una plataforma** (el ángulo y el alcance, sin valor por defecto: D-7 y D-20 de la 015; el factor de malla y
la métrica valen para el borde) y la orden **calcula y crea una plataforma de la 015 con la huella del acopio** —una sola operación
``des.platform``: ``design.model.PlatformRequest.of_stockpile`` + ``design.steps.platform_run``; la huella entera queda en el plano de su base
y el resumen enseña las cifras de la plataforma y las de la retirada—; lo apoyado se confirma igual (``confirm_resting``) y su pared es la de su
borde, un aviso de la plataforma. La vista previa de «Plataforma…» no se enciende para la retirada (RF-016-23 no la pide). Disponible con el
proyecto en escritura y la versión activa editable y, si no, desactivada con su motivo (RF-015-28: :class:`DesignCommandAware`).

**Cuerpo apoyado…** (spec 016, T25; HU-016-4; RF-016-20 a RF-016-22, RF-015-03, RF-015-28, RF-015-29; RNF-016-02 y 05; comprobación manual
M2): :class:`GEOBLENDER_OT_des_create_body` (``geoblender.des_create_body``, interna, de la entrada «016») calcula ``des.body`` de la
versión activa con ``design.steps.body_run``: un cuerpo de espesor ≥ 0 con su huella (un polígono de una capa de entidades), sus datos
de espesor (un campo de puntos o de polígonos, o la Z de los vértices de una capa de líneas 3D: **la M no llega al proyecto**), la
superficie conocida y su sentido —«sobre una base» (apoyo: la superficie de la cadena sube hasta el techo) o «bajo un techo» (el escombro
existente: deja su base y su espesor dispersos y no cambia la superficie)—, la distancia máxima a los datos (sin valor por defecto: D-9) y
«cero en el borde». Sigue el patrón de la retirada (:class:`_CalculateAndCreate`; las listas de su diálogo y su resumen, en
``bl.ui.des_panels``): no retira nada ni deja una pared, así que no pide más confirmación que Crear. **Tras crear, encadena**
``entity_store.after_entity_change`` (T41; :class:`_ChainsEntityLayer`): el cuerpo no declara restricciones, pero la capa de entidades se pone
al día con su fila, como operación aparte (T34).

**Contrafuerte…** (spec 016, T27 (b); HU-016-3; RF-016-17, RF-016-18, RF-015-02, RF-015-03, RF-015-10, RF-015-12, RF-015-28, RF-015-29;
RNF-016-05; comprobación manual M3): :class:`GEOBLENDER_OT_des_add_buttress` (``geoblender.des_add_buttress``, la clave del catálogo, que
es de la entrada «016», entregada por la T35) calcula ``des.buttress`` de la versión activa con ``design.steps.buttress_run``:
el escalonado en relleno de la 013 desde una semilla en la zona de coronación, con el perfil de banco elegido y **sin cortar ninguna
celda**. Su diálogo pide el nombre, la capa de polígonos y la zona de coronación, la partida (la última de la cadena) y el apoyo, el perfil,
**la cota de coronación (sin valor por defecto: D-21; fuera del ancla de su perfil se rechaza con la cota del ancla más próxima,
RF-016-18)**, el alcance, la métrica y si protege (**por defecto sí**, D-1) con su resguardo (obligatorio si protege: D-19) y su motivo.
Calcular, Crear, Cancelar y Esc son los de :class:`_CalculateAndCreate`. **Tras crear, encadena** ``entity_store.after_entity_change`` como
«Plataforma…»: declara «sin corte» sobre la **zona de coronación** y no sobre toda la huella (P-8, H-6), recompila las máscaras y pone al
día la capa de entidades, por pasos con el avance y Esc.

**Acopio (detectar, retirar)…, Detectar acopios… y Candidatos de los acopios…** (spec 016, T35; HU-016-1, HU-016-4; RF-016-02, RF-016-08,
RF-016-10, RF-016-23, RF-016-25, RF-015-28, RF-015-29; RNF-016-05; D-3, D-15; plan 016 §5.3.3 y §5.5; comprobación manual M6):
:class:`GEOBLENDER_OT_des_edit_stockpile` (``geoblender.des_edit_stockpile``, la del menú Entidades y del menú «Entidad ▾») pregunta si se
detecta o se retira y abre la orden que toque cuando acaba ella. :class:`GEOBLENDER_OT_des_detect_stockpiles`
(``geoblender.des_detect_stockpiles``) calcula la detección con ``design.steps.stockpile_run``: su diálogo pide el nombre, **la superficie**
(las del proyecto y las de la versión activa: la detección es **del proyecto si la superficie lo es, también sin versión activa**, y de la
versión si es de una: D-15), la capa de marcas con sus campos (que propone de entre ``nombre``, ``margen``, ``material`` y ``base`` los que la
capa tiene), si busca candidatos y **los umbrales de D-3, cada uno con su valor por defecto y su tipo** (ADOPTADO o HIPÓTESIS): un umbral
vacío es el valor por defecto con su procedencia y la petición no lleva ninguna cifra minera; con la **«Vista previa» de las marcas**
(``bl.draw.entity.EntityPlan(stockpile=…)``, T32: se redibuja al cambiar un campo y se quita al cancelar, al Esc, al crear y al conmutar).
Calcular, Crear, Cancelar y Esc son los de :class:`_CalculateAndCreate` (``_ClearsEntityPreview`` antes); tras crear una detección **de una
versión** encadena ``entity_store.after_entity_change`` (la declaración, las máscaras y la capa de entidades con una fila por acopio, T34); la
del proyecto no encadena nada. :class:`GEOBLENDER_OT_des_stockpile_candidates` (``geoblender.des_stockpile_candidates``; los botones de la barra
N «Entidad» de la detección la llaman) lista los candidatos de la detección (la del objeto seleccionado, la que se dice o la única que tiene)
con su huella, área y volumen, su estado y «Ir a», y **decide** sobre uno —convertirlo en acopio, descartarlo o volver a preguntar, siempre
con su motivo: ``design.stockpile_store.decide_candidate``— y **recalcula la detección** con la decisión (``core_recompute_stale`` de esa
operación, por pasos con el avance y Esc). El código ``STK-001`` se repite en cada ámbito: la detección del proyecto seleccionada no la toman
las órdenes de las entidades de una versión.
"""

from __future__ import annotations

import functools
import json
import logging
import math
import sqlite3
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
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
from ...gis.masks import declaring
from ...gis.messages import GisError
from ..props.core import OBJECT_PROPERTY
from ..props.des import PREVIEW_PROPERTY, GEOBLENDER_PG_des_bring_row, GEOBLENDER_PG_des_refit_surface
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
    register_parameter_adjust,
    register_parameter_after,
    register_parameter_check,
    register_recompute_after,
    scope_choice,
    typed_value,
    unregister_parameter_adjust,
    unregister_parameter_after,
    unregister_parameter_check,
    unregister_recompute_after,
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
# ``design.reproduce.reproduce_declare_constraints``); la capa de entidades (T30) se recalcula
# (``design.entity_store.recompute_entity_layer``, que ``recompute_run`` llama) y **no se reproduce**: su contenido
# incluye el estado de cada entidad, que deduce el grafo del proyecto (como ``des.refit``).


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


# Los cuatro tipos de la 016 (T03; plan 016 §5.2.3): el mismo camino que los de las specs anteriores. Su recálculo lo hace
# ``design.store.recompute_run`` y su reproducción, ``design.reproduce``; **sin comportamiento todavía** (las tareas que
# crean cada operación, T14, T20, T25 y T27, les dan su cálculo: hasta entonces no hay ninguna operación de esos tipos
# que recalcular ni reproducir y ambas dicen qué tarea falta).


def recompute_stockpile_detect(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.stockpile_detect`` (RF-016-10; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_stockpile_removal(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.stockpile_removal`` (RF-016-11; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_buttress(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.buttress`` (RF-016-17; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_body(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.body`` (RF-016-20; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def reproduce_stockpile_detect(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.stockpile_detect``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_stockpile_detect(request)


def reproduce_stockpile_removal(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.stockpile_removal``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_stockpile_removal(request)


def reproduce_buttress(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.buttress``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_buttress(request)


def reproduce_body(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.body``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_body(request)


# Los tres tipos de la 017 (T03; plan 017 §5.2.3): el mismo camino que los de las specs anteriores. Su recálculo lo hace
# ``design.store.recompute_run`` y su reproducción, ``design.reproduce``. **Los tres tienen ya su cálculo**: la accesibilidad (T17b:
# ``access_store.recompute_access`` y ``reproduce.reproduce_road_access``), la pista (T22: ``road_store.recompute_road`` y ``reproduce.reproduce_road``) y
# «Proponer el trazado» (T27: ``road_store.recompute_propose`` y ``reproduce.reproduce_road_propose``).


def recompute_road(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.road`` (RF-017-01, RF-015-16; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_road_access(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.road_access`` (RF-017-24; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_road_propose(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.road_propose`` (RF-017-28; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def recompute_road_layer(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``des.road_layer`` (RF-017-27; T26-a; D-19 de la 013): véase el módulo."""
    return _recompute(request)


def reproduce_road(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.road``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_road(request)


def reproduce_road_access(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.road_access``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_road_access(request)


def reproduce_road_propose(request: ReproduceRequest) -> Iterator[Progress]:
    """La reproducción de ``des.road_propose``: la de ``design.reproduce``."""
    from ...design import reproduce  # al usarla: habilitar no carga la reproducción

    return reproduce.reproduce_road_propose(request)


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
"""La función de recálculo de cada tipo de la 015 (todos se repiten solos; RF-015-02, RF-015-27)."""
ENTITY_REPRODUCE: Mapping[str, Callable[[ReproduceRequest], Iterator[Progress]]] = (
    MappingProxyType({
        provenance.PLATFORM: reproduce_platform,
        provenance.DECLARE_CONSTRAINTS: reproduce_declare_constraints,
    }))
"""La función de reproducción de cada tipo de la 015 que se reproduce: la plataforma y la declaración de
restricciones (RF-015-02); la capa de entidades no (T30)."""
SUPPORTED_RECOMPUTE: Mapping[str, Callable[[RecomputeRequest], OperationHandle]] = (
    MappingProxyType({
        provenance.STOCKPILE_DETECT: recompute_stockpile_detect,
        provenance.STOCKPILE_DETECT_PROJECT: recompute_stockpile_detect,
        provenance.STOCKPILE_REMOVAL: recompute_stockpile_removal,
        provenance.BUTTRESS: recompute_buttress,
        provenance.BODY: recompute_body,
    }))
"""La función de recálculo de cada tipo de la 016 (todos se repiten solos; RF-016-10): la detección de versión y la de
proyecto (T04, D-15) con la misma, el mismo algoritmo en otro ámbito."""
SUPPORTED_REPRODUCE: Mapping[str, Callable[[ReproduceRequest], Iterator[Progress]]] = (
    MappingProxyType({
        provenance.STOCKPILE_DETECT: reproduce_stockpile_detect,
        provenance.STOCKPILE_DETECT_PROJECT: reproduce_stockpile_detect,
        provenance.STOCKPILE_REMOVAL: reproduce_stockpile_removal,
        provenance.BUTTRESS: reproduce_buttress,
        provenance.BODY: reproduce_body,
    }))
"""La función de reproducción de cada tipo de la 016 (todos se reproducen; RF-009-11): la detección de versión y la de
proyecto (T04, D-15) con la misma."""
ROAD_RECOMPUTE: Mapping[str, Callable[[RecomputeRequest], OperationHandle]] = (
    MappingProxyType({
        provenance.ROAD: recompute_road,
        provenance.ROAD_ACCESS: recompute_road_access,
        provenance.ROAD_PROPOSE: recompute_road_propose,
        provenance.ROAD_LAYER: recompute_road_layer,
    }))
"""La función de recálculo de cada tipo de la 017 (todos se repiten solos; RF-017-01, RF-017-24, RF-017-28 y, la capa de ejes de pistas, RF-017-27)."""
ROAD_REPRODUCE: Mapping[str, Callable[[ReproduceRequest], Iterator[Progress]]] = (
    MappingProxyType({
        provenance.ROAD: reproduce_road,
        provenance.ROAD_ACCESS: reproduce_road_access,
        provenance.ROAD_PROPOSE: reproduce_road_propose,
    }))
"""La función de reproducción de cada tipo de la 017 que se reproduce (la pista, la accesibilidad y la propuesta; RF-009-11): la capa de ejes de pistas no (T26-a), que incluye el estado de cada pista."""
OPERATION_DEFS: tuple[contract.OperationDef, ...] = (
    *provenance.operation_defs(RECOMPUTE, REPRODUCE), *design_profiles.OPERATIONS,
    *provenance.quarry_operation_defs(QUARRY_RECOMPUTE, QUARRY_REPRODUCE),
    *provenance.entity_operation_defs(ENTITY_RECOMPUTE, ENTITY_REPRODUCE),
    *provenance.supported_operation_defs(SUPPORTED_RECOMPUTE, SUPPORTED_REPRODUCE),
    *provenance.road_operation_defs(ROAD_RECOMPUTE, ROAD_REPRODUCE), *provenance.ROAD_PROFILE_OPERATIONS)
"""Los ``OperationDef`` de los veinte tipos de ``des``: de la 013, la envolvente y el escalonado, de
la versión y repetibles, y la edición de los perfiles de banco, del proyecto; de la 014, el recinto,
la cantera con dos superficies, la transición, «solo relleno» y el ajuste, de la versión y
repetibles (T05); de la 015, la plataforma, la declaración de restricciones y la capa de entidades,
de la versión y repetibles (T04); la capa de entidades no se reproduce (T30); de la 016 (T03), la
detección de acopios, su retirada, el contrafuerte y el cuerpo apoyado, de la versión, repetibles y
reproducibles, sin comportamiento todavía; de la 017 (T03), la pista, la accesibilidad de las pistas y «Proponer el trazado», de la
versión, repetibles y reproducibles (la accesibilidad, con su cálculo desde la T17b; la pista, desde la T22; la propuesta, desde la T27), y la edición de los
perfiles de pista, del proyecto y sin repetición."""
DEFINITIONS: tuple[core_params.ParamDef, ...] = (
    *design_params.DEFINITIONS, *design_params.QUARRY_DEFINITIONS)
"""Las definiciones de parámetros de ``des``: las dos del proyecto de la 013 y las siete de la 014
(plan 014 §5.2.2)."""
FAMILIES: tuple[core_params.ParamFamily, ...] = (*design_params.FAMILIES,
                                                *design_params.ENTITY_FAMILIES,
                                                *design_params.SUPPORTED_FAMILIES,
                                                *design_params.ROAD_FAMILIES, *design_params.ACCESS_FAMILIES,
                                                *design_params.ROAD_PROFILE_FAMILIES)
"""Las familias de parámetros de ``des`` (ADR-0027): las seis de la 013, las 20 de una plataforma
(``des.platform.{e}.*``, T04) y las de los cuatro tipos de la 016 (``des.stockpile.{e}.*``, ``des.removal.{e}.*``,
``des.buttress.{e}.*`` y ``des.body.{e}.*``, T03) y las de la 017 (``des.road.{e}.*``, ``des.access.{e}.*`` y, por perfil,
``des.roadprofile.{p}.*``, T03)."""
FIGURES: tuple[contract.FigureDef, ...] = (*provenance.FIGURES, *provenance.QUARRY_FIGURES,
                                           *provenance.ENTITY_FIGURES, *provenance.SUPPORTED_FIGURES,
                                           *provenance.ROAD_FIGURES, *provenance.ACCESS_FIGURES)
"""Las cifras de ``des``: las de la envolvente y las del escalonado (013), las de la 014, las de las
entidades (015), las de los cuatro tipos de la 016 (T03) y las de la pista y la accesibilidad (017, T03; las de la propuesta del
trazado son dos de la pista)."""


# --- El gancho de la declaración (spec 015, T38; RF-015-10, RF-015-29; CE-015-04) ---------------------


def _declaration_pending(project: Any, conn: Any, version_uid: str) -> bool:
    """Si una entidad viva de la versión que protege aún no tiene su restricción declarada (el gancho
    ``pending`` de ``gis.masks.declaring``: ``design.entity_store.declaration_pending``). Se pregunta con cada
    ``mask_state``, también al dibujar la interfaz: sin ninguna operación vigente de un tipo que declara (la plataforma y, desde la
    016, el contrafuerte: :func:`~...design.provenance.has_declaring_operation`) es **una consulta** y no importa las entidades
    (habilitar ni mirar las máscaras de una versión sin ellas las cargan)."""
    if not provenance.has_declaring_operation(conn, version_uid):
        return False
    from ...design import entity_store  # al usarlo: habilitar no carga las entidades

    return entity_store.declaration_pending(project, conn, version_uid)


def _declaration_steps(project: Any, version_uid: str, budget_s: float) -> Iterator[Progress]:
    """Los pasos de declarar las restricciones de las entidades de la versión (el gancho ``declare``:
    ``design.entity_store.declare_constraints_steps``)."""
    from ...design import entity_store  # al usarlo: habilitar no carga las entidades

    return entity_store.declare_constraints_steps(project, version_uid, budget_s=budget_s)


DECLARATION_HOOK = declaring.DeclarationHook(pending=_declaration_pending, declare=_declaration_steps)
"""Lo que ``des`` da a ``gis.masks.access`` (:mod:`geoblender.gis.masks.declaring`): las máscaras no están al día
mientras una entidad viva que protege no tenga su restricción en la declaración vigente, y quien las pide (los
operadores, «Compilar las máscaras») declara antes de compilar. Es :data:`design.entity_store.DECLARATION_HOOK` con
sus importaciones al usarlo, no al habilitar (:func:`register` lo registra)."""


# --- Las reglas entre entidades al cambiar un parámetro (spec 015, T39; RF-015-01, RF-015-04, RF-015-12) ---

PARAMETER_PREFIX = f"{design_params.PLATFORM_PREFIX}."
"""El principio de las claves de los parámetros de una plataforma (``des.platform.``): el único que vigilaba
:func:`_check_entity_parameter` hasta la T47 de la 016."""
PARAMETER_PREFIXES: tuple[str, ...] = tuple(f"{spec.key_prefix}." for spec in (
    design_params.PLATFORM_ENTITY, design_params.STOCKPILE_ENTITY, design_params.REMOVAL_ENTITY,
    design_params.BUTTRESS_ENTITY, design_params.BODY_ENTITY, design_params.ROAD_ENTITY, design_params.ACCESS_ENTITY))
"""El principio de las claves de los parámetros de **cada tipo de entidad** del programa (``des.platform.``, ``des.stockpile.``,
``des.removal.``, ``des.buttress.``, ``des.body.`` y, de la 017 (T03), ``des.road.`` y ``des.access.``): los que vigilan :func:`_check_entity_parameter` y lo que sigue a cambiarlos
(:func:`_after_entity_parameter`). Spec 016, T47 (hallazgo D-2): hasta entonces solo el de la plataforma, y un contrafuerte que protege
aceptaba un nombre vacío, y su resguardo declarado seguía en el de antes hasta una pasada de «Recalcular lo obsoleto»."""


def _check_entity_parameter(project: Any, key: str, value: Any, version_uid: str) -> None:
    """Lo que ``des`` registra en «Cambiar parámetro…» (:func:`~.core_provenance.register_parameter_check`):
    ``design.entity_store.check_parameter_change``, que aplica al cambio de un parámetro de una entidad **de cualquier tipo**
    (:data:`PARAMETER_PREFIXES`) las reglas entre entidades de crearla (nombre único, una entidad por superficie y sin ciclos, sin
    proteger en «en corte y relleno» ni sin resguardo). Importa el almacén al usarlo, no al habilitar."""
    from ...design import entity_store  # al usarlo: habilitar no carga las entidades

    entity_store.check_parameter_change(project, key, value, version=version_uid)


ROAD_PROFILE_PARAMETER_PREFIX = "des.roadprofile."
"""El principio de las claves de los valores de un perfil de pista (``des.roadprofile.{p}.*``, spec 017, T40): lo que vigila :func:`_check_road_profile_parameter` (no es de una entidad: el perfil es del proyecto)."""


def _check_road_profile_parameter(project: Any, key: str, value: Any, version_uid: str | None) -> None:
    """Lo que ``des`` registra en «Cambiar parámetro…» de un valor de un perfil de pista (:func:`~.core_provenance.register_parameter_check`; spec 017, T40; hallazgo A-1; RF-017-04, RF-017-07): lo
    mismo que comprueba «Perfil de pista…» (``design.road_profiles.check_profile_change``: el rango, con el ángulo de 90° excluido, y los radios con el resto del perfil) antes de que la orden
    escriba. **También con el ámbito proyecto** (``version_uid`` es ``None``; registrada con ``project_scope=True``, T49, hallazgo T47-1: un valor del proyecto llega a las versiones que no tienen el
    suyo y el diálogo propone el proyecto cuando la versión no tiene valor propio). Importa el módulo al usarlo, no al habilitar."""
    from ...design import road_profiles  # al usarlo: habilitar no carga los perfiles de pista

    road_profiles.check_profile_change(project, key, value, version=version_uid)


ROAD_PARAMETER_PREFIX = f"{design_params.ROAD_ENTITY.key_prefix}."
"""El principio de las claves de los parámetros de una pista (``des.road.``): el único del que :func:`_adjust_entity_parameter` completa el cambio."""
_HAND_LEVEL_SUFFIXES = (f".{design_params.RoadParam.START_LEVEL}", f".{design_params.RoadParam.END_LEVEL}", f".{design_params.RoadParam.SUPPORTS}")


def _adjust_entity_parameter(project: Any, key: str, record: Any, changes: dict[str, Any], version_uid: str) -> dict[str, Any]:
    """Lo que ``des`` registra para completar «Cambiar parámetro…» (:func:`~.core_provenance.register_parameter_adjust`; spec 017, T29c y T40; RF-017-03, D-13): quien cambia a mano **el valor de la
    cota de inicio o de fin de una pista** o **sus dependencias declaradas** (``supports``) que había derivado el algoritmo las deja **suyas** (``source_kind = person``, con su origen:
    ``design.road_store.parameter_changes``), de modo que recalcular no las vuelve a derivar. Con cualquier otro parámetro, los mismos cambios y sin importar el almacén (habilitar no carga las pistas)."""
    if "value" not in changes or not key.endswith(_HAND_LEVEL_SUFFIXES):
        return changes
    from ...design import road_store  # al usarlo: habilitar no carga las pistas

    return road_store.parameter_changes(project, key, record, changes, version=version_uid)


# --- Lo que sigue a cambiar una entidad y a «Recalcular lo obsoleto» (spec 015, T43; RF-015-10, RF-015-27) ---

REFRESH_ENTITIES = "geoblender.des_entity_refresh"


def _after_entity_parameter(project: Any, key: str, version_uid: str) -> None:
    """Lo que ``des`` registra tras «Cambiar parámetro…» (:func:`~.core_provenance.register_parameter_after`): el cambio
    de un parámetro de una entidad de la versión (``des.<tipo>.<e>.<p>`` de cualquier tipo, :data:`PARAMETER_PREFIXES`) hace lo que
    hace crear o descartar una —declarar sus restricciones, recompilar las máscaras si hace falta y poner al día la capa de
    entidades—, por pasos con el avance y Esc en :class:`GEOBLENDER_OT_des_entity_refresh`: sin esto, «Recalcular lo obsoleto» tardaba tres
    pasadas en dejar al día una entidad cuyo resguardo cambió y la capa decía «al día» sobre una entidad obsoleta
    (hallazgos E-2 y E-4). «Cambiar parámetro…» cambia el de la versión **activa** (``scope = VERSION``): es la que pone
    al día la orden; si ya no lo es, no hace nada."""
    if scene_versions.active_version() != version_uid:
        return
    bpy.ops.geoblender.des_entity_refresh("EXEC_DEFAULT", in_steps=True)


def _layers_after_recompute(project: Any) -> Iterator[Progress] | None:
    """Lo que ``des`` registra al terminar «Recalcular lo obsoleto» (:func:`~.core_provenance.register_recompute_after`):
    la capa de entidades de cada versión que no diga lo que el registro de sus entidades (``design.entity_store.
    layers_sync_steps``). La 008 rehace las entidades por el grafo y, si la salida de una no cambia (RF-008-26), no toca
    lo que depende de ella: la capa seguía diciendo «obsoleta» sobre una entidad al día (hallazgo E-4). Sin ninguna
    operación de **una entidad de cualquier tipo** en el proyecto (:data:`~...design.provenance.ENTITY_OP_NAMES`: la plataforma, la
    detección de acopios, la retirada, el contrafuerte y el cuerpo apoyado; spec 016, T47, hallazgo D-1: hasta entonces solo la
    plataforma, y en una versión con un contrafuerte solo la capa seguía «obsoleta» sobre una entidad al día) es una consulta y no
    importa el almacén (habilitar ni recalcular proyectos sin ellas lo cargan)."""
    names = provenance.ENTITY_OP_NAMES
    with project.read() as conn:
        found = conn.execute(f"SELECT 1 FROM gb_operation WHERE op_type IN ({', '.join('?' for _ in names)}) "
                             "AND status = 'done' AND superseded_by IS NULL LIMIT 1", names).fetchone()
    if found is None:
        return None
    from ...design import entity_store  # al usarlo: habilitar no carga las entidades

    return entity_store.layers_sync_steps(project)


# --- Registro ------------------------------------------------------------------------------------


def register() -> None:
    """Instala los textos del diseño en ``core.i18n`` y registra sus definiciones de parámetros
    (:data:`DEFINITIONS`), sus familias, sus tipos de operación (:data:`OPERATION_DEFS`) y sus
    cifras (:data:`FIGURES`) que aún no están, **el gancho de la declaración de las restricciones de las entidades**
    (:data:`DECLARATION_HOOK`, T38), **la comprobación de las reglas entre entidades al cambiar un parámetro de una**
    (:func:`_check_entity_parameter`, T39) y se apunta a los cambios de proyecto de la sesión
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
    if declaring.current() is not DECLARATION_HOOK:
        declaring.register(DECLARATION_HOOK)
        _UNDO.append(functools.partial(declaring.unregister, DECLARATION_HOOK))
    for prefix in PARAMETER_PREFIXES:  # los de cada tipo de entidad (T47, D-2)
        register_parameter_check(prefix, _check_entity_parameter)
        _UNDO.append(functools.partial(unregister_parameter_check, prefix, _check_entity_parameter))
        register_parameter_after(prefix, _after_entity_parameter)
        _UNDO.append(functools.partial(unregister_parameter_after, prefix, _after_entity_parameter))
    register_parameter_check(ROAD_PROFILE_PARAMETER_PREFIX, _check_road_profile_parameter, project_scope=True)  # los valores de un perfil de pista, con las reglas de «Perfil de pista…» (T40), también con el ámbito proyecto (T49)
    _UNDO.append(functools.partial(unregister_parameter_check, ROAD_PROFILE_PARAMETER_PREFIX, _check_road_profile_parameter))
    register_parameter_adjust(ROAD_PARAMETER_PREFIX, _adjust_entity_parameter)  # la cota y las dependencias que da la persona a mano (T29c y T40)
    _UNDO.append(functools.partial(unregister_parameter_adjust, ROAD_PARAMETER_PREFIX, _adjust_entity_parameter))
    register_recompute_after(_layers_after_recompute)
    _UNDO.append(functools.partial(unregister_recompute_after, _layers_after_recompute))
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
    que esperaba a la envolvente y las listas de una accesibilidad (``des_panels.show_access``, T30).
    Sin él, nada."""
    held = _HELD[:]
    _HELD.clear()
    _NEXT.clear()
    des_panels.show_access(None)
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


# --- Perfil de pista… (spec 017, T29; HU-017-1; RF-017-07, RF-017-08, RF-017-29, RF-015-28; plan 017 §5.3.3) ------------------------

EDIT_ROAD_PROFILE = provenance.ROAD_PROFILE_COMMAND
SAVE_ROAD_PROFILE = des_panels.SAVE_ROAD_PROFILE
ROAD_METRIC_ITEMS = [("DEFAULT", "Default (exact)", ""), ("EXACT", "Exact Euclidean", ""), ("CHAMFER5", "Chamfer 5×5", "")]
"""La métrica de las envolventes del borde de la pista: la «por defecto» (la euclídea exacta, D-2) no escribe ningún valor; las otras sí."""
_ROAD_EXAMPLE = "p"  # un código cualquiera para preguntar el ámbito de las claves de los perfiles de pista


def _road_fields() -> tuple[tuple[design_params.RoadProfileParam, str, str], ...]:
    """Los quince valores de un perfil de pista, en el orden del diálogo (RF-017-07): el valor, la propiedad de la orden que lo teclea y su
    etiqueta en el idioma de Geoblender (el arcén y el caballón, en metros; la pendiente de diseño pd, la media pm, en %)."""
    param = design_params.RoadProfileParam
    return (
        (param.VEHICLE_WIDTH, "vehicle", tr("Design vehicle width A (m)")),
        (param.LANE_FACTOR, "lane_factor", tr("Carriageway factor f")),
        (param.SHOULDER, "shoulder", tr("Shoulder width (m)")),
        (param.BERM, "windrow", tr("Windrow width (m)")),
        (param.MAX_GRADIENT, "max_gradient", tr("Maximum design gradient pd (%)")),
        (param.STATION_STEP, "station_step", tr("Step of the level profile w (m)")),
        (param.MAX_MEAN_GRADIENT, "max_mean_gradient", tr("Maximum mean gradient pm (%)")),
        (param.CURVE_RADIUS, "curve_radius", tr("Curve radius R (m)")),
        (param.MIN_RADIUS, "min_radius", tr("Minimum radius Rmin (m)")),
        (param.CUT_ANGLE, "cut_angle", tr("Cut angle (°)")),
        (param.FILL_ANGLE, "fill_angle", tr("Fill angle (°)")),
        (param.REACH, "reach", tr("Reach of the edge (m)")),
        (param.CLASS, "road_class", tr("Normative class")),
        (param.MESH_FACTOR, "mesh", tr("Mesh factor")),
        (param.METRIC, "metric", tr("Metric")),
    )


class GEOBLENDER_OT_des_edit_road_profile(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Road profiles such as PISTA_PRINCIPAL, with their values, their source and the widths derived from them"""

    bl_idname = EDIT_ROAD_PROFILE
    bl_label = "Road profile…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.EDIT_ROAD_PROFILES

    def execute(self, context: Any) -> set[str]:
        """Lee los perfiles de pista del proyecto y sus valores en la versión activa en la vista y abre su ventana; desde un guion sin
        ventana, solo la vista (RF-017-07, RF-017-08). Activa con el proyecto en escritura y la versión activa editable (o ninguna: la
        edición es de proyecto) y, si no, desactivada con su motivo (RF-017-29)."""
        try:
            des_panels.fill_road_profiles(SESSION.project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}
        return _call_panel(des_panels.ROAD_PROFILES_PANEL)


class GEOBLENDER_OT_des_save_road_profile(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Create a road profile, complete the values it lacks or rename it"""

    bl_idname = SAVE_ROAD_PROFILE
    bl_label = "Save road profile…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    provenance_op_type = provenance.EDIT_ROAD_PROFILES

    code: StringProperty(  # type: ignore[valid-type]
        name="Profile", description="Code of the road profile to complete or rename (empty: a new profile)", options=_HIDDEN)
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the profile, such as PISTA_PRINCIPAL: it can change, its code cannot", options=_FIELD)
    vehicle: StringProperty(  # type: ignore[valid-type]
        name="Design vehicle width A (m)", description="Width of the design vehicle in metres, more than 0", options=_FIELD)
    lane_factor: StringProperty(  # type: ignore[valid-type]
        name="Carriageway factor f",
        description="Factor that multiplies the width of the vehicle to give the carriageway, more than 0", options=_FIELD)
    shoulder: StringProperty(  # type: ignore[valid-type]
        name="Shoulder width (m)", description="Width of the shoulder in metres, 0 or more", options=_FIELD)
    windrow: StringProperty(  # type: ignore[valid-type]
        name="Windrow width (m)", description="Width of the windrow in metres, 0 or more", options=_FIELD)
    max_gradient: StringProperty(  # type: ignore[valid-type]
        name="Maximum design gradient pd (%)", description="Maximum gradient of the haul road in per cent, more than 0",
        options=_FIELD)
    station_step: StringProperty(  # type: ignore[valid-type]
        name="Step of the level profile w (m)",
        description="Distance between the stations where the gradient is checked, in metres, more than 0", options=_FIELD)
    max_mean_gradient: StringProperty(  # type: ignore[valid-type]
        name="Maximum mean gradient pm (%)",
        description="Maximum mean gradient of the whole haul road in per cent, more than 0", options=_FIELD)
    curve_radius: StringProperty(  # type: ignore[valid-type]
        name="Curve radius R (m)", description="Radius of the curves in metres, more than 0", options=_FIELD)
    min_radius: StringProperty(  # type: ignore[valid-type]
        name="Minimum radius Rmin (m)",
        description="Smallest radius allowed in metres, more than 0, at most R and at least the half width of the section",
        options=_FIELD)
    cut_angle: StringProperty(  # type: ignore[valid-type]
        name="Cut angle (°)",
        description="Inclination of the cut slope at the edge of the haul road in degrees, between 0 and 90 (both excluded)",
        options=_FIELD)
    fill_angle: StringProperty(  # type: ignore[valid-type]
        name="Fill angle (°)",
        description="Inclination of the fill slope at the edge of the haul road in degrees, between 0 and 90 (both excluded)",
        options=_FIELD)
    reach: StringProperty(  # type: ignore[valid-type]
        name="Reach of the edge (m)",
        description="How far the cut and fill slopes of the edge reach, in metres, more than 0", options=_FIELD)
    road_class: StringProperty(  # type: ignore[valid-type]
        name="Normative class",
        description="Class of the haul road in the standard it follows, such as «main» or «access to the pit»", options=_FIELD)
    mesh: StringProperty(  # type: ignore[valid-type]
        name="Mesh factor",
        description="Factor between 0 (excluded) and 1 that reduces the slope of the edge for the grid (empty: 1)", options=_FIELD)
    metric: EnumProperty(  # type: ignore[valid-type]
        name="Metric",
        description="How the distance of the edge is measured: the exact Euclidean distance (the default) or the 5×5 chamfer",
        items=ROAD_METRIC_ITEMS, default="DEFAULT", options=_FIELD)
    kind: EnumProperty(  # type: ignore[valid-type]
        name="Type", description="Type of the values: adopted or hypothesis", items=PROFILE_KIND_ITEMS, default="ADOPTADO",
        options=_FIELD)
    source: StringProperty(  # type: ignore[valid-type]
        name="Source",
        description="Document, standard, person, operation or algorithm the values come from (empty: the decider)", options=_FIELD)
    source_kind: EnumProperty(  # type: ignore[valid-type]
        name="Source type",
        description="Whether the source is a document, a standard, a person, an operation or an algorithm",
        items=SOURCE_KIND_ITEMS, default="PERSON", options=_FIELD)
    decided_by: StringProperty(  # type: ignore[valid-type]
        name="Decided by", description="Who decided the values (the owner, a laboratory, a person)", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the profile has these values (recorded in its history)", options=_FIELD)
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Scope",
        description="Whether the change is for the project or only for the active version (a parameter that its module admits by "
                    "version)",
        items=PARAMETER_SCOPE_ITEMS, default="PROJECT", options=_FIELD)

    def _stored(self, project: Any) -> Any:
        """La fila del perfil de :attr:`code` en el proyecto; ``ProfileFormError`` si ya no está (sin código, ``None``: un perfil nuevo)."""
        from ...design import road_profiles  # al usarlo: habilitar no lo carga (RNF-001-03)

        if not self.code:
            return None
        with project.read() as conn:
            found = [row for row in road_profiles.read_profiles(conn) if row.code == self.code]
        if not found:
            raise ProfileFormError(tr("The road profile is no longer in the project: open the list again"))
        return found[0]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo: de un perfil que existe, con su nombre y lo que ya vale en cada ámbito (solo se piden los valores que le
        faltan); de uno nuevo, vacío. Propone el decisor (la persona de la sesión) y, de los parámetros de versión con una versión activa,
        el ámbito (RF-009-29); no cambia nada hasta que se acepta."""
        self.provenance_dialog = True
        project = SESSION.project
        try:
            row = self._stored(project)
            self._known = {} if row is None else _known_road_values(project, row.code)
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
            self, width=DIALOG_WIDTH, translate=False, title=tr("Road profile"), confirm_text=tr("Save"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        choice = scope_choice(design_params.road_profile_key(_ROAD_EXAMPLE, design_params.RoadProfileParam.VEHICLE_WIDTH))
        if choice is not None:  # «¿Para el proyecto o solo para V01?» (RF-009-29)
            layout.label(text=tr("For the project or only for {version}?", version=choice.code), translate=False)
            row = layout.row(align=True)
            row.use_property_split = False
            row.prop_enum(self, "scope", "PROJECT", text=tr("The project"), translate=False)
            only = row.row(align=True)
            only.enabled = choice.refusal is None  # «Versión no editable» (RF-009-21)
            only.prop_enum(self, "scope", "VERSION", text=tr("Only {version}", version=choice.code), translate=False)
            if choice.refusal is not None:
                refused = layout.row()
                refused.alert = True
                refused.label(text=choice.refusal, icon="ERROR", translate=False)
        known = getattr(self, "_known", {})
        declared = False
        for param, attribute, label in _road_fields():
            here = known.get(param, {}).get(self.scope)
            if here is not None:  # ya vale en ese ámbito: se cambia con «Cambiar…»
                layout.label(text=tr("{name}: {value}", name=label, value=here), translate=False)
                declared = True
            else:
                layout.prop(self, attribute, text=label, translate=False)
        if declared:
            layout.label(text=tr("Values already declared are changed with «Change…» in the list"), translate=False)
        layout.prop(self, "kind", text=tr("Type"), translate=False)
        layout.prop(self, "source", text=tr("Source"), translate=False)
        layout.prop(self, "source_kind", text=tr("Source type"), translate=False)
        layout.prop(self, "decided_by", text=tr("Decided by"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def _request(self, project: Any) -> tuple[Any, Any]:
        """Lo escrito, como lo pide el dominio: la edición (un perfil nuevo con sus valores, o el existente con su nombre nuevo y los valores
        que se completan) y la declaración de los valores (tipo, fuente, decisor, motivo y ámbito). :class:`ProfileFormError` si lo escrito no
        se puede leer o no cambia nada; los rangos, los radios, los nombres y los valores que faltan los rechaza el dominio (``DesignError``,
        RF-017-07): ninguna regla ni cuenta es de aquí."""
        from ...design import road_profiles  # al usarlo: habilitar no lo carga (RNF-001-03)

        row = self._stored(project)
        param = design_params.RoadProfileParam
        values: dict[Any, Any] = {}
        for item, attribute, label in _road_fields():
            typed = getattr(self, attribute)
            if item is param.CLASS:
                if typed.strip():
                    values[item] = typed.strip()
            elif item is param.METRIC:
                if typed != "DEFAULT":  # la métrica por defecto no escribe ningún valor (D-2)
                    values[item] = typed.lower()
            else:
                number = typed_number(typed, label)
                if number is not None:  # un perfil nuevo sin un valor: el dominio dice cuál falta
                    values[item] = number
        if row is None:
            edit = road_profiles.ProfileEdit(name=self.name, values=values)
        else:
            typed_name = self.name.strip()  # vacío: se queda con el suyo
            renamed = self.name if typed_name and typed_name != row.name else None
            if renamed is None and not values:
                raise ProfileFormError(tr("Nothing to change in «{name}»", name=row.name))
            edit = road_profiles.ProfileEdit(name=renamed, code=row.code, values=values)
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
                raise ProfileFormError(tr("Choose the active version first: Project ▸ Versions ▸ Active version"))
            version = active.code
        kind = ParamKind.ADOPTADO if self.kind == "ADOPTADO" else ParamKind.HIPOTESIS
        return edit, road_profiles.ProfileDeclaration(
            source=source or decided_by, decided_by=decided_by,
            reason=self.reason.strip() or tr("Declared in the road profiles window"),
            source_kind=self.source_kind.lower() if source else "person", kind=kind.value, version=version)

    def execute(self, context: Any) -> set[str]:
        """Crea, completa o renombra el perfil con ``design.road_profiles.edit_road_profiles`` (una sola operación de proyecto y una sola
        transacción; RF-017-07). Todo se mira antes de escribir: un perfil sin nombre, con el nombre de otro, sin un valor, con uno fuera de
        rango o con los radios que no caben se rechaza nombrando el perfil, el campo y el valor, y no deja nada (0 transacciones)."""
        from ...design import road_profiles  # al usarlo: habilitar no lo carga (RNF-001-03)

        project = SESSION.project
        try:
            edit, declaration = self._request(project)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report, dialog=self.provenance_dialog,
                             version=scene_versions.active_version())
        if ready is None:
            return {"CANCELLED"}
        try:
            edited = road_profiles.edit_road_profiles(project, [edit], declaration)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, provenance.EDIT_ROAD_PROFILES)
        code = edited.created[0] if edited.created else edit.code
        shown = next(row.name for row in edited.profiles if row.code == code)
        text = (tr("Road profile «{name}» created with the code «{code}»", name=shown, code=code) if edited.created else
                tr("Road profile «{name}» saved (code «{code}»)", name=shown, code=code))
        try:
            des_panels.fill_road_profiles(project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.warning("No se pudo volver a leer la lista de perfiles de pista", exc_info=True)
        des_panels.choose_road(code)
        des_panels.show_road_report([(text, False)])
        self.report({"INFO"}, text)
        return {"FINISHED"}


def _known_road_values(project: Any, code: str) -> dict[Any, dict[str, str]]:
    """Lo que el perfil de pista ``code`` ya tiene declarado, por valor y ámbito (``PROJECT`` o ``VERSION``, el de la versión activa): su
    texto («3,5 m [ADO]»). Con ello el diálogo de completar no pide lo que ya vale (se cambia con «Cambiar…»)."""
    store = core_params.ParameterStore(project)
    version = scene_versions.active()
    found: dict[Any, dict[str, str]] = {}
    with project.read() as conn:
        for param in design_params.RoadProfileParam:
            key = design_params.road_profile_key(code, param)
            records = {"PROJECT": store.get(key, conn=conn),
                       "VERSION": None if version is None else store.get(key, version=version.uid, conn=conn)}
            found[param] = {scope: des_panels.record_text(record) for scope, record in records.items()
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
        # El informe de la orden lleva el resumen **entero** (T51, H3-4): el del diálogo (``shown.summary``) se recorta en las pistas para que «Crear» quepa en la ventana.
        for text, alert in () if shown is None else des_panels.summary_lines(opened):
            self._report({"WARNING" if alert else "INFO"}, text)
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
        self._registered(opened)
        return {"FINISHED"}

    def _registered(self, opened: Calculation) -> None:
        """Lo que hace la orden en cuanto el cálculo ``opened`` está **registrado** (T44: lo comparten crear de una vez y crear por
        pasos): lo anota para Ctrl+Z (que no lo deshace), pone al día los indicadores de la procedencia, vacía el resumen y lo dice en
        el informe."""
        undo_watch.record(UndoKind.OPERATION, opened.op_type)  # Ctrl+Z no lo deshace
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        des_panels.show_summary(None)
        self._report({"INFO"}, self._created_text(opened))

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
_PLATFORM_HIDDEN = frozenset({"confirm", "in_steps", "confirm_counterslope", "preview", "insert_before", "code"})
"""Las propiedades ocultas de «Plataforma…»: las pone quien la lanza (o su ventana de confirmar)."""
ENTITY_PREVIEW = "geoblender.des_entity_preview"
ENTITY_DRAW_MODULE = "draw.entity"
"""El módulo de la vista previa de una entidad dentro de ``bl`` (``bl.draw.entity``)."""


def _entity_preview() -> Any:
    """El módulo de la vista previa de una entidad (``bl.draw.entity``), importado al usarlo."""
    from ..draw import entity as preview  # al usarlo: nada pesado al registrar

    return preview


def _entity_preview_loaded() -> Any:
    """El módulo de la vista previa de una entidad **si ya está importado** (si no, ``None``: no puede estar
    activa y no hace falta importarlo para saberlo)."""
    return sys.modules.get(f"{__package__.rsplit('.', 1)[0]}.{ENTITY_DRAW_MODULE}")


def _entity_preview_on() -> bool:
    """Si la vista previa de una entidad está activa."""
    loaded = _entity_preview_loaded()
    return bool(loaded is not None and loaded.enabled())


def _entity_preview_off() -> None:
    """Quita la vista previa de una entidad si está activa (cancelar la orden, crear la plataforma)."""
    loaded = _entity_preview_loaded()
    if loaded is not None:
        loaded.disable()


def _platform_fields() -> tuple[str, ...]:
    """Los campos del diálogo de «Plataforma…»: sus propiedades no ocultas."""
    return tuple(name for name in GEOBLENDER_OT_des_create_platform.__annotations__
                 if name not in _PLATFORM_HIDDEN)


def _draw_entity_preview_button(layout: Any, operator: Any, command: str, fields: Iterable[str],
                                **extra: Any) -> None:
    """El botón «Vista previa» del diálogo de una orden de entidades (T29 y, con la 016, T32; RF-015-26, RF-016-23): la misma orden
    (``command``) con la propiedad oculta ``preview`` y todo lo pedido en el diálogo (cada campo de ``fields``, tal como está; ``extra``,
    lo que más se le pone), que se ejecuta sin abrir otro diálogo. Un valor que su lista ya no ofrece se queda en el de por defecto (y lo
    rechaza la orden si falta)."""
    row = layout.row()
    row.operator_context = "EXEC_DEFAULT"
    shown = row.operator(command, text=tr("Preview"), icon="HIDE_OFF")
    for name in fields:
        try:
            setattr(shown, name, getattr(operator, name))
        except (TypeError, ValueError):
            LOGGER.debug("El campo %s no pasa a la vista previa de %s", name, command, exc_info=True)
    for name, value in extra.items():
        setattr(shown, name, value)
    shown.preview = True


def _draw_platform_preview_button(layout: Any, operator: Any) -> None:
    """El botón «Vista previa» del diálogo de «Plataforma…» (T29; RF-015-26): la misma orden con ``preview`` y todo lo
    pedido en el diálogo (cada campo, tal como está), que se ejecuta sin abrir otro diálogo. Un valor que su lista ya
    no ofrece se queda en el de por defecto (y lo rechaza la orden si falta)."""
    _draw_entity_preview_button(layout, operator, CREATE_PLATFORM, _platform_fields(),
                                insert_before=operator.insert_before)  # una inserción se previsualiza como tal (RF-015-05)


class _ClearsEntityPreview:
    """Lo que toda orden de entidades que tiene «Vista previa» hace con ella (T29 y T32; RF-015-26, RF-016-23): **quitarla al
    cancelar** la orden (``cancel``: su diálogo y su ventana de confirmar) y al **Esc a mitad del cálculo** y al desactivar Geoblender
    (``_StepsModal._stop``: Esc en un modal de pasos no llama a ``cancel``, ``docs/trampas.md`` §4). Es de las órdenes de
    :class:`_CalculateAndCreate` y va **antes** de ella en sus bases (``cancel`` llama a la suya por su nombre, como
    ``GEOBLENDER_OT_des_create_platform``: las pruebas lo llaman con un ``self`` simulado, que ``super()`` no admite)."""

    def cancel(self, context: Any) -> None:
        """Lo que Blender llama al cancelar: quita la vista previa de la entidad y hace lo de siempre
        (:meth:`_CalculateAndCreate.cancel`)."""
        _entity_preview_off()
        _CalculateAndCreate.cancel(self, context)  # type: ignore[arg-type]

    def _stop(self, context: Any, *, after: bool = True) -> set[str]:
        """Esc a mitad del cálculo: los pasos se cierran como siempre y la vista previa de la entidad se quita."""
        stopped = super()._stop(context, after=after)  # type: ignore[misc]
        _entity_preview_off()
        return stopped  # type: ignore[no-any-return]


def _refresh_preview(self: Any, _context: Any) -> None:
    """El ``update`` de cada campo de «Plataforma…» (T29; RF-015-26): con la vista previa de **esa plataforma** activa
    (la de una entidad de la versión no), la redibuja con lo que dice ahora el diálogo. Un diálogo a medias (un campo
    sin escribir, un número que no lo es) no la cambia: sigue la última completa. Solo lee."""
    loaded = _entity_preview_loaded()
    if loaded is None or not loaded.enabled() or loaded.plan() is None or loaded.plan().request is None:
        return
    try:
        request = GEOBLENDER_OT_des_create_platform._request(self)
    except ProfileFormError:
        return
    loaded.replace(loaded.EntityPlan(request=request, insert_before=self.insert_before.strip() or None))


def _propose_and_refresh(self: Any, context: Any) -> None:
    """El ``update`` de la capa, la geometría y sus campos: propone la cota inicial, la pendiente y el ancho de la capa
    (:func:`_propose_values`) y redibuja la vista previa (:func:`_refresh_preview`)."""
    _propose_values(self, context)
    _refresh_preview(self, context)


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


def _entity_request(project: Any, version: str, code: str) -> design_model.PlatformRequest:
    """La petición de la entidad **sin calcular** ``code`` de la versión ``version`` (T41; RF-015-18; hallazgo C-12;
    ``design.entity_store.entity_request``: de los parámetros que ya tiene la versión, con los campos de la capa de por
    defecto del diálogo de «Plataforma…»; solo lee)."""
    from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

    return entity_store.entity_request(project, version, code, start_level_field=START_LEVEL_FIELD,
                                       gradient_field=GRADIENT_FIELD, width_field=WIDTH_FIELD)


class GEOBLENDER_OT_des_create_platform(_CalculateAndCreate, DesignCommandAware,
                                        ProvenanceAwareOperator, _StepsModal, bpy.types.Operator):
    """Platform of a layer of the project: its footprint and its level applied to its start surface,
    with the edge that joins it with the ground"""

    bl_idname = CREATE_PLATFORM
    bl_label = "Platform…"
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
        items=des_panels.platform_layer_items, options=_FIELD, update=_propose_and_refresh)
    feature: StringProperty(  # type: ignore[valid-type]
        name="Platform of the layer",
        description="Name or number (fid) of the geometry of the layer that is the platform",
        options=_FIELD, update=_propose_and_refresh)
    start_level_field: StringProperty(  # type: ignore[valid-type]
        name="Start elevation field",
        description="Numeric field of the layer with the elevation of the platform level at the "
                    "start of the axis in metres", default=START_LEVEL_FIELD, options=_FIELD,
        update=_propose_and_refresh)
    gradient_field: StringProperty(  # type: ignore[valid-type]
        name="Gradient field",
        description="Numeric field of the layer with the gradient of the platform level in %, positive "
                    "when it rises along the axis", default=GRADIENT_FIELD, options=_FIELD,
        update=_propose_and_refresh)
    width_field: StringProperty(  # type: ignore[valid-type]
        name="Width field",
        description="Numeric field of the layer of lines with the width of each platform in metres",
        default=WIDTH_FIELD, options=_FIELD, update=_propose_and_refresh)
    axis_layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of axes",
        description="Layer of lines with the axis of each polygon (none: the main axis of the "
                    "polygon)", items=des_panels.line_layer_items, options=_FIELD, update=_refresh_preview)
    axis_field: StringProperty(  # type: ignore[valid-type]
        name="Axis link field",
        description="Numeric field of the layer of polygons with the number (fid) of its axis in the "
                    "layer of axes", default=AXIS_LINK_FIELD, options=_FIELD, update=_refresh_preview)
    start_level: StringProperty(  # type: ignore[valid-type]
        name="Start elevation (m)",
        description="Elevation of the platform level at the start of the axis in metres (abscissa 0: the first "
                    "vertex of a line; in a polygon with a linked line, where the line enters the polygon): the one "
                    "of the layer, which you can correct (empty: the one of the layer)", options=_FIELD,
        update=_refresh_preview)
    gradient: StringProperty(  # type: ignore[valid-type]
        name="Gradient (%)",
        description="Gradient of the platform level in %, positive when it rises along the axis: the one "
                    "of the layer, which you can correct (empty: the one of the layer)",
        options=_FIELD, update=_refresh_preview)
    width: StringProperty(  # type: ignore[valid-type]
        name="Width (m)",
        description="Width of the platform in metres: the one of the layer, which you can correct "
                    "(empty: the one of the layer)", options=_FIELD, update=_refresh_preview)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the platform starts from: the ground, a design surface or the surface "
                    "of another platform (by default, the last of the chain)",
        items=des_panels.platform_start_items, options=_FIELD, update=_refresh_preview)
    support: EnumProperty(  # type: ignore[valid-type]
        name="Support surface",
        description="Surface the platform rests on, if it rests on one (none: it rests on no other "
                    "surface)", items=des_panels.platform_support_items, options=_FIELD, update=_refresh_preview)
    mode: EnumProperty(  # type: ignore[valid-type]
        name="Mode",
        description="In cut: the platform only lowers the ground to its level; in cut and fill: "
                    "it also raises it where fill is admitted", items=PLATFORM_MODE_ITEMS,
        default="CUT", options=_FIELD, update=_refresh_preview)
    edge_angle: StringProperty(  # type: ignore[valid-type]
        name="Edge angle (°)",
        description="Angle of the slope that joins the platform with the ground, in degrees",
        options=_FIELD, update=_refresh_preview)
    reach: StringProperty(  # type: ignore[valid-type]
        name="Reach of the edge (m)",
        description="Farthest distance from the footprint the edge can reach, in metres",
        options=_FIELD, update=_refresh_preview)
    mesh_factor: StringProperty(  # type: ignore[valid-type]
        name="Mesh factor",
        description="Factor of the mesh of the edge (empty: the default value)", options=_FIELD, update=_refresh_preview)
    metric: EnumProperty(  # type: ignore[valid-type]
        name="Metric",
        description="How the distance to the footprint is measured: the 5×5 chamfer (fast, with the "
                    "scale of the grid) or the exact Euclidean distance", items=METRIC_ITEMS,
        default="EXACT", options=_FIELD, update=_refresh_preview)
    counter_tolerance: StringProperty(  # type: ignore[valid-type]
        name="Counter-slope tolerance (m)",
        description="How much the longitudinal profile can rise against the sense in which the "
                    "platform level falls before it has to be confirmed, in metres (empty: the "
                    "default value)",
        options=_FIELD, update=_refresh_preview)
    protect: BoolProperty(  # type: ignore[valid-type]
        name="Protect",
        description="Declare the footprint a protected zone: the other designs neither cut nor fill "
                    "in it", default=False, options=_FIELD, update=_refresh_preview)
    guard: StringProperty(  # type: ignore[valid-type]
        name="Guard (m)",
        description="Distance around the footprint that is also protected, in metres; required to "
                    "protect", options=_FIELD, update=_refresh_preview)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con
    # el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez. La confirmación expresa de
    # la contrapendiente (RF-015-23): la pone el botón de su ventana, que lo dice; desde un guion, quien
    # la lanza.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    confirm_counterslope: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    # La vista previa (T29; RF-015-26): el botón «Vista previa» del diálogo la pone y la orden enseña lo pedido.
    preview: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    # Insertar antes o después de otra entidad (T31; RF-015-05): la entidad (su código) que hoy parte de la misma superficie y
    # que pasará a partir de la de la nueva; la pone «Insertar antes o después de…» al abrir el diálogo.
    insert_before: StringProperty(default="", options=_HIDDEN)  # type: ignore[valid-type]
    # Calcular una entidad traída o heredada «sin calcular» (T41; RF-015-18; hallazgo C-12): el código de la entidad que ya está en
    # la versión; la pone «Calcular…» del menú «Entidad ▾». Con él no hay diálogo: se calcula con los parámetros que la entidad ya
    # tiene en la versión (``design.entity_store.entity_request``), con su código, sin escribir ninguno.
    code: StringProperty(default="", options=_HIDDEN)  # type: ignore[valid-type]

    _insert_name = ""
    """El nombre de la entidad ``insert_before`` como lo enseña el diálogo (lo lee ``invoke``)."""

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué.
        Con ``confirm``, el diálogo de crear el cálculo abierto. Con ``code`` (una entidad sin calcular, T41), sin
        diálogo: calcula (:meth:`execute`). Si no, las listas de capas y de superficies leídas de nuevo, la propuesta
        (el nombre, la capa y la partida: la última de la cadena) y el diálogo del cálculo: Intro calcula."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        if self.code.strip():  # una entidad sin calcular: todo lo que hace falta ya lo tiene la versión (T41)
            return self.execute(context)
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            des_panels.refresh_choices(project)
            des_panels.refresh_platform_choices(project, insert_before=self.insert_before.strip() or None)
            self._propose(context, project)
            self._insert_name = self._insertion_name(project)
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

    def _insertion_name(self, project: Any) -> str:
        """El nombre de la entidad ``insert_before`` (T31; RF-015-05) como lo enseña el diálogo: el de la entidad de la versión
        activa o, si no es de ella, lo que dice la propiedad; vacío si no se inserta."""
        wanted = self.insert_before.strip()
        if not wanted:
            return ""
        from ...design import entities  # al usarlo: habilitar no carga las entidades

        found = entities.registry(project, scene_versions.active_version() or "").get(wanted)
        return wanted if found is None else found.record.name

    def draw(self, context: Any) -> None:
        """Arriba el nombre (y, si se inserta antes de otra entidad, lo que pasará con ella); la capa, la geometría y sus
        campos; los valores que da la capa (la cota inicial, la pendiente y el ancho), que se corrigen aquí; la partida, el
        apoyo y el modo; el borde (su ángulo, su alcance, su factor de malla y la métrica); la tolerancia de
        contrapendiente y si protege, con su resguardo. En la confirmación de crear, el resumen."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        kind = des_panels.platform_layer_kind(self.layer)
        if self.insert_before.strip():  # una inserción (RF-015-05): lo que pasará con la que la sigue
            layout.label(text=tr("It is inserted before «{entity}»: «{entity}» will start from its surface and, with "
                                 "what follows it, will be out of date until it is recomputed",
                                 entity=self._insert_name or self.insert_before.strip()),
                         icon="INFO", translate=False)
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
        _draw_platform_preview_button(layout, self)

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
        sector con la búsqueda pendiente, el nombre repetido) y todas las cuentas son de ``design``. Con ``preview``, la
        vista previa de lo pedido (:meth:`_show_preview`). Con ``code`` (T41), la entidad **sin calcular** de la versión
        con ese código (:func:`_entity_request`: la que dejó «Traer las entidades de…» o heredó una versión que parte de
        otra): se calcula con los parámetros que ya tiene y con su código, sin escribir ninguno."""
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
        code = self.code.strip()
        try:
            request = _entity_request(project, version, code) if code else self._request()
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
        steps = design_steps.platform_run(project, request, version=version, code=code or None,
                                          insert_before=self.insert_before.strip() or None,
                                          budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _show_preview(self) -> set[str]:
        """«Vista previa» (T29; RF-015-26): comprueba lo pedido como al calcular (:meth:`_request`, sin escribir ni
        calcular nada) y activa con ello la vista previa de la entidad (``bl.draw.entity``: la huella, el eje con la
        flecha de su sentido y las cotas de la rasante en sus extremos, lo que se le apoya y las restricciones que
        declarará, con su leyenda); la que hubiera activa se cambia por la nueva (pulsarlo otra vez, o cambiar un
        campo del diálogo: :func:`_refresh_preview`). Lo que falta del diálogo se rechaza sin tocar la vista previa; lo
        que rechazaría «Calcular» (RF-015-08, RF-015-09) sale en la propia vista previa, como aviso. Se quita al
        cancelar la orden, al crear la plataforma, con su control y al conmutar a la interfaz de Blender."""
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            request = self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        preview = _entity_preview()
        try:
            preview.enable(preview.EntityPlan(request=request, insert_before=self.insert_before.strip() or None))
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr("The preview of the entity could not be shown: {detail}",
                                      detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of the platform «{name}»", name=request.name))
        return {"FINISHED"}

    def cancel(self, context: Any) -> None:
        """Lo que Blender llama al cancelar: quita la vista previa de la entidad (RF-015-26: se quita al cancelar) y
        hace lo de siempre (:meth:`_CalculateAndCreate.cancel`: un modal en curso cierra sus pasos, la ventana de
        la confirmación cerrada sin crear descarta el cálculo abierto)."""
        _entity_preview_off()
        _CalculateAndCreate.cancel(self, context)

    def _stop(self, context: Any, *, after: bool = True) -> set[str]:
        """Esc a mitad del cálculo (y la cancelación al desactivar Geoblender): los pasos se cierran como siempre
        (``_StepsModal._stop``) y la vista previa de la entidad se quita (RF-015-26: se quita al cancelar)."""
        stopped = super()._stop(context, after=after)
        _entity_preview_off()
        return stopped

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
        _entity_preview_off()  # la entidad ya existe: ya no se prepara (RF-015-26)
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
                      "are brought up to date before the next operation that uses them, and the entity "
                      "layer with the next entity order or «Recompute the stale results»")
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
# T30 (RF-015-27): también la superficie de una entidad, con la misma orden (botón de la barra N «Entidad»).

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
    the classification of a quarry or an excavation boundary, or the surface of an entity) as a
    deliverable GeoTIFF (it is not an operation: also from a superseded version and, outside the
    project, in read-only)"""

    bl_idname = EXPORT_DESIGN_GRID
    bl_label = "Export grid to GeoTIFF…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    STEP_BUDGET_S = 0.05

    source: StringProperty(  # type: ignore[valid-type]
        name="Design grid",
        description="Uid or name of the grid of the design (empty: the active one in the view)",
        options=_FIELD)
    part: StringProperty(  # type: ignore[valid-type]
        name="Part of the entity",
        description="What to export of an entity: empty, its surface; «thickness», its thickness (the one of a retirement "
                    "or a buttress is the difference between its two surfaces)",
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
        objeto de diseño activo de la vista o, si es una **entidad** (T30; RF-015-27), su superficie (la tabla de
        la entidad que enseña la vista da la ``des_psf_`` de su versión); ``ValueError`` sin ninguna, y
        ``DesignError`` si no es una rejilla viva del diseño."""
        from ...design import export  # al usarlo: habilitar no lo carga

        ref = self.source.strip() or des_panels.wanted(context) or des_panels.entity_wanted(context)
        if not ref:
            raise ValueError(tr("Choose the design grid: select it in the view"))
        return export.stored_grid(SESSION.project, ref,
                                  version=scene_versions.active_version() or "", part=str(getattr(self, "part", "")).strip())

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
            stem = "_".join(item for item in (stored.record.name, "thickness" if stored.part else "", stored.version_code) if item)
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
                read_only=read_only_dirs(), overwrite=bool(self.overwrite), part=stored.part)
        except GisError as exc:
            interactive = self.in_steps and getattr(context, "window", None) is not None
            if exc.code == "gis.export_target_exists" and interactive:
                self.report({"WARNING"}, error_text(exc))
                _confirm_later({"source": stored.record.uid, "filepath": shown, **({"part": stored.part} if stored.part else {})},
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
            self.entity = _entity_or_selected(self.entity, context)  # del menú «Entidad ▾»: la seleccionada (T31)
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
                  "date before the next operation that uses them, and the entity layer with the next entity "
                  "order or «Recompute the stale results»")

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
            self.target = _entity_or_selected(self.target, context)  # del menú «Entidad ▾»: la seleccionada (T31)
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


# --- Lo que sigue a cambiar un parámetro de una entidad (spec 015, T43; RF-015-10, RF-015-27, RF-015-29) ----------


class GEOBLENDER_OT_des_entity_refresh(_EntitySteps, DesignCommand, _StepsModal, bpy.types.Operator):
    """Bring up to date the constraints declared by the design entities, the masks and the entity layer of the active version after one of them changed"""

    bl_idname = REFRESH_ENTITIES
    bl_label = "Update the entity constraints and layer"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    def execute(self, context: Any) -> set[str]:
        """Lo que sigue a cambiar un parámetro de una entidad (``design.entity_store.after_entity_change``, lo mismo que a
        crear o descartar una): declara las restricciones de las entidades vivas, recompila las máscaras si ya no están al
        día y pone al día la capa de entidades, por pasos con el avance y Esc; desde un guion, de una vez. La que lo
        lanza es «Cambiar parámetro…» (:func:`_after_entity_parameter`), con el cambio **ya escrito**: cerrar o fallar a
        mitad no lo deshace, deja las máscaras obsoletas con su causa y la capa marcada
        (``design.entity_store.layer_pending``) hasta la próxima orden de entidades o «Recalcular lo obsoleto»."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project, version = SESSION.project, scene_versions.active_version() or ""
        try:
            steps = entity_store.after_entity_change(project, version, budget_s=self.STEP_BUDGET_S)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError, TypeError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        started = self._run_steps(context, project, version, steps)
        return {"FINISHED"} if started == {"CANCELLED"} else started  # el cambio ya está escrito: el fallo está dicho

    def _finished(self, context: Any, result: Any) -> set[str]:
        """Lo que hizo lo que sigue (``design.entity_store.EntityChain``): la declaración, las máscaras de nuevo, lo ganado y
        perdido por restricción, lo que quedó obsoleto y, en alerta, lo que no se pudo poner al día."""
        undo_watch.record(UndoKind.OPERATION, provenance.DECLARE_CONSTRAINTS)  # Ctrl+Z no lo deshace
        shown = i18n.language()
        for notice in result.notices():
            self._report({"WARNING" if notice.severity == "warning" else "INFO"}, notice.text(shown))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        return {"FINISHED"}

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Updating the declared constraints, the masks and the entity layer… {percent} % · Esc: cancel",
                  percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Cancelled: the change is written; the declared constraints and the masks are brought up to date "
                  "before the next operation that uses them, and the entity layer with the next entity order or "
                  "«Recompute the stale results»")

    def _error_text(self, exc: GeoblenderError) -> str:
        return f"{design_error_text(exc)} " + tr("The change is written: only the declared constraints, the masks and "
                                                 "the entity layer have not been brought up to date")


# --- Traer las entidades de otra versión (spec 015, T26; HU-015-2; RF-015-18; plan 015 §5.3.3) -----------------

BRING_ENTITIES = "geoblender.des_entity_bring"


def _is_bringable(entry: Any) -> bool:
    """Si la entidad ``entry`` (``design.entities.EntityEntry``) se puede traer a otra versión (RF-015-18; spec 017, decisión de la sesión principal tras la
    T31b): **la accesibilidad, no**: no es una entidad con cadena (sin ``start`` ni ``supports``, que «Traer» re-apunta), y en otra versión se vuelve a calcular.
    Las demás (la plataforma, la pista y los cuatro tipos de la 016), sí."""
    from ...design import entities  # al usarlo: habilitar no carga las entidades

    return bool(entry.record.kind is not entities.EntityKind.ACCESS)


def _bring_entities_of(self: Any, _context: Any) -> None:
    """El ``update`` de la versión de origen de «Traer las entidades de…» (T26): pone en ``rows`` las entidades vivas de
    esa versión (no se traen las descartadas **ni la accesibilidad**: T33b), todas marcadas (``design.entities.registry``;
    solo lee). Lo que no se puede leer (una versión que no existe, un proyecto cerrado) deja la lista vacía."""
    self.rows.clear()
    project, wanted = SESSION.project, self.source.strip()
    if project is None or not wanted:
        return
    from ...design import entities  # al usarlo: habilitar no carga las entidades

    try:
        listed = entities.registry(project, wanted)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.debug("No se pudieron leer las entidades de la versión «%s»", wanted, exc_info=True)
        return
    for entry in listed:
        if entry.record.state is entities.EntityState.DISCARDED or not _is_bringable(entry):
            continue
        row = self.rows.add()
        row.name, row.selected = entry.record.code, True
        row.label = f"{entry.record.name} ({entry.record.code})"


class GEOBLENDER_OT_des_entity_bring(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Bring the entities of another version to the active one, without their results: they are left as «not calculated»"""

    bl_idname = BRING_ENTITIES
    bl_label = "Bring the entities of…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PLATFORM

    source: StringProperty(  # type: ignore[valid-type]
        name="Version", description="Code of the version the entities are brought from: any but the active one",
        options=_FIELD, update=_bring_entities_of)
    entities: StringProperty(  # type: ignore[valid-type]
        name="Entities",
        description="Codes or names of the entities to bring, separated by commas (empty: the ones chosen in the "
                    "window or, without it, every one that is not discarded)", options=_FIELD)
    versions: CollectionProperty(type=GEOBLENDER_PG_des_bring_row, options=_FIELD)  # type: ignore[valid-type]
    rows: CollectionProperty(type=GEOBLENDER_PG_des_bring_row, options=_FIELD)  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo con la versión de origen (cualquiera de las del proyecto menos la activa) y sus entidades
        vivas, todas marcadas; no escribe nada. Sin versión editable o sin otra versión, lo dice."""
        self.provenance_dialog = True
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        active = scene_versions.active_version()
        others = [item for item in scene_versions.versions() if item.uid != active]
        if not others:
            self.report({"ERROR"}, tr("The project has no other version to bring entities from"))
            return {"CANCELLED"}
        self.versions.clear()
        for item in others:
            row = self.versions.add()
            row.name, row.label = item.code, item.name()
        if self.source.strip() not in {item.code for item in others}:
            self.source = others[-1].code
        _bring_entities_of(self, context)
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Bring the entities of…"),
            confirm_text=tr("Bring"))

    def draw(self, context: Any) -> None:
        """La versión de origen y sus entidades vivas, una casilla cada una, y lo que pasará con ellas."""
        layout = self.layout
        layout.prop_search(self, "source", self, "versions", text=tr("Version"), translate=False)
        if not self.source.strip():
            return
        if len(self.rows) == 0:
            layout.label(text=tr("«{version}» has no entities to bring (the discarded ones are not brought)",
                                 version=self.source.strip()), translate=False)
            return
        layout.label(text=tr("Entities to bring:"), translate=False)
        box = layout.box()
        for row in self.rows:
            box.prop(row, "selected", text=row.label, translate=False)
        layout.label(text=tr("They are brought without their results, as «not calculated»."), translate=False)
        layout.label(text=tr("Their dependencies are detected again when you calculate them."), translate=False)

    def _wanted(self) -> list[str]:
        """Las entidades que se piden, **siempre por su código o su nombre** (nunca «todas»: incluiría la accesibilidad, que no se trae):
        las que se teclean en ``entities``; o las marcadas en la ventana; o, sin ventana ni nada tecleado, todas las vivas menos la
        accesibilidad. :class:`ValueError` si no hay ninguna marcada o si se teclea una accesibilidad (no se trae: se vuelve a calcular
        en la versión; T33b)."""
        from ...design import entities  # al usarlo: habilitar no carga las entidades

        typed = [part.strip() for part in self.entities.split(",") if part.strip()]
        rows = len(self.rows) > 0
        if rows and not typed:
            chosen = [row.name for row in self.rows if row.selected]
            if not chosen:
                raise ValueError(tr("Choose at least one entity to bring"))
            return chosen
        try:
            listed = entities.registry(SESSION.project, self.source.strip())
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):  # una versión que no se puede leer: la rechaza el dominio con sus palabras
            LOGGER.debug("No se pudieron leer las entidades de la versión «%s»", self.source, exc_info=True)
            return typed
        if typed:
            for ref in typed:
                found = listed.get(ref)
                if found is not None and not _is_bringable(found):
                    raise ValueError(tr("«{name}» is an accessibility, not an entity with a chain: it is not brought to another version; "
                                        "calculate it again in the active version", name=found.record.name))
            return typed
        return [entry.record.code for entry in listed if entry.record.state is not entities.EntityState.DISCARDED and _is_bringable(entry)]

    def execute(self, context: Any) -> set[str]:
        """Trae a la versión activa las entidades pedidas de la de origen (``design.entity_store.bring_entities``):
        sus definiciones, sin resultados ni cifras, «sin calcular», en una sola transacción; dice lo que hizo y lo que
        quedó sin valor. Los rechazos (la misma versión, una descartada, sin versión de origen…) son de ``design``: nada
        se escribe."""
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
            if not self.source.strip():
                raise ValueError(tr("Choose the version to bring the entities from"))
            found = entity_store.bring_entities(project, self.source.strip(), version, codes=self._wanted())
        except (GeoblenderError, sqlite3.Error, OSError, ValueError, TypeError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        if found.entities:
            undo_watch.record(UndoKind.OPERATION, "des.entity_bring")  # Ctrl+Z no lo deshace
        shown = i18n.language()
        for notice in found.notices:
            self.report({"WARNING" if notice.severity == "warning" else "INFO"}, notice.text(shown))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        return {"FINISHED"}


# --- La vista previa de una entidad (spec 015, T29; HU-015-3; RF-015-26; plan 015 §5.3.3) -----------------------


def _selected_entity(context: Any) -> tuple[str, str]:
    """El código y la versión (uid) de la entidad del objeto ``DESIGN_ENTITY`` activo de la Vista 3D
    (``des_panels.entity_wanted``); ``("", "")`` si no hay ninguno. Solo lee el proyecto."""
    uid = des_panels.entity_wanted(context)
    project = SESSION.project
    if not uid or project is None:
        return "", ""
    with project.read() as conn:
        return des_panels.entity_of(project, conn, uid)


def _entity_or_selected(given: str, context: Any) -> str:
    """La entidad a la que se refiere una orden del menú «Entidad ▾» (T31; RF-015-28, D-14): la que se tecleó (``given``: su
    código o su nombre) o, sin ella, la del objeto de entidad seleccionado en la vista (``_selected_entity``); ``""`` si no hay
    ninguna. :class:`ValueError` si la seleccionada es de otra versión que la activa."""
    typed = given.strip()
    if typed:
        return typed
    code, owner = _selected_entity(context)
    if code and not owner:  # el objeto de una detección **del proyecto** (D-15): su código se repite en cada versión (spec 016, T35)
        raise ValueError(tr("The selected detection belongs to the project, not to a version: this command is about the entities of the "
                            "active version"))
    if code and owner != scene_versions.active_version():
        raise ValueError(tr("The selected entity is not of the active version: make its version the active one first"))
    return code


class GEOBLENDER_OT_des_entity_preview(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Show, before calculating, the footprint of a platform, its axis with its sense, the levels at its ends, what rests on it and the constraints it will declare; the marks of a detection of stockpiles; the crown zone of a buttress; the origin, the destination and the corridor of a road, or its axis with its gradients"""

    bl_idname = ENTITY_PREVIEW
    bl_label = "Preview of the entity"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PLATFORM

    entity: StringProperty(  # type: ignore[valid-type]
        name="Entity",
        description="Code or name of the design entity to preview (empty: the one of the object selected in the "
                    "3D view)", options=_FIELD)

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Con la vista previa activa, se puede quitar siempre; si no, lo de las órdenes de Diseño (RF-015-28): con
        un proyecto en escritura y la versión activa editable o ninguna."""
        return True if _entity_preview_on() else _write_poll(cls)

    @staticmethod
    def _plan(project: Any, active: Any, entry: Any) -> Any:
        """Lo que se previsualiza de la entidad ``entry`` de la versión ``active`` (spec 016, T35; RF-016-23): de una **plataforma**, la de
        la versión con sus parámetros vigentes (``EntityPlan(code=…)``); de una **detección de acopios**, sus marcas, y de un **contrafuerte**,
        su zona de coronación, **reconstruidas** de los ajustes de su operación vigente y de los parámetros vigentes de la entidad (como lo
        que recalcularía: ``design.provenance.stockpile_request`` y ``buttress_request``). Una retirada y un cuerpo apoyado no tienen vista
        previa (RF-016-23 solo pide las marcas y la zona de coronación). :class:`ValueError` si no la tiene o la entidad no está calculada."""
        from ...design import entities, entity_store  # al usarlo: habilitar no carga el cálculo
        from ...design.preview import RoadAsk

        preview = _entity_preview()
        record = entry.record
        if record.kind == entities.EntityKind.PLATFORM:
            return preview.EntityPlan(code=record.code)
        if record.kind == entities.EntityKind.ROAD:  # su eje guardado, con la rasante por tramos y lo que se le apoya (spec 017, T28; RF-017-26); sin calcular, lo dice la vista previa
            return preview.EntityPlan(road=RoadAsk(code=record.code))
        label = entities.entity_type(record.kind).params.label
        if record.kind not in (entities.EntityKind.STOCKPILE, entities.EntityKind.BUTTRESS):
            raise ValueError(tr("«{name}» ({kind}) has no preview: only a platform, a detection of stockpiles (its marks), a buttress "
                                "(its crown zone) and a road (its axis) have one", name=record.name, kind=label))
        if entry.operation_uid is None:
            raise ValueError(tr("«{name}» ({kind}) is not calculated: there is nothing to preview", name=record.name, kind=label))
        with project.read() as conn:
            row = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?", (entry.operation_uid,)).fetchone()
        settings = json.loads(row[0]) if row is not None and row[0] else {}
        values = entity_store.entity_parameters(project, record.code, version=active)
        if record.kind == entities.EntityKind.STOCKPILE:
            return preview.EntityPlan(stockpile=provenance.stockpile_request(settings, values))
        return preview.EntityPlan(buttress=provenance.buttress_request(settings, values))

    def execute(self, context: Any) -> set[str]:
        """Con la vista previa de una entidad activa, la quita. Si no, activa la de la entidad pedida (``entity``) o,
        sin ella, la del objeto de entidad seleccionado, **con sus parámetros vigentes** (lo que recalcularía), sin
        escribir ni calcular nada (``bl.draw.entity``). Sin versión editable, sin entidad o con una de otra versión,
        lo dice y no activa nada."""
        if _entity_preview_on():
            _entity_preview_off()
            self.report({"INFO"}, tr("Preview of the entity hidden"))
            return {"FINISHED"}
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        active = scene_versions.active()
        try:
            code, owner = self.entity.strip(), ""
            if not code:
                code, owner = _selected_entity(context)
                if code and not owner:  # la detección **del proyecto** (D-15): su código se repite en cada versión (spec 016, T35)
                    raise ValueError(tr("The selected detection belongs to the project, not to a version: this command is about the "
                                        "entities of the active version"))
            if not code:
                self.report({"ERROR"}, tr("Choose the entity to preview: select its object in the 3D view or "
                                          "give its code"))
                return {"CANCELLED"}
            if owner and owner != active.uid:
                self.report({"ERROR"}, tr("The selected entity is not of the active version: make its version "
                                          "the active one first"))
                return {"CANCELLED"}
            from ...design import entities  # al usarlo: habilitar no carga el cálculo

            found = entities.registry(SESSION.project, active.uid).get(code)
            if found is None:
                self.report({"ERROR"}, tr("«{entity}» is not an entity of {version}", entity=code,
                                          version=active.code))
                return {"CANCELLED"}
            plan = self._plan(SESSION.project, active, found)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        preview = _entity_preview()
        try:
            preview.enable(plan)
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr("The preview of the entity could not be shown: {detail}",
                                      detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of the entity «{name}»", name=found.record.name))
        return {"FINISHED"}


# --- El menú «Entidad ▾»: lo que se apoya en la entidad (spec 015, T31; HU-015-2; RF-015-15, RF-015-28; D-11, D-14) ----------

DEPENDENTS = "geoblender.des_entity_dependents"
INSERT_ENTITY = "geoblender.des_entity_insert"


@dataclass(frozen=True, slots=True)
class _Dependents:
    """Lo que enseña la ventana de «Lo que se apoya en ella»: el ``name`` y el ``code`` de la entidad, **la lista única** de
    lo que se apoya en ella o parte de su superficie (``on_it``: ``design.entities.dependents``) y en qué se apoya ella
    (``rests_on``: ``design.entities.dependencies_of``)."""

    name: str
    code: str
    on_it: tuple[Any, ...]
    rests_on: tuple[Any, ...]


class GEOBLENDER_OT_des_entity_dependents(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Show the single list of what rests on the entity or starts from its surface, with the volume that rests on it, and what the entity rests on"""

    bl_idname = DEPENDENTS
    bl_label = "What rests on it"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PLATFORM

    entity: StringProperty(  # type: ignore[valid-type]
        name="Entity", description="Code or name of the design entity (empty: the one of the object selected in the 3D "
                                   "view)", options=_FIELD)

    _listed = None
    """Lo que enseña la ventana (:class:`_Dependents`), leído al abrirla."""

    def _read(self, context: Any) -> _Dependents:
        """La entidad pedida (o la seleccionada en la vista) con lo que se apoya en ella y en qué se apoya, leído del proyecto
        en **una** instantánea y sin escribir nada. :class:`ValueError` si no hay entidad o no es de la versión activa."""
        from ...design import entities  # al usarlo: habilitar no carga las entidades

        code = _entity_or_selected(self.entity, context)
        if not code:
            raise ValueError(tr("Choose the entity: select its object in the 3D view or give its code"))
        project, version = SESSION.project, scene_versions.active()
        if project is None or version is None:
            raise ValueError(tr("There is no active version: the entities are those of a version"))
        with project.read() as conn:
            conn.execute("BEGIN")
            try:
                listed = entities.registry(project, version.uid, conn=conn)
                entry = listed.get(code)
                if entry is None:
                    raise ValueError(tr("«{entity}» is not an entity of {version}", entity=code, version=version.code))
                found = entry.record.code
                return _Dependents(
                    entry.record.name, found, entities.dependents(project, version.uid, found, conn=conn),
                    entities.dependencies_of(project, version.uid, found, conn=conn, listed=listed))
            finally:
                conn.execute("ROLLBACK")

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre la ventana con la lista de lo que se apoya en la entidad (y en qué se apoya); no escribe nada. Sin versión
        editable, sin entidad o con una que no es de la versión activa, lo dice."""
        self.provenance_dialog = True
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            self._listed = self._read(context)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_popup(self, width=DIALOG_WIDTH)

    def draw(self, context: Any) -> None:
        """La entidad, **la lista única** de lo que se apoya en ella o parte de su superficie (nombre, tipo y m³, o «superficie
        de partida»; en alerta lo que no está al día) y, debajo, en qué se apoya ella."""
        found = self._listed
        if found is None:
            return
        layout = self.layout
        layout.label(text=tr("Design entity «{name}» ({code})", name=found.name, code=found.code), translate=False)
        for heading, rows, nothing in ((tr("What rests on it"), found.on_it, tr("Nothing rests on it")),
                                       (tr("Rests on"), found.rests_on, tr("It rests on nothing"))):
            layout.label(text=heading, translate=False)
            box = layout.box()
            for text, alert in des_panels.dependent_texts(rows):
                row = box.row()
                row.alert = alert
                row.label(text=text, icon="DOT", translate=False)
            if not rows:
                box.label(text=nothing, translate=False)

    def execute(self, context: Any) -> set[str]:
        """Desde un guion: informa la lista, línea a línea (la entidad, lo que se apoya en ella y en qué se apoya), sin
        escribir nada."""
        try:
            found = self._read(context)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Design entity «{name}» ({code})", name=found.name, code=found.code))
        for heading, rows, nothing in ((tr("What rests on it"), found.on_it, tr("Nothing rests on it")),
                                       (tr("Rests on"), found.rests_on, tr("It rests on nothing"))):
            self.report({"INFO"}, heading)
            for text, _alert in des_panels.dependent_texts(rows):
                self.report({"INFO"}, text)
            if not rows:
                self.report({"INFO"}, nothing)
        return {"FINISHED"}


# --- Insertar antes o después de otra entidad (spec 015, T31; HU-015-2; RF-015-05, RF-015-04; D-2, D-14) --------------------

PLACEMENT_ITEMS = [
    ("AFTER", "After", "The new platform starts from the surface of the entity and the one that followed it starts from "
                       "the new one"),
    ("BEFORE", "Before", "The new platform starts from the surface the entity starts from and the entity starts from "
                         "the new one")]
"""Dónde se inserta la nueva respecto de la entidad de referencia (``design.entities.insertion_point``)."""


class GEOBLENDER_OT_des_entity_insert(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Insert a new platform before or after another entity of its chain: the one that follows starts from the new one and is left out of date with what follows it"""

    bl_idname = INSERT_ENTITY
    bl_label = "Insert before or after…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PLATFORM

    reference: StringProperty(  # type: ignore[valid-type]
        name="Entity", description="Name or code of the entity the new platform is inserted next to (empty: the one of "
                                   "the object selected in the 3D view)", options=_FIELD)
    placement: EnumProperty(  # type: ignore[valid-type]
        name="Position", description="Insert the new platform after or before that entity", items=PLACEMENT_ITEMS,
        default="AFTER", options=_FIELD)
    references: CollectionProperty(type=GEOBLENDER_PG_des_bring_row, options=_FIELD)  # type: ignore[valid-type]

    _records = ()
    """Las entidades de la versión activa como las leyó ``invoke`` (``design.entities.EntityRecord``): lo que dibuja el
    diálogo no lee el proyecto."""

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo con las entidades vivas de la versión activa (por su nombre) y propone la del objeto seleccionado en la
        vista o, sin ella, la primera; no escribe nada. Sin versión editable o sin entidades, lo dice."""
        from ...design import entities  # al usarlo: habilitar no carga las entidades

        self.provenance_dialog = True
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            wanted = _entity_or_selected(self.reference, context)
            self._records = entities.registry(SESSION.project, scene_versions.active_version() or "").records
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        live = [item for item in self._records
                if item.state is not entities.EntityState.DISCARDED and entities.entity_type(item.kind).chained]  # una detección no tiene cadena
        if not live:
            self.report({"ERROR"}, tr("The active version has no entities to insert next to: create a platform first"))
            return {"CANCELLED"}
        self.references.clear()
        for item in live:
            row = self.references.add()
            row.name, row.label = item.name, f"{item.name} ({item.code})"
        found = entities.find_entity(live, wanted) if wanted else None
        self.reference = (found or live[0]).name
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Insert before or after…"),
            confirm_text=tr("Continue"))

    def draw(self, context: Any) -> None:
        """La entidad de referencia (de la lista de las vivas) y antes o después de ella; y, según lo elegido, de qué superficie
        parte la nueva y qué pasará con la sucesora (pasa a partir de la nueva y, con lo que la sigue, queda obsoleta) o que se
        añade al final de su cadena."""
        from ...design import entities  # al usarlo: habilitar no carga las entidades

        layout = self.layout
        layout.prop_search(self, "reference", self, "references", text=tr("Entity"), translate=False)
        layout.prop(self, "placement", expand=True)
        wanted = self.reference.strip()
        if not wanted:
            return
        try:
            found = entities.insertion_point(self._records, wanted, before=self.placement == "BEFORE")
        except (GeoblenderError, ValueError) as exc:
            layout.label(text=tr("It cannot be inserted: {reason}", reason=design_error_text(exc)), icon="ERROR",
                         translate=False)
            return
        name = found.reference.name
        layout.label(text=tr("The new platform starts from the same surface as «{entity}»", entity=name) if found.before
                     else tr("The new platform starts from the surface of «{entity}»", entity=name), translate=False)
        layout.label(text=tr("«{entity}» will start from the new platform and, with what follows it, will be out of "
                             "date until it is recomputed", entity=found.successor.name) if found.successor is not None
                     else tr("Nothing starts from the surface of «{entity}»: the new platform is added at the end of "
                             "its chain", entity=name), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Abre la creación de la plataforma (**«Plataforma…»**, :data:`CREATE_PLATFORM`) con la partida de la nueva
        (``design.entities.insertion_point``: la superficie que deja la entidad de referencia o la de la que parte) y, si la
        hay, la entidad que pasará a partir de ella (``insert_before``); no escribe nada: al crear, la sucesora pasa a partir
        de la nueva y queda obsoleta con las que la siguen (``design.entity_store.apply_insertion``). Sin entidad, con una que no
        es de la versión o descartada, o con una partida que la plataforma aún no puede tener (una entidad sin calcular no tiene
        superficie), lo dice y no abre nada."""
        from ...design import entities  # al usarlo: habilitar no carga las entidades

        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = SESSION.project
        try:
            wanted = _entity_or_selected(self.reference, context)
            if not wanted:
                raise ValueError(tr("Choose the entity the new platform is inserted next to"))
            found = entities.insertion_point(
                entities.registry(project, scene_versions.active_version() or "").records, wanted,
                before=self.placement == "BEFORE")
            des_panels.refresh_choices(project)
            des_panels.refresh_platform_choices(project)
            if found.start not in {item[0] for item in des_panels.platform_start_items(None, None)}:
                raise ValueError(tr("«{start}» cannot be the start surface yet: a platform that is not calculated has "
                                    "no surface", start=found.start))
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        values: dict[str, Any] = {"start": found.start}
        if found.successor is not None:
            values["insert_before"] = found.successor.code
        _invoke_later(CREATE_PLATFORM, getattr(context, "window", None) or _first_window(), **values)
        return {"FINISHED"}


# --- Calcular una entidad traída o heredada «sin calcular» (spec 015, T41; HU-015-2; RF-015-18; CE-015-01; hallazgo C-12) ------

CALCULATE_ENTITY = "geoblender.des_entity_calculate"


def _calculable() -> tuple[Any, ...]:
    """Los tipos de entidad que «Calcular…» calcula con sus parámetros guardados (spec 017, T33c): **la plataforma** y **la pista**, las dos órdenes de entidad que
    aceptan ``code``; ni la accesibilidad (no es una entidad: no se trae) ni los cuatro de la 016 (ninguna de sus órdenes lo tiene)."""
    from ...design import entities  # al usarlo: habilitar no carga las entidades

    return (entities.EntityKind.PLATFORM, entities.EntityKind.ROAD)


class GEOBLENDER_OT_des_entity_calculate(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Calculate a design entity that has no result yet, brought from another version or inherited: with the parameters it has in the version, and what rests on it is detected again"""

    bl_idname = CALCULATE_ENTITY
    bl_label = "Calculate…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.PLATFORM

    entity: StringProperty(  # type: ignore[valid-type]
        name="Entity",
        description="Code or name of the design entity to calculate: one brought from another version or inherited, "
                    "without a result (empty: the one chosen in the window)", options=_FIELD)
    candidates: CollectionProperty(type=GEOBLENDER_PG_des_bring_row, options=_FIELD)  # type: ignore[valid-type]

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre la ventana con las plataformas y las pistas **sin calcular** de la versión activa (por su nombre: una sin
        calcular no tiene objeto en la vista, así que no se elige seleccionándolo) y propone la dada o la primera; no
        escribe nada. Sin versión editable o sin ninguna entidad sin calcular de esos dos tipos, lo dice."""
        from ...design import entities  # al usarlo: habilitar no carga las entidades

        self.provenance_dialog = True
        refusal = self._version_refusal()
        if refusal is not None:
            if scene_versions.active_version() is not None:
                self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            listed = entities.registry(SESSION.project, scene_versions.active_version() or "")
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        # Las plataformas y las pistas (T33c): «Plataforma…» y «Pista…» tienen `code`. Ninguna orden de la 016 lo tiene, así que lo traído de
        # sus cuatro tipos (acopio, retirada, contrafuerte y cuerpo) queda sin calcular y ninguna orden lo calcula (S-5; «Para Samuel», 11 de
        # `tasks.md` de la 016); la accesibilidad no es una entidad y no se trae: se vuelve a calcular con su orden.
        waiting = [entry.record for entry in listed if entry.record.state is entities.EntityState.UNCALCULATED
                   and entry.record.kind in _calculable()]
        if not waiting:
            self.report({"ERROR"}, tr("The active version has no entity without a result: the ones brought from another "
                                      "version or inherited from the version it starts from are left without one"))
            return {"CANCELLED"}
        self.candidates.clear()
        for record in waiting:
            row = self.candidates.add()
            row.name, row.label = record.name, f"{record.name} ({record.code})"
        wanted = self.entity.strip()
        found = entities.find_entity(waiting, wanted) if wanted else None
        self.entity = (found or waiting[0]).name
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Calculate…"), confirm_text=tr("Calculate"))

    def draw(self, context: Any) -> None:
        """La entidad (de la lista de las que no tienen resultado) y lo que pasará: se calcula con los parámetros que ya
        tiene en la versión y Calcular no registra nada (solo «Crear» lo hace, y entonces se detecta de nuevo lo que se
        apoya en ella)."""
        layout = self.layout
        layout.prop_search(self, "entity", self, "candidates", text=tr("Entity"), translate=False)
        layout.label(text=tr("It is calculated with the parameters it has in the version; nothing is chosen again."),
                     translate=False)
        layout.label(text=tr("Calculating shows its summary and registers nothing: only «Create» does, and then what "
                             "rests on it is detected again."), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Abre el cálculo de la entidad elegida (**«Plataforma…»**, :data:`CREATE_PLATFORM`, o **«Pista…»**,
        :data:`CREATE_ROAD`, con su ``code``): sin diálogo, calcula con los parámetros que la entidad ya tiene en la
        versión, enseña el resumen y pide confirmar; no escribe nada (al crear, la entidad conserva su código y sus
        parámetros y la dependencia «se apoya en» se detecta de nuevo). Sin entidad, con una que no es de la versión, que
        ya tiene resultado o está descartada, o sin su partida (``design.entity_store.entity_request`` y
        ``design.road_store.entity_road_request``), lo dice y no abre nada; con otro tipo (la accesibilidad, un acopio…),
        dice que solo una plataforma o una pista se calculan así."""
        from ...design import entities  # al usarlo: habilitar no carga las entidades

        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project, active = SESSION.project, scene_versions.active()
        try:
            wanted = self.entity.strip()
            if not wanted:
                raise ValueError(tr("Choose the entity to calculate"))
            found = entities.registry(project, active.uid).get(wanted)
            if found is None:
                raise ValueError(tr("«{entity}» is not an entity of {version}", entity=wanted, version=active.code))
            if found.record.kind not in _calculable():
                raise ValueError(tr("«{name}» ({kind}) is not calculated from here: it is made again with its own command; only a platform or a road "
                                    "are calculated with their saved parameters", name=found.record.name,
                                    kind=entities.entity_type(found.record.kind).params.label))
            if found.record.kind == entities.EntityKind.ROAD:  # lo que rechazaría el cálculo, antes de abrir nada
                _road_entity_request(project, active.uid, found.record.code)
            else:
                _entity_request(project, active.uid, found.record.code)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        opens = CREATE_ROAD if found.record.kind == entities.EntityKind.ROAD else CREATE_PLATFORM
        _invoke_later(opens, getattr(context, "window", None) or _first_window(), code=found.record.code)
        return {"FINISHED"}


# --- Retirar un acopio… (spec 016, T20 (b); HU-016-2; RF-016-11 a RF-016-15, RF-015-02, RF-015-03, RF-015-28, RF-015-29;
#     RNF-016-05; plan 016 §5.3.3 y §5.5; comprobación manual M1) -------------------------------------------------

REMOVE_STOCKPILE = provenance.REMOVAL_COMMAND
_QUIET: list[bool] = []
"""Si el diálogo de «Retirar un acopio…» se está rellenando por la propuesta (la lista de lo que se apoya se lee una sola vez al final)."""


def _refresh_resting(self: Any, _context: Any) -> None:
    """El ``update`` del acopio y de la partida de «Retirar un acopio…» (T20 (b); RF-016-14, A7): lee **antes de calcular y sin escribir
    nada** lo que se apoya en el acopio elegido sobre la partida elegida (``design.supported_store.resting_preview``: **una sola lista**,
    con quién lo puso y sus m³) y lo deja en el diálogo (``des_panels.show_resting``); lo que no se puede leer (la detección obsoleta, una
    partida que no existe) sale en ámbar, con el texto del rechazo que daría «Calcular». Sin acopio o sin partida, nada."""
    if _QUIET:
        return
    project = SESSION.project
    version = scene_versions.active_version() or ""
    stockpile, start = self.stockpile, self.start
    if (project is None or not version or not des_panels.has_removal_stockpiles()
            or stockpile in ("", des_panels.NO_ZONE) or start in ("", des_panels.NO_ZONE)):
        des_panels.show_resting(())
        return
    from ...design import supported_store  # al usarlo: habilitar no carga el cálculo

    try:
        rows = supported_store.resting_preview(project, version, stockpile, start)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
        LOGGER.info("No se pudo leer lo que se apoya en «%s» sobre «%s»", stockpile, start, exc_info=True)
        des_panels.show_resting([(design_error_text(exc), True)])
        return
    if rows:
        shown = i18n.language()
        des_panels.show_resting([*((row.text(shown), True) for row in rows),
                                 (tr("The stockpile is not removed without your express confirmation: the button that creates the "
                                     "removal confirms it"), False)])
    else:
        des_panels.show_resting([(tr("Nothing rests on the stockpile"), False)])


class _ChainsEntityLayer:
    """Lo que sigue a crear una entidad de la 016 que no es una plataforma ni un contrafuerte (la retirada y el cuerpo apoyado, T41; RF-015-10,
    RF-015-27, RF-016-24; plan 016 §5.3.2 y §5.4 A9): tras el commit de «Crear», **encadena** ``design.entity_store.after_entity_change`` por
    pasos con el avance y Esc, como «Plataforma…» y «Contrafuerte…»: repite la declaración de las restricciones de las entidades de la
    versión (la retirada no protege y el cuerpo no declara: no cambia), recompila las máscaras si ya no están al día y pone al día **la capa de
    entidades** (``des_enl_<vNN>``, como operación aparte: T34), que así tiene la fila de la entidad sin otra orden. La entidad **ya está
    creada** (cada etapa es una operación y una transacción propias): cerrar o fallar a mitad deja las máscaras obsoletas con su causa y la
    capa se pone al día con la orden de entidades siguiente o «Recalcular lo obsoleto». Se pone **antes** de :class:`_CalculateAndCreate`;
    cada orden da su ``_create`` (que llama a :meth:`_update_declared` si crea) y los textos de su ``_status_text``, ``_cancelled_text`` y
    ``_error_text`` para :attr:`_chain`."""

    _chain = False
    """Si los pasos que corren son los de lo que sigue a crear la entidad (y no los de calcularla)."""

    def _update_declared(self, context: Any, opened: Calculation) -> set[str]:
        """Tras crear la entidad, **pone al día** lo que sigue a toda orden de entidades (``design.entity_store.after_entity_change``), por
        pasos con el avance y Esc: la entidad **ya está creada**, así que cerrar o fallar a mitad no la deshace (``{"FINISHED"}``: el fallo ya
        está dicho)."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        project = SESSION.project
        self._chain = True
        steps = entity_store.after_entity_change(project, opened.version, budget_s=self.STEP_BUDGET_S)  # type: ignore[attr-defined]
        started = self._run_steps(context, project, opened.name, steps)  # type: ignore[attr-defined]
        return {"FINISHED"} if started == {"CANCELLED"} else started  # ya creada: el fallo está dicho

    def _finished(self, context: Any, opened: Any) -> set[str]:
        """Con los pasos de lo que sigue a crearla, dice lo que hizo (:meth:`_report_chain`); si no, como las demás órdenes."""
        if self._chain:
            self._chain = False
            self._report_chain(opened)
            return {"FINISHED"}
        return _CalculateAndCreate._finished(self, context, opened)  # type: ignore[arg-type]

    def _report_chain(self, chain: Any) -> None:
        """Lo que hizo ``chain`` (``design.entity_store.EntityChain``), en el informe y en el registro: la declaración, las máscaras
        recompiladas, por restricción el polígono y la zona ganados y perdidos (m²), lo que quedó obsoleto y, en alerta, lo que no se pudo
        hacer (RF-012-06)."""
        shown = i18n.language()
        for notice in chain.notices():
            self._report({"WARNING" if notice.severity == "warning" else "INFO"}, notice.text(shown))  # type: ignore[attr-defined]
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()


class _CreatesInSteps:
    """«Crear» **por pasos** desde la interfaz, de las órdenes de la 017 cuyo cálculo sabe crearse así (la pista y la accesibilidad: ``Calculation.create_steps``; spec 017, T32; RF-017-30, RF-015-29,
    RNF-017-06; el patrón de ``GEOBLENDER_OT_des_detect_stockpiles._creation_steps``, T44 de la 016): escribir la superficie entera de una pista o la rejilla de lo alcanzable de una accesibilidad de una
    vez era una sola llamada larga del hilo de Blender. Con ventana (:attr:`in_steps`), :meth:`_create_in_steps` empieza el modal de pasos —cada evento, una llamada de ≤ 0,2 s— con la transacción final
    como último paso, y **en cuanto lo guardado llega, lo que sigue en el mismo modal** (:meth:`_registered`, :meth:`_after_registered` y los pasos de ``entity_store.after_entity_change``: la
    declaración, las máscaras, la capa de entidades y la de ejes de pistas). Esc entre los pasos de crear, un fallo o cerrar el proyecto no dejan nada (``create_steps`` descarta el cálculo y borra sus
    temporales); Esc **ya creada** (en lo que sigue) deja la entidad creada (``_ChainsEntityLayer``). Desde un guion (sin ventana), de una vez, como las demás órdenes: el resultado es el mismo, bit a bit.
    Se pone **antes** de :class:`_ChainsEntityLayer`; cada orden da su ``_create`` (que llama a :meth:`_create_in_steps`) y los textos de crear en su ``_status_text``, ``_cancelled_text`` y
    :attr:`_creating`."""

    _creating = False
    """Si los pasos que corren son los de crear el cálculo (y no los de calcularlo ni los de lo que sigue a crearlo)."""

    def _create_in_steps(self, context: Any, opened: Calculation | None) -> set[str] | None:
        """Empieza el modal de pasos de crear ``opened`` si hay ventana (la interfaz) y devuelve ``{"RUNNING_MODAL"}``; desde un guion, o sin cálculo abierto, ``None``: crea de una vez."""
        if opened is None or not self.in_steps or getattr(context, "window", None) is None:  # type: ignore[attr-defined]
            return None
        project = SESSION.project
        self._project, self._name, self._creating = project, opened.name, True  # type: ignore[attr-defined]
        self._start(context, self._creation_steps(project, opened))  # type: ignore[attr-defined]
        return {"RUNNING_MODAL"}

    def _after_registered(self) -> None:
        """Lo que hace la orden en cuanto lo guardado llega, además de :meth:`_CalculateAndCreate._registered` (por defecto, nada)."""

    def _creation_steps(self, project: Any, opened: Calculation) -> Iterator[Progress]:
        """Los pasos de «Crear» ``opened`` en el modal (T32): los de ``Calculation.create_steps`` (cada tabla y cada rejilla, montada y escrita en su temporal por pasos; la transacción final, el
        último) y, en cuanto lo guardado llega, **lo que sigue a crearla en el mismo modal**: lo registrado, lo que dice :meth:`_after_registered` y los pasos de
        ``entity_store.after_entity_change``. Cerrar los pasos antes (Esc) o un fallo no dejan nada: ``create_steps`` descarta el cálculo y borra sus temporales."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        created = None
        creating = opened.create_steps(budget_s=self.STEP_BUDGET_S)  # type: ignore[attr-defined]
        try:
            for step in creating:
                if step.result is not None:
                    created = step
                    break
                yield step
        finally:
            creating.close()
        assert created is not None  # los pasos acaban siempre con lo guardado
        self._registered(opened)  # type: ignore[attr-defined]
        self._after_registered()
        self._creating, self._chain = False, True  # type: ignore[attr-defined]
        yield from entity_store.after_entity_change(project, opened.version, budget_s=self.STEP_BUDGET_S)  # type: ignore[attr-defined]

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        """Como las demás órdenes; al **crearlo**, con el proyecto cerrado se para sin dejar nada y lo dice con sus palabras (no se calculaba: se guardaba)."""
        if self._creating and project_session.current() is not getattr(self, "_project", None):
            return self._fail(context, tr("The project was closed while «{name}» was being saved: nothing has been left half-done",  # type: ignore[attr-defined]
                                          name=getattr(self, "_name", "")))
        return _CalculateAndCreate._result(self, context, step)  # type: ignore[arg-type]

    def _after_stop(self, context: Any) -> None:
        """Tras cancelar (Esc) o fallar **al crearlo**: ``create_steps`` ya descartó el cálculo y borró sus temporales; aquí se suelta (ya no está abierto) y se vacía su resumen. Tras cancelar lo
        que sigue a crearlo, nada: la entidad está creada."""
        if self._creating:
            self._creating = False
            discard_calculation()
            des_panels.show_summary(None)


class GEOBLENDER_OT_des_remove_stockpile(_ChainsEntityLayer, _CalculateAndCreate, DesignCommandAware, ProvenanceAwareOperator,
                                         _StepsModal, bpy.types.Operator):
    """Remove a stockpile detected in the active version: its footprint goes down to its base, joined with the ground by a transition, and what rests on it is listed before calculating"""

    bl_idname = REMOVE_STOCKPILE
    bl_label = "Remove a stockpile…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.STOCKPILE_REMOVAL
    COMMAND = REMOVE_STOCKPILE

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the removal, unique in the active version", options=_FIELD)
    stockpile: EnumProperty(  # type: ignore[valid-type]
        name="Stockpile",
        description="Stockpile to remove: one of the detections of the active version or of the project; one whose detection is "
                    "out of date is refused, saying what changed",
        items=des_panels.removal_stockpile_items, options=_FIELD, update=_refresh_resting)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the stockpile is removed from: the ground, a design surface or the surface of another entity (by "
                    "default, the last of the chain)",
        items=des_panels.platform_start_items, options=_FIELD, update=_refresh_resting)
    transition_angle: StringProperty(  # type: ignore[valid-type]
        name="Transition angle (°)",
        description="Angle of the slope that joins the removed footprint with the rest of the surface, in degrees; it has no default "
                    "value: you choose it", options=_FIELD)
    mesh_factor: StringProperty(  # type: ignore[valid-type]
        name="Mesh factor", description="Factor of the mesh of the transition, or of the edge of the platform (empty: the default value)",
        options=_FIELD)
    metric: EnumProperty(  # type: ignore[valid-type]
        name="Metric",
        description="How the distance to the footprint is measured in the transition or in the edge of the platform: the 5×5 chamfer "
                    "(fast, with the scale of the grid) or the exact Euclidean distance", items=METRIC_ITEMS, default="EXACT",
        options=_FIELD)
    wall_reason: StringProperty(  # type: ignore[valid-type]
        name="Reason for the wall",
        description="Why you accept the wall that removing the stockpile may leave at the edge of what is removed: it is needed "
                    "only if the wall passes the height and the angle that ask for a reason, and it is recorded with the removal",
        options=_FIELD)
    # «Como plataforma» (T41; RF-016-16, A9): en lugar de la transición, la huella entera queda en el plano de su base y con ella se crea una
    # plataforma de la 015 (``PlatformRequest.of_stockpile``), con su borde: el ángulo y el alcance (los de la plataforma; sin valor por
    # defecto: D-7 y D-20 de la 015). El factor de malla y la métrica valen para la transición o para el borde.
    as_platform: BoolProperty(  # type: ignore[valid-type]
        name="As a platform",
        description="Remove the stockpile as a platform: its whole footprint is left in the plane of its base and a platform of the "
                    "chain is made with it, with its edge, its checks and its constraints; the transition angle and the wall do not "
                    "apply", default=False, options=_FIELD)
    edge_angle: StringProperty(  # type: ignore[valid-type]
        name="Edge angle (°)",
        description="Angle of the slope that joins the platform with the ground, in degrees", options=_FIELD)
    reach: StringProperty(  # type: ignore[valid-type]
        name="Reach of the edge (m)",
        description="Farthest distance from the footprint the edge can reach, in metres", options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con el avance y Esc: los pone invoke;
    # desde un guion, sin ellos, de una vez. Las confirmaciones expresas de lo que se apoya y de la pared (RF-016-14, RF-016-15): las pone
    # el botón de su ventana, que las dice; desde un guion, quien la lanza.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    confirm_resting: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    confirm_wall: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué. Con ``confirm``, el diálogo de crear
        el cálculo abierto. Si no, las listas leídas de nuevo (los acopios de las detecciones, las superficies y las entidades de la
        cadena), la propuesta (un nombre, el primer acopio al día y la partida: la última de la cadena o el terreno), **lo que se apoya
        en el acopio elegido** (:func:`_refresh_resting`) y el diálogo del cálculo: Intro calcula. Sin ninguna detección de acopios,
        lo dice."""
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
            des_panels.refresh_removal_choices(project)
            if not des_panels.has_removal_stockpiles():
                self.report({"ERROR"}, tr("There is no detection of stockpiles in the project or in the active version: detect the "
                                          "stockpiles first"))
                return {"CANCELLED"}
            _QUIET.append(True)
            try:
                self._propose(context, project)
            finally:
                _QUIET.pop()
            _refresh_resting(self, context)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label), confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 016 §5.3.3): **el primer acopio cuya detección está al día**
        (o el primero), un nombre que no repite el de ninguna entidad de la versión («Retirada de «Acopio 1»») y la **partida: la última
        de la cadena** (``des_panels.platform_default_start``) o, sin entidades calculadas, el terreno (``surface_proposal.ground_item``,
        con lo seleccionado en la vista). El ángulo de transición no se propone: no tiene valor por defecto (D-2)."""
        given = self.properties.is_property_set
        offered = [identifier for identifier, _label, _about in des_panels.removal_stockpile_items(None, None)
                   if identifier != des_panels.NO_ZONE]
        if offered and not given("stockpile"):
            current = [ref for ref in offered if getattr(des_panels.removal_stockpile(ref), "state", None) == "current"]
            self.stockpile = (current or offered)[0]
        if not self.name.strip():
            found = des_panels.removal_stockpile(self.stockpile)
            base = tr("Removal of «{stockpile}»", stockpile=found.name if found is not None else tr("stockpile"))
            names, number = des_panels.platform_names(), 1
            proposal = base
            while proposal in names:
                number += 1
                proposal = f"{base} {number}"
            self.name = proposal
        if not given("start"):
            start = des_panels.platform_default_start()
            if start is None and des_panels.has_surfaces():
                items = [identifier for identifier, _name, _about in des_panels.platform_start_items(None, None)
                         if identifier != des_panels.NO_ZONE and not identifier.startswith("entity:")]
                start = surface_proposal.ground_item(context, project, items, des_panels.surface_choice)
            if start is not None:
                self.start = start

    def draw(self, context: Any) -> None:
        """Arriba el nombre; el acopio y la partida; **la lista de lo que se apoya en el acopio**, leída antes de calcular; la transición
        (el ángulo, el factor de malla y la métrica) y el motivo de la pared. En la confirmación de crear, el resumen y, si pide un
        motivo que falta, qué hacer."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "stockpile", text=tr("Stockpile"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        des_panels.draw_resting(layout, DIALOG_WIDTH)
        layout.prop(self, "as_platform", text=tr("As a platform"), translate=False)
        box = layout.box()
        if self.as_platform:  # en lugar de la transición y la pared: el borde de la plataforma (T41)
            box.label(text=tr("Edge of the platform"), translate=False)
            box.prop(self, "edge_angle", text=tr("Edge angle (°)"), translate=False)
            box.prop(self, "reach", text=tr("Reach of the edge (m)"), translate=False)
            box.prop(self, "mesh_factor", text=tr("Mesh factor"), translate=False)
            box.prop(self, "metric", text=tr("Metric"), translate=False)
            return
        box.label(text=tr("Transition at the edge of the stockpile"), translate=False)
        box.prop(self, "transition_angle", text=tr("Transition angle (°)"), translate=False)
        box.prop(self, "mesh_factor", text=tr("Mesh factor"), translate=False)
        box.prop(self, "metric", text=tr("Metric"), translate=False)
        layout.prop(self, "wall_reason", text=tr("Reason for the wall"), translate=False)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self) -> design_model.RemovalRequest:
        """Lo pedido en el diálogo como la ``design.model.RemovalRequest`` (RF-016-11), comprobado sin escribir ni calcular nada. Lo que
        se deja vacío (el factor de malla) lo resuelve el dominio con el valor por defecto de su parámetro; el ángulo de transición no
        tiene ninguno y lo rechaza el dominio si falta (D-2). :class:`ComputeFormError` si falta algo del diálogo."""
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the removal"))
        if self.stockpile in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the stockpile to remove"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the removal"))
        return design_model.RemovalRequest(
            name, self.stockpile, self.start, transition_deg=typed_number(self.transition_angle, tr("Transition angle (°)")),
            mesh_factor=typed_number(self.mesh_factor, tr("Mesh factor")), metric=self.metric.lower(),
            wall_reason=self.wall_reason.strip() or None)

    def _platform_request(self) -> design_model.PlatformRequest:
        """Lo pedido «como plataforma» como la ``design.model.PlatformRequest`` de la plataforma de la 015 con la huella del acopio
        (:meth:`~geoblender.design.model.PlatformRequest.of_stockpile`; RF-016-16, A9), comprobado sin escribir ni calcular nada: el ángulo
        y el alcance del borde (sin valor por defecto: los rechaza el dominio si faltan, RF-015-08), el factor de malla (vacío: el valor por
        defecto) y la métrica. La cota inicial, la pendiente y el eje salen del plano de la base del acopio y no se piden; el modo, la
        tolerancia de contrapendiente y lo que declara, los valores por defecto de la plataforma (no protege). :class:`ComputeFormError` si
        falta algo del diálogo."""
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the removal"))
        if self.stockpile in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the stockpile to remove"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the removal"))
        return design_model.PlatformRequest.of_stockpile(
            name, self.stockpile, self.start, edge_angle_deg=typed_number(self.edge_angle, tr("Edge angle (°)")),
            reach_m=typed_number(self.reach, tr("Reach of the edge (m)")),
            mesh_factor=typed_number(self.mesh_factor, tr("Mesh factor")), metric=self.metric.lower())

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido (sin escribir nada si falta algo), pasa por
        la puerta de la 008 y calcula la retirada por pasos con ``design.steps.removal_run`` —compila las máscaras antes si no están al
        día—, sin registrar nada (RF-015-03): desde la interfaz, en el modal con el avance y Esc (RF-015-29, RNF-016-05); desde un guion,
        de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los rechazos (el acopio y su detección
        —obsoleta: RF-016-12—, el ángulo de transición sin valor, la partida, un sector con la búsqueda pendiente, el nombre repetido) y
        todas las cuentas son de ``design``."""
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
            request: design_model.PlatformRequest | design_model.RemovalRequest = (
                self._platform_request() if self.as_platform else self._request())
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        as_platform = isinstance(request, design_model.PlatformRequest)
        ready = ensure_ready(provenance.PLATFORM if as_platform else self.provenance_op_type, [], report=self.report,
                             dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        if isinstance(request, design_model.PlatformRequest):  # una sola operación: la de una plataforma de la 015 con la huella del acopio (T21)
            steps = design_steps.platform_run(project, request, version=version, budget_s=self.STEP_BUDGET_S)
        else:
            steps = design_steps.removal_run(project, request, version=version, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _confirmation(self, context: Any) -> set[str]:
        """El diálogo de crear el cálculo abierto. Con algo apoyado en el acopio (RF-016-14) o una pared (RF-016-15) que piden
        confirmación expresa, su botón lo dice («Confirmar lo que se le apoya y crear»…): pulsarlo es la confirmación; «Cancelar» y
        cerrarlo no crean nada. Retirado «como plataforma» solo hay lo apoyado que confirmar: su pared es la de su borde, un aviso."""
        held = calculation()
        self.confirm_resting = held is not None and held.needs_resting_confirmation
        self.confirm_wall = held is not None and held.needs_wall_confirmation
        return _CalculateAndCreate._confirmation(self, context)

    def _confirm_text(self, held: Calculation) -> str:
        resting, wall = held.needs_resting_confirmation, held.needs_wall_confirmation
        if resting and wall:
            return tr("Confirm what rests on it and the wall, and create")
        if resting:
            return tr("Confirm what rests on it and create")
        if wall:
            return tr("Confirm the wall and create")
        return _CalculateAndCreate._confirm_text(self, held)

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-016-11, RF-015-02): como las demás, y con algo apoyado en el acopio o una pared **no se crea sin la confirmación
        expresa** (``confirm_resting`` y ``confirm_wall``: el botón de la ventana, o quien la lanza desde un guion) ni, con una pared de
        más de 45° y 3 m, sin su motivo (RF-016-14, RF-016-15): lo dice y el cálculo sigue abierto (se confirma, o se calcula otra vez con
        el motivo). Con ellas, las deja dichas en el cálculo antes de crearlo (``Calculation.confirm_removal``: quedan en los ajustes de
        la operación con su decisor y su fecha)."""
        from ...design import entity_store, removal, supported_store  # al usarlo: habilitar no carga el cálculo

        opened = calculation()
        if opened is not None and isinstance(opened.entity, supported_store.PreparedRemoval):
            try:
                supported_store.check_removal_confirmed(opened.entity, opened.outcome,  # type: ignore[arg-type]
                                                        resting=self.confirm_resting, wall=self.confirm_wall)
            except design_messages.DesignError as exc:
                self.report({"ERROR"}, design_error_text(exc))
                return {"CANCELLED"}
            opened.confirm_removal(resting=self.confirm_resting, wall=self.confirm_wall)
        elif (opened is not None and isinstance(opened.entity, entity_store.PreparedPlatform) and opened.entity.origin is not None
              and opened.entity.removed is not None):
            # «como plataforma» (T41; RF-016-16, RF-016-14): solo hay lo apoyado que confirmar (su pared es la de su borde, un aviso de la
            # plataforma); sin la confirmación expresa no se crea, y el cálculo sigue abierto
            try:
                removal.check_resting_confirmed(opened.entity.origin.item.name, opened.entity.resting, confirmed=self.confirm_resting)
            except design_messages.DesignError as exc:
                self.report({"ERROR"}, design_error_text(exc))
                return {"CANCELLED"}
            opened.confirm_removal(resting=self.confirm_resting)
        created = _CalculateAndCreate._create(self, context)
        if opened is None or "FINISHED" not in created:
            return created
        return self._update_declared(context, opened)  # T41: lo que sigue (la capa de entidades, como operación aparte, T34)

    def _created_text(self, opened: Calculation) -> str:
        if opened.op_type == provenance.PLATFORM:  # retirado «como plataforma» (T41)
            return tr("Removal of the stockpile «{stockpile}» as the platform «{name}» created in {version}",
                      stockpile=opened.entity.removed.name, name=opened.name, version=opened.version)  # type: ignore[union-attr]
        return tr("Removal of the stockpile «{name}» created in {version}", name=opened.name, version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando la retirada del acopio… 40 % · Esc: cancelar» o, tras crearla, «Poniendo al día las
        restricciones declaradas… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._chain:
            return tr("Updating the declared constraints and the masks… {percent} % · Esc: cancel", percent=percent)
        return tr("Computing the removal of the stockpile… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._chain:
            return tr("Cancelled: the removal is created; the declared constraints and the masks are brought up to date before the next "
                      "operation that uses them, and the entity layer with the next entity order or «Recompute the stale results»")
        return _CalculateAndCreate._cancelled_text(self)

    def _error_text(self, exc: GeoblenderError) -> str:
        found = _CalculateAndCreate._error_text(self, exc)
        if self._chain:
            return f"{found} " + tr("The removal is created: only the declared constraints and the masks have not been brought up to date")
        return found


# --- Cuerpo apoyado… (spec 016, T25; HU-016-4; RF-016-20 a RF-016-22, RF-015-02, RF-015-03, RF-015-28, RF-015-29; RNF-016-02 y 05;
#     plan 016 §5.3.3 y §5.5; comprobación manual M2) -------------------------------------------------------------------

CREATE_BODY = provenance.BODY_COMMAND
BODY_SENSE_ITEMS = [
    ("ON_BASE", "On a base", "The known surface is its support: the roof is the support plus the thickness"),
    ("UNDER_ROOF", "Under a roof", "The known surface is its roof: the base is the roof minus the thickness")]
BODY_FROM_ITEMS = [
    ("FIELD", "A field", "The thickness is a field of the points or of the polygons of the layer"),
    ("Z", "The Z of the vertices", "The thickness is the Z of each vertex of the 3D lines of the layer")]


def _body_data_layer_changed(self: Any, _context: Any) -> None:
    """El ``update`` de la capa de datos de «Cuerpo apoyado…»: de cómo se lee el espesor propone lo que la capa puede dar (la Z de sus
    vértices si es de líneas 3D, un campo si es de puntos o de polígonos; la M no llega al proyecto)."""
    self.data_from = "Z" if des_panels.body_data_kind(self.data_layer) == "line3d" else "FIELD"


class GEOBLENDER_OT_des_create_body(_ChainsEntityLayer, _CalculateAndCreate, DesignCommandAware, ProvenanceAwareOperator, _StepsModal,
                                   bpy.types.Operator):
    """Create a body from its footprint and its thickness data, resting on a known surface or under a known roof: the thickness is interpolated and the other surface is derived from it"""

    bl_idname = CREATE_BODY
    bl_label = "Supported body…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.BODY
    COMMAND = CREATE_BODY

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the body, unique in the active version", options=_FIELD)
    layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of the footprints",
        description="Layer of polygons of the project the footprint of the body is taken from",
        items=des_panels.body_footprint_items, options=_FIELD)
    feature: StringProperty(  # type: ignore[valid-type]
        name="Footprint of the layer",
        description="Name or number (fid) of the polygon of the layer that is the footprint of the body", options=_FIELD)
    data_layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of the thickness data",
        description="Layer of the project with the thickness of the body: points or polygons with a field, or 3D lines with the "
                    "thickness in the Z of their vertices", items=des_panels.body_data_items, options=_FIELD,
        update=_body_data_layer_changed)
    data_from: EnumProperty(  # type: ignore[valid-type]
        name="Thickness from",
        description="Where the thickness is read from: a field of the points or of the polygons (constant in each polygon), or the "
                    "Z of the vertices of the 3D lines; it is not assumed", items=BODY_FROM_ITEMS, default="FIELD", options=_FIELD)
    data_field: StringProperty(  # type: ignore[valid-type]
        name="Thickness field",
        description="Numeric field of the layer with the thickness in metres; it cannot be negative", options=_FIELD)
    sense: EnumProperty(  # type: ignore[valid-type]
        name="Sense",
        description="On a base: the known surface is its support and the surface of the chain rises to the roof; under a roof: the "
                    "known surface is its roof, as the existing waste, and the surface does not change", items=BODY_SENSE_ITEMS,
        default="UNDER_ROOF", options=_FIELD)
    surface: EnumProperty(  # type: ignore[valid-type]
        name="Known surface",
        description="The surface the body rests on (on a base) or hangs under (under a roof): the ground, a design surface or the "
                    "surface of an entity that changes the surface", items=des_panels.platform_start_items, options=_FIELD)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the body starts from (only on a base): the surface that rises to the roof of the body (by default, the "
                    "last of the chain)", items=des_panels.platform_start_items, options=_FIELD)
    max_distance: StringProperty(  # type: ignore[valid-type]
        name="Maximum distance to the data (m)",
        description="Farthest distance from a thickness datum, in metres: what is farther is warned and triangles longer than twice "
                    "this are not interpolated; it has no default value: you choose it", options=_FIELD)
    zero_at_edge: BoolProperty(  # type: ignore[valid-type]
        name="Zero at the edge",
        description="The thickness is zero at the edge of the footprint", default=False, options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con el avance y Esc: los pone invoke; desde
    # un guion, sin ellos, de una vez. Un cuerpo no retira nada ni deja una pared: no pide más confirmación.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué. Con ``confirm``, el diálogo de crear
        el cálculo abierto. Si no, las listas leídas de nuevo (las capas de huellas y de datos, las superficies y las entidades de la
        cadena), la propuesta (un nombre, la primera capa de huellas y de datos, cómo se lee el espesor y las superficies) y el diálogo del
        cálculo: Intro calcula. Sin ninguna capa de polígonos, lo dice."""
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
            des_panels.refresh_body_choices(project)
            if not des_panels.has_body_footprints():
                self.report({"ERROR"}, tr("There is no layer of polygons in the project: import the footprints of the bodies first"))
                return {"CANCELLED"}
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label), confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 016 §5.3.3): un nombre que no repite el de ninguna entidad de la
        versión («Cuerpo apoyado», «Cuerpo apoyado 2»…), **la primera capa de huellas y la primera de datos** con cómo se lee su espesor
        (la Z de unas líneas 3D, un campo de puntos o de polígonos) y las superficies: la conocida y la de partida, **la última de la
        cadena** (``des_panels.platform_default_start``) o, sin entidades calculadas, el terreno (``surface_proposal.ground_item``, con lo
        seleccionado en la vista). La distancia máxima no se propone: no tiene valor por defecto (D-9)."""
        given = self.properties.is_property_set
        if not given("layer"):
            self.layer = des_panels.body_footprint_items(None, None)[0][0]
        data = [item[0] for item in des_panels.body_data_items(None, None) if item[0] != des_panels.NO_LAYER]
        if data and not given("data_layer"):
            self.data_layer = data[0]
            if not given("data_from"):
                _body_data_layer_changed(self, None)
        if not self.name.strip():
            names, number = des_panels.platform_names(), 1
            proposal = base = tr("Supported body")
            while proposal in names:
                number += 1
                proposal = f"{base} {number}"
            self.name = proposal
        items = [identifier for identifier, _name, _about in des_panels.platform_start_items(None, None)
                 if identifier != des_panels.NO_ZONE and not identifier.startswith("entity:")]
        ground = surface_proposal.ground_item(context, project, items, des_panels.surface_choice) if items else None
        if not given("surface") and ground is not None:
            self.surface = ground
        if not given("start"):
            start = des_panels.platform_default_start() or ground
            if start is not None:
                self.start = start

    def draw(self, context: Any) -> None:
        """Arriba el nombre; la huella (su capa y su geometría); los datos de espesor (su capa, cómo se lee y su campo); la superficie
        conocida (su sentido, ella y, «sobre una base», la de partida); la distancia máxima y «cero en el borde». En la confirmación de
        crear, el resumen."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        box = layout.box()
        box.label(text=tr("Footprint of the body"), translate=False)
        box.prop(self, "layer", text=tr("Layer"), translate=False)
        box.prop(self, "feature", text=tr("Footprint of the layer"), translate=False)
        box = layout.box()
        box.label(text=tr("Thickness data"), translate=False)
        box.prop(self, "data_layer", text=tr("Layer"), translate=False)
        box.prop(self, "data_from", text=tr("Thickness from"), translate=False)
        if self.data_from == "FIELD":
            box.prop(self, "data_field", text=tr("Thickness field"), translate=False)
        box = layout.box()
        box.label(text=tr("Known surface"), translate=False)
        box.prop(self, "sense", text=tr("Sense"), translate=False)
        box.prop(self, "surface", text=tr("Known surface"), translate=False)
        if self.sense == "ON_BASE":
            box.prop(self, "start", text=tr("Start surface"), translate=False)
        layout.prop(self, "max_distance", text=tr("Maximum distance to the data (m)"), translate=False)
        layout.prop(self, "zero_at_edge", text=tr("Zero at the edge"), translate=False)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self) -> design_model.BodyRequest:
        """Lo pedido en el diálogo como la ``design.model.BodyRequest`` (RF-016-20), comprobado sin escribir ni calcular nada. La
        distancia máxima no tiene valor por defecto: si falta, la rechaza el dominio (D-9); un espesor negativo o que falta, también.
        :class:`ComputeFormError` si falta algo del diálogo."""
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the body"))
        if self.layer in ("", des_panels.NO_LAYER):
            raise ComputeFormError(tr("Choose the layer of the footprints of the body"))
        feature = self.feature.strip()
        if not feature:
            raise ComputeFormError(tr("Write the name or the number of the footprint in its layer"))
        if self.data_layer in ("", des_panels.NO_LAYER):
            raise ComputeFormError(tr("Choose the layer of the thickness data"))
        from_field = self.data_from == "FIELD"
        field = self.data_field.strip() if from_field else "Z"
        if not field:
            raise ComputeFormError(tr("Write the field of the layer with the thickness"))
        if self.surface in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the known surface of the body"))
        on_base = self.sense == "ON_BASE"
        if on_base and self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the body"))
        return design_model.BodyRequest(
            name, self.layer, feature, self.data_layer, field, self.data_from.lower(), self.surface, self.sense.lower(),
            start=self.start if on_base else None,
            max_distance_m=typed_number(self.max_distance, tr("Maximum distance to the data (m)")), zero_at_edge=self.zero_at_edge)

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_CalculateAndCreate._create`). Si no, comprueba lo pedido (sin escribir nada
        si falta algo), pasa por la puerta de la 008 y calcula el cuerpo por pasos con ``design.steps.body_run`` —compila las máscaras
        antes si no están al día—, sin registrar nada (RF-015-03): desde la interfaz, en el modal con el avance y Esc (RF-015-29,
        RNF-016-05); desde un guion, de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los rechazos (los
        datos de espesor, la distancia máxima sin valor, una huella sin datos o con todo lejos, la partida y los nombres) y todas las
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
        ready = ensure_ready(self.provenance_op_type, [], report=self.report, dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.body_run(project, request, version=version, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-016-20, RF-015-02): como las demás (:meth:`_CalculateAndCreate._create`: una transacción) y, **ya creado**, encadena lo
        que sigue (:meth:`_ChainsEntityLayer._update_declared`, T41: el cuerpo no declara restricciones, pero la capa de entidades se pone al
        día con su fila, como operación aparte: T34)."""
        opened = calculation()
        created = _CalculateAndCreate._create(self, context)
        if opened is None or "FINISHED" not in created:
            return created
        return self._update_declared(context, opened)

    def _created_text(self, opened: Calculation) -> str:
        return tr("Supported body «{name}» created in {version}", name=opened.name, version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando el cuerpo apoyado… 40 % · Esc: cancelar» o, tras crearlo, «Poniendo al día las
        restricciones declaradas… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._chain:
            return tr("Updating the declared constraints and the masks… {percent} % · Esc: cancel", percent=percent)
        return tr("Computing the supported body… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._chain:
            return tr("Cancelled: the supported body is created; the declared constraints and the masks are brought up to date before the "
                      "next operation that uses them, and the entity layer with the next entity order or «Recompute the stale results»")
        return _CalculateAndCreate._cancelled_text(self)

    def _error_text(self, exc: GeoblenderError) -> str:
        found = _CalculateAndCreate._error_text(self, exc)
        if self._chain:
            return f"{found} " + tr("The supported body is created: only the declared constraints and the masks have not been brought up "
                                    "to date")
        return found


# --- Contrafuerte… (spec 016, T27 (b); HU-016-3; RF-016-17, RF-016-18, RF-015-02, RF-015-03, RF-015-10, RF-015-12, RF-015-28, RF-015-29;
#     RNF-016-05; plan 016 §5.3.3 y §5.5; comprobación manual M3) --------------------------------------------------------

ADD_BUTTRESS = provenance.BUTTRESS_COMMAND
_BUTTRESS_HIDDEN = frozenset({"confirm", "in_steps", "preview"})
"""Las propiedades ocultas de «Contrafuerte…»: las pone quien la lanza (o su ventana de confirmar)."""


def _buttress_fields() -> tuple[str, ...]:
    """Los campos del diálogo de «Contrafuerte…»: sus propiedades no ocultas."""
    return tuple(name for name in GEOBLENDER_OT_des_add_buttress.__annotations__ if name not in _BUTTRESS_HIDDEN)


def _refresh_buttress_preview(self: Any, _context: Any) -> None:
    """El ``update`` de cada campo de «Contrafuerte…» que cambia lo que dibuja su vista previa (T32; RF-016-23): con la vista previa **de
    la zona de coronación** activa, la redibuja con lo que dice ahora el diálogo. Un diálogo a medias (un campo sin escribir, un número
    que no lo es, sin perfil) no la cambia: sigue la última completa. Solo lee."""
    loaded = _entity_preview_loaded()
    if loaded is None or not loaded.enabled() or loaded.plan() is None or loaded.plan().buttress is None:
        return
    project = SESSION.project
    if project is None:
        return
    try:
        request = GEOBLENDER_OT_des_add_buttress._request(self, project)
    except (ProfileFormError, GeoblenderError, sqlite3.Error, OSError, ValueError):
        return
    loaded.replace(loaded.EntityPlan(buttress=request))


class GEOBLENDER_OT_des_add_buttress(_ClearsEntityPreview, _CalculateAndCreate, DesignCommandAware, ProvenanceAwareOperator,
                                     _StepsModal, bpy.types.Operator):
    """Buttress at the toe of a slope"""

    bl_idname = ADD_BUTTRESS
    bl_label = "Buttress…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.BUTTRESS
    COMMAND = ADD_BUTTRESS

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the buttress, unique in the active version", options=_FIELD,
        update=_refresh_buttress_preview)
    layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of the crown zones",
        description="Layer of polygons of the project the crown zone of the buttress is taken from",
        items=des_panels.buttress_zone_items, options=_FIELD, update=_refresh_buttress_preview)
    feature: StringProperty(  # type: ignore[valid-type]
        name="Crown zone of the layer",
        description="Name or number (fid) of the polygon of the layer that is the crown zone of the buttress", options=_FIELD,
        update=_refresh_buttress_preview)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the buttress starts from: the ground, a design surface or the surface of another entity (by default, the "
                    "last of the chain)", items=des_panels.platform_start_items, options=_FIELD, update=_refresh_buttress_preview)
    support: EnumProperty(  # type: ignore[valid-type]
        name="Support surface",
        description="Surface the buttress rests on, if it is not the start surface: a design surface, the exploitation surface of a "
                    "quarry or the surface of another entity (none: it rests on the start surface); it does not change the calculation",
        items=des_panels.buttress_support_items, options=_FIELD)
    profile: StringProperty(  # type: ignore[valid-type]
        name="Bench profile",
        description="Bench profile of the buttress: its height, its face, its berm and its anchor give its slopes and the levels the "
                    "crown can be at", options=_FIELD, update=_refresh_buttress_preview)
    crown: StringProperty(  # type: ignore[valid-type]
        name="Crown elevation (m)",
        description="Elevation of the crown of the buttress in metres: it has to be one of the anchor levels of its profile (the anchor "
                    "plus a whole number of bench heights); it has no default value: you choose it", options=_FIELD,
        update=_refresh_buttress_preview)
    reach: StringProperty(  # type: ignore[valid-type]
        name="Reach (m)",
        description="Farthest distance from the crown zone the slopes can reach, in metres (empty: down to the lowest elevation of the "
                    "start surface)", options=_FIELD)
    metric: EnumProperty(  # type: ignore[valid-type]
        name="Metric",
        description="How the distance to the crown zone is measured: the 5×5 chamfer (fast, with the scale of the grid) or the exact "
                    "Euclidean distance", items=METRIC_ITEMS, default="EXACT", options=_FIELD)
    protect: BoolProperty(  # type: ignore[valid-type]
        name="Protect",
        description="Declare the crown zone a zone without cut: the other designs do not cut in it (the buttress protects by default)",
        default=True, options=_FIELD, update=_refresh_buttress_preview)
    guard: StringProperty(  # type: ignore[valid-type]
        name="Guard (m)",
        description="Distance around the crown zone that is also protected, in metres; it is required to protect and has no default "
                    "value: you choose it", options=_FIELD, update=_refresh_buttress_preview)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why the crown zone is protected, recorded with the declared constraint (empty: a reason is generated that you can "
                    "edit later)", options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con el avance y Esc: los pone invoke; desde
    # un guion, sin ellos, de una vez. Un contrafuerte no retira nada ni deja una pared: no pide más confirmación.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    preview: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]  # «Vista previa» de la zona de coronación (T32)

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué. Con ``confirm``, el diálogo de crear
        el cálculo abierto. Si no, las listas leídas de nuevo (los perfiles de banco, las superficies, las entidades de la cadena y las
        capas de polígonos de las zonas de coronación), la propuesta (un nombre, la primera capa y la partida) y el diálogo del cálculo:
        Intro calcula. Sin ninguna capa de polígonos, lo dice."""
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
            des_panels.refresh_choices(project)
            des_panels.refresh_platform_choices(project)
            des_panels.refresh_buttress_choices(project)
            if not des_panels.has_buttress_zones():
                self.report({"ERROR"}, tr("There is no layer of polygons in the project: import the crown zones of the buttress first"))
                return {"CANCELLED"}
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label), confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 016 §5.3.3): un nombre que no repite el de ninguna entidad de la
        versión («Contrafuerte», «Contrafuerte 2»…), **la primera capa de polígonos** y la partida: **la última de la cadena**
        (``des_panels.platform_default_start``) o, sin entidades calculadas, el terreno (``surface_proposal.ground_item``, con lo
        seleccionado en la vista). **No propone** el perfil, la cota de coronación ni el resguardo: no tienen valor por defecto (D-21,
        D-19) y los elige la persona."""
        given = self.properties.is_property_set
        if not given("layer"):
            self.layer = des_panels.buttress_zone_items(None, None)[0][0]
        if not self.name.strip():
            names, number = des_panels.platform_names(), 1
            proposal = base = tr("Buttress")
            while proposal in names:
                number += 1
                proposal = f"{base} {number}"
            self.name = proposal
        if not given("start"):
            start = des_panels.platform_default_start()
            if start is None and des_panels.has_surfaces():
                items = [identifier for identifier, _name, _about in des_panels.platform_start_items(None, None)
                         if identifier != des_panels.NO_ZONE and not identifier.startswith("entity:")]
                start = surface_proposal.ground_item(context, project, items, des_panels.surface_choice)
            if start is not None:
                self.start = start

    def draw(self, context: Any) -> None:
        """Arriba el nombre; la zona de coronación (su capa y su geometría); la partida y el apoyo; el perfil de banco (se busca entre los
        del proyecto), la cota de coronación y el alcance; la métrica; si protege, con su resguardo y su motivo. En la confirmación de
        crear, el resumen."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        box = layout.box()
        box.label(text=tr("Crown zone"), translate=False)
        box.prop(self, "layer", text=tr("Layer"), translate=False)
        box.prop(self, "feature", text=tr("Crown zone of the layer"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        layout.prop(self, "support", text=tr("Support surface"), translate=False)
        shown = des_panels.view()
        box = layout.box()
        box.label(text=tr("Slopes of the buttress"), translate=False)
        if shown is not None:
            box.prop_search(self, "profile", shown, "profiles", text=tr("Bench profile"), translate=False)
        box.prop(self, "crown", text=tr("Crown elevation (m)"), translate=False)
        box.prop(self, "reach", text=tr("Reach (m)"), translate=False)
        box.prop(self, "metric", text=tr("Metric"), translate=False)
        layout.prop(self, "protect", text=tr("Protect"), translate=False)
        if self.protect:
            layout.prop(self, "guard", text=tr("Guard (m)"), translate=False)
            layout.prop(self, "reason", text=tr("Reason"), translate=False)
        _draw_entity_preview_button(layout, self, ADD_BUTTRESS, _buttress_fields())  # «Vista previa» de la zona de coronación (T32)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self, project: Any) -> design_model.ButtressRequest:
        """Lo pedido en el diálogo como la ``design.model.ButtressRequest`` (RF-016-17), comprobado sin escribir ni calcular nada: los
        perfiles se leen de nuevo (un guion no abre el diálogo que los lee). **La cota de coronación y el resguardo de quien protege no
        tienen valor por defecto** (D-21, D-19): si faltan, los rechaza el dominio; una cota fuera del ancla de su perfil, también
        (RF-016-18, con la cota del ancla más próxima). :class:`ComputeFormError` si falta algo del diálogo."""
        des_panels.fill_profiles(project)
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the buttress"))
        if self.layer in ("", des_panels.NO_LAYER):
            raise ComputeFormError(tr("Choose the layer of the crown zones of the buttress"))
        feature = self.feature.strip()
        if not feature:
            raise ComputeFormError(tr("Write the name or the number of the crown zone in its layer"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the buttress"))
        profile = GEOBLENDER_OT_des_compute_envelope._profile_code(self.profile, tr("Bench profile"), des_panels.profile_codes())
        if profile is None:
            raise ComputeFormError(tr("Choose the bench profile of the buttress"))
        return design_model.ButtressRequest(
            name, design_model.ButtressFields(self.layer), feature, self.start, profile,
            support=None if self.support in ("", des_panels.NO_ZONE) else self.support,
            crown_m=typed_number(self.crown, tr("Crown elevation (m)")), reach_m=typed_number(self.reach, tr("Reach (m)")),
            metric=self.metric.lower(), protect=self.protect,
            guard_m=typed_number(self.guard, tr("Guard (m)")) if self.protect else None,
            reason=(self.reason.strip() or None) if self.protect else None)

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido (sin escribir nada si falta algo), pasa
        por la puerta de la 008 y calcula el contrafuerte por pasos con ``design.steps.buttress_run`` —compila las máscaras antes si no
        están al día—, sin registrar nada (RF-015-03): desde la interfaz, en el modal con el avance y Esc (RF-015-29, RNF-016-05); desde
        un guion, de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los rechazos (la capa y su geometría,
        la cota de coronación sin valor o fuera del ancla de su perfil, el resguardo sin valor de quien protege, la coronación por debajo
        del apoyo, la partida, un sector con la búsqueda pendiente, el nombre repetido) y todas las cuentas son de ``design``."""
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
        ready = ensure_ready(self.provenance_op_type, [], report=self.report, dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.buttress_run(project, request, version=version, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _show_preview(self) -> set[str]:
        """«Vista previa» (T32; RF-016-23): comprueba lo pedido hasta el perfil como al calcular (:meth:`_request`, sin escribir ni
        calcular nada) y activa con ello la vista previa de la zona de coronación (``bl.draw.entity``: la zona, la zona con su
        resguardo que declarará «sin corte» y la cota de coronación, con su leyenda); la que hubiera activa se cambia por la nueva
        (pulsarlo otra vez, o cambiar un campo del diálogo: :func:`_refresh_buttress_preview`). Lo que falta del diálogo se rechaza sin
        tocar la vista previa; lo que rechazaría «Calcular» de la capa, de la geometría y del resguardo sale en la propia vista previa,
        como aviso; la cota y el resguardo sin elegir se dicen. Se quita al cancelar la orden, al Esc a mitad del cálculo, al crear el
        contrafuerte, con su control y al conmutar a la interfaz de Blender."""
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
        preview = _entity_preview()
        try:
            preview.enable(preview.EntityPlan(buttress=request))
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr("The preview of the entity could not be shown: {detail}", detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of the buttress «{name}»", name=request.name))
        return {"FINISHED"}

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-016-17, RF-015-02): como las demás (:meth:`_CalculateAndCreate._create`: una transacción) y, **ya creado**,
        quita la vista previa de la zona de coronación (RF-016-23: el contrafuerte ya existe, ya no se prepara) y encadena lo que sigue
        (:meth:`_update_declared`)."""
        opened = calculation()
        created = _CalculateAndCreate._create(self, context)
        if opened is None or "FINISHED" not in created:
            return created
        _entity_preview_off()
        return self._update_declared(context, opened)

    # --- Lo que sigue a crearlo (RF-015-10, RF-012-06; plan 016 §5.3.2, P-8) -------------------

    _chain = False
    """Si los pasos que corren son los de lo que sigue a crear el contrafuerte (y no los de calcularlo)."""

    def _update_declared(self, context: Any, opened: Calculation) -> set[str]:
        """Tras crear el contrafuerte, **pone al día** las restricciones que declaran las entidades de la versión y las máscaras
        (``design.entity_store.after_entity_change``: declara «sin corte» sobre **su zona de coronación** —no sobre toda la huella: P-8,
        H-6—, recompila las máscaras si ya no están al día, dice qué quedó obsoleto y pone al día la capa de entidades), por pasos con
        el avance y Esc: el contrafuerte **ya está creado** (cada etapa es una operación y una transacción propias); cerrar o fallar a
        mitad deja las máscaras obsoletas con su causa y se compilan de nuevo antes de que un operador las use."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        project = SESSION.project
        self._chain = True
        steps = entity_store.after_entity_change(project, opened.version, budget_s=self.STEP_BUDGET_S)
        started = self._run_steps(context, project, opened.name, steps)
        return {"FINISHED"} if started == {"CANCELLED"} else started  # ya creado: el fallo está dicho

    def _finished(self, context: Any, opened: Any) -> set[str]:
        """Con los pasos de lo que sigue a crearlo, dice lo que hizo (:meth:`_report_chain`); si no, como las demás órdenes."""
        if self._chain:
            self._chain = False
            self._report_chain(opened)
            return {"FINISHED"}
        return _CalculateAndCreate._finished(self, context, opened)

    def _report_chain(self, chain: Any) -> None:
        """Lo que hizo ``chain`` (``design.entity_store.EntityChain``), en el informe y en el registro: la declaración, las máscaras
        recompiladas, por restricción el polígono y la zona ganados y perdidos (m²), lo que quedó obsoleto y, en alerta, lo que no se
        pudo hacer (RF-012-06)."""
        shown = i18n.language()
        for notice in chain.notices():
            self._report({"WARNING" if notice.severity == "warning" else "INFO"}, notice.text(shown))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()

    def _created_text(self, opened: Calculation) -> str:
        return tr("Buttress «{name}» created in {version}", name=opened.name, version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando el contrafuerte… 40 % · Esc: cancelar» o, tras crearlo, «Poniendo al día las
        restricciones declaradas… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._chain:
            return tr("Updating the declared constraints and the masks… {percent} % · Esc: cancel", percent=percent)
        return tr("Computing the buttress… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._chain:
            return tr("Cancelled: the buttress is created; the declared constraints and the masks are brought up to date before the "
                      "next operation that uses them, and the entity layer with the next entity order or «Recompute the stale results»")
        return _CalculateAndCreate._cancelled_text(self)

    def _error_text(self, exc: GeoblenderError) -> str:
        found = _CalculateAndCreate._error_text(self, exc)
        if self._chain:
            return f"{found} " + tr("The buttress is created: only the declared constraints and the masks have not been brought up to date")
        return found


# --- Acopio (detectar, retirar)… (spec 016, T35; HU-016-1, HU-016-4; RF-016-02, RF-016-08, RF-016-10, RF-016-23, RF-016-25, RF-015-03,
#     RF-015-28, RF-015-29; RNF-016-05; plan 016 §5.3.3 y §5.5; comprobación manual M6) -------------------------------------------

DETECT_STOCKPILES = provenance.STOCKPILE_COMMAND
EDIT_STOCKPILE = "geoblender.des_edit_stockpile"
STOCKPILE_CANDIDATES = des_panels.STOCKPILE_CANDIDATES
_STOCKPILE_HIDDEN = frozenset({"confirm", "in_steps", "preview"})
"""Las propiedades ocultas de «Detectar acopios…»: las pone quien la lanza (o su ventana de confirmar)."""
MARK_FIELDS: tuple[tuple[str, str], ...] = (("name_field", "nombre"), ("margin_field", "margen"), ("material_field", "material"),
                                            ("base_field", "base"))
"""Los campos de una capa de marcas y el nombre que propone el diálogo para cada uno (plan 016 §5.2.1; la capa que los lleve): solo
se proponen los que la capa tiene; ninguno es una cifra, y la persona los cambia o los vacía."""
STOCKPILE_MODE_ITEMS = [
    ("DETECT", "Detect stockpiles", "Detect the stockpiles of a layer of marks on a surface and, if you want, the candidates without a mark"),
    ("REMOVE", "Remove a stockpile", "Remove a stockpile of a detection: its footprint goes down to its base, joined with the ground by a "
                                     "transition")]
"""Lo que hace «Acopio (detectar, retirar)…»: abre la orden de detectar o la de retirar."""
STOCKPILE_ACTION_ITEMS = [
    ("CONVERT", "Convert into a stockpile", "The candidate is a stockpile: the detection keeps it as one, with the reason you give"),
    ("DISCARD", "Discard", "The candidate is not a stockpile: it is not asked about again, with the reason you give"),
    ("ASK", "Ask again", "Remove the decision: the candidate is pending again, with the reason you give"),
    ("GO_TO", "Go to", "Frame the 3D view on the candidate; nothing changes")]
"""Lo que se hace con un candidato (``design.stockpile_store.decide_candidate``) o «Ir a» él."""
_DECISION_STATES = {"CONVERT": "converted", "DISCARD": "discarded", "ASK": "pending"}
"""El estado de cada decisión sobre un candidato (``design.stockpiles.CANDIDATE_*``)."""


def _taken_entity_names(project: Any) -> set[str]:
    """Los nombres de las entidades que ya hay en el proyecto y en la versión activa (una detección no repite ninguno en su ámbito)."""
    from ...design import entities  # al usarlo: habilitar no carga las entidades

    taken = {entry.record.name for entry in entities.project_registry(project)}
    version = scene_versions.active_version()
    if version:
        taken |= {entry.record.name for entry in entities.registry(project, version)}
    return taken


def _stockpile_fields() -> tuple[str, ...]:
    """Los campos del diálogo de «Detectar acopios…»: sus propiedades no ocultas."""
    return tuple(name for name in GEOBLENDER_OT_des_detect_stockpiles.__annotations__ if name not in _STOCKPILE_HIDDEN)


def _propose_mark_fields(self: Any, _context: Any) -> None:
    """El ``update`` de la capa de marcas de «Detectar acopios…» (T35; plan 016 §5.2.1): **propone** los campos que la capa tiene de entre los
    que lee la detección (:data:`MARK_FIELDS`: el nombre, el margen, el material y la superficie de base); los que no tiene, vacíos (la
    detección usa entonces el ``fid`` y los valores por defecto). Solo lee."""
    project = SESSION.project
    if project is None or self.layer in ("", des_panels.NO_LAYER):
        return
    from ...gis import store as gis_store  # al usarlo: habilitar no carga el almacén de ``gis``

    try:
        found = {column.field for column in gis_store.feature_source(project, self.layer).columns}
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.debug("No se pudieron leer los campos de la capa de marcas «%s»", self.layer, exc_info=True)
        return
    for prop, wanted in MARK_FIELDS:
        setattr(self, prop, wanted if wanted in found else "")


def _refresh_stockpile_preview(self: Any, _context: Any) -> None:
    """El ``update`` de cada campo de «Detectar acopios…» que cambia lo que dibuja su vista previa (T35, que pone lo de la T32; RF-016-23): con la
    vista previa **de las marcas** activa, la redibuja con lo que dice ahora el diálogo. Un diálogo a medias (un campo sin escribir, un número que no
    lo es) no la cambia: sigue la última completa. Solo lee."""
    loaded = _entity_preview_loaded()
    if loaded is None or not loaded.enabled() or loaded.plan() is None or loaded.plan().stockpile is None:
        return
    try:
        request = GEOBLENDER_OT_des_detect_stockpiles._request(self)
    except (ProfileFormError, GeoblenderError, sqlite3.Error, OSError, ValueError):
        return
    loaded.replace(loaded.EntityPlan(stockpile=request))


def _stockpile_layer_changed(self: Any, context: Any) -> None:
    """El ``update`` de la capa de marcas: propone sus campos (:func:`_propose_mark_fields`) y redibuja la vista previa."""
    _propose_mark_fields(self, context)
    _refresh_stockpile_preview(self, context)


def _threshold_text(param: str) -> str:
    """Lo que dice el diálogo de un umbral de la detección (D-3) cuando se deja vacío: **su valor por defecto y su tipo**, el de su familia
    (``design.params.STOCKPILE_ENTITY``): «Por defecto: 10 m · ADOPTADO». Un campo vacío es el valor por defecto con su procedencia (la de
    la familia: la HIPÓTESIS lo sigue siendo); lo que se escribe es lo que eligió la persona."""
    template = design_params.entity_params("stockpile").template(param)
    value = float(template.default)  # type: ignore[arg-type]
    units = {"m": " m", "m2": " m²", "deg": " °", "-": ""}.get(str(template.unit), f" {template.unit}")
    kind = tr("ASSUMPTION") if template.kind == ParamKind.HIPOTESIS else tr("ADOPTED")
    return tr("By default: {value}{unit} · {kind}", value=i18n.format_number(value, 0 if value.is_integer() else 2), unit=units, kind=kind)


class GEOBLENDER_OT_des_detect_stockpiles(_ClearsEntityPreview, _CalculateAndCreate, DesignCommandAware, ProvenanceAwareOperator,
                                          _StepsModal, bpy.types.Operator):
    """Detect the stockpiles of a layer of marks on a surface of the project or of the active version: plane, footprint and volume of each one, and the candidates without a mark if you ask for them"""

    bl_idname = DETECT_STOCKPILES
    bl_label = "Detect stockpiles…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.STOCKPILE_DETECT_PROJECT  # el de la versión lo decide la superficie (D-15): ``execute``
    COMMAND = DETECT_STOCKPILES

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the detection, unique in its scope (the project or the active version)", options=_FIELD)
    surface: EnumProperty(  # type: ignore[valid-type]
        name="Surface",
        description="Surface the stockpiles are detected on: the ground or a survey of the project (the detection is then of the project, "
                    "also without an active version) or a surface of the active version (the detection is then of the version)",
        items=des_panels.surface_items, options=_FIELD, update=_refresh_stockpile_preview)
    layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of the marks",
        description="Layer of polygons of the project with one mark per stockpile: a polygon that says roughly where it is",
        items=des_panels.layer_items, options=_FIELD, update=_stockpile_layer_changed)
    name_field: StringProperty(  # type: ignore[valid-type]
        name="Name field",
        description="Field of the layer with the name of each mark (its key; empty: the number of the polygon)", options=_FIELD,
        update=_refresh_stockpile_preview)
    margin_field: StringProperty(  # type: ignore[valid-type]
        name="Margin field",
        description="Numeric field of the layer with the margin of each mark in metres (empty: the margin of the detection)", options=_FIELD,
        update=_refresh_stockpile_preview)
    material_field: StringProperty(  # type: ignore[valid-type]
        name="Material field",
        description="Field of the layer with the material of each stockpile (empty: without material)", options=_FIELD,
        update=_refresh_stockpile_preview)
    base_field: StringProperty(  # type: ignore[valid-type]
        name="Base surface field",
        description="Field of the layer with the name of a surface of the project that is the base of the stockpile instead of a fitted "
                    "plane (empty: the plane)", options=_FIELD, update=_refresh_stockpile_preview)
    candidates: BoolProperty(  # type: ignore[valid-type]
        name="Look for candidates",
        description="Also look for the stockpiles that have no mark: the zones that stand out from the opening of the surface, listed so that "
                    "you convert each one into a stockpile or discard it with a reason", default=False, options=_FIELD,
        update=_refresh_stockpile_preview)
    margin_m: StringProperty(  # type: ignore[valid-type]
        name="Margin around the mark (m)",
        description="How far from its mark a stockpile can reach, in metres (empty: the default value, shown; a mark can give its own)",
        options=_FIELD, update=_refresh_stockpile_preview)
    crown_inner_m: StringProperty(  # type: ignore[valid-type]
        name="Inner distance of the crown (m)",
        description="Distance from the footprint where the ring of the crown that fits the base plane begins, in metres (empty: the default "
                    "value, shown)", options=_FIELD)
    crown_outer_m: StringProperty(  # type: ignore[valid-type]
        name="Outer distance of the crown (m)",
        description="Distance from the footprint where that ring ends, in metres (empty: the default value, shown)", options=_FIELD)
    crown_slope_deg: StringProperty(  # type: ignore[valid-type]
        name="Slope of the flat terrain (°)",
        description="Slope under which the terrain of the crown counts as flat, in degrees (empty: the default value, shown)", options=_FIELD)
    crown_flat_min_m2: StringProperty(  # type: ignore[valid-type]
        name="Minimum flat area of the crown (m²)",
        description="Area of flat terrain the crown needs to fit the plane with it alone; with less, the whole crown is used and it is "
                    "warned (empty: the default value, shown)", options=_FIELD)
    max_residual_m: StringProperty(  # type: ignore[valid-type]
        name="Maximum residual (m)",
        description="Distance to the plane from which a cell of the crown is left out of the fit, in metres (empty: the default value, "
                    "shown)", options=_FIELD)
    fit_rounds: StringProperty(  # type: ignore[valid-type]
        name="Rounds of the fit",
        description="How many times the plane is fitted leaving out the cells that do not fit it: a whole number (empty: the default "
                    "value, shown)", options=_FIELD)
    turns: StringProperty(  # type: ignore[valid-type]
        name="Rounds of plane and footprint",
        description="How many times the plane and the footprint are repeated until the footprint does not change: a whole number (empty: "
                    "the default value, shown)", options=_FIELD)
    tilt_max_deg: StringProperty(  # type: ignore[valid-type]
        name="Maximum tilt of the plane (°)",
        description="Tilt of the base plane from which it is limited, in degrees: a hypothesis that is warned and recorded (empty: the "
                    "default value, shown)", options=_FIELD)
    support_quantile: StringProperty(  # type: ignore[valid-type]
        name="Support quantile",
        description="Quantile of the residuals of the crown the limited plane rests on, from 0 to 1: a hypothesis (empty: the default "
                    "value, shown)", options=_FIELD)
    open_diameter_m: StringProperty(  # type: ignore[valid-type]
        name="Opening diameter (m)",
        description="Diameter of the disc of the morphological opening that finds the candidates, in metres (empty: the default value, "
                    "shown)", options=_FIELD)
    min_height_m: StringProperty(  # type: ignore[valid-type]
        name="Minimum height of a candidate (m)",
        description="How much a zone has to stand out from the opening to be a candidate, in metres (empty: the default value, shown)",
        options=_FIELD)
    min_area_m2: StringProperty(  # type: ignore[valid-type]
        name="Minimum area of a candidate (m²)",
        description="Smallest area of a candidate, in square metres (empty: the default value, shown)", options=_FIELD)
    max_area_m2: StringProperty(  # type: ignore[valid-type]
        name="Maximum area of a candidate (m²)",
        description="Largest area of a candidate, in square metres (empty: the default value, shown)", options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con el avance y Esc: los pone invoke; desde un
    # guion, sin ellos, de una vez. «Vista previa» de las marcas (T32): la pone el botón del diálogo. Una detección no retira nada ni deja una
    # pared: no pide más confirmación que Crear.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    preview: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Con ``confirm``, el diálogo de crear el cálculo abierto. Si no, las listas leídas de nuevo (las superficies del proyecto y de la
        versión activa, **también sin versión activa**: D-15, y las capas de polígonos), la propuesta (un nombre, la primera capa con sus
        campos y el terreno) y el diálogo del cálculo: Intro calcula. Sin ninguna superficie o ninguna capa de polígonos, lo dice."""
        self.provenance_dialog = True
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            return self._confirmation(context)
        project = SESSION.project
        try:
            des_panels.refresh_choices(project)
            if not des_panels.has_surfaces():
                self.report({"ERROR"}, tr("There is no surface in the project: import the ground or a survey first"))
                return {"CANCELLED"}
            if not any(item[0] != des_panels.NO_LAYER for item in des_panels.layer_items(None, None)):
                self.report({"ERROR"}, tr("There is no layer of polygons in the project: import the marks of the stockpiles first"))
                return {"CANCELLED"}
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label), confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 016 §5.3.3): un nombre que no repite el de ninguna entidad del
        proyecto ni de la versión («Acopios», «Acopios 2»…), **la primera capa de polígonos con los campos que tiene** (:data:`MARK_FIELDS`)
        y el terreno (``surface_proposal.ground_item``, con lo seleccionado en la vista). Los umbrales **no se proponen**: vacíos son su valor
        por defecto, que el diálogo enseña con su tipo (D-3)."""
        given = self.properties.is_property_set
        if not given("layer"):
            self.layer = [item[0] for item in des_panels.layer_items(None, None) if item[0] != des_panels.NO_LAYER][0]
            _propose_mark_fields(self, context)
        if not self.name.strip():
            taken, number = _taken_entity_names(project), 1
            proposal = base = tr("Stockpiles")
            while proposal in taken:
                number += 1
                proposal = f"{base} {number}"
            self.name = proposal
        if not given("surface"):
            items = [identifier for identifier, _name, _about in des_panels.surface_items(None, None) if identifier != des_panels.NO_ZONE]
            ground = surface_proposal.ground_item(context, project, items, des_panels.surface_choice) if items else None
            if ground is not None:
                self.surface = ground

    def draw(self, context: Any) -> None:
        """Arriba el nombre y la superficie; la capa de marcas con sus campos; si busca candidatos; **los umbrales de D-3, cada uno con su valor
        por defecto y su tipo** (ADOPTADO o HIPÓTESIS) y, abajo, «Vista previa» de las marcas (RF-016-23). En la confirmación de crear, el
        resumen."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "surface", text=tr("Surface"), translate=False)
        box = layout.box()
        box.label(text=tr("Marks of the stockpiles"), translate=False)
        box.prop(self, "layer", text=tr("Layer"), translate=False)
        box.prop(self, "name_field", text=tr("Name field"), translate=False)
        box.prop(self, "margin_field", text=tr("Margin field"), translate=False)
        box.prop(self, "material_field", text=tr("Material field"), translate=False)
        box.prop(self, "base_field", text=tr("Base surface field"), translate=False)
        layout.prop(self, "candidates", text=tr("Look for candidates"), translate=False)
        rows = [("margin_m", "margin_m", tr("Margin around the mark (m)")),
                ("crown_inner_m", "crown_inner_m", tr("Inner distance of the crown (m)")),
                ("crown_outer_m", "crown_outer_m", tr("Outer distance of the crown (m)")),
                ("crown_slope_deg", "crown_slope_deg", tr("Slope of the flat terrain (°)")),
                ("crown_flat_min_m2", "crown_flat_min_m2", tr("Minimum flat area of the crown (m²)")),
                ("max_residual_m", "max_residual_m", tr("Maximum residual (m)")),
                ("fit_rounds", "fit_rounds", tr("Rounds of the fit")),
                ("turns", "turns", tr("Rounds of plane and footprint")),
                ("tilt_max_deg", "tilt_max_deg", tr("Maximum tilt of the plane (°)")),
                ("support_quantile", "support_quantile", tr("Support quantile"))]
        if self.candidates:
            rows += [("open_diameter_m", "open_diameter_m", tr("Opening diameter (m)")),
                     ("min_height_m", "min_height_m", tr("Minimum height of a candidate (m)")),
                     ("min_area_m2", "min_area_m2", tr("Minimum area of a candidate (m²)")),
                     ("max_area_m2", "max_area_m2", tr("Maximum area of a candidate (m²)"))]
        box = layout.box()
        box.label(text=tr("Thresholds of the detection: empty is the value shown"), translate=False)
        for prop, param, label in rows:
            row = box.row()
            row.prop(self, prop, text=label, translate=False)
            row.label(text=_threshold_text(param), translate=False)
        _draw_entity_preview_button(layout, self, DETECT_STOCKPILES, _stockpile_fields())  # «Vista previa» de las marcas (RF-016-23)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self) -> design_model.StockpileRequest:
        """Lo pedido en el diálogo como la ``design.model.StockpileRequest`` (RF-016-02, RF-016-08), comprobado sin escribir ni calcular nada.
        Un umbral vacío es **su valor por defecto**: lo resuelve el dominio con su procedencia (D-3: la petición no lleva ninguna cifra
        minera). :class:`ComputeFormError` si falta algo del diálogo."""
        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the detection"))
        if self.layer in ("", des_panels.NO_LAYER):
            raise ComputeFormError(tr("Choose the layer of the marks of the stockpiles"))
        if self.surface in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the surface the stockpiles are detected on"))

        def number(prop: str, label: str) -> float | None:
            return typed_number(getattr(self, prop), label)

        def whole(prop: str, label: str) -> int | None:
            typed = number(prop, label)
            if typed is None:
                return None
            if typed != int(typed):
                raise ComputeFormError(tr("«{value}» is not a whole number (field «{field}»)", value=getattr(self, prop).strip(), field=label))
            return int(typed)

        fields = design_model.StockpileFields(
            self.layer, name_field=self.name_field.strip() or None, margin_field=self.margin_field.strip() or None,
            material_field=self.material_field.strip() or None, base_field=self.base_field.strip() or None)
        return design_model.StockpileRequest(
            name, fields, self.surface, candidates=self.candidates,
            margin_m=number("margin_m", tr("Margin around the mark (m)")),
            crown_inner_m=number("crown_inner_m", tr("Inner distance of the crown (m)")),
            crown_outer_m=number("crown_outer_m", tr("Outer distance of the crown (m)")),
            crown_slope_deg=number("crown_slope_deg", tr("Slope of the flat terrain (°)")),
            crown_flat_min_m2=number("crown_flat_min_m2", tr("Minimum flat area of the crown (m²)")),
            max_residual_m=number("max_residual_m", tr("Maximum residual (m)")),
            fit_rounds=whole("fit_rounds", tr("Rounds of the fit")), turns=whole("turns", tr("Rounds of plane and footprint")),
            tilt_max_deg=number("tilt_max_deg", tr("Maximum tilt of the plane (°)")),
            support_quantile=number("support_quantile", tr("Support quantile")),
            open_diameter_m=number("open_diameter_m", tr("Opening diameter (m)")),
            min_height_m=number("min_height_m", tr("Minimum height of a candidate (m)")),
            min_area_m2=number("min_area_m2", tr("Minimum area of a candidate (m²)")),
            max_area_m2=number("max_area_m2", tr("Maximum area of a candidate (m²)")))

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Con ``preview``, activa la vista previa de las marcas
        (:meth:`_show_preview`). Si no, comprueba lo pedido (sin escribir nada si falta algo), decide el **ámbito** (D-15: del proyecto si la
        superficie lo es, **también sin versión activa**; de la versión si es de una), pasa por la puerta de la 008 con el tipo de operación
        de ese ámbito y calcula la detección por pasos con ``design.steps.stockpile_run`` —compila las máscaras antes si la versión no las
        tiene al día—, sin registrar nada (RF-015-03): desde la interfaz, en el modal con el avance y Esc (RF-015-29, RNF-016-05); desde un
        guion, de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los rechazos (la capa, sus campos y marcas
        solapadas, la superficie, los umbrales, el nombre repetido) y todas las cuentas son de ``design``."""
        if self.confirm:
            return self._create(context)
        if self.preview:
            return self._show_preview()
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        from ...design import stockpile_store  # al usarlo: habilitar no carga el cálculo

        project = SESSION.project
        active = scene_versions.active_version() or None
        try:
            request = self._request()
            scope, _found = stockpile_store.detection_scope(project, request, active)
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        of_version = scope == stockpile_store.VERSION
        ready = ensure_ready(provenance.STOCKPILE_DETECT if of_version else provenance.STOCKPILE_DETECT_PROJECT, [], report=self.report,
                             dialog=self.provenance_dialog, version=active if of_version else None)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.stockpile_run(project, request, version=active, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _show_preview(self) -> set[str]:
        """«Vista previa» (T35, con lo de la T32; RF-016-23): comprueba lo pedido como al calcular (:meth:`_request`, sin escribir ni calcular
        nada) y activa con ello la vista previa de las marcas con su margen (``bl.draw.entity``: el contorno de cada marca y el de la marca
        ampliada, con su nombre, margen, material y base y su leyenda); la que hubiera activa se cambia por la nueva (pulsarlo otra vez, o
        cambiar un campo del diálogo: :func:`_refresh_stockpile_preview`). Vale **sin versión activa** (la detección de una superficie del
        proyecto, D-15). Lo que rechazaría «Calcular» de la capa o de las marcas sale en la propia vista previa, como aviso. Se quita al cancelar
        la orden, al Esc a mitad del cálculo, al crear la detección, con su control y al conmutar a la interfaz de Blender."""
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        try:
            request = self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        preview = _entity_preview()
        try:
            preview.enable(preview.EntityPlan(stockpile=request))
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr("The preview of the entity could not be shown: {detail}", detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of the marks of the detection «{name}»", name=request.name))
        return {"FINISHED"}

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-016-02, RF-015-02): **desde la interfaz, por pasos** (T44; RNF-016-03: escribir las cuatro rejillas dispersas de 2,81
        M celdas de una vez era una sola llamada de ≈ 1 s del hilo de Blender): el modal de pasos de ``Calculation.create_steps`` —cada
        evento, una llamada de ≤ 0,2 s— con la transacción final como último paso (:meth:`_creation_steps`); Esc entre pasos no deja nada a
        medias (RNF-016-05). Desde un guion (sin ventana), de una vez, como las demás (:meth:`_CalculateAndCreate._create`: una transacción);
        el resultado es el mismo, bit a bit. **Ya creada**, quita la vista previa de las marcas (RF-016-23: la detección ya existe, ya no se
        prepara) y, si es **de una versión**, encadena lo que sigue (:meth:`_update_declared`: la capa de entidades de la versión, y la
        declaración y las máscaras como en toda orden de entidades). La del proyecto no sale en ninguna capa de versión ni declara nada (D-15,
        D-1): no encadena nada."""
        from ...design import stockpile_store  # al usarlo: habilitar no carga el cálculo

        opened = calculation()
        if (opened is not None and self.in_steps and getattr(context, "window", None) is not None
                and isinstance(opened.entity, stockpile_store.PreparedDetection)):
            project = SESSION.project
            self._project, self._name, self._creating = project, opened.name, True
            self._start(context, self._creation_steps(project, opened))
            return {"RUNNING_MODAL"}
        created = _CalculateAndCreate._create(self, context)
        if opened is None or "FINISHED" not in created:
            return created
        _entity_preview_off()
        if opened.op_type != provenance.STOCKPILE_DETECT:
            return created
        return self._update_declared(context, opened)

    _creating = False
    """Si los pasos que corren son los de crear la detección (y no los de calcularla ni los de lo que sigue a crearla)."""

    def _creation_steps(self, project: Any, opened: Calculation) -> Iterator[Progress]:
        """Los pasos de «Crear» la detección ``opened`` en el modal (T44; RNF-016-03, RNF-016-05): los de ``Calculation.create_steps``
        (cada tabla y cada rejilla dispersa, montada y escrita en su temporal por pasos; la transacción final, el último) y, en cuanto lo
        guardado llega, **lo que sigue a crearla en el mismo modal**: lo registrado (:meth:`_CalculateAndCreate._registered`), la vista
        previa quitada y, si la detección es **de una versión**, los pasos de ``entity_store.after_entity_change`` (:meth:`_update_declared`,
        pero sin otro modal). La del proyecto acaba con el paso que lleva lo guardado. Cerrar los pasos antes (Esc) o un fallo no dejan nada:
        ``create_steps`` descarta el cálculo y borra sus temporales."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        created = None
        creating = opened.create_steps(budget_s=self.STEP_BUDGET_S)
        try:
            for step in creating:
                if step.result is not None:
                    created = step
                    break
                yield step
        finally:
            creating.close()
        assert created is not None  # los pasos acaban siempre con lo guardado
        self._registered(opened)
        _entity_preview_off()
        if opened.op_type != provenance.STOCKPILE_DETECT:
            yield created  # la del proyecto no encadena nada (D-15, D-1): lleva lo guardado
            return
        self._creating, self._chain = False, True
        yield from entity_store.after_entity_change(project, opened.version, budget_s=self.STEP_BUDGET_S)

    # --- Lo que sigue a crearla (RF-015-10, RF-015-27; plan 016 §5.3.2) -------------------------

    _chain = False
    """Si los pasos que corren son los de lo que sigue a crear la detección (y no los de calcularla)."""

    def _update_declared(self, context: Any, opened: Calculation) -> set[str]:
        """Tras crear la detección **de una versión**, **pone al día** lo que sigue a toda orden de entidades
        (``design.entity_store.after_entity_change``: repite la declaración de las restricciones de las entidades de la versión, recompila las
        máscaras si ya no están al día, dice qué quedó obsoleto y pone al día la **capa de entidades**, que ahora lleva **una fila por acopio**,
        T34), por pasos con el avance y Esc: la detección **ya está creada** (cada etapa es una operación y una transacción propias); cerrar o
        fallar a mitad deja las máscaras obsoletas con su causa y se compilan de nuevo antes de que un operador las use."""
        from ...design import entity_store  # al usarlo: habilitar no carga el cálculo

        project = SESSION.project
        self._chain = True
        steps = entity_store.after_entity_change(project, opened.version, budget_s=self.STEP_BUDGET_S)
        started = self._run_steps(context, project, opened.name, steps)
        return {"FINISHED"} if started == {"CANCELLED"} else started  # ya creada: el fallo está dicho

    def _finished(self, context: Any, opened: Any) -> set[str]:
        """Con los pasos de lo que sigue a crearla, dice lo que hizo (:meth:`_report_chain`); con los de crearla (la del proyecto, que no
        encadena nada), ya lo dijo al registrarla (:meth:`_creation_steps`); si no, como las demás órdenes."""
        if self._chain:
            self._chain = False
            self._report_chain(opened)
            return {"FINISHED"}
        if self._creating:
            self._creating = False
            return {"FINISHED"}
        return _CalculateAndCreate._finished(self, context, opened)

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        """Como las demás órdenes; al **crearla**, con el proyecto cerrado se para sin dejar nada y lo dice con sus palabras (no se calculaba:
        se guardaba)."""
        if self._creating and project_session.current() is not getattr(self, "_project", None):
            return self._fail(context, tr("The project was closed while the detection «{name}» was being saved: nothing has been left "
                                           "half-done", name=getattr(self, "_name", "")))
        return _CalculateAndCreate._result(self, context, step)

    def _after_stop(self, context: Any) -> None:
        """Tras cancelar (Esc) o fallar **al crearla**: ``create_steps`` ya descartó el cálculo y borró sus temporales; aquí se suelta (ya no está
        abierto) y se vacía su resumen. Tras cancelar lo que sigue a crearla, nada: la detección está creada."""
        if self._creating:
            self._creating = False
            discard_calculation()
            des_panels.show_summary(None)

    def _report_chain(self, chain: Any) -> None:
        """Lo que hizo ``chain`` (``design.entity_store.EntityChain``), en el informe y en el registro: la declaración, las máscaras
        recompiladas, lo que quedó obsoleto y, en alerta, lo que no se pudo hacer (RF-012-06)."""
        shown = i18n.language()
        for notice in chain.notices():
            self._report({"WARNING" if notice.severity == "warning" else "INFO"}, notice.text(shown))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()

    def _created_text(self, opened: Calculation) -> str:
        if opened.op_type == provenance.STOCKPILE_DETECT:
            return tr("Detection of stockpiles «{name}» created in {version}", name=opened.name, version=opened.version)
        return tr("Detection of stockpiles «{name}» created in the project", name=opened.name)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Detectando los acopios… 40 % · Esc: cancelar» o, tras crearla, «Poniendo al día las
        restricciones declaradas… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._chain:
            return tr("Updating the declared constraints and the masks… {percent} % · Esc: cancel", percent=percent)
        if self._creating:
            return tr("Saving the detection… {percent} % · Esc: cancel", percent=percent)
        return tr("Detecting the stockpiles… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._chain:
            return tr("Cancelled: the detection is created; the declared constraints and the masks are brought up to date before the next "
                      "operation that uses them, and the entity layer with the next entity order or «Recompute the stale results»")
        if self._creating:
            return tr("Creation cancelled: the detection has not been created and the calculation has been discarded; nothing has been "
                      "left half-done")
        return _CalculateAndCreate._cancelled_text(self)

    def _error_text(self, exc: GeoblenderError) -> str:
        found = _CalculateAndCreate._error_text(self, exc)
        if self._chain:
            return f"{found} " + tr("The detection is created: only the declared constraints and the masks have not been brought up to date")
        return found


@dataclass(frozen=True, slots=True)
class _Candidates:
    """Lo que enseña la ventana de «Candidatos de los acopios…»: la detección (``code``, ``name``), su ámbito (``version``: la versión de la
    detección o ``None`` si es **del proyecto**), la operación que la hizo (``operation_uid``) y sus candidatos como los guardó la operación
    (``rows``: una fila de ``des_stc_`` por candidato, :func:`design.stockpile_store.read_stored_rows`)."""

    code: str
    name: str
    version: Any
    operation_uid: str
    rows: tuple[Mapping[str, Any], ...]

    @property
    def op_type(self) -> str:
        """El tipo de operación de la detección: de la versión o del proyecto (D-15)."""
        return provenance.STOCKPILE_DETECT_PROJECT if self.version is None else provenance.STOCKPILE_DETECT


class GEOBLENDER_OT_des_stockpile_candidates(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """List the candidates of a detection of stockpiles with their footprint, area and volume, and convert each one into a stockpile or discard it with a reason; the detection is then recomputed"""

    bl_idname = STOCKPILE_CANDIDATES
    bl_label = "Candidates of the stockpiles…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.STOCKPILE_DETECT_PROJECT  # la detección puede ser del proyecto (sin versión activa): sin la puerta de versión

    detection: StringProperty(  # type: ignore[valid-type]
        name="Detection",
        description="Code or name of the detection of stockpiles (empty: the one of the object selected in the 3D view or, without it, the "
                    "only one that has candidates)", options=_FIELD)
    in_project: BoolProperty(  # type: ignore[valid-type]
        name="Of the project",
        description="The detection is of the project and not of the active version (a detection of a surface of the project)", default=False,
        options=_FIELD)
    candidate: StringProperty(  # type: ignore[valid-type]
        name="Candidate", description="Key of the candidate the decision is about (c01…): one of those of the list", options=_FIELD)
    action: EnumProperty(  # type: ignore[valid-type]
        name="Decision", description="What is done with the candidate", items=STOCKPILE_ACTION_ITEMS, default="CONVERT", options=_FIELD)
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why: it is recorded with the decision, who made it and when; it is needed to convert, discard or ask again",
        options=_FIELD)
    recompute: BoolProperty(  # type: ignore[valid-type]
        name="Recompute the detection",
        description="Repeat the detection with the decision as soon as it is made (otherwise it stays out of date until «Recompute the stale "
                    "results»)", default=True, options=_FIELD)
    rows: CollectionProperty(type=GEOBLENDER_PG_des_bring_row, options=_FIELD)  # type: ignore[valid-type]

    _listed = None  # lo que enseña la ventana (:class:`_Candidates`), leído al abrirla

    def _read(self, context: Any) -> _Candidates:
        """La detección pedida (``detection``; si no, la del objeto seleccionado en la vista; si no, la única con candidatos) con sus
        candidatos, leídos de la tabla de **su operación vigente** en una instantánea y sin escribir nada. La busca en la versión activa y, si
        no está o es ``in_project``, en el proyecto. :class:`ValueError` si no hay proyecto o detección, si hay varias sin decir cuál o si no
        tiene lista de candidatos."""
        from ...design import entities, entity_store, stockpile_store  # al usarlo: habilitar no carga el cálculo

        project, active = SESSION.project, scene_versions.active()
        if project is None:
            raise ValueError(tr("Open a project"))
        given, of_project = self.detection.strip(), self.in_project
        if not given:
            code, owner = _selected_entity(context)
            if code:
                given, of_project = code, not owner
        with project.read() as conn:
            conn.execute("BEGIN")
            try:
                found: list[tuple[Any, Any]] = []
                scopes = [(None, entities.project_registry(project, conn=conn))] if of_project else [
                    *([(active, entities.registry(project, active.uid, conn=conn))] if active is not None else []),
                    (None, entities.project_registry(project, conn=conn))]
                for scope, listed in scopes:
                    for entry in listed:
                        if entry.record.kind != entities.EntityKind.STOCKPILE or entry.operation_uid is None:
                            continue
                        if not given or given in (entry.record.code, entry.record.name):
                            found.append((scope, entry))
                    if given and found:
                        break
                with_rows = []
                for scope, entry in found:
                    table = entity_store.operation_table(conn, entry.operation_uid, provenance.STOCKPILE_CANDIDATES_ROLE)
                    rows = () if table is None else stockpile_store.read_stored_rows(
                        conn, provenance.STOCKPILE_CANDIDATES_TABLE, table)
                    if rows or given:
                        with_rows.append(_Candidates(entry.record.code, entry.record.name, scope, str(entry.operation_uid), tuple(rows)))
            finally:
                conn.execute("ROLLBACK")
        if given and not with_rows:
            raise ValueError(tr("«{entity}» is not a detection of stockpiles of the project or of the active version", entity=given))
        if not with_rows:
            raise ValueError(tr("There is no detection with candidates: detect the stockpiles asking for the candidates first"))
        if len(with_rows) > 1 and not given:
            raise ValueError(tr("There is more than one detection with candidates: select the object of one or give its code"))
        found_one = with_rows[0]
        if not found_one.rows:
            raise ValueError(tr("The detection «{name}» has no candidates: it was detected without asking for them, or none passed the "
                                "filters", name=found_one.name))
        return found_one

    def _lines(self) -> list[tuple[str, bool, tuple[str, str, str], str]]:
        """Las filas de la ventana: por candidato, su texto (su clave, su huella, su volumen y su plano, y su estado: pendiente, convertido o
        descartado con su motivo, quién y cuándo), si pide una decisión, el lugar de «Ir a» y su clave."""
        from ...design import stockpile_store  # al usarlo: habilitar no carga el cálculo

        found = self._listed
        assert found is not None
        shown, lines = i18n.language(), []
        for row in found.rows:
            text = stockpile_store.candidate_row_notice(row).text(shown)
            state, reason = row["state"], row["reason"] or ""
            if state == "converted":
                text += " · " + tr("Converted into a stockpile: {reason} ({person}, {date})", reason=reason,
                                   person=row["decided_by"] or "", date=row["decided_on"] or "")
            elif state == "discarded":
                text += " · " + tr("Discarded: {reason} ({person}, {date})", reason=reason, person=row["decided_by"] or "",
                                   date=row["decided_on"] or "")
            else:
                text += " · " + tr("Pending")
            lines.append((text, state not in ("converted", "discarded"),
                          constraint_panels.place_of(float(row["x"]), float(row["y"]), float(row["area_m2"])), str(row["key"])))
        return lines

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre la ventana con los candidatos de la detección (con su estado y «Ir a» cada uno), propone el primero **pendiente** (o el que dio
        quien la lanzó: los botones de la barra N) y pide la decisión con su motivo; no escribe nada. Con ``action`` «Ir a» y un candidato,
        encuadra la vista sin abrir nada. Sin detección o sin candidatos, lo dice."""
        self.provenance_dialog = True
        try:
            self._listed = self._read(context)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        found = self._listed
        self.detection, self.in_project = found.code, found.version is None
        if self.action == "GO_TO" and self.candidate.strip():
            return self.execute(context)
        self.rows.clear()
        for text, _alert, _place, key in self._lines():
            row = self.rows.add()
            row.name, row.label = key, text
        pending = [str(row["key"]) for row in found.rows if row["state"] not in ("converted", "discarded")]
        keys = [str(row["key"]) for row in found.rows]
        if self.candidate.strip() not in keys:
            self.candidate = (pending or keys)[0]
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Candidates of «{name}»", name=found.name), confirm_text=tr("Apply"))

    def draw(self, context: Any) -> None:
        """La detección y su ámbito, **la lista de candidatos** con su huella, área y volumen, su estado y «Ir a», y, debajo, el candidato, la
        decisión (convertir, descartar o volver a preguntar), su motivo y si se recalcula la detección."""
        layout = self.layout
        found = self._listed
        if found is None:
            return
        layout.label(text=tr("Detection «{name}» ({code}) of the project", name=found.name, code=found.code) if found.version is None
                     else tr("Detection «{name}» ({code}) of {version}", name=found.name, code=found.code,
                             version=getattr(found.version, "code", "")), translate=False)
        box = layout.box()
        for text, alert, (x, y, radius), _key in self._lines():
            row = box.row()
            des_panels.draw_wrapped(row.column(), text, DIALOG_WIDTH - 90, alert=alert)
            button = row.operator(constraint_panels.GO_TO_PLACE, text=tr("Go to"), translate=False)
            button.x, button.y, button.radius = x, y, radius
        layout.prop_search(self, "candidate", self, "rows", text=tr("Candidate"), translate=False)
        layout.prop(self, "action", text=tr("Decision"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)
        layout.prop(self, "recompute", text=tr("Recompute the detection"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """«Ir a» (``action`` ``GO_TO``): encuadra la vista en el candidato y no cambia nada. Si no, **decide** sobre el candidato
        (``design.stockpile_store.decide_candidate``: convertir, descartar o volver a preguntar, siempre con su motivo; es un cambio del
        parámetro ``decisions`` de la detección, con su decisor y su fecha) y, con ``recompute``, **recalcula la detección** con la decisión
        aplicada (:func:`bpy.ops.geoblender.core_recompute_stale` de esa operación: por pasos, con el avance y Esc; sin él, queda obsoleta
        hasta «Recalcular lo obsoleto»). Los rechazos (sin candidato, sin motivo, un candidato que no está, el proyecto en solo lectura) no
        escriben nada."""
        blocked = None if self.action == "GO_TO" else write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        from ...design import stockpile_store  # al usarlo: habilitar no carga el cálculo

        try:
            found = self._listed = self._read(context)
            key = self.candidate.strip()
            if not key:
                raise ValueError(tr("Choose the candidate"))
            row = next((item for item in found.rows if str(item["key"]) == key), None)
            if row is None:
                raise ValueError(tr("«{candidate}» is not a candidate of «{name}»", candidate=key, name=found.name))
            if self.action == "GO_TO":
                x, y, radius = constraint_panels.place_of(float(row["x"]), float(row["y"]), float(row["area_m2"]))
                return {"FINISHED"} if bpy.ops.geoblender.core_go_to_place("EXEC_DEFAULT", x=x, y=y, radius=radius) == {"FINISHED"} \
                    else {"CANCELLED"}
            if not self.reason.strip():
                raise ValueError(tr("Write the reason of the decision: it is recorded with it"))
            project = SESSION.project
            stockpile_store.decide_candidate(project, found.code, key, _DECISION_STATES[self.action], self.reason, version=found.version,
                                             decided_by=project.session.user_host)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.OPERATION, found.op_type)  # Ctrl+Z no lo deshace
        self.report({"INFO"}, tr("Decision recorded on the candidate «{candidate}» of «{name}»: the detection is out of date until it is "
                                 "recomputed", candidate=key, name=found.name))
        if ui_provenance.refresh(force=True):
            ui_provenance.redraw()
        if self.recompute:
            if getattr(context, "window", None) is None:
                self.report({"WARNING"}, tr("It is not recomputed here: use «Recompute the stale results» from a Blender window"))
            else:
                bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT", scope="ITEM", subject_uid=found.operation_uid)
        return {"FINISHED"}


class GEOBLENDER_OT_des_edit_stockpile(DesignCommandAware, ProvenanceAwareOperator, bpy.types.Operator):
    """Detect the stockpiles of a layer of marks or remove one already detected: it opens the order you choose"""

    bl_idname = EDIT_STOCKPILE
    bl_label = "Stockpile (detect, remove)…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.STOCKPILE_DETECT_PROJECT  # detectar puede ser del proyecto (D-15): sin la puerta de versión

    mode: EnumProperty(  # type: ignore[valid-type]
        name="What to do",
        description="Detect the stockpiles of a layer of marks, or remove one of those already detected in the active version or in the project",
        items=STOCKPILE_MODE_ITEMS, default="DETECT", options=_FIELD)

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Abre el diálogo con lo que se puede hacer (detectar o retirar) y propone **retirar** si ya hay acopios detectados que se puedan retirar
        (los de la versión activa y del proyecto) y **detectar** si no; no escribe nada."""
        self.provenance_dialog = True
        project = SESSION.project
        if not self.properties.is_property_set("mode"):
            try:
                des_panels.refresh_removal_choices(project)
            except (GeoblenderError, sqlite3.Error, OSError, ValueError):
                LOGGER.debug("No se pudieron leer los acopios que se pueden retirar", exc_info=True)
            self.mode = "REMOVE" if des_panels.has_removal_stockpiles() else "DETECT"
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(EDIT_STOCKPILE)].label), confirm_text=tr("Continue"))

    def draw(self, context: Any) -> None:
        """Las dos opciones y lo que hace la elegida."""
        layout = self.layout
        layout.prop(self, "mode", expand=True)
        layout.label(text=tr("It opens the detection of stockpiles: their marks, the surface and the thresholds.") if self.mode == "DETECT"
                     else tr("It opens the removal of a stockpile: the stockpile, the start surface and the transition."), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Abre la orden elegida (**«Detectar acopios…»**, :data:`DETECT_STOCKPILES`, o **«Retirar un acopio…»**, :data:`REMOVE_STOCKPILE`) en
        cuanto acaba ésta (un diálogo no se abre desde dentro de otro); no escribe nada. Cada una dice por sí misma lo que le falta (la
        retirada pide una versión activa y una detección)."""
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        _invoke_later(REMOVE_STOCKPILE if self.mode == "REMOVE" else DETECT_STOCKPILES, getattr(context, "window", None) or _first_window())
        return {"FINISHED"}


# --- Pista… (spec 017, T29b; HU-017-1, HU-017-2, HU-017-4; RF-017-29, RF-017-02, RF-017-17, RF-017-22, RF-015-28; plan 017 §5.3.3 y §5.5; comprobación manual M1) --------

CREATE_ROAD = provenance.ROAD_COMMAND
ROAD_MODE_ITEMS = [
    ("TRACE", "Trace", "From an origin to a destination: the axis and the level profile come out of the search of the route"),
    ("ON_AXIS", "Over an axis", "A line in plan of a layer of the project: the curves are fitted to it and the level profile is given"),
    ("AXIS_3D", "3D axis", "A line with its Z of a layer of the project: its Z is the level profile, which is only checked and engraved")]
"""El modo de la pista (``design.road_model.RoadMode``; RF-017-02): «trazar», «sobre un eje» y «eje 3D»."""
ROAD_ORIGIN_ITEMS = [
    ("POINT", "A point of the layer", "The origin is a point of the layer of points"),
    ("ROAD", "The axis of another road", "The origin is a point of the axis of another road of the active version, at an abscissa")]
"""De dónde sale el origen de «trazar» (RF-017-02, RF-017-03)."""
ROAD_DESTINATION_ITEMS = [
    ("POINT", "A point of the layer", "The destination is a point of the layer of points"),
    ("ENTITY", "A platform", "The destination is the point of the layer that falls on the footprint of a platform of the active version"),
    ("LEVEL", "An elevation with its zone", "The ramp: the road ends where it reaches an elevation inside a zone, with its arrival tolerance")]
"""A dónde llega «trazar»: un punto de la capa, una plataforma o una cota con su zona y su tolerancia (RF-017-02, RF-017-03, D-4)."""
_ROAD_HIDDEN = frozenset({"confirm", "in_steps", "preview", "confirm_mean", "confirm_carriageway", "code"})
"""Las propiedades ocultas de «Pista…»: las pone quien la lanza (o su ventana de confirmar)."""


def _route_rows() -> tuple[tuple[str, str, str], ...]:
    """Los nueve parámetros de la ruta de «trazar» (RF-017-10): la propiedad del diálogo, el valor de ``RoadRequest`` (y de ``des.road.{e}.*``) y su etiqueta en el
    idioma de Geoblender. Ocho son HIPÓTESIS sin valor por defecto (D-10, D-11) y el presupuesto de estados lo tiene (P-3): el diálogo dice el tipo de cada uno."""
    return (("mesh", "mesh_m", tr("Mesh of the route (m)")), ("level_step", "level_step_m", tr("Elevation step (m)")),
            ("max_cut_fill", "max_cut_fill_m", tr("Maximum cut and fill height (m)")),
            ("lambda_weight", "lambda_per_m", tr("Weight of the earthworks (1/m)")), ("turn", "turn_m", tr("Turn penalty (m)")),
            ("margin", "margin_m", tr("Margin of the corridor (m)")), ("simplify", "simplify_m", tr("Simplification tolerance (m)")),
            ("arrival_tol", "arrival_tol_m", tr("Arrival tolerance of the route (m)")), ("search_budget", "search_budget", tr("Budget of states")))


def _route_text(param: str) -> str:
    """Lo que dice el diálogo de «Pista…» de un parámetro de la ruta (RF-017-10, D-10, D-11): **su tipo** (el de su familia) y, si lo tiene, su valor por defecto:
    «HIPÓTESIS: sin valor por defecto, lo elige usted» o «Por defecto: 5.000.000 · ADOPTADO». Ninguno se propone: vacío es el valor por defecto o, si no lo tiene,
    el rechazo del cálculo con su nombre."""
    return _entity_param_text("road", param)


def _entity_param_text(entity: str, param: str) -> str:
    """El tipo (y, si lo tiene, el valor por defecto) del parámetro ``param`` de las entidades del tipo ``entity`` (``road``, ``access``…) como lo dicen los diálogos de la 017: lo de
    :func:`_route_text` y de :func:`_access_text` (D-10, D-11, D-17)."""
    template = design_params.entity_params(entity).template(param)
    kind = tr("ASSUMPTION") if template.kind == ParamKind.HIPOTESIS else tr("ADOPTED")
    if template.default is None:
        return tr("{kind}: no default value, you choose it", kind=kind)
    value = float(template.default)  # type: ignore[arg-type]
    return tr("By default: {value}{unit} · {kind}", value=i18n.format_number(value, 0 if value.is_integer() else 2), unit="", kind=kind)


def _road_entity_request(project: Any, version: str, code: str) -> Any:
    """La petición de la pista **sin calcular** ``code`` de la versión ``version`` (T33c; RF-015-18; la duda T22b (d); ``design.road_store.entity_road_request``: de los parámetros que ya tiene la
    versión y de su nombre, como la repite el recálculo; solo lee)."""
    from ...design import road_store  # al usarlo: habilitar no carga el cálculo

    return road_store.entity_road_request(project, version, code)


def _road_dialog_fields() -> tuple[str, ...]:
    """Los campos del diálogo de «Pista…» que pasan a su vista previa: sus propiedades no ocultas (la del motivo de la pendiente media es de la confirmación)."""
    return tuple(name for name in GEOBLENDER_OT_des_create_road.__annotations__ if name not in _ROAD_HIDDEN and name != "mean_reason")


def _refresh_road_preview(self: Any, _context: Any) -> None:
    """El ``update`` de cada campo de «Pista…» (T29b; RF-017-26, RF-015-26): con la vista previa **de esa pista** activa (la de una pista de la versión no), la
    redibuja con lo que dice ahora el diálogo (``EntityPlan(road=RoadAsk(request=…))``: antes de calcular, el origen, el destino y el pasillo). Un diálogo a
    medias (un campo sin escribir, un número que no lo es) no la cambia: sigue la última completa. Solo lee."""
    _redraw_road_preview(self, GEOBLENDER_OT_des_create_road._request)


def _redraw_road_preview(self: Any, build: Callable[[Any], Any], *, propose: bool = False) -> None:
    """Lo de :func:`_refresh_road_preview` con la petición que arma ``build`` de lo que dice el diálogo ``self`` (su ``_request``: la de «Pista…» o la de «Proponer el trazado…», T33: el origen, el destino y
    el pasillo de la ruta). ``propose``: es la vista previa de **una propuesta** del trazado (T44, D-1), no la de una pista: la que está activa ha de ser de la misma clase."""
    loaded = _entity_preview_loaded()
    if loaded is None or not loaded.enabled() or loaded.plan() is None or loaded.plan().road is None or loaded.plan().road.request is None or loaded.plan().road.propose != propose:
        return
    from ...design.preview import RoadAsk  # al usarlo: habilitar no carga el cálculo

    try:
        request = build(self)
    except (ProfileFormError, GeoblenderError, sqlite3.Error, OSError, ValueError):
        return
    if loaded.plan().road.request == request:
        return  # lo mismo que ya se dibuja, con o sin lo calculado (lo repite cada dibujo del diálogo al copiar sus campos al botón): no se reconstruye
    loaded.replace(loaded.EntityPlan(road=RoadAsk(request=request, propose=propose)))


def _show_calculated_preview(opened: Any, *, propose: bool) -> None:
    """Con la vista previa **activa de esta clase** (la de una pista o la de una propuesta del trazado: ``propose``), la cambia por la de lo que dejó «Calcular» (``opened``: el cálculo abierto; con ``propose``,
    la :class:`~...design.road_store.PreparedProposal` y el ``ProposalOutcome``): el eje con su rasante (T28; T44, D-1: también el de la propuesta). Solo lee."""
    loaded = _entity_preview_loaded()
    if loaded is None or not loaded.enabled() or loaded.plan() is None or loaded.plan().road is None or loaded.plan().road.request is None or loaded.plan().road.propose != propose:
        return
    from ...design.preview import RoadAsk  # al usarlo: habilitar no carga el cálculo

    loaded.replace(loaded.EntityPlan(road=RoadAsk(request=opened.entity.job.request, prepared=opened.entity, outcome=opened.outcome, propose=propose)))


def _road_mode_changed(self: Any, context: Any) -> None:
    """El ``update`` del modo de «Pista…»: la lista de capas es otra (puntos, líneas o líneas con Z), y si la elegida no está en ella, pasa a la primera; después
    redibuja la vista previa (:func:`_refresh_road_preview`)."""
    layers = [item[0] for item in des_panels.road_layers(self.mode)]
    if layers and self.layer not in layers:
        self.layer = layers[0]
    _refresh_road_preview(self, context)


def _road_points(self: Any) -> dict[str, Any]:
    """El origen y el destino de «trazar» de lo que dice el diálogo ``self`` (sus propiedades: la llaman también los ``update``, que reciben solo las propiedades de la orden) como los pide ``RoadRequest`` (RF-017-02, RF-017-03): ``origin`` y ``destination`` (el texto de un punto de la capa, de un
    punto del eje de otra pista —``RDW-001@100.5``— o de una plataforma —``entity:PLT-001``—) o, con una cota, ``dest_level_m``, ``dest_tol_m`` y ``dest_zone`` (la
    capa de su zona y, tras ``:``, el polígono). :class:`ComputeFormError` si falta la pista, la abscisa o la plataforma elegidas."""
    from ...design import entities  # al usarlo: habilitar no carga las entidades

    found: dict[str, Any] = {}
    if self.origin_from == "ROAD":
        if self.origin_road in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the road whose axis the origin is on"))
        station = typed_number(self.origin_station, tr("Abscissa of the origin (m)"))
        if station is None:
            raise ComputeFormError(tr("Write the abscissa of the origin on the axis of the other road, in metres"))
        found["origin"] = f"{self.origin_road}@{station!r}"
    else:
        found["origin"] = self.origin_point.strip() or None
    if self.destination_to == "LEVEL":
        level = typed_number(self.dest_level, tr("Elevation of the destination (m)"))
        tolerance = typed_number(self.dest_tol, tr("Arrival tolerance of the elevation (m)"))
        zone = None if self.dest_zone in ("", des_panels.NO_LAYER) else self.dest_zone
        if level is None and tolerance is None and zone is None:
            raise ComputeFormError(tr("Write the elevation of the destination, its arrival tolerance and choose its zone"))
        feature = self.dest_zone_feature.strip()
        found.update(dest_level_m=level, dest_tol_m=tolerance, dest_zone=None if zone is None else (f"{zone}:{feature}" if feature else zone))
    elif self.destination_to == "ENTITY":
        if self.destination_entity in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the platform the road ends at"))
        found["destination"] = entities.surface_ref(self.destination_entity)
    else:
        found["destination"] = self.destination_point.strip() or None
    return found


def _route_changes(self: Any) -> dict[str, Any]:
    """Los nueve parámetros de la ruta de lo que dice el diálogo ``self`` (de «Pista…» en «trazar» y de «Proponer el trazado…»; RF-017-10) como los pide ``RoadRequest``: cada uno tecleado con coma o punto
    decimal, **vacío sin cifra** (lo rechaza el cálculo con su nombre, RF-015-08) y el presupuesto de estados, un número entero (``ComputeFormError`` si no lo es)."""
    changes: dict[str, Any] = {}
    for prop, param, label in _route_rows():
        number = typed_number(getattr(self, prop), label)
        if param == "search_budget" and number is not None:
            if number != int(number):
                raise ComputeFormError(tr("«{value}» is not a whole number (field «{field}»)", value=getattr(self, prop).strip(), field=label))
            number = int(number)
        changes[param] = number
    return changes


def _propose_trace_values(self: Any, context: Any, project: Any) -> None:
    """Lo que proponen los diálogos de «Pista…» y de «Proponer el trazado…» si quien los lanza no lo dio (plan 017 §5.3.3): la primera capa del modo, el primer perfil, la primera pista, plataforma y zona que
    ofrecen y **la partida: la superficie de explotación de la cantera de la 014 y, si no hay o ya parte de ella otra entidad, la última de la cadena** (RF-017-05, D-3) o, sin ninguna, el terreno
    (``surface_proposal.ground_item``, con lo seleccionado en la vista). Ninguna cifra minera se propone: los parámetros de la ruta, las cotas y el destino por cota quedan vacíos."""
    given = self.properties.is_property_set

    def first(items: Any, none: str) -> str | None:
        offered = [item[0] for item in items(self, None) if item[0] != none]
        return offered[0] if offered else None

    for prop, items, none in (("layer", des_panels.road_layer_items, des_panels.NO_LAYER), ("profile", des_panels.road_profile_items, des_panels.NO_ZONE),
                              ("origin_road", des_panels.road_road_items, des_panels.NO_ZONE),
                              ("destination_entity", des_panels.road_platform_items, des_panels.NO_ZONE),
                              ("dest_zone", des_panels.road_zone_items, des_panels.NO_LAYER)):
        found = first(items, none)
        if found is not None and not given(prop):
            setattr(self, prop, found)
    if not given("start"):
        offered = {item[0] for item in des_panels.platform_start_items(None, None)}
        start = des_panels.road_default_start()
        if start is None or start not in offered:
            items = [identifier for identifier in offered if identifier != des_panels.NO_ZONE and not identifier.startswith("entity:")]
            start = surface_proposal.ground_item(context, project, sorted(items), des_panels.surface_choice) if items else None
        if start is not None:
            self.start = start


def _draw_trace_points(box: Any, self: Any) -> None:
    """El origen y el destino de «trazar» en el diálogo ``self`` (de «Pista…» y de «Proponer el trazado…»): **el origen** (un punto de la capa o el eje de otra pista a una abscisa) y **el destino** (un
    punto, una plataforma o una cota con su zona y su tolerancia), dibujados en ``box``."""
    box.prop(self, "origin_from", text=tr("The origin is"), translate=False)
    if self.origin_from == "ROAD":
        box.prop(self, "origin_road", text=tr("Road of the origin"), translate=False)
        box.prop(self, "origin_station", text=tr("Abscissa of the origin (m)"), translate=False)
    else:
        box.prop(self, "origin_point", text=tr("Origin point"), translate=False)
    box.prop(self, "destination_to", text=tr("It ends at"), translate=False)
    if self.destination_to == "ENTITY":  # el destino es el punto de la capa que cae en su huella: no se elige otro
        box.prop(self, "destination_entity", text=tr("Platform of the destination"), translate=False)
    elif self.destination_to == "LEVEL":
        box.prop(self, "dest_level", text=tr("Elevation of the destination (m)"), translate=False)
        box.prop(self, "dest_tol", text=tr("Arrival tolerance of the elevation (m)"), translate=False)
        box.prop(self, "dest_zone", text=tr("Zone of the destination"), translate=False)
        box.prop(self, "dest_zone_feature", text=tr("Polygon of the zone"), translate=False)
    else:
        box.prop(self, "destination_point", text=tr("Destination point"), translate=False)


def _draw_route_params(layout: Any, self: Any) -> None:
    """Los nueve parámetros de la ruta de «trazar» en el diálogo ``self``, **cada uno con su tipo** (HIPÓTESIS sin valor por defecto y el presupuesto con el suyo: :func:`_route_text`)."""
    route = layout.box()
    route.label(text=tr("Search of the route: the type of each value is shown"), translate=False)
    for prop, param, label in _route_rows():
        row = route.row()
        row.prop(self, prop, text=label, translate=False)
        row.label(text=_route_text(param), translate=False)


class GEOBLENDER_OT_des_create_road(_ClearsEntityPreview, _CreatesInSteps, _ChainsEntityLayer, _CalculateAndCreate, DesignCommandAware, ProvenanceAwareOperator, _StepsModal,
                                    bpy.types.Operator):
    """Haul road of the active version: its axis, its level profile and its section engraved on its start surface, from an origin to a destination, over an axis or over a 3D axis"""

    bl_idname = CREATE_ROAD
    bl_label = "Road…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.ROAD
    COMMAND = CREATE_ROAD

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the road, unique in the active version", options=_FIELD)
    mode: EnumProperty(  # type: ignore[valid-type]
        name="Mode",
        description="Trace it from an origin to a destination, give it an axis in plan to fit the curves to, or give it a line with its Z whose Z is the level profile",
        items=ROAD_MODE_ITEMS, default="TRACE", options=_FIELD, update=_road_mode_changed)
    layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer",
        description="Layer of the project the road is taken from: of points (trace), of lines (over an axis) or of 3D lines (3D axis: the breaklines of the "
                    "project and the proposed routes of the active version)", items=des_panels.road_layer_items, options=_FIELD, update=_refresh_road_preview)
    name_field: StringProperty(  # type: ignore[valid-type]
        name="Name field",
        description="Field of the layer with the name of each geometry (empty: the field «nombre» or «name» or, without it, the number (fid))", options=_FIELD,
        update=_refresh_road_preview)
    feature: StringProperty(  # type: ignore[valid-type]
        name="Line of the layer",
        description="Name or number (fid) of the line of the layer that is the axis of the road (over an axis and 3D axis)", options=_FIELD,
        update=_refresh_road_preview)
    origin_from: EnumProperty(  # type: ignore[valid-type]
        name="The origin is",
        description="Whether the origin is a point of the layer or a point of the axis of another road, at an abscissa", items=ROAD_ORIGIN_ITEMS, default="POINT",
        options=_FIELD, update=_refresh_road_preview)
    origin_point: StringProperty(  # type: ignore[valid-type]
        name="Origin point",
        description="Name or number (fid) of the point of the layer that is the origin of the road", options=_FIELD, update=_refresh_road_preview)
    origin_road: EnumProperty(  # type: ignore[valid-type]
        name="Road of the origin",
        description="Road of the active version whose axis the origin is on: the new road rests on it and becomes stale if it changes",
        items=des_panels.road_road_items, options=_FIELD, update=_refresh_road_preview)
    origin_station: StringProperty(  # type: ignore[valid-type]
        name="Abscissa of the origin (m)",
        description="Distance along the axis of the other road, from its start, of the point where the new road starts, in metres", options=_FIELD,
        update=_refresh_road_preview)
    destination_to: EnumProperty(  # type: ignore[valid-type]
        name="It ends at",
        description="Whether the road ends at a point of the layer, on a platform of the active version or where it reaches an elevation inside a zone",
        items=ROAD_DESTINATION_ITEMS, default="POINT", options=_FIELD, update=_refresh_road_preview)
    destination_point: StringProperty(  # type: ignore[valid-type]
        name="Destination point",
        description="Name or number (fid) of the point of the layer that is the destination of the road", options=_FIELD, update=_refresh_road_preview)
    destination_entity: EnumProperty(  # type: ignore[valid-type]
        name="Platform of the destination",
        description="Platform of the active version the road ends at: its destination is the point of the layer that falls on its footprint, at the level of its "
                    "surface; the road rests on it", items=des_panels.road_platform_items, options=_FIELD, update=_refresh_road_preview)
    dest_level: StringProperty(  # type: ignore[valid-type]
        name="Elevation of the destination (m)",
        description="Elevation in metres the road has to reach: it ends at the first point of the zone whose start surface differs from it by less than the arrival "
                    "tolerance", options=_FIELD, update=_refresh_road_preview)
    dest_tol: StringProperty(  # type: ignore[valid-type]
        name="Arrival tolerance of the elevation (m)",
        description="How much the start surface may differ from the elevation of the destination where the road ends, in metres", options=_FIELD,
        update=_refresh_road_preview)
    dest_zone: EnumProperty(  # type: ignore[valid-type]
        name="Zone of the destination",
        description="Layer of polygons of the project with the zone where the elevation has to be reached", items=des_panels.road_zone_items, options=_FIELD,
        update=_refresh_road_preview)
    dest_zone_feature: StringProperty(  # type: ignore[valid-type]
        name="Polygon of the zone",
        description="Name or number (fid) of the polygon of the layer that is the zone (empty: all the polygons of the layer)", options=_FIELD,
        update=_refresh_road_preview)
    profile: EnumProperty(  # type: ignore[valid-type]
        name="Road profile",
        description="Profile of the road: its vehicle, its carriageway, its gradients, its radii and its slopes; create or complete them with «Road profile…»",
        items=des_panels.road_profile_items, options=_FIELD, update=_refresh_road_preview)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the road starts from: by default, the exploitation surface of the quarry and, without it, the last of the chain",
        items=des_panels.platform_start_items, options=_FIELD, update=_refresh_road_preview)
    support: EnumProperty(  # type: ignore[valid-type]
        name="Support surface",
        description="Surface the road rests on, if it rests on one (none: it rests on no other surface)", items=des_panels.platform_support_items, options=_FIELD,
        update=_refresh_road_preview)
    start_level: StringProperty(  # type: ignore[valid-type]
        name="Start level (m)",
        description="Elevation of the level profile at the start of the road in metres (empty: the one of the start surface at that point, recorded with its "
                    "origin; what you write is recorded as decided by you)", options=_FIELD, update=_refresh_road_preview)
    end_level: StringProperty(  # type: ignore[valid-type]
        name="End level (m)",
        description="Elevation of the level profile at the end of the road in metres (empty: the one of the start surface at that point or of the platform of the "
                    "destination, recorded with its origin; what you write is recorded as decided by you)", options=_FIELD, update=_refresh_road_preview)
    mesh: StringProperty(  # type: ignore[valid-type]
        name="Mesh of the route (m)",
        description="Side of the blocks of the grid in which the route is searched, in metres: a whole multiple of the step of the project; a hypothesis without "
                    "default value", options=_FIELD, update=_refresh_road_preview)
    level_step: StringProperty(  # type: ignore[valid-type]
        name="Elevation step (m)",
        description="Step of the elevations the route can take above or below the ground, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_road_preview)
    max_cut_fill: StringProperty(  # type: ignore[valid-type]
        name="Maximum cut and fill height (m)",
        description="Most the level profile of the route may be above or below the ground, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_road_preview)
    lambda_weight: StringProperty(  # type: ignore[valid-type]
        name="Weight of the earthworks (1/m)",
        description="How much the cost of the route grows with the height of cut and fill, in 1/m; a hypothesis without default value", options=_FIELD,
        update=_refresh_road_preview)
    turn: StringProperty(  # type: ignore[valid-type]
        name="Turn penalty (m)",
        description="Length added to the cost of the route for each change of heading, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_road_preview)
    margin: StringProperty(  # type: ignore[valid-type]
        name="Margin of the corridor (m)",
        description="How much longer than the shortest route the routes inside the corridor can be, in metres: the route changes with it; a hypothesis without "
                    "default value", options=_FIELD, update=_refresh_road_preview)
    simplify: StringProperty(  # type: ignore[valid-type]
        name="Simplification tolerance (m)",
        description="Most the simplified axis may separate from the route, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_road_preview)
    arrival_tol: StringProperty(  # type: ignore[valid-type]
        name="Arrival tolerance of the route (m)",
        description="How far from the destination elevation the route may end, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_road_preview)
    search_budget: StringProperty(  # type: ignore[valid-type]
        name="Budget of states",
        description="Most states the search of the route may expand before it stops saying so: a whole number (empty: the default value, shown)", options=_FIELD,
        update=_refresh_road_preview)
    mean_reason: StringProperty(  # type: ignore[valid-type]
        name="Reason for the mean gradient",
        description="Why you accept a mean gradient above the maximum of the profile: it stays recorded with who and when; it is needed only if the mean gradient "
                    "passes it", options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con el avance y Esc: los pone invoke; desde un guion, sin ellos, de una
    # vez. «Vista previa» (T28): la pone el botón del diálogo. Las confirmaciones expresas de la pendiente media y de la calzada que no queda en su rasante (RF-017-17,
    # RF-017-22): las pone el botón de su ventana, que las dice; desde un guion, quien la lanza (la media, además, con su motivo ``mean_reason``).
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    preview: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    confirm_mean: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    confirm_carriageway: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    # Calcular una pista traída o heredada «sin calcular» (T33c; RF-015-18, RF-015-04; la duda T22b (d)): el código de la pista que ya está en la versión; lo pone «Calcular…» del menú
    # «Entidad ▾» (``des_entity_calculate``). Con él no hay diálogo: se calcula con los parámetros que la pista ya tiene en la versión (``design.road_store.entity_road_request``), con su
    # código, sin escribir ninguno; «Crear» (por pasos y en una sola transacción) la registra con su código y las dependencias se detectan de nuevo.
    code: StringProperty(default="", options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué. Con ``confirm``, el diálogo de crear el cálculo abierto. Con ``code`` (una pista
        sin calcular, T33c) y la versión editable, sin diálogo: calcula (:meth:`execute`). Si no, las listas leídas de nuevo (las superficies, las capas, los perfiles de pista, las pistas y las plataformas
        de la versión), la propuesta (un nombre, la primera capa del modo, el primer perfil y la partida: la superficie de explotación de la cantera o la última de la cadena) y el
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
        if self.code.strip():  # una pista sin calcular: todo lo que hace falta ya lo tiene la versión (T33c)
            return self.execute(context)
        project = SESSION.project
        try:
            des_panels.refresh_choices(project)
            des_panels.refresh_platform_choices(project)
            des_panels.refresh_road_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label), confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 017 §5.3.3): un nombre que no repite el de ninguna entidad de la versión («Pista 1»…), el modo
        «trazar», la primera capa de ese modo, el primer perfil, la primera pista, plataforma y zona que ofrece y **la partida: la superficie de explotación de la
        cantera de la 014 y, si no hay o ya parte de ella otra entidad, la última de la cadena** (RF-017-05, D-3) o, sin ninguna, el terreno
        (``surface_proposal.ground_item``, con lo seleccionado en la vista). Ninguna cifra minera se propone: los parámetros de la ruta, las cotas y el destino por
        cota quedan vacíos."""
        if not self.name.strip():
            taken, number = set(des_panels.platform_names()), 1
            while f"{tr('Road')} {number}" in taken:
                number += 1
            self.name = f"{tr('Road')} {number}"
        _propose_trace_values(self, context, project)

    def draw(self, context: Any) -> None:
        """Arriba el nombre y el modo; la capa y, en «trazar», **el origen** (un punto de la capa o el eje de otra pista a una abscisa) y **el destino** (un punto,
        una plataforma o una cota con su zona y su tolerancia) o, en «sobre un eje» y «eje 3D», la línea; el perfil, la partida y el apoyo; las cotas de inicio y de
        fin y, en «trazar», **los parámetros de la ruta, cada uno con su tipo**; y «Vista previa». En la confirmación de crear, el resumen y, si la pendiente media
        pide un motivo, su campo."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            if self.confirm_mean:
                layout.prop(self, "mean_reason", text=tr("Reason for the mean gradient"), translate=False)
            return
        layout.use_property_split = True
        trace = self.mode == "TRACE"
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "mode", text=tr("Mode"), translate=False)
        box = layout.box()
        box.label(text=tr("Geometry of the road"), translate=False)
        box.prop(self, "layer", text=tr("Layer"), translate=False)
        box.prop(self, "name_field", text=tr("Name field"), translate=False)
        if trace:
            _draw_trace_points(box, self)
        else:
            box.prop(self, "feature", text=tr("Line of the layer"), translate=False)
        layout.prop(self, "profile", text=tr("Road profile"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        layout.prop(self, "support", text=tr("Support surface"), translate=False)
        if self.mode != "AXIS_3D":  # en «eje 3D» la Z de la línea es la rasante: no hay cota de inicio ni de fin que dar
            levels = layout.box()
            levels.label(text=tr("Elevations (empty: those of the start surface, recorded with their origin)"), translate=False)
            levels.prop(self, "start_level", text=tr("Start level (m)"), translate=False)
            levels.prop(self, "end_level", text=tr("End level (m)"), translate=False)
        if trace:
            _draw_route_params(layout, self)
        _draw_entity_preview_button(layout, self, CREATE_ROAD, _road_dialog_fields())  # «Vista previa» (RF-017-26)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self) -> Any:
        """Lo pedido en el diálogo como la ``design.road_model.RoadRequest`` (RF-017-01, RF-017-02, RF-017-10), comprobado sin escribir ni calcular nada. En «trazar»,
        el origen es un punto de la capa (por su nombre o su ``fid``) o ``RDW-001@s`` (el eje de otra pista a la abscisa ``s``) y el destino, un punto, ``entity:PLT-001``
        (una plataforma: el punto de la capa que cae en su huella) o una cota con su zona y su tolerancia; en «sobre un eje» y «eje 3D», la línea. Lo que se deja vacío
        (las cotas de inicio y de fin, los parámetros de la ruta, el presupuesto de estados) lo resuelve el dominio: la cota de la superficie de partida con su
        origen, el valor por defecto de su parámetro o, si no lo tiene, el rechazo de RF-015-08 con su nombre. :class:`ComputeFormError` si falta algo que el diálogo
        necesita para armar la petición."""
        from ...design import road_model  # al usarlo: habilitar no carga el cálculo

        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the road"))
        if self.layer in ("", des_panels.NO_LAYER):
            raise ComputeFormError(tr("Choose the layer of the road: there is none for this mode in the project"))
        if self.profile in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the profile of the road: create one with «Road profile…»"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the road"))
        mode = self.mode
        fields = road_model.LayerFields(self.layer, self.name_field.strip() or None)
        changes: dict[str, Any] = {}
        support = None if self.support in ("", des_panels.NO_ZONE) else self.support
        if mode == "TRACE":
            changes.update(_road_points(self))
            changes.update(_route_changes(self))
        else:
            changes["feature"] = self.feature.strip() or None
        if mode != "AXIS_3D":
            changes["start_level_m"] = typed_number(self.start_level, tr("Start level (m)"))
            changes["end_level_m"] = typed_number(self.end_level, tr("End level (m)"))
        return road_model.RoadRequest(name, fields, mode.lower(), self.profile, self.start, support=support, **changes)

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Con ``preview``, activa la vista previa de lo pedido (:meth:`_show_preview`). Si no, comprueba
        lo pedido (sin escribir nada si falta algo), pasa por la puerta de la 008 y calcula la pista por pasos con ``design.steps.road_run`` —compila las máscaras
        antes si no están al día—, sin registrar nada (RF-015-03): desde la interfaz, en el modal con el avance y Esc (RF-015-29, RF-017-30); desde un guion, de una
        vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los rechazos (la capa, el origen y el destino, las cotas, el perfil y su valor, la
        partida, los parámetros de la ruta que faltan, un sector con la búsqueda pendiente, el nombre repetido, una ruta que no existe y por qué) y todas las
        cuentas son de ``design``. Con ``code`` (T33c), la pista **sin calcular** de la versión con ese código (:func:`_road_entity_request`: la que dejó «Traer las entidades de…» o
        heredó una versión que parte de otra): se calcula con los parámetros que ya tiene y con su código, sin escribir ninguno."""
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
        code = self.code.strip()
        try:
            request = _road_entity_request(project, version, code) if code else self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report, dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.road_run(project, request, version=version, code=code or None, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _show_preview(self) -> set[str]:
        """«Vista previa» (T28 y T29b; RF-017-26, RF-015-26): comprueba lo pedido como al calcular (:meth:`_request`, sin escribir ni calcular nada) y activa con ello la
        vista previa de la pista (``bl.draw.entity``: antes de calcular, el origen, el destino y el pasillo de la ruta); la que hubiera activa se cambia por la nueva
        (pulsarlo otra vez, o cambiar un campo del diálogo: :func:`_refresh_road_preview`). Lo que rechazaría «Calcular» sale en la propia vista previa, como aviso.
        Se quita al cancelar la orden, al Esc a mitad del cálculo, al crearla, con su control y al conmutar a la interfaz de Blender."""
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            request = self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        from ...design.preview import RoadAsk  # al usarlo: habilitar no carga el cálculo

        preview = _entity_preview()
        try:
            preview.enable(preview.EntityPlan(road=RoadAsk(request=request)))
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr("The preview of the entity could not be shown: {detail}", detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of the road «{name}»", name=request.name))
        return {"FINISHED"}

    def _finished(self, context: Any, opened: Any) -> set[str]:
        """Como las demás (:meth:`_ChainsEntityLayer._finished`) y, **tras calcular**, con la vista previa activa, **le da lo calculado** (``RoadAsk(request, prepared,
        outcome)``: el eje con su flecha, las pendientes por tramos y la anchura de la sección, sin repetir la preparación: T28)."""
        calculated = not self._chain
        done = _ChainsEntityLayer._finished(self, context, opened)
        if calculated:
            self._show_calculated(opened)
        return done

    @staticmethod
    def _show_calculated(opened: Any) -> None:
        """Con la vista previa de **esta** pista activa, la cambia por la de lo que dejó «Calcular» (``opened``: el cálculo abierto). Solo lee."""
        _show_calculated_preview(opened, propose=False)

    def _confirmation(self, context: Any) -> set[str]:
        """El diálogo de crear el cálculo abierto. Con la **pendiente media por encima de pm** (RF-017-17) o la **calzada que no queda en su rasante** (RF-017-22), que
        piden confirmación expresa, su botón lo dice («Confirmar y crear»): pulsarlo es la confirmación y, de la media, el diálogo pide además su **motivo**, que
        queda registrado con quién y cuándo y no bloquea; «Cancelar» y cerrarlo no crean nada."""
        held = calculation()
        self.confirm_mean = held is not None and held.needs_mean_confirmation
        self.confirm_carriageway = held is not None and held.needs_carriageway_confirmation
        return _CalculateAndCreate._confirmation(self, context)

    def _confirm_text(self, held: Calculation) -> str:
        if held.needs_mean_confirmation or held.needs_carriageway_confirmation:
            return tr("Confirm and create")
        return _CalculateAndCreate._confirm_text(self, held)

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-017-01, RF-015-02): como las demás, y con la **pendiente media por encima de pm** o la **calzada que no queda en su rasante** **no se crea sin la
        confirmación expresa** (``confirm_mean`` y ``confirm_carriageway``: el botón de la ventana, o quien la lanza desde un guion) ni, la media, **sin su motivo**
        (``mean_reason``: RF-017-17, D-6, que queda en los ajustes de la operación con quién y cuándo y no bloquea): lo dice y el cálculo sigue abierto (se confirma, o se
        calcula otra vez). Con ellas, las deja dichas en el cálculo antes de crearlo (``Calculation.confirm_road``). **Ya creada**, quita la vista previa (la pista ya
        existe: ya no se prepara) y encadena lo que sigue (:meth:`_update_declared`: la capa de entidades y la de ejes, como operaciones aparte)."""
        from ...design import road_store  # al usarlo: habilitar no carga el cálculo

        opened = calculation()
        if opened is not None and isinstance(opened.entity, road_store.PreparedRoad):
            reason = self.mean_reason.strip() or None
            try:
                road_store.check_road_confirmed(opened.outcome, mean=self.confirm_mean, carriageway=self.confirm_carriageway, reason=reason)  # type: ignore[arg-type]
            except design_messages.DesignError as exc:
                self.report({"ERROR"}, design_error_text(exc))
                if self.in_steps and getattr(context, "window", None) is not None:
                    _ask_confirmation(context, idname=self.COMMAND)  # el cálculo sigue abierto: se vuelve a pedir, con su motivo
                return {"CANCELLED"}
            opened.confirm_road(mean=self.confirm_mean, carriageway=self.confirm_carriageway, reason=reason)
            started = self._create_in_steps(context, opened)
            if started is not None:  # desde la interfaz, por pasos (T32): lo que sigue va en el mismo modal
                return started
        created = _CalculateAndCreate._create(self, context)
        if opened is None or "FINISHED" not in created:
            return created
        _entity_preview_off()  # la pista ya existe: ya no se prepara (RF-017-26)
        return self._update_declared(context, opened)

    def _after_registered(self) -> None:
        """En cuanto lo guardado llega (:class:`_CreatesInSteps`), quita la vista previa: la pista ya existe, ya no se prepara (RF-017-26)."""
        _entity_preview_off()

    def _created_text(self, opened: Calculation) -> str:
        return tr("Road «{name}» created in {version}", name=opened.name, version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando la pista… 40 % · Esc: cancelar», «Guardando la pista… 40 % · Esc: cancelar» o, tras crearla, «Poniendo al día las restricciones
        declaradas… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._chain:
            return tr("Updating the declared constraints and the masks… {percent} % · Esc: cancel", percent=percent)
        if self._creating:
            return tr("Saving the road… {percent} % · Esc: cancel", percent=percent)
        return tr("Computing the road… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._chain:
            return tr("Cancelled: the road is created; the declared constraints and the masks are brought up to date before the next operation that uses them, "
                      "and the entity layer and the layer of axes with the next entity order or «Recompute the stale results»")
        if self._creating:
            return tr("Creation cancelled: the road has not been created and the calculation has been discarded; nothing has been left half-done")
        return _CalculateAndCreate._cancelled_text(self)

    def _error_text(self, exc: GeoblenderError) -> str:
        found = _CalculateAndCreate._error_text(self, exc)
        if self._chain:
            return f"{found} " + tr("The road is created: only the declared constraints and the masks have not been brought up to date")
        return found


# --- Accesibilidad de las pistas… (spec 017, T30; HU-017-3; RF-017-29, RF-017-24, RF-017-25, RF-017-30, RF-015-28; plan 017 §5.3.3 y §5.5; comprobación manual M3) ------------

ROAD_ACCESS_COMMAND = provenance.ACCESS_COMMAND
_ACCESS_HIDDEN = frozenset({"confirm", "in_steps"})
"""Las propiedades ocultas de «Accesibilidad de las pistas…»: las pone quien la lanza (o su ventana de confirmar)."""


def _access_rows() -> tuple[tuple[str, str, str], ...]:
    """Los tres umbrales de la accesibilidad (RF-017-24, RF-017-25, D-17): la propiedad del diálogo, el valor de ``AccessRequest`` (y de ``des.access.{e}.*``) y su etiqueta en el idioma de Geoblender.
    Los tres son HIPÓTESIS sin valor por defecto: el diálogo dice el tipo de cada uno."""
    return (("walk_slope", "walk_slope_pct", tr("Maximum walkable gradient (%)")), ("walk_width", "walk_width_m", tr("Minimum walkable width (m)")),
            ("min_berm_area", "min_berm_area_m2", tr("Minimum area of a berm stretch (m²)")))


def _access_text(param: str) -> str:
    """Lo que dice el diálogo de «Accesibilidad de las pistas…» de un umbral (D-17): **su tipo**, el de su familia: «HIPÓTESIS: sin valor por defecto, lo elige usted». Ninguno se propone: vacío es el
    rechazo del cálculo con su nombre (RF-015-08)."""
    return _entity_param_text("access", param)


class GEOBLENDER_OT_des_road_access(_CreatesInSteps, _ChainsEntityLayer, _CalculateAndCreate, DesignCommandAware, ProvenanceAwareOperator, _StepsModal, bpy.types.Operator):
    """Accessibility of the haul roads on a surface of the project or of the active version: what can be reached on foot from the entry points, the reachable elevations and which berm stretches, platforms and zones that require access are communicated"""

    bl_idname = ROAD_ACCESS_COMMAND
    bl_label = "Accessibility of the roads…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.ROAD_ACCESS
    COMMAND = ROAD_ACCESS_COMMAND

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the accessibility, unique in the active version", options=_FIELD)
    surface: EnumProperty(  # type: ignore[valid-type]
        name="Surface",
        description="Surface the accessibility is calculated on: a grid of the project or of the active version; by default, the last of the chain of entities of the version",
        items=des_panels.surface_items, options=_FIELD)
    layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer of the entry points",
        description="Layer of points of the project with the entry points: where people or machines get onto the surface", items=des_panels.access_layer_items, options=_FIELD)
    name_field: StringProperty(  # type: ignore[valid-type]
        name="Name field", description="Field of the layer with the name of each entry point (empty: its number (fid))", options=_FIELD)
    walk_slope: StringProperty(  # type: ignore[valid-type]
        name="Maximum walkable gradient (%)",
        description="Local gradient above which a cell cannot be walked, in per cent; a hypothesis without default value", options=_FIELD)
    walk_width: StringProperty(  # type: ignore[valid-type]
        name="Minimum walkable width (m)",
        description="Narrowest passage that can be walked, in metres, between cell centres; a hypothesis without default value", options=_FIELD)
    min_berm_area: StringProperty(  # type: ignore[valid-type]
        name="Minimum area of a berm stretch (m²)",
        description="Smallest berm stretch that is listed, in square metres; a hypothesis without default value", options=_FIELD)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez. Una accesibilidad no retira
    # nada, no mueve ninguna celda ni deja una pared: no pide más confirmación que Crear.
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué. Con ``confirm``, el diálogo de crear el cálculo abierto, con su resumen y sus listas. Si no, las listas
        leídas de nuevo (las superficies del proyecto y de la versión, las capas de puntos y la superficie por defecto), la propuesta (un nombre, la primera capa y la superficie: la última de la cadena)
        y el diálogo del cálculo: Intro calcula."""
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
            des_panels.refresh_access_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label), confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio (plan 017 §5.3.3): un nombre que no repite el de ninguna entidad del proyecto ni de la versión («Accesibilidad 1»…), la primera capa de
        puntos y **la superficie: la última de la cadena** de la versión (RF-017-24) o, sin cadena, la explotación de su cantera y, sin ninguna, el terreno (``surface_proposal.ground_item``, con lo
        seleccionado en la vista). Ningún umbral se propone: no tienen valor por defecto (D-17)."""
        given = self.properties.is_property_set
        if not self.name.strip():
            taken, number = _taken_entity_names(project), 1
            while f"{tr('Accessibility')} {number}" in taken:
                number += 1
            self.name = f"{tr('Accessibility')} {number}"
        if not given("layer"):
            layers = [item[0] for item in des_panels.access_layer_items(self, None) if item[0] != des_panels.NO_LAYER]
            if layers:
                self.layer = layers[0]
        if not given("surface"):
            offered = [identifier for identifier, _name, _about in des_panels.surface_items(None, None) if identifier != des_panels.NO_ZONE]
            default = des_panels.access_default_surface()
            ground = default if default in offered else (surface_proposal.ground_item(context, project, offered, des_panels.surface_choice) if offered else None)
            if ground is not None:
                self.surface = ground

    def draw(self, context: Any) -> None:
        """Arriba el nombre y la superficie; la capa de los puntos de entrada con su campo y **los umbrales, cada uno con su tipo** (HIPÓTESIS, sin valor por defecto). En la confirmación de crear, el
        resumen (la cabecera, las cotas mínima y máxima alcanzables y los avisos) y **las listas de bermas, plataformas y zonas «requiere acceso»**, comunicadas o no, cada una con su «Ir a»."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto y sus listas
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            des_panels.draw_access_lists(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "surface", text=tr("Surface"), translate=False)
        box = layout.box()
        box.label(text=tr("Entry points"), translate=False)
        box.prop(self, "layer", text=tr("Layer of the entry points"), translate=False)
        box.prop(self, "name_field", text=tr("Name field"), translate=False)
        walkable = layout.box()
        walkable.label(text=tr("Walkable ground and berms: the type of each value is shown"), translate=False)
        for prop, param, label in _access_rows():
            row = walkable.row()
            row.prop(self, prop, text=label, translate=False)
            row.label(text=_access_text(param), translate=False)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self) -> Any:
        """Lo pedido en el diálogo como la ``design.road_model.AccessRequest`` (RF-017-24, RF-017-25), comprobado sin escribir ni calcular nada. Un umbral vacío queda sin cifra: lo rechaza el cálculo
        nombrando la entidad, el campo y el valor (RF-015-08, D-17: la petición no lleva ninguna cifra minera). :class:`ComputeFormError` si falta algo del diálogo."""
        from ...design import road_model  # al usarlo: habilitar no carga el cálculo

        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the accessibility"))
        if self.layer in ("", des_panels.NO_LAYER):
            raise ComputeFormError(tr("Choose the layer of the entry points: there is none of points in the project"))
        if self.surface in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the surface the accessibility is calculated on"))
        thresholds = {param: typed_number(getattr(self, prop), label) for prop, param, label in _access_rows()}
        return road_model.AccessRequest(name, road_model.LayerFields(self.layer, self.name_field.strip() or None), self.surface, **thresholds)

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Si no, comprueba lo pedido (sin escribir nada si falta algo), pasa por la puerta de la 008 y calcula la accesibilidad por pasos con
        ``design.steps.access_run`` —compila las máscaras antes si no están al día—, sin registrar nada (RF-015-03): desde la interfaz, en el modal con el avance y Esc (RF-015-29, RF-017-30); desde un
        guion, de una vez. Al terminar deja el cálculo abierto con su resumen y sus listas y pide confirmar. Los rechazos (la capa y su campo, los puntos de entrada, los umbrales, la superficie, el
        nombre repetido) y todas las cuentas son de ``design``."""
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
        ready = ensure_ready(self.provenance_op_type, [], report=self.report, dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.access_run(project, request, version=version, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _finished(self, context: Any, opened: Any) -> set[str]:
        """Como las demás (:meth:`_ChainsEntityLayer._finished`) y, **tras calcular**, dice en el informe **lo que no se comunica** (:func:`~..ui.des_panels.access_report_lines`): el resumen que se
        enseña no lo repite, porque lo dicen las listas con su lugar y su «Ir a»."""
        calculated = not self._chain
        done = _ChainsEntityLayer._finished(self, context, opened)
        if calculated:
            for text, alert in des_panels.access_report_lines():
                self._report({"WARNING" if alert else "INFO"}, text)
        return done

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-017-24, RF-015-02): como las demás. **Ya creada**, encadena lo que sigue (:meth:`_update_declared`: la capa de entidades, la declaración y las máscaras, como operaciones aparte): la
        accesibilidad no declara ninguna restricción."""
        opened = calculation()
        started = self._create_in_steps(context, opened)
        if started is not None:  # desde la interfaz, por pasos (T32): lo que sigue va en el mismo modal
            return started
        created = _CalculateAndCreate._create(self, context)
        if opened is None or "FINISHED" not in created:
            return created
        return self._update_declared(context, opened)

    def _created_text(self, opened: Calculation) -> str:
        return tr("Accessibility «{name}» created in {version}", name=opened.name, version=opened.version)

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando la accesibilidad… 40 % · Esc: cancelar», «Guardando la accesibilidad… 40 % · Esc: cancelar» o, tras crearla, «Poniendo al día las
        restricciones declaradas… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._chain:
            return tr("Updating the declared constraints and the masks… {percent} % · Esc: cancel", percent=percent)
        if self._creating:
            return tr("Saving the accessibility… {percent} % · Esc: cancel", percent=percent)
        return tr("Computing the accessibility… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._chain:
            return tr("Cancelled: the accessibility is created; the declared constraints and the masks are brought up to date before the next operation that uses them, "
                      "and the entity layer with the next entity order or «Recompute the stale results»")
        if self._creating:
            return tr("Creation cancelled: the accessibility has not been created and the calculation has been discarded; nothing has been left half-done")
        return _CalculateAndCreate._cancelled_text(self)

    def _error_text(self, exc: GeoblenderError) -> str:
        found = _CalculateAndCreate._error_text(self, exc)
        if self._chain:
            return f"{found} " + tr("The accessibility is created: only the declared constraints and the masks have not been brought up to date")
        return found


# --- Proponer el trazado… (spec 017, T33; HU-017-1, HU-017-4; RF-017-28, RF-017-29, RF-017-30, RF-015-28; plan 017 §5.3.3 y §5.5; comprobación manual M1) ------------------------------------------

PROPOSE_ROAD = provenance.PROPOSE_COMMAND
_PROPOSE_HIDDEN = frozenset({"confirm", "in_steps", "preview"})
"""Las propiedades ocultas de «Proponer el trazado…»: las pone quien la lanza (o su ventana de confirmar)."""


def _propose_dialog_fields() -> tuple[str, ...]:
    """Los campos del diálogo de «Proponer el trazado…» que pasan a su vista previa: sus propiedades no ocultas."""
    return tuple(name for name in GEOBLENDER_OT_des_propose_road.__annotations__ if name not in _PROPOSE_HIDDEN)


def _refresh_propose_preview(self: Any, _context: Any) -> None:
    """El ``update`` de cada campo de «Proponer el trazado…» (T33; RF-017-26): como el de «Pista…» (:func:`_refresh_road_preview`), con la petición del diálogo de la propuesta: la vista previa de la
    pista (antes de calcular, el origen, el destino y el pasillo de la ruta; sin sección: la propuesta no la tiene)."""
    _redraw_road_preview(self, GEOBLENDER_OT_des_propose_road._request, propose=True)


class GEOBLENDER_OT_des_propose_road(_ClearsEntityPreview, _CreatesInSteps, _CalculateAndCreate, DesignCommandAware, ProvenanceAwareOperator, _StepsModal, bpy.types.Operator):
    """Proposal of the route of a haul road of the active version, from an origin to a destination: its axis and its level profile as a layer of 3D lines that you can edit in QGIS; it changes no surface and is not an entity"""

    bl_idname = PROPOSE_ROAD
    bl_label = "Propose the route…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.ROAD_PROPOSE
    COMMAND = PROPOSE_ROAD

    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the proposed route, unique in the active version: the layer of 3D lines is called after it", options=_FIELD)
    layer: EnumProperty(  # type: ignore[valid-type]
        name="Layer",
        description="Layer of points of the project with the origin and the destination of the route", items=des_panels.road_layer_items, options=_FIELD,
        update=_refresh_propose_preview)
    name_field: StringProperty(  # type: ignore[valid-type]
        name="Name field",
        description="Field of the layer with the name of each geometry (empty: the field «nombre» or «name» or, without it, the number (fid))", options=_FIELD,
        update=_refresh_propose_preview)
    origin_from: EnumProperty(  # type: ignore[valid-type]
        name="The origin is",
        description="Whether the origin is a point of the layer or a point of the axis of another road, at an abscissa", items=ROAD_ORIGIN_ITEMS, default="POINT",
        options=_FIELD, update=_refresh_propose_preview)
    origin_point: StringProperty(  # type: ignore[valid-type]
        name="Origin point",
        description="Name or number (fid) of the point of the layer that is the origin of the road", options=_FIELD, update=_refresh_propose_preview)
    origin_road: EnumProperty(  # type: ignore[valid-type]
        name="Road of the origin",
        description="Road of the active version whose axis the origin is on: the proposal becomes stale if it changes",
        items=des_panels.road_road_items, options=_FIELD, update=_refresh_propose_preview)
    origin_station: StringProperty(  # type: ignore[valid-type]
        name="Abscissa of the origin (m)",
        description="Distance along the axis of the other road, from its start, of the point where the new road starts, in metres", options=_FIELD,
        update=_refresh_propose_preview)
    destination_to: EnumProperty(  # type: ignore[valid-type]
        name="It ends at",
        description="Whether the route ends at a point of the layer, on a platform of the active version or where it reaches an elevation inside a zone",
        items=ROAD_DESTINATION_ITEMS, default="POINT", options=_FIELD, update=_refresh_propose_preview)
    destination_point: StringProperty(  # type: ignore[valid-type]
        name="Destination point",
        description="Name or number (fid) of the point of the layer that is the destination of the road", options=_FIELD, update=_refresh_propose_preview)
    destination_entity: EnumProperty(  # type: ignore[valid-type]
        name="Platform of the destination",
        description="Platform of the active version the route ends at: its destination is the point of the layer that falls on its footprint, at the level of its "
                    "surface", items=des_panels.road_platform_items, options=_FIELD, update=_refresh_propose_preview)
    dest_level: StringProperty(  # type: ignore[valid-type]
        name="Elevation of the destination (m)",
        description="Elevation in metres the route has to reach: it ends at the first point of the zone whose start surface differs from it by less than the arrival "
                    "tolerance", options=_FIELD, update=_refresh_propose_preview)
    dest_tol: StringProperty(  # type: ignore[valid-type]
        name="Arrival tolerance of the elevation (m)",
        description="How much the start surface may differ from the elevation of the destination where the road ends, in metres", options=_FIELD,
        update=_refresh_propose_preview)
    dest_zone: EnumProperty(  # type: ignore[valid-type]
        name="Zone of the destination",
        description="Layer of polygons of the project with the zone where the elevation has to be reached", items=des_panels.road_zone_items, options=_FIELD,
        update=_refresh_propose_preview)
    dest_zone_feature: StringProperty(  # type: ignore[valid-type]
        name="Polygon of the zone",
        description="Name or number (fid) of the polygon of the layer that is the zone (empty: all the polygons of the layer)", options=_FIELD,
        update=_refresh_propose_preview)
    profile: EnumProperty(  # type: ignore[valid-type]
        name="Road profile",
        description="Profile of the road: its vehicle, its carriageway, its gradients, its radii and its slopes; create or complete them with «Road profile…»",
        items=des_panels.road_profile_items, options=_FIELD, update=_refresh_propose_preview)
    start: EnumProperty(  # type: ignore[valid-type]
        name="Start surface",
        description="Surface the route is searched on: by default, the exploitation surface of the quarry and, without it, the last of the chain",
        items=des_panels.platform_start_items, options=_FIELD, update=_refresh_propose_preview)
    start_level: StringProperty(  # type: ignore[valid-type]
        name="Start level (m)",
        description="Elevation of the level profile at the start of the route in metres (empty: the one of the start surface at that point)", options=_FIELD,
        update=_refresh_propose_preview)
    end_level: StringProperty(  # type: ignore[valid-type]
        name="End level (m)",
        description="Elevation of the level profile at the end of the route in metres (empty: the one of the start surface at that point or of the platform of the "
                    "destination)", options=_FIELD, update=_refresh_propose_preview)
    mesh: StringProperty(  # type: ignore[valid-type]
        name="Mesh of the route (m)",
        description="Side of the blocks of the grid in which the route is searched, in metres: a whole multiple of the step of the project; a hypothesis without "
                    "default value", options=_FIELD, update=_refresh_propose_preview)
    level_step: StringProperty(  # type: ignore[valid-type]
        name="Elevation step (m)",
        description="Step of the elevations the route can take above or below the ground, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_propose_preview)
    max_cut_fill: StringProperty(  # type: ignore[valid-type]
        name="Maximum cut and fill height (m)",
        description="Most the level profile of the route may be above or below the ground, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_propose_preview)
    lambda_weight: StringProperty(  # type: ignore[valid-type]
        name="Weight of the earthworks (1/m)",
        description="How much the cost of the route grows with the height of cut and fill, in 1/m; a hypothesis without default value", options=_FIELD,
        update=_refresh_propose_preview)
    turn: StringProperty(  # type: ignore[valid-type]
        name="Turn penalty (m)",
        description="Length added to the cost of the route for each change of heading, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_propose_preview)
    margin: StringProperty(  # type: ignore[valid-type]
        name="Margin of the corridor (m)",
        description="How much longer than the shortest route the routes inside the corridor can be, in metres: the route changes with it; a hypothesis without "
                    "default value", options=_FIELD, update=_refresh_propose_preview)
    simplify: StringProperty(  # type: ignore[valid-type]
        name="Simplification tolerance (m)",
        description="Most the simplified axis may separate from the route, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_propose_preview)
    arrival_tol: StringProperty(  # type: ignore[valid-type]
        name="Arrival tolerance of the route (m)",
        description="How far from the destination elevation the route may end, in metres; a hypothesis without default value", options=_FIELD,
        update=_refresh_propose_preview)
    search_budget: StringProperty(  # type: ignore[valid-type]
        name="Budget of states",
        description="Most states the search of the route may expand before it stops saying so: a whole number (empty: the default value, shown)", options=_FIELD,
        update=_refresh_propose_preview)
    # La confirmación de crear (D-14 de la 013) y los pasos con el temporizador de la ventana, con el avance y Esc: los pone invoke; desde un guion, sin ellos, de una vez. «Vista previa» (T28): la pone el
    # botón del diálogo. Una propuesta no pide confirmación: no graba ninguna superficie (la pendiente media por encima de pm solo avisa).
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    preview: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    _saved = False
    """Si lo que llega al modal es lo guardado de la propuesta (y no el cálculo)."""

    # --- El diálogo ---------------------------------------------------------------------------

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Sin versión activa, la ventana que pide una (RF-009-05); con ella no editable, el porqué. Con ``confirm``, el diálogo de crear el cálculo abierto. Si no, las listas leídas de nuevo (las superficies,
        las capas, los perfiles de pista, las pistas y las plataformas de la versión), la propuesta (un nombre, la primera capa de puntos, el primer perfil y la partida) y el diálogo del cálculo: Intro calcula."""
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
            des_panels.refresh_road_choices(project)
            self._propose(context, project)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=command_text(catalog().commands[command_idname(self.COMMAND)].label), confirm_text=tr("Calculate"))

    def _propose(self, context: Any, project: Any) -> None:
        """Lo que propone el diálogo si quien lo lanza no lo dio: un nombre que no repite el de ninguna capa propuesta de la versión («Ruta propuesta 1»…) y lo de «Pista…» (:func:`_propose_trace_values`: la
        primera capa de puntos, el primer perfil y la partida). Ninguna cifra minera se propone."""
        if not self.name.strip():
            version = scene_versions.active()
            taken = set() if version is None else set(des_panels._proposed_routes(project, version.uid))
            number = 1
            while provenance.dataset_name(provenance.ROUTE_LAYER_TABLE, f"{tr('Proposed route')} {number}") in taken:
                number += 1
            self.name = f"{tr('Proposed route')} {number}"
        _propose_trace_values(self, context, project)

    def draw(self, context: Any) -> None:
        """Arriba el nombre; la capa de puntos y **el origen** (un punto de la capa o el eje de otra pista a una abscisa) y **el destino** (un punto, una plataforma o una cota con su zona y su tolerancia); el perfil
        y la partida; las cotas de inicio y de fin; **los parámetros de la ruta, cada uno con su tipo**; y «Vista previa». En la confirmación de crear, el resumen."""
        layout = self.layout
        if self.confirm:  # el resumen del cálculo abierto
            des_panels.draw_summary(layout, DIALOG_WIDTH)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        box = layout.box()
        box.label(text=tr("Geometry of the road"), translate=False)
        box.prop(self, "layer", text=tr("Layer"), translate=False)
        box.prop(self, "name_field", text=tr("Name field"), translate=False)
        _draw_trace_points(box, self)
        layout.prop(self, "profile", text=tr("Road profile"), translate=False)
        layout.prop(self, "start", text=tr("Start surface"), translate=False)
        levels = layout.box()
        levels.label(text=tr("Elevations (empty: those of the start surface)"), translate=False)
        levels.prop(self, "start_level", text=tr("Start level (m)"), translate=False)
        levels.prop(self, "end_level", text=tr("End level (m)"), translate=False)
        _draw_route_params(layout, self)
        _draw_entity_preview_button(layout, self, PROPOSE_ROAD, _propose_dialog_fields())  # «Vista previa» (RF-017-26)

    # --- Lo pedido ----------------------------------------------------------------------------

    def _request(self) -> Any:
        """Lo pedido en el diálogo como la ``design.road_model.RoadRequest`` de «trazar» (RF-017-28, RF-017-02, RF-017-10), comprobado sin escribir ni calcular nada: el origen es un punto de la capa (por su nombre o
        su ``fid``) o ``RDW-001@s`` (el eje de otra pista a la abscisa ``s``) y el destino, un punto, ``entity:PLT-001`` (una plataforma) o una cota con su zona y su tolerancia. Lo que se deja vacío (las cotas de
        inicio y de fin, los parámetros de la ruta, el presupuesto de estados) lo resuelve el dominio: la cota de la superficie de partida, el valor por defecto de su parámetro o, si no lo tiene, el rechazo de
        RF-015-08 con su nombre. :class:`ComputeFormError` si falta algo que el diálogo necesita para armar la petición."""
        from ...design import road_model  # al usarlo: habilitar no carga el cálculo

        name = self.name.strip()
        if not name:
            raise ComputeFormError(tr("Write the name of the proposed route"))
        if self.layer in ("", des_panels.NO_LAYER):
            raise ComputeFormError(tr("Choose the layer of the route: there is none of points in the project"))
        if self.profile in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the profile of the road: create one with «Road profile…»"))
        if self.start in ("", des_panels.NO_ZONE):
            raise ComputeFormError(tr("Choose the start surface of the route"))
        changes: dict[str, Any] = {**_road_points(self), **_route_changes(self)}
        changes["start_level_m"] = typed_number(self.start_level, tr("Start level (m)"))
        changes["end_level_m"] = typed_number(self.end_level, tr("End level (m)"))
        return road_model.RoadRequest(name, road_model.LayerFields(self.layer, self.name_field.strip() or None), "trace", self.profile, self.start, **changes)

    # --- Calcular y crear ---------------------------------------------------------------------

    def execute(self, context: Any) -> set[str]:
        """Con ``confirm``, crea el cálculo abierto (:meth:`_create`). Con ``preview``, activa la vista previa de lo pedido (:meth:`_show_preview`). Si no, comprueba lo pedido (sin escribir nada si falta algo), pasa
        por la puerta de la 008 y calcula la propuesta por pasos con ``design.steps.road_propose_run`` —compila las máscaras antes si no están al día—, sin registrar nada (RF-015-03): desde la interfaz, en el modal
        con el avance y Esc (RF-015-29, RF-017-30); desde un guion, de una vez. Al terminar deja el cálculo abierto con su resumen y pide confirmar. Los rechazos (la capa y sus puntos, el perfil y su valor, la
        partida, los parámetros de la ruta que faltan, un sector con la búsqueda pendiente, el nombre repetido, una ruta que no existe y por qué) y todas las cuentas son de ``design``."""
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
            request = self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        ready = ensure_ready(self.provenance_op_type, [], report=self.report, dialog=self.provenance_dialog, version=version)
        if ready is None:
            return {"CANCELLED"}
        from ...design import steps as design_steps  # al usarlo: habilitar no carga el cálculo

        discard_calculation()  # el anterior, si seguía abierto: sus temporales no se quedan
        steps = design_steps.road_propose_run(project, request, version=version, budget_s=self.STEP_BUDGET_S)
        return self._run_steps(context, project, request.name, steps)

    def _show_preview(self) -> set[str]:
        """«Vista previa» (RF-017-26, RF-015-26): comprueba lo pedido como al calcular (:meth:`_request`, sin escribir ni calcular nada) y activa con ello la vista previa de la pista (``bl.draw.entity``: antes de
        calcular, el origen, el destino y el pasillo de la ruta); la que hubiera activa se cambia por la nueva. Lo que rechazaría «Calcular» sale en la propia vista previa, como aviso. Se quita al cancelar la orden,
        al Esc a mitad del cálculo, al crearla, con su control y al conmutar a la interfaz de Blender."""
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        try:
            request = self._request()
        except ProfileFormError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        from ...design.preview import RoadAsk  # al usarlo: habilitar no carga el cálculo

        preview = _entity_preview()
        try:
            preview.enable(preview.EntityPlan(road=RoadAsk(request=request, propose=True)))  # una propuesta no es una entidad: no se rechaza la partida que ya ocupa otra (T44, D-1)
        except (RuntimeError, GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, tr("The preview of the entity could not be shown: {detail}", detail=design_error_text(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Showing the preview of the proposed route «{name}»", name=request.name))
        return {"FINISHED"}

    def _finished(self, context: Any, opened: Any) -> set[str]:
        """Con lo guardado llegando (:meth:`_creation_steps`), acaba: la propuesta ya está creada. Si no, como las demás (:meth:`_CalculateAndCreate._finished`): deja el cálculo abierto con su resumen y pide
        confirmar."""
        if self._saved:
            self._saved = False
            return {"FINISHED"}
        done = _CalculateAndCreate._finished(self, context, opened)
        self._show_calculated(opened)  # con su vista previa activa, **el eje con su rasante** de lo que dejó «Calcular» (T44, D-1)
        return done

    @staticmethod
    def _show_calculated(opened: Any) -> None:
        """Con la vista previa de **esta propuesta** activa, la cambia por la de lo que dejó «Calcular» (``opened``: el cálculo abierto): el eje con su rasante, sin sección. Solo lee."""
        _show_calculated_preview(opened, propose=True)

    def _create(self, context: Any) -> set[str]:
        """«Crear» (RF-017-28, RF-015-02): registra la propuesta —**la capa de líneas con Z editable en QGIS** y la operación, en una transacción— sin más confirmación que el botón (no graba ninguna superficie: la
        pendiente media por encima de pm solo avisa). Desde la interfaz, **por pasos** con el avance y Esc (:class:`_CreatesInSteps`: ``Calculation.create_steps``, la transacción final como último paso); desde un
        guion, de una vez, con el mismo resultado. **Una propuesta no es una entidad**: no encadena la capa de entidades ni la de ejes, no declara ni compila nada. Quita la vista previa en cuanto existe."""
        opened = calculation()
        if opened is None or opened.op_type != self.provenance_op_type:
            self.report({"ERROR"}, tr("There is no open calculation: compute first"))
            return {"CANCELLED"}
        started = self._create_in_steps(context, opened)
        if started is not None:  # desde la interfaz, por pasos
            return started
        created = _CalculateAndCreate._create(self, context)
        if "FINISHED" in created:
            _entity_preview_off()  # la propuesta ya existe: ya no se prepara (RF-017-26)
        return created

    def _creation_steps(self, project: Any, opened: Calculation) -> Iterator[Progress]:
        """Los pasos de «Crear» ``opened`` en el modal: los de ``Calculation.create_steps`` (la capa propuesta, montada y escrita en su temporal por pasos; la transacción final, el último) y, en cuanto lo guardado
        llega, lo registrado (:meth:`_registered`) y quitar la vista previa; **nada más**: una propuesta no es una entidad, no encadena ``entity_store.after_entity_change``. Cerrar los pasos antes (Esc) o un
        fallo no dejan nada: ``create_steps`` descarta el cálculo y borra sus temporales."""
        creating = opened.create_steps(budget_s=self.STEP_BUDGET_S)
        saved = None
        try:
            for step in creating:
                if step.result is not None:
                    saved = step
                    break
                yield step
        finally:
            creating.close()
        assert saved is not None  # los pasos acaban siempre con lo guardado
        self._registered(opened)
        self._after_registered()
        self._creating, self._saved = False, True
        yield saved

    def _after_registered(self) -> None:
        """En cuanto lo guardado llega, quita la vista previa: la propuesta ya existe, ya no se prepara (RF-017-26)."""
        _entity_preview_off()

    def _created_text(self, opened: Calculation) -> str:
        from ...design import road_layer  # al usarlo: habilitar no carga el cálculo

        return tr("Route «{name}» proposed in {version}: the layer «{layer}» is editable in QGIS", name=opened.name, version=opened.version,
                  layer=road_layer.route_layer_table(opened.version, opened.name))

    def _status_text(self, step: Progress) -> str:
        """El avance en la barra de estado: «Calculando la propuesta del trazado… 40 % · Esc: cancelar» o «Guardando la propuesta del trazado… 40 % · Esc: cancelar»."""
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        if self._creating:
            return tr("Saving the proposal of the route… {percent} % · Esc: cancel", percent=percent)
        return tr("Computing the proposal of the route… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        if self._creating:
            return tr("Creation cancelled: the route has not been proposed and the calculation has been discarded; nothing has been left half-done")
        return _CalculateAndCreate._cancelled_text(self)


# --- Exportar pista… (spec 017, T33; HU-017-4; RF-017-27, RF-017-29, RF-015-28; H-9; plan 017 §5.3.3 y §5.5; comprobación manual M6) --------------------------------------------------------

EXPORT_ROAD = "geoblender.des_export_road"
EXPORT_ROAD_ITEMS = [
    ("SURFACE", "Surface of the road", "The surface the road leaves in its version, as a deliverable GeoTIFF"),
    ("GRADIENT", "Level profile of the road", "The abscissa, the x and y, the ground elevation, the level profile elevation and the gradient of each station of the axis of the road, in m and in %, as a CSV for a "
                                              "spreadsheet"),
    ("REACH", "What an accessibility reaches", "The cells a walker reaches from the entry points of an accessibility, as a deliverable GeoTIFF of codes with its legend")]
"""Lo que exporta «Exportar pista…» (``design.export.ROAD_EXPORTS``; RF-017-27): la superficie de una pista, su rasante (CSV) y lo que alcanza una accesibilidad."""
_EXPORT_ROAD_WHAT = {"SURFACE": "surface", "GRADIENT": "gradient", "REACH": "reach"}
_CSV_SUFFIX = ".csv"


class GEOBLENDER_OT_des_export_road(_StepsModal, bpy.types.Operator):
    """Write the surface of a road or what an accessibility reaches as a deliverable GeoTIFF, or the level profile of a road as a CSV (it is not an operation: it writes nothing in the project, also from a superseded version and, outside the project, in read-only)"""

    bl_idname = EXPORT_ROAD
    bl_label = "Export road…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    STEP_BUDGET_S = 0.05

    what: EnumProperty(  # type: ignore[valid-type]
        name="What to export", description="The surface of a road (GeoTIFF), its level profile (CSV) or what an accessibility reaches (GeoTIFF)", items=EXPORT_ROAD_ITEMS, default="SURFACE", options=_FIELD)
    source: StringProperty(  # type: ignore[valid-type]
        name="Road or accessibility",
        description="Code or name of the road or of the accessibility of the active version to export (empty: the one of the object selected in the 3D view)", options=_FIELD)
    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.tif;*.tiff;*.csv", options={"HIDDEN"})
    check_existing: BoolProperty(  # type: ignore[valid-type]
        default=True, options={"HIDDEN", "SKIP_SAVE"})
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace", description="Replace the file if it already exists", options=_FIELD)
    confirm: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Con un proyecto abierto y con procedencia: exportar no es una operación (H-9, D-29 de la 011), así que también en solo lectura (fuera del proyecto) y con la versión SUPERADO."""
        reason = SESSION.unavailable()
        if reason is not None:
            cls.poll_message_set(reason)
            return False
        return True

    def _ref(self, context: Any) -> str:
        """La pista o la accesibilidad que se exporta: la que se tecleó (:attr:`source`: su código o su nombre) o la del objeto seleccionado en la vista (de una pista, su entidad; de una accesibilidad, su rejilla de
        lo alcanzable). :class:`ValueError` si no hay ninguna o es de otra versión que la activa."""
        ref = _entity_or_selected(self.source, context)
        if not ref and self.what == "REACH":
            ref = des_panels.wanted(context)
        if not ref:
            raise ValueError(tr("Choose the road or the accessibility to export: select its object in the 3D view or give its code or name"))
        return ref

    def _stored(self, ref: str) -> Any:
        """Lo que se exporta (``design.export.stored_road_export``): una ``StoredGrid`` (la superficie de una pista o lo que alcanza una accesibilidad) o una ``StoredRoad`` (su rasante), de la versión activa. Sin
        versión activa, :class:`ValueError`; ``DesignError`` si la pista no está calculada o no es lo alcanzable de una accesibilidad."""
        from ...design import export  # al usarlo: habilitar no lo carga

        active = scene_versions.active()
        if active is None:
            raise ValueError(tr("There is no active version: make the version of the road the active one first"))
        return export.stored_road_export(SESSION.project, _EXPORT_ROAD_WHAT[self.what], ref, version=active.uid)

    def draw(self, context: Any) -> None:
        """Lo que se exporta y de qué pista o accesibilidad (en el panel del selector de ficheros)."""
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "what", text=tr("What to export"), translate=False)
        layout.prop(self, "source", text=tr("Road or accessibility"), translate=False)

    def check(self, context: Any) -> bool:
        """Lo que Blender llama al cambiar una propiedad con el selector de ficheros abierto: la extensión del fichero sigue a lo que se exporta (``.csv`` la rasante; ``.tif`` lo demás)."""
        if not self.filepath:
            return False
        path = Path(self.filepath)
        rasante = self.what == "GRADIENT"
        if (path.suffix.lower() == _CSV_SUFFIX) if rasante else (path.suffix.lower() in (".tif", ".tiff")):
            return False
        self.filepath = str(path.with_suffix(_CSV_SUFFIX if rasante else GEOTIFF_SUFFIX))
        return True

    def invoke(self, context: Any, event: Any) -> set[str]:
        """El diálogo de fichero, con el destino que propone (``exports/<dato>_<V01>.tif`` o ``.csv`` del proyecto); con ``confirm``, la confirmación de sustituir el que ya existe."""
        self.in_steps = getattr(context, "window", None) is not None
        if self.confirm:
            self.overwrite = True
            return context.window_manager.invoke_confirm(
                self, event, title=tr("Replace the file"), message=tr("«{file}» already exists: replace it?", file=Path(self.filepath).name), confirm_text=tr("Replace"), translate=False)
        try:
            ref = self._ref(context)
            stored = self._stored(ref)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        self.source = ref
        if not self.filepath:
            suffix = _CSV_SUFFIX if self.what == "GRADIENT" else GEOTIFF_SUFFIX
            self.filepath = str(Path(SESSION.project.root, gis_provenance.EXPORTS_FOLDER, f"{stored.record.name}_{stored.version_code}{suffix}"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        """Escribe el entregable desde lo registrado (``design.export``) y **no escribe nada en el proyecto** (H-9): la superficie de una pista o lo que alcanza una accesibilidad, por pasos con el avance y Esc
        desde la interfaz (de una vez desde un guion), y la rasante, a CSV, de una vez. Sobre un fichero que ya existe, solo con ``overwrite`` (desde la interfaz, lo pregunta). Dice en el informe qué escribió y dónde."""
        from ...design import export  # al usarlo: habilitar no lo carga

        blocked = SESSION.unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        shown = self.filepath.strip()
        steps: Iterator[float] | None = None
        try:
            ref = self._ref(context)
            stored = self._stored(ref)
            if not shown:
                raise ValueError(tr("Choose the file to export to"))
            target = Path(bpy.path.abspath(shown))
            if self.what == "GRADIENT":
                export.export_road_csv(SESSION.project, stored.name, target, version=stored.version_uid, read_only=read_only_dirs(), overwrite=bool(self.overwrite))
            else:
                steps = export.export_grid_steps(SESSION.project, stored.family, stored.name, target, version=stored.version_uid, read_only=read_only_dirs(), overwrite=bool(self.overwrite))
        except GisError as exc:
            interactive = self.in_steps and getattr(context, "window", None) is not None
            if exc.code == "gis.export_target_exists" and interactive:
                self.report({"WARNING"}, error_text(exc))
                _confirm_later({"what": self.what, "source": self.source, "filepath": shown}, idname=EXPORT_ROAD)
            else:
                self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        self._file = target.name
        self.report_log: list[str] = []
        if steps is None:  # la rasante a CSV: de una vez, ya escrita
            return self._exported()
        progress = _export_progress(steps, target.name)
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, progress)
            return {"RUNNING_MODAL"}
        try:
            for step in progress:
                if step.result is not None:
                    return self._exported()
        except (GeoblenderError, OSError) as exc:
            self._report({"ERROR"}, design_error_text(exc))
            return {"CANCELLED"}
        return {"CANCELLED"}  # pragma: no cover - los pasos acaban siempre con el fichero

    def _exported(self) -> set[str]:
        """Lo que dice el informe al exportar: qué se escribió y dónde."""
        file = getattr(self, "_file", "")
        if self.what == "GRADIENT":
            text = tr("Level profile of the road exported to «{file}»", file=file)
        elif self.what == "REACH":
            text = tr("What the accessibility reaches exported to «{file}»", file=file)
        else:
            text = tr("Surface of the road exported to «{file}»", file=file)
        self._report({"INFO"}, text)
        return {"FINISHED"}

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Exporting «{file}»… {percent} % · Esc: cancel", file=getattr(self, "_file", ""), percent=percent)

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
            LOGGER.error("La exportación de «%s» se ha parado", getattr(self, "_file", ""), exc_info=exc)
            return self._fail(context, error_text(exc))


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
                             GEOBLENDER_OT_des_entity_release_support,
                             GEOBLENDER_OT_des_entity_refresh,
                             GEOBLENDER_OT_des_entity_bring,
                             GEOBLENDER_OT_des_entity_preview,
                             GEOBLENDER_OT_des_entity_dependents,
                             GEOBLENDER_OT_des_entity_insert,
                             GEOBLENDER_OT_des_entity_calculate,
                             GEOBLENDER_OT_des_remove_stockpile,
                             GEOBLENDER_OT_des_create_body,
                             GEOBLENDER_OT_des_add_buttress,
                             GEOBLENDER_OT_des_edit_stockpile,
                             GEOBLENDER_OT_des_detect_stockpiles,
                             GEOBLENDER_OT_des_stockpile_candidates,
                             GEOBLENDER_OT_des_edit_road_profile,
                             GEOBLENDER_OT_des_save_road_profile,
                             GEOBLENDER_OT_des_create_road,
                             GEOBLENDER_OT_des_road_access,
                             GEOBLENDER_OT_des_propose_road,
                             GEOBLENDER_OT_des_export_road)
"""Las órdenes reales del diseño (la T22 pone «Perfiles de banco…» y su orden interna, la T23
«Sectores de diseño…» y la suya, la T24 «Envolventes y escalonado…», la T25 «Vista previa de
semillas, dominios y restricciones», la T28, la interna que exporta una rejilla a GeoTIFF, y la
T44, la que declara de nuevo los sectores desde su ventana; de la 014, la T20 pone «Límite desde el
perímetro…», la T21 «Cantera con dos superficies…», la T28 «Transiciones con el terreno no
afectado», la T30 «Solo relleno…» y la T33 «Ajustar el diseño a un límite nuevo…», de la entrada
«014», que la T58 entrega; de la 015, la T15 pone «Plataforma…», la T25 «Descartar…» y «Soltar el apoyo…», la T26 «Traer las
entidades de…» y la T29 la vista previa de una entidad, todas de la entrada «015», que entrega la T31 con el menú «Entidad ▾»
(las dos internas nuevas de la T31, «Lo que se apoya en ella» e «Insertar antes o después de…», también; y la T41, «Calcular…»;
y la T43, la interna que lanza «Cambiar parámetro…», sin menú); de la 016, la T20 pone «Retirar un acopio…», interna, de la entrada
«016», que la entrega (la T35 la pone detrás de «Acopio (detectar, retirar)…»); la T25 pone «Cuerpo apoyado…» (``des_create_body``, que la T35 pasa
de la «Unidad por espesor sobre su apoyo…» de Geología al menú Entidades); la T27 pone «Contrafuerte…», con la clave del catálogo
``des_add_buttress``; la T35 pone «Acopio (detectar, retirar)…», «Detectar acopios…» y «Candidatos de los acopios…» y entrega la entrada 016 con
el menú Diseño ▸ Pistas y entidades ▸ Entidades); de la 017, la T29 pone «Perfil de pista…» (``des_edit_road_profile``) y su interna
(``des_save_road_profile``), la T29b, «Pista…» (``des_create_road``), la T30, «Accesibilidad de las pistas…» (``des_road_access``) y la T33 (a), «Proponer el trazado…» (``des_propose_road``) y
«Exportar pista…» (``des_export_road``); **la T33b las pone en el menú** —los cinco primeros puestos de Diseño ▸ Pistas y entidades— y entrega la entrada 017, que sustituye a las tres provisionales de «R-40»)."""
