# Extending the CLI

← Back to [Developer Guide](README.md)

The `dc29` CLI is built with [Typer](https://typer.tiangolo.com/). Entry point: `dc29/cli.py`, installed via the `dc29` script defined in `pyproject.toml`.

---

## Adding a Simple Command

```python
# dc29/cli.py
import typer
from dc29.protocol import ESCAPE, CMD_SET_EFFECT, EffectMode

app = typer.Typer(name="dc29", help="DC29 badge toolkit")

@app.command()
def breathe(
    port: str = typer.Option(..., "--port", "-p", help="Badge serial port"),
):
    """Set LED effect to breathe mode."""
    import serial
    with serial.Serial(port, 9600) as s:
        s.write(bytes([ESCAPE, CMD_SET_EFFECT, EffectMode.BREATHE]))
    typer.echo("Effect set to breathe")
```

Typer automatically generates:
- `dc29 breathe --help` documentation from the function signature and docstring
- Validation for typed arguments
- Shell completion (with `typer.completion install`)

---

## Adding a Command with Arguments

```python
@app.command()
def flash(
    port: str = typer.Option(..., "--port", "-p"),
    n: int = typer.Argument(help="LED number 1-4"),
    r: int = typer.Argument(help="Red 0-255"),
    g: int = typer.Argument(help="Green 0-255"),
    b: int = typer.Argument(help="Blue 0-255"),
):
    """Flash an LED with a specific color."""
    if not (1 <= n <= 4):
        typer.echo(f"LED must be 1-4, got {n}", err=True)
        raise typer.Exit(1)
    import serial
    with serial.Serial(port, 9600) as s:
        for _ in range(3):
            s.write(bytes([0x01, ord('L'), n, r, g, b]))
            import time; time.sleep(0.2)
            s.write(bytes([0x01, ord('L'), n, 0, 0, 0]))
            time.sleep(0.2)
    typer.echo(f"Flashed LED {n}")
```

---

## Adding a Command That Reads a Badge Reply

For commands that need to wait for a response from the badge (like `get-key`):

```python
@app.command()
def get_key(
    port: str = typer.Option(..., "--port", "-p"),
    button: int = typer.Argument(help="Button 1-4"),
    timeout: float = typer.Option(2.0, help="Reply timeout in seconds"),
):
    """Query a button's current keymap."""
    import serial
    from dc29.protocol import ESCAPE, CMD_QUERY_KEY, EVT_KEY_REPLY, modifier_name, keycode_name

    with serial.Serial(port, 9600, timeout=timeout) as s:
        # Send the query
        s.write(bytes([ESCAPE, CMD_QUERY_KEY, button]))

        # Parse the response using the state machine
        state = 0
        cmd = 0
        args = []
        start = __import__("time").time()

        while __import__("time").time() - start < timeout:
            data = s.read(1)
            if not data:
                continue
            b = data[0]
            if state == 0:
                if b == ESCAPE:
                    state = 1
            elif state == 1:
                cmd = b
                args = []
                state = 2
            elif state == 2:
                args.append(b)
                if cmd == EVT_KEY_REPLY and len(args) == 3:
                    n, mod, key = args
                    typer.echo(
                        f"Button {n}: {modifier_name(mod)}+{keycode_name(key, mod)}"
                        f"  (mod=0x{mod:02X} key=0x{key:02X})"
                    )
                    return
                    state = 0

        typer.echo("Timeout: no reply from badge", err=True)
        raise typer.Exit(1)
```

---

## Adding a Subgroup

Group related commands under a namespace:

```python
led_app = typer.Typer(name="led", help="LED control commands")
app.add_typer(led_app)

@led_app.command("set")
def led_set(
    port: str = typer.Option(..., "--port", "-p"),
    n: int = typer.Argument(),
    color: str = typer.Argument(help="Color name or r,g,b"),
):
    """Set an LED color."""
    from dc29.protocol import parse_color
    r, g, b = parse_color(color)
    import serial
    with serial.Serial(port, 9600) as s:
        s.write(bytes([0x01, ord('L'), n, r, g, b]))

@led_app.command("off")
def led_off(
    port: str = typer.Option(..., "--port", "-p"),
):
    """Turn off all LEDs."""
    import serial
    with serial.Serial(port, 9600) as s:
        for n in range(1, 5):
            s.write(bytes([0x01, ord('L'), n, 0, 0, 0]))
```

Users would call: `dc29 led set 1 red --port PORT`

---

## Sharing the Port Option

To avoid repeating `--port` on every command, you can use a Typer callback to set a global:

```python
from typing import Optional
import typer

app = typer.Typer()

# Module-level port storage (simple approach)
_port: Optional[str] = None

@app.callback()
def main(
    port: Optional[str] = typer.Option(None, "--port", "-p", envvar="DC29_PORT",
                                        help="Badge serial port. Can also set DC29_PORT env var."),
):
    """DC29 badge toolkit."""
    global _port
    _port = port

@app.command()
def info():
    """Show all keymaps."""
    if not _port:
        typer.echo("--port is required", err=True)
        raise typer.Exit(1)
    # use _port ...
```

Users can then set `export DC29_PORT=/dev/tty.usbmodem14201` and omit `--port` from every command.

---

## Output Formatting with Rich

The `rich` library is already a dependency. Use it for prettier output:

```python
from rich.console import Console
from rich.table import Table

@app.command()
def info(port: str = typer.Option(..., "--port", "-p")):
    """Show all keymaps."""
    from dc29.protocol import modifier_name, keycode_name
    from tools.teams_mute_indicator import BadgeWriter
    import time

    badge = BadgeWriter(port)
    results = {}

    def on_reply(n, mod, key):
        results[n] = (mod, key)

    # ... query all 4 buttons ...

    console = Console()
    table = Table(title="DC29 Button Keymaps")
    table.add_column("Button", style="cyan")
    table.add_column("Modifier")
    table.add_column("Key")
    table.add_column("Hex")

    for n in (1, 2, 3, 4):
        mod, key = results.get(n, (0, 0))
        table.add_row(
            str(n),
            modifier_name(mod),
            keycode_name(key, mod),
            f"mod=0x{mod:02X} key=0x{key:02X}",
        )

    console.print(table)
```

---

## Running Your Extension During Development

You don't need to reinstall the package every time. With `pip install -e .` (editable install), changes to `dc29/cli.py` are reflected immediately in the `dc29` command.

```bash
cd /path/to/Defcon29-mute-button
pip install -e .

# Your changes to dc29/cli.py are live:
dc29 my-new-command --port /dev/tty.usbmodem14201
```
