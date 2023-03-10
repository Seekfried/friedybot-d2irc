# friedybot-d2irc
A pickupbot for managing Xonotic pickup games

### Features:
- Managing pickup games over IRC and Discord (**maybe Matrix in the Future**)
- sync messages between IRC and Discord, with command for users to disable bridge function (**privacy reasons**)
- saving Players/Games/Gametypes/Servers in sqlite (**through peewee mysql, postgresql and cockroachdb possible too**)
- command for cup bracket generation (**needs chromium-based browser installed**)

## Installation and usage

**Note**: friedybot-d2irc requires Python >= 3.8, as it depends on [discord.py](https://github.com/Rapptz/discord.py)

Download the code from this repository and configure setting.json (see [Configuration](https://github.com/Seekfried/friedybot-d2irc#configuration))

Install python dependencies
```python
pip install -r requirements.txt
```

Create database (**pickups.db**)
```python
python setupdb.py --createdb
```

*Optional*: import gametypes from gametypes.json
```python
python setupdb.py --creategametypes
```

Other options for setupdb.py:
```python
python setupdb.py --deletegametypes #Delete gametypes from database
python setupdb.py --deletepickups   #Delete past pickupgames from database
```

And run the bot:
```python
python startbot.py
```

## Configuration

First you need to create a Discord bot user, which you can do by following the instructions [here](https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token).

The token is needed for the settings.json.

To get the **server and channel ID** of your discord, just go to your discord server and write down the IDs found in the URL. **(Example below)**

![server-channel](https://i.imgur.com/MUbxESc.png)

### Settings.json
```js
{
    "irc": {
        "server": "",       //IRC-Server address
        "port": "",         //IRC-Server port
        "channel": "#",     //Your IRC-Channelname
        "nickname": "",     //IRC-Nickname for the bot
        "botowner": "",     //IRC-User that can close the bot with the !quit command
        "quitmsg": "Cya!"   //IRC quit message
    },
    "discord": {
        "token": "",        //Discord bot's token
        "botowner": "",     //Discord-User that can close the bot with the !quit command
        "server": "",       //Discord server ID
        "channel": "",      //Discord channel ID
        "modrole": "mods"   //Discord rolename to enable Admin/Moderator commands for users
    },
    "bot": {
        "pugtimewarning": 2400, //time in seconds, to warn player that pickup is going to expire
        "pugtimeout": 3600      //time in seconds, that pickup is expired   
    }
}
```



There are three other different setting files:
- **cmdresult.json**: command output texts and help texts
- **gametypes.json**: a collection of predefined game types 
- **xonotic.json**: xonotic flavoured messages for the !kill command

## Commands

### Player commands
- **!register**: Connect your account with your XonStats (stats.xonotic.org): !register \<xonstats-id>
- **!add**: Add to all current pickup games or specific games: !add \[gametype]
- **!renew**: Renew pickup games
- **!remove**: Remove from all pickup games or specific games: !remove \[\<gametype>]
- **!server**: Show all available Xonotic servers or specific server and their IP: !server \<servername>
- **!who**: List all current pickup games with players
- **!kill**: Command for marking users with xonotic flavour (*see xonotic.json for more*)
- **!bridge**: Switch bridge functionality on or off (for yourself)

### Admin/Moderator commands
*For discord-users with the role specific to settings.json (modrole) or IRC-users with OP*
- **!pull**: remove specific player from pickup games: !pull \[\<players>]
- **!addgametype**: To add gametype: !addgametype \<gametypename> \<playercount> \<teamcount> \<statsname>
- **!addserver**: To add server: !addserver \<servername> \<ip:port>
- **!removegametype**: To delete gametype: !removegametype \[\<gametypename>]
- **!removeserver**: To delete server: !removeserver \[\<servername>],

### Cup Generation
- at the moment just direct cup generation with **!cupstart** (future feature -> with player signing in themselves)
- **!cupstart**: To generate cup brackets: !cupstart \<cuptitle> \[\<players/teams>]

**example: !cupstart seeky-cup grunt hotdog ramses packer mirio**

![cup-generator](https://i.imgur.com/XqH5OXm.png)