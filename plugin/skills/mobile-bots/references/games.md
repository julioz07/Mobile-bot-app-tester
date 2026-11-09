# Testing games with bots

Game engines (Unity, Godot, Unreal, Flutter Flame, web canvases) draw their own pixels, so Android's
UI tree (`ui`) is empty. You play by looking at screenshots and tapping coordinates.

## The loop

```
bots.py shot <bot> --max 1280 --label step3     # prints the file and "scale S"
# read the PNG, decide where to touch
bots.py tap 640 410 <bot> --scale S             # coordinates measured on the PNG
bots.py swipe 300 900 300 400 <bot> --ms 300 --scale S
```

- `--scale` converts screenshot pixels to device pixels. Without `--max` (full-size screenshots) the
  scale is 1 and you can omit it. Each bot has its own scale; don't reuse one bot's scale on another.
- Wait between actions: games animate. One to three seconds is usually right; loading screens take longer.
- Hold or drag gestures: `swipe` with the same start and end point and a long `--ms` is a long press.
- Landscape games: the screenshot comes out rotated already; coordinates still match it.
- Text entry in games often uses a custom keyboard. If `type` does nothing, tap the on-screen keys.

## Watching for problems while playing

Start a watcher before playing, in the background:

```
bots.py crashwatch <bot> --package <pkg> --minutes 30
```

It catches Java crashes, native crashes (`Fatal signal`), ANRs, and engine errors such as `E/Unity` and
`E/flutter`. Note what you were doing when an event appears.

## What to check in a game

- **First launch:** time to the first playable screen on the smallest bot. Long black screens feel like a crash.
- **Controls:** are they reachable with thumbs, and big enough (about 48 dp, so roughly 7 mm)? Are PC hints
  ("Click", "Press 1/2/3", keyboard keys) left in a phone build?
- **Safe areas:** notches, the gesture bar and rounded corners. Check HUD elements at the edges on every bot.
- **Pause:** the Android back button and `key home` then `launch` should pause, not lose progress.
- **Rotation:** does it lock to its orientation, or break when the phone turns?
- **Text:** fits on `phone-small`, follows the phone language (`variants --lang`), no overlap with the HUD.
- **Ads (if any):** emulators always get test ads; check they don't cover controls and can be closed.

## Limits to report honestly

- Emulator frame rates and loading times are not a real phone's. Report slowness as "check on a real
  low-end phone", not as a fact.
- Multi-touch (pinch, two-finger gestures) can't be sent with `adb input`. Say it wasn't tested.
- Sensors (gyro, accelerometer) and camera are simulated; test them on a real device.
