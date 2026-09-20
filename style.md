# ParaCheck — Site & Product Design System
Version: 1.0 — 2026-09-21

## 0. Purpose

This file is the source of truth for the ParaCheck marketing site and the product-facing SaaS UX.

The site must make a Solidity developer who is frustrated by expensive, poorly optimized contracts immediately think:

> "This will tell me exactly what is costing me money, show me what to change, and prove that the fix worked."

The experience should feel so smooth that the user can go from repository to useful optimization findings in a few clicks.

Do NOT build another generic "AI code review" landing page.

ParaCheck's product wedge is specialized, evidence-driven analysis for Solidity teams shipping to parallel-execution chains, especially Monad:

- static Solidity analysis using Slither + ParaCheck's hot-slot classifier
- dynamic contention analysis using Foundry/anvil + trace data
- GitHub PR Check Runs and annotations
- hosted SaaS dashboard for installations, repositories, review history, quotas, and billing
- optional future BYOK Claude synthesis
- Cloudflare Pages + Workers + D1 as the hosted control plane
- GitHub Actions as the execution environment for repository analysis

Current launch architecture:
Cloudflare Pages -> Cloudflare Worker -> D1 / GitHub / Stripe / Clerk -> GitHub Actions -> Foundry + solc + Slither + ParaCheck -> GitHub Check Run.

Cloudflare Workers must NOT be represented as executing Foundry, solc, Slither, npm installs, or arbitrary repository builds. GitHub Actions performs the analysis.

---

# 1. Product Positioning

## Core statement

> Ship cheaper contracts.

Supporting statement:

> ParaCheck finds the storage, execution, gas, and parallelism patterns making your Solidity expensive — and shows you exactly what to change.

Alternative supporting language:

> Write Solidity → see what's costing you → fix it → prove it's better → ship.

The emotional promise:

> "We are on your side. We help you make the contract better."

Never frame findings as an accusation:
- avoid "you wrote this wrong"
- avoid "bad code"
- avoid "developer mistake"
- avoid shame-heavy language

Prefer:
- "This contract is leaving parallel execution on the table."
- "This path performs a repeated storage read."
- "This pattern can cause contention."
- "This change could reduce execution cost."
- "Here's the measurable effect of the fix."

## Target developer

Primary:
- Solidity developer
- smart-contract engineer
- protocol engineer
- Web3 infrastructure engineer
- developer shipping contracts to Monad / parallel-execution environments
- developer whose team cares about gas, throughput, execution efficiency, and production cost

Psychological context:
- they have been told their contract is too expensive
- they have had PRs rejected for gas/performance reasons
- they know Solidity but do not always know why a contract is expensive
- they do not want another generic linter dumping 40 findings on them
- they want evidence, prioritization, and concrete fixes
- they want to remain in GitHub / their coding workflow

The site should make them feel:
1. understood
2. relieved
3. curious
4. confident
5. immediately productive

---

# 2. Competitive Context

Relevant products:

- CodeRabbit
- Greptile
- Qodo

Current market pattern:
- CodeRabbit emphasizes automated review, context, agent loops, triage, change understanding, and workflow automation.
- Greptile emphasizes repository graph context, agent swarms, custom rules, learning from PR comments, and one-click handoff to coding agents.
- Qodo emphasizes full-codebase context, specialized review agents, standards/governance, IDE + Git workflows, and quality infrastructure.

ParaCheck should NOT imitate their generic positioning.

Do not make the homepage:
- "AI code review for Solidity"
- "Your AI pair programmer"
- "The smartest code reviewer"
- "AI-powered code quality"
- "multi-agent code review"
- "catch bugs with AI"

These are crowded messages.

Instead:

> ParaCheck is the performance/optimization layer for Solidity.

The differentiator is that ParaCheck can combine deterministic static analysis with runtime evidence and measured contention behavior.

The LLM is not the source of truth.

Architecture:

                         ParaCheck
                             |
             +---------------+---------------+
             |               |               |
             v               v               v
         Static          Runtime          Economic
         analysis        analysis         analysis
             |               |               |
             +---------------+---------------+
                             |
                    Optimization findings
                             |
                    +--------+--------+
                    |                 |
                    v                 v
             deterministic          Claude
                report              BYOK
                                 (future/optional)

Principle:

> ParaCheck owns the evidence. Claude explains and helps transform findings.

---

# 3. Product Story

The ideal loop:

WRITE CONTRACT
      ↓
PARA CHECK
      ↓
82 / 100
4 optimizations
      ↓
FIX
      ↓
RUN MEASUREMENTS
      ↓
94 / 100
27% less gas
4.8× less contention
      ↓
OPEN PR
      ↓
PARA CHECK PASSES
      ↓
MERGE

Only show numerical claims when they are actually measured or defensibly calculated.

Never fabricate:
- gas savings
- dollar savings
- throughput improvements
- contention percentages
- performance multipliers

If data is unavailable, use:
- "potential"
- "estimated"
- "detected"
- "measured" only when actually measured

---

# 4. Homepage Structure

The homepage should be short, extremely polished, and conversion-oriented.

Recommended sequence:

1. Navigation
2. Hero
3. Interactive product proof
4. Problem
5. How ParaCheck finds the problem
6. Before/after optimization example
7. GitHub workflow
8. Technical credibility
9. CTA
10. Footer

Do not make the homepage a giant feature checklist.

The visitor should understand the product within 5 seconds.

---

# 5. Hero

## Primary headline

# Ship cheaper contracts.

This is the preferred headline.

Supporting copy:

> ParaCheck finds the storage, execution, gas, and parallelism patterns making your Solidity expensive — and shows you exactly what to change.

Primary CTA:

> Connect GitHub

Secondary CTA:

> Analyze a contract

Optional tertiary link:

> See how it works

Avoid:
- "Get started for free" if there is no free tier
- fake urgency
- "revolutionary"
- "AI-powered"
- "10x your productivity"
- startup jargon

The CTA must be action-oriented.

---

# 6. Hero Product Proof

The hero should show the product doing something, not a generic illustration.

Preferred composition:

LEFT:
headline + short explanation + CTA

RIGHT:
a compact live-looking optimization report

Example:

    PARACHECK
    ───────────────────────────────

    VAULT.SOL

    CONTRACT PERFORMANCE

                  82
               / 100

    6 optimizations found

    CRITICAL
    swap()
    Storage contention
    [ View fix → ]

    HIGH
    deposit()
    Repeated SLOAD
    [ View fix → ]

    MEDIUM
    claim()
    Unnecessary storage write
    [ View fix → ]

Use real product terminology.

Do not make it look like a fake crypto dashboard.

---

# 7. The "Holy Shit" Moment

The product's strongest interaction is:

Finding → explanation → fix → measurement.

Example:

    CRITICAL

    swap()

    Storage contention

    Every concurrent swap touches:

      reserve0
      reserve1
      totalLiquidity

    Result:
    transactions serialize under contention.

    [ Fix this ]

After clicking:

    BEFORE
    100% contention

    AFTER
    18% contention

    EXECUTION IMPACT
    ~5.4× more transactions can execute concurrently

Only use values that actually come from ParaCheck's measurement system.

The user should be able to understand the finding without reading a long report.

---

# 8. Optimization Report

The report is the core product surface.

Do not present 40 findings with equal visual weight.

Prioritize by:
1. measurable impact
2. severity
3. confidence
4. ease of remediation

Recommended top section:

    CONTRACT PERFORMANCE

    82 / 100

    Potential improvements
    6

    Critical
    2

    High
    2

    Medium
    2

Then show findings.

Example:

    CRITICAL
    ─────────────────────────────────

    swap()

    Storage contention

    This path writes:
      reserve0
      reserve1
      totalLiquidity

    Concurrent swaps repeatedly invalidate
    each other's reads.

    [ Fix this ]   [ View evidence ]

Then:

    HIGH
    ─────────────────────────────────

    deposit()

    Repeated storage read

    balance[user] is loaded 4×.

    Estimated:
    ~2,100 gas / transaction

    [ Fix this ]

Then:

    MEDIUM
    ─────────────────────────────────

    claim()

    Unnecessary storage write

    ...

---

# 9. Finding Language

Every finding should answer four questions immediately:

1. What is wrong?
2. Where is it?
3. Why does it matter?
4. What should I do?

Structure:

    TITLE

    WHAT:
    concise statement

    WHY:
    concrete performance/execution consequence

    EVIDENCE:
    measured/static evidence

    FIX:
    specific remediation

    [ Fix this ]

Example:

    Repeated SLOAD

    WHAT:
    balance[user] is read four times in this path.

    WHY:
    The repeated storage access adds execution cost.

    EVIDENCE:
    4 reads detected in swap().

    FIX:
    Cache the value in memory and reuse it.

Do not make every finding verbose.

---

# 10. Before / After Is the Product Language

Prefer:

> This contract is leaving parallel execution on the table.

over:

> Potential storage conflict detected.

Prefer:

> This costs ~X gas every time claim() runs.

over:

> Potential gas optimization.

Prefer:

> Split this storage by market to let independent transactions execute concurrently.

over:

> Consider sharding storage.

Prefer:

> 3 changes could materially improve this contract.

over:

> 3 issues found.

The UI should feel like an optimization coach, not a punishment system.

---

# 11. "Fix This" Interaction

Every actionable finding should have a clear primary action.

Preferred:

[ Fix this ]

Secondary:

[ View evidence ]

Possible later actions:

[ Copy patch ]
[ Open in GitHub ]
[ Send to Claude Code ]
[ Send to Cursor ]

The user should not need to manually translate the finding into an action.

Show a focused diff:

    - reserve0 = newReserve0;
    - reserve1 = newReserve1;
    + _updateBand(bandId, newReserve0, newReserve1);

Then show impact.

Before:
    contention: 100%

After:
    contention: 18%

Again: only use actual measured values.

---

# 12. Optimization Score

A performance score can create a strong recurring loop.

Do NOT call it "code quality score."

Preferred:

CONTRACT PERFORMANCE

82 / 100

Breakdown:

Gas efficiency        91
Storage efficiency    68
Parallelism            54
Execution overhead     89

Then:

> You can probably improve this contract.

Button:

[ Improve score ]

The score should be explainable.

Do not create arbitrary numbers just to gamify.

If the score cannot yet be defensibly computed, do not ship it. Use the same visual treatment for measured categories without inventing a composite score.

---

# 13. First-Run UX

Goal: from landing page to first useful result in as few clicks as possible.

Ideal:

1. Connect GitHub
2. Choose repository
3. Choose contract
4. Analyze

That's it.

Do not force users to configure:
- Slither
- compiler settings
- simulation parameters
- model providers
- API keys
- chain settings
- YAML
- advanced thresholds

Put advanced controls behind:

[ Advanced ]

Defaults should be intelligent.

The first-run experience must feel almost effortless.

---

# 14. GitHub Workflow

The second core experience is:

> "Put ParaCheck in my PRs."

One clear action.

Every PR can produce:

    ✓ Security
    ✓ Gas
    ⚠ Parallelism
    ✓ Storage
    ✓ EVM compatibility

Then:

    ParaCheck found 2 optimization opportunities.

    Potential savings:
    ~X gas / 1,000 transactions

Only show economic numbers if calculated from actual available data.

GitHub Check Runs and annotations are a major product surface.

Do not force the developer into the ParaCheck dashboard for every finding.

---

# 15. Product Architecture Messaging

When explaining the technical product:

    Static analysis
    Slither + ParaCheck hot-slot classifier

    Dynamic analysis
    Foundry/anvil + trace data

    GitHub
    Check Runs + annotations

    Hosted control plane
    Cloudflare Pages + Workers + D1

    Execution
    GitHub Actions

Do not imply Cloudflare Workers run Foundry or arbitrary repository builds.

Use architecture diagrams sparingly.

The technical story should establish credibility, not overwhelm the homepage.

---

# 16. Claude / BYOK

Claude synthesis is an optional future capability, not the launch identity.

Future model:

- customer supplies their own Anthropic key
- customer pays Anthropic directly
- ParaCheck does not pay Claude usage
- keys remain encrypted
- keys are never passed to reviewed repository build tools
- model selection should initially use an allowlist

Launch behavior:
- deterministic findings
- deterministic Markdown rendering
- Claude disabled unless explicitly enabled

Do not headline the product around Claude.

Do not make "AI" the hero.

If mentioning it:

> Bring your own Claude key for AI-assisted explanations and remediation.

---

# 17. Design Philosophy

Primary aesthetic:

> Swiss-inspired technical software.

Reference feeling:
- Linear
- Vercel
- high-end developer tooling
- technical documentation
- precision instrumentation
- modern Swiss editorial design

But do not copy any brand literally.

The site should feel:
- precise
- quiet
- technical
- expensive
- confident
- restrained
- fast
- trustworthy

It should NOT feel:
- crypto-bro
- cyberpunk
- neon
- gamer
- generic AI startup
- enterprise dashboard
- marketing-heavy
- overly editorial
- poster-like

The first visual direction became too editorial/poster-like. The revised direction must remain a practical developer tool with a clear first action and live product proof.

---

# 18. Color System

Default palette:

Background:
#F7F7F5

Primary surface:
#FFFFFF

Secondary surface:
#F1F1EE

Primary text:
#111111

Secondary text:
#5F5F5A

Muted text:
#85857F

Border:
#DCDCD6

Strong border:
#BDBDB6

Accent:
Use exactly ONE accent color throughout the product.

Recommended accent:
#1D4ED8

Accent hover:
#1E40AF

Success:
#16803C

Warning:
#A16207

Critical:
#B42318

Do not use gradients.

Do not use purple AI gradients.

Do not use glowing effects.

Do not use excessive colored cards.

Severity colors should be small signals, not large backgrounds.

---

# 19. Typography

Use a modern neutral sans-serif.

Preferred:
- Inter
- Geist
- equivalent high-quality grotesk

Use a monospace font for:
- Solidity
- file paths
- function names
- gas values
- hashes
- technical metadata
- CLI output
- code diffs

Typography hierarchy:

Hero:
64–80px desktop
44–52px tablet
36–42px mobile

Hero line-height:
0.95–1.05

Section headings:
36–48px

Card headings:
16–20px

Body:
15–17px

Small metadata:
12–13px

Code:
13–14px

Avoid giant marketing copy everywhere.

Whitespace should do most of the visual work.

---

# 20. Layout

Maximum content width:
1200–1280px

Main horizontal padding:
32px desktop
20px mobile

Hero:
12-column grid

Preferred:
5 columns text
7 columns product proof

Sections:
large vertical spacing

Desktop:
120–180px between major sections

Mobile:
80–120px

Do not cram sections together.

The product should feel calm.

---

# 21. Grid / Swiss System

Use a subtle grid only where useful.

Grid:
- 12 columns
- consistent gutters
- strong alignment
- baseline rhythm
- clear left edges

Optional background grid:
1px lines
very low contrast
never decorative enough to compete with content

The grid should make the site feel engineered, not futuristic.

---

# 22. Borders

Prefer 1px borders.

Use:
- subtle rectangular containers
- square-ish or mildly rounded corners

Border radius:
4px–8px

Do not use:
- huge 24px rounded cards
- floating glassmorphism
- pill-shaped everything

Buttons can have:
6px–8px radius.

Tags can be pills only when semantically appropriate.

---

# 23. Cards

Cards should be used sparingly.

A card must contain a meaningful unit of information.

Avoid card-grid hell:

    [ card ]
    [ card ]
    [ card ]
    [ card ]

Prefer:

    one large product surface
    + small supporting information blocks

The product UI itself can use bordered panels.

Marketing cards should feel like slices of the product, not generic SaaS feature boxes.

---

# 24. Buttons

Primary button:
- dark/black or accent background
- white text
- 40–48px height
- 14–15px semibold
- 6–8px radius

Primary CTA:

[ Connect GitHub → ]

Secondary:
- white/background
- 1px border
- dark text

Tertiary:
- text link

Button copy should describe the action.

Good:
- Connect GitHub
- Analyze contract
- View evidence
- Fix this
- Open in GitHub
- Improve score

Bad:
- Learn More
- Get Started
- Discover
- Explore Now
- Supercharge

---

# 25. Navigation

Minimal navigation.

Suggested:

PARACHECK

Product
How it works
Docs
Pricing

[ Sign in ]
[ Connect GitHub ]

Do not overload navigation.

On scroll, keep it compact.

Header:
- thin
- white/off-white
- subtle bottom border
- sticky if appropriate

---

# 26. Motion

Motion should communicate state, not decoration.

Good:
- button hover
- finding expansion
- analysis progress
- score transition
- diff reveal
- measurement transition
- Check Run status
- subtle page transitions

Bad:
- floating blobs
- animated gradients
- excessive parallax
- scroll-jacking
- spinning crypto graphics
- constant movement

Animation timing:
- 120–180ms micro interactions
- 200–300ms component transitions
- 400–600ms larger reveals

Respect `prefers-reduced-motion`.

---

# 27. Analysis Progress UX

Do not show a generic spinner for 30 seconds.

Show meaningful progress:

    ANALYZING VAULT.SOL

    ✓ Repository loaded
    ✓ Compiler detected
    ✓ Slither analysis
    ✓ Storage access analysis
    ● Dynamic contention analysis
    ○ Optimization synthesis
    ○ Report generation

If a stage takes time, explain what is happening.

The developer should feel that the system is working intelligently.

---

# 28. Empty States

Never use generic:

> Nothing here yet.

Instead:

    NO REVIEWS YET

    Connect a repository and run your first
    performance analysis.

    [ Connect GitHub ]

Empty states should always explain:
- what this surface is
- why it is empty
- what the user should do next

---

# 29. Error States

Errors should be direct and useful.

Bad:

> Something went wrong.

Good:

    ANALYSIS FAILED

    Foundry could not compile this repository.

    Error:
    solc 0.8.24 is required.

    [ View logs ]
    [ Retry ]

Never hide technical details from technical users.

---

# 30. Dashboard

Dashboard should answer:

> "How are my contracts doing?"

Top-level:

    YOUR CONTRACTS

    12 repositories
    37 analyses
    8 optimizations found
    5 resolved

Then recent activity.

Example:

    Vault.sol
    Optimization found
    Storage contention
    2 hours ago

    Router.sol
    Analysis passed
    1 day ago

Do not turn the dashboard into enterprise analytics unless the data actually provides value.

---

# 31. Review Detail Page

Structure:

    BACK
    Vault.sol

    PERFORMANCE
    82 / 100

    6 findings

    [ Critical 2 ] [ High 2 ] [ Medium 2 ]

    ─────────────────────────────

    FINDING

    swap()

    Storage contention

    ...

    EVIDENCE
    ...

    RECOMMENDED CHANGE
    ...

    DIFF
    ...

    IMPACT
    ...

    [ Fix this ]
    [ Open in GitHub ]

Keep the primary action visible.

---

# 32. Technical Credibility

The site must make sophisticated developers believe the tool is real.

Show the actual methodology:

    STATIC
    Slither + storage access analysis

    DYNAMIC
    Foundry/anvil + execution traces

    PARALLELISM
    Storage conflict detection

    GITHUB
    Native PR Check Runs

Avoid meaningless badges like:
- "Powered by AI"
- "Next generation"
- "Enterprise ready"

Instead show:
- actual technologies
- actual execution flow
- actual evidence
- actual sample findings

---

# 33. Security / Trust

Developer tools touch source code.

Make trust information easy to find.

Explain:
- what is sent where
- where analysis runs
- how GitHub permissions work
- how credentials are handled
- how BYOK keys are protected
- what data is retained
- what is not retained

Do not make unsupported security claims.

Cloudflare controls the hosted control plane.
GitHub Actions performs repository analysis.

---

# 34. Billing UX

Current intended launch pricing:

Hobby:
$9/month
20 reviews

Pro:
$29/month
100 reviews

Enterprise:
custom

These values must remain synchronized across:
- billing code
- dashboard
- pricing page
- docs

Do not offer unlimited reviews.

The product runs repository compilation and analysis workloads, so usage must be quota-based.

Pricing page should be simple.

Example:

    HOBBY
    $9 / month

    20 reviews / month

    GitHub integration
    Static analysis
    Dynamic analysis
    PR checks

    [ Choose Hobby ]

    PRO
    $29 / month

    100 reviews / month

    Everything in Hobby
    Advanced analysis
    ...

    [ Choose Pro ]

    ENTERPRISE
    Custom

    Custom quota
    Custom deployment/support options

    [ Talk to us ]

Do not use fake discounts or countdowns.

---

# 35. SaaS Architecture Copy

If the architecture is shown publicly:

    Cloudflare Pages
          ↓
    Cloudflare Worker
          ↓
    Clerk / Stripe / GitHub / D1
          ↓
    GitHub Actions
          ↓
    Foundry + solc + Slither + ParaCheck
          ↓
    GitHub Check Run

The Worker is the control plane.

GitHub Actions is the compute plane.

This distinction should remain technically accurate everywhere.

---

# 36. Developer Workflow

Ideal flow:

LANDING PAGE
→ Connect GitHub
→ Select repo
→ Select contract
→ Analyze
→ See prioritized findings
→ Open finding
→ View evidence
→ Apply fix
→ Re-run
→ See measured improvement
→ Install PR checks
→ Ship

The product should progressively move the user from:
"Tell me what's wrong"
to:
"Help me fix it"
to:
"Automatically protect this repo."

---

# 37. The Product Flywheel

The recurring product loop is:

    WRITE
      ↓
    ANALYZE
      ↓
    FIND
      ↓
    FIX
      ↓
    MEASURE
      ↓
    PROVE
      ↓
    MERGE
      ↓
    REPEAT

The website should communicate this loop visually.

---

# 38. Landing Page Copy Principles

Every sentence should be:
- short
- concrete
- technically credible
- outcome-oriented

Prefer:

> Find what's making your contract expensive.

over:

> Leverage next-generation AI-powered intelligent optimization.

Prefer:

> See the storage access causing contention.

over:

> Unlock unprecedented parallel execution insights.

Prefer:

> Fix it. Measure it. Ship it.

over:

> Transform your development workflow.

Never use:
- revolutionize
- supercharge
- unlock
- empower
- next-generation
- cutting-edge
- seamless
- game-changing
- AI-powered (unless technically relevant)

---

# 39. Emotional Design

The developer should experience:

### Before
"I know this contract is slow/expensive but I don't know why."

### During
"Oh. There it is."

### Fix
"That's literally the change I need."

### After
"Wait — it actually improved."

### Retention
"I want this running on every PR."

Design every major interaction around this emotional progression.

---

# 40. Microcopy

Analysis button:
> Analyze contract

Loading:
> Looking for expensive paths...

Static stage:
> Mapping storage access...

Dynamic stage:
> Measuring contention...

Success:
> Analysis complete.

Finding:
> Optimization opportunity

Critical:
> Material execution impact

Evidence:
> Show evidence

Fix:
> Show me the fix

After measurement:
> Re-run analysis

Success:
> Improvement verified.

PR installation:
> Protect this repo

---

# 41. Demo Experience

The marketing site should contain a convincing interactive demo.

Preferred interaction:

    CONTRACT
    NaiveAMM.sol

    [ Analyze ]

Then staged output:

    1. Static analysis
    2. Storage access map
    3. Dynamic execution
    4. Contention analysis
    5. Optimization report

Then:

    3 optimization opportunities

    1 critical
    1 high
    1 medium

The demo must use clearly labeled sample/demo data.

Never imply demo measurements are from the visitor's code.

---

# 42. Visualizing Storage Contention

This is one of the most valuable technical visuals.

Use a simple matrix:

        swap A   swap B   claim
swap A    —       HIGH      LOW
swap B   HIGH       —       LOW
claim    LOW       LOW       —

Or a small node graph:

    swap A ─────── reserve0
       │
       └────────── reserve1
                    │
    swap B ─────────┘

The visualization should be sparse and understandable.

Avoid flashy Web3 network graphs.

---

# 43. Code Diff Visual Design

Use a high-quality monospace font.

Show:
- file name
- function name
- line numbers
- small focused diff
- syntax highlighting
- minimal chrome

Example:

    Vault.sol
    swap()

    - reserve0 = newReserve0;
    - reserve1 = newReserve1;
    + _updateBand(bandId, newReserve0, newReserve1);

Then:

    Estimated impact
    ↓ contention
    ↑ parallel execution

The diff should never occupy the whole screen unless the user explicitly expands it.

---

# 44. Mobile

Mobile is not an afterthought.

Hero:
- stack vertically
- CTA immediately visible
- product proof below

Dashboard:
- one-column
- findings full width
- sticky action where useful

Tables:
- collapse into cards or horizontal scroll

Code:
- horizontal scroll

Do not shrink desktop UI until it is unreadable.

---

# 45. Accessibility

Must have:
- semantic HTML
- keyboard navigation
- visible focus states
- sufficient contrast
- reduced-motion support
- accessible buttons
- accessible status indicators
- no color-only meaning

Severity must use:
icon + label + color

not color alone.

---

# 46. Performance

The marketing site itself should embody the product philosophy.

Target:
- fast initial load
- minimal JavaScript
- optimized fonts
- no giant animation libraries unless necessary
- lazy-load heavy interactive demo code
- static-first rendering
- minimal third-party scripts

Avoid loading a huge frontend bundle just to render a landing page.

Cloudflare Pages is the intended hosted frontend.

---

# 47. Responsive Design

Breakpoints should be chosen based on layout needs rather than arbitrary device names.

At desktop:
- 12-column grid
- large hero
- two-column product proof

At tablet:
- 8-column or stacked layout

At mobile:
- single-column
- compact nav
- full-width primary CTA
- findings become vertical

Maintain generous whitespace.

---

# 48. Visual Hierarchy Rules

Every screen should have exactly one dominant action.

Example dashboard:
dominant action = Analyze

Finding:
dominant action = Fix this

After fix:
dominant action = Re-run

After verification:
dominant action = Install PR checks

Do not give five buttons equal visual prominence.

---

# 49. What NOT to Build

Do not build:

- generic AI chat as the homepage centerpiece
- giant chatbot window
- crypto coin imagery
- neon purple gradients
- futuristic 3D blockchain graphics
- animated matrix rain
- excessive glassmorphism
- giant dashboard mockups with fake data
- meaningless metrics
- dozens of feature cards
- fake testimonials
- fake savings numbers
- arbitrary performance scores
- generic "AI code reviewer" messaging
- complicated onboarding
- mandatory model configuration
- mandatory YAML setup before first analysis

---

# 50. What TO Build

Priority 1:
- extremely clear hero
- GitHub connection
- repository selection
- one-click analysis
- prioritized optimization report
- evidence view
- fix/diff interaction
- re-run analysis
- measured before/after result

Priority 2:
- GitHub PR Check Runs
- inline annotations
- repo dashboard
- analysis history
- billing/quota surfaces

Priority 3:
- optimization score if defensible
- Claude BYOK explanations
- coding-agent handoffs
- deeper performance analytics

---

# 51. Agent Implementation Rules

When implementing this site:

1. Build the visual system before individual pages.
2. Create reusable tokens for colors, spacing, typography, radii, shadows, and borders.
3. Create reusable components:
   - Navbar
   - Button
   - Badge
   - Finding
   - FindingList
   - AnalysisProgress
   - CodeDiff
   - ImpactMetric
   - Score
   - RepoCard
   - CheckRunStatus
   - EmptyState
   - ErrorState
4. Reuse product components on the marketing site so the marketing site previews the real product.
5. Do not invent visual styles page-by-page.
6. Keep all components aligned to the same grid.
7. Prefer CSS transitions over JavaScript animation.
8. Use actual product terminology.
9. Use realistic technical data for demos and label demo data.
10. Never fabricate customer logos, metrics, testimonials, performance numbers, or savings.
11. Do not introduce a new color without checking the design system.
12. Do not introduce a new radius scale without checking the design system.
13. Do not add decorative UI that does not communicate information.
14. Make the first CTA obvious.
15. Make every state useful.

---

# 52. Definition of "Perfect"

The site is successful if a Solidity developer can answer these questions almost immediately:

1. What is ParaCheck?
   → A performance/optimization tool for Solidity.

2. Why should I care?
   → It finds expensive gas/storage/execution patterns and parallelism problems.

3. Is this just an AI reviewer?
   → No. The core findings come from deterministic static and runtime analysis.

4. Can it tell me why the contract is expensive?
   → Yes.

5. Can it tell me what to change?
   → Yes.

6. Can it prove the change helped?
   → Yes, when the relevant behavior can be measured.

7. Can it run on my PRs?
   → Yes.

8. Do I need to configure a bunch of things?
   → No. The default path should be a few clicks.

9. Can I use my own Claude?
   → Future/optional BYOK Claude synthesis.

10. Does it look like a serious developer tool?
    → It should feel precise, quiet, technical, and premium.

The final emotional reaction should be:

> "Holy shit. I can finally see why this contract is expensive."

followed by:

> "And it literally showed me what to change."

---

# 53. Final North Star

ParaCheck is not selling AI.

ParaCheck is not selling reports.

ParaCheck is not selling dashboards.

ParaCheck is selling **certainty**.

The developer starts with:

> "Something about this contract is expensive."

ParaCheck should get them to:

> "I know exactly what is expensive."

Then:

> "I know exactly what to change."

Then:

> "I measured the improvement."

Then:

> "My PR is protected from doing this again."

Everything in the website and product UX should serve that progression.
