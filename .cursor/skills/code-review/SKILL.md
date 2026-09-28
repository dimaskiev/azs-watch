---
name: code-review
description: Reviews and auto-fixes code against architecture, performance, reliability, and maintainability rules. Use when the user says «перевір код», «перевірка коду», «перевір», «рев'ю», «ревью», «аудит коду», «review code», «code review», or asks to check/fix code quality or architecture.
---

# Review and fix

Do not only report. **Fix what you find**, then re-check.

Quality bar: `.cursor/rules/code-quality.mdc` + `.cursor/rules/azs-watch.mdc` + `AGENTS.md`. Product rules win over generic style.

## Steps

1. Read the two rules above.
2. Scope: uncommitted / requested files. If «весь код» or no scope — `server.py`, `app.py`, `web/app.js`.
3. Walk the checklist. For each fail: **fix in place**, unless it adds a new abstraction for one implementation.
4. No test suite: smoke `/api/state` or a local scrape helper. UI changes: exercise the flow if browser tools exist.
5. Reply in Ukrainian: what was wrong, what you fixed, what you left (and why).

## Checklist

### Architecture

- [ ] Scrape/parse stays out of Flask routes and `web/`.
- [ ] No new client/repo/interface unless a second implementation exists.

### Performance

- [ ] Hosted state does not scrape on every request when cache is fresh.
- [ ] No new sequential HTTP on the request path.

### Reliability / security

- [ ] No empty `except`.
- [ ] Discount POST validates keys and range.
- [ ] Hosted TLS stays verified; no secrets in git; hosted errors are generic.
- [ ] HTML from API fields is escaped in `web/app.js`.

### Maintainability

- [ ] Touched files only. No format-only or drive-by rewrite.

## Do not “fix” by

- Adding repository interfaces
- Re-enabling Plusy discount scrape
- Showing source sites/dates in the table
- Mass rename or CRLF-only commits
