from model import *
from xonotic.utils import *
from datetime import datetime
from copy import deepcopy
from utils import create_logger
from peewee_migrate import Router

db_logger = create_logger("dbConnector")

class DatabaseConnector:
    
    def __init__(self):
        db_logger.info("Initialize db connection")
        db.close()
        router = Router(db)
        router.run()
        db.close()
        self.delete_active_games()

    def __get_active_games(self) -> PickupGames:
        games = PickupGames.select().where(PickupGames.isPlayed == False)
        return games

    def __get_active_player_entries(self, player) -> PickupEntries:
        if player is not None:
            return PickupEntries.select().join(PickupGames).where(PickupGames.isPlayed == False).where(PickupEntries.playerId == player)
        return None
    
    def __get_found_matchtext(self, puggame:PickupGames, forcedstart: bool = False) -> dict:
        #excutes in case match is found and sends notification to all players
        result = {}
        has_teams: bool = False
        ircresult: str = ""
        discordresult: str = ""

        db_logger.info("found_match: puggame=%s", puggame)
        pugplayers = PickupEntries.select().where(PickupEntries.gameId == puggame.id)
        db_logger.info("found_match: pugplayers.count()=%s", pugplayers.count())
        if pugplayers.count() == puggame.gametypeId.playerCount or forcedstart:
            puggame.isPlayed = True
            puggame.save()
            if puggame.gametypeId.playerCount == puggame.gametypeId.teamCount or puggame.gametypeId.statsName is None:
                ircresult = puggame.gametypeId.title + " ready! Players are: "
                discordresult = puggame.gametypeId.title + " ready! Players are: "
                for pugplayer in pugplayers:
                    #self.__withdraw_player_from_all(pugplayer.playerId)
                    if pugplayer.addedFrom == "irc":
                        discordresult += pugplayer.playerId.ircName + " (" + pugplayer.playerId.statsDiscordName + ") "
                        ircresult += pugplayer.playerId.ircName + " (" + pugplayer.playerId.statsIRCName + ") "
                    else:
                        discordresult += pugplayer.playerId.discordMention + " (" + pugplayer.playerId.statsDiscordName + ") "
                        ircresult += pugplayer.playerId.discordName + " (" + pugplayer.playerId.statsIRCName + ") "
                    self.__withdraw_player_from_all(pugplayer.playerId)
            else:
                has_teams = True
                team_result = self.__get_teamtext(pugplayers, puggame.gametypeId.teamCount, puggame.gametypeId.statsName)
                ircresult = team_result["irc"]
                discordresult = team_result["discord"]
                ircresult.insert(0, puggame.gametypeId.title + " ready! Players are: ")
                discordresult.insert(0, puggame.gametypeId.title + " ready! Players are: ")
            result = {"has_teams": has_teams, "irc": ircresult, "discord": discordresult, "playercount": puggame.gametypeId.playerCount}
            self.__delete_all_pickupgames_without_entries()
        return result
    
    def __get_player(self, user, chattype=None) -> Players:
        player = None
        user = user if type(user)==str else user.name
        if chattype is None:
            player = Players.select().where((Players.ircName == user)|(Players.discordName == user)).first()
        elif chattype == "irc":
            player = Players.select().where(Players.ircName == user).first()
        else:
            player = Players.select().where(Players.discordName == user).first()
        return player
    
    def __get_player_subscriptions(self, player) -> Subscriptions:
        if player:
            return Subscriptions.select().where(Subscriptions.playerId == player)
        return None

    def __get_teamtext(self, players, teamcount, xongametype):
        #logger.info("found_match: players=%s, teamcount=%s, xongametype=%s", players, teamcount, xongametype)
        matchtext = {"irc":[],"discord":[]}
        teams = [[] for _ in range(teamcount)]
        total_elo = [0] * teamcount
        players_with_elo = []

        for player_entry in players:
            self.__withdraw_player_from_all(player_entry.playerId)
            if player_entry.playerId.statsId:
                players_with_elo.append({"player": player_entry, "elo": get_gamestats(player_entry.playerId.statsId, xongametype)})
            else:
                players_with_elo.append({"player": player_entry, "elo": 0})

        # Sort players by elo rating in descending order
        players_with_elo.sort(key=lambda x: x['elo'], reverse=True)

        # Distribute players to teams
        for player in players_with_elo:
            # Assign the player to the team with the least total elo
            team_index = total_elo.index(min(total_elo))
            teams[team_index].append(player)
            total_elo[team_index] += player['elo']
    
        # Prepare the results with team information
        team_info = []

        for team in teams:
            if team:
                captain = max(team, key=lambda x: x['elo'])
                average_elo = sum(player['elo'] for player in team) / len(team)
                team_info.append({
                    'team': team,
                    'captain': captain,
                    'average_elo': average_elo
                })     

        # Format the Teamresult for irc and discord
        captains_discord = "Captains are: "
        captains_irc = "Captains are: "
        for index, team in enumerate(team_info, start=1):
            irc_entry = f"Team {index}: "
            discord_entry = f"Team {index}: "
            captain = team['captain']
            for team_member in team['team']:
                #self.__withdraw_player_from_all(team_member['player'].playerId)
                if team_member['player'].addedFrom == "irc":
                    discord_entry += team_member['player'].playerId.ircName + " (" + team_member['player'].playerId.statsName + ") "
                    irc_entry += team_member['player'].playerId.ircName + " (" + team_member['player'].playerId.statsIRCName + ") "
                else:
                    discord_entry += team_member['player'].playerId.discordMention + " (" + team_member['player'].playerId.statsName + ") "
                    irc_entry += team_member['player'].playerId.discordName + " (" + team_member['player'].playerId.statsIRCName + ") "

            captains_discord += f"{captain['player'].playerId.statsDiscordName} ({captain['elo']:.2f}) "
            discord_entry += f"Average Elo: {team['average_elo']:.2f} "
            captains_irc += f"{captain['player'].playerId.statsIRCName} ({captain['elo']:.2f}) "
            irc_entry += f"Average Elo: {team['average_elo']:.2f} "
            matchtext["irc"].append(irc_entry)
            matchtext["discord"].append(discord_entry)
        
        matchtext["irc"].append(captains_irc)
        matchtext["discord"].append(captains_discord)
        return matchtext
    
    def __delete_all_pickupgames_without_entries(self):
        games: list[PickupGames] = self.__get_active_games()

        for game in games:
            if len(game.addedplayers) == 0:
                game.delete_instance()        
        
    def __withdraw_player_from_all(self, player) -> bool:
        #check if player is already in database
        if player is not None:
            gameentries = self.__get_active_player_entries(player)

        if player is None or not gameentries.exists():
            return False
        
        for gameentry in gameentries:
            self.__withdraw_player_from_gametype(player, gameentry.gameId.gametypeId.title)
        return True
    
    def __withdraw_player_from_gametype(self, player, gametypetitle) -> bool:
        if player is None:
            return False
        
        gtype = GameTypes.select().where(GameTypes.title == gametypetitle).first()
        if gtype is not None: 
            games = PickupGames.select().where(PickupGames.gametypeId == gtype.id, PickupGames.isPlayed == False)
            for game in games:
                PickupEntries.delete().where(PickupEntries.playerId == player, PickupEntries.gameId == game.id).execute()
        return True
    
    def add_gametypes(self, gt_title, gt_playercount, gt_teamcount, gt_xonstatname) -> str:
        message = ""

        db.connect()
        try:
            game = GameTypes(title=gt_title, playerCount=gt_playercount, teamCount=gt_teamcount, statsName=gt_xonstatname)
            game.save()
            message = "Gametype " + gt_title + " added."
        except:
            message = "Gametype already registered!"
        
        db.close()
        return message

    def add_player_to_games(self, user, gametypes:list[str], chattype, recipient=None) -> tuple[bool, list[str], dict]:
        db_logger.info("add_player_to_games: user=%s, gametypes=%s, chattype=%s", user, gametypes, chattype)
        result: bool = False
        error_message = []
        found_match = {}

        db.connect()
        
        #check where user added from
        if recipient is not None:
            player = self.__get_player(recipient)
        else:        
            player = self.__get_player(user,chattype)
            
        try:
            #!add without gametype
            if player:
                if len(gametypes) == 0:
                    games = self.__get_active_games()

                    #no pickup game found and show possible gametypes
                    if not games.exists():
                        gametype_result = []
                        for gametype in GameTypes:
                            gametype_result.append(gametype.title)
                        error_message.append("No game found! Possible gametypes: " + ", ".join(gametype_result))
                    #adds to all current active pickup games
                    else:
                        for game in games:
                            pickentry = PickupEntries.select().where(PickupEntries.playerId == player.id, PickupEntries.gameId == game.id).first()
                            if pickentry is None:
                                __addedFrom: str = chattype
                                if recipient is not None:
                                    if player.ircName:
                                        __addedFrom = "irc"
                                    else:
                                        __addedFrom = "discord"
                                pickentry = PickupEntries(playerId=player.id, gameId=game.id, addedFrom=__addedFrom)
                                pickentry.save()
                                result = True
                                found = self.__get_found_matchtext(game)
                                if not found_match or (found["playercount"] > found_match["playercount"]):
                                    found_match = deepcopy(found)
                            else:
                                error_message.append("Already added for " + pickentry.gameId.gametypeId.title)
                #add with gametypes
                #example: !add duel 2v2tdm
                else:
                    for gtypeentries in gametypes:
                        gtype = GameTypes.select().where(GameTypes.title == gtypeentries).first()
                        if gtype is not None:
                            game = PickupGames.select().where(PickupGames.gametypeId == gtype.id, PickupGames.isPlayed == False).first()
                            if game is None:
                                game = PickupGames(gametypeId=gtype.id, isPlayed=False)
                                game.save()
                            pickentry = PickupEntries.select().where(PickupEntries.playerId == player.id, PickupEntries.gameId == game.id).first()
                            if pickentry is None:
                                pickentry = PickupEntries(playerId=player.id, gameId=game.id, addedFrom=chattype)
                                pickentry.save()
                                result = True
                                found = self.__get_found_matchtext(game)
                                if found:
                                    if not found_match or (found["playercount"] > found_match["playercount"]):
                                        found_match = deepcopy(found)
                            else:
                                error_message.append("Already added for " + pickentry.gameId.gametypeId.title)
            else:
                if recipient is not None:
                    error_message.append(recipient + " needs to register first (!register) to be added for games!")
                else:
                    error_message.append("You need to register first (!register) to add for games!")
        except Exception as e:
            db_logger.error("Something wrong with add_player_to_games: ", e)
        db.close()
        return result, error_message, found_match
    
    def add_server(self, servername: str, serveraddressIPv4: str, serveraddressIPv6: str) -> str:
        message = ""
        db_logger.info("add_server: servername=%s, serveraddressIPv4=%s, serveraddressIPv6=%s", servername, serveraddressIPv4, serveraddressIPv6)
        if not servername:
            db_logger.error("add_server: missing data: servername=%s", servername)
            return "Missing data! servername is required!"
            
        if not serveraddressIPv4 and not serveraddressIPv6:
            db_logger.error("add_server: missing data: serveraddressIPv4=%s, serveraddressIPv6=%s", serveraddressIPv4, serveraddressIPv6)
            return "Missing data! serveraddressIPv4 or serveraddressIPv6 is required!"
            
        db.connect()
        try:
            serv = Servers(serverName=servername, serverIPv4=serveraddressIPv4, serverIPv6=serveraddressIPv6)
            serv.save()
            message = "Server " + servername + " added."
        except:
            message = "Server already registered!" 

        db.close() 
        return message
    
    def add_subscription(self, user, gametypetitle, chattype) -> str:
        discord_name: str = ""
        message: str = ""
        result: bool = False

        db.connect()
        player = self.__get_player(user, chattype)
        if not player:
            message = "You need to register first (!register) to subscribe!"
        else:
            subscriptions = self.__get_player_subscriptions(player)
            gametype = GameTypes.select().where(GameTypes.title == gametypetitle).first()
            if gametype and (not subscriptions or not subscriptions.where(Subscriptions.gametypeId == gametype).exists()):
                result = True
                playersub = Subscriptions(playerId=player,gametypeId=gametype)
                playersub.save()
                if player.discordName:
                    discord_name = player.discordName
            else:
                message = "You can't subscribe to: " + gametypetitle
        db.close()
        return result, message, discord_name

    def delete_active_games(self):
        #Delete pickgames that were not played
        db.connect()
        if PickupGames.table_exists():
            games = PickupGames.delete().where(PickupGames.isPlayed == False)
            games.execute()
        db.close()
    
    def delete_games_without_player(self):
        db.connect()
        games = self.__get_active_games()
        for game in games:
            if len(game.addedplayers) == 0:
                game.delete_instance() 
        db.close()
    
    def delete_gametypes(self, gametypes) -> list[str]:
        messages = []

        db.connect()
        if gametypes:
            for gametypeentry in gametypes:
                gtype = GameTypes.select().where(GameTypes.title == gametypeentry).first()
                if gtype is not None:
                    gtype.delete_instance()
                    messages.append(gametypeentry + " deleted.")
                else:
                    messages.append(gametypeentry + " not found.")
        else:
            messages.append("To delete gametype: !removegametype [<gametypename>]")
        
        db.close()
        return messages

    def delete_server(self, serverlist) -> list[str]:
        messages = []

        db.connect()
        if serverlist:
            for serverentry in serverlist:
                gserver = Servers.select().where(Servers.serverName == serverentry).first()
                if gserver is not None:
                    gserver.delete_instance()
                    messages.append(serverentry + " deleted.")
                else:
                    messages.append(serverentry + " not found.")
        else:
            messages.append("To delete server: !removeserver [<servername>]")

        db.close()
        return messages

    def delete_subscription(self, user, gametypetitle, chattype) -> list[str]:
        discord_name: str = ""
        message: str = ""

        db.connect()
        player = self.__get_player(user, chattype)
        if not player:
            message = "You need to register first (!register) to subscribe!"
        sub_entry = Subscriptions.select().join(GameTypes).where(GameTypes.title == gametypetitle, Subscriptions.playerId == player).first()
        if sub_entry:
            sub_entry.delete_instance()
            if player.discordName:
                discord_name = player.discordName
        else:
            message = "You are not subscribed to: " + gametypetitle

        db.close()
        return message, discord_name
    
    def get_active_games_and_players(self) -> dict:
        # structur of result
        # {"duel": {"irc":["Seek-y"], "discord":[], "playercount":"(1/2)"}, "2v2tdm": {"irc":["Seek-y", "Grunt"], "discord":["Silence"], "playercount":"(3/4)"}} 
        result: dict = {}
        inner_result: dict = {"irc":[], "discord":[], "playercount":""}

        db.connect()
        games: list[PickupGames] = self.__get_active_games()
        if games.exists():
            for game in games:
                result.update({game.gametypeId.title : deepcopy(inner_result) })
                playerentries: list[PickupEntries] = game.addedplayers
                result[game.gametypeId.title]["playercount"] = "(" + str(len(playerentries)) + "/" + str(game.gametypeId.playerCount) + ")"
                for playerentry in playerentries:
                    if playerentry.addedFrom == "irc":
                        result[game.gametypeId.title]["irc"].append(playerentry.playerId.ircName)
                    else:
                        result[game.gametypeId.title]["discord"].append(playerentry.playerId.discordName)

        db.close()
        return result
    
    def get_full_stats(self, player_name: str, chattype: str) -> dict:
        db_logger.info("get_skill_stats: player=%s, chattype=%s", player_name, chattype)
        skill_stats: list[dict] = []
        stats = {}
        stats_id: int = -1
        db.connect()
        player: Players = None

        player = Players.select().where((Players.ircName == player_name)|(Players.discordName == player_name)).first()

        if player is None:
            if player_name.isdigit():
                stats_id = int(player_name)
        else:
            stats_id = player.statsId
        db.close()
    
        db_logger.info("get_skill_stats: player=%s, stats_id=%d", player, stats_id)

        if stats_id != -1:
            skill_stats = get_full_gamestats(stats_id)
            stats = get_full_stats(stats_id)
            if stats.get('player') is not None:
                stats["skill_stats"] = skill_stats
                if chattype == "irc":
                    stats["player"]["colored_name"] = irc_colors(stats["player"]["nick"])
                elif chattype == "discord":
                    stats["player"]["colored_name"] = discord_colors(stats["player"]["nick"])
                else:
                    stats["player"]["colored_name"] = stats["player"]["stripped_nick"]
            
        return stats

    def get_gametype_list(self) -> list[str]:
        #Get a list of strings of all possible gametypes
        result = []

        db.connect()
        for gametype in GameTypes:
            result.append(gametype.title)

        db.close()
        return result

    def get_lastgame(self, chattype) -> str:
        db.connect()
        lastPickupGame = PickupGames.select().where(PickupGames.isPlayed == True).order_by(PickupGames.createdDate.desc()).first()
        lastPickupGamePlayers = lastPickupGame.addedplayers
        resultText = lastPickupGame.gametypeId.title + ", played on " + lastPickupGame.createdDate.strftime("%Y-%m-%d") + " was played with: "
        for player in lastPickupGamePlayers:
            if chattype == "irc":
                playername = player.playerId.ircName if player.playerId.ircName is not None else player.playerId.discordName
                resultText += playername + " " + ("("+player.playerId.statsIRCName + ") " if player.playerId.statsIRCName is not None else "")
            else:
                playername = player.playerId.discordName if player.playerId.discordName is not None else player.playerId.ircName
                resultText += playername + " " + ("("+player.playerId.statsDiscordName + ") " if player.playerId.statsDiscordName is not None else "")
        db.close()

    def get_pickuptext(self) -> tuple[bool, str]:
        #Get string of active pickups with gametype and number of players/player needed 
        #example: "2v2tdm (2/4)"
        db_logger.info("Build pickuptext")
        result: str = ""

        db.connect()
        games: list[PickupGames] = self.__get_active_games()

        for game in games:
            result += game.gametypeId.title + " (" + str(len(game.addedplayers)) + "/" + str(game.gametypeId.playerCount) + ") "
        
        db.close()
        return result
       
    def get_server(self, servername = None) -> tuple[bool, str]:
        result: str = ""
        wrong_server: bool = False

        db.connect()
        if not servername:
            serverresult = []
            for gameserver in Servers:
                serverresult.append(gameserver.serverName)
            result = "Available servers: " + ", ".join(serverresult)
        else:
            server: Servers = Servers.select().where(Servers.serverName == servername).first()
            if server is not None:
                message = "Server: " + server.serverName + " with"
                if server.serverIPv4:
                    message = message + " IPv4: " + server.serverIPv4
                if server.serverIPv6:
                    message = message + " IPv6: " + server.serverIPv6
                result = message
            else:
                wrong_server = True
                result = "Server: " + servername + " not found!"

        db.close()
        return wrong_server, result
    
    def get_server_info(self, servername) -> tuple[bool, list[str]]:
        #TODO use rcon in future
        messages: list[str] = []
        wrong_server: bool = False
        result: bool = False

        db.connect()
        server: Servers = Servers.select().where(Servers.serverName == servername).first()
        if server is not None:
            if server.serverIPv4:
                result, messages = get_serverinfo(server.serverIPv4)
            if not result and server.serverIPv6:
                result, messages = get_serverinfo(server.serverIPv6)
            if not result:
                messages = "Server: " + servername + " offline!"
                wrong_server = True
        else:
            wrong_server = True
            messages = "Server: " + servername + " not found!"
        db.close()
        return wrong_server, messages
    
    def get_subscribed_players(self, gametypetitle:str) -> list[str]:
        result: list[str] = []

        db.connect()
        subscripts = Subscriptions.select().join(GameTypes).where(GameTypes.title == gametypetitle)
        for subscript in subscripts:
            result.append(subscript.playerId.ircName)
        db.close()
        return result

    def get_subscriptions(self, user, chattype) -> list[str]:
        subs: list[str] = []

        db.connect()
        player = self.__get_player(user, chattype)
        if player:
            for subscription in Subscriptions.select().where(Subscriptions.playerId == player):
                subs.append(subscription.gametypeId.title)
        db.close()
        return subs
    
    def get_unbridged_players(self) -> tuple[list[str], list[str]]:
        muted_discord_users = []
        muted_irc_users = []

        db.connect()
        if not Players.table_exists():
            db.close()
            return muted_discord_users, muted_irc_users
        
        players: list[Players] = Players.select().where(Players.shouldBridge == False)
        for player in players:
            if player.discordName:
                muted_discord_users.append(player.discordName)
            if player.ircName:
                muted_irc_users.append(player.ircName)
        db.close()
        return muted_discord_users, muted_irc_users
    
    def has_active_games(self) -> bool:
        result: bool = False

        db.connect()
        games: list[PickupGames] = self.__get_active_games()
        result = games.exists()
        db.close()
        return result
    
    def pugtimer_step(self, mindiff, currenttime, deletetime, warntime) -> tuple[int, bool, bool, dict]:
        #return values 
        # mindiff as int: new min-difference, 
        # has_break as bool: timer should take a break, 
        # has_new_text as bool: should send pickuptext
        # warn_user as dict: {"user": "usernameToWarn", "chattype": "irc"/"discord"} 
        has_break: bool = False
        has_new_text: bool = False
        warn_user: dict = {}

        db.connect()
        pugentries = PickupEntries.select().join(PickupGames).where(PickupGames.isPlayed == False).order_by(PickupEntries.addedDate.asc())
        for pugentry in pugentries:
            pugdiff = round((currenttime - pugentry.addedDate).total_seconds())
            if pugdiff >= deletetime:
                gid = pugentry.gameId
                pugentry.delete_instance()
                game = PickupGames.select().where(PickupGames.id == gid).first()
                if len(game.addedplayers) == 0:
                    game.delete_instance()
                    has_new_text = True
            elif pugdiff >= warntime:
                if mindiff > deletetime - pugdiff:
                    mindiff = deletetime - pugdiff  
                if not pugentry.isWarned:
                    pugentry.isWarned = True
                    pugentry.save()
                    if pugentry.addedFrom == "irc":
                        warn_user = {"user": pugentry.playerId.ircName, "chattype": "irc"}
                    else:
                        warn_user = {"user": pugentry.playerId.discordMention, "chattype": "discord"}
            else:
                if mindiff > warntime - pugdiff:
                    mindiff = warntime - pugdiff
                # else:
                #     has_break = True
        db.close()
        return mindiff, has_break, has_new_text, warn_user
    
    def register_player(self, user, xonstatId, chattype) -> tuple[str, str, str]:
        db_logger.info("register_player: user=%s, xonstatId=%s, chattype=%s", user, xonstatId, chattype)
        error_result: str = ""
        irc_name: str = ""
        discord_name: str = ""

        db.connect()
        if xonstatId and xonstatId.isdigit():
            try:
                xonstatscoloredname, xonstatsname = get_statsnames(xonstatId)
                pl = None
                if xonstatsname is None:
                    error_result = "No Player with this ID"
                else:
                    if chattype == "irc":
                        irc_player: Players = Players.select().where(Players.ircName == user).first()
                        pl: Players = Players.select().where(Players.statsId == xonstatId).first()
                        if pl is None and irc_player is None:
                            pl = Players(ircName = user, 
                                        statsId = xonstatId, 
                                        statsName = xonstatsname, 
                                        statsIRCName = irc_colors(xonstatscoloredname), 
                                        statsDiscordName = discord_colors(xonstatscoloredname))
                            pl.save()
                            irc_name = pl.statsIRCName
                            discord_name = pl.statsDiscordName
                        else:
                            if irc_player == pl:
                                error_result = "Already registered with Xonstat account #" + xonstatId
                            if irc_player and pl is None:
                                irc_player.statsName = xonstatsname
                                irc_player.statsId = xonstatId
                                irc_player.statsIRCName = irc_colors(xonstatscoloredname)
                                irc_player.statsDiscordName = discord_colors(xonstatscoloredname)
                                irc_player.save()
                                irc_name = irc_player.statsIRCName
                                discord_name = irc_player.statsDiscordName
                            else:
                                if pl.ircName:
                                    error_result = "Another player is registered with Xonstat account #" + xonstatId
                                else:
                                    irc_player.ircName = None
                                    irc_player.save()
                                    pl.ircName = user
                                    pl.save()
                                    irc_name = pl.statsIRCName
                                    discord_name = pl.statsDiscordName
                    else:
                        discord_player: Players = Players.select().where(Players.discordName == user.name).first()
                        pl: Players = Players.select().where(Players.statsId == xonstatId).first()
                        if pl is None and discord_player is None:
                            pl = Players(discordName = user.name, 
                                        discordMention = user.mention, 
                                        statsId = xonstatId, 
                                        statsName = xonstatsname, 
                                        statsIRCName = irc_colors(xonstatscoloredname), 
                                        statsDiscordName = discord_colors(xonstatscoloredname))
                            pl.save()
                            irc_name = pl.statsIRCName
                            discord_name = pl.statsDiscordName                            
                        else:
                            if discord_player == pl:
                                error_result = "Already registered with Xonstat account #" + xonstatId
                            if discord_player and pl is None:
                                discord_player.statsId = xonstatId
                                discord_player.statsName = xonstatsname
                                discord_player.statsIRCName = irc_colors(xonstatscoloredname)
                                discord_player.statsDiscordName = discord_colors(xonstatscoloredname)
                                discord_player.save()
                                irc_name = discord_player.statsIRCName
                                discord_name = discord_player.statsDiscordName
                            else:
                                if pl.discordName:
                                    error_result = "Another player is registered with Xonstat account #" + xonstatId
                                else:
                                    discord_player.discordName = None
                                    discord_player.discordMention = None
                                    discord_player.save()
                                    pl.discordName = user.name
                                    pl.discordMention = user.mention
                                    pl.save()
                                    irc_name = pl.statsIRCName
                                    discord_name = pl.statsDiscordName
            except Exception as e:
                db_logger.error("Error in command_register: ", e, "Reason: ", e.args)
                error_result = "Problem with XonStats"
        else:
            error_result = "No ID given!"
        db.close()
        return error_result, discord_name, irc_name
    
    def renew_pickupentry(self, user, gametypes, chattype) -> str:
        db_logger.info("renew_pickupentry: user=%s, gametypes=%s, chattype=%s", user, gametypes, chattype)
        gameentries = None
        player = None
        error_result: str = ""

        db.connect()
        #check where user renewed from
        player = self.__get_player(user, chattype)

        #check if player is already in database
        if player is not None:
            gameentries = PickupEntries.select().join(PickupGames).where(PickupGames.isPlayed == False).where(PickupEntries.playerId == player)
        
        #send message if theres is no active pickup game
        if player is None or not gameentries.exists():
            error_result = "No game added!"

        #!renew without gametype, renew all pickups of player
        if not gametypes:
            for gameentry in gameentries:
                gameentry.isWarned = False
                gameentry.addedDate = datetime.now()
                gameentry.save()

        #just renews gametypes that are given
        #example: !renew duel
        else:
            for gtypeentries in gametypes:
                gtype = GameTypes.select().where(GameTypes.title == gtypeentries).first()
                if gtype is not None: 
                    gameentry = gameentries.select().where(PickupEntries.gameId == gtype.id).first()
                    gameentry.isWarned = False
                    gameentry.addedDate = datetime.now()
                    gameentry.save()

        db.close()
        return error_result
    
    def set_irc_nickname(self, oldnick:str, newnick:str):
        db_logger.info("set_irc_nickname: oldnick=%s, newnick=%s", oldnick, newnick)
        db.connect()
        pl = Players.select().where(Players.ircName == oldnick).first()
        if pl is not None:
            pl.ircName = newnick
            pl.save()
        db.close()

    def start_pickupgame(self, gametypetitle:str) -> str:
        db_logger.info("start_pickupgame: gametypetitle=%s", gametypetitle)
        result: bool = False
        error_message: str = ""
        found_match = {}

        db.connect()
        active_games: PickupGames = self.__get_active_games()
        if active_games.exists():
            starting_game = active_games.join(GameTypes).where(GameTypes.title == gametypetitle).first()
            if starting_game:
                result = True
                found_match = self.__get_found_matchtext(starting_game, True)
            else:
                error_message = "No active pickup game found for gametype: " + gametypetitle
        else:
            error_message = "No active pickup game found!"

        db.close()
        return result, error_message, found_match

    
    def withdraw_player_from_pickup(self, user, gametypes:list[str] = None, chattype = None) -> bool:
        db_logger.info("remove_player_from_pickup: user=%s, gametypes=%s, chattype=%s", user, gametypes, chattype)
        player = None
        result: bool = False

        db.connect()

        #check where user removed from
        player = self.__get_player(user, chattype)
                
        #!remove without gametype, remove all entries and if only player removes pickup game completely
        if not gametypes:
            result = self.__withdraw_player_from_all(player)
        
        #just removes gametypes that are given and if last player removes pickup game completely
        #example: !remove duel
        else:
            for gametype in gametypes:
                result = self.__withdraw_player_from_gametype(player, gametype)

        db.close()
        if result:
            self.delete_games_without_player()
        return result
    
    def toggle_player_bridge(self, user, chattype) -> tuple[str, str]:
        #toggles if a player should be bridged to discord/irc        
        db_logger.info("toggle_player_bridge: user=%s, chattype=%s", user, chattype)
        irc_name: str = ""
        discord_name: str = ""

        db.connect
        player: Players = self.__get_player(user, chattype)
        if player:
            irc_name = player.ircName
            discord_name = player.discordName
            player.shouldBridge = not player.shouldBridge
            player.save()
        db.close()
        return irc_name, discord_name
            