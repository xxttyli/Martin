"""Voice interface for Martin — push-to-talk speech-to-text.

Speech is just another way to type: hold a hotkey, speak, release; the audio is
transcribed locally by Faster-Whisper and the resulting TEXT is fed into the very
same pipeline the CLI uses (``Martin.handle``). Replies are printed. (Phase 1 is
speech-to-text only; spoken replies / TTS come later.)

The voice stack (faster-whisper, sounddevice, keyboard) is OPTIONAL and imported
lazily, so importing this module — and unit-testing the transcript→pipeline
handoff — never requires that stack to be installed. Install it with:

    pip install -r requirements-voice.txt

Run the loop with:

    python -m martin.interfaces.voice
"""

from __future__ import annotations

from martin.core.config import Settings, get_settings
from martin.interfaces.cli import Martin

DEFAULT_HOTKEY = "space"
SAMPLE_RATE = 16_000  # Whisper expects 16 kHz mono


class WhisperTranscriber:
    """Local speech-to-text via Faster-Whisper.

    Args:
        model_size: Whisper model size ("tiny"/"base"/"small"/"medium"/...).
        device: "auto", "cuda", or "cpu". "auto" lets CTranslate2 pick (CUDA on
            the RTX 4060 Ti, else CPU).
        compute_type: CTranslate2 compute type ("default" picks a good one per
            device; "float16" for CUDA, "int8" for CPU are common choices).
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "default",
    ) -> None:
        from faster_whisper import WhisperModel  # lazy: optional dependency

        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio, sample_rate: int = SAMPLE_RATE) -> str:
        """Transcribe a mono float32 numpy array to text."""
        segments, _info = self._model.transcribe(audio, language="en")
        return " ".join(segment.text for segment in segments).strip()


class VoiceInterface:
    """Push-to-talk voice front-end over the Martin pipeline.

    Args:
        agent: The Martin pipeline (built if omitted).
        transcriber: A speech-to-text engine (built lazily on first use if
            omitted; injectable for tests).
        settings: Settings override.
        hotkey: Push-to-talk key name (see the ``keyboard`` library).
        sample_rate: Mic capture rate, Hz.
    """

    def __init__(
        self,
        agent: Martin | None = None,
        transcriber: WhisperTranscriber | None = None,
        settings: Settings | None = None,
        hotkey: str = DEFAULT_HOTKEY,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self.settings = settings or get_settings()
        self.agent = agent or Martin(settings=self.settings)
        self.transcriber = transcriber
        self.hotkey = hotkey
        self.sample_rate = sample_rate

    def _ensure_transcriber(self) -> WhisperTranscriber:
        if self.transcriber is None:
            self.transcriber = WhisperTranscriber()
        return self.transcriber

    def handle_audio(self, audio) -> str | None:
        """Transcribe captured audio and run it through Martin.

        Returns Martin's reply, or None if nothing intelligible was heard.
        This is the core, fully-testable seam between speech and the pipeline.
        """
        transcript = self._ensure_transcriber().transcribe(audio, self.sample_rate)
        transcript = transcript.strip()
        if not transcript:
            return None
        return self.agent.handle(transcript)

    def record_while_held(self):
        """Capture microphone audio while the hotkey is held; return a numpy array.

        Hardware-dependent; not unit-tested. Requires sounddevice + keyboard.
        """
        import keyboard  # lazy: optional dependency
        import numpy as np
        import sounddevice as sd

        frames: list = []

        def _callback(indata, _frames, _time, _status):
            frames.append(indata.copy())

        keyboard.wait(self.hotkey)  # block until pressed
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=_callback,
        ):
            while keyboard.is_pressed(self.hotkey):
                sd.sleep(50)

        if not frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(frames, axis=0).flatten()

    def run(self) -> None:
        """Interactive push-to-talk loop. Ctrl+C to quit."""
        print(
            f"Martin (voice mode). Hold [{self.hotkey}] to talk, release to send. "
            "Ctrl+C to quit.\n"
        )
        self._ensure_transcriber()  # warm the model up front
        try:
            while True:
                audio = self.record_while_held()
                reply = self.handle_audio(audio)
                if reply is None:
                    print("martin > [didn't catch that]\n")
                    continue
                print(f"martin > {reply}\n")
        except KeyboardInterrupt:
            print("\nGoodbye.")


def main() -> None:
    VoiceInterface().run()


if __name__ == "__main__":
    main()
