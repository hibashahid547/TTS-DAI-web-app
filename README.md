# TTS-DAI (FastAPI + Chatterbox TTS, CPU-only)

Production-style Text-to-Speech API for marketing voiceovers using **Chatterbox TTS** with **CPU-only** inference.

## Features

- **POST `/tts`**: Send `text` + `voice` and get an **MP3** back
- **Human-like pacing**: text is split into sentence-sized chunks and stitched with natural pauses (no “one-go” monotone dump)
- **GET `/voices`**: discover available voices and their specialty/use-case
- **CPU-only**: explicitly forces `device=cpu`

## Requirements

- Python 3.11 recommended
- `ffmpeg` installed and available in `PATH` (required for MP3 export via pydub)

### Install ffmpeg (Windows)

- Download: https://www.gyan.dev/ffmpeg/builds/
- Add the `bin/` folder to your `PATH`
- Verify:

```powershell
ffmpeg -version
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```powershell
uvicorn main:app --host 0.0.0.0 --port 8965
```

## Run with Docker (recommended)

### Docker Compose

```powershell
docker compose up --build
```

Notes:

- The compose file mounts `./voices` into the container (read-write) so the Voice Studio can save new voices.
- Model/download caches are persisted in the named volume `tts_model_cache` to avoid re-downloading weights.

### Docker (without compose)

```powershell
docker build -t tts-dai .
docker run --rm -p 8965:8965 -v tts_model_cache:/cache -v ${PWD}/voices:/app/voices tts-dai
```

Open:
- Swagger UI: http://localhost:8965/docs
- OpenAPI: http://localhost:8965/openapi.json

## Web UI

This service also ships with a server-rendered UI (Tailwind + Jinja):

- **Dashboard:** http://localhost:8965/ui
- **Voice Studio:** http://localhost:8965/ui/voices
  - Upload MP3/WAV reference clip
  - Auto-convert to normalized mono WAV (24kHz) under `voices/<voice>.wav`
  - Writes metadata to `voices/voices.json`
- **TTS Studio:** http://localhost:8965/ui/tts
  - Script editor + voice picker
  - Pacing controls (chunk size + pause durations)
  - Exports MP3 with selectable bitrate

## Supabase persistence (recommended for production)

To avoid losing voices on redeploy and to share voices across servers, configure Supabase:

### 1) Storage bucket

- Create a **public** Supabase Storage bucket named: `TTS-VOICES`
- The app uploads normalized reference WAVs to `TTS-VOICES/voices/<voice>.wav`

### 2) Database table

Create a table (default name: `tts_voices`) to store voice metadata:

```sql
create table if not exists public.tts_voices (
  voice text primary key,
  display_name text not null,
  specialty text not null default '',
  use_case text not null default '',
  notes text not null default '',
  storage_path text,
  public_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
```

### 3) Environment variables

Copy `.env.example` to `.env` and fill in:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Notes:

- Use the **Service Role key on the server only** (never in browser JS).
- When Supabase is configured, the app loads voices from Supabase on startup, and Voice Studio saves to Supabase.
- Reference WAVs are downloaded and cached locally under `VOICE_CACHE_DIR` when needed for generation.

## API

### POST `/tts`

Request JSON:

```json
{
  "text": "Your marketing script goes here.",
  "voice": "default"
}
```

Response:
- `audio/mpeg` bytes (MP3)

Example:

```powershell
curl -X POST "http://localhost:8965/tts" -H "Content-Type: application/json" -d "{\"text\":\"Hello! This is a demo.\",\"voice\":\"default\"}" --output out.mp3
```

### GET `/voices`

Returns the voice registry with:
- `specialty`
- `use_case`
- `notes`

## Voices

Chatterbox TTS provides a high-quality base voice, and supports **voice cloning** when you provide a short reference clip.

In this project, “voices” are defined in `voices/voices.json` as a **registry of reference clips** + metadata. This lets you build a curated set of brand/character voices for marketing.

Each voice can optionally point to a clean reference WAV file (6–15 seconds recommended) to maximize realism/consistency.

Example entry:

```json
{
  "my_brand_voice": {
    "display_name": "My Brand Voice",
    "reference_wav": "voices/my_brand_voice.wav",
    "specialty": "Warm, confident marketing narration",
    "use_case": "Explainer videos, product launch promos, ads",
    "notes": "Use a dry studio recording; avoid music/echo."
  }
}
```

### Recommended built-in voices to create (marketing-ready)

This repo ships with a single `default` voice entry (no reference clip) so it runs out of the box.

For **human-realistic** marketing voiceovers, add 3–6 reference voices like:

- **brand_warm_friendly**
  - specialty: warm, approachable narration
  - use case: explainer videos, onboarding, social ads
- **brand_confident_authority**
  - specialty: confident, premium delivery
  - use case: product launches, cinematic promos
- **brand_fast_energetic**
  - specialty: upbeat pacing for short-form
  - use case: TikTok/Reels, performance ads
- **brand_calm_trustworthy**
  - specialty: calm, trustworthy tone
  - use case: testimonials, compliance-heavy messaging

## Quality Notes (important)

- Best results come from:
  - clean input text with punctuation
  - shorter sentences
  - providing a good reference clip per voice
- This server deliberately generates **per-chunk** and stitches with punctuation-aware pauses to avoid unnatural “single-breath” output.
- CPU-only inference is enforced (`device=cpu`). Latency may be higher, but output quality is prioritized.

## License

This repository is an integration scaffold. Model licensing and terms are governed by the upstream Chatterbox project and the `chatterbox-tts` package.
