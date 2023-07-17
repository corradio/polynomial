from datetime import date, timedelta
from typing import List

import pandas as pd

from mainapp.models import Measurement

from ..queries import query_measurements_without_gaps

LOOKBACK_DAYS = 30
MIN_POINTS_PERCENTAGE = 0.5
STD_MULTIPLIER = 5  # Noise level tolerance


def extract_spikes(metric_series: dict) -> List[date]:
    """
    Returns dates of spikes
    """
    df = pd.DataFrame(
        [{"date": dt, "value": value} for dt, value in metric_series]
    ).set_index("date")
    df.index = pd.to_datetime(df.index)
    if len(df.dropna()) / len(df) < MIN_POINTS_PERCENTAGE:
        return []

    df["trend"] = df["value"].rolling(5).mean()
    std = df["trend"].std()
    # detect points
    is_outside_noise_level = (df["trend"] - df["value"]).abs() > std * STD_MULTIPLIER
    is_not_na = ~df["value"].isna()
    df["is_spike"] = is_not_na & is_outside_noise_level
    return [d.date() for d in df.index[df["is_spike"]].to_pydatetime()]


def detected_spike(metric_id: int) -> bool:
    # Query
    end_date = date.today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    metric_series = query_measurements_without_gaps(start_date, end_date, metric_id)
    # Get all outliers
    spike_dates = extract_spikes(metric_series)
    if spike_dates:
        # Verify this is indeed the last point
        last_non_nan_measurement = (
            Measurement.objects.exclude(value=float("nan"))
            .filter(metric=metric_id)
            .order_by("date")
            .last()
        )
        if (
            last_non_nan_measurement
            and last_non_nan_measurement.date == spike_dates[-1]
        ):
            return True
    return False
