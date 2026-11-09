# Mobile bot app tester

Test your Android apps and games on a small fleet of emulators ("bots") of different sizes, driven by
[Claude Code](https://claude.com/claude-code) or by a plain command-line tool.

It started as the setup we used to test our own apps. A few emulators of different sizes and languages
caught most of the bugs a real tester group would find: cut-off text on small phones, broken layouts on
foldables, untranslated screens, crashes. This project packages that setup so anyone can repeat it.

- **One command per job:** create bots from ready-made device profiles, start them, install a build on all of
  them, take screenshots, record video, change language, text size or dark mode, and hunt crashes.
- **Works for apps and games.** Apps are driven through Android's view of the screen ("tap the button called
  Next"). Games draw their own pixels, so they are played from screenshots and coordinates.
- **Claude Code skill.** Claude asks what you want to test, proposes the bots, sets them up, plays your app,
  and writes a report with screenshots and steps to reproduce.
- **No dependencies.** One Python file using the standard library. Runs on Windows, Linux and macOS.
- **Safe for precious bots.** Bots with a Google login can be protected: delete refuses them.

## Contents

- [What you need](#what-you-need)
- [Install](#install)
- [Use it with Claude Code](#use-it-with-claude-code)
- [Use it from the command line](#use-it-from-the-command-line)
- [Device profiles](#device-profiles)
- [Commands](#commands)
- [Apps and games](#apps-and-games)
- [Play Store closed tests](#play-store-closed-tests)
- [Where things are stored](#where-things-are-stored)
- [Troubleshooting](#troubleshooting)
- [Limits](#limits)

## What you need

| | Windows | Linux | macOS |
| --- | --- | --- | --- |
| Python 3.9 or later | [python.org](https://www.python.org/downloads/) | usually installed (`python3`) | `brew install python` |
| Android SDK | [Android Studio](https://developer.android.com/studio) | Android Studio | Android Studio |
| Hardware acceleration | turn on **Windows Hypervisor Platform** in *Turn Windows features on or off* | KVM: `/dev/kvm` must exist and your user must be in the `kvm` group | built in |

The Android SDK needs four packages. Install them in Android Studio > **Settings > Languages & Frameworks >
Android SDK > SDK Tools**:

- Android SDK Platform-Tools (`adb`)
- Android Emulator
- Android SDK Command-line Tools (latest)
- Java 17 or later. Android Studio already ships one, and the tool finds it by itself.

**Memory and disk.** Each bot uses about 2-3 GB of RAM while running and 6-10 GB of disk. Keep about 6 GB of
RAM for the system and your editor. As a rule of thumb, 16 GB of RAM runs about 3 bots and 32 GB about 8,
fewer if other heavy programs are open. `doctor` does the maths for your computer.

**Optional:**

- [Pillow](https://pypi.org/project/pillow/) (`pip install pillow`) makes `shot --max` shrink screenshots. Smaller
  images are faster for Claude to read.
- [bundletool](https://github.com/google/bundletool/releases) is needed only to install `.aab` files. Save it
  as `~/.mobile-bots/bundletool.jar`.

## Install

### As a Claude Code plugin

In Claude Code:

```text
/plugin marketplace add julioz07/Mobile-bot-app-tester
/plugin install mobile-bots@mobile-bot-app-tester
```

Then ask Claude something like *"set up test bots for my app"*, or type `/mobile-bots:mobile-bots`.

### As a command-line tool only

```text
git clone https://github.com/julioz07/Mobile-bot-app-tester.git
cd Mobile-bot-app-tester
python bots.py doctor
```

On Linux and macOS use `python3` where this guide says `python`.

## Use it with Claude Code

The first time, Claude runs `doctor` to check your computer. Then it asks what you want to test (apps, games
or both) and what for (smoke tests, screen sizes, a Play Store closed test, crash hunting, store screenshots).
It proposes a set of bots that fits your memory and creates them after you agree.

Things you can ask:

- *"Create 3 bots: a small phone, a normal phone and a foldable."*
- *"Install build/app-release.apk on all bots and check the first launch on each screen size."*
- *"Play my game com.example.game for 10 minutes on the small phone and tell me what feels wrong."*
- *"Review my app like a new user would, in Spanish and with large text, and write a report."*
- *"Run the monkey on all bots for 5000 events and explain any crash."*
- *"Take dark-mode screenshots of the home screen on every bot for the Play Store."*

Reports go to `bot-reports/` with their screenshots and videos. Each one lists what works, what's broken (with
steps to reproduce), what could be better, and what wasn't tested.

Claude follows a few rules here. It never deletes a protected bot, and it asks before anything that erases
data (deleting a bot, clearing or uninstalling an app). It doesn't type your passwords: for Google logins it
guides you and you type.

## Use it from the command line

```text
python bots.py doctor                                  # is this computer ready? how many bots fit?
python bots.py create small --profile phone-small --download
python bots.py create normal --profile phone
python bots.py start small normal                      # boots and waits until they're ready
python bots.py install app-release.apk                 # on every running bot
python bots.py launch com.example.app
python bots.py shot --label first-launch               # bot-reports/shots/<bot>-first-launch-<time>.png
python bots.py ui small                                # what's on screen, with tap coordinates
python bots.py tap-text "Start|Começar" small
python bots.py variants --font 1.3                     # large text on every bot
python bots.py monkey com.example.app --events 3000    # random taps; counts crashes and ANRs
python bots.py stop all
```

Commands that act on bots take bot names or `all`. With no name, they act on every running bot.
`python bots.py <command> --help` shows every option.

## Device profiles

| Profile | Screen | Good for |
| --- | --- | --- |
| `phone-small` | 720x1280, 320 dpi | Cut-off text and buttons pushed off screen. Most layout bugs show up here first. |
| `phone` | 1080x2400, 420 dpi | The typical phone. The default. |
| `phone-large` | 1344x2992, 480 dpi | Large high-density phones. |
| `foldable` | 2076x2152 open | Near-square screens that break phone layouts. |
| `tablet` | 2560x1600, 320 dpi | Tablets in landscape. |

Every profile runs Android 15 (API 35) by default; `--api` picks another version. Add `--play` for a Play Store
image (see [Play Store closed tests](#play-store-closed-tests)). Use `variants --screen` to fake other sizes on
a running bot without creating a new one.

## Commands

| Command | What it does |
| --- | --- |
| `doctor` | Checks the SDK, Java, hardware acceleration, RAM and disk, and says how many bots fit. |
| `profiles` | Lists the device profiles. |
| `create NAME --profile P [--play] [--download]` | Creates a bot. `--download` fetches the Android system image if missing (about 1.5 GB) and accepts the SDK licenses. |
| `adopt AVD [--name N] [--protect]` | Turns an emulator you already have into a bot. |
| `list [--avds]` | Bots and whether they're running. `--avds` also shows emulators that aren't bots yet. |
| `start BOTS [--headless] [--cold]` | Starts bots and waits until Android has booted. Refuses if RAM is too low (`--force` to override). |
| `stop [BOTS]` | Shuts bots down. |
| `protect` / `unprotect BOTS` | Protected bots can't be deleted. |
| `delete BOT --yes` | Deletes a bot and its emulator for good. |
| `snapshot save\|load\|list BOT [NAME]` | Saves or restores the whole emulator state, for example right after a Google login. |
| `install FILE [BOTS] [--grant]` | Installs an `.apk`, `.aab`, `.apks` or a folder of split APKs. |
| `launch PACKAGE [BOTS]` | Opens an app. |
| `app stop\|clear\|uninstall PACKAGE [BOTS]` | Force-stops an app, erases its data, or removes it. |
| `info [BOTS] [--package P]` | Device facts, plus the installed version of an app and where it came from (Play Store or adb). |
| `shot [BOTS] [--label L] [--max PX]` | Screenshots. `--max` shrinks them and prints the scale to use with `tap`. |
| `record [BOTS] --seconds N` | Screen video, up to 180 seconds. |
| `ui BOT` | On-screen elements with their tap coordinates (apps only; games show nothing). |
| `tap X Y` / `tap-text REGEX` / `swipe X1 Y1 X2 Y2` / `type TEXT` / `key NAME` | Touch and keys. `key` knows back, home, enter, recents and more. |
| `rotate portrait\|landscape\|auto` | Screen rotation. |
| `variants [--package P --lang L] [--dark on\|off] [--font F] [--screen WxH@DPI] [--reset]` | Changes the app's language (Android 13+), dark mode, text size or the simulated screen. |
| `crashwatch [BOTS] [--package P] [--minutes M]` | Watches the logs for crashes, ANRs and engine errors (Unity, Flutter) while someone plays. |
| `monkey PACKAGE [BOTS] [--events N] [--seed S]` | Random taps and swipes. Reports crashes and ANRs. The same `--seed` repeats a run exactly. |
| `logcat BOT [--package P] [--errors]` | Recent log lines. |

## Apps and games

**Apps** built with standard Android views, Jetpack Compose, Flutter or React Native show up in `ui`. Every
labeled element is listed with its tap coordinates, so both people and Claude can click by name
(`tap-text "Settings"`). If an app screen shows almost nothing in `ui`, TalkBack can't read it either: that is
an accessibility bug worth reporting.

**Games** (Unity, Godot, Unreal, web canvases) draw their own pixels, so they're played from screenshots:

```text
python bots.py shot small --max 1280        # prints "scale 1.0" or e.g. "scale 1.345"
python bots.py tap 640 410 small --scale 1.345
python bots.py crashwatch small --package com.example.game --minutes 30   # in another terminal
```

The skill has a [game testing guide](plugin/skills/mobile-bots/references/games.md) with what to check: first
launch time, control size, safe areas around notches, pause on back/home, PC-only hints left in a phone build,
and more.

## Play Store closed tests

To test exactly what your testers get from Google Play, create bots with `--play`. One person then signs in to
a Google test account on each bot, joins the test and installs the app from the Play Store. Google blocks
automated sign-ins, so this step can't be scripted. Afterwards, `snapshot save BOT logged-in` and
`protect BOT` keep that work safe.

The full steps are in [play-store.md](plugin/skills/mobile-bots/references/play-store.md).

A build you compiled yourself won't install over the Play Store version, because Google re-signs apps. `install`
tells you when that happens. Uninstalling the Play version erases its data.

## Where things are stored

| What | Where |
| --- | --- |
| Bot list (names, ports, protection) | `~/.mobile-bots/bots.json` (set `MOBILE_BOTS_HOME` to move it) |
| Emulator logs | `~/.mobile-bots/logs/` |
| Emulators | The standard Android place: `~/.android/avd/`, as `bot_<name>` |
| Screenshots, videos, crash logs and reports | `bot-reports/` in the folder you run it from (`--out` to change) |

Bots are ordinary Android emulators, so Android Studio's Device Manager shows and runs them too.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Java 17+ ... NOT FOUND` | Install Android Studio (it ships Java), or set `JAVA_HOME` to a JDK 17 or later. An older `JAVA_HOME` is skipped automatically. |
| `Hardware acceleration: NOT AVAILABLE` | Windows: turn on *Windows Hypervisor Platform* and restart. Linux: `sudo apt install qemu-kvm` (or your distro's package), then `sudo usermod -aG kvm $USER` and log in again. |
| `system image not installed` | Add `--download` to `create`. |
| `port ... is used by another emulator` | An emulator started outside this tool took the port. Close it, or `adopt` that emulator. |
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | The installed copy is signed with another key (for example from the Play Store). Uninstall it first (`app uninstall`), which erases its data. |
| `INSTALL_FAILED_VERSION_DOWNGRADE` | A newer version is installed. Uninstall it first, or raise your `versionCode`. |
| A bot takes minutes to boot, or the computer freezes | Too many bots for your RAM. Run fewer. Small 2 GB profiles struggle most when the computer is busy. |
| `python` not found on Linux | Use `python3`. |
| Running on a server or in CI | `start --headless` runs without a window and uses software rendering. |

## Limits

- Android only. iOS simulators need a Mac and Xcode, which this tool doesn't cover.
- Emulators are not real phones: loading times and frame rates are only a rough guide. Confirm performance
  problems on a real low-end device.
- `adb` can't send multi-touch (pinch, two fingers), and sensors and the camera are simulated.
- Google sign-in and joining a closed test must be done by a person, once per bot.
- On Linux and macOS with ARM processors, the tool uses `arm64-v8a` system images automatically, but some
  Play Store images exist only for `x86_64`.

## Contributing

Issues and pull requests are welcome. The whole tool is
[`plugin/skills/mobile-bots/scripts/bots.py`](plugin/skills/mobile-bots/scripts/bots.py), and Claude's
instructions are in [`SKILL.md`](plugin/skills/mobile-bots/SKILL.md). Please keep the tool free of dependencies
and test it on at least one OS before opening a pull request.

## License

[MIT](LICENSE)
