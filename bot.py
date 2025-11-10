import os
import logging
from dotenv import load_dotenv

import discord
from discord.ext import commands

import wavelink
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s:%(levelname)s:%(name)s: %(message)s",
    handlers=[
        logging.FileHandler(filename='discord.log',
                            encoding='utf-8', mode='w'),
        logging.StreamHandler()
    ]
)

# ---------- Config ----------
LAVALINK_URI = "http://localhost:2333"
LAVALINK_PASSWORD = "youshallnotpass"

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

handler = logging.FileHandler(
    filename="discord.log", encoding="utf-8", mode="w")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True  # needed to connect to voice

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- Lavalink Node Setup ----------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    # Connect to Lavalink only once
    if not wavelink.Pool.nodes:
        node = wavelink.Node(
            uri=LAVALINK_URI,
            password=LAVALINK_PASSWORD,
        )
        # Connect the pool
        await wavelink.Pool.connect(nodes=[node], client=bot)
        print("Connected to Lavalink node.")


# ---------- Helper: ensure we're in voice ----------
async def ensure_voice(ctx) -> wavelink.Player:
    """Get or create a Player connected to the author's voice channel."""
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        raise commands.CommandError("You must be in a voice channel.")

    # If already connected, reuse that player
    if isinstance(ctx.voice_client, wavelink.Player):
        return ctx.voice_client

    # Otherwise connect, creating a Wavelink Player
    channel = ctx.author.voice.channel
    player: wavelink.Player = await channel.connect(cls=wavelink.Player)
    # Optional: configure the player's internal queue
    player.queue = wavelink.Queue()  # wavelink provides a simple queue structure
    return player


# ---------- Music Cog ----------
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Events ---
    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """Auto-play next track when current finishes."""
        player: wavelink.Player = payload.player
        if player.queue and not player.playing:
            next_track = player.queue.get()
            await player.play(next_track)
            channel = self._text_channel_for_player(player)
            if channel:
                await channel.send(f"▶️ Now playing: **{next_track.title}**")

    def _text_channel_for_player(self, player: wavelink.Player) -> discord.TextChannel | None:
        """Best-effort: find a text channel in the same guild where we can speak."""
        guild = player.guild
        # Prefer the channel where the last command was used (if we stored it), else first text channel
        # For simplicity, pick the system channel or any text channel
        return guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

    # --- Commands ---
    @commands.command(name="join", help="Join your voice channel.")
    async def join(self, ctx: commands.Context):
        try:
            await ensure_voice(ctx)
            await ctx.send("🔊 Joined voice channel.")
        except commands.CommandError as e:
            await ctx.send(str(e))

    @commands.command(name="leave", aliases=["disconnect"], help="Leave the voice channel.")
    async def leave(self, ctx: commands.Context):
        if isinstance(ctx.voice_client, wavelink.Player):
            await ctx.voice_client.disconnect()
            await ctx.send("👋 Disconnected.")
        else:
            await ctx.send("I'm not connected to a voice channel.")

    @commands.command(name="play", help="Play a song by search or URL. Usage: !play <query>")
    async def play(self, ctx: commands.Context, *, query: str):
        try:
            player = await ensure_voice(ctx)
        except commands.CommandError as e:
            await ctx.send(str(e))
            return

        # If user pasted a URL, Lavalink will resolve it; otherwise search YouTube
        if not (query.startswith("http://") or query.startswith("https://")):
            query = f"ytsearch:{query}"

        tracks = await wavelink.Pool.fetch_tracks(query)
        if not tracks:
            await ctx.send("No results found.")
            return

        # If a playlist was provided, add them all; otherwise pick the first track
        if isinstance(tracks, wavelink.Playlist):
            for t in tracks.tracks:
                player.queue.put(t)
            await ctx.send(f"➕ Queued playlist: **{tracks.name}** ({len(tracks.tracks)} tracks)")
        else:
            track = tracks[0]
            # If nothing is playing, play immediately; else queue it
            if not player.playing:
                await player.play(track)
                await ctx.send(f"▶️ Now playing: **{track.title}**")
            else:
                player.queue.put(track)
                await ctx.send(f"➕ Queued: **{track.title}**")

    @commands.command(name="skip", help="Skip the current track.")
    async def skip(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client if isinstance(
            ctx.voice_client, wavelink.Player) else None
        if not player or not player.playing:
            await ctx.send("Nothing to skip.")
            return
        await player.stop()  # triggers track_end, which pulls next from queue
        await ctx.send("⏭️ Skipped.")

    @commands.command(name="pause", help="Pause playback.")
    async def pause(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client if isinstance(
            ctx.voice_client, wavelink.Player) else None
        if not player or not player.playing:
            await ctx.send("Nothing is playing.")
            return
        await player.pause(True)
        await ctx.send("⏸️ Paused.")

    @commands.command(name="resume", help="Resume playback.")
    async def resume(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client if isinstance(
            ctx.voice_client, wavelink.Player) else None
        if not player:
            await ctx.send("I'm not connected.")
            return
        await player.pause(False)
        await ctx.send("▶️ Resumed.")

    @commands.command(name="stop", help="Stop playback and clear the queue.")
    async def stop(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client if isinstance(
            ctx.voice_client, wavelink.Player) else None
        if not player:
            await ctx.send("I'm not connected.")
            return
        player.queue.clear()
        await player.stop()
        await ctx.send("⏹️ Stopped and cleared the queue.")

    @commands.command(name="queue", aliases=["q"], help="Show the next few tracks in queue.")
    async def queue_cmd(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client if isinstance(
            ctx.voice_client, wavelink.Player) else None
        if not player:
            await ctx.send("I'm not connected.")
            return
        if not player.queue:
            await ctx.send("The queue is empty.")
            return

        upcoming = list(player.queue)[:10]
        lines = [f"{i+1}. {t.title}" for i, t in enumerate(upcoming)]
        await ctx.send("🎶 **Queue**:\n" + "\n".join(lines))


# ---------- Your existing fun commands ----------
@bot.command()
async def twolove(ctx):
    await ctx.send("2 LØVE 2 LØVE")


@bot.command()
async def gog(ctx):
    await ctx.send("gog shut the fuck up")


# ---------- Add Cog + Run ----------
async def main():
    await bot.add_cog(Music(bot))
    await bot.start(TOKEN)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
