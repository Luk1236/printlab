# Signierte Updates und Absicherung des GitHub-Kontos

Das Update in PrintLab holt einen Release-Tag von GitHub und setzt den Programmordner darauf. Ohne weitere Prüfung genügt es,
das GitHub-Konto zu übernehmen, um Code auf dem Pi auszuführen. Mit der **Signaturprüfung** nimmt PrintLab nur Tags an, die du
mit deinem eigenen Schlüssel signiert hast. Der Schlüssel, dem der Pi vertraut, liegt **auf dem Pi** und nicht bei GitHub.

## Was geschützt wird, und was nicht

- Geschützt: ein übernommenes oder missbrauchtes GitHub-Konto, ein verschobener oder neu gesetzter Tag, ein Branch mit
  Tag-Namen, ein Tag ohne Signatur.
- Nicht geschützt: ein gestohlener **privater** Signaturschlüssel (deshalb mit Passphrase), und das erneute Einspielen einer
  älteren, echt signierten Version (ein „Rückwärts-Update").
- Das Update von **1.6.1 auf 1.6.3** läuft noch ohne Prüfung, weil die alte Version sie nicht kennt. Die Prüfung gilt ab dem
  Update danach.

## 1. Signaturschlüssel auf deinem PC erzeugen (einmalig)

In PowerShell oder Git Bash, **mit Passphrase** (die Eingabe fragt danach, nicht leer lassen):

```bash
ssh-keygen -t ed25519 -C "printlab-releases" -f ~/.ssh/printlab_signing
```

Es entstehen `printlab_signing` (privat, nie weitergeben, nie ins Repo) und `printlab_signing.pub` (öffentlich).

Im Projektordner einrichten (gilt nur für dieses Repo):

```bash
git config gpg.format ssh
git config user.signingkey ~/.ssh/printlab_signing.pub
```

## 2. Releases ab jetzt signiert erstellen

```bash
git tag -s v1.6.4 -m "PrintLab v1.6.4"
git push origin v1.6.4
```

`-s` signiert den Tag (die Passphrase wird abgefragt). Danach das Release wie gewohnt auf GitHub anlegen. Ein Tag mit `-a`
(nur beschriftet) oder ohne Option wird vom Pi abgelehnt.

Optional: den **öffentlichen** Schlüssel in GitHub unter Settings → SSH and GPG keys als „Signing Key" eintragen, dann zeigt
GitHub „Verified" an. Für den Pi ist das nicht nötig.

## 3. Den Schlüssel auf dem Pi hinterlegen

Erst **nachdem** ein signierter Tag existiert und der Pi auf 1.6.3 oder neuer ist.

**Variante A, ohne Neuinstallation** (in Pi Connect, eine Zeile; den Inhalt von `printlab_signing.pub` einsetzen):

```bash
echo 'printlab namespaces="git" ssh-ed25519 AAAA...hier-dein-oeffentlicher-schluessel... printlab-releases' > ~/printlab/data/update_allowed_signers
```

Der Pi braucht dazu `ssh-keygen` (`sudo apt install openssh-client`, auf Raspberry Pi OS meist schon da).

**Variante B, beim Neuaufspielen:**

```bash
export PRINTLAB_UPDATE_PUBKEY='ssh-ed25519 AAAA... printlab-releases'
curl -fsSL https://raw.githubusercontent.com/Luk1236/printlab/bambu-monitor-port/werkzeuge/pi_neu_installieren.sh | bash
```

Prüfen: In PrintLab unter Einstellungen → System steht „Updates werden nur mit gültiger Signatur eingespielt." Ein Update
auf einen unsignierten Tag endet mit „Update refused: the release is not signed by a trusted key", und nichts wird verändert.

## 4. Wenn etwas schiefgeht

- **Alle Updates werden abgelehnt:** Datei prüfen (`cat ~/printlab/data/update_allowed_signers`, eine Zeile mit
  `namespaces="git"` und dem Schlüssel), `ssh-keygen` vorhanden? Notausstieg: Datei löschen oder umbenennen, dann gilt wieder
  das alte Verhalten.
- **Schlüssel verloren oder gestohlen:** neuen erzeugen, Datei auf dem Pi ersetzen, ab dann mit dem neuen signieren. Der
  Pi vertraut nur dem, was in der Datei steht.
- Mehrere Schlüssel (zum Beispiel einer für einen zweiten PC): einfach weitere Zeilen in dieselbe Datei.

## 5. GitHub-Konto zusätzlich absichern

Das sind Einstellungen, die nur du setzen kannst:

1. **Zwei-Faktor-Anmeldung** einschalten, am besten mit **Passkey** oder Sicherheitsschlüssel statt SMS (Settings → Password
   and authentication).
2. **Alte Zugangstokens widerrufen** (Settings → Developer settings → Personal access tokens). Ein Token, das in einem Chat
   oder Terminal sichtbar war, gilt als verbrannt.
3. **Regelsatz für das Repo** (Settings → Rules → Rulesets): Branch `bambu-monitor-port` schützen (kein Force-Push, kein
   Löschen) und Tags `v*` schützen (nicht verschieben, nicht löschen).
4. **Anmeldungen und Sitzungen** gelegentlich prüfen (Settings → Sessions und Security log).
5. Keine fremden Apps und Aktionen mit Schreibrechten auf das Repo zulassen (Settings → Applications).
