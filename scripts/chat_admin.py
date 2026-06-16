"""Chat API helper using app authentication (service account).

Usage:
  python scripts/chat_admin.py list                 # list spaces the app is in
  python scripts/chat_admin.py post <space> <text>  # post a message to a space
  python scripts/chat_admin.py announce             # post TESTING notice to all app spaces
  python scripts/chat_admin.py join <space>         # try to add the app to a space

Requires /tmp/sa-key.json (service account key in the same GCP project as the
Chat app). The service account acts AS the Chat app for app authentication.
"""
import json, sys, time, base64, ssl, urllib.request, urllib.parse, urllib.error

ctx = ssl.create_default_context()
KEY_PATH = "/tmp/sa-key.json"

TESTING_NOTICE = (
    "\U0001F916 *NowAndForever Ops Bot — TESTING*\n"
    "This bot is currently in *testing*. Please *ignore it* and *do not interact* "
    "with it — anything it posts is test output, not official. "
    "We'll let you know when it's live. Thanks!"
)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def get_token(scopes: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    sa = json.load(open(KEY_PATH))
    now = int(time.time())
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps({
        "iss": sa["client_email"], "scope": scopes,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now, "exp": now + 3600,
    }).encode())
    pk = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = pk.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{header}.{payload}.{b64url(sig)}"
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt,
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    return json.loads(urllib.request.urlopen(req, context=ctx).read())["access_token"]


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    url = f"https://chat.googleapis.com/v1/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    try:
        return json.loads(urllib.request.urlopen(req, context=ctx).read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()}


def list_spaces(token: str) -> list[dict]:
    spaces, page = [], ""
    while True:
        path = "spaces?pageSize=200" + (f"&pageToken={page}" if page else "")
        res = api("GET", path, token)
        if "_error" in res:
            print("list error:", res); break
        spaces.extend(res.get("spaces", []))
        page = res.get("nextPageToken", "")
        if not page:
            break
    return spaces


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        token = get_token("https://www.googleapis.com/auth/chat.bot")
        spaces = list_spaces(token)
        print(f"App is a member of {len(spaces)} space(s):")
        for s in spaces:
            print(f"  {s.get('name')}  type={s.get('spaceType', s.get('type'))}  name={s.get('displayName','(dm)')}")
    elif cmd == "post":
        token = get_token("https://www.googleapis.com/auth/chat.bot")
        space, text = sys.argv[2], sys.argv[3]
        print(api("POST", f"{space}/messages", token, {"text": text}))
    elif cmd == "announce":
        token = get_token("https://www.googleapis.com/auth/chat.bot")
        only_spaces = [s for s in list_spaces(token) if (s.get("spaceType") or s.get("type")) in ("SPACE", "GROUP_CHAT", "ROOM")]
        print(f"Announcing to {len(only_spaces)} room(s)...")
        for s in only_spaces:
            r = api("POST", f"{s['name']}/messages", token, {"text": TESTING_NOTICE})
            ok = "_error" not in r
            print(f"  {'OK ' if ok else 'FAIL'} {s.get('displayName')} ({s['name']}) {'' if ok else r}")
    elif cmd == "join":
        token = get_token("https://www.googleapis.com/auth/chat.memberships.app")
        space = sys.argv[2]
        print(api("POST", f"{space}/members", token, {"member": {"name": "users/app", "type": "BOT"}}))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
