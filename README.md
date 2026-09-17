# SafeUpdate2026

SafeUpdate2026 ist ein Enigma2-Plugin fuer einen abgesicherten OpenATV-Update-Ablauf bei KEXEC-/Multiboot-Systemen.

## Aktueller Teststand

- Version: `2026.1-r26`
- Ziel: Enigma2 / OpenATV mit KEXEC-Multiboot
- Receiver-Erkennung dynamisch fuer VU+, Octagon, GigaBlue und weitere Boxen
- VU+ Duo 4K SE: klassische Receiver-Grafik
- andere Receiver: herstellerneutrale r26-Grafik
- Sicherheitsprinzip: erst pruefen, Backup erstellen und verifizieren, danach Update freigeben
- Backup-/KEXEC-/Slot-/Update-Logik gegenueber dem bewaehrten Stand nicht erweitert oder entschaerft

> **Tester-Hinweis:** Auf weiteren Receivern bitte zuerst nur Plugin oeffnen und Receiver-Erkennung, KEXEC/HOLD-Status und Slot-Erkennung pruefen. Solange ein Sicherheitsstatus nicht eindeutig OK ist, kein Backup und kein OpenATV-Update starten.

## Installation per Telnet

```sh
wget -qO- https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/main/install.sh | sh
```

Falls `wget` fehlt und `curl` vorhanden ist:

```sh
curl -fsSL https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/main/install.sh | sh
```

Der Installer laedt den in `latest.json` festgelegten r26-Teststand. Die r24-Basis wird per SHA256 geprueft; die r26-Code- und Grafik-Payloads werden gegen ihre Git-Blob-SHAs verifiziert. Danach wird der Python-Code entpackt und syntaktisch geprueft. Eine vorhandene Installation wird vor dem Austausch gesichert; bei Installations- oder Syntaxfehlern erfolgt ein Rollback. Build-/Runtime-Caches (`__pycache__`, `*.pyc`) werden nicht uebernommen.

## 2026.1-r26

- Receiver-Hersteller und Modell dynamisch erkannt
- VU+ Duo 4K SE behaelt die klassische Hero-Grafik
- andere Receiver verwenden die neutrale Receiver-/Schutzgrafik
- r26-Code liegt platzsparend als `r26/plugin.zlib.b64` vor
- neutrale Grafik liegt als `r26/generic.jpg.b64` vor
- Tester-Installer verwendet die gepruefte r24-Basis und setzt darauf die verifizierten r26-Payloads
- ein einzelner, dauerhaft gleicher Telnet-Befehl bleibt erhalten
