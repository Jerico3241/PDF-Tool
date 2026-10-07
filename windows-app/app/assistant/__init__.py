"""KI-Assistent (optional, ab 3.2): Fragen zum geöffneten PDF beantworten und Dokumente zusammenfassen – vollständig
lokal auf diesem PC.

* ``catalog``: die angebotenen Sprachmodelle (feste Quelle, feste Revision, SHA-256, Lizenz).
* ``store``: Modelle auf diesem PC (``%LOCALAPPDATA%\\PDF-Tool-KI``) – nicht in Sicherungen oder Support-Paketen,
  jederzeit löschbar.
* ``text``: Abschnitte mit Seitenangabe, Suche passender Stellen, Seitenangaben in Antworten.
* ``prompts``: Anweisungen an das Modell (Antworten nur aus dem Dokument, mit Seitenangabe).
* ``runtime``: llama.cpp (``llama-server``) als eigener Prozess – nur ``127.0.0.1``, zufälliger Port und Schlüssel,
  endet mit der App.
* ``client``: Anfragen an diesen Prozess, Antworten Stück für Stück, abbrechbar.

Standardmäßig ist der Assistent aus. Ein Modell wird nur auf ausdrücklichen Wunsch geladen. Dokumenttexte, Fragen und
Antworten werden nie protokolliert und verlassen den PC nicht.
"""
