"""Conservative Spanish morphological lemmatizer for the LSRD translator.

Pure Python, standard library only. All input is expected to be lowercase
with accents already stripped (the dictionary "norm" form).

A lemma different from the input is only returned when it is present in the
`known` set (reachable dictionary norms) or comes from the explicit
irregular-verb map. This prevents inventing words that have no sign.

Public API:
    lemmatize(word_norm, known, verb_context=False, reflexive=None)
                                -> (lemma, method)
    build_known(db_path)        -> set of reachable dictionary norms
    build_reflexive(db_path)    -> set of norms of pronominal verbs
                                   ('aburrirse', or 'banar' for 'banar, se')

method is one of: 'exact', 'irregular', 'regular_verb', 'plural', 'gender',
'diminutive', 'derivation', 'enclitic', 'none'.

``verb_context`` means the word follows a clitic pronoun (me, te, se, nos,
os, le, les), so it can only be a verb: "se burla" is BURLARSE, not the noun
BURLA. ``reflexive`` lets that context prefer the pronominal headword when
the clitic agrees in person with the verb ending.
"""

import re
import sqlite3
import unicodedata

# Conjugated forms of the most common irregular Spanish verbs mapped to their
# infinitive (Spanish data, moved from nlp_engine.py). Explicit whitelist on
# purpose: no risk of turning nouns ending in -a/-e/-o into invented verbs.
_BASE_IRREGULAR = {
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


# Additional irregular forms (accent-stripped): preterite, imperfect, future,
# conditional, present subjunctive, gerund and participle of common verbs.
_EXTRA_FORMS = {
    'ser': 'soy eres es somos sois son era eras eramos erais eran sea seas seamos seais sean '
           'siendo sido sere seras sera seremos sereis seran seria serias seriamos seriais serian '
           'fue fueron',
    'estar': 'estoy estas esta estamos estais estan estuve estuviste estuvo estuvimos estuvisteis estuvieron '
             'estaba estabas estabamos estaban estando estado estare estaras estara estaremos estaran '
             'estaria estarias estariamos estarian estemos esten estes',
    'ir': 'voy vas va vamos vais van fui fuiste fuimos fuisteis iba ibas ibamos ibais iban '
          'vaya vayas vayamos vayais vayan yendo ido ire iras ira iremos iran iria irias iriamos irian',
    'tener': 'tuviste tuvimos tuvisteis teniamos tenias teniendo tenido tendre tendras tendra tendremos tendran '
             'tendria tendrias tendriamos tendrian tenga tengas tengamos tengan',
    'hacer': 'hiciste hicimos haciendo hecho hare haras hara haremos haran haria harias hariamos harian '
             'haga hagas hagamos hagan hacia hacias haciamos hacian',
    'poder': 'pudiste pudimos pudiendo podido podre podras podra podremos podran podria podrias podriamos podrian '
             'pueda puedas podamos puedan podia podias podian',
    'decir': 'dijiste dijimos diciendo dicho dire diras dira diremos diran diria dirias diriamos dirian '
             'diga digas digamos digan decia decias decian',
    'ver': 'viste vimos viendo visto veia veias veiamos veian vere veras vera veremos veran veria verian '
           'vea veas veamos vean',
    'dar': 'diste dimos dando dado dare daras dara daremos daran daria darian dabas daba daban dabamos '
           'dieras dieran',
    'saber': 'supiste supimos sabiendo sabido sabre sabras sabra sabremos sabran sabria sabrian '
             'sepa sepas sepamos sepan sabia sabias sabian',
    'querer': 'quisiste quisimos queriendo querido querre querras querra querremos querran querria querrian '
              'quiera quieras queramos quieran queria querias querian',
    'poner': 'pusiste pusimos poniendo puesto pondre pondras pondra pondremos pondran pondria pondrian '
             'ponga pongas pongamos pongan ponia ponian',
    'venir': 'viniste vinimos viniendo venido vendre vendras vendra vendremos vendran vendria vendrian '
             'venga vengas vengamos vengan venia venian',
    'salir': 'saliste salimos saliendo salido saldre saldras saldra saldremos saldran saldria saldrian '
             'salga salgas salgamos salgan salia salian',
    'traer': 'traje trajiste trajo trajimos trajeron trayendo traido traiga traigas traigamos traigan traia traian',
    'oir': 'oi oiste oyo oyeron oyendo oido oiga oigas oigamos oigan oia oian',
    'haber': 'hube hubo hubieron habra habran habria habrian haya hayas hayamos hayan hay habiamos habiendo habido',
    'conocer': 'conozca conozcas conozcamos conozcan',
    'seguir': 'segui seguiste siguio siguieron siguiendo siga sigas sigamos sigan seguido',
    'pedir': 'pedi pediste pidio pidieron pidiendo pida pidas pidamos pidan pedido',
    'dormir': 'durmio durmieron durmiendo duerma duermas durmamos duerman dormido',
    'sentir': 'senti sentiste sintio sintieron sintiendo sienta sientas sintamos sientan sentido',
    'jugar': 'jugue jugaste jugo jugaron juegue juegues juguemos jueguen jugando jugado',
    'pensar': 'piense pienses pensemos piensen pensando pensado',
    'entender': 'entienda entiendas entendamos entiendan entendiendo entendido',
    'volver': 'vuelva vuelvas volvamos vuelvan volviendo vuelto',
    'encontrar': 'encuentre encuentres encontremos encuentren encontrando encontrado',
    'contar': 'cuente cuentes contemos cuenten contando contado',
    'cerrar': 'cierre cierres cerremos cierren cerrando cerrado',
    'escribir': 'escrito',
    'abrir': 'abierto',
    'romper': 'roto',
    'morir': 'muere mueres mueren murio murieron muriendo muerto',
    'resolver': 'resuelto',
    'andar': 'anduve anduviste anduvo anduvimos anduvieron',
    'caer': 'caigo cayo cayeron cayendo caido caiga',
    'leer': 'leyo leyeron leyendo leido',
    'creer': 'creyo creyeron creyendo creido',
    # reir: 'rio' is listed so that a verb context ("se rio") reaches it; the
    # bare word still gives the noun RIO because exact matches come first.
    'reir': 'rio rie ries rien reimos rei reiste rieron riendo reido ria rias rian reia reian',
    'freir': 'frie fries frien frito',
}

# Irregular verbs whose prefixed compounds conjugate the same way
# (detener -> detuvo, posponer -> pospuso, bendecir -> bendigo,
# envolver -> envuelto, describir -> descrito, satisfacer -> satisfizo).
# A compound is only returned when it is a known dictionary norm.
_COMPOUND_BASES = frozenset((
    'tener', 'poner', 'venir', 'hacer', 'decir', 'traer', 'volver', 'escribir',
    'abrir', 'reir', 'seguir', 'pedir', 'sentir', 'conocer', 'caer',
    'leer', 'salir', 'ver', 'contar', 'cerrar', 'pensar', 'entender', 'romper',
    'resolver',
))

# Imperative forms that only apply when a clitic pronoun follows
# (dime -> decir, ponlo -> poner); plain 'di'/'ve' stay as in the base map.
_ENCLITIC_IMPERATIVE = {
    'di': 'decir', 've': 'ir', 'pon': 'poner', 'sal': 'salir', 'ten': 'tener',
    'haz': 'hacer', 'ven': 'venir', 'da': 'dar',
}

# Apocopated forms (buen -> bueno), valid only if the target is known.
_APOCOPE = {
    'buen': 'bueno', 'mal': 'malo', 'gran': 'grande', 'primer': 'primero',
    'tercer': 'tercero', 'algun': 'alguno', 'ningun': 'ninguno', 'san': 'santo',
}

# Forms that are verbs far more often than homographic nouns; they win even
# when the same string happens to be a dictionary entry.
_FORCE_IRREGULAR = {
    'es', 'son', 'fue', 'fueron', 'era', 'eran', 'soy', 'eres', 'voy', 'vas', 'va',
    'vamos', 'van', 'he', 'has', 'ha', 'han', 'hemos', 'hay', 'fui', 'fuiste',
}


def _build_irregular():
    mapping = dict(_BASE_IRREGULAR)
    for inf, forms in _EXTRA_FORMS.items():
        for form in forms.split():
            mapping.setdefault(form, inf)
    return mapping


IRREGULAR_VERB_MAP = _build_irregular()

# (suffix, infinitive ending) for regular paradigms, accent-stripped.
_AR = ('o as a amos ais an e aste asteis aron aba abas abamos abais aban '
       'es emos eis en ando ado ada ados adas aramos ad').split()
_ER = ('o es e emos eis en i iste io imos isteis ieron ia ias iamos iais ian '
       'a as amos ais an iendo yendo ido ida idos idas yo yeron ieran ieras ieramos iera').split()
_IR = ('o es e imos is en i iste io isteis ieron ia ias iamos iais ian '
       'a as amos ais an iendo yendo ido ida idos idas yo yeron ieran ieras ieramos iera id').split()
_SUFFIXES = (
    [(s, 'ar') for s in _AR] + [(s, 'er') for s in _ER] + [(s, 'ir') for s in _IR]
)
# Present-subjunctive endings. A form that is indicative in one conjugation
# and subjunctive in another ("creen": creer / crear) is read as indicative.
_SUBJUNCTIVE = {
    'ar': frozenset('e es emos eis en'.split()),
    'er': frozenset('a as amos ais an'.split()),
    'ir': frozenset('a as amos ais an'.split()),
}
# Last tie-break between conjugations: "vendo" -> vender, "creo" -> creer.
_ENDING_RANK = {'er': 0, 'ir': 1, 'ar': 2}
_REFLEXIVE_CLITICS = ('se', 'me', 'te', 'nos', 'os')

# Grammatical person of each finite ending, so a clitic only selects the
# pronominal verb when it agrees with the verb: "me levanto" (1s + 1s) is
# LEVANTARSE but "me parece" (1s + 3s) is parecer with a dative "me".
# Endings not listed (gerund, participle, infinitive) agree with any clitic.
_PERSON_TABLE = {
    'ar': {'o': '1s 3s', 'as': '2s', 'a': '3s', 'amos': '1p', 'ais': '2p', 'an': '3p',
           'e': '1s 3s', 'aste': '2s', 'asteis': '2p', 'aron': '3p', 'aba': '1s 3s',
           'abas': '2s', 'abamos': '1p', 'abais': '2p', 'aban': '3p', 'es': '2s',
           'emos': '1p', 'eis': '2p', 'en': '3p', 'aramos': '1p', 'ad': '2p'},
    'er': {'o': '1s', 'es': '2s', 'e': '3s', 'emos': '1p', 'eis': '2p', 'en': '3p',
           'i': '1s', 'iste': '2s', 'io': '3s', 'imos': '1p', 'isteis': '2p', 'ieron': '3p',
           'ia': '1s 3s', 'ias': '2s', 'iamos': '1p', 'iais': '2p', 'ian': '3p',
           'a': '1s 3s', 'as': '2s', 'amos': '1p', 'ais': '2p', 'an': '3p', 'yo': '3s',
           'yeron': '3p', 'ieran': '3p', 'ieras': '2s', 'ieramos': '1p', 'iera': '1s 3s',
           'is': '2p', 'id': '2p'},
}
_PERSON_TABLE['ir'] = _PERSON_TABLE['er']
_FUT_PERSON = {'e': '1s', 'as': '2s', 'a': '3s', 'emos': '1p', 'eis': '2p', 'an': '3p',
               'ia': '1s 3s', 'ias': '2s', 'iamos': '1p', 'iais': '2p', 'ian': '3p'}
# 'se' also goes with usted/ustedes (3rd-person verb forms); le/les are never
# reflexive.
_CLITIC_PERSON = {'me': {'1s'}, 'te': {'2s'}, 'se': {'3s', '3p'}, 'nos': {'1p'},
                  'os': {'2p'}, 'le': set(), 'les': set()}


def _agrees(persons, clitic):
    """True when the clitic can be reflexive with a verb of ``persons``
    (a space-separated string, None for non-finite forms). An unknown
    clitic (None) agrees with everything."""
    if clitic is None or persons is None:
        return clitic not in ('le', 'les')
    return bool(_CLITIC_PERSON.get(clitic, set()) & set(persons.split()))
# Future / conditional: infinitive + ending (word = inf + ending).
_FUT_COND = 'e as a emos eis an ia ias iamos iais ian'.split()
_PRONOUNS = sorted(('me', 'te', 'se', 'lo', 'la', 'le', 'nos', 'os', 'los', 'las', 'les'),
                   key=len, reverse=True)


def _strip_accents(text):
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def _stem_variants(stem, ending):
    """Undo the stem alternations and spelling changes of a verb stem.

    Alternations are tied to the conjugation they occur in: ie -> e and
    ue -> o in all three, ue -> u only in -ar (jugar), i -> e and u -> o only
    in -ir (pide, durmio). Applying them everywhere turned nouns into verbs
    ("burra" -> borrar, "patio" -> patear).
    """
    vowel = [stem]
    pats = [('ie', 'e'), ('ue', 'o')]
    if ending == 'ar':
        pats.append(('ue', 'u'))
    for pat, rep in pats:
        i = stem.rfind(pat)
        if i != -1:
            vowel.append(stem[:i] + rep + stem[i + len(pat):])
    if ending == 'ir':
        for pat, rep in (('i', 'e'), ('u', 'o')):
            i = stem.rfind(pat)
            # Not inside the diphthongs ie/ue handled above ("riendo" is not
            # a form of rendir).
            if i != -1 and i >= len(stem) - 3 and stem[i + 1:i + 2] != 'e':
                vowel.append(stem[:i] + rep + stem[i + 1:])
    if ending == 'er' and stem.startswith('hue'):
        vowel.append('o' + stem[3:])  # oler: huele
    out = []
    for v in vowel:
        out.append(v)
        if ending == 'ar':
            if v.endswith('qu'):
                out.append(v[:-2] + 'c')   # busque -> buscar
            elif v.endswith('gu'):
                out.append(v[:-2] + 'g')   # llegue -> llegar
            elif v.endswith('c'):
                out.append(v[:-1] + 'z')   # empece -> empezar
        elif v.endswith('zc'):
            out.append(v[:-2] + 'c')       # conozca -> conocer
        elif v.endswith('j'):
            out.append(v[:-1] + 'g')       # cojo -> coger, elijo -> elegir
        elif v.endswith('z'):
            out.append(v[:-1] + 'c')       # venzo -> vencer
        elif ending == 'ir' and v.endswith('uy'):
            out.append(v[:-1])             # construye -> construir
        elif ending == 'ir' and v.endswith('g'):
            out.append(v + 'u')            # distingo -> distinguir
    return out


# Without a clitic, a pronominal-only headword is not reached from these bare
# person endings: "mudo", "muda" (mute), "relajo" (Dominican: fuss) are far
# more often adjectives or nouns than "(me) mudo", "(se) muda".
_BARE_SE_BLOCKED = frozenset(('o', 'a', 'as', 'e', 'es'))


def _regular_candidates(word, known):
    """Yield (infinitive, subjunctive, via_se, suffix_len, variant, ending)
    for every regular-paradigm reading of ``word`` that the dictionary knows.

    ``via_se`` marks a pronominal headword reached by adding -se
    ("aburro" -> "aburrirse" when the dictionary only has ABURRIRSE).
    """
    for suf, ending in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 2:
            stem = word[:-len(suf)]
            subj = suf in _SUBJUNCTIVE[ending]
            for vi, var in enumerate(_stem_variants(stem, ending)):
                cand = var + ending
                if cand == word:
                    continue
                if cand in known:
                    yield cand, subj, False, len(suf), vi, ending
                if cand + 'se' in known:
                    yield cand + 'se', subj, True, len(suf), vi, ending


def _best_regular(word, known, reflexive=None, clitic=None):
    """Best regular reading and its sort key.

    Indicative before subjunctive, then (only when ``reflexive`` is given,
    i.e. after a clitic that agrees with the ending) pronominal headwords,
    then the direct infinitive before the -se fallback, longer suffix, fewer
    stem changes.
    """
    best, best_key = None, None
    for cand, subj, via_se, slen, vi, ending in _regular_candidates(word, known):
        suf = word[len(word) - slen:]
        refl_ok = reflexive is not None and _agrees(_PERSON_TABLE[ending].get(suf), clitic)
        if via_se and not refl_ok and suf in _BARE_SE_BLOCKED:
            continue
        refl = 0 if refl_ok and (via_se or cand in reflexive) else 1
        key = (subj, refl, via_se, -slen, vi, _ENDING_RANK[ending])
        if best_key is None or key < best_key:
            best, best_key = cand, key
    return best, best_key


def _compound_lemma(word, known):
    """Prefixed compound of an irregular verb: detuvo -> detener,
    pospondra -> posponer, satisfizo -> satisfacer (old f- stem of hacer)."""
    for i in range(1, len(word) - 2):
        prefix, rest = word[:i], word[i:]
        base = IRREGULAR_VERB_MAP.get(rest)
        if base in _COMPOUND_BASES and prefix + base in known:
            return prefix + base
        if rest[0] == 'f' and IRREGULAR_VERB_MAP.get('h' + rest[1:]) == 'hacer' \
                and prefix + 'facer' in known:
            return prefix + 'facer'
    return None


def _verb_lemma(word, known, verb_context=False, reflexive=None):
    """Return (infinitive, 'irregular'|'regular_verb') or None.

    ``verb_context`` is False, True (after some clitic) or the clitic itself.
    """
    clitic = verb_context if isinstance(verb_context, str) else None
    if verb_context and word not in _FORCE_IRREGULAR:
        # After a clitic, a pronominal headword read with an indicative
        # ending beats the irregular map ("se viste" is VESTIR, SE, not ver).
        cand, key = _best_regular(word, known, reflexive if reflexive is not None else set(),
                                  clitic)
        if cand and not key[0] and key[1] == 0:
            return cand, 'regular_verb'
    if word in IRREGULAR_VERB_MAP:
        return IRREGULAR_VERB_MAP[word], 'irregular'
    # Future / conditional: infinitive + ending.
    for end in _FUT_COND:
        if word.endswith(end) and len(word) - len(end) >= 4:
            inf = word[:-len(end)]
            if inf.endswith(('ar', 'er', 'ir')):
                if verb_context and inf + 'se' in known and _agrees(_FUT_PERSON[end], clitic):
                    return inf + 'se', 'regular_verb'   # se levantara -> levantarse
                if inf in known:
                    return inf, 'regular_verb'
                if inf + 'se' in known:
                    return inf + 'se', 'regular_verb'
    cand, _key = _best_regular(word, known,
                               (reflexive if reflexive is not None else set()) if verb_context else None,
                               clitic)
    if cand:
        return cand, 'regular_verb'
    comp = _compound_lemma(word, known)
    if comp:
        return comp, 'irregular'
    return None


def _plural_candidates(word):
    out = []
    if len(word) > 3 and word.endswith('ces'):
        out.append(word[:-3] + 'z')
    if len(word) > 3 and word.endswith('s'):
        out.append(word[:-1])
    if len(word) > 4 and word.endswith('es'):
        out.append(word[:-2])
    return out


def _gender_candidates(word):
    """Feminine -> base: abogada -> abogado, doctora -> doctor, jefa -> jefe,
    actriz -> actor, alcaldesa -> alcalde, poetisa -> poeta."""
    out = []
    if len(word) > 3 and word.endswith('a'):
        out += [word[:-1] + 'o', word[:-1], word[:-1] + 'e']
    if len(word) > 5 and word.endswith('triz'):
        out.append(word[:-4] + 'tor')
    if len(word) > 6 and word.endswith('esa'):
        out += [word[:-2], word[:-3]]    # alcaldesa -> alcalde, baronesa -> baron
    if len(word) > 6 and word.endswith('isa'):
        out.append(word[:-3] + 'a')      # poetisa -> poeta
    return out


def _diminutive_candidates(word):
    out = []
    for suf in ('ecito', 'ecita', 'cito', 'cita', 'ito', 'ita', 'ico', 'ica', 'illo', 'illa'):
        # -ico/-ica on a two-letter stem is an adjective ending (unica), not
        # a diminutive.
        min_stem = 3 if suf in ('ico', 'ica') else 2
        if word.endswith(suf) and len(word) - len(suf) >= min_stem:
            stem = word[:-len(suf)]
            # A feminine diminutive points to the feminine noun first
            # (hijita -> hija, not hijo).
            if suf.endswith('a'):
                out += [stem + 'a', stem + 'o', stem + 'e', stem]
            else:
                out += [stem + 'o', stem + 'a', stem + 'e', stem]
            if stem.endswith('qu'):
                out += [stem[:-2] + 'co', stem[:-2] + 'ca']
            if stem.endswith('gu'):
                out += [stem[:-2] + 'go', stem[:-2] + 'ga']
    return out


def _participle_adjective(word, known):
    """Feminine participle -> masculine adjective headword (acabada ->
    acabado), checked before the verb rule turns it into the infinitive."""
    if len(word) > 5 and word.endswith(('ada', 'ida')):
        masc = word[:-1] + 'o'
        if masc in known:
            return masc
    return None


def _derivation(word, known):
    """-mente adverbs and -isimo superlatives -> adjective headword
    (generosamente -> generoso, peligrosisimo -> peligroso)."""
    if len(word) > 8 and word.endswith('mente') and word[-6] != 'o':
        base = word[:-5]
        if base in known:
            return base
        if base.endswith('a') and base[:-1] + 'o' in known:
            return base[:-1] + 'o'
        return None
    for suf in ('isimos', 'isimas', 'isimo', 'isima'):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            stem = word[:-len(suf)]
            cands = [stem + 'o', stem + 'e', stem]
            if stem.endswith('qu'):
                cands.append(stem[:-2] + 'co')     # riquisimo -> rico
            elif stem.endswith('gu'):
                cands.append(stem[:-2] + 'go')     # larguisimo -> largo
            elif stem.endswith('bil'):
                cands.append(stem[:-3] + 'ble')    # amabilisimo -> amable
            elif stem.endswith('c'):
                cands.append(stem[:-1] + 'z')      # felicisimo -> feliz
            for c in cands:
                if c in known:
                    return c
            return None
    return None


def _enclitic(word, known, reflexive=None):
    """Strip up to two trailing clitic pronouns and lemmatize the verb.
    A reflexive clitic prefers the pronominal headword (levantandose ->
    levantarse when both LEVANTAR and LEVANTARSE exist)."""
    rest = word
    for _ in range(2):
        for pr in _PRONOUNS:
            if rest.endswith(pr) and len(rest) - len(pr) >= 2:
                rest = rest[:-len(pr)]
                break
        else:
            return None
        refl = pr in _REFLEXIVE_CLITICS
        if rest.endswith(('ar', 'er', 'ir')):
            if refl and rest + 'se' in known:
                return rest + 'se'
            if rest in known:
                return rest
        if rest in _ENCLITIC_IMPERATIVE:
            return _ENCLITIC_IMPERATIVE[rest]
        res = _verb_lemma(rest, known, verb_context=refl, reflexive=reflexive)
        if res:
            return res[0]
    return None


def lemmatize(word_norm, known, verb_context=False, reflexive=None):
    """Return (lemma, method) for an accent-stripped lowercase word.

    ``verb_context``: the word follows a clitic pronoun, so a verb reading
    beats a homographic noun ("se burla", "te abrazo"). Pass the clitic
    itself ('se', 'me', ...) so that only an agreeing one selects the
    pronominal verb; True means "some clitic".
    ``reflexive``: norms of pronominal verbs, preferred in that context.
    """
    w = _strip_accents(word_norm.lower().strip())
    if not w:
        return word_norm, 'none'
    if verb_context and len(w) > 2:
        res = _verb_lemma(w, known, verb_context=verb_context, reflexive=reflexive)
        if res:
            return res
    irregular = IRREGULAR_VERB_MAP.get(w)
    if w in known and not (irregular and w in _FORCE_IRREGULAR):
        return w, 'exact'
    if irregular:
        return irregular, 'irregular'
    if w in _APOCOPE and _APOCOPE[w] in known:
        return _APOCOPE[w], 'irregular'
    if len(w) <= 2:
        return w, 'none'
    if w.endswith(('ar', 'er', 'ir')) and w + 'se' in known:
        return w + 'se', 'regular_verb'   # deprimir -> deprimirse

    plurals = _plural_candidates(w)
    for p in plurals:
        if p in known:
            return p, 'plural'

    bases = [w] + plurals
    for base in bases:
        adj = _participle_adjective(base, known)
        if adj:
            return adj, 'gender'
    der = _derivation(w, known)
    if der:
        return der, 'derivation'

    res = _verb_lemma(w, known)
    if res:
        return res

    for base in bases:
        for g in _gender_candidates(base):
            if g in known:
                return g, 'gender'
    for base in bases:
        for d in _diminutive_candidates(base):
            if d in known:
                return d, 'diminutive'

    # Dominican -ao for -ado ("quemao" -> "quemado", "cansao" -> "cansado").
    if len(w) > 4 and w.endswith(('ao', 'aos')):
        full = w[:-2] + 'ado' if w.endswith('ao') else w[:-3] + 'ados'
        lemma, how = lemmatize(full, known)
        if how != 'none':
            return lemma, 'derivation'

    lemma = _enclitic(w, known, reflexive)
    if lemma:
        return lemma, 'enclitic'
    return w, 'none'


def _add_norms(raw, known):
    if not raw:
        return
    text = _strip_accents(raw.lower())
    text = re.sub(r'\(([^)]*)\)', r' \1 ', text)  # drop parentheses, keep content
    text = re.sub(r'\s+', ' ', text).strip()
    parts = [p.strip() for p in text.split(',') if p.strip()]
    if not parts:
        return
    known.add(parts[0])
    for part in parts[1:]:
        # Short parts are gender suffixes ('abogado, da'), not words.
        if len(part) >= 4:
            known.add(part)


def build_known(db_path):
    """Return the set of reachable dictionary norms (bare lemmas)."""
    known = set()
    conn = sqlite3.connect('file:' + db_path.replace('\\', '/') + '?mode=ro', uri=True)
    try:
        cur = conn.cursor()
        for (norm,) in cur.execute('SELECT palabra_norm FROM palabras'):
            _add_norms(norm, known)
        try:
            for (norm,) in cur.execute('SELECT sinonimo_norm FROM sinonimos_mapeo'):
                _add_norms(norm, known)
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    return known


def build_reflexive(db_path):
    """Norms of pronominal verb headwords: 'aburrirse', or 'banar' for an
    entry stored as 'banar, se'. Used to prefer them after a clitic."""
    out = set()
    conn = sqlite3.connect('file:' + db_path.replace('\\', '/') + '?mode=ro', uri=True)
    try:
        for (norm,) in conn.execute('SELECT palabra_norm FROM palabras'):
            if not norm:
                continue
            text = re.sub(r'\([^)]*\)', ' ', _strip_accents(norm.lower()))
            parts = [' '.join(p.split()) for p in text.split(',')]
            head = parts[0]
            if not head or ' ' in head:
                continue
            if head.endswith(('arse', 'erse', 'irse')) or 'se' in parts[1:]:
                out.add(head)
    finally:
        conn.close()
    return out


if __name__ == '__main__':
    import os
    K = {'abogado', 'doctor', 'maestro', 'dia', 'libro', 'nino', 'hermano', 'bueno', 'comer',
         'trabajar', 'trabajo', 'dar', 'escribir', 'poder', 'cantar', 'vivir', 'luz', 'pan',
         'perro', 'cafe', 'ir', 'ver', 'saber', 'tener', 'decir', 'ser', 'estar', 'hablar',
         'empezar', 'jugar', 'pedir', 'conocer', 'cuenta', 'contar', 'amigo', 'casa', 'leer',
         'entender', 'venir', 'cansado', 'mucho', 'cancion', 'ayudar', 'estudiar', 'salir'}

    def L(w):
        return lemmatize(w, K)

    assert L('abogado') == ('abogado', 'exact')
    assert L('cuenta') == ('cuenta', 'exact')
    assert L('tengo') == ('tener', 'irregular')
    assert L('fui') == ('ir', 'irregular')
    assert L('fuimos') == ('ir', 'irregular')
    assert L('es') == ('ser', 'irregular')
    assert L('estoy') == ('estar', 'irregular')
    assert L('tendre') == ('tener', 'irregular')
    assert L('viniste') == ('venir', 'irregular')
    assert L('vaya') == ('ir', 'irregular')
    assert L('visto') == ('ver', 'irregular')
    assert L('comimos') == ('comer', 'regular_verb')
    assert L('comeran') == ('comer', 'regular_verb')
    assert L('comeria') == ('comer', 'regular_verb')
    assert L('trabaje') == ('trabajar', 'regular_verb')
    assert L('trabajando') == ('trabajar', 'regular_verb')
    assert L('cantaron') == ('cantar', 'regular_verb')
    assert L('cantabamos') == ('cantar', 'regular_verb')
    assert L('vivio') == ('vivir', 'regular_verb')
    assert L('cansadas')[0] == 'cansado'
    assert L('empiezo') == ('empezar', 'regular_verb')
    assert L('empece') == ('empezar', 'regular_verb')
    assert L('conozco') == ('conocer', 'irregular')
    assert L('dias') == ('dia', 'plural')
    assert L('libros') == ('libro', 'plural')
    assert L('ninos') == ('nino', 'plural')
    assert L('luces') == ('luz', 'plural')
    assert L('canciones') == ('cancion', 'plural')
    assert L('abogada') == ('abogado', 'gender')
    assert L('doctora') == ('doctor', 'gender')
    assert L('maestras')[0] == 'maestro'
    assert L('mucha') == ('mucho', 'gender')
    assert L('buen') == ('bueno', 'irregular')
    assert L('perrito') == ('perro', 'diminutive')
    assert L('cafecito') == ('cafe', 'diminutive')
    assert L('pancito') == ('pan', 'diminutive')
    assert L('amiguito')[0] == 'amigo'
    assert L('damelo') == ('dar', 'enclitic')
    assert L('dime') == ('decir', 'enclitic')
    assert L('escribirle') == ('escribir', 'enclitic')
    assert L('ayudarme') == ('ayudar', 'enclitic')
    assert L('xyzzy') == ('xyzzy', 'none')
    assert L('casas')[0] == 'casa'
    assert L('Comió') == ('comer', 'regular_verb')
    assert L('cansadamente') == ('cansado', 'derivation')
    assert L('cansao') == ('cansado', 'derivation')
    assert L('describio') == ('describio', 'none')
    db = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lsrd_dictionary.db')
    if os.path.exists(db):
        kn = build_known(db)
        assert 'abogado' in kn and len(kn) > 1500
        print('known size:', len(kn), 'reflexive:', len(build_reflexive(db)))
    print('morphology self-test OK')
