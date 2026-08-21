1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

State your assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them - don't pick silently.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop. Name what's confusing. Ask.
2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

No features beyond what was asked.
No abstractions for single-use code.
No "flexibility" or "configurability" that wasn't requested.
No error handling for impossible scenarios.
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

Don't "improve" adjacent code, comments, or formatting.
Don't refactor things that aren't broken.
Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it - don't delete it.
When your changes create orphans:

Remove imports/variables/functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.
The test: Every changed line should trace directly to the user's request.

4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

Do not do any automated tests, I will always test manually.

5. Versioning & Git Rule
On every code change, you MUST bump the version number in ALL of the following places.
Missing any one of these causes displays to silently serve stale cached code.

**`sw.js`**
- `const APP_VERSION = '...'`

**`config.js`**
- `export const APP_VERSION = '...'`

**`index.html`** (the display entry point — ALL query strings must match)
- `<link rel="stylesheet" href="/style.css?v=..."`
- `<link rel="stylesheet" href="/css/display.css?v=..."`
- `<script src="/js/supabase.min.js?v=...">`
- `<script type="module" src="/display-entry.js?v=...">`

**`admin.html`** (the admin entry point — ALL query strings must match)
- `<link rel="stylesheet" href="/style.css?v=..."`
- `<link rel="stylesheet" href="/css/display.css?v=..."`
- `<script src="/js/supabase.min.js?v=...">`
- `<script type="module" src="/admin-entry.js?v=...">`

**`receiver.html`** (the Cast receiver entry point — ALL query strings must match)
- `<link rel="stylesheet" href="/css/display.css?v=..."`
- `<script type="module" src="/js/receiver.js?v=...">`

Also, automatically perform the Git and GitHub updates for both repositories,
and update the Electron wrapper (package version & build/release) only when changes have been made to that component.

6. Electron Wrapper Environment
This app runs in an Electron wrapper on Windows. Keep the following quirks in mind:
- Native browser dialogs like `window.prompt()`, `window.alert()`, or `window.confirm()` often fail or block without showing UI in Electron. Always use custom HTML/JS inline inputs or modals instead.
- There is a known Chromium DOM focus quirk on Windows with Electron where the window loses OS-level focus, causing inputs to become "locked". This is handled globally via a `mousedown` event listener in `adminShell.js` that calls `window.focus()`.
- Do not use `e.stopPropagation()` or `e.preventDefault()` on `mousedown` or `pointerdown` for inputs, as it will break the native caret placement and the global focus fix, preventing users from typing in fields.
