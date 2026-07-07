"""
SKORMAgency - Common utilities
Helper functions used across all cogs.
"""
from datetime import timedelta

import discord

from bot.config import (
    COLOR_BLACK,
    EMBED_COLOR,
    FOOTER_TEXT,
    BRAND_NAME,
)


# === Embed helper ===
def create_embed(
    title: str = None,
    description: str = None,
    color: int = EMBED_COLOR,
    fields: list = None,
    image: str = None,
    thumbnail: str = None,
    footer: str = FOOTER_TEXT,
) -> discord.Embed:
    """Create a SKORM-branded Discord embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
    )
    if fields:
        for name, value, *inline in fields:
            embed.add_field(name=name, value=value, inline=bool(inline and inline[0]))
    if image:
        embed.set_image(url=image)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if footer:
        embed.set_footer(text=footer)
    return embed


# === Duration formatting ===
def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable string (e.g. '2h 30m 15s')."""
    if seconds <= 0:
        return "0s"
    delta = timedelta(seconds=int(seconds))
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def parse_duration(duration_str: str) -> int:
    """Parse a human duration string (e.g. '1h', '30m', '2d') to seconds.

    Supports both compact ('1h', '30m') and verbose ('30 minutes') formats.
    Returns None when the format is invalid.
    """
    if not duration_str:
        return None

    s = duration_str.strip().lower()

    units = {
        "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
        "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
        "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
        "d": 86400, "day": 86400, "days": 86400,
        "w": 604800, "week": 604800, "weeks": 604800,
    }

    import re
    total = 0
    matched = False
    pattern = re.compile(r"(\d+)\s*([a-z]+)")
    for match in pattern.finditer(s):
        value = int(match.group(1))
        unit = match.group(2)
        if unit in units:
            total += value * units[unit]
            matched = True
        else:
            return None
    return total if matched else None


# === Role / channel lookup ===
def get_role_by_name(guild: discord.Guild, name: str) -> discord.Role | None:
    """Get a role by name (case-insensitive)."""
    target = name.casefold()
    for role in guild.roles:
        if role.name.casefold() == target:
            return role
    return None


def get_channel_by_name(guild: discord.Guild, name: str) -> discord.TextChannel | discord.VoiceChannel | None:
    """Get a channel by name.

    Tries exact match first, then falls back to partial match on the last
    word of the channel name (e.g. "🎭│roles" matches "roles").
    """
    target = name.casefold()

    # 1. Exact match
    for channel in guild.channels:
        if channel.name.casefold() == target:
            return channel

    # 2. Partial match — extract the key word (last segment after │, ・, or space)
    key = target.split("│")[-1].split("・")[-1].split()[-1] if target else target
    if not key:
        return None

    for channel in guild.channels:
        ch_key = channel.name.casefold().split("│")[-1].split("・")[-1].split()[-1]
        if ch_key == key:
            return channel

    return None


# === Permission helpers ===
DIRECTION_ROLES = {"Founder", "CEO", "Creative Director", "Label Founder", "Admin"}
STAFF_ROLES = {
    "Moderator", "Support",
    "Artistic Coach", "Production Coach", "DJ Coach", "Social Media Coach",
    "Trainer",
}


def check_admin_role(member: discord.Member) -> bool:
    """Check if a member has any Direction role."""
    if member is None:
        return False
    if member.guild_permissions.administrator:
        return True
    member_role_names = {r.name for r in member.roles}
    return bool(DIRECTION_ROLES & member_role_names)


def check_staff_role(member: discord.Member) -> bool:
    """Check if a member has any Staff role or higher."""
    if check_admin_role(member):
        return True
    if member is None:
        return False
    member_role_names = {r.name for r in member.roles}
    return bool(STAFF_ROLES & member_role_names)