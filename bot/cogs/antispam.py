"""
SKORMAgency - Anti-spam cog
Tracks message rates, join rates and mass-mentions; applies timeouts when needed.
"""
import logging
import time
from collections import defaultdict, deque
from typing import Deque

import discord
from discord.ext import commands

from bot.cogs.utils import create_embed, get_channel_by_name, check_staff_role

log = logging.getLogger("skorm.antispam")


class AntiSpamCog(commands.Cog):
    """Anti-spam, anti-raid, anti-mass-mention."""

    # === Tunables ===
    MESSAGE_LIMIT = 5            # messages
    MESSAGE_WINDOW = 3.0         # seconds
    MESSAGE_TIMEOUT_SECONDS = 300  # 5 minutes

    JOIN_LIMIT = 10              # joins
    JOIN_WINDOW = 60.0           # seconds

    MENTION_LIMIT = 3            # @everyone/@here mentions
    MENTION_WINDOW = 10.0        # seconds

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # user_id -> deque[float] of message timestamps
        self._messages: dict[int, Deque[float]] = defaultdict(deque)
        # join timestamps in last JOIN_WINDOW (shared list)
        self._joins: Deque[float] = deque()

    # --- Helpers ---
    def _prune(self, queue: Deque[float], window: float) -> None:
        cutoff = time.time() - window
        while queue and queue[0] < cutoff:
            queue.popleft()

    async def _warn_staff(
        self, guild: discord.Guild, embed: discord.Embed
    ) -> None:
        """Send a warning embed to mod-logs."""
        target = get_channel_by_name(guild, "mod-logs")
        if target is None:
            return
        try:
            await target.send(embed=embed)
        except Exception as exc:
            log.error("Failed to warn staff: %s", exc)

    # --- Events ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        # Don't moderate staff
        if isinstance(message.author, discord.Member) and check_staff_role(message.author):
            return
        # Skip DMs / system messages
        if message.channel.id == message.guild.id:
            return

        now = time.time()
        user_id = message.author.id
        queue = self._messages[user_id]
        queue.append(now)
        self._prune(queue, self.MESSAGE_WINDOW)

        # --- Mass mention spam ---
        mass_mentions = (
            message.mention_everyone
            + sum(1 for m in message.role_mentions if m.name == "@everyone")
            + message.content.count("@here")
        )
        if mass_mentions > 0:
            mention_queue = self._messages.get(f"mention:{user_id}", deque())
            mention_queue.append(now)
            self._messages[f"mention:{user_id}"] = mention_queue
            self._prune(mention_queue, self.MENTION_WINDOW)
            if len(mention_queue) > self.MENTION_LIMIT:
                try:
                    await message.delete()
                except Exception:
                    pass
                await self._warn_staff(
                    message.guild,
                    create_embed(
                        title="⚠️ Spam de mentions massives",
                        description=(
                            f"**Membre** : {message.author.mention} (`{user_id}`)\n"
                            f"**Salon** : {message.channel.mention}\n"
                            f"Plus de {self.MENTION_LIMIT} mentions "
                            f"@everyone/@here en {self.MENTION_WINDOW:.0f}s."
                        ),
                    ),
                )
                try:
                    await message.author.send(
                        embed=create_embed(
                            title="⛔ Mention Spam",
                            description=(
                                "Mass mentions (@everyone/@here) are "
                                "limited. Try again later."
                            ),
                        )
                    )
                except Exception:
                    pass

        # --- Message rate ---
        if len(queue) > self.MESSAGE_LIMIT:
            try:
                await message.author.timeout(
                    discord.utils.utcnow() + discord.timedelta(
                        seconds=self.MESSAGE_TIMEOUT_SECONDS
                    ),
                    reason="SKORM anti-spam",
                )
            except discord.Forbidden:
                pass
            except Exception as exc:
                log.error("Timeout failed: %s", exc)

            await self._warn_staff(
                message.guild,
                create_embed(
                    title="🚨 Anti-spam triggered",
                    description=(
                        f"**Member** : {message.author.mention} (`{user_id}`)\n"
                        f"**Channel** : {message.channel.mention}\n"
                        f"{self.MESSAGE_TIMEOUT_SECONDS // 60} min timeout applied.\n"
                        f"{len(queue)} messages in {self.MESSAGE_WINDOW:.0f}s."
                    ),
                ),
            )
            queue.clear()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        now = time.time()
        self._joins.append(now)
        self._prune(self._joins, self.JOIN_WINDOW)
        if len(self._joins) > self.JOIN_LIMIT:
            await self._warn_staff(
                member.guild,
                create_embed(
                    title="⚠️ Join spike detected",
                    description=(
                        f"{len(self._joins)} joins in {self.JOIN_WINDOW:.0f}s.\n"
                        "Monitor new arrivals and enable verification mode "
                        "if needed."
                    ),
                ),
            )
            # Reset the counter so we don't spam every join after the spike
            self._joins.clear()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AntiSpamCog(bot))