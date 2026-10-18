"""Garmin's standard golf club-type IDs, independent of a player's club IDs.

Reference: Garmin DI-GOLF CLUB_TYPES v1 export, prepared 2025-08-18, published at
https://github.com/torjussa/golf-analytics/blob/main/data/DI-GOLF/Golf-CLUB_TYPES.json

Only the static type catalog is used, never that repository's player data.
Live catalog labels and the player's custom club names take precedence.
"""

GARMIN_CLUB_TYPE_NAMES = {
    "0": "Unknown club",
    "1": "Driver",
    "2": "3 wood",
    "3": "5 wood",
    "4": "1 hybrid",
    "5": "2 hybrid",
    "6": "3 hybrid",
    "7": "4 hybrid",
    "8": "5 hybrid",
    "9": "6 hybrid",
    "10": "1 iron",
    "11": "2 iron",
    "12": "3 iron",
    "13": "4 iron",
    "14": "5 iron",
    "15": "6 iron",
    "16": "7 iron",
    "17": "8 iron",
    "18": "9 iron",
    "19": "Pitching wedge",
    "20": "Gap wedge",
    "21": "Sand wedge",
    "22": "Lob wedge",
    "23": "Putter",
    "24": "2 wood",
    "25": "4 wood",
    "26": "7 wood",
    "27": "9 wood",
    "28": "11 wood",
    "29": "13 wood",
    "30": "15 wood",
    "31": "17 wood",
    "32": "19 wood",
    "33": "21 wood",
    "34": "23 wood",
    "35": "25 wood",
    "36": "7 hybrid",
    "37": "8 hybrid",
    "38": "9 hybrid",
    "39": "PW hybrid",
    "40": "GW hybrid",
    "41": "SW hybrid",
    "42": "LW hybrid",
}
