import os
import sqlite3
import unicodedata

# Ruta relativa a la base de datos dentro de la misma carpeta
DB_PATH = os.path.join(os.path.dirname(__file__), "lsrd_dictionary.db")

DACTYL_LETTER_MAP = {
    'a': 'lsrd_0001', 'b': 'lsrd_0262', 'c': 'lsrd_0372', 'd': 'lsrd_0678',
    'e': 'lsrd_0807', 'f': 'lsrd_0971', 'g': 'lsrd_1040', 'h': 'lsrd_1090',
    'i': 'lsrd_1155', 'j': 'lsrd_1222', 'k': 'lsrd_1242', 'l': 'lsrd_1248',
    'm': 'lsrd_1327', 'n': 'lsrd_1475', 'ñ': 'lsrd_1526', 'o': 'lsrd_1527',
    'p': 'lsrd_1582', 'q': 'lsrd_1799', 'r': 'lsrd_1815', 's': 'lsrd_1907',
    't': 'lsrd_2028', 'u': 'lsrd_2157', 'v': 'lsrd_2170', 'w': 'lsrd_2237',
    'x': 'lsrd_2239', 'y': 'lsrd_2240', 'z': 'lsrd_2247'
}

class LSRDTranslator:
    def __init__(self, db_path=DB_PATH):
        self.db_path = os.path.abspath(db_path)

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def find_sign_by_word(self, word_norm):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT p.id, p.palabra_es, p.definicion_es, p.pagina, c.nombre as categoria,
                   sd.descripcion_sena, ri.ruta_imagen
            FROM palabras p
            LEFT JOIN categorias c ON p.categoria_id = c.id
            LEFT JOIN senas_descripciones sd ON p.id = sd.palabra_id
            LEFT JOIN rutas_imagenes ri ON p.id = ri.palabra_id
            WHERE p.palabra_norm = ? OR p.palabra_norm LIKE ?
            LIMIT 1
        """, (word_norm, f"{word_norm},%"))
        
        row = cursor.fetchone()
        
        if not row:
            cursor.execute("""
                SELECT p.id, p.palabra_es, p.definicion_es, p.pagina, c.nombre as categoria,
                       sd.descripcion_sena, ri.ruta_imagen
                FROM sinonimos_mapeo sm
                JOIN palabras p ON sm.palabra_id = p.id
                LEFT JOIN categorias c ON p.categoria_id = c.id
                LEFT JOIN senas_descripciones sd ON p.id = sd.palabra_id
                LEFT JOIN rutas_imagenes ri ON p.id = ri.palabra_id
                WHERE sm.sinonimo_norm = ?
                LIMIT 1
            """, (word_norm,))
            row = cursor.fetchone()
            
        conn.close()
        return dict(row) if row else None

    def get_fingerspelling_sequence(self, word):
        sequence = []
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for char in word.lower():
            if char in DACTYL_LETTER_MAP:
                sign_id = DACTYL_LETTER_MAP[char]
                cursor.execute("""
                    SELECT p.id, p.palabra_es, p.definicion_es, p.pagina, c.nombre as categoria,
                           sd.descripcion_sena, ri.ruta_imagen
                    FROM palabras p
                    LEFT JOIN categorias c ON p.categoria_id = c.id
                    LEFT JOIN senas_descripciones sd ON p.id = sd.palabra_id
                    LEFT JOIN rutas_imagenes ri ON p.id = ri.palabra_id
                    WHERE p.id = ?
                    LIMIT 1
                """, (sign_id,))
                row = cursor.fetchone()
                if row:
                    item = dict(row)
                    item['es_deletreo'] = True
                    item['letra'] = char.upper()
                    sequence.append(item)
        conn.close()
        return sequence

    def translate_sequence(self, tokens_lsrd):
        result_sequence = []
        for token in tokens_lsrd:
            sign_match = self.find_sign_by_word(token)
            if sign_match:
                sign_match['es_deletreo'] = False
                sign_match['letra'] = None
                result_sequence.append(sign_match)
            else:
                dactyl_seq = self.get_fingerspelling_sequence(token)
                result_sequence.extend(dactyl_seq)
        return result_sequence
