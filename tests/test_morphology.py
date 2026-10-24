import unittest

import _common  # noqa: F401
import morphology
import nlp_engine


class MorphologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.known = nlp_engine.get_resources().known

    def lem(self, word):
        return morphology.lemmatize(word, self.known)[0]

    def test_regular_verb_tenses(self):
        for form in ("vivieron", "vivimos", "vivire", "vivia"):
            self.assertEqual(self.lem(form), "vivir", form)
        for form in ("estudiaron", "estudiando"):
            self.assertEqual(self.lem(form), "estudiar", form)
        self.assertEqual(self.lem("hablaron"), "hablar")

    def test_irregular_verbs(self):
        cases = {"quiero": "querer", "quisieron": "querer", "tengo": "tener",
                 "dijo": "decir", "hizo": "hacer", "fui": "ir", "fueron": "ser"}
        for form, lemma in cases.items():
            self.assertEqual(self.lem(form), lemma, form)

    def test_plural(self):
        self.assertEqual(self.lem("casas"), "casa")
        self.assertEqual(self.lem("amigos"), "amigo")
        self.assertEqual(self.lem("profesores"), "profesor")

    def test_gender(self):
        self.assertEqual(self.lem("abogada"), "abogado")
        self.assertEqual(self.lem("profesora"), "profesor")

    def test_enclitics(self):
        self.assertEqual(self.lem("estudiarlo"), "estudiar")
        self.assertEqual(self.lem("dime"), "decir")
        self.assertEqual(self.lem("dandole"), "dar")

    def test_known_word_is_exact(self):
        self.assertEqual(morphology.lemmatize("casa", self.known), ("casa", "exact"))

    def test_unknown_word_is_unchanged(self):
        self.assertEqual(morphology.lemmatize("xyzqwk", self.known), ("xyzqwk", "none"))

    def test_protected_senas_not_lemmatized(self):
        eng = nlp_engine.LSRDNlpEngine()
        self.assertEqual(eng._lemmatize("senas"), ("senas", "exact"))
        self.assertEqual(eng._lemmatize("sena"), ("sena", "exact"))

    def test_engine_marks_method(self):
        eng = nlp_engine.LSRDNlpEngine()
        self.assertEqual(eng._lemmatize("casas"), ("casa", "morphology"))
        self.assertEqual(eng._lemmatize("casa"), ("casa", "exact"))


if __name__ == "__main__":
    unittest.main()


class StressedPreteriteTests(unittest.TestCase):
    """The written accent is the only cue separating "trabajó" from "trabajo"."""

    @classmethod
    def setUpClass(cls):
        cls.engine = nlp_engine.LSRDNlpEngine()

    def seq(self, text):
        return list(self.engine.process(text)["secuencia_lsrd"])

    def test_accented_preterite_becomes_verb(self):
        self.assertIn("trabajar", self.seq("Mi hermana no trabajó hoy"))
        self.assertIn("trabajar", self.seq("Ayer trabajé mucho"))

    def test_unaccented_noun_is_kept(self):
        self.assertIn("trabajo", self.seq("Mi trabajo es bueno"))


class GenericMorphologyRuleTests(unittest.TestCase):
    """Generic gaps found by the A-Z reachability audit (v2.3). Each case
    uses a headword of the official dictionary."""

    @classmethod
    def setUpClass(cls):
        cls.known = nlp_engine.get_resources().known
        cls.reflexive = nlp_engine.get_resources().reflexive

    def lem(self, word, **kw):
        return morphology.lemmatize(word, self.known, reflexive=self.reflexive, **kw)[0]

    def test_pronominal_only_headwords(self):
        # Only ABURRIRSE / DEPRIMIRSE / MUDARSE exist: conjugations add -se.
        for form in ("aburren", "aburrio", "aburrido", "aburriendose"):
            self.assertEqual(self.lem(form), "aburrirse", form)
        for form in ("deprimir", "deprimen", "deprimiendo"):
            self.assertEqual(self.lem(form), "deprimirse", form)
        self.assertEqual(self.lem("mudaron"), "mudarse")

    def test_bare_person_endings_do_not_reach_pronominal_only_verbs(self):
        # "mudo" (mute) and "muda" are adjectives far more often than verbs.
        self.assertNotEqual(self.lem("mudo"), "mudarse")
        self.assertNotEqual(self.lem("muda"), "mudarse")
        self.assertEqual(self.lem("mudo", verb_context="me"), "mudarse")

    def test_clitic_prefers_agreeing_pronominal_verb(self):
        self.assertEqual(self.lem("levanto", verb_context="me"), "levantarse")
        self.assertEqual(self.lem("levanto"), "levantar")
        self.assertEqual(self.lem("burla", verb_context="se"), "burlarse")
        self.assertEqual(self.lem("burla"), "burla")
        self.assertEqual(self.lem("sienta", verb_context="se"), "sentarse")
        self.assertEqual(self.lem("siente", verb_context="se"), "sentir")
        self.assertEqual(self.lem("viste", verb_context="se"), "vestir")
        # Dative "me" with a 3rd-person verb is not reflexive.
        self.assertEqual(self.lem("parece", verb_context="me"), "parecer")

    def test_clitic_turns_homographic_noun_into_verb(self):
        self.assertEqual(self.lem("abrazo", verb_context="te"), "abrazar")
        self.assertEqual(self.lem("pregunta", verb_context="le"), "preguntar")
        self.assertEqual(self.lem("abrazo"), "abrazo")

    def test_feminine_participle_reaches_adjective(self):
        for form, lemma in (("acabada", "acabado"), ("terminadas", "terminado"),
                            ("escondida", "escondido"), ("conocidas", "conocido")):
            self.assertEqual(self.lem(form), lemma, form)

    def test_indicative_reading_beats_subjunctive(self):
        self.assertEqual(self.lem("creen"), "creer")    # not crear
        self.assertEqual(self.lem("venden"), "vender")  # not vendar
        self.assertEqual(self.lem("vende"), "vender")
        self.assertEqual(self.lem("vendo"), "vender")

    def test_stem_alternations_follow_the_conjugation(self):
        self.assertEqual(self.lem("burra"), "burro")   # u -> o is -ir only
        self.assertNotEqual(self.lem("patio"), "patear")  # i -> e is -ir only
        self.assertNotEqual(self.lem("rojo"), "rogar")
        self.assertEqual(self.lem("huele"), "oler")
        self.assertEqual(self.lem("construye"), "construir")
        self.assertEqual(self.lem("influyen"), "influir")

    def test_compounds_of_irregular_verbs(self):
        cases = {"detuvo": "detener", "detengo": "detener", "detendra": "detener",
                 "sostuvieron": "sostener", "pospuso": "posponer", "pospuesto": "posponer",
                 "bendijo": "bendecir", "envuelto": "envolver", "descrito": "describir",
                 "satisfizo": "satisfacer", "satisfecho": "satisfacer"}
        for form, lemma in cases.items():
            self.assertEqual(self.lem(form), lemma, form)

    def test_reir_paradigm(self):
        self.assertEqual(self.lem("riendo"), "reir")   # not rendir
        self.assertEqual(self.lem("rieron"), "reir")
        self.assertEqual(self.lem("rio"), "rio")       # bare word: the river
        self.assertEqual(self.lem("rio", verb_context="se"), "reir")

    def test_irregular_feminine_and_diminutive(self):
        self.assertEqual(self.lem("actriz"), "actor")
        self.assertEqual(self.lem("actrices"), "actor")
        self.assertEqual(self.lem("alcaldesa"), "alcalde")
        self.assertEqual(self.lem("hijita"), "hija")

    def test_adverbs_superlatives_and_dominican_ao(self):
        self.assertEqual(self.lem("generosamente"), "generoso")
        self.assertEqual(self.lem("incorrectamente"), "incorrecto")
        self.assertEqual(self.lem("humildemente"), "humilde")
        self.assertEqual(self.lem("peligrosisimo"), "peligroso")
        self.assertEqual(self.lem("picantisimo"), "picante")
        self.assertEqual(self.lem("quemao"), "quemado")


class SentenceMorphologyTests(unittest.TestCase):
    """Context rules in nlp_engine: clitics, written accents, inflected phrases."""

    @classmethod
    def setUpClass(cls):
        cls.engine = nlp_engine.LSRDNlpEngine()

    def seq(self, text):
        return list(self.engine.process(text)["secuencia_lsrd"])

    def test_reflexive_clitic_sentences(self):
        self.assertIn("burlarse", self.seq("Pedro se burla de todos"))
        self.assertIn("levantarse", self.seq("Me levanto temprano"))
        self.assertIn("levantarse", self.seq("Ella se levantó tarde"))
        self.assertIn("sentarse", self.seq("Me senté en la silla"))
        self.assertIn("parecer", self.seq("Me parece bien"))

    def test_sabe_and_te_with_accent_are_not_clitics(self):
        self.assertNotIn("freir", self.seq("Un té frío"))
        self.assertIn("nadar", self.seq("Yo sé nadar"))

    def test_accented_iar_preterite_and_imperfect(self):
        self.assertIn("cambiar", self.seq("Juan cambió el carro"))
        self.assertIn("medir", self.seq("La mesa medía dos metros"))
        self.assertIn("cambio", self.seq("El cambio es bueno"))
        self.assertNotIn("ver", self.seq("Vía pública"))

    def test_inflected_multiword_entries(self):
        self.assertIn("arma de fuego", self.seq("Tiene armas de fuego"))
        self.assertIn("cruzar las piernas", self.seq("Ella cruzó las piernas"))
        self.assertIn("lavarse las manos", self.seq("Me lavo las manos"))
        self.assertIn("hacer clic", self.seq("Hace clic aquí"))

    def test_copula_is_not_read_as_phrase_verb(self):
        # "es humano" is ser + adjective, not the SER HUMANO entry.
        self.assertNotIn("ser humano, humano, na", self.seq("Es humano"))
