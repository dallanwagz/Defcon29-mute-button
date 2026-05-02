"""
dc29.scenes — Authorable LED scenes (static, keyframe-animated, or reactive).

A **scene** is a JSON/TOML-serializable description of what the badge's four
LEDs should do — either as a static snapshot, a looping keyframe animation,
or (future) a reactive callback driven by external input (audio, etc.).

This module is intentionally agent-friendly: the file format is human and
machine readable, the schema is small and stable, and there is exactly one
way to author each scene type.  An agent can write ``my-light-show.toml``,
run ``dc29 scene play my-light-show.toml``, see the result on the badge,
edit, and iterate.

File format
-----------

.. code-block:: toml

    # Required: the scene's display name.
    name = "Sunrise"

    # Optional: one-line description for the TUI scene grid.
    description = "Slow warm-to-yellow gradient over 3 seconds, looped."

    # Optional: brightness scalar 0.0..1.0, applied to every color.
    brightness = 1.0

    # --- One of: static OR keyframes OR mode ---

    # Static colors — set once and hold.
    [static]
    led1 = [255, 100, 0]
    led2 = [255, 150, 0]
    led3 = [255, 200, 50]
    led4 = [255, 230, 100]

    # Keyframe animation — the player interpolates between adjacent keyframes.
    [animation]
    interp = "linear"           # or "step" for hard cuts
    loop = true                 # loop forever, or play once and freeze on last frame
    fps = 60                    # render rate (capped to 60 by Throttle)

    [[animation.keyframes]]
    t = 0                       # ms from scene start
    leds = [[20, 0, 0], [20, 0, 0], [20, 0, 0], [20, 0, 0]]

    [[animation.keyframes]]
    t = 1500
    leds = [[255, 100, 0], [255, 150, 0], [255, 200, 50], [255, 230, 100]]

    [[animation.keyframes]]
    t = 3000
    leds = [[255, 230, 100], [255, 230, 100], [255, 230, 100], [255, 230, 100]]

    # Firmware mode — point the badge at a built-in scene.  Cheapest option:
    # the firmware does the animation, the host just sends one byte.
    [firmware]
    mode = "rainbow-chase"      # one of: off, rainbow-chase, breathe, wipe,
                                #         twinkle, gradient, theater, cylon

Storage location
----------------

Scenes live under ``~/.config/dc29/scenes/<name>.toml`` by default — see
:data:`DEFAULT_SCENE_DIR`.  Pass an explicit path to :func:`load_scene` to
load from elsewhere.

Playing a scene
---------------

.. code-block:: python

    badge = BadgeAPI("/dev/tty.usbmodem14201")
    scene = load_scene("sunrise.toml")
    runner = SceneRunner(badge, scene)
    await runner.run()              # forever, or until cancelled
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from dc29.badge import BadgeAPI
from dc29.protocol import EFFECT_NAMES, EffectMode
from dc29.throttle import Throttle, fps_to_interval

# Python 3.11+ has tomllib in stdlib.  3.10 needs the tomli backport.
try:
    import tomllib as _tomllib
except ImportError:  # pragma: no cover — Python <3.11
    try:
        import tomli as _tomllib  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover
        _tomllib = None  # type: ignore[assignment]

# tomli-w for writing.  Optional — save_scene falls back to a hand-rolled
# emitter if tomli-w isn't installed (acceptable since we control the schema).
try:
    import tomli_w as _tomli_w  # type: ignore[import]
except ImportError:  # pragma: no cover
    _tomli_w = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# Default scene directory.  Created on first save_scene call.
DEFAULT_SCENE_DIR: Path = Path.home() / ".config" / "dc29" / "scenes"

# Cap render rate to a sensible ceiling.  Agents writing scenes can request
# any fps but the player throttles — we don't need to flood the serial bus.
MAX_FPS: float = 60.0

RGB = tuple[int, int, int]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class StaticPayload:
    """A 4-LED color snapshot, applied once and held."""

    led1: RGB
    led2: RGB
    led3: RGB
    led4: RGB

    def colors(self) -> tuple[RGB, RGB, RGB, RGB]:
        return (self.led1, self.led2, self.led3, self.led4)


@dataclass
class Keyframe:
    """One frame in a keyframe animation."""

    t: int
    """Time offset in milliseconds from the start of the scene."""

    leds: tuple[RGB, RGB, RGB, RGB]
    """Per-LED RGB triples at this moment."""


@dataclass
class AnimationPayload:
    """A list of keyframes plus interpolation behavior."""

    keyframes: list[Keyframe]
    interp: str = "linear"
    """``"linear"`` blends between adjacent keyframes; ``"step"`` holds the lower frame."""

    loop: bool = True
    """``True`` to repeat forever; ``False`` to play once and freeze on the last frame."""

    fps: float = 30.0
    """Target render rate.  Capped to :data:`MAX_FPS`."""

    def duration_ms(self) -> int:
        if not self.keyframes:
            return 0
        return self.keyframes[-1].t


@dataclass
class FirmwarePayload:
    """Point the badge at a built-in firmware effect mode."""

    mode: int
    """An :class:`~dc29.protocol.EffectMode` value (0 through 34 — see EFFECT_NAMES for the full list)."""


@dataclass
class Scene:
    """A complete scene — exactly one of :attr:`static`, :attr:`animation`,
    or :attr:`firmware` is non-None."""

    name: str
    description: str = ""
    brightness: float = 1.0
    static: Optional[StaticPayload] = None
    animation: Optional[AnimationPayload] = None
    firmware: Optional[FirmwarePayload] = None
    # Free-form metadata: source file path (set by load_scene), author tags, etc.
    metadata: dict = field(default_factory=dict)

    def kind(self) -> str:
        """Return ``"static"``, ``"animation"``, or ``"firmware"``."""
        if self.static is not None:
            return "static"
        if self.animation is not None:
            return "animation"
        if self.firmware is not None:
            return "firmware"
        return "empty"


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def _parse_rgb(value, *, where: str) -> RGB:
    if not (isinstance(value, (list, tuple)) and len(value) == 3):
        raise ValueError(f"{where}: expected 3-element [r, g, b] list, got {value!r}")
    r, g, b = (int(c) & 0xFF for c in value)
    return (r, g, b)


def _parse_rgb_quad(value, *, where: str) -> tuple[RGB, RGB, RGB, RGB]:
    if not (isinstance(value, (list, tuple)) and len(value) == 4):
        raise ValueError(f"{where}: expected 4 LED entries, got {value!r}")
    return tuple(_parse_rgb(v, where=f"{where}[{i}]") for i, v in enumerate(value))  # type: ignore[return-value]


def parse_scene(raw: dict, *, source: Optional[Path] = None) -> Scene:
    """Build a :class:`Scene` from a parsed TOML dict.

    Used by :func:`load_scene`; exposed so callers can validate scenes coming
    from non-file sources (e.g. agent-generated dicts before saving).
    """
    if not isinstance(raw, dict):
        raise ValueError(f"scene root must be a table; got {type(raw).__name__}")

    name = str(raw.get("name", "")).strip()
    if not name:
        raise ValueError("scene must have a non-empty 'name'")

    description = str(raw.get("description", ""))
    brightness = float(raw.get("brightness", 1.0))
    brightness = max(0.0, min(1.0, brightness))

    static = animation = firmware = None
    payload_count = 0

    if "static" in raw:
        s = raw["static"]
        static = StaticPayload(
            led1=_parse_rgb(s.get("led1", [0, 0, 0]), where="static.led1"),
            led2=_parse_rgb(s.get("led2", [0, 0, 0]), where="static.led2"),
            led3=_parse_rgb(s.get("led3", [0, 0, 0]), where="static.led3"),
            led4=_parse_rgb(s.get("led4", [0, 0, 0]), where="static.led4"),
        )
        payload_count += 1

    if "animation" in raw:
        a = raw["animation"]
        kfs_raw = a.get("keyframes", [])
        if not kfs_raw:
            raise ValueError("animation requires at least one keyframe")
        keyframes = [
            Keyframe(
                t=int(kf.get("t", 0)),
                leds=_parse_rgb_quad(kf.get("leds", []), where=f"keyframe[{i}].leds"),
            )
            for i, kf in enumerate(kfs_raw)
        ]
        keyframes.sort(key=lambda kf: kf.t)
        animation = AnimationPayload(
            keyframes=keyframes,
            interp=str(a.get("interp", "linear")).lower(),
            loop=bool(a.get("loop", True)),
            fps=min(MAX_FPS, max(1.0, float(a.get("fps", 30.0)))),
        )
        if animation.interp not in ("linear", "step"):
            raise ValueError(f"animation.interp must be 'linear' or 'step', got {animation.interp!r}")
        payload_count += 1

    if "firmware" in raw:
        f = raw["firmware"]
        mode_raw = f.get("mode", 0)
        if isinstance(mode_raw, str):
            rev = {v: k for k, v in EFFECT_NAMES.items()}
            if mode_raw.lower() not in rev:
                raise ValueError(
                    f"firmware.mode must be one of {sorted(rev)} or 0..{max(EFFECT_NAMES)}; "
                    f"got {mode_raw!r}"
                )
            mode_int = int(rev[mode_raw.lower()])
        else:
            mode_int = int(mode_raw)
            if mode_int not in EFFECT_NAMES:
                raise ValueError(f"firmware.mode {mode_int} is out of range")
        firmware = FirmwarePayload(mode=mode_int)
        payload_count += 1

    if payload_count == 0:
        raise ValueError("scene must define one of [static], [animation], or [firmware]")
    if payload_count > 1:
        raise ValueError("scene must define exactly one of [static], [animation], [firmware]")

    metadata: dict = {}
    if source is not None:
        metadata["source"] = str(source)

    return Scene(
        name=name,
        description=description,
        brightness=brightness,
        static=static,
        animation=animation,
        firmware=firmware,
        metadata=metadata,
    )


def load_scene(path: Union[str, Path]) -> Scene:
    """Load a scene from a TOML file.

    Args:
        path: File path.  Resolved relative to the current directory; if not
              found, also tried under :data:`DEFAULT_SCENE_DIR`.

    Raises:
        FileNotFoundError: the file (and the default-dir fallback) doesn't exist.
        ValueError:        the TOML is malformed or violates the schema.
    """
    if _tomllib is None:
        raise ImportError(
            "TOML support requires Python 3.11+ or `pip install tomli`."
        )

    p = Path(path)
    if not p.exists():
        candidate = DEFAULT_SCENE_DIR / p.name
        if candidate.exists():
            p = candidate
        else:
            raise FileNotFoundError(f"scene not found: {path} (also looked in {DEFAULT_SCENE_DIR})")

    with open(p, "rb") as fh:
        raw = _tomllib.load(fh)
    return parse_scene(raw, source=p)


def save_scene(scene: Scene, path: Optional[Union[str, Path]] = None) -> Path:
    """Save *scene* to a TOML file under :data:`DEFAULT_SCENE_DIR`.

    Args:
        scene: The scene to write.
        path:  Override the destination.  If omitted, writes to
               ``DEFAULT_SCENE_DIR / f"{scene.name}.toml"`` (slugified name).

    Returns:
        The path that was written.
    """
    if path is None:
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in scene.name).strip("-").lower()
        DEFAULT_SCENE_DIR.mkdir(parents=True, exist_ok=True)
        path = DEFAULT_SCENE_DIR / f"{slug or 'scene'}.toml"
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_render_scene_toml(scene), encoding="utf-8")
    return p


def _render_scene_toml(scene: Scene) -> str:
    """Hand-rolled TOML emitter — small enough that we don't need the tomli-w dep.

    Schema is fixed so we can be exact about formatting (lists not split, etc.).
    """
    out = []
    out.append(f'name = "{scene.name}"')
    if scene.description:
        out.append(f'description = "{scene.description}"')
    if abs(scene.brightness - 1.0) > 1e-6:
        out.append(f"brightness = {scene.brightness}")
    out.append("")

    if scene.static is not None:
        out.append("[static]")
        out.append(f"led1 = [{scene.static.led1[0]}, {scene.static.led1[1]}, {scene.static.led1[2]}]")
        out.append(f"led2 = [{scene.static.led2[0]}, {scene.static.led2[1]}, {scene.static.led2[2]}]")
        out.append(f"led3 = [{scene.static.led3[0]}, {scene.static.led3[1]}, {scene.static.led3[2]}]")
        out.append(f"led4 = [{scene.static.led4[0]}, {scene.static.led4[1]}, {scene.static.led4[2]}]")

    elif scene.animation is not None:
        out.append("[animation]")
        out.append(f'interp = "{scene.animation.interp}"')
        out.append(f"loop = {str(scene.animation.loop).lower()}")
        out.append(f"fps = {scene.animation.fps}")
        out.append("")
        for kf in scene.animation.keyframes:
            out.append("[[animation.keyframes]]")
            out.append(f"t = {kf.t}")
            led_strs = [f"[{r}, {g}, {b}]" for (r, g, b) in kf.leds]
            out.append(f"leds = [{', '.join(led_strs)}]")
            out.append("")

    elif scene.firmware is not None:
        out.append("[firmware]")
        name = EFFECT_NAMES.get(scene.firmware.mode, str(scene.firmware.mode))
        out.append(f'mode = "{name}"')

    return "\n".join(out).rstrip() + "\n"


def list_scenes(directory: Optional[Path] = None) -> list[Path]:
    """Return all ``*.toml`` files under :data:`DEFAULT_SCENE_DIR` (or *directory*)."""
    d = directory or DEFAULT_SCENE_DIR
    if not d.exists():
        return []
    return sorted(d.glob("*.toml"))


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _interp_keyframes(
    kfs: list[Keyframe], t_ms: int, *, interp: str
) -> tuple[RGB, RGB, RGB, RGB]:
    """Sample a list of keyframes at time *t_ms*.

    Assumes *kfs* is sorted by ``t`` and non-empty.  Times before the first or
    after the last clamp to the boundary frame.
    """
    if t_ms <= kfs[0].t:
        return kfs[0].leds
    if t_ms >= kfs[-1].t:
        return kfs[-1].leds

    # Linear scan — keyframe lists are short (rarely >32), no need for bisect.
    for i in range(1, len(kfs)):
        if t_ms < kfs[i].t:
            lo, hi = kfs[i - 1], kfs[i]
            if interp == "step":
                return lo.leds
            span = hi.t - lo.t
            frac = (t_ms - lo.t) / span if span > 0 else 0.0
            return tuple(  # type: ignore[return-value]
                (
                    _lerp(lo.leds[j][0], hi.leds[j][0], frac),
                    _lerp(lo.leds[j][1], hi.leds[j][1], frac),
                    _lerp(lo.leds[j][2], hi.leds[j][2], frac),
                )
                for j in range(4)
            )
    return kfs[-1].leds  # unreachable but keeps type-checker happy


class SceneRunner:
    """Plays a :class:`Scene` on a :class:`BadgeAPI` until cancelled.

    Usage::

        runner = SceneRunner(badge, scene)
        task = asyncio.create_task(runner.run())
        # ... cancel task to stop ...

    Static and firmware scenes return immediately after applying their state
    (the firmware then handles animation, or the static colors hold).
    Animation scenes loop forever (or once, if ``loop = false``) at the
    scene's requested fps, throttled to :data:`MAX_FPS`.

    ``brightness`` is applied multiplicatively to every emitted color.
    """

    def __init__(self, badge: BadgeAPI, scene: Scene) -> None:
        self._badge = badge
        self._scene = scene

    async def run(self) -> None:
        scene = self._scene
        scale = scene.brightness

        if scene.firmware is not None:
            self._badge.set_effect_mode(scene.firmware.mode)
            log.info(
                "Scene %r → firmware mode %d (%s)",
                scene.name, scene.firmware.mode,
                EFFECT_NAMES.get(scene.firmware.mode, "?"),
            )
            # Firmware animations run on the badge.  Just hold here so the
            # caller's task lifetime owns the effect.
            await asyncio.Event().wait()
            return

        if scene.static is not None:
            cs = scene.static.colors()
            scaled = tuple(_apply_brightness(c, scale) for c in cs)
            self._badge.set_all_leds(*scaled)  # type: ignore[arg-type]
            log.info("Scene %r → static colors %s", scene.name, scaled)
            # Hold the colors — caller cancels to stop.
            await asyncio.Event().wait()
            return

        if scene.animation is None:
            log.warning("Scene %r is empty; nothing to do", scene.name)
            return

        anim = scene.animation
        gate = Throttle(fps_to_interval(min(MAX_FPS, anim.fps)))
        loop_count = 0
        log.info(
            "Scene %r → animation: %d keyframes, %.1f fps, loop=%s",
            scene.name, len(anim.keyframes), anim.fps, anim.loop,
        )
        try:
            start = asyncio.get_event_loop().time()
            duration = anim.duration_ms() / 1000.0
            while True:
                t_ms = int((asyncio.get_event_loop().time() - start) * 1000)
                if t_ms >= anim.keyframes[-1].t:
                    if anim.loop:
                        loop_count += 1
                        start = asyncio.get_event_loop().time()
                        t_ms = 0
                    else:
                        # Apply final frame and hold.
                        cs = anim.keyframes[-1].leds
                        scaled = tuple(_apply_brightness(c, scale) for c in cs)
                        self._badge.set_all_leds(*scaled)  # type: ignore[arg-type]
                        await asyncio.Event().wait()
                        return

                if gate.allow():
                    cs = _interp_keyframes(anim.keyframes, t_ms, interp=anim.interp)
                    scaled = tuple(_apply_brightness(c, scale) for c in cs)
                    self._badge.set_all_leds(*scaled)  # type: ignore[arg-type]

                # Sleep for half the frame interval — the throttle is the
                # actual rate limiter; this keeps us from busy-looping.
                await asyncio.sleep(gate.min_interval / 2)
        except asyncio.CancelledError:
            log.info("Scene %r cancelled (looped %d time(s))", scene.name, loop_count)
            raise


def _apply_brightness(c: RGB, scale: float) -> RGB:
    if abs(scale - 1.0) < 1e-6:
        return c
    return (
        max(0, min(255, int(c[0] * scale))),
        max(0, min(255, int(c[1] * scale))),
        max(0, min(255, int(c[2] * scale))),
    )


# ---------------------------------------------------------------------------
# Convenience factories — agents and the TUI use these to build common scenes
# ---------------------------------------------------------------------------


def static_scene(name: str, c1: RGB, c2: RGB, c3: RGB, c4: RGB, *, description: str = "") -> Scene:
    """Build a static-colors scene without writing TOML."""
    return Scene(
        name=name,
        description=description,
        static=StaticPayload(led1=c1, led2=c2, led3=c3, led4=c4),
    )


def firmware_scene(name: str, mode: Union[int, EffectMode], *, description: str = "") -> Scene:
    """Build a firmware-mode scene from an :class:`EffectMode` value."""
    return Scene(
        name=name,
        description=description,
        firmware=FirmwarePayload(mode=int(mode)),
    )
