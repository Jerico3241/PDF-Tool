# Releases: Beta und Stable

PDF Tool kennt zwei Update-Kanäle. **Stable** (Standard) erhält nur freigegebene Versionen,
**Beta** zusätzlich Vorabversionen zum Testen. Die App liest dafür die GitHub-Releases des
offiziellen Repositories `Jerico3241/PDF-Tool` – ein Release ist damit sofort für den passenden
Kanal sichtbar. Technische Einzelheiten des Updaters: [`windows-app/ARCHITECTURE.md`](../windows-app/ARCHITECTURE.md).

## Versionen und Namen

| | Stable | Beta |
| --- | --- | --- |
| `windows-app/VERSION` | `2.8.0` | `2.8.0-beta.1`, `2.8.0-beta.2` … |
| Git-Tag | `v2.8.0` | `v2.8.0-beta.1` |
| GitHub-Release | normales Release („Latest“) | Vorabversion (Prerelease), nie „Latest“ |
| Setup | `PDF-Tool-Setup-2.8.0.exe` | `PDF-Tool-Setup-2.8.0-beta.1.exe` |
| Prüfsumme | `PDF-Tool-Setup-2.8.0.exe.sha256` | `PDF-Tool-Setup-2.8.0-beta.1.exe.sha256` |
| Release Notes | `windows-app/release-notes/2.8.0.md` | `windows-app/release-notes/2.8.0-beta.1.md` |

Versionen folgen [Semantic Versioning](https://semver.org): `2.8.0-beta.1 < 2.8.0-beta.2 < 2.8.0`.
Andere Vorabkennungen (`-rc.1`, `-alpha`) verwendet das Projekt nicht; der Build lehnt sie ab. Die App
zeigt die Version vollständig an (Einstellungen → Updates und „Über“: `2.8.0-beta.1` mit
Beta-Kennzeichen). Die Windows-Dateiversion des Setups enthält nur den Zahlenteil (`2.8.0.0`).

Jedes Release braucht **beide Dateien** mit genau diesen Namen. Die Prüfsummendatei hat das Format
von `sha256sum` – 64 Hex-Zeichen, zwei Leerzeichen, Dateiname, Zeilenende:

```
3cd865b7b1a82d7045aae23b558c9af319368ace8447b7fcab4f27072f9d3bd9  PDF-Tool-Setup-2.7.1.exe
```

Ohne Prüfsumme oder mit falscher Prüfsumme installiert die App nichts. Ein Release ohne passende
Dateien bieten die Kanäle nicht an. Entwürfe (Drafts) sehen weder Stable noch Beta.

## Verbindliche Regel: Beta vor Stable

- **Jede neue Funktionsversion beginnt als Beta** `X.Y.Z-beta.1` – als GitHub-Vorabversion mit
  eigenem Setup und eigener Prüfsummendatei.
- **Weitere Betas** (`-beta.2`, `-beta.3` …) beheben Fehler. Eine veröffentlichte Beta wird nie
  überschrieben oder ersetzt.
- **Stable erst nach ausdrücklichem Test und ausdrücklicher Freigabe** – als eigens gebautes Release
  aus `windows-app/VERSION` `X.Y.Z`, nie eine umbenannte Beta.
- **Patch-Hotfix ohne Beta** (`X.Y.Z` mit Z > 0) nur nach ausdrücklicher Entscheidung. Änderungen an
  PDF-Verarbeitung, Datenformaten, Installer, Updater, Sicherung/Wiederherstellung, Qt/QML, Regeln,
  Vorlagen oder Persistenz gehen immer zuerst als Beta hinaus.

Der Release-Workflow setzt die Regel durch (Schritt „Beta vor Stable“): Ein stabiles Release bricht
ab, wenn es keine veröffentlichte Beta derselben Version gibt (`vX.Y.Z-beta.N`, Vorabversion, kein
Entwurf). Einzige Ausnahme: ein manueller Lauf mit `hotfix_ohne_beta: true` für eine Patch-Version
(Z > 0) – eine neue Funktionsversion (`X.Y.0`) kann nie ohne Beta Stable werden.

## Ablauf

Beispiel 2.8.0:

```
v2.8.0-beta.1  →  testen  →  Fehler gefunden  →  v2.8.0-beta.2  →  testen  →  v2.8.0-beta.3  →  freigeben  →  v2.8.0
```

1. **Beta veröffentlichen:** `windows-app/VERSION` auf `2.8.0-beta.1` setzen, Release Notes
   `windows-app/release-notes/2.8.0-beta.1.md` anlegen, per Pull Request auf `main` bringen. Dann
   entweder den Tag setzen

   ```
   git tag v2.8.0-beta.1
   git push origin v2.8.0-beta.1
   ```

   oder den Workflow „Windows-Setup“ auf `main` mit `release: true` starten. Der Workflow baut das
   Setup, führt alle Tests und Installer-Prüfungen aus und veröffentlicht danach eine
   **GitHub-Vorabversion** mit Setup und Prüfsumme. Anschließend den Workflow „Update-Test“
   starten (`von: 2.7.2`, `ziel: 2.8.0-beta.1`, `kanal: beta`): Er aktualisiert eine installierte
   stabile Version über ihren eigenen Updater im Kanal „Beta“ und prüft das Ergebnis.
2. **Weitere Betas** genauso mit `2.8.0-beta.2`, `2.8.0-beta.3` …
3. **Stable veröffentlichen:** bewusst und erst nach Test und Freigabe – `windows-app/VERSION` auf
   `2.8.0`, Release Notes `2.8.0.md`, Pull Request, dann Tag `v2.8.0` (bzw. Workflow mit
   `release: true`). Der Workflow baut das Setup neu und prüft, dass eine Beta von `2.8.0`
   veröffentlicht ist. Es entsteht ein **normales Release**, das „Latest“ wird. Anschließend den
   Workflow „Update-Test“ für beide Wege starten: `von: 2.7.2`, `ziel: 2.8.0`, `kanal: stable`
   (Anwender der stabilen Version) und `von: 2.8.0-beta.1`, `ziel: 2.8.0`, `kanal: beta`
   (Beta-Tester; die letzte Beta der Version).

Eine Beta wird nie automatisch zu Stable: Der Kanal eines Releases folgt allein aus der Version in
`windows-app/VERSION`, die ein Mensch per Pull Request ändert.

Hinweis: Die Downloadseite (`src/components/landing-page.tsx`) zeigt die Version aus
`windows-app/VERSION` – während einer Beta-Phase auf `main` also die Beta.

## Prüfungen vor der Veröffentlichung

`windows-app/release_check.py` läuft im Build und noch einmal im Release-Schritt:

- Version gültig (`X.Y.Z` oder `X.Y.Z-beta.N`), Tag `vX.Y.Z…` passt zu `windows-app/VERSION` und
  zeigt auf einen Stand von `main`
- Setup und Prüfsummendatei vorhanden, Namen exakt nach der Konvention, keine fremden Dateien
- die Prüfsumme gehört exakt zum Setup, die Dateiversion im Setup stimmt
- Release Notes vorhanden

Nach der Veröffentlichung prüft der Workflow das Release: Tag → Commit, Vorabversion ja/nein,
genau die beiden Dateien, veröffentlichte Prüfsumme = gebaute Prüfsumme.

Veröffentlichte Releases sind unveränderlich: Gibt es das Release einer Version schon (oder beim
manuellen Start bereits ihren Tag), bricht der Workflow ab; Tags werden nie verschoben, Dateien eines
Releases nie überschrieben. Eine Korrektur erscheint als neue Version (z. B. `2.8.0-beta.2` oder
`2.8.1`).

## Was die Kanäle sehen

- **Stable:** nur Releases ohne Vorabkennung, auf GitHub nicht als Vorabversion markiert, keine
  Entwürfe, neuer als die installierte Version.
- **Beta:** zusätzlich Beta-Vorabversionen. Ein Beta-Nutzer erhält auch die stabile Version, sobald sie
  neuer ist (`2.8.0-beta.3` → `2.8.0`), und bleibt danach im Beta-Kanal (`2.8.1-beta.1` …).
- **Kein Downgrade:** Wer von Beta auf Stable wechselt, bleibt auf seiner Beta, bis eine neuere stabile
  Version erscheint.
