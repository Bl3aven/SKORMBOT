"""
SKORMAgency - Moonshine STT client
Wraps moonshine-voice for speech-to-text transcription.

Uses the Moonshine Base model (CPU-only, ~58M params, ~10% WER).
Model is downloaded on first use and cached.
"""
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.signal import resample

log = logging.getLogger("skorm.stt")


class MoonshineSTT:
    """Moonshine Voice STT wrapper for batch transcription."""

    # Model configuration
    MODEL_LANGUAGE = "en"  # Auto-detection works best with English model as fallback
    MODEL_ARCH = 2  # Base (2 = Base, 1 = Tiny, 3 = Small Streaming)

    def __init__(self) -> None:
        self._transcriber: Optional[object] = None
        self._initialized = False
        self._model_path: Optional[str] = None

    async def initialize(self) -> bool:
        """Initialize the Moonshine transcriber. Downloads model if needed."""
        if self._initialized:
            return True

        try:
            log.info("Initializing Moonshine STT...")

            # Lazy import - moonshine-voice may not be installed in dev
            from moonshine_voice import Transcriber, get_model_for_language

            # Get or download model path
            try:
                self._model_path, model_arch = get_model_for_language("en")
                log.info("Moonshine model ready at: %s (arch=%s)", self._model_path, model_arch)
            except Exception as model_err:
                log.error("Failed to get Moonshine model: %s", model_err)
                raise

            # Create transcriber
            self._transcriber = Transcriber(
                model_path=self._model_path,
                model_arch=model_arch,
                update_interval=1.0,  # Update every second for streaming
            )
            self._initialized = True
            log.info("Moonshine STT initialized successfully")
            return True

        except ImportError as e:
            log.error("moonshine-voice import error: %s. Run: pip install moonshine-voice", e)
            return False
        except Exception as e:
            log.error("Failed to initialize Moonshine STT: %s", e)
            return False

    async def transcribe_audio(
        self,
        audio_data: bytes,
        sample_rate: int = 48000,
    ) -> str:
        """
        Transcribe raw PCM audio data.

        Args:
            audio_data: Raw PCM audio bytes (16-bit signed integer, mono)
            sample_rate: Input sample rate (default 48000 from Discord)

        Returns:
            Transcribed text string.
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized:
            return "[STT service unavailable]"

        try:
            # Convert bytes to numpy array (16-bit signed int → float32)
            pcm_int16 = np.frombuffer(audio_data, dtype=np.int16)
            audio_float = pcm_int16.astype(np.float32) / 32768.0

            # Resample to 16kHz (Moonshine's native rate) if needed
            if sample_rate != 16000:
                num_samples = int(len(audio_float) * 16000 / sample_rate)
                audio_float = resample(audio_float, num_samples)
                log.debug("Resampled audio: %d → %d samples (%dHz → 16kHz)",
                         len(pcm_int16), num_samples, sample_rate)

            # Transcribe using batch mode (no streaming needed for post-recording)
            transcript = self._transcriber.transcribe_without_streaming(
                audio_data=audio_float.tolist(),
                sample_rate=16000,
            )

            # Extract text from transcript lines
            lines = []
            if hasattr(transcript, "lines"):
                for line in transcript.lines:
                    text = getattr(line, "text", "").strip()
                    if text:
                        lines.append(text)
            elif isinstance(transcript, list):
                for item in transcript:
                    if isinstance(item, str):
                        lines.append(item.strip())
                    elif hasattr(item, "text"):
                        text = getattr(item, "text", "").strip()
                        if text:
                            lines.append(text)

            result = " ".join(lines)
            log.info("Transcription result (%d chars): %s...",
                    len(result), result[:100])
            return result if result else "[No speech detected]"

        except Exception as e:
            log.error("Transcription failed: %s", e, exc_info=True)
            return f"[Transcription error: {type(e).__name__}]"

    async def transcribe_audio_streaming(
        self,
        audio_chunks: list[tuple[bytes, int]],
    ) -> str:
        """
        Transcribe audio using streaming mode (for real-time feedback).
        Each chunk is (pcm_bytes, sample_rate).

        Args:
            audio_chunks: List of (pcm_bytes, sample_rate) tuples.

        Returns:
            Full transcribed text.
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized:
            return "[STT service unavailable]"

        try:
            transcriber = self._transcriber
            transcriber.start()

            # Feed audio chunks
            for chunk_bytes, sample_rate in audio_chunks:
                pcm_int16 = np.frombuffer(chunk_bytes, dtype=np.int16)
                audio_float = pcm_int16.astype(np.float32) / 32768.0

                # Resample to 16kHz
                if sample_rate != 16000:
                    num_samples = int(len(audio_float) * 16000 / sample_rate)
                    audio_float = resample(audio_float, num_samples)

                transcriber.add_audio(audio_float.tolist(), 16000)

            # Stop and get final transcript
            transcriber.stop()

            # Collect all lines
            transcript = transcriber.update_transcription()
            lines = []
            if hasattr(transcript, "lines"):
                for line in transcript.lines:
                    text = getattr(line, "text", "").strip()
                    if text:
                        lines.append(text)

            result = " ".join(lines)
            log.info("Streaming transcription (%d chars): %s...",
                    len(result), result[:100])
            return result if result else "[No speech detected]"

        except Exception as e:
            log.error("Streaming transcription failed: %s", e, exc_info=True)
            return f"[Transcription error: {type(e).__name__}]"

    @property
    def is_ready(self) -> bool:
        return self._initialized
