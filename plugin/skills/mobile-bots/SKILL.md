---
name: mobile-bots
description: Set up and drive a fleet of Android emulators ("bots") to test mobile apps and games - create bots from device profiles, install builds, play or explore the app, hunt crashes, check layouts across screen sizes and languages, and write a test report. Use when the user wants test devices/emulators/bots, to test or review an Android app or game, to try a build on several screen sizes, to hunt crashes, or to prepare a Play Store closed test.
argument-hint: "[what to test, e.g. 'set up 3 bots' or 'review com.example.game']"
---

# Mobile bots

You drive Android emulators ("bots") through one CLI. Never improvise raw `avdmanager`/`emulator`
commands when the CLI has a command for it: the CLI handles SDK paths, Java versions, ports, RAM
checks and protection of precious bots.

What the user asked, if anything: $ARGUMENTS

## The CLI

```
python "${CLAUDE_SKILL_DIR}/scripts/bots.py" <command> [...]
```

Use `python3` where `python` is Python 2 or missing (many Linux systems). Run `<command> --help` for
options. Commands that take bots accept names or `all`; with none they act on every running bot.

| Area | Commands |
|---|---|
| Setup | `doctor`, `profiles`, `create`, `adopt`, `list`, `start`, `stop`, `protect`, `unprotect`, `delete`, `snapshot` |
| Apps | `install` (.apk, .aab, .apks, folder of splits), `launch`, `app stop/clear/uninstall`, `info --package` |
| Look and touch | `shot`, `record`, `ui`, `tap`, `tap-text`, `swipe`, `type`, `key`, `rotate` |
| Variations | `variants --lang/--dark/--font/--screen/--reset` |
| Bugs | `crashwatch`, `monkey`, `logcat` |

Output files go to `bot-reports/` in the current folder unless `--out` says otherwise.

## First time: set up the fleet

1. Run `doctor`. If it says NOT READY, explain each failing line in plain words and stop there
   until it is fixed. Common fixes are in the README's Troubleshooting section.
2. Run `list --avds`. If the user already has emulators that aren't bots yet, offer to `adopt` them
   (and `protect` any with a Google login) instead of creating new ones.
3. Ask, with AskUserQuestion where it fits:
   - **What will they test?** Apps, games, or both. This decides how you will drive them later, not which bots to create.
   - **What for?** Pick all that apply: install builds and smoke test; screen sizes and layout;
     a Play Store closed test (needs Play Store images and a Google login done by hand); crash hunting;
     store screenshots.
   - **How many bots?** Propose a set yourself from the goal and the capacity `doctor` printed.
     A good default is `phone-small` + `phone` + `phone-large` (+ `foldable` or `tablet` if they care about big screens).
     Never propose more than `doctor` says fit.
4. Before creating: say the disk cost (6-10 GB per bot, plus ~1.5 GB once per system image) and that
   `--download` accepts the Android SDK licenses on their behalf. Create only after they agree.
5. `create <name> --profile <p> [--play] [--download]` for each, then `start all`.
6. For Play Store bots, walk the user through the manual login (references/play-store.md), then
   `snapshot save <bot> logged-in` and `protect <bot>`.

## Rules

- `protect`ed bots are precious (Google logins, long setups). Never `unprotect` or `delete` one unless
  the user asks for that specific bot. Never run the emulator with `-wipe-data`.
- `delete`, `app clear` and `app uninstall` erase data: ask first, every time.
- A build signed with a different key than the installed one will not install over it
  (Play Store installs are re-signed by Google). The CLI says so; ask before uninstalling.
- Do not type passwords or sign into accounts for the user. Guide them; they type.
- Starting too many bots freezes the computer. Respect the RAM check; use `--force` only if the user insists.
- Bots use a lot of memory: `stop all` when a session ends, unless the user wants them left running.

## Driving an app (normal UI)

1. `ui <bot>` lists what Android sees, with tap coordinates. Prefer `tap-text "<regex>"` over
   coordinates: it survives layout changes.
2. After each action, wait a moment (animations), then `ui` or `shot` again to see the result.
3. Read screenshots with the Read tool. Use `shot --max 1280` so images stay small; the command prints
   a `scale` - pass `--scale <that>` to `tap`/`swipe` when you aim with screenshot pixels.
4. `ui` showing nothing useful (only a View or an ad) means a canvas: treat it like a game. Report it,
   since screen readers (TalkBack) can't read that screen either.

## Driving a game

Games draw on a canvas, so `ui` sees nothing. Read references/games.md before the first session. In short:
`shot --max 1280` -> look -> `tap X Y --scale S` (or `swipe`) -> wait -> `shot` again, while
`crashwatch --package <pkg>` runs in the background. Use `record` for anything that depends on timing.

## Recipes

**Smoke test a build.** `install <file>` on all bots -> `launch <pkg>` -> `shot --label start` -> walk
the main flow on each size -> `crashwatch` in the background the whole time -> report.

**Screen sizes and text.** For each bot, also check `variants --font 1.3` (large text) and
`variants --screen 720x1280@320` on a big bot (fake a small phone). Look for cut-off text,
overlapping elements and buttons pushed off screen. `variants --reset` afterwards.

**Languages.** `variants --package <pkg> --lang es-ES` sets the app's language (Android 13+). Apps with their
own in-app language setting ignore it; then use the app's setting. Check that texts fit and nothing stays in
the wrong language.

**Crash hunt.** `monkey <pkg> --events 3000` on all bots (it runs a crash watcher too). Note the seed of any run
that crashed: `--seed N` replays it. Then read the crash log it points to and turn it into a bug: what crashed,
the top of the stack trace, and steps or seed to reproduce.

**App review.** Follow references/review-template.md. Test as a real user would: first launch,
onboarding, main loop, back button, leaving and returning (`key home`, then `launch`), rotation,
another language, large text, and the smallest bot.

**Store screenshots.** `variants --dark on/off` as wanted, put the app in a good state, `shot --label <name>`
on each bot. Report the device size of each file.

## Reports

Write findings to a Markdown file (ask where; default `bot-reports/report-<date>.md`), in the user's language.
Each finding: what happens, on which bot(s), how to reproduce, a screenshot or video path, and how bad it is.
Separate "broken" from "could be better". Say what you could not test (for example payments or a real
low-end phone) instead of guessing.
