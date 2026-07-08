import asyncio
import os
import discord
from dotenv import load_dotenv

load_dotenv("/opt/skorm-bot/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
STAFF_CHANNEL_ID = 1523438113479983166  # 💬│staff-chat

async def send_tutorial():
    intents = discord.Intents.all()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        channel = client.get_channel(STAFF_CHANNEL_ID)
        if not channel:
            print("Channel not found")
            await client.close()
            return

        print("Sending formatting tutorial to {}...".format(channel.name))

        # Message 1: Text formatting
        await channel.send(embed=discord.Embed(
            title="📝 Discord Formatting Guide",
            description="Complete reference for all text formatting options in Discord.",
            color=0x5865F2
        ).add_field(
            name="**Bold**",
            value="Syntax: `**text**` or `__text__`\nPreview: **Bold text**",
            inline=False
        ).add_field(
            name="*Italic*",
            value="Syntax: `*text*` or `_text_`\nPreview: *Italic text*",
            inline=False
        ).add_field(
            name="***Bold Italic***",
            value="Syntax: `***text***` or `___text___`\nPreview: ***Bold & Italic***",
            inline=False
        ).add_field(
            name="~~Strikethrough~~",
            value="Syntax: `~~text~~`\nPreview: ~~Strikethrough~~",
            inline=False
        ).add_field(
            name="__Underline__",
            value="Syntax: `__text__` (in some clients)\nPreview: __Underline__",
            inline=False
        ).add_field(
            name="||Spoiler||",
            value="Syntax: `||text||`\nPreview: ||Spoiler text||",
            inline=False
        ).add_field(
            name="`Inline Code`",
            value="Syntax: `` `code` ``\nPreview: `print('hello')`",
            inline=False
        ).add_field(
            name="`Blockquote`",
            value="Syntax: `> text`\nPreview: > This is a quote",
            inline=False
        ),
        )

        # Message 2: Code blocks
        await channel.send("""```python
# Code blocks with syntax highlighting
def hello(name):
    return f"Hello, {name}!"

print(hello("World"))
```

```javascript
// JavaScript example
const greet = (name) => `Hello, ${name}!`;
console.log(greet("World"));
```

```yaml
# YAML example
server:
  name: SKORM
  members: 7
  tags:
    - CREATE
    - CONNECT
    - DEVELOP
```""")

        # Message 3: Lists and headers
        await channel.send("""## Headers (Markdown-style in some contexts)

### Unordered Lists
• Item one
• Item two
  • Nested item
  • Another nested
• Item three

### Numbered Lists
1. First step
2. Second step
3. Third step

### Task Lists (GitHub-style, not native Discord)
- [x] Completed task
- [ ] Pending task

---

### Horizontal Rules
You can create lines with `---`, `***`, or `___`

---""")

        # Message 4: Mentions and links
        await channel.send(embed=discord.Embed(
            title="🔗 Mentions & Links",
            color=0x5865F2
        ).add_field(
            name="User Mention",
            value="Syntax: `<@user_id>`\nExample: <@&1523407172514349097> mentions @everyone",
            inline=False
        ).add_field(
            name="Role Mention",
            value="Syntax: `<@&role_id>`\nExample: <@&1523421035091722263> mentions @Student",
            inline=False
        ).add_field(
            name="Channel Mention",
            value="Syntax: `<#channel_id>`\nExample: <#1524411795123605657> mentions 💬│general",
            inline=False
        ).add_field(
            name="Auto-Link",
            value="Just paste a URL:\nhttps://discord.com",
            inline=False
        ).add_field(
            name="Named Link",
            value="Syntax: `[text](url)`\nPreview: [Discord](https://discord.com)",
            inline=False
        ).add_field(
            name="Timestamp",
            value="Syntax: `<t:timestamp:style>`\nStyles: f=relative, F=long relative, t=time, T=long time, d=date, D=long date, D=date+time\n\nExamples:\n`<t:1751980800:f>` → <t:1751980800:f>\n`<t:1751980800:F>` → <t:1751980800:F>\n`<t:1751980800:t>` → <t:1751980800:t>\n`<t:1751980800:T>` → <t:1751980800:T>\n`<t:1751980800:d>` → <t:1751980800:d>\n`<t:1751980800:D>` → <t:1751980800:D>\n`<t:1751980800:R>` → <t:1751980800:R>",
            inline=False
        ))

        # Message 5: Embeds
        embed = discord.Embed(
            title="📦 Embed Example",
            description="This is an embed with rich formatting!",
            color=0x5865F2
        )
        embed.add_field(name="Field 1", value="Value 1", inline=True)
        embed.add_field(name="Field 2", value="Value 2", inline=True)
        embed.add_field(name="Field 3", value="Value 3", inline=True)
        embed.add_field(name="Long Field", value="This field spans the full width because inline=False.", inline=False)
        embed.set_author(name="SKORM Bot", url="https://discord.com")
        embed.set_footer(text="SKORM — CREATE. CONNECT. DEVELOP.")
        embed.set_thumbnail(url="https://cdn.discordapp.com/embed/avatars/0.png")

        await channel.send(content="### 📦 Embeds\nEmbeds are created via bot/API only (not in regular chat):\n", embed=embed)

        # Message 6: Emojis
        await channel.send("""### 😀 Emojis

**Built-in:** 😀 😃 😄 😁 😆 😅 🤣 😂 🙂 🙃 😉 😊 😇
**Custom:** Use `:emoji_name:` or paste directly
**Animated:** Use `:emoji_name:` for GIF emojis
**Custom emoji link:** `<a:name:id>` for animated, `<name:id>` for static

### 🎨 Colored Text (via code blocks)
Not natively supported, but you can simulate with:
- `||spoiler||` for hidden text
- Embeds with custom colors via bot

### 💡 Pro Tips
1. **Combine formats:** `**_bold italic_**`
2. **Nested quotes:** `> > Double quote`
3. **Code in quotes:** `> \`code in quote\``
4. **Multi-line code blocks:** Use triple backticks with language
5. **Timestamps:** Great for events and deadlines
6. **Spoilers:** Perfect for reveals and surprises""")

        print("Tutorial sent!")
        await client.close()

    await client.start(BOT_TOKEN)

asyncio.run(send_tutorial())
