import hashlib
import sys
from pathlib import Path


def hash_file(file_path: str) -> str:
    """
    Calculate the SHA-256 hash of a file.
    This function will be reused for datasets, logs, models and manifests.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    sha256 = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python src/hashing.py <file_path>")
        sys.exit(1)

    file_path = sys.argv[1]
    file_hash = hash_file(file_path)

    print(f"File: {file_path}")
    print(f"SHA-256: {file_hash}")
