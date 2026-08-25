import io
import logging
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
import torchaudio
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pwdlib import PasswordHash
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from pydub import AudioSegment
from pydub.silence import detect_nonsilent
from pydub.effects import normalize
from deep_translator import GoogleTranslator
from fastapi.templating import Jinja2Templates

from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from dotenv import load_dotenv

from persistence import ApiError, DataApi, StoreApi

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("tts-dai")


def _configure_ffmpeg() -> None:
    """Ensure pydub can find ffmpeg/ffprobe even if the process PATH is stale."""
    ffmpeg = (
        os.getenv("FFMPEG_PATH", "").strip()
        or shutil.which("ffmpeg")
        or ""
    )
    ffprobe = (
        os.getenv("FFPROBE_PATH", "").strip()
        or shutil.which("ffprobe")
        or ""
    )

    # Fall back to common WinGet install location if PATH wasn't refreshed.
    if not ffmpeg or not ffprobe:
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if local.is_dir():
            for candidate in local.glob("Gyan.FFmpeg*/ffmpeg-*/bin"):
                cand_ffmpeg = candidate / "ffmpeg.exe"
                cand_ffprobe = candidate / "ffprobe.exe"
                if cand_ffmpeg.is_file() and cand_ffprobe.is_file():
                    ffmpeg = ffmpeg or str(cand_ffmpeg)
                    ffprobe = ffprobe or str(cand_ffprobe)
                    break

    if ffmpeg:
        bin_dir = str(Path(ffmpeg).resolve().parent)
        path_parts = os.environ.get("PATH", "").split(os.pathsep)
        if bin_dir not in path_parts:
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        AudioSegment.converter = ffmpeg
        logger.info("Using ffmpeg at %s", ffmpeg)
    else:
        logger.warning(
            "ffmpeg not found. Install it or set FFMPEG_PATH. Audio upload/export will fail."
        )

    if ffprobe:
        logger.info("Using ffprobe at %s", ffprobe)
    else:
        logger.warning(
            "ffprobe not found. Install it or set FFPROBE_PATH. Audio upload will fail."
        )


_configure_ffmpeg()


APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
VOICES_DIR = APP_DIR / "voices"
VOICE_CACHE_DIR = APP_DIR / os.getenv("VOICE_CACHE_DIR", "voices/cache")

DATA_API_URL = os.getenv("DATA_API_URL", "").strip()
DATA_API_KEY = os.getenv("DATA_API_KEY", "").strip()
STORE_API_URL = os.getenv("STORE_API_URL", "").strip()
STORE_API_KEY = os.getenv("STORE_API_KEY", "").strip()

SPEAKERS_TABLE = os.getenv("SPEAKERS_TABLE", "speakers")
SPEAKER_EMOTIONS_TABLE = os.getenv("SPEAKER_EMOTIONS_TABLE", "speaker_emotions")
GENERATIONS_TABLE = os.getenv("GENERATIONS_TABLE", "tts_generations")
SPEAKERS_BUCKET = os.getenv("SPEAKERS_BUCKET", "tts-speakers")
GENERATIONS_BUCKET = os.getenv("GENERATIONS_BUCKET", "tts-generations")


REF_AUDIO_MAX_SECONDS = float(os.getenv("REF_AUDIO_MAX_SECONDS", "300"))
PASSWORD_HASHER = PasswordHash.recommended()
USERS_TABLE = os.getenv("USERS_TABLE", "users")
MIN_PASSWORD_LENGTH = 8
TTS_DEVICE = os.getenv("TTS_DEVICE", "cpu").strip().lower()
SUPPORTED_LANGUAGES = {
    "English": "en",
    "Arabic": "ar",
    "Danish": "da",
    "German": "de",
    "Greek": "el",
    "Spanish": "es",
    "Finnish": "fi",
    "French": "fr",
    "Hebrew": "he",
    "Hindi": "hi",
    "Italian": "it",
    "Japanese": "ja",
    "Korean": "ko",
    "Malay": "ms",
    "Dutch": "nl",
    "Norwegian": "no",
    "Polish": "pl",
    "Portuguese": "pt",
    "Russian": "ru",
    "Swedish": "sv",
    "Swahili": "sw",
    "Turkish": "tr",
    "Chinese": "zh",
}
class TTSRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=50_000,
        description="Text to synthesize. For best realism, use punctuation and avoid extremely long paragraphs.",
    )

    speaker: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Speaker name",
    )

    emotion: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Emotion of the selected speaker",
    )
    speed: float = Field(
    1.0,
    ge=0.5,
    le=2.0,
    description="Speaking speed multiplier.",
    )
    chunk_max_chars: int = Field(
        220,
        ge=60,
        le=600,
        description="Max characters per synthesized chunk. Smaller chunks generally improve natural pauses.",
    )

    pause_sentence_ms: int = Field(
        420,
        ge=0,
        le=2000,
    )

    pause_clause_ms: int = Field(
        220,
        ge=0,
        le=2000,
    )

    pause_default_ms: int = Field(
        160,
        ge=0,
        le=2000,
    )

    mp3_bitrate: str = Field(
        "192k",
        pattern=r"^(128k|160k|192k|256k|320k)$",
        description="MP3 bitrate used when returning audio/mpeg.",
    )

app = FastAPI(
    title="TTS-DAI",
    version="1.0.0",
    description="CPU-only Text-to-Speech API using Chatterbox TTS. High-quality chunked generation with natural pauses.",
)
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")

if not SESSION_SECRET_KEY:
    raise RuntimeError(
        "SESSION_SECRET_KEY is not configured."
    )

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="tts_dai_session",
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
    https_only=False,
)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_MTL_MODEL: Optional[ChatterboxMultilingualTTS] = None

_SPEAKERS: List[Dict[str, Any]] = []

_SPEAKER_EMOTIONS: List[Dict[str, Any]] = []

_DATA_API: Optional[DataApi] = None
_STORE_API: Optional[StoreApi] = None


def _data_api_enabled() -> bool:
    return bool(DATA_API_URL and DATA_API_KEY)


def _store_api_enabled() -> bool:
    return bool(STORE_API_URL and STORE_API_KEY)


def _persistence_enabled() -> bool:
    return _data_api_enabled() and _store_api_enabled()


def _get_data_api() -> DataApi:
    if _DATA_API is None:
        raise HTTPException(
            status_code=500,
            detail="Data API client not initialized",
        )
    return _DATA_API


def _get_store_api() -> StoreApi:
    if _STORE_API is None:
        raise HTTPException(
            status_code=500,
            detail="Store API client not initialized",
        )
    return _STORE_API

def _get_user_by_login(login: str) -> Optional[Dict[str, Any]]:
    """Find a user by username or email."""
    login = login.strip()

    if not login:
        return None

    data_api = _get_data_api()

    # Try username first, case-insensitively.
    users = data_api.select(
        USERS_TABLE,
        filters={
            "username": f"ilike.{login}",
        },
        limit=1,
    )

    if users:
        return users[0]

    # Then try email, case-insensitively.
    users = data_api.select(
        USERS_TABLE,
        filters={
            "email": f"eq.{login.lower()}",
        },
        limit=1,
    )

    if users:
        return users[0]

    return None
def _get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Find a user by username, case-insensitively."""
    username = username.strip()

    if not username:
        return None

    users = _get_data_api().select(
        USERS_TABLE,
        filters={
            "username": f"ilike.{username}",
        },
        limit=1,
    )

    return users[0] if users else None


def _get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Find a user by email."""
    email = email.strip().lower()

    if not email:
        return None

    users = _get_data_api().select(
        USERS_TABLE,
        filters={
            "email": f"eq.{email}",
        },
        limit=1,
    )

    return users[0] if users else None

def _get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Return the currently logged-in user from the session."""
    user_id = request.session.get("user_id")

    if not user_id:
        return None

    users = _get_data_api().select(
        USERS_TABLE,
        filters={
            "id": f"eq.{user_id}",
        },
        limit=1,
    )

    return users[0] if users else None

def _require_login(request: Request) -> Dict[str, Any]:
    """Require an authenticated user."""
    user = _get_current_user(request)

    if user is None:
        raise HTTPException(
            status_code=303,
            headers={"Location": "/login"},
        )

    return user
# ==========================================================
# Speaker Helpers
# ==========================================================

def _load_speakers() -> List[Dict[str, Any]]:
    """Load all speakers from the Data API."""
    if not _data_api_enabled():
        return []

    try:
        return _get_data_api().select(
            SPEAKERS_TABLE,
            columns="*",
            order="name.asc",
        )
    except ApiError as e:
        logger.error("Failed to load speakers: %s %s", e, e.body)
        return []


def _load_speaker_emotions() -> List[Dict[str, Any]]:
    """Load all emotion audios."""
    if not _data_api_enabled():
        return []

    try:
        return _get_data_api().select(
            SPEAKER_EMOTIONS_TABLE,
            columns="*",
            order="emotion.asc",
        )
    except ApiError as e:
        logger.error("Failed to load speaker emotions: %s %s", e, e.body)
        return []


def _get_speaker(
    speaker_id: str,
    *,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get a speaker by ID.

    Visible speakers:
    - system speakers
    - speakers owned by the current user
    """

    for speaker in _SPEAKERS:
        if speaker["id"] != speaker_id:
            continue

        source = speaker.get("source", "system")
        owner_id = speaker.get("user_id")

        if source == "system":
            return speaker

        if source == "user" and user_id and owner_id == user_id:
            return speaker

        return None

    return None
    
def _get_speaker_id(
    speaker_name: str,
    *,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """
    Get a visible speaker UUID using speaker name.

    A user can select:
    - any system speaker
    - their own user-created speaker

    Speakers belonging to other users are ignored.
    """

    for speaker in _SPEAKERS:
        if speaker["name"].lower() != speaker_name.lower():
            continue

        source = speaker.get("source", "system")
        owner_id = speaker.get("user_id")

        if source == "system":
            return speaker["id"]

        if source == "user" and user_id and owner_id == user_id:
            return speaker["id"]

    return None

def _get_emotion(
    emotion_id: str,
    *,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get an emotion audio by ID if it is visible to the current user.

    Visible emotion audios:
    - system emotion audios
    - emotion audios owned by the current user
    """

    for emotion in _SPEAKER_EMOTIONS:
        if emotion["id"] != emotion_id:
            continue

        source = emotion.get("source", "system")
        owner_id = emotion.get("user_id")

        if source == "system":
            return emotion

        if source == "user" and user_id and owner_id == user_id:
            return emotion

        return None

    return None
def _get_emotion_by_speaker(
    speaker_id: str,
    emotion_name: str,
    *,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get an emotion audio for a speaker if it is visible to the current user.
    """

    for emotion in _SPEAKER_EMOTIONS:

        if (
            emotion["speaker_id"] != speaker_id
            or emotion["emotion"].lower() != emotion_name.lower()
        ):
            continue

        source = emotion.get("source", "system")
        owner_id = emotion.get("user_id")

        if source == "system":
            return emotion

        if source == "user" and user_id and owner_id == user_id:
            return emotion

        return None

    return None

def _is_visible_to_user(
    record: Dict[str, Any],
    *,
    user_id: str,
) -> bool:
    """
    Return True if a speaker/emotion record is visible to the user.

    System records are visible to everyone.
    User records are visible only to their owner.
    """

    source = record.get("source", "system")
    owner_id = record.get("user_id")

    if source == "system":
        return True

    return source == "user" and owner_id == user_id

def _get_visible_speakers(
    *,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Return system speakers + speakers owned by the current user."""

    return [
        speaker
        for speaker in _SPEAKERS
        if _is_visible_to_user(speaker, user_id=user_id)
    ]


def _get_visible_speaker_emotions(
    *,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Return system emotions + emotions owned by the current user."""

    return [
        emotion
        for emotion in _SPEAKER_EMOTIONS
        if _is_visible_to_user(emotion, user_id=user_id)
    ]

def _load_generations(
    limit: int = 50,
    *,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Load recent TTS generations for a specific user."""
    if not _data_api_enabled():
        return []

    db = _get_data_api()

    try:
        generations = db.select(
            GENERATIONS_TABLE,
            columns=(
                "id,created_at,input_text,translated_text,"
                "language,speed,reference_audio_path,"
                "output_audio_path,speaker_name,emotion"
            ),
            filters={
                "user_id": f"eq.{user_id}",
            },
            order="created_at.desc",
            limit=limit,
        )

    except ApiError as e:
        logger.error(
            "Failed to load generations: %s %s",
            e,
            e.body,
        )
        return []

    store = _STORE_API

    for g in generations:

        # ----------------------------------------
        # Speaker / emotion snapshot
        # ----------------------------------------

        g["speaker_name"] = (
            g.get("speaker_name")
            or "Unknown Speaker"
        )

        g["emotion"] = (
            g.get("emotion")
            or "Neutral"
        )

        # ----------------------------------------
        # Text
        # ----------------------------------------

        g["text"] = g.get("input_text") or ""

        g["translated_text"] = (
            g.get("translated_text")
            or ""
        )

        # ----------------------------------------
        # Generated output audio
        # ----------------------------------------

        output_path = g.get("output_audio_path")

        if output_path and store is not None:
            g["public_url"] = store.public_url(
                GENERATIONS_BUCKET,
                output_path,
            )
        else:
            g["public_url"] = ""

        # ----------------------------------------
        # Reference audio
        # ----------------------------------------
        reference_path = g.get("reference_audio_path")

        g["reference_audio_url"] = ""
        g["reference_audio_deleted"] = False

        if reference_path and store is not None:
            try:
                reference_url = store.public_url(
                    SPEAKERS_BUCKET,
                    reference_path,
                )

                if reference_url:
                    g["reference_audio_url"] = reference_url
                else:
                    g["reference_audio_deleted"] = True

            except Exception as e:
                logger.warning(
                    "Failed to generate reference audio URL "
                    "for path %r: %s",
                    reference_path,
                    e,
                )
                g["reference_audio_deleted"] = True

        elif not reference_path:
            # No reference audio was stored for this generation.
            g["reference_audio_deleted"] = True

        # ----------------------------------------
        # Date / time
        # ----------------------------------------

        created_at = g.get("created_at")

        if created_at:

            try:

                if isinstance(created_at, datetime):
                    dt = created_at

                else:
                    dt = datetime.fromisoformat(
                        str(created_at).replace(
                            "Z",
                            "+00:00",
                        )
                    )

                # Convert UTC to Pakistan Standard Time
                dt = dt.astimezone(
                    ZoneInfo("Asia/Karachi")
                )

                g["formatted_date"] = dt.strftime(
                    "%d %b %Y • %I:%M %p"
                )

            except Exception:

                logger.exception(
                    "Failed to format generation date: %r",
                    created_at,
                )

                g["formatted_date"] = str(
                    created_at
                )

        else:
            g["formatted_date"] = ""
    logger.info(
        "HISTORY GENERATION: %s",
         generations,
    )
    return generations

def _upload_generated_mp3(*, mp3_bytes: bytes, storage_path: str) -> str:
    if not _store_api_enabled():
        out_dir = (APP_DIR / "voices" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        local_path = out_dir / Path(storage_path).name
        local_path.write_bytes(mp3_bytes)
        return f"/ui/generated/{local_path.name}"

    store = _get_store_api()
    try:
        return store.upload(
            GENERATIONS_BUCKET,
            storage_path,
            mp3_bytes,
            content_type="audio/mpeg",
        )
    except ApiError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Store upload failed: {e} {e.body}",
        ) from e


@app.on_event("startup")
def _startup() -> None:
    global _MTL_MODEL, _DATA_API, _STORE_API, _SPEAKERS, _SPEAKER_EMOTIONS

    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if _data_api_enabled():
        _DATA_API = DataApi(DATA_API_URL, DATA_API_KEY)
    else:
        logger.warning("DATA_API_URL / DATA_API_KEY not set; DB features disabled")

    if _store_api_enabled():
        _STORE_API = StoreApi(STORE_API_URL, STORE_API_KEY)
    else:
        logger.warning("STORE_API_URL / STORE_API_KEY not set; storage upload disabled")

    _SPEAKERS = _load_speakers()
    _SPEAKER_EMOTIONS = _load_speaker_emotions()

    logger.info(
        "Loaded %d speakers and %d emotion audios.",
        len(_SPEAKERS),
        len(_SPEAKER_EMOTIONS),
    )

    # Select device
    device = TTS_DEVICE
    if device in {"gpu", "cuda"}:
        device = "cuda"

    if device not in {"cpu", "cuda"}:
        logger.warning(
            "Invalid TTS_DEVICE=%r. Falling back to cpu.",
            TTS_DEVICE,
        )
        device = "cpu"

    if device == "cuda" and not torch.cuda.is_available():
        logger.warning(
            "TTS_DEVICE=cuda but no CUDA GPU detected. Falling back to cpu."
        )
        device = "cpu"

    torch.set_num_threads(max(1, os.cpu_count() or 1))

    if os.getenv("HF_HUB_DISABLE_PROGRESS_BARS") is None:
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"

    logger.info(
        "Loading ChatterboxMultilingualTTS model (device=%s)...",
        device,
    )

    _MTL_MODEL = ChatterboxMultilingualTTS.from_pretrained(device=device)

    logger.info(
        "ChatterboxMultilingualTTS model loaded successfully (cuda_available=%s)",
        torch.cuda.is_available(),
    )

def _split_text_into_chunks(text: str, *, max_chars: int) -> List[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []

    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue

        if len(p) <= max_chars:
            chunks.append(p)
            continue

        sub_parts = re.split(r"(?<=[,;:])\s+", p)
        buf = ""
        for sp in sub_parts:
            sp = sp.strip()
            if not sp:
                continue
            candidate = f"{buf} {sp}".strip() if buf else sp
            if len(candidate) <= max_chars:
                buf = candidate
            else:
                if buf:
                    chunks.append(buf)
                buf = sp
        if buf:
            chunks.append(buf)

    final_chunks: List[str] = []
    for c in chunks:
        c = c.strip()
        if c:
            final_chunks.append(c)
    return final_chunks


def _pause_ms_for_chunk(
    chunk: str,
    *,
    pause_sentence_ms: int,
    pause_clause_ms: int,
    pause_default_ms: int,
) -> int:
    chunk = chunk.strip()
    if not chunk:
        return 0
    if chunk.endswith("..."):
        return max(pause_sentence_ms, 650)
    last = chunk[-1]
    if last in ".!?":
        return pause_sentence_ms
    if last in ",;:":
        return pause_clause_ms
    return pause_default_ms


def _silence(sr: int, ms: int) -> torch.Tensor:
    if ms <= 0:
        return torch.zeros(1, 0)
    n = int(sr * (ms / 1000.0))
    return torch.zeros(1, n)
def _apply_speed_to_pauses(
    speed: float,
    sentence_ms: int,
    clause_ms: int,
    default_ms: int,
):
    """
    Adjust pause durations according to the selected speed.

    speed > 1.0  -> shorter pauses (faster)
    speed < 1.0  -> longer pauses (slower)
    """

    speed = max(0.5, min(speed, 2.0))

    return (
        int(sentence_ms / speed),
        int(clause_ms / speed),
        int(default_ms / speed),
    )
def _generate_mp3_bytes(
    req: TTSRequest,
    language_id: str,
    user_id: str,
) -> bytes:
    """
    Generate MP3 audio using the selected speaker emotion
    as the reference voice and the selected language.
    """

    sentence_pause, clause_pause, default_pause = _apply_speed_to_pauses(
        req.speed,
        req.pause_sentence_ms,
        req.pause_clause_ms,
        req.pause_default_ms,
    )
    logger.info("DEBUG: _MTL_MODEL = %s", _MTL_MODEL)
    if _MTL_MODEL is None:
        raise HTTPException(
            status_code=500,
            detail="Multilingual TTS model not loaded",
        )

    speaker_id = _get_speaker_id(
        req.speaker,
        user_id=user_id,
    )

    if speaker_id is None:
        raise HTTPException(
            status_code=404,
            detail="Speaker not found",
        )

    emotion_info = _get_emotion_by_speaker(
        speaker_id,
        req.emotion,
        user_id=user_id,
    )

    if emotion_info is None:
        raise HTTPException(
            status_code=404,
            detail="Emotion audio not found",
        )

    ref_wav = _download_reference_audio(emotion_info)

    chunks = _split_text_into_chunks(
        req.text,
        max_chars=req.chunk_max_chars,
    )

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="Text is empty",
        )

    # Multilingual model sample rate
    sr = int(getattr(_MTL_MODEL, "sr", 24000))

    wavs: List[torch.Tensor] = []

    for i, chunk in enumerate(chunks):

        logger.info(
            "Generating chunk %s/%s | language=%s",
            i + 1,
            len(chunks),
            language_id,
        )

        wav = _MTL_MODEL.generate(
            chunk,
            language_id=language_id,
            audio_prompt_path=ref_wav,
        )
        
        if wav.dim() == 1:
            wav = wav.unsqueeze(0)

        wavs.append(wav)

        if i < len(chunks) - 1:

            pause = _silence(
                sr,
                _pause_ms_for_chunk(
                    chunk,
                    pause_sentence_ms=sentence_pause,
                    pause_clause_ms=clause_pause,
                    pause_default_ms=default_pause,
                ),
            )

            wavs.append(pause)

    final_audio = (
        torch.cat(wavs, dim=1)
        if len(wavs) > 1
        else wavs[0]
    )

    return _wav_tensor_to_mp3_bytes(
        final_audio,
        sr,
        bitrate=req.mp3_bitrate,
    )

def _download_reference_audio(emotion: Dict[str, Any]) -> str:
    """Download emotion reference audio from Store API (cached locally)."""
    storage_path = emotion.get("storage_path")

    if not storage_path:
        raise HTTPException(
            status_code=400,
            detail="Emotion has no reference audio.",
        )

    cache_file = (
        VOICE_CACHE_DIR / storage_path.replace("/", "_")
    ).resolve()

    if cache_file.exists():
        return str(cache_file)

    if not _store_api_enabled():
        raise HTTPException(
            status_code=500,
            detail="Store API is not configured",
        )

    try:
        audio_bytes = _get_store_api().download(SPEAKERS_BUCKET, storage_path)
    except ApiError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to download reference audio: {e} {e.body}",
        ) from e

    cache_file.write_bytes(audio_bytes)
    return str(cache_file)

def _wav_tensor_to_mp3_bytes(wav: torch.Tensor, sr: int, *, bitrate: str) -> bytes:
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)
    wav = wav.detach().cpu()
    wav = torch.clamp(wav, -1.0, 1.0)

    with tempfile.TemporaryDirectory() as td:
        wav_path = Path(td) / "out.wav"
        torchaudio.save(str(wav_path), wav, sr)
        seg = AudioSegment.from_wav(str(wav_path))
        buf = io.BytesIO()
        seg.export(buf, format="mp3", bitrate=bitrate)
        return buf.getvalue()


def _sanitize_voice_key(key: str) -> str:
    """Normalize a label into a safe object-storage path segment."""
    k = key.strip()
    if not k:
        raise HTTPException(status_code=400, detail="Voice name is required")

    # Keep readable names (spaces, etc.) as storage-safe keys.
    k = re.sub(r"\s+", "_", k)
    k = re.sub(r"[^a-zA-Z0-9_-]+", "_", k)
    k = re.sub(r"_+", "_", k).strip("_-")
    if not k:
        raise HTTPException(
            status_code=400,
            detail="Voice name must contain at least one letter or number",
        )
    return k[:64]


async def _upload_speaker_emotion(
    speaker_name: str,
    emotion: str,
    upload: UploadFile,
) -> Dict[str, str]:
    """
    Clean, validate, and upload an emotion reference audio
    to object storage.
    """

    data = await upload.read()

    if not data:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty",
        )

    # --------------------------------------------------
    # 1. Read uploaded audio
    # --------------------------------------------------

    try:
        seg = AudioSegment.from_file(io.BytesIO(data))

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid audio file: {e}",
        )

    # --------------------------------------------------
    # 2. Basic duration validation
    # --------------------------------------------------

    duration_seconds = len(seg) / 1000.0

    if duration_seconds < 1.0:
        raise HTTPException(
            status_code=400,
            detail="Audio is too short. Please upload at least 1 second of speech.",
        )

    if duration_seconds > REF_AUDIO_MAX_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Audio is too long ({duration_seconds:.1f}s). "
                f"Please keep the reference audio under {REF_AUDIO_MAX_SECONDS:.0f} seconds."
            ),
        )

    # --------------------------------------------------
    # 3. Convert to mono + 24 kHz
    # --------------------------------------------------

    seg = seg.set_channels(1)
    seg = seg.set_frame_rate(24000)

    # --------------------------------------------------
    # 4. Normalize volume
    # --------------------------------------------------

    seg = normalize(seg)

    # --------------------------------------------------
    # 5. Trim excessive silence
    # --------------------------------------------------

    # Detect non-silent regions.
    # Silence quieter than -40 dBFS is considered silence.
    nonsilent_ranges = detect_nonsilent(
        seg,
        min_silence_len=300,
        silence_thresh=-40,
    )

    if not nonsilent_ranges:
        raise HTTPException(
            status_code=400,
            detail="No speech detected in the uploaded audio.",
        )

    # First and last detected speech positions.
    speech_start = nonsilent_ranges[0][0]
    speech_end = nonsilent_ranges[-1][1]

    # Keep a small natural buffer around the speech.
    padding_ms = 100

    speech_start = max(0, speech_start - padding_ms)
    speech_end = min(len(seg), speech_end + padding_ms)

    seg = seg[speech_start:speech_end]

    # --------------------------------------------------
    # 6. Validate cleaned duration
    # --------------------------------------------------

    cleaned_duration = len(seg) / 1000.0

    if cleaned_duration < 1.0:
        raise HTTPException(
            status_code=400,
            detail="Not enough speech detected after removing silence.",
        )

    # --------------------------------------------------
    # 7. Export cleaned WAV
    # --------------------------------------------------

    wav_buffer = io.BytesIO()

    seg.export(
        wav_buffer,
        format="wav",
    )

    wav_bytes = wav_buffer.getvalue()

    # --------------------------------------------------
    # 8. Storage configuration
    # --------------------------------------------------

    if not _store_api_enabled():
        raise HTTPException(
            status_code=500,
            detail="Store API is not configured",
        )

    safe_speaker = _sanitize_voice_key(speaker_name)
    safe_emotion = _sanitize_voice_key(emotion)

    filename = f"{safe_speaker}_{safe_emotion}.wav"
    storage_path = f"{safe_speaker}/{filename}"

    # --------------------------------------------------
    # 9. Upload cleaned reference audio
    # --------------------------------------------------

    try:
        public_url = _get_store_api().upload(
            SPEAKERS_BUCKET,
            storage_path,
            wav_bytes,
            content_type="audio/wav",
        )
    except ApiError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Store upload failed: {e} {e.body}",
        ) from e

    logger.info(
        "Reference audio cleaned successfully | "
        "speaker=%s | emotion=%s | "
        "original=%.2fs | cleaned=%.2fs",
        speaker_name,
        emotion,
        duration_seconds,
        cleaned_duration,
    )

    return {
        "storage_path": storage_path,
        "public_url": str(public_url),
    }

async def _replace_speaker_emotion(
    emotion_info: Dict[str, Any],
    speaker_name: str,
    emotion: str,
    upload: UploadFile,
) -> Dict[str, str]:
    """
    Replace an existing speaker emotion reference audio.

    The new audio is cleaned and uploaded using the
    current speaker/emotion storage structure.
    """

    old_storage_path = emotion_info.get("storage_path")

    # Upload the new audio first.
    audio_info = await _upload_speaker_emotion(
        speaker_name=speaker_name,
        emotion=emotion,
        upload=upload,
    )

    new_storage_path = audio_info["storage_path"]

    # Only delete the old file if it is actually a DIFFERENT file.
    #
    # If old_storage_path == new_storage_path, the upload above
    # already replaced the old object. Removing it here would
    # delete the newly uploaded audio.
    if (
        old_storage_path
        and old_storage_path != new_storage_path
        and _store_api_enabled()
    ):
        try:
            _get_store_api().remove(
                SPEAKERS_BUCKET,
                [old_storage_path],
            )

        except Exception as e:
            logger.warning(
                "Could not remove old emotion audio '%s': %s",
                old_storage_path,
                e,
            )
    return audio_info

def _create_or_get_speaker(
    name: str,
    gender: str = "",
    description: str = "",
    *,
    user_id: str,
) -> Dict[str, Any]:
    """
    Get an existing visible speaker or create a new user-owned speaker.

    System speakers are available to everyone.
    User speakers are available only to their owner.
    """

    db = _get_data_api()

    name = name.strip()

    # First check the user's visible speakers.
    existing = db.select(
        SPEAKERS_TABLE,
        columns="*",
        filters={
            "name": f"eq.{name}",
        },
    )

    for speaker in existing:
        source = speaker.get("source", "system")
        owner_id = speaker.get("user_id")

        # System speaker
        if source == "system":
            return speaker

        # Current user's speaker
        if source == "user" and owner_id == user_id:
            return speaker

    # Create a NEW user-owned speaker.
    return db.insert(
        SPEAKERS_TABLE,
        {
            "name": name,
            "gender": gender,
            "description": description,
            "source": "user",
            "user_id": user_id,
        },
    )
def _save_speaker_emotion(
    speaker_id: str,
    emotion: str,
    storage_path: str,
    public_url: str,
    *,
    user_id: str,
) -> Dict[str, Any]:
    """
    Save a user-owned emotion reference audio.
    """

    return _get_data_api().upsert(
        SPEAKER_EMOTIONS_TABLE,
        {
            "speaker_id": speaker_id,
            "emotion": emotion,
            "storage_path": storage_path,
            "public_url": public_url,
            "source": "user",
            "user_id": user_id,
        },
        on_conflict="speaker_id,emotion",
    )
def _update_speaker(
    speaker_id: str,
    name: str,
    gender: str,
    description: str,
    *,
    user_id: str,
) -> Dict[str, Any]:
    """Update a user-owned speaker's name, gender, and description."""

    if not _data_api_enabled():
        raise HTTPException(
            status_code=500,
            detail="Data API is not configured",
        )

    name = name.strip()
    gender = gender.strip().lower()
    description = description.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Speaker name is required",
        )

    # Verify the speaker belongs to the current user.
    speaker = _get_speaker(
        speaker_id,
        user_id=user_id,
    )

    if speaker is None:
        raise HTTPException(
            status_code=404,
            detail="Speaker not found",
        )

    # System speakers are read-only.
    if speaker.get("source", "system") == "system":
        raise HTTPException(
            status_code=403,
            detail="System speakers cannot be edited.",
        )

    # Extra ownership check.
    if speaker.get("user_id") != user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only edit your own speakers.",
        )

    try:
        result = _get_data_api().update(
            SPEAKERS_TABLE,
            filters={
                "id": f"eq.{speaker_id}",
                "source": "eq.user",
                "user_id": f"eq.{user_id}",
            },
            data={
                "name": name,
                "gender": gender,
                "description": description,
            },
        )

        if isinstance(result, list):
            return result[0] if result else {}

        return result

    except ApiError as e:
        logger.error(
            "Failed to update speaker: %s %s",
            e,
            e.body,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update speaker: {e}",
        ) from e
def _refresh_speaker_cache():

    global _SPEAKERS
    global _SPEAKER_EMOTIONS

    _SPEAKERS = _load_speakers()
    _SPEAKER_EMOTIONS = _load_speaker_emotions()

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _get_current_user(request):
        return RedirectResponse("/ui", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "title": "Login • TTS-DAI",
            "error": None,
        },
    )
    
@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if _get_current_user(request):
        return RedirectResponse("/ui", status_code=303)

    return templates.TemplateResponse(
        "signup.html",
        {
            "request": request,
            "title": "Signup • TTS-DAI",
            "error": None,
            "success": None,
        },
    )

@app.post("/signup")
def signup(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    username = username.strip()
    email = email.strip().lower()

    # -----------------------------
    # Required fields
    # -----------------------------
    if not username:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Username is required.",
            },
            status_code=400,
        )

    if not email:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Email is required.",
            },
            status_code=400,
        )

    # -----------------------------
    # Username validation
    # 3–30 characters
    # At least one letter
    # Letters, numbers, _, and single spaces only
    # -----------------------------
    if len(username) < 3 or len(username) > 30:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Username must be between 3 and 30 characters.",
            },
            status_code=400,
        )

    if not re.fullmatch(
        r"(?=.*[A-Za-z])[A-Za-z0-9_]+(?: [A-Za-z0-9_]+)*",
        username,
    ):
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": (
                    "Username must contain at least one letter and can only "
                    "contain letters, numbers, underscores, and single spaces."
                ),
            },
            status_code=400,
        )

    # -----------------------------
    # Email validation
    # -----------------------------
    if not re.fullmatch(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        email,
    ):
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Please enter a valid email address.",
            },
            status_code=400,
        )

    # -----------------------------
    # Password confirmation
    # -----------------------------
    if password != confirm_password:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Passwords do not match.",
            },
            status_code=400,
        )

    # -----------------------------
    # Password validation
    # Minimum 8 characters
    # At least one uppercase
    # At least one special character
    # -----------------------------
    if len(password) < 8:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Password must be at least 8 characters long.",
            },
            status_code=400,
        )

    if not re.search(r"[A-Z]", password):
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Password must contain at least one uppercase letter.",
            },
            status_code=400,
        )

    if not re.search(r"[^A-Za-z0-9\s]", password):
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Password must contain at least one special character.",
            },
            status_code=400,
        )

    # -----------------------------
    # Duplicate username
    # -----------------------------
    existing_username = _get_user_by_username(username)

    if existing_username:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Username is already taken.",
            },
            status_code=400,
        )

    # -----------------------------
    # Duplicate email
    # -----------------------------
    existing_email = _get_user_by_email(email)

    if existing_email:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "An account with this email already exists.",
            },
            status_code=400,
        )

    # -----------------------------
    # Hash password
    # -----------------------------
    password_hash = PASSWORD_HASHER.hash(password)

    # -----------------------------
    # Insert user
    # -----------------------------
    try:
        _get_data_api().insert(
            USERS_TABLE,
            {
                "username": username,
                "email": email,
                "password_hash": password_hash,
            },
        )

    except ApiError as e:
        logger.error(
            "Signup failed: %s %s",
            e,
            e.body,
        )

        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "title": "TTS-DAI • Signup",
                "error": "Unable to create account. Please try again.",
            },
            status_code=500,
        )

    # -----------------------------
    # Signup successful
    # -----------------------------
    return templates.TemplateResponse(
        "signup.html",
        {
            "request": request,
            "title": "Signup • TTS-DAI",
            "error": None,
            "success": "Account created successfully. Login now."
        },
        status_code=200,
    )

@app.post("/login")
def login(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
):
    login = login.strip()

    if not login or not password:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "title": "Login • TTS-DAI",
                "error": "Username/email and password are required.",
            },
            status_code=400,
        )

    user = _get_user_by_login(login)

    if user is None:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "title": "Login • TTS-DAI",
                "error": "Invalid username/email or password.",
            },
            status_code=401,
        )

    password_hash = user.get("password_hash", "")

    try:
        password_valid = PASSWORD_HASHER.verify(
            password,
            password_hash,
        )
    except Exception:
        password_valid = False

    if not password_valid:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "title": "Login • TTS-DAI",
                "error": "Invalid username/email or password.",
            },
            status_code=401,
        )

    request.session.clear()
    request.session["user_id"] = user["id"]

    return RedirectResponse(
        "/ui",
        status_code=303,
    )
@app.post("/logout")
def logout(request: Request):
    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=303,
    )
@app.get("/speakers")
def list_speakers(request: Request):
    user = _require_login(request)

    return {
        "speakers": _get_visible_speakers(
            user_id=user["id"],
        ),
        "speaker_emotions": _get_visible_speaker_emotions(
            user_id=user["id"],
        ),
    }

@app.get("/ui", response_class=HTMLResponse)
def ui_index(request: Request) -> HTMLResponse:

    user = _require_login(request)

    data_api = _get_data_api()

    # Use the same visibility logic as Speaker Studio
    speakers = _get_visible_speakers(
        user_id=user["id"],
    )

    # Get only this user's generations
    generations = data_api.select(
        "tts_generations",
        columns="id",
        filters={
            "user_id": f"eq.{user['id']}",
        },
    )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "TTS-DAI • Dashboard",

            "speaker_count": len(speakers),
            "generation_count": len(generations),

            "current_user": user,
        },
    )
@app.get("/ui/speakers", response_class=HTMLResponse)
def ui_speakers(request: Request):
    user = _require_login(request)

    speakers = _get_visible_speakers(
        user_id=user["id"],
    )

    speaker_emotions = _get_visible_speaker_emotions(
        user_id=user["id"],
    )

    return templates.TemplateResponse(
        "speakers.html",
        {
            "request": request,
            "title": "Speaker Studio",
            "speakers": speakers,
            "speaker_emotions": speaker_emotions,
            "current_user": user,
        },
    )
@app.post("/ui/speakers/upload")
async def ui_speakers_upload(
    request: Request,
    speaker_name: str = Form(...),
    gender: str = Form(""),
    description: str = Form(""),
    emotion: str = Form(...),
    sample: UploadFile = File(...),
) -> RedirectResponse:

    user = _require_login(request)

    description = description.strip()
    gender = gender.strip().lower()
    emotion = emotion.strip().lower()
    speaker_name = speaker_name.strip()

    if not speaker_name:
        raise HTTPException(
            status_code=400,
            detail="Speaker name is required",
        )

    if not emotion:
        raise HTTPException(
            status_code=400,
            detail="Emotion is required",
        )


    # 1. Find visible speaker
    speaker_id = _get_speaker_id(
        speaker_name,
        user_id=user["id"],
    )

    # --------------------------------------------------
    # 3. Create new user-owned speaker if needed
    # --------------------------------------------------

    if speaker_id is None:

        speaker = _create_or_get_speaker(
            name=speaker_name,
            gender=gender,
            description=description,
            user_id=user["id"],
        )

        speaker_id = speaker["id"]

    else:
        speaker = _get_speaker(
           speaker_id,
           user_id=user["id"],
        )

        if speaker is None:
            raise HTTPException(
               status_code=404,
               detail="Speaker not found",
            )

        # System speakers cannot be modified.
        if speaker.get("source", "system") == "system":
            raise HTTPException(
                status_code=403,
                detail="System speakers cannot be modified.",
            )
     # 3. Upload and clean audio
    try:
        audio_info = await _upload_speaker_emotion(
            speaker_name=speaker_name,
            emotion=emotion,
            upload=sample,
        )
        # 4. Save user-owned emotion
        _save_speaker_emotion(
            speaker_id=speaker_id,
            emotion=emotion,
            storage_path=audio_info["storage_path"],
            public_url=audio_info["public_url"],
            user_id=user["id"],
        )

    except Exception as e:
        import traceback

        traceback.print_exc()

        raise HTTPException(
            status_code=400,
            detail=str(e),
        )  

    # 5. Refresh memory cache
    _refresh_speaker_cache()


    return RedirectResponse(
        "/ui/speakers",
        status_code=303,
    )

@app.post("/ui/speakers/update")
async def ui_speakers_update(
    request: Request,
    speaker_id: str = Form(...),
    speaker_name: str = Form(...),
    gender: str = Form(""),
    description: str = Form(""),
    emotion_id: str = Form(""),
    sample: Optional[UploadFile] = File(None),
) -> RedirectResponse:
    user = _require_login(request)
    speaker_name = speaker_name.strip()
    gender = gender.strip().lower()
    description = description.strip()

    if not speaker_id:
        raise HTTPException(
            status_code=400,
            detail="Speaker ID is required",
        )

    if not speaker_name:
        raise HTTPException(
            status_code=400,
            detail="Speaker name is required",
        )

    speaker = _get_speaker(
        speaker_id,
        user_id=user["id"],
    )

    if speaker is None:
        raise HTTPException(
            status_code=404,
            detail="Speaker not found",
        )

    # --------------------------------------------------
    # 1. Update speaker information
    # --------------------------------------------------

    old_name = speaker.get("name", "").strip()

    _update_speaker(
        speaker_id=speaker_id,
        name=speaker_name,
        gender=gender,
        description=description,
        user_id=user["id"],
    )
    
    # --------------------------------------------------
    # 2. Replace emotion audio if provided
    # --------------------------------------------------

    if sample is not None and sample.filename:

        if not emotion_id:
            raise HTTPException(
                status_code=400,
                detail="Emotion ID is required when replacing audio",
            )

        emotion_info = _get_emotion(
            emotion_id,
            user_id=user["id"],
        )

        if emotion_info is None:
            raise HTTPException(
                status_code=404,
                detail="Emotion audio not found",
            )

        if emotion_info.get("speaker_id") != speaker_id:
            raise HTTPException(
                status_code=400,
                detail="Emotion does not belong to this speaker",
            )
        if emotion_info.get("source", "system") == "system":
            raise HTTPException(
                status_code=403,
                detail="System emotion audio cannot be replaced.",
            )

        if emotion_info.get("user_id") != user["id"]:
            raise HTTPException(
                status_code=403,
                detail="You can only replace your own emotion audio.",
            )
        emotion_name = emotion_info.get("emotion", "").strip().lower()

        audio_info = await _replace_speaker_emotion(
            emotion_info=emotion_info,
            speaker_name=speaker_name,
            emotion=emotion_name,
            upload=sample,
        )

        # Update database
        try:
            _get_data_api().update(
                SPEAKER_EMOTIONS_TABLE,
                filters={
                    "id": f"eq.{emotion_id}",
                },
                data={
                    "storage_path": audio_info["storage_path"],
                    "public_url": audio_info["public_url"],
                },
            )

        except ApiError as e:
            logger.error(
                "Failed to update emotion audio: %s %s",
                e,
                e.body,
            )

            raise HTTPException(
                status_code=500,
                detail=f"Failed to update emotion audio: {e}",
            ) from e

    # --------------------------------------------------
    # 3. Refresh cache
    # --------------------------------------------------

    _refresh_speaker_cache()

    return RedirectResponse(
        "/ui/speakers",
        status_code=303,
    )

@app.get("/ui/speakers/audio/{emotion_id}")
def ui_speakers_audio(emotion_id: str):
    db = _get_data_api()

    rows = db.select(
        SPEAKER_EMOTIONS_TABLE,
        columns="*",
        filters={"id": f"eq.{emotion_id}"},
        limit=1,
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Audio record not found",
        )

    emotion = rows[0]
    storage_path = emotion.get("storage_path")

    if not storage_path:
        raise HTTPException(
            status_code=404,
            detail="Audio storage path not found",
        )

    try:
        audio_bytes = _get_store_api().download(
            SPEAKERS_BUCKET,
            storage_path,
        )
    except ApiError as exc:
        raise HTTPException(
            status_code=exc.status_code or 500,
            detail=exc.body or str(exc),
        )

    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
@app.post("/ui/speakers/delete")
async def ui_speakers_delete(
    request: Request,
    speaker_id: str = Form(...),
) -> RedirectResponse:
    global _SPEAKERS, _SPEAKER_EMOTIONS

    # --------------------------------------------------
    # 1. Require authentication
    # --------------------------------------------------

    user = _require_login(request)

    # --------------------------------------------------
    # 2. Find speaker visible to this user
    # --------------------------------------------------

    speaker = _get_speaker(
        speaker_id,
        user_id=user["id"],
    )

    if speaker is None:
        raise HTTPException(
            status_code=404,
            detail="Speaker not found",
        )

    # --------------------------------------------------
    # 3. System speakers cannot be deleted
    # --------------------------------------------------

    if speaker.get("source", "system") == "system":
        raise HTTPException(
            status_code=403,
            detail="System speakers cannot be deleted.",
        )

    # --------------------------------------------------
    # 4. Make sure this speaker belongs to current user
    # --------------------------------------------------

    if speaker.get("user_id") != user["id"]:
        raise HTTPException(
            status_code=403,
            detail="You can only delete your own speakers.",
        )

    # --------------------------------------------------
    # 5. Delete database/storage records
    # --------------------------------------------------

    if _persistence_enabled():

        db = _get_data_api()
        store = _get_store_api()

        emotion_paths = []

        for emotion in _SPEAKER_EMOTIONS:

            if emotion.get("speaker_id") != speaker_id:
                continue

            # Extra protection:
            # only collect files belonging to this user's speaker.
            if (
                emotion.get("source", "system") == "user"
                and emotion.get("user_id") == user["id"]
            ):
                storage_path = emotion.get("storage_path")

                if storage_path:
                    emotion_paths.append(storage_path)

        # --------------------------------------------------
        # 6. Remove audio files from storage
        # --------------------------------------------------

        if emotion_paths:

            try:
                store.remove(
                    SPEAKERS_BUCKET,
                    emotion_paths,
                )

            except Exception as e:
                logger.warning(
                    "Could not remove speaker emotion files: %s",
                    e,
                )

        # --------------------------------------------------
        # 7. Delete emotion database records
        # --------------------------------------------------

        db.delete(
            SPEAKER_EMOTIONS_TABLE,
            filters={
                "speaker_id": f"eq.{speaker_id}",
                "source": "eq.user",
                "user_id": f"eq.{user['id']}",
            },
        )

        # --------------------------------------------------
        # 8. Delete speaker database record
        # --------------------------------------------------

        db.delete(
            SPEAKERS_TABLE,
            filters={
                "id": f"eq.{speaker_id}",
                "source": "eq.user",
                "user_id": f"eq.{user['id']}",
            },
        )

    # --------------------------------------------------
    # 9. Refresh cache
    # --------------------------------------------------

    _SPEAKERS = _load_speakers()
    _SPEAKER_EMOTIONS = _load_speaker_emotions()

    return RedirectResponse(
        "/ui/speakers",
        status_code=303,
    )


@app.get("/ui/tts", response_class=HTMLResponse)
def ui_tts(request: Request) -> HTMLResponse:
    user = _require_login(request)

    speakers = _get_visible_speakers(
        user_id=user["id"],
    )

    speaker_emotions = _get_visible_speaker_emotions(
        user_id=user["id"],
    )

    return templates.TemplateResponse(
        "tts.html",
        {
            "request": request,
            "title": "TTS-DAI • TTS Studio",

            "speakers": speakers,
            "speaker_emotions": speaker_emotions,

            "chunk_max_chars": 220,
            "pause_sentence_ms": 420,
            "pause_clause_ms": 220,
            "pause_default_ms": 160,
            "mp3_bitrate": "192k",
            "filename": "voiceover.mp3",
        },
    )
def _persist_generation(
    *,
    user_id: str,
    speaker_id: str,
    emotion_id: str,
    speaker_name: str,
    emotion: str,
    input_text: str,
    translated_text: str,
    language: str,
    speed: float,
    reference_audio_path: str,
    output_audio_path: str,
) -> None:
    """Save a generation record via the Data API."""
    if not _data_api_enabled():
        return

    try:
        _get_data_api().insert(
            GENERATIONS_TABLE,
            {
                "user_id": user_id,
                "speaker_id": speaker_id,
                "emotion_id": emotion_id,
                "speaker_name": speaker_name,
                "emotion": emotion,
                "input_text": input_text,
                "translated_text": translated_text,
                "language": language,
                "speed": speed,
                "reference_audio_path": reference_audio_path,
                "output_audio_path": output_audio_path,
            },
        )
    except ApiError as e:
        logger.error(
            "Failed to persist generation: %s %s",
            e,
            e.body,
        )
@app.post("/ui/tts/translate")
async def ui_tts_translate(
    text: str = Form(...),
    language: str = Form(...),
) -> JSONResponse:

    text = text.strip()
    language = language.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Text is required for translation.",
        )

    language_code = SUPPORTED_LANGUAGES.get(language)

    if not language_code:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language: {language}",
        )

    try:
        translated_text = GoogleTranslator(
            source="auto",
            target=language_code,
        ).translate(text)

    except Exception:
        logger.exception("Translation failed")

        raise HTTPException(
            status_code=503,
            detail="Translation service is temporarily unavailable.",
        )

    return JSONResponse(
        {
            "original_text": text,
            "translated_text": translated_text,
            "language": language_code,
        }
    )

@app.post("/ui/tts/generate")
async def ui_tts_generate(
    request: Request,
    text: str = Form(...),
    original_text: str = Form(""),
    translated_text: str = Form(""),
    speaker: str = Form(...),
    emotion: str = Form(...),
    speed: float = Form(1.0),
    language: str = Form(""),
    chunk_max_chars: int = Form(220),
    pause_sentence_ms: int = Form(420),
    pause_clause_ms: int = Form(220),
    pause_default_ms: int = Form(160),
    mp3_bitrate: str = Form("192k"),
    filename: str = Form("voiceover.mp3"),
) -> Response:
    user = _require_login(request)
    # ----------------------------------------
    # Determine TTS language
    # ----------------------------------------

    if language:
        language_code = SUPPORTED_LANGUAGES.get(language)

        if not language_code:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported language: {language}",
            )
    else:
        # Original Language option
        language_code = "en"

    logger.info(
        "Selected language: %s -> %s",
        language,
        language_code,
    )

    # ----------------------------------------
    # Optional Translation
    # ----------------------------------------

    processed_text = text

    
    # ----------------------------------------
    # Build TTS request
    # ----------------------------------------

    req = TTSRequest(
        text=processed_text,
        speaker=speaker,
        emotion=emotion,
        speed=speed,
        chunk_max_chars=chunk_max_chars,
        pause_sentence_ms=pause_sentence_ms,
        pause_clause_ms=pause_clause_ms,
        pause_default_ms=pause_default_ms,
        mp3_bitrate=mp3_bitrate,
    )

    # ----------------------------------------
    # Sanitize filename
    # ----------------------------------------

    safe_name = (
        (filename or "voiceover.mp3")
        .strip()
        .replace('"', "")
        .replace("\n", "")
    )

    if not safe_name.lower().endswith(".mp3"):
        safe_name += ".mp3"

    
    # ----------------------------------------
    # Get speaker
    # ----------------------------------------

    speaker_id = _get_speaker_id(
        req.speaker,
        user_id=user["id"],
    )

    if speaker_id is None:
        raise HTTPException(
            status_code=404,
            detail="Speaker not found",
        )

    speaker_info = _get_speaker(
            speaker_id,
            user_id=user["id"],
        )
    
    if speaker_info is None:
        raise HTTPException(
            status_code=404,
            detail="Speaker not found",
            )

    # ----------------------------------------
    # Get emotion
    # ----------------------------------------

    emotion_info = _get_emotion_by_speaker(
        speaker_id,
        req.emotion,
        user_id=user["id"],
    )

    if emotion_info is None:
        raise HTTPException(
            status_code=404,
            detail="Emotion not found",
        )

    # ----------------------------------------
    # Generate audio
    # ----------------------------------------
    
    mp3_bytes = _generate_mp3_bytes(
        req,
        language_id=language_code,
        user_id=user["id"],
    )
    

    # ----------------------------------------
    # Upload generated audio
    # ----------------------------------------

    gen_id = str(uuid.uuid4())

    storage_path = f"generations/{gen_id}.mp3"

    public_url = _upload_generated_mp3(
        mp3_bytes=mp3_bytes,
        storage_path=storage_path,
    )

    # ----------------------------------------
    # Generation configuration
    # ----------------------------------------

    sentence_pause, clause_pause, default_pause = _apply_speed_to_pauses(
        req.speed,
        req.pause_sentence_ms,
        req.pause_clause_ms,
        req.pause_default_ms,
    )

    config = {
        "speed": req.speed,
        "chunk_max_chars": req.chunk_max_chars,
        "pause_sentence_ms": sentence_pause,
        "pause_clause_ms": clause_pause,
        "pause_default_ms": default_pause,
        "mp3_bitrate": req.mp3_bitrate,
        "language": language_code,
    }

    # ----------------------------------------
    # Save generation record
    # ----------------------------------------
    
    _persist_generation(
        user_id=user["id"],
        speaker_id=speaker_id,
        emotion_id=emotion_info["id"],
        speaker_name=speaker_info["name"],
        emotion=emotion_info["emotion"],
        input_text=original_text or req.text,
        translated_text=translated_text,
        language=language_code,
        speed=req.speed,
        reference_audio_path=emotion_info["storage_path"],
        output_audio_path=storage_path,
    )

    # ----------------------------------------
    # Return response
    # ----------------------------------------

    return JSONResponse(
        {
            "id": gen_id,
            "speaker": req.speaker,
            "emotion": req.emotion,
            "language": language_code,
            "filename": safe_name,
            "text": req.text,
            "config": config,
            "storage_path": storage_path,
            "public_url": public_url,
        }
    )
    
@app.get("/ui/tts/download/{generation_id}")
async def ui_tts_download(
    generation_id: str,
    request: Request,
):
    user = _require_login(request)

    storage_path = f"generations/{generation_id}.mp3"

    if not _store_api_enabled():
        local_path = (
            APP_DIR
            / "voices"
            / "generated"
            / f"{generation_id}.mp3"
        )

        if not local_path.exists():
            raise HTTPException(
                status_code=404,
                detail="Audio file not found",
            )

        audio_bytes = local_path.read_bytes()

    else:
        store = _get_store_api()

        try:
            audio_bytes = store.download(
                GENERATIONS_BUCKET,
                storage_path,
            )

        except ApiError as e:
            raise HTTPException(
                status_code=404,
                detail=f"Audio file not found: {e}",
            ) from e

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{generation_id}.mp3"'
            )
        },
    )

@app.get("/ui/history", response_class=HTMLResponse)
def ui_history(request: Request) -> HTMLResponse:
    user = _require_login(request)

    gens = _load_generations(
        limit=100,
        user_id=user["id"],
    )

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "title": "TTS-DAI • History",
            "generations": gens,
        },
    )


@app.get("/api/generations")
def api_generations(
    request: Request,
    limit: int = 100,
) -> JSONResponse:
    user = _require_login(request)

    return JSONResponse(
        {
            "items": _load_generations(
                limit=limit,
                user_id=user["id"],
            )
        }
    )
