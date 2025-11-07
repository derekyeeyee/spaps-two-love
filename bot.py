import discord
from discord.ext import commands
from dotenv import load_dotenv

import os
import logging

LAVALINK_PASSWORD = "youshallnotpass"

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

handler = logging.FileHandler(
    filename='discord.log', encoding='utf-8', mode='w')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print("bot is ready")


@bot.command()
async def twolove(ctx):
    await ctx.send(f"2 LØVE 2 LØVE")


bot.run(token, log_handler=handler, log_level=logging.DEBUG)
