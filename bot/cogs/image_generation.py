"""
SKORMAgency - ComfyUI image generation cog.

Provides /createimage, backed by the MOODBEAST image endpoint which starts
ComfyUI through the GPU switcher and returns an OpenAI-compatible b64 image.
"""
import asyncio
import base64
import io
import logging
import re
from typing import Any, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.config import (
    BRAND_NAME,
    COLOR_BLACK,
    COLOR_GRAY,
    COLOR_WHITE,
    COMFYUI_IMAGE_API_ENDPOINT,
    COMFYUI_IMAGE_API_KEY,
    COMFYUI_IMAGE_CFG,
    COMFYUI_IMAGE_EDIT_DENOISE,
    COMFYUI_IMAGE_EDIT_MAX_BYTES,
    COMFYUI_IMAGE_EDIT_SIZE,
    COMFYUI_IMAGE_MODEL,
    COMFYUI_IMAGE_NEGATIVE_PROMPT,
    COMFYUI_IMAGE_PROMPT_ENHANCE_ENABLED,
    COMFYUI_IMAGE_QUALITY,
    COMFYUI_IMAGE_SIZE,
    COMFYUI_IMAGE_STEPS,
    COMFYUI_IMAGE_TIMEOUT_SECONDS,
    OXEEGEN_API_ENDPOINT,
    OXEEGEN_API_KEY,
    OXEEGEN_MODEL,
)
from bot.cogs.utils import create_embed

log = logging.getLogger("skorm.image_generation")


class ImageGenerationError(RuntimeError):
    """Raised when ComfyUI image generation fails."""


class ImageGenerationCog(commands.Cog):
    """Generate images through the ComfyUI-backed MOODBEAST API."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self._generation_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        timeout = aiohttp.ClientTimeout(total=COMFYUI_IMAGE_TIMEOUT_SECONDS)
        self.session = aiohttp.ClientSession(timeout=timeout)

    async def cog_unload(self) -> None:
        if self.session:
            await self.session.close()

    @staticmethod
    def _images_url(kind: str = "generations") -> str:
        base = COMFYUI_IMAGE_API_ENDPOINT.rstrip("/")
        return f"{base}/images/{kind}"

    @staticmethod
    def _normalize_quality(quality: str | None) -> str:
        raw = (quality or COMFYUI_IMAGE_QUALITY or "standard").strip().lower()
        aliases = {
            "rapide": "fast",
            "fast": "fast",
            "standard": "standard",
            "qualite": "quality",
            "qualité": "quality",
            "quality": "quality",
        }
        if raw not in aliases:
            raise ImageGenerationError("Qualite invalide. Utilise rapide, standard ou qualite.")
        return aliases[raw]

    @staticmethod
    def _validate_attachment(image: discord.Attachment) -> None:
        content_type = (image.content_type or "").lower()
        filename = (image.filename or "").lower()
        allowed_extensions = (".png", ".jpg", ".jpeg", ".webp")
        if content_type and not content_type.startswith("image/"):
            raise ImageGenerationError("Le fichier fourni n'est pas une image.")
        if not filename.endswith(allowed_extensions):
            raise ImageGenerationError("Format image non supporte. Utilise PNG, JPG, JPEG ou WEBP.")
        if image.size and image.size > COMFYUI_IMAGE_EDIT_MAX_BYTES:
            max_mb = COMFYUI_IMAGE_EDIT_MAX_BYTES / (1024 * 1024)
            raise ImageGenerationError(f"Image trop lourde. Limite actuelle : {max_mb:.0f} MB.")

    async def _read_attachment(self, image: discord.Attachment) -> tuple[bytes, str, str]:
        self._validate_attachment(image)
        try:
            image_bytes = await image.read()
        except discord.HTTPException as exc:
            raise ImageGenerationError("Impossible de lire l'image Discord.") from exc

        if not image_bytes:
            raise ImageGenerationError("Image fournie vide.")
        if len(image_bytes) > COMFYUI_IMAGE_EDIT_MAX_BYTES:
            max_mb = COMFYUI_IMAGE_EDIT_MAX_BYTES / (1024 * 1024)
            raise ImageGenerationError(f"Image trop lourde. Limite actuelle : {max_mb:.0f} MB.")

        return image_bytes, image.filename or "image.png", image.content_type or "image/png"

    @staticmethod
    def _fallback_image_prompt(prompt: str, *, editing: bool) -> str:
        normalized = prompt.strip()
        replacements = {
            r"\bmodifie(?:s|r)?\b": "edit",
            r"\bmodifier\b": "edit",
            r"\bajoute(?:r|s)?\b": "add",
            r"\brajoute(?:r|s)?\b": "add",
            r"\bsupprime(?:r|s)?\b": "remove",
            r"\benleve(?:r|s)?\b": "remove",
            r"\benlève(?:r|s)?\b": "remove",
            r"\bsoleil\b": "sun",
            r"\barriere[- ]plan\b": "background",
            r"\barrière[- ]plan\b": "background",
            r"\bfond\b": "background",
            r"\bciel\b": "sky",
            r"\bderriere\b": "behind",
            r"\bderrière\b": "behind",
            r"\bdroite\b": "right",
            r"\bgauche\b": "left",
        }
        for pattern, replacement in replacements.items():
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)

        lower = prompt.lower()
        if "soleil" in lower or "sun" in lower:
            normalized = (
                "add a clearly visible warm golden sun disk in the background behind the subject, "
                "with subtle natural rim light"
            )

        if editing:
            return (
                "Realistic image edit. Preserve the original subject, face, identity, pose, outfit, "
                "composition, lighting and style. Only apply this requested change: "
                f"{normalized}"
            )
        return f"High quality image, {normalized}"

    async def _prepare_prompt(self, prompt: str, *, editing: bool) -> str:
        if not self.session or not COMFYUI_IMAGE_PROMPT_ENHANCE_ENABLED or not OXEEGEN_API_KEY:
            return self._fallback_image_prompt(prompt, editing=editing)

        mode = "image editing" if editing else "text-to-image generation"
        system_prompt = (
            "Rewrite the user's request as a concise English Stable Diffusion prompt for "
            f"{mode}. Return only the final prompt, no markdown. "
            "If the user writes French, translate it. "
            "For image editing, preserve the original subject, face, identity, pose, outfit, "
            "composition, lighting and style unless the user explicitly asks to change them. "
            "Make the requested change clear and visually concrete."
        )
        payload = {
            "model": OXEEGEN_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 180,
        }
        headers = {
            "Authorization": f"Bearer {OXEEGEN_API_KEY}",
            "Content-Type": "application/json",
        }
        url = f"{OXEEGEN_API_ENDPOINT.rstrip('/')}/chat/completions"

        try:
            timeout = aiohttp.ClientTimeout(total=45)
            async with self.session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    log.warning("Prompt enhancement failed status=%s body=%s", resp.status, body[:400])
                    return self._fallback_image_prompt(prompt, editing=editing)
                data = await resp.json()
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            log.warning("Prompt enhancement unavailable: %s", type(exc).__name__)
            return self._fallback_image_prompt(prompt, editing=editing)

        try:
            enhanced = str(data["choices"][0]["message"]["content"]).strip().strip('"')
        except Exception:
            log.warning("Prompt enhancement returned invalid response: %s", data)
            return self._fallback_image_prompt(prompt, editing=editing)

        if not enhanced or enhanced.lower() in {"none", "null", "n/a", "na"}:
            return self._fallback_image_prompt(prompt, editing=editing)
        return enhanced[:1200]

    async def _request_image_api(
        self,
        *,
        prompt: str,
        quality: str,
        image: discord.Attachment | None = None,
        denoise: float | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        if not self.session:
            raise ImageGenerationError("Session HTTP non initialisee.")
        if not COMFYUI_IMAGE_API_ENDPOINT:
            raise ImageGenerationError("Endpoint ComfyUI non configure.")
        if not COMFYUI_IMAGE_API_KEY:
            raise ImageGenerationError("Cle API image manquante.")

        headers = {
            "Authorization": f"Bearer {COMFYUI_IMAGE_API_KEY}",
            "User-Agent": "SKORMBOT/1.0 (+https://tournayre.ovh)",
        }

        try:
            if image:
                image_bytes, filename, content_type = await self._read_attachment(image)
                form = aiohttp.FormData()
                form.add_field("model", COMFYUI_IMAGE_MODEL)
                form.add_field("prompt", prompt)
                form.add_field("quality", quality)
                form.add_field("n", "1")
                form.add_field("size", COMFYUI_IMAGE_EDIT_SIZE)
                form.add_field("response_format", "b64_json")
                if denoise is not None:
                    form.add_field("denoise", str(denoise))
                form.add_field("negative_prompt", COMFYUI_IMAGE_NEGATIVE_PROMPT)
                form.add_field("image", image_bytes, filename=filename, content_type=content_type)
                request_kwargs = {"data": form}
                url = self._images_url("edits")
            else:
                payload: dict[str, Any] = {
                    "model": COMFYUI_IMAGE_MODEL,
                    "prompt": prompt,
                    "quality": quality,
                    "n": 1,
                    "response_format": "b64_json",
                    "negative_prompt": COMFYUI_IMAGE_NEGATIVE_PROMPT,
                }
                request_kwargs = {"json": payload, "headers": {**headers, "Content-Type": "application/json"}}
                url = self._images_url("generations")

            if image:
                request_kwargs["headers"] = headers

            async with self.session.post(url, **request_kwargs) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    log.error("ComfyUI image API error %d: %s", resp.status, body[:1000])
                    raise ImageGenerationError(f"API image indisponible ({resp.status}).")

                data = await resp.json()
        except asyncio.TimeoutError as exc:
            raise ImageGenerationError("Generation trop longue ou timeout ComfyUI.") from exc
        except aiohttp.ClientError as exc:
            raise ImageGenerationError(f"Connexion impossible a l'API image: {type(exc).__name__}") from exc

        try:
            item = data["data"][0]
            image_b64 = item["b64_json"]
            image_bytes = base64.b64decode(image_b64, validate=True)
        except Exception as exc:
            log.error("Invalid ComfyUI image response: %s", data)
            raise ImageGenerationError("Reponse image invalide.") from exc

        if not image_bytes:
            raise ImageGenerationError("Image vide retournee par ComfyUI.")

        metadata = data.get("metadata") or {}
        if item.get("revised_prompt"):
            metadata["prompt_used"] = item["revised_prompt"]
        return image_bytes, metadata

    @app_commands.command(name="createimage", description="Cree une image avec ComfyUI")
    @app_commands.describe(
        prompt="Description detaillee de l'image a generer ou modifier",
        image="Image optionnelle a modifier avec le prompt",
        force="Force de modification pour une image, de 0.1 a 1.0",
        qualite="Profil de rendu: standard par defaut, rapide pour SD 1.5, qualite pour le meilleur profil valide",
    )
    @app_commands.choices(
        qualite=[
            app_commands.Choice(name="standard", value="standard"),
            app_commands.Choice(name="rapide", value="rapide"),
            app_commands.Choice(name="qualite", value="qualite"),
        ]
    )
    async def createimage(
        self,
        interaction: discord.Interaction,
        prompt: str,
        image: Optional[discord.Attachment] = None,
        force: Optional[float] = None,
        qualite: Optional[str] = None,
    ) -> None:
        """Generate or edit an image from a prompt using ComfyUI."""
        prompt = (prompt or "").strip()
        if not prompt:
            await interaction.response.send_message("Prompt vide.", ephemeral=True)
            return

        if len(prompt) > 1200:
            await interaction.response.send_message(
                "Prompt trop long. Limite actuelle : 1200 caracteres.",
                ephemeral=True,
            )
            return

        if self._generation_lock.locked():
            await interaction.response.send_message(
                "Une generation image est deja en cours. Reessaie dans quelques instants.",
                ephemeral=True,
            )
            return

        if force is not None and not 0.1 <= force <= 1.0:
            await interaction.response.send_message(
                "Force invalide. Utilise une valeur entre 0.1 et 1.0.",
                ephemeral=True,
            )
            return

        try:
            quality = self._normalize_quality(qualite)
        except ImageGenerationError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        mode = "edition" if image else "generation"

        async with self._generation_lock:
            log.info(
                "Image %s requested by %s (%s): prompt_chars=%d attachment=%s quality=%s",
                mode,
                interaction.user,
                interaction.user.id,
                len(prompt),
                bool(image),
                quality,
            )
            try:
                api_prompt = await self._prepare_prompt(prompt, editing=bool(image))
                image_bytes, metadata = await self._request_image_api(
                    prompt=api_prompt,
                    quality=quality,
                    image=image,
                    denoise=force,
                )
            except ImageGenerationError as exc:
                await interaction.followup.send(
                    embed=create_embed(
                        title="Image non generee",
                        description=str(exc),
                        color=COLOR_GRAY,
                    )
                )
                return
            except Exception as exc:
                log.exception("Unexpected image generation error")
                await interaction.followup.send(
                    embed=create_embed(
                        title="Erreur image",
                        description=f"Erreur inattendue : `{type(exc).__name__}`.",
                        color=COLOR_GRAY,
                    )
                )
                return

        filename = "skorm-comfyui-edit.png" if image else "skorm-comfyui.png"
        file = discord.File(io.BytesIO(image_bytes), filename=filename)
        metadata_lines = [
            f"Modele: `{metadata.get('model') or COMFYUI_IMAGE_MODEL}`",
            f"Profil: `{metadata.get('profile') or quality}`",
            f"Workflow: `{metadata.get('workflow', 'n/a')}`",
            f"Checkpoint: `{metadata.get('checkpoint', 'n/a')}`",
            f"Taille: `{metadata.get('size') or COMFYUI_IMAGE_SIZE}`",
            f"Steps: `{metadata.get('steps') or COMFYUI_IMAGE_STEPS}`",
            f"Mode: `{'edition' if image else 'generation'}`",
            f"Seed: `{metadata.get('seed', 'n/a')}`",
        ]
        if metadata.get("elapsed_seconds") is not None:
            metadata_lines.append(f"Temps: `{metadata['elapsed_seconds']}s`")
        if image:
            metadata_lines.append(f"Denoise: `{metadata.get('denoise', COMFYUI_IMAGE_EDIT_DENOISE)}`")
            if metadata.get("source_size"):
                metadata_lines.append(f"Source: `{metadata['source_size']}`")
        prompt_preview = prompt if len(prompt) <= 900 else prompt[:897].rstrip() + "..."

        embed = create_embed(
            title=f"Image {'modifiee' if image else 'generee'} - {BRAND_NAME}",
            description=f"**Prompt**\n{prompt_preview}",
            color=COLOR_BLACK,
        )
        if image:
            embed.add_field(name="Source", value=f"`{image.filename}`", inline=False)
        prompt_used = str(metadata.get("prompt_used") or "").strip()
        if prompt_used and prompt_used.lower() != prompt.lower():
            prompt_used_preview = prompt_used if len(prompt_used) <= 600 else prompt_used[:597].rstrip() + "..."
            embed.add_field(name="Prompt optimise", value=prompt_used_preview, inline=False)
        embed.add_field(name="ComfyUI", value="\n".join(metadata_lines), inline=False)
        embed.set_image(url=f"attachment://{filename}")
        embed.set_footer(text=f"Demande par {interaction.user.display_name}")

        await interaction.followup.send(embed=embed, file=file)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ImageGenerationCog(bot))
