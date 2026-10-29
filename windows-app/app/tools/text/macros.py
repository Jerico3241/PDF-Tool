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
SLIDES_MODULE = "Folien"  # seit 5.0 Beta 6: Präsentationen
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

SLIDES_BASIC = r'''
Option Explicit

' Präsentationen (seit 5.0 Beta 6): Designs, Hintergrund, Video und Ton, Übergänge. Die Hilfen Lesen, Schreiben,
' Melden, Wert und Zahl stehen im Modul »Text« derselben Bibliothek.

Function Farbe(s As String) As Long
    s = Replace(Trim(s), "#", "")
    If Len(s) <> 6 Then
        Farbe = -1
    Else
        Farbe = CLng("&H" & s)
    End If
End Function

Function Hintergrund(sFarbe1 As String, sFarbe2 As String) As Object
    Dim oBg As Object, oVerlauf As New com.sun.star.awt.Gradient
    oBg = ThisComponent.createInstance("com.sun.star.drawing.Background")
    If sFarbe2 = "" Then
        oBg.FillStyle = com.sun.star.drawing.FillStyle.SOLID
        oBg.FillColor = Farbe(sFarbe1)
    Else
        oVerlauf.Style = com.sun.star.awt.GradientStyle.LINEAR
        oVerlauf.StartColor = Farbe(sFarbe1)
        oVerlauf.EndColor = Farbe(sFarbe2)
        oVerlauf.Angle = 450
        oVerlauf.Border = 0
        oVerlauf.XOffset = 0
        oVerlauf.YOffset = 0
        oVerlauf.StartIntensity = 100
        oVerlauf.EndIntensity = 100
        oVerlauf.StepCount = 0
        oBg.FillStyle = com.sun.star.drawing.FillStyle.GRADIENT
        oBg.FillGradient = oVerlauf
    End If
    Hintergrund = oBg
End Function

Sub Schrift(oStil As Object, sName As String, nFarbe As Long)
    If sName <> "" Then
        oStil.CharFontName = sName
        oStil.CharFontNameAsian = sName
        oStil.CharFontNameComplex = sName
    End If
    If nFarbe >= 0 Then oStil.CharColor = nFarbe
End Sub

Sub Rechteck(oSeite As Object, nX As Long, nY As Long, nB As Long, nH As Long, nFarbe As Long, sName As String)
    Dim oForm As Object, oPos As New com.sun.star.awt.Point, oGr As New com.sun.star.awt.Size
    oForm = ThisComponent.createInstance("com.sun.star.drawing.RectangleShape")
    oSeite.add(oForm)
    oPos.X = nX : oPos.Y = nY : oGr.Width = nB : oGr.Height = nH
    oForm.Position = oPos
    oForm.Size = oGr
    oForm.FillColor = nFarbe
    oForm.LineStyle = com.sun.star.drawing.LineStyle.NONE
    oForm.Name = sName
    oForm.MoveProtect = True
    oForm.SizeProtect = True
    oForm.ZOrder = 0
End Sub

' Design auf alle Folienmaster: Hintergrund (Farbe 1, Farbe 2 für einen Verlauf oder leer), Schrift und Farbe des
' Titels und des Textes, Akzentfarbe und -form (leiste, linie, band, ecke oder leer)
Sub DesignAnwenden(sEin As String, sAus As String)
    Dim aWerte As Variant, oDoc As Object, oMaster As Object, oStile As Object, i As Integer, j As Integer
    Dim nAkzent As Long, sForm As String, nB As Long, nH As Long, oForm As Object, sStil As String
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    oDoc = ThisComponent
    nAkzent = Farbe(Wert(aWerte, 6))
    sForm = Wert(aWerte, 7)
    oDoc.UndoManager.enterUndoContext("Design")
    For i = 0 To oDoc.MasterPages.Count - 1
        oMaster = oDoc.MasterPages.getByIndex(i)
        oMaster.Background = Hintergrund(Wert(aWerte, 0), Wert(aWerte, 1))
        For j = oMaster.Count - 1 To 0 Step -1
            oForm = oMaster.getByIndex(j)
            If Left(oForm.Name, 14) = "NovadeskAkzent" Then oMaster.remove(oForm)
        Next j
        nB = oMaster.Width : nH = oMaster.Height
        If nAkzent >= 0 Then
            Select Case sForm
                Case "leiste" : Rechteck(oMaster, 0, 0, nB \ 60, nH, nAkzent, "NovadeskAkzent")
                Case "linie" : Rechteck(oMaster, nB \ 16, nH - nH \ 9, nB - nB \ 8, nH \ 160, nAkzent, "NovadeskAkzent")
                Case "band" : Rechteck(oMaster, 0, 0, nB, nH \ 40, nAkzent, "NovadeskAkzent")
                Case "ecke"
                    Rechteck(oMaster, nB - nB \ 7, 0, nB \ 7, nH \ 40, nAkzent, "NovadeskAkzent1")
                    Rechteck(oMaster, nB - nH \ 40, 0, nH \ 40, nH \ 5, nAkzent, "NovadeskAkzent2")
            End Select
        End If
        oStile = oDoc.StyleFamilies.getByName(oMaster.Name)
        Schrift(oStile.getByName("title"), Wert(aWerte, 2), Farbe(Wert(aWerte, 3)))
        Schrift(oStile.getByName("subtitle"), Wert(aWerte, 4), Farbe(Wert(aWerte, 5)))
        For j = 1 To 9
            sStil = "outline" & CStr(j)
            If oStile.hasByName(sStil) Then Schrift(oStile.getByName(sStil), Wert(aWerte, 4), Farbe(Wert(aWerte, 5)))
        Next j
    Next i
    oDoc.UndoManager.leaveUndoContext()
    Schreiben(sAus, Array("ok", CStr(oDoc.MasterPages.Count)))
    Exit Sub
Fehler:
    Melden(sAus, Error$ & " (Zeile " & Erl & ")")
End Sub

' Hintergrund einer Folie (Wert 2: Nummer ab 0, -1 = alle Folien); leere Farbe: wie im Folienmaster
Sub FolienHintergrund(sEin As String, sAus As String)
    Dim aWerte As Variant, oDoc As Object, oSeite As Object, i As Integer
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    oDoc = ThisComponent
    oDoc.UndoManager.enterUndoContext("Hintergrund")
    For i = 0 To oDoc.DrawPages.Count - 1
        oSeite = oDoc.DrawPages.getByIndex(i)
        If Wert(aWerte, 2) = "-1" Or Wert(aWerte, 2) = CStr(i) Then
            If Wert(aWerte, 0) = "" Then
                oSeite.setPropertyToDefault("Background")
            Else
                oSeite.Background = Hintergrund(Wert(aWerte, 0), Wert(aWerte, 1))
            End If
        End If
    Next i
    oDoc.UndoManager.leaveUndoContext()
    Schreiben(sAus, Array("ok"))
    Exit Sub
Fehler:
    Melden(sAus, Error$ & " (Zeile " & Erl & ")")
End Sub

Function Zuletzt(s As String, sTeil As String) As Long
    Dim n As Long, nGefunden As Long
    nGefunden = 0
    n = InStr(1, s, sTeil)
    Do While n > 0
        nGefunden = n
        n = InStr(n + 1, s, sTeil)
    Loop
    Zuletzt = nGefunden
End Function

' Datei in den Ordner »Media« des Dokuments kopieren (wie avmedia::EmbedMedia); Antwort: Adresse im Dokument
Function Einbetten(sUrl As String, sTyp As String) As String
    Dim oSfa As Object, oQuelle As Object, oSpeicher As Object, oMedien As Object, oStrom As Object, oAus As Object
    Dim sName As String, sEndung As String, n As Integer, aDaten() As Byte, nGelesen As Long
    oSfa = createUnoService("com.sun.star.ucb.SimpleFileAccess")
    oQuelle = oSfa.openFileRead(sUrl)
    sName = Mid(sUrl, Zuletzt(sUrl, "/") + 1)
    sEndung = ""
    If Zuletzt(sName, ".") > 0 Then sEndung = LCase(Mid(sName, Zuletzt(sName, ".")))
    oSpeicher = ThisComponent.getDocumentStorage()
    oMedien = oSpeicher.openStorageElement("Media", com.sun.star.embed.ElementModes.READWRITE)
    n = 1
    Do While oMedien.hasByName("media" & CStr(n) & sEndung)
        n = n + 1
    Loop
    sName = "media" & CStr(n) & sEndung
    oStrom = oMedien.openStreamElement(sName, com.sun.star.embed.ElementModes.WRITE)
    oAus = oStrom.getOutputStream()
    Do
        nGelesen = oQuelle.readBytes(aDaten, 1048576)
        If nGelesen > 0 Then oAus.writeBytes(aDaten)
    Loop While nGelesen > 0
    oQuelle.closeInput()
    If sTyp <> "" Then oStrom.setPropertyValue("MediaType", sTyp)
    oAus.closeOutput()
    oMedien.commit()
    oSpeicher.commit()
    Einbetten = "vnd.sun.star.Package:Media/" & sName
End Function

Function Bild(sUrl As String) As Object
    Dim aArg(0) As New com.sun.star.beans.PropertyValue
    aArg(0).Name = "URL"
    aArg(0).Value = sUrl
    Bild = createUnoService("com.sun.star.graphic.GraphicProvider").queryGraphic(aArg())
End Function

' Video oder Ton auf einer Folie: Adresse der Datei, Art (video oder ton), Breite und Höhe in Pixeln (0: unbekannt),
' Art der Datei (MIME), Folie (ab 0), Adresse des Vorschaubilds (leer: LibreOffice holt eins)
Sub MedienEinfuegen(sEin As String, sAus As String)
    Dim aWerte As Variant, oSeite As Object, oForm As Object, nB As Long, nH As Long, nVB As Double, nVH As Double
    Dim oPos As New com.sun.star.awt.Point, oGr As New com.sun.star.awt.Size, sUrl As String
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    oSeite = ThisComponent.DrawPages.getByIndex(CInt(Zahl(Wert(aWerte, 5))))
    nB = ThisComponent.DrawPages.getByIndex(0).Width
    nH = ThisComponent.DrawPages.getByIndex(0).Height
    If Wert(aWerte, 1) = "ton" Then
        oGr.Width = nH \ 8 : oGr.Height = nH \ 8
        oPos.X = nB - oGr.Width - nB \ 30 : oPos.Y = nH - oGr.Height - nH \ 20
    Else
        nVB = Zahl(Wert(aWerte, 2)) : nVH = Zahl(Wert(aWerte, 3))
        If nVB <= 0 Or nVH <= 0 Then nVB = 16 : nVH = 9
        oGr.Width = nB * 0.6
        oGr.Height = oGr.Width * nVH / nVB
        If oGr.Height > nH * 0.7 Then
            oGr.Height = nH * 0.7
            oGr.Width = oGr.Height * nVB / nVH
        End If
        oPos.X = (nB - oGr.Width) \ 2 : oPos.Y = (nH - oGr.Height) \ 2
    End If
    sUrl = Einbetten(Wert(aWerte, 0), Wert(aWerte, 4))
    oForm = ThisComponent.createInstance("com.sun.star.presentation.MediaShape")
    oSeite.add(oForm)
    oForm.Size = oGr
    oForm.Position = oPos
    ' Vorschaubild von Novadesk: Sonst holt LibreOffice selbst ein Bild aus dem Video – das dauert mitunter Sekunden
    If Wert(aWerte, 6) <> "" Then
        On Error Resume Next
        oForm.Graphic = Bild(Wert(aWerte, 6))
        On Error GoTo Fehler
    End If
    If Wert(aWerte, 4) <> "" Then oForm.MediaMimeType = Wert(aWerte, 4)
    ' Erst jetzt die Datei (danach dauerte jede Änderung an der Form Sekunden), eingebettet wie
    ' »Einfügen« in LibreOffice: Die Präsentation nimmt die Datei mit, auch als .pptx
    oForm.MediaURL = sUrl
    ' Ein neues Dokument findet die Datei darin noch nicht: dann wie beim Laden aus einer Datei übergeben
    If oForm.PrivateTempFileURL = "" Then
        On Error Resume Next
        oForm.PrivateStream = createUnoService("com.sun.star.ucb.SimpleFileAccess").openFileRead(Wert(aWerte, 0))
        On Error GoTo Fehler
    End If
    Schreiben(sAus, Array("ok"))
    Exit Sub
Fehler:
    Melden(sAus, Error$ & " (Zeile " & Erl & ")")
End Sub

' Alle Videos und Töne: je Eintrag Folie, Datei zum Abspielen, Links, Oben, Breite, Höhe (1/100 mm), Wiederholen, Art
Sub Medien(sEin As String, sAus As String)
    Dim oDoc As Object, oSeite As Object, oForm As Object, i As Integer, j As Integer, aAus() As String, n As Integer
    Dim sDatei As String
    On Error GoTo Fehler
    oDoc = ThisComponent
    n = 0
    ReDim aAus(0)
    aAus(0) = "ok"
    For i = 0 To oDoc.DrawPages.Count - 1
        oSeite = oDoc.DrawPages.getByIndex(i)
        For j = 0 To oSeite.Count - 1
            oForm = oSeite.getByIndex(j)
            If oForm.ShapeType = "com.sun.star.presentation.MediaShape" Then
                sDatei = ""
                On Error Resume Next
                sDatei = oForm.PrivateTempFileURL
                On Error GoTo Fehler
                If sDatei = "" Then sDatei = oForm.MediaURL
                n = n + 1
                ReDim Preserve aAus(n)
                aAus(n) = Join(Array(CStr(i), sDatei, CStr(oForm.Position.X), CStr(oForm.Position.Y), _
                    CStr(oForm.Size.Width), CStr(oForm.Size.Height), IIf(oForm.Loop, "1", "0"), oForm.MediaMimeType), Chr(31))
            End If
        Next j
    Next i
    Schreiben(sAus, aAus)
    Exit Sub
Fehler:
    Melden(sAus, Error$ & " (Zeile " & Erl & ")")
End Sub

' Übergang einer Folie: Art, Dauer in Sekunden, nach Sekunden weiter (leer: Klick), Folie (ab 0, -1 = alle)
Sub UebergangSetzen(sEin As String, sAus As String)
    Dim aWerte As Variant, oDoc As Object, oSeite As Object, i As Integer, nArt As Integer, nUnter As Integer
    Dim sArt As String
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    oDoc = ThisComponent
    sArt = Wert(aWerte, 0)
    nArt = 0 : nUnter = 0
    Select Case sArt
        Case "blenden" : nArt = com.sun.star.animations.TransitionType.FADE : nUnter = com.sun.star.animations.TransitionSubType.CROSSFADE
        Case "schwarz" : nArt = com.sun.star.animations.TransitionType.FADE : nUnter = com.sun.star.animations.TransitionSubType.FADEOVERCOLOR
        Case "schieben" : nArt = com.sun.star.animations.TransitionType.PUSHWIPE : nUnter = com.sun.star.animations.TransitionSubType.FROMRIGHT
        Case "wischen" : nArt = com.sun.star.animations.TransitionType.BARWIPE : nUnter = com.sun.star.animations.TransitionSubType.LEFTTORIGHT
        Case "aufdecken" : nArt = com.sun.star.animations.TransitionType.SLIDEWIPE : nUnter = com.sun.star.animations.TransitionSubType.FROMRIGHT
    End Select
    oDoc.UndoManager.enterUndoContext("Übergang")
    For i = 0 To oDoc.DrawPages.Count - 1
        oSeite = oDoc.DrawPages.getByIndex(i)
        If Wert(aWerte, 3) = "-1" Or Wert(aWerte, 3) = CStr(i) Then
            oSeite.TransitionType = nArt
            oSeite.TransitionSubtype = nUnter
            oSeite.TransitionDirection = True
            If nArt = 0 Then oSeite.Effect = com.sun.star.presentation.FadeEffect.NONE
            If Zahl(Wert(aWerte, 1)) > 0 Then oSeite.TransitionDuration = Zahl(Wert(aWerte, 1))
            If Wert(aWerte, 2) = "" Then
                oSeite.Change = 0
            Else
                oSeite.Change = 1
                oSeite.HighResDuration = Zahl(Wert(aWerte, 2))
            End If
        End If
    Next i
    oDoc.UndoManager.leaveUndoContext()
    Schreiben(sAus, Array("ok"))
    Exit Sub
Fehler:
    Melden(sAus, Error$ & " (Zeile " & Erl & ")")
End Sub

Function UebergangArt(nArt As Integer, nUnter As Integer) As String
    Dim sArt As String
    Select Case nArt
        Case 0 : sArt = "keiner"
        Case com.sun.star.animations.TransitionType.FADE
            If nUnter = com.sun.star.animations.TransitionSubType.FADEOVERCOLOR Or nUnter = com.sun.star.animations.TransitionSubType.FADETOCOLOR Then
                sArt = "schwarz"
            Else
                sArt = "blenden"
            End If
        Case com.sun.star.animations.TransitionType.PUSHWIPE : sArt = "schieben"
        Case com.sun.star.animations.TransitionType.BARWIPE : sArt = "wischen"
        Case com.sun.star.animations.TransitionType.SLIDEWIPE : sArt = "aufdecken"
        Case Else : sArt = "andere"
    End Select
    UebergangArt = sArt
End Function

' Übergänge aller Folien: je Eintrag Art (keiner, blenden, schwarz, schieben, wischen, aufdecken, andere), Dauer in
' Sekunden, Wechsel (0 Klick, 1 nach Zeit), Zeit in Sekunden
Sub Uebergaenge(sEin As String, sAus As String)
    Dim oDoc As Object, oSeite As Object, i As Integer, n As Integer, aAus() As String
    On Error GoTo Fehler
    oDoc = ThisComponent
    n = oDoc.DrawPages.Count
    ReDim aAus(n)
    aAus(0) = "ok"
    For i = 0 To oDoc.DrawPages.Count - 1
        oSeite = oDoc.DrawPages.getByIndex(i)
        aAus(i + 1) = Join(Array(UebergangArt(oSeite.TransitionType, oSeite.TransitionSubtype), _
            Trim(Str(oSeite.TransitionDuration)), CStr(oSeite.Change), Trim(Str(oSeite.HighResDuration))), Chr(31))
    Next i
    Schreiben(sAus, aAus)
    Exit Sub
Fehler:
    Melden(sAus, Error$ & " (Zeile " & Erl & ")")
End Sub

' Folien als Bilder wie beim Vorführen (ohne leere Platzhalter): Ordner (Adresse), Breite, Höhe in Pixeln, Art (png
' oder jpg), erste und letzte Folie (ab 0). Dateien »folie-<Nummer ab 1>.<Art>« im Ordner
Sub FolienBilder(sEin As String, sAus As String)
    Dim aWerte As Variant, oFilter As Object, i As Integer, sArt As String, sTyp As String, nBis As Integer
    Dim aDaten(2) As New com.sun.star.beans.PropertyValue
    Dim aArg(2) As New com.sun.star.beans.PropertyValue
    On Error GoTo Fehler
    aWerte = Lesen(sEin)
    sArt = LCase(Wert(aWerte, 3))
    sTyp = IIf(sArt = "jpg", "image/jpeg", "image/png")
    aDaten(0).Name = "PixelWidth" : aDaten(0).Value = CLng(Zahl(Wert(aWerte, 1)))
    aDaten(1).Name = "PixelHeight" : aDaten(1).Value = CLng(Zahl(Wert(aWerte, 2)))
    aDaten(2).Name = "Quality" : aDaten(2).Value = 92
    oFilter = createUnoService("com.sun.star.drawing.GraphicExportFilter")
    nBis = CInt(Zahl(Wert(aWerte, 5)))
    If nBis > ThisComponent.DrawPages.Count - 1 Then nBis = ThisComponent.DrawPages.Count - 1
    For i = CInt(Zahl(Wert(aWerte, 4))) To nBis
        oFilter.setSourceDocument(ThisComponent.DrawPages.getByIndex(i))
        aArg(0).Name = "URL" : aArg(0).Value = Wert(aWerte, 0) & "/folie-" & CStr(i + 1) & "." & sArt
        aArg(1).Name = "MediaType" : aArg(1).Value = sTyp
        aArg(2).Name = "FilterData" : aArg(2).Value = aDaten()
        oFilter.filter(aArg())
    Next i
    Schreiben(sAus, Array("ok"))
    Exit Sub
Fehler:
    Melden(sAus, Error$ & " (Zeile " & Erl & ")")
End Sub
'''

MODULES = {MODULE: BASIC, SLIDES_MODULE: SLIDES_BASIC}

SCRIPT_XLB = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">
<library:library xmlns:library="http://openoffice.org/2000/library" library:name="{library}" library:readonly="true" library:passwordprotected="false">
 {elements}
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
    elements = "\n ".join(f'<library:element library:name="{name}"/>' for name in MODULES)
    (folder / "script.xlb").write_text(SCRIPT_XLB.format(library=LIBRARY, elements=elements), encoding="utf-8")
    for name, code in MODULES.items():
        (folder / f"{name}.xba").write_text(MODULE_XBA.format(module=name, code=escape(code, {'"': "&quot;"})), encoding="utf-8")
    listing = basic / "script.xlc"
    if not listing.is_file() or f'library:name="{LIBRARY}"'.encode() not in listing.read_bytes():
        listing.write_text(SCRIPT_XLC.format(library=LIBRARY), encoding="utf-8")
