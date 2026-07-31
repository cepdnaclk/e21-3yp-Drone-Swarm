---
layout: home
permalink: index.html

repository-name: e21-drone-swarm-testbed
title: The Mocap
---

# Programmable Indoor Drone Swarm Testbed

---

## Team
-  E/21/217, Ishan, [e21217@eng.pdn.ac.lk](mailto:name@email.com)
-  E/21/180, Siyumi, [e21180@eng.pdn.ac.lk](mailto:name@email.com)
-  E/21/009, Lisitha, [e21009@eng.pdn.ac.lk](mailto:name@email.com)
-  E/21/156, Thinula, [e21156@eng.pdn.ac.lk](mailto:name@email.com)

<!-- Add final system image here -->
<!-- ![System](./images/system.png) -->


## Table of Contents

1. [Introduction](#introduction)
2. [Problem](#problem)
3. [Our Solution](#our-solution)
4. [Solution Architecture](#solution-architecture)
5. [Hardware and Software Design](#hardware-and-software-design)
6. [Key Features](#key-features)
7. [Testing](#testing)
8. [Budget](#budget)
9. [Conclusion](#conclusion)
10. [Links](#links)

---

## Introduction

Drone swarms have significant potential in applications such as search and rescue, environmental monitoring, warehouse automation, surveillance, and entertainment.

However, developing and testing drone swarm algorithms using real drones can be expensive, complicated, and time-consuming. Indoor experiments are especially challenging because GPS cannot provide reliable positioning inside buildings.

This project develops a low-cost **Indoor Programmable Drone Swarm Testbed** that provides researchers and students with an integrated environment for programming, controlling, tracking, and testing multiple small drones.

---

## Problem

Researchers often need to configure several independent systems before testing a drone swarm, including:

- Drone hardware and flight controllers
- Communication systems
- Control algorithms
- Indoor localization systems
- Experiment monitoring and data collection
- Software interfaces for programming each drone

These separate configurations increase the complexity, cost, and time required to perform real-world experiments.

Simulation environments are useful during early development, but they cannot fully represent physical effects such as sensor noise, communication delays, control errors, battery variations, and real drone behaviour.

---

## Our Solution

Our system provides a complete programmable indoor drone swarm platform designed to make researchers’ lives easier.

Through the software interface, users can:

- Select individual drones
- Upload custom algorithms
- Use a predefined set of control functions
- Execute commands through an interactive console
- Observe the behaviour of real drones
- Monitor the real-time 3D position of each drone
- Configure and manage experiments from a central system

This allows researchers to spend less time configuring separate systems and more time developing, testing, and improving swarm algorithms.

---

## Solution Architecture

The system consists of three main components:

### 1. Programmable Drone Platform

Multiple small indoor drones receive commands from the central computer through a wireless communication network.

Each drone contains:

- A flight controller
- Wireless communication hardware
- Brushed motors and propellers
- An illuminated tracking marker
- Onboard control and communication software

### 2. Camera-Based Indoor Localization

Four cameras are positioned around the flight area to track the illuminated marker attached to each drone.

The localization system:

1. Captures the marker from multiple camera views
2. Detects its image coordinates
3. Uses calibrated camera parameters
4. Applies triangulation
5. Calculates the real-world X, Y, and Z position

This provides real-time indoor localization without relying on GPS.

### 3. Central Software Platform

The central computer connects the user interface, communication system, localization system, and drone controller.

It is responsible for:

- Uploading user algorithms
- Providing predefined control functions
- Executing user commands
- Sending commands to selected drones
- Receiving localization data
- Displaying console output
- Monitoring experiments
- Visualizing drone movement

---

## Hardware and Software Design

### Hardware

- Mini indoor drones
- Flight controllers
- ESP32-based wireless communication modules
- Four USB cameras
- Illuminated tracking markers
- Central processing computer
- Power and battery systems
- Indoor experimental flight area

### Software

- User programming interface
- Interactive command console
- Camera capture and calibration modules
- Marker detection and tracking
- Multi-camera triangulation
- Real-time 3D localization
- Drone communication module
- Feedback control system
- Experiment monitoring and visualization
- Safety and command validation functions

---

## Key Features

- Low-cost indoor drone swarm platform
- User-programmable drone behaviour
- Individual drone selection and control
- Custom algorithm uploading
- Predefined control functions
- Interactive command console
- Real-world drone testing
- Four-camera localization
- Real-time 3D position tracking
- GPS-independent indoor operation
- Centralized experiment monitoring
- Suitable for education and research

---

## Testing

The system is evaluated through several experimental stages:

### Localization Testing

- Camera calibration accuracy
- Marker detection reliability
- Multi-camera triangulation
- X, Y, and Z position accuracy
- Real-time tracking performance

### Communication Testing

- Command delivery reliability
- Communication delay
- Packet transmission rate
- Multi-drone communication performance

### Drone Control Testing

- Arming and disarming
- Motor response
- Takeoff and landing
- Hovering stability
- Position control
- Response to uploaded commands

### Platform Testing

- Drone selection
- Algorithm uploading
- Predefined function execution
- Console command execution
- Error handling
- Real-time visualization
- Complete end-to-end operation

---

## Budget

A detailed project budget, including drone components, flight controllers, communication modules, cameras, batteries, structural materials, and additional electronic components.
| Item                      | Quantity | Unit Cost (LKR) | Total Cost (LKR) |
| ------------------------- | -------: | --------------: | ---------------: |
| USB Cameras               |        4 |           1,800 |            7,200 |
| Drone + Flight Controller |        3 |           9,500 |           28,500 |
| ESP32 Base Station        |        1 |           3,000 |            3,000 |
| ESP32 (Drone - C3)        |        3 |             900 |            2,700 |
| USB Extension Cables      |        4 |           1,000 |            4,000 |
| Extra                     |        1 |           2,600 |            2,600 |
| **Total**         |          |                 |       **48,000** |


---

> **Making researchers’ lives easier—one swarm at a time.**

---

## Links

- **Project Repository:** [(https://github.com/cepdnaclk/e21-3yp-Drone-Swarm)]
- **Project Website:** [(https://cepdnaclk.github.io/e21-3yp-Drone-Swarm/)]
- **Documentation:** [(https://cepdnaclk.github.io/e21-3yp-Drone-Swarm/user-manual.html)]
