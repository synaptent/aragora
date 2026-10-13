"""
WebConnector - Live web access for aragora agents.

Provides web search and URL content fetching capabilities,
enabling agents to access real-time information during debates.

Features:
- Web search via DuckDuckGo (no API key required)
- URL content fetching with HTML parsing
- Domain authority scoring
- Rate limiting and caching
"""

__all__ = [
    "DOMAIN_AUTHORITY",
    "WebConnector",
]

import asyncio
import hashlib
import importlib.util
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from aragora.config import DB_TIMEOUT_SECONDS
from aragora.connectors.base import BaseConnector, Evidence
from aragora.resilience import CircuitBreaker

logger = logging.getLogger(__name__)
from aragora.reasoning.provenance import ProvenanceManager, SourceType

# Try to import optional dependencies
try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    from bs4 import BeautifulSoup

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

DDGS_AVAILABLE = importlib.util.find_spec("duckduckgo_search") is not None

# Domain authority scores (0-1) for common sources
DOMAIN_AUTHORITY = {
    # High authority (0.9+)
    "wikipedia.org": 0.95,
    "gov": 0.9,  # .gov domains
    "edu": 0.9,  # .edu domains
    "nature.com": 0.95,
    "science.org": 0.95,
    "arxiv.org": 0.9,
    "github.com": 0.85,
    # Medium-high authority (0.7-0.9)
    "stackoverflow.com": 0.85,
    "docs.python.org": 0.9,
    "developer.mozilla.org": 0.9,
    "microsoft.com": 0.8,
    "google.com": 0.8,
    "anthropic.com": 0.85,
    "openai.com": 0.85,
    # Medium authority (0.5-0.7)
    "medium.com": 0.6,
    "dev.to": 0.65,
    "reddit.com": 0.5,
    "twitter.com": 0.5,
    "x.com": 0.5,
    # Lower authority (news/blogs vary)
    "nytimes.com": 0.8,
    "bbc.com": 0.8,
    "reuters.com": 0.85,
}


_DDGS_SUBPROCESS_CODE = """
import json
import sys
import warnings

from duckduckgo_search import DDGS

rename_warning_pattern = r"This package .* has been renamed to `ddgs`!.*"
original_simplefilter = warnings.simplefilter


def _safe_simplefilter(
    action: str,
    category: type[Warning] = Warning,
    lineno: int = 0,
    append: bool = False,
) -> None:
    if action == "always":
        original_simplefilter(
            action,
            category=category,
            lineno=lineno,
            append=True,
        )
        return
    original_simplefilter(
        action,
        category=category,
        lineno=lineno,
        append=append,
    )


warnings.simplefilter = _safe_simplefilter
try:
    query = sys.argv[1]
    region = sys.argv[2]
    max_results = int(sys.argv[3])
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=rename_warning_pattern,
            category=RuntimeWarning,
        )
        ddgs_client = DDGS()
    results = list(ddgs_client.text(query, region=region, max_results=max_results))
    sys.stdout.write(json.dumps(results))
finally:
    warnings.simplefilter = original_simplefilter
"""


class WebConnector(BaseConnector):
    """
    Connector for live web search and content fetching.

    Enables agents to:
    - Search the web for relevant information
    - Fetch and parse content from URLs
    - Track source authority and freshness

    Example:
        connector = WebConnector()
        results = await connector.search("latest Python 3.12 features")
        for evidence in results:
            print(f"{evidence.title}: {evidence.content[:100]}...")
    """

    def __init__(
        self,
        provenance: ProvenanceManager | None = None,
        default_confidence: float = 0.6,
        timeout: int = 30,
        max_content_length: int = 10000,
        rate_limit_delay: float = 1.0,
        cache_dir: str = ".web_cache",
        circuit_breaker: CircuitBreaker | None = None,
        enable_circuit_breaker: bool = True,
    ):
        """
        Initialize WebConnector.

        Args:
            provenance: Optional provenance manager for tracking
            default_confidence: Base confidence for web sources
            timeout: HTTP request timeout in seconds
            max_content_length: Max chars to extract from pages
            rate_limit_delay: Delay between requests (seconds)
            cache_dir: Directory for caching search results
            circuit_breaker: Optional shared circuit breaker instance
            enable_circuit_breaker: Whether to enable circuit breaker protection
        """
        super().__init__(provenance, default_confidence)
        self.timeout = timeout
        self.max_content_length = max_content_length
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time = 0.0
        self._http_client: httpx.AsyncClient | None = None

        # Initialize cache
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

        # Circuit breaker for graceful failure handling
        # Use provided circuit breaker or create a new local instance
        if circuit_breaker is not None:
            self._circuit_breaker = circuit_breaker
        elif enable_circuit_breaker:
            self._circuit_breaker = CircuitBreaker(
                failure_threshold=5,  # Higher threshold for web - transient errors common
                cooldown_seconds=30.0,  # Shorter cooldown - web may recover quickly
            )
        else:
            self._circuit_breaker = None

        # Check dependencies
        if not HTTPX_AVAILABLE:
            logger.debug("httpx not installed - URL fetching will be limited")
        if not BS4_AVAILABLE:
            logger.debug("beautifulsoup4 not installed - HTML parsing will be limited")
        if not DDGS_AVAILABLE:
            logger.debug("duckduckgo-search not installed - web search will be unavailable")

    @property
    def source_type(self) -> SourceType:
        return SourceType.WEB_SEARCH

    @property
    def name(self) -> str:
        return "Web Search"

    async def _get_http_client(self) -> "httpx.AsyncClient":
        """Get or create shared HTTP client with connection pooling.

        Note: Redirects are disabled to allow manual validation of each
        redirect target for SSRF protection.
        """
        if self._http_client is None:
            try:
                self._http_client = httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=False,  # Disabled for SSRF protection
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
                )
            except (httpx.HTTPError, OSError, ValueError) as e:
                logger.error("Failed to create HTTP client: %s", e)
                raise  # Fail fast instead of retrying infinitely
        return self._http_client

    async def cleanup(self) -> None:
        """Clean up HTTP client on shutdown."""
        if self._http_client:
            try:
                await self._http_client.aclose()
            except (OSError, RuntimeError, TypeError, AttributeError) as e:
                logger.warning("Error closing HTTP client: %s", e)
            finally:
                self._http_client = None

    async def search(
        self,
        query: str,
        limit: int = 10,
        region: str = "wt-wt",  # Worldwide
        **kwargs,
    ) -> list[Evidence]:
        """
        Search the web for relevant content.

        Args:
            query: Search query
            limit: Maximum results
            region: DuckDuckGo region code

        Returns:
            List of Evidence objects from search results
        """
        # Check cache first for deterministic behavior
        cache_file = self._get_cache_file(query)
        if cache_file.exists():
            try:
                cached_data = json.loads(cache_file.read_text())
                # Properly reconstruct Evidence objects from cache
                return [Evidence.from_dict(e) for e in cached_data["results"]]
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                # If cache is corrupted, proceed with search
                logger.debug("Cache load failed for query '%s': %s", query[:50], e)
            except OSError as e:
                # File system error, proceed with search
                logger.debug("Cache file read error for query '%s': %s", query[:50], e)

        # Use test seam for actual search (allows mocking in tests)
        return await self._search_web_actual(query, limit, region)

    async def _search_web_actual(
        self,
        query: str,
        limit: int = 10,
        region: str = "wt-wt",
    ) -> list[Evidence]:
        """
        Perform the actual web search. Isolated as test seam for mocking.

        This method is called by search() after cache check.
        Mock this in tests to avoid network calls.
        """
        if not DDGS_AVAILABLE:
            return [
                self._create_error_evidence(
                    "duckduckgo-search not installed. Run: pip install duckduckgo-search"
                )
            ]

        await self._rate_limit()

        try:
            results = await self._run_ddgs_search_subprocess(
                query=query,
                region=region,
                limit=limit,
            )

            evidence_list = []
            for result in results:
                evidence = self._result_to_evidence(result, query)
                evidence_list.append(evidence)
                self._cache_put(evidence.id, evidence)

            # Cache the results
            self._save_to_cache(query, evidence_list)

            return evidence_list

        except (ConnectionError, OSError) as e:
            return [self._create_error_evidence(f"Network error during search: {e}")]
        except RuntimeError as e:
            # DuckDuckGo library can raise RuntimeError for various issues
            return [self._create_error_evidence(f"Search service error: {e}")]
        except (ValueError, TypeError, AttributeError) as e:
            # Handle other common errors from search library
            logger.warning("Search error: %s: %s", type(e).__name__, e)
            return [self._create_error_evidence(f"Search failed: {e}")]

    async def _run_ddgs_search_subprocess(
        self,
        *,
        query: str,
        region: str,
        limit: int,
    ) -> list[dict]:
        """Run DDGS in a subprocess so native panics can't abort the parent process."""
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _DDGS_SUBPROCESS_CODE,
            query,
            region,
            str(limit),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=DB_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            logger.warning("DDGS search timed out for query: %s...", query[:50])
            raise RuntimeError(f"Search timed out for: {query[:50]}") from exc

        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            if stderr_text:
                stderr_text = stderr_text.splitlines()[-1]
            else:
                stderr_text = f"exit code {process.returncode}"
            raise RuntimeError(f"DDGS subprocess failed: {stderr_text}")

        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("DDGS subprocess returned invalid JSON") from exc

    def _is_local_ip(self, url: str) -> bool:
        """Check if URL points to local/private IP ranges for security."""
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname

            if not hostname:
                return False

            # Check for localhost
            if hostname in ("localhost", "127.0.0.1", "::1"):
                return True

            # Parse IP address
            import ipaddress

            try:
                ip = ipaddress.ip_address(hostname)
                # Block private ranges: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16
                return ip.is_private or ip.is_loopback or ip.is_link_local
            except ValueError:
                # Not an IP address, allow
                return False

        except (ValueError, OSError) as e:
            # If parsing fails, err on side of caution
            logger.warning("[web] URL security validation failed for %s: %s", url, e)
            return True

    def _resolve_and_validate_ip(self, url: str) -> tuple[bool, str]:
        """
        Resolve hostname to IP and validate it's not private/local.

        Security measures:
        - Uses getaddrinfo() for IPv4+IPv6 support (not just gethostbyname)
        - Validates ALL resolved IPs, not just the first one
        - Blocks on DNS failure (fail-closed, not fail-open)
        - Checks multicast addresses

        Returns:
            Tuple of (is_safe, error_message). If is_safe is False,
            error_message contains the reason.
        """
        import ipaddress
        import socket

        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            if not hostname:
                return False, "No hostname in URL"

            # Check for obvious localhost
            if hostname in ("localhost", "127.0.0.1", "::1"):
                return False, "Localhost access blocked"

            # Resolve hostname to ALL IPs (IPv4 + IPv6)
            try:
                addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
            except socket.gaierror as e:
                # DNS resolution failed - BLOCK (fail-closed for security)
                logger.warning("DNS resolution failed for %s: %s", hostname, e)
                return False, f"DNS resolution failed: {e}"

            if not addr_info:
                return False, f"DNS resolution returned no results for {hostname}"

            # Validate ALL resolved IPs (prevents DNS rebinding attacks)
            for family, socktype, proto, canonname, sockaddr in addr_info:
                ip_str = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    if ip.is_private:
                        return False, f"Resolved to private IP: {ip_str}"
                    if ip.is_loopback:
                        return False, f"Resolved to loopback IP: {ip_str}"
                    if ip.is_link_local:
                        return False, f"Resolved to link-local IP: {ip_str}"
                    if ip.is_reserved:
                        return False, f"Resolved to reserved IP: {ip_str}"
                    if ip.is_multicast:
                        return False, f"Resolved to multicast IP: {ip_str}"
                except ValueError:
                    return False, f"Invalid IP address format: {ip_str}"

            return True, ""

        except (ValueError, OSError) as e:
            logger.warning("[web] IP validation error for %s: %s", url, e)
            return False, f"Security validation error: {e}"

    def _validate_redirect_target(self, redirect_url: str) -> tuple[bool, str]:
        """
        Validate a redirect URL before following it.

        Prevents SSRF via open redirects that lead to internal services.
        """
        # Check basic URL format
        if not redirect_url:
            return False, "Empty redirect URL"

        # Must be http/https
        parsed = urlparse(redirect_url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Invalid redirect scheme: {parsed.scheme}"

        # Validate the target IP
        return self._resolve_and_validate_ip(redirect_url)

    def _get_cache_file(self, query: str) -> Path:
        """Get the cache file path for a query."""
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        return self.cache_dir / f"{query_hash}.json"

    def _save_to_cache(self, query: str, results: list[Evidence]) -> None:
        """Save search results to cache with proper serialization."""
        cache_file = self._get_cache_file(query)
        cache_data = {
            "query": query,
            "timestamp": datetime.now().isoformat(),
            # Properly serialize Evidence objects for round-trip
            "results": [e.to_dict() for e in results],
        }
        try:
            cache_file.write_text(json.dumps(cache_data, indent=2))
        except (OSError, TypeError, ValueError) as e:
            # If caching fails, don't break the search
            logger.debug("Failed to cache search results: %s", e)

    async def fetch(self, evidence_id: str) -> Evidence | None:
        """
        Fetch full content for a piece of evidence.

        If evidence_id is a URL, fetches and parses the page.
        Otherwise looks up cached evidence and fetches its URL.
        """
        # Check cache first
        cached = self._cache_get(evidence_id)
        if cached is not None:
            # If we have full content, return it
            if len(cached.content) > 500:
                return cached
            # Otherwise fetch full content from URL
            if cached.url:
                return await self.fetch_url(cached.url)

        # If evidence_id looks like a URL, fetch it directly
        if evidence_id.startswith("http"):
            return await self.fetch_url(evidence_id)

        return None

    async def fetch_url(
        self,
        url: str,
        max_redirects: int = 5,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> Evidence | None:
        """
        Fetch and parse content from a URL with SSRF protection and retry logic.

        Args:
            url: URL to fetch
            max_redirects: Maximum number of redirects to follow
            max_retries: Maximum retry attempts for transient failures
            base_delay: Base delay between retries (exponential backoff)

        Returns:
            Evidence object with parsed content, or None on failure
        """
        if not HTTPX_AVAILABLE:
            return self._create_error_evidence("httpx not installed")

        # Check circuit breaker before attempting fetch
        if self._circuit_breaker is not None and not self._circuit_breaker.can_proceed():
            return self._create_error_evidence(
                f"Circuit breaker open - web requests temporarily disabled "
                f"(cooldown: {self._circuit_breaker.cooldown_seconds}s)"
            )

        # Security check: Block local/private IP ranges
        if self._is_local_ip(url):
            return self._create_error_evidence("Access to local/private IPs blocked for security")

        # SSRF protection: Resolve and validate IP before fetching
        from aragora.security.ssrf_protection import validate_url as _validate_url

        _ssrf_result = _validate_url(url, resolve_dns=True)
        if not _ssrf_result.is_safe:
            return self._create_error_evidence(f"SSRF protection: {_ssrf_result.error}")

        is_safe, error_msg = self._resolve_and_validate_ip(url)
        if not is_safe:
            return self._create_error_evidence(f"SSRF protection: {error_msg}")

        last_error: Exception | None = None

        for attempt in range(max_retries):
            await self._rate_limit()

            current_url = url
            redirect_count = 0

            try:
                client = await self._get_http_client()
                # Normalize AsyncMock side_effect lists to iterators (test safety).
                try:
                    side_effect = getattr(client.get, "side_effect", None)
                    if isinstance(side_effect, list):
                        client.get.side_effect = iter(side_effect)  # type: ignore[attr-defined]
                except (AttributeError, TypeError) as e:
                    logger.debug("Mock side_effect normalization skipped: %s", e)

                while redirect_count <= max_redirects:
                    response = await client.get(
                        current_url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (compatible; AragoraBot/1.0; +https://aragora.ai)"
                        },
                    )

                    # Handle redirects manually
                    if response.is_redirect:
                        redirect_count += 1
                        if redirect_count > max_redirects:
                            return self._create_error_evidence(
                                f"Too many redirects (>{max_redirects})"
                            )

                        # Get and validate redirect target
                        redirect_url = response.headers.get("location", "")
                        if not redirect_url:
                            return self._create_error_evidence("Redirect without Location header")

                        # Handle relative URLs
                        if redirect_url.startswith("/"):
                            parsed = urlparse(current_url)
                            redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"

                        # Validate redirect target for SSRF
                        is_safe, error_msg = self._validate_redirect_target(redirect_url)
                        if not is_safe:
                            return self._create_error_evidence(f"Blocked redirect to: {error_msg}")

                        logger.debug("Following redirect: %s -> %s", current_url, redirect_url)
                        current_url = redirect_url
                        continue

                    # Not a redirect, process the response
                    response.raise_for_status()
                    break

                content_type = response.headers.get("content-type", "")

                if "text/html" in content_type:
                    content, title = self._parse_html(response.text)
                elif "application/json" in content_type:
                    content = response.text[: self.max_content_length]
                    title = "JSON Response"
                elif "text/" in content_type:
                    content = response.text[: self.max_content_length]
                    title = "Text Content"
                else:
                    return self._create_error_evidence(f"Unsupported content type: {content_type}")

                evidence_id = hashlib.sha256(url.encode()).hexdigest()[:16]
                domain = urlparse(url).netloc

                evidence = Evidence(
                    id=evidence_id,
                    source_type=SourceType.WEB_SEARCH,
                    source_id=url,
                    content=content,
                    title=title,
                    url=url,
                    author=domain,
                    created_at=datetime.now().isoformat(),
                    confidence=self.default_confidence,
                    authority=self._get_domain_authority(domain),
                    freshness=1.0,  # Just fetched
                    metadata={"fetched_at": datetime.now().isoformat()},
                )

                self._cache_put(evidence_id, evidence)

                # Record success to circuit breaker
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_success()

                return evidence

            except httpx.TimeoutException as e:
                last_error = e
                # Transient - retry with backoff
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
            except httpx.ConnectError as e:
                last_error = e
                # Transient - retry with backoff
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
            except httpx.HTTPStatusError as e:
                last_error = e
                # Only retry on 5xx errors (server errors), not 4xx (client errors)
                if e.response.status_code >= 500:
                    if self._circuit_breaker is not None:
                        self._circuit_breaker.record_failure()
                else:
                    # 4xx errors are not transient - don't retry
                    return self._create_error_evidence(f"HTTP {e.response.status_code} for {url}")
            except httpx.RequestError as e:
                last_error = e
                # Transient - retry with backoff
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
            except (ValueError, TypeError, KeyError) as e:
                # Data parsing/processing errors - don't retry
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                logger.warning("Fetch data error for %s: %s: %s", url, type(e).__name__, e)
                return self._create_error_evidence(f"Error fetching {url}: {e}")

            # If we get here, we had a transient error - apply backoff and retry
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.info(
                    "Fetch failed (attempt %s/%s), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    last_error,
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        logger.warning("All %s fetch attempts failed for %s: %s", max_retries, url, last_error)
        if isinstance(last_error, httpx.TimeoutException):
            return self._create_error_evidence(
                f"Failed after {max_retries} attempts: Timeout: {last_error}"
            )
        return self._create_error_evidence(f"Failed after {max_retries} attempts: {last_error}")

    def _parse_html(self, html: str) -> tuple[str, str]:
        """
        Parse HTML and extract readable content with security sanitization.

        Returns:
            Tuple of (content, title)
        """
        if not BS4_AVAILABLE:
            # Basic extraction without BeautifulSoup
            title_match = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
            title = title_match.group(1) if title_match else "Untitled"

            # Aggressively remove all scripts, styles, and HTML tags for security
            content = re.sub(
                r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
            )
            content = re.sub(
                r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE
            )
            content = re.sub(r"<[^>]+>", " ", content)  # Remove all HTML tags
            content = re.sub(r"\s+", " ", content).strip()

            return content[: self.max_content_length], title

        soup = BeautifulSoup(html, "html.parser")

        # Extract title
        title = soup.title.string if soup.title else "Untitled"

        # Aggressively remove all potentially dangerous elements for security
        for element in soup(
            ["script", "style", "nav", "header", "footer", "aside", "iframe", "object", "embed"]
        ):
            element.decompose()

        # Try to find main content
        main_content = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", {"class": re.compile(r"content|main|body", re.I)})
            or soup.body
        )

        if main_content:
            # Get text with some structure
            paragraphs = main_content.find_all(["p", "h1", "h2", "h3", "h4", "li", "pre", "code"])
            text_parts = []
            for p in paragraphs:
                text = p.get_text(strip=True)
                if len(text) > 5:  # Skip very short elements (punctuation, whitespace)
                    text_parts.append(text)
            content = "\n\n".join(text_parts)
        else:
            content = soup.get_text(separator=" ", strip=True)

        # Final security pass: remove any remaining HTML-like content
        content = re.sub(r"<[^>]*>", "", content)  # Remove any remaining tags
        content = re.sub(r"\s+", " ", content).strip()

        return content[: self.max_content_length], title

    def _result_to_evidence(self, result: dict, query: str) -> Evidence:
        """Convert DuckDuckGo result to Evidence object."""
        url = result.get("href", result.get("link", ""))
        domain = urlparse(url).netloc if url else "unknown"

        evidence_id = hashlib.sha256(f"{url}:{query}".encode()).hexdigest()[:16]

        return Evidence(
            id=evidence_id,
            source_type=SourceType.WEB_SEARCH,
            source_id=url,
            content=result.get("body", result.get("snippet", "")),
            title=result.get("title", ""),
            url=url,
            author=domain,
            created_at=datetime.now().isoformat(),
            confidence=self.default_confidence,
            authority=self._get_domain_authority(domain),
            freshness=1.0,  # Search results are current
            metadata={
                "query": query,
                "position": result.get("position", 0),
            },
        )

    def _get_domain_authority(self, domain: str) -> float:
        """Get authority score for a domain."""
        domain = domain.lower().replace("www.", "")

        # Check exact match
        if domain in DOMAIN_AUTHORITY:
            return DOMAIN_AUTHORITY[domain]

        # Check TLD
        tld = domain.split(".")[-1] if "." in domain else ""
        if tld in DOMAIN_AUTHORITY:
            return DOMAIN_AUTHORITY[tld]

        # Check if any known domain is a suffix
        for known_domain, score in DOMAIN_AUTHORITY.items():
            if domain.endswith(known_domain):
                return score

        # Default for unknown domains
        return 0.5

    def _create_error_evidence(self, error_msg: str) -> Evidence:
        """Create an error evidence object."""
        return Evidence(
            id=hashlib.sha256(error_msg.encode()).hexdigest()[:16],
            source_type=SourceType.WEB_SEARCH,
            source_id="error",
            content=f"[Error]: {error_msg}",
            title="Search Error",
            confidence=0.0,
            authority=0.0,
            freshness=0.0,
        )

    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        import time

        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    # Convenience methods for agent use

    async def search_web(self, query: str, limit: int = 5) -> str:
        """
        Agent-friendly web search that returns formatted results.

        Example:
            results = await connector.search_web("Python async best practices")
        """
        evidence_list = await self.search(query, limit=limit)

        if not evidence_list or evidence_list[0].confidence == 0:
            return f"[No results found for: {query}]"

        results = []
        for i, ev in enumerate(evidence_list, 1):
            results.append(
                f"{i}. **{ev.title}**\n"
                f"   Source: {ev.author} (authority: {ev.authority:.0%})\n"
                f"   {ev.content[:300]}...\n"
                f"   URL: {ev.url}"
            )

        return f"## Web Search Results for: {query}\n\n" + "\n\n".join(results)

    async def read_url(self, url: str) -> str:
        """
        Agent-friendly URL reading that returns formatted content.

        Example:
            content = await connector.read_url("https://docs.python.org/3/library/asyncio.html")
        """
        evidence = await self.fetch_url(url)

        if not evidence or evidence.confidence == 0:
            return f"[Failed to read: {url}]"

        return (
            f"## Content from: {evidence.title}\n"
            f"**Source:** {evidence.author} | **Authority:** {evidence.authority:.0%}\n\n"
            f"{evidence.content}"
        )
