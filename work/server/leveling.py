"""
The 2016 Pokemon-level curve -- the fine-grained power-up table.

gamedata.CPM (from the game master) has one cp_multiplier per whole trainer level
(40 values). The REAL game powers a Pokemon up in HALF-level steps, each with its
own multiplier and its own escalating Stardust/Candy price -- exactly the numbers
the client shows on the power-up button. Those half-steps aren't in the game
master, so this table carries them, transcribed from the community leveling
spreadsheet (which is itself derived from the client, so charging these keeps the
server's price and the button's price identical).

LEVELS[i] = (cp_multiplier, stardust_to_next, candy_to_next) for Pokemon-level
step i (0-based; step 0 is a freshly hatched/level-1 Pokemon). The stardust/candy
are what it costs to advance FROM this step to the next. The last entry is
Pokemon level 40 (CpMultiplier 0.7903) -- the real ceiling; you cannot power past
it, so its cost is never charged.
"""

# (cpm, stardust, candy)  -- level 1 .. 40 in 0.5 steps (79 steps)
LEVELS = [
    (0.0940000, 200, 1), (0.1351374, 200, 1), (0.1663979, 200, 1), (0.1926509, 200, 1),
    (0.2157325, 400, 1), (0.2365727, 400, 1), (0.2557201, 400, 1), (0.2735304, 400, 1),
    (0.2902499, 600, 1), (0.3060574, 600, 1), (0.3210876, 600, 1), (0.3354450, 600, 1),
    (0.3492127, 800, 1), (0.3624578, 800, 1), (0.3752356, 800, 1), (0.3875924, 800, 1),
    (0.3995673, 1000, 1), (0.4111936, 1000, 1), (0.4225000, 1000, 1), (0.4329264, 1000, 1),
    (0.4431076, 1300, 2), (0.4530600, 1300, 2), (0.4627984, 1300, 2), (0.4723361, 1300, 2),
    (0.4816850, 1600, 2), (0.4908558, 1600, 2), (0.4998584, 1600, 2), (0.5087018, 1600, 2),
    (0.5173940, 1900, 2), (0.5259425, 1900, 2), (0.5343543, 1900, 2), (0.5426358, 1900, 2),
    (0.5507927, 2200, 2), (0.5588306, 2200, 2), (0.5667545, 2200, 2), (0.5745692, 2200, 2),
    (0.5822789, 2500, 2), (0.5898879, 2500, 2), (0.5974000, 2500, 2), (0.6048188, 2500, 2),
    (0.6121573, 3000, 3), (0.6194041, 3000, 3), (0.6265671, 3000, 3), (0.6336492, 3000, 3),
    (0.6406530, 3500, 3), (0.6475810, 3500, 3), (0.6544356, 3500, 3), (0.6612193, 3500, 3),
    (0.6679340, 4000, 3), (0.6745819, 4000, 3), (0.6811649, 4000, 4), (0.6876849, 4000, 4),
    (0.6941437, 4500, 4), (0.7005429, 4500, 4), (0.7068842, 4500, 4), (0.7131691, 4500, 4),
    (0.7193991, 5000, 4), (0.7255756, 5000, 4), (0.7317000, 5000, 4), (0.7347410, 5000, 4),
    (0.7377695, 6000, 6), (0.7407856, 6000, 6), (0.7437894, 6000, 6), (0.7467812, 6000, 6),
    (0.7497610, 7000, 8), (0.7527291, 7000, 8), (0.7556855, 7000, 8), (0.7586304, 7000, 8),
    (0.7615638, 8000, 10), (0.7644861, 8000, 10), (0.7673972, 8000, 10), (0.7702973, 8000, 10),
    (0.7731865, 9000, 12), (0.7760650, 9000, 12), (0.7789328, 9000, 12), (0.7817901, 9000, 12),
    (0.7846370, 10000, 15), (0.7874736, 10000, 15), (0.7903000, 10000, 15),
]

MAX_INDEX = len(LEVELS) - 1          # Pokemon level 40


def level_index_for_cpm(cpm):
    """The step whose multiplier is closest to `cpm`. A caught Pokemon's CP was
    generated free-form, so its multiplier rarely lands exactly on a step; snap it
    to the nearest real level so a power-up moves it one genuine notch."""
    best, bd = 0, 1e9
    for i, (m, _d, _c) in enumerate(LEVELS):
        d = abs(m - cpm)
        if d < bd:
            best, bd = i, d
    return best


def max_index_for_trainer(trainer_level):
    """A Pokemon can be powered up to two levels above your trainer level -- i.e.
    four half-steps. Beyond that the button is greyed until you level up. Trainer
    40 unlocks the full ceiling (Pokemon level 40 = step index 78)."""
    return min(MAX_INDEX, 2 * int(trainer_level) + 2)
