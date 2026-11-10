# T1 Sicherheit: Authentifizierung, Rechte, Token, LDAP, OIDC, Middlewares

Stand: 2026-11-10, Branch `bambu-monitor-port`. Teil der gestaffelten Gesamtanalyse (Plan: Tranchen T1 bis T11).
Bestehende Übersicht ohne Tiefe: [GESAMTAUDIT-2026-11-07.md](../GESAMTAUDIT-2026-11-07.md).

## 0. Abdeckung (was wie gründlich geprüft wurde)

| Datei | Zeilen | Funktionen | Stufe |
|---|---:|---:|---|
| `backend/app/core/auth.py` | 2.525 | 84 | **A**: vollständig gelesen |
| `backend/app/main.py` (3 Middlewares, öffentliche Listen) | Z. 1.402 bis 1.901 | 5 (von 30 in der Datei) | **A**: vollständig gelesen |
| `backend/app/services/secret_codec.py` | 112 | 6 | **A**: vollständig gelesen |
| `backend/app/api/routes/auth.py` | 1.998 | 41 | **A** für `_get_client_ip`, `setup_auth`, `login`, `forgot_password`, `forgot_password_confirm`; **B** für den Rest |
| `backend/app/api/routes/mfa.py` | 2.321 | 50 | **A** für Pre-Auth-Token, Rate-Limit, TOTP-Replay, E-Mail-Auflösung, `oidc_authorize`, `oidc_callback`; **B** für den Rest (u. a. `verify_2fa`, TOTP-Einrichtung, Backup-Codes, Provider-CRUD, `oidc_exchange`) |
| `backend/app/services/ldap_service.py` | 595 | 17 | **A** für `_create_server`, `_start_tls_if_configured`, `authenticate_ldap_user`, `lookup_ldap_user`; **B** für den Rest |
| `backend/app/services/long_lived_tokens.py` | 243 | 9 | **B**: nur Kopf und Speicherformat gelesen |
| `backend/app/core/permissions.py` | 528 | 0 (Enum, 116 Werte) | **B**: nur gezählt, gegen die Allowlist in `core/auth.py` gestellt |

Das Inventar der T1-Dateien umfasst 237 Funktionen (Python-`ast`; die Summe enthält alle 30 Funktionen von `main.py`, die Zahl 5.159 für das ganze Backend ist gegengeprüft).
**Nicht** gelesen und deshalb hier nicht beurteilt: `verify_2fa`, `setup_totp`, `enable_totp`, `regenerate_backup_codes`,
`oidc_exchange`, `reset_user_password`, LDAP-Provisionierung, Langzeit-Token-Routen. Sie stehen als offene Punkte in Abschnitt 6.

Belegregel: Jeder Befund nennt `datei:zeile` und sagt, ob er **gelesen und logisch begründet** oder **per Gegenprobe bestätigt** ist.
Nichts davon wurde gegen eine laufende Instanz ausgenutzt.

## 1. High-Level-Überblick

- **Zweck:** Anmeldung (lokal, LDAP, OIDC), Sitzungs-Token (JWT), API-Schlüssel mit Bereichs-Flags, Rechteprüfung je Route,
  kurzlebige Zugriffstoken für Medien, Kamera und WebSocket, Zwei-Faktor, Passwort-Rücksetzung.
- **Muster:** FastAPI-Abhängigkeiten als Fabriken (`require_permission_if_auth_enabled(...)` liefert die eigentliche Prüffunktion),
  zusätzlich ein Gateway in `auth_middleware`. Zwei Verteidigungslinien: Gateway (Middleware) und Route (Abhängigkeit).
  Ein Struktur-Test (`backend/tests/unit/test_route_auth_coverage.py`) verlangt für jede Route eine Abhängigkeit, deren Name `require_`
  (oder einen der Namen `get_current_user`, `get_api_key`, `cloud_caller` u. ä.) enthält, oder einen Eintrag in einer begründeten Ausnahmeliste.
- **Sitzung:** HS256-JWT mit `exp`, `iat`, `jti`. Sperrliste über `auth_ephemeral_tokens` (`revoked_jti`). Frische über
  `password_changed_at` (`_is_token_fresh`).
- **API-Schlüssel:** `bb_…`, pbkdf2-Hash, Vorfilter über die ersten 8 Zeichen. **Allowlist** `_APIKEY_SCOPE_BY_PERMISSION`
  (nicht zugeordnet gleich verboten) und zusätzlich auf die Rechte des Besitzers eingeengt.
- **Abhängigkeiten:** PyJWT, passlib (pbkdf2_sha256), ldap3, httpx, pyotp, SQLAlchemy async.

## 2. Funktionsaufbau `core/auth.py` (alle 84 Funktionen, gruppiert)

Spalten: Zweck / Rückgabe / Nebenwirkung. „DB“ heißt Lesen oder Schreiben in der Datenbank.

### 2.1 API-Schlüssel-Rechte (Z. 324 bis 481)

| Funktion | Zweck | Rückgabe | Nebenwirkung |
|---|---|---|---|
| `_required_apikey_scopes(perm)` | Wandelt Rechte-Text in nötige Flags; `None` = nicht erlaubt | `tuple[str,...] \| None` | keine |
| `apikey_effective_permissions(key, owner)` | Alle Rechte, die der Schlüssel wirklich ausüben darf (Flags und Besitzerrechte) | sortierte Liste | keine |
| `resolve_apikey_owner(db, key)` | Besitzer laden; `user_id` leer gleich Altschlüssel, Besitzer weg oder inaktiv gleich 403 | `User \| None` | DB lesen |
| `authorize_api_key(db, key, perms, require_any)` | Besitzer auflösen, dann `_check_apikey_permissions` | `None` oder 403 | DB lesen |
| `_check_apikey_permissions(...)` | Allowlist, Flags, Besitzerrecht; leere Liste gleich 403 (fail-closed) | `None` oder 403 | keine |
| `require_api_key_scope(...)` | Enge Tür für einen Einzel-Flag (Energiepreis, App-Nachrichten); unterstützt JWT und Schlüssel | Abhängigkeit mit `ScopedCaller` | DB, öffnet eigene Sitzung |
| `require_energy_cost_update()`, `require_notification_send()` | Dünne Hüllen um die vorige | Abhängigkeit | keine |

### 2.2 Geheimnis und Einstellungen (Z. 613 bis 712)

| Funktion | Zweck | Rückgabe | Nebenwirkung |
|---|---|---|---|
| `_get_jwt_secret()` | Reihenfolge: Umgebung, Datei `.jwt_secret`, sonst neu erzeugen und speichern | `str` | Datei schreiben, `chmod` |
| `resolve_session_max_minutes(db)` | Sitzungsdauer aus Einstellungen, begrenzt auf 1 bis 720 Stunden | `int` | DB lesen |

### 2.3 Kurzlebige Token (Z. 715 bis 1048)

| Funktion | Zweck | Besonderheit |
|---|---|---|
| `create_slicer_download_token` / `verify_slicer_download_token` | 5 Minuten, an Ressource gebunden (`nonce` = `typ:id`); einmalig per `DELETE … RETURNING` oder wiederholbar | atomar; Bindung im `WHERE`, damit ein falscher Aufruf das Token nicht verbraucht |
| `create_camera_stream_token` / `verify_camera_stream_token` | 60 Minuten, anonym; Prüfung fällt auf Langzeit-Token zurück | Langzeit-Import erst zur Laufzeit |
| `verify_camwall_token`, `verify_overlay_token` | Nur Langzeit-Token mit passendem Bereich | bewusst enger als Kamera-Token |
| `create_websocket_token` / `verify_websocket_token` | 60 Minuten, trägt Benutzernamen | nicht verbraucht |
| `create_media_token` / `verify_media_token` | wie WebSocket, für Miniaturen und Symbole (#3025) | Token von API-Schlüsseln tragen `""` und werden später abgelehnt |

Alle `create_*` entfernen beim Anlegen abgelaufene Zeilen ihrer Art (Aufräumen nebenbei) und committen.

### 2.4 Passwort und JWT (Z. 1051 bis 1147)

| Funktion | Zweck | Rückgabe |
|---|---|---|
| `verify_password`, `get_password_hash` | pbkdf2_sha256 über passlib | `bool` / `str` |
| `create_access_token(data, expires_delta)` | JWT mit `exp`, `iat`, `jti` | `str` |
| `_is_token_fresh(iat, user)` | `iat` fehlt gleich abgelehnt; sonst `iat >= password_changed_at` (auf Sekunden gekürzt) | `bool` |
| `revoke_jti`, `is_jti_revoked` | Sperrliste schreiben (Doppeleintrag still ignoriert) bzw. lesen | `None` / `bool` |

### 2.5 Benutzer und Anmeldung (Z. 1150 bis 1285)

| Funktion | Zweck | Auffälligkeit |
|---|---|---|
| `get_user_by_username`, `get_user_by_email` | Groß-/Kleinschreibung egal, Gruppen vorgeladen | |
| `authenticate_user`, `authenticate_user_by_email` | Passwort prüfen; LDAP/OIDC-Benutzer werden abgewiesen | **fast identisch (DRY)**; Benutzer unbekannt gleich sofortige Rückkehr ohne Hash (siehe T1-07) |
| `is_auth_enabled(db)` | Liest `auth_enabled`; nur `True` wird 30 s gepuffert; DB-Fehler laufen durch (fail-closed) | Modul-Globals, kein Schutz bei mehreren Workern außer TTL |
| `invalidate_auth_enabled_cache()` | Puffer leeren | |
| `_user_from_api_key` | Besitzer oder `None` | Duplikat der Idee von `resolve_apikey_owner`, aber ohne 403 |
| `_validate_api_key(db, value)` | Vorfilter über 8 Zeichen (LIKE mit Escape), pbkdf2 gegen Kandidaten, Ablauf prüfen, `last_used` setzen und **committen**, Ergebnis in ContextVar | breiter `except` gibt `None` zurück (dokumentiert fail-closed) |

### 2.6 Abhängigkeiten für Routen (Z. 1338 bis 2525)

| Funktion | Verhalten |
|---|---|
| `get_current_user_optional` | kein Token gleich `None`; Token falsch/gesperrt gleich 401 |
| `get_current_user` | wie oben, aber **403** statt 401 bei inaktivem Benutzer (T1-15) |
| `get_current_active_user` | Alias |
| `require_auth_if_enabled` | Anmeldung aus gleich `None`; Schlüssel gültig gleich `None`; JWT gleich `User` |
| `require_role`, `RequireAdmin` | prüft `user.role` (kein Gruppen-Admin) |
| `require_admin_if_auth_enabled` | Schlüssel ausdrücklich 403; JWT und `user.is_admin` (Rolle oder Gruppe) |
| `generate_api_key`, `get_api_key` | Schlüssel erzeugen (`bb_` plus 32 Byte); `get_api_key` prüft Header, Ablauf, setzt `last_used` (**Duplikat** von `_validate_api_key`) |
| `caller_is_api_key`, `validated_api_key_from_request`, `current_api_key_if_present` | Schlüssel-Erkennung; Cache über ContextVar |
| `check_permission`, `check_webhook_permission`, `check_printer_access` | alte Webhook-Flags, Besitzerprüfung, Drucker-Freigabeliste (`None` = alle, `[]` = keiner) |
| `require_printer_permission_if_auth_enabled` | Recht plus Drucker-Freigabeliste (siehe T1-12) |
| `require_permission` | alle Rechte, Anmeldung zwingend |
| `require_permission_if_auth_enabled` | wie oben, bei ausgeschalteter Anmeldung `None` |
| `probe_permissions_if_auth_enabled` | wandelt 403 in `False`, 401 bleibt |
| `require_any_permission_if_auth_enabled` | mindestens ein Recht |
| `require_ownership_permission` | `(user, kann_alles)`; Schlüssel gelten als „alles“ nach Prüfung des ALL-Rechts |
| `require_camera_stream_token_*`, `require_camwall_token_*`, `require_overlay_token_*` | Token per Query-Parameter, nur wenn Anmeldung an |
| `_user_from_media_token`, `require_media_token_permission`, `…_ownership`, `…_printer_permission` | Medien-Token als zusätzlicher Weg neben Kopfzeilen |
| `RequirePermission`, `RequirePermissionIfAuthEnabled`, … | dünne `Depends(...)`-Hüllen |

**Datenfluss einer geschützten Route:** Browser sendet `Authorization: Bearer <JWT>` oder `X-API-Key`. Gateway (`auth_middleware`)
prüft JWT vollständig, Schlüssel nur auf Vorhandensein. Danach öffnet die Abhängigkeit **eine eigene** DB-Sitzung und prüft das JWT
**erneut** (Signatur, Sperrliste, Benutzer, Frische, Recht). Erst dann läuft der Handler.

## 3. Gateway und Header (`main.py`)

| Teil | Funktion |
|---|---|
| `security_headers_middleware` (Z. 1590) | Nonce je Anfrage, `nosniff`, `X-Frame-Options` (nur ohne vertrauenswürdige Rahmen-Herkünfte), `Referrer-Policy`, `Permissions-Policy`, CSP in vier Varianten (API-Doku, STEP-Worker, PDF-Worker, Standard), HSTS nur bei `https` |
| `auth_middleware` (Z. 1719) | nur `/api/`; öffentliche Routen, Präfixe, Muster; Fork-Sperre `fork_startup.auth_gate`; Anmeldestatus fail-closed (503); Schlüssel durchwinken; sonst JWT prüfen (Sperrliste, Benutzer aktiv, Frische) |
| `trace_id_middleware` (Z. 1855) | Trace-ID aus Whitelist-geprüfter Kopfzeile oder neu, in ContextVar und Antwort |
| `PUBLIC_API_ROUTES/PREFIXES/PATTERNS` (Z. 1402 bis 1470) | Ausnahmen vom Gateway; **Muster werden per Teilzeichenfolge verglichen** (`pattern in path`) |

## 4. Befunde

Schweregrad: **M** mittel, **N** niedrig, **I** Hinweis. Beleg: **gelesen** = im Code nachvollzogen; **Gegenprobe** = zusätzlich durch Suche oder Test gestützt.

| Nr. | Grad | Befund | Beleg |
|---|:---:|---|---|
| T1-01 | M | **Gateway winkt jeden API-Schlüssel ohne Prüfung durch.** Ein beliebiger Header `X-API-Key: x` oder `Bearer bb_x` überspringt in `auth_middleware` die gesamte Prüfung (`main.py:1780-1783`). Die Sicherheit hängt dann allein an der Abhängigkeit der jeweiligen Route. Der Struktur-Test prüft nur, dass der **Name** einer Abhängigkeit `require_` enthält, nicht ihr Verhalten. Das widerspricht dem Docstring „Defense-in-Depth … unabhängig von Routen-Abhängigkeiten“. | gelesen, Gegenprobe (Testquelle) |
| T1-02 | M | **LDAP-TLS ohne Zertifikatsprüfung, sobald keine CA-Datei gesetzt ist** (`ldap_service.py:97-100`, `Tls(validate=ssl.CERT_NONE)`). Der Docstring sagt „Always uses TLS“, tatsächlich kann ein Mann in der Mitte Benutzer- und Dienstkonto-Passwörter lesen. Standard-Sicherheit ist `starttls`. | gelesen |
| T1-03 | M | **LDAP blockiert die Ereignisschleife.** `authenticate_ldap_user` ist synchron (ldap3) und wird im Async-Handler direkt aufgerufen (`routes/auth.py:504`); weder dort noch im Dienst gibt es `to_thread`. Bei langsamem Verzeichnis stehen alle Anfragen bis zu `connect_timeout=10` s plus Bind-Zeit. | gelesen, Gegenprobe (`grep to_thread` leer) |
| T1-04 | M | **OIDC-Login-CSRF: `state` ist nicht an den Browser gebunden.** `oidc_authorize` ist öffentlich und setzt kein Cookie (`mfa.py:1731-1748`); `oidc_callback` löst `state` nur per `DELETE … RETURNING` ein (`mfa.py:1789-1808`). Ein Angreifer startet den Ablauf, meldet sich beim IdP an und schickt dem Opfer die Rückruf-URL; das Opfer landet in der Sitzung des Angreifers. Für die 2FA-Challenge gibt es die Cookie-Bindung bereits (`routes/auth.py:610-623`). | gelesen (nicht praktisch reproduziert) |
| T1-05 | M (Konfiguration) | **Automatisches Verknüpfen über benutzerbearbeitbare Ansprüche.** Der Schutz `_enforce_auto_link_safety` hält „Fall C“ (eigener `email_claim`, z. B. `preferred_username`) für sicher, weil dort kein `email_verified` geprüft wird (`mfa.py:461-473`, `501-506`). Bei IdPs, in denen der Benutzer diesen Anspruch selbst ändern darf, kann eine passende E-Mail-Form die Verknüpfung mit einem lokalen Konto auslösen. | gelesen |
| T1-06 | N | **Erfolgreicher Login setzt den IP-Zähler zurück** (`routes/auth.py:585-586`). Wer ein eigenes Konto hat, kann zwischen Rate-Limit-Treffern einen gültigen Login einstreuen und die 20-pro-15-Minuten-Grenze gegen andere Konten aushebeln. | gelesen |
| T1-07 | N | **Benutzer-Aufzählung per Antwortzeit.** Ist der Benutzer unbekannt, kehrt `authenticate_user` ohne pbkdf2 zurück (`core/auth.py:1172-1174`); bei bekanntem Benutzer läuft der Hash. | gelesen |
| T1-08 | N | **Zeitunterschied bei `forgot-password`**: für vorhandene Benutzer werden Token, Vorlage und mehrere DB-Zugriffe **vor** der Antwort erledigt (`routes/auth.py:1156-1202`), für unbekannte nicht. Der Kommentar „L-R9-B“ deckt nur den E-Mail-Versand ab. | gelesen |
| T1-09 | N | **LDAP-Login prüft `is_active` nicht** (`routes/auth.py:507-529`); ein deaktivierter LDAP-Benutzer bekommt ein Token (oder eine Pre-Auth-Challenge). Es bleibt wirkungslos, weil jede spätere Abhängigkeit `is_active` prüft, ist aber inkonsistent zum lokalen Pfad (`core/auth.py:1179`). | gelesen |
| T1-10 | N | **JWT-Geheimnis**: Datei wird mit Standardrechten geschrieben und erst danach auf `0600` gesetzt (`core/auth.py:660-662`, kurzes Zeitfenster); ein Wert aus `JWT_SECRET_KEY` wird ohne Mindestlänge akzeptiert (`:631-634`), während die Datei 32 Zeichen verlangt (`:645`). | gelesen |
| T1-11 | N | **Doppelter Code für API-Schlüssel**: `get_api_key` (`:1645-1700`) und `_validate_api_key` (`:1297-1335`) machen dasselbe mit unterschiedlichen Fehlerarten; `get_api_key` nutzt den Request-Cache nicht. | gelesen |
| T1-12 | N | **Fehlverhalten bei ausgeschalteter Anmeldung**: Auf Drucker-Routen ruft `checker` nach dem Rechte-Check `validated_api_key_from_request` immer auf (`:1846-1849`, Medien-Variante `:2519-2523`). Mit ausgeschalteter Anmeldung und einem veralteten `X-API-Key`-Header kommt dort 401, auf allen anderen Routen 200. | gelesen |
| T1-13 | N | **CSP weit offen**: `connect-src … ws: wss:` erlaubt WebSocket-Verbindungen zu beliebigen Hosts, `frame-src 'self' http: https:` beliebige Rahmen (`main.py:1707`, `1711`). Bei einer XSS-Lücke wäre das ein Abflusskanal. Gegenprobe vor Änderung: Browser-Verhalten von `'self'` für `ws:` auf Safari prüfen. | gelesen |
| T1-14 | I | **Kurzlebige Token liegen im Klartext in der DB** (WebSocket, Medien, Kamera; `core/auth.py:843-1048`), Langzeit-Token dagegen gehasht (`long_lived_tokens.py:9-10`). Wer die DB liest, kann aktive Medien-/Kamera-Token nutzen (bis 60 Minuten). | gelesen |
| T1-15 | I | **Uneinheitliche Fehlercodes**: `get_current_user` gibt für inaktive Benutzer 403 (`:1412-1416`), alle anderen Wege 401. | gelesen |
| T1-16 | N | **Doppelte Arbeit je Anfrage**: Gateway und Abhängigkeit laden beide Benutzer, Sperrliste und Gruppen (je eigene Sitzung); jeder API-Schlüssel-Aufruf schreibt `last_used` und committet (`:1329-1330`); `check_rate_limit` lädt alle Ereignisse und zählt in Python (`mfa.py:352-359`). | gelesen |
| T1-17 | N | **Breiter `except` im Gateway** (`main.py:1844`: `(jwt.InvalidTokenError, ValueError, Exception)`) meldet auch DB-Fehler als 401 „Invalid token“ statt 503. | gelesen |
| T1-18 | N | **OIDC über `http://` erlaubt**: Token-Endpunkt wird nur auf `http(s)` geprüft (`mfa.py:1835`); `client_secret` und Code gehen dann im Klartext, und ein manipuliertes Entdeckungsdokument kann das Secret an einen beliebigen Host schicken. | gelesen |

### 4.1 Geprüft, kein Befund (damit niemand es noch einmal prüft)

- **Rate-Limit-Umgehung durch Groß-/Kleinschreibung:** vermutet, widerlegt: `check_rate_limit`, `record_failed_attempt`, `clear_failed_attempts` setzen `username.lower()` (`mfa.py:349`, `369`, `377`).
- **Passwort-Regeln bei Rücksetzung:** erzwungen im Schema (`schemas/auth.py:161-168`).
- **Einmal-Token:** Pre-Auth, OIDC-State, OIDC-Austausch, Download-Token sind atomar (`DELETE … RETURNING`).
- **Ausfallsicherheit:** `is_auth_enabled` lässt DB-Fehler durch, die Middleware antwortet 503 (kein stilles „Anmeldung aus“).
- **API-Schlüssel:** Allowlist statt Sperrliste, Besitzerbeschränkung, leere Rechteliste gleich 403.
- **OIDC:** PKCE (S256), Nonce zwingend, Austausch-Token im URL-Fragment, `email_verified` je Fall sauber getrennt, `exp`/`aud` durch PyJWT geprüft.
- **Rücksetzung:** Token einmalig, im Fragment, löscht frühere Token, `password_changed_at` macht alte JWT ungültig, LDAP/OIDC-Benutzer ausgeschlossen.
- **`secret_codec.py`:** Fernet, Schlüsseldatei atomar über `tmp`/`replace`, keine stille Klartext-Rückgabe für `enc:`-Werte. Anmerkung: Rechte werden unter Windows nicht gesetzt (dokumentiert).

### 4.2 Wartbarkeit (Zahlen)

| Kennzahl | Wert |
|---|---|
| Vollständige Kopien der JWT-Prüfung (Signatur, `sub`, `jti`, Sperrliste, Benutzer, Frische) | **11** (`core/auth.py` 9, `routes/auth.py:736` 1, `main.py:1806` 1); dazu 2 Teilkopien nur zum Auslesen von `jti`/`exp` (Logout `routes/auth.py:800`, Passwortänderung `routes/users.py:587`). `mfa.py:1924` prüft ein OIDC-ID-Token und zählt nicht mit. |
| Kopien der Token-Ausgabe (`create_*_token`) | 4 (Slicer, Kamera, WebSocket, Medien) |
| `login` | 193 Zeilen, Komplexität 32 |
| `oidc_callback` | 410 Zeilen, Komplexität 62, 9 breite `except` |
| `setup_auth` | 140 Zeilen, Komplexität 25 |
| breite `except` in T1-Dateien | 40, stille `pass`: 0 |
| Funktionen ohne Docstring | 28 von 237 |

## 5. Refactoring-Vorschläge (nicht angewendet)

Alle Blöcke sind auf Syntax geprüft (`py_compile`). Sie laufen **nicht** gegen die vorhandenen Tests; vor Umsetzung gehört jede Änderung
in einen eigenen Commit mit Testlauf (`test_auth_api.py`, `test_auth_apikey_rbac.py`, `test_route_auth_coverage.py`).

### 5.1 Eine einzige JWT-Prüfung (löst T1-15, T1-17, den Großteil von 4.2)

```python
async def resolve_jwt_user(db: AsyncSession, token: str) -> User:
    """Die einzige Stelle, die ein Sitzungs-JWT prüft. Wirft immer dieselbe 401-Antwort.

    Prüft: Signatur und Pflichtfelder, Sperrliste, Benutzer aktiv, Token nicht älter als die letzte Passwortänderung.
    """
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub", "jti"]},  # fehlende Felder gleich abgelehnt
        )
    except JWTError as exc:
        raise _credentials_error() from exc
    if await is_jti_revoked(payload["jti"], db):
        raise _credentials_error()
    user = await get_user_by_username(db, payload["sub"])
    if user is None or not user.is_active or not _is_token_fresh(payload["iat"], user):
        raise _credentials_error()
    return user


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass(frozen=True)
class Principal:
    """Wer ruft auf: ein Benutzer, ein API-Schlüssel oder niemand (Anmeldung aus)."""

    user: User | None = None
    api_key: APIKey | None = None


async def authenticate(db: AsyncSession, credentials, x_api_key: str | None) -> Principal:
    """Löst Kopfzeilen in einen Principal auf. Wirft 401 bei fehlenden oder falschen Zugangsdaten."""
    candidate = x_api_key or (credentials.credentials if credentials and credentials.credentials.startswith("bb_") else None)
    if candidate:
        api_key = await _validate_api_key(db, candidate)
        if api_key is None:
            raise _credentials_error()
        return Principal(api_key=api_key)
    if credentials is None:
        raise _credentials_error()
    return Principal(user=await resolve_jwt_user(db, credentials.credentials))
```

Eine Abhängigkeit schrumpft damit von rund 90 auf etwa 15 Zeilen:

```python
def require_permission_if_auth_enabled(*permissions: str | Permission):
    perm_strings = [p.value if isinstance(p, Permission) else p for p in permissions]

    async def permission_checker(credentials=Depends(security), x_api_key=Header(default=None, alias="X-API-Key")):
        async with async_session() as db:
            if not await is_auth_enabled(db):
                return None
            who = await authenticate(db, credentials, x_api_key)
            if who.api_key is not None:
                await authorize_api_key(db, who.api_key, perm_strings)
                return None  # Schlüssel liefern bewusst keinen Benutzer
            if not who.user.has_all_permissions(*perm_strings):
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing required permissions: {', '.join(perm_strings)}")
            return who.user

    return permission_checker
```

Mehrwert: eine Stelle für Fehlerarten, Pflichtfelder und Sperrliste; ein Fehler (z. B. fehlende Frische-Prüfung) kann nicht mehr in nur
einer der 11 Kopien stecken.

### 5.2 Gateway prüft den Schlüssel wirklich (löst T1-01)

```python
    if x_api_key or (auth_header and auth_header.startswith("Bearer bb_")):
        from backend.app.core.auth import _validate_api_key

        candidate = x_api_key or auth_header.removeprefix("Bearer ").strip()
        async with async_session() as db:
            if await _validate_api_key(db, candidate) is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid API key"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)
```

Kosten: ein pbkdf2-Vergleich mehr je Schlüssel-Anfrage, außer der Cache aus `_validated_api_key` greift. Vor der Umsetzung messen. Zusätzlich
`PUBLIC_API_PATTERNS` von Teilzeichenfolgen auf verankerte Muster umstellen:

```python
import re

_PUBLIC_API_PATTERNS = [
    re.compile(r"^/api/v1/(archives|library/files)/\d+/thumbnail$"),
    re.compile(r"^/api/v1/printers/\d+/camera/(stream|snapshot)$"),
    re.compile(r"^/api/v1/(archives|library/files)/\d+/dl/[^/]+/[^/]+$"),
]


def _is_public_pattern(path: str) -> bool:
    return any(p.match(path) for p in _PUBLIC_API_PATTERNS)
```

### 5.3 Zeitgleiche Antwort bei unbekanntem Benutzer (löst T1-07)

```python
# einmal beim Import: ein gültiger Hash, gegen den bei unbekanntem Benutzer verglichen wird
_DUMMY_HASH = pwd_context.hash("timing-dummy-not-a-real-password")


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    user = await get_user_by_username(db, username)
    local = user is not None and user.password_hash and getattr(user, "auth_source", "local") not in ("ldap", "oidc")
    # Immer genau ein Hash-Vergleich, egal ob der Benutzer existiert.
    password_ok = verify_password(password, user.password_hash if local else _DUMMY_HASH)
    if not (local and password_ok and user.is_active):
        return None
    return user
```

`authenticate_user_by_email` ruft dieselbe Kernfunktion mit `get_user_by_email` auf (löst auch das DRY-Problem).

### 5.4 JWT-Geheimnis ohne Rechte-Fenster (löst T1-10)

```python
def _write_secret_file(path: Path, secret: str) -> None:
    """Legt die Datei von Anfang an mit 0600 an; schlägt fehl, wenn sie schon existiert (kein Überschreiben)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(secret)


MIN_SECRET_LENGTH = 32

env_secret = os.environ.get("JWT_SECRET_KEY", "")
if env_secret and len(env_secret) < MIN_SECRET_LENGTH:
    raise RuntimeError("JWT_SECRET_KEY ist kürzer als 32 Zeichen; bitte ein längeres Geheimnis setzen.")
```

### 5.5 LDAP: Zertifikate prüfen und nicht blockieren (löst T1-02, T1-03)

```python
def _build_tls(config: LDAPConfig) -> Tls:
    """Zertifikat wird immer geprüft; Abschalten nur ausdrücklich und mit Warnung im Log."""
    if config.ca_cert_path:
        return Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=config.ca_cert_path)
    if config.skip_cert_verification:  # neue, bewusst benannte Einstellung, Standard: False
        logger.warning("LDAP: Zertifikatsprüfung ist abgeschaltet (skip_cert_verification)")
        return Tls(validate=ssl.CERT_NONE)
    return Tls(validate=ssl.CERT_REQUIRED)  # Systemzertifikate
```

```python
# routes/auth.py, statt des direkten Aufrufs in Zeile 504:
ldap_user = await asyncio.to_thread(authenticate_ldap_user, ldap_config, request.username, request.password)
```

Hinweis: Wie ldap3 bei `CERT_REQUIRED` ohne `ca_certs_file` die Systemzertifikate lädt, vor der Umsetzung auf Windows und Pi testen.

### 5.6 OIDC-State an den Browser binden (löst T1-04)

```python
# oidc_authorize: Antwort bekommt ein Cookie mit einem zweiten Wert, der in der DB neben dem State liegt
browser_binding = secrets.token_urlsafe(32)
db.add(AuthEphemeralToken(token=state, token_type=TokenType.OIDC_STATE, provider_id=provider_id,
                          nonce=nonce, code_verifier=code_verifier, challenge_id=browser_binding,
                          expires_at=now + OIDC_STATE_TTL))
response.set_cookie("oidc_binding", browser_binding, httponly=True, secure=raw_request.url.scheme == "https",
                    samesite="lax", max_age=600, path="/api/v1/auth/oidc")

# oidc_callback: beim Einlösen zusätzlich prüfen, genau wie consume_pre_auth_token
if stored_challenge_id != request.cookies.get("oidc_binding"):
    return RedirectResponse(url=f"{frontend_error_url}invalid_state", status_code=302)
```

Die Spalte `challenge_id` existiert bereits im Modell `AuthEphemeralToken` (wird für Pre-Auth genutzt), eine Migration ist nicht nötig.
`SameSite=Lax` genügt, weil der Rückruf eine Top-Level-Navigation ist.

### 5.7 Kleinere Korrekturen

- **T1-06:** IP-Zähler bei Erfolg **nicht** löschen (nur den Benutzerzähler); die Ereignisse verfallen im Fenster von selbst.
- **T1-08:** Für bekannte und unbekannte E-Mails dieselbe Arbeit vor der Antwort (Token erzeugen und Vorlage rendern, aber nur bei echten Benutzern senden), oder die gesamte Arbeit in den `BackgroundTask` verlegen.
- **T1-09:** In `login` nach der LDAP-Auflösung `if user and not user.is_active: user = None` einfügen.
- **T1-12:** `validated_api_key_from_request` nur aufrufen, wenn der Rechte-Check ein Schlüssel-Ergebnis geliefert hat (z. B. über `Principal`), nicht blind aus den Kopfzeilen.
- **T1-16:** `check_rate_limit` mit `select(func.count())` statt `scalars().all()`; `last_used` höchstens einmal je Minute schreiben.
- **T1-17:** `except (jwt.InvalidTokenError, ValueError):` und DB-Fehler getrennt mit 503 beantworten.
- **T1-18:** `http://` für Token-Endpunkt und JWKS nur zulassen, wenn der Anbieter selbst mit `http://` konfiguriert wurde, sonst ablehnen; zusätzlich den Host des Entdeckungsdokuments mit dem Host der konfigurierten Aussteller-URL vergleichen.
- **Zerlegung:** `login` in `_try_ldap`, `_local_login_allowed`, `_issue_2fa_challenge`, `_issue_session`; `oidc_callback` in `_discover`, `_exchange_code`, `_validate_id_token`, `_resolve_or_create_user`, `_issue_exchange_token`.

## 6. Offene Punkte aus T1

1. Nicht gelesene Funktionen (Abschnitt 0) in einer Folgesitzung nachholen, zuerst `verify_2fa` (140 Zeilen, Komplexität 23) und `oidc_exchange`.
2. T1-01 und T1-04 gegen eine laufende Test-Instanz **praktisch** nachstellen, bevor sie als bestätigte Schwachstellen gelten.
3. Wie viele Routen enthalten `PUBLIC_API_PATTERNS`-Teilzeichenfolgen in ihrem Pfad, ohne selbst eine Abhängigkeit mit echter Prüfung zu haben? Das beantwortet T11 mit einem Skript über `app.routes`.
4. Aufbewahrung der Tabelle `auth_rate_limit_events` (wird sie je gelöscht?): in T3 (Datenbank) klären.

Die Entscheidung über die Umsetzung von 5.1 bis 5.7 liegt beim Auftraggeber; nichts davon ist im Code angewendet.
