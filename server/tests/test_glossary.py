import json
import sqlite3

from app import main
from app.db import Database
from app.glossary import group_entries, normalize, parse_entries, sort_key, to_markdown

from .test_api import AUTH, _post_lecture, client  # noqa: F401  (Fixture)


def _finish_notes_and_glossary(fake_client):
    fake_client.finished = True
    main.service.poll_jobs()             # Notizen fertig
    main.service.ensure_glossary_jobs()  # Glossar-Job aus den Notizen
    main.service.poll_jobs()             # Glossar fertig


def test_parse_entries_drops_unknown_sources():
    text = json.dumps({"eintraege": [{"begriff": " Eigenwert ", "art": "Begriff", "definition": "d",
                                      "formel": "$x$", "zeitstempel": ["00:00:10", "02:00:00", "quatsch"],
                                      "seiten": ["Skript S. 1", "[Skript S. 2]", "Anderes S. 1"]}]})
    [e] = parse_entries(text, duration_sec=3600, known_pages={("Skript", "1"), ("Skript", "2")})
    assert e["term"] == "Eigenwert" and e["formula"] == "x"
    assert e["timestamps"] == ["00:00:10"]
    assert e["pages"] == ["Skript S. 1", "Skript S. 2"]


def test_group_and_sort():
    assert normalize("Satz  von Bayes!") == normalize("satz von bayes")
    assert sorted(["Zahl", "Ähnlichkeit", "Basis"], key=sort_key) == ["Ähnlichkeit", "Basis", "Zahl"]
    rows = [
        {"norm": "eigenwert", "term": "eigenwert", "kind": "Begriff", "definition": "alt", "formula": "a",
         "lecture_id": 1, "lecture_title": "VL1", "timestamps": [], "pages": []},
        {"norm": "eigenwert", "term": "Eigenwert", "kind": "Begriff", "definition": "neu", "formula": "",
         "lecture_id": 2, "lecture_title": "VL2", "timestamps": ["00:01:00"], "pages": []},
    ]
    [g] = group_entries(rows)
    assert g["term"] == "Eigenwert" and g["definition"] == "neu" and g["formula"] == "a"
    assert [o["lecture_title"] for o in g["other_definitions"]] == ["VL1"]
    md = to_markdown("LA", [g], "01.10.2026")
    assert "## E" in md and "$$ a $$" in md and "> VL1: alt" in md and "VL2 [00:01:00]" in md


def test_glossary_from_existing_notes_and_growth(client, fake_client, sample_pdf):
    with sample_pdf.open("rb") as f:
        client.post("/api/modules/Lineare Algebra/scripts", headers=AUTH,
                    files={"file": ("Skript.pdf", f, "application/pdf")})
    first = _post_lecture(client, "VL01.mp4").json()["lecture_id"]
    _finish_notes_and_glossary(fake_client)

    groups = main.service.module_glossary(1)
    assert [g["term"] for g in groups] == ["Ähnlichkeit", "Eigenwert"]
    eigenwert = groups[1]
    # Zeitstempel hinter dem Videoende und unbekannte Seiten werden verworfen
    assert eigenwert["sources"][0]["timestamps"] == ["00:00:10"]
    assert eigenwert["sources"][0]["pages"] == ["Skript S. 1"]

    # Ein erneuter Durchlauf legt keinen weiteren Glossar-Job an
    before = main.service.db.connect
    with before() as conn:
        n_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'glossary'").fetchone()[0]
    main.service.ensure_glossary_jobs()
    with before() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'glossary'").fetchone()[0] == n_jobs

    # Zweite Vorlesung: gleicher Begriff wird zusammengeführt, das Glossar wächst mit
    _post_lecture(client, "VL02.mp4")
    _finish_notes_and_glossary(fake_client)
    groups = main.service.module_glossary(1)
    assert len(groups) == 2 and len(groups[1]["sources"]) == 2

    # Die Notizen-Ansicht der Vorlesung zeigt weiterhin die Notizen, nicht das Glossar-JSON
    assert main.service.latest_job(first)["kind"] == "notes"
    info = client.get("/api/modules/Lineare Algebra/glossary", headers=AUTH).json()
    assert info["count"] == 2 and "# Glossar – Lineare Algebra" in info["markdown"]
    assert client.get("/api/modules/Unbekannt/glossary", headers=AUTH).json() == {"count": 0, "markdown": ""}

    page = client.get("/modules/1/glossar")
    assert page.status_code == 200 and "Eigenwert" in page.text and 'class="math block"' in page.text
    assert "2 Einträge" in client.get("/modules/1").text
    assert "(Glossar)" in client.get("/kosten").text
    assert client.get("/modules/1/glossar.md").headers["content-disposition"].startswith("attachment")


def test_migration_adds_columns(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, lecture_id INTEGER, status TEXT)")
    conn.commit()
    conn.close()
    Database(path)
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(jobs)")}
    assert {"kind", "source_job_id"} <= cols
