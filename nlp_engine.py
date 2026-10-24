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
    'estos', 'estas', 'ese', 'esa', 'esos', 'esas', 'aquel', 'aquella', 'se',
    # --- Function words with NO sign of their own, dropped like the ones above
    # instead of being fingerspelled letter by letter. Each one was checked
    # against the dictionary (palabras + sinonimos_mapeo + data/synonyms_extra.json):
    # none resolves to a sign. Words that DO have a sign are deliberately absent
    # (mi, tu, te = TE "tea", me, nos, no, pero, ya, si, tambien, mas,
    # muy, todo, otro): dropping them would delete real content.
    # Object clitics: LSRD marks the argument with direction/pointing, not a sign.
    'lo', 'le', 'les', 'os',
    # One-letter function words. The dictionary has them only as letters of the
    # fingerspelling alphabet (A, Y, O, E, U), not as words, so keeping them
    # showed the letter sign for the preposition "a" or the conjunction "y".
    'a', 'y', 'o', 'e', 'u',
    # Relative pronouns/possessives, same role as 'que', 'cual', 'quien' above.
    # 'cuales' and 'quienes' stay available as wh-words inside questions
    # (grammar.QUESTION_WORDS is checked first in remove_stopwords).
    'cuales', 'quienes', 'cuyo', 'cuya', 'cuyos', 'cuyas',
    # Prepositions with no sign whose relation is carried by the signing space
    # or the context. Not added on purpose: 'entre' (also entrar, "entre por la
    # puerta"), 'bajo' (also adjective), 'tras', 'mediante', 'hasta manana'
    # (own entries or phrases) and 'contra', 'mientras' (they carry meaning).
    'ante', 'hacia', 'segun', 'desde', 'hasta',
    # Concessive/contrastive connectors and fillers with no sign. 'ni' is NOT
    # dropped: removing a negation would flip the meaning ("ni Juan vino").
    'aunque', 'pues', 'sino',
}

# Auxiliaries dropped from the gloss unless the dictionary has the word itself.
# 'haber' is the perfect-tense/existential auxiliary (he, has, ha, hemos, han,
# habia, hay, hubo): morphology maps all of them to 'haber', which has no sign.
AUXILIARY_VERBS = {'es', 'son', 'ser', 'esta', 'estan', 'estar', 'fue', 'fueron', 'era', 'eran',
                   'haber'}

# Words whose morphological or fuzzy resolution is known to be wrong
# (e.g. "senas" -> "seno"). They are kept as-is and end up fingerspelled
# unless the dictionary has them literally.
PROTECTED_WORDS = {'senas', 'sena'}

# Clitic pronouns that are always followed by a verb ("se burla", "te
# abrazo", "le pregunta"). 'lo', 'la', 'los', 'las' are left out because
# they are also articles.
CLITIC_PRONOUNS = {'me', 'te', 'se', 'nos', 'os', 'le', 'les'}

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


def spelling_form(word):
    """Lowercase, punctuation and accents removed, but ñ kept: it has its own
    fingerspelling sign."""
    word = re.sub(r'[^\w\s]', '', word.lower().strip())
    return "".join(
        ch if ch == 'ñ' else "".join(c for c in unicodedata.normalize('NFKD', ch)
                                     if not unicodedata.combining(c))
        for ch in word)


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
        # Curated synonyms (word -> target norm). Kept apart from ``known`` so the
        # base lemmatizer behaves exactly as before; _lemmatize consults them
        # to stop wrong neighbours ("duele" -> "dolar") and to reach curated
        # lemmas ("gusta" -> "gustar").
        extra = os.path.join(os.path.dirname(db_path), "data", "synonyms_extra.json")
        self.curated = {}
        for entry in load_synonyms_extra(extra):
            self.curated.setdefault(normalize_word(entry["word"]),
                                    normalize_word(entry.get("target_norm") or ""))
        self.known_plus = self.known | set(self.curated)
        # Pronominal verbs (ABURRIRSE, BAÑAR, SE): preferred after a clitic.
        self.reflexive = morphology.build_reflexive(db_path)
        self.phrases = PhraseMatcher.from_db(db_path)
        # Every proper prefix of a phrase key, to prune inflected-phrase search.
        # Phrase words join ``known`` when lemmatizing inside a phrase, so that
        # "cruzo" reaches the CRUZAR of CRUZAR LAS PIERNAS.
        self.phrase_prefixes = set()
        phrase_words = set()
        for key in self.phrases.phrases:
            words = key.split()
            phrase_words.update(words)
            for n in range(1, len(words)):
                self.phrase_prefixes.add(" ".join(words[:n]))
        self.known_phrase = self.known | phrase_words


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

    def __init__(self, tokens=(), methods=None, context="", surfaces=None):
        super().__init__(tokens)
        self.methods = list(methods) if methods is not None else ["exact"] * len(self)
        self.context = context
        # normalized token -> spelling form (lowercase, accents removed, ñ kept),
        # so fingerspelling shows ESPAÑOLA rather than ESPANOLA.
        self.surfaces = dict(surfaces or {})


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

    def _lemmatize(self, token, verb_context=False):
        """Return (lemma, method); method is 'exact', 'phrase' or 'morphology'.

        ``verb_context``: the clitic pronoun the token follows (see
        CLITIC_PRONOUNS), or False; morphology then prefers a verb reading.
        """
        if ' ' in token or ',' in token:
            return token, 'phrase'
        if token in PROTECTED_WORDS:
            return token, 'exact'
        res = self.resources
        lemma, how = morphology.lemmatize(token, res.known, verb_context=verb_context,
                                          reflexive=res.reflexive)
        target = res.curated.get(token)
        if target is not None and lemma != token and lemma != target                 and not (verb_context and (lemma in res.reflexive or lemma.endswith('rse'))):
            # An interpreter-curated mapping beats a morphological guess that
            # lands on a different sign, except a pronominal verb read after
            # a clitic ("me visto" is VESTIR, SE even though visto -> ver).
            return token, 'exact'
        if lemma == token and token not in res.known and token not in res.curated:
            lemma2, _ = morphology.lemmatize(token, res.known_plus)
            if lemma2 != token and lemma2 in res.curated:
                return lemma2, 'morphology'
        if lemma == token or how in ('exact', 'none'):
            return lemma, 'exact'
        return lemma, 'morphology'

    def _stressed_preterites(self, clause, verb_ctx=()):
        """Map normalized forms to infinitives for words whose written accent
        marks a preterite verb ("trabajó", "trabajé", "comió").

        Accent stripping turns "trabajó" into "trabajo", which is also a noun
        in the dictionary, so the accent is the only cue that it's a verb.
        The same holds for -iar verbs ("cambió", "premió" are not the nouns
        CAMBIO, PREMIO), pronominal headwords ("se sentó" -> SENTARSE),
        irregular forms ("rió" -> reír) and the stressed imperfect -ía
        ("medía" is medir, not MEDIA).
        Only infinitives that exist in the dictionary are returned.
        """
        known = self.resources.known
        overrides = {}
        for word in clause.lower().split():
            word = word.strip(".,;:!?¡¿\"'()")
            base = normalize_word(word)
            if len(word) < 3 or base == word:
                continue
            if word[-1] in 'óé':
                stem = base[:-1]
                if word.endswith('ió'):
                    candidates = [stem[:-1] + 'er', stem[:-1] + 'ir', stem + 'ar']
                else:  # -ó, -é: 3rd/1st person preterite of -ar verbs
                    candidates = [stem + 'ar']
            elif word.endswith(('ía', 'ías', 'ían')) and len(base.rsplit('ia', 1)[0]) >= 3:
                stem = base.rsplit('ia', 1)[0]
                candidates = [stem + 'er', stem + 'ir']
            else:
                continue
            for inf in candidates:
                # se levantó -> levantarse; me senté -> sentarse (person agrees)
                if verb_ctx.get(base) == ('me' if word[-1] == 'é' else 'se')                         and inf + 'se' in known:
                    overrides[base] = inf + 'se'
                    break
                if inf in known:
                    overrides[base] = inf
                    break
                if inf + 'se' in known:
                    overrides[base] = inf + 'se'
                    break
            else:
                irregular = morphology.IRREGULAR_VERB_MAP.get(base)
                if irregular and word[-1] in 'óé' and irregular in known:
                    overrides[base] = irregular
        return overrides

    @staticmethod
    def _verb_contexts(clause):
        """Map each normalized word that directly follows a clitic pronoun to
        that clitic ("se burla" -> {'burla': 'se'}). Accented "sé" (I know)
        and "té" (tea) are not clitics."""
        words = [w.strip(".,;:!?¡¿\"'()[]").lower() for w in clause.split()]
        ctx = {}
        for prev, cur in zip(words, words[1:]):
            if prev in CLITIC_PRONOUNS and cur:
                ctx.setdefault(normalize_word(cur), prev)
        return ctx

    def _phrase_variants(self, token):
        """Base forms under which an inflected token can match a phrase key:
        the token, its singular ("armas" -> "arma"), its lemma and, for verbs,
        the infinitive and its pronominal form ("lavo" -> lavar, lavarse)."""
        res = self.resources
        out = [token]
        if ' ' in token or token in AUXILIARY_VERBS or token in morphology.IRREGULAR_VERB_MAP \
                and morphology.IRREGULAR_VERB_MAP[token] in ('ser', 'estar', 'haber', 'ir'):
            return out
        cands = morphology._plural_candidates(token)
        lemma = morphology.lemmatize(token, res.known_phrase)[0]
        cands.append(lemma)
        if lemma.endswith(('ar', 'er', 'ir')):
            cands.append(lemma + 'se')
        for c in cands:
            if c not in out:
                out.append(c)
        return out

    def _segment_phrases(self, toks, names):
        """Phrase segmentation that also matches inflected multi-word entries
        ("armas de fuego" -> ARMA DE FUEGO, "cruzó las piernas" -> CRUZAR LAS
        PIERNAS). An exact match at a position always wins; inflected variants
        are tried only where no exact phrase starts."""
        res = self.resources
        pm = res.phrases
        if len(toks) < 2:
            return list(toks)
        variants = [(t,) if t in names else self._phrase_variants(t) for t in toks]
        out, i, n = [], 0, len(toks)
        max_len = min(pm.max_len, 4)

        def search(start, prefix, depth):
            """Longest phrase key from ``start`` built from token variants."""
            best = None
            if start + depth >= n or depth >= max_len:
                return None
            for v in variants[start + depth]:
                key = v if not prefix else prefix + " " + v
                if depth >= 1 and key in pm.phrases:
                    best = (depth + 1, pm.phrases[key]) if best is None or depth + 1 > best[0] else best
                if key in res.phrase_prefixes:
                    deeper = search(start, key, depth + 1)
                    if deeper and (best is None or deeper[0] > best[0]):
                        best = deeper
            return best

        while i < n:
            size = 0
            for s in range(min(max_len, n - i), 1, -1):
                hit = pm.phrases.get(" ".join(toks[i:i + s]))
                if hit is not None:
                    out.append(hit)
                    size = s
                    break
            if not size:
                found = search(i, "", 0)
                if found:
                    size, hit = found
                    out.append(hit)
            if size:
                i += size
            else:
                out.append(toks[i])
                i += 1
        return out

    @staticmethod
    def _name_groups(clause, sentence_initial):
        """Proper-noun spans in a clause, as tuples of normalized words.

        A word counts as a name when it is capitalized and is not the first
        word of a sentence; consecutive capitalized words form one name
        ("Puerto Rico", "La Española"). Names must not be resolved through
        synonyms, morphology or fuzzy matching: "Mona" is not MONO and the
        "Rico" in "Puerto Rico" is not RICO.
        """
        groups, current = [], []
        for i, raw in enumerate(clause.split()):
            word = raw.strip(".,;:!?¡¿\"'()[]")
            is_name = bool(word) and word[0].isupper() and not (i == 0 and sentence_initial)
            if is_name:
                current.append(normalize_word(word))
            elif current:
                groups.append(tuple(current))
                current = []
        if current:
            groups.append(tuple(current))
        return [g for g in groups if all(g)]

    @staticmethod
    def _merge_names(tokens, groups):
        """Replace each name span in ``tokens`` by one space-joined token."""
        names = set()
        out, i = [], 0
        by_first = {}
        for g in groups:
            by_first.setdefault(g[0], []).append(g)
        while i < len(tokens):
            match = None
            for g in sorted(by_first.get(tokens[i], []), key=len, reverse=True):
                if tuple(tokens[i:i + len(g)]) == g:
                    match = g
                    break
            if match:
                name = " ".join(match)
                out.append(name)
                names.add(name)
                i += len(match)
            else:
                out.append(tokens[i])
                i += 1
        return out, names

    def reorder_grammar_lsrd(self, tokens, is_question=False):
        return grammar.reorder(tokens, is_question)

    def process(self, text):
        normalized_text = dominican_lexicon.normalize_text(text)
        clauses = grammar.split_clauses_flagged(normalized_text)
        phrases = self.resources.phrases

        raw_tokens, filtered_tokens, lemmas = [], [], []
        ordered, methods = [], []
        lemma_methods = {}

        offset = 0
        surfaces = {}
        for clause, is_q in clauses:
            # A clause starts a sentence when nothing but sentence punctuation
            # precedes it; clauses after a comma do not.
            pos = normalized_text.find(clause, offset)
            if pos < 0:
                pos = offset
            before = normalized_text[:pos].rstrip(" ¿¡\"'(")
            sentence_initial = not before or before[-1] in ".!?:;\n"
            offset = pos + len(clause)

            toks = self.tokenize(clause)
            raw_tokens.extend(toks)
            for w in clause.split():
                norm = normalize_word(w)
                if norm and 'ñ' in w.lower():
                    surfaces.setdefault(norm, spelling_form(w))
            toks, names = self._merge_names(toks, self._name_groups(clause, sentence_initial))
            toks = self._segment_phrases(toks, names)
            # Stored phrase norms may carry a trailing comma ("ser humano,").
            toks = [t.strip(' ,') if ((' ' in t or ',' in t) and t not in names) else t for t in toks]
            # A word written with ñ is never a stopword: "uña" normalizes to
            # "una", which would otherwise be dropped as the article.
            toks = [t for t in toks if t in names or t in surfaces
                    or t in self.remove_stopwords([t], keep_question_words=is_q)]
            filtered_tokens.extend(toks)

            verb_ctx = self._verb_contexts(clause)
            preterites = self._stressed_preterites(clause, verb_ctx)
            pairs = [(t, 'name') if t in names
                     else (preterites[t], 'morphology') if t in preterites
                     else self._lemmatize(t, verb_context=verb_ctx.get(t, False))
                     for t in toks]
            # Carry ñ over to lemmas ("años" -> "año", not "ano"): suffix rules
            # only change the ending, so ñ keeps its position in the stem.
            for t, (lemma, _how) in zip(toks, pairs):
                surf = surfaces.get(t)
                if surf and lemma != t and lemma not in surfaces:
                    chars = list(lemma)
                    for i, ch in enumerate(surf):
                        if ch == 'ñ' and i < len(chars) and chars[i] == 'n':
                            chars[i] = 'ñ'
                    if 'ñ' in chars:
                        surfaces[lemma] = "".join(chars)
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
            "secuencia_lsrd": TokenSequence(ordered, methods, normalized_text, surfaces),
            "normalized_text": normalized_text,
            "is_question": grammar.is_question_text(text),
            "lemmatization_methods": lemma_methods,
        }
