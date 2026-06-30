import time
from faster_whisper import WhisperModel

AUDIO_PATH = "sample_audio.mp4"
MODEL_SIZE = "medium"

print(f"Loading model '{MODEL_SIZE}' on CUDA (int8)...")
t0 = time.time()
model = WhisperModel(MODEL_SIZE, device="cuda", compute_type="int8")
print(f"Model loaded in {time.time() - t0:.1f}s")

print("Starting transcription...")
t0 = time.time()
segments, info = model.transcribe(AUDIO_PATH, beam_size=5)

full_text = []
last_end = 0.0
for segment in segments:
    full_text.append(segment.text)
    last_end = segment.end

elapsed = time.time() - t0
audio_duration = info.duration
rtf = elapsed / audio_duration

print("\n--- RESULTS ---")
print(f"Audio duration: {audio_duration:.1f}s ({audio_duration/60:.1f} min)")
print(f"Transcription time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
print(f"Real-time factor (RTF): {rtf:.3f}  (speed: {1/rtf:.2f}x realtime)")
print(f"Detected language: {info.language} (p={info.language_probability:.2f})")
print(f"\nSample text (first 500 chars):\n{''.join(full_text)[:500]}")

with open("transcript_sample.txt", "w", encoding="utf-8") as f:
    f.write("".join(full_text))
