# ASEMACO · Documentos electrónicos de control administrativo

Aplicación para socios con cuentas independientes, datos habituales y logotipo por empresa. Genera PDF nativo con QR integrado, QR PNG independiente y ZIP con ambos. El PNG y el ZIP se generan al descargarlos y no ocupan almacenamiento permanente. Máximo admitido por PDF: **5.000.000 bytes (5 MB)**.

## Cambios de esta versión

- Validación de domicilio del cargador contractual, origen/destino, naturaleza de mercancía y peso positivo en kg. Si no puede determinarse el peso exacto, se permite una magnitud alternativa con explicación. Exige matrículas de vehículo y remolque cuando corresponda, y referencia de autorización especial cuando se declare necesaria.
- La fecha del transporte es distinta de la creación del fichero. Registra creación/modificación y las incluye en los metadatos del PDF. Requiere confirmar que el servicio no ha comenzado y que se entregará el documento al conductor. La aplicación no conoce ni demuestra el inicio efectivo: la declaración debe ser verdadera.
- El QR devuelve directamente el PDF sin sesión ni página intermedia. Desactivar una cuenta impide su acceso privado pero **no interrumpe la consulta pública de los documentos**.
- Los PDF nuevos tienen hash SHA-256 verificado al descargarlos; no se editan en el servidor. Para rectificar, se genera otro PDF y QR con referencia al anterior y motivo del cambio. Se conservan todas las versiones. Solo puede rectificarse la última versión de un servicio sin finalizar. Hay que entregar el nuevo PDF y QR al conductor; no se envían automáticamente.
- El socio registra la finalización efectiva del servicio desde su ficha. No puede introducir una fecha futura, anterior a la creación de alguna versión o al inicio declarado del transporte. Todas las versiones comparten el plazo de conservación.
- No permite borrar ni desactivar los QR antes de **12 meses desde la finalización registrada**. Después se permite el borrado manual de todo el servicio con confirmación y aviso de que todos sus QR dejan de funcionar. La desactivación posterior es reversible mientras se conserve el documento.
- Borrado automático de todo el servicio a los **15 meses naturales desde su finalización registrada**. Sin finalización registrada, no caduca automáticamente. Esto evita eliminar un servicio en curso. El socio debe finalizar los servicios efectivamente terminados; la aplicación no conoce por sí sola su finalización.
- Se conservan eventos de auditoría con identificador, usuario, operación y fecha tras borrar los documentos; se vacía el detalle de esos eventos. Las copias descargadas y las copias externas de seguridad requieren su propia política de conservación.

El bloqueo de desactivación durante un año es una política conservadora para facilitar la descarga por cargador y transportista; no implica que la norma prohíba toda desactivación antes de ese plazo. Los plazos aparecen en la interfaz y en los nuevos PDF. Los meses se calculan en hora de Madrid, ajustando al último día del mes cuando corresponda.

## Alcance normativo y límites

Referencias revisadas: Resolución de 5 de junio de 2026 (BOE-A-2026-12784) y artículo 6 de la Orden FOM/2861/2012 (BOE-A-2013-154).

Esta versión gestiona un envío de mercancías por documento. No genera documentos internacionales ni hojas de ruta de viajeros. Es un DeCA administrativo: no incluye firma electrónica avanzada ni funcionalidades de carta de porte contractual. Se han retirado los espacios de firma manual para evitar confundir ambos usos. Las referencias de adjuntos son texto, no archivos adicionales.

Las pruebas funcionales y los cambios de código **no constituyen certificación jurídica ni homologación**. Antes de usarlo en carretera, hay que verificar en el servidor real la disponibilidad, certificado, TLS 1.2 o superior y descarga pública directa. La corrección del contenido, la entrega al conductor y la conservación por las partes siguen dependiendo de la operación real. Mantener reloj del servidor sincronizado, dominio estable y copias restaurables.

## Actualizar una instalación existente

1. Detener la aplicación y hacer copia completa de `data` (base SQLite, PDF y logotipos), o del volumen Docker.
2. Sustituir el código conservando `data` y la configuración `.env`. No sobrescribir una base real con datos de prueba.
3. Actualizar dependencias o reconstruir Docker. Arrancar primero la aplicación para aplicar la migración y después la limpieza.
4. Los documentos anteriores se marcan como heredados; no se regeneran ni se certifican retroactivamente. Se conserva su URL original. Su expiración anterior se retira mientras no exista finalización registrada: revisar sus datos, estado del QR y registrar la finalización real. Los enlaces previamente revocados no se reactivan automáticamente; el propietario puede reactivarlos.

La migración no recupera documentos ya eliminados. Un documento heredado que sea incorrecto debe revisarse antes de usarlo: los cambios no incorporan mágicamente campos ni metadatos a PDF antiguos.

## Instalar con Docker en Linux

1. Copiar `.env.example` a `.env`.
2. Generar `SECRET_KEY` con `python3 -c "import secrets; print(secrets.token_hex(32))"`.
3. Definir `PUBLIC_BASE_URL` con el dominio HTTPS definitivo, sin rutas ni barra final. No emitir documentos reales antes de configurar ese dominio: las URL quedan fijadas en los QR.
4. Ejecutar `docker compose up -d --build`.
5. Crear el administrador: `docker compose exec app flask --app app:create_app create-admin`. Solicita correo y contraseña (mínimo 12 caracteres).
6. Configurar certificado válido y proxy HTTPS hacia `127.0.0.1:8000`. Se incluye `deploy/nginx.conf.example`: sustituir dominio y rutas de certificados; permite únicamente TLS 1.2 y 1.3. `TRUST_ONE_PROXY=1` solo cuando la app es accesible exclusivamente desde ese proxy.
7. Entrar como administrador, abrir «Gestionar socios» y crear una cuenta por empresa. El socio cambia su contraseña en el primer acceso. No hay registro público ni credenciales predeterminadas. Entregar las credenciales por un canal adecuado; no incluye correo automático ni MFA.

El volumen `asemaco_data` guarda SQLite, PDF y logotipos. Usar un único servidor con almacenamiento persistente; esta versión no está preparada para réplicas con bases independientes. No borrar el volumen al actualizar. Mantener copias consistentes y comprobar restauraciones.

Comprobación antes de activar: generar un documento de prueba con la URL definitiva, abrir su QR desde un teléfono sin sesión y verificar que devuelve el PDF directamente; comprobar por separado la configuración TLS mínima y renovación del certificado. Este paquete no configura ni comprueba un servidor al que no se le ha dado acceso.

## Prueba local con Windows / Laragon

Laragon puede alojar la carpeta, pero la aplicación necesita **Python 3.11 o superior**; no es PHP. Descomprimir `asemaco_web` en `C:\laragon\www`. Abrir PowerShell en esa carpeta y ejecutar:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:SECRET_KEY = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))")
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:8000'
$env:COOKIE_SECURE = '0'
$env:TRUST_ONE_PROXY = '0'
.\.venv\Scripts\python.exe -m flask --app app:create_app create-admin
.\.venv\Scripts\python.exe -m flask --app app:create_app run --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000`. Mantener la consola abierta. Al abrir una consola nueva, volver a definir las variables de configuración con **la misma clave secreta guardada para esa instalación**. No es necesario recrear el administrador. En Linux usar los comandos equivalentes con `python3`, activar `.venv` y exportar las variables.

HTTP local muestra un aviso en interfaz y PDF. Solo sirve para pruebas: un QR con 127.0.0.1 no puede abrirse desde otro equipo y no es operativo DeCA. En producción usar HTTPS y Gunicorn (incluido en Docker), no el servidor de desarrollo.

## Limpieza y mantenimiento

Docker incluye un servicio `retention` que limpia cada hora sin depender de visitas. La app también intenta limpiar al recibir peticiones, como máximo una vez por hora por proceso. Desde el vencimiento se bloquea la descarga aunque el borrado físico esté pendiente. Los servicios no finalizados no se purgan.

Sin Docker, configurar una tarea horaria:

- Linux: ejecutar `RUTA_VENV/bin/python RUTA_APP/retention_worker.py --once` mediante cron/systemd.
- Windows: Programador de tareas, programa `C:\laragon\www\asemaco_web\.venv\Scripts\python.exe`, argumentos `C:\laragon\www\asemaco_web\retention_worker.py --once` y directorio inicial `C:\laragon\www\asemaco_web`.

Configurar `DATA_DIR` si se usa otra ubicación y otorgar permisos de lectura/borrado. Prueba manual: `python retention_worker.py --once`. Revisar errores de limpieza y rotación de copias externas. SQLite reutiliza espacio liberado pero su fichero no tiene por qué reducirse inmediatamente.

Cada empresa guarda su perfil, catálogos y documentos independientes. Puede subir PNG/JPG de hasta 2 MB y 16 megapíxeles; el logotipo se optimiza a 600 × 600 píxeles, respetando proporciones. Cambiarlo no altera PDF anteriores. El frontal conserva ASEMACO. El administrador no dispone de pantalla para leer documentos ajenos; el operador del servidor sí tiene acceso técnico a datos y copias.

Quien reciba un QR podrá ver todos los datos del PDF, también los del conductor. No hay listado público y se envían instrucciones de no indexación. Sesiones de ocho horas, protección CSRF, contraseñas scrypt y bloqueo temporal de intentos fallidos. Mantener dependencias actualizadas y dimensionar/monitorizar disponibilidad y almacenamiento.

## Pruebas incluidas

`python -m unittest discover -s tests -v`

Las pruebas usan datos temporales. Cubren aislamiento, acceso público, desactivación de cuentas, QR/ZIP, logotipos, conservación, borrado protegido, migración, rectificaciones, integridad, límite de PDF y metadatos. No sustituyen una auditoría externa ni una prueba de carga del alojamiento.
