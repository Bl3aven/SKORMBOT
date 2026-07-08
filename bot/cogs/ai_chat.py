"""
SKORMAgency - AI Chat cog
Connects to Oxee-flash for Discord server information queries.
"""
import asyncio
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.config import (
    OXEEGEN_API_ENDPOINT, OXEEGEN_API_KEY, OXEEGEN_MODEL,
    COLOR_WHITE, COLOR_GRAY,
)
from bot.cogs import db
from bot.cogs.utils import create_embed, check_staff_role

log = logging.getLogger("skorm.ai_chat")

SYSTEM_PROMPT = """You are SKORM Assistant, a READ-ONLY AI helper for the SKORM Discord server.

YOUR ROLE:
- Answer questions about the Discord server (members, roles, channels, rules, events, tickets, etc.)
- Help users navigate the server and understand its structure
- Provide information about server features and commands
- Give factual answers based on the server context provided

STRICT RESTRICTIONS - READ ONLY:
- You CANNOT modify, create, delete, or change ANYTHING on the Discord server
- You CANNOT change channels, roles, permissions, categories, or server settings
- You CANNOT execute commands or perform actions on the server
- You are a INFORMATION-ONLY assistant - you can only provide answers and information
- If a user asks you to do something (create, delete, modify, change), politely explain that you can only provide information
- Do NOT share confidential information (passwords, private DMs, personal data)
- If asked about something unrelated to the server, politely decline
- Keep responses concise and helpful

SERVER CONTEXT (Read-Only):
{context}

RESPONSE FORMAT:
- Use Discord markdown formatting
- Keep responses under 2000 characters
- Be friendly and professional
- If asked to perform an action, respond with: 'I can only provide information about the server. I cannot modify channels, roles, or settings. For changes, please contact a staff member with the appropriate permissions.'
"""


class AIChatCog(commands.Cog):
    """AI-powered chat for Discord server information."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.session = None

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession()

    async def cog_unload(self) -> None:
        if self.session:
            await self.session.close()

    def _build_context(self, guild: discord.Guild, member: discord.Member, is_staff: bool) -> str:
        """Build context string with server info for the AI."""
        now = asyncio.get_event_loop().time()
        from datetime import datetime
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        context = f"""Server: {guild.name} (ID: {guild.id})
Current time: {now_str}
Members: {guild.member_count}
Text channels: {len([c for c in guild.channels if isinstance(c, discord.TextChannel)])}
Voice channels: {len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])}
Categories: {len(guild.categories)}
Roles: {len(guild.roles)}

"""

        # Channel structure
        context += "CHANNEL STRUCTURE:\n"
        for cat in guild.categories:
            channels = [ch for ch in cat.channels if isinstance(ch, discord.TextChannel)]
            if channels:
                context += f"  {cat.name}:\n"
                for ch in channels[:10]:
                    context += f"    - {ch.name}\n"

        # Role structure
        context += "\nROLES:\n"
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True)[:20]:
            members_count = len(role.members)
            context += f"  - {role.name} ({members_count} members)\n"

        # Staff-only: member list
        if is_staff:
            context += "\nMEMBER LIST (Staff access):\n"
            for m in sorted(guild.members, key=lambda x: x.joined_at)[:50]:
                roles = ", ".join(r.name for r in m.roles if r.name != "@everyone")
                joined = m.joined_at.strftime("%Y-%m-%d") if m.joined_at else "unknown"
                context += f"  - {m.display_name} (joined: {joined}, roles: {roles})\n"

        return context

    async def call_oxeegen(self, user_message: str, context: str, user_id: int) -> str:
        """Call Oxeegen API with the user message and server context."""
        if not OXEEGEN_API_KEY:
            return "❌ AI service not configured (missing API key)."

        # Get recent chat history for context
        history = await db.get_chat_context(user_id)

        # Build messages array
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(context=context)}
        ]

        # Add recent history (oldest first)
        for entry in reversed(history):
            messages.append({"role": "user", "content": entry["message"]})
            messages.append({"role": "assistant", "content": entry["response"]})

        # Add current message
        messages.append({"role": "user", "content": user_message})

        url = f"{OXEEGEN_API_ENDPOINT}/chat/completions"
        headers = {
            "Authorization": f"Bearer {OXEEGEN_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": OXEEGEN_MODEL,
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0.7,
        }

        try:
            async with self.session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    error_text = await resp.text()
                    log.error(f"Oxeegen API error {resp.status}: {error_text}")
                    return f"❌ AI service error ({resp.status})."
        except asyncio.TimeoutError:
            return "❌ AI service timeout. Please try again."
        except Exception as e:
            log.error(f"Oxeegen API call failed: {e}")
            return f"❌ AI service error: {type(e).__name__}"

    @app_commands.command(name="chat", description="Ask questions about the Discord server")
    @app_commands.describe(question="Your question about the server")
    async def chat(self, interaction: discord.Interaction, question: str) -> None:
        """Chat with AI about the Discord server."""
        if not OXEEGEN_API_KEY:
            await interaction.response.send_message(
                "❌ AI service not configured.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=create_embed(
                title="⏳ Thinking...",
                description="Processing your question...",
                color=COLOR_GRAY,
            )
        )

        guild = interaction.guild
        member = interaction.user
        is_staff = check_staff_role(member)

        # Build context
        context = self._build_context(guild, member, is_staff)

        # Call AI
        response = await self.call_oxeegen(question, context, member.id)

        # Save to database
        try:
            await db.save_chat_entry(
                user_id=member.id,
                channel_id=interaction.channel_id,
                guild_id=guild.id,
                message=question,
                response=response,
                context_summary=f"Staff: {is_staff}, Members: {guild.member_count}"
            )
        except Exception as e:
            log.warning(f"Failed to save chat entry: {e}")

        # Send response
        response_text = response[:1900] + "..." if len(response) > 1900 else response

        await interaction.edit_original_response(
            embed=create_embed(
                title="🤖 SKORM Assistant",
                description=response_text,
                color=COLOR_WHITE,
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIChatCog(bot))
