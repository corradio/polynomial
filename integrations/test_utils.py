from unittest import TestCase

from integrations import INTEGRATION_CLASSES
from integrations.utils import deofuscate_protected_fields, obfuscate_protected_fields


class UnitTestCase(TestCase):
    def setUp(self):
        self.config = {
            "database_connection": {
                "host": "x",
                "port": 5432,
                "dbname": "x",
                "user": "x",
                "password": "very_secret_password",
            },
            "sql_query_template": "x",
        }
        self.integration_id = "postgresql"

    def test_obfuscation(self):
        protected_copy = obfuscate_protected_fields(
            self.config, INTEGRATION_CLASSES[self.integration_id]
        )
        self.assertNotEqual(protected_copy, self.config, "Should return a copy")
        self.assertDictEqual(
            protected_copy,
            {
                "database_connection": {
                    "host": "x",
                    "port": 5432,
                    "dbname": "x",
                    "user": "x",
                    "password": "value_has_been_hidden_for_security_reasons",
                },
                "sql_query_template": "x",
            },
        )
        # Reverse
        new_config = {
            "database_connection": {
                "host": "y",
                "port": 54320,
                "dbname": "y",
                "user": "y",
                "password": "value_has_been_hidden_for_security_reasons",
            },
            "sql_query_template": "y",
        }
        deobfuscated = deofuscate_protected_fields(
            new_config, self.config, INTEGRATION_CLASSES[self.integration_id]
        )
        self.assertNotEqual(deobfuscated, new_config, "Should return a copy")
        self.assertDictEqual(
            deobfuscated,
            {
                "database_connection": {
                    "host": "y",
                    "port": 54320,
                    "dbname": "y",
                    "user": "y",
                    "password": "very_secret_password",
                },
                "sql_query_template": "y",
            },
        )
