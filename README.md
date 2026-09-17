# SafeUpdate2026

SafeUpdate2026 ist ein Enigma2-Plugin fuer einen abgesicherten OpenATV-Update-Ablauf bei KEXEC-/Multiboot-Systemen.

## Aktueller Teststand

- Version: `2026.1-r24`
- Ziel: Enigma2 / OpenATV mit KEXEC-Multiboot
- Hardware-Anzeige: dynamisch, nicht auf VU+ fest verdrahtet
- Sicherheitsprinzip: erst pruefen, Backup erstellen und verifizieren, danach Update freigeben

> **Testversion:** Vor einer breiten Veroeffentlichung wird die Erkennung auf weiteren Receivern wie Octagon und GigaBlue getestet. Auf fremder Hardware bitte zunaechst nur Erkennung/Slot-Status pruefen und keinen Update-Lauf erzwingen.

## Installation per Telnet

```sh
wget -qO- https://raw.githubusercontent.com/keggy6893/SafeUpdate2026/main/install.sh | sh
```

Der Installer laedt die in `latest.json` angegebene Version, prueft SHA256 und Python-Syntax, sichert eine vorhandene Installation und fuehrt bei einem Installationsfehler ein Rollback durch.

## Dateien

- `install.sh` – Telnet-Installer
- `latest.json` – aktuelle Version, Download und SHA256
- `releases/` – Plugin-ZIP-Dateien

## Aktuelle SHA256

`SafeUpdate2026_2026.1-r24.zip`

```text
0fe477c4e6aa3a351219a57d68a091587f13f62cc2bd63f208c8e581407a035d
```
