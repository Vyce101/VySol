# Quickstart

## Requirements

- OS support: Windows.
- Python: Python `3.14.0` or newer. VySol is currently tested against Python `3.14.x`.
- Node.js: Node.js `20.19.0` or newer. VySol is currently tested against Node.js `24.x`.
- Git: required for the Git command install path.
- Local services: no manual service install is required for the current bootstrap.
- API keys: provider API keys will be required for AI-backed ingestion, embeddings, graph extraction, and future chat. The app can open before keys are configured.
- Hardware: no local GPU is required for cloud-provider workflows. Large worlds will need more disk space, setup time, provider quota, and processing time.

## GIT COMMANDS

Open PowerShell in the folder where VySol should be installed.

Copy and paste this setup command:

```powershell
git clone https://github.com/Vyce101/VySol.git VySol
cd VySol
py -3.14 -m venv .venv
```

Run VySol:

```powershell
.\run.bat
```

After setup, run `run.bat` from the project folder whenever you want to start VySol again.

On the current bootstrap, `run.bat`:

- checks the existing local `.venv`
- installs pinned Python dependencies from `requirements.txt` if missing
- starts the backend
- waits for the backend health check to be ready
- opens the health check in your browser
- writes launcher runtime logs under `runtime/logs`

Closing the `run.bat` window or pressing `Q` in it stops the app-owned runtime processes that launcher started.

## DOWNLOADING LATEST INSTALL

1. Download the latest main ZIP: [VySol ZIP](https://github.com/Vyce101/VySol/archive/refs/heads/main.zip).
2. Unzip the downloaded file.
3. Open the unzipped `VySol-main` folder.
4. Run `run.bat`.

The ZIP path uses the latest main branch. Released app builds may not include every documented feature yet.
