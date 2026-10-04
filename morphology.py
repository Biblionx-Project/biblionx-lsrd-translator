"""Conservative Spanish morphological lemmatizer for the LSRD translator.

Pure Python, standard library only. All input is expected to be lowercase
with accents already stripped (the dictionary "norm" form).

A lemma different from the input is only returned when it is present in the
`known` set (reachable dictionary norms) or comes from the explicit
irregular-verb map. This prevents inventing words that have no sign.

Public API:
    lemmatize(word_norm, known) -> (lemma, method)
    build_known(db_path)        -> set of reachable dictionary norms

method is one of: 'exact', 'irregular', 'regular_verb', 'plural', 'gender',
'diminutive', 'enclitic', 'none'.
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
}

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
# Future / conditional: infinitive + ending (word = inf + ending).
_FUT_COND = 'e as a emos eis an ia ias iamos iais ian'.split()
_PRONOUNS = sorted(('me', 'te', 'se', 'lo', 'la', 'le', 'nos', 'os', 'los', 'las', 'les'),
                   key=len, reverse=True)


def _strip_accents(text):
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def _stem_variants(stem):
    """Undo common stem alternations and spelling changes of verb stems."""
    vowel = [stem]
    for pat, rep in (('ie', 'e'), ('ue', 'o'), ('ue', 'u')):
        i = stem.rfind(pat)
        if i != -1:
            vowel.append(stem[:i] + rep + stem[i + len(pat):])
    for pat, rep in (('i', 'e'), ('u', 'o')):
        i = stem.rfind(pat)
        if i != -1 and i >= len(stem) - 3:
            vowel.append(stem[:i] + rep + stem[i + 1:])
    out = []
    for v in vowel:
        out.append(v)
        if v.endswith('zc'):
            out.append(v[:-2] + 'c')
        elif v.endswith('qu'):
            out.append(v[:-2] + 'c')
        elif v.endswith('gu'):
            out.append(v[:-2] + 'g')
        elif v.endswith('c'):
            out.append(v[:-1] + 'z')
        elif v.endswith('j'):
            out.append(v[:-1] + 'g')
    return out


def _verb_lemma(word, known):
    """Return (infinitive, 'irregular'|'regular_verb') or None."""
    if word in IRREGULAR_VERB_MAP:
        return IRREGULAR_VERB_MAP[word], 'irregular'
    # Future / conditional: infinitive + ending.
    for end in _FUT_COND:
        if word.endswith(end) and len(word) - len(end) >= 4:
            inf = word[:-len(end)]
            if inf in known and inf.endswith(('ar', 'er', 'ir')):
                return inf, 'regular_verb'
    for suf, ending in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 2:
            stem = word[:-len(suf)]
            for var in _stem_variants(stem):
                cand = var + ending
                if cand in known and cand != word:
                    return cand, 'regular_verb'
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
    """Feminine -> base: abogada -> abogado, doctora -> doctor, jefa -> jefe."""
    if len(word) > 3 and word.endswith('a'):
        return [word[:-1] + 'o', word[:-1], word[:-1] + 'e']
    return []


def _diminutive_candidates(word):
    out = []
    for suf in ('ecito', 'ecita', 'cito', 'cita', 'ito', 'ita', 'ico', 'ica', 'illo', 'illa'):
        if word.endswith(suf) and len(word) - len(suf) >= 2:
            stem = word[:-len(suf)]
            out += [stem + 'o', stem + 'a', stem + 'e', stem]
            if stem.endswith('qu'):
                out += [stem[:-2] + 'co', stem[:-2] + 'ca']
            if stem.endswith('gu'):
                out += [stem[:-2] + 'go', stem[:-2] + 'ga']
    return out


def _enclitic(word, known):
    """Strip up to two trailing clitic pronouns and lemmatize the verb."""
    rest = word
    for _ in range(2):
        for pr in _PRONOUNS:
            if rest.endswith(pr) and len(rest) - len(pr) >= 2:
                rest = rest[:-len(pr)]
                break
        else:
            return None
        if rest in known and rest.endswith(('ar', 'er', 'ir')):
            return rest
        if rest in _ENCLITIC_IMPERATIVE:
            return _ENCLITIC_IMPERATIVE[rest]
        res = _verb_lemma(rest, known)
        if res:
            return res[0]
    return None


def lemmatize(word_norm, known):
    """Return (lemma, method) for an accent-stripped lowercase word."""
    w = _strip_accents(word_norm.lower().strip())
    if not w:
        return word_norm, 'none'
    irregular = IRREGULAR_VERB_MAP.get(w)
    if w in known and not (irregular and w in _FORCE_IRREGULAR):
        return w, 'exact'
    if irregular:
        return irregular, 'irregular'
    if w in _APOCOPE and _APOCOPE[w] in known:
        return _APOCOPE[w], 'irregular'
    if len(w) <= 2:
        return w, 'none'

    plurals = _plural_candidates(w)
    for p in plurals:
        if p in known:
            return p, 'plural'

    res = _verb_lemma(w, known)
    if res:
        return res

    bases = [w] + plurals
    for base in bases:
        for g in _gender_candidates(base):
            if g in known:
                return g, 'gender'
    for base in bases:
        for d in _diminutive_candidates(base):
            if d in known:
                return d, 'diminutive'

    lemma = _enclitic(w, known)
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
    db = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lsrd_dictionary.db')
    if os.path.exists(db):
        kn = build_known(db)
        assert 'abogado' in kn and len(kn) > 1500
        print('known size:', len(kn))
    print('morphology self-test OK')
