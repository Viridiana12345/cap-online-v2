import base64
import hashlib
import hmac
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from .webrtc import TurnUnavailable, get_twilio_ice_servers, rtc_configuration


@override_settings(
    TWILIO_ACCOUNT_SID="", TWILIO_API_KEY="", TWILIO_API_SECRET="",
    WEBRTC_TURN_URLS=[], WEBRTC_TURN_URL="", WEBRTC_TURN_USERNAME="",
    WEBRTC_TURN_CREDENTIAL="", WEBRTC_TURN_SHARED_SECRET="",
    WEBRTC_ICE_TRANSPORT_POLICY="all", WEBRTC_TURN_TTL=3600,
    WEBRTC_STUN_URLS=["stun:stun.example.org:3478"],
)
class RTCConfigurationTests(SimpleTestCase):
    def test_local_stun_configuration(self):
        self.assertEqual(len(rtc_configuration(1)["iceServers"]), 1)

    @override_settings(WEBRTC_TURN_URL="turn:relay.example.org:3478",
                       WEBRTC_TURN_USERNAME="user", WEBRTC_TURN_CREDENTIAL="password")
    def test_legacy_url_supported(self):
        self.assertEqual(rtc_configuration(1)["iceServers"][1]["username"], "user")

    @override_settings(WEBRTC_TURN_URLS=["turn:relay.example.org:3478?transport=udp",
                                        "turns:relay.example.org:443?transport=tcp"],
                       WEBRTC_TURN_SHARED_SECRET="test-secret", WEBRTC_ICE_TRANSPORT_POLICY="relay")
    @patch("portal.webrtc.time.time", return_value=1000)
    def test_temporary_credentials_and_transports(self, clock):
        config = rtc_configuration(42)
        turn = config["iceServers"][1]
        self.assertEqual(config["iceTransportPolicy"], "relay")
        self.assertEqual(len(turn["urls"]), 2)
        self.assertEqual(turn["username"], "4600:42")
        expected = base64.b64encode(hmac.new(b"test-secret", b"4600:42", hashlib.sha1).digest()).decode()
        self.assertEqual(turn["credential"], expected)
        self.assertNotIn("test-secret", str(config))

    @override_settings(WEBRTC_TURN_URLS=["turn:relay.example.org:3478"])
    def test_missing_credentials_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            rtc_configuration(1)

    @override_settings(WEBRTC_ICE_TRANSPORT_POLICY="relay")
    def test_relay_requires_turn(self):
        with self.assertRaises(ImproperlyConfigured):
            rtc_configuration(1)

    @override_settings(WEBRTC_TURN_URLS=["https://relay.example.org"])
    def test_invalid_scheme_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            rtc_configuration(1)


@override_settings(TWILIO_ACCOUNT_SID="account-test", TWILIO_API_KEY="key-test",
                   TWILIO_API_SECRET="secret-test", WEBRTC_ICE_TRANSPORT_POLICY="relay")
class TwilioTests(SimpleTestCase):
    @patch("portal.webrtc.Client")
    def test_token_is_connected_to_browser_configuration(self, client):
        client.return_value.tokens.create.return_value.ice_servers = [
            {"urls": "stun:example.org"},
            {"urls": "turn:example.org", "username": "temporary", "credential": "temporary-password", "extra": "ignored"},
        ]
        config = rtc_configuration(1)
        client.return_value.tokens.create.assert_called_once_with(ttl=3600)
        self.assertEqual(client.call_args.kwargs["account_sid"], "account-test")
        self.assertEqual(config["iceTransportPolicy"], "relay")
        self.assertEqual(config["iceServers"][1]["username"], "temporary")
        self.assertNotIn("extra", config["iceServers"][1])
        self.assertNotIn("secret-test", str(config))

    @override_settings(TWILIO_API_SECRET="")
    @patch("portal.webrtc.Client")
    def test_partial_configuration_fails_without_network(self, client):
        with self.assertRaises(TurnUnavailable):
            rtc_configuration(1)
        client.assert_not_called()

    @patch("portal.webrtc.Client")
    def test_network_error_is_sanitized(self, client):
        from requests.exceptions import Timeout
        client.return_value.tokens.create.side_effect = Timeout("secret-test")
        with self.assertRaises(TurnUnavailable) as error:
            get_twilio_ice_servers()
        self.assertNotIn("secret-test", str(error.exception))

    @patch("portal.webrtc.Client")
    def test_stun_only_response_rejected(self, client):
        client.return_value.tokens.create.return_value.ice_servers = [{"urls": "stun:example.org"}]
        with self.assertRaises(TurnUnavailable):
            get_twilio_ice_servers()

    @patch("portal.webrtc.Client")
    def test_bad_ttl_does_not_request_token(self, client):
        with self.assertRaises(ValueError):
            get_twilio_ice_servers(86401)
        client.assert_not_called()
