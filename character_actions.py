"""High-level requests for the seated action layer, independent of Tk and AI.

This is the first Action API boundary, not a second movement state machine.
SeatMotion remains the only timeline/priority owner. The host supplies its
current state; an interrupted action is discarded, never queued for replay.
No positions, amplitudes, velocities, resources or effects enter this API.
"""
from dataclasses import asdict, dataclass
import math

from seat_motion import ACTIONS

SOURCES = frozenset(('user', 'agent', 'demo'))
AGENT_ACTIONS = frozenset(('glance', 'nudge', 'startle', 'relief'))


@dataclass(frozen=True)
class ActionContext:
    movement: str
    on_swing: bool
    sleeping: bool = False
    reduced_motion: bool = False
    dragging: bool = False
    singing: bool = False


def blocked_reason(context):
    """The seated layer never wakes, moves or changes the host's main state."""
    if not isinstance(context, ActionContext):
        return 'invalid_context'
    for blocked, reason in ((context.sleeping, 'sleeping'),
                            (context.dragging, 'dragging'),
                            (context.reduced_motion, 'reduced_motion'),
                            (context.singing, 'singing')):
        if blocked:
            return reason
    if context.movement != 'swing':
        return 'not_seated'
    if not context.on_swing:
        return 'missing_scene'
    return None


def _valid_time(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (ValueError, OverflowError):
        return False


@dataclass(frozen=True)
class ActionResult:
    action: str | None
    source: str | None
    accepted: bool
    reason: str

    def __bool__(self):
        return self.accepted


class ActionSystem:
    """A small request/cancel boundary over the existing seated timeline."""

    def __init__(self, motion):
        self.motion = motion
        self.last_request = None
        self.last_cancel_reason = None

    def request(self, name, context, now, *, source='user', side=1):
        # Record only public vocabulary, never arbitrary input or model text.
        action = name if isinstance(name, str) and name in ACTIONS else None
        origin = source if isinstance(source, str) and source in SOURCES else None
        reason = None
        if action is None:
            reason = 'unknown_action'
        elif origin is None:
            reason = 'unknown_source'
        elif not _valid_time(now):
            reason = 'invalid_time'
        elif type(side) is not int or side not in (-1, 1):
            reason = 'invalid_side'
        elif origin == 'agent' and action not in AGENT_ACTIONS:
            reason = 'source_not_allowed'
        else:
            reason = blocked_reason(context)
        if reason is None and not self.motion.start(action, now, side):
            reason = 'priority'
        accepted = reason is None
        self.last_request = ActionResult(action, origin, accepted, reason or 'started')
        if accepted:
            self.last_cancel_reason = None
        return self.last_request

    def active(self, context, now):
        reason = blocked_reason(context) if _valid_time(now) else 'invalid_time'
        if reason:
            if self.motion.name is not None:
                self.motion.stop()
                self.last_cancel_reason = reason
            return None
        return self.motion.active(now)

    def snapshot(self, context, now):
        # Diagnostics never interrupt playback. The host's normal update owns
        # cancellation, including release of expression overlays it created.
        blocked = blocked_reason(context) or (None if _valid_time(now) else 'invalid_time')
        name = self.motion.name
        active = (name if not blocked and name in ACTIONS
                  and now - self.motion.born < ACTIONS[name]['dur'] else None)
        return {'state': 'blocked' if blocked else 'playing' if active else 'idle',
                'active': active,
                'last_request': asdict(self.last_request) if self.last_request is not None else None,
                'last_cancel_reason': self.last_cancel_reason}
