@@ -11,12 +11,12 @@ WHAT'S IN THIS FOLDER
                                   use whichever one your phone's installer will open)
To add pokestops and spawns other than the base go to "http://127.0.0.1:8080" while your server is open.
LINKS: https://pgorelease.nianticlabs.com/shop (shop)
https://pokemongo.zendesk.com/hc (put a stop at your house)

============================================================

  ONE-TIME PHONE SETUP  (do this once)
============================================================

1) Copy pokemon-go-0.29.apk and ca.crt (or ca.pem) onto the phone.

1) Copy pokemon-go-0.29.apk and ca.pem onto the phone.

2) Install the game: tap pokemon-go-0.29.apk. Allow "install from unknown
   sources" if asked. If it says "App not installed," uninstall any other
@@ -28,9 +28,8 @@ To add pokestops and spawns other than the base go to "http://127.0.0.1:8080" wh
   Accept the warning. (You may need a screen-lock PIN set first.)


============================================================
  EACH TIME YOU PLAY!
============================================================


ON THE PC:
  1) Double-click  Start-Pokemon-GO-Server.exe
@@ -50,9 +49,9 @@ ON THE PHONE:
TO STOP: close the black server window on the PC.


============================================================

  WORLD MANAGER  (place your own PokeStops, Gyms and Pokemon)
============================================================


While the server is running, open this on the PC's browser:

        http://127.0.0.1:8080
You get a map of your neighbourhood. Pick what you want to place
(PokeStop / Gym / Pokemon + species), then CLICK THE MAP to drop it at
that exact spot. Click any marker to remove it. Give things names --
"Dad's Porch", "Backyard Arena" -- and the name shows up in game.
  - "Random spawns: ON/OFF" toggles the automatically generated stops and
    wild Pokemon. Turn it OFF if you only want the things you placed.
  - The yellow dot is where your trainer currently is.
  - Changes apply after you restart (quickest). Walk around in game and they appear on the next
    map refresh (a few seconds) 
  - Your placements are saved in places.json next to the .exe, so they
    survive restarts.
QUICK BUILD
  "Build ring" drops a circle of PokeStops (and a Gym in the middle) around
  wherever your trainer is standing -- an instant neighbourhood. Choose how
  many stops and how far out (in metres) before clicking.
EVENTS
  Change what spawns, live:
    - Density ......... how many wild Pokemon around you (0-60)
    - All 151 / From list / One species .. what can appear
    - CP range ........ how strong they are
  One-click presets: Normal, Swarm, Pikachu Festival, Starter Party,
  Legendary Hunt, High CP. Pick one and it applies.
  (Example: "One species" + Pikachu = a Pikachu festival in your street.)
  Note: shiny Pokemon aren't available -- the 2016 game predates them.
The page is only reachable from this PC (never from the phone or the
internet). The map picture needs internet; placing things works either way.
============================================================
  TROUBLESHOOTING
============================================================
- Stuck on the loading screen / "unable to authenticate":
    * The server window must be OPEN on the PC.
    * Phone Wi-Fi "DNS 1" must EXACTLY match the number the server printed.
    * Phone and PC must be on the SAME Wi-Fi.
    * Re-check the certificate was installed (step 3).
- Map loads but no Pokemon / no PokeStops:
    * (still optional) Make sure "Fake GPS Location" is running (you pressed PLAY).
    * Location mode must be "GPS only."
    * If the server window shows "(0.00000,0.00000)" your location isn't set --
      use Fake GPS and reopen the game.
- Phone gets STUCK on the loading screen (spinner never finishes):
    * The full Pokemon data may be too much for a first sync. Run
      "Start-Server (no-Pokemon fallback).bat" instead -- you'll reach the map
      with PokeStops/Gyms but no wild Pokemon.
- It worked yesterday but not today:
    * Your PC's Wi-Fi IP can change. Re-run the server, read the NEW number,
      and update the phone's "DNS 1" to match.
- Want to play away from home (cellular / different Wi-Fi):
    * See VPN.md in the project (Tailscale) -- point the phone's DNS at the PC's
      Tailscale IP and run the server the same way.
- Notes:
  * Shiny Pokemon and custom "events" aren't here yet -- 0.29 predates shinies
    (2017). Spawn variety / density / event controls are coming later.
  * Pokemon and Pokemon GO are trademarks of Nintendo / Creatures / GAME FREAK /
    Niantic. This is a personal, non-commercial project, not affiliated with them.
- More Notes (not ai): Yes I'm trying to do events soon. I'm also gonna try to get the Pokestop nomination feature working because I want to release the server global. After that I will still have the public one but the newer one will be global and the public one for download will still be available. Cheers!
Have fun!  (Pokemon and Pokemon GO are trademarks of Nintendo / The Pokemon
Company / Niantic. This is a personal, non-commercial project, not affiliated
with them.)
