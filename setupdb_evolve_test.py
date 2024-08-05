from model_test import *

import argparse
import peeweedbevolve

def createDatabase():
    db.connect()
    db.create_tables([Servers])
    db.close()

def createServers():    
    db.connect()
    try:
        for i in range(1, 11):
            Servers.get_or_create(serverName="Server"+str(i), serverIP="192.168.0."+str(i))
    except:
        print("No table for servers found! Please execute 'createdb' first.")
    db.close()

def deleteServers():
    db.connect()
    Servers.delete().execute()
    db.close()

def main():
    parser = argparse.ArgumentParser(description="Commands for the pickup-database:")
    parser.add_argument('--createdb', help='Create database-file for the pickupbot', action='store_true')
    parser.add_argument('--createservers', help='Create common servers for the pickupbot', action='store_true')
    parser.add_argument('--deleteservers', help='Delete servers from the database', action='store_true')
    args = parser.parse_args()
    if args.createdb:
        createDatabase()
    elif args.createservers:
        createServers()
    elif args.deleteservers:
        deleteServers()

if __name__ == '__main__':
    main()