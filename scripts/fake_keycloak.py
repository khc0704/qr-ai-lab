"""A tiny stand-in for Keycloak (OIDC authorization-code + PKCE, RS256 JWKS, refresh, userinfo, end-session)
so the Keycloak integration can be exercised end to end without the company server.

    python fake_keycloak.py --port 8089 --realm qr --client qr-ai-lab --secret dev-secret

Users (any password): superadmin → realm role "superadmin"; admin → "admin"; user → no role; alice → "qr-admin" client role.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import secrets
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

USERS = {
    "superadmin": {"name": "系統管理員（Keycloak）", "email": "superadmin@corp.example", "realm": ["superadmin"], "client": []},
    "admin": {"name": "管理員（Keycloak）", "email": "admin@corp.example", "realm": ["admin"], "client": []},
    "user": {"name": "一般使用者（Keycloak）", "email": "user@corp.example", "realm": ["offline_access"], "client": []},
    "alice": {"name": "Alice Chen", "email": "alice@corp.example", "realm": [], "client": ["qr-admin"]},
}
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
KID = "fake-kc-" + secrets.token_hex(4)
CODES: dict[str, dict] = {}
REFRESH: dict[str, dict] = {}


def b64url(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Server(ThreadingHTTPServer):
    allow_reuse_address = True


def make_handler(issuer: str, client_id: str, client_secret: str, access_ttl: int):
    pub = KEY.public_key().public_numbers()
    jwks = {"keys": [{"kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256", "n": b64url(pub.n), "e": b64url(pub.e)}]}
    base = "/realms/" + issuer.rsplit("/realms/", 1)[1]

    def tokens(username: str, nonce: str | None) -> dict:
        u = USERS[username]
        now = int(time.time())
        sub = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{username}.fake-keycloak"))
        access = {
            "iss": issuer,
            "sub": sub,
            "aud": "account",
            "azp": client_id,
            "typ": "Bearer",
            "iat": now,
            "exp": now + access_ttl,
            "jti": str(uuid.uuid4()),
            "scope": "openid profile email",
            "preferred_username": username,
            "name": u["name"],
            "email": u["email"],
            "email_verified": True,
            "realm_access": {"roles": u["realm"]},
            "resource_access": {client_id: {"roles": u["client"]}} if u["client"] else {},
        }
        idt = {
            "iss": issuer,
            "sub": sub,
            "aud": client_id,
            "azp": client_id,
            "typ": "ID",
            "iat": now,
            "auth_time": now,
            "exp": now + access_ttl,
            "preferred_username": username,
            "name": u["name"],
            "email": u["email"],
            "email_verified": True,
        }
        if nonce:
            idt["nonce"] = nonce
        hdr = {"kid": KID}
        rt = secrets.token_urlsafe(32)
        REFRESH[rt] = {"username": username, "nonce": nonce}
        return {
            "access_token": jwt.encode(access, PEM, algorithm="RS256", headers=hdr),
            "id_token": jwt.encode(idt, PEM, algorithm="RS256", headers=hdr),
            "refresh_token": rt,
            "token_type": "Bearer",
            "expires_in": access_ttl,
            "refresh_expires_in": 1800,
            "scope": "openid profile email",
            "session_state": str(uuid.uuid4()),
        }

    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: D401
            print(f"[fake-keycloak] {self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}", flush=True)

        def _json(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _html(self, body: str, code: int = 200) -> None:
            data = body.encode()
            self.send_response(code)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, url: str) -> None:
            self.send_response(302)
            self.send_header("location", url)
            self.send_header("content-length", "0")
            self.end_headers()

        def _form(self) -> dict[str, str]:
            n = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(n).decode() if n else ""
            return {k: v[0] for k, v in parse_qs(raw).items()}

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == f"{base}/.well-known/openid-configuration":
                return self._json(
                    200,
                    {
                        "issuer": issuer,
                        "authorization_endpoint": f"{issuer}/protocol/openid-connect/auth",
                        "token_endpoint": f"{issuer}/protocol/openid-connect/token",
                        "userinfo_endpoint": f"{issuer}/protocol/openid-connect/userinfo",
                        "jwks_uri": f"{issuer}/protocol/openid-connect/certs",
                        "end_session_endpoint": f"{issuer}/protocol/openid-connect/logout",
                        "response_types_supported": ["code"],
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "subject_types_supported": ["public"],
                        "id_token_signing_alg_values_supported": ["RS256"],
                        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                        "code_challenge_methods_supported": ["S256", "plain"],
                        "scopes_supported": ["openid", "profile", "email"],
                        "claims_supported": ["sub", "iss", "name", "preferred_username", "email"],
                    },
                )
            if url.path == f"{base}/protocol/openid-connect/certs":
                return self._json(200, jwks)
            if url.path == f"{base}/protocol/openid-connect/auth":
                hidden = "".join(
                    f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
                    for k, v in q.items()
                )
                opts = "".join(f'<option value="{u}">{u} — {html.escape(USERS[u]["name"])}</option>' for u in USERS)
                return self._html(
                    f"""<!doctype html><html lang="zh-TW"><head><meta charset="utf-8"><title>Fake Keycloak · 登入</title>
<style>body{{font-family:system-ui,sans-serif;background:#f3f4f6;margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center}}
.card{{background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);padding:32px;width:360px}}
h1{{font-size:18px;margin:0 0 4px}} p{{color:#6b7280;font-size:13px;margin:0 0 20px}}
label{{display:block;font-size:13px;margin:12px 0 4px}} select,input{{width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;box-sizing:border-box}}
button{{margin-top:20px;width:100%;padding:10px;border:0;border-radius:8px;background:#1f2937;color:#fff;font-size:14px;cursor:pointer}}</style></head>
<body><form class="card" method="post"><h1>公司單一登入（模擬 Keycloak）</h1><p>realm {html.escape(base.split('/')[-1])} · client {html.escape(q.get('client_id',''))}</p>
{hidden}<label for="username">帳號</label><select id="username" name="username">{opts}</select>
<label for="password">密碼</label><input id="password" name="password" type="password" value="x">
<button type="submit">登入</button></form></body></html>"""
                )
            if url.path == f"{base}/protocol/openid-connect/userinfo":
                auth = self.headers.get("authorization", "")
                try:
                    claims = jwt.decode(auth.split(" ", 1)[1], KEY.public_key(), algorithms=["RS256"], audience="account")
                except Exception as e:
                    return self._json(401, {"error": "invalid_token", "error_description": str(e)})
                return self._json(200, {k: claims[k] for k in ("sub", "preferred_username", "name", "email", "email_verified")})
            if url.path == f"{base}/protocol/openid-connect/logout":
                target = q.get("post_logout_redirect_uri") or q.get("redirect_uri")
                if target:
                    return self._redirect(target)
                return self._html("<p>已登出（fake Keycloak）</p>")
            return self._json(404, {"error": "not_found", "path": url.path})

        def do_POST(self):
            url = urlparse(self.path)
            form = self._form()
            if url.path == f"{base}/protocol/openid-connect/auth":
                username = form.get("username", "")
                if username not in USERS:
                    return self._html("<p>unknown user</p>", 400)
                code = secrets.token_urlsafe(24)
                CODES[code] = {
                    "username": username,
                    "nonce": form.get("nonce"),
                    "challenge": form.get("code_challenge"),
                    "method": form.get("code_challenge_method", "plain"),
                    "redirect_uri": form.get("redirect_uri"),
                }
                params = {"code": code, "session_state": str(uuid.uuid4())}
                if form.get("state"):
                    params["state"] = form["state"]
                sep = "&" if "?" in (form.get("redirect_uri") or "") else "?"
                return self._redirect(f"{form.get('redirect_uri')}{sep}{urlencode(params)}")
            if url.path == f"{base}/protocol/openid-connect/token":
                cid, csec = form.get("client_id"), form.get("client_secret")
                auth = self.headers.get("authorization", "")
                if auth.lower().startswith("basic "):
                    cid, _, csec = base64.b64decode(auth.split(" ", 1)[1]).decode().partition(":")
                if cid != client_id or csec != client_secret:
                    return self._json(401, {"error": "invalid_client"})
                grant = form.get("grant_type")
                if grant == "authorization_code":
                    c = CODES.pop(form.get("code", ""), None)
                    if c is None:
                        return self._json(400, {"error": "invalid_grant", "error_description": "unknown code"})
                    if c["challenge"]:
                        v = form.get("code_verifier", "")
                        expect = (
                            base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
                            if c["method"] == "S256"
                            else v
                        )
                        if expect != c["challenge"]:
                            return self._json(400, {"error": "invalid_grant", "error_description": "pkce"})
                    return self._json(200, tokens(c["username"], c["nonce"]))
                if grant == "refresh_token":
                    r = REFRESH.pop(form.get("refresh_token", ""), None)
                    if r is None:
                        return self._json(400, {"error": "invalid_grant", "error_description": "unknown refresh token"})
                    return self._json(200, tokens(r["username"], r["nonce"]))
                return self._json(400, {"error": "unsupported_grant_type"})
            if url.path == f"{base}/protocol/openid-connect/logout":
                return self._json(204, {})
            return self._json(404, {"error": "not_found", "path": url.path})

    return H


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8089)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--realm", default="qr")
    ap.add_argument("--client", default="qr-ai-lab")
    ap.add_argument("--secret", default="dev-secret")
    ap.add_argument("--access-ttl", type=int, default=120, help="short, so the refresh path gets exercised")
    a = ap.parse_args()
    issuer = f"http://{a.host}:{a.port}/realms/{a.realm}"
    srv = Server((a.host, a.port), make_handler(issuer, a.client, a.secret, a.access_ttl))
    print(f"fake keycloak at {issuer} (client {a.client})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
