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
proyecto y las cifras de la selección (spec 010, aún sin integrar en la rama principal). Lo de
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
el recorrido del MDT y los sondeos, con las órdenes reales; falta verlo en la pantalla de
referencia (el resaltado de Refrescar, abrir una vista con doble clic y los paneles).

### Añadido

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
    (F5)»), y la superposición de los sondeos (etiquetas, leyendas y marcas) se rehace en
    segundo plano. Abrir tarda lo mismo con la vista que sin ella.
  - **Abrir el proyecto de una vista.** Al abrir con doble clic una vista sin su proyecto, además
    del aviso de siempre, un diálogo ofrece «Abrir el proyecto de esta vista»: lo busca donde lo
    guardó la vista y, si no está, entre los proyectos recientes del equipo por su identidad, y
    lo abre con sus reglas de siempre (cerrojo, solo lectura, migración). «Ahora no» no abre
    nada, y el panel Proyecto mantiene el botón. Si no lo encuentra, dice dónde se esperaba y
    con qué identidad, y «Localizar el proyecto…» solo acepta ese proyecto. No se ofrece en un
    guion sin interfaz, al recuperar una sesión o un autoguardado, ni en una vista dentro de una
    copia de respaldo del proyecto (`.anterior`, `.respaldo-esquema-N`, `.publicando`).
  - **N ▸ Proyecto ▸ Elemento activo**: del dato del objeto activo, leído del proyecto, su tipo,
    su estado, si está al día en la vista, su versión («—» hasta que lleguen las versiones), la
    operación que escribió su contenido (con su fecha y la versión de Geoblender), sus entradas
    con su hash, sus derivados con «obsoleto» y sus cifras con su unidad y su tipo; Procedencia
    abre su cadena entera.
  - **N ▸ Proyecto ▸ Inventario**: lo registrado en el proyecto, cargado o no (entradas y
    datos), con su estado, sus marcas (obsoleto, entrada cambiada) y si está en la escena;
    filtros por tipo, estado (los vivos, por defecto), versión, presencia en la escena y texto
    (sin distinguir mayúsculas ni tildes), como mucho 500 filas a la vez («… y 19 500 más: afine
    el filtro»), y Cargar en la vista, Descargar y Procedencia de la fila elegida (desactivadas
    con su motivo si no se puede).
  - **Cifras de la selección** (control 29; Herramientas ▸ Consulta): las cifras registradas de
    los datos de los objetos seleccionados, con su insignia de tipo, su unidad y sus marcas
    («depende de una hipótesis», «obsoleta»). No mide nada; hasta que la cubicación registre las
    primeras, dice «Sin cifras registradas». Cada objeto guarda además, en texto de solo
    lectura, las cifras de su dato, puestas al día al cargarlo y en cada Refrescar; ningún
    cálculo las lee.
  - Medido con Blender 5.2.1 en el PC de referencia: Refrescar una vista con 200 datos de los
    que cambiaron 10 (uno, una malla de 1 millón de vértices), 1,3 s (≤ 5 s), con el avance cada
    0,13 s como mucho y Esc en 0,12 s; el inventario de un proyecto de 20 000 datos se abre y se
    filtra en 0,08 s como mucho (≤ 0,5 s; en `Z:`, 0,07 s); la marca de 200 datos que quedan
    obsoletos a la vez, al día en 0,63 s (≤ 1 s), sin que ningún paso pase de 20 ms (en `Z:`,
    tampoco).

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

### Cambiado

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
  no se borraban). Con las pruebas de las vistas regenerables (spec 010), unos 38 s.
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
