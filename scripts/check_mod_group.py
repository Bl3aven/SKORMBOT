import json
import sys
sys.path.insert(0, "/app")

# Import the cog class to inspect mod_group
from bot.cogs.moderation import ModerationCog

mod_group = ModerationCog.mod_group
print(f"mod_group name: {mod_group.name}")
print(f"mod_group commands: {[c.name for c in mod_group.walk_commands()]}")
print(f"mod_group command count: {len(list(mod_group.walk_commands()))}")

# Check all commands in the group
for cmd in mod_group.walk_commands():
    print(f"  - {cmd.name}: {cmd.description}")

# Also check cleanchat specifically
print("\n--- Checking cleanchat ---")
cleanchat_cmd = mod_group.get_command("cleanchat")
if cleanchat_cmd:
    print(f"cleanchat found: {cleanchat_cmd.name}")
    print(f"  qualified_name: {cleanchat_cmd.qualified_name}")
    print(f"  callback: {cleanchat_cmd.callback}")
else:
    print("cleanchat NOT FOUND in mod_group!")
