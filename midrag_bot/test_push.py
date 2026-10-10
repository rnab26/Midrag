"""Tests des notifications push : vrai envoi Web Push (chiffrement + signature
VAPID) vers un faux service push local, décodé puis vérifié.

Lancer : python -m unittest midrag_bot/test_push.py  (depuis la racine)
"""
import base64
import http.server
import json
import os
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

import http_ece
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid

sys.path.insert(0, os.path.dirname(__file__))
import bot  # noqa: E402
import push  # noqa: E402

b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
unb64u = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
TZ = ZoneInfo("Asia/Jerusalem")


class FakePushService:
    """Reçoit les envois comme le ferait le service push de Chrome."""

    def __init__(self, status=201):
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append((dict(self.headers), body))
                self.send_response(status)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/push/abc"

    def close(self):
        self.server.shutdown()


def make_world(status=201):
    """Un « téléphone » (clés d'abonnement) et une paire VAPID, comme la page les crée."""
    browser_key = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    service = FakePushService(status)
    sub = {
        "endpoint": service.endpoint,
        "keys": {
            "p256dh": b64u(browser_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)),
            "auth": b64u(auth),
        },
    }
    vapid = Vapid()
    vapid.generate_keys()
    raw_private = b64u(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
    raw_public = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return service, browser_key, auth, sub, raw_private, raw_public


class PushTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def env(self, sub, private):
        return mock.patch.dict(os.environ, {"WEBPUSH_SUBSCRIPTION": json.dumps(sub), "VAPID_PRIVATE_KEY": private})

    def test_envoi_complet_dechiffre_et_signe(self):
        service, browser_key, auth, sub, private, public = make_world()
        self.addCleanup(service.close)
        with self.env(sub, private):
            self.assertTrue(push.send_push("Titre", "Corps", tag="midrag-token"))
        headers, body = service.requests[0]
        clear = http_ece.decrypt(body, private_key=browser_key, auth_secret=auth, version="aes128gcm")
        self.assertEqual(
            json.loads(clear),
            {"title": "Titre", "body": "Corps", "tag": "midrag-token", "url": push.CONFIG_PAGE},
        )
        # Signature VAPID : « vapid t=<jwt>, k=<clé publique> », jwt vérifiable avec k.
        auth_header = {k.lower(): v for k, v in headers.items()}["authorization"]
        self.assertTrue(auth_header.startswith("vapid "))
        parts = dict(p.strip().split("=", 1) for p in auth_header[len("vapid "):].split(","))
        self.assertEqual(unb64u(parts["k"]), public)
        head, claims, sig = parts["t"].split(".")
        self.assertEqual(json.loads(unb64u(claims))["sub"], push.VAPID_SUBJECT)
        raw_sig = unb64u(sig)
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        der = encode_dss_signature(int.from_bytes(raw_sig[:32], "big"), int.from_bytes(raw_sig[32:], "big"))
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public).verify(
            der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())
        )

    def test_secrets_absents_rien_envoye(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(push.send_push("t", "b", tag="x"))

    def test_abonnement_expire_ne_casse_pas_le_run(self):
        service, _, _, sub, private, _ = make_world(status=410)
        self.addCleanup(service.close)
        with self.env(sub, private):
            self.assertFalse(push.send_push("t", "b", tag="x"))  # pas d'exception

    def test_cle_invalide_ne_casse_pas_le_run(self):
        service, _, _, sub, _, _ = make_world()
        self.addCleanup(service.close)
        with self.env(sub, b64u(bytes(32))):  # 0 n'est pas une clé privée P-256 valide
            self.assertFalse(push.send_push("t", "b", tag="x"))


class ReminderTests(unittest.TestCase):
    def test_texte_selon_le_delai(self):
        now = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
        _, body3 = bot.expiry_push_text(now + timedelta(days=3, hours=2), now, TZ)
        self.assertIn("dans 3 jours", body3)
        _, body1 = bot.expiry_push_text(now + timedelta(hours=20), now, TZ)
        self.assertIn("moins de 24 h", body1)
        title, body0 = bot.expiry_push_text(now - timedelta(hours=1), now, TZ)
        self.assertIn("expiré", title)
        self.assertIn("plus maintenue", body0)

    def test_fenetre_du_rappel(self):
        expiry = datetime.now(timezone.utc) + timedelta(days=2)
        at = lambda h, m: datetime(2026, 11, 6, h, m, tzinfo=TZ)
        with mock.patch.object(bot, "send_push") as sent:
            bot.remind_expiry(expiry, at(8, 59), TZ, 9)   # avant
            bot.remind_expiry(expiry, at(9, 30), TZ, 9)   # après la fenêtre
            bot.remind_expiry(expiry, at(10, 0), TZ, 9)   # autre heure
            self.assertEqual(sent.call_count, 0)
            bot.remind_expiry(expiry, at(9, 0), TZ, 9)
            bot.remind_expiry(expiry, at(9, 29), TZ, 9)
            self.assertEqual(sent.call_count, 2)
            self.assertEqual(sent.call_args.kwargs["tag"], bot.PUSH_TAG_TOKEN)

    def test_heure_reglable(self):
        expiry = datetime.now(timezone.utc) + timedelta(days=2)
        with mock.patch.object(bot, "send_push") as sent:
            bot.remind_expiry(expiry, datetime(2026, 11, 6, 20, 5, tzinfo=TZ), TZ, 20)
            self.assertEqual(sent.call_count, 1)

    def test_panne_notifiee_seulement_a_la_creation_de_l_issue(self):
        with mock.patch.object(bot, "send_push") as sent:
            with mock.patch.object(bot, "_open_issue_once", return_value=False):
                bot.report_failure("Panne")
            self.assertEqual(sent.call_count, 0)  # issue déjà ouverte : silence
            with mock.patch.object(bot, "_open_issue_once", return_value=True):
                bot.report_failure("Panne")
            self.assertEqual(sent.call_count, 1)

    def test_heure_par_defaut(self):
        self.assertEqual(bot.DEFAULT_NOTIFY_HOUR, 9)
        cfg = bot.load_config()  # config.yaml actuel : pas encore de notify_hour
        self.assertIsInstance(cfg.notify_hour, int)

    def test_notification_test_ne_ping_pas(self):
        with mock.patch.dict(os.environ, {"TEST_PUSH": "true"}, clear=True), \
             mock.patch.object(bot, "send_push", return_value=True) as sent, \
             mock.patch.object(bot, "set_slider_status") as ping:
            self.assertEqual(bot.main(), 0)
        self.assertEqual(sent.call_count, 1)
        ping.assert_not_called()
        with mock.patch.dict(os.environ, {"TEST_PUSH": "true"}, clear=True), \
             mock.patch.object(bot, "send_push", return_value=False):
            self.assertEqual(bot.main(), 1)  # échec visible pour la page


if __name__ == "__main__":
    unittest.main()
