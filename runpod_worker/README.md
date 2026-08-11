# Worker RunPod (FaceFusion)

C'est le composant qui fait le vrai calcul GPU. L'app principale (dossier `app/`) lui
envoie du travail via l'API RunPod ; ce dossier contient tout ce qu'il faut pour
déployer ce worker sur RunPod.

## 1. Créer un compte RunPod

https://www.runpod.io — ajoute un moyen de paiement (facturation à l'usage, pas
d'abonnement).

## 2. Construire et publier l'image Docker

Il faut un registre accessible par RunPod (Docker Hub, GHCR...) :

```bash
cd runpod_worker
docker build -t TON_USER_DOCKERHUB/faceswap-worker:latest .
docker push TON_USER_DOCKERHUB/faceswap-worker:latest
```

⚠️ L'image télécharge FaceFusion + ses modèles pendant le build : ça peut prendre
un bon moment et l'image finale est volumineuse (plusieurs Go). C'est normal.

## 3. Créer un stockage S3-compatible pour récupérer les résultats

Le worker doit uploader la vidéo/photo générée quelque part pour que l'app
principale puisse la télécharger. Le plus simple et gratuit : **Cloudflare R2**
(10 Go gratuits). Crée un bucket, une clé API, note :
- endpoint URL
- access key id
- secret access key
- nom du bucket

## 4. Créer l'endpoint serverless sur RunPod

Dashboard RunPod → Serverless → New Endpoint :
- Image : `TON_USER_DOCKERHUB/faceswap-worker:latest`
- GPU : commence par un GPU "milieu de gamme" (ex: RTX 4090) pour un bon rapport
  qualité/prix, tu pourras ajuster ensuite
- Container Disk : au moins 20 Go (modèles FaceFusion)
- Variables d'environnement (pour l'upload du résultat, lues par
  `runpod.serverless.utils.rp_upload`) :
  - `BUCKET_ENDPOINT_URL`
  - `BUCKET_ACCESS_KEY_ID`
  - `BUCKET_SECRET_ACCESS_KEY`

Une fois créé, RunPod te donne un **Endpoint ID** et tu as ta **clé API** dans
Settings → API Keys.

## 5. Connecter l'app principale

Dans le `.env` de l'app (racine du repo) :

```
SWAP_BACKEND=runpod
RUNPOD_API_KEY=ta_cle_api
RUNPOD_ENDPOINT_ID=ton_endpoint_id
PUBLIC_BASE_URL=https://ton-url-publique.example.com
```

`PUBLIC_BASE_URL` doit être une URL par laquelle RunPod peut télécharger tes
fichiers uploadés (`/media/uploads/...`). En local, utilise un tunnel
(Cloudflare Tunnel, ngrok) le temps des tests ; en prod, c'est le domaine de ton
serveur.

## 6. Premier vrai test

Ce worker a été écrit à partir de la documentation de FaceFusion et de RunPod,
mais **n'a pas pu être testé ici faute de GPU**. Avant de considérer que ça
marche :

1. Lance un swap depuis l'app avec `SWAP_BACKEND=runpod`.
2. Si le job échoue, regarde les logs RunPod (Dashboard → ton endpoint → Requests).
   Le message d'erreur inclut le `stdout`/`stderr` de FaceFusion.
3. La cause la plus probable : les noms des options de la commande FaceFusion
   ont changé entre versions. Corrige `handler.py` (`_run_facefusion`) en te
   basant sur `python facefusion.py headless-run --help` exécuté dans le
   conteneur.
