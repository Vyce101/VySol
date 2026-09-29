---
label: AI Connections Reference
order: 65
---
# AI Connections Reference

Exact provider, credential, model, and Embedding Profile behavior for the local app. For the setup procedure, see [AI Connections](ai-connections.md).

## Provider support

| Provider | Chronicle chat | Embeddings | Model discovery | Key requirement |
| --- | --- | --- | --- | --- |
| Google | Gemini Interactions or Generate Content | Gemini `embedContent` | Google model list | Required |
| OpenAI | Responses API | Embeddings API | `/v1/models` | Required |
| Anthropic | Messages API | Not supported | `/v1/models` | Required |
| DeepSeek | Chat Completions | Not supported | `/models` | Required |
| OpenAI-compatible | Chat Completions | `/embeddings` | Configured `/models` | Optional when the server allows keyless access |

An OpenAI-compatible credential has a fixed **Base URL**. VySol appends `/models`, `/chat/completions`, or `/embeddings` for the requested operation. The address cannot contain credentials, a query, or a fragment, and it cannot be changed after the credential is saved.

## Credentials and model catalogs

Each credential has its own model catalog. Saving a new credential or replacing its key refreshes that catalog. VySol also refreshes catalogs in the background when their last successful update is at least 24 hours old. The refresh button checks the selected credential immediately.

A failed refresh records a safe error and retains the last successful model list and timestamp. Automatic retries for the same stale credential are spaced by at least 15 minutes during one app session. Disabling a provider preserves its credentials and cached catalogs, but the connection cannot refresh models or send requests until it is enabled again.

Model discovery does not make every returned model a chat or embedding model. VySol uses provider metadata and known model profiles to exclude models that do not support the requested operation.

## Embedding Profiles

Google, OpenAI, and OpenAI-compatible credentials can back an Embedding Profile.

| Field | Behavior |
| --- | --- |
| Profile Name | Required; up to 100 characters. |
| API Connection | An enabled credential that can reach an embedding model. A keyless compatible server is allowed. |
| Embedding Model | A model returned by that credential's catalog and not identified as unsupported for embeddings. |
| Dimensions | Starts at the model's highest known value. A smaller supported whole number can be selected before the profile is used. |
| Maximum Input | Highest known model input in tokens. VySol records this value as read only. |
| Default | The first saved profile becomes the configured default. Create World selects the last-used profile when available, otherwise the configured default. |

Known embedding models use these limits:

| Provider | Model | Highest dimensions | Maximum input |
| --- | --- | ---: | ---: |
| Google | `gemini-embedding-2` | 3,072 | 8,192 tokens |
| Google | `gemini-embedding-2-preview` | 3,072 | 8,192 tokens |
| Google | `gemini-embedding-001` | 3,072 | 2,048 tokens |
| OpenAI | `text-embedding-3-small` | 1,536 | 8,192 tokens |
| OpenAI | `text-embedding-3-large` | 3,072 | 8,192 tokens |
| OpenAI | `text-embedding-ada-002` | 1,536, fixed | 8,192 tokens |

VySol sends the selected dimensions to Google and to OpenAI models that accept custom dimensions. An unknown compatible embedding model can leave dimensions unknown until preflight. Preflight sends the text `VySol embedding profile check`, records the returned vector size, and must succeed before the profile is usable.

Once an unfinished World uses a profile, only its name can change. After completion, its provider, model, dimensions, input format, and compatible Base URL remain fixed. The profile can move to another credential only when those properties match. A profile used by a World or unfinished creation cannot be removed. A credential cannot be removed while any Embedding Profile references it or an unfinished creation depends on it.

Existing Google Worlds with 768-dimensional vectors retain their saved legacy input formatting and query prefix.

## Chat models and controls

**Tested** means VySol has a model profile that defines its supported API, output limit, and reasoning or thinking controls. **Untested** means the provider returned the model but VySol has no model-specific profile. Untested models remain selectable; unknown optional settings are omitted so the provider uses its defaults.

The Chronicle model picker searches model names, IDs, providers, and families. It groups up to three recent tested models first, then tested models by provider, followed by **Untested** models.

| Control | Behavior |
| --- | --- |
| Output Limit | Starts at the model's highest known output. A lower positive value is allowed. Unknown models show **Provider Default**. |
| Thinking Level | Google models with documented levels. Options include the model default and only its supported levels. |
| Reasoning | OpenAI, Anthropic, and DeepSeek models with documented levels. **Off** appears only when the model supports it. |
| Thinking Budget | Gemini 2.5 models that use a numeric budget instead of Thinking Level. |

Shared Output Limit and reasoning choices remain saved when the model changes. If the new model cannot use the saved value, VySol applies its documented default or the closest supported lower level without overwriting the shared choice.

## Gemini 2.5 Thinking Budgets

| Model | Blank value | Allowed value |
| --- | --- | --- |
| `gemini-2.5-pro` | Google's dynamic default | 128–32,768 tokens |
| `gemini-2.5-flash` | Google's dynamic default | 0–24,576 tokens; zero turns thinking off |
| `gemini-2.5-flash-lite` | Off | Zero for off, or 512–24,576 tokens |

These models use Google's streaming Generate Content API. Other profiled Google chat models use the Interactions API.

## OpenAI-compatible Advanced Settings

Compatible-server overrides are optional. A blank value is omitted from the request so the server uses its default.

| Setting | Supported value |
| --- | --- |
| Output Limit | Positive whole number, up to 1,000,000 through the settings contract |
| Temperature | 0.00–2.00 |
| Top P | Greater than 0.00 and at most 1.00 |
| Frequency Penalty | -2.00–2.00 |
| Presence Penalty | -2.00–2.00 |
| Seed | Whole number from 0 to 2,147,483,647 |
| Stop Sequences | Up to 16 nonblank sequences, each at most 200 characters; enter one per line |
| Reasoning Effort | Provider Default, Minimal, Low, Medium, or High |
| Verbosity | Provider Default, Low, Medium, or High |

VySol forwards only these named fields. A compatible server can reject a field that it does not implement.

## Developer model preview

**Settings > Developer > Model Picker Preview** adds VySol's documented chat profiles and previously discovered models to the Chronicle picker without requiring a working chat key. Preview choices are temporary, and Chronicle sending remains disabled until the preview is turned off. The setting resets to **Off** when the page reloads.
