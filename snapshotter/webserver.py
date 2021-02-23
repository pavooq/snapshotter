import os
import json
import time
import uuid
import signal
import asyncio
import pathlib
import functools

import yarl
import aiohttp.web
import aiohttp.web_runner

from pyngrok import ngrok

import slack_sdk.web.async_client


# pylint: disable=multiple-statements


def entrypoint(host: str, port: int, datapath: pathlib.Path):
    """
    runs web server for user API tokens collection
    """

    application = aiohttp.web.Application()

    application["ID"] = os.environ.get("SLACK_CLIENT_ID")

    application["secret"] = os.environ.get("SLACK_CLIENT_SECRET")

    if application["ID"] is None:
        raise SystemExit("SLACK_CLIENT_ID unset or empty")
    if application["secret"] is None:
        raise SystemExit("SLACK_CLIENT_SECRET unset or empty")

    application["datapath"] = datapath.expanduser().absolute()

    application.add_routes(routes)

    application.cleanup_ctx.append(storage)

    application.cleanup_ctx.append(
        functools.partial(tunnel, address=f"{host}:{port}"))

    return aiohttp.web.run_app(application, host=host, port=port, print=False)


async def tunnel(app: aiohttp.web.Application, *, address: str):
    """
    opens a tunnel for ngrok to get publicly accessible domain for the OAuth
    """
    app["tunnel"] = ngrok.connect(address, "http")

    URL = app["tunnel"].public_url

    print(f"""

    Base URL: {URL} <- add it as a Redirect URL at the app management page

    OAuth URL: {URL}/install <- give it to your workspace' members

    """)

    yield

    try:
        ngrok.disconnect(app["tunnel"].public_url)
    except Exception:   # pylint: disable=broad-except
        return  # "Connection Refused" is often a cause


async def storage(app: aiohttp.web.Application):
    """
    implements simple in-memory storage for the application globals
    """
    app.update(tokens=dict(), states=dict(), total=0)

    asyncio.create_task(counter(app), name="counter")

    yield   # startup and cleanup hooks delimiter

    with open(app["datapath"]/"tokens.json", "wt") as authfile:
        json.dump(app["tokens"], authfile, indent=4)


async def counter(app: aiohttp.web.Application):
    """
    prints tokens collection progress
    """
    print("waiting for authorizations... ", end="", flush=True)

    while not app["total"]:
        await asyncio.sleep(0.5)

    while len(app["tokens"]) != app["total"]:

        print("\raccess granted by {current}/{total} members ".format(
            current=len(app["tokens"]), total=app["total"]
        ), end="", flush=True)

        await asyncio.sleep(0.5)

    print("""\rall tokens received, first stage completed

    now you can run "snapshotter collect" in this directory to
    begin workspace data collection with acquired tokens

    """, flush=True)

    os.kill(os.getpid(), signal.SIGINT)


routes = aiohttp.web.RouteTableDef()


@routes.get("/install", allow_head=False)
async def install(request):
    """
    OAuth handshake entrypoint
    """
    base = yarl.URL("https://slack.com/oauth/v2/authorize")

    # generate random state to prevent forgery-type attacks
    # request.app["states"][(state := str(uuid.uuid4()))] = time.time()
    state = str(uuid.uuid4()); request.app["states"][state] = time.time()

    scopes = ",".join([
        "users:read", "im:history", "im:read", "mpim:history", "mpim:read",
        "channels:history", "channels:read", "groups:history", "groups:read"
    ])

    return aiohttp.web.HTTPPermanentRedirect(base % {
        "state": state, "client_id": request.app["ID"], "user_scope": scopes,
        "redirect_uri": request.app["tunnel"].public_url
    }, headers={"Cache-Control": "no-store"})


@routes.get("/", allow_head=False)
async def callback(request):
    """
    Second step of the OAuth handshake
    """
    if "error" in request.query:
        raise aiohttp.web.HTTPForbidden(text=json.dumps({
            "reason": f"forbidden by Slack API ({request.query['error']})"
        }, indent=4), content_type="application/json")

    # verify request state to prevent forgery-type attacks
    state = request.query.get("state")

    if not state:
        raise aiohttp.web.HTTPBadRequest(text=json.dumps({
            "reason": "request state parameter is not provided"
        }, indent=4), content_type="application/json")

    timestamp = request.app["states"].pop(state, None)

    if not timestamp:
        raise aiohttp.web.HTTPForbidden(text=json.dumps({
            "reason": "request state parameter is not valid"
        }, indent=4), content_type="application/json")

    if time.time() - timestamp > 600:
        raise aiohttp.web.HTTPForbidden(text=json.dumps({
            "reason": "request state parameter is expired"
        }, indent=4), content_type="application/json")

    client = slack_sdk.web.async_client.AsyncWebClient()

    # exchange authorization code for a token

    auth = (await client.oauth_v2_access(code=request.query["code"], **{
        "client_id": request.app["ID"], "client_secret": request.app["secret"],
        "redirect_uri": request.app["tunnel"].public_url
    })).data["authed_user"]     # always exists if user scopes was granted

    if not request.app["total"]:
        members = (await client.users_list(
            token=auth["access_token"])).data["members"]

        for member in members:
            if not any([    # skip members that can not grant access a priori
                member["id"] == "USLACKBOT", member.get("is_bot"),
                member.get("is_app_user"), member.get("is_invited_user"),
                member.get("is_restricted"), member.get("is_ultra_restricted")
            ]):
                request.app["total"] += 1

    request.app["tokens"][auth["id"]] = auth["access_token"]

    return aiohttp.web.HTTPOk(
        text="<h2>token acquired, thank you</h2>", content_type="text/html",
        headers={"Cache-Control": "no-store"}
    )
