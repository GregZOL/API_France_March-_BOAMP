API France Marché — Minimal Front (HTML/CSS) + Back (Python)

What’s inside
- Front-end/: Server-rendered HTML templates and CSS (no JS)
- Back-end/: Minimal Flask app with Opendatasoft (ODS) logic

Run locally
- Python 3.10+
- Install: `pip install -r Back-end/requirements.txt`
- Start: `python Back-end/app.py`
- Open: http://localhost:8000 (page d'accueil avec un bouton « Lancer l'API »)
- Avancé (filtres): http://localhost:8000/search
 - CPV (liste formation): http://localhost:8000/cpv
 - Par défaut, le filtre « Formations » est appliqué (useTraining=on).

Configuration (optional)
- `ODS_BASE` (default: https://boamp-datadila.opendatasoft.com)
- `DATASET_ID` (default: boamp)
- `ODS_APIKEY` (facultatif si le portail le requiert)
- `PREFER_EXPLORE` (1 par défaut): tente Explore v2.1 d'abord puis retombe en v1 si la clause WHERE est refusée (4xx). Mettre `0` pour tenter d'abord v1.
- `ALLOW_INSECURE_SSL` (0 par défaut): si `1`, désactive la vérification SSL (à éviter; utiliser plutôt certifi qui est installé par défaut)
- `REQUEST_TIMEOUT_SECONDS` (30 par défaut)
- `RESULTS_CACHE_TTL_SECONDS` (60 par défaut): cache mémoire des résultats
- `AUTO_FALLBACK_INSECURE_SSL` (1 par défaut): en cas d'erreur CERTIFICATE_VERIFY_FAILED, retente une fois en mode non vérifié pour éviter un blocage utilisateur. Préférez fournir un CA local plutôt que de laisser ceci activé en production.
- `ODS_APIKEY` (optional if your portal requires a key)

Notes
- The app prefers ODS Explore v2.1 and automatically falls back to Records v1.
- All filters are server-rendered. No front-end JavaScript is required.
- To refresh the cached dataset schema, add `?refreshSchema=1` to the URL.
- SSL: si vous êtes derrière un proxy d’entreprise, placez le certificat racine dans `Back-end/local_ca.pem` (ou définissez `LOCAL_CA_FILE`/`SSL_CERT_FILE`). Les lanceurs le détectent automatiquement.
 - Par défaut, les résultats sont filtrés sur les CPV formation: 80500000, 80510000, 80533100, 80570000, 80000000, 80553000, 79632000, 79952000. Voir `/cpv` pour la liste et les descriptions.

Repository cleanup
- Previous Next.js apps and Windows packaging are now redundant. Once you
  validate this minimal implementation, we can safely delete the old folders:
  `Virtual Factory/` and `VF test/` (and anything under them).
