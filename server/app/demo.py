"""Beispieldaten für die öffentliche Vorschau (DEMO_MODE=1).

Die Vorschau läuft als eigene Instanz mit eigener Datenbank (DATA_DIR) und ist
schreibgeschützt: keine Uploads, keine Claude-Aufträge, keine API. Beim ersten
Start wird die leere Datenbank mit einem Beispielmodul gefüllt.
"""

import json

from . import glossary
from .db import Database, now

MODULE = "Beispiel: Lineare Algebra"
KUERZEL = "LA_Skript"

PAGES = [
    ("1", "Kapitel 1: Vektorräume. Ein Vektorraum über einem Körper K ist eine Menge V mit Addition "
          "und Skalarmultiplikation, die die Vektorraumaxiome erfüllt."),
    ("2", "Lineare Unabhängigkeit und Basis. Vektoren v1, …, vn heißen linear unabhängig, wenn aus "
          "a1 v1 + … + an vn = 0 folgt, dass alle ai = 0 sind. Eine linear unabhängige Erzeugendenmenge "
          "heißt Basis; ihre Mächtigkeit ist die Dimension."),
    ("3", "Kapitel 2: Eigenwerte. λ heißt Eigenwert der Matrix A, wenn es einen Vektor v ≠ 0 gibt mit "
          "A v = λ v. Die Eigenwerte sind die Nullstellen des charakteristischen Polynoms det(A − λE)."),
    ("4", "Diagonalisierbarkeit. A ist genau dann diagonalisierbar, wenn es eine Basis aus Eigenvektoren "
          "gibt. Dann gilt A = S D S⁻¹ mit einer Diagonalmatrix D."),
]

LECTURES = [
    {
        "title": "VL01 Vektorräume und Basen",
        "file": "VL01 Vektorräume und Basen.mp4",
        "duration": 5400,
        "segments": [
            (12, "Guten Morgen zusammen, heute steigen wir in die Vektorräume ein."),
            (95, "Ein Vektorraum ist erst mal nur eine Menge mit zwei Verknüpfungen, Addition und Skalarmultiplikation."),
            (410, "Die Axiome stehen im Skript auf Seite eins, die müssen Sie nicht auswendig können."),
            (1260, "Jetzt der wichtigste Begriff heute: lineare Unabhängigkeit."),
            (1320, "Die einzige Linearkombination, die null ergibt, ist die triviale."),
            (2415, "Eine Basis ist ein linear unabhängiges Erzeugendensystem."),
            (2880, "Alle Basen haben gleich viele Elemente, das nennen wir Dimension."),
            (4020, "Das Austauschverfahren kommt garantiert in der Klausur dran."),
            (5220, "Nächste Woche geht es mit linearen Abbildungen weiter."),
        ],
        "notes": """# VL01 Vektorräume und Basen

Einführung in Vektorräume: Definition, lineare Unabhängigkeit, Basis und Dimension. [00:00:12]

## Themen

### Vektorräume
- Ein Vektorraum ist eine Menge $V$ mit Addition und Skalarmultiplikation über einem Körper $K$ [00:01:35] [LA_Skript S. 1]
- Die Axiome stehen im Skript und müssen nicht auswendig gelernt werden [00:06:50] [LA_Skript S. 1]

### Lineare Unabhängigkeit
- $v_1, \\dots, v_n$ sind linear unabhängig, wenn nur die triviale Linearkombination null ergibt [00:21:00] [LA_Skript S. 2]

$$
a_1 v_1 + \\dots + a_n v_n = 0 \\;\\Rightarrow\\; a_1 = \\dots = a_n = 0
$$

### Basis und Dimension
- Eine Basis ist ein linear unabhängiges Erzeugendensystem [00:40:15] [LA_Skript S. 2]
- Alle Basen eines Vektorraums sind gleich groß – diese Zahl ist die Dimension $\\dim V$ [00:48:00] [LA_Skript S. 2]

## Hinweise des Dozenten
- Das **Austauschverfahren** kommt „garantiert in der Klausur“ [01:07:00]

## Nicht im Skript
- Ausblick: Nächste Woche lineare Abbildungen [01:27:00]

## Offene Punkte
- Keine
""",
        "glossary": [
            ("Vektorraum", "Begriff", "Menge $V$ mit Addition und Skalarmultiplikation über einem Körper $K$, "
             "die die Vektorraumaxiome erfüllt.", "", ["00:01:35"], ["LA_Skript S. 1"]),
            ("Lineare Unabhängigkeit", "Begriff", "Vektoren sind linear unabhängig, wenn nur die triviale "
             "Linearkombination den Nullvektor ergibt.", "a_1 v_1 + \\dots + a_n v_n = 0 \\Rightarrow a_i = 0",
             ["00:21:00"], ["LA_Skript S. 2"]),
            ("Basis", "Begriff", "Linear unabhängiges Erzeugendensystem eines Vektorraums.", "",
             ["00:40:15"], ["LA_Skript S. 2"]),
            ("Dimension", "Begriff", "Anzahl der Elemente einer (jeder) Basis, geschrieben $\\dim V$.", "",
             ["00:48:00"], ["LA_Skript S. 2"]),
        ],
    },
    {
        "title": "VL02 Eigenwerte und Diagonalisierung",
        "file": "VL02 Eigenwerte und Diagonalisierung.mp4",
        "duration": 5100,
        "segments": [
            (20, "Heute geht es um Eigenwerte, eines der wichtigsten Themen des Semesters."),
            (300, "Ein Eigenvektor wird von der Matrix nur gestreckt, nicht gedreht."),
            (1500, "Die Eigenwerte finden wir über das charakteristische Polynom."),
            (1560, "Also Determinante von A minus Lambda mal Einheitsmatrix gleich null setzen."),
            (3000, "Diagonalisierbar heißt: Es gibt eine Basis aus Eigenvektoren."),
            (3900, "Achtung, typischer Fehler: Die Reihenfolge in S und D muss zusammenpassen."),
            (4980, "Übungsblatt drei ist ab heute online."),
        ],
        "notes": """# VL02 Eigenwerte und Diagonalisierung

Eigenwerte und Eigenvektoren, das charakteristische Polynom und Diagonalisierbarkeit. [00:00:20]

## Themen

### Eigenwerte und Eigenvektoren
- $\\lambda$ ist Eigenwert von $A$, wenn es $v \\neq 0$ gibt mit $A v = \\lambda v$ [00:05:00] [LA_Skript S. 3]
- Anschaulich: Ein Eigenvektor wird nur gestreckt, nicht gedreht [00:05:00]

### Charakteristisches Polynom
- Eigenwerte sind die Nullstellen von $\\det(A - \\lambda E)$ [00:25:00] [LA_Skript S. 3]

$$
\\chi_A(\\lambda) = \\det(A - \\lambda E) = 0
$$

### Diagonalisierbarkeit
- $A$ ist diagonalisierbar genau dann, wenn es eine Basis aus Eigenvektoren gibt [00:50:00] [LA_Skript S. 4]
- Dann gilt $A = S D S^{-1}$ mit Diagonalmatrix $D$ [00:50:00] [LA_Skript S. 4]

## Hinweise des Dozenten
- Typischer Fehler: Die Reihenfolge der Eigenvektoren in $S$ muss zu den Eigenwerten in $D$ passen [01:05:00]
- Übungsblatt 3 ist online [01:23:00]

## Nicht im Skript
- Keine

## Offene Punkte
- Keine
""",
        "glossary": [
            ("Eigenwert", "Begriff", "Zahl $\\lambda$, für die es einen Vektor $v \\neq 0$ mit $A v = \\lambda v$ gibt.",
             "A v = \\lambda v", ["00:05:00"], ["LA_Skript S. 3"]),
            ("Charakteristisches Polynom", "Formel", "Polynom, dessen Nullstellen genau die Eigenwerte von $A$ sind.",
             "\\chi_A(\\lambda) = \\det(A - \\lambda E)", ["00:25:00"], ["LA_Skript S. 3"]),
            ("Diagonalisierbarkeit", "Satz", "$A$ ist genau dann diagonalisierbar, wenn es eine Basis aus "
             "Eigenvektoren gibt.", "A = S D S^{-1}", ["00:50:00"], ["LA_Skript S. 4"]),
            ("Basis", "Begriff", "Eine Basis aus Eigenvektoren macht $A$ diagonalisierbar.", "",
             ["00:50:00"], ["LA_Skript S. 4"]),
        ],
    },
]


def seed_if_empty(db: Database) -> None:
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0]:
            return
        module_id = conn.execute(
            "INSERT INTO modules (name, created_at) VALUES (?, ?)", (MODULE, now())
        ).lastrowid
        script_id = conn.execute(
            "INSERT INTO scripts (module_id, filename, kuerzel, sha256, page_count, created_at)"
            " VALUES (?, ?, ?, 'beispiel', ?, ?)",
            (module_id, "LA_Skript.pdf", KUERZEL, len(PAGES), now()),
        ).lastrowid
        conn.executemany(
            "INSERT INTO pages (script_id, page_index, label, text) VALUES (?, ?, ?, ?)",
            [(script_id, i, label, text) for i, (label, text) in enumerate(PAGES)],
        )
        pages_json = json.dumps([[KUERZEL, label] for label, _ in PAGES])
        for lec in LECTURES:
            segments = [
                {"start": float(t), "end": float(t + 8), "text": text} for t, text in lec["segments"]
            ]
            lecture_id = conn.execute(
                "INSERT INTO lectures (module_id, title, source_filename, duration_sec, segments_json,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (module_id, lec["title"], lec["file"], lec["duration"], json.dumps(segments), now()),
            ).lastrowid
            notes_job = conn.execute(
                "INSERT INTO jobs (lecture_id, kind, status, model, request_json, pages_json,"
                " input_tokens_est, cost_est_usd, notes_md, warnings_json, created_at, updated_at)"
                " VALUES (?, 'notes', 'done', 'Beispiel', '{}', ?, 0, 0, ?, '[]', ?, ?)",
                (lecture_id, pages_json, lec["notes"], now(), now()),
            ).lastrowid
            glossary_job = conn.execute(
                "INSERT INTO jobs (lecture_id, kind, source_job_id, status, model, request_json,"
                " pages_json, input_tokens_est, cost_est_usd, created_at, updated_at)"
                " VALUES (?, 'glossary', ?, 'done', 'Beispiel', '{}', ?, 0, 0, ?, ?)",
                (lecture_id, notes_job, pages_json, now(), now()),
            ).lastrowid
            conn.executemany(
                "INSERT INTO glossary_entries (module_id, lecture_id, job_id, term, norm, kind,"
                " definition, formula, timestamps_json, pages_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(module_id, lecture_id, glossary_job, term, glossary.normalize(term), kind, definition,
                  formula, json.dumps(ts), json.dumps(pg))
                 for term, kind, definition, formula, ts, pg in lec["glossary"]],
            )
