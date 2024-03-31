from unittest import TestCase

from integrations.utils import (
    deofuscate_protected_fields,
    get_protected_fields_paths,
    obfuscate_protected_fields,
)


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
        self.schema = {
            "type": "dict",
            "keys": {
                "database_connection": {
                    "type": "dict",
                    "keys": {
                        "host": {"type": "string", "required": True},
                        "port": {"type": "number", "required": True, "default": 5432},
                        "dbname": {"type": "string", "required": True},
                        "user": {"type": "string", "required": True},
                        "password": {
                            "type": "string",
                            "required": True,
                            "format": "password",
                        },
                    },
                },
                "sql_query_template": {
                    "type": "string",
                    "widget": "textarea",
                    "required": True,
                    "helpText": "Use %(date_start)s and %(date_end)s to insert requested start and end dates in SQL Query. Note the dates are inclusive.",
                    "default": "SELECT NOW() as date, 1 as value",
                },
            },
        }

    def test_get_protected_fields_paths(self):
        paths = get_protected_fields_paths(self.schema)
        self.assertListEqual(paths, [["database_connection", "password"]])

    def test_obfuscation(self):
        protected_copy = obfuscate_protected_fields(self.config, self.schema)
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
        deobfuscated = deofuscate_protected_fields(new_config, self.config, self.schema)
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
