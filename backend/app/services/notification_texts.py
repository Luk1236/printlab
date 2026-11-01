"""Eingebaute Meldungstexte in weiteren Sprachen.

Die Meldungsvorlagen liegen in der Datenbank und sind editierbar. Übersetzt werden deshalb nur die **unveränderten**
Vorgaben: Wer den englischen Standardtext nie angefasst hat, bekommt ihn in der eingestellten Sprache; eine eigene
Formulierung bleibt unangetastet. Platzhalter sind dieselben wie in ``DEFAULT_TEMPLATES``.
"""

from __future__ import annotations

from backend.app.models.notification_template import DEFAULT_TEMPLATES

# Fünf zusätzliche Sprachen zu Englisch und Deutsch, für die häufigsten Ereignisse eines Drucks.
_TEXT: dict[str, dict[str, tuple[str, str]]] = {
    "de": {
        "print_start": ("Druck gestartet", "{printer}: {filename}\nGeschätzt: {estimated_time}"),
        "print_complete": ("Druck fertig", "{printer}: {filename}\nZeit: {duration}\nMaterial: {filament_grams} g"),
        "print_failed": ("Druck fehlgeschlagen", "{printer}: {filename}\nZeit: {duration}\nGrund: {reason}"),
        "print_stopped": ("Druck gestoppt", "{printer}: {filename}\nZeit: {duration}"),
        "print_progress": ("Druck zu {progress} % fertig", "{printer}: {filename}\nVerbleibend: {remaining_time}"),
    },
    "es": {
        "print_start": ("Impresión iniciada", "{printer}: {filename}\nEstimado: {estimated_time}"),
        "print_complete": (
            "Impresión terminada",
            "{printer}: {filename}\nTiempo: {duration}\nFilamento: {filament_grams} g",
        ),
        "print_failed": ("Impresión fallida", "{printer}: {filename}\nTiempo: {duration}\nMotivo: {reason}"),
        "print_stopped": ("Impresión detenida", "{printer}: {filename}\nTiempo: {duration}"),
        "print_progress": ("Impresión al {progress} %", "{printer}: {filename}\nRestante: {remaining_time}"),
    },
    "fr": {
        "print_start": ("Impression démarrée", "{printer} : {filename}\nEstimé : {estimated_time}"),
        "print_complete": (
            "Impression terminée",
            "{printer} : {filename}\nDurée : {duration}\nFilament : {filament_grams} g",
        ),
        "print_failed": ("Impression échouée", "{printer} : {filename}\nDurée : {duration}\nCause : {reason}"),
        "print_stopped": ("Impression arrêtée", "{printer} : {filename}\nDurée : {duration}"),
        "print_progress": ("Impression à {progress} %", "{printer} : {filename}\nRestant : {remaining_time}"),
    },
    "it": {
        "print_start": ("Stampa avviata", "{printer}: {filename}\nStimato: {estimated_time}"),
        "print_complete": (
            "Stampa completata",
            "{printer}: {filename}\nTempo: {duration}\nFilamento: {filament_grams} g",
        ),
        "print_failed": ("Stampa non riuscita", "{printer}: {filename}\nTempo: {duration}\nMotivo: {reason}"),
        "print_stopped": ("Stampa fermata", "{printer}: {filename}\nTempo: {duration}"),
        "print_progress": ("Stampa al {progress}%", "{printer}: {filename}\nRimanente: {remaining_time}"),
    },
    "ja": {
        "print_start": ("印刷開始", "{printer}: {filename}\n予想時間: {estimated_time}"),
        "print_complete": ("印刷完了", "{printer}: {filename}\n時間: {duration}\nフィラメント: {filament_grams} g"),
        "print_failed": ("印刷失敗", "{printer}: {filename}\n時間: {duration}\n理由: {reason}"),
        "print_stopped": ("印刷停止", "{printer}: {filename}\n時間: {duration}"),
        "print_progress": ("印刷 {progress}% 完了", "{printer}: {filename}\n残り: {remaining_time}"),
    },
    "zh-CN": {
        "print_start": ("开始打印", "{printer}: {filename}\n预计: {estimated_time}"),
        "print_complete": ("打印完成", "{printer}: {filename}\n用时: {duration}\n耗材: {filament_grams} g"),
        "print_failed": ("打印失败", "{printer}: {filename}\n用时: {duration}\n原因: {reason}"),
        "print_stopped": ("打印停止", "{printer}: {filename}\n用时: {duration}"),
        "print_progress": ("打印进度 {progress}%", "{printer}: {filename}\n剩余: {remaining_time}"),
    },
}

_BY_EVENT = {entry["event_type"]: entry for entry in DEFAULT_TEMPLATES}


def localized_default(event_type: str, language: str, title: str, body: str) -> tuple[str, str] | None:
    """Übersetzung für eine unveränderte Standardvorlage, sonst ``None``.

    ``None`` ist die wichtige Antwort: Sie bedeutet „eigene Vorlage, bitte unverändert senden“. Nur wenn Titel **und**
    Text exakt den englischen Vorgaben entsprechen, gilt die Vorlage als unangetastet.
    """
    default = _BY_EVENT.get(event_type)
    if default is None or title != default["title_template"] or body != default["body_template"]:
        return None
    return _TEXT.get(language, {}).get(event_type)


SUPPORTED_LANGUAGES = ("en", "de", "es", "fr", "it", "ja", "zh-CN")
