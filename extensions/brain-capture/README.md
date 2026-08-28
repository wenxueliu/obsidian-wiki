# Brain Vault Capture

A zero-build Chrome extension that captures the active page URL and readable text into an Obsidian Wiki `_raw` folder.

## Install

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select this folder: `extensions/brain-capture`.

## Use

Find this repo's configured vault path from the command line:

```bash
awk -F= '/^OBSIDIAN_VAULT_PATH=/{print $2 "/_raw"; exit}' "$(git rev-parse --show-toplevel)/.env"
```

1. Open the extension popup.
2. Click **Choose _raw** and select the vault raw folder, usually `vault/_raw`.
3. Open any normal web page and click **Capture current page**.
4. Or right-click a page and choose **Capture page to brain raw**.
5. Or select text, right-click, and choose **Capture selection to brain raw**.

The extension writes a markdown file named like `2026-06-17-page-title.md` into the selected folder.

## Promote Captures Into The Wiki

After captures land in `_raw/`, run the ingest skill from your AI agent:

```text
/wiki-folder-ingest promote my raw pages
```

The ingest skill will distill the raw captures into proper wiki pages, update the vault bookkeeping files, and delete promoted `_raw/` files so they are not processed twice.

## What Gets Captured

- YAML frontmatter with title, source URL, creation timestamp, and capture metadata.
- The page title, URL, optional user note, selected text, and readable page text.
- Content is capped at 140,000 characters to keep captures usable for later wiki ingest.
