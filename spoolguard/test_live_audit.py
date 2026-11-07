"""Mutation tests against captured evidence; does not start Docker."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from audit_live import audit


class EvidenceAudit(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parent
        work=root.parents[1]/"work"
        work.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=work,prefix="audit-test-")
        self.folder=Path(self.temp.name)
        for name in ["live-results.json","send-traces.json","snapshot-before.json","snapshot-after.json"]:
            shutil.copyfile(root/"live-evidence"/name,self.folder/name)

    def tearDown(self):
        self.temp.cleanup()

    def change(self,name,fn):
        p=self.folder/name
        data=json.loads(p.read_text())
        fn(data)
        p.write_text(json.dumps(data))

    def test_captured_evidence_passes(self):
        self.assertTrue(audit(self.folder)["passed"])

    def test_detects_send_after_expiry(self):
        expiry=json.loads((self.folder/"live-results.json").read_text())["expiry_ns"]
        self.change("send-traces.json",lambda t:t["fanout_aware"]["payments"][-1].update(send_ns=expiry))
        self.assertFalse(audit(self.folder)["passed"])

    def test_detects_rate_contract_violation(self):
        def alter(t):
            events=t["fanout_aware"]["payments"]
            for event in events[:4]: event["send_ns"]=events[0]["send_ns"]
        self.change("send-traces.json",alter)
        self.assertFalse(audit(self.folder)["passed"])

    def test_detects_mismatched_ack_fanout(self):
        def alter(snapshot):
            q=next(q for q in snapshot["data"] if q["queueName"]=="lab-fanout_aware-orders")
            q["spooledMsgCount"]+=1
        self.change("snapshot-after.json",alter)
        self.assertFalse(audit(self.folder)["passed"])

    def test_detects_queue_peak_above_certificate(self):
        def alter(snapshot):
            q=next(q for q in snapshot["data"] if q["queueName"]=="lab-fanout_aware-archive")
            q["msgSpoolPeakUsage"]=9999999
        self.change("snapshot-after.json",alter)
        self.assertFalse(audit(self.folder)["passed"])


if __name__=="__main__":
    unittest.main()
