"""
GitHub Secrets sync backend.

Pushes rotated secret values to GitHub repository secrets after rotation.
Uses the GitHub REST API with libsodium sealed-box encryption (required by GitHub).
"""

from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)


class GitHubSecretsSyncBackend:
    """Push rotated secrets to GitHub repository secrets."""

    def __init__(self, repo: str, token: str | None = None):
        """
        Initialize GitHub Secrets sync backend.

        Args:
            repo: GitHub repository in 'owner/repo' format
            token: GitHub App installation token or PAT.
                   Falls back to GITHUB_ROTATION_TOKEN env var.
        """
        self.repo = repo
        self._token = token

    @property
    def token(self) -> str | None:
        """Resolve auth token with fallback chain."""
        if self._token:
            return self._token

        # Try GitHub App installation token first
        app_token = self._get_app_installation_token()
        if app_token:
            return app_token

        # Fall back to PAT
        return os.environ.get("GITHUB_ROTATION_TOKEN")

    def _get_app_installation_token(self) -> str | None:
        """Generate a GitHub App installation token if app credentials are available."""
        app_id = os.environ.get("GITHUB_APP_ID")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
        installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")

        if not (app_id and private_key and installation_id):
            return None

        try:
            import jwt
            import time

            now = int(time.time())
            payload = {
                "iat": now - 60,
                "exp": now + (10 * 60),  # 10 minute expiry
                "iss": app_id,
            }
            encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

            from aragora.security.safe_http import safe_post

            response = safe_post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {encoded_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10.0,
            )
            if response.status_code == 201:
                return response.json().get("token")

            logger.warning("GitHub App token request failed: %d", response.status_code)
            return None

        except (ImportError, OSError, ValueError, KeyError) as e:
            logger.debug("GitHub App token generation failed: %s", e)
            return None

    async def get_public_key(self) -> tuple[str, str]:
        """
        Get repository public key for sealed-box encryption.

        Returns:
            Tuple of (key_id, public_key_base64)

        Raises:
            RuntimeError: If the public key cannot be fetched
        """
        token = self.token
        if not token:
            raise RuntimeError("No GitHub token available for secrets sync")

        from aragora.observability.http_client_pool import get_http_pool

        pool = get_http_pool()
        async with pool.get_session("github") as client:
            response = await client.get(
                f"https://api.github.com/repos/{self.repo}/actions/secrets/public-key",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["key_id"], data["key"]

    async def sync_secret(self, name: str, value: str) -> bool:
        """
        Encrypt and push a secret value to GitHub repository secrets.

        Uses libsodium sealed-box encryption as required by GitHub's API.

        Args:
            name: Secret name in GitHub (e.g., "ANTHROPIC_API_KEY")
            value: Secret value to store

        Returns:
            True if sync succeeded, False otherwise
        """
        token = self.token
        if not token:
            logger.warning("No GitHub token configured, skipping secrets sync for %s", name)
            return False

        try:
            # Get the repository public key
            key_id, public_key_b64 = await self.get_public_key()

            # Encrypt the secret using sealed box
            encrypted_value = self._encrypt_secret(public_key_b64, value)

            # PUT the encrypted secret
            from aragora.observability.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("github") as client:
                response = await client.put(
                    f"https://api.github.com/repos/{self.repo}/actions/secrets/{name}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={
                        "encrypted_value": encrypted_value,
                        "key_id": key_id,
                    },
                    timeout=10.0,
                )

                if response.status_code in (201, 204):
                    logger.info("Synced secret %s to GitHub repo %s", name, self.repo)
                    return True

                logger.warning(
                    "GitHub secrets sync failed for %s: HTTP %d",
                    name,
                    response.status_code,
                )
                return False

        except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
            logger.error("GitHub secrets sync error for %s: %s", name, e)
            return False

    def _encrypt_secret(self, public_key_b64: str, secret_value: str) -> str:
        """
        Encrypt a secret value using the repository's public key.

        Uses PyNaCl (libsodium) sealed box encryption.

        Args:
            public_key_b64: Base64-encoded repository public key
            secret_value: Plain text secret value

        Returns:
            Base64-encoded encrypted value
        """
        from nacl.public import PublicKey, SealedBox

        public_key_bytes = base64.b64decode(public_key_b64)
        public_key = PublicKey(public_key_bytes)
        sealed_box = SealedBox(public_key)
        encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
        return base64.b64encode(encrypted).decode("utf-8")
