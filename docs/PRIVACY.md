# Privacy Policy - Biblionx LSRD Translator (browser extension)

Last updated: 2026-10-04

Biblionx translates selected Spanish text into Dominican Sign Language (LSRD). This policy describes what the extension does with your data.

## What is sent
- Only the text you choose to translate (via the floating button or the right-click menu) is sent, and only to the API server configured in the extension popup. The default is a local server on your own computer (`http://127.0.0.1:8000`).
- Nothing is sent automatically while you browse. The extension does not read pages, forms, history or cookies beyond the selection you explicitly translate.

## What is stored
- In your browser (`chrome.storage.sync`): the API base URL and your playback speed. Nothing else.
- On the server: no text, no user identifiers and no IP-based profiles are stored. The server keeps only aggregate counters (for example, number of requests and cache hits).

## Optional AI fallback
If the server operator enables the AI fallback, single unknown words plus a short surrounding context may be sent to the AI provider configured by that operator, only to find the closest existing sign. This is off unless the operator configures it. The operator of the server you connect to is responsible for that provider relationship.

## Remote servers
If you set a non-local API address, the extension asks your permission for that one `https://` origin. Plain `http://` is only accepted for localhost. You can revoke the permission at any time in the browser's extension settings.

## No tracking
No analytics, advertising, fingerprinting or third-party trackers. Data is never sold or shared.

## Contact
Open an issue in the project repository for questions or requests.
