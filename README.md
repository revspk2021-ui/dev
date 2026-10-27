# The Lazy Aussie Investor · Creator Studio

A working, local video-production app for a single creator. Python/FastAPI serves the dashboard; SQLite saves projects, exact-version approvals and background jobs; FFmpeg makes the MP4. No accounts, rendering subscription or YouTube publishing integration.

## Start on your computer

You need **Python 3.12 or newer** and **FFmpeg** (including FFprobe, libx264 and libass). Supported first-version platforms are Linux and macOS; Windows users can use Ubuntu through WSL. The cloud workspace already has these prerequisites.

- Ubuntu/WSL: `sudo apt-get install python3-venv ffmpeg fonts-dejavu-core`
- macOS with Homebrew: `brew install python ffmpeg`

In this project folder, run:

```bash
./setup.sh
./start.sh
```

Open `localhost:8000` in your local browser. Leave the terminal running; Ctrl+C stops the app. To restart, run `./start.sh` again. Run only **one instance**, without `--reload` or extra workers. An instance lock prevents two workers using the same data directory. The app binds to loopback and rejects other hosts and cross-origin writes. It is not configured as a public website.

`setup.sh` installs pinned dependencies into `.venv` and creates `.env` only if you do not already have one. There is no separate database setup. `data/studio.sqlite3` and `data/assets/` are created automatically. Back up the **entire data folder** while the app is stopped, along with your `.env` separately. Do not move just the database: manifests contain absolute asset paths. Keep `.env` and data out of source control.

## Try the free demonstration

The default `PROVIDER_MODE=mock` never calls paid providers. It produces an editable demonstration script, clearly labelled illustrations and **audible placeholder tones, not spoken narration**. FFmpeg still produces a real, playable MP4. Mock images do not reproduce Liam's actual likeness.

With the server stopped, create the sample:

```bash
.venv/bin/python -m app.sample
./start.sh
```

The sample is deliberately pre-approved and marked `DEMO`. It does not approve any of your own projects. The sample command is repeatable and refuses to run in live mode. A finished sample is already present in this prepared cloud workspace. The normal flow starts from New project and requires your approvals.

## Your production workflow

1. Choose **New project**. Add the topic, research, supplied source links, format and target duration. Research is data, never instructions to operate the server. Links are not fetched automatically.
2. Under **Research & references**, upload Liam's host references and optional style examples. Save them as defaults for future projects if you like. Every real image-generation request includes every uploaded reference. Check the images yourself: identity and clothing consistency are not guaranteed.
3. Generate the script. Edit the hook, each spoken segment, visual direction and planned text. Source notes stay separate. Save, then explicitly approve the current script revision. Changes invalidate approvals and downstream assets; previous versions remain stored.
4. Generate images. Review each image and approve individually or approve all. Regenerate a single scene with feedback or upload a replacement without disturbing other scenes. Replacements need fresh approval. **Narration and rendering are blocked until all current images are approved.**
5. Save your exact ElevenLabs voice ID and settings under **Voice & video**. Generate narration. Rendering follows automatically unless you select **Review audio before rendering**. Use the audio player to review, or explicitly regenerate.
6. Preview the finished video and download MP4. Output is 1080×1920 or 1920×1080, H.264 video, AAC audio, 25 fps. This is a finished MP4, **not an editable Canva timeline**. Nothing is published automatically.

Defaults use static images and simple cuts. Optional gentle motion is slow and centred. Captions are optional and placed above typical interface areas. The render overlay field on each image is separate from the approved narration; changing it or the render settings does **not** regenerate images or audio. Save render changes, then click Render again. The last MP4 is labelled outdated until a current render finishes.

**Target duration is writing guidance, not a guarantee.** The actual narration length determines the video length. Each narration scene is generated separately; long scenes are split at whitespace under the configured provider limit without discarding words. Adjacent text is sent as continuity context. Actual measured audio lengths determine scene cuts, rounded to video frames (about 40 ms). Provider character alignment drives captions when returned; otherwise caption timing is estimated within its actual audio segment. Mock captions use that estimate. Review pauses and scene boundaries before publishing manually.

## Enable real OpenAI and ElevenLabs providers

Stop the app. Open `.env` in a text editor on your computer—**do not paste keys into chat**. Set:

```dotenv
PROVIDER_MODE=live
OPENAI_API_KEY=your-private-key
OPENAI_TEXT_MODEL=your-accessible-text-model
OPENAI_IMAGE_MODEL=your-accessible-image-model
ELEVENLABS_API_KEY=your-private-key
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
```

The placeholders above are not model suggestions. Choose models your account can access. The text model must support Responses API JSON-object output. The image model must support base64 output, multi-image edits and your configured sizes. Size defaults are 1024×1536 and 1536×1024, centre-fitted locally to the final 9:16 or 16:9 ratio. Override `OPENAI_IMAGE_SIZE_VERTICAL` and `OPENAI_IMAGE_SIZE_LANDSCAPE` to sizes supported by your selected model. Supply all relevant Liam references; without them generation cannot preserve his identity. Exact text and figures are added by the local renderer, not the image model.

Restart with `./start.sh`. Set **your existing ElevenLabs voice ID** in channel preferences or project settings. The app never chooses another voice when it is missing or fails. Voice stability, similarity, style, speaker boost and speed are sent to ElevenLabs; choose a model that supports them. `ELEVENLABS_TEXT_LIMIT` can be reduced for a model with a lower limit. Requests use the timestamp endpoint and MP3 44.1 kHz / 128 kbps. The provider might reject unsupported settings or an unavailable voice; check your account and model rather than substituting a voice silently.

For cloud environments using proxy-injected credentials, the app also accepts **LAZY_OPENAI_KEY** in place of OPENAI_API_KEY. Configure it securely for `api.openai.com` and ELEVENLABS_API_KEY for `api.elevenlabs.io`; do not put raw keys in saved setup scripts. OPENAI_API_KEY is a reserved name in the cloud secret-settings tool, so use LAZY_OPENAI_KEY there. Live network access needs those two domains. Local `.env` credentials use normal direct HTTPS.

The dashboard shows mock/live mode prominently. Changing modes does not magically regenerate earlier mock assets: create a fresh live project for production. Keys stay server-side, are not included in API responses, and are never logged. Reference images, research and narration are sent to the configured providers in live mode—use material you are entitled to share.

## Facts, spending and safe recovery

There is **no independent web fact-checker** in this version. The report flags current information as unverified, records supplied links and asks you to check dates, claims and whether a policy is proposed or already in effect. No URL is claimed as checked. Review narration and sources before approval; AI-generated financial information can be wrong. This limitation is visible in the UI and the generated report.

Project limits cap scene count and manual retries/regenerations. There are no automatic provider retries. Rapid duplicate requests reuse the same queued job; completion receipts are saved for each image or narration chunk. Retrying a failed job reuses completed chunks. Provider usage is shown when returned; characters and voice ID are recorded for narration. The app does not show a dollar estimate because pricing depends on your chosen models and account. Set provider-side spending limits as well.

A request can be billed even if the connection drops. Exactly-once execution across a remote API and SQLite is not guaranteed. On restart, interrupted jobs become failed; they are **not automatically replayed**. If a live call has an uncertain outcome, check the provider dashboard before explicitly acknowledging a possible duplicate charge and retrying. Bounded retries cannot eliminate that remote billing risk. Old job output is retained but cannot replace newer content. Job progress, errors and retry controls appear under Production activity.

Script history, old images, audio, videos and provider receipts are retained in the database/data folder. Usage & retained versions includes a downloadable project manifest with their asset URLs and paths. No automatic pruning runs. You will need enough disk space; backup and retention management are manual in this first version.

## Development and verification

```bash
.venv/bin/python -m pytest -q
node --check static/app.js  # optional, if Node is installed
```

Tests always use mocks or stubbed HTTP and temporary databases, so they do not incur API charges. They cover backend approval enforcement, exact-version invalidation, individual image replacement, duplicate jobs, bounded retry, chunk reuse, uncertain live outcomes, stale running jobs, restart recovery, selected voice payloads, reference attachments, local-host security and full FFmpeg export/decoding in both formats, including motion and captions. See [verification notes](docs/verification.md) and [provider references](docs/providers.md).

The API is documented locally at `/docs`. Source layout: `app/main.py` owns storage, API and job coordination; `app/providers.py` owns integrations and mocks; `app/render.py` owns timing and FFmpeg; `static/` is the dashboard. No JavaScript build step or additional paid renderer is required.
