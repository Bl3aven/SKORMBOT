import sys
sys.path.insert(0, "/app")
from bot.main import bot

cmds = list(bot.tree.walk_commands())
print(f"Total commands in bot.tree: {len(cmds)}")
for cmd in cmds:
    parent = cmd.parent.name if cmd.parent else "None"
    print(f"  /{cmd.qualified_name} (parent: {parent})")
