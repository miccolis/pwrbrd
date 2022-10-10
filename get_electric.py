"""Updates history with today's update"""
import sys
import os
import json
import logging
from datetime import date, datetime, timedelta, timezone
from util.fetch_enphase import EnphaseClient
from util.fetch_pepco import PepcoOpowerClient


def get_raw_generation(day):
    enphase = EnphaseClient(
        os.getenv("ENPHASE_CLIENT_ID"),
        os.getenv("ENPHASE_CLIENT_SECRET"),
        os.getenv("ENPHASE_API_KEY"),
    )
    enphase.load_enphase_creds(
        os.getenv("ENPHASE_EMAIL"),
        os.getenv("ENPHASE_PASSWORD"),
    )

    # enphase.v4_request("systems", {})
    system_id = os.getenv("ENPHASE_SYSTEM_ID")

    # TODO account for timezone/DST offset
    start_at = int(datetime.fromisoformat(day).timestamp())

    # From conversation with Enphase support: If the granularity is specified as day, maximum of
    # 288 intervals will appear in response where each interval is of 5 mins duration.

    return enphase.v4_request(
        f"systems/{system_id}/telemetry/production_micro",
        {"granularity": "day", "start_at": start_at},
    )


def convert_generation_response(payload):
    # {'end_at': 1678448400, 'devices_reporting': 19, 'powr': 6, 'enwh': 1}
    intervals = []
    hour_back = timedelta(hours=-1)
    current_key = None
    current_wh = 0
    for reading in payload[payload["items"]]:
        ends_on = datetime.fromtimestamp(reading["end_at"]).minute
        if ends_on == 60:
            period_key = (
                datetime.fromtimestamp(reading["end_at"], tz=timezone.utc).replace(
                    minute=0
                )
                + hour_back
            ).isoformat()
        else:
            period_key = (
                datetime.fromtimestamp(reading["end_at"], tz=timezone.utc)
                .replace(minute=0)
                .isoformat()
            )

        if current_key is None:
            current_key = period_key
        elif period_key != current_key:
            intervals.append({"start_at": current_key, "kwh": current_wh / 1000})
            current_key = None
            current_wh = 0

        current_wh += reading["enwh"]

    if current_wh > 0:
        intervals.append({"start_at": current_key, "kwh": current_wh / 1000})

    return intervals


def get_raw_consumption(day):
    client = PepcoOpowerClient()
    client.load_opower_creds(
        os.getenv("PEPCO_SIGNIN_NAME"), os.getenv("PEPCO_PASSWORD")
    )
    return client.opower_request(day)


def convert_consumption_response(payload):
    # {'startTime': '2023-03-20T00:00:00.000-04:00', 'endTime': '2023-03-20T01:00:00.000-04:00',
    # 'consumption': {'value': 0.27, 'type': 'ACTUAL'}, 'demand': None, 'exported': None,
    # 'grossConsumption': None, 'grossGeneration': None, 'imported': None, 'reactivePower': None,
    # 'providedCost': None, 'milesDriven': 0}
    return [
        {
            "start_at": datetime.fromisoformat(v["startTime"])
            .astimezone(tz=timezone.utc)
            .isoformat(),
            "kwh": v["consumption"]["value"],
        }
        for v in payload["reads"]
    ]


def merge_generation_consumption(generation, consumption):
    merged = {
        v["start_at"]: {"net": v["kwh"], "consumption": v["kwh"], "generation": 0}
        for v in consumption
    }

    for gen in generation:
        key = gen["start_at"]
        if key in merged:
            cur = merged[key]
            cur["generation"] = gen["kwh"]
            cur["consumption"] = cur["net"] + cur["generation"]
        else:
            logging.error(f"{key} not present in consumption reponse")

    return merged


def main():
    """Get generation and net use from 2 days ago, merge together"""
    if len(sys.argv) > 1:
        start_time = sys.argv[1]
    else:
        start_time = (date.today() + timedelta(days=-2)).isoformat()

    gen = convert_generation_response(get_raw_generation(start_time))

    con = convert_consumption_response(get_raw_consumption(start_time))

    print(json.dumps(merge_generation_consumption(gen, con)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
