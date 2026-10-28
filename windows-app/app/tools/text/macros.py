"""Hilfsmakros des Textkerns (seit 5.0 Beta 5): eine Basic-Bibliothek »Novadesk« im Profil des Kerns.

LibreOfficeKit zeigt keine Dialoge von LibreOffice. Was sich mit einem einfachen Befehl (».uno:InsertFootnote«) nicht
erledigen lässt – Inhaltsverzeichnis, Querverweise, Formeln, Diagramme, zwei Fassungen vergleichen –, erledigen diese
Makros über die Programmierschnittstelle von LibreOffice am gerade bearbeiteten Dokument (``ThisComponent``). Der Kern
ruft sie mit ``runMacro`` auf (``cmd_macro``): Die Werte stehen in einer Datei (getrennt durch das Zeichen 30), die
Antwort schreibt das Makro in eine zweite; Datensätze darin trennt das Zeichen 31. Die erste Antwort ist »ok« oder ein
Fehler mit »!« davor. Makros der Anwendung (»Meine Makros«) laufen ohne Sicherheitsabfrage; die Bibliothek ist
schreibgeschützt und wird bei jedem Start des Kerns neu geschrieben (neue Fassung von Novadesk).
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

LIBRARY = "Novadesk"
MODULE = "Text"
I18N_CALLS = ()  # keine Oberflächentexte (Basic-Quelltext; Meldungen daraus zeigt der Text nur in Klammern)
CLSID_MATH = "078B7ABA-54FC-457F-8551-6147e776a997"
CLSID_CHART = "12dcae26-281f-416f-a234-c3086127382e"

BASIC = r'''
Option Explicit

Const TRENNER = 30
Const FELD = 31

Function Lesen(sUrl As String) As Variant
    Dim oSfa As Object, oStream As Object, oText As Object, sAlles As String
    oSfa = createUnoService("com.sun.star.ucb.SimpleFileAccess")
    oStream = oSfa.openFileRead(sUrl)
    oText = createUnoService("com.sun.star.io.TextInputStream")
    oText.setInputStream(oStream)
    oText.setEncoding("UTF-8")
    sAlles = ""
    If Not oText.isEOF() Then sAlles = oText.readString(Array(), False)
    oText.closeInput()
    Lesen = Split(sAlles, Chr(TRENNER))
End Function

Sub Schreiben(sUrl As String, aWerte As Variant)
    Dim oSfa As Object, oStream As Object, oText As Object
    oSfa = createUnoService("com.sun.star.ucb.SimpleFileAccess")
    If oSfa.exists(sUrl) Then oSfa.kill(sUrl)
    oStream = oSfa.openFileWrite(sUrl)
    oText = createUnoService("com.sun.star.io.TextOutputStream")
    oText.setOutputStream(oStream)
    oText.setEncoding("UTF-8")
    oText.writeString(Join(aWerte, Chr(TRENNER)))
    oText.closeOutput()
End Sub

Sub Melden(sAus As String, sText As String)
    Schreiben(sAus, Array("!" & sText))
End Sub

Function Wert(aWerte As Variant, n As Integer) As String
    If n <= UBound(aWerte) Then Wert = aWerte(n) Else Wert = ""
End Function

Function Zahl(s As String) As Double
    Zahl = Val(Replace(s, ",", "."))
End Function

Function AlsText(d As Double) As String
    AlsText = Trim(Str(d))
End Function

Function Schreibmarke() As Object
    Schreibmarke = ThisComponent.CurrentController.ViewCursor
End Function

Function Kurz(s As String) As String
    s = Trim(Replace(Replace(s, Chr(10), " "), Chr(13), " "))
    If Len(s) > 80 Then s = Left(s, 79) & "…"
    Kurz = s
End Function

' Inhaltsverzeichnis an der Schreibmarke: Titel, Ebenen (1 … 10)
Sub Verzeichnis(sEin As String, sAus As String)
    Dim aWerte As Variant, oDoc As Object, oIndex As Object, oMarke As Object, nEbenen As Integer
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    oDoc = ThisComponent
    oMarke = Schreibmarke()
    nEbenen = CInt(Zahl(Wert(aWerte, 1)))
    If nEbenen < 1 Or nEbenen > 10 Then nEbenen = 3
    oDoc.UndoManager.enterUndoContext("Inhaltsverzeichnis")
    oIndex = oDoc.createInstance("com.sun.star.text.ContentIndex")
    oIndex.Title = Wert(aWerte, 0)
    oIndex.CreateFromOutline = True
    oIndex.Level = nEbenen
    oMarke.Text.insertTextContent(oMarke, oIndex, False)
    oIndex.update()
    oDoc.UndoManager.leaveUndoContext()
    Schreiben(sAus, Array("ok"))
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub

' Alle Verzeichnisse neu aufbauen (Seitenzahlen, neue Überschriften)
Sub VerzeichnisseAktualisieren(sEin As String, sAus As String)
    Dim oIndexes As Object, i As Integer
    On Error GoTo Fehler
    oIndexes = ThisComponent.DocumentIndexes
    For i = 0 To oIndexes.Count - 1
        oIndexes.getByIndex(i).update()
    Next i
    ThisComponent.TextFields.refresh()
    Schreiben(sAus, Array("ok", CStr(oIndexes.Count)))
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub

' Ziele für Querverweise: Überschriften (Art, Nummer des Absatzes, Ebene, Nummerierung, Text), Textmarken,
' Fuß- und Endnoten
Sub Ziele(sEin As String, sAus As String)
    Dim oDoc As Object, oEnum As Object, oPar As Object, aAus() As String, n As Long, i As Long, s As String
    Dim oNamen As Variant, oNote As Object
    On Error GoTo Fehler
    oDoc = ThisComponent
    ReDim aAus(0)
    aAus(0) = "ok"
    n = 0
    i = 0
    oEnum = oDoc.Text.createEnumeration()
    Do While oEnum.hasMoreElements()
        oPar = oEnum.nextElement()
        If oPar.supportsService("com.sun.star.text.Paragraph") Then
            i = i + 1
            If oPar.OutlineLevel > 0 And Trim(oPar.String) <> "" Then
                n = n + 1
                ReDim Preserve aAus(n)
                s = ""
                On Error Resume Next
                s = oPar.ListLabelString
                On Error GoTo Fehler
                aAus(n) = Join(Array("heading", CStr(i), CStr(oPar.OutlineLevel), s, Kurz(oPar.String)), Chr(FELD))
            End If
        End If
    Loop
    oNamen = oDoc.Bookmarks.ElementNames
    For i = 0 To UBound(oNamen)
        If Left(oNamen(i), 1) <> "_" Then
            n = n + 1
            ReDim Preserve aAus(n)
            aAus(n) = Join(Array("bookmark", oNamen(i), "0", "", Kurz(oDoc.Bookmarks.getByName(oNamen(i)).Anchor.String)), Chr(FELD))
        End If
    Next i
    For i = 0 To oDoc.Footnotes.Count - 1
        oNote = oDoc.Footnotes.getByIndex(i)
        n = n + 1
        ReDim Preserve aAus(n)
        aAus(n) = Join(Array("footnote", CStr(oNote.ReferenceId), "0", oNote.Anchor.String, Kurz(oNote.String)), Chr(FELD))
    Next i
    For i = 0 To oDoc.Endnotes.Count - 1
        oNote = oDoc.Endnotes.getByIndex(i)
        n = n + 1
        ReDim Preserve aAus(n)
        aAus(n) = Join(Array("endnote", CStr(oNote.ReferenceId), "0", oNote.Anchor.String, Kurz(oNote.String)), Chr(FELD))
    Next i
    Schreiben(sAus, aAus())
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub

' Textmarke um den ganzen Absatz Nummer nAbsatz (wie in Ziele gezählt) – vorhandene von Novadesk wiederverwenden
Function MarkeUmAbsatz(oDoc As Object, nAbsatz As Long) As String
    Dim oEnum As Object, oPar As Object, i As Long, oNamen As Variant, j As Long, oMarke As Object, oCursor As Object
    Dim sName As String
    MarkeUmAbsatz = ""
    oEnum = oDoc.Text.createEnumeration()
    i = 0
    Do While oEnum.hasMoreElements()
        oPar = oEnum.nextElement()
        If oPar.supportsService("com.sun.star.text.Paragraph") Then
            i = i + 1
            If i = nAbsatz Then
                oNamen = oDoc.Bookmarks.ElementNames
                For j = 0 To UBound(oNamen)
                    If Left(oNamen(j), 4) = "_Ref" Then
                        oMarke = oDoc.Bookmarks.getByName(oNamen(j)).Anchor
                        If oMarke.Text Is oDoc.Text Then
                            If oDoc.Text.compareRegionStarts(oMarke, oPar) = 0 Then
                                MarkeUmAbsatz = oNamen(j)
                                Exit Function
                            End If
                        End If
                    End If
                Next j
                Randomize
                Do
                    sName = "_Ref" & CStr(100000000 + Int(Rnd() * 899999999))
                Loop While oDoc.Bookmarks.hasByName(sName)
                oCursor = oDoc.Text.createTextCursorByRange(oPar.Start)
                oCursor.gotoEndOfParagraph(True)
                oMarke = oDoc.createInstance("com.sun.star.text.Bookmark")
                oMarke.Name = sName
                oDoc.Text.insertTextContent(oCursor, oMarke, True)
                MarkeUmAbsatz = sName
                Exit Function
            End If
        End If
    Loop
End Function

' Querverweis an der Schreibmarke: Art des Ziels, Ziel (wie aus Ziele), Teil (page, text, number, updown)
Sub Querverweis(sEin As String, sAus As String)
    Dim aWerte As Variant, oDoc As Object, oFeld As Object, oMarke As Object, sArt As String, sTeil As String
    Dim nTeil As Integer, sName As String
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    oDoc = ThisComponent
    sArt = Wert(aWerte, 0)
    sTeil = Wert(aWerte, 2)
    oDoc.UndoManager.enterUndoContext("Querverweis")
    oFeld = oDoc.createInstance("com.sun.star.text.TextField.GetReference")
    Select Case sArt
        Case "heading", "bookmark"
            If sArt = "heading" Then sName = MarkeUmAbsatz(oDoc, CLng(Zahl(Wert(aWerte, 1)))) Else sName = Wert(aWerte, 1)
            If sName = "" Or Not oDoc.Bookmarks.hasByName(sName) Then
                oDoc.UndoManager.leaveUndoContext()
                Melden(sAus, "Das Ziel gibt es nicht mehr.")
                Exit Sub
            End If
            oFeld.ReferenceFieldSource = 2
            oFeld.SourceName = sName
            Select Case sTeil
                Case "page": nTeil = 0
                Case "number": nTeil = 8
                Case "updown": nTeil = 3
                Case Else: nTeil = 2
            End Select
        Case "footnote", "endnote"
            If sArt = "footnote" Then oFeld.ReferenceFieldSource = 3 Else oFeld.ReferenceFieldSource = 4
            oFeld.SequenceNumber = CInt(Zahl(Wert(aWerte, 1)))
            Select Case sTeil
                Case "page": nTeil = 0
                Case "updown": nTeil = 3
                Case Else: nTeil = 2
            End Select
        Case Else
            oDoc.UndoManager.leaveUndoContext()
            Melden(sAus, "Unbekanntes Ziel.")
            Exit Sub
    End Select
    oFeld.ReferenceFieldPart = nTeil
    oMarke = Schreibmarke()
    oMarke.Text.insertTextContent(oMarke, oFeld, False)
    oDoc.TextFields.refresh()
    oDoc.UndoManager.leaveUndoContext()
    Schreiben(sAus, Array("ok"))
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub

' Ausgewähltes eingebettetes Objekt (Formel bzw. Diagramm) oder nichts
Function Ausgewaehlt(sClsid As String) As Object
    Dim oSel As Object
    Ausgewaehlt = Nothing
    oSel = ThisComponent.CurrentSelection
    If IsNull(oSel) Then Exit Function
    If Not oSel.supportsService("com.sun.star.text.TextEmbeddedObject") Then Exit Function
    If LCase(oSel.CLSID) = LCase(sClsid) Then Ausgewaehlt = oSel
End Function

' Inhalt (Modell) eines eingebetteten Objekts – vorher starten, sonst ist es nur ein Platzhalter
Function Modell(oObj As Object) As Object
    Dim oEingebettet As Object
    oEingebettet = oObj.ExtendedControlOverEmbeddedObject
    If oEingebettet.CurrentState = com.sun.star.embed.EmbedStates.LOADED Then oEingebettet.changeState(com.sun.star.embed.EmbedStates.RUNNING)
    Modell = oEingebettet.Component
End Function

Function NeuesObjekt(sClsid As String) As Object
    Dim oObj As Object, oMarke As Object
    oObj = ThisComponent.createInstance("com.sun.star.text.TextEmbeddedObject")
    oObj.CLSID = sClsid
    oObj.AnchorType = com.sun.star.text.TextContentAnchorType.AS_CHARACTER
    oMarke = Schreibmarke()
    oMarke.Text.insertTextContent(oMarke, oObj, False)
    NeuesObjekt = oObj
End Function

' Formel: ausgewählte lesen bzw. einfügen oder ändern (Schreibweise von LibreOffice Math)
Sub FormelLesen(sEin As String, sAus As String)
    Dim oObj As Object
    On Error GoTo Fehler
    oObj = Ausgewaehlt("''' + CLSID_MATH + r'''")
    If IsNull(oObj) Then
        Schreiben(sAus, Array("ok"))
    Else
        Schreiben(sAus, Array("ok", Modell(oObj).Formula))
    End If
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub

Sub Formel(sEin As String, sAus As String)
    Dim aWerte As Variant, oObj As Object, oDoc As Object
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    oDoc = ThisComponent
    oDoc.UndoManager.enterUndoContext("Formel")
    oObj = Nothing
    If Wert(aWerte, 1) = "replace" Then oObj = Ausgewaehlt("''' + CLSID_MATH + r'''")
    If IsNull(oObj) Then oObj = NeuesObjekt("''' + CLSID_MATH + r'''")
    Modell(oObj).Formula = Wert(aWerte, 0)
    oDoc.UndoManager.leaveUndoContext()
    Schreiben(sAus, Array("ok"))
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub

' Diagramm: ausgewähltes lesen (Art, Titel, Kopfzeile, Zeilen) bzw. einfügen oder ändern. Zeilen: Beschriftung und
' Werte, getrennt durch das Zeichen 31; die Kopfzeile nennt die Reihen.
Sub DiagrammLesen(sEin As String, sAus As String)
    Dim oObj As Object, oChart As Object, oDaten As Object, aAus() As String, aZeilen As Variant, aSpalten As Variant
    Dim aBeschriftungen As Variant, sArt As String, i As Integer, j As Integer, aZeile() As String, sTitel As String
    On Error GoTo Fehler
    oObj = Ausgewaehlt("''' + CLSID_CHART + r'''")
    If IsNull(oObj) Then
        Schreiben(sAus, Array("ok"))
        Exit Sub
    End If
    oChart = Modell(oObj)
    Select Case oChart.Diagram.DiagramType
        Case "com.sun.star.chart.LineDiagram": sArt = "line"
        Case "com.sun.star.chart.PieDiagram": sArt = "pie"
        Case "com.sun.star.chart.BarDiagram"
            If oChart.Diagram.Vertical Then sArt = "bar" Else sArt = "column"
        Case Else: sArt = "column"
    End Select
    sTitel = ""
    If oChart.HasMainTitle Then sTitel = oChart.Title.String
    oDaten = oChart.Data
    aZeilen = oDaten.getData()
    aSpalten = oDaten.getColumnDescriptions()
    aBeschriftungen = oDaten.getRowDescriptions()
    ReDim aAus(4 + UBound(aZeilen))
    aAus(0) = "ok"
    aAus(1) = sArt
    aAus(2) = sTitel
    aAus(3) = Chr(FELD) & Join(aSpalten, Chr(FELD))
    For i = 0 To UBound(aZeilen)
        ReDim aZeile(UBound(aZeilen(i)) + 1)
        If i <= UBound(aBeschriftungen) Then aZeile(0) = aBeschriftungen(i)
        For j = 0 To UBound(aZeilen(i))
            aZeile(j + 1) = AlsText(aZeilen(i)(j))
        Next j
        aAus(4 + i) = Join(aZeile, Chr(FELD))
    Next i
    Schreiben(sAus, aAus())
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub

Sub Diagramm(sEin As String, sAus As String)
    Dim aWerte As Variant, oObj As Object, oChart As Object, oDaten As Object, sArt As String, aKopf As Variant
    Dim nZeilen As Integer, nReihen As Integer, i As Integer, j As Integer, aZeile As Variant, oDoc As Object
    Dim aDaten() As Variant, aReihe() As Double, aBeschriftungen() As String, aNamen() As String, oGroesse As New com.sun.star.awt.Size
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    oDoc = ThisComponent
    sArt = Wert(aWerte, 0)
    aKopf = Split(Wert(aWerte, 3), Chr(FELD))
    nReihen = UBound(aKopf)
    nZeilen = UBound(aWerte) - 4
    If nReihen < 1 Or nZeilen < 0 Then
        Melden(sAus, "Das Diagramm braucht mindestens eine Reihe mit Werten.")
        Exit Sub
    End If
    oDoc.UndoManager.enterUndoContext("Diagramm")
    oObj = Nothing
    If Wert(aWerte, 2) = "replace" Then oObj = Ausgewaehlt("''' + CLSID_CHART + r'''")
    If IsNull(oObj) Then
        oObj = NeuesObjekt("''' + CLSID_CHART + r'''")
        oGroesse.Width = 15000
        oGroesse.Height = 9000
        oObj.Size = oGroesse
    End If
    oChart = Modell(oObj)
    oChart.lockControllers()
    Select Case sArt
        Case "line": oChart.Diagram = oChart.createInstance("com.sun.star.chart.LineDiagram")
        Case "pie": oChart.Diagram = oChart.createInstance("com.sun.star.chart.PieDiagram")
        Case Else
            oChart.Diagram = oChart.createInstance("com.sun.star.chart.BarDiagram")
            oChart.Diagram.Vertical = (sArt = "bar")
    End Select
    ReDim aDaten(nZeilen)
    ReDim aBeschriftungen(nZeilen)
    ReDim aNamen(nReihen - 1)
    For j = 1 To nReihen
        aNamen(j - 1) = aKopf(j)
    Next j
    For i = 0 To nZeilen
        aZeile = Split(aWerte(4 + i), Chr(FELD))
        aBeschriftungen(i) = aZeile(0)
        ReDim aReihe(nReihen - 1)
        For j = 1 To nReihen
            If j <= UBound(aZeile) Then aReihe(j - 1) = Zahl(aZeile(j)) Else aReihe(j - 1) = 0
        Next j
        aDaten(i) = aReihe()
    Next i
    oDaten = oChart.Data
    oDaten.setData(aDaten())
    oDaten.setRowDescriptions(aBeschriftungen())
    oDaten.setColumnDescriptions(aNamen())
    oChart.HasMainTitle = (Wert(aWerte, 1) <> "")
    If oChart.HasMainTitle Then oChart.Title.String = Wert(aWerte, 1)
    oChart.HasLegend = (nReihen > 1 Or sArt = "pie")
    If sArt <> "pie" Then
        oChart.Diagram.Wall.FillStyle = com.sun.star.drawing.FillStyle.NONE
        oChart.Diagram.Wall.LineStyle = com.sun.star.drawing.LineStyle.NONE
    End If
    oChart.unlockControllers()
    oDoc.UndoManager.leaveUndoContext()
    Schreiben(sAus, Array("ok"))
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub

' Als geändert markieren (Serienbrief: das neue Dokument soll beim Schließen nach dem Speichern fragen)
Sub Geaendert(sEin As String, sAus As String)
    On Error GoTo Fehler
    ThisComponent.setModified(True)
    Schreiben(sAus, Array("ok"))
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub

' Mit einer anderen Fassung vergleichen: Die Unterschiede erscheinen als nachverfolgte Änderungen
Sub Vergleichen(sEin As String, sAus As String)
    Dim aWerte As Variant, oDispatcher As Object, aArgs(0) As New com.sun.star.beans.PropertyValue
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    aArgs(0).Name = "URL"
    aArgs(0).Value = Wert(aWerte, 0)
    oDispatcher = createUnoService("com.sun.star.frame.DispatchHelper")
    oDispatcher.executeDispatch(ThisComponent.CurrentController.Frame, ".uno:CompareDocuments", "", 0, aArgs())
    Schreiben(sAus, Array("ok", CStr(ThisComponent.Redlines.Count)))
    Exit Sub
Fehler:
    Melden(sAus, Error$)
End Sub
'''

SCRIPT_XLB = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">
<library:library xmlns:library="http://openoffice.org/2000/library" library:name="{library}" library:readonly="true" library:passwordprotected="false">
 <library:element library:name="{module}"/>
</library:library>
"""

MODULE_XBA = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="{module}" script:language="StarBasic">{code}</script:module>
"""

SCRIPT_XLC = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:libraries PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "libraries.dtd">
<library:libraries xmlns:library="http://openoffice.org/2000/library" xmlns:xlink="http://www.w3.org/1999/xlink">
 <library:library library:name="Standard" library:link="false"/>
 <library:library library:name="{library}" xlink:href="$(USER)/basic/{library}/script.xlb/" xlink:type="simple" library:link="true" library:readonly="true"/>
</library:libraries>
"""


STANDARD_XLB = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">
<library:library xmlns:library="http://openoffice.org/2000/library" library:name="Standard" library:readonly="false" library:passwordprotected="false"/>
"""

DIALOG_XLC = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:libraries PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "libraries.dtd">
<library:libraries xmlns:library="http://openoffice.org/2000/library" xmlns:xlink="http://www.w3.org/1999/xlink">
 <library:library library:name="Standard" library:link="false"/>
</library:libraries>
"""


def install(user: Path) -> None:
    """Bibliothek in ``<Profil>/user/basic`` schreiben und anmelden. »Standard« bleibt, wie LibreOffice sie angelegt
    hat; in einem neuen Profil legt Novadesk sie leer an (sonst fehlte sie, weil die Liste schon da ist)."""
    basic = user / "basic"
    standard = basic / "Standard"
    standard.mkdir(parents=True, exist_ok=True)
    for name in ("script.xlb", "dialog.xlb"):
        if not (standard / name).is_file():
            (standard / name).write_text(STANDARD_XLB, encoding="utf-8")
    if not (basic / "dialog.xlc").is_file():
        (basic / "dialog.xlc").write_text(DIALOG_XLC, encoding="utf-8")
    folder = basic / LIBRARY
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "script.xlb").write_text(SCRIPT_XLB.format(library=LIBRARY, module=MODULE), encoding="utf-8")
    (folder / f"{MODULE}.xba").write_text(MODULE_XBA.format(module=MODULE, code=escape(BASIC, {'"': "&quot;"})), encoding="utf-8")
    listing = basic / "script.xlc"
    if not listing.is_file() or f'library:name="{LIBRARY}"'.encode() not in listing.read_bytes():
        listing.write_text(SCRIPT_XLC.format(library=LIBRARY), encoding="utf-8")
