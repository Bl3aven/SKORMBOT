import asyncio
import os
import discord
from dotenv import load_dotenv

load_dotenv("/opt/skorm-bot/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = 1523437878083059752  # 💬│general

async def purge():
    intents = discord.Intents.all()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            print("Channel not found")
            await client.close()
            return

        print("Purging: {} (id={})".format(channel.name, channel.id))
        deleted = 0
        errors = 0

        async for msg in channel.history(limit=None, oldest_first=False):
            if msg.system:
                continue
            try:
                await msg.delete()
                deleted += 1
                if deleted % 100 == 0:
                    print("  Deleted {} messages...".format(deleted))
                    await asyncio.sleep(1)  # rate limit
            except discord.Forbidden:
                errors += 1
                if errors <= 5:
                    print("  [FORBIDDEN] msg id={}".format(msg.id))
            except discord.HTTPException as e:
                errors += 1
                if errors <= 5:
                    print("  [HTTP] msg id={} - {}".format(msg.id, e))
                await asyncio.sleep(2)

        print()
        print("Done! Deleted: {}, Errors: {}".format(deleted, errors))
        await client.close()

    await client.start(BOT_TOKEN)

asyncio.run(purge())
