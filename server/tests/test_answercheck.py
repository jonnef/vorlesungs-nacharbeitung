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


def test_text_check_and_followup(client, fake_client, sample_pdf):
    _setup(client, fake_client, sample_pdf)
    karte, _ = _cards()
    r = client.post(f"/lernen/{karte['id']}/antwort-pruefen", json={"answer": "Ein Skalar mit Av = λv"})
    assert r.status_code == 200
    data = r.json()
    assert data["bewertung"] == "falsch" and data["vorschlag"] == 1 and data["vorschlag_text"] == "Nochmal"
    assert 'class="math inline"' in data["rueckmeldung_html"] and data["rueckfrage"]
    req = fake_client.created[-1]
    assert req["model"] == "claude-haiku-5-5" and req["output_config"]["effort"] == "low"
    assert "<musterantwort>" in req["messages"][0]["content"] and "Av = λv" in req["messages"][0]["content"]

    r = client.post(f"/lernen/{karte['id']}/antwort-pruefen", json={
        "answer": "Sonst wäre jedes λ ein Eigenwert.", "followup": data["rueckfrage"],
        "expectation": data["rueckfrage_erwartung"]})
    assert r.json()["bewertung"] == "richtig" and r.json()["vorschlag"] == 3
    assert "<rueckfrage>" in fake_client.created[-1]["messages"][0]["content"]

    # Kosten landen im Monatsbudget und auf der Kostenseite
    with main.service.db.connect() as conn:
        notes = [r[0] for r in conn.execute("SELECT note FROM usage_log WHERE job_id IS NULL")]
    assert notes == [f"Antwort geprüft (Karte {karte['id']})", f"Rückfrage geprüft (Karte {karte['id']})"]
    assert f"Antwort geprüft (Karte {karte['id']})" in client.get("/kosten").text

    page = client.get("/lernen?art=karte").text
    assert 'id="check-answer"' in page and "Antwort prüfen" in page


def test_photo_check(client, fake_client, sample_pdf):
    _setup(client, fake_client, sample_pdf)
    karte, aufgabe = _cards()
    main.settings.answer_photo_model = "claude-opus-5"
    try:
        r = client.post(f"/lernen/{aufgabe['id']}/antwort-pruefen", json={"image": _jpeg_data_url()})
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
    assert "<musterloesung>" in req["messages"][0]["content"][1]["text"]

    # Fotos nur bei Aufgaben, kaputte Bilder abgelehnt
    assert client.post(f"/lernen/{karte['id']}/antwort-pruefen", json={"image": _jpeg_data_url()}).status_code == 400
    bad = client.post(f"/lernen/{aufgabe['id']}/antwort-pruefen", json={"image": "data:image/jpeg;base64,AAAA"})
    assert bad.status_code == 400 and "Foto" in bad.json()["fehler"]
    assert 'id="check-photo"' in client.get("/lernen?art=aufgabe").text


def test_check_errors_and_budget(client, fake_client, sample_pdf):
    _setup(client, fake_client, sample_pdf)
    karte, _ = _cards()
    assert client.post(f"/lernen/{karte['id']}/antwort-pruefen", json={"answer": "  "}).status_code == 400
    n = len(fake_client.created)
    main.settings.monthly_budget_usd = 0.0
    try:
        r = client.post(f"/lernen/{karte['id']}/antwort-pruefen", json={"answer": "x"})
        assert r.status_code == 402 and "budget" in r.json()["fehler"].lower() and len(fake_client.created) == n
    finally:
        main.settings.monthly_budget_usd = 5.0
    fake_client.check_stop_reason = "max_tokens"
    try:
        r = client.post(f"/lernen/{karte['id']}/antwort-pruefen", json={"answer": "x"})
        assert r.status_code == 400 and "abgeschnitten" in r.json()["fehler"]
    finally:
        fake_client.check_stop_reason = "end_turn"


def test_parse_suggestion_is_fixed():
    assert answercheck.parse('{"bewertung": "teilweise", "rueckmeldung": "x", "fehlt": []}')["vorschlag"] == 2
    assert answercheck.parse('{"bewertung": "unleserlich", "rueckmeldung": "x", "fehlt": []}')["vorschlag"] is None
