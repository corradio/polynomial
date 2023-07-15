import base64
import json
from datetime import date, datetime, timedelta

import vl_convert as vlc

from ..queries import query_measurements_without_gaps


def date_to_js_timestamp(d: date):
    return int(datetime.fromisoformat(d.isoformat()).timestamp() * 1000)


def get_vl_spec(
    start_date: date,
    end_date: date,
    measurements=[],
    width="container",
    height="container",
):
    return {
        "$schema": "https:#vega.github.io/schema/vega-lite/v5.json",
        "width": width,
        "height": height,
        "view": {"stroke": "transparent"},  # Remove background rectangle
        # This ensures the padding is not added on top of axis padding
        "autosize": {"type": "none"},
        "padding": {"right": 30, "left": 30, "top": 5, "bottom": 30},
        "data": {
            "values": [
                {"value": value, "date": date.isoformat()}
                for date, value in measurements
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
                "window": [{"field": "value", "op": "mean", "as": "rolling_mean"}],
                "frame": [-15, 15],
            }
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
            # Moving average
            {
                "name": "moving_average",
                "mark": {"type": "line", "color": "red", "opacity": 0.5},
                "encoding": {"y": {"field": "rolling_mean", "title": "Value"}},
            },
        ],
    }


def metric_chart_vl_spec(metric_id: int):
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    measurements = query_measurements_without_gaps(
        start_date=start_date, end_date=end_date, metric_id=metric_id
    )
    return json.dumps(
        get_vl_spec(start_date, end_date, measurements, width=640, height=280)
    )


def generate_png(vl_spec: str) -> bytes:
    return vlc.vegalite_to_png(vl_spec=vl_spec, scale=2)


def to_b64_img_src(png_data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_data).decode()
