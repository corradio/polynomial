from datetime import date, timedelta
from typing import Callable, Iterable, List, Protocol, TypeVar, cast

import pandas as pd
from environs import Env

from .base import MeasurementTuple

env = Env()
env.read_env()  # read .env file, if it exists


def get_secret(key):
    return env.str(key, default=None)


# Time

T = TypeVar("T", covariant=True)


class RangeCallable(Protocol[T]):
    def __call__(self, date_start: date, date_end: date) -> Iterable[T]:
        ...


def batch_range_per_month(
    date_start: date,
    date_end: date,
    callable: RangeCallable[T],
) -> Iterable[T]:
    df = pd.DataFrame(index=pd.date_range(start=date_start, end=date_end, freq="D"))
    assert isinstance(df.index, pd.DatetimeIndex)
    df["year"] = df.index.year
    df["month"] = df.index.month
    df["day"] = df.index.day
    batches = df.groupby(["year", "month"]).agg(["first", "last"])["day"]
    return (
        measurement
        for index, row in batches.iterrows()
        for measurement in callable(
            date_start=date(index[0], index[1], row["first"]),
            date_end=date(index[0], index[1], row["last"]),
        )
    )


def batch_range_by_max_batch(
    date_start: date,
    date_end: date,
    max_days: int,
    callable: RangeCallable[T],
) -> Iterable[T]:
    days: List[date] = [
        d.to_pydatetime().date()
        for d in pd.date_range(start=date_start, end=date_end, freq="D")
    ]
    # Chunk interval up in smaller pieces with max length
    return (
        measurement
        for i in range(0, len(days), max_days)
        for measurement in callable(
            date_start=days[i],
            date_end=days[min(i + max_days - 1, len(days) - 1)],
        )
    )


def fill_mesurement_range(
    measurements: List[MeasurementTuple],
    date_start: date,
    date_end: date,
    fill_value: float = 0,
):
    df = pd.DataFrame(measurements)
    # Convert 'date' object column into DatetimeIndex
    series: pd.Series[float] = df.set_index(pd.DatetimeIndex(df.date)).value
    # Reindex to set missing dates
    range_index = pd.date_range(start=date_start, end=date_end, freq="D")
    series = series.reindex(range_index, fill_value=fill_value)
    assert isinstance(series.index, pd.DatetimeIndex)
    # Exclude points outside the range
    series = series[(series.index.date >= date_start) & (series.index.date <= date_end)]
    return [
        MeasurementTuple(
            date=cast(pd.Timestamp, dt).date(),
            value=value,
        )
        for dt, value in series.items()
    ]
