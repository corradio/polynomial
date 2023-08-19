from datetime import date
from typing import List, Optional, Tuple

from django.db import connection

from .models import Measurement


def query_measurements_without_gaps(
    start_date: date, end_date: date, metric_id: int
) -> List[Measurement]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT s.date, value
            FROM (
               SELECT generate_series(timestamp %s,
                                      timestamp %s,
                                      interval  '1 day')::date
               AS date
            ) s
            LEFT JOIN (
                SELECT * FROM mainapp_measurement WHERE metric_id = %s
            ) m
            ON m.date = s.date
            ORDER BY date;
        """,
            [start_date, end_date, metric_id],
        )
        results: List[Tuple[date, Optional[float]]] = cursor.fetchall()
        return [
            Measurement(date=date, value=value if value is not None else float("nan"))
            for date, value in results
        ]
