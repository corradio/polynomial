from datetime import date, timedelta
from typing import List, final

import psycopg2
from psycopg2.extras import RealDictCursor

from ..models import Integration, MeasurementTuple


@final
class Postgresql(Integration):
    # Use https://bhch.github.io/react-json-form/playground
    config_schema = {
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
                "helpText": "Use %(date_start)s and %(date_end)s to insert requested start and end dates in SQL Query",
                "default": "SELECT NOW() as date, 1 as value",
            },
        },
    }

    def __enter__(self):
        self.conn = psycopg2.connect(**self.config["database_connection"])
        self.conn.set_session(readonly=True)
        self.cur = self.conn.cursor(cursor_factory=RealDictCursor)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "cur"):
            self.cur.close()
        if hasattr(self, "conn"):
            self.conn.close()

    def can_backfill(self):
        if not "sql_query_template" in self.config:
            return False
        sql_query_template = self.config["sql_query_template"]
        return (
            "%(date_start)s" in sql_query_template
            and "%(date_end)s" in sql_query_template
        )

    def collect_latest(self) -> MeasurementTuple:
        sql_query_template = self.config["sql_query_template"]
        if self.can_backfill():
            return self.collect_past(date.today() - timedelta(days=1))
        else:
            self.cur.execute(sql_query_template)
            return [
                MeasurementTuple(date=row["date"].date(), value=row["value"])
                for row in self.cur
            ][0]

    def collect_past(self, date: date) -> MeasurementTuple:
        return self.collect_past_range(date_start=date, date_end=date)[0]

    def collect_past_range(
        self, date_start: date, date_end: date
    ) -> List[MeasurementTuple]:
        assert self.can_backfill()
        sql_query_template = self.config["sql_query_template"]
        self.cur.execute(
            sql_query_template, vars={"date_start": date_start, "date_end": date_end}
        )
        return [
            MeasurementTuple(date=row["date"].date(), value=row["value"])
            for row in self.cur
        ]
