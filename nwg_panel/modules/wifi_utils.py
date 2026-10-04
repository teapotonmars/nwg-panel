"""Wi-Fi identity and security selection without GTK or NetworkManager bindings."""


def security(flags, wpa, rsn):
    combined = wpa | rsn
    if combined & 0x400:
        return "sae"
    if combined & 0x100:
        return "wpa-psk"
    if combined & (0x200 | 0x2000):
        return "enterprise"
    if combined & (0x800 | 0x1000):
        return "owe"
    if combined:
        return "unsupported"
    return "wep" if flags & 1 else "open"


def select_access_points(points):
    """Keep each SSID/security pair, preferring its active BSSID then strength."""
    selected = {}
    for point in points:
        if not point["ssid"]:
            continue
        key = (point["device"], point["ssid"], point["security"])
        old = selected.get(key)
        if old is None or (point["active"], point["strength"]) > (old["active"], old["strength"]):
            selected[key] = point
    return sorted(selected.values(), key=lambda point: (
        not point["active"], -point["strength"], point["ssid"]))


def valid_password(password, mode):
    if mode == "sae":
        return 1 <= len(password.encode("utf-8")) <= 63
    encoded = password.encode("utf-8")
    return (8 <= len(encoded) <= 63 or
            len(password) == 64 and all(char in "0123456789abcdefABCDEF" for char in password))
