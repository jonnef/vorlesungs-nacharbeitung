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

> [!example]- Beispiel: Sind (1, 2) und (2, 4) linear unabhängig? (eigenes Beispiel)
> Ansatz $a_1 (1, 2) + a_2 (2, 4) = (0, 0)$ liefert $a_1 + 2a_2 = 0$ und $2a_1 + 4a_2 = 0$.
>
> Die zweite Gleichung ist das Doppelte der ersten, also gibt es nichttriviale Lösungen, z. B. $a_1 = 2,\\ a_2 = -1$.
>
> **Ergebnis:** linear abhängig – der zweite Vektor ist das Doppelte des ersten.

### Basis und Dimension
- Eine Basis ist ein linear unabhängiges Erzeugendensystem [00:40:15] [LA_Skript S. 2]
- Alle Basen eines Vektorraums sind gleich groß – diese Zahl ist die Dimension $\\dim V$ [00:48:00] [LA_Skript S. 2]

> [!diagram]+ Vom Vektorraum zur Dimension
> ```mermaid
> flowchart LR
>   V["Vektorraum V"] --> E["Erzeugendensystem"]
>   E -->|"linear unabhängig"| B["Basis"]
>   B -->|"Anzahl der Elemente"| D["Dimension dim V"]
> ```

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

> [!example]- Beispiel: Eigenwerte einer 2×2-Matrix (eigenes Beispiel)
> $A = \\begin{pmatrix} 2 & 1 \\\\ 1 & 2 \\end{pmatrix}$, also
> $\\det(A - \\lambda E) = (2-\\lambda)^2 - 1 = \\lambda^2 - 4\\lambda + 3$.
>
> Nullstellen: $\\lambda_1 = 1$, $\\lambda_2 = 3$.

> [!proof]- Herleitung: Warum $\\det(A - \\lambda E) = 0$?
> $A v = \\lambda v \\iff (A - \\lambda E) v = 0$.
>
> Es gibt genau dann ein $v \\neq 0$, wenn $A - \\lambda E$ nicht invertierbar ist, also wenn $\\det(A - \\lambda E) = 0$. [00:26:00]

### Diagonalisierbarkeit
- $A$ ist diagonalisierbar genau dann, wenn es eine Basis aus Eigenvektoren gibt [00:50:00] [LA_Skript S. 4]
- Dann gilt $A = S D S^{-1}$ mit Diagonalmatrix $D$ [00:50:00] [LA_Skript S. 4]

> [!diagram]+ Ablauf der Diagonalisierung
> ```mermaid
> flowchart TD
>   A["Matrix A"] --> P["charakteristisches Polynom aufstellen"]
>   P --> L["Eigenwerte als Nullstellen"]
>   L --> V["Eigenvektoren je Eigenwert"]
>   V --> Q{"Basis aus Eigenvektoren?"}
>   Q -->|"ja"| D["A = S D S⁻¹"]
>   Q -->|"nein"| N["nicht diagonalisierbar"]
> ```

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


EXAM = """# Klausurvorbereitung – Beispiel: Lineare Algebra

Im Mittelpunkt stehen Basis und Dimension sowie Eigenwerte und Diagonalisierung. Wer die
Definitionen sicher beherrscht und das Austauschverfahren sowie das charakteristische Polynom
rechnen kann, ist gut vorbereitet.

## Vom Dozenten ausdrücklich genannt
- Das **Austauschverfahren** kommt „garantiert in der Klausur“ [V1 01:07:00]
- Eigenwerte sind „eines der wichtigsten Themen des Semesters“ [V2 00:00:20]

## Kernthemen

### 1. Basis und Dimension – **hoch**
*Vom Dozenten angekündigt (Austauschverfahren), Grundlage für alle späteren Themen.*
- Lineare Unabhängigkeit prüfen: nur die triviale Linearkombination ergibt $0$ [V1 00:21:00] [LA_Skript S. 2]
- Basis bestimmen und Dimension angeben [V1 00:40:15] [LA_Skript S. 2]

### 2. Eigenwerte und charakteristisches Polynom – **hoch**
*Vom Dozenten als besonders wichtig bezeichnet.*
- Eigenwerte als Nullstellen berechnen [V2 00:25:00] [LA_Skript S. 3]

$$
\\chi_A(\\lambda) = \\det(A - \\lambda E) = 0
$$

### 3. Diagonalisierung – **mittel**
*Baut auf Eigenwerten auf; typischer Fehler angesprochen.*
- $A = S D S^{-1}$, wenn es eine Basis aus Eigenvektoren gibt [V2 00:50:00] [LA_Skript S. 4]

## Typische Fehler
- Reihenfolge der Eigenvektoren in $S$ passt nicht zu den Eigenwerten in $D$ [V2 01:05:00]

## Übungsaufgaben im Stil des Dozenten

### Aufgabe 1: Lineare Unabhängigkeit
*Schwierigkeit: leicht · Quelle: [V1 00:21:00] [LA_Skript S. 2]*

Prüfen Sie, ob die Vektoren $(1, 0, 1)$, $(0, 1, 1)$ und $(1, 1, 2)$ linear unabhängig sind. Begründen Sie Ihre Antwort.

> [!hint]- Tipp
> Schauen Sie, ob sich ein Vektor als Summe der anderen schreiben lässt.

> [!solution]- Musterlösung
> $(1, 0, 1) + (0, 1, 1) = (1, 1, 2)$, also ist $1 \\cdot v_1 + 1 \\cdot v_2 - 1 \\cdot v_3 = 0$ eine nichttriviale Linearkombination.
>
> **Ergebnis:** linear abhängig. [V1 00:21:00]

### Aufgabe 2: Eigenwerte und Diagonalisierung
*Schwierigkeit: mittel · Quelle: [V2 00:25:00] [V2 00:50:00]*

Gegeben ist $A = \\begin{pmatrix} 4 & 1 \\\\ 2 & 3 \\end{pmatrix}$.

a) Berechnen Sie die Eigenwerte von $A$.

b) Ist $A$ diagonalisierbar? Begründen Sie.

> [!solution]- Musterlösung
> a) $\\det(A - \\lambda E) = (4-\\lambda)(3-\\lambda) - 2 = \\lambda^2 - 7\\lambda + 10 = (\\lambda - 2)(\\lambda - 5)$, also $\\lambda_1 = 2$, $\\lambda_2 = 5$. [V2 00:25:00]
>
> b) Zwei verschiedene Eigenwerte einer $2 \\times 2$-Matrix liefern zwei linear unabhängige Eigenvektoren – es gibt eine Basis aus Eigenvektoren, $A$ ist diagonalisierbar. [V2 00:50:00]

## Kurzfragen

> [!question]- Warum haben alle Basen eines Vektorraums gleich viele Elemente?
> Das folgt aus dem Austauschverfahren: Man kann Basisvektoren schrittweise austauschen, ohne die Anzahl zu ändern. Diese Anzahl ist die Dimension. [V1 00:48:00]

> [!question]- Worauf muss man bei $S$ und $D$ achten?
> Die $i$-te Spalte von $S$ muss ein Eigenvektor zum $i$-ten Diagonaleintrag von $D$ sein. [V2 01:05:00]

## Checkliste
- [ ] Definition lineare Unabhängigkeit
- [ ] Austauschverfahren an einem Beispiel gerechnet
- [ ] Charakteristisches Polynom einer $3 \\times 3$-Matrix aufgestellt
- [ ] Eine Matrix vollständig diagonalisiert
"""


def seed_exam_if_missing(db: Database) -> None:
    """Beispiel-Klausurvorbereitung (auch für Vorschau-Datenbanken, die schon vorher befüllt wurden)."""
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'exam'").fetchone()[0]:
            return
        rows = conn.execute(
            "SELECT l.id AS lecture_id, MAX(j.id) AS job_id FROM lectures l"
            " JOIN jobs j ON j.lecture_id = l.id AND j.kind = 'notes'"
            " GROUP BY l.id ORDER BY l.source_filename"
        ).fetchall()
        if not rows:
            return
        conn.execute(
            "INSERT INTO jobs (lecture_id, kind, source_ids, status, model, request_json, pages_json,"
            " input_tokens_est, cost_est_usd, notes_md, warnings_json, created_at, updated_at)"
            " VALUES (?, 'exam', ?, 'done', 'Beispiel', '{}', '[]', 0, 0, ?, '[]', ?, ?)",
            (rows[-1]["lecture_id"], json.dumps([[r["lecture_id"], r["job_id"]] for r in rows]), EXAM, now(), now()),
        )


# (Vorlesung, Art, Thema, Zitat aus dem Beispiel-Transkript, Sekunden, Seiten, Erläuterung)
HINTS = [
    (0, "nicht_klausurrelevant", "Vektorraumaxiome",
     "Die Axiome stehen im Skript auf Seite eins, die müssen Sie nicht auswendig können.", 410,
     ["LA_Skript S. 1"], "Die einzelnen Axiome müssen nicht auswendig gelernt werden."),
    (0, "klausurrelevant", "Austauschverfahren",
     "Das Austauschverfahren kommt garantiert in der Klausur dran.", 4020,
     ["LA_Skript S. 2"], "Das Austauschverfahren sollte man an einem Beispiel sicher durchrechnen können."),
    (1, "typischer_fehler", "Diagonalisierung",
     "Achtung, typischer Fehler: Die Reihenfolge in S und D muss zusammenpassen.", 3900,
     ["LA_Skript S. 4"], "Die Eigenvektoren in S müssen in derselben Reihenfolge stehen wie die Eigenwerte in D."),
]


def seed_hints_if_missing(db: Database) -> None:
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'hints'").fetchone()[0]:
            return
        rows = conn.execute(
            "SELECT l.id AS lecture_id, l.module_id, MAX(j.id) AS notes_job_id FROM lectures l"
            " JOIN jobs j ON j.lecture_id = l.id AND j.kind = 'notes' GROUP BY l.id ORDER BY l.source_filename"
        ).fetchall()
        if not rows:
            return
        job_ids = []
        for r in rows:
            job_ids.append(conn.execute(
                "INSERT INTO jobs (lecture_id, kind, source_job_id, status, model, request_json, pages_json,"
                " input_tokens_est, cost_est_usd, created_at, updated_at)"
                " VALUES (?, 'hints', ?, 'done', 'Beispiel', '{}', '[]', 0, 0, ?, ?)",
                (r["lecture_id"], r["notes_job_id"], now(), now()),
            ).lastrowid)
        for index, kind, topic, quote, seconds, pages, note in HINTS:
            if index < len(rows):
                r = rows[index]
                h, m, s = seconds // 3600, seconds % 3600 // 60, seconds % 60
                conn.execute(
                    "INSERT INTO exam_hints (module_id, lecture_id, job_id, kind, topic, quote, timestamp, seconds,"
                    " pages_json, note, verified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (r["module_id"], r["lecture_id"], job_ids[index], kind, topic, quote,
                     f"{h:02d}:{m:02d}:{s:02d}", seconds, json.dumps(pages), note),
                )


def _pm(a, b, c, d) -> str:
    return rf"\begin{{pmatrix}} {a} & {b} \\ {c} & {d} \end{{pmatrix}}"


def _vec(a, b) -> str:
    return rf"\begin{{pmatrix}} {a} \\ {b} \end{{pmatrix}}"


def _eigen_task(a, b, c, d, poly, factored, l1, l2) -> dict:
    lam = r"\lambda"
    return {
        "front": f"Berechnen Sie die Eigenwerte der Matrix $$A = {_pm(a, b, c, d)}.$$",
        "back": (f"Charakteristisches Polynom aufstellen:\n\n"
                 f"$$\\det(A - {lam} E) = \\det {_pm(f'{a} - {lam}', b, c, f'{d} - {lam}')}"
                 f" = ({a} - {lam})({d} - {lam}) - {b * c}$$\n\n"
                 f"Ausmultiplizieren und faktorisieren: $${poly} = {factored}$$\n\n"
                 f"Nullstellen ablesen: ${lam}_1 = {l1}$, ${lam}_2 = {l2}$."),
        "result": f"${lam}_1 = {l1},\\ {lam}_2 = {l2}$",
    }


def _independence_task(v, w, det, independent, note) -> dict:
    verdict = "linear unabhängig" if independent else "linear abhängig"
    return {
        "front": f"Sind die Vektoren ${_vec(*v)}$ und ${_vec(*w)}$ linear unabhängig?",
        "back": (f"Zwei Vektoren im $\\mathbb{{R}}^2$ sind genau dann linear unabhängig, wenn die Determinante "
                 f"der Matrix aus ihnen nicht null ist:\n\n"
                 f"$$\\det {_pm(v[0], w[0], v[1], w[1])} = ({v[0]}) \\cdot ({w[1]}) - ({w[0]}) \\cdot ({v[1]})"
                 f" = {det}$$\n\n{note}"),
        "result": f"{verdict} (Determinante {det})",
    }


# (Vorlesung, Art, Thema, Taschenrechner, Varianten, Zeitstempel, Seiten)
CARDS = [
    (0, "karte", "Lineare Unabhängigkeit", False, [{
        "front": r"Wann heißen Vektoren $v_1, \dots, v_n$ **linear unabhängig**?",
        "back": r"Wenn aus $a_1 v_1 + \dots + a_n v_n = 0$ folgt, dass alle $a_i = 0$ sind – nur die triviale "
                "Linearkombination ergibt den Nullvektor.", "result": ""}],
     ["00:21:00", "00:22:00"], ["LA_Skript S. 2"]),
    (0, "karte", "Basis und Dimension", False, [{
        "front": "Was ist eine **Basis** eines Vektorraums, und was ist seine **Dimension**?",
        "back": "Eine Basis ist ein linear unabhängiges Erzeugendensystem. Alle Basen haben gleich viele Elemente; "
                "diese Anzahl ist die Dimension.", "result": ""}],
     ["00:40:15", "00:48:00"], ["LA_Skript S. 2"]),
    (0, "aufgabe", "Lineare Unabhängigkeit prüfen", False, [
        _independence_task((1, 2), (3, 6), 0, False, "Die Determinante ist $0$, also sind die Vektoren linear "
                           "abhängig – tatsächlich ist der zweite das Dreifache des ersten."),
        _independence_task((1, 2), (2, 5), 1, True, r"Die Determinante ist $1 \neq 0$, also sind die Vektoren "
                           r"linear unabhängig (und bilden eine Basis des $\mathbb{R}^2$)."),
        _independence_task((2, -1), (-4, 2), 0, False, "Die Determinante ist $0$, also sind die Vektoren linear "
                           "abhängig – der zweite ist das $(-2)$-Fache des ersten."),
    ], ["00:22:00"], ["LA_Skript S. 2"]),
    (1, "karte", "Eigenwerte bestimmen", False, [{
        "front": "Wie bestimmt man die **Eigenwerte** einer quadratischen Matrix $A$?",
        "back": r"Als Nullstellen des charakteristischen Polynoms: $\det(A - \lambda E) = 0$ setzen und nach "
                r"$\lambda$ auflösen.", "result": ""}],
     ["00:25:00", "00:26:00"], ["LA_Skript S. 3"]),
    (1, "aufgabe", "Eigenwerte einer 2×2-Matrix", False, [
        _eigen_task(2, 1, 1, 2, r"\lambda^2 - 4\lambda + 3", r"(\lambda - 1)(\lambda - 3)", 1, 3),
        _eigen_task(4, 1, 2, 3, r"\lambda^2 - 7\lambda + 10", r"(\lambda - 2)(\lambda - 5)", 2, 5),
        _eigen_task(1, 2, 2, 1, r"\lambda^2 - 2\lambda - 3", r"(\lambda + 1)(\lambda - 3)", -1, 3),
    ], ["00:25:00", "00:26:00"], ["LA_Skript S. 3"]),
    (1, "aufgabe", "Eigenwerte mit Wurzeln", True, [
        {"front": f"Berechnen Sie die Eigenwerte von $$A = {_pm(1, 2, 3, 1)}$$ auf zwei Nachkommastellen.",
         "back": r"$$\det(A - \lambda E) = (1 - \lambda)^2 - 6 = 0 \iff 1 - \lambda = \pm\sqrt{6}$$"
                 "\n\n" r"Also $\lambda = 1 \pm \sqrt{6} \approx 1 \pm 2{,}449$.",
         "result": r"$\lambda_1 \approx 3{,}45,\ \lambda_2 \approx -1{,}45$"},
        {"front": f"Berechnen Sie die Eigenwerte von $$A = {_pm(2, 1, 3, 2)}$$ auf zwei Nachkommastellen.",
         "back": r"$$\det(A - \lambda E) = (2 - \lambda)^2 - 3 = 0 \iff 2 - \lambda = \pm\sqrt{3}$$"
                 "\n\n" r"Also $\lambda = 2 \pm \sqrt{3} \approx 2 \pm 1{,}732$.",
         "result": r"$\lambda_1 \approx 3{,}73,\ \lambda_2 \approx 0{,}27$"},
    ], ["00:26:00"], ["LA_Skript S. 3"]),
    (1, "karte", "Diagonalisierbarkeit", False, [{
        "front": r"Wann ist eine Matrix $A$ **diagonalisierbar**, und worauf muss man bei $A = S D S^{-1}$ achten?",
        "back": "Genau dann, wenn es eine Basis aus Eigenvektoren gibt. Die Eigenvektoren in $S$ müssen in derselben "
                "Reihenfolge stehen wie die zugehörigen Eigenwerte in $D$ – ein typischer Fehler.", "result": ""}],
     ["00:50:00", "01:05:00"], ["LA_Skript S. 4"]),
]


def seed_cards_if_missing(db: Database) -> None:
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'cards'").fetchone()[0]:
            return
        rows = conn.execute(
            "SELECT l.id AS lecture_id, l.module_id, MAX(j.id) AS notes_job_id FROM lectures l"
            " JOIN jobs j ON j.lecture_id = l.id AND j.kind = 'notes' GROUP BY l.id ORDER BY l.source_filename"
        ).fetchall()
        if not rows:
            return
        job_ids = [conn.execute(
            "INSERT INTO jobs (lecture_id, kind, source_job_id, status, model, request_json, pages_json,"
            " input_tokens_est, cost_est_usd, created_at, updated_at)"
            " VALUES (?, 'cards', ?, 'done', 'Beispiel', '{}', '[]', 0, 0, ?, ?)",
            (r["lecture_id"], r["notes_job_id"], now(), now())).lastrowid for r in rows]
        for index, kind, topic, calculator, variants, timestamps, pages in CARDS:
            if index < len(rows):
                r = rows[index]
                conn.execute(
                    "INSERT INTO cards (module_id, lecture_id, job_id, kind, topic, calculator, variants_json, norm,"
                    " timestamps_json, pages_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (r["module_id"], r["lecture_id"], job_ids[index], kind, topic, int(calculator),
                     json.dumps(variants), glossary.normalize(variants[0]["front"]), json.dumps(timestamps),
                     json.dumps(pages), now()),
                )


# Beispiel für eine automatisch aussortierte Karte (Vorlesung, Vorderseite, Rückseite, Zeitstempel, Grund)
SORTED_OUT_CARD = (1, "Ab wann ist Übungsblatt 3 online?", "Ab dem Tag der Vorlesung.", "01:23:00",
                   "Organisatorisch: Termin zum Übungsbetrieb, kein Fachinhalt.")


def mark_cards_checked(db: Database) -> None:
    """Vorschau: keine Prüfung im Hintergrund – Beispielkarten gelten als geprüft, eine ist aussortiert."""
    with db.connect() as conn:
        conn.execute("UPDATE cards SET checked_at = ? WHERE checked_at IS NULL", (now(),))
        if conn.execute("SELECT COUNT(*) FROM cards WHERE archive_reason IS NOT NULL").fetchone()[0]:
            return
        index, front, back, ts, reason = SORTED_OUT_CARD
        rows = conn.execute("SELECT id, module_id FROM lectures ORDER BY source_filename").fetchall()
        if index >= len(rows):
            return
        conn.execute(
            "INSERT INTO cards (module_id, lecture_id, kind, topic, calculator, variants_json, norm, timestamps_json,"
            " pages_json, suspended, checked_at, archive_reason, created_at)"
            " VALUES (?, ?, 'karte', 'Übungsbetrieb', 0, ?, ?, ?, '[]', 1, ?, ?, ?)",
            (rows[index]["module_id"], rows[index]["id"], json.dumps([{"front": front, "back": back, "result": ""}]),
             glossary.normalize(front), json.dumps([ts]), now(), reason, now()))


# Concept Map aus den Glossarbegriffen: (Begriff, Thema) und (von, nach, Art, Beschriftung)
CONCEPT_NODES = [
    ("Vektorraum", "Vektorräume"), ("Lineare Unabhängigkeit", "Vektorräume"), ("Basis", "Vektorräume"),
    ("Dimension", "Vektorräume"), ("Eigenwert", "Eigenwerte"), ("Charakteristisches Polynom", "Eigenwerte"),
    ("Diagonalisierbarkeit", "Eigenwerte"),
]
CONCEPT_EDGES = [
    ("Vektorraum", "Lineare Unabhängigkeit", "voraussetzung", "Rahmen für"),
    ("Lineare Unabhängigkeit", "Basis", "voraussetzung", "Bedingung für eine"),
    ("Basis", "Dimension", "voraussetzung", "Anzahl der Elemente ist die"),
    ("Charakteristisches Polynom", "Eigenwert", "verwendet", "Nullstellen liefern die"),
    ("Eigenwert", "Diagonalisierbarkeit", "voraussetzung", "Eigenvektoren entscheiden über"),
    ("Basis", "Diagonalisierbarkeit", "voraussetzung", "aus Eigenvektoren bedeutet"),
    ("Eigenwert", "Lineare Unabhängigkeit", "verwandt", "Eigenvektoren zu verschiedenen Eigenwerten sind"),
]


def seed_conceptmap_if_missing(db: Database) -> None:
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'conceptmap'").fetchone()[0]:
            return
        rows = conn.execute(
            "SELECT g.lecture_id, MAX(g.job_id) AS job_id FROM glossary_entries g JOIN lectures l ON l.id = g.lecture_id"
            " GROUP BY g.lecture_id ORDER BY MIN(l.source_filename)").fetchall()
        if not rows:
            return
        data = {"nodes": [{"norm": glossary.normalize(t), "group": g} for t, g in CONCEPT_NODES],
                "edges": [{"from": glossary.normalize(a), "to": glossary.normalize(b), "kind": k, "label": label}
                          for a, b, k, label in CONCEPT_EDGES]}
        conn.execute(
            "INSERT INTO jobs (lecture_id, kind, source_ids, status, model, request_json, pages_json,"
            " input_tokens_est, cost_est_usd, notes_md, warnings_json, created_at, updated_at)"
            " VALUES (?, 'conceptmap', ?, 'done', 'Beispiel', '{}', '[]', 0, 0, ?, '[]', ?, ?)",
            (rows[-1]["lecture_id"], json.dumps([[r["lecture_id"], r["job_id"]] for r in rows]),
             json.dumps(data, ensure_ascii=False), now(), now()),
        )


def seed_if_empty(db: Database) -> None:
    try:
        _seed_module(db)
    finally:
        seed_hints_if_missing(db)
        seed_exam_if_missing(db)
        seed_cards_if_missing(db)
        seed_conceptmap_if_missing(db)
        mark_cards_checked(db)
        refresh_sample_texts(db)


def refresh_sample_texts(db: Database) -> None:
    """Bringt Notizen und Klausurvorbereitung bestehender Vorschau-Datenbanken auf den aktuellen Stand."""
    with db.connect() as conn:
        for lec in LECTURES:
            conn.execute(
                "UPDATE jobs SET notes_md = ? WHERE kind = 'notes' AND model = 'Beispiel'"
                " AND lecture_id IN (SELECT id FROM lectures WHERE title = ?)",
                (lec["notes"], lec["title"]),
            )
        conn.execute("UPDATE jobs SET notes_md = ? WHERE kind = 'exam' AND model = 'Beispiel'", (EXAM,))


def _seed_module(db: Database) -> None:
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
