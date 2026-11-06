"""Core Veil tests: encrypted round trips, LSB hide/reveal in image and audio
carriers, capacity and no-overwrite guarantees, and honest-by-design limits.
"""

import struct
import wave
from pathlib import Path
import tempfile
import unittest

from envy_veil import core
from envy_veil.core import VeilError


def make_png(path, w=64, h=64, color=(90, 120, 200)):
    from PIL import Image
    Image.new("RGB", (w, h), color).save(path, "PNG")


def make_wav(path, frames=20000):
    with wave.open(str(path), "wb") as wv:
        wv.setnchannels(1); wv.setsampwidth(2); wv.setframerate(44100)
        wv.writeframes(struct.pack("<%dh" % frames, *([1000, -1000] * (frames // 2))))


class VeilTest(unittest.TestCase):
    SECRET = b"a long private veil passphrase"

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="envy-veil-"))
        self.addCleanup(__import__("shutil").rmtree, self.dir)

    # ----- envelope -----------------------------------------------------
    def test_encrypted_round_trip_and_magic(self):
        blob = core.encrypt_bytes(b"secret", self.SECRET)
        self.assertEqual(blob[:11], b"ENVYVAULT2\x00")  # byte-compatible with ENVY Vault
        self.assertEqual(core.decrypt_bytes(blob, self.SECRET), b"secret")

    def test_short_passphrase_rejected(self):
        png = self.dir / "c.png"; make_png(png)
        payload = self.dir / "p.txt"; payload.write_bytes(b"hello world")
        with self.assertRaises(VeilError):
            core.hide(png, payload, self.dir / "out.png", b"tooshort")

    # ----- image round trip --------------------------------------------
    def test_hide_and_reveal_image(self):
        png = self.dir / "cover.png"; make_png(png, 128, 128)
        secret_file = self.dir / "message.txt"
        secret_file.write_bytes(b"The authorized inventory is in bay 7." * 3)
        out = self.dir / "veiled.png"
        res = core.hide(png, secret_file, out, self.SECRET)
        self.assertEqual(res["kind"], "image")
        self.assertTrue(out.exists())
        self.assertTrue(png.exists(), "carrier preserved")
        # The output is a valid PNG and visually close to the cover.
        recovered = self.dir / "back.txt"
        r = core.reveal(out, recovered, self.SECRET)
        self.assertEqual(recovered.read_bytes(), secret_file.read_bytes())
        self.assertEqual(r["payload_bytes"], secret_file.stat().st_size)

    def test_hide_and_reveal_audio(self):
        wav = self.dir / "cover.wav"; make_wav(wav, 40000)
        payload = self.dir / "p.bin"; payload.write_bytes(bytes(range(256)) * 4)
        out = self.dir / "veiled.wav"
        core.hide(wav, payload, out, self.SECRET)
        recovered = self.dir / "back.bin"
        core.reveal(out, recovered, self.SECRET)
        self.assertEqual(recovered.read_bytes(), payload.read_bytes())

    def test_wrong_passphrase_fails_to_reveal(self):
        png = self.dir / "c.png"; make_png(png, 96, 96)
        payload = self.dir / "p.txt"; payload.write_bytes(b"x" * 50)
        out = self.dir / "v.png"
        core.hide(png, payload, out, self.SECRET)
        with self.assertRaises(VeilError):
            core.reveal(out, self.dir / "n.txt", b"the wrong passphrase!")

    def test_payload_too_large_for_carrier(self):
        png = self.dir / "tiny.png"; make_png(png, 16, 16)      # 16*16*3 = 768 bits of slots
        payload = self.dir / "big.bin"; payload.write_bytes(b"A" * 5000)
        with self.assertRaises(VeilError):
            core.hide(png, payload, self.dir / "o.png", self.SECRET)

    def test_capacity_reports_usable_bytes(self):
        png = self.dir / "c.png"; make_png(png, 100, 100)       # 100*100*3 slots
        cap = core.capacity(png)
        self.assertEqual(cap["kind"], "image")
        self.assertEqual(cap["bit_slots"], 100 * 100 * 3)
        self.assertGreater(cap["max_payload_bytes"], 0)

    # ----- inspect ------------------------------------------------------
    def test_inspect_detects_payload(self):
        png = self.dir / "c.png"; make_png(png, 80, 80)
        self.assertFalse(core.inspect(png)["veil_payload_present"])
        payload = self.dir / "p.txt"; payload.write_bytes(b"secret note")
        out = self.dir / "v.png"
        core.hide(png, payload, out, self.SECRET)
        self.assertTrue(core.inspect(out)["veil_payload_present"])

    def test_reveal_empty_carrier_errors(self):
        png = self.dir / "clean.png"; make_png(png, 80, 80)
        with self.assertRaises(VeilError):
            core.reveal(png, self.dir / "x", self.SECRET)

    # ----- lossy destroys payload (honest-by-design) -------------------
    def test_jpeg_output_rejected(self):
        png = self.dir / "c.png"; make_png(png, 80, 80)
        payload = self.dir / "p.txt"; payload.write_bytes(b"data")
        with self.assertRaises(VeilError):
            core.hide(png, payload, self.dir / "out.jpg", self.SECRET)

    def test_carrier_type_must_match_output(self):
        png = self.dir / "c.png"; make_png(png, 80, 80)
        payload = self.dir / "p.txt"; payload.write_bytes(b"data")
        with self.assertRaises(VeilError):
            core.hide(png, payload, self.dir / "out.wav", self.SECRET)

    def test_unsupported_carrier_rejected(self):
        bad = self.dir / "c.gif"; bad.write_bytes(b"GIF89a")
        with self.assertRaises(VeilError):
            core.capacity(bad)

    # ----- no overwrite -------------------------------------------------
    def test_hide_never_overwrites_output(self):
        png = self.dir / "c.png"; make_png(png, 80, 80)
        payload = self.dir / "p.txt"; payload.write_bytes(b"data here")
        out = self.dir / "exists.png"; out.write_bytes(b"keep me")
        with self.assertRaises(VeilError):
            core.hide(png, payload, out, self.SECRET)
        self.assertEqual(out.read_bytes(), b"keep me")

    def test_empty_payload_rejected(self):
        png = self.dir / "c.png"; make_png(png, 80, 80)
        empty = self.dir / "empty.bin"; empty.write_bytes(b"")
        with self.assertRaises(VeilError):
            core.hide(png, empty, self.dir / "o.png", self.SECRET)


if __name__ == "__main__":
    unittest.main()
