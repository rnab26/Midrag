#!/usr/bin/env python3
"""Maintient automatiquement le statut de disponibilité sur Midrag.

Lancé par un workflow GitHub Actions planifié toutes les ~15 minutes. À
chaque exécution: si l'heure courante tombe dans une plage définie dans
config.yaml, le bot rejoue l'appel "SetSliderStatus" pour empêcher
l'expiration automatique du niveau demandé (le site remet le compte à zéro
du timer d'expiration à chaque appel réussi).

La connexion (téléphone + numéro d'entreprise + code SMS) ne peut pas être
automatisée car Midrag exige un code reçu par SMS à chaque login. Le bot
utilise donc directement le token JWT obtenu après une connexion manuelle
(voir README pour la procédure de capture/rafraîchissement), stocké dans
la variable d'environnement MIDRAG_TOKEN. Ce token dure plusieurs semaines
avant expiration.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

SET_STATUS_URL = "https://biz-api.midrag.co.il/SliderAvailability/SetSliderStatus"

# Correspondance entre les modes du config.yaml et les niveaux attendus par
# l'API Midrag (confirmé via capture réseau du curseur du site).
MODE_TO_LEVEL = {
    "now": 1,        # פנוי עכשיו - disponible maintenant
    "today": 2,       # פנוי היום - disponible aujourd'hui
    "tomorrow": 3,    # פנוי מחר - disponible demain
    "unavailable": 0,  # לא פנוי - pas disponible
}


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


def token_expiry(token: str) -> datetime | None:
    """Lit le champ 'exp' du JWT sans vérifier la signature (juste pour
    prévenir l'utilisateur avant l'expiration, la vraie vérification est
    faite par Midrag)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    except Exception:
        return None


def set_slider_status(token: str, sector_id: int, level: int) -> dict:
    resp = requests.post(
        SET_STATUS_URL,
        json={"level": level, "sectorId": sector_id},
        cookies={"accessToken": token},
        headers={
            "Origin": "https://bizn.midrag.co.il",
            "Referer": "https://bizn.midrag.co.il/",
        },
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("isBusinessLogicError"):
        raise RuntimeError(f"Midrag a refusé la mise à jour: {body}")
    return body


def main() -> int:
    token = os.environ.get("MIDRAG_TOKEN")
    if not token:
        print("MIDRAG_TOKEN manquant dans l'environnement.", file=sys.stderr)
        return 1

    tz, sector_id, windows = load_config()
    now = datetime.now(tz)

    expiry = token_expiry(token)
    if expiry is not None:
        days_left = (expiry - datetime.now(timezone.utc)).days
        if days_left < 0:
            print(
                f"MIDRAG_TOKEN a expiré le {expiry.isoformat()}. "
                "Refais la procédure de connexion manuelle et mets à jour le secret GitHub.",
                file=sys.stderr,
            )
            return 1
        if days_left <= 5:
            print(f"[ATTENTION] MIDRAG_TOKEN expire dans {days_left} jour(s) ({expiry.isoformat()}).")

    active = next((w for w in windows if w.is_active(now)), None)
    if active is None:
        print(f"[{now.isoformat()}] Hors plage horaire configurée, rien à faire.")
        return 0

    level = MODE_TO_LEVEL[active.mode]
    result = set_slider_status(token, sector_id, level)
    current_level = result["data"]["currentLevel"]
    print(
        f"[{now.isoformat()}] Mode '{active.mode}' (niveau {level}) repointé "
        f"pour le secteur {sector_id}. Niveau confirmé par Midrag: {current_level}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
