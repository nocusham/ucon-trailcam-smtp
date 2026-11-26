# Fehlerbenachrichtigung / Health alerts

**Entwicklungsstand:** optionaler Alarmkanal, SQLite-Zustandslogik und manueller SMTP-Test sind implementiert. Die automatische Beobachtung und Ausführung durch den späteren Dauerbetrieb sind noch nicht angeschlossen. Keine regelmäßigen Kameraverbindungen, automatischen Alarmmails oder Anmeldeversuche werden durch diese Änderung aktiviert.

## Konfiguration

Siehe den vollständig kommentierten Abschnitt [alerts] und [alerts.smtp] in [config.example.toml](../config.example.toml). Bei bestehenden Installationen nur diesen Abschnitt übernehmen; die Kameraeinstellungen bleiben unverändert. Ohne den Abschnitt oder bei enabled=false ist der Alarmkanal deaktiviert. Der private SMTP-Account hat eigenen Server, Port, Benutzer, Passwortverweis und Empfänger. Ein unabhängiger Anbieter ist sinnvoll, damit eine Störung des Bild-SMTP-Servers nicht gleichzeitig den Alarmkanal ausschaltet. Fehlerberichte sind reine Textmails ohne Bildanhänge. Nur STARTTLS oder TLS mit Zertifikatsprüfung; Revierwelt-Ziele werden für Alarme abgelehnt. Passwort wie bisher in .env, z.B. ALERT_SMTP_PASSWORD. Keine Passwörter oder Rohantworten in Alarmtexten.

| Kategorie | Standard | Voraussetzung |
| --- | --- | --- |
| Login | 15 min | Wiederholte fehlgeschlagene Prüfungen über die Frist; bestätigter Login-Code 20005 darf auch ohne weitere Anmeldung alarmieren |
| API | 30 min | Tatsächliche wiederholte API-Fehler über die Frist |
| Kamera | 24 h | Tatsächliche wiederholte Verbindungsfehler derselben UID über die Frist |
| Wiederholungsmeldung | 24 h | Störung besteht laut letztem Prüfergebnis fort |
| Alarm-SMTP-Wiederholung | 60 min | Vorheriger Alarmversuch fehlgeschlagen |
| Entwarnung | Aktiv | Erfolgreiche Prüfung nach zuvor bestätigter Alarmannahme |

Die Frist beginnt mit dem ersten beobachteten Fehler. Für normale Störungen sind mindestens zwei fehlgeschlagene Prüfungen erforderlich, deren Zeitabstand die Frist erreicht. Eine einzelne fehlgeschlagene Prüfung wird nicht allein durch Zeitablauf zum bestätigten Ausfall. Code 20005 wurde bei falschem Passwort beobachtet; später muss der Dienst das Login gezielt sperren und bei korrigierten Zugangsdaten wieder freigeben. Diese Login-Sperre ist noch nicht implementiert.

Fehlende PIR-Ereignisse sind kein Erreichbarkeitsnachweis. Ein späterer optionaler Gesundheitscheck kann eine schlafende Kamera wecken und Akku/Daten verbrauchen. Ohne aktive Prüfung oder andere belastbare Information kann ein Ausfall ohne neue Bilder unentdeckt bleiben. Während einer globalen Cloud-Störung keine neuen kamerabezogenen Ausfälle aus nicht ausgeführten Kameraprüfungen ableiten.

## Manueller Test (kein Zugriff auf Kamera oder Cloud)

```sh
python health_alerts.py --config config.local.toml
# Nur wenn enabled=true und private SMTP-Zugangsdaten eingerichtet sind:
python health_alerts.py --config config.local.toml --send-test
```

Der erste Aufruf validiert nur die Alarmkonfiguration. Der zweite sendet genau eine ausdrücklich als Test markierte E-Mail, ohne SQLite-Zustände zu ändern. Keine Testmeldung an Revierwelt.

## Persistenz und Integration

health_incidents speichert in SQLite den Schlüssel (Kategorie, Scope), erste/letzte Fehlerzeit, Anzahl, optionalen numerischen API-Code, Status der Login-Sperre, Erholungszeit und letzten Alarmversuch/letzte bestätigte SMTP-Annahme. Globaler Scope ucon für Login/API, exakte UID für Kamera. Der Dienst muss init_health, observe und dispatch_due unter seiner Datenbank-Sperre in einem einzelnen Worker aufrufen. Nur wirkliche Prüfergebnisse melden; keine Rohdaten. Eine gesunde Prüfung beendet die Störung; Entwarnung nur nach zuvor bestätigter Alarmannahme und aktivierter Option. Die E-Mail nennt den lokalen Kameranamen statt UID. Zustände bleiben über Neustarts erhalten. Erfolgreich angenommene Alarmmeldungen sind pro Störung begrenzt; nach einem unklaren SMTP-Ergebnis darf der Alarm nach retry_minutes erneut versucht werden. Anders als bei Bildmails kann dadurch im Zweifelsfall eine doppelte Fehlermeldung entstehen. Ein Ausfall des Servers selbst, seines Internetzugangs oder des Alarm-Mailservers kann Zustellung verhindern; externe Überwachung wäre für diesen Fall erforderlich.

Elf neue Standalone-Unit-Tests mit echter temporärer SQLite-Datei, synthetischen Zeitpunkten und simuliertem SMTP wurden lokal bestanden. Gesamtsuite, gemeinsame Konfiguration und tatsächlicher Alarmversand sind auf dem Testserver zu prüfen. Noch keine automatische Fehlerüberwachung und keine geänderte Cloud- oder SD-Retry-Logik.
