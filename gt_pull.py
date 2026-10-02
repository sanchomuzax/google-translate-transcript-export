"""Google Fordító átiratok kimentése adb + uiautomator dump segítségével.

Használat:
    .venv/Scripts/python.exe gt_pull.py            # normál mód
    .venv/Scripts/python.exe gt_pull.py --debug    # címjelöltek kiírása is

Az átirat minden szekciója (stop/restart) külön elem a Fordító listájában, és a
dump csak a képernyőn lévő elemeket tartalmazza. Ezért egy átiraton belül a
script folyamatosan dumpol, amíg a felhasználó lassan végiggörget, és gyűjti a
szekciókat. A telefont kézzel kell navigálni (INJECT_EVENTS nincs).
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

def find_adb():
    """adb keresése: GT_ADB környezeti változó, PATH, winget-es Platform Tools, Android SDK."""
    if os.environ.get("GT_ADB"):
        return os.environ["GT_ADB"]
    found = shutil.which("adb")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = sorted(local.glob("Microsoft/WinGet/Packages/Google.PlatformTools*/platform-tools/adb.exe"))
    candidates.append(local / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    return str(next((c for c in candidates if c.is_file()), "adb"))


ADB = find_adb()
PKG = "com.google.android.apps.translate"
ID = f"{PKG}:id/"

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "atiratok"
DUMP_DIR = BASE_DIR / "dumps"  # nyers XML-ek hibakereséshez

# Az Android forrásban "hierchary" elírással szerepel; mindkét írásmódot elfogadjuk.
DUMP_OK_RE = re.compile(r"UI hier\w*y dumped to:\s*(\S+)")

# Ezek gombfeliratok / UI-elemek, nem címek.
TITLE_BLACKLIST = {
    "", "átirat", "átiratok", "transcript", "transcripts", "magyar", "angol",
    "hungarian", "english", "vissza", "back", "további lehetőségek", "more options",
}


class DumpError(Exception):
    pass


def adb(*args, timeout=60):
    """adb parancs futtatása; (returncode, stdout+stderr) utf-8-ként."""
    # CREATE_NO_WINDOW: a grafikus indításnál (pythonw) ne villanjon fel konzolablak.
    proc = subprocess.run([ADB, *args], capture_output=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace").strip()
    return proc.returncode, out


def check_device():
    code, out = adb("devices")
    devices = [l for l in out.splitlines()[1:] if l.strip().endswith("\tdevice")]
    if code != 0 or not devices:
        raise DumpError(f"Nincs csatlakoztatott eszköz 'device' állapotban:\n{out}")


def device_status():
    """{'state': 'device'|'unauthorized'|'offline'|'none', 'model': str, 'translate': bool}"""
    status = {"state": "none", "model": "", "translate": False}
    code, out = adb("devices", timeout=15)
    states = [l.split("\t")[1].strip() for l in out.splitlines()[1:] if "\t" in l]
    if not states:
        return status
    status["state"] = "device" if "device" in states else states[0]
    if status["state"] != "device":
        return status
    _, model = adb("shell", "getprop ro.product.marketname", timeout=15)
    status["model"] = model.strip()
    _, focus = adb("shell", "dumpsys window | grep mCurrentFocus", timeout=15)
    status["translate"] = PKG in focus
    return status


def fresh_dump():
    """Friss dump egyedi távoli névre, ellenőrzött kimenettel. Visszaadja a helyi XML útvonalát."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    remote = f"/sdcard/gt_dump_{stamp}.xml"
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    local = DUMP_DIR / f"gt_dump_{stamp}.xml"

    try:
        code, out = adb("shell", "uiautomator", "dump", remote, timeout=90)
        m = DUMP_OK_RE.search(out)
        if code != 0 or not m:
            raise DumpError(f"A dump nem sikerült (exit {code}). Kimenet:\n{out}")
        if m.group(1) != remote:
            raise DumpError(f"A dump más fájlba ment ({m.group(1)}), mint amit kértünk ({remote}).")

        code, out = adb("pull", remote, str(local))
        if code != 0 or not local.is_file() or local.stat().st_size == 0:
            raise DumpError(f"A pull nem sikerült (exit {code}):\n{out}")
    finally:
        # Távoli fájl törlése, hogy később véletlenül se lehessen újra lehúzni.
        adb("shell", "rm", "-f", remote)
    return local


def parse_bounds(b):
    nums = [int(x) for x in re.findall(r"-?\d+", b or "")]
    return tuple(nums) if len(nums) == 4 else (0, 0, 0, 0)


def normalize(text):
    # Sortöréseket megtartjuk, a soron belüli többszörös szóközöket/tabokat egyre vonjuk össze.
    text = text.replace("\r\n", "\n").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(xml_path, debug=False):
    """A dumpban látható szekciók listája [(nyelvpár, szöveg)] fentről lefelé, és a cím (vagy None)."""
    root = ET.parse(xml_path).getroot()
    nodes = list(root.iter("node"))

    if not any(n.get("package") == PKG for n in nodes):
        pkgs = sorted({n.get("package", "") for n in nodes} - {""})
        raise DumpError(f"Nem a Google Fordító van előtérben (talált csomag: {', '.join(pkgs)}).")

    # Minden translated_text node egy szekció, elrendezéstől függetlenül. Ha van
    # content_root őse, abból vesszük a nyelvpárt (ha látszik) és a szekció alját.
    parent = {c: p for p in root.iter() for c in p}

    def section_root(n):
        while n is not None and n.get("resource-id") != ID + "content_root":
            n = parent.get(n)
        return n

    sections = []
    bottoms = []
    for tn in nodes:
        if tn.get("resource-id") != ID + "translated_text":
            continue
        cr = section_root(tn)
        langs = None
        if cr is not None:
            labels = {n.get("resource-id"): n.get("text", "") for n in cr.iter("node")}
            lf, lt = labels.get(ID + "language_from_label"), labels.get(ID + "language_to_label")
            if lf and lt:
                langs = f"{lf} → {lt}"
        # Nyelvtől és tartalomtól függetlenül minden szekciót megtartunk, az üreset is.
        sections.append((parse_bounds(tn.get("bounds"))[1], langs, normalize(tn.get("text", ""))))
        bottoms.append(parse_bounds((cr if cr is not None else tn).get("bounds"))[3])

    if not sections:
        others = [(n.get("resource-id") or "-", len(n.get("text", ""))) for n in nodes
                  if n.get("package") == PKG and len(n.get("text", "")) > 20]
        raise DumpError("Nincs translated_text a dumpban (ismeretlen elrendezés?). "
                        f"Hosszabb szövegű node-ok: {others or 'nincs'}. Dump: {Path(xml_path).name}")
    sections.sort(key=lambda s: s[0])

    # Ha az utolsó szekció a lista aljáig ér, alatta lehet még tartalom. A lista végén
    # (mérve) rés marad az utolsó szekció alatt. Lista nélkül nem tudjuk megítélni.
    rv = next((n for n in nodes if n.get("resource-id") == ID + "recycler_view"), None)
    bottom_clipped = rv is None or max(bottoms) >= parse_bounds(rv.get("bounds"))[3]

    # A lista tetején (mérve, 50 dumpon) a felső sáv kinyitva áll (alja a toolbar alatt
    # van), és a legfelső szekció nyelvpár-fejléce látszik.
    appbar = next((n for n in nodes if n.get("resource-id") == ID + "app_bar_layout"), None)
    toolbar = next((n for n in nodes if n.get("resource-id") == ID + "toolbar"), None)
    at_top = (appbar is not None and toolbar is not None and sections[0][1] is not None
              and parse_bounds(appbar.get("bounds"))[3] > parse_bounds(toolbar.get("bounds"))[3])

    title = find_title(nodes, debug)
    return [(langs, text) for _, langs, text in sections], title, bottom_clipped, at_top


def find_title(nodes, debug=False):
    """Cím keresése: Fordító-csomagbeli TextView a toolbar sávjában."""
    toolbar = next((n for n in nodes if n.get("resource-id") == ID + "toolbar"), None)
    limit = parse_bounds(toolbar.get("bounds"))[3] if toolbar is not None else 346

    candidates = []
    for n in nodes:
        if n.get("package") != PKG or "TextView" not in (n.get("class") or ""):
            continue
        if n.get("resource-id") == ID + "translated_text":
            continue
        t = (n.get("text") or "").strip()
        y1, y2 = parse_bounds(n.get("bounds"))[1::2]
        if y2 <= 0 or y1 >= limit:
            continue
        rid = n.get("resource-id", "")
        score = len(t) + (1000 if re.search(r"title|toolbar|header", rid, re.I) else 0)
        candidates.append((score, t, rid, n.get("bounds")))

    if debug:
        print(f"  [debug] toolbar sáv: y < {limit}")
        for c in sorted(candidates, reverse=True):
            print(f"  [debug] jelölt score={c[0]} id={c[2] or '-'} bounds={c[3]} text={c[1][:80]!r}")

    for score, t, rid, _ in sorted(candidates, reverse=True):
        if t.lower() not in TITLE_BLACKLIST and len(t) >= 3:
            return t
    return None


class Collector:
    """Egy átirat szekcióinak gyűjtése több dumpon át, látás szerinti sorrendben."""

    def __init__(self):
        self.sections = []  # [(nyelvpár, szöveg)]
        self.title = None
        self.dumps = 0
        self.errors = 0
        self.gaps = 0
        self.bottom_clipped = True  # az utolsó sikeres dump alapján
        self.top_seen = False  # látszott-e valaha a lista teteje

    def add(self, found, title, at_top=False):
        """Az új dump ablakát az eddigi listához illeszti átfedés alapján (nem szöveg-
        egyezés szerinti szűréssel, így az azonos szövegű szekciók is megmaradnak).
        Visszaadja (új szekciók szövegei, volt-e átfedés)."""
        self.dumps += 1
        self.title = self.title or title
        acc = [t for _, t in self.sections]
        win = [t for _, t in found]

        # A legkésőbbi illeszkedő pozíció: acc[off:] eleje == win eleje (vagy win teljesen acc-on belül).
        offset = None
        for off in range(len(acc) - 1, -1, -1):
            k = min(len(acc) - off, len(win))
            if acc[off:off + k] == win[:k]:
                offset = off
                break

        if offset is None and acc:
            # Felfelé görgetés: az ablak vége illeszkedik az eddigi lista elejére.
            for k in range(min(len(acc), len(win)), 0, -1):
                if win[-k:] == acc[:k]:
                    self.sections[:0] = found[:-k]
                    return found[:-k], True
            if at_top:  # nincs átfedés, de ez a lista teteje: elé kerül
                self.sections[:0] = found
                return found, False

        overlap = offset is not None or not acc
        if offset is None:
            offset = len(acc)
        start = len(acc) - offset  # win-ből ennyi elem már megvan
        for i, (langs, text) in enumerate(found[:start]):  # hiányzó nyelvpár pótlása
            j = offset + i
            if langs and not self.sections[j][0]:
                self.sections[j] = (langs, text)
        new = found[start:]
        self.sections.extend(new)
        return new, overlap

    @property
    def text(self):
        return "\n\n".join(t for _, t in self.sections)


def poll(collector, stop, debug=False, emit=None):
    """Háttérszál: folyamatos friss dump, amíg stop nincs beállítva.

    emit(kind, data) eseményei: "error" (szöveg), "gap" (előtte lévő szekciók száma),
    "section" ((sorszám, nyelvpár, szöveg)), "dump" (None, minden sikeres dump után).
    A sikeres dumpok XML-jét töröljük, a hibásakat megtartjuk hibakereséshez."""
    emit = emit or print_event
    while not stop.is_set():
        xml_path = None
        try:
            xml_path = fresh_dump()
            found, title, bottom_clipped, at_top = extract(xml_path, debug)
        except (DumpError, ET.ParseError, subprocess.TimeoutExpired) as e:
            collector.errors += 1
            # Görgetés közben gyakori, hogy a képernyő nem "idle"; ilyenkor csak újrapróbáljuk.
            emit("error", str(e).splitlines()[0][:120])
            continue
        if not debug:
            xml_path.unlink(missing_ok=True)
        collector.bottom_clipped = bottom_clipped
        collector.top_seen = collector.top_seen or at_top
        before = len(collector.sections)
        new, overlap = collector.add(found, title, at_top)
        if not overlap:
            collector.gaps += 1
            emit("gap", before)
        for i, (langs, text) in enumerate(new, before + 1):
            emit("section", (i, langs, text))
        emit("dump", None)


def print_event(kind, data):
    if kind == "error":
        print(f"  (dump kihagyva: {data[:90]})")
    elif kind == "gap":
        print(f"  !!! Nincs átfedés az előző dumppal: a {data}. és {data + 1}. szekció "
              "között KIMARADHATOTT szekció. Görgess vissza egy kicsit, lassabban.")
    elif kind == "section":
        i, _, text = data
        print(f"  + {i}. szekció: {len(text):>6} kar.  \"{text[:50]}...\"")


def safe_filename(name, max_len=120):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:max_len].rstrip(" .") or None


def render(collector):
    parts = [f"# {collector.title}\n"] if collector.title else []
    multi = len(collector.sections) > 1
    for i, (langs, text) in enumerate(collector.sections, 1):
        if multi:
            parts.append(f"## {i}. szekció" + (f" ({langs})" if langs else "") + "\n")
        parts.append((text or "(üres szekció)") + "\n")
    return "\n".join(parts)


def default_name(collector):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (safe_filename(collector.title) if collector.title else None) or f"atirat_{stamp}"


def save(collector, out_dir=None, name=None):
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = safe_filename(name) if name else None
    base = base or default_name(collector)
    path = out_dir / f"{base}.md"
    if path.exists():  # soha ne írjunk felül meglévő mentést
        path = out_dir / f"{base}_{stamp}.md"
    target = path.resolve()
    if os.name == "nt" and len(str(target)) >= 240:  # MAX_PATH (260) megkerülése hosszú útvonalnál
        target = Path("\\\\?\\" + str(target))
    target.write_text(render(collector), encoding="utf-8")
    return path


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ask_yes_no(prompt):
    while True:
        ans = input(prompt).strip().lower()
        if ans in ("i", "igen", "y", "yes", ""):
            return True
        if ans in ("n", "nem", "no", "q"):
            return False


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--debug", action="store_true", help="címjelöltek kiírása")
    args = ap.parse_args()

    if not Path(ADB).is_file():
        sys.exit(f"Nem található az adb: {ADB}")
    try:
        check_device()
    except DumpError as e:
        sys.exit(str(e))

    print(f"Mentési mappa: {OUT_DIR}")
    prev_hash = None

    while True:
        input("\nNyisd meg az átiratot, görgess a LEGELEJÉRE, majd nyomj Entert... ")
        print("Gyűjtés indul. Görgess LASSAN a végéig (kb. 3 mp-enként frissül), "
              "a végén nyomj Entert.")
        collector = Collector()
        while True:
            stop = threading.Event()
            worker = threading.Thread(target=poll, args=(collector, stop, args.debug), daemon=True)
            worker.start()
            input()
            stop.set()
            print("Utolsó dump befejezése...")
            worker.join()
            if collector.sections and collector.bottom_clipped:
                print("\nFIGYELEM: az utolsó dumpban az utolsó szekció a képernyő aljáig ért, "
                      "alatta LEHET még szekció.")
                if ask_yes_no("Folytatod a gyűjtést (görgess tovább)? [I/n] "):
                    print("Gyűjtés folytatódik, a végén nyomj Entert.")
                    continue
            break

        if not collector.sections:
            print(f"\nHIBA: egyetlen szekciót sem sikerült kiolvasni ({collector.errors} sikertelen dump).")
            if not ask_yes_no("Újrapróbálod? [I/n] "):
                break
            continue

        text = collector.text
        h = sha(text)
        print(f"\nCím:          {collector.title or '(nem található, timestamp lesz a fájlnév)'}")
        print(f"Szekciók:     {len(collector.sections)}  "
              f"({', '.join(str(len(t)) for _, t in collector.sections)} kar.)")
        print(f"Karakterszám: {len(text):,}".replace(",", " "))
        print(f"Dumpok:       {collector.dumps} sikeres, {collector.errors} kihagyva")
        if collector.gaps:
            print(f"FIGYELEM: {collector.gaps} helyen nem volt átfedés két dump között, "
                  "ott kimaradhatott szekció.")

        if h == prev_hash:
            print("FIGYELEM: a szöveg AZONOS az előző mentéssel! "
                  "Nem váltottál átiratot, vagy a képernyő nem frissült.")
            if not ask_yes_no("Mégis mentsem? [I/n] "):
                if not ask_yes_no("Jön még egy átirat? [I/n] "):
                    break
                continue

        path = save(collector)
        prev_hash = h
        print(f"Mentve:       {path}")

        if not ask_yes_no("\nJön még egy átirat? [I/n] "):
            break

    print("Kész.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nMegszakítva.")
