import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import yt_dlp

from cogs.helpers import (
    Colors, BLANK_COLOR, CHECK, CROSS, CSRP_ICON,
    success_embed, error_embed, info_embed, brand_footer, embed_description,
)

queues: dict[int, list[dict[str, str]]] = {}
now_playing: dict[int, dict] = {}


def search_youtube(query: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
            return {
                'url': info['url'],
                'title': info['title'],
                'duration': info['duration'],
                'webpage_url': info['webpage_url'],
                'thumbnail': info.get('thumbnail', ''),
            }
        except Exception as e:
            print(f"Error searching YouTube: {e}")
            return None


def format_duration(seconds):
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def play_next_song(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in queues or len(queues[guild_id]) == 0:
            now_playing.pop(guild_id, None)
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            return

        song = queues[guild_id].pop(0)
        now_playing[guild_id] = song
        source = discord.FFmpegPCMAudio(song['url'], before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")

        def after_playing(e):
            asyncio.run_coroutine_threadsafe(self.play_next_song(ctx), self.bot.loop)

        embed = discord.Embed(
            title="Now Playing",
            description=embed_description(
                f"> [{song['title']}]({song['webpage_url']})",
                (
                    f"> **Duration:** `{format_duration(song['duration'])}`\n"
                    + (f"> **Up Next:** {queues[guild_id][0]['title']}" if guild_id in queues and queues[guild_id] else "")
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        if song.get('thumbnail'):
            embed.set_thumbnail(url=song['thumbnail'])
        brand_footer(embed)
        await ctx.send(embed=embed)

        ctx.voice_client.play(source, after=after_playing)

    @commands.hybrid_command(name="play", description="Play a song from YouTube.")
    @app_commands.describe(query="The song to play.")
    async def play(self, ctx: commands.Context, *, query: str):
        if ctx.author.voice is None:
            await ctx.reply(embed=error_embed("Not in Voice Channel", "You need to be in a voice channel to use this command."))
            return

        voice_channel = ctx.author.voice.channel
        guild_id = ctx.guild.id

        song = search_youtube(query)
        if not song:
            await ctx.reply(embed=error_embed("Song Not Found", "Could not find the song on YouTube."))
            return

        if guild_id not in queues:
            queues[guild_id] = []

        queues[guild_id].append(song)

        if not ctx.voice_client or not ctx.voice_client.is_connected():
            await voice_channel.connect()
            await self.play_next_song(ctx)
        elif not ctx.voice_client.is_playing():
            await self.play_next_song(ctx)
        else:
            embed = discord.Embed(
                title="Added to Queue",
                description=embed_description(
                    f"> [{song['title']}]({song['webpage_url']})",
                    (
                        f"> **Duration:** `{format_duration(song['duration'])}`\n"
                        f"> **Position:** `#{len(queues[guild_id])}`"
                    ),
                ),
                color=BLANK_COLOR,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
            if song.get('thumbnail'):
                embed.set_thumbnail(url=song['thumbnail'])
            brand_footer(embed)
            await ctx.reply(embed=embed)

    @commands.hybrid_command(name="queue", description="Show the current song queue.")
    async def queue(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        if guild_id not in queues or len(queues[guild_id]) == 0:
            await ctx.reply(embed=info_embed("Song Queue", "The queue is empty."))
            return

        embed = discord.Embed(
            title="Song Queue",
            description="\n\n".join(
                f"**{index}. {song['title']}**\n> `{format_duration(song['duration'])}` — [Link]({song['webpage_url']})"
                for index, song in enumerate(queues[guild_id][:10], start=1)
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        total = len(queues[guild_id])
        footer = f"{total} song{'s' if total != 1 else ''} in queue"
        if total > 10:
            footer += f" (showing first 10)"
        embed.set_footer(text=f"{footer} • CSRP Utilities", icon_url=CSRP_ICON)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", description="Show the currently playing song.")
    async def nowplaying(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        song = now_playing.get(guild_id)
        if not song or not ctx.voice_client or not ctx.voice_client.is_playing():
            await ctx.reply(embed=info_embed("Now Playing", "No song is currently playing."))
            return

        embed = discord.Embed(
            title="Now Playing",
            description=embed_description(
                f"> [{song['title']}]({song['webpage_url']})",
                (
                    f"> **Duration:** `{format_duration(song['duration'])}`\n"
                    + (f"> **Up Next:** {queues[guild_id][0]['title']}" if guild_id in queues and queues[guild_id] else "")
                ),
            ),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        if song.get('thumbnail'):
            embed.set_thumbnail(url=song['thumbnail'])
        brand_footer(embed)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="skip", description="Skip the current song.")
    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.reply(embed=success_embed("Song Skipped", "Skipped the current song."))
        else:
            await ctx.reply(embed=error_embed("Nothing Playing", "No song is currently playing."))

    @commands.hybrid_command(name="pause", description="Pause the current song.")
    async def pause(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.reply(embed=success_embed("Playback Paused", "Playback has been paused."))
        else:
            await ctx.reply(embed=error_embed("Nothing Playing", "No song is currently playing."))

    @commands.hybrid_command(name="resume", description="Resume the paused song.")
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.reply(embed=success_embed("Playback Resumed", "Playback has been resumed."))
        else:
            await ctx.reply(embed=error_embed("Nothing Paused", "No song is currently paused."))

    @commands.hybrid_command(name="stop", description="Stop playback and clear the queue.")
    async def stop(self, ctx: commands.Context):
        if ctx.voice_client:
            guild_id = ctx.guild.id
            now_playing.pop(guild_id, None)
            if guild_id in queues:
                queues[guild_id].clear()
            await ctx.voice_client.disconnect()
            await ctx.reply(embed=success_embed("Playback Stopped", "Stopped playback and cleared the queue."))
        else:
            await ctx.reply(embed=error_embed("Not Connected", "I'm not connected to a voice channel."))


async def setup(bot):
    await bot.add_cog(Music(bot))
