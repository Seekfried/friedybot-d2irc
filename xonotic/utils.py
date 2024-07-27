import re
import logging
import requests

utils_logger = logging.getLogger("xonoticUtils")

# this was basically taken from rcon2irc.pl
def rgb_to_simple(r: int, g: int,b: int) -> int:

    min_ = min(r,g,b)
    max_ = max(r,g,b)

    v = max_ / 15.0
    s = (1 - min_/max_) if max_ != min_  else 0
    h = 0
    if s < 0.2:
        return 0 if v < 0.5 else 7

    if max_ == min_:
        h = 0
    elif max_ == r:
        h = (60 * (g - b) / (max_ - min_)) % 360
    elif max_ == g:
        h = (60 * (b - r) / (max_ - min_)) + 120
    elif max_ == b:
        h = (60 * (r - g) / (max_ - min_)) + 240

    color_thresholds =[(36,1), (80,3), (150,2),(200,5),(270,4),(330,6)]

    for threshold, value in color_thresholds:
        if h < threshold:
            return value

    return 1

# Discord colors
def discord_colors(qstr: str) -> str:
    _discord_colors = [ 0, 31, 32, 33, 34, 36, 35, 0, 0, 0 ]

    _all_colors = re.compile(r'(\^\d|\^x[\dA-Fa-f]{3})')
    #qstr = ''.join([ x if ord(x) < 128 else '' for x in qstr ]).replace('^^', '^').replace(u'\x00', '') # strip weird characters
    parts = _all_colors.split(qstr)
    result = "```ansi\n"
    oldcolor = None
    while len(parts) > 0:
        tag = None
        txt = parts[0]
        if _all_colors.match(txt):
            tag = txt[1:]  # strip leading '^'
            if len(parts) < 2:
                break
            txt = parts[1]
            del parts[1]
        del parts[0]

        if not txt or len(txt) == 0:
            # only colorcode and no real text, skip this
            continue

        color = 7
        if tag:
            if len(tag) == 4 and tag[0] == 'x':
                r = int(tag[1], 16)
                g = int(tag[2], 16)
                b = int(tag[3], 16)
                color = rgb_to_simple(r,g,b)
            elif len(tag) == 1 and int(tag[0]) in range(0,10):
                color = int(tag[0])
        color = _discord_colors[color]
        if color != oldcolor:
            result += "\u001b[1;" + str(color) + "m"
        result += txt
        oldcolor = color
    result += "\u001b[0m```"
    return result

# Method taken from zykure's bot: https://gitlab.com/xonotic-zykure/multibot
def irc_colors( qstr: str) -> str:
    _irc_colors = [ -1, 4, 9, 8, 12, 11, 13, -1, -1, -1 ]

    _all_colors = re.compile(r'(\^\d|\^x[\dA-Fa-f]{3})')
    #qstr = ''.join([ x if ord(x) < 128 else '' for x in qstr ]).replace('^^', '^').replace(u'\x00', '') # strip weird characters
    parts = _all_colors.split(qstr)
    result = "\002"
    oldcolor = None
    while len(parts) > 0:
        tag = None
        txt = parts[0]
        if _all_colors.match(txt):
            tag = txt[1:]  # strip leading '^'
            if len(parts) < 2:
                break
            txt = parts[1]
            del parts[1]
        del parts[0]

        if not txt or len(txt) == 0:
            # only colorcode and no real text, skip this
            continue

        color = 7
        if tag:
            if len(tag) == 4 and tag[0] == 'x':
                r = int(tag[1], 16)
                g = int(tag[2], 16)
                b = int(tag[3], 16)
                color = rgb_to_simple(r,g,b)
            elif len(tag) == 1 and int(tag[0]) in range(0,10):
                color = int(tag[0])
        color = _irc_colors[color]
        if color != oldcolor:
            if color < 0:
                result += "\017\002"
            else:
                result += "\003" + "%02d" % color
        result += txt
        oldcolor = color
    result += "\017"
    return result

def get_statsnames(id):
    #get xonstat player names
    utils_logger.info("get_statsnames: id=%s", id)
    header =  {'Accept': 'application/json'}
    response = requests.get("https://stats.xonotic.org/player/" + str(id), headers=header)
    utils_logger.info("get_statsnames: response.status_code=%s", response.status_code)
    player = response.json()
    if response.status_code == 200:
        return player["player"]["nick"],player["player"]["stripped_nick"]
    else:
        utils_logger.error("Error in get_statsnames. Status code: ", response.status_code)
        return None

def get_gamestats(id, gtype):        
    #get xonstat player elo for specific gametype
    utils_logger.info("get_gamestats: id=%s, gtype=%s", id, gtype)
    elo = 0
    header =  {'Accept': 'application/json'}
    response = requests.get("https://stats.xonotic.org/player/" + str(id)+ "/skill?game_type_cd=" + gtype, headers=header)
    utils_logger.info("get_gamestats: response.status_code=%s", response.status_code)
    player = response.json()
    if response.status_code == 200:
        if len(player):
            elo = player[0]["mu"]
    else:
        utils_logger.error("Error in get_gamestats. Status code: ", response.status_code)
        return None
    return elo