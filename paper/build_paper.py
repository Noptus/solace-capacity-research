"""Rebuild the review draft from recorded evidence. Requires reportlab/matplotlib."""
from pathlib import Path
import html
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Table,TableStyle,Image,Preformatted

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parent/"work"/"paper"
WORK.mkdir(parents=True,exist_ok=True)
BENCH=ROOT/"broker-capacity"
NAVY=colors.HexColor("#18354b")
TEAL="#1d7b73"
RUST="#bc604d"


def read(path):return json.loads(path.read_text())


def records(folder):
    result=[]
    if not read(folder/"completed.json")["all_passed"]:raise ValueError("study incomplete")
    for case in read(folder/"design.json"):
        row=read(folder/(case["id"]+".json"))
        if not row["all_accounting_checks_passed"]:raise ValueError("invalid evidence")
        result.append(row)
    return result


matrix=records(BENCH/"matrix-evidence")
rep=records(BENCH/"replication-evidence")
cache=records(BENCH/"cache-window-evidence")
models=read(BENCH/"matrix-model-results.json")
rep_summary=read(BENCH/"replication-summary.json")
cache_summary=read(BENCH/"cache-window-summary.json")
if len(matrix)+len(rep)+len(cache)!=20:raise ValueError("unexpected experiment count")

sdk=[]
for dirname in ['sdkperf-validated-evidence','sdkperf-followup-evidence','sdkperf-drain-evidence']:
    folder=BENCH/dirname
    terminal=folder/('completed.json' if (folder/'completed.json').exists() else 'failure.json')
    accepted=read(terminal)['completed']
    for name in accepted:
        r=read(folder/(name+'.json'))
        if not r['all_integrity_checks_passed']:raise ValueError('Invalid SDKPerf record')
        sdk.append(r)
if len(sdk)<6:raise ValueError('SDKPerf accepted evidence missing')

plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,
                     "axes.labelcolor":"#26333d","text.color":"#26333d",
                     "axes.edgecolor":"#9aa5ad","grid.color":"#e2e7ea",
                     "figure.facecolor":"white","savefig.facecolor":"white"})
fig,ax=plt.subplots(figsize=(6.7,2.9),layout="constrained")
for f,color,marker in [(1,TEAL,"o"),(4,RUST,"s")]:
    rr=sorted((r for r in matrix if r["case"]["split"]=="train" and r["case"]["fanout"]==f),key=lambda r:r["case"]["size"])
    ax.plot([r["case"]["size"]/1024 for r in rr],
            [r["steady_ack_messages_per_second"] for r in rr],
            marker=marker,color=color,label=f"Training: fanout {f}",linewidth=1.3)
tt=[r for r in matrix if r["case"]["split"]=="test"]
ax.scatter([r["case"]["size"]/1024 for r in tt],[r["steady_ack_messages_per_second"] for r in tt],
           color="#557da2",marker="D",s=45,label="Held out: fanout 2 or 3",zorder=4)
ax.set_xscale("log",base=2);ax.set_yscale("log")
ax.set_xticks([.25,4,8,32,64,128],["0.25","4","8","32","64","128"])
ax.set_xlabel("Payload size (KiB)");ax.set_ylabel("Interior ACK rate (messages/s)")
ax.grid(axis="y",which="major",linewidth=.6);ax.legend(frameon=False,fontsize=8.5)
fig.savefig(WORK/"matrix.png",dpi=240);plt.close(fig)

fig,axes=plt.subplots(1,2,figsize=(6.7,2.65),layout="constrained")
labels=["256\npair 1","2048\npair 1","256\npair 2","2048\npair 2"]
bar_colors=[TEAL,RUST,TEAL,RUST]
axes[0].bar(range(4),[r["count_over_30s_admission"] for r in cache_summary],color=bar_colors,width=.65)
axes[0].set_ylabel("Later-ACKed messages / 30 s")
axes[1].bar(range(4),[r["max_ack_ms"]/1000 for r in cache_summary],color=bar_colors,width=.65)
axes[1].set_ylabel("Maximum publisher ACK delay (s)")
for ax in axes:
    ax.set_xticks(range(4),labels,fontsize=8.5)
    ax.set_xlabel("End-to-end outstanding-message budget")
    ax.grid(axis="y",linewidth=.5);ax.set_axisbelow(True)
fig.savefig(WORK/"credit.png",dpi=240);plt.close(fig)

styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name="PaperTitle",fontName="Helvetica-Bold",fontSize=29,leading=32,textColor=NAVY,spaceAfter=12))
styles.add(ParagraphStyle(name="Sub",fontName="Helvetica",fontSize=15,leading=20,textColor=NAVY,spaceAfter=13))
styles.add(ParagraphStyle(name="Meta",fontName="Helvetica",fontSize=9,leading=13,textColor=colors.HexColor("#576978"),spaceAfter=12))
styles.add(ParagraphStyle(name="BodyPaper",fontName="Helvetica",fontSize=10.3,leading=15,spaceAfter=9))
styles.add(ParagraphStyle(name="HeadPaper",fontName="Helvetica-Bold",fontSize=17,leading=21,textColor=NAVY,spaceAfter=12))
styles.add(ParagraphStyle(name="SubheadPaper",fontName="Helvetica-Bold",fontSize=11,leading=15,textColor=NAVY,spaceBefore=5,spaceAfter=7))
styles.add(ParagraphStyle(name="CaptionPaper",fontName="Helvetica",fontSize=8.5,leading=11.5,textColor=colors.HexColor("#52616d"),spaceAfter=11))
styles.add(ParagraphStyle(name="ReferencePaper",fontName="Helvetica",fontSize=8.8,leading=12,spaceAfter=6))
styles.add(ParagraphStyle(name="EquationPaper",fontName="Courier",fontSize=9.3,leading=14,spaceBefore=3,spaceAfter=10))
story=[]
def p(text,style="BodyPaper"):story.append(Paragraph(text,styles[style]))
def head(text):p(text,"HeadPaper")
def sub(text):p(text,"SubheadPaper")
def eq(text):story.append(Preformatted(text,styles["EquationPaper"]))
def page():story.append(PageBreak())
def table(rows,widths):
    data=[[Paragraph(str(cell),styles["CaptionPaper"]) for cell in row] for row in rows]
    t=Table(data,colWidths=widths,hAlign="LEFT",repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e8eff3")),
        ("VALIGN",(0,0),(-1,-1),"TOP"),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),6),("LINEBELOW",(0,0),(-1,0),.6,colors.HexColor("#b2c0ca")),
        ("LINEBELOW",(0,1),(-1,-1),.3,colors.HexColor("#dce3e8"))]))
    story.append(t);story.append(Spacer(1,10))

p("When Message Rates Mislead","PaperTitle")
p("Telemetry, flow control and dependence uncertainty in event-driven trading infrastructure","Sub")
p("Working-paper draft, SDKPerf revision | 7 November 2026<br/>Independent research project. Author attribution and publication destination pending confirmation.","Meta")
sub("Abstract")
p("Can a small telemetry-derived work vector predict the capacity of a message broker across message sizes and fanouts? We investigate this on a disposable, resource-limited Solace Standard broker. Twenty initial workload cases include training, held-out combinations, repeats and credit controls. Simple predictors overestimate held-out acknowledgment rates by about 29-31%. Independent SDKPerf/JCSMP checks add CRC and per-stream order validation: low fixed rates track, while higher offers expose backpressure, quota rejection and completion-accounting artifacts. Repeats and queue diagnostics prevent interpreting a short-run rate as a stable hardware-capacity boundary. A classical sharp-coupling result explains why separate size/fanout averages can miss copy-byte work, and why separate signal/capture marginals may not identify even the sign of an illustrative net opportunity. The contribution is a reproducible diagnostic study and telemetry adapter, not a new performance law or an empirically profitable strategy.")
sub("Findings that survived the accounting checks")
for text in [
    "<b>Client configuration can dominate a benchmark.</b> Underfilling a 255-message SDK window produced about 1 message/s; a properly matched one-message SDK window reached about 196 messages/s in a separate control.",
    "<b>Received is not uniquely accepted.</b> SEMP guaranteed-ingress counts must be reconciled with rejected attempts and protocol retransmissions.",
    "<b>A simple point predictor is still unproven.</b> Payload/fanout models missed both unseen combinations, and large-message repeats changed materially.",
    "<b>Dependence is measurable work.</b> Equal marginal means can hide a 4.56-fold difference in copy-byte demand in a two-point example."]:
    p(text)
p("Scope: one ARM64 Docker environment, persistent SMF, no TLS or replay, short load intervals, Standard-edition limits. Publisher ACK delay is not exchange execution latency.","CaptionPaper")
page()

head("1. Measurement before prediction")
p("The broker image was Solace 10.26.9.13589, pinned by digest. Docker imposed a two-CPU quota, 3 GiB memory and 1 GiB shared memory. Separate host Node.js processes used solclientjs 10.18.3. Four publishers and one consumer per matching queue formed the main study. All workload queues were created in an isolated localhost broker and removed afterward.")
table([["Design component","Cases / configuration"],
       ["Training","8 combinations: payloads 256, 4,096, 32,768 and 131,072 bytes; fanout 1 or 4"],
       ["Held out","8,192 bytes / fanout 2; 65,536 bytes / fanout 3"],
       ["Main controls","Repeat 256-byte / fanout-1 case; increase completion credit from 2,048 to 4,096"],
       ["Follow-up","4 large-message replications; 4 alternating 256/2,048-credit cases"]],[120,384])
sub("Accounting gate")
p("For each accepted initial case, source sends equalled publisher ACKs, NACKs were zero, every matching consumer's count equalled the source count, each queue's spooled-message count reconciled, and all final queue usages were zero. SEMP's guaranteed-ingress delta reconciled with sends plus recorded SDK retransmissions. Main accepted cases had no publisher retransmissions. These initial checks do not verify individual identities or CRC; the subsequent SDKPerf study adds separate integrity checks (Section 4).")
sub("Bound the pipeline, but do not mistake the bound for capacity")
p("Cumulative publisher credits were issued from the minimum consumer receipt count across queues. With P publishers and outstanding budget W, each publisher's admission limit was floor((min(received) + W)/P). Therefore:")
eq("total source admissions <= min(consumer receipt counts) + W")
p("The invariant bounds messages still awaiting application receipt. It does not bound all retained spool bytes, because consumer ACKs can be batched after receipt. SDK windows remained at 255 and publisher retransmission timeouts were raised to 60 seconds in the main matrix, separating the base workload from default two-second retry effects. A wider-credit control did not materially change the small-message rate.")
sub("Telemetry scope")
p("SEMP queue collections were read at intervals of at least 30 seconds. VPN counters were sampled about every two seconds; container cgroup CPU readings were supplementary host telemetry, not SEMP. Later diagnostic runs added the schema-supported SEMP v1 message-spool detail reply. Root message counters, unique accepted work and delivered copies were kept distinct [1-4].")
page()

head("2. Small models and held-out errors")
p("The proposed work vector contains source-message count, source bytes, queue-copy count and copy bytes, with feature-specific terms to be added only when justified. Motivated by operational analysis and Roofline reasoning [5,6], the initial fit used payload/fanout metadata validated by SEMP counts. The candidate effective-demand model was nonnegative and deliberately small:")
eq("d(s,f) = a + b*s + c*f + e*s*f\npredicted rate = min(10,000, 1,000,000 / d(s,f))")
p("Here s is payload KiB and d is effective microseconds per source message. The edition ceiling was taken from documentation, not fitted to test labels. Comparisons included constant message rate, constant payload-byte rate, a two-limit Roofline form and reduced demand models. Parameters used training cases only. Holdout combinations were declared before collection; this was not an externally preregistered study.")
story.append(Image(str(WORK/"matrix.png"),width=504,height=218))
p("Figure 1. Rates in the fixed 5-25 second interior of the 30-second admission interval. Lines connect training configurations; diamonds are held out. These statistics are not certified stationary rates or unrestricted broker peaks.","CaptionPaper")
table([["Model","8 KiB / f=2 error","64 KiB / f=3 error"],
       ["Constant messages", "+51.8%", "+1,093.7%"],
       ["Constant payload bytes", "+32.6%", "+30.4%"],
       ["Two-limit Roofline", "+31.1%", "+28.9%"],
       ["Nonnegative joint work", "+31.1%", "+28.9%"]],[210,147,147])
p("The held-out observed rates were 1,256.7 and 159.8 messages/s. Positive errors overstate headroom. In this dataset, adding nonnegative fanout and copy-byte terms did not improve the selected least-squares fit: their fitted coefficients were zero. This is not evidence that fanout has no cost; it shows the proposed model did not resolve these measurements.","CaptionPaper")
page()

head("3. Pressure, variation and an error floor")
p("For 131,072-byte messages and fanout 1, the interior ACK statistic changed from 83.0 to 124.2 messages/s on repetition. With a fixed input vector and one deterministic prediction x, the best possible worst relative error across two observed rates l and h is:")
eq("min_x max(|x/l - 1|, |x/h - 1|) = (h-l)/(h+l)")
p("Equalizing the two errors gives x = 2lh/(l+h). These two observations alone impose a 19.9% minimum worst error on a single fixed prediction for that configuration. This is an algebraic statement about the observed pair, not a population-level statistical bound. Small-message repetition changed by only about 0.34%.")
sub("Outstanding-work experiment: 128 KiB, fanout 1")
story.append(Image(str(WORK/"credit.png"),width=504,height=199))
p("Figure 2. Two consecutive low/high-budget pairs. Left: admitted messages subsequently ACKed, divided by the 30-second admission duration; this is not completed-by-deadline throughput. Right: maximum observed publisher ACK delay. Pair order was fixed; there are only two pairs.","CaptionPaper")
p("Reducing the outstanding budget eightfold produced similar admitted totals within each pair, while maximum ACK delays were smaller in both low-budget cases. However, the experiment did not isolate a clean cache-to-disk mode switch. Both budgets reached nearly the same reported cache-usage ceiling and retained disk-spooled messages. The second high-budget run's interior consumer-receipt rate also differed greatly from its publisher-ACK statistic, exposing transients and batching.")
p("These observations do not justify a strong peak claim. Longer randomized runs and an explicit stationarity gate remain needed. The next section adds independent SDKPerf sequence/integrity checks and fixed-rate trials. TCP SRTT must remain distinct from the much longer application-level ACK delays observed here.")
page()

head("4. Independent SDKPerf: a second measurement path")
p(f"SDKPerf/JCSMP 10.30.3 ran natively on an ARM64 Java 17 runtime against the same pinned broker image and Docker limits. {len(sdk)} cases passed send/ACK, SEMP-attempt, receive, CRC, per-stream sequence and drain gates. Each requested 60 seconds of messages; fixed-count publishers could take longer when backpressured. Distinct source stream IDs were essential. Higher-load failures are retained and excluded from clean calibration.")
rows=[["Payload / target (msg/s)","Interior SEMP rate","Target tracks?"]]
for r in sdk:
    c=r['case'];t=r['telemetry_summary']
    rows.append([f"{c['size']/1024:g} KiB / {c['target_rate']:,}",f"{t['interior_ingress_messages_per_second']:,.1f}","Yes" if t['operational_target_tracking'] else "No"])
table(rows,[235,140,129])
p("Interior samples fall at controller times 10-50 seconds. The operational diagnostic requires ingress within 5% of target and queue-byte OLS growth no greater than 2% of offered payload bytes/s. This is a finite-window check, not a statistical stationarity proof. Queue maxima are sampled, not instantaneous maxima.","CaptionPaper")
sub("Clean delivery, sustainable rate and tool summaries differ")
p("At 256 bytes, higher offers again produced rates near 5.9k/s in repeated cases, although one 8k offer was more transient. That is cross-stack evidence, not proof of a broker-only ceiling. A 32 KiB / 1,000-message/s offer filled its 300 MB queue: 60,000 attempts, 30,016 NACKs and 29,984 receipts. SDKPerf's displayed Total ACKED Messages summed to 90,016, while ACK Events reconciled with receipts. We do not treat that displayed summary as a success count under overload.")
p("The first 128 KiB / 152-message/s trial had an unresolved tail after the default two-second publish-end delay. A separate 60-second end-delay control delivered and ACKed all 9,120 messages with CRC/order checks, but SEMP counted 9,344 ingress attempts. The 224-attempt surplus is consistent with retries; the SDK retry count was not instrumented. It fails the zero-surplus calibration gate. End delays, quotas, rate control, metadata and ACK timeouts differ from the Node.js study; this is not a matched causal comparison.")
sub("SEMP work vector and pressure")
eq("work = [source messages, source data bytes,\n        queue-ingress copies, queue-spooled bytes]")
p("The new adapter obtains these dimensions directly from counter deltas and preserves exact ratios. Copy bytes retain size/fanout dependence. Legacy SEMP show process supplies top-style CPU data, correcting the broader inference from the absent SEMP v2 broker CPU field. Cache ratios and raw CPU fields are retained; their denominators must not be confused with Docker limits. Measured work is not remaining capacity.")
page()

head("5. The finance link: dependence uncertainty")
p("Let X and Y have known nonnegative finite marginals but an unknown joint distribution. Write Q for their marginal quantile functions and integrate over u from 0 to 1. Classical monotone and countermonotone coupling gives sharp lower and upper bounds [7]:")
eq("integral Q_X(u)*Q_Y(1-u) du <= E[X*Y]\nE[X*Y] <= integral Q_X(u)*Q_Y(u) du")
p("For finite histograms, sort and merge quantile steps. The implementation uses exact fractions and returns attaining joint distributions. The exchange identity delta*(x2-x1)*(y2-y1) shows why aligning ordered values increases the product expectation while preserving marginals. This is established mathematics; the application and diagnostic implementation are the project's contribution.")
sub("Broker work")
p("If size and fanout are each 1 or 9 with equal probability, mean size and mean fanout are both 5. Yet expected copy-byte demand ranges sharply from 9 to 41; independence gives 25. A copy-byte-only capacity budget C would imply a range C/41 to C/9. Other broker resources can tighten or invalidate that single-resource interpretation.")
sub("A hypothetical execution diagnostic")
p("Suppose gross opportunity A is 0.5 or 2 basis points, each equally likely. A retained fraction G is 0.25 or 0.90, also equally likely, and a constant cost is 0.60 bp. The diagnostic quantity is A*G - cost. No market data or decay parameter was estimated.")
table([["Dependence assumption","Gross expectation","Net after 0.60 bp"],
       ["Adverse coupling", "0.47500 bp", "-0.12500 bp"],
       ["Independence", "0.71875 bp", "+0.11875 bp"],
       ["Favorable coupling", "0.96250 bp", "+0.36250 bp"]],[210,147,147])
p("The same marginal summaries admit either sign. Large opportunities coinciding with smaller retention fractions are a plausible stress mechanism to test, not a finding from these broker runs. The example omits fills, inventory and dynamic impact. Publisher ACK latency is not execution latency. An empirical extension requires aligned signal/fill/cost/latency observations and out-of-sample evaluation [8].")
p("Seven tests verify example values, witness marginals, an exhaustive permutation oracle and randomized interval properties. The tool gives a precise answer to a limited question: what the supplied marginals identify, and what their missing dependence leaves uncertain.")
page()

head("6. Reproducible contribution and next gate")
p("The current contribution is a diagnostic workflow: reconcile protocol counters; separate admission, receipt and release; test client-window artifacts; retain failed cases; evaluate held-out configurations; and report dependence uncertainty with attaining witnesses. It is useful research-engineering evidence, but it does not yet provide a validated general Solace peak predictor or a trading strategy.")
sub("Before a stronger capacity claim")
p("SDKPerf crosschecks now complement the original custom generator. Next, run longer offered-load sweeps through a stable throughput/latency frontier. Repeat in randomized order, vary CPU/memory and source/consumer concurrency, and test cache pressure directly. Fit calibrated resource-demand intervals and validate new sizes, fanouts and mixed workloads before introducing TLS, replay or other interactions. Standard-edition measurements must not be presented as unrestricted Enterprise hardware capacity.")
sub("Reproduction package")
eq("broker-capacity/run_matrix.py        # initial controlled experiments\nbroker-capacity/sdkperf_crosscheck.py # independent client stack\nbroker-capacity/semp_work_vector.py  # compact SEMP work abstraction\nfinance-dependence/dependence.py     # sharp bounds, joint witnesses")
p("Design files, image digest, SDK settings, raw telemetry, run-source snapshots, model errors and replication records accompany this draft. The earlier outage-admission prototype is a separate finite-queue safety result; its throughput ratios must not be interpreted as broker speedup. Public author attribution and the final publication venue remain to be confirmed.","CaptionPaper")
sub("Primary references")
refs=[
("1. Solace. Message Spooling.","https://docs.solace.com/Messaging/Guaranteed-Msg/Message-Spooling.htm"),
("2. Solace. SEMP Features and polling guidance.","https://docs.solace.com/Admin/SEMP/SEMP-Features.htm"),
("3. Solace. MessagePublisherProperties, JavaScript API 10.18.3.","https://docs.solace.com/API-Developer-Online-Ref-Documentation/js/solace.MessagePublisherProperties.html"),
("4. Solace. Software broker edition comparison.","https://docs.solace.com/Software-Broker/SW-Broker-Set-Up/Setting-Up-SW-Brokers.htm"),
("5. Denning and Buzen. Operational Analysis of Queueing Networks.","https://docs.lib.purdue.edu/cstech/165/"),
("6. Williams, Waterman and Patterson. Roofline (2009).","https://escholarship.org/uc/item/5tz795vq"),
("7. Puccetti and Wang. Extremal Dependence Concepts (2015).","https://arxiv.org/abs/1512.03232"),
("8. Lehalle and Mounjid. Limit Order Strategic Placement, Adverse Selection and Latency.","https://arxiv.org/abs/1610.00261"),
("9. Solace. SDKPerf and independent performance/integrity testing.","https://docs.solace.com/API/SDKPerf/SDKPerf.htm")]
for text,url in refs:p('<link href="'+html.escape(url,quote=True)+'" color="#315d7e">'+html.escape(text)+'</link>',"ReferencePaper")

def footer(canvas,doc):
    canvas.setStrokeColor(colors.HexColor("#c7d2da"));canvas.setLineWidth(.4)
    canvas.line(54,43,558,43)
    canvas.setFont("Helvetica",8);canvas.setFillColor(colors.HexColor("#5f7080"))
    canvas.drawString(54,30,"When Message Rates Mislead | working draft | 7 November 2026")
    canvas.drawRightString(558,30,str(doc.page))

target=ROOT/"research-draft-sdkperf.pdf"
doc=SimpleDocTemplate(str(target),pagesize=(612,792),rightMargin=54,leftMargin=54,
                      topMargin=48,bottomMargin=55,title="When Message Rates Mislead",
                      author="Independent research project - draft attribution pending")
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(target)
