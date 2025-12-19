import os
import shutil
from pathlib import Path
from typing import List, Optional, Callable, Union
from loguru import logger
from ffmpeg_normalize import FFmpegNormalize
import ffmpeg

# Ensure ffmpeg is available
# ffmpeg-binaries provides the executable path. We need to make sure it's usable.
ffmpeg.init()
ffmpeg.add_to_path()


class AudioNormalizer:
    def __init__(
        self,
        target_level: float = -23.0,
        true_peak: float = -1.0,
        batch_mode: bool = False,
    ):
        self.target_level = target_level
        self.true_peak = true_peak
        self.batch_mode = batch_mode

    def _get_codec_for_ext(self, ext: str) -> str:
        ext = ext.lower()
        if ext in [".mp3"]:
            return "libmp3lame"
        elif ext in [".m4a", ".aac", ".mp4"]:
            return "aac"
        elif ext in [".ogg"]:
            return "libvorbis"
        elif ext in [".flac"]:
            return "flac"
        elif ext in [".wav"]:
            return "pcm_s16le"
        return "aac"  # Default fallback

    def normalize(
        self,
        input_paths: Union[str, List[str]],
        output_dir: str,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> List[str]:
        """
        Normalize one or more audio files.

        Args:
            input_paths: Single path or list of paths to normalize.
            output_dir: Directory to save normalized files.
            progress_callback: Function to call with (status_message, progress_float).
                               Progress float is 0.0 to 1.0.

        Returns:
            List of paths to normalized files.
        """
        if isinstance(input_paths, str):
            input_paths = [input_paths]

        if not input_paths:
            return []

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Prepare output paths to preserve filenames
        output_paths = []
        for p in input_paths:
            fname = os.path.basename(p)
            output_paths.append(os.path.join(output_dir, fname))

        logger.info(
            f"Normalizing {len(input_paths)} files. Batch mode: {self.batch_mode}"
        )

        if not self.batch_mode:
            # Process individually to handle different codecs/extensions correctly
            total = len(input_paths)
            for i, (inp, outp) in enumerate(zip(input_paths, output_paths)):
                ext = os.path.splitext(inp)[1]
                codec = self._get_codec_for_ext(ext)

                if progress_callback:
                    progress_callback(
                        f"Normalizing {os.path.basename(inp)}...", (i / total)
                    )

                normalizer = FFmpegNormalize(
                    target_level=self.target_level,
                    true_peak=self.true_peak,
                    print_stats=False,
                    progress=False,  # We handle progress manually for individual files loop
                    batch=False,
                    audio_codec=codec,
                )
                normalizer.add_media_file(inp, outp)
                try:
                    normalizer.run_normalization()
                except Exception as e:
                    logger.error(f"Normalization failed for {inp}: {e}")
                    raise

            if progress_callback:
                progress_callback("Normalization complete", 1.0)
            return output_paths

        else:
            # Batch mode
            # We assume all files are compatible with the codec of the first file
            first_ext = os.path.splitext(input_paths[0])[1]
            codec = self._get_codec_for_ext(first_ext)

            normalizer = FFmpegNormalize(
                target_level=self.target_level,
                true_peak=self.true_peak,
                print_stats=False,
                progress=bool(progress_callback),
                batch=True,
                audio_codec=codec,
            )

            for inp, outp in zip(input_paths, output_paths):
                normalizer.add_media_file(inp, outp)

            if progress_callback:
                progress_callback("Normalizing (Batch)...", 0.1)

            try:
                normalizer.run_normalization()
            except Exception as e:
                logger.error(f"Normalization failed: {e}")
                raise

            if progress_callback:
                progress_callback("Normalization complete", 1.0)

            return output_paths
