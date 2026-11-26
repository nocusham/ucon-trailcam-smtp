# Geplantes Feature: optionale Bild-Fußzeile

**Status:** Anforderungen abgestimmt am 26.11.2026; noch nicht implementiert. Umsetzung erst nach Abschluss der bereits vereinbarten Ziele (Langzeittest, Produktionsstruktur, LXC/Systemd, Revierwelt und weitere offene Ziele). Der laufende Langzeittest bleibt unverändert.

## Ziel

Wildkamerabilder ohne eigene Informationsleiste sollen beim E-Mail-Versand optional eine einheitliche, gut lesbare Fußzeile erhalten. Die Beispiele verschiedener Kamerahersteller dienen als gestalterische Orientierung; keine Herstellerlogos, privaten Beispielbilder oder GPS-Daten werden in das Repository übernommen.

Pflichtinformationen für Version 1:

| Information | Quelle |
| --- | --- |
| Kameraname | Lokaler Name des konfigurierten Kameraprofils |
| Akkustand | Batterie-Prozentwert aus den Metadaten des konkreten Fotoereignisses |
| Datum | Aufnahmezeitpunkt des Ereignisses, et_utc |
| Uhrzeit | Derselbe Aufnahmezeitpunkt, niemals Download- oder Versandzeit |

Standard: Europe/Berlin mit automatischer Sommer-/Winterzeitumstellung, Format DD.MM.YYYY HH:MM:SS; ein Zeitzonenhinweis MEZ/MESZ ist sinnvoll. Fehlender oder ungültiger Akkustand wird als unbekannt angezeigt, nicht erfunden und nicht stillschweigend durch einen später gemeldeten Batteriestand ersetzt. Keine zusätzliche Cloud- oder P4P-Abfrage allein für die Fußzeile.

## Bildgeometrie — verbindliche Anforderung

Die Fußzeile wird **unten an das vollständige Bild angehängt**. Sie darf keinen Teil des Motivs überdecken, abschneiden, strecken oder verkleinern.

- Originalbreite W und Originalhöhe H bleiben für den Fotobereich erhalten.
- Neue Bildfläche: W x (H + F), wobei F die Höhe der Fußzeile ist.
- Originalbild an Position (0, 0) in die neue Bildfläche kopieren.
- Ausschließlich im zusätzlichen Bereich ab y = H zeichnen.
- Schwarzer, deckender Hintergrund mit weißer, kontrastreicher Schrift. Keine halbtransparente Überlagerung.
- Schrift und Abstände proportional zur Bildbreite, mit ausreichendem Rand; lange zulässige Kameranamen dürfen nicht zu abgeschnittenem Text führen.
- Einzeiliger Standardstil, beispielsweise: `testkamera | Akku: 87% | 26.11.2026 14:58:21`.
- Beispiel für die DEATTI DL04: 5120 x 2880 Pixel plus beispielhaft 120 Pixel Fußzeile ergibt 5120 x 3000 Pixel. Die 120 Pixel sind ein Rechenbeispiel, keine festgelegte Standardhöhe.

Das heruntergeladene JPEG bleibt bytegenau unverändert. Die Versandkopie muss neu als JPEG kodiert werden; daher ist sie nicht byteidentisch und die dekodierten Pixel können durch JPEG-Kompression geringfügig abweichen. Keine Veränderung des Bildausschnitts oder der Bildauflösung des Fotobereichs. Geeignete JPEG-Qualität und Schriftwahl werden bei der Umsetzung getestet.

## Konfiguration (Entwurf, noch nicht unterstützt)

Pro Kamera optional innerhalb des vorhandenen [[cameras]]-Profils:

```toml
[cameras.image_footer]
enabled = false
```

Das Beispiel ist ein geplanter TOML-Unterabschnitt, keine jetzt gültige Einstellung. Weitere vorgeschlagene Optionen für Stil, angezeigte Felder, Zeitformat, Zeitzone, Hintergrund- und Schriftfarbe sowie Schriftgröße, Abstände und Höhe werden bei der Implementierung festgelegt. Version 1 soll ohne zusätzliche Einstellungen einen einheitlichen schwarzen Balken mit weißen Angaben erzeugen. Standardmäßig deaktiviert; alte Konfigurationen müssen unverändert funktionieren.

## Verarbeitung und Sicherheit

1. SD-Original herunterladen und wie bisher über MD5, JPEG-Validierung und lokalen SHA256-Downloadnachweis prüfen.
2. Bei deaktivierter Option die unveränderten Originalbytes wie bisher als Anhang verwenden.
3. Bei aktivierter Option nach der Originalprüfung und vor SMTP eine separate Versandkopie mit erweitertem Bildbereich erzeugen. Originaldatei niemals überschreiben; keine dauerhafte zweite Bildsammlung erforderlich.
4. Versandkopie auf JPEG-Format, vollständigen Fotobereich, erwartete Abmessungen, zulässige Größe und korrekten Anhang prüfen. Die bestehende Original-Hash-Prüfung bleibt erhalten; der bearbeitete MIME-Anhang benötigt eine eigene Prüfung gegen die erzeugte Kopie, nicht gegen den Originalhash.
5. Originalen Kameradateinamen als Anhangsnamen beibehalten; bestehender Betreff und E-Mail-Metadaten bleiben erhalten. Pro Kamera und auch im Gruppenmodus jede Aufnahme mit ihren eigenen Ereignisdaten verarbeiten.
6. Bei Fehlern der Fußzeilenerzeugung keine unbemerkte Rückkehr zum unbeschrifteten Anhang und kein Versand mit falschen Metadaten; Original und ausstehender Versandstatus bleiben erhalten. Fehler lokal klassifizieren. Keine erneute Kameraübertragung allein wegen eines Renderingfehlers.
7. Bestehenden Schutz gegen doppelten Versand, SMTP-Wiederholungsregeln, Aufbewahrungsfristen und Originalnachweise erhalten. Versandkopie und tatsächlich verwendete Metadaten müssen bei der späteren Umsetzung nachvollziehbar geprüft werden können.

## Abnahmetests

- Option aus: Anhang SHA256-identisch zum Original, keine Änderung der bisherigen Pipeline.
- Option an: Originaldatei SHA256-identisch vor und nach Verarbeitung; Breite unverändert, Höhe um Fußzeile erhöht; Fotobereich vollständig und ohne Überlagerung.
- Inhalt mit Kameraname, Akku, Aufnahmedatum und -uhrzeit korrekt; unbekannter Akku; Winter-/Sommerzeit und Zeitumstellung.
- Kleine und große Bildauflösungen, lange Kameranamen, Tag-/Nachtbilder, passende Textgröße und JPEG-Qualität.
- Zwei Kameraprofile mit unterschiedlichen Einstellungen; Einzel- und Gruppenmodus.
- Fehler bei Erzeugung und Größenprüfung ohne Versand oder erneuten Kamerazugriff; kein doppelter Versand nach Wiederholung.
- Zunächst synthetische Testbilder, dann privater SMTP-Test, erst danach Kompatibilität mit Revierwelt prüfen.

## Nicht Bestandteil von Version 1

GPS, Temperatur, Mondphase, PIR-Status, Signalstärke, Herstellerlogos, mehrzeilige oder herstellerspezifische Layouts. Keine Firmwareänderung und keine Änderung am Bild auf der SD-Karte.
