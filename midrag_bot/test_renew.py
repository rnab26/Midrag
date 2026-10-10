"""Tests de renew.py avec un faux Midrag et un faux GitHub (aucun réseau).

Lancer : python -m unittest midrag_bot/test_renew.py  (depuis la racine)
"""
import base64
import json
import os
import sys
import time
import unittest
from unittest import mock

import requests
from nacl import encoding, public

sys.path.insert(0, os.path.dirname(__file__))
import renew  # noqa: E402


def jwt(exp):
    part = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"h.{part}.s"


class Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeWorld:
    """Midrag + GitHub simulés. Garde les secrets écrits, déchiffrés."""

    def __init__(self, midrag_ok=True):
        self.midrag_ok = midrag_ok
        self.secrets = {}
        self.deleted = []
        self.files = {}
        self.midrag_calls = []
        self.private = public.PrivateKey.generate()
        self.token = jwt(int(time.time()) + 30 * 86400)

    def midrag_post(self, session, url, json=None, **kw):
        path = url.split(".il/", 1)[1]
        self.midrag_calls.append((path, json))
        if not self.midrag_ok:
            return Resp(200, {"operationStatus": 2, "message": "קוד שגוי"})
        data = {
            "Account/Login": {"uuid": "uuid-123"},
            "Account/SendCode": {"ok": True, "x": 1},
            "Account/Token": {"token": self.token},
        }[path]
        return Resp(200, {"operationStatus": 1, "data": data})

    def gh(self, method, url, json=None, **kw):
        if url.endswith("/actions/secrets/public-key"):
            pk = self.private.public_key.encode(encoding.Base64Encoder).decode()
            return Resp(200, {"key": pk, "key_id": "k1"})
        if "/actions/secrets/" in url:
            name = url.rsplit("/", 1)[1]
            if method == "PUT":
                box = public.SealedBox(self.private)
                self.secrets[name] = box.decrypt(base64.b64decode(json["encrypted_value"])).decode()
                return Resp(201)
            self.deleted.append(name)
            return Resp(204)
        if "/contents/" in url:
            if method == "PUT":
                self.files[url] = base64.b64decode(json["content"]).decode()
                return Resp(201, {})
            return Resp(404)
        raise AssertionError(url)

    def run(self, step, env):
        base = {
            "MIDRAG_SP_ID": "12345", "MIDRAG_PHONE": "050-123 4567", "MIDRAG_COMPANY": "9999",
            "RENEW_GH_TOKEN": "ghp_x", "GITHUB_REPOSITORY": "o/r", "GITHUB_REF_NAME": "main",
        }
        base.update(env)
        with mock.patch.dict(os.environ, base, clear=True), \
             mock.patch.object(requests.Session, "post", self.midrag_post_bound()), \
             mock.patch.object(requests.Session, "get", lambda s, u, **k: self.gh("GET", u, **k)), \
             mock.patch.object(requests.Session, "put", lambda s, u, **k: self.gh("PUT", u, **k)), \
             mock.patch.object(requests.Session, "delete", lambda s, u, **k: self.gh("DELETE", u, **k)):
            return renew.main(["renew.py", step])

    def midrag_post_bound(self):
        return lambda s, url, **kw: self.midrag_post(s, url, **kw)


class RenewTests(unittest.TestCase):
    def test_send_range_le_sms_et_garde_l_etat(self):
        w = FakeWorld()
        self.assertEqual(w.run("send", {}), 0)
        paths = [p for p, _ in w.midrag_calls]
        self.assertEqual(paths, ["Account/Login", "Account/SendCode"])
        login_body = w.midrag_calls[0][1]
        self.assertEqual(login_body["phoneNumber"], "0501234567")  # tirets/espaces retirés
        self.assertEqual(login_body["spId"], 12345)
        self.assertEqual(json.loads(w.secrets["MIDRAG_PENDING"])["uuid"], "uuid-123")

    def test_verify_remplace_le_token_et_nettoie(self):
        w = FakeWorld()
        env = {"MIDRAG_PENDING": json.dumps({"uuid": "uuid-123", "cookies": {}}), "MIDRAG_SMS_CODE": "123456"}
        self.assertEqual(w.run("verify", env), 0)
        self.assertEqual(w.secrets["MIDRAG_TOKEN"], w.token)
        self.assertEqual(sorted(w.deleted), ["MIDRAG_PENDING", "MIDRAG_SMS_CODE"])
        token_body = w.midrag_calls[0][1]
        self.assertEqual(token_body, {"spId": 12345, "verificationCode": "123456", "uuid": "uuid-123"})
        status = json.loads(next(iter(w.files.values())))
        self.assertIn("expires_at", status)
        self.assertNotIn(w.token, json.dumps(status))  # jamais le token lui-même

    def test_code_refuse_par_midrag_echoue_sans_ecrire_de_secret(self):
        w = FakeWorld(midrag_ok=False)
        env = {"MIDRAG_PENDING": json.dumps({"uuid": "u", "cookies": {}}), "MIDRAG_SMS_CODE": "123456"}
        self.assertEqual(w.run("verify", env), 1)
        self.assertNotIn("MIDRAG_TOKEN", w.secrets)
        self.assertEqual(w.deleted, [])  # le code reste, l'ancien token aussi

    def test_code_mal_forme(self):
        w = FakeWorld()
        env = {"MIDRAG_PENDING": json.dumps({"uuid": "u"}), "MIDRAG_SMS_CODE": "12ab"}
        self.assertEqual(w.run("verify", env), 1)
        self.assertEqual(w.midrag_calls, [])

    def test_verify_sans_send_prealable(self):
        self.assertEqual(FakeWorld().run("verify", {"MIDRAG_SMS_CODE": "123456"}), 1)

    def test_identifiants_manquants(self):
        w = FakeWorld()
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(renew.main(["renew.py", "send"]), 1)
        self.assertEqual(w.midrag_calls, [])

    def test_etape_inconnue(self):
        self.assertEqual(renew.main(["renew.py", "nimporte"]), 2)


if __name__ == "__main__":
    unittest.main()
