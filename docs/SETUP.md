# Setup

## Start in 60 Seconds

1. Run [VySol.bat](../VySol.bat). It will launch the backend, start the frontend in the current terminal window, and open a browser tab automatically.
2. On the home page, click the top-right settings icon.
3. Open `Key Library` and add the provider credentials you plan to use:
   - Google AI Studio, Anthropic, OpenAI, OpenRouter, Groq, Mistral, xAI, or other API keys for the providers you plan to use
   - Base URLs or richer credential fields for providers such as Ollama, OpenAI Compatible, or Vertex AI when those providers require them
4. Go back to `Configuration`. Leave the locked `Default` preset as-is for your first run, or save a new preset later if you want multiple global setups. The five AI slot cards start collapsed by default.
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
- Provider selectors are listed alphabetically.
- Some providers are `custom-model-first`, which means VySol shows a freeform model-id textbox with a placeholder example instead of a fixed dropdown. Right now that applies to `Hugging Face`, `NanoGPT`, `NVIDIA NIM`, `Ollama`, `OpenAI Compatible`, and `OpenRouter`.
- Other providers use catalog-backed model dropdowns and reject unknown model ids on save.

Default models (current):

- Graph Architect Model: `gemini/gemini-2.0-flash-lite`
- Chat Model: `gemini/gemini-2.0-flash`
- Entity Chooser Model: `gemini/gemini-2.0-flash-lite`
- Entity Combiner Model: `gemini/gemini-2.0-flash-lite`
- Default Embedding Provider: `Google AI Studio`
- Default Embedding Model: `gemini/gemini-embedding-001`

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

Launcher behavior:

- VySol opens the app at `http://127.0.0.1:3000`
- The frontend talks to the backend at `http://127.0.0.1:8000` by default
- Before launching, `VySol.bat` checks whether ports `8000` and `3000` are already in use
- For safety, it no longer auto-closes unrelated processes on those ports; if either port is busy, the launcher stops and tells you which PID to close manually
- `VySol.bat` also checks that LiteLLM is exactly `1.82.6` inside the backend virtual environment and stops if a different version is installed

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

By default the frontend talks to `http://127.0.0.1:8000`.
The repo now includes `frontend/.env.local.example` with that default value for clean local setup.

Local development notes:

- The backend's default CORS allowlist includes `http://localhost:3000`, `http://127.0.0.1:3000`, and `http://[::1]:3000`
- If you already have a custom frontend `.env.local`, make sure `NEXT_PUBLIC_API_URL` matches the backend you actually want to use
- If port `3000` or `8000` is already occupied, stop the old process manually before rerunning `VySol.bat`
- `backend/requirements.txt` pins `litellm==1.82.6`; do not upgrade LiteLLM separately unless you are intentionally changing the app's pinned provider layer too

## First Run Behavior

- `settings/settings.json` is created automatically when the backend first needs a live settings file
- Local worlds, graphs, vectors, and chat history are stored under `saved_worlds/`
- Provider credentials added in `Key Library` are stored locally in `settings/settings.json`
- The five AI slots in `Configuration` are `Graph Architect`, `Chat`, `Entity Chooser`, `Entity Combiner`, and `Default Embeddings`
- Provider and model options come from the backend LiteLLM catalog instead of hardcoded frontend family tables
- Strict providers use catalog dropdowns, while custom-model-first providers use freeform model-id entry with example placeholders
- The embedding slot only offers embedding-capable catalog providers and models, so chat-only Gemini models do not appear there
- `ChatGPT Subscription` is intentionally hidden from selectable provider lists
- This public repo does not ship with live secrets, saved worlds, imported corpora, or personal runtime data

Environment fallbacks:

- Many providers can still use environment fallbacks when no enabled Key Library entry is ready, including provider-specific API-key env vars such as `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `HF_TOKEN`, and others defined by the backend provider manifest
- Providers that use richer fields such as base URLs, Vertex project/location values, or local Ollama defaults can also surface those defaults or env-backed values through the same provider manifest
