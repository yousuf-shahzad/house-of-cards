"""Produce the requested standalone PDF from reviewed benchmark artifacts."""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether

from run_benchmark import OUT, ROOT, CASES

DELIVERY = ROOT / "output" / "pdf"
FIGURES = OUT / "figures"
PDF = DELIVERY / "house-of-cards-etf-accuracy-report.pdf"
NAVY="#142C42"; TEAL="#087E8B"; PALE="#EAF4F5"; GRAY="#52616F"; GOLD="#A56512"


def load(name):return json.loads((OUT/f"{name}.json").read_text())


def clean(s):
    return str(s).replace("\u2011","-").replace("\u2013","-").replace("\u2014","-").replace("\u2212","-").replace("\u2192"," to ")


def number(x,d=2):return "n/a" if x is None else f"{x:.{d}f}"


def make_figures(summary,pairs,ev):
    FIGURES.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"axes.labelcolor":GRAY,"text.color":NAVY,"axes.unicode_minus":False,"savefig.facecolor":"white"})
    fig,ax=plt.subplots(figsize=(9,4.2))
    default=set(summary["cases"][0]["pairs"]+summary["cases"][1]["pairs"])
    for label,group,color,marker in [("Defaults",[r for r in pairs if r['pair'] in default],NAVY,"o"),("New non-tech tests",[r for r in pairs if r['pair'] not in default],TEAL,"s")]:
        ax.scatter([r['app_company_overlap_pct'] for r in group],[r['independent_yahoo_return_corr'] for r in group],label=label,c=color,marker=marker,s=48,alpha=.82)
    for name,offset in [("EEM/IVV",(7,-14)),("VTI/VXUS",(8,8)),("XLE/XLP",(10,-4)),("QQQ/XLK",(-62,-20))]:
        r=next(x for x in pairs if x['pair']==name)
        ax.annotate(name,(r['app_company_overlap_pct'],r['independent_yahoo_return_corr']),xytext=offset,textcoords='offset points',fontsize=9)
    ax.set(xlabel="Company holdings overlap (%) - House of Cards",ylabel="Weekly total-return correlation - independent prices",xlim=(-3,95),ylim=(.08,1.05))
    ax.grid(alpha=.12);ax.legend(loc="lower right",frameon=False);fig.tight_layout();fig.savefig(FIGURES/'overlap-vs-correlation.png',dpi=190);plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,3.6))
    groups=[r for r in summary['cases'] if r['group']=='nontech']
    x=np.arange(len(groups));width=.35
    ax.bar(x-width/2,[r['top10_pct'] for r in groups],width,color=TEAL,label="Top ten companies (% of portfolio)")
    ax.bar(x+width/2,[r['coverage_pct'] for r in groups],width,color="#B8CBD5",label="Equity holdings coverage (%)")
    ax.set_xticks(x,[f"N{i+1:02}" for i in range(10)]);ax.set_ylim(0,112);ax.set_ylabel("Percent of portfolio");ax.legend(loc='upper center',bbox_to_anchor=(.5,1.17),ncol=2,frameon=False,fontsize=9);ax.grid(axis='y',alpha=.12);fig.tight_layout();fig.savefig(FIGURES/'nontech-concentration.png',dpi=190);plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,3.5))
    cs=summary['cache_inventory'];x=np.arange(len(cs))
    ax.bar(x,[r['portfolio_weight_with_cached_edges_pct'] for r in cs],color=[NAVY if i<2 else TEAL for i in x])
    ax.set_xticks(x,['D1','D2']+[f'N{i:02}' for i in range(1,11)]);ax.set_ylabel('Portfolio with cached dependency edges (%)');ax.set_ylim(0,50);ax.grid(axis='y',alpha=.12);fig.tight_layout();fig.savefig(FIGURES/'dependency-cache-coverage.png',dpi=190);plt.close(fig)


def build():
    s,pairs,portfolios,ev=load('summary'),load('pair_results'),load('portfolio_results'),load('eval-replay')
    make_figures(s,pairs,ev)
    DELIVERY.mkdir(parents=True,exist_ok=True)
    font_path=Path('C:/Windows/Fonts/arial.ttf');bold_path=Path('C:/Windows/Fonts/arialbd.ttf')
    if font_path.exists():
        pdfmetrics.registerFont(TTFont('Report',str(font_path)));pdfmetrics.registerFont(TTFont('ReportBold',str(bold_path)))
    else:
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        font_path=None
    regular='Report' if font_path else 'Helvetica';bold='ReportBold' if font_path else 'Helvetica-Bold'
    pdfmetrics.registerFontFamily(regular,normal=regular,bold=bold,italic=regular,boldItalic=bold)
    styles=getSampleStyleSheet()
    for name in styles.byName:
        styles[name].fontName=regular;styles[name].textColor=colors.HexColor(NAVY)
    styles.add(ParagraphStyle('Kicker',fontName=bold,fontSize=8.5,leading=12,textColor=colors.HexColor(TEAL),spaceAfter=8))
    styles.add(ParagraphStyle('TitleCustom',fontName=bold,fontSize=30,leading=35,spaceAfter=14))
    styles.add(ParagraphStyle('Deck',fontName=regular,fontSize=13,leading=19,textColor=colors.HexColor(GRAY),spaceAfter=16))
    styles.add(ParagraphStyle('BodyCustom',fontName=regular,fontSize=9.5,leading=14,spaceAfter=8))
    styles.add(ParagraphStyle('SmallCustom',fontName=regular,fontSize=8,leading=11,textColor=colors.HexColor(GRAY),spaceAfter=6))
    styles.add(ParagraphStyle('H2Custom',fontName=bold,fontSize=14,leading=18,spaceAfter=8,spaceBefore=10))
    styles.add(ParagraphStyle('Cell',fontName=regular,fontSize=8,leading=11))
    styles.add(ParagraphStyle('CellSmall',fontName=regular,fontSize=7.1,leading=9.6))
    styles.add(ParagraphStyle('CellHead',fontName=bold,fontSize=8,leading=10.5,textColor=colors.white))
    story=[];width=A4[0]-88
    def P(text,style='BodyCustom'):
        return Paragraph(clean(text),styles[style])
    def para(text):story.append(P(text))
    def small(text):story.append(P(text,'SmallCustom'))
    def heading(text):story.append(P(text,'H2Custom'))
    def title(n,text,deck=None):
        if story:story.append(PageBreak())
        story.append(P(f'VALIDATION REPORT  /  {n:02}','Kicker'));story.append(P(text,'TitleCustom'))
        if deck:story.append(P(deck,'Deck'))
    def table(headers,rows,widths=None,compact=False):
        st='CellSmall' if compact else 'Cell'
        data=[[P(escape(str(h)),'CellHead') for h in headers]]+[[P(escape(clean(v)),st) for v in row] for row in rows]
        t=Table(data,colWidths=widths or [width/len(headers)]*len(headers),repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor(NAVY)),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F1F5F7')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor(TEAL))]))
        story.append(t);story.append(Spacer(1,9))
    def figure(name,height):story.append(Image(str(FIGURES/name),width=width,height=height));story.append(Spacer(1,6))
    def code(case):return 'D1' if case=='default-us' else 'D2' if case=='default-global' else 'N'+case[-2:]
    def ci(m):return f"{100*m['value']:.1f}% ({100*m['ci_low']:.1f}-{100*m['ci_high']:.1f})"
    def pairrow(key):return next(r for r in pairs if r['pair']==key)

    title(1,'Are we accurate?', 'House of Cards: default portfolios and ten new non-tech ETF combinations')
    small(f"8 November 2026  |  Baseline {s['baseline_commit'][:7]}  |  12 portfolios, 22 ETFs, 23 distinct pairs")
    heading('Holdings arithmetic passes. That is not the whole model.')
    para('The production analysis API reconciled to a separate Decimal-based calculation on all 12 portfolios. All 23 listing-level overlap calculations matched. Same-date issuer checks supported the inputs for 11 funds and 2,120 equity rows, within source rounding.')
    table(['What was tested','Result','What it establishes'],[
        ['Portfolio/listing arithmetic','12 / 12 portfolios pass','Correct weighted aggregation on the frozen inputs'],
        ['Listing overlap','23 / 23 pairs pass','Correct sum of the smaller shared weights'],
        ['Independent return correlations',f"Largest difference {s['max_return_corr_delta']:.5f}",'Strong agreement with TickerInside; app has no return-correlation output'],
        ['Dependency extraction replay','88.4% blind precision; 57.4% recall','Recorded evaluation, not a fresh test on the ten new portfolios'],
    ],[120,151,width-271])
    heading('The most useful counterexample')
    r=pairrow('EEM/IVV')
    para(f"EEM and IVV have <b>0.00% listing overlap</b>, but their independently calculated weekly return correlation is <b>{r['independent_yahoo_return_corr']:.3f}</b>. Shared holdings, shared suppliers and historical co-movement answer different questions.")
    heading('Decision')
    para('The arithmetic is credible for the tested equity snapshots. Do not describe the app as a validated return-correlation model, assume old holdings are current, or treat missing dependency links as evidence of independence. The dependency layer needs new, blind non-tech filing evaluations before claiming general accuracy.')
    small('This is a software/data validation exercise. "Independent" means a separate calculation path and external provider/issuer controls; no second human auditor reviewed this report.')

    title(2,'What we tested','The cohort was fixed before batch measurement; no production model or formula was tuned.')
    table(['Case','Mandate / purpose','ETF allocations'],[[code(c['id']),c['label'],', '.join(f'{t} {100*w:g}%' for t,w in c['weights'].items())] for c in CASES],[37,175,width-212])
    para('D1 and D2 are the exact allocation-based defaults in hoc/examples.py. They do not use the UI\'s whole-share rounding. N01-N08 compare large-cap and broad funds in the same non-tech sector. N09 and N10 test mixed-sector portfolios and unequal allocations.')
    small('"New" means absent from the two default portfolios as combinations. It does not establish that an LLM has never encountered the funds or that their constituents are outside all previous development data. XLF/VFH was also used for API reconnaissance. This is a diagnostic convenience sample, not a random market sample or a training holdout.')
    heading('Four separate comparison paths')
    para('<b>Inside:</b> pinned production sources, identity resolution, normalization, portfolio maths and /api/analysis, exercised through FastAPI TestClient. Only the HTTP input seam records/replays public source bytes; no production arithmetic is replaced.')
    para('<b>Outside:</b> raw holdings summed with Decimal; TickerInside public pair answers; direct iShares/SPDR/Vanguard issuer files; and Yahoo daily adjusted closes rolled into Friday-ending weeks. Pearson correlation was recomputed without application helpers and cross-checked with NumPy.')
    small('TickerInside is an upstream source for House of Cards. Agreement with its own fund files is shared-source parity, not independent truth. Direct issuer and independent price checks are reported separately.')

    title(3,'The default ETF pairs','Company overlap and listing overlap differ by design when share classes or listings are merged.')
    default_keys=set(s['cases'][0]['pairs']+s['cases'][1]['pairs'])
    default_pairs=[r for r in pairs if r['pair'] in default_keys]
    table(['Pair','App company overlap %','Manual listing overlap %','TI listing overlap %','Outside return r'],[[r['pair'],number(r['app_company_overlap_pct'],4),number(r['manual_listing_overlap_pct'],4),number(r['tickerinside_overlap_pct'],1),number(r['independent_yahoo_return_corr'],4)] for r in default_pairs],[91,105,112,106,width-414])
    heading('Why QQQ/VXUS looks different')
    r=pairrow('QQQ/VXUS')
    para(f"House of Cards reports <b>{r['app_company_overlap_pct']:.4f}% company overlap</b>; the separate listing calculation is <b>{r['manual_listing_overlap_pct']:.4f}%</b>, which TickerInside rounds to {r['tickerinside_overlap_pct']:.1f}%. The {r['app_company_overlap_pct']-r['manual_listing_overlap_pct']:.4f}-point bridge is accounted for by ASML and Ferrovial listings:")
    table(['Company','Symbols grouped by the app','Added company overlap (pp)'],[[x['company'],', '.join(x['symbols']),number(x['added_overlap_pp'],4)] for x in s['cross_listing_bridge']],[130,230,width-360])
    para('This is a definition difference, not a failed overlap formula. Company-level arithmetic was checked against the app\'s supplied symbol memberships; that check does not independently prove every entity match. The two listed bridges are explicitly identified for review.')
    small('Overlap percentages compare fund holdings and do not depend on the portfolio allocation. The portfolio exposure and top-ten tests do use the allocations on page 2.')

    title(4,'Ten new non-tech combinations','Same-sector pairs move together strongly. Mixed-sector portfolios are not proven independent by zero holdings overlap.')
    nc=[c for c in s['cases'] if c['group']=='nontech']
    def span(a,b,d):return number(a,d) if abs(a-b)<1e-9 else f'{a:.{d}f}-{b:.{d}f}'
    table(['Case','ETF combination','App overlap %','Outside weekly r','Top ten %'],[[code(c['id']),'/'.join(c['weights']),span(c['overlap_min'],c['overlap_max'],2),span(c['rho_min'],c['rho_max'],3),number(c['top10_pct'],2)] for c in nc],[37,160,105,110,width-412])
    small('For the three-fund cases N09 and N10, overlap and r show the range across their three constituent pairs, not a "portfolio correlation" or an average correlation. All correlations use the same 156 aligned weeks.')
    figure('nontech-concentration.png',202)
    para('The eight same-sector tests produced high overlap and return correlations near one. The mixed-sector pairs had zero listing overlap, yet positive weekly return correlations. Concentration remains material in several same-sector portfolios, even when two ETF names are held.')

    title(5,'Independent issuer checks','Keep current-source differences separate from calculation errors on a frozen source vintage.')
    para(f"<b>Same-date control:</b> {s['matched_issuer_funds']} funds, {s['matched_issuer_rows']:,} equity rows, all dated 5 November 2026. Direct iShares and SPDR weights agree with TickerInside to at most <b>{s['max_matched_issuer_weight_error_pp']:.6f} percentage points per line</b>. This is consistent with four-decimal source rounding. One immaterial IVV holding rounds out of the TickerInside map; no material holding was missing.")
    issuer_pairs=[r for r in pairs if any(r['pair']==p for p in ['VFH/XLF','VHT/XLV','VDE/XLE','VPU/XLU','VDC/XLP','VIS/XLI','VAW/XLB','VNQ/XLRE'])]
    table(['Pair','App / old TI %','Issuer files %','Change pp','Vanguard date in TI -> issuer'],[[r['pair'],number(r['app_listing_overlap_pct'],3),number(r['issuer_overlap_pct'],3),f"{r['issuer_overlap_pct']-r['app_listing_overlap_pct']:+.3f}",f"{r['ti_date_a'][5:]} -> {r['issuer_date_a'][5:]}" ] for r in issuer_pairs],[81,95,90,79,width-345])
    small('SPDR is 2026-11-05 on both sides. Vanguard issuer files are 2026-09-30; TickerInside uses 2026-08-31, except VNQ 2026-07-31. Direct issuer pairs use CUSIP/security identifiers. Vintage changes, corporate actions and identifier changes are therefore confounded; these deltas are not app arithmetic failures.')
    heading('Fresh prices can sit next to old holdings')
    para('Price series end on 6 November 2026, but holdings dates range from 5 November back to 30 June. On the collection date, QQQ and VTI holdings are 131 days old, VXUS and VNQ 100 days old, and the other Vanguard sector files 69 days old. This is a real limitation of present-day exposure claims even when the calculation is exact.')
    para('Direct holdings were obtained for 21 of the 22 funds. A complete independent QQQ holdings file was not obtained, so no full issuer-control pass is claimed for it. Its independent adjusted-price correlation check is complete.')

    title(6,'Correlation outside the app','23 pairs, 156 common Friday-ending weeks: 17 November 2023 through 6 November 2026.')
    figure('overlap-vs-correlation.png',246)
    para(f"Pearson correlations computed from TickerInside's published weekly total returns match its displayed pair answers within the expected two-decimal rounding bound. The largest absolute rounding difference is {s['max_ti_corr_rounding_delta']:.6f}. Rebuilding weekly returns from a second provider's daily dividend/split-adjusted closes changes r by at most <b>{s['max_return_corr_delta']:.6f}</b> across the 23 pairs.")
    table(['Example','Holdings overlap %','Independent return r','Meaning'],[[name,number(pairrow(name)['app_company_overlap_pct'],3),number(pairrow(name)['independent_yahoo_return_corr'],4),meaning] for name,meaning in [('EEM/IVV','No shared listings; substantial co-movement'),('VTI/VXUS','Little overlap; common market movements'),('XLE/XLP','No shared listings; lower, still positive r'),('QQQ/XLK','High overlap and high co-movement')]],[85,103,103,width-291])
    para('<b>Feature gap:</b> the production API does not calculate historical return correlation. The correlations here belong to the external benchmark; they are not predictions or outputs that our model has passed. A historical correlation layer would complement the holdings and dependency views, rather than replace them.')
    small('Weeks are aligned by date, not by truncating arrays to the same length. Both price paths are total-return adjusted. r is a historical association, not a measure of dependency direction, expected loss, or causation. The chosen pairs are not independent statistical observations.')

    title(7,'A hand-style calculation','The independent oracle uses source weights, not the application\'s overlap or exposure helpers.')
    para('For N01, 50% XLF plus 50% VFH, the portfolio stake in JPMorgan is 0.5 x 11.0634% + 0.5 x 10.4679% = <b>10.76565%</b>. The app gives the same answer. Its contribution to fund overlap is the smaller fund weight, <b>10.4679 percentage points</b>; these are different calculations.')
    table(['Holding','XLF %','VFH %','Manual portfolio %','App %','Overlap contribution pp'],[[r['symbol'],number(r['xlf_weight_pct'],4),number(r['vfh_weight_pct'],4),number(r['manual_portfolio_pct'],5),number(r['app_company_pct'],5),number(r['overlap_contribution_pct'],4)] for r in s['worked_financials']],[58,73,73,106,87,width-397])
    heading('What reconciled across all twelve portfolios')
    para('Listing exposure = sum of ETF allocation x that listing\'s fund weight. Listing overlap = sum of min(weight A, weight B) across common listings. Top-ten concentration = the ten largest company exposures added together. HHI = sum of squared company shares after normalizing to covered company holdings; effective N = 1 / HHI.')
    table(['Check','Observed maximum error','Scope'],[
        ['Listing exposure','0.00000000 pp','Every included listing in all 12 portfolios'],
        ['Company arithmetic','0.00000000 pp','Conditional on app entity memberships'],
        ['Listing overlap','0.00000000 pp','All 23 pairs'],
        ['Top-ten concentration','Less than 0.00000001 pp','All 12 portfolios'],
        ['HHI',f"{s['max_hhi_error']:.2e}",'Within API numeric serialization precision'],
    ],[130,155,width-285])
    para('The equity oracle explicitly excludes nine observed index-futures contracts, including positive and negative positions. The application correctly excludes them too. Direct issuer cash, money-market rows with no equity identifier, and warrants are also separated. Raw source weights are never silently scaled to 100%.')
    small('These are independent computations by code, with a worked example suitable for manual checking. They are not a claim that a person calculated every line with a calculator. No app source or model was changed to improve the benchmark score.')

    title(8,'How a company link is weighted','Three separate stages: discover the relationship, rank its importance, then aggregate portfolio exposure.')
    para('<b>Detection:</b> the backend selects portfolio companies, retrieves available SEC annual reports, and asks Gemini for named suppliers, customers, manufacturers, inputs, partners and facilities with supporting quotes. Deterministic checks ground targets and quotes in the filing; semantic interpretation review can reject or flag a relationship. Cached extraction and optional additional research sit around this pipeline.')
    para('<b>Importance:</b> a deterministic rule score ranks the relationship. The starting value depends on its type, then wording in the evidence changes it. This is a heuristic ranking, not a learned probability or an estimated share of production at risk.')
    table(['Relationship','Starting score','Example rule'],[
        ['Foundry / contract manufacturer','0.90 / 0.85','High starting importance by type'],
        ['Key input / supplier / joint venture','0.60 / 0.50 / 0.40','Evidence wording can raise or lower the score'],
        ['Customer','0.50, 0.70 or 0.90','Grounded revenue share: under 10%, 10-20%, or at least 20%'],
        ['Facility','0.70 / 0.30 / 0.50','Production / office or R&D / other location'],
    ],[150,120,width-270])
    para('Sole-source evidence sets a floor of 0.95. Other cues add 0.05-0.15; alternative sources subtract 0.15, with the result clipped to 0-1. A flagged interpretation or qualifying reverse-customer disclosure is capped at 0.55. Tiers are critical at 0.80+, high at 0.60+, medium at 0.40+, otherwise low.')
    heading('The portfolio percentage is a different number')
    para('For a supplier, the backend sums the portfolio stakes of the distinct companies linked to that supplier. If two companies represent 2% and 3% of the portfolio, the displayed linked-company exposure is 5%, even if one filing supplies several quotes. The critical/high subset uses qualifying relationships only. The calculation does not multiply 5% by the importance score.')
    para('That 5% describes money held in linked companies. It does not establish that 5% of the portfolio would be lost, that all their revenue depends on this supplier, or that the relationship explains their return correlation. Separate supplier totals may overlap because one company can have several suppliers.')
    small('Code inspected at the frozen baseline: hoc/ai/extractor.py and verifier.py; hoc/graph/importance.py, metrics.py and orchestrator.py. The API arithmetic benchmark does not validate the economic calibration of these relationship scores. The recorded importance evaluation follows on the next page.')

    title(9,'What the existing AI eval says','Replay of the pinned ten-company extraction benchmark, not a new inference run on the ETF portfolios.')
    blind,pool=ev['blind_overall_after_vint'],ev['overall_after_vint']
    table(['Metric','Blind gold','With pooled additions'],[
        ['Precision (95% company bootstrap CI)',ci(blind['precision']),ci(pool['precision'])],
        ['Core recall (95% CI)',ci(blind['recall']),ci(pool['recall'])],
        ['F1 (95% CI)',ci(blind['f1']),ci(pool['f1'])],
        ['Predictions / core misses',f"{blind['predicted_count']} / {blind['fn']}",f"{pool['predicted_count']} / {pool['fn']}"],
    ],[205,151,width-356])
    para('The blind gold contains 212 relationships. Ten additional relationships were accepted through pooling after reviewing predictions, making 222. Pooled precision is useful, but the blind 88.4% estimate is the stronger headline for generalization. Core recall is 66/115, so 49 core relationships are missed.')
    table(['Additional measure','Result','Interpretation'],[
        ['Importance exact agreement','68.4% (54/79)','Tier labels disagree on roughly a third of scored matches'],
        ['Importance weighted kappa','0.475 (95% CI 0.382-0.631)','Useful signal, not calibrated economic dependence'],
        ['Direction / facility-country agreement','124/124 and 39/39','Conditional on evaluated matches; not whole-graph accuracy'],
        ['Agentic research effect','35 findings; 0 edges added or removed','No measured precision or recall improvement on this replay'],
    ],[152,160,width-312])
    heading('Failures matter more than a single headline')
    weak=sorted(ev['companies'],key=lambda c:c['recall_after_vint'])[:4]
    table(['Company','Core found / missed','Blind precision','Core recall'],[[c['ticker'],f"{c['tp_core_after_vint']} / {c['fn_after_vint']}",f"{100*c['precision_blind_after_vint']:.1f}%",f"{100*c['recall_after_vint']:.1f}%"] for c in weak],[105,145,130,width-380])
    small('Source: existing gold and recorded predictions in the repository; replay run at baseline 9bdf21f, B=2,000 company bootstrap draws. This result evaluates stored predictions, not whether newer extractor/scoring code would produce the same results in a fresh live run. Extended gold is optional for recall; these are not exhaustive filing labels.')

    title(10,'What remains unvalidated','Cache availability is a coverage check, not a test of what the AI would discover in a fresh scan.')
    figure('dependency-cache-coverage.png',207)
    table(['Case','Top companies','Cached companies','Portfolio with cached links %'],[[code(r['case']),r['top_companies'],r['cached_companies'],number(r['portfolio_weight_with_cached_edges_pct'],2)] for r in s['cache_inventory']],[50,110,130,width-290])
    para('The local extraction-cache snapshot contains no top-company results for five of the ten new non-tech portfolios. That does not mean those companies have no dependencies, and it does not predict coverage after a fresh scan. It shows why the holdings benchmark alone cannot validate the dependency graph on these combinations.')
    small('No fresh LLM extraction or new blind filing annotation was run for this cohort. The requested overlap/correlation benchmark is complete; non-tech semantic extraction accuracy remains an explicitly separate, unmeasured question. Cache numbers are time-specific local state, with the selected cached edge payloads saved for inspection.')

    title(11,'What to change next','Priorities follow the evidence, rather than tuning the model to these twelve portfolios.')
    table(['Priority','Action','Acceptance criterion'],[
        ['1','Name the metric at every comparison','Company overlap, listing overlap, return correlation and dependency exposure are separate labels, with their own dates and units.'],
        ['1','Make stale holdings conspicuous','Show holdings vintage separately from the latest price; prefer available fresh issuer data or explain the older source selection.'],
        ['1','Expand blind non-tech dependency evaluation','Freeze new filings/labels before running inference; score missed links, incorrect links, direction, importance and portfolio exposure coverage.'],
        ['2','Add correlation only as a distinct feature','Adjusted returns, weekly date alignment, minimum sample size and source/window shown; validate against the external series retained here.'],
        ['2','Retain source and calculation regression checks','Run the frozen cases without modifying them; treat version/date changes as new benchmark runs.'],
    ],[42,165,width-207])
    heading('Keep the correct parts')
    para('Do not modify holdings arithmetic to force company overlap to equal TickerInside\'s listing overlap. Do not multiply portfolio exposure by the heuristic importance score and call it measured loss. The app\'s source aggregation and calculations passed the checks designed for them.')
    heading('Verification and limits')
    para('The focused backend test run passed 152 tests with one skipped live test. Existing evaluation replay completed. The initial test command needed a task-local temporary directory because Windows denied access to the shared pytest temp directory; the rerun passed without changing tests.')
    para('The API run used captured TickerInside inputs and the real normalization/identity/maths implementation. It did not test upstream outage retries, user-interface rendering, intraday quotes, trading outcomes, live dependency extraction on the new portfolios, or completeness of every company alias. The sample is deliberately diagnostic and cannot establish universal accuracy.')
    small('The two independent price providers may use shared exchange/vendor feeds. Their agreement is an independent provider check, not proof of wholly independent market observations. Issuer files were kept locally for verification and are not redistributed in the evidence bundle.')

    title(12,'All 23 pair results','Detailed numerical results; full precision and dates are in the companion CSV.')
    table(['Pair','App company %','Manual listing %','TI listing %','TI r (shown)','Manual TI r','Outside r'],[[r['pair'],number(r['app_company_overlap_pct'],4),number(r['manual_listing_overlap_pct'],4),number(r['tickerinside_overlap_pct'],1),number(r['tickerinside_return_corr'],2),number(r['manual_ti_return_corr'],5),number(r['independent_yahoo_return_corr'],5)] for r in pairs],[81,76,79,71,65,66,width-438],compact=True)
    small('All independent correlations use 156 observations. The production app has no return-correlation result to compare. The TickerInside overlap endpoint refused large global pairs with HTTP 400 "too_large"; its documented diversify endpoint supplied the equivalent pair figures. Both the refusal and alternate response were retained.')

    title(13,'Sources and reproducibility','The report is backed by source snapshots, hashes, independent calculations and machine-readable results.')
    source_links=[
        ('TickerInside API and schemas','https://tickerinside.com/api/'),
        ('TickerInside overlap definition','https://tickerinside.com/etf-overlap-api/'),
        ('TickerInside calculation methodology','https://tickerinside.com/how-the-numbers-are-produced/'),
        ('Example raw fund: XLF','https://tickerinside.com/api/v1/fund/xlf.json'),
        ('Example pair: XLF / VFH','https://tickerinside.com/api/v1/overlap?funds=XLF,VFH'),
        ('Official SPDR holdings: XLF','https://www.ssga.com/us/en/individual/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlf.xlsx'),
        ('Official Vanguard holdings: VFH','https://investor.vanguard.com/irr/funds/profile/VFH-AdditionalFundData'),
        ('Official iShares holdings: IVV','https://www.ishares.com/us/products/239726/ishares-core-s-p-500-etf/latest-holdings.csv'),
        ('Official iShares holdings: EEM','https://www.ishares.com/us/products/239637/ishares-msci-emerging-markets-etf/latest-holdings.csv'),
        ('Independent adjusted-price history: XLF','https://finance.yahoo.com/quote/XLF/history/'),
    ]
    for label,url in source_links:para(f'<link href="{escape(url, {chr(34): "&quot;"})}" color="{TEAL}">{escape(label)}</link>')
    small('TickerInside data is credited to TickerInside, holdings/returns through 2026-11-06, CC BY 4.0. Every fund/pair endpoint and retrieval timestamp is in sources.csv; the local snapshot manifest includes content SHA-256 hashes. Issuer source dates are carried individually, not inferred from the retrieval date.')
    heading('Code and artifacts')
    para('Source: backend/tests/live/etf_accuracy/. The scripts are run_benchmark.py, analyze_results.py and build_pdf.py; cases.json fixes the cohort. The frozen baseline commit is '+s['baseline_commit']+'.')
    para('Reproduce with the baseline backend installed and report dependencies available: run run_benchmark.py all; then analyze_results.py; then build_pdf.py. Network responses are cached under artifacts/raw, once per URL. Preserve these bytes to reproduce this run; fetching newer upstream data creates a new data vintage.')
    table(['Delivered companion file','Contents'],[
        ['ETF-benchmark-evidence.zip','Case manifest, portfolio/pair results, dates, issuer controls, cache inventory, source URL/hash manifest, validation summary and scripts'],
        ['ETF-pair-comparisons.csv','All 23 pairs, full precision and source dates'],
        ['ETF-portfolio-checks.csv','All 12 portfolio arithmetic checks'],
    ],[190,width-190])
    small('Locally retained evidence includes full API responses, source bytes, replay evaluation output, selected extraction-cache payloads and verification logs. The compact delivery bundle omits raw issuer holdings and secrets. No API keys or account information were used in the report.')

    def page_frame(canvas,doc):
        canvas.saveState();w,h=A4
        canvas.setStrokeColor(colors.HexColor('#D7E1E7'));canvas.setLineWidth(.6);canvas.line(44,42,w-44,42)
        canvas.setFont(regular,7.5);canvas.setFillColor(colors.HexColor(GRAY));canvas.drawString(44,28,'HOUSE OF CARDS  /  ETF ACCURACY BENCHMARK  /  08 NOV 2026');canvas.drawRightString(w-44,28,f'{doc.page}');canvas.restoreState()
    doc=SimpleDocTemplate(str(PDF),pagesize=A4,rightMargin=44,leftMargin=44,topMargin=42,bottomMargin=58,title='House of Cards - ETF accuracy validation',author='House of Cards / Codex validation')
    doc.build(story,onFirstPage=page_frame,onLaterPages=page_frame)
    for src,name in [('pairs.csv','ETF-pair-comparisons.csv'),('portfolios.csv','ETF-portfolio-checks.csv')]:shutil.copy2(OUT/src,DELIVERY/name)
    print(PDF)


if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=DELIVERY)
    args = parser.parse_args()
    DELIVERY = args.output_dir.resolve()
    PDF = DELIVERY / 'house-of-cards-etf-accuracy-report.pdf'
    build()
