# Setup

## Start in 60 Seconds

1. Run [VySol.bat](../VySol.bat). It will launch backend/frontend and open a browser tab automatically.
2. On the home page, click the top-right settings icon.
3. Open `Key Library` and add the provider credentials you plan to use:
   - Gemini API keys for Gemini-backed chat/extraction/entity-resolution/embeddings
   - Groq API keys for Groq-backed chat/extraction/entity-resolution
   - An IntenseRP base URL if you want chat to use IntenseRP Next
4. Go back to `Configuration`. Leave the locked `Default` preset as-is for your first run, or save a new preset later if you want multiple global setups.
5. Create a world.
6. Upload any `.txt` document.
7. Start ingestion and wait until it shows complete.
8. Open chat and ask a question.

After ingestion, you can optionally run Entity Resolution with either `Exact only` or `Exact + chooser/combiner`, and tune its unique-node embedding batch and delay controls per run.

Credential note:

- Limits are tied to project context.
- Multiple keys from the same project share that project's limits.
- Splitting keys across projects can help isolate limits, but abusive or policy-violating traffic can still trigger enforcement across your usage.
- `Configuration` presets are separate from the shared `Key Library`.
- The locked `Default` preset is the baseline global configuration.
- Keys and base URLs stored in `Key Library` are shared across every preset for that provider.

Default models (current):

- Graph Architect Model: `gemini-3.1-flash-lite-preview` with `minimal` thinking
- Chat Model: `gemini-3-flash-preview` with `high` thinking
- Entity Chooser Model: `gemini-3.1-flash-lite-preview` with `high` thinking
- Entity Combiner Model: `gemini-3.1-flash-lite-preview` with `high` thinking
- Default Embedding Provider: `Google (Gemini)`
- Default Embedding Model: `gemini-embedding-2-preview`
- Gemini `Send Thinking`: `on` by default
- Groq `Include Reasoning`: `off` by default when Groq chat is selected

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
# Optional: copy .env.local.example to .env.local and change the API URL if needed
npm run dev
```

By default the frontend talks to `http://localhost:8000`.
The repo now includes `frontend/.env.local.example` with that default value for clean local setup.

## First Run Behavior

- `settings/settings.json` is created automatically when the backend first needs a live settings file
- Local worlds, graphs, vectors, and chat history are stored under `saved_worlds/`
- Provider credentials added in `Key Library` are stored locally in `settings/settings.json`
- Gemini and Groq can be selected per text-model slot in `Configuration`
- Gemini-only controls such as `Disable Safety Filters` only appear when a Gemini slot is selected
- Groq-only controls such as reasoning effort and chat `Include Reasoning` only appear when Groq is selected
- Embedding provider settings exist globally and per world, but this build still blocks `OpenAI-compatible > Groq` for embeddings until a real embedding adapter exists
- This public repo does not ship with live secrets, saved worlds, imported corpora, or personal runtime data

Environment fallbacks:

- `GEMINI_API_KEY` can still act as a local Gemini fallback if no ready Gemini library entry is enabled
- `GROQ_API_KEY` can still act as a local Groq fallback if no ready Groq library entry is enabled
- `INTENSERP_BASE_URL` can still act as a local IntenseRP endpoint fallback
