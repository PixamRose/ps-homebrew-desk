# Pixam Community — Setup Discord

Script qui monte **tout le serveur Discord** pour ta communauté : rôles, catégories, salons texte / annonces / forum / vocal, règles et messages d'accueil.

Thème : **jailbreak PS5**, **news firmware**, **homebrew**, **mises à jour apps Pixam** (PS Homebrew Desk…).

---

## Ce que ça crée

### Rôles
| Rôle | Rôle |
|---|---|
| 👑 Pixam | Admin (toi) |
| 🛡️ Modérateur | Modération |
| ⭐ VIP | Membres proches |
| 🎮 Membre | Accès standard |
| 📢 Ping News | Alertes actus PS5 |
| 🔧 Ping Updates | Alertes maj apps |
| 🚨 Ping JB | Alertes jailbreak |

### Salons
- **📢 ACCUEIL** — bienvenue, règles, annonces, rôles  
- **📰 NEWS PS5** — news, firmware, leaks  
- **🛠️ JAILBREAK & HOMEBREW** — jb-general, aide, etaHEN/OnionHEN, payloads, ps4  
- **📱 APPS PIXAM** — mises-à-jour, ps-homebrew-desk, suggestions, bugs  
- **💬 COMMUNAUTÉ** — général, présentations, media, off-topic  
- **🔊 VOCAL** — général, gaming/chill, support live, AFK  
- **🔒 STAFF** — mod-chat, mod-logs, vocal staff (privé)

---

## Prérequis (5 min)

1. **Crée un serveur Discord vide**  
   Discord → `+` → Créer un serveur → ex. `Pixam Community`

2. **Crée une application bot**  
   → [discord.com/developers/applications](https://discord.com/developers/applications)  
   → **New Application** → nom `Pixam Setup` (ou autre)  
   → onglet **Bot** → **Add Bot** → **Reset Token** → copie le token  
   → active **Server Members Intent** (Privileged Gateway Intents)

3. **Invite le bot en admin**  
   Onglet **OAuth2 → URL Generator**  
   - Scopes : `bot`  
   - Bot Permissions : `Administrator`  
   - Ouvre l’URL générée → choisis ton serveur → Autoriser

4. **Récupère l’ID du serveur**  
   Discord → Paramètres → Avancés → **Mode développeur** ON  
   → clic droit sur le serveur → **Copier l'identifiant du serveur**

---

## Lancer le setup (Windows)

```bat
cd community\discord
copy .env.example .env
notepad .env
```

Dans `.env` :
```env
DISCORD_TOKEN=ton_token
DISCORD_GUILD_ID=id_du_serveur
```

Puis :
```bat
python -m pip install -r requirements.txt
python setup_server.py
```

Ou double-clic sur `setup.bat`.

Le bot se connecte, crée toute la structure, poste les messages, puis se déconnecte.  
Tu peux relancer le script : il **ne duplique pas** ce qui existe déjà.

---

## Après le setup

1. Icône + bannière du serveur (logo Pixam)  
2. Assigne **🛡️ Modérateur** à tes modos  
3. Partage l’invite (Réglages serveur → Invitations)  
4. (Optionnel) Ajoute un bot de réactions pour les pings dans `#roles`  
5. Le token bot n’est plus obligatoire au quotidien — tu peux le régénérer ou le garder pour des futures maj de structure

---

## Sécurité

- **Ne commit jamais** `.env` ni ton token  
- Ne partage pas le token en screenshot / Discord  
- Pas de liens de dumps / jeux piratés dans les règles du serveur (déjà indiqué dans `#regles`)
