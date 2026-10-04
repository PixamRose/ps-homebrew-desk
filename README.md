# PS Homebrew Desk

<p align="center">
  <img src="assets/logo.png" alt="PS Homebrew Desk" width="160" />
</p>

<p align="center"><strong>by Pixam</strong></p>

Companion **Mac / Windows / iPhone (PWA)** pour installer des `.elf` / tools / fichiers sur une PS5 jailbreakée, via le FTP (etaHEN / OnionHEN).

---

## Prérequis

### Console PS5

| Besoin | Détail |
|---|---|
| Firmware jailbreakable | Console déjà en homebrew (HEN / exploit) |
| FTP actif | Port **1337** (OnionHEN / etaHEN) |
| IP locale connue | Ex. `192.168.1.x` (Réglages réseau PS5) |
| Même réseau | Mac/PC et PS5 sur le **même Wi‑Fi / Ethernet** |
| PSN | Reste **offline** sur console JB |

### Mac (mode source)

| Besoin | Détail |
|---|---|
| macOS | Version récente recommandée |
| Python | **3.10+** (`python3 --version`) |
| Dépendances | `pip install -r requirements.txt` → **pywebview**, rarfile |
| Archives (optionnel) | **Keka** ou `brew install unar` pour RAR/7z |
| Réseau | Accès LAN vers la PS5 |

### Windows — utilisateurs (release `.exe`)

| Besoin | Détail |
|---|---|
| Windows | **10** ou **11** (64-bit) |
| Runtime | [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (souvent déjà là avec Edge) |
| App | `PSHomebrewDesk.exe` (release) — **Python pas obligatoire** |
| Réseau | Même LAN que la PS5 |

### Windows — développeur / build

| Besoin | Détail |
|---|---|
| Python | **3.10+** avec *Add to PATH* |
| WebView2 | Runtime Edge |
| Build | `scripts\build-windows.bat` → `dist\PSHomebrewDesk\` |
| Archives (optionnel) | WinRAR / UnRAR ou **7-Zip** |

### iPhone (PWA)

| Besoin | Détail |
|---|---|
| Hub | Mac ou PC lancé en **mode LAN** |
| Navigateur | **Safari** |
| Réseau | Même Wi‑Fi que le hub |
| Install | Partager → **Sur l’écran d’accueil** |

### Sécurité LAN (fortement recommandé)

```bash
# Mac
DESK_TOKEN=ton-secret DESK_LAN=1 DESK_HOST=0.0.0.0 python3 desktop.py

# Windows (cmd)
set DESK_TOKEN=ton-secret
set DESK_LAN=1
set DESK_HOST=0.0.0.0
start-lan.bat
```

Sans `DESK_TOKEN`, tout appareil sur le Wi‑Fi de confiance peut piloter le hub.

---

## Lancer rapidement

### Mac

```bash
cd pshomebrew-desk
python3 -m pip install --user -r requirements.txt
python3 desktop.py
# ou double-clic : start.command
```

Mode navigateur : `python3 app.py` → http://127.0.0.1:8787

### Windows

1. Release : lance `PSHomebrewDesk.exe`
2. Source : double-clic `start.bat`

### Mode LAN (iPhone / autre PC)

```bash
./start-lan.command   # Mac
start-lan.bat         # Windows
```

Puis onglet **Desk → Réseau & mises à jour** pour copier l’URL.

---

## Structure du projet

```
pshomebrew-desk/
├── desktop.py              # Entrée fenêtre native (Mac / Windows)
├── app.py                  # Entrée serveur HTTP + API
├── version.json            # Version + auteur (Pixam)
├── requirements.txt
├── start.command / start.bat
├── start-lan.command / start-lan.bat
├── desk/                   # Code applicatif
│   ├── common.py           # Chemins, version, LAN, notifs
│   ├── transfer.py         # FTP / archives / jobs
│   ├── games.py · elfs.py  # Jeux & outils .elf
│   ├── relapse.py          # Host Relapse (optionnel)
│   └── update_channel.py   # Mises à jour LAN
├── static/                 # UI (HTML / CSS / JS) + PWA
├── assets/                 # Branding (.ico / .icns / logo)
│   └── source/             # Sources graphiques (non runtime)
├── catalog/                # Store (default.json) — files/ ignoré
├── payloads/               # Tes .elf (non versionnés) + README
├── updates/                # Zips de update LAN (ignorés)
├── packaging/              # Spec PyInstaller Windows
├── scripts/                # build-windows, publish/apply update
├── community/              # Outils communauté (Discord…)
└── docs/
    └── RELEASE.md          # Publier sans exposer le source
```

| Dossier | Rôle |
|---|---|
| `desk/` | Logique métier (imports Python) |
| `static/` | Interface web / PWA |
| `assets/` | Branding (logo Pixam) |
| `catalog/` | Catalogue store |
| `payloads/` | Binaires HEN / tools **à ajouter toi-même** |
| `packaging/` | Build `.exe` Windows |
| `scripts/` | Outils build & update |
| `community/` | Setup Discord / communauté Pixam |
| `docs/` | Doc publication |

---

## Fonctionnalités

- Scan ports (1337 / 9021 / …)
- Explorateur : écriture `/data`, `/user`, `/mnt` — système en lecture seule
- Store local + SHA-256
- Transfert FTP, liens → download → extract local → upload
- Hub LAN + updates + PWA iPhone
- Signature **by Pixam**

### Archives (onglet Lien)

`.rar` / `.zip` / `.7z` : extraits **sur le Mac/PC**, puis upload du contenu (pas sur la PS5).

### Payloads

Les `.elf` **ne sont pas** dans le dépôt. Place-les dans `payloads/` — voir `payloads/README.txt`.

---

## Ce que ça ne fait pas

- Écriture sur `/system`
- Patch kernel
- Autoload automatique

---

## Distribution

Voir [`docs/RELEASE.md`](docs/RELEASE.md) : publier le **build Windows**, pas forcément tout le code source.

---

## Licence / auteur

- **Auteur :** Pixam  
- **Licence :** All Rights Reserved — voir [`LICENSE`](LICENSE)  
- Respecte les licences des outils / payloads tiers.
