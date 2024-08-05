from peewee import *

db = SqliteDatabase('test.db', pragmas={'foreign_keys': 1})

class Servers(Model):
    serverName = CharField(unique=True)
    serverIP = CharField(unique=True, null=True)

    class Meta:
        database = db

