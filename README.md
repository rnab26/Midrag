# FaceSwap Perso

Petite appli web perso de face swap (photo + vidéo), pensée comme alternative à
faceswapfree.io : pas d'abonnement, tes visages/vidéos sont sauvegardés pour être
réutilisés, historique de tous tes swaps, et **support du multi-visages** (échanger
plusieurs visages différents dans une même vidéo/photo, chose que le site original
ne fait pas).

Le moteur de swap est [FaceFusion](https://github.com/facefusion/facefusion), un
projet open source — voir `runpod_worker/` pour le déploiement du calcul GPU.

## Architecture

```
app/            -> l'appli web (FastAPI) : comptes, bibliothèque de visages/médias,
                    file d'attente de jobs, historique
runpod_worker/  -> conteneur Docker déployé sur RunPod, qui fait tourner FaceFusion
                    sur GPU loué à l'usage (pas de GPU perso nécessaire)
data/           -> fichiers uploadés/générés + base SQLite (créé au premier lancement)
```

`app/` ne fait jamais le calcul lui-même : il envoie le travail au backend GPU
configuré (`SWAP_BACKEND`) et récupère le résultat. Deux backends :

- **`mock`** (par défaut) : ne fait aucun vrai swap, copie juste le fichier cible
  (avec un filigrane "MOCK SWAP" sur les images). Sert à tester toute l'appli
  (comptes, upload, historique, téléchargement) sans dépenser un centime ni avoir
  de compte RunPod.
- **`runpod`** : le vrai moteur, voir `runpod_worker/README.md` pour le déployer.

## Lancer en local (mode mock, aucun compte externe requis)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# édite SESSION_SECRET dans .env (génère avec la commande indiquée dans le fichier)

uvicorn app.main:app --reload
```

Ouvre http://localhost:8000, crée un compte, uploade un visage source et un
média cible, lance un swap. En mode mock c'est instantané.

## Passer au vrai moteur (RunPod)

Une fois que tu veux du vrai résultat (et pas juste tester la plomberie), suis
`runpod_worker/README.md` pour déployer FaceFusion sur RunPod, puis dans `.env` :

```
SWAP_BACKEND=runpod
RUNPOD_API_KEY=...
RUNPOD_ENDPOINT_ID=...
PUBLIC_BASE_URL=...
```

## Ce qui a été amélioré par rapport à faceswapfree.io/pro

- **Multi-visages** : chaque visage détecté dans la cible peut recevoir un
  visage source différent (le site original ne semble pas le proposer).
- **Bibliothèque réutilisable** : les visages sources et médias cibles uploadés
  sont sauvegardés, pas besoin de re-uploader à chaque swap.
- **Historique** : tous les jobs et leurs résultats restent consultables.
- **Coût** : paiement à l'usage du calcul GPU (RunPod) au lieu d'un forfait de
  crédits, généralement bien moins cher pour un usage occasionnel perso.
- **Qualité visage/bouche** : les modules "face enhancer" et "lip syncer" de
  FaceFusion sont exposés et activables, avec la possibilité d'ajuster leurs
  réglages directement dans `runpod_worker/handler.py` si besoin.

## Statut / limites connues

- Le worker RunPod (`runpod_worker/`) a été écrit d'après la documentation de
  FaceFusion et de RunPod mais **n'a pas pu être testé sur un vrai GPU** dans cet
  environnement de développement (aucun GPU disponible ici). Le pipeline complet
  de l'appli (comptes, upload, jobs, historique, téléchargement) a lui été testé
  de bout en bout en mode mock et fonctionne. Voir la section "Premier vrai test"
  de `runpod_worker/README.md` avant de considérer le moteur RunPod comme fiable.
- Usage personnel : l'auth est volontairement simple (un ou quelques comptes),
  pas pensée pour un usage public à grande échelle.
- Le contenu généré par ce type d'outil (échange de visage) peut avoir un usage
  sensible : n'utilise que sur des photos/vidéos de personnes consentantes.
