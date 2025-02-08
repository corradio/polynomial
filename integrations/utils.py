import copy
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Protocol, TypeVar, cast

import pandas as pd
from environs import Env

from .base import MeasurementTuple

env = Env()
env.read_env()  # read .env file, if it exists


def get_secret(key):
    return env.str(key, default=None)


def replace_null_with_nan(f: Optional[float]) -> float:
    if f is None:
        return float("nan")
    return f


# Time

T = TypeVar("T", covariant=True)


class RangeCallable(Protocol[T]):
    def __call__(self, date_start: date, date_end: date) -> Iterable[T]: ...


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
    assert date_start <= date_end
    df = pd.DataFrame(measurements, columns=["date", "value"])
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


def get_protected_fields_paths(
    schema: Dict[str, Any], path_prefix: Optional[List[str]] = None
) -> List[List[str]]:
    if not path_prefix:
        path_prefix = []
    paths: List[List[str]] = []
    for schema_k, schema_v in schema.items():
        if isinstance(schema_v, dict):
            if schema_k == "keys":
                # Go deeper but keep path_prefix intact as the JSON won't have the `keys` entry
                paths += get_protected_fields_paths(schema_v, path_prefix)
            elif schema_v.get("format") == "password":
                # Found one
                paths += [path_prefix + [schema_k]]
            else:
                # Go deeper
                paths += get_protected_fields_paths(schema_v, path_prefix + [schema_k])
    return paths


def obfuscate_protected_fields(
    config: Dict[str, Any], schema: Dict[str, Any]
) -> Dict[str, Any]:
    paths = get_protected_fields_paths(schema)
    config_copy = copy.deepcopy(config)
    for path in paths:
        obj = config_copy
        for p in path[:-1]:
            obj = obj[p]
        obj[path[-1]] = "value_has_been_hidden_for_security_reasons"
    return config_copy


def deofuscate_protected_fields(
    config: Dict[str, Any], unprotected_config: Dict[str, Any], schema: Dict[str, Any]
) -> Dict[str, Any]:
    # Replaces values of `config` with `unprotected_config` for the protected paths
    # if the value is still the obfuscated value
    paths = get_protected_fields_paths(schema)
    config_copy = copy.deepcopy(config)
    for path in paths:
        obj_w = config_copy
        obj_r = unprotected_config
        for p in path[:-1]:
            obj_w = obj_w[p]
            obj_r = obj_r[p]
        k = path[-1]
        if obj_w[k] == "value_has_been_hidden_for_security_reasons":
            # Value has not changed, we can restore field
            obj_w[k] = obj_r[k]
    return config_copy
