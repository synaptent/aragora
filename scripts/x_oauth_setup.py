#!/usr/bin/env python3
"""One-time OAuth2 PKCE setup for X (Twitter) bookmarks/likes ingestion.

Run this YOURSELF (it opens a consent page in your browser; no credentials
pass through any agent):

    python scripts/x_oauth_setup.py --client-id <your_app_client_id>

Prereqs (once, at https://developer.x.com):
  1. Create a project + app (Free tier works for owned reads).
  2. In the app's "User authentication settings": enable OAuth 2.0,
     type "Native App" (public client), and add the callback URL
     http://127.0.0.1:8765/callback (or pass --redirect-port)
  3. Copy the OAuth 2.0 Client ID.

The script requests scopes: tweet.read users.read bookmark.read like.read
offline.access — the last one grants a refresh token so the sync can run
unattended. Tokens are written to .aragora/x_intake/oauth.json (0600,
gitignored via .aragora/). X rotates refresh tokens on every refresh; the
ingestion path persists rotations automatically.

Afterwards:
    aragora ideacloud load --source twitter-bookmarks --api
    aragora ideacloud load --source twitter-likes --api
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
DEFAULT_PORT = 8765  # matches the callback registered on the X app
SCOPES = "tweet.read users.read bookmark.read like.read offline.access"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    state_expected: str = ""

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        state = params.get("state", [""])[0]
        if state != _CallbackHandler.state_expected:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"State mismatch - aborting.")
            return
        _CallbackHandler.code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Authorized. You can close this tab.</h2>")

    def log_message(self, *args: object) -> None:  # silence request logging
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True, help="OAuth 2.0 Client ID of your X app")
    parser.add_argument(
        "--redirect-port",
        type=int,
        default=DEFAULT_PORT,
        help="Localhost port of the registered callback URI (default: %(default)s)",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=300,
        help="How long to wait for the browser consent callback (default: %(default)s)",
    )
    parser.add_argument(
        "--token-path",
        default=".aragora/x_intake/oauth.json",
        help=(
            "Where to store the token pair. If you change this, set "
            "ARAGORA_X_OAUTH_TOKEN_PATH to the same value so ingestion finds it"
        ),
    )
    args = parser.parse_args()
    redirect_uri = f"http://127.0.0.1:{args.redirect_port}/callback"

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = secrets.token_urlsafe(24)
    _CallbackHandler.state_expected = state

    authorize = (
        AUTH_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": args.client_id,
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )

    server = http.server.HTTPServer(("127.0.0.1", args.redirect_port), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print("Open this URL in your browser and authorize the app:\n")
    print(authorize)
    print(f"\nWaiting for the callback on {redirect_uri} ...")

    deadline = time.time() + args.wait_seconds
    while _CallbackHandler.code is None and time.time() < deadline:
        time.sleep(0.5)
    server.shutdown()

    if not _CallbackHandler.code:
        print(f"Timed out waiting for authorization ({args.wait_seconds}s).", file=sys.stderr)
        return 1

    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": _CallbackHandler.code,
            "client_id": args.client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
    except OSError as exc:
        print(f"Token exchange failed: {exc}", file=sys.stderr)
        return 1

    from aragora.connectors.x_oauth import XOAuthTokens, XOAuthTokenStore

    store = XOAuthTokenStore(args.token_path)
    store.save(
        XOAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            client_id=args.client_id,
            expires_at=time.time() + float(data.get("expires_in", 7200)),
        )
    )
    print(f"\nTokens saved to {args.token_path} (0600).")
    print("Try: aragora ideacloud load --source twitter-bookmarks --api")
    return 0


if __name__ == "__main__":
    sys.exit(main())
