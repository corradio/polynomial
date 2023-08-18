from typing import Optional

import orjson
from django.core.serializers.json import DjangoJSONEncoder
from django.http.response import HttpResponse
from django.utils.http import urlencode


def add_next(uri: str, next: Optional[str], encode=False):
    if next:
        if encode:
            return f"{uri}?{urlencode({'next': next})}"
        else:
            return f"{uri}?next={next}"
    return uri


class OrjsonResponse(HttpResponse):
    """
    An HTTP response class that consumes data to be serialized to JSON.

    :param data: Data to be dumped into json. By default only ``dict`` objects
      are allowed to be passed due to a security flaw before ECMAScript 5. See
      the ``safe`` parameter for more information.
    :param encoder: Should be a json encoder class. Defaults to
      ``django.core.serializers.json.DjangoJSONEncoder``.
    :param safe: Controls if only ``dict`` objects may be serialized. Defaults
      to ``True``.
    :param json_dumps_params: A dictionary of kwargs passed to json.dumps().
    """

    def __init__(
        self,
        data,
        safe=True,
        json_dumps_params=None,
        **kwargs,
    ):
        if safe and not isinstance(data, dict):
            raise TypeError(
                "In order to allow non-dict objects to be serialized set the "
                "safe parameter to False."
            )
        if json_dumps_params is None:
            json_dumps_params = {}
        kwargs.setdefault("content_type", "application/json")
        data = orjson.dumps(
            data, default=DjangoJSONEncoder.default, **json_dumps_params
        )
        super().__init__(content=data, **kwargs)
