import asyncio
import os
import discord
from dotenv import load_dotenv

load_dotenv("/opt/skorm-bot/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CATEGORY_ID = 1523437854943084565  # 🔒 ------- Staff

async def create_voice():
    intents = discord.Intents.all()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        guild = client.guilds[0]
        print("Server: {} (id={})".format(guild.name, guild.id))

        category = guild.get_channel(CATEGORY_ID)
        if not category:
            print("Category {} not found".format(CATEGORY_ID))
            await client.close()
            return
        print("Category: {} (id={})".format(category.name, category.id))

        print("Creating 🖥️│Le bureau voice channel...")
        try:
            vc = await guild.create_voice_channel(
                name="🖥️│Le bureau",
                category=category,
                overwrites={},  # synced to category
                reason="Staff voice channel"
            )
            print("  Created: {} (id={})".format(vc.name, vc.id))
        except Exception as e:
            print("  Error: {}".format(e))

        await client.close()

    await client.start(BOT_TOKEN)

asyncio.run(create_voice())
