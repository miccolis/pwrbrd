"""Fetch generation data from enphase"""
import logging
import time
import json
import base64
import os
import re
import requests
from requests.auth import HTTPBasicAuth


class EnphaseClient:
    """Handles Auth for the enphase API"""

    def __init__(self, client_id, client_secret, api_key):
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_key = api_key

        self.creds = {}

    def enphase_authenticate(self, user_email, user_password):
        """Walk the OAuth authenication flow"""
        enphase_redirect_uri = "https://api.enphaseenergy.com/oauth/redirect_uri"

        sesh = requests.Session()
        login_form = sesh.get(
            (
                f"https://api.enphaseenergy.com/oauth/authorize?"
                f"response_type=code&client_id={self.client_id}"
                f"&redirect_uri={enphase_redirect_uri}"
            ),
            timeout=15,
        )

        login_hidden = self.extract_hidden(login_form.text.split("\n"))

        logging.warning("Authenticating")
        login_resp = sesh.post(
            "https://api.enphaseenergy.com/oauth_login",
            data={
                "email": user_email,
                "password": user_password,
                "_csrf": login_hidden["_csrf"],
            },
            timeout=15,
        )

        login_hidden = self.extract_hidden(login_resp.text.split("\n"))

        logging.warning("Authorizing")
        authorize_resp = sesh.post(
            "https://api.enphaseenergy.com/oauth/authorize",
            data={
                "_csrf": login_hidden["_csrf"],
                "user_oauth_approval": "true",
                "app_id": login_hidden["app_id"],
            },
            timeout=15,
        )

        code = re.match(".*code=(.+)", authorize_resp.url).group(1)

        logging.warning("Retrieving token")
        request_time = int(time.time())
        body = requests.post(
            "https://api.enphaseenergy.com/oauth/token",
            params={
                "grant_type": "authorization_code",
                "redirect_uri": enphase_redirect_uri,
                "code": code,
            },
            auth=HTTPBasicAuth(self.client_id, self.client_secret),
            timeout=15,
        )
        payload = json.loads(body.text)
        payload["expires_at"] = request_time + payload["expires_in"]
        return payload

    def refresh_enphase_token(self, refresh_token):
        logging.warning("Refeshing token")
        request_time = int(time.time())
        body = requests.post(
            (
                "https://api.enphaseenergy.com/oauth/token?"
                f"grant_type=refresh_token&refresh_token={refresh_token}"
            ),
            auth=HTTPBasicAuth(self.client_id, self.client_secret),
            timeout=15,
        )

        if body.status_code == 401:
            # TODO better handling of errors here
            return None

        payload = json.loads(body.text)
        payload["expires_at"] = request_time + payload["expires_in"]
        return payload

    def extract_hidden(self, lines):
        lines = [v.strip() for v in lines if str.__contains__(v, 'type="hidden"')]
        search = re.compile('.*name="([-_a-z0-9]+)".*value="([-_a-z0-9]*)"')
        extracted = {}
        for line in lines:
            match = search.match(line)
            if match is not None:
                extracted[match.group(1)] = match.group(2)
        return extracted

    def load_enphase_creds(self, user_email="", user_password=""):
        """Wraps actual authentication with local cache"""
        # TODO validate token is for requested user.
        if os.path.exists("token.json"):
            with open("token.json", "r", encoding="utf-8") as enphase_token:
                token_data = json.load(enphase_token)

            current_time = int(time.time())
            if current_time < token_data["expires_at"]:
                self.creds = token_data
                return None

            refresh_token_content = json.loads(
                base64.b64decode(token_data["refresh_token"].split(".")[1])
            )

            if current_time < refresh_token_content["exp"]:
                token_data = self.refresh_enphase_token(token_data["refresh_token"])
                with open("token.json", "w", encoding="utf-8") as token_file:
                    token_file.write(json.dumps(token_data))
                self.creds = token_data
                return None

        self.creds = self.enphase_authenticate(user_email, user_password)
        with open("token.json", "w", encoding="utf-8") as token_file:
            token_file.write(json.dumps(self.creds))
        return None

    def production_request(self, system_id, start_at):
        access_token = self.creds["access_token"]
        stats = requests.get(
            f"https://api.enphaseenergy.com/api/v4/systems/{system_id}/telemetry/production_micro",
            params={"key": self.api_key, "granularity": "day", "start_at": start_at},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )

        if stats.status_code == 422:
            return []

        return json.loads(stats.text)["intervals"]

    def v4_request(self, path, params):
        access_token = self.creds["access_token"]
        resp = requests.get(
            f"https://api.enphaseenergy.com/api/v4/{path}",
            params={"key": self.api_key, **params},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )

        if resp.status_code == 422:
            return []

        return json.loads(resp.text)


def basic_enphase_fetch():
    enphase = EnphaseClient(
        os.getenv("ENPHASE_CLIENT_ID"),
        os.getenv("ENPHASE_CLIENT_SECRET"),
        os.getenv("ENPHASE_API_KEY"),
    )
    enphase.load_enphase_creds(
        os.getenv("ENPHASE_EMAIL"),
        os.getenv("ENPHASE_PASSWORD"),
    )

    return enphase.v4_request("systems", {})
