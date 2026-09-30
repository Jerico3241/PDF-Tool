"""Werkzeuge einrichten: jedes Werkzeug bringt eigene Controller mit und meldet sich beim
AppController (Tastenkürzel, Drag & Drop, Speichern) und bei QML (Singletons) an."""

from __future__ import annotations


def build_tools(runtime) -> None:
    """Controller der Werkzeuge anlegen und als QML-Singletons eintragen."""
    from .contracts.tool import ContractsTool
    from .repair import RepairTool

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
        }
    )
    repair = RepairTool(app, runtime.cfg)
    runtime.repair = repair
    runtime.singletons["Repair"] = repair.controller
    contracts.start()
