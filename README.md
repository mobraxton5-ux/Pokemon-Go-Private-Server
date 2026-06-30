# Pokemon-Go-Private-Server

  POKEMON GO - HOME SERVER  (version 0.29, the original 2016 game)


WHAT THIS IS
  A personal, offline Pokemon GO server. You log in with ANY name (no
  account needed) and walk a map of your real neighborhood full of
  PokeStops and Gyms you can spin for items.

  Note: wild Pokemon do NOT appear. Their 3D models only ever lived on
  Niantic's servers (shut down years ago) and were never in the app, so
  there's no way to show them. Everything else works - login, your
  character, the map, and spinnable PokeStops + Gyms.

WHAT YOU NEED
  - This Windows PC (runs the server)
  - An Android phone (runs the game) -- iPhone will NOT work
  - Both on the SAME Wi-Fi network

FILES IN THIS FOLDER
  - Start-Pokemon-GO-Server.exe ... the server (runs on this PC)
  - pokemon-go-0.29.apk .......... the game (install on the phone)
  - ca.crt ....................... a security certificate (install on phone, ONE time)


============================================================
  ONE-TIME PHONE SETUP  (do this once)
============================================================

1) Copy "pokemon-go-0.29.apk" and "ca.crt" onto the phone (USB, email, etc.).

2) Install the app: tap pokemon-go-0.29.apk. If it warns about "unknown
   sources," allow it. (If it says "App not installed," uninstall any other
   Pokemon GO first.)

3) Install the certificate:
   Settings -> Security -> "Install a certificate" -> "CA certificate"
   -> choose ca.crt.  (Exact wording varies by phone; search Settings for
   "certificate" if needed. Accept the warning.)

4) Set up location (so the map works indoors):
   a) Install "Fake GPS Location" (by Lexa) from the Play Store.
   b) Unlock Developer options: Settings -> About phone -> tap "Build
      number" 7 times.
   c) Settings -> Developer options -> "Select mock location app" -> Fake GPS.
   d) Settings -> Location -> set the mode to "GPS only" (NOT High accuracy).


============================================================
  EACH TIME YOU PLAY
============================================================

ON THE PC:
  1) Double-click  Start-Pokemon-GO-Server.exe
  2) A black window opens and prints a line like:
            Point the phone's Wi-Fi DNS at:   192.168.1.50
     Note that number. KEEP THIS WINDOW OPEN while you play.

ON THE PHONE:
  3) Open "Fake GPS Location," drop the pin where you want to be, press PLAY.
  4) Wi-Fi -> tap your network -> edit/advanced -> "IP settings" = Static
     -> set "DNS 1" to the number from step 2 -> leave "DNS 2" blank -> Save.
  5) Open Pokemon GO. Enter ANY username and ANY password -> you're in.
  6) You'll land on the map with PokeStops and Gyms around you.
     Tap a stop, swipe the photo disc to spin it, and grab the items!

TO STOP: close the black server window on the PC.


============================================================
  TROUBLESHOOTING
============================================================

- Stuck on the loading screen / "unable to authenticate":
    * The server window must be OPEN on the PC.
    * Phone Wi-Fi "DNS 1" must EXACTLY match the number the server printed.
    * Phone and PC must be on the SAME Wi-Fi.

- Map loads but NO PokeStops/Gyms:
    * Make sure "Fake GPS Location" is running (you pressed PLAY).
    * Location mode must be "GPS only."
    * If the server window shows "(0.00000,0.00000)" your location isn't set
      - fix Fake GPS and reopen the game.

- It worked yesterday but not today:
    * Your PC's Wi-Fi IP can change. Re-run the server, read the NEW number,
      and update the phone's "DNS 1" to match.

Have fun!  (Pokemon and Pokemon GO are trademarks of Nintendo / The Pokemon
Company / Niantic. This is a personal, non-commercial project, not affiliated
with them.)
