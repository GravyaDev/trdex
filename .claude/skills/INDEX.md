# Claudify Skills Library

> 2726+ professional skills across 46 categories.
> Each skill is a structured operational procedure — not a prompt template.

## How Skills Work

Skills are invoked automatically when Claude detects a relevant task, or manually via `/skill-name`.
Every skill:
- Reads your project context from `memory.md` and `knowledge-base.md`
- Follows a structured process with named frameworks
- Produces a defined output format
- Validates quality before delivery
- Updates project memory with learnings

## Categories

| Category | Skills | Description |
|----------|--------|-------------|
| [3D Web & WebGL](./3d-web/) | 18 | Three.js, React Three Fiber, Spline, shaders, interactive 3D scenes |
| [Agent Systems & Orchestration](./agent-systems/) | 32 | Multi-agent systems, memory architectures, tool building, evaluation |
| [Agriculture & Farming](./agriculture/) | 45 | Crop planning, farm budgets, soil management |
| [AI & Automation](./ai-automation/) | 83 | Prompt engineering, workflow automation, AI strategy |
| [Blockchain & Web3](./blockchain-web3/) | 10 | Solidity, DeFi, NFT, smart contracts, web3 testing |
| [Construction & Trades](./construction/) | 42 | Project estimation, safety plans, contractor management |
| [Consulting & Strategy](./consulting/) | 62 | Frameworks, client proposals, strategy documents |
| [Content & Copywriting](./content/) | 104 | Written content across all formats — blog posts, whitepapers, scripts |
| [Context Engineering](./context-engineering/) | 13 | Context window management, compression, degradation analysis |
| [Conversion Rate Optimization](./cro-conversion/) | 7 | A/B tests, forms, popups, onboarding flows, paywall optimization |
| [Customer Success & Support](./customer-success/) | 50 | Onboarding, churn, NPS, support workflows |
| [Data & Analytics](./data/) | 77 | Dashboards, reports, data pipelines, KPI frameworks |
| [Data Science Libraries](./data-science-libs/) | 16 | matplotlib, scikit-learn, pandas, seaborn, polars, networkx |
| [Database Engineering](./database-engineering/) | 27 | PostgreSQL, vector DB, optimization, migrations, Drizzle, Prisma |
| [Design & Creative](./design/) | 82 | UX audits, design systems, creative briefs, UI patterns |
| [DevOps & Cloud](./devops-cloud/) | 59 | Docker, Kubernetes, Terraform, CI/CD, cloud platforms |
| [Document Generation](./document-generation/) | 5 | DOCX, PDF, PPTX, XLSX creation and manipulation |
| [E-commerce](./ecommerce/) | 60 | Online store management, conversion optimization, marketplace strategy |
| [Education & Training](./education/) | 56 | Course creation, curriculum design, assessment, workshops |
| [Email Marketing](./email/) | 53 | Campaigns, sequences, deliverability, A/B testing |
| [Energy & Sustainability](./energy/) | 45 | Energy audits, carbon footprint, renewable plans |
| [Finance & Accounting](./finance/) | 69 | Budgets, forecasts, investor decks, financial models |
| [Fitness & Wellness](./fitness-wellness/) | 45 | Training plans, nutrition, coaching programs |
| [Food & Beverage](./food-beverage/) | 42 | Menu engineering, catering, restaurant operations |
| [Game Development](./game-dev/) | 8 | Unity, Unreal, Godot, Bevy, multiplayer game systems |
| [Healthcare](./healthcare/) | 70 | Clinical workflows, patient education, compliance, health analysis |
| [HR & People](./hr/) | 60 | Hiring, onboarding, performance reviews, org design |
| [Legal & Compliance](./legal/) | 61 | Contracts, policies, risk assessments, GDPR |
| [Marketing & Advertising](./marketing/) | 89 | Campaign strategy, audience research, brand positioning |
| [Media & Publishing](./media/) | 46 | Content publishing, editorial management, audience growth |
| [Mobile Development](./mobile-dev/) | 19 | iOS, Android, Flutter, React Native, Expo |
| [NLP & LLM Engineering](./nlp-llm/) | 28 | LLM evaluation, RAG, prompt engineering, fine-tuning |
| [Nonprofit & Social Impact](./nonprofit/) | 50 | Fundraising, grant writing, volunteer management |
| [Operations & Project Management](./operations/) | 77 | Process design, project planning, resource management |
| [Product Management](./product/) | 70 | Product strategy, roadmaps, user research, prioritization |
| [Programming Languages](./programming-languages/) | 61 | Per-language expert skills — Python, Go, Rust, TypeScript, etc. |
| [Personal Productivity](./productivity/) | 125 | Time management, goal setting, decision making, communication |
| [Real Estate](./real-estate/) | 45 | Property listings, market analysis, investment analysis |
| [SaaS Integrations](./saas-integrations/) | 98 | Per-tool automations — Slack, HubSpot, Jira, Notion, etc. |
| [Sales & Revenue](./sales/) | 70 | Prospecting, proposals, pipeline management, forecasting |
| [Security & Pentesting](./security-pentesting/) | 64 | Offensive security, SAST, fuzzing, red team, OWASP |
| [SEO & Search](./seo/) | 74 | Keyword research, on-page, technical, link building, analytics |
| [Social Media](./social-media/) | 69 | Platform-specific content, scheduling, engagement, analytics |
| [Software Development](./development/) | 323 | Architecture, code review, APIs, testing, debugging, frameworks |
| [Startup & Entrepreneurship](./startup/) | 63 | Business planning, fundraising, validation, growth |
| [Travel & Hospitality](./travel/) | 54 | Trip planning, hospitality operations, guest experience |

## Dedicated Skills (project-specific, standalone)

| Skill | Description |
|-------|-------------|
| [persistent-memory-stack](./persistent-memory-stack/SKILL.md) | Bootstrap 6-tier persistent memory for AI agent systems — PostgreSQL + pgvector + Python templates |
| [multi-agent-brainstorming](./multi-agent-brainstorming/SKILL.md) | Structured design review with enforced agent roles |
| [brainstorming](./brainstorming/SKILL.md) | Single-agent ideation with Understanding Lock |
| [autoresearch](./autoresearch/SKILL.md) | Autonomous deep research with source validation |
| [web-fetch](./web-fetch/SKILL.md) | Fetch and extract structured content from web pages |

---

## Quick Start

1. Run any skill by asking Claude to perform the task (skills auto-detect)
2. Or invoke directly: "Use the [skill-name] skill to..."
3. Skills read your project context automatically
4. Output follows a structured format with quality checks
5. Learnings are captured for future improvement

## Quality Standard

Every skill in this library meets a consistent quality standard:
- **Actionable**: Every step tells Claude exactly what to do
- **Specific**: Includes concrete numbers, frameworks, and thresholds
- **Complete**: Covers the full workflow from input to deliverable
- **System-aware**: Integrates with memory, knowledge base, and audit trail
- **Validated**: Includes quality checklist before delivery
