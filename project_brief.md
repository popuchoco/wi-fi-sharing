# My agent: Wi-Fi-Sharing
One-liner: A conversational agent that helps hosts, venues, and users quickly share Wi-Fi passwords by generating scannable Wi-Fi connection QR codes and sharing cards.

Tool coverage:
- Memory: Remembers saved Wi-Fi networks (SSID, encryption type, guest notes, usage policies) and host preferences across sessions
- Tools: Generate standard Wi-Fi connection QR codes (`WIFI:T:<type>;S:<ssid>;P:<password>;;`), validate credentials, and query network configs
- Catalog/UI: Catalog of Wi-Fi access points (Home, Guest, Office, Meeting Room) rendered as cards and tables
- Image gen: Visual Wi-Fi connection cards, desktop tent cards, and printable table signs with custom branding
- Sandbox: QR matrix generation and encoding validation

Recommended for every project: memory, storage, tools, image generation, A2UI
Agent-specific / stretch (pick what fits): code sandbox for QR matrix encoding, Cloud Trace
