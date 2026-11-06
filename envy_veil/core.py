"""Hide an encrypted file inside a lossless carrier, and recover it.

A self-contained engine for ENVY Veil, packaged as a standalone app. A payload is
first sealed in the same AES-256-GCM envelope ENVY Vault uses, then its bytes are
written into the least-significant bits (LSB) of a carrier image (PNG/BMP) or audio
file (WAV). Extraction reads the bits back and decrypts with the passphrase.

Honest by design: steganography hides that a message exists, it is not the security
— the AES-256-GCM encryption is. LSB embedding is detectable by steganalysis, and it
survives only in *lossless* carriers: re-saving the output as JPEG, MP3 or MP4, or any
lossy re-encoding, destroys the hidden data. Capacity is bounded by the carrier size.

Images use Pillow; audio uses the standard-library ``wave`` module; encryption uses
``cryptography``. Nothing is sent anywhere.
"""

from __future__ import annotations

import os
import stat
import struct
import wave
from pathlib import Path

# --- Shared errors and bounds ------------------------------------------------

MAGIC = b"ENVYVAULT2\x00"          # the AES envelope magic (byte-compatible with ENVY Vault)
STEG_MAGIC = b"ENVYVEIL1"          # marks an embedded payload; followed by a 4-byte length
MIN_PASSPHRASE = 12
MAX_PAYLOAD = 64 * 1024 * 1024     # 64 MiB plaintext payload ceiling
MAX_CARRIER = 256 * 1024 * 1024    # 256 MiB carrier ceiling
IMAGE_SUFFIXES = (".png", ".bmp")
AUDIO_SUFFIXES = (".wav",)
HEADER = STEG_MAGIC + b"\x00\x00\x00\x00"   # magic + u32 length placeholder


class VeilError(RuntimeError):
    """A clean, expected error: a bad passphrase, an oversized payload, a wrong carrier."""


# --- Safe file primitives (never follow symlinks, never overwrite) -----------

def read_regular(path, limit: int = MAX_CARRIER) -> bytes:
    path = Path(path).expanduser()
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
            raise VeilError("Expected a regular file within the size limit")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise VeilError("File exceeded the size limit")
    return data


def new_file(path, data: bytes, mode: int = 0o600) -> Path:
    """Write a brand-new file. O_EXCL means an existing file is never overwritten."""
    path = Path(path).expanduser()
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError:
        raise VeilError(f"Refusing to overwrite an existing file: {path}") from None
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return path


# --- Encrypted envelope (byte-compatible with ENVY Vault) --------------------

def _key(secret: bytes, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(secret)


def encrypt_bytes(data: bytes, secret: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_key(secret, salt)).encrypt(nonce, data, MAGIC)


def decrypt_bytes(data: bytes, secret: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not data.startswith(MAGIC) or len(data) < len(MAGIC) + 44:
        raise VeilError("Hidden data is not an ENVY encrypted envelope")
    blob = data[len(MAGIC):]
    try:
        return AESGCM(_key(secret, blob[:16])).decrypt(blob[16:28], blob[28:], MAGIC)
    except InvalidTag:
        raise VeilError("Incorrect passphrase or modified carrier") from None


def check_passphrase(secret: bytes) -> bytes:
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < MIN_PASSPHRASE:
        raise VeilError(f"Use a passphrase of at least {MIN_PASSPHRASE} bytes")
    return bytes(secret)


# --- Bit helpers -------------------------------------------------------------

def _bits(data: bytes):
    for byte in data:
        for shift in (7, 6, 5, 4, 3, 2, 1, 0):
            yield (byte >> shift) & 1


def _frame(payload: bytes) -> bytes:
    """STEG_MAGIC + u32 length + payload, the exact run of bytes written to LSBs."""
    return STEG_MAGIC + struct.pack(">I", len(payload)) + payload


def _embed_into(cover: bytearray, framed: bytes):
    """Write one bit per cover byte's LSB. Raises if the cover is too small."""
    need = len(framed) * 8
    if need > len(cover):
        raise VeilError(f"Carrier is too small: needs {need} slots, has {len(cover)}")
    for i, bit in enumerate(_bits(framed)):
        cover[i] = (cover[i] & 0xFE) | bit


def _read_bytes(cover, count: int) -> bytes:
    """Read ``count`` bytes from the LSBs of the cover bytes."""
    if count * 8 > len(cover):
        raise VeilError("Carrier does not contain a complete hidden payload")
    out = bytearray(count)
    for i in range(count):
        value = 0
        for j in range(8):
            value = (value << 1) | (cover[i * 8 + j] & 1)
        out[i] = value
    return bytes(out)


def _extract_framed(cover) -> bytes:
    head = _read_bytes(cover, len(HEADER))
    if not head.startswith(STEG_MAGIC):
        raise VeilError("No ENVY Veil payload found in this carrier")
    (length,) = struct.unpack(">I", head[len(STEG_MAGIC):len(STEG_MAGIC) + 4])
    if length <= 0 or length > MAX_PAYLOAD + 1024:
        raise VeilError("Hidden payload length is invalid")
    return _read_bytes(cover, len(HEADER) + length)[len(HEADER):]


# --- Carrier back-ends: expose a mutable byte plane --------------------------

def _carrier_kind(path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    raise VeilError("Carrier must be a lossless PNG, BMP or WAV file")


def _load_image_plane(path):
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        data = bytearray(im.tobytes())
        size = im.size
    return data, size


def _save_image_plane(path, plane, size, out_format):
    from PIL import Image
    im = Image.frombytes("RGB", size, bytes(plane))
    stream = __import__("io").BytesIO()
    im.save(stream, format=out_format)
    return new_file(path, stream.getvalue())


def _load_audio_plane(path):
    with wave.open(str(Path(path).expanduser()), "rb") as w:
        params = w.getparams()
        if params.sampwidth != 2:
            raise VeilError("WAV carriers must be 16-bit PCM")
        frames = bytearray(w.readframes(params.nframes))
    return frames, params


def _save_audio_plane(path, frames, params):
    import io
    stream = io.BytesIO()
    with wave.open(stream, "wb") as w:
        w.setparams(params)
        w.writeframes(bytes(frames))
    return new_file(path, stream.getvalue())


def capacity(path) -> dict:
    """How many payload bytes this carrier can hold (after the header)."""
    kind = _carrier_kind(path)
    if kind == "image":
        plane, _ = _load_image_plane(path)
    else:
        plane, _ = _load_audio_plane(path)
    slots = len(plane)
    usable = max(0, slots // 8 - len(HEADER))
    # Encryption adds a fixed overhead (magic + salt + nonce + tag = 11+16+12+16).
    overhead = len(MAGIC) + 16 + 12 + 16
    return {"carrier": str(path), "kind": kind, "bit_slots": slots,
            "max_framed_bytes": slots // 8, "max_payload_bytes": max(0, usable - overhead)}


# --- Public operations -------------------------------------------------------

def hide(carrier, payload_file, destination, secret):
    """Encrypt ``payload_file`` and hide it in ``carrier``; write a new carrier file."""
    check_passphrase(secret)
    kind = _carrier_kind(carrier)
    out_suffix = Path(destination).suffix.lower()
    if out_suffix not in IMAGE_SUFFIXES + AUDIO_SUFFIXES:
        raise VeilError("Output must be a lossless PNG, BMP or WAV file")
    if (kind == "image") != (out_suffix in IMAGE_SUFFIXES):
        raise VeilError("Output carrier type must match the input carrier type")
    payload = read_regular(payload_file, MAX_PAYLOAD)
    if not payload:
        raise VeilError("The payload file is empty")
    framed = _frame(encrypt_bytes(payload, secret))

    if kind == "image":
        plane, size = _load_image_plane(carrier)
        _embed_into(plane, framed)
        out_format = "PNG" if out_suffix == ".png" else "BMP"
        _save_image_plane(destination, plane, size, out_format)
    else:
        plane, params = _load_audio_plane(carrier)
        _embed_into(plane, framed)
        _save_audio_plane(destination, plane, params)
    return {"output": str(destination), "kind": kind, "payload_bytes": len(payload),
            "embedded_bytes": len(framed), "carrier": str(carrier),
            "note": "The hidden data is AES-256-GCM encrypted. Keep the output lossless — "
                    "re-saving it as a lossy format (JPEG, MP3, MP4) destroys the payload."}


def reveal(carrier, destination, secret):
    """Extract and decrypt a payload hidden in ``carrier``; write a new file."""
    check_passphrase(secret)
    kind = _carrier_kind(carrier)
    plane = _load_image_plane(carrier)[0] if kind == "image" else _load_audio_plane(carrier)[0]
    payload = decrypt_bytes(_extract_framed(plane), secret)
    new_file(destination, payload)
    return {"output": str(destination), "kind": kind, "payload_bytes": len(payload),
            "note": "A successful decrypt authenticates the payload; it does not reveal who hid it."}


def inspect(carrier) -> dict:
    """Report, without a passphrase, whether a carrier holds an ENVY Veil payload."""
    kind = _carrier_kind(carrier)
    plane = _load_image_plane(carrier)[0] if kind == "image" else _load_audio_plane(carrier)[0]
    head = _read_bytes(plane, len(HEADER)) if len(plane) >= len(HEADER) * 8 else b""
    present = head.startswith(STEG_MAGIC)
    info = {"carrier": str(carrier), "kind": kind, "veil_payload_present": present}
    if present:
        (length,) = struct.unpack(">I", head[len(STEG_MAGIC):len(STEG_MAGIC) + 4])
        info["embedded_bytes"] = len(HEADER) + length
    info["note"] = ("A present marker only shows this tool wrote here; absence does not prove a "
                    "carrier is clean, and the payload stays encrypted without the passphrase.")
    return info
