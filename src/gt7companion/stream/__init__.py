"""The program and the user's stream: the chat of Twitch and YouTube.

``twitch.py`` reads the chat of a Twitch channel and, after the user signed in, announces new
followers and subs and writes the Box's answers into the chat. ``youtube.py`` reads the live
chat of a YouTube stream. ``chat.py`` holds what both share.

Both put what they read on the bus (see ``chat.py``); the Box answers mentions through
``engineer/announcer.py``. Nothing here is needed for the dashboard: everything stays off until
it is switched on on the stream page.
"""
