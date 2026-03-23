# Setup

## Start in 60 Seconds

1. Run [VySol.bat](../VySol.bat). It will launch backend/frontend and open a browser tab automatically.
2. On the home page, click the top-right settings icon.
3. Add your Gemini API keys.
4. Leave model defaults as-is for your first run (listed below).
5. Create a world.
6. Upload any `.txt` document.
7. Start ingestion and wait until it shows complete.
8. Open chat and ask a question.

After ingestion, you can optionally run Entity Resolution with either `Exact only` or `Exact + chooser/combiner`, and tune its unique-node embedding batch and delay controls per run.

API key note:

- Limits are tied to project context.
- Multiple keys from the same project share that project's limits.
- Splitting keys across projects can help isolate limits, but abusive or policy-violating traffic can still trigger enforcement across your usage.

Default models (current):

- Graph Architect Model: `gemini-3.1-flash-lite-preview` with `minimal` thinking
- Chat Model: `gemini-3-flash-preview` with `high` thinking
- Entity Chooser Model: `gemini-3.1-flash-lite-preview` with `high` thinking
- Entity Combiner Model: `gemini-3.1-flash-lite-preview` with `high` thinking
- Default Embedding Model: `gemini-embedding-2-preview`
- Gemini `Send Thinking`: `on` by default

Default chat settings (current):

- Top K Chunks: `5`
- Entry Nodes: `5`
- Graph Hops: `2`
- Max Graph Nodes: `50`
- Vector Query (Msgs): `3`
- Chat History Context (Msgs): `1000`

For full setup details and troubleshooting, use the sections below.

## Quick Start For Windows

If you are on Windows, the easiest path is:

1. Run [VySol.bat](../VySol.bat).
2. Let it check for supported Python and Node.js versions.
3. If something is missing, it will try to install it with `winget`.
4. It will create or reuse the backend virtual environment, install dependencies, and launch the app.

What `VySol.bat` expects:

- Windows
- `winget` available if prerequisites need to be installed
- Python 3.10 or newer
- Node.js 18 or newer

If Python and Node are already installed, the launcher will reuse them instead of reinstalling them.

## Manual Setup

If you do not want to use the batch file, you can run the app manually.

Requirements:

- Python 3.10 or newer
- Node.js 18 or newer
- npm

Backend:

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

By default the frontend talks to `http://localhost:8000`.

## First Run Behavior

- `settings/settings.json` is created automatically when the backend first needs a live settings file
- Local worlds, graphs, vectors, and chat history are stored under `saved_worlds/`
- Gemini API keys added in the app are stored locally in `settings/settings.json`
- This public repo does not ship with live secrets, saved worlds, imported corpora, or personal runtime data
