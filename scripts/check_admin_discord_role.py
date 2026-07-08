import sys
sys.path.insert(0, "/app")
from bot.config import BOT_TOKEN, SERVER_ID
import urllib.request, json

if not BOT_TOKEN or not SERVER_ID:
    print('BOT_TOKEN or SERVER_ID missing')
    sys.exit(1)

url = f"https://discord.com/api/v10/guilds/{SERVER_ID}/roles"
req = urllib.request.Request(url, headers={"Authorization": f"Bot {BOT_TOKEN}", "User-Agent": "skorm-bot-check/1.0"})
try:
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
except Exception as e:
    print('Error fetching roles:', e)
    sys.exit(1)

found = [r for r in data if r.get('name') == 'AdminDiscord']
if not found:
    print('AdminDiscord role NOT found')
    for r in data[:20]:
        print('-', r.get('name'))
    sys.exit(2)
print('AdminDiscord role found:')
print(found[0])
