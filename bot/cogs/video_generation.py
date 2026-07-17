"""
SKORMBOT - ComfyUI video generation cog.

Provides /createvideo, backed by the MOODBEAST video endpoint. The backend owns
GPU switching, ComfyUI rendering and Nextcloud upload.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.config import (
    BRAND_NAME,
    COLOR_BLACK,
    COLOR_GRAY,
    COMFYUI_VIDEO_API_ENDPOINT,
    COMFYUI_VIDEO_API_KEY,
    COMFYUI_VIDEO_MAX_IMAGE_BYTES,
    COMFYUI_VIDEO_MAX_PROMPT_CHARS,
    COMFYUI_VIDEO_MODEL,
    COMFYUI_VIDEO_POLL_SECONDS,
    COMFYUI_VIDEO_TIMEOUT_SECONDS,
    OWNER_ID,
)
from bot.cogs.utils import create_embed

log = logging.getLogger("skorm.video_generation")


class VideoGenerationError(RuntimeError):
    """Raised when video generation cannot be started or completed."""


class VideoGenerationCog(commands.Cog):
    """Generate SKORM brand videos through the MOODBEAST ComfyUI API."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self._generation_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        timeout = aiohttp.ClientTimeout(total=COMFYUI_VIDEO_TIMEOUT_SECONDS + 300)
        self.session = aiohttp.ClientSession(timeout=timeout)

    async def cog_unload(self) -> None:
        if self.session:
            await self.session.close()

    @staticmethod
    def _videos_url(path: str) -> str:
        base = COMFYUI_VIDEO_API_ENDPOINT.rstrip("/")
        return f"{base}/videos/{path.lstrip('/')}"

    @staticmethod
    def _is_admindiscord(member: discord.Member | discord.User) -> bool:
        roles = getattr(member, "roles", [])
        return any(getattr(role, "name", "") == "AdminDiscord" for role in roles)

    @classmethod
    def _can_use_video(cls, interaction: discord.Interaction) -> bool:
        if OWNER_ID and interaction.user.id == OWNER_ID:
            return True
        return cls._is_admindiscord(interaction.user)

    @staticmethod
    def _validate_image(image: discord.Attachment) -> None:
        content_type = (image.content_type or "").lower()
        filename = (image.filename or "").lower()
        if content_type and not content_type.startswith("image/"):
            raise VideoGenerationError("Le fichier fourni n'est pas une image.")
        if not filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
            raise VideoGenerationError("Format image non supporte. Utilise PNG, JPG, JPEG ou WEBP.")
        if image.size and image.size > COMFYUI_VIDEO_MAX_IMAGE_BYTES:
            max_mb = COMFYUI_VIDEO_MAX_IMAGE_BYTES / (1024 * 1024)
            raise VideoGenerationError(f"Image trop lourde. Limite actuelle : {max_mb:.0f} MB.")

    async def _read_image(self, image: discord.Attachment) -> tuple[bytes, str, str]:
        self._validate_image(image)
        try:
            image_bytes = await image.read()
        except discord.HTTPException as exc:
            raise VideoGenerationError("Impossible de lire l'image Discord.") from exc
        if not image_bytes:
            raise VideoGenerationError("Image fournie vide.")
        if len(image_bytes) > COMFYUI_VIDEO_MAX_IMAGE_BYTES:
            max_mb = COMFYUI_VIDEO_MAX_IMAGE_BYTES / (1024 * 1024)
            raise VideoGenerationError(f"Image trop lourde. Limite actuelle : {max_mb:.0f} MB.")
        return image_bytes, image.filename or "image.png", image.content_type or "image/png"

    async def _start_video_job(
        self,
        *,
        prompt: str,
        image: discord.Attachment,
        duration: int,
        quality: str,
    ) -> dict[str, Any]:
        if not self.session:
            raise VideoGenerationError("Session HTTP non initialisee.")
        if not COMFYUI_VIDEO_API_ENDPOINT:
            raise VideoGenerationError("Endpoint video non configure.")
        if not COMFYUI_VIDEO_API_KEY:
            raise VideoGenerationError("Cle API video manquante.")

        image_bytes, filename, content_type = await self._read_image(image)
        form = aiohttp.FormData()
        form.add_field("model", COMFYUI_VIDEO_MODEL)
        form.add_field("prompt", prompt)
        form.add_field("duration_seconds", str(duration))
        form.add_field("aspect_ratio", "9:16")
        form.add_field("quality", quality)
        form.add_field("image", image_bytes, filename=filename, content_type=content_type)
        headers = {
            "Authorization": f"Bearer {COMFYUI_VIDEO_API_KEY}",
            "User-Agent": "SKORMBOT/1.0 (+https://tournayre.ovh)",
        }
        try:
            async with self.session.post(self._videos_url("generations"), data=form, headers=headers) as resp:
                if resp.status == 423:
                    raise VideoGenerationError("Un jeu est en cours sur MOODBEAST. Generation video refusee.")
                if resp.status >= 400:
                    body = await resp.text()
                    log.error("Video API start error %s: %s", resp.status, body[:1000])
                    raise VideoGenerationError(f"API video indisponible ({resp.status}).")
                return await resp.json()
        except asyncio.TimeoutError as exc:
            raise VideoGenerationError("Timeout au lancement du job video.") from exc
        except aiohttp.ClientError as exc:
            raise VideoGenerationError(f"Connexion impossible a l'API video: {type(exc).__name__}") from exc

    async def _poll_job(self, job_id: str) -> dict[str, Any]:
        if not self.session:
            raise VideoGenerationError("Session HTTP non initialisee.")
        headers = {
            "Authorization": f"Bearer {COMFYUI_VIDEO_API_KEY}",
            "User-Agent": "SKORMBOT/1.0 (+https://tournayre.ovh)",
        }
        deadline = asyncio.get_running_loop().time() + COMFYUI_VIDEO_TIMEOUT_SECONDS
        last_status = ""
        while asyncio.get_running_loop().time() < deadline:
            async with self.session.get(self._videos_url(f"jobs/{job_id}"), headers=headers) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise VideoGenerationError(f"Statut video indisponible ({resp.status}) : {body[:300]}")
                data = await resp.json()
            status = str(data.get("status") or "")
            if status != last_status:
                log.info("Video job %s status=%s message=%s", job_id, status, data.get("message"))
                last_status = status
            if status == "succeeded":
                return data
            if status in {"failed", "cancelled"}:
                detail = str(data.get("error") or data.get("message") or status)
                raise VideoGenerationError(detail[:900])
            await asyncio.sleep(COMFYUI_VIDEO_POLL_SECONDS)
        raise VideoGenerationError("Generation video trop longue ou timeout.")

    async def _send_public_update(self, interaction: discord.Interaction, embed: discord.Embed) -> None:
        try:
            await interaction.followup.send(embed=embed)
            return
        except discord.HTTPException as exc:
            log.warning("Interaction followup failed for video update: %s", exc)
        channel = interaction.channel
        if channel and hasattr(channel, "send"):
            await channel.send(embed=embed)

    @app_commands.command(name="createvideo", description="Cree une video SKORM avec ComfyUI")
    @app_commands.describe(
        prompt="Prompt detaille de la video a generer",
        image="Image de reference obligatoire",
        duree="Duree finale: 12 ou 15 secondes",
        qualite="premium tente le meilleur profil local puis fallback; fiable utilise le profil 5B",
    )
    @app_commands.choices(
        duree=[
            app_commands.Choice(name="12 secondes", value=12),
            app_commands.Choice(name="15 secondes", value=15),
        ],
        qualite=[
            app_commands.Choice(name="premium", value="premium"),
            app_commands.Choice(name="fiable", value="fiable"),
        ],
    )
    async def createvideo(
        self,
        interaction: discord.Interaction,
        prompt: str,
        image: discord.Attachment,
        duree: Optional[int] = 15,
        qualite: Optional[str] = "premium",
    ) -> None:
        prompt = (prompt or "").strip()
        if not self._can_use_video(interaction):
            await interaction.response.send_message(
                "Commande reservee au owner ou au role AdminDiscord.",
                ephemeral=True,
            )
            return
        if not prompt:
            await interaction.response.send_message("Prompt vide.", ephemeral=True)
            return
        if len(prompt) > COMFYUI_VIDEO_MAX_PROMPT_CHARS:
            await interaction.response.send_message(
                f"Prompt trop long. Limite actuelle : {COMFYUI_VIDEO_MAX_PROMPT_CHARS} caracteres.",
                ephemeral=True,
            )
            return
        if self._generation_lock.locked():
            await interaction.response.send_message(
                "Une generation video est deja en cours. Reessaie quand elle est terminee.",
                ephemeral=True,
            )
            return
        duration = int(duree or 15)
        if duration not in {12, 15}:
            await interaction.response.send_message("Duree invalide. Utilise 12 ou 15 secondes.", ephemeral=True)
            return
        quality = (qualite or "premium").strip().lower()
        if quality not in {"premium", "fiable"}:
            await interaction.response.send_message("Qualite invalide. Utilise premium ou fiable.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        async with self._generation_lock:
            try:
                started = await self._start_video_job(
                    prompt=prompt,
                    image=image,
                    duration=duration,
                    quality=quality,
                )
                job_id = str(started.get("job_id") or "")
                if not job_id:
                    raise VideoGenerationError("L'API video n'a pas retourne de job_id.")
                await self._send_public_update(
                    interaction,
                    create_embed(
                        title=f"Video lancee - {BRAND_NAME}",
                        description=f"Job `{job_id}` lance. Rendu ComfyUI puis upload Nextcloud en cours.",
                        color=COLOR_BLACK,
                    ),
                )
                result = await self._poll_job(job_id)
            except VideoGenerationError as exc:
                await self._send_public_update(
                    interaction,
                    create_embed(
                        title="Video non generee",
                        description=str(exc),
                        color=COLOR_GRAY,
                    ),
                )
                return
            except Exception as exc:
                log.exception("Unexpected video generation error")
                await self._send_public_update(
                    interaction,
                    create_embed(
                        title="Erreur video",
                        description=f"Erreur inattendue : `{type(exc).__name__}`.",
                        color=COLOR_GRAY,
                    ),
                )
                return

        metadata = result.get("metadata") or {}
        url = str(result.get("download_url") or "")
        details = [
            f"Job: `{result.get('job_id')}`",
            f"Modele: `{result.get('model') or COMFYUI_VIDEO_MODEL}`",
            f"Profil: `{metadata.get('profile', result.get('quality', quality))}`",
            f"Workflow: `{metadata.get('workflow', 'n/a')}`",
            f"Duree: `{result.get('duration_seconds', duration)}s`",
            f"Frames modele: `{metadata.get('frames', 'n/a')}`",
            f"Seed: `{result.get('seed', 'n/a')}`",
        ]
        if result.get("elapsed_seconds") is not None:
            details.append(f"Temps: `{result['elapsed_seconds']}s`")
        if result.get("bytes") is not None:
            details.append(f"Fichier: `{int(result['bytes']) / (1024 * 1024):.1f} MB`")

        prompt_preview = prompt if len(prompt) <= 900 else prompt[:897].rstrip() + "..."
        embed = create_embed(
            title=f"Video generee - {BRAND_NAME}",
            description=f"**Prompt**\n{prompt_preview}",
            color=COLOR_BLACK,
        )
        embed.add_field(name="Nextcloud", value=url or "Lien indisponible", inline=False)
        embed.add_field(name="ComfyUI", value="\n".join(details), inline=False)
        embed.set_footer(text=f"Demande par {interaction.user.display_name}")
        await self._send_public_update(interaction, embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VideoGenerationCog(bot))
