"""tools/test_migrar.py — pruebas de las funciones PURAS de migrar.py.

Como `transformar` no toca disco ni SQL, se prueba sola, sin base de datos.
Ejecuta:  make test   (o: python3 -m unittest discover -s tools -v)
"""
import unittest

from migrar import SQL_DATETIME_ZERO, etiquetas_json, fecha_chyrp, slugify, transformar

ENTRADA = {
    "slug": "hola-hugo",
    "titulo": "Hola, Hugo",
    "fecha": "2026-10-27",
    "cuerpo": "Texto con **Markdown**.",
    "tags": ["hugo", "Árbol B"],
    "draft": False,
}


class TestSlugify(unittest.TestCase):
    def test_tildes_y_espacios(self):
        self.assertEqual(slugify("Árbol B"), "arbol-b")

    def test_signos(self):
        self.assertEqual(slugify("¡Hola, Mundo!"), "hola-mundo")


class TestFecha(unittest.TestCase):
    def test_solo_dia(self):
        self.assertEqual(fecha_chyrp("2026-10-27", "X"), "2026-10-27 00:00:00")

    def test_con_hora(self):
        self.assertEqual(fecha_chyrp("2026-10-27T09:30", "X"), "2026-10-27 09:30:00")

    def test_sin_fecha_usa_el_valor_por_defecto(self):
        self.assertEqual(fecha_chyrp("", "2026-11-16 12:00:00"), "2026-11-16 12:00:00")


class TestEtiquetas(unittest.TestCase):
    def test_formato_del_modulo_tags(self):
        self.assertEqual(etiquetas_json(["sql", "Árbol B"]),
                         '{"sql":"sql","\\u00c1rbol B":"arbol-b"}')

    def test_sin_etiquetas(self):
        self.assertEqual(etiquetas_json([]), "[]")


class TestTransformar(unittest.TestCase):
    def setUp(self):
        self.fila = transformar(ENTRADA, user_id=1, ahora="2026-11-16 12:00:00")

    def test_fila_de_posts(self):
        self.assertEqual(self.fila["post"]["clean"], "hola-hugo")
        self.assertEqual(self.fila["post"]["status"], "public")
        self.assertEqual(self.fila["post"]["created_at"], "2026-10-27 00:00:00")
        self.assertEqual(self.fila["post"]["updated_at"], SQL_DATETIME_ZERO)

    def test_atributos(self):
        self.assertEqual(set(self.fila["attrs"]), {"title", "body", "tags"})
        self.assertEqual(self.fila["attrs"]["body"], "Texto con **Markdown**.")

    def test_borrador(self):
        borrador = transformar({**ENTRADA, "draft": True}, 1, "ahora")
        self.assertEqual(borrador["post"]["status"], "draft")

    def test_es_pura(self):
        # Misma entrada, mismo resultado, y la entrada original no cambia.
        self.assertEqual(self.fila, transformar(ENTRADA, 1, "2026-11-16 12:00:00"))
        self.assertEqual(ENTRADA["tags"], ["hugo", "Árbol B"])


if __name__ == "__main__":
    unittest.main()
