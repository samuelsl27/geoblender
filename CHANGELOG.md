# Historial de cambios

Todos los cambios relevantes de Geoblender se anotan aquí, escritos para quien lo usa.

Formato basado en [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/).
Versionado según [SemVer 2.0.0](https://semver.org/lang/es/); la versión vive en
`geoblender/blender_manifest.toml`. Mientras la versión sea 0.y.z, cualquier cosa puede
cambiar.

## [Sin publicar]

Geoblender 0.1.0 ya se instala (spec 001), crea y abre proyectos con su sistema de
referencia y su origen local (spec 002), tiene su interfaz (spec 003) y ejecuta los cálculos
largos en segundo plano, con un motor de cálculo opcional (spec 004), aunque todavía no
tiene funciones mineras. Lo de la spec 002 está comprobado también con QGIS 4.2 sin su
interfaz (PyQGIS) y en la red con un solo equipo; falta con dos equipos a la vez, y que IMGA
acepte esas pruebas de QGIS y, en lugar de la del panel del proyecto, las de la interfaz de la
spec 003. Lo de la spec 003 está comprobado en una pantalla de 1920 × 1080 con Windows al 125 %,
salvo algunas teclas en modo Blender, la lista de F3 en los dos modos, la barra T de Blender, la
fila 1, el clic derecho, Mayús+Alt+B y la chincheta, la fila 2 en edición, dos idiomas de
entrada, la plantilla instalada en el Blender de cada uno, la revisión de los iconos y la
lectura de la barra con tres ingenieros. Lo de la spec 004 está comprobado en esa misma
pantalla, con el motor de cálculo instalado desde un almacén de ruedas en el disco del equipo;
falta el almacén del NAS de IMGA.

### Añadido

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

### Cambiado

- El código vive en su propio repositorio (spec 007), con la extensión en `geoblender/`; la
  documentación del proyecto, interna de IMGA, queda en otro que no se publica. Las
  herramientas encuentran la raíz del código por el manifiesto y `tools/check.py`, y la
  comprobación completa ya no necesita la documentación al lado: en el PC de referencia, con
  el código en su disco local, con las pruebas de la publicación (`--completo`) tarda unos
  62 s.
- `tools/check.py` reparte las pruebas unitarias en 12 procesos y las de Blender en 5
  Blender que se ejecutan a la vez dentro de su paso (los pasos siguen uno tras otro), sin
  quitar ni acortar ninguna. Desde la spec 004, el reparto sigue lo que tardó cada módulo de
  pruebas en la comprobación anterior (guardado fuera del repositorio, en
  `%TEMP%\geoblender-tiempos\`; la primera vez, por número de pruebas). La comprobación de
  cada tarea pasó de unos 55 s a unos 25 s en el PC de referencia; con las pruebas de la
  spec 004 y su paso «motor» llegó a unos 40 s, y con más procesos (spec 006) volvió a unos
  30 s; con las pruebas de la 006 y de la 008 juntas, y más procesos en el paso «motor»,
  tarda unos 40 s. Cada prueba se ejecuta en una sola parte, y si las partes no suman las
  pruebas que hay, el paso falla. Una prueba con un presupuesto de milisegundos mide otra
  vez mientras la máquina está cargada, sin cambiar el presupuesto.
