"""
Auth Namespace API

Provides methods for authentication and user session management.

Features:
- User registration and login
- Token refresh and logout
- Password reset workflows
- MFA setup and verification
- OAuth authentication flows
- Session management
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class AuthAPI:
    """
    Synchronous Auth API.

    Provides methods for authentication operations:
    - User registration and login
    - Token management
    - Password reset
    - MFA configuration
    - OAuth flows
    - Session management

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> token = client.auth.login(email="user@example.com", password="secret")
        >>> user = client.auth.get_current_user()
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    # ===========================================================================
    # Registration and Login
    # ===========================================================================

    def register(
        self,
        email: str,
        password: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """
        Register a new user account.

        Args:
            email: User email address
            password: Password (min 8 chars)
            name: Optional display name

        Returns:
            Dict with user info and confirmation status
        """
        data = {"email": email, "password": password}
        if name:
            data["name"] = name

        return self._client.request("POST", "/api/v1/auth/register", json=data)

    def login(
        self,
        email: str,
        password: str,
        mfa_code: str | None = None,
    ) -> dict[str, Any]:
        """
        Authenticate and get access token.

        Args:
            email: User email
            password: User password
            mfa_code: Optional MFA code if enabled

        Returns:
            Dict with access_token, refresh_token, expires_in, and token_type
        """
        data = {"email": email, "password": password}
        if mfa_code:
            data["mfa_code"] = mfa_code

        return self._client.request("POST", "/api/v1/auth/login", json=data)

    def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """
        Refresh the access token.

        Args:
            refresh_token: The refresh token

        Returns:
            Dict with new access_token, refresh_token, expires_in
        """
        return self._client.request(
            "POST",
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

    def logout(self) -> dict[str, Any]:
        """
        Logout and invalidate current token.

        Returns:
            Dict with success status
        """
        return self._client.request("POST", "/api/v1/auth/logout")

    def get_current_user(self) -> dict[str, Any]:
        """
        Get the current authenticated user.

        Returns:
            Dict with user profile information
        """
        return self._client.request("GET", "/api/v1/auth/me")

    def update_profile(
        self,
        name: str | None = None,
        avatar_url: str | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Update user profile.

        Args:
            name: New display name
            avatar_url: New avatar URL
            preferences: User preferences dict

        Returns:
            Updated user profile
        """
        data: dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if avatar_url is not None:
            data["avatar_url"] = avatar_url
        if preferences is not None:
            data["preferences"] = preferences

        return self._client.request("PATCH", "/api/v1/auth/me", json=data)

    # ===========================================================================
    # Password Management
    # ===========================================================================

    def change_password(
        self,
        current_password: str,
        new_password: str,
    ) -> dict[str, Any]:
        """
        Change the user's password.

        Args:
            current_password: Current password for verification
            new_password: New password (min 8 chars)

        Returns:
            Dict with success status
        """
        return self._client.request(
            "POST",
            "/api/v1/auth/password/change",
            json={
                "current_password": current_password,
                "new_password": new_password,
            },
        )

    def request_password_reset(self, email: str) -> dict[str, Any]:
        """
        Request a password reset email.

        Args:
            email: Email address to send reset link to

        Returns:
            Dict with success status
        """
        return self._client.request(
            "POST",
            "/api/v1/auth/password/forgot",
            json={"email": email},
        )

    def reset_password(self, token: str, new_password: str) -> dict[str, Any]:
        """
        Reset password using reset token.

        Args:
            token: Password reset token from email
            new_password: New password

        Returns:
            Dict with success status
        """
        return self._client.request(
            "POST",
            "/api/v1/auth/password/reset",
            json={"token": token, "new_password": new_password},
        )

    # ===========================================================================
    # Email Verification
    # ===========================================================================

    def verify_email(self, token: str) -> dict[str, Any]:
        """
        Verify email address with token.

        Args:
            token: Verification token from email

        Returns:
            Dict with verified status
        """
        return self._client.request(
            "POST",
            "/api/v1/auth/verify-email",
            json={"token": token},
        )

    def resend_verification(self) -> dict[str, Any]:
        """
        Resend email verification link.

        Returns:
            Dict with success status
        """
        return self._client.request("POST", "/api/v1/auth/verify-email/resend")

    # ===========================================================================
    # MFA (Multi-Factor Authentication)
    # ===========================================================================

    def setup_mfa(self, method: str = "totp") -> dict[str, Any]:
        """
        Start MFA setup process.

        Args:
            method: MFA method (totp, hotp)

        Returns:
            Dict with secret, qr_code_uri, and backup_codes
        """
        return self._client.request(
            "POST",
            "/api/v1/auth/mfa/setup",
            json={"method": method},
        )

    def verify_mfa_setup(self, code: str) -> dict[str, Any]:
        """
        Verify MFA setup with code.

        Args:
            code: MFA code from authenticator app

        Returns:
            Dict with verified status
        """
        return self._client.request(
            "POST",
            "/api/v1/auth/mfa/verify",
            json={"code": code},
        )

    def enable_mfa(self, code: str) -> dict[str, Any]:
        """
        Enable MFA after verification.

        Args:
            code: MFA code to confirm

        Returns:
            Dict with enabled status
        """
        return self._client.request(
            "POST",
            "/api/v1/auth/mfa/enable",
            json={"code": code},
        )

    def disable_mfa(self, password: str) -> dict[str, Any]:
        """
        Disable MFA (requires password confirmation).

        Args:
            password: Current password for verification

        Returns:
            Dict with success status
        """
        return self._client.request(
            "POST",
            "/api/v1/auth/mfa/disable",
            json={"password": password},
        )

    def generate_backup_codes(self) -> dict[str, Any]:
        """
        Generate new backup codes.

        Returns:
            Dict with codes array
        """
        return self._client.request("POST", "/api/v1/auth/mfa/backup-codes")

    # ===========================================================================
    # OAuth
    # ===========================================================================

    def get_oauth_url(
        self,
        provider: str,
        redirect_uri: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        """
        Get OAuth authorization URL.

        Args:
            provider: OAuth provider (google, github, microsoft)
            redirect_uri: Callback URL
            state: CSRF state parameter

        Returns:
            Dict with auth_url
        """
        params = {"provider": provider}
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
        if state:
            params["state"] = state

        return self._client.request("GET", "/api/v1/auth/oauth/url", params=params)

    def complete_oauth(
        self,
        provider: str,
        code: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """
        Complete OAuth flow with authorization code.

        Args:
            provider: OAuth provider
            code: Authorization code from callback
            state: CSRF state parameter

        Returns:
            Dict with access_token, refresh_token
        """
        data = {"provider": provider, "code": code}
        if state:
            data["state"] = state

        return self._client.request("POST", "/api/v1/auth/oauth/callback", json=data)

    def list_oauth_providers(self) -> dict[str, Any]:
        """
        List available OAuth providers.

        Returns:
            Dict with providers array
        """
        return self._client.request("GET", "/api/v1/auth/oauth/providers")

    # ===========================================================================
    # Sessions
    # ===========================================================================

    def list_sessions(self) -> dict[str, Any]:
        """
        List active sessions.

        Returns:
            Dict with sessions array
        """
        return self._client.request("GET", "/api/v1/auth/sessions")

    def get_active_sessions(self) -> dict[str, Any]:
        """Get currently active sessions with details.

        Returns:
            Dict with active session count and details.
        """
        return self._client.request("GET", "/api/v1/auth/sessions/active")

    def get_session_health(self) -> dict[str, Any]:
        """Get session subsystem health status.

        Returns:
            Dict with session health metrics.
        """
        return self._client.request("GET", "/api/v1/auth/sessions/health")

    def sweep_sessions(self) -> dict[str, Any]:
        """Sweep expired sessions.

        Returns:
            Dict with count of swept sessions.
        """
        return self._client.request("POST", "/api/v1/auth/sessions/sweep")

    def revoke_session(self, session_id: str) -> dict[str, Any]:
        """
        Revoke a specific session.

        Args:
            session_id: Session ID to revoke

        Returns:
            Dict with success status
        """
        return self._client.request("DELETE", f"/api/v1/auth/sessions/{session_id}")

    # ===========================================================================
    # API Keys
    # ===========================================================================

    def list_api_keys(self) -> dict[str, Any]:
        """
        List API keys for the current user.

        Returns:
            Dict with keys array
        """
        return self._client.request("GET", "/api/v1/auth/api-keys")

    def create_api_key(
        self,
        name: str,
        scopes: list[str] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new API key.

        Args:
            name: Key name for identification
            scopes: Optional permission scopes
            expires_at: Optional expiration (ISO 8601)

        Returns:
            Dict with key info including the secret (only shown once)
        """
        data: dict[str, Any] = {"name": name}
        if scopes:
            data["scopes"] = scopes
        if expires_at:
            data["expires_at"] = expires_at

        return self._client.request("POST", "/api/v1/auth/api-keys", json=data)

    def revoke_api_key(self, key_id: str) -> dict[str, Any]:
        """
        Revoke an API key.

        Args:
            key_id: API key ID

        Returns:
            Dict with success status
        """
        return self._client.request("DELETE", f"/api/v1/auth/api-keys/{key_id}")

    # ===========================================================================
    # Team Invitations
    # ===========================================================================

    def invite_team_member(
        self,
        email: str,
        role: str | None = None,
    ) -> dict[str, Any]:
        """
        Invite a new team member.

        Args:
            email: Email address to invite
            role: Optional role to assign (default: member)

        Returns:
            Dict with invite_token, invite_url, and expires_in
        """
        data: dict[str, Any] = {"email": email}
        if role:
            data["role"] = role

        return self._client.request("POST", "/api/v1/auth/invite", json=data)

    def health(self) -> dict[str, Any]:
        """
        Check authentication service health.

        Returns:
            Dict with status and service health details
        """
        return self._client.request("GET", "/api/auth/health")

    # ===========================================================================
    # Profile (alternative endpoint)
    # ===========================================================================

    def get_profile(self) -> dict[str, Any]:
        """
        Get the authenticated user's profile.

        Alternative to get_current_user(), uses /api/auth/profile endpoint.

        Returns:
            Dict with user profile information
        """
        return self._client.request("GET", "/api/auth/profile")

    # ===========================================================================
    # MFA (combined endpoint)
    # ===========================================================================

    def mfa(
        self,
        action: str = "setup",
        code: str | None = None,
        method: str | None = None,
    ) -> dict[str, Any]:
        """
        Combined MFA setup and verification endpoint.

        Args:
            action: MFA action (setup, verify, enable, disable)
            code: MFA code for verify/enable actions
            method: MFA method for setup (totp, hotp)

        Returns:
            Dict with MFA operation result
        """
        data: dict[str, Any] = {"action": action}
        if code:
            data["code"] = code
        if method:
            data["method"] = method

        return self._client.request("POST", "/api/auth/mfa", json=data)

    # ===========================================================================
    # OAuth (additional endpoints)
    # ===========================================================================

    def get_oauth_authorize_url(
        self,
        provider: str,
        redirect_uri: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        """
        Get OAuth authorization URL via the authorize endpoint.

        Args:
            provider: OAuth provider (google, github, microsoft)
            redirect_uri: Callback URL
            state: CSRF state parameter

        Returns:
            Dict with authorization_url
        """
        params: dict[str, str] = {"provider": provider}
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
        if state:
            params["state"] = state

        return self._client.request("GET", "/api/auth/oauth/authorize", params=params)

    def get_oauth_diagnostics(self) -> dict[str, Any]:
        """
        Get OAuth configuration diagnostics.

        Returns diagnostic information about OAuth provider configuration,
        useful for troubleshooting authentication issues.

        Returns:
            Dict with provider configs, status, and diagnostic details
        """
        return self._client.request("GET", "/api/auth/oauth/diagnostics")

    def get_oauth_callback(
        self,
        code: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """
        Handle OAuth callback with authorization code.

        Args:
            code: Authorization code from OAuth provider
            state: CSRF state parameter

        Returns:
            Dict with access_token and user info
        """
        params: dict[str, str] = {"code": code}
        if state:
            params["state"] = state

        return self._client.request("GET", "/api/auth/oauth/callback", params=params)

    # ===========================================================================
    # Password (alternative endpoints)
    # ===========================================================================

    def forgot_password(self, email: str) -> dict[str, Any]:
        """
        Request a password reset via the forgot-password endpoint.

        Alternative to request_password_reset(), uses /api/auth/forgot-password.

        Args:
            email: Email address to send reset link to

        Returns:
            Dict with success status
        """
        return self._client.request(
            "POST",
            "/api/auth/forgot-password",
            json={"email": email},
        )

    def reset_password_alt(self, token: str, new_password: str) -> dict[str, Any]:
        """
        Reset password via the reset-password endpoint.

        Alternative to reset_password(), uses /api/auth/reset-password.

        Args:
            token: Password reset token from email
            new_password: New password

        Returns:
            Dict with success status
        """
        return self._client.request(
            "POST",
            "/api/auth/reset-password",
            json={"token": token, "new_password": new_password},
        )

    # ===========================================================================
    # Verification (alternative endpoint)
    # ===========================================================================

    def resend_verification_alt(self, email: str | None = None) -> dict[str, Any]:
        """
        Resend email verification via the resend-verification endpoint.

        Alternative to resend_verification(), uses /api/auth/resend-verification.

        Args:
            email: Optional email address

        Returns:
            Dict with success status
        """
        data: dict[str, Any] = {}
        if email:
            data["email"] = email

        return self._client.request("POST", "/api/auth/resend-verification", json=data)

    # ===========================================================================
    # Invitations (alternative endpoints)
    # ===========================================================================

    def check_invite_alt(self, token: str) -> dict[str, Any]:
        """
        Check invitation validity via the check-invite endpoint.

        Alternative to check_invite(), uses /api/auth/check-invite.

        Args:
            token: Invitation token

        Returns:
            Dict with valid, email, organization_id, role, expires_at
        """
        return self._client.request(
            "GET",
            "/api/auth/check-invite",
            params={"token": token},
        )

    def accept_invite_alt(self, token: str) -> dict[str, Any]:
        """
        Accept a team invitation via the accept-invite endpoint.

        Alternative to accept_invite(), uses /api/auth/accept-invite.

        Args:
            token: Invitation token

        Returns:
            Dict with organization_id and role
        """
        return self._client.request(
            "POST",
            "/api/auth/accept-invite",
            json={"token": token},
        )

    # ===========================================================================
    # Organization Setup
    # ===========================================================================

    def setup_organization(
        self,
        name: str,
        slug: str | None = None,
    ) -> dict[str, Any]:
        """
        Set up a new organization after registration.

        Args:
            name: Organization name
            slug: Optional URL-friendly slug

        Returns:
            Dict with organization details
        """
        data: dict[str, Any] = {"name": name}
        if slug:
            data["slug"] = slug

        return self._client.request("POST", "/api/auth/setup-organization", json=data)

    # ===========================================================================
    # Onboarding
    # ===========================================================================

    def get_onboarding_status(self) -> dict[str, Any]:
        """
        Get the current onboarding status for the organization.

        Returns:
            Dict with onboarding progress, completed steps, and remaining tasks
        """
        return self._client.request("GET", "/api/onboarding/status")

    def complete_onboarding(self, **kwargs: Any) -> dict[str, Any]:
        """
        Mark the onboarding process as complete.

        Args:
            **kwargs: Additional completion parameters

        Returns:
            Dict with completion confirmation
        """
        return self._client.request("POST", "/api/onboarding/complete", json=kwargs)


class AsyncAuthAPI:
    """
    Asynchronous Auth API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     token = await client.auth.login(email="user@example.com", password="secret")
        ...     user = await client.auth.get_current_user()
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    # ===========================================================================
    # Registration and Login
    # ===========================================================================

    async def register(
        self,
        email: str,
        password: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Register a new user account."""
        data = {"email": email, "password": password}
        if name:
            data["name"] = name

        return await self._client.request("POST", "/api/v1/auth/register", json=data)

    async def login(
        self,
        email: str,
        password: str,
        mfa_code: str | None = None,
    ) -> dict[str, Any]:
        """Authenticate and get access token."""
        data = {"email": email, "password": password}
        if mfa_code:
            data["mfa_code"] = mfa_code

        return await self._client.request("POST", "/api/v1/auth/login", json=data)

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token."""
        return await self._client.request(
            "POST",
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

    async def logout(self) -> dict[str, Any]:
        """Logout and invalidate current token."""
        return await self._client.request("POST", "/api/v1/auth/logout")

    async def get_current_user(self) -> dict[str, Any]:
        """Get the current authenticated user."""
        return await self._client.request("GET", "/api/v1/auth/me")

    async def update_profile(
        self,
        name: str | None = None,
        avatar_url: str | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update user profile."""
        data: dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if avatar_url is not None:
            data["avatar_url"] = avatar_url
        if preferences is not None:
            data["preferences"] = preferences

        return await self._client.request("PATCH", "/api/v1/auth/me", json=data)

    # ===========================================================================
    # Password Management
    # ===========================================================================

    async def change_password(
        self,
        current_password: str,
        new_password: str,
    ) -> dict[str, Any]:
        """Change the user's password."""
        return await self._client.request(
            "POST",
            "/api/v1/auth/password/change",
            json={
                "current_password": current_password,
                "new_password": new_password,
            },
        )

    async def request_password_reset(self, email: str) -> dict[str, Any]:
        """Request a password reset email."""
        return await self._client.request(
            "POST",
            "/api/v1/auth/password/forgot",
            json={"email": email},
        )

    async def reset_password(self, token: str, new_password: str) -> dict[str, Any]:
        """Reset password using reset token."""
        return await self._client.request(
            "POST",
            "/api/v1/auth/password/reset",
            json={"token": token, "new_password": new_password},
        )

    # ===========================================================================
    # Email Verification
    # ===========================================================================

    async def verify_email(self, token: str) -> dict[str, Any]:
        """Verify email address with token."""
        return await self._client.request(
            "POST",
            "/api/v1/auth/verify-email",
            json={"token": token},
        )

    async def resend_verification(self) -> dict[str, Any]:
        """Resend email verification link."""
        return await self._client.request("POST", "/api/v1/auth/verify-email/resend")

    # ===========================================================================
    # MFA (Multi-Factor Authentication)
    # ===========================================================================

    async def setup_mfa(self, method: str = "totp") -> dict[str, Any]:
        """Start MFA setup process."""
        return await self._client.request(
            "POST",
            "/api/v1/auth/mfa/setup",
            json={"method": method},
        )

    async def verify_mfa_setup(self, code: str) -> dict[str, Any]:
        """Verify MFA setup with code."""
        return await self._client.request(
            "POST",
            "/api/v1/auth/mfa/verify",
            json={"code": code},
        )

    async def enable_mfa(self, code: str) -> dict[str, Any]:
        """Enable MFA after verification."""
        return await self._client.request(
            "POST",
            "/api/v1/auth/mfa/enable",
            json={"code": code},
        )

    async def disable_mfa(self, password: str) -> dict[str, Any]:
        """Disable MFA (requires password confirmation)."""
        return await self._client.request(
            "POST",
            "/api/v1/auth/mfa/disable",
            json={"password": password},
        )

    async def generate_backup_codes(self) -> dict[str, Any]:
        """Generate new backup codes."""
        return await self._client.request("POST", "/api/v1/auth/mfa/backup-codes")

    # ===========================================================================
    # OAuth
    # ===========================================================================

    async def get_oauth_url(
        self,
        provider: str,
        redirect_uri: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Get OAuth authorization URL."""
        params = {"provider": provider}
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
        if state:
            params["state"] = state

        return await self._client.request("GET", "/api/v1/auth/oauth/url", params=params)

    async def complete_oauth(
        self,
        provider: str,
        code: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Complete OAuth flow with authorization code."""
        data = {"provider": provider, "code": code}
        if state:
            data["state"] = state

        return await self._client.request("POST", "/api/v1/auth/oauth/callback", json=data)

    async def list_oauth_providers(self) -> dict[str, Any]:
        """List available OAuth providers."""
        return await self._client.request("GET", "/api/v1/auth/oauth/providers")

    # ===========================================================================
    # Sessions
    # ===========================================================================

    async def list_sessions(self) -> dict[str, Any]:
        """List active sessions."""
        return await self._client.request("GET", "/api/v1/auth/sessions")

    async def get_active_sessions(self) -> dict[str, Any]:
        """Get currently active sessions with details."""
        return await self._client.request("GET", "/api/v1/auth/sessions/active")

    async def get_session_health(self) -> dict[str, Any]:
        """Get session subsystem health status."""
        return await self._client.request("GET", "/api/v1/auth/sessions/health")

    async def sweep_sessions(self) -> dict[str, Any]:
        """Sweep expired sessions."""
        return await self._client.request("POST", "/api/v1/auth/sessions/sweep")

    async def revoke_session(self, session_id: str) -> dict[str, Any]:
        """Revoke a specific session."""
        return await self._client.request("DELETE", f"/api/v1/auth/sessions/{session_id}")

    # ===========================================================================
    # API Keys
    # ===========================================================================

    async def list_api_keys(self) -> dict[str, Any]:
        """List API keys for the current user."""
        return await self._client.request("GET", "/api/v1/auth/api-keys")

    async def create_api_key(
        self,
        name: str,
        scopes: list[str] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a new API key."""
        data: dict[str, Any] = {"name": name}
        if scopes:
            data["scopes"] = scopes
        if expires_at:
            data["expires_at"] = expires_at

        return await self._client.request("POST", "/api/v1/auth/api-keys", json=data)

    async def revoke_api_key(self, key_id: str) -> dict[str, Any]:
        """Revoke an API key."""
        return await self._client.request("DELETE", f"/api/v1/auth/api-keys/{key_id}")

    # ===========================================================================
    # Team Invitations
    # ===========================================================================

    async def invite_team_member(
        self,
        email: str,
        role: str | None = None,
    ) -> dict[str, Any]:
        """Invite a new team member."""
        data: dict[str, Any] = {"email": email}
        if role:
            data["role"] = role

        return await self._client.request("POST", "/api/v1/auth/invite", json=data)

    async def health(self) -> dict[str, Any]:
        """Check authentication service health."""
        return await self._client.request("GET", "/api/auth/health")

    # ===========================================================================
    # Profile (alternative endpoint)
    # ===========================================================================

    async def get_profile(self) -> dict[str, Any]:
        """Get the authenticated user's profile via /api/auth/profile."""
        return await self._client.request("GET", "/api/auth/profile")

    # ===========================================================================
    # MFA (combined endpoint)
    # ===========================================================================

    async def mfa(
        self,
        action: str = "setup",
        code: str | None = None,
        method: str | None = None,
    ) -> dict[str, Any]:
        """Combined MFA setup and verification endpoint."""
        data: dict[str, Any] = {"action": action}
        if code:
            data["code"] = code
        if method:
            data["method"] = method

        return await self._client.request("POST", "/api/auth/mfa", json=data)

    # ===========================================================================
    # OAuth (additional endpoints)
    # ===========================================================================

    async def get_oauth_authorize_url(
        self,
        provider: str,
        redirect_uri: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Get OAuth authorization URL via the authorize endpoint."""
        params: dict[str, str] = {"provider": provider}
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
        if state:
            params["state"] = state

        return await self._client.request("GET", "/api/auth/oauth/authorize", params=params)

    async def get_oauth_diagnostics(self) -> dict[str, Any]:
        """Get OAuth configuration diagnostics."""
        return await self._client.request("GET", "/api/auth/oauth/diagnostics")

    async def get_oauth_callback(
        self,
        code: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Handle OAuth callback with authorization code."""
        params: dict[str, str] = {"code": code}
        if state:
            params["state"] = state

        return await self._client.request("GET", "/api/auth/oauth/callback", params=params)

    # ===========================================================================
    # Password (alternative endpoints)
    # ===========================================================================

    async def forgot_password(self, email: str) -> dict[str, Any]:
        """Request a password reset via /api/auth/forgot-password."""
        return await self._client.request(
            "POST",
            "/api/auth/forgot-password",
            json={"email": email},
        )

    async def reset_password_alt(self, token: str, new_password: str) -> dict[str, Any]:
        """Reset password via /api/auth/reset-password."""
        return await self._client.request(
            "POST",
            "/api/auth/reset-password",
            json={"token": token, "new_password": new_password},
        )

    # ===========================================================================
    # Verification (alternative endpoint)
    # ===========================================================================

    async def resend_verification_alt(self, email: str | None = None) -> dict[str, Any]:
        """Resend email verification via /api/auth/resend-verification."""
        data: dict[str, Any] = {}
        if email:
            data["email"] = email

        return await self._client.request("POST", "/api/auth/resend-verification", json=data)

    # ===========================================================================
    # Invitations (alternative endpoints)
    # ===========================================================================

    async def check_invite_alt(self, token: str) -> dict[str, Any]:
        """Check invitation validity via /api/auth/check-invite."""
        return await self._client.request(
            "GET",
            "/api/auth/check-invite",
            params={"token": token},
        )

    async def accept_invite_alt(self, token: str) -> dict[str, Any]:
        """Accept a team invitation via /api/auth/accept-invite."""
        return await self._client.request(
            "POST",
            "/api/auth/accept-invite",
            json={"token": token},
        )

    # ===========================================================================
    # Organization Setup
    # ===========================================================================

    async def setup_organization(
        self,
        name: str,
        slug: str | None = None,
    ) -> dict[str, Any]:
        """Set up a new organization after registration."""
        data: dict[str, Any] = {"name": name}
        if slug:
            data["slug"] = slug

        return await self._client.request("POST", "/api/auth/setup-organization", json=data)

    # ===========================================================================
    # Onboarding
    # ===========================================================================

    async def get_onboarding_status(self) -> dict[str, Any]:
        """Get the current onboarding status for the organization."""
        return await self._client.request("GET", "/api/onboarding/status")

    async def complete_onboarding(self, **kwargs: Any) -> dict[str, Any]:
        """Mark the onboarding process as complete."""
        return await self._client.request("POST", "/api/onboarding/complete", json=kwargs)
