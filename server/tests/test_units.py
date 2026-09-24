from app import pricing
from app.prompt import build_request, validate_citations
from app.scripts import extract_pages, make_kuerzel
from app.selection import select_pages
from app.transcript import fmt_ts, format_transcript, merge_segments, parse_ts

from .conftest import SEGMENTS


def test_timestamps_roundtrip():
    assert fmt_ts(3725.9) == "01:02:05"
    assert parse_ts("01:02:05") == 3725


def test_merge_segments_into_blocks():
    blocks = merge_segments(SEGMENTS, block_sec=30)
    assert len(blocks) == 2
    assert blocks[0]["text"].startswith("Heute") and "gestreckt" in blocks[0]["text"]
    assert format_transcript(SEGMENTS).splitlines()[1].startswith("[00:00:40]")


def test_extract_pages(sample_pdf):
    pages = extract_pages(sample_pdf)
    assert [p[1] for p in pages] == ["1", "2"]
    assert "Eigenwerte" in pages[0][2]


def test_kuerzel_unique():
    assert make_kuerzel("VL 3 – Lineare Algebra.pdf", set()) == "VL_3_Lineare_Algebra"
    assert make_kuerzel("a.pdf", {"a"}) == "a_2"


def test_select_all_pages_when_budget_allows():
    pages = [{"id": i, "text": f"Seite {i} Text"} for i in range(5)]
    assert select_pages(pages, SEGMENTS, token_budget=10_000) == pages


def test_select_relevant_pages_when_over_budget():
    filler = "Integral Stammfunktion Substitution " * 40
    pages = [{"id": i, "text": filler} for i in range(10)]
    pages[7] = {"id": 7, "text": "Eigenwerte Eigenvektor Matrix gestreckt " * 40}
    chosen = select_pages(pages, SEGMENTS, token_budget=600)
    assert [p["id"] for p in chosen] == [7]


def test_validate_citations():
    notes = "a [00:00:10] [Skript S. 1] b [02:00:00] [Skript S. 9] c [Andere S. 1]"
    warnings = validate_citations(notes, duration_sec=3600, known_pages={("Skript", "1")})
    assert len(warnings) == 3
    assert "02:00:00" in warnings[0]


def test_build_request_escapes_and_contains_rules():
    params = build_request(model="claude-opus-5", effort="high", max_tokens=1000, title="VL <1>",
                           segments=SEGMENTS, pages=[{"kuerzel": "S", "label": "3", "text": "a < b"}])
    content = params["messages"][0]["content"]
    assert 'kuerzel="S" seite="3"' in content and "a &lt; b" in content
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"] == {"effort": "high"}


def test_cost_batch_discount():
    # 1 Mio. Input + 1 Mio. Output bei Opus 5: (5 + 25) * 0.5
    assert pricing.cost_usd("claude-opus-5", 1_000_000, 1_000_000) == 15.0
    assert pricing.cost_usd("claude-opus-5", 1_000_000, 0, batch=False) == 5.0
