import json
import sys
import urllib.request

TOKEN = sys.argv[1]
GUILD_ID = sys.argv[2]

url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/commands"
req = urllib.request.Request(url, headers={
    "Authorization": f"Bot {TOKEN}",
    "Content-Type": "application/json"
})

try:
    with urllib.request.urlopen(req) as resp:
        commands = json.loads(resp.read().decode())
        print(f"Found {len(commands)} guild commands:")
        for cmd in commands:
            if cmd.get("options"):
                for opt in cmd["options"]:
                    sub = ", ".join(f'/{cmd["name"]} {s["name"]}' for s in opt.get("options", [opt]))
                    print(f'  /{cmd["name"]} {opt["name"]}: {opt.get("description", "")}')
            else:
                print(f'  /{cmd["name"]}: {cmd.get("description", "")}')
except Exception as e:
    print(f"Error: {e}")
