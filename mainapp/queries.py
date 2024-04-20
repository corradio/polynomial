from datetime import date
from typing import Iterable, List, Optional, Tuple

from django.db import connection

from .models import Measurement, Metric


def query_measurements_without_gaps(
    start_date: date, end_date: date, metric_id: int
) -> List[Measurement]:
    """Will return Measurements with NaN value if missing"""
    assert start_date <= end_date, "start_date should be before end_date"
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


def query_measurements_for_dates(
    dates: List[date | None], metric_id: int
) -> List[Measurement | None]:
    """Will return Measurements with NaN value if missing. If date is missing, then will return None"""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT s.date, value
            FROM (
               SELECT UNNEST(%s) AS date, UNNEST(%s) AS index
            ) s
            LEFT JOIN (
                SELECT * FROM mainapp_measurement WHERE metric_id = %s
            ) m
            ON m.date = s.date
            ORDER BY index ASC;
        """,
            [dates, list(range(len(dates))), metric_id],
        )
        results: List[Tuple[date, Optional[float]]] = cursor.fetchall()
        return [
            (
                Measurement(
                    date=date, value=value if value is not None else float("nan")
                )
                if date
                else None
            )
            for date, value in results
        ]


def query_topk_dates(metric_id: int, topk=3) -> Iterable[date]:
    sort_field_arg = "value"
    metric = Metric.objects.get(pk=metric_id)
    if metric.higher_is_better:
        sort_field_arg = f"-{sort_field_arg}"  # Reverse sort order
    return (
        m.date
        for m in Measurement.objects.filter(metric_id=metric_id).order_by(
            sort_field_arg
        )[:3]
    )
