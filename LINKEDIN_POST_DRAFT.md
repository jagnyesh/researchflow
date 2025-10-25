# LinkedIn Post Draft - REVISED

**Correct Framing:** AI should handle administrative PM work, with SMEs (informaticians, biostatisticians) providing technical expertise. Meta-story: Used agentic AI coding to build an agentic AI system.

---

## Option A: "AI Built with AI" (Meta Story)

I used AI agents to build an AI agent system. And that experience taught me exactly where AI belongs in healthcare workflows.

**The Setup:**

As a biomedical informatician supporting clinical research, I spent half my time on administrative coordination: scheduling stakeholder meetings, routing requests between teams, tracking workflow status, sending status updates. The other half? Technical work that required deep expertise: validating SQL queries, understanding data models, ensuring computational accuracy.

Only one of those needed a human expert.

**The Experiment:**

I built ResearchFlow entirely using agentic AI coding (Claude Code). The system uses 7 AI agents that orchestrate clinical research data requests from natural language to delivery - handling all the administrative PM work I used to do manually.

But here's the critical design choice: informaticians and biostatisticians remain in the loop as human approval gates for every technical decision. No SQL query executes without expert review. No data extraction proceeds without validation.

**The Result:**

- Turnaround time: Weeks → Hours (AI handles coordination at machine speed)
- Technical quality: Maintained at 100% (SMEs validate all queries, computations, QA)
- The PM work? Fully delegated to AI agents (scheduling, routing, status tracking, stakeholder communication)

**The Insight:**

Building AI with AI proved the concept: administrative coordination is exactly where AI should own the workflow. Subject matter experts should focus on what they're irreplaceable for - technical judgment about data organization, computational validity, and domain expertise.

We don't need AI to replace experts. We need AI to free experts from administrative work.

I've open-sourced ResearchFlow (MIT License) because this division of labor - AI for coordination, humans for expertise - represents a sustainable architecture for healthcare AI.

**Link:** https://github.com/jagnyesh/researchflow

**Question:** For those building AI systems in technical domains - where have you found the clearest boundaries between work AI should own vs. where human experts are essential?

---

## Option B: "The Right Division of Labor" (Technical Focus)

Clinical research data requests have two bottlenecks: administrative coordination and technical expertise.

Only one of them needs a human.

**The Technical Reality:**

As a biomedical informatician at an academic medical center, my work split cleanly:

**Administrative (50% of time):**
- Scheduling kickoff meetings with research teams
- Routing requests between informaticians, biostatisticians, IRB coordinators
- Tracking workflow status across 15+ states
- Sending status updates to stakeholders
- Coordinating approvals and escalations

**Technical (50% of time):**
- Validating SQL queries against FHIR data models
- Reviewing cohort definitions for computational accuracy
- Ensuring proper de-identification based on data use agreements
- QA validation of delivered datasets

Guess which half actually required domain expertise?

**The Solution:**

I built ResearchFlow - a 7-agent AI system that handles all the administrative coordination while keeping informaticians and biostatisticians as human-in-loop for technical decisions.

The architecture:
- **AI Agents Own:** Workflow orchestration, stakeholder communication, meeting scheduling, status tracking, data packaging
- **SMEs Validate:** SQL queries, feasibility calculations, data quality, PHI scrubbing

Result: 95% reduction in turnaround time (weeks → hours), but 100% expert validation on technical decisions.

**The Meta-Proof:**

I built the entire system using agentic AI coding. If AI can build a multi-agent system with 18,000+ lines of code, it can certainly handle meeting scheduling and workflow routing.

**The Broader Lesson:**

We need to stop asking "Can AI replace this expert?" and start asking "Which parts of this expert's work require expertise vs. administrative coordination?"

ResearchFlow shows one answer: Let AI own the PM work. Keep experts for technical judgment.

Open source (MIT): https://github.com/jagnyesh/researchflow

**Question:** What work in your technical domain is administrative coordination vs. irreplaceable expertise? Where's the boundary?

---

## Option C: "From SME to Product Manager" (RECOMMENDED)

**Making the transition from biomedical informatician to Product Manager taught me which work needs experts and which needs coordination.**

The insight came from analyzing my own time as an informatician supporting clinical research:

**~50% Administrative PM Work:**
- Scheduling stakeholder meetings
- Routing requests between teams (researchers → informaticians → biostatisticians → IRB)
- Tracking workflow status (15 states from submission to delivery)
- Sending status updates and notifications
- Coordinating approval workflows
- Managing escalations

**~50% Technical Expertise:**
- Validating SQL queries against complex FHIR data models
- Reviewing phenotype definitions for clinical accuracy
- Ensuring computational validity of cohort calculations
- Approving de-identification methods based on data use agreements
- QA validation of datasets

The administrative work was essential but didn't require years of informatics training. The technical work? Absolutely required domain expertise.

**The Experiment:**

I built ResearchFlow - an AI-powered multi-agent system for clinical research automation - entirely using agentic AI coding (Claude Code). The meta-experiment: Can AI build AI that handles the PM work I used to do?

**The Architecture:**

Seven AI agents orchestrate the entire workflow:
- Requirements extraction from natural language
- SQL-on-FHIR query generation
- Stakeholder meeting scheduling
- Multi-source data extraction
- Quality assurance automation
- Data packaging and delivery
- Approval workflow coordination

**But here's the critical design:**

Informaticians and biostatisticians remain as mandatory approval gates:
- No SQL executes without informatician review
- No requirements proceed without validation
- No data extracts without authorization
- No datasets deliver without QA approval

**The Result:**

- **AI handles:** All administrative coordination (routing, scheduling, status tracking, notifications)
- **SMEs validate:** All technical decisions (SQL queries, computations, data quality)
- **Outcome:** Weeks → Hours turnaround, but 100% expert validation maintained

**The Broader Insight:**

Building AI with AI proved the concept. Administrative PM work - the coordination, orchestration, and routing - is exactly where AI should own the workflow.

Subject matter experts should spend 100% of their time on what they're irreplaceable for: technical judgment.

I've open-sourced ResearchFlow (MIT License) because this architecture - AI for coordination, humans for expertise - shows a sustainable path for AI in healthcare and other regulated technical domains.

**Link:** https://github.com/jagnyesh/researchflow

**For fellow PMs and technical leaders:** Where have you found the clearest boundaries between administrative coordination (AI-ready) and irreplaceable expertise (human-essential) in your domain?

---

## Why Option C is Recommended

**Strengths:**
1. **Personal Journey:** Informatician → Product Manager transition is authentic and shows growth
2. **Specific Time Breakdown:** The 50/50 split is concrete and memorable
3. **Meta-Story:** "AI built with AI" proves the concept
4. **Clear Stakeholders:** Researchers need data, SMEs (informaticians/biostatisticians) provide technical expertise
5. **Right Division of Labor:** AI = admin/PM work, Humans = technical judgment
6. **Career Positioning:** Shows product thinking (analyzing work to find automation opportunities)
7. **Not Confrontational:** Doesn't diminish PM work, just shows where AI excels
8. **Engagement Hook:** Asks readers to identify boundaries in their own domains

**Tone:** Professional, thoughtful, demonstrates strategic thinking about AI adoption, positions you as someone who understands both technical work AND how to build products that serve technical experts.

**Key Differences from Original Drafts:**

❌ **Old Framing:** PM/non-technical staff have tacit knowledge (wrong!)
✅ **New Framing:** PM work is admin coordination that AI can handle

❌ **Old Stakeholders:** Technical vs. non-technical staff
✅ **New Stakeholders:** Researchers (need data) + SMEs (provide expertise)

❌ **Old Division:** Humans have "tacit knowledge" AI can't replicate
✅ **New Division:** AI handles coordination, SMEs handle technical validation

❌ **Old Story:** Built system with human-in-loop (generic)
✅ **New Story:** Used AI to build AI, proving AI can handle PM work

---

## Posting Recommendations

**Visual:** Attach `diagrams/ResearchFlow Architecture.png` to show the 7-agent system

**Hashtags:** #HealthcareAI #ClinicalResearch #ProductManagement #AgenticAI #FHIR #OpenSource #AIAutomation #TechLeadership

**Best Time to Post:** Tuesday or Thursday, 8-10 AM (highest engagement for professional content)

**Follow-up Engagement:**
- Respond to comments within first 2 hours
- Share genuine insights from your informatician experience
- Ask follow-up questions to commenters about their own AI/human boundaries

**Potential Concerns Addressed:**

1. **"Isn't this dismissive of PM work?"**
   - No - it shows PM coordination work is valuable AND automatable
   - Frees humans for higher-leverage work

2. **"Won't this threaten informatician jobs?"**
   - Architecture explicitly keeps informaticians for technical work
   - Actually elevates their role to pure expertise vs. admin tasks

3. **"Is full automation safe in healthcare?"**
   - Clear answer: No. That's why SMEs approve all technical decisions
   - Architecture ensures safety through mandatory expert validation

---

**Final Note:** Option C tells YOUR story (informatician → PM), demonstrates YOUR insight (50/50 time split), proves YOUR concept (built AI with AI), and positions YOU correctly (product thinker who understands technical work).

This is the most authentic and differentiated version.
