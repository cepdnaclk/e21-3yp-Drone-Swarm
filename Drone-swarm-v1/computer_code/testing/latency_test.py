"""
Measure backend -> sender ESP32 serial latency/timing.

The production sender firmware accepts:
    S,x,y,z,vx,vy,vz,yaw_sp,x_sp,y_sp,z_sp,armed\n

Important limitation:
    The current sender_esp32.ino does not acknowledge S packets over USB serial.
    Without an ACK from the ESP32, the PC can measure write time and send-period
    jitter, but it cannot directly measure true one-way PC -> ESP32 parse latency.

Modes:
    write  - send realistic S packets and report serial write duration/jitter.
    ack    - send L,<seq>,<pc_ns> probe lines and wait for an echo/ACK line.

ACK mode expects test firmware on the sender ESP32 to reply with either:
    A,<seq>
    A,<seq>,<esp_us>
    L,<seq>,<pc_ns>

Example:
    python latency_test.py --port COM6 --baud 115200 --mode write --hz 60 --samples 600
    python latency_test.py --port COM6 --baud 115200 --mode ack --samples 200
"""

from __future__ import annotations

import argparse
import statistics
import time
from dataclasses import dataclass

import serial


@dataclass
class Stats:
    count: int
    minimum_ms: float
    mean_ms: float
    median_ms: float
    p95_ms: float
    maximum_ms: float


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * q))
    return ordered[index]


def summarize(values_ms: list[float]) -> Stats:
    if not values_ms:
        return Stats(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return Stats(
        count=len(values_ms),
        minimum_ms=min(values_ms),
        mean_ms=statistics.fmean(values_ms),
        median_ms=statistics.median(values_ms),
        p95_ms=percentile(values_ms, 0.95),
        maximum_ms=max(values_ms),
    )


def print_stats(title: str, values_ms: list[float]) -> None:
    s = summarize(values_ms)
    print(f"\n{title}")
    print(f"  samples : {s.count}")
    print(f"  min     : {s.minimum_ms:.3f} ms")
    print(f"  mean    : {s.mean_ms:.3f} ms")
    print(f"  median  : {s.median_ms:.3f} ms")
    print(f"  p95     : {s.p95_ms:.3f} ms")
    print(f"  max     : {s.maximum_ms:.3f} ms")


def state_line(seq: int) -> bytes:
    # Keep the exact production S-line format. seq is encoded in x at tiny scale
    # only to make logic-analyzer captures easy to correlate if needed.
    x = (seq % 10000) / 1_000_000.0
    return (
        f"S,{x:.4f},0.0000,0.0000,"
        "0.0000,0.0000,0.0000,"
        "0.0000,"
        "0.0000,0.0000,0.0000,"
        "0\n"
    ).encode("ascii")


def open_serial(port: str, baud: int, timeout: float) -> serial.Serial:
    ser = serial.Serial(port, baud, timeout=timeout, write_timeout=timeout)
    time.sleep(2.0)  # ESP32 often resets when the serial port opens.
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def run_write_mode(args: argparse.Namespace) -> None:
    period = 1.0 / args.hz
    write_ms: list[float] = []
    interval_ms: list[float] = []
    late_ms: list[float] = []

    with open_serial(args.port, args.baud, args.timeout) as ser:
        print(f"Opened {args.port} @ {args.baud}")
        print(f"Sending {args.samples} S packets at {args.hz:.2f} Hz")

        next_send = time.perf_counter()
        last_send_started: float | None = None

        for seq in range(args.samples):
            now = time.perf_counter()
            if now < next_send:
                time.sleep(next_send - now)

            send_started = time.perf_counter()
            if last_send_started is not None:
                interval_ms.append((send_started - last_send_started) * 1000.0)
            late_ms.append(max(0.0, send_started - next_send) * 1000.0)

            t0 = time.perf_counter_ns()
            ser.write(state_line(seq))
            ser.flush()
            t1 = time.perf_counter_ns()
            write_ms.append((t1 - t0) / 1_000_000.0)

            last_send_started = send_started
            next_send += period

    print_stats("Serial write duration", write_ms)
    print_stats("Actual send interval", interval_ms)
    print_stats("Scheduler lateness", late_ms)
    print(
        "\nNote: this is PC -> USB serial write timing. True ESP32 parse or "
        "ESP-NOW latency needs ACK firmware or receiver-side timestamping."
    )


def parse_ack(line: str) -> int | None:
    if not line:
        return None
    parts = line.strip().split(",")
    if len(parts) < 2 or parts[0] not in {"A", "L"}:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def run_ack_mode(args: argparse.Namespace) -> None:
    rtt_ms: list[float] = []
    lost = 0

    with open_serial(args.port, args.baud, args.timeout) as ser:
        print(f"Opened {args.port} @ {args.baud}")
        print(f"Sending {args.samples} latency probes; waiting for ACK/echo")

        for seq in range(args.samples):
            pc_ns = time.perf_counter_ns()
            ser.write(f"L,{seq},{pc_ns}\n".encode("ascii"))
            ser.flush()

            deadline = time.perf_counter() + args.timeout
            matched = False
            while time.perf_counter() < deadline:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="ignore").strip()
                ack_seq = parse_ack(line)
                if ack_seq == seq:
                    rtt_ms.append((time.perf_counter_ns() - pc_ns) / 1_000_000.0)
                    matched = True
                    break

            if not matched:
                lost += 1

            if args.delay_ms > 0:
                time.sleep(args.delay_ms / 1000.0)

    print_stats("Serial round-trip latency", rtt_ms)
    if rtt_ms:
        one_way = [v / 2.0 for v in rtt_ms]
        print_stats("Estimated one-way latency", one_way)
    print(f"\nLost/unmatched probes: {lost}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backend to sender ESP32 latency test")
    parser.add_argument("--port", default="COM6", help="Sender ESP32 serial port")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--mode", choices=["write", "ack"], default="write")
    parser.add_argument("--samples", type=int, default=600)
    parser.add_argument("--hz", type=float, default=60.0, help="S packet rate for write mode")
    parser.add_argument("--timeout", type=float, default=0.2, help="Serial read/write timeout")
    parser.add_argument("--delay-ms", type=float, default=5.0, help="Delay between ACK probes")
    args = parser.parse_args()

    if args.mode == "write":
        run_write_mode(args)
    else:
        run_ack_mode(args)


if __name__ == "__main__":
    main()
