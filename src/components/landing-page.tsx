import { Download } from "lucide-react";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";

const SETUP_HREF = "/downloads/Uebersichten-Ersteller-Setup-2.1.0.exe";

const STEPS = [
  {
    n: "1",
    title: "Setup doppelklicken",
    body: "Die Datei Uebersichten-Ersteller-Setup-2.1.0.exe öffnen. Administratorrechte sind nicht nötig.",
  },
  {
    n: "2",
    title: "Einrichtung bestätigen",
    body: "Falls SmartScreen erscheint: Weitere Informationen, dann Trotzdem ausführen. Danach dem Setup-Assistenten folgen. Ein Update behält alle Einstellungen.",
  },
  {
    n: "3",
    title: "PDF erzeugen",
    body: "Firmenname und Kundennummer eintragen, Excel wählen, PDF erstellen.",
  },
];

const RULES = [
  "Nur Netto, keine Brutto-Spalte, keine Summenzeile, kein Status",
  "„x “ und „SW-Pflege“ am Anfang der Beschreibung werden entfernt",
  "Hotline = Supportvertrag, alle anderen = Softwarepflegevertrag",
  "Lastschr wird als Lastschrift ausgegeben",
  "Kundennummer und Firmenname tragen Sie selbst ein",
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
              Übersichten-Ersteller 2.1.0
            </h1>
            <p className="mt-4 max-w-xl text-base leading-7 text-muted-foreground text-pretty">
              Die einfache Windows-Oberfläche. Entwickler und Inhaber: Jerico.
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
              Setup.exe · 64-Bit · ohne Admin-Rechte · Version 2.1.0
            </p>
          </div>

          <div className="overflow-hidden rounded-xl bg-canvas shadow-[var(--shadow-window)]">
            <div className="flex h-9 items-center justify-between border-b border-border bg-card px-3">
              <p className="text-xs text-muted-foreground">Übersichten-Ersteller 2.1.0</p>
              <div className="flex gap-1.5 text-muted-foreground">
                <span className="size-2.5 rounded-sm bg-muted" />
                <span className="size-2.5 rounded-sm bg-muted" />
                <span className="size-2.5 rounded-sm bg-muted" />
              </div>
            </div>
            <div className="flex">
              <nav className="flex w-28 shrink-0 flex-col gap-1 bg-muted/50 p-2 text-xs">
                <span className="rounded-md border-l-2 border-primary bg-card px-2 py-1">Erstellen</span>
                <span className="px-2 py-1 text-muted-foreground">Darstellung</span>
                <span className="px-2 py-1 text-muted-foreground">Einstellungen</span>
              </nav>
              <div className="flex-1 space-y-3 bg-muted/30 p-4">
                <div className="rounded-lg border border-border bg-card p-3">
                  <p className="text-xs font-semibold">Kundendaten</p>
                  <MockField label="Firmenname" value="" />
                  <MockField label="Kundennummer" value="" />
                </div>
                <div className="rounded-lg border border-border bg-card p-3">
                  <p className="text-xs font-semibold">Dateien und Pfade</p>
                  <MockField label="Excel-Datei" value="Keine Datei gewählt" />
                  <MockField label="Logo" value="hott_logo_final.png" />
                </div>
                <div className="flex items-center gap-3">
                  <span className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs text-primary-foreground">
                    PDF erstellen
                  </span>
                  <span className="text-xs text-muted-foreground">PDF nach dem Erstellen öffnen</span>
                </div>
              </div>
            </div>
            <div className="flex items-center justify-between border-t border-border bg-card px-3 py-1.5">
              <p className="text-xs text-muted-foreground">Bereit</p>
              <p className="text-xs text-muted-foreground">Version 2.1.0</p>
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

        <section className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-6">
          <h2 className="font-display text-2xl font-semibold">Regeln der PDF</h2>
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

function MockField({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 rounded-sm border border-border bg-background px-2 py-1 text-xs">
        {value || "\u00a0"}
      </p>
    </div>
  );
}
