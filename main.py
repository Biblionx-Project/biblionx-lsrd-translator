import sqlite3
import json
from nlp_engine import LSRDNlpEngine
from translator import LSRDTranslator

def run_cli_translator():
    print("=" * 70)
    print("      BIBLIONX - MOTOR DE TRADUCCIÓN A LENGUA DE SEÑAS DOMINICANA (LSRD)")
    print("=" * 70)
    print("Escribe una frase en español para traducirla a LSRD (o escribe 'salir'):\n")

    nlp = LSRDNlpEngine()
    translator = LSRDTranslator()

    while True:
        try:
            texto = input("Español > ").strip()
            if not texto:
                continue
            if texto.lower() in ['salir', 'exit', 'quit']:
                print("¡Hasta luego!")
                break

            nlp_res = nlp.process(texto)
            sequence = translator.translate_sequence(nlp_res['secuencia_lsrd'])

            print("\n--- RESULTADO DE LA TRADUCCIÓN A LSRD ---")
            print(f"Oración Original:      \"{texto}\"")
            print(f"Secuencia Gramatical:  {nlp_res['secuencia_lsrd']}")
            print(f"Total de Señas:        {len(sequence)}\n")

            print("SECUENCIA ORDENADA DE SEÑAS:")
            for idx, item in enumerate(sequence, 1):
                tipo = f"(Deletreo '{item['letra']}')" if item.get('es_deletreo') else "(Seña Léxica)"
                desc = item.get('descripcion_sena') or item.get('definicion_es', '')[:60]
                print(f"  {idx:02d}. {item['palabra_es']:<20} {tipo:<20} | Pág. {item.get('pagina', 'N/A')}")
                print(f"      - Movimiento: {desc}")
                print(f"      - Imagen:     {item.get('ruta_imagen')}\n")

        except KeyboardInterrupt:
            print("\nOperación cancelada.")
            break
        except Exception as e:
            print(f"Error procesando la traducción: {e}")

if __name__ == "__main__":
    run_cli_translator()
