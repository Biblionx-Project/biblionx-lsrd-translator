#!/usr/bin/env python3
"""
NLP module: preprocesses Dominican Spanish text into an LSRD-ordered token
sequence.

Pipeline (one pass, see LSRDNlpEngine.process):

    dominican normalize_text -> clause split -> tokenize/normalize
    -> phrase segmentation -> stopword removal (wh-words kept in questions)
    -> morphological lemmatization against the dictionary vocabulary
    -> LSRD grammar reorder (grammar.py)

All dictionary-derived indexes are built once per database path and shared
(see get_resources), so constructing engines is cheap.
"""

import json
import os
import re
import threading
import unicodedata

import dominican_lexicon
import grammar
import morphology
from phrases import PhraseMatcher

LSRD_STOP_WORDS = {
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
    'de', 'del', 'al', 'en', 'para', 'por', 'con', 'sin', 'sobre',
    'que', 'cual', 'quien', 'donde', 'como', 'cuando', 'este', 'esta',
    'estos', 'estas', 'ese', 'esa', 'esos', 'esas', 'aquel', 'aquella', 'se'
}

AUXILIARY_VERBS = {'es', 'son', 'ser', 'esta', 'estan', 'estar', 'fue', 'fueron', 'era', 'eran'}

# Words whose morphological or fuzzy resolution is known to be wrong
# (e.g. "senas" -> "seno"). They are kept as-is and end up fingerspelled
# unless the dictionary has them literally.
PROTECTED_WORDS = {'senas', 'sena'}

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "lsrd_dictionary.db")
DATA_DIR = os.path.join(_HERE, "data")
SYNONYMS_EXTRA_PATH = os.path.join(DATA_DIR, "synonyms_extra.json")


def normalize_word(word):
    word = word.lower().strip()
    word = re.sub(r'[^\w\s]', '', word)
    nfkd_form = unicodedata.normalize('NFKD', word)
    only_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return only_ascii


def load_synonyms_extra(path=SYNONYMS_EXTRA_PATH):
    """Load curated synonyms.

    Format: {"version": 1, "entries": [{"word", "target_norm", "palabra_id", "source"}]}.
    Returns a list of entries (empty if the file is missing or invalid).
    """
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f).get("entries", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [e for e in entries if isinstance(e, dict) and e.get("word")]


class Resources:
    """Dictionary-derived indexes shared by every engine for one database."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.known = morphology.build_known(db_path)
        self.phrases = PhraseMatcher.from_db(db_path)


_resources = {}
_resources_lock = threading.Lock()


def get_resources(db_path=DB_PATH):
    key = os.path.abspath(db_path)
    res = _resources.get(key)
    if res is None:
        with _resources_lock:
            res = _resources.get(key)
            if res is None:
                res = _resources[key] = Resources(key)
    return res


def lemmatize_word(word_norm, db_path=DB_PATH):
    """Lemmatize one normalized word against the dictionary vocabulary."""
    return morphology.lemmatize(word_norm, get_resources(db_path).known)[0]


class TokenSequence(list):
    """List of LSRD tokens that also carries per-token provenance.

    Behaves exactly like a plain list (and serializes as one in JSON). The
    translator reads ``methods`` (parallel list of 'exact' | 'morphology' |
    'phrase') and ``context`` (the normalized sentence) when present.
    """

    def __init__(self, tokens=(), methods=None, context=""):
        super().__init__(tokens)
        self.methods = list(methods) if methods is not None else ["exact"] * len(self)
        self.context = context


class LSRDNlpEngine:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    @property
    def resources(self):
        return get_resources(self.db_path)

    def tokenize(self, text):
        tokens = [normalize_word(w) for w in text.split() if w.strip()]
        return [t for t in tokens if t]

    def remove_stopwords(self, tokens, keep_question_words=False):
        filtered = []
        for t in tokens:
            if keep_question_words and t in grammar.QUESTION_WORDS:
                filtered.append(t)
            elif t not in LSRD_STOP_WORDS and t not in AUXILIARY_VERBS:
                filtered.append(t)
        return filtered

    def lemmatize_tokens(self, tokens):
        return [self._lemmatize(t)[0] for t in tokens]

    def _lemmatize(self, token):
        """Return (lemma, method); method is 'exact', 'phrase' or 'morphology'."""
        if ' ' in token or ',' in token:
            return token, 'phrase'
        if token in PROTECTED_WORDS:
            return token, 'exact'
        lemma, how = morphology.lemmatize(token, self.resources.known)
        if lemma == token or how in ('exact', 'none'):
            return lemma, 'exact'
        return lemma, 'morphology'

    def _stressed_preterites(self, clause):
        """Map normalized forms to infinitives for words whose written accent
        marks a preterite verb ("trabajó", "trabajé", "comió").

        Accent stripping turns "trabajó" into "trabajo", which is also a noun
        in the dictionary, so the accent is the only cue that it's a verb.
        Only infinitives that exist in the dictionary are returned.
        """
        known = self.resources.known
        overrides = {}
        for word in clause.lower().split():
            word = word.strip(".,;:!?¡¿\"'()")
            if len(word) < 4 or word[-1] not in 'óé':
                continue
            base = normalize_word(word)
            stem = base[:-1]
            if word.endswith('ió'):
                candidates = [stem[:-1] + 'er', stem[:-1] + 'ir']
            elif word.endswith('ó'):
                candidates = [stem + 'ar']
            else:  # -é (1st person preterite of -ar verbs)
                candidates = [stem + 'ar']
            for inf in candidates:
                if inf in known:
                    overrides[base] = inf
                    break
        return overrides

    def reorder_grammar_lsrd(self, tokens, is_question=False):
        return grammar.reorder(tokens, is_question)

    def process(self, text):
        normalized_text = dominican_lexicon.normalize_text(text)
        clauses = grammar.split_clauses_flagged(normalized_text)
        phrases = self.resources.phrases

        raw_tokens, filtered_tokens, lemmas = [], [], []
        ordered, methods = [], []
        lemma_methods = {}

        for clause, is_q in clauses:
            toks = self.tokenize(clause)
            raw_tokens.extend(toks)
            toks = phrases.segment(toks)
            # Stored phrase norms may carry a trailing comma ("ser humano,").
            toks = [t.strip(' ,') if (' ' in t or ',' in t) else t for t in toks]
            toks = self.remove_stopwords(toks, keep_question_words=is_q)
            filtered_tokens.extend(toks)

            preterites = self._stressed_preterites(clause)
            pairs = [(preterites[t], 'morphology') if t in preterites else self._lemmatize(t)
                     for t in toks]
            # Conjugated copulas (estoy, soy, ...) lemmatize to ser/estar; drop
            # them like the auxiliaries above unless the dictionary has a sign.
            pairs = [p for p in pairs
                     if not (p[0] in AUXILIARY_VERBS and p[0] not in self.resources.known)]
            lemmas.extend(p[0] for p in pairs)
            method_of = {}
            for lemma, how in pairs:
                method_of.setdefault(lemma, how)
                lemma_methods.setdefault(lemma, how)
            clause_order = grammar.reorder([p[0] for p in pairs], is_q)
            ordered.extend(clause_order)
            methods.extend(method_of[t] for t in clause_order)

        return {
            "original_text": text,
            "tokens_normalizados": raw_tokens,
            "tokens_filtrados": filtered_tokens,
            "tokens_lematizados": lemmas,
            "secuencia_lsrd": TokenSequence(ordered, methods, normalized_text),
            "normalized_text": normalized_text,
            "is_question": grammar.is_question_text(text),
            "lemmatization_methods": lemma_methods,
        }
