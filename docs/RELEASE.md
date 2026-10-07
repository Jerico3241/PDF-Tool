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

Der Workflow „Release“ setzt die Regel durch (Schritt „Beta vor Stable“): Ein stabiles Release bricht
ab, wenn es keine veröffentlichte Beta derselben Version gibt (`vX.Y.Z-beta.N`, Vorabversion, kein
Entwurf) oder keine davon getestet ist. **Getestet** heißt: ein erfolgreicher Lauf von „Update-Test“
auf `main` mit dieser Beta als Ziel im Kanal Beta – erkannt am Laufnamen
`Update-Test <von> → X.Y.Z-beta.N (beta)`, nur lesend über die Actions-API. Läufe ohne diesen
Laufnamen (vor seiner Einführung) zählen nicht; dann den Update-Test der Beta erneut starten. Einzige
Ausnahme: ein Lauf mit `hotfix_ohne_beta: true` für eine Patch-Version (Z > 0) – eine neue
Funktionsversion (`X.Y.0`) kann nie ohne Beta Stable werden.

## Build once – Test – Release genau dieses Setup

Veröffentlicht wird immer genau das Setup, das vorher gebaut, installiert, aktualisiert, gestartet
und getestet wurde – kein zweiter Build nur für das Release.

| Workflow | Wann | Was |
| --- | --- | --- |
| **Windows-Setup** (`windows-setup.yml`) | jeder Pull Request; jeder Push auf `main`; manuell | vollständige Prüfung: alle Tests (Kern, Qt/QML, PDF Editor, PDF reparieren, Migration, Updater), Setup bauen, Release-Dateien prüfen, Clean-Install-, Upgrade-, Runtime-, QML- und Updater-E2E-Test |
| | nur auf `main`, nur wenn alle Jobs bestanden sind | **Release Candidate** speichern: Artifact `PDF-Tool-Release-Candidate-<Commit-SHA>` (Setup, `.sha256`, Manifest `release-candidate.json`), 90 Tage aufbewahrt |
| **Release** (`release.yml`) | nur manuell auf `main` | veröffentlicht den Release Candidate eines erfolgreichen main-Laufs – baut nichts, testet nicht erneut |
| **Update-Test** (`update-test.yml`) | nur manuell, nach dem Veröffentlichen | Update aus Sicht der Anwender über den Updater der Vorversion – genau ein Weg aktuell → neu; ein erfolgreicher Lauf auf eine Beta ist Voraussetzung für Stable |
| **Release-Prüfung** (`release-guard.yml`) | Release von Hand erstellt oder geändert | prüft die Regeln; bei einem Verstoß wird das Release wieder zum Entwurf |

**Commit ↔ Artifact:** Der Name des Artifacts enthält den vollständigen Commit-SHA; das Manifest nennt
Commit, Lauf, Version, Setup und SHA-256 des Setups (`windows-app/release_candidate.py write`).
GitHub ordnet jedes Artifact zusätzlich seinem Lauf zu (Lauf, Commit, Zweig).

**Was der Workflow „Release“ prüft** (`windows-app/release_candidate.py`):

1. Release-Commit bestimmen: Standard ist der aktuelle Stand von `main`; optional ein vollständiger
   Commit-SHA (`commit`). Der Workflow läuft nur auf `main`.
2. Der Commit liegt auf `main`.
3. Für **genau diesen Commit** gibt es einen abgeschlossenen, erfolgreichen main-Lauf von
   „Windows-Setup“ (Push oder manueller Lauf). Ein erfolgreicher Lauf eines anderen Commits zählt nie
   (CI für `abc123`, Release-Commit `abc124` → abgelehnt).
4. Dessen Artifact `PDF-Tool-Release-Candidate-<Commit-SHA>` – nicht abgelaufen, von genau diesem
   Lauf, Commit und Zweig – wird geladen.
5. Manifest: Commit und Lauf stimmen; Version = `windows-app/VERSION` des Commits; Dateinamen exakt;
   keine fremden Dateien; SHA-256 des Setups neu berechnet = Prüfsummendatei = Manifest;
   Dateiversion im Setup; Release Notes des Commits vorhanden. Jede Abweichung bricht ab.
6. Beta vor Stable: veröffentlichte und per „Update-Test“ geprüfte Beta (Hotfix-Regel wie oben).
7. Release und Tag `v<Version>` existieren noch nicht – nie überschreiben, nie verschieben.
8. Release mit genau diesen beiden Dateien erstellen (Beta → Vorabversion, nie „Latest“;
   Stable → „Latest“), Tag auf den geprüften Commit. Danach: Tag → Commit, Vorabversion ja/nein,
   genau die beiden Dateien, SHA-256 des veröffentlichten Setups = Release Candidate.

**Fehlt der Release Candidate** (abgelaufen, oder ein Commit auf `main` hatte wegen der Pfadfilter
keinen Lauf), baut „Release“ nichts nach: „Windows-Setup“ auf `main` manuell starten – das prüft den
Stand vollständig neu und speichert einen neuen Release Candidate – oder einen neuen Commit verwenden.

Es gibt nur diesen einen Veröffentlichungsweg. Ein Tag-Push löst keinen Workflow aus; die App bietet
Releases ohne Setup und Prüfsummendatei nie an.

**Releases von Hand** (auf GitHub angelegt oder geändert) prüft der Workflow „Release-Prüfung“
(`release-guard.yml`, bei `published`, `edited`, `prereleased` und `released`), denn die App bietet
jedes veröffentlichte Release mit passenden Dateien an:

- Tag `vX.Y.Z` oder `vX.Y.Z-beta.N`; ein Beta-Tag ist eine Vorabversion
- Stable nur mit veröffentlichter und per „Update-Test“ geprüfter Beta derselben Version – ohne
  Hotfix-Ausnahme
- genau die Dateien `PDF-Tool-Setup-<Version>.exe` und `PDF-Tool-Setup-<Version>.exe.sha256`

Bei einem Verstoß setzt der Workflow das Release mit `gh release edit <Tag> --draft=true` auf Entwurf
zurück (Entwürfe sieht kein Kanal) und schlägt mit der Begründung fehl – ebenso, wenn die Prüfung
nicht durchläuft. Rechte: `contents: write` und `actions: read`, sonst keine. Releases von „Release“
lösen die Prüfung nach GitHub-Regel nicht aus (`GITHUB_TOKEN`) und sind bereits geprüft; werden sie
später von Hand geändert, gelten Tag, Vorabversion und Dateien weiter, Beta vor Stable samt
Hotfix-Regel hat „Release“ beim Erstellen geprüft (solange Release und Dateien von
`github-actions[bot]` stammen). GitHub startet die Prüfung in der Fassung des Commits, auf den der Tag
zeigt – Releases auf Commits vor ihrer Einführung prüft sie nicht.

## Ablauf

Beispiel 2.8.0:

```
v2.8.0-beta.1  →  testen  →  Fehler gefunden  →  v2.8.0-beta.2  →  testen  →  v2.8.0-beta.3  →  freigeben  →  v2.8.0
```

1. **Beta veröffentlichen:** `windows-app/VERSION` auf `2.8.0-beta.1` setzen, Release Notes
   `windows-app/release-notes/2.8.0-beta.1.md` anlegen, per Pull Request auf `main` bringen. Der
   main-Lauf von „Windows-Setup“ prüft den Merge-Commit vollständig und speichert seinen Release
   Candidate. Danach den Workflow „Release“ auf `main` starten: Er veröffentlicht genau dieses Setup
   als **GitHub-Vorabversion** mit Prüfsumme. Anschließend den Workflow „Update-Test“
   starten (`ziel: 2.8.0-beta.1`, `kanal: beta`, `von` leer): Er bestimmt die unmittelbar vorherige
   veröffentlichte Version (hier 2.7.2; für `3.1.0-beta.1` wäre es `3.0.0-beta.2`), aktualisiert sie
   über ihren eigenen Updater im Kanal „Beta“ und prüft das Ergebnis. Dieser Lauf macht die Beta zur
   getesteten Beta – Voraussetzung für Stable.
2. **Weitere Betas** genauso mit `2.8.0-beta.2`, `2.8.0-beta.3` …
3. **Stable veröffentlichen:** bewusst und erst nach Test und Freigabe – `windows-app/VERSION` auf
   `2.8.0`, Release Notes `2.8.0.md`, Pull Request. Weil sich die Version ändert, ist Stable ein
   eigener Build: Der main-Lauf prüft den neuen Commit vollständig (Tests, Setup, Installer-Tests)
   und speichert seinen Release Candidate – nie ein umbenanntes Beta-Setup. Dann den Workflow
   „Release“ auf `main` starten; er prüft zusätzlich, dass eine Beta von `2.8.0` veröffentlicht und
   per „Update-Test“ geprüft ist. Es entsteht ein **normales Release**, das „Latest“ wird.
   Anschließend den Workflow „Update-Test“ für beide Wege starten, `von` jeweils leer:
   `ziel: 2.8.0`, `kanal: stable` (von der letzten stabilen Version, hier 2.7.2 – Anwender der
   stabilen Version) und `ziel: 2.8.0`, `kanal: beta` (von der letzten Beta der Version, z. B.
   `2.8.0-beta.3` – Beta-Tester).

Eine Beta wird nie automatisch zu Stable: Der Kanal eines Releases folgt allein aus der Version in
`windows-app/VERSION`, die ein Mensch per Pull Request ändert.

Hinweis: Die Downloadseite (`src/components/landing-page.tsx`) zeigt die Version aus
`windows-app/VERSION` – während einer Beta-Phase auf `main` also die Beta.

## Prüfungen vor der Veröffentlichung

`windows-app/release_check.py` läuft im Build, beim Speichern des Release Candidates und noch einmal
im Workflow „Release“ (über `release_candidate.py verify`):

- Version gültig (`X.Y.Z` oder `X.Y.Z-beta.N`), Tag `vX.Y.Z…` passt zu `windows-app/VERSION` des
  Release-Commits, der auf `main` liegt
- Setup und Prüfsummendatei vorhanden, Namen exakt nach der Konvention, keine fremden Dateien
- die Prüfsumme gehört exakt zum Setup, die Dateiversion im Setup stimmt
- Release Notes vorhanden

Nach der Veröffentlichung prüft der Workflow das Release: Tag → Commit, Vorabversion ja/nein,
genau die beiden Dateien, SHA-256 des veröffentlichten Setups = Release Candidate.

Veröffentlichte Releases sind unveränderlich: Gibt es das Release einer Version oder ihren Tag schon,
bricht der Workflow ab; Tags werden nie verschoben, Dateien eines Releases nie überschrieben. Eine
Korrektur erscheint als neue Version (z. B. `2.8.0-beta.2` oder `2.8.1`).

## Was die Kanäle sehen

- **Stable:** nur Releases ohne Vorabkennung, auf GitHub nicht als Vorabversion markiert, keine
  Entwürfe, neuer als die installierte Version.
- **Beta:** zusätzlich Beta-Vorabversionen. Ein Beta-Nutzer erhält auch die stabile Version, sobald sie
  neuer ist (`2.8.0-beta.3` → `2.8.0`), und bleibt danach im Beta-Kanal (`2.8.1-beta.1` …).
- **Kein Downgrade:** Wer von Beta auf Stable wechselt, bleibt auf seiner Beta, bis eine neuere stabile
  Version erscheint.
