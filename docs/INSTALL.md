# Installing – step by step

*Deutsch: [INSTALL.de.md](INSTALL.de.md)*

You need a Mac or a Windows PC in the same home network as your PlayStation, and about
ten minutes. Nothing is installed outside the program's own folder (except Python itself).

> The Mac steps were run on a Mac with Apple silicon. **The Windows steps are untested** –
> they should work, but nobody has tried them on a real Windows PC yet. If something goes
> wrong, please open an issue: <https://github.com/qshiqshi/gt7-companion-by-qshi/issues>.

## 1. Install Python (once)

The program is written in Python and needs version 3.12 or newer.

- **Mac:** download the installer from <https://www.python.org/downloads/> and run it.
- **Windows:** download the installer from <https://www.python.org/downloads/>, run it and tick
  **"Add python.exe to PATH"** on its first page.

## 2. Get the program

Open <https://github.com/qshiqshi/gt7-companion-by-qshi>, click the green button **Code** → **Download ZIP**. Unpack the
ZIP and move the folder to a place where it can stay, for example your Documents folder.

(If you know git: `git clone` the repository instead; `git pull` updates it later.)

## 3. Start it

- **Mac:** double-click `start-mac.command`. The first time macOS refuses because the file
  comes from the internet: right-click the file → **Open** → **Open**. (Or open the Terminal,
  type `bash `, drag the file into the window and press Return.)
- **Windows:** double-click `start-windows.bat`. If Windows shows "Windows protected your PC",
  click **More info** → **Run anyway**.

The first start sets everything up and takes a few minutes. Then a small symbol appears –
on the Mac in the menu bar at the top right, on Windows in the tray next to the clock – and
the dashboard opens in your browser with a demo lap.

To quit, click the symbol → **Quit**. To start again, double-click the same file.

<img src="images/en/dashboard.png" width="640" alt="Dashboard">

Move the pointer (or touch the screen) and a small menu appears at the top right – with
**Edit** you rearrange the dashboard:

<img src="images/en/menu.png" width="540" alt="Menu">

## 4. Connect your PlayStation

1. PlayStation and computer are in the same home network (not a guest Wi-Fi).
2. Start Gran Turismo 7.
3. Click the symbol → **Settings** → *Where does the data come from?* → **PlayStation in the
   home network** → **Save**.

The console is found by itself. The first time your computer asks whether the program may
receive data from the network – allow it (Windows: "Allow access"; Mac: "Allow").

<img src="images/en/settings-source.png" width="500" alt="Settings">

Nothing arrives? Quit other telemetry programs (only one can listen at a time), and check
that both devices are in the same network.

## 5. Tablet, phone, second screen

Click the symbol → **Share in the home network**, then → **Connect devices**. Scan the QR code
with the tablet's camera. To change layouts on the tablet, tap **Edit** there and enter the
PIN from the same page.

<img src="images/en/connect.png" width="430" alt="Connect">

<img src="images/en/tablet.png" width="430" alt="Tablet">

## 6. Stream overlay in OBS

Add a source of the kind **Browser**, width 1920, height 1080, address:

```
http://127.0.0.1:8707/?obs=1
```

<img src="images/en/overlay.png" width="640" alt="Overlay">

## 7. The Box – race engineer on the radio (optional)

1. Get an API key in Google AI Studio (<https://aistudio.google.com/>). Using it costs money;
   Google bills it to your account.
2. Symbol → **Settings** → *The Box*: tick **Switch on the messages**, paste the key,
   **Save the key**, then **Check** and **Test message**.

<img src="images/en/settings-box.png" width="360" alt="Box">

### "Hey Box" (optional)

To ask without pressing a button, the computer needs speech recognition. Install it once:

- **Mac:** open the Terminal, type `cd `, drag the program's folder into the window, press
  Return, then run: `.venv/bin/python -m pip install -e ".[wake]"`
- **Windows:** open the program's folder, click into the address bar, type `cmd`, press Enter,
  then run: `.venv\Scripts\python.exe -m pip install -e ".[wake]"`

Start the program again and tick **Listen for "Hey Box"** in the settings. The first use
downloads the recognition model (about 500 MB).

## Updating

Download the ZIP again and replace the folder (or `git pull`). Your settings and your own
layouts are not in that folder; they stay. If the start file reports a problem after an
update, delete the folder `.venv` inside the program's folder and start again.

## Removing

Quit the program and delete its folder. Your settings are in
`~/Library/Application Support/gt7-companion-by-qshi` (Mac) or
`%LOCALAPPDATA%\gt7-companion-by-qshi` (Windows); delete that folder, too, if you like.
