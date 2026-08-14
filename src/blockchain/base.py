"""
Blockchain backend interface.

Every supported blockchain (Circular, Polygon, Ethereum, ...) provides a
subclass of BlockchainBackend. The rest of the pipeline talks ONLY to this
interface, never to a specific chain's SDK. This is what makes the system
blockchain-agnostic: to switch chains, we swap the backend, not the pipeline.

Two operations are enough to cover the whole certify/verify workflow:

  submit(manifest_text)      -> receipt dict   (anchor a manifest on-chain)
  fetch_certificate(receipt) -> manifest_text  (read back what was anchored)

The receipt is a plain dict that always contains at least the keys in
REQUIRED_RECEIPT_KEYS, so downstream tooling (verification, cost estimation,
the report) keeps working regardless of which chain produced it.
"""

from abc import ABC, abstractmethod


# Keys every backend must put in its receipt so the rest of the project
# (verify_certificate.py, estimate_costs.py) can rely on them.
REQUIRED_RECEIPT_KEYS = {
    "backend",          # which backend produced this (e.g. "circular", "polygon")
    "manifest_sha256",  # SHA-256 of the manifest file that was anchored
    "network",          # network name (e.g. "testnet", "amoy", "mainnet")
    "tx_id",            # transaction identifier on that chain
    "status",           # confirmed status (e.g. "Executed", "success")
}


class BlockchainBackend(ABC):
    """Common interface all chain backends implement."""

    #: short, lowercase identifier for this backend, e.g. "circular"
    name: str = "base"

    @abstractmethod
    def submit(self, manifest_text: str, manifest_sha256: str) -> dict:
        """
        Anchor a manifest on the blockchain.

        Args:
            manifest_text:   the full manifest JSON as a string.
            manifest_sha256: the SHA-256 of the manifest file (already computed
                             by the caller so hashing stays in one place).

        Returns:
            A receipt dict containing at least REQUIRED_RECEIPT_KEYS.
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_certificate(self, receipt: dict) -> str:
        """
        Read back the manifest that was anchored, using the info in the receipt.

        Args:
            receipt: a receipt dict previously returned by submit().

        Returns:
            The manifest text as stored on-chain (or the manifest hash, for
            backends that anchor only the hash — see each backend's docstring).
        """
        raise NotImplementedError

    def validate_receipt(self, receipt: dict) -> None:
        """
        Helper: make sure a receipt has the keys the rest of the project needs.
        Backends call this at the end of submit() to fail fast on mistakes.
        """
        missing = REQUIRED_RECEIPT_KEYS - receipt.keys()
        if missing:
            raise ValueError(
                f"{self.name} backend produced a receipt missing keys: {sorted(missing)}"
            )