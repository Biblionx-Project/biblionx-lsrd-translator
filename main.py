import sys

from nlp_engine import LSRDNlpEngine
from translator import LSRDTranslator

def run_cli_translator():
    if not sys.stdin.isatty():  # piped input/output: force UTF-8 on Windows
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
    print("=" * 70)
    print("      BIBLIONX - DOMINICAN SIGN LANGUAGE (LSRD) TRANSLATION ENGINE")
    print("=" * 70)
    print("Type a sentence in Spanish to translate it to LSRD (or type 'exit'):\n")

    nlp = LSRDNlpEngine()
    translator = LSRDTranslator()

    while True:
        try:
            try:
                texto = input("Spanish > ").strip()
            except EOFError:
                break
            if not texto:
                continue
            if texto.lower() in ['salir', 'exit', 'quit']:
                print("Goodbye!")
                break

            nlp_res = nlp.process(texto)
            sequence = translator.translate_sequence(nlp_res['secuencia_lsrd'])  # carries phrase/morphology hints

            print("\n--- LSRD TRANSLATION RESULT ---")
            print(f"Original sentence:     \"{texto}\"")
            print(f"Grammatical sequence:  {nlp_res['secuencia_lsrd']}")
            print(f"Total signs:           {len(sequence)}\n")

            print("ORDERED SIGN SEQUENCE:")
            for idx, item in enumerate(sequence, 1):
                tipo = f"(Fingerspelled '{item['letra']}')" if item.get('es_deletreo') else f"(Sign: {item.get('match_method', 'exact')})"
                desc = item.get('descripcion_sena') or item.get('definicion_es', '')[:60]
                print(f"  {idx:02d}. {item['palabra_es']:<20} {tipo:<24} | conf {item.get('confidence', 0):.2f} | Page {item.get('pagina', 'N/A')}")
                print(f"      - Movement: {desc}")
                print(f"      - Image:    {item.get('ruta_imagen')}\n")

        except KeyboardInterrupt:
            print("\nOperation cancelled.")
            break
        except Exception as e:
            print(f"Error processing translation: {e}")

if __name__ == "__main__":
    run_cli_translator()
