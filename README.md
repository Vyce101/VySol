<p align="center">
  <img src="docs/images/Social Preview 4 - Compressed.jpg" width="100%">
</p>

# VySol

VySol is a project for AI experiences set inside established fictional worlds.

Large fictional worlds contain far more than facts about characters and places. What happens in a scene can depend on events from much earlier in the story, relationships that changed over time, rules that are never repeated when they become relevant, and information that some characters know while others do not.

That creates a difficult problem for AI. Having access to the source material is not the same as understanding which parts of that world matter now.

VySol is being built around that problem.

## Why VySol

Imagine two characters arguing near the end of a story. The immediate conversation might explain what they are arguing about, but not why either of them reacts the way they do. That may depend on a betrayal several books earlier, a promise one character still considers binding, something only one of them knows, or a relationship that has changed repeatedly since they first met.

Those details may be far apart in the original material and may have almost nothing in common at the level of wording. To a reader, however, they belong to the same situation.

This is the gap VySol is interested in: helping an AI work with a fictional world as more than a collection of isolated pieces of text.

## Project status

VySol is under active development. The current `main` branch is the foundation of the new version and is not yet a finished end-user release.

Earlier prototypes are preserved in separate branches as previous iterations of the project. They should not be treated as a specification for how the new version will work.

## Get started

The current local app creates worlds from ordered TXT or EPUB books, splits their text into chunks, and saves Gemini embeddings with resumable processing. Named API keys are managed in Settings. Chronicles provide separate saved conversations within each world, retrieving relevant book passages for Google-hosted chat models.

Follow the [Quickstart](docs/retype/quickstart.md) to run it on Windows. Usage details and supported behavior are covered in the documentation.

## Documentation

- [Changelog](docs/CHANGELOG.md)
- [Documentation Home](docs/retype/index.md)

## License

[License](LICENSE)
