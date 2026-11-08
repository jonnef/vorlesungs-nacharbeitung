import json
from datetime import date, timedelta

from app import cards, main

from .conftest import FakeClient
from .test_api import AUTH, _post_lecture, client  # noqa: F401  (Fixture)

TODAY = date(2026, 11, 9)


def _finish_notes_and_cards(fake_client):
    fake_client.finished = True
    main.service.poll_jobs()           # Notizen fertig
    main.service.ensure_card_jobs()    # Karten-Job aus den Notizen
    main.service.poll_jobs()           # Karten fertig


def _setup(client, fake_client, sample_pdf):
    with sample_pdf.open("rb") as f:
        client.post("/api/modules/Lineare Algebra/scripts", headers=AUTH,
                    files={"file": ("Skript.pdf", f, "application/pdf")})
    lecture_id = _post_lecture(client, "VL01.mp4").json()["lecture_id"]
    _finish_notes_and_cards(fake_client)
    return lecture_id


def test_parse_drops_empty_and_unknown_sources():
    items = cards.parse(FakeClient().cards_json, duration_sec=3600, known_pages={("Skript", "1")})
    assert [i["kind"] for i in items] == ["karte", "aufgabe", "aufgabe"]
    karte, aufgabe, log = items
    assert len(karte["variants"]) == 1 and karte["timestamps"] == ["00:00:10"] and karte["pages"] == ["Skript S. 1"]
    assert len(aufgabe["variants"]) == 3 and not aufgabe["calculator"]
    assert log["calculator"]


def test_schedule_grows_and_resets():
    state = {"reps": 0, "interval_days": 0, "ease": 2.5, "lapses": 0}
    s = cards.schedule(state, 3, TODAY)
    assert s["interval_days"] == 1 and s["due"] == (TODAY + timedelta(days=1)).isoformat()
    s = cards.schedule(s, 3, TODAY)
    assert s["interval_days"] == 3
    s = cards.schedule(s, 3, TODAY)
    assert s["interval_days"] == 8  # 3 × 2,5
    assert cards.schedule(s, 4, TODAY)["interval_days"] > cards.schedule(s, 3, TODAY)["interval_days"] \
        > cards.schedule(s, 2, TODAY)["interval_days"]
    again = cards.schedule(s, 1, TODAY)
    assert again["reps"] == 0 and again["lapses"] == 1 and again["due"] == TODAY.isoformat()
    assert again["ease"] == 2.3
    assert cards.schedule({"reps": 0, "interval_days": 0, "ease": 2.5, "lapses": 0}, 4, TODAY)["interval_days"] == 4


def test_cited_pages_respects_cap():
    pages = [{"kuerzel": "S", "label": str(i), "text": "x" * 300} for i in range(1, 4)]
    chosen = cards.cited_pages("a [S S. 2] b [S S. 1] c [S S. 2] [S S. 9]", pages, max_tokens=200)
    assert [p["label"] for p in chosen] == ["2"]


def test_cards_flow(client, fake_client, sample_pdf):
    lecture_id = _setup(client, fake_client, sample_pdf)
    svc = main.service
    today = date.today()  # wie die Weboberfläche
    counts = svc.learning_counts(today)
    assert counts == {"total": 3, "due": 0, "new_total": 3, "new": 3, "reviewed_today": 0}
    assert svc.learning_counts(today, kind="aufgabe")["total"] == 2
    assert svc.learning_counts(today, no_calculator=True)["total"] == 2

    # Karten-Job enthält die zitierte Skriptseite
    with svc.db.connect() as conn:
        req = json.loads(conn.execute("SELECT request_json FROM jobs WHERE kind = 'cards'").fetchone()[0])
    assert '<seite kuerzel="Skript" seite="1">' in req["messages"][0]["content"]

    page = client.get("/lernen")
    assert page.status_code == 200 and "Was ist ein Eigenwert?" in page.text and "Antwort zeigen" in page.text
    first = svc.next_card(today)
    assert first["kind"] == "karte"

    # Aufgabe: jede Wiederholung zeigt die nächste Variante
    task = svc.next_card(today, kind="aufgabe", no_calculator=True)
    assert cards.variant_for(task)[0] == 0
    svc.review_card(task["id"], 1, today)
    task = svc.card(task["id"])
    assert cards.variant_for(task)[0] == 1

    # Bewerten über die Weboberfläche, Auswahl bleibt erhalten
    r = client.post(f"/lernen/{first['id']}/bewerten", data={"grade": "3", "modul": "", "art": "karte", "ohne_tr": ""},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/lernen?art=karte"
    assert svc.card(first["id"])["due"] == (today + timedelta(days=1)).isoformat()

    # Nochmal-Karten kommen am selben Tag nach den neuen wieder
    assert svc.next_card(today)["kind"] == "aufgabe"
    assert svc.learning_counts(today)["due"] == 1

    # Aussetzen
    client.post(f"/lernen/{task['id']}/aussetzen", data={})
    assert svc.card(task["id"])["suspended"] == 1
    assert "Ausgesetzte Karten (1)" in client.get("/lernen").text
    client.post(f"/lernen/{task['id']}/aussetzen", data={"wieder": "1"})
    assert svc.card(task["id"])["suspended"] == 0

    # Neue Fassung der Notizen: gelernte Karten bleiben, ungelernte werden ersetzt, keine Dubletten
    client.post(f"/lectures/{lecture_id}/jobs")
    _finish_notes_and_cards(fake_client)
    with svc.db.connect() as conn:
        rows = conn.execute("SELECT id, last_reviewed FROM cards ORDER BY id").fetchall()
    assert len(rows) == 3 and {r["id"] for r in rows if r["last_reviewed"]} == {first["id"], task["id"]}
    assert "3 Karteikarten und Aufgaben" in client.get("/modules/1").text


def test_new_card_limit(client, fake_client, sample_pdf):
    _setup(client, fake_client, sample_pdf)
    main.settings.new_cards_per_day = 1
    try:
        card = main.service.next_card(TODAY)
        main.service.review_card(card["id"], 3, TODAY)
        assert main.service.learning_counts(TODAY)["new"] == 0
        assert main.service.next_card(TODAY) is None
        assert main.service.next_card(TODAY + timedelta(days=1)) is not None
    finally:
        main.settings.new_cards_per_day = 20
