"""Vorlagen 2.0 für Vertragsübersichten.

* ``models``     – Datenmodell (Metadaten, Darstellung, Kopf-/Fußzeile, Regel-Verweis) mit
  Schema-Version und stabiler ID; ``to_entry`` liefert das bisherige Wörterbuch einer Vorlage
* ``repository`` – je Vorlage eine atomar geschriebene JSON-Datei (``vorlagen\\<id>.json``)
* ``migration``  – einmalige Übernahme der Vorlagen bis 2.7 aus ``gui-config.json``
* ``priority``   – welche Vorlage gilt (Einzelmodus, Kundenakte, Stapel, Standardvorlage)
"""
