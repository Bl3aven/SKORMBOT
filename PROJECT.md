# 🌩️ SKORMBOT — Discord Server Management Bot

> **Serveur Discord** : configurable via `.env`
> **Stack** : Python 3.11 + discord.py + SQLite + Docker
> **Statut** : 🟢 Stable
> **Créé** : 2026-07-05

---

## 🎯 Objectif

Bot Discord administrateur qui configure et gère entièrement le serveur SKORM :
- Structure complète (catégories, salons, rôles, permissions)
- Automatisations (welcome, tickets, auto-rôles, logs, anti-spam, rappels)
- Modération automatique
- Déploiement 24/7 sur VPS

---

## 📋 Cahier des charges

### Organisation du serveur

| Catégorie | Visible par | Salons |
|-----------|------------|--------|
| 🏠 Accueil & Communauté | Tous | 14 textuels + 4 vocaux |
| 🎤 Artistes | Artist, Coach, Direction | 28 textuels + 6 vocaux |
| 🤝 Agents | Agent, Direction | 19 textuels + 5 vocaux |
| 🎓 Formations | Student (inscrit), Formateur, Direction | 21 textuels + 5 vocaux |
| 🔒 Staff | Staff, Direction | 2 textuels |
| 📜 Logs | Bot uniquement | 2 textuels (cachés) |

### Hiérarchie des rôles

**Direction** (`#FFFFFF`)
- Founder, CEO, Creative Director, Label Founder, Admin

**Staff** (`#888888`)
- Moderator, Support, Coach Artistique, Coach Production, Coach DJ, Coach Social Media, Formateur

**Membres** (`#333333`)
- Artist, Agent, Student, Verified Member, Community, Partner

**Formations** (`#555555`)
- IA Musicale, Suno, Production, DJ Performance, Social Media, Marketing

**Système** (`#000000`)
- Verified, Ticket Admin

### Permissions

| Rôle | Accueil | Artistes | Agents | Formations |
|------|---------|----------|--------|------------|
| Direction | ✓ | ✓ | ✓ | ✓ |
| Artist | ✓ | ✓ | ✗ | ✗ |
| Agent | ✓ | ✗ | ✓ | ✗ |
| Student | ✓ | ✗ | ✗ | ✓ (inscrites) |
| Staff | ✓ | Selon rôle | Selon rôle | Selon rôle |

---

## 🚀 Plan de déploiement

### Phase 1 — Structure du projet ✅

- [x] **1.1** Créer la structure du projet (`bot/`, `cogs/`, `assets/`, `data/`)
- [x] **1.2** Configurer `.env.example` + `requirements.txt`
- [ ] **1.3** Stocker le token dans `.secrets/passwords.sops.json` (`discord.skorm.token`)
- [x] **1.4** Créer `Dockerfile` + `docker-compose.yml`
- [x] **1.5** Écrire `README.md`

### Phase 2 — Configuration du serveur ✅

- [x] **2.1** `bot/main.py` — Point d'entrée, intents, cog loading
- [x] **2.2** `bot/config.py` — Chargement config (token, server ID, channels)
- [x] **2.3** `bot/cogs/setup.py` — Création catégories, salons, rôles, permissions
- [x] **2.4** `bot/cogs/utils.py` — Utilitaires communs
- [ ] **2.5** Tester `/setup` → vérification structure serveur

### Phase 3 — Automatisations ✅

- [x] **3.1** `bot/cogs/welcome.py` — Welcome + vérification (bouton → rôle Verified)
- [x] **3.2** `bot/cogs/autoroless.py` — Auto-rôles via réactions
- [x] **3.3** `bot/cogs/tickets.py` — Système de tickets (création, close, transfer, claim)
- [x] **3.4** `bot/cogs/logging_cog.py` — Logs de modération (embeds structurés)
- [x] **3.5** `bot/cogs/antispam.py` — Anti-spam (>5msg/3s), anti-raid (>10joins/min)
- [x] **3.6** `bot/cogs/reminders.py` — Rappels + événements (H-24/H-1 notifications)
- [x] **3.7** `bot/cogs/moderation.py` — Warn, mute, kick, ban, auto-delete

### Phase 4 — Déploiement VPS

- [ ] **4.1** Tester localement : `python bot/main.py` → bot online + `/setup`
- [ ] **4.2** Déployer sur VPS OVH (.57) : `/opt/skorm-bot/`
- [ ] **4.3** Configurer `.env` sur le VPS (chmod 600)
- [ ] **4.4** Docker Compose up + systemd auto-restart
- [ ] **4.5** Vérifier bot online 24/7 + automations fonctionnelles

---

## 📁 Structure du projet

```
SKORMAgency/
├── PROJECT.md                 # ← Ce fichier (suivi de projet)
├── README.md                  # Documentation
├── .env.example               # Template variables
├── requirements.txt           # Dépendances Python
├── Dockerfile                 # Containerisation
├── docker-compose.yml         # Déploiement Docker
├── bot/
│   ├── main.py                # Point d'entrée
│   ├── config.py              # Configuration
│   └── cogs/
│       ├── __init__.py
│       ├── setup.py           # Création serveur
│       ├── welcome.py         # Welcome + vérification
│       ├── autoroless.py      # Auto-rôles
│       ├── tickets.py         # Système de tickets
│       ├── logging.py         # Logs modération
│       ├── antispam.py        # Anti-spam/raid
│       ├── reminders.py       # Rappels + événements
│       ├── moderation.py      # Modération
│       └── utils.py           # Utilitaires
├── assets/
│   ├── skormlogo.jpeg         # Logo SKORM
│   └── skormban.jpeg          # Bannière SKORM
└── data/
    └── skorm.db               # SQLite (tickets, rappels, rôles)
```

---

## 🔑 Configuration

### Variables d'environnement

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Token du bot Discord |
| `SERVER_ID` | ID du serveur Discord |
| `OWNER_ID` | ID de l'utilisateur owner |
| `LOG_CHANNEL_ID` | ID du salon de logs |
| `WELCOME_CHANNEL_ID` | ID du salon welcome |
| `ROLES_CHANNEL_ID` | ID du salon auto-rôles |
| `TICKETS_CATEGORY_ID` | ID de la catégorie tickets |

### Secrets

- Token stocké dans `.secrets/passwords.sops.json` → clé `discord.skorm.token`
- Sur le VPS : `.env` avec `chmod 600`

---

## 🧪 Vérification

- [ ] Test local : bot se connecte, `/setup` crée tout le serveur
- [ ] `/serverinfo` confirme catégories, salons, rôles, permissions
- [ ] Join → welcome message + bouton vérification
- [ ] Réaction → auto-rôle attribué
- [ ] Ticket → salon privé créé
- [ ] Anti-spam → timeout après >5 messages en 3 secondes
- [ ] Docker running 24/7 sur VPS OVH (.57)

---

## 📝 Décisions

- **discord.py** — Framework Python moderne, async, bien documenté
- **Docker sur VPS OVH (.57)** — Serveur le plus puissant, déjà utilisé
- **SQLite** — Persistance légère (tickets, rappels, rôles)
- **Couleurs noir/blanc/gris** — Match avec l'identité visuelle SKORM
- **Commandes slash** pour admin, **boutons/réactions** pour utilisateurs
- **Intégrations Notion/Google Calendar** → Phase 2 (futur)

---

## 🔮 Phase 2 (Futur)

- [ ] Intégration Notion — Suivi des artistes
- [ ] Intégration Google Calendar — Sync événements
- [ ] Webhook Discord — Notifications asynchrones
- [ ] Dashboard web — Stats, membres, tickets
- [ ] Migration PostgreSQL — Si le serveur grossit