# SafeUpdate2026

SafeUpdate2026 ist ein Enigma2-Plugin fuer einen abgesicherten OpenATV-Update-Ablauf bei KEXEC-/Multiboot-Systemen.

## Aktueller Teststand

- Version: `2026.1-r25`
- Ziel: Enigma2 / OpenATV mit KEXEC-Multiboot
- r25: dynamische Receiver-Erkennung und herstellerneutrale Kopf-/Hero-Anzeige fuer VU+, GigaBlue, Octagon und weitere Boxen
- Sicherheitsprinzip: erst pruefen, Backup erstellen und verifizieren, danach Update freigeben

> **Testversion fuer weitere Receiver:** Auf GigaBlue/Octagon bitte zunaechst nur Plugin oeffnen und Erkennung/Slot-Status pruefen. Solange KEXEC, HOLDs oder Datentraeger nicht eindeutig als OK erkannt werden, kein Backup und kein OpenATV-Update starten.

## Installation per Telnet

```sh
wget -qO- https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/main/install.sh | sh
```

Falls `wget` fehlt und `curl` vorhanden ist:

```sh
curl -fsSL https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/main/install.sh | sh
```

Der Installer laedt die in `latest.json` festgelegte Version, prueft alle Nutzdaten per SHA256, prueft die Python-Syntax, sichert eine vorhandene Installation und fuehrt bei einem Installationsfehler ein Rollback durch.

## r25

- feste/doppelte Herstelleranzeige entfernt
- Receivername in der Kopfzeile dynamisch
- Modell-Erkennung fuer gaengige GigaBlue-/Octagon-Modelle erweitert
- rechter Hero-Bereich herstellerneutral
- Backup-/KEXEC-/Slot-/Update-Logik gegenueber r24 nicht geaendert

Die r25-Verteilung verwendet die gepruefte r24-Basis plus SHA256-gepruefte r25-Code-/UI-Deltas. Dadurch bleibt der Telnet-Installer eine einzelne, dauerhaft gleiche Befehlszeile.
