import base64
import io

from app import answercheck, main

from .test_api import client  # noqa: F401  (Fixture)
from .test_cards import _setup


def _jpeg_data_url(size=(3000, 2000)) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _cards():
    karte = next(c for c in main.service.list_cards() if c["kind"] == "karte")
    aufgabe = next(c for c in main.service.list_cards() if c["kind"] == "aufgabe" and not c["calculator"])
    return karte, aufgabe


def _post(client, card_id, **body):
    return client.post(f"/lernen/{card_id}/antwort-pruefen", json=body)


def test_chat_check_and_discussion(client, fake_client, sample_pdf):
    _setup(client, fake_client, sample_pdf)
    karte, _ = _cards()
    history = [{"role": "user", "text": "Ähm, also, ein Skalar mit, äh, Av gleich lambda v"}]
    r = _post(client, karte["id"], messages=history)
    assert r.status_code == 200
    data = r.json()
    assert data["bewertung"] == "falsch" and data["vorschlag"] == 1 and data["vorschlag_text"] == "Nochmal"
    assert 'class="math inline"' in data["antwort_html"] and data["verstanden"] == "Ein Skalar mit Av = λv."
    assert data["verlauf_text"].startswith("Bewertung: falsch\nEs fehlt")
    req = fake_client.created[-1]
    assert req["model"] == "claude-haiku-5-5" and req["output_config"]["effort"] == "low"
    first = req["messages"][0]["content"]
    assert "<musterantwort>" in first and "<antwort>" in first and "Av gleich lambda v" in first
    assert "Füllwörter" in req["system"] and "Stelle keine neuen Prüfungsfragen" in req["system"]

    # Diskussion: Verlauf geht als Gespräch mit, Bewertung kann sich ändern
    history += [{"role": "assistant", "text": data["verlauf_text"]},
                {"role": "user", "text": "Das v ungleich null steckt doch im Wort Eigenvektor."}]
    r = _post(client, karte["id"], messages=history)
    data = r.json()
    assert data["bewertung"] == "richtig" and data["vorschlag"] == 3 and data["hinweis_html"]
    req = fake_client.created[-1]
    assert [m["role"] for m in req["messages"]] == ["user", "assistant", "user"]
    assert "<musterantwort>" not in req["messages"][2]["content"]

    with main.service.db.connect() as conn:
        notes = [r[0] for r in conn.execute("SELECT note FROM usage_log WHERE job_id IS NULL ORDER BY id")]
    assert notes == [f"Antwort geprüft (Karte {karte['id']})", f"Antwort besprochen (Karte {karte['id']})"]
    assert f"Antwort besprochen (Karte {karte['id']})" in client.get("/kosten").text

    page = client.get("/lernen?art=karte").text
    assert 'id="chat-text"' in page and "Antwort besprechen" in page and "Rückfrage" not in page


def test_invalid_history_rejected(client, fake_client, sample_pdf):
    _setup(client, fake_client, sample_pdf)
    karte, _ = _cards()
    n = len(fake_client.created)
    for bad in ([], [{"role": "assistant", "text": "x"}], [{"role": "user", "text": "  "}],
                [{"role": "user", "text": "a"}, {"role": "assistant", "text": "b"}],
                [{"role": "user", "text": "x" * 5000}],
                [{"role": "user" if i % 2 == 0 else "assistant", "text": "x"} for i in range(21)]):
        r = _post(client, karte["id"], messages=bad)
        assert r.status_code == 400, bad
    assert len(fake_client.created) == n


def test_photo_check_then_discussion(client, fake_client, sample_pdf):
    _setup(client, fake_client, sample_pdf)
    karte, aufgabe = _cards()
    main.settings.answer_photo_model = "claude-opus-5"
    try:
        r = _post(client, aufgabe["id"], image=_jpeg_data_url())
    finally:
        main.settings.answer_photo_model = ""
    data = r.json()
    assert r.status_code == 200 and data["bewertung"] == "teilweise" and data["fehler"] == "Zeile 3: Vorzeichenfehler."
    req = fake_client.created[-1]
    assert req["model"] == "claude-opus-5"
    image = req["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    from PIL import Image
    sent = Image.open(io.BytesIO(base64.b64decode(image["source"]["data"])))
    assert max(sent.size) == answercheck.MAX_IMAGE_SIDE  # verkleinert

    # Danach über den Rechenweg sprechen (ohne das Foto erneut zu schicken)
    r = _post(client, aufgabe["id"], messages=[
        {"role": "user", "text": answercheck.PHOTO_PLACEHOLDER},
        {"role": "assistant", "text": data["verlauf_text"]},
        {"role": "user", "text": "Warum ist Zeile 3 falsch?"}])
    assert r.status_code == 200
    req = fake_client.created[-1]
    assert req["model"] == "claude-haiku-5-5" and "Das Foto selbst liegt nicht mehr vor" in req["messages"][0]["content"]
    assert "Ergebnis:" in req["messages"][0]["content"]

    # Fotos nur bei Aufgaben, kaputte Bilder abgelehnt
    assert _post(client, karte["id"], image=_jpeg_data_url()).status_code == 400
    bad = _post(client, aufgabe["id"], image="data:image/jpeg;base64,AAAA")
    assert bad.status_code == 400 and "Foto" in bad.json()["fehler"]
    assert 'id="check-photo"' in client.get("/lernen?art=aufgabe").text


def test_check_errors_and_budget(client, fake_client, sample_pdf):
    _setup(client, fake_client, sample_pdf)
    karte, _ = _cards()
    n = len(fake_client.created)
    main.settings.monthly_budget_usd = 0.0
    try:
        r = _post(client, karte["id"], messages=[{"role": "user", "text": "x"}])
        assert r.status_code == 402 and "budget" in r.json()["fehler"].lower() and len(fake_client.created) == n
    finally:
        main.settings.monthly_budget_usd = 5.0
    fake_client.check_stop_reason = "max_tokens"
    try:
        r = _post(client, karte["id"], messages=[{"role": "user", "text": "x"}])
        assert r.status_code == 400 and "abgeschnitten" in r.json()["fehler"]
    finally:
        fake_client.check_stop_reason = "end_turn"


def test_parse_suggestion_is_fixed():
    base = '"antwort": "x", "fehlt": [], "musterantwort_hinweis": ""'
    assert answercheck.parse('{"bewertung": "teilweise", ' + base + '}')["vorschlag"] == 2
    assert answercheck.parse('{"bewertung": "unleserlich", ' + base + '}')["vorschlag"] is None
