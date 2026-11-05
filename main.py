"""Cercle chromatique interactif pour comparer des parcours de quintes."""

from __future__ import annotations

import math
import sys
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from tkinter import ttk
from typing import Callable, Iterator


REFERENCE_HZ = 440.0
MAX_CYCLE_OCTAVES = 120
REFERENCE_PITCH_CLASS = 9
CHROMATIC_NOTES = ("Do", "Do#", "Ré", "Ré#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si")
DIATONIC_PITCH_CLASSES = (0, 2, 4, 5, 7, 9, 11)
PURE_FIFTHS_COLOR = "#c2410c"
EQUAL_FIFTHS_COLOR = "#075985"
EVENT_COLORS = {
    "unison": "#e0ad00",
    "multiple": "#f97316",
    "common_multiple": "#be123c",
    "octave": "#0891b2",
    "closest": "#16a34a",
    "widest": "#9333ea",
}
TRACE_SEPARATION_SCALE = 2.5


def copy_to_clipboard(content: str, root: tk.Tk) -> None:
    """Copies text to the system clipboard, independent of Tk's lifetime on Windows."""
    if sys.platform != "win32":
        root.clipboard_clear()
        root.clipboard_append(content)
        root.update()
        return

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p

    if not user32.OpenClipboard(None):
        raise ctypes.WinError(ctypes.get_last_error())

    memory_handle = None
    try:
        encoded_content = content.encode("utf-16-le") + b"\0\0"
        memory_handle = kernel32.GlobalAlloc(0x0002, len(encoded_content))
        if not memory_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        memory_pointer = kernel32.GlobalLock(memory_handle)
        if not memory_pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(memory_pointer, encoded_content, len(encoded_content))
        finally:
            kernel32.GlobalUnlock(memory_handle)

        if not user32.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        if not user32.SetClipboardData(13, memory_handle):
            raise ctypes.WinError(ctypes.get_last_error())
        memory_handle = None
    finally:
        if memory_handle:
            kernel32.GlobalFree(memory_handle)
        user32.CloseClipboard()


class Series(str, Enum):
    PURE_FIFTHS = "Quintes pures (ratio 3/2)"
    EQUAL_FIFTHS = "Quintes tempérées (ratio 2^(7/12))"
    DIATONIC = "Ordre diatonique"


CYCLE_COLORS = {
    Series.PURE_FIFTHS.value: PURE_FIFTHS_COLOR,
    Series.EQUAL_FIFTHS.value: EQUAL_FIFTHS_COLOR,
}


class LabelMode(str, Enum):
    HERTZ = "Hertzien (Hz)"
    TEMPERED = "Tempéré (degrés)"


@dataclass(frozen=True)
class MusicStep:
    pitch_class: int
    note: str
    frequency_hz: float
    fifth_position: int | None = None


@dataclass(frozen=True)
class CycleArrival:
    note: str
    octave_number: int
    frequency_hz: float
    folded_frequency_hz: float


@dataclass(frozen=True)
class CyclePoint:
    temperament: str
    starting_note: str
    starting_octave_number: int
    starting_frequency_hz: float
    step_number: int
    note: str
    octave_number: int
    frequency_hz: float
    log2_frequency: float

    @property
    def note_label(self) -> str:
        return format_fifth_note(
            self.starting_note,
            self.step_number,
            self.frequency_hz,
            self.starting_frequency_hz,
        )

    @property
    def written_octave_number(self) -> int:
        return fifth_note_components(
            self.starting_note,
            self.step_number,
            self.frequency_hz,
            self.starting_frequency_hz,
        )[1]

    @property
    def reference_octave_hz(self) -> float:
        octave_offset = self.log2_frequency - math.floor(self.log2_frequency)
        return REFERENCE_HZ * 2**octave_offset

    @property
    def path(self) -> str:
        return (
            f"{self.temperament}, {self.note_label} = quinte {self.step_number} "
            f"depuis {format_note_octave(self.starting_note, self.starting_octave_number)}"
        )


@dataclass(frozen=True)
class PointPair:
    first: CyclePoint
    second: CyclePoint
    distance_cents: float


@dataclass(frozen=True)
class CycleAnalysis:
    points: tuple[CyclePoint, ...]
    unisons: tuple[PointPair, ...]
    cross_temperament_unisons: tuple[PointPair, ...]
    corresponding_fifths: tuple[PointPair, ...]
    cross_temperament_octave_matches: tuple[PointPair, ...]
    cross_temperament_integer_multiples: tuple[PointPair, ...]
    integer_multiple_pairs: tuple[PointPair, ...]
    closest_non_unison: PointPair | None
    closest_cross_temperament: PointPair | None
    widest_pair: PointPair | None
    comparisons: int
    max_octaves: int


def octave_position_cents(point: CyclePoint) -> float:
    octave_start_log2 = math.log2(REFERENCE_HZ) + point.octave_number - 4 - REFERENCE_PITCH_CLASS / 12
    return min(1200.0, max(0.0, (point.log2_frequency - octave_start_log2) * 1200))


def integer_frequency_multiple(first_hz: float, second_hz: float) -> int | None:
    """Return the integer ratio when frequencies differ by a nontrivial multiple."""
    if not math.isfinite(first_hz) or not math.isfinite(second_hz) or min(first_hz, second_hz) <= 0:
        return None

    lower, higher = sorted((first_hz, second_hz))
    ratio = higher / lower
    if not math.isfinite(ratio) or ratio > 2**53:
        return None
    if math.ulp(ratio) > 1e-9:
        return None

    multiple = round(ratio)
    if multiple < 2:
        return None

    expected_higher = lower * multiple
    if not math.isfinite(expected_higher):
        return None
    tolerance = 2 * (math.ulp(higher) + math.ulp(expected_higher))
    return multiple if abs(higher - expected_higher) <= tolerance else None


def _project_globe_point(
    x: float,
    y: float,
    z: float,
    center: float | tuple[float, float],
    radius: float,
    yaw: float,
    pitch: float,
) -> tuple[float, float, float]:
    x_rotated = x * math.cos(yaw) + z * math.sin(yaw)
    z_rotated = -x * math.sin(yaw) + z * math.cos(yaw)
    screen_y = y * math.cos(pitch) + z_rotated * math.sin(pitch)
    depth = z_rotated * math.cos(pitch) - y * math.sin(pitch)
    center_x, center_y = center if isinstance(center, tuple) else (center, center)
    return center_x + radius * x_rotated, center_y + radius * screen_y, depth


def _globe_surface_coordinates(
    octave_fraction: float,
    chromatic_degree: float,
    center: float | tuple[float, float],
    radius: float,
    yaw: float,
    pitch: float,
) -> tuple[float, float, float]:
    longitude = 2 * math.pi * octave_fraction
    colatitude = math.pi * chromatic_degree / len(CHROMATIC_NOTES)
    return _project_globe_point(
        math.sin(colatitude) * math.cos(longitude),
        math.sin(colatitude) * math.sin(longitude),
        math.cos(colatitude),
        center,
        radius,
        yaw,
        pitch,
    )


def globe_coordinates(
    point: CyclePoint,
    center: float | tuple[float, float],
    radius: float,
    octave_min: int = 4,
    octave_max: int = 124,
    yaw: float = 0.0,
    pitch: float = -0.55,
) -> tuple[float, float, float]:
    """Project a note onto its cyclic octave longitude and chromatic cross-section."""
    pitch_index = CHROMATIC_NOTES.index(point.note)
    degree = (pitch_index - REFERENCE_PITCH_CLASS) % len(CHROMATIC_NOTES)
    longitude_count = max(1, octave_max - octave_min + 1)
    octave_index = (point.octave_number - octave_min) % longitude_count
    octave_fraction = octave_index / longitude_count
    return _globe_surface_coordinates(
        octave_fraction,
        degree,
        center,
        radius,
        yaw,
        pitch,
    )


def globe_trace_coordinates(
    start_point: CyclePoint,
    end_point: CyclePoint,
    center: float | tuple[float, float],
    radius: float,
    octave_min: int,
    octave_max: int,
    yaw: float = 0.0,
    pitch: float = -0.55,
    samples: int = 8,
) -> tuple[tuple[float, float, float], ...]:
    """Interpolate a fifth along the cyclic octave surface."""
    if samples < 1:
        raise ValueError("Le nombre d'échantillons doit être positif.")

    octave_span = max(1, octave_max - octave_min)
    longitude_count = octave_span + 1
    start_index = CHROMATIC_NOTES.index(start_point.note)
    end_index = CHROMATIC_NOTES.index(end_point.note)
    start_degree = (start_index - REFERENCE_PITCH_CLASS) % len(CHROMATIC_NOTES)
    end_degree = (end_index - REFERENCE_PITCH_CLASS) % len(CHROMATIC_NOTES)
    degree_delta = end_degree - start_degree
    start_longitude = (
        2
        * math.pi
        * ((start_point.octave_number - octave_min) % longitude_count)
        / longitude_count
    )
    longitude_delta = (
        2 * math.pi * (end_point.octave_number - start_point.octave_number)
        / longitude_count
    )
    coordinates = []

    for index in range(samples + 1):
        fraction = index / samples
        coordinates.append(
            _globe_surface_coordinates(
                (start_longitude + longitude_delta * fraction) / (2 * math.pi),
                start_degree + degree_delta * fraction,
                center,
                radius,
                yaw,
                pitch,
            )
        )

    return tuple(coordinates)


def horizontal_trace_coordinates(
    point: CyclePoint,
    octave_min: int,
    octave_width: float = 90,
    row_height: float = 42,
    left: float = 70,
    top: float = 44,
    octave_positions: dict[int, float] | None = None,
) -> tuple[float, float]:
    """Map a point to its octave column and frequency-real chromatic position."""
    degree = (CHROMATIC_NOTES.index(point.note) - REFERENCE_PITCH_CLASS) % len(CHROMATIC_NOTES)
    cents_from_la = 1200 * (point.log2_frequency - math.log2(REFERENCE_HZ))
    cents_from_note = (cents_from_la - degree * 100 + 600) % 1200 - 600
    return (
        (
            octave_positions[point.octave_number]
            if octave_positions is not None
            else left + (point.octave_number - octave_min) * octave_width
        ),
        top + degree * row_height + cents_from_note * row_height / 100,
    )


def compressed_octave_positions(
    octave_min: int,
    octave_max: int,
    event_octaves: set[int],
    left: float = 72,
    octave_width: float = 90,
    compressed_width: float = 11,
    context_octaves: int = 1,
) -> dict[int, float]:
    """Keep event neighborhoods expanded and compress the octave gaps between them."""
    if octave_max < octave_min:
        raise ValueError("L'octave maximale doit être supérieure ou égale à l'octave minimale.")

    expanded_intervals = {
        octave
        for event_octave in event_octaves
        for octave in range(event_octave - context_octaves, event_octave + context_octaves + 1)
        if octave_min <= octave < octave_max
    }
    positions = {octave_min: left}
    for octave in range(octave_min, octave_max):
        interval_width = octave_width if octave in expanded_intervals else compressed_width
        positions[octave + 1] = positions[octave] + interval_width
    return positions


def build_cycle_analysis(max_octaves: int = MAX_CYCLE_OCTAVES) -> CycleAnalysis:
    """Mémorise et compare les cycles purs et tempérés depuis la référence La4."""
    if not isinstance(max_octaves, int) or isinstance(max_octaves, bool):
        raise TypeError("La limite doit être un nombre entier d'octaves.")
    if not 0 < max_octaves <= MAX_CYCLE_OCTAVES:
        raise ValueError(
            f"La limite doit être comprise entre 1 et {MAX_CYCLE_OCTAVES} octaves."
        )

    temperaments = (
        (Series.PURE_FIFTHS.value, 3 / 2),
        (Series.EQUAL_FIFTHS.value, 2 ** (7 / 12)),
    )
    points: list[CyclePoint] = []
    unisons: list[PointPair] = []
    cross_temperament_unisons: list[PointPair] = []
    corresponding_fifths: list[PointPair] = []
    cross_temperament_octave_matches: list[PointPair] = []
    cross_temperament_integer_multiples: list[PointPair] = []
    integer_multiple_pairs: list[PointPair] = []
    closest_non_unison: PointPair | None = None
    closest_cross_temperament: PointPair | None = None
    widest_pair: PointPair | None = None
    comparisons = 0

    for temperament, fifth_ratio in temperaments:
        steps_per_cycle = math.floor(max_octaves / math.log2(fifth_ratio))
        for starting_pitch in (REFERENCE_PITCH_CLASS,):
            semitones_from_a = (starting_pitch - REFERENCE_PITCH_CLASS) % 12
            starting_frequency = REFERENCE_HZ * 2 ** (semitones_from_a / 12)
            starting_note = CHROMATIC_NOTES[starting_pitch]
            starting_octave_number = 4 + math.floor(
                math.log2(starting_frequency / REFERENCE_HZ) + REFERENCE_PITCH_CLASS / 12
            )

            for cycle_step_number in range(steps_per_cycle + 1):
                step_number = cycle_step_number
                pitch_class = (starting_pitch + cycle_step_number * 7) % 12
                frequency_hz = starting_frequency * fifth_ratio**cycle_step_number
                log2_frequency = math.log2(frequency_hz)
                # This octave is used by the chromatic chart; the written octave
                # is derived separately from the diatonic spelling.
                octave_number = 4 + math.floor(
                    log2_frequency - math.log2(REFERENCE_HZ) + REFERENCE_PITCH_CLASS / 12
                )
                point = CyclePoint(
                    temperament=temperament,
                    starting_note=starting_note,
                    starting_octave_number=starting_octave_number,
                    starting_frequency_hz=starting_frequency,
                    step_number=step_number,
                    note=CHROMATIC_NOTES[pitch_class],
                    octave_number=octave_number,
                    frequency_hz=frequency_hz,
                    log2_frequency=log2_frequency,
                )

                # Chaque nouveau point est comparé à tous les points déjà mémorisés.
                for previous in points:
                    distance_cents = abs(point.log2_frequency - previous.log2_frequency) * 1200
                    is_unison = point.frequency_hz == previous.frequency_hz
                    if not is_unison and distance_cents == 0:
                        lower_frequency = min(point.frequency_hz, previous.frequency_hz)
                        distance_cents = (
                            math.log1p(abs(point.frequency_hz - previous.frequency_hz) / lower_frequency)
                            * 1200
                            / math.log(2)
                        )
                    pair = PointPair(previous, point, distance_cents)
                    comparisons += 1
                    is_cross_temperament = previous.temperament != point.temperament
                    is_corresponding_fifth = (
                        is_cross_temperament and previous.step_number == point.step_number
                    )
                    if is_corresponding_fifth:
                        corresponding_fifths.append(pair)
                    if is_unison:
                        unisons.append(pair)
                        if is_cross_temperament:
                            cross_temperament_unisons.append(pair)
                    else:
                        if closest_non_unison is None or distance_cents < closest_non_unison.distance_cents:
                            closest_non_unison = pair
                        multiple = integer_frequency_multiple(
                            point.frequency_hz,
                            previous.frequency_hz,
                        )
                        if multiple is not None:
                            integer_multiple_pairs.append(pair)
                            if is_cross_temperament:
                                cross_temperament_integer_multiples.append(pair)
                        if is_cross_temperament:
                            octave_shift = round(point.log2_frequency - previous.log2_frequency)
                            if (
                                octave_shift != 0
                                and abs(
                                    point.log2_frequency - previous.log2_frequency - octave_shift
                                )
                                <= 1e-12
                            ):
                                cross_temperament_octave_matches.append(pair)
                    if (
                        is_corresponding_fifth
                        and not is_unison
                        and (
                            closest_cross_temperament is None
                            or distance_cents < closest_cross_temperament.distance_cents
                        )
                    ):
                        closest_cross_temperament = pair
                    if (
                        is_corresponding_fifth
                        and (
                            widest_pair is None
                            or distance_cents > widest_pair.distance_cents
                        )
                    ):
                        widest_pair = pair

                points.append(point)

    return CycleAnalysis(
        points=tuple(points),
        unisons=tuple(unisons),
        cross_temperament_unisons=tuple(cross_temperament_unisons),
        corresponding_fifths=tuple(corresponding_fifths),
        cross_temperament_octave_matches=tuple(cross_temperament_octave_matches),
        cross_temperament_integer_multiples=tuple(cross_temperament_integer_multiples),
        integer_multiple_pairs=tuple(integer_multiple_pairs),
        closest_non_unison=closest_non_unison,
        closest_cross_temperament=closest_cross_temperament,
        widest_pair=widest_pair,
        comparisons=comparisons,
        max_octaves=max_octaves,
    )


def build_sequence(series: Series, reference_hz: float = REFERENCE_HZ) -> tuple[MusicStep, ...]:
    """Construit une séquence depuis La4 en conservant les fréquences réelles des quintes."""
    if not math.isfinite(reference_hz) or reference_hz <= 0:
        raise ValueError("La fréquence de référence doit être un nombre positif et fini.")

    if series is Series.PURE_FIFTHS:
        steps: list[MusicStep] = []
        frequency = reference_hz
        for index in range(12):
            pitch_class = (REFERENCE_PITCH_CLASS + index * 7) % 12
            steps.append(MusicStep(pitch_class, CHROMATIC_NOTES[pitch_class], frequency, index))
            frequency *= 3 / 2
        return tuple(steps)

    if series is Series.EQUAL_FIFTHS:
        return tuple(
            MusicStep(
                (REFERENCE_PITCH_CLASS + index * 7) % 12,
                CHROMATIC_NOTES[(REFERENCE_PITCH_CLASS + index * 7) % 12],
                reference_hz * (2 ** (7 / 12)) ** index,
                index,
            )
            for index in range(12)
        )

    # Parcourt les notes diatoniques à partir de La (La, Si, Do, Ré, Mi, Fa, Sol).
    pitch_classes = tuple(
        sorted(DIATONIC_PITCH_CLASSES, key=lambda pitch_class: (pitch_class - REFERENCE_PITCH_CLASS) % 12)
    )
    return tuple(
        MusicStep(
            pitch_class,
            CHROMATIC_NOTES[pitch_class],
            reference_hz * 2 ** (((pitch_class - REFERENCE_PITCH_CLASS) % 12) / 12),
        )
        for pitch_class in pitch_classes
    )


def format_note_label(step: MusicStep) -> str:
    """Formate une note avec l'altération avant le nom et son octave réelle."""
    if step.fifth_position is not None:
        return format_fifth_note("La", step.fifth_position, step.frequency_hz)

    octave_number = 4 + math.floor(
        math.log2(step.frequency_hz / REFERENCE_HZ) + REFERENCE_PITCH_CLASS / 12
    )
    return format_note_octave(step.note, octave_number)


def format_accidentals(accidental_count: int) -> str:
    """Encode a signed accidental count in the compact notation."""
    count = abs(accidental_count)
    remainder, triples = count % 3, count // 3
    if accidental_count > 0:
        return ("+" if remainder == 1 else "x" if remainder == 2 else "") + "^" * triples
    if accidental_count < 0:
        return ("-" if remainder == 1 else "o" if remainder == 2 else "") + "*" * triples
    return ""


def fifth_note_components(
    starting_note: str,
    step_number: int,
    frequency_hz: float,
    starting_frequency_hz: float = REFERENCE_HZ,
) -> tuple[str, int]:
    """Return the diatonic spelling and octave reached by a fifth-chain step."""
    letters = ("Do", "Ré", "Mi", "Fa", "Sol", "La", "Si")
    natural_semitones_from_a = {
        "Do": -9,
        "Ré": -7,
        "Mi": -5,
        "Fa": -4,
        "Sol": -2,
        "La": 0,
        "Si": 2,
    }
    starting_letter = starting_note.partition("#")[0]
    starting_accidentals = starting_note.count("#")
    starting_octave = 4 + math.floor(
        math.log2(starting_frequency_hz / REFERENCE_HZ)
        - (natural_semitones_from_a[starting_letter] + starting_accidentals) / 12
    )
    starting_letter_index = letters.index(starting_letter)
    target_letter_position = starting_letter_index + 4 * step_number
    letter = letters[target_letter_position % len(letters)]
    octave = starting_octave + target_letter_position // len(letters)
    starting_natural_semitones = (
        12 * (starting_octave - 4) + natural_semitones_from_a[starting_letter]
    )
    target_semitones = starting_natural_semitones + starting_accidentals + 7 * step_number
    target_natural_semitones = 12 * (octave - 4) + natural_semitones_from_a[letter]
    accidentals = target_semitones - target_natural_semitones
    note_semitones = natural_semitones_from_a[letter] + accidentals
    octave_number = 4 + math.floor(
        math.log2(frequency_hz / REFERENCE_HZ) - note_semitones / 12
    )
    return f"{format_accidentals(accidentals)}{letter.upper()}", octave_number


def format_fifth_note(
    starting_note: str,
    step_number: int,
    frequency_hz: float,
    starting_frequency_hz: float = REFERENCE_HZ,
) -> str:
    note, octave_number = fifth_note_components(
        starting_note,
        step_number,
        frequency_hz,
        starting_frequency_hz,
    )
    return f"{note}{octave_number}"


def format_note_octave(note_name: str, octave_number: int) -> str:
    note, has_sharp, _ = note_name.partition("#")
    return f"{'#' if has_sharp else ''}{note.upper()}{octave_number}"


def build_cycle_arrival(series: Series, reference_hz: float = REFERENCE_HZ) -> CycleArrival | None:
    """Returns the frequency reached by closing a fifth cycle from Ré back to La."""
    if not math.isfinite(reference_hz) or reference_hz <= 0:
        raise ValueError("La fréquence de référence doit être un nombre positif et fini.")
    if series is Series.DIATONIC:
        return None

    fifth_ratio = 3 / 2 if series is Series.PURE_FIFTHS else 2 ** (7 / 12)
    frequency = reference_hz * fifth_ratio**12
    octave_number = 4 + math.floor(
        math.log2(frequency / REFERENCE_HZ) + REFERENCE_PITCH_CLASS / 12
    )
    folded_frequency = frequency
    while folded_frequency >= reference_hz * 2:
        folded_frequency /= 2
    while folded_frequency < reference_hz:
        folded_frequency *= 2
    return CycleArrival("La", octave_number, frequency, folded_frequency)


def animated_sequence(method: Callable[..., Iterator[int]]) -> Callable[..., None]:
    """Anime une séquence Tkinter en annulant toute animation précédente."""

    @wraps(method)
    def wrapper(self: MusicCircleApp, *args: object, **kwargs: object) -> None:
        self.stop_animation()
        steps = iter(method(self, *args, **kwargs))

        def advance() -> None:
            self._after_id = None
            try:
                visible_steps = next(steps)
            except StopIteration:
                return
            self.draw_circle(visible_steps)
            self._after_id = self.root.after(self.animation_delay_ms, advance)

        advance()

    return wrapper


class MusicCircleApp:
    CANVAS_SIZE = 620
    CENTER = CANVAS_SIZE / 2
    RADIUS = 220

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Cercle des quintes")
        self.root.minsize(760, 760)
        self.animation_delay_ms = 500
        self._after_id: str | None = None
        self._analysis_after_id: str | None = None
        self._cycle_analysis: CycleAnalysis | None = None
        self._analysis_future: Future[CycleAnalysis] | None = None
        self._analysis_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cycle-analysis")
        self._analysis_window: tk.Toplevel | None = None
        self._analysis_status: tk.Label | None = None
        self.series_var = tk.StringVar(value=Series.PURE_FIFTHS.value)
        self.label_mode_var = tk.StringVar(value=LabelMode.HERTZ.value)

        controls = tk.Frame(root, padx=12, pady=10)
        controls.pack(fill="x")

        tk.Label(controls, text="Séquence :").pack(side="left")
        series_menu = tk.OptionMenu(
            controls,
            self.series_var,
            *(series.value for series in Series),
            command=self._selection_changed,
        )
        series_menu.pack(side="left", padx=(4, 14))

        for mode in LabelMode:
            tk.Radiobutton(
                controls,
                text=mode.value,
                value=mode.value,
                variable=self.label_mode_var,
                command=self._selection_changed,
            ).pack(side="left", padx=4)

        tk.Button(controls, text="Animer", command=self.start_animation).pack(side="left", padx=(14, 4))
        tk.Button(controls, text="Arrêter", command=self.stop_animation).pack(side="left", padx=4)
        tk.Button(controls, text="Analyser 120 octaves", command=self.show_cycle_analysis).pack(side="left", padx=4)

        self.canvas = tk.Canvas(
            root,
            width=self.CANVAS_SIZE,
            height=self.CANVAS_SIZE,
            background="#fcfbf7",
            highlightthickness=0,
        )
        self.canvas.pack(padx=12, pady=4)

        tk.Label(
            root,
            text=(
                "Référence : La4 = 440 Hz. Les 12 positions représentent les classes chromatiques ; "
                "les étiquettes conservent l'octave réelle du parcours."
            ),
            wraplength=740,
            justify="center",
            padx=12,
            pady=8,
        ).pack()
        self.cycle_arrival_label = tk.Label(
            root,
            text="",
            justify="center",
            wraplength=740,
            padx=12,
            pady=4,
        )
        self.cycle_arrival_label.pack()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.draw_circle()

    @property
    def selected_series(self) -> Series:
        return Series(self.series_var.get())

    def _selection_changed(self, *_: object) -> None:
        self.stop_animation()
        self.draw_circle()

    def stop_animation(self) -> None:
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None

    def close(self) -> None:
        self.stop_animation()
        if self._analysis_after_id is not None:
            self.root.after_cancel(self._analysis_after_id)
            self._analysis_after_id = None
        self._analysis_executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def show_cycle_analysis(self) -> None:
        if self._cycle_analysis is not None:
            self._show_analysis_report(self._cycle_analysis)
            return
        if self._analysis_future is not None:
            if self._analysis_window is not None and self._analysis_window.winfo_exists():
                self._analysis_window.lift()
            return

        self._analysis_window = tk.Toplevel(self.root)
        self._analysis_window.title("Mémoire des cycles — analyse")
        self._analysis_window.geometry("520x120")
        self._analysis_status = tk.Label(
            self._analysis_window,
            text="Calcul des cycles et comparaison de tous les points…",
            padx=16,
            pady=24,
        )
        self._analysis_status.pack(fill="both", expand=True)
        self._analysis_window.protocol("WM_DELETE_WINDOW", self._close_analysis_window)
        self._analysis_future = self._analysis_executor.submit(build_cycle_analysis)
        self._poll_cycle_analysis()

    def _close_analysis_window(self) -> None:
        if self._analysis_window is not None:
            self._analysis_window.destroy()
        self._analysis_window = None
        self._analysis_status = None

    def _poll_cycle_analysis(self) -> None:
        future = self._analysis_future
        if future is None:
            return
        if not future.done():
            self._analysis_after_id = self.root.after(100, self._poll_cycle_analysis)
            return

        self._analysis_after_id = None
        self._analysis_future = None
        error = future.exception()
        if error is not None:
            if self._analysis_status is not None:
                self._analysis_status.configure(
                    text=f"L'analyse a échoué ({type(error).__name__}) : {error}"
                )
            return

        self._cycle_analysis = future.result()
        if self._analysis_window is not None and self._analysis_window.winfo_exists():
            self._show_analysis_report(self._cycle_analysis, self._analysis_window)

    def _show_analysis_report(
        self,
        analysis: CycleAnalysis,
        report: tk.Toplevel | None = None,
    ) -> None:
        if report is None:
            report = tk.Toplevel(self.root)
            report.title("Mémoire des cycles — rapprochements")
            report.geometry("920x680")
        else:
            for child in report.winfo_children():
                child.destroy()

        report.title("Mémoire des cycles — rapprochements")
        report.geometry("920x680")
        self._analysis_window = report
        self._analysis_status = None

        text = tk.Text(report, wrap="word", padx=10, pady=10)
        scrollbar = tk.Scrollbar(report, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        report_controls = tk.Frame(report, padx=10, pady=8)
        copy_status = tk.Label(report_controls, anchor="w")
        copy_status.pack(side="left", fill="x", expand=True)

        def copy_report() -> None:
            try:
                content = text.get("sel.first", "sel.last")
                status = "Sélection copiée dans le presse-papiers."
            except tk.TclError:
                content = text.get("1.0", "end-1c")
                status = "Rapport complet copié dans le presse-papiers."
            try:
                copy_to_clipboard(content, self.root)
            except OSError as error:
                copy_status.configure(text=f"Échec de la copie : {error}")
                return
            copy_status.configure(text=status)

        tk.Button(
            report_controls,
            text="Copier la sélection / tout le rapport",
            command=copy_report,
        ).pack(side="right")
        tk.Button(
            report_controls,
            text="Carte des 120 octaves",
            command=lambda: self._show_cycle_map(analysis),
        ).pack(side="right", padx=(0, 8))
        report_controls.pack(side="bottom", fill="x")
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)

        text.insert(
            "end",
            (
                f"Référence : La4 = {REFERENCE_HZ:.2f} Hz\n"
                f"Étendue maximale par cycle : {analysis.max_octaves} octaves\n"
                f"Points mémorisés : {len(analysis.points):,}\n"
                f"Comparaisons effectuées : {analysis.comparisons:,}\n"
                "Chaque écart est calculé en cents à partir des fréquences réelles, "
                "sans rabattre les octaves.\n"
                "Unisson : égalité exacte des fréquences calculées en Hz ; "
                "0 cents signifie une différence de fréquence nulle.\n\n"
            ).replace(",", " "),
        )

        text.insert("end", f"Unissons détectés : {len(analysis.unisons):,}\n".replace(",", " "))
        text.insert(
            "end",
            (
                "Unissons entre les deux calibrages : "
                f"{len(analysis.cross_temperament_unisons):,}\n"
            ).replace(",", " "),
        )
        for pair in analysis.cross_temperament_unisons:
            text.insert("end", self._format_unison_pair(pair))

        text.insert(
            "end",
            (
                "\nComparaison des quintes de même rang : "
                f"{len(analysis.corresponding_fifths):,}\n"
                "Les fréquences sont égales uniquement si les valeurs en Hz sont strictement égales.\n"
            ).replace(",", " "),
        )
        for pair in analysis.corresponding_fifths:
            text.insert("end", self._format_corresponding_fifth(pair))

        text.insert(
            "end",
            (
                "\nPaires inter-tempéraments dont le rapport de fréquences est entier "
                "(hors égalités exactes) : "
                f"{len(analysis.cross_temperament_integer_multiples):,}\n"
            ).replace(",", " "),
        )
        for pair in analysis.cross_temperament_integer_multiples:
            text.insert("end", self._format_integer_multiple(pair))

        text.insert(
            "end",
            (
                "\nPaires dont le rapport de fréquences est entier parmi toutes les quintes "
                f"(hors égalités exactes) : {len(analysis.integer_multiple_pairs):,}\n"
            ).replace(",", " "),
        )
        for pair in analysis.integer_multiple_pairs:
            text.insert("end", self._format_integer_multiple(pair))

        text.insert(
            "end",
            (
                "\nÉquivalences entre calibrages par octave "
                f"(rapport puissance de 2) : {len(analysis.cross_temperament_octave_matches):,}\n"
            ).replace(",", " "),
        )
        for pair in analysis.cross_temperament_octave_matches:
            text.insert("end", self._format_octave_match(pair))

        text.insert("end", "\nÉcart minimal non nul entre quintes de même rang :\n")
        text.insert("end", self._format_pair(analysis.closest_cross_temperament))
        text.insert("end", "\nÉcart maximal entre quintes de même rang :\n")
        text.insert("end", self._format_pair(analysis.widest_pair))
        text.insert("end", "\nTous les unissons détectés :\n")
        for pair in analysis.unisons:
            text.insert("end", self._format_unison_pair(pair))

        text.insert("end", "\nRapprochement non nul le plus fin :\n")
        text.insert("end", self._format_pair(analysis.closest_non_unison))
        text.configure(state="disabled")

    def _show_cycle_map(self, analysis: CycleAnalysis) -> None:
        window = tk.Toplevel(self.root)
        window.title("Développement des calibrages — carte des octaves")
        window.geometry("1180x820")
        window.minsize(850, 600)

        header = tk.Label(
            window,
            text=(
                "Les deux parcours partent de La4 = 440 Hz. Basculez entre la carte 3D cyclique et la vue "
                "horizontale déroulée par octave ; les fréquences et octaves réelles restent dans le tableau."
            ),
            justify="left",
            anchor="w",
            wraplength=1120,
            padx=12,
            pady=8,
        )
        header.pack(fill="x")

        summary = (
            f"Égalités exactes : {len(analysis.cross_temperament_unisons)}    "
            f"Rapports entiers : {len(analysis.integer_multiple_pairs)} "
            f"(dont {len(analysis.cross_temperament_integer_multiples)} inter-tempéraments)    "
            f"Équivalences d’octave : {len(analysis.cross_temperament_octave_matches)}    "
            f"Fréquences mémorisées : {min(point.frequency_hz for point in analysis.points):.6g}–"
            f"{max(point.frequency_hz for point in analysis.points):.6g} Hz"
        )
        tk.Label(
            window,
            text=summary,
            justify="left",
            anchor="w",
            padx=12,
        ).pack(fill="x")

        marked_pairs = (
            ("unison", analysis.cross_temperament_unisons, "#facc15", "Unisson exact"),
            (
                "multiple",
                analysis.cross_temperament_integer_multiples,
                "#f97316",
                "Rapport de fréquences entier",
            ),
            (
                "octave",
                analysis.cross_temperament_octave_matches,
                "#0891b2",
                "Équivalence d’octave (rapport puissance de 2)",
            ),
            (
                "closest",
                (analysis.closest_cross_temperament,) if analysis.closest_cross_temperament else (),
                "#16a34a",
                "Plus petit écart non nul, même rang",
            ),
            (
                "widest",
                (analysis.widest_pair,) if analysis.widest_pair else (),
                "#9333ea",
                "Plus grand écart, même rang",
            ),
        )
        legend = tk.LabelFrame(window, text="Légende des deux vues", padx=8, pady=4)
        legend.pack(fill="x", padx=12, pady=(2, 6))
        legend_items = (
            ("pure", PURE_FIFTHS_COLOR, "Quintes pures : trait plein, cercle"),
            ("equal", EQUAL_FIFTHS_COLOR, "Quintes tempérées : pointillé, carré"),
            ("unison", EVENT_COLORS["unison"], "Égalité exacte — anneau"),
            ("multiple", EVENT_COLORS["multiple"], "Rapport entier inter-tempéraments — anneau"),
            ("octave", EVENT_COLORS["octave"], "Équivalence d’octave — anneau"),
            ("closest", EVENT_COLORS["closest"], "Écart minimal non nul, même rang — anneau"),
            ("widest", EVENT_COLORS["widest"], "Écart maximal, même rang — anneau"),
            ("link", EVENT_COLORS["common_multiple"], "Rapport entier entre quintes — lien pointillé, vue horizontale"),
            ("hatch", "#075985", "Zone hachurée : écart entre les deux parcours"),
            ("break", "#64748b", "// : octaves sans événement comprimées, vue horizontale"),
            ("grid", "#cbd5e1", "Grille : octaves et degrés chromatiques"),
        )
        for column in range(3):
            legend.columnconfigure(column, weight=1)
        for index, (symbol, color, label) in enumerate(legend_items):
            row, column = divmod(index, 3)
            entry = tk.Frame(legend)
            entry.grid(row=row, column=column, sticky="w", padx=4, pady=1)
            key = tk.Canvas(
                entry,
                width=34,
                height=20,
                highlightthickness=0,
                background=legend.cget("background"),
            )
            key.pack(side="left", padx=(0, 4))
            if symbol == "pure":
                key.create_line(2, 10, 32, 10, fill=color, width=2)
                key.create_oval(13, 6, 21, 14, fill=color, outline="white")
            elif symbol == "equal":
                key.create_line(2, 10, 32, 10, fill=color, width=2, dash=(4, 2))
                key.create_rectangle(13, 6, 21, 14, fill=color, outline="white")
            elif symbol in ("unison", "multiple", "octave", "closest", "widest"):
                key.create_oval(8, 2, 26, 20, outline=color, width=2)
                key.create_oval(14, 8, 20, 14, fill="#64748b", outline="")
            elif symbol == "link":
                key.create_line(2, 10, 32, 10, fill=color, width=2, dash=(2, 3))
            elif symbol == "hatch":
                key.create_rectangle(3, 3, 31, 17, fill=color, stipple="gray50", outline=color)
            elif symbol == "break":
                key.create_line(2, 10, 12, 10, fill=color, width=2)
                key.create_line(13, 6, 18, 14, fill=color, width=2)
                key.create_line(19, 6, 24, 14, fill=color, width=2)
                key.create_line(24, 10, 32, 10, fill=color, width=2)
            else:
                key.create_line(3, 10, 31, 10, fill=color, width=2)
            tk.Label(
                entry,
                text=label,
                justify="left",
                anchor="w",
                wraplength=300,
            ).pack(side="left", fill="x", expand=True)

        views = ttk.Notebook(window)
        views.pack(fill="both", expand=True, padx=8, pady=4)
        chart_frame = tk.Frame(views)
        views.add(chart_frame, text="Carte 3D")
        trace_controls = tk.Frame(chart_frame, padx=8, pady=4)
        trace_controls.pack(fill="x")
        tk.Label(trace_controls, text="Départ des quintes : La4 = 440 Hz").pack(side="left")
        view_mode = {"value": "globe"}
        view_toggle = ttk.Button(trace_controls, text="Vue horizontale")
        view_toggle.pack(side="left", padx=8)
        initial_pitch_degrees = math.degrees(-0.55)
        pitch_degrees = tk.DoubleVar(value=initial_pitch_degrees)
        tk.Label(trace_controls, text="Inclinaison :").pack(side="left", padx=(8, 2))
        pitch_scale = ttk.Scale(
            trace_controls,
            from_=-80.2,
            to=80.2,
            variable=pitch_degrees,
            command=lambda value: set_globe_pitch(float(value)),
            length=140,
        )
        pitch_scale.pack(side="left")
        pitch_label = tk.Label(
            trace_controls, text=f"{initial_pitch_degrees:.0f}°", width=5, anchor="w"
        )
        pitch_label.pack(side="left", padx=(2, 4))

        def set_globe_pitch(degrees: float) -> None:
            rotation["pitch"] = math.radians(degrees)
            pitch_label.configure(text=f"{degrees:.0f}°")
            redraw_globe()

        def reset_globe_rotation() -> None:
            rotation["yaw"] = 0.0
            pitch_degrees.set(initial_pitch_degrees)
            set_globe_pitch(initial_pitch_degrees)

        reset_rotation_button = ttk.Button(
            trace_controls, text="Réinitialiser l’angle", command=reset_globe_rotation
        )
        reset_rotation_button.pack(side="left", padx=4)
        canvas_frame = tk.Frame(chart_frame)
        canvas_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(
            canvas_frame,
            width=900,
            height=620,
            background="#fcfbf7",
            highlightthickness=0,
        )
        canvas_y_scrollbar = ttk.Scrollbar(
            canvas_frame, orient="vertical", command=canvas.yview
        )
        canvas_x_scrollbar = ttk.Scrollbar(
            canvas_frame, orient="horizontal", command=canvas.xview
        )
        canvas.configure(
            xscrollcommand=canvas_x_scrollbar.set,
            yscrollcommand=canvas_y_scrollbar.set,
        )
        canvas.grid(row=0, column=0, sticky="nsew")
        canvas_y_scrollbar.grid(row=0, column=1, sticky="ns")
        canvas_x_scrollbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        canvas_x_scrollbar.grid_remove()
        canvas_y_scrollbar.grid_remove()

        table_frame = tk.Frame(views, padx=8, pady=8)
        views.add(table_frame, text="Points mémorisés")
        columns = ("temperament", "start", "step", "point", "frequency", "degree")
        table = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)
        column_specs = (
            ("temperament", "Calibrage", 205),
            ("start", "Départ (note / octave / Hz)", 230),
            ("step", "Quinte", 70),
            ("point", "Point atteint", 145),
            ("frequency", "Fréquence réelle (Hz)", 170),
            ("degree", "Degré / octave", 130),
        )
        for column, heading, width in column_specs:
            table.heading(column, text=heading)
            table.column(column, width=width, minwidth=60, stretch=column in ("start", "point"))
        y_scrollbar = tk.Scrollbar(table_frame, orient="vertical", command=table.yview)
        x_scrollbar = tk.Scrollbar(table_frame, orient="horizontal", command=table.xview)
        table.configure(yscrollcommand=y_scrollbar.set, xscrollcommand=x_scrollbar.set)
        y_scrollbar.pack(side="right", fill="y")
        x_scrollbar.pack(side="bottom", fill="x")
        table.pack(side="left", fill="both", expand=True)

        point_tags: dict[int, str] = {}
        chart_event_tags: dict[int, set[str]] = {}
        marker_priority = {"unison": 1, "multiple": 2, "octave": 3, "closest": 4, "widest": 5}
        for tag, pairs, _, _ in marked_pairs:
            for pair in pairs:
                for point in (pair.first, pair.second):
                    chart_event_tags.setdefault(id(point), set()).add(tag)
                    previous_tag = point_tags.get(id(point))
                    if previous_tag is None or marker_priority[tag] > marker_priority[previous_tag]:
                        point_tags[id(point)] = tag
        horizontal_event_tags = {
            point_id: tuple(sorted(tags, key=marker_priority.__getitem__))
            for point_id, tags in chart_event_tags.items()
        }
        event_octaves = {
            point.octave_number
            for _, pairs, _, _ in marked_pairs
            for pair in pairs
            for point in (pair.first, pair.second)
        }

        table.tag_configure("unison", background="#fef3c7")
        table.tag_configure("multiple", background="#ffedd5")
        table.tag_configure("octave", background="#cffafe")
        table.tag_configure("closest", background="#dcfce7")
        table.tag_configure("widest", background="#f3e8ff")
        ordered_points = sorted(
            analysis.points,
            key=lambda point: (point.octave_number, octave_position_cents(point), point.temperament),
        )
        for point in ordered_points:
            table.insert(
                "",
                "end",
                values=(
                    point.temperament,
                    f"{point.starting_note}{point.starting_octave_number} / "
                    f"{point.starting_frequency_hz:.9g}",
                    point.step_number,
                    point.note_label,
                    f"{point.frequency_hz:.12g}",
                    f"{(CHROMATIC_NOTES.index(point.note) - REFERENCE_PITCH_CLASS) % 12 + 1}° / "
                    f"{point.written_octave_number}",
                ),
                tags=(point_tags[id(point)],) if id(point) in point_tags else (),
            )

        grouped_points: dict[tuple[str, str], list[CyclePoint]] = {}
        for point in analysis.points:
            grouped_points.setdefault((point.temperament, point.starting_note), []).append(point)
        octave_min = min(point.octave_number for point in analysis.points)
        octave_max = max(point.octave_number for point in analysis.points)
        octave_positions = compressed_octave_positions(octave_min, octave_max, event_octaves)
        rotation = {"yaw": 0.0, "pitch": -0.55}
        drag_origin = {"x": 0, "y": 0}

        def redraw_globe() -> None:
            selected_note = "La"
            visible_groups = {
                key: sequence
                for key, sequence in grouped_points.items()
                if key[1] == selected_note
            }
            visible_point_ids = {
                id(point)
                for sequence in visible_groups.values()
                for point in sequence
            }
            visible_tags = {
                point_id: tuple(
                    sorted(tags, key=marker_priority.__getitem__)
                )
                for point_id, tags in chart_event_tags.items()
                if point_id in visible_point_ids
            }

            if view_mode["value"] == "globe":
                canvas_width = max(1, canvas.winfo_width())
                canvas_height = max(1, canvas.winfo_height())
                center = (canvas_width / 2, canvas_height / 2)
                globe_radius = max(1, min(canvas_width, canvas_height) / 2 - 66)
                canvas.configure(
                    scrollregion=(0, 0, canvas_width, canvas_height),
                )
                canvas_x_scrollbar.grid_remove()
                canvas_y_scrollbar.grid_remove()
                self._draw_transparent_globe(
                    canvas,
                    visible_groups,
                    visible_tags,
                    center,
                    globe_radius,
                    canvas_height,
                    octave_min,
                    octave_max,
                    rotation["yaw"],
                    rotation["pitch"],
                    selected_note,
                )
                view_toggle.configure(text="Vue horizontale")
            else:
                canvas_x_scrollbar.grid()
                canvas_y_scrollbar.grid()
                canvas.update_idletasks()
                self._draw_horizontal_trace(
                    canvas,
                    visible_groups,
                    octave_min,
                    octave_max,
                    selected_note,
                    horizontal_event_tags,
                    octave_positions,
                    analysis.integer_multiple_pairs,
                )
                view_toggle.configure(text="Vue 3D cyclique")

        def begin_rotation(event: tk.Event) -> None:
            if view_mode["value"] != "globe":
                return
            drag_origin["x"] = event.x
            drag_origin["y"] = event.y

        def rotate_globe(event: tk.Event) -> None:
            if view_mode["value"] != "globe":
                return
            rotation["yaw"] += (event.x - drag_origin["x"]) * 0.01
            rotation["pitch"] = min(
                1.4,
                max(-1.4, rotation["pitch"] + (event.y - drag_origin["y"]) * 0.01),
            )
            pitch_degrees.set(math.degrees(rotation["pitch"]))
            pitch_label.configure(text=f"{rotation['pitch'] * 180 / math.pi:.0f}°")
            drag_origin["x"] = event.x
            drag_origin["y"] = event.y
            redraw_globe()

        def toggle_view() -> None:
            view_mode["value"] = "horizontal" if view_mode["value"] == "globe" else "globe"
            if view_mode["value"] == "horizontal":
                canvas.unbind("<ButtonPress-1>")
                canvas.unbind("<B1-Motion>")
                pitch_scale.configure(state="disabled")
                reset_rotation_button.configure(state="disabled")
            else:
                canvas.bind("<ButtonPress-1>", begin_rotation)
                canvas.bind("<B1-Motion>", rotate_globe)
                pitch_scale.configure(state="normal")
                reset_rotation_button.configure(state="normal")
            redraw_globe()

        view_toggle.configure(command=toggle_view)
        last_canvas_size = {"width": 0, "height": 0}

        def resize_canvas(event: tk.Event) -> None:
            size = (event.width, event.height)
            if size == (last_canvas_size["width"], last_canvas_size["height"]):
                return
            last_canvas_size["width"], last_canvas_size["height"] = size
            if event.width > 1 and event.height > 1:
                redraw_globe()

        canvas.bind("<Configure>", resize_canvas)
        canvas.bind("<ButtonPress-1>", begin_rotation)
        canvas.bind("<B1-Motion>", rotate_globe)
        redraw_globe()

    @staticmethod
    def _draw_horizontal_trace(
        canvas: tk.Canvas,
        grouped_points: dict[tuple[str, str], list[CyclePoint]],
        octave_min: int,
        octave_max: int,
        starting_note: str,
        event_tags_by_point: dict[int, tuple[str, ...]] | None = None,
        octave_positions: dict[int, float] | None = None,
        integer_multiple_pairs: tuple[PointPair, ...] = (),
    ) -> None:
        canvas.delete("all")
        octave_width = 90
        row_height = 42
        left = 72
        top = 48
        if octave_positions is None:
            octave_positions = {
                octave: left + (octave - octave_min) * octave_width
                for octave in range(octave_min, octave_max + 1)
            }
        chart_width = octave_positions[octave_max] + 90

        point_positions: dict[int, tuple[float, float]] = {}
        points_by_start_and_temperament: dict[
            tuple[str, str], dict[int, CyclePoint]
        ] = {}
        for (temperament, note), sequence in grouped_points.items():
            sequence.sort(key=lambda point: point.step_number)
            points_by_start_and_temperament[(temperament, note)] = {
                point.step_number: point for point in sequence
            }
            for point in sequence:
                point_positions[id(point)] = horizontal_trace_coordinates(
                    point,
                    octave_min,
                    octave_width,
                    row_height,
                    left,
                    top,
                    octave_positions,
                )

        starting_notes = {note for _, note in points_by_start_and_temperament}
        for note in starting_notes:
            pure_points = points_by_start_and_temperament.get(
                (Series.PURE_FIFTHS.value, note), {}
            )
            equal_points = points_by_start_and_temperament.get(
                (Series.EQUAL_FIFTHS.value, note), {}
            )
            for step in pure_points.keys() & equal_points.keys():
                pure = pure_points[step]
                equal = equal_points[step]
                pure_x, pure_y = point_positions[id(pure)]
                equal_x, equal_y = point_positions[id(equal)]
                midpoint = (pure_y + equal_y) / 2
                point_positions[id(pure)] = (
                    pure_x,
                    midpoint + (pure_y - midpoint) * TRACE_SEPARATION_SCALE,
                )
                point_positions[id(equal)] = (
                    equal_x,
                    midpoint + (equal_y - midpoint) * TRACE_SEPARATION_SCALE,
                )

        min_point_y = min(y for _, y in point_positions.values())
        vertical_shift = max(0, top - 20 - min_point_y)
        if vertical_shift:
            point_positions = {
                point_id: (x, y + vertical_shift)
                for point_id, (x, y) in point_positions.items()
            }
        plot_top = top + vertical_shift
        plot_bottom = plot_top + (len(CHROMATIC_NOTES) - 1) * row_height
        max_point_y = max(y for _, y in point_positions.values())
        graph_top = min(plot_top, min(y for _, y in point_positions.values()))
        graph_bottom = max(plot_bottom, max_point_y)
        graph_height = max(1, graph_bottom - graph_top)
        viewport_height = max(1, canvas.winfo_height())
        available_graph_height = max(1, viewport_height - top - 120)
        vertical_scale = min(
            1.0,
            max(0.35, available_graph_height / graph_height),
        )
        point_positions = {
            point_id: (
                x,
                top + (y - graph_top) * vertical_scale,
            )
            for point_id, (x, y) in point_positions.items()
        }
        plot_top = top + (plot_top - graph_top) * vertical_scale
        row_height *= vertical_scale
        chart_height = int(top + graph_height * vertical_scale + 120)
        legend_top = chart_height - 100
        canvas.configure(
            width=900,
            height=620,
            scrollregion=(0, 0, chart_width, chart_height),
        )
        canvas.xview_moveto(0)
        canvas.yview_moveto(0)

        note_by_degree = {
            (pitch_index - REFERENCE_PITCH_CLASS) % len(CHROMATIC_NOTES): note
            for pitch_index, note in enumerate(CHROMATIC_NOTES)
        }
        for note in starting_notes:
            pure_points = points_by_start_and_temperament.get(
                (Series.PURE_FIFTHS.value, note), {}
            )
            equal_points = points_by_start_and_temperament.get(
                (Series.EQUAL_FIFTHS.value, note), {}
            )
            for step in pure_points.keys() & equal_points.keys():
                next_step = step + 1
                if next_step not in pure_points or next_step not in equal_points:
                    continue
                pure_start = point_positions[id(pure_points[step])]
                pure_end = point_positions[id(pure_points[next_step])]
                equal_start = point_positions[id(equal_points[step])]
                equal_end = point_positions[id(equal_points[next_step])]
                vertices = (pure_start, pure_end, equal_end, equal_start)
                area = abs(
                    sum(
                        vertices[index][0] * vertices[(index + 1) % 4][1]
                        - vertices[(index + 1) % 4][0] * vertices[index][1]
                        for index in range(4)
                    )
                ) / 2
                if area <= 1:
                    continue
                pure_mid_y = (pure_start[1] + pure_end[1]) / 2
                equal_mid_y = (equal_start[1] + equal_end[1]) / 2
                upper_temperament = (
                    Series.PURE_FIFTHS.value
                    if pure_mid_y < equal_mid_y
                    else Series.EQUAL_FIFTHS.value
                )
                canvas.create_polygon(
                    *(coordinate for point in vertices for coordinate in point),
                    fill=CYCLE_COLORS[upper_temperament],
                    outline="",
                    stipple="gray50",
                )

        for degree in range(len(CHROMATIC_NOTES)):
            y = plot_top + degree * row_height
            canvas.create_line(left - 12, y, chart_width - 24, y, fill="#e1e6ec", width=1)
            canvas.create_text(
                left - 22,
                y,
                text=note_by_degree[degree],
                anchor="e",
                fill="#475569",
                font=("Segoe UI", 9, "bold" if degree == 0 else "normal"),
            )

        expanded_octaves = {
            octave
            for octave in range(octave_min, octave_max)
            if octave_positions[octave + 1] - octave_positions[octave] >= 30
        }
        event_octaves = {
            point.octave_number
            for (temperament, _), sequence in grouped_points.items()
            for point in sequence
            if event_tags_by_point is not None and id(point) in event_tags_by_point
        }
        label_candidates = event_octaves | {
            octave for octave in range(octave_min, octave_max + 1) if octave % 12 == 0
        }
        labeled_octaves: set[int] = set()
        for octave in sorted(label_candidates, key=lambda value: (value not in event_octaves, value)):
            if all(
                abs(octave_positions[octave] - octave_positions[existing]) >= 42
                for existing in labeled_octaves
            ):
                labeled_octaves.add(octave)

        for octave in range(octave_min, octave_max + 1):
            x = octave_positions[octave]
            if octave < octave_max and octave in expanded_octaves:
                canvas.create_line(
                    x,
                    plot_top - 22,
                    x,
                    legend_top - 16,
                    fill="#cbd5e1" if octave % 12 == 0 else "#edf0f4",
                    width=1.2 if octave % 12 == 0 else 0.8,
                )
            if octave in labeled_octaves:
                canvas.create_text(
                    x,
                    plot_top - 34,
                    text=f"LA{octave}",
                    fill="#475569",
                    font=("Segoe UI", 8, "bold"),
                )

        compressed_runs: list[list[int]] = []
        for octave in range(octave_min, octave_max):
            if octave in expanded_octaves:
                continue
            if not compressed_runs or compressed_runs[-1][-1] != octave - 1:
                compressed_runs.append([])
            compressed_runs[-1].append(octave)
        for run in compressed_runs:
            middle_octave = run[len(run) // 2]
            x = (octave_positions[middle_octave] + octave_positions[middle_octave + 1]) / 2
            for y in (plot_top - 22, legend_top - 16):
                canvas.create_line(x - 4, y - 3, x, y + 3, fill="#64748b", width=1.4)
                canvas.create_line(x + 1, y - 3, x + 5, y + 3, fill="#64748b", width=1.4)

        for pair in integer_multiple_pairs:
            first_position = point_positions.get(id(pair.first))
            second_position = point_positions.get(id(pair.second))
            if first_position is None or second_position is None:
                continue
            canvas.create_line(
                *first_position,
                *second_position,
                fill=EVENT_COLORS["common_multiple"],
                width=1,
                dash=(2, 4),
            )

        for (temperament, _), sequence in grouped_points.items():
            for start_point, end_point in zip(sequence, sequence[1:]):
                start = point_positions[id(start_point)]
                end = point_positions[id(end_point)]
                canvas.create_line(
                    *start,
                    *end,
                    fill=CYCLE_COLORS[temperament],
                    width=2.2,
                    capstyle=tk.ROUND,
                    dash=() if temperament == Series.PURE_FIFTHS.value else (5, 3),
                )
            for point in sequence:
                x, y = point_positions[id(point)]
                if temperament == Series.PURE_FIFTHS.value:
                    radius = 3
                    canvas.create_oval(
                        x - radius,
                        y - radius,
                        x + radius,
                        y + radius,
                        fill=CYCLE_COLORS[temperament],
                        outline="#ffffff",
                        width=1,
                    )
                else:
                    canvas.create_rectangle(
                        x - 3,
                        y - 3,
                        x + 3,
                        y + 3,
                        fill=CYCLE_COLORS[temperament],
                        outline="#ffffff",
                        width=1,
                    )
                event_tags = (
                    event_tags_by_point.get(id(point), ())
                    if event_tags_by_point is not None
                    else ()
                )
                for event_index, tag in enumerate(event_tags):
                    canvas.create_oval(
                        x - 8 - event_index * 3,
                        y - 8 - event_index * 3,
                        x + 8 + event_index * 3,
                        y + 8 + event_index * 3,
                        fill="",
                        outline=EVENT_COLORS[tag],
                        width=2,
                    )

            if sequence:
                origin_x, origin_y = point_positions[id(sequence[0])]
                if temperament == Series.PURE_FIFTHS.value:
                    canvas.create_oval(
                        origin_x - 6,
                        origin_y - 6,
                        origin_x + 6,
                        origin_y + 6,
                        fill=CYCLE_COLORS[temperament],
                        outline="#ffffff",
                        width=1.5,
                    )
                else:
                    canvas.create_rectangle(
                        origin_x - 7,
                        origin_y - 7,
                        origin_x + 7,
                        origin_y + 7,
                        fill="",
                        outline=CYCLE_COLORS[temperament],
                        width=2,
                    )

        pure_legend_y = legend_top
        canvas.create_oval(
            left,
            pure_legend_y - 5,
            left + 10,
            pure_legend_y + 5,
            fill=CYCLE_COLORS[Series.PURE_FIFTHS.value],
            outline="#ffffff",
            width=1,
        )
        canvas.create_text(
            left + 17,
            pure_legend_y,
            text="Quintes pures — trait continu, cercle",
            anchor="w",
            fill=CYCLE_COLORS[Series.PURE_FIFTHS.value],
            font=("Segoe UI", 9),
        )
        equal_legend_y = pure_legend_y + 24
        equal_legend_x = left
        canvas.create_rectangle(
            equal_legend_x,
            equal_legend_y - 6,
            equal_legend_x + 12,
            equal_legend_y + 6,
            fill="",
            outline=CYCLE_COLORS[Series.EQUAL_FIFTHS.value],
            width=2,
        )
        canvas.create_text(
            equal_legend_x + 19,
            equal_legend_y,
            text="Quintes tempérées — trait discontinu, carré",
            anchor="w",
            fill=CYCLE_COLORS[Series.EQUAL_FIFTHS.value],
            font=("Segoe UI", 9),
        )

        canvas.create_text(
            left,
            equal_legend_y + 26,
            text=(
                f"Départ {starting_note} · 1 octave = 12 lignes · "
                f"écart réel : {row_height / vertical_scale / 100:.2f} px/cent · "
                f"séparation ×{TRACE_SEPARATION_SCALE:g}, hauteur affichée ×"
                f"{vertical_scale:.2f} · zones hachurées entre les parcours · "
                "// = octave sans événement comprimée"
            ),
            anchor="w",
            fill="#596575",
            font=("Segoe UI", 9),
        )

    @staticmethod
    def _draw_transparent_globe(
        canvas: tk.Canvas,
        grouped_points: dict[tuple[str, str], list[CyclePoint]],
        point_tags: dict[int, tuple[str, ...]],
        center: float | tuple[float, float],
        radius: float,
        chart_height: int,
        octave_min: int,
        octave_max: int,
        yaw: float,
        pitch: float,
        starting_note: str,
    ) -> None:
        canvas.delete("all")
        center_x, center_y = center if isinstance(center, tuple) else (center, center)

        def layer_coordinates(
            layer: float, chromatic_degree: float
        ) -> tuple[float, float, float]:
            return _globe_surface_coordinates(
                layer,
                chromatic_degree,
                center,
                radius,
                yaw,
                pitch,
            )

        def draw_curve(
            samples: list[tuple[float, float, float]],
            front_color: str,
            back_color: str,
            width: float = 1,
            dash: tuple[int, int] = (2, 4),
        ) -> None:
            for start, end in zip(samples, samples[1:]):
                midpoint_depth = (start[2] + end[2]) / 2
                canvas.create_line(
                    start[0],
                    start[1],
                    end[0],
                    end[1],
                    fill=front_color if midpoint_depth >= 0 else back_color,
                    width=width,
                    dash=() if midpoint_depth >= 0 else dash,
                )

        octave_span = max(1, octave_max - octave_min)
        longitude_count = octave_span + 1
        major_step = max(1, math.ceil(octave_span / 12))
        major_octaves = set(range(octave_min, octave_max + 1, major_step))
        major_octaves.update((octave_min, octave_max))
        for octave in range(octave_min, octave_max + 1):
            layer = (octave - octave_min) / longitude_count
            samples = [
                layer_coordinates(layer, 12 * index / 48)
                for index in range(49)
            ]
            major = octave in major_octaves
            draw_curve(
                samples,
                "#aeb9c7" if major else "#d5dbe3",
                "#d1d8e1" if major else "#e5e9ef",
                1.2 if major else 0.7,
            )

        for pitch_index in range(len(CHROMATIC_NOTES)):
            degree = (pitch_index - REFERENCE_PITCH_CLASS) % len(CHROMATIC_NOTES)
            samples = [
                layer_coordinates(index / 48, degree)
                for index in range(49)
            ]
            draw_curve(samples, "#c1cad5", "#e0e5eb", 0.8)

        middle_layer = 0.5
        label_step = max(1, math.ceil(octave_span / 6))
        labeled_octaves = set(range(octave_min, octave_max, label_step))
        labeled_octaves.add(octave_min)
        for octave in sorted(labeled_octaves):
            layer = (octave - octave_min) / longitude_count
            x, y, _ = layer_coordinates(layer, 6)
            canvas.create_text(
                x,
                y - 10,
                text=f"λ{octave - octave_min}",
                anchor="s",
                fill="#596575",
                font=("Segoe UI", 8),
            )

        note_label_positions: list[tuple[str, float, float]] = []
        for pitch_index, note in enumerate(CHROMATIC_NOTES):
            degree = (pitch_index - REFERENCE_PITCH_CLASS) % len(CHROMATIC_NOTES)
            x, y, _ = layer_coordinates(0.25, degree)
            dx, dy = x - center_x, y - center_y
            label_distance = max(1, math.hypot(dx, dy))
            note_label_positions.append(
                (
                    note,
                    x + dx / label_distance * 18,
                    y + dy / label_distance * 18,
                )
            )

        for note, x, y in note_label_positions:
            label_width = 14 + len(note) * 7
            canvas.create_rectangle(
                x - label_width / 2,
                y - 10,
                x + label_width / 2,
                y + 10,
                fill="#fcfbf7",
                outline="#cbd5e1",
                width=1,
            )
        for note, x, y in note_label_positions:
            canvas.create_text(
                x,
                y,
                text=note,
                fill="#596575",
                font=("Segoe UI", 9, "bold" if note == "La" else "normal"),
            )

        path_colors = {
            Series.PURE_FIFTHS.value: ("#c2410c", "#e6a17f"),
            Series.EQUAL_FIFTHS.value: ("#075985", "#7bb5d6"),
        }
        for (temperament, _), sequence in grouped_points.items():
            sequence.sort(key=lambda point: point.step_number)
            front_color, back_color = path_colors[temperament]
            for start_point, end_point in zip(sequence, sequence[1:]):
                trace = globe_trace_coordinates(
                    start_point,
                    end_point,
                    center,
                    radius,
                    octave_min,
                    octave_max,
                    yaw,
                    pitch,
                )
                for start, end in zip(trace, trace[1:]):
                    front = (start[2] + end[2]) / 2 >= 0
                    canvas.create_line(
                        start[0],
                        start[1],
                        end[0],
                        end[1],
                        fill=front_color if front else back_color,
                        width=2.2 if front else 1.4,
                        dash=() if front else (5, 3),
                    )

        points = [point for sequence in grouped_points.values() for point in sequence]
        points.sort(
            key=lambda point: globe_coordinates(
                point, center, radius, octave_min, octave_max, yaw, pitch
            )[2]
        )
        trace_colors = {
            Series.PURE_FIFTHS.value: ("#c2410c", "#e6a17f"),
            Series.EQUAL_FIFTHS.value: ("#075985", "#7bb5d6"),
        }
        for point in points:
            x, y, depth = globe_coordinates(
                point, center, radius, octave_min, octave_max, yaw, pitch
            )
            front_fill, back_fill = trace_colors[point.temperament]
            fill = front_fill if depth >= 0 else back_fill
            outline = fill
            size = 1.5 if point.step_number else 1
            width = 0
            canvas.create_oval(
                x - size,
                y - size,
                x + size,
                y + size,
                fill=fill,
                outline=outline,
                width=width,
            )
            for ring_index, tag in enumerate(point_tags.get(id(point), ())):
                ring_size = 5 + ring_index * 3
                canvas.create_oval(
                    x - ring_size,
                    y - ring_size,
                    x + ring_size,
                    y + ring_size,
                    fill="",
                    outline=EVENT_COLORS[tag],
                    width=2,
                )

        canvas.create_text(
            center_x,
            chart_height - 14,
            text=(
                f"Départ {starting_note} · longitude 0 = La4 · "
                f"longitude 120 puis 121 = 0 · 12 demi-tons équidistants · "
                "glisser pour tourner ; régler l’inclinaison ci-dessus"
            ),
            fill="#596575",
            font=("Segoe UI", 9),
        )

    @staticmethod
    def _format_pair(pair: PointPair | None) -> str:
        if pair is None:
            return "Aucune paire trouvée.\n"
        return (
            f"  {MusicCircleApp._format_cents(pair.distance_cents)} cents\n"
            f"  {pair.first.path} — {pair.first.frequency_hz:.9g} Hz\n"
            f"  {pair.second.path} — {pair.second.frequency_hz:.9g} Hz\n"
        )

    @staticmethod
    def _format_corresponding_fifth(pair: PointPair) -> str:
        frequencies_equal = pair.first.frequency_hz == pair.second.frequency_hz
        equality = "oui" if frequencies_equal else "non"
        return (
            f"  Quinte {pair.first.step_number} depuis La4 :\n"
            f"    {pair.first.temperament} — {pair.first.path} — "
            f"{pair.first.frequency_hz:.17g} Hz\n"
            f"    {pair.second.temperament} — {pair.second.path} — "
            f"{pair.second.frequency_hz:.17g} Hz\n"
            f"    Fréquences strictement égales : {equality} ; "
            f"écart : {MusicCircleApp._format_cents(pair.distance_cents)} cents\n\n"
        )

    @staticmethod
    def _format_cents(distance_cents: float) -> str:
        return "0" if distance_cents == 0 else f"{distance_cents:.9g}"

    @staticmethod
    def _format_unison_pair(pair: PointPair) -> str:
        points = sorted(
            (pair.first, pair.second),
            key=lambda point: (
                point.temperament != Series.PURE_FIFTHS.value,
                point.temperament,
            ),
        )
        lines = []
        for point in points:
            lines.extend(
                (
                    f"  {point.temperament}\n",
                    f"    {point.note_label} = quinte {point.step_number} depuis "
                    f"{format_note_octave(point.starting_note, point.starting_octave_number)} "
                    f"— {point.frequency_hz:.9g} Hz\n",
                )
            )
        lines.append(f"  Écart : {MusicCircleApp._format_cents(pair.distance_cents)} cents\n\n")
        return "".join(lines)

    @staticmethod
    def _format_octave_match(pair: PointPair) -> str:
        octave_shift = round(pair.second.log2_frequency - pair.first.log2_frequency)
        direction = "au-dessus" if octave_shift > 0 else "au-dessous"
        return (
            f"  {pair.first.path} — {pair.first.frequency_hz:.9g} Hz\n"
            f"  {pair.second.path} — {pair.second.frequency_hz:.9g} Hz\n"
            f"  Rapport de fréquences : 2^{abs(octave_shift)} ({direction})\n\n"
        )

    @staticmethod
    def _format_integer_multiple(pair: PointPair) -> str:
        multiple = integer_frequency_multiple(pair.first.frequency_hz, pair.second.frequency_hz)
        if multiple is None:
            raise ValueError("Le rapport des fréquences de cette paire n'est pas entier.")
        lower = min(pair.first.frequency_hz, pair.second.frequency_hz)
        higher = max(pair.first.frequency_hz, pair.second.frequency_hz)
        return (
            f"  {pair.first.path} — {pair.first.frequency_hz:.9g} Hz\n"
            f"  {pair.second.path} — {pair.second.frequency_hz:.9g} Hz\n"
            f"  Rapport de fréquences : {higher:.9g} / {lower:.9g} ≈ {multiple}\n\n"
        )

    @animated_sequence
    def start_animation(self) -> Iterator[int]:
        for count in range(1, len(build_sequence(self.selected_series)) + 1):
            yield count

    def draw_circle(self, visible_steps: int | None = None) -> None:
        """Dessine les classes chromatiques et les étapes actuellement révélées.

        Les coordonnées représentent des classes de hauteur, pas des fréquences exactes.
        La fermeture du cercle ci-dessous est donc graphique ; elle ne signifie pas
        que la dernière quinte pure rejoint acoustiquement la fréquence initiale.
        """
        self.canvas.delete("all")
        sequence = build_sequence(self.selected_series)
        cycle_is_complete = visible_steps is None or visible_steps >= len(sequence)
        arrival = build_cycle_arrival(self.selected_series) if cycle_is_complete else None
        if self.selected_series is Series.DIATONIC:
            self.cycle_arrival_label.configure(
                text=(
                    "L’ordre diatonique présente sept notes ; il est distinct du cycle chromatique "
                    "des quintes. En tempérament égal, les 12 quintes reviennent exactement à La "
                    "après 7 octaves ; avec des quintes pures, subsiste le comma."
                )
            )
        elif arrival is None:
            self.cycle_arrival_label.configure(text="Arrivée Ré → La : visible à la fin de l'animation.")
        else:
            self.cycle_arrival_label.configure(
                text=(
                    f"Départ : La4 = {REFERENCE_HZ:.2f} Hz   |   "
                    f"Arrivée Ré → La : {arrival.note}{arrival.octave_number} = "
                    f"{arrival.frequency_hz:,.2f} Hz   "
                    f"(dans l'octave du cercle : La4 = {arrival.folded_frequency_hz:.2f} Hz)"
                ).replace(",", " ")
            )
        # Do est placé en haut, puis les 12 positions avancent dans le sens horaire.
        angles = {
            pitch_class: -math.pi / 2 + pitch_class * 2 * math.pi / 12
            for pitch_class in range(12)
        }
        coordinates = {
            pitch_class: (
                self.CENTER + self.RADIUS * math.cos(angle),
                self.CENTER + self.RADIUS * math.sin(angle),
            )
            for pitch_class, angle in angles.items()
        }

        self.canvas.create_oval(
            self.CENTER - self.RADIUS,
            self.CENTER - self.RADIUS,
            self.CENTER + self.RADIUS,
            self.CENTER + self.RADIUS,
            outline="#c8c8c8",
            width=1,
        )

        count = len(sequence) if visible_steps is None else visible_steps
        shown = sequence[:count]
        # Relie uniquement les étapes déjà révélées par l'animation.
        for previous, current in zip(shown, shown[1:]):
            self._draw_link(coordinates[previous.pitch_class], coordinates[current.pitch_class])
        if visible_steps is None or count == len(sequence):
            if len(sequence) > 1:
                # Fermeture visuelle entre la dernière et la première position, sans calcul du comma.
                self._draw_link(coordinates[sequence[-1].pitch_class], coordinates[sequence[0].pitch_class])

        # Une seule étiquette est affichée par position chromatique.
        shown_by_pitch = {step.pitch_class: step for step in shown}
        for pitch_class, (x, y) in coordinates.items():
            step = shown_by_pitch.get(pitch_class)
            is_active = step is not None
            color = "#e27b36" if is_active else "#ffffff"
            self.canvas.create_oval(
                x - 23,
                y - 23,
                x + 23,
                y + 23,
                fill=color,
                outline="#374151",
                width=2,
            )
            self.canvas.create_text(
                x,
                y - 5,
                text=format_note_label(step) if step is not None else CHROMATIC_NOTES[pitch_class].upper(),
                font=("Segoe UI", 10, "bold"),
                fill="#ffffff" if is_active else "#374151",
            )
            if step is not None:
                label = (
                    f"{step.frequency_hz:.2f} Hz"
                    if self.label_mode_var.get() == LabelMode.HERTZ.value
                    else f"{(pitch_class - REFERENCE_PITCH_CLASS) % 12 + 1}°"
                )
                self.canvas.create_text(
                    x,
                    y + 39,
                    text=label,
                    font=("Segoe UI", 9),
                    fill="#333333",
                )

    def _draw_link(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        self.canvas.create_line(
            *start,
            *end,
            fill="#55738b",
            width=2,
            arrow=tk.LAST,
            arrowshape=(9, 11, 4),
        )


def main() -> None:
    root = tk.Tk()
    MusicCircleApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
