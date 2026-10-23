"""WLAN-Verwaltung der Fotobox ueber NetworkManager (nmcli).

Alle Aufrufe laufen ueber `sudo -n nmcli`; der Installer legt dafuer eine
sudoers-Regel an (/etc/sudoers.d/fotobox). Ohne diese Regel liefern die
Funktionen eine Fehlermeldung statt zu haengen (-n = niemals nach Passwort
fragen).

Modi (siehe status()):
  client   - mit einem fremden WLAN verbunden (Normalfall)
  ethernet - nur Kabel
  ap       - eigener Hotspot aktiv (Fallback oder Autark-Modus)
  offline  - gar keine Verbindung (Uebergangszustand)

Ein Verbindungswechsel laeuft in einem Hintergrund-Thread, weil das Tablet
dabei selbst die Verbindung zum Pi verliert und keine Antwort mehr abholen
kann. Das Ergebnis landet in last_error (Fehler) bzw. wird verworfen (ok).
"""
import os
import socket
import subprocess
import threading

import config

_ENV = dict(os.environ, LANG="C", LC_ALL="C")
_lock = threading.Lock()
_job = {"running": False, "ssid": None}


class WifiError(Exception):
    pass


# --------------------------------------------------------------------------
# nmcli-Helfer
# --------------------------------------------------------------------------
def _nmcli(*args, timeout=20, check=True):
    """Fuehrt `sudo -n nmcli ARGS` aus und gibt stdout (ohne Zeilenumbruch am Ende) zurueck."""
    cmd = ["sudo", "-n", config.NMCLI, *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, env=_ENV)
    except FileNotFoundError:
        raise WifiError("nmcli/sudo nicht gefunden - laeuft die App auf dem Pi?")
    except subprocess.TimeoutExpired:
        raise WifiError(f"nmcli {' '.join(args[:3])} ... antwortet nicht")
    if check and r.returncode != 0:
        err = (r.stderr or r.stdout).strip() or f"nmcli Exit-Code {r.returncode}"
        if "a password is required" in err or "sudo:" in err:
            err = ("Keine Rechte fuer nmcli. Bitte Installer erneut ausfuehren "
                   "(sudo ~/fotobox/install.sh). Details: " + err)
        raise WifiError(err)
    return r.stdout.rstrip("\n")


def _split(line):
    """Zerlegt eine Zeile aus `nmcli -t` (Doppelpunkt-getrennt, '\\:' ist escaped)."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _rows(*args, **kw):
    out = _nmcli("-t", *args, **kw)
    return [_split(l) for l in out.splitlines() if l.strip()]


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


# --------------------------------------------------------------------------
# Lesen
# --------------------------------------------------------------------------
def autark_enabled():
    return os.path.exists(config.AUTARK_FLAG)


def known_networks():
    """{ssid: profilname} aller gespeicherten WLAN-Profile (ohne den Hotspot)."""
    known = {}
    for row in _rows("-f", "NAME,TYPE", "con", "show"):
        if len(row) < 2 or row[1] != "802-11-wireless" or row[0] == config.AP_CON_NAME:
            continue
        ssid = _nmcli("-g", "802-11-wireless.ssid", "con", "show", row[0], check=False)
        if ssid:
            known[ssid] = row[0]
    return known


def ap_settings():
    """SSID und Passwort des Hotspot-Profils (Passwort braucht -s = show secrets)."""
    ssid = _nmcli("-g", "802-11-wireless.ssid", "con", "show", config.AP_CON_NAME,
                  check=False) or config.AP_SSID_DEFAULT
    psk = _nmcli("-s", "-g", "802-11-wireless-security.psk", "con", "show",
                 config.AP_CON_NAME, check=False)
    return ssid, psk


def status():
    """Zusammenfassung fuer die /wlan-Seite."""
    info = {
        "mode": "offline", "ssid": None, "ips": [],
        "hostname": socket.gethostname(),
        "autark": autark_enabled(),
        "ap_ssid": config.AP_SSID_DEFAULT, "ap_password": "",
        "ap_ip": config.AP_IP, "port": config.PORT,
        "busy": _job["running"], "busy_ssid": _job["ssid"],
        "last_error": _read(config.WIFI_ERROR_FILE),
        "error": None,
    }
    try:
        ap_active = False
        for row in _rows("-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"):
            if len(row) < 4:
                continue
            dev, typ, state, con = row[:4]
            if typ not in ("wifi", "ethernet") or state != "connected":
                continue
            ip = _nmcli("-g", "IP4.ADDRESS", "dev", "show", dev, check=False)
            ip = ip.splitlines()[0].split("/")[0] if ip else ""
            info["ips"].append({"dev": dev, "ip": ip, "con": con})
            if con == config.AP_CON_NAME:
                ap_active = True
            elif typ == "wifi":
                info["ssid"] = _nmcli("-g", "802-11-wireless.ssid", "con", "show",
                                      con, check=False) or con
                info["mode"] = "client"
            elif info["mode"] == "offline":
                info["mode"] = "ethernet"
        if ap_active:
            info["mode"] = "ap"
        info["ap_ssid"], info["ap_password"] = ap_settings()
    except WifiError as e:
        info["error"] = str(e)
    return info


def scan():
    """Liste sichtbarer Netze [{ssid, signal, security, known}], staerkstes zuerst.

    Im Hotspot-Modus kann wlan0 nicht scannen; dann wird der vom Boot-Skript
    (fotobox-wifi-check) vor dem Hotspot-Start gespeicherte Scan verwendet.
    """
    cached = False
    try:
        if status()["mode"] == "ap":
            raise WifiError("ap")
        out = _nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
                     "--rescan", "auto", timeout=30)
    except WifiError:
        out = _read(config.SCAN_CACHE)
        cached = True
    known = {}
    try:
        known = known_networks()
    except WifiError:
        pass
    best = {}
    for line in out.splitlines():
        row = _split(line)
        if len(row) < 3 or not row[0]:
            continue
        ssid, sig, sec = row[0], row[1], row[2]
        try:
            sig = int(sig)
        except ValueError:
            sig = 0
        if ssid not in best or best[ssid]["signal"] < sig:
            best[ssid] = {"ssid": ssid, "signal": sig, "security": sec,
                          "known": ssid in known}
    nets = sorted(best.values(), key=lambda n: -n["signal"])
    return {"networks": nets, "cached": cached}


# --------------------------------------------------------------------------
# Schreiben
# --------------------------------------------------------------------------
def _key_mgmt(security):
    """nmcli-Schluesselverwaltung aus der SECURITY-Spalte des Scans ableiten."""
    s = (security or "").upper()
    if "WPA3" in s and "WPA2" not in s and "WPA1" not in s:
        return "sae"
    return "wpa-psk"


def connect(ssid, password="", hidden=False, security=""):
    """Startet den Wechsel zu `ssid` im Hintergrund. Wirft WifiError bei Eingabefehlern."""
    ssid = (ssid or "").strip()
    if not ssid:
        raise WifiError("Bitte einen WLAN-Namen (SSID) angeben.")
    if password and len(password) < 8:
        raise WifiError("WLAN-Passwort muss mindestens 8 Zeichen haben.")
    if ssid == config.AP_CON_NAME or ssid == ap_settings()[0]:
        raise WifiError("Das ist der eigene Hotspot der Fotobox - damit kann sie sich nicht verbinden.")
    with _lock:
        if _job["running"]:
            raise WifiError(f"Es laeuft bereits ein Verbindungsversuch ({_job['ssid']}).")
        _job.update(running=True, ssid=ssid)
    t = threading.Thread(target=_connect_worker, name="wifi-connect",
                         args=(ssid, password, hidden, security), daemon=True)
    t.start()


def _connect_worker(ssid, password, hidden, security):
    try:
        try:
            os.remove(config.WIFI_ERROR_FILE)
        except OSError:
            pass
        # Wer ein fremdes WLAN waehlt, will keinen dauerhaften Hotspot mehr.
        if autark_enabled():
            try:
                os.remove(config.AUTARK_FLAG)
            except OSError:
                pass
        # Vorhandenes Profil fuer diese SSID ersetzen (sauberer als modify).
        for name in {ssid, *[n for s, n in known_networks().items() if s == ssid]}:
            _nmcli("con", "delete", name, check=False)
        add = ["con", "add", "type", "wifi", "ifname", config.WIFI_IFACE,
               "con-name", ssid, "ssid", ssid, "connection.autoconnect", "yes"]
        if password:
            add += ["wifi-sec.key-mgmt", _key_mgmt(security), "wifi-sec.psk", password]
        if hidden:
            add += ["802-11-wireless.hidden", "yes"]
        _nmcli(*add)
        # Aktiviert das neue Profil; ein aktiver Hotspot auf wlan0 wird dabei
        # von NetworkManager automatisch beendet.
        # -w: nmcli selbst wartet maximal so lange auf die Aktivierung.
        _nmcli("-w", str(config.WIFI_CONNECT_TIMEOUT), "con", "up", ssid,
               timeout=config.WIFI_CONNECT_TIMEOUT + 15)
        # Der NetworkManager-Dispatcher (system/90-fotobox-ap) startet bei
        # erfolgreicher Verbindung den Tunnel-Dienst wieder.
    except WifiError as e:
        msg = str(e)
        if "Secrets were required" in msg or "secrets" in msg.lower():
            msg = f"Verbindung mit '{ssid}' fehlgeschlagen - Passwort falsch?"
        elif "No network with SSID" in msg or "not found" in msg.lower():
            msg = f"WLAN '{ssid}' nicht gefunden (ausser Reichweite oder versteckt?)."
        else:
            msg = f"Verbindung mit '{ssid}' fehlgeschlagen: {msg}"
        _write(config.WIFI_ERROR_FILE, msg)
        # Fehlgeschlagenes Profil nicht liegen lassen (wuerde beim Boot stoeren).
        _nmcli("con", "delete", ssid, check=False)
        _restore_hotspot_if_offline()
    except Exception as e:                       # noqa: BLE001 - alles protokollieren
        _write(config.WIFI_ERROR_FILE, f"Interner Fehler: {e}")
        _restore_hotspot_if_offline()
    finally:
        with _lock:
            _job.update(running=False, ssid=None)


def _restore_hotspot_if_offline():
    """Nach einem Fehlversuch: ohne andere Verbindung den Hotspot wieder oeffnen."""
    try:
        if status()["mode"] == "offline":
            _nmcli("con", "up", config.AP_CON_NAME, timeout=40, check=False)
    except WifiError:
        pass


def forget(ssid):
    ssid = (ssid or "").strip()
    names = [n for s, n in known_networks().items() if s == ssid]
    if not names:
        raise WifiError(f"Kein gespeichertes Profil fuer '{ssid}'.")
    for n in names:
        _nmcli("con", "delete", n)


def set_ap(ssid, password):
    """Hotspot-Name/-Passwort aendern; bei aktivem Hotspot sofort neu starten."""
    ssid = (ssid or "").strip()
    if not ssid or len(ssid) > 32:
        raise WifiError("Hotspot-Name muss 1-32 Zeichen lang sein.")
    if len(password) < 8 or len(password) > 63:
        raise WifiError("Hotspot-Passwort muss 8-63 Zeichen lang sein.")
    _nmcli("con", "modify", config.AP_CON_NAME,
           "802-11-wireless.ssid", ssid, "wifi-sec.psk", password)
    if status()["mode"] == "ap":
        threading.Thread(target=lambda: _nmcli("con", "up", config.AP_CON_NAME,
                                               timeout=40, check=False),
                         daemon=True).start()


def set_autark(enabled):
    """Autark-Modus schalten und den Boot-Check neu ausfuehren (bringt Hotspot hoch/runter)."""
    if enabled:
        _write(config.AUTARK_FLAG, "1\n")
    else:
        try:
            os.remove(config.AUTARK_FLAG)
        except OSError:
            pass
    # fotobox-wifi.service entscheidet anhand des Flags (Hotspot vs. bekanntes Netz)
    # und stoppt/startet den Tunnel. Laeuft asynchron, weil die Verbindung wechselt.
    subprocess.Popen(["sudo", "-n", "/usr/bin/systemctl", "restart", "--no-block",
                      "fotobox-wifi"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, env=_ENV)
