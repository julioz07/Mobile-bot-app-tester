# App review template

Write the review in the user's language. Keep it for the developer: concrete, reproducible, kind.
Delete sections that don't apply.

```markdown
# Review of <app name> (<date>)

Tested <version from `info --package`>, installed from <Play Store closed test / APK / AAB>, on:

| Bot | Screen | Language | Notes |
| --- | --- | --- | --- |
| phone-small | 720x1280, 2 GB RAM | EN | |
| phone | 1080x2400 | ES | |
| phone-large | 1344x2992 | EN | large text 1.3 |

## Across all bots
- Issues that show up everywhere (language, accessibility, store listing vs app name...).

## Works well
- What a player or user would enjoy. Keep it short, but say it: it tells the developer what not to break.

## Broken
- **<Short title>.** What happens, on which bots. Steps: 1... 2... 3...
  Expected: ... Screenshot: `bot-reports/shots/<file>.png`

## Could be better
- Smaller issues and suggestions, each with a reason.

## Crashes and errors
- From `crashwatch` / `monkey`: the error line, the top of the stack trace, and how to reproduce
  (steps, or `monkey --seed N`).

## Not tested
- What you couldn't check (payments, real low-end phone, multi-touch, sensors...).

## How we tested
- Bot profiles, how the app was installed, roughly how long each part took. Enough for the developer
  to repeat it with this same tool.
```

## Checklist

- [ ] First launch and onboarding on the smallest and the largest bot
- [ ] The main flow, end to end
- [ ] Back button on every main screen; leaving the app and returning
- [ ] Rotation (or confirm it's locked on purpose)
- [ ] Another phone language
- [ ] Large text (`variants --font 1.3`)
- [ ] Dark mode, if the app has one
- [ ] `ui` on the main screens: are things labeled for TalkBack?
- [ ] `crashwatch` running for the whole session; a `monkey` run at the end
- [ ] Store listing text vs what the app shows (name, features, screenshots)
