import asyncio
import os
import discord
from dotenv import load_dotenv

load_dotenv("/opt/skorm-bot/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CATEGORY_ID = 1523437845480739046
OLD_CHANNEL_ID = 1523437878083059752  # old 💬│general

async def recreate_general():
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

        # Delete old channel if it exists
        old = guild.get_channel(OLD_CHANNEL_ID)
        if old:
            print("Deleting old channel: {} (id={})".format(old.name, old.id))
            try:
                await old.delete(reason="Recreating with synced permissions")
                print("  Deleted.")
            except Exception as e:
                print("  Error deleting: {}".format(e))

        # Create new channel with synced permissions (empty overwrites = synced to category)
        print("Creating new 💬│general in category...")
        try:
            new_channel = await guild.create_text_channel(
                name="💬│general",
                category=category,
                overwrites={},  # empty = synced to category
                reason="Recreated with synced permissions"
            )
            print("  Created: {} (id={})".format(new_channel.name, new_channel.id))
            print("  Overwrites: {} (synced to category)".format(len(new_channel.overwrites)))
        except Exception as e:
            print("  Error creating: {}".format(e))

        await client.close()

    await client.start(BOT_TOKEN)

asyncio.run(recreate_general())
