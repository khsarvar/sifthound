"""Open-source, self-hostable search/extract/crawl API for AI agents (Tavily-compatible)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sifthound")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0"
