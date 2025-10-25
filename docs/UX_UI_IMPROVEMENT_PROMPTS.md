# UX/UI Improvement Prompts for ResearchFlow

**Goal:** Create a unified, modern, user-friendly design system across all three Streamlit frontends (Researcher Portal, Admin Dashboard, Research Notebook) using Claude + Playwright MCP for visual testing and iteration.

---

## Current State Analysis

### Three Frontends:
1. **Researcher Portal** ([researcher_portal.py](app/web_ui/researcher_portal.py)) - Port 8501
   - For researchers to submit and track data requests
   - iOS glass-like design (already styled)
   - Conversational AI interface with chat bubbles
   - Multi-phase workflow (info → conversation → review)

2. **Admin Dashboard** ([admin_dashboard.py](app/web_ui/admin_dashboard.py)) - Port 8502
   - For informaticians/admins to approve requests
   - iOS glass-like design (same style as portal)
   - Tabs: Overview, Agent Metrics, Pending Approvals, Escalations, Analytics
   - Complex data tables and approval workflows

3. **Research Notebook** ([research_notebook.py](app/web_ui/research_notebook.py)) - Port 8503
   - Interactive research assistant
   - Simpler CSS (chat bubbles, warning boxes, success boxes)
   - Conversational + data visualization
   - Two-stage workflow (feasibility → extraction)

### Current Issues:
- **Inconsistent styling**: Research Notebook uses different CSS than Portal/Dashboard
- **Mixed design languages**: iOS glass effect vs. basic colored boxes
- **No design system**: Colors, spacing, typography not standardized
- **Limited mobile responsiveness**: Streamlit defaults, not optimized
- **Accessibility gaps**: No ARIA labels, keyboard navigation issues
- **Visual hierarchy unclear**: Important actions don't stand out enough

---

## Phase 1: Foundation - Create Design System

### Prompt for Claude:

```markdown
I need you to create a comprehensive design system for my ResearchFlow application with three Streamlit frontends. Use Playwright MCP to visually test the changes across all three apps.

**Context:**
- Healthcare/clinical research application
- Three user roles: Researchers, Informaticians/Admins, Research Analysts
- Need to balance professional credibility with modern, approachable UX
- Must work on desktop (primary) and tablet (secondary)

**Current tech stack:**
- Streamlit (Python web framework)
- Custom CSS injected via st.markdown()
- Three separate apps on ports 8501, 8502, 8503

**Design System Requirements:**

1. **Color Palette** (create a cohesive palette):
   - Primary color for actions (currently blue #007AFF)
   - Secondary color for info/neutral states
   - Success color (green) for approvals/completed states
   - Warning color (amber) for pending reviews
   - Danger color (red) for rejections/errors
   - Neutral grays for text hierarchy
   - Background gradients or solid colors

2. **Typography Scale**:
   - H1, H2, H3 consistent sizing and weights
   - Body text readable at 16px minimum
   - Code/monospace for technical content
   - Suggest font pairings (system fonts for performance)

3. **Spacing System**:
   - Base unit (4px or 8px grid)
   - Consistent padding/margin across components
   - Card spacing, section separation

4. **Component Library** (define styles for):
   - Buttons (primary, secondary, danger)
   - Input fields (text, textarea, select)
   - Cards/containers
   - Tables/data grids
   - Chat messages (user vs assistant)
   - Status badges (workflow states)
   - Metrics/KPI cards
   - Approval gates (critical vs normal)
   - Toast notifications
   - Progress indicators

5. **Glass Morphism vs Flat Design**:
   - Currently using iOS glass effect - should we keep, modify, or replace?
   - Suggest modern alternative if glass effect feels dated

**Deliverables:**
1. CSS file with all design tokens (colors, spacing, typography)
2. Component-specific CSS classes
3. Dark mode support (optional but nice)
4. Accessibility considerations (WCAG AA)

**Use Playwright to:**
- Screenshot current state of all three apps
- Show before/after comparisons
- Test on different viewport sizes (1920x1080, 1366x768, iPad)
```

---

## Phase 2: Researcher Portal Modernization

### Prompt for Claude:

```markdown
Using the design system we created, modernize the Researcher Portal (port 8501) with focus on user experience.

**Current file:** app/web_ui/researcher_portal.py

**User Journey:**
1. Researcher fills out basic info (name, email, IRB number)
2. Has conversational chat with AI to define requirements
3. Reviews extracted requirements
4. Submits request
5. Tracks request progress in sidebar

**UX Problems to Fix:**

1. **Chat Interface**:
   - Current: Blue bubbles (user) and gray bubbles (assistant) - feels cramped
   - Desired: Modern chat UI like ChatGPT/Claude with better spacing, avatars/icons, timestamps
   - Add typing indicator when AI is thinking
   - Smooth scroll to latest message
   - Clear visual separation between messages

2. **Progress Indicator**:
   - Current: Simple progress bar showing "completeness score"
   - Desired: Step indicator showing phases (Info → Conversation → Review → Submit)
   - Make current phase clear, show completed phases as checkmarks

3. **Final Review Screen**:
   - Current: Wall of text with nested details
   - Desired: Scannable cards for each section (criteria, data elements, timeframe)
   - Visual hierarchy: most important info prominent
   - Edit buttons inline for quick changes

4. **Sidebar (My Requests)**:
   - Current: Small expanders with truncated IDs
   - Desired: Request cards with status badges, visual state indicators
   - Color-coded by status (pending=yellow, approved=green, etc.)
   - Quick actions visible on hover

5. **Empty States**:
   - Add friendly illustrations/icons when no requests exist
   - Guidance text explaining next steps

**Accessibility:**
- Ensure chat is keyboard navigable (Tab, Enter to send)
- Screen reader friendly labels
- Focus states visible
- Color not only indicator (use icons + text)

**Use Playwright to:**
- Navigate through full user journey
- Screenshot each phase
- Test form validation
- Verify chat scrolling behavior
- Check mobile viewport
```

---

## Phase 3: Admin Dashboard Optimization

### Prompt for Claude:

```markdown
Apply the design system to Admin Dashboard (port 8502) with focus on information density and decision-making.

**Current file:** app/web_ui/admin_dashboard.py

**User Journey:**
1. Admin sees overview of all requests
2. Checks agent metrics/system health
3. Reviews pending approvals (CRITICAL: SQL queries need review)
4. Handles escalations
5. Views analytics/ROI data

**UX Problems to Fix:**

1. **Critical SQL Review UI**:
   - Current: SQL code in expander, warnings below
   - Problem: Easy to miss critical details, no visual emphasis on danger
   - Desired:
     - **CRITICAL** badge in red for SQL approvals
     - SQL syntax highlighting with line numbers
     - Checklist of validation steps (syntax ✓, date filters ✓, etc.)
     - Side-by-side: SQL query | Expected impact/cohort size
     - Diff view if modifications made

2. **Approval Queue**:
   - Current: Collapsible cards, hard to see urgency
   - Desired:
     - Kanban-style board or priority queue
     - Visual urgency indicators (< 2hrs = red, < 6hrs = yellow)
     - Batch approval for non-critical items
     - Quick approve/reject buttons (don't hide in expanders)

3. **Agent Metrics Table**:
   - Current: Static data table
   - Desired:
     - Sparklines showing trends (success rate over time)
     - Color-coded status (green=idle, blue=working, red=failed)
     - Alert badges for agents with high failure rates
     - Drill-down to see individual executions

4. **Analytics Charts**:
   - Current: Basic Streamlit line/bar charts
   - Desired:
     - Professional data viz (consider Plotly for interactivity)
     - Tooltips on hover
     - Date range selector
     - Export to PNG/CSV buttons

5. **Filter & Search**:
   - Add global search for request IDs
   - Filter approvals by type, urgency, assignee
   - Save filter presets ("My Reviews", "Urgent Only")

6. **Auto-refresh Indicator**:
   - Current: Checkbox + dropdown (functional but bland)
   - Desired: Animated indicator when refreshing
   - Show "Live" badge when auto-refresh on
   - Countdown to next refresh

**Information Architecture:**
- Prioritize critical actions (SQL reviews) over metrics
- Use color strategically (red = requires immediate action)
- Progressive disclosure (summary → details on click)

**Use Playwright to:**
- Test approval workflow (approve, reject, modify)
- Verify urgency indicators update correctly
- Check table sorting/filtering
- Test auto-refresh behavior
- Ensure charts render properly
```

---

## Phase 4: Research Notebook Polish

### Prompt for Claude:

```markdown
Unify Research Notebook (port 8503) with the design system and add data science UX best practices.

**Current file:** app/web_ui/research_notebook.py

**User Journey:**
1. Analyst asks question in natural language
2. AI interprets intent (feasibility check vs full extraction)
3. Shows feasibility results (cohort size, data availability)
4. If approved, submits full extraction request
5. Tracks request through approval workflow

**UX Problems to Fix:**

1. **Intent Detection Clarity**:
   - Current: Implicit - user doesn't know what AI will do
   - Desired:
     - After user types, show: "I understand you want to: [feasibility check / data extraction]"
     - Confirmation button: "Yes, run feasibility" vs "No, I want full data"
     - Clear explanation of difference

2. **Feasibility Results**:
   - Current: Basic cards with numbers
   - Desired:
     - Visual cohort funnel (total patients → inclusion → exclusion → final cohort)
     - Data availability heatmap (which fields have 100% vs 50% coverage)
     - Comparison to similar requests (if available)
     - "Should I proceed?" recommendation

3. **Query Refinement**:
   - Add: "Refine query" button to adjust criteria without starting over
   - Show SQL query generated (with toggle to hide technical details)
   - Side-by-side: Natural language → SQL

4. **Approval Tracking**:
   - Current: Separate approval tracker component
   - Desired:
     - Embedded timeline view in chat
     - Real-time status updates (WebSocket or polling)
     - Notifications when approval needed
     - Direct link to admin dashboard for self-service review

5. **Data Visualization**:
   - When feasibility results show:
     - Bar chart of cohort breakdown
     - Pie chart of data element availability
     - Timeline showing patient distribution over time

6. **Export & Share**:
   - Add: "Export chat transcript" (Markdown, PDF)
   - Share query with team (generate shareable link)
   - Save query templates for common requests

**Conversational UX:**
- Add suggested follow-up questions (chips below AI response)
- "Start over" button always visible
- Undo/redo for query changes

**Use Playwright to:**
- Test full feasibility → extraction workflow
- Verify charts render correctly
- Test query refinement flow
- Check approval tracking updates
- Validate export functionality
```

---

## Phase 5: Cross-App Consistency

### Prompt for Claude:

```markdown
Now that all three apps have been modernized individually, ensure perfect consistency across them.

**Create Shared Component Library:**

File: `app/web_ui/shared/design_system.py`

```python
# Centralized CSS and component functions all apps can import
def get_base_styles() -> str:
    """Returns CSS string with design system"""

def render_status_badge(status: str) -> str:
    """Renders consistent status badges"""

def render_metric_card(label: str, value: str, delta: str = None) -> None:
    """Renders consistent KPI cards"""

def render_approval_action_buttons(approval_id: str, on_approve, on_reject) -> None:
    """Consistent approval buttons across apps"""
```

**Consistency Checklist:**

1. **Colors**: All apps use same palette (no one-off colors)
2. **Spacing**: Grid system applied uniformly
3. **Typography**: Same font sizes/weights for H1, H2, H3, body
4. **Buttons**: Primary/secondary/danger look identical
5. **Status badges**: Same colors for workflow states
6. **Chat bubbles**: Same style in Portal and Notebook
7. **Tables**: Same header colors, row styling
8. **Forms**: Input fields identical styling
9. **Sidebar**: Same width, background, styling
10. **Animations**: Consistent transitions (buttons, loaders)

**Navigation Between Apps:**

Add header with app switcher:
```
[🔬 Researcher Portal] [⚙️ Admin Dashboard] [🤖 Research Notebook]
```
- Highlight current app
- Quick switch between apps
- Show user role badge

**Documentation:**

Create: `docs/DESIGN_SYSTEM.md`
- All color codes with usage guidelines
- Component examples with screenshots
- Do's and Don'ts
- Accessibility notes

**Use Playwright to:**
- Screenshot all three apps side-by-side
- Create visual regression tests
- Generate component gallery (Storybook-style)
- Test color contrast ratios (WCAG compliance)
- Verify consistent spacing with visual diff
```

---

## Phase 6: Playwright Visual Testing Strategy

### Prompt for Claude:

```markdown
Set up automated visual testing for all three Streamlit apps using Playwright MCP.

**Test Scenarios:**

1. **Researcher Portal:**
   - Initial load (empty state)
   - Form filled with validation errors
   - Active conversation with 5+ messages
   - Final review screen with complete requirements
   - Sidebar with 3 requests (different states)

2. **Admin Dashboard:**
   - Overview tab with 10 requests
   - Agent metrics table (7 agents)
   - Pending approvals with urgent SQL review
   - Escalations tab (empty state)
   - Analytics charts with real data

3. **Research Notebook:**
   - Welcome screen
   - Feasibility results displayed
   - Extraction request submitted
   - Approval tracking in progress

**Visual Regression Tests:**
```python
# Pseudo-code for Playwright tests

async def test_researcher_portal_chat_ui():
    await page.goto('http://localhost:8501')
    await page.fill('input[name="name"]', 'Dr. Test')
    await page.click('button:has-text("Start Conversation")')

    # Take screenshot of chat interface
    await page.screenshot(path='screenshots/researcher_portal_chat.png')

    # Compare to baseline
    assert_visual_match('researcher_portal_chat.png')

async def test_admin_sql_approval():
    await page.goto('http://localhost:8502')
    await page.click('text=Pending Approvals')
    await page.click('text=SQL REVIEW (CRITICAL)')

    # Screenshot SQL approval card
    await page.screenshot(path='screenshots/admin_sql_approval.png')
    assert_visual_match('admin_sql_approval.png')
```

**Responsive Testing:**
- Desktop: 1920x1080, 1366x768
- Tablet: 1024x768, 768x1024
- Mobile: 414x896, 375x667 (not primary but good to check)

**Accessibility Testing:**
```javascript
// Use axe-core via Playwright
const results = await page.evaluate(() => {
  return axe.run()
})
// Check for violations
assert(results.violations.length === 0)
```

**Performance Testing:**
- Measure time to first paint
- Check CSS size (should be < 50KB)
- Verify no layout shift on load

**Deliverables:**
1. Screenshot gallery of all states
2. Visual diff reports (before/after improvements)
3. Accessibility audit results
4. Performance metrics
```

---

## Phase 7: Micro-Interactions & Delight

### Prompt for Claude:

```markdown
Add polish and micro-interactions to make the UX delightful without being distracting.

**Subtle Animations:**

1. **Button Hover/Click**:
   - Smooth scale on hover (transform: scale(1.02))
   - Ripple effect on click (like Material Design)
   - Disabled state clearly visible (opacity + cursor)

2. **Chat Messages**:
   - Fade in from bottom when new message arrives
   - Typing indicator with 3 animated dots
   - Smooth scroll to bottom

3. **Status Changes**:
   - Badge color transitions (pending → approved)
   - Checkmark animation when task completes
   - Progress bar fills smoothly (not jumps)

4. **Loading States**:
   - Skeleton screens instead of spinners (show layout)
   - Shimmer effect for loading cards
   - Optimistic UI (show success immediately, undo if fails)

5. **Form Validation**:
   - Shake animation on error
   - Checkmark appears on valid field
   - Error message slides down (not pops in)

**Feedback Mechanisms:**

1. **Success Confirmations**:
   - Toast notification (top-right) with auto-dismiss
   - Confetti animation on request submission (st.balloons() is good but can be better)
   - Sound effect (optional, toggle-able)

2. **Error Handling**:
   - Friendly error messages (not technical jargon)
   - Suggested actions ("Try again" or "Contact support")
   - Error boundaries (don't crash whole app)

3. **Empty States**:
   - Illustrations (simple SVG or emoji)
   - Helpful guidance text
   - Primary CTA clearly visible

**Contextual Help:**

1. **Tooltips**:
   - On hover for icons/abbreviations
   - Keyboard accessible (focus state)
   - Placement smart (above/below based on viewport)

2. **Info Popovers**:
   - "What is feasibility score?" → explanation
   - "Why do I need IRB number?" → context
   - "What is SQL-on-FHIR?" → technical explainer

3. **Onboarding**:
   - First-time user tour (optional, dismissible)
   - Inline hints ("Start by typing your research question")
   - Progress persistence (don't lose work on refresh)

**Keyboard Shortcuts:**

- `Ctrl+/` or `Cmd+/`: Open help
- `Enter`: Send chat message
- `Esc`: Close modals
- Tab navigation through forms
- `Ctrl+K` or `Cmd+K`: Global search (Admin Dashboard)

**CSS Transitions:**
```css
/* Smooth all the things (but not too slow) */
* {
  transition: background-color 0.2s ease,
              color 0.2s ease,
              border-color 0.2s ease,
              transform 0.15s ease,
              opacity 0.2s ease;
}

/* Reduce motion for accessibility */
@media (prefers-reduced-motion: reduce) {
  * {
    transition: none !important;
    animation: none !important;
  }
}
```

**Use Playwright to:**
- Record video of animations
- Test keyboard navigation
- Verify tooltips appear on hover
- Check loading states
- Validate error message display
```

---

## Execution Strategy

### How to Use These Prompts with Claude + Playwright MCP:

1. **Start with Phase 1** (Design System):
   - Give Claude the full prompt
   - Ask it to create the CSS file
   - Use Playwright to screenshot current state
   - Apply new styles
   - Compare before/after

2. **Iterate on Each App** (Phases 2-4):
   - Work on one app at a time
   - Make changes incrementally
   - Test visually with Playwright after each change
   - Get feedback from real users if possible

3. **Unify** (Phase 5):
   - Extract common components
   - Create shared CSS file
   - Refactor all three apps to use shared components

4. **Test Comprehensively** (Phase 6):
   - Set up automated visual regression
   - Run accessibility audits
   - Performance benchmarks

5. **Polish** (Phase 7):
   - Add animations last (easier to remove if too much)
   - Test with real users
   - Iterate based on feedback

### Sample Conversation with Claude:

```
You: Let's start with Phase 1. I need you to create a modern design system for my ResearchFlow application. Here are my three current Streamlit apps:

[Paste researcher_portal.py CSS section]
[Paste admin_dashboard.py CSS section]
[Paste research_notebook.py CSS section]

Based on these, create a unified design system that:
1. Keeps the best parts of the current iOS glass effect
2. Standardizes colors, spacing, typography
3. Is accessible (WCAG AA)
4. Works on desktop and tablet

Use Playwright MCP to screenshot the current state of all three apps first.

Claude: [Uses Playwright to capture screenshots]

I've captured the current state. Now let me analyze the CSS and create a unified design system...

[Claude creates new CSS with design tokens]

Here's the proposed design system. Let me show you before/after comparisons...

[Uses Playwright to apply new CSS and capture screenshots]

You: Great! The spacing looks better but I think the primary blue is too bright. Can you tone it down?

Claude: [Adjusts color, re-tests with Playwright, shows new screenshots]

Is this better?

You: Perfect! Now let's move to Phase 2 and modernize the Researcher Portal chat interface...
```

---

## Key Principles for All Improvements

1. **Healthcare Context**: Professional, credible, trustworthy (not playful)
2. **Information Density**: Show data clearly without overwhelming
3. **Speed**: Fast interactions, no unnecessary animations
4. **Accessibility**: WCAG AA minimum, keyboard navigable
5. **Mobile-Second**: Optimize for desktop, ensure tablet works
6. **Consistency**: Same patterns across all three apps
7. **Progressive Enhancement**: Basic functionality works without JS
8. **Error Prevention**: Validate early, guide users, allow undo
9. **Transparency**: Show what AI is doing, allow override
10. **Delight**: Small touches of polish, but never distracting

---

## Tools & Resources

**Streamlit Styling:**
- Custom CSS via `st.markdown(..., unsafe_allow_html=True)`
- Custom components: https://github.com/streamlit/component-template
- Streamlit theme config: `.streamlit/config.toml`

**Design Inspiration:**
- Linear.app (clean, fast, delightful)
- Notion (information hierarchy, cards)
- Stripe Dashboard (data viz, metrics)
- Vercel Dashboard (status indicators, real-time updates)
- GitHub Pull Requests (approval workflows, diff views)

**Color Palette Tools:**
- https://coolors.co/ (generate palettes)
- https://webaim.org/resources/contrastchecker/ (check accessibility)
- https://color.adobe.com (color harmony)

**Typography:**
- System fonts for performance: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto
- Monospace for code: "SF Mono", "Roboto Mono", "Courier New"

**Playwright MCP:**
- Use for visual testing, screenshots, interaction testing
- Can record videos of user flows
- Accessibility testing with axe-core integration

---

## Expected Outcomes

After completing all phases, you should have:

✅ **Unified Design System**: One CSS file all apps share
✅ **Modern UX**: Chat interfaces, approval workflows, data viz
✅ **Accessibility**: WCAG AA compliant, keyboard navigable
✅ **Visual Consistency**: All three apps feel like one product
✅ **Micro-interactions**: Smooth animations, helpful feedback
✅ **Automated Tests**: Playwright tests for visual regression
✅ **Documentation**: Design system guide with examples

**Estimated Timeline:**
- Phase 1: 2-3 hours
- Phase 2-4: 3-4 hours each (9-12 hours total)
- Phase 5: 2-3 hours
- Phase 6: 2-3 hours
- Phase 7: 3-4 hours

**Total: ~20-25 hours** (spread over multiple sessions with Claude)

---

## Next Steps

1. **Start conversation with Claude**: Copy Phase 1 prompt
2. **Use Playwright MCP**: Screenshot current state
3. **Iterate incrementally**: Don't try to do everything at once
4. **Test with real users**: Get feedback early and often
5. **Document as you go**: Keep design decisions recorded
6. **Share progress**: Update your LinkedIn post with before/after screenshots!

Good luck! 🚀
