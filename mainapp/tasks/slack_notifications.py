import secrets
from typing import Tuple

from celery.utils.log import get_task_logger
from django.http import HttpRequest
from django.urls import reverse
from requests_oauthlib import OAuth2Session

from config.settings import DEBUG
from integrations.utils import get_secret

from ..models import Organization

logger = get_task_logger(__name__)

client_id = get_secret("SLACK_CLIENT_ID")
client_secret = get_secret("SLACK_CLIENT_SECRET")
authorization_url = "https://slack.com/oauth/v2/authorize"
token_url = "https://slack.com/api/oauth.v2.access"
scopes = ["files:write,chat:write,channels:read,channels:join"]


def authorize(request: HttpRequest) -> Tuple[str, str]:
    # Generate state to uniquely identify this request
    state = secrets.token_urlsafe(32)
    # Get uri
    client = OAuth2Session(
        client_id,
        scope=scopes,
        # Note: Slack doesn't allow for localhost redirects.
        # You can temporarily change the next line with ngrok for testing with HTTPS
        # redirect_uri=f'https://xxx.ngrok-free.app{reverse("authorize-callback")}'
        redirect_uri=request.build_absolute_uri(reverse("authorize-callback")),
    )
    uri, _ = client.authorization_url(
        authorization_url,
        state=state,
    )
    return uri, state


def process_authorize_callback(
    organization_id: int, uri: str, authorize_callback_uri: str, state: str
) -> str:
    # When testing Slack behind NGROK, we need to make sure Django things we're under http
    if DEBUG:
        authorize_callback_uri = authorize_callback_uri.replace("http://", "https://")
    client = OAuth2Session(client_id, redirect_uri=authorize_callback_uri)
    # Checks that the state is valid, will raise
    # MismatchingStateError if not.
    client.fetch_token(
        token_url,
        client_secret=client_secret,
        authorization_response=uri,
        state=state,
    )
    credentials = client.token
    org = Organization.objects.get(pk=organization_id)
    org.slack_notifications_credentials = credentials
    org.save()
    return reverse("organization_edit", args=[organization_id])


def query_public_channels(credentials: dict, cursor=None):
    # `token_type` is set to `bot` and this doesn't fare well with oauthlib
    credentials = {**credentials, "token_type": "bearer"}
    session = OAuth2Session(
        client_id,
        token=credentials,
    )
    url = "https://slack.com/api/conversations.list"
    if cursor:
        url += f"?cursor={cursor}"
    response = session.get(url)
    response.raise_for_status()
    obj = response.json()
    assert obj["ok"] == True, str(obj)
    next_cursor = obj["response_metadata"].get("next_cursor")
    if next_cursor:
        return obj["channels"] + query_public_channels(credentials, next_cursor)
    return obj["channels"]


def list_public_channels(credentials: dict):
    return sorted(f"#{obj['name']}" for obj in query_public_channels(credentials))


def notify_channel(credentials: dict, channel_name: str, img_data: bytes, message: str):
    """
    Sharing to private channels won't be possible here.
    It turns out that a bot token can't upload a file somewhere, and then make it public so it can be
    shared in any channel. This requires a user token, only possible in the paid plan.
    This is because uploading a file using `files.upload` outside of a channel makes it private,
    and making it public using `files.sharedPublicURL` requires a paid account and a user token.
    The solution could therefore be to give the bot the ability to upload to any public channel using
    the `chat:write.public` scope. However, turns out that bots can't upload to channels they are not
    part of. We therefore need to join the channel first.
    """

    channel_id = next(
        obj["id"]
        for obj in query_public_channels(credentials)
        if obj["name"] == channel_name.replace("#", "")
    )

    # `token_type` is set to `bot` and this doesn't fare well with oauthlib
    credentials = {**credentials, "token_type": "bearer"}
    # Note: token never expires
    session = OAuth2Session(
        client_id,
        token=credentials,
    )

    # Check if there's a need to join the public channel
    # (slack bots can't upload files to channel they don't belong to)
    response = session.post(
        "https://slack.com/api/conversations.join",
        data={
            "channel": channel_id,
        },
    )
    response.raise_for_status()
    obj = response.json()
    assert obj["ok"] == True, str(obj)

    # Upload image
    response = session.post(
        "https://slack.com/api/files.upload",
        data={
            "filetype": "png",
            "filename": "image.png",
            "channels": channel_name,
            "initial_comment": message,
        },
        files={"file": img_data},
    )
    response.raise_for_status()
    obj = response.json()
    assert obj["ok"] == True, str(obj)
