# SafeUpdate2026

SafeUpdate2026 ist ein Enigma2-Plugin fuer einen abgesicherten OpenATV-Update-Ablauf bei KEXEC-/Multiboot-Systemen.

## Aktueller Teststand

- Version: `2026.1-r27`
- Ziel: Enigma2 / OpenATV mit KEXEC-Multiboot
- Receiver-Erkennung dynamisch fuer VU+, Octagon, GigaBlue und weitere Boxen
- VU+ Duo 4K SE: klassische Receiver-Grafik
- andere Receiver: herstellerneutrale Receiver-/Schutzgrafik
- Sicherheitsprinzip: erst pruefen, Backup erstellen und verifizieren, danach Update freigeben
- Backup-/KEXEC-/Slot-/Update-Logik bleibt abgesichert; der aktive Slot darf niemals als Loeschziel verwendet werden

> **Tester-Hinweis:** Auf weiteren Receivern bitte zuerst Plugin oeffnen und Receiver-Erkennung, KEXEC/HOLD-Status und Slot-Erkennung pruefen. Solange ein Sicherheitsstatus nicht eindeutig OK ist, kein Backup und kein OpenATV-Update starten.

## Installation per Telnet

```sh
wget -qO- https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/main/install.sh | sh
```

Falls `wget` fehlt und `curl` vorhanden ist:

```sh
curl -fsSL https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/main/install.sh | sh
```

Der Installer liest `latest.json`, laedt das komplette Paket `SafeUpdate2026_2026.1-r27.zip` und prueft vor dem Entpacken dessen SHA256. Danach wird `plugin.py` syntaktisch geprueft. Eine vorhandene Installation wird vor dem Austausch gesichert; bei Installations- oder Syntaxfehlern erfolgt ein Rollback. Build-/Runtime-Caches (`__pycache__`, `*.pyc`) werden nicht uebernommen. Nach erfolgreicher Installation wird Enigma2 neu gestartet.

## 2026.1-r27

- Receiver-Hersteller und Modell dynamisch erkannt
- VU+ Duo 4K SE behaelt die klassische Hero-Grafik
- andere Receiver verwenden die neutrale Receiver-/Schutzgrafik
- vollstaendiges r27-Paket statt r26-Delta-Installation
- Taste `0` loescht nach Bestaetigung ausschliesslich das aktuell von SafeUpdate verifizierte Sicherheitsbackup
- der aktive Slot kann niemals geloescht werden
- `STARTUP_N` bleibt erhalten; der Backup-Slot kann nach erfolgreichem Loeschen wieder als frei erkannt werden
- vor dem Loeschen werden State, Slot-Zuordnung, Root-Geraet und physische Backup-Struktur erneut geprueft
- nach erfolgreichem Loeschen wird der gespeicherte Backup-Status entfernt und das OpenATV-Update sofort wieder gesperrt
- bei unvollstaendiger Loeschung wird der Slot ausdruecklich nicht als frei behandelt
