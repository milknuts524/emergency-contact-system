"""Start only this application's server and Cloudflare Tunnel."""
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    from dotenv import load_dotenv
    load_dotenv(os.getenv("ENV_FILE", ".env"))
    if subprocess.call([sys.executable, "scripts/run_server.py", "--check"]):
        return 1
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        print("Install cloudflared before starting HTTPS access.")
        return 1
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", 8000))
    except OSError:
        print("Port 8000 is in use. Stop the existing application first.")
        return 1
    finally:
        probe.close()
    mode = os.getenv("PUBLIC_URL_MODE", "dynamic")
    if mode not in {"fixed", "dynamic"}:
        print("PUBLIC_URL_MODE must be fixed or dynamic.")
        return 1
    public_url = os.getenv("FIXED_PUBLIC_URL", "").rstrip("/")
    if mode == "fixed" and not public_url.startswith("https://"):
        print("Set FIXED_PUBLIC_URL to the public HTTPS address first.")
        return 1
    children = []
    try:
        server = subprocess.Popen([sys.executable, "scripts/run_server.py"])
        children.append(server)
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Application startup failed.")
            try:
                with socket.create_connection(("127.0.0.1", 8000), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Application startup timed out.")
        current_url = Path(os.getenv("CURRENT_URL_FILE", "current_url.txt"))
        if mode == "fixed":
            command = [cloudflared, "tunnel", "run", os.getenv("CLOUDFLARED_TUNNEL_NAME", "emergency")]
        else:
            current_url.unlink(missing_ok=True)
            command = [cloudflared, "tunnel", "--url", "http://127.0.0.1:8000"]
        with open("cloudflared.log", "w", encoding="utf-8") as log:
            tunnel = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            children.append(tunnel)
            print("Server bound to this PC only. Tunnel logs: cloudflared.log", flush=True)
            if mode == "dynamic":
                for _ in range(300):
                    if tunnel.poll() is not None:
                        raise RuntimeError("Tunnel failed. Check cloudflared.log.")
                    matches = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", Path("cloudflared.log").read_text(errors="replace"))
                    if matches:
                        public_url = matches[-1]
                        current_url.parent.mkdir(parents=True, exist_ok=True)
                        current_url.write_text(public_url + "\n", encoding="utf-8")
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Tunnel URL was not received. Check cloudflared.log.")
            print("Public HTTPS URL: " + public_url, flush=True)
            webbrowser.open(public_url)
            print("Press Ctrl+C to stop this server and tunnel.", flush=True)
            while all(child.poll() is None for child in children):
                time.sleep(0.5)
            raise RuntimeError("Server or tunnel stopped. Check the logs.")
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(str(exc))
        return 1
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())
