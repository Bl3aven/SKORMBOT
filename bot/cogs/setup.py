"""
SKORMAgency - Server setup cog
Creates the full SKORM server structure: categories, channels, roles, permissions.

⚠️  Single-use cog. Running /setup a second time is safe (idempotent).
"""
import asyncio
import logging
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import (
    OWNER_ID, SERVER_ID,
    COLOR_WHITE, COLOR_GRAY, COLOR_DARK_GRAY, COLOR_MED_GRAY, COLOR_BLACK,
)
from bot.cogs.utils import create_embed, get_role_by_name, get_channel_by_name

log = logging.getLogger("skorm.setup")


# === Server structure definition ===

CATEGORIES = [
    {"name": "🌩️ SKORM", "position": 0},
    {"name": "──────────────", "position": 1},
    {"name": "🏠 Welcome & Community", "position": 2},
    {"name": "──────────────", "position": 3},
    {"name": "🎤 Artistes", "position": 10},
    {"name": "──────────────", "position": 11},
    {"name": "🤝 Agents", "position": 20},
    {"name": "──────────────", "position": 21},
    {"name": "🎓 Formations", "position": 30},
    {"name": "──────────────", "position": 31},
    {"name": "🔒 Staff", "position": 40},
    {"name": "──────────────", "position": 41},
    {"name": "📜 Logs", "position": 50},
]


CHANNELS_PER_CATEGORY = {
    "🏠 Welcome & Community": {
        "text": [
            ("📌│welcome", {"news": True}),
            ("📖│rules", {}),
            ("📢│announcements", {"news": True}),
            ("📰│news", {}),
            ("📅│events", {}),
            ("❓│faq", {}),
            ("🎫│support", {}),
            ("🎭│roles", {}),
            ("💬│general", {}),
            ("🎵│music", {}),
            ("📸│media", {}),
            ("😂│memes", {}),
            ("💡│ideas", {}),
            ("🤝│network", {}),
        ],
        "voice": ["🎙️│General", "☕│Chill", "🎶│Music", "🎮│Gaming"],
    },
    "🎤 Artistes": {
        "text": [
            ("📢│artist-announcements", {}),
            ("📅│planning", {}),
            ("🎯│goals", {}),
            ("📈│roadmap", {}),
            ("💬│artist-chat", {}),
            ("🆘│artist-help", {}),
            ("💡│brainstorm", {}),
            ("🤝│collaborations", {}),
            ("🎼│production", {}),
            ("🎹│sound-design", {}),
            ("🥁│drums", {}),
            ("🎛️│mixing", {}),
            ("🎚️│mastering", {}),
            ("🎵│track-feedback", {}),
            ("📂│project-sharing", {}),
            ("🎧│dj-performance", {}),
            ("🔥│sets", {}),
            ("🎬│recordings", {}),
            ("📱│social-media", {}),
            ("🎥│content-ideas", {}),
            ("📸│shootings", {}),
            ("📊│analytics", {}),
            ("📅│bookings", {}),
            ("📍│events", {}),
            ("✈️│travel", {}),
            ("📚│templates", {}),
            ("📂│downloads", {}),
            ("🧰│tools", {}),
        ],
        "voice": ["🎙️│Studio 1", "🎙️│Studio 2", "🎛️│Production", "🎧│DJ Practice", "🎓│Coaching", "💡│Brainstorm"],
    },
    "🤝 Agents": {
        "text": [
            ("📢│agent-announcements", {}),
            ("📅│planning", {}),
            ("📊│targets", {}),
            ("💬│agent-chat", {}),
            ("🤝│prospection", {}),
            ("📞│contacts", {}),
            ("🏢│clubs", {}),
            ("🎪│festivals", {}),
            ("🌍│international", {}),
            ("📋│artist-follow-up", {}),
            ("📈│reports", {}),
            ("📄│contracts", {}),
            ("💰│finance", {}),
            ("📂│documents", {}),
            ("📱│campaigns", {}),
            ("📊│statistics", {}),
            ("💡│strategy", {}),
        ],
        "voice": ["🎙️│Meeting", "📅│Booking", "🤝│Prospection", "👔│Direction", "💡│Brainstorm"],
    },
    "🎓 Formations": {
        "text": [
            ("📢│formation-announcements", {}),
            ("📅│calendar", {}),
            ("📚│course-roadmap", {}),
            ("💬│ia-chat", {}),
            ("📂│resources", {}),
            ("🎓│assignments", {}),
            ("❓│questions", {}),
            ("💬│suno-chat", {}),
            ("🎼│prompts", {}),
            ("🎵│feedback", {}),
            ("🎹│fl-studio", {}),
            ("🎛️│mixing", {}),
            ("🎚️│mastering", {}),
            ("🎼│composition", {}),
            ("📱│social-media", {}),
            ("🎥│content", {}),
            ("📈│growth", {}),
            ("📅│appointments", {}),
            ("🎤│live-classes", {}),
            ("🧠│mentoring", {}),
        ],
        "voice": ["🏫│Classroom 1", "🏫│Classroom 2", "🎓│Individual Coaching", "👥│Group Coaching", "❓│Questions / Answers"],
    },
    "🔒 Staff": {
        "text": [
            ("💬│staff-chat", {}),
            ("📢│staff-announcements", {}),
        ],
        "voice": [],
    },
    "📜 Logs": {
        "text": [
            ("📕│mod-logs", {"hidden": True}),
            ("📓│audit-logs", {"hidden": True}),
        ],
        "voice": [],
    },
}


# Roles defined top-down (highest privileges first)
ROLES = [
    # Direction
    {"name": "Founder", "color": COLOR_WHITE, "hoist": True, "mentionable": True},
    {"name": "CEO", "color": COLOR_WHITE, "hoist": True, "mentionable": True},
    {"name": "Creative Director", "color": COLOR_WHITE, "hoist": True, "mentionable": True},
    {"name": "Label Founder", "color": COLOR_WHITE, "hoist": True, "mentionable": True},
    {"name": "Admin", "color": COLOR_WHITE, "hoist": True, "mentionable": True},
    # Staff
    {"name": "Moderator", "color": COLOR_GRAY, "hoist": True, "mentionable": True},
    {"name": "Support", "color": COLOR_GRAY, "hoist": True, "mentionable": True},
    {"name": "Artistic Coach", "color": COLOR_GRAY, "hoist": True, "mentionable": True},
    {"name": "Production Coach", "color": COLOR_GRAY, "hoist": True, "mentionable": True},
    {"name": "DJ Coach", "color": COLOR_GRAY, "hoist": True, "mentionable": True},
    {"name": "Social Media Coach", "color": COLOR_GRAY, "hoist": True, "mentionable": True},
    {"name": "Trainer", "color": COLOR_GRAY, "hoist": True, "mentionable": True},
    # Membres
    {"name": "Artist", "color": COLOR_DARK_GRAY, "hoist": False, "mentionable": True},
    {"name": "Agent", "color": COLOR_DARK_GRAY, "hoist": False, "mentionable": True},
    {"name": "Student", "color": COLOR_DARK_GRAY, "hoist": False, "mentionable": True},
    {"name": "Student", "color": COLOR_DARK_GRAY, "hoist": False, "mentionable": True},
    {"name": "Verified Member", "color": COLOR_DARK_GRAY, "hoist": False, "mentionable": True},
    {"name": "Community", "color": COLOR_DARK_GRAY, "hoist": False, "mentionable": True},
    {"name": "Partner", "color": COLOR_DARK_GRAY, "hoist": False, "mentionable": True},
    # Formations
    {"name": "Musical AI", "color": COLOR_MED_GRAY, "hoist": False, "mentionable": True},
    {"name": "Suno", "color": COLOR_MED_GRAY, "hoist": False, "mentionable": True},
    {"name": "Production", "color": COLOR_MED_GRAY, "hoist": False, "mentionable": True},
    {"name": "DJ Performance", "color": COLOR_MED_GRAY, "hoist": False, "mentionable": True},
    {"name": "Social Media", "color": COLOR_MED_GRAY, "hoist": False, "mentionable": True},
    {"name": "Marketing", "color": COLOR_MED_GRAY, "hoist": False, "mentionable": True},
    # Système
    {"name": "Verified", "color": COLOR_BLACK, "hoist": False, "mentionable": False},
    {"name": "Ticket Admin", "color": COLOR_BLACK, "hoist": False, "mentionable": False},
]


DIRECTION_ROLES = {"Founder", "CEO", "Creative Director", "Label Founder", "Admin"}
STAFF_ROLES = {
    "Moderator", "Support",
    "Artistic Coach", "Production Coach", "DJ Coach", "Social Media Coach",
    "Trainer",
}
COACH_ROLES = {
    "Artistic Coach", "Production Coach", "DJ Coach", "Social Media Coach",
}
FORMATION_ROLES = {"IA Musicale", "Suno", "Production", "DJ Performance", "Social Media", "Marketing"}


# === Cog ===
class SetupCog(commands.Cog):
    """Single-use server bootstrapper."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if OWNER_ID is None:
            return False
        return ctx.author.id == OWNER_ID

    @app_commands.command(
        name="debug",
        description="Debug: lists all channels (owner only).",
    )
    async def debug_channels(self, interaction: discord.Interaction) -> None:
        if OWNER_ID and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ Owner only.", ephemeral=True
            )
            return
        guild = interaction.guild
        if guild is None:
            return
        lines = []
        for cat in guild.categories:
            lines.append(f"**{cat.name}**")
            for ch in cat.text_channels:
                lines.append(f"  📝 {ch.name}")
            for ch in cat.voice_channels:
                lines.append(f"  🔊 {ch.name}")
        for ch in guild.channels:
            if ch.category is None:
                lines.append(f"  📝 {ch.name} (no category)")
        await interaction.response.send_message(
            "\n".join(lines[:1000]), ephemeral=True
        )

    @app_commands.command(
        name="setup",
        description="Creates the entire SKORM structure (owner only).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(clean="Deletes old channels and orphan categories.")
    async def setup(
        self, interaction: discord.Interaction, clean: bool = False
    ) -> None:
        if OWNER_ID and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ This command is reserved for the bot owner.", ephemeral=True
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ This command must be run in a server.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        report: dict[str, list[str]] = {
            "categories": [], "text_channels": [], "voice_channels": [],
            "roles": [], "errors": [],
            "deleted_categories": [], "deleted_channels": [],
        }

        # 0. Cleanup old channels & categories (if requested)
        if clean:
            await interaction.edit_original_response(
                content="⏳ Cleaning old channels…"
            )
            await self._cleanup_old(guild, report)

        # 1. Roles (must be created before setting permission overwrites)
        await interaction.edit_original_response(
            content="⏳ Creating roles…"
        )
        created_roles = await self._create_roles(guild, report)

        # 2. Categories
        await interaction.edit_original_response(
            content="⏳ Creating categories…"
        )
        category_map = await self._create_categories(guild, report)

        # 3. Channels
        await interaction.edit_original_response(
            content="⏳ Creating channels…"
        )
        await self._create_channels(guild, category_map, report)

        # 4. Permissions
        await interaction.edit_original_response(
            content="⏳ Applying permissions…"
        )
        await self._apply_permissions(guild, category_map, created_roles)

        # 5. Hierarchy
        await interaction.edit_original_response(
            content="⏳ Applying hierarchy…"
        )
        await self._apply_role_hierarchy(guild, created_roles)

        # 6. Voice channel security
        await interaction.edit_original_response(
            content="⏳ Securing voice channels…"
        )
        voice_secured = await self._secure_voice_channels(guild, created_roles, report)

        # 7. Confirmation
        summary = (
            f"**Categories** : {len(report['categories'])}\n"
            f"**Text channels** : {len(report['text_channels'])}\n"
            f"**Voice channels** : {len(report['voice_channels'])}\n"
            f"**Roles** : {len(report['roles'])}\n"
            f"**🔒 Voice channels secured** : {voice_secured}\n"
        )
        if clean:
            summary += (
                f"**🗑️ Deleted categories** : {len(report['deleted_categories'])}\n"
                f"**🗑️ Deleted channels** : {len(report['deleted_channels'])}\n"
            )
        summary += f"**Errors** : {len(report['errors'])}"
        embed = create_embed(
            title="✅ SKORM setup complete",
            description=summary,
            color=0xFFFFFF,
        )
        if report["errors"]:
            error_list = "\n".join(f"• {e}" for e in report["errors"][:10])
            embed.add_field(name="⚠️ Errors", value=error_list[:1024], inline=False)
        await interaction.edit_original_response(content=None, embed=embed)

        # Send confirmation in the first available text channel of Accueil category
        welcome_channel = get_channel_by_name(guild, "│welcome")
        if welcome_channel is not None:
            try:
                await welcome_channel.send(embed=create_embed(
                    title="🌩️ SKORM server configured",
                    description=(
                        "**CREATE. CONNECT. DEVELOP.**\n\n"
                        "The SKORM server is now operational.\n"
                        "All channels, roles, and permissions are in place.\n\n"
                        "Read the rules and click the verification button "
                        "to access the server."
                    ),
                ))
            except Exception as exc:
                log.warning("Could not send welcome message: %s", exc)

    # --- Helpers ---

    async def _create_roles(
        self, guild: discord.Guild, report: dict
    ) -> dict[str, discord.Role]:
        """Create all SKORM roles and return a name -> role mapping."""
        role_map: dict[str, discord.Role] = {}

        # Existing roles (for idempotency)
        for role in guild.roles:
            role_map[role.name] = role

        for spec in ROLES:
            existing = get_role_by_name(guild, spec["name"])
            if existing:
                role_map[spec["name"]] = existing
                continue

            try:
                role = await guild.create_role(
                    name=spec["name"],
                    color=discord.Color(spec["color"]),
                    hoist=spec.get("hoist", False),
                    mentionable=spec.get("mentionable", False),
                    reason="SKORM setup",
                )
                role_map[spec["name"]] = role
                report["roles"].append(spec["name"])
                log.info("Created role %s", spec["name"])
                await asyncio.sleep(0.3)
            except Exception as exc:
                log.error("Failed to create role %s: %s", spec["name"], exc)
                report["errors"].append(f"role:{spec['name']}: {exc}")

        return role_map

    async def _create_categories(
        self, guild: discord.Guild, report: dict
    ) -> dict[str, discord.CategoryChannel]:
        """Create all categories and return a name -> category mapping."""
        category_map: dict[str, discord.CategoryChannel] = {}

        for existing in guild.categories:
            category_map[existing.name] = existing

        for spec in CATEGORIES:
            existing = next(
                (c for c in guild.categories if c.name == spec["name"]), None
            )
            if existing:
                category_map[spec["name"]] = existing
                continue
            try:
                category = await guild.create_category(
                    name=spec["name"],
                    position=spec["position"],
                    reason="SKORM setup",
                )
                category_map[spec["name"]] = category
                report["categories"].append(spec["name"])
                log.info("Created category %s", spec["name"])
                await asyncio.sleep(0.3)
            except Exception as exc:
                log.error("Failed to create category %s: %s", spec["name"], exc)
                report["errors"].append(f"category:{spec['name']}: {exc}")

        return category_map

    async def _create_channels(
        self,
        guild: discord.Guild,
        category_map: dict[str, discord.CategoryChannel],
        report: dict,
    ) -> None:
        """Create all text and voice channels."""
        for category_name, spec in CHANNELS_PER_CATEGORY.items():
            category = category_map.get(category_name)
            if category is None:
                report["errors"].append(f"missing category {category_name}")
                continue

            for channel_name, opts in spec.get("text", []):
                existing = next(
                    (
                        c for c in category.text_channels
                        if c.name == channel_name
                    ),
                    None,
                )
                if existing:
                    continue
                try:
                    overwrites = {}
                    if opts.get("hidden"):
                        # Hide from everyone, allow bot
                        bot_member = guild.me
                        overwrites[guild.default_role] = discord.PermissionOverwrite(
                            view_channel=False
                        )
                        if bot_member:
                            overwrites[bot_member] = discord.PermissionOverwrite(
                                view_channel=True, send_messages=True,
                                read_message_history=True,
                            )
                    kwargs = {
                        "name": channel_name,
                        "category": category,
                        "reason": "SKORM setup",
                    }
                    if opts.get("news"):
                        kwargs["news"] = True
                    if overwrites:
                        kwargs["overwrites"] = overwrites
                    await guild.create_text_channel(**kwargs)
                    report["text_channels"].append(f"{category_name}/{channel_name}")
                    await asyncio.sleep(0.3)
                except Exception as exc:
                    log.error("Failed to create text %s: %s", channel_name, exc)
                    report["errors"].append(f"text:{channel_name}: {exc}")

            for channel_name in spec.get("voice", []):
                existing = next(
                    (
                        c for c in category.voice_channels
                        if c.name == channel_name
                    ),
                    None,
                )
                if existing:
                    continue
                try:
                    await guild.create_voice_channel(
                        name=channel_name,
                        category=category,
                        reason="SKORM setup",
                    )
                    report["voice_channels"].append(f"{category_name}/{channel_name}")
                    await asyncio.sleep(0.3)
                except Exception as exc:
                    log.error("Failed to create voice %s: %s", channel_name, exc)
                    report["errors"].append(f"voice:{channel_name}: {exc}")

    async def _sync_category_channels(
        self,
        category: discord.CategoryChannel,
        overwrites: dict,
    ) -> None:
        """Apply category overwrites to all existing channels in the category."""
        synced = 0
        for channel in category.channels:
            try:
                # Merge category overwrites with channel-specific overwrites
                ch_overwrites = dict(overwrites)
                # Keep existing channel-specific overwrites that differ from category
                for target, overwrite in channel.overwrites.items():
                    if target not in ch_overwrites:
                        ch_overwrites[target] = overwrite
                await channel.edit(overwrites=ch_overwrites, reason="SKORM - sync category perms")
                synced += 1
                await asyncio.sleep(0.2)
            except Exception as exc:
                log.warning("Failed to sync perms for channel %s: %s", channel.name, exc)
        log.info("Synced %d/%d channels in category %s", synced, len(category.channels), category.name)

    async def _apply_permissions(
        self,
        guild: discord.Guild,
        category_map: dict[str, discord.CategoryChannel],
        role_map: dict[str, discord.Role],
    ) -> None:
        """Apply per-category permission overwrites using flexible name matching."""
        everyone = guild.default_role
        bot_member = guild.me

        def find_category(keyword: str) -> discord.CategoryChannel | None:
            """Find a category by keyword (case-insensitive)."""
            kw = keyword.lower()
            for cat in guild.categories:
                if kw in cat.name.lower():
                    return cat
            return None

        def allow_roles(*role_names: str) -> dict:
            ow = {everyone: discord.PermissionOverwrite(view_channel=False)}
            for n in role_names:
                if n in role_map:
                    ow[role_map[n]] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True,
                        read_message_history=True,
                    )
            if bot_member:
                ow[bot_member] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True,
                    read_message_history=True, manage_channels=True,
                )
            return ow

        # 🏠 Accueil & Communauté — hide from everyone, allow verified roles
        accueil = find_category("Accueil")
        if accueil:
            try:
                accueil_overwrites = {
                    everyone: discord.PermissionOverwrite(view_channel=False),
                    **{
                        role_map[n]: discord.PermissionOverwrite(
                            view_channel=True, send_messages=True,
                            read_message_history=True,
                        )
                        for n in (
                            list(DIRECTION_ROLES)
                            + list(STAFF_ROLES)
                            + ["Artist", "Agent", "Student",
                               "Verified", "Verified Member", "Community", "Partner"]
                        )
                        if n in role_map
                    },
                }
                await accueil.edit(overwrites=accueil_overwrites)
                await asyncio.sleep(0.3)

                # Sync to all existing channels
                await self._sync_category_channels(accueil, accueil_overwrites)

                # │rules is the ONLY channel visible to everyone (pre-verification)
                rules_channel = next(
                    (c for c in accueil.text_channels if "rules" in c.name.lower()),
                    None,
                )
                if rules_channel:
                    rules_overwrites = dict(accueil_overwrites)
                    rules_overwrites[everyone] = discord.PermissionOverwrite(view_channel=True, read_message_history=True)
                    await rules_channel.edit(
                        overwrites=rules_overwrites,
                        reason="SKORM - rules visible before verification",
                    )
                    await asyncio.sleep(0.3)
            except Exception as exc:
                log.error("Failed to set perms for Accueil: %s", exc)

        # 🎤 Artistes — Artist + Coach roles + Direction
        artistes = find_category("Artistes")
        if artistes:
            try:
                artist_roles = ["Artist"] + list(COACH_ROLES) + list(DIRECTION_ROLES)
                artist_overwrites = allow_roles(*artist_roles)
                await artistes.edit(overwrites=artist_overwrites)
                await asyncio.sleep(0.3)
                await self._sync_category_channels(artistes, artist_overwrites)
            except Exception as exc:
                log.error("Failed to set perms for Artistes: %s", exc)

        # 🤝 Agents — Agent + Direction
        agents = find_category("Agents")
        if agents:
            try:
                agent_roles = ["Agent"] + list(DIRECTION_ROLES)
                agent_overwrites = allow_roles(*agent_roles)
                await agents.edit(overwrites=agent_overwrites)
                await asyncio.sleep(0.3)
                await self._sync_category_channels(agents, agent_overwrites)
            except Exception as exc:
                log.error("Failed to set perms for Agents: %s", exc)

        # 🎓 Formations — Student + Formateur + Direction + formation roles
        formations = find_category("Formations")
        if formations:
            try:
                formation_allow = (
                    ["Student", "Formateur"]
                    + list(DIRECTION_ROLES)
                    + list(FORMATION_ROLES)
                )
                formation_overwrites = allow_roles(*formation_allow)
                await formations.edit(overwrites=formation_overwrites)
                await asyncio.sleep(0.3)
                await self._sync_category_channels(formations, formation_overwrites)
            except Exception as exc:
                log.error("Failed to set perms for Formations: %s", exc)

        # 🔒 Staff — Staff + Direction
        staff = find_category("Staff")
        if staff:
            try:
                staff_roles = list(STAFF_ROLES) + list(DIRECTION_ROLES)
                staff_overwrites = allow_roles(*staff_roles)
                await staff.edit(overwrites=staff_overwrites)
                await asyncio.sleep(0.3)
                await self._sync_category_channels(staff, staff_overwrites)
            except Exception as exc:
                log.error("Failed to set perms for Staff: %s", exc)

        # 📜 Logs — Bot only
        logs_cat = find_category("Logs")
        if logs_cat:
            try:
                ow = {everyone: discord.PermissionOverwrite(view_channel=False)}
                if bot_member:
                    ow[bot_member] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True,
                        read_message_history=True, manage_channels=True,
                    )
                # Allow Direction roles for moderation audits
                for r in DIRECTION_ROLES:
                    if r in role_map:
                        ow[role_map[r]] = discord.PermissionOverwrite(
                            view_channel=True, send_messages=False,
                            read_message_history=True,
                        )
                await logs_cat.edit(overwrites=ow)
                await asyncio.sleep(0.3)
                await self._sync_category_channels(logs_cat, ow)
            except Exception as exc:
                log.error("Failed to set perms for Logs: %s", exc)

    async def _apply_role_hierarchy(
        self,
        guild: discord.Guild,
        role_map: dict[str, discord.Role],
    ) -> None:
        """Position every role so the visual hierarchy matches the SKORM spec."""
        # Order from highest (top) to lowest (bottom): Founder first.
        ordered_names = [
            "Founder", "CEO", "Creative Director", "Label Founder", "Admin",
            "Moderator", "Support",
            "Coach Artistique", "Coach Production", "Coach DJ", "Coach Social Media",
            "Formateur",
            "Artist", "Agent", "Student", "Verified Member", "Community", "Partner",
            "IA Musicale", "Suno", "Production", "DJ Performance",
            "Social Media", "Marketing",
            "Verified", "Ticket Admin",
        ]

        # Discord API needs us to space positions to avoid conflicts
        # Use 1, 2, 3, ... then reorder once at the end.
        ordered_roles = [
            role_map[name] for name in ordered_names if name in role_map
        ]
        if not ordered_roles:
            return

        try:
            # Position so that index 0 has the highest position.
            # discord.py `edit` with position= places role at that index.
            # Use bulk position update via reverse.
            # Newer discord.py: use Role.edit(position=...)
            for index, role in enumerate(ordered_roles):
                try:
                    target_pos = len(ordered_roles) - index
                    await role.edit(position=target_pos, reason="SKORM hierarchy")
                    await asyncio.sleep(0.2)
                except Exception as exc:
                    log.warning("Failed to set position for %s: %s", role.name, exc)
        except Exception as exc:
            log.error("Hierarchy update failed: %s", exc)

    async def _secure_voice_channels(
        self,
        guild: discord.Guild,
        role_map: dict[str, discord.Role],
        report: dict,
    ) -> int:
        """Apply restrictive permissions to all voice channels for user roles."""
        DENY_PERMS = [
            "manage_channels", "manage_webhooks",
            "deafen_members", "move_members", "priority_speaker",
            "mention_everyone", "manage_messages",
        ]

        ADMIN_ROLES = DIRECTION_ROLES | STAFF_ROLES

        def deny_overwrite():
            ow = discord.PermissionOverwrite()
            for perm in DENY_PERMS:
                setattr(ow, perm, False)
            return ow

        secured = 0
        for voice_channel in guild.voice_channels:
            try:
                ow = {guild.default_role: deny_overwrite()}

                for role_name, role in role_map.items():
                    if role_name in ADMIN_ROLES or role.is_default():
                        continue
                    ow[role] = deny_overwrite()

                await voice_channel.edit(overwrites=ow, reason="SKORM voice security")
                secured += 1
                await asyncio.sleep(0.2)
            except Exception as exc:
                log.warning("Failed to secure voice channel %s: %s", voice_channel.name, exc)
                report["errors"].append(f"voice security:{voice_channel.name}: {exc}")

        log.info("Secured %d voice channel(s)", secured)
        return secured

    async def _cleanup_old(
        self, guild: discord.Guild, report: dict
    ) -> None:
        """Delete categories and channels that are no longer in the spec."""
        # Build set of expected category names
        expected_categories = {c["name"] for c in CATEGORIES}

        # Build set of expected channel names (all text + voice across all categories)
        expected_channels: set[str] = set()
        for cat_name, spec in CHANNELS_PER_CATEGORY.items():
            for channel_name, _ in spec.get("text", []):
                expected_channels.add(channel_name)
            for channel_name in spec.get("voice", []):
                expected_channels.add(channel_name)

        # Delete old channels first (channels inside categories we'll delete)
        for channel in list(guild.text_channels) + list(guild.voice_channels):
            if channel.name not in expected_channels:
                try:
                    await channel.delete(reason="SKORM cleanup - no longer in spec")
                    report["deleted_channels"].append(channel.name)
                    log.info("Deleted old channel %s", channel.name)
                    await asyncio.sleep(0.3)
                except Exception as exc:
                    log.warning("Failed to delete channel %s: %s", channel.name, exc)
                    report["errors"].append(f"delete channel:{channel.name}: {exc}")

        # Delete old categories (after channels are gone)
        for category in list(guild.categories):
            if category.name not in expected_categories:
                try:
                    await category.delete(reason="SKORM cleanup - no longer in spec")
                    report["deleted_categories"].append(category.name)
                    log.info("Deleted old category %s", category.name)
                    await asyncio.sleep(0.3)
                except Exception as exc:
                    log.warning("Failed to delete category %s: %s", category.name, exc)
                    report["errors"].append(f"delete category:{category.name}: {exc}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))