import sys
sys.path.insert(0, "/app")
from bot.config import BOT_TOKEN, SERVER_ID
import urllib.request, json

if not BOT_TOKEN or not SERVER_ID:
    print('BOT_TOKEN or SERVER_ID missing in bot.config')
    sys.exit(1)

headers = {
    'Authorization': f'Bot {BOT_TOKEN}',
    'Content-Type': 'application/json',
    'User-Agent': 'skorm-bot/1.0'
}

def request(method, path, data=None):
    url = f'https://discord.com/api/v10{path}'
    body = None
    if data is not None:
        body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req) as resp:
        if resp.status == 204:
            return None
        return json.load(resp)

try:
    app = request('GET', '/oauth2/applications/@me')
    app_id = app.get('id')
    print('Application id:', app_id)
    print('Clearing guild commands...')
    request('PUT', f'/applications/{app_id}/guilds/{SERVER_ID}/commands', [])
    print('Guild commands cleared.')
except Exception as e:
    print('Error:', e)
    sys.exit(1)
