# Historial de cambios

Todos los cambios relevantes de Geoblender se anotan aquí, escritos para quien lo usa.

Formato basado en [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/).
Versionado según [SemVer 2.0.0](https://semver.org/lang/es/); la versión vive en
`geoblender/blender_manifest.toml`. Mientras la versión sea 0.y.z, cualquier cosa puede
cambiar.

## [Sin publicar]

Geoblender 0.1.0 ya se instala (spec 001), crea y abre proyectos con su sistema de
referencia y su origen local (spec 002), tiene su interfaz (spec 003), ejecuta los cálculos
largos en segundo plano, con un motor de cálculo opcional (spec 004), registra la procedencia
de los parámetros, las entradas, las operaciones y las cifras del proyecto (spec 008) y tiene
su primera función minera, la topografía base: MDT, rejilla de cálculo de paso exacto, TIN,
curvas de nivel y su intercambio con QGIS (spec 006); la segunda, los sondeos: importar tablas y
bases de RecMin, validarlos, calcular sus trazas y verlos en 3D (spec 005). Y la vista de Blender
se pone al día desde el proyecto: marca lo que ya no está al día, lo vuelve a cargar con F5,
ofrece abrir el proyecto de una vista y enseña la ficha del objeto activo, el inventario del
proyecto y las cifras de la selección (spec 010). Y el proyecto tiene versiones con su estado y
sus revisiones, que se congelan en instantáneas que no cambian y se pueden reproducir meses
después, y las decisiones de la propiedad (spec 009). Y cubica: entre dos superficies, por fase,
banco y unidad, con el escombro en su sitio y cada material pesado según su estado, con sus
cifras de la versión (spec 011). Y sabe dónde no se puede cortar ni rellenar: declara el límite
legal y el perímetro de actuación, guarda las restricciones tipadas que también se editan en QGIS,
busca lo intocable por sector, lo compila todo a máscaras sobre la rejilla del proyecto y verifica
en m³ por recinto cualquier superficie de diseño (spec 012). Y calcula el diseño de rejilla:
envolventes de pendiente acotada hacia arriba y hacia abajo de unas semillas, perfiles de banco
con nombre, y el escalonado en corte y en relleno, anclado a cotas absolutas, con la berma de cada
sector, el recorte final y las cotas reales de las bermas, todo visto antes de calcular y
confirmado antes de escribirse (spec 013). Y diseña la cantera completa: el recinto excavable de las
restricciones con las semillas en su coronación, los fondos por polígonos, los corredores, las zonas
a conservar, la superficie final y la de explotación con su orden y su clasificación en desdoblado y
relleno, la transición del borde con el terreno no afectado, el diseño «solo relleno» y el ajuste a
un límite nuevo (spec 014, en curso; sus órdenes ya están disponibles en sus menús). Y pone sobre ella
las entidades de diseño: la plataforma, que se aplica en cadena sobre una superficie, declara lo que
prohíbe a los demás operadores y dice en qué se apoya (spec 015, hecha a falta de verla en pantalla). Y
detecta los acopios de un levantamiento con su plano de base, su huella y su volumen, los retira con lo que se les
apoyaba a la vista, hace el contrafuerte con el pie libre en lo que se admite y los cuerpos apoyados por espesor, y
la verificación de los límites distingue el corte de terreno del de acopios (spec 016, cerrada el 20/11/2026 y vista
en pantalla con eventos simulados, sin ratón real). Lo de
la spec 002 está comprobado también con QGIS 4.2 sin su interfaz (PyQGIS) y en la red con un
solo equipo; falta con dos equipos a la vez, y que IMGA acepte esas pruebas de QGIS y, en lugar
de la del panel del proyecto, las de la interfaz de la spec 003. Lo de la spec 003 está
comprobado en una pantalla de 1920 × 1080
con Windows al 125 %, salvo algunas teclas en modo Blender, la lista de F3 en los dos modos, la
barra T de Blender, la fila 1, el clic derecho, Mayús+Alt+B y la chincheta, la fila 2 en
edición, dos idiomas de entrada, la plantilla instalada en el Blender de cada uno, la revisión
de los iconos y la lectura de la barra con tres ingenieros. Lo de la spec 004 está comprobado en
esa misma pantalla, con el motor de cálculo instalado desde un almacén de ruedas en el disco
del equipo; falta el almacén del NAS de IMGA. Lo de la spec 008 está comprobado con Blender
5.2.1 sin su interfaz, con datos sintéticos (también el volumen de un proyecto grande), con el
GDAL de QGIS 4.2 y con QGIS 4.2 sin su interfaz (PyQGIS: una capa del proyecto editada y lo
importado protegido), migrando un proyecto creado con la spec 002, en la pantalla de referencia
(paneles, diálogos, barra de estado y Ctrl+Z) y en `Z:` con un proyecto entero el 10/10/2026;
faltan con QGIS con su interfaz y la demostración de sus cuatro escenarios con un ingeniero. Lo de la spec 006 está
comprobado con Blender 5.2.1 sin su interfaz, con datos sintéticos y casos de referencia
analíticos (también del tamaño de Silvestre), con el GDAL de QGIS 4.2 y con QGIS 4.2 sin su
interfaz (PyQGIS), y en la pantalla de referencia el 12 y el 14/10/2026 (del MDT a la vista, el
TIN con roturas, las curvas con maestras, los niveles de detalle, la interfaz y la procedencia);
faltan que un ingeniero de IMGA haga sin ayuda el recorrido completo hasta QGIS (CE-006-04) y la
comparación con el MDT real de Silvestre (CE-006-05), que se ejecuta a petición. Lo de la spec 005
está comprobado con Blender 5.2.1 sin su interfaz, con datos sintéticos (también del tamaño de una
campaña de 2 000 sondeos) y casos de referencia analíticos, con bases de RecMin sintéticas de los
dos formatos, con el GDAL de QGIS 4.2 y con QGIS 4.2 (sin su interfaz y, la vista 3D, con ella),
y en la pantalla de referencia el 15/10/2026 (la importación, la base de RecMin, la vista y la
procedencia; lo que salió se corrigió después, con sus pruebas); faltan que un ingeniero de IMGA
importe la base de ejemplo y la vea en 3D sin ayuda (CE-005-04), la comparación con una base real
de RecMin (CE-005-05), que se ejecuta a petición, y los puestos de IMGA con el motor de Access. Lo
de la spec 010 está comprobado con Blender 5.2.1 sin su interfaz, con datos sintéticos (también
con el volumen de un proyecto grande: 20 000 datos en el proyecto y 200 en la vista) y en `Z:`, y
el recorrido del MDT y los sondeos, con las órdenes reales, y en la pantalla de referencia el
18/10/2026 sin ratón; falta, con el ratón, Esc a mitad de F5, «Ahora no», recuperar la última
sesión y los paneles a 1920 px. Lo de la spec 009 está comprobado con Blender 5.2.1 sin su
interfaz, con las órdenes reales y un proyecto sintético (sus dos escenarios de principio a fin),
con QGIS 4.2 sin su interfaz y en `Z:`; falta verlo en la pantalla de referencia (el control de
la versión activa, el avance de congelar, los colores del Outliner, el renombrado y los
diálogos). Lo de la spec 011 está comprobado con Blender 5.2.1 sin su interfaz, con las órdenes
reales y un proyecto sintético (sus cinco escenarios de principio a fin, dos veces, con las mismas
cifras), con casos de referencia analíticos, con datos del tamaño de un proyecto real y en `Z:`,
y en la pantalla de referencia el 24/10/2026 con la escala 1,0 (los diálogos, el avance y Esc, la
rejilla de diferencias en la vista y el panel; lo que salió se corrigió después, con sus
pruebas); faltan la pantalla con la escala 1,25, el CSV abierto en Excel y el GeoTIFF en QGIS,
que un ingeniero de IMGA entregue sin ayuda la cubicación de un levantamiento y la comparación
con el proyecto de referencia, que se ejecuta a petición. Lo de la spec 012 está comprobado con
Blender 5.2.1 sin su interfaz, con las órdenes reales y un proyecto sintético (sus cinco
escenarios de principio a fin, en dos procesos, con las mismas cifras), con casos de referencia
calculados a mano (los recuentos de celdas, la torre, el perímetro, el redibujado, la balsa y las
versiones) y con datos del tamaño de un proyecto real (500 restricciones, 2,8 millones de celdas y
diez capas de 10.000 entidades) en disco local, y pasó su verificación única (01/11/2026), cuyos
hallazgos ya están corregidos; faltan verlo en la pantalla de referencia, la capa de restricciones
editada en QGIS 4.2, las medidas en `Z:`, la comparación con el proyecto de referencia, que se
ejecuta a petición (CE-012-08), que un ingeniero de IMGA declare los límites y las restricciones de
un GeoPackage sintético, busque los intocables de un sector y verifique un diseño en menos de 15
minutos y sin ayuda (CE-012-09). Con varios límites legales, la zona, la cifra y la banda hacia
dentro de cada uno son las suyas y no las de la unión (el hallazgo F-1 de esa verificación, decidido
por Samuel el 01/11/2026 y corregido). Las llamadas de «Recalcular lo obsoleto» tardan de 0,40 a
0,55 s, más que los 0,2 s de las demás (el contrato de la spec 008). Lo de la spec 013 está
comprobado con Blender 5.2.1 sin su interfaz, con las órdenes reales y un proyecto sintético (sus
escenarios E1 a E5 de principio a fin: semillas, vista previa, envolvente, escalonado en corte y en
relleno, confirmar, congelar, reproducir y exportar), con casos de referencia calculados a mano (el
cono de un punto, el punto fijo, el escalonado de referencia, la berma de 19,58 m, el recorte
final, las máscaras, la corta circular de 1.308.944 m³) y con datos del tamaño de un proyecto real
(una rejilla de 2,8 millones de celdas, 20 sectores, 10 perfiles y 500 restricciones) en disco
local, y pasó su verificación única (04/11/2026), cuyos hallazgos ya están corregidos (la marca de la
búsqueda pendiente sale también junto a las cifras); faltan verlo en la pantalla
de referencia (los colores de la vista previa, los diálogos, el avance y Esc, la barra N «Diseño»),
el GeoTIFF abierto en QGIS 4.2, las medidas en `Z:`, la comparación con el proyecto de referencia,
que se ejecuta a petición (CE-013-10), y que un ingeniero de IMGA defina una semilla, elija un
perfil y un sector con talud impuesto, revise la vista previa y confirme una superficie de diseño en
menos de 15 minutos y sin ayuda (CE-013-11). Lo de la spec 014 está comprobado con Blender 5.2.1 sin
su interfaz, con las órdenes reales y proyectos sintéticos (las dos superficies con los dos órdenes,
su clasificación y «explotación hasta la final», la transición, «solo relleno», la comprobación al
compilar las máscaras, el ajuste y la exportación), con casos de referencia calculados a mano
(CE-014-01 a CE-014-08: las semillas en toda la ladera, la zona a conservar, el corredor de 200 m,
100 diseños con los dos órdenes cuadrados con la cubicación, la zona de 2 ha sin explotar, el escalón
creado junto a un escarpe, el tendido junto a la torre y el ajuste con 60° y 35°) y con datos del
tamaño de un proyecto real (2,8 millones de celdas y 20 sectores) en disco local, y pasó su
verificación única (13/11/2026), cuyos hallazgos ya están corregidos (los que pedían una decisión,
con la que tomó Samuel ese día); faltan verlo en la pantalla de referencia, el GeoTIFF abierto en
QGIS 4.2 con su ventana, las medidas en `Z:`, la comparación con el proyecto de referencia
(CE-014-09) y que un ingeniero de IMGA diseñe una cantera con dos superficies, revise la
clasificación y la cree en menos de 20 minutos (CE-014-10).

### Añadido

- **Acopios, contrafuerte y cuerpos apoyados** (spec 016, R-36, segunda spec; cerrada el 20/11/2026: verificada sin pantalla y vista
  en pantalla con eventos simulados, sin ratón real). En el proyecto de referencia los acopios, el contrafuerte y el escombro de una ladera se hicieron con scripts sueltos, y cada
  uno costó un error: 77 montones sin filtrar en lugar de los 9 acopios de la propiedad; acopios cubicados con la litología de la roca y
  pesados con la densidad in situ (un 23 % de más); un acopio de 12 m retirado junto a un relleno, con una cara a más de 45°; un relleno
  que seguía apoyado en un acopio que la versión siguiente retiraba; un contrafuerte recortado a su zona, con el pie en una zona de solo
  restauración y una cara de 60 a 70°; y espesores negativos al interpolar la cota de la base de un cuerpo. Con el marco de la 015
  (la cadena, lo que declara cada entidad, lo que se le apoya), Geoblender hace ahora los tres. Guía de uso:
  `docs/usuario/acopios-y-contrafuertes.md` de la documentación. Menú **Diseño ▸ Pistas y entidades ▸ Entidades ▸ Acopio (detectar,
  retirar)…, Contrafuerte… y Cuerpo apoyado…** (este último sale de Geología, donde era la «Unidad por espesor sobre su apoyo…»):
  disponibles con un proyecto en escritura y una versión activa que se puede editar (la detección sobre una superficie del proyecto, también
  sin versión activa) y en gris con su motivo en los demás casos. Como en las demás, hasta **Crear** no se escribe nada, todo va por pasos y
  **Esc** cancela sin dejar nada a medias.
  - **Detectar acopios…** (en **Acopio (detectar, retirar)…**): con una capa de polígonos con una marca por acopio (con su `margen`, su
    `material` y su `base`, si la capa los tiene), da en **una sola operación**, por cada marca, su **plano de base** (ajustado al terreno
    llano que la rodea), su **huella**, su **volumen sobre la base** y su espesor máximo, con los avisos: la huella llega al borde de la
    marca, hay más de una zona, la corona tiene poco terreno llano, el plano se limitó por inclinado, el plano y la huella no se
    estabilizan, y las celdas que dos acopios comparten, repartidas entre los dos. **La marca ha de rodear el pie del montón**: con una
    marca dentro del pie de un acopio alto el plano sale torcido (1,64 m de error en la base de un acopio de 12 m). Con **Buscar
    candidatos sin marca** lista los montones que pasan la altura y el área, y **ninguno sin filtrar**; cada uno se **convierte en acopio
    o se descarta con un motivo**, y al repetir la detección conserva su decisión si su huella casi no cambió. **Dos marcas solapadas se
    rechazan, solo ellas dos**, y las demás se detectan. El **azimut** del plano es el de la máxima pendiente hacia donde sube. La **vista
    previa** dibuja las marcas con su margen antes de calcular. La detección es **del proyecto** si parte de una superficie del proyecto (el terreno o un
    levantamiento), y de la versión si parte de una de la versión. Cambiar un umbral, o la capa de marcas en QGIS (también su margen o su
    material, no solo su geometría), deja obsoleta la detección. Un montón que toca el borde de la rejilla no sale como candidato.
  - **Lo que deja la detección**: la **base** y el **espesor** de los acopios de cada material, el **terreno sin acopios** y la superficie
    con que se detectó, solo en las huellas, que se ven en la vista y se exportan a GeoTIFF; y una **capa en QGIS con una fila por
    acopio**. La **cubicación (011)** toma cada material como una unidad antrópica con su base y su espesor y la pesa con la densidad
    suelta: se añade en **Materiales y densidades…**, eligiendo la base y el espesor por su nombre (no hay un botón que las añada) y
    **comprobando su estado**: una unidad antrópica nueva nace «Suelto» (un acopio no está in situ) y, si la deja en «In situ», el acopio se
    pesa un 23 % de más sin ningún aviso, así que revise el estado de cada unidad de acopio. Su volumen es el de la detección y no da
    toneladas propias.
  - **Retirar un acopio…**: baja la huella hasta su base, unida al terreno por una **transición** con el ángulo que se declare (sin valor
    por defecto), dentro de los límites aunque su corte no esté admitido (bajar un acopio no es cortar terreno); da lo retirado, lo que se
    le apoyaba, la transición y lo que los límites no dejan retirar. **Antes de calcular** enseña **una sola lista de todo lo que se le
    apoya** (un relleno, un contrafuerte, la superficie de otra versión) y **no lo retira sin su confirmación**; lo que se apoyaba queda
    en «apoyo retirado» —también si la detección es del proyecto, que es lo normal, y si el relleno se hizo antes que la detección— y
    «Recalcular lo obsoleto» no lo rehace hasta que se decida. **Lo que no se puede retirar avisa** (por ejemplo, un acopio cortado por el
    perímetro de actuación) con su volumen y su lugar. **Las celdas de la huella sin dato también avisan**, en la retirada y en el
    contrafuerte (no se retiran ni suben, no cuentan en el volumen y no impiden crear): el resumen dice cuántas son, su área y dónde
    está la primera. La **pared** que quede donde los límites no dejan retirar se mide siempre y,
    si la hubiera, se avisa con su altura, su inclinación y su lugar y no se crea sin confirmar (con más de 45° y 3 m, además con un
    motivo que queda registrado); con la transición que usa, ninguna cara creada pasa del ángulo, así que no salta en el uso normal. Con
    **Como plataforma**, deja la huella entera en el plano de su base y crea con ella una **plataforma**, con su eje
    de borde a borde, su borde y sus comprobaciones (no mide la pared de la retirada: la cara del borde de la plataforma es un aviso de
    la plataforma). No se retira un acopio cuya detección está obsoleta; si el contrafuerte que protege dejó obsoleta la detección,
    primero hay que pulsar «Recalcular lo obsoleto».
  - **Contrafuerte…**: un relleno al pie de un talud desde una **zona de coronación** (una capa de polígonos), con un perfil de banco, una
    cota de coronación **que ha de ser la de un ancla del perfil** (si no, se rechaza con la cota del ancla más próxima) y, si se quiere, un
    alcance. **El pie no se recorta a la zona dibujada**: llega donde caiga dentro de lo admitido, **también en las zonas de solo
    restauración**, y **no corta nada**. Si el borde de lo admitido le quita parte del pie, el resumen avisa con el área, el volumen y el
    salto creado (es el único aviso del salto del borde: uno genérico saltaría en casi todo contrafuerte). Avisa también de la zona que
    la rejilla recorta y de lo que sube hasta el borde de la rejilla o a celdas sin dato, y del orden con la otra superficie de una
    cantera. La superficie en que **se apoya** es solo una dependencia: no cambia el cálculo, que parte de su partida. **Declara «sin corte» sobre su zona de coronación** (con su resguardo, obligatorio) para todos los operadores, y se ve en
    «Ver restricciones y límites».
  - **Cuerpo apoyado…**: un volumen desde sus **espesores** (en puntos, en polígonos o en las líneas 3D con el espesor en su Z), «sobre una
    base» o «bajo un techo» (el escombro existente), **sin espesores negativos**: se interpola el espesor, nunca la cota de la base. Las
    celdas a más de la **distancia máxima** de un dato (obligatoria, sin valor por defecto) se avisan con su área, su volumen y su lugar; los
    datos fuera de la huella se ignoran con aviso. **La M de las líneas 3D no se admite** (la importación de capas no la guarda): se
    rechaza. Las líneas 3D han de ser líneas de rotura del proyecto. Un cuerpo «sobre una base» que termina en un escalón en el borde
    de su huella lo dice con un renglón informativo. Con «espesor cero en el borde» el cero se promedia con el dato de las celdas de
    borde. Un cuerpo con secciones muy separadas avisa de que tardará más de lo previsto (8 secciones a 200 m en 100 ha tardan 12 s).
  - **Cifras y su tipo.** Los umbrales de la detección son los del proyecto de referencia, ADOPTADO «sin confirmar» (margen 10 m; corona de
    1 a 3 m; pendiente de corona 12°; área llana mínima 10 m²; residuo máximo 1 m; 4 y 6 vueltas; candidatos desde 2 m de altura, de 150 a
    20.000 m²): **ninguna la ha confirmado la propiedad**. **La inclinación máxima del plano de base (4°) y el cuantil de apoyo (0,6) son
    HIPÓTESIS**: el volumen de un acopio con el plano limitado lleva esa marca. **El diámetro de apertura de los candidatos (31 m) no está
    confirmado** (es HIPÓTESIS): con los filtros de la V10 salen 74, 20 o 135 candidatos según se lea «31 m» como diámetro, como 31 celdas o
    como radio, y la V10 daba 60; es una cifra que decide Samuel con el expediente delante. Los 45° y 3 m de la pared que pide un motivo
    son ADOPTADO «sin confirmar». El ángulo de transición de la retirada, la cota de coronación y la
    distancia máxima de un cuerpo **no tienen valor por defecto**: los declara quien los usa.
  - **Lo que cambia del marco de las entidades de la 015**: «Cambiar parámetro…» vale para los cinco tipos de entidad (rechaza un nombre
    vacío o repetido y un resguardo que falta, sin escribir nada, y al instante pone al día lo que declara; no admite «proteger» en
    una retirada, un cuerpo ni una detección); la capa de entidades de QGIS se pone al día tras «Recalcular lo obsoleto» con cualquier
    entidad; traer las entidades de otra versión re-apunta la superficie conocida de un cuerpo (y avisa si la referida no se trae).
  - **Lo que no hace todavía**: se vio en pantalla (20/11/2026, con eventos simulados y sin ratón real), pero no la ventana
    «Materiales y densidades…» con el ratón, los botones de candidatos de la barra N, la barra N de la retirada, del contrafuerte y del
    cuerpo, ni la capa de entidades en QGIS con ventana; no se contrastó con el banco del proyecto de referencia (CE-016-08: ni la
    plataforma del acopio 7 ni la transición, que queda sin ejecutar con los datos originales de la V10); un cuerpo con secciones muy separadas
    pasa de los 10 s que pedía la spec (avisa antes; la spec lo admite con el aviso); la pared no salta con la transición del plan y
    «como plataforma» no la mide; «Calcular…» solo ofrece plataformas, así que lo traído de otra versión de los demás tipos queda sin
    calcular; la retirada y el contrafuerte toleran las celdas sin dato de su huella (una excepción escrita de la spec: se dejan como
    están y no cuentan en el volumen) y las avisan con su lugar; y una verificación
    hecha con una detección obsoleta no queda obsoleta sola al recalcularla (hay que verificar otra vez). Lo que vio la pantalla y no se
    arregló: «Recalcular lo obsoleto» no rehace nada mientras una unidad espera una decisión, y su contador de obsoletos sube en cada
    intento fallido junto a una plataforma protegida; dos textos repiten una palabra; el título del objeto de la detección dice «NO AL
    DÍA» hasta recargarlo; y la leyenda de la vista previa queda debajo del diálogo.

- **Entidades de diseño paramétricas** (spec 015, R-36, hecha a falta de verla en pantalla). Lo que se pone encima de una cantera
  (la plataforma de la planta, una balsa, un acopio) se hizo en el proyecto de referencia como
  recortes de ráster y scripts sueltos, y ninguno sabía qué prohibía a los demás ni en qué se apoyaba:
  una plataforma impuesta como cota mínima quedó como un lomo de 5 m; su corredor de extremos
  redondos la alargó 140 m; la programación lineal rellenó un 17 % de una balsa (4.300 m³) porque
  ningún operador sabía que no se rellenaba, y un relleno siguió apoyado en un acopio que la versión
  siguiente retiraba. En Geoblender, una **entidad de diseño** se aplica **en cadena** sobre una
  superficie, **declara lo que prohíbe** a los demás operadores y **dice en qué se apoya**; la
  primera es la **plataforma** (los acopios, el contrafuerte y los cuerpos apoyados usarán el mismo
  marco en la spec 016). Guía de uso: `docs/usuario/entidades-de-diseno.md` de la documentación. Menú
  **Diseño ▸ Pistas y entidades ▸ Entidades ▸ Plataforma…** y menú contextual **Entidad ▾** (con una
  entidad seleccionada): disponibles con un proyecto en escritura y una versión activa que se puede
  editar, y en gris con su motivo en los demás casos.
  - **Plataforma…**: un eje con su ancho (una capa de líneas) o un polígono (con su eje enlazado o, sin
    él, su eje principal, con aviso), con la cota inicial y la pendiente de su rasante, que el diálogo
    propone de la capa y deja corregir. En el modo **en corte** (el de por defecto) baja el terreno
    hasta la rasante dentro de su huella y **no sube nunca** (el lomo de 5 m no se repite); en
    **en corte y relleno**, también lo sube donde se admite el relleno. Su **borde** la une con el
    terreno con su ángulo y su alcance (obligatorio: sin tope, en una ladera empinada el talud
    cortaría toda la ladera), solo donde las máscaras de las restricciones lo admiten, y avisa de las
    paredes más empinadas, de lo que queda por debajo de la rasante, de lo que no mueve por una
    restricción de otra entidad y del salto creado. Un perfil que sube en contra del sentido de la
    rasante no se crea sin confirmación expresa. **Calcular** enseña el resumen sin escribir nada,
    con lo que quedará obsoleto al crearla; el botón **Vista previa** dibuja antes de calcular la
    huella, el eje con su flecha, las cotas de los extremos, lo que se le apoya y lo que declarará; y
    solo **Crear** registra, en una transacción. Un valor sin valor por defecto que falta, una
    geometría que se corta a sí misma o falta dato en la huella se rechazan nombrando la capa, la
    entidad, el campo y el valor. Tras su verificación (15/11/2026): el factor de malla del borde es de 0
    a 1, como el de la envolvente (con más de 1, toda la pared salía como una pared de más); un eje enlazado
    que discurre sobre el contorno del polígono se rechaza, y su abscisa 0 es donde la línea entra en el
    polígono, que es lo que dicen ahora la vista previa y el diálogo; el borde **no avisa la pared que el
    terreno ya tenía** en esa celda, porque no la crea; y la barra N enseña «En corte» y «Euclídea exacta»
    en vez de «cut» y «exact». **Si la geometría sale de la rejilla del proyecto**, la plataforma se calcula
    con la parte de dentro y el resumen, la vista previa y el informe dicen cuántos m² de huella quedan fuera
    y dónde está la primera (antes se calculaba recortada y sin aviso: un eje de 80 m pegado al borde daba la
    mitad de la huella); no se rechaza. **Calcular** con las máscaras obsoletas las compila antes, como
    operación propia que no se deshace con Esc una vez terminada.
  - **Lo que declara**: con **Proteger** y un resguardo, la huella de la plataforma es una zona
    **sin relleno** para **todos** los operadores, por las máscaras de la 012 (el error 51: un
    «solo relleno» y otra plataforma que la solapa rellenan 0 m³ en ella y la verificación da
    «cumple»). En «Ver restricciones y límites» la restricción lleva su entidad («Plataforma P1
    (declarada)») y no se cambia desde ahí: se cambia en la entidad. Si se edita en QGIS, se
    bloquea y las máscaras no se compilan hasta aceptar la edición con un motivo. Tras la verificación:
    si Esc o un fallo cortan lo que sigue a «Crear» antes de la primera declaración de una versión, las
    máscaras salen obsoletas con su causa y la próxima plataforma o **Compilar las máscaras** declara y
    compila antes (antes, una plataforma «en corte y relleno» sobre su huella rellenaba 420 m³ sin ningún
    aviso: el error 51 por otro camino); cambiar el resguardo de una plataforma que protege deja al día la
    entidad, las máscaras y la capa con «Recalcular lo obsoleto» sin repetirlo (antes, tres veces); editar en QGIS
    la tabla de la propia entidad (su huella) bloquea la declaración y las máscaras con un error que nombra la
    entidad (antes, la zona pasaba de 1.653 a 133 celdas sin avisar); aceptar con un motivo la edición de la
    tabla de lo declarado limpia lo que esperaba a esa edición sin deshacer lo aceptado; y la restricción de
    un proyecto con el código de una declarada se rechaza con un texto que dice que la declara una entidad.
  - **La cadena y lo que se apoya**: de cada superficie parte una sola entidad; **insertar antes o
    después** de otra rehace el orden y deja obsoletas las siguientes con su causa. Una operación
    que rellena sobre la huella de una entidad **se apoya en ella** (al crearla y también al
    recalcularla, aunque la entidad apareciera después); **Lo que se apoya en ella**
    enseña la lista única (con los m³), **Descartar…** no borra nada y deja lo apoyado en
    «apoyo retirado» (fuera de «Recalcular lo obsoleto» hasta que se rehaga, se descarte o se dé por
    bueno con **Soltar el apoyo…** y un motivo), y **Traer las entidades de…** copia sus definiciones
    de otra versión «sin calcular». Tras la verificación: **Calcular…** (menú **Entidad ▾**) calcula las
    entidades que quedan sin calcular, traídas o heredadas, con los parámetros que ya tienen y sin escribir
    ninguno, y se detecta de nuevo aquello que se les apoya (antes no se podían calcular desde la interfaz:
    «Plataforma…» las tomaba por nuevas y chocaba con su nombre o su partida); «Cambiar parámetro…» rechaza
    lo que crear rechazaría (un nombre repetido o vacío, una partida que otra entidad ya usa o en ciclo, un
    apoyo en ciclo y proteger en el modo «en corte y relleno»), nombrando la entidad, el campo y el valor, e
    insertar antes de una entidad ya no ofrece como apoyo lo que sería un ciclo; una entidad descartada
    **no vuelve** al plan de «Recalcular lo obsoleto» ni falla cada vez que se recalcula, y lo que se apoyaba en ella se
    rechaza diciendo que espera una decisión; y un «solo relleno» creado antes que la plataforma sobre la que
    rellena gana su dependencia al recalcularlo (antes solo la ganaba al crearse).
  - **Cambiar una entidad** deja obsoleta la plataforma y, en cascada, todo lo que depende de ella;
    **Recalcular lo obsoleto** lo rehace en orden de dependencia, y **una sola pulsación** de «Recalcular lo
    obsoleto» recorre toda la cadena (al verlo en pantalla, el 18/11/2026, con cuatro plataformas encadenadas y
    la cota de la primera cambiada, cada pulsación rehacía una sola y había que pulsar de nuevo hasta que no
    quedara nada obsoleto): la orden vuelve a planificar sola mientras quede algo que rehacer, con su avance y
    Esc como siempre, sin rehacer lo apoyado en una entidad descartada y sin repetir lo que ya no se puede
    rehacer, con un tope contra los bucles que avisa si se alcanza. El resumen de «Calcular» y lo que dice la orden
    al terminar nombran **la capa de entidades de V01** y **las restricciones declaradas de V01** (antes, el
    identificador interno de su tipo, «des.entity_layer»). **Congelar** pide verificar la
    última superficie de cada cadena (las intermedias se verifican a petición; si la cadena parte de la
    superficie de una cantera de la 014, también esa: nunca pide de menos, decisión de Samuel del
    15/11/2026), y la revisión congelada no cambia y se reproduce.
  - **En la vista y en QGIS**: la barra N **Entidad** enseña el estado con su causa, los parámetros
    con su origen, lo que declara, la cadena, en qué se apoya y lo que se le apoya y las cifras; la
    capa de entidades (`des_enl_<vNN>`) abre en QGIS con un estilo por tipo y por estado, y la
    superficie de cada entidad se exporta a GeoTIFF. El estado que dice la capa es el del registro: se pone
    al día también tras cambiar un parámetro, al dar por bueno un apoyo y al terminar «Recalcular lo
    obsoleto»; si Esc o un fallo cortan lo que sigue a una orden antes de la capa, queda marcada y se pone al
    día con la próxima orden de entidades. **Esc vale también mientras «Recalcular lo obsoleto» pone al día
    la capa** (acaba en ese momento y la capa queda marcada).
  - **Cambios en la spec 012** (0.3 y 0.4): la compilación de las máscaras consume también las
    restricciones que declaran las entidades (RF-012-29) y unas máscaras se dan por obsoletas si
    llega una declarada que no consumieron (el hueco por el que el error 51 se habría repetido);
    una entidad que protege queda obsoleta al crearse y «Recalcular lo obsoleto» le quita la marca
    si su resultado no cambia, para lo cual las máscaras que solo están obsoletas por ese ciclo se
    entregan como al día: es la excepción de RF-012-17 que aprobó Samuel el 15/11/2026.
  - **Medido** (2,81 millones de celdas, en disco local): una plataforma de 10 ha, de «Calcular» a
    «Crear», en 1,5 s; recalcular una plataforma de 1 ha lee 8 de 98 teselas de la superficie y de
    las máscaras (de 0,25 a 0,11 s de CPU en el núcleo; la peor llamada del hilo de Blender, de 0,09 a
    0,13 s); recalcular una cadena de 20 plataformas, en unos 24 s; lo que se apoya en una
    entidad, con 200 entidades, en 0,02 s. Un eje digitalizado con muchos vértices ya no bloquea Blender:
    el de 1,8 km con 400 vértices tardaba 8 s de una sola llamada, sin progreso ni Esc, y ahora, 0,1 s en
    pasos de pocos milisegundos que se cancelan (con 2.000 vértices, de 44 s a 0,3 s); la huella y las
    cotas son las mismas, bit a bit. Cada entidad guarda su superficie en la rejilla entera:
    unos 16 MiB (con ruido en las cotas) y unos 0,3 GiB con 20 entidades; el tope (RNF-015-09), de 17 MiB
    por entidad, lo decidió Samuel el 15/11/2026. Activar la vista previa con 200 entidades tarda 0,77 s,
    y Esc en «Recalcular lo obsoleto» acaba en menos de 0,2 s.
  - Lo de la spec 015 está comprobado con Blender 5.2.1 sin su interfaz, con las órdenes reales y
    proyectos sintéticos, con casos de referencia calculados a mano (CE-015-01 a CE-015-05 y
    CE-015-07) y con datos del tamaño de un proyecto real y cadenas de 20 entidades, y pasó su verificación
    única (15/11/2026, cinco verificadores independientes con sus propios cálculos a mano y pruebas de
    mutación: 46 hallazgos, ya corregidos o decididos); faltan verlo en
    pantalla (el diálogo, la vista previa, la barra N, el menú «Entidad ▾»), la capa abierta en QGIS
    4.2 con su ventana y que un ingeniero de IMGA cree una plataforma, la
    proteja y vea lo que queda obsoleto al cambiarla en menos de 20 minutos (CE-015-06). Aún no hay
    objeto en la escena para una plataforma sin calcular; «Recalcular lo obsoleto» no ve lo que Esc dejó a
    medias tras «Crear» (la próxima operación que use las máscaras o **Compilar las máscaras** lo hace); el
    enlace de un polígono con su eje no pasa a la versión que trae o hereda la
    entidad; y declarar que algo se apoya en una entidad solo se puede por parámetro o por la API (decisiones
    de Samuel, 15/11/2026: para la spec 016 o después).
- **Cantera con dos superficies** (spec 014, en curso). Con las envolventes y el escalonado se hace
  una corta, pero no la cantera completa de un proyecto; lo que pasó en el proyecto de referencia
  (semillas en toda la ladera y fondos altísimos; una ladera a conservar enterrada, 58.167 m³; un
  corredor con los extremos redondos 140 m más largo; hasta 36 m de «desdoblado» porque la explotación
  no llegaba a la final; 39.000 m³ falsos al ajustar el muro de explotación a un límite nuevo con el
  ángulo de la final; escalones de 3,6 a 4,7 m en el borde, medidos como salto absoluto; un tendido
  «solo de relleno» que rebajó 26,6 m el montículo de una torre) no se puede repetir. Guía de uso:
  `docs/usuario/cantera-con-dos-superficies.md` de la documentación. Menú **Diseño ▸ Cantera**
  (Límite desde el perímetro…, Cantera con dos superficies…, Ajustar el diseño a un límite nuevo…,
  Solo relleno…) y **Restauración ▸ Superficie final ▸ Transiciones con el terreno no afectado…**: sus
  órdenes están **disponibles en sus menús**, como las de la spec 013 (con un proyecto en escritura y
  una versión activa que se puede editar), desde que se entregó su entrada del catálogo, antes de
  verla en pantalla.
  - **Límite desde el perímetro…**: el recinto excavable de la versión activa, el corte admitido por
    sus máscaras (perímetro ∩ límite legal, menos intocables, exclusiones, el resguardo hacia dentro
    y las zonas sin corte) con dato de terreno, con su área en m². Vacío, se rechaza diciendo el área
    de cada parte que lo vacía, una frase por parte (también en inglés: antes, en inglés, las partes
    salían en español).
  - **Cantera con dos superficies…**: la superficie final y la de explotación en una sola orden, cada
    una con sus semillas, su perfil base y el de cada sector, su ancla y el *chamfer* 5×5 (la
    euclídea exacta, que se ofrecía y se rechazaba siempre, ya no se ofrece, y pedirla desde un guion
    se rechaza antes de leer nada nombrando la cantera y la superficie). Un botón **Vista previa** en
    su diálogo enseña, sin calcular ni escribir nada, el recinto, la coronación, las zonas a sostener,
    los fondos, las zonas a conservar y los corredores con su leyenda (antes solo se activaba desde un
    guion). Las semillas «Coronación y zonas a sostener» siembran el terreno solo en el anillo que
    rodea el recinto (3 celdas, Adoptado «sin confirmar») y en los intocables y las zonas sin corte;
    con las de la 013, las que caen fuera se avisan por grupos con su área y su centro **antes de
    calcular**, en una ventana que pide confirmarlas («Calcular con ellas»; desde un guion,
    `confirm_outside=True`), sin escribir nada hasta entonces (su verificación encontró que el aviso
    salía después de calcular). Las **cotas de fondo** se dan con una capa de polígonos (un fondo es
    un suelo; dos que se solapan o una cota imposible se rechazan nombrando la capa, el polígono, el
    campo y el valor); los **corredores**, con una capa de líneas, su ancho y una cota o una rasante,
    con los extremos planos (un eje de 200 m mide 199 m, no 220), también cuando el primer o el último
    tramo es más corto que medio ancho (su verificación encontró que ese extremo salía redondo: el eje
    de 200 m digitalizado en dos tramos, de 198 y 2 m, daba 4.118 celdas en lugar de 4.000), con su
    cota en las del terreno ± 1.000 m como un fondo (antes, un corredor a 5.000 m anulaba la corta sin
    avisar) y, si queda por encima del terreno, en el aviso de los fondos sobre el terreno; una **zona
    a conservar** tiene su techo de conservación, con su talud (sin valor por defecto), y no se excava
    ni se entierra (si un diseño moviera algo en ella, es un error del diseño, con el volumen y el
    centro de cada parte, y no se crea nunca); y el ancla **«Al fondo de cada muro»** pone las bermas
    de cada muro a la cota de su fondo más k bancos (con un corredor con rasante, siguen su rampa). El
    **orden del diseño** («Primero la superficie final», por defecto, o «Primero la superficie de
    explotación») sube la explotación o baja la final, y nunca se crean unas superficies sin
    `final ≤ explotación ≤ terreno` a 1 mm, tampoco al ajustar las dos a un límite nuevo (abajo). Las
    celdas que cambió la regla (en el resumen, en el informe de la cantera y en la nota del ajuste)
    se cuentan con esa misma tolerancia, las que cambian más de 1 mm: antes contaban también las que
    cambiaban por el ruido del cálculo (en una sonda de su verificación, 4.806 de 7.146 celdas, por
    menos de 4·10⁻¹³ m); en las pruebas, la cantera de prueba pasa de 76.571 a 76.570 celdas, el
    ajuste de prueba de 140 a 84 y algunos de los 100 diseños de referencia, de 328 a 327 o de 234
    a 230. Cada superficie se compara con la misma de la cantera del mismo nombre de la revisión congelada más
    reciente (el aviso de magnitud de la spec 013); sin ella, una sola nota con el nombre de la
    cantera (antes, dos notas que no comparaban nada). La diferencia se **clasifica** en
    desdoblado, relleno de restauración (en una capa de zonas) y sin diferencia (el espesor mínimo de
    la verificación), con sus m³ y ha por sector, iguales a los de la cubicación sobre las mismas
    rejillas. Si la explotación no llega a la final en zonas de más de 1 m de desdoblado sobre terreno
    sin explotar y de más de 0,2 ha (una zona de justo el área mínima no se avisa, cualquiera que sea
    la cifra tecleada en ha), **se avisa** con cada zona, y **«Explotación hasta la final»**
    (en todas las zonas avisadas o en las de una capa) la baja con los bancos de su perfil hasta la
    cota de su ancla inmediatamente por encima de la final y dice cuánto pasa del desdoblado a la
    explotación. **Ninguna celda de la zona queda por debajo de su cota de ancla** (RF-014-18;
    hallazgo de CE-014-09): donde la cota cambia de un banco al siguiente, la cara de su perfil baja
    desde la cota de arriba (la de cada celda del recinto, también fuera de la zona) y la transición
    con el resto de la explotación sube desde lo que queda en la zona. Su comparación con el
    proyecto de referencia encontró que la cara subía desde la cota de abajo y se comía las celdas de
    arriba: 17.775 celdas por debajo de su cota y 899.048 m³ a la explotación frente a los 738.612
    de la referencia. En las pruebas, lo que pasa a la explotación baja en la cantera de la historia
    de Blender (E4) de 3.828,6 a 1.380,5 m³, en la de las vistas de 90,5 a 2,9 m³ y en la cantera
    sintética del banco de 410,239 a 136,462 m³ (allí la final cruza cotas de ancla y las caras bajan
    ahora desde las cotas de alrededor de la zona, más altas); los casos a mano (la zona de 2 ha:
    190.000 y 185.000 m³) no cambian, y calcularlo tarda 0,65 s en lugar de 0,37 s en 2,8 millones
    de celdas. Lo que aún queda dentro de las zonas tratadas (menos de una altura de banco: la
    cota de ancla inmediatamente por encima de la final deja allí el terreno sin explotar) se avisa
    con un aviso propio que lo dice y ya no vuelve a recomendar el modo (lo decidió Samuel el
    13/11/2026; su verificación encontró que el aviso se repetía tal cual); fuera de ellas, como
    siempre. Si una de las dos superficies no mueve ninguna celda más del espesor mínimo, se avisa
    nombrándola («La superficie de explotación de «…» no mueve…»), medido sobre la superficie que se
    crea: en su demostración en pantalla, el resumen de «Explotación hasta la final» decía «El
    diseño no mueve ninguna celda…» (el escalonado de un lado, antes del modo) aunque la
    explotación excavaba 491.006 m³. Se niega a calcular con un sector del recinto sin búsqueda de
    intocables vigente.
  - **Transiciones con el terreno no afectado…**: une una superficie de diseño (la seleccionada) con el
    terreno del borde de lo que mueve, sin paredes más empinadas que el ángulo de transición (sin
    valor por defecto), y mide el **salto creado** de cada pareja del borde como el salto con el diseño
    menos el que ya tenía el terreno: un escarpe natural no cuenta. Si menos del 99 % de las parejas
    queda por debajo de 1 m, avisa con sus tramos, sin bloquear. El salto creado no lo mide solo la
    transición: el resumen de la cantera (de cada una de sus dos superficies), de **Solo relleno…**
    y del ajuste a un límite nuevo (de cada superficie ajustada) lo mide igual, en el mismo borde, y
    avisa nombrando la superficie (lo decidió Samuel el 13/11/2026; su verificación encontró que
    solo lo medía la transición); por eso esas tres operaciones anotan también el salto y el
    porcentaje admitidos entre sus parámetros, y cambiarlos las deja obsoletas. Ninguna cifra
    cambia. El resumen de cada orden enseña los 10 primeros tramos de cada aviso y «… y N tramos más
    (en el informe)», que los guarda todos (en su demostración en pantalla, con 204 tramos el botón
    «Crear» quedaba fuera de la ventana); el ajuste, que no guarda informe, los enseña todos. La
    transición **solo acerca la superficie al terreno**: cada celda queda entre su cota de diseño y la del terreno, así que no
    convierte un corte en relleno ni un relleno en corte, no ahonda un corte ni sube un relleno, y no
    rellena donde las restricciones solo admiten el corte. Su verificación lo encontró junto a un
    escarpe previo más empinado que el ángulo: la primera versión subía por encima del terreno una
    corta a su pie (en el caso del escalón creado junto al escarpe, 1.000 celdas, hasta 2,56 m y
    1.300,8 m³ de relleno que el diseño no tenía) y ahondaba lo alto (en la cantera de prueba, el
    salto creado de la superficie final pasaba de 0,63 a 2,56 m); ahora esas celdas se quedan en el
    terreno o en el diseño (en la cantera de prueba, el salto creado queda en 0,61 m, frente a los
    0,63 m de la final sin transición) y en el caso del escarpe las parejas del borde de la
    superficie nueva son 308 en lugar de 520.
  - **Solo relleno…**: escalona en relleno una envolvente de la versión sin cortar nunca, con el pie
    dentro del relleno admitido (sin pasar el límite) y las **láminas de agua** de una capa como
    terreno de partida, solo en memoria; un diseño que cortaría 1 m³ o más, o movería algo en un
    intocable, se rechaza nombrándolo. La lámina solo es la partida del relleno (lo decidió Samuel
    el 13/11/2026): donde el relleno no sube de su cota (la balsa que no se rellena), fuera del
    relleno admitido y en los intocables, la superficie queda en el terreno registrado; cada lámina
    que cae fuera del relleno admitido o en un intocable se avisa con sus celdas y su área; y las
    cifras del diseño (el terraplén, el área con movimiento…) se miden frente al terreno registrado,
    como la cubicación de la misma superficie, así que el relleno que cubre una balsa cuenta con el
    agua de debajo. Su verificación encontró que la superficie se quedaba con la cota de la lámina en
    esas celdas: una lámina sobre la franja de fuera del límite y una torre dejaba 468 m³ fuera del
    límite y 92 m³ en la torre sin rechazarse (ahora, 0 m³ y el aviso), y en la balsa de prueba 352
    celdas a 270 m sin relleno, con un terraplén de 33.354,8 m³ frente a la lámina y 33.947,4 m³ de
    la superficie frente al terreno (ahora, esas celdas en el terreno y 33.412,3 m³). Por lo mismo,
    el terraplén del diseño de prueba de la operación pasa de 7.185,1 a 7.776,3 m³ (+591,25 m³, el
    agua bajo el relleno) y el del caso a mano, de 2.120,9 a 2.132,3 m³.
  - **Un límite nuevo**: **Compilar las máscaras** comprueba después, por pasos y con Esc, cada
    superficie de esta spec de la versión y dice el volumen y el área que el límite vigente deja fuera
    (también en la barra N de esa superficie); **Ajustar el diseño a un límite nuevo…** las ofrece
    marcadas y las ajusta con **la cara de su propio perfil** (60° la explotación, 35° la final, no el
    mismo para las dos), con los m³ de cada una; pedir otro ángulo se rechaza, y si el límite no corta
    una superficie su ajuste es de 0 m³ y lo dice. La cara y el factor de malla son los que anotó la
    operación que diseñó la superficie, no los del perfil de hoy, y el ajuste los anota en sus
    ajustes: su verificación encontró que, cambiado el perfil de explotación a 50° después de crear
    la cantera con 60°, el ajuste daba 18.011,0 m³ en lugar de 17.050,6 m³. Ninguna cifra de prueba
    cambia. Si se ajustan juntas las dos superficies de una cantera, después se les aplica la regla
    de orden de la cantera y se comprueba `final ≤ explotación ≤ terreno` antes de crear, con una nota
    de las celdas que cambió más de 1 mm, que no sale si no cambió ninguna (antes, «cambia en 0
    celdas»; los m³ de ajuste de cada una siguen siendo los de su cara); ajustar solo
    una avisa si la final queda por encima de la explotación (lo decidió Samuel el 13/11/2026; su
    verificación encontró que ajustarlas por separado dejaba la final hasta 20,72 m por encima). El
    resumen del ajuste avisa también de que el diseño del que sale está obsoleto y de que
    «Recalcular lo obsoleto» lo rehace con el límite vigente y sustituye al ajuste (lo decidió Samuel
    el 13/11/2026), y cerrar el proyecto mientras la ventana del ajuste comprueba las superficies ya
    no la vuelve a abrir. Ninguna cifra registrada cambia.
  - **Confirmar antes de escribir**: las cinco órdenes calculan por pasos, con el avance en la barra
    de estado y Esc, y enseñan su resumen; solo **Crear** lo registra, en una transacción. Cerrar el
    proyecto mientras calculan no deja nada, tampoco justo cuando acaban: el cálculo se descarta con
    sus rejillas temporales y lo dicen («Se cerró el proyecto mientras se calculaba…»). Su
    verificación encontró que, cerrado el proyecto en el último paso, el cálculo quedaba abierto
    pidiendo **Crear**, con sus temporales en la carpeta del proyecto cerrado; **Envolventes y
    escalonado…** (spec 013) hacía lo mismo y se corrige igual. Ninguna cifra cambia. Son cinco
    operaciones de la versión activa con sus entradas, sus parámetros y sus cifras con tipo y
    procedencia (con el nombre de la operación, la superficie y el sector como ámbito): quedan
    obsoletas con su causa si cambia una capa, un perfil o las máscaras, se recalculan con
    «Recalcular lo obsoleto», se congelan con su revisión (las superficies, como superficies de diseño
    para la verificación por recinto) y se reproducen, salvo el ajuste, que existe por un límite que
    cambió.
  - **Ver y exportar**: el recinto, las dos superficies, sus envolventes, la clasificación (con un
    color por clase sobre la superficie final), la transición y la superficie ajustada se cargan como
    objetos de tipo **Diseño**, con su ficha en la barra N (las cifras de una superficie dicen
    «cantera, explotación» en español: antes, «exploitation», el valor que se guarda); las listas
    de superficies de los diálogos ya no ofrecen las rejillas de códigos (la clasificación, el
    recinto, la rejilla de clases de las máscaras), que no son cotas (antes, la de las semillas
    proponía la primera la clasificación); **Exportar rejilla a GeoTIFF…** las
    exporta todas, y la clasificación y el recinto con su código por clase y su leyenda en los
    metadatos, con los nombres de la vista y de la barra N («relleno de restauración», «recinto
    excavable»; antes, «relleno» y «recinto de excavación»).
  - **Textos**: los mensajes que cuentan algo (zonas, partes, grupos de semillas, tramos, parejas,
    celdas, polígonos y líneas) tienen su singular, también en el resumen de cada orden, en sus
    líneas («la regla de orden cambió 1 celda», también las de la transición, el ajuste, las láminas,
    el recinto y las bermas) y en la vista previa («en 1 zona»; antes el resumen decía «en 1 zonas»
    y «1 celdas»); **Transiciones con el terreno no afectado…** lleva en su menú el «…» de las
    órdenes que abren un diálogo, y los avisos del salto creado la nombran así; el aviso de una
    superficie fuera del límite vigente acaba en «Ajustar el diseño a un límite nuevo…» (antes, con
    un punto de más); y la vista previa dice cuántas
    líneas tiene la capa de corredores («1 línea»; antes, un número suelto); el campo de la
    pendiente de un corredor con rasante se llama **Campo de pendiente de la rasante**; los rechazos
    de «Solo relleno…» dicen «revise la envolvente, su perfil y su dominio» (no hay semillas que
    revisar); el de una superficie que no es de diseño nombra todas las que valen (también una
    transición, un diseño «solo relleno» y una ajustada); el de la cota de un corredor dice
    «corredor N»; y se quita un mensaje de una capa en otro CRS que nada lanzaba (las capas del
    proyecto ya están en su CRS).
  - **Parámetros nuevos**, de versión: el anillo de coronación (3 celdas), el desdoblado que se avisa
    (1 m) y su área mínima (0,2 ha), el salto creado admitido (1 m) y su porcentaje (99 %), todos
    Adoptado «sin confirmar», y el ángulo de transición y el talud de conservación, **sin valor por
    defecto**: los declara una persona con su origen.
  - **Rendimiento**, medido en el PC de referencia con 2,8 millones de celdas y 20 sectores, en disco
    local, en su verificación única y tras su convergencia: las dos superficies, 7,2 s (≤ 20 s; 7,3 s
    con el salto creado de las dos), con 511 MiB de pico; el salto creado, 0,03 s; la transición,
    1,5 s; el ajuste de una superficie, de 2,0 a 2,1 s, y de las dos en una orden, de 3,72 a 3,95 s
    (≤ 5 s); cada llamada, de 94 a 156 ms de CPU (≤ 0,2 s); Esc, ≤ 0,12 s. `tools/check.py` sigue
    por debajo de 48 s con el equipo en reposo (mediana 47,3 s en la verificación única, +3,0 s por
    la 014; de 45,6 a 47,6 s en la convergencia), y pasa de ellos con otros programas cargando el
    equipo.
  - **Sin dependencias nuevas**: las componentes conexas y la distancia euclídea exacta con la cota
    del más próximo son código propio sobre el numpy de Blender. Una corrección de un texto: la
    descripción de «Límite desde el perímetro…» decía «Retranqueo y talud final desde el perímetro
    hasta el fondo», que no es lo que hace; ahora dice «Recinto excavable de la versión: el corte
    admitido por sus máscaras».
  - **Lo que hoy no hace**, tras su verificación única: la capa de láminas del diálogo de la cantera
    no se usa (las láminas son de «Solo relleno…»); una sola zona a conservar por diseño; y un
    corredor que pisa un fondo se rechaza.

- **Envolventes y escalonado** (spec 013). Antes de excavar un hueco, tender un frente o rellenar
  un talud hay que poder decir, con cifras, hasta dónde llega un talud y cómo se convierte en
  bancos; lo que pasó en el proyecto de referencia (una métrica que alargaba la distancia un
  8,2 % y dejaba caras a 37,2° en lugar de 35°; semillas en toda la ladera, con un relleno de
  716.000 m³ donde bastaban 17.607 m³; la berma deducida de la pendiente local; caras de hasta
  84,6° y paredes entre sectores; perfiles y factores de malla copiados de un script a otro) no se
  puede repetir. Guía de uso: `docs/usuario/envolventes-y-escalonado.md` de la documentación.
  Menú **Diseño ▸ Parámetros** (Perfiles de banco…, Sectores de diseño…, Vista previa de semillas,
  dominios y restricciones) y **Diseño ▸ Cantera ▸ Envolventes y escalonado…**: sus órdenes dejan
  de estar en gris (el resto de Cantera, de la spec 014, sigue en gris hasta que esta se cierre).
  - **Perfiles de banco…**: un perfil tiene un nombre (`EXPL_10_60_6`) y un código que no cambia, y
    su altura, la inclinación máxima de su cara, su berma mínima, su cota de anclaje y su factor de
    malla son parámetros con tipo, origen, decisor e historial, **por versión**: **ninguno tiene
    valor por defecto** (salvo el factor de malla, 1,0 «sin confirmar»), porque un perfil por
    defecto sería una cifra inventada. La ventana enseña de cada uno su avance y su talud general
    (`EXPL_10_60_6`: 11,77 m y 40,34°; `REST_5_35_6`: 13,14 m y 20,83°) y lo marca «no resuelto
    por la rejilla» en rojo, con un triángulo, si su cara o su berma es más estrecha que una celda.
    Un perfil sin nombre, con el de otro o con un valor sin declarar o fuera de rango se rechaza
    nombrando el perfil, el campo y el valor.
  - **Sectores de diseño…**: los sectores de la búsqueda de intocables (o el perímetro, si no hay
    capa de sectores) con su área, el estado de su búsqueda y el **talud general máximo** que
    impone la propiedad, con su origen y su decisor, por sector y por versión: cambiarlo en una no
    lo cambia en las demás. Declarar los sectores de nuevo conserva los valores de los que
    mantienen su código y lista, sin borrarlos, los de los que ya no existen.
  - **Vista previa de semillas, dominios y restricciones**: antes de calcular, y sin escribir nada
    en el proyecto, dibuja las semillas coloreadas por cota, el dominio de trabajo, los sectores
    (en ámbar si su búsqueda está pendiente) y las zonas de las restricciones con su leyenda, y
    resume sus magnitudes, con el aviso de las celdas de semilla fuera del dominio: el error de las
    semillas en toda la ladera se ve antes de calcular. Se quita al conmutar a la interfaz de
    Blender.
  - **Envolventes y escalonado…**: la envolvente descendente (la menor que no queda por debajo de
    las semillas: el hueco más profundo bajo unas coronaciones) o ascendente (la mayor que no
    queda por encima: un hueco que sube desde un fondo), de las semillas que se elijan (una
    superficie en una zona, una cota fija o una rejilla de cotas), con una pendiente constante o
    la de cada sector, un factor de malla, un alcance máximo y el dominio acotado a unos sectores
    o a una capa. **Dos métricas y ninguna más**: el *chamfer* 5×5, con un error de distancia de
    ±1,4 %, y la euclídea exacta, solo con pendiente constante; el 3×3, que alargaba la distancia
    un 8,2 %, no existe. Cada ejecución comprueba que la envolvente converge y no pasa de la
    pendiente, y si no, no entrega nada. Se **niega a calcular** en un sector sin búsqueda de
    intocables vigente, con otra rejilla, CRS o datum, sin semillas con cota o con el dominio
    vacío, nombrando el objeto, el campo y el valor, y sin registrar nada.
  - **Escalonar**: la envolvente se convierte en bancos y bermas **anclados a cotas absolutas**,
    z₀ + n·h, que nada mueve después: en **corte** (la cara primero, queda por encima) o en
    **relleno** (la berma primero, queda por debajo). Un sector con talud general máximo impuesto
    tiene la berma de la fórmula (19,58 m con `REST_5_35_6` y 10,6°, no los 6 m del resto) y no la
    deducida de la pendiente local; entre sectores se regulariza la envolvente, para que no queden
    paredes, y al final se recorta la inclinación a la cara del perfil, sin dejar el corte por
    debajo del terreno. La **superficie de diseño** se compone con el terreno solo donde las
    máscaras de la 012 admiten corte o relleno, y se verifica por recinto con 0 m³ fuera de lo
    admitido. Salen también la rejilla de las **cotas reales de las bermas** y su tabla por
    sector, perfil y cota (sin suponer múltiplos de nada), y un informe con el desmonte y el
    terraplén, el área con movimiento, la inclinación p90, p99 y máxima con su lugar, el salto en el
    borde de lo prohibido y los avisos (movimiento en el borde de la rejilla, inclinación pasada de
    la cara, desmonte o terraplén muy superior al de la revisión congelada anterior y, si una
    envolvente de pendiente constante más empinada que el talud de un sector se regulariza y baja,
    cuántas celdas y cuántos metros como máximo, sin cambiar la envolvente ni el escalonado).
  - **Confirmar antes de escribir**: «Calcular» va por pasos, con el avance en la barra de estado y
    Esc, y enseña el resumen con sus avisos; solo **Crear** lo registra, todo en una transacción, y
    Cancelar, Esc o cerrar la ventana no dejan nada. Son dos operaciones de la versión activa, con
    sus cifras con tipo y procedencia y el nombre de la operación como ámbito (dos envolventes de
    la misma versión no se pisan): quedan obsoletas con su causa si cambia una entrada (una
    restricción, un sector, una búsqueda, un perfil o un talud), se recalculan con «Recalcular lo
    obsoleto», se congelan con su revisión y se reproducen. Al congelar, el diálogo lista también
    cada superficie de diseño sin verificación al día, como las de la 012.
  - **Ver y exportar**: la envolvente, la superficie de diseño y las cotas de berma se cargan en
    la vista como objetos de tipo **Diseño**; la barra N «Diseño» enseña su estado, sus
    parámetros, las semillas y el dominio, las restricciones aplicadas y sus cifras, y, una por
    sector y en rojo con un triángulo, la marca de búsqueda de intocables pendiente si un sector
    que tocó el cálculo ha perdido su búsqueda (bajo su estado y como primera fila de sus cifras: es del estado de ahora y
    no se escribe en el proyecto, así que el informe y las cifras guardados no cambian); su botón
    **Exportar rejilla a GeoTIFF…** escribe el GeoTIFF que QGIS abre georreferenciado (Float32,
    −9999 como «sin dato»).
  - **Rendimiento**, medido en el PC de referencia con una rejilla de 2,8 millones de celdas, en
    disco local y con el equipo cargado por otros programas: el *chamfer*, 0,13 s; con 20 sectores,
    0,52 s; la euclídea exacta, de 3,1 s a 9,9 s (la cifra de la exacta, ≤ 6 s con semillas de
    contorno y ≤ 30 s con una zona maciza, la aprobó Samuel); el cálculo completo con diez perfiles,
    4,9 s; 436 MiB de pico; activar la vista previa con 100.000 semillas, 20 sectores y 500
    restricciones, de 0,80 a 0,98 s y cada redibujo, de 0,4 a 0,6 ms; la llamada más larga, 125 ms
    (≤ 0,2 s), y la transacción final, de 40 a 59 ms. `tools/check.py` pasa de 41,6 s a unos 44–46 s en reposo:
    IMGA sube su límite de 45 a 48 s (spec 001, versión 0.12, y spec 007, versión 0.8).
  - **Sin dependencias nuevas**: los dos algoritmos son código propio sobre el numpy de Blender
    (la transformada de distancia separable no resuelve la euclídea con semillas de cotas
    distintas; `docs/trampas.md`). Una corrección de un texto: el aviso de un sector pendiente en
    la vista previa dice en inglés «Find untouchable elements by sector…», como la orden. Otra:
    si se cierra el proyecto a mitad de un cálculo del diseño, el mensaje dice «Se cerró el
    proyecto mientras se calculaba «Hoyo»: no ha quedado nada a medias» y no que se cubicaba (el de
    la cubicación no cambia).
  - **El resumen de la vista previa ya no queda bajo la barra de herramientas**: empieza a la
    derecha de ella cuando se superpone a la Vista 3D (con sus textos y cifras como antes) y no
    pierde las primeras letras de cada línea; lo vio el H3 en la pantalla de referencia.
  - **La leyenda de las semillas de la vista previa dice el color que se ve**: con todas las
    semillas a la misma cota (una superficie plana) enseña una sola fila, «Semillas a 650,0 m», con
    el verde con que se pintan, y no dos filas iguales en azul y en rojo; con varias cotas, las
    dos de siempre. Ningún cálculo ni cifra cambia; lo vio el H3 en la pantalla de referencia.
  - **«Verificar un diseño por recinto…» y «Entre dos superficies…» proponen la superficie de
    diseño que se ha seleccionado**: antes no reconocían el objeto de tipo Diseño y caían en «la
    primera y la segunda de la lista» (de partida las bermas, de final la envolvente). Ahora, con la
    superficie de diseño seleccionada (la envolvente y las bermas no cuentan), la final marcada es
    ella y la partida, la de «Superficie de partida» de su ficha (si sigue en la lista); con otra
    superficie seleccionada o con dos diseños se ordenan como siempre, de partida la de mayor cota
    media. El nombre que propone la verificación («Verificación de des_srf_hueco») sigue a las
    finales que se marcan después en la ventana, y uno tecleado no se toca. Ningún cálculo ni cifra
    cambia; lo vio el H3 con ratón y teclado reales.

- **Límites legales y restricciones** (spec 012). Antes de diseñar hay que saber dónde no se puede
  cortar ni rellenar, y después hay que poder demostrarlo en m³: lo que pasó en el proyecto de
  referencia (un perímetro de actuación sin cortar con la concesión, 1.126 m² de relleno fuera y
  0,68 ha fuera sin listar; una copia vieja de un límite redibujado, +1,43 ha; el montículo de una
  torre de 132 kV rebajado 26,6 m porque nadie buscó antes lo intocable; la balsa rellena un 17 %;
  unas marcas del cliente tomadas como límites) no se puede repetir. Guía de uso:
  `docs/usuario/limites-y-restricciones.md` de la documentación. Menú **Diseño ▸ Límites y
  restricciones** (sus órdenes dejan de estar en gris; «Cuadrículas mineras…» sigue «Disponible en
  R-32»: es de una segunda spec).
  - **Límites…**: el límite legal (la concesión o la autorización; varios se unen) y el perímetro de
    actuación, de capas de polígonos del proyecto, con su motivo, su decisor, su fecha y el
    resguardo hacia dentro del límite legal. El informe da el área de cada uno en m² y en ha, la de
    su intersección y la **franja de solo relleno** (el perímetro que queda fuera de la concesión)
    parte a parte, con su área y las coordenadas de su centro, y «Ir a» la encuadra: el error de
    los 1.126 m² de relleno fuera de la concesión no pasa desapercibido.
  - **Restricciones…**: una capa tipada con **once tipos** —límite legal, perímetro de actuación,
    intocable, exclusión, sin corte, solo relleno, solo restauración, banda de resguardo, sin
    relleno, preferible no afectar y requiere acceso—, de polígonos, líneas o puntos, con resguardo,
    peso, motivo, decisor y fecha. **Desde una capa…** crea las de todas sus entidades (un tipo
    para todas o el campo que lo da, con su correspondencia de valores) e informa de las creadas y
    de las rechazadas, con la entidad y el motivo; la capa de origen no se toca. Cada restricción
    tiene un código que no cambia. Los **resguardos, el peso y «activa» no tienen valor por defecto**
    (una distancia de seguridad por defecto acabaría en un plano) y valen **por versión**: la
    propiedad puede liberar o endurecer una zona en una versión sin redibujarla. Una restricción
    **incompleta** (sin motivo ni decisor, como las que se dibujan en QGIS, o sin un resguardo) o
    **no válida** (que se corta a sí misma, sin área, una línea o un punto sin resguardo) **bloquea
    la compilación** con la lista de todas; **Completar…** la arregla.
  - **Editar en QGIS 4.2**: las tres capas (polígonos, líneas y puntos) están en el GeoPackage del
    proyecto con **un estilo por tipo** y el tipo como **lista de valores en español**. Lo que se
    dibuja, se cambia o se redibuja en QGIS se anota como edición fuera de Geoblender y deja
    obsoletas las máscaras y las verificaciones, con la causa.
  - **Compilar las máscaras**: las restricciones activas de la versión pasan a la rejilla del
    proyecto con una sola regla, la del lado seguro: una celda está **dentro de una zona** si alguna
    parte de su área queda a menos del resguardo, y **dentro de un límite** solo si toda su área
    queda dentro. Salen el **dominio por defecto** (perímetro ∩ límite legal − intocables −
    exclusiones, con sus resguardos), el corte y el relleno admitidos, la franja, las zonas y una
    rejilla de clases; las prohibiciones **siempre se suman** (ninguna prioridad devuelve un
    movimiento que otra restricción prohíbe) y se informa de dónde no cabe ningún movimiento y por
    qué restricciones. Al compilar de nuevo, **el área ganada y perdida** de cada restricción que
    cambió (redibujar el perímetro en QGIS, +1,43 ha, se ve). Son datos de la versión: se congelan
    con su revisión y se reproducen. Con 500 restricciones de 100.000 vértices en una rejilla de 2,8
    millones de celdas, unos 3 s, por pasos y con Esc. **Exportar las máscaras…** escribe la rejilla
    de clases como GeoTIFF con su leyenda en español, que QGIS carga solo.
  - **Buscar elementos intocables por sector…**: los sectores de una capa de polígonos (o el
    perímetro entero), hasta diez capas de infraestructuras y una distancia de búsqueda (25 m,
    «sin confirmar»). Lista cada entidad a esa distancia con sus atributos, para **convertirla en
    intocable** (con su resguardo y su motivo) o **descartarla con un motivo**; **cerrar la
    búsqueda** deja constancia de qué se revisó, quién y cuándo, y la búsqueda **vuelve a pendiente**
    si cambia el sector o una capa consultada: las máscaras, la verificación y el diálogo de congelar
    lo dicen («Búsqueda de elementos intocables pendiente en: Sector 2»). Un sector con diez capas
    de 10.000 entidades, en 1 s.
  - **Intenciones del cliente…**: las marcas del cliente, con su papel (proteger, rellenar, explotar a
    una cota, conservar como está, plataforma, talud a tratar), su fecha y su documento de origen,
    se guardan aparte y **no cambian ninguna máscara ni verificación**; **Convertir en
    restricción…** crea una restricción enlazada a la intención, que no cambia. En la vista, en
    violeta, con un estilo que ninguna restricción usa.
  - **Ver restricciones y límites** (el **control 30** y el menú): sobre la Vista 3D, el contorno de
    cada restricción con un color por tipo, su nombre, su zona rayada, el dominio, la franja y una
    leyenda, sin escribir en el proyecto; se quita al conmutar a Blender. Activarla, menos de 1 s.
    La **barra N ▸ Restricción** enseña la seleccionada: tipo, resguardos y peso con su tipo y su
    ámbito, motivo, decisor, fecha, decisión de la propiedad, estado y las cifras de su última
    verificación.
  - **Verificar un diseño por recinto…** (también en Cubicación ▸ Control de cifras): una o hasta
    diez superficies finales —**también una importada de fuera**— frente a la de partida dan, por
    recinto (cada restricción, «Fuera del perímetro de actuación» y «Fuera del límite legal»), el
    **corte y el relleno en m³** y el área con movimiento, con el veredicto: «no cumple» con una
    sola celda que corta o rellena donde no se puede (0 m³ de tolerancia, por encima del espesor
    mínimo de verificación de 0,02 m), la afección sin juicio de una «preferible no afectar» y «sin
    comprobar» en «requiere acceso». Cada **grupo de celdas** que incumple sale con su recinto, su
    área, su volumen, su espesor máximo y su centro (**Ir a**), y la **rejilla de incumplimientos**
    se carga en la vista y se abre en QGIS. Tres finales en todos los recintos, de 3 a 4,2 s; Esc
    no deja nada a medias.
  - **Versiones y procedencia**: compilar y verificar son operaciones de la versión, con sus cifras
    con tipo y procedencia; quedan obsoletas al cambiar una restricción, un sector, una búsqueda, una
    superficie o un parámetro, se recalculan con «Recalcular lo obsoleto», se congelan con su
    revisión y se reproducen con las mismas cifras. **Congelar** una revisión lista los hallazgos de
    las verificaciones (recintos que no cumplen, verificaciones obsoletas o con la búsqueda
    pendiente, superficies de diseño sin verificar) y pide aceptarlos con un motivo, que queda en la
    revisión: no se bloquea, pero no pasa sin que nadie lo vea. El formato del proyecto no cambia
    (sigue el 3): las tablas `core_constraint_polygon`, `core_constraint_line`, `core_constraint_point`,
    `core_intention`, `core_sector`, `core_untouchable_search` y `core_untouchable_hit`, el estilo en
    `layer_styles`, las máscaras (`gis_msk_…`, `gis_mskz_…`, `gis_mskr_…`, `gis_mskp_…`,
    `gis_mskg_…`) y las verificaciones (`res_chk_…`, `res_chkg_…`, `rasters/res_chkv_…`) se crean al
    usarse.
  - **Importar capas con el papel «Entidades»** (Topografía ▸ Importar ▸ Capas vectoriales…):
    puntos, líneas o polígonos con todos sus campos, llevados al sistema del proyecto, de donde
    salen las restricciones, las infraestructuras que se buscan, las marcas del cliente y los
    sectores. Una capa que mezcla geometrías se importa en dos.
  - **Tras la verificación única** (01/11/2026), sin cambiar ninguna cifra de los casos de
    referencia: habilitar Geoblender vuelve a tardar 0,45 s (las órdenes de la spec 012 importan su
    cálculo al usarlo); una zona alineada con la rejilla ya no gana un anillo de celdas por el
    redondeo de las coordenadas de un UTM (la tolerancia de la celda sale de las coordenadas de la
    rejilla: 1 µm con nortes de 4,4 millones de metros); una restricción mucho mayor que la rejilla
    (50 km con celdas de 1 m) se compila en 0,15 s y no en 88 s; la **decisión de la propiedad** se
    enlaza a una restricción en «Desde una capa…» y en «Completar…», y «Convertir en restricción…»
    hereda la de la intención; una capa sin entidades lo dice, sin la lista vacía de rechazadas; y
    la superposición de polígonos que se tocan en una esquina ya no escribe un aviso en la consola.
    Las llamadas de «Recalcular lo obsoleto» tardan de 0,40 a 0,55 s, y la transacción final de
    compilar y verificar pasa de los 0,2 s de las demás (hasta 0,5-0,6 s).
  - **Varios límites legales** (el hallazgo F-1 de la verificación única, decidido por Samuel el
    01/11/2026): **la zona, la cifra y la banda hacia dentro de cada límite legal son las suyas**,
    no las de la unión. Dos concesiones contiguas de 900 m² dan 900 m² cada una (antes, 1.800 m²
    cada una), la suma de las zonas es el límite legal, y un corte de 2 m³ en la banda se cuenta y
    se lista **una vez**: un solo recinto, un solo grupo y una sola línea al congelar (antes salía
    en el recinto de cada concesión). Cada celda de la banda va a un solo límite (la que está en
    dos concesiones que se solapan, a la primera por código). El dominio, el corte y el relleno
    admitidos, la franja y la rejilla de clases siguen formándose con la unión, y manda el mayor
    resguardo hacia dentro, en todo el contorno. Con un solo límite legal, las mismas cifras que
    antes. La compilación sube a la versión 1.1 de su algoritmo: lo compilado con la anterior (y las
    verificaciones que lo usaron) queda obsoleto y «Recalcular lo obsoleto» lo rehace.
  - **Tras ver la spec en pantalla** (01/11/2026, a 1920 px con la escala 1,0, con ratón y
    teclado): la barra N y la ventana de Restricciones enseñan el valor de cada parámetro («V01:
    8 m [ADO]»), con su nombre y «Cambiar…» en líneas propias, sin cortes ni valores escondidos; y
    la línea de cada grupo de la verificación y de cada parte de la franja del informe de límites
    se lee entera, con «Ir a» en su propia fila. Ninguna cifra cambia.

- **Cubicación entre superficies** (spec 011). El número que se entrega —la cubicación mensual de
  una cantera, la de un proyecto o un plan de labores— sale de un solo cálculo, con tipo y
  procedencia, y no de un script por versión: lo que pasó en Silvestre (el escombro descontado «en
  proporción» de todas las unidades, 19.600 t vendibles; un umbral de escombro distinto en cada
  script; un acopio pesado con la densidad in situ, un 23 % de más; cifras pasadas a mano) no se
  puede repetir. Guía de uso: `docs/usuario/cubicacion.md` de la documentación.
  - **Cubicar entre dos superficies…** (menú Cubicación, el control 28 y **Mayús+Alt+M**): con dos
    superficies seleccionadas, las propone (de partida, la más alta; «Invertir» las cambia) e Intro
    cubica. Da desmonte, terraplén y neto (m³) y el área con dato, sin dato y sin movimiento (m²),
    celda a celda con el **área real de celda**, opcionalmente dentro de un ámbito (con la fracción
    exacta de cada celda; un ámbito con polígonos que se solapan, que se cortan a sí mismos o sin
    área se rechaza con la lista antes de cubicar, para no contar nada dos veces). Superficies: rejillas del proyecto o de la versión activa, las congeladas
    en la revisión de la que parte o una cota constante; **ninguna se remuestrea**: dos que no
    están en la misma rejilla, sistema o datum vertical se rechazan nombrando la diferencia y la
    orden que lo arregla. El espesor mínimo es un umbral (0 m por defecto). La pirámide de
    referencia da su volumen con error ≤ 0,1 % con celdas de 2, 1 y 0,5 m. Dos superficies de 2,8
    millones de celdas, en menos de 1 s (en `Z:`, unos 1,1 s).
  - **Diferencia entre superficies…**: la rejilla final − partida como dato de la versión, en la
    vista sobre la superficie final, en rojos (desmonte), azules (terraplén) y gris (sin
    movimiento); su menú «Diferencia ▾» la exporta a GeoTIFF para el cliente y QGIS.
  - **Por unidad, fase y banco…**: por las fases o zonas de una capa importada con el papel nuevo
    **«Dominios»** (cada polígono, con la fracción exacta de cada celda; los que se solapan o no
    valen se rechazan con la lista y el área de cada solape), por **bancos** anclados a cotas
    absolutas (o una lista de cotas) y por las **unidades** de la columna de materiales, todo en
    un solo cálculo que cuadra con el total. Con 8 unidades, 20 fases y 30 bancos, unos 4–5 s.
  - **Materiales y densidades…**: la columna del proyecto de arriba abajo (natural, antrópica con
    su rejilla de espesores, compuesta con sus componentes y porcentajes), útil o estéril, in situ
    o suelto. **El escombro va en su sitio**: presente donde su espesor pasa de **un único umbral**
    (0,30 m), con su volumen desde su base hacia arriba, y las unidades de debajo cortadas en esa
    base; nunca se descuenta en proporción. Las densidades, los K y los porcentajes son parámetros
    con tipo e historial, **sin valor por defecto**; el K y los porcentajes, también solo para una
    versión.
  - **Toneladas y relaciones**: lo in situ, V · densidad (y su volumen esponjado, V · K); lo
    suelto (un acopio), **V · densidad / K**. Lo que no tiene densidad sale sin toneladas, con su
    aviso, y la cubicación sin total de toneladas: nada se supone. Relaciones estéril/útil en
    m³/m³ y en t/t, en total y por fase, y la intrínseca de las compuestas (**Ratios…**).
  - **Por momentos de extracción…**: la suma de unas cubicaciones (explotación, desdoblado,
    stock…) frente a la directa, en m³ y en %, con aviso por encima de la tolerancia (1 %); ninguna
    cifra se ajusta. Su tabla (momento × unidad, la suma y la diferencia) está en el panel y en el
    CSV, con la columna «Momento».
  - **El panel** (N ▸ Proyecto ▸ Cubicaciones, y la misma tabla en una ventana al terminar de
    cubicar, por unidades o por momentos, o con Ratios…): las cubicaciones de la versión activa con su revisión («V03.r1 en curso», «V03 vigente: r1»), la
    tabla filtrable por fase, banco y unidad, cada valor con su unidad, su tipo y sus marcas, los
    parámetros usados y el factor combinado (la escala de la proyección por la de la elevación y
    su efecto en %, informado y no aplicado: los volúmenes son «de cuadrícula»). Las cifras se ven
    con los decimales de su unidad (91 451 m³; 1,57 m³/m³).
  - **Exportar CSV…**: para Excel en español (UTF-8 con BOM para las tildes, «;» y coma decimal), con una cabecera de
    procedencia (proyecto, versión, revisión, superficies con su hash, parámetros con su tipo,
    fecha y versión de Geoblender) y una fila por valor, con el **valor completo**.
  - **Son las primeras operaciones de versión**: sus cifras son de la versión activa, quedan
    obsoletas cuando cambia lo que usaron (un K cambiado solo rehace las toneladas y el in situ de
    lo suelto, no los m³ de la cubicación), se
    recalculan con «Recalcular lo obsoleto», se congelan con su revisión y se reproducen con las
    mismas cifras. Sin versión activa se pide una; con la versión SUPERADO o en solo lectura, las
    órdenes salen desactivadas con su motivo. Esc a mitad no deja nada. El formato del proyecto no
    cambia (sigue el 3): sus tablas (`res_materials`, `res_vol_…`, `res_ton_…`, `res_stg_…`) y su
    rejilla (`rasters/res_dif_…`) se crean al usarse.

- **Versiones, revisiones e instantáneas** (spec 009). El proyecto guarda alternativas de diseño
  con identidad propia, como la V10 de Silvestre, sin que cambiar de estado rompa nada y sin las
  carpetas `_previo_N`: lo que pasó con la V10 (211 capas de QGIS rotas al renombrar su carpeta,
  sus reservas cambiadas tres veces en un día y cuatro estados que restaurar para rehacerla) no se
  puede repetir. La topografía y los sondeos son del proyecto, comunes a todas las versiones; las
  primeras operaciones de versión son las de la cubicación (spec 011), y el diseño vendrá después.
  Las versiones se crean, cambian de estado, se anotan las decisiones de la propiedad y sus
  revisiones se congelan con lo que tengan. Guía de uso: `docs/usuario/versiones.md` de la documentación.
  - **Versiones con su estado** (Proyecto ▸ Versiones, el control 8 del acceso rápido y el menú
    «Versión ▾» de la colección de una versión): Nueva versión… (rasgo, título, motivo, de cuál
    parte y el encargo) le da el código siguiente (V01, V02…, que no cambia nunca), en BORRADOR y
    con su revisión r1 abierta; Cambiar estado… solo ofrece lo que se puede (a VIGENTE, con una
    revisión congelada, y la VIGENTE anterior pasa a SUPERADO en el mismo paso; a DESCARTADO, con
    motivo). **Cambiar de estado no toca ningún fichero** salvo la base del proyecto, su diario y
    la cabecera, y QGIS sigue abriendo todas las capas, también las de las instantáneas (unos
    0,01 s en disco local y 0,07 s en `Z:`). Una versión SUPERADO o DESCARTADO no cambia: sus
    órdenes dicen «V09 está en estado SUPERADO: cree una versión nueva a partir de ella». Nada se
    borra.
  - **La versión activa** es de cada sesión: el control 8 la dice con el color de su estado
    («● V10.r2»; VIGENTE verde, BORRADOR ámbar, SUPERADO gris, DESCARTADO marrón) y la barra de
    estado, «V10.r2 VIGENTE». Cambiarla no escribe en el proyecto (se puede en solo lectura, para
    consultar); al abrir, la de la vista, la de este equipo o la VIGENTE.
  - **Partir de otra versión** hereda sus parámetros de versión («Heredado de V10.r2») y lo
    congelado en su última revisión, como entrada posible; **nunca sus resultados ni sus cifras**.
  - **Nueva revisión…** congela la revisión abierta y abre la siguiente, con su motivo: copia a
    una instantánea (`snapshots/V10.r2/`, en GeoPackage, GeoTIFF y npz) lo que la versión produjo
    y lo derivado o editable a mano de aguas arriba, comprobando cada copia, sin copiar otra vez
    lo que ya está en otra instantánea (se referencia), y anota sin copiarlo lo inmutable del
    proyecto (lo importado y los originales, los parámetros, las operaciones y las cifras). No
    congela con una entrada cambiada sin decidir ni con una operación de la versión en curso; si
    hay resultados obsoletos, operaciones que esperan revisión a mano o entradas no localizables,
    los lista y hay que aceptarlos (quedan anotados). Con su avance en la barra de estado y Esc,
    que no deja nada a medias; tampoco un cierre de Blender (lo copiado se aparta a `orphans/`).
    **Desactivar Geoblender a mitad** la cancela como Esc, igual que Reproducir…, Cargar en la
    vista, Refrescar, la copia local y la publicación: sin nada a medias, sin el avance en la
    barra de estado y sin nada que apartar al volver a activarlo.
    Congelar 1 GB en disco local, unos 24 s; **5 GB en `Z:`, unos 3 min**. Una revisión que no
    cambia nada hace crecer el proyecto menos de 1 MB (con 2 000 elementos).
  - **Lo vigente** de una versión es lo de su última revisión congelada; lo de la abierta, «en
    curso». Lo de una versión SUPERADO o DESCARTADO ya no se marca obsoleto ni se cuenta en
    «! n obsoletos», pero **dice el estado que tenía al congelarse** en Elemento activo y en el
    inventario («VIGENTE · OBSOLETO AL CONGELARSE, ACEPTADO», «A REVISAR A MANO AL CONGELARSE»,
    «NO REPRODUCIBLE»), y cada cifra vigente o congelada de la ficha, el suyo debajo («obsoleta
    al congelarse, aceptada»); lo «en curso», el estado de hoy.
  - **Instantáneas comprobadas**: al abrir el proyecto (dentro de su comprobación, en segundo
    plano: 200 revisiones en 0,12 s, y en `Z:`, en 2,5–2,9 s) y con «Comprobar cambios en las
    entradas». Un fichero que falta o que cambió deja **solo esa revisión «alterada»**, con un
    aviso grave que la nombra a ella y al fichero: no se usa ni se reproduce, y el proyecto sigue
    en escritura. Las fechas no cuentan: una copia de seguridad restaurada no avisa.
  - **Reproducir la versión desde sus entradas congeladas**: vuelve a calcular en la caché, sin
    tocar el proyecto, cada operación de la última revisión congelada con sus entradas y sus
    parámetros congelados, y dice qué resultados (por su hash de contenido) y qué cifras coinciden
    y, en los que no, la causa probable (otra versión del algoritmo, de Geoblender o de una
    biblioteca). Con su avance y Esc.
  - **Encargos y decisiones de la propiedad** (Proyecto ▸ Control ▸ Procedencia y registro):
    quién decide, cuándo, qué y su documento o una referencia en texto, enlazada a los parámetros
    y las versiones que afecta; se ve junto a cada parámetro en Parámetros del proyecto y en el
    control 8. No se cambian ni se borran.
  - **Parámetros por versión**: en los que su módulo lo admite, Cambiar parámetro… pregunta «¿Para
    el proyecto o solo para V11?», y el panel dice los dos valores («V11: 1,25 [HIP] · proyecto:
    1,23 [ADO]»).
  - **En la vista**, un dato de una versión va en la colección de su versión, «V10 · Definitiva
    [VIGENTE] r2», con el color de su estado, que cambia solo al cambiar de estado (una versión
    SUPERADO no se oculta). **Renombrar en el Outliner** la colección de una versión, o el objeto
    de cualquier dato del proyecto, guarda el texto como su título y vuelve a generar el nombre
    con él, sin cambiar ninguna ruta. El inventario y Elemento activo enseñan las versiones, sus
    revisiones y las cifras vigentes y «en curso» de cada dato de versión.

- **Vistas regenerables** (spec 010). Lo que se ve en Blender es una vista del proyecto, nunca
  su fuente: se pone al día desde el proyecto, sin escribir nada en él (también en solo
  lectura) y sin borrar ningún objeto.
  - **La vista marca en vivo lo que no está al día.** En menos de 1 s tras cualquier cambio en
    el proyecto (un recálculo, un parámetro, una entrada actualizada o descartada, otra sesión
    que escribe) o un Ctrl+Z que devuelve un objeto a una carga anterior, los objetos y su
    colección cambian de nombre sin volver a cargarse: «MDT mdt_norte [VIGENTE · NO AL DÍA]»
    (muestra un contenido anterior), «[VIGENTE · OBSOLETO]», «[SIN RESPALDO]» (su dato ya no
    está en el proyecto o se descartó) o «[FALTA]». Lo que hacía solo la vista de los sondeos,
    ahora en todo dato cargado. Mientras haya algo así, el control 7 del acceso rápido
    («Refrescar») sale resaltado y su descripción dice cuántos («3 datos de la vista no están
    al día»). Los objetos del usuario y los de «99 Trabajo» no se tocan nunca.
  - **Refrescar las vistas desde el proyecto** (F5, Proyecto ▸ Refrescar…, el control 7):
    vuelve a cargar por pasos, con su avance en la barra de estado y Esc, solo lo que no está
    al día (también lo cargado con otro origen local) y, en lugar de lo importado de una
    entrada actualizada, lo importado de la nueva; lo demás no se toca (con el MDT y los
    sondeos en la vista, tras recalcular el MDT, solo el MDT). Cancelado, la vista queda como
    estaba; al terminar, «Vista al día: 1 dato vuelto a cargar, 2 sin respaldo en el proyecto,
    197 al día»; Ctrl+Z deshace la recarga. Un dato obsoleto no se recarga (su contenido no
    cambió): primero Recalcular lo obsoleto. Antes, F5 decía «Disponible en R-07».
  - **Al abrir el proyecto** (o otra vista suya con él abierto), lo que no está al día se marca
    sin volver a cargarlo y se dice una vez («3 datos de la vista no están al día: Refrescar
    (F5)»), y la superposición de los sondeos al día (etiquetas, leyendas y marcas) se rehace
    en segundo plano, sin volver a cargarlos. Abrir tarda lo mismo con la vista que sin ella.
  - **Abrir el proyecto de una vista.** Al abrir con doble clic una vista sin su proyecto, además
    del aviso de siempre, un diálogo ofrece «Abrir el proyecto de esta vista»: lo busca donde lo
    guardó la vista y, si no está, entre los proyectos recientes del equipo por su identidad, y
    lo abre con sus reglas de siempre (cerrojo, solo lectura, migración). «Ahora no» no abre
    nada, y el panel Proyecto mantiene el botón. Si no lo encuentra, dice dónde se esperaba y
    con qué identidad, y «Localizar el proyecto…» solo acepta ese proyecto. No se ofrece en un
    guion sin interfaz, al recuperar una sesión o un autoguardado, ni en una vista dentro de una
    copia de respaldo del proyecto (`.anterior`, `.respaldo-esquema-N`, `.publicando`).
  - **N ▸ Proyecto ▸ Elemento activo**: del dato del objeto activo, leído del proyecto, su tipo,
    su estado, si está al día en la vista, su versión (spec 009; «—», lo del proyecto), la
    operación que escribió su contenido (con su fecha y la versión de Geoblender), sus entradas
    con su hash, sus derivados con «obsoleto» y sus cifras con su unidad y su tipo; Procedencia
    abre su cadena entera.
  - **N ▸ Proyecto ▸ Inventario**: lo registrado en el proyecto, cargado o no (entradas y
    datos), con su estado, sus marcas (obsoleto, entrada cambiada) y si está en la escena;
    filtros por tipo, estado (los vivos, por defecto), versión, presencia en la escena y texto
    (sin distinguir mayúsculas ni tildes), como mucho 500 filas a la vez («… y 19 500 más: afine
    el filtro»), y Cargar en la vista, Descargar y Procedencia de la fila elegida (desactivadas
    con su motivo si no se puede). Al cargar o descargar (desde el inventario, el menú o un
    guion), sus filas se ponen al día sin volver a leer el proyecto.
  - **Cifras de la selección** (control 29; Herramientas ▸ Consulta): las cifras registradas de
    los datos de los objetos seleccionados, con su insignia de tipo, su unidad y sus marcas
    («depende de una hipótesis», «obsoleta»), como las de una rejilla de diferencias de la
    cubicación (spec 011). No mide nada; sin cifras registradas en lo seleccionado, dice «Sin
    cifras registradas». Cada objeto guarda además, en texto de solo
    lectura, las cifras de su dato, puestas al día al cargarlo y en cada Refrescar; ningún
    cálculo las lee.
  - Medido con Blender 5.2.1 en el PC de referencia: Refrescar una vista con 200 datos de los
    que cambiaron 10 (uno, una malla de 1 millón de vértices), 1,3 s (≤ 5 s), con el avance cada
    0,13 s como mucho y Esc en 0,12 s; el inventario de un proyecto de 20 000 datos se abre y se
    filtra en 0,08 s como mucho (≤ 0,5 s; en `Z:`, 0,07 s); la marca de 200 datos que quedan
    obsoletos a la vez, al día en 0,63 s (≤ 1 s), sin que ningún paso pase de 20 ms; en `Z:` se
    midió sin cambios y con 10 de 200 no al día: ningún paso pasa de 20 ms (15,3 ms el más largo).

- **Sondeos** (spec 005). La rama geológica empieza: bocas, desviaciones, litología y análisis en
  el proyecto, validados, con su traza 3D y visibles en Blender y en QGIS, sin tocar nunca las
  fuentes y sin suponer ningún convenio. Las órdenes están en el menú **Sondeos** (Importar, Base
  de datos, Validar y desviar, Ver) y en la pestaña **«Sondeos»** de la barra lateral de la Vista
  3D (N); sin proyecto abierto salen desactivadas y dicen el paso previo. La barra superior no
  cambia.
  - **Importar tablas** (Sondeos ▸ Importar ▸ Sondeos…, o un `.xlsx` en «Importar un
    fichero…»; un CSV o un TXT ahí abre el importador de puntos de la topografía): bocas,
    desviaciones, litología, análisis (en columnas por elemento o en filas) y catálogos de
    litologías y elementos, todos los ficheros de una vez, en CSV, TXT o XLSX (una tabla por
    hoja). Un asistente propone el papel de cada tabla por el nombre del fichero o de la hoja
    («bocas», «collars», «desviaciones»…) o, si no lo dice, por sus columnas (una tabla que no
    reconoce queda «No se importa»), y el campo de cada columna por su nombre habitual en
    español o en inglés; y enseña sus 20 primeras filas tal como se van a leer. **Se declara
    siempre**, y nunca se supone: el sistema de referencia y el datum vertical de las bocas (el
    datum empieza «Sin declarar»; una altura elipsoidal de un GNSS se lleva al datum del
    proyecto con el geoide del IGN), la referencia del azimut (cuadrícula, geográfico, o
    magnético con su declinación) y el convenio de la inclinación de las desviaciones y de la
    orientación en boca (negativa o positiva hacia abajo, o desde la vertical), la unidad de
    cada elemento (g/t, ppm, ppb o %), el formato de las fechas de una tabla que las trae, los
    valores sin dato («−99;ND») y si un negativo es «bajo el límite»; mientras falte algo,
    «Importar» está desactivado y dice qué falta. El separador, el decimal, la codificación
    (UTF-8, Windows-1252, Latin-1 o DOS) y la cabecera son ajustes de lectura. Un valor
    vacío o sin dato queda sin dato; «<0,01», como 0,01 con la marca «bajo el límite» y su texto;
    «>x», con la marca «sobre el límite»; uno que no es un número, o con el otro separador
    decimal, se rechaza con su fila, su sondeo, su tramo, su campo y su valor. Las leyes se
    convierten de forma exacta a la unidad de su catálogo, con el valor y la unidad del
    laboratorio conservados. Un XLSX da lo mismo que su CSV. Un fichero o una hoja sin filas
    (solo la cabecera) no se importa: la importación falla diciendo cuál y que no tiene filas.
  - **Importación pendiente** (N ▸ Sondeos): antes de escribir nada, los códigos nuevos (darlos de
    alta; las litologías, con un color propio distinto de los demás) y los sondeos que el
    proyecto ya tiene en alguna tabla que trae la fuente (sustituir sus registros o conservarlos:
    nunca se mezclan dos importaciones en una tabla de un sondeo), con Aplicar y Descartar. Si no
    hay nada que decidir, se aplica sola. El informe de cada tabla (leídos, importados, rechazados
    con su motivo y sustituidos) queda en el proyecto. Cancelar o fallar a mitad no deja nada.
  - **Bases de RecMin** (Sondeos ▸ Importar ▸ Base de sondeos RecMin…, o un `.mdb` en
    «Importar un fichero…»): una base de RecMin Free o Pro (MDB o ACCDB, formatos Jet 4 y ACE,
    esquemas 11 y 12) **en solo lectura**: se lee una copia con el motor de Access del equipo
    en un proceso aparte, con su avance y cancelable, y junto a la base no aparece ningún
    fichero. Entran sin pérdida las bocas, las desviaciones,
    todas sus tablas de litología y de muestras (de columnas por elemento a un valor por tramo),
    los catálogos (litologías con su color, densidad y orden; elementos; sectores, grupos y
    zonas), las intersecciones y los cortes: los valores en precisión simple, por su decimal más
    corto (0,1, no 0,100000001490116), y el identificador de RecMin y los campos sin equivalente,
    conservados. Una base abierta en RecMin (con su `.laccdb` al lado) o de otra versión de
    esquema se lee solo si se confirma; sin un motor que lea su formato, se dice el formato y qué
    instalar (o exportar desde RecMin a CSV), con el motivo entero en una ventana emergente, y no
    se importa nada.
  - **La base y su validación.** Lo importado de cada fuente se guarda tal cual, en lo que se
    declaró, y no cambia nunca; tras cada importación se monta con todo ello la base del proyecto
    y se valida. En la base, las bocas en el sistema de referencia y el datum del proyecto, con
    una transformación de precisión conocida (de ED50 a ETRS89 con la rejilla del IGN, y su
    precisión en el informe); el azimut del norte de cuadrícula, con la declinación y la
    convergencia de cada boca (lo medido queda en cada estación), y la inclinación, negativa
    hacia abajo. **Validar la base de sondeos**: 27 comprobaciones (nombres repetidos, coordenadas
    o profundidad que faltan, estaciones repetidas o fuera del sondeo, tramos mal, solapes,
    códigos fuera de catálogo, huecos, cambios bruscos de dirección, bocas lejos del MDT del
    proyecto o fuera de la ventana de trabajo, unidades distintas, valores ≤ 0 sin marca…), cada
    una con su código (DH-E o DH-W), su alcance y un mensaje que dice qué corregir; un error
    excluye solo lo que fija su alcance (el sondeo, o esa tabla de ese sondeo), y lo demás sigue.
    Con el MDT del proyecto, la diferencia de cada boca con él (su cota menos la del MDT, en m)
    se ve en una fila por boca: el aviso, si pasa de la tolerancia; si no, «Información»; y
    «Sin evaluar», si la boca queda fuera del MDT.
    La lista, con filtros por nivel y código, en N ▸ Sondeos ▸ Validación; **Exportar el informe
    de validación…**, a un CSV para Excel en español (punto y coma, coma decimal y tildes).
  - **Trazas** (Calcular trazas…): por mínima curvatura (o tangente, o tangente equilibrada), de
    todos los sondeos o solo de los de traza obsoleta; la posición de cualquier profundidad, sobre
    el mismo arco y a menos de 1 mm a 500 m de la solución analítica. Si cambian la boca, las
    desviaciones, la referencia del azimut o la declinación de un sondeo, su traza queda obsoleta
    y la vista lo marca en ese sondeo; el método es el de cada cálculo: con otro, o con otros
    parámetros de las trazas, se recalculan todas. **Referencia de azimut y declinación…**
    corrige la de una importación, con su motivo, sin tocar lo medido, y deja obsoletas solo las
    trazas de sus sondeos.
  - **Vista 3D**: tubos coloreados por la litología del esquema elegido con los colores del
    catálogo (gris donde no hay dato), barras de leyes de un elemento con 5 clases por quintiles
    (o las propias) y una clase «< LD», etiquetas «S-12 (160,00 m)» con la profundidad en el
    fondo si se pide, leyenda, y un aspa roja con su código en un sondeo excluido; todo sin
    perder precisión (≤ 0,5 mm de la traza). El radio del tubo cambia en vivo; el esquema, el
    elemento o las clases recargan la vista por pasos (N ▸ Sondeos ▸ Representación).
  - **Valores bajo el límite de detección…**: la regla con que se sustituyen en los cálculos
    posteriores (por defecto, la mitad del límite, ADOPTADO), como parámetro del proyecto con su
    historial; nunca cambia un valor guardado.
  - **QGIS 4.2** abre las bocas (puntos con cota) y las trazas (líneas 3D) en el sistema de
    referencia del proyecto y lo demás como tablas, con los nombres de las columnas en español,
    sin avisos; nada se edita desde QGIS (una boca movida allí bloquea la base hasta aceptar la
    edición con un motivo o recalcularla).
  - **Procedencia** (spec 008): una entrada por fichero (por hoja; la base de RecMin, una) con su
    hash de contenido y su original guardado; importar otra vez lo mismo no lo duplica; un
    fichero cambiado fuera de Geoblender se decide (Actualizar · Mantener la copia · Cancelar), y
    Recalcular lo obsoleto rehace la base, la validación y las trazas. Los 8 parámetros de los
    sondeos (las tolerancias de la validación, el cambio de dirección máximo, la diferencia con
    el MDT, el paso de las trazas y la regla bajo el límite), ADOPTADO «sin confirmar».
  - Medido en el PC de referencia con una campaña de 2 000 sondeos, 20 000 estaciones, 50 000
    tramos y 500 000 análisis: importar sus seis CSV de principio a fin, 29,5–30,0 s (≤ 30 s);
    desde una base de RecMin, 32,5 s (cancelar, 0,11 s, sin dejar ningún proceso); validar,
    0,3 s; las trazas y 100 000 posiciones, 0,05 s; la vista, 1,4 s; el hash de una base de
    RecMin de 100 MB, 22 s. La interfaz no se para más de unos 0,15 s en ningún paso con el
    proyecto en el disco del equipo; con el proyecto en la red, lo que hace Geoblender en cada
    paso no pasa de unos 0,18 s, y las esperas del servidor al guardar y al enviar lo escrito
    (vistas de hasta 0,5 s) se miden aparte, sin límite (lo decidió IMGA: spec 005, 0.5).

- **Topografía base** (spec 006). La primera función minera: el terreno con el que se diseña y
  se cubica, exacto, en el sistema de referencia del proyecto y con su procedencia. Las órdenes
  están en el menú **Topografía** (Importar, Superficies, Analizar y Exportar) y en **Proyecto ▸
  Intercambio** (Importar un fichero…, Cargar en la vista…, Descargar de la vista); sin proyecto
  abierto salen desactivadas y dicen el paso previo («Primero abra un proyecto (Proyecto ▸
  Proyecto ▸ Abrir proyecto…)»), y en solo lectura, el motivo. La barra superior no cambia.
  - **Importar un MDT** (Topografía ▸ Importar ▸ MDT ráster…): GeoTIFF de una banda (sin
    compresión, DEFLATE, LZW o PackBits; cotas en coma flotante o enteras; TIFF o BigTIFF),
    ESRI ASCII Grid con su `.prj` y XYZ en malla regular. Se guarda en el proyecto en su rejilla
    de origen, cada cota igual a la del fichero y las celdas sin dato como sin dato; el informe
    dice la rejilla, la codificación y cuántas celdas tienen dato. **El sistema de referencia y
    el datum vertical son obligatorios**: si el fichero no los declara, se declaran en el
    diálogo (el datum empieza «Sin declarar»; «El del proyecto» lo propone, pero hay que
    elegirlo) y nunca se supone el del proyecto. Se rechaza, diciendo el fichero, lo que tiene y
    qué hacer, sin importar nada: compresión JPEG, ZSTD o LERC («Guárdelo en QGIS con
    compresión DEFLATE o LZW…»), varias bandas, georreferencia girada, escala u offset de
    valores, más de 100 millones de celdas (recortarlo en QGIS) o un XYZ que no forma una malla.
    Un GeoTIFF *PixelIsPoint* se desplaza medio paso, con aviso. Avisa si el MDT sale de la
    ventana de trabajo (se importa entero; la rejilla del proyecto solo cubre la ventana) o si
    alguna celda queda a más de 8 km del origen local, con el error estimado en mm.
  - **Otro sistema de referencia u otro datum**: se transforma al del proyecto con una
    transformación de precisión conocida que no depende de la configuración de PROJ ni de GDAL
    del equipo ni de internet, y el informe dice cuál y su precisión: de **ED50 a ETRS89 con la
    rejilla del IGN** `es_ign_SPED2ETV2` (0,2 m; comprobado en el vértice REGENTE 55901, a
    0,009 m de su reseña) y de **alturas elipsoidales ETRS89 a altitudes con el geoide del IGN**
    (0,05 m; también en Canarias). Sin una transformación de precisión conocida, no se importa,
    y se nombran los dos sistemas. Si la mediana de la diferencia con un MDT del proyecto está
    entre 40 y 60 m (posibles alturas elipsoidales de un GNSS o un dron sin geoide), se avisa
    con la mediana y la importación espera a que la persona la confirme.
  - **Rejilla de cálculo de paso exacto** (Topografía ▸ Superficies ▸ Rejilla de proyecto desde
    un MDT…): el MDT en la rejilla del proyecto (su paso, de 0,5 a 5 m; 1,000 m por defecto,
    alineada a metros enteros), con el área real de cada celda en todo cálculo de áreas y
    volúmenes. Por defecto, **media ponderada por área** si las celdas del MDT no son mayores
    que las del proyecto (un MDT de dron de 0,5 m a 1 m: conserva el volumen) e **interpolación
    bilineal** si lo son (un MDT05 del IGN de 5 m a 1 m, sin escalones de 5 m); el informe dice
    el método. Una celda que el MDT no cubre del todo queda sin dato: nunca se rellena con
    ningún valor. Un ráster ya alineado con el paso del proyecto sale idéntico. Desde ED50, se
    reproyecta en segundo plano.
  - **Puntos y líneas de rotura** (Topografía ▸ Importar ▸ Puntos y líneas de rotura…): un CSV,
    TXT o XYZ de levantamiento con su asistente (codificación UTF-8, Windows-1252, Latin-1 o DOS;
    separador; coma o punto decimal; cabecera; y el papel de cada columna: punto, X, Y, Z, código
    y línea, con una vista previa de las primeras filas). Las coordenadas se guardan tal cual,
    en doble precisión; el informe da las filas leídas, las rechazadas (con su número y el
    motivo) y los duplicados. Las roturas, duras (son aristas del TIN) o blandas (solo aportan
    sus puntos); una rotura sin cota o de un solo punto se rechaza. Del fichero se guarda una
    copia en el proyecto. **Capas vectoriales** (Importar ▸ Capas vectoriales…): una capa de un
    GeoPackage, también uno que QGIS tiene abierto (se lee una copia), como puntos, líneas de
    rotura, curvas de nivel (con su campo de cota o la Z de sus vértices) o contorno y huecos;
    las geometrías curvas se rechazan y los valores M se descartan con aviso.
  - **TIN** (Topografía ▸ Superficies ▸ TIN desde puntos y líneas de rotura…): triangulación de
    Delaunay restringida en la que cada rotura dura es una sucesión de aristas, con los vértices
    en sus coordenadas exactas y todos los triángulos con la normal hacia arriba; con contorno,
    huecos y lado máximo opcionales. Si dos puntos coinciden en planta, dos roturas se cruzan o
    una pasa por un punto con cotas que difieren más de 0,01 m, no se crea el TIN y se lista cada
    conflicto con sus nombres, su posición y sus dos cotas («las líneas de rotura «PIE_3» y
    «CAB_2» se cruzan en (700 020,000; 4 400 020,000) con cotas 805,000 m y 825,000 m»); para
    los puntos que coinciden se elige media, mínima, máxima, el primero o cancelar, y las roturas
    se corrigen en su fuente. Dos roturas que se cruzan a la misma cota comparten el vértice. Un
    levantamiento de hasta unos 350 000 puntos lo triangula Blender al momento (si tarda más de
    1 s, la barra de estado lo avisa antes: «Triangulando 300 000 puntos (unos 1,9 s)…», la
    única pausa de la interfaz, aprobada por IMGA); uno mayor, en segundo plano, más despacio.
    **Desde curvas de nivel** (TIN desde curvas de nivel…): añade puntos entre curvas vecinas
    donde quedan triángulos planos, hasta menos del 1 % (en el caso de referencia, del 19,3 % al
    0 %), y dice el porcentaje antes y después y los puntos añadidos; una cima o un fondo sin
    punto acotado queda plano, y se dice. **MDT ⇄ TIN…** convierte una rejilla en TIN y al
    revés con las mismas cotas.
  - **Curvas de nivel** (Topografía ▸ Analizar ▸ Curvas de nivel…): de una rejilla o de un TIN,
    3D con la Z igual a su cota y marcadas como maestras o no, con equidistancia, cota base,
    maestras cada n m (por defecto, 1 m y maestras cada 5 m), desfase de las maestras,
    simplificación y longitud mínima. Solo quedan abiertas en el borde de la superficie o de sus
    huecos, sus vértices están sobre la superficie (a 1 mm como mucho) y en una silla no se
    cruzan ni se tocan, también con un punto de la rejilla justo a la cota de una curva (pasan
    a 2 cm de él). En la vista, las maestras se dibujan con un trazo más grueso.
  - **Validar la superficie** (Topografía ▸ Superficies): el área y el % sin dato, cada hueco
    interior con su área, las celdas fuera de la ventana de trabajo, las cotas fuera del rango
    plausible (−500 a 5 000 m: un −9999 que nadie declaró como sin dato) y, en un TIN, el % de
    triángulos planos, el lado máximo y los degenerados.
  - **Verlo en Blender** (Proyecto ▸ Intercambio ▸ Cargar en la vista… y Descargar de la vista):
    rejillas, TIN, puntos, roturas y curvas, en la colección «Datos base / Topografía» con su
    estado y su fecha, sin perder precisión (de vuelta a coordenadas reales, 0,24 mm de error a
    8 km del origen); el objeto «Ancla del proyecto» lleva las esquinas de la ventana de
    trabajo, el recorte de la vista se ajusta a lo cargado y, con el cursor 3D sobre un
    vértice, la barra de estado da sus coordenadas reales. Una malla con caras hacia abajo o
    cuyo volumen no cuadra con el de la rejilla no se muestra como superficie. Una rejilla de
    menos de 2 m se puede ver con versiones de 2 y 5 m para la vista general («Nivel de
    detalle»), sin tocar la de cálculo. La carga va por pasos, con su avance en la barra de
    estado, y Esc la cancela sin dejar nada a medias; descargar quita los objetos y no toca el
    proyecto. **Importar un fichero…** (o soltarlo sobre la Vista 3D) abre el importador que
    corresponde a su extensión (`.tif`, `.asc`, `.xyz`, `.csv`, `.txt`, `.gpkg`).
  - **Entregables y QGIS** (Topografía ▸ Exportar): **Superficie o rejilla a GeoTIFF…** escribe
    un GeoTIFF float32 con sin dato −9999, compresión sin pérdida y el sistema de referencia del
    proyecto (cada cota, la del proyecto redondeada a float32: menos de 0,12 mm por debajo de
    4 096 m); **Capas a GeoPackage…**, puntos, roturas, el TIN como triángulos, curvas (con
    `elevation` e `is_index`) y contornos, con Z, coordenadas idénticas a las del proyecto y un
    **estilo por defecto de QGIS para las curvas** que dibuja las maestras más gruesas (0,5 mm
    frente a 0,25 mm). QGIS 4.2 abre sin avisos de sistema de referencia las rejillas del
    proyecto (`rasters/`) y los entregables, con la misma cota en cada celda. Nunca se escribe
    sobre una fuente, en su carpeta o en una carpeta de solo lectura (se nombra), ni sobre un
    fichero que ya existe sin confirmarlo; uno abierto en QGIS da error sin dejar un fichero a
    medias. Dentro del proyecto, solo en `exports/`.
  - **Transformar coordenadas** (Proyecto ▸ Georreferencia ▸ Transformar coordenadas…): puntos
    tecleados entre dos sistemas del catálogo (ED50 → ETRS89, de un huso a otro), con 1 mm, la
    transformación y su precisión, el factor de escala y la convergencia de cuadrícula. Si otra
    extensión de Blender trae otra versión de pyproj, las transformaciones se desactivan con un
    mensaje que dice las dos versiones, y el resto de Geoblender sigue funcionando.
  - **Procedencia** (spec 008): cada importación registra su entrada con su hash de contenido y
    los sistemas de referencia declarados, y cada operación sus parámetros, el triangulador, la
    versión de su algoritmo y el hash de sus resultados. Los 17 parámetros de la topografía
    (tolerancias de duplicados, fracción mínima cubierta, umbral de triángulos planos, los de
    las curvas, el límite de celdas…) salen en Parámetros del proyecto como ADOPTADO «sin
    confirmar» hasta que alguien los confirma; un valor tecleado en un diálogo vale para esa
    orden y no cambia el parámetro. Importar otra vez lo mismo no lo duplica; si un levantamiento
    cambia fuera de Geoblender, el TIN que depende de él espera a que se decida (Actualizar ·
    Mantener la copia · Cancelar), y al actualizarlo el TIN y sus curvas quedan obsoletos y
    **Recalcular lo obsoleto** los rehace.
  - **Sin parar la interfaz**: lo que tarda (importar, remuestrear, triangular, curvas, validar,
    exportar) va en segundo plano, con su avance en la barra de estado y su cancelación, y lo
    que vuelve al proyecto se incorpora por pasos («Incorporando «…» al proyecto… n %»).
    Cancelar o fallar a mitad no deja nada escrito en el proyecto.
  - **Casos de referencia** (los cálculos son exactos celda a celda): la corta circular de
    1 308 944,006 m³ con celdas de 1 m, a +0,0005 % como mucho (≤ 0,01 %; con 4 m, ≤ 0,025 %);
    un prisma de 10 m sobre celdas de 1,000294 × 1,000302 m, 10 005 966,77 m³ exactos (suponer
    1 m² por celda habría dado −0,06 %, como en Silvestre); remuestrear a la rejilla del
    proyecto conserva el volumen de la zona cubierta (error 0); las curvas de un cono de
    referencia, a 0,006 m del círculo teórico (≤ 0,01 m).
  - Medido en el PC de referencia con datos del tamaño de Silvestre: importar un MDT de 3 399 ×
    3 309 celdas (11,2 M) tarda 5,8 s con DEFLATE y 14,3 s con LZW (0,11 GB más de memoria); su
    rejilla de 1 m (2,81 M celdas), 2,2 s, y desde ED50, 26,5 s; un TIN de 300 000 puntos y
    10 000 tramos de rotura, 4,4 s (el triangulador propio, 20 000 puntos en 0,35 s); las curvas
    de 1 m de esa rejilla con 150 m de desnivel (2 235 curvas), 2,0 s; cargarla en la vista,
    3,0 s, y su versión de 5 m, 0,45 s; exportarla a GeoTIFF, 0,26 s, y 50 000 polilíneas con
    1,5 M de vértices a GeoPackage, 1,4 s; el hash de contenido de un MDT de 100 M celdas, 6,4 s
    en segundo plano. La interfaz nunca pasa más de 0,5 s sin refrescar el avance, salvo la
    triangulación de Blender avisada antes.
- **Procedencia: parámetros, entradas, operaciones y cifras** (spec 008). Geoblender anota en
  el proyecto de dónde sale cada resultado: de qué entradas, con qué parámetros (y de qué tipo),
  con qué operación y con qué versión del programa, y avisa de lo que deja de valer cuando algo
  cambia. La topografía (spec 006) ya registra así sus entradas, sus operaciones y sus
  resultados, y los sondeos (spec 005), también. Las órdenes están en **Proyecto ▸ Control**.
  - **Parámetros del proyecto…**: cada parámetro que mueve cifras, con su valor y su unidad
    (como las cifras, con el separador de miles: 500 000 t/año, también en los avisos), su
    tipo (MEDIDO, CALCULADO, ADOPTADO o HIPÓTESIS, con las insignias [MED], [CAL], [ADO] y
    [HIP], esta con un icono ámbar, también en el historial y en la procedencia; el rojo queda
    para los errores y los cambios), su origen (documento, norma, persona, operación o
    algoritmo), quién lo decidió y cuándo; se filtran por módulo, tipo y marca, y el
    seleccionado enseña su historial entero, que nunca se reescribe: una hipótesis que pasa a
    adoptada sigue constando como hipótesis en sus entradas anteriores. **Cambiar parámetro…**
    pide siempre el motivo y rechaza, diciendo la clave, el valor, la unidad y el rango, un
    valor fuera de rango, vacío, NaN o en una unidad que no se convierte; un valor en otra
    unidad de la misma magnitud se convierte (35 % en un parámetro en fracción se guarda 0,35;
    también t y kt, o m² y ha). Un valor por defecto de Geoblender queda «sin confirmar» hasta
    que una persona lo confirma o lo cambia, y las cifras que dependen de él lo dicen; si otra
    versión de Geoblender cambia la definición de un parámetro (su unidad, su rango o su valor
    por defecto), queda «revisar», sin tocar su valor.
  - **Un cálculo nunca cambia un parámetro**: si una operación calcula un valor distinto del que
    fijó una persona (un K de esponjamiento), lo guarda como cifra CALCULADO y avisa de la
    diferencia; adoptarlo lo decide una persona («Usar el valor calculado…»).
  - **Registro de entradas…**: cada fuente importada (uno o varios ficheros, o una capa), con su
    estado (vigente, cambiada, cambiada · se mantiene la copia, no localizable, sustituida o
    descartada), su tipo, la fecha de entrega y quién la entregó, los sistemas de referencia
    horizontal y vertical declarados al importarla, su hash de contenido y si se guarda su
    original. El hash de contenido no cambia si QGIS solo abre y guarda un GeoPackage o si se
    renumeran sus entidades, y cambia con cualquier coordenada, cota, píxel, atributo, fila o
    sistema de referencia declarado.
  - **Una entrada que cambió bloquea lo que depende de ella.** Al abrir el proyecto, antes de
    cada operación y con **Comprobar cambios en las entradas**, Geoblender compara cada fuente
    con lo registrado y, si su contenido cambió, lo dice con lo que depende de ella («La entrada
    «Limites_v1» ha cambiado desde su registro (…). Dependen de ella: 3 datos, 5 operaciones y
    12 cifras») y no ejecuta nada que la use hasta que se decide: **Actualizar** (se reimporta
    como una entrada nueva, y lo que dependía de la anterior queda obsoleto), **Mantener la
    copia** (se sigue con lo importado y no se vuelve a avisar hasta otro cambio) o Cancelar.
    Al abrir y antes de operar se miran primero el tamaño y la fecha de sus ficheros: una fuente
    sustituida por otra del mismo tamaño y con la fecha conservada (copiada con robocopy o
    sacada de un zip) solo la ve Comprobar cambios en las entradas, que calcula siempre el hash.
    Una fuente que no se encuentra queda «no localizable» y se sigue con lo importado.
  - **Lo recibido no se pierde ni se toca.** Lo importado de cada entrada queda en el proyecto
    tal cual, también al actualizarla o descartarla (**Descartar entrada…**, con motivo, no
    borra nada); de las fuentes tabulares y de los documentos (CSV, XLSX, bases de RecMin, PDF)
    se guarda además una copia del original, con su huella, en `originals/` dentro del proyecto,
    hasta 200 MB por entrada (parámetro `core.original_copy_limit`). Volver a importar el mismo
    contenido con los mismos ajustes no duplica la entrada. Geoblender nunca escribe junto a
    una fuente (tampoco un `-wal`, un `-shm` o un `.ldb`), y rechaza, nombrándola, una
    exportación sobre una fuente, en su carpeta o en una carpeta de solo lectura.
  - **Carpetas de solo lectura** (las de los expedientes de clientes), en las preferencias de
    Geoblender y en la variable de IMGA `GEOBLENDER_READ_ONLY_DIRS`: un proyecto dentro de una
    se abre en solo lectura, sin cerrojo y sin migrarlo, y en ellas no se crea un proyecto, ni
    se saca o se publica una copia local, ni se exporta. Si no hay ninguna, Geoblender avisa;
    Ayuda ▸ Diagnóstico de la instalación las muestra.
  - **Lo obsoleto.** Cambiar el valor de un parámetro (no solo su tipo), actualizar o descartar
    una entrada, editar un dato fuera de Geoblender, que falte uno o actualizar a un Geoblender
    que cambia el algoritmo de una operación dejan obsoleto exactamente lo que depende del
    cambio, con su causa («Obsoleto: cambió Producción»); las operaciones acopladas (las que
    siempre van juntas) quedan obsoletas juntas. La barra de estado dice «! n obsoletos» y el
    control 7 del acceso rápido, «Refrescar · obsoletos (n)» (n cuenta los datos obsoletos, los
    cálculos obsoletos que solo dejan cifras, como un área, y lo que espera revisión a mano): al
    pulsarlos se ve la lista, con la causa, el módulo y Recalcular en cada resultado.
    **Recalcular lo obsoleto** lo repite en orden, como operaciones nuevas, con su avance en la
    barra de estado y Esc para cancelar (lo ya recalculado queda); nunca se recalcula nada
    solo. Si un recálculo da el mismo contenido,
    lo que dependía solo de él deja de estar obsoleto sin recalcularse. Lo que no se repite solo
    (una edición a mano) queda «revisar a mano» hasta que se rehace o se da por bueno con un
    motivo (**Dar por buena…**). Un equipo con un Geoblender anterior no recalcula lo calculado
    con un algoritmo más nuevo: «Calculado con gis.resample 1.1: actualice Geoblender».
  - **Ediciones fuera de Geoblender.** Una capa del proyecto editada en QGIS se detecta al
    abrir, antes de usarla y a petición, queda registrada como edición externa y deja obsoleto
    lo que depende de ella; si su módulo no la declara editable a mano, queda bloqueada hasta
    aceptar la edición con un motivo, recalcularla o reimportarla. Lo importado no se puede
    editar (QGIS no lo guarda) y, si aun así cambia, queda dañado y solo se reimporta. Un dato
    que falta (un fichero borrado, una capa eliminada) se marca y se ofrece recalcularlo o
    reimportarlo. Los restos de una operación interrumpida se apartan a `orphans/`, dentro del
    proyecto, sin borrar nada; las capas creadas desde QGIS en la base del proyecto se pueden
    registrar como entrada o ignorar, y nada se mueve.
  - **Al abrir un proyecto**, queda listo para trabajar igual de rápido que antes, y las
    comprobaciones (entradas, ediciones externas, lo que falta, operaciones interrumpidas,
    restos y versiones de los algoritmos y de los parámetros) siguen en segundo plano, con
    «Comprobando el proyecto… n %» en la barra de estado y un botón para cancelarlas; una orden
    que dependa de algo aún sin comprobar no se ejecuta y pide esperar a que termine. En solo
    lectura se ve lo detectado y no se escribe nada: se registra al abrirlo en escritura.
  - **De dónde sale una cifra** (Proyecto ▸ Control ▸ Procedencia y registro ▸ **Grafo de
    operaciones y procedencia…**): se busca una cifra o un dato por su nombre, su clave o su
    uid, y se ve la cadena entera hasta sus entradas, con cada operación (quién, cuándo, en qué
    equipo y con qué versión), sus parámetros (valor, unidad, tipo y «sin confirmar») y el
    estado de cada eslabón. Cada cifra lleva su unidad, su tipo y las marcas «depende de una
    hipótesis», «depende de un valor sin confirmar» y «obsoleta», y ninguna cifra de un cálculo
    se escribe en el nombre de un objeto, de una colección o de un fichero.
  - **Ctrl+Z** deshace la escena, no lo registrado en el proyecto, y lo dice en la barra de
    estado («Ctrl+Z no deshace la operación «…»: sigue en el proyecto»).
  - Las órdenes que dependen de una entrada cambiada salen con ⚠ (al ejecutarlas, se decide
    sobre la entrada), y las que tienen resultados obsoletos dicen la causa en su descripción,
    con «Recalcular lo obsoleto» resaltado. Los avisos de la barra de estado se ven en modo
    Geoblender y en modo Blender. Si no caben (una escala de la interfaz grande en una pantalla
    de 1920 px), primero desaparecen el encaje y el recorte y después se pliegan, de derecha a
    izquierda, el trabajo en segundo plano (sin su último mensaje y con una barra corta que
    solo dice el %) y los avisos («⚠ 1», «! 3», solo el % de la comprobación), con sus botones
    de cancelar a la vista.
  - Medido con Blender 5.2.1 en el PC de referencia, con un proyecto sintético de 100 entradas,
    300 parámetros, 10 000 operaciones y 20 000 datos: queda listo para trabajar en 0,1 s como
    mucho; mientras se comprueba, la interfaz responde en menos de 0,02 s, y buscar las
    ediciones externas y lo que falta tarda 0,77 s (2,8 s con el proyecto en `Z:`); comprobar
    100 entradas por tamaño y fecha, 0,03 s (0,19 s con las fuentes en `Z:`); saber qué deja
    obsoleto un cambio, 0,34 s; la procedencia de una cifra, 0,4 s; los avisos de la barra de
    estado están al día en menos de 0,7 s. El hash de contenido de un MDT de 11,2 M celdas
    tarda 0,5 s, el de 100 000 polígonos 1,6 s y el de 500 000 filas 3,6 s; el de una rejilla
    de 100 M celdas, 4,6 s en segundo plano, y se cancela al instante. El de una capa de 2 M
    polígonos (0,9 GB) tarda 37 s en segundo plano, y el de un GeoPackage de 1 GB en `Z:`,
    48 s, con su avance también mientras cuenta las entidades y mientras cierra el hash; se
    cancela en cualquier momento en menos de 0,5 s.
- **Trabajos en segundo plano y motor de cálculo** (spec 004). Los cálculos largos se
  ejecutan aparte, sin congelar Blender: mientras avanzan se puede girar la vista, abrir menús
  y seguir trabajando. Todavía ningún cálculo minero los usa (llegarán con GemPy, la
  estimación y la programación lineal); para probarlos, **Herramientas ▸ Trabajos ▸
  Autodiagnóstico ▸** lanza una suma de prueba de unos 10 s o un producto de matrices con el
  motor de cálculo (o el intérprete externo) o con el numpy de Blender.
  - **En la barra de estado**, en modo Geoblender y también en modo Blender: cuántos trabajos
    hay en marcha, el nombre y el % del más antiguo (se actualiza cada cuarto de segundo) y su
    último mensaje, con un botón para ver la lista y otro para cancelarlo. Al acabar, durante
    10 s, su nombre, cómo terminó («Terminado», «Fallido», «Cancelado», «Tiempo agotado» o
    «Interrumpido») y su duración en s; si no terminó bien, el motivo en español, nunca una
    traza de Python.
  - **Trabajos en segundo plano** (Herramientas ▸ Trabajos, o el botón de la barra de estado):
    la lista de los trabajos de la sesión y de los que quedaron en su carpeta, cada uno con su
    estado, avance, duración, el intérprete que lo ejecutó (Python, numpy y su BLAS) y su
    último mensaje, y los botones Cancelar, Registro (abre su `job.log`) y Descartar; arriba,
    lo que ocupa la carpeta de los trabajos y el estado del motor de cálculo.
  - **Cancelar** detiene un trabajo en menos de 1 s (se exige como mucho 2 s); uno que no
    atiende la petición se termina a la fuerza al acabar su plazo de gracia (5 s) y consta
    «cancelado (forzado)». Cada trabajo tiene un tiempo máximo (una hora si su tipo no fija
    otro). Como mucho van 2 trabajos a la vez en proceso aparte (de 1 a 4, en las
    preferencias) y uno corto dentro de Blender; los demás esperan «En cola», por orden de
    llegada.
  - **Un cálculo nunca toca el proyecto**: no recibe su ruta, trabaja en su propia carpeta y
    devuelve ficheros que se comprueban con su huella (sha256) antes de darlo por
    «Terminado». Si falla, se cuelga o se pasa de tiempo, Blender sigue como estaba. Las
    carpetas de los trabajos van en la caché del proyecto (en el disco del equipo si el
    proyecto está en la red o en solo lectura, y en los datos de Geoblender del equipo si no hay
    proyecto abierto) y las de los terminados se borran a los 7 días
    al abrir el proyecto (se cambia en las preferencias) o con **Limpiar trabajos
    terminados…** (con «Borrar» y «Cancelar» en el idioma de Geoblender), que dice los MB
    liberados; nunca las de un trabajo en cola o en curso.
  - **Cerrar Blender o desactivar Geoblender** con trabajos en marcha los detiene sin dejar
    ningún `python.exe` (medido: 0,2 s; se exige como mucho 3 s); al volver, la lista los
    muestra «Interrumpido». 100 trabajos seguidos (bien, fallidos, cancelados y agotados) no
    dejan ningún proceso ni hacen crecer más de 2 MB la memoria del proceso que los lanza.
  - **Motor de cálculo** (Herramientas ▸ Trabajos ▸ Motor de cálculo…): un numpy aparte
    (2.5.3, de PyPI, con OpenBLAS) para los cálculos pesados, que multiplica dos matrices de
    2000 × 2000 en **0,04 s, frente a unos 25 s con el numpy de Blender**. **Solo se instala
    si se acepta**, en un diálogo que dice de dónde (el almacén de ruedas de IMGA o PyPI), qué
    paquetes, con qué versión y licencia, cuánto ocupa (12,6 MB de descarga y 53,9 MB en
    disco) y en qué carpeta, con «Instalar» y «Cancelar» en el idioma de Geoblender;
    habilitar Geoblender no lo crea. Desde un almacén de ruedas local se instala y se verifica
    en unos 6 s, sin internet; desde PyPI necesita «Permitir acceso en línea» de Blender y, si
    está desactivado, no se conecta y explica las dos salidas. Cada paquete se comprueba con su
    huella, y una instalación cortada o cancelada no deja nada. La verificación comprueba las
    versiones, que numpy sale del motor y no de Blender y que usa la BLAS optimizada, y mide el
    producto: «Listo · numpy 2.5.3 · BLAS scipy-openblas · 2000 × 2000 en 0,040 s». Desde la
    misma ventana se verifica, se repara o se quita (con «Quitar» y «Cancelar»); con otra
    versión de Geoblender se ofrece actualizarlo, y el anterior se borra al terminar si
    ningún trabajo lo está usando; si
    alguno lo usa (también desde otra sesión de Blender), se borra después, cuando ya no se
    usa, al terminar el siguiente cálculo con el motor o al abrir Geoblender. Si un
    cálculo lo necesita y falta, se ofrece instalarlo con el mismo diálogo; si el que hay es de
    otra versión de Geoblender, el cálculo dice cuál está instalado y cuál hace falta («El
    motor de cálculo instalado (…) no es el que necesita esta versión de Geoblender (…):
    actualícelo.») y se ofrece actualizarlo. Su estado sale
    también en Ayuda ▸ Diagnóstico de la instalación, con el intérprete externo si hay uno.
  - **Intérprete externo, para desarrollo** (Herramientas ▸ Trabajos): un Python 3.13 con numpy
    (por ejemplo, el de un entorno de GemPy) en lugar del motor, para probar versiones nuevas de
    las librerías sin reinstalarlo. Se comprueba antes de guardarlo y, si no sirve, se rechaza
    diciendo por qué («es Python 3.14.2, no 3.13»); la lista y el registro de cada trabajo
    dicen cuándo se usó. Autodiagnóstico ▸ Producto de matrices con el motor de cálculo lo
    prueba con su numpy.
  - Lanzar un trabajo devuelve el control en 0,014 s y su primer aviso llega a los 0,15 s
    (también con el motor de cálculo); con 4 trabajos en curso que informan 100 veces por
    segundo, seguirlos cuesta a Blender unos 0,5 ms (2,2 ms como mucho) cada cuarto de segundo,
    y un avance llega a la barra de estado en menos de 0,25 s (medido con Blender 5.2.1).
- **Interfaz de Geoblender** (spec 003). Un conmutador **[GB|B]** al principio de la barra
  superior (o **Ctrl+F10**) pasa cada ventana de la interfaz de Blender a la de Geoblender y
  vuelve, sin recargar el fichero ni tocar las preferencias de Blender. En modo Geoblender, la
  barra tiene Disposición ▾, los menús de Blender plegados (≡), los **11 menús del trabajo**
  en su orden (de Proyecto a Planos, cada uno con su «Paso n de 11»), Herramientas, Ayuda y
  el acceso rápido del proyecto; en modo Blender, la barra de Blender entera con un menú
  «Geoblender ▾» delante. Están **todos los comandos del producto** (unos 390), también los que
  aún no existen: salen en gris y dicen «Disponible en …» (la spec o la entrada del roadmap que
  los traerá); si se pulsan, lo dicen y no hacen nada. La búsqueda de Blender (**F3**) los
  encuentra en los dos modos, también «Conmutar Geoblender ⇄ Blender». Si la ventana es
  estrecha, los títulos pasan a iconos, solo los que no caben: en una pantalla de 1920 px
  se leen todos con la escala de Windows al 100 % y los 11 del trabajo con la del 125 %
  (Herramientas y Ayuda, en icono). Desactivar Geoblender deja Blender como estaba.
  - **Acceso rápido de cada Vista 3D** (24 controles que se pliegan si no caben), **vistas
    mineras** (planta, secciones N-S y E-O, isométricas; menú circular Mayús+Alt+V),
    **encuadrar la ventana de trabajo**, **vistas guardadas** (Ctrl+Mayús+F5…F8 y
    Ctrl+F5…F8) y el recorte **«Banda de la vista»**: oculta lo que queda a más de ±5 m del
    plano que pasa por el cursor 3D (Alt+0 lo quita).
  - **Disposiciones** (Sección y planta, Datos, Diseño y perfil, Fases), el **menú del tipo
    del objeto activo** en la fila 1, en el clic derecho y con Mayús+Alt+B, y la **barra de
    estado minera** con el proyecto, su EPSG y las coordenadas reales del cursor 3D.
  - **Línea de comandos (F10)**: encuentra cualquier comando por su nombre en español o en
    inglés, sus alias (también los de Datamine), los términos de RecMin o su entrada («R-38»)
    y lo ejecuta en la vista. La lista dice dónde está cada uno, por qué coincidió si no es
    por su nombre («Nueva polilínea — ns») y, si aún no existe, «Disponible en …»; sin
    escribir nada, enseña los comandos más usados.
  - **Idioma**: español por defecto, sea cual sea el de Blender; Ayuda ▸ Idioma de Geoblender
    ▸ English lo cambia sin reiniciar (las descripciones de las preferencias, al reiniciar).
  - **Ayuda**: hoja de atajos, alias y glosario (con versión imprimible), diagnóstico de la
    instalación, «Acerca de» y Reparar la interfaz. **49 atajos**, ninguno de los que usa
    Blender en la Vista 3D, y **58 iconos propios** (CC0) con su icono de Blender de reserva.
  - **Plantilla de aplicación y lanzador**: `tools/install_app_template.py` instala la
    plantilla «Geoblender» y deja `Geoblender.cmd` en el escritorio, que abre Blender en modo
    Geoblender sobre una escena vacía en metros, con su imagen de bienvenida y sin cambiar la
    configuración del Blender normal. Con un fichero (`Geoblender.cmd fichero.blend`), lo
    abre tal como se guardó, en su espacio de trabajo.
  - La barra superior cuesta 0,03 ms por dibujo, el registro de la interfaz 18 ms y un cambio
    de idioma unos 10 ms (medido con Blender 5.2.1). Redibujar la ventana entera cuesta unos
    0,6 ms más en modo Geoblender que en modo Blender (a 1920 × 1080). Para no pasar de ahí,
    el espacio «Geoblender» se abre con la barra lateral de la Vista 3D cerrada: la pestaña
    «Proyecto» sale con **N**.

- **Proyectos de Geoblender** (spec 002). Un proyecto es una carpeta `<Nombre>.gbproj` que
  se copia, se archiva y se publica entera: su base de datos (`project.gpkg`, un GeoPackage
  que QGIS abre directamente) es la fuente de verdad, y los ficheros de Blender son vistas
  que se guardan en `scenes/` con rutas relativas, sin los datos de la interfaz de Blender
  y con la salida de render en la carpeta de la vista (también con Ctrl+S): no llevan
  ninguna ruta del equipo ni el nombre de usuario. Al abrir una, Blender conserva su
  interfaz, muestra la primera escena y avisa «Library file, loading empty scene»: los
  datos se cargan igual. En la pestaña **«Proyecto»** de la Vista 3D (tecla N) se ven
  siempre el nombre, el modo (escritura, red, copia local o solo
  lectura, con su motivo), los sistemas de referencia, el origen local, la ventana de
  trabajo y el paso de rejilla, con los botones del proyecto.
  - **Nuevo proyecto…**: nombre, carpeta, sistema de referencia horizontal (por defecto
    ETRS89 / UTM zona 30N, EPSG:25830) y vertical (por defecto altitudes de Alicante,
    EPSG:5782, o una referencia local con su descripción), ventana de trabajo (coordenadas
    con coma o punto decimal), paso de rejilla (de 0,5 a 5 m) y Z0. Una ventana fuera del
    ámbito de su sistema de referencia, pero a 3° de longitud o menos de su huso UTM (como
    Vinaròs, Benicarló o Peñíscola en EPSG:25830, la de la cartografía valenciana), se
    admite con un aviso de cuánto se sale del huso y de la deformación de escala (en
    Vinaròs, +671 ppm: 0,67 m por km). Se rechaza con el campo y el valor una ventana con X
    e Y intercambiadas, más allá de ese huso extendido o vacía, un nombre que Windows no
    admite y una carpeta tan larga que Blender no podría usar las rutas del
    proyecto (más de 259 caracteres: se dice la ruta y el límite); nunca queda una carpeta a
    medias. El sistema de referencia nunca se supone: el diálogo lo propone y, si falta, no
    se crea el proyecto. Los sistemas de referencia salen de
    un catálogo propio de 25 (EPSG, de IOGP) que no depende del PROJ del equipo.
  - **Origen local (GeoOrigin)** en metros enteros, múltiplo de 100 m cerca del centro de la
    ventana: Blender trabaja en coordenadas locales y las reales vuelven con un error
    máximo de 0,244 mm a 8 km del origen (medido con un millón de puntos; el límite es
    0,5 mm). Si la ventana se aleja más de 8 km del origen, se avisa con las esquinas y el
    error estimado.
    **Ventana de trabajo…** cambia la ventana, el paso y el origen con un motivo
    obligatorio (y el mismo aviso del huso extendido): no toca ninguna coordenada guardada
    y marca las vistas como desfasadas; deshacer (Ctrl+Z) no deshace el cambio y las deja
    desfasadas.
  - **Abrir proyecto…**, **Abrir reciente** (los 10 últimos de cada equipo, guardados en el
    equipo y no en el proyecto), **Guardar** y **Cerrar proyecto**. Al abrir se comprueba que
    la cabecera y la base de datos coinciden en identidad, sistema de referencia y origen; si
    no, no se abre y se muestran los dos valores. Una anotación hecha a mano en la cabecera
    (`manifest.json`) con una clave que no es de su formato no impide abrirlo: se avisa de
    ella y se conserva cada vez que Geoblender reescribe la cabecera, salvo si lleva una ruta
    absoluta, que se descarta (el aviso lo dice). Un fichero de Blender con otra
    georreferencia avisa y no se usa.
  - **Un solo escritor.** Quien abre un proyecto que otra persona tiene abierto lo ve en
    solo lectura con su equipo, usuario y hora, y en solo lectura no se escribe nada en la
    carpeta del proyecto. Un cerrojo que lleva más de 30 min sin renovarse (se cambia en las
    preferencias) se puede forzar desde **Cerrojo del proyecto…**, siempre con confirmación;
    quien lo perdió pasa a solo lectura con aviso en su siguiente comprobación (cada 5 min).
    Si una escritura falla por el disco o la red, el proyecto pasa a solo lectura con el
    motivo y suelta su cerrojo (o lo suelta al cerrar, si en ese momento no había red), así
    que otro equipo puede abrirlo en escritura sin esperar a que caduque. Si al cambiar la
    ventana de trabajo no se puede escribir la cabecera, manda la base de datos: el origen
    nuevo queda guardado y la cabecera se regenera al volver a abrir el proyecto.
  - **En la red (`Z:`)** se trabaja directamente, con la caché en el disco local del equipo.
    Para cálculos pesados, **Trabajar en copia local…** reserva el original y lo copia al
    disco local comprobando que la copia es idéntica, y **Publicar en la red…** sustituye el
    original por la copia y conserva el anterior como `<Nombre>.gbproj.anterior`. Si alguien
    forzó la reserva o QGIS tiene abierto el original, no se publica a medias: el original y
    la copia quedan como estaban, se explica qué hacer y se puede reintentar. Las copias
    muestran su progreso y se cancelan con Esc.
  - **QGIS.** El GeoPackage del proyecto pasa la validación de GDAL y QGIS 4.2 lo abre sin
    avisos; las tablas internas de Geoblender se ven, pero la base de datos rechaza
    cualquier cambio en ellas. Si QGIS deja la base en modo WAL (lo hace al editar un
    GeoPackage en disco local), Geoblender la devuelve al diario clásico al abrirla, sin
    perder datos y con aviso; si QGIS la tiene abierta, el proyecto se abre en solo lectura
    pidiendo que se cierre QGIS.
  - **Versiones del formato.** Un proyecto de una versión anterior se migra, si se acepta,
    con una copia previa completa junto al original; uno de una versión más moderna de
    Geoblender se abre en solo lectura indicando qué versión hace falta.
  - **Rendimiento** medido en el PC de referencia: crear, abrir o cerrar un proyecto tarda
    menos de 0,02 s en disco local y menos de 0,06 s en `Z:`; la copia local, la publicación
    y la copia previa de un proyecto de 1 GiB, entre 14 y 21 s, con el progreso al día y
    cancelables en menos de 0,1 s.
- Geoblender 0.1.0 instalable, todavía sin funciones, y la comprobación completa del
  repositorio (spec 001). La extensión se instala desde *Preferencias › Extensiones › Instalar
  desde disco* con el zip que genera `tools/build.py`, y se habilita y se desinstala sin dejar
  rastro en Blender. `tools/check.py` dice si el código está en verde: ejecuta todas las
  pruebas, también dentro de Blender, y comprueba por máquina las reglas de la constitución
  (capas, librerías, licencias, origen local en enteros, nombres y codificación de los ficheros).
  No da por buena una prueba que no llega a ejecutarse (un fichero que no se carga, una omisión
  sin un recurso que la justifique, un fallo marcado como esperado), ni una extensión que deja
  rastro en Blender al deshabilitarse, ni una comprobación que escribe en el repositorio.
- Herramientas de desarrollo (spec 001):
  - instalación de la versión del repositorio en un perfil de Blender aislado
    (`tools/dev_install.py`);
  - empaquetado del zip con prueba de instalación y desinstalación (`tools/build.py`);
  - descarga de las dependencias fijadas con su hash (`tools/fetch_wheels.py`);
  - banco privado de Silvestre, que se lee a petición y en solo lectura
    (`tools/bench_silvestre.py`).
- Licencia GPL-3.0-or-later (`LICENSE`) para el código y CC0-1.0 para los activos propios.
- Instrucciones para agentes de IA: `AGENTS.md` en la raíz y en `geoblender/`, con un
  `CLAUDE.md` junto a cada uno que los importa.
- `.editorconfig` y `.gitattributes`: UTF-8 sin BOM y finales LF.
- Comprobación de la documentación del proyecto, `tools/check_docs.py`, y la opción
  `--documentacion` de `tools/check.py` (spec 007).
- Publicación, `tools/publish.py` (spec 007): sube el código a GitHub sin forzar y deja el
  NAS igual que la carpeta del proyecto, solo si los dos repositorios están limpios y las
  dos comprobaciones en verde. El espejo nunca borra ni pisa lo que alguien haya dejado en
  el NAS: si algo cambió allí desde el último espejo, se para, lo lista y explica cómo
  traerlo al PC. Opciones `--solo-espejo` y `--rehacer-estado`.
- Herramientas del motor de cálculo (spec 004), con el Python de Blender:
  - `tools/lock_runtime.py` completa el lock del motor, `geoblender/jobs/runtime_lock.toml`:
    para la versión fijada de cada paquete, su rueda con su huella y su tamaño (los que publica
    PyPI), su licencia (la que declara la rueda) y lo que ocupa instalada;
  - `tools/fetch_runtime_wheels.py` llena el almacén de ruedas del motor (local o del NAS,
    `GEOBLENDER_WHEELHOUSE`) y solo deja las ruedas cuya huella es la del lock;
  - `tools/make_runtime.py` crea el motor de cálculo de pruebas en `.deps/runtime/`, desde el
    almacén o desde PyPI, con el mismo código que la instalación del producto.

  Con ese motor, `tools/check.py` ejecuta otra vez las pruebas unitarias de los paquetes de
  dominio con su numpy (paso «motor», a la vez que las pruebas de Blender); sin él, termina
  «VERDE CON OMISIONES» y dice cómo crearlo. `tools/check.py --rendimiento` mide además los
  trabajos en segundo plano: `tests/rendimiento/test_jobs_rendimiento.py` (lanzamiento, primer
  aviso, producto 2000 × 2000, instalación del motor, longitud de sus rutas y 100 trabajos
  seguidos) y, dentro de Blender, `tests/rendimiento/blender/perf_jobs_monitor.py` (el
  seguimiento en la barra de estado).
- `tools/check.py --rendimiento` mide también la procedencia con el volumen de un proyecto
  grande (spec 008): `tests/rendimiento/core/test_provenance_perf.py` (registrar una operación,
  lo obsoleto, la procedencia de una cifra, comprobar las entradas y los datos al abrir y el
  hash de contenido, también de las fuentes grandes) y, dentro de Blender,
  `tests/rendimiento/blender/perf_provenance_ui.py` (los avisos de la barra de estado, los
  paneles de parámetros y de entradas, y la interfaz mientras se comprueba el proyecto). Con
  `GEOBLENDER_NET_TEST_DIR`, algunas se miden también en esa carpeta de la red.
- `tools/check.py --rendimiento` mide también la topografía (spec 006) con datos generados del
  tamaño de Silvestre: `tests/rendimiento/gis/test_perf_gis.py` y `test_perf_gis_hash.py`
  (importar un MDT, la rejilla del proyecto, también desde ED50, el triangulador propio, las
  curvas, las exportaciones, la memoria y el hash de un MDT de 100 M celdas) y, dentro de
  Blender, `tests/rendimiento/blender/perf_gis.py` (el TIN de 300 000 puntos, importar un
  levantamiento y un MDT, cargar en la vista y la interfaz sin pararse). `tools/check.py
  --banco` compara, con `GEOBLENDER_SILVESTRE_DIR`, la rejilla exacta con la de la V10 de
  Silvestre sobre su MDT real, en solo lectura (`tests/banco/silvestre/test_gis_grid_area.py`).
- `tools/check.py --rendimiento` mide también los sondeos (spec 005) con una campaña generada de
  2 000 sondeos: `tests/rendimiento/test_dh_perf.py` (importarla desde CSV de principio a fin,
  validarla y sus trazas), `tests/rendimiento/test_dh_mdb_perf.py` (importarla desde una base de
  RecMin y cancelar, con el motor de Access) y `tests/rendimiento/dh/test_perf_dh_hash.py` (el
  hash de una base de RecMin de 100 MB, también con la copia y el trabajo en la red).
  `tools/check.py --banco` compara, con `GEOBLENDER_RECMIN_BANK_DIR`, la importación de una base
  real de RecMin con una lectura directa con el motor de Access de 64 bits (los recuentos por
  tabla, la suma de cada elemento, el hash de contenido y la carpeta intacta), en solo lectura y
  sobre una copia (`tests/banco/recmin/`).
- `tools/check.py --rendimiento` mide también las versiones (spec 009):
  `tests/rendimiento/core/test_versions_perf.py` (cambiar de estado con la lista de ficheros y
  sus huellas, congelar 1 GB con su avance y Esc, comprobar 200 revisiones congeladas y lo que
  crece el proyecto con 1 000 y 2 000 elementos) y, con `GEOBLENDER_NET_TEST_DIR`, en la red:
  cambiar de estado, comprobar las 200 revisiones y congelar 5 GB (unos 10 min y 10 GB en la red,
  que se borran), con las esperas de la red medidas aparte de lo que hace Geoblender en cada
  llamada (`tests/support/netwaits.py`). Con la red, sus pruebas de Python tardan unos 37 min:
  cada orden de `--rendimiento` y de `--banco` tiene ahora 2 h para terminar (las demás, 30 min
  como antes); antes se paraba a los 30 min sin dar ninguna medida.

### Cambiado

- **Una unidad antrópica nueva nace «Suelto»** (spec 011, ventana de Cubicación ▸ Materiales y densidades…; decidido con la spec 016): al
  elegir la clase «Antrópica» (el acopio, el escombro) en una unidad de la columna, su estado pasa a «Suelto», porque un acopio no está in situ
  y se pesa con V·ρ/K, no con V·ρ. Antes toda unidad nacía «In situ» y, si no se cambiaba a mano, el acopio salía un 23 % más pesado sin
  ningún aviso (el error 67). Solo se cambia si la unidad estaba en «In situ» (se puede volver a elegir «In situ») y no cambia ninguna otra
  clase, ni las columnas y unidades que ya están guardadas, ni ningún resultado de la cubicación.
- **Verificación por recinto** (spec 012, versión 0.5; hecho con la spec 016): cuando hay una **detección de acopios hecha sobre la
  superficie de partida**, la verificación **no cuenta como cortar terreno** lo que baja de un acopio hasta su base, y da aparte el **corte de
  terreno** y el **corte de acopios** (en las zonas sin corte, de solo relleno, de solo restauración, la banda de resguardo y la banda hacia
  dentro de un límite legal; fuera del límite legal, los intocables, las exclusiones, fuera del perímetro, el relleno y la afección cuentan
  todo el movimiento). Antes, retirar un acopio en una zona sin corte daba «no cumple» y pedía aceptación con motivo al congelar cada
  revisión. La base es **automática** —las detecciones al día hechas sobre la partida; con varias, la menor— y **la ventana de «Verificar un
  diseño por recinto…» dice qué base usa o por qué no** (obsoleta, o hecha sobre otra superficie: entonces todo el corte cuenta); la tabla por
  recinto lleva «Corte de terreno (m³)» y «Corte de acopios (m³)» y el veredicto es el de terreno; una celda por debajo de la base sigue
  siendo «no cumple». Cada base es una entrada de la verificación: cambiar la detección la deja obsoleta. **Sin acopios detectados, la
  verificación da exactamente lo de siempre.**
- **La comprobación de cada tarea deja fuera las pruebas pesadas de la spec 016** (RNF-016-06): las clases con proyecto de 2 m de la
  detección, la retirada, el contrafuerte y el cuerpo, y los módulos de Blender más pesados pasan a ficheros `milestone_*.py`, sin cambiar una
  aserción; los ejecuta el paso «hito» de `--completo` (que la publicación pide siempre) y cada requisito de la 016 sigue teniendo en el
  «verde» al menos una prueba (lo guarda `tests/unit/design/test_milestone_coverage_016.py`). La 016 cuesta unos 3 s más en el «verde», que sigue
  sobre los 48 s de RNF-001-01 desde antes de esta spec.
- **La comprobación de cada tarea deja fuera las pruebas pesadas de la spec 015** (RNF-015-07; plan
  015 §7.4): las clases con proyecto que repiten un escenario por variante (la cascada de lo
  declarado, descartar y soltar, traer, insertar, la capa de entidades, congelar, la edición de la
  tabla de lo declarado…) y los módulos de Blender «Entidad ▾» más pesados pasan a ficheros `milestone_*.py`, sin
  cambiar una aserción: `tools/check.py` no los descubre y los ejecuta el paso nuevo «hito» de
  `--completo`, que la publicación pide siempre (y el resumen lo dice sin la opción). Cada requisito
  de la 015 sigue teniendo en el «verde» al menos una prueba (lo guarda
  `tests/unit/design/test_milestone_coverage.py`) y la regla TST-02 admite ese nombre en
  `tests/unit` y `tests/blender`. `--completo` tarda unos 20 s más.
- **Límites y restricciones** (spec 012, versiones 0.3 y 0.4; hechos con la spec 015): la compilación de
  las máscaras consume también las restricciones que declaran las entidades de diseño, que son de la
  versión y no de las tres capas del proyecto (RF-012-29), y una declarada que llega después de compilar
  deja obsoletas las máscaras (antes, el grafo no lo habría visto y los operadores habrían diseñado sin su
  prohibición). Las máscaras que solo están obsoletas por el ciclo de una entidad que protege (la entidad
  consume las máscaras, que consumen lo que ella declara) se entregan como al día, excepción de RF-012-17
  que aprobó Samuel el 15/11/2026; cualquier otra causa las sigue dejando obsoletas (cada una de las cuatro
  tiene ahora su prueba: tres de las cuatro mutaciones de esa comprobación sobrevivían a las pruebas). También
  una versión **sin** tabla de declaradas con una entidad que protege deja las máscaras obsoletas hasta que se
  declara, y **Compilar las máscaras** y todo operador de diseño declaran antes de compilar. Sin entidades que
  declaren, todo es como antes.
- **Procedencia** (spec 008, hecho con la spec 015; cambios aditivos y revisables): una operación en curso puede
  anotar al terminar las entradas que solo conoce entonces (el apoyo que se detecta al recalcular); lo que se
  descartó por completo no vuelve al plan de «Recalcular lo obsoleto» (sigue obsoleto como historia); una
  operación puede ofrecer «darla por buena» sin lo que consumió, y su rechazo dice que espera esa decisión; y
  dar por buena una operación de una versión, también al aceptar la edición de una de sus tablas, no deshace
  lo aceptado; y «Recalcular lo obsoleto» recorre el plan de una vez, volviendo a planificar entre una operación
  y otra, cuando lo recalculado vuelve a quedar obsoleto por un ciclo entre operaciones (hasta que no queda nada
  que se pueda rehacer, se cancela con Esc o llega a un tope que avisa), en vez de rehacer una sola por pulsación.
  Nada cambia sin entidades de diseño.
- **Formato del proyecto, versión 3** (spec 009): la base del proyecto lleva las tablas de las
  versiones, las revisiones y las decisiones de la propiedad (QGIS las ve y no las puede cambiar,
  como las demás internas), y el proyecto, cuando se congela una revisión, la carpeta
  `snapshots/`. Un proyecto del formato 2 se migra al abrirlo, si se acepta, con una copia
  completa previa (`<Nombre>.gbproj.respaldo-esquema-2`), sin cambiar ningún dato; sin migrar, se
  abre en solo lectura. Un Geoblender anterior abre un proyecto migrado en solo lectura, y uno
  que ya tiene alguna versión, **solo con su cabecera** (nombre, sistemas de referencia, origen y
  la lista de revisiones congeladas), para que no presente como vigentes las cifras de una versión
  que no lo es: hay que actualizarlo.
- **Formato del proyecto, versión 2** (spec 008): la base del proyecto lleva las tablas de la
  procedencia (QGIS las ve y no las puede cambiar, como las demás internas), y el proyecto,
  cuando hacen falta, dos carpetas nuevas: `originals/` (los originales de las entradas) y
  `orphans/` (los restos apartados). Un proyecto creado antes se migra al abrirlo, si se
  acepta, con una copia completa previa junto al original
  (`<Nombre>.gbproj.respaldo-esquema-1`), y queda sin parámetros, entradas ni operaciones; sin
  migrar, se abre en solo lectura. Un Geoblender anterior abre un proyecto migrado en solo
  lectura, diciendo qué versión hace falta.
- El código vive en su propio repositorio (spec 007), con la extensión en `geoblender/`; la
  documentación del proyecto, interna de IMGA, queda en otro que no se publica. Las
  herramientas encuentran la raíz del código por el manifiesto y `tools/check.py`, y la
  comprobación completa ya no necesita la documentación al lado: en el PC de referencia, con
  el código en su disco local, con las pruebas de la publicación (`--completo`) tarda unos
  62 s.
- `tools/check.py` reparte las pruebas unitarias en 16 procesos y las de Blender en 5
  Blender que se ejecutan a la vez dentro de su paso (los pasos siguen uno tras otro), sin
  quitar ni acortar ninguna. Desde la spec 004, el reparto sigue lo que tardó cada módulo de
  pruebas en la comprobación anterior (guardado fuera del repositorio, en
  `%TEMP%\geoblender-tiempos\`; la primera vez, por número de pruebas). La comprobación de
  cada tarea pasó de unos 55 s a unos 25 s en el PC de referencia; con las pruebas de la
  spec 004 y su paso «motor» llegó a unos 40 s, y con más procesos (spec 006) volvió a unos
  30 s; con las pruebas de la 006 y de la 008 juntas, y más procesos en el paso «motor»,
  llegó a unos 40 s, y con 16 procesos de pruebas unitarias tarda unos 38 s. Ahora las
  reglas leen y analizan cada fichero una sola vez por proceso, las pruebas que las pasan por
  el repositorio van juntas en el mismo proceso y el paso «motor» reparte sus procesos (16
  como mucho, antes 19) por lo que tarda cada carpeta, y tarda unos 35 s; las reglas dan los
  mismos incumplimientos que antes. Cada prueba se
  ejecuta en una sola parte, y si las partes no suman las pruebas que hay, el paso falla.
  Una prueba con un presupuesto de milisegundos mide otra vez mientras la máquina está
  cargada, sin cambiar el presupuesto. Con las pruebas de la topografía (spec 006) y de la
  procedencia (spec 008) completas llegó a unos 50 s; ahora tarda unos 37 s, con las mismas
  pruebas y alguna más: dentro de Blender, las clases de pruebas que no prueban el registro
  ya no vuelven a importar la extensión cada vez que la habilitan (la registran otra vez
  sobre los módulos ya cargados, como al desactivarla y activarla en las preferencias); los
  6 Blender (antes 5) comparten una copia de la extensión que la comprobación prepara y
  compila mientras corren las pruebas unitarias; y cada proceso de pruebas unitarias, con
  las duraciones guardadas, solo importa sus módulos de prueba (antes, todos), y dice
  cuántos módulos tiene de cuántos hay. Las pruebas que miden cuánto tarda en pararse un
  trabajo, en devolver «ocupado» una escritura o en vencer un tiempo máximo miden otra vez
  mientras la máquina está cargada, también sin cambiar sus plazos. Con las últimas pruebas
  de la topografía volvió a unos 40 s (44 s con otros programas abiertos en el equipo); ahora
  tarda unos 37 s (con esos programas abiertos) con las mismas pruebas y alguna más: los
  procesos de cada paso se reparten los módulos según acaban, de una cola que comparten, y
  no por lo que tardaron la vez anterior, así que acaban casi a la vez; los casos de
  referencia también van en 6 procesos (de 2,0 a 0,9 s); las de Blender, en 7 Blender; la
  prueba que inicia la GPU (tras ella, abrir un `.blend` tarda 25 veces más en ese Blender)
  va la última de su proceso; las clases que prueban el registro devuelven al terminar los
  módulos de la extensión que tenían cargados las demás, que ya no la importan otra vez; y
  cada proceso de pruebas unitarias ya no analiza todos los ficheros de prueba para saber
  cuáles van juntos (0,6 s menos cada uno). Tres pruebas que dependían del orden (lo que
  dejaban registrado otras en el mismo proceso, o una cancelación que la carga no dejaba
  medir) ya no dependen de él. Con las pruebas de la importación de los sondeos (spec 005)
  llegó a unos 42 s; ahora tarda unos 37,5 s con las mismas pruebas y alguna más: las órdenes
  de Python leen el código compilado de una carpeta de la temporal del sistema
  (`%TEMP%\geoblender-pyc\`, al día al empezar la comprobación; lo del repositorio,
  validado por el hash de cada fuente) en vez de compilarlo cada una; las bases de RecMin
  sintéticas se crean una vez y se copian a cada prueba que las necesita
  (`%TEMP%\geoblender-datos\`); las pruebas unitarias van en 18 procesos (antes 16); y la
  prueba de Blender que va la última de su proceso ya no espera al final de la cola, que
  dejaba a su Blender casi 1 s detrás de los demás. Con las últimas pruebas de los sondeos
  volvió a unos 42 s, limitada por los procesadores del equipo; ahora la comprobación de
  cada tarea ya no ejecuta el paso «motor» (las mismas pruebas unitarias de los paquetes
  de dominio, otra vez con el numpy del motor de cálculo): lo ejecuta `--completo`, que la
  publicación pide siempre (spec 004, versión 0.4), y el resumen lo dice. Tarda unos 34 s
  (con `--completo`, unos 97 s). Las pruebas que copiaban entradas a la carpeta de un
  trabajo ya no dejan una carpeta en `%TEMP%` cada vez (las entradas son de solo lectura y
  no se borraban). Con las pruebas de las vistas regenerables (spec 010), unos 38 s. Con las de
  las versiones (spec 009), unos 4 s más con el equipo en el mismo estado: ahora las pruebas de
  referencia, la comprobación de las licencias y la de los iconos se ejecutan a la vez que las de
  Blender (spec 001, versión 0.8), y el resumen las sigue diciendo en su orden, cada una con su
  duración; y crear un proyecto escribe una imagen de su base hecha una vez por proceso (de 17,5
  a 12,7 ms), con el mismo esquema. IMGA sube su límite de 40 a 45 s (spec 001, versión 0.9, y
  spec 007, versión 0.6): unos 41 s en reposo y unos 47 s con otros programas abiertos en el
  equipo.
- Solo un `tools/check.py` a la vez en el equipo (spec 006): si hay otro en marcha (de la
  misma carpeta, de un *worktree* o de otra sesión), el nuevo dice a cuál espera (su pid y su
  carpeta) y empieza cuando termina; su tiempo se cuenta desde entonces. Antes los dos se
  estorbaban: tardaban más y las pruebas que miden tiempos fallaban. Si una comprobación se
  cierra de golpe, la siguiente no queda esperando ni hay que borrar nada a mano.
  `tools/publish.py` espera igual.
- **Cubicación de la topografía con celdas de 4 m** (spec 006, versión 0.4, por decisión de
  IMGA): el caso de referencia del volumen entre dos superficies (una corta circular de
  1 308 944,006 m³) admite con celdas de 4 m un error de hasta el 0,025 % (antes, el 0,02 %)
  en cualquier posición de la corta respecto a la rejilla. Con el eje de la corta sobre un
  nodo de la rejilla da +0,0202 %, que antes quedaba fuera de la prueba y ahora se comprueba.
  El cálculo no cambia: es exacto celda a celda, y la diferencia viene de muestrear la corta
  con una rejilla gruesa. Con celdas de 2, 1 y 0,5 m sigue el 0,01 %.
- **Una orden que no se hace ya no dice «Terminado»** (trabajos en segundo plano, spec 004; por
  la 006): si el cálculo termina bien pero su operación no se hace al incorporarla al proyecto
  (un TIN con roturas que se cruzan, una entrada que ya estaba registrada), la línea del trabajo
  en la barra de estado dice durante 10 s «Operación fallida» (con el icono de error) u
  «Operación cancelada», su duración y el principio del motivo, y el motivo entero llega al
  registro de Blender (Info) como error, con su ventana emergente, o como aviso. Antes decía
  «Terminado» y el motivo solo quedaba en los avisos del panel Proyecto, cortado a su anchura.
- **Los ajustes de cada operación en su procedencia** (spec 008; por la 006): en Grafo de
  operaciones y procedencia, debajo de cada operación sale una fila con los ajustes de su orden,
  con su nombre y su unidad («Ajustes: Equidistancia = 2 m · Cota base = 0 m»; «Puntos que
  coinciden = Preguntar»), antes de sus parámetros; nunca un nombre de fichero ni una ruta.
  Antes solo se veían los parámetros, y no con qué equidistancia se habían hecho unas curvas.
- **El hash de contenido de una tabla, unas cuatro veces más deprisa** (spec 008; por la 005):
  las filas de una tabla se hashean por columnas y, las de una tabla que se acaba de calcular,
  sin guardarlas antes en una base temporal. Los hashes son los mismos, bit a bit (los de los
  vectores de referencia y los de los proyectos ya creados). Las 500 000 filas de los
  análisis de una campaña de 2 000 sondeos, de 7,9 s a 1,7 s.
- **La interfaz ya no se para al terminar un trabajo ni al importar una campaña grande**
  (spec 004 y 008; por la 005): la comprobación de los resultados de un trabajo en segundo
  plano (su huella) se hace en otro hilo, y el trabajo sigue «En curso» hasta que acaba; la
  rejilla con que se valida y lo leído al aplicar una importación los copia su trabajo; lo que
  se envía a un trabajo va por partes; los trabajos de una importación se sueltan de uno en
  uno; los indicadores de la procedencia no leen el proyecto mientras Geoblender escribe en
  él, y, con el proyecto en la red, cada paso de una escritura envía lo suyo al servidor en
  vez de dejarlo todo para el final; las operaciones de una orden de importación con varios
  ficheros se empiezan de una vez, y la vista lee solo su esquema y su elemento. Con una campaña
  de 2 000 sondeos y 500 000 análisis, ninguna espera de la interfaz pasa de 0,14 s en disco
  local (antes, hasta 1,2 s), ni de 0,16 s en la red en cuatro recorridos (antes, hasta 1,9 s;
  una vez se vio una espera del servidor de 0,39 s).
- **El hash de contenido de una base de RecMin grande avisa siempre de su avance** (spec 008;
  por la 005): el trabajo de hash de una fuente que se copia antes de leerla (una base de
  Access) avisa de su avance mientras la copia y comprueba su huella, y se puede cancelar en
  ese momento; las tablas de una base de RecMin se convierten y se hashean por trozos. Con una
  base de 101 MB (2 000 sondeos y 875 000 muestras de 20 elementos), 22 s, con un aviso cada
  0,24 s como mucho (antes, la copia pasaba 1,9 s sin avisar y la tabla de muestras, 4,4 s), y
  cancelar la para en 0,12 s sin dejar ningún proceso vivo. Los hashes son los mismos.

### Corregido

- Un cálculo en segundo plano cuyo Blender muere justo cuando avisa de su avance termina como
  «padre perdido» (código 4, con su motivo en el registro del trabajo), igual que el que lo
  descubre al vigilar su entrada; antes, de vez en cuando, salía con una excepción no capturada
  (código 1) en el registro. En los dos casos termina en menos de 5 s (spec 004).
- En Diseño ▸ Parámetros ▸ Sectores de diseño…, «Declarar de nuevo desde una capa…» deja en la
  misma ventana, sin cerrarla, los sectores nuevos, el talud que vuelve a su sector, «Parámetros
  sin sector» con los valores de los sectores que ya no existen y lo que dice la declaración
  («Sectores declarados: …»); antes la ventana seguía enseñando los sectores de antes hasta
  cerrarla y abrirla otra vez. Ningún cálculo ni cifra cambia (spec 013).
- En Diseño ▸ «Envolventes y escalonado…», la «Superficie» de las semillas y la «Superficie de
  partida» del escalonado proponen el terreno: el MDT o el TIN seleccionado en la vista; con una
  superficie de diseño seleccionada, la de partida con que se hizo; sin selección, la primera
  superficie de la lista que no es una envolvente, unas bermas ni una superficie de diseño. Antes
  proponían la primera de la lista, que con un diseño en el proyecto era la rejilla de sus bermas.
  La lista sigue ofreciéndolas todas y ningún cálculo ni cifra cambia (spec 013).
- En Diseño ▸ «Vista previa de semillas, dominios y restricciones», la «Superficie» de las semillas
  propone el terreno, como «Envolventes y escalonado…»; antes proponía la primera de la lista, que
  con un diseño en el proyecto era la rejilla de sus bermas. La lista sigue ofreciéndolas todas y
  ningún cálculo ni cifra cambia (spec 013).
- En Diseño ▸ Parámetros ▸ Sectores de diseño…, «Parámetros sin sector» ya no lista el valor por
  defecto sin valor que el proyecto registra cuando una operación lee el talud de un sector («— ·
  valor por defecto de Geoblender»): no hay nada que declarar de nuevo. Los valores que decidió una
  persona se siguen listando y nada se borra. Ningún cálculo ni cifra cambia (spec 013).
