"""Tests for martin.interfaces.voice.

The voice stack (faster-whisper, sounddevice, keyboard) is optional and NOT
installed in the test environment — this module importing at all proves the lazy
imports work. We test the core seam, handle_audio(): transcribe -> pipeline,
with both the transcriber and the agent mocked. No real audio is used.
"""

from __future__ import annotations

from martin.core.config import Settings
from martin.interfaces.voice import VoiceInterface


class FakeTranscriber:
    def __init__(self, text):
        self.text = text
        self.received = None

    def transcribe(self, audio, sample_rate=16_000):
        self.received = (audio, sample_rate)
        return self.text


class FakeAgent:
    def __init__(self, reply="here is the answer"):
        self.reply = reply
        self.handled = None

    def handle(self, text):
        self.handled = text
        return self.reply


def make_voice(transcript, reply="here is the answer"):
    agent = FakeAgent(reply=reply)
    transcriber = FakeTranscriber(transcript)
    voice = VoiceInterface(
        agent=agent,
        transcriber=transcriber,
        settings=Settings(_env_file=None),
    )
    return voice, agent, transcriber


def test_handle_audio_feeds_transcript_into_pipeline():
    voice, agent, transcriber = make_voice("what is the weather today")

    reply = voice.handle_audio(audio="<fake-pcm>")

    assert reply == "here is the answer"
    # The transcript (speech) entered the same pipeline the CLI uses.
    assert agent.handled == "what is the weather today"
    # Audio + sample rate were handed to the transcriber.
    assert transcriber.received == ("<fake-pcm>", 16_000)


def test_blank_transcript_is_ignored():
    voice, agent, _ = make_voice("   ")
    assert voice.handle_audio(audio="<silence>") is None
    # Nothing intelligible -> the pipeline is never invoked.
    assert agent.handled is None


def test_empty_transcript_is_ignored():
    voice, agent, _ = make_voice("")
    assert voice.handle_audio(audio="<silence>") is None
    assert agent.handled is None
