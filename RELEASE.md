# Publication (by Pixam)

Objectif : mettre Desk à disposition **sans exposer tout le code source**.

## Modèle recommandé

| Public | Privé |
|---|---|
| Releases GitHub : zip Windows `PSHomebrewDesk/` | Repo source (privé) ou rien |
| README + logo + captures | `app.py`, `transfer.py`, etc. |

Ne push **pas** le dossier source complet en public si tu veux garder le code fermé.
Publie seulement le build `dist/PSHomebrewDesk/`.

## Build Windows (sur ton PC)

1. Copie le projet sur le PC Windows (SMB, clé USB, etc.)
2. Installe [Python 3](https://www.python.org/downloads/) (coche *Add to PATH*)
3. Installe [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) si besoin
4. Double-clic `scripts\build-windows.bat`
5. Zippe `dist\PSHomebrewDesk\` → upload en **GitHub Release**

Les utilisateurs lancent `PSHomebrewDesk.exe` — pas besoin de Python ni du source.

## Signature

- Auteur : **Pixam** (`version.json` → `author`)
- Titre fenêtre / UI : `by Pixam`

## Ce qui n’est pas dans le zip public

- Sources `.py`
- `payloads/*.elf` (chacun met les siens)
- `vendor/` (Relapse optionnel, téléchargé à la demande)

## Licence

Ajoute un `LICENSE` (ex. MIT pour l’app, ou “All rights reserved — Pixam”) selon ce que tu veux autoriser.
