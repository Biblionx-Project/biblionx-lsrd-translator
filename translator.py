#!/usr/bin/env python3
"""
Maps lemmas to an LSRD sign sequence.

Lookup chain for every token (first hit wins):

    exact palabra_norm  ->  sinonimos_mapeo  ->  curated synonyms
    (data/synonyms_extra.json)  ->  fuzzy ML match (char n-gram TF-IDF)
    ->  optional semantic AI choice over the whole dictionary
    ->  A-Z fingerspelling

Each returned sign carries ``match_method`` and ``confidence`` (0-1) in
addition to the original keys. Every fingerspelled letter also carries
``spelled_word`` (the original token), ``spelled_index`` (0-based position of
the letter inside that word) and ``spelled_length`` (letters emitted for it) so
UIs can group the letters of one word. Lookup tables are built once per database
(shared, read-only); each translator owns one SQLite connection guarded by a
lock, so an instance is safe to share across server threads.
"""

import os
import sqlite3
import threading

from ml_matcher import FuzzyMatcher
from llm_fallback import AI_CONFIDENCE_CAP, LLMFallback
from nlp_engine import PROTECTED_WORDS, load_synonyms_extra, normalize_word

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "lsrd_dictionary.db")

FUZZY_MIN_SCORE = 0.84
SEMANTIC_MIN_LEN = 3  # shorter tokens are never worth a model call

# Fingerspelling alphabet letter mapping, extracted from the Dictionary (pages 21-28 / entries)
DACTYL_LETTER_MAP = {
    'a': 'lsrd_0001',
    'b': 'lsrd_0262',
    'c': 'lsrd_0372',
    'd': 'lsrd_0678',
    'e': 'lsrd_0807',
    'f': 'lsrd_0971',
    'g': 'lsrd_1040',
    'h': 'lsrd_1090',
    'i': 'lsrd_1155',
    'j': 'lsrd_1222',
    'k': 'lsrd_1242',
    'l': 'lsrd_1248',
    'm': 'lsrd_1327',
    'n': 'lsrd_1475',
    'ñ': 'lsrd_1526',
    'o': 'lsrd_1527',
    'p': 'lsrd_1582',
    'q': 'lsrd_1799',
    'r': 'lsrd_1815',
    's': 'lsrd_1907',
    't': 'lsrd_2028',
    'u': 'lsrd_2157',
    'v': 'lsrd_2170',
    'w': 'lsrd_2237',
    'x': 'lsrd_2239',
    'y': 'lsrd_2240',
    'z': 'lsrd_2247'
}

# Digit strings that have a dictionary sign under their Spanish word. Other
# digits have no sign and are skipped (the alphabet has no numerals).
NUMBER_WORDS = {'2': 'dos', '10': 'diez', '20': 'veinte', '100': 'cien', '1000': 'mil'}

CONFIDENCE = {'exact': 1.0, 'phrase': 0.95, 'morphology': 0.9, 'synonym': 0.9,
              'curated_synonym': 0.85, 'ai': AI_CONFIDENCE_CAP, 'fingerspelling': 0.5}

_SIGN_QUERY = """
    SELECT p.id, p.palabra_es, p.definicion_es, p.pagina, c.nombre as categoria,
           sd.descripcion_sena, ri.ruta_imagen
    FROM palabras p
    LEFT JOIN categorias c ON p.categoria_id = c.id
    LEFT JOIN senas_descripciones sd ON p.id = sd.palabra_id
    LEFT JOIN rutas_imagenes ri ON p.id = ri.palabra_id
    WHERE p.id = ?
    LIMIT 1
"""


# Derivational endings: a word carrying one of these is a different lexeme
# from a dictionary entry that lacks it (ingenieria vs ingeniera,
# arquitectura vs arquitecta), so fuzzy matching must not bridge them.
_DERIVATIONAL_ENDINGS = ('ia', 'ura', 'ico', 'ica', 'ismo', 'ista', 'ario', 'aria', 'dad', 'cion')


def _is_wrong_neighbour(word, matched):
    """True when a fuzzy hit changes the lexeme rather than fixing a typo."""
    if not matched or word == matched:
        return False
    # Final o <-> a flip (musico/musica, cuento/cuenta): gender or meaning
    # change, handled deterministically by morphology, never by fuzzy matching.
    if len(word) == len(matched) and word[:-1] == matched[:-1] and {word[-1], matched[-1]} == {'o', 'a'}:
        return True
    for end in _DERIVATIONAL_ENDINGS:
        if word.endswith(end) and not matched.endswith(end):
            return True
    return False


class _Index:
    """In-memory lookup tables derived from the database (read-only)."""

    def __init__(self, db_path):
        conn = sqlite3.connect(db_path)
        try:
            self.exact = {}      # palabra_norm (full) -> palabra_id
            self.prefix = {}     # first comma-separated part -> palabra_id
            letter_ids = set(DACTYL_LETTER_MAP.values())
            lemmas = set()       # sign lemmas offered to the semantic AI fallback
            for pid, norm in conn.execute("SELECT id, palabra_norm FROM palabras ORDER BY rowid"):
                if not norm:
                    continue
                norm = norm.strip()
                if norm and pid not in letter_ids:
                    lemmas.add(norm)
                self.exact.setdefault(norm, pid)
                if ',' in norm:
                    self.exact.setdefault(norm.rstrip(', '), pid)
                    self.prefix.setdefault(norm.split(',')[0].strip(), pid)
                stripped = norm.strip('¿?¡!').strip()
                if stripped and stripped != norm:
                    self.exact.setdefault(stripped, pid)
                    if ',' in stripped:
                        self.exact.setdefault(stripped.rstrip(', '), pid)
                        self.prefix.setdefault(stripped.split(',')[0].strip(), pid)
            self.lemmas = tuple(sorted(lemmas))
            self.synonym = {}
            try:
                for pid, syn in conn.execute(
                        "SELECT palabra_id, sinonimo_norm FROM sinonimos_mapeo ORDER BY id"):
                    if syn:
                        self.synonym.setdefault(syn.strip(), pid)
            except sqlite3.Error:
                pass
        finally:
            conn.close()
        self.curated = {}        # word -> palabra_id
        extra = os.path.join(os.path.dirname(db_path), "data", "synonyms_extra.json")
        for e in load_synonyms_extra(extra):
            pid = e.get("palabra_id") or self.exact.get(normalize_word(e.get("target_norm") or ""))
            if pid:
                self.curated.setdefault(normalize_word(e["word"]), pid)
        self._fuzzy = None
        self._lock = threading.Lock()
        self.db_path = db_path

    @property
    def fuzzy(self):
        if self._fuzzy is None:
            with self._lock:
                if self._fuzzy is None:
                    self._fuzzy = FuzzyMatcher.from_db(self.db_path)
        return self._fuzzy


_indexes = {}
_indexes_lock = threading.Lock()


def _get_index(db_path):
    key = os.path.abspath(db_path)
    idx = _indexes.get(key)
    if idx is None:
        with _indexes_lock:
            idx = _indexes.get(key)
            if idx is None:
                idx = _indexes[key] = _Index(key)
    return idx


class LSRDTranslator:
    def __init__(self, db_path=DB_PATH, llm=None):
        self.db_path = os.path.abspath(db_path)
        self._index = _get_index(self.db_path)
        self._llm = llm
        self._conn = None
        self._lock = threading.Lock()
        self._rows = {}

    @property
    def llm(self):
        if self._llm is None:
            self._llm = LLMFallback.from_env()
        return self._llm

    # ---- database access ----
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _row(self, palabra_id):
        """Sign row for a palabra id (a fresh dict copy; rows are cached)."""
        row = self._rows.get(palabra_id)
        if row is None:
            with self._lock:
                if self._conn is None:
                    self._conn = self.get_connection()
                found = self._conn.execute(_SIGN_QUERY, (palabra_id,)).fetchone()
            if found is None:
                return None
            row = self._rows[palabra_id] = dict(found)
        return dict(row)

    # ---- lookups ----
    def _lookup_id(self, word_norm):
        """Deterministic lookups. Returns (palabra_id, method) or (None, None)."""
        idx = self._index
        pid = idx.exact.get(word_norm) or idx.prefix.get(word_norm)
        if pid:
            return pid, 'exact'
        pid = idx.synonym.get(word_norm)
        if pid:
            return pid, 'synonym'
        pid = idx.curated.get(word_norm)
        if pid:
            return pid, 'curated_synonym'
        number = NUMBER_WORDS.get(word_norm)
        if number:
            pid = idx.exact.get(number) or idx.synonym.get(number)
            if pid:
                return pid, 'curated_synonym'
        return None, None

    @staticmethod
    def _tag(item, method, confidence):
        item['es_deletreo'] = False
        item['letra'] = None
        item['match_method'] = method
        item['confidence'] = round(float(confidence), 3)
        return item

    def find_sign_by_word(self, word_norm):
        """Looks up a sign by exact word match, synonym or curated synonym."""
        pid, method = self._lookup_id(word_norm)
        if not pid:
            return None
        row = self._row(pid)
        return self._tag(row, method, CONFIDENCE[method]) if row else None

    def _fuzzy_sign(self, word_norm, context):
        """Fuzzy ML match. Returns a tagged sign or None."""
        if word_norm in PROTECTED_WORDS or len(word_norm) <= 3 or any(c.isdigit() for c in word_norm):
            return None
        fz = self._index.fuzzy
        hit = fz.match(word_norm, FUZZY_MIN_SCORE)
        if hit and _is_wrong_neighbour(word_norm, hit['norm']):
            hit = None
        if hit:
            row = self._row(hit['palabra_id'])
            if row:
                item = self._tag(row, 'fuzzy', hit['score'])
                item['matched_norm'] = hit['norm']
                return item
        return None

    def _semantic_sign(self, word_norm, context):
        """Optional AI choice over the whole dictionary. Returns a tagged sign or None.

        Runs only after exact/synonym/fuzzy missed and before fingerspelling.
        The model sees every sign lemma and the sentence; its answer is
        validated against the dictionary, so it can only pick an existing sign.
        """
        llm = self.llm
        if not llm.enabled or not hasattr(llm, 'choose_semantic'):
            return None
        if (word_norm in PROTECTED_WORDS or len(word_norm) < SEMANTIC_MIN_LEN
                or any(c.isdigit() for c in word_norm)):
            return None
        lemma = llm.choose_semantic(word_norm, context or '', self._index.lemmas)
        if not lemma:
            return None
        pid = self._index.exact.get(lemma) or self._index.prefix.get(lemma)
        row = self._row(pid) if pid else None
        if not row:
            return None
        item = self._tag(row, 'ai', CONFIDENCE['ai'])
        item['matched_norm'] = lemma
        return item

    def get_fingerspelling_sequence(self, word):
        """Generates a fingerspelling sequence for words not found in the dictionary.

        Each letter item carries ``spelled_word`` (the original token),
        ``spelled_index`` (0-based position among the emitted letters) and
        ``spelled_length`` (number of letters emitted for the word).
        """
        sequence = []
        for char in word.lower():
            sign_id = DACTYL_LETTER_MAP.get(char)
            if not sign_id:
                continue
            item = self._row(sign_id)
            if item:
                item['es_deletreo'] = True
                item['letra'] = char.upper()
                item['match_method'] = 'fingerspelling'
                item['confidence'] = CONFIDENCE['fingerspelling']
                item['spelled_word'] = word
                item['spelled_index'] = len(sequence)
                sequence.append(item)
        for item in sequence:
            item['spelled_length'] = len(sequence)
        return sequence

    def translate_sequence(self, tokens_lsrd, context=None):
        """Translates a list of tokens into an ordered sequence of sign objects.

        If ``tokens_lsrd`` is a nlp_engine.TokenSequence, its provenance
        ('phrase' / 'morphology') labels exact matches and its sentence
        context is passed to the optional semantic AI fallback.
        """
        hints = getattr(tokens_lsrd, 'methods', None)
        if context is None:
            context = getattr(tokens_lsrd, 'context', None)
        result_sequence = []

        for i, token in enumerate(tokens_lsrd):
            pid, method = self._lookup_id(token)
            if pid:
                row = self._row(pid)
                if row:
                    if method == 'exact' and hints and hints[i] in ('phrase', 'morphology'):
                        method = hints[i]
                    result_sequence.append(self._tag(row, method, CONFIDENCE[method]))
                    continue
            fuzzy_item = self._fuzzy_sign(token, context) or self._semantic_sign(token, context)
            if fuzzy_item:
                result_sequence.append(fuzzy_item)
            else:
                result_sequence.extend(self.get_fingerspelling_sequence(token))

        return result_sequence
