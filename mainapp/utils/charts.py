import base64
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import vl_convert as vlc

from ..models import Measurement
from ..queries import query_measurements_without_gaps


def date_to_js_timestamp(d: date):
    return int(datetime.fromisoformat(d.isoformat()).timestamp() * 1000)


def get_vl_spec(
    measurements: List[Measurement],
    highlight_date: Optional[date] = None,
    width="container",
    height="container",
    labels: Optional[Dict[date, str]] = None,
):
    if not measurements:
        return {}
    start_date = measurements[0].date
    end_date = measurements[-1].date
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
                    "value": None if m.value != m.value else m.value,
                    # due to the way javascript parses dates, we must take some care here
                    # see https://stackoverflow.com/questions/64319836/date-parsing-and-when-to-use-utc-timeunits-in-vega-lite
                    "date": f"{m.date.isoformat()}T00:00:00",
                    "label": labels.get(m.date, "") if labels else "",
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
        "transform": [],
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


def metric_chart_vl_spec(metric_id: int, highlight_date: Optional[date] = None):
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    measurements = query_measurements_without_gaps(
        start_date=start_date, end_date=end_date, metric_id=metric_id
    )
    return json.dumps(
        get_vl_spec(measurements, highlight_date=highlight_date, width=640, height=280)
    )


def generate_png(vl_spec: str) -> bytes:
    return vlc.vegalite_to_png(vl_spec=vl_spec, scale=2)


def to_b64_img_src(png_data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_data).decode()
