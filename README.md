# Google Translate transcript export

Egyszerű Windows-alkalmazás, amely a Google Fordító (Android) **mentett átiratait** szövegfájlba menti a telefonról, USB-n, adb segítségével. Root nem kell.

*English: a small Windows app that exports saved transcripts from the Google Translate Android app to Markdown files over adb, without root. It reads the screen via `uiautomator dump` while you scroll through the transcript.*

## Miért kell ehhez külön eszköz?

- Az átiratok a Fordító privát adatbázisában vannak. Root nélkül nem érhetők el (`run-as`: az app nem debuggable).
- `adb backup`: az Android 12 óta az ADB-mentés kihagyja a 31-es vagy újabb targetSdk-ra fordított appok adatait.
- Az appon belüli kijelölés és másolás hosszú átiratnál elvágja a szöveget, és szekciónként kell kijelölni.

Ez az eszköz ehelyett a képernyőn lévő felület szövegét olvassa ki (`uiautomator dump`), miközben te végiggörgeted az átiratot.

## Követelmények

- Windows 10/11
- Python 3.10 vagy újabb (csak beépített modulok, nincs `pip install`)
- Android Platform Tools (`adb`), például: `winget install Google.PlatformTools`
- A telefonon bekapcsolt **USB-hibakeresés**, és engedélyezett hozzáférés a számítógéphez

Az `adb`-t a program magától megkeresi: `GT_ADB` környezeti változó, PATH, a winget-es Platform Tools mappa, végül az Android SDK.

## Telepítés

PowerShellben:

```powershell
git clone https://github.com/sanchomuzax/google-translate-transcript-export.git
cd google-translate-transcript-export
python -m venv .venv
.venv\Scripts\python.exe install_launcher.py
```

Az utolsó lépés létrehoz egy **Atirat** nevű parancsikont az Asztalon és a Start menüben. Indítás: Start gomb, beírod, hogy `atirat`, Enter.

## Használat

1. Csatlakoztasd a telefont. Az ablak tetején zöld pötty jelzi, ha a telefon elérhető és a Fordító van előtérben.
2. Nyisd meg a Fordítóban a mentett átiratot.
3. Nyomd meg: **Import start**.
4. Tekerd **fel a tetejére**, aztán **le az aljára**. Az ablak mutatja: `Teteje ✓  Alja ✓`.
5. Ha mindkettő ✓, az app pár másodperc múlva magától ment. A kék **Kész** gombbal kézzel is lezárhatod.

A mentett fájlok az `atiratok\` mappába kerülnek (ablakban: **Mappa megnyitása**). Ugyanazt a szöveget nem menti el kétszer.

### Kimenet

Markdown fájl. Ha az átirat több szekcióból áll (a felvétel közben leállítás és újraindítás volt), a szekciók külön fejlécet kapnak a nyelvpárral:

```markdown
## 1. szekció (angol → magyar)

...

## 2. szekció (magyar → angol)

...
```

Csak a **fordított** szöveg kerül mentésre, az eredeti nem.

## Hogyan működik

- Kb. 3 másodpercenként friss `uiautomator dump` készül egyedi fájlnévre. A program ellenőrzi a parancs kimenetét, lehúzza a fájlt, majd a telefonról azonnal törli. Így régi dump soha nem kerülhet újra elő.
- Az átirat minden szekciója külön elem a Fordító listájában (`recycler_view`), és a dump csak a képernyőn lévő elemeket tartalmazza. Egy szekció teljes szövege viszont akkor is benne van, ha csak egy része látszik.
- A program a dumpok közti átfedés alapján fűzi össze a szekciókat, fel- és lefelé görgetésnél is helyes sorrendben. Az azonos szövegű szekciók (például két külön "Oké.") megmaradnak.
- **Lista alja:** az utolsó szekció alatt üres rés marad. **Lista teteje:** a felső sáv kinyitva áll, és a legfelső szekció nyelvpár-fejléce látszik.
- Ha két olvasás között nincs közös szekció (túl gyors görgetés), az ablak figyelmeztet, hogy kimaradhatott szekció.

## Parancssoros mód

```powershell
.venv\Scripts\python.exe gt_pull.py
```

## Fájlok

| Fájl | Szerep |
|---|---|
| `gt_gui.py` | Az ablakos alkalmazás |
| `gt_pull.py` | A motor (adb, dump, kinyerés, összefűzés, mentés), parancssorból is futtatható |
| `install_launcher.py` | Az **Atirat** parancsikon létrehozása |
| `make_icon.py` | Az `atirat.ico` ikon előállítása |

## Korlátok

- A Fordító belső azonosítóira épül (`translated_text`, `content_root`, `recycler_view`, `app_bar_layout`). Ha a Google megváltoztatja az app felületét, igazítani kell rajta.
- Tesztelve: Xiaomi 14T, HyperOS 3 (Android 16), Google Fordító 10.37.
- A görgetést kézzel kell végezni, mert az `adb shell input` ezen a telefonon nem engedélyezett (`INJECT_EVENTS`).
