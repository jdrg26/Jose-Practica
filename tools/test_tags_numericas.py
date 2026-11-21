import unittest
from migrar import etiquetas_json

class TestTagsNumericas(unittest.TestCase):
    def test_etiqueta_2026(self):
        self.assertEqual(
            etiquetas_json(["2026"]),
            r'{"\ufe0e2026":"a3a10ebe2ba87b81b32702fce0637e74"}'
        )
