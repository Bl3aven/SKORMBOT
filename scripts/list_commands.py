import asyncio
import os
import discord
from dotenv import load_dotenv

load_dotenv("/opt/skorm-bot/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
SERVER_ID = int(os.getenv("SERVER_ID", "0")) if os.getenv("SERVER_ID") else None

async def list_commands():
    intents = discord.Intents.all()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        guild = client.get_guild(SERVER_ID)
        if not guild:
            print("Guild not found")
            await client.close()
            return

        # Get guild commands
        commands = await guild.fetch_commands()
        print("Slash commands in {} ({} total):".format(guild.name, len(commands)))
        for cmd in commands:
            print("  /{} (id={})".format(cmd.name, cmd.id))
        
        # Check if user has Admin role
        user = guild.get_member(220252773659181079)
        if user:
            print("\nUser: {} (id={})".format(user.display_name, user.id))
            print("Roles:")
            for role in user.roles:
                print("  - {} (id={}, pos={})".format(role.name, role.id, role.position))
            has_admin = any(r.name == "Admin" for r in user.roles)
            print("Has Admin role: {}".format(has_admin))
        else:
            print("\nUser 220252773659181079 not found in guild")

        await client.close()

    await client.start(BOT_TOKEN)

asyncio.run(list_commands())
