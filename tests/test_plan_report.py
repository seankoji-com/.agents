"""Synthetic plan reporting arithmetic and rejection cases; no host/model calls."""
import copy
import ast
from datetime import datetime, timezone
from html.parser import HTMLParser
import importlib.util
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("plan_ledger", ROOT / "skills/plan-report/scripts/render.py")
ledger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ledger)


def fixture():
    return json.loads((ROOT / "skills/plan-report/examples/long-run.json").read_text())


class Ledger(unittest.TestCase):
    def test_original_approved_allocations_calibrate_exactly(self):
        data = ledger.validate(fixture())
        result = ledger.calibration(data)
        build = result["groups"][("synthetic-build", "Builder A", "high", "build")]
        review = result["groups"][("synthetic-review", "Reviewer B", "high", "review")]
        self.assertEqual(build, dict(estimated_minutes=420, actual_minutes=630, ratio=1.5))
        self.assertEqual(review, dict(estimated_minutes=240, actual_minutes=270, ratio=1.125))
        self.assertEqual(result["rounds"][6], dict(task="T07", planned=1, actual=2))
        changed = next(x for x in result["comparisons"] if x["task"] == "T04" and x["kind"] == "build")
        self.assertEqual(changed, dict(task="T04", kind="build", comparable=False,
                                     estimated_minutes=60, actual_minutes=90))
        self.assertNotIn(("synthetic-build", "Builder C", "high", "build"), result["groups"])
        self.assertEqual(result["costs"][("synthetic-build", "Builder A")]["tokens"]["known"], 24000)
        self.assertAlmostEqual(result["costs"][("synthetic-review", "Reviewer B")]["usd"]["known"], 0.48)
        self.assertTrue(result["costs"][("synthetic-review", "Reviewer B")]["usd"]["estimated"])
        self.assertGreater(result["costs"][("synthetic-review", "Reviewer B")]["usd"]["missing"], 0)

    def test_effort_change_is_not_comparable_and_round_splits_count_once(self):
        data = fixture()
        task = data["tasks"][0]
        task["segments"][0]["effort"] = "low"
        split = copy.deepcopy(task["segments"][1])
        split.update(id="split", start="2026-10-03T00:00:00Z", end="2026-10-03T00:05:00Z")
        task["segments"].append(split)
        result = ledger.calibration(ledger.validate(data))
        self.assertFalse(next(x for x in result["comparisons"] if x["task"] == "T01" and x["kind"] == "build")["comparable"])
        self.assertNotIn(("synthetic-build", "Builder A", "low", "build"), result["groups"])
        self.assertEqual(result["rounds"][0]["actual"], 1)

    def test_rebaseline_preserves_original_and_unapproved_has_no_ratios(self):
        data = fixture()
        original = copy.deepcopy(data["tasks"][8]["baseline"])
        ledger.validate(data)
        self.assertEqual(data["tasks"][8]["baseline"], original)
        self.assertEqual(ledger.baseline_end(original).isoformat(), "2026-10-03T13:30:00+00:00")
        data["approval"] = None
        data["rebaselines"] = []
        self.assertEqual(ledger.calibration(ledger.validate(data))["groups"], {})

    def test_unknown_cost_and_task_total_attribution(self):
        data = fixture()
        task = data["tasks"][3]
        for segment in task["segments"]:
            segment["cost"] = {}
        task["cost"] = {"usd": dict(value=2, source="synthetic task receipt", basis="reported")}
        result = ledger.cost_totals(ledger.validate(data))
        self.assertEqual(result[("unattributed", "task total")]["usd"]["known"], 2)
        unknown = result[("synthetic-build", "Builder C")]["tokens"]
        self.assertEqual(unknown["sources"], [])
        self.assertEqual(unknown["missing"], 1)

    def test_invalid_dependency_reversed_segment_and_approved_baseline(self):
        for mutation, error in [
            (lambda d: d["tasks"][0]["dependencies"].append("missing"), "unknown dependency id: missing"),
            (lambda d: d["tasks"][0]["segments"][0].update(end="2026-10-02T21:00:00Z"), "ends before it starts"),
            (lambda d: d["tasks"][0].pop("baseline"), "missing approved baseline"),
            (lambda d: d["tasks"][0]["dependencies"].append("T02"), "dependency cycle"),
            (lambda d: d["tasks"][0]["segments"][0]["cost"].update(usd={"value": 3}), "source"),
            (lambda d: d["tasks"][0].update(cost={"usd":dict(value=1,source="synthetic",basis="reported")}), "both task and segment"),
            (lambda d: d["rebaselines"][0].update(approver=""), "approver"),
        ]:
            with self.subTest(error=error):
                data = fixture()
                mutation(data)
                with self.assertRaisesRegex(ValueError, error):
                    ledger.validate(data)

    def test_dst_display_and_elapsed_time_use_real_instants(self):
        before = ledger.display_time("2026-10-04T01:30:00+10:00")
        after = ledger.display_time("2026-10-04T03:30:00+11:00")
        self.assertEqual(before, "04 Oct 2026 01:30")
        self.assertEqual(after, "04 Oct 2026 03:30")
        self.assertEqual(ledger.segment_minutes(dict(start="2026-10-04T01:30:00+10:00", end="2026-10-04T03:30:00+11:00"),
                                               "2026-10-04T05:00:00+11:00"), 60)
        self.assertEqual(ledger.segment_minutes(dict(start="2026-04-05T01:30:00+11:00", end="2026-04-05T03:30:00+10:00"),
                                               "2026-04-05T05:00:00+10:00"), 180)

    def test_scoped_events_and_remaining_critical_path(self):
        data = ledger.validate(fixture())
        event = data["events"][1]
        self.assertTrue(ledger.event_affects(event, data["tasks"][9]))
        self.assertFalse(ledger.event_affects(event, data["tasks"][8]))
        self.assertEqual(ledger.critical_path(data), ["T09", "T10"])

    def test_long_dependency_chain_has_no_recursion_limit(self):
        data = fixture()
        template = data['tasks'][-1]
        data['tasks'] = []
        for i in range(1200):
            task = copy.deepcopy(template)
            task.update(id=str(i), dependencies=[str(i-1)] if i else [])
            data['tasks'].append(task)
        for name in ('events','milestones','needs_owner','decisions','rebaselines'):
            data[name] = []
        self.assertEqual(len(ledger.critical_path(ledger.validate(data))), 1200)


class Tables(HTMLParser):
    """Read visible cell text by section, independent of renderer formatting."""
    def __init__(self, html):
        super().__init__()
        self.sections, self.cells, self.row = [], {}, []
        self.cell = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section':
            self.sections.append(attrs.get('id'))
        if tag == 'td':
            self.cell = []
        if tag in {'small', 'br'} and self.cell is not None:
            self.cell.append(' ')

    def handle_endtag(self, tag):
        if tag == 'td':
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row:
            self.cells.setdefault(self.sections[-1], []).append(self.row)
            self.row = []
        if tag == 'section':
            self.sections.pop()

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def section_fragment(html, section_id):
    return re.search(r'<section id="'+section_id+r'"[^>]*>.*?</section>',html,re.S).group(0)


class Disclosures(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.sections, self.details, self.summaries = [], {}, {}
        self.current, self.depth = None, 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='section':
            self.current=attrs['id']
            self.sections.append(self.current)
        elif tag=='details':
            self.depth+=1
            self.details.setdefault(self.current,[]).append((attrs,self.depth))
        elif tag=='summary':
            self.summaries[self.current]=attrs

    def handle_endtag(self, tag):
        if tag=='details':
            self.depth-=1
        elif tag=='section':
            self.current=None


class Renderer(unittest.TestCase):
    def test_running_table_has_stakeholder_value_and_legacy_fallback(self):
        data = fixture()
        active = [t for t in data['tasks'] if any(s.get('end') is None for s in t['segments'])]
        active[0]['value'] = 'Customers can resume interrupted work <safely>.'
        html = ledger.render(data)
        rows = Tables(html).cells['running']
        expected = [[s['model'], t['id'], t.get('value', t['title'])]
                    for t in active for s in t['segments'] if s.get('end') is None]
        self.assertEqual(rows, expected)
        self.assertEqual(re.findall(r'<th\b[^>]*>(.*?)</th>', section_fragment(html, 'running')),
                         ['Model', 'Task ID', 'Value'])
        self.assertNotIn('<safely>', html)
        active[0].pop('value')
        self.assertEqual(Tables(ledger.render(data)).cells['running'][0][-1], active[0]['title'])
        for invalid in ('', None, 7):
            active[0]['value'] = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'value'):
                ledger.render(data)

    def test_completion_history_is_omitted_only_in_report_mode(self):
        for mode in ('propose', 'report', 'final'):
            self.assertEqual('recently-completed' in Disclosures(ledger.render(fixture(), mode)).sections,
                             mode != 'report')

    def test_renderer_clock_rejects_future_but_accepts_history_and_marks_fixture_override(self):
        data = fixture()
        boundary = ledger.timestamp(data['project']['as_of'])
        with mock.patch.object(ledger, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = boundary
            ledger.render(data)  # equality at the real observed boundary is allowed
            clock.now.return_value = ledger.timestamp('2026-10-03T14:59:59Z')
            with self.assertRaisesRegex(ValueError, 'as_of.*future'):
                ledger.render(data)
            html = ledger.render(data, allow_future_fixture=True)
            self.assertIn('Synthetic fixture', html)
            self.assertIn('not live evidence', html)
        self.assertNotIn('Synthetic fixture', ledger.render(fixture()))

    def test_one_row_keeps_gaps_and_stacks_overlap_with_every_identity(self):
        data = fixture()
        task = data['tasks'][0]
        task.update(status='done', dependencies=[])
        task['segments'] = [
            dict(task['segments'][0], id='build-a', start='2026-10-03T00:00:00Z', end='2026-10-03T00:30:00Z'),
            dict(task['segments'][1], id='review-a', start='2026-10-03T00:30:00Z', end='2026-10-03T01:00:00Z'),
            dict(task['segments'][0], id='build-gap', start='2026-10-03T02:00:00Z', end='2026-10-03T03:00:00Z'),
            dict(task['segments'][1], id='review-overlap', start='2026-10-03T02:15:00Z', end='2026-10-03T02:45:00Z', model='Reviewer overlap'),
        ]
        data['tasks'] = [task]
        for collection in ('milestones', 'events', 'decisions', 'rebaselines', 'needs_owner'):
            data[collection] = []
        html = section_fragment(ledger.render(data, 'final'), 'whole')
        self.assertEqual(html.count('class="chart-row task-row'), 1)
        self.assertIn('--lanes:1', html)
        bars = re.findall(r'<span class="bar (build|review)[^"]*" style="--x:([\d.]+)%;--w:([\d.]+)%;--lane:(\d)', html)
        self.assertEqual([(b[0], b[3]) for b in bars], [('build', '0'), ('review', '0'), ('build', '0'), ('review', '1')])
        first, second, third, overlap = bars
        self.assertAlmostEqual(float(first[1])+float(first[2]), float(second[1]), places=3)
        self.assertLess(float(second[1])+float(second[2]), float(third[1]))
        self.assertGreater(float(overlap[1]), float(third[1]))
        self.assertLess(float(overlap[1])+float(overlap[2]), float(third[1])+float(third[2]))
        for segment in task['segments']:
            self.assertIn(segment['model'], html)

    def test_active_forecasts_show_eta_and_dashed_build_and_review_shares(self):
        recent = section_fragment(ledger.render(fixture()), 'recent')
        self.assertIn('class="eta"', recent)
        self.assertIn('title="ETA 04 Oct 2026 04:30">04:30</span>', recent)
        running = recent.split('id="recent-task-8"', 1)[1].split('id="recent-task-10"', 1)[0]
        self.assertIn('class="bar build open"', running)
        self.assertIn('class="bar build projection"', running)
        self.assertIn('class="bar review projection"', running)
        self.assertIn('dashed', re.search(r'\.bar\.projection\{([^}]+)', ledger.CSS).group(1))

    def test_forecast_build_keeps_the_model_that_is_building_now(self):
        task = fixture()['tasks'][8]
        task['segments'][0].update(model='Builder C')
        projected = ledger.projection(task, ledger.timestamp('2026-10-03T15:00:00Z'))
        self.assertEqual([(s['kind'], s['model']) for s in projected], [('build', 'Builder C'), ('review', 'Reviewer B')])

    def test_whole_run_only_at_run_boundaries_and_links_resolve(self):
        for mode in ('propose', 'report', 'final'):
            with self.subTest(mode=mode):
                html = ledger.render(fixture(), mode)
                sections = Disclosures(html).sections
                self.assertEqual('whole' in sections, mode != 'report')
                self.assertIn('recent', sections)
                ids = set(re.findall(r'\bid="([^"]+)"', html))
                for target in re.findall(r'href="#([^"]+)"', html):
                    self.assertIn(target, ids)

    def test_empty_disclosures_are_omitted_but_populated_ones_remain(self):
        data = fixture()
        data['approval'] = None
        for name in ('events', 'milestones', 'needs_owner', 'decisions', 'rebaselines'):
            data[name] = []
        task = data['tasks'][-1]
        task.update(dependencies=[], segments=[], status='planned')
        task.pop('baseline', None)
        task.pop('cost', None)
        task.pop('issues', None)
        task.pop('prs', None)
        data['tasks'] = [task]
        absent = {'owner', 'running', 'overruns', 'events', 'recently-completed',
                  'milestones', 'rebaselines', 'original', 'calibration',
                  'by-model', 'by-effort', 'by-kind', 'not-comparable'}
        for mode in ('propose', 'report', 'final'):
            with self.subTest(mode=mode):
                html = ledger.render(data, mode)
                self.assertFalse(absent.intersection(Disclosures(html).sections))
                self.assertNotIn('None recorded', html)
        task['issues'] = ['synthetic issue 7']
        html = ledger.render(data)
        self.assertIn('original', Disclosures(html).sections)
        self.assertIn('synthetic issue 7', Tables(html).cells['original'][0][-1])
        data['events'] = fixture()['events'][:1]
        data['events'][0]['scope'] = {'all': True}
        self.assertIn('events', Disclosures(ledger.render(data)).sections)

    def test_recent_first_and_each_following_section_independently_closed(self):
        data=fixture()
        before=copy.deepcopy(data)
        metrics=ledger.calibration(data)
        html=ledger.render(data,'final')
        layout=Disclosures(html)
        self.assertEqual(layout.sections, ['recent','whole','owner','running','overruns','events',
                                          'recently-completed','milestones','rebaselines','original',
                                          'calibration','by-model','by-effort','by-kind','not-comparable',
                                          'review-rounds','costs'])
        self.assertNotIn('recent',layout.details)
        for section in layout.sections[1:]:
            self.assertEqual(layout.details[section], [({},1)],section)
            self.assertEqual(layout.summaries[section], {},section)  # native focus/keyboard, no role overrides
        self.assertEqual(data,before)
        self.assertEqual(ledger.calibration(data),metrics)
        tables=Tables(html).cells
        self.assertEqual(tables['calibration'][0][3:],[ '420','630','1.5×'])
        self.assertEqual(len(tables['original']),12)
        self.assertIn('id="whole-task-8"',section_fragment(html,'whole'))
        self.assertIn('href="#whole-task-8"',html)

    def test_progress_view_hides_finished_work_and_starts_at_oldest_open_task(self):
        html = ledger.render(fixture())
        recent = section_fragment(html, 'recent')
        self.assertIn('<h2>Remaining work</h2>', recent)
        self.assertIn('03 Oct 2026 21:50 – 04 Oct 2026 07:10', recent)  # ten minutes either side, across the missing local hour
        shown = set(re.findall(r'id="recent-task-(\d+)"', recent))
        self.assertEqual(shown, {'8', '9', '10', '11'})
        self.assertIn('3 finished hidden', recent)
        self.assertEqual(recent.count('class="now"'), 1)
        self.assertIn('Owner acceptance', recent)
        self.assertNotIn('Contract accepted', recent)
        self.assertIn('>after Exercise recovery</span>', recent)
        self.assertIn('<strong>67%</strong> of estimated work done · 12.0h of 18.0h', html)
        for removed in ('class="baseline"', 'class="overrun', 'event-band', '<svg', 'class="dependency"'):
            self.assertNotIn(removed, html)

    def test_progress_view_falls_back_to_recent_work_when_nothing_remains(self):
        data = fixture()
        data['tasks'][8].update(status='done')
        data['tasks'][8]['segments'][0]['end'] = '2026-10-03T14:30:00Z'
        for task in data['tasks'][9:]:
            task['status'] = 'cancelled'
        data['decisions'] = data['decisions'][:1]
        recent = section_fragment(ledger.render(data), 'recent')
        self.assertIn('<h2>Recent work</h2>', recent)
        self.assertEqual(set(re.findall(r'id="recent-task-(\d+)"', recent)), {'7', '8'})  # ended inside the four-hour lookback
        self.assertIn('clipped at window edge', recent)
        quiet = section_fragment(ledger.render(data, recent_hours=0.25), 'recent')
        self.assertNotIn('id="recent-task-', quiet)
        self.assertIn('Project total', quiet)

    def test_local_labels_omit_zone_suffixes_but_preserve_source_offsets(self):
        data=fixture()
        before=copy.deepcopy(data)
        html=ledger.render(data,'final')
        self.assertNotRegex(html,r'AEST|AEDT|UTC[+-]|Australia/Sydney')
        self.assertIn('As of <strong>04 Oct 2026 01:00</strong>',html)
        self.assertIn('title="As of 04 Oct 2026 01:00"',html)
        self.assertEqual(data,before)
        data['decisions'][0]['source']='Synthetic source UTC+1000 (literal evidence label)'
        self.assertIn('Synthetic source UTC+1000',ledger.render(data,'final'))

    def test_decision_record_shows_real_answer_and_pending_without_recommendation_as_answer(self):
        data=fixture()
        before=copy.deepcopy(data)
        html=ledger.render(data,'final')
        self.assertNotIn('Needs the owner',html)
        self.assertIn('<h2>Decision record</h2>',html)
        rows=Tables(html).cells['owner']
        self.assertEqual(rows[0][1],'Decided')
        self.assertIn('Use online migration with no planned downtime.',rows[0][2])
        self.assertEqual(rows[0][3],'Asked: 03 Oct 2026 09:40 Decided: 03 Oct 2026 10:00')
        self.assertIn('T03, T07',rows[0][4])
        self.assertEqual(rows[1][1:3],['Awaiting answer','unknown'])
        self.assertIn('Recommendation: Keep 30 days',rows[1][0])
        self.assertIn('Decided: unknown',rows[1][3])
        self.assertEqual(data,before)
        reply=dict(data['decisions'][1], status='decided',answer='Keep seven days.',decided_at='2026-10-03T14:00:00Z')
        data['decisions'].append(reply)
        html=ledger.render(data,'final')
        rows=Tables(html).cells['owner']
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[1][1:3],['Earlier question','unknown'])
        self.assertEqual(rows[2][1:3],['Decided','Keep seven days.'])
        self.assertNotIn('class="decision-strip"',html)
        data['decisions'].append(dict(data['decisions'][0],answer='Use an offline migration.',decided_at='2026-10-03T14:30:00Z'))
        rows=Tables(ledger.render(data,'final')).cells['owner']
        self.assertEqual(rows[0][1],'Earlier decision')
        self.assertIn('no planned downtime',rows[0][2])
        self.assertTrue(rows[-1][2].startswith('Use an offline migration.'))

    def test_legacy_question_data_does_not_invent_a_decision(self):
        data=fixture()
        data.pop('decisions')
        data['needs_owner']=[dict(question='Legacy choice',owner='Synthetic owner',status='closed',tasks=['T10'],recommendation='Suggested only')]
        row=Tables(ledger.render(data,'final')).cells['owner'][0]
        self.assertEqual(row[1:4],['Answer not recorded','unknown','Asked: unknown Decided: unknown'])
        data['needs_owner'][0]['id']='legacy-choice'
        data['decisions']=[dict(id='legacy-choice',question='Legacy choice',owner='Synthetic owner',
                                status='decided',answer='Actual later reply',tasks=['T10'])]
        rows=Tables(ledger.render(data,'final')).cells['owner']
        self.assertEqual(rows[0][1:3],['Earlier question','unknown'])
        self.assertEqual(rows[1][1:3],['Decided','Actual later reply'])

    def test_decision_validation_rejects_fabricated_pending_answers_and_time_reversal(self):
        for change,error in [({'answer':'Keep 30 days'},'actual answer'),
                             ({'decided_at':'2026-10-03T14:00:00Z'},'pending decision'),
                             ({'status':'decided','answer':'Approved','decided_at':'2026-10-03T12:00:00Z'},'precedes question')]:
            with self.subTest(change=change):
                data=fixture()
                data['decisions'][1].update(change)
                with self.assertRaisesRegex(ValueError,error):
                    ledger.validate(data)

    def test_axis_cuts_idle_gaps_and_compresses_the_far_future(self):
        at = lambda hours: ledger.timestamp('2026-10-03T00:00:00Z') + ledger.timedelta(hours=hours)
        pieces, fraction = ledger.build_axis([(at(0), at(2)), (at(12), at(13))])
        self.assertEqual([p['kind'] for p in pieces], ['time', 'cut', 'time'])
        self.assertAlmostEqual(pieces[1]['x1'] - pieces[1]['x0'], 0.03)
        self.assertAlmostEqual(pieces[-1]['x1'], 1)
        marks = [fraction(at(h)) for h in (0, 1, 2, 7, 12, 13)]
        self.assertEqual(marks, sorted(marks))
        self.assertGreater(fraction(at(1)) - fraction(at(0)), 2 * (fraction(at(12)) - fraction(at(2))))  # 1h of work outweighs 10h idle
        self.assertEqual([p['kind'] for p in ledger.build_axis([(at(0), at(2)), (at(2.5), at(3))])[0]], ['time'])
        pieces, fraction = ledger.build_axis([(at(0), at(30))], squeeze_from=at(4))
        self.assertEqual([p['kind'] for p in pieces], ['time', 'far'])
        self.assertAlmostEqual(pieces[1]['x1'] - pieces[1]['x0'], ledger.FAR_SHARE)
        pieces, _ = ledger.build_axis([(at(0), at(5))], squeeze_from=at(4))
        self.assertEqual({p['kind'] for p in pieces}, {'time'})  # nothing to compress
        recent = section_fragment(ledger.render(fixture(), recent_hours=1), 'recent')
        self.assertIn('later, compressed', recent)
        self.assertNotIn('later, compressed', section_fragment(ledger.render(fixture(), 'propose'), 'recent').replace('title=', ''))

    def test_mtoks_column_reports_known_tokens_without_inventing_zero(self):
        key = ('synthetic-build', 'Builder A')
        self.assertEqual(ledger.mtoks({key: 24000}, 0), '0.02')
        self.assertEqual(ledger.mtoks({key: 171_300_000}, 0), '171.3')
        self.assertIn('&lt;0.01+', ledger.mtoks({key: 3000}, 2))
        self.assertIn('–', ledger.mtoks({}, 3))
        data = fixture()
        self.assertEqual(ledger.task_tokens(data['tasks'][0]), ({key: 3000}, 1))
        self.assertEqual(ledger.task_tokens(data['tasks'][11]), ({}, 0))
        task = data['tasks'][3]
        for segment in task['segments']:
            segment['cost'] = {}
        task['cost'] = {'tokens': dict(value=5_000_000, source='synthetic task receipt', basis='reported')}
        self.assertEqual(ledger.task_tokens(task), ({('unattributed', 'task total'): 5_000_000}, 0))
        whole = section_fragment(ledger.render(data, 'final'), 'whole')
        self.assertIn('>mtoks</div>', whole)
        row = whole.split('id="whole-task-3"', 1)[1].split('id="whole-task-', 1)[0]
        self.assertIn('<div class="cost">5.00</div>', row)
        total = whole.split('class="chart-row total"', 1)[1]
        self.assertIn('Project total', total)
        self.assertIn('<div class="cost"><span title="Known subtotal; 9 observations unreported">5.02+</span></div>', total)

    def test_issue_numbers_link_to_the_task_thread_and_reject_script_links(self):
        data = fixture()
        data['tasks'][8].update(title='#7 Exercise <recovery>, see #12', thread='https://example.test/threads/7')
        data['tasks'][10].update(thread='t3-thread://v2/synthetic/one')
        recent = section_fragment(ledger.render(data), 'recent')
        link = '<a href="https://example.test/threads/7">'
        self.assertIn(f'{link}#7</a> Exercise &lt;recovery&gt;, see {link}#12</a>', recent)
        self.assertIn('<a href="t3-thread://v2/synthetic/one">Accept release candidate</a>', recent)
        self.assertIn('>after #7</span>', recent)
        self.assertNotIn('T09 ·', re.sub(r'title="[^"]*"', '', recent))  # internal ids only on hover
        for bad in ('javascript:alert(1)', 'not a link', '', 7):
            data['tasks'][8]['thread'] = bad
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'thread'):
                ledger.render(data)

    def test_model_colours_follow_provider_and_keep_chart_contrast_in_both_themes(self):
        def luminance(colour):
            channels=[int(colour[i:i+2],16)/255 for i in (1,3,5)]
            linear=[x/12.92 if x<=0.04045 else ((x+0.055)/1.055)**2.4 for x in channels]
            return sum(a*b for a,b in zip(linear,(0.2126,0.7152,0.0722)))
        for family,(light,dark) in ledger.FAMILIES.items():
            self.assertEqual((len(set(light)),len(set(dark))),(4,4),family)
            for shades,panel in ((light,'#ffffff'),(dark,'#202e40')):
                for colour in shades:
                    a,b=sorted((luminance(colour),luminance(panel)))
                    self.assertGreaterEqual((b+0.05)/(a+0.05),3,(family,colour))
        identities={('claudeAgent','claude-fable-5-2'),('claudeAgent','claude-haiku-5-5'),('codex','gpt-6.1-sol'),
                    ('opencode','litellm/deepseek-v4.1-flash'),('synthetic-a','Model one'),('synthetic-b','Model two')}
        names,css=ledger.model_palette(identities)
        light=dict(re.findall(r'(--m\d):(#[0-9a-f]{6})',css.split('.report.dark')[0]))
        colour=lambda provider,model:light[names[(provider,model)][4:-1]]
        self.assertEqual(colour('claudeAgent','claude-fable-5-2'),ledger.FAMILIES['orange'][0][0])
        self.assertEqual(colour('claudeAgent','claude-haiku-5-5'),ledger.FAMILIES['orange'][0][1])
        self.assertEqual(colour('codex','gpt-6.1-sol'),ledger.FAMILIES['green'][0][0])
        self.assertEqual(colour('opencode','litellm/deepseek-v4.1-flash'),ledger.FAMILIES['blue'][0][0])
        self.assertEqual({colour('synthetic-a','Model one'),colour('synthetic-b','Model two')},
                         {ledger.FAMILIES['teal'][0][0],ledger.FAMILIES['pink'][0][0]})
        self.assertIn('.report.auto{',css)

    def test_distinct_efforts_and_unknown_identity_are_not_mixed(self):
        data=fixture()
        data['tasks'][0]['baseline']['allocations'][0]['effort']='low'
        data['tasks'][0]['segments'][0]['effort']='low'
        tables=Tables(ledger.render(data,'final')).cells
        self.assertEqual(tables['by-effort'], [['high','600','810','1.35×'], ['low','60','90','1.5×']])
        data['tasks'][0]['baseline']['allocations'][0]['model']='unknown'
        data['tasks'][0]['segments'][0]['model']='unknown'
        result=ledger.calibration(ledger.validate(data))
        self.assertFalse(next(r for r in result['comparisons'] if r['task']=='T01' and r['kind']=='build')['comparable'])

    def test_final_html_has_exact_calibration_and_known_unknown_costs(self):
        html = ledger.render(fixture(), 'final', 'light')
        tables = Tables(html).cells
        self.assertEqual(tables['calibration'], [
            ['Builder A synthetic-build', 'high', 'build', '420', '630', '1.5×'],
            ['Reviewer B synthetic-review', 'high', 'review', '240', '270', '1.125×']])
        self.assertEqual(tables['by-model'], [['synthetic-build / Builder A','420','630','1.5×'],
                                             ['synthetic-review / Reviewer B','240','270','1.125×']])
        self.assertEqual(tables['by-effort'], [['high','660','900','1.36364×']])
        self.assertEqual(tables['by-kind'], [['build','420','630','1.5×'], ['review','240','270','1.125×']])
        self.assertEqual(tables['review-rounds'][6], ['T07','1','2'])
        excluded = tables['not-comparable'][0]
        self.assertEqual(excluded[:3], ['T04','build','not comparable Identity changed'])
        self.assertIn('60 min', excluded[3])
        self.assertIn('Builder C', excluded[4])
        costs = {row[0]: row[1:] for row in tables['costs']}
        self.assertIn('$0.4800 known subtotal (host estimate)', costs['Reviewer B synthetic-review'][2])
        self.assertTrue(costs['Builder C synthetic-build'][2].startswith('unknown'))
        self.assertNotIn('id="calibration"', ledger.render(fixture(), 'report'))

    def test_chart_marks_rounds_targets_and_sections_are_data_driven(self):
        data = fixture()
        html = ledger.render(data, 'propose')
        for element in ('id="whole"','id="recent"','class="now"','class="marker gate"','class="marker milestone"',
                        'class="bar build projection"','class="pbar"','id="owner"','id="running"','id="events"',
                        'id="overruns"','id="recently-completed"','Review R2 · Reviewer B · high'):
            self.assertIn(element, html)
        self.assertLess(html.index('class="decision-strip"'), html.index('id="whole"'))
        whole = section_fragment(html, 'whole')
        self.assertEqual(len(re.findall(r'id="whole-task-\d+"', whole)), 12)
        self.assertEqual(whole.count('class="chart-row group"'), 3)
        self.assertNotIn('finished hidden', whole)
        for width_case in ('light','dark','auto'):
            self.assertIn(f'class="report {width_case}"', ledger.render(data, theme=width_case))

    def test_long_names_and_untrusted_text_stay_escaped_and_reachable(self):
        data = fixture()
        name = 'Very long model name ' * 12 + '<script>alert("x")</script>'
        data['tasks'][8]['segments'][0]['model'] = name
        data['tasks'][8]['title'] = 'Long task ' * 20
        html = ledger.render(data)
        self.assertNotIn('<script>alert', html)
        self.assertIn('&lt;script&gt;alert', html)
        # Complete identity is on the bar for hover and assistive tech, and in the key.
        self.assertIn(f'aria-label="Build B · {ledger.esc(name)} · high · synthetic-build', html)
        self.assertIn(f'{ledger.esc(name)} · synthetic-build</span>', html)
        self.assertIn('text-overflow:ellipsis', html)
        self.assertIn('overflow-wrap:anywhere', html)
        self.assertNotIn('<script src=', html)
        self.assertNotIn('<link ', html)

    def test_projection_covers_forecast_without_shrinking_or_doubling(self):
        task = fixture()['tasks'][8]
        projected = ledger.projection(task, ledger.timestamp('2026-10-03T15:00:00Z'))
        self.assertEqual([ledger.segment_minutes(s,'2026-10-04T00:00:00Z') for s in projected], [100,50])
        self.assertEqual(projected[0]['end'], projected[1]['start'])
        self.assertEqual(ledger.timestamp(projected[-1]['end']), ledger.timestamp(task['forecast']['end']))

    def test_single_file_relocation_and_cli_invalid_inputs_leave_output_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copied = root/'copied-render.py'
            shutil.copy2(ROOT/'skills/plan-report/scripts/render.py', copied)
            foreign = root/'foreign'
            foreign.mkdir()
            path, output = root/'ledger.json', root/'report.html'
            command = [sys.executable,str(copied),str(path),'--mode','final','--output',str(output)]
            path.write_text(json.dumps(fixture()))
            result = subprocess.run(command,cwd=foreign,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('Final calibration',output.read_text())
            saved = output.read_bytes()
            for mutate, expected in [
                (lambda d:d['tasks'][0]['dependencies'].append('absent'),'unknown dependency id: absent'),
                (lambda d:d['tasks'][0]['segments'][0].update(end='2026-10-02T00:00:00Z'),'ends before it starts'),
                (lambda d:d['tasks'][0].pop('baseline'),'missing approved baseline'),
                (lambda d:d['project'].update(as_of='2099-01-01T00:00:00Z'),'as_of is in the future'),
            ]:
                data=fixture()
                mutate(data)
                path.write_text(json.dumps(data))
                result=subprocess.run(command,cwd=foreign,text=True,capture_output=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(expected,result.stderr)
                self.assertNotIn('Traceback',result.stderr)
                self.assertEqual(output.read_bytes(),saved)
            replay = subprocess.run(command+['--allow-future-fixture'], cwd=foreign,
                                    text=True, capture_output=True)
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertIn('Synthetic fixture replay, not live evidence.', output.read_text())

    def test_renderer_syntax_is_compatible_with_minimum_python(self):
        source=(ROOT/'skills/plan-report/scripts/render.py').read_text()
        ast.parse(source, feature_version=(3,10))


if __name__ == "__main__":
    unittest.main()
