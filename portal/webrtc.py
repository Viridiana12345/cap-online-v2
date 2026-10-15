"""Browser ICE configuration; never expose the TURN shared secret."""
import base64
import hashlib
import hmac
import time

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from requests.exceptions import RequestException
from twilio.base.exceptions import TwilioException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client


class TurnUnavailable(Exception):
    """Safe error without provider credentials or response bodies."""


def get_twilio_ice_servers(ttl=3600):
    if not all((settings.TWILIO_ACCOUNT_SID, settings.TWILIO_API_KEY,
                settings.TWILIO_API_SECRET)):
        raise TurnUnavailable("Falta configurar Twilio en el servidor.")
    if not isinstance(ttl, int) or not 1 <= ttl <= 86400:
        raise ValueError("TURN TTL must be between 1 and 86400 seconds.")
    try:
        client = Client(
            settings.TWILIO_API_KEY, settings.TWILIO_API_SECRET,
            account_sid=settings.TWILIO_ACCOUNT_SID,
            http_client=TwilioHttpClient(timeout=10),
        )
        servers = client.tokens.create(ttl=ttl).ice_servers
    except (TwilioException, RequestException):
        raise TurnUnavailable("No se pudo contactar al servicio de videollamadas.") from None
    if not isinstance(servers, list) or not servers:
        raise TurnUnavailable("El servicio no devolvió servidores TURN.")
    clean = []
    has_turn = False
    for server in servers:
        if not isinstance(server, dict):
            raise TurnUnavailable("Respuesta TURN inválida.")
        urls = server.get("urls") or server.get("url")
        values = [urls] if isinstance(urls, str) else urls
        if not isinstance(values, list) or not values or any(
            not isinstance(url, str) or not url.startswith(("stun:", "stuns:", "turn:", "turns:"))
            for url in values
        ):
            raise TurnUnavailable("Respuesta TURN inválida.")
        item = {"urls": urls}
        if any(url.startswith(("turn:", "turns:")) for url in values):
            if not server.get("username") or not server.get("credential"):
                raise TurnUnavailable("Respuesta TURN sin credenciales.")
            item.update(username=server["username"], credential=server["credential"])
            has_turn = True
        clean.append(item)
    if not has_turn:
        raise TurnUnavailable("El servicio no devolvió servidores TURN.")
    return clean


def rtc_configuration(user_id):
    policy = settings.WEBRTC_ICE_TRANSPORT_POLICY
    if policy not in {"all", "relay"}:
        raise ImproperlyConfigured("ICE policy must be all or relay.")
    if any((settings.TWILIO_ACCOUNT_SID, settings.TWILIO_API_KEY, settings.TWILIO_API_SECRET)):
        return {"iceServers": get_twilio_ice_servers(), "iceTransportPolicy": policy}
    urls = settings.WEBRTC_TURN_URLS or settings.WEBRTC_TURN_URL
    if isinstance(urls, str):
        urls = [url.strip() for url in urls.split(",") if url.strip()]
    servers = [{"urls": settings.WEBRTC_STUN_URLS}] if settings.WEBRTC_STUN_URLS else []
    if urls:
        if any(not url.startswith(("turn:", "turns:")) for url in urls):
            raise ImproperlyConfigured("WEBRTC_TURN_URLS must contain turn: or turns: URLs.")
        username = settings.WEBRTC_TURN_USERNAME
        credential = settings.WEBRTC_TURN_CREDENTIAL
        if settings.WEBRTC_TURN_SHARED_SECRET:
            username = f"{int(time.time()) + settings.WEBRTC_TURN_TTL}:{user_id}"
            credential = base64.b64encode(hmac.new(
                settings.WEBRTC_TURN_SHARED_SECRET.encode(), username.encode(), hashlib.sha1,
            ).digest()).decode()
        if not username or not credential:
            raise ImproperlyConfigured("TURN requires credentials or WEBRTC_TURN_SHARED_SECRET.")
        servers.append({"urls": urls, "username": username, "credential": credential})
    policy = settings.WEBRTC_ICE_TRANSPORT_POLICY
    if policy not in {"all", "relay"} or (policy == "relay" and not urls):
        raise ImproperlyConfigured("ICE policy must be all, or relay with TURN configured.")
    return {"iceServers": servers, "iceTransportPolicy": policy}
