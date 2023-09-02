"""Get number of micro-inverters that are online"""
import os
from util.fetch_enphase import EnphaseClient


def online_micro_count():
    enphase = EnphaseClient(
        os.getenv("ENPHASE_CLIENT_ID"),
        os.getenv("ENPHASE_CLIENT_SECRET"),
        os.getenv("ENPHASE_API_KEY"),
    )
    enphase.load_enphase_creds(
        os.getenv("ENPHASE_EMAIL"), os.getenv("ENPHASE_PASSWORD")
    )

    system_id = os.getenv("ENPHASE_SYSTEM_ID")

    micros = enphase.v4_request(f"systems/{system_id}/devices", {})["devices"]["micros"]
    return len(list(filter(lambda v: v["status"] == "normal", micros)))


print(online_micro_count())
