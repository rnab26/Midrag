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
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

SET_STATUS_URL = "https://biz-api.midrag.co.il/SliderAvailability/SetSliderStatus"

# Combien de jours avant l'expiration du token on prévient, si config.yaml ne
# le précise pas (réglable depuis la page de configuration).
DEFAULT_ALERT_DAYS = 3

# Le planning est daté jour par jour: quand la dernière date est dépassée, le
# bot continue de tourner mais ne repointe plus rien. On prévient ce nombre de
# jours avant que le planning n'arrive à sa fin (réglable depuis la page).
DEFAULT_PLANNING_ALERT_DAYS = 2

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


@dataclass
class Config:
    tz: ZoneInfo
    sector_id: int
    token_alert_days: int
    planning_alert_days: int
    windows: list[Window]


def load_config() -> Config:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(
        tz=ZoneInfo(raw["timezone"]),
        sector_id=raw["sector_id"],
        token_alert_days=int(raw.get("token_alert_days", DEFAULT_ALERT_DAYS)),
        planning_alert_days=int(
            raw.get("planning_alert_days", DEFAULT_PLANNING_ALERT_DAYS)
        ),
        windows=[
            Window(date=w["date"], start=w["start"], end=w["end"], mode=w["mode"])
            for w in raw["schedule"] or []
        ],
    )


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

# Avertissement AVANT la panne: le token a une date d'expiration connue, donc
# rien n'oblige à attendre que la disponibilité décroche pour prévenir. Issue
# séparée de celle de panne: ici le bot travaille encore normalement.
EXPIRY_ISSUE_TITLE = "🔑 Bot Midrag : le token Midrag expire bientôt"

# Fin de planning: ce n'est pas une panne (le job reste vert), mais le
# résultat est le même côté Midrag — d'où une issue dédiée, pour ne pas
# mélanger « le bot est cassé » et « tu n'as plus rien programmé ».
PLANNING_ISSUE_TITLE = "📅 Bot Midrag : le planning arrive à sa fin"

CONFIG_PAGE = "https://rnab26.github.io/Midrag/"

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


def _find_open_issue(
    session: requests.Session, repo: str, title: str = ISSUE_TITLE
) -> dict | None:
    resp = session.get(
        f"{GITHUB_API}/repos/{repo}/issues",
        params={"state": "open", "per_page": 100},
        timeout=30,
    )
    resp.raise_for_status()
    for issue in resp.json():
        if issue.get("title") == title and "pull_request" not in issue:
            return issue
    return None


def _open_issue_once(title: str, body: str, kind: str) -> None:
    """Ouvre l'issue si aucune du même titre n'est déjà ouverte.

    Volontairement silencieux quand elle existe déjà : un commentaire par run
    rejouerait exactement le flot de notifications qu'on cherche à supprimer."""
    ctx = _github_session()
    if ctx is None:
        print(
            f"GITHUB_TOKEN/GITHUB_REPOSITORY absents : pas d'{kind} ouverte.",
            file=sys.stderr,
        )
        return
    session, repo = ctx
    try:
        if _find_open_issue(session, repo, title) is not None:
            print(f"{kind.capitalize()} déjà ouverte, rien à signaler de plus.")
            return
        resp = session.post(
            f"{GITHUB_API}/repos/{repo}/issues",
            json={"title": title, "body": body},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"{kind.capitalize()} ouverte : {resp.json()['html_url']}")
    except Exception as exc:  # noqa: BLE001 - best effort, ne doit jamais casser le run
        print(f"Impossible d'ouvrir l'{kind} : {exc}", file=sys.stderr)


def _close_issue(title: str, comment: str, kind: str) -> None:
    """Referme l'issue du titre donné, avec un mot expliquant pourquoi."""
    ctx = _github_session()
    if ctx is None:
        return
    session, repo = ctx
    try:
        issue = _find_open_issue(session, repo, title)
        if issue is None:
            return
        number = issue["number"]
        session.post(
            f"{GITHUB_API}/repos/{repo}/issues/{number}/comments",
            json={"body": comment},
            timeout=30,
        )
        resp = session.patch(
            f"{GITHUB_API}/repos/{repo}/issues/{number}",
            json={"state": "closed", "state_reason": "completed"},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"{kind.capitalize()} #{number} refermée.")
    except Exception as exc:  # noqa: BLE001
        print(f"Impossible de refermer l'{kind} : {exc}", file=sys.stderr)


def report_failure(reason: str, detail: str = "") -> None:
    """Signale une panne qui empêche le bot de travailler."""
    print(f"[PANNE] {reason}", file=sys.stderr)
    if detail:
        print(detail, file=sys.stderr)

    body = (
        f"{reason}\n\n"
        "Tant que ce problème dure, le bot laisse le statut Midrag expirer tout seul.\n\n"
        "**Quoi faire :** ouvrir la page de planning, coller un token Midrag frais "
        f"(voir {CONFIG_PAGE}) et enregistrer.\n\n"
        "Cette issue se fermera automatiquement dès qu'une exécution du bot repassera au vert.\n"
    )
    if detail:
        body += f"\n<details><summary>Détail technique</summary>\n\n```\n{detail}\n```\n</details>\n"
    _open_issue_once(ISSUE_TITLE, body, "issue de suivi")


def clear_failure() -> None:
    """Referme l'issue de suivi après une exécution réussie."""
    _close_issue(
        ISSUE_TITLE,
        "✅ Le bot a de nouveau repointé la disponibilité avec succès.",
        "issue de suivi",
    )


def warn_expiry(expiry: datetime, tz: ZoneInfo, alert_days: int) -> None:
    """Prévient que le token approche de son expiration."""
    remaining = expiry - datetime.now(timezone.utc)
    hours = remaining.total_seconds() / 3600
    delay = f"{hours:.0f} h" if hours < 48 else f"{int(hours // 24)} jours"
    print(f"[ATTENTION] MIDRAG_TOKEN expire dans {delay} ({expiry.isoformat()}).")

    body = (
        f"Le token Midrag expire le **{expiry.astimezone(tz):%d/%m/%Y à %H:%M}** "
        f"(heure d'Israël), soit dans {delay}.\n\n"
        "La disponibilité est encore maintenue normalement jusque-là, mais elle "
        "décrochera à cette date si le token n'est pas renouvelé d'ici là.\n\n"
        f"**Quoi faire :** ouvrir la page de planning ({CONFIG_PAGE}), coller un token "
        "Midrag frais et enregistrer.\n\n"
        "Cette issue se fermera automatiquement dès que le token sera renouvelé. "
        f"Le délai d'avertissement ({alert_days} jours) se règle depuis la page de "
        "configuration.\n"
    )
    _open_issue_once(EXPIRY_ISSUE_TITLE, body, "issue d'avertissement")


def clear_expiry_warning(comment: str) -> None:
    """Referme l'issue d'avertissement (token renouvelé, ou panne déjà
    signalée par l'issue dédiée)."""
    _close_issue(EXPIRY_ISSUE_TITLE, comment, "issue d'avertissement")


def warn_planning(last_date: str | None, today: date, alert_days: int, tz: ZoneInfo) -> None:
    """Prévient que le planning est fini, ou sur le point de l'être.

    Un planning épuisé n'est pas une panne: le bot tourne, les exécutions
    restent vertes, il n'y a simplement plus rien à repointer. Sans ce
    signalement, la disponibilité s'arrête sans que personne ne le voie."""
    if last_date is None:
        headline = (
            "**Plus aucun créneau n'est configuré à partir d'aujourd'hui.** Le bot "
            "tourne toujours, mais il ne repointe plus rien : ta disponibilité "
            "Midrag n'est plus maintenue."
        )
        print("[PLANNING] Aucun créneau configuré à partir d'aujourd'hui.")
    else:
        remaining_days = (date.fromisoformat(last_date) - today).days
        quand = "aujourd'hui" if remaining_days == 0 else (
            "demain" if remaining_days == 1 else f"dans {remaining_days} jours"
        )
        headline = (
            f"**Ton planning s'arrête le {date.fromisoformat(last_date):%d/%m/%Y}**, "
            f"soit {quand}. Passé cette date, le bot continuera de tourner sans rien "
            "repointer : ta disponibilité Midrag ne sera plus maintenue."
        )
        print(f"[PLANNING] Dernier créneau configuré le {last_date}.")

    body = (
        f"{headline}\n\n"
        f"**Quoi faire :** ouvrir la page de planning ({CONFIG_PAGE}) et remplir les "
        "jours qui viennent.\n\n"
        "Un jour réglé sur « pas disponible » compte comme configuré : cette alerte ne "
        "se déclenche que quand il n'y a plus rien du tout.\n\n"
        "Cette issue se fermera automatiquement dès que le planning sera rempli. "
        f"Le délai d'avertissement ({alert_days} jours) se règle depuis la page de "
        "configuration.\n"
    )
    _open_issue_once(PLANNING_ISSUE_TITLE, body, "issue de planning")


def clear_planning_warning() -> None:
    """Referme l'issue de planning dès qu'il y a de nouveau des créneaux."""
    _close_issue(
        PLANNING_ISSUE_TITLE,
        "✅ Le planning est de nouveau rempli pour les jours qui viennent.",
        "issue de planning",
    )


def check_planning(windows: list[Window], now: datetime, alert_days: int, tz: ZoneInfo) -> None:
    """Compare la dernière date configurée à l'horizon d'alerte."""
    today = now.date()
    today_str = today.isoformat()
    future = sorted(w.date for w in windows if w.date >= today_str)
    last_date = future[-1] if future else None
    if last_date is None or date.fromisoformat(last_date) <= today + timedelta(days=alert_days):
        warn_planning(last_date, today, alert_days, tz)
    else:
        clear_planning_warning()


def main() -> int:
    token = os.environ.get("MIDRAG_TOKEN")
    if not token:
        report_failure("Le secret `MIDRAG_TOKEN` est absent de l'environnement du workflow.")
        return 0

    cfg = load_config()
    tz, sector_id, windows = cfg.tz, cfg.sector_id, cfg.windows
    alert_days = cfg.token_alert_days
    now = datetime.now(tz)

    expiry = token_expiry(token)
    if expiry is not None:
        remaining = expiry - datetime.now(timezone.utc)
        if remaining.total_seconds() <= 0:
            report_failure(
                f"Le token Midrag a expiré le {expiry.astimezone(tz):%d/%m/%Y à %H:%M} "
                "(heure d'Israël). Il faut se reconnecter à Midrag et en fournir un nouveau."
            )
            # L'issue de panne dit désormais tout: garder l'avertissement
            # ouvert en plus ferait deux fils pour un seul problème.
            clear_expiry_warning(
                "⛔ Le token a expiré — le suivi continue dans l'issue de panne."
            )
            return 0
        if remaining.total_seconds() <= alert_days * 86400:
            warn_expiry(expiry, tz, alert_days)
        else:
            clear_expiry_warning("✅ Token renouvelé, l'échéance est repoussée.")

    check_planning(windows, now, cfg.planning_alert_days, tz)

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
