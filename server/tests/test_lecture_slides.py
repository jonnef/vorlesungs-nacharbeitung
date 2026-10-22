from app import main
from app.lecture_slides import best_page, match_lecture, name_keys

from .test_api import AUTH, _post_lecture, client  # noqa: F401  (Fixture)


def test_name_keys_numbers_and_dates():
    assert name_keys("VL03 Eigenwerte.mp4") == {"n3"}
    assert name_keys("Vorlesung_3_annotiert.pdf") == {"n3"}
    assert name_keys("03_Folien.pdf") == {"n3"}
    assert name_keys("LA 14.10.2026.mp4") == {"d10-14"}
    assert name_keys("Folien_2026-10-14.pdf") == {"d10-14"}
    assert name_keys("Skript.pdf") == set()


def test_match_lecture_only_when_unique():
    lectures = [{"id": 1, "source_filename": "VL01 Vektorräume.mp4", "title": "VL01 Vektorräume"},
                {"id": 2, "source_filename": "VL02 Eigenwerte.mp4", "title": "VL02 Eigenwerte"},
                {"id": 3, "source_filename": "LA 14.10.2026.mp4", "title": "LA 14.10.2026"}]
    assert match_lecture("VL2_mit_Notizen.pdf", lectures) == 2
    assert match_lecture("Folien 2026-10-14.pdf", lectures) == 3
    assert match_lecture("Folien.pdf", lectures) is None
    assert match_lecture("V1 und V2.pdf", lectures) is None  # mehrdeutig


def test_best_page_by_text_and_by_index():
    script = "Eigenwerte: lambda heisst Eigenwert der Matrix A wenn es einen Vektor gibt"
    pages = [{"slide_id": 1, "page_index": 0, "page_count": 2, "text": "Vektorraum Axiome Addition Skalar"},
             {"slide_id": 1, "page_index": 1, "page_count": 2,
              "text": "Eigenwerte: lambda heisst Eigenwert der Matrix A, wenn es einen Vektor v gibt (Notiz!)"}]
    assert best_page(script, pages)["page_index"] == 1
    assert best_page("ganz anderes Thema mit vielen anderen Wörtern hier", pages) is None
    scanned = [{"slide_id": 2, "page_index": i, "page_count": 3, "text": ""} for i in range(3)]
    assert best_page(script, scanned, script_page_count=3, script_index=2)["page_index"] == 2
    assert best_page(script, scanned, script_page_count=5, script_index=2) is None


def test_lecture_slides_flow(client, sample_pdf):
    with sample_pdf.open("rb") as f:
        client.post("/api/modules/Lineare Algebra/scripts", headers=AUTH, files={"file": ("Skript.pdf", f)})
    # Folien kommen vor der Vorlesung: zunächst ohne Zuordnung …
    with sample_pdf.open("rb") as f:
        res = client.post("/api/modules/Lineare Algebra/lecture-slides", headers=AUTH,
                          files={"file": ("VL07 Folien bemalt.pdf", f)}).json()
    assert res["created"] and res["lecture_id"] is None
    assert "Folien ohne Vorlesung" in client.get("/modules/1").text
    # … und werden zugeordnet, sobald die Vorlesung da ist.
    lecture = _post_lecture(client, "VL07 Eigenwerte.mp4").json()["lecture_id"]
    [slides] = main.service.lecture_slides_of(lecture_id=lecture)
    assert slides["filename"] == "VL07 Folien bemalt.pdf"
    page = client.get(f"/lectures/{lecture}")
    assert "VL07 Folien bemalt.pdf" in page.text and "Folien aus der Vorlesung" in page.text

    # Seite 1 des Skripts ↔ Seite 1 der bemalten Folien (gleicher Text)
    r = client.get(f"/lectures/{lecture}/folie/Skript/1.png")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert client.get(f"/lectures/{lecture}/folie/Skript/99.png").status_code == 404
    assert client.get(f"/vorlesungsfolien/{slides['id']}.pdf").headers["content-type"] == "application/pdf"

    # „gehört nicht hierher“ → wieder offen; von Hand zuordnen; löschen
    client.post(f"/vorlesungsfolien/{slides['id']}/zuordnen", data={"lecture_id": "", "back": "/"})
    assert main.service.lecture_slides_of(lecture_id=lecture) == []
    client.post(f"/vorlesungsfolien/{slides['id']}/zuordnen", data={"lecture_id": str(lecture), "back": "/"})
    assert len(main.service.lecture_slides_of(lecture_id=lecture)) == 1
    client.post(f"/vorlesungsfolien/{slides['id']}/loeschen", data={"back": "/"})
    assert main.service.lecture_slides_of(lecture_id=lecture) == []
    assert client.get(f"/lectures/{lecture}/folie/Skript/1.png").status_code == 404
