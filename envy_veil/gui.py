"""A native ENVY Veil window: a real desktop app, not a web view.

Built with PyQt6 and styled in the ENVY palette with a live animated header.
Hide an AES-256-GCM encrypted file inside a lossless image (PNG/BMP) or audio
(WAV) carrier, watch the capacity meter, and recover it later. Every result is a
brand-new file; the carrier and payload are never overwritten.

Nothing is sent: no network, no accounts. Steganography hides that data exists —
the encryption is what keeps it secret.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from . import __version__
from . import core
from .core import VeilError

BG = "#050713"
PANEL = "#0a0e22"
PANEL_HI = "#121735"
INK = "#f2f4ff"
MUTED = "#b9c3df"
DIM = "#6f7898"
PINK = "#ff3db4"
CYAN = "#35e8ff"
LAVENDER = "#ac8cff"
VIOLET = "#8547e8"
AMBER = "#ffb347"
GREEN = "#49e3a6"
LINE = "#1f2547"


def lerp(a, b, t):
    from PyQt6.QtGui import QColor
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t),
                  int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t))


def _build():
    from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
    from PyQt6.QtGui import (QColor, QPainter, QLinearGradient, QRadialGradient, QFont,
                             QPen, QBrush, QPixmap)
    from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QTabWidget,
                                 QVBoxLayout, QHBoxLayout, QProgressBar, QFrame,
                                 QInputDialog, QFileDialog, QMessageBox, QLineEdit as QLE)

    class Header(QWidget):
        def __init__(self):
            super().__init__()
            self.setFixedHeight(172)
            self.phase = 0.0
            self.stars = [(((i * 139 + 37) % 1000) / 1000.0,
                           ((i * 83 + 19) % 172) / 172.0,
                           0.6 + (i % 3) * 0.5, (i % 7) / 7.0) for i in range(60)]

        def tick(self, phase):
            self.phase = phase
            self.update()

        def paintEvent(self, _event):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            p.fillRect(self.rect(), QColor(BG))
            for cx, cy, rad, col, a in ((w - 120, 60, 250, VIOLET, 60),
                                        (60, h, 280, PINK, 52), (w * 0.5, -40, 240, CYAN, 42)):
                g = QRadialGradient(cx, cy, rad)
                c = QColor(col); c.setAlpha(a); g.setColorAt(0, c)
                c2 = QColor(col); c2.setAlpha(0); g.setColorAt(1, c2)
                p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(cx, cy), rad, rad)
            for sx, sy, sr, ph in self.stars:
                tw = 0.5 + 0.5 * math.sin(self.phase / 0.5 + ph * 6.28)
                c = QColor(205, 217, 255); c.setAlphaF(0.15 + 0.6 * tw)
                p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(sx * w, sy * h), sr, sr)
            pulse = 0.5 + 0.5 * math.sin(self.phase)
            p.setFont(QFont("Helvetica", 24))
            p.setPen(QColor(CYAN) if pulse > 0.5 else QColor(PINK))
            p.drawText(QRectF(22, 26, 46, 46), Qt.AlignmentFlag.AlignCenter, "◌")
            p.setFont(QFont("Helvetica", 37, QFont.Weight.Bold))
            grad = QLinearGradient(74, 0, 380, 0)
            grad.setColorAt(0, QColor(PINK))
            grad.setColorAt(0.5, QColor(lerp(PINK, "#ffffff", 0.2 * pulse)))
            grad.setColorAt(1, QColor(CYAN))
            glow = QColor(VIOLET); glow.setAlpha(int(55 + 55 * pulse))
            p.setPen(QPen(glow, 1))
            for dx, dy in ((1.3, 1.3), (-1.3, 1.3), (1.3, -1.3)):
                p.drawText(QRectF(74 + dx, 34 + dy, 420, 52), Qt.AlignmentFlag.AlignVCenter, "ENVY VEIL")
            p.setPen(QPen(QBrush(grad), 1))
            p.drawText(QRectF(74, 34, 420, 52), Qt.AlignmentFlag.AlignVCenter, "ENVY VEIL")
            p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
            p.setPen(QColor(LAVENDER))
            p.drawText(QRectF(78, 90, 560, 20), Qt.AlignmentFlag.AlignVCenter,
                       "ENCRYPTED  ·  HIDDEN  ·  LOSSLESS")
            y = 126
            p.setPen(QPen(QColor(LINE), 2)); p.drawLine(78, y, w - 54, y)
            p.setPen(QPen(QColor(VIOLET), 3)); p.drawLine(78, y, 150, y)
            span = (w - 54) - 78
            x = 78 + span * ((self.phase * 0.12) % 1.0)
            halo = QRadialGradient(x, y, 15)
            hc = QColor(PINK); hc.setAlpha(170); halo.setColorAt(0, hc)
            hc2 = QColor(PINK); hc2.setAlpha(0); halo.setColorAt(1, hc2)
            p.setBrush(QBrush(halo)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), 15, 15)
            p.setBrush(QColor("#ffffff")); p.drawEllipse(QPointF(x, y), 2.5, 2.5)
            p.end()

    class Window(QWidget):
        IMAGE_FILTER = "Lossless carriers (*.png *.bmp *.wav);;Images (*.png *.bmp);;Audio (*.wav);;All files (*)"

        def __init__(self):
            super().__init__()
            self.secret = None
            self.hide_carrier = None
            self.hide_payload = None
            self.reveal_carrier = None
            self.setWindowTitle("ENVY Veil")
            self.resize(1120, 860)
            self.setMinimumSize(940, 720)
            self.setStyleSheet(STYLE)
            root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
            self.header = Header(); root.addWidget(self.header)

            body = QWidget(); body.setObjectName("body")
            bl = QVBoxLayout(body); bl.setContentsMargins(22, 14, 22, 16); bl.setSpacing(12)

            intro = QLabel("Hide an encrypted file inside a lossless image or audio carrier, and recover "
                           "it with your passphrase. The carrier looks unchanged; the hidden data is "
                           "AES-256-GCM encrypted. Nothing is sent.")
            intro.setObjectName("status"); intro.setWordWrap(True); bl.addWidget(intro)

            self.tabs = QTabWidget(); self.tabs.setObjectName("tabs")
            self.tabs.addTab(self._hide_tab(), "Hide a file")
            self.tabs.addTab(self._reveal_tab(), "Reveal a file")
            self.tabs.addTab(self._inspect_tab(), "Inspect a carrier")
            bl.addWidget(self.tabs, 1)

            foot = QLabel("Steganography hides that data exists; it is not the security — the AES-256-GCM "
                          "encryption is. LSB embedding is detectable by steganalysis and survives only in "
                          "lossless carriers: re-saving as JPEG, MP3 or MP4 destroys the payload.")
            foot.setObjectName("foot"); foot.setWordWrap(True); bl.addWidget(foot)
            root.addWidget(body, 1)

            self.phase = 0.0
            self.timer = QTimer(self); self.timer.timeout.connect(self._animate); self.timer.start(33)

        # ----- hide tab -----------------------------------------------------
        def _hide_tab(self):
            tab = QWidget(); g = QVBoxLayout(tab); g.setSpacing(10)
            g.addWidget(self._tag("CARRIER  ·  a lossless PNG, BMP or WAV to hide inside"))
            self.h_carrier_btn, self.h_carrier_lbl = self._picker("Choose carrier…", self.pick_hide_carrier)
            g.addLayout(self._row(self.h_carrier_btn, self.h_carrier_lbl))

            self.preview = QLabel("No carrier selected."); self.preview.setObjectName("preview")
            self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumHeight(230)
            g.addWidget(self.preview, 1)

            g.addWidget(self._tag("PAYLOAD  ·  the file to hide"))
            self.h_payload_btn, self.h_payload_lbl = self._picker("Choose payload…", self.pick_hide_payload)
            g.addLayout(self._row(self.h_payload_btn, self.h_payload_lbl))

            self.cap_bar = QProgressBar(); self.cap_bar.setObjectName("cap"); self.cap_bar.setTextVisible(False)
            self.cap_bar.setFixedHeight(10); g.addWidget(self.cap_bar)
            self.cap_lbl = QLabel("Choose a carrier to see its capacity."); self.cap_lbl.setObjectName("status")
            g.addWidget(self.cap_lbl)

            row = QHBoxLayout()
            self.hide_btn = QPushButton("Hide file in a new carrier"); self.hide_btn.setObjectName("go")
            self.hide_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.hide_btn.clicked.connect(self.do_hide)
            self.hide_status = QLabel(""); self.hide_status.setObjectName("status")
            row.addWidget(self.hide_btn); row.addWidget(self.hide_status, 1)
            g.addLayout(row)
            return tab

        # ----- reveal tab ---------------------------------------------------
        def _reveal_tab(self):
            tab = QWidget(); g = QVBoxLayout(tab); g.setSpacing(10)
            g.addWidget(self._tag("CARRIER  ·  a PNG, BMP or WAV that holds a Veil payload"))
            self.r_carrier_btn, self.r_carrier_lbl = self._picker("Choose carrier…", self.pick_reveal_carrier)
            g.addLayout(self._row(self.r_carrier_btn, self.r_carrier_lbl))
            self.r_info = QLabel(""); self.r_info.setObjectName("status"); self.r_info.setWordWrap(True)
            g.addWidget(self.r_info)
            g.addStretch(1)
            row = QHBoxLayout()
            self.reveal_btn = QPushButton("Reveal && save the payload"); self.reveal_btn.setObjectName("go")
            self.reveal_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.reveal_btn.clicked.connect(self.do_reveal)
            self.reveal_status = QLabel(""); self.reveal_status.setObjectName("status")
            row.addWidget(self.reveal_btn); row.addWidget(self.reveal_status, 1)
            g.addLayout(row)
            return tab

        # ----- inspect tab --------------------------------------------------
        def _inspect_tab(self):
            tab = QWidget(); g = QVBoxLayout(tab); g.setSpacing(10)
            g.addWidget(self._tag("CARRIER  ·  check for a payload without a passphrase"))
            btn, self.i_lbl = self._picker("Choose carrier…", self.do_inspect)
            g.addLayout(self._row(btn, self.i_lbl))
            self.i_result = QLabel("No carrier inspected yet."); self.i_result.setObjectName("mono")
            self.i_result.setWordWrap(True); self.i_result.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.i_result.setMinimumHeight(160)
            g.addWidget(self.i_result, 1)
            return tab

        # ----- small builders ----------------------------------------------
        def _tag(self, text):
            lab = QLabel(text); lab.setObjectName("tag"); return lab

        def _picker(self, caption, handler):
            btn = QPushButton(caption); btn.setObjectName("pick")
            btn.setCursor(Qt.CursorShape.PointingHandCursor); btn.clicked.connect(handler)
            lbl = QLabel("None selected."); lbl.setObjectName("path"); lbl.setWordWrap(True)
            return btn, lbl

        def _row(self, btn, lbl):
            row = QHBoxLayout(); row.addWidget(btn); row.addWidget(lbl, 1); return row

        # ----- actions ------------------------------------------------------
        def _ask_passphrase(self, confirm):
            text, ok = QInputDialog.getText(self, "Passphrase",
                                            "Veil passphrase (at least 12 characters):", QLE.EchoMode.Password)
            if not ok:
                return None
            secret = text.encode("utf-8")
            if confirm:
                again, ok2 = QInputDialog.getText(self, "Confirm passphrase",
                                                  "Repeat the passphrase:", QLE.EchoMode.Password)
                if not ok2:
                    return None
                if again.encode("utf-8") != secret:
                    self._warn("Passphrases do not match."); return None
            try:
                return core.check_passphrase(secret)
            except VeilError as exc:
                self._warn(str(exc)); return None

        def pick_hide_carrier(self):
            path, _ = QFileDialog.getOpenFileName(self, "Choose a carrier", "", self.IMAGE_FILTER)
            if not path:
                return
            self.hide_carrier = Path(path)
            self.h_carrier_lbl.setText(path)
            self._show_preview(self.hide_carrier)
            self._update_capacity()

        def pick_hide_payload(self):
            path, _ = QFileDialog.getOpenFileName(self, "Choose a payload to hide")
            if not path:
                return
            self.hide_payload = Path(path)
            self.h_payload_lbl.setText(path)
            self._update_capacity()

        def _show_preview(self, path):
            if path.suffix.lower() in core.AUDIO_SUFFIXES:
                self.preview.setPixmap(QPixmap())
                self.preview.setText(f"♪  Audio carrier\n{path.name}")
                return
            pix = QPixmap(str(path))
            if pix.isNull():
                self.preview.setText("Cannot preview this image."); return
            self.preview.setPixmap(pix.scaled(self.preview.width() - 12, 300,
                                              Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))

        def _update_capacity(self):
            if not self.hide_carrier:
                return
            try:
                cap = core.capacity(self.hide_carrier)
            except (VeilError, OSError) as exc:
                self.cap_lbl.setText(str(exc)); self.cap_bar.setValue(0); return
            maxp = cap["max_payload_bytes"]
            used = self.hide_payload.stat().st_size if self.hide_payload else 0
            pct = min(100, round(100 * used / maxp)) if maxp else 100
            self.cap_bar.setMaximum(100); self.cap_bar.setValue(pct)
            fits = used <= maxp
            color = GREEN if fits else PINK
            self.cap_bar.setStyleSheet(f"#cap::chunk{{background:{color};border-radius:5px;}}")
            self.cap_lbl.setText(
                f"Capacity: {maxp:,} bytes ({cap['kind']}).  "
                + (f"Payload: {used:,} bytes — {'fits' if fits else 'TOO LARGE'}." if self.hide_payload
                   else "Choose a payload."))
            self.cap_lbl.setStyleSheet(f"#status{{color:{color if self.hide_payload else MUTED};}}")

        def do_hide(self):
            if not self.hide_carrier or not self.hide_payload:
                self.hide_status.setText("Choose a carrier and a payload first."); return
            secret = self._ask_passphrase(confirm=True)
            if secret is None:
                return
            suffix = self.hide_carrier.suffix.lower()
            default = f"veiled{suffix}"
            dest, _ = QFileDialog.getSaveFileName(self, "Save the new carrier", default,
                                                  f"Carrier (*{suffix});;All files (*)")
            if not dest:
                return
            try:
                if Path(dest).exists():
                    Path(dest).unlink()
                result = core.hide(self.hide_carrier, self.hide_payload, dest, secret)
            except (VeilError, OSError) as exc:
                self.hide_status.setText(str(exc)); self.hide_status.setStyleSheet(f"#status{{color:{PINK};}}")
                return
            self.hide_status.setText(f"Hid {result['payload_bytes']:,} bytes → {Path(dest).name}")
            self.hide_status.setStyleSheet(f"#status{{color:{CYAN};}}")
            self._warn(f"Hid {result['payload_bytes']:,} encrypted bytes inside {Path(dest).name}.\n\n"
                       "Keep it lossless — re-saving as JPEG, MP3 or MP4 destroys the hidden data.",
                       icon=QMessageBox.Icon.Information, title="Payload hidden")

        def pick_reveal_carrier(self):
            path, _ = QFileDialog.getOpenFileName(self, "Choose a carrier", "", self.IMAGE_FILTER)
            if not path:
                return
            self.reveal_carrier = Path(path)
            self.r_carrier_lbl.setText(path)
            try:
                info = core.inspect(self.reveal_carrier)
                self.r_info.setText("A Veil payload appears to be present." if info["veil_payload_present"]
                                    else "No Veil payload marker found — revealing will likely fail.")
            except (VeilError, OSError) as exc:
                self.r_info.setText(str(exc))

        def do_reveal(self):
            if not self.reveal_carrier:
                self.reveal_status.setText("Choose a carrier first."); return
            secret = self._ask_passphrase(confirm=False)
            if secret is None:
                return
            dest, _ = QFileDialog.getSaveFileName(self, "Save the recovered payload", "revealed.bin")
            if not dest:
                return
            try:
                if Path(dest).exists():
                    Path(dest).unlink()
                result = core.reveal(self.reveal_carrier, dest, secret)
            except (VeilError, OSError) as exc:
                self.reveal_status.setText(str(exc)); self.reveal_status.setStyleSheet(f"#status{{color:{PINK};}}")
                return
            self.reveal_status.setText(f"Revealed {result['payload_bytes']:,} bytes → {Path(dest).name}")
            self.reveal_status.setStyleSheet(f"#status{{color:{CYAN};}}")

        def do_inspect(self):
            path, _ = QFileDialog.getOpenFileName(self, "Choose a carrier", "", self.IMAGE_FILTER)
            if not path:
                return
            self.i_lbl.setText(path)
            try:
                info = core.inspect(path)
            except (VeilError, OSError) as exc:
                self.i_result.setText(str(exc)); return
            verdict = "PAYLOAD PRESENT" if info["veil_payload_present"] else "no Veil payload marker"
            lines = [f"carrier   {Path(path).name}", f"kind      {info['kind']}", f"status    {verdict}"]
            if info.get("embedded_bytes"):
                lines.append(f"embedded  {info['embedded_bytes']:,} bytes (still encrypted)")
            lines += ["", info["note"]]
            self.i_result.setText("\n".join(lines))

        def _warn(self, message, icon=None, title="Veil"):
            box = QMessageBox(self); box.setWindowTitle(title)
            box.setIcon(icon or QMessageBox.Icon.Warning); box.setText(message); box.exec()

        def _animate(self):
            self.phase += 0.05
            self.header.tick(self.phase)

    return QApplication, Window


STYLE = f"""
#body {{ background: {BG}; }}
QWidget {{ color: {INK}; font-family: Helvetica, Arial, sans-serif; font-size: 13px; }}
#tag {{ color: {MUTED}; font-weight: bold; font-size: 11px; letter-spacing: 1px; }}
#status {{ color: {MUTED}; font-size: 12px; }}
#path {{ color: {DIM}; font-size: 12px; }}
#foot {{ color: {DIM}; font-size: 11px; }}
#mono {{ background: {PANEL_HI}; border: 1px solid {LINE}; border-radius: 9px; color: {INK};
         font-family: "Courier New", monospace; font-size: 13px; padding: 10px; }}
#preview {{ background: {PANEL_HI}; border: 1px solid {LINE}; border-radius: 12px; color: {DIM};
            font-family: "Courier New", monospace; }}
QTabWidget#tabs::pane {{ border: 1px solid {LINE}; border-radius: 12px; background: {PANEL}; padding: 10px; }}
QTabBar::tab {{ background: {PANEL_HI}; color: {MUTED}; padding: 8px 20px; margin-right: 6px;
                border-top-left-radius: 9px; border-top-right-radius: 9px; font-weight: bold; }}
QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {PINK}; }}
QProgressBar#cap {{ background: {PANEL_HI}; border: 1px solid {LINE}; border-radius: 5px; }}
QProgressBar#cap::chunk {{ background: {CYAN}; border-radius: 5px; }}
QPushButton#go {{ background: {PINK}; color: {BG}; border: none; border-radius: 10px; font-weight: bold; padding: 10px 18px; }}
QPushButton#go:hover {{ background: {CYAN}; }}
QPushButton#pick {{ background: {PANEL_HI}; border: 1px solid {LAVENDER}; border-radius: 9px; color: {INK};
                    font-weight: bold; padding: 8px 14px; }}
QPushButton#pick:hover {{ background: #1b2150; }}
"""


def run_app() -> int:
    try:
        from PyQt6.QtWidgets import QApplication  # noqa: F401
    except Exception:
        print("PyQt6 is required for the Veil window. Use 'envy-veil' subcommands in a terminal instead.")
        return 2
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("No display found. Use 'envy-veil hide/reveal/capacity/inspect' in a terminal instead.")
        return 2
    try:
        QApplication, Window = _build()
        app = QApplication.instance() or QApplication(sys.argv)
        window = Window(); window.show()
        return app.exec()
    except Exception as exc:  # pragma: no cover
        print(f"Could not open the window: {exc}")
        return 2
