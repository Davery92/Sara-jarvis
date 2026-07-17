# Sara Desktop Context — Browser Extension

Streams the active tab's URL and title to the Sara desktop sidecar so Sara
knows which site you're looking at. Without this, the activity classifier
sees `chrome.exe` and nothing more.

## What it sends

For every active-tab change or page-load completion:

```json
{
  "type": "browser_context",
  "url": "https://docs.anthropic.com/en/docs/prompt-caching",
  "title": "Prompt caching - Anthropic",
  "domain": "docs.anthropic.com"
}
```

Only HTTP(S) pages are sent. `chrome://`, `about:`, `file://`, and
`chrome-extension://` URLs are filtered out before transmission.

## What it does NOT send

- Page contents, DOM, or scripts
- Form values, cookies, or auth tokens
- Anything from internal browser pages

## Where it sends to

`ws://127.0.0.1:9876` — the Sara sidecar's local bridge port. The connection
is loopback only; if the sidecar isn't running, the extension retries with
exponential backoff and is otherwise inert.

## Install (unpacked)

Chrome / Edge / Brave:

1. Visit `chrome://extensions` (or `edge://extensions`).
2. Toggle **Developer mode** on.
3. Click **Load unpacked**.
4. Pick this `browser-extension/` folder.

Firefox:

1. Visit `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on**.
3. Pick `manifest.json` in this folder.

Firefox unloads temporary add-ons on restart; for permanent install you'd
need to sign-and-self-host. Chrome retains unpacked extensions across
restarts.

## Verifying it works

After install:

1. The sidecar log (`%USERPROFILE%\.sara\sidecar.log`) should show a
   `browser_context` line each time you switch tabs or finish loading a page.
2. Next `focus_span` event for the browser app will include `url`/`domain`
   in its payload.
3. Sara's chat responses will start mentioning the actual sites you're on
   when summarizing your day.

## Removing it

`chrome://extensions` → toggle off or click **Remove**. Or just close the
sidecar — the extension does nothing without it.
