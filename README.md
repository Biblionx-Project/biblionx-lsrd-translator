# Modelo de Traducción a Lengua de Señas Dominicana (LSRD)

## 📌 Descripción General

Este directorio contiene la implementación autónoma y portátil del **Motor de Traducción de Español a Lengua de Señas Dominicana (LSRD)**. 

Está diseñado como un **paquete exportable e independiente** que incluye la base de datos relacional SQLite (`lsrd_dictionary.db`), la totalidad de las 2,458 ilustraciones vectoriales recortadas (`extracted_images/`), el motor de Procesamiento de Lenguaje Natural (NLP) y los scripts de prueba interactiva. 

Cualquier desarrollado, docente o investigador puede copiar este directorio a otro equipo y comenzar a realizar consultas o traducciones inmediatamente **sin necesidad de instalar dependencias externas**.

---

## 📦 Inventario de Archivos del Paquete

| Archivo / Carpeta | Descripción del Recurso |
| :--- | :--- |
| **`lsrd_dictionary.db`** | Base de datos SQLite3 con 2,458 lemas, categorías gramaticales, descripciones de movimiento y referencias al PDF oficial. |
| **`extracted_images/`** | Carpeta con las 2,458 imágenes vectoriales de señas recortadas en formato PNG (`lsrd_0001.png` a `lsrd_2458.png`). |
| **`main.py`** | Interfaz interactiva de consola (CLI) para ingresar texto en español y ver la traducción ordenada en LSRD. |
| **`nlp_engine.py`** | Módulo NLP de normalización, filtrado de stopwords, lematización verbal y reordenamiento sintáctico. |
| **`translator.py`** | Mapeador relacional de señas con resolución de sinónimos y fallback dactilológico (deletreo A-Z). |
| **`README.md`** | Este manual explicativo de arquitectura, consultas e instrucciones de uso. |

---

## 🏗️ Arquitectura y Funcionamiento del Modelo

El modelo traduce oraciones del español a LSRD a través de un flujo estructurado de 3 fases:

```
[Texto en Español de Entrada] (Ej. "El abogado no trabaja hoy en la escuela")
       │
       ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 1. Módulo NLP de Preprocesamiento (nlp_engine.py)                           │
 │    - Tokenización y Normalización de minúsculas/acentos                    │
 │    - Depuración de Stop-words y artículos sin equivalencia directa          │
 │    - Lematización verbal (ej: "trabajaba" -> "trabajar")                    │
 │    - Reordenamiento Sintáctico LSRD: [TIEMPO] + [LUGAR] + [SUJETO] + [VERBO] + [NEGACIÓN] │
 └───────────────────────────────────┬─────────────────────────────────────────┘
                                     │ (Secuencia Gramatical LSRD)
                                     ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 2. Mapeador de la Base de Datos Local (translator.py & lsrd_dictionary.db)  │
 │    - Consulta en SQLite por palabra o sinónimos de la tabla 'palabras'     │
 │    - Extrae parámetros querológicos (forma de mano, orientación, movimiento)│
 │    - Fallback a Dactilología A-Z: Si una palabra o nombre propio no existe, │
 │      se sustituye por la secuencia de señas del abecedario dactilológico.   │
 └───────────────────────────────────┬─────────────────────────────────────────┘
                                     │
                                     ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 3. Secuencia Resultante de Salida (main.py)                                 │
 │    - Lista ordenada de señas con su ID en DB (`lsrd_XXXX`)                   │
 │    - Descripción del movimiento querológico (Stokoe)                        │
 │    - Número de página del Diccionario Oficial de LSRD                       │
 │    - Ruta local a la ilustración vectorial (`extracted_images/lsrd_XXXX.png`) │
 └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Instrucciones de Ejecución (Para un Nuevo Usuario)

Cualquier persona que reciba esta carpeta solo requiere tener **Python 3.6 o superior** instalado (utiliza la librería estándar de Python, **no requiere `pip install`**):

1. Abrir una terminal en este directorio:
   ```bash
   cd "Modelo De traduccion"
   ```

2. Ejecutar el consolador interactivo:
   ```bash
   python3 main.py
   ```

3. Escribir cualquier frase en español.

### Ejemplo de Salida en Terminal:
```text
======================================================================
      BIBLIONX - MOTOR DE TRADUCCIÓN A LENGUA DE SEÑAS DOMINICANA (LSRD)
======================================================================
Escribe una frase en español para traducirla a LSRD (o escribe 'salir'):

Español > El abogado no trabaja hoy en la escuela

--- RESULTADO DE LA TRADUCCIÓN A LSRD ---
Oración Original:      "El abogado no trabaja hoy en la escuela"
Secuencia Gramatical:  ['hoy', 'escuela', 'abogado', 'trabajar', 'no']
Total de Señas:        5

SECUENCIA ORDENADA DE SEÑAS:
  01. HOY                  (Seña Léxica)        | Pág. 210
      - Movimiento: Las manos en forma de Y con las palmas hacia arriba bajan simultáneamente en rectas paralelas.
      - Imagen:     extracted_images/lsrd_1146.png

  02. ESCUELA              (Seña Léxica)        | Pág. 167
      - Movimiento: Las manos planas con las palmas enfrentadas; la mano dominante arriba con los dedos hacia afuera sobre la otra mano...
      - Imagen:     extracted_images/lsrd_0908.png

  03. ABOGADO,DA           (Seña Léxica)        | Pág. 30
      - Movimiento: La mano dominante en forma de L toca arriba y abajo la mano plana contraria.
      - Imagen:     extracted_images/lsrd_0009.png

  04. TRABAJAR             (Seña Léxica)        | Pág. 376
      - Movimiento: Laborar, realizar una actividad que supone esfuerzo...
      - Imagen:     extracted_images/lsrd_2124.png

  05. NO                   (Seña Léxica)        | Pág. 272
      - Movimiento: La mano en forma de 3 cerrado con la palma hacia afuera, une los dedos mayor, índice y pulgar...
      - Imagen:     extracted_images/lsrd_1503.png
```

---

## 🗄️ Guía para Desarrolladores: Consultas Directas a `lsrd_dictionary.db`

La base de datos relacional `lsrd_dictionary.db` consta de 5 tablas principales:
- `palabras` (ID, lemma, lema normalizado, categoría, página).
- `categorias` (Nombres de categorías gramaticales).
- `senas_descripciones` (Movimientos y descripción morfológica).
- `rutas_imagenes` (Ruta a los archivos PNG en `extracted_images/`).
- `sinonimos_mapeo` (Variaciones de flexión y sinónimos).

### Ejemplo 1: Consultar con SQLite CLI en la terminal
```bash
sqlite3 lsrd_dictionary.db "SELECT p.palabra_es, s.descripcion_sena FROM palabras p JOIN senas_descripciones s ON p.id = s.palabra_id WHERE p.palabra_norm = 'profesor';"
```

### Ejemplo 2: Consultar mediante Script de Python
```python
import sqlite3

# Conectar a la BD local dentro del paquete
conn = sqlite3.connect("lsrd_dictionary.db")
cursor = conn.cursor()

# Búsqueda por palabra clave o lema
cursor.execute("""
    SELECT p.id, p.palabra_es, c.nombre, s.descripcion_sena, r.ruta_imagen
    FROM palabras p
    LEFT JOIN categorias c ON p.categoria_id = c.id
    LEFT JOIN senas_descripciones s ON p.id = s.palabra_id
    LEFT JOIN rutas_imagenes r ON p.id = r.palabra_id
    WHERE p.palabra_norm = 'biblioteca'
""")

row = cursor.fetchone()
print(f"ID: {row[0]} | Seña: {row[1]} ({row[2]})")
print(f"Movimiento Querológico: {row[3]}")
print(f"Imagen PNG: {row[4]}")
```
