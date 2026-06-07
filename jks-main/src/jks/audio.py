from __future__ import annotations

from pathlib import Path
import platform
import subprocess
import tempfile
import time
from typing import Optional
from uuid import uuid4


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        output_dir: Optional[Path] = None,
        sounddevice_module=None,
        soundfile_module=None,
    ):
        self.sample_rate = sample_rate
        self.output_dir = Path(output_dir) if output_dir is not None else Path(tempfile.gettempdir())
        self._sounddevice_module = sounddevice_module
        self._soundfile_module = soundfile_module
        self._stream = None
        self._chunks = []

    def record_fixed_seconds(self, seconds: float = 4.0) -> Path:
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        sd = self._sounddevice()
        sf = self._soundfile()
        frames = int(self.sample_rate * seconds)
        data = sd.rec(frames, samplerate=self.sample_rate, channels=1, dtype="float32")
        sd.wait()
        output = self._new_output_path()
        sf.write(output, data, self.sample_rate)
        return output

    def start_recording(self) -> None:
        if self._stream is not None:
            raise RuntimeError("recording already in progress")
        self._chunks = []
        stream = self._sounddevice().InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._capture_chunk,
        )
        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream

    def stop_recording(self) -> Path:
        if self._stream is None:
            raise RuntimeError("recording is not in progress")
        stream = self._stream
        self._stream = None
        try:
            stream.stop()
        finally:
            stream.close()

        output = self._new_output_path()
        self._soundfile().write(output, self._merged_chunks(), self.sample_rate)
        return output

    def _capture_chunk(self, indata, frames, time, status) -> None:
        if hasattr(indata, "copy"):
            self._chunks.append(indata.copy())
        else:
            self._chunks.append(indata)

    def _merged_chunks(self):
        if not self._chunks:
            return []
        if len(self._chunks) == 1:
            return self._chunks[0]
        try:
            import numpy as np
        except ImportError:
            return self._chunks
        return np.concatenate(self._chunks, axis=0)

    def _new_output_path(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir / f"jks-recording-{uuid4().hex}.wav"

    def _sounddevice(self):
        if self._sounddevice_module is None:
            import sounddevice as sd

            self._sounddevice_module = sd
        return self._sounddevice_module

    def _soundfile(self):
        if self._soundfile_module is None:
            import soundfile as sf

            self._soundfile_module = sf
        return self._soundfile_module


class AudioPlayer:
    def __init__(self, runner=subprocess.run, popen=subprocess.Popen):
        self._runner = runner
        self._popen = popen
        self._sd = None
        self._process = None
        self._stopped = False

    def play(self, audio_path: Path) -> None:
        audio_path = Path(audio_path)
        self._stopped = False
        if self._runner is not None and self._runner is not subprocess.run:
            self._runner(["afplay", audio_path.as_posix()], check=True)
            return

        try:
            import sounddevice as sd
            import soundfile as sf

            data, sample_rate = sf.read(audio_path)
            self._sd = sd
            sd.play(data, sample_rate)
            sd.wait()
            self._sd = None
            return
        except Exception:
            self._sd = None

        system = platform.system()
        if system == "Darwin":
            self._run_interruptible(["afplay", str(audio_path)])
        elif system == "Windows":
            import winsound

            winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
        else:
            self._run_interruptible(["aplay", str(audio_path)])

    def play_stream(self, chunks, suffix: str = ".mp3") -> None:
        if suffix != ".mp3":
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as output:
                output_path = Path(output.name)
                for chunk in chunks:
                    if chunk:
                        output.write(chunk)
            self.play(output_path)
            return None

        if self._popen is subprocess.Popen and platform.system() == "Windows":
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as output:
                output_path = Path(output.name)
                for chunk in chunks:
                    if self._stopped:
                        return None
                    if chunk:
                        output.write(chunk)
            self.play(output_path)
            return None

        process = self._popen(["mpg123", "-q", "-"], stdin=subprocess.PIPE)
        self._process = process
        self._stopped = False
        try:
            if process.stdin is None:
                raise RuntimeError("stream player stdin is unavailable")
            for chunk in chunks:
                if self._stopped:
                    return None
                if chunk:
                    process.stdin.write(chunk)
            process.stdin.close()
            returncode = process.wait()
            if returncode:
                raise subprocess.CalledProcessError(returncode, ["mpg123", "-q", "-"])
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
            raise
        finally:
            self._process = None
        return None

    def stop(self) -> None:
        self._stopped = True
        if self._sd is not None:
            try:
                self._sd.stop()
            except Exception:
                pass
        poll = getattr(self._process, "poll", None)
        if self._process is not None and callable(poll) and poll() is None:
            try:
                self._process.terminate()
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        if platform.system() == "Windows":
            try:
                import winsound

                winsound.PlaySound(None, 0)
            except Exception:
                pass

    def _run_interruptible(self, command: list[str]) -> None:
        self._process = self._popen(command)
        try:
            while self._process.poll() is None:
                if self._stopped:
                    self.stop()
                    return
                time.sleep(0.05)
            if self._process.returncode:
                raise subprocess.CalledProcessError(self._process.returncode, command)
        finally:
            self._process = None
