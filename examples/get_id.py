"""Simple example showing user searching.
Author: NeKitDS
"""
import asyncio
import gd

client = gd.Client()

async def main():
    # get some input from user
    name = input('Enter your GD nickname: ')

    # look up and print IDs if found
    try:
        user = await client.find_user(name)

        if isinstance(user, gd.UnregisteredUser):
            print(f'Hey there, {user.name}! Seems like you are unregistered...')

        else:
            print(f'Hello, {user.name}! Your AccountID is {user.account_id} and PlayerID is {user.id}.')

    # could not find
    except gd.MissingAccess:
        print(f'Sorry, could not find user with name {name}...')

    # let us wait a bit before exiting
    await asyncio.sleep(3)

# run a program
client.run(main())
