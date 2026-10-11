# Stream – Twitch, YouTube, Discord, OBS

*Deutsch: [STREAM.de.md](STREAM.de.md)*

The page **Stream** connects the program with your stream: on the start page **Connect Twitch,
YouTube, Discord and OBS**, or directly `http://127.0.0.1:8707/stream`. All of it is optional – the
dashboard runs as usual without.

What the Box does with the chat:

- **Questions from the chat:** whoever writes your channel's name in the chat – "@yourchannel how
  much fuel is left?" – gets an answer on the radio. With Gemini the Box answers freely and looks the
  numbers up in the data of the drive. When the Mac speaks by itself, it answers questions about fuel,
  laps, lap times, tyres, starting position, speed and incidents, and reads everything else out ("Max
  writes: …").
- **Answer in the chat** (Twitch, signed in): the answer also appears in the chat, as a reply to the
  question.
- **Followers and subs** (Twitch, signed in): the Box welcomes new followers, subs and resubs by name.
- **Question for the Box:** the menu of the dashboard has a field where you – on the computer or on a
  paired device – type a question. The Box answers on the radio as it does a spoken question.

For the Box to speak it has to be switched on in the **Settings**. There, under "What should be
announced?", you also find **Answer questions from the chat** and **New followers and subs**; switching
them on on the stream page ticks them there, too.

**Cost and limits.** With Gemini every answer costs a turn on your key, like every announcement; the
limits of the Box (per minute, per session) count for the chat as well. On top of that the Box answers
the chat at most once every 8 seconds and the same viewer at most once every 45 seconds; a question that
waited longer than 30 seconds is left out. Commands (`!…`), known bots and your own messages are never
answered. Gemini gets the chat as a viewer's words, not as instructions, and does not answer anything
insulting. Still: whatever the Box says can be heard live in the stream.

## Twitch

### Reading and answering the chat – without signing in

1. Under **Channel** enter the name of your channel as it appears in its address
   (`twitch.tv/yourchannel` → `yourchannel`). The whole address works too.
2. Tick **Read the chat**. The program follows the chat like a viewer who is not signed in; the page
   says "Connected to the chat of …" and counts the messages.
3. Tick **Mentions to the Box**.
4. To try it, write from another account (or have somebody write): "@yourchannel how much fuel do I
   have left?"

Whatever you write into your own chat is never taken as a question to the Box.

### Signing in – for answers in the chat, followers and subs

1. On the computer running the program, click **Sign in at Twitch**. (Other devices do not have the
   button.)
2. The page shows a code and **Open twitch.tv/activate**. Sign in there with your channel's account,
   enter the code and confirm what the program may do.
3. After a few seconds the page says "Signed in at Twitch as …". If **Channel** was empty, the program
   fills in your channel.
4. Tick **Answer in the chat** and/or **Announce followers and subs**.

The program never gets your password, only an access (a "token"). It keeps it on this computer alone,
in `secrets.json`, which only you can read, and never shows it. **Sign out** hands it back to Twitch and
deletes it; you can also take it back at Twitch under Settings → Connections ("Other Connections"). If
the program does not run for 30 days, the sign-in runs out; then sign in again.

The program asks for these rights: reading and writing the chat (`chat:read`, `chat:edit`,
`user:read:chat`, `user:write:chat`), seeing followers (`moderator:read:followers`) and seeing subs
(`channel:read:subscriptions`). Twitch reports followers only to the channel's account and its
moderators, and subs only to the channel itself, and only for partners and affiliates.

### When "Sign in at Twitch" is missing

Signing in needs an app registered at Twitch. If your version has none yet, the page shows a note
instead of the button – reading and answering the chat works all the same. With an app of your own you
can sign in, too:

1. Log in at <https://dev.twitch.tv/console/apps>. Twitch requires two-factor authentication to be
   switched on for your account.
2. **Register Your Application**:
   - **Name:** anything, but unique at Twitch, for example "GT7 Companion for yourchannel".
   - **OAuth Redirect URLs:** enter `http://localhost` and click **Add** (the program does not use one,
     but the form needs it).
   - **Category:** whatever fits best, for example "Broadcasting Suite" or "Other".
   - **Client Type:** **Public**.
3. **Create**, then **Manage** at the app: copy the **Client ID**. You do not need a client secret.
4. On the stream page, enter the client ID under **Advanced**. Then **Sign in at Twitch** appears.

> **Note for the project's maintainer:** to make signing in work for everybody without an app of their
> own, register an app as above once (name for example "GT7 Companion by qshi", client type **Public**,
> redirect `http://localhost`) and enter its client ID in `src/gt7companion/stream/twitch.py` as
> `TWITCH_CLIENT_ID`. A client ID is not secret, and a public app has no secret.

## YouTube

1. Under **Channel or stream** enter your handle (`@yourchannel`), the address of your channel or the
   address of the running stream.
2. Tick **Read the chat** and **Mentions to the Box**.
3. As soon as you are live, the page says "Live stream found: …". Given the channel, the program looks
   for a running stream every minute; **Look now** looks at once.

No Google sign-in is needed: the program reads the public live chat as a viewer sees it who is not
signed in. It writes nothing into the YouTube chat – the Box's answers are heard on the radio only. A
mention is your handle or your channel's name as a word of its own.

> YouTube has no official way to read along without an account; the program does what YouTube's own
> chat page does in a browser. If YouTube changes that, the page says "YouTube has changed its chat" –
> then an update of the program helps. A stream without a chat cannot be read.

## Discord

The Box in the headset: a Discord bot of your own plays its voice and the brake tones into a voice
channel that you join from the PlayStation. Step by step – create the bot, invite it, enter the token,
join from the PS5 – in [DISCORD.md](DISCORD.md).

## OBS

The button **Open OBS with the overlay** (on the start page and on the *OBS* card) starts OBS when it is
not running, connects to its WebSocket server and adds the browser source "GT7 Companion Overlay" to the
current scene – 1920 × 1080, audio through OBS. A source that is there already stays as it is. The
program never starts OBS on its own.

Once in OBS: **Tools → WebSocket Server Settings → Enable WebSocket server** (leave the port at 4455),
then **Show Connect Info** and enter the password on the *OBS* card. If OBS runs on another computer,
enter its name or address under *Advanced*; the overlay is then loaded through the home network
(sharing under *Settings*). The way by hand is in the [install guide](INSTALL.md#6-stream-overlay-in-obs).
