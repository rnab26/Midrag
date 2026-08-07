# Midrag – bot de disponibilité automatique

Petit robot qui repointe automatiquement ton statut de disponibilité sur
Midrag (bizn.midrag.co.il) selon un planning que tu définis, pour ne plus
avoir à cliquer toutes les heures.

## Comment ça marche

- `midrag_bot/config.yaml` : tu y définis des plages par **date précise**
  (pas de récurrence hebdomadaire — chaque jour se règle individuellement)
  avec heure de début/fin et le mode voulu (`now` = disponible maintenant,
  `today` = disponible aujourd'hui, `tomorrow` = disponible demain,
  `unavailable` = pas disponible).
- `midrag_bot/bot.py` : à chaque exécution, regarde l'heure actuelle, la
  compare à `config.yaml`, et si on est dans une plage active, appelle
  l'API Midrag (`SetSliderStatus`) pour repointer le niveau correspondant
  — ce qui remet à zéro le décompte avant expiration côté Midrag.
- `.github/workflows/midrag-availability.yml` : fait tourner `bot.py`
  automatiquement toutes les 15 minutes via GitHub Actions — pas besoin de
  garder un téléphone ou un ordinateur allumé.

### Pourquoi pas une connexion 100% automatique ?

Midrag exige un code reçu par SMS à chaque connexion (téléphone + n°
d'entreprise + code SMS → token). Ça ne peut pas être automatisé sans
accès à tes SMS. À la place, le bot utilise directement le **token** que
Midrag délivre après une connexion manuelle — ce token reste valable
plusieurs semaines. Il te suffit donc de refaire la procédure ci-dessous
environ **une fois par mois**, au lieu de pointer toutes les heures.

## Mise en place

### 1. Récupérer ton token Midrag (à refaire ~1x/mois)

1. Va sur `bizn.midrag.co.il` et connecte-toi normalement (téléphone + n°
   d'entreprise + code SMS).
2. Une fois sur la page de disponibilité, ouvre les outils développeur du
   navigateur (`F12`), onglet **Network**, filtre **Fetch/XHR**.
3. Cherche dans l'historique la requête **`Token`** (elle a eu lieu pendant
   la connexion — si tu ne la vois pas, déconnecte-toi et refais la
   procédure de connexion avec Network déjà ouvert).
4. Onglet **Response** de cette requête → copie la valeur de `data.token`
   (une longue chaîne commençant par `eyJ...`). C'est ton nouveau token.

### 2. Secret GitHub

- Sur GitHub (web ou appli mobile) : `Settings` → `Secrets and variables`
  → `Actions` → `New repository secret`.
- Nom : `MIDRAG_TOKEN`. Valeur : le token copié à l'étape précédente.
- Quand tu rafraîchis le token (~1x/mois, ou si le bot t'envoie un mail
  d'échec GitHub Actions signalant une expiration), remplace juste la
  valeur de ce même secret.

### 3. Planning — page de configuration

Une page dédiée (`docs/index.html`, hébergée via GitHub Pages) permet de
régler le planning — jour par jour, par vraies dates (aujourd'hui,
demain, etc., calées sur le fuseau Asia/Jerusalem) — et la cadence de
réactualisation, sans toucher au YAML à la main :

1. Active GitHub Pages : `Settings` → `Pages` → Source = "Deploy from a
   branch" → branche `claude/midrag-availability-automation-fn3mav` →
   dossier `/docs` → Save. L'URL de la page apparaît en haut de cet écran
   après quelques instants (souvent `https://<owner>.github.io/Midrag/`).
2. Crée un jeton d'accès GitHub scopé à ce seul repo : `Settings` (de ton
   compte) → `Developer settings` → `Personal access tokens` →
   `Fine-grained tokens` → `Generate new token`. Repository access :
   uniquement `Midrag`. Permissions : `Contents: Read and write` (+
   `Actions: Read and write` si tu veux le bouton "Lancer maintenant").
3. Ouvre la page GitHub Pages sur ton téléphone, colle ce jeton (il reste
   stocké uniquement dans ton navigateur), et règle ton planning +
   cadence directement depuis le calendrier. "Enregistrer" pousse les
   changements sur GitHub à ta place.

Cette page réécrit entièrement `config.yaml` et la ligne de cadence du
workflow à chaque sauvegarde — évite de les éditer à la main en dehors de
la page si tu veux garder tes changements.

### 4. C'est tout

Le workflow tourne ensuite tout seul toutes les 15 minutes. Onglet
`Actions` du repo pour voir l'historique des exécutions. Si une exécution
échoue (token expiré, etc.), GitHub t'envoie normalement un email
d'alerte automatique.

## ⚠️ Point d'attention

Automatiser des actions sur une plateforme tierce peut être contraire à
ses conditions d'utilisation (beaucoup de plateformes de mise en relation
interdisent les bots pour éviter de fausser l'attribution des missions).
C'est ton compte et ta décision, mais vérifie les CGU de Midrag et reste
conscient du risque (suspension de compte) avant d'activer ça en continu.
