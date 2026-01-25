"""Health check: send signed test event to Railway bot, assert HTTP 200."""

import hashlib
import hmac
import json
import os
import time
import urllib.request

ENDPOINT = "https://agikids-bot-production.up.railway.app/slack/events"
BOT_USER_ID = "U0AAJUXE07M"
CHANNEL_ID = "C0AA2F5EQ5S"


def check_bot_health() -> None:
    signing_secret = os.environ["SLACK_SIGNING_SECRET"]
    timestamp = str(int(time.time()))
    event_ts = f"{timestamp}.000100"

    payload = json.dumps(
        {
            "token": "healthcheck",
            "team_id": "T0A9YSTH6Q2",
            "api_app_id": "A0ABKKER5H6",
            "type": "event_callback",
            "event_id": f"Ev_hc_{int(time.time())}",
            "event_time": int(timestamp),
            "event": {
                "type": "app_mention",
                "text": f"<@{BOT_USER_ID}> health check ping",
                "user": "U0A9HDRSLTZ",
                "channel": CHANNEL_ID,
                "ts": event_ts,
                "event_ts": event_ts,
                "channel_type": "channel",
            },
        }
    )

    sig_basestring = f"v0:{timestamp}:{payload}"
    signature = "v0=" + hmac.new(
        signing_secret.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()

    req = urllib.request.Request(
        ENDPOINT,
        data=payload.encode(),
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    assert resp.status == 200, f"Bot returned HTTP {resp.status}"
    print(f"Health check passed: HTTP {resp.status}")


if __name__ == "__main__":
    check_bot_health()
