"""Synthetic plan reporting arithmetic and rejection cases; no host/model calls."""
import copy
import ast
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

    def test_recent_future_horizon_clips_half_open_boundaries_across_dst(self):
        html=ledger.render(fixture())
        recent=section_fragment(html,'recent')
        self.assertIn('03 Oct 2026 21:00 – 04 Oct 2026 06:00',recent)  # eight elapsed hours across the missing local hour
        self.assertIn('id="recent-task-10"',recent)
        self.assertIn('id="recent-task-11"',recent)
        self.assertIn('class="bar review projection"',recent)
        self.assertIn('Owner acceptance',recent)
        self.assertIn('clipped at window edge',recent)
        now_positions=re.findall(r'class="now" style="--x:([\d.]+)%"',recent)
        self.assertTrue(now_positions)
        self.assertEqual(set(now_positions),{'50.000000'})
        data=fixture()
        data['tasks'][11]['forecast'].update(start='2026-10-03T19:00:00Z',end='2026-10-03T20:00:00Z')
        boundary=copy.deepcopy(data['milestones'][1])
        boundary.update(id='edge',name='At excluded horizon boundary',target='2026-10-03T19:00:00Z')
        data['milestones'].append(boundary)
        recent=section_fragment(ledger.render(data),'recent')
        self.assertNotIn('id="recent-task-11"',recent)
        self.assertNotIn('At excluded horizon boundary',recent)
        short=section_fragment(ledger.render(fixture(),recent_hours=1),'recent')
        self.assertIn('04 Oct 2026 00:00 – 04 Oct 2026 03:00',short)
        self.assertNotIn('id="recent-task-10"',short)

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

    def test_waiting_events_and_handoffs_show_real_boundaries(self):
        html=ledger.render(fixture(), recent_hours=1)
        recent=section_fragment(html,'recent')
        self.assertIn('id="recent-task-9"',recent)
        self.assertIn('data-event="E2"',recent)
        self.assertNotIn('id="recent-task-10"',recent)  # starts exactly at window end
        paths=[dict(re.findall(r'([\w-]+)="([^"]*)"',p)) for p in re.findall(r'<path [^>]*class="handoff[^>]*>',html)]
        task9=next(p for p in paths if p.get('data-node')=='8')
        self.assertEqual(task9['class'],'handoff projected')
        self.assertAlmostEqual(float(task9['data-x']),1120/1320)
        self.assertFalse(any(p.get('data-node')=='9' for p in paths))
        self.assertLess(html.index('Scrollable timeline:'),html.index('class="chart-scroll"'))

    def test_model_colours_have_chart_contrast_in_both_themes(self):
        def luminance(colour):
            channels=[int(colour[i:i+2],16)/255 for i in (1,3,5)]
            linear=[x/12.92 if x<=0.04045 else ((x+0.055)/1.055)**2.4 for x in channels]
            return sum(a*b for a,b in zip(linear,(0.2126,0.7152,0.0722)))
        for selector,panel in [(r'\.report\{','#ffffff'),(r'\.report.dark\{','#202e40')]:
            block=re.search(selector+r'([^}]+)',ledger.CSS).group(1)
            colours=re.findall(r'--model-\d:(#[0-9a-f]{6})',block)
            self.assertEqual(len(colours),6)
            for colour in colours:
                a,b=sorted((luminance(colour),luminance(panel)))
                self.assertGreaterEqual((b+0.05)/(a+0.05),3,colour)

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

    def test_gantt_marks_scoped_events_rounds_and_decisions_are_data_driven(self):
        data = fixture()
        html = ledger.render(data)
        for element in ('id="whole"','id="recent"','class="baseline"','class="overrun',
                        'class="dependency"','class="handoff"','class="event-band"',
                        'class="now"','class="marker gate"','class="marker rebaseline"',
                        'class="bar build projection"','id="owner"','id="running"','id="events"',
                        'id="overruns"','id="recently-completed"','R2 · Reviewer B · high'):
            self.assertIn(element, html)
        self.assertLess(html.index('class="decision-strip"'), html.index('id="whole"'))
        first = html.split('id="whole-task-0"',1)[1].split('id="whole-task-1"',1)[0]
        self.assertNotIn('data-event="E1"', first)  # finished before provider outage
        affected = html.split('id="whole-task-3"',1)[1].split('id="whole-task-4"',1)[0]
        build, review = affected.split('class="chart-row lane review"',1)
        self.assertIn('data-event="E1"', build)
        self.assertNotIn('data-event="E1"', review)  # different provider
        for width_case in ('light','dark','auto'):
            self.assertIn(f'class="report {width_case}"', ledger.render(data, theme=width_case))

    def test_short_clipped_segments_long_names_and_untrusted_text_stay_readable(self):
        data = fixture()
        name = 'Very long model name ' * 12 + '<script>alert("x")</script>'
        data['tasks'][8]['segments'][0]['model'] = name
        data['tasks'][8]['title'] = 'Long task ' * 20
        data['tasks'][8]['segments'][0]['start'] = '2026-10-03T10:00:00Z'
        html = ledger.render(data)
        self.assertNotIn('<script>alert', html)
        self.assertIn('&lt;script&gt;alert', html)
        # Complete identity is in the label, independently of the thin/clipped bar.
        self.assertIn(f'<span class="lane-name">B · {ledger.esc(name)} · high</span>', html)
        self.assertIn('clipped at window edge', html)
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
            ]:
                data=fixture()
                mutate(data)
                path.write_text(json.dumps(data))
                result=subprocess.run(command,cwd=foreign,text=True,capture_output=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(expected,result.stderr)
                self.assertNotIn('Traceback',result.stderr)
                self.assertEqual(output.read_bytes(),saved)

    def test_renderer_syntax_is_compatible_with_minimum_python(self):
        source=(ROOT/'skills/plan-report/scripts/render.py').read_text()
        ast.parse(source, feature_version=(3,10))


if __name__ == "__main__":
    unittest.main()
