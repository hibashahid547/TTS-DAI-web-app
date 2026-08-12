# TTS-DAI (FastAPI + Chatterbox TTS)

Production-style Text-to-Speech API for marketing voiceovers using **Chatterbox TTS**. Speakers, emotion reference audio, generated MP3s, and history are persisted through a **PostgreSQL Data API** (PostgREST) and an **object Store API**.

## Features

### Speaker Profile Management

- Create speaker profiles with:
  - Speaker name
  - Description
  - Emotion-specific reference audio
- Upload multiple reference audio files for a single speaker.
- Each uploaded audio file is associated with a specific emotion.
- View all saved speakers through the Speaker Studio.
- View the emotions available for each speaker.
- Speaker and emotion information is persisted via the Data API.

### Emotion-Based Voice Generation

- Select a saved speaker before generating speech.
- Select an emotion associated with that speaker.
- Use the corresponding emotion reference audio during Chatterbox TTS generation.
- Supports multiple emotions per speaker, such as:
  - `neutral`
  - `happy`
  - `sad`
  - `angry`
  - and other custom emotions stored in the database / object store.

### Multilingual Text-to-Speech

- Supports multiple languages through the language selector.
- Available languages include:
  - English
  - Arabic
  - Danish
  - German
  - Greek
  - Spanish
  - Finnish
  - French
  - Hebrew
  - Hindi
  - Italian
  - Japanese
  - Korean
  - Malay
  - Dutch
  - Norwegian
  - Polish
  - Portuguese
  - Russian
  - Swedish
  - Swahili
  - Turkish
  - Chinese

### Translation

- Users can optionally translate their text before generating speech.
- Translation is triggered from the TTS Studio UI.
- The translated text is displayed in an editable text box.
- Users can modify the translated text before generating audio.
- Translation is performed through the `/ui/tts/translate` endpoint.
- The translated text is sent directly to the TTS generation process, preventing duplicate translation.

### Speech Generation

- Generate speech using Chatterbox TTS.
- Supports speaker and emotion selection.
- Supports configurable speaking speed.
- Text is processed in chunks for improved speech pacing.
- Sentence, clause, and default pauses can be configured.
- Generated audio is converted to MP3.
- MP3 bitrate can be configured.

### Audio Playback and Download

- Generated audio is uploaded to object storage (`tts-generations` by default).
- Generated audio can be played directly inside the browser.
- Users can download generated audio as an MP3 file.
- Each generation receives a unique generation ID.

### Generation History

- Generation records are stored in the `tts_generations` table.
- Stored information includes:
  - Speaker
  - Emotion
  - Input text
  - Language
  - Speaking speed
  - Generated audio path
  - Generation timestamp

---

## Prerequisites

<<<<<<< HEAD
- Python 3.12+
- [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) on your `PATH` (required by `pydub`)
- PostgreSQL Data API URL + API key
- Object Store API URL + API key
- Storage buckets already created (defaults: `tts-speakers`, `tts-generations`, both public)
=======
- Speaker profiles
- Speaker emotion reference files
- Generated audio
- Generation history

The project uses the following Supabase database tables:
speakers
speaker_emotions
tts_generations
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

### Install ffmpeg (Windows)

- Download: https://www.gyan.dev/ffmpeg/builds/
- Add the `bin/` folder to your `PATH`
- Verify:

```powershell
ffmpeg -version
```

---

## Local setup

### 1. Clone and create a virtualenv

```powershell
cd E:\Projects\CB-TTS-DAI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

Then install PyTorch:

**GPU (CUDA 12.4 wheels):**

```powershell
pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
```

**CPU only:**

```powershell
pip install torch==2.6.0 torchaudio==2.6.0
```

Confirm CUDA (GPU hosts):

```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

### 3. Configure environment

```powershell
copy .env.example .env
```

Edit `.env` and set at least:

| Variable | Purpose |
|---|---|
| `DATA_API_URL` | PostgREST base URL (ends with `/rest/` or `/rest`) |
| `DATA_API_KEY` | Data API key |
| `STORE_API_URL` | Store buckets root (ends with `/storage-api/buckets/`) |
| `STORE_API_KEY` | Store API key |
| `SPEAKERS_BUCKET` | Default `tts-speakers` |
| `GENERATIONS_BUCKET` | Default `tts-generations` |
| `TTS_DEVICE` | `cpu` or `cuda` (also accepts `gpu`) |
| `PORT` | Server port (default `8965`) |

`DATABASE_URL` is **only** needed if you apply schema migrations with `scripts/migrate.py`. The running app uses `DATA_API_*` and `STORE_API_*` only.

### 4. Create the database schema

The Data API cannot run `CREATE TABLE`. Apply the SQL once against Postgres.

**Option A — SQL editor / query console** (recommended if you do not have a direct DB URL):

1. Open your Postgres / Jarvis SQL editor.
2. Paste and run [`migrations/001_init.sql`](migrations/001_init.sql).
3. If the Data API still returns `PGRST205` (table not in schema cache), run grants + reload:

```sql
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT rolname
    FROM pg_roles
    WHERE rolcanlogin
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', r.rolname);
    EXECUTE format(
      'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I',
      r.rolname
    );
  END LOOP;
END $$;

NOTIFY pgrst, 'reload schema';
```

Also use any **Reload schema / Reload PostgREST** control in your hosting UI if available.

**Option B — migrate script** (needs a direct Postgres URL):

```powershell
# in .env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME

python scripts\migrate.py
```

Dry-run (print SQL only):

```powershell
python scripts\migrate.py --dry-run
```

### 5. Run the app

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn main:app --host 127.0.0.1 --port 8965
```

First startup downloads Chatterbox model weights (can take several minutes).

<<<<<<< HEAD
### 6. Open the UI

| Page | URL |
|---|---|
| Dashboard | http://127.0.0.1:8965/ui |
| Speaker Studio | http://127.0.0.1:8965/ui/speakers |
| TTS Studio | http://127.0.0.1:8965/ui/tts |
| History | http://127.0.0.1:8965/ui/history |
| Swagger | http://127.0.0.1:8965/docs |
| OpenAPI | http://127.0.0.1:8965/openapi.json |

## GPU notes

Set in `.env`:

```env
TTS_DEVICE=cuda
```

The app maps `cuda` / `gpu` to CUDA. If `torch.cuda.is_available()` is false (CPU-only PyTorch build, missing drivers, etc.), it logs a warning and falls back to CPU.

## Run with Docker (GPU)

### Prerequisites (GPU PC)

1. NVIDIA GPU driver installed
2. [Docker](https://docs.docker.com/get-docker/) with NVIDIA GPU support:
   - **Linux:** [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
   - **Windows:** Docker Desktop + WSL2 + NVIDIA GPU support enabled
3. Verify GPU is visible to Docker:

```powershell
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### Quick start

```powershell
git clone <repo-url>
cd CB-TTS-DAI
copy .env.example .env
# Edit .env: set DATA_API_URL, DATA_API_KEY, STORE_API_URL, STORE_API_KEY
# Ensure TTS_DEVICE=cuda (default in .env.example)

=======
## Docker Compose

Build and start the application using Docker Compose:

</> powershell
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc
docker compose up --build
Docker Compose uses the project's Docker configuration to build and run the TTS-DAI application.

<<<<<<< HEAD
First start downloads Chatterbox model weights into the `tts_model_cache` volume (can take several minutes). Later starts reuse the cache.

Open:

- UI: http://localhost:8965/ui
- Swagger: http://localhost:8965/docs

### What Compose configures

- Builds an image with **ffmpeg** and **CUDA PyTorch 2.6 (cu124)**
- Passes `gpus: all` so the container can use the host GPU
- Loads `.env`
- Mounts `./voices` for local audio cache
- Persists HF/torch model downloads in volume `tts_model_cache`

### Docker without Compose

```powershell
docker build -t tts-dai .
docker run --rm --gpus all -p 8965:8965 `
  -v tts_model_cache:/cache `
  -v ${PWD}/voices:/app/voices `
  --env-file .env `
  tts-dai
```

### CPU-only Docker (no GPU)
=======
## Docker

To build the Docker image manually:
docker build -t tts-dai .

Run the container:
docker run --rm -p 8965:8965 --env-file .env tts-dai
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

Set in `.env`:

<<<<<<< HEAD
```env
TTS_DEVICE=cpu
```

And remove or comment `gpus: all` in `docker-compose.yml` (or override with a local compose file). The image still includes CUDA torch; it will run on CPU if CUDA is unavailable.
=======
## Web UI

TTS-DAI includes a server-rendered web interface built with **Jinja2** and **Tailwind CSS**.

### Dashboard

**URL:** http://localhost:8965/ui

The dashboard provides access to the main TTS-DAI features.

### Speaker Studio

**URL:** http://localhost:8965/ui/speakers

Speaker Studio is used to manage speaker profiles.

Features include:

- Create speaker profiles
- Add speaker name and description
- Upload multiple emotion-specific reference audio files
- Associate each audio file with an emotion
- View saved speaker profiles
- View available emotions for each speaker
- Store speaker and emotion information in Supabase

Speaker reference audio is stored in the Supabase `tts_speakers` Storage bucket.

### TTS Studio

**URL:** http://localhost:8965/ui/tts

TTS Studio is the main speech-generation interface.

Features include:

- Enter text for speech generation
- Select a target language
- Translate text before generation
- Edit translated text
- Select a speaker
- Select an emotion
- Adjust speaking speed
- Configure speech pacing
- Generate MP3 audio
- Play generated audio in the browser
- Download generated audio

Generated audio is stored in the Supabase `tts_generations` Storage bucket.

### Generation History

**URL:** http://localhost:8965/ui/history

The Generation History page displays previously generated speech and information stored in the `tts_generations` database table.

It provides access to:

- Speaker
- Emotion
- Input text
- Language
- Speaking speed
- Generated audio
- Generation timestamp

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
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

---

## Persistence (Data API + Store API)

The application uses:

- **Data API** for speaker profiles, emotion metadata, and generation history
- **Store API** for emotion reference WAVs and generated MP3s

Tables:

```text
speakers
speaker_emotions
tts_generations
```

Buckets:

```text
tts-speakers
tts-generations
```

### Storage: `tts-speakers`

Stores reference audio files associated with speaker profiles.

Recommended configuration:

- Bucket name: `tts-speakers`
- Public: Yes

<<<<<<< HEAD
Example layout:

```text
tts-speakers/
│
├── Sarah/
│   ├── Sarah_neutral.wav
│   ├── Sarah_happy.wav
│   ├── Sarah_sad.wav
│   └── Sarah_angry.wav
```
=======
Reference audio files are organized by speaker and emotion.

### 2. 'tts-generations'
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

### Storage: `tts-generations`

Stores generated MP3 audio files.

Recommended configuration:

- Bucket name: `tts-generations`
- Public: Yes

<<<<<<< HEAD
Example:

```text
tts-generations/
│
└── generations/
    ├── <generation-uuid>.mp3
    └── <generation-uuid>.mp3
```
=======
The application generates a unique UUID for every generated audio file.
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

Example path:

```text
generations/550e8400-e29b-41d4-a716-446655440000.mp3
```

The public object URL is used by the web UI to play and download generated audio.

<<<<<<< HEAD
### Database relationships

```text
speakers
   │
   │ 1
   │
   └───────────────< speaker_emotions
                         │
                         │ 1
                         │
                         └───────────────< tts_generations
```

### 1. Speakers table
=======
Play the generated audio
Download the generated audio

### Supabase Database:

TTS-DAI uses three PostgreSQL tables in Supabase:

speakers
speaker_emotions
tts_generations

## 1. speakers Table
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

Stores the main information about each speaker profile.

```sql
create table if not exists public.speakers (
    id uuid primary key default gen_random_uuid(),
<<<<<<< HEAD
    name text not null,
    description text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
=======
    name text not null unique,
    description text default '',
    created_at timestamptz default now()
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc
);
```

<<<<<<< HEAD
### 2. Speaker emotions table
=======
## 2. speaker_emotions Table
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

Stores emotion-specific reference audio associated with each speaker.

```sql
create table if not exists public.speaker_emotions (
    id uuid primary key default gen_random_uuid(),
<<<<<<< HEAD
    speaker_id uuid not null
        references public.speakers(id)
        on delete cascade,
    emotion text not null,
    storage_path text not null,
    public_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (speaker_id, emotion)
);
```

### 3. TTS generations table
=======

    speaker_id uuid not null references public.speakers(id) on delete cascade,

    emotion text not null,

    storage_path text,
    public_url text,

    created_at timestamptz default now(),

    constraint unique_speaker_emotion unique (speaker_id, emotion)
);
## 3. tts_generations Table
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

Stores information about every generated audio file.

<<<<<<< HEAD
```sql
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
```

The canonical schema used by the app is in [`migrations/001_init.sql`](migrations/001_init.sql).
=======
CREATE TABLE tts_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    speaker_id UUID NOT NULL
        REFERENCES speakers(id)
        ON DELETE CASCADE,

    emotion_id UUID NOT NULL
        REFERENCES speaker_emotions(id)
        ON DELETE CASCADE,

    input_text TEXT NOT NULL,

    language VARCHAR(50),

    speed DECIMAL(3,2) DEFAULT 1.00,

    output_audio_path TEXT NOT NULL,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
### 3) Environment Variables

TTS-DAI uses environment variables for server configuration and Supabase access.

Create a `.env` file in the project root:

env
# Server
PORT=8965

# TTS Device
TTS_DEVICE=cpu

# Logging
LOG_LEVEL=INFO

# Hugging Face
HF_HUB_DISABLE_PROGRESS_BARS=0

# Supabase
SUPABASE_URL=your_supabase_project_url
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key

# Database Tables
SUPABASE_SPEAKERS_TABLE=speakers
SUPABASE_SPEAKER_EMOTIONS_TABLE=speaker_emotions
SUPABASE_GENERATIONS_TABLE=tts_generations

# Storage Buckets
SUPABASE_SPEAKERS_BUCKET=tts_speakers
SUPABASE_GENERATIONS_BUCKET=tts_generations

# Local Cache
VOICE_CACHE_DIR=voices/cache

# API

TTS-DAI provides REST API endpoints for:

- Text-to-speech generation
- Text translation
- Speaker profile management
- Emotion reference audio management
- Generated audio retrieval
- Server-rendered TTS Studio interface
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

---

## How speakers and emotions work

TTS-DAI uses speaker profiles instead of a local `voices.json` registry.

A speaker represents a complete voice profile and can contain multiple emotion-specific reference audio files.

Example:

<<<<<<< HEAD
```text
Sarah
│
├── neutral.wav
├── happy.wav
├── sad.wav
└── angry.wav
```

Speaker information is stored in the `speakers` table.

Emotion-specific reference audio metadata is stored in `speaker_emotions`.

### Speaker data

```text
Speaker
├── id
├── name
├── description
├── created_at
└── updated_at
```

Example:

```json
{
  "id": "7f4c...",
  "name": "Sarah",
  "description": "Professional female marketing voice"
}
```

### Emotion-based reference audio

Each speaker can have multiple emotion reference audio files.

Example emotion record:

```json
{
  "id": "9a12...",
  "speaker_id": "7f4c...",
  "emotion": "happy",
  "storage_path": "Sarah/Sarah_happy.wav",
  "public_url": "https://..."
}
```

### Speaker and emotion selection

The TTS Studio dynamically loads available speakers from the database.

When a speaker is selected:

1. The frontend identifies the selected speaker.
2. The available emotions for that speaker are loaded.
3. The emotion dropdown is populated.
4. The selected speaker and emotion are sent to the generation API.

Example:

```text
Speaker: Sarah
Available Emotions: [neutral] [happy] [sad] [angry]
```

When generating with `Speaker: Sarah` and `Emotion: happy`, the backend downloads that emotion’s reference WAV (cached under `VOICE_CACHE_DIR`) and uses it as the Chatterbox audio prompt.

---

## How translation works

When translation is enabled in the TTS Studio:

```text
Original Text
      │
      ▼
POST /ui/tts/translate
      │
      ▼
Translated Text
      │
      ▼
User edits translation (optional)
      │
      ▼
POST /ui/tts/generate
      │
      ▼
Chatterbox TTS
      │
      ▼
Generated MP3
```

The backend does **not** translate again during generation. The edited translated text from the UI is sent directly to `/ui/tts/generate`.

### Translation API

`POST /ui/tts/translate`

Accepts `multipart/form-data`.

PowerShell example:

```powershell
$form = @{
    text = "Hello, welcome to our company."
    language = "French"
}

Invoke-RestMethod `
    -Uri "http://localhost:8965/ui/tts/translate" `
    -Method Post `
    -Form $form
```

Response:

```json
{
  "translated_text": "Bonjour, bienvenue dans notre entreprise."
}
```

---

## How TTS generation works

### Generation flow

```text
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
       ├── Find emotion
       ├── Retrieve reference audio from Store API
       ▼
Chatterbox TTS
       │
       ▼
Generated Audio
       │
       ├──────────────► Store API (tts-generations)
       │
       └──────────────► Data API (tts_generations)
       │
       ▼
public_url
       ├── Audio Player
       └── Download
```

### TTS Generation API

`POST /ui/tts/generate`

Accepts `multipart/form-data`.
=======
#### Request Parameters
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

| Parameter | Type | Required | Default | Description |
|---|---|---:|---|---|
| `text` | string | Yes | — | Text to convert into speech |
| `speaker` | string | Yes | — | Name of the speaker profile |
| `emotion` | string | Yes | — | Emotion / reference audio to use |
| `speed` | float | No | `1.0` | Speaking speed |
| `language` | string | No | `""` | Target language display name |
| `chunk_max_chars` | int | No | `220` | Maximum characters per TTS chunk |
| `pause_sentence_ms` | int | No | `420` | Pause after sentences |
| `pause_clause_ms` | int | No | `220` | Pause after clauses |
| `pause_default_ms` | int | No | `160` | Default pause duration |
| `mp3_bitrate` | string | No | `192k` | MP3 output bitrate |
| `filename` | string | No | `voiceover.mp3` | Output filename |

PowerShell example:

powershell
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
```

<<<<<<< HEAD
Example response:
=======
### Response

A successful request returns a JSON response similar to:
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

```json
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
  "public_url": "https://.../storage-api/buckets/tts-generations/objects/generations/..."
}
```

---

## Supported languages

<<<<<<< HEAD
The TTS Studio language selector includes:
=======
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

### Response
{
    "translated_text": "Bonjour, bienvenue dans notre entreprise."
}

The translated text is displayed in the TTS Studio where the user can edit it before generating speech.



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
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

```text
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
```

Selected display names are mapped to language codes by the backend using `SUPPORTED_LANGUAGES`.

Example:

<<<<<<< HEAD
```text
English → en
French  → fr
Chinese → zh
```

The resulting language code is passed to Chatterbox multilingual TTS.

---

## Speed control

The TTS Studio provides a speaking-speed slider.

- Default: `1.0x`
- Range: `0.5x` → `2.0x`
- Typical step: `0.25x`

The selected speed is sent to `POST /ui/tts/generate`. The backend also scales configured pause durations with speed (faster speech → shorter pauses).

---

## Audio output

Generated audio is exported as MP3.

- Default bitrate: `192k`
- Uploaded to: `tts-generations`
- Returned fields include `storage_path` and `public_url`

---

## Web UI routes

| Route | Purpose |
|---|---|
| `GET /ui` | Dashboard |
| `GET /ui/speakers` | Create speakers, upload emotion reference audio, manage profiles |
| `GET /ui/tts` | Script editor, language/translate, speaker/emotion, speed, generate/play/download |
| `GET /ui/history` | Previously generated audio and metadata |

---
=======
{
    "filename": "voiceover.mp3",
    "storage_path": "generations/<uuid>.mp3",
    "public_url": "https://..."
}

## API Summary
Method	Endpoint	Purpose
POST	/ui/tts/generate	Generate speech
POST	/ui/tts/translate	Translate text
GET	/ui	Dashboard
GET	/ui/speakers	Speaker management UI
GET	/ui/tts	TTS Studio
GET	/ui/history	Generation history
>>>>>>> 2380e97d5d0f05f892abe4318c67e942e2126fcc

## API summary

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/ui/tts/generate` | Generate speech |
| `POST` | `/ui/tts/translate` | Translate text |
| `GET` | `/ui` | Dashboard |
| `GET` | `/ui/speakers` | Speaker management UI |
| `POST` | `/ui/speakers/upload` | Upload speaker emotion audio |
| `POST` | `/ui/speakers/delete` | Delete a speaker |
| `GET` | `/ui/tts` | TTS Studio |
| `GET` | `/ui/history` | Generation history |
| `GET` | `/api/generations` | Generations JSON |
| `GET` | `/speakers` | Speakers / emotions JSON |

---

## Project layout

```text
main.py                 # FastAPI app + TTS
persistence.py          # Data API + Store API clients
migrations/001_init.sql # Postgres schema
scripts/migrate.py      # Optional schema applicator
templates/              # Jinja UI
requirements.txt
.env.example
```

---

## Quality notes

- Best results come from:
  - clean input text with punctuation
  - shorter sentences
  - a good reference clip per emotion
- This server generates **per-chunk** and stitches with punctuation-aware pauses to avoid unnatural “single-breath” output.
- With `TTS_DEVICE=cpu`, latency may be higher; quality is still prioritized. Use `TTS_DEVICE=cuda` with a CUDA PyTorch build for GPU acceleration.

## License

This repository is an integration scaffold. Model licensing and terms are governed by the upstream Chatterbox project and the `chatterbox-tts` package.
