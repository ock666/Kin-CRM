from __future__ import annotations

import os
import tempfile
from typing import Optional, BinaryIO

import httpx
from openai import OpenAI


class WhisperError(Exception):
    pass


def _read_settings(db):
    from ..settings_store import get_setting, get_setting_sensitive
    cfg = {
        "provider": get_setting(db, "whisper_provider", "openai"),
        "base_url": get_setting(db, "whisper_base_url", ""),
        "api_key": get_setting_sensitive(db, "whisper_api_key"),
        "model": get_setting(db, "whisper_model", "whisper-1"),
        # Fallbacks to AI settings (OpenAI-compatible) if whisper not set
        "ai_base_url": get_setting(db, "ai_base_url", ""),
        "ai_api_key": get_setting_sensitive(db, "ai_api_key"),
    }
    return cfg


def transcribe_from_settings(db, file_obj: BinaryIO, filename: str = "audio.webm") -> str:
    """Transcribe an audio file using configured Whisper settings.

    Supports two providers:
    - provider=openai: calls OpenAI-compatible audio.transcriptions (uses whisper_* if set, else AI settings)
    - provider=asr-webservice: POSTs to {base_url}/asr (onerahmet/openai-whisper-asr-webservice)
    """
    cfg = _read_settings(db)
    provider = (cfg.get("provider") or "openai").strip().lower()
    base_url = (cfg.get("base_url") or "").strip()
    api_key = (cfg.get("api_key") or "").strip()
    model = (cfg.get("model") or "whisper-1").strip()

    if provider == "asr-webservice":
        if not base_url:
            raise WhisperError("Whisper base URL not set.")
        url = base_url.rstrip("/") + "/asr"
        with httpx.Client(timeout=60.0) as client:
            files = {"audio_file": (filename, file_obj, "application/octet-stream")}
            # encode=true lets the service transcode if needed; output=json returns {text: ..}
            r = client.post(url, params={"encode": "true", "task": "transcribe", "output": "json"}, files=files)
            if r.status_code != 200:
                raise WhisperError(f"ASR webservice error: HTTP {r.status_code}")
            data = r.json()
            text = data.get("text", "").strip()
            return text

    # Default: OpenAI-compatible
    obase = base_url or cfg.get("ai_base_url")
    okey = api_key or cfg.get("ai_api_key")
    if not obase or not okey:
        raise WhisperError("AI/Whisper is not configured.")

    client = OpenAI(base_url=obase, api_key=okey)
    # Some SDKs require a real file handle on disk; ensure we can re-open.
    # If file_obj is not seekable or not a real path, persist to temp.
    try:
        # Try passing the file-like directly
        resp = client.audio.transcriptions.create(model=model, file=file_obj)
        return getattr(resp, "text", "") or ""
    except Exception:
        # Fallback: write to a temp file and retry
        file_obj.seek(0)
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1] or ".webm", delete=True) as tmp:
            tmp.write(file_obj.read())
            tmp.flush()
            with open(tmp.name, "rb") as fh:
                resp = client.audio.transcriptions.create(model=model, file=fh)
                return getattr(resp, "text", "") or ""
