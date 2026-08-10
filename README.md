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

# Supabase Configuration

TTS-DAI uses Supabase for persistent storage of speaker profiles, emotion-specific reference audio, and generated audio history.

Supabase is used for:

- Speaker profile management
- Emotion reference audio management
- Generated audio storage
- Generation history
- Persistent data across deployments

---

## Supabase Storage

The application uses two Supabase Storage buckets.

### 1. `tts-speakers`

This bucket stores the reference audio files associated with speaker profiles.

Recommended configuration:

- Bucket name: `tts-speakers`
- Public: Yes

Reference audio files are organized by speaker and emotion.

Example:

```text
tts-speakers/
│
├── speaker-id/
│   ├── neutral.wav
│   ├── happy.wav
│   ├── sad.wav
│   └── angry.wav

## 1.tts-generations

This bucket stores generated MP3 audio files.

Recommended configuration:

Bucket name: tts-generations
Public: Yes

Generated files are stored using a unique generation ID.

Example:

tts-generations/
│
└── generations/
    ├── <generation-uuid>.mp3
    ├── <generation-uuid>.mp3
    └── <generation-uuid>.mp3
The application generates a unique UUID for every generated audio file.

Example storage path:

generations/550e8400-e29b-41d4-a716-446655440000.mp3

The public URL returned by Supabase is used by the web interface to:

Play the generated audio
Download the generated audio

## Supabase Database

TTS-DAI uses three PostgreSQL tables in Supabase:

speakers
speaker_emotions
tts_generations

The tables are related through the speaker and emotion IDs.

The overall relationship is:

speakers
   │
   │ 1
   │
   └───────────────< speaker_emotions
                         │
                         │ 1
                         │
                         └───────────────< tts_generations

## 1. Speakers Table

The speakers table stores the main information about each speaker profile.

create table if not exists public.speakers (
    id uuid primary key default gen_random_uuid(),

    name text not null,

    description text not null default '',

    created_at timestamptz not null default now(),

    updated_at timestamptz not null default now()
);

## 2. Speaker Emotions Table

The speaker_emotions table stores the emotion-specific reference audio associated with each speaker.

create table if not exists public.speaker_emotions (
    id uuid primary key default gen_random_uuid(),

    speaker_id uuid not null
        references public.speakers(id)
        on delete cascade,

    emotion text not null,

    audio_path text not null,

    public_url text,

    created_at timestamptz not null default now(),

    updated_at timestamptz not null default now()
);

## 3. TTS Generations Table

The tts_generations table stores information about every generated audio file.

create table if not exists public.tts_generations (
    id uuid primary key default gen_random_uuid(),

    speaker_id uuid not null
        references public.speakers(id)
        on delete cascade,

    emotion_id uuid not null
        references public.speaker_emotions(id)
        on delete cascade,

    input_text text not null,

    language text not null default 'en',

    speed double precision not null default 1.0,

    output_audio_path text not null,

    created_at timestamptz not null default now()
);
### 3) Environment variables

Copy `.env.example` to `.env` and fill in:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Notes:

- Use the **Service Role key on the server only** (never in browser JS).
- When Supabase is configured, the app loads voices from Supabase on startup, and Voice Studio saves to Supabase.
- Reference WAVs are downloaded and cached locally under `VOICE_CACHE_DIR` when needed for generation.

# API

TTS-DAI provides REST API endpoints for:

- Text-to-speech generation
- Text translation
- Speaker profile management
- Emotion reference audio management
- Generated audio retrieval
- Server-rendered TTS Studio interface

---

## TTS Generation API

### POST `/ui/tts/generate`

Generates speech using the selected speaker and emotion reference audio.

The endpoint accepts `multipart/form-data`.

### Request Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---:|---|---|
| `text` | string | Yes | — | Text to convert into speech |
| `speaker` | string | Yes | — | Name of the speaker profile |
| `emotion` | string | Yes | — | Emotion/reference audio to use |
| `speed` | float | No | `1.0` | Speaking speed |
| `language` | string | No | `""` | Target language |
| `chunk_max_chars` | int | No | `220` | Maximum characters per TTS chunk |
| `pause_sentence_ms` | int | No | `420` | Pause after sentences |
| `pause_clause_ms` | int | No | `220` | Pause after clauses |
| `pause_default_ms` | int | No | `160` | Default pause duration |
| `mp3_bitrate` | string | No | `192k` | MP3 output bitrate |
| `filename` | string | No | `voiceover.mp3` | Output filename |

---

### Example Request

Using PowerShell:

```powershell
$form = @{
    text = "Welcome to our company. We provide innovative AI solutions."
    speaker = "Sarah"
    emotion = "happy"
    speed = "1.0"
    language = "English"
    chunk_max_chars = "220"
    pause_sentence_ms = "420"
    pause_clause_ms = "220"
    pause_default_ms = "160"
    mp3_bitrate = "192k"
    filename = "voiceover.mp3"
}

Invoke-RestMethod `
    -Uri "http://localhost:8965/ui/tts/generate" `
    -Method Post `
    -Form $form

## Response

A successful request returns a JSON response similar to:

{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "speaker": "Sarah",
    "emotion": "happy",
    "language": "en",
    "filename": "voiceover.mp3",
    "text": "Welcome to our company. We provide innovative AI solutions.",
    "config": {
        "speed": 1.0,
        "chunk_max_chars": 220,
        "pause_sentence_ms": 420,
        "pause_clause_ms": 220,
        "pause_default_ms": 160,
        "mp3_bitrate": "192k",
        "language": "en"
    },
    "storage_path": "generations/550e8400-e29b-41d4-a716-446655440000.mp3",
    "public_url": "https://your-project.supabase.co/storage/v1/object/public/tts-generations/generations/..."
}
The returned public_url is used by the TTS Studio to:

Play the generated audio
Download the generated audio
Access the generated MP3 from Supabase Storage

## Translation API
POST /ui/tts/translate

Translates text into the selected target language.

The endpoint accepts multipart/form-data.
$form = @{
    text = "Hello, welcome to our company."
    language = "French"
}

Invoke-RestMethod `
    -Uri "http://localhost:8965/ui/tts/translate" `
    -Method Post `
    -Form $form

## Response
{
    "translated_text": "Bonjour, bienvenue dans notre entreprise."
}

The translated text is displayed in the TTS Studio where the user can edit it before generating speech.

## Speaker Management

TTS-DAI uses speaker profiles instead of the previous voices.json voice registry.

A speaker represents a complete voice profile and can contain multiple emotion-specific reference audio files.

Example:

Sarah
│
├── neutral.wav
├── happy.wav
├── sad.wav
└── angry.wav

Speaker information is stored in the Supabase speakers table.

Emotion-specific reference audio information is stored in the speaker_emotions table.

## Speaker Data

A speaker contains:

Speaker
├── id
├── name
├── description
├── created_at
└── updated_at

Example:

{
    "id": "7f4c...",
    "name": "Sarah",
    "description": "Professional female marketing voice"
}
## Emotion-Based Reference Audio

Each speaker can have multiple emotion reference audio files.

For example:

Sarah
│
├── neutral
├── happy
├── sad
└── angry

Each emotion is associated with a reference audio file stored in the Supabase tts-speakers bucket.

The corresponding database record is stored in:

speaker_emotions

Example:

{
    "id": "9a12...",
    "speaker_id": "7f4c...",
    "emotion": "happy",
    "audio_path": "speaker-id/happy.wav",
    "public_url": "https://..."
}
## Speaker and Emotion Selection

The TTS Studio dynamically loads available speakers from the database.

When a speaker is selected:

The frontend identifies the selected speaker.
The available emotions for that speaker are loaded.
The emotion dropdown is populated.
Speaker information is displayed.
The selected speaker and emotion are sent to the generation API.

For example:

Speaker:
Sarah

Available Emotions:
[neutral] [happy] [sad] [angry]

When the user selects:

Speaker: Sarah
Emotion: Happy

## Generated Audio

Every successful TTS generation receives a unique UUID.

Example:

550e8400-e29b-41d4-a716-446655440000

The generated MP3 is uploaded to the Supabase Storage bucket:

tts-generations

with a storage path similar to:

generations/550e8400-e29b-41d4-a716-446655440000.mp3

The generation is also recorded in:

tts_generations

with information about:

Speaker
Emotion
Input text
Language
Speed
Generated audio path
Generation timestamp

## Generation Flow

The complete TTS generation process is:

User
 │
 ├── Text
 ├── Speaker
 ├── Emotion
 ├── Language
 └── Speed
       │
       ▼
TTS Studio
       │
       ▼
POST /ui/tts/generate
       │
       ▼
FastAPI Backend
       │
       ├── Find speaker
       │
       ├── Find emotion
       │
       ├── Retrieve reference audio
       │
       ▼
Chatterbox TTS
       │
       ▼
Generated Audio
       │
       ├──────────────► Supabase Storage
       │                tts-generations
       │
       └──────────────► Supabase Database
                        tts_generations
       │
       ▼
public_url
       │
       ├── Audio Player
       │
       └── Download

## Translation + TTS Flow

When translation is enabled:

Original Text
      │
      ▼
POST /ui/tts/translate
      │
      ▼
Translated Text
      │
      ▼
User edits translation
      │
      ▼
POST /ui/tts/generate
      │
      ▼
Chatterbox TTS
      │
      ▼
Generated MP3

The backend does not translate the text again after the frontend translation step.

The edited translated text is sent directly to the TTS generation endpoint.

## Supported Languages

The TTS Studio provides a language selector containing:

English
Arabic
Danish
German
Greek
Spanish
Finnish
French
Hebrew
Hindi
Italian
Japanese
Korean
Malay
Dutch
Norwegian
Polish
Portuguese
Russian
Swedish
Swahili
Turkish
Chinese

The selected language is mapped to its corresponding language code by the backend using:

SUPPORTED_LANGUAGES

For example:

English → en

The resulting language code is passed to the TTS generation service.

## Speed Control

The TTS Studio provides a speaking-speed slider.

Default:

1.0x

Available range:

0.5x → 2.0x

with increments of:

0.25x

The selected speed is sent to:

POST /ui/tts/generate

The backend also applies the selected speed to the configured pause durations.

## Audio Output

Generated audio is exported as MP3.

Default bitrate:

192k

The generated file is uploaded to:

tts-generations

and the API returns its public URL.

Example:

{
    "filename": "voiceover.mp3",
    "storage_path": "generations/<uuid>.mp3",
    "public_url": "https://..."
}
## Web UI Routes

TTS-DAI also provides server-rendered web pages.

## Dashboard
GET /ui

Main application dashboard.

## Speaker Studio
GET /ui/speakers

Used to:

Create speaker profiles
Add speaker information
Upload emotion reference audio
Manage speaker profiles

## TTS Studio
GET /ui/tts

Used to:

Enter text
Select language
Translate text
Edit translated text
Select speaker
Select emotion
Adjust speaking speed
Generate speech
Play generated audio
Download generated MP3

## Generation History
GET /ui/history

Displays previously generated audio and generation information stored in Supabase.

## API Summary
Method	Endpoint	Purpose
POST	/ui/tts/generate	Generate speech
POST	/ui/tts/translate	Translate text
GET	/ui	Dashboard
GET	/ui/speakers	Speaker management UI
GET	/ui/tts	TTS Studio
GET	/ui/history	Generation history
the backend retrieves the corresponding emotion reference audio and uses it during speech generation.



## Quality Notes (important)

- Best results come from:
  - clean input text with punctuation
  - shorter sentences
  - providing a good reference clip per voice
- This server deliberately generates **per-chunk** and stitches with punctuation-aware pauses to avoid unnatural “single-breath” output.
- CPU-only inference is enforced (`device=cpu`). Latency may be higher, but output quality is prioritized.

## License

This repository is an integration scaffold. Model licensing and terms are governed by the upstream Chatterbox project and the `chatterbox-tts` package.
