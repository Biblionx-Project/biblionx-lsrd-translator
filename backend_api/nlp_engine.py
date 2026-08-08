#!/usr/bin/env python3
"""
NLP module for preprocessing and lemmatizing Spanish text -> LSRD grammar.
"""

import os
import re
import sqlite3
import unicodedata

LSRD_STOP_WORDS = {
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
    'de', 'del', 'al', 'en', 'para', 'por', 'con', 'sin', 'sobre',
    'que', 'cual', 'quien', 'donde', 'como', 'cuando', 'este', 'esta',
    'estos', 'estas', 'ese', 'esa', 'esos', 'esas', 'aquel', 'aquella', 'se'
}

AUXILIARY_VERBS = {'es', 'son', 'ser', 'esta', 'estan', 'estar', 'fue', 'fueron', 'era', 'eran'}

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lsrd_dictionary.db")

# Conjugated forms of the ~35 most common irregular Spanish verbs, mapped to
# their infinitive. This is an explicit whitelist on purpose: unlike blindly
# stripping suffixes, it carries no risk of turning common nouns (which also
# end in -a/-e/-o) into nonexistent verbs.
IRREGULAR_VERB_MAP = {
    # tener
    'tengo': 'tener', 'tienes': 'tener', 'tiene': 'tener', 'tenemos': 'tener', 'tienen': 'tener',
    'tuve': 'tener', 'tuvo': 'tener', 'tuvieron': 'tener', 'tenia': 'tener', 'tenian': 'tener',
    # ir
    'voy': 'ir', 'vas': 'ir', 'va': 'ir', 'vamos': 'ir', 'van': 'ir',
    # hacer
    'hago': 'hacer', 'haces': 'hacer', 'hace': 'hacer', 'hacemos': 'hacer', 'hacen': 'hacer',
    'hice': 'hacer', 'hizo': 'hacer', 'hicieron': 'hacer',
    # poder
    'puedo': 'poder', 'puedes': 'poder', 'puede': 'poder', 'podemos': 'poder', 'pueden': 'poder',
    'pude': 'poder', 'pudo': 'poder', 'pudieron': 'poder',
    # decir
    'digo': 'decir', 'dices': 'decir', 'dice': 'decir', 'decimos': 'decir', 'dicen': 'decir',
    'dije': 'decir', 'dijo': 'decir', 'dijeron': 'decir',
    # ver
    'veo': 'ver', 'ves': 'ver', 've': 'ver', 'vemos': 'ver', 'ven': 'ver',
    'vi': 'ver', 'vio': 'ver', 'vieron': 'ver',
    # dar
    'doy': 'dar', 'das': 'dar', 'da': 'dar', 'damos': 'dar', 'dan': 'dar',
    'di': 'dar', 'dio': 'dar', 'dieron': 'dar',
    # saber
    'sabes': 'saber', 'sabe': 'saber', 'sabemos': 'saber', 'saben': 'saber',
    'supe': 'saber', 'supo': 'saber', 'supieron': 'saber',
    # querer (key irregular verb — "quiero" used to fail before this fix)
    'quiero': 'querer', 'quieres': 'querer', 'quiere': 'querer', 'queremos': 'querer', 'quieren': 'querer',
    'quise': 'querer', 'quiso': 'querer', 'quisieron': 'querer',
    # poner
    'pongo': 'poner', 'pones': 'poner', 'pone': 'poner', 'ponemos': 'poner', 'ponen': 'poner',
    'puse': 'poner', 'puso': 'poner', 'pusieron': 'poner',
    # venir
    'vengo': 'venir', 'vienes': 'venir', 'viene': 'venir', 'venimos': 'venir', 'vienen': 'venir',
    'vine': 'venir', 'vino': 'venir', 'vinieron': 'venir',
    # salir
    'salgo': 'salir', 'sales': 'salir', 'sale': 'salir', 'salimos': 'salir', 'salen': 'salir',
    # traer
    'traigo': 'traer', 'traes': 'traer', 'trae': 'traer', 'traemos': 'traer', 'traen': 'traer',
    # oir
    'oigo': 'oir', 'oyes': 'oir', 'oye': 'oir', 'oimos': 'oir', 'oyen': 'oir',
    # conocer
    'conozco': 'conocer', 'conoces': 'conocer', 'conoce': 'conocer', 'conocemos': 'conocer', 'conocen': 'conocer',
    # seguir
    'sigo': 'seguir', 'sigues': 'seguir', 'sigue': 'seguir', 'seguimos': 'seguir', 'siguen': 'seguir',
    # pedir
    'pido': 'pedir', 'pides': 'pedir', 'pide': 'pedir', 'pedimos': 'pedir', 'piden': 'pedir',
    # dormir
    'duermo': 'dormir', 'duermes': 'dormir', 'duerme': 'dormir', 'dormimos': 'dormir', 'duermen': 'dormir',
    # sentir
    'siento': 'sentir', 'sientes': 'sentir', 'siente': 'sentir', 'sentimos': 'sentir', 'sienten': 'sentir',
    # jugar
    'juego': 'jugar', 'juegas': 'jugar', 'juega': 'jugar', 'jugamos': 'jugar', 'juegan': 'jugar',
    # pensar
    'pienso': 'pensar', 'piensas': 'pensar', 'piensa': 'pensar', 'pensamos': 'pensar', 'piensan': 'pensar',
    # entender
    'entiendo': 'entender', 'entiendes': 'entender', 'entiende': 'entender', 'entendemos': 'entender', 'entienden': 'entender',
    # volver
    'vuelvo': 'volver', 'vuelves': 'volver', 'vuelve': 'volver', 'volvemos': 'volver', 'vuelven': 'volver',
    # encontrar
    'encuentro': 'encontrar', 'encuentras': 'encontrar', 'encuentra': 'encontrar', 'encontramos': 'encontrar', 'encuentran': 'encontrar',
    # contar
    'cuento': 'contar', 'cuentas': 'contar', 'cuenta': 'contar', 'contamos': 'contar', 'cuentan': 'contar',
    # cerrar
    'cierro': 'cerrar', 'cierras': 'cerrar', 'cierra': 'cerrar', 'cerramos': 'cerrar', 'cierran': 'cerrar',
    # haber
    'he': 'haber', 'has': 'haber', 'ha': 'haber', 'hemos': 'haber', 'han': 'haber',
    'habia': 'haber', 'habian': 'haber',
    # plus the 7 regular verbs already covered by the dynamic dictionary lookup below
}

_regular_conjugation_cache = None


def _load_regular_conjugation_map():
    """
    Automatically generates regular conjugated forms (present tense,
    I/you/he-she/we/they) for every -ar/-er/-ir infinitive that ALREADY
    exists in the LSRD dictionary. Unlike blindly stripping suffixes from
    any word, this only generates forms for verbs we already know are
    translatable, so there's no risk of "inventing" a verb from a noun that
    happens to end in -ar/-er/-ir (e.g. "lugar" / "place").
    """
    global _regular_conjugation_cache
    if _regular_conjugation_cache is not None:
        return _regular_conjugation_cache

    mapping = {}
    try:
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT palabra_norm FROM palabras WHERE palabra_norm LIKE '%ar' OR palabra_norm LIKE '%er' OR palabra_norm LIKE '%ir'")
            infinitives = [row[0] for row in cur.fetchall() if row[0] and ' ' not in row[0] and ',' not in row[0]]
            conn.close()

            endings = {
                # present tense
                'ar': {'o': 'ar', 'as': 'ar', 'a': 'ar', 'amos': 'ar', 'an': 'ar',
                       # imperfect (-aba)
                       'aba': 'ar', 'abas': 'ar', 'abamos': 'ar', 'aban': 'ar'},
                'er': {'o': 'er', 'es': 'er', 'e': 'er', 'emos': 'er', 'en': 'er',
                       # imperfect (-ia)
                       'ia': 'er', 'ias': 'er', 'iamos': 'er', 'ian': 'er'},
                'ir': {'o': 'ir', 'es': 'ir', 'e': 'ir', 'imos': 'ir', 'en': 'ir',
                       'ia': 'ir', 'ias': 'ir', 'iamos': 'ir', 'ian': 'ir'},
            }
            for inf in infinitives:
                if len(inf) < 4:
                    continue
                group = inf[-2:]
                stem = inf[:-2]
                for person_ending in endings.get(group, {}):
                    form = stem + person_ending
                    # Don't overwrite if the word itself already exists in the dictionary
                    # (avoids, for example, mapping "casa"/"house" to a verb "casar"/"to marry").
                    if form != inf:
                        mapping.setdefault(form, inf)
    except Exception:
        mapping = {}

    _regular_conjugation_cache = mapping
    return mapping


def normalize_word(word):
    word = word.lower().strip()
    word = re.sub(r'[^\w\s]', '', word)
    nfkd_form = unicodedata.normalize('NFKD', word)
    only_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return only_ascii


def lemmatize_word(word_norm):
    # 1. Common irregular verbs (explicit, safe whitelist).
    if word_norm in IRREGULAR_VERB_MAP:
        return IRREGULAR_VERB_MAP[word_norm]

    # 2. Regular conjugated forms derived from infinitives that actually
    #    exist in the LSRD dictionary.
    regular_map = _load_regular_conjugation_map()
    if word_norm in regular_map:
        return regular_map[word_norm]

    if len(word_norm) <= 3:
        return word_norm

    if word_norm.endswith(('ar', 'er', 'ir')):
        return word_norm

    # 3. Backward compatibility with the previous manual mappings (in case
    #    the dictionary doesn't yet contain one of these infinitives).
    if word_norm in ['trabaja', 'trabajas', 'trabajamos', 'trabajan', 'trabajando', 'trabajo']:
        return 'trabajar'
    if word_norm in ['estudia', 'estudias', 'estudiamos', 'estudian', 'estudiando']:
        return 'estudiar'
    if word_norm in ['corre', 'corres', 'corremos', 'corren', 'corriendo']:
        return 'correr'
    if word_norm in ['come', 'comes', 'comemos', 'comen', 'comiendo']:
        return 'comer'
    if word_norm in ['habla', 'hablas', 'hablamos', 'hablan', 'hablando']:
        return 'hablar'
    if word_norm in ['escribe', 'escribes', 'escribimos', 'escriben', 'escribiendo']:
        return 'escribir'
    if word_norm in ['lee', 'lees', 'leemos', 'leen', 'leyendo']:
        return 'leer'
    return word_norm


class LSRDNlpEngine:
    def tokenize(self, text):
        tokens = [normalize_word(w) for w in text.split() if w.strip()]
        return [t for t in tokens if t]

    def remove_stopwords(self, tokens):
        filtered = []
        for t in tokens:
            if t not in LSRD_STOP_WORDS and t not in AUXILIARY_VERBS:
                filtered.append(t)
        return filtered

    def lemmatize_tokens(self, tokens):
        return [lemmatize_word(t) for t in tokens]

    def reorder_grammar_lsrd(self, tokens):
        if not tokens:
            return []

        time_tokens = []
        negation_tokens = []
        other_tokens = []

        TIME_WORDS = {'ayer', 'hoy', 'manana', 'ahora', 'anoche', 'pasado', 'futuro', 'lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo', 'mes', 'ano'}
        NEGATION_WORDS = {'no', 'nunca', 'jamas', 'nada', 'ninguno', 'ninguna'}

        for t in tokens:
            if t in TIME_WORDS:
                time_tokens.append(t)
            elif t in NEGATION_WORDS:
                negation_tokens.append(t)
            else:
                other_tokens.append(t)

        reordered = time_tokens + other_tokens + negation_tokens
        return reordered

    def process(self, text):
        raw_tokens = self.tokenize(text)
        clean_tokens = self.remove_stopwords(raw_tokens)
        lemmas = self.lemmatize_tokens(clean_tokens)
        lsrd_ordered = self.reorder_grammar_lsrd(lemmas)
        return {
            "original_text": text,
            "tokens_normalizados": raw_tokens,
            "tokens_filtrados": clean_tokens,
            "tokens_lematizados": lemmas,
            "secuencia_lsrd": lsrd_ordered
        }
