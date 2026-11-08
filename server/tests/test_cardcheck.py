import json

from app import cardcheck, main
from app.db import now

from .test_api import AUTH, _post_lecture, client  # noqa: F401  (Fixture)
from .test_cards import _setup


def _add_card(front: str, module_id: int = 1) -> int:
    with main.service.db.connect() as conn:
        lecture_id = conn.execute("SELECT id FROM lectures WHERE module_id = ? LIMIT 1", (module_id,)).fetchone()[0]
        return conn.execute(
            "INSERT INTO cards (module_id, lecture_id, kind, topic, calculator, variants_json, norm, timestamps_json,"
            " pages_json, created_at) VALUES (?, ?, 'karte', 'Organisation', 0, ?, ?, '[]', '[]', ?)",
            (module_id, lecture_id, json.dumps([{"front": front, "back": "Im Portal.", "result": ""}]),
             front.lower(), now())).lastrowid


def _check(fake_client):
    main.service.ensure_cardcheck_jobs()
    main.service.poll_jobs()


def _jobs():
    with main.service.db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE kind = 'cardcheck' ORDER BY id")]


def test_parse_only_checked_ids():
    text = json.dumps({"aussortieren": [{"id": 1, "grund": "organisatorisch", "begruendung": "Termin."},
                                        {"id": 2, "grund": "quatsch", "begruendung": ""},
                                        {"id": 7, "grund": "ohne_lerninhalt", "begruendung": "x"}]})
    assert cardcheck.parse(text, {1, 2}) == {1: "Organisatorisch: Termin.", 2: "Aussortiert"}


def test_cardcheck_flow(client, fake_client, sample_pdf):
    _setup(client, fake_client, sample_pdf)
    svc = main.service
    org = _add_card("Bis wann ist die Anmeldung zur Klausur?")
    _check(fake_client)
    [job] = _jobs()
    assert job["status"] == "done" and len(json.loads(job["source_ids"])) == 4
    content = json.loads(job["request_json"])["messages"][0]["content"]
    assert "<pruefungshinweise_des_dozenten>" in content and "Was ist ein Eigenwert?" in content

    card = svc.card(org)
    assert card["suspended"] == 1 and card["archive_reason"] == "Organisatorisch: Termin, kein Fachinhalt."
    assert all(c["checked_at"] for c in svc.list_cards())  # übrige Karten geprüft, aber aktiv
    assert len(svc.list_cards()) == 3

    # Archiv zeigt den Grund; schon geprüfte Karten lösen keine neue Prüfung aus
    page = client.get("/lernen/karten?archiv=1").text
    assert "Organisatorisch" in page and "Termin, kein Fachinhalt." in page
    assert "1 automatisch aussortiert" in client.get("/lernen/karten").text
    _check(fake_client)
    assert len(_jobs()) == 1

    # Wiederhergestellte Karten werden nicht erneut aussortiert
    client.post(f"/lernen/{org}/archivieren", data={"wieder": "1"})
    assert svc.card(org)["archive_reason"] is None
    client.post("/lernen/karten/pruefen", data={"modul": "1"})
    svc.poll_jobs()
    # „Erneut prüfen“ nimmt alle aktiven Karten – außer den von Hand wiederhergestellten
    assert len(_jobs()) == 2 and svc.card(org)["suspended"] == 0
    assert org not in json.loads(_jobs()[-1]["source_ids"])

    # Neue Karte → wird beim nächsten Durchlauf geprüft
    other = _add_card("Neue Fachkarte zur Diagonalisierung")
    _check(fake_client)
    assert len(_jobs()) == 3 and svc.card(other)["checked_at"] and not svc.card(other)["suspended"]


def test_cardcheck_waits_while_cards_are_created(client, fake_client, sample_pdf):
    with sample_pdf.open("rb") as f:
        client.post("/api/modules/Lineare Algebra/scripts", headers=AUTH,
                    files={"file": ("Skript.pdf", f, "application/pdf")})
    _post_lecture(client, "VL01.mp4")
    fake_client.finished = True
    main.service.poll_jobs()
    main.service.ensure_card_jobs()      # Karten-Job läuft
    main.service.ensure_cardcheck_jobs()
    assert _jobs() == []
    main.service.poll_jobs()
    main.service.ensure_hint_jobs()      # Prüfungshinweise laufen
    main.service.ensure_cardcheck_jobs()
    assert _jobs() == []
    main.service.poll_jobs()
    main.service.ensure_cardcheck_jobs()
    assert len(_jobs()) == 1
