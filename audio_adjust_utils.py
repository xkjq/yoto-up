import os
import tempfile
import numpy as np
from pydub import AudioSegment

def save_adjusted_audio(audio: np.ndarray, framerate: int, ext: str, orig_path: str, gain_db: float) -> str:
    """
    Save the adjusted audio (with gain applied) to a temporary file.
    Returns the path to the temp file.
    """
    # Convert float32 audio to int16 for WAV, or export as MP3
    temp_dir = tempfile.gettempdir()
    base = os.path.splitext(os.path.basename(orig_path))[0]
    if ext == '.wav':
        # Scale to int16
        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        temp_path = os.path.join(temp_dir, f"{base}_adj_{int(gain_db*10)}.wav")
        import wave
        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(framerate)
            wf.writeframes(audio_int16.tobytes())
        return temp_path
    elif ext == '.mp3':
        temp_path = os.path.join(temp_dir, f"{base}_adj_{int(gain_db*10)}.mp3")
        # Convert to pydub AudioSegment
        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        seg = AudioSegment(
            audio_int16.tobytes(),
            frame_rate=framerate,
            sample_width=2,
            channels=1
        )
        seg.export(temp_path, format='mp3', bitrate='192k')
        return temp_path
    else:
        raise ValueError(f"Unsupported extension for saving: {ext}")
