# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["kokoro-onnx==0.6.1"]
# ///
"""
Runs the Kokoro TTS model outside Calibre (Calibre's Python can't load onnxruntime).
Launched by worker.py through `uv run --script`.

Usage: kokoro_helper.py <job.json> <out_dir>
job.json: {"voice", "lang", "speed", "model_dir",
           "chapters": [{"paragraphs": [["chunk", ...], ...]}, ...]}
Writes out_dir/chapter_000.wav ... and prints "PROGRESS done total" lines.
"""
import json
import os
import sys
import urllib.request
import wave

import numpy as np

MODEL_URL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'
MODEL_FILES = ('kokoro-v1.0.onnx', 'voices-v1.0.bin')
PARAGRAPH_PAUSE = 0.4
CHAPTER_PAUSE = 1.5


def ensure_model(model_dir):
    os.makedirs(model_dir, exist_ok=True)
    for name in MODEL_FILES:
        path = os.path.join(model_dir, name)
        if not os.path.exists(path):
            print(f'STATUS Downloading voice model {name} (first time only)...', flush=True)
            urllib.request.urlretrieve(MODEL_URL + name, path + '.part')
            os.replace(path + '.part', path)
    return [os.path.join(model_dir, n) for n in MODEL_FILES]


def main(job_path, out_dir):
    with open(job_path, encoding='utf-8') as f:
        job = json.load(f)

    from kokoro_onnx import Kokoro
    kokoro = Kokoro(*ensure_model(job['model_dir']))

    chapters = job['chapters']
    total = sum(len(p) for c in chapters for p in c['paragraphs'])
    done = 0
    sr = 24000
    for ci, chapter in enumerate(chapters):
        audio = []
        for paragraph in chapter['paragraphs']:
            for chunk in paragraph:
                samples, sr = kokoro.create(chunk, voice=job['voice'], speed=job['speed'], lang=job['lang'])
                audio.append(samples)
                done += 1
                print(f'PROGRESS {done} {total}', flush=True)
            audio.append(np.zeros(int(sr * PARAGRAPH_PAUSE), dtype=np.float32))
        audio.append(np.zeros(int(sr * CHAPTER_PAUSE), dtype=np.float32))

        pcm = (np.clip(np.concatenate(audio), -1, 1) * 32767).astype(np.int16)
        with wave.open(os.path.join(out_dir, f'chapter_{ci:03d}.wav'), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
