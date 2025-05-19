import logging
from datetime import date, timedelta
from typing import List, Optional
from uuid import UUID

import pandas as pd

from mainapp.models import Measurement
from mainapp.models.metric import Metric

from ..queries import query_measurements_without_gaps

LOOKBACK_DAYS = 40
MIN_POINTS_PERCENTAGE = 0.5
STD_MULTIPLIER = 7  # Noise level tolerance
TREND_ROLLING_DAYS = 5
MIN_CHANGE_PERCENTAGE = 10  # Min percentage of change (even if above noise level)

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

    df["trend"] = df["value"].rolling(TREND_ROLLING_DAYS).mean()
    std = df["trend"].std()
    # detect points
    is_outside_noise_level = (df["trend"] - df["value"]).abs() > std * STD_MULTIPLIER
    # being outside noise level is not sufficient - you also need to be x% above the signal
    is_large_deviation = (df["trend"] - df["value"]).abs() / df[
        "trend"
    ] * 100 > MIN_CHANGE_PERCENTAGE

    is_not_na = ~df["value"].isna()
    df["is_spike"] = is_not_na & is_outside_noise_level & is_large_deviation
    spike_index: pd.DatetimeIndex = df.index[df["is_spike"]]
    return list(spike_index.date)


def detected_spike(metric_id: UUID) -> Optional[date]:
    logger.info(f"Starting spike detection for metric_id={metric_id}")
    # Query
    end_date = date.today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    measurements = query_measurements_without_gaps(start_date, end_date, metric_id)
    # Get all outliers
    spike_dates = extract_spikes(measurements)
    # Filter out spikes that have already been detected
    metric = Metric.objects.get(pk=metric_id)
    spike_dates = [
        d for d in spike_dates if d > (metric.last_detected_spike or date.min)
    ]
    if spike_dates:
        spike_date = spike_dates[0]
        logger.info(f"Detected spike at {spike_date} for metric_id={metric_id}")
        # Verify this is indeed the last point
        last_non_nan_measurement = (
            Measurement.objects.exclude(value=float("nan"))
            .filter(metric=metric_id)
            .order_by("date")
            .last()
        )
        if not last_non_nan_measurement or last_non_nan_measurement.date != spike_date:
            return None
        # If a spike was just detected, abort if its value did not change
        if (
            metric.last_detected_spike
            and metric.last_detected_spike + timedelta(days=1)
            == last_non_nan_measurement.date
        ):
            last_spike = Measurement.objects.filter(
                metric=metric_id, date=metric.last_detected_spike
            ).first()
            if last_spike and last_spike.value == last_non_nan_measurement.value:
                logger.info(
                    f"Last spike is equal to the previous one for metric_id={metric_id}"
                )
                return None
        # Return
        return spike_date
    logger.info(f"No spikes detected for metric_id={metric_id}")
    return None
