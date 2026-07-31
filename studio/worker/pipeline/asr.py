"""Transcripción con faster-whisper. Script STANDALONE: se ejecuta con el venv
dedicado (studio/.venv), no importa nada del paquete studio.

Uso:  python asr.py <media> <out.json> <model> <lang>
Salida: JSON [{"start","end","text"}, ...]
"""
import json
import sys

from faster_whisper import WhisperModel


def main() -> None:
    media, out_path, model_size, lang = sys.argv[1:5]
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        media, language=lang, vad_filter=True, beam_size=5
    )
    data = [
        {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
        for s in segments
        if s.text and s.text.strip()
    ]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"asr: {len(data)} segmentos")


if __name__ == "__main__":
    main()
