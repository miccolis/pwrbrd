import base64


def btoa(raw):
    """Encode string in base64"""
    return str(base64.b64encode(raw.encode("utf-8")), "utf-8")
