# API France Marché – BOAMP

## Structure du dépôt
- `Back-end/` : application Flask historique qui expose une API JSON et des templates serveur.
- `Front-end/` : gabarits HTML d'origine servis par Flask (optionnel désormais).
- `docs/` : SPA statique (HTML/CSS/JS) consommant directement l'API publique Opendatasoft. C'est ce dossier qu'il faut publier sur GitHub Pages.
- `.venv/`, scripts `Launch_API.*` : helpers locaux pour démarrer la version Flask.

## Lancer l'API Flask (optionnel)
```bash
python -m venv .venv
.venv\Scripts\activate  # PowerShell
pip install -r Back-end/requirements.txt
python Back-end/app.py
```
L'interface est alors disponible sur http://localhost:8000/ (accueil) et http://localhost:8000/search (version SSR).

Variables d'environnement principales si vous utilisez Flask :
- `ODS_BASE` (défaut : https://boamp-datadila.opendatasoft.com)
- `DATASET_ID` (défaut : boamp)
- `ODS_APIKEY` (facultatif si le portail l'exige)
- Voir `Back-end/app.py` pour les options de cache, SSL, fallback Explore/v1.

## SPA statique (docs/)
Le dossier `docs/` contient :
- `index.html` : interface principale filtrant les avis BOAMP via fetch côté navigateur.
- `cpv.html` : rappel des codes CPV « formation » appliqués par défaut.
- `styles.css`, `app.js` : assets du front.

### Tester en local
Servez le dossier `docs/` avec n'importe quel serveur statique (Python, Node, etc.) pour éviter les blocages liés à `file://` :
```bash
cd docs
python -m http.server 8001
# puis ouvrir http://localhost:8001/index.html
```

### Publier sur GitHub Pages
1. Commitez le dossier `docs/` et poussez votre branche principale (`main`).
2. Sur GitHub : *Settings → Pages → Build and deployment*.
3. Source : `Deploy from a branch`. Branche : `main`. Dossier : `/docs`.
4. Sauvegardez ; l'URL générée est disponible après quelques minutes. La SPA interroge directement l'API ODS, aucun back-end n'est requis.

### Personnalisation
Modifiez `ODS_BASE`, `DATASET_ID` ou ajoutez une clé dans `app.js` si vous utilisez un portail Opendatasoft privé. Prévoir les entêtes CORS sur le portail cible.

## Notes diverses
- Les anciens dossiers `Front-end/` et `Back-end/` sont conservés pour référence ou exécution locale. GitHub Pages n'en a pas besoin.
- Les filtres « Formations » activent automatiquement la liste blanche de CPV et la catégorie de services 24 dans la SPA.
- Aucune dépendance externe n'est embarquée côté navigateur ; tout est en HTML/CSS/JS vanilla.
