# The Box in the headset: setting up Discord

*Deutsche Fassung: [DISCORD.de.md](DISCORD.de.md)*

The Box – the race engineer on the radio – speaks from the computer's loudspeakers, from every
browser showing the dashboard and from the OBS source. Whoever sits at the PlayStation with a
headset hears none of it. This is the way around that: a **Discord bot of your own** plays the
voice of the Box and the brake tones into a voice channel; you join the same channel **from the
PlayStation** and hear both in the headset, mixed with the sound of the game.

The bot **only sends**. It does not listen, reads no messages and writes none. Questions to the
Box still go through the talk button, "Hey Box" or the chat. Your viewers are not affected: the
PlayStation does not put Discord audio on HDMI, so the stream keeps getting the Box from the OBS
source alone – no double voice.

Setting it up takes about ten minutes, once.

## What you need

- a Discord account and a **server of your own** (or one where you may invite bots – you create
  your own in Discord with **+** → "Create My Own" in a minute),
- a PlayStation 5 with a linked Discord account (step 4),
- the program on Mac or Windows (the app brings everything; from source: `pip install -e
  ".[discord]"`, on a Mac also `brew install opus`).

## 1. Create the bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and sign in.
2. **New Application** → a name such as "GT7 Companion" → **Create**.
3. Choose **Bot** on the left. Under **Token** click **Reset Token** (with two-factor
   authentication Discord asks for the code) and **copy** the token – it is shown this once
   only. Treat it like a password.
4. The bot needs **no** "Privileged Gateway Intents"; everything below can stay off.

## 2. Invite the bot to your server

1. Choose **OAuth2** on the left, then **OAuth2 URL Generator**.
2. Under **Scopes** tick **bot** only.
3. Under **Bot Permissions** tick **Connect** and **Speak** only (in the group *Voice
   Permissions*).
4. Copy the generated address at the bottom, open it in the browser, choose your server,
   **Authorize**.

The bot now appears as a member of your server (offline until the program starts it).

## 3. Enter it in the program

1. Start page → **Connect Twitch, YouTube, Discord and OBS** (the *Stream* page), card
   **Discord**.
2. Paste the token → **Save token**. It stays on this computer only (`secrets.json`, readable
   by you alone) and is never shown again.
3. Tick **Send the Box into the Discord voice channel**. Under **Voice channel** enter the name
   of the channel (empty: the server's first voice channel). **Save**.
4. After a few seconds it says: *The bot is in the channel "…" on "…".* **Test tone** plays a
   brake tone and a sample message into the channel.

The brake tones come along as long as **Brake tones into the channel as well** is ticked.

## 4. Join from the PlayStation

1. PS5: **Settings → Users and Accounts → Linked Services → Discord** → link (once, through the
   phone or the browser).
2. In the game open the control centre (PS button) → **Game Base** → **Discord** → choose your
   server and the bot's voice channel → join. Or join the channel in Discord on the phone and
   choose **Transfer to PlayStation** there.
3. In the control centre under **Sound** mix the volume of voice chat and game.

Now you hear the Box and the brake tones in the headset.

## Good to know

- **Delay:** through Discord the sound arrives about a quarter of a second later than from the
  computer's loudspeakers. Nothing for messages; whoever wants the brake tones to the tenth
  hears them better straight from the computer, tablet or phone (menu of the dashboard →
  **Brake tones**).
- **Sending only:** the bot receives nothing from the channel. Its microphone symbol in Discord
  stays muted – that is as it should be.
- **Whoever else is in the channel** hears the Box too. For a channel of your own: create a
  voice channel in Discord that only you and the bot can see.
- **Token lost or leaked?** In the Developer Portal under **Bot** → **Reset Token**: the old one
  is void, enter the new one in the program.
- **Removing the bot:** remove the token in the program, kick the bot from the server in
  Discord, delete the application in the Developer Portal.

## If something does not work

| The card says … | Meaning | Remedy |
|---|---|---|
| Discord does not accept the token | token wrong or reset | **Reset Token** in the Developer Portal, enter the new one |
| The bot is not on any server yet | step 2 missing | invite it with the generated address |
| The bot's server has no voice channel | text channels only | create a voice channel in Discord |
| The bot could not join the voice channel | permissions missing | allow the bot (or its role) **Connect** and **Speak** in the channel |
| The Opus library is missing | from source on a Mac only | `brew install opus`, restart the program |
| This program runs without Discord support | extra missing (source) | `pip install -e ".[discord]"`, restart the program |
| The connection to Discord broke off | network or Discord | the program tries again every ten seconds |
