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
| `/play` (YouTube) | ✅ OK | URL directe, autocomplete, fallback SoundCloud, sélection de résultats via `ytsearch:` et départ optionnel `debut` |
| `/play` (SoundCloud) | ✅ OK | URL SoundCloud fonctionnelle |
| `/play` (Spotify) | ✅ OK | App Spotify `SKORMBOT`, OAuth client credentials validé, LavaSrc résout les URLs Spotify |
| `/nowplaying`, `/queue`, `/skip` | ✅ OK | Commandes de file fonctionnelles |
| `/play debut`, `/volume`, `/volumedefaut` | ✅ OK | Départ optionnel précis + volume de session + volume par défaut persistant à 20 |
| Reprise après restart | ✅ OK | Piste courante, position, pause, volume, salon vocal, file et historique sauvegardés/restaurés |
| `/stoprecord` | ✅ Répond | Plus de timeout (event loop fixé) |
| Slash commands | ✅ Sync | 20 commandes syncées |
| Moonshine STT | ✅ Chargé | Medium Streaming model, CPU-only |

---

## ❌ Bloqué

### 1. Spotify — Clés API invalides ✅ Résolu

**Problème initial** : Lavalink retournait `invalid_client` / `400 Bad Request` sur l'OAuth Spotify.

**Cause** : L'app Spotify existante est configurée pour Home Assistant (OAuth avec redirect URIs). Le flow **client credentials** que LavaSrc utilise ne fonctionne pas avec cette app.

**Test initial** :
```
curl -X POST https://accounts.spotify.com/api/token \
  -u "<client_id>:<client_secret>" \
  -d "grant_type=client_credentials"
→ HTTP 400 Bad Request
```

**Correction appliquée** :
1. Création d'une app Spotify Developer dédiée : `SKORMBOT`
2. Mise à jour de `/opt/skorm-bot/.env` avec les nouveaux `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`
3. Backup ciblé : `/opt/skorm-bot/backups/20260708-195256-spotify-audio-fix/`
4. Rebuild/restart : `docker compose up -d --build`

**Validation prod** :
- OAuth Spotify depuis VPS : HTTP 200 avec `access_token`
- Lavalink `/v4/loadtracks` sur URL Spotify : `loadType=track`, source `spotify`, titre/auteur/URI présents
- Logs Lavalink : plus de `invalid_client`

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

### 3. `/play` — Erreur 404 Unknown Message ✅ Corrigé localement

**Problème initial** : Parfois le `/play` levait `NotFound: 404 Not Found (error code: 10008): Unknown Message`.

**Cause** : Le bot pouvait essayer d'éditer un message de statut supprimé ou expiré (après un restart ou un timeout).

**Correction** : `bot/cogs/music.py` utilise maintenant `_safe_message_edit()` pour ignorer proprement les messages supprimés, notamment sur le menu de résultats de `/play`.

**Correction complémentaire** : les erreurs Lavalink `Failed to Load Tracks` / `Something went wrong while looking up the track` déclenchent maintenant des fallbacks :
- URL Spotify → test OAuth client credentials ; si invalide, bypass LavaSrc direct
- URL directe → métadonnées publiques Spotify/oEmbed titre/artiste → `ytsearch:` → `scsearch:` → recherche brute
- `ytsearch:` autocomplete → `scsearch:` → recherche brute

**Validation** : `python -m py_compile bot/cogs/music.py`

---

### 4. `/pause`, `/next` — Session Lavalink périmée ✅ Mitigé localement

**Problème initial** : Après un restart de Lavalink seul (sans le bot), les commandes `/pause`, `/next`, `/skip` retournaient `404 Not Found` car la session Lavalink était invalidée.

**Cause** : Le bot garde une référence à un player Lavalink qui n'existe plus.

**Correction** : les commandes player capturent maintenant les erreurs de session expirée, nettoient le voice client local et demandent de relancer `/play` pour recréer un player propre. `/play` retente automatiquement une lecture si la session est détectée périmée.

**Procédure recommandée en prod** : redémarrer les deux containers ensemble :
```bash
docker compose up -d
```

---

## 📋 Résumé des fichiers modifiés

| Fichier | Modification |
|---------|-------------|
| `bot/cogs/voice_record.py` | Rewrite complet : recv() thread dédié, queue.Queue, thread pool Opus |
| `bot/cogs/music.py` | Fallback `ytsearch:`, autocomplete, sélection des résultats, safe edit, gestion session Lavalink périmée, test OAuth Spotify runtime, reprise complète après restart |
| `bot/cogs/db.py` | Persistance du volume par défaut musique, fallback à 20 |
| `.env.example` | Ajout placeholders `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` |
| `README.md` | Documentation `/play` URL/recherche et variables Lavalink/Spotify |
| `bot/cogs/setup.py` | `_secure_voice_channels()` préserve l'accès bot aux salons vocaux |
| `/opt/skorm-bot/.env` | Spotify credentials remplacées par l'app `SKORMBOT` validée |

---

## 🎯 Priorités

1. **`/recordconv`** : Tester la capture audio → feature principale en cours
2. **`/play` Spotify** : validé côté Lavalink, à confirmer par test Discord réel en salon vocal
3. **Restart Lavalink** : mitigation ajoutée, garder `docker compose up -d` comme procédure standard
