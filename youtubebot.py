#!/usr/bin/env python3.10

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

bot = commands.Bot(command_prefix='.')
queues = {} # {server_id: [vid_file, ...]}

def main():
    with open('./token.txt') as t:
        lines = t.readlines()
        token = lines[0][:-1]
    bot.run(token)

@bot.command(name='skip', aliases=['s'])
async def skip(ctx: commands.Context, *args):
    try: queue_length = len(queues[ctx.guild.id])
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
        queues[ctx.guild.id].pop(0)
    voice_client.stop()

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
    with yt_dlp.YoutubeDL({'format': 'worstaudio',
                           'source_address': '0.0.0.0',
                           'default_search': 'ytsearch',
                           'outtmpl': '%(id)s.%(ext)s',
                           'noplaylist': True,
                           'allow_playlist_files': False,
                           # 'progress_hooks': [lambda info, ctx=ctx: video_progress_hook(ctx, info)],
                           # 'match_filter': lambda info, incomplete, will_need_search=will_need_search, ctx=ctx: start_hook(ctx, info, incomplete, will_need_search),
                           'paths': {'home': f'./dl/{server_id}'}}) as ydl:
        info = ydl.extract_info(query, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        # send link if it was a search, otherwise send title as sending link again would clutter chat with previews
        await ctx.send('downloading ' + (f'https://youtu.be/{info["id"]}' if will_need_search else f'`{info["title"]}`'))
        ydl.download([query])
        
        path = f'./dl/{server_id}/{info["id"]}.{info["ext"]}'
        try: queues[server_id].append(path)
        except KeyError: # first in queue
            queues[server_id] = [path]
            try: connection = await voice_state.channel.connect()
            except discord.ClientException: connection = get_voice_client_from_channel_id(voice_state.channel.id)
            connection.play(discord.FFmpegOpusAudio(path), after=lambda error=None, connection=connection, server_id=server_id:
                                                             after_track(error, connection, server_id))

def get_voice_client_from_channel_id(channel_id: int):
    for voice_client in bot.voice_clients:
        if voice_client.channel.id == channel_id:
            return voice_client

def after_track(error, connection, server_id):
    if error is not None:
        print(error)
    try: path = queues[server_id].pop(0)
    except KeyError: return # probably got disconnected
    if path not in queues[server_id]: # check that the same video isn't queued multiple times
        try: os.remove(path)
        except FileNotFoundError: pass
    try: connection.play(discord.FFmpegOpusAudio(queues[server_id][0]), after=lambda error=None, connection=connection, server_id=server_id:
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
        await ctx.send('you have to be in a vc to use this command')
        return False

    if bot.user.id not in [member.id for member in ctx.author.voice.channel.members] and ctx.guild.id in queues.keys():
        await ctx.send('you have to be in the same vc as the bot to use this command')
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
async def on_command_error(event: str, *args, **kwargs):
    type_, value, traceback = sys.exc_info()
    sys.stderr.write(f'{type_}: {value} raised during {event}, {args=}, {kwargs=}')
    sp.run(['./restart'])


#def ydl_download_in_new_thread(ydl, query):
#    def run_in_asyncio_loop(ydl, query):
#        loop = asyncio.new_event_loop()
#        asyncio.set_event_loop(loop)
#        loop.run_until_complete(async_ydl_download(ydl, query))
#        loop.close()
#
#    async def async_ydl_download(ydl, query):
#        ydl.download([query])
#
#    threading.Thread(target=run_in_asyncio_loop, args=(ydl, query)).start()

#def start_hook(ctx, info: dict, incomplete: bool, will_need_search: bool):
#    if incomplete:
#        return
#    if will_need_search:
#        # send link as input was a search
#        message = f'Downloading https://youtu.be/{info["id"]}'
#    else:
#        # send title as link has already been sent, sending again would clutter chat with previews
#        message = f'Downloading `{info["title"]}`'
#    # everything else works but this is incredibly slow for some reason
#    bot.loop.create_task(ctx.send(message))

#def send_message_in_new_thread(ctx, message):
#    def run_in_asyncio_loop(ctx, message):
#        loop = asyncio.new_event_loop()
#        asyncio.set_event_loop(loop)
#        loop.run_until_complete(ctx.send(message))
#        loop.close()
#    threading.Thread(target=run_in_asyncio_loop, args=(ctx, message)).start()

# would use progress hooks but yt-dlp expects sync while discord.py uses async.
# implementation as below (commented) tries to create a task using discord.py's asyncio loop
# but this only runs after yt-dlp finishes downloading as it is blocking/synchronous on this loop
#def video_progress_hook(ctx, info: dict):
#    if info['status'] == 'downloading':
#        info_dict = info['info_dict']
#        print(info['elapsed'])
#        bot.loop.create_task(ctx.send(f'Downloading `{info_dict["title"]}`'))

@bot.event
async def on_ready():
    print(f'logged in successfully as {bot.user.name}')

if __name__ == '__main__':
    main()