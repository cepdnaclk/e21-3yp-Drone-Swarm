# Desktop build and AWS release

Drone Swarm runs on the operator's computer so it can access local cameras and
serial devices. AWS S3 and CloudFront only distribute the native release files.

## Runtime behavior

- Flask binds to `127.0.0.1:3001`, serves the built React app, and opens the
  default browser after the listener is ready.
- The frontend uses the current page origin for HTTP streams and Socket.IO.
- Writable files are kept in `%APPDATA%\DroneSwarm` on Windows and
  `~/.config/DroneSwarm` on Ubuntu.
- Set `DRONE_SWARM_DATA_DIR` to override the writable directory.
- Set `DRONE_BACKEND_PORT` to change the port.
- Set `DRONE_OPEN_BROWSER=false` to prevent automatic browser launch.
- Set `DRONE_CAMERA_BACKEND=dshow`, `v4l2`, or `default` to override automatic
  camera-backend selection.

## Build on Windows

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\Drone-swarm-v1\computer_code\scripts\build_windows.ps1
```

Output:

```text
Drone-swarm-v1/computer_code/release/DroneSwarm-Windows-x64.exe
```

## Build on Ubuntu

Install the OS packages required by Python, OpenCV, and Node first, then run:

```bash
chmod +x Drone-swarm-v1/computer_code/scripts/build_ubuntu.sh
./Drone-swarm-v1/computer_code/scripts/build_ubuntu.sh
```

Output:

```text
Drone-swarm-v1/computer_code/release/DroneSwarm-Ubuntu-x64.tar.gz
```

Ubuntu operators may need serial-device permission:

```bash
sudo usermod -a -G dialout "$USER"
```

Log out and back in before using the serial device.

## Configure automated publishing

The `.github/workflows/release.yml` workflow builds Windows and Ubuntu on pushes
to `main`, uploads both files to `latest/`, creates versioned files for `v*`
tags, and invalidates `/latest/*` in CloudFront.

Create these GitHub Actions repository secrets before running the workflow:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_REGION
AWS_S3_BUCKET
AWS_CLOUDFRONT_DISTRIBUTION_ID
```

The AWS identity needs `s3:PutObject` for the bucket and
`cloudfront:CreateInvalidation` for the distribution. Do not put these
credentials in the desktop application.
