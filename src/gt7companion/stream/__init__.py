"""How the program joins a stream: the chat of Twitch and YouTube, the Box in a Discord voice
channel, the overlay in OBS. Each service is optional, lives in a module of its own and stays
off until it is switched on on the stream page.

``twitch.py`` reads the chat of a Twitch channel and, after the user signed in, announces new
followers and subs and writes the Box's answers into the chat. ``youtube.py`` reads the live
chat of a YouTube stream. ``chat.py`` holds what both share; both put what they read on the bus
(see ``chat.py``), and the Box answers mentions through ``engineer/announcer.py``.
``discord_voice.py`` sends the voice of the Box and the brake tones into a voice channel,
``obs.py`` puts the overlay into OBS on one button.
"""
