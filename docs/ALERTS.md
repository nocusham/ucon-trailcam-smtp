# Fehlerbenachrichtigung / Health alerts

**Entwicklungsstand:** optionaler Alarmkanal, SQLite-Zustandslogik und manueller SMTP-Test sind implementiert. Die automatische Beobachtung und Ausführung durch den späteren Dauerbetrieb sind noch nicht angeschlossen. Keine regelmäßigen Kameraverbindungen, automatischen Alarmmails oder Anmeldeversuche werden durch diese Änderung aktiviert.

## Konfiguration

Siehe den vollständig kommentierten Abschnitt [alerts] und [alerts.smtp] in [config.example.toml](../config.example.toml). Bei bestehenden Installationen nur diesen Abschnitt übernehmen; die Kameraeinstellungen bleiben unverändert. Ohne den Abschnitt oder bei enabled=false ist der Alarmkanal deaktiviert. Der private SMTP-Account hat eigenen Server, Port, Benutzer, Passwortverweis und Empfänger. Ein unabhängiger Anbieter ist sinnvoll, damit eine Störung des Bild-SMTP-Servers nicht gleichzeitig den Alarmkanal ausschaltet. Fehlerberichte sind reine Textmails ohne Bildanhänge. Nur STARTTLS oder TLS mit Zertifikatsprüfung; Revierwelt-Ziele werden für Alarme abgelehnt. Passwort wie bisher in .env, z.B. ALERT_SMTP_PASSWORD. Keine Passwörter oder Rohantworten in Alarmtexten.

| Kategorie | Standard | Voraussetzung |
| --- | --- | --- |
| Login | 15 min | Wiederholte fehlgeschlagene Prüfungen über die Frist; bestätigter Login-Code 20005 darf auch ohne weitere Anmeldung alarmieren |
| API | 30 min | Tatsächliche wiederholte API-Fehler über die Frist |
| Originaldownload | 24 h | Wiederholte fehlgeschlagene SD-Originaldownloadversuche für bekannte, noch ausstehende Cloud-Ereignisse derselben UID über die Frist |
| Wiederholungsmeldung | 24 h | Störung besteht laut letztem Prüfergebnis fort |
| Alarm-SMTP-Wiederholung | 60 min | Vorheriger Alarmversuch fehlgeschlagen |
| Entwarnung | Aktiv | Erfolgreiche Prüfung nach zuvor bestätigter Alarmannahme |

Die Frist beginnt mit dem ersten beobachteten Fehler. Für normale Störungen sind mindestens zwei fehlgeschlagene Prüfungen erforderlich, deren Zeitabstand die Frist erreicht. Eine einzelne fehlgeschlagene Prüfung wird nicht allein durch Zeitablauf zum bestätigten Ausfall. Code 20005 wurde bei falschem Passwort beobachtet; später muss der Dienst das Login gezielt sperren und bei korrigierten Zugangsdaten wieder freigeben. Diese Login-Sperre ist noch nicht implementiert.

Fehlende PIR-Ereignisse sind kein Erreichbarkeitsnachweis. Es sind ausdrücklich keine zusätzlichen aktiven Erreichbarkeitsprüfungen vorgesehen. Die spätere Download-Verarbeitung meldet kamerabezogene Störungen nur bei konkreten, fehlgeschlagenen Abrufversuchen eines bekannten ausstehenden Cloud-Ereignisses. Auch ein fehlendes SD-Original kann einen Downloadfehler verursachen, ohne dass die Kamera offline ist. Lokale Dateisystem- oder SMTP-Fehler sind keine Kameraverbindungsfehler. Ein Erfolg für ein anderes Ereignis darf ein weiterhin fehlendes Original nicht stillschweigend als erledigt behandeln; Entwarnung erst nach Auflösung des betroffenen Rückstands. Während einer globalen Cloud-Störung keine neuen kamerabezogenen Ausfälle aus nicht ausgeführten Kameraprüfungen ableiten. Die Zuordnung zu konkreten Ereignissen, Retry-Planung und Entwarnungsbedingungen müssen noch im Dauerbetrieb implementiert werden.

## Letzter Kamerakontakt und optionale Inaktivität

Am 26.11.2026 bestätigte die authentifizierte Ucon-Geräteabfrage /api/v2/user/device_list an der H4 das Feld `dynamic_info.latest_active_utc` (Integer). Ebenfalls vorhanden: online_state (String), battery und signal (Integer), is_battery_charging und is_low_power (Boolean). Der anschließende Live-Test bestätigte einen plausiblen Unix-Zeitstempel in Sekunden (UTC), der nach einer neuen PIR-Auslösung bei geschlossener App und ohne clientseitige P4P-Sitzung aktualisiert wurde. Der neue Aktivitätszeitpunkt lag zehn Sekunden nach dem gemeldeten Fotoereignis. Vorher war ein Aktivitätszeitpunkt innerhalb eines erfolgreich abgefragten Zeitfensters ohne Fotoereignisse vorhanden. Das deutet auf weitere Arten von Aktivität hin, beweist aber keine regelmäßigen Heartbeats. Die Statuswerte können zwischengespeichert sein; Aktualisierungsverhalten ohne PIR und langfristige Zuverlässigkeit bleiben offen. Nur ausgewählte Telemetriewerte ausgeben, niemals die gesamte Geräteantwort mit Zugangsdaten, SIM-Kennungen oder Standortinformationen.

`et_utc` bleibt der Fotoereigniszeitpunkt. Für die H4 soll die spätere optionale Inaktivitätswarnung primär latest_active_utc verwenden (sieben Tage ohne gemeldete Aktivität). Bei Modellen ohne dieses Feld sind sieben Tage ohne neue Cloud-Fotoereignisse der vorgesehene Rückfall; ein vorübergehend fehlender oder ungültiger Zeitwert allein soll keinen Quellenwechsel auslösen. Eine Warnung beschreibt ausbleibende gemeldete Aktivität, nicht einen nachgewiesenen Offline-Zustand. Standardmäßig deaktiviert, pro Kamera konfigurierbar. Keine zusätzlichen aktiven Erreichbarkeitsprüfungen. Warnungen nur bei erfolgreichen, hinreichend vollständigen und aktuellen Cloud-Abfragen; bei unbekannter Historie, ungültigen oder fehlenden Zeitwerten sowie API-Ausfällen keine unbegründete Offline-Meldung. Der 24-Stunden-Alarm für wiederholt fehlgeschlagene Originaldownloads bleibt davon unabhängig. Die Inaktivitätslogik ist noch nicht implementiert.

## Manueller Test (kein Zugriff auf Kamera oder Cloud)

```sh
python health_alerts.py --config config.local.toml
# Nur wenn enabled=true und private SMTP-Zugangsdaten eingerichtet sind:
python health_alerts.py --config config.local.toml --send-test
```

Der erste Aufruf validiert nur die Alarmkonfiguration. Der zweite sendet genau eine ausdrücklich als Test markierte E-Mail, ohne SQLite-Zustände zu ändern. Keine Testmeldung an Revierwelt.

## Persistenz und Integration

health_incidents speichert in SQLite den Schlüssel (Kategorie, Scope), erste/letzte Fehlerzeit, Anzahl, optionalen numerischen API-Code, Status der Login-Sperre, Erholungszeit und letzten Alarmversuch/letzte bestätigte SMTP-Annahme. Globaler Scope ucon für Login/API, exakte UID für Kamera. Der Dienst muss init_health, observe und dispatch_due unter seiner Datenbank-Sperre in einem einzelnen Worker aufrufen. Nur wirkliche Prüfergebnisse melden; keine Rohdaten. Eine gesunde Prüfung beendet die Störung; Entwarnung nur nach zuvor bestätigter Alarmannahme und aktivierter Option. Die E-Mail nennt den lokalen Kameranamen statt UID. Zustände bleiben über Neustarts erhalten. Erfolgreich angenommene Alarmmeldungen sind pro Störung begrenzt; nach einem unklaren SMTP-Ergebnis darf der Alarm nach retry_minutes erneut versucht werden. Anders als bei Bildmails kann dadurch im Zweifelsfall eine doppelte Fehlermeldung entstehen. Ein Ausfall des Servers selbst, seines Internetzugangs oder des Alarm-Mailservers kann Zustellung verhindern; externe Überwachung wäre für diesen Fall erforderlich.

Elf Standalone-Unit-Tests mit temporärer SQLite-Datei, synthetischen Zeitpunkten und simuliertem SMTP waren im vorherigen Entwicklungsstand erfolgreich. Der manuelle Alarmtest wurde am 26.11.2026 auf dem Testserver erfolgreich versendet und empfangen. Die vollständige erweiterte Testsuite ist noch nicht bestätigt. Noch keine automatische Fehlerüberwachung und keine geänderte Cloud- oder SD-Retry-Logik.
