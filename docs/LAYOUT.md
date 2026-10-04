# Layout du dépôt

Organisation voulue (by Pixam) :

- **Racine légère** : seulement les entrées (`desktop.py`, `app.py`, `start.*`), meta (`README`, `LICENSE`, `version.json`, `requirements.txt`).
- **`desk/`** : tout le code Python métier.
- **`static/` + `assets/`** : UI et branding.
- **`scripts/` + `packaging/`** : build Windows et updates LAN.
- **`community/`** : outils Discord / communauté (hors app).
- **`docs/`** : documentation.

Ne pas déplacer `desktop.py` / `app.py` / `start.*` sans mettre à jour PyInstaller et les raccourcis.
