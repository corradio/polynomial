from datetime import date
from typing import List

import psycopg2

from ..models import Integration, MeasurementTuple


class Postgresql(Integration):
    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
        "type": "dict",
        "keys": {
            "database_connection": {
                "type": "dict",
                "keys": {
                    "host": {"type": "string", "required": True},
                    "port": {"type": "int", "required": True, "default": 5432},
                    "dbname": {"type": "string", "required": True},
                    "user": {"type": "string", "required": True},
                    "password": {
                        "type": "string",
                        "required": True,
                        "format": "password",
                    },
                },
            },
            "sql_template": {
                "type": "string",
                "widget": "textarea",
                "required": True,
                "helpText": "Use %(date)s to insert requested date",
            },
        },
    }

    def __init__(self, config, secrets):
        super().__init__(config, secrets)
        self.conn = psycopg2.connect(**config["database_connection"])
        self.conn.set_session(readonly=True)
        self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def __del__(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    def collect_past(self, date: date) -> MeasurementTuple:
        return self.collect_past_multi([date])[0]

    def collect_past_multi(self, dates: List[date]) -> List[MeasurementTuple]:
        sql_template = self.config["sql_template"]
        self.cur.execute(sql_template, vars={"date": date})
        return [
            MeasurementTuple(date=row["date"], value=row["value"]) for row in self.cur
        ]
