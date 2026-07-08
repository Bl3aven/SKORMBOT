# SKORMBOT - État des Bloccages

**Date** : 2026-07-08
**Serveur** : VPS OVH (46.18.212.57)
**Docker** : `skorm-bot` + `skorm-lavalink`

---

## ✅ Fonctionnel

| Feature | Statut | Notes |
|---------|--------|-------|
| Bot Discord | ✅ Online | BleavenBOT#3775, connecté au gateway |
| Lavalink | ✅ Connecté | YouTube plugin + LavaSrc chargés |
| `/play` (YouTube) | ✅ OK | Recherche texte via `ytsearch:` fallback |
| `/play` (SoundCloud) | ✅ OK | URL SoundCloud fonctionnelle |
| `/nowplaying`, `/queue`, `/skip` | ✅ OK | Commandes de file fonctionnelles |
| `/stoprecord` | ✅ Répond | Plus de timeout (event loop fixé) |
| Slash commands | ✅ Sync | 20 commandes syncées |
| Moonshine STT | ✅ Chargé | Medium Streaming model, CPU-only |

---

## ❌ Bloqué

### 1. Spotify — Clés API invalides

**Problème** : Lavalink retourne `invalid_client` / `400 Bad Request` sur l'OAuth Spotify.

**Cause** : L'app Spotify "Max" (Client ID: `8135bad63143448190f458e0587ba33f`) est configurée pour Home Assistant (OAuth avec redirect URIs). Le flow **client credentials** que LavaSrc utilise ne fonctionne pas avec cette app.

**Test effectué** :
```
curl -X POST https://accounts.spotify.com/api/token \
  -u "8135bad63143448190f458e0587ba33f:24fec0ef2f0448fd8f7d488514792a2d2" \
  -d "grant_type=client_credentials"
→ HTTP 400 Bad Request
```

**Solution** : Créer une **nouvelle app Spotify** dédiée au bot Discord :
1. https://developer.spotify.com/dashboard → **Create app**
2. Nom : `SKORMBOT`
3. Récupérer Client ID + Client Secret
4. Mettre à jour `/opt/skorm-bot/.env` :
   ```
   SPOTIFY_CLIENT_ID=<nouveau>
   SPOTIFY_CLIENT_SECRET=<nouveau>
   ```
5. `docker compose restart lavalink`

---

### 2. `/recordconv` — Capture audio à valider

**Problème** : L'architecture a été entièrement réécrite (recv() dans un thread dédié + queue.Queue + thread pool pour le décodage Opus), mais la capture n'a pas été validée avec succès.

**Historique des tentatives** :
1. `recv()` dans l'event loop → bloquait le gateway Discord (timeout 30s)
2. `on_voice_receive` callback → ne fire pas (expérimental dans discord.py 2.x)
3. `recv()` dans un thread dédié → déployé, à tester

**Architecture actuelle** :
- `_recv_thread()` : thread daemon qui appelle `voice_client.recv(timeout=1.0)` et enfile dans `queue.Queue`
- `_process_packets()` : tâche async qui vide la queue et décode dans un thread pool
- Event loop reste 100% responsive (`/stoprecord` répond instantanément)

**À tester** :
1. Rejoindre un salon vocal
2. `/recordconv`
3. Parler 10-15 secondes
4. `/stoprecord`
5. Vérifier que des packets sont capturés et que la transcription fonctionne

**Logs à surveiller** :
```
grep -E '(recv thread|packet processor|packets from|Ending recording)' /var/log/skorm-bot.log
```

---

### 3. `/play` — Erreur 404 Unknown Message

**Problème** : Parfois le `/play` lève `NotFound: 404 Not Found (error code: 10008): Unknown Message`.

**Cause** : Le bot essaie d'éditer un message de statut qui a été supprimé ou qui n'existe plus (après un restart ou un timeout).

**Impact** : Mineur — la musique joue quand même, mais l'utilisateur voit une erreur.

**Solution** : Ajouter un try/except sur `message.edit()` dans le music cog.

---

### 4. `/pause`, `/next` — Session Lavalink périmée

**Problème** : Après un restart de Lavalink seul (sans le bot), les commandes `/pause`, `/next`, `/skip` retournent `404 Not Found` car la session Lavalink est invalidée.

**Cause** : Le bot garde une référence à un player Lavalink qui n'existe plus.

**Solution** : Toujours restart les deux containers ensemble :
```bash
docker compose up -d
```

---

## 📋 Résumé des fichiers modifiés

| Fichier | Modification |
|---------|-------------|
| `bot/cogs/voice_record.py` | Rewrite complet : recv() thread dédié, queue.Queue, thread pool Opus |
| `bot/cogs/music.py` | Fallback `ytsearch:` pour la recherche YouTube |
| `bot/cogs/setup.py` | `_secure_voice_channels()` préserve l'accès bot aux salons vocaux |
| `/opt/skorm-bot/.env` | Spotify credentials mises à jour (à remplacer par nouvelles clés) |

---

## 🎯 Priorités

1. **Spotify** : Créer nouvelle app Spotify → bloquant pour `/play` Spotify
2. **`/recordconv`** : Tester la capture audio → feature principale en cours
3. **`/play` 404** : Try/except sur message.edit() → cosmétique
4. **Restart Lavalink** : Documenter la procédure → UX
