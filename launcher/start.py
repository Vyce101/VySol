"""Windows launcher: prepare locked dependencies, supervise the server, retain errors."""

import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import socket
import sys
import time
from urllib.request import urlopen
import webbrowser

from windows_job import ProcessJob

ROOT = Path(__file__).resolve().parents[1]


class ColorFormatter(logging.Formatter):
    def format(self, record):
        color = {10: "\033[34m", 20: "\033[32m", 30: "\033[33m", 40: "\033[31m", 50: "\033[1;37;41m"}[record.levelno]
        return color + super().format(record) + "\033[0m"


def logger_for(root):
    folder = root / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("vysol.launcher")
    logger.setLevel(logging.INFO)
    terminal = logging.StreamHandler(sys.stdout)
    terminal.setFormatter(ColorFormatter("%(levelname)s %(message)s"))
    disk = RotatingFileHandler(folder / "launcher.log", maxBytes=1024 * 1024, backupCount=10, encoding="utf-8")
    disk.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.handlers = [terminal, disk]
    return logger


def frontend_fingerprint():
    digest = hashlib.sha256()
    frontend = ROOT / "frontend"
    for path in sorted(frontend.rglob("*")):
        if path.is_file() and not {"node_modules", "dist", ".vite"}.intersection(path.relative_to(frontend).parts):
            digest.update(str(path.relative_to(frontend)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def run():
    data = Path(os.environ.get("VYSOL_DATA_DIR", ROOT / "data")).resolve()
    logger = logger_for(data)
    job = ProcessJob()
    try:
        port = int(os.environ.get("VYSOL_PORT", "8765"))
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise RuntimeError(f"Port {port} is already in use. Close the other VySol instance or choose VYSOL_PORT.") from None
        uv, node = shutil.which("uv"), shutil.which("node")
        if not uv or not node:
            raise RuntimeError("Install Python 3.12, uv, and Node.js with npm, then start VySol again.")
        npm = Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if not npm.is_file():
            raise RuntimeError("npm was not found alongside Node.js. Repair the Node.js installation.")
        environment = {**os.environ, "VYSOL_DATA_DIR": str(data), "PYTHONUNBUFFERED": "1"}
        def command(args, cwd=ROOT):
            process = job.spawn(args, cwd=cwd, env=environment)
            if process.wait() != 0:
                raise RuntimeError("Preparation failed. Review the output above and try again.")
        logger.info("Checking Python dependencies")
        command([uv, "sync", "--locked"])
        fingerprint = frontend_fingerprint()
        stamp = data / "frontend-build.json"
        try:
            previous = json.loads(stamp.read_text()).get("fingerprint")
        except (FileNotFoundError, json.JSONDecodeError):
            previous = None
        if previous != fingerprint or not (ROOT / "frontend/dist/client/index.html").exists():
            logger.info("Preparing the interface")
            command([node, str(npm), "ci", "--no-audit", "--no-fund"], ROOT / "frontend")
            command([node, str(npm), "run", "build"], ROOT / "frontend")
            stamp.write_text(json.dumps({"fingerprint": fingerprint}))
        logger.info("Starting VySol")
        server = job.spawn([str(ROOT / ".venv/Scripts/python.exe"), "-m", "uvicorn", "vysol.server:create_app", "--factory", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"], cwd=ROOT, env=environment)
        address = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError("The server exited before startup completed.")
            try:
                with urlopen(address + "/api/health", timeout=1) as response:
                    if json.load(response).get("app") == "vysol":
                        break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError("The server did not become ready in time.")
        logger.info("VySol is ready. Close this window to stop the app.")
        webbrowser.open(address)
        code = server.wait()
        logger.warning("The server stopped with exit code %s. Close this window when ready.", code)
    except KeyboardInterrupt:
        logger.info("Stopping VySol")
    except Exception as error:
        logger.error("%s", error)
    finally:
        job.close()
        logger.info("All app-owned processes stopped")


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        print(f"Startup failed: {error}", flush=True)
    print("Close this window when you are ready.", flush=True)
    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            pass
