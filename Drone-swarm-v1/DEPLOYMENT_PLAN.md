# Drone Swarm Desktop Distribution And AWS Hosting Plan

## Current System Structure

This repository contains three main parts:

- `computer_code/`: the PC-side control software.
  - `src/`: React + Vite frontend.
  - `api/`: Python Flask + Socket.IO backend.
  - The backend talks to four USB cameras, OpenCV, serial ESP32 hardware, calibration files, and uploaded Python mission scripts.
- `sender_esp32/` and `receiver_esp32/`: ESP32 firmware.
- `3d_files/`: mechanical model files.

The important deployment point is that this system must run on the user's local computer because it needs direct access to USB cameras and serial ports. AWS should host the downloadable packages, not run the drone-control software itself.

## Recommended Architecture

Use a browser-based local application flow:

- React/Vite: builds the frontend into static files.
- Flask: serves both the API and the built React frontend locally.
- PyInstaller: bundles the Python backend, React build output, calibration files, and Python libraries into a native executable.
- AWS S3: stores release files.
- AWS CloudFront: serves fast public download links.
- GitHub Actions: builds and uploads new downloadable packages when code is pushed to `main`.

Expected downloadable outputs:

- Windows: `DroneSwarm-Windows-x64.exe`
- Ubuntu simple package: `DroneSwarm-Ubuntu-x64.tar.gz`
- Optional Ubuntu desktop package: `DroneSwarm-Ubuntu-x64.AppImage`
- Optional Ubuntu installer package: `DroneSwarm-Ubuntu-x64.deb`

Electron is not required if it is acceptable for the UI to open in the user's normal browser.

## Installed App Runtime Flow

When the user double-clicks or runs the downloaded application:

1. The bundled Python executable starts.
2. The backend starts locally on `127.0.0.1:<port>`.
3. Flask serves the built React frontend.
4. The executable opens the user's default browser at `http://127.0.0.1:<port>`.
5. React connects to the same local backend using Socket.IO.
6. The backend accesses local USB cameras, serial ports, calibration files, and mission upload files.

The backend should bind to `127.0.0.1` in production, not `0.0.0.0`, because it is intended to serve only the local browser UI.

The user should not need Python, Node.js, npm, or Python libraries installed. The downloadable package should include the built frontend, the Python runtime bundle, and required Python dependencies.

## Code Changes Needed Before Packaging

### 1. Make Flask Serve The React Build

Build the React frontend:

```bash
npm run build
```

Vite will generate:

```text
computer_code/dist/
```

Update the Flask app so it serves this directory:

```python
app = Flask(
    __name__,
    static_folder="../dist",
    static_url_path="",
)

@app.route("/")
def serve_index():
    return app.send_static_file("index.html")

@app.errorhandler(404)
def spa_fallback(_):
    return app.send_static_file("index.html")
```

The exact paths must be adjusted so they work both in development and after PyInstaller bundling.

### 2. Open The Browser Automatically

On startup, open the local UI in the user's default browser:

```python
import webbrowser

webbrowser.open(f"http://127.0.0.1:{PORT}")
```

Start the browser after the local server is ready.

### 3. Make Frontend Backend URL Configurable

The frontend currently uses hardcoded local backend URLs such as:

```text
http://localhost:3001
```

These should be changed to same-origin URLs, for example:

```ts
const API_BASE_URL = window.location.origin;
```

The same approach should be used for:

- Socket.IO connection.
- Camera stream endpoint.
- Any future HTTP API calls.

If Flask serves the React frontend and Socket.IO API from the same origin, the app can avoid hardcoded `localhost` URLs.

### 4. Add PyInstaller Build

Add a PyInstaller configuration for:

```text
computer_code/api/index.py
```

It must include:

- `dist/*`
- `api/calibration/*`
- `api/fleet.json`
- Python files in `api/`
- OpenCV, NumPy, SciPy, Flask, Flask-SocketIO, Flask-CORS, and PySerial dependencies.

Build the Python backend separately on each target OS. PyInstaller should build Windows executables on Windows and Linux executables on Linux.

### 5. Move Writable Runtime Files

Do not write user-modified files inside the installed application directory.

Move these to a user data directory:

- `fleet.json`
- `uploads/`
- logs
- future settings files

Suggested locations:

- Windows: `%APPDATA%/DroneSwarm`
- Ubuntu: `~/.config/DroneSwarm`

### 6. Fix Platform-Specific Camera Handling

The tracker currently uses:

```python
cv.VideoCapture(self.src, cv.CAP_DSHOW)
```

`cv.CAP_DSHOW` is Windows-specific. For Ubuntu, use either:

```python
cv.VideoCapture(self.src, cv.CAP_V4L2)
```

or OpenCV's default backend.

Recommended approach:

- Windows: use `cv.CAP_DSHOW`
- Ubuntu: use `cv.CAP_V4L2`
- fallback: use default `cv.VideoCapture(self.src)`

### 7. Make Serial Port Configurable

The backend currently reads `SENDER_SERIAL_PORT` from the environment.

Keep that behavior, but also expose serial port configuration in the UI or a config file.

Typical defaults:

- Windows: `COM10`, `COM5`, etc.
- Ubuntu: `/dev/ttyUSB0` or `/dev/ttyACM0`

Ubuntu users may also need serial permissions:

```bash
sudo usermod -a -G dialout $USER
```

The user must log out and log back in after this command.

## AWS Hosting Plan

Use one private or public S3 bucket for release artifacts:

```text
s3://drone-swarm-downloads/
  releases/
    v1.0.0/
      DroneSwarm-Windows-x64.exe
      DroneSwarm-Ubuntu-x64.tar.gz
      DroneSwarm-Ubuntu-x64.AppImage
      DroneSwarm-Ubuntu-x64.deb
      checksums.txt
  latest/
    DroneSwarm-Windows-x64.exe
    DroneSwarm-Ubuntu-x64.tar.gz
    DroneSwarm-Ubuntu-x64.AppImage
    DroneSwarm-Ubuntu-x64.deb
    version.json
```

Put CloudFront in front of the S3 bucket.

Example public download links:

```text
https://downloads.example.com/latest/DroneSwarm-Windows-x64.exe
https://downloads.example.com/latest/DroneSwarm-Ubuntu-x64.tar.gz
https://downloads.example.com/latest/DroneSwarm-Ubuntu-x64.AppImage
https://downloads.example.com/latest/DroneSwarm-Ubuntu-x64.deb
```

If downloads should be private, use one of these:

- CloudFront signed URLs for controlled CDN downloads.
- S3 presigned URLs for temporary direct object access.

## GitHub Actions CI/CD Plan

Create:

```text
.github/workflows/release.yml
```

The workflow should run on every push to `main`.

High-level CI steps:

1. Build Windows app on `windows-latest`.
2. Build Ubuntu app on `ubuntu-22.04` or `ubuntu-24.04`.
3. Install Node dependencies.
4. Build React frontend.
5. Install Python dependencies.
6. Build bundled Python executable with PyInstaller.
7. Package Windows output as `.exe`.
8. Package Ubuntu output as `.tar.gz`, and optionally `.AppImage` or `.deb`.
9. Upload artifacts to S3 under `latest/`.
10. If the commit has a tag such as `v1.0.0`, also upload artifacts under `releases/v1.0.0/`.
11. Invalidate CloudFront cache for `latest/*`.

Recommended release behavior:

- Push to `main`: updates the `latest/` download files.
- Git tag such as `v1.0.0`: creates a permanent versioned release.

## Required GitHub Secrets

Store these in GitHub repository secrets:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_REGION
AWS_S3_BUCKET
AWS_CLOUDFRONT_DISTRIBUTION_ID
```

Better long-term option:

- Use GitHub OIDC with an AWS IAM role instead of long-lived AWS access keys.

## AWS IAM Permissions Needed By CI

The GitHub Actions deploy role or user needs permissions for:

- Uploading objects to the release S3 bucket.
- Reading/listing the release S3 bucket if needed.
- Creating CloudFront invalidations.

Minimum AWS services involved:

- S3
- CloudFront
- IAM
- Optional Route 53 if using a custom domain such as `downloads.example.com`
- Optional ACM certificate for HTTPS on the custom CloudFront domain

## Security And Production Notes

- Windows packages should eventually be code-signed to reduce Microsoft SmartScreen warnings.
- Ubuntu `.deb` is useful if the app needs desktop shortcuts, udev rules, or system integration.
- Ubuntu `.AppImage` is easier for simple double-click distribution.
- Ubuntu `.tar.gz` is simplest to build first, but the user may need to run a shell script or mark the executable as runnable.
- The uploaded mission-script feature executes Python code. Only trusted users should use it unless sandboxing is added later.
- Keep the backend local-only in production.
- Do not put AWS credentials inside the app.
- Do not put drone secrets or private calibration data in public release artifacts unless intended.

## Best Implementation Order

1. Make the backend production-safe:
   - bind to `127.0.0.1`
   - support configurable port
   - support platform-specific camera backend
   - move writable files to user data directory
2. Make Flask serve the built React frontend from `dist/`.
3. Change frontend URLs to same-origin URLs.
4. Add browser auto-open on backend startup.
5. Add PyInstaller backend build.
6. Test local Windows and Ubuntu builds manually.
7. Add GitHub Actions build matrix.
8. Add AWS S3 upload.
9. Add CloudFront distribution and cache invalidation.
10. Add versioned releases.
11. Add `.AppImage`, `.deb`, or code signing when ready for public users.

## Final User Experience

The final user experience should be:

1. User visits a download page or receives a download link.
2. User clicks the Windows or Ubuntu download button.
3. Package downloads from CloudFront.
4. User installs or extracts the app, depending on package type.
5. User double-clicks Drone Swarm.
6. The local backend starts automatically.
7. The user's default browser opens automatically.
8. The UI connects to the local backend automatically.
9. User configures camera and serial settings if needed.
10. User runs the drone-control system locally.


cd Drone-swarm-v1/computer_code
pip install -r api/requirements.txt -r api/requirements-build.txt
npm install && npm run build
pyinstaller api/droneswarm.spec --noconfirm --distpath dist_exe
./dist_exe/DroneSwarm.exe      # plug in your cameras + ESP32 first