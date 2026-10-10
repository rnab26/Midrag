#!/usr/bin/env python3
"""Renouvelle le token Midrag sans favori ni ordinateur.

La connexion Midrag = 3 appels (Account/Login -> Account/SendCode ->
Account/Token). Un serveur n'est pas soumis au CORS qui obligeait à passer
par un favori dans le navigateur : GitHub Actions peut les faire lui-même.
Seul le code SMS reste humain, d'où deux étapes lancées depuis la page :

  send    Login + SendCode. Le SMS part ; l'état de la connexion en cours
          (uuid + cookies) est rangé dans le secret MIDRAG_PENDING.
  verify  Token avec le code que la page a rangé dans MIDRAG_SMS_CODE.
          Le token obtenu remplace le secret MIDRAG_TOKEN, les secrets
          temporaires sont supprimés, et la date d'expiration (pas le token)
          est publiée dans midrag_bot/token_status.json pour la page.

Les secrets s'écrivent avec RENEW_GH_TOKEN (un jeton GitHub limité à ce
repo, posé par la page) : le GITHUB_TOKEN d'un workflow n'a pas le droit
d'écrire des secrets. Aucun token, code ni uuid n'est jamais affiché dans
les logs.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import timezone

import requests
from nacl import encoding, public

from bot import token_expiry

API = "https://biz-api.midrag.co.il/"
OK = 1  # operationStatus.Success
HEADERS = {
    "Origin": "https://bizn.midrag.co.il",
    "Referer": "https://bizn.midrag.co.il/",
    "Accept": "application/json",
}
GITHUB_API = "https://api.github.com"
STATUS_PATH = "midrag_bot/token_status.json"

SECRET_TOKEN = "MIDRAG_TOKEN"
SECRET_PENDING = "MIDRAG_PENDING"
SECRET_CODE = "MIDRAG_SMS_CODE"


class RenewError(Exception):
    """Erreur dont le message est lisible tel quel dans les logs."""


def midrag_call(session: requests.Session, path: str, body: dict):
    try:
        resp = session.post(API + path, json=body, headers=HEADERS, timeout=30)
    except requests.RequestException as exc:
        raise RenewError(f"{path} : Midrag injoignable ({type(exc).__name__}).") from exc
    try:
        payload = resp.json()
    except ValueError:
        raise RenewError(f"{path} : réponse illisible de Midrag (HTTP {resp.status_code}).")
    if payload.get("operationStatus") != OK:
        detail = payload.get("message") or f"code {payload.get('errorCode', payload.get('operationStatus'))}"
        raise RenewError(f"{path} : Midrag a refusé la demande ({detail}).")
    data = payload.get("data")
    # data est souvent un objet à une seule clé ({uuid: ...}, {token: ...}) :
    # on le déballe comme le fait le site.
    if isinstance(data, dict) and len(data) == 1:
        data = next(iter(data.values()))
    return data


# --- GitHub ------------------------------------------------------------------

def gh_session() -> tuple[requests.Session, str, str]:
    token = os.environ.get("RENEW_GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token:
        raise RenewError(
            "Le secret RENEW_GH_TOKEN est absent : active d'abord le renouvellement "
            "en un tap depuis la page de configuration."
        )
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s, repo, os.environ.get("GITHUB_REF_NAME", "")


def put_secret(name: str, value: str) -> None:
    s, repo, _ = gh_session()
    key_resp = s.get(f"{GITHUB_API}/repos/{repo}/actions/secrets/public-key", timeout=30)
    key_resp.raise_for_status()
    key = key_resp.json()
    sealed = public.SealedBox(
        public.PublicKey(key["key"].encode(), encoding.Base64Encoder)
    ).encrypt(value.encode())
    resp = s.put(
        f"{GITHUB_API}/repos/{repo}/actions/secrets/{name}",
        json={
            "encrypted_value": base64.b64encode(sealed).decode(),
            "key_id": key["key_id"],
        },
        timeout=30,
    )
    if resp.status_code not in (201, 204):
        raise RenewError(f"Écriture du secret {name} refusée (HTTP {resp.status_code}).")


def delete_secret(name: str) -> None:
    s, repo, _ = gh_session()
    resp = s.delete(f"{GITHUB_API}/repos/{repo}/actions/secrets/{name}", timeout=30)
    if resp.status_code not in (204, 404):
        print(f"Suppression du secret {name} impossible (HTTP {resp.status_code}).", file=sys.stderr)


def publish_expiry(token: str) -> None:
    """Publie la date d'expiration (jamais le token) pour que la page l'affiche,
    quel que soit l'appareil. Best effort : un échec ici ne doit pas annuler un
    renouvellement réussi."""
    expiry = token_expiry(token)
    if expiry is None:
        return
    try:
        s, repo, branch = gh_session()
        url = f"{GITHUB_API}/repos/{repo}/contents/{STATUS_PATH}"
        current = s.get(url, params={"ref": branch}, timeout=30)
        body = {
            "message": "Token Midrag renouvelé : mise à jour de la date d'expiration",
            "content": base64.b64encode(
                json.dumps({"expires_at": expiry.astimezone(timezone.utc).isoformat()}).encode()
            ).decode(),
            "branch": branch,
        }
        if current.status_code == 200:
            body["sha"] = current.json()["sha"]
        resp = s.put(url, json=body, timeout=30)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"Date d'expiration non publiée : {type(exc).__name__}", file=sys.stderr)


# --- Étapes ------------------------------------------------------------------

def credentials() -> dict:
    try:
        return {
            "spId": int(os.environ["MIDRAG_SP_ID"].strip()),
            "phoneNumber": os.environ["MIDRAG_PHONE"].strip().replace("-", "").replace(" ", ""),
            "companyNumber": os.environ["MIDRAG_COMPANY"].strip(),
        }
    except (KeyError, ValueError) as exc:
        raise RenewError(
            "Identifiants Midrag absents ou invalides (MIDRAG_SP_ID, MIDRAG_PHONE, "
            "MIDRAG_COMPANY) : refais « Activer » depuis la page de configuration."
        ) from exc


def step_send() -> None:
    values = credentials()
    send_method = int(os.environ.get("MIDRAG_SEND_METHOD") or 1)  # 1 = SMS, 2 = WhatsApp
    session = requests.Session()
    uuid = midrag_call(session, "Account/Login", values)
    if not uuid or not isinstance(uuid, str):
        raise RenewError("Account/Login : Midrag n'a pas renvoyé d'identifiant de connexion.")
    midrag_call(session, "Account/SendCode", {**values, "uuid": uuid, "sendMethod": send_method})
    put_secret(
        SECRET_PENDING,
        json.dumps({"uuid": uuid, "cookies": requests.utils.dict_from_cookiejar(session.cookies)}),
    )
    print("Code envoyé.")


def step_verify() -> None:
    values = credentials()
    code = (os.environ.get(SECRET_CODE) or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise RenewError("Le code SMS est absent ou n'a pas 6 chiffres.")
    try:
        pending = json.loads(os.environ[SECRET_PENDING])
        uuid = pending["uuid"]
    except (KeyError, ValueError) as exc:
        raise RenewError(
            "Aucune connexion en attente : demande d'abord un code (étape « send »)."
        ) from exc
    session = requests.Session()
    session.cookies.update(pending.get("cookies") or {})
    token = midrag_call(
        session,
        "Account/Token",
        {"spId": values["spId"], "verificationCode": code, "uuid": uuid},
    )
    if not token or not isinstance(token, str):
        raise RenewError("Account/Token : Midrag n'a pas renvoyé de token.")
    print(f"::add-mask::{token}")
    put_secret(SECRET_TOKEN, token)
    delete_secret(SECRET_PENDING)
    delete_secret(SECRET_CODE)
    publish_expiry(token)
    print("Token renouvelé.")


def main(argv: list[str]) -> int:
    steps = {"send": step_send, "verify": step_verify}
    if len(argv) != 2 or argv[1] not in steps:
        print("Usage : renew.py send|verify", file=sys.stderr)
        return 2
    try:
        steps[argv[1]]()
    except RenewError as exc:
        print(f"[ÉCHEC] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
