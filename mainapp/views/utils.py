from typing import Optional

from django.utils.http import urlencode


def add_next(uri: str, next: Optional[str], encode=False):
    if next:
        if encode:
            return f"{uri}?{urlencode({'next': next})}"
        else:
            return f"{uri}?next={next}"
    return uri
