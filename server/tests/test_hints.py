from app import hints, main

from .conftest import SEGMENTS
from .test_api import AUTH, _post_lecture, client  # noqa: F401  (Fixture)


def test_candidate_blocks_with_context():
    segments = [{"start": float(i * 40), "end": float(i * 40 + 5), "text": t} for i, t in enumerate(
        ["Einleitung.", "Erstes Thema.", "Das kommt in der Klausur dran.", "Weiter im Stoff.", "Ganz anderes.", "Ende."])]
    blocks = hints.candidate_blocks(segments)
    assert [b["text"] for b in blocks] == ["Erstes Thema.", "Das kommt in der Klausur dran.", "Weiter im Stoff."]
    assert hints.candidate_blocks([{"start": 0.0, "end": 1.0, "text": "Nichts Besonderes."}]) == []


def test_quote_check():
    transcript = "Also, das Austauschverfahren kommt garantiert in der Klausur dran. Nächstes Thema."
    assert hints.quote_found("„Das Austauschverfahren kommt garantiert in der Klausur dran.“", transcript)
    assert hints.quote_found("Austauschverfahren kommt … in der Klausur dran", transcript)
    assert not hints.quote_found("Das Austauschverfahren kommt sicher nicht dran.", transcript)


def test_hints_flow(client, fake_client, sample_pdf):
    with sample_pdf.open("rb") as f:
        client.post("/api/modules/Lineare Algebra/scripts", headers=AUTH,
                    files={"file": ("Skript.pdf", f, "application/pdf")})
    lecture_id = _post_lecture(client).json()["lecture_id"]
    fake_client.finished = True
    main.service.poll_jobs()
    main.service.ensure_hint_jobs()
    request = fake_client.messages.batches.created[-1][0]["params"]
    assert "garantiert in der Klausur" in request["messages"][0]["content"]
    main.service.poll_jobs()

    items = main.service.module_hints(1)
    # Zeitstempel hinter dem Videoende wird verworfen, erfundenes Zitat markiert, unbekannte Seite entfernt
    assert [(h["topic"], h["verified"]) for h in items] == [("Erfunden", False), ("Klausur", True)]
    assert items[1]["pages"] == ["Skript S. 1"] and items[1]["seconds"] == 40
    main.service.ensure_hint_jobs()  # kein zweiter Auftrag für dieselben Notizen
    with main.service.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'hints'").fetchone()[0] == 1

    page = client.get("/modules/1/pruefungshinweise").text
    assert f'/lectures/{lecture_id}#t-40"' in page and "Zitat nicht wörtlich gefunden" in page
    assert "Klausurrelevant (1)" in page and "Prüfungshinweise" in client.get("/modules/1").text
    assert 'data-t="40"' in client.get(f"/lectures/{lecture_id}").text
    md = client.get("/modules/1/pruefungshinweise.md").text
    assert "## Klausurrelevant" in md and "„Das kommt garantiert in der Klausur.“" in md
    api = client.get("/api/modules/Lineare Algebra/hints", headers=AUTH).json()
    assert api["count"] == 2 and api["markdown"].startswith("# Prüfungshinweise")
    assert "(Prüfungshinweise)" in client.get("/kosten").text

    # Die Klausurvorbereitung bekommt die geprüften Hinweise als Eingabe
    main.service.ensure_exam_jobs()
    exam_request = fake_client.messages.batches.created[-1][0]["params"]["messages"][0]["content"]
    assert "<pruefungshinweise_des_dozenten>" in exam_request and "(Klausurrelevant) Klausur" in exam_request


def test_no_trigger_words_means_no_claude_call(client, fake_client):
    r = client.post("/api/modules/Lineare Algebra/lectures", headers=AUTH, json={
        "title": "Ruhig", "source_filename": "ruhig.mp4", "duration_sec": 60,
        "segments": [{"start": 0, "end": 5, "text": "Heute nur Beispiele ohne Besonderheiten."}]})
    assert r.status_code == 200
    fake_client.finished = True
    main.service.poll_jobs()
    before = len(fake_client.messages.batches.created)
    main.service.ensure_hint_jobs()
    assert len(fake_client.messages.batches.created) == before
    assert main.service.hints_status(1)["lectures"] == 1 and main.service.module_hints(1) == []
