"""
Backend factory.

One place decides which blockchain backend the whole pipeline uses. The choice
comes from a single environment variable:

    BLOCKCHAIN=circular     # or: polygon   (default: circular)

certificate_service.py and verify_certificate.py call get_backend() and never
mention a specific chain. To switch chains you change one line in .env --
nothing else. This is the core of the blockchain-agnostic design.
"""

import os

from dotenv import load_dotenv

from .base import BlockchainBackend


def get_backend() -> BlockchainBackend:
    """Return the backend selected by the BLOCKCHAIN environment variable."""
    load_dotenv()
    choice = os.getenv("BLOCKCHAIN", "circular").strip().lower()

    if choice == "circular":
        from .circular_backend import CircularBackend
        return CircularBackend()

    if choice == "polygon":
        # Added in a later step; referenced here so the switch is ready.
        from .polygon_backend import PolygonBackend
        return PolygonBackend()

    raise ValueError(
        f"Unknown BLOCKCHAIN='{choice}'. Supported values: circular, polygon."
    )