# Store Listing - Biblionx LSRD Translator

## Name
Biblionx - Dominican Sign Language (LSRD) Translator

## Short description (max 132 chars)
Select Spanish text on any page and see it as Dominican Sign Language (LSRD) in an accessible player.

## Long description
Biblionx translates selected Spanish (Dominican Republic) text into Dominican Sign Language (LSRD). Select text, press the floating button or right-click and choose "Translate to LSRD", and a keyboard-accessible player shows each sign in sequence with its word and movement description.

- Sign-by-sign player with play/pause, previous/next, speed control and timeline
- Fingerspelling for words without a sign, clearly labelled
- Matches flagged when they come from approximate or AI-assisted lookup
- Text cards with the movement description when a sign image is unavailable
- Screen-reader friendly, full keyboard support, respects reduced motion
- Works with a local server or an https server you configure; no tracking

Requires a running Biblionx API (see the project README).

## Permission justifications
- `storage`: saves the API address and playback speed.
- `contextMenus`: adds the "Translate to LSRD" entry for selected text.
- `activeTab`: delivers the context-menu selection to the current tab.
- Host permissions `http://127.0.0.1:8000/*`, `http://localhost:8000/*`: call the default local API.
- Optional host permission `https://*/*`: requested at runtime, for one origin only, when the user saves a remote API address; never granted automatically.
- Content script on `<all_urls>`: shows the floating button and player on the selected text; no page content is read or transmitted except the user's selection.

## Single purpose
Translate user-selected Spanish text to LSRD.

## Privacy
See docs/PRIVACY.md. Host the policy at a public URL and enter it in the store form.

## Screenshots checklist (1280x800 or 640x400)
- [ ] Floating "Translate to LSRD" button over selected text
- [ ] Player showing a sign image with word and description
- [ ] Timeline with fingerspelled and AI-match badges
- [ ] Text card (image unavailable state)
- [ ] Settings popup with API URL and speed
- [ ] Error state (rate limit / unreachable server)
- [ ] Small promo tile 440x280 and 128x128 icon
