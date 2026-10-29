"""Werkzeuge einrichten: jedes Werkzeug bringt eigene Controller mit und meldet sich beim
AppController (Tastenkürzel, Drag & Drop, Speichern) und bei QML (Singletons) an."""

from __future__ import annotations


def build_tools(runtime) -> None:
    """Controller der Werkzeuge anlegen und als QML-Singletons eintragen."""
    from .contracts.tool import ContractsTool
    from .actions import ActionsTool
    from .convert import ConvertTool
    from .reader.controller import ReaderTool
    from .repair import RepairTool
    from .versions import VersionsTool

    app = runtime.app
    contracts = ContractsTool(app, runtime.cfg)
    runtime.contracts = contracts
    runtime.settings.attach_customers(contracts.customers)
    runtime.preview_lookup = contracts.preview.lookup
    runtime.singletons.update(
        {
            "Contracts": contracts.overview,
            "Customers": contracts.customers,
            "Preview": contracts.preview,
            "Batch": contracts.batch,
            "Comparison": contracts.comparison,
            "Templates": contracts.templates,
            "Rules": contracts.rules,
        }
    )
    repair = RepairTool(app, runtime.cfg)
    runtime.repair = repair
    runtime.singletons["Repair"] = repair.controller
    app.repair_tool = repair  # beschädigte PDF aus dem Reader an »PDF reparieren« übergeben
    reader = ReaderTool(app, runtime.cfg)
    runtime.reader = reader
    runtime.singletons["Reader"] = reader.controller
    runtime.image_providers["pdfpage"] = reader.controller.provider
    app.reader_controller = reader.controller  # Ergebnisse der Stapel-Aktionen im Reader öffnen
    batch_actions = ActionsTool(app, runtime.cfg)
    runtime.actions = batch_actions
    runtime.singletons["Actions"] = batch_actions.controller
    converter = ConvertTool(app, runtime.cfg)
    runtime.convert = converter
    runtime.singletons["Convert"] = converter.controller
    keeper = VersionsTool(app, runtime.cfg)
    runtime.versions = keeper
    runtime.singletons["Versions"] = keeper.controller
    keeper.controller.start()
    contracts.start()
