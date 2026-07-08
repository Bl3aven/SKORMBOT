import json
import sys
sys.path.insert(0, "/app")

from bot.main import bot

cmds = []
for cmd in bot.tree.walk_commands():
    parent_name = cmd.parent.name if cmd.parent else None
    cmds.append({
        "name": cmd.name,
        "parent": parent_name,
        "qualified": cmd.qualified_name
    })

print(json.dumps(cmds, indent=2))
print(f"\nTotal commands in tree: {len(cmds)}")
