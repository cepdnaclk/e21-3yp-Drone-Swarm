Install dependencies and run

This project requires Python 3.7+ and the `pyserial` package. Tkinter is part of the standard library on Windows and macOS; on some Linux variants you may need to install a system package (e.g. `python3-tk`).

Quick install (Windows / macOS / Linux):

```bash
python -m venv venv
# On Windows PowerShell
venv\Scripts\Activate.ps1
# On Windows cmd
venv\Scripts\activate.bat
# On macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

Run the controller (replace COM port as needed):

```bash
python python_drone_controller.py --port COM5
# or on Linux
python python_drone_controller.py --port /dev/ttyUSB0
```

If you see an ImportError for `tkinter` on Linux, install the system package, e.g. on Debian/Ubuntu:

```bash
sudo apt install python3-tk
```

If you want me to install packages directly into your environment now, tell me which Python interpreter or let me run the install for you.
