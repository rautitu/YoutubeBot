#!/usr/bin/env python3
import re

import discord
from discord.ext import commands
import yt_dlp
import urllib
import asyncio
import threading
import os
import shutil
import sys
import subprocess as sp
from dotenv import load_dotenv
import requests

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
PREFIX = os.getenv('BOT_PREFIX', '.')
YTDL_FORMAT = os.getenv('YTDL_FORMAT', 'worstaudio')
PRINT_STACK_TRACE = os.getenv('PRINT_STACK_TRACE', '1').lower() in ('true', 't', '1')
BOT_REPORT_COMMAND_NOT_FOUND = os.getenv('BOT_REPORT_COMMAND_NOT_FOUND', '1').lower() in ('true', 't', '1')
BOT_REPORT_DL_ERROR = os.getenv('BOT_REPORT_DL_ERROR', '0').lower() in ('true', 't', '1')
MAX_DURATION_SECONDS = int(os.getenv('MAX_DURATION_SECONDS'))
DOWNLOAD_RATE_LIMIT = os.getenv('DOWNLOAD_RATE_LIMIT')

try:
    COLOR = int(os.getenv('BOT_COLOR', 'ff0000'), 16)
except ValueError:
    print('the BOT_COLOR in .env is not a valid hex color')
    print('using default color ff0000')
    COLOR = 0xff0000

bot = commands.Bot(command_prefix=PREFIX, intents=discord.Intents(voice_states=True, guilds=True, guild_messages=True, message_content=True))
queues = {} # {server_id: 'queue': [(vid_file, info), ...], 'loop': bool}

def main():
    if TOKEN is None:
        return ("no token provided. Please create a .env file containing the token.\n"
                "for more information view the README.md")
    try: bot.run(TOKEN)
    except discord.PrivilegedIntentsRequired as error:
        return error

@bot.command(name='restart')
async def queue(ctx: commands.Context, *args):
    await ctx.send('Force restarting the bot, please wait for about 30 seconds for the bot to become responsive again')
    sys.stdout.write(f'Bot was force restarted using restart -command')
    #will exit with a non zero exit value which will trigger automatic restart for the container
    sys.exit(1)

@bot.command(name='queue', aliases=['q'])
async def queue(ctx: commands.Context, *args):
    try: queue = queues[ctx.guild.id]['queue']
    except KeyError: queue = None
    if queue == None:
        await ctx.send('the bot isn\'t playing anything')
    else:
        title_str = lambda val: '‣ %s\n\n' % val[1] if val[0] == 0 else '**%2d:** %s\n' % val
        queue_str = ''.join(map(title_str, enumerate([i[1]["title"] for i in queue])))
        embedVar = discord.Embed(color=COLOR)
        embedVar.add_field(name='Now playing:', value=queue_str)
        await ctx.send(embed=embedVar)
    if not await sense_checks(ctx):
        return
    
@bot.command(name='remove', aliases=['r'])
async def remove(ctx: commands.Context, index: int):
    try:
        queue = queues[ctx.guild.id]['queue']
    except KeyError:
        await ctx.send('The bot isn\'t playing anything, so there is nothing to remove.')
        return

    queue_length = len(queue)
    if queue_length <= 0:
        await ctx.send('The bot isn\'t playing anything, so there is nothing to remove.')
        return

    if not await sense_checks(ctx):
        return

    #user input validation
    if index < 0 or index >= queue_length or not isinstance(index, int):
        await ctx.send(f'Invalid index. Please choose a number between 0 (currently playing song) and {queue_length - 1} (current queue length).')
        return

    #if the remove targets currently playing song (index = 0), remove the first item and stop the voice client (forcing a skip essentially)
    if index == 0:
        #capturing the currently playing some to a variable
        removed_item = queues[ctx.guild.id]['queue'][0]
        #stopping the current track, triggering the next song to play
        voice_client = get_voice_client_from_channel_id(ctx.author.voice.channel.id)
        voice_client.stop()
    else:
        #removing the item at the given index
        removed_item = queues[ctx.guild.id]['queue'].pop(index)

    removed_title = removed_item[1].get("title", "Unknown Title")
    await ctx.send(f'Removed: **{removed_title}** from the queue.')

    if queues[ctx.guild.id]['queue']:
        await ctx.send(f"Queue length after removal: {len(queues[ctx.guild.id]['queue']) - 1}")
    else:
        await ctx.send('The queue is now empty.')


@bot.command(name='skip', aliases=['s'])
async def skip(ctx: commands.Context, *args):
    try: queue_length = len(queues[ctx.guild.id]['queue'])
    except KeyError: queue_length = 0
    if queue_length <= 0:
        await ctx.send('the bot isn\'t playing anything')
    if not await sense_checks(ctx):
        return

    try: n_skips = int(args[0])
    except IndexError:
        n_skips = 1
    except ValueError:
        if args[0] == 'all': n_skips = queue_length
        else: n_skips = 1
    if n_skips == 1:
        message = 'skipping track'
    elif n_skips < queue_length:
        message = f'skipping `{n_skips}` of `{queue_length}` tracks'
    else:
        message = 'skipping all tracks'
        n_skips = queue_length
    await ctx.send(message)

    voice_client = get_voice_client_from_channel_id(ctx.author.voice.channel.id)
    for _ in range(n_skips - 1):
        queues[ctx.guild.id]['queue'].pop(0)
    voice_client.stop()

@bot.command(name='leave')
async def leave(ctx: commands.Context):
    #voice_client = ctx.guild.voice_client  
    voice_client = get_voice_client_from_channel_id(ctx.author.voice.channel.id)
    server_id = ctx.guild.id
    if voice_client and voice_client.is_connected():
        if voice_client.is_playing():  # Stop any audio that is playing
            print("leave-command used, stopped current audio playback")
            voice_client.stop()  # This will stop the FFmpeg process
        queues.pop(server_id) # directory will be deleted on disconnect, will lead to error 
        message: str = f"Leaving channel {voice_client.channel}."
        print(f"leave-command used: {message}")
        await ctx.send(message) 
        await voice_client.disconnect()  
    else:
        message: str = "The bot is not connected to a voice channel, did nothing."
        print(f"leave-command used: {message}")
        await ctx.send(message)  

def is_bot_playing(server_id: int) -> bool:
    """Check if bot is currently playing audio in this server."""
    try:
        if server_id not in queues:
            return False
        # Check if there's a queue and if any voice client is playing for this server
        for voice_client in bot.voice_clients:
            if voice_client.guild.id == server_id and voice_client.is_playing():
                return True
        return False
    except:
        return False


def get_ydl_options(server_id: int, is_playing: bool = False) -> dict:
    """
    Build yt-dlp options dictionary.
    
    Args:
        server_id: Guild/server ID for download path
        is_playing: Whether bot is currently playing audio (throttles download if True)
    """
    options = {
        'format': YTDL_FORMAT,
        'source_address': '0.0.0.0',  # Force IPv4
        'default_search': 'ytsearch',
        'outtmpl': '%(id)s.%(ext)s',
        'noplaylist': True,
        'allow_playlist_files': False,
        'paths': {'home': f'./dl/{server_id}'}
    }
    
    # Throttle download if currently playing to prevent audio stuttering
    if is_playing:
        #options['ratelimit'] = DOWNLOAD_RATE_LIMIT
        options['ratelimit'] = 500
    
    return options


async def fetch_info(ctx: commands.Context, query: str, server_id: int, is_playing: bool = False) -> dict | None:
    """
    Fetch video info from YouTube without downloading.
    
    Returns:
        Video info dict or None if failed
    """
    will_need_search = not urllib.parse.urlparse(query).scheme
    
    await ctx.send(f'looking for `{query}`...')
    
    ydl_opts = get_ydl_options(server_id, is_playing)
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
        except yt_dlp.utils.DownloadError as err:
            await notify_about_failure(ctx, err)
            return None
        
        # Handle search results
        if 'entries' in info:
            if len(info['entries']) > 0:
                info = info['entries'][0]
            else:
                await ctx.send(f"No results found with `{query}`.")
                return None
        
        # Add search flag to info for later use
        info['_will_need_search'] = will_need_search
        return info


async def validate_duration(ctx: commands.Context, info: dict) -> bool:
    """
    Validate video duration is within acceptable limits.
    
    Returns:
        True if duration is valid, False otherwise
    """
    video_duration = info.get('duration', None)
    
    if video_duration is None:
        await ctx.send("Response from youtube did not contain duration property. "
                      "Won't play anything that does not have a duration")
        return False
    
    video_duration_minutes = round(video_duration / 60, 2)
    print(f'duration of the video to be played: {video_duration}')
    
    if video_duration > MAX_DURATION_SECONDS:
        await ctx.send(f"Duration of the video exceeds {MAX_DURATION_SECONDS} seconds/"
                      f"{MAX_DURATION_SECONDS//60} minutes (duration of the video in link was "
                      f"{video_duration_minutes} minutes), will only play max "
                      f"{MAX_DURATION_SECONDS//60} minute videos.")
        return False
    
    return True


async def send_download_message(ctx: commands.Context, info: dict):
    """Send informative download message to user."""
    will_need_search = info.get('_will_need_search', False)
    video_duration = info.get('duration', 0)
    video_duration_minutes = round(video_duration / 60, 2)
    
    # Send link if it was a search, otherwise send title to avoid preview clutter
    if will_need_search:
        download_info = f'downloading https://youtu.be/{info["id"]}'
    else:
        download_info = f'downloading `{info["title"]}`'
    
    download_info += f', play duration will be {video_duration_minutes} minutes'
    await ctx.send(download_info)


async def download_audio(ctx: commands.Context, query: str, server_id: int, is_playing: bool = False) -> bool:
    """
    Download audio file with optional bandwidth throttling.
    
    Args:
        ctx: Command context
        query: Search query or URL
        server_id: Guild/server ID
        is_playing: Whether bot is currently playing (throttles download if True)
    
    Returns:
        True if successful, False otherwise
    """
    ydl_opts = get_ydl_options(server_id, is_playing)
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([query])
            return True
        except yt_dlp.utils.DownloadError as err:
            await notify_about_failure(ctx, err)
            return False


def add_to_queue(server_id: int, path: str, info: dict):
    """
    Add track to server queue.
    
    Returns:
        True if this is the first track (queue was created), False if added to existing queue
    """
    try:
        queues[server_id]['queue'].append((path, info))
        return False  # Queue already existed
    except KeyError:
        # First track in queue
        queues[server_id] = {'queue': [(path, info)], 'loop': False}
        return True  # Queue was just created


async def start_playback(voice_state: discord.VoiceState, server_id: int, path: str):
    """
    Connect to voice channel and start playback.
    Should only be called for the first track in queue.
    """
    try:
        connection = await voice_state.channel.connect()
    except discord.ClientException:
        connection = get_voice_client_from_channel_id(voice_state.channel.id)
    
    connection.play(
        discord.FFmpegOpusAudio(path),
        after=lambda error=None, connection=connection, server_id=server_id:
            after_track(error, connection, server_id)
    )


@bot.command(name='play', aliases=['p'])
async def play(ctx: commands.Context, *args):
    """Main play command - orchestrates the music playing process."""
    voice_state = ctx.author.voice
    if not await sense_checks(ctx, voice_state=voice_state):
        return

    query = ' '.join(args)
    server_id = ctx.guild.id
    
    # Check if bot is currently playing to determine if we should throttle
    currently_playing = is_bot_playing(server_id)
    
    # Fetch video info (without downloading)
    info = await fetch_info(ctx, query, server_id, currently_playing)
    if info is None:
        return
    
    # Validate duration limits
    if not await validate_duration(ctx, info):
        return
    
    # Inform user about download
    await send_download_message(ctx, info)
    
    # Download with potential bandwidth throttling
    if not await download_audio(ctx, query, server_id, currently_playing):
        return
    
    # Build file path
    path = f'./dl/{server_id}/{info["id"]}.{info["ext"]}'
    
    # Add to queue and check if this is the first track
    is_first_track = add_to_queue(server_id, path, info)
    
    # Only start playback if this is the first track
    if is_first_track:
        await start_playback(voice_state, server_id, path)

@bot.command('loop', aliases=['l'])
async def loop(ctx: commands.Context, *args):
    if not await sense_checks(ctx):
        return
    try:
        loop = queues[ctx.guild.id]['loop']
    except KeyError:
        await ctx.send('the bot isn\'t playing anything')
        return
    queues[ctx.guild.id]['loop'] = not loop

    await ctx.send('looping is now ' + ('on' if not loop else 'off'))

@bot.command(name='joke', aliases=['juuzo'])
async def skip(ctx: commands.Context):
    joke_site_url: str = "https://icanhazdadjoke.com/"
    headers = {
    'Accept': 'application/json'
    }

    try:
        joke_api_response: str = requests.request("GET", joke_site_url, headers=headers)
        joke_data: dict = joke_api_response.json()
        joke: str = joke_data["joke"]
    except Exception as e:
        await ctx.send('Fetching joke failed with an error, view bot logs for the error. You can continue using the bot')
        print(f'Fetching a joke failed with an error: {str(e)}')
        return  
    await ctx.send(joke)

def get_voice_client_from_channel_id(channel_id: int):
    for voice_client in bot.voice_clients:
        if voice_client.channel.id == channel_id:
            return voice_client

def after_track(error, connection, server_id):
    if error is not None:
        print(error)
    try:
        last_video_path = queues[server_id]['queue'][0][0]
        if not queues[server_id]['loop']:
            os.remove(last_video_path)
            queues[server_id]['queue'].pop(0)
    except KeyError: return # probably got disconnected
    if last_video_path not in [i[0] for i in queues[server_id]['queue']]: # check that the same video isn't queued multiple times
        try: os.remove(last_video_path)
        except FileNotFoundError: pass
    try: connection.play(discord.FFmpegOpusAudio(queues[server_id]['queue'][0][0]), after=lambda error=None, connection=connection, server_id=server_id:
                                                                          after_track(error, connection, server_id))
    except IndexError: # that was the last item in queue
        queues.pop(server_id) # directory will be deleted on disconnect
        asyncio.run_coroutine_threadsafe(safe_disconnect(connection), bot.loop).result()

async def safe_disconnect(connection):
    if not connection.is_playing():
        await connection.disconnect()

async def sense_checks(ctx: commands.Context, voice_state=None) -> bool:
    if voice_state is None: voice_state = ctx.author.voice
    if voice_state is None:
        await ctx.send('you have to be in a voice channel to use this command')
        return False

    if bot.user.id not in [member.id for member in ctx.author.voice.channel.members] and ctx.guild.id in queues.keys():
        await ctx.send('you have to be in the same voice channel as the bot to use this command')
        return False
    return True

@bot.event
async def on_voice_state_update(member: discord.User, before: discord.VoiceState, after: discord.VoiceState):
    if member != bot.user:
        return
    if before.channel is None and after.channel is not None: # joined vc
        return
    if before.channel is not None and after.channel is None: # disconnected from vc
        # clean up
        server_id = before.channel.guild.id
        try: queues.pop(server_id)
        except KeyError: pass
        try: shutil.rmtree(f'./dl/{server_id}/')
        except FileNotFoundError: pass

@bot.event
async def on_command_error(ctx: discord.ext.commands.Context, err: discord.ext.commands.CommandError):
    # now we can handle command errors
    if isinstance(err, discord.ext.commands.errors.CommandNotFound):
        if BOT_REPORT_COMMAND_NOT_FOUND:
            await ctx.send("command not recognized. To see available commands type {}help".format(PREFIX))
        return

    await ctx.send("Bot hit an unrecognized error. Restarting the bot, please wait for about 30 seconds for the bot to become responsive again")
    # we ran out of handlable exceptions, re-start. type_ and value are None for these
    sys.stderr.write(f'unhandled command error raised, {err=}')
    sys.stderr.flush()
    sys.exit(1)

@bot.event
async def on_ready():
    print(f'logged in successfully as {bot.user.name}')

async def notify_about_failure(ctx: commands.Context, err: yt_dlp.utils.DownloadError):
    if BOT_REPORT_DL_ERROR:
        # remove shell colors for discord message
        sanitized = re.compile(r'\x1b[^m]*m').sub('', err.msg).strip()
        if sanitized[0:5].lower() == "error":
            # if message starts with error, strip it to avoid being redundant
            sanitized = sanitized[5:].strip(" :")
        await ctx.send('failed to download due to error: {}'.format(sanitized))
    else:
        await ctx.send('sorry, failed to download this video')
    return

if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemError as error:
        if PRINT_STACK_TRACE:
            raise
        else:
            print(error)
