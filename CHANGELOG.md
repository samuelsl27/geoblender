# Historial de cambios

Todos los cambios relevantes de Geoblender se anotan aquí, escritos para quien lo usa.

Formato basado en [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/).
Versionado según [SemVer 2.0.0](https://semver.org/lang/es/); la versión vive en
`geoblender/blender_manifest.toml`. Mientras la versión sea 0.y.z, cualquier cosa puede
cambiar.

## [Sin publicar]

Geoblender 0.1.0 ya se instala (spec 001), crea y abre proyectos con su sistema de
referencia y su origen local (spec 002) y tiene su interfaz (spec 003), aunque todavía no
tiene funciones mineras. Lo de la spec 002 está probado sin interfaz y en la red con un solo
equipo; falta comprobarlo con la interfaz de Blender, con QGIS abierto y con dos equipos a la
vez. Lo de la spec 003 está probado sin la interfaz gráfica; falta verlo en la pantalla.

### Añadido

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
    configuración del Blender normal.
  - La barra superior cuesta 0,03 ms por dibujo, el registro de la interfaz 18 ms y un cambio
    de idioma unos 10 ms (medido con Blender 5.2.1).

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

### Cambiado

- El código vive en su propio repositorio (spec 007), con la extensión en `geoblender/`; la
  documentación del proyecto, interna de IMGA, queda en otro que no se publica. Las
  herramientas encuentran la raíz del código por el manifiesto y `tools/check.py`, y la
  comprobación completa ya no necesita la documentación al lado: en el PC de referencia, con
  el código en su disco local, tarda unos 40 s con las pruebas de la publicación (antes,
  unos 48 s en la unidad de red, sin ellas).
- `tools/check.py` reparte las pruebas unitarias en 4 procesos y las de Blender en 3
  Blender que se ejecutan a la vez dentro de su paso (los pasos siguen uno tras otro), sin
  quitar ni acortar ninguna: la comprobación de cada tarea pasa de unos 55 s a unos 25 s
  en el PC de referencia. Cada prueba se ejecuta en una sola parte, y si las partes no
  suman las pruebas que hay, el paso falla.
