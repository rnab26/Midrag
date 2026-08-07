#!/usr/bin/env python3
"""Maintient automatiquement le statut de disponibilité sur Midrag.

Lu par un workflow GitHub Actions planifié toutes les ~15 minutes. À chaque
exécution: si l'heure courante tombe dans une plage définie dans
config.yaml, le bot se connecte à Midrag et repointe le mode demandé
("disponible maintenant" ou "disponible aujourd'hui") pour empêcher
l'expiration automatique du statut.

Identifiants lus depuis les variables d'environnement MIDRAG_EMAIL et
MIDRAG_PASSWORD (jamais en dur dans le code, jamais commités).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

# ---------------------------------------------------------------------------
# TODO: à remplir une fois la capture réseau faite (voir README).
# ---------------------------------------------------------------------------
LOGIN_URL = "TODO_URL_DE_LOGIN"
LOGIN_METHOD = "POST"
# Noms des champs attendus par l'API de login (à ajuster selon la capture).
LOGIN_PAYLOAD_TEMPLATE = {
    "email": "{email}",
    "password": "{password}",
}
# Où trouver le token dans la réponse JSON du login, ex: "token" ou
# "data.accessToken". Laisser tel quel si l'auth passe par cookie de session
# (dans ce cas, utiliser une requests.Session() suffit, voir plus bas).
TOKEN_JSON_PATH: str | None = None  # ex: "token"

AVAILABILITY_URL = "TODO_URL_DE_DISPONIBILITE"
AVAILABILITY_METHOD = "POST"
# Valeurs exactes attendues par l'API pour chaque mode (à ajuster).
MODE_PAYLOADS = {
    "now": {"status": "TODO_VALEUR_DISPONIBLE_MAINTENANT"},
    "today": {"status": "TODO_VALEUR_DISPONIBLE_AUJOURDHUI"},
}
# ---------------------------------------------------------------------------


@dataclass
class Window:
    days: set[str]
    start: str
    end: str
    mode: str

    def is_active(self, now: datetime) -> bool:
        day_code = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
        if day_code not in self.days:
            return False
        current = now.strftime("%H:%M")
        return self.start <= current <= self.end


def load_config() -> tuple[ZoneInfo, int, list[Window]]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    tz = ZoneInfo(raw["timezone"])
    sector_id = raw["sector_id"]
    windows = [
        Window(days=set(w["days"]), start=w["start"], end=w["end"], mode=w["mode"])
        for w in raw["schedule"]
    ]
    return tz, sector_id, windows


def login(session: requests.Session, email: str, password: str) -> str | None:
    payload = {
        k: v.format(email=email, password=password) if isinstance(v, str) else v
        for k, v in LOGIN_PAYLOAD_TEMPLATE.items()
    }
    resp = session.request(LOGIN_METHOD, LOGIN_URL, json=payload, timeout=30)
    resp.raise_for_status()

    if TOKEN_JSON_PATH is None:
        # Auth par cookie de session: requests.Session conserve les cookies
        # automatiquement entre les appels, rien à faire de plus.
        return None

    data = resp.json()
    token = data
    for part in TOKEN_JSON_PATH.split("."):
        token = token[part]
    return token


def set_availability(session: requests.Session, sector_id: int, mode: str, token: str | None) -> None:
    payload = {**MODE_PAYLOADS[mode], "sectorId": sector_id}
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = session.request(AVAILABILITY_METHOD, AVAILABILITY_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()


def main() -> int:
    email = os.environ.get("MIDRAG_EMAIL")
    password = os.environ.get("MIDRAG_PASSWORD")
    if not email or not password:
        print("MIDRAG_EMAIL / MIDRAG_PASSWORD manquants dans l'environnement.", file=sys.stderr)
        return 1

    tz, sector_id, windows = load_config()
    now = datetime.now(tz)

    active = next((w for w in windows if w.is_active(now)), None)
    if active is None:
        print(f"[{now.isoformat()}] Hors plage horaire configurée, rien à faire.")
        return 0

    session = requests.Session()
    token = login(session, email, password)
    set_availability(session, sector_id, active.mode, token)
    print(f"[{now.isoformat()}] Statut '{active.mode}' repointé avec succès (secteur {sector_id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
