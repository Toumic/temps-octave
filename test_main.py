from dataclasses import replace
import math
import unittest

from main import (
    CHROMATIC_NOTES,
    CYCLE_COLORS,
    DIATONIC_PITCH_CLASSES,
    EVENT_COLORS,
    REFERENCE_HZ,
    TRACE_SEPARATION_SCALE,
    CyclePoint,
    MusicCircleApp,
    PointPair,
    Series,
    _project_globe_point,
    build_cycle_arrival,
    build_cycle_analysis,
    build_sequence,
    compressed_octave_positions,
    format_accidentals,
    format_multiple,
    format_note_label,
    globe_coordinates,
    globe_trace_coordinates,
    horizontal_trace_coordinates,
    integer_frequency_multiple,
    octave_position_cents,
    pair_integer_multiple,
    without_pure_tonic,
)


class BuildSequenceTests(unittest.TestCase):
    def test_default_globe_orientation_places_north_at_the_top(self) -> None:
        _, north_y, _ = _project_globe_point(
            0,
            0,
            1,
            (100, 100),
            50,
            0,
            -0.55,
        )

        self.assertLess(north_y, 100)

    def test_pure_fifths_follow_the_chromatic_circle(self) -> None:
        steps = build_sequence(Series.PURE_FIFTHS)

        self.assertEqual(len(steps), 12)
        self.assertEqual(
            [step.note for step in steps],
            ["La", "Mi", "Si", "Fa#", "Do#", "Sol#", "Ré#", "La#", "Fa", "Do", "Sol", "Ré"],
        )
        self.assertAlmostEqual(steps[0].frequency_hz, 440.0)
        self.assertAlmostEqual(steps[1].frequency_hz, 660.0)
        self.assertAlmostEqual(steps[2].frequency_hz, 990.0)
        self.assertTrue(
            all(previous.frequency_hz < current.frequency_hz for previous, current in zip(steps, steps[1:]))
        )

    def test_equal_fifths_use_semitone_steps(self) -> None:
        steps = build_sequence(Series.EQUAL_FIFTHS)

        self.assertEqual([step.note for step in steps[:2]], ["La", "Mi"])
        self.assertAlmostEqual(steps[1].frequency_hz / steps[0].frequency_hz, 2 ** (7 / 12))
        self.assertAlmostEqual(steps[-1].frequency_hz, REFERENCE_HZ * (2 ** (7 / 12)) ** 11)

    def test_bubble_labels_prefix_accidentals_and_keep_real_octaves(self) -> None:
        pure_steps = build_sequence(Series.PURE_FIFTHS)
        equal_steps = build_sequence(Series.EQUAL_FIFTHS)

        self.assertEqual(format_note_label(pure_steps[0]), "LA4")
        self.assertEqual(format_note_label(pure_steps[3]), "+FA6")
        self.assertEqual(format_note_label(pure_steps[9]), "+SI9")
        self.assertEqual(format_note_label(equal_steps[1]), "MI5")

    def test_signed_accidental_notation_matches_the_supplied_index_tables(self) -> None:
        expected = {
            0: "",
            1: "+",
            2: "x",
            3: "^",
            4: "+^",
            5: "x^",
            6: "^^",
            28: "+^^^^^^^^^",
            29: "x^^^^^^^^^",
            30: "^^^^^^^^^^",
            -1: "-",
            -2: "o",
            -3: "*",
            -4: "-*",
            -5: "o*",
            -6: "**",
            -28: "-*********",
            -29: "o*********",
            -30: "**********",
        }

        for accidental_count, notation in expected.items():
            with self.subTest(accidental_count=accidental_count):
                self.assertEqual(format_accidentals(accidental_count), notation)

    def test_cycle_arrival_shows_the_fifth_from_d_to_a(self) -> None:
        pure_arrival = build_cycle_arrival(Series.PURE_FIFTHS)
        equal_arrival = build_cycle_arrival(Series.EQUAL_FIFTHS)

        self.assertIsNotNone(pure_arrival)
        self.assertIsNotNone(equal_arrival)
        self.assertEqual(pure_arrival.note, "La")
        self.assertEqual(equal_arrival.note, "La")
        self.assertEqual(pure_arrival.octave_number, 11)
        self.assertEqual(equal_arrival.octave_number, 11)
        self.assertAlmostEqual(pure_arrival.frequency_hz, 440.0 * (3 / 2) ** 12)
        self.assertAlmostEqual(pure_arrival.folded_frequency_hz, 446.0030365, places=6)
        self.assertAlmostEqual(equal_arrival.frequency_hz, 56320.0, places=8)
        self.assertAlmostEqual(equal_arrival.folded_frequency_hz, 440.0, places=10)
        self.assertIsNone(build_cycle_arrival(Series.DIATONIC))

    def test_diatonic_order_uses_seven_notes(self) -> None:
        steps = build_sequence(Series.DIATONIC)

        self.assertEqual(
            [step.pitch_class for step in steps],
            [9, 11, 0, 2, 4, 5, 7],
        )
        self.assertEqual(len(steps), 7)
        self.assertEqual(steps[0].note, "La")
        self.assertAlmostEqual(steps[0].frequency_hz, REFERENCE_HZ)
        self.assertEqual(set(step.pitch_class for step in steps), set(DIATONIC_PITCH_CLASSES))

    def test_invalid_reference_frequency_is_rejected(self) -> None:
        for frequency in (0, -1, float("inf"), float("nan")):
            with self.subTest(frequency=frequency):
                with self.assertRaises(ValueError):
                    build_sequence(Series.PURE_FIFTHS, frequency)

    def test_integer_frequency_multiplicity_is_not_limited_to_octaves(self) -> None:
        self.assertEqual(integer_frequency_multiple(660.0, 220.0), 3)
        self.assertEqual(integer_frequency_multiple(880.0, 220.0), 4)
        self.assertEqual(integer_frequency_multiple(660.0000000000001, 220.0), 3)
        self.assertIsNone(integer_frequency_multiple(700.0, 220.0))
        self.assertIsNone(integer_frequency_multiple(440.0, 440.0))
        self.assertIsNone(integer_frequency_multiple(0.0, 220.0))
        self.assertIsNone(integer_frequency_multiple(440.0 * 100_000_000, 440.0))

    def test_cycle_analysis_uses_only_the_la4_reference_start(self) -> None:
        analysis = build_cycle_analysis(max_octaves=1)

        self.assertEqual(len(analysis.points), 4)
        self.assertEqual(analysis.comparisons, 4 * 3 // 2)
        self.assertTrue(analysis.unisons)
        self.assertTrue(analysis.cross_temperament_unisons)
        self.assertTrue(
            all(pair.first.frequency_hz == pair.second.frequency_hz for pair in analysis.unisons)
        )
        self.assertTrue(all(pair.distance_cents == 0 for pair in analysis.unisons))
        self.assertTrue(
            all(pair.first.frequency_hz == pair.second.frequency_hz for pair in analysis.cross_temperament_unisons)
        )
        self.assertEqual({point.starting_note for point in analysis.points}, {"La"})
        self.assertEqual(len(analysis.cross_temperament_unisons), 1)
        self.assertEqual(
            {
                (pair.first.starting_note, pair.second.starting_note)
                for pair in analysis.cross_temperament_unisons
            },
            {("La", "La")},
        )
        self.assertIsNotNone(analysis.closest_cross_temperament)
        self.assertEqual(analysis.max_octaves, 1)

    def test_analysis_compares_same_rank_fifths_and_reports_their_minimum_and_maximum(self) -> None:
        analysis = build_cycle_analysis(max_octaves=12)

        self.assertTrue(analysis.corresponding_fifths)
        self.assertTrue(
            all(
                pair.first.temperament != pair.second.temperament
                and pair.first.step_number == pair.second.step_number
                for pair in analysis.corresponding_fifths
            )
        )
        non_unison_pairs = [
            pair for pair in analysis.corresponding_fifths if pair.distance_cents > 0
        ]
        self.assertIsNotNone(analysis.closest_cross_temperament)
        self.assertIsNotNone(analysis.widest_pair)
        self.assertEqual(
            analysis.closest_cross_temperament.distance_cents,
            min(pair.distance_cents for pair in non_unison_pairs),
        )
        self.assertEqual(
            analysis.widest_pair.distance_cents,
            max(pair.distance_cents for pair in analysis.corresponding_fifths),
        )
        self.assertEqual(
            len(analysis.integer_multiple_pairs),
            len(set(analysis.integer_multiple_pairs)),
        )
        self.assertTrue(
            all(
                pair in analysis.integer_multiple_pairs
                for pair in analysis.cross_temperament_integer_multiples
            )
        )

        report_line = MusicCircleApp._format_corresponding_fifth(
            analysis.corresponding_fifths[1]
        )
        self.assertIn("Fréquences strictement égales :", report_line)
        self.assertIn(" Hz", report_line)

    def test_cycle_analysis_validates_the_octave_limit(self) -> None:
        for max_octaves in (0, 121):
            with self.subTest(max_octaves=max_octaves):
                with self.assertRaises(ValueError):
                    build_cycle_analysis(max_octaves=max_octaves)
        for max_octaves in (1.5, True):
            with self.subTest(max_octaves=max_octaves):
                with self.assertRaises(TypeError):
                    build_cycle_analysis(max_octaves=max_octaves)

    def test_cycle_point_labels_follow_the_la4_reference_cycle(self) -> None:
        analysis = build_cycle_analysis(max_octaves=1)
        tempered_la_cycle = [
            point
            for point in analysis.points
            if point.temperament == Series.EQUAL_FIFTHS.value and point.starting_note == "La"
        ]

        self.assertEqual(
            tempered_la_cycle[0].path,
            "Quintes tempérées (ratio 2^(7/12)), LA4 = quinte 0 depuis LA4",
        )
        self.assertEqual(
            tempered_la_cycle[1].path,
            "Quintes tempérées (ratio 2^(7/12)), MI5 = quinte 1 depuis LA4",
        )
        self.assertTrue(all(point.starting_note == "La" for point in analysis.points))

    def test_ninth_pure_fifth_from_la_is_written_as_si_sharp_nine(self) -> None:
        analysis = build_cycle_analysis(max_octaves=6)
        ninth_fifth = next(
            point
            for point in analysis.points
            if point.temperament == Series.PURE_FIFTHS.value
            and point.starting_note == "La"
            and point.step_number == 9
        )

        self.assertEqual(ninth_fifth.note_label, "+SI9")
        self.assertEqual(ninth_fifth.written_octave_number, 9)
        self.assertEqual(ninth_fifth.octave_number, 10)
        self.assertAlmostEqual(ninth_fifth.frequency_hz, 440.0 * (3 / 2) ** 9)
        self.assertIn("= quinte 9 depuis LA4", ninth_fifth.path)

    def test_accidentals_accumulate_past_an_octave_of_sharps(self) -> None:
        analysis = build_cycle_analysis(max_octaves=50)
        eighty_fourth_fifth = next(
            point
            for point in analysis.points
            if point.temperament == Series.PURE_FIFTHS.value
            and point.step_number == 84
        )

        self.assertEqual(eighty_fourth_fifth.note_label, f"{'^' * 4}LA52")
        self.assertEqual(eighty_fourth_fifth.written_octave_number, 52)

    def test_unison_report_shows_la4_reference_unison(self) -> None:
        analysis = build_cycle_analysis(max_octaves=1)
        pair = next(
            pair
            for pair in analysis.cross_temperament_unisons
            if pair.first.starting_note == "La" and pair.second.starting_note == "La"
        )

        report = MusicCircleApp._format_unison_pair(pair)

        self.assertIn("LA4 = quinte 0 depuis LA4 — 440 Hz", report)
        self.assertNotIn("Départ :", report)
        self.assertLess(report.index(Series.PURE_FIFTHS.value), report.index(Series.EQUAL_FIFTHS.value))

    def test_octave_equivalent_cross_temperament_frequencies_keep_point_metadata(self) -> None:
        analysis = build_cycle_analysis(max_octaves=12)

        self.assertTrue(analysis.cross_temperament_octave_matches)
        self.assertTrue(
            all(
                pair in analysis.cross_temperament_integer_multiples
                for pair in analysis.cross_temperament_octave_matches
            )
        )
        pair = analysis.cross_temperament_octave_matches[0]
        shift = round(pair.second.log2_frequency - pair.first.log2_frequency)
        self.assertNotEqual(shift, 0)
        self.assertAlmostEqual(
            pair.second.log2_frequency - pair.first.log2_frequency,
            shift,
            places=12,
        )
        report = MusicCircleApp._format_octave_match(pair)
        self.assertIn(pair.first.path, report)
        self.assertIn(pair.second.path, report)
        self.assertIn("Rapport de fréquences : 2^", report)
        self.assertIn(pair, analysis.cross_temperament_integer_multiples)

    def test_integer_multiple_report_shows_factor_and_frequencies(self) -> None:
        analysis = build_cycle_analysis(max_octaves=1)
        first = replace(
            analysis.points[0],
            frequency_hz=220.0,
            log2_frequency=math.log2(220.0),
        )
        second = replace(
            analysis.points[1],
            frequency_hz=660.0,
            log2_frequency=math.log2(660.0),
        )
        pair = PointPair(first, second, math.log2(3) * 1200)

        report = MusicCircleApp._format_integer_multiple(pair)

        self.assertIn("Rapport de fréquences", report)
        self.assertIn("≈ 3", report)

    def test_octave_position_is_measured_from_c_and_stays_within_the_octave(self) -> None:
        analysis = build_cycle_analysis(max_octaves=1)
        la_start = next(
            point
            for point in analysis.points
            if point.temperament == Series.PURE_FIFTHS.value
            and point.starting_note == "La"
            and point.step_number == 0
        )

        self.assertAlmostEqual(octave_position_cents(la_start), 900.0, places=7)
        self.assertTrue(
            all(0 <= octave_position_cents(point) <= 1200 for point in analysis.points)
        )

    def test_globe_uses_octave_longitudes_and_twelve_equal_chromatic_positions(self) -> None:
        do_octave_4 = CyclePoint(
            temperament=Series.PURE_FIFTHS.value,
            starting_note="Do",
            starting_octave_number=4,
            starting_frequency_hz=REFERENCE_HZ,
            step_number=0,
            note="Do",
            octave_number=4,
            frequency_hz=REFERENCE_HZ,
            log2_frequency=0.0,
        )
        positions = {
            note: globe_coordinates(
                replace(do_octave_4, note=note, octave_number=4),
                100,
                50,
                octave_min=4,
                octave_max=124,
                yaw=0,
                pitch=-0.7,
            )
            for note in CHROMATIC_NOTES
        }
        la_position = positions["La"]

        self.assertAlmostEqual(la_position[0], 100, places=10)
        self.assertLess(la_position[1], 100)
        self.assertAlmostEqual(la_position[2], math.cos(0.7), places=10)
        self.assertEqual(len({(round(x, 8), round(y, 8)) for x, y, _ in positions.values()}), 12)
        octave_note_order = ("La", "La#", "Si", "Do", "Do#", "Ré", "Ré#", "Mi", "Fa", "Fa#", "Sol", "Sol#")
        three_dimensional_positions = [
            (x, y, depth * 50)
            for x, y, depth in (positions[note] for note in octave_note_order)
        ]
        adjacent_distances = [
            math.dist(
                three_dimensional_positions[index],
                three_dimensional_positions[index + 1],
            )
            for index in range(len(CHROMATIC_NOTES) - 1)
        ]
        self.assertTrue(
            all(
                math.isclose(distance, adjacent_distances[0], rel_tol=1e-12)
                for distance in adjacent_distances
            )
        )

        la_at_closing_longitude = globe_coordinates(
            replace(do_octave_4, note="La", octave_number=124),
            100,
            50,
            octave_min=4,
            octave_max=124,
            yaw=0,
            pitch=-0.7,
        )
        self.assertAlmostEqual(la_position[0], la_at_closing_longitude[0])
        self.assertAlmostEqual(la_position[1], la_at_closing_longitude[1])
        self.assertAlmostEqual(la_position[2], la_at_closing_longitude[2])
        wrapped_la_position = globe_coordinates(
            replace(do_octave_4, note="La", octave_number=125),
            100,
            50,
            octave_min=4,
            octave_max=124,
            yaw=0,
            pitch=-0.7,
        )
        self.assertAlmostEqual(la_position[0], wrapped_la_position[0])
        self.assertAlmostEqual(la_position[1], wrapped_la_position[1])
        rotated_position = globe_coordinates(
            replace(do_octave_4, note="La", octave_number=64),
            100,
            50,
            octave_min=4,
            octave_max=124,
            yaw=0.5,
            pitch=-0.7,
        )
        self.assertNotEqual(la_position, rotated_position)

    def test_globe_back_points_keep_their_temperament_color(self) -> None:
        analysis = build_cycle_analysis(max_octaves=120)
        octave_min = min(point.octave_number for point in analysis.points)
        octave_max = max(point.octave_number for point in analysis.points)
        point = next(
            point
            for point in analysis.points
            if point.starting_note == "La"
            and globe_coordinates(
                point, (100, 100), 50, octave_min, octave_max
            )[2] < 0
        )
        expected_fill = (
            "#e6a17f"
            if point.temperament == Series.PURE_FIFTHS.value
            else "#7bb5d6"
        )

        class CanvasProbe:
            def __init__(self) -> None:
                self.ovals: list[tuple[tuple[float, ...], dict[str, object]]] = []
                self.rectangles: list[tuple[tuple[float, ...], dict[str, object]]] = []
                self.texts: list[tuple[tuple[object, ...], dict[str, object]]] = []

            def delete(self, *_args: object) -> None:
                pass

            def create_line(self, *_args: object, **_kwargs: object) -> None:
                pass

            def create_text(self, *coordinates: object, **options: object) -> None:
                self.texts.append((coordinates, options))

            def create_rectangle(
                self, *coordinates: float, **options: object
            ) -> None:
                self.rectangles.append((coordinates, options))

            def create_oval(
                self, *coordinates: float, **options: object
            ) -> None:
                self.ovals.append((coordinates, options))

        canvas = CanvasProbe()
        MusicCircleApp._draw_transparent_globe(
            canvas,
            {(point.temperament, "La"): [point]},
            {id(point): ("unison", "closest")},
            (100, 100),
            50,
            200,
            octave_min,
            octave_max,
            0,
            0.55,
            "La",
        )
        x, y, _ = globe_coordinates(
            point, (100, 100), 50, octave_min, octave_max, 0, 0.55
        )
        point_size = 1.5 if point.step_number else 1

        self.assertIn(
            (
                (
                    x - point_size,
                    y - point_size,
                    x + point_size,
                    y + point_size,
                ),
                {"fill": expected_fill, "outline": expected_fill, "width": 0},
            ),
            canvas.ovals,
        )
        self.assertIn(
            EVENT_COLORS["unison"],
            [options.get("outline") for _, options in canvas.ovals],
        )
        self.assertIn(
            EVENT_COLORS["closest"],
            [options.get("outline") for _, options in canvas.ovals],
        )
        self.assertEqual(
            {
                options["text"]
                for _, options in canvas.texts
                if options.get("text") in CHROMATIC_NOTES
            },
            set(CHROMATIC_NOTES),
        )
        note_label_backgrounds = [
            options
            for _, options in canvas.rectangles
            if options.get("fill") == "#fcfbf7"
        ]
        self.assertEqual(len(note_label_backgrounds), len(CHROMATIC_NOTES))

    def test_quint_trace_interpolates_on_globe_surface(self) -> None:
        analysis = build_cycle_analysis()
        sequence = sorted(
            (
                point
                for point in analysis.points
                if point.temperament == Series.PURE_FIFTHS.value
                and point.starting_note == "La"
            ),
            key=lambda point: point.step_number,
        )
        start, end = sequence[3:5]

        trace = globe_trace_coordinates(
            start,
            end,
            center=100,
            radius=50,
            octave_min=4,
            octave_max=6,
            yaw=0.3,
            pitch=0.4,
            samples=8,
        )

        self.assertEqual(len(trace), 9)
        for actual, expected in (
            (trace[0], globe_coordinates(start, 100, 50, 4, 6, 0.3, 0.4)),
            (trace[-1], globe_coordinates(end, 100, 50, 4, 6, 0.3, 0.4)),
        ):
            for actual_coordinate, expected_coordinate in zip(actual, expected):
                self.assertAlmostEqual(actual_coordinate, expected_coordinate)
        for x, y, depth in trace:
            distance = math.sqrt(
                (x - 100) ** 2 + (y - 100) ** 2 + (depth * 50) ** 2
            )
            self.assertAlmostEqual(distance, 50, places=7)

    def test_horizontal_trace_separates_octaves_and_keeps_la_at_first_row(self) -> None:
        analysis = build_cycle_analysis(max_octaves=2)
        la_point = next(
            point
            for point in analysis.points
            if point.temperament == Series.PURE_FIFTHS.value
            and point.starting_note == "La"
            and point.step_number == 0
        )
        la_next_octave = replace(
            la_point,
            octave_number=la_point.octave_number + 1,
            frequency_hz=la_point.frequency_hz * 2,
            log2_frequency=la_point.log2_frequency + 1,
        )
        si_frequency = REFERENCE_HZ * 2 ** (2 / 12)
        si_point = replace(
            la_point,
            note="Si",
            frequency_hz=si_frequency,
            log2_frequency=math.log2(si_frequency),
        )

        la_x, la_y = horizontal_trace_coordinates(la_point, octave_min=4)
        next_octave_x, next_octave_y = horizontal_trace_coordinates(
            la_next_octave, octave_min=4
        )
        si_x, si_y = horizontal_trace_coordinates(si_point, octave_min=4)

        self.assertEqual(next_octave_x - la_x, 90)
        self.assertEqual(next_octave_y, la_y)
        self.assertEqual(si_x, la_x)
        self.assertAlmostEqual(si_y - la_y, 2 * 42)

    def test_horizontal_trace_uses_frequency_deviation_in_cents(self) -> None:
        analysis = build_cycle_analysis(max_octaves=6)
        points = {
            (point.temperament, point.step_number): point
            for point in analysis.points
        }
        pure_step_1 = points[(Series.PURE_FIFTHS.value, 1)]
        equal_step_1 = points[(Series.EQUAL_FIFTHS.value, 1)]
        pure_step_9 = points[(Series.PURE_FIFTHS.value, 9)]
        equal_step_9 = points[(Series.EQUAL_FIFTHS.value, 9)]

        pure_y, equal_y = (
            horizontal_trace_coordinates(point, octave_min=4)[1]
            for point in (pure_step_1, equal_step_1)
        )
        pure_y_later, equal_y_later = (
            horizontal_trace_coordinates(point, octave_min=4)[1]
            for point in (pure_step_9, equal_step_9)
        )
        expected_step_1_delta = math.log2(
            pure_step_1.frequency_hz / equal_step_1.frequency_hz
        ) * 1200 * 42 / 100
        expected_step_9_delta = math.log2(
            pure_step_9.frequency_hz / equal_step_9.frequency_hz
        ) * 1200 * 42 / 100

        self.assertAlmostEqual(pure_y - equal_y, expected_step_1_delta)
        self.assertAlmostEqual(pure_y_later - equal_y_later, expected_step_9_delta)
        self.assertGreater(abs(pure_y_later - equal_y_later), abs(pure_y - equal_y))

    def test_compressed_octave_axis_preserves_event_context_and_shrinks_empty_gaps(self) -> None:
        positions = compressed_octave_positions(
            4,
            20,
            {4, 12, 20},
            left=72,
            octave_width=90,
            compressed_width=11,
            context_octaves=1,
        )

        self.assertEqual(positions[5] - positions[4], 90)
        self.assertEqual(positions[6] - positions[5], 90)
        self.assertEqual(positions[9] - positions[8], 11)
        self.assertEqual(positions[12] - positions[11], 90)
        self.assertEqual(positions[13] - positions[12], 90)
        self.assertLess(positions[20] - positions[4], 16 * 90)

    def test_horizontal_trace_marks_origins_for_both_calibrations(self) -> None:
        analysis = build_cycle_analysis()
        grouped = {
            (point.temperament, point.starting_note): [
                candidate
                for candidate in analysis.points
                if candidate.temperament == point.temperament
                and candidate.starting_note == point.starting_note
            ]
            for point in analysis.points
            if point.starting_note == "La"
        }

        class CanvasProbe:
            def __init__(self) -> None:
                self.height = 550
                self.settings: dict[str, object] = {}
                self.ovals: list[tuple[float, ...]] = []
                self.oval_details: list[
                    tuple[tuple[float, ...], dict[str, object]]
                ] = []
                self.rectangles: list[tuple[float, ...]] = []
                self.rectangle_details: list[
                    tuple[tuple[float, ...], dict[str, object]]
                ] = []
                self.polygons: list[tuple[tuple[float, ...], dict[str, object]]] = []
                self.lines: list[tuple[tuple[float, ...], dict[str, object]]] = []
                self.texts: list[tuple[tuple[object, ...], dict[str, object]]] = []

            def delete(self, *_args: object) -> None:
                pass

            def configure(self, **_kwargs: object) -> None:
                self.settings.update(_kwargs)

            def xview_moveto(self, _fraction: float) -> None:
                pass

            def yview_moveto(self, _fraction: float) -> None:
                pass

            def winfo_height(self) -> int:
                return self.height

            def create_line(self, *coordinates: float, **options: object) -> None:
                self.lines.append((coordinates, options))

            def create_text(self, *coordinates: object, **options: object) -> None:
                self.texts.append((coordinates, options))

            def create_oval(
                self, *coordinates: float, **options: object
            ) -> None:
                self.ovals.append(coordinates)
                self.oval_details.append((coordinates, options))

            def create_rectangle(
                self, *coordinates: float, **options: object
            ) -> None:
                self.rectangles.append(coordinates)
                self.rectangle_details.append((coordinates, options))

            def create_polygon(
                self, *coordinates: float, **options: object
            ) -> None:
                self.polygons.append((coordinates, options))

        canvas = CanvasProbe()
        octave_min = min(point.octave_number for point in analysis.points)
        octave_max = max(point.octave_number for point in analysis.points)
        event_octaves = {
            point.octave_number
            for point in analysis.points
            if point.temperament == Series.PURE_FIFTHS.value and point.step_number == 1
        }
        octave_positions = compressed_octave_positions(octave_min, octave_max, event_octaves)
        closest_point = next(
            point for point in analysis.points
            if point.temperament == Series.PURE_FIFTHS.value and point.step_number == 1
        )
        common_multiple_pair = analysis.integer_multiple_pairs[0]
        event_tags = {id(closest_point): ("multiple", "closest")}
        MusicCircleApp._draw_horizontal_trace(
            canvas,
            grouped,
            octave_min,
            octave_max,
            "La",
            event_tags,
            octave_positions,
            (common_multiple_pair,),
        )

        origin_x, _ = horizontal_trace_coordinates(
            grouped[(Series.PURE_FIFTHS.value, "La")][0],
            octave_min,
            left=72,
            top=48,
        )
        equal_origin_x, _ = horizontal_trace_coordinates(
            grouped[(Series.EQUAL_FIFTHS.value, "La")][0],
            octave_min,
            left=72,
            top=48,
        )
        closest_x, _ = horizontal_trace_coordinates(
            closest_point, octave_min, top=48, octave_positions=octave_positions
        )
        closest_ring = next(
            coordinates
            for coordinates, options in canvas.oval_details
            if coordinates[2] - coordinates[0] == 16
            and abs((coordinates[0] + coordinates[2]) / 2 - closest_x) < 0.01
            and options.get("outline") == EVENT_COLORS["multiple"]
        )
        closest_y = (closest_ring[1] + closest_ring[3]) / 2
        matching_equal_point = next(
            point
            for point in analysis.points
            if point.temperament == Series.EQUAL_FIFTHS.value
            and point.step_number == closest_point.step_number
        )
        self.assertIn(
            (closest_x - 8, closest_y - 8, closest_x + 8, closest_y + 8),
            canvas.ovals,
        )
        self.assertIn(
            (closest_x - 11, closest_y - 11, closest_x + 11, closest_y + 11),
            canvas.ovals,
        )
        origin_oval = next(
            coordinates
            for coordinates, options in canvas.oval_details
            if options.get("fill") == CYCLE_COLORS[Series.PURE_FIFTHS.value]
            and coordinates[2] - coordinates[0] == 6
            and abs((coordinates[0] + coordinates[2]) / 2 - origin_x) < 0.01
        )
        equal_origin_rectangle = next(
            coordinates
            for coordinates, options in canvas.rectangle_details
            if options.get("outline") == CYCLE_COLORS[Series.EQUAL_FIFTHS.value]
            and coordinates[2] - coordinates[0] == 14
            and abs((coordinates[0] + coordinates[2]) / 2 - equal_origin_x) < 0.01
        )
        self.assertAlmostEqual(
            (origin_oval[1] + origin_oval[3]) / 2,
            (equal_origin_rectangle[1] + equal_origin_rectangle[3]) / 2,
        )
        pure_step_x, pure_step_y = horizontal_trace_coordinates(
            closest_point, octave_min, top=48, octave_positions=octave_positions
        )
        equal_step_x, equal_step_y = horizontal_trace_coordinates(
            matching_equal_point,
            octave_min,
            top=48,
            octave_positions=octave_positions,
        )
        pure_marker = next(
            coordinates
            for coordinates, options in canvas.oval_details
            if options.get("fill") == "#c2410c"
            and coordinates[2] - coordinates[0] == 6
            and coordinates[0] <= pure_step_x <= coordinates[2]
            and abs((coordinates[1] + coordinates[3]) / 2 - closest_y) < 0.01
        )
        equal_marker = next(
            coordinates
            for coordinates, options in canvas.rectangle_details
            if options.get("fill") == "#075985"
            and coordinates[2] - coordinates[0] == 6
            and coordinates[0] <= equal_step_x <= coordinates[2]
        )
        amplified_gap = abs(
            (pure_marker[1] + pure_marker[3] - equal_marker[1] - equal_marker[3])
            / 2
        )
        grid_y_positions = sorted(
            coordinates[1]
            for coordinates, options in canvas.lines
            if options.get("fill") == "#e1e6ec"
        )
        vertical_scale = (grid_y_positions[1] - grid_y_positions[0]) / 42
        self.assertAlmostEqual(
            amplified_gap,
            abs(pure_step_y - equal_step_y)
            * TRACE_SEPARATION_SCALE
            * vertical_scale,
        )
        scroll_region = canvas.settings["scrollregion"]
        self.assertLessEqual(scroll_region[3], canvas.height)
        self.assertTrue(
            all(
                0 <= coordinates[1] <= canvas.height
                for coordinates, _ in canvas.texts
                if isinstance(coordinates[1], (int, float))
            )
        )
        pure_lines = [
            options for _, options in canvas.lines if options.get("fill") == "#c2410c"
        ]
        equal_lines = [
            options for _, options in canvas.lines if options.get("fill") == "#075985"
        ]
        self.assertTrue(pure_lines)
        self.assertTrue(equal_lines)
        self.assertTrue(canvas.polygons)
        self.assertTrue(
            all(
                options.get("stipple") == "gray50"
                for _, options in canvas.polygons
            )
        )
        self.assertTrue(
            all(
                options.get("fill") in CYCLE_COLORS.values()
                for _, options in canvas.polygons
            )
        )
        event_ring_colors = {
            options.get("outline")
            for _, options in canvas.oval_details
            if options.get("outline") in EVENT_COLORS.values()
        }
        self.assertIn(EVENT_COLORS["multiple"], event_ring_colors)
        self.assertIn(EVENT_COLORS["closest"], event_ring_colors)
        self.assertEqual(
            sum(
                options.get("fill") == EVENT_COLORS["common_multiple"]
                for _, options in canvas.lines
            ),
            1,
        )
        self.assertTrue(all(options.get("dash") == () for options in pure_lines))
        self.assertTrue(all(options.get("dash") == (5, 3) for options in equal_lines))
        self.assertEqual(origin_x, equal_origin_x)
        self.assertAlmostEqual(
            (origin_oval[1] + origin_oval[3]) / 2,
            (equal_origin_rectangle[1] + equal_origin_rectangle[3]) / 2,
        )
        legend_rows = [
            coordinates[1]
            for coordinates, options in canvas.texts
            if options.get("text") in (
                "Quintes pures — trait continu, cercle",
                "Quintes tempérées — trait discontinu, carré",
            )
        ]
        self.assertEqual(len(legend_rows), 2)
        self.assertEqual(legend_rows[1] - legend_rows[0], 24)


class NovemberUpdateTests(unittest.TestCase):
    """Alignement du programme sur l'application web (novembre 2026)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.analysis = build_cycle_analysis()

    def test_reference_counts_are_unchanged(self) -> None:
        analysis = self.analysis
        self.assertEqual(len(analysis.points), 412)
        self.assertEqual(analysis.comparisons, 84666)
        self.assertEqual(len(analysis.unisons), 1)
        self.assertEqual(len(analysis.cross_temperament_unisons), 1)
        self.assertEqual(len(analysis.corresponding_fifths), 206)

    def test_octave_equivalences_are_counted_as_integer_ratios(self) -> None:
        analysis = self.analysis
        self.assertEqual(len(analysis.cross_temperament_octave_matches), 17)
        self.assertEqual(len(analysis.cross_temperament_integer_multiples), 17)
        self.assertEqual(len(analysis.internal_integer_multiples), 523)
        self.assertEqual(len(analysis.integer_multiple_pairs), 540)
        self.assertEqual(
            len(analysis.integer_multiple_pairs),
            len(set(analysis.integer_multiple_pairs)),
        )
        for pair in analysis.cross_temperament_octave_matches:
            self.assertIn(pair, analysis.cross_temperament_integer_multiples)
            self.assertIn(pair, analysis.integer_multiple_pairs)

    def test_cross_comparisons_count_pure_against_tempered_pairs(self) -> None:
        pure = sum(1 for point in self.analysis.points if point.temperament == Series.PURE_FIFTHS.value)
        equal = len(self.analysis.points) - pure
        self.assertEqual(self.analysis.cross_comparisons, pure * equal)
        self.assertEqual(self.analysis.cross_comparisons, 42436)

    def test_very_large_power_of_two_is_written_as_power(self) -> None:
        pair = max(
            self.analysis.cross_temperament_octave_matches,
            key=lambda item: abs(item.second.log2_frequency - item.first.log2_frequency),
        )
        shift = round(pair.second.log2_frequency - pair.first.log2_frequency)
        multiple = pair_integer_multiple(pair.first, pair.second)
        self.assertEqual(multiple, 2 ** abs(shift))
        self.assertEqual(format_multiple(2**60), "2^60")
        self.assertEqual(format_multiple(2**10), "1024")
        self.assertEqual(format_multiple(3 * 2**45), str(3 * 2**45))
        report = MusicCircleApp._format_integer_multiple(pair)
        self.assertIn("Rapport de fréquences", report)

    def test_pair_integer_multiple_ignores_internal_pairs_without_exact_ratio(self) -> None:
        first = self.analysis.points[0]
        same_series = next(
            point for point in self.analysis.points[1:] if point.temperament == first.temperament
        )
        self.assertEqual(
            pair_integer_multiple(first, same_series),
            integer_frequency_multiple(first.frequency_hz, same_series.frequency_hz),
        )

    def test_without_pure_tonic_removes_only_its_pairs(self) -> None:
        reduced = without_pure_tonic(self.analysis)
        self.assertEqual(len(reduced.points), 412)
        self.assertEqual(reduced.comparisons, 84255)
        self.assertEqual(reduced.cross_comparisons, 42230)
        self.assertEqual(len(reduced.unisons), 0)
        self.assertEqual(len(reduced.cross_temperament_unisons), 0)
        self.assertEqual(len(reduced.corresponding_fifths), 205)
        self.assertEqual(len(reduced.cross_temperament_octave_matches), 0)
        self.assertEqual(len(reduced.cross_temperament_integer_multiples), 0)
        self.assertEqual(len(reduced.internal_integer_multiples), 523)
        self.assertEqual(len(reduced.integer_multiple_pairs), 523)
        # L'analyse d'origine n'est pas modifiée.
        self.assertEqual(self.analysis.comparisons, 84666)
        for pair in reduced.corresponding_fifths:
            for point in (pair.first, pair.second):
                self.assertFalse(
                    point.temperament == Series.PURE_FIFTHS.value and point.step_number == 0
                )


if __name__ == "__main__":
    unittest.main()
