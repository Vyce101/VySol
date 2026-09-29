---
order: 75
---
# Chronicles

A Chronicle is a separate conversation inside a World. Each World can hold several Chronicles, including ones with the same name. Creating a Chronicle leaves you on its list so you can choose when to open it.

## Start a Chronicle

Open a World and choose **Chronicles** in its sidebar. Choose **New Chronicle**. New conversations are named **New Chronicle** until you rename them from the three-dot menu; sending a message does not rename them. The menu also lets you delete a Chronicle and its messages after confirmation.

Chronicles can be created while a World is processing. Chat becomes available when the World's books have finished embedding. If you try to open a Chronicle earlier, VySol points you to **Overview** to check progress.

Use **Search Chronicles** to filter the current World's Chronicle names. Matching ignores letter case and accents. The list shows each Chronicle's latest message preview, last message time, and total count of user and AI messages. A new Chronicle says **No messages yet** and **Not started**.

## Chat

Open a Chronicle and write in **What do you do?**. Before contacting the selected chat model, VySol searches that World's embedded book chunks using your latest message. It sends qualifying passages along with the prior conversation. If no passage meets the similarity setting, the conversation can still continue.

Unsent text stays with its Chronicle when you switch between Chronicles in the same World. It is not a saved message; reloading the page or leaving and reopening the World clears those drafts. The message field starts at one line, grows to about four lines, then scrolls within the field. It shrinks again when you delete text or send the message.

The response appears as it arrives at the chosen display speed. The square control stops generation and retains answer or thinking text already received. **Thinking** appears only when the provider supplies readable thinking; it is separate from the answer and can be expanded or collapsed. VySol does not add a built-in roleplay instruction, so the selected model's response style can vary.

While a response is generating, you can edit the next message in **What do you do?**; send it after the current response finishes. The transcript scrolls independently, keeping the Chronicle title and message box in place as you read older messages. Scrollbars appear during vertical scrolling and fade when movement stops.

## Chronicle Settings

Use the control below the message box to open the Chronicle **Settings** drawer. Choose an **API Connection** and one of its discovered **Chat Models** in **AI**. Search matches model names, IDs, providers, and model families without case sensitivity. The picker groups recent models first, then tested models by provider, with **Untested** models in their own group. The refresh button checks the selected connection for model changes. Sending requires an enabled connection; an OpenAI-compatible server may work without a key if the server allows it. Add or enable connections in **Settings > AI Connections**, following the [AI Connections guide](ai-connections.md) when you need to set one up. The read-only World embedding details show the profile used for that World's books.

**Tested** models have a VySol profile for translating their supported settings. **Untested** means the provider returned a model without that profile; it can still be selected, and unknown optional settings are left to the provider. **Output Limit** starts at the model's highest known limit. The reasoning control is labeled **Thinking Level** for Google and **Reasoning** for other providers. It offers the model default and supported levels, including **Off** where available. These chat choices are shared across Chronicles and Worlds. Switching models carries your choices across, but each model uses only its supported effective value. See the [AI Connections reference](ai-connections-reference.md#chat-models-and-controls) for catalog behavior, settings, and limits.

Gemini 2.5 models use a numeric **Thinking Budget** instead of Thinking Level. Leave the field blank to use Google's default:

| Model | Default when blank | Thinking Budget |
| --- | --- | --- |
| Gemini 2.5 Pro | Dynamic | 128–32,768 tokens; zero is not allowed |
| Gemini 2.5 Flash | Dynamic | 0–24,576 tokens; zero turns thinking off |
| Gemini 2.5 Flash-Lite | Off | Zero for off, or 512–24,576 tokens when enabled |

VySol uses Google's Generate Content API for these models. See the [AI Connections reference](ai-connections-reference.md#gemini-25-thinking-budgets) for the exact provider behavior.

OpenAI-compatible models have an **Advanced Settings** disclosure with optional output limit, sampling, penalty, seed, stop sequence, reasoning effort, and verbosity controls. Some compatible servers may reject an optional setting; see the [supported ranges](ai-connections-reference.md#openai-compatible-advanced-settings).

For interface previews, **Settings > Developer > Model Picker Preview** shows documented chat models and any previously discovered chat models in the Chronicle picker without requiring a working chat key. Choices made in this preview are temporary, and sending is disabled until the preview is turned off.

**Retrieval** controls the maximum number of passages, Minimum Similarity, and preceding source characters included with each passage. **Section Tags** holds editable plain-text prefixes and suffixes around chat history and retrieved passages. **Response** controls how answer text is revealed: **Off** waits for generation to finish, 1–99 chars/s reveals gradually, and **Instant** shows provider output as it arrives. Thinking text is never slowed by this setting. If generation fails after producing usable text, VySol reveals that partial answer even when Off is selected.

These settings are shared by every Chronicle in every World. Each drawer section starts open, and VySol remembers whether you leave it open or closed.

To change the artwork shading while chatting, open **Settings > General > Chronicle Chat Appearance**. **Focus the Reading Area** shades the center and leaves the surrounding artwork clear; **Shade the Full Page** darkens the full background.
