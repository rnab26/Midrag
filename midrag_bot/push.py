"""Notifications push (Web Push) vers le téléphone.

L'abonnement du téléphone (secret WEBPUSH_SUBSCRIPTION) et la clé privée VAPID
(secret VAPID_PRIVATE_KEY) sont posés par la page de configuration quand on
touche « Activer les notifications » : rien à copier à la main. Tout est
best effort : une notification qui échoue ne doit jamais casser un run, et
l'issue GitHub reste le filet de sécurité.
"""
from __future__ import annotations

import json
import os
import sys

CONFIG_PAGE = "https://rnab26.github.io/Midrag/"

# Le service push veut un contact pour joindre l'émetteur en cas de souci :
# mailto: ou URL https sans chemin (on n'y met pas d'e-mail personnel).
VAPID_SUBJECT = "https://rnab26.github.io"

# Si le téléphone est éteint ou hors ligne, le service push garde le message
# ce temps-là avant de l'abandonner.
TTL_SECONDS = 12 * 3600


def send_push(title: str, body: str, tag: str, url: str = CONFIG_PAGE) -> bool:
    """Envoie une notification. `tag` identique = la nouvelle remplace
    l'ancienne sur le téléphone (pas d'empilement si un rappel part deux fois)."""
    raw_subscription = os.environ.get("WEBPUSH_SUBSCRIPTION")
    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    if not raw_subscription or not private_key:
        print("[PUSH] Notifications non activées (secrets absents) : rien envoyé.")
        return False
    try:
        from py_vapid import Vapid
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info=json.loads(raw_subscription),
                data=json.dumps({"title": title, "body": body, "tag": tag, "url": url}),
                vapid_private_key=Vapid.from_raw(private_key.strip().encode()),
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=TTL_SECONDS,
                timeout=20,
            )
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (404, 410):
                print(
                    "[PUSH] Abonnement expiré ou supprimé : réactive les notifications "
                    "depuis la page de configuration.",
                    file=sys.stderr,
                )
            else:
                print(f"[PUSH] Envoi refusé (HTTP {status}).", file=sys.stderr)
            return False
    except Exception as exc:  # noqa: BLE001 - jamais de secret dans les logs
        print(f"[PUSH] Envoi impossible ({type(exc).__name__}).", file=sys.stderr)
        return False
    print(f"[PUSH] Notification envoyée : {title}")
    return True
