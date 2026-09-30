"""Qt-Anwendungsschicht von PDF Tool: Controller, Modelle und Dienste zwischen Python-Kern und QML.

Aufbau (siehe README, Abschnitt »Architektur«):

* Python-Kern – ``engine``, ``richtext``, ``tools/contract_overview/{overview,batch,customers,history}``,
  ``tools/pdf_repair`` … – kennt weder Qt noch QML.
* Diese Schicht – je Fachbereich ein Controller (``QObject`` mit Properties, Signalen und Slots),
  Listenmodelle (``QAbstractListModel``) und gemeinsame Dienste (Worker, Hinweise, Dialoge, Dateien).
* QML (``app/qml``) – die Oberfläche. Sie entscheidet über Darstellung und Animation und ruft nur Slots.
"""
