# Local Management Bridge

## Purpose

Connects a running controller to the PyXaseco Administrator Console on the same
computer. Exposes authenticated runtime status and supported management actions.
https://github.com/nilakite2/PyXaseco-Administrator-Console

## Commands

No chat commands. Register/select the instance in the Administrator Console;
normal in-game administration remains available independently.

## Configuration

Enable optional `app/management_bridge`. `app_defaults.toml` selects a numeric
loopback host (`127.0.0.1` or `::1`) and port; `port = 0` chooses a free local port
per instance. Requires the instance's management identity/token and compatible
runtime-lock entrypoint, prepared by the management registration/setup workflow.
Simply copying this app is not sufficient to register an older installation.

## Changes And Limits

- Uses the existing controller runtime, not a second gameplay process or GUI
  dependency in the core. Every instance keeps its own identity and configuration.
- Requests are authenticated, bounded and passed to controller-owned management
  handling rather than mutating gameplay state directly in HTTP handlers.
- Loopback-only: this is not an Internet-facing administration API. Do not proxy
  it publicly or share its private management credentials.
- Runtime connectivity and OS service registration are separate. A connected
  controller does not imply its dedicated server is installed as an OS service.
- Offline configuration editing is an explicit Console choice, not an automatic
  fallback when a running bridge is unavailable.

## Credits

Nila / PyXaseco project.
