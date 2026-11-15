"""ENVY Veil: hide an AES-256-GCM encrypted file inside a lossless image or audio carrier."""

__version__ = "0.2.1"
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
