"""Rule-based LSRD (Dominican Sign Language) clause reordering.

Conservative, data-driven word-order rules for Spanish -> LSRD gloss
sequences. Nothing here is a complete grammar of LSRD; only widely
documented patterns of Sign Languages of the Americas are applied.

Rules (applied independently to each clause):

1. TIME first: temporal words (ayer, hoy, manana, ...) move to the start
   of the clause, keeping their relative order.
2. NEGATION last: negation words (no, nunca, jamas, nada, ...) move to
   the end of the clause, keeping their relative order. (Rules 1-2 are the
   rules carried over unchanged from nlp_engine.reorder_grammar_lsrd.)
3. WH-QUESTION words last: when the input is a question ('?' or the
   inverted '¿' present), wh-words (que, quien, donde, cuando, como,
   cual, cuanto/a/s, "por que") move to the very end of the clause,
   after any negation.
4. QUANTITY after noun: a numeral/quantity that directly precedes a
   noun token (as detected by the optional ``nouns`` set) is kept after
   it. Only applied when the caller supplies a noun set, because
   nouns are not trivially detectable from the surface form.
5. CLAUSE splitting: text is split on commas, periods, semicolons,
   colons, exclamation and question marks so reordering never moves a
   word across a clause boundary (see split_clauses).

All rules should be validated with Deaf LSRD users before being relied on.

Tokens are expected to be lowercase, accent-free Spanish words, as produced
by nlp_engine. The module uses only the standard library.
"""

import re

# --- Rule data (Spanish word sets, matched against normalized tokens) ---

TIME_WORDS = {
    'ayer', 'hoy', 'manana', 'ahora', 'anoche', 'pasado', 'futuro',
    'lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado',
    'domingo', 'mes', 'ano',
}

NEGATION_WORDS = {'no', 'nunca', 'jamas', 'nada', 'ninguno', 'ninguna'}

# Single-token wh-words. 'por que' / 'porque' handled as a bigram below.
# Exposed so the integrator can stop dropping them as stopwords in questions.
QUESTION_WORDS = {
    'que', 'quien', 'quienes', 'donde', 'cuando', 'como', 'cual', 'cuales',
    'cuanto', 'cuanta', 'cuantos', 'cuantas',
    '¿por que?', 'por que', 'para que',
}

# Multi-token wh-expressions, matched before single words.
QUESTION_PHRASES = [('por', 'que'), ('para', 'que')]

QUANTITY_WORDS = {
    'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho',
    'nueve', 'diez', 'once', 'doce', 'veinte', 'treinta', 'cien',
    'mil', 'mucho', 'mucha', 'muchos', 'muchas', 'poco', 'poca',
    'pocos', 'pocas',
}

_CLAUSE_SPLIT_RE = re.compile(r'[,.;:!?¿¡\n]+')
_QUESTION_RE = re.compile(r'[?¿]')


def is_question_text(text):
    """True if the text contains '?' or the inverted '¿'."""
    return bool(_QUESTION_RE.search(text or ''))


def split_clauses(text):
    """Split raw text into clauses on , . ; : ! ? and newlines.

    Returns a list of non-empty stripped clause strings. A clause that
    belongs to a question keeps no marker; use split_clauses_flagged when
    per-clause question status is needed.
    """
    if not text:
        return []
    return [c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]


def split_clauses_flagged(text):
    """Like split_clauses but returns (clause, is_question) tuples.

    A clause is a question if it is terminated by '?' or starts with '¿'
    (or sits between '¿' and '?').
    """
    out = []
    if not text:
        return out
    in_question = False
    buf = []

    def flush(terminator):
        clause = ''.join(buf).strip()
        buf.clear()
        if clause:
            out.append((clause, in_question or terminator == '?'))

    for ch in text:
        if ch == '¿':
            flush('')
            in_question = True
        elif ch == '?':
            flush('?')
            in_question = False
        elif ch in ',.;:!\n':
            flush('')
        else:
            buf.append(ch)
    flush('')
    return out


def _extract_question_words(tokens):
    """Return (rest, wh) where wh keeps wh-words/phrases in original order."""
    rest, wh = [], []
    i = 0
    n = len(tokens)
    while i < n:
        if i + 1 < n and (tokens[i], tokens[i + 1]) in QUESTION_PHRASES:
            wh.extend(tokens[i:i + 2])
            i += 2
        elif tokens[i] in QUESTION_WORDS:
            wh.append(tokens[i])
            i += 1
        else:
            rest.append(tokens[i])
            i += 1
    return rest, wh


def _quantity_after_noun(tokens, nouns):
    """Swap 'QUANTITY NOUN' to 'NOUN QUANTITY' when NOUN is a known noun."""
    if not nouns:
        return list(tokens)
    out = list(tokens)
    i = 0
    while i < len(out) - 1:
        if out[i] in QUANTITY_WORDS and out[i + 1] in nouns \
                and out[i + 1] not in QUANTITY_WORDS:
            out[i], out[i + 1] = out[i + 1], out[i]
            i += 2
        else:
            i += 1
    return out


def reorder(tokens, is_question=False, nouns=None):
    """Reorder one clause of tokens into LSRD order.

    Order: TIME + other tokens + NEGATION + WH-words (questions only).
    Relative order inside each group is preserved. ``nouns`` is an optional
    set of known noun tokens enabling the quantity-after-noun rule.
    """
    if not tokens:
        return []
    tokens = list(tokens)
    wh = []
    if is_question:
        tokens, wh = _extract_question_words(tokens)

    time_t, neg_t, other = [], [], []
    for t in tokens:
        if t in TIME_WORDS:
            time_t.append(t)
        elif t in NEGATION_WORDS:
            neg_t.append(t)
        else:
            other.append(t)
    other = _quantity_after_noun(other, nouns)
    return time_t + other + neg_t + wh


def reorder_clauses(clauses, nouns=None):
    """Reorder a list of (tokens, is_question) clauses and concatenate."""
    result = []
    for tokens, q in clauses:
        result.extend(reorder(tokens, q, nouns))
    return result


if __name__ == '__main__':
    # Existing rules preserved: time first, negation last.
    assert reorder(['yo', 'comer', 'ayer', 'no']) == ['ayer', 'yo', 'comer', 'no']
    assert reorder([]) == []
    # Wh-words are untouched in statements.
    assert reorder(['como', 'comer']) == ['como', 'comer']
    # Wh-words go last in questions, after negation.
    assert reorder(['donde', 'vivir', 'tu'], True) == ['vivir', 'tu', 'donde']
    assert reorder(['que', 'querer', 'no'], True) == ['querer', 'no', 'que']
    assert reorder(['por', 'que', 'llorar', 'hoy'], True) == \
        ['hoy', 'llorar', 'por', 'que']
    assert reorder(['¿por que?', 'llorar', 'hoy'], True) == \
        ['hoy', 'llorar', '¿por que?']
    assert reorder(['por que', 'llorar', 'hoy'], True) == \
        ['hoy', 'llorar', 'por que']
    assert reorder(['para que', 'llorar', 'hoy'], True) == \
        ['hoy', 'llorar', 'para que']
    assert reorder(['cuantos', 'ano', 'tener'], True) == ['ano', 'tener', 'cuantos']
    # Quantity after noun only with a noun set.
    assert reorder(['dos', 'libro']) == ['dos', 'libro']
    assert reorder(['dos', 'libro'], nouns={'libro'}) == ['libro', 'dos']
    # Clause splitting.
    assert split_clauses('Hola, como estas? Bien.') == ['Hola', 'como estas', 'Bien']
    assert split_clauses('') == []
    assert split_clauses_flagged('¿Como estas?, bien. Y tu?') == \
        [('Como estas', True), ('bien', False), ('Y tu', True)]
    assert is_question_text('¿Que hora es') and not is_question_text('Hola.')
    assert reorder_clauses([(['donde', 'ir'], True), (['ayer', 'llover'], False)]) \
        == ['ir', 'donde', 'ayer', 'llover']
    print('grammar.py: all assertions passed')
