---
label: AI Connections
order: 85
---
# AI Connections

AI Connections store provider credentials and the models available to each credential. **Embedding Profiles** choose the provider connection and embedding model that a World uses for its saved vectors. Chronicles choose a chat model separately.

## Choose a provider

Open **Settings > AI Connections** and choose **Select Connections**. Enable the providers you want to use: Google, OpenAI, Anthropic, DeepSeek, or OpenAI-compatible.

Google, OpenAI, and OpenAI-compatible servers that provide embeddings can be used for Embedding Profiles. Anthropic and DeepSeek connections are available for Chronicle chat.

## Add a credential

Expand an enabled provider and choose **Add Credential**. Enter a **Connection Name** and the provider's **API Key**, then choose **Save Changes**. Hosted providers require a key. OpenAI-compatible connections also require the server's **Base URL**; their key is optional when the server does not require authentication. Model discovery and embeddings can work without a key on a keyless compatible server.

The Base URL is fixed after the compatible credential is saved. If it is wrong, add a new credential with the correct address and update any profile that can safely use it. When editing a saved credential, a blank API Key keeps its current secret; enter a new key to replace it.

Credentials are stored as plain-text files in the local runtime's `credentials/` folder. The key stays masked unless you choose **Show API Key**. Anyone with access to that folder or its backups can read the key, so keep them private. Processing sends book chunks to the provider selected by the World’s profile and uses that connection's API allowance.

## Find and refresh models

VySol checks a provider's model list when a credential is saved and stores the result for that credential. The model list can refresh in the background when it becomes stale. While adding or editing an Embedding Profile, choose its API Connection and use **Refresh models** beside **Embedding Model** to check immediately.

If a refresh fails, VySol shows the error and keeps the last successful list when one is available. A model marked **Untested** has not been given model-specific settings by VySol; an OpenAI-compatible model may still work if the server supports the requested operation.

## Create an Embedding Profile

In **Embedding Profiles**, choose **Add Profile**, then give it a name, choose an API Connection, and select one of that connection's discovered embedding models. The first saved profile becomes the configured default. **Create World** selects the last-used profile when one is available, otherwise it selects the configured default. You can choose another profile for an individual World.

**Dimensions** starts at the model's highest known value. You can choose a smaller supported value before a World uses the profile. For OpenAI embedding models that accept custom dimensions, VySol sends the selected value to OpenAI and stores vectors at that size. The profile's maximum input limit comes from the model catalog when known. VySol records it as read-only information and shows it with the World's embedding details. This limit is in tokens, while **Maximum Chunk Size** in Create World is measured in characters.

Some compatible models do not publish their embedding dimensions. VySol runs a small **preflight** embedding request when you save a profile that needs checking. A successful check confirms the connection can return an embedding and records the returned vector size. The request goes to your provider and may count toward its API usage. The profile must pass preflight before it can be used to create a World.

## Confirm it works

The saved profile appears under **Embedding Profiles** with its provider, model, and connection. Open **Create World** and confirm that **Processing** selects the last-used profile or the configured default and lets you choose another usable profile.

## Keep profiles compatible

Once an unfinished World uses a profile, only the profile's name can change. Its API Connection, Embedding Model, and Dimensions stay locked until that unfinished creation is discarded or completed. A profile used by any World cannot be deleted.

A profile used by a completed World must keep the same provider, model, and dimensions so its saved vectors remain compatible. For an OpenAI-compatible server, the Base URL must also stay the same. You can change the profile's API Connection to another credential only when those compatibility details match. A credential cannot be removed while a profile or unfinished creation still uses it.

## If a connection does not work

- If no models appear, confirm that the provider is enabled and the credential is saved. Check that a hosted API key is current, or that the compatible Base URL is correct and reachable. Then refresh the models.
- If an Embedding Profile is unavailable in Create World, confirm its connection is enabled and its key is present. Choose an embedding model and complete preflight if VySol asks for it.
- If a World reports a key error, pause it before replacing the credential's API Key, then resume the World. If you changed a compatible server address, create a credential for that address and preserve the profile's compatibility with any completed Worlds.
