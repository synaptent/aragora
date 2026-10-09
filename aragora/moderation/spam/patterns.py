"""
Spam detection pattern constants and word lists.

Contains all static pattern sets used for rule-based spam classification:
- Spam indicator words
- Urgency and money-related words
- Suspicious TLDs and known spam domains
- Free email providers
- URL shortener services
- Dangerous file extensions
- Promotional patterns
- Required email headers
"""

# Spam indicator words
SPAM_WORDS = {
    "winner",
    "congratulations",
    "prize",
    "won",
    "lottery",
    "urgent",
    "act now",
    "limited time",
    "expire",
    "hurry",
    "free",
    "discount",
    "offer",
    "deal",
    "save",
    "cash",
    "money",
    "dollars",
    "bitcoin",
    "crypto",
    "click here",
    "click now",
    "unsubscribe",
    "pharmacy",
    "pills",
    "medication",
    "viagra",
    "weight loss",
    "diet",
    "lose weight",
    "earn money",
    "work from home",
    "income",
    "nigerian",
    "prince",
    "inheritance",
    "attorney",
}

URGENCY_WORDS = {
    "urgent",
    "immediately",
    "asap",
    "act now",
    "limited",
    "expire",
    "deadline",
    "hurry",
    "last chance",
    "final notice",
    "important",
    "attention",
    "warning",
    "alert",
    "action required",
}

MONEY_WORDS = {
    "money",
    "cash",
    "dollars",
    "payment",
    "bank",
    "transfer",
    "wire",
    "bitcoin",
    "crypto",
    "invest",
    "million",
    "billion",
    "profit",
    "earn",
    "income",
    "loan",
    "credit",
    "debt",
    "insurance",
    "mortgage",
}

SUSPICIOUS_TLDS = {
    ".tk",
    ".ml",
    ".ga",
    ".cf",
    ".gq",
    ".xyz",
    ".top",
    ".work",
    ".click",
    ".loan",
    ".zip",
    ".mov",
    ".review",
    ".stream",
    ".download",
    ".win",
    ".bid",
    ".racing",
    ".party",
    ".science",
    ".date",
    ".faith",
    ".accountant",
    ".cricket",
}

# Known spam domains (frequently used for spam/phishing)
KNOWN_SPAM_DOMAINS = {
    # These are commonly spoofed or used for spam
    "mailinator.com",
    "guerrillamail.com",
    "10minutemail.com",
    "tempmail.com",
    "throwaway.email",
    "temp-mail.org",
    "fakeinbox.com",
    "sharklasers.com",
    "spam4.me",
    "spamgourmet.com",
    "trashmail.com",
}

# Free email providers (not necessarily spam, but can be indicator)
FREE_EMAIL_PROVIDERS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "mail.com",
    "protonmail.com",
    "zoho.com",
    "icloud.com",
    "yandex.com",
    "gmx.com",
    "mail.ru",
    "qq.com",
    "163.com",
    "126.com",
}

# URL shortener services
URL_SHORTENERS = {
    "bit.ly",
    "tinyurl.com",
    "goo.gl",
    "t.co",
    "ow.ly",
    "is.gd",
    "buff.ly",
    "adf.ly",
    "j.mp",
    "tiny.cc",
    "shorte.st",
    "v.gd",
    "rb.gy",
    "cutt.ly",
    "shorturl.at",
    "t.ly",
    "rebrand.ly",
    "bl.ink",
    "soo.gd",
    "s.id",
}

# Dangerous file extensions
DANGEROUS_EXTENSIONS = {
    # Executables
    ".exe",
    ".com",
    ".bat",
    ".cmd",
    ".msi",
    ".scr",
    ".pif",
    ".application",
    ".gadget",
    ".msp",
    ".msc",
    # Scripts
    ".js",
    ".jse",
    ".vbs",
    ".vbe",
    ".ws",
    ".wsf",
    ".wsc",
    ".wsh",
    ".ps1",
    ".ps1xml",
    ".ps2",
    ".ps2xml",
    ".psc1",
    ".psc2",
    # Macros and Office
    ".docm",
    ".xlsm",
    ".pptm",
    ".dotm",
    ".xltm",
    ".xlam",
    ".ppam",
    ".ppsm",
    ".sldm",
    # Archives (can contain malware)
    ".jar",
    ".hta",
    ".cpl",
    # Shortcuts
    ".lnk",
    ".inf",
    ".reg",
    # Other dangerous
    ".dll",
    ".ocx",
    ".sys",
    ".drv",
}

PROMOTIONAL_PATTERNS = [
    r"unsubscribe",
    r"email\s+preferences",
    r"opt.?out",
    r"manage\s+subscription",
    r"view\s+in\s+browser",
    r"trouble\s+viewing",
    r"add\s+us\s+to\s+your\s+address\s+book",
    r"©\s*\d{4}",  # Copyright notice
    r"all\s+rights\s+reserved",
]

# Required email headers (absence may indicate forgery)
REQUIRED_HEADERS = {
    "from",
    "to",
    "date",
    "message-id",
}
