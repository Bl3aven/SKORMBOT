"""
Export full Discord server configuration: categories, channels, roles, permissions.
Outputs a structured JSON file and a human-readable Markdown report.
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("export")

BOT_TOKEN = os.getenv("BOT_TOKEN")
SERVER_ID = int(os.getenv("SERVER_ID", "0")) if os.getenv("SERVER_ID") else None


def role_to_dict(role: discord.Role) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "color": f"#{role.color.value:06X}",
        "hoist": role.hoist,
        "mentionable": role.mentionable,
        "position": role.position,
        "permissions": str(role.permissions),
        "members": len(role.members),
    }


def channel_to_dict(channel: discord.abc.GuildChannel) -> dict:
    base = {
        "id": channel.id,
        "name": channel.name,
        "type": channel.type.name,
        "position": channel.position,
        "topic": getattr(channel, "topic", None),
        "nsfw": getattr(channel, "nsfw", False),
        "slowmode_delay": getattr(channel, "slowmode_delay", 0),
        "bitrate": getattr(channel, "bitrate", None),
        "user_limit": getattr(channel, "user_limit", None),
        "rtc_region": getattr(channel, "rtc_region", None),
    }
    # Permissions overwrites
    overwrites = []
    for target, ow in channel.overwrites.items():
        entry = {
            "type": "role" if isinstance(target, discord.Role) else "member",
            "id": target.id,
            "name": target.name if hasattr(target, "name") else str(target),
        }
        if ow.view_channel is not None:
            entry["view_channel"] = ow.view_channel
        if ow.send_messages is not None:
            entry["send_messages"] = ow.send_messages
        if ow.read_message_history is not None:
            entry["read_message_history"] = ow.read_message_history
        if ow.connect is not None:
            entry["connect"] = ow.connect
        if ow.speak is not None:
            entry["speak"] = ow.speak
        if ow.add_reactions is not None:
            entry["add_reactions"] = ow.add_reactions
        if ow.attach_files is not None:
            entry["attach_files"] = ow.attach_files
        if ow.embed_links is not None:
            entry["embed_links"] = ow.embed_links
        if ow.manage_channels is not None:
            entry["manage_channels"] = ow.manage_channels
        if ow.manage_messages is not None:
            entry["manage_messages"] = ow.manage_messages
        if ow.kick_members is not None:
            entry["kick_members"] = ow.kick_members
        if ow.ban_members is not None:
            entry["ban_members"] = ow.ban_members
        if ow.administrator is not None:
            entry["administrator"] = ow.administrator
        if ow.change_nickname is not None:
            entry["change_nickname"] = ow.change_nickname
        if ow.manage_roles is not None:
            entry["manage_roles"] = ow.manage_roles
        if ow.manage_nicknames is not None:
            entry["manage_nicknames"] = ow.manage_nicknames
        if ow.use_external_emojis is not None:
            entry["use_external_emojis"] = ow.use_external_emojis
        if ow.priority_speaker is not None:
            entry["priority_speaker"] = ow.priority_speaker
        if ow.use_vad is not None:
            entry["use_vad"] = ow.use_vad
        if ow.request_to_speak is not None:
            entry["request_to_speak"] = ow.request_to_speak
        overwrites.append(entry)
    base["overwrites"] = overwrites
    return base


async def export() -> None:
    if not BOT_TOKEN or not SERVER_ID:
        log.error("BOT_TOKEN or SERVER_ID not set in .env")
        return

    intents = discord.Intents.all()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        guild = client.get_guild(SERVER_ID)
        if not guild:
            log.error("Guild not found")
            await client.close()
            return

        log.info("Exporting guild: %s (id=%s)", guild.name, guild.id)

        # === Roles ===
        roles = []
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            roles.append(role_to_dict(role))

        # === Categories + Channels ===
        categories = []
        orphan_channels = []

        for category in sorted(guild.categories, key=lambda c: c.position):
            cat_entry = {
                "id": category.id,
                "name": category.name,
                "position": category.position,
                "text_channels": [],
                "voice_channels": [],
            }
            for ch in sorted(category.text_channels, key=lambda c: c.position):
                cat_entry["text_channels"].append(channel_to_dict(ch))
            for ch in sorted(category.voice_channels, key=lambda c: c.position):
                cat_entry["voice_channels"].append(channel_to_dict(ch))
            categories.append(cat_entry)

        # Orphan channels (no category)
        for ch in guild.channels:
            if ch.category is None and isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                orphan_channels.append(channel_to_dict(ch))

        # === Members summary ===
        member_count = len(guild.members)
        bot_count = sum(1 for m in guild.members if m.bot)
        human_count = member_count - bot_count

        # === Emojis ===
        emojis = [
            {"id": e.id, "name": e.name, "animated": e.animated, "available": e.available}
            for e in guild.emojis
        ]

        # === Stickers ===
        stickers = [
            {"id": s.id, "name": s.name, "type": s.type.name, "format_type": s.format_type.name}
            for s in guild.stickers
        ]

        # === Build export ===
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        export_data = {
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "guild": {
                "id": guild.id,
                "name": guild.name,
                "owner_id": guild.owner_id,
                "created_at": guild.created_at.isoformat(),
                "member_count": member_count,
                "bot_count": bot_count,
                "human_count": human_count,
                "verification_level": guild.verification_level.name,
                "explicit_content_filter": guild.explicit_content_filter.name,
                "default_message_notifications": guild.default_message_notifications.name,
                "mf_level": guild.mfa_level.name,
                "system_channel_id": guild.system_channel_id,
                "rules_channel_id": guild.rules_channel_id,
                "public_updates_channel_id": guild.public_updates_channel_id,
                "premium_tier": guild.premium_tier,
                "premium_subscription_count": guild.premium_subscription_count,
            },
            "roles": roles,
            "categories": categories,
            "orphan_channels": orphan_channels,
            "emojis": emojis,
            "stickers": stickers,
        }

        # Write JSON
        output_dir = Path(__file__).parent.parent.parent / "backups" / "discord-export"
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / f"skorm-server-{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        log.info("JSON exported: %s", json_path)

        # Write Markdown report
        md_path = output_dir / f"skorm-server-{timestamp}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# SKORM Discord Server — Configuration Export\n\n")
            f.write(f"**Exported:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n")
            f.write(f"**Server:** {guild.name} (id={guild.id})\n\n")

            f.write("## Summary\n\n")
            f.write(f"| Metric | Value |\n")
            f.write(f"|--------|-------|\n")
            f.write(f"| Members | {member_count} ({human_count} humans, {bot_count} bots) |\n")
            f.write(f"| Roles | {len(roles)} |\n")
            f.write(f"| Categories | {len(categories)} |\n")
            f.write(f"| Orphan Channels | {len(orphan_channels)} |\n")
            f.write(f"| Emojis | {len(emojis)} |\n")
            f.write(f"| Stickers | {len(stickers)} |\n\n")

            f.write("## Roles (hierarchy)\n\n")
            f.write("| Position | Name | Color | Hoist | Mentionable | Members |\n")
            f.write("|----------|------|-------|-------|-------------|---------|\n")
            for r in roles:
                f.write(
                    f"| {r['position']} | {r['name']} | {r['color']} "
                    f"| {'✅' if r['hoist'] else '❌'} "
                    f"| {'✅' if r['mentionable'] else '❌'} "
                    f"| {r['members']} |\n"
                )
            f.write("\n")

            f.write("## Categories & Channels\n\n")
            for cat in categories:
                f.write(f"### {cat['name']} (pos={cat['position']})\n\n")
                if cat["text_channels"]:
                    f.write("**Text Channels:**\n\n")
                    f.write("| Position | Name | ID | Overwrites |\n")
                    f.write("|----------|------|----|------------|\n")
                    for ch in cat["text_channels"]:
                        f.write(
                            f"| {ch['position']} | {ch['name']} "
                            f"| `{ch['id']}` | {len(ch['overwrites'])} |\n"
                        )
                    f.write("\n")
                if cat["voice_channels"]:
                    f.write("**Voice Channels:**\n\n")
                    f.write("| Position | Name | ID | Bitrate | User Limit | Overwrites |\n")
                    f.write("|----------|------|----|---------|------------|------------|\n")
                    for ch in cat["voice_channels"]:
                        f.write(
                            f"| {ch['position']} | {ch['name']} "
                            f"| `{ch['id']}` "
                            f"| {ch['bitrate'] or 'default'} "
                            f"| {ch['user_limit'] or '∞'} "
                            f"| {len(ch['overwrites'])} |\n"
                        )
                    f.write("\n")

            if orphan_channels:
                f.write("### Orphan Channels (no category)\n\n")
                f.write("| Name | Type | ID |\n")
                f.write("|------|------|----|\n")
                for ch in orphan_channels:
                    f.write(f"| {ch['name']} | {ch['type']} | `{ch['id']}` |\n")
                f.write("\n")

            if emojis:
                f.write("## Custom Emojis\n\n")
                f.write("| Name | ID | Animated |\n")
                f.write("|------|----|----------|\n")
                for e in emojis:
                    f.write(
                        f"| {':' + e['name'] + ':'} "
                        f"| `{e['id']}` "
                        f"| {'🔄' if e['animated'] else '🖼️'} |\n"
                    )
                f.write("\n")

        log.info("Markdown report: %s", md_path)
        log.info("✅ Export complete!")
        await client.close()

    await client.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(export())
