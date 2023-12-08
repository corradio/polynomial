import base64
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import vl_convert as vlc
from django.templatetags.static import static

from config.settings import DEBUG

from ..models import Measurement, Metric
from ..queries import query_measurements_without_gaps, query_topk_dates

TOP3_MEDAL_IMAGE_PATH = [
    static("images/medal_1st.png"),  # 🥇
    static("images/medal_2nd.png"),  # 🥈
    static("images/medal_3rd.png"),  # 🥉
]


def date_to_js_timestamp(d: date):
    return int(datetime.fromisoformat(d.isoformat()).timestamp() * 1000)


def filter_nan(value: float) -> Optional[float]:
    # Remove NaN
    return None if value != value else value


def get_vl_spec(
    measurements: List[Measurement],
    highlight_date: Optional[date] = None,
    width="container",
    height="container",
    labels: Optional[Dict[date, str]] = None,
    imageLabelUrls: Optional[Dict[date, str]] = None,
):
    if not measurements:
        return {}
    start_date = measurements[0].date
    end_date = measurements[-1].date
    value_extent = max((filter_nan(m.value) or 0 for m in measurements)) - min(
        (filter_nan(m.value) or 0 for m in measurements)
    )
    vl_spec = {
        "$schema": "https:#vega.github.io/schema/vega-lite/v5.json",
        "width": width,
        "height": height,
        "view": {"stroke": "transparent"},  # Remove background rectangle
        # This ensures the padding is not added on top of axis padding
        "autosize": {"type": "none"},
        "padding": {"right": 30, "left": 30, "top": 15, "bottom": 30},
        "data": {
            "values": [
                {
                    # NaN should be returned None in order to be JSON compliant
                    "value": filter_nan(m.value),
                    # due to the way javascript parses dates, we must take some care here
                    # see https://stackoverflow.com/questions/64319836/date-parsing-and-when-to-use-utc-timeunits-in-vega-lite
                    "date": f"{m.date.isoformat()}T00:00:00",
                    "label": labels.get(m.date, "") if labels else "",
                    "imageLabelUrl": imageLabelUrls.get(m.date, "")
                    if imageLabelUrls
                    else "",
                }
                for m in measurements
            ]
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
        ],
        "encoding": {
            "x": {
                "field": "date",
                "type": "temporal",
                "axis": {
                    "title": None,
                    "labelAngle": 0,
                    # https://github.com/d3/d3-time-format#locale_format
                    "labelExpr": '[timeFormat(datum.value, "%b"), timeFormat(datum.value, "%m") == "01" ? timeFormat(datum.value, "%Y") : ""]',
                    "labelColor": "gray",
                    "domainColor": "black",
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
                "field": "value",
                "type": "quantitative",
                "axis": {
                    "title": False,
                    "grid": True,
                    "domain": False,
                    "ticks": False,
                    "offset": 4,
                    "format": ".2s",  # will show SI units (k, M, G...)
                    "orient": "right",
                    "labelColor": "gray",
                },
            },
        },
        "layer": [
            # Line
            {"name": "line", "mark": {"type": "line"}},
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
        x_axis[
            "labelExpr"
        ] = '[timeFormat(datum.value, "%e"), timeFormat(datum.value, "%d") == "01" ? timeFormat(datum.value, "%b") : ""]'

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
                "mark": {"type": "line", "color": "red", "opacity": 0.5},
                "encoding": {"y": {"field": "rolling_mean", "title": "Value"}},
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
    elif day_span > 200:
        # Year graph
        pass
    else:
        # < Quarter/month graph
        if highlight_date:
            vl_spec["layer"].append(
                {
                    "name": "points",
                    "mark": {"type": "circle", "tooltip": True},
                    "encoding": {
                        "size": {
                            "condition": {
                                "test": {
                                    "field": "date",
                                    "oneOf": [date_to_js_timestamp(highlight_date)],
                                },
                                "value": 200,
                            },
                            "value": 20,  # default value
                        }
                    },
                }
            )
        else:
            # Highlight points based on mouseover
            vl_spec["layer"].append(
                {
                    "name": "points",
                    "mark": {"type": "circle", "tooltip": True},
                    "encoding": {
                        "size": {
                            "condition": {
                                "param": "highlight",
                                "empty": False,
                                "value": 200,
                            },
                            "value": 20,  # default value
                        }
                    },
                }
            )
    # Only add points if we're dealing with less than X points
    return vl_spec


def metric_chart_vl_spec(
    metric_id: int, highlight_date: Optional[date] = None, lookback_days: int = 30
):
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    measurements = query_measurements_without_gaps(
        start_date=start_date, end_date=end_date, metric_id=metric_id
    )
    metric = Metric.objects.get(metric_id)
    imageLabelUrls = None
    if metric.enable_medals:
        topk_dates = query_topk_dates(metric_id)
        root_path = "http://127.0.0.1:8000" if DEBUG else "https://polynomial.so"
        imageLabelUrls = dict(
            zip(
                topk_dates,
                [f"{root_path}{path}" for path in TOP3_MEDAL_IMAGE_PATH],
            )
        )

    return json.dumps(
        get_vl_spec(
            measurements,
            highlight_date=highlight_date,
            width=640,
            height=280,
            imageLabelUrls=imageLabelUrls,
        )
    )


def generate_png(vl_spec: str) -> bytes:
    return vlc.vegalite_to_png(vl_spec=vl_spec, scale=2)


def to_b64_img_src(png_data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_data).decode()
