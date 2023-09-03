import logging
from datetime import date, timedelta
from typing import List, Optional

import pandas as pd

from mainapp.models import Measurement

from ..queries import query_measurements_without_gaps

LOOKBACK_DAYS = 40
MIN_POINTS_PERCENTAGE = 0.5
STD_MULTIPLIER = 7  # Noise level tolerance
TREND_ROLLING_DAYS = 5

logger = logging.getLogger(__name__)


def extract_spikes(measurements: List[Measurement]) -> List[date]:
    """
    Returns dates of spikes
    """
    df = pd.DataFrame(
        [{"date": m.date, "value": m.value} for m in measurements]
    ).set_index("date")
    df.index = pd.to_datetime(df.index)
    assert isinstance(df.index, pd.DatetimeIndex)
    logger.debug(f"Using n={len(df)} points")
    if len(df.dropna()) / len(df) < MIN_POINTS_PERCENTAGE:
        return []

    df["trend"] = df["value"].rolling(7).mean()
    std = df["trend"].std()
    # detect points
    is_outside_noise_level = (df["trend"] - df["value"]).abs() > std * STD_MULTIPLIER
    is_not_na = ~df["value"].isna()
    df["is_spike"] = is_not_na & is_outside_noise_level
    spike_index: pd.DatetimeIndex = df.index[df["is_spike"]]
    return list(spike_index.date)


def detected_spike(metric_id: int) -> Optional[date]:
    logger.info(f"Starting spike detection for metric_id={metric_id}")
    # Query
    end_date = date.today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    measurements = query_measurements_without_gaps(start_date, end_date, metric_id)
    # Get all outliers
    spike_dates = extract_spikes(measurements)
    if spike_dates:
        logger.info(f"Detected spikes at {spike_dates} for metric_id={metric_id}")
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
            return spike_dates[-1]
    logger.info(f"No spikes detected for metric_id={metric_id}")
    return None
