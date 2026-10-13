"""
Repository Crawler (compatibility path).

The crawler lives in :mod:`aragora.analysis.codebase.repository_crawler`; this
module re-exports the same objects.
"""

from __future__ import annotations

from aragora.analysis.codebase.repository_crawler import EXTENSION_MAP as EXTENSION_MAP
from aragora.analysis.codebase.repository_crawler import (
    CrawlConfig,
    CrawledFile,
    CrawlResult,
    CrawlState,
    FileDependency,
    FileSymbol,
    FileType,
    RepositoryCrawler,
    crawl_repository,
)

__all__ = [
    "RepositoryCrawler",
    "CrawlConfig",
    "CrawlResult",
    "CrawlState",
    "CrawledFile",
    "FileSymbol",
    "FileDependency",
    "FileType",
    "crawl_repository",
]
