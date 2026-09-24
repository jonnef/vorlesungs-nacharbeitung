"""Auswahl der zur Vorlesung passenden Skriptseiten (BM25, ohne externe Abhängigkeiten).

Passen alle Seiten des Moduls ins Token-Budget, werden alle mitgeschickt. Sonst wird das
Transkript in Abschnitte zerlegt und für jeden Abschnitt die ähnlichsten Seiten gewählt,
damit auch Themen vom Ende der Vorlesung Kontext bekommen.
"""

import math
import re
from collections import Counter

from .transcript import merge_segments

STOPWORDS = set(
    """
    aber alle allem allen aller alles als also am an ander andere anderem anderen anderer anderes
    auch auf aus bei bin bis bist da damit dann das dass dein deine dem den denn der des dessen
    deshalb die dies diese diesem diesen dieser dieses doch dort du durch ein eine einem einen
    einer eines einfach einmal er es etwa etwas euch euer für gegen genau gibt habe haben hat
    hier hin hinter ich ihm ihn ihnen ihr ihre im immer in ist ja jede jedem jeden jeder jedes
    jetzt kann kein keine können könnte machen man mal mehr mein meine mit muss müssen nach
    nicht nichts noch nun nur ob oder ohne okay schon sehr sein seine sich sie sind so solche
    soll sollen sondern sozusagen über um und uns unser unter viel vom von vor wann war waren
    warum was weil weiter welche wenn wer werden wie wieder will wir wird wo wollen würde zu
    zum zur zwar zwischen also halt eben quasi genau ähm äh hm the and of to in is for that
    """.split()
)

TOKEN_RE = re.compile(r"[a-zäöüß0-9]{3,}")


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def approx_tokens(text: str) -> int:
    # Grobe Schätzung nur für die Auswahl; die echte Zählung macht count_tokens.
    return len(text) // 3 + 20


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avg = (sum(self.lens) / len(docs)) if docs else 0.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        q = Counter(query)
        out = []
        for tf, length in zip(self.tfs, self.lens):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * length / (self.avg or 1))
            for term, qf in q.items():
                f = tf.get(term)
                if f:
                    s += self.idf[term] * f * (self.k1 + 1) / (f + norm) * min(qf, 3)
            out.append(s)
        return out


def select_pages(
    pages: list[dict],
    segments: list[dict],
    token_budget: int,
    chunk_sec: float = 300.0,
    per_chunk: int = 4,
) -> list[dict]:
    """Wählt Seiten (dicts mit mindestens `id` und `text`) passend zum Transkript aus.

    Rückgabe in Originalreihenfolge (Skript, Seite), damit Claude den Aufbau des Skripts sieht.
    """
    pages = [p for p in pages if p["text"].strip()]
    if not pages:
        return []
    total = sum(approx_tokens(p["text"]) for p in pages)
    if total <= token_budget:
        return pages

    bm25 = BM25([tokenize(p["text"]) for p in pages])
    chunks = merge_segments(segments, block_sec=chunk_sec)
    ranked_rounds: list[list[int]] = []
    for chunk in chunks:
        scores = bm25.scores(tokenize(chunk["text"]))
        top = sorted(range(len(pages)), key=lambda i: scores[i], reverse=True)[:per_chunk]
        ranked_rounds.append([i for i in top if scores[i] > 0])

    # Reihum aus jedem Abschnitt die nächstbeste Seite nehmen, bis das Budget voll ist.
    chosen: list[int] = []
    used = 0
    for rank in range(per_chunk):
        for top in ranked_rounds:
            if rank < len(top) and top[rank] not in chosen:
                cost = approx_tokens(pages[top[rank]]["text"])
                if used + cost <= token_budget:
                    chosen.append(top[rank])
                    used += cost
    return [pages[i] for i in sorted(chosen)]
