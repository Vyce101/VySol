---
order: 70
---
# Reference

Supported values and behavior for the current local app. For the creation procedure, see [Create a world](create-world.md). Implementation contracts belong in [Development](development.md).

## Supported books

| Input | Working copy |
| --- | --- |
| TXT | UTF-8 without an encoding marker. Wording, whitespace, and line breaks are preserved. |
| EPUB 2 or 3 with extractable text | UTF-8 text extracted in the book's declared reading order. |

TXT accepts UTF-8 with or without a byte-order mark (BOM), or UTF-16/UTF-32 with an explicit BOM. Other encodings are not guessed. Invalid decoding and null characters are rejected rather than silently repaired or replaced. Save a corrected copy as UTF-8 in a text editor before importing again.

EPUB extraction retains text such as copyright notices, dedications, contents, headings, paragraphs, notes, captions, and link text. Supplementary reading-order entries are included. Navigation outside that sequence is included first, once; remaining text documents are appended in manifest order. EPUB 2 navigation labels are used when no textual contents document is identified. A document is extracted once, but repeated passages are not removed.

Readable block spacing and explicit line breaks are retained, and horizontal rules become plain-text separators. Exact typography, page layout, and visual chapter styling are not preserved. Scripts, styles, and image data are excluded. There is no OCR or external-resource fetching. Encrypted text, missing referenced content, and unsupported or unreadable text resources can prevent import.

PDF is not supported. An empty file or a book with only whitespace in its extracted text is rejected.

### Limits

| Limit | Default |
| --- | --- |
| Each uploaded file | 100 MiB (104,857,600 bytes) |
| EPUB archive entries | 10,000 |
| Total uncompressed EPUB content | 500 MiB (524,288,000 bytes) |

These are per-file/archive limits, not a combined allowance for all books in a world. They are not adjustable in Settings.

## Duplicate book names

Within a world, the app removes the final extension, trims surrounding whitespace from that name, and applies Unicode case folding before comparison. This rule works across TXT and EPUB.

For example, `Book.epub`, `book.txt`, and ` book .TXT` conflict. `Book.Part.1.epub` conflicts with `book.part.1.txt`, but not with `Book.Part.2.txt`. Dots inside a name are preserved.

This compares filenames, not book contents. Importing the same book into another world creates independent copies there. Files with directory components, unsafe characters, or reserved Windows filenames are rejected.

## Creation processing settings

These fields appear under **Processing** on Create World. Chunk settings are inside **Advanced Settings**.

| Field | Supported values | Default | Meaning |
| --- | --- | --- | --- |
| Embedding Model | Gemini Embedding 2 (`gemini-embedding-2`) | Last submitted model | Converts each chunk into a stored embedding for later retrieval. Retrieval is not available yet. |
| Credential | A saved Google AI Studio API key | Last submitted credential, if still available | A valid selection is required before submission. |
| Maximum chunk size (chars) | Whole number from 1 to 1,000,000 | 8,000 | Maximum characters in each text chunk before any further splitting required by the model. |
| Boundary search distance (chars) | Whole number from 0 to one less than Maximum chunk size | 1,000 | How far backward from the size limit VySol searches for a suitable break. Zero disables this search. |

Characters include spaces and line breaks. VySol counts Unicode code points rather than bytes; some displayed symbols contain more than one code point. Chunks are contiguous and do not overlap. Joining their text reproduces the working TXT exactly.

Within the search window, the splitter prefers paragraph breaks, then line breaks, then `?`, `!`, or `.`, then spaces or other whitespace. It chooses the latest break at the highest available priority. Punctuation stays with the preceding text. This is punctuation matching, so a period in an abbreviation or number can also become a break.

If no suitable break is found, VySol cuts at **Maximum chunk size**. For example, an 8,000-character maximum with a 7,000-character search looks backward through the last 7,000 characters before that limit. A preferred break near character 1,000 can produce a much shorter chunk; with no break, the cut stays at 8,000, not 7,000. The final chunk can be shorter simply because the book ends.

Gemini embeddings use a fixed 768 dimensions. If Google explicitly rejects a chunk as too large, VySol splits that chunk into smaller pieces using the same boundary priorities and retries. It saves the smaller chunks and updates the total chunk count without dropping text.

## Saved files

Each accepted upload produces an untouched original and a separate UTF-8 TXT working copy, including when the upload is already TXT. `Story.epub` becomes `Story.txt`; `Story.Part.1.epub` becomes `Story.Part.1.txt`. Originals are copied, never moved or altered.

The Windows launcher stores runtime data in the repository's `data/` folder by default. Books are inside `data/worlds/<world key>/books/<book key>/`, with `original/` and `text/` subfolders. The generated keys are internal identifiers, so folder names do not match world titles. Metadata records the correspondence.

Worlds, book copies, settings, custom artwork, logs, and creation staging files remain under the configured runtime directory. `processing.sqlite3` stores creation checkpoints, source offsets, chunk text, vectors, and credential labels. `creations/` holds attempt files. The repository excludes its root `data/` folder from Git. If you configure another location, choose one outside tracked source; the default exclusion does not automatically cover other folders. To back up the current application data, close the launcher first and copy the runtime directory. API key secrets are plain-text files under `credentials/` and are included in a full runtime backup. Keep that folder and its backups private. The credentials folder has its own ignore file so keys and temporary writes remain ignored even with a custom runtime directory.

## Browsing worlds

World names must be nonblank and at most 200 characters. Separate worlds can share the same display name.

A world card shows its book count and Ready, Creating, Paused, or Attention status. Opening a card shows its Overview: ordered Stories and saved World Details. A creating world's Overview also shows per-book chunk progress and Pause, Resume, or Discard World actions as appropriate. Several worlds can be created and processed at once.

Hovering, keyboard-focusing, or touching a card previews its title and background. Leaving it retains that preview. Search matches world names without case sensitivity and lists suggestions without rearranging the cards. Hovering or using arrow keys in search does not change the preview; selecting a result focuses and scrolls to its card.

The startup preview uses the most recently used world when usage information exists, otherwise the most recently created. Card previews do not record usage, and opening an Overview does not yet update usage history.

Frostwake is the default artwork for new worlds and the empty homepage. Artwork selection, world editing, book reading, chronicles, and AI roleplay are not available in this interface yet.

## Settings

The gear opens **Settings**. Use its X to return to the page you came from, including an unfinished Create World draft.

| Section / setting | Choices | Initial value | Persistence |
| --- | --- | --- | --- |
| AI Connections | Enable or disable Google under Select Connections; add, rename, reveal, replace, or remove numbered credentials | No connection | Names and sequence numbers in SQLite; plain-text secrets in the ignored credentials folder |
| General / World Display | Shelf; Grid | Shelf | Saved automatically |
| General / Background Transition Speed | Fast — 150 ms; Normal — 300 ms; Slow — 600 ms | Normal — 300 ms | Saved automatically; controls artwork changes |
| Developer / Homepage Preview | Your Saved Worlds; 4 Sample Worlds; 12 Sample Worlds; Empty Homepage | Your Saved Worlds | Resets on reload |

**Horizontal shelf** keeps cards in one row. Use the mouse wheel over the homepage, horizontal touch scrolling, or keyboard focus to reach more cards. **Grid** wraps cards into rows and allows vertical page scrolling for larger collections. Shelf mode and grids with up to four worlds adapt to ordinary viewport sizes without vertical page scrolling; extremely short windows keep controls readable instead of shrinking them indefinitely.

Developer options are available in normal builds too. Sample and empty previews do not create or delete stored worlds. Reduced-motion preferences remove animated background changes, card zoom, smooth wheel motion, and edge nudges.

If a saved setting fails to write, Settings displays an error and retains the last successfully saved value. There is no Save button.

## Startup options

| Environment variable | Default | Effect |
| --- | --- | --- |
| `VYSOL_PORT` | `8765` | Port used by the Windows launcher. The server binds to `127.0.0.1`. |
| `VYSOL_DATA_DIR` | Repository `data/` when launched with `Start.cmd` | Runtime storage location. Prefer an absolute path. |

For example, from PowerShell in the repository root:

```powershell
$env:VYSOL_PORT = "8766"
.\Start.cmd
```

Startup messages remain in the launcher window. Runtime logs are in `data/logs/` by default: `launcher.log` for startup and supervision, and `imports.log` for application and import outcomes. Each log retains at most ten previous rotated files.
