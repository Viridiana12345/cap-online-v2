# CAP Online V2

Proyecto integrador con **portal web + cliente móvil + un solo backend/base de datos**.

## Incluido

### Web pública
- Landing informativa.
- Servicios y psicólogos publicados.
- Login, registro de paciente y recuperación de contraseña.

### Paciente
- Dashboard móvil/responsive basado en el diseño de Figma.
- Catálogo y perfil de psicólogos.
- Citas: crear, cancelar y reprogramar.
- Chat con profesionales con relación de atención.
- Notificaciones.
- Perfil/configuración.
- Videollamada WebRTC para citas **online aprobadas**.

### Psicólogo
- Dashboard.
- Foto y perfil profesional.
- Agenda y aprobación/rechazo/finalización de citas.
- Disponibilidad semanal.
- Chat.
- Notas clínicas restringidas a pacientes relacionados.
- Notificaciones.
- Videollamada.

### Administrador
- Alta y listado de psicólogos desde el portal administrativo.
- Django Admin sigue disponible en `/admin/`.

### API móvil `/api/v1/`
- Login/logout con bearer token (el servidor guarda únicamente hash del token).
- Usuario actual.
- Psicólogos.
- Citas.
- Cancelación de citas.
- Conversaciones y mensajes.
- Notificaciones.
- Preparación de videollamada.

### App móvil
Carpeta `mobile/`, preparada para Capacitor Android/iOS. La aplicación entra directamente al Login, consume la API de Django y reutiliza la misma base de datos.

Biometría:
- Android: huella/biometría disponible.
- iPhone: Face ID.
- En navegador normal se muestra un fallback porque el navegador no dispone del plugin nativo.

> iOS puede compartir el mismo código, pero compilar y firmar la app requiere Xcode en macOS.

---

# Ejecutar local en Windows

## Opción rápida
Haz doble clic en:

`run_local.bat`

La primera vez:
1. crea `venv`;
2. instala dependencias;
3. ejecuta migraciones;
4. inicia Django en `http://127.0.0.1:8000`.

También puedes usar PowerShell:

```powershell
.\run_local.ps1
```

## Manual

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DEBUG="True"
python manage.py migrate
python manage.py runserver
```

Abre:

`http://127.0.0.1:8000`

## Datos demo opcionales
Si quieres usuarios de prueba, después de instalar las dependencias ejecuta:

`load_demo.bat`

Credenciales:

- Paciente: `paciente@caponline.local` / `Paciente123!`
- Psicóloga: `doctora@caponline.local` / `Doctora123!`

No es obligatorio; tu `db.sqlite3` original se conserva y fue migrado a la estructura nueva.

---

# Recuperación de contraseña local

En local Django usa el backend de correo de consola. Al solicitar recuperación, el enlace aparece en la terminal donde ejecutaste `runserver`.

En Render configura SMTP mediante las variables indicadas en `.env.example`.

---

# Videollamada local

La sala está vinculada a una cita con:
- estado `Aprobada`;
- modalidad `Online`.

Para probar:
1. inicia sesión como paciente en un navegador normal;
2. abre otro navegador/perfil incógnito con el doctor;
3. ambos abren la misma cita y pulsan Videollamada;
4. concede cámara y micrófono.

La señalización usa Django y `CallSignal`. El video/audio utiliza WebRTC del navegador. En redes restrictivas puede requerirse un servidor TURN para producción; el proyecto incluye STUN público como base.

---

# Vista previa de la app móvil

Con Django ejecutándose:

```powershell
cd mobile
npm install
npm run dev
```

Abre `http://127.0.0.1:5173`.

## Android Studio

```powershell
cd mobile
npm install
npx cap add android
npm run build
npx cap sync android
npx cap open android
```

Para el emulador Android, la app usa por defecto:

`http://10.0.2.2:8000/api/v1`

Si usas un teléfono Android físico, entra a Perfil en la app y cambia la URL de API por la IP local de tu PC, por ejemplo:

`http://192.168.1.20:8000/api/v1`

Para permitir acceso desde otro dispositivo, ejecuta Django así:

```powershell
python manage.py runserver 0.0.0.0:8000
```

y agrega temporalmente la IP/nombre necesario a `ALLOWED_HOSTS` mediante variable de entorno.

---

# Render

El backend puede seguir en Render y usar PostgreSQL mediante `DATABASE_URL`.

El flujo es:

```text
CAP Online Web ───────┐
                      ├── Django / API ── PostgreSQL
CAP Online Mobile ────┘
```

`Dockerfile` usa Gunicorn para producción y `build.sh` ejecuta `collectstatic` + migraciones. No crea superusuarios automáticamente.

Para fotos de doctores en producción recuerda usar almacenamiento persistente/externo para `MEDIA_ROOT`; WhiteNoise es para archivos estáticos, no para uploads.

---

# Pruebas

Se ejecutaron las pruebas del proyecto después de los cambios:

**49 pruebas aprobadas.**

Incluyen permisos por rol, recuperación de contraseña, modelos y API móvil básica.

---

# Importante antes de uso real

CAP Online es un proyecto académico. Antes de usar datos clínicos reales se deben revisar requisitos legales/privacidad, almacenamiento de archivos, política de retención, cifrado/gestión de secretos, logs y una infraestructura de videollamada con TURN adecuada.
