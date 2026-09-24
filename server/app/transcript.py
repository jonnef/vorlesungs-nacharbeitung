"""Transkript-Segmente (von Whisper) zusammenfassen und formatieren."""


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def parse_ts(ts: str) -> int:
    h, m, s = (int(x) for x in ts.split(":"))
    return h * 3600 + m * 60 + s


def merge_segments(segments: list[dict], block_sec: float = 30.0) -> list[dict]:
    """Fasst kurze Whisper-Segmente zu Blöcken von ca. `block_sec` Sekunden zusammen.

    Spart Tokens (weniger Zeitstempel) und hält die Zeitangaben trotzdem genau genug.
    """
    blocks: list[dict] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if blocks and seg["start"] - blocks[-1]["start"] < block_sec:
            blocks[-1]["text"] += " " + text
            blocks[-1]["end"] = seg["end"]
        else:
            blocks.append({"start": float(seg["start"]), "end": float(seg["end"]), "text": text})
    return blocks


def format_transcript(segments: list[dict]) -> str:
    return "\n".join(f"[{fmt_ts(b['start'])}] {b['text']}" for b in merge_segments(segments))


def full_text(segments: list[dict]) -> str:
    return " ".join((s.get("text") or "").strip() for s in segments)
