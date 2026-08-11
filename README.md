# TTS-DAI (FastAPI + Chatterbox TTS, CPU-only)

Production-style Text-to-Speech API for marketing voiceovers using **Chatterbox TTS** with **CPU-only** inference.

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
- Speaker and emotion information is persisted in Supabase.

### Emotion-Based Voice Generation

- Select a saved speaker before generating speech.
- Select an emotion associated with that speaker.
- Use the corresponding emotion reference audio during Chatterbox TTS generation.
- Supports multiple emotions per speaker, such as:
  - `neutral`
  - `happy`
  - `sad`
  - `angry`
  - and other custom emotions stored in Supabase.

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

- Generated audio is uploaded to Supabase Storage.
- Generated audio can be played directly inside the browser.
- Users can download generated audio as an MP3 file.
- Each generation receives a unique generation ID.

### Generation History

- Generation records are stored in the Supabase `tts_generations` table.
- Stored information includes:
  - Speaker
  - Emotion
  - Input text
  - Language
  - Speaking speed
  - Generated audio path
  - Generation timestamp

### Supabase Persistence

The application uses Supabase for persistent storage of:

- Speaker profiles
- Speaker emotion reference files
- Generated audio
- Generation history

The project uses the following Supabase database tables:
speakers
speaker_emotions
tts_generations

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
uvicorn main:app --host 127.0.0.1 --port 8965
```

## Run with Docker (recommended)

## Docker Compose

Build and start the application using Docker Compose:

</> powershell
docker compose up --build
Docker Compose uses the project's Docker configuration to build and run the TTS-DAI application.

## Docker

To build the Docker image manually:
docker build -t tts-dai .

Run the container:
docker run --rm -p 8965:8965 --env-file .env tts-dai

## Web UI

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

---

## Supabase Storage

The application uses two Supabase Storage buckets.

### 1. `tts-speakers`

This bucket stores the reference audio files associated with speaker profiles.

Recommended configuration:

- Bucket name: `tts-speakers`
- Public: Yes

Reference audio files are organized by speaker and emotion.

### 2. 'tts-generations'

This bucket stores generated MP3 audio files.

Recommended configuration:

Bucket name: tts-generations
Public: Yes

Generated files are stored using a unique generation ID.

The application generates a unique UUID for every generated audio file.

Example storage path:

generations/550e8400-e29b-41d4-a716-446655440000.mp3

The public URL returned by Supabase is used by the web interface to:

Play the generated audio
Download the generated audio

### Supabase Database:

TTS-DAI uses three PostgreSQL tables in Supabase:

speakers
speaker_emotions
tts_generations

## 1. speakers Table

The speakers table stores the main information about each speaker profile.

create table if not exists public.speakers (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    description text default '',
    created_at timestamptz default now()
);

## 2. speaker_emotions Table

The speaker_emotions table stores the emotion-specific reference audio associated with each speaker.

create table if not exists public.speaker_emotions (
    id uuid primary key default gen_random_uuid(),

    speaker_id uuid not null references public.speakers(id) on delete cascade,

    emotion text not null,

    storage_path text,
    public_url text,

    created_at timestamptz default now(),

    constraint unique_speaker_emotion unique (speaker_id, emotion)
);
## 3. tts_generations Table

The tts_generations table stores information about every generated audio file.

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

---

## TTS Generation API

### POST `/ui/tts/generate`

Generates speech using the selected speaker and emotion reference audio.

The endpoint accepts `multipart/form-data`.

#### Request Parameters

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

### Response

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

## API Summary
Method	Endpoint	Purpose
POST	/ui/tts/generate	Generate speech
POST	/ui/tts/translate	Translate text
GET	/ui	Dashboard
GET	/ui/speakers	Speaker management UI
GET	/ui/tts	TTS Studio
GET	/ui/history	Generation history

## Quality Notes (important)

- Best results come from:
  - clean input text with punctuation
  - shorter sentences
  - providing a good reference clip per voice
- This server deliberately generates **per-chunk** and stitches with punctuation-aware pauses to avoid unnatural “single-breath” output.
- CPU-only inference is enforced (`device=cpu`). Latency may be higher, but output quality is prioritized.

## License

This repository is an integration scaffold. Model licensing and terms are governed by the upstream Chatterbox project and the `chatterbox-tts` package.
