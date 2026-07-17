# 🌩️ SKORMBOT — Discord Server Management Bot

> **CREATE. CONNECT. DEVELOP.**

Bot Discord administrateur pour serveur créatif/agency. Il configure, automatise et
modère l'ensemble du serveur — identité visuelle noir/blanc/gris, branding
minimaliste, expérience fluide.

---

## ✨ Fonctionnalités

| Module | Description |
|--------|-------------|
| 🏗️ **Setup** | Crée les 6 catégories, 100+ salons, 25+ rôles et toutes les permissions en une commande (`/setup`). |
| 👋 **Welcome** | Message de bienvenue + bouton de vérification (rôle `Verified`). |
| 🎭 **Auto-roles** | Réactions sur le message pinned pour s'attribuer ses rôles. |
| 🎫 **Tickets** | Système de tickets privés avec claim, transfer, close + transcript. |
| 📜 **Logs** | Tous les events de modération loggés dans `mod-logs` (embeds structurés). |
| 🚨 **Anti-spam** | Timeout 5 min si > 5 msg / 3 s, anti-mass-mention, anti-raid. |
| ⏰ **Reminders** | Rappels personnels (`/remind set 30m …`) + événements Discord avec notifications H-24 et H-1. |
| 🛡️ **Moderation** | `/mod warn`, `mute`, `kick`, `ban`, `unmute`, `warnings` + auto-delete liens suspects. |
| 🎵 **Music** | Player Lavalink : `/play` accepte URLs directes, vérifie Spotify OAuth, fallback par métadonnées publiques, suggestions d'autocomplete et recherches texte avec menu de sélection ; volume par défaut configurable avec `/volumedefaut` ; reprise automatique de la piste, de la position et de la file après redémarrage. |
| 🖼️ **Images** | `/createimage` génère ou modifie une image via MOODBEAST/ComfyUI avec profils `rapide`, `standard` et `qualite`. |
| 🎬 **Vidéos** | `/createvideo` lance une génération image-to-video MOODBEAST/ComfyUI, libère la VRAM via le GPU switcher et renvoie un lien Nextcloud. |

---

## 📁 Structure du projet

```
SKORMBOT/
├── PROJECT.md                 # Cahier des charges / suivi
├── README.md                  # ← ce fichier
├── .env.example               # Template des variables d'environnement
├── .gitignore
├── requirements.txt           # discord.py, aiosqlite, python-dotenv
├── Dockerfile                 # Image Python 3.11 slim
├── docker-compose.yml         # Service skorm-bot (restart: unless-stopped)
├── bot/
│   ├── __init__.py
│   ├── main.py                # Point d'entrée, intents, chargement des cogs
│   ├── config.py              # Couleurs, paths, branding
│   └── cogs/
│       ├── __init__.py
│       ├── db.py              # aiosqlite schema + helpers
│       ├── utils.py           # Embeds, parse_duration, role/channel lookup
│       ├── setup.py           # /setup — création serveur complet
│       ├── welcome.py         # Welcome + vérification
│       ├── autoroless.py      # Auto-rôles par réaction
│       ├── tickets.py         # /ticket, /ticket claim/close/transfer
│       ├── logging_cog.py     # Logs modération (mod-logs)
│       ├── antispam.py        # Anti-spam, anti-raid, anti-mention
│       ├── reminders.py       # /remind, /event
│       └── moderation.py      # /mod warn/mute/kick/ban/unmute/warnings
├── assets/
│   ├── skormlogo.jpeg
│   └── skormban.jpeg
└── data/
    └── skorm.db               # SQLite (créé au runtime)
```

---

## 🚀 Installation locale

### 1. Cloner & configurer

```bash
git clone https://github.com/Bl3aven/SKORMBOT.git
cd SKORMBOT
cp .env.example .env
# Édite .env avec ton BOT_TOKEN et ton OWNER_ID
```

### 2. Installer les dépendances

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Lancer le bot

```bash
python bot/main.py
```

Le bot se connecte, initialise la base SQLite, synchronise les slash commands
et reste en ligne.

### 4. Premier setup du serveur

Une fois le bot invité et en ligne, exécute dans ton serveur :

```
/setup
```

> ⚠️ Réservé à l'utilisateur avec l'ID `OWNER_ID` du `.env`.

Le bot va créer **~25 rôles**, **6 catégories**, **~80 salons textuels**,
**~25 vocaux** et appliquer toutes les permissions.

---

## 🐳 Déploiement Docker (VPS OVH .57)

```bash
git clone https://github.com/Bl3aven/SKORMBOT.git /opt/skorm-bot
cd /opt/skorm-bot
cp .env.example .env
nano .env                         # Remplir BOT_TOKEN, SERVER_ID, OWNER_ID
chmod 600 .env
docker compose up -d --build
docker compose logs -f skorm-bot
```

Pour un redémarrage automatique au reboot du VPS, active le service Docker
(systemd ou `docker compose` + redémarrage par Docker — `restart: unless-stopped`
est déjà configuré).

---

## 🔐 Configuration (`.env`)

| Variable | Description | Exemple |
|----------|-------------|---------|
| `BOT_TOKEN` | Token Discord du bot | `MTx5b3VyLnRva2VuPg…` |
| `SERVER_ID` | ID du serveur Discord | `123456789012345678` |
| `OWNER_ID` | Ton ID Discord (autorise `/setup`) | `123456789012345678` |
| `LAVALINK_HOST` | Host Lavalink | `lavalink` |
| `LAVALINK_PORT` | Port Lavalink | `2333` |
| `LAVALINK_PASSWORD` | Mot de passe Lavalink | `skorm` |
| `SPOTIFY_CLIENT_ID` | Client ID Spotify dédié au bot | `xxxxxxxx` |
| `SPOTIFY_CLIENT_SECRET` | Client Secret Spotify dédié au bot | `xxxxxxxx` |
| `COMFYUI_IMAGE_API_ENDPOINT` | Endpoint image MOODBEAST OpenAI-compatible | `http://192.168.1.210:8091/v1` |
| `COMFYUI_IMAGE_API_KEY` | Clé API `mood-inference-api` | `xxxxxxxx` |
| `COMFYUI_IMAGE_QUALITY` | Profil image par défaut | `standard` |
| `COMFYUI_VIDEO_API_ENDPOINT` | Endpoint vidéo MOODBEAST OpenAI-compatible | `https://inference.tournayre.ovh/v1` |
| `COMFYUI_VIDEO_API_KEY` | Clé API `mood-inference-api` pour `/createvideo` | `xxxxxxxx` |
| `COMFYUI_VIDEO_MODEL` | Modèle vidéo exposé par MOODBEAST | `moodvideo` |
| `COMFYUI_VIDEO_TIMEOUT_SECONDS` | Timeout maximal de rendu/polling vidéo | `7200` |
| `COMFYUI_VIDEO_POLL_SECONDS` | Intervalle de polling du job vidéo | `10` |
| `COMFYUI_VIDEO_MAX_IMAGE_BYTES` | Taille maximale image de référence | `25165824` |

Le token doit rester **secret** :
- En local : `.env` ignoré par Git (`.gitignore`)
- Sur le VPS : `chmod 600 .env`
- **Ne jamais committer le fichier `.env` ni exposer le token en clair**

---

## 🛠️ Commandes

### Owner
| Commande | Description |
|----------|-------------|
| `/setup` | Construit le serveur complet (one-shot). |

### Staff & Direction
| Commande | Description |
|----------|-------------|
| `/ticket close` | Ferme le ticket courant. |
| `/ticket claim` | Prend en charge le ticket. |
| `/ticket transfer @user` | Ajoute un utilisateur au ticket. |
| `/mod warn @user raison` | Avertit (auto-mute à 3 warns). |
| `/mod mute @user 10m raison` | Timeout 1 min → 24 h. |
| `/mod unmute @user` | Retire le timeout. |
| `/mod kick @user raison` | Exclut (Direction+). |
| `/mod ban @user raison` | Bannit (Direction+). |
| `/mod warnings @user` | Liste des avertissements. |

### Membres
| Commande | Description |
|----------|-------------|
| `/remind set message 30m` | Programme un rappel (DM). |
| `/remind list` | Liste des rappels actifs. |
| `/remind delete id` | Supprime un rappel. |
| `/event create name "2026-12-31 20:00"` | Crée un événement Discord. |
| `/play <url ou recherche> [debut]` | Lance une URL directement, teste OAuth pour Spotify, tente un fallback titre/artiste si le lien échoue, ou propose les meilleurs résultats d'une recherche texte. `debut` accepte `90s`, `1m30s`, `2:15`, `1:02:03`. |
| `/queue`, `/nowplaying`, `/pause`, `/skip`, `/stop` | Contrôle la lecture Lavalink. |
| `/volume <niveau>` | Règle le volume de la lecture en cours. |
| `/volumedefaut <niveau>` | Définit le volume par défaut des nouvelles lectures (20 par défaut). |
| `/createimage <prompt> [image] [force] [qualite]` | Génère une image ou modifie un fichier image. `qualite` accepte `rapide`, `standard` ou `qualite`; `force` règle l'intensité d'édition de 0.1 à 1.0. |
| `/createvideo <prompt> <image> [duree] [qualite]` | Génère une vidéo 9:16 à partir d'une image de référence via MOODBEAST/ComfyUI. Réservé au owner ou au rôle `AdminDiscord`; `duree` accepte 12 ou 15 secondes, `qualite` accepte `premium` (Wan2.2 14B puis fallback) ou `fiable` (Wan2.2 5B). Le résultat est hébergé sur Nextcloud, jamais uploadé en pièce jointe Discord. |

L'état musique est sauvegardé en SQLite toutes les 10 secondes et lors des actions de contrôle : piste courante, position, pause, volume, salon vocal, file d'attente et historique récent.

---

## 🎨 Identité visuelle

- **Noir** : `#000000` — fond, embed par défaut
- **Blanc** : `#FFFFFF` — Direction
- **Gris foncé** : `#333333` — Membres
- **Gris** : `#888888` — Staff
- **Gris moyen** : `#555555` — Formations
- **Footer systématique** : `SKORM — CREATE. CONNECT. DEVELOP.`

---

## 🧪 Tests manuels

```bash
# 1. Lancer le bot
python bot/main.py

# 2. Dans Discord :
/setup                                  # Crée tout
# -> Vérifie : 6 catégories, ~80 salons, 25+ rôles
# -> Vérifie : la hiérarchie des rôles
# -> Vérifie : les permissions des catégories

# 3. Rejoindre le serveur avec un compte test
# -> Welcome message dans 📌・welcome
# -> Bouton "J'accepte le règlement" → rôle Verified

# 4. Ajouter une réaction dans 🎭・roles
# -> Le rôle correspondant est attribué

# 5. Cliquer "🎫 Ouvrir un ticket" dans 🎫・support
# -> Salon privé 🎫-username créé

# 6. Spam 6 messages en < 3 s
# -> Timeout 5 min + log dans mod-logs

# 7. /remind set "Test" 1m
# -> DM reçu après 1 minute
```

---

## 📜 Licence

Propriétaire — © 2026 SKORM. Tous droits réservés.
