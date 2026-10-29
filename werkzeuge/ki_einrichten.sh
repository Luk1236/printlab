#!/usr/bin/env bash
# Richtet auf dem Pi einen lokalen KI-Assistenten für PrintLab ein: Ollama (Modell-Server) und ein kleines Modell.
#
#   werkzeuge/ki_einrichten.sh                      # prüft alles und lädt das Standardmodell
#   werkzeuge/ki_einrichten.sh qwen2.5:1.5b         # anderes Modell (kleiner = schneller, weniger zuverlässig)
#   werkzeuge/ki_einrichten.sh --installieren       # installiert zuvor Ollama mit dem offiziellen Skript (braucht sudo)
#
# Das Skript ändert nichts an PrintLab selbst. Danach unter Wartung → Assistent einschalten.
set -euo pipefail

MODEL="qwen2.5:3b"          # muss zur Voreinstellung in backend/app/services/assistant_config.py passen
URL="http://127.0.0.1:11434"
INSTALL=0

for arg in "$@"; do
  case "$arg" in
    --installieren) INSTALL=1 ;;
    -*) echo "Unbekannte Option: $arg" >&2; exit 2 ;;
    *) MODEL="$arg" ;;
  esac
done

echo "== Lokaler KI-Assistent: Einrichtung =="

if ! command -v ollama >/dev/null 2>&1; then
  if [ "$INSTALL" -eq 1 ]; then
    echo "Ollama wird mit dem offiziellen Skript von ollama.com installiert (fragt nach sudo) ..."
    curl -fsSL https://ollama.com/install.sh | sh
  else
    echo "Ollama ist nicht installiert."
    echo "Installation mit dem offiziellen Skript (braucht sudo):"
    echo "    curl -fsSL https://ollama.com/install.sh | sh"
    echo "oder dieses Skript mit --installieren erneut starten."
    exit 1
  fi
fi

# Arbeitsspeicher: ein Modell mit 3 Milliarden Parametern braucht etwa 2 bis 3 GB frei.
if [ -r /proc/meminfo ]; then
  mem_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
  echo "Arbeitsspeicher: ${mem_mb} MB"
  if [ "$mem_mb" -lt 3500 ]; then
    echo "Hinweis: Das ist wenig. Nimm ein kleineres Modell (zum Beispiel qwen2.5:1.5b) oder rechne mit Verzögerungen." >&2
  fi
fi

if ! curl -fsS --max-time 5 "$URL/api/tags" >/dev/null 2>&1; then
  echo "Der Modell-Server antwortet nicht unter $URL."
  echo "Starten mit:  sudo systemctl enable --now ollama"
  exit 1
fi
echo "Modell-Server erreichbar: $URL"

echo "Lade Modell $MODEL (das kann dauern) ..."
ollama pull "$MODEL"

echo "Kurzer Test ..."
start=$(date +%s)
reply=$(curl -fsS --max-time 300 "$URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Antworte mit einem Wort: Hallo\"}],\"max_tokens\":20,\"stream\":false}") || {
  echo "Der Test ist fehlgeschlagen. Läuft das Modell? Siehe: journalctl -u ollama -n 30" >&2
  exit 1
}
echo "Antwort nach $(( $(date +%s) - start )) s: $(printf '%s' "$reply" | head -c 200)"

echo
echo "Fertig. In PrintLab: Wartung → Assistent → einschalten, Modell \"$MODEL\" eintragen (falls abweichend)."
echo "Auf dem Pi sind Antworten langsam; die Zeitgrenze lässt sich dort einstellen."
