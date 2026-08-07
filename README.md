# Midrag – bot de disponibilité automatique

Petit robot qui repointe automatiquement ton statut de disponibilité sur
Midrag (bizn.midrag.co.il) selon un planning que tu définis, pour ne plus
avoir à cliquer toutes les heures.

## Comment ça marche

- `midrag_bot/config.yaml` : tu y définis tes plages horaires (jours, heure
  de début/fin) et le mode voulu pour chacune (`now` = disponible
  maintenant en boucle, `today` = disponible aujourd'hui).
- `midrag_bot/bot.py` : script qui, à chaque exécution, regarde l'heure
  actuelle, la compare à `config.yaml`, et si on est dans une plage active,
  se connecte à Midrag et repointe le statut correspondant.
- `.github/workflows/midrag-availability.yml` : fait tourner `bot.py`
  automatiquement toutes les 15 minutes via GitHub Actions — pas besoin de
  garder un ordinateur allumé.

## État actuel du projet

⚠️ **Pas encore fonctionnel.** `bot.py` contient des `TODO_...` à la place
des vraies URLs d'API Midrag (login + changement de disponibilité). Il faut
d'abord capturer ces informations réseau (voir la conversation avec
Claude / la section ci-dessous), puis les renseigner dans `bot.py`.

## Mise en place (une fois les endpoints connus)

1. **Secrets GitHub** (jamais tes identifiants en clair dans le repo) :
   - Sur GitHub (web ou appli mobile) : `Settings` → `Secrets and
     variables` → `Actions` → `New repository secret`.
   - Créer `MIDRAG_EMAIL` avec ton email/téléphone de connexion.
   - Créer `MIDRAG_PASSWORD` avec ton mot de passe.
2. **Planning** : éditer `midrag_bot/config.yaml` directement depuis
   l'appli GitHub mobile (ouvrir le fichier → crayon pour éditer → commit)
   pour changer tes horaires ou le mode, quand tu veux, depuis ton
   téléphone.
3. Le workflow tourne ensuite tout seul toutes les 15 minutes. Onglet
   `Actions` du repo pour voir l'historique des exécutions et les erreurs
   éventuelles.

## ⚠️ Point d'attention

Automatiser des clics/connexions sur une plateforme tierce peut être
contraire à ses conditions d'utilisation (beaucoup de plateformes de mise
en relation interdisent les bots pour éviter de fausser l'attribution des
missions). C'est ton compte et ta décision, mais vérifie les CGU de Midrag
et reste conscient du risque (suspension de compte) avant d'activer ça en
continu.
