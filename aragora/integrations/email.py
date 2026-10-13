"""
Email notification integration for aragora debates.

Sends debate summaries, consensus alerts, and digest emails.
Supports HTML email templates with inline CSS.

Providers:
    - SMTP (default): Standard SMTP protocol
    - SendGrid: SendGrid Web API v3
    - AWS SES: Amazon Simple Email Service

Usage:
    # SMTP (default)
    email = EmailIntegration(EmailConfig(smtp_host="smtp.example.com"))

    # SendGrid
    email = EmailIntegration(EmailConfig(
        provider="sendgrid",
        sendgrid_api_key="SG.xxxxx"
    ))

    # AWS SES
    email = EmailIntegration(EmailConfig(
        provider="ses",
        ses_region="us-east-1"
    ))
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Any

import aiohttp

from aragora.core import DebateResult
from aragora.http_client import DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

# Circuit breaker for email providers (lazy import to avoid circular deps)
# Uses contextvars for per-context isolation in multi-worker deployments,
# consistent with the pattern used across 63+ other modules in the codebase.
import contextvars
import threading

_circuit_breakers_var: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "email_circuit_breakers",
    default=None,  # type: ignore[arg-type]
)
_circuit_breakers_init_lock = threading.Lock()


def _get_email_circuit_breakers() -> dict[str, Any]:
    """Get context-local circuit breaker dict, creating if needed."""
    breakers = _circuit_breakers_var.get(None)
    if breakers is None:
        breakers = {}
        _circuit_breakers_var.set(breakers)
    return breakers


def _get_email_circuit_breaker(provider: str, threshold: int = 5, cooldown: float = 60.0) -> Any:
    """Get or create circuit breaker for email provider.

    Uses context-local storage for multi-worker isolation.
    Thread-safe initialization via lock for the creation path.
    """
    breakers = _get_email_circuit_breakers()

    if provider in breakers:
        return breakers[provider]

    # Acquire lock for creation to prevent race conditions
    with _circuit_breakers_init_lock:
        # Re-check after acquiring lock (another thread may have created it)
        breakers = _get_email_circuit_breakers()
        if provider not in breakers:
            try:
                from aragora.resilience import get_circuit_breaker

                breakers[provider] = get_circuit_breaker(
                    name=f"email_{provider}",
                    failure_threshold=threshold,
                    cooldown_seconds=cooldown,
                )
                logger.debug("Circuit breaker initialized for email provider: %s", provider)
            except ImportError:
                logger.debug("Circuit breaker module not available for email")
                breakers[provider] = None
    return breakers.get(provider)


# Distributed rate limiter (lazy import to avoid circular deps)
_distributed_rate_limiter: Any = None


def _get_distributed_rate_limiter() -> Any:
    """Get the distributed email rate limiter, if available."""
    global _distributed_rate_limiter
    if _distributed_rate_limiter is not None:
        return _distributed_rate_limiter
    try:
        from aragora.integrations.email_rate_limiter import get_email_rate_limiter

        _distributed_rate_limiter = get_email_rate_limiter()
        return _distributed_rate_limiter
    except ImportError:
        return None


# OAuth credential store (lazy import)
def _get_credential_store() -> Any:
    """Get the email credential store for OAuth token management."""
    try:
        from aragora.integrations.email_oauth import get_email_credential_store

        return get_email_credential_store()
    except ImportError:
        return None


class EmailProvider(Enum):
    """Email service provider."""

    SMTP = "smtp"
    SENDGRID = "sendgrid"
    SES = "ses"


@dataclass
class EmailConfig:
    """Configuration for Email integration."""

    # Provider selection
    provider: str = "smtp"  # "smtp", "sendgrid", or "ses"

    # SMTP settings
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    use_tls: bool = True
    use_ssl: bool = False

    # SendGrid settings
    sendgrid_api_key: str = ""

    # AWS SES settings
    ses_region: str = "us-east-1"
    ses_access_key_id: str = ""
    ses_secret_access_key: str = ""

    # Email settings
    from_email: str = "debates@aragora.ai"
    from_name: str = "Aragora Debates"
    reply_to: str = ""

    # Notification settings
    notify_on_consensus: bool = True
    notify_on_debate_end: bool = True
    notify_on_error: bool = True

    # Digest settings
    enable_digest: bool = True
    digest_frequency: str = "daily"  # "daily" or "weekly"

    # Minimum confidence for consensus alerts
    min_consensus_confidence: float = 0.7

    # Rate limiting
    max_emails_per_hour: int = 50

    # Retry settings
    max_retries: int = 3
    retry_delay: float = 2.0

    # Circuit breaker settings
    enable_circuit_breaker: bool = True
    circuit_breaker_threshold: int = 5  # Failures before opening
    circuit_breaker_cooldown: float = 60.0  # Seconds before retry

    # SMTP timeout (for synchronous operations)
    smtp_timeout: float = 30.0

    # Distributed rate limiting (uses email_rate_limiter module)
    enable_distributed_rate_limit: bool = True

    # OAuth auto-refresh before sending
    enable_oauth_refresh: bool = True
    oauth_tenant_id: str = "default"

    # Tracking
    enable_click_tracking: bool = False
    enable_open_tracking: bool = False

    def __post_init__(self) -> None:
        # Load from environment if not provided
        if not self.sendgrid_api_key:
            self.sendgrid_api_key = os.environ.get("SENDGRID_API_KEY", "")
        if not self.ses_access_key_id:
            self.ses_access_key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
        if not self.ses_secret_access_key:
            self.ses_secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        if not self.ses_region:
            self.ses_region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

        # Validate configuration based on provider
        if self.provider == "smtp" and not self.smtp_host:
            # Check for SendGrid or SES as fallback
            if self.sendgrid_api_key:
                self.provider = "sendgrid"
            elif self.ses_access_key_id and self.ses_secret_access_key:
                self.provider = "ses"
            else:
                raise ValueError("SMTP host is required for SMTP provider")

    @property
    def email_provider(self) -> EmailProvider:
        """Get the email provider enum."""
        return EmailProvider(self.provider)


@dataclass
class EmailRecipient:
    """An email recipient."""

    email: str
    name: str | None = None
    preferences: dict[str, Any] = field(default_factory=dict)

    @property
    def formatted(self) -> str:
        """Get formatted email address."""
        if self.name:
            return f"{self.name} <{self.email}>"
        return self.email


class EmailIntegration:
    """
    Email integration for sending debate notifications.

    Supports multiple providers:
        - SMTP: Standard email protocol
        - SendGrid: SendGrid Web API v3
        - AWS SES: Amazon Simple Email Service

    Usage:
        # SMTP
        email = EmailIntegration(EmailConfig(
            smtp_host="smtp.example.com",
            smtp_username="user",
            smtp_password="pass",
        ))

        # SendGrid
        email = EmailIntegration(EmailConfig(
            provider="sendgrid",
            sendgrid_api_key="SG.xxxxx",
        ))

        # AWS SES
        email = EmailIntegration(EmailConfig(
            provider="ses",
            ses_region="us-east-1",
        ))

        # Add recipient
        email.add_recipient(EmailRecipient(
            email="user@example.com",
            name="User Name"
        ))

        # Send debate summary
        await email.send_debate_summary(debate_result)

        # Send daily digest
        await email.send_digest()
    """

    # API endpoints
    SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"
    SES_API_VERSION = "2010-12-01"

    def __init__(self, config: EmailConfig):
        self.config = config
        self.recipients: list[EmailRecipient] = []
        self._email_count = 0
        self._last_reset = datetime.now()
        self._pending_digests: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # asyncio.Lock for async coroutine coordination within a single event loop
        self._rate_limit_lock = asyncio.Lock()
        # threading.Lock for cross-thread safety in multi-worker deployments
        self._thread_lock = threading.Lock()
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with timeout protection."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def add_recipient(self, recipient: EmailRecipient) -> None:
        """Add an email recipient."""
        self.recipients.append(recipient)

    def remove_recipient(self, email: str) -> bool:
        """Remove a recipient by email address."""
        for i, r in enumerate(self.recipients):
            if r.email == email:
                del self.recipients[i]
                return True
        return False

    async def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits.

        Checks the distributed rate limiter first (if available and enabled),
        then falls back to the local per-instance rate limit.
        """
        # Check distributed rate limiter first
        if self.config.enable_distributed_rate_limit:
            limiter = _get_distributed_rate_limiter()
            if limiter is not None:
                result = await limiter.acquire(
                    self.config.oauth_tenant_id,
                    self.config.provider,
                )
                if not result.allowed:
                    logger.warning(
                        "Distributed email rate limit reached (%s), retry after %.1fs",
                        result.limit_type,
                        result.retry_after,
                    )
                    return False
                return True

        # Fallback to local per-instance rate limiting
        async with self._rate_limit_lock:
            with self._thread_lock:
                now = datetime.now()
                elapsed = (now - self._last_reset).total_seconds()

                if elapsed >= 3600:  # 1 hour
                    self._email_count = 0
                    self._last_reset = now

                if self._email_count >= self.config.max_emails_per_hour:
                    logger.warning("Email rate limit reached, skipping email")
                    return False

                self._email_count += 1
                return True

    async def _refresh_oauth_if_needed(self) -> None:
        """Auto-refresh OAuth tokens if they are about to expire.

        Uses the email credential store to check token expiry and
        refreshes using the provider's OAuth flow.
        """
        if not self.config.enable_oauth_refresh:
            return

        store = _get_credential_store()
        if store is None:
            return

        try:
            credential = await store.get(
                self.config.oauth_tenant_id,
                self.config.provider,
                self.config.from_email,
            )
            if credential is None or not credential.needs_refresh():
                return

            if not credential.refresh_token:
                logger.warning(
                    "OAuth token expiring but no refresh token available for %s",
                    self.config.from_email,
                )
                return

            # Attempt refresh via provider-specific endpoint
            new_token = await self._do_oauth_refresh(credential)
            if new_token:
                credential.access_token = new_token["access_token"]
                if "refresh_token" in new_token:
                    credential.refresh_token = new_token["refresh_token"]
                if "expires_in" in new_token:
                    from datetime import timezone

                    credential.token_expiry = datetime.now(timezone.utc) + timedelta(
                        seconds=new_token["expires_in"]
                    )
                credential.failure_count = 0
                credential.last_error = ""
                await store.save(credential)
                await store.reset_failures(
                    credential.tenant_id,
                    credential.provider,
                    credential.email_address,
                )
                logger.info("OAuth token refreshed for %s", self.config.from_email)
            else:
                await store.record_failure(
                    credential.tenant_id,
                    credential.provider,
                    credential.email_address,
                    "Token refresh returned empty response",
                )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            logger.warning("OAuth token refresh failed: %s", e)
        except (ValueError, KeyError) as e:
            logger.warning("OAuth token refresh parse error: %s", e)

    async def _do_oauth_refresh(self, credential: Any) -> dict[str, Any] | None:
        """Execute OAuth token refresh for a given credential.

        Supports Gmail and Microsoft OAuth2 refresh flows.
        """
        session = await self._get_session()
        provider = credential.provider

        if provider in ("gmail", "google"):
            token_url = "https://oauth2.googleapis.com/token"  # noqa: S105 -- OAuth endpoint URL
        elif provider in ("microsoft", "outlook", "office365"):
            token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"  # noqa: S105 -- OAuth endpoint URL
        else:
            logger.debug("OAuth refresh not supported for provider: %s", provider)
            return None

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": credential.refresh_token,
            "client_id": credential.client_id,
            "client_secret": credential.client_secret,
        }

        async with session.post(
            token_url,
            data=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status == 200:
                return await response.json()
            text = await response.text()
            logger.warning(
                "OAuth refresh failed for %s: %s %s",
                provider,
                response.status,
                text[:200],
            )
            return None

    def _get_circuit_breaker(self) -> Any:
        """Get circuit breaker for current provider."""
        if not self.config.enable_circuit_breaker:
            return None
        return _get_email_circuit_breaker(
            self.config.provider,
            threshold=self.config.circuit_breaker_threshold,
            cooldown=self.config.circuit_breaker_cooldown,
        )

    def _check_circuit_breaker(self) -> tuple[bool, str | None]:
        """Check if circuit breaker allows the request."""
        cb = self._get_circuit_breaker()
        if cb is None:
            return True, None
        if not cb.can_proceed():
            remaining = cb.cooldown_remaining()
            error = (
                f"Email circuit breaker open for {self.config.provider}. Retry in {remaining:.1f}s"
            )
            logger.warning(error)
            return False, error
        return True, None

    def _record_success(self) -> None:
        """Record successful email send."""
        cb = self._get_circuit_breaker()
        if cb:
            cb.record_success()

    def _record_failure(self, error: Exception | None = None) -> None:
        """Record failed email send."""
        cb = self._get_circuit_breaker()
        if cb:
            cb.record_failure()
            status = cb.get_status()
            if status == "open":
                logger.warning(
                    "Email circuit breaker OPENED for %s after repeated failures",
                    self.config.provider,
                )

    def get_health_status(self) -> dict[str, Any]:
        """Get health status of email integration."""
        cb = self._get_circuit_breaker()
        cb_status = "unknown"
        if cb:
            cb_status = cb.get_status()

        return {
            "provider": self.config.provider,
            "configured": bool(
                self.config.smtp_host
                or self.config.sendgrid_api_key
                or self.config.ses_access_key_id
            ),
            "circuit_breaker_enabled": self.config.enable_circuit_breaker,
            "circuit_breaker_status": cb_status,
            "emails_sent_this_hour": self._email_count,
            "rate_limit": self.config.max_emails_per_hour,
            "recipients_count": len(self.recipients),
        }

    async def _send_email(
        self,
        recipient: EmailRecipient,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send an email with retry logic and circuit breaker.

        Dispatches to the appropriate provider based on configuration.
        Includes OAuth auto-refresh, circuit breaker, and rate limiting.
        """
        # Refresh OAuth tokens if needed
        await self._refresh_oauth_if_needed()

        # Check circuit breaker first
        can_proceed, error_msg = self._check_circuit_breaker()
        if not can_proceed:
            logger.warning("Email send blocked: %s", error_msg)
            return False

        if not await self._check_rate_limit():
            return False

        provider = self.config.email_provider

        for attempt in range(self.config.max_retries):
            try:
                if provider == EmailProvider.SENDGRID:
                    success = await self._send_via_sendgrid(
                        recipient, subject, html_body, text_body
                    )
                elif provider == EmailProvider.SES:
                    success = await self._send_via_ses(recipient, subject, html_body, text_body)
                else:
                    # Default to SMTP
                    success = await self._send_via_smtp(recipient, subject, html_body, text_body)

                if success:
                    self._record_success()
                    logger.debug("Email sent to %s via %s", recipient.email, provider.value)
                    return True

                # If not successful but no exception, record failure and retry
                self._record_failure()
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (2**attempt))
                    continue
                return False

            except aiohttp.ClientError as e:
                logger.error("Email network error via %s: %s", provider.value, e)
                self._record_failure(e)
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (2**attempt))
                    continue
                return False
            except asyncio.TimeoutError as e:
                logger.error("Email request timed out via %s", provider.value)
                self._record_failure(e)
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (2**attempt))
                    continue
                return False
            except smtplib.SMTPException as e:
                logger.error("SMTP error via %s: %s", provider.value, e)
                self._record_failure(e)
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (2**attempt))
                    continue
                return False
            except OSError as e:
                # Network/socket errors
                logger.error("Email connection error via %s: %s", provider.value, e)
                self._record_failure(e)
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (2**attempt))
                    continue
                return False

        return False

    async def _send_via_smtp(
        self,
        recipient: EmailRecipient,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send email via SMTP."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.config.from_name} <{self.config.from_email}>"
        msg["To"] = recipient.formatted
        msg["List-Unsubscribe"] = (
            f"<mailto:unsubscribe@aragora.ai?subject=unsubscribe-{recipient.email}>"
        )

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # Run in thread pool to avoid blocking
        await asyncio.get_running_loop().run_in_executor(
            None,
            self._smtp_send,
            msg,
            recipient.email,
        )
        return True

    async def _send_via_sendgrid(
        self,
        recipient: EmailRecipient,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send email via SendGrid Web API v3.

        SendGrid API documentation: https://docs.sendgrid.com/api-reference/mail-send/mail-send
        """
        session = await self._get_session()

        # Build SendGrid payload
        payload: dict[str, Any] = {
            "personalizations": [
                {
                    "to": [{"email": recipient.email}],
                }
            ],
            "from": {
                "email": self.config.from_email,
                "name": self.config.from_name,
            },
            "subject": subject,
            "content": [],
        }

        # Add recipient name if available
        if recipient.name:
            payload["personalizations"][0]["to"][0]["name"] = recipient.name

        # Add reply-to if configured
        if self.config.reply_to:
            payload["reply_to"] = {"email": self.config.reply_to}

        # Add content (plain text first, then HTML)
        if text_body:
            payload["content"].append({"type": "text/plain", "value": text_body})
        payload["content"].append({"type": "text/html", "value": html_body})

        # Tracking settings
        payload["tracking_settings"] = {
            "click_tracking": {"enable": self.config.enable_click_tracking},
            "open_tracking": {"enable": self.config.enable_open_tracking},
        }

        # Add unsubscribe header
        payload["headers"] = {
            "List-Unsubscribe": f"<mailto:unsubscribe@aragora.ai?subject=unsubscribe-{recipient.email}>"
        }

        headers = {
            "Authorization": f"Bearer {self.config.sendgrid_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with session.post(
                self.SENDGRID_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status in (200, 202):
                    return True
                else:
                    text = await response.text()
                    logger.error("SendGrid API error: %s - %s", response.status, text)
                    return False
        except aiohttp.ClientError as e:
            logger.error("SendGrid connection error: %s", e)
            return False

    async def _send_via_ses(
        self,
        recipient: EmailRecipient,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send email via AWS SES.

        Uses AWS SES SendEmail API with Signature Version 4.
        For simplicity, uses boto3 if available, otherwise falls back to direct API.
        """
        try:
            # Try using boto3 (preferred method)
            import boto3
            from botocore.config import Config

            config = Config(
                region_name=self.config.ses_region,
                retries={"max_attempts": 1},  # We handle retries ourselves
            )

            # Create SES client with explicit credentials if provided
            if self.config.ses_access_key_id and self.config.ses_secret_access_key:
                ses_client = boto3.client(
                    "ses",
                    config=config,
                    aws_access_key_id=self.config.ses_access_key_id,
                    aws_secret_access_key=self.config.ses_secret_access_key,
                )
            else:
                # Use default credential chain (env vars, IAM role, etc.)
                ses_client = boto3.client("ses", config=config)

            # Build email message
            message: dict[str, Any] = {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            }

            if text_body:
                message["Body"]["Text"] = {"Data": text_body, "Charset": "UTF-8"}

            # Send email
            response = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: ses_client.send_email(
                    Source=f"{self.config.from_name} <{self.config.from_email}>",
                    Destination={"ToAddresses": [recipient.email]},
                    Message=message,
                    ReplyToAddresses=[self.config.reply_to] if self.config.reply_to else [],
                ),
            )

            message_id = response.get("MessageId")
            if message_id:
                logger.debug("SES message sent: %s", message_id)
                return True
            return False

        except ImportError:
            logger.error("boto3 is required for AWS SES. Install with: pip install boto3")
            return False
        except Exception as e:  # noqa: BLE001 - botocore exceptions (ClientError, etc.) may not be importable
            error_name = type(e).__name__
            if "ClientError" in error_name or "Botocore" in error_name:
                logger.error("SES AWS error: %s", e)
            else:
                logger.error("SES send error: %s", e, exc_info=True)
            return False

    def _smtp_send(self, msg: MIMEMultipart, to_email: str) -> None:
        """Send email via SMTP (synchronous, called from executor).

        Includes timeout protection to prevent indefinite hangs.
        """
        timeout = self.config.smtp_timeout

        if self.config.use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                self.config.smtp_host,
                self.config.smtp_port,
                context=context,
                timeout=timeout,
            ) as server:
                if self.config.smtp_username:
                    server.login(self.config.smtp_username, self.config.smtp_password)
                server.sendmail(self.config.from_email, to_email, msg.as_string())
        else:
            with smtplib.SMTP(
                self.config.smtp_host,
                self.config.smtp_port,
                timeout=timeout,
            ) as server:
                if self.config.use_tls:
                    server.starttls()
                if self.config.smtp_username:
                    server.login(self.config.smtp_username, self.config.smtp_password)
                server.sendmail(self.config.from_email, to_email, msg.as_string())

    def _get_email_styles(self) -> str:
        """Get inline CSS styles for emails."""
        return """
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }
            .container { max-width: 600px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #00ff00, #00cc00); color: #000; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }
            .content { background: #f9f9f9; padding: 20px; border: 1px solid #e0e0e0; }
            .footer { background: #333; color: #999; padding: 15px; text-align: center; font-size: 12px; border-radius: 0 0 8px 8px; }
            .status-success { color: #00cc00; }
            .status-fail { color: #cc0000; }
            .metric { display: inline-block; background: #fff; border: 1px solid #e0e0e0; padding: 10px 15px; margin: 5px; border-radius: 4px; }
            .metric-label { font-size: 12px; color: #666; display: block; }
            .metric-value { font-size: 18px; font-weight: bold; color: #333; }
            .button { display: inline-block; background: #00cc00; color: #000; padding: 10px 20px; text-decoration: none; border-radius: 4px; font-weight: bold; margin: 10px 0; }
            .code { background: #f0f0f0; padding: 15px; border-radius: 4px; font-family: monospace; font-size: 13px; overflow-x: auto; }
            .divider { border-top: 1px solid #e0e0e0; margin: 20px 0; }
        </style>
        """

    async def send_debate_summary(
        self,
        result: DebateResult,
        recipients: list[EmailRecipient] | None = None,
    ) -> int:
        """Send a debate summary to recipients.

        Args:
            result: The debate result to summarize
            recipients: Optional list of recipients (defaults to all)

        Returns:
            Number of emails sent successfully
        """
        if not self.config.notify_on_debate_end:
            return 0

        recipients = recipients or self.recipients
        if not recipients:
            return 0

        subject = f"Debate Completed: {result.task[:50]}..."
        html_body = self._build_debate_summary_html(result)
        text_body = self._build_debate_summary_text(result)

        # Add to pending digest
        if self.config.enable_digest:
            self._add_to_digest(
                {
                    "type": "debate_summary",
                    "result": result,
                    "timestamp": datetime.now(),
                }
            )

        sent = 0
        for recipient in recipients:
            if await self._send_email(recipient, subject, html_body, text_body):
                sent += 1

        return sent

    def _build_debate_summary_html(self, result: DebateResult) -> str:
        """Build HTML email for debate summary."""
        status_class = "status-success" if result.consensus_reached else "status-fail"
        status_text = "Consensus Reached" if result.consensus_reached else "No Consensus"
        confidence = getattr(result, "confidence", 0.0)

        final_answer_html = ""
        if result.consensus_reached and result.final_answer:
            preview = result.final_answer[:600].replace("\n", "<br>")
            if len(result.final_answer) > 600:
                preview += "..."
            final_answer_html = f"""
            <div class="divider"></div>
            <h3>Final Proposal</h3>
            <div class="code">{preview}</div>
            """

        debate_id = getattr(result, "debate_id", "unknown")

        return f"""
        <!DOCTYPE html>
        <html>
        <head>{self._get_email_styles()}</head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Debate Completed</h1>
                </div>
                <div class="content">
                    <h2>{result.task}</h2>

                    <div style="text-align: center; margin: 20px 0;">
                        <div class="metric">
                            <span class="metric-label">Status</span>
                            <span class="metric-value {status_class}">{status_text}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Confidence</span>
                            <span class="metric-value">{confidence:.0%}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Rounds</span>
                            <span class="metric-value">{result.rounds_used}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Winner</span>
                            <span class="metric-value">{result.winner or "None"}</span>
                        </div>
                    </div>

                    {final_answer_html}

                    <div style="text-align: center; margin-top: 20px;">
                        <a href="https://aragora.ai/debate/{debate_id}" class="button">View Full Debate</a>
                    </div>
                </div>
                <div class="footer">
                    <p>Aragora AI Debate System</p>
                    <p><a href="mailto:unsubscribe@aragora.ai?subject=unsubscribe" style="color: #666;">Unsubscribe</a></p>
                </div>
            </div>
        </body>
        </html>
        """

    def _build_debate_summary_text(self, result: DebateResult) -> str:
        """Build plain text email for debate summary."""
        status = "REACHED" if result.consensus_reached else "NOT REACHED"
        confidence = getattr(result, "confidence", 0.0)

        lines = [
            "DEBATE COMPLETED",
            "=" * 40,
            "",
            f"Task: {result.task}",
            "",
            f"Consensus: {status}",
            f"Confidence: {confidence:.0%}",
            f"Rounds: {result.rounds_used}",
            f"Winner: {result.winner or 'None'}",
        ]

        if result.consensus_reached and result.final_answer:
            preview = result.final_answer[:400]
            if len(result.final_answer) > 400:
                preview += "..."
            lines.extend(["", "Final Proposal:", preview])

        lines.extend(
            [
                "",
                "-" * 40,
                "Aragora AI Debate System",
                "To unsubscribe, reply with UNSUBSCRIBE",
            ]
        )

        return "\n".join(lines)

    async def send_consensus_alert(
        self,
        debate_id: str,
        confidence: float,
        winner: str | None = None,
        task: str | None = None,
        recipients: list[EmailRecipient] | None = None,
    ) -> int:
        """Send a consensus reached notification.

        Returns:
            Number of emails sent successfully
        """
        if not self.config.notify_on_consensus:
            return 0

        if confidence < self.config.min_consensus_confidence:
            return 0

        recipients = recipients or self.recipients
        if not recipients:
            return 0

        subject = f"Consensus Reached! ({confidence:.0%} confidence)"
        html_body = self._build_consensus_alert_html(debate_id, confidence, winner, task)
        text_body = self._build_consensus_alert_text(debate_id, confidence, winner, task)

        sent = 0
        for recipient in recipients:
            if await self._send_email(recipient, subject, html_body, text_body):
                sent += 1

        return sent

    def _build_consensus_alert_html(
        self,
        debate_id: str,
        confidence: float,
        winner: str | None,
        task: str | None,
    ) -> str:
        """Build HTML email for consensus alert."""
        task_html = f"<p><strong>Task:</strong> {task}</p>" if task else ""
        winner_html = f"<p><strong>Winner:</strong> {winner}</p>" if winner else ""

        return f"""
        <!DOCTYPE html>
        <html>
        <head>{self._get_email_styles()}</head>
        <body>
            <div class="container">
                <div class="header" style="background: linear-gradient(135deg, #ffd700, #ffcc00);">
                    <h1>Consensus Reached!</h1>
                </div>
                <div class="content">
                    {task_html}

                    <div style="text-align: center; margin: 20px 0;">
                        <div class="metric">
                            <span class="metric-label">Debate</span>
                            <span class="metric-value">{debate_id[:8]}...</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Confidence</span>
                            <span class="metric-value status-success">{confidence:.0%}</span>
                        </div>
                    </div>

                    {winner_html}

                    <div style="text-align: center;">
                        <a href="https://aragora.ai/debate/{debate_id}" class="button">View Debate</a>
                    </div>
                </div>
                <div class="footer">
                    <p>Aragora AI Debate System</p>
                </div>
            </div>
        </body>
        </html>
        """

    def _build_consensus_alert_text(
        self,
        debate_id: str,
        confidence: float,
        winner: str | None,
        task: str | None,
    ) -> str:
        """Build plain text email for consensus alert."""
        lines = [
            "CONSENSUS REACHED!",
            "=" * 40,
            "",
            f"Debate: {debate_id[:8]}...",
            f"Confidence: {confidence:.0%}",
        ]
        if winner:
            lines.append(f"Winner: {winner}")
        if task:
            lines.extend(["", f"Task: {task}"])
        lines.extend(
            [
                "",
                f"View: https://aragora.ai/debate/{debate_id}",
            ]
        )
        return "\n".join(lines)

    def _add_to_digest(self, item: dict[str, Any]) -> None:
        """Add an item to the pending digest (thread-safe)."""
        with self._thread_lock:
            date_key = datetime.now().strftime("%Y-%m-%d")
            self._pending_digests[date_key].append(item)

    async def send_digest(
        self,
        recipients: list[EmailRecipient] | None = None,
    ) -> int:
        """Send a digest of recent debates.

        Returns:
            Number of emails sent successfully
        """
        if not self.config.enable_digest:
            return 0

        recipients = recipients or self.recipients
        if not recipients:
            return 0

        # Get items for digest
        items: list[dict[str, Any]] = []
        cutoff = datetime.now() - timedelta(
            days=7 if self.config.digest_frequency == "weekly" else 1
        )

        with self._thread_lock:
            for date_key, day_items in list(self._pending_digests.items()):
                date = datetime.strptime(date_key, "%Y-%m-%d")
                if date >= cutoff:
                    items.extend(day_items)
                else:
                    # Clean up old items
                    del self._pending_digests[date_key]

        if not items:
            return 0

        subject = f"Aragora Debate Digest - {len(items)} debates"
        html_body = self._build_digest_html(items)
        text_body = self._build_digest_text(items)

        sent = 0
        for recipient in recipients:
            if await self._send_email(recipient, subject, html_body, text_body):
                sent += 1

        return sent

    def _build_digest_html(self, items: list[dict[str, Any]]) -> str:
        """Build HTML email for digest."""
        debates_html = ""
        for item in items:
            if item["type"] == "debate_summary":
                result = item["result"]
                status = "Consensus" if result.consensus_reached else "No Consensus"
                debates_html += f"""
                <div style="border-bottom: 1px solid #e0e0e0; padding: 15px 0;">
                    <strong>{result.task[:80]}{"..." if len(result.task) > 80 else ""}</strong>
                    <br>
                    <span style="color: #666;">Status: {status} | Winner: {result.winner or "None"}</span>
                </div>
                """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>{self._get_email_styles()}</head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Debate Digest</h1>
                    <p>{len(items)} debates in the last {self.config.digest_frequency.replace("ly", "")}</p>
                </div>
                <div class="content">
                    {debates_html}
                    <div style="text-align: center; margin-top: 20px;">
                        <a href="https://aragora.ai/debates" class="button">View All Debates</a>
                    </div>
                </div>
                <div class="footer">
                    <p>Aragora AI Debate System</p>
                    <p><a href="mailto:unsubscribe@aragora.ai?subject=unsubscribe" style="color: #666;">Unsubscribe</a></p>
                </div>
            </div>
        </body>
        </html>
        """

    def _build_digest_text(self, items: list[dict[str, Any]]) -> str:
        """Build plain text email for digest."""
        lines = [
            "ARAGORA DEBATE DIGEST",
            f"{len(items)} debates in the last {self.config.digest_frequency.replace('ly', '')}",
            "=" * 40,
            "",
        ]

        for item in items:
            if item["type"] == "debate_summary":
                result = item["result"]
                status = "Consensus" if result.consensus_reached else "No Consensus"
                lines.extend(
                    [
                        f"- {result.task[:60]}{'...' if len(result.task) > 60 else ''}",
                        f"  Status: {status} | Winner: {result.winner or 'None'}",
                        "",
                    ]
                )

        lines.extend(
            [
                "View all: https://aragora.ai/debates",
                "",
                "To unsubscribe, reply with UNSUBSCRIBE",
            ]
        )

        return "\n".join(lines)

    async def __aenter__(self) -> EmailIntegration:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


__all__ = [
    "EmailConfig",
    "EmailProvider",
    "EmailRecipient",
    "EmailIntegration",
]
