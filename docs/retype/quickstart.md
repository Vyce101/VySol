---
order: 90
---
# Quickstart

Start the local Windows app and reach the Worlds homepage. VySol currently runs from its source folder; there is no desktop installer yet.

## Requirements

Install these before starting:

- [Python 3.12](https://www.python.org/downloads/windows/), including the Windows `py` launcher.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), available on your command path.
- [Node.js 24 with npm](https://nodejs.org/en/download), using the standard Windows installation layout.
- A web browser and an internet connection for the initial dependency download.

The launcher expects npm alongside Node.js. Developer setup and the frontend's supported Node.js versions are covered in [Development](development.md#run-from-source).

## Get the source

Download the source ZIP from the [VySol repository](https://github.com/Vyce101/VySol) using **Code > Download ZIP**, then extract it to a writable folder. Open the extracted folder containing `Start.cmd`.

## Run

Double-click `Start.cmd`. Keep its window open while using VySol.

The launcher installs the locked dependencies and builds the interface when necessary. It opens your browser once the server is ready, normally at `http://127.0.0.1:8765/`. Initial preparation may take longer than later launches.

## Confirm it works

You should see the **Worlds** homepage and a Settings gear. A new installation shows **Create Your First World** over the default background. Existing local data shows your saved worlds instead.

If the browser does not open but the launcher says VySol is ready, visit `http://127.0.0.1:8765/` yourself. If startup fails, the launcher window stays open with the error. Check that the required tools are installed and available before trying again. If the port is already in use, close the other VySol launcher or select another port as described in [Reference](reference.md#startup-options).

## Stop the app

Close the launcher window to stop its server and other app-owned processes. Closing just the browser tab leaves the server running. Closing the launcher does not close your browser.

Next, [create a world](create-world.md). You will need at least one TXT or EPUB book, an internet connection, and a Google AI Studio / Gemini API key. Closing the launcher pauses unfinished processing; restart and choose **Resume** to continue.
