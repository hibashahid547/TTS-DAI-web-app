-- TTS-DAI schema for PostgREST Data API
-- Matches application usage in main.py (storage_path, not audio_path).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.speakers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT speakers_name_key UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS public.speaker_emotions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    speaker_id uuid NOT NULL
        REFERENCES public.speakers (id)
        ON DELETE CASCADE,
    emotion text NOT NULL,
    storage_path text NOT NULL,
    public_url text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT speaker_emotions_speaker_id_emotion_key UNIQUE (speaker_id, emotion)
);

CREATE INDEX IF NOT EXISTS speaker_emotions_speaker_id_idx
    ON public.speaker_emotions (speaker_id);

CREATE TABLE IF NOT EXISTS public.tts_generations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    speaker_id uuid NOT NULL
        REFERENCES public.speakers (id)
        ON DELETE CASCADE,
    emotion_id uuid NOT NULL
        REFERENCES public.speaker_emotions (id)
        ON DELETE CASCADE,
    input_text text NOT NULL,
    language text NOT NULL DEFAULT 'en',
    speed double precision NOT NULL DEFAULT 1.0,
    output_audio_path text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tts_generations_created_at_idx
    ON public.tts_generations (created_at DESC);

CREATE INDEX IF NOT EXISTS tts_generations_speaker_id_idx
    ON public.tts_generations (speaker_id);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS speakers_set_updated_at ON public.speakers;
CREATE TRIGGER speakers_set_updated_at
    BEFORE UPDATE ON public.speakers
    FOR EACH ROW
    EXECUTE PROCEDURE public.set_updated_at();

DROP TRIGGER IF EXISTS speaker_emotions_set_updated_at ON public.speaker_emotions;
CREATE TRIGGER speaker_emotions_set_updated_at
    BEFORE UPDATE ON public.speaker_emotions
    FOR EACH ROW
    EXECUTE PROCEDURE public.set_updated_at();

-- Expose tables to common PostgREST roles when present.
DO $$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'anon',
        'authenticated',
        'authenticator',
        'service_role',
        'web_anon',
        'api_user'
    ]
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', role_name);
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I',
                role_name
            );
            EXECUTE format(
                'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I',
                role_name
            );
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
                role_name
            );
        END IF;
    END LOOP;
END;
$$;

-- Ask PostgREST to reload its schema cache (no-op if listener absent).
NOTIFY pgrst, 'reload schema';
