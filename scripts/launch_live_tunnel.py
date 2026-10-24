#!/usr/bin/env python3
"""
Automated Live Cloudflare Tunnel & Mobile QR-Code Orchestrator for MedBill Shield.

Features:
1. Checks/installs `cloudflared` (via portable GitHub release binary or winget)
   and ensures `qrcode` + `pillow` are installed.
2. Checks if FastAPI backend is running on http://127.0.0.1:8000; if not, launches
   Uvicorn (`backend.app:app --host 0.0.0.0 --port 8000`) in the background.
3. Starts `cloudflared tunnel --url http://127.0.0.1:8000` and parses the live
   `https://*.trycloudflare.com` URL.
4. Displays the live HTTPS URL, prints an ASCII QR code directly in the terminal,
   and saves a high-resolution `demo_qr.png` to the repository root.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

# Ensure UTF-8 output on Windows PowerShell so ASCII/Unicode QR blocks render cleanly
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
VENV_SCRIPTS_DIR = BACKEND_DIR / ".venv" / "Scripts"
SCRIPTS_DIR = REPO_ROOT / "scripts"
DEMO_QR_PATH = REPO_ROOT / "demo_qr.png"
LIVE_URL_FILE = REPO_ROOT / "live_tunnel_url.txt"

CLOUDFLARED_DOWNLOAD_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
)
TRYCLOUDFLARE_REGEX = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def ensure_python_dependencies() -> None:
    """Ensure `qrcode` and `pillow` are available in the active Python environment."""
    try:
        import PIL  # noqa: F401
        import qrcode  # noqa: F401
        return
    except ImportError:
        print("[Setup] Installing `qrcode` and `pillow` into Python environment...")
        uv_bin = shutil.which("uv")
        if uv_bin:
            subprocess.run(
                [uv_bin, "pip", "install", "--python", sys.executable, "qrcode", "pillow"],
                check=True,
            )
        else:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "qrcode", "pillow"],
                check=True,
            )


def ensure_cloudflared() -> str:
    """
    Locate `cloudflared` in PATH or local directories.
    If not found, download the official portable executable or install via winget.
    """
    # 1. Check system PATH
    system_cf = shutil.which("cloudflared")
    if system_cf:
        return system_cf

    # 2. Check local candidate paths
    candidates = [
        VENV_SCRIPTS_DIR / "cloudflared.exe",
        SCRIPTS_DIR / "cloudflared-windows-amd64.exe",
        SCRIPTS_DIR / "cloudflared.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    # 3. Download portable cloudflared-windows-amd64.exe
    target_path = VENV_SCRIPTS_DIR / "cloudflared.exe" if VENV_SCRIPTS_DIR.is_dir() else SCRIPTS_DIR / "cloudflared-windows-amd64.exe"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[Setup] `cloudflared` not found in PATH. Downloading official portable binary to {target_path}...")
    try:
        req = urllib.request.Request(
            CLOUDFLARED_DOWNLOAD_URL,
            headers={"User-Agent": "MedBillShield-Tunnel-Launcher/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as response, open(target_path, "wb") as out_file:
            shutil.copyfileobj(response, out_file)
        print(f"[Setup] Downloaded `cloudflared` successfully ({target_path.stat().st_size // (1024 * 1024)} MB).")
        return str(target_path)
    except Exception as dl_err:
        print(f"[Setup] Direct download failed ({dl_err}). Attempting winget installation...")
        subprocess.run(
            [
                "winget",
                "install",
                "Cloudflare.cloudflared",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            check=False,
        )
        system_cf = shutil.which("cloudflared")
        if system_cf:
            return system_cf
        raise RuntimeError("Unable to install or locate `cloudflared`.") from dl_err


def is_backend_running(url: str = "http://127.0.0.1:8000") -> bool:
    """Check if the local FastAPI server is responding on port 8000."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def ensure_backend_server() -> subprocess.Popen | None:
    """Start a fresh FastAPI Uvicorn server on 0.0.0.0:8000 with the latest code."""
    if is_backend_running():
        print("[Server] Restarting existing backend on port 8000 to load latest code...")
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }",
                ],
                check=False,
                capture_output=True,
            )
            time.sleep(1.0)
        except Exception:
            pass

    print("[Server] Launching FastAPI Uvicorn server on http://0.0.0.0:8000 ...")
    env = os.environ.copy()
    src_path = str(BACKEND_DIR / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".strip(os.pathsep)

    uvicorn_log = REPO_ROOT / "uvicorn_live.log"
    log_fh = open(uvicorn_log, "w", encoding="utf-8")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )

    # Wait up to 20 seconds for the server to become healthy
    for _ in range(40):
        if is_backend_running():
            print("[Server] FastAPI server is online and responding at http://127.0.0.1:8000")
            return proc
        if proc.poll() is not None:
            raise RuntimeError(
                f"Uvicorn process exited prematurely with code {proc.returncode}. Check {uvicorn_log}"
            )
        time.sleep(0.5)

    raise TimeoutError("Timed out waiting for FastAPI server on http://127.0.0.1:8000")


def generate_and_display_qr(public_url: str, open_target: str | None = None) -> None:
    """Render terminal ASCII QR code and save high-resolution `demo_qr.png`."""
    import qrcode

    LIVE_URL_FILE.write_text(public_url + "\n", encoding="utf-8")

    # 1. Generate high-res PNG image for slides / judge display
    qr_img_builder = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=14,
        border=3,
    )
    qr_img_builder.add_data(public_url)
    qr_img_builder.make(fit=True)
    img = qr_img_builder.make_image(fill_color="#1B3A6B", back_color="white")
    img.save(DEMO_QR_PATH)

    # 2. Print prominent banner + ASCII QR code in terminal
    border_line = "=" * 72
    print(f"\n{border_line}")
    print("  MEDBILL SHIELD — LIVE HTTPS MOBILE & JUDGE DEMO TUNNEL")
    print(border_line)
    print(f"\n  PUBLIC HTTPS URL :  {public_url}")
    print(f"  LOCAL SERVER URL :  http://127.0.0.1:8000")
    print(f"  SAVED QR IMAGE   :  {DEMO_QR_PATH}\n")
    print("  Scan this QR code with your smartphone camera:\n")

    qr_ascii = qrcode.QRCode(border=1)
    qr_ascii.add_data(public_url)
    qr_ascii.make(fit=True)
    qr_ascii.print_ascii(invert=True)

    print(f"\n{border_line}", flush=True)

    if open_target == "url":
        webbrowser.open(public_url)
    elif open_target == "qr":
        webbrowser.open(DEMO_QR_PATH.as_uri())


def start_cloudflare_tunnel(cloudflared_bin: str, target_url: str = "http://127.0.0.1:8000") -> tuple[subprocess.Popen, str]:
    """Start `cloudflared tunnel` and extract the generated `.trycloudflare.com` URL."""
    print(f"[Tunnel] Starting Cloudflare Quick Tunnel -> {target_url} ...")
    proc = subprocess.Popen(
        [cloudflared_bin, "tunnel", "--url", target_url, "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    captured_url: str | None = None
    start_time = time.time()

    assert proc.stdout is not None
    for line in proc.stdout:
        match = TRYCLOUDFLARE_REGEX.search(line)
        if match:
            captured_url = match.group(0)
            break
        if time.time() - start_time > 35:
            break

    if not captured_url:
        proc.terminate()
        raise RuntimeError("Failed to capture `.trycloudflare.com` URL from cloudflared output.")

    return proc, captured_url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch MedBill Shield FastAPI server + Cloudflare HTTPS tunnel + QR Code"
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Only verify/install cloudflared and Python QR dependencies, then exit.",
    )
    parser.add_argument(
        "--open",
        choices=["url", "qr", "none"],
        default="none",
        help="Optionally open the live URL or demo_qr.png in the default browser.",
    )
    args = parser.parse_args()

    ensure_python_dependencies()
    cf_bin = ensure_cloudflared()

    if args.setup_only:
        print(f"[Setup] Ready. cloudflared binary: {cf_bin}")
        return

    backend_proc = ensure_backend_server()
    tunnel_proc, public_url = start_cloudflare_tunnel(cf_bin, "http://127.0.0.1:8000")

    generate_and_display_qr(public_url, open_target=None if args.open == "none" else args.open)

    print("  Tunnel is active and forwarding traffic. Press Ctrl+C to stop.\n", flush=True)

    # Keep streaming tunnel output quietly so pipe buffer never blocks
    try:
        assert tunnel_proc.stdout is not None
        for _ in tunnel_proc.stdout:
            pass
    except KeyboardInterrupt:
        print("\n[Shutdown] Stopping Cloudflare tunnel and local server...")
    finally:
        tunnel_proc.terminate()
        if backend_proc is not None:
            backend_proc.terminate()


if __name__ == "__main__":
    main()

