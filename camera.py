"""Kamera-Anbindung der Fotobox (Canon EOS M50 via gphoto2).

Die `CameraManager`-Klasse besitzt die Kamera exklusiv. Ein Hintergrund-Thread
(Supervisor) liest fortlaufend Liveview-Frames von `gphoto2 --capture-movie
--stdout`. Neue Frames werden ueber eine `threading.Condition` veroeffentlicht,
sodass Stream-Konsumenten *sofort* geweckt werden, statt zu pollen.

Fuer ein Vollbild wird der Liveview kurz pausiert (gphoto2 erlaubt nur einen
Kamerazugriff gleichzeitig), das Foto aufgenommen und der Liveview danach vom
Supervisor automatisch wieder gestartet.
"""
import os
import subprocess
import threading
import time
from datetime import datetime

import config

JPEG_SOI = b"\xff\xd8"   # Start of Image
JPEG_EOI = b"\xff\xd9"   # End of Image


class CameraManager:
    def __init__(self):
        self._frame = None            # zuletzt empfangenes JPEG (bytes) oder None
        self._frame_ctr = 0           # zaehlt hoch bei jedem neuen Frame
        self._frame_ts = 0.0          # Zeitpunkt des letzten Frames (monotonic)
        self._cond = threading.Condition()  # schuetzt frame/ctr/ts UND weckt Streams
        self._cam_lock = threading.Lock()   # serialisiert exklusiven Kamerazugriff
        self._paused = threading.Event()     # gesetzt => Liveview ruht (Capture laeuft)
        self._proc = None
        self._use_card = None         # None = noch nicht geprueft; True = SD-Karte in der Kamera
        self._stop = False
        self._sup = threading.Thread(target=self._supervise,
                                     name="liveview", daemon=True)
        self._sup.start()

    # ---- Supervisor: haelt den Liveview am Leben -----------------------
    def _supervise(self):
        while not self._stop:
            if self._paused.is_set():
                time.sleep(0.2)
                continue
            with self._cam_lock:
                if self._paused.is_set():
                    continue
                produced = self._run_liveview_once()
            time.sleep(config.SUPERVISOR_RETRY_OK if produced
                       else config.SUPERVISOR_RETRY_FAIL)

    def _run_liveview_once(self):
        """Startet gphoto2-Movie und veroeffentlicht Frames bis Abbruch.

        Gibt True zurueck, wenn mindestens ein Frame kam (= Kamera ist da).
        """
        try:
            self._proc = subprocess.Popen(
                ["gphoto2", "--capture-movie", "--stdout"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        except Exception:
            self._proc = None
            return False
        produced = False
        try:
            for frame in self._iter_jpeg(self._proc.stdout):
                self._publish(frame)
                produced = True
        except Exception:
            pass
        finally:
            self._kill_proc()
        return produced

    def _iter_jpeg(self, stream):
        """Zerlegt den fortlaufenden MJPEG-Bytestrom in einzelne JPEG-Frames.

        Nutzt ein wachsendes bytearray (amortisiert O(1) beim Anhaengen) statt
        wiederholter bytes-Verkettung.
        """
        buf = bytearray()
        while not self._paused.is_set() and not self._stop:
            chunk = stream.read(config.LIVEVIEW_READ_CHUNK)
            if not chunk:
                break
            buf += chunk
            while True:
                start = buf.find(JPEG_SOI)
                if start == -1:
                    # kein Frame-Anfang in Sicht -> nicht endlos wachsen lassen
                    if len(buf) > 2_000_000:
                        del buf[:]
                    break
                end = buf.find(JPEG_EOI, start + 2)
                if end == -1:
                    if start > 0:        # Muell vor dem Frame-Anfang verwerfen
                        del buf[:start]
                    break
                yield bytes(buf[start:end + 2])
                del buf[:end + 2]

    def _publish(self, frame):
        with self._cond:
            self._frame = frame
            self._frame_ctr += 1
            self._frame_ts = time.monotonic()
            self._cond.notify_all()

    def _kill_proc(self):
        p, self._proc = self._proc, None
        if p:
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    # ---- Konsumenten-API ----------------------------------------------
    def frames(self, timeout=None):
        """Generator: liefert das neueste JPEG, sobald ein neues vorliegt.

        Blockiert ohne Polling (Condition.wait_for) bis ein neuer Frame da ist.
        Laeuft das Timeout ab, wird der letzte bekannte Frame erneut geliefert
        (Keepalive haelt die HTTP-Verbindung offen). Liefert None, solange noch
        gar kein Frame empfangen wurde.
        """
        timeout = config.STREAM_WAIT_TIMEOUT if timeout is None else timeout
        min_interval = 1.0 / config.STREAM_MAX_FPS if config.STREAM_MAX_FPS else 0
        last = -1
        last_sent = 0.0
        while not self._stop:
            with self._cond:
                self._cond.wait_for(lambda: self._frame_ctr != last,
                                    timeout=timeout)
                frame = self._frame
                ctr = self._frame_ctr
            now = time.monotonic()
            # Framerate drosseln: neue Frames, die zu schnell aufeinander folgen,
            # ueberspringen (immer der neueste wird gesendet). Bei Timeout bleibt
            # ctr == last -> letzter Frame als Keepalive, nicht gedrosselt.
            if ctr != last and min_interval and (now - last_sent) < min_interval:
                last = ctr
                continue
            last = ctr
            last_sent = now
            yield frame

    def is_live(self):
        """True, wenn kuerzlich ein Frame kam (Kamera liefert Liveview)."""
        with self._cond:
            if not self._frame_ts:
                return False
            return (time.monotonic() - self._frame_ts) < config.LIVE_FRESH_SECONDS

    def capture(self):
        """Pausiert den Liveview, nimmt ein Vollbild auf, setzt ihn fort.

        Gibt den Dateinamen des heruntergeladenen Fotos zurueck.
        """
        self._paused.set()
        self._kill_proc()
        try:
            with self._cam_lock:       # wartet, bis der Supervisor die Kamera freigibt
                time.sleep(0.5)
                return self._capture_still()
        finally:
            self._paused.clear()       # Supervisor startet den Liveview danach neu

    NO_CARD = "4294967295"        # availableshots = 0xFFFFFFFF -> keine Speicherkarte

    def _card_present(self):
        """True, wenn die Kamera eine Speicherkarte meldet (Abfrage ca. 1 s)."""
        try:
            r = subprocess.run(["gphoto2", "--get-config", "availableshots"],
                               capture_output=True, text=True, timeout=20)
        except Exception:
            return False
        for line in r.stdout.splitlines():
            if line.startswith("Current:"):
                return line.split(":", 1)[1].strip() != self.NO_CARD
        return False

    def _run_capture(self, target, capturetarget):
        """Ein gphoto2-Aufnahmeversuch; gibt die gesammelte Ausgabe zurueck."""
        result = subprocess.run(
            ["gphoto2", "--set-config-index", f"capturetarget={capturetarget}",
             "--capture-image-and-download",
             "--filename", target, "--force-overwrite"],
            capture_output=True, text=True, timeout=config.CAPTURE_TIMEOUT)
        output = (result.stderr.strip() + "\n" + result.stdout.strip()).strip()
        if result.returncode != 0:
            raise RuntimeError(output or "Unbekannter gphoto2-Fehler")
        return output

    def _capture_still(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = os.path.join(config.PHOTO_DIR, f"fotobox_{ts}.%C")
        # capturetarget=1 (Karte): Bild bleibt zusaetzlich auf der Kamera-SD als Backup.
        # Ohne Karte verweigert die Kamera die Aufnahme -> capturetarget=0 (interner RAM).
        # Die Entscheidung wird gemerkt und nur nach einem Fehlschlag neu geprueft.
        if self._use_card is None:
            self._use_card = self._card_present()
        output = self._run_capture(target, 1 if self._use_card else 0)
        # gphoto2 meldet "Could not capture" bei Canon teils mit Exit-Code 0,
        # z.B. ohne Karte, wenn der Autofokus kein Ziel findet oder das Objektiv zu ist.
        if "could not capture" in output.lower() and self._use_card:
            self._use_card = self._card_present()
            if not self._use_card:
                output = self._run_capture(target, 0)
        if "could not capture" in output.lower():
            raise RuntimeError(
                "Kamera konnte nicht ausloesen. Typische Ursachen: Autofokus findet "
                "kein Ziel (zu dunkel/zu nah), Objektivdeckel drauf, Objektiv nicht "
                "ausgefahren, Kamera im Wiedergabe-Modus. gphoto2: " + output)
        made = [f for f in os.listdir(config.PHOTO_DIR)
                if f.startswith(f"fotobox_{ts}")
                and f.lower().endswith(config.ALLOWED_EXT)]
        if not made:
            got = [f for f in os.listdir(config.PHOTO_DIR) if f.startswith(f"fotobox_{ts}")]
            if got:
                raise RuntimeError("Nur RAW erhalten (" + ", ".join(got) + ") - Kamera "
                                   "auf JPEG (z.B. 'Large Fine JPEG') stellen.")
            raise RuntimeError("Aufnahme gemeldet, aber keine Datei erhalten. gphoto2: "
                               + (output or "(keine Ausgabe)"))
        return sorted(made)[0]
