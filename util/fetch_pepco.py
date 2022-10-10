"""Fetch Usage data from pepco/opower"""
import os
import time
import json
import logging
import base64
import re
import requests
from util import btoa


class PepcoOpowerClient:
    def __init__(self):
        self.pepco_session = None
        self.creds = {}

    def pepco_auth(self, signin_name, password):
        """Get a token that can be used to fetch usage data"""
        # https://learn.microsoft.com/en-us/azure/active-directory-b2c/identity-provider-azure-ad-b2c?pivots=b2c-user-flow

        logging.warning("Authenticating to Pepco")
        self.pepco_session = requests.Session()
        login_form = self.pepco_session.get(
            "https://secure.pepco.com/Pages/Login.aspx?/login="
        )

        # a tid is used in the request URI, not sure where to get, this is my best guess
        tid = login_form.headers["x-request-id"]
        enc = btoa(json.dumps({"TID": tid}))

        settings_line = [v for v in login_form.text.split("\n") if "var SETTINGS" in v][
            0
        ]
        settings_json = re.match("var SETTINGS = (.*);\\r", settings_line).group(
            1
        )  # Settings also has tid
        csrf = json.loads(settings_json)["csrf"]

        ms_base = (
            "https://secure.exeloncorp.com/euazurephi.onmicrosoft.com/B2C_1A_SignIn"
        )

        # The actual login
        self.pepco_session.post(
            (f"{ms_base}/SelfAsserted" f"?tx=StateProperties={enc}&p=B2C_1A_SignIn"),
            data={
                "request_type": "RESPONSE",
                "signinName": signin_name,
                "password": password,
            },
            headers={"X-CSRF-TOKEN": csrf},
        )

        # Trigger a 5 page redirect flow to collect cookies and get to the dashboard
        self.pepco_session.get(
            f"{ms_base}/api/CombinedSigninAndSignup/confirmed"
            f"?rememberMe=true"
            f"&csrf_token={csrf}"
            f"&tx=StateProperties={enc}"
            f"&p=B2C_1A_SignIn"
        )

        logging.warning("Retrieving Opower token")
        opower_jwt_req = self.pepco_session.post(
            "https://secure.pepco.com/api/Services/OpowerService.svc/GetOpowerToken"
        )
        opower_token = json.loads(opower_jwt_req.text)
        opower_token["expires_at"] = json.loads(
            base64.b64decode(opower_token["access_token"].split(".")[1])
        )["exp"]

        # email of current user is available at
        # "https://secure.pepco.com/api/Services/MyAccountService.svc/GetWebUserName"

        # JWT is available at...
        # "https://secure.pepco.com/api/services/myaccountservice.svc/getsession"
        return opower_token

    def load_opower_creds(self, signin_name, password):

        if os.path.exists("opower_token.json"):
            with open("opower_token.json", "r", encoding="utf-8") as enphase_token:
                token_data = json.load(enphase_token)

                current_time = int(time.time())
                if current_time < token_data["expires_at"]:
                    self.creds = token_data
                    return None

        self.creds = self.pepco_auth(signin_name, password)

        with open("opower_token.json", "w", encoding="utf-8") as token_file:
            token_file.write(json.dumps(self.creds))

        return None

    def opower_request(self, day):
        """Request a day of reads"""
        access_token = self.creds["access_token"]
        customer_info_resp = requests.get(
            "https://pepd.opower.com/ei/edge/apis/multi-account-v1/cws/pepd/customers/current",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        customer_info = json.loads(customer_info_resp.text)
        utility_account = customer_info["utilityAccounts"][0]["uuid"]

        utility_reads_resp = requests.get(
            (
                "https://pepd.opower.com/ei/edge/apis/DataBrowser-v1/"
                f"cws/utilities/pepd/utilityAccounts/{utility_account}/reads"
                f"?startDate={day}"  # yyyy-mm-dd
                f"&endDate={day}"  # yyyy-mm-dd
                "&aggregateType=hour"
                "&includeEnhancedBilling=false"
                "&includeMultiRegisterData=false"
            ),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        utility_reads = json.loads(utility_reads_resp.text)

        return utility_reads
