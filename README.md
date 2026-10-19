# portalbot

Playwright script that logs into GitHub with a TOTP code, reuses the session, goes three pages
deep to a form with a dependent field, starts a workflow and saves the PDF it produces.

```
login (password + TOTP) → repo → Actions → workflow → Run workflow form (branch changes the fields)
→ submit → wait for the run → download PDF + print run page → runs/<id>/manifest.json
```

## Setup

Needs Python 3.9+.

```bash
make setup     # venv, dependencies, Chromium
make doctor    # checks .env
```

**`.env` is included**, pointing at a throwaway GitHub account made for this assignment, so it runs
as-is against [`harshvardhan213/demo`](https://github.com/harshvardhan213/demo) (built from
[`demo-target/`](demo-target)).

| `.env` | |
|---|---|
| `GH_USERNAME`, `GH_PASSWORD` | GitHub login |
| `GH_TOTP_SECRET` | the authenticator "setup key" |
| `HEADLESS` | `false` to watch the browser |

To use your own account instead: put your values in `.env`, create a repo from `demo-target/`
(`generate-report.main.yml` on `main`, `generate-report.v2.yml` on a `v2` branch, both at
`.github/workflows/generate-report.yml`, plus `scripts/generate_report.py`), and set `"repo"` in
`inputs/*.json`.

## Try it

| | Command | Expect |
|---|---|---|
| First run | `make run` | full login, PDF in `runs/<id>/files/` |
| Run again | `make run` | `session reused`, no login page, same PDF |
| Corrupt session | `echo '{' > state/github.json && make run` | dead session detected, full login |
| Other input | `make run INPUT=inputs/main-statement.json` | different PDF |
| Dependent field | `make run INPUT=inputs/v2-audit.json` | `v2` form adds `region` |
| Break a step | `make run INPUT=inputs/demo-broken-step.json` | fails, `runs/<id>/evidence/` written |
| Resolver offline | `make test` | passes on mutated HTML |

Sample outputs: [`examples/`](examples).

## Answers

**Code and wrong codes.** `TotpProvider.get_code()` computes the code from the secret (`pyotp`)
and skips codes about to expire. If GitHub stays on the 2FA page, it retries once with the next
code, then fails. Codes are redacted from all output.

**Dead session.** Reused only if the file parses, has the `user_session` cookie, and an
auth-only page (`/settings/profile`) shows our username. Otherwise: full login.

**Locator order.** Role + name → label → nearby text → structure (`name=`, `autocomplete=`) →
id/class. Most stable first; GitHub's classes and ids are generated per build, so they go last.
Exactly one visible match wins; the winner is logged. Searches iframes too.

**Quirks.** Dependent field (branch changes the form), download event, print to PDF, iframe.

**Retries.** Timeouts and network errors: 3 tries, 2s/4s backoff. Final (no retry): wrong
password, code rejected twice, element not found, input not in form, failed workflow. Submit is
never retried, to avoid a double dispatch. Final failures write a screenshot (inputs and account
name masked), redacted HTML, URL, console log, stage key and resolver attempts.

**For 100 portals.** Keep the engine shared (session, resolver, retries, manifest, evidence) and
make each portal a small module of targets and steps, with a code provider per 2FA type and a
job queue in front.
