import sys
import asyncio

sys.path.insert(0, "/app")

from bot.main import bot, load_cogs

async def main():
    await load_cogs()
    cmds = list(bot.tree.walk_commands())
    print(f"Total commands in loaded bot.tree: {len(cmds)}")
    for cmd in cmds:
        parent = cmd.parent.name if cmd.parent else None
        print(f"/{cmd.qualified_name} parent={parent} type={type(cmd).__name__}")
    mod = bot.tree.get_command('mod')
    if mod:
        print('\n/mod children:')
        for child in mod.walk_commands():
            print(f"  {child.name}: {child.description}")
    else:
        print('\n/mod not found')

asyncio.run(main())
