#!/usr/bin/env python3
"""Gmail OAuth setup helper for inbox triage dogfood.

One-time interactive script that walks the founder through:
  1. Creating a Google Cloud project + enabling Gmail API
  2. Creating OAuth 2.0 credentials (client ID + secret)
  3. Running a local callback server to capture the refresh token
  4. Saving the token for use by GmailConnector

Usage:
    # First run -- prints setup instructions when creds are missing
    python scripts/gmail_oauth_setup.py

    # After setting GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET
    python scripts/gmail_oauth_setup.py

Dependencies: stdlib + httpx (already in aragora deps)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import stat
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

_DEFAULT_PORT = 8085
CALLBACK_PORT = _DEFAULT_PORT
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"

TOKEN_DIR = Path.home() / ".aragora"
TOKEN_FILE = TOKEN_DIR / "gmail_refresh_token"


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------


def get_client_credentials() -> tuple[str, str]:
    """Read OAuth client ID and secret from environment.

    Mirrors the lookup order in GmailClientMixin._get_client_credentials().
    """
    client_id = (
        os.environ.get("GMAIL_CLIENT_ID")
        or os.environ.get("GOOGLE_GMAIL_CLIENT_ID")
        or os.environ.get("GOOGLE_CLIENT_ID")
        or ""
    )
    client_secret = (
        os.environ.get("GMAIL_CLIENT_SECRET")
        or os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET")
        or os.environ.get("GOOGLE_CLIENT_SECRET")
        or ""
    )
    return client_id, client_secret


def check_credentials() -> tuple[bool, str, str]:
    """Return (ok, client_id, client_secret). ok is True when both are set."""
    client_id, client_secret = get_client_credentials()
    return bool(client_id and client_secret), client_id, client_secret


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

SETUP_INSTRUCTIONS = """\
=======================================================
  Gmail OAuth Setup -- Credentials Not Found
=======================================================

Before running this script you need a Google Cloud project
with OAuth 2.0 credentials. Follow these steps:

1. Go to https://console.cloud.google.com/
   - Create a new project (or select an existing one).

2. Enable the Gmail API:
   - Navigate to "APIs & Services" > "Library".
   - Search for "Gmail API" and click "Enable".

3. Configure the OAuth consent screen:
   - Go to "APIs & Services" > "OAuth consent screen".
   - Choose "External" user type (or "Internal" if using Workspace).
   - Fill in app name (e.g. "Aragora Inbox Triage") and your email.
   - Add scopes:
       gmail.readonly
       gmail.modify
   - Add your Gmail address as a test user.
   - Save.

4. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials".
   - Click "Create Credentials" > "OAuth client ID".
   - Application type: "Web application".
   - Name: "Aragora Inbox Triage".
   - Under "Authorized redirect URIs" add:
       {redirect_uri}
   - Click "Create" and note the Client ID and Client Secret.

5. Set the credentials as environment variables:

   export GMAIL_CLIENT_ID="your-client-id-here"
   export GMAIL_CLIENT_SECRET="your-client-secret-here"

   Or add them to your .env file:

   GMAIL_CLIENT_ID=your-client-id-here
   GMAIL_CLIENT_SECRET=your-client-secret-here

6. Re-run this script:

   python scripts/gmail_oauth_setup.py

=======================================================
""".format(redirect_uri=REDIRECT_URI)


def print_missing_credentials() -> None:
    """Print setup instructions when credentials are not configured."""
    print(SETUP_INSTRUCTIONS)


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


def exchange_code_for_tokens(code: str, client_id: str, client_secret: str) -> dict[str, Any]:
    """Exchange the authorization code for access + refresh tokens.

    Uses httpx (sync) which is already an aragora dependency.
    """
    import httpx

    response = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Local callback server
# ---------------------------------------------------------------------------


def build_auth_url(client_id: str, state: str) -> str:
    """Build the Google OAuth consent URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth redirect and extracts the authorization code."""

    # Set by the server wrapper before serving
    auth_code: str | None = None
    auth_error: str | None = None
    expected_state: str = ""
    code_received: Event

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = parse_qs(parsed.query)

        # Verify state to prevent CSRF
        received_state = params.get("state", [""])[0]
        if received_state != self.expected_state:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"State mismatch -- possible CSRF. Please try again.")
            _OAuthCallbackHandler.auth_error = "state mismatch"
            self.code_received.set()
            return

        error = params.get("error", [None])[0]
        if error:
            self.send_response(400)
            self.end_headers()
            msg = f"OAuth error: {error}"
            self.wfile.write(msg.encode())
            _OAuthCallbackHandler.auth_error = error
            self.code_received.set()
            return

        code = params.get("code", [None])[0]
        if not code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No authorization code received.")
            _OAuthCallbackHandler.auth_error = "no code"
            self.code_received.set()
            return

        _OAuthCallbackHandler.auth_code = code

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Authorization successful!</h2>"
            b"<p>You can close this tab and return to the terminal.</p>"
            b"</body></html>"
        )
        self.code_received.set()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress default stderr logging."""
        pass


def run_callback_server(state: str) -> str | None:
    """Start HTTP server, wait for callback, return auth code or None."""
    code_event = Event()
    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.auth_error = None
    _OAuthCallbackHandler.expected_state = state
    _OAuthCallbackHandler.code_received = code_event

    server = HTTPServer(("127.0.0.1", CALLBACK_PORT), _OAuthCallbackHandler)
    server.timeout = 120  # 2 minute timeout

    print(f"\nListening for OAuth callback on http://localhost:{CALLBACK_PORT}/callback ...")
    print("Waiting for authorization (timeout: 2 minutes) ...\n")

    while not code_event.is_set():
        server.handle_request()

    server.server_close()

    if _OAuthCallbackHandler.auth_error:
        print(f"\nAuthorization failed: {_OAuthCallbackHandler.auth_error}")
        return None

    return _OAuthCallbackHandler.auth_code


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


def save_refresh_token(refresh_token: str) -> Path:
    """Save refresh token to ~/.aragora/gmail_refresh_token with 0600 perms."""
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(refresh_token + "\n")
    TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return TOKEN_FILE


def load_refresh_token() -> str | None:
    """Load previously saved refresh token, if it exists."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    global CALLBACK_PORT, REDIRECT_URI  # noqa: PLW0603

    parser = argparse.ArgumentParser(description="Gmail OAuth setup for Aragora inbox triage")
    parser.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_PORT,
        help=f"Local callback port (default: {_DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the auth URL instead of opening a browser",
    )
    args = parser.parse_args(argv)

    # Update module-level port if overridden
    if args.port != _DEFAULT_PORT:
        CALLBACK_PORT = args.port
        REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"

    print("=== Aragora Gmail OAuth Setup ===\n")

    # Step 1: Check for credentials
    ok, client_id, client_secret = check_credentials()
    if not ok:
        print_missing_credentials()
        return 1

    print(f"Client ID found: {client_id[:12]}...{client_id[-4:]}")
    print("Client Secret found: ****")

    # Step 2: Check for existing token
    existing = load_refresh_token()
    if existing:
        print(f"\nExisting refresh token found at {TOKEN_FILE}")
        answer = input("Re-authorize? (y/N): ").strip().lower()
        if answer != "y":
            print("Keeping existing token. Done.")
            return 0

    # Step 3: Build auth URL and start flow
    state = secrets.token_urlsafe(32)
    auth_url = build_auth_url(client_id, state)

    print("\nOpening Google OAuth consent screen...")
    print(f"Scopes: {', '.join(OAUTH_SCOPES)}\n")

    if args.no_browser:
        print("Open this URL in your browser:\n")
        print(f"  {auth_url}\n")
    else:
        webbrowser.open(auth_url)
        print(f"If the browser didn't open, visit:\n  {auth_url}\n")

    # Step 4: Wait for callback
    code = run_callback_server(state)
    if not code:
        print("\nFailed to receive authorization code.")
        return 1

    print("Authorization code received. Exchanging for tokens...")

    # Step 5: Exchange code for tokens
    try:
        token_data = exchange_code_for_tokens(code, client_id, client_secret)
    except Exception as exc:
        print(f"\nToken exchange failed: {exc}")
        return 1

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        print(
            "\nNo refresh token returned. This can happen if you previously "
            "authorized this app. Try revoking access at "
            "https://myaccount.google.com/permissions and re-running."
        )
        return 1

    # Step 6: Save token
    path = save_refresh_token(refresh_token)
    print(f"\nRefresh token saved to: {path}")
    print("  Permissions: 0600 (owner read/write only)")

    # Step 7: Print .env instructions
    print(
        f"""
=======================================================
  Setup Complete!
=======================================================

Add the following to your .env file:

  GMAIL_CLIENT_ID={client_id}
  GMAIL_CLIENT_SECRET={client_secret}
  GMAIL_REFRESH_TOKEN={refresh_token}

Or export them in your shell:

  export GMAIL_REFRESH_TOKEN=$(cat ~/.aragora/gmail_refresh_token)

The GmailConnector will use these to authenticate.
You can verify by running:

  python -c "
from pathlib import Path
token = Path.home().joinpath('.aragora/gmail_refresh_token').read_text().strip()
print(f'Token loaded: {{token[:12]}}...')
"
=======================================================
"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
