import json, time, urllib.request, urllib.parse, base64, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def base64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def get_token(sa_key, scopes):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    now = int(time.time())
    header = base64url(json.dumps({"alg":"RS256","typ":"JWT"}).encode())
    payload = base64url(json.dumps({
        "iss": sa_key["client_email"],
        "scope": scopes,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now, "exp": now + 3600
    }).encode())
    private_key = serialization.load_pem_private_key(sa_key["private_key"].encode(), password=None)
    sig = private_key.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{header}.{payload}.{base64url(sig)}"
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    try:
        resp = json.loads(urllib.request.urlopen(req, context=ctx).read())
        return resp["access_token"]
    except urllib.error.HTTPError as e:
        print("Token error:", e.read().decode())
        raise

def add_bot(token, space_id, name):
    url = f"https://chat.googleapis.com/v1/spaces/{space_id}/members"
    data = json.dumps({"member": {"name": "users/app", "type": "BOT"}}).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })
    try:
        resp = json.loads(urllib.request.urlopen(req, context=ctx).read())
        print(f"✓ {name}: added")
    except urllib.error.HTTPError as e:
        print(f"✗ {name}: {json.loads(e.read())}")

sa_key = json.load(open("/tmp/sa-key.json"))
token = get_token(sa_key, "https://www.googleapis.com/auth/chat.memberships.app")
print("Token OK")

rooms = {
    "12 S Main Stafford": "AAAA3s2JArA",
    "All Captains Chat":  "AAAAhO6H0_Y",
    "4 Channelview":      "AAAAayKiMyg",
}
for name, sid in rooms.items():
    add_bot(token, sid, name)
