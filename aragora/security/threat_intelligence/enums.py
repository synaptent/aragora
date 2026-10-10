"""
Threat intelligence enums, constants, and pattern definitions.
"""

from __future__ import annotations

from enum import Enum


class ThreatType(Enum):
    """Types of detected threats."""

    NONE = "none"
    MALWARE = "malware"
    PHISHING = "phishing"
    SPAM = "spam"
    SUSPICIOUS = "suspicious"
    MALICIOUS_IP = "malicious_ip"
    COMMAND_AND_CONTROL = "c2"
    BOTNET = "botnet"
    CRYPTO_MINER = "crypto_miner"
    RANSOMWARE = "ransomware"
    TROJAN = "trojan"
    UNKNOWN = "unknown"


class ThreatSeverity(Enum):
    """Severity levels for threats."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class ThreatSource(Enum):
    """Source of threat intelligence."""

    VIRUSTOTAL = "virustotal"
    ABUSEIPDB = "abuseipdb"
    PHISHTANK = "phishtank"
    URLHAUS = "urlhaus"
    LOCAL_RULES = "local_rules"
    CACHED = "cached"


# Known malicious patterns for local detection
MALICIOUS_URL_PATTERNS = [
    r"(?i)paypal.*\.(?!paypal\.com)",  # PayPal phishing
    r"(?i)google.*login.*\.(?!google\.com)",  # Google phishing
    r"(?i)microsoft.*verify.*\.(?!microsoft\.com)",  # Microsoft phishing
    r"(?i)apple.*id.*\.(?!apple\.com)",  # Apple phishing
    r"(?i)bank.*verify",  # Banking phishing
    r"(?i)account.*suspend",  # Account suspension scam
    r"(?i)\.tk$|\.ml$|\.ga$|\.cf$",  # Free TLD abuse
    r"(?i)bit\.ly.*[a-z0-9]{6,}",  # Suspicious shortened URLs
]

SUSPICIOUS_TLDS = {
    ".tk",
    ".ml",
    ".ga",
    ".cf",
    ".gq",  # Free TLDs
    ".xyz",
    ".top",
    ".work",
    ".click",  # Often abused
    ".zip",
    ".mov",  # Confusing file extensions
}
