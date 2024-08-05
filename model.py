import datetime
from peewee import *

db = SqliteDatabase('pickups.db', pragmas={'foreign_keys': 1})
#db = SqliteQueueDatabase('pickups.db', pragmas={'foreign_keys': 1}, autostart=False, queue_max_size=64, results_timeout=5.0, autoconnect=False)

class Servers(Model):
    serverName = CharField(unique=True)
    serverIP = CharField(unique=True, null=True)

    class Meta:
        database = db

