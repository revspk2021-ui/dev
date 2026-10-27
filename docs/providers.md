# Integration references

Consulted 27 October 2026, before integration implementation.

The official documentation sites were attempted but the environment proxy blocked access. The current public SDK sources from the providers' own GitHub organisations were successfully retrieved instead:

- OpenAI Images: https://github.com/openai/openai-python/blob/main/src/openai/resources/images.py — generate/edit request fields, arrays of reference files, configurable image sizes, base64 output.
- OpenAI Responses: https://github.com/openai/openai-python/blob/main/src/openai/resources/responses/responses.py — separate instructions and input, JSON text format, output content and usage.
- ElevenLabs TTS: https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/text_to_speech/client.py — convert_with_timestamps, exact voice ID, model and voice settings, output format, previous_text/next_text for continuity, alignment output.

Documentation links for model capabilities and future changes:

- https://platform.openai.com/docs/guides/image-generation
- https://platform.openai.com/docs/api-reference/responses/create
- https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps

The app makes plain HTTPS calls with verified TLS, bounded timeouts and no automatic retries. Models are configuration, not assumed universal capabilities. No live paid requests were made during implementation. Contract tests inspect payloads with stub responses; they cannot prove your account's current model access, billing or real voice/image quality. Validate a short real project after securely configuring credentials, consciously approving each paid stage.
