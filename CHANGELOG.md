# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2026-10-18
### Added
- Kokoro Cloud: the same voice through OpenRouter's speech API (API key in settings), 8 requests at a time; a bad key or empty balance stops the job right away.
- Kokoro: natural-sounding offline voice, run through `uv` outside Calibre's Python. Now the default engine.
- M4B output (new default) with chapter markers, cover art and title/author tags via ffmpeg.
- Front and back matter (contents, copyright, acknowledgments, notes, index, About the Author, ads) are skipped; intros, prefaces, forewords and prologues are kept.
- Failed pieces are retried 3 times; the real error and any missing parts are reported.
### Changed
- Text is split at sentence ends instead of every 5000 characters, with pauses between paragraphs and chapters.
- Edge TTS English voices switched to Andrew/Ava Multilingual. Bumped edge-tts to 7.3.1 (7.2.8 was rejected with 403).
- Existing audiobooks in the unified folder are no longer overwritten.
### Removed
- VibeVoice engine and the non-functional "Audio quality" setting.

## [1.1.1] - 2026-08-11
### Fixed
- Edge TTS: removed an `audio_format` argument no longer accepted by the vendored edge-tts library, which was crashing every chunk.
- gTTS: fixed a Windows-only `PermissionError` caused by writing to a temp file while still holding it open.
- VibeVoice: missing `torch`/`transformers` now produce a single clear error explaining they must be installed separately, instead of five duplicate per-chunk failures.

## [0.2.0] - 2026-04-29
### Added
- Microsoft VibeVoice as an additional TTS engine option (local model, requires manual download).
- Dynamic UI updates: Voice gender and audio quality options are now disabled when VibeVoice or gTTS is selected.

## [0.1.9] - 2026-04-10
### Fixed
- Improved configuration UI to automatically disable unified folder selection when Internal storage mode is selected.

## [0.1.8] - 2026-04-10
### Added
- New storage mode options: "Internal" (save to Calibre book folder) and "External" (save to a single unified folder).
- Emblem synchronization now identifies audiobooks in both storage modes.
### Changed
- Refactored `has_audio_format` for better reliability in identifying existing audiobooks.

## [0.1.7] - 2026-04-10
### Added
- Expanded language support to include Portuguese, French, Italian, and Spanish (Spain).
- Improved automatic language detection to support 2-letter and 3-letter ISO 639 codes.
### Changed
- Refactored voice and language selection to use a more maintainable mapping dictionary.

## [0.1.6] - 2026-04-10
### Added
- New configuration option: "Detect language from book metadata".
- Automatic language detection for English and Spanish based on book metadata.

## [0.1.5] - 2026-04-08
### Added
- Initial release with support for Edge TTS and gTTS.
- Basic English and Spanish (Latam) support.
- Background generation and status bar progress tracking.
- Cassette emblem for covers of books with audiobooks.
