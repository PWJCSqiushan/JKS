import tempfile
import unittest
from pathlib import Path

from jks.audio import AudioRecorder, AudioPlayer


class FakeChunk:
    def __init__(self, value):
        self.value = value

    def copy(self):
        return f"{self.value}-copy"


class FakeInputStream:
    def __init__(self, *, samplerate, channels, dtype, callback):
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.callback = callback
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        self.started = True
        self.callback(FakeChunk("stream"), 1, None, None)

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FailingInputStream(FakeInputStream):
    def start(self):
        raise OSError("microphone unavailable")


class FakeSoundDevice:
    def __init__(self):
        self.streams = []
        self.rec_calls = []
        self.waited = False

    def InputStream(self, **kwargs):
        stream = FakeInputStream(**kwargs)
        self.streams.append(stream)
        return stream

    def rec(self, frames, *, samplerate, channels, dtype):
        self.rec_calls.append(
            {
                "frames": frames,
                "samplerate": samplerate,
                "channels": channels,
                "dtype": dtype,
            }
        )
        return "fixed-recording"

    def wait(self):
        self.waited = True


class FailingSoundDevice(FakeSoundDevice):
    def InputStream(self, **kwargs):
        stream = FailingInputStream(**kwargs)
        self.streams.append(stream)
        return stream


class FakeSoundFile:
    def __init__(self):
        self.writes = []

    def write(self, output, data, sample_rate):
        self.writes.append((Path(output), data, sample_rate))


class AudioTests(unittest.TestCase):
    def test_fixed_recording_uses_unique_output_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_sd = FakeSoundDevice()
            fake_sf = FakeSoundFile()
            recorder = AudioRecorder(
                sample_rate=16000,
                output_dir=Path(tmp),
                sounddevice_module=fake_sd,
                soundfile_module=fake_sf,
            )

            first = recorder.record_fixed_seconds(0.1)
            second = recorder.record_fixed_seconds(0.1)

        self.assertNotEqual(first, second)
        self.assertEqual(fake_sd.rec_calls[0]["frames"], 1600)
        self.assertTrue(fake_sd.waited)
        self.assertEqual(len(fake_sf.writes), 2)

    def test_start_and_stop_recording_supports_button_toggle(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_sd = FakeSoundDevice()
            fake_sf = FakeSoundFile()
            recorder = AudioRecorder(
                output_dir=Path(tmp),
                sounddevice_module=fake_sd,
                soundfile_module=fake_sf,
            )

            recorder.start_recording()
            output = recorder.stop_recording()

        self.assertTrue(fake_sd.streams[0].started)
        self.assertTrue(fake_sd.streams[0].stopped)
        self.assertTrue(fake_sd.streams[0].closed)
        self.assertTrue(output.name.startswith("jks-recording-"))
        self.assertEqual(fake_sf.writes[-1][1], "stream-copy")

    def test_recording_lifecycle_rejects_invalid_transitions(self):
        recorder = AudioRecorder(
            sounddevice_module=FakeSoundDevice(),
            soundfile_module=FakeSoundFile(),
        )

        with self.assertRaises(RuntimeError):
            recorder.stop_recording()

        recorder.start_recording()
        with self.assertRaises(RuntimeError):
            recorder.start_recording()

    def test_failed_stream_start_closes_stream_and_allows_retry(self):
        fake_sd = FailingSoundDevice()
        recorder = AudioRecorder(
            sounddevice_module=fake_sd,
            soundfile_module=FakeSoundFile(),
        )

        with self.assertRaises(OSError):
            recorder.start_recording()

        self.assertTrue(fake_sd.streams[0].closed)

        with self.assertRaises(OSError):
            recorder.start_recording()

        self.assertEqual(len(fake_sd.streams), 2)

    def test_player_uses_afplay(self):
        calls = []
        player = AudioPlayer(runner=lambda args, check: calls.append((args, check)))

        player.play(Path("/tmp/reply.wav"))

        self.assertEqual(calls, [(["afplay", "/tmp/reply.wav"], True)])

    def test_player_streams_mp3_chunks_to_mpg123_stdin(self):
        class FakeStdin:
            def __init__(self):
                self.writes = []
                self.closed = False

            def write(self, data):
                self.writes.append(data)

            def close(self):
                self.closed = True

        class FakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.waited = False
                self.killed = False

            def wait(self):
                self.waited = True
                return 0

            def kill(self):
                self.killed = True

        created = []

        def fake_popen(args, stdin):
            process = FakeProcess()
            created.append((args, stdin, process))
            return process

        player = AudioPlayer(popen=fake_popen)

        player.play_stream([b"mp3-", b"", b"bytes"], suffix=".mp3")

        args, stdin, process = created[0]
        self.assertEqual(args, ["mpg123", "-q", "-"])
        self.assertIsNotNone(stdin)
        self.assertEqual(process.stdin.writes, [b"mp3-", b"bytes"])
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.waited)
        self.assertFalse(process.killed)


if __name__ == "__main__":
    unittest.main()
