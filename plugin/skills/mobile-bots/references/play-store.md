# Play Store bots and closed tests

Use this when the user wants to install their app from Google Play (internal or closed testing) on bots,
for example to test exactly what testers get, or to count as testers for Google's closed-testing requirement.

## Create the bot

```
bots.py create tester1 --profile phone --play --download
bots.py start tester1
```

Only `--play` images have the Play Store. They can't be rooted, which is fine for testing.

## The manual part (the user does this, you guide)

Google blocks automated sign-ins, so a person has to do these steps once per bot, in the emulator window:

1. Open **Play Store** and sign in with a Google account. Use a test account, not a personal one.
   Each tester account can be signed in on one bot.
2. That account must be on the app's tester list in Play Console (Testing > Closed testing > Testers),
   usually through a Google Group or email list.
3. In a browser on the bot (Chrome), open the opt-in link from Play Console and tap **Become a tester**.
4. Back in the Play Store, find the app (the store link from Play Console works) and install it.
   It can take a few minutes after opting in before it appears.

Then save the work:

```
bots.py snapshot save tester1 logged-in
bots.py protect tester1
```

## Keeping them healthy

- Updates come through the Play Store like on a phone. `info <bot> --package <pkg>` shows the installed
  version and the installer (`com.android.vending` = Play Store).
- An APK built locally won't install over a Play Store install (different signature). Uninstalling the Play
  version erases its data and means reinstalling from Play later: always ask first.
- If a bot misbehaves, `snapshot load <bot> logged-in` returns to the saved state without losing the login.
