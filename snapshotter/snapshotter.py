import re
import json
import random
import pathlib

import slack_sdk.web.async_client


async def paginate(action: callable, *args, **kwargs) -> dict:
    """
    Executes `action` until it does not contain "next_cursor" in the response.

    Parameters
    ----------
    action : callable
        Coroutine function; must be a slack_sdk API method itself

    *args, **kwargs
        Parameters for the API method provided in `action`
    """

    kwargs.pop("next_cursor", None)     # clear now internal variable

    data, coroutine = list(), action(*args, **kwargs)

    response = (await coroutine).data

    cursor = response.get(
        "response_metadata", dict()
    ).get("next_cursor", None)

    while cursor:

        data.append(response)

        coroutine = action(*args, **kwargs, next_cursor=cursor)

        response = (await coroutine).data

        cursor = response.get(
            "response_metadata", dict()
        ).get("next_cursor", None)

    data.append(response)

    return data


def sanitize(object: dict, regex: re.Pattern = (
    re.compile(r"(?<!(?P<bound><)\W)\b(?P<word>\w+)\b(?(bound)(?!>)|)")
), placeholder: str = "<obscured>") -> dict:
    """
    Removes obsolete properties and obscures the rest.

    Latter includes names, statuses, messages text etc.
    """

    result = dict()

    for key, value in object.items():

        if isinstance(value, dict):
            value = sanitize(value)

        if key in (
            "enterprise_name", "email", "name", "name_normalized",
            "real_name", "real_name_normalized", "display_name",
            "display_name_normalized", "title", "phone", "skype",
            "first_name", "last_name"
        ):
            value = placeholder if value else None

        if key.startswith(("image", "status")) or key == "blocks":
            continue    # message blocks are too complex to sanitize, drop them

        if key in ("topic", "purpose"):
            if isinstance(value, dict):
                value.update(value=placeholder)
            else:
                value = placeholder
        if key == "previous_names":
            value = [placeholder] * len(value)

        if key == "text":
            value = re.sub(regex, lambda match: (
                "X" * len(match["word"])), value)

        if key in ("files", "attachments"):
            key, value = f"{key}_count", len(value)

        result[key] = value

    return result


async def entrypoint(datapath: pathlib.Path):

    members, channels, messages = dict(), dict(), dict()

    # read tokens from the storage
    with open(datapath/"tokens.json") as authfile:
        # disable python 3.9 false-positive: pylint: disable=superfluous-parens
        tokens = json.load(authfile)

        if not tokens:
            raise SystemExit("no such authorization tokens")

    client = slack_sdk.web.async_client.AsyncWebClient()

    # fetch workspace members list (any member can do it)

    for response in await paginate(
        client.users_list, token=random.choice(list(tokens.values()))
    ):
        for member in response["members"]:
            if member["team_id"] not in members:
                members[member["team_id"]] = dict()

            members[member["team_id"]][member["id"]] = sanitize(member)

    # fetch channels list (all members must do it)

    for token in tokens.values():

        # get token owner's team ID (matters in shared teams case)
        teamID = (await client.auth_test(token=token)).data["team_id"]

        if teamID not in channels:
            channels[teamID] = dict()

        if teamID not in messages:
            messages[teamID] = dict()

        for response in await paginate(client.users_conversations, types=(
            "public_channel,private_channel,im,mpim"
        ), token=token):

            for channel in response["channels"]:

                if channel["id"] not in channels[teamID]:
                    channels[teamID][channel["id"]] = sanitize(channel)

                if channel["id"] not in messages[teamID]:
                    messages[teamID][channel["id"]] = list()

                # fetch channel history

                for response in await paginate(
                    client.conversations_history,
                    channel=channel["id"], token=token
                ):

                    messages[teamID][channel["id"]].extend([
                        sanitize(message) for message in response["messages"]
                    ])

    # save received data

    for teamID, members in members.items():
        (datapath/teamID).mkdir(exist_ok=True)

        with open(datapath/teamID/"members.json", "wt") as datafile:
            json.dump(members, datafile, indent=4)

        for channel in channels.get(teamID, dict()).values():
            (datapath/teamID/channel["id"]).mkdir(exist_ok=True)

            with open(
                datapath/teamID/channel["id"]/"metadata.json", "wt"
            ) as datafile:
                json.dump(channel, datafile, indent=4)

            with open(
                datapath/teamID/channel["id"]/"messages.json", "wt"
            ) as datafile:
                json.dump(messages[teamID][channel["id"]], datafile, indent=4)


    print(f"""

    Please delete tokens.json from the working directory and send the rest.

    Data collection completed, temporary Slack application can be removed.

    """)
