from peewee import *

db = SqliteDatabase('test.db', pragmas={'foreign_keys': 1})

class Servers(Model):
    serverName = CharField(unique=True)
    serverIPv4 = CharField(unique=True, null=True, aka='serverIP')
    serverIPv6 = CharField(unique=True, null=True)

    class Meta:
        database = db

