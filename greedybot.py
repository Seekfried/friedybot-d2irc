from chattype import ChatType
import threading
import random
from datetime import datetime
import time
from ircconnection import IrcConnector
from discordconnection import DiscordConnector, client
from dbconnection import DatabaseConnector
from matrixconnection import MatrixConnector
from xonotic.utils import get_quote
from utils import create_logger, sanitize_ip_and_port, is_ipv4_address, is_ipv6_address
import asyncio

logger = create_logger(__name__)

class Greedybot:
    def __init__(self, settings, cmdresults, xonotic):
        self.pickupText = "Pickups: "
        self.picktimer = None
        self.settings = settings
        self.cmdresults = cmdresults
        self.xonotic = xonotic
        self.ircconnect = None
        self.discordconnect = None
        self.topic = ""
        self.dbconnect = DatabaseConnector(self.settings["database"]["filename"])        
        self.muted_discord_users = []
        self.muted_irc_users = []
        self.muted_matrix_users = []
        self.muted_discord_users, self.muted_irc_users, self.muted_matrix_users = self.dbconnect.get_unbridged_players()

    async def run(self):
        self.irc_enabled: bool = ChatType.IRC.value in self.settings
        self.discord_enabled: bool = ChatType.DISCORD.value in self.settings
        self.matrix_enabled: bool = ChatType.MATRIX.value in self.settings
        
        if self.irc_enabled:
            self.ircconnect = IrcConnector(self.settings[ChatType.IRC.value], self)
            t1 = threading.Thread(target=self.ircconnect.run)
            t1.daemon = True                                    # Thread dies when main thread (only non-daemon thread) exits.
            t1.start()
        
        if self.discord_enabled:
            self.discordconnect = DiscordConnector(self.settings[ChatType.DISCORD.value], self)
            self.discord_task = asyncio.create_task(client.start(self.settings[ChatType.DISCORD.value]["token"]))
            
        if self.matrix_enabled:
            self.matrixconnect = MatrixConnector(self.settings[ChatType.MATRIX.value], self)
            self.matrix_task = asyncio.create_task(self.matrixconnect.start())

        if self.discord_enabled and self.matrix_enabled:
            await asyncio.gather(self.discord_task, self.matrix_task)
            # await self.discord_task
            # await self.matrix_task
        elif self.discord_enabled:
            await self.discord_task
        elif self.matrix_enabled:
            await self.matrix_task

    def close(self):
        if self.discord_enabled:
            self.discord_task.cancel()
        if self.matrix_enabled:
            self.matrix_task.cancel()
        if self.irc_enabled:
            self.ircconnect.close()
    
    def start_pugtimer(self):
        #background timer to warn players of expiring pickup games or deletes old pickup games
        warntime = self.settings["bot"]["pugtimewarning"]
        deletetime = self.settings["bot"]["pugtimeout"]
        while True:
            mindiff = warntime
            currenttime = datetime.now()      
            if self.dbconnect.has_active_games(): #pugentries.exists():

                mindiff, has_break, has_new_text, warn_user = self.dbconnect.pugtimer_step(mindiff, currenttime, deletetime, warntime)
                
                #player was over the time and got remove from game
                if has_new_text:
                    self.build_pickuptext()

                #player gets notified: "Your added games will expire in 20 minutes, type !renew to renew your games"
                if warn_user:
                    if warn_user["chattype"] == ChatType.IRC.value:
                        self.send_notice(warn_user["user"], warn_user["user"] + " " + self.cmdresults["misc"]["pugtimewarn"], warn_user["chattype"])
                    elif warn_user["chattype"] == ChatType.DISCORD.value:
                        self.send_notice(None, warn_user["user"] + " " + self.cmdresults["misc"]["pugtimewarn"], warn_user["chattype"])
                    elif warn_user["chattype"] == ChatType.MATRIX.value:
                        self.send_notice(None, warn_user["user"] + " " + self.cmdresults["misc"]["pugtimewarn"], warn_user["chattype"])
                        pass
                    else:
                        logger.error("Unknown chattype: ", warn_user["chattype"])
                if has_break:
                    break
                if not self.dbconnect.has_active_games():
                    return
                else:
                    time.sleep(mindiff)
            else:
                return

    def set_irc_topic(self):
        #sets the current pickups as irc topic
        logger.info("set_irc_topic")
        try:
            if  self.pickupText != "Pickups: ":
                self.ircconnect.connection.topic(self.settings[ChatType.IRC.value]["channel"], new_topic=self.pickupText)
            else:
                self.ircconnect.connection.topic(self.settings[ChatType.IRC.value]["channel"], new_topic=self.topic)
        except Exception as e:
            logger.error("Something wrong with topic: ", e)
    
    def send_command(self, user, argument, chattype, isadmin):
        #forwards commands from irc/discord to bot specific command
        logger.info("send_command: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        argument = argument.split()
        method_name = 'command_' + str(argument[0][1:].lower())
        method = getattr(self, method_name, self.wrong_command)
        try:
            method(user, argument, chattype, isadmin)
        except Exception as e:
            self.send_notice(user, "Sorry, something went wrong", chattype)
            logger.error("Error in command:", e)

    def send_notice(self, user, message, chattype):
        #sends message to only discord or to specific irc-user (for future: send direct message to discord-user)
        logger.info("send_notice: user=%s, message=%s, chattype=%s", user, message, chattype)
        if chattype == ChatType.IRC.value and self.irc_enabled:
            self.ircconnect.send_single_message(user,message)
        elif chattype == ChatType.DISCORD.value and self.discord_enabled:
            self.discordconnect.send_my_message(message)
        elif chattype == ChatType.MATRIX.value and self.matrix_enabled:
            self.matrixconnect.send_my_message(message, True)
        else:
            logger.error("Unknown chattype: ", chattype)

    def send_all(self, message:str, ircmessage:str = None, matrixmessage:str = None, chattype:str = None, messagehead:str = None, discordmention:bool = False, matrix_html: bool = False):
        logger.info("send_all: message=%s, ircmessage=%s, matrixmessage=%s, chattype=%s, messagehead=%s, discordmention=%s", 
                    message, ircmessage, matrixmessage, chattype, messagehead, discordmention)
        
        if messagehead:
            if self.irc_enabled and chattype != ChatType.IRC.value:
                if ircmessage is not None:
                    self.ircconnect.send_my_message(ircmessage, messagehead)
                else:
                    self.ircconnect.send_my_message(message, messagehead)
                    
            if self.matrix_enabled and chattype != ChatType.MATRIX.value:
                if matrixmessage is not None:
                    self.matrixconnect.send_my_message(messagehead + matrixmessage, matrix_html)
                else:
                    self.matrixconnect.send_my_message(messagehead + message, matrix_html)
            
            if self.discord_enabled and chattype != ChatType.DISCORD.value:
                if discordmention:
                    self.discordconnect.send_my_message_with_mention(messagehead + message)
                else:
                    self.discordconnect.send_my_message(messagehead + message)
        else:
            if self.irc_enabled and chattype != ChatType.IRC.value:
                if ircmessage is not None:
                    self.ircconnect.send_my_message(ircmessage)
                else:
                    self.ircconnect.send_my_message(message)
                    
            if self.matrix_enabled and chattype != ChatType.MATRIX.value:
                if matrixmessage is not None:
                    self.matrixconnect.send_my_message(matrixmessage, matrix_html)
                else:
                    self.matrixconnect.send_my_message(message, matrix_html)
            
            if self.discord_enabled and chattype != ChatType.DISCORD.value:
                if discordmention:
                    self.discordconnect.send_my_message_with_mention(message)
                else:
                    self.discordconnect.send_my_message(message)

    def wrong_command(self, user, argument, chattype, isadmin):
        #if user inputs wrong command
        logger.info("wrong_command: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        self.send_notice(user, self.cmdresults["misc"]["wrongcommand"], chattype)

    def change_name(self, oldnick, newnick):
        #changes irc-name of users in case of nickname changes
        logger.info("change_name: oldnick=%s, newnick=%s", oldnick, newnick)
        self.muted_irc_users = [newnick if x==oldnick else x for x in self.muted_irc_users]
        self.dbconnect.set_irc_nickname(oldnick, newnick)

    def remove_user_on_exit(self, user,chattype):
        #removes user from all pickups in case of disconnect
        logger.info("remove_user_on_exit: user=%s, chattype=%s", user, chattype)
        gameentries = None
        player = None
        
        try:                        
            result = self.dbconnect.withdraw_player_from_pickup(user, chattype=chattype)
            if result:
                self.build_pickuptext()
        except Exception as e:
            logger.error("Error in remove_user_on_exit: ", e)

    def build_pickuptext(self):
        #sends current pickup games to all channels
        #result: "Pickups: duel (1/2) 2v2tdm (1/4)"        
        logger.info("build_pickuptext")   
        games_exists = self.dbconnect.has_active_games()
        pickuptext_new = self.dbconnect.get_pickuptext()
        if not games_exists and self.pickupText == "Pickups: ":
            self.set_irc_topic()
            return

        if not games_exists and self.pickupText != "Pickups: ":            
            self.pickupText = "Pickups: " 
            self.send_all(self.pickupText)
            self.set_irc_topic()  
        else:
            self.pickupText = "Pickups: "
            self.pickupText += pickuptext_new
            self.send_all(self.pickupText)
            self.set_irc_topic()
        return self.pickupText
    """
    Commands for IRC, Discord, and Matrix
        Naming Convention for bot methods is command_yourcommand
        example:
            def command_hug(self, user, argument, chattype, isadmin):
                user: irc-username or discord author-object
                argument: array of user typed command for example: !add duel 2v2tdm -> [!add, duel, 2v2tdm]
                chattype: incoming message type (ChatType.IRC.value/ChatType.DISCORD.value/ChatType.MATRIX.value)
                isAdmin: is user in discord-moderator-role (see settings.json) or is irc-operator
    """

    def command_register(self, user, argument, chattype, isadmin):
        #command to connect player in database with their XonStats-account
        logger.info("command_register: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        xonstatsId: str = argument[1]
        error_message: str = ""
        discord_name: str = ""
        irc_name: str = ""
        error_message, discord_name, irc_name, matrix_name = self.dbconnect.register_player(user, xonstatsId, chattype)

        if error_message == "":
            if chattype == ChatType.IRC.value:
                self.send_all(self.cmdresults["misc"]["registsuccess"].format(user, xonstatsId, discord_name), 
                              self.cmdresults["misc"]["registsuccess"].format(user, xonstatsId, irc_name),
                              self.cmdresults["misc"]["registsuccess"].format(user, xonstatsId, matrix_name),
                              matrix_html=True)
            elif chattype == ChatType.DISCORD.value:
                self.send_all(self.cmdresults["misc"]["registsuccess"].format(user.name, xonstatsId, discord_name), 
                              self.cmdresults["misc"]["registsuccess"].format(user.name, xonstatsId, irc_name),
                              self.cmdresults["misc"]["registsuccess"].format(user.name, xonstatsId, matrix_name),
                              matrix_html=True)
            elif chattype == ChatType.MATRIX.value:
                self.send_all(self.cmdresults["misc"]["registsuccess"].format(user, xonstatsId, discord_name), 
                              self.cmdresults["misc"]["registsuccess"].format(user, xonstatsId, irc_name),
                              self.cmdresults["misc"]["registsuccess"].format(user, xonstatsId, matrix_name),
                              matrix_html=True)
                pass
            else:
                logger.error("Unknown chattype: ", chattype)
        else: 
            self.send_notice(user, error_message, chattype)

    def command_add(self, user, argument, chattype, isadmin):
        # command to add player to pickup games
        logger.info("command_add: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        result: bool = False
        error_messages: list[str] = []
        found_match: dict = {}
        gametypes: list[str] = argument[1:]

        result, error_messages, found_match = self.dbconnect.add_player_to_games(user, gametypes, chattype)
        if result:
            # match found ready to notify player 
            if found_match:
                # match with teams and captains
                if found_match["has_teams"]:
                    self.send_all("\n".join(found_match[ChatType.DISCORD.value]), "\n".join(found_match[ChatType.IRC.value]), "\n".join(found_match[ChatType.MATRIX.value]), matrix_html=True)
                else:
                    self.send_all(found_match[ChatType.DISCORD.value], found_match[ChatType.IRC.value], found_match[ChatType.MATRIX.value], matrix_html=True)

            #start the background timer to delete old pickup games
            if self.picktimer is None or not self.picktimer.is_alive():
                self.picktimer = threading.Thread(target=self.start_pugtimer, daemon=True)
                self.picktimer.start()
            self.build_pickuptext()
        
        for error_message in error_messages:
            self.send_notice(user, error_message, chattype)

    def command_pickups(self, user, argument, chattype, isadmin):
        # command to know all available game types
        logger.info("command_pickups: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        result: str = "Possible gametypes: "
        result += ", ".join(self.dbconnect.get_gametype_list())
        self.send_notice(user, result, chattype)

    def command_remove(self, user, argument, chattype, isadmin):
        # command to remove player from pickup games
        logger.info("command_remove: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        #TODO errormessages for wrong gametype
        gametypes = argument[1:]
        
        result = self.dbconnect.withdraw_player_from_pickup(user, gametypes, chattype)
        
        if result:            
            self.build_pickuptext() 
        else:
            self.send_notice(user, "No game added!", chattype)

    def command_push(self, user, argument, chattype, isadmin):
        # adds pickup player to games (just discord-moderators or irc-operators)
        logger.info("command_push: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        if isadmin:
            result: bool = False
            error_messages: list[str] = []
            found_match: dict = {}

            player: str = argument[1]
            gametypes: list[str] = argument[2:]

            result, error_messages, found_match = self.dbconnect.add_player_to_games(user, gametypes, chattype, player)
            if result:
                # match found ready to notify player 
                if found_match:
                    # match with teams and captains
                    if found_match["has_teams"]:
                        self.send_all("\n".join(found_match[ChatType.DISCORD.value]), "\n".join(found_match[ChatType.IRC.value]), "\n".join(found_match[ChatType.MATRIX.value]), matrix_html=True)
                    else:
                        self.send_all(found_match[ChatType.DISCORD.value], found_match[ChatType.IRC.value], found_match[ChatType.MATRIX.value], matrix_html=True)

                #start the background timer to delete old pickup games
                if self.picktimer is None or not self.picktimer.is_alive():
                    self.picktimer = threading.Thread(target=self.start_pugtimer, daemon=True)
                    self.picktimer.start()
                self.build_pickuptext()
            
            for error_message in error_messages:
                self.send_notice(user, error_message, chattype)
        else:
            self.send_notice(user, self.cmdresults["misc"]["restricted"], chattype)

    def command_pull(self, user, argument, chattype, isadmin):
        # removes pickup player from games (just discord-moderators or irc-operators)
        logger.info("command_pull: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        if isadmin:
            if len(argument) > 1:
                result: bool = False
                not_existing_players = []
                for arg in argument[1:]:
                    result = self.dbconnect.withdraw_player_from_pickup(arg)
                    if not result:
                        not_existing_players.append(arg)
                
                if len(not_existing_players) > 0:
                    self.send_notice(user, "The following player(s) was/were not added! →" + ", ".join(not_existing_players), chattype)
                
                if len(not_existing_players) != len(argument[1:]):
                    self.build_pickuptext()
        else:
            self.send_notice(user, self.cmdresults["misc"]["restricted"], chattype)
        
    def command_renew(self, user, argument, chattype, isadmin):
        logger.info("command_renew: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        gametypes: list[str] = argument[1:]
        error_message: str = ""

        error_message = self.dbconnect.renew_pickupentry(user, gametypes, chattype)

        if error_message:
            self.send_notice(user, error_message, chattype)
        

    def command_who(self, user, argument, chattype, isadmin):
        # command that shows list of pickup games and their players
        logger.info("command_who: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        result = self.dbconnect.get_active_games_and_players()
        resultText:str = ""

        if not result:            
            self.send_notice(user, "No game added!", chattype)
        else:            
            for gametype in result.keys():
                resultText += gametype + result[gametype]["playercount"] +": "
                players = result[gametype][ChatType.IRC.value] + result[gametype][ChatType.DISCORD.value]
                resultText += ", ".join(players) + " "
            self.send_notice(user, resultText, chattype)

    def command_server(self, user, argument, chattype, isadmin):
        # !server without arguments shows all available servers
        logger.info("command_server: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        if len(argument) == 1:
            wrongs_server, resultText = self.dbconnect.get_server()
            self.send_all(resultText)

        #shows specific servers from arguments
        #example: !server dogcity
        else:
            wrongs_server, resultText = self.dbconnect.get_server(argument[1])
            if wrongs_server:
                self.send_notice(user, resultText, chattype)
            else:
                self.send_all(resultText)

    def command_addserver(self, user, argument, chattype, isadmin):
        #command to add servers with their ip:port to database
        logger.info("command_addserver: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        message: str = ""
        server_name: str = argument[1] if len(argument) > 1 else None
        server_address: str = argument[2] if len(argument) > 2 else None
        server_address2: str = argument[3] if len(argument) > 3 else None
        
        if isadmin:
            if server_address:            
                try:
                    sanitized_ip_and_port1: str = sanitize_ip_and_port(server_address)
                    sanitized_ip_and_port2: str = None
                    if server_address2:
                        sanitized_ip_and_port2: str = sanitize_ip_and_port(server_address2)
                        if not ((is_ipv4_address(sanitized_ip_and_port1) and is_ipv6_address(sanitized_ip_and_port2)) or
                                (is_ipv6_address(sanitized_ip_and_port1) and is_ipv4_address(sanitized_ip_and_port2))):
                            self.send_notice(user, "Not a valid IP-addresses! When providing 2 IPs, one must be IPv4 and the other IPv6", chattype)
                            raise ValueError("Not a valid IP-addresses! When providing 2 IPs, one must be IPv4 and the other IPv6")
                    if is_ipv4_address(sanitized_ip_and_port1):
                        message = self.dbconnect.add_server(server_name, sanitized_ip_and_port1, sanitized_ip_and_port2)
                    else:
                        message = self.dbconnect.add_server(server_name, sanitized_ip_and_port2, sanitized_ip_and_port1)
                    self.send_notice(user, message, chattype)
                except ValueError:
                    self.send_notice(user, "Not a valid IP-address or port! To add server: !addserver <servername> <ip:port> [ <ip:port> ]", chattype)
            else:
                self.send_notice(user, self.cmdresults["cmds"]["addserver"], chattype)
        else:
            self.send_notice(user, self.cmdresults["misc"]["restricted"],chattype)
    
    def command_addgametype(self, user, argument, chattype, isadmin):
        #command to add gametype to database (duel, 2v2tdm)
        #Usage: !addgametype <gametypetitle> <playercount> <teamcount> <statsname>
        #example: !addgametype 2v2v2ca 6 3 ca
        logger.info("command_addgametype: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        message: str = ""
        gt_title: str = argument[1] if len(argument) > 1 else None
        gt_playercount: str = argument[2] if len(argument) > 2 and argument[2].isdigit() else None
        gt_teamcount: str = argument[3] if len(argument) > 3 and argument[3].isdigit() else gt_playercount
        gt_xonstatname: str = argument[4] if len(argument) > 4 else None

        if isadmin:
            if gt_playercount:
                message = self.dbconnect.add_gametypes(gt_title, gt_playercount, gt_teamcount, gt_xonstatname)
            else:
                message = self.cmdresults["cmds"]["addgametype"]                
            self.send_notice(user, message, chattype) 
        else:
            self.send_notice(user, self.cmdresults["misc"]["restricted"], chattype)

    def command_removeserver(self, user, argument, chattype, isadmin):
        #command to remove server from database
        logger.info("command_removeserver: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        messages = []
        serverlist = argument[1:]

        if isadmin:
            messages = self.dbconnect.delete_server(serverlist)
            for message in messages:
                self.send_notice(user, message, chattype)            
        else:
            self.send_notice(user, self.cmdresults["misc"]["restricted"], chattype)
    
    def command_removegametype(self, user, argument, chattype, isadmin):
        #command to remove gametype from database
        logger.info("command_removegametype: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        messages = []
        gametypes = argument[1:]

        if isadmin:
            messages = self.dbconnect.delete_gametypes(gametypes)
            for message in messages:
                self.send_notice(user, message, chattype)
        else:
            self.send_notice(user, self.cmdresults["misc"]["restricted"], chattype)
    
    def command_help(self, user, argument, chattype, isadmin):
        #command for general overview of commands
        #or with arguments help for specific command
        logger.info("command_help: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        if isadmin:
            if len(argument) > 1 and self.cmdresults["cmds"][argument[1]] is not None:
                self.send_notice(user, self.cmdresults["cmds"][argument[1]], chattype)
            else:
                self.send_notice(user, self.cmdresults["misc"]["helpadmin"], chattype)
        else:
            if len(argument) > 1 and self.cmdresults["cmds"][argument[1]] is not None:
                self.send_notice(user, self.cmdresults["cmds"][argument[1]], chattype)
            else:
                self.send_notice(user, self.cmdresults["misc"]["help"], chattype)

    def command_kill(self, user, argument, chattype, isadmin):
        #command for marking users with xonotic flavour
        #example: !kill DrJaska
        #result: "DrJaska felt the electrifying air of Seek-y's Electro combo"
        logger.info("command_kill: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        killer:str = ""
        is_real_irc_user:bool = False
        is_real_discord_user:bool = False
        is_real_matrix_user:bool = False

        if chattype == ChatType.IRC.value:
            killer = user
        elif chattype == ChatType.DISCORD.value:
            killer = user.name
        elif chattype == ChatType.MATRIX.value:
            killer = user
        else:
            logger.error("Unknown chattype: ", chattype)

        if len(argument) > 1:    
            #get victim name        
            victim = argument[1]
            if self.irc_enabled:
                #fill user list with irc
                irc_users = list(self.ircconnect.get_online_users())
                #victim is real user
                is_real_irc_user = victim in irc_users
            if self.discord_enabled and not is_real_irc_user:
                #fill user list with discord
                discord_users = self.discordconnect.get_online_members()
                #victim is real user
                is_real_discord_user = victim in discord_users
            if self.matrix_enabled and not is_real_discord_user:
                #victim is real user
                is_real_matrix_user = self.matrixconnect.found_user_in_room(victim)                
            #random chance 
            is_random_chance = random.random() <= self.xonotic["chance"]
            #victim is real user
            is_real_user = is_real_irc_user or is_real_discord_user or is_real_matrix_user

            if is_random_chance or (victim == killer) or not is_real_user:
                self.send_all(random.choice(self.xonotic["suicides"]).format(killer))
            else:
                message:str = random.choice(self.xonotic["kills"]).format(killer, victim)
                if self.irc_enabled:
                    self.ircconnect.send_my_message(message)                
                if self.discord_enabled:       
                    if is_real_discord_user:
                        discord_message = message.replace(victim, "@" + victim)
                        self.discordconnect.send_my_message_with_mention(discord_message)
                    else:
                        self.discordconnect.send_my_message_with_mention(message)
                if self.matrix_enabled:
                    self.matrixconnect.send_my_message(message)
        else:
            self.send_all(random.choice(self.xonotic["suicides"]).format(killer))

    def command_bridge(self, user, argument, chattype, isadmin):
        #toggle on/off if specific user-messages should be bridged (future)
        logger.info("command_bridge: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        irc_name: str = ""
        discord_name: str = ""
        matrix_name: str = ""
        irc_name, discord_name, matrix_name = self.dbconnect.toggle_player_bridge(user, chattype)

        if chattype == ChatType.IRC.value:
            if user in self.muted_irc_users:
                self.muted_irc_users.remove(user)
                self.muted_discord_users.remove(discord_name)
                self.muted_matrix_users.remove(matrix_name)
                self.send_notice(user, "Your messages are now bridged to discord and matrix.", chattype)
            else:
                self.muted_irc_users.append(user)
                self.muted_discord_users.append(discord_name)
                self.muted_matrix_users.append(matrix_name)
                self.send_notice(user, "Your messages are now not bridged to discord and matrix.", chattype)
        elif chattype == ChatType.DISCORD.value:
            if user.name in self.muted_discord_users:
                self.muted_discord_users.remove(user.name)
                self.muted_irc_users.remove(irc_name)
                self.muted_matrix_users.remove(matrix_name)
                self.send_notice(user, "Your messages are now bridged to irc and matrix", chattype)
            else:
                self.muted_discord_users.append(user.name)
                self.muted_irc_users.append(irc_name)
                self.muted_matrix_users.append(matrix_name)
                self.send_notice(user, "Your messages are now not bridged to irc and matrix", chattype)
        elif chattype == ChatType.MATRIX.value:
            if user in self.muted_matrix_users:
                self.muted_discord_users.remove(discord_name)
                self.muted_irc_users.remove(irc_name)
                self.muted_matrix_users.remove(user)
                self.send_notice(user, "Your messages are now bridged to irc and discord", chattype)
            else:
                self.muted_discord_users.append(discord_name)
                self.muted_irc_users.append(irc_name)
                self.muted_matrix_users.append(user)
                self.send_notice(user, "Your messages are now not bridged to irc and discord", chattype)
        else:
            logger.error("Unknown chattype: ", chattype)

    def command_online(self, user, argument, chattype, isadmin):
        #List all current online discord-members for irc-users and vice versa
        logger.info("command_online: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)

        if chattype == ChatType.IRC.value and self.discord_enabled:
            self.ircconnect.send_my_message("On Discord are online: " + ", ".join(self.discordconnect.get_online_members()))
        elif chattype == ChatType.DISCORD.value and self.irc_enabled:
            self.discordconnect.send_my_message("On IRC are online: " + ", ".join(self.ircconnect.get_online_users()))
        elif chattype == ChatType.MATRIX.value:
            if self.discord_enabled:
                self.matrixconnect.send_my_message("On Discord are online: " + ", ".join(self.discordconnect.get_online_members()))
            if self.irc_enabled:
                self.matrixconnect.send_my_message("On IRC are online: " + ", ".join(self.ircconnect.get_online_users()))
        else:
            logger.error("Unknown chattype: ", chattype)

    def command_lastgame(self, user, argument, chattype, isadmin):
        #Show the last played pickupgame with date and players
        logger.info("command_lastgame: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        result = self.dbconnect.get_lastgame(chattype)       
        self.send_notice(user, result, chattype)
        
    def command_subscribe(self, user, argument, chattype, isadmin):
        #Add to subscription to a specific gametype to get notified in !promote command
        #example: !subscribe 2v2tdm
        logger.info("command_subscribe: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        result: bool = False
        message: str = ""
        discord_name: str = ""
        gametype_args = set(argument[1:])
        new_subscriptions = []
        
        if gametype_args:
            for gametype_entry in gametype_args:
                result, message, discord_name = self.dbconnect.add_subscription(user, gametype_entry, chattype)

                if result:
                    new_subscriptions.append(gametype_entry)
                    if discord_name:
                        self.discordconnect.give_role(discord_name, gametype_entry)
                else:
                    self.send_notice(user, message, chattype)
            if not new_subscriptions:
                self.command_pickups(user, argument, chattype, isadmin)
            else:
                self.send_notice(user, "You are now subscribed to: " + ", ".join(new_subscriptions), chattype)
        else:
            subscriptions = self.dbconnect.get_subscriptions(user, chattype)
            if subscriptions:                
                self.send_notice(user, "You are subscribed to: " + ", ".join([x for x in subscriptions]), chattype)
            else:
                self.command_pickups(user, argument, chattype, isadmin)

    def command_unsubscribe(self, user, argument, chattype, isadmin):
        #Remove from all gametype subscriptions or specific gametype subscription        
        #example: !unsubscribe 2v2tdm
        logger.info("command_unsubscribe: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        gametype_args = set(argument[1:])
        message: str = ""
        discord_name: str = ""

        if gametype_args:
            for gametype_entry in gametype_args:
                message, discord_name = self.dbconnect.delete_subscription(user, gametype_entry, chattype)
                if message:
                    self.send_notice(user, message, chattype)
                else:
                    if discord_name:
                        self.discordconnect.take_role(discord_name, gametype_entry)
                
        else:            
            subscriptions = self.dbconnect.get_subscriptions(user, chattype)
            for gametype_entry in subscriptions:
                message, discord_name = self.dbconnect.delete_subscription(user, gametype_entry, chattype)
                if message:                    
                    self.send_notice(user, message, chattype)                    
                else:
                    if discord_name:
                        self.discordconnect.take_role(discord_name, gametype_entry)

        subscriptions = self.dbconnect.get_subscriptions(user, chattype)

        if subscriptions:
            self.send_notice(user, "You are subscribed to: " + ", ".join([x for x in subscriptions]), chattype)
        else:
            self.send_notice(user, "You are subscribed to nothing!", chattype)

    def command_promote(self, user, argument, chattype, isadmin):
        #Notify all players to gametype specific pickupgame
        #example: !promote 2v2tdm
        logger.info("command_promote: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        gametype_args = set(argument[1:])
        active_games_and_player: dict = self.dbconnect.get_active_games_and_players()
        notify_players: list[str] = []
        online_players: list[str] = self.ircconnect.get_online_users()

        for gametype in gametype_args:
            if gametype in active_games_and_player.keys():
                self.discordconnect.send_promote_message(gametype + " " + active_games_and_player[gametype]["playercount"] + " please add!", gametype)
                gametype_subs = self.dbconnect.get_subscribed_players(gametype)
                notify_players = [player for player in gametype_subs if player not in active_games_and_player[gametype][ChatType.IRC.value]]
                notify_players = [player for player in notify_players if player in online_players]
                for notify_player in notify_players:
                    self.send_notice(notify_player, notify_player + ": " + gametype + " " + active_games_and_player[gametype]["playercount"] + " please add!", ChatType.IRC.value)
            else:
                logger.warning("No active pickup found for: " + gametype)

    def command_info(self, user, argument, chattype, isadmin):
        #Show xonstat information about one player per playername or xonstats-id
        logger.info("command_info: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
                    
        if len(argument) > 1:
            player = argument[1]
            stats: dict = self.dbconnect.get_full_stats(player, chattype)
            if stats and stats["player"]:
                skills_stats: list[dict] = stats["skill_stats"]
                
                response: str = ("Player: " + stats["player"]["colored_name"] + " (" + str(stats["player"]["player_id"]) + "). " +
                                "Joined: " + stats["player"]["joined_fuzzy"] + ". Games played: " + str(stats["games_played"]["overall"]["games"]) +
                                ". Wins: " + str(round(stats["games_played"]["overall"]["win_pct"],2)) + "%. ")
                
                if len(skills_stats) > 0:
                    for skill in skills_stats:
                        response += " | " + skill["game_type_cd"] + " elo: " + str(round(skill["mu"],2))
                    
                else:
                    response += " | No games found"
                self.send_notice(user, response, chattype)
            else:
                self.send_notice(user, "No player found!", chattype)
        else:
            self.send_notice(user, "No player given!", chattype)

    def command_quote(self, user, argument, chattype, isadmin):
        #Get random quote from quoteDB or with playername from specific player
        logger.info("command_quote: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        quotelines: list[str] = []
        message: str = ""
        q_player: str = argument[1] if len(argument) > 1 else None
        quotelines = get_quote(q_player)
        for line in quotelines:
            message += "Quote: \"" + line + "\"\n"
        self.send_all(message=message)

    def command_serverinfo(self, user, argument, chattype, isadmin):
        #Get infos from server like name, map, player, gametype
        #TODO at the moment just for public ipv4 servers -> in future with RCON
        logger.info("command_serverinfo: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        server_infos = []
        resultText: str = ""
        server: str = argument[1] if len(argument) > 1 else None

        if len(argument) == 1:
            wrongs_server, resultText = self.dbconnect.get_server()
            self.send_all("Available servers: " + resultText)
        else:
            wrongs_server, server_infos = self.dbconnect.get_server_info(server)
            if wrongs_server:
                self.send_notice(user, server_infos, chattype)
            else:
                for line in server_infos:
                    self.send_all(line)

    def command_start(self, user, argument, chattype, isadmin):
        #Force the start of a pickup game that doesn't have all the players yet
        #example: !start 2v2tdm
        logger.info("command_start: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        gametype: str = argument[1] if len(argument) > 1 else None

        if gametype:
            result, error_message, found_match = self.dbconnect.start_pickupgame(gametype)
            if result:
                if found_match["has_teams"]:
                    self.send_all("\n".join(found_match[ChatType.DISCORD.value]), "\n".join(found_match[ChatType.IRC.value]), "\n".join(found_match[ChatType.MATRIX.value]), matrix_html=True)
                else:
                    self.send_all(found_match[ChatType.DISCORD.value], found_match[ChatType.IRC.value], found_match[ChatType.MATRIX.value], matrix_html=True)
                self.build_pickuptext()
            else:
                self.send_notice(user, error_message, chattype)
        else:
            self.send_notice(user, "You need to include a specific gametype!", chattype)

    def command_top10(self, user, argument, chattype, isadmin):
        #Show the top 10 players who have participated the most in the last 30 days in the given game types. 
        #If no game types are provided, it returns the overall: 
        #example: !top10 2v2tdm
        logger.info("command_top10: user=%s, argument=%s, chattype=%s, isadmin=%s", user, argument, chattype, isadmin)
        gametype_args = set(argument[1:])
        message: str = ""
        
        message = self.dbconnect.get_top_ten(gametype_args)
        self.send_notice(user, message, chattype)
