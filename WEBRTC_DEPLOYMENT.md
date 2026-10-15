# Videollamadas entre redes

## Twilio en Render

La integración ya lee TWILIO_ACCOUNT_SID, TWILIO_API_KEY y TWILIO_API_SECRET.
Si cualquiera está definida, se exige configurar las tres. Twilio tiene prioridad
sobre el TURN manual descrito abajo. No hacen falta WEBRTC_TURN_URLS ni credenciales
TURN manuales para usar Twilio.

Al entrar a una sala autorizada, Django pide un token de 3600 segundos con un
timeout de 10 segundos y entrega únicamente los servidores ICE y sus credenciales
temporales al navegador. Las credenciales API permanecen en el servidor. Si falla
Twilio se muestra una página para reintentar (503), sin iniciar la llamada ni
ocultar el fallo con STUN solamente. Recargar la sala obtiene un token nuevo.

El .env local ya se carga mediante _load_local_env; no se necesita python-dotenv.
Render usa sus variables Environment: no necesita subir el .env local. Los cambios
de código y requirements.txt deben llegar al despliegue antes de que estas variables
activen la integración. No basta con volver a desplegar una revisión antigua.

Una respuesta correcta de la API verifica autenticación y emisión de credenciales,
pero la comprobación de audio/video entre redes del final sigue siendo necesaria.

La aplicación señaliza mediante HTTP autenticado (CallSignal en la base de datos),
no mediante Django Channels. ASGI solo sirve Django HTTP; no hay consumers,
WebSockets ni channel layer. Cambiar a Channels no resuelve NAT: el audio/video
necesita TURN cuando no puede establecer una conexión directa.

## Variables del servidor

Configurar un servicio TURN real (proveedor o coturn con IP pública). Ejemplo,
reemplazando los dominios por los endpoints que realmente ofrece el servicio:

```dotenv
WEBRTC_TURN_URLS=turn:turn.example.org:3478?transport=udp,turn:turn.example.org:3478?transport=tcp,turns:turn.example.org:443?transport=tcp
WEBRTC_TURN_USERNAME=usuario-del-proveedor
WEBRTC_TURN_CREDENTIAL=credencial-del-proveedor
WEBRTC_ICE_TRANSPORT_POLICY=all
```

La variable anterior WEBRTC_TURN_URL sigue funcionando. WEBRTC_TURN_URLS tiene
prioridad. Con coturn y autenticación TURN REST, usar WEBRTC_TURN_SHARED_SECRET
en vez de usuario/contraseña: debe coincidir con static-auth-secret del servidor
coturn (use-auth-secret activado). Django genera credenciales HMAC-SHA1 temporales;
el secreto compartido nunca se envía al navegador. WEBRTC_TURN_TTL es 86400
segundos por defecto; debe cubrir la sesión. Sin shared secret, las credenciales
del proveedor llegan al navegador por necesidad del protocolo: usar credenciales
de alcance limitado y rotarlas según su política.

No hay credenciales públicas incorporadas ni un TURN desplegado por este cambio.
Las URL de ejemplo no son servidores funcionales.

## Red y aplicación

- Servir CAP Online desde un dominio público con HTTPS y certificado válido.
  getUserMedia no funciona sobre HTTP remoto; localhost tiene una excepción.
- Configurar ALLOWED_HOSTS y CSRF_TRUSTED_ORIGINS para el dominio público.
  El proxy debe conservar Host e informar X-Forwarded-Proto correctamente.
- Todos los workers deben compartir la base de datos de señalización (PostgreSQL
  en despliegues con varias instancias), sin caché del proxy para /portal/api/call/.
- TURN requiere puertos públicos propios: UDP/TCP 3478 y TLS TCP 443 (o el puerto
  que publique el proveedor), además del rango UDP de relay del servidor.
  Coturn detrás de NAT necesita external-ip y apertura de ese rango en firewall.
  TURN TLS requiere un certificado válido del dominio TURN; un proxy HTTP de
  Django no sustituye un listener TURN. El puerto 443 de ejemplo solo funciona
  si el servidor TURN realmente escucha allí.

## Comprobación real

1. Probar el servicio con https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/
   y confirmar candidatos de tipo relay; no compartir credenciales en capturas.
2. Temporalmente establecer WEBRTC_ICE_TRANSPORT_POLICY=relay y reiniciar Django.
3. Abrir la misma cita vigente como doctor y paciente: uno en Wi-Fi y otro en
   datos móviles, ambos en el dominio HTTPS público. Activar cámara/micrófono.
4. Confirmar audio/video bidireccional y candidate-pair seleccionado con relay
   en chrome://webrtc-internals o about:webrtc. Probar también TURN TLS desde
   una red que bloquee UDP. Revisar errores de autenticación y firewall si falla.
5. Recargar cada participante por separado y verificar recuperación; probar
   permisos denegados y el botón de reintento.
6. Restablecer policy=all para permitir conexión directa cuando sea posible.

Las pruebas automatizadas validan configuración y acceso a las salas, pero no
certifican conectividad real entre dos redes. Esa validación requiere navegadores,
permisos de cámara/micrófono y un servicio TURN accesible.
