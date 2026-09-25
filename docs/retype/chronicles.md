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

The response appears as it arrives at the chosen display speed. The square control stops generation and retains answer text or a thinking summary already received. **Thinking** appears only when the provider supplies a readable summary; it is separate from the answer and can be expanded or collapsed. VySol does not add a built-in roleplay instruction, so the selected model's response style can vary.

While a response is generating, you can edit the next message in **What do you do?**; send it after the current response finishes. The transcript scrolls independently, keeping the Chronicle title and message box in place as you read older messages. Scrollbars appear during vertical scrolling and fade when movement stops.

## Chronicle Settings

Use the control below the message box to open the Chronicle **Settings** drawer. Choose an **API Connection** and **Chat Model** in **AI**. Model choices remain visible even when no connection is enabled, but sending requires a usable saved API key on an enabled connection. Add or enable one in **Settings > AI Connections** before sending. The read-only **Embedding Model** field shows the model used for that World's books.

**Retrieval** controls the maximum number of passages, Minimum Similarity, and preceding source characters included with each passage. **Section Tags** holds editable plain-text prefixes and suffixes around chat history and retrieved passages. **Response** controls how answer text is revealed: **Off** waits for generation to finish, 1–99 chars/s reveals gradually, and **Instant** shows provider output as it arrives. Thinking summaries are never slowed by this setting. If generation fails after producing usable text, VySol reveals that partial answer even when Off is selected.

These settings are shared by every Chronicle in every World. Each drawer section starts open, and VySol remembers whether you leave it open or closed.

To change the artwork shading while chatting, open **Settings > General > Chronicle Chat Appearance**. **Focus the Reading Area** shades the center and leaves the surrounding artwork clear; **Shade the Full Page** darkens the full background.
