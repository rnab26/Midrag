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

Quand le bot ne peut plus faire son travail (token expiré ou rejeté, API
Midrag en panne), il ne fait PAS échouer le job : à raison d'une exécution
tous les quarts d'heure, cela envoyait une notification GitHub par run pour
un problème unique. Il ouvre à la place une issue de suivi, refermée
automatiquement dès qu'une exécution repasse au vert.
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
    date: str  # YYYY-MM-DD
    start: str
    end: str
    mode: str

    def is_active(self, now: datetime) -> bool:
        if now.strftime("%Y-%m-%d") != self.date:
            return False
        current = now.strftime("%H:%M")
        # "00:00" as an end time means "end of this day" (midnight), not
        # "the very start of the day" — normalize so it sorts last.
        end = "24:00" if self.end == "00:00" else self.end
        return self.start <= current <= end

    def duration_minutes(self) -> int:
        def to_minutes(t: str) -> int:
            h, m = t.split(":")
            return int(h) * 60 + int(m)

        end = 24 * 60 if self.end == "00:00" else to_minutes(self.end)
        return end - to_minutes(self.start)


def load_config() -> tuple[ZoneInfo, int, list[Window]]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    tz = ZoneInfo(raw["timezone"])
    sector_id = raw["sector_id"]
    windows = [
        Window(date=w["date"], start=w["start"], end=w["end"], mode=w["mode"])
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


# ---------------------------------------------------------------------------
# Signalement des pannes
#
# Le workflow tourne toutes les ~15 minutes. Faire échouer le job à chaque
# passage envoyait une notification GitHub par run (≈ 96 mails/jour) pour un
# seul et même problème. À la place, on ouvre UNE issue de suivi, qui se
# referme d'elle-même dès qu'une exécution repasse au vert. Le job, lui, reste
# vert : rien de ce qu'il fait ne peut corriger un token expiré.
# ---------------------------------------------------------------------------

ISSUE_TITLE = "⚠️ Bot Midrag : la disponibilité n'est plus maintenue"

GITHUB_API = "https://api.github.com"


def _github_session() -> tuple[requests.Session, str] | None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return session, repo


def _find_open_issue(session: requests.Session, repo: str) -> dict | None:
    resp = session.get(
        f"{GITHUB_API}/repos/{repo}/issues",
        params={"state": "open", "per_page": 100},
        timeout=30,
    )
    resp.raise_for_status()
    for issue in resp.json():
        if issue.get("title") == ISSUE_TITLE and "pull_request" not in issue:
            return issue
    return None


def report_failure(reason: str, detail: str = "") -> None:
    """Ouvre l'issue de suivi si elle n'existe pas déjà.

    Volontairement silencieux si une issue est déjà ouverte : un commentaire
    par run rejouerait exactement le flot de notifications qu'on cherche à
    supprimer."""
    print(f"[PANNE] {reason}", file=sys.stderr)
    if detail:
        print(detail, file=sys.stderr)

    ctx = _github_session()
    if ctx is None:
        print(
            "GITHUB_TOKEN/GITHUB_REPOSITORY absents : pas d'issue de suivi ouverte.",
            file=sys.stderr,
        )
        return
    session, repo = ctx
    try:
        if _find_open_issue(session, repo) is not None:
            print("Issue de suivi déjà ouverte, rien à signaler de plus.")
            return
        body = (
            f"{reason}\n\n"
            "Tant que ce problème dure, le bot laisse le statut Midrag expirer tout seul.\n\n"
            "**Quoi faire :** ouvrir la page de planning, coller un token Midrag frais "
            "(procédure de capture dans le README) et enregistrer.\n\n"
            "Cette issue se fermera automatiquement dès qu'une exécution du bot repassera au vert.\n"
        )
        if detail:
            body += f"\n<details><summary>Détail technique</summary>\n\n```\n{detail}\n```\n</details>\n"
        resp = session.post(
            f"{GITHUB_API}/repos/{repo}/issues",
            json={"title": ISSUE_TITLE, "body": body},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"Issue de suivi ouverte : {resp.json()['html_url']}")
    except Exception as exc:  # noqa: BLE001 - best effort, ne doit jamais casser le run
        print(f"Impossible d'ouvrir l'issue de suivi : {exc}", file=sys.stderr)


def clear_failure() -> None:
    """Referme l'issue de suivi après une exécution réussie."""
    ctx = _github_session()
    if ctx is None:
        return
    session, repo = ctx
    try:
        issue = _find_open_issue(session, repo)
        if issue is None:
            return
        number = issue["number"]
        session.post(
            f"{GITHUB_API}/repos/{repo}/issues/{number}/comments",
            json={"body": "✅ Le bot a de nouveau repointé la disponibilité avec succès."},
            timeout=30,
        )
        resp = session.patch(
            f"{GITHUB_API}/repos/{repo}/issues/{number}",
            json={"state": "closed", "state_reason": "completed"},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"Issue de suivi #{number} refermée (retour à la normale).")
    except Exception as exc:  # noqa: BLE001
        print(f"Impossible de refermer l'issue de suivi : {exc}", file=sys.stderr)


def main() -> int:
    token = os.environ.get("MIDRAG_TOKEN")
    if not token:
        report_failure("Le secret `MIDRAG_TOKEN` est absent de l'environnement du workflow.")
        return 0

    tz, sector_id, windows = load_config()
    now = datetime.now(tz)

    expiry = token_expiry(token)
    if expiry is not None:
        remaining = expiry - datetime.now(timezone.utc)
        if remaining.total_seconds() <= 0:
            report_failure(
                f"Le token Midrag a expiré le {expiry.astimezone(tz):%d/%m/%Y à %H:%M} "
                "(heure d'Israël). Il faut se reconnecter à Midrag et en fournir un nouveau."
            )
            return 0
        if remaining.days <= 5:
            print(f"[ATTENTION] MIDRAG_TOKEN expire dans {remaining.days} jour(s) ({expiry.isoformat()}).")

    # Plusieurs créneaux peuvent se chevaucher pour la même date (ex: toute
    # la journée en "now", avec une sous-plage plus précise en "today") —
    # on privilégie le créneau le plus spécifique (le plus court) plutôt
    # que le premier de la liste.
    candidates = [w for w in windows if w.is_active(now)]
    active = min(candidates, key=lambda w: w.duration_minutes()) if candidates else None
    if active is None:
        print(f"[{now.isoformat()}] Hors plage horaire configurée, rien à faire.")
        return 0

    level = MODE_TO_LEVEL[active.mode]
    try:
        result = set_slider_status(token, sector_id, level)
        current_level = result["data"]["currentLevel"]
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (401, 403):
            report_failure(
                "Midrag a rejeté le token (authentification refusée). Il a probablement été "
                "invalidé par une reconnexion depuis un autre appareil : il faut en fournir un nouveau.",
                detail=str(exc),
            )
        else:
            report_failure(
                f"L'appel à Midrag a échoué (HTTP {status}). Si le site est simplement en panne, "
                "cette issue se refermera toute seule au prochain passage réussi.",
                detail=str(exc),
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - réseau, JSON inattendu, refus métier...
        report_failure(
            "L'appel à Midrag a échoué pour une raison inattendue.",
            detail=f"{type(exc).__name__}: {exc}",
        )
        return 0

    print(
        f"[{now.isoformat()}] Mode '{active.mode}' (niveau {level}) repointé "
        f"pour le secteur {sector_id}. Niveau confirmé par Midrag: {current_level}."
    )
    clear_failure()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
