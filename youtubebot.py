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

@bot.command(name='play', aliases=['p'])
async def play(ctx: commands.Context, *args):
    voice_state = ctx.author.voice
    if not await sense_checks(ctx, voice_state=voice_state):
        return

    query = ' '.join(args)
    # this is how it's determined if the url is valid (i.e. whether to search or not) under the hood of yt-dlp
    will_need_search = not urllib.parse.urlparse(query).scheme

    server_id = ctx.guild.id

    # source address as 0.0.0.0 to force ipv4 because ipv6 breaks it for some reason
    # this is equivalent to --force-ipv4 (line 312 of https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/options.py)
    await ctx.send(f'looking for `{query}`...')
    with yt_dlp.YoutubeDL({'format': YTDL_FORMAT,
                           'source_address': '0.0.0.0',
                           'default_search': 'ytsearch',
                           'outtmpl': '%(id)s.%(ext)s',
                           'noplaylist': True,
                           'allow_playlist_files': False,
                           # 'progress_hooks': [lambda info, ctx=ctx: video_progress_hook(ctx, info)],
                           # 'match_filter': lambda info, incomplete, will_need_search=will_need_search, ctx=ctx: start_hook(ctx, info, incomplete, will_need_search),
                           'paths': {'home': f'./dl/{server_id}'}}) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
        except yt_dlp.utils.DownloadError as err:
            await notify_about_failure(ctx, err)
            return
        
        #NOTE: just a test print to discord chat
        #await ctx.send(f"Response from youtube type: {type(info)}, content (100 first chars): {str(info)[0:100]}")

        if 'entries' in info:
            if len(info['entries']) > 0:
                info = info['entries'][0]
            else:
                await ctx.send(f"No results found with `{query}`.")
                return
                

        #getting duration of the youtube search entry we have selected
        video_duration: float = info.get('duration', None)
        video_duration_minutes: float = round(video_duration / 60, 2)
        print(f'duration of the video to be played: {video_duration}')
        #if duration wasnt gotten lets not do anything for now
        if video_duration == None:
            await ctx.send(f"Response from youtube did not contain duration property. Wont play anything that does not have a duration")
            return    
        #if duration exceeds 1800 seconds = 30 minutes, we info the user that wont play such long and return
        if video_duration > 1800:
            await ctx.send(f"Duration of the video exceeds 1800 seconds/30 minutes (duration of the video in link was {video_duration_minutes} minutes), will only play max 30 minute videos.")
            return    

        # send link if it was a search, otherwise send title as sending link again would clutter chat with previews
        download_info_text: str = 'downloading ' + (f'https://youtu.be/{info["id"]}' if will_need_search else f'`{info["title"]}`')
        download_info_text: str = f'{download_info_text}, play duration will be {video_duration_minutes} minutes'
        await ctx.send(download_info_text)
        try:
            ydl.download([query])
        except yt_dlp.utils.DownloadError as err:
            await notify_about_failure(ctx, err)
            return
        path = f'./dl/{server_id}/{info["id"]}.{info["ext"]}'
        try:
            queues[server_id]['queue'].append((path, info))
        except KeyError: # first in queue
            queues[server_id] = {'queue': [(path, info)], 'loop': False}
            try: connection = await voice_state.channel.connect()
            except discord.ClientException: connection = get_voice_client_from_channel_id(voice_state.channel.id)
            connection.play(discord.FFmpegOpusAudio(path), after=lambda error=None, connection=connection, server_id=server_id:
                                                             after_track(error, connection, server_id))

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
