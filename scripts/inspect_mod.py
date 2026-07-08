import sys
sys.path.insert(0, "/app")
from bot.cogs.moderation import ModerationCog

mg = ModerationCog.mod_group
print("mod_group commands:")
for cmd in mg.walk_commands():
    cb = cmd.callback
    print(f"  {cmd.name} -> {cb.__qualname__}")

print(f"\nTotal: {len(list(mg.walk_commands()))}")
