"""Multi-word expression (MWE) segmentation for the LSRD translator.

Dictionary entries such as 'buenos dias' or 'arbol de navidad' are signed as
one unit. PhraseMatcher merges consecutive tokens into one token when they form
a known phrase, using greedy longest-match (up to MAX_PHRASE_LEN tokens).

Merged token contract: the merged token is the ORIGINAL ``palabras.palabra_norm``
of the matching entry (e.g. 'buenos dias'; for an entry stored as
'abajo, debajo' it would be 'abajo, debajo'), so the translator's lookup
``palabra_norm = token`` finds it directly. Keys are derived from:
  - multi-word palabra_norm entries (parenthetical qualifiers stripped,
    'a, b' alternatives split into separate keys, single-word gender suffixes
    such as 'abogado, da' / 'actor, triz' ignored),
  - multi-word sinonimos_mapeo.sinonimo_norm values.
Input tokens must already be normalized (lowercase, no accents, no punctuation).
"""
import re
import sqlite3

MAX_PHRASE_LEN = 4
_PAREN = re.compile(r"\([^)]*\)?")


def _clean_key(part):
    """Normalize a dictionary fragment into a space-joined token key."""
    part = part.strip()
    if part.startswith("(") and not part.startswith("()"):
        # Entry that is entirely parenthetical: the content is the phrase.
        part = part.replace("(", " ").replace(")", " ")
    else:
        part = _PAREN.sub(" ", part)
    return " ".join(re.sub(r"[^\w\s]", " ", part).split())


def _keys_from_entry(norm):
    """Yield multi-word keys (2..MAX_PHRASE_LEN tokens) for one entry."""
    for part in norm.split(","):
        key = _clean_key(part)
        n = len(key.split())
        if 2 <= n <= MAX_PHRASE_LEN:
            yield key


class PhraseMatcher:
    def __init__(self, phrases=None):
        # key (space-joined tokens) -> palabra_norm to emit
        self.phrases = dict(phrases or {})
        self.max_len = max(
            (len(k.split()) for k in self.phrases), default=1
        )

    @classmethod
    def from_db(cls, db_path):
        phrases = {}
        con = sqlite3.connect(db_path)
        try:
            for norm, in con.execute("SELECT palabra_norm FROM palabras"):
                if not norm:
                    continue
                for key in _keys_from_entry(norm):
                    # An entry whose norm equals the key beats partial matches.
                    if norm == key or key not in phrases:
                        phrases[key] = norm
            rows = con.execute(
                "SELECT s.sinonimo_norm, p.palabra_norm FROM sinonimos_mapeo s "
                "JOIN palabras p ON p.id = s.palabra_id"
            )
            for syn, norm in rows:
                if not syn or not norm:
                    continue
                for key in _keys_from_entry(syn):
                    phrases.setdefault(key, norm)
        finally:
            con.close()
        return cls(phrases)

    def segment(self, tokens):
        """Greedy longest-match merge; returns a new list of tokens."""
        out, i, n = [], 0, len(tokens)
        while i < n:
            for size in range(min(self.max_len, MAX_PHRASE_LEN, n - i), 1, -1):
                key = " ".join(tokens[i:i + size])
                hit = self.phrases.get(key)
                if hit is not None:
                    out.append(hit)
                    i += size
                    break
            else:
                out.append(tokens[i])
                i += 1
        return out


if __name__ == "__main__":
    import os
    db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lsrd_dictionary.db")
    pm = PhraseMatcher.from_db(db)
    print(len(pm.phrases), "phrase keys")
    assert pm.segment(["buenos", "dias", "amigo"]) == ["buenos dias", "amigo"]
    assert pm.segment(["a", "traves", "de", "casa"])[0] == "a traves"
    assert pm.segment(["arbol", "de", "navidad"]) == ["arbol de navidad,"]  # stored norm has a trailing comma
    assert pm.segment(["el", "ser", "humano"]) == ["el", "ser humano,"]
    assert pm.segment(["la", "vega"]) == ["la vega"]
    assert pm.segment(["casa", "grande"]) == ["casa", "grande"]
    assert pm.segment([]) == []
    print("ok")
