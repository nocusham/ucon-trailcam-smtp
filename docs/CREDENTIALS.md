# Lokale Zugangsdaten und Neustart

Die Installation verwendet zwei lokale, nicht versionierte Dateien: config.local.toml (Kamera- und SMTP-Einstellungen) und .env (vertrauliche Zugangsdaten). Beide bleiben auf dem Datenträger erhalten. Standardpfad der .env ist neben den Python-Skripten; optional setzt der Betreiber UCON_SECRETS_FILE auf einen anderen absoluten Dateipfad. Kein Shell-Sourcing, keine neue Abhängigkeit und kein interaktiver Passwortmanager nötig.

```sh
umask 077
test -e .env || cp .env.example .env
test -e config.local.toml || cp config.example.toml config.local.toml
chmod 600 .env config.local.toml
nano .env
```

Die Datei muss dem ausführenden Benutzer gehören und Modus 600 oder 400 haben. Symbolische Links, nicht reguläre Dateien, doppelte Schlüssel und fehlerhafte Einträge werden abgelehnt. UTF-8; NAME=Wert, eine Zeile je Schlüssel; kein export und keine Anführungszeichen als Syntax. Der gesamte Inhalt hinter dem ersten Gleichheitszeichen wird als Literal gelesen, auch Sonderzeichen und Leerzeichen. Kommentare nur auf eigenen Zeilen. Nicht mit source ausführen. Dateiwerte haben Vorrang vor schon exportierten Variablen, fehlende Schlüssel greifen auf die Prozessumgebung zurück. Wenn die Standarddatei fehlt, bleibt das bisherige Verhalten erhalten. Explizit gesetzter, fehlender UCON_SECRETS_FILE ist ein Fehler. Keine Dateiinhalte oder Kennwörter in Logs.

```dotenv
UCON_ACCOUNT=mein-konto@example.invalid
UCON_PASSWORD=MEIN_UCON_PASSWORT
SMTP_PASSWORD=MEIN_SMTP_PASSWORT
SMTP_PASSWORD_KAMERA2=WEITERES_SMTP_PASSWORT
```

In config.local.toml verweist password_env auf den Schlüsselnamen, nicht auf das Passwort. Alternativ ist ausschließlich das öffentlich dokumentierte Revierwelt-Passwort password = "mail" zugelassen, wenn host smtp.revierwelt.de und Empfänger @revierwelt.de sind. Dann password_env weglassen. username ohne Passwortquelle bzw. beide Quellen gleichzeitig werden abgelehnt. Bei SMTP ohne Anmeldung username und beide Passwortfelder weglassen. Kein Revierwelt-Livetest bis Projektabschluss.

Die manuellen Ucon-Probes nutzen read_credentials(); bei fehlenden Werten dürfen sie interaktiv nachfragen. Der spätere unbeaufsichtigte Dienst muss read_credentials(interactive=False) nutzen und bei fehlenden Angaben mit einem verständlichen, geheimnisfreien Fehler beenden. camera_smtp.py lädt Zugangsdaten nur beim tatsächlichen Versand. Die alten SMTP-Probes lesen ihre globalen SMTP_* Einstellungen ebenfalls über den lokalen Loader; diese globalen Einstellungen sind nicht die Mehrkamera-Konfiguration.

Beim späteren systemd-Dienst wird der dedizierte, unprivilegierte Benutzer die private Datei direkt lesen, optional UCON_SECRETS_FILE=/absoluter/pfad/.env in der Unit (nur Pfad, keine Geheimnisse). Ein Neustart benötigt keine manuelle Anmeldung oder export-Befehle, sofern der Dienst aktiviert und die Datei vorhanden und lesbar ist. Die systemd-Unit und tatsächlicher Neustarttest stehen noch aus. Nicht als systemd EnvironmentFile interpretieren, da dieses eine andere Quoting-Syntax hat.

Dateirechte sind kein Schutz vor root, kompromittiertem Dienst, Datenträgerdiebstahl oder ungeschützten Backups. Backups von Konfiguration, Datenbank und Zugangsdaten vertraulich behandeln. Eine private Passwortdatei ist nicht verschlüsselt. SMTP ohne TLS überträgt auch private Inhalte unverschlüsselt; das öffentliche Passwort ändert daran nichts.

## Bestätigter Teststand (26.11.2026)

Die Anmeldung aus der lokalen .env nach Entfernen der exportierten Variablen war erfolgreich. Beide lokalen Dateien hatten Modus 600. Die Tests zur Ucon-Anmeldung sind seit Commit 49f6de4 vom tatsächlichen Installationsverzeichnis isoliert; Vergleichsfehler geben keine Zugangsdaten aus. Die vollständige Suite mit 108 Tests war anschließend auf dem konfigurierten Testserver erfolgreich. Bei absichtlich falschem Passwort meldete die Login-API Code 20005. Das geplante Anhalten automatischer Login-Wiederholungen für diesen Fall ist noch nicht implementiert. Bei versehentlich offengelegten Zugangsdaten das Passwort ändern und .env aktualisieren; keine Geheimnisse in Fehlerberichte übernehmen.
