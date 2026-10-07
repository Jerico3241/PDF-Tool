import QtQuick
import PdfTool.Backend
import PdfTool.Style

// Seitenwechsel: Seite A blendet kurz aus, die fertige Zielseite wird umgeschaltet und blendet
// ein (zusammen ~180 ms, »Aus«: sofort). Die erste Seite entsteht beim Laden der Oberfläche und steht
// ohne Einblenden im ersten Bild. Seiten bleiben nach dem ersten Laden bestehen; nach dem
// Start werden alle verfügbaren Seiten nacheinander im Hintergrund geladen, damit ein Wechsel
// nie auf den Aufbau warten muss. Nicht sichtbare Seiten werden nicht gezeichnet.
Item {
    id: host
    property var components: ({})       // Seitenschlüssel → Component
    property var order: []               // Reihenfolge des Vorladens
    property string shownKey: ""
    property bool preloading: false
    readonly property string targetKey: App.currentPage
    readonly property bool transitioning: outAnim.running || inAnim.running

    onTargetKeyChanged: update()

    function slotFor(key) {
        for (var i = 0; i < slots.count; ++i) {
            var slot = slots.itemAt(i)
            if (slot && slot.key === key) return slot
        }
        return null
    }
    function update() {
        var key = targetKey
        if (key === "") return
        var slot = slotFor(key)
        if (!slot) return
        slot.wanted = true
        if (slot.status !== Loader.Ready) return          // weiter, sobald die Seite fertig ist
        if (key === shownKey && !outAnim.running) {
            if (!inAnim.running) { slot.visible = true; slot.opacity = 1; shift.y = 0 }
            return
        }
        var current = slotFor(shownKey)
        if (current && current.visible && Motion.enabled) {
            inAnim.stop()
            outAnim.target = current
            outAnim.from = current.opacity
            outAnim.restart()
            return
        }
        commit()
    }
    function commit() {
        var key = targetKey
        var slot = slotFor(key)
        if (!slot || slot.status !== Loader.Ready) return
        var hadFocus = false
        for (var i = 0; i < slots.count; ++i) {
            var other = slots.itemAt(i)
            if (other && other !== slot) {
                if (other.activeFocus) hadFocus = true
                other.visible = false; other.opacity = 1; other.transform = []
            }
        }
        shownKey = key
        slot.transform = [shift]
        slot.visible = true
        // Tastaturfokus nur mitnehmen, wenn er auf der verlassenen Seite lag (sonst bleibt er z. B. in der Tab-Leiste)
        if (hadFocus) slot.forceActiveFocus()
        // Ohne Animation: »Aus« – und die erste Seite beim Start (sie steht fertig im ersten Bild)
        if (!Motion.enabled || !App.ready) { slot.opacity = 1; shift.y = 0; return }
        slot.opacity = 0
        shift.y = Motion.pageShift
        inAnim.targetSlot = slot
        inAnim.restart()
    }
    function preloadNext() {
        if (!App.ready) return
        for (var i = 0; i < order.length; ++i) {
            var slot = slotFor(order[i])
            if (slot && !slot.wanted && components[order[i]] && App.unavailablePages.indexOf(order[i]) < 0) {
                slot.wanted = true
                return
            }
        }
        preloading = false
        if (!App.pagesLoaded && allLoaded()) App.markPagesLoaded()
    }
    function allLoaded() {
        for (var i = 0; i < slots.count; ++i) {
            var slot = slots.itemAt(i)
            if (slot && slot.wanted && slot.status === Loader.Loading) return false
        }
        return true
    }
    Connections {
        target: App
        function onReadyChanged() { if (App.ready) host.preloadNext() }
        function onUnavailablePagesChanged() { host.preloadNext() }
    }

    Translate { id: shift; y: 0 }
    NumberAnimation {
        id: outAnim
        property: "opacity"
        to: 0
        duration: Motion.pageOut
        easing.type: Motion.accelerate
        onFinished: host.commit()
    }
    ParallelAnimation {
        id: inAnim
        property Item targetSlot: null
        NumberAnimation { target: inAnim.targetSlot; property: "opacity"; from: 0; to: 1; duration: Motion.pageIn; easing.type: Motion.decelerate }
        NumberAnimation { target: shift; property: "y"; to: 0; duration: Motion.pageIn; easing.type: Motion.decelerate }
    }

    Repeater {
        id: slots
        model: host.order
        Loader {
            id: slot
            required property string modelData
            readonly property string key: modelData
            property bool wanted: false
            objectName: "page_" + key
            width: host.width
            height: host.height
            visible: false
            active: wanted
            asynchronous: key !== host.targetKey || App.ready
            sourceComponent: host.components[key] || null
            onLoaded: {
                if (key === host.targetKey) host.update()
                host.preloadNext()
            }
            // Die Seite, mit der die App startet, gleich beim Laden der Oberfläche aufbauen (synchron, s. o.)
            Component.onCompleted: if (key === host.targetKey) host.update()
        }
    }
}
