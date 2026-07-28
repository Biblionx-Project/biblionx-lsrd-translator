import re
import unicodedata

LSRD_STOP_WORDS = {
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
    'de', 'del', 'al', 'en', 'para', 'por', 'con', 'sin', 'sobre',
    'que', 'cual', 'quien', 'donde', 'como', 'cuando', 'este', 'esta',
    'estos', 'estas', 'ese', 'esa', 'esos', 'esas', 'aquel', 'aquella'
}

AUXILIARY_VERBS = {'es', 'son', 'ser', 'esta', 'estan', 'estar', 'fue', 'fueron', 'era', 'eran'}

def normalize_word(word):
    word = word.lower().strip()
    word = re.sub(r'[^\w\s]', '', word)
    nfkd_form = unicodedata.normalize('NFKD', word)
    only_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return only_ascii

def lemmatize_word(word_norm):
    if len(word_norm) <= 3:
        return word_norm
    if word_norm.endswith(('ar', 'er', 'ir')):
        return word_norm
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
