import { Download } from "lucide-react";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import versionFile from "../../windows-app/VERSION?raw";

// Die Version steht – wie für App und Setup – nur in windows-app/VERSION.
const VERSION = versionFile.trim();
const SETUP_FILE = `PDF-Tool-Setup-${VERSION}.exe`;
const SETUP_HREF = `/downloads/${SETUP_FILE}`;

const STEPS = [
  {
    n: "1",
    title: "Setup doppelklicken",
    body: `Die Datei ${SETUP_FILE} öffnen. Administratorrechte sind nicht nötig.`,
  },
  {
    n: "2",
    title: "Einrichtung bestätigen",
    body: "Falls SmartScreen erscheint: Weitere Informationen, dann Trotzdem ausführen. Danach dem Setup-Assistenten folgen. Ein Update vom Übersichten-Ersteller übernimmt alle Einstellungen.",
  },
  {
    n: "3",
    title: "Werkzeug wählen",
    body: "Auf der Startseite »Vertragsübersichten« oder »PDF reparieren« öffnen – oder eine Datei einfach in das Fenster ziehen.",
  },
];

const TOOLS = [
  {
    title: "Vertragsübersichten",
    body: "Erstellt professionelle Vertragsübersichten aus Excel-Dateien – einzeln oder als Stapel aus vielen Excel-Listen in einem Durchlauf, mit Vorlagen, Kopf- und Fußzeile, Textbausteinen, Live-Vorschau, optionalen Kundenakten, die bekannte Kunden an der Rechnungsempfänger-E-Mail wiedererkennen, und einem Vergleich mit dem letzten Vertragsstand des Kunden.",
  },
  {
    title: "PDF reparieren",
    body: "Analysiert beschädigte PDF-Dateien und versucht, lesbare Inhalte in eine neue PDF zu übertragen – bei Bedarf wird die Dokumentstruktur aus den noch vorhandenen Objekten neu aufgebaut. Die Originaldatei wird nie verändert.",
  },
];

// Regeln des Werkzeugs »Vertragsübersichten«
const RULES = [
  "Nur Netto, keine Brutto-Spalte, keine Summenzeile, kein Status",
  "„x “ und „SW-Pflege“ am Anfang der Beschreibung werden entfernt",
  "Hotline = Supportvertrag, alle anderen = Softwarepflegevertrag",
  "Lastschr wird als Lastschrift ausgegeben",
  "Kundennummer und Firmenname stammen aus Ihrer Eingabe, der Excel oder Ihrer (optionalen) Kundenakte – nie geraten",
];

export function LandingPage() {
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <SiteHeader />
      <main>
        <section className="mx-auto grid w-full max-w-6xl gap-10 px-4 py-12 sm:px-6 lg:grid-cols-[1.15fr_0.85fr] lg:py-16">
          <div className="flex flex-col justify-center">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-primary">
              Für Windows 10 und 11
            </p>
            <h1 className="mt-3 max-w-xl font-display text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
              PDF Tool {VERSION}
            </h1>
            <p className="mt-4 max-w-xl text-base leading-7 text-muted-foreground text-pretty">
              Werkzeuge für PDF-Dateien: Vertragsübersichten erstellen und beschädigte PDFs reparieren. Alles wird lokal auf
              Ihrem PC verarbeitet. Entwickler und Inhaber: Jerico.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg">
                <a href={SETUP_HREF} download>
                  <Download />
                  Windows-App herunterladen
                </a>
              </Button>
            </div>
            <p className="mt-4 text-sm text-muted-foreground">
              Setup.exe · 64-Bit · ohne Admin-Rechte · Version {VERSION}
            </p>
          </div>

          <div className="overflow-hidden rounded-xl bg-canvas shadow-[var(--shadow-window)]">
            <div className="flex h-9 items-center justify-between border-b border-border bg-card px-3">
              <p className="text-xs text-muted-foreground">PDF Tool {VERSION}</p>
              <div className="flex gap-1.5 text-muted-foreground">
                <span className="size-2.5 rounded-sm bg-muted" />
                <span className="size-2.5 rounded-sm bg-muted" />
                <span className="size-2.5 rounded-sm bg-muted" />
              </div>
            </div>
            <div className="flex">
              <nav className="flex w-36 shrink-0 flex-col gap-1 bg-muted/50 p-2 text-xs">
                <span className="rounded-md border-l-2 border-primary bg-card px-2 py-1">Start</span>
                <span className="px-2 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Tools
                </span>
                <span className="px-2 py-1 text-muted-foreground">Vertragsübersichten</span>
                <span className="px-2 py-1 text-muted-foreground">PDF reparieren</span>
                <span className="mt-6 px-2 py-1 text-muted-foreground">Einstellungen</span>
              </nav>
              <div className="flex-1 space-y-3 bg-muted/30 p-4">
                <p className="text-sm font-semibold">PDF Tool</p>
                {TOOLS.map((tool) => (
                  <div key={tool.title} className="rounded-lg border border-border bg-card p-3">
                    <p className="text-xs font-semibold">{tool.title}</p>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">{tool.body}</p>
                    <span className="mt-2 inline-flex h-7 items-center rounded-md bg-primary px-3 text-xs text-primary-foreground">
                      Öffnen
                    </span>
                  </div>
                ))}
              </div>
            </div>
            <div className="flex items-center justify-between border-t border-border bg-card px-3 py-1.5">
              <p className="text-xs text-muted-foreground">Bereit</p>
              <p className="text-xs text-muted-foreground">Version {VERSION}</p>
            </div>
          </div>
        </section>

        <section className="border-y border-border bg-card">
          <div className="mx-auto grid w-full max-w-6xl gap-4 px-4 py-10 sm:px-6 md:grid-cols-3">
            {STEPS.map((step) => (
              <article key={step.n} className="rounded-xl bg-background p-5">
                <p className="font-display text-2xl font-semibold text-primary">{step.n}</p>
                <h2 className="mt-2 text-base font-semibold">{step.title}</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground text-pretty">{step.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="mx-auto grid w-full max-w-6xl gap-4 px-4 pt-12 sm:px-6 md:grid-cols-2">
          {TOOLS.map((tool) => (
            <article key={tool.title} className="rounded-xl border border-border bg-card p-5">
              <h2 className="font-display text-xl font-semibold">{tool.title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground text-pretty">{tool.body}</p>
            </article>
          ))}
        </section>

        <section className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-6">
          <h2 className="font-display text-2xl font-semibold">Regeln der Vertragsübersicht</h2>
          <ul className="mt-4 space-y-2 text-sm leading-6 text-muted-foreground">
            {RULES.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}
