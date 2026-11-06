"""CLI tests that need no display. The passphrase prompt is patched."""

import contextlib
import io
import json
import struct
import wave
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from envy_veil import cli


def make_png(path, w=96, h=96):
    from PIL import Image
    Image.new("RGB", (w, h), (80, 110, 190)).save(path, "PNG")


class CLITest(unittest.TestCase):
    SECRET = b"a long private veil passphrase"

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="envy-veil-cli-"))
        self.addCleanup(__import__("shutil").rmtree, self.dir)

    def invoke(self, *args, secret=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(cli, "_passphrase", return_value=secret or self.SECRET):
            code = cli.main([str(a) for a in args])
        return code, out.getvalue(), err.getvalue()

    def test_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("envy-veil", out.getvalue())

    def test_hide_then_reveal_flow(self):
        png = self.dir / "cover.png"; make_png(png, 128, 128)
        payload = self.dir / "secret.txt"; payload.write_bytes(b"meet at the usual place")
        veiled = self.dir / "veiled.png"
        code, out, _ = self.invoke("hide", png, payload, veiled)
        self.assertEqual(code, 0)
        self.assertIn("hid", out)
        self.assertTrue(veiled.exists())

        back = self.dir / "back.txt"
        code, out, _ = self.invoke("reveal", veiled, back)
        self.assertEqual(code, 0)
        self.assertEqual(back.read_bytes(), payload.read_bytes())

    def test_capacity_and_inspect(self):
        png = self.dir / "c.png"; make_png(png, 100, 100)
        code, out, _ = self.invoke("capacity", png)
        self.assertEqual(code, 0)
        self.assertGreater(json.loads(out)["max_payload_bytes"], 0)
        code, out, _ = self.invoke("inspect", png)
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["veil_payload_present"])

    def test_wrong_passphrase_is_error(self):
        png = self.dir / "c.png"; make_png(png, 96, 96)
        payload = self.dir / "p.txt"; payload.write_bytes(b"x" * 40)
        veiled = self.dir / "v.png"
        self.invoke("hide", png, payload, veiled)
        code, _, err = self.invoke("reveal", veiled, self.dir / "n.txt", secret=b"the wrong passphrase!")
        self.assertEqual(code, 2)
        self.assertIn("passphrase", err.lower())

    def test_unknown_command(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["seance"])


if __name__ == "__main__":
    unittest.main()
