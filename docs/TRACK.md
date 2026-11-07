# Agentverse 2026: track brief

## Event overview

Two days, four tracks, over 300 builders in teams of 3–5 around Bloomsbury.

- **Robotics, "Embodied AI"** (with NVIDIA and UCL Robotics): turn perception into safe physical action. Examples: drone fleets, assistive wearables, MuJoCo twins or offline Gemma 4.
- **Finance, "Trusted Markets"** (with Jane Street): agents you'd trust with real money. Examples: anomaly and VaR checks proven in Python, market stress-tests, everyday financial inclusion.
- **Biotech, "Lab to Patient"**: shorten discovery from papers to bedside. Examples: summarising papers, clinical trial matching.
- **Creative, "Brand & Worlds"**: branding, video and interactive 3D worlds.

## Finance track: the challenge

Help people make better money decisions. Pick one busy person (a compliance analyst facing 400 alerts, a trader testing a hunch, a small business owner worried about payroll). Find a decision they get wrong or make too slowly, and build an agent that helps without hiding its reasoning or the risk.

Areas to aim at: risk and compliance, market agents, financial inclusion, scams and fraud, regulation, or your own idea.

The bar: would you let it near your own money? Show your reasoning so a professional could check it.

## Finance track: judging

| Criterion | Weight | What it means |
|---|---|---|
| Traceable reasoning | 25% | Every decision traces from raw data to output, with the maths done separately from the AI. |
| Testing on unseen data | 25% | Real costs, a fitting benchmark and stated uncertainty. |
| Relevance and impact | 20% | A specific user, with the failure that would hurt them handled on screen. |
| Risk controls and oversight | 15% | Limits enforced in code, every action logged, one control shown live. |
| Ambition and technical quality | 15% | Does something a normal program couldn't. |

## Finance track: what to submit

- **Code:** a public repo with a short README, ideally with a demo that runs, even a rough one.
- **Pitch deck:** the problem, who it helps, your data, how you evaluated it against a benchmark, the agent's limits and risk controls, and your key statistics. Judges score every team from the deck, so put your evidence there.
- **Live pitch:** top 3 teams only, up to 4 minutes plus 2 minutes of questions.

## Finance track: data and tools

Agentverse finance kit: synthetic cases, real price history and a hidden test mode.

Other sources:

- **Crypto prices:** Binance Vision, Binance API.
- **Macro and rates:** FRED, Bank of England, ECB, ONS.
- **Company filings:** SEC EDGAR, Companies House.
- **Fraud and laundering:** IBM AMLSim, PaySim, Elliptic, ULB card fraud.
- **Prediction markets:** Polymarket.
- **Households:** World Bank Findex, FCA Financial Lives, ONS.
- **Rules and regulation:** FCA Handbook, legislation.gov.uk, BIS.

Synthetic data is allowed, but you must:

- label it and say how you made it;
- never present it as real-world performance;
- use no real financial records or logins;
- paper-trade only, never with real money;
- cite every dataset and check its licence.

## Google DeepMind: getting started (pick one path)

- **AI Studio Build:** describe your app in one sentence and it builds the scaffold, using gemini-4-argon, with GitHub or Cloud Run export.
- **Live & Speech Studio:** live camera, voice and expressive voices in Chrome.
- **Antigravity & Skills:** an agent-based coding tool.

Take a photo of that slide to claim onsite credits at the DeepMind booth.

## Google DeepMind: "Best Use of Gemini" prize

- **2+ modalities:** live camera, voice, video, 3D, images or audio.
- **Real proof:** Argon plans with `thinking_level="high"`, and Python or a solver checks its maths.
- **Beyond text:** interactive 3D or a live canvas, adaptive audio, and human sign-off when the stakes are real.

Judges want to feel the magic in 10 seconds, with zero hallucinated outputs and a build for one real user. Prizes are cash, credits and swag.

Their test: if your whole product would work inside a plain text prompt, push harder.

## Google DeepMind: what judges notice in 10 seconds (from auditing 200+ repos)

Do:

- demo live in the first second with real, messy inputs;
- use the Interactions API, which has automatic caching;
- keep humans in control of money, medical care or hardware, with deterministic Python checks and an explicit approval step.

Skip:

- plain chat wrappers;
- mocked UIs or hardcoded JSON;
- the deprecated Gemini 2.5.
