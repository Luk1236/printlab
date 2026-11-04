# GitHub-Absicherung für `Luk1236/printlab`

Stand: 04.11.2026 · Gilt für das öffentliche Repo <https://github.com/Luk1236/printlab> (Branch `bambu-monitor-port`).
Alle Schritte brauchen Zugriff auf das GitHub-Konto — das Skript und die CI können sie nicht abnehmen.

## Warum

Das Repo ist öffentlich, der Workflow „Release gate" und „Release (Docker-Image)" laufen mit Schreibrechten,
der signierte Tag startet die Veröffentlichung. Wer das Konto oder einen alten Token übernimmt, kann Releases
manipulieren oder das Konto löschen. Die folgenden Einstellungen verkleinern die Angriffsfläche auf das,
was nötig ist. Dauer gesamt: etwa 15 Minuten.

## 1. Konto sichern (Settings → Password and authentication)

1. **Zwei-Faktor einschalten**, bevorzugt **Passkey** (FIDO2, USB-Stick oder Plattform-Authenticator);
   als Fallsicherung mindestens einen Wiederherstellungscode sicher aufbewahren (nicht im selben Ordner).
2. **Neue „Codes" prüfen:** unter „Recovery codes" ggf. neu erzeugen, alte ungültig machen.

## 2. Alte Tokens und Apps widerrufen

1. **Settings → Developer settings → Personal access tokens** — jeden Token ansehen:
   Wofür war er? Letzte Nutzung? Wenn nicht mehr nötig: **Delete**. Nicht mehr benutzte *classic* Tokens
   durch *fine-grained* ersetzen (nur `contents: write` für printlab, nur dieses Repo, kurze Laufzeit).
2. **Settings → Applications → Installed GitHub Apps** und **Authorized OAuth Apps**: alles Unbekannte entfernen.

## 3. Actions-Standard härten (Settings → Actions → General)

1. **Actions permissions:** „Allow all actions and reusable workflows" reicht; fork-basierte Pull-Requests
   vom Publikum brauchen keine Approvals, weil es am Projekt keine Fork-Beitrags-Logik gibt — trotzdem:
   „Require approval for all external contributors" wählen.
2. **Workflow permissions:** „Read repository contents and packages permissions" als Voreinstellung.
   Die beiden Release-Workflows haben `permissions: contents: write` fest im Kopf (bewusst, minimiert) — ändern.
3. **„Allow GitHub Actions to create and approve pull requests": aus.**

## 4. Branch schützen (Settings → Rules → Rulesets)

Regelsatz **„main line"**:

- **Target:** Branch `bambu-monitor-port`
- **Restrict deletions:** an (Branch kann nicht gelöscht werden)
- **Block force pushes:** an (History bleibt unveränderlich)
- **Require signed commits:** **auslassen** — der Pi-Push und Tooling sind nicht alle SSH-signiert;
   für Tags reicht der signierte Tag des Release-Skripts.
- **Status checks:** optional `CI` und `CodeQL` verlangen, **erst nach grüner CI einrichten** — solange
   lokal entwickelt wird, bremsen sie den Alltag. Vorher eher nicht einschalten.

Regelsatz **„release tags"**:

- **Target:** Tag-Pattern `v*`
- **Restrict creations:** an, erlaubt für `Luk1236` allein (sonst kann eine CI-Runtime einen Tag bauen).
- **Restrict deletions:** an.
- **Block force pushes:** an — ein Tag, der einmal veröffentlicht war, wird nie überschrieben.
   Nur mit `--force` am `release.py` bewusst ausnehmen.

## 5. Secret-Scanning einschalten (Settings → Code security)

- **Secret scanning + Push protection:** an (kostenlos für öffentliche Repos; verhindert, dass versehentlich
  committete Schlüssel gepusht werden).
- **Dependabot alerts / CodeQL / Security Audit:** sind an (läuft bereits für die v2.0.9).

## 6. Inventur prüfen (Settings → Repository)

- **Collaborators:** niemand außer `Luk1236` mit Admin.
- **Deploy keys / SSH keys** (Settings → Deploy keys): nur die, die bekannt sind; nicht genutzte löschen.
- **Webhooks** (Settings → Webhooks): jede fremde URL entfernen — ein fremder Webhook bekommt bei jedem
  Push die volle Push-Nutzlast.
- **Secrets and variables → Actions:** nur die nötigen; jedes Secret einmal drehen, wenn es „alt" ist
  (Letzter Stand: Registry/Docker-Publish-Zugang).

## 7. Kontrolle am Ende

- Den Regelsatz „release tags" testen: `git push origin :refs/tags/v2.0.9` **muss abgelehnt werden**.
- `git push -f` auf den Branch **muss abgelehnt werden**.
- `git tag -v v2.0.9` lokal sagt „Good „git" signature" (Einrichtung: `docs/VERSIONING.md`).

## Abbruchkriterium / Fertig

Alle sechs Abschnitte sind an der Konto-Oberfläche umgesetzt, die drei Kontrollen im Abschnitt 7 sind durch.
Der Punkt in `TODO.md` („GitHub-Konto absichern") kann dann auf `[x]` stehen.