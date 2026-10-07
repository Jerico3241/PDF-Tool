"""Die Sprachmodelle des KI-Assistenten: feste Quelle (Hugging Face), feste Revision und SHA-256 – ein Modell wird nur
verwendet, wenn die geladene Datei genau dieser Prüfsumme entspricht.

Beide Modelle stehen unter der Apache-Lizenz 2.0 (Qwen3.5 von Alibaba Cloud, als GGUF von Unsloth) und sprechen
Deutsch. »Genau« beantwortete im Test alle Fragen zu einem Vertrag richtig, braucht aber rund 5 GB Arbeitsspeicher;
»Kompakt« ist etwa doppelt so schnell und braucht rund 2 GB, ist aber ungenauer.
"""

from __future__ import annotations

from dataclasses import dataclass

GB = 1024**3
SOURCE_HOST = "huggingface.co"


@dataclass(frozen=True)
class Model:
    key: str
    name: str  # in der Oberfläche
    description: str
    repo: str  # Hugging Face
    revision: str  # Commit – die Datei ändert sich nie mehr
    file: str
    size: int  # Bytes
    sha256: str
    ram: int  # empfohlener Arbeitsspeicher des PCs (Bytes)
    memory: int  # Bedarf beim Antworten (Bytes, gemessen mit 8192 Tokens Kontext)
    license: str = "Apache-2.0"

    @property
    def url(self) -> str:
        return f"https://{SOURCE_HOST}/{self.repo}/resolve/{self.revision}/{self.file}"

    @property
    def page(self) -> str:
        """Seite des Modells (Lizenz, Herkunft) – für den Hinweis in der Oberfläche."""
        return f"https://{SOURCE_HOST}/{self.repo}"


STANDARD = Model(
    key="standard",
    name="Genau",
    description="Qwen3.5 4B – genauere Antworten, braucht mehr Arbeitsspeicher",
    repo="unsloth/Qwen3.5-4B-GGUF",
    revision="e87f176479d0855a907a41277aca2f8ee7a09523",
    file="Qwen3.5-4B-Q4_K_M.gguf",
    size=2_740_937_888,
    sha256="00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
    ram=12 * GB,
    memory=5 * GB,
)
COMPACT = Model(
    key="kompakt",
    name="Kompakt",
    description="Qwen3.5 2B – schneller und kleiner, etwas ungenauer",
    repo="unsloth/Qwen3.5-2B-GGUF",
    revision="f6d5376be1edb4d416d56da11e5397a961aca8ae",
    file="Qwen3.5-2B-Q4_K_M.gguf",
    size=1_280_835_840,
    sha256="aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223",
    ram=6 * GB,
    memory=int(2.2 * GB),
)
MODELS = (STANDARD, COMPACT)
BY_KEY = {model.key: model for model in MODELS}
MIN_RAM = 6 * GB  # darunter wird der Assistent nicht empfohlen (Hinweis, kein Verbot)


def get(key: str) -> Model | None:
    return BY_KEY.get(str(key or ""))


def recommended(ram: int) -> Model:
    """Empfehlung für einen PC mit ``ram`` Bytes Arbeitsspeicher (0: unbekannt → »Kompakt«)."""
    return STANDARD if ram >= STANDARD.ram else COMPACT
