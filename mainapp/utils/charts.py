import base64
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID

import vl_convert as vlc
from django.templatetags.static import static

from config.settings import DEBUG

from ..models import Measurement, Metric
from ..queries import query_measurements_without_gaps, query_topk_dates

TOP3_MEDAL_IMAGE_PATH = [
    "images/medal_1st.png",  # 🥇
    "images/medal_2nd.png",  # 🥈
    "images/medal_3rd.png",  # 🥉
]

# https://d3js.org/d3-format#locale_format
# - `s` will show SI units (k, M, G...)
# - `~` removes insignificant trailing zeros
# - The integer represents number of significant digits
VALUE_FORMAT = ".3~s"


def date_to_js_timestamp(d: date):
    return int(datetime.fromisoformat(d.isoformat()).timestamp() * 1000)


def filter_nan(value: float) -> Optional[float]:
    # Remove NaN
    return None if value != value else value


def get_vl_spec(
    measurements: List[Measurement],
    # Some measurements of the other period might be missing due to leap years
    measurements_other_period: Optional[List[Optional[Measurement]]] = None,
    highlight_date: Optional[date] = None,
    width="container",
    height="container",
    labels: Optional[Dict[date, str]] = None,
    imageLabelUrls: Optional[Dict[date, str]] = None,
    markers: Optional[Dict[date, str]] = None,
    target: Optional[float] = None,
) -> dict:
    if not measurements:
        return {}
    if measurements_other_period:
        assert len(measurements) == len(
            measurements_other_period
        ), "Both measurements series should have same length"

    start_date = measurements[0].date
    end_date = measurements[-1].date
    max_value = max((filter_nan(m.value) or 0 for m in measurements))
    value_extent = max_value - min((filter_nan(m.value) or 0 for m in measurements))
    values = [
        {
            # NaN should be returned None in order to be JSON compliant
            "value": filter_nan(m.value),
            "date": date_to_js_timestamp(m.date),
            "label": labels.get(m.date, "") if labels else "",
            "imageLabelUrl": (imageLabelUrls.get(m.date, "") if imageLabelUrls else ""),
            "marker": markers.get(m.date, "") if markers else "",
        }
        for m in measurements
    ]
    for i, _ in enumerate(measurements):
        if measurements_other_period:
            m_prev = measurements_other_period[i]
            if m_prev:
                values[i]["value_prev"] = filter_nan(m_prev.value)
                values[i]["date_prev"] = date_to_js_timestamp(m_prev.date)

    vl_spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": width,
        "height": height,
        "view": {"stroke": "transparent"},  # Remove background rectangle
        # This ensures the padding is not added on top of axis padding
        "autosize": {"type": "none"},
        "padding": {"right": 30, "left": 30, "top": 15, "bottom": 30},
        "data": {
            "name": "data",
            "values": values,
        },
        "params": [
            {
                "name": "highlight",
                "select": {
                    "type": "point",
                    "nearest": True,
                    "on": "mouseover",
                    "encodings": ["x"],
                },
                "views": ["points"],
            }
        ],
        "transform": [
            {
                "calculate": f"datum.value + {0.1 * value_extent}",
                "as": "valueWithOffset",
            },
            {
                "calculate": "datum.marker ? datum.date : null",
                "as": "markerDate",
            },
        ],
        "encoding": {
            "x": {
                "type": "temporal",
                "axis": {
                    "title": None,
                    "labelAngle": 0,
                    # https://github.com/d3/d3-time-format#locale_format
                    "labelExpr": '[timeFormat(datum.value, "%b"), timeFormat(datum.value, "%m") == "01" ? timeFormat(datum.value, "%Y") : ""]',
                    "labelColor": "gray",
                    "tickCount": "month",
                    "tickSize": 3,
                    "gridDash": [2, 2],
                },
                "scale": {
                    "domain": [
                        date_to_js_timestamp(start_date),
                        date_to_js_timestamp(end_date),
                    ],
                },
            },
            "y": {
                "type": "quantitative",
                "axis": {
                    "title": False,
                    "grid": True,
                    "domain": False,
                    "ticks": False,
                    "offset": 4,
                    "format": VALUE_FORMAT,
                    "orient": "right",
                    "labelColor": "gray",
                },
            },
        },
        "layer": [
            # Line of last period
            {
                "name": "line_prev",
                "mark": {
                    "type": "line",
                    "stroke": "gray",
                    "strokeDash": [4, 2],
                    "opacity": 0.3,
                },
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "value_prev", "type": "quantitative"},
                },
            },
            # Line
            {
                "name": "line",
                "mark": {"type": "line"},
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "value", "type": "quantitative"},
                },
            },
            # Labels
            {
                "name": "labels",
                "mark": {
                    "type": "text",
                    "align": "center",
                    "baseline": "bottom",
                    "dy": -5,
                    "fontSize": 15,
                },
                "encoding": {"text": {"field": "label"}},
            },
            # Image labels
            {
                "name": "imageLabels",
                "mark": {
                    "type": "image",
                    "width": 24,
                    "height": 24,
                },
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "valueWithOffset", "type": "quantitative"},
                    "url": {"field": "imageLabelUrl", "type": "nominal"},
                },
            },
        ],
    }
    # The x-ticks above are made for months. Move to days if the span is days
    if len(measurements) < 60:
        x_axis = vl_spec["encoding"]["x"]["axis"]
        x_axis["tickCount"] = {"interval": "day", "step": 1}
        # https://d3js.org/d3-time-format#locale_format
        x_axis["labelExpr"] = (
            '[timeFormat(datum.value, "%e"), timeFormat(datum.value, "%d") == "01" ? timeFormat(datum.value, "%b") : ""]'
        )

    # Only add moving average if there's more than X days of data being non NaN
    if len([m for m in measurements if m.value == m.value]) > 30:
        vl_spec["transform"].append(
            {
                "window": [{"field": "value", "op": "mean", "as": "rolling_mean"}],
                "frame": [-15, 15],
            }
        )
        vl_spec["layer"].append(
            {
                "name": "moving_average",
                "mark": {"type": "line", "color": "#f03b20", "opacity": 0.7},
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "rolling_mean", "title": "Value"},
                },
            }
        )
    day_span = (end_date - start_date).days
    if day_span > 365:
        # Multi-year graph

        # Ticks per year
        vl_spec["encoding"]["x"]["axis"]["tickCount"] = "year"
        vl_spec["encoding"]["x"]["axis"]["labelExpr"] = "timeFormat(datum.value, '%Y')"
        # Style
        vl_spec["layer"][0]["mark"]["opacity"] = 0.5
        vl_spec["layer"][0]["mark"]["strokeWidth"] = 1.5

    # Add tooltips
    vl_spec["layer"].append(
        {
            "name": "points",
            "mark": {
                "type": "circle",
                "tooltip": {"content": "data"},  # Pass all data to tooltip plugin
                # The following doesn't work as it formats `value_prev` nulls as 0
                # "tooltip": {"expr": f"datum.datum && {{'Day': timeFormat(datum.datum.date, '%b %d, %Y'), 'Value': format(datum.datum.value, '{VALUE_FORMAT}'), 'Value {str_ago}': format(datum.datum.value_prev, '{VALUE_FORMAT}')}}"}
            },
            "encoding": {
                "x": {"field": "date", "type": "temporal"},
                "y": {"field": "value", "type": "quantitative"},
            },
        }
    )
    default_value = 20
    highlight_value = 200
    if day_span >= 365:
        default_value = int(default_value / 2)
        highlight_value = int(highlight_value / 2)
    if day_span > 365:
        default_value = 0
    if highlight_date:
        vl_spec["layer"][-1]["encoding"]["size"] = {
            "condition": {
                "test": {
                    "field": "date",
                    "oneOf": [date_to_js_timestamp(highlight_date)],
                },
                "value": highlight_value,
            },
            "value": default_value,  # default value
        }
    else:
        # Highlight points based on mouseover
        vl_spec["layer"][-1]["encoding"]["size"] = {
            "condition": {
                "param": "highlight",
                "empty": False,
                "value": highlight_value,
            },
            "value": default_value,  # default value
        }
        vl_spec["layer"].append(
            {
                "name": "points_prev",
                "mark": {"type": "circle", "opacity": 0.3},
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "value_prev", "type": "quantitative"},
                    "size": {
                        "condition": {
                            "param": "highlight",
                            "empty": False,
                            "value": 50,
                        },
                        "value": 0,  # default value
                    },
                },
            }
        )
        # Highlight markers based on mouseover
        for layer in vl_spec["layer"]:
            if layer["name"] == "commentLabels":
                layer["encoding"]["color"] = {
                    "condition": {
                        "param": "highlight",
                        "empty": False,
                        "value": "black",
                    },
                    "value": "gray",  # default value,
                }
                break

    if target is not None:
        vl_spec["layer"].append(
            {
                # "name": "target",
                "mark": {"type": "rule", "color": "blue", "strokeDash": [4, 4]},
                "data": {"values": [{}]},
                "encoding": {"y": {"datum": target, "type": "quantitative"}},
            }
        )

    if day_span < 365:
        # Show rulers
        vl_spec["layer"].append(
            {
                "name": "markers",
                "mark": "rule",
                "encoding": {
                    "x": {"field": "markerDate", "type": "temporal"},
                    "y": None,
                    "color": {"value": "gray"},
                },
            }
        )
        vl_spec["layer"].append(
            {
                "name": "commentLabels",
                "mark": {
                    "type": "text",
                    "align": "right",
                    "baseline": "top",
                    "dx": 0,
                    "dy": 2,
                    "fontSize": 11,
                    "angle": -90,
                    "color": "gray",
                },
                "encoding": {
                    "x": {"field": "markerDate"},
                    "y": {"value": 0},
                    "text": {"field": "marker"},
                },
            },
        )

    return vl_spec


def metric_chart_vl_spec(
    metric_id: UUID, highlight_date: Optional[date] = None, lookback_days: int = 30
):
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    measurements = query_measurements_without_gaps(
        start_date=start_date, end_date=end_date, metric_id=metric_id
    )
    metric = Metric.objects.get(pk=metric_id)
    markers = {marker.date: marker.text for marker in metric.marker_set.all()}
    imageLabelUrls = None
    if metric.enable_medals:
        topk_dates = query_topk_dates(metric_id)
        root_path = "http://127.0.0.1:8000" if DEBUG else "https://polynomial.so"
        imageLabelUrls = dict(
            zip(
                topk_dates,
                [f"{root_path}{static(path)}" for path in TOP3_MEDAL_IMAGE_PATH],
            )
        )

    return json.dumps(
        get_vl_spec(
            measurements,
            highlight_date=highlight_date,
            width=640,
            height=280,
            imageLabelUrls=imageLabelUrls,
            markers=markers,
            target=metric.target,
        )
    )


def generate_png(vl_spec: str) -> bytes:
    return vlc.vegalite_to_png(vl_spec=vl_spec, scale=2)


def to_b64_img_src(png_data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_data).decode()
