import sys
sys.path.insert(0, "/app")
from bot.config import BOT_TOKEN, SERVER_ID
import urllib.request, json

if not BOT_TOKEN or not SERVER_ID:
    print('BOT_TOKEN or SERVER_ID missing')
    sys.exit(1)

def req(url):
    r = urllib.request.Request(url, headers={"Authorization": f"Bot {BOT_TOKEN}", "User-Agent": "skorm-bot-check/1.0"})
    with urllib.request.urlopen(r) as resp:
        return json.load(resp)

try:
    me = req('https://discord.com/api/v10/users/@me')
    app_id = me['id']
    print('Application id:', app_id)
    cmds = req(f'https://discord.com/api/v10/applications/{app_id}/guilds/{SERVER_ID}/commands')
except Exception as e:
    print('Error fetching commands:', e)
    sys.exit(1)

print(f'Found {len(cmds)} guild commands:')
for c in cmds:
    print('-', c.get('name'), '(id=', c.get('id'), ')')
    if c.get('options'):
        for o in c['options']:
            print('   option:', o.get('name'), 'type', o.get('type'))
    if c.get('type'):
        print('   type:', c.get('type'))
