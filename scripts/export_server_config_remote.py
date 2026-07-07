import asyncio
import json
import os
from datetime import datetime
import discord
from dotenv import load_dotenv

load_dotenv("/opt/skorm-bot/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
SERVER_ID = int(os.getenv("SERVER_ID", "0")) if os.getenv("SERVER_ID") else None

def role_to_dict(role):
    return {
        "id": role.id, "name": role.name,
        "color": "#{:06X}".format(role.color.value),
        "hoist": role.hoist, "mentionable": role.mentionable,
        "position": role.position, "permissions": str(role.permissions),
        "members": len(role.members),
    }

def channel_to_dict(channel):
    base = {
        "id": channel.id, "name": channel.name, "type": channel.type.name,
        "position": channel.position,
        "topic": getattr(channel, "topic", None),
        "nsfw": getattr(channel, "nsfw", False),
        "slowmode_delay": getattr(channel, "slowmode_delay", 0),
        "bitrate": getattr(channel, "bitrate", None),
        "user_limit": getattr(channel, "user_limit", None),
    }
    overwrites = []
    for target, ow in channel.overwrites.items():
        entry = {"type": "role" if isinstance(target, discord.Role) else "member", "id": target.id, "name": target.name if hasattr(target, "name") else str(target)}
        for perm in ["view_channel","send_messages","read_message_history","connect","speak","add_reactions","attach_files","embed_links","manage_channels","manage_messages","kick_members","ban_members","administrator","change_nickname","manage_roles","manage_nicknames","use_external_emojis","priority_speaker","use_vad","request_to_speak"]:
            val = getattr(ow, perm, None)
            if val is not None:
                entry[perm] = val
        overwrites.append(entry)
    base["overwrites"] = overwrites
    return base

async def export():
    intents = discord.Intents.all()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        guild = client.get_guild(SERVER_ID)
        if not guild:
            print("Guild not found")
            await client.close()
            return
        print("Exporting: {} (id={})".format(guild.name, guild.id))

        roles = [role_to_dict(r) for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)]

        categories = []
        for cat in sorted(guild.categories, key=lambda c: c.position):
            ce = {"id": cat.id, "name": cat.name, "position": cat.position, "text_channels": [], "voice_channels": []}
            for ch in sorted(cat.text_channels, key=lambda c: c.position):
                ce["text_channels"].append(channel_to_dict(ch))
            for ch in sorted(cat.voice_channels, key=lambda c: c.position):
                ce["voice_channels"].append(channel_to_dict(ch))
            categories.append(ce)

        orphan = []
        for ch in guild.channels:
            if ch.category is None and isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
                orphan.append(channel_to_dict(ch))

        member_count = len(guild.members)
        bot_count = sum(1 for m in guild.members if m.bot)
        emojis = [{"id": e.id, "name": e.name, "animated": e.animated, "available": e.available} for e in guild.emojis]

        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        data = {
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "guild": {"id": guild.id, "name": guild.name, "owner_id": guild.owner_id, "created_at": guild.created_at.isoformat(), "member_count": member_count, "bot_count": bot_count, "human_count": member_count - bot_count, "verification_level": guild.verification_level.name, "premium_tier": guild.premium_tier, "premium_subscription_count": guild.premium_subscription_count},
            "roles": roles, "categories": categories, "orphan_channels": orphan, "emojis": emojis,
        }

        print("===JSON_START===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print("===JSON_END===")

        print()
        print("===MARKDOWN_START===")
        print("# SKORM Discord Server - Configuration Export")
        print()
        print("**Exported:** {}".format(now_str))
        print("**Server:** {} (id={})".format(guild.name, guild.id))
        print()
        print("## Summary")
        print()
        print("| Metric | Value |")
        print("|--------|-------|")
        print("| Members | {} ({} humans, {} bots) |".format(member_count, member_count - bot_count, bot_count))
        print("| Roles | {} |".format(len(roles)))
        print("| Categories | {} |".format(len(categories)))
        print("| Orphan Channels | {} |".format(len(orphan)))
        print("| Emojis | {} |".format(len(emojis)))
        print()
        print("## Roles (hierarchy)")
        print()
        print("| Position | Name | Color | Hoist | Mentionable | Members |")
        print("|----------|------|-------|-------|-------------|---------|")
        for r in roles:
            h = "YES" if r["hoist"] else "no"
            m = "YES" if r["mentionable"] else "no"
            print("| {} | {} | {} | {} | {} | {} |".format(r["position"], r["name"], r["color"], h, m, r["members"]))
        print()
        print("## Categories & Channels")
        print()
        for cat in categories:
            print("### {} (pos={})".format(cat["name"], cat["position"]))
            print()
            if cat["text_channels"]:
                print("**Text Channels:**")
                print()
                print("| Position | Name | ID | Overwrites |")
                print("|----------|------|----|------------|")
                for ch in cat["text_channels"]:
                    print("| {} | {} | {} | {} |".format(ch["position"], ch["name"], ch["id"], len(ch["overwrites"])))
                print()
            if cat["voice_channels"]:
                print("**Voice Channels:**")
                print()
                print("| Position | Name | ID | Bitrate | User Limit | Overwrites |")
                print("|----------|------|----|---------|------------|------------|")
                for ch in cat["voice_channels"]:
                    br = ch["bitrate"] or "default"
                    ul = ch["user_limit"] or "unlimited"
                    print("| {} | {} | {} | {} | {} | {} |".format(ch["position"], ch["name"], ch["id"], br, ul, len(ch["overwrites"])))
                print()
        if orphan:
            print("### Orphan Channels (no category)")
            print()
            for ch in orphan:
                print("- {} ({})".format(ch["name"], ch["type"]))
            print()
        print("===MARKDOWN_END===")
        await client.close()

    await client.start(BOT_TOKEN)

asyncio.run(export())
