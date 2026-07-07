import asyncio
import os
import discord
from dotenv import load_dotenv

load_dotenv("/opt/skorm-bot/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
SERVER_ID = int(os.getenv("SERVER_ID", "0")) if os.getenv("SERVER_ID") else None

RENAMES = {
    "Coach Artistique": "Artistic Coach",
    "Coach Production": "Production Coach",
    "Coach DJ": "DJ Coach",
    "Coach Social Media": "Social Media Coach",
    "Formateur": "Trainer",
    "IA Musicale": "Musical AI",
}

async def rename_roles():
    intents = discord.Intents.all()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        guild = client.get_guild(SERVER_ID)
        if not guild:
            print("Guild not found")
            await client.close()
            return

        print("Server: {} (id={})".format(guild.name, guild.id))
        print()

        for old_name, new_name in RENAMES.items():
            role = discord.utils.get(guild.roles, name=old_name)
            if role is None:
                print("[SKIP] '{}' not found".format(old_name))
                continue
            try:
                await role.edit(name=new_name)
                print("[OK] '{}' -> '{}' (id={}, {} members)".format(old_name, new_name, role.id, len(role.members)))
            except Exception as e:
                print("[ERROR] '{}' -> '{}': {}".format(old_name, new_name, e))

        print()
        print("Done!")
        await client.close()

    await client.start(BOT_TOKEN)

asyncio.run(rename_roles())
