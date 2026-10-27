# Verification report

Tested 27 October 2026 in the cloud Linux workspace with Python 3.12.14, FFmpeg 7.1.5 and system Chromium.

- `./setup.sh` installed the pinned dependency lock and was rerun successfully without replacing `.env`.
- `python -m pytest -q`: **20 passed**. HTTP provider tests are stubbed; normal workflow tests use free mock providers. FFmpeg tests actually encode and decode full-resolution videos. Test data paths include spaces and an apostrophe.
- `python -m pip check`: no broken requirements.
- JavaScript syntax check and Python compilation passed.
- Chromium/Playwright completed the dashboard flow: new topic → generate script → edit/save → approve → generate images → approve all → save exact voice ID → generate mock narration → automatic render → playable video → MP4 download control. No JavaScript errors were observed. Desktop and mobile screenshots were inspected.
- The completed browser-run MP4 was 5.36 seconds. Chromium loaded metadata and advanced playback. HTTP media serving returned 206 for range requests.
- A real server process was stopped and restarted. The pre-approved demonstration remained Ready with its script and image approvals intact, and its saved MP4 remained accessible.
- `python -m app.sample` created a full mock sample and was rerun without creating duplicates. The script refuses live mode and now requires exclusive access to the data folder.

| Acceptance criterion | Evidence |
| --- | --- |
| Topic produces editable script | API test and Chromium editor/save workflow; mock text provider |
| Images blocked before script approval | Backend returns 409; exact revision tested |
| Individual image replacement/regeneration | Upload and regeneration tests retain other scenes and old assets |
| Narration blocked until every current image is approved | Backend 409 checks, including after replacement |
| Configured ElevenLabs voice | Stubbed live payload verifies exact voice ID, selected model and text; no substitution |
| Playable MP4 and aligned scenes | Real FFmpeg exports and full decode in both 1080×1920 and 1920×1080; actual per-scene audio durations, motion/captions and browser playback |
| Restart preserves projects/approvals | SQLite recovery test and actual server process restart |
| Failures retry using completed work | Simulated scene-two audio failure reuses completed scene-one receipt; bounded retries; uncertain live outcome acknowledgement |
| Script edits cannot reuse stale approvals | Version invalidation and in-flight stale-result tests; old files remain present |
| No automatic publishing | No publishing route or publishing integration exists |

## Scope limits

**No paid OpenAI or ElevenLabs request was made.** Real network credentials, account access, image-model capabilities, Liam likeness, voice quality, real timing output and billing still require a short user-run live project. Official provider SDK sources were consulted; stubbed requests verify the implemented API shape but are not live integration tests.

Mock audio consists of tones. Mock images are deliberately simple demo illustrations. Financial/current-event assertions are not independently verified: supplied URLs are preserved, current information is marked unverified, and creator review is required. Target duration guides script writing; measured narration determines output length. Live alignment is used where available, with estimated caption timing otherwise.

Saved cloud configuration contains `install_script`, `start_skill` and the two optional live-provider network domains. Draft saving does not apply the network policy or publish a filesystem snapshot. The user must review and save in environment settings, then publish. Restoration in a new cloud task has not been tested.

The single-user application is restricted to localhost, with no authentication/public hosting configuration. Windows requires WSL. Old media consumes disk until manually archived or removed. The MP4 is not an editable Canva project. A remote request can be charged before a lost response; uncertain attempts require acknowledgement rather than an automatic retry.
